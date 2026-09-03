"""Public Summon embedding contract tests ([SUM-13])."""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import threading
import time
import tomllib
from collections.abc import Callable
from dataclasses import fields
from pathlib import Path
from typing import Any

import psutil
import pytest
from simplebroker import Queue
from taut_summon._control import control_in_queue_name
from taut_summon._state import (
    capture_driver_evidence,
    ensure_summon_schema,
    get_session,
    record_session,
)
from taut_summon.controller import _status_from_reply

from taut import TautClient
from taut.client import Member

pytestmark = pytest.mark.sqlite_only

PROJECT_ROOT = Path(__file__).resolve().parents[3]

EXPECTED_PUBLIC_EXPORTS = [
    "ActivityEvent",
    "AdapterError",
    "AdapterEvent",
    "AdapterHandle",
    "DriverUnresponsive",
    "ExitEvent",
    "NothingSummoned",
    "ProviderAdapter",
    "ShellSummonInteraction",
    "StopResult",
    "SummonController",
    "SummonInteraction",
    "SummonOperationError",
    "SummonRequest",
    "SummonRunHandle",
    "SummonStatus",
    "SummonedMember",
    "TerminalAttachNotice",
    "TerminalAvailability",
    "TerminalIntent",
    "TerminalLease",
    "UnknownAdapterError",
    "adapter_names",
    "get_adapter",
]


def _member() -> Member:
    return Member(
        member_id="m_reviewer",
        name="reviewer",
        aliases=(),
        kind="agent",
        presence="active",
        last_active_ts=1,
    )


def _status_reply() -> dict[str, Any]:
    return {
        "command": "STATUS",
        "status": "ok",
        "request_id": "req-1",
        "driver": "alive",
        "provider": "scripted",
        "thread_count": 1,
        "cursor_lag": {"general": 0},
        "control_health": "ok",
    }


def _create_live_member(db: Path, *, name: str = "reviewer") -> Member:
    TautClient.init(db_path=db)
    client = TautClient(db_path=db, as_name=name)
    try:
        client.join("general")
        member = client.last_created_member
        assert member is not None and member.token is not None
    finally:
        client.close()
    queue = Queue("taut.summon_state", db_path=str(db))
    try:
        ensure_summon_schema(queue)
        pid, start = capture_driver_evidence(os.getpid())
        record_session(
            queue,
            member_id=member.member_id,
            token=member.token,
            provider="scripted",
            driver_pid=pid,
            driver_start_time=start,
            updated_ts=queue.generate_timestamp(),
        )
    finally:
        queue.close()
    return member


def _create_foreground_project(db: Path, *, occupied_name: str | None = None) -> None:
    TautClient.init(db_path=db)
    client = TautClient(db_path=db, as_name="van")
    try:
        client.join("general")
    finally:
        client.close()
    if occupied_name is not None:
        occupied = TautClient(db_path=db, as_name=occupied_name)
        try:
            occupied.join("general")
        finally:
            occupied.close()


def _scripted_foreground_environment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    tag: str,
    scenario: dict[str, Any] | None = None,
) -> Path:
    scenario_path = tmp_path / f"{tag}-scenario.json"
    received_path = tmp_path / f"{tag}-received.jsonl"
    scenario_path.write_text(json.dumps(scenario or {}), encoding="utf-8")
    monkeypatch.setenv("TAUT_SUMMON_SCENARIO", str(scenario_path))
    monkeypatch.setenv("TAUT_SUMMON_RECEIVED_LOG", str(received_path))
    monkeypatch.setenv("TAUT_SUMMON_RESUME_BACKOFF", "0.05,0.05")
    monkeypatch.setenv("TAUT_SUMMON_CONTROL_INTERVAL", "0.02")
    return received_path


def _foreground_request(name: str) -> Any:
    from taut_summon import SummonRequest

    return SummonRequest(
        name=name,
        threads=("general",),
        persona=None,
        system_prompt_file=None,
        rate_limit=None,
        detach=True,
    )


def _received_entries(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _wait_until(
    predicate: Callable[[], bool], *, timeout: float = 10.0, message: str
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError(f"timed out waiting for {message}")


def test_public_controller_models_have_exact_fields() -> None:
    from taut_summon import (
        DriverUnresponsive,
        NothingSummoned,
        StopResult,
        SummonedMember,
        SummonOperationError,
        SummonRequest,
        SummonStatus,
    )

    assert tuple(field.name for field in fields(SummonRequest)) == (
        "name",
        "threads",
        "persona",
        "system_prompt_file",
        "rate_limit",
        "attach",
        "detach",
        "provider_flag",
        "takeover",
    )
    assert tuple(field.name for field in fields(SummonedMember)) == (
        "member_id",
        "name",
        "provider",
    )
    assert tuple(field.name for field in fields(SummonStatus)) == (
        "member_id",
        "name",
        "driver",
        "provider",
        "thread_count",
        "cursor_lag",
        "details",
    )
    assert tuple(field.name for field in fields(StopResult)) == (
        "member_id",
        "name",
    )
    assert issubclass(NothingSummoned, SummonOperationError)
    assert issubclass(DriverUnresponsive, SummonOperationError)


def test_foreground_ready_callback_is_once_and_control_live_across_resume(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from taut_summon import (
        ShellSummonInteraction,
        SummonController,
        SummonRunHandle,
    )

    db = tmp_path / ".taut.db"
    _create_foreground_project(db)
    received = _scripted_foreground_environment(
        monkeypatch,
        tmp_path,
        tag="ready-resume",
        scenario={},
    )
    controller = SummonController(db_path=db)
    ready = threading.Event()
    callbacks: list[SummonRunHandle] = []
    callback_threads: list[int] = []
    callback_statuses: list[Any] = []
    failures: list[BaseException] = []

    def on_ready(handle: SummonRunHandle) -> None:
        callbacks.append(handle)
        callback_threads.append(threading.get_ident())
        callback_statuses.append(controller.status(handle.member.name))
        ready.set()

    def run() -> None:
        try:
            controller.run_foreground(
                _foreground_request("scripted"),
                ShellSummonInteraction(),
                on_ready=on_ready,
            )
        except BaseException as exc:  # noqa: BLE001 approved [DOM-10.2.1] [RUFF-SUP-070] exception
            failures.append(exc)

    worker = threading.Thread(target=run, name="summon-ready-owner")
    worker.start()
    assert ready.wait(timeout=10.0)
    assert len(callbacks) == 1
    handle = callbacks[0]
    assert callback_threads == [worker.ident]
    assert handle.member.name == "Scripted"
    assert handle.member.provider == "scripted"
    assert callback_statuses[0].member_id == handle.member.member_id
    with pytest.raises(AttributeError):
        handle.member = handle.member

    starts = [
        entry for entry in _received_entries(received) if entry["event"] == "start"
    ]
    assert len(starts) == 1
    os.kill(int(starts[0]["pid"]), 9)
    _wait_until(
        lambda: (
            len(
                [
                    entry
                    for entry in _received_entries(received)
                    if entry["event"] == "start"
                ]
            )
            >= 2
        ),
        message="resumed scripted generation",
    )
    assert len(callbacks) == 1

    handle.request_stop()
    handle.request_stop()
    worker.join(timeout=10.0)
    assert not worker.is_alive()
    assert failures == []
    handle.request_stop()


def test_foreground_handle_stop_is_run_scoped_after_rename_and_completion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from taut_summon import ShellSummonInteraction, SummonController, SummonRunHandle

    db = tmp_path / ".taut.db"
    _create_foreground_project(db, occupied_name="scripted")
    _scripted_foreground_environment(monkeypatch, tmp_path, tag="run-scope")
    controller = SummonController(db_path=db)

    def start_run(
        name: str,
    ) -> tuple[threading.Thread, SummonRunHandle, list[BaseException]]:
        ready = threading.Event()
        handles: list[SummonRunHandle] = []
        failures: list[BaseException] = []

        def on_ready(handle: SummonRunHandle) -> None:
            handles.append(handle)
            ready.set()

        def run() -> None:
            try:
                controller.run_foreground(
                    _foreground_request(name),
                    ShellSummonInteraction(),
                    on_ready=on_ready,
                )
            except BaseException as exc:  # noqa: BLE001 approved [DOM-10.2.1] [RUFF-SUP-070] exception
                failures.append(exc)

        worker = threading.Thread(target=run)
        worker.start()
        assert ready.wait(timeout=10.0)
        return worker, handles[0], failures

    first_worker, first, first_failures = start_run("scripted")
    assert first.member.name != "scripted"
    state = Queue("taut.summon_state", db_path=str(db))
    try:
        row = get_session(state, first.member.member_id)
    finally:
        state.close()
    assert row is not None
    identity = TautClient(db_path=db, token=row["token"])
    try:
        renamed = identity.set_name("reviewer")
    finally:
        identity.close()
    assert renamed.member_id == first.member.member_id

    first.request_stop()
    first_worker.join(timeout=10.0)
    assert not first_worker.is_alive()
    assert first_failures == []

    second_worker, second, second_failures = start_run("reviewer")
    assert second.member.member_id == first.member.member_id
    first.request_stop()
    time.sleep(0.1)
    assert second_worker.is_alive()
    assert controller.status("reviewer").member_id == second.member.member_id
    second.request_stop()
    second_worker.join(timeout=10.0)
    assert not second_worker.is_alive()
    assert second_failures == []


def test_foreground_ready_callback_failure_cleans_up_and_preserves_cause(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from taut_summon import (
        ShellSummonInteraction,
        SummonController,
        SummonOperationError,
        SummonRunHandle,
    )

    db = tmp_path / ".taut.db"
    _create_foreground_project(db)
    received = _scripted_foreground_environment(
        monkeypatch, tmp_path, tag="callback-failure"
    )
    failure = RuntimeError("host callback failed")
    seen: list[SummonRunHandle] = []
    child_processes: list[psutil.Process] = []

    def on_ready(handle: SummonRunHandle) -> None:
        seen.append(handle)
        starts = [
            entry for entry in _received_entries(received) if entry["event"] == "start"
        ]
        assert len(starts) == 1
        # Retain the child's creation identity while it is known live. A later
        # PID-only probe can observe a reused PID, and os.kill(pid, 0) is not a
        # harmless existence check on Windows.
        child_processes.append(psutil.Process(int(starts[0]["pid"])))
        raise failure

    with pytest.raises(
        SummonOperationError, match="readiness callback failed"
    ) as caught:
        SummonController(db_path=db).run_foreground(
            _foreground_request("scripted"),
            ShellSummonInteraction(),
            on_ready=on_ready,
        )

    assert caught.value.__cause__ is failure
    assert len(seen) == 1
    state = Queue("taut.summon_state", db_path=str(db))
    try:
        row = get_session(state, seen[0].member.member_id)
    finally:
        state.close()
    assert row is not None
    assert row["driver_pid"] is None
    starts = [
        entry for entry in _received_entries(received) if entry["event"] == "start"
    ]
    assert len(starts) == 1
    assert len(child_processes) == 1
    assert not child_processes[0].is_running()


def test_foreground_ready_callback_may_request_immediate_stop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from taut_summon import ShellSummonInteraction, SummonController, SummonRunHandle

    db = tmp_path / ".taut.db"
    _create_foreground_project(db)
    _scripted_foreground_environment(monkeypatch, tmp_path, tag="immediate-stop")
    seen: list[SummonRunHandle] = []

    def on_ready(handle: SummonRunHandle) -> None:
        seen.append(handle)
        handle.request_stop()

    SummonController(db_path=db).run_foreground(
        _foreground_request("scripted"),
        ShellSummonInteraction(),
        on_ready=on_ready,
    )

    assert len(seen) == 1
    seen[0].request_stop()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("thread_count", True),
        ("cursor_lag", {"general": True}),
        ("extra", {"nested": "object"}),
        ("extra", float("nan")),
    ],
)
def test_status_validation_rejects_non_contract_values(
    field: str, value: object
) -> None:
    from taut_summon import SummonOperationError

    reply = _status_reply()
    reply[field] = value

    with pytest.raises(SummonOperationError, match="invalid STATUS"):
        _status_from_reply(_member(), reply)


def test_status_mapping_copies_structured_fields_and_excludes_protocol_keys() -> None:
    reply = _status_reply()

    status = _status_from_reply(_member(), reply)

    assert status.cursor_lag == {"general": 0}
    assert status.details == {"control_health": "ok"}
    raw_lag = reply["cursor_lag"]
    assert isinstance(raw_lag, dict)
    raw_lag["general"] = 9
    reply["control_health"] = "degraded"
    assert status.cursor_lag == {"general": 0}
    assert status.details == {"control_health": "ok"}


def test_all_advertised_provider_names_resolve_to_pty_adapter() -> None:
    from taut_summon import SummonController, get_adapter
    from taut_summon._pty import PtyAdapter

    assert SummonController().provider_names() == (
        "claude",
        "coder",
        "codex",
        "grok",
        "kimi",
        "opencode",
        "pi",
        "pty",
        "qwen",
        "scripted",
    )
    assert all(
        isinstance(get_adapter(name), PtyAdapter)
        for name in SummonController().provider_names()
    )


def test_structured_adapter_surface_is_absent() -> None:
    import taut_summon
    from taut_summon import _adapter

    assert "AssistantTextEvent" not in _adapter.__dict__
    assert "SessionEvent" not in _adapter.__dict__
    assert "session_id" not in _adapter.AdapterHandle.__dict__
    assert "supports_terminal_mode" not in _adapter.ProviderAdapter.__annotations__
    assert "emits_session_events" not in _adapter.ProviderAdapter.__annotations__
    assert "AssistantTextEvent" not in taut_summon.__all__
    assert "SessionEvent" not in taut_summon.__all__
    assert "ScriptedAdapter" not in taut_summon.__all__


def test_claude_stream_is_unknown_and_not_advertised() -> None:
    from taut_summon import SummonController, UnknownAdapterError, get_adapter

    assert "claude-stream" not in SummonController().provider_names()
    with pytest.raises(UnknownAdapterError, match="claude-stream"):
        get_adapter("claude-stream")


def _stored_provider_request(name: str, provider: str | None) -> Any:
    """Build the public request used by legacy-provider recovery probes."""
    from taut_summon import SummonRequest

    return SummonRequest(
        name=name,
        threads=("general",),
        persona=None,
        system_prompt_file=None,
        rate_limit=None,
        attach=False,
        detach=True,
        provider_flag=provider,
        takeover=False,
    )


def _create_stored_provider_member(
    db: Path,
    *,
    provider: str,
    driver_pid: int | None,
    driver_start_time: str | None,
) -> str:
    TautClient.init(db_path=db)
    client = TautClient(db_path=db, as_name="reviewer")
    try:
        client.join("general")
        member = client.last_created_member
        assert member is not None and member.token is not None
    finally:
        client.close()
    queue = Queue("taut.summon_state", db_path=str(db))
    try:
        ensure_summon_schema(queue)
        partial_evidence = (driver_pid is None) != (driver_start_time is None)
        record_session(
            queue,
            member_id=member.member_id,
            token=member.token,
            provider=provider,
            driver_pid=None if partial_evidence else driver_pid,
            driver_start_time=None if partial_evidence else driver_start_time,
            updated_ts=queue.generate_timestamp(),
        )
        with queue.sidecar(transaction=True) as session:
            session.run(
                "UPDATE taut_summon_sessions SET provider_session_id = ? WHERE member_id = ?",
                ("released-v1-session", member.member_id),
            )
        if partial_evidence:
            with queue.sidecar(transaction=True) as session:
                session.run(
                    """
                    UPDATE taut_summon_sessions
                    SET driver_pid = ?, driver_start_time = ?
                    WHERE member_id = ?
                    """,
                    (driver_pid, driver_start_time, member.member_id),
                )
    finally:
        queue.close()
    return member.member_id


@pytest.mark.parametrize(
    (
        "case",
        "stored_provider",
        "evidence",
        "requested_provider",
        "accepted",
        "diagnostic",
    ),
    (
        ("absent", "claude-stream", "absent", "claude", True, None),
        ("proven-dead", "claude-stream", "dead", "claude", True, None),
        ("omitted", "claude-stream", "absent", None, False, "--provider claude"),
        ("live", "claude-stream", "live", "claude", False, "live"),
        ("pid-only", "claude-stream", "pid-only", "claude", False, "indeterminate"),
        (
            "start-only",
            "claude-stream",
            "start-only",
            "claude",
            False,
            "indeterminate",
        ),
        ("other-provider", "scripted", "absent", "claude", False, "refusing"),
    ),
)
def test_public_start_legacy_provider_recovery_matrix(
    case: str,
    stored_provider: str,
    evidence: str,
    requested_provider: str | None,
    accepted: bool,
    diagnostic: str | None,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from taut_summon import (
        ShellSummonInteraction,
        SummonController,
        SummonOperationError,
    )
    from taut_summon._driver import SummonDriver

    if evidence == "live":
        driver_pid, driver_start_time = capture_driver_evidence(os.getpid())
    elif evidence == "dead":
        driver_pid, driver_start_time = os.getpid(), "not-this-process-start"
    elif evidence == "pid-only":
        driver_pid, driver_start_time = os.getpid(), None
    elif evidence == "start-only":
        driver_pid, driver_start_time = None, "partial-start"
    else:
        driver_pid, driver_start_time = None, None

    db = tmp_path / f"{case}.db"
    member_id = _create_stored_provider_member(
        db,
        provider=stored_provider,
        driver_pid=driver_pid,
        driver_start_time=driver_start_time,
    )
    supervised: list[str] = []

    def finish_after_bootstrap(
        _driver: SummonDriver,
        boot: Any,
        _db_display: str,
        *,
        db_path: str | None = None,
    ) -> int:
        del db_path
        supervised.append(boot.provider)
        return 0

    monkeypatch.setattr(SummonDriver, "_supervise", finish_after_bootstrap)
    controller = SummonController(db_path=db)
    interaction = ShellSummonInteraction(
        input_stream=io.StringIO(), output_stream=io.StringIO()
    )
    request = _stored_provider_request("reviewer", requested_provider)

    if accepted:
        controller.run_foreground(request, interaction)
        # The migration is one-time. A second explicit start is an ordinary
        # same-provider resume, not another compatibility rewrite.
        controller.run_foreground(request, interaction)
        assert supervised == ["claude", "claude"]
        expected_provider = "claude"
    else:
        assert diagnostic is not None
        with pytest.raises(SummonOperationError, match=diagnostic):
            controller.run_foreground(request, interaction)
        assert supervised == []
        expected_provider = stored_provider

    queue = Queue("taut.summon_state", db_path=str(db))
    try:
        row = get_session(queue, member_id)
    finally:
        queue.close()
    assert row is not None
    assert row["provider"] == expected_provider


def test_public_start_refuses_legacy_provider_recovery_after_predicate_loss(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import taut_summon._driver as driver_module
    from taut_summon import (
        ShellSummonInteraction,
        SummonController,
        SummonOperationError,
    )
    from taut_summon._driver import SummonDriver

    db = tmp_path / "predicate-loss.db"
    member_id = _create_stored_provider_member(
        db,
        provider="claude-stream",
        driver_pid=None,
        driver_start_time=None,
    )
    supervised: list[str] = []
    monkeypatch.setattr(
        SummonDriver,
        "_supervise",
        lambda _driver, boot, _display, **_kwargs: (
            supervised.append(boot.provider) or 0
        ),
    )
    original_liveness = driver_module.driver_liveness
    contenders_ready = threading.Barrier(2)

    def synchronized_liveness(row: Any) -> Any:
        result = original_liveness(row)
        contenders_ready.wait(timeout=5.0)
        return result

    monkeypatch.setattr(driver_module, "driver_liveness", synchronized_liveness)
    outcomes: list[BaseException | None] = []

    def run_contender() -> None:
        controller = SummonController(db_path=db)
        interaction = ShellSummonInteraction(
            input_stream=io.StringIO(), output_stream=io.StringIO()
        )
        try:
            controller.run_foreground(
                _stored_provider_request("reviewer", "claude"), interaction
            )
        except BaseException as exc:  # noqa: BLE001 approved [DOM-10.2.1] [RUFF-SUP-070] exception
            outcomes.append(exc)
        else:
            outcomes.append(None)

    contenders = [threading.Thread(target=run_contender) for _ in range(2)]
    for contender in contenders:
        contender.start()
    for contender in contenders:
        contender.join(timeout=10.0)

    assert all(not contender.is_alive() for contender in contenders)
    assert len(supervised) == 1
    assert sum(outcome is None for outcome in outcomes) == 1
    failures = [outcome for outcome in outcomes if outcome is not None]
    assert len(failures) == 1
    assert isinstance(failures[0], SummonOperationError)
    assert "changed concurrently" in str(failures[0])
    queue = Queue("taut.summon_state", db_path=str(db))
    try:
        row = get_session(queue, member_id)
    finally:
        queue.close()
    assert row is not None
    assert row["provider"] == "claude"


def test_controller_empty_list_returns_empty_tuple_without_printing(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from taut_summon import SummonController

    controller = SummonController(db_path=str(tmp_path / "missing.db"))

    assert controller.list_live() == ()

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_controller_lists_live_sessions_as_typed_current_members(
    tmp_path: Path,
) -> None:
    from taut_summon import SummonController, SummonedMember

    db = tmp_path / ".taut.db"
    TautClient.init(db_path=db)
    created: list[tuple[str, str]] = []
    for name in ("reviewer", "archivist"):
        client = TautClient(db_path=db, as_name=name)
        try:
            client.join("general")
            member = client.last_created_member
            assert member is not None and member.token is not None
            created.append((member.member_id, member.token))
        finally:
            client.close()
    queue = Queue("taut.summon_state", db_path=str(db))
    try:
        ensure_summon_schema(queue)
        pid, start = capture_driver_evidence(os.getpid())
        record_session(
            queue,
            member_id=created[0][0],
            token=created[0][1],
            provider="scripted",
            driver_pid=pid,
            driver_start_time=start,
            updated_ts=queue.generate_timestamp(),
        )
        record_session(
            queue,
            member_id=created[1][0],
            token=created[1][1],
            provider="claude",
            updated_ts=queue.generate_timestamp(),
        )
    finally:
        queue.close()

    assert SummonController(db_path=db).list_live() == (
        SummonedMember(
            member_id=created[0][0],
            name="reviewer",
            provider="scripted",
        ),
    )


def test_controller_status_and_stop_use_real_correlated_control_plane(
    summon_db: Path,
    driver_factory: Callable[..., Any],
) -> None:
    from taut_summon import StopResult, SummonController, SummonStatus

    driver = driver_factory(summon_db, "reviewer", provider="scripted")
    driver.wait_for_start()
    controller = SummonController(db_path=summon_db)

    first = controller.status("reviewer")

    assert isinstance(first, SummonStatus)
    assert first.name == "reviewer"
    assert first.driver == "alive"
    assert first.provider == "scripted"
    assert first.thread_count == 1
    assert first.cursor_lag == {"general": 0}
    assert first.details == {
        "awaiting_onboarding": "true",
        "control_health": "ok",
        "rate_breaches": 0,
        "rate_limited": False,
    }
    first.cursor_lag["general"] = 99
    first.details["control_health"] = "mutated"
    second = controller.status("reviewer")
    assert second.cursor_lag == {"general": 0}
    assert second.details["control_health"] == "ok"

    result = controller.stop("reviewer")

    assert result == StopResult(member_id=first.member_id, name="reviewer")
    assert driver.wait() == 0


@pytest.mark.parametrize("operation", ["status", "stop"])
def test_controller_unresponsive_driver_uses_typed_error_over_real_queues(
    operation: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import taut_summon.controller as controller_module
    from taut_summon import DriverUnresponsive, SummonController

    db = tmp_path / ".taut.db"
    _create_live_member(db)
    monkeypatch.setattr(controller_module, "_STATUS_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(controller_module, "_STOP_TIMEOUT_SECONDS", 0.05)

    with pytest.raises(DriverUnresponsive, match="driver did not"):
        getattr(SummonController(db_path=db), operation)("reviewer")

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_controller_refuses_error_stop_ack_before_release_confirmation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import taut_summon.controller as controller_module
    from taut_summon import SummonController, SummonOperationError

    db = tmp_path / ".taut.db"
    member = _create_live_member(db)
    responder_errors: list[BaseException] = []

    def respond() -> None:
        request_queue = Queue(control_in_queue_name(member.member_id), db_path=str(db))
        try:
            deadline = time.monotonic() + 2.0
            body: str | None = None
            while body is None and time.monotonic() < deadline:
                candidate = request_queue.read_one()
                body = candidate if isinstance(candidate, str) else None
                if body is None:
                    time.sleep(0.01)
            assert body is not None
            request = json.loads(body)
            reply_queue = Queue(request["reply_to"], db_path=str(db))
            try:
                reply_queue.write(
                    json.dumps(
                        {
                            "command": "STOP",
                            "status": "error",
                            "request_id": request["request_id"],
                            "error": "driver slot release could not be confirmed",
                        }
                    )
                )
            finally:
                reply_queue.close()
        except BaseException as exc:  # noqa: BLE001 approved [DOM-10.2.1] [RUFF-SUP-070] exception
            responder_errors.append(exc)
        finally:
            request_queue.close()

    monkeypatch.setattr(controller_module, "_STOP_TIMEOUT_SECONDS", 2.0)
    responder = threading.Thread(target=respond)
    responder.start()
    try:
        with pytest.raises(
            SummonOperationError, match="driver slot release could not be confirmed"
        ) as caught:
            SummonController(db_path=db).stop("reviewer")
    finally:
        responder.join(timeout=3.0)

    assert type(caught.value) is SummonOperationError
    assert not responder.is_alive()
    assert responder_errors == []


def test_release_confirmation_reads_once_after_final_sleep(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import taut_summon.controller as controller_module
    from taut_summon import SummonController

    now = 0.0
    released = False
    reads = 0

    class QueueHandle:
        def close(self) -> None:
            pass

    class Client:
        def queue(self, name: str) -> QueueHandle:
            assert name == "taut.summon_state"
            return QueueHandle()

    def monotonic() -> float:
        return now

    def sleep(seconds: float) -> None:
        nonlocal now, released
        assert 0 < seconds <= 0.05
        now += seconds
        if now >= 0.1:
            released = True

    def get_session(_queue: QueueHandle, member_id: str) -> dict[str, Any]:
        nonlocal reads
        assert member_id == "m_reviewer"
        reads += 1
        return {
            "driver_pid": None if released else 123,
            "driver_start_time": None if released else "start",
        }

    monkeypatch.setattr(controller_module.time, "monotonic", monotonic)
    monkeypatch.setattr(controller_module.time, "sleep", sleep)
    monkeypatch.setattr(controller_module, "get_session", get_session)

    assert SummonController._confirm_released(
        Client(),  # type: ignore[arg-type]
        "m_reviewer",
        driver_pid=123,
        driver_start_time="start",
        timeout=0.1,
    )
    assert reads == 3


def test_package_facade_is_lazy_and_preserves_introspection() -> None:
    code = """
import json
import sys

import taut_summon

before = sorted(name for name in sys.modules if name.startswith("taut_summon"))
all_visible = set(taut_summon.__all__) <= set(dir(taut_summon))
request_type = taut_summon.SummonRequest
after_request = sorted(name for name in sys.modules if name.startswith("taut_summon"))
controller_type = taut_summon.SummonController
after_controller = sorted(name for name in sys.modules if name.startswith("taut_summon"))
print(json.dumps({
    "before": before,
    "all_visible": all_visible,
    "request_module": request_type.__module__,
    "after_request": after_request,
    "controller_module": controller_type.__module__,
    "after_controller": after_controller,
}, sort_keys=True))
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["before"] == ["taut_summon"]
    assert payload["all_visible"] is True
    assert payload["request_module"] == "taut_summon.models"
    assert payload["after_request"] == ["taut_summon", "taut_summon.models"]
    assert payload["controller_module"] == "taut_summon.controller"
    assert "taut_summon._driver" not in payload["after_controller"]


def test_package_facade_preserves_exact_public_exports_and_object_identity() -> None:
    import taut_summon
    from taut_summon import _adapter
    from taut_summon.controller import SummonController
    from taut_summon.interaction import (
        ShellSummonInteraction,
        TerminalAttachNotice,
        TerminalLease,
    )
    from taut_summon.models import SummonRequest

    assert (
        len(taut_summon.__all__)
        == len(set(taut_summon.__all__))
        == len(EXPECTED_PUBLIC_EXPORTS)
    )
    assert set(taut_summon.__all__) == set(EXPECTED_PUBLIC_EXPORTS)
    assert taut_summon.ActivityEvent is _adapter.ActivityEvent
    assert taut_summon.adapter_names is _adapter.adapter_names
    assert taut_summon.get_adapter is _adapter.get_adapter
    assert taut_summon.SummonController is SummonController
    assert taut_summon.SummonRequest is SummonRequest
    assert taut_summon.ShellSummonInteraction is ShellSummonInteraction
    assert taut_summon.TerminalAttachNotice is TerminalAttachNotice
    assert taut_summon.TerminalLease is TerminalLease
    missing_name = "missing_public_name"
    with pytest.raises(AttributeError, match="missing_public_name"):
        getattr(taut_summon, missing_name)


def test_static_typing_rejects_unknown_summon_export(tmp_path: Path) -> None:
    probe = tmp_path / "unknown_summon_export.py"
    probe.write_text(
        "import taut_summon\n\ncontroller = taut_summon.SummonControllr\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "mypy",
            "--config-file",
            str(PROJECT_ROOT / "pyproject.toml"),
            str(probe),
        ],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 1
    assert 'Module has no attribute "SummonControllr"' in result.stdout


def test_command_manifest_has_exact_lightweight_specs_and_import_floor() -> None:
    script = """
import json
import sys
from taut_summon.command_manifest import dismiss, summon

def shape(spec):
    return {
        "api": spec.command_api_version,
        "name": spec.name,
        "summary": spec.summary,
        "globals": sorted(item.value for item in spec.post_verb_globals),
        "implementation": spec.implementation,
    }

print(json.dumps({
    "summon": shape(summon),
    "dismiss": shape(dismiss),
    "loaded": sorted(sys.modules),
}, sort_keys=True))
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["summon"] == {
        "api": 1,
        "name": "summon",
        "summary": "Start or resume a summoned agent harness.",
        "globals": ["db"],
        "implementation": "taut_summon.commands.summon:create_command",
    }
    assert payload["dismiss"] == {
        "api": 1,
        "name": "dismiss",
        "summary": "Stop one live summoned agent harness.",
        "globals": ["db"],
        "implementation": "taut_summon.commands.dismiss:create_command",
    }
    loaded = set(payload["loaded"])
    assert "taut_summon.command_manifest" in loaded
    assert "taut_summon.controller" not in loaded
    assert "taut_summon._adapter" not in loaded
    assert "taut_summon._control" not in loaded
    assert "taut_summon._driver" not in loaded
    assert "taut_summon._pty" not in loaded
    assert "taut_summon._state" not in loaded
    assert "taut_summon.commands.summon" not in loaded
    assert "taut_summon.commands.dismiss" not in loaded


def test_extension_metadata_registers_both_official_command_manifests() -> None:
    metadata = tomllib.loads(
        (PROJECT_ROOT / "extensions/taut_summon/pyproject.toml").read_text(
            encoding="utf-8"
        )
    )

    assert metadata["project"]["entry-points"]["taut.commands"] == {
        "summon": "taut_summon.command_manifest:summon",
        "dismiss": "taut_summon.command_manifest:dismiss",
    }
    assert metadata["project"]["entry-points"]["taut.command_syntax"] == {
        "taut-summon": "taut_summon.command_syntax:provide_syntax",
    }


def test_summon_syntax_provider_is_typed_and_execution_free() -> None:
    from taut_summon.command_syntax import provide_syntax

    from taut.commands.syntax import (
        core_command_syntax,
        merge_command_syntax,
        parse_command_line,
    )

    provider = provide_syntax()
    assert provider.provider_name == "taut-summon"
    assert tuple(command.path for command in provider.commands) == (
        ("summon",),
        ("dismiss",),
    )
    assert all(
        command.path not in {("taut",), ("taut-summon",)}
        for command in provider.commands
    )
    invocation = parse_command_line(
        "summon grok --provider scripted",
        syntax=merge_command_syntax(core_command_syntax(), (provider,)),
    )
    assert invocation.path == ("summon",)
    assert invocation.values["name"] == "grok"
    assert invocation.values["provider"] == "scripted"


@pytest.mark.parametrize(
    "argv",
    [
        ["--help"],
        ["run", "--help"],
        ["stop", "--help"],
        ["status", "--help"],
    ],
)
def test_standalone_help_does_not_import_runtime_subsystems(argv: list[str]) -> None:
    code = f"""
import contextlib
import io
import json
import sys

from taut_summon.cli import main

with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
    try:
        rc = main({argv!r})
    except SystemExit as exc:
        rc = exc.code
loaded = sorted(name for name in sys.modules if name.startswith(("taut", "simplebroker")))
print(json.dumps({{"rc": rc, "loaded": loaded}}, sort_keys=True))
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["rc"] == 0
    loaded = payload["loaded"]
    forbidden = (
        "simplebroker",
        "taut.client",
        "taut.state",
        "taut_summon._adapter",
        "taut_summon._control",
        "taut_summon._driver",
        "taut_summon._pty",
        "taut_summon._state",
        "taut_summon.controller",
        "taut_summon.interaction",
    )
    assert not [name for name in loaded if name.startswith(forbidden)]
