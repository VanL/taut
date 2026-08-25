"""Immediate Windows anonymous-pipe readiness probes [SUM-7.1]."""

from __future__ import annotations

import ctypes
import os
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from taut_summon._adapter import AdapterError

DWORD = ctypes.c_uint32
BOOL = ctypes.c_int32
HANDLE = ctypes.c_void_p
LPVOID = ctypes.c_void_p

_CLEAN_EOF_ERRORS = frozenset(
    {
        109,  # ERROR_BROKEN_PIPE: the write end was closed.
        232,  # ERROR_NO_DATA: the pipe is being closed.
        233,  # ERROR_PIPE_NOT_CONNECTED: no writer remains connected.
    }
)


class Win32PipeError(OSError):
    """A stable operation plus native code from one pipe call."""

    def __init__(self, operation: str, error_code: int) -> None:
        self.operation = operation
        self.error_code = error_code
        super().__init__(
            error_code, f"{operation} failed with Win32 error {error_code}"
        )


class PipeKernelApi(Protocol):
    """The one documented kernel operation required by the probe."""

    def available_bytes(self, handle: int) -> int: ...


class Kernel32PipeApi:
    """Exact-width binding for documented ``PeekNamedPipe``."""

    def __init__(
        self,
        *,
        library: Any | None = None,
        last_error: Callable[[], int] | None = None,
    ) -> None:
        if library is None:
            if os.name != "nt":
                raise AdapterError(
                    "Windows pipe readiness is available only on Windows"
                )
            win_dll = ctypes.WinDLL  # type: ignore[attr-defined]
            library = win_dll("kernel32", use_last_error=True)
        if last_error is None:
            last_error = ctypes.get_last_error  # type: ignore[attr-defined]
        self._last_error = last_error
        self._peek_named_pipe = library.PeekNamedPipe
        self._peek_named_pipe.argtypes = [
            HANDLE,
            LPVOID,
            DWORD,
            ctypes.POINTER(DWORD),
            ctypes.POINTER(DWORD),
            ctypes.POINTER(DWORD),
        ]
        self._peek_named_pipe.restype = BOOL

    def available_bytes(self, handle: int) -> int:
        available = DWORD()
        if not self._peek_named_pipe(
            HANDLE(handle),
            None,
            0,
            None,
            ctypes.byref(available),
            None,
        ):
            raise Win32PipeError("PeekNamedPipe", int(self._last_error()))
        return int(available.value)


@dataclass(frozen=True, slots=True)
class PipePoll:
    """One immediate observation of a pipe's readable state."""

    available: int
    eof: bool


class WindowsPipeReadiness:
    """Observe available bytes without blocking or consuming the pipe."""

    def __init__(self, *, api: PipeKernelApi, handle: int) -> None:
        self._api = api
        self._handle = handle

    @classmethod
    def from_fd(cls, fd: int) -> WindowsPipeReadiness:
        """Build the real probe for a Windows CRT pipe descriptor."""

        if os.name != "nt":
            raise AdapterError("Windows pipe readiness is available only on Windows")
        import msvcrt

        handle = msvcrt.get_osfhandle(fd)  # type: ignore[attr-defined]
        return cls(api=Kernel32PipeApi(), handle=int(handle))

    def poll(self) -> PipePoll:
        try:
            available = self._api.available_bytes(self._handle)
        except Win32PipeError as exc:
            if exc.error_code in _CLEAN_EOF_ERRORS:
                return PipePoll(available=0, eof=True)
            raise
        return PipePoll(available=available, eof=False)
