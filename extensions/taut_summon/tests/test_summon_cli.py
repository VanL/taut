"""CLI surface tests for the taut-summon entry points.

Contract under test: docs/specs/04-summon.md [SUM-3] (argument shape and
name/provider resolution up to the driver hand-off) and the core
exit-code classes ([TAUT-8.1]: usage errors exit 1; the nothing-summoned
class exits 2). Driver behavior itself is covered by ``test_driver.py``;
``stop``/``status`` remain thin placeholders until the control plane
slice.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from taut_summon.cli import build_parser, run_request

SummonCliRunner = Callable[..., tuple[int, str, str]]


def test_run_defaults_thread_to_general() -> None:
    request = run_request(build_parser().parse_args(["run", "claude"]))

    assert request.name == "claude"
    assert request.threads == ("general",)


def test_run_captures_positional_threads_in_order() -> None:
    request = run_request(build_parser().parse_args(["run", "claude", "dev", "ops"]))

    assert request.threads == ("dev", "ops")


def test_run_provider_defaults_to_name() -> None:
    request = run_request(build_parser().parse_args(["run", "claude"]))

    assert request.provider == "claude"


def test_run_provider_flag_wins_over_name() -> None:
    request = run_request(
        build_parser().parse_args(["run", "reviewer", "--provider", "claude", "dev"])
    )

    assert request.name == "reviewer"
    assert request.provider == "claude"
    assert request.threads == ("dev",)


def test_run_double_dash_preserves_option_shaped_name() -> None:
    request = run_request(build_parser().parse_args(["run", "--", "-q"]))

    assert request.name == "-q"
    assert request.provider == "-q"
    assert request.threads == ("general",)


def test_run_double_dash_preserves_option_shaped_thread_tail() -> None:
    request = run_request(
        build_parser().parse_args(
            ["run", "reviewer", "--provider", "claude", "--", "--as"]
        )
    )

    assert request.name == "reviewer"
    assert request.provider == "claude"
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
    rc, out, _err = run_summon_cli(cwd=tmp_path)

    assert rc == 1
    assert "usage:" in out


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


def test_cli_status_bare_reports_nothing_summoned_exit_2(
    run_summon_cli: SummonCliRunner, tmp_path: Path
) -> None:
    rc, out, err = run_summon_cli("status", cwd=tmp_path)

    assert rc == 2
    assert "nothing summoned" in err
    assert out == ""


def test_cli_status_with_name_reports_nothing_summoned_exit_2(
    run_summon_cli: SummonCliRunner, tmp_path: Path
) -> None:
    rc, out, err = run_summon_cli("status", "claude", cwd=tmp_path)

    assert rc == 2
    assert "nothing summoned as 'claude'" in err
    assert out == ""
