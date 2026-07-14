from __future__ import annotations

import argparse
import json
import os
import queue as queue_module
import re
import signal
import subprocess
import sys
import threading
from io import StringIO
from pathlib import Path
from typing import TextIO, cast

import pytest
from simplebroker import Queue

import taut.cli as cli
from taut import addressing
from taut._constants import META_QUEUE_NAME
from taut._exceptions import TautError
from taut.client import InitResult, Message, _validate_sqlite_path
from taut.commands._rendering import emit_init as _emit_init
from taut.commands._rendering import format_message_time as _format_message_time
from taut.commands._rendering import format_unread_count as _format_unread_count
from taut.commands._rendering import human_message_row as _human_message_row
from taut.commands._rendering import thread_heading as _thread_heading
from taut.envelope import encode_envelope
from taut.state import SQLITE_SQL_DIALECT, SqlSidecarTautState
from tests.conftest import PROJECT_ROOT, build_cli_env, run_cli

pytestmark = [pytest.mark.sqlite_only, pytest.mark.usefixtures("clean_env")]


def _heading_pattern(thread: str) -> str:
    escaped = re.escape(thread)
    return rf"(?:── {escaped} ─{{38}}|-- {escaped} -{{38}})"


def _notice_pattern(text_pattern: str, *, timestamps: bool = False) -> str:
    id_pattern = r"\d{19}  " if timestamps else ""
    return rf"  {id_pattern}\d\d:\d\d (?:·|-) {text_pattern}"


def _assert_only_structural_newlines(text: str) -> None:
    assert all(
        character == "\n"
        or not (ord(character) < 0x20 or 0x7F <= ord(character) <= 0x9F)
        for character in text
    )


def _write_terminal_project_config(
    root: Path,
    *,
    escape_patterns: tuple[str, ...],
    inherit_defaults: bool | None = None,
    target: str = ".taut.db",
) -> None:
    lines = [
        "version = 1",
        'backend = "sqlite"',
        f"target = {json.dumps(target)}",
        "",
        "[terminal_text]",
    ]
    if inherit_defaults is not None:
        lines.append(f"inherit_defaults = {str(inherit_defaults).lower()}")
    rendered_patterns = ", ".join(json.dumps(item) for item in escape_patterns)
    lines.extend((f"escape_patterns = [{rendered_patterns}]", ""))
    (root / ".taut.toml").write_text("\n".join(lines), encoding="utf-8")


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

    assert _thread_heading("general", stream=stream) == (
        "-- general --------------------------------------"
    )
    expected_time = _format_message_time(message.ts)

    assert (
        _human_message_row(
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


def test_cli_human_message_controls_are_visible_while_json_stays_exact(
    tmp_path: Path,
) -> None:
    assert run_cli("init", cwd=tmp_path)[0] == 0
    assert run_cli("--as", "van", "join", "general", cwd=tmp_path)[0] == 0
    assert run_cli("--as", "bob", "join", "general", cwd=tmp_path)[0] == 0
    probe = "line1\nline2\x1b]52;c;Y2xpcGJvYXJk\x07\x9b[31m\r\b\tend"
    escaped = r"line1\nline2\x1b]52;c;Y2xpcGJvYXJk\a\x9b[31m\r\b\tend"
    assert run_cli("--as", "van", "say", "general", probe, cwd=tmp_path)[0] == 0

    rc, human, err = run_cli("log", "general", cwd=tmp_path)
    assert rc == 0, err
    assert escaped in human
    _assert_only_structural_newlines(human)
    assert sum(escaped in line for line in human.splitlines()) == 1

    rc, unread, err = run_cli("--as", "bob", "read", "general", cwd=tmp_path)
    assert rc == 0, err
    assert escaped in unread
    _assert_only_structural_newlines(unread)

    rc, encoded, err = run_cli("log", "general", "--json", cwd=tmp_path)
    assert rc == 0, err
    assert probe in [json.loads(line)["text"] for line in encoded.splitlines()]


def test_cli_forged_sender_and_foreign_body_are_safe_only_in_human_output(
    tmp_path: Path,
) -> None:
    assert run_cli("init", cwd=tmp_path)[0] == 0
    assert run_cli("--as", "van", "join", "general", cwd=tmp_path)[0] == 0
    member = json.loads(run_cli("--as", "van", "whoami", "--json", cwd=tmp_path)[1])
    sender = "forged\x1b]0;title\x07\t"
    body = "body\nnext\x9b[31m\r\b"
    foreign = "foreign\x1b]52;c;Y2xpcGJvYXJk\x07\nrow"
    queue = Queue("general", db_path=str(tmp_path / ".taut.db"))
    try:
        queue.write(
            encode_envelope(
                from_id=member["member_id"],
                from_name=sender,
                kind="message",
                text=body,
            )
        )
        queue.write(foreign)
    finally:
        queue.close()

    rc, human, err = run_cli("log", "general", cwd=tmp_path)
    assert rc == 0, err
    assert r"forged\x1b]0;title\a\t" in human
    assert r"body\nnext\x9b[31m\r\b" in human
    assert r"foreign\x1b]52;c;Y2xpcGJvYXJk\a\nrow" in human
    _assert_only_structural_newlines(human + "\n" + err)

    rc, encoded, err = run_cli("log", "general", "--json", cwd=tmp_path)
    assert rc == 0, err
    records = [json.loads(line) for line in encoded.splitlines()]
    forged = next(record for record in records if record["from"] == sender)
    raw = next(record for record in records if record["kind"] == "foreign")
    assert forged["text"] == body
    assert raw["text"] == foreign


def test_cli_human_message_escaping_does_not_rescan_generated_escapes(
    tmp_path: Path,
) -> None:
    _write_terminal_project_config(
        tmp_path,
        escape_patterns=(r"\\",),
    )
    assert run_cli("init", cwd=tmp_path)[0] == 0
    assert run_cli("--as", "van", "join", "general", cwd=tmp_path)[0] == 0
    member = json.loads(run_cli("--as", "van", "whoami", "--json", cwd=tmp_path)[1])
    queue = Queue("general", db_path=str(tmp_path / ".taut.db"))
    try:
        queue.write(
            encode_envelope(
                from_id=member["member_id"],
                from_name="evil\x1b",
                kind="message",
                text=r"literal\slash",
            )
        )
    finally:
        queue.close()

    rc, human, err = run_cli("log", "general", cwd=tmp_path)

    assert rc == 0, err
    assert r"evil\x1b" in human
    assert r"evil\x5cx1b" not in human
    assert r"literal\x5cslash" in human


def test_cli_notification_actor_thread_and_foreign_raw_are_human_safe_json_exact(
    tmp_path: Path,
) -> None:
    assert run_cli("init", cwd=tmp_path)[0] == 0
    assert run_cli("--as", "bob", "join", "general", cwd=tmp_path)[0] == 0
    bob = json.loads(run_cli("--as", "bob", "whoami", "--json", cwd=tmp_path)[1])
    actor = "actor\x1b]0;title\x07"
    thread = "general\x9b[31m\nrow"
    foreign = "foreign notice\x1b]52;c;Y2xpcGJvYXJk\x07\r\t"
    known = json.dumps(
        {
            "type": "reply",
            "to_id": bob["member_id"],
            "actor_id": "m_" + "a" * 26,
            "actor_name": actor,
            "thread": thread,
            "message_ts": 1_785_000_000_000_000_001,
        }
    )
    inbox_name = addressing.notification_queue_name(bob["member_id"])

    def seed() -> None:
        inbox = Queue(inbox_name, db_path=str(tmp_path / ".taut.db"))
        try:
            inbox.write(known)
            inbox.write(foreign)
        finally:
            inbox.close()

    seed()
    rc, human, err = run_cli("--as", "bob", "inbox", cwd=tmp_path)
    assert rc == 0, err
    assert r"actor\x1b]0;title\a" in human
    assert r"general\x9b[31m\nrow" in human
    assert r"foreign notice\x1b]52;c;Y2xpcGJvYXJk\a\r\t" in human
    _assert_only_structural_newlines(human + "\n" + err)

    seed()
    rc, encoded, err = run_cli("--as", "bob", "inbox", "--json", cwd=tmp_path)
    assert rc == 0, err
    records = [json.loads(line) for line in encoded.splitlines()]
    reply = next(record for record in records if record["type"] == "reply")
    raw = next(record for record in records if record["type"] == "foreign")
    assert reply["actor_name"] == actor
    assert reply["thread"] == thread
    assert raw["raw"] == foreign


def test_init_database_target_is_escaped_only_for_humans() -> None:
    # Exercise the renderer directly because Windows rejects control characters
    # in filenames. The CLI's explicit-target integration is covered with valid
    # paths below and elsewhere in this module.
    controlled = "db\x1b]0;title\x07\t.sqlite"
    result = InitResult(db=controlled, created=True)
    human_stream = StringIO()

    _emit_init(
        result,
        json_output=False,
        quiet=False,
        stdout=human_stream,
    )

    human = human_stream.getvalue()
    assert r"db\x1b]0;title\a\t.sqlite" in human
    _assert_only_structural_newlines(human)

    json_stream = StringIO()
    _emit_init(
        result,
        json_output=True,
        quiet=False,
        stdout=json_stream,
    )
    assert json.loads(json_stream.getvalue())["db"] == controlled


@pytest.mark.parametrize(
    "codepoint",
    range(0x20),
    ids=lambda codepoint: f"U+{codepoint:04X}",
)
def test_windows_sqlite_target_validation_rejects_every_control(
    codepoint: int,
) -> None:
    with pytest.raises(
        TautError,
        match="invalid SQLite database path on Windows: control characters",
    ):
        _validate_sqlite_path(
            Path(f"db{chr(codepoint)}.sqlite"),
            platform="nt",
        )


def test_posix_sqlite_target_validation_preserves_control_bearing_paths() -> None:
    _validate_sqlite_path(
        Path("db\x00\x07\t\x1f.sqlite"),
        platform="posix",
    )


@pytest.mark.skipif(os.name != "nt", reason="Windows filename contract")
def test_cli_windows_control_bearing_database_target_fails_fast(
    tmp_path: Path,
) -> None:
    controlled = tmp_path / "db\x1b]0;title\x07\t.sqlite"

    rc, out, err = run_cli(
        "--db",
        str(controlled),
        "init",
        cwd=tmp_path,
        timeout=10.0,
    )

    assert rc == 1
    assert out == ""
    assert err == (
        "invalid SQLite database path on Windows: control characters are not allowed"
    )
    assert not controlled.exists()


def test_cli_persona_is_escaped_only_for_humans(tmp_path: Path) -> None:
    controlled = tmp_path / "controlled.sqlite"
    persona = "builder\noperator\x1b]52;c;Y2xpcGJvYXJk\x07\x9b"

    rc, human, err = run_cli("--db", str(controlled), "init", cwd=tmp_path)
    assert rc == 0, err
    assert str(controlled) in human

    assert (
        run_cli(
            "--db",
            str(controlled),
            "--as",
            "van",
            "join",
            "general",
            "--persona",
            persona,
            cwd=tmp_path,
        )[0]
        == 0
    )
    rc, human, err = run_cli(
        "--db", str(controlled), "--as", "van", "whoami", cwd=tmp_path
    )
    assert rc == 0, err
    assert r"builder\noperator\x1b]52;c;Y2xpcGJvYXJk\a\x9b" in human
    _assert_only_structural_newlines(human)

    rc, encoded, err = run_cli(
        "--db",
        str(controlled),
        "--as",
        "van",
        "whoami",
        "--json",
        cwd=tmp_path,
    )
    assert rc == 0, err
    assert json.loads(encoded)["persona"] == persona


def test_cli_human_output_inherits_project_terminal_policy(
    tmp_path: Path,
) -> None:
    persona = "MARK\x1b"
    _write_terminal_project_config(
        tmp_path,
        escape_patterns=("MARK",),
    )

    assert run_cli("init", cwd=tmp_path)[0] == 0
    assert (
        run_cli(
            "--as",
            "van",
            "join",
            "general",
            "--persona",
            persona,
            cwd=tmp_path,
        )[0]
        == 0
    )

    rc, human, err = run_cli("--as", "van", "whoami", cwd=tmp_path)
    assert rc == 0, err
    assert r"\x4d\x41\x52\x4b\x1b" in human
    assert "MARK" not in human
    _assert_only_structural_newlines(human)

    rc, encoded, err = run_cli(
        "--as",
        "van",
        "whoami",
        "--json",
        cwd=tmp_path,
    )
    assert rc == 0, err
    assert json.loads(encoded)["persona"] == persona


def test_project_terminal_policy_applies_with_explicit_database_path(
    tmp_path: Path,
) -> None:
    _write_terminal_project_config(
        tmp_path,
        escape_patterns=("MARK",),
        target="unused.db",
    )
    explicit_db = tmp_path / "MARK.db"

    rc, human, err = run_cli("--db", explicit_db, "init", cwd=tmp_path)

    assert rc == 0, err
    assert explicit_db.exists()
    assert r"\x4d\x41\x52\x4b.db" in human
    assert "MARK.db" not in human


def test_project_terminal_policy_applies_with_taut_db_selector(
    tmp_path: Path,
) -> None:
    _write_terminal_project_config(
        tmp_path,
        escape_patterns=("MARK",),
        target="unused.db",
    )
    env_db = tmp_path / "MARK-env.db"

    rc, human, err = run_cli(
        "init",
        cwd=tmp_path,
        env={"TAUT_DB": str(env_db)},
    )

    assert rc == 0, err
    assert env_db.exists()
    assert r"\x4d\x41\x52\x4b-env.db" in human
    assert "MARK-env.db" not in human


def test_invalid_project_terminal_policy_preflights_human_commands_only(
    tmp_path: Path,
) -> None:
    _write_terminal_project_config(
        tmp_path,
        escape_patterns=("[",),
        target="unused.db",
    )
    human_db = tmp_path / "human.db"

    rc, human, err = run_cli("--db", human_db, "init", cwd=tmp_path)

    assert rc == 1
    assert human == ""
    assert err == "terminal output policy is unavailable"
    assert not human_db.exists()

    json_db = tmp_path / "json.db"
    rc, encoded, err = run_cli(
        "--json",
        "--db",
        json_db,
        "init",
        cwd=tmp_path,
    )
    assert rc == 0, err
    assert json.loads(encoded)["db"] == str(json_db)
    assert json_db.exists()


def test_data_dependent_policy_failure_is_not_a_command_load_error(
    tmp_path: Path,
) -> None:
    _write_terminal_project_config(
        tmp_path,
        escape_patterns=(r"(?=P)",),
    )

    rc, out, err = run_cli("--as", "van", "say", "general", "hello", cwd=tmp_path)

    assert rc == 1
    assert out == ""
    assert err == "terminal output policy is unavailable"
    assert "failed to load" not in err


def test_post_commit_policy_failure_does_not_roll_back_sent_message(
    tmp_path: Path,
) -> None:
    assert run_cli("init", cwd=tmp_path)[0] == 0
    assert run_cli("--as", "van", "join", "general", cwd=tmp_path)[0] == 0
    _write_terminal_project_config(
        tmp_path,
        escape_patterns=(r"(?=\d{19})",),
    )

    rc, out, err = run_cli(
        "--as",
        "van",
        "--timestamps",
        "say",
        "general",
        "committed before render failure",
        cwd=tmp_path,
    )

    assert rc == 1
    assert out == ""
    assert err == "terminal output policy is unavailable"

    rc, encoded, err = run_cli("log", "general", "--json", cwd=tmp_path)
    assert rc == 0, err
    assert "committed before render failure" in [
        json.loads(line)["text"] for line in encoded.splitlines()
    ]


def test_core_human_renderer_inventory_escapes_every_dynamic_model_field() -> None:
    from types import SimpleNamespace

    from taut.client import InitResult, Member, Notification, TautClient, Thread
    from taut.commands._rendering import (
        emit_created_member,
        emit_init,
        emit_members,
        emit_messages,
        emit_notification_warnings,
        emit_notifications,
        emit_renamed_thread,
        emit_threads,
    )

    probe = "value\x1b]52;c;Y2xpcGJvYXJk\x07\x9b\r\b\t\nrow"
    escaped = r"value\x1b]52;c;Y2xpcGJvYXJk\a\x9b\r\b\t\nrow"
    member = Member(
        member_id="m_" + "a" * 26,
        name=probe,
        aliases=(),
        kind=probe,
        presence=probe,
        last_active_ts=1,
        persona=probe,
        token=probe,
        explain={probe: probe},
    )
    message = Message(
        thread=probe,
        ts=1_785_000_000_000_000_001,
        from_id=member.member_id,
        from_name=probe,
        kind="message",
        text=probe,
        warning=probe,
    )
    thread = Thread(
        name=probe,
        parent=None,
        unread=True,
        last_ts=message.ts,
        unread_count=4,
        display_name=probe,
    )
    notification = Notification(
        type="reply",
        to_id=member.member_id,
        actor_id=member.member_id,
        actor_name=probe,
        thread=probe,
        message_ts=message.ts,
        warning=probe,
    )
    foreign = Notification(
        type="foreign",
        to_id=None,
        actor_id=None,
        actor_name=None,
        thread=None,
        message_ts=None,
        raw=probe,
    )
    client = cast(
        TautClient,
        SimpleNamespace(
            last_created_member=member,
            last_candidates=[(probe, [probe])],
            last_notification_warnings=[probe],
        ),
    )
    stdout = StringIO()
    stderr = StringIO()

    emit_init(
        InitResult(db=probe, created=True),
        json_output=False,
        quiet=False,
        stdout=stdout,
    )
    emit_created_member(
        client,
        json_output=False,
        quiet=False,
        stdout=stdout,
        stderr=stderr,
    )
    emit_notification_warnings(client, quiet=False, stderr=stderr)
    emit_messages(
        [message],
        json_output=False,
        timestamps=False,
        quiet=False,
        stdout=stdout,
        stderr=stderr,
    )
    emit_members([member], json_output=False, quiet=False, stdout=stdout)
    emit_threads([thread], json_output=False, quiet=False, stdout=stdout)
    emit_notifications(
        [notification, foreign],
        client=None,
        json_output=False,
        quiet=False,
        stdout=stdout,
        stderr=stderr,
    )
    emit_renamed_thread(
        thread,
        old_name=probe,
        json_output=False,
        quiet=False,
        stdout=stdout,
    )

    rendered = stdout.getvalue() + stderr.getvalue()
    assert rendered.count(escaped) >= 18
    _assert_only_structural_newlines(rendered)

    json_output = StringIO()
    emit_messages(
        [message],
        json_output=True,
        timestamps=False,
        quiet=False,
        stdout=json_output,
        stderr=StringIO(),
    )
    emit_members([member], json_output=True, quiet=False, stdout=json_output)
    emit_threads([thread], json_output=True, quiet=False, stdout=json_output)
    emit_notifications(
        [notification, foreign],
        client=None,
        json_output=True,
        quiet=False,
        stdout=json_output,
        stderr=StringIO(),
    )
    records = [json.loads(line) for line in json_output.getvalue().splitlines()]
    assert records[0]["text"] == probe
    assert records[1]["persona"] == probe
    assert records[1]["explain"] == {probe: probe}
    assert records[2]["thread"] == probe
    assert records[3]["actor_name"] == probe
    assert records[4]["raw"] == probe


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


def test_cli_usage_error_unknown_root_option_exits_1(tmp_path: Path) -> None:
    rc, out, err = run_cli("--wat", "whoami", cwd=tmp_path)

    assert rc == 1
    assert out == ""
    assert "unrecognized root option: --wat" in err
    assert "Traceback" not in err


def test_cli_missing_root_value_exits_1_without_traceback(tmp_path: Path) -> None:
    rc, out, err = run_cli("--db", cwd=tmp_path)

    assert rc == 1
    assert out == ""
    assert "argument --db" in err
    assert "Traceback" not in err


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


def test_cli_short_help_and_preverb_long_abbreviation_remain_accepted(
    tmp_path: Path,
) -> None:
    rc, out, err = run_cli("-h", cwd=tmp_path)
    assert rc == 0, err
    assert out.startswith("usage: taut ")

    assert run_cli("init", cwd=tmp_path)[0] == 0
    assert run_cli("--as", "van", "join", "general", cwd=tmp_path)[0] == 0
    rc, out, err = run_cli("--timest", "log", "general", cwd=tmp_path)
    assert rc == 0, err
    assert re.search(r"\d{19}", out)


def test_cli_post_verb_globals_are_exact_but_local_abbreviations_remain(
    tmp_path: Path,
) -> None:
    rc, out, err = run_cli("join", "general", "--tok", "continuity-token", cwd=tmp_path)
    assert rc == 1
    assert out == ""
    assert "unrecognized" in err

    assert run_cli("init", cwd=tmp_path)[0] == 0
    rc, out, err = run_cli("--as", "van", "join", "general", "--json", cwd=tmp_path)
    assert rc == 0, err
    token = json.loads(out.splitlines()[0])["token"]
    rc, out, err = run_cli("rejoin", "--t", token, "--json", cwd=tmp_path)
    assert rc == 0, err
    assert json.loads(out)["name"] == "van"


@pytest.mark.parametrize(
    ("args", "error_fragment"),
    [
        (("--",), "usage: taut"),
        (("--", "say"), "usage: taut say"),
        (("--", "summon"), "usage: taut summon"),
    ],
)
def test_cli_root_separator_selects_later_verb_and_preserves_tail_boundary(
    tmp_path: Path,
    args: tuple[str, ...],
    error_fragment: str,
) -> None:
    rc, out, err = run_cli(*args, cwd=tmp_path, stdin="")

    assert rc == 1
    assert out == ""
    assert error_fragment in err
    assert "Traceback" not in err


def test_cli_no_subcommand_prints_help_to_stderr_and_exits_1(
    tmp_path: Path,
) -> None:
    rc, out, err = run_cli(cwd=tmp_path)

    assert rc == 1
    assert out == ""
    assert "usage:" in err
    folded = " ".join(err.split())
    assert "0 success" in folded
    assert "2 empty" in folded


def test_main_explicit_empty_argv_does_not_fall_back_to_process_argv(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(sys, "argv", ["taut", "--version"])

    assert cli.main([]) == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "usage:" in captured.err


def test_every_cli_parser_action_has_useful_help() -> None:
    from taut.commands._dispatch import _build_command_parser, _load_command
    from taut.commands._registry import CommandRegistry

    pending: list[argparse.ArgumentParser] = []
    for selected in CommandRegistry(entry_points=()).commands():
        assert selected.spec is not None
        pending.append(
            _build_command_parser(
                selected.spec,
                _load_command(selected),
                StringIO(),
                StringIO(),
                escape_description=True,
            )
        )
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
            (
                "continuity",
                "not authentication",
                "errors remain text on stderr",
                "0 success",
                "1 error",
                "2 empty",
            ),
        ),
        (
            ("say", "--help"),
            ("stdin", "TEXT", "-"),
        ),
        (
            ("reply", "--help"),
            ("19-digit", "suffix", "at least 4", "stdin"),
        ),
        (
            ("log", "--help"),
            ("ISO 8601", "unix", "19-digit", "most recent"),
        ),
    ],
)
def test_cli_help_exposes_load_bearing_contracts(
    tmp_path: Path,
    args: tuple[str, ...],
    phrases: tuple[str, ...],
) -> None:
    rc, out, err = run_cli(*args, cwd=tmp_path)

    assert rc == 0, err
    folded = " ".join(out.lower().split())
    for phrase in phrases:
        assert phrase.lower() in folded


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


def test_cli_human_list_labels_dm_by_other_current_name(tmp_path: Path) -> None:
    assert run_cli("init", cwd=tmp_path)[0] == 0
    assert run_cli("--as", "van", "join", "general", cwd=tmp_path)[0] == 0
    assert run_cli("--as", "bob", "join", "general", cwd=tmp_path)[0] == 0
    assert run_cli("--as", "van", "say", "@bob", "hi", cwd=tmp_path)[0] == 0

    rc, out, err = run_cli("--as", "van", "list", "--all", cwd=tmp_path)

    assert rc == 0, err
    assert "DM with bob" in out
    assert "dm.d_" not in out


def test_cli_human_list_dm_with_bad_participants_uses_explicit_fallback(
    tmp_path: Path,
) -> None:
    assert run_cli("init", cwd=tmp_path)[0] == 0
    assert run_cli("--as", "van", "join", "general", cwd=tmp_path)[0] == 0
    assert run_cli("--as", "bob", "join", "general", cwd=tmp_path)[0] == 0
    out = run_cli("--as", "van", "say", "@bob", "hi", "--json", cwd=tmp_path)[1]
    thread = json.loads(out)["thread"]
    meta = Queue(META_QUEUE_NAME, db_path=str(tmp_path / ".taut.db"))
    try:
        with meta.sidecar(transaction=True) as session:
            session.run(
                "UPDATE taut_threads SET meta = ? WHERE name = ?",
                ('{"members":["missing"]}', thread),
            )
    finally:
        meta.close()

    rc, out, err = run_cli("--as", "van", "list", "--all", cwd=tmp_path)

    assert rc == 0, err
    assert f"DM {thread} (participants unavailable)" in out


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


def test_cli_human_mention_uses_shortest_working_reply_suffix(
    tmp_path: Path,
) -> None:
    assert run_cli("init", cwd=tmp_path)[0] == 0
    assert run_cli("--as", "van", "join", "general", cwd=tmp_path)[0] == 0
    assert run_cli("--as", "bob", "join", "general", cwd=tmp_path)[0] == 0
    source_ts = _say_ts(tmp_path, "van", "general", "hello @bob")
    full_id = str(source_ts)
    ids = [str(value) for value in _log_ts_values(tmp_path, "general")]
    expected_suffix = next(
        full_id[-length:]
        for length in range(4, len(full_id) + 1)
        if sum(candidate.endswith(full_id[-length:]) for candidate in ids) == 1
    )

    rc, out, err = run_cli("--as", "bob", "inbox", cwd=tmp_path)

    assert rc == 0, err
    assert "taut log general" in out
    assert f"taut reply general {expected_suffix}" in out
    assert (
        run_cli(
            "--as",
            "bob",
            "reply",
            "general",
            expected_suffix,
            "works",
            cwd=tmp_path,
        )[0]
        == 0
    )


def test_cli_human_mention_omits_reply_action_after_recipient_leaves(
    tmp_path: Path,
) -> None:
    assert run_cli("init", cwd=tmp_path)[0] == 0
    assert run_cli("--as", "van", "join", "general", cwd=tmp_path)[0] == 0
    assert run_cli("--as", "bob", "join", "general", cwd=tmp_path)[0] == 0
    _say_ts(tmp_path, "van", "general", "hello @bob")
    assert run_cli("--as", "bob", "leave", "general", cwd=tmp_path)[0] == 0

    rc, out, err = run_cli("--as", "bob", "inbox", cwd=tmp_path)

    assert rc == 0, err
    assert "taut log general" in out
    assert "taut reply" not in out
    assert run_cli("--as", "bob", "log", "general", cwd=tmp_path)[0] == 0


def test_cli_human_dm_mention_offers_log_but_not_invalid_reply(
    tmp_path: Path,
) -> None:
    assert run_cli("init", cwd=tmp_path)[0] == 0
    assert run_cli("--as", "van", "join", "general", cwd=tmp_path)[0] == 0
    assert run_cli("--as", "bob", "join", "general", cwd=tmp_path)[0] == 0
    sent = run_cli("--as", "van", "say", "@bob", "hello @bob", "--json", cwd=tmp_path)
    dm_thread = json.loads(sent[1])["thread"]

    rc, out, err = run_cli("--as", "bob", "inbox", cwd=tmp_path)

    assert rc == 0, err
    assert "inspect: taut read" in out
    assert f"taut reply {dm_thread}" not in out
    assert run_cli("--as", "bob", "read", cwd=tmp_path)[0] == 0


def test_cli_human_subthread_mention_offers_log_but_not_invalid_reply(
    tmp_path: Path,
) -> None:
    assert run_cli("init", cwd=tmp_path)[0] == 0
    assert run_cli("--as", "van", "join", "general", cwd=tmp_path)[0] == 0
    assert run_cli("--as", "bob", "join", "general", cwd=tmp_path)[0] == 0
    root_ts = _say_ts(tmp_path, "van", "general", "root")
    assert (
        run_cli("--as", "bob", "reply", "general", root_ts, "answer", cwd=tmp_path)[0]
        == 0
    )
    child = f"general.{root_ts}"
    assert run_cli("--as", "van", "read", child, cwd=tmp_path)[0] == 0
    assert run_cli("--as", "van", "say", child, "ping @bob", cwd=tmp_path)[0] == 0

    rc, out, err = run_cli("--as", "bob", "inbox", cwd=tmp_path)

    assert rc == 0, err
    assert f"taut log {child}" in out
    assert f"taut reply {child}" not in out
    assert run_cli("--as", "bob", "log", child, cwd=tmp_path)[0] == 0


def test_cli_human_mention_uses_full_id_when_all_short_suffixes_collide(
    tmp_path: Path,
) -> None:
    assert run_cli("init", cwd=tmp_path)[0] == 0
    assert run_cli("--as", "van", "join", "general", cwd=tmp_path)[0] == 0
    assert run_cli("--as", "bob", "join", "general", cwd=tmp_path)[0] == 0
    van = json.loads(run_cli("--as", "van", "whoami", "--json", cwd=tmp_path)[1])
    bob = json.loads(run_cli("--as", "bob", "whoami", "--json", cwd=tmp_path)[1])
    first_ts = 1_000_000_000_000_004_321
    second_ts = 2_000_000_000_000_004_321
    queue = Queue("general", db_path=str(tmp_path / ".taut.db"))
    inbox = Queue(
        addressing.notification_queue_name(bob["member_id"]),
        db_path=str(tmp_path / ".taut.db"),
    )
    try:
        queue.insert_messages(
            [
                (
                    encode_envelope(
                        from_id=van["member_id"],
                        from_name="van",
                        kind="message",
                        text=text,
                    ),
                    timestamp,
                )
                for text, timestamp in (
                    ("first collision", first_ts),
                    ("second collision", second_ts),
                )
            ]
        )
        inbox.write(
            json.dumps(
                {
                    "type": "mention",
                    "to_id": bob["member_id"],
                    "actor_id": van["member_id"],
                    "actor_name": "van",
                    "thread": "general",
                    "message_ts": first_ts,
                    "matched": "@bob",
                }
            )
        )
    finally:
        queue.close()
        inbox.close()

    rc, out, err = run_cli("--as", "bob", "inbox", cwd=tmp_path)

    assert rc == 0, err
    assert f"taut reply general {first_ts}" in out
    assert (
        run_cli(
            "--as",
            "bob",
            "reply",
            "general",
            str(first_ts),
            "full id works",
            cwd=tmp_path,
        )[0]
        == 0
    )


def test_cli_human_reply_notification_renders_membership_independent_log_action(
    tmp_path: Path,
) -> None:
    assert run_cli("init", cwd=tmp_path)[0] == 0
    assert run_cli("--as", "van", "join", "general", cwd=tmp_path)[0] == 0
    assert run_cli("--as", "bob", "join", "general", cwd=tmp_path)[0] == 0
    root_out = run_cli("--as", "van", "say", "general", "root", "--json", cwd=tmp_path)[
        1
    ]
    root_ts = json.loads(root_out)["ts"]
    assert (
        run_cli("--as", "bob", "reply", "general", root_ts, "answer", cwd=tmp_path)[0]
        == 0
    )

    rc, out, err = run_cli("--as", "van", "inbox", cwd=tmp_path)

    child = f"general.{root_ts}"
    assert rc == 0, err
    assert re.search(r"\b\d\d:\d\d\b", out)
    assert f"taut log {child}" in out
    assert run_cli("--as", "van", "log", child, cwd=tmp_path)[0] == 0

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
    assert "usage: taut reply THREAD MSG_ID [TEXT|-]" in err
    assert "at least 4 digits" in err


def test_cli_reply_too_short_suffix_names_usage_and_minimum(tmp_path: Path) -> None:
    assert run_cli("init", cwd=tmp_path)[0] == 0
    assert run_cli("--as", "van", "join", "general", cwd=tmp_path)[0] == 0

    rc, out, err = run_cli(
        "--as", "van", "reply", "general", "123", "child", cwd=tmp_path
    )

    assert rc == 2
    assert out == ""
    assert "message id suffix must be at least 4 digits" in err
    assert "usage: taut reply THREAD MSG_ID [TEXT|-]" in err


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


def test_cli_watch_json_flushes_records_while_live(tmp_path: Path) -> None:
    """[TAUT-8.1] watch flushes message and notification NDJSON while live."""

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

        assert (
            run_cli("--as", "bob", "say", "general", "@van ping", cwd=tmp_path)[0] == 0
        )

        seen_message = False
        seen_notification = False
        for _ in range(60):  # bounded wait: 60 * 0.5s
            try:
                line = lines.get(timeout=0.5)
            except queue_module.Empty:
                continue
            item = json.loads(line)
            if item.get("text") == "@van ping":
                seen_message = True
            if item.get("type") == "mention":
                seen_notification = True
            if seen_message and seen_notification:
                break
        assert seen_message, "watch did not flush the message while still live"
        assert seen_notification, (
            "watch did not flush the notification while still live"
        )

        if os.name == "nt":
            proc.terminate()
            proc.wait(timeout=10)
        else:
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


def test_cli_watch_policy_failure_stops_without_advancing_cursor(
    tmp_path: Path,
) -> None:
    """[TAUT-6.4, TAUT-8.4] Policy failure is a terminal delivery failure."""

    assert run_cli("init", cwd=tmp_path)[0] == 0
    assert run_cli("--as", "van", "join", "general", cwd=tmp_path)[0] == 0
    assert run_cli("--as", "bob", "join", "general", cwd=tmp_path)[0] == 0
    assert run_cli("--as", "van", "read", "general", "--json", cwd=tmp_path)[0] == 0
    bob = json.loads(run_cli("--as", "bob", "whoami", "--json", cwd=tmp_path)[1])
    _write_terminal_project_config(
        tmp_path,
        escape_patterns=(r"(?=TRIGGER)",),
    )

    proc = subprocess.Popen(
        [sys.executable, "-m", "taut", "--as", "van", "watch"],
        cwd=tmp_path,
        env=build_cli_env(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    queue = Queue("general", db_path=str(tmp_path / ".taut.db"))
    try:
        queue.write(
            encode_envelope(
                from_id=bob["member_id"],
                from_name="bob",
                kind="message",
                text="TRIGGER policy failure",
            )
        )
        stdout, stderr = proc.communicate(timeout=10)
    finally:
        queue.close()
        if proc.poll() is None:
            proc.kill()
        proc.wait(timeout=10)

    assert proc.returncode == 1
    assert stderr == "terminal output policy is unavailable\n"
    assert "Traceback" not in stdout + stderr

    rc, unread, err = run_cli("--as", "van", "read", "general", "--json", cwd=tmp_path)
    assert rc == 0, err
    assert "TRIGGER policy failure" in [
        json.loads(line)["text"] for line in unread.splitlines()
    ]


@pytest.mark.skipif(
    os.name == "nt",
    reason="closing the parent read fd is a POSIX pipe contract probe",
)
def test_cli_watch_closed_pipe_exits_0_without_advancing_cursor(
    tmp_path: Path,
) -> None:
    """[TAUT-8.4] EPIPE is terminal sink failure, never poison content."""

    assert run_cli("init", cwd=tmp_path)[0] == 0
    assert run_cli("--as", "van", "join", "general", cwd=tmp_path)[0] == 0
    assert run_cli("--as", "bob", "join", "general", cwd=tmp_path)[0] == 0
    assert run_cli("--as", "van", "read", "general", cwd=tmp_path)[0] == 0
    assert run_cli("--as", "van", "read", "general", cwd=tmp_path)[0] == 2

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
    published_ids: list[int] = []
    try:
        assert proc.stdout is not None
        proc.stdout.close()
        assert proc.poll() is None

        for index in range(4):
            body = f"closed-pipe-{index}-" + ("x" * 20_000)
            rc, out, err = run_cli(
                "--as",
                "bob",
                "say",
                "general",
                "-",
                "--json",
                cwd=tmp_path,
                stdin=body,
            )
            assert rc == 0, err
            published_ids.append(int(json.loads(out)["ts"]))

        assert proc.wait(timeout=10) == 0
        assert proc.stderr is not None
        stderr = proc.stderr.read()
        assert "Traceback" not in stderr
        assert "BrokenPipeError" not in stderr

        rc, out, err = run_cli("--as", "van", "read", "general", "--json", cwd=tmp_path)
        assert rc == 0, err
        unread_ids = {int(json.loads(line)["ts"]) for line in out.splitlines()}
        assert unread_ids.issuperset(published_ids)
    finally:
        if proc.poll() is None:
            proc.kill()
        proc.wait(timeout=10)
        if proc.stderr is not None:
            proc.stderr.close()


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


def test_cli_join_new_refuses_occupied_explicit_name(tmp_path: Path) -> None:
    """[IAN-3.3]: CLI ``join --new`` fails-not-adopts on an occupied name."""

    assert run_cli("init", cwd=tmp_path)[0] == 0
    assert run_cli("--as", "van", "join", "general", cwd=tmp_path)[0] == 0

    rc, out, err = run_cli("--as", "van", "join", "general", "--new", cwd=tmp_path)

    assert rc == 1
    assert out == ""
    assert "member name already exists: van" in err
    assert "Traceback" not in err

    rc, out, err = run_cli("who", "--json", cwd=tmp_path)
    assert rc == 0, err
    vans = [obj for obj in map(json.loads, out.splitlines()) if obj["name"] == "van"]
    assert len(vans) == 1


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


# --- summon/dismiss delegation verbs ([TAUT-8.1] D4, spec 04 [SUM-3]) ------
#
# The presence-path tests below require the taut-summon extension in the
# dev environment (root dev extra + [tool.uv.sources]); reaching the
# extension's S2 skeleton messages proves the argv round-trip through
# core's delegation.


def test_cli_summon_delegates_argv_to_extension(tmp_path: Path) -> None:
    # An unknown provider token: 'claude' resolves to a real adapter since
    # S5, so the round-trip proof rides the unknown-adapter error path.
    rc, out, err = run_cli("summon", "zz-unknown", cwd=tmp_path)

    assert rc == 1
    assert "no adapter named 'zz-unknown'" in err
    assert out == ""


def test_cli_summon_provider_flag_round_trips_to_extension(tmp_path: Path) -> None:
    # --provider is not a core flag: seeing it change Summon's resolution
    # proves the selected compatibility or native adapter received the tail.
    rc, _out, err = run_cli(
        "summon", "reviewer", "--provider", "zz-unknown", "dev", cwd=tmp_path
    )

    assert rc == 1
    assert "no adapter named 'zz-unknown'" in err


def test_cli_summon_db_after_subcommand_reaches_extension(tmp_path: Path) -> None:
    # The extension echoes the db it parsed on this error path; a dropped
    # --db would still produce the generic error, so the echo is the
    # propagation proof.
    db = str(tmp_path / "x.taut.db")
    rc, _out, err = run_cli("summon", "zz-unknown", "--db", db, cwd=tmp_path)

    assert rc == 1
    assert "no adapter named 'zz-unknown'" in err
    assert f"db: {db}" in err


def test_cli_summon_db_before_subcommand_reaches_extension(tmp_path: Path) -> None:
    db = str(tmp_path / "x.taut.db")
    rc, _out, err = run_cli("--db", db, "summon", "zz-unknown", cwd=tmp_path)

    assert rc == 1
    assert "no adapter named 'zz-unknown'" in err
    assert f"db: {db}" in err


def test_cli_dismiss_db_before_verb_reaches_extension(tmp_path: Path) -> None:
    db = str(tmp_path / "x.taut.db")
    rc, _out, err = run_cli("--db", db, "dismiss", "ghost", cwd=tmp_path)

    assert rc == 2
    assert "nothing summoned as 'ghost'" in err
    assert f"db: {db}" in err


def test_cli_summon_tail_keeps_core_global_lookalikes(tmp_path: Path) -> None:
    # [SUM-3]: undeclared root-global lookalikes remain in the selected Summon
    # adapter's tail. Both the compatibility and native manifests declare only
    # `--db` post-verb. The usage error proves `--json` was not hoisted. The
    # installed-wheel matrix separately proves which owner runs per artifact
    # state; this source-tree case is intentionally owner-agnostic.
    rc, _out, err = run_cli("summon", "claude", "--json", cwd=tmp_path)

    assert rc == 1
    assert "--json" in err
    assert "no adapter named" not in err


def test_cli_summon_tail_keeps_value_option_lookalikes(tmp_path: Path) -> None:
    rc, _out, err = run_cli("summon", "claude", "--as", "bob", cwd=tmp_path)

    assert rc == 1
    assert "--as" in err
    assert "no adapter named" not in err


def test_cli_summon_double_dash_tail_passes_through_verbatim(tmp_path: Path) -> None:
    rc, _out, err = run_cli("summon", "--", "anything", cwd=tmp_path)

    assert rc == 1
    assert "no adapter named 'anything'" in err

    # Even an option-shaped token after `--` reaches the extension as a
    # positional ([TAUT-8.1]: `--` ends option parsing).
    rc, _out, err = run_cli("summon", "--", "-q", cwd=tmp_path)

    assert rc == 1
    assert "no adapter named '-q'" in err


def test_cli_dismiss_maps_to_extension_stop(tmp_path: Path) -> None:
    rc, out, err = run_cli("dismiss", "claude", cwd=tmp_path)

    assert rc == 2
    assert "nothing summoned" in err
    assert out == ""


def test_cli_summon_without_extension_exits_1_with_install_hint(
    tmp_path: Path,
) -> None:
    # Absence path via a real subprocess: `-S` disables site processing and
    # PYTHONPATH names only the core checkout. Do not add site-packages here:
    # official Summon entry-point metadata without its importable package is a
    # broken installation, which must not fall back to the absence hint.
    # Lazy core command selection needs no third-party runtime dependency for
    # this path. No import mocking anywhere.
    env = os.environ.copy()
    env.pop("PYTHONHOME", None)
    env["PYTHONPATH"] = str(PROJECT_ROOT)
    env["PYTHONIOENCODING"] = "utf-8"

    probe = subprocess.run(
        [
            sys.executable,
            "-S",
            "-c",
            "import importlib.util; import sys; "
            "sys.exit(3 if importlib.util.find_spec('taut_summon') else 0)",
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert probe.returncode == 0, "guard: taut_summon still importable under -S"

    completed = subprocess.run(
        [sys.executable, "-S", "-m", "taut", "summon", "claude"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
    )

    assert completed.returncode == 1, completed.stderr
    assert "taut summon requires the taut-summon extension" in completed.stderr
    assert "pipx inject taut taut-summon" in completed.stderr
    assert completed.stdout == ""
