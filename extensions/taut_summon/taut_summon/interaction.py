"""Public host-terminal seam for foreground Summon runs ([SUM-7.4], [SUM-13])."""

from __future__ import annotations

import os
import select
import sys
import threading
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass, field
from enum import Enum
from types import TracebackType
from typing import Protocol, TextIO, TypeVar, cast

_WINDOWS_ERROR_NOT_FOUND = 1168
_WINDOWS_ERROR_OPERATION_ABORTED = 995
_WINDOWS_THREAD_TERMINATE = 0x0001
_WINDOWS_READ_POLL_SECONDS = 0.1
_NO_RESULT = object()
_T = TypeVar("_T")


class _LineReader(Protocol):
    def readline(self) -> str: ...


def _is_windows() -> bool:
    return os.name == "nt"


class _ErrorCapture:
    """Capture an arbitrary owned-call failure without an except boundary."""

    def __init__(self) -> None:
        self.error: BaseException | None = None

    def __enter__(self) -> None:
        return None

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        del exc_type, traceback
        self.error = exc_value
        return exc_value is not None


@dataclass(slots=True)
class _WindowsReadState:
    lock: threading.Lock = field(default_factory=threading.Lock)
    ready: threading.Event = field(default_factory=threading.Event)
    start: threading.Event = field(default_factory=threading.Event)
    done: threading.Event = field(default_factory=threading.Event)
    abort_before_read: bool = False
    terminal_action: str | None = None
    handle: int | None = None
    open_error: BaseException | None = None
    line: str | None = None
    error: BaseException | None = None
    cancel_succeeded: bool = False


def _claim_windows_terminal_action(state: _WindowsReadState, action: str) -> bool:
    with state.lock:
        if state.terminal_action is None:
            state.terminal_action = action
        return state.terminal_action == action


def _open_windows_thread(native_id: int) -> int:
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
    open_thread = kernel32.OpenThread
    open_thread.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    open_thread.restype = wintypes.HANDLE
    handle = open_thread(_WINDOWS_THREAD_TERMINATE, False, native_id)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())  # type: ignore[attr-defined]
    value = ctypes.cast(handle, ctypes.c_void_p).value
    if value is None:  # pragma: no cover - guarded by the false-handle check
        raise RuntimeError("OpenThread returned an invalid handle")
    return value


def _cancel_windows_synchronous_io(handle: int) -> bool:
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
    cancel_io = kernel32.CancelSynchronousIo
    cancel_io.argtypes = [wintypes.HANDLE]
    cancel_io.restype = wintypes.BOOL
    if cancel_io(wintypes.HANDLE(handle)):
        return True
    error = ctypes.get_last_error()  # type: ignore[attr-defined]
    if error == _WINDOWS_ERROR_NOT_FOUND:
        return False
    raise ctypes.WinError(error)  # type: ignore[attr-defined]


def _close_windows_handle(handle: int) -> None:
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = [wintypes.HANDLE]
    close_handle.restype = wintypes.BOOL
    if not close_handle(wintypes.HANDLE(handle)):
        raise ctypes.WinError(ctypes.get_last_error())  # type: ignore[attr-defined]


class _WindowsCancelableReadOwner:
    def __init__(self, stream: _LineReader, cancel: threading.Event) -> None:
        self._stream = stream
        self._cancel = cancel
        self._state = _WindowsReadState()
        self._primary_error: BaseException | None = None
        self._reader = threading.Thread(
            target=self._read_once,
            name="taut-summon-shell-input",
            daemon=False,
        )

    def run(self) -> str | None:
        with self._lifecycle():
            self._reader.start()
            self._wait_until_ready()
            with self._state.lock:
                handle = self._state.handle
                open_error = self._state.open_error
            if open_error is not None:
                raise open_error
            if self._primary_error is not None:
                raise self._primary_error
            if handle is None:  # pragma: no cover - ready requires handle or error
                raise RuntimeError("Windows input reader published no handle")
            return self._observe(handle)

    @contextmanager
    def _lifecycle(self) -> Iterator[None]:
        try:
            yield
        finally:
            active_error = sys.exception()
            self._record_primary(active_error)
            close_error = self._cleanup()
            if active_error is None:
                if self._primary_error is not None:
                    raise self._primary_error
                if close_error is not None:
                    raise close_error

    def _cleanup(self) -> BaseException | None:
        if self._reader.ident is None:
            return None
        if self._primary_error is not None:
            self._abort_before_read()
        self._wait_until_ready()
        handle, open_error = self._retry_cleanup_state_action(
            lambda: (self._state.handle, self._state.open_error)
        )
        self._record_primary(open_error)
        if self._primary_error is not None:
            self._abort_before_read()
        return self._finish_reader(handle)

    def _read_once(self) -> None:
        open_error = _ErrorCapture()
        handle: int | None = None
        with open_error:
            handle = _open_windows_thread(threading.get_native_id())
        with self._state.lock:
            self._state.handle = handle
            self._state.open_error = open_error.error
        self._state.ready.set()
        if open_error.error is not None:
            self._state.done.set()
            return
        self._state.start.wait()
        with self._state.lock:
            if self._state.abort_before_read or self._state.terminal_action == "cancel":
                self._state.done.set()
                return
        read_error = _ErrorCapture()
        line: str | None = None
        with read_error:
            line = self._stream.readline()
        with self._state.lock:
            if read_error.error is not None:
                self._state.error = read_error.error
            else:
                self._state.line = line
            if self._state.terminal_action is None:
                self._state.terminal_action = "line"
        self._state.done.set()

    def _wait_until_ready(self) -> None:
        while not self._state.ready.is_set():
            ready_error = _ErrorCapture()
            with ready_error:
                self._state.ready.wait(_WINDOWS_READ_POLL_SECONDS)
            self._record_primary(ready_error.error)

    def _abort_before_read(self) -> None:
        def abort() -> None:
            self._state.abort_before_read = True

        self._retry_cleanup_state_action(abort)
        self._retry_cleanup_action(self._state.start.set)

    def _observe(self, handle: int) -> str | None:
        with self._state.lock:
            if self._cancel.is_set():
                self._state.abort_before_read = True
        if self._cancel.is_set():
            self._retry_cleanup_state_action(
                lambda: self._claim_terminal_action_locked("cancel")
            )
        self._state.start.set()
        while not self._state.done.wait(_WINDOWS_READ_POLL_SECONDS):
            self._cancel_if_requested(handle)
        self._reader.join()
        return self._outcome()

    def _cancel_if_requested(self, handle: int) -> None:
        if not self._cancel.is_set() or not _claim_windows_terminal_action(
            self._state, "cancel"
        ):
            return
        cancel_error = _ErrorCapture()
        cancelled = False
        with cancel_error:
            cancelled = _cancel_windows_synchronous_io(handle)
        if cancel_error.error is not None:
            self._record_primary(cancel_error.error)
            return
        if cancelled:
            with self._state.lock:
                self._state.cancel_succeeded = True

    def _outcome(self) -> str | None:
        with self._state.lock:
            action = self._state.terminal_action
            line = self._state.line
            read_error = self._state.error
            cancel_succeeded = self._state.cancel_succeeded
        if self._primary_error is None and read_error is not None:
            owned_abort = (
                action == "cancel"
                and cancel_succeeded
                and isinstance(read_error, OSError)
                and getattr(read_error, "winerror", None)
                == _WINDOWS_ERROR_OPERATION_ABORTED
            )
            if not owned_abort:
                self._primary_error = read_error
        if self._primary_error is not None:
            raise self._primary_error
        return None if action == "cancel" else line

    def _finish_reader(self, handle: int | None) -> BaseException | None:
        while not self._state.done.is_set():
            wait_error = _ErrorCapture()
            with wait_error:
                self._state.done.wait(_WINDOWS_READ_POLL_SECONDS)
            self._record_primary(wait_error.error)
            if self._state.done.is_set():
                break
            if handle is None:
                continue
            self._retry_cleanup_state_action(
                lambda: self._claim_terminal_action_locked("cancel")
            )
            cancel_error = _ErrorCapture()
            cancelled = False
            with cancel_error:
                cancelled = _cancel_windows_synchronous_io(handle)
            self._record_primary(cancel_error.error)
            if cancelled:
                self._retry_cleanup_state_action(self._mark_cancel_succeeded)
        while self._retry_cleanup_action(self._reader.is_alive):
            join_error = _ErrorCapture()
            with join_error:
                self._reader.join(_WINDOWS_READ_POLL_SECONDS)
            self._record_primary(join_error.error)
        if handle is None:
            return None
        close_capture = _ErrorCapture()
        with close_capture:
            _close_windows_handle(handle)
        return close_capture.error

    def _record_primary(self, error: BaseException | None) -> None:
        if error is not None and self._primary_error is None:
            self._primary_error = error

    def _retry_cleanup_state_action(self, action: Callable[[], _T]) -> _T:
        def locked_action() -> _T:
            with self._state.lock:
                return action()

        return self._retry_cleanup_action(locked_action)

    def _retry_cleanup_action(self, action: Callable[[], _T]) -> _T:
        while True:
            action_error = _ErrorCapture()
            result: _T | object = _NO_RESULT
            with action_error:
                result = action()
            self._record_primary(action_error.error)
            if action_error.error is None:
                return cast(_T, result)

    def _claim_terminal_action_locked(self, action: str) -> bool:
        if self._state.terminal_action is None:
            self._state.terminal_action = action
        return self._state.terminal_action == action

    def _mark_cancel_succeeded(self) -> None:
        self._state.cancel_succeeded = True


def _windows_cancelable_readline(
    stream: _LineReader,
    cancel: threading.Event,
) -> str | None:
    """Own one Windows synchronous read until a line or cancellation wins."""

    return _WindowsCancelableReadOwner(stream, cancel).run()


class TerminalIntent(Enum):
    """Whether the caller explicitly requires or merely prefers a terminal."""

    REQUIRED = "required"
    PREFERRED = "preferred"


class TerminalAvailability(Enum):
    """Why the host can or cannot grant its human terminal."""

    AVAILABLE = "available"
    NO_TTY = "no-tty"
    NESTED_HOST = "nested-host"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class TerminalLease:
    """Host-owned input and output descriptors valid for one attach scope."""

    input_fd: int
    output_fd: int


@dataclass(frozen=True, slots=True)
class TerminalAttachNotice:
    """Semantic facts a host must present before a raw provider attach."""

    member: str
    provider: str
    detach_hint: str


class SummonInteraction(Protocol):
    """Pre-spawn acknowledgement and terminal handoff from a foreground host."""

    def terminal_availability(self, intent: TerminalIntent) -> TerminalAvailability:
        """Report host availability without changing terminal state."""
        ...

    def confirm_terminal_attach(
        self,
        notice: TerminalAttachNotice,
        *,
        cancel: threading.Event | None = None,
    ) -> bool:
        """Present an actual attach decision and return proceed or cancel."""
        ...

    def terminal_lease(self) -> AbstractContextManager[TerminalLease]:
        """Grant host descriptors and restore host state when the scope exits."""
        ...


class ShellSummonInteraction:
    """Terminal interaction for the standalone shell command surface."""

    def __init__(
        self,
        *,
        input_stream: TextIO | None = None,
        output_stream: TextIO | None = None,
    ) -> None:
        self._availability: TerminalAvailability | None = None
        self._input_stream = sys.stdin if input_stream is None else input_stream
        self._output_stream = sys.stderr if output_stream is None else output_stream

    def terminal_availability(self, intent: TerminalIntent) -> TerminalAvailability:
        del intent
        if not self._input_stream.isatty():
            availability = TerminalAvailability.NO_TTY
        elif os.environ.get("TAUT_HOST_TUI") == "1":
            availability = TerminalAvailability.NESTED_HOST
        else:
            availability = TerminalAvailability.AVAILABLE
        self._availability = availability
        return availability

    def confirm_terminal_attach(
        self,
        notice: TerminalAttachNotice,
        *,
        cancel: threading.Event | None = None,
    ) -> bool:
        from taut import escape_terminal_text

        member = escape_terminal_text(notice.member)
        provider = escape_terminal_text(notice.provider)
        detach_hint = escape_terminal_text(notice.detach_hint)
        self._output_stream.write(
            f"Preparing provider setup for '{member}' with '{provider}'.\n"
            "This is provider setup, not Taut chat.\n"
            "Complete only trust, login, model, or equivalent setup.\n"
            f"When setup is complete, return to Taut with {detach_hint}.\n"
            "This foreground Summon command keeps running after detach; "
            "chat from another terminal.\n"
            "Press Enter to continue, or type anything else to cancel: "
        )
        self._output_stream.flush()
        if cancel is None:
            return self._input_stream.readline() in {"\n", "\r\n"}
        if _is_windows():
            return _windows_cancelable_readline(self._input_stream, cancel) in {
                "\n",
                "\r\n",
            }
        try:
            input_fd = self._input_stream.fileno()
        except (AttributeError, OSError):
            return self._input_stream.readline() in {"\n", "\r\n"}
        while not cancel.is_set():
            ready, _, _ = select.select([input_fd], [], [], 0.1)
            if ready:
                return self._input_stream.readline() in {"\n", "\r\n"}
        return False

    @contextmanager
    def terminal_lease(self) -> Iterator[TerminalLease]:
        if self._availability is not TerminalAvailability.AVAILABLE:
            raise RuntimeError("terminal is not available")
        yield TerminalLease(input_fd=0, output_fd=1)


__all__ = [
    "ShellSummonInteraction",
    "SummonInteraction",
    "TerminalAttachNotice",
    "TerminalAvailability",
    "TerminalIntent",
    "TerminalLease",
]
