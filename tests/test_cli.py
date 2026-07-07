from __future__ import annotations

import json
import os
import queue as queue_module
import re
import signal
import subprocess
import sys
import threading
from pathlib import Path
from typing import TextIO, cast

import pytest
from simplebroker import Queue

import taut.cli as cli
from taut import addressing
from taut._constants import META_QUEUE_NAME
from taut.cli import _format_unread_count
from taut.client import Message
from taut.envelope import encode_envelope
from taut.state import SQLITE_SQL_DIALECT, SqlSidecarTautState
from tests.conftest import build_cli_env, run_cli

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


def test_cli_usage_error_unknown_flag_exits_1(tmp_path: Path) -> None:
    rc, out, err = run_cli("read", "--bogus", cwd=tmp_path)

    assert rc == 1
    assert "usage:" in err
    assert out == ""


def test_cli_usage_error_unknown_subcommand_exits_1(tmp_path: Path) -> None:
    rc, out, err = run_cli("nosuchverb", cwd=tmp_path)

    assert rc == 1
    assert "usage:" in err
    assert out == ""


def test_cli_usage_error_nested_set_subcommand_exits_1(tmp_path: Path) -> None:
    rc, out, err = run_cli("set", "bogus", cwd=tmp_path)

    assert rc == 1
    assert "usage:" in err
    assert out == ""


def test_cli_help_exits_0(tmp_path: Path) -> None:
    rc, out, _err = run_cli("--help", cwd=tmp_path)

    assert rc == 0
    assert "usage:" in out


def test_cli_version_exits_0(tmp_path: Path) -> None:
    rc, out, _err = run_cli("--version", cwd=tmp_path)

    assert rc == 0
    assert out.startswith("taut ")


def test_cli_double_dash_posts_literal_quiet_flag_text(tmp_path: Path) -> None:
    assert run_cli("init", cwd=tmp_path)[0] == 0
    assert run_cli("--as", "van", "join", "general", cwd=tmp_path)[0] == 0

    # stdin is pinned empty so the pre-fix hoist bug (which eats the "-q"
    # token and falls back to stdin) fails fast instead of blocking.
    rc, _out, err = run_cli(
        "--as", "van", "say", "general", "--", "-q", cwd=tmp_path, stdin=""
    )

    assert rc == 0, err
    rc, out, _err = run_cli("log", "general", "--json", cwd=tmp_path)
    assert rc == 0
    assert "-q" in [json.loads(line)["text"] for line in out.splitlines()]


def test_cli_double_dash_posts_literal_json_flag_text(tmp_path: Path) -> None:
    assert run_cli("init", cwd=tmp_path)[0] == 0
    assert run_cli("--as", "van", "join", "general", cwd=tmp_path)[0] == 0

    rc, _out, err = run_cli(
        "--as", "van", "say", "general", "--", "--json", cwd=tmp_path, stdin=""
    )

    assert rc == 0, err
    rc, out, _err = run_cli("log", "general", "--json", cwd=tmp_path)
    assert rc == 0
    assert "--json" in [json.loads(line)["text"] for line in out.splitlines()]


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


def test_cli_rename_finishes_interrupted_rename(tmp_path: Path) -> None:
    assert run_cli("init", cwd=tmp_path)[0] == 0
    assert run_cli("--as", "van", "join", "general", cwd=tmp_path)[0] == 0
    assert run_cli("--as", "van", "say", "general", "root", cwd=tmp_path)[0] == 0

    # White-box crash-window simulation (see tests/test_client.py): public
    # APIs never leave a 'started' marker behind; this reproduces a rename
    # interrupted before any broker queue was renamed.
    queue = Queue(META_QUEUE_NAME, db_path=str(tmp_path / ".taut.db"))
    try:
        SqlSidecarTautState(queue, SQLITE_SQL_DIALECT).start_channel_rename(
            old_name="general",
            new_name="ops",
            affected=[{"old": "general", "new": "ops"}],
            started_ts=queue.generate_timestamp(),
        )
    finally:
        queue.close()

    rc, _out, err = run_cli("--as", "van", "say", "general", "blocked", cwd=tmp_path)
    assert rc == 1
    assert "run 'taut rename general ops' to finish it" in err

    rc, out, err = run_cli("rename", "general", "ops", "--json", cwd=tmp_path)
    assert rc == 0, err
    assert json.loads(out)["thread"] == "ops"

    rc, out, err = run_cli("--as", "van", "log", "ops", "--json", cwd=tmp_path)
    assert rc == 0, err
    assert [json.loads(line)["text"] for line in out.splitlines()] == [
        "van created #general",
        "root",
    ]


def test_cli_dm_mention_suppression_warning_renders_verbatim(tmp_path: Path) -> None:
    assert run_cli("init", cwd=tmp_path)[0] == 0
    assert run_cli("--as", "van", "join", "general", cwd=tmp_path)[0] == 0
    assert run_cli("--as", "bob", "join", "general", cwd=tmp_path)[0] == 0
    van_id = json.loads(run_cli("--as", "van", "whoami", "--json", cwd=tmp_path)[1])[
        "member_id"
    ]
    bob_id = json.loads(run_cli("--as", "bob", "whoami", "--json", cwd=tmp_path)[1])[
        "member_id"
    ]
    thread = addressing.dm_queue_name(van_id, bob_id)

    # White-box seeding (corrupted-registry simulation): the public API
    # always writes members meta on DM registry rows; fabricate the DM row
    # without it so mention scoping has no participant list to consult.
    queue = Queue(META_QUEUE_NAME, db_path=str(tmp_path / ".taut.db"))
    try:
        SqlSidecarTautState(queue, SQLITE_SQL_DIALECT).upsert_thread(
            name=thread,
            kind="dm",
            parent=None,
            origin_ts=None,
            created_by=van_id,
            meta={},
            created_ts=queue.generate_timestamp(),
        )
    finally:
        queue.close()

    rc, out, err = run_cli(
        "--as", "van", "say", "@bob", "hi @bob", "--json", cwd=tmp_path
    )

    assert rc == 0, err
    assert json.loads(out)["thread"] == thread
    assert "warning" not in out
    assert (
        "warning: mention notifications suppressed: direct-message registry "
        f"row for {thread} lacks participant metadata"
    ) in err

    rc, _out, err = run_cli("--as", "bob", "inbox", "--json", cwd=tmp_path)
    assert rc == 2
    assert "nothing pending" in err


def _log_texts(tmp_path: Path, thread: str) -> list[str]:
    rc, out, err = run_cli("log", thread, "--json", cwd=tmp_path)
    assert rc == 0, err
    return [json.loads(line)["text"] for line in out.splitlines()]


def _log_ts_values(tmp_path: Path, thread: str) -> list[int]:
    rc, out, err = run_cli("log", thread, "--json", cwd=tmp_path)
    assert rc == 0, err
    return [json.loads(line)["ts"] for line in out.splitlines()]


def _say_ts(tmp_path: Path, name: str, thread: str, text: str) -> int:
    rc, out, err = run_cli("--as", name, "say", thread, text, "--json", cwd=tmp_path)
    assert rc == 0, err
    return next(
        cast(int, obj["ts"]) for obj in map(json.loads, out.splitlines()) if "ts" in obj
    )


def test_cli_leave_member_exit_0_and_notice_in_log(tmp_path: Path) -> None:
    assert run_cli("init", cwd=tmp_path)[0] == 0
    assert run_cli("--as", "van", "join", "general", cwd=tmp_path)[0] == 0

    rc, _out, err = run_cli("--as", "van", "leave", "general", cwd=tmp_path)

    assert rc == 0, err
    assert "van left" in _log_texts(tmp_path, "general")


def test_cli_leave_non_member_exit_2(tmp_path: Path) -> None:
    assert run_cli("init", cwd=tmp_path)[0] == 0
    assert run_cli("--as", "van", "join", "general", cwd=tmp_path)[0] == 0
    assert run_cli("--as", "bob", "join", "other", cwd=tmp_path)[0] == 0

    rc, _out, err = run_cli("--as", "bob", "leave", "general", cwd=tmp_path)

    assert rc == 2
    assert "is not a member of general" in err


def test_cli_reply_full_id_posts_into_subthread(tmp_path: Path) -> None:
    assert run_cli("init", cwd=tmp_path)[0] == 0
    assert run_cli("--as", "van", "join", "general", cwd=tmp_path)[0] == 0
    root_ts = _say_ts(tmp_path, "van", "general", "root")

    rc, out, err = run_cli(
        "--as", "van", "reply", "general", str(root_ts), "child", "--json", cwd=tmp_path
    )

    assert rc == 0, err
    reply = json.loads(out)
    assert reply["thread"] == f"general.{root_ts}"
    assert reply["text"] == "child"
    assert _log_texts(tmp_path, f"general.{root_ts}") == ["child"]


def test_cli_reply_suffix_resolves_message(tmp_path: Path) -> None:
    assert run_cli("init", cwd=tmp_path)[0] == 0
    assert run_cli("--as", "van", "join", "general", cwd=tmp_path)[0] == 0
    root_ts = _say_ts(tmp_path, "van", "general", "root")

    # Shortest >=4-digit suffix of the target id that is unique across
    # the thread's history (a shorter one could collide with the notice).
    ts_values = _log_ts_values(tmp_path, "general")
    full = str(root_ts)
    suffix = next(
        full[-length:]
        for length in range(4, 20)
        if sum(1 for ts in ts_values if str(ts).endswith(full[-length:])) == 1
    )

    rc, out, err = run_cli(
        "--as", "van", "reply", "general", suffix, "via suffix", "--json", cwd=tmp_path
    )

    assert rc == 0, err
    assert json.loads(out)["thread"] == f"general.{root_ts}"


def test_cli_reply_ambiguous_suffix_exit_1_lists_candidates(tmp_path: Path) -> None:
    assert run_cli("init", cwd=tmp_path)[0] == 0
    assert run_cli("--as", "van", "join", "general", cwd=tmp_path)[0] == 0
    van_id = json.loads(run_cli("--as", "van", "whoami", "--json", cwd=tmp_path)[1])[
        "member_id"
    ]

    # White-box crafted-timestamp seeding: the public API cannot
    # deterministically mint two message ids sharing a 4-digit suffix, so
    # insert two envelopes whose ids differ by exactly 10_000.
    queue = Queue("general", db_path=str(tmp_path / ".taut.db"))
    try:
        ts_a = queue.generate_timestamp()
        ts_b = ts_a + 10_000
        queue.insert_messages(
            [
                (
                    encode_envelope(
                        from_id=van_id, from_name="van", kind="message", text=text
                    ),
                    ts,
                )
                for text, ts in (("first twin", ts_a), ("second twin", ts_b))
            ]
        )
    finally:
        queue.close()

    rc, out, err = run_cli(
        "--as", "van", "reply", "general", str(ts_a)[-4:], "child", cwd=tmp_path
    )

    assert rc == 1
    assert out == ""
    assert "ambiguous message id suffix" in err
    assert str(ts_a) in err
    assert str(ts_b) in err


def test_cli_reply_unknown_suffix_exit_2(tmp_path: Path) -> None:
    assert run_cli("init", cwd=tmp_path)[0] == 0
    assert run_cli("--as", "van", "join", "general", cwd=tmp_path)[0] == 0
    _say_ts(tmp_path, "van", "general", "root")

    ts_values = _log_ts_values(tmp_path, "general")
    unknown = next(
        candidate
        for candidate in ("1111", "2222", "3333", "4444", "5555", "6666", "7777")
        if not any(str(ts).endswith(candidate) for ts in ts_values)
    )

    rc, _out, err = run_cli(
        "--as", "van", "reply", "general", unknown, "child", cwd=tmp_path
    )

    assert rc == 2
    assert "message not found" in err


def test_cli_who_bare_and_per_thread(tmp_path: Path) -> None:
    assert run_cli("init", cwd=tmp_path)[0] == 0
    assert run_cli("--as", "van", "join", "general", cwd=tmp_path)[0] == 0
    assert run_cli("--as", "bob", "join", "other", cwd=tmp_path)[0] == 0

    rc, out, err = run_cli("who", "--json", cwd=tmp_path)

    assert rc == 0, err
    names = {json.loads(line)["name"] for line in out.splitlines()}
    assert names == {"van", "bob"}

    rc, out, err = run_cli("who", "general", "--json", cwd=tmp_path)

    assert rc == 0, err
    assert [json.loads(line)["name"] for line in out.splitlines()] == ["van"]


def test_cli_who_unknown_thread_exit_2(tmp_path: Path) -> None:
    assert run_cli("init", cwd=tmp_path)[0] == 0
    assert run_cli("--as", "van", "join", "general", cwd=tmp_path)[0] == 0

    rc, _out, err = run_cli("who", "nosuch", cwd=tmp_path)

    assert rc == 2
    assert "thread not found" in err


@pytest.mark.skipif(
    os.name == "nt",
    reason="SIGINT-driven clean stop is not a Windows process contract",
)
def test_cli_watch_json_streams_message_and_sigint_exits_0(tmp_path: Path) -> None:
    """[TAUT-8.1] watch: live-follow delivers messages as ndjson and a
    SIGINT stop is a clean stop (exit 0)."""

    assert run_cli("init", cwd=tmp_path)[0] == 0
    assert run_cli("--as", "van", "join", "general", cwd=tmp_path)[0] == 0
    assert run_cli("--as", "bob", "join", "general", cwd=tmp_path)[0] == 0

    proc = subprocess.Popen(
        [sys.executable, "-m", "taut", "--as", "van", "watch", "--json"],
        cwd=tmp_path,
        env=build_cli_env(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )
    lines: queue_module.Queue[str] = queue_module.Queue()
    try:
        assert proc.stdout is not None
        stdout = proc.stdout

        def _pump() -> None:
            for line in stdout:
                lines.put(line)

        threading.Thread(target=_pump, daemon=True).start()

        assert run_cli("--as", "bob", "say", "general", "ping", cwd=tmp_path)[0] == 0

        seen = False
        for _ in range(60):  # bounded wait: 60 * 0.5s
            try:
                line = lines.get(timeout=0.5)
            except queue_module.Empty:
                continue
            if json.loads(line).get("text") == "ping":
                seen = True
                break
        assert seen, "watch did not deliver the message within the bounded wait"

        proc.send_signal(signal.SIGINT)
        assert proc.wait(timeout=10) == 0
    finally:
        if proc.poll() is None:
            proc.kill()
        proc.wait(timeout=10)
        if proc.stderr is not None:
            proc.stderr.close()
        if proc.stdout is not None:
            proc.stdout.close()


def test_cli_taut_as_env_resolves_like_as_flag(tmp_path: Path) -> None:
    assert run_cli("init", cwd=tmp_path)[0] == 0
    assert run_cli("--as", "van", "join", "general", cwd=tmp_path)[0] == 0

    rc, out, err = run_cli("whoami", "--json", cwd=tmp_path, env={"TAUT_AS": "van"})

    assert rc == 0, err
    assert json.loads(out)["name"] == "van"

    rc, _out, err = run_cli(
        "say", "general", "sent via env", cwd=tmp_path, env={"TAUT_AS": "van"}
    )

    assert rc == 0, err
    assert "sent via env" in _log_texts(tmp_path, "general")


def test_cli_db_flag_resolves_from_another_cwd(tmp_path: Path) -> None:
    data = tmp_path / "data"
    data.mkdir()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    db = data / ".taut.db"

    assert run_cli("init", "--db", str(db), cwd=elsewhere)[0] == 0
    assert db.exists()
    assert not (elsewhere / ".taut.db").exists()

    assert (
        run_cli("--db", str(db), "--as", "van", "join", "general", cwd=elsewhere)[0]
        == 0
    )
    assert (
        run_cli("--db", str(db), "--as", "van", "say", "general", "hi", cwd=elsewhere)[
            0
        ]
        == 0
    )

    rc, out, err = run_cli("--db", str(db), "log", "general", "--json", cwd=elsewhere)

    assert rc == 0, err
    assert "hi" in [json.loads(line)["text"] for line in out.splitlines()]


def test_cli_quiet_suppresses_stderr_on_error_path_but_not_exit_code(
    tmp_path: Path,
) -> None:
    rc, out, err = run_cli("-q", "list", cwd=tmp_path)

    assert rc == 1
    assert out == ""
    assert err == ""


def test_cli_join_persona_visible_in_whoami_json(tmp_path: Path) -> None:
    assert run_cli("init", cwd=tmp_path)[0] == 0
    assert (
        run_cli(
            "--as",
            "van",
            "join",
            "general",
            "--persona",
            "keeper of the build",
            cwd=tmp_path,
        )[0]
        == 0
    )

    rc, out, err = run_cli("--as", "van", "whoami", "--json", cwd=tmp_path)

    assert rc == 0, err
    assert json.loads(out)["persona"] == "keeper of the build"


def test_cli_join_new_mints_second_member(tmp_path: Path) -> None:
    assert run_cli("init", cwd=tmp_path)[0] == 0
    rc, out, err = run_cli("join", "general", "--json", cwd=tmp_path)
    assert rc == 0, err
    first = next(obj for obj in map(json.loads, out.splitlines()) if "token" in obj)

    rc, out, err = run_cli("join", "general", "--new", "--json", cwd=tmp_path)

    assert rc == 0, err
    second = next(obj for obj in map(json.loads, out.splitlines()) if "token" in obj)
    assert second["member_id"] != first["member_id"]

    rc, out, err = run_cli("who", "--json", cwd=tmp_path)
    assert rc == 0, err
    member_ids = {json.loads(line)["member_id"] for line in out.splitlines()}
    assert {first["member_id"], second["member_id"]} <= member_ids


def test_cli_say_dash_posts_piped_stdin(tmp_path: Path) -> None:
    assert run_cli("init", cwd=tmp_path)[0] == 0
    assert run_cli("--as", "van", "join", "general", cwd=tmp_path)[0] == 0

    rc, _out, err = run_cli(
        "--as", "van", "say", "general", "-", cwd=tmp_path, stdin="hello from stdin\n"
    )

    assert rc == 0, err
    assert "hello from stdin\n" in _log_texts(tmp_path, "general")


def test_cli_say_without_text_posts_piped_stdin(tmp_path: Path) -> None:
    assert run_cli("init", cwd=tmp_path)[0] == 0
    assert run_cli("--as", "van", "join", "general", cwd=tmp_path)[0] == 0

    # Pipe-detection branch: TEXT omitted and stdin is not a tty.
    rc, _out, err = run_cli(
        "--as", "van", "say", "general", cwd=tmp_path, stdin="piped body"
    )

    assert rc == 0, err
    assert "piped body" in _log_texts(tmp_path, "general")
