"""Narrow synchronous Win32 I/O ownership for the ConPTY backend."""

from __future__ import annotations

import ctypes
import os
import threading
from collections.abc import Callable
from ctypes import wintypes
from dataclasses import dataclass
from typing import Any, Protocol

from taut_summon._adapter import AdapterError

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

ERROR_BROKEN_PIPE = 109
ERROR_INVALID_HANDLE = 6
ERROR_INSUFFICIENT_BUFFER = 122
ERROR_NO_DATA = 232
ERROR_PIPE_NOT_CONNECTED = 233
ERROR_OPERATION_ABORTED = 995
ERROR_NOT_FOUND = 1168
WAIT_OBJECT_0 = 0
WAIT_TIMEOUT = 258
WAIT_FAILED = 0xFFFFFFFF
STILL_ACTIVE = 259
DWORD_FAILURE = 0xFFFFFFFF
CREATE_SUSPENDED = 0x00000004
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


class Win32IoError(OSError):
    """One failed documented operation and its stable Win32 error code."""

    def __init__(self, operation: str, error_code: int) -> None:
        self.operation = operation
        self.error_code = error_code
        super().__init__(
            error_code, f"{operation} failed with Win32 error {error_code}"
        )


class NativeApi:
    """Exact-width bindings for the native calls in the approved ledger."""

    CreatePipe: Any
    CreatePseudoConsole: Any
    ClosePseudoConsole: Any
    InitializeProcThreadAttributeList: Any
    UpdateProcThreadAttribute: Any
    DeleteProcThreadAttributeList: Any
    CreateProcessW: Any
    ResumeThread: Any
    TerminateProcess: Any
    ReadFile: Any
    WriteFile: Any
    GetConsoleMode: Any
    SetConsoleMode: Any
    GetConsoleCP: Any
    SetConsoleCP: Any
    GetConsoleOutputCP: Any
    SetConsoleOutputCP: Any
    GetCurrentProcess: Any
    DuplicateHandle: Any
    OpenThread: Any
    CancelSynchronousIo: Any
    WaitForSingleObject: Any
    GetExitCodeProcess: Any
    CloseHandle: Any

    def __init__(
        self,
        *,
        library: Any | None = None,
        last_error: Callable[[], int] | None = None,
    ) -> None:
        if library is None:
            if os.name != "nt":
                raise AdapterError("Windows ConPTY is available only on Windows")
            library = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
        self._last_error = last_error or ctypes.get_last_error  # type: ignore[attr-defined]
        self._library = library
        try:
            self._bind()
        except AttributeError as exc:
            missing = exc.name or "required kernel32 export"
            raise AdapterError(
                f"Windows ConPTY initialization is unavailable: missing {missing}"
            ) from exc

    def _bind(self) -> None:
        k = self._library
        signatures = {
            "CreatePipe": (
                [ctypes.POINTER(HANDLE), ctypes.POINTER(HANDLE), LPVOID, DWORD],
                BOOL,
            ),
            "CreatePseudoConsole": (
                [COORD, HANDLE, HANDLE, DWORD, ctypes.POINTER(HPCON)],
                HRESULT,
            ),
            "ClosePseudoConsole": ([HPCON], None),
            "InitializeProcThreadAttributeList": (
                [LPVOID, DWORD, DWORD, ctypes.POINTER(SIZE_T)],
                BOOL,
            ),
            "UpdateProcThreadAttribute": (
                [
                    LPVOID,
                    DWORD,
                    ULONG_PTR,
                    LPVOID,
                    SIZE_T,
                    LPVOID,
                    ctypes.POINTER(SIZE_T),
                ],
                BOOL,
            ),
            "DeleteProcThreadAttributeList": ([LPVOID], None),
            "CreateProcessW": (
                [
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
                ],
                BOOL,
            ),
            "ResumeThread": ([HANDLE], DWORD),
            "TerminateProcess": ([HANDLE, UINT], BOOL),
            "ReadFile": ([HANDLE, LPVOID, DWORD, ctypes.POINTER(DWORD), LPVOID], BOOL),
            "WriteFile": ([HANDLE, LPVOID, DWORD, ctypes.POINTER(DWORD), LPVOID], BOOL),
            "GetConsoleMode": ([HANDLE, ctypes.POINTER(DWORD)], BOOL),
            "SetConsoleMode": ([HANDLE, DWORD], BOOL),
            "GetConsoleCP": ([], UINT),
            "SetConsoleCP": ([UINT], BOOL),
            "GetConsoleOutputCP": ([], UINT),
            "SetConsoleOutputCP": ([UINT], BOOL),
            "GetCurrentProcess": ([], HANDLE),
            "DuplicateHandle": (
                [HANDLE, HANDLE, HANDLE, ctypes.POINTER(HANDLE), DWORD, BOOL, DWORD],
                BOOL,
            ),
            "OpenThread": ([DWORD, BOOL, DWORD], HANDLE),
            "CancelSynchronousIo": ([HANDLE], BOOL),
            "WaitForSingleObject": ([HANDLE, DWORD], DWORD),
            "GetExitCodeProcess": ([HANDLE, ctypes.POINTER(DWORD)], BOOL),
            "CloseHandle": ([HANDLE], BOOL),
        }
        for name, (argtypes, restype) in signatures.items():
            function = getattr(k, name)
            function.argtypes = argtypes
            function.restype = restype
            setattr(self, name, function)

    @staticmethod
    def handle_value(raw: Any, operation: str = "native call") -> int:
        value = ctypes.cast(raw, ctypes.c_void_p).value
        if value is None:
            raise Win32IoError(operation, 0)
        return int(value)

    def require_bool(self, operation: str, result: int) -> None:
        if not result:
            raise Win32IoError(operation, int(self._last_error()))

    def close_handle(self, handle: int | None) -> None:
        if handle is not None:
            self.require_bool("CloseHandle", self.CloseHandle(HANDLE(handle)))

    def create_pipe(self) -> tuple[int, int]:
        read, write = HANDLE(), HANDLE()
        self.require_bool(
            "CreatePipe",
            self.CreatePipe(ctypes.byref(read), ctypes.byref(write), None, 0),
        )
        return self.handle_value(read, "CreatePipe"), self.handle_value(
            write, "CreatePipe"
        )

    def open_current_thread(self) -> int:
        raw = self.OpenThread(THREAD_TERMINATE, 0, threading.get_native_id())
        if not raw:
            raise Win32IoError("OpenThread", int(self._last_error()))
        return self.handle_value(raw, "OpenThread")

    def cancel_thread(self, thread_handle: int, *, retiring: bool) -> bool:
        if self.CancelSynchronousIo(HANDLE(thread_handle)):
            return True
        error = int(self._last_error())
        if error == ERROR_NOT_FOUND and retiring:
            return False
        raise Win32IoError("CancelSynchronousIo", error)

    def duplicate_fd_handle(self, fd: int) -> int:
        if os.name != "nt":
            raise AdapterError(
                "Windows handle duplication is available only on Windows"
            )
        import msvcrt

        borrowed = int(msvcrt.get_osfhandle(fd))  # type: ignore[attr-defined]
        process = self.GetCurrentProcess()
        duplicate = HANDLE()
        self.require_bool(
            "DuplicateHandle",
            self.DuplicateHandle(
                process,
                HANDLE(borrowed),
                process,
                ctypes.byref(duplicate),
                0,
                0,
                DUPLICATE_SAME_ACCESS,
            ),
        )
        return self.handle_value(duplicate, "DuplicateHandle")

    def read(self, handle: int, size: int = 4096) -> bytes:
        buffer = ctypes.create_string_buffer(size)
        count = DWORD()
        if not self.ReadFile(HANDLE(handle), buffer, size, ctypes.byref(count), None):
            raise Win32IoError("ReadFile", int(self._last_error()))
        return buffer.raw[: count.value]

    def write(self, handle: int, data: bytes) -> None:
        buffer = ctypes.create_string_buffer(data)
        count = DWORD()
        self.require_bool(
            "WriteFile",
            self.WriteFile(
                HANDLE(handle), buffer, len(data), ctypes.byref(count), None
            ),
        )
        if count.value != len(data):
            raise AdapterError(f"WriteFile wrote {count.value} of {len(data)} bytes")

    def get_console_mode(self, handle: int) -> int:
        value = DWORD()
        self.require_bool(
            "GetConsoleMode", self.GetConsoleMode(HANDLE(handle), ctypes.byref(value))
        )
        return int(value.value)

    def set_console_mode(self, handle: int, value: int) -> None:
        self.require_bool("SetConsoleMode", self.SetConsoleMode(HANDLE(handle), value))

    def get_console_cp(self) -> int:
        value = int(self.GetConsoleCP())
        if value == 0:
            raise Win32IoError("GetConsoleCP", int(self._last_error()))
        return value

    def set_console_cp(self, value: int) -> None:
        self.require_bool("SetConsoleCP", self.SetConsoleCP(value))

    def get_console_output_cp(self) -> int:
        value = int(self.GetConsoleOutputCP())
        if value == 0:
            raise Win32IoError("GetConsoleOutputCP", int(self._last_error()))
        return value

    def set_console_output_cp(self, value: int) -> None:
        self.require_bool("SetConsoleOutputCP", self.SetConsoleOutputCP(value))


class ConsoleApi(Protocol):
    def get_console_mode(self, handle: int) -> int: ...
    def set_console_mode(self, handle: int, value: int) -> None: ...
    def get_console_cp(self) -> int: ...
    def set_console_cp(self, value: int) -> None: ...
    def get_console_output_cp(self) -> int: ...
    def set_console_output_cp(self, value: int) -> None: ...


@dataclass(frozen=True, slots=True)
class _ConsoleSnapshot:
    input_mode: int
    output_mode: int
    input_cp: int
    output_cp: int


class ConsoleLease:
    """Borrow a real console and restore every process-global setting exactly."""

    def __init__(
        self, *, api: ConsoleApi, input_handle: int, output_handle: int
    ) -> None:
        self._api = api
        self._input = input_handle
        self._output = output_handle
        self._snapshot: _ConsoleSnapshot | None = None

    def enter(self) -> None:
        snapshot = _ConsoleSnapshot(
            input_mode=self._api.get_console_mode(self._input),
            output_mode=self._api.get_console_mode(self._output),
            input_cp=self._api.get_console_cp(),
            output_cp=self._api.get_console_output_cp(),
        )
        self._snapshot = snapshot
        try:
            input_mode = snapshot.input_mode
            input_mode &= ~(
                ENABLE_LINE_INPUT | ENABLE_ECHO_INPUT | ENABLE_QUICK_EDIT_MODE
            )
            input_mode |= (
                ENABLE_EXTENDED_FLAGS
                | ENABLE_PROCESSED_INPUT
                | ENABLE_VIRTUAL_TERMINAL_INPUT
            )
            output_mode = (
                snapshot.output_mode
                | ENABLE_PROCESSED_OUTPUT
                | ENABLE_VIRTUAL_TERMINAL_PROCESSING
            )
            self._api.set_console_mode(self._input, input_mode)
            self._api.set_console_mode(self._output, output_mode)
            self._api.set_console_cp(CP_UTF8)
            self._api.set_console_output_cp(CP_UTF8)
        except Exception:
            self.restore()
            raise

    def restore(self) -> None:
        snapshot, self._snapshot = self._snapshot, None
        if snapshot is None:
            return
        failures: list[BaseException] = []
        restorers = (
            lambda: self._api.set_console_mode(self._input, snapshot.input_mode),
            lambda: self._api.set_console_mode(self._output, snapshot.output_mode),
            lambda: self._api.set_console_cp(snapshot.input_cp),
            lambda: self._api.set_console_output_cp(snapshot.output_cp),
        )
        for restore in restorers:
            try:
                restore()
            except (OSError, AdapterError) as exc:
                failures.append(exc)
        if failures:
            error = AdapterError(f"console restoration failed: {failures[0]}")
            for failure in failures[1:]:
                error.add_note(str(failure))
            raise error
