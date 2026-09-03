"""Windows ConPTY process and channel owner for the universal PTY adapter."""

from __future__ import annotations

import ctypes
import logging
import queue
import subprocess
import threading
import time
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from functools import partial
from typing import Any, Protocol

from taut_summon._adapter import (
    ActivityEvent,
    AdapterError,
    AdapterEvent,
    ExitEvent,
)
from taut_summon._win32_io import (
    COORD,
    CREATE_SUSPENDED,
    CREATE_UNICODE_ENVIRONMENT,
    DWORD,
    DWORD_FAILURE,
    ERROR_BROKEN_PIPE,
    ERROR_INVALID_HANDLE,
    ERROR_NO_DATA,
    ERROR_OPERATION_ABORTED,
    ERROR_PIPE_NOT_CONNECTED,
    EXTENDED_STARTUPINFO_PRESENT,
    HANDLE,
    HPCON,
    LPVOID,
    PROC_THREAD_ATTRIBUTE_PSEUDOCONSOLE,
    PROCESS_INFORMATION,
    SIZE_T,
    STARTF_USESTDHANDLES,
    STARTUPINFOEXW,
    STILL_ACTIVE,
    WAIT_OBJECT_0,
    ConsoleLease,
    NativeApi,
    Win32IoError,
)

_CLEAN_PIPE_END = frozenset(
    {ERROR_BROKEN_PIPE, ERROR_NO_DATA, ERROR_PIPE_NOT_CONNECTED}
)
_ACTIVITY_SECONDS = 10.0
_CLOSE_TIMEOUT_S = 10.0
_DETACH_RESET = b"\x1b[?1049l\x1b[?25h\x1b[0m\x1b[?2004l"
logger = logging.getLogger("taut_summon.pty_windows")


class TerminalIntegration(Protocol):
    """Common terminal semantics supplied by the platform-neutral adapter."""

    def encode_injection(self, text: str) -> bytes: ...

    def observe_output(self, data: bytes) -> tuple[bytes, ...]: ...

    def mark_stalled(self, *, now: float | None = None) -> None: ...

    def mark_awaiting_onboarding(self) -> None: ...

    def detach_matcher(self, chord: bytes) -> DetachMatcher: ...

    @property
    def unhandled_query_pending(self) -> bool: ...

    @property
    def input_prompt_observed(self) -> bool: ...

    def output_tail(self) -> str: ...

    def status_fields(self) -> dict[str, str]: ...


class DetachMatcher(Protocol):
    def feed(self, data: bytes) -> tuple[bytes, bool]: ...


def _record_cleanup(failures: list[Exception], action: Callable[[], object]) -> None:
    try:
        action()
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        failures.append(exc)


@dataclass(slots=True)
class _ActiveWrite:
    epoch: int
    thread_handle: int


class _EpochWriter:
    """Serialized ConPTY input with exact-thread epoch cancellation."""

    def __init__(self, api: NativeApi, handle: int) -> None:
        self._api = api
        self._handle = handle
        self._state = threading.Condition()
        self._serializer = threading.Lock()
        self._epoch = 0
        self._active: _ActiveWrite | None = None
        self._retired = False
        self._interrupting = False
        self._close_thread: threading.Thread | None = None
        self._close_failure: BaseException | None = None

    def write(self, payload: bytes) -> None:
        with self._state:
            epoch = self._epoch
            self._validate(epoch)
        with self._serializer:
            thread_handle: int | None = None
            try:
                with self._state:
                    self._validate(epoch)
                    thread_handle = self._api.open_current_thread()
                    self._active = _ActiveWrite(epoch, thread_handle)
                try:
                    self._api.write(self._handle, payload)
                except Win32IoError as exc:
                    with self._state:
                        if epoch != self._epoch:
                            raise AdapterError("PTY write interrupted") from exc
                    raise AdapterError(f"PTY write failed: {exc}") from exc
                with self._state:
                    self._validate(epoch)
            finally:
                with self._state:
                    if (
                        self._active is not None
                        and self._active.thread_handle == thread_handle
                    ):
                        self._active = None
                    self._state.notify_all()
                if thread_handle is not None:
                    self._api.close_handle(thread_handle)

    def interrupt(self) -> None:
        with self._state:
            if self._retired:
                return
            self._epoch += 1
            self._interrupting = True
            active = self._active
        self._cancel_active(active)
        self._wait_inactive("interrupt")
        with self._state:
            self._interrupting = False
            self._state.notify_all()
        self.write(b"\x03")

    def request_close(self) -> None:
        with self._state:
            if self._retired:
                return
            self._retired = True
            self._interrupting = True
            self._epoch += 1
            active = self._active
            worker = threading.Thread(
                target=self._graceful_close_write,
                args=(active,),
                name="taut-conpty-close-request",
                daemon=True,
            )
            self._close_thread = worker
        worker.start()

    def finish_close_request(self) -> None:
        worker = self._close_thread
        if worker is None:
            return
        worker.join(_CLOSE_TIMEOUT_S)
        if worker.is_alive():
            raise AdapterError("ConPTY graceful close write did not finish")
        if self._close_failure is not None:
            raise AdapterError(
                f"ConPTY graceful close write failed: {self._close_failure}"
            ) from self._close_failure

    def _graceful_close_write(self, active: _ActiveWrite | None) -> None:
        thread_handle: int | None = None
        try:
            self._cancel_active(active)
            self._wait_inactive("request_close")
            with self._serializer:
                thread_handle = self._api.open_current_thread()
                self._api.write(self._handle, b"\x03")
        except Win32IoError as exc:
            if exc.error_code not in _CLEAN_PIPE_END:
                self._close_failure = exc
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            self._close_failure = exc
        finally:
            if thread_handle is not None:
                try:
                    self._api.close_handle(thread_handle)
                except (OSError, RuntimeError, TypeError, ValueError) as exc:
                    if self._close_failure is None:
                        self._close_failure = exc

    def _cancel_active(self, active: _ActiveWrite | None) -> None:
        if active is None:
            return
        try:
            self._api.cancel_thread(active.thread_handle, retiring=True)
        except Win32IoError as exc:
            raise AdapterError(f"ConPTY write cancellation failed: {exc}") from exc

    def _wait_inactive(self, operation: str) -> None:
        deadline = time.monotonic() + _CLOSE_TIMEOUT_S
        with self._state:
            while self._active is not None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise AdapterError(f"ConPTY writer did not stop after {operation}")
                self._state.wait(remaining)

    def _validate(self, epoch: int) -> None:
        if epoch != self._epoch or self._interrupting:
            raise AdapterError("PTY write interrupted")
        if self._retired:
            raise AdapterError("PTY master is closed")


class _TerminalReplyWriter:
    """Keep terminal-report replies off the sole ConPTY output drain."""

    def __init__(self, writer: _EpochWriter) -> None:
        self._writer = writer
        self._items: queue.Queue[bytes | None] = queue.Queue(maxsize=64)
        self._retired = threading.Event()
        self._thread = threading.Thread(
            target=self._run,
            name="taut-conpty-terminal-replies",
            daemon=True,
        )
        self._thread.start()

    def enqueue(self, payload: bytes) -> None:
        if self._retired.is_set():
            return
        try:
            self._items.put_nowait(payload)
        except queue.Full:
            logger.debug("dropping terminal reply because its queue is full")

    def request_close(self) -> None:
        if self._retired.is_set():
            return
        self._retired.set()
        while True:
            try:
                self._items.get_nowait()
            except queue.Empty:
                break
        self._items.put_nowait(None)

    def finish(self) -> None:
        self._thread.join(_CLOSE_TIMEOUT_S)
        if self._thread.is_alive():
            raise AdapterError("ConPTY terminal reply writer did not stop")

    def _run(self) -> None:
        while True:
            payload = self._items.get()
            if payload is None or self._retired.is_set():
                return
            try:
                self._writer.write(payload)
            except AdapterError:
                if self._retired.is_set():
                    return
                logger.debug("terminal reply write was interrupted", exc_info=True)


class _AttachSink:
    """One generation-owned attach output writer."""

    def __init__(self, api: NativeApi, handle: int, generation: int) -> None:
        self._api = api
        self._handle = handle
        self.generation = generation
        self._items: queue.Queue[tuple[int, bytes] | None] = queue.Queue()
        self._retired = False
        self._active_thread: int | None = None
        self._ready = threading.Event()
        self._done = threading.Event()
        self._failure: BaseException | None = None
        self._quarantined = False
        self._thread = threading.Thread(
            target=self._run,
            name=f"taut-conpty-attach-output-{generation}",
            daemon=True,
        )

    def start(self) -> None:
        self._thread.start()
        if not self._ready.wait(5.0):
            raise AdapterError("attach output writer did not start")
        if self._failure is not None:
            raise AdapterError(f"attach output writer failed: {self._failure}")

    def enqueue(self, generation: int, data: bytes) -> None:
        if not self._retired and generation == self.generation:
            self._items.put((generation, data))

    def retire(self, *, close_handle: bool = True) -> None:
        self._retired = True
        while True:
            try:
                self._items.get_nowait()
            except queue.Empty:
                break
        active = self._active_thread
        if active is not None:
            self._api.cancel_thread(active, retiring=True)
        self._items.put(None)
        if not self._done.wait(_CLOSE_TIMEOUT_S):
            self._quarantined = True
            threading.Thread(
                target=self._close_after_exit,
                name=f"taut-conpty-attach-output-reaper-{self.generation}",
                daemon=True,
            ).start()
            raise AdapterError("attach output writer did not stop")
        self._thread.join()
        try:
            if self._failure is not None:
                raise AdapterError(f"attach output writer failed: {self._failure}")
        finally:
            if close_handle:
                self._api.close_handle(self._handle)

    def _close_after_exit(self) -> None:
        self._done.wait()
        self._thread.join()
        try:
            self._api.close_handle(self._handle)
        except (OSError, RuntimeError, TypeError, ValueError):
            logger.exception("quarantined attach output handle cleanup failed")

    def _run(self) -> None:
        thread_handle: int | None = None
        try:
            thread_handle = self._api.open_current_thread()
            self._ready.set()
            while True:
                item = self._items.get()
                if item is None:
                    return
                generation, data = item
                if self._retired or generation != self.generation:
                    continue
                self._active_thread = thread_handle
                try:
                    self._api.write(self._handle, data)
                except Win32IoError as exc:
                    if not (
                        self._retired and exc.error_code == ERROR_OPERATION_ABORTED
                    ):
                        raise
                finally:
                    self._active_thread = None
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            self._failure = exc
            self._ready.set()
        finally:
            if thread_handle is not None:
                try:
                    self._api.close_handle(thread_handle)
                except (OSError, RuntimeError, TypeError, ValueError) as exc:
                    if self._failure is None:
                        self._failure = exc
            self._done.set()


class _OutputDrain:
    """The sole reader of a ConPTY output channel."""

    def __init__(self, api: NativeApi, handle: int, owner: WindowsPtyHandle) -> None:
        self._api = api
        self._handle = handle
        self._owner = owner
        self._routing_lock = threading.Lock()
        self._sink: tuple[int, _AttachSink] | None = None
        self._thread_handle: int | None = None
        self._done = threading.Event()
        self.failure: BaseException | None = None
        self._thread = threading.Thread(
            target=self._run, name="taut-conpty-output", daemon=True
        )

    def start(self) -> None:
        self._thread.start()

    def route(self, generation: int, sink: _AttachSink) -> None:
        with self._routing_lock:
            if self._sink is not None:
                raise AdapterError("a terminal is already attached")
            self._sink = (generation, sink)

    def unroute(self, generation: int) -> _AttachSink:
        with self._routing_lock:
            if self._sink is None or self._sink[0] != generation:
                raise AdapterError("attach output generation changed")
            _, sink = self._sink
            self._sink = None
            return sink

    def cancel_and_join(self) -> None:
        thread_handle = self._thread_handle
        if thread_handle is not None:
            self._api.cancel_thread(thread_handle, retiring=True)
        if not self._done.wait(_CLOSE_TIMEOUT_S):
            raise AdapterError("ConPTY output reader did not stop")
        self._thread.join()
        if self.failure is not None:
            raise AdapterError(f"ConPTY output reader failed: {self.failure}")

    def join_after_close(self) -> None:
        if not self._done.wait(_CLOSE_TIMEOUT_S):
            raise AdapterError("ConPTY output reader did not reach broken pipe")
        self._thread.join()
        if self.failure is not None:
            raise AdapterError(f"ConPTY output reader failed: {self.failure}")

    def _run(self) -> None:
        try:
            self._thread_handle = self._api.open_current_thread()
            while True:
                try:
                    data = self._api.read(self._handle)
                except Win32IoError as exc:
                    if exc.error_code not in _CLEAN_PIPE_END:
                        self.failure = exc
                    return
                if not data:
                    continue
                self._owner._observe_output(data)
                with self._routing_lock:
                    if self._sink is not None:
                        generation, sink = self._sink
                        sink.enqueue(generation, data)
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            self.failure = exc
        finally:
            if self._thread_handle is not None:
                try:
                    self._api.close_handle(self._thread_handle)
                except (OSError, RuntimeError, TypeError, ValueError) as exc:
                    if self.failure is None:
                        self.failure = exc
            self._done.set()
            self._owner._output_ended()


class _AttachSession:
    """One bounded foreground bridge over duplicated host handles."""

    def __init__(
        self,
        owner: WindowsPtyHandle,
        *,
        wake: threading.Event,
        shutdown: threading.Event,
        input_fd: int,
        output_fd: int,
        detach_chord: bytes,
    ) -> None:
        self.owner = owner
        self.api = owner._api
        self.wake = wake
        self.shutdown = shutdown
        self.input_handle = self.api.duplicate_fd_handle(input_fd)
        try:
            self.output_handle: int | None = self.api.duplicate_fd_handle(output_fd)
        except (OSError, AdapterError) as exc:
            try:
                self.api.close_handle(self.input_handle)
            except (OSError, AdapterError) as cleanup:
                exc.add_note(f"first attach duplicate cleanup also failed: {cleanup}")
            raise
        self.matcher = owner._terminal.detach_matcher(detach_chord)
        self.done = threading.Event()
        self.chunks: queue.SimpleQueue[bytes | Exception | None] = queue.SimpleQueue()
        self.input_thread_handle: int | None = None
        self.input_ready = threading.Event()
        self.reader: threading.Thread | None = None
        self.console: ConsoleLease | None = None
        self.sink: _AttachSink | None = None
        self.generation: int | None = None
        self.routed = False

    def run(self) -> str:
        try:
            self._configure_console_if_present()
            self._start_routes()
            return self._bridge()
        finally:
            self._cleanup()

    def _configure_console_if_present(self) -> None:
        try:
            self.api.get_console_mode(self.input_handle)
        except Win32IoError as exc:
            if exc.error_code == ERROR_INVALID_HANDLE:
                return
            raise
        assert self.output_handle is not None
        self.console = ConsoleLease(
            api=self.api,
            input_handle=self.input_handle,
            output_handle=self.output_handle,
        )
        self.console.enter()

    def _start_routes(self) -> None:
        self.owner._attach_generation += 1
        self.generation = self.owner._attach_generation
        assert self.output_handle is not None
        self.sink = _AttachSink(self.api, self.output_handle, self.generation)
        self.sink.start()
        self.owner._drain.route(self.generation, self.sink)
        self.routed = True
        self.reader = threading.Thread(
            target=self._read_input,
            name="taut-conpty-attach-input",
            daemon=True,
        )
        self.reader.start()
        if not self.input_ready.wait(5.0):
            raise AdapterError("attach input reader did not publish ownership")

    def _read_input(self) -> None:
        try:
            self.input_thread_handle = self.api.open_current_thread()
            self.input_ready.set()
            while not self.done.is_set():
                self.chunks.put(self.api.read(self.input_handle))
        except Win32IoError as exc:
            if not (self.done.is_set() and exc.error_code == ERROR_OPERATION_ABORTED):
                self.chunks.put(exc)
        finally:
            self.input_ready.set()
            if self.input_thread_handle is not None:
                try:
                    self.api.close_handle(self.input_thread_handle)
                except (OSError, RuntimeError, TypeError, ValueError) as exc:
                    self.chunks.put(exc)
                finally:
                    self.input_thread_handle = None
            self.chunks.put(None)

    def _bridge(self) -> str:
        while True:
            if self.shutdown.is_set():
                return "shutdown"
            if self.wake.is_set():
                self.wake.clear()
            try:
                item = self.chunks.get(timeout=0.05)
            except queue.Empty:
                if self.owner._exit_ready.is_set():
                    return "eof"
                continue
            if isinstance(item, Exception):
                raise AdapterError(f"attach input failed: {item}") from item
            if item is None or item == b"":
                return "eof"
            forward, detached = self.matcher.feed(item)
            if forward:
                self.owner._writer.write(forward)
            if detached:
                return "detached"

    def _cleanup(self) -> None:
        self.done.set()
        failures: list[Exception] = []
        if self.input_thread_handle is not None:
            input_thread_handle = self.input_thread_handle
            _record_cleanup(
                failures,
                partial(self.api.cancel_thread, input_thread_handle, retiring=True),
            )
        if self.reader is not None:
            self.reader.join(_CLOSE_TIMEOUT_S)
            if self.reader.is_alive():
                failures.append(AdapterError("attach input reader did not stop"))
        self._retire_sink(failures)
        reset_handle = self.output_handle
        if reset_handle is not None:
            _record_cleanup(
                failures, lambda: self.api.write(reset_handle, _DETACH_RESET)
            )
        if self.console is not None:
            _record_cleanup(failures, self.console.restore)
        for handle in (self.input_handle, self.output_handle):
            _record_cleanup(failures, partial(self.api.close_handle, handle))
        self.output_handle = None
        if failures:
            error = AdapterError(str(failures[0]))
            for failure in failures[1:]:
                error.add_note(str(failure))
            raise error

    def _retire_sink(self, failures: list[Exception]) -> None:
        if self.sink is None or self.generation is None:
            return
        if self.routed:
            generation = self.generation

            def action() -> None:
                self.owner._drain.unroute(generation).retire(close_handle=False)

        else:
            action = partial(self.sink.retire, close_handle=False)
        try:
            action()
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            failures.append(exc)
            if self.sink._quarantined:
                self.output_handle = None
        self.sink = None


class WindowsPtyHandle:
    """One Windows ConPTY, its child tree, and all blocking I/O owners."""

    def __init__(
        self,
        *,
        api: NativeApi,
        hpcon: int,
        input_write: int,
        output_read: int,
        process_handle: int,
        pid: int,
        quiet_ms: int,
        max_settle_s: float,
        terminal: TerminalIntegration,
    ) -> None:
        self._api = api
        self._hpcon: int | None = hpcon
        self._input_write: int | None = input_write
        self._output_read: int | None = output_read
        self._process_handle: int | None = process_handle
        self._pid = pid
        self._quiet_s = quiet_ms / 1000
        self._max_settle_s = max_settle_s
        self._terminal = terminal
        self._writer = _EpochWriter(api, input_write)
        self._reply_writer = _TerminalReplyWriter(self._writer)
        self._lock = threading.Condition()
        self._events_lock = threading.Lock()
        self._events_claimed = False
        self._events: queue.SimpleQueue[AdapterEvent] = queue.SimpleQueue()
        self._exit_ready = threading.Event()
        self._exit_emitted = False
        self._returncode: int | None = None
        self._exit_monitor_failure: BaseException | None = None
        self._close_state = "open"
        self._close_error: str | None = None
        self._last_output = time.monotonic()
        self._last_activity = 0.0
        self._seen_output = threading.Event()
        self._attach_generation = 0
        self._drain = _OutputDrain(api, output_read, self)
        self._drain.start()
        self._exit_monitor_done = threading.Event()
        self._exit_monitor = threading.Thread(
            target=self._monitor_process_exit,
            args=(process_handle,),
            name="taut-conpty-process-exit",
            daemon=True,
        )
        self._exit_monitor.start()
        self._events.put(ActivityEvent(description="spawn"))

    @property
    def pid(self) -> int:
        return self._pid

    @property
    def input_prompt_observed(self) -> bool:
        return self._terminal.input_prompt_observed

    def mark_awaiting_onboarding(self) -> None:
        self._terminal.mark_awaiting_onboarding()

    def status_fields(self) -> dict[str, str]:
        return self._terminal.status_fields()

    def output_tail(self) -> str:
        return self._terminal.output_tail()

    def wait_until_quiet(self) -> None:
        deadline = time.monotonic() + self._max_settle_s
        while time.monotonic() < deadline:
            now = time.monotonic()
            self._terminal.mark_stalled(now=now)
            if (
                self._seen_output.is_set()
                and now - self._last_output >= self._quiet_s
                and not self._terminal.unhandled_query_pending
            ):
                return
            if self._exit_ready.wait(0.02):
                return

    def inject(self, text: str) -> None:
        self._writer.write(self._terminal.encode_injection(text))
        self._events.put(ActivityEvent(description="inject"))

    def interrupt(self) -> None:
        self._writer.interrupt()

    def request_close(self) -> None:
        with self._lock:
            if self._close_state != "open":
                return
            self._close_state = "close_requested"
        self._reply_writer.request_close()
        self._writer.request_close()

    def close(self) -> None:
        primary = __import__("sys").exception()
        self.request_close()
        with self._lock:
            if self._close_state == "closed":
                failure = self._close_error
                owner = False
            elif self._close_state == "closing":
                self._lock.wait_for(lambda: self._close_state == "closed")
                failure = self._close_error
                owner = False
            else:
                self._close_state = "closing"
                owner = True
                failure = None
        if owner:
            close_failures: list[Exception] = []
            try:
                self._writer.finish_close_request()
            except (OSError, RuntimeError, TypeError, ValueError) as exc:
                close_failures.append(exc)
            try:
                self._reply_writer.finish()
            except (OSError, RuntimeError, TypeError, ValueError) as exc:
                close_failures.append(exc)
            try:
                self._close_owned_domain()
            except (OSError, RuntimeError, TypeError, ValueError) as exc:
                close_failures.append(exc)
            if close_failures:
                failure = f"{type(close_failures[0]).__name__}: {close_failures[0]}"
                failure += "".join(
                    f"; cleanup also failed: {type(item).__name__}: {item}"
                    for item in close_failures[1:]
                )
            with self._lock:
                self._close_error = failure
                self._close_state = "closed"
                self._lock.notify_all()
            self._publish_recorded_exit()
        if failure:
            if primary is not None:
                primary.add_note(f"adapter cleanup also failed: {failure}")
            else:
                raise AdapterError(failure)

    def events(self) -> Iterator[AdapterEvent]:
        with self._events_lock:
            if self._events_claimed:
                raise AdapterError("events() already has a consumer")
            self._events_claimed = True
        while True:
            event = self._events.get()
            yield event
            if isinstance(event, ExitEvent):
                return

    def attach(
        self,
        *,
        wake: threading.Event,
        shutdown: threading.Event,
        input_fd: int = 0,
        output_fd: int = 1,
        detach_chord: bytes = b"\x1c\x1c",
    ) -> str:
        return _AttachSession(
            self,
            wake=wake,
            shutdown=shutdown,
            input_fd=input_fd,
            output_fd=output_fd,
            detach_chord=detach_chord,
        ).run()

    def _observe_output(self, data: bytes) -> None:
        now = time.monotonic()
        with self._lock:
            self._last_output = now
            replies = self._terminal.observe_output(data)
        for reply in replies:
            self._reply_writer.enqueue(reply)
        self._seen_output.set()
        if now - self._last_activity >= _ACTIVITY_SECONDS:
            self._last_activity = now
            self._events.put(ActivityEvent(description="output"))

    def _output_ended(self) -> None:
        self._exit_ready.set()
        self._publish_recorded_exit()

    def _monitor_process_exit(self, process: int) -> None:
        publish = False
        try:
            wait = int(self._api.WaitForSingleObject(HANDLE(process), 0xFFFFFFFF))
            if wait != WAIT_OBJECT_0:
                raise AdapterError(f"ConPTY child wait failed with result {wait}")
            status = DWORD()
            self._api.require_bool(
                "GetExitCodeProcess",
                self._api.GetExitCodeProcess(HANDLE(process), ctypes.byref(status)),
            )
            if status.value == STILL_ACTIVE:
                raise AdapterError("ConPTY child remained active after exit wait")
            with self._lock:
                self._returncode = int(status.value)
                publish = self._close_state == "open"
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            self._exit_monitor_failure = exc
        finally:
            self._exit_monitor_done.set()
            self._exit_ready.set()
        if publish:
            self._publish_recorded_exit()

    def _publish_recorded_exit(self) -> None:
        with self._lock:
            if (
                self._exit_emitted
                or self._returncode is None
                or self._close_state not in ("open", "closed")
            ):
                return
            self._exit_emitted = True
            returncode = self._returncode
        self._events.put(ExitEvent(returncode=returncode))

    def _close_owned_domain(self) -> None:
        hpcon, process = self._hpcon, self._process_handle
        if hpcon is None or process is None:
            return
        self._api.ClosePseudoConsole(HPCON(hpcon))
        self._hpcon = None
        failures: list[Exception] = []
        _record_cleanup(failures, self._drain.join_after_close)
        _record_cleanup(failures, self._finish_exit_monitor)
        for handle in (process, self._input_write, self._output_read):
            _record_cleanup(failures, partial(self._api.close_handle, handle))
        self._process_handle = None
        self._input_write = None
        self._output_read = None
        if failures:
            error = AdapterError(str(failures[0]))
            for failure in failures[1:]:
                error.add_note(str(failure))
            raise error

    def _finish_exit_monitor(self) -> None:
        if not self._exit_monitor_done.wait(_CLOSE_TIMEOUT_S):
            raise AdapterError("ConPTY child tree did not exit after terminal close")
        self._exit_monitor.join()
        if self._exit_monitor_failure is not None:
            raise AdapterError(
                f"ConPTY child wait failed: {self._exit_monitor_failure}"
            ) from self._exit_monitor_failure

    def _abort_pre_resume(self) -> None:
        """Roll back a child that was created but never published or resumed."""

        with self._lock:
            self._close_state = "closing"
        self._reply_writer.request_close()
        self._reply_writer.finish()
        process = self._process_handle
        if process is not None:
            self._api.require_bool(
                "TerminateProcess",
                self._api.TerminateProcess(HANDLE(process), 96),
            )
            wait = int(self._api.WaitForSingleObject(HANDLE(process), 5_000))
            if wait != WAIT_OBJECT_0:
                raise AdapterError(f"partial ConPTY child wait returned {wait}")
        if self._hpcon is not None:
            self._api.ClosePseudoConsole(HPCON(self._hpcon))
            self._hpcon = None
        self._drain.join_after_close()
        self._finish_exit_monitor()
        self._api.close_handle(self._process_handle)
        self._process_handle = None
        self._api.close_handle(self._input_write)
        self._input_write = None
        self._api.close_handle(self._output_read)
        self._output_read = None


def _environment_block(env: Mapping[str, str]) -> ctypes.Array[Any]:
    entries = [
        f"{key}={value}"
        for key, value in sorted(env.items(), key=lambda item: item[0].upper())
    ]
    return ctypes.create_unicode_buffer("\0".join(entries) + "\0\0")


def _cleanup_failed_spawn(
    native: NativeApi,
    exc: Exception,
    *,
    child_created: bool,
    attribute_initialized: bool,
    attribute_buffer: Any | None,
    hpcon: int | None,
    handles: tuple[int | None, ...],
) -> None:
    process_handle = handles[1]
    if child_created and process_handle is not None:
        try:
            native.require_bool(
                "TerminateProcess",
                native.TerminateProcess(HANDLE(process_handle), 96),
            )
            native.WaitForSingleObject(HANDLE(process_handle), 5_000)
        except (OSError, RuntimeError, TypeError, ValueError) as cleanup:
            exc.add_note(f"partial child cleanup also failed: {cleanup}")
    if attribute_initialized and attribute_buffer is not None:
        native.DeleteProcThreadAttributeList(ctypes.cast(attribute_buffer, LPVOID))
    if hpcon is not None:
        native.ClosePseudoConsole(HPCON(hpcon))
    for handle in handles:
        try:
            native.close_handle(handle)
        except (OSError, RuntimeError, TypeError, ValueError) as cleanup:
            exc.add_note(f"native handle cleanup also failed: {cleanup}")


def spawn_windows_pty(
    *,
    argv: tuple[str, ...],
    env: Mapping[str, str],
    rows: int,
    cols: int,
    quiet_ms: int,
    max_settle_s: float,
    terminal: TerminalIntegration,
    api: NativeApi | None = None,
) -> WindowsPtyHandle:
    """Create one suspended child in a ConPTY and publish only after resume."""

    native = api or NativeApi()
    input_read = input_write = output_read = output_write = None
    hpcon = process_handle = thread_handle = None
    attribute_buffer: Any | None = None
    attribute_initialized = False
    child_created = False
    backend: WindowsPtyHandle | None = None
    try:
        input_read, input_write = native.create_pipe()
        output_read, output_write = native.create_pipe()
        raw_hpcon = HPCON()
        result = int(
            native.CreatePseudoConsole(
                COORD(cols, rows),
                HANDLE(input_read),
                HANDLE(output_write),
                0,
                ctypes.byref(raw_hpcon),
            )
        )
        if result < 0:
            raise AdapterError(
                f"CreatePseudoConsole failed with HRESULT 0x{result & 0xFFFFFFFF:08x}"
            )
        hpcon = native.handle_value(raw_hpcon, "CreatePseudoConsole")
        size = SIZE_T()
        ctypes.set_last_error(0)  # type: ignore[attr-defined]
        sizing = native.InitializeProcThreadAttributeList(
            None, 1, 0, ctypes.byref(size)
        )
        error = int(ctypes.get_last_error())  # type: ignore[attr-defined]
        if sizing or error != 122 or size.value == 0:
            raise AdapterError("failed to size ConPTY process attribute list")
        attribute_buffer = ctypes.create_string_buffer(size.value)
        attribute = ctypes.cast(attribute_buffer, LPVOID)
        native.require_bool(
            "InitializeProcThreadAttributeList",
            native.InitializeProcThreadAttributeList(
                attribute, 1, 0, ctypes.byref(size)
            ),
        )
        attribute_initialized = True
        native.require_bool(
            "UpdateProcThreadAttribute",
            native.UpdateProcThreadAttribute(
                attribute,
                0,
                PROC_THREAD_ATTRIBUTE_PSEUDOCONSOLE,
                LPVOID(hpcon),
                ctypes.sizeof(HPCON),
                None,
                None,
            ),
        )
        startup = STARTUPINFOEXW()
        startup.StartupInfo.cb = ctypes.sizeof(STARTUPINFOEXW)
        startup.StartupInfo.dwFlags = STARTF_USESTDHANDLES
        startup.lpAttributeList = attribute
        command = ctypes.create_unicode_buffer(subprocess.list2cmdline(argv))
        environment = _environment_block(env)
        info = PROCESS_INFORMATION()
        native.require_bool(
            "CreateProcessW",
            native.CreateProcessW(
                None,
                command,
                None,
                None,
                0,
                EXTENDED_STARTUPINFO_PRESENT
                | CREATE_UNICODE_ENVIRONMENT
                | CREATE_SUSPENDED,
                environment,
                None,
                ctypes.byref(startup.StartupInfo),
                ctypes.byref(info),
            ),
        )
        process_handle = native.handle_value(info.hProcess, "CreateProcessW")
        thread_handle = native.handle_value(info.hThread, "CreateProcessW")
        child_created = True
        native.DeleteProcThreadAttributeList(attribute)
        attribute_initialized = False
        attribute_buffer = None
        native.close_handle(input_read)
        input_read = None
        native.close_handle(output_write)
        output_write = None
        backend = WindowsPtyHandle(
            api=native,
            hpcon=hpcon,
            input_write=input_write,
            output_read=output_read,
            process_handle=process_handle,
            pid=int(info.dwProcessId),
            quiet_ms=quiet_ms,
            max_settle_s=max_settle_s,
            terminal=terminal,
        )
        hpcon = input_write = output_read = process_handle = None
        previous = int(native.ResumeThread(HANDLE(thread_handle)))
        if previous == DWORD_FAILURE:
            raise Win32IoError("ResumeThread", int(ctypes.get_last_error()))  # type: ignore[attr-defined]
        if previous != 1:
            raise AdapterError(f"ResumeThread returned {previous}, expected 1")
        native.close_handle(thread_handle)
        thread_handle = None
        return backend
    except Exception as exc:
        if backend is not None:
            try:
                backend._abort_pre_resume()
            except (OSError, RuntimeError, TypeError, ValueError) as cleanup:
                exc.add_note(f"partial ConPTY owner cleanup also failed: {cleanup}")
        _cleanup_failed_spawn(
            native,
            exc,
            child_created=child_created,
            attribute_initialized=attribute_initialized,
            attribute_buffer=attribute_buffer,
            hpcon=hpcon,
            handles=(
                thread_handle,
                process_handle,
                input_read,
                input_write,
                output_read,
                output_write,
            ),
        )
        if isinstance(exc, AdapterError):
            raise
        raise AdapterError(f"failed to spawn Windows PTY harness: {exc}") from exc
