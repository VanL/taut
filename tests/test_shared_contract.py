from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, cast

import pytest
from simplebroker import Queue, dump_lines, open_broker, resolve_broker_target
from simplebroker.ext import IntegrityError, SidecarSession
from taut_summon._state import (
    LEDGER_QUEUE_NAME,
    SUMMON_SCHEMA_VERSION_KEY,
    SummonSchemaVersionError,
    ensure_summon_schema,
    get_claim,
    get_summon_schema_version,
)

import taut.state._sql as sql_state
from taut import addressing, identity
from taut._constants import META_QUEUE_NAME, load_config
from taut._exceptions import (
    BlankMessageError,
    EmptyResultError,
    MembershipError,
    NotFoundError,
    TautError,
    TokenError,
)
from taut.client import (
    Channel,
    Message,
    MessageDeletion,
    MessageReaction,
    Notification,
    TautClient,
    Thread,
)
from taut.envelope import encode_envelope
from taut.search._jobs import FAILED_QUEUE_NAME
from taut.state import SqlDialect, dialect_for_taut_target
from tests.conftest import build_cli_env, run_cli

pytestmark = pytest.mark.shared


def test_system_doctor_is_passive_and_portable_across_sql_backends(
    taut_project: Path,
) -> None:
    """[DOCT-2] [DOCT-7] Healthy and failed-work reports use real storage."""

    TautClient.init()
    config = load_config()
    target = resolve_broker_target(taut_project, config=config)
    assert target is not None
    meta_queue = Queue(META_QUEUE_NAME, db_path=target, config=config)
    try:
        state = sql_state.SqlSidecarTautState(
            meta_queue,
            dialect_for_taut_target(target),
        )
        before_meta = state.persistence_meta()
        before_records = state.persistence_records()

        healthy = TautClient.doctor()

        assert healthy.healthy is True
        assert [check.name for check in healthy.checks] == [
            "core_schema",
            "load_guard",
            "core_state",
            "broker_state",
            "extension_state",
            "search_work",
        ]
        assert healthy.db == target.display_target
        if target.backend_name == "postgres":
            assert healthy.db != target.target
            assert "***" in healthy.db
        assert state.persistence_meta() == before_meta
        assert state.persistence_records() == before_records
    finally:
        meta_queue.close()

    failed = Queue(FAILED_QUEUE_NAME, db_path=target, config=config)
    try:
        failed.write("sanitized failed-work fixture")
    finally:
        failed.close()

    finding = TautClient.doctor()
    search = next(check for check in finding.checks if check.name == "search_work")
    assert finding.healthy is False
    assert search.status == "fail"
    assert search.data["failed"] == 1


def _downgrade_summon_claim_schema_to_v2(queue: Queue) -> None:
    ensure_summon_schema(queue)
    with queue.sidecar(transaction=True) as session:
        session.run("DROP INDEX IF EXISTS taut_summon_claim_route_key_uq")
        session.run(
            "UPDATE taut_meta SET value = ? WHERE key = ?",
            ("2", SUMMON_SCHEMA_VERSION_KEY),
        )


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


def test_project_exact_show_and_delete_contract(taut_project: Path) -> None:
    TautClient.init()
    author = TautClient(as_name="author")
    reader = TautClient(as_name="reader")
    author.join("general")
    reader.join("general")
    message = author.say("general", "shared exact message")

    assert reader.show_message(str(message.ts)) == message
    assert author.delete_message(str(message.ts)) == MessageDeletion(
        thread="general",
        ts=message.ts,
        deleted=True,
    )
    with pytest.raises(NotFoundError, match=rf"^message not found: {message.ts}$"):
        reader.show_message(str(message.ts))


def test_project_message_reaction_contract(taut_project: Path) -> None:
    TautClient.init()
    alice = TautClient(as_name="alice")
    bob = TautClient(as_name="bob")
    carol = TautClient(as_name="carol")
    for member in (alice, bob, carol):
        member.join("general")
    target = bob.say("general", "shared reaction target")

    receipt = alice.react_to_message(str(target.ts), "ack")

    assert receipt == MessageReaction(
        thread="general",
        message_ts=target.ts,
        reaction="ack",
        audience_count=2,
    )
    for recipient in (bob, carol):
        notification = recipient.inbox()[0]
        assert notification.type == "reaction"
        assert notification.to_id is None
        assert notification.actor_name == "alice"
        assert notification.thread == "general"
        assert notification.message_ts == target.ts
        assert notification.reaction == "ack"


def test_project_resolved_target_config_handoff_contract(
    taut_project: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """[TAUT-3.2] Frozen target handoff is backend-shared and cwd-free."""

    TautClient.init()
    config = load_config()
    target = resolve_broker_target(taut_project, config=config)
    assert target is not None
    elsewhere = taut_project.parent / "outside-taut-project"
    elsewhere.mkdir(exist_ok=True)
    ambient_db = elsewhere / "ambient.db"
    monkeypatch.chdir(elsewhere)
    monkeypatch.setenv("TAUT_DB", str(ambient_db))
    writer = TautClient(
        broker_target=target,
        broker_config=config,
        as_name="writer",
    )
    reader = TautClient(
        broker_target=target,
        broker_config=config,
        as_name="reader",
    )

    writer.join("general")
    reader.join("general")
    written = writer.say("general", "resolved handoff")

    assert [item.ts for item in reader.read("general")] == [written.ts]
    assert not ambient_db.exists()


def test_project_read_limit_paginates_without_skipping(taut_project: Path) -> None:
    """[TAUT-7.2] A bounded unread cursor advances through returned rows only."""

    TautClient.init()
    reader = TautClient(as_name="reader")
    writer = TautClient(as_name="writer")
    reader.join("general")
    writer.join("general")
    reader.read("general")
    reader_id = reader.whoami().member_id
    writer_identity = writer.whoami()
    queue = writer.queue("general")
    bodies = [
        encode_envelope(
            from_id=writer_identity.member_id,
            from_name=writer_identity.name,
            kind="message",
            text=f"message {index}",
        )
        for index in range(250)
    ]
    first_written_ts = queue.generate_timestamp() + 1
    written_timestamps = [first_written_ts + offset for offset in range(len(bodies))]
    queue.insert_messages(list(zip(bodies, written_timestamps, strict=True)))

    pages: list[list[Message]] = []
    cursor_timestamps: list[int] = []
    for _ in range(3):
        pages.append(reader.read("general", limit=100))
        membership = reader._state.get_membership(
            thread="general",
            member_id=reader_id,
        )
        assert membership is not None
        cursor_timestamps.append(membership["last_seen_ts"])

    assert [len(page) for page in pages] == [100, 100, 50]
    for page_index, page in enumerate(pages):
        start = page_index * 100
        expected_timestamps = written_timestamps[start : start + 100]
        assert [message.text for message in page] == [
            f"message {index}"
            for index in range(start, start + len(expected_timestamps))
        ]
        assert [message.ts for message in page] == expected_timestamps
        assert cursor_timestamps[page_index] == page[-1].ts

    returned_timestamps = [message.ts for page in pages for message in page]
    assert returned_timestamps == written_timestamps
    with pytest.raises(EmptyResultError):
        reader.read("general", limit=100)


def test_project_blank_say_has_no_shared_backend_state(taut_project: Path) -> None:
    """[TAUT-6.5] The blank guard fires on every supported real backend."""

    TautClient.init()
    van = TautClient(as_name="van")
    van.join("general")
    created = van.last_created_member
    assert created is not None
    before_member = van._state.get_member(created.member_id)
    before_threads = van._state.list_threads(include_internal=True)
    before_memberships = van._state.list_memberships(created.member_id)
    before_messages = [(item.ts, item.text) for item in van.log("general")]

    with pytest.raises(BlankMessageError):
        van.say("missing target!", "\u00a0\u200b")

    assert van._state.get_member(created.member_id) == before_member
    assert van._state.list_threads(include_internal=True) == before_threads
    assert van._state.list_memberships(created.member_id) == before_memberships
    assert [(item.ts, item.text) for item in van.log("general")] == before_messages


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


def test_project_reply_pointer_claim_and_membership_contract(
    taut_project: Path,
) -> None:
    """[IAN-7.2]/[IAN-7.4] reply pointers remain backend-shared."""

    TautClient.init()
    van = TautClient(as_name="van")
    bob = TautClient(as_name="bob")
    van.join("general")
    bob.join("general")
    root = van.say("general", "root")

    first = bob.reply("general", str(root.ts), "first reply")
    claimed = van.inbox()

    assert [(item.type, item.thread, item.message_ts) for item in claimed] == [
        ("reply", first.thread, first.ts)
    ]
    with pytest.raises(EmptyResultError):
        van.inbox()
    assert [message.text for message in van.log(first.thread)] == ["first reply"]

    assert [message.text for message in van.read(first.thread)] == ["first reply"]
    second = bob.reply("general", str(root.ts), "while joined")
    with pytest.raises(EmptyResultError):
        van.inbox()
    assert [message.ts for message in van.read(first.thread)] == [second.ts]

    van.leave(first.thread)
    after_leave = bob.reply("general", str(root.ts), "after leave")
    assert [item.message_ts for item in van.inbox()] == [after_leave.ts]


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


def test_project_joined_thread_names_contract(taut_project: Path) -> None:
    """[TAUT-8.3] read-only membership discovery is backend-shared."""

    TautClient.init()
    owner = TautClient(as_name="reviewer")
    owner.join("ops")
    created = owner.last_created_member
    assert created is not None
    owner.join("general")
    speaker = TautClient(as_name="speaker")
    speaker.join("general")
    mention = speaker.say("general", "ping @reviewer")
    member_ids_before = {member.member_id for member in owner.who()}
    member_before = owner._state.get_member(created.member_id)
    assert member_before is not None
    meta = owner.queue(META_QUEUE_NAME)
    try:
        before_high_water = meta.refresh_last_ts()
        names = owner.joined_thread_names()
        after_high_water = meta.refresh_last_ts()
    finally:
        meta.close()
    member_after = owner._state.get_member(created.member_id)
    assert member_after is not None
    assert names == ("general", "ops")
    assert member_after["last_active_ts"] == member_before["last_active_ts"]
    assert after_high_water == before_high_water
    assert [item.message_ts for item in owner.inbox()] == [mention.ts]

    ghost = TautClient(as_name="ghost")
    with pytest.raises(NotFoundError):
        ghost.joined_thread_names()
    assert {member.member_id for member in owner.who()} == member_ids_before


def test_project_sender_interval_probe_preserves_intervening_message(
    taut_project: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """[TAUT-7.4] the committed open-interval probe is backend-shared."""

    TautClient.init()
    van = TautClient(as_name="van")
    bob = TautClient(as_name="bob")
    van.join("general")
    bob.join("general")
    real_write = Queue.write
    inserted = False
    injecting = False

    def write_with_intervening(queue: Queue, body: str) -> int:
        nonlocal inserted, injecting
        if queue.name == "general" and not inserted and not injecting:
            inserted = True
            injecting = True
            try:
                van.say("general", "intervening")
            finally:
                injecting = False
        return real_write(queue, body)

    monkeypatch.setattr(Queue, "write", write_with_intervening)

    response = bob.say("general", "response")

    unread = bob.read("general")
    assert [message.text for message in unread] == ["intervening", "response"]
    assert [message.ts for message in unread] == sorted(
        message.ts for message in unread
    )
    assert unread[-1].ts == response.ts


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
            stdout, stderr = process.communicate(timeout=20)
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


def test_project_automatic_name_skips_alias_owned_route_contract(
    taut_project: Path,
) -> None:
    TautClient.init()
    owner = TautClient(as_name="owner")
    owner.join("general")
    owner._state.add_member_alias(
        member_id=owner.whoami().member_id,
        alias="codex",
        created_ts=1,
    )
    automatic = TautClient(
        identity_capture=_agent_capture(pid=505, start_time="alias-route-start")
    )

    automatic.join("general")

    assert automatic.whoami().name == "Codette"


def test_project_summon_v2_claim_migration_and_route_index_contract(
    taut_project: Path,
) -> None:
    TautClient.init()
    client = TautClient()
    queue = client.queue(LEDGER_QUEUE_NAME)
    try:
        _downgrade_summon_claim_schema_to_v2(queue)
        with queue.sidecar(transaction=True) as session:
            session.run(
                """
                INSERT INTO taut_summon_claims (
                    name, provider, driver_pid, driver_start_time, claimed_ts
                ) VALUES (?, ?, ?, ?, ?)
                """,
                ("Reviewer", "scripted", 123, "legacy-start", 1),
            )

        ensure_summon_schema(queue)

        assert get_summon_schema_version(queue) == 3
        migrated = get_claim(queue, name="REVIEWER", provider="scripted")
        assert migrated is not None
        assert migrated["name"] == "reviewer"
        with queue.sidecar(transaction=True) as session:
            session.run(
                """
                INSERT INTO taut_summon_claims (
                    name, provider, driver_pid, driver_start_time, claimed_ts
                ) VALUES (?, ?, ?, ?, ?)
                """,
                ("Legacy", "scripted", 789, "late-v2-start", 2),
            )
        assert get_claim(queue, name="legacy", provider="scripted") is not None
        with pytest.raises(IntegrityError):  # noqa: SIM117 approved [DOM-10.2.1] [RUFF-SUP-074] exception
            with queue.sidecar(transaction=True) as session:
                session.run(
                    """
                    INSERT INTO taut_summon_claims (
                        name, provider, driver_pid, driver_start_time, claimed_ts
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    ("LEGACY", "scripted", 456, "duplicate-v2-start", 3),
                )
    finally:
        queue.close()
        client.close()


def test_project_summon_v2_case_variant_migration_fails_before_mutation_contract(
    taut_project: Path,
) -> None:
    TautClient.init()
    client = TautClient()
    queue = client.queue(LEDGER_QUEUE_NAME)
    try:
        _downgrade_summon_claim_schema_to_v2(queue)
        with queue.sidecar(transaction=True) as session:
            for name, pid in (("Reviewer", 123), ("reviewer", 456)):
                session.run(
                    """
                    INSERT INTO taut_summon_claims (
                        name, provider, driver_pid, driver_start_time, claimed_ts
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (name, "scripted", pid, f"legacy-{pid}", pid),
                )

        with pytest.raises(SummonSchemaVersionError, match="case-variant claims"):
            ensure_summon_schema(queue)

        assert get_summon_schema_version(queue) == 2
        with queue.sidecar() as session:
            rows = list(
                session.run(
                    """
                    SELECT name FROM taut_summon_claims
                    WHERE provider = ? ORDER BY name
                    """,
                    ("scripted",),
                    fetch=True,
                )
            )
        assert {str(row[0]) for row in rows} == {"Reviewer", "reviewer"}
    finally:
        queue.close()
        client.close()


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


def test_project_stable_dm_say_survives_name_reassignment_contract(
    taut_project: Path,
) -> None:
    """[IAN-5.1] Stable handles stay with the pair while routes move."""

    TautClient.init()
    alice = TautClient(as_name="alice")
    original_bob = TautClient(as_name="bob")
    alice.join("general")
    original_bob.join("general")
    stable = alice.say("@bob", "old route owner").thread

    original_bob.set_name("robert")
    replacement_bob = TautClient(as_name="bob")
    replacement_bob.join("general")
    stable_message = alice.say(stable, "stable old pair")
    routed_message = alice.say("@bob", "current route owner")

    assert stable_message.thread == stable
    assert routed_message.thread != stable
    assert [item.text for item in alice.log(stable)] == [
        "old route owner",
        "stable old pair",
    ]
    assert [item.text for item in alice.log("@bob")] == ["current route owner"]
    assert [item.text for item in original_bob.log(stable)] == [
        "old route owner",
        "stable old pair",
    ]
    with pytest.raises(NotFoundError, match="direct message not found or inaccessible"):
        replacement_bob.log(stable)


def _stable_dm_state_snapshot(
    client: TautClient,
    *,
    actor_id: str,
) -> dict[str, object]:
    """Capture durable shared-backend state, permitting only actor activity."""

    state = cast(sql_state.SqlSidecarTautState, client._state)

    def normalized(record: dict[str, Any]) -> dict[str, Any]:
        result = dict(record)
        if result.get("member_id") == actor_id and "last_active_ts" in result:
            result["last_active_ts"] = "<permitted actor activity>"
        if result.get("type") == "header" and "last_ts" in result:
            result["last_ts"] = "<permitted actor activity allocator>"
        return result

    core_records = tuple(
        json.dumps(
            normalized(record),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        for record in state.persistence_records()
    )
    members = tuple(
        json.dumps(
            normalized(dict(member)),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        for member in client._state.list_members()
    )
    with open_broker(client.target, config=client.config) as broker:
        broker_records = tuple(
            sorted(
                json.dumps(
                    normalized(json.loads(line)),
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                for line in dump_lines(broker)
            )
        )
        queue_stats = tuple(
            sorted(
                (item.queue, item.pending, item.claimed, item.total)
                for item in broker.list_queue_stats()
            )
        )
        raw_broker_meta = broker.get_meta()
        broker_meta = tuple(
            sorted(
                (
                    key,
                    "<permitted actor activity allocator>"
                    if key == "last_ts"
                    else value,
                )
                for key, value in raw_broker_meta.items()
            )
        )
    return {
        "persistence_meta": state.persistence_meta(),
        "core_records": core_records,
        "members": members,
        "broker_meta": broker_meta,
        "broker_records": broker_records,
        "queue_stats": queue_stats,
    }


def _corrupt_shared_direct_message(
    alice: TautClient,
    *,
    stable: str,
    corruption: str,
    alice_id: str,
    bob_id: str,
    carol_id: str,
) -> None:
    if corruption == "missing-actor-membership":
        assert alice._state.remove_membership(thread=stable, member_id=alice_id)
        return
    if corruption == "missing-peer-membership":
        assert alice._state.remove_membership(thread=stable, member_id=bob_id)
        return
    if corruption == "missing-member":
        with alice._meta_queue.sidecar(transaction=True) as session:
            session.run(
                "DELETE FROM taut_membership WHERE member_id = ?",
                (bob_id,),
            )
            session.run(
                "DELETE FROM taut_identity_claims WHERE member_id = ?",
                (bob_id,),
            )
            session.run(
                "DELETE FROM taut_member_aliases WHERE member_id = ?",
                (bob_id,),
            )
            session.run("DELETE FROM taut_members WHERE member_id = ?", (bob_id,))
        return

    metadata: dict[str, dict[str, object]] = {
        "missing-members-meta": {},
        "members-not-list": {"members": "not-a-list"},
        "member-not-string": {"members": [alice_id, 7]},
        "wrong-cardinality-one": {"members": [alice_id]},
        "wrong-cardinality-three": {"members": [alice_id, bob_id, carol_id]},
        "duplicate-member-ids": {"members": [alice_id, alice_id]},
        "invalid-member-id": {"members": [alice_id, "invalid-id"]},
        "deterministic-name-mismatch": {"members": [alice_id, carol_id]},
        "actor-absent-metadata": {"members": [bob_id, carol_id]},
        "wrong-kind": {"members": [alice_id, bob_id]},
    }
    if corruption == "deterministic-name-mismatch":
        alice._state.add_membership(
            thread=stable,
            member_id=carol_id,
            joined_ts=alice._meta_queue.generate_timestamp(),
            last_seen_ts=0,
        )
    kind = "channel" if corruption == "wrong-kind" else "dm"
    with alice._meta_queue.sidecar(transaction=True) as session:
        session.run(
            "UPDATE taut_threads SET kind = ?, meta = ? WHERE name = ?",
            (kind, json.dumps(metadata[corruption]), stable),
        )


def test_project_stable_dm_say_existing_conversation_contract(
    taut_project: Path,
) -> None:
    """[TAUT-8.1]/[IAN-5.3] Stable say reuses one valid existing DM."""

    TautClient.init()
    alice = TautClient(as_name="alice")
    bob = TautClient(as_name="bob")
    carol = TautClient(as_name="carol")
    for member in (alice, bob, carol):
        member.join("general")
    alice_id = alice.whoami().member_id
    bob_id = bob.whoami().member_id
    state = cast(sql_state.SqlSidecarTautState, alice._state)
    first = alice.say("@bob", "created through the person route")
    stable = first.thread
    started = bob.inbox()
    assert [(item.type, item.thread) for item in started] == [("dm_started", stable)]
    thread_before = alice._state.get_thread(stable)
    actor_before = alice._state.get_member(alice_id)
    actor_membership_before = alice._state.get_membership(
        thread=stable,
        member_id=alice_id,
    )
    peer_membership_before = alice._state.get_membership(
        thread=stable,
        member_id=bob_id,
    )
    registry_before = {
        (record["thread"], record["member_id"])
        for record in state.persistence_records()
        if record["type"] == "membership"
    }
    assert thread_before is not None
    assert actor_before is not None
    assert actor_membership_before is not None
    assert peer_membership_before is not None

    written = alice.say(stable, "stable hello @bob and private @carol")
    actor_after = alice._state.get_member(alice_id)
    actor_membership_after = alice._state.get_membership(
        thread=stable,
        member_id=alice_id,
    )

    assert written.thread == stable
    assert isinstance(written.ts, int)
    assert [message.text for message in alice.log(stable)] == [
        "created through the person route",
        "stable hello @bob and private @carol",
    ]
    assert alice._state.get_thread(stable) == thread_before
    assert {
        (record["thread"], record["member_id"])
        for record in state.persistence_records()
        if record["type"] == "membership"
    } == registry_before
    assert actor_after is not None
    assert actor_after["last_active_ts"] > actor_before["last_active_ts"]
    assert actor_membership_after is not None
    assert actor_membership_after["last_seen_ts"] == written.ts
    assert (
        alice._state.get_membership(
            thread=stable,
            member_id=bob_id,
        )
        == peer_membership_before
    )
    assert [(item.type, item.thread, item.message_ts) for item in bob.inbox()] == [
        ("mention", stable, written.ts)
    ]
    with pytest.raises(EmptyResultError):
        carol.inbox()


@pytest.mark.parametrize(
    "failure",
    [
        "absent",
        "wrong-kind",
        "missing-members-meta",
        "members-not-list",
        "member-not-string",
        "wrong-cardinality-one",
        "wrong-cardinality-three",
        "duplicate-member-ids",
        "invalid-member-id",
        "deterministic-name-mismatch",
        "actor-absent-metadata",
        "nonparticipant",
        "missing-member",
        "missing-actor-membership",
        "missing-peer-membership",
    ],
)
def test_project_stable_dm_say_misses_are_uniform_and_noncreating(
    taut_project: Path,
    failure: str,
) -> None:
    """[IAN-5.3]/[IAN-10] Every stable-send miss fails closed on real state."""

    TautClient.init()
    alice = TautClient(as_name="alice")
    bob = TautClient(as_name="bob")
    carol = TautClient(as_name="carol")
    dave = TautClient(as_name="dave")
    for member in (alice, bob, carol, dave):
        member.join("general")
    alice_id = alice.whoami().member_id
    bob_id = bob.whoami().member_id
    carol_id = carol.whoami().member_id

    if failure == "absent":
        stable = "dm.d_" + "a" * 26
        assert alice._state.get_thread(stable) is None
    elif failure == "nonparticipant":
        stable = carol.say("@dave", "private to another pair").thread
    else:
        stable = alice.say("@bob", "existing conversation").thread
        _corrupt_shared_direct_message(
            alice,
            stable=stable,
            corruption=failure,
            alice_id=alice_id,
            bob_id=bob_id,
            carol_id=carol_id,
        )
    actor_before = alice._state.get_member(alice_id)
    assert actor_before is not None
    before = _stable_dm_state_snapshot(alice, actor_id=alice_id)

    with pytest.raises(NotFoundError) as caught:
        alice.say(stable, "must not create or repair state")

    assert type(caught.value) is NotFoundError
    assert str(caught.value) == "direct message not found or inaccessible"
    actor_after = alice._state.get_member(alice_id)
    assert actor_after is not None
    assert actor_after["last_active_ts"] >= actor_before["last_active_ts"]
    assert _stable_dm_state_snapshot(alice, actor_id=alice_id) == before


def test_project_dm_navigation_and_directory_contract(taut_project: Path) -> None:
    """[TAUT-7.8] DM selectors and directory work on every real backend."""

    TautClient.init()
    alice = TautClient(as_name="alice")
    bob = TautClient(as_name="bob")
    carol = TautClient(as_name="carol")
    for member in (alice, bob, carol):
        member.join("general")
    alice_id = alice.whoami().member_id
    bob_id = bob.whoami().member_id
    sent = bob.say("@alice", "shared DM")
    stable = addressing.dm_queue_name(alice_id, bob_id)
    membership_before = alice._state.get_membership(
        thread=stable,
        member_id=alice_id,
    )
    actor_before = alice._state.get_member(alice_id)

    assert sent.thread == stable
    assert [item.text for item in alice.log("@bob")] == ["shared DM"]
    assert [item.text for item in alice.log(stable)] == ["shared DM"]
    assert (
        alice._state.get_membership(
            thread=stable,
            member_id=alice_id,
        )
        == membership_before
    )
    assert alice._state.get_member(alice_id) == actor_before
    assert [item.text for item in alice.read("@bob")] == ["shared DM"]
    assert alice.list_direct_messages()[0].name == stable
    assert alice.list_direct_messages()[0].unread is False

    empty = carol.say("@alice", "delete me")
    carol.delete_message(str(empty.ts))
    listed = alice.list_direct_messages()
    assert {item.name for item in listed} == {stable, empty.thread}
    assert next(item for item in listed if item.name == empty.thread).last_ts is None

    bob.set_name("robert")
    assert [item.text for item in alice.log("@robert")] == ["shared DM"]
    assert [item.text for item in alice.log(stable)] == ["shared DM"]


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


def test_project_notification_peek_is_observational_contract(
    taut_project: Path,
) -> None:
    """[TAUT-8.3]/[IAN-7.4] Peek is ordered and read-only on each backend."""

    TautClient.init()
    owner = TautClient(as_name="reviewer")
    owner.join("general")
    created = owner.last_created_member
    assert created is not None
    assert created.token is not None
    observer = TautClient(token=created.token)
    token_claim = identity.claim_for_token(created.token)
    assert observer._state.get_identity_claim(token_claim.claim_hash) is None
    assert observer.peek_inbox() == []
    assert observer._state.get_identity_claim(token_claim.claim_hash) is None
    observer.whoami()
    established_claim = observer._state.get_identity_claim(token_claim.claim_hash)
    assert established_claim is not None
    speaker = TautClient(as_name="speaker")
    speaker.join("general")
    written = [
        speaker.say("general", "first @reviewer"),
        speaker.say("general", "second @reviewer"),
    ]
    member_before = observer._state.get_member(created.member_id)
    memberships_before = observer._state.list_memberships(created.member_id)
    claim_before = observer._state.get_identity_claim(token_claim.claim_hash)
    assert member_before is not None
    assert claim_before == established_claim
    meta = observer.queue(META_QUEUE_NAME)
    notifications = observer.queue(
        addressing.notification_queue_name(created.member_id)
    )
    try:
        meta_high_water_before = meta.refresh_last_ts()
        stats_before = notifications.stats()

        first = observer.peek_inbox(limit=1)
        repeated_first = observer.peek_inbox(limit=1)
        all_pending = observer.peek_inbox(limit=2)

        meta_high_water_after = meta.refresh_last_ts()
        stats_after = notifications.stats()
    finally:
        notifications.close()
        meta.close()

    assert [item.message_ts for item in first] == [written[0].ts]
    assert repeated_first == first
    assert [item.message_ts for item in all_pending] == [
        message.ts for message in written
    ]
    assert observer._state.get_member(created.member_id) == member_before
    assert observer._state.list_memberships(created.member_id) == memberships_before
    assert observer._state.get_identity_claim(token_claim.claim_hash) == claim_before
    assert meta_high_water_after == meta_high_water_before
    assert stats_after == stats_before

    assert observer.inbox(limit=2) == all_pending
    member_after_consume = observer._state.get_member(created.member_id)
    claim_after_consume = observer._state.get_identity_claim(token_claim.claim_hash)
    assert member_after_consume is not None
    assert claim_after_consume is not None
    assert member_after_consume["last_active_ts"] > member_before["last_active_ts"]
    assert claim_after_consume["last_seen_ts"] > claim_before["last_seen_ts"]
    assert observer.peek_inbox() == []
    with pytest.raises(EmptyResultError):
        observer.inbox()

    with observer._meta_queue.sidecar(transaction=True) as session:
        session.run(
            "UPDATE taut_members SET token = NULL WHERE member_id = ?",
            (created.member_id,),
        )
    member_after_unbind = observer._state.get_member(created.member_id)
    assert member_after_unbind is not None
    with pytest.raises(TokenError, match="TAUT_TOKEN does not match a taut member"):
        observer.peek_inbox()
    assert observer._state.get_member(created.member_id) == member_after_unbind


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


def test_project_channel_topic_state_and_rename_contract(
    taut_project: Path,
) -> None:
    TautClient.init()
    owner = TautClient(as_name="owner")
    owner.join("general")
    member = owner.whoami()
    before_messages = owner.log("general")
    before_membership = owner._state.get_membership(
        thread="general",
        member_id=member.member_id,
    )
    with owner._meta_queue.sidecar(transaction=True) as session:
        session.run(
            "UPDATE taut_threads SET meta = ? WHERE name = ?",
            (
                json.dumps(
                    {
                        "closed": {"future": "preserve"},
                        "custom": {"value": 1},
                    }
                ),
                "general",
            ),
        )

    updated = owner.set_channel_topic("general", "shared backend topic")
    updated_member = owner._state.get_member(member.member_id)
    updated_row = owner._state.get_thread("general")
    assert updated_member is not None
    assert updated_row is not None
    assert updated_member["last_active_ts"] == updated.topic_updated_ts
    assert updated_row["meta"] == {
        "closed": {"future": "preserve"},
        "custom": {"value": 1},
        "topic": {
            "text": "shared backend topic",
            "updated_ts": updated.topic_updated_ts,
            "updated_by_id": member.member_id,
        },
    }
    assert owner.set_channel_topic("general", "shared backend topic") == updated
    assert owner._state.get_member(member.member_id) == updated_member
    assert owner._state.get_thread("general") == updated_row
    assert (
        owner._state.get_membership(
            thread="general",
            member_id=member.member_id,
        )
        == before_membership
    )
    assert owner.log("general") == before_messages

    renamed = owner.rename_channel("general", "ops")
    assert renamed.topic == "shared backend topic"
    assert owner.get_channel("ops") == updated.__class__(
        name="ops",
        topic=updated.topic,
        topic_updated_ts=updated.topic_updated_ts,
        topic_updated_by_id=updated.topic_updated_by_id,
        topic_updated_by_name=updated.topic_updated_by_name,
    )
    renamed_row = owner._state.get_thread("ops")
    assert renamed_row is not None
    assert renamed_row["meta"] == updated_row["meta"]

    cleared = owner.set_channel_topic("ops", None)
    assert cleared.topic is None
    assert cleared.topic_updated_ts is None
    cleared_row = owner._state.get_thread("ops")
    assert cleared_row is not None
    assert cleared_row["meta"] == {
        "closed": {"future": "preserve"},
        "custom": {"value": 1},
    }


def test_project_concurrent_channel_topics_are_internally_consistent(
    taut_project: Path,
) -> None:
    TautClient.init()
    alice = TautClient(as_name="alice")
    bob = TautClient(as_name="bob")
    alice.join("general")
    bob.join("general")
    alice_id = alice.whoami().member_id
    bob_id = bob.whoami().member_id
    with alice._meta_queue.sidecar(transaction=True) as session:
        session.run(
            "UPDATE taut_threads SET meta = ? WHERE name = ?",
            (json.dumps({"closed": "reserved", "custom": 1}), "general"),
        )
    start = threading.Barrier(2)

    def update(as_name: str, topic: str) -> object:
        writer = TautClient(as_name=as_name)
        try:
            start.wait(timeout=10)
            return writer.set_channel_topic("general", topic)
        finally:
            writer.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        alice_future = pool.submit(update, "alice", "alice topic")
        bob_future = pool.submit(update, "bob", "bob topic")
        written = [alice_future.result(timeout=20), bob_future.result(timeout=20)]

    current = alice.get_channel("general")
    assert current in written
    expected_author = {
        "alice topic": alice_id,
        "bob topic": bob_id,
    }
    assert current.topic is not None
    assert current.topic_updated_by_id == expected_author[current.topic]
    row = alice._state.get_thread("general")
    assert row is not None
    assert row["meta"]["closed"] == "reserved"
    assert row["meta"]["custom"] == 1
    assert row["meta"]["topic"] == {
        "text": current.topic,
        "updated_ts": current.topic_updated_ts,
        "updated_by_id": current.topic_updated_by_id,
    }


def test_project_channel_topic_racing_cooperative_meta_writer_preserves_both(
    taut_project: Path,
) -> None:
    TautClient.init()
    owner = TautClient(as_name="owner")
    owner.join("general")
    start = threading.Barrier(2)

    def write_topic() -> None:
        writer = TautClient(as_name="owner")
        try:
            start.wait(timeout=10)
            writer.set_channel_topic("general", "topic write")
        finally:
            writer.close()

    def write_unknown_meta() -> None:
        queue = Queue(META_QUEUE_NAME, db_path=owner.target, config=owner.config)
        try:
            start.wait(timeout=10)
            with queue.sidecar(transaction=True) as session:
                sql_state._acquire_advisory_lock(
                    session,
                    dialect_for_taut_target(owner.target),
                    "taut:channel:general",
                )
                rows = list(
                    session.run(
                        "SELECT meta FROM taut_threads WHERE name = ?",
                        ("general",),
                        fetch=True,
                    )
                )
                assert len(rows) == 1
                meta = json.loads(rows[0][0])
                meta["custom"] = {"cooperative": True}
                session.run(
                    "UPDATE taut_threads SET meta = ? WHERE name = ?",
                    (json.dumps(meta), "general"),
                )
        finally:
            queue.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        topic_future = pool.submit(write_topic)
        metadata_future = pool.submit(write_unknown_meta)
        topic_future.result(timeout=20)
        metadata_future.result(timeout=20)

    row = owner._state.get_thread("general")
    assert row is not None
    assert row["meta"]["custom"] == {"cooperative": True}
    assert row["meta"]["topic"]["text"] == "topic write"


@pytest.mark.parametrize("first", ["topic", "rename"])
def test_project_channel_topic_and_rename_marker_share_serialization(
    taut_project: Path,
    monkeypatch: pytest.MonkeyPatch,
    first: str,
) -> None:
    TautClient.init()
    owner = TautClient(as_name="owner")
    owner.join("general")
    held = threading.Event()
    release = threading.Event()
    second_started = threading.Event()
    original_lock = sql_state._acquire_advisory_lock
    first_thread = f"{first}-writer"

    def pause_first_holder(
        session: SidecarSession,
        dialect: SqlDialect,
        key: str,
    ) -> None:
        original_lock(session, dialect, key)
        if key == "taut:channel:general" and threading.current_thread().name.startswith(
            first_thread
        ):
            held.set()
            assert release.wait(timeout=10)

    monkeypatch.setattr(sql_state, "_acquire_advisory_lock", pause_first_holder)

    def set_topic() -> Channel:
        writer = TautClient(as_name="owner")
        try:
            return writer.set_channel_topic("general", "raced topic")
        finally:
            writer.close()

    def rename() -> Thread:
        writer = TautClient(as_name="owner")
        try:
            return writer.rename_channel("general", "ops")
        finally:
            writer.close()

    first_call = set_topic if first == "topic" else rename
    second_operation = rename if first == "topic" else set_topic

    def second_call() -> Channel | Thread:
        second_started.set()
        return second_operation()

    with (
        ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix=first_thread,
        ) as first_pool,
        ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="second-writer",
        ) as second_pool,
    ):
        first_future = first_pool.submit(first_call)
        assert held.wait(timeout=10)
        second_future = second_pool.submit(second_call)
        assert second_started.wait(timeout=10)
        release.set()
        first_result = first_future.result(timeout=20)
        if first == "topic":
            second_result = second_future.result(timeout=20)
            assert cast(Channel, first_result).topic == "raced topic"
            assert cast(Thread, second_result).topic == "raced topic"
        else:
            assert cast(Thread, first_result).topic is None
            with pytest.raises((TautError, NotFoundError)):
                second_future.result(timeout=20)

    current = owner.get_channel("ops")
    assert current.topic == ("raced topic" if first == "topic" else None)


def test_project_channel_rename_resume_contract(taut_project: Path) -> None:
    TautClient.init()
    van = TautClient(as_name="van")
    van.join("general")
    root = van.say("general", "root")
    van.reply("general", str(root.ts), "threaded")
    affected = [
        {"old": "general", "new": "ops"},
        {"old": f"general.{root.ts}", "new": f"ops.{root.ts}"},
    ]
    # White-box crash-window simulation (mirrors tests/test_client.py):
    # public APIs never leave a 'started' marker behind. The marker is a
    # sidecar row, so this recovery contract holds on every backend. Only a
    # strict subset of the affected queues is renamed before the "crash".
    meta_queue = van.queue(META_QUEUE_NAME)
    try:
        van._state.start_channel_rename(
            old_name="general",
            new_name="ops",
            affected=affected,
            started_ts=meta_queue.generate_timestamp(),
        )
    finally:
        meta_queue.close()
    with open_broker(van.target, config=van.config) as broker:
        broker.rename_queue("general", "ops", retarget_aliases=False)

    with pytest.raises(
        TautError,
        match="run 'taut channel rename general ops' to finish it",
    ):
        van.say("general", "blocked")

    renamed = van.rename_channel("general", "ops")

    assert renamed.name == "ops"
    assert [message.text for message in van.log("ops")] == [
        "van created #general",
        "root",
    ]
    assert [message.text for message in van.log(f"ops.{root.ts}")] == ["threaded"]
    with pytest.raises(NotFoundError, match="channel not found: general"):
        van.rename_channel("general", "ops")
