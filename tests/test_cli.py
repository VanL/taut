from __future__ import annotations

import json
import re
from pathlib import Path
from typing import TextIO, cast

import pytest

import taut.cli as cli
from taut.cli import _format_unread_count
from taut.client import Message
from tests.conftest import run_cli

pytestmark = [pytest.mark.sqlite_only, pytest.mark.usefixtures("clean_env")]


def _heading_pattern(thread: str) -> str:
    escaped = re.escape(thread)
    return rf"(?:── {escaped} ─{{38}}|-- {escaped} -{{38}})"


def _notice_pattern(text_pattern: str, *, timestamps: bool = False) -> str:
    id_pattern = r"\d{19}  " if timestamps else ""
    return rf"  {id_pattern}\d\d:\d\d (?:·|-) {text_pattern}"


def test_cli_human_glyphs_fall_back_for_legacy_stdout_encoding() -> None:
    class C1252Stream:
        encoding = "cp1252"
        errors = "strict"

    stream = cast(TextIO, C1252Stream())
    message = Message(
        thread="general",
        ts=1_785_000_000_000_000_000,
        from_id="m_" + "a" * 26,
        from_name="van",
        kind="notice",
        text="van created #general",
    )

    assert cli._thread_heading("general", stream=stream) == (
        "-- general --------------------------------------"
    )
    expected_time = cli._format_message_time(message.ts)

    assert (
        cli._human_message_row(
            message,
            timestamps=False,
            sender_width=6,
            stream=stream,
        )
        == f"  {expected_time} - van created #general"
    )


def test_cli_json_join_say_log(tmp_path: Path) -> None:
    assert run_cli("init", "--json", cwd=tmp_path)[0] == 0
    rc, out, _ = run_cli("--as", "van", "join", "general", "--json", cwd=tmp_path)

    assert rc == 0
    lines = [json.loads(line) for line in out.splitlines()]
    assert lines[0]["name"] == "van"
    assert lines[0]["member_id"].startswith("m_")
    assert lines[1]["kind"] == "notice"
    assert lines[1]["from_id"] == lines[0]["member_id"]

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
    assert re.fullmatch(_heading_pattern("general"), lines[0])
    assert re.fullmatch(_notice_pattern(r"van created #general"), lines[1])
    assert re.fullmatch(_notice_pattern(r"claude joined"), lines[2])
    assert re.fullmatch(r"  \d\d:\d\d claude  yes\. what broke\?", lines[3])


def test_cli_human_log_timestamps_prepend_message_ids(tmp_path: Path) -> None:
    assert run_cli("init", cwd=tmp_path)[0] == 0
    assert run_cli("--as", "van", "join", "general", cwd=tmp_path)[0] == 0

    rc, out, _err = run_cli("log", "general", "-t", cwd=tmp_path)

    assert rc == 0
    lines = out.splitlines()
    assert re.fullmatch(_heading_pattern("general"), lines[0])
    assert re.fullmatch(
        _notice_pattern(r"van created #general", timestamps=True),
        lines[1],
    )


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
    assert re.fullmatch(_heading_pattern("general"), lines[0])
    assert re.fullmatch(_notice_pattern(r"claude joined"), lines[1])
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
    assert json.loads(out)["name"] == "van"

    rc, out, _err = run_cli("whoami", "--json", "--token", token, cwd=tmp_path)

    assert rc == 0
    assert json.loads(out)["name"] == "van"


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
    assert json.loads(out)["name"] == "van"


def test_cli_rejoin_uses_global_token_or_as_selector(tmp_path: Path) -> None:
    assert run_cli("init", cwd=tmp_path)[0] == 0
    rc, out, _err = run_cli("--as", "van", "join", "general", "--json", cwd=tmp_path)
    assert rc == 0
    token = next(
        json.loads(line)["token"] for line in out.splitlines() if "token" in line
    )

    rc, out, _err = run_cli("--token", token, "rejoin", "--json", cwd=tmp_path)

    assert rc == 0
    assert json.loads(out)["name"] == "van"

    rc, out, _err = run_cli("--as", "van", "rejoin", "--json", cwd=tmp_path)

    assert rc == 0
    assert json.loads(out)["name"] == "van"


def test_cli_rejoin_rejects_ambiguous_name_and_token(tmp_path: Path) -> None:
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


def test_cli_set_name_json_and_old_name_stops_routing(tmp_path: Path) -> None:
    assert run_cli("init", cwd=tmp_path)[0] == 0
    assert run_cli("--as", "van", "join", "general", cwd=tmp_path)[0] == 0

    rc, out, err = run_cli("--as", "van", "set", "name", "VanL", "--json", cwd=tmp_path)

    assert rc == 0, err
    obj = json.loads(out)
    assert obj["name"] == "VanL"
    assert "member_id" in obj

    rc, _out, err = run_cli("--as", "van", "whoami", cwd=tmp_path)
    assert rc == 2
    assert "member not found" in err


def test_cli_set_name_unrecognized_exits_2(tmp_path: Path) -> None:
    assert run_cli("init", cwd=tmp_path)[0] == 0

    rc, _out, err = run_cli("set", "name", "VanL", cwd=tmp_path)

    assert rc == 2
    assert "unrecognized caller" in err


def test_cli_say_dm_and_list_json_members(tmp_path: Path) -> None:
    assert run_cli("init", cwd=tmp_path)[0] == 0
    assert run_cli("--as", "van", "join", "general", cwd=tmp_path)[0] == 0
    assert run_cli("--as", "bob", "join", "general", cwd=tmp_path)[0] == 0

    rc, out, err = run_cli("--as", "van", "say", "@bob", "hi", "--json", cwd=tmp_path)

    assert rc == 0, err
    message = json.loads(out)
    assert message["thread"].startswith("dm.")

    rc, out, err = run_cli("--as", "bob", "list", "--all", "--json", cwd=tmp_path)
    assert rc == 0, err
    dm = next(obj for obj in map(json.loads, out.splitlines()) if obj["kind"] == "dm")
    assert set(dm["members"]) == {
        message["from_id"],
        json.loads(run_cli("--as", "bob", "whoami", "--json", cwd=tmp_path)[1])[
            "member_id"
        ],
    }


def test_cli_inbox_json_claims_notifications(tmp_path: Path) -> None:
    assert run_cli("init", cwd=tmp_path)[0] == 0
    assert run_cli("--as", "van", "join", "general", cwd=tmp_path)[0] == 0
    assert run_cli("--as", "bob", "join", "general", cwd=tmp_path)[0] == 0
    assert run_cli("--as", "van", "say", "general", "hello @bob", cwd=tmp_path)[0] == 0

    rc, out, err = run_cli("--as", "bob", "inbox", "--json", cwd=tmp_path)

    assert rc == 0, err
    notification = json.loads(out)
    assert notification["type"] == "mention"
    assert notification["actor_name"] == "van"

    rc, _out, err = run_cli("--as", "bob", "inbox", "--json", cwd=tmp_path)
    assert rc == 2
    assert "nothing pending" in err


def test_cli_rename_channel_json(tmp_path: Path) -> None:
    assert run_cli("init", cwd=tmp_path)[0] == 0
    assert run_cli("--as", "van", "join", "general", cwd=tmp_path)[0] == 0

    rc, out, err = run_cli("rename", "general", "ops", "--json", cwd=tmp_path)

    assert rc == 0, err
    obj = json.loads(out)
    assert obj["thread"] == "ops"
    assert obj["kind"] == "channel"
