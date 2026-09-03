"""TEMPORARY hosted-Windows ConPTY qualification probe; delete after Slice 1."""

# The coordinator must turn every worker and cleanup failure into its one JSON record.
# ruff: noqa: BLE001, C901

from __future__ import annotations

import base64
import ctypes
import json
import os
import queue
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import traceback
from ctypes import wintypes
from pathlib import Path
from typing import Any, NoReturn

import psutil

DWORD = ctypes.c_uint32
WORD = ctypes.c_uint16
SHORT = ctypes.c_int16
BOOL = ctypes.c_int32
UINT = ctypes.c_uint32
SIZE_T = ctypes.c_size_t
ULONG_PTR = ctypes.c_size_t
HRESULT = ctypes.c_int32
HANDLE = ctypes.c_void_p
LPVOID = ctypes.c_void_p
HPCON = ctypes.c_void_p

ERROR_INSUFFICIENT_BUFFER = 122
ERROR_BROKEN_PIPE = 109
ERROR_INVALID_HANDLE = 6
ERROR_OPERATION_ABORTED = 995
ERROR_NOT_FOUND = 1168
WAIT_OBJECT_0 = 0
WAIT_TIMEOUT = 258
WAIT_FAILED = 0xFFFFFFFF
STILL_ACTIVE = 259
DWORD_FAILURE = 0xFFFFFFFF
CREATE_SUSPENDED = 0x00000004
CREATE_NEW_CONSOLE = 0x00000010
CREATE_UNICODE_ENVIRONMENT = 0x00000400
EXTENDED_STARTUPINFO_PRESENT = 0x00080000
STARTF_USESTDHANDLES = 0x00000100
PROC_THREAD_ATTRIBUTE_PSEUDOCONSOLE = 0x00020016
THREAD_TERMINATE = 0x0001
DUPLICATE_SAME_ACCESS = 0x00000002
ENABLE_PROCESSED_INPUT = 0x0001
ENABLE_LINE_INPUT = 0x0002
ENABLE_ECHO_INPUT = 0x0004
ENABLE_QUICK_EDIT_MODE = 0x0040
ENABLE_EXTENDED_FLAGS = 0x0080
ENABLE_VIRTUAL_TERMINAL_INPUT = 0x0200
ENABLE_PROCESSED_OUTPUT = 0x0001
ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
CP_UTF8 = 65001
KEY_EVENT = 0x0001


class COORD(ctypes.Structure):
    _fields_ = [("X", SHORT), ("Y", SHORT)]


class STARTUPINFOW(ctypes.Structure):
    _fields_ = [
        ("cb", DWORD),
        ("lpReserved", wintypes.LPWSTR),
        ("lpDesktop", wintypes.LPWSTR),
        ("lpTitle", wintypes.LPWSTR),
        ("dwX", DWORD),
        ("dwY", DWORD),
        ("dwXSize", DWORD),
        ("dwYSize", DWORD),
        ("dwXCountChars", DWORD),
        ("dwYCountChars", DWORD),
        ("dwFillAttribute", DWORD),
        ("dwFlags", DWORD),
        ("wShowWindow", WORD),
        ("cbReserved2", WORD),
        ("lpReserved2", ctypes.POINTER(ctypes.c_ubyte)),
        ("hStdInput", HANDLE),
        ("hStdOutput", HANDLE),
        ("hStdError", HANDLE),
    ]


class STARTUPINFOEXW(ctypes.Structure):
    _fields_ = [("StartupInfo", STARTUPINFOW), ("lpAttributeList", LPVOID)]


class PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("hProcess", HANDLE),
        ("hThread", HANDLE),
        ("dwProcessId", DWORD),
        ("dwThreadId", DWORD),
    ]


class CHAR_UNION(ctypes.Union):
    _fields_ = [
        ("UnicodeChar", ctypes.c_wchar),
        ("AsciiChar", ctypes.c_char),
    ]


class KEY_EVENT_RECORD(ctypes.Structure):
    _fields_ = [
        ("bKeyDown", BOOL),
        ("wRepeatCount", WORD),
        ("wVirtualKeyCode", WORD),
        ("wVirtualScanCode", WORD),
        ("uChar", CHAR_UNION),
        ("dwControlKeyState", DWORD),
    ]


class INPUT_EVENT_UNION(ctypes.Union):
    _fields_ = [
        ("KeyEvent", KEY_EVENT_RECORD),
        ("padding", ctypes.c_byte * 16),
    ]


class INPUT_RECORD(ctypes.Structure):
    _fields_ = [("EventType", WORD), ("Event", INPUT_EVENT_UNION)]


class Win32Failure(OSError):
    def __init__(self, operation: str, error_code: int) -> None:
        self.operation = operation
        self.error_code = error_code
        super().__init__(
            error_code, f"{operation} failed with Win32 error {error_code}"
        )


class InjectedPreResumeFailure(RuntimeError):
    pass


class Native:
    def __init__(self) -> None:
        if os.name != "nt":
            raise RuntimeError("native ConPTY qualification requires Windows")
        self.k32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
        self.calls: list[dict[str, Any]] = []
        self._bind()

    def _bind(self) -> None:
        k = self.k32
        self.CreatePipe = k.CreatePipe
        self.CreatePipe.argtypes = [
            ctypes.POINTER(HANDLE),
            ctypes.POINTER(HANDLE),
            LPVOID,
            DWORD,
        ]
        self.CreatePipe.restype = BOOL
        self.CreatePseudoConsole = k.CreatePseudoConsole
        self.CreatePseudoConsole.argtypes = [
            COORD,
            HANDLE,
            HANDLE,
            DWORD,
            ctypes.POINTER(HPCON),
        ]
        self.CreatePseudoConsole.restype = HRESULT
        self.ClosePseudoConsole = k.ClosePseudoConsole
        self.ClosePseudoConsole.argtypes = [HPCON]
        self.ClosePseudoConsole.restype = None
        self.InitializeProcThreadAttributeList = k.InitializeProcThreadAttributeList
        self.InitializeProcThreadAttributeList.argtypes = [
            LPVOID,
            DWORD,
            DWORD,
            ctypes.POINTER(SIZE_T),
        ]
        self.InitializeProcThreadAttributeList.restype = BOOL
        self.UpdateProcThreadAttribute = k.UpdateProcThreadAttribute
        self.UpdateProcThreadAttribute.argtypes = [
            LPVOID,
            DWORD,
            ULONG_PTR,
            LPVOID,
            SIZE_T,
            LPVOID,
            ctypes.POINTER(SIZE_T),
        ]
        self.UpdateProcThreadAttribute.restype = BOOL
        self.DeleteProcThreadAttributeList = k.DeleteProcThreadAttributeList
        self.DeleteProcThreadAttributeList.argtypes = [LPVOID]
        self.DeleteProcThreadAttributeList.restype = None
        self.CreateProcessW = k.CreateProcessW
        self.CreateProcessW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.LPWSTR,
            LPVOID,
            LPVOID,
            BOOL,
            DWORD,
            LPVOID,
            wintypes.LPCWSTR,
            ctypes.POINTER(STARTUPINFOW),
            ctypes.POINTER(PROCESS_INFORMATION),
        ]
        self.CreateProcessW.restype = BOOL
        self.ResumeThread = k.ResumeThread
        self.ResumeThread.argtypes = [HANDLE]
        self.ResumeThread.restype = DWORD
        self.TerminateProcess = k.TerminateProcess
        self.TerminateProcess.argtypes = [HANDLE, UINT]
        self.TerminateProcess.restype = BOOL
        self.ReadFile = k.ReadFile
        self.ReadFile.argtypes = [HANDLE, LPVOID, DWORD, ctypes.POINTER(DWORD), LPVOID]
        self.ReadFile.restype = BOOL
        self.WriteFile = k.WriteFile
        self.WriteFile.argtypes = [HANDLE, LPVOID, DWORD, ctypes.POINTER(DWORD), LPVOID]
        self.WriteFile.restype = BOOL
        # Qualification-only input injection. This is not part of the production API ledger.
        self.WriteConsoleInputW = k.WriteConsoleInputW
        self.WriteConsoleInputW.argtypes = [
            HANDLE,
            ctypes.POINTER(INPUT_RECORD),
            DWORD,
            ctypes.POINTER(DWORD),
        ]
        self.WriteConsoleInputW.restype = BOOL
        self.GetConsoleMode = k.GetConsoleMode
        self.GetConsoleMode.argtypes = [HANDLE, ctypes.POINTER(DWORD)]
        self.GetConsoleMode.restype = BOOL
        self.SetConsoleMode = k.SetConsoleMode
        self.SetConsoleMode.argtypes = [HANDLE, DWORD]
        self.SetConsoleMode.restype = BOOL
        self.GetConsoleCP = k.GetConsoleCP
        self.GetConsoleCP.argtypes = []
        self.GetConsoleCP.restype = UINT
        self.SetConsoleCP = k.SetConsoleCP
        self.SetConsoleCP.argtypes = [UINT]
        self.SetConsoleCP.restype = BOOL
        self.GetConsoleOutputCP = k.GetConsoleOutputCP
        self.GetConsoleOutputCP.argtypes = []
        self.GetConsoleOutputCP.restype = UINT
        self.SetConsoleOutputCP = k.SetConsoleOutputCP
        self.SetConsoleOutputCP.argtypes = [UINT]
        self.SetConsoleOutputCP.restype = BOOL
        self.GetCurrentProcess = k.GetCurrentProcess
        self.GetCurrentProcess.argtypes = []
        self.GetCurrentProcess.restype = HANDLE
        self.DuplicateHandle = k.DuplicateHandle
        self.DuplicateHandle.argtypes = [
            HANDLE,
            HANDLE,
            HANDLE,
            ctypes.POINTER(HANDLE),
            DWORD,
            BOOL,
            DWORD,
        ]
        self.DuplicateHandle.restype = BOOL
        self.OpenThread = k.OpenThread
        self.OpenThread.argtypes = [DWORD, BOOL, DWORD]
        self.OpenThread.restype = HANDLE
        self.CancelSynchronousIo = k.CancelSynchronousIo
        self.CancelSynchronousIo.argtypes = [HANDLE]
        self.CancelSynchronousIo.restype = BOOL
        self.WaitForSingleObject = k.WaitForSingleObject
        self.WaitForSingleObject.argtypes = [HANDLE, DWORD]
        self.WaitForSingleObject.restype = DWORD
        self.GetExitCodeProcess = k.GetExitCodeProcess
        self.GetExitCodeProcess.argtypes = [HANDLE, ctypes.POINTER(DWORD)]
        self.GetExitCodeProcess.restype = BOOL
        self.CloseHandle = k.CloseHandle
        self.CloseHandle.argtypes = [HANDLE]
        self.CloseHandle.restype = BOOL

    @staticmethod
    def value(raw: int | None) -> int:
        value = ctypes.cast(raw, ctypes.c_void_p).value
        if value is None:
            raise RuntimeError("native call returned a null handle")
        return int(value)

    def record(self, operation: str, result: Any, error: int | None = None) -> None:
        self.calls.append({"operation": operation, "result": result, "error": error})

    def require_bool(self, operation: str, result: int) -> None:
        if not result:
            error = int(ctypes.get_last_error())  # type: ignore[attr-defined]
            self.record(operation, False, error)
            raise Win32Failure(operation, error)
        self.record(operation, True, 0)

    def close(self, handle: int | None, label: str) -> None:
        if handle is None:
            return
        self.require_bool(label, self.CloseHandle(HANDLE(handle)))

    def open_thread(self) -> int:
        raw = self.OpenThread(THREAD_TERMINATE, 0, threading.get_native_id())
        if not raw:
            raise Win32Failure(
                "OpenThread",
                int(ctypes.get_last_error()),  # type: ignore[attr-defined]
            )
        value = self.value(raw)
        self.record("OpenThread", value, 0)
        return value


class AttachSink:
    """A generation-owned, dedicated blocking writer for the attach-output route."""

    def __init__(self, native: Native, handle: int, generation: int) -> None:
        self.native = native
        self.handle = handle
        self.generation = generation
        self.items: queue.Queue[tuple[int, bytes] | None] = queue.Queue()
        self.ready = threading.Event()
        self.done = threading.Event()
        self.active = threading.Event()
        self.thread_handle: int | None = None
        self.retired = False
        self.write_error: int | None = None
        self.failure: str | None = None
        self.close_failure: str | None = None
        self.discarded = 0
        self.rejected = 0
        self.successful = bytearray()
        self.successful_lock = threading.Lock()
        self.thread = threading.Thread(
            target=self._run, name=f"attach-sink-{generation}", daemon=True
        )

    def start(self) -> None:
        self.thread.start()
        if not self.ready.wait(5.0):
            raise RuntimeError("attach sink did not publish worker ownership")
        if self.failure is not None:
            raise RuntimeError(self.failure)

    def enqueue(self, generation: int, data: bytes) -> bool:
        if self.retired or generation != self.generation:
            self.rejected += 1
            return False
        self.items.put((generation, data))
        return True

    def _run(self) -> None:
        try:
            self.thread_handle = self.native.open_thread()
            self.ready.set()
            while True:
                item = self.items.get()
                if item is None:
                    return
                generation, data = item
                if self.retired or generation != self.generation:
                    self.discarded += 1
                    continue
                buf = ctypes.create_string_buffer(data)
                count = DWORD()
                self.active.set()
                ok = self.native.WriteFile(
                    HANDLE(self.handle), buf, len(data), ctypes.byref(count), None
                )
                self.active.clear()
                if not ok:
                    self.write_error = int(ctypes.get_last_error())  # type: ignore[attr-defined]
                    if self.write_error == ERROR_OPERATION_ABORTED and self.retired:
                        return
                    raise Win32Failure("WriteFile(attach-sink)", self.write_error)
                if count.value != len(data):
                    raise RuntimeError(
                        f"attach sink short write: {count.value} of {len(data)}"
                    )
                with self.successful_lock:
                    self.successful.extend(data)
        except BaseException:
            self.failure = traceback.format_exc()
            self.ready.set()
        finally:
            self.active.clear()
            if self.thread_handle is not None:
                try:
                    self.native.close(
                        self.thread_handle, "CloseHandle(attach-sink-thread)"
                    )
                except BaseException as exc:
                    self.close_failure = f"{type(exc).__name__}: {exc}"
            self.done.set()

    def wait_blocked(self, timeout: float = 10.0) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.active.wait(0.05):
                time.sleep(0.1)
                if self.active.is_set() and not self.done.is_set():
                    return
            if self.done.is_set():
                break
        raise RuntimeError(
            "actual attach sink WriteFile did not remain blocked; "
            f"error={self.write_error}, failure={self.failure}"
        )

    def successful_snapshot(self) -> bytes:
        with self.successful_lock:
            return bytes(self.successful)

    def retire(self, *, require_cancel: bool) -> dict[str, Any]:
        self.retired = True
        while True:
            try:
                item = self.items.get_nowait()
            except queue.Empty:
                break
            if item is not None:
                self.discarded += 1
        cancelled = False
        if self.active.is_set():
            if self.thread_handle is None:
                raise RuntimeError(
                    "active attach sink has no cancellable thread handle"
                )
            self.native.require_bool(
                "CancelSynchronousIo(attach-sink)",
                self.native.CancelSynchronousIo(HANDLE(self.thread_handle)),
            )
            cancelled = True
        else:
            self.items.put(None)
        if not self.done.wait(5.0):
            raise RuntimeError("retired attach sink worker did not finish")
        self.thread.join()
        if self.failure is not None:
            raise RuntimeError(self.failure)
        if self.close_failure is not None:
            raise RuntimeError(self.close_failure)
        if require_cancel and (
            not cancelled or self.write_error != ERROR_OPERATION_ABORTED
        ):
            raise RuntimeError(
                "blocked attach sink was not cancelled with ERROR_OPERATION_ABORTED: "
                f"cancelled={cancelled}, error={self.write_error}"
            )
        self.native.close(self.handle, "CloseHandle(attach-sink-write)")
        self.handle = 0
        return {
            "cancelled": cancelled,
            "write_error": self.write_error,
            "discarded_queue_items": self.discarded,
            "rejected_after_retire": self.rejected,
        }


class OutputDrain:
    def __init__(self, native: Native, handle: int) -> None:
        self.native = native
        self.handle = handle
        self.data = bytearray()
        self.lock = threading.Lock()
        self.ready = threading.Event()
        self.done = threading.Event()
        self.thread_handle: int | None = None
        self.terminal_error: int | None = None
        self.failure: str | None = None
        self.sink_lock = threading.Lock()
        self.sink: tuple[int, AttachSink] | None = None
        self.thread = threading.Thread(
            target=self._run, name="conpty-output-drain", daemon=True
        )

    def register_sink(self, generation: int, sink: AttachSink) -> None:
        with self.sink_lock:
            if self.sink is not None:
                raise RuntimeError("attach sink already registered")
            self.sink = (generation, sink)

    def unregister_sink(self, generation: int) -> AttachSink:
        with self.sink_lock:
            if self.sink is None or self.sink[0] != generation:
                raise RuntimeError(f"attach generation {generation} is not registered")
            _generation, sink = self.sink
            self.sink = None
            return sink

    def start(self) -> None:
        self.thread.start()
        if not self.ready.wait(5.0):
            raise RuntimeError("ConPTY output reader did not publish ownership")

    def _run(self) -> None:
        try:
            self.thread_handle = self.native.open_thread()
            self.ready.set()
            while True:
                buf = ctypes.create_string_buffer(4096)
                count = DWORD()
                ok = self.native.ReadFile(
                    HANDLE(self.handle), buf, len(buf), ctypes.byref(count), None
                )
                if ok:
                    if count.value:
                        chunk = buf.raw[: count.value]
                        with self.lock:
                            self.data.extend(chunk)
                        with self.sink_lock:
                            if self.sink is not None:
                                generation, sink = self.sink
                                sink.enqueue(generation, chunk)
                    continue
                error = int(ctypes.get_last_error())  # type: ignore[attr-defined]
                self.terminal_error = error
                if error != ERROR_BROKEN_PIPE:
                    self.failure = (
                        f"ConPTY output ReadFile failed with Win32 error {error}"
                    )
                return
        except BaseException:
            self.failure = traceback.format_exc()
            self.ready.set()
        finally:
            if self.thread_handle is not None:
                try:
                    self.native.close(
                        self.thread_handle, "CloseHandle(output-reader-thread)"
                    )
                except BaseException:
                    self.failure = (self.failure or "") + traceback.format_exc()
            self.done.set()

    def wait_for(self, marker: bytes, timeout: float = 10.0) -> bytes:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self.lock:
                data = bytes(self.data)
            if marker in data:
                return data
            if self.done.wait(0.01):
                break
        raise RuntimeError(
            f"ConPTY output did not contain {marker!r}; tail={data[-2000:]!r}; "
            f"failure={self.failure!r}"
        )

    def snapshot(self) -> bytes:
        with self.lock:
            return bytes(self.data)


class WriteAttempt:
    def __init__(self, ticket: int) -> None:
        self.ticket = ticket
        self.started = threading.Event()
        self.ready = threading.Event()
        self.done = threading.Event()
        self.thread_handle: int | None = None
        self.entered_writefile = False
        self.error: int | None = None
        self.written = 0
        self.stale = False
        self.failure: str | None = None
        self.close_failure: str | None = None
        self.thread: threading.Thread | None = None


class EpochWriter:
    def __init__(self, native: Native, handle: int, events: list[str]) -> None:
        self.native = native
        self.handle = handle
        self.events = events
        self.state_lock = threading.Lock()
        self.serializer = threading.Lock()
        self.epoch = 0
        self.interrupting = False
        self.retired = False
        self.privileged_close_write_used = False

    def start(self, payload: bytes) -> WriteAttempt:
        with self.state_lock:
            ticket = self.epoch
            if self.retired:
                raise RuntimeError("write rejected after request_close")
        attempt = WriteAttempt(ticket)

        def run() -> None:
            attempt.started.set()
            with self.serializer:
                with self.state_lock:
                    if self.retired or attempt.ticket != self.epoch:
                        attempt.stale = True
                        self.events.append("queued-released-stale")
                        attempt.done.set()
                        return
                    if self.interrupting:
                        attempt.error = ERROR_OPERATION_ABORTED
                        attempt.done.set()
                        return
                thread_handle: int | None = None
                try:
                    thread_handle = self.native.open_thread()
                    attempt.thread_handle = thread_handle
                    attempt.ready.set()
                    buffer = ctypes.create_string_buffer(payload)
                    written = DWORD()
                    attempt.entered_writefile = True
                    self.events.append("writefile-entered")
                    ok = self.native.WriteFile(
                        HANDLE(self.handle),
                        buffer,
                        len(payload),
                        ctypes.byref(written),
                        None,
                    )
                    attempt.written = int(written.value)
                    if not ok:
                        attempt.error = int(ctypes.get_last_error())  # type: ignore[attr-defined]
                        self.events.append(f"writefile-error-{attempt.error}")
                except BaseException:
                    attempt.error = -1
                    attempt.failure = traceback.format_exc()
                    self.events.append("writefile-python-failure")
                finally:
                    if thread_handle is not None:
                        try:
                            self.native.close(
                                thread_handle, "CloseHandle(writer-thread)"
                            )
                        except BaseException as exc:
                            attempt.close_failure = f"{type(exc).__name__}: {exc}"
                    attempt.done.set()

        attempt.thread = threading.Thread(
            target=run, name="conpty-input-write", daemon=True
        )
        attempt.thread.start()
        return attempt

    def write(self, payload: bytes, timeout: float = 10.0) -> WriteAttempt:
        attempt = self.start(payload)
        if not attempt.done.wait(timeout):
            raise RuntimeError("bounded ConPTY input write did not finish")
        assert attempt.thread is not None
        attempt.thread.join()
        if (
            attempt.error is not None
            or attempt.stale
            or attempt.failure is not None
            or attempt.close_failure is not None
        ):
            raise RuntimeError(
                "ConPTY input write failed: "
                f"error={attempt.error}, stale={attempt.stale}, "
                f"failure={attempt.failure}, close_failure={attempt.close_failure}"
            )
        return attempt

    def privileged_close_interrupt(self, timeout: float = 20.0) -> WriteAttempt:
        with self.state_lock:
            assert self.retired
            assert not self.privileged_close_write_used
            self.privileged_close_write_used = True
            ticket = self.epoch
        attempt = WriteAttempt(ticket)

        def run() -> None:
            thread_handle: int | None = None
            with self.serializer:
                try:
                    thread_handle = self.native.open_thread()
                    attempt.thread_handle = thread_handle
                    attempt.ready.set()
                    payload = b"\x03"
                    buf = ctypes.create_string_buffer(payload)
                    count = DWORD()
                    attempt.entered_writefile = True
                    self.events.append("privileged-close-interrupt-entered")
                    ok = self.native.WriteFile(
                        HANDLE(self.handle), buf, 1, ctypes.byref(count), None
                    )
                    attempt.written = int(count.value)
                    if not ok:
                        attempt.error = int(ctypes.get_last_error())  # type: ignore[attr-defined]
                    elif count.value != 1:
                        attempt.failure = (
                            f"privileged Ctrl-C short write: {count.value}"
                        )
                except BaseException:
                    attempt.failure = traceback.format_exc()
                finally:
                    if thread_handle is not None:
                        try:
                            self.native.close(
                                thread_handle, "CloseHandle(privileged-writer-thread)"
                            )
                        except BaseException as exc:
                            attempt.close_failure = f"{type(exc).__name__}: {exc}"
                    attempt.done.set()

        attempt.thread = threading.Thread(
            target=run, name="conpty-privileged-close-interrupt", daemon=True
        )
        attempt.thread.start()
        if not attempt.done.wait(timeout):
            raise RuntimeError(
                "privileged graceful Ctrl-C remained blocked after request_close"
            )
        attempt.thread.join()
        if (
            attempt.error is not None
            or attempt.failure is not None
            or attempt.close_failure is not None
        ):
            raise RuntimeError(
                "privileged graceful Ctrl-C failed: "
                f"error={attempt.error}, failure={attempt.failure}, "
                f"close_failure={attempt.close_failure}"
            )
        return attempt

    def cancel_blocked(
        self, active: WriteAttempt, queued: WriteAttempt, *, terminal: bool
    ) -> dict[str, Any]:
        if not active.ready.wait(5.0):
            raise RuntimeError("blocked writer did not publish its thread handle")
        if not queued.started.wait(5.0):
            raise RuntimeError("queued writer did not start")
        if active.done.is_set():
            raise RuntimeError("could not force ConPTY input WriteFile to block")
        with self.state_lock:
            self.epoch += 1
            self.interrupting = True
            self.retired = terminal
            self.events.append(
                "request-close-invalidate" if terminal else "interrupt-invalidate"
            )
        assert active.thread_handle is not None
        deadline = time.monotonic() + 5.0
        while True:
            ok = self.native.CancelSynchronousIo(HANDLE(active.thread_handle))
            if ok:
                self.events.append("cancel-returned-true")
                break
            error = int(ctypes.get_last_error())  # type: ignore[attr-defined]
            if error != ERROR_NOT_FOUND:
                raise Win32Failure("CancelSynchronousIo", error)
            if active.done.is_set():
                raise RuntimeError(
                    "blocked WriteFile completed before CancelSynchronousIo owned it"
                )
            if time.monotonic() >= deadline:
                raise RuntimeError(
                    "CancelSynchronousIo never observed the blocked WriteFile"
                )
            active.done.wait(0.001)
        if not active.done.wait(5.0):
            raise RuntimeError("cancelled ConPTY writer did not observe cancellation")
        assert active.thread is not None
        active.thread.join()
        if active.error != ERROR_OPERATION_ABORTED:
            raise RuntimeError(
                "cancelled ConPTY WriteFile did not return ERROR_OPERATION_ABORTED: "
                f"{active.error}"
            )
        if active.failure is not None or active.close_failure is not None:
            raise RuntimeError(
                "cancelled writer worker cleanup failed: "
                f"failure={active.failure}, close_failure={active.close_failure}"
            )
        self.events.append("active-observed-995")
        if not queued.done.wait(5.0):
            raise RuntimeError("queued ConPTY writer was not released")
        assert queued.thread is not None
        queued.thread.join()
        if not queued.stale or queued.entered_writefile:
            raise RuntimeError("queued old-epoch writer entered WriteFile")
        if queued.failure is not None or queued.close_failure is not None:
            raise RuntimeError(
                "queued writer worker cleanup failed: "
                f"failure={queued.failure}, close_failure={queued.close_failure}"
            )
        rearmed = False
        if not terminal:
            with self.state_lock:
                self.interrupting = False
                self.events.append("rearm-new-epoch")
                rearmed = True
        return {
            "blocked_write_error": active.error,
            "queued_entered_writefile": queued.entered_writefile,
            "queued_stale": queued.stale,
            "rearmed": rearmed,
        }


class ConPtyOwner:
    def __init__(self, native: Native, helper: Path) -> None:
        self.native = native
        self.helper = helper
        self.input_read: int | None = None
        self.input_write: int | None = None
        self.output_read: int | None = None
        self.output_write: int | None = None
        self.hpcon: int | None = None
        self.attr_buffer: Any | None = None
        self.attr_initialized = False
        self.process_handle: int | None = None
        self.thread_handle: int | None = None
        self.pid: int | None = None
        self.drain: OutputDrain | None = None
        self.closed = False
        self.cleanup: list[str] = []
        self.rollback_evidence: dict[str, Any] | None = None

    def _pipe(self) -> tuple[int, int]:
        read = HANDLE()
        write = HANDLE()
        self.native.require_bool(
            "CreatePipe",
            self.native.CreatePipe(ctypes.byref(read), ctypes.byref(write), None, 0),
        )
        return self.native.value(read), self.native.value(write)

    def spawn(self, *, inject_pre_resume_failure: bool = False) -> None:
        self.input_read, self.input_write = self._pipe()
        self.output_read, self.output_write = self._pipe()
        hpcon = HPCON()
        hr = int(
            self.native.CreatePseudoConsole(
                COORD(80, 24),
                HANDLE(self.input_read),
                HANDLE(self.output_write),
                0,
                ctypes.byref(hpcon),
            )
        )
        self.native.record("CreatePseudoConsole", hr, None)
        if hr < 0:
            raise RuntimeError(
                f"CreatePseudoConsole failed with HRESULT 0x{hr & 0xFFFFFFFF:08x}"
            )
        self.hpcon = self.native.value(hpcon)

        size = SIZE_T()
        ctypes.set_last_error(0)  # type: ignore[attr-defined]
        initial = self.native.InitializeProcThreadAttributeList(
            None, 1, 0, ctypes.byref(size)
        )
        sizing_error = int(ctypes.get_last_error())  # type: ignore[attr-defined]
        self.native.record(
            "InitializeProcThreadAttributeList(size)", bool(initial), sizing_error
        )
        if initial or sizing_error != ERROR_INSUFFICIENT_BUFFER or size.value == 0:
            raise RuntimeError(
                "attribute-list sizing did not return ERROR_INSUFFICIENT_BUFFER"
            )
        self.attr_buffer = ctypes.create_string_buffer(size.value)
        attr = ctypes.cast(self.attr_buffer, LPVOID)
        self.native.require_bool(
            "InitializeProcThreadAttributeList",
            self.native.InitializeProcThreadAttributeList(
                attr, 1, 0, ctypes.byref(size)
            ),
        )
        self.attr_initialized = True
        self.native.require_bool(
            "UpdateProcThreadAttribute(PSEUDOCONSOLE)",
            self.native.UpdateProcThreadAttribute(
                attr,
                0,
                PROC_THREAD_ATTRIBUTE_PSEUDOCONSOLE,
                LPVOID(self.hpcon),
                ctypes.sizeof(HPCON),
                None,
                None,
            ),
        )
        startup = STARTUPINFOEXW()
        startup.StartupInfo.cb = ctypes.sizeof(STARTUPINFOEXW)
        # A redirected parent can otherwise have its standard handles duplicated
        # into the client even with bInheritHandles=False.  Null standard handles
        # plus STARTF_USESTDHANDLES let the pseudoconsole supply the console I/O.
        startup.StartupInfo.dwFlags = STARTF_USESTDHANDLES
        startup.lpAttributeList = attr
        command = ctypes.create_unicode_buffer(
            subprocess.list2cmdline([sys.executable, str(self.helper), "--client"])
        )
        info = PROCESS_INFORMATION()
        self.native.require_bool(
            "CreateProcessW",
            self.native.CreateProcessW(
                None,
                command,
                None,
                None,
                0,
                EXTENDED_STARTUPINFO_PRESENT
                | CREATE_UNICODE_ENVIRONMENT
                | CREATE_SUSPENDED,
                None,
                None,
                ctypes.byref(startup.StartupInfo),
                ctypes.byref(info),
            ),
        )
        self.process_handle = self.native.value(info.hProcess)
        self.thread_handle = self.native.value(info.hThread)
        self.pid = int(info.dwProcessId)
        self.native.DeleteProcThreadAttributeList(attr)
        self.native.record("DeleteProcThreadAttributeList", True, None)
        self.attr_initialized = False
        self.attr_buffer = None

        # The ConPTY-facing pipe handles remain live through CreateProcessW.
        self.native.close(self.input_read, "CloseHandle(ConPTY-input-read)")
        self.cleanup.append("conpty-input-read-after-create-process")
        self.input_read = None
        self.native.close(self.output_write, "CloseHandle(ConPTY-output-write)")
        self.cleanup.append("conpty-output-write-after-create-process")
        self.output_write = None
        assert self.output_read is not None
        self.drain = OutputDrain(self.native, self.output_read)
        self.drain.start()
        if inject_pre_resume_failure:
            self.rollback_evidence = self._rollback_pre_resume_failure()
            raise InjectedPreResumeFailure(
                "deliberate post-CreateProcessW/pre-ResumeThread failure"
            )
        previous = int(self.native.ResumeThread(HANDLE(self.thread_handle)))
        self.native.record(
            "ResumeThread",
            previous,
            0 if previous != DWORD_FAILURE else int(ctypes.get_last_error()),
        )  # type: ignore[attr-defined]
        if previous != 1:
            raise RuntimeError(f"ResumeThread returned {previous}; expected 1")
        self.native.close(self.thread_handle, "CloseHandle(primary-thread)")
        self.cleanup.append("primary-thread-after-resume")
        self.thread_handle = None

    def _rollback_pre_resume_failure(self) -> dict[str, Any]:
        if (
            self.process_handle is None
            or self.thread_handle is None
            or self.hpcon is None
            or self.drain is None
            or self.pid is None
        ):
            raise RuntimeError("pre-resume rollback transaction is incomplete")
        identity = psutil.Process(self.pid)
        self.native.require_bool(
            "TerminateProcess(pre-resume-rollback)",
            self.native.TerminateProcess(HANDLE(self.process_handle), 96),
        )
        wait = int(self.native.WaitForSingleObject(HANDLE(self.process_handle), 5_000))
        self.native.record("WaitForSingleObject(pre-resume-rollback)", wait, 0)
        if wait != WAIT_OBJECT_0:
            raise RuntimeError(f"pre-resume rollback wait returned {wait}")
        self.native.close(self.thread_handle, "CloseHandle(rollback-primary-thread)")
        self.thread_handle = None
        reader_alive = self.drain.thread.is_alive()
        self.native.ClosePseudoConsole(HPCON(self.hpcon))
        self.native.record("ClosePseudoConsole(pre-resume-rollback)", True, None)
        self.hpcon = None
        if not self.drain.done.wait(5.0):
            raise RuntimeError("pre-resume rollback output drain did not finish")
        self.drain.thread.join()
        if self.drain.failure is not None:
            raise RuntimeError(self.drain.failure)
        self.native.close(self.process_handle, "CloseHandle(rollback-primary-process)")
        self.process_handle = None
        self.native.close(self.input_write, "CloseHandle(rollback-input-write)")
        self.input_write = None
        self.native.close(self.output_read, "CloseHandle(rollback-output-read)")
        self.output_read = None
        self.closed = True
        return {
            "injected_after_create_before_resume": True,
            "terminate_process": True,
            "bounded_wait_result": wait,
            "reader_alive_at_close": reader_alive,
            "reader_terminal_error": self.drain.terminal_error,
            "process_absent": wait_absent(identity),
        }

    def close(self) -> dict[str, Any]:
        if self.hpcon is None or self.drain is None or self.process_handle is None:
            raise RuntimeError("ConPTY owner is incomplete")
        reader_alive = self.drain.thread.is_alive()
        before = len(self.drain.snapshot())
        started = time.monotonic()
        self.native.ClosePseudoConsole(HPCON(self.hpcon))
        self.native.record("ClosePseudoConsole", True, None)
        self.cleanup.append("pseudoconsole-closed-with-reader-live")
        self.hpcon = None
        elapsed = time.monotonic() - started
        if not self.drain.done.wait(10.0):
            raise RuntimeError(
                "ConPTY output reader did not reach broken pipe after close"
            )
        self.drain.thread.join()
        if self.drain.failure is not None:
            raise RuntimeError(self.drain.failure)
        after = len(self.drain.snapshot())
        wait = int(self.native.WaitForSingleObject(HANDLE(self.process_handle), 10_000))
        self.native.record("WaitForSingleObject(leader)", wait, 0)
        if wait != WAIT_OBJECT_0:
            error = int(ctypes.get_last_error()) if wait == WAIT_FAILED else None  # type: ignore[attr-defined]
            raise RuntimeError(f"leader wait failed: result={wait}, error={error}")
        status = DWORD()
        self.native.require_bool(
            "GetExitCodeProcess",
            self.native.GetExitCodeProcess(
                HANDLE(self.process_handle), ctypes.byref(status)
            ),
        )
        if status.value == STILL_ACTIVE:
            raise RuntimeError("leader remained STILL_ACTIVE after ConPTY close")
        self.native.close(self.process_handle, "CloseHandle(primary-process)")
        self.cleanup.append("primary-process-after-wait")
        self.process_handle = None
        self.native.close(self.input_write, "CloseHandle(parent-input-write)")
        self.input_write = None
        self.native.close(self.output_read, "CloseHandle(parent-output-read)")
        self.output_read = None
        self.closed = True
        return {
            "reader_alive_at_close": reader_alive,
            "reader_terminal_error": self.drain.terminal_error,
            "bytes_at_close": before,
            "bytes_after_close": after,
            "close_seconds": elapsed,
            "leader_exit_code": int(status.value),
        }

    def emergency_cleanup(self) -> None:
        if self.attr_initialized and self.attr_buffer is not None:
            self.native.DeleteProcThreadAttributeList(
                ctypes.cast(self.attr_buffer, LPVOID)
            )
            self.attr_initialized = False
        if self.process_handle is not None:
            self.native.TerminateProcess(HANDLE(self.process_handle), 97)
            self.native.WaitForSingleObject(HANDLE(self.process_handle), 5_000)
        if self.hpcon is not None:
            self.native.ClosePseudoConsole(HPCON(self.hpcon))
            self.hpcon = None
        for name in (
            "thread_handle",
            "process_handle",
            "input_read",
            "input_write",
            "output_read",
            "output_write",
        ):
            value = getattr(self, name)
            if value is not None:
                try:
                    self.native.close(value, f"CloseHandle(emergency-{name})")
                except OSError:
                    pass
                setattr(self, name, None)


def send_control(port: int, command: str) -> None:
    with socket.create_connection(("127.0.0.1", port), timeout=5.0) as conn:
        conn.sendall(command.encode("ascii") + b"\n")
        reply = conn.recv(100)
    if reply != b"OK\n":
        raise RuntimeError(f"client control rejected {command!r}: {reply!r}")


def parse_ready(data: bytes) -> tuple[int, int, int]:
    import re

    match = re.search(rb"READY leader=(\d+) descendant=(\d+) control=(\d+)", data)
    if match is None:
        raise RuntimeError(f"malformed ConPTY READY output: {data[-2000:]!r}")
    return tuple(map(int, match.groups()))  # type: ignore[return-value]


def wait_absent(process: psutil.Process, timeout: float = 10.0) -> bool:
    try:
        process.wait(timeout=timeout)
    except psutil.NoSuchProcess:
        return True
    except psutil.TimeoutExpired:
        return False
    return not process.is_running()


def pipe_attach_probe(native: Native) -> dict[str, Any]:
    read = HANDLE()
    write = HANDLE()
    native.require_bool(
        "CreatePipe(pipe-attach)",
        native.CreatePipe(ctypes.byref(read), ctypes.byref(write), None, 0),
    )
    read_value, write_value = native.value(read), native.value(write)
    mode = DWORD()
    ctypes.set_last_error(0)  # type: ignore[attr-defined]
    classified = native.GetConsoleMode(HANDLE(read_value), ctypes.byref(mode))
    classification_error = int(ctypes.get_last_error())  # type: ignore[attr-defined]
    if classified or classification_error != ERROR_INVALID_HANDLE:
        raise RuntimeError(
            f"pipe classification returned {classified}, error={classification_error}"
        )

    def write(data: bytes) -> None:
        buf = ctypes.create_string_buffer(data)
        count = DWORD()
        native.require_bool(
            "WriteFile(pipe-attach)",
            native.WriteFile(
                HANDLE(write_value), buf, len(data), ctypes.byref(count), None
            ),
        )
        if count.value != len(data):
            raise RuntimeError("pipe attach WriteFile was short")

    def read_chunk() -> bytes:
        buf = ctypes.create_string_buffer(64)
        count = DWORD()
        native.require_bool(
            "ReadFile(pipe-attach)",
            native.ReadFile(
                HANDLE(read_value), buf, len(buf), ctypes.byref(count), None
            ),
        )
        return buf.raw[: count.value]

    forwarded = bytearray()
    pending = b""
    detached = False
    try:
        for chunk in (b"before\x1c", b"\x1cafter"):
            write(chunk)
            data = read_chunk()
            for byte in data:
                candidate = pending + bytes([byte])
                if b"\x1c\x1c".startswith(candidate):
                    pending = candidate
                    if pending == b"\x1c\x1c":
                        pending = b""
                        detached = True
                        break
                    continue
                forwarded.extend(pending)
                pending = b""
                forwarded.append(byte)
            if detached:
                break
    finally:
        native.close(read_value, "CloseHandle(pipe-attach-read)")
        native.close(write_value, "CloseHandle(pipe-attach-write)")
    return {
        "classification_error": classification_error,
        "forwarded": forwarded.decode("ascii"),
        "detached": detached,
        "set_console_mode_calls": 0,
    }


def run_console_probe(result_path: Path) -> int:
    evidence: dict[str, Any] = {"ok": False}
    try:
        import msvcrt

        native = Native()
        if ctypes.sizeof(INPUT_RECORD) != 20:
            raise RuntimeError(
                f"INPUT_RECORD ABI size is {ctypes.sizeof(INPUT_RECORD)}, expected 20"
            )
        borrowed_in = int(msvcrt.get_osfhandle(0))
        borrowed_out = int(msvcrt.get_osfhandle(1))
        current = native.GetCurrentProcess()
        owned_in = HANDLE()
        owned_out = HANDLE()
        native.require_bool(
            "DuplicateHandle(console-input)",
            native.DuplicateHandle(
                current,
                HANDLE(borrowed_in),
                current,
                ctypes.byref(owned_in),
                0,
                0,
                DUPLICATE_SAME_ACCESS,
            ),
        )
        native.require_bool(
            "DuplicateHandle(console-output)",
            native.DuplicateHandle(
                current,
                HANDLE(borrowed_out),
                current,
                ctypes.byref(owned_out),
                0,
                0,
                DUPLICATE_SAME_ACCESS,
            ),
        )
        input_handle = native.value(owned_in)
        output_handle = native.value(owned_out)
        saved_in = DWORD()
        saved_out = DWORD()
        native.require_bool(
            "GetConsoleMode(input)",
            native.GetConsoleMode(HANDLE(input_handle), ctypes.byref(saved_in)),
        )
        native.require_bool(
            "GetConsoleMode(output)",
            native.GetConsoleMode(HANDLE(output_handle), ctypes.byref(saved_out)),
        )
        saved_cp_in = int(native.GetConsoleCP())
        saved_cp_out = int(native.GetConsoleOutputCP())
        if not saved_cp_in or not saved_cp_out:
            raise RuntimeError("new console returned a zero code page")
        raw_in = (
            saved_in.value | ENABLE_EXTENDED_FLAGS | ENABLE_VIRTUAL_TERMINAL_INPUT
        ) & ~(
            ENABLE_PROCESSED_INPUT
            | ENABLE_LINE_INPUT
            | ENABLE_ECHO_INPUT
            | ENABLE_QUICK_EDIT_MODE
        )
        raw_out = (
            saved_out.value
            | ENABLE_PROCESSED_OUTPUT
            | ENABLE_VIRTUAL_TERMINAL_PROCESSING
        )
        read_ready = threading.Event()
        read_done = threading.Event()
        read_state: dict[str, Any] = {}
        utf8_ready = threading.Event()
        utf8_done = threading.Event()
        utf8_state: dict[str, Any] = {}
        console_text = "café λ"
        expected_utf8 = console_text.encode()
        output_bytes = (console_text + "\r\n").encode()
        output_count = DWORD()

        def read_injected_utf8() -> None:
            try:
                utf8_ready.set()
                received = bytearray()
                while len(received) < len(expected_utf8):
                    buf = ctypes.create_string_buffer(64)
                    count = DWORD()
                    native.require_bool(
                        "ReadFile(console-utf8-input)",
                        native.ReadFile(
                            HANDLE(input_handle),
                            buf,
                            len(buf),
                            ctypes.byref(count),
                            None,
                        ),
                    )
                    received.extend(buf.raw[: count.value])
                utf8_state["received"] = bytes(received)
            except BaseException:
                utf8_state["failure"] = traceback.format_exc()
            finally:
                utf8_done.set()

        def blocked_read() -> None:
            thread_handle: int | None = None
            try:
                thread_handle = native.open_thread()
                read_state["thread_handle"] = thread_handle
                read_ready.set()
                buf = ctypes.create_string_buffer(1)
                count = DWORD()
                ok = native.ReadFile(
                    HANDLE(input_handle), buf, 1, ctypes.byref(count), None
                )
                read_state["ok"] = bool(ok)
                read_state["error"] = 0 if ok else int(ctypes.get_last_error())  # type: ignore[attr-defined]
            except BaseException:
                read_state["failure"] = traceback.format_exc()
                read_ready.set()
            finally:
                if thread_handle is not None:
                    try:
                        native.close(
                            thread_handle, "CloseHandle(console-reader-thread)"
                        )
                    except BaseException as exc:
                        read_state["close_failure"] = f"{type(exc).__name__}: {exc}"
                read_done.set()

        try:
            native.require_bool(
                "SetConsoleMode(input-raw-vt)",
                native.SetConsoleMode(HANDLE(input_handle), raw_in),
            )
            native.require_bool(
                "SetConsoleMode(output-vt)",
                native.SetConsoleMode(HANDLE(output_handle), raw_out),
            )
            native.require_bool("SetConsoleCP(utf8)", native.SetConsoleCP(CP_UTF8))
            native.require_bool(
                "SetConsoleOutputCP(utf8)", native.SetConsoleOutputCP(CP_UTF8)
            )
            output_buffer = ctypes.create_string_buffer(output_bytes)
            native.require_bool(
                "WriteFile(console-utf8-output)",
                native.WriteFile(
                    HANDLE(output_handle),
                    output_buffer,
                    len(output_bytes),
                    ctypes.byref(output_count),
                    None,
                ),
            )
            if output_count.value != len(output_bytes):
                raise RuntimeError(
                    "console UTF-8 output was a short write: "
                    f"{output_count.value} of {len(output_bytes)}"
                )

            utf8_reader = threading.Thread(
                target=read_injected_utf8, name="console-utf8-read", daemon=True
            )
            utf8_reader.start()
            if not utf8_ready.wait(5.0):
                raise RuntimeError("console UTF-8 reader did not start")
            records = (INPUT_RECORD * len(console_text))()
            for index, char in enumerate(console_text):
                records[index].EventType = KEY_EVENT
                records[index].Event.KeyEvent.bKeyDown = 1
                records[index].Event.KeyEvent.wRepeatCount = 1
                records[index].Event.KeyEvent.uChar.UnicodeChar = char
            injected = DWORD()
            native.require_bool(
                "WriteConsoleInputW(test-only-utf8-injection)",
                native.WriteConsoleInputW(
                    HANDLE(input_handle),
                    records,
                    len(records),
                    ctypes.byref(injected),
                ),
            )
            if injected.value != len(records):
                raise RuntimeError(
                    f"WriteConsoleInputW injected {injected.value} of {len(records)}"
                )
            if not utf8_done.wait(5.0):
                raise RuntimeError("raw console UTF-8 ReadFile did not finish")
            utf8_reader.join()
            if utf8_state.get("failure") is not None:
                raise RuntimeError(utf8_state["failure"])
            if utf8_state.get("received") != expected_utf8:
                raise RuntimeError(
                    "raw console ReadFile did not return exact UTF-8 bytes: "
                    f"{utf8_state.get('received')!r} != {expected_utf8!r}"
                )

            reader = threading.Thread(
                target=blocked_read, name="console-blocked-read", daemon=True
            )
            reader.start()
            if not read_ready.wait(5.0):
                raise RuntimeError("console reader did not publish ownership")
            if "failure" in read_state:
                raise RuntimeError(read_state["failure"])
            time.sleep(0.05)
            thread_handle = read_state.get("thread_handle")
            if thread_handle is None:
                raise RuntimeError("console reader published no thread handle")
            if not native.CancelSynchronousIo(HANDLE(thread_handle)):
                error = int(ctypes.get_last_error())  # type: ignore[attr-defined]
                raise Win32Failure("CancelSynchronousIo(console-read)", error)
            if not read_done.wait(5.0):
                raise RuntimeError("cancelled console ReadFile did not return")
            reader.join()
            if read_state.get("error") != ERROR_OPERATION_ABORTED:
                raise RuntimeError(
                    "console ReadFile did not return ERROR_OPERATION_ABORTED: "
                    f"{read_state}"
                )
            if read_state.get("close_failure") is not None:
                raise RuntimeError(read_state["close_failure"])
        finally:
            restore_errors: list[str] = []
            for operation, call in (
                (
                    "SetConsoleMode(input-restore)",
                    lambda: native.SetConsoleMode(HANDLE(input_handle), saved_in.value),
                ),
                (
                    "SetConsoleMode(output-restore)",
                    lambda: native.SetConsoleMode(
                        HANDLE(output_handle), saved_out.value
                    ),
                ),
                ("SetConsoleCP(restore)", lambda: native.SetConsoleCP(saved_cp_in)),
                (
                    "SetConsoleOutputCP(restore)",
                    lambda: native.SetConsoleOutputCP(saved_cp_out),
                ),
            ):
                try:
                    native.require_bool(operation, call())
                except BaseException as exc:
                    restore_errors.append(f"{operation}: {exc}")
            restored_in = DWORD()
            restored_out = DWORD()
            input_mode_restored = (
                bool(
                    native.GetConsoleMode(
                        HANDLE(input_handle), ctypes.byref(restored_in)
                    )
                )
                and restored_in.value == saved_in.value
            )
            output_mode_restored = (
                bool(
                    native.GetConsoleMode(
                        HANDLE(output_handle), ctypes.byref(restored_out)
                    )
                )
                and restored_out.value == saved_out.value
            )
            input_cp_restored = int(native.GetConsoleCP()) == saved_cp_in
            output_cp_restored = int(native.GetConsoleOutputCP()) == saved_cp_out
            native.close(input_handle, "CloseHandle(console-input-duplicate)")
            native.close(output_handle, "CloseHandle(console-output-duplicate)")
            borrowed_mode = DWORD()
            borrowed_valid = bool(
                native.GetConsoleMode(HANDLE(borrowed_in), ctypes.byref(borrowed_mode))
            )
            evidence.update(
                {
                    "input_mode_restored": input_mode_restored,
                    "output_mode_restored": output_mode_restored,
                    "input_code_page_restored": input_cp_restored,
                    "output_code_page_restored": output_cp_restored,
                    "borrowed_handle_valid": borrowed_valid,
                    "blocked_read_error": read_state.get("error"),
                    "utf8_input_hex": expected_utf8.hex(),
                    "utf8_input_exact": utf8_state.get("received") == expected_utf8,
                    "utf8_output_byte_count": int(output_count.value),
                    "utf8_output_expected_byte_count": len(output_bytes),
                    "test_only_input_api": "WriteConsoleInputW",
                    "restore_errors": restore_errors,
                    "saved_input_mode": int(saved_in.value),
                    "saved_output_mode": int(saved_out.value),
                    "raw_input_mode": int(raw_in),
                    "raw_output_mode": int(raw_out),
                    "saved_input_code_page": saved_cp_in,
                    "saved_output_code_page": saved_cp_out,
                }
            )
            if restore_errors:
                raise RuntimeError("; ".join(restore_errors))
        evidence["ok"] = True
    except BaseException as exc:
        evidence["failure"] = f"{type(exc).__name__}: {exc}"
        evidence["traceback"] = traceback.format_exc()
    result_path.write_text(json.dumps(evidence, sort_keys=True), encoding="utf-8")
    return 0 if evidence["ok"] else 1


def run_descendant() -> NoReturn:
    signal.signal(signal.SIGINT, lambda _sig, _frame: None)
    print(f"DESCENDANT_READY {os.getpid()}", flush=True)
    while True:
        time.sleep(1.0)


def run_client(helper: Path) -> NoReturn:
    import msvcrt

    interrupt_count = 0
    reading = threading.Event()
    reading.set()
    discard_until: list[str | None] = [None]

    descendant = subprocess.Popen(
        [sys.executable, str(helper), "--descendant"], close_fds=True
    )
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("127.0.0.1", 0))
    server.listen()
    port = int(server.getsockname()[1])

    def control() -> None:
        while True:
            conn, _address = server.accept()
            with conn:
                command = conn.recv(200).decode("ascii").strip()
                if command.startswith("RESUME "):
                    discard_until[0] = command.removeprefix("RESUME ")
                    reading.set()
                elif command == "STOP":
                    reading.set()
                conn.sendall(b"OK\n")

    threading.Thread(target=control, daemon=True, name="probe-control").start()
    print(
        f"READY leader={os.getpid()} descendant={descendant.pid} control={port}",
        flush=True,
    )
    command = ""
    rolling = ""
    while True:
        reading.wait()
        char = msvcrt.getwch()
        if char == "\x03":
            interrupt_count += 1
            print(f"INTERRUPT {interrupt_count}", flush=True)
            continue
        token = discard_until[0]
        if token is not None:
            rolling = (rolling + char)[-max(256, len(token) + 4) :]
            if rolling.endswith(f"SYNC:{token}\r"):
                discard_until[0] = None
                rolling = ""
                print(f"SYNCED {token}", flush=True)
            continue
        if char not in ("\r", "\n"):
            command += char
            continue
        if not command:
            continue
        if command.startswith("ECHO:"):
            encoded = base64.b64encode(command[5:].encode("utf-8")).decode("ascii")
            print(f"ECHO {encoded}", flush=True)
        elif command == "VT":
            print("\x1b[31mVT_RED\x1b[0m", flush=True)
        elif command == "PAUSE1":
            reading.clear()
            print(f"PAUSED {command}", flush=True)
        elif command == "PAUSE_CLOSE":
            reading.clear()
            threading.Timer(3.0, reading.set).start()
            print("PAUSED PAUSE_CLOSE", flush=True)
        elif command == "FLOOD":
            sys.stdout.write("F" * (1024 * 1024))
            print("FLOOD_DONE", flush=True)
        command = ""


def run_coordinator(helper: Path) -> int:
    evidence: dict[str, Any] = {"ok": False}
    owner: ConPtyOwner | None = None
    try:
        native = Native()
        evidence["abi"] = {
            "pointer_size": ctypes.sizeof(ctypes.c_void_p),
            "coord_size": ctypes.sizeof(COORD),
            "startup_info_size": ctypes.sizeof(STARTUPINFOW),
            "startup_info_ex_size": ctypes.sizeof(STARTUPINFOEXW),
            "process_information_size": ctypes.sizeof(PROCESS_INFORMATION),
        }
        if ctypes.sizeof(COORD) != 4:
            raise RuntimeError(f"COORD ABI size is {ctypes.sizeof(COORD)}, expected 4")

        failed_owner = ConPtyOwner(native, helper)
        try:
            try:
                failed_owner.spawn(inject_pre_resume_failure=True)
            except InjectedPreResumeFailure:
                if failed_owner.rollback_evidence is None:
                    raise RuntimeError(
                        "pre-resume rollback emitted no evidence"
                    ) from None
                evidence["pre_resume_failure"] = failed_owner.rollback_evidence
            else:
                raise RuntimeError("deliberate pre-resume failure did not fire")
        except BaseException:
            if not failed_owner.closed:
                failed_owner.emergency_cleanup()
            raise

        owner = ConPtyOwner(native, helper)
        owner.spawn()
        assert owner.drain is not None and owner.input_write is not None
        ready_data = owner.drain.wait_for(b"READY ")
        leader_pid, descendant_pid, port = parse_ready(ready_data)
        owner.drain.wait_for(f"DESCENDANT_READY {descendant_pid}".encode())
        if owner.pid != leader_pid:
            raise RuntimeError(
                f"CreateProcessW pid {owner.pid} disagrees with child pid {leader_pid}"
            )
        leader_identity = psutil.Process(leader_pid)
        descendant_identity = psutil.Process(descendant_pid)

        events: list[str] = []
        writer = EpochWriter(native, owner.input_write, events)
        echo_text = "café λ red"
        writer.write(f"ECHO:{echo_text}\r".encode())
        expected_echo = base64.b64encode(echo_text.encode("utf-8"))
        owner.drain.wait_for(b"ECHO " + expected_echo)
        vt_start = len(owner.drain.snapshot())
        writer.write(b"VT\r")
        vt_deadline = time.monotonic() + 10.0
        while True:
            vt_output = owner.drain.snapshot()[vt_start:]
            marker_index = vt_output.find(b"\x1b[31mVT_RED")
            if marker_index >= 0:
                break
            if time.monotonic() >= vt_deadline:
                raise RuntimeError(
                    "ConPTY output did not preserve the color VT sequence: "
                    f"{vt_output[-2000:]!r}"
                )
            time.sleep(0.01)
        evidence["io"] = {
            "utf8_vt_round_trip": True,
            "echo_base64": expected_echo.decode("ascii"),
            "vt_output": "red-sgr-observed",
        }

        sink1_read, sink1_write = owner._pipe()
        sink1 = AttachSink(native, sink1_write, 1)
        sink1.start()
        owner.drain.register_sink(1, sink1)
        writer.write(b"FLOOD\r")
        owner.drain.wait_for(b"FLOOD_DONE", timeout=20.0)
        sink1.wait_blocked()
        if owner.drain.unregister_sink(1) is not sink1:
            raise RuntimeError("unregistered attach sink identity changed")
        first_sink = sink1.retire(require_cancel=True)
        if sink1.enqueue(2, b"must-not-reuse"):
            raise RuntimeError(
                "retired attach generation accepted later-generation data"
            )
        first_sink["rejected_after_retire"] = sink1.rejected
        native.close(sink1_read, "CloseHandle(attach-sink1-read)")

        sink2_read, sink2_write = owner._pipe()
        sink2 = AttachSink(native, sink2_write, 2)
        sink2.start()
        owner.drain.register_sink(2, sink2)
        generation_marker = f"attach-generation-{time.monotonic_ns()}"
        writer.write(f"ECHO:{generation_marker}\r".encode("ascii"))
        encoded_generation_marker = base64.b64encode(generation_marker.encode("ascii"))
        output_marker = b"ECHO " + encoded_generation_marker
        owner.drain.wait_for(output_marker)
        deadline = time.monotonic() + 5.0
        while output_marker not in sink2.successful_snapshot():
            if sink2.done.wait(0.01) or time.monotonic() >= deadline:
                raise RuntimeError(
                    "later attach generation did not receive actual ConPTY output"
                )
        if owner.drain.unregister_sink(2) is not sink2:
            raise RuntimeError("later attach sink identity changed")
        second_sink = sink2.retire(require_cancel=False)
        native.close(sink2_read, "CloseHandle(attach-sink2-read)")
        evidence["attach_output"] = {
            "first_generation": first_sink,
            "second_generation": second_sink,
            "later_generation_received_output": True,
            "old_generation_rejected_reuse": sink1.rejected == 1,
            "sole_reader": owner.drain.thread.name,
        }

        writer.write(b"\x03")
        owner.drain.wait_for(b"INTERRUPT 1")

        writer.write(b"PAUSE1\r")
        owner.drain.wait_for(b"PAUSED PAUSE1")
        active = writer.start(b"x" * (64 * 1024 * 1024))
        if not active.ready.wait(5.0):
            raise RuntimeError("first blocked writer did not publish readiness")
        queued = writer.start(b"old-epoch-queued\r")
        interrupt = writer.cancel_blocked(active, queued, terminal=False)
        token = f"epoch-{time.monotonic_ns()}"
        send_control(port, f"RESUME {token}")
        writer.write(f"SYNC:{token}\r".encode("ascii"), timeout=20.0)
        owner.drain.wait_for(f"SYNCED {token}".encode(), timeout=20.0)
        writer.write(b"\x03")
        owner.drain.wait_for(b"INTERRUPT 2")
        evidence["interrupt"] = {
            **interrupt,
            "first_ctrl_c": 1,
            "post_cancel_ctrl_c": 2,
            "events": list(events),
        }

        writer.write(b"PAUSE_CLOSE\r")
        owner.drain.wait_for(b"PAUSED PAUSE_CLOSE")
        closing_active = writer.start(b"y" * (64 * 1024 * 1024))
        if not closing_active.ready.wait(5.0):
            raise RuntimeError("request-close blocked writer did not publish readiness")
        closing_queued = writer.start(b"retired-queued\r")
        request_close = writer.cancel_blocked(
            closing_active, closing_queued, terminal=True
        )
        try:
            writer.start(b"must-not-rearm")
        except RuntimeError as exc:
            request_close["post_close_rejection"] = str(exc)
        else:
            raise RuntimeError("request_close allowed a later ConPTY input write")
        privileged = writer.privileged_close_interrupt()
        owner.drain.wait_for(b"INTERRUPT 3", timeout=20.0)
        request_close["privileged_ctrl_c_written"] = privileged.written == 1
        request_close["child_interrupt_count"] = 3
        request_close["normal_injection_remained_retired"] = writer.retired
        evidence["request_close"] = request_close

        conpty = owner.close()
        conpty["leader_absent"] = wait_absent(leader_identity)
        conpty["descendant_absent"] = wait_absent(descendant_identity)
        conpty["leader_pid"] = leader_pid
        conpty["descendant_pid"] = descendant_pid
        conpty["cleanup_order"] = list(owner.cleanup)
        if not conpty["leader_absent"] or not conpty["descendant_absent"]:
            raise RuntimeError(
                "ClosePseudoConsole did not retire both attached process identities: "
                f"{conpty}"
            )
        evidence["conpty"] = conpty
        evidence["pipe_attach"] = pipe_attach_probe(native)

        with tempfile.TemporaryDirectory(prefix="taut-conpty-console-") as temp:
            result_path = Path(temp) / "console-result.json"
            startup = subprocess.STARTUPINFO()
            startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startup.wShowWindow = subprocess.SW_HIDE
            console_process = subprocess.Popen(
                [sys.executable, str(helper), "--console", str(result_path)],
                creationflags=CREATE_NEW_CONSOLE,
                startupinfo=startup,
                close_fds=True,
            )
            try:
                console_status = console_process.wait(timeout=20.0)
            except subprocess.TimeoutExpired as exc:
                console_process.kill()
                console_process.wait(timeout=5.0)
                raise RuntimeError("real-console mode probe timed out") from exc
            if not result_path.exists():
                raise RuntimeError(
                    f"real-console mode probe exited {console_status} without evidence"
                )
            console = json.loads(result_path.read_text(encoding="utf-8"))
            if console_status != 0 or not console.get("ok"):
                raise RuntimeError(f"real-console mode probe failed: {console}")
            evidence["console"] = console

        evidence["native_calls"] = native.calls
        evidence["ok"] = True
    except BaseException as exc:
        evidence["failure"] = f"{type(exc).__name__}: {exc}"
        evidence["traceback"] = traceback.format_exc()
        if owner is not None and not owner.closed:
            try:
                owner.emergency_cleanup()
            except BaseException as cleanup_exc:
                evidence["cleanup_failure"] = (
                    f"{type(cleanup_exc).__name__}: {cleanup_exc}"
                )
    print("TAUT_CONPTY_PROBE=" + json.dumps(evidence, sort_keys=True), flush=True)
    return 0 if evidence["ok"] else 1


def main() -> int:
    helper = Path(__file__).resolve()
    if len(sys.argv) < 2:
        raise SystemExit("qualification mode required")
    mode = sys.argv[1]
    if mode == "--coordinator":
        return run_coordinator(helper)
    if mode == "--client":
        run_client(helper)
    if mode == "--descendant":
        run_descendant()
    if mode == "--console" and len(sys.argv) == 3:
        return run_console_probe(Path(sys.argv[2]))
    raise SystemExit(f"unknown qualification mode: {sys.argv[1:]!r}")


if __name__ == "__main__":
    raise SystemExit(main())
