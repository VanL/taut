"""Real-terminal helpers shared by extension acceptance suites.

The helpers live in the repository test tree, not an extension package, so
they cannot accidentally become part of either wheel.
"""

from __future__ import annotations

import errno
import os
import re
import select
import signal
import sys
import threading
import time
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import Any, Self

import psutil

_PROMPT = "TAUT-HOST-PROMPT> "
_ANSI_SEQUENCE = re.compile(
    rb"(?:\x1b\[[0-?]*[ -/]*[@-~])"
    rb"|(?:\x1b\][^\x07\x1b]*(?:\x07|\x1b\\))"
    rb"|(?:\x1b[ -/]*[0-~])"
)


def strip_terminal_bytes(data: bytes) -> str:
    """Reduce terminal bytes to stable screen-scraping text."""

    clean = _ANSI_SEQUENCE.sub(b"", data).replace(b"\r", b"")
    return clean.decode("utf-8", errors="replace")


class PosixHostShell:
    """Own an interactive shell and its controlling host PTY.

    The parent retains the slave solely for direct termios and foreground
    process-group inspection. The child becomes a session leader, acquires the
    slave with ``TIOCSCTTY``, and execs an interactive shell. Reads append to a
    cumulative transcript so callers can combine monotonic deadlines with
    phase marks instead of losing diagnostics between expectations.
    """

    def __init__(
        self,
        *,
        pid: int,
        master_fd: int,
        slave_fd: int,
        leader_create_time: float,
        prompt: str,
    ) -> None:
        self.pid = pid
        self.master_fd = master_fd
        self.slave_fd = slave_fd
        self._leader_create_time = leader_create_time
        self.prompt = prompt
        self._transcript = bytearray()
        self._closed = False

    @classmethod
    def open(
        cls,
        *,
        cwd: Path,
        env: dict[str, str] | None = None,
        prompt: str = _PROMPT,
    ) -> Self:
        if os.name == "nt":
            raise RuntimeError("PosixHostShell requires POSIX")
        import fcntl
        import pty
        import termios

        master_fd, slave_fd = pty.openpty()
        child_pid = os.fork()
        if child_pid == 0:  # pragma: no cover - behavior observed by parent
            try:
                os.close(master_fd)
                os.setsid()
                fcntl.ioctl(slave_fd, termios.TIOCSCTTY, 0)
                os.tcsetpgrp(slave_fd, os.getpid())
                for target in (0, 1, 2):
                    os.dup2(slave_fd, target)
                if slave_fd > 2:
                    os.close(slave_fd)
                os.chdir(cwd)
                child_env = os.environ.copy()
                if env is not None:
                    child_env.update(env)
                child_env.update(
                    {
                        "PS1": prompt,
                        "PS2": "TAUT-HOST-CONT> ",
                        "PROMPT_COMMAND": "",
                        "HISTFILE": "/dev/null",
                        "BASH_SILENCE_DEPRECATION_WARNING": "1",
                    }
                )
                shell = child_env.get("TAUT_TEST_SHELL", "/bin/bash")
                os.execve(shell, [shell, "--noprofile", "--norc", "-i"], child_env)
            except BaseException as exc:  # noqa: BLE001 approved [DOM-10.2.1] [RUFF-SUP-070] exception
                try:
                    os.write(2, f"host shell setup failed: {exc}\n".encode())
                finally:
                    os._exit(127)
        os.set_blocking(master_fd, False)
        leader_create_time = psutil.Process(child_pid).create_time()
        return cls(
            pid=child_pid,
            master_fd=master_fd,
            slave_fd=slave_fd,
            leader_create_time=leader_create_time,
            prompt=prompt,
        )

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc_value, traceback
        self.close()

    @property
    def transcript(self) -> bytes:
        self.read_available()
        return bytes(self._transcript)

    @property
    def text(self) -> str:
        return strip_terminal_bytes(self.transcript)

    def mark(self) -> int:
        self.read_available()
        return len(self._transcript)

    def read_available(self) -> bytes:
        chunks = bytearray()
        while True:
            readable, _, _ = select.select([self.master_fd], [], [], 0)
            if not readable:
                break
            try:
                chunk = os.read(self.master_fd, 65_536)
            except BlockingIOError:
                break
            except OSError as exc:
                if exc.errno == errno.EIO:
                    break
                raise
            if not chunk:
                break
            chunks.extend(chunk)
        self._transcript.extend(chunks)
        return bytes(chunks)

    def wait_for_text(
        self,
        needle: str,
        *,
        after: int = 0,
        timeout: float = 15.0,
    ) -> str:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.read_available()
            observed = strip_terminal_bytes(bytes(self._transcript[after:]))
            if needle in observed:
                return observed
            if self.poll() is not None:
                break
            time.sleep(0.02)
        observed = strip_terminal_bytes(bytes(self._transcript[after:]))
        raise TimeoutError(
            f"host shell did not show {needle!r}; pid={self.pid}; "
            f"exit={self.poll()!r}; transcript_tail={observed[-4096:]!r}"
        )

    def wait_for_prompt(self, *, after: int = 0, timeout: float = 15.0) -> str:
        return self.wait_for_text(self.prompt, after=after, timeout=timeout)

    def write(self, data: bytes) -> None:
        remaining = memoryview(data)
        while remaining:
            try:
                written = os.write(self.master_fd, remaining)
            except BlockingIOError:
                _, writable, _ = select.select([], [self.master_fd], [], 0.1)
                if not writable:
                    continue
                continue
            if written <= 0:
                raise OSError("host PTY write made no progress")
            remaining = remaining[written:]

    def run(self, command: str) -> None:
        self.write(command.encode("utf-8") + b"\n")

    def termios_snapshot(self) -> list[Any]:
        import termios

        return termios.tcgetattr(self.slave_fd)

    def foreground_pgid(self) -> int:
        return os.tcgetpgrp(self.slave_fd)

    def poll(self) -> int | None:
        try:
            waited, status = os.waitpid(self.pid, os.WNOHANG)
        except ChildProcessError:
            return 0
        if waited == 0:
            return None
        return os.waitstatus_to_exitcode(status)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            for sig, wait_seconds in ((signal.SIGTERM, 1.0), (signal.SIGKILL, 1.0)):
                if self._retire_session(sig, timeout=wait_seconds):
                    break
        finally:
            self._close_fds()
            self._reap_shell()

    def _live_session_members(self) -> list[tuple[psutil.Process, float]]:
        try:
            current_leader = psutil.Process(self.pid)
            if current_leader.create_time() != self._leader_create_time:
                return []
        except psutil.NoSuchProcess:
            pass
        members: list[tuple[psutil.Process, float]] = []
        for process in psutil.process_iter(("pid", "create_time", "status")):
            try:
                if process.info["status"] == psutil.STATUS_ZOMBIE:
                    continue
                if os.getsid(process.pid) != self.pid:
                    continue
                members.append((process, float(process.info["create_time"])))
            except (OSError, TypeError, psutil.Error):
                continue
        return members

    @staticmethod
    def _signal_members(
        members: list[tuple[psutil.Process, float]], sig: signal.Signals
    ) -> None:
        for process, create_time in members:
            try:
                if process.create_time() != create_time:
                    continue
                process.send_signal(sig)
            except psutil.Error:
                continue

    def _retire_session(self, sig: signal.Signals, *, timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        members = self._live_session_members()
        self._signal_members(members, sig)
        while time.monotonic() < deadline:
            members = self._live_session_members()
            if not members:
                return True
            if sig == signal.SIGKILL:
                self._signal_members(members, sig)
            time.sleep(0.02)
        return False

    def _reap_shell(self) -> None:
        try:
            waited, _status = os.waitpid(self.pid, os.WNOHANG)
        except ChildProcessError:
            return
        if waited == self.pid:
            return
        try:
            os.kill(self.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        try:
            waited, _status = os.waitpid(self.pid, 0)
        except ChildProcessError:
            return
        if waited != self.pid:  # pragma: no cover - waitpid's blocking contract
            raise RuntimeError(f"waitpid reaped {waited}, expected {self.pid}")

    def _close_fds(self) -> None:
        for fd in (self.master_fd, self.slave_fd):
            try:
                os.close(fd)
            except OSError:
                pass


def _windows_pipe_available(fd: int) -> int:
    import ctypes
    import msvcrt

    ctypes_api: Any = ctypes
    msvcrt_api: Any = msvcrt
    kernel32 = ctypes_api.WinDLL("kernel32", use_last_error=True)
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
    """Test-owned host side of a real provider terminal lease."""

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


def run_terminal_child(
    source: str,
    *,
    input_when_output_contains: tuple[bytes, bytes] | None = None,
    timeout: float,
) -> TerminalRun:
    """Run Python through the real adapter and capture raw terminal bytes."""

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
        shutdown = threading.Event()
        errors: list[BaseException] = []
        with ExitStack() as failed_start:
            failed_start.callback(handle.close)
            thread = _start_terminal_attach(handle, terminal, shutdown, errors)
            failed_start.pop_all()
        cleanup.callback(_finish_terminal_attach, handle, thread, shutdown)
        output, input_sent = _collect_terminal_output(
            thread,
            terminal,
            input_when_output_contains=input_when_output_contains,
            timeout=timeout,
        )
        if errors:
            raise RuntimeError("real-terminal attach failed") from errors[0]
        returncodes = [
            event.returncode
            for event in handle.events()
            if isinstance(event, ExitEvent)
        ]
        if len(returncodes) != 1:
            raise RuntimeError(f"terminal probe emitted exit codes {returncodes!r}")
        return TerminalRun(bytes(output), returncodes[0], input_sent)


def _start_terminal_attach(
    handle: Any,
    terminal: HostTerminal,
    shutdown: threading.Event,
    errors: list[BaseException],
) -> threading.Thread:
    from taut_summon._adapter import AdapterError

    def attach() -> None:
        try:
            handle.attach(
                shutdown=shutdown,
                input_fd=terminal.lease_input_fd,
                output_fd=terminal.lease_output_fd,
            )
        except AdapterError as exc:
            errors.append(exc)

    thread = threading.Thread(target=attach, name="tui-terminal-probe", daemon=True)
    thread.start()
    return thread


def _finish_terminal_attach(
    handle: Any,
    thread: threading.Thread,
    shutdown: threading.Event,
) -> None:
    shutdown.set()
    thread.join(timeout=3.0)
    try:
        handle.close()
    finally:
        thread.join(timeout=3.0)
        if thread.is_alive():
            failure = RuntimeError("real-terminal attach thread survived cleanup")
            active = sys.exception()
            if active is None:
                raise failure
            active.add_note(str(failure))


def _collect_terminal_output(
    thread: threading.Thread,
    terminal: HostTerminal,
    *,
    input_when_output_contains: tuple[bytes, bytes] | None,
    timeout: float,
) -> tuple[bytearray, bool]:
    output = bytearray()
    input_sent = False
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and thread.is_alive():
        chunk = terminal.read_available()
        if not chunk:
            thread.join(timeout=0.02)
            continue
        output.extend(chunk)
        if (
            input_when_output_contains is not None
            and not input_sent
            and input_when_output_contains[0] in output
        ):
            terminal.write(input_when_output_contains[1])
            input_sent = True
    if thread.is_alive():
        raise TimeoutError(f"real-terminal child timed out: {bytes(output[-4096:])!r}")
    while chunk := terminal.read_available():
        output.extend(chunk)
    return output, input_sent


__all__ = [
    "HostTerminal",
    "PosixHostShell",
    "TerminalRun",
    "run_terminal_child",
    "strip_terminal_bytes",
]
