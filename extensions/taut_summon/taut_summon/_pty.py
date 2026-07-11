"""Universal interactive PTY adapter ([SUM-7.4]).

The adapter hosts a harness in its normal full-screen interactive mode. It
does not parse the screen as speech; the master reader exists only for coarse
liveness, finite terminal-query replies, diagnostics, and clean lifecycle
ownership.
"""

from __future__ import annotations

import errno
import fcntl
import logging
import math
import os
import pty
import queue
import select
import signal
import struct
import subprocess
import sys
import termios
import threading
import time
import tty
from collections.abc import Iterator, Mapping
from dataclasses import dataclass

from taut_summon._adapter import (
    ActivityEvent,
    AdapterError,
    AdapterEvent,
    ExitEvent,
)

logger = logging.getLogger("taut_summon.pty")

ESC = b"\x1b"
BEL = b"\x07"
ST = ESC + b"\\"

_DEFAULT_ROWS = 24
_DEFAULT_COLS = 80
_OUTPUT_ACTIVITY_WINDOW_SECONDS = 10.0
_DEFAULT_DETACH_CHORD = b"\x1c\x1c"
_TTY_RESET = (
    b"\x18"
    + ST
    + b"\x1b[?1049l\x1b[?47l\x1b[?1047l"
    + b"\x1b[?25h\x1b[r\x1b[0m\x1b[?7h\x1b[?2026l\x1b[?1007l"
    + b"\x1b[?1l\x1b>"
    + b"\x1b[?1004l"
    + b"\x1b[?1000l\x1b[?1002l\x1b[?1003l\x1b[?1005l"
    + b"\x1b[?1006l\x1b[?1015l"
    + b"\x1b[?2004l\x1b[<u"
)


@dataclass(frozen=True, slots=True)
class PtySpec:
    """One validated launch shape.

    Dimensions must fit the unsigned-short PTY winsize fields. Stall and
    settle deadlines are finite and positive; a zero quiet interval is valid.
    """

    name: str
    argv: tuple[str, ...]
    rows: int = _DEFAULT_ROWS
    cols: int = _DEFAULT_COLS
    stall_s: float = 10.0
    quiet_ms: int = 500
    max_settle_s: float = 10.0


class PtyAdapter:
    """Spawn an interactive harness on a pseudo-terminal."""

    supports_terminal_mode: bool = False
    supports_attach: bool = True
    orientation_via_inject: bool = True
    emits_session_events: bool = False

    def __init__(self, spec: PtySpec | None = None) -> None:
        self._spec = spec or PtySpec(name="pty", argv=(os.environ.get("SHELL", "sh"),))
        _validate_spec(self._spec)
        self.name = self._spec.name

    @property
    def argv(self) -> tuple[str, ...]:
        return self._spec.argv

    def spawn(
        self,
        *,
        session_id: str | None,
        system_prompt: str,
        env: Mapping[str, str],
    ) -> PtyHandle:
        del session_id, system_prompt
        master_fd, slave_fd = pty.openpty()
        child_env = dict(os.environ)
        child_env.update(env)
        child_env["TERM"] = "xterm-256color"
        child_env.setdefault("COLORTERM", "truecolor")
        try:
            _set_winsize(slave_fd, self._spec.rows, self._spec.cols)
            _set_nonblocking(master_fd)
            proc = subprocess.Popen(
                list(self._spec.argv),
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                env=child_env,
                close_fds=True,
                start_new_session=True,
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
        return PtyHandle(
            proc,
            master_fd=master_fd,
            rows=self._spec.rows,
            cols=self._spec.cols,
            stall_s=self._spec.stall_s,
            quiet_ms=self._spec.quiet_ms,
            max_settle_s=self._spec.max_settle_s,
        )


class PtyHandle:
    """Live PTY child; satisfies ``AdapterHandle`` for [SUM-7.4]."""

    def __init__(
        self,
        proc: subprocess.Popen[bytes],
        *,
        master_fd: int,
        rows: int,
        cols: int,
        stall_s: float,
        quiet_ms: int,
        max_settle_s: float,
    ) -> None:
        self._proc = proc
        self._master_fd = master_fd
        self._rows = rows
        self._cols = cols
        self._stall_s = stall_s
        self._quiet_s = quiet_ms / 1000.0
        self._max_settle_s = max_settle_s
        self._responder = _TerminalResponder(rows=rows, cols=cols)
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
        self._master_closed = False
        self._exit_emitted = False
        self._bracketed_paste = False
        self._last_output_ts = time.monotonic()
        self._seen_output = threading.Event()
        self._awaiting_query: str | None = None
        self._awaiting_onboarding = False
        self._pending_events: queue.SimpleQueue[AdapterEvent] = queue.SimpleQueue()

    @property
    def session_id(self) -> str | None:
        return None

    @property
    def pid(self) -> int:
        return self._proc.pid

    @property
    def last_output_ts(self) -> float:
        return self._last_output_ts

    def mark_awaiting_onboarding(self) -> None:
        self._awaiting_onboarding = True

    def status_fields(self) -> dict[str, str]:
        fields: dict[str, str] = {}
        if self._awaiting_query is not None:
            fields["awaiting_query"] = self._awaiting_query
        if self._awaiting_onboarding:
            fields["awaiting_onboarding"] = "true"
        return fields

    def wait_until_quiet(self) -> None:
        self._reader_started_event.wait(timeout=self._max_settle_s)
        deadline = time.monotonic() + self._max_settle_s
        while time.monotonic() < deadline:
            if (
                self._seen_output.is_set()
                and time.monotonic() - self._last_output_ts >= self._quiet_s
            ):
                return
            time.sleep(0.05)

    def attach(
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
        matcher = _DetachChordMatcher(detach_chord)
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
        sanitized = _sanitize_for_pty(text)
        if self._bracketed_paste:
            payload = ESC + b"[200~" + sanitized.encode() + ESC + b"[201~\r"
        else:
            payload = sanitized.replace("\n", " ").encode() + b"\r"
        self._write_all(payload)
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

    def close(self) -> None:
        primary_error = sys.exception()
        owns_close = False
        close_operation: object | None = None
        close_interrupt_fd: int | None = None
        with self._close_condition:
            if self._close_state == "closed":
                close_error = self._close_error
            elif self._close_state == "closing":
                self._close_condition.wait_for(lambda: self._close_state == "closed")
                close_error = self._close_error
            else:
                self._close_state = "closing"
                if not self._master_closed:
                    close_operation = self._register_operation_unlocked()
                    try:
                        close_interrupt_fd = os.dup(self._master_fd)
                    except OSError:
                        self._discard_operation_unlocked(close_operation)
                        close_operation = None
                self._retired = True
                self._write_epoch += 1
                owns_close = True
                close_error = None

        if not owns_close:
            self._raise_close_error(close_error, primary_error)
            return

        failure: AdapterError | None = None
        try:
            self._write_interrupt_fd_best_effort(close_interrupt_fd)
            if close_interrupt_fd is not None:
                self._close_operation_fd(close_interrupt_fd)
                close_interrupt_fd = None
            if close_operation is not None:
                self._release_operation(close_operation)
                close_operation = None
            self._wait_for_active_operations()
            self._reap_child()
        except AdapterError as exc:
            failure = exc
        except Exception as exc:  # pragma: no cover - defensive Popen boundary
            failure = AdapterError(f"PTY child cleanup failed: {exc}")
            failure.__cause__ = exc
        finally:
            if close_interrupt_fd is not None:
                self._close_operation_fd(close_interrupt_fd)
            if close_operation is not None:
                self._release_operation(close_operation)
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

    def _event_stream(self) -> Iterator[AdapterEvent]:
        with self._lifecycle_lock:
            self._reader_started = True
            self._last_output_ts = time.monotonic()
            self._reader_started_event.set()
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
                    if self._proc.poll() is not None:
                        break
                    continue
                try:
                    data = os.read(self._master_fd, 4096)
                except BlockingIOError:
                    continue
                except OSError:
                    break
                if not data:
                    break
                self._last_output_ts = time.monotonic()
                self._seen_output.set()
                replies = self._responder.feed(data)
                self._bracketed_paste = self._responder.bracketed_paste
                for reply in replies:
                    self._write_best_effort(reply)
                now = time.monotonic()
                if now - last_activity >= _OUTPUT_ACTIVITY_WINDOW_SECONDS:
                    last_activity = now
                    yield ActivityEvent(description="output")
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
        outstanding = self._responder.outstanding_query
        if outstanding is None or self._awaiting_query is not None:
            return
        if time.monotonic() - self._last_output_ts >= self._stall_s:
            self._awaiting_query = outstanding
            logger.warning(
                "PTY harness is awaiting an unhandled terminal report query: %s",
                outstanding,
            )

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
        if self._proc.poll() is None:
            self._reap_child()
        returncode = self._proc.returncode
        yield ExitEvent(returncode=0 if returncode is None else int(returncode))

    def _write_all(self, data: bytes) -> None:
        offset = 0
        with self._lifecycle_lock:
            if self._retired or self._master_closed:
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
        if self._retired or self._master_closed:
            raise AdapterError("PTY master is closed")
        if self._proc.poll() is not None:
            raise AdapterError("PTY child exited during write")

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
        if self._proc.poll() is not None:
            return
        try:
            os.killpg(self._proc.pid, sig)
        except ProcessLookupError:
            return
        except OSError:
            try:
                self._proc.send_signal(sig)
            except OSError:
                return

    def _reap_child(self) -> None:
        if self._proc.poll() is not None:
            return
        last_timeout: subprocess.TimeoutExpired | None = None
        try:
            self._proc.wait(timeout=0.3)
            return
        except subprocess.TimeoutExpired as exc:
            last_timeout = exc
        for sig, timeout in ((signal.SIGTERM, 2.0), (signal.SIGKILL, 2.0)):
            if self._proc.poll() is not None:
                return
            self._signal_process_group(sig)
            try:
                self._proc.wait(timeout=timeout)
                return
            except subprocess.TimeoutExpired as exc:
                last_timeout = exc
                continue
        raise AdapterError("PTY child did not exit after SIGKILL") from last_timeout

    def _close_master_unlocked(self) -> None:
        if self._master_closed:
            return
        self._master_closed = True
        try:
            os.close(self._master_fd)
        except OSError as exc:
            if exc.errno != errno.EBADF:
                raise


def _validate_spec(spec: PtySpec) -> None:
    """Validate the one central PTY construction boundary."""

    if not spec.argv or not all(isinstance(item, str) and item for item in spec.argv):
        raise AdapterError(
            "argv (TAUT_SUMMON_PTY_ARGV) must be a non-empty string sequence"
        )
    for field, env_name, dimension_value in (
        ("rows", "TAUT_SUMMON_PTY_ROWS", spec.rows),
        ("cols", "TAUT_SUMMON_PTY_COLS", spec.cols),
    ):
        if (
            isinstance(dimension_value, bool)
            or not isinstance(dimension_value, int)
            or not 1 <= dimension_value <= 65_535
        ):
            raise AdapterError(f"{field} ({env_name}) must be between 1 and 65535")
    for field, env_name, timing_value in (
        ("stall_s", "TAUT_SUMMON_PTY_STALL_S", spec.stall_s),
        ("max_settle_s", "TAUT_SUMMON_PTY_MAX_SETTLE_S", spec.max_settle_s),
    ):
        if isinstance(timing_value, bool) or not isinstance(timing_value, (int, float)):
            raise AdapterError(f"{field} ({env_name}) must be a finite positive number")
        try:
            finite_timing = float(timing_value)
        except OverflowError as exc:
            raise AdapterError(
                f"{field} ({env_name}) must be a finite positive number"
            ) from exc
        if not math.isfinite(finite_timing) or finite_timing <= 0:
            raise AdapterError(f"{field} ({env_name}) must be a finite positive number")
    if (
        isinstance(spec.quiet_ms, bool)
        or not isinstance(spec.quiet_ms, int)
        or spec.quiet_ms < 0
    ):
        raise AdapterError(
            "quiet_ms (TAUT_SUMMON_PTY_QUIET_MS) must be a non-negative integer"
        )
    try:
        quiet_seconds = spec.quiet_ms / 1000.0
    except OverflowError as exc:
        raise AdapterError(
            "quiet_ms (TAUT_SUMMON_PTY_QUIET_MS) must produce finite seconds"
        ) from exc
    if not math.isfinite(quiet_seconds):
        raise AdapterError(
            "quiet_ms (TAUT_SUMMON_PTY_QUIET_MS) must produce finite seconds"
        )


class _TerminalResponder:
    def __init__(self, *, rows: int, cols: int) -> None:
        self._rows = rows
        self._cols = cols
        self._row = 1
        self._col = 1
        self._buffer = b""
        self._outstanding_query: str | None = None
        self.bracketed_paste = False

    @property
    def outstanding_query(self) -> str | None:
        return self._outstanding_query

    def feed(self, data: bytes) -> list[bytes]:
        replies: list[bytes] = []
        self._buffer += data
        while True:
            start = self._buffer.find(ESC)
            if start < 0:
                self._buffer = b""
                return replies
            if start > 0:
                self._buffer = self._buffer[start:]
            if len(self._buffer) < 2:
                return replies
            introducer = self._buffer[1:2]
            if introducer == b"[":
                parsed = self._take_csi()
            elif introducer == b"]":
                parsed = self._take_osc()
            else:
                parsed = self._buffer[:2]
                self._buffer = self._buffer[2:]
            if parsed is None:
                return replies
            reply = self._handle_sequence(parsed)
            if reply:
                replies.append(reply)

    def _take_csi(self) -> bytes | None:
        for index in range(2, len(self._buffer)):
            byte = self._buffer[index]
            if 0x40 <= byte <= 0x7E:
                seq = self._buffer[: index + 1]
                self._buffer = self._buffer[index + 1 :]
                return seq
        return None

    def _take_osc(self) -> bytes | None:
        bel = self._buffer.find(BEL, 2)
        st = self._buffer.find(ST, 2)
        ends = [pos + 1 for pos in (bel,) if pos >= 0]
        ends.extend(pos + 2 for pos in (st,) if pos >= 0)
        if not ends:
            return None
        end = min(ends)
        seq = self._buffer[:end]
        self._buffer = self._buffer[end:]
        return seq

    def _handle_sequence(self, seq: bytes) -> bytes | None:
        if seq.startswith(ESC + b"["):
            return self._handle_csi(seq)
        if seq.startswith(ESC + b"]"):
            return self._handle_osc(seq)
        return None

    def _handle_csi(self, seq: bytes) -> bytes | None:
        body = seq[2:-1]
        final = seq[-1:]
        self._track_cursor(body, final)
        self._track_modes(body, final)
        if final == b"n":
            if body == b"6":
                return f"\x1b[{self._row};{self._col}R".encode()
            if body == b"5":
                return b"\x1b[0n"
            if body == b"?996":
                return b"\x1b[?997;1n"
            self._mark_report(seq)
            return None
        if final == b"c":
            if body in (b"", b"0"):
                return b"\x1b[?1;2c"
            if body == b">":
                return b"\x1b[>0;0;0c"
            self._mark_report(seq)
            return None
        if final == b"p" and body.startswith(b"?") and body.endswith(b"$"):
            mode = body[1:-1] or b"0"
            return b"\x1b[?" + mode + b";0$y"
        if final == b"q" and body.startswith(b">"):
            return b"\x1bP>|taut-summon(0)\x1b\\"
        if final == b"q" and body.endswith(b" "):
            return None
        if final == b"u" and body == b"?":
            return b"\x1b[?0u"
        if final == b"u" and body.startswith(b">"):
            return None
        if final in (b"p", b"q", b"u"):
            self._mark_report(seq)
        return None

    def _handle_osc(self, seq: bytes) -> bytes | None:
        content = seq[2:]
        if content.endswith(BEL):
            content = content[:-1]
        elif content.endswith(ST):
            content = content[:-2]
        if content == b"10;?":
            return b"\x1b]10;rgb:ffff/ffff/ffff\x1b\\"
        if content == b"11;?":
            return b"\x1b]11;rgb:0000/0000/0000\x1b\\"
        if content.startswith((b"10;?", b"11;?")):
            self._mark_report(seq)
        return None

    def _track_cursor(self, body: bytes, final: bytes) -> None:
        if final in (b"H", b"f"):
            parts = body.split(b";")
            row = _parse_int(parts[0] if parts else b"", default=1)
            col = _parse_int(parts[1] if len(parts) > 1 else b"", default=1)
            self._row, self._col = self._clamp(row, col)
        elif final == b"C":
            self._row, self._col = self._clamp(
                self._row, self._col + _parse_int(body, default=1)
            )
        elif final == b"B":
            self._row, self._col = self._clamp(
                self._row + _parse_int(body, default=1), self._col
            )
        elif final == b"D":
            self._row, self._col = self._clamp(
                self._row, self._col - _parse_int(body, default=1)
            )
        elif final == b"A":
            self._row, self._col = self._clamp(
                self._row - _parse_int(body, default=1), self._col
            )

    def _track_modes(self, body: bytes, final: bytes) -> None:
        if b"?2004" not in body:
            return
        if final == b"h":
            self.bracketed_paste = True
        elif final == b"l":
            self.bracketed_paste = False

    def _clamp(self, row: int, col: int) -> tuple[int, int]:
        return max(1, min(self._rows, row)), max(1, min(self._cols, col))

    def _mark_report(self, seq: bytes) -> None:
        self._outstanding_query = _printable_sequence(seq)


def _set_winsize(fd: int, rows: int, cols: int) -> None:
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))


def _set_nonblocking(fd: int) -> None:
    flags = fcntl.fcntl(fd, fcntl.F_GETFL)
    fcntl.fcntl(fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)


def _parse_int(raw: bytes, *, default: int) -> int:
    try:
        return int(raw or str(default).encode())
    except ValueError:
        return default


def _printable_sequence(seq: bytes) -> str:
    text = seq.decode("latin1", errors="replace")
    return text.replace("\x1b", "")


def _sanitize_for_pty(text: str) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    out: list[str] = []
    for char in normalized:
        code = ord(char)
        if char == "\t":
            out.append(" ")
        elif char == "\n":
            out.append(char)
        elif char == "\x1b" or code == 0x7F or code < 0x20:
            continue
        else:
            out.append(char)
    return "".join(out)


class _DetachChordMatcher:
    def __init__(self, chord: bytes) -> None:
        if not chord or chord.startswith(ESC):
            raise AdapterError("detach chord must be non-empty and must not start ESC")
        self._chord = chord
        self._buffer = b""

    def feed(self, data: bytes) -> tuple[bytes, bool]:
        out = bytearray()
        for byte in data:
            candidate = self._buffer + bytes([byte])
            if self._chord.startswith(candidate):
                self._buffer = candidate
                if candidate == self._chord:
                    self._buffer = b""
                    return bytes(out), True
                continue
            if self._buffer:
                out.extend(self._buffer)
                self._buffer = b""
            out.append(byte)
        return bytes(out), False
