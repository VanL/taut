"""POSIX PTY lifecycle backend for the universal adapter."""

from __future__ import annotations

import errno
import fcntl
import logging
import os
import pty
import queue
import select
import signal
import struct
import sys
import termios
import threading
import time
import tty
from collections.abc import Iterator, Mapping

from taut_summon._adapter import (
    ActivityEvent,
    AdapterError,
    AdapterEvent,
    AdapterExitedError,
    ExitEvent,
)
from taut_summon._process_domain_posix import ProcessDomain, ProcessIO, spawn_process
from taut_summon._pty import (
    _DEFAULT_DETACH_CHORD,
    _OUTPUT_ACTIVITY_WINDOW_SECONDS,
    _TTY_RESET,
    PtySpec,
    _TerminalState,
)

logger = logging.getLogger("taut_summon.pty")


def spawn_posix_pty(
    *, spec: PtySpec, env: Mapping[str, str], terminal: _TerminalState
) -> PosixPtyHandle:
    master_fd, slave_fd = pty.openpty()
    try:
        _set_winsize(slave_fd, spec.rows, spec.cols)
        _set_nonblocking(master_fd)
        spawned = spawn_process(
            list(spec.argv),
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            env=env,
            close_fds=True,
        )
    except Exception as exc:
        try:
            os.close(master_fd)
        except OSError as cleanup_exc:
            exc.add_note(f"PTY master cleanup also failed: {cleanup_exc}")
        raise AdapterError(f"failed to spawn PTY harness: {exc}") from exc
    finally:
        try:
            os.close(slave_fd)
        except OSError:
            pass
    return PosixPtyHandle(
        spawned.process,
        domain=spawned.domain,
        master_fd=master_fd,
        terminal=terminal,
        quiet_ms=spec.quiet_ms,
        max_settle_s=spec.max_settle_s,
    )


class PosixPtyHandle:
    """Live PTY child; satisfies ``AdapterHandle`` for [SUM-7.4]."""

    def __init__(
        self,
        proc: ProcessIO,
        *,
        domain: ProcessDomain,
        master_fd: int,
        terminal: _TerminalState | None = None,
        rows: int = 24,
        cols: int = 80,
        stall_s: float = 10.0,
        quiet_ms: int,
        max_settle_s: float,
    ) -> None:
        self._proc = proc
        self._domain = domain
        self._master_fd = master_fd
        self._quiet_s = quiet_ms / 1000.0
        self._max_settle_s = max_settle_s
        self._terminal = terminal or _TerminalState(
            rows=rows, cols=cols, stall_s=stall_s
        )
        self._lifecycle_lock = threading.RLock()
        self._events_lock = threading.Lock()
        self._normal_writer_lock = threading.Lock()
        self._events_claimed = False
        self._write_epoch = 0
        self._retired = False
        self._close_condition = threading.Condition(self._lifecycle_lock)
        self._active_operations: set[object] = set()
        self._close_state = "open"
        self._close_error: str | None = None
        self._reader_started = False
        self._reader_started_event = threading.Event()
        self._settle_wake = threading.Event()
        self._master_closed = False
        self._exit_emitted = False
        self._pending_events: queue.SimpleQueue[AdapterEvent] = queue.SimpleQueue()

    @property
    def pid(self) -> int:
        return self._proc.pid

    @property
    def last_output_ts(self) -> float:
        return self._terminal.last_output_ts

    def mark_awaiting_onboarding(self) -> None:
        self._terminal.mark_awaiting_onboarding()

    @property
    def input_prompt_observed(self) -> bool:
        """Whether a bracketed-paste enable was observed since spawn.

        Latched: an alt-screen exit that disables paste mode does not
        unconfirm a prompt that was already presented ([SUM-7.4]).
        """
        return self._terminal.input_prompt_observed

    def output_tail(self) -> str:
        return self._terminal.output_tail()

    def status_fields(self) -> dict[str, str]:
        return self._terminal.status_fields()

    @property
    def _bracketed_paste(self) -> bool:
        return self._terminal.bracketed_paste

    def _observe_output(self, data: bytes) -> None:
        for reply in self._terminal.observe_output(data):
            self._write_best_effort(reply)
        self._settle_wake.set()

    def wait_until_quiet(self) -> None:
        deadline = time.monotonic() + self._max_settle_s
        while not self._reader_started_event.is_set():
            with self._lifecycle_lock:
                if self._retired or self._master_closed:
                    return
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            self._settle_wake.wait(timeout=min(0.05, remaining))
            self._settle_wake.clear()
        while True:
            with self._lifecycle_lock:
                if self._retired or self._master_closed:
                    return
            now = time.monotonic()
            self._terminal.mark_stalled(now=now)
            if (
                self._terminal.seen_output
                and now - self._terminal.last_output_ts >= self._quiet_s
                and not self._terminal.unhandled_query_pending
            ):
                return
            remaining = deadline - now
            if remaining <= 0:
                return
            self._settle_wake.wait(timeout=min(0.05, remaining))
            self._settle_wake.clear()

    def attach(  # noqa: C901 approved [DOM-10.2.1] [RUFF-SUP-030] exception
        self,
        *,
        wake: threading.Event,
        shutdown: threading.Event,
        input_fd: int = 0,
        output_fd: int = 1,
        detach_chord: bytes = _DEFAULT_DETACH_CHORD,
    ) -> str:
        """Bridge a human tty to the harness until detach, EOF, or shutdown."""

        saved = termios.tcgetattr(input_fd)
        tty.setraw(input_fd)
        done = threading.Event()
        pipe_r, pipe_w = os.pipe()

        def _forward_wake() -> None:
            try:
                while not done.is_set():
                    if wake.wait(timeout=0.05) or done.is_set():
                        try:
                            os.write(pipe_w, b"x")
                        except (BrokenPipeError, OSError):
                            pass
                        return
            finally:
                pass

        forwarder = threading.Thread(
            target=_forward_wake, daemon=True, name="taut-summon-attach-waker"
        )
        forwarder.start()
        matcher = self._terminal.detach_matcher(detach_chord)
        result = "eof"
        try:
            while True:
                ready, _, _ = select.select(
                    [input_fd, self._master_fd, pipe_r], [], [], 0.1
                )
                if pipe_r in ready:
                    if shutdown.is_set():
                        result = "shutdown"
                        break
                    os.read(pipe_r, 4096)
                if self._master_fd in ready:
                    try:
                        data = os.read(self._master_fd, 4096)
                    except BlockingIOError:
                        continue
                    except OSError:
                        result = "eof"
                        break
                    if not data:
                        result = "eof"
                        break
                    replies = self._terminal.observe_output(data, answer_queries=False)
                    for reply in replies:
                        self._write_best_effort(reply)
                    self._settle_wake.set()
                    os.write(output_fd, data)
                if input_fd in ready:
                    data = os.read(input_fd, 4096)
                    if not data:
                        result = "eof"
                        break
                    forward, detached = matcher.feed(data)
                    if forward:
                        self._write_all(forward)
                    if detached:
                        result = "detached"
                        break
                if self._domain.observe_leader_exit() is not None:
                    result = "eof"
                    break
        finally:
            done.set()
            forwarder.join(timeout=1.0)
            for fd in (pipe_r, pipe_w):
                try:
                    os.close(fd)
                except OSError:
                    pass
            try:
                os.write(output_fd, _TTY_RESET)
            finally:
                termios.tcsetattr(input_fd, termios.TCSADRAIN, saved)
        return result

    def inject(self, text: str) -> None:
        self._write_all(self._terminal.encode_injection(text))
        self._pending_events.put(ActivityEvent(description="inject"))

    def events(self) -> Iterator[AdapterEvent]:
        with self._events_lock:
            if self._events_claimed:
                raise AdapterError(
                    "events() already has a consumer; the PTY stream is single-consumer"
                )
            self._events_claimed = True
        return self._event_stream()

    def interrupt(self) -> None:
        operation: object | None = None
        interrupt_fd: int | None = None
        with self._close_condition:
            if self._retired or self._master_closed:
                return
            operation = self._register_operation_unlocked()
            self._write_epoch += 1
            try:
                interrupt_fd = os.dup(self._master_fd)
            except OSError:
                interrupt_fd = None
        try:
            wrote_interrupt = self._write_interrupt_fd_best_effort(interrupt_fd)
            if not wrote_interrupt:
                self._signal_process_group(signal.SIGTERM)
        finally:
            if interrupt_fd is not None:
                self._close_operation_fd(interrupt_fd)
            assert operation is not None
            self._release_operation(operation)

    def request_close(self) -> None:
        operation: object | None = None
        interrupt_fd: int | None = None
        with self._close_condition:
            if self._close_state != "open":
                return
            self._close_state = "close_requested"
            self._retired = True
            self._write_epoch += 1
            self._settle_wake.set()
            if not self._master_closed:
                operation = self._register_operation_unlocked()
                try:
                    interrupt_fd = os.dup(self._master_fd)
                except OSError:
                    interrupt_fd = None

        if operation is None:
            return
        try:
            wrote_interrupt = self._write_interrupt_fd_best_effort(interrupt_fd)
            if not wrote_interrupt:
                self._signal_process_group(signal.SIGTERM)
        finally:
            if interrupt_fd is not None:
                self._close_operation_fd(interrupt_fd)
            self._release_operation(operation)

    def close(self) -> None:
        primary_error = sys.exception()
        self.request_close()
        owns_close = False
        with self._close_condition:
            if self._close_state == "closed":
                close_error = self._close_error
            elif self._close_state == "closing":
                self._close_condition.wait_for(lambda: self._close_state == "closed")
                close_error = self._close_error
            else:
                assert self._close_state == "close_requested"
                self._close_state = "closing"
                owns_close = True
                close_error = None

        if not owns_close:
            self._raise_close_error(close_error, primary_error)
            return

        failure: AdapterError | None = None
        try:
            self._wait_for_active_operations()
            self._domain.finalize()
        except AdapterError as exc:
            failure = exc
        except Exception as exc:  # pragma: no cover  # noqa: BLE001 approved [DOM-10.2.1] [RUFF-SUP-067] exception
            failure = AdapterError(f"PTY child cleanup failed: {exc}")
            failure.__cause__ = exc
        finally:
            with self._close_condition:
                try:
                    if (
                        failure is not None or not self._reader_started
                    ) and not self._master_closed:
                        self._close_master_unlocked()
                except OSError as exc:
                    cleanup_failure = AdapterError(f"PTY master cleanup failed: {exc}")
                    cleanup_failure.__cause__ = exc
                    if failure is None:
                        failure = cleanup_failure
                    else:
                        failure.add_note(str(cleanup_failure))
                close_error = str(failure) if failure is not None else None
                self._close_error = close_error
                self._close_state = "closed"
                self._close_condition.notify_all()

        self._raise_close_error(close_error, primary_error)

    @staticmethod
    def _raise_close_error(
        close_error: str | None, primary_error: BaseException | None
    ) -> None:
        if close_error is None:
            return
        if primary_error is not None:
            primary_error.add_note(f"adapter cleanup also failed: {close_error}")
            return
        raise AdapterError(close_error)

    def _event_stream(self) -> Iterator[AdapterEvent]:  # noqa: C901 approved [DOM-10.2.1] [RUFF-SUP-031] exception
        with self._lifecycle_lock:
            self._reader_started = True
            self._reader_started_event.set()
            self._settle_wake.set()
            if self._master_closed:
                yield from self._emit_exit()
                return
        self._pending_events.put(ActivityEvent(description="spawn"))
        last_activity = 0.0
        try:
            while True:
                yield from self._drain_pending()
                try:
                    ready, _, _ = select.select([self._master_fd], [], [], 0.05)
                except (OSError, ValueError):
                    break
                if not ready:
                    self._maybe_mark_stall()
                    if self._domain.observe_leader_exit() is not None:
                        break
                    continue
                try:
                    data = os.read(self._master_fd, 4096)
                except BlockingIOError:
                    if self._domain.observe_leader_exit() is not None:
                        break
                    continue
                except OSError:
                    break
                if not data:
                    break
                replies = self._terminal.observe_output(data)
                self._settle_wake.set()
                leader_exited = self._domain.observe_leader_exit() is not None
                for reply in replies:
                    self._write_best_effort(reply)
                now = time.monotonic()
                if now - last_activity >= _OUTPUT_ACTIVITY_WINDOW_SECONDS:
                    last_activity = now
                    yield ActivityEvent(description="output")
                if leader_exited:
                    break
        finally:
            with self._lifecycle_lock:
                if not self._master_closed:
                    self._close_master_unlocked()
            yield from self._emit_exit()

    def _drain_pending(self) -> Iterator[AdapterEvent]:
        while True:
            try:
                yield self._pending_events.get_nowait()
            except queue.Empty:
                return

    def _maybe_mark_stall(self) -> None:
        self._terminal.mark_stalled()

    def _emit_exit(self) -> Iterator[AdapterEvent]:
        if self._exit_emitted:
            return
        self._exit_emitted = True
        with self._close_condition:
            if self._close_state == "closing":
                self._close_condition.wait_for(lambda: self._close_state == "closed")
            close_error = self._close_error if self._close_state == "closed" else None
        if close_error is not None:
            raise AdapterError(close_error)
        self._wait_for_active_operations()
        returncode = self._domain.wait_for_leader_exit(0.3)
        if returncode is None:
            raise AdapterError("PTY stream ended before provider leader exit")
        yield ExitEvent(returncode=returncode)

    def _write_all(self, data: bytes) -> None:  # noqa: C901 approved [DOM-10.2.1] [RUFF-SUP-032] exception
        offset = 0
        with self._lifecycle_lock:
            if self._master_closed:
                raise AdapterExitedError("PTY master is closed")
            if self._retired:
                raise AdapterError("PTY master is closed")
            write_epoch = self._write_epoch
        with self._normal_writer_lock:
            operation: object | None = None
            fd: int | None = None
            try:
                with self._close_condition:
                    self._validate_write_unlocked(write_epoch)
                    operation = self._register_operation_unlocked()
                    try:
                        fd = os.dup(self._master_fd)
                    except OSError as exc:
                        self._discard_operation_unlocked(operation)
                        operation = None
                        raise AdapterError(f"PTY write fd lease failed: {exc}") from exc
                while offset < len(data):
                    with self._lifecycle_lock:
                        self._validate_write_unlocked(write_epoch)
                    try:
                        written = os.write(fd, data[offset:])
                    except BlockingIOError:
                        written = None
                    except OSError as exc:
                        with self._lifecycle_lock:
                            self._validate_write_unlocked(write_epoch)
                        raise AdapterError(f"PTY write failed: {exc}") from exc
                    with self._lifecycle_lock:
                        self._validate_write_unlocked(write_epoch)
                    if written is None:
                        try:
                            select.select([], [fd], [], 0.05)
                        except (OSError, ValueError) as exc:
                            with self._lifecycle_lock:
                                self._validate_write_unlocked(write_epoch)
                            raise AdapterError(f"PTY write wait failed: {exc}") from exc
                        with self._lifecycle_lock:
                            self._validate_write_unlocked(write_epoch)
                        continue
                    if written <= 0:
                        raise AdapterError("PTY write wrote no bytes")
                    offset += written
            finally:
                if fd is not None:
                    self._close_operation_fd(fd)
                if operation is not None:
                    self._retire_write_operation(operation, write_epoch)

    def _validate_write_unlocked(self, write_epoch: int) -> None:
        if write_epoch != self._write_epoch:
            raise AdapterError("PTY write interrupted")
        if self._master_closed:
            raise AdapterExitedError("PTY master is closed")
        if self._retired:
            raise AdapterError("PTY master is closed")
        if self._domain.observe_leader_exit() is not None:
            raise AdapterExitedError("PTY child exited during write")

    def _write_best_effort(self, data: bytes) -> None:
        try:
            self._write_all(data)
        except AdapterError:
            pass

    @staticmethod
    def _write_interrupt_fd_best_effort(fd: int | None) -> bool:
        if fd is None:
            return False
        try:
            os.write(fd, b"\x03")
            return True
        except BlockingIOError:
            return False
        except OSError:
            return False

    @staticmethod
    def _close_operation_fd(fd: int) -> None:
        try:
            os.close(fd)
        except OSError:
            logger.debug("PTY operation fd cleanup failed", exc_info=True)

    def _register_operation_unlocked(self) -> object:
        operation = object()
        self._active_operations.add(operation)
        return operation

    def _discard_operation_unlocked(self, operation: object) -> None:
        self._active_operations.discard(operation)
        self._close_condition.notify_all()

    def _release_operation(self, operation: object) -> None:
        with self._close_condition:
            self._discard_operation_unlocked(operation)

    def _retire_write_operation(self, operation: object, write_epoch: int) -> None:
        with self._close_condition:
            try:
                if write_epoch != self._write_epoch:
                    raise AdapterError("PTY write interrupted")
            finally:
                self._discard_operation_unlocked(operation)

    def _wait_for_active_operations(self) -> None:
        with self._close_condition:
            self._close_condition.wait_for(lambda: not self._active_operations)

    def _signal_process_group(self, sig: signal.Signals) -> None:
        try:
            self._domain.signal_group(sig)
        except AdapterError:
            logger.debug("PTY process-group interrupt failed", exc_info=True)

    def _close_master_unlocked(self) -> None:
        if self._master_closed:
            return
        self._master_closed = True
        self._settle_wake.set()
        try:
            os.close(self._master_fd)
        except OSError as exc:
            if exc.errno != errno.EBADF:
                raise


def _set_winsize(fd: int, rows: int, cols: int) -> None:
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))


def _set_nonblocking(fd: int) -> None:
    flags = fcntl.fcntl(fd, fcntl.F_GETFL)
    fcntl.fcntl(fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)
