from __future__ import annotations

import json
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path

import pytest

import taut.identity as identity
from taut._exceptions import EmptyResultError, MembershipError
from taut.client import Message, Notification, TautClient
from tests.conftest import build_cli_env, run_cli

pytestmark = pytest.mark.shared


def _wait_until(predicate: Callable[[], bool], *, timeout: float = 3.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("condition was not satisfied before timeout")


def _spawn_cli(cwd: Path, *args: object) -> subprocess.Popen[str]:
    return subprocess.Popen(
        [sys.executable, "-m", "taut", *map(str, args)],
        cwd=cwd,
        env=build_cli_env(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def _agent_capture(*, pid: int, start_time: str) -> identity.IdentityCapture:
    process = identity.ProcessInfo(
        pid=pid,
        ppid=None,
        start_time=start_time,
        exe="/usr/bin/codex",
        argv=("codex",),
        uid=1000,
        cwd="/workspace",
    )
    return identity.IdentityCapture(
        chain=(process,),
        host=identity.HostIdentity("host:test", "test-host"),
        uid=1000,
        login="tester",
        anchor=process,
        kind="agent",
        rule="test capture",
    )


def test_project_client_join_say_read_contract(taut_project: Path) -> None:
    result = TautClient.init()
    van = TautClient(as_name="van")
    bob = TautClient(as_name="bob")

    van.join("general")
    bob.join("general")
    message = van.say("general", "shared hello")

    assert result.db
    assert message.thread == "general"
    assert [item.text for item in bob.read("general")][-1:] == ["shared hello"]


def test_project_reply_creates_subthread_contract(taut_project: Path) -> None:
    TautClient.init()
    van = TautClient(as_name="van")
    bob = TautClient(as_name="bob")
    van.join("general")
    bob.join("general")
    root = van.say("general", "root")

    reply = bob.reply("general", str(root.ts), "threaded shared reply")

    assert reply.thread == f"general.{root.ts}"
    assert [message.text for message in van.log(reply.thread)] == [
        "threaded shared reply"
    ]
    child = next(
        thread
        for thread in van.list_threads(all_threads=True)
        if thread.name == reply.thread
    )
    assert child.parent == "general"


def test_project_leave_removes_membership_contract(taut_project: Path) -> None:
    TautClient.init()
    van = TautClient(as_name="van")
    bob = TautClient(as_name="bob")
    van.join("general")
    bob.join("general")

    left = bob.leave("general")

    assert left.text == "bob left"
    assert [member.name for member in van.who("general")] == ["van"]
    with pytest.raises(MembershipError):
        bob.say("general", "should fail after leave")


def test_project_rejoin_updates_anchor_contract(taut_project: Path) -> None:
    TautClient.init()
    old_capture = _agent_capture(pid=1001, start_time="old-start")
    new_capture = _agent_capture(pid=2002, start_time="new-start")
    TautClient(as_name="codex", identity_capture=old_capture).join("general")

    rejoined = TautClient(identity_capture=new_capture).rejoin("codex")

    assert rejoined.name == "codex"
    assert TautClient(identity_capture=new_capture).whoami().name == "codex"
    assert TautClient(identity_capture=old_capture).whoami().name == "codex"


def test_project_list_reports_unread_contract(taut_project: Path) -> None:
    TautClient.init()
    van = TautClient(as_name="van")
    bob = TautClient(as_name="bob")
    van.join("general")
    bob.join("general")
    bob.say("general", "unread shared message")

    threads = van.list_threads()

    assert [
        (thread.name, thread.unread, thread.unread_count) for thread in threads
    ] == [("general", True, 2)]
    assert [message.text for message in van.read("general")] == [
        "bob joined",
        "unread shared message",
    ]
    with pytest.raises(EmptyResultError):
        van.list_threads()


def test_project_list_reports_newest_pending_timestamp_contract(
    taut_project: Path,
) -> None:
    TautClient.init()
    van = TautClient(as_name="van")
    bob = TautClient(as_name="bob")
    van.join("general")
    bob.join("general")
    bob.say("general", "first timestamp message")
    newest = bob.say("general", "newest timestamp message")

    listed = next(
        thread
        for thread in van.list_threads(all_threads=True)
        if thread.name == "general"
    )

    assert listed.last_ts == newest.ts
    assert "newest timestamp message" in [
        message.text for message in van.read("general")
    ]
    listed_after_read = next(
        thread
        for thread in van.list_threads(all_threads=True)
        if thread.name == "general"
    )
    assert listed_after_read.last_ts == newest.ts


def test_project_list_ignores_foreign_claimed_messages_contract(
    taut_project: Path,
) -> None:
    TautClient.init()
    van = TautClient(as_name="van")
    bob = TautClient(as_name="bob")
    van.join("general")
    bob.join("general")
    older = bob.say("general", "still pending")
    newest = bob.say("general", "foreign claimed")
    queue = van.queue("general")

    claimed = queue.read_one(exact_timestamp=newest.ts, with_timestamps=True)

    assert claimed is not None
    listed = next(
        thread
        for thread in van.list_threads(all_threads=True)
        if thread.name == "general"
    )
    assert listed.last_ts == older.ts

    while queue.read_one(with_timestamps=True) is not None:
        pass
    listed_after_all_claimed = next(
        thread
        for thread in van.list_threads(all_threads=True)
        if thread.name == "general"
    )
    assert listed_after_all_claimed.last_ts is None


def test_project_log_limit_returns_recent_chronological_contract(
    taut_project: Path,
) -> None:
    TautClient.init()
    van = TautClient(as_name="van")
    van.join("general")
    for text in ("first", "second", "third"):
        van.say("general", text)

    messages = van.log("general", limit=2)

    assert [message.text for message in messages] == ["second", "third"]


def test_project_cli_join_say_log_contract(taut_project: Path) -> None:
    assert run_cli("init", "--json", cwd=taut_project)[0] == 0
    rc, out, err = run_cli(
        "--as",
        "van",
        "join",
        "general",
        "--json",
        cwd=taut_project,
    )
    assert rc == 0, err
    assert json.loads(out.splitlines()[0])["name"] == "van"

    rc, out, err = run_cli(
        "--as",
        "van",
        "say",
        "general",
        "hello from shared cli",
        "--json",
        cwd=taut_project,
    )
    assert rc == 0, err
    assert json.loads(out)["text"] == "hello from shared cli"

    rc, out, err = run_cli("log", "general", "--json", cwd=taut_project)
    assert rc == 0, err
    assert [json.loads(line)["text"] for line in out.splitlines()] == [
        "van created #general",
        "hello from shared cli",
    ]


def test_project_watcher_receives_cli_write(taut_project: Path) -> None:
    TautClient.init()
    van = TautClient(as_name="van")
    bob = TautClient(as_name="bob")
    van.join("general")
    bob.join("general")
    seen: list[str] = []

    def record(item: Message | Notification) -> None:
        if isinstance(item, Message):
            seen.append(item.text)

    watcher = van.watch(record)
    thread = watcher.start()
    try:
        _wait_until(thread.is_alive)

        rc, out, err = run_cli(
            "--as",
            "bob",
            "say",
            "general",
            "hello from watched cli",
            "--json",
            cwd=taut_project,
        )
        assert rc == 0, err
        written = json.loads(out)

        _wait_until(lambda: "hello from watched cli" in seen)
        assert thread.is_alive()
        assert written["text"] == "hello from watched cli"
    finally:
        watcher.stop()
        thread.join(timeout=2)
        assert not thread.is_alive()


def test_project_concurrent_writers_persist_all_messages(taut_project: Path) -> None:
    TautClient.init()
    van = TautClient(as_name="van")
    van.join("general")
    for name in ("bob", "codex"):
        TautClient(as_name=name).join("general")

    target_texts = {"from bob", "from codex"}
    processes = [
        _spawn_cli(taut_project, "--as", "bob", "say", "general", "from bob"),
        _spawn_cli(taut_project, "--as", "codex", "say", "general", "from codex"),
    ]
    try:
        for process in processes:
            stdout, stderr = process.communicate(timeout=8)
            assert process.returncode == 0, stdout + stderr
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()

    messages = [
        message for message in van.log("general") if message.text in target_texts
    ]

    assert {message.text for message in messages} == target_texts
    assert {message.from_name for message in messages} == {"bob", "codex"}
    assert [message.ts for message in messages] == sorted(
        message.ts for message in messages
    )


def test_project_member_id_survives_name_change_contract(
    taut_project: Path,
) -> None:
    TautClient.init()
    van = TautClient(as_name="van")
    van.join("general")
    before = van.whoami()
    old = van.say("general", "before rename")

    renamed = van.set_name("VanL")
    new = van.say("general", "after rename")

    assert renamed.member_id == before.member_id
    assert old.from_id == new.from_id == before.member_id
    assert old.from_name == "van"
    assert new.from_name == "VanL"
    with pytest.raises(EmptyResultError):
        TautClient(as_name="van").whoami()
    assert TautClient(as_name="VanL").whoami().member_id == before.member_id


def test_project_dm_queue_stable_across_name_change_contract(
    taut_project: Path,
) -> None:
    TautClient.init()
    van = TautClient(as_name="van")
    bob = TautClient(as_name="bob")
    van.join("general")
    bob.join("general")

    first = van.say("@bob", "hi")
    bob.set_name("robert")
    second = bob.say("@van", "hello")

    assert first.thread == second.thread
    listed = next(
        thread
        for thread in van.list_threads(all_threads=True)
        if thread.name == first.thread
    )
    assert listed.kind == "dm"
    assert set(listed.members) == {van.whoami().member_id, bob.whoami().member_id}


def test_project_notifications_claim_without_touching_history_contract(
    taut_project: Path,
) -> None:
    TautClient.init()
    van = TautClient(as_name="van")
    bob = TautClient(as_name="bob")
    van.join("general")
    bob.join("general")

    written = van.say("general", "ping @bob @bob")
    notifications = bob.inbox()

    assert len(notifications) == 1
    assert notifications[0].type == "mention"
    assert notifications[0].message_ts == written.ts
    with pytest.raises(EmptyResultError):
        bob.inbox()
    assert "ping @bob @bob" in [message.text for message in bob.log("general")]


def test_project_channel_rename_moves_subthreads_contract(
    taut_project: Path,
) -> None:
    TautClient.init()
    van = TautClient(as_name="van")
    van.join("general")
    root = van.say("general", "root")
    van.reply("general", str(root.ts), "threaded")

    renamed = van.rename_channel("general", "ops")

    assert renamed.name == "ops"
    assert [message.text for message in van.log("ops")] == [
        "van created #general",
        "root",
    ]
    assert [message.text for message in van.log(f"ops.{root.ts}")] == ["threaded"]
    with pytest.raises(EmptyResultError):
        van.log("general")
