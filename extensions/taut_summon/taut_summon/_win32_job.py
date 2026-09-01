"""Windows Job Object ownership for structured Summon providers [SUM-7.1].

The production Win32 library is loaded only when the default API is requested
on Windows.  Importing this module on POSIX is intentionally safe so the
transaction and ownership rules can be tested with an injected API.
"""

from __future__ import annotations

import ctypes
import os
import signal
import subprocess
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, NoReturn, Protocol

from taut_summon._adapter import AdapterError

CREATE_SUSPENDED = 0x00000004
CREATE_BREAKAWAY_FROM_JOB = 0x01000000

DWORD = ctypes.c_uint32
LONG = ctypes.c_int32
SIZE_T = ctypes.c_size_t
ULONG_PTR = ctypes.c_size_t
LARGE_INTEGER = ctypes.c_int64
ULONGLONG = ctypes.c_uint64
BOOL = ctypes.c_int32
HANDLE = ctypes.c_void_p
LPVOID = ctypes.c_void_p


class THREADENTRY32(ctypes.Structure):
    _fields_ = [
        ("dwSize", DWORD),
        ("cntUsage", DWORD),
        ("th32ThreadID", DWORD),
        ("th32OwnerProcessID", DWORD),
        ("tpBasePri", LONG),
        ("tpDeltaPri", LONG),
        ("dwFlags", DWORD),
    ]


class JOBOBJECT_BASIC_ACCOUNTING_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("TotalUserTime", LARGE_INTEGER),
        ("TotalKernelTime", LARGE_INTEGER),
        ("ThisPeriodTotalUserTime", LARGE_INTEGER),
        ("ThisPeriodTotalKernelTime", LARGE_INTEGER),
        ("TotalPageFaultCount", DWORD),
        ("TotalProcesses", DWORD),
        ("ActiveProcesses", DWORD),
        ("TotalTerminatedProcesses", DWORD),
    ]


class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", LARGE_INTEGER),
        ("PerJobUserTimeLimit", LARGE_INTEGER),
        ("LimitFlags", DWORD),
        ("MinimumWorkingSetSize", SIZE_T),
        ("MaximumWorkingSetSize", SIZE_T),
        ("ActiveProcessLimit", DWORD),
        ("Affinity", ULONG_PTR),
        ("PriorityClass", DWORD),
        ("SchedulingClass", DWORD),
    ]


class IO_COUNTERS(ctypes.Structure):
    _fields_ = [
        ("ReadOperationCount", ULONGLONG),
        ("WriteOperationCount", ULONGLONG),
        ("OtherOperationCount", ULONGLONG),
        ("ReadTransferCount", ULONGLONG),
        ("WriteTransferCount", ULONGLONG),
        ("OtherTransferCount", ULONGLONG),
    ]


class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
        ("IoInfo", IO_COUNTERS),
        ("ProcessMemoryLimit", SIZE_T),
        ("JobMemoryLimit", SIZE_T),
        ("PeakProcessMemoryUsed", SIZE_T),
        ("PeakJobMemoryUsed", SIZE_T),
    ]


class Win32CallError(OSError):
    """A stable operation plus native error code from one kernel32 call."""

    def __init__(self, operation: str, error_code: int) -> None:
        self.operation = operation
        self.error_code = error_code
        super().__init__(
            error_code, f"{operation} failed with Win32 error {error_code}"
        )


class Kernel32Api:
    """Typed documented kernel32 bindings used by the transaction owner."""

    _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
    _JOB_OBJECT_BASIC_ACCOUNTING_INFORMATION = 1
    _JOB_OBJECT_BASIC_UI_RESTRICTIONS = 4
    _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
    _PROCESS_TERMINATE = 0x0001
    _PROCESS_SET_QUOTA = 0x0100
    _TH32CS_SNAPTHREAD = 0x00000004
    _THREAD_SUSPEND_RESUME = 0x0002
    _ERROR_NO_MORE_FILES = 18
    _DWORD_FAILURE = 0xFFFFFFFF

    def __init__(
        self,
        *,
        library: Any | None = None,
        last_error: Callable[[], int] | None = None,
    ) -> None:
        if library is None:
            if os.name != "nt":
                raise AdapterError("Win32 Job Objects are available only on Windows")
            win_dll = ctypes.WinDLL  # type: ignore[attr-defined]
            library = win_dll("kernel32", use_last_error=True)
        if last_error is None:
            last_error = ctypes.get_last_error  # type: ignore[attr-defined]
        self._library = library
        self._last_error = last_error
        self._bind_functions()

    def _bind_functions(self) -> None:
        self._create_job = self._library.CreateJobObjectW
        self._create_job.argtypes = [LPVOID, ctypes.c_wchar_p]
        self._create_job.restype = HANDLE

        self._set_job_information = self._library.SetInformationJobObject
        self._set_job_information.argtypes = [HANDLE, ctypes.c_int32, LPVOID, DWORD]
        self._set_job_information.restype = BOOL

        self._open_process = self._library.OpenProcess
        self._open_process.argtypes = [DWORD, BOOL, DWORD]
        self._open_process.restype = HANDLE

        self._assign_process = self._library.AssignProcessToJobObject
        self._assign_process.argtypes = [HANDLE, HANDLE]
        self._assign_process.restype = BOOL

        self._create_snapshot = self._library.CreateToolhelp32Snapshot
        self._create_snapshot.argtypes = [DWORD, DWORD]
        self._create_snapshot.restype = HANDLE

        self._thread_first = self._library.Thread32First
        self._thread_first.argtypes = [HANDLE, ctypes.POINTER(THREADENTRY32)]
        self._thread_first.restype = BOOL

        self._thread_next = self._library.Thread32Next
        self._thread_next.argtypes = [HANDLE, ctypes.POINTER(THREADENTRY32)]
        self._thread_next.restype = BOOL

        self._open_thread = self._library.OpenThread
        self._open_thread.argtypes = [DWORD, BOOL, DWORD]
        self._open_thread.restype = HANDLE

        self._resume_thread = self._library.ResumeThread
        self._resume_thread.argtypes = [HANDLE]
        self._resume_thread.restype = DWORD

        self._query_job_information = self._library.QueryInformationJobObject
        self._query_job_information.argtypes = [
            HANDLE,
            ctypes.c_int32,
            LPVOID,
            DWORD,
            ctypes.POINTER(DWORD),
        ]
        self._query_job_information.restype = BOOL

        self._terminate_job = self._library.TerminateJobObject
        self._terminate_job.argtypes = [HANDLE, ctypes.c_uint32]
        self._terminate_job.restype = BOOL

        self._close_handle = self._library.CloseHandle
        self._close_handle.argtypes = [HANDLE]
        self._close_handle.restype = BOOL

    def create_job(self) -> int:
        return self._required_handle("CreateJobObjectW", self._create_job(None, None))

    def configure_kill_on_close(self, job: int) -> None:
        limits = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        limits.BasicLimitInformation.LimitFlags = (
            self._JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        )
        if not self._set_job_information(
            HANDLE(job),
            self._JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
            ctypes.byref(limits),
            ctypes.sizeof(limits),
        ):
            self._raise_last_error("SetInformationJobObject")

    def configure_ui_restrictions(self, job: int, restrictions: int) -> None:
        """Set documented basic UI limits for the real rejection fixture."""

        value = DWORD(restrictions)
        if not self._set_job_information(
            HANDLE(job),
            self._JOB_OBJECT_BASIC_UI_RESTRICTIONS,
            ctypes.byref(value),
            ctypes.sizeof(value),
        ):
            self._raise_last_error("SetInformationJobObject")

    def open_process(self, pid: int) -> int:
        raw = self._open_process(
            self._PROCESS_SET_QUOTA | self._PROCESS_TERMINATE,
            0,
            pid,
        )
        return self._required_handle("OpenProcess", raw)

    def assign_process(self, job: int, process: int) -> None:
        if not self._assign_process(HANDLE(job), HANDLE(process)):
            self._raise_last_error("AssignProcessToJobObject")

    def create_thread_snapshot(self) -> int:
        raw = self._create_snapshot(self._TH32CS_SNAPTHREAD, 0)
        invalid = ctypes.c_void_p(-1).value
        value = self._required_handle("CreateToolhelp32Snapshot", raw)
        if value == invalid:
            self._raise_last_error("CreateToolhelp32Snapshot")
        return value

    def thread_entries(self, snapshot: int) -> tuple[tuple[int, int], ...]:
        entry = THREADENTRY32()
        entry.dwSize = ctypes.sizeof(THREADENTRY32)
        if not self._thread_first(HANDLE(snapshot), ctypes.byref(entry)):
            error_code = int(self._last_error())
            if error_code == self._ERROR_NO_MORE_FILES:
                return ()
            raise Win32CallError("Thread32First", error_code)
        entries: list[tuple[int, int]] = []
        while True:
            entries.append((int(entry.th32ThreadID), int(entry.th32OwnerProcessID)))
            entry.dwSize = ctypes.sizeof(THREADENTRY32)
            if self._thread_next(HANDLE(snapshot), ctypes.byref(entry)):
                continue
            error_code = int(self._last_error())
            if error_code != self._ERROR_NO_MORE_FILES:
                raise Win32CallError("Thread32Next", error_code)
            return tuple(entries)

    def open_thread(self, thread_id: int) -> int:
        raw = self._open_thread(self._THREAD_SUSPEND_RESUME, 0, thread_id)
        return self._required_handle("OpenThread", raw)

    def resume_thread(self, thread: int) -> int:
        previous_count = int(self._resume_thread(HANDLE(thread)))
        if previous_count == self._DWORD_FAILURE:
            self._raise_last_error("ResumeThread")
        return previous_count

    def active_processes(self, job: int) -> int:
        accounting = JOBOBJECT_BASIC_ACCOUNTING_INFORMATION()
        returned = DWORD()
        if not self._query_job_information(
            HANDLE(job),
            self._JOB_OBJECT_BASIC_ACCOUNTING_INFORMATION,
            ctypes.byref(accounting),
            ctypes.sizeof(accounting),
            ctypes.byref(returned),
        ):
            self._raise_last_error("QueryInformationJobObject")
        if returned.value not in (0, ctypes.sizeof(accounting)):
            raise AdapterError(
                "QueryInformationJobObject returned unexpected accounting size "
                f"{returned.value}"
            )
        return int(accounting.ActiveProcesses)

    def terminate_job(self, job: int, exit_code: int) -> None:
        if not self._terminate_job(HANDLE(job), exit_code):
            self._raise_last_error("TerminateJobObject")

    def close_handle(self, handle: int) -> None:
        if not self._close_handle(HANDLE(handle)):
            self._raise_last_error("CloseHandle")

    def _required_handle(self, operation: str, raw: int | None) -> int:
        if raw is None or raw == 0:
            self._raise_last_error(operation)
        return int(raw)

    def _raise_last_error(self, operation: str) -> NoReturn:
        raise Win32CallError(operation, int(self._last_error()))


class Win32Api(Protocol):
    """Python-level boundary around the documented kernel32 calls."""

    def create_job(self) -> int: ...

    def configure_kill_on_close(self, job: int) -> None: ...

    def open_process(self, pid: int) -> int: ...

    def assign_process(self, job: int, process: int) -> None: ...

    def create_thread_snapshot(self) -> int: ...

    def thread_entries(self, snapshot: int) -> tuple[tuple[int, int], ...]: ...

    def open_thread(self, thread_id: int) -> int: ...

    def resume_thread(self, thread: int) -> int: ...

    def active_processes(self, job: int) -> int: ...

    def terminate_job(self, job: int, exit_code: int) -> None: ...

    def close_handle(self, handle: int) -> None: ...


class _OwnedHandle:
    def __init__(self, api: Win32Api, value: int) -> None:
        self._api = api
        self._value: int | None = value

    @property
    def value(self) -> int:
        if self._value is None:
            raise RuntimeError("native handle ownership was already released")
        return self._value

    @property
    def closed(self) -> bool:
        return self._value is None

    def close(self) -> None:
        value = self._value
        if value is None:
            return
        self._value = None
        self._api.close_handle(value)


@dataclass(frozen=True)
class WindowsSpawnedProcess:
    proc: subprocess.Popen[Any]
    domain: WindowsJobDomain


class WindowsJobDomain:
    """Retained Job Object capability for one provider generation."""

    def __init__(
        self,
        proc: subprocess.Popen[Any],
        *,
        api: Win32Api,
        job: _OwnedHandle,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._proc = proc
        self._api = api
        self._job = job
        self._monotonic = monotonic
        self._sleep = sleep
        self._lock = threading.RLock()
        self._returncode: int | None = None
        self._reap_attempted = False
        self._reaped = False
        self._finalize_error: str | None = None

    def observe_leader_exit(self) -> int | None:
        with self._lock:
            if self._returncode is not None:
                return self._returncode
            observed = self._proc.poll()
            if observed is not None:
                self._returncode = int(observed)
            return self._returncode

    def wait_for_leader_exit(self, timeout: float) -> int | None:
        """Observe boundedly without consuming the owner's one final reap."""

        with self._lock:
            deadline = self._monotonic() + max(0.0, timeout)
            while True:
                observed = self.observe_leader_exit()
                if observed is not None:
                    return observed
                remaining = deadline - self._monotonic()
                if remaining <= 0:
                    return None
                self._sleep(min(0.01, remaining))

    def signal_leader(self, sig: signal.Signals) -> None:
        del sig
        with self._lock:
            try:
                if self.observe_leader_exit() is None:
                    self._proc.terminate()
            except OSError as exc:
                raise AdapterError(
                    f"Windows provider leader signal failed: {exc}"
                ) from exc

    def signal_group(self, sig: signal.Signals) -> None:
        del sig
        raise AdapterError("Windows Job Objects have no reusable group signal")

    def active_processes(self) -> int:
        """Return the current Job Object population without changing ownership."""

        with self._lock:
            active = self._api.active_processes(self._job.value)
            if active < 0:
                raise AdapterError(
                    f"Windows provider job returned invalid active count {active}"
                )
            return active

    @property
    def final_active_processes(self) -> int | None:
        """Expose the retained zero proof after successful finalization."""

        with self._lock:
            if self._reaped and self._job.closed and self._finalize_error is None:
                return 0
            return None

    def finalize(  # noqa: C901 approved [DOM-10.2.1] [RUFF-SUP-035] exception
        self,
        *,
        graceful_timeout: float = 5.0,
        term_timeout: float = 2.0,
        kill_timeout: float = 2.0,
    ) -> int:
        """Retire the whole job, prove it empty, reap the leader, release it."""

        del term_timeout  # Windows has one forced Job Object stage.
        with self._lock:
            if self._finalize_error is not None:
                raise AdapterError(self._finalize_error)
            if self._reaped and self._job.closed:
                assert self._returncode is not None
                return self._returncode
            failure: AdapterError | None = None
            status: int | None = None
            try:
                self.wait_for_leader_exit(graceful_timeout)
                active = self.active_processes()
                if active > 0:
                    self._api.terminate_job(self._job.value, 1)
                deadline = self._monotonic() + kill_timeout
                while active > 0:
                    remaining = deadline - self._monotonic()
                    if remaining <= 0:
                        raise AdapterError(
                            f"Windows provider job still has {active} active processes"
                        )
                    self._sleep(min(0.01, remaining))
                    active = self.active_processes()
                remaining = max(0.0, deadline - self._monotonic())
                status = self._reap_leader(remaining)
                if status is None:
                    raise AdapterError(
                        "provider leader did not exit after Job Object termination"
                    )
            except AdapterError as exc:
                failure = exc
            except OSError as exc:
                failure = AdapterError(
                    f"Windows provider job finalization failed: {exc}"
                )
                failure.__cause__ = exc
            try:
                self._job.close()
            except OSError as exc:
                close_failure = AdapterError(
                    f"Windows provider job handle cleanup failed: {exc}"
                )
                close_failure.__cause__ = exc
                if failure is None:
                    failure = close_failure
                else:
                    failure.add_note(str(close_failure))
            if failure is not None:
                if not self._reap_attempted:
                    try:
                        cleanup_status = self._reap_leader(kill_timeout)
                        if cleanup_status is None:
                            failure.add_note(
                                "provider leader remained live after "
                                "kill-on-close cleanup"
                            )
                    except (OSError, AdapterError) as exc:
                        failure.add_note(
                            f"provider leader cleanup wait also failed: {exc}"
                        )
                self._finalize_error = str(failure)
                raise failure
            assert status is not None
            return status

    def _reap_leader(self, timeout: float) -> int | None:
        if self._reaped:
            return self._returncode
        if self._reap_attempted:
            raise AdapterError("provider leader reap was already attempted")
        self._reap_attempted = True
        try:
            self._returncode = int(self._proc.wait(timeout=timeout))
        except subprocess.TimeoutExpired:
            return None
        self._reaped = True
        return self._returncode


@dataclass
class _WindowsSpawnAttempt:
    """Own partially acquired resources until spawn publishes a domain."""

    api: Win32Api
    job: _OwnedHandle | None = None
    process: _OwnedHandle | None = None
    snapshot: _OwnedHandle | None = None
    thread: _OwnedHandle | None = None
    proc: Any | None = None
    assigned: bool = False

    def publish(
        self,
        *,
        monotonic: Callable[[], float],
        sleep: Callable[[float], None],
    ) -> WindowsSpawnedProcess:
        """Transfer the completed process and job ownership atomically."""

        assert self.proc is not None
        assert self.job is not None
        spawned = WindowsSpawnedProcess(
            proc=self.proc,
            domain=WindowsJobDomain(
                self.proc,
                api=self.api,
                job=self.job,
                monotonic=monotonic,
                sleep=sleep,
            ),
        )
        self.job = None
        return spawned

    def rollback(self) -> tuple[BaseException, ...]:
        """Run every compensating action and retain its failure in order."""

        cleanup_errors: list[BaseException] = []
        reaped = False
        if self.proc is not None:
            reaped = self._attempt_cleanup(self._retire_and_reap, cleanup_errors)
            for stream in (self.proc.stdin, self.proc.stdout, self.proc.stderr):
                if stream is not None:
                    self._attempt_cleanup(stream.close, cleanup_errors)
        for owned in (self.thread, self.snapshot, self.process, self.job):
            if owned is not None:
                self._attempt_cleanup(owned.close, cleanup_errors)
        if self.proc is not None and not reaped:
            self._attempt_cleanup(self._reap, cleanup_errors)
        return tuple(cleanup_errors)

    def _retire_and_reap(self) -> None:
        assert self.proc is not None
        if self.assigned:
            assert self.job is not None
            self.api.terminate_job(self.job.value, 1)
        elif self.proc.poll() is None:
            self.proc.kill()
        self.proc.wait(timeout=5.0)

    def _reap(self) -> None:
        assert self.proc is not None
        self.proc.wait(timeout=5.0)

    @staticmethod
    def _attempt_cleanup(
        action: Callable[[], object],
        cleanup_errors: list[BaseException],
    ) -> bool:
        try:
            action()
        except BaseException as exc:  # noqa: BLE001 approved [DOM-10.2.1] [RUFF-SUP-091] exception
            cleanup_errors.append(exc)
            return False
        return True


def _translated_spawn_failure(
    primary: BaseException,
    cleanup_errors: Sequence[BaseException],
) -> AdapterError | None:
    """Return a public setup error, or ``None`` to re-raise the primary."""

    if isinstance(primary, AdapterError):
        failure = primary
    elif isinstance(primary, OSError):
        failure = AdapterError(f"Windows provider setup failed: {primary}")
        failure.__cause__ = primary
    else:
        for cleanup_error in cleanup_errors:
            primary.add_note(
                f"Windows provider setup cleanup also failed: {cleanup_error}"
            )
        return None
    for cleanup_error in cleanup_errors:
        failure.add_note(f"Windows provider setup cleanup also failed: {cleanup_error}")
    return failure


def spawn_windows_process(
    argv: Sequence[str],
    *,
    creationflags: int = 0,
    api: Win32Api | None = None,
    popen_factory: Callable[..., Any] = subprocess.Popen,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    **popen_kwargs: Any,
) -> WindowsSpawnedProcess:
    """Create, contain, resume, and atomically publish a stream provider."""

    if creationflags & CREATE_BREAKAWAY_FROM_JOB:
        raise AdapterError(
            "CREATE_BREAKAWAY_FROM_JOB is incompatible with provider containment"
        )
    if api is None:
        api = Kernel32Api()
    attempt = _WindowsSpawnAttempt(api)
    try:
        job = attempt.job = _OwnedHandle(api, api.create_job())
        api.configure_kill_on_close(job.value)
        proc = attempt.proc = popen_factory(
            list(argv),
            creationflags=creationflags | CREATE_SUSPENDED,
            **popen_kwargs,
        )
        process = attempt.process = _OwnedHandle(api, api.open_process(proc.pid))
        api.assign_process(job.value, process.value)
        attempt.assigned = True
        snapshot = attempt.snapshot = _OwnedHandle(api, api.create_thread_snapshot())
        entries = [
            entry
            for entry in api.thread_entries(snapshot.value)
            if entry[1] == proc.pid
        ]
        if len(entries) != 1:
            raise AdapterError(
                f"suspended provider has {len(entries)} owned threads; "
                "expected exactly one"
            )
        thread = attempt.thread = _OwnedHandle(api, api.open_thread(entries[0][0]))
        previous_suspend_count = api.resume_thread(thread.value)
        if previous_suspend_count != 1:
            raise AdapterError(
                "provider primary thread had unexpected suspend count "
                f"{previous_suspend_count}; expected 1"
            )
        thread.close()
        snapshot.close()
        process.close()
        return attempt.publish(monotonic=monotonic, sleep=sleep)
    except BaseException as primary:
        failure = _translated_spawn_failure(primary, attempt.rollback())
        if failure is None or failure is primary:
            raise
        raise failure from primary
