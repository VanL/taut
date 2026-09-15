"""Cross-platform real-terminal helpers for TUI acceptance probes."""

from __future__ import annotations

import os
import select
import sys
import threading
import time
from contextlib import ExitStack
from dataclasses import dataclass
from typing import Any


def _windows_pipe_available(fd: int) -> int:
    """Return readable bytes for a test-owned Windows anonymous pipe."""

    import ctypes
    import msvcrt

    ctypes_api: Any = ctypes
    msvcrt_api: Any = msvcrt
    kernel32 = ctypes_api.WinDLL("kernel32", use_last_error=True)
    kernel32.PeekNamedPipe.argtypes = [
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_uint32),
        ctypes.c_void_p,
    ]
    kernel32.PeekNamedPipe.restype = ctypes.c_int
    available = ctypes.c_uint32()
    if not kernel32.PeekNamedPipe(
        ctypes.c_void_p(msvcrt_api.get_osfhandle(fd)),
        None,
        0,
        None,
        ctypes.byref(available),
        None,
    ):
        error = ctypes_api.get_last_error()
        if error in (6, 109):
            return 0
        raise OSError(error, "PeekNamedPipe failed")
    return int(available.value)


class HostTerminal:
    """Test-owned host side of a real provider terminal lease.

    POSIX requires a PTY because the attach bridge changes the input terminal
    mode. Windows' ConPTY bridge accepts ordinary OS fds, so paired pipes give
    the test independent read and write directions without claiming a console.
    """

    def __init__(
        self,
        *,
        user_read_fd: int,
        user_write_fd: int,
        lease_input_fd: int,
        lease_output_fd: int,
    ) -> None:
        self.user_read_fd = user_read_fd
        self.user_write_fd = user_write_fd
        self.lease_input_fd = lease_input_fd
        self.lease_output_fd = lease_output_fd

    @classmethod
    def open(cls) -> HostTerminal:
        if os.name == "nt":
            lease_input_fd, user_write_fd = os.pipe()
            user_read_fd, lease_output_fd = os.pipe()
            return cls(
                user_read_fd=user_read_fd,
                user_write_fd=user_write_fd,
                lease_input_fd=lease_input_fd,
                lease_output_fd=lease_output_fd,
            )
        import pty

        user_fd, lease_fd = pty.openpty()
        return cls(
            user_read_fd=user_fd,
            user_write_fd=user_fd,
            lease_input_fd=lease_fd,
            lease_output_fd=lease_fd,
        )

    def read_available(self) -> bytes:
        if os.name == "nt":
            available = _windows_pipe_available(self.user_read_fd)
            if available == 0:
                return b""
            return os.read(self.user_read_fd, min(available, 65_536))
        readable, _, _ = select.select([self.user_read_fd], [], [], 0)
        if not readable:
            return b""
        try:
            return os.read(self.user_read_fd, 65_536)
        except OSError:
            return b""

    def read_until(self, needle: bytes, *, timeout: float = 15.0) -> bytes:
        deadline = time.monotonic() + timeout
        output = bytearray()
        while time.monotonic() < deadline:
            chunk = self.read_available()
            if chunk:
                output.extend(chunk)
                if needle in output:
                    break
            else:
                time.sleep(0.02)
        return bytes(output)

    def write(self, data: bytes) -> None:
        os.write(self.user_write_fd, data)

    def close(self) -> None:
        seen: set[int] = set()
        for fd in (
            self.user_read_fd,
            self.user_write_fd,
            self.lease_input_fd,
            self.lease_output_fd,
        ):
            if fd in seen:
                continue
            seen.add(fd)
            try:
                os.close(fd)
            except OSError:
                pass


@dataclass(frozen=True, slots=True)
class TerminalRun:
    output: bytes
    returncode: int
    input_sent: bool


def _start_attach(
    handle: Any,
    terminal: HostTerminal,
    wake: threading.Event,
    shutdown: threading.Event,
    errors: list[BaseException],
) -> threading.Thread:
    def attach() -> None:
        try:
            handle.attach(
                wake=wake,
                shutdown=shutdown,
                input_fd=terminal.lease_input_fd,
                output_fd=terminal.lease_output_fd,
            )
        except BaseException as exc:  # noqa: BLE001 approved [DOM-10.2.1] [RUFF-SUP-070] exception
            errors.append(exc)

    thread = threading.Thread(
        target=attach,
        name="tui-terminal-probe",
        daemon=True,
    )
    thread.start()
    return thread


def _collect_output(
    thread: threading.Thread,
    terminal: HostTerminal,
    *,
    input_when_output_contains: tuple[bytes, bytes] | None,
    timeout: float,
) -> tuple[bytes, bool]:
    output = bytearray()
    input_sent = False
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and thread.is_alive():
        chunk = terminal.read_available()
        if chunk:
            output.extend(chunk)
            if (
                input_when_output_contains is not None
                and not input_sent
                and input_when_output_contains[0] in output
            ):
                terminal.write(input_when_output_contains[1])
                input_sent = True
        else:
            thread.join(timeout=0.02)
    if thread.is_alive():
        raise TimeoutError("real-terminal child probe timed out")
    while chunk := terminal.read_available():
        output.extend(chunk)
    return bytes(output), input_sent


def _cleanup_attach(
    handle: Any,
    thread: threading.Thread,
    wake: threading.Event,
    shutdown: threading.Event,
) -> None:
    shutdown.set()
    wake.set()
    thread.join(timeout=3.0)
    close_completed = False
    try:
        handle.close()
        close_completed = True
    finally:
        thread.join(timeout=3.0)
        if thread.is_alive():
            error = RuntimeError("real-terminal attach thread survived adapter cleanup")
            if not close_completed and (close_error := sys.exception()) is not None:
                error.add_note("adapter cleanup also failed")
                raise error from close_error
            raise error


def run_terminal_child(
    source: str,
    *,
    input_when_output_contains: tuple[bytes, bytes] | None = None,
    timeout: float,
) -> TerminalRun:
    """Run Python in the real platform PTY and capture its raw terminal bytes.

    ``input_when_output_contains`` is a ``(readiness_marker, input_bytes)``
    pair. The child owns the marker and must emit it only after the terminal
    behavior under test is ready to receive input.
    """

    from taut_summon._adapter import ExitEvent
    from taut_summon._pty import PtyAdapter, PtySpec

    with ExitStack() as cleanup:
        terminal = HostTerminal.open()
        cleanup.callback(terminal.close)
        handle = PtyAdapter(
            PtySpec(
                name="tui-terminal-probe",
                argv=(sys.executable, "-c", source),
                rows=24,
                cols=80,
            )
        ).spawn(system_prompt="unused", env={})
        wake = threading.Event()
        shutdown = threading.Event()
        attach_errors: list[BaseException] = []
        with ExitStack() as failed_start_cleanup:
            failed_start_cleanup.callback(handle.close)
            thread = _start_attach(handle, terminal, wake, shutdown, attach_errors)
            failed_start_cleanup.pop_all()
        cleanup.callback(_cleanup_attach, handle, thread, wake, shutdown)
        output, input_sent = _collect_output(
            thread,
            terminal,
            input_when_output_contains=input_when_output_contains,
            timeout=timeout,
        )
        if attach_errors:
            raise RuntimeError("real-terminal attach failed") from attach_errors[0]
        events = tuple(handle.events())
        returncodes = [
            event.returncode for event in events if isinstance(event, ExitEvent)
        ]
        if len(returncodes) != 1:
            raise RuntimeError(f"terminal probe emitted exit codes {returncodes!r}")
        return TerminalRun(
            output=output,
            returncode=returncodes[0],
            input_sent=input_sent,
        )
