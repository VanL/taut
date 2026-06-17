from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from taut.cli import _format_unread_count
from tests.conftest import run_cli

pytestmark = pytest.mark.usefixtures("clean_env")


def test_cli_json_join_say_log(tmp_path: Path) -> None:
    assert run_cli("init", "--json", cwd=tmp_path)[0] == 0
    rc, out, _ = run_cli("--as", "van", "join", "general", "--json", cwd=tmp_path)

    assert rc == 0
    lines = [json.loads(line) for line in out.splitlines()]
    assert lines[0]["handle"] == "van"
    assert lines[1]["kind"] == "notice"

    rc, out, _ = run_cli(
        "--as", "van", "say", "general", "hello", "--json", cwd=tmp_path
    )

    assert rc == 0
    assert json.loads(out)["text"] == "hello"

    rc, out, _ = run_cli("log", "general", "--json", cwd=tmp_path)

    assert rc == 0
    assert [json.loads(line)["text"] for line in out.splitlines()] == [
        "van created #general",
        "hello",
    ]


def test_cli_human_log_groups_messages_by_thread(tmp_path: Path) -> None:
    assert run_cli("init", cwd=tmp_path)[0] == 0
    assert run_cli("--as", "van", "join", "general", cwd=tmp_path)[0] == 0
    assert run_cli("--as", "claude", "join", "general", cwd=tmp_path)[0] == 0
    assert (
        run_cli("--as", "claude", "say", "general", "yes. what broke?", cwd=tmp_path)[0]
        == 0
    )

    rc, out, _err = run_cli("log", "general", cwd=tmp_path)

    assert rc == 0
    lines = out.splitlines()
    assert lines[0] == "── general ──────────────────────────────────────"
    assert re.fullmatch(r"  \d\d:\d\d · van created #general", lines[1])
    assert re.fullmatch(r"  \d\d:\d\d · claude joined", lines[2])
    assert re.fullmatch(r"  \d\d:\d\d claude  yes\. what broke\?", lines[3])


def test_cli_human_log_timestamps_prepend_message_ids(tmp_path: Path) -> None:
    assert run_cli("init", cwd=tmp_path)[0] == 0
    assert run_cli("--as", "van", "join", "general", cwd=tmp_path)[0] == 0

    rc, out, _err = run_cli("log", "general", "-t", cwd=tmp_path)

    assert rc == 0
    lines = out.splitlines()
    assert lines[0] == "── general ──────────────────────────────────────"
    assert re.fullmatch(r"  \d{19}  \d\d:\d\d · van created #general", lines[1])


def test_cli_log_limit_returns_most_recent_messages(tmp_path: Path) -> None:
    assert run_cli("init", cwd=tmp_path)[0] == 0
    assert run_cli("--as", "van", "join", "general", cwd=tmp_path)[0] == 0
    assert run_cli("--as", "van", "say", "general", "old", cwd=tmp_path)[0] == 0
    assert run_cli("--as", "van", "say", "general", "latest", cwd=tmp_path)[0] == 0

    rc, out, _err = run_cli("log", "general", "--limit", "1", cwd=tmp_path)

    assert rc == 0
    assert "latest" in out
    assert "old" not in out


def test_cli_human_read_uses_grouped_readme_shape(tmp_path: Path) -> None:
    assert run_cli("init", cwd=tmp_path)[0] == 0
    assert run_cli("--as", "van", "join", "general", cwd=tmp_path)[0] == 0
    assert run_cli("--as", "claude", "join", "general", cwd=tmp_path)[0] == 0
    assert run_cli("--as", "claude", "say", "general", "yes", cwd=tmp_path)[0] == 0

    rc, out, _err = run_cli("--as", "van", "read", "general", cwd=tmp_path)

    assert rc == 0
    lines = out.splitlines()
    assert lines[0] == "── general ──────────────────────────────────────"
    assert re.fullmatch(r"  \d\d:\d\d · claude joined", lines[1])
    assert re.fullmatch(r"  \d\d:\d\d claude  yes", lines[2])


def test_cli_human_list_shows_unread_counts(tmp_path: Path) -> None:
    assert run_cli("init", cwd=tmp_path)[0] == 0
    assert run_cli("--as", "van", "join", "general", cwd=tmp_path)[0] == 0
    assert run_cli("--as", "claude", "join", "general", cwd=tmp_path)[0] == 0
    assert run_cli("--as", "claude", "say", "general", "one", cwd=tmp_path)[0] == 0

    rc, out, _err = run_cli("--as", "van", "list", cwd=tmp_path)

    assert rc == 0
    assert out == "general  2 unread"


def test_cli_human_list_caps_unread_count_display() -> None:
    assert _format_unread_count(999) == "999"
    assert _format_unread_count(1000) == "999+"


def test_cli_missing_database_exit_1(tmp_path: Path) -> None:
    rc, _out, err = run_cli("list", cwd=tmp_path)

    assert rc == 1
    assert "No taut database found" in err


def test_cli_read_empty_exit_2(tmp_path: Path) -> None:
    assert run_cli("init", cwd=tmp_path)[0] == 0
    assert run_cli("--as", "van", "join", "general", cwd=tmp_path)[0] == 0

    rc, _out, err = run_cli("--as", "van", "read", "general", cwd=tmp_path)

    assert rc == 2
    assert "nothing unread" in err


def test_cli_global_token_resolves_identity_before_and_after_command(
    tmp_path: Path,
) -> None:
    assert run_cli("init", cwd=tmp_path)[0] == 0
    rc, out, _err = run_cli("--as", "van", "join", "general", "--json", cwd=tmp_path)
    assert rc == 0
    token = next(
        json.loads(line)["token"] for line in out.splitlines() if "token" in line
    )

    rc, out, _err = run_cli("--token", token, "whoami", "--json", cwd=tmp_path)

    assert rc == 0
    assert json.loads(out)["handle"] == "van"

    rc, out, _err = run_cli("whoami", "--json", "--token", token, cwd=tmp_path)

    assert rc == 0
    assert json.loads(out)["handle"] == "van"


def test_cli_whoami_invalid_token_is_error_exit_1(tmp_path: Path) -> None:
    assert run_cli("init", cwd=tmp_path)[0] == 0

    rc, _out, err = run_cli(
        "whoami",
        "--json",
        cwd=tmp_path,
        env={"TAUT_TOKEN": "taut-invalid"},
    )

    assert rc == 1
    assert "TAUT_TOKEN does not match" in err


def test_cli_rejoin_token_is_not_consumed_by_global_hoisting(
    tmp_path: Path,
) -> None:
    assert run_cli("init", cwd=tmp_path)[0] == 0
    rc, out, _err = run_cli("--as", "van", "join", "general", "--json", cwd=tmp_path)
    assert rc == 0
    token = next(
        json.loads(line)["token"] for line in out.splitlines() if "token" in line
    )

    rc, out, _err = run_cli("rejoin", "--token", token, "--json", cwd=tmp_path)

    assert rc == 0
    assert json.loads(out)["handle"] == "van"


def test_cli_rejoin_uses_global_token_or_as_selector(tmp_path: Path) -> None:
    assert run_cli("init", cwd=tmp_path)[0] == 0
    rc, out, _err = run_cli("--as", "van", "join", "general", "--json", cwd=tmp_path)
    assert rc == 0
    token = next(
        json.loads(line)["token"] for line in out.splitlines() if "token" in line
    )

    rc, out, _err = run_cli("--token", token, "rejoin", "--json", cwd=tmp_path)

    assert rc == 0
    assert json.loads(out)["handle"] == "van"

    rc, out, _err = run_cli("--as", "van", "rejoin", "--json", cwd=tmp_path)

    assert rc == 0
    assert json.loads(out)["handle"] == "van"


def test_cli_rejoin_rejects_ambiguous_handle_and_token(tmp_path: Path) -> None:
    assert run_cli("init", cwd=tmp_path)[0] == 0
    rc, out, _err = run_cli("--as", "van", "join", "general", "--json", cwd=tmp_path)
    assert rc == 0
    token = next(
        json.loads(line)["token"] for line in out.splitlines() if "token" in line
    )

    rc, _out, err = run_cli("rejoin", "van", "--token", token, cwd=tmp_path)

    assert rc == 1
    assert "exactly one" in err

    rc, _out, err = run_cli("--token", token, "rejoin", "van", cwd=tmp_path)

    assert rc == 1
    assert "exactly one" in err
