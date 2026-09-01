"""Deterministic Win32 Job Object process-domain tests [SUM-7.1]."""

from __future__ import annotations

import ctypes
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, cast

import pytest
import taut_summon._win32_job as win32_job_module
from taut_summon._adapter import AdapterError
from taut_summon._win32_job import (
    CREATE_BREAKAWAY_FROM_JOB,
    CREATE_SUSPENDED,
    JOBOBJECT_BASIC_ACCOUNTING_INFORMATION,
    JOBOBJECT_EXTENDED_LIMIT_INFORMATION,
    THREADENTRY32,
    Kernel32Api,
    Win32CallError,
    spawn_windows_process,
)


class _FakeStream:
    def __init__(self) -> None:
        self.close_calls = 0

    def close(self) -> None:
        self.close_calls += 1


def test_win32_structure_layouts_match_the_sdk_abi() -> None:
    assert ctypes.sizeof(THREADENTRY32) == 28
    assert ctypes.sizeof(JOBOBJECT_BASIC_ACCOUNTING_INFORMATION) == 48
    expected_extended_size = 144 if ctypes.sizeof(ctypes.c_void_p) == 8 else 112
    assert ctypes.sizeof(JOBOBJECT_EXTENDED_LIMIT_INFORMATION) == expected_extended_size


class _NativeFunction:
    def __init__(self, result: object = 1) -> None:
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
    def __init__(self) -> None:
        self.CreateJobObjectW = _NativeFunction(10)
        self.SetInformationJobObject = _NativeFunction(1)
        self.OpenProcess = _NativeFunction(11)
        self.AssignProcessToJobObject = _NativeFunction(1)
        self.CreateToolhelp32Snapshot = _NativeFunction(12)
        self.Thread32First = _NativeFunction(0)
        self.Thread32Next = _NativeFunction(0)
        self.OpenThread = _NativeFunction(13)
        self.ResumeThread = _NativeFunction(1)
        self.QueryInformationJobObject = _NativeFunction(1)
        self.TerminateJobObject = _NativeFunction(1)
        self.CloseHandle = _NativeFunction(1)


def test_kernel32_api_sets_typed_kill_on_close_job_limit() -> None:
    library = _FakeKernel32()
    api = Kernel32Api(library=library, last_error=lambda: 5)

    job = api.create_job()
    api.configure_kill_on_close(job)

    assert job == 10
    assert library.CreateJobObjectW.argtypes is not None
    assert library.CreateJobObjectW.restype is ctypes.c_void_p
    call = library.SetInformationJobObject.calls[0]
    assert ctypes.cast(call[0], ctypes.c_void_p).value == 10
    assert call[1] == 9
    info = ctypes.cast(
        call[2], ctypes.POINTER(JOBOBJECT_EXTENDED_LIMIT_INFORMATION)
    ).contents
    assert info.BasicLimitInformation.LimitFlags == 0x00002000
    assert call[3] == ctypes.sizeof(JOBOBJECT_EXTENDED_LIMIT_INFORMATION)


def test_kernel32_api_sets_typed_basic_ui_restriction() -> None:
    library = _FakeKernel32()
    api = Kernel32Api(library=library, last_error=lambda: 5)

    api.configure_ui_restrictions(10, 0x1)

    call = library.SetInformationJobObject.calls[0]
    assert ctypes.cast(call[0], ctypes.c_void_p).value == 10
    assert call[1] == 4
    assert ctypes.cast(call[2], ctypes.POINTER(ctypes.c_uint32)).contents.value == 1
    assert call[3] == ctypes.sizeof(ctypes.c_uint32)


def test_kernel32_api_enumerates_typed_thread_entries_to_end_marker() -> None:
    library = _FakeKernel32()
    next_calls = 0

    def first(_snapshot: object, raw_entry: Any) -> int:
        entry = ctypes.cast(raw_entry, ctypes.POINTER(THREADENTRY32)).contents
        assert entry.dwSize == ctypes.sizeof(THREADENTRY32)
        entry.th32ThreadID = 101
        entry.th32OwnerProcessID = 4312
        return 1

    def next_entry(_snapshot: object, raw_entry: Any) -> int:
        nonlocal next_calls
        next_calls += 1
        if next_calls > 1:
            return 0
        entry = ctypes.cast(raw_entry, ctypes.POINTER(THREADENTRY32)).contents
        entry.th32ThreadID = 102
        entry.th32OwnerProcessID = 9999
        return 1

    library.Thread32First.result = first
    library.Thread32Next.result = next_entry
    api = Kernel32Api(library=library, last_error=lambda: 18)

    assert api.thread_entries(12) == ((101, 4312), (102, 9999))


def test_kernel32_api_uses_documented_rights_and_reads_active_accounting() -> None:
    library = _FakeKernel32()

    def query(
        _job: object,
        info_class: object,
        raw_accounting: Any,
        size: object,
        raw_returned: Any,
    ) -> int:
        assert info_class == 1
        assert size == ctypes.sizeof(JOBOBJECT_BASIC_ACCOUNTING_INFORMATION)
        accounting = ctypes.cast(
            raw_accounting,
            ctypes.POINTER(JOBOBJECT_BASIC_ACCOUNTING_INFORMATION),
        ).contents
        accounting.ActiveProcesses = 3
        returned = ctypes.cast(raw_returned, ctypes.POINTER(ctypes.c_uint32)).contents
        returned.value = ctypes.sizeof(JOBOBJECT_BASIC_ACCOUNTING_INFORMATION)
        return 1

    library.QueryInformationJobObject.result = query
    api = Kernel32Api(library=library, last_error=lambda: 5)

    assert api.open_process(4312) == 11
    api.assign_process(10, 11)
    assert api.open_thread(101) == 13
    assert api.resume_thread(13) == 1
    assert api.active_processes(10) == 3
    api.terminate_job(10, 7)
    api.close_handle(13)

    assert library.OpenProcess.calls == [(0x00000101, 0, 4312)]
    assert library.OpenThread.calls == [(0x0002, 0, 101)]
    assert library.TerminateJobObject.calls[0][1] == 7


def test_kernel32_api_preserves_operation_and_error_code() -> None:
    library = _FakeKernel32()
    library.ResumeThread.result = 0xFFFFFFFF
    api = Kernel32Api(library=library, last_error=lambda: 87)

    with pytest.raises(Win32CallError) as captured:
        api.resume_thread(13)

    assert captured.value.operation == "ResumeThread"
    assert captured.value.error_code == 87
    assert "Win32 error 87" in str(captured.value)


class _FakeProcess:
    pid = 4312

    def __init__(self, calls: list[tuple[Any, ...]] | None = None) -> None:
        self.calls = calls
        self.stdin = _FakeStream()
        self.stdout = _FakeStream()
        self.stderr = None
        self.returncode: int | None = None
        self.wait_calls = 0
        self.terminate_error: OSError | None = None

    def poll(self) -> int | None:
        return self.returncode

    def wait(self, timeout: float | None = None) -> int:
        self.wait_calls += 1
        if self.calls is not None:
            self.calls.append(("wait", timeout))
        if self.returncode is None:
            raise subprocess.TimeoutExpired(["provider"], timeout or 0.0)
        return self.returncode

    def kill(self) -> None:
        self.returncode = 1

    def terminate(self) -> None:
        if self.terminate_error is not None:
            raise self.terminate_error
        self.returncode = 1


class _FakeApi:
    def __init__(
        self,
        calls: list[tuple[Any, ...]],
        *,
        proc: _FakeProcess | None = None,
        resume_result: int = 1,
        active_results: list[int] | None = None,
        fail_at: str | None = None,
        entries: tuple[tuple[int, int], ...] | None = None,
    ) -> None:
        self.calls = calls
        self.proc = proc
        self.resume_result = resume_result
        self.active_results = active_results or [0]
        self.fail_at = fail_at
        self.entries = entries if entries is not None else ((21, _FakeProcess.pid),)

    def _fail(self, operation: str) -> None:
        if self.fail_at == operation:
            raise OSError(f"{operation} failed")

    def create_job(self) -> int:
        self._fail("create_job")
        self.calls.append(("create_job",))
        return 10

    def configure_kill_on_close(self, job: int) -> None:
        self._fail("configure")
        self.calls.append(("configure", job))

    def open_process(self, pid: int) -> int:
        self._fail("open_process")
        self.calls.append(("open_process", pid))
        return 11

    def assign_process(self, job: int, process: int) -> None:
        self._fail("assign")
        self.calls.append(("assign", job, process))

    def create_thread_snapshot(self) -> int:
        self._fail("snapshot")
        self.calls.append(("snapshot",))
        return 12

    def thread_entries(self, snapshot: int) -> tuple[tuple[int, int], ...]:
        self._fail("thread_entries")
        self.calls.append(("thread_entries", snapshot))
        return self.entries

    def open_thread(self, thread_id: int) -> int:
        self._fail("open_thread")
        self.calls.append(("open_thread", thread_id))
        return 13

    def resume_thread(self, thread: int) -> int:
        self._fail("resume")
        self.calls.append(("resume", thread))
        return self.resume_result

    def active_processes(self, job: int) -> int:
        self._fail("active")
        result = (
            self.active_results.pop(0)
            if len(self.active_results) > 1
            else self.active_results[0]
        )
        self.calls.append(("active", job, result))
        return result

    def terminate_job(self, job: int, exit_code: int) -> None:
        self._fail("terminate_job")
        self.calls.append(("terminate_job", job, exit_code))
        if self.proc is not None:
            self.proc.returncode = exit_code

    def close_handle(self, handle: int) -> None:
        self.calls.append(("close", handle))
        self._fail(f"close_{handle}")
        if handle == 10 and self.proc is not None and self.proc.returncode is None:
            # Model JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE.
            self.proc.returncode = 1


class _CleanupStageStream(_FakeStream):
    def __init__(self, failure: BaseException | None = None) -> None:
        super().__init__()
        self._failure = failure

    def close(self) -> None:
        super().close()
        if self._failure is not None:
            raise self._failure


class _CleanupStageProcess(_FakeProcess):
    def __init__(
        self,
        calls: list[tuple[Any, ...]],
        fallback_failure: BaseException | None,
    ) -> None:
        super().__init__(calls)
        self._fallback_failure = fallback_failure

    def wait(self, timeout: float | None = None) -> int:
        if self._fallback_failure is not None:
            self.wait_calls += 1
            assert self.calls is not None
            self.calls.append(("wait", timeout))
            raise self._fallback_failure
        return super().wait(timeout)


class _CleanupStageApi(_FakeApi):
    def __init__(
        self,
        calls: list[tuple[Any, ...]],
        *,
        proc: _FakeProcess,
        stage: str,
        primary: BaseException,
        cleanup_failure: BaseException,
    ) -> None:
        super().__init__(calls, proc=proc)
        self._stage = stage
        self._primary = primary
        self._cleanup_failure = cleanup_failure

    def resume_thread(self, thread: int) -> int:
        self.calls.append(("resume", thread))
        raise self._primary

    def terminate_job(self, job: int, exit_code: int) -> None:
        self.calls.append(("terminate_job", job, exit_code))
        if self._stage == "initial_retire":
            raise self._cleanup_failure
        if self._stage == "fallback_reap":
            raise OSError("initial retire cleanup")
        assert self.proc is not None
        self.proc.returncode = exit_code

    def close_handle(self, handle: int) -> None:
        self.calls.append(("close", handle))
        if self._stage == "handle_close" and handle == 12:
            raise self._cleanup_failure
        if handle == 10 and self.proc is not None and self.proc.returncode is None:
            self.proc.returncode = 1


def test_spawn_assigns_suspended_process_before_exact_primary_thread_resume() -> None:
    calls: list[tuple[Any, ...]] = []
    proc = _FakeProcess()

    def popen(argv: list[str], **kwargs: Any) -> _FakeProcess:
        calls.append(("popen", tuple(argv), kwargs["creationflags"]))
        return proc

    spawned = spawn_windows_process(
        ["provider", "--stream"],
        creationflags=0x00000200,
        api=_FakeApi(calls),
        popen_factory=popen,
    )

    assert spawned.proc is proc
    assert ("popen", ("provider", "--stream"), 0x00000200 | CREATE_SUSPENDED) in calls
    assert calls.index(("assign", 10, 11)) < calls.index(("resume", 13))
    assert calls[-3:] == [("close", 13), ("close", 12), ("close", 11)]
    assert ("close", 10) not in calls


def test_spawn_uses_platform_api_loader_only_when_no_api_is_injected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[Any, ...]] = []
    proc = _FakeProcess()
    api = _FakeApi(calls)
    monkeypatch.setattr(win32_job_module, "Kernel32Api", lambda: api)

    spawned = spawn_windows_process(
        ["provider"],
        popen_factory=lambda *_args, **_kwargs: proc,
    )

    assert spawned.proc is proc
    assert ("assign", 10, 11) in calls


def test_spawn_rejects_breakaway_before_acquiring_any_resource() -> None:
    calls: list[tuple[Any, ...]] = []

    with pytest.raises(AdapterError, match="CREATE_BREAKAWAY_FROM_JOB"):
        spawn_windows_process(
            ["provider"],
            creationflags=CREATE_BREAKAWAY_FROM_JOB,
            api=_FakeApi(calls),
            popen_factory=lambda *_args, **_kwargs: pytest.fail(
                "breakaway must fail before Popen"
            ),
        )

    assert calls == []


def test_leader_signal_normalizes_public_popen_failure() -> None:
    calls: list[tuple[Any, ...]] = []
    proc = _FakeProcess()
    proc.terminate_error = OSError("TerminateProcess failed")
    spawned = spawn_windows_process(
        ["provider"],
        api=_FakeApi(calls),
        popen_factory=lambda *_args, **_kwargs: proc,
    )

    with pytest.raises(AdapterError, match="leader signal failed"):
        spawned.domain.signal_leader(signal.SIGINT)

    assert ("close", 10) not in calls


def test_unexpected_resume_count_fails_closed_and_releases_every_handle() -> None:
    calls: list[tuple[Any, ...]] = []
    proc = _FakeProcess()

    with pytest.raises(AdapterError, match="unexpected suspend count 0"):
        spawn_windows_process(
            ["provider"],
            api=_FakeApi(calls, proc=proc, resume_result=0),
            popen_factory=lambda *_args, **_kwargs: proc,
        )

    assert calls.index(("assign", 10, 11)) < calls.index(("resume", 13))
    assert ("terminate_job", 10, 1) in calls
    for handle in (10, 11, 12, 13):
        assert calls.count(("close", handle)) == 1
    assert proc.stdin.close_calls == 1
    assert proc.stdout.close_calls == 1


def test_setup_cleanup_reaps_after_termination_api_failure_and_job_close() -> None:
    calls: list[tuple[Any, ...]] = []
    proc = _FakeProcess()

    with pytest.raises(AdapterError, match="unexpected suspend count 0") as captured:
        spawn_windows_process(
            ["provider"],
            api=_FakeApi(
                calls,
                proc=proc,
                resume_result=0,
                fail_at="terminate_job",
            ),
            popen_factory=lambda *_args, **_kwargs: proc,
        )

    assert calls.count(("close", 10)) == 1
    assert proc.returncode == 1
    assert proc.wait_calls == 1
    assert any("terminate_job failed" in note for note in captured.value.__notes__)


@pytest.mark.parametrize(
    "stage",
    ["initial_retire", "stream_close", "handle_close", "fallback_reap"],
)
def test_setup_cleanup_contains_control_flow_failure_at_each_boundary(
    stage: str,
) -> None:
    """Every broad cleanup boundary preserves one control-flow primary."""

    calls: list[tuple[Any, ...]] = []
    primary = SystemExit("resume aborted")
    cleanup_failure = KeyboardInterrupt(f"{stage} cleanup")
    fallback_failure = cleanup_failure if stage == "fallback_reap" else None
    proc = _CleanupStageProcess(calls, fallback_failure)
    stream_failure = cleanup_failure if stage == "stream_close" else None
    proc.stdin = _CleanupStageStream(stream_failure)
    proc.stdout = _CleanupStageStream()
    stderr = _CleanupStageStream()
    cast(Any, proc).stderr = stderr
    api = _CleanupStageApi(
        calls,
        proc=proc,
        stage=stage,
        primary=primary,
        cleanup_failure=cleanup_failure,
    )

    with pytest.raises(SystemExit, match="resume aborted") as captured:
        spawn_windows_process(
            ["provider"],
            api=api,
            popen_factory=lambda *_args, **_kwargs: proc,
        )

    assert captured.value is primary
    notes = primary.__notes__
    assert any(str(cleanup_failure) in note for note in notes)
    if stage == "fallback_reap":
        assert any("initial retire cleanup" in note for note in notes)
    for handle in (10, 11, 12, 13):
        assert calls.count(("close", handle)) == 1
    assert proc.stdin.close_calls == 1
    assert proc.stdout.close_calls == 1
    assert stderr.close_calls == 1
    assert proc.wait_calls == 1


def test_assignment_failure_never_resumes_and_cleans_suspended_child() -> None:
    calls: list[tuple[Any, ...]] = []
    proc = _FakeProcess()

    with pytest.raises(AdapterError, match="assign failed"):
        spawn_windows_process(
            ["provider"],
            api=_FakeApi(calls, proc=proc, fail_at="assign"),
            popen_factory=lambda *_args, **_kwargs: proc,
        )

    assert not any(call[0] == "resume" for call in calls)
    assert not any(call[0] == "terminate_job" for call in calls)
    assert proc.returncode == 1
    assert proc.stdin.close_calls == 1
    assert proc.stdout.close_calls == 1
    assert calls.count(("close", 11)) == 1
    assert calls.count(("close", 10)) == 1


@pytest.mark.parametrize(
    ("failure", "closed_handles", "assigned"),
    [
        ("create_job", (), False),
        ("configure", (10,), False),
        ("open_process", (10,), False),
        ("snapshot", (11, 10), True),
        ("thread_entries", (12, 11, 10), True),
        ("open_thread", (12, 11, 10), True),
        ("resume", (13, 12, 11, 10), True),
        ("close_13", (13, 12, 11, 10), True),
    ],
)
def test_each_win32_setup_failure_releases_all_acquired_ownership(
    failure: str,
    closed_handles: tuple[int, ...],
    assigned: bool,
) -> None:
    calls: list[tuple[Any, ...]] = []
    proc = _FakeProcess()
    popen_calls = 0

    def popen(*_args: object, **_kwargs: object) -> _FakeProcess:
        nonlocal popen_calls
        popen_calls += 1
        return proc

    with pytest.raises(AdapterError, match=failure):
        spawn_windows_process(
            ["provider"],
            api=_FakeApi(calls, proc=proc, fail_at=failure),
            popen_factory=popen,
        )

    assert popen_calls == (0 if failure in {"create_job", "configure"} else 1)
    for handle in closed_handles:
        assert calls.count(("close", handle)) == 1
    assert any(call[0] == "terminate_job" for call in calls) is assigned
    if popen_calls:
        assert proc.returncode == 1
        assert proc.stdin.close_calls == 1
        assert proc.stdout.close_calls == 1


def test_popen_failure_releases_configured_job_without_publishing_child() -> None:
    calls: list[tuple[Any, ...]] = []

    def popen(*_args: object, **_kwargs: object) -> _FakeProcess:
        raise OSError("CreateProcess failed")

    with pytest.raises(AdapterError, match="CreateProcess failed"):
        spawn_windows_process(
            ["provider"],
            api=_FakeApi(calls),
            popen_factory=popen,
        )

    assert calls.count(("close", 10)) == 1
    assert not any(call[0] == "open_process" for call in calls)


@pytest.mark.parametrize("entries", [(), ((21, 4312), (22, 4312))])
def test_spawn_requires_exactly_one_thread_owned_by_suspended_pid(
    entries: tuple[tuple[int, int], ...],
) -> None:
    calls: list[tuple[Any, ...]] = []
    proc = _FakeProcess()
    api = _FakeApi(calls, proc=proc, entries=entries)

    with pytest.raises(AdapterError, match="expected exactly one"):
        spawn_windows_process(
            ["provider"],
            api=api,
            popen_factory=lambda *_args, **_kwargs: proc,
        )

    assert not any(call[0] == "resume" for call in calls)
    assert calls.count(("terminate_job", 10, 1)) == 1


def test_finalize_terminates_nonempty_job_and_proves_zero_before_release() -> None:
    calls: list[tuple[Any, ...]] = []
    proc = _FakeProcess()
    api = _FakeApi(calls, proc=proc, active_results=[2, 1, 0])
    spawned = spawn_windows_process(
        ["provider"],
        api=api,
        popen_factory=lambda *_args, **_kwargs: proc,
    )

    assert spawned.domain.finalize(graceful_timeout=0.0, kill_timeout=0.1) == 1
    assert spawned.domain.final_active_processes == 0

    assert calls.count(("terminate_job", 10, 1)) == 1
    assert [call for call in calls if call[0] == "active"] == [
        ("active", 10, 2),
        ("active", 10, 1),
        ("active", 10, 0),
    ]
    assert calls.index(("active", 10, 0)) < calls.index(("close", 10))


def test_natural_exit_observation_stays_unreaped_until_job_zero_proof() -> None:
    calls: list[tuple[Any, ...]] = []
    proc = _FakeProcess(calls)
    proc.returncode = 7
    spawned = spawn_windows_process(
        ["provider"],
        api=_FakeApi(calls, proc=proc, active_results=[0]),
        popen_factory=lambda *_args, **_kwargs: proc,
    )

    assert spawned.domain.observe_leader_exit() == 7
    assert spawned.domain.final_active_processes is None
    assert spawned.domain.wait_for_leader_exit(0.01) == 7
    assert proc.wait_calls == 0

    assert spawned.domain.finalize(graceful_timeout=0.0) == 7

    assert proc.wait_calls == 1
    active_index = calls.index(("active", 10, 0))
    wait_index = next(index for index, call in enumerate(calls) if call[0] == "wait")
    assert active_index < wait_index < calls.index(("close", 10))


def test_bounded_leader_wait_polls_natural_exit_without_reaping() -> None:
    now = 0.0
    proc = _FakeProcess()

    def monotonic() -> float:
        return now

    def sleep(seconds: float) -> None:
        nonlocal now
        now += seconds
        if now >= 0.02:
            proc.returncode = 4

    spawned = spawn_windows_process(
        ["provider"],
        api=_FakeApi([]),
        popen_factory=lambda *_args, **_kwargs: proc,
        monotonic=monotonic,
        sleep=sleep,
    )

    assert spawned.domain.wait_for_leader_exit(0.05) == 4
    assert now == pytest.approx(0.02)
    assert proc.wait_calls == 0


def test_domain_exposes_read_only_active_process_count() -> None:
    calls: list[tuple[Any, ...]] = []
    spawned = spawn_windows_process(
        ["provider"],
        api=_FakeApi(calls, active_results=[2]),
        popen_factory=lambda *_args, **_kwargs: _FakeProcess(),
    )

    assert spawned.domain.active_processes() == 2
    assert ("close", 10) not in calls


def test_finalize_timeout_closes_kill_on_close_job_and_reaps_leader() -> None:
    calls: list[tuple[Any, ...]] = []
    proc = _FakeProcess()
    api = _FakeApi(calls, proc=proc, active_results=[1])
    now = 0.0

    def monotonic() -> float:
        return now

    def sleep(seconds: float) -> None:
        nonlocal now
        now += seconds

    spawned = spawn_windows_process(
        ["provider"],
        api=api,
        popen_factory=lambda *_args, **_kwargs: proc,
        monotonic=monotonic,
        sleep=sleep,
    )

    with pytest.raises(AdapterError, match="still has 1 active processes"):
        spawned.domain.finalize(graceful_timeout=0.0, kill_timeout=0.02)

    assert calls.count(("close", 10)) == 1
    assert proc.returncode == 1
    assert proc.wait_calls == 1


@pytest.mark.parametrize("failure", ["active", "terminate_job"])
def test_finalize_api_failure_uses_kill_on_close_and_preserves_primary(
    failure: str,
) -> None:
    calls: list[tuple[Any, ...]] = []
    proc = _FakeProcess()
    api = _FakeApi(
        calls,
        proc=proc,
        active_results=[1],
        fail_at=failure,
    )
    spawned = spawn_windows_process(
        ["provider"],
        api=api,
        popen_factory=lambda *_args, **_kwargs: proc,
    )

    with pytest.raises(AdapterError, match=failure):
        spawned.domain.finalize(graceful_timeout=0.0, kill_timeout=0.01)

    assert calls.count(("close", 10)) == 1
    assert proc.returncode == 1
    assert proc.wait_calls == 1


def test_finalize_is_idempotent_after_success() -> None:
    calls: list[tuple[Any, ...]] = []
    proc = _FakeProcess()
    api = _FakeApi(calls, proc=proc, active_results=[1, 0])
    spawned = spawn_windows_process(
        ["provider"],
        api=api,
        popen_factory=lambda *_args, **_kwargs: proc,
        sleep=lambda _seconds: None,
    )

    assert spawned.domain.finalize(graceful_timeout=0.0) == 1
    calls_after_first = list(calls)
    assert spawned.domain.finalize(graceful_timeout=0.0) == 1
    assert calls == calls_after_first
    assert proc.wait_calls == 1


@pytest.mark.skipif(os.name != "nt", reason="real incompatible nested-job proof")
@pytest.mark.xdist_group("process")
def test_real_nested_job_assignment_rejects_before_provider_execution(
    tmp_path: Path,
) -> None:
    """[SUM-7.1] Real assignment failure leaves the provider suspended."""

    result = tmp_path / "nested-job-result"
    provider_marker = tmp_path / "provider-started"
    helper = """
import subprocess
import sys
import ctypes
from pathlib import Path

from taut_summon import _win32_job
from taut_summon._process_domain import spawn_process

result, marker = map(Path, sys.argv[1:])
configure_kill_on_close = _win32_job.Kernel32Api.configure_kill_on_close
blockers = []

def configure_full_nested_job(api, job):
    configure_kill_on_close(api, job)
    limits = _win32_job.JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
    limits.BasicLimitInformation.LimitFlags = 0x00002000 | 0x00000008
    limits.BasicLimitInformation.ActiveProcessLimit = 1
    if not api._set_job_information(
        _win32_job.HANDLE(job),
        9,
        ctypes.byref(limits),
        ctypes.sizeof(limits),
    ):
        api._raise_last_error("SetInformationJobObject")
    blocker = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    blockers.append(blocker)
    process_handle = api.open_process(blocker.pid)
    try:
        api.assign_process(job, process_handle)
    finally:
        api.close_handle(process_handle)

_win32_job.Kernel32Api.configure_kill_on_close = configure_full_nested_job
provider = "from pathlib import Path; import sys; Path(sys.argv[1]).write_text('started', encoding='utf-8')"
try:
    spawned = spawn_process(
        [sys.executable, "-c", provider, str(marker)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
except BaseException as exc:
    result.write_text(f"{type(exc).__name__}: {exc}", encoding="utf-8")
else:
    try:
        spawned.domain.finalize(graceful_timeout=0.0)
    finally:
        result.write_text("unexpected success", encoding="utf-8")
finally:
    for blocker in blockers:
        try:
            blocker.wait(timeout=5.0)
        except subprocess.TimeoutExpired:
            blocker.terminate()
            blocker.wait(timeout=5.0)
"""
    outer = spawn_windows_process(
        [
            sys.executable,
            "-c",
            helper,
            str(result),
            str(provider_marker),
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
    )
    try:
        deadline = time.monotonic() + 15.0
        while not result.exists():
            assert time.monotonic() < deadline, "nested-job helper did not finish"
            time.sleep(0.01)

        diagnostic = result.read_text(encoding="utf-8")
        assert "AssignProcessToJobObject" in diagnostic
        assert not provider_marker.exists()
        assert outer.domain.wait_for_leader_exit(5.0) == 0
    finally:
        outer.domain.finalize()
