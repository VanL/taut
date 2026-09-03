"""Small cross-platform terminal-input helpers for real child fixtures."""

from __future__ import annotations

import os
import queue
import threading
from typing import Any


def configure_raw_input() -> None:
    """Put an interactive stdin in raw mode on POSIX or Windows."""

    if not os.isatty(0):
        return
    if os.name == "nt":
        import ctypes
        import msvcrt

        ctypes_api: Any = ctypes
        msvcrt_api: Any = msvcrt
        kernel32 = ctypes_api.WinDLL("kernel32", use_last_error=True)
        kernel32.GetConsoleMode.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_uint32),
        ]
        kernel32.GetConsoleMode.restype = ctypes.c_int
        kernel32.SetConsoleMode.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        kernel32.SetConsoleMode.restype = ctypes.c_int
        handle = msvcrt_api.get_osfhandle(0)
        mode = ctypes.c_uint32()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            raise OSError(ctypes_api.get_last_error(), "GetConsoleMode(stdin) failed")
        raw_mode = (mode.value & ~(0x0001 | 0x0002 | 0x0004)) | 0x0200
        if not kernel32.SetConsoleMode(handle, raw_mode):
            raise OSError(ctypes_api.get_last_error(), "SetConsoleMode(stdin) failed")
        return

    import tty

    tty.setraw(0)


class TerminalInput:
    """Own one blocking reader so Windows pipe input never uses ``select``."""

    _EOF = object()

    def __init__(self, fd: int = 0) -> None:
        self._fd = fd
        self._chunks: queue.Queue[bytes | object] = queue.Queue()
        self._reading = threading.Event()
        self._reading.set()
        threading.Thread(
            target=self._read,
            daemon=True,
            name="summon-fixture-input",
        ).start()

    def _read(self) -> None:
        try:
            while True:
                self._reading.wait()
                chunk = os.read(self._fd, 4096)
                if not chunk:
                    break
                self._chunks.put(chunk)
        except OSError:
            pass
        finally:
            self._chunks.put(self._EOF)

    def pause(self) -> None:
        """Stop issuing reads after any read already owned by the worker returns."""

        self._reading.clear()

    def receive(self, *, timeout: float | None = None) -> bytes | None:
        """Return bytes, ``b\"\"`` on timeout, or ``None`` at EOF."""

        try:
            chunk = self._chunks.get(timeout=timeout)
        except queue.Empty:
            return b""
        if chunk is self._EOF:
            return None
        assert isinstance(chunk, bytes)
        return chunk
