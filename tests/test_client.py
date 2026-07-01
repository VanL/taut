from __future__ import annotations

import json
from pathlib import Path

import pytest
from simplebroker import Queue

import taut.identity as identity
from taut._constants import META_QUEUE_NAME
from taut._exceptions import (
    EmptyResultError,
    IdentityError,
    NotFoundError,
    NotInitializedError,
    TautError,
    ThreadNameError,
)
from taut.client import TautClient
from taut.state import SQLITE_SQL_DIALECT, SqlSidecarTautState

pytestmark = pytest.mark.sqlite_only


def client(tmp_path: Path, name: str) -> TautClient:
    TautClient.init(db_path=tmp_path / ".taut.db")
    return TautClient(db_path=tmp_path / ".taut.db", as_name=name)


def existing_client(tmp_path: Path, name: str) -> TautClient:
    return TautClient(db_path=tmp_path / ".taut.db", as_name=name)


def next_meta_timestamp(tmp_path: Path) -> int:
    queue = Queue(META_QUEUE_NAME, db_path=str(tmp_path / ".taut.db"))
    try:
        return queue.generate_timestamp()
    finally:
        queue.close()


def test_explicit_missing_path_does_not_auto_create(tmp_path: Path) -> None:
    with pytest.raises(NotInitializedError):
        TautClient(db_path=tmp_path / ".taut.db")

    assert not (tmp_path / ".taut.db").exists()


def test_join_starts_at_now_and_other_member_message_is_unread(tmp_path: Path) -> None:
    van = client(tmp_path, "van")
    van.join("general")
    claude = existing_client(tmp_path, "claude")
    claude.join("general")

    van.say("general", "hello")
    unread = claude.read("general")

    assert [message.text for message in unread] == ["hello"]
    with pytest.raises(EmptyResultError):
        claude.read("general")


def test_sender_cursor_advances_when_caught_up(tmp_path: Path) -> None:
    van = client(tmp_path, "van")
    van.join("general")
    van.say("general", "self")

    with pytest.raises(EmptyResultError):
        van.read("general")


def test_say_missing_thread_does_not_create_member(tmp_path: Path) -> None:
    van = client(tmp_path, "van")

    with pytest.raises(NotFoundError):
        van.say("missing", "hello")

    assert van.who() == []


def test_reply_missing_thread_does_not_create_member(tmp_path: Path) -> None:
    van = client(tmp_path, "van")

    with pytest.raises(NotFoundError):
        van.reply("missing", "1234", "hello")

    assert van.who() == []


def test_say_unjoined_channel_does_not_create_member(tmp_path: Path) -> None:
    bob = client(tmp_path, "bob")
    bob.join("general")
    van = existing_client(tmp_path, "van")

    with pytest.raises(NotFoundError):
        van.say("general", "hello")

    assert [member.name for member in van.who()] == ["bob"]


def test_reply_full_id_creates_subthread(tmp_path: Path) -> None:
    van = client(tmp_path, "van")
    van.join("general")
    first = van.say("general", "root")

    reply = van.reply("general", str(first.ts), "threaded")

    assert reply.thread == f"general.{first.ts}"
    assert van.log(reply.thread)[0].text == "threaded"


def test_guest_read_only_resolution_does_not_generate_timestamp(tmp_path: Path) -> None:
    TautClient.init(db_path=tmp_path / ".taut.db")
    queue = Queue(META_QUEUE_NAME, db_path=str(tmp_path / ".taut.db"))
    before = queue.refresh_last_ts()

    TautClient(db_path=tmp_path / ".taut.db").who()

    after = queue.refresh_last_ts()
    assert after == before


def test_member_creation_returns_stable_member_id_name_and_token(
    tmp_path: Path,
) -> None:
    van = client(tmp_path, "VanL")
    van.join("general")

    member = van.last_created_member

    assert member is not None
    assert member.member_id.startswith("m_")
    assert member.name == "VanL"
    assert member.token is not None
    assert "van" not in member.member_id.lower()


def test_member_creation_conflict_re_resolves_matching_claim(tmp_path: Path) -> None:
    van = client(tmp_path, "van")
    van.join("general")
    existing = van.whoami()
    capture = van._capture()
    claim = identity.claim_for_capture(capture)

    resolved = van._create_member(
        capture,
        claim=claim,
        name="van",
        persona=None,
        active_ts=next_meta_timestamp(tmp_path),
        force_new=False,
    )

    assert resolved["member_id"] == existing.member_id


def test_member_creation_force_new_does_not_re_resolve_matching_claim(
    tmp_path: Path,
) -> None:
    van = client(tmp_path, "van")
    van.join("general")
    capture = van._capture()
    claim = identity.claim_for_capture(capture)

    with pytest.raises(IdentityError):
        van._create_member(
            capture,
            claim=claim,
            name="van",
            persona=None,
            active_ts=next_meta_timestamp(tmp_path),
            force_new=True,
        )


def test_set_name_changes_current_name_without_changing_member_id(
    tmp_path: Path,
) -> None:
    van = client(tmp_path, "van")
    van.join("general")
    before = van.whoami()
    old = van.say("general", "old name")

    after = van.set_name("VanL")
    new = van.say("general", "new name")

    assert after.member_id == before.member_id
    assert after.name == "VanL"
    assert old.from_id == new.from_id == before.member_id
    assert old.from_name == "van"
    assert new.from_name == "VanL"
    with pytest.raises(NotFoundError):
        TautClient(db_path=tmp_path / ".taut.db", as_name="van").whoami()
    assert (
        TautClient(db_path=tmp_path / ".taut.db", as_name="VanL").whoami().member_id
        == before.member_id
    )


def test_set_name_requires_resolved_member(tmp_path: Path) -> None:
    TautClient.init(db_path=tmp_path / ".taut.db")

    with pytest.raises(IdentityError, match="unrecognized caller"):
        TautClient(db_path=tmp_path / ".taut.db").set_name("VanL")


def test_direct_message_queue_is_stable_across_name_change(tmp_path: Path) -> None:
    van = client(tmp_path, "van")
    bob = existing_client(tmp_path, "bob")
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


def test_self_dm_is_rejected(tmp_path: Path) -> None:
    van = client(tmp_path, "van")
    van.join("general")

    with pytest.raises(ValueError):
        van.say("@van", "no")


def test_unknown_dm_target_is_not_found(tmp_path: Path) -> None:
    van = client(tmp_path, "van")
    van.join("general")

    with pytest.raises(NotFoundError):
        van.say("@missing", "no")


def test_mention_notification_is_claimed_without_touching_chat_history(
    tmp_path: Path,
) -> None:
    van = client(tmp_path, "van")
    bob = existing_client(tmp_path, "bob")
    van.join("general")
    bob.join("general")

    message = van.say("general", "hello @bob @bob")
    notifications = bob.inbox()

    assert len(notifications) == 1
    assert notifications[0].type == "mention"
    assert notifications[0].actor_name == "van"
    assert notifications[0].message_ts == message.ts
    with pytest.raises(EmptyResultError):
        bob.inbox()
    assert message.text in [item.text for item in bob.log("general")]


def test_malformed_notification_does_not_crash_inbox(tmp_path: Path) -> None:
    bob = client(tmp_path, "bob")
    bob.join("general")
    member_id = bob.whoami().member_id
    queue = bob.queue(f"notify.{member_id}")
    ts = queue.generate_timestamp()
    queue.insert_messages([("not json", ts)])

    notifications = bob.inbox()

    assert notifications[0].type == "foreign"
    assert notifications[0].warning is not None


def test_mention_notification_without_matched_is_malformed(tmp_path: Path) -> None:
    bob = client(tmp_path, "bob")
    bob.join("general")
    member_id = bob.whoami().member_id
    queue = bob.queue(f"notify.{member_id}")
    ts = queue.generate_timestamp()
    queue.insert_messages(
        [
            (
                json.dumps(
                    {
                        "type": "mention",
                        "to_id": member_id,
                        "actor_id": member_id,
                        "actor_name": "bob",
                        "thread": "general",
                        "message_ts": ts,
                    }
                ),
                ts,
            )
        ]
    )

    notifications = bob.inbox()

    assert notifications[0].type == "foreign"
    assert notifications[0].warning == "malformed notification"


def test_channel_names_reject_dots_and_reserved_words(tmp_path: Path) -> None:
    van = client(tmp_path, "van")

    for name in ("general.foo", "dm", "notify", "sys", "taut"):
        with pytest.raises(ThreadNameError):
            van.join(name)


def test_unregistered_broker_queues_are_invisible_to_list(tmp_path: Path) -> None:
    van = client(tmp_path, "van")
    van.join("general")
    van.queue("foreign").insert_messages(
        [("raw", van.queue("foreign").generate_timestamp())]
    )

    assert [thread.name for thread in van.list_threads(all_threads=True)] == ["general"]


def test_rename_channel_moves_messages_and_subthreads(tmp_path: Path) -> None:
    van = client(tmp_path, "van")
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
    with pytest.raises(NotFoundError):
        van.log("general")


def test_rename_channel_rejects_existing_target_without_mutation(
    tmp_path: Path,
) -> None:
    van = client(tmp_path, "van")
    van.join("general")
    van.join("ops")

    with pytest.raises(ValueError):
        van.rename_channel("general", "ops")

    assert {thread.name for thread in van.list_threads(all_threads=True)} == {
        "general",
        "ops",
    }


def test_incomplete_channel_rename_blocks_chat_history_operations(
    tmp_path: Path,
) -> None:
    van = client(tmp_path, "van")
    van.join("general")
    queue = Queue(META_QUEUE_NAME, db_path=str(tmp_path / ".taut.db"))
    try:
        state = SqlSidecarTautState(queue, SQLITE_SQL_DIALECT)
        started_ts = queue.generate_timestamp()
        # White-box setup: public APIs never leave this crash-window marker behind.
        state.start_channel_rename(
            old_name="general",
            new_name="ops",
            affected=[{"old": "general", "new": "ops"}],
            started_ts=started_ts,
        )
    finally:
        queue.close()

    with pytest.raises(TautError, match="incomplete channel rename"):
        van.log("general")
