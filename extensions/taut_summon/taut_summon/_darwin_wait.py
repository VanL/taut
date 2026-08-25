"""Darwin Python 3.11/3.12 non-reaping ``waitid`` compatibility shim.

Python did not expose ``os.waitid`` on these runtimes even though Darwin's
public libc ABI provides it. This module mirrors the SDK ``siginfo_t`` fields
used by [SUM-7.1] and nothing more.
"""

from __future__ import annotations

import ctypes
import errno
import os
from typing import Any, ClassVar


class _Sigval(ctypes.Union):
    _fields_: ClassVar[list[tuple[str, Any]]] = [
        ("sival_int", ctypes.c_int),
        ("sival_ptr", ctypes.c_void_p),
    ]


class _Siginfo(ctypes.Structure):
    _fields_: ClassVar[list[tuple[str, Any]]] = [
        ("si_signo", ctypes.c_int),
        ("si_errno", ctypes.c_int),
        ("si_code", ctypes.c_int),
        ("si_pid", ctypes.c_int32),
        ("si_uid", ctypes.c_uint32),
        ("si_status", ctypes.c_int),
        ("si_addr", ctypes.c_void_p),
        ("si_value", _Sigval),
        ("si_band", ctypes.c_long),
        ("_pad", ctypes.c_ulong * 7),
    ]


if ctypes.sizeof(_Siginfo) != 104:  # pragma: no cover - supported ABI invariant
    raise RuntimeError(f"unsupported Darwin siginfo_t size: {ctypes.sizeof(_Siginfo)}")


_libc = ctypes.CDLL(None, use_errno=True)
try:
    _waitid = _libc.waitid
except AttributeError as exc:  # pragma: no cover - supported Darwin invariant
    raise RuntimeError("Darwin libc does not expose waitid") from exc
_waitid.argtypes = [
    ctypes.c_int,
    ctypes.c_uint32,
    ctypes.POINTER(_Siginfo),
    ctypes.c_int,
]
_waitid.restype = ctypes.c_int

_P_PID = 1
_WEXITED = 0x00000004
_WNOHANG = 0x00000001
_WNOWAIT = 0x00000020


def observe_exit(pid: int) -> tuple[int, int, int] | None:
    """Return ``(pid, code, status)`` without reaping, or ``None`` if live."""

    info = _Siginfo()
    while True:
        ctypes.set_errno(0)
        result = _waitid(
            _P_PID,
            ctypes.c_uint32(pid),
            ctypes.byref(info),
            _WEXITED | _WNOHANG | _WNOWAIT,
        )
        if result == 0:
            return (
                None
                if info.si_pid == 0
                else (info.si_pid, info.si_code, info.si_status)
            )
        error = ctypes.get_errno()
        if error == errno.EINTR:
            continue
        raise OSError(error, os.strerror(error))
