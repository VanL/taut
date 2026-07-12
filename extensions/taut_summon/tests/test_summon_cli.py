"""CLI surface tests for the taut-summon entry points.

Contract under test: docs/specs/04-summon.md [SUM-3] (argument shape and
name/provider resolution up to the driver hand-off), [SUM-9] control-client
behavior, and the core exit-code classes ([TAUT-8.1]: usage errors exit 1;
the nothing-summoned class exits 2). Driver behavior itself is covered by
``test_driver.py``.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import cast

import pytest
import taut_summon.cli as cli_module
from simplebroker import Queue
from taut_summon._state import (
    SUMMON_SCHEMA_VERSION,
    SUMMON_SCHEMA_VERSION_KEY,
    capture_driver_evidence,
    ensure_summon_schema,
    record_session,
    release_evidence_confirmed,
)
from taut_summon.cli import build_parser, run_request

from taut import TautClient

SummonCliRunner = Callable[..., tuple[int, str, str]]
pytestmark = pytest.mark.sqlite_only


@pytest.mark.parametrize(
    ("row", "expected"),
    (
        (None, True),
        ({"driver_pid": None, "driver_start_time": None}, True),
        ({"driver_pid": None, "driver_start_time": "partial"}, False),
        ({"driver_pid": 123, "driver_start_time": None}, False),
        ({"driver_pid": 123, "driver_start_time": "claimed"}, False),
        ({"driver_pid": 456, "driver_start_time": "replacement"}, True),
    ),
)
def test_stop_release_confirmation_uses_complete_requested_evidence(
    row: dict[str, int | str | None] | None,
    expected: bool,
) -> None:
    assert (
        release_evidence_confirmed(
            cast(
                "tuple[int | None, str | None]",
                (None, None)
                if row is None
                else (row["driver_pid"], row["driver_start_time"]),
            ),
            (123, "claimed"),
        )
        is expected
    )


@pytest.mark.parametrize(
    ("reply", "expected_error"),
    (
        (
            {
                "command": "STOP",
                "status": "error",
                "error": "driver slot release could not be confirmed",
            },
            "driver slot release could not be confirmed",
        ),
        (None, "did not acknowledge STOP"),
    ),
)
def test_stop_requires_ack_before_a_cleared_row_can_be_success(
    reply: dict[str, str] | None,
    expected_error: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    class FakeMember:
        member_id = "m_reviewer"
        name = "reviewer"

    class FakeClient:
        def queue(self, _name: str) -> object:
            return object()

        def close(self) -> None:
            pass

    class ErrorControl:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        def request(self, command: str, *, timeout: float) -> dict[str, str] | None:
            assert command == "STOP"
            assert timeout > 0
            return reply

        def close(self) -> None:
            pass

    pid, start = capture_driver_evidence(os.getpid())
    row = {"driver_pid": pid, "driver_start_time": start}
    confirm_calls: list[bool] = []

    def confirm_released(*_args: object, **_kwargs: object) -> bool:
        confirm_calls.append(True)
        return True

    monkeypatch.setattr(cli_module, "_open_client", lambda _args: FakeClient())
    monkeypatch.setattr(cli_module, "_resolve_member", lambda *_args: FakeMember())
    monkeypatch.setattr(cli_module, "_resolve_member_session", lambda *_args: row)
    monkeypatch.setattr(cli_module, "ControlClient", ErrorControl)
    monkeypatch.setattr(
        cli_module,
        "_confirm_released",
        confirm_released,
    )
    args = build_parser().parse_args(["stop", "reviewer"])

    rc = cli_module._cmd_stop(args)  # noqa: SLF001

    captured = capsys.readouterr()
    assert rc == 1
    assert captured.out == ""
    assert expected_error in captured.err
    assert confirm_calls == []


@pytest.mark.parametrize("command", (("status",), ("stop", "reviewer")))
def test_cli_incompatible_summon_schema_is_fatal(
    command: tuple[str, ...],
    run_summon_cli: SummonCliRunner,
    tmp_path: Path,
) -> None:
    db = tmp_path / ".taut.db"
    TautClient.init(db_path=db)
    client = TautClient(db_path=db, as_name="reviewer")
    try:
        client.join("general")
    finally:
        client.close()
    queue = Queue("taut.summon_state", db_path=str(db))
    try:
        ensure_summon_schema(queue)
        with queue.sidecar(transaction=True) as session:
            session.run(
                "UPDATE taut_meta SET value = ? WHERE key = ?",
                (str(SUMMON_SCHEMA_VERSION + 1), SUMMON_SCHEMA_VERSION_KEY),
            )
    finally:
        queue.close()

    rc, out, err = run_summon_cli(*command, "--db", db, cwd=tmp_path)

    assert rc == 1
    assert out == ""
    assert "summon schema version" in err
    assert "Traceback (most recent call last)" not in err
    assert len(err.splitlines()) == 1


def test_run_defaults_thread_to_general() -> None:
    request = run_request(build_parser().parse_args(["run", "claude"]))

    assert request.name == "claude"
    assert request.threads == ("general",)


def test_run_captures_positional_threads_in_order() -> None:
    request = run_request(build_parser().parse_args(["run", "claude", "dev", "ops"]))

    assert request.threads == ("dev", "ops")


def test_run_provider_defaults_to_name() -> None:
    request = run_request(build_parser().parse_args(["run", "claude"]))

    assert request.provider_flag is None


def test_run_provider_flag_wins_over_name() -> None:
    request = run_request(
        build_parser().parse_args(["run", "reviewer", "--provider", "claude", "dev"])
    )

    assert request.name == "reviewer"
    assert request.provider_flag == "claude"
    assert request.threads == ("dev",)


def test_run_double_dash_preserves_option_shaped_name() -> None:
    request = run_request(build_parser().parse_args(["run", "--", "-q"]))

    assert request.name == "-q"
    assert request.provider_flag is None
    assert request.threads == ("general",)


def test_run_double_dash_preserves_option_shaped_thread_tail() -> None:
    request = run_request(
        build_parser().parse_args(
            ["run", "reviewer", "--provider", "claude", "--", "--as"]
        )
    )

    assert request.name == "reviewer"
    assert request.provider_flag == "claude"
    assert request.threads == ("--as",)


def test_run_parses_placeholder_flags() -> None:
    request = run_request(
        build_parser().parse_args(
            [
                "run",
                "claude",
                "--terminal",
                "--persona",
                "standing reviewer",
                "--system-prompt-file",
                "prompt.md",
                "--rate-limit",
                "30",
                "--db",
                "x.taut.db",
            ]
        )
    )

    assert request.terminal is True
    assert request.persona == "standing reviewer"
    assert request.system_prompt_file == "prompt.md"
    assert request.rate_limit == 30
    assert request.db_path == "x.taut.db"


def test_cli_no_arguments_prints_help_and_exits_1(
    run_summon_cli: SummonCliRunner, tmp_path: Path
) -> None:
    rc, out, err = run_summon_cli(cwd=tmp_path)

    assert rc == 1
    assert out == ""
    folded = " ".join(err.split())
    assert "usage:" in folded
    assert "0 success" in folded
    assert "2 nothing summoned" in folded


def test_cli_help_exits_0_on_stdout(
    run_summon_cli: SummonCliRunner, tmp_path: Path
) -> None:
    rc, out, err = run_summon_cli("--help", cwd=tmp_path)

    assert rc == 0
    assert err == ""
    assert "usage:" in out


def test_every_summon_parser_action_has_useful_help() -> None:
    root = build_parser()
    pending = [root]
    seen: set[int] = set()
    missing: list[str] = []

    while pending:
        parser = pending.pop()
        if id(parser) in seen:
            continue
        seen.add(id(parser))
        if not parser.description or not parser.description.strip():
            missing.append(f"{parser.prog}: parser description")
        for action in parser._actions:
            if action.dest != "help" and (
                action.help == argparse.SUPPRESS
                or not isinstance(action.help, str)
                or not action.help.strip()
            ):
                missing.append(f"{parser.prog}: {action.dest}")
            if isinstance(action, argparse._SubParsersAction):
                pending.extend(action.choices.values())
                for choice in action._choices_actions:
                    if (
                        choice.help == argparse.SUPPRESS
                        or not choice.help
                        or not choice.help.strip()
                    ):
                        missing.append(f"{parser.prog}: subcommand {choice.dest}")

    assert missing == []


@pytest.mark.parametrize(
    ("args", "phrases"),
    [
        (
            ("--help",),
            ("0 success", "1 error", "2 nothing summoned"),
        ),
        (
            ("run", "--help"),
            (
                "default: general",
                "--provider",
                "current directory",
                "ancestor",
                "--attach",
                "--detach",
            ),
        ),
        (
            ("stop", "--help"),
            ("STOP", "current directory", "ancestor"),
        ),
        (
            ("status", "--help"),
            ("live sessions", "current directory", "ancestor"),
        ),
    ],
)
def test_summon_help_exposes_load_bearing_contracts(
    run_summon_cli: SummonCliRunner,
    tmp_path: Path,
    args: tuple[str, ...],
    phrases: tuple[str, ...],
) -> None:
    rc, out, err = run_summon_cli(*args, cwd=tmp_path)

    assert rc == 0, err
    folded = " ".join(out.lower().split())
    for phrase in phrases:
        assert phrase.lower() in folded


def test_cli_unknown_subcommand_exits_1(
    run_summon_cli: SummonCliRunner, tmp_path: Path
) -> None:
    rc, out, err = run_summon_cli("bogus", cwd=tmp_path)

    assert rc == 1
    assert "usage:" in err
    assert out == ""


def test_cli_run_missing_name_is_usage_error_exit_1(
    run_summon_cli: SummonCliRunner, tmp_path: Path
) -> None:
    rc, out, err = run_summon_cli("run", cwd=tmp_path)

    assert rc == 1
    assert "usage:" in err
    assert out == ""


def test_cli_run_unknown_flag_is_usage_error_exit_1(
    run_summon_cli: SummonCliRunner, tmp_path: Path
) -> None:
    rc, out, err = run_summon_cli("run", "claude", "--bogus", cwd=tmp_path)

    assert rc == 1
    assert "usage:" in err
    assert out == ""


def test_cli_run_reports_missing_adapter_exit_1(
    run_summon_cli: SummonCliRunner, tmp_path: Path
) -> None:
    # [SUM-3] resolution step 4: an unknown provider is an error naming
    # the known adapters (registry lookup, not a placeholder).
    rc, out, err = run_summon_cli("run", "zz-unknown", cwd=tmp_path)

    assert rc == 1
    assert "no adapter named 'zz-unknown'" in err
    assert "known adapters:" in err
    for name in ("claude", "claude-stream", "coder", "pty", "scripted"):
        assert name in err
    assert out == ""


def test_cli_run_known_adapter_without_database_exits_1(
    run_summon_cli: SummonCliRunner, tmp_path: Path
) -> None:
    # The registry resolves 'scripted' ([SUM-7.2]); with no database the
    # driver cannot bootstrap and the diagnostic names the real problem.
    rc, out, err = run_summon_cli("run", "scripted", cwd=tmp_path)

    assert rc == 1
    assert "No taut database found" in err
    assert out == ""


def test_cli_run_known_adapter_echoes_db(
    run_summon_cli: SummonCliRunner, tmp_path: Path
) -> None:
    # The parsed --db still echoes on the error path so a dropped flag is
    # observable through the delegation seam.
    db = str(tmp_path / "x.taut.db")
    rc, _out, err = run_summon_cli("run", "scripted", "--db", db, cwd=tmp_path)

    assert rc == 1
    assert "No taut database found" in err
    assert f"db: {db}" in err


def test_cli_run_resolves_provider_flag_before_name(
    run_summon_cli: SummonCliRunner, tmp_path: Path
) -> None:
    # An unknown --provider errors before any database work, proving the
    # flag wins over the positional name ([SUM-3] step 1).
    rc, _out, err = run_summon_cli(
        "run", "reviewer", "--provider", "zz-unknown", "dev", cwd=tmp_path
    )

    assert rc == 1
    assert "no adapter named 'zz-unknown'" in err


def test_cli_run_double_dash_makes_tail_positional(
    run_summon_cli: SummonCliRunner, tmp_path: Path
) -> None:
    rc, _out, err = run_summon_cli("run", "--", "-q", cwd=tmp_path)

    assert rc == 1
    assert "no adapter named '-q'" in err


def test_cli_stop_reports_nothing_summoned_exit_2(
    run_summon_cli: SummonCliRunner, tmp_path: Path
) -> None:
    rc, out, err = run_summon_cli("stop", "claude", cwd=tmp_path)

    assert rc == 2
    assert "nothing summoned as 'claude'" in err
    assert out == ""


def test_cli_stop_dead_driver_returns_exit_2_without_control_wait(
    run_summon_cli: SummonCliRunner, tmp_path: Path
) -> None:
    db = tmp_path / ".taut.db"
    TautClient.init(db_path=db)
    client = TautClient(db_path=db, as_name="reviewer")
    try:
        client.join("general")
        member = client.last_created_member
        assert member is not None and member.token is not None
    finally:
        client.close()
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        pid, start = capture_driver_evidence(child.pid)
    finally:
        child.kill()
        child.wait()
    queue = Queue("taut.summon_state", db_path=str(db))
    try:
        ensure_summon_schema(queue)
        record_session(
            queue,
            member_id=member.member_id,
            token=member.token,
            provider="scripted",
            provider_session_id=None,
            driver_pid=pid,
            driver_start_time=start,
            updated_ts=queue.generate_timestamp(),
        )
    finally:
        queue.close()

    rc, out, err = run_summon_cli("stop", "reviewer", "--db", db, cwd=tmp_path)

    assert rc == 2
    assert out == ""
    assert "nothing summoned as 'reviewer'" in err


def test_cli_status_bare_reports_nothing_summoned_exit_2(
    run_summon_cli: SummonCliRunner, tmp_path: Path
) -> None:
    rc, out, err = run_summon_cli("status", cwd=tmp_path)

    assert rc == 2
    assert "nothing summoned" in err
    assert out == ""


def test_cli_status_bare_lists_live_sessions(
    run_summon_cli: SummonCliRunner, tmp_path: Path
) -> None:
    db = tmp_path / ".taut.db"
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
        pid, start = capture_driver_evidence(os.getpid())
        record_session(
            queue,
            member_id=member.member_id,
            token=member.token,
            provider="scripted",
            provider_session_id="sess-live",
            driver_pid=pid,
            driver_start_time=start,
            updated_ts=queue.generate_timestamp(),
        )
    finally:
        queue.close()

    rc, out, err = run_summon_cli("status", "--db", db, cwd=tmp_path)

    assert rc == 0
    assert out == "reviewer\tscripted\tlive\tsession=sess-live"
    assert err == ""


def test_cli_status_bare_reports_malformed_ledger_without_traceback(
    run_summon_cli: SummonCliRunner, tmp_path: Path
) -> None:
    db = tmp_path / ".taut.db"
    TautClient.init(db_path=db)
    queue = Queue("taut.summon_state", db_path=str(db))
    try:
        ensure_summon_schema(queue)
        with queue.sidecar(transaction=True) as session:
            session.run(
                """
                INSERT INTO taut_summon_sessions (
                    member_id, token, provider, provider_session_id,
                    driver_pid, driver_start_time, wired, updated_ts
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                ("m_bad", "tok", "scripted", None, None, None, 2, 1),
            )
    finally:
        queue.close()

    rc, out, err = run_summon_cli("status", "--db", db, cwd=tmp_path)

    assert rc == 1
    assert out == ""
    assert "malformed summon session row" in err
    assert "Traceback (most recent call last)" not in err
    assert len(err.splitlines()) == 1


def test_cli_status_with_name_reports_nothing_summoned_exit_2(
    run_summon_cli: SummonCliRunner, tmp_path: Path
) -> None:
    rc, out, err = run_summon_cli("status", "claude", cwd=tmp_path)

    assert rc == 2
    assert "nothing summoned as 'claude'" in err
    assert out == ""
