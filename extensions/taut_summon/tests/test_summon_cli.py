"""CLI surface tests for the taut-summon entry points.

Contract under test: docs/specs/04-summon.md [SUM-3] (argument shape and
name/provider resolution up to the driver hand-off), [SUM-9] control-client
behavior, and the core exit-code classes ([TAUT-8.1]: usage errors exit 1;
the nothing-summoned class exits 2). Driver behavior itself is covered by
``test_driver.py``.
"""

from __future__ import annotations

import argparse
import logging
import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import cast

import pytest
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
from taut_summon.models import SummonedMember, SummonStatus

from taut import TautClient

SummonCliRunner = Callable[..., tuple[int, str, str]]
pytestmark = pytest.mark.sqlite_only


def _assert_only_structural_newlines(text: str) -> None:
    assert all(
        character == "\n"
        or not (ord(character) < 0x20 or 0x7F <= ord(character) <= 0x9F)
        for character in text
    )


def test_standalone_human_records_escape_all_dynamic_status_fields(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from taut_summon.cli import _print_live_member, _print_status

    probe = "value\x1b]52;c;Y2xpcGJvYXJk\x07\x9b\r\b\t\nrow"
    escaped = r"value\x1b]52;c;Y2xpcGJvYXJk\a\x9b\r\b\t\nrow"
    _print_live_member(
        SummonedMember(
            member_id="m_" + "a" * 26,
            name=probe,
            provider=probe,
            provider_session_id=probe,
        )
    )
    _print_status(
        SummonStatus(
            member_id="m_" + "a" * 26,
            name=probe,
            driver=probe,
            provider=probe,
            provider_session_id=probe,
            thread_count=1,
            cursor_lag={probe: 2},
            details={probe: probe},
        )
    )

    output = capsys.readouterr().out
    assert output.count(escaped) >= 9
    _assert_only_structural_newlines(output)


def test_standalone_human_records_inherit_project_terminal_policy(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from taut_summon.cli import _print_live_member

    (tmp_path / ".taut.toml").write_text(
        "\n".join(
            (
                "version = 1",
                'backend = "sqlite"',
                'target = ".taut.db"',
                "",
                "[terminal_text]",
                'escape_patterns = ["MARK"]',
                "",
            )
        ),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    _print_live_member(
        SummonedMember(
            member_id="m_" + "a" * 26,
            name="MARK",
            provider="provider",
            provider_session_id=None,
        )
    )

    assert capsys.readouterr().out.startswith(r"\x4d\x41\x52\x4b\t")


def test_standalone_argparse_and_operation_errors_escape_caller_text(
    run_summon_cli: SummonCliRunner,
    tmp_path: Path,
) -> None:
    probe = "bad\x1b]0;title\x07\x9b\r\b\t\nrow"
    escaped = r"bad\x1b]0;title\a\x9b\r\b\t\nrow"

    rc, out, err = run_summon_cli("run", "reviewer", f"--{probe}", cwd=tmp_path)
    assert rc == 1
    assert out == ""
    assert escaped in err
    _assert_only_structural_newlines(err)

    controlled_db = tmp_path / "db\x1b]52;c;Y2xpcGJvYXJk\x07.sqlite"
    rc, out, err = run_summon_cli(
        "run",
        probe,
        "--db",
        controlled_db,
        cwd=tmp_path,
    )
    assert rc == 1
    assert out == ""
    assert escaped in err
    assert r"db\x1b]52;c;Y2xpcGJvYXJk\a.sqlite" in err
    _assert_only_structural_newlines(err)


def test_summon_logging_formatter_escapes_messages_and_bootstraps_safely(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from io import StringIO

    from taut_summon.commands.summon import _TerminalSafeFormatter

    import taut.terminal as terminal

    output = StringIO()
    handler = logging.StreamHandler(output)
    handler.setFormatter(_TerminalSafeFormatter("%(name)s %(levelname)s %(message)s"))
    logger = logging.Logger("summon-test")
    logger.addHandler(handler)
    logger.propagate = False
    logger.warning("assistant %s", "text\x1b]52;c;Y2xpcGJvYXJk\x07\nrow")
    assert output.getvalue() == (
        r"summon-test WARNING assistant text\x1b]52;c;Y2xpcGJvYXJk\a\nrow"
        "\n"
    )

    (tmp_path / "defaults.toml").write_text("terminal_text = [", encoding="utf-8")
    monkeypatch.setattr(terminal.resources, "files", lambda _package: tmp_path)
    terminal._default_pattern_sources.cache_clear()
    terminal._compiled_default_patterns.cache_clear()
    output.seek(0)
    output.truncate(0)
    previous = logging.raiseExceptions
    logging.raiseExceptions = True
    try:
        logger.warning("unrenderable")
    finally:
        logging.raiseExceptions = previous
        terminal._default_pattern_sources.cache_clear()
        terminal._compiled_default_patterns.cache_clear()

    assert output.getvalue() == "terminal output policy is unavailable\n"
    assert "Logging error" not in output.getvalue()
    assert "Traceback" not in output.getvalue()


def test_native_summon_command_owns_safe_logging_without_replacing_host_handlers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from io import StringIO

    import taut_summon.controller as controller_module
    from taut_summon.commands.summon import SummonCommand

    from taut.commands import CommandContext

    probe = "driver\x1b]52;c;Y2xpcGJvYXJk\x07\nrow"
    escaped = r"driver\x1b]52;c;Y2xpcGJvYXJk\a\nrow"
    host_output = StringIO()
    host_handler = logging.StreamHandler(host_output)
    command_output = StringIO()
    root_logger = logging.getLogger()
    summon_logger = logging.getLogger("taut_summon")
    root_state = (list(root_logger.handlers), root_logger.level)
    summon_state = (
        list(summon_logger.handlers),
        summon_logger.level,
        summon_logger.propagate,
    )

    class Controller:
        def __init__(self, *, db_path: str | None) -> None:
            assert db_path == "project.db"

        def run_foreground(self, request: object, interaction: object) -> None:
            assert request is not None
            assert interaction is not None
            logging.getLogger("taut_summon.driver").warning("%s", probe)

    monkeypatch.setattr(controller_module, "SummonController", Controller)
    try:
        root_logger.handlers[:] = [host_handler]
        root_logger.setLevel(logging.WARNING)
        summon_logger.handlers.clear()
        summon_logger.setLevel(logging.NOTSET)
        summon_logger.propagate = True
        context = CommandContext(
            db_path="project.db",
            as_name=None,
            auth_token=None,
            json=False,
            timestamps=False,
            quiet=False,
            stdin=StringIO(),
            stdout=StringIO(),
            stderr=command_output,
        )
        args = argparse.Namespace(
            name="reviewer",
            threads=["general"],
            terminal=False,
            persona=None,
            system_prompt_file=None,
            rate_limit=None,
            attach=False,
            detach=True,
            provider=None,
            takeover=False,
        )

        assert SummonCommand().run(context, args) == 0
    finally:
        root_logger.handlers[:] = root_state[0]
        root_logger.setLevel(root_state[1])
        summon_logger.handlers[:] = summon_state[0]
        summon_logger.setLevel(summon_state[1])
        summon_logger.propagate = summon_state[2]

    assert command_output.getvalue().endswith(f"WARNING {escaped}\n")
    assert host_output.getvalue() == ""


def test_standalone_policy_failure_is_one_fixed_exit_one_diagnostic(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from taut_summon.cli import main

    import taut.terminal as terminal

    (tmp_path / "defaults.toml").write_text("terminal_text = [", encoding="utf-8")
    monkeypatch.setattr(terminal.resources, "files", lambda _package: tmp_path)
    terminal._default_pattern_sources.cache_clear()
    terminal._compiled_default_patterns.cache_clear()
    try:
        result = main(["run", "reviewer", "--bad"])
    finally:
        terminal._default_pattern_sources.cache_clear()
        terminal._compiled_default_patterns.cache_clear()

    captured = capsys.readouterr()
    assert result == 1
    assert captured.out == ""
    assert captured.err.endswith("terminal output policy is unavailable\n")
    assert captured.err.count("terminal output policy is unavailable") == 1
    assert "Traceback" not in captured.err


def test_standalone_project_policy_failure_preflights_before_controller(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import taut_summon.controller as controller_module
    from taut_summon.cli import main

    (tmp_path / ".taut.toml").write_text(
        "\n".join(
            (
                "version = 1",
                'backend = "sqlite"',
                'target = ".taut.db"',
                "",
                "[terminal_text]",
                'escape_patterns = ["["]',
                "",
            )
        ),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        controller_module,
        "SummonController",
        lambda **_kwargs: pytest.fail("controller constructed before preflight"),
    )

    result = main(["status"])

    captured = capsys.readouterr()
    assert result == 1
    assert captured.out == ""
    assert captured.err == "terminal output policy is unavailable\n"
    assert "Traceback" not in captured.err


def test_native_command_records_escape_stop_results_and_fault_diagnostics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from io import StringIO

    import taut_summon.controller as controller_module
    from taut_summon.commands import command_error
    from taut_summon.commands.dismiss import DismissCommand
    from taut_summon.models import StopResult, SummonOperationError

    from taut.commands import CommandContext

    probe = "value\x1b]52;c;Y2xpcGJvYXJk\x07\x9b\r\b\t\nrow"
    escaped = r"value\x1b]52;c;Y2xpcGJvYXJk\a\x9b\r\b\t\nrow"

    class Controller:
        def __init__(self, *, db_path: str | None) -> None:
            assert db_path == probe

        def stop(self, name: str) -> StopResult:
            assert name == "requested"
            return StopResult(member_id="m_" + "a" * 26, name=probe)

    monkeypatch.setattr(controller_module, "SummonController", Controller)
    stdout = StringIO()
    stderr = StringIO()
    context = CommandContext(
        db_path=probe,
        as_name=None,
        auth_token=None,
        json=False,
        timestamps=False,
        quiet=False,
        stdin=StringIO(),
        stdout=stdout,
        stderr=stderr,
    )

    assert DismissCommand().run(context, argparse.Namespace(name="requested")) == 0
    assert stdout.getvalue().count(escaped) == 2
    _assert_only_structural_newlines(stdout.getvalue())

    monkeypatch.setenv("TAUT_SUMMON_STATUS_FAULT_PLANE", "1")
    error = command_error(
        SummonOperationError(probe, fault_plane="control_read"),
        context,
        exit_code=1,
    )
    assert str(error).count(probe) == 2
    assert escaped in stderr.getvalue()
    _assert_only_structural_newlines(stderr.getvalue())


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


def test_status_fault_plane_diagnostic_classifies_real_resolution_failure(
    run_summon_cli: SummonCliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
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
    monkeypatch.setenv("TAUT_SUMMON_STATUS_FAULT_PLANE", "1")

    rc, out, err = run_summon_cli("status", "reviewer", "--db", db, cwd=tmp_path)

    assert rc == 1
    assert out == ""
    assert "status_fault_plane=resolve_session" in err
    assert "SummonOperationError" in err
    assert "summon schema version" in err
    assert "Traceback" not in err
    assert len(err.splitlines()) == 2


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
    parsed = build_parser().parse_args(
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
    request = run_request(parsed)

    assert request.terminal is True
    assert request.persona == "standing reviewer"
    assert request.system_prompt_file == "prompt.md"
    assert request.rate_limit == 30
    assert parsed.db_path == "x.taut.db"


def test_standalone_run_and_stop_select_shared_command_factories() -> None:
    from taut_summon.commands.dismiss import create_command as create_dismiss_command
    from taut_summon.commands.summon import create_command as create_summon_command

    run_args = build_parser().parse_args(["run", "scripted", "--detach"])
    stop_args = build_parser().parse_args(["stop", "scripted"])

    assert run_args.command_factory is create_summon_command
    assert stop_args.command_factory is create_dismiss_command


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


def test_cli_rejects_attach_and_detach_together_as_usage_error(
    run_summon_cli: SummonCliRunner, tmp_path: Path
) -> None:
    rc, out, err = run_summon_cli(
        "run",
        "reviewer",
        "--provider",
        "scripted",
        "--attach",
        "--detach",
        cwd=tmp_path,
    )

    assert rc == 1
    assert out == ""
    assert "usage:" in err
    assert "not allowed with argument --attach" in err
    assert "Traceback" not in err


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
    assert out == r"reviewer\tscripted\tlive\tsession=sess-live"
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
