"""Deterministic Windows anonymous-pipe readiness tests [SUM-7.1]."""

from __future__ import annotations

import ctypes
import os
import sys
from types import ModuleType
from typing import Any

import pytest
import taut_summon._stream as stream_module
import taut_summon._win32_pipe as win32_pipe_module
from taut_summon._adapter import AdapterError
from taut_summon._win32_pipe import (
    BOOL,
    DWORD,
    HANDLE,
    Kernel32PipeApi,
    PipePoll,
    Win32PipeError,
    WindowsPipeReadiness,
)


class _AvailableKernel:
    def __init__(self, available: int = 23) -> None:
        self.available = available

    def available_bytes(self, handle: int) -> int:
        assert handle == 17
        return self.available


def test_pipe_readiness_reports_the_available_byte_count() -> None:
    readiness = WindowsPipeReadiness(api=_AvailableKernel(), handle=17)

    assert readiness.poll().available == 23


def test_zero_available_bytes_is_not_eof() -> None:
    readiness = WindowsPipeReadiness(api=_AvailableKernel(0), handle=17)

    assert readiness.poll().eof is False


class _FailingKernel:
    def __init__(self, error_code: int) -> None:
        self.error_code = error_code

    def available_bytes(self, handle: int) -> int:
        assert handle == 17
        raise Win32PipeError("PeekNamedPipe", self.error_code)


@pytest.mark.parametrize("error_code", [109, 232, 233])
def test_closed_or_broken_pipe_is_clean_eof(error_code: int) -> None:
    readiness = WindowsPipeReadiness(api=_FailingKernel(error_code), handle=17)

    assert readiness.poll().eof is True


def test_unexpected_peek_error_remains_fatal_with_its_native_code() -> None:
    readiness = WindowsPipeReadiness(api=_FailingKernel(5), handle=17)

    with pytest.raises(Win32PipeError) as captured:
        readiness.poll()

    assert captured.value.operation == "PeekNamedPipe"
    assert captured.value.error_code == 5


class _NativeFunction:
    def __init__(self, result: object) -> None:
        self.result = result
        self.calls: list[tuple[Any, ...]] = []
        self.argtypes: object = None
        self.restype: object = None

    def __call__(self, *args: Any) -> object:
        self.calls.append(args)
        if callable(self.result):
            return self.result(*args)
        return self.result


class _FakeKernel32:
    def __init__(self, result: object) -> None:
        self.PeekNamedPipe = _NativeFunction(result)


def test_kernel_api_binds_exact_widths_and_returns_available_bytes() -> None:
    def peek(
        raw_handle: Any,
        buffer: object,
        buffer_size: object,
        bytes_read: object,
        raw_available: Any,
        bytes_left: object,
    ) -> int:
        assert ctypes.cast(raw_handle, HANDLE).value == 17
        assert buffer is None
        assert buffer_size == 0
        assert bytes_read is None
        assert bytes_left is None
        available = ctypes.cast(raw_available, ctypes.POINTER(DWORD)).contents
        available.value = 23
        return 1

    library = _FakeKernel32(peek)
    api = Kernel32PipeApi(library=library, last_error=lambda: 5)

    assert ctypes.sizeof(BOOL) == 4
    assert ctypes.sizeof(DWORD) == 4
    assert ctypes.sizeof(HANDLE) == ctypes.sizeof(ctypes.c_void_p)
    assert library.PeekNamedPipe.restype is BOOL
    assert library.PeekNamedPipe.argtypes == [
        HANDLE,
        ctypes.c_void_p,
        DWORD,
        ctypes.POINTER(DWORD),
        ctypes.POINTER(DWORD),
        ctypes.POINTER(DWORD),
    ]
    assert api.available_bytes(17) == 23


def test_kernel_api_preserves_fatal_peek_error_code() -> None:
    library = _FakeKernel32(0)
    api = Kernel32PipeApi(library=library, last_error=lambda: 87)

    with pytest.raises(Win32PipeError) as captured:
        api.available_bytes(17)

    assert captured.value.operation == "PeekNamedPipe"
    assert captured.value.error_code == 87


def test_real_constructor_rejects_posix_before_loading_windows_modules(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    posix_os = ModuleType("os")
    posix_os.__dict__["name"] = "posix"
    monkeypatch.setattr(win32_pipe_module, "os", posix_os)

    with pytest.raises(AdapterError, match="available only on Windows"):
        WindowsPipeReadiness.from_fd(3)


def test_real_constructor_converts_only_the_supplied_crt_descriptor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    converted: list[int] = []
    msvcrt = ModuleType("msvcrt")

    def get_osfhandle(fd: int) -> int:
        converted.append(fd)
        return 17

    msvcrt.__dict__["get_osfhandle"] = get_osfhandle
    api = _AvailableKernel()
    monkeypatch.setitem(sys.modules, "msvcrt", msvcrt)
    monkeypatch.setattr(win32_pipe_module.os, "name", "nt")
    monkeypatch.setattr(win32_pipe_module, "Kernel32PipeApi", lambda: api)

    readiness = WindowsPipeReadiness.from_fd(8)

    assert converted == [8]
    assert readiness.poll().available == 23


def test_stream_reader_drains_only_peeked_bytes_without_waiting_for_eof(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = b'{"type":"result"}\n'
    read_fd, write_fd = os.pipe()
    states = iter([PipePoll(len(payload), False), PipePoll(0, False)])

    class Readiness:
        def poll(self) -> PipePoll:
            return next(states)

    monkeypatch.setattr(
        WindowsPipeReadiness,
        "from_fd",
        classmethod(lambda cls, fd: Readiness()),
    )
    os.write(write_fd, payload)
    reader = stream_module._WindowsUtf8Lines(read_fd)
    try:
        lines, eof = reader.read_available()
        assert lines == ['{"type":"result"}']
        assert eof is False
    finally:
        reader.close()
        os.close(read_fd)
        os.close(write_fd)


def test_stream_reader_normalizes_fatal_peek_error_to_adapter_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    read_fd, write_fd = os.pipe()

    class Readiness:
        def poll(self) -> PipePoll:
            raise Win32PipeError("PeekNamedPipe", 5)

    monkeypatch.setattr(
        WindowsPipeReadiness,
        "from_fd",
        classmethod(lambda cls, fd: Readiness()),
    )
    reader = stream_module._WindowsUtf8Lines(read_fd)
    try:
        with pytest.raises(AdapterError, match="Win32 error 5"):
            reader.read_available()
    finally:
        reader.close()
        os.close(read_fd)
        os.close(write_fd)
