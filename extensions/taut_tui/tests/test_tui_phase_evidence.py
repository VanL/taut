"""Content-free diagnostics follow real owners without driving their work."""

from __future__ import annotations

import json
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import closing
from pathlib import Path

import pytest


def test_phase_records_keep_opaque_identity_and_only_safe_error_details(
    tmp_path: Path,
) -> None:
    from _phase_evidence import PhaseEvidence

    path = tmp_path / "phase.jsonl"
    clock = iter((100.0, 100.25, 100.5, 100.75))
    evidence = PhaseEvidence(path, clock=lambda: next(clock))
    first, second = object(), object()
    evidence.emit(first, "worker.completed", "error", error=ValueError("SECRET"))
    evidence.emit(second, "worker.completed", "success", generation=7)
    evidence.close()
    records = [json.loads(line) for line in path.read_text().splitlines()]
    assert records[:-1] == [
        {
            "sequence": 1,
            "request": 1,
            "phase": "worker.completed",
            "outcome": "error",
            "elapsed_s": 0.25,
            "error_type": "ValueError",
        },
        {
            "sequence": 2,
            "request": 2,
            "phase": "worker.completed",
            "outcome": "success",
            "elapsed_s": 0.5,
            "generation": 7,
        },
    ]
    assert "SECRET" not in path.read_text()


def test_phase_record_limit_is_a_single_tripwire_and_disposal_is_inert(
    tmp_path: Path,
) -> None:
    from _phase_evidence import PhaseEvidence

    path = tmp_path / "phase.jsonl"
    evidence = PhaseEvidence(path, max_records=2)
    for _ in range(20):
        evidence.emit(object(), "worker.completed", "success")
    evidence.close()
    evidence.emit(object(), "worker.completed", "error")
    records = [json.loads(line) for line in path.read_text().splitlines()]
    assert len(records) == 4
    assert records[-2]["phase"] == "recorder.tripwire"
    assert records[-2]["outcome"] == "truncated"
    assert records[-1]["phase"] == "test.summary"
    assert records[-1]["complete"] is False


def test_phase_records_serialize_concurrent_writers_without_losing_outcomes(
    tmp_path: Path,
) -> None:
    from _phase_evidence import PhaseEvidence

    path = tmp_path / "phase.jsonl"
    evidence = PhaseEvidence(path)
    owner = object()
    with ThreadPoolExecutor(max_workers=4) as workers:
        futures = [
            workers.submit(evidence.emit, owner, "worker.completed", "success")
            for _ in range(100)
        ]
        for future in futures:
            future.result()
    evidence.close()
    records = [json.loads(line) for line in path.read_text().splitlines()]
    assert [record["sequence"] for record in records] == list(range(1, 102))
    assert {record["request"] for record in records[:-1]} == {1}


def test_navigation_records_real_source_and_applied_dm_with_the_same_request(
    tmp_path: Path,
) -> None:
    import asyncio

    import pytest
    from _phase_evidence import PhaseEvidence, install_phase_observers

    from taut import TautClient
    from taut_tui.app import TautApp

    path = tmp_path / "phase.jsonl"
    database = tmp_path / "workspace.db"
    TautClient.init(db_path=database)
    with closing(TautClient(db_path=database, as_name="alice")) as alice:
        alice.join("general")
    with closing(TautClient(db_path=database, as_name="bob")) as bob:
        bob.join("general")
    with closing(TautClient(db_path=database, as_name="alice")) as alice:
        alice.say("@bob", "NEVER-EXPORT-THIS-BODY")

    evidence = PhaseEvidence(path)
    with pytest.MonkeyPatch.context() as patch:
        install_phase_observers(patch, evidence)

        async def exercise() -> None:
            app = TautApp(db_path=str(database), as_name="alice", continuity_token=None)
            async with app.run_test() as pilot:
                await pilot.pause()

        asyncio.run(exercise())
    evidence.close(test_kind="navigation")
    records = [json.loads(line) for line in path.read_text().splitlines()]
    source = next(row for row in records if row["phase"] == "navigation.source")
    applied = next(row for row in records if row["phase"] == "navigation.applied")
    assert source["source_dm_count"] == 1
    assert applied["rendered_dm_count"] == 1
    assert source["request"] == applied["request"]
    assert source["sequence"] < applied["sequence"]
    requested = next(row for row in records if row["phase"] == "navigation.requested")
    assert requested["request"] == source["request"]
    assert requested["elapsed_s"] <= source["elapsed_s"]
    assert records[-1]["complete"] is True
    assert "NEVER-EXPORT" not in path.read_text()


def test_confirmation_and_lease_observers_preserve_real_resolution_and_hold(
    tmp_path: Path,
) -> None:
    from contextlib import contextmanager
    from threading import Thread
    from typing import Any

    import pytest
    from _phase_evidence import PhaseEvidence, install_phase_observers
    from taut_summon import TerminalAttachNotice

    from taut_tui.summon import TerminalAttachConfirmationRequest, TerminalLeaseRequest

    path = tmp_path / "phase.jsonl"
    evidence = PhaseEvidence(path)
    calls: list[str] = []

    class Host:
        @contextmanager
        def suspend(self) -> Any:
            calls.append("suspended")
            yield
            calls.append("restored")

        def refresh(self, *, layout: bool) -> None:
            assert layout

    with pytest.MonkeyPatch.context() as patch:
        install_phase_observers(patch, evidence)
        confirmation = TerminalAttachConfirmationRequest(
            TerminalAttachNotice(member="private", provider="private", detach_hint="x")
        )
        confirmation.set_on_resolved(lambda: calls.append("resolved"))
        confirmation.resolve(True)
        confirmation.resolve(False)
        assert confirmation.decision is True
        assert calls == ["resolved"]
        request = TerminalLeaseRequest()
        thread = Thread(target=request.hold, args=(Host(),))
        thread.start()
        try:
            assert request.acquired.wait(2)
        finally:
            request.release.set()
            thread.join(2)
        assert not thread.is_alive()
        assert request.restored.is_set()
    evidence.close()
    records = [json.loads(line) for line in path.read_text().splitlines()]
    phases = [row["phase"] for row in records]
    assert phases.count("confirmation.resolved") == 1
    assert phases.index("lease.acquired") < phases.index("lease.restored")
    assert phases.index("lease.restored") < phases.index("lease.hold_returned")
    assert calls == ["resolved", "suspended", "restored"]


def test_provider_acknowledgement_requires_a_complete_chunk_spanning_echo(
    tmp_path: Path,
) -> None:
    from _phase_evidence import EchoCapture, PhaseEvidence

    path = tmp_path / "phase.jsonl"
    evidence = PhaseEvidence(path)
    capture = EchoCapture(evidence, object(), b"private-orientation-marker")
    capture.feed(b"private-orientation-marker\r\nchat> ")
    capture.feed(b"\r\nech")
    capture.feed(b"o:[200~private-orient")
    capture.feed(b"ation-marker[201~\r\r\n")
    assert path.read_text() == ""
    capture.feed(b"chat> ")
    capture.feed(b"\r\necho:private-orientation-marker\r\nchat> ")
    evidence.close()
    records = [json.loads(line) for line in path.read_text().splitlines()]
    assert [row["phase"] for row in records] == ["provider.consumed", "test.summary"]
    assert records[0]["outcome"] == "success"
    assert "private-orientation-marker" not in path.read_text()


def test_source_errors_and_cancellation_survive_successful_ui_callbacks(
    tmp_path: Path,
) -> None:
    import asyncio

    import pytest
    from _phase_evidence import PhaseEvidence, install_phase_observers

    from taut_tui.app import TautApp

    path = tmp_path / "phase.jsonl"
    evidence = PhaseEvidence(path)
    failed: Future[None] = Future()
    failed.set_exception(ValueError("DO-NOT-EXPORT"))
    cancelled: Future[None] = Future()
    assert cancelled.cancel()
    applied: list[Future[None]] = []

    with pytest.MonkeyPatch.context() as patch:
        install_phase_observers(patch, evidence)

        async def exercise() -> None:
            app = TautApp(db_path=None, as_name=None, continuity_token=None)
            async with app.run_test() as pilot:
                app._watch_future(failed, applied.append)
                app._watch_future(cancelled, applied.append)
                await pilot.pause()

        asyncio.run(exercise())
    evidence.close()
    assert applied == [failed, cancelled]
    records = [json.loads(line) for line in path.read_text().splitlines()]
    callbacks = [row for row in records if row["phase"] == "callback.applied"]
    assert any(
        row["outcome"] == "error" and row["error_type"] == "ValueError"
        for row in callbacks
    )
    assert any(row["outcome"] == "cancelled" for row in callbacks)
    assert failed.exception() is not None
    assert cancelled.cancelled()
    assert "DO-NOT-EXPORT" not in path.read_text()


def test_confirmation_failure_keeps_error_and_production_callback(
    tmp_path: Path,
) -> None:
    import pytest
    from _phase_evidence import PhaseEvidence, install_phase_observers
    from taut_summon import TerminalAttachNotice

    from taut_tui.summon import TerminalAttachConfirmationRequest

    path = tmp_path / "phase.jsonl"
    evidence = PhaseEvidence(path)
    error = ValueError("NO-CONTENT")
    calls: list[bool] = []
    with pytest.MonkeyPatch.context() as patch:
        install_phase_observers(patch, evidence)
        request = TerminalAttachConfirmationRequest(
            TerminalAttachNotice(member="private", provider="private", detach_hint="x")
        )
        request.set_on_resolved(lambda: calls.append(True))
        request.fail(error)
        request.resolve(True)
        assert request.error is error
        assert request.decision is None
    evidence.close()
    assert calls == [True]
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    resolved = [row for row in rows if row["phase"] == "confirmation.resolved"]
    assert len(resolved) == 1
    assert resolved[0]["outcome"] == "error"
    assert resolved[0]["error_type"] == "ValueError"
    assert "NO-CONTENT" not in path.read_text()


def test_recovery_summary_rejects_success_phases_from_different_owners(
    tmp_path: Path,
) -> None:
    from _phase_evidence import PhaseEvidence

    path = tmp_path / "phase.jsonl"
    evidence = PhaseEvidence(path)
    for phase in (
        "confirmation.resolved",
        "lease.acquired",
        "lease.restored",
        "lease.hold_returned",
        "provider.injected",
        "provider.consumed",
        "resource.closed",
    ):
        evidence.emit(object(), phase, "success")
    evidence.close(test_kind="recovery")
    summary = json.loads(path.read_text().splitlines()[-1])
    assert summary["complete"] is False
    assert "lease.lifecycle" in summary["missing"]
    assert "provider.two_consumed_and_retired" in summary["missing"]


def test_transition_time_is_retained_when_other_threads_write_first(
    tmp_path: Path,
) -> None:
    from _phase_evidence import PhaseEvidence

    path = tmp_path / "phase.jsonl"
    clock = iter((100.0, 100.25, 100.5, 100.75))
    evidence = PhaseEvidence(path, clock=lambda: next(clock))
    transition = evidence.now()
    evidence.emit(object(), "lease.acquired", "success")
    evidence.emit(object(), "confirmation.resolved", "success", at=transition)
    evidence.close()
    records = [json.loads(line) for line in path.read_text().splitlines()]
    assert records[0]["sequence"] == 1
    assert records[0]["elapsed_s"] == 0.5
    assert records[1]["sequence"] == 2
    assert records[1]["elapsed_s"] == 0.25


def test_required_navigation_rejects_duplicate_completion_and_impossible_order(
    tmp_path: Path,
) -> None:
    from _phase_evidence import PhaseEvidence

    for duplicate in (False, True):
        path = tmp_path / f"phase-{duplicate}.jsonl"
        evidence = PhaseEvidence(path, clock=lambda: 100.0)
        request = object()
        evidence.emit(
            request, "navigation.source", "success", source_dm_count=1, at=100.8
        )
        evidence.emit(
            request,
            "navigation.applied",
            "success",
            rendered_dm_count=1,
            at=101.0 if duplicate else 100.2,
        )
        if duplicate:
            evidence.emit(
                request, "navigation.source", "success", source_dm_count=1, at=100.9
            )
        evidence.close(test_kind="navigation")
        records = [json.loads(line) for line in path.read_text().splitlines()]
        assert any(row["phase"] == "recorder.tripwire" for row in records)
        assert records[-1]["complete"] is False
        expected = (
            "recorder.duplicate_terminal" if duplicate else "recorder.phase_order"
        )
        assert expected in records[-1]["missing"]


@pytest.mark.parametrize(
    ("test_kind", "phase"),
    [
        ("navigation", "navigation.source"),
        ("navigation", "navigation.applied"),
        ("recovery", "confirmation.resolved"),
        ("recovery", "lease.acquired"),
        ("recovery", "lease.restored"),
        ("recovery", "lease.hold_returned"),
        ("recovery", "provider.injected"),
        ("recovery", "provider.consumed"),
        ("recovery", "resource.closed"),
        ("recovery", "attach.retired"),
    ],
)
@pytest.mark.parametrize(
    "second_outcome", ["success", "error", "cancelled", "declined", "superseded"]
)
def test_required_phase_rejects_conflicting_terminal_outcomes(
    tmp_path: Path, test_kind: str, phase: str, second_outcome: str
) -> None:
    from _phase_evidence import PhaseEvidence

    path = tmp_path / "phase.jsonl"
    evidence = PhaseEvidence(path)
    owner = object()
    evidence.emit(owner, phase, "success")
    evidence.emit(owner, phase, second_outcome)
    evidence.close(test_kind=test_kind)
    records = [json.loads(line) for line in path.read_text().splitlines()]
    assert any(row["phase"] == "recorder.tripwire" for row in records)
    assert "recorder.duplicate_terminal" in records[-1]["missing"]


def test_unrelated_background_outcomes_remain_diagnostics(
    tmp_path: Path,
) -> None:
    from _phase_evidence import PhaseEvidence

    path = tmp_path / "phase.jsonl"
    evidence = PhaseEvidence(path)
    request, background = object(), object()
    evidence.emit(request, "navigation.source", "success", source_dm_count=1)
    evidence.emit(request, "navigation.applied", "success", rendered_dm_count=1)
    evidence.emit(background, "worker.completed", "error")
    evidence.emit(background, "worker.completed", "cancelled")
    evidence.close(test_kind="navigation")
    records = [json.loads(line) for line in path.read_text().splitlines()]
    assert not any(row["phase"] == "recorder.tripwire" for row in records)
    assert records[-1]["complete"] is True


def test_windows_output_observer_preserves_query_policy_and_runs_after_owner(
    tmp_path: Path,
) -> None:
    from typing import Any

    import pytest
    from _phase_evidence import PhaseEvidence, _install_pty_handle

    path = tmp_path / "phase.jsonl"
    evidence = PhaseEvidence(path)
    evidence.register_marker("fixture-marker")
    calls: list[bool] = []

    class Handle:
        def inject(self, text: str) -> None:
            assert "fixture-marker" in text

        def _observe_output(self, data: bytes, *, answer_queries: bool = True) -> None:
            del data
            # Completion must not be claimed before the actual owner sees bytes.
            assert "provider.consumed" not in path.read_text()
            calls.append(answer_queries)

        def close(self) -> None:
            pass

    with pytest.MonkeyPatch.context() as patch:
        _install_pty_handle(patch, evidence, Handle, windows=True)
        handle: Any = Handle()
        handle.inject("first line\nfixture-marker\nlast line")
        handle._observe_output(
            b"\r\necho:first\r\nfixture-marker\r\nchat> ", answer_queries=False
        )
        handle.close()
        handle.close()
    evidence.close()
    records = [json.loads(line) for line in path.read_text().splitlines()]
    assert calls == [False]
    assert [row["phase"] for row in records].count("resource.closed") == 1
    assert [row["phase"] for row in records].count("provider.consumed") == 1
    assert "fixture-marker" not in path.read_text()


def test_late_future_completion_does_not_write_after_observer_disposal(
    tmp_path: Path,
) -> None:
    import pytest
    from _phase_evidence import PhaseEvidence, install_phase_observers

    from taut_tui.app import TautApp

    path = tmp_path / "phase.jsonl"
    evidence = PhaseEvidence(path)
    future: Future[None] = Future()
    with pytest.MonkeyPatch.context() as patch:
        install_phase_observers(patch, evidence)
        app = TautApp(db_path=None, as_name=None, continuity_token=None)
        app._watch_future(future, lambda _future: None)
        evidence.close()
        before = path.read_bytes()
        future.set_result(None)
        assert future.result() is None
        assert path.read_bytes() == before


def test_opt_in_fixture_undoes_test_patches_without_leaking_closed_observers(
    tmp_path: Path,
) -> None:
    import os
    import subprocess
    import sys

    tests_directory = Path(__file__).resolve().parent
    (tmp_path / "conftest.py").write_text(
        (tests_directory / "conftest.py").read_text(), encoding="utf-8"
    )
    (tmp_path / "test_cleanup.py").write_text(
        "from taut_tui.app import TautApp\n"
        "ORIGINAL = TautApp._watch_future\n"
        "def test_first(monkeypatch):\n"
        "    monkeypatch.setattr(TautApp, '_watch_future', lambda *args: None)\n"
        "def test_next():\n"
        "    assert TautApp._watch_future.__wrapped__ is ORIGINAL\n",
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["TAUT_TUI_PHASE_DIR"] = str(tmp_path / "phases")
    env["PYTHONPATH"] = os.pathsep.join(
        (str(tests_directory), str(tests_directory.parents[2]))
    )
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", str(tmp_path / "test_cleanup.py")],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
