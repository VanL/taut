"""Temporary hosted-Windows driver for exact MCP-body diagnostics."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time

import _windows_mcp_diagnostic as diagnostic
import psutil
import pytest


def _iterations(name: str, default: int) -> int:
    return int(os.environ.get(name, default))


def _print_reports(diagnostic_name: str, reports: list[dict[str, object]]) -> None:
    """Keep every GitHub log record below its single-line truncation boundary."""

    for report in reports:
        bodies = report.get("bodies")
        if not isinstance(bodies, list):
            raise TypeError(f"diagnostic report bodies are not a list: {report!r}")
        summary = {key: value for key, value in report.items() if key != "bodies"}
        print(
            json.dumps(
                {"diagnostic": diagnostic_name, "summary": summary}, sort_keys=True
            )
        )
        for body in bodies:
            print(
                json.dumps(
                    {"body_result": body, "diagnostic": diagnostic_name},
                    sort_keys=True,
                )
            )


def test_exact_mcp_body_budget_lane() -> None:
    reports = diagnostic.run_diagnostic(
        lane="budget",
        iterations=_iterations("TAUT_MCP_DIAGNOSTIC_BUDGET_ITERATIONS", 24),
    )
    _print_reports("budget", reports)


def test_exact_mcp_body_phase_lane() -> None:
    reports = diagnostic.run_diagnostic(
        lane="phase",
        iterations=_iterations("TAUT_MCP_DIAGNOSTIC_PHASE_ITERATIONS", 2),
    )
    _print_reports("phase", reports)


def _isolated_sleeper() -> subprocess.Popen[str]:
    command = [sys.executable, "-c", "import time; time.sleep(300)"]
    if os.name == "nt":
        return subprocess.Popen(
            command,
            text=True,
            creationflags=int(getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)),
        )
    return subprocess.Popen(command, text=True, start_new_session=True)


def _protocol_state() -> diagnostic._ProtocolState:
    return diagnostic._ProtocolState(
        run_id="protocol-test",
        lane="budget",
        body="tools",
        iterations=1,
    )


def _terminal_record(
    *,
    body_id: str,
    iteration: int,
    local_phases: list[dict[str, object]],
    final: bool,
) -> dict[str, object]:
    return {
        "event": "terminal_complete",
        "operation_id": f"terminal-{body_id}",
        "body_id": body_id,
        "iteration": iteration,
        "local_phases": local_phases,
        "final": final,
    }


def _active_observation(
    *, body_id: str, iteration: int, parent_entered: float, child_entered: float
) -> diagnostic._Observation:
    return diagnostic._Observation(
        body_id=body_id,
        iteration=iteration,
        parent_entered=parent_entered,
        child_entered=child_entered,
    )


def test_report_output_is_one_bounded_record_per_body(
    capsys: pytest.CaptureFixture[str],
) -> None:
    report: dict[str, object] = {
        "aggregate_progress_evidence": False,
        "body": "tools",
        "bodies": [
            {"duration_seconds": 1.0, "iteration": 0},
            {"duration_seconds": 2.0, "iteration": 1},
        ],
        "iterations": 2,
        "lane": "budget",
    }

    _print_reports("budget", [report])

    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 3
    assert json.loads(lines[0])["summary"]["iterations"] == 2
    assert [json.loads(line)["body_result"]["iteration"] for line in lines[1:]] == [
        0,
        1,
    ]


def test_aggregate_pressure_predicate_is_per_body_and_budget_only() -> None:
    """Only one post-threshold progressing budget body can authorize the branch."""

    now = time.monotonic()

    batch = diagnostic._ProtocolState(
        run_id="batch",
        lane="budget",
        body="tools",
        iterations=2,
        saw_ready=True,
    )
    batch.active = _active_observation(
        body_id="batch-0",
        iteration=0,
        parent_entered=now,
        child_entered=100.0,
    )
    diagnostic._handle_terminal(
        _terminal_record(
            body_id="batch-0",
            iteration=0,
            local_phases=[
                {
                    "label": "tools.reactor.read",
                    "entered": 100.0,
                    "finished": 108.0,
                    "outcome": "returned",
                }
            ],
            final=False,
        ),
        batch,
        now + 8.0,
    )
    batch.active = _active_observation(
        body_id="batch-1",
        iteration=1,
        parent_entered=now + 8.0,
        child_entered=200.0,
    )
    diagnostic._handle_terminal(
        _terminal_record(
            body_id="batch-1",
            iteration=1,
            local_phases=[
                {
                    "label": "tools.reactor.read",
                    "entered": 200.0,
                    "finished": 208.0,
                    "outcome": "returned",
                }
            ],
            final=True,
        ),
        batch,
        now + 16.0,
    )
    assert diagnostic._aggregate_progress_evidence(batch.reports) is False

    stopped = _protocol_state()
    stopped.saw_ready = True
    stopped.active = _active_observation(
        body_id="stopped",
        iteration=0,
        parent_entered=now - 16.0,
        child_entered=300.0,
    )
    diagnostic._handle_terminal(
        _terminal_record(
            body_id="stopped",
            iteration=0,
            local_phases=[
                {
                    "label": "tools.reactor.read",
                    "entered": 300.0,
                    "finished": 314.0,
                    "outcome": "returned",
                }
            ],
            final=True,
        ),
        stopped,
        now,
    )
    assert stopped.reports[0]["active_at_15_seconds"] is True
    assert stopped.reports[0]["post_observation_inner_progress"] is False
    assert diagnostic._aggregate_progress_evidence(stopped.reports) is False

    progressing = _protocol_state()
    progressing.saw_ready = True
    progressing.active = _active_observation(
        body_id="progressing",
        iteration=0,
        parent_entered=now - 16.0,
        child_entered=400.0,
    )
    diagnostic._handle_terminal(
        _terminal_record(
            body_id="progressing",
            iteration=0,
            local_phases=[
                {
                    "label": "tools.reactor.read",
                    "entered": 414.0,
                    "finished": 416.0,
                    "outcome": "returned",
                }
            ],
            final=True,
        ),
        progressing,
        now,
    )
    assert progressing.reports[0]["active_at_15_seconds"] is True
    assert progressing.reports[0]["post_observation_inner_progress"] is True
    assert diagnostic._aggregate_progress_evidence(progressing.reports) is True

    detailed = diagnostic._ProtocolState(
        run_id="phase",
        lane="phase",
        body="tools",
        iterations=1,
        saw_ready=True,
    )
    detailed.active = _active_observation(
        body_id="phase",
        iteration=0,
        parent_entered=now - 16.0,
        child_entered=500.0,
    )
    diagnostic._handle_terminal(
        _terminal_record(
            body_id="phase",
            iteration=0,
            local_phases=[],
            final=True,
        ),
        detailed,
        now,
    )
    assert detailed.reports[0]["active_at_15_seconds"] is True
    assert detailed.reports[0]["post_observation_inner_progress"] is False
    assert diagnostic._aggregate_progress_evidence(detailed.reports) is False


def test_diagnostic_protocol_failure_paths_and_tree_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Protocol faults fire, and both driver and tracked MCP trees are reaped."""

    state = _protocol_state()
    with pytest.raises(EOFError, match="EOF before final completion"):
        diagnostic._validate_record(diagnostic._EOF, state)

    unknown = {
        "protocol": diagnostic.PROTOCOL,
        "run_id": state.run_id,
        "lane": state.lane,
        "body": state.body,
        "body_id": "body-1",
        "iteration": 0,
        "operation_id": "operation-1",
        "sequence": 1,
        "event": "unknown_event",
    }
    with pytest.raises(AssertionError, match="unknown diagnostic event"):
        diagnostic._validate_record(json.dumps(unknown), state)

    state.saw_ready = True
    now = time.monotonic()
    state.active = diagnostic._Observation(
        body_id="body-1",
        iteration=0,
        parent_entered=now,
        child_entered=now,
    )
    with pytest.raises(AssertionError, match="diagnostic target failed"):
        diagnostic._handle_record(
            {
                "event": "terminal_error",
                "operation_id": "operation-2",
                "body_id": "body-1",
                "iteration": 0,
                "local_phases": [],
                "traceback": "sentinel traceback",
            },
            state,
            now,
        )

    driver = _isolated_sleeper()
    mcp_server = _isolated_sleeper()
    tracked = diagnostic._TrackedProcess(
        process_id=mcp_server.pid,
        create_time=psutil.Process(mcp_server.pid).create_time(),
    )
    cleanup_state = _protocol_state()
    diagnostic._record_process_control(
        {
            "process_control": "created",
            "mcp_process_id": tracked.process_id,
            "mcp_process_create_time": tracked.create_time,
        },
        cleanup_state,
    )
    try:
        with pytest.raises(AssertionError, match="missing-progress cap"):
            diagnostic._check_parent_deadlines(
                process=driver,
                state=cleanup_state,
                now=now,
                progress_deadline=now - 1,
                absolute_deadline=now + 100,
                absolute_cap=100,
            )
    finally:
        diagnostic._force_kill(driver, set(cleanup_state.tracked_mcp))
        driver.wait(timeout=10)
        mcp_server.wait(timeout=10)
    diagnostic._record_process_control(
        {
            "process_control": "stopped",
            "mcp_process_id": tracked.process_id,
            "mcp_process_create_time": tracked.create_time,
        },
        cleanup_state,
    )
    diagnostic._wait_reaped(set(cleanup_state.tracked_mcp))
    assert cleanup_state.stopped_mcp == {tracked}

    exited = subprocess.Popen(
        [sys.executable, "-c", "raise SystemExit(7)"],
        text=True,
    )
    assert exited.wait(timeout=10) == 7
    with pytest.raises(AssertionError, match="exited early with code 7"):
        diagnostic._check_parent_deadlines(
            process=exited,
            state=_protocol_state(),
            now=now,
            progress_deadline=now + 100,
            absolute_deadline=now + 100,
            absolute_cap=100,
        )

    exited_driver = subprocess.Popen(
        [sys.executable, "-c", "pass"],
        text=True,
    )
    assert exited_driver.wait(timeout=10) == 0
    tracked_server = _isolated_sleeper()
    tracked_server_identity = diagnostic._TrackedProcess(
        process_id=tracked_server.pid,
        create_time=psutil.Process(tracked_server.pid).create_time(),
    )
    taskkill_pids: list[int] = []

    def record_taskkill(
        command: list[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        taskkill_pids.append(int(command[2]))
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(diagnostic, "_is_windows", lambda: True)
    monkeypatch.setattr(diagnostic.subprocess, "run", record_taskkill)
    try:
        diagnostic._force_kill(exited_driver, {tracked_server_identity})
    finally:
        tracked_server.terminate()
        tracked_server.wait(timeout=10)
    assert exited_driver.pid not in taskkill_pids
    assert taskkill_pids == [tracked_server.pid]
