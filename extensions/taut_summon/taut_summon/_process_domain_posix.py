"""POSIX provider process domains for Summon adapter generations [SUM-7.1]."""

from __future__ import annotations

import errno
import json
import os
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from taut_summon._adapter import AdapterError

_CLD_EXITED = 1
_TRAMPOLINE_READY = b"READY\n"
_TRAMPOLINE_ERROR = b"ERROR "

_CONTROLLING_TERMINAL_TRAMPOLINE = r"""
import fcntl
import json
import os
import sys
import termios

status_fd = int(sys.argv[1])
target = sys.argv[2:]
stage = "terminal setup"
try:
    flags = fcntl.fcntl(status_fd, fcntl.F_GETFD)
    fcntl.fcntl(status_fd, fcntl.F_SETFD, flags | fcntl.FD_CLOEXEC)
    os.write(status_fd, b"READY\n")
    fcntl.ioctl(0, termios.TIOCSCTTY, 0)
    stage = "provider exec"
    os.execvpe(target[0], target, os.environ)
except BaseException as exc:
    payload = json.dumps({
        "stage": stage,
        "type": type(exc).__name__,
        "errno": getattr(exc, "errno", None),
        "message": getattr(exc, "strerror", None) or str(exc),
    }).encode("utf-8", "replace")
    try:
        os.write(status_fd, b"ERROR " + payload)
    except OSError:
        pass
    os._exit(127)
"""


class ProcessDomain(Protocol):
    def observe_leader_exit(self) -> int | None: ...

    def wait_for_leader_exit(self, timeout: float) -> int | None: ...

    def signal_leader(self, sig: signal.Signals) -> None: ...

    def signal_group(self, sig: signal.Signals) -> None: ...

    def finalize(self) -> int: ...


@dataclass(frozen=True)
class ProcessIO:
    """Borrowed adapter I/O without process-lifecycle capabilities."""

    pid: int
    stdin: Any
    stdout: Any


@dataclass(frozen=True)
class SpawnedProcess:
    """Atomically published adapter I/O plus its cleanup capability."""

    process: ProcessIO
    domain: ProcessDomain


def spawn_process(
    argv: Sequence[str],
    *,
    stdin: Any = None,
    stdout: Any = None,
    stderr: Any = None,
    env: Mapping[str, str] | None = None,
    text: bool | None = None,
    encoding: str | None = None,
    bufsize: int = -1,
    close_fds: bool = True,
    pass_fds: tuple[int, ...] = (),
    controlling_terminal: bool = False,
) -> SpawnedProcess:
    """Create a new POSIX session before publishing its I/O and domain."""

    target = list(argv)
    status_read_fd = -1
    status_write_fd = -1
    if controlling_terminal:
        status_read_fd, status_write_fd = os.pipe()
        popen_argv = [
            sys.executable,
            "-I",
            "-S",
            "-c",
            _CONTROLLING_TERMINAL_TRAMPOLINE,
            str(status_write_fd),
            *target,
        ]
        inherited_fds = tuple(sorted({*pass_fds, status_write_fd}))
    else:
        popen_argv = target
        inherited_fds = pass_fds

    try:
        proc = subprocess.Popen(
            popen_argv,
            stdin=stdin,
            stdout=stdout,
            stderr=stderr,
            env=env,
            text=text,
            encoding=encoding,
            bufsize=bufsize,
            close_fds=close_fds,
            pass_fds=inherited_fds,
            start_new_session=True,
        )
    except BaseException:
        _close_fd(status_read_fd)
        _close_fd(status_write_fd)
        raise

    if controlling_terminal:
        _close_fd(status_write_fd)
        status_write_fd = -1
        try:
            status_payload = _read_spawn_status(status_read_fd)
        except BaseException as exc:
            cleanup_failure = _retire_unpublished_process(proc)
            if cleanup_failure is not None:
                exc.add_note(
                    f"unpublished child cleanup also failed: {cleanup_failure}"
                )
            raise
        finally:
            _close_fd(status_read_fd)
        failure = _decode_spawn_failure(status_payload)
        if failure is not None:
            cleanup_failure = _retire_unpublished_process(proc)
            if cleanup_failure is not None:
                failure.add_note(
                    f"unpublished child cleanup also failed: {cleanup_failure}"
                )
            raise failure

    return SpawnedProcess(
        process=ProcessIO(pid=proc.pid, stdin=proc.stdin, stdout=proc.stdout),
        domain=PosixProcessDomain(proc),
    )


def _close_fd(fd: int) -> None:
    if fd < 0:
        return
    try:
        os.close(fd)
    except OSError:
        pass


def _read_spawn_status(fd: int) -> bytes:
    chunks: list[bytes] = []
    while True:
        chunk = os.read(fd, 4096)
        if not chunk:
            return b"".join(chunks)
        chunks.append(chunk)


def _decode_spawn_failure(payload: bytes) -> AdapterError | None:
    if payload == _TRAMPOLINE_READY:
        return None
    if not payload.startswith(_TRAMPOLINE_READY):
        return AdapterError("provider exec trampoline exited before readiness")
    payload = payload[len(_TRAMPOLINE_READY) :]
    if not payload.startswith(_TRAMPOLINE_ERROR):
        return AdapterError("provider child setup failed without a valid status report")
    payload = payload[len(_TRAMPOLINE_ERROR) :]
    try:
        report = json.loads(payload.decode("utf-8"))
        stage = str(report["stage"])
        error_type = str(report["type"])
        message = str(report["message"])
    except (KeyError, TypeError, ValueError, UnicodeDecodeError):
        return AdapterError("provider child setup failed without a valid status report")
    return AdapterError(f"provider {stage} failed ({error_type}): {message}")


def _retire_unpublished_process(proc: subprocess.Popen[Any]) -> str | None:
    signal_failure: str | None = None
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    except OSError as exc:
        signal_failure = f"process-group SIGKILL failed: {exc}"
    try:
        proc.wait(timeout=2.0)
    except (OSError, subprocess.TimeoutExpired) as exc:
        wait_failure = f"leader reap failed: {exc}"
        return (
            wait_failure
            if signal_failure is None
            else f"{signal_failure}; {wait_failure}"
        )
    return signal_failure


class PosixProcessDomain:
    """Own non-reaping leader observation, group retirement, and one reap."""

    def __init__(self, proc: subprocess.Popen[Any]) -> None:
        self._proc = proc
        self._pgid = proc.pid
        self._lock = threading.RLock()
        self._returncode: int | None = None
        self._reaped = False
        self._finalize_error: AdapterError | None = None

    def observe_leader_exit(self) -> int | None:
        """Observe terminal leader status without releasing its PID/PGID."""

        with self._lock:
            if self._returncode is not None:
                return self._returncode
            try:
                observed = _observe_exit(self._proc.pid)
            except ChildProcessError as exc:
                raise AdapterError(
                    "provider leader was reaped outside its process domain"
                ) from exc
            except OSError as exc:
                raise AdapterError(
                    f"provider leader observation failed: {exc}"
                ) from exc
            if observed is None:
                return None
            code, status = observed
            self._returncode = status if code == _CLD_EXITED else -status
            return self._returncode

    def wait_for_leader_exit(self, timeout: float) -> int | None:
        deadline = time.monotonic() + timeout
        while True:
            status = self.observe_leader_exit()
            if status is not None:
                return status
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            threading.Event().wait(min(0.01, remaining))

    def signal_leader(self, sig: signal.Signals) -> None:
        """Signal only a still-live provider leader without reaping it."""

        with self._lock:
            if self.observe_leader_exit() is not None:
                return
            try:
                os.kill(self._proc.pid, sig)
            except ProcessLookupError:
                # Exit can race the observation. Confirm it without reaping.
                if self.observe_leader_exit() is None:
                    raise AdapterError(
                        "provider leader disappeared before signal"
                    ) from None
            except OSError as exc:
                raise AdapterError(f"provider leader signal failed: {exc}") from exc

    def signal_group(self, sig: signal.Signals) -> None:
        """Deliver a reusable group interrupt while the PGID remains pinned."""

        with self._lock:
            if self._reaped:
                return
            self._signal_group(sig)

    def finalize(
        self,
        *,
        graceful_timeout: float = 5.0,
        term_timeout: float = 2.0,
        kill_timeout: float = 2.0,
    ) -> int:
        """Retire signalable group members while the leader pins the PGID."""

        with self._lock:
            if self._finalize_error is not None:
                raise self._finalize_error
            if self._reaped:
                assert self._returncode is not None
                return self._returncode

            failure = self._wait_stage_failure(graceful_timeout)
            term_delivered, term_failure = self._attempt_group_signal(signal.SIGTERM)
            failure = _append_finalize_failure(failure, term_failure)
            if term_delivered and term_timeout > 0:
                threading.Event().wait(term_timeout)

            _, kill_failure = self._attempt_group_signal(signal.SIGKILL)
            failure = _append_finalize_failure(failure, kill_failure)
            status, status_failure = self._terminal_status(kill_timeout)
            failure = _append_finalize_failure(failure, status_failure)
            if status is not None:
                failure = _append_finalize_failure(failure, self._reap_leader())
            if failure is not None:
                self._finalize_error = failure
                raise failure
            assert status is not None
            return status

    def _wait_stage_failure(self, timeout: float) -> AdapterError | None:
        try:
            self.wait_for_leader_exit(timeout)
        except AdapterError as exc:
            return exc
        return None

    def _attempt_group_signal(
        self,
        sig: signal.Signals,
    ) -> tuple[bool, AdapterError | None]:
        try:
            return self._signal_group(sig), None
        except AdapterError as exc:
            return False, exc

    def _terminal_status(
        self,
        timeout: float,
    ) -> tuple[int | None, AdapterError | None]:
        try:
            status = self.wait_for_leader_exit(timeout)
        except AdapterError as exc:
            return None, exc
        if status is None:
            return None, AdapterError("provider leader did not exit after SIGKILL")
        return status, None

    def _reap_leader(self) -> AdapterError | None:
        try:
            self._proc.wait(timeout=0.0)
        except (OSError, subprocess.TimeoutExpired) as exc:
            failure = AdapterError(f"provider leader reap failed: {exc}")
            failure.__cause__ = exc
            return failure
        self._reaped = True
        return None

    def _signal_group(self, sig: signal.Signals) -> bool:
        try:
            os.killpg(self._pgid, sig)
        except ProcessLookupError:
            return False
        except PermissionError as exc:
            if sys.platform == "darwin":
                # Darwin can report EPERM while the leader crosses into zombie
                # state. Cached terminal evidence makes that a no-target result.
                if self.observe_leader_exit() is not None:
                    return False
            raise AdapterError(
                f"provider process-group signal {sig!s} failed: {exc}"
            ) from exc
        except OSError as exc:
            if exc.errno == errno.ESRCH:
                return False
            raise AdapterError(
                f"provider process-group signal {sig!s} failed: {exc}"
            ) from exc
        return True


def _append_finalize_failure(
    primary: AdapterError | None,
    failure: AdapterError | None,
) -> AdapterError | None:
    if failure is None:
        return primary
    if primary is None:
        return failure
    primary.add_note(f"provider process-domain finalization also failed: {failure}")
    return primary


def _observe_exit(pid: int) -> tuple[int, int] | None:
    if hasattr(os, "waitid"):
        result = os.waitid(
            os.P_PID,
            pid,
            os.WEXITED | os.WNOHANG | os.WNOWAIT,
        )
        if result is None or result.si_pid == 0:
            return None
        return result.si_code, result.si_status
    if sys.platform != "darwin":  # pragma: no cover - supported POSIX runtimes
        raise RuntimeError("POSIX runtime does not expose non-reaping waitid")
    from taut_summon._darwin_wait import observe_exit

    darwin_result = observe_exit(pid)
    if darwin_result is None:
        return None
    _, code, status = darwin_result
    return code, status
