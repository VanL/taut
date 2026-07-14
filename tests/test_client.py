from __future__ import annotations

import json
import threading
from collections.abc import Callable
from pathlib import Path

import pytest
from simplebroker import Queue, open_broker
from simplebroker.ext import IntegrityError

import taut.client._messaging as messaging
import taut.identity as identity
from taut import addressing
from taut._constants import META_QUEUE_NAME
from taut._exceptions import (
    AmbiguousMessageError,
    EmptyResultError,
    IdentityError,
    MembershipError,
    NotFoundError,
    NotInitializedError,
    TautError,
    ThreadNameError,
)
from taut.client import Message, TautClient
from taut.commands._rendering import format_unread_count
from taut.envelope import encode_envelope
from taut.state import SQLITE_SQL_DIALECT, MembershipRow, SqlSidecarTautState

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


def test_read_without_thread_reads_all_membership_unread(tmp_path: Path) -> None:
    van = client(tmp_path, "van")
    van.join("general")
    bob = existing_client(tmp_path, "bob")
    bob.join("general")

    bob.say("general", "broadcast")
    unread = van.read()

    assert [message.text for message in unread] == ["bob joined", "broadcast"]


def test_read_unread_advances_cursor_once_for_a_full_thread_page(
    tmp_path: Path,
) -> None:
    van = client(tmp_path, "van")
    van.join("general")
    member_id = van.whoami().member_id
    queue = van.queue("general")
    bodies = [
        encode_envelope(
            from_id=member_id,
            from_name="van",
            kind="message",
            text=f"message {index}",
        )
        for index in range(1000)
    ]
    timestamps = [queue.generate_timestamp() for _ in bodies]
    queue.insert_messages(list(zip(bodies, timestamps, strict=True)))
    delegate = van._state

    class CountingState:
        def __init__(self) -> None:
            self.advance_calls: list[int] = []

        def advance_cursor(self, *, thread: str, member_id: str, seen_ts: int) -> None:
            self.advance_calls.append(seen_ts)
            delegate.advance_cursor(
                thread=thread,
                member_id=member_id,
                seen_ts=seen_ts,
            )

        def __getattr__(self, name: str) -> object:
            return getattr(delegate, name)

    counting = CountingState()
    van._state = counting  # type: ignore[assignment]

    unread = van.read_unread("general")

    assert len(unread) == 1000
    assert counting.advance_calls == [timestamps[-1]]
    membership = delegate.get_membership(thread="general", member_id=member_id)
    assert membership is not None
    assert membership["last_seen_ts"] == timestamps[-1]


def test_read_unread_does_not_advance_a_page_when_decoding_raises(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    van = client(tmp_path, "van")
    van.join("general")
    member_id = van.whoami().member_id
    membership = van._state.get_membership(thread="general", member_id=member_id)
    assert membership is not None
    cursor_before = membership["last_seen_ts"]
    queue = van.queue("general")
    bodies = [
        encode_envelope(
            from_id=member_id,
            from_name="van",
            kind="message",
            text=text,
        )
        for text in ("decodes", "fault injection")
    ]
    timestamps = [queue.generate_timestamp() for _ in bodies]
    queue.insert_messages(list(zip(bodies, timestamps, strict=True)))
    real_decoder = messaging.message_from_body

    def fail_second(thread: str, body: str, ts: int) -> object:
        if body == bodies[1]:
            raise RuntimeError("decoder fault")
        return real_decoder(thread, body, ts)

    monkeypatch.setattr(messaging, "message_from_body", fail_second)

    with pytest.raises(RuntimeError, match="decoder fault"):
        van.read_unread("general")

    membership = van._state.get_membership(thread="general", member_id=member_id)
    assert membership is not None
    assert membership["last_seen_ts"] == cursor_before


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


def test_say_does_not_advance_cursor_when_sender_has_unread(tmp_path: Path) -> None:
    van = client(tmp_path, "van")
    van.join("general")
    bob = existing_client(tmp_path, "bob")
    bob.join("general")

    van.say("general", "pending")
    bob.say("general", "response")

    assert [message.text for message in bob.read("general")] == [
        "pending",
        "response",
    ]


def test_sender_does_not_skip_message_published_during_its_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """[TAUT-7.4]: catch-up is decided against the committed own id."""

    van = client(tmp_path, "van")
    van.join("general")
    bob = existing_client(tmp_path, "bob")
    bob.join("general")

    real_has_pending = Queue.has_pending
    real_write = Queue.write
    armed = True
    inserted = False
    injecting = False

    def inject_intervening() -> None:
        nonlocal inserted, injecting
        inserted = True
        injecting = True
        try:
            van.say("general", "intervening")
        finally:
            injecting = False

    def has_pending_with_gate(queue: Queue, after_timestamp: int | None = None) -> bool:
        result = real_has_pending(queue, after_timestamp=after_timestamp)
        if armed and queue.name == "general" and not inserted and not injecting:
            inject_intervening()
        return result

    def write_with_gate(queue: Queue, message: str) -> int:
        if armed and queue.name == "general" and not inserted and not injecting:
            inject_intervening()
        return real_write(queue, message)

    monkeypatch.setattr(Queue, "has_pending", has_pending_with_gate)
    monkeypatch.setattr(Queue, "write", write_with_gate)

    bob.say("general", "response")

    assert [message.text for message in bob.read("general")] == [
        "intervening",
        "response",
    ]


def test_join_notice_does_not_skip_message_published_after_membership(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    van = client(tmp_path, "van")
    van.join("general")
    bob = existing_client(tmp_path, "bob")
    real_write = Queue.write
    inserted = False

    def write_with_gate(queue: Queue, message: str) -> int:
        nonlocal inserted
        if queue.name == "general" and not inserted:
            inserted = True
            van.say("general", "between membership and notice")
        return real_write(queue, message)

    monkeypatch.setattr(Queue, "write", write_with_gate)

    notice = bob.join("general")

    assert [message.text for message in bob.read("general")] == [
        "between membership and notice",
        notice.text,
    ]


def test_dm_does_not_skip_message_published_after_membership(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    van = client(tmp_path, "van")
    van.join("general")
    bob = existing_client(tmp_path, "bob")
    bob.join("general")
    thread = addressing.dm_queue_name(van.whoami().member_id, bob.whoami().member_id)
    real_write = Queue.write
    inserted = False

    def write_with_gate(queue: Queue, message: str) -> int:
        nonlocal inserted
        if queue.name == thread and not inserted:
            inserted = True
            bob.say("@van", "between membership and dm")
        return real_write(queue, message)

    monkeypatch.setattr(Queue, "write", write_with_gate)

    sent = van.say("@bob", "outbound")

    assert sent.thread == thread
    listed = next(
        item for item in van.list_threads(all_threads=True) if item.name == thread
    )
    assert listed.unread_count == 2


def test_list_skips_bounded_peek_for_caught_up_memberships(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    alice = client(tmp_path, "alice")
    for thread in ("caught-up-a", "unread", "caught-up-b"):
        alice.join(thread)
    bob = existing_client(tmp_path, "bob")
    bob.join("unread")
    alice.read("unread")
    bob.say("unread", "pending")
    membership = alice._state.get_membership(
        thread="unread",
        member_id=alice.whoami().member_id,
    )
    assert membership is not None

    real_peek_many = Queue.peek_many
    peek_calls: list[tuple[str, int | None]] = []

    def counting_peek_many(
        queue: Queue,
        limit: int = 1000,
        *,
        with_timestamps: bool = False,
        after_timestamp: int | None = None,
        before_timestamp: int | None = None,
        include_claimed: bool = False,
    ) -> list[str] | list[tuple[str, int]]:
        peek_calls.append((queue.name, after_timestamp))
        return real_peek_many(
            queue,
            limit,
            with_timestamps=with_timestamps,
            after_timestamp=after_timestamp,
            before_timestamp=before_timestamp,
            include_claimed=include_claimed,
        )

    monkeypatch.setattr(Queue, "peek_many", counting_peek_many)

    counts = {
        thread.name: thread.unread_count
        for thread in alice.list_threads(all_threads=True)
    }

    assert counts == {"caught-up-a": 0, "caught-up-b": 0, "unread": 1}
    assert peek_calls == [("unread", membership["last_seen_ts"])]


def test_list_unread_count_is_exact_through_999_and_then_saturates(
    tmp_path: Path,
) -> None:
    alice = client(tmp_path, "alice")
    alice.join("general")
    bob = existing_client(tmp_path, "bob")
    bob.join("general")
    alice.read("general")
    body = encode_envelope(
        from_id=bob.whoami().member_id,
        from_name="bob",
        kind="message",
        text="pending",
    )
    queue = bob.queue("general")
    first_ts = queue.generate_timestamp() + 1
    records = [(body, first_ts + offset) for offset in range(1001)]

    try:
        queue.insert_messages(records[:999])
        at_999 = next(
            thread
            for thread in alice.list_threads(all_threads=True)
            if thread.name == "general"
        )

        queue.insert_messages(records[999:])
        above_1000 = next(
            thread
            for thread in alice.list_threads(all_threads=True)
            if thread.name == "general"
        )
    finally:
        queue.close()

    assert at_999.unread_count == 999
    assert format_unread_count(at_999.unread_count) == "999"
    assert above_1000.unread_count == 1000
    assert format_unread_count(above_1000.unread_count) == "999+"


def test_list_converges_after_write_racing_latest_timestamp_probe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    alice = client(tmp_path, "alice")
    alice.join("general")
    bob = existing_client(tmp_path, "bob")
    bob.join("general")
    alice.read("general")
    alice_id = alice.whoami().member_id
    before = alice._state.get_membership(thread="general", member_id=alice_id)
    assert before is not None
    cursor_before = before["last_seen_ts"]
    real_latest_pending_timestamp = Queue.latest_pending_timestamp
    injected: list[Message] = []

    def latest_then_write(queue: Queue) -> int | None:
        prior_latest = real_latest_pending_timestamp(queue)
        if queue.name == "general" and not injected:
            injected.append(bob.say("general", "raced latest timestamp"))
        return prior_latest

    monkeypatch.setattr(
        Queue,
        "latest_pending_timestamp",
        latest_then_write,
    )

    first = next(
        thread
        for thread in alice.list_threads(all_threads=True)
        if thread.name == "general"
    )
    assert first.unread_count == 0
    assert first.unread is False
    assert len(injected) == 1
    after_first = alice._state.get_membership(
        thread="general",
        member_id=alice_id,
    )
    assert after_first is not None
    assert after_first["last_seen_ts"] == cursor_before

    second = next(
        thread
        for thread in alice.list_threads(all_threads=True)
        if thread.name == "general"
    )
    message = injected[0]
    after = alice._state.get_membership(thread="general", member_id=alice_id)

    assert second.unread_count == 1
    assert second.unread is True
    assert second.last_ts == message.ts
    assert after is not None
    assert after["last_seen_ts"] == cursor_before


def test_reply_does_not_skip_message_published_after_membership(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    van = client(tmp_path, "van")
    van.join("general")
    bob = existing_client(tmp_path, "bob")
    bob.join("general")
    root = van.say("general", "root")
    child = f"general.{root.ts}"
    real_write = Queue.write
    inserted = False

    def write_with_gate(queue: Queue, message: str) -> int:
        nonlocal inserted
        if queue.name == child and not inserted:
            inserted = True
            van.reply("general", str(root.ts), "between membership and reply")
        return real_write(queue, message)

    monkeypatch.setattr(Queue, "write", write_with_gate)

    response = bob.reply("general", str(root.ts), "response")

    assert response.thread == child
    assert [message.text for message in bob.read(child)] == [
        "between membership and reply",
        "response",
    ]


def test_reply_full_id_creates_subthread(tmp_path: Path) -> None:
    van = client(tmp_path, "van")
    van.join("general")
    first = van.say("general", "root")

    reply = van.reply("general", str(first.ts), "threaded")

    assert reply.thread == f"general.{first.ts}"
    assert van.log(reply.thread)[0].text == "threaded"


def test_parent_member_can_read_subthread_without_explicit_subthread_join(
    tmp_path: Path,
) -> None:
    van = client(tmp_path, "van")
    van.join("general")
    bob = existing_client(tmp_path, "bob")
    bob.join("general")
    root = van.say("general", "root")
    reply = van.reply("general", str(root.ts), "threaded")

    assert [message.text for message in bob.read(reply.thread)] == ["threaded"]


def test_reply_requires_parent_thread_membership(tmp_path: Path) -> None:
    bob = client(tmp_path, "bob")
    bob.join("general")
    root = bob.say("general", "root")
    van = existing_client(tmp_path, "van")
    van.join("ops")

    with pytest.raises(MembershipError):
        van.reply("general", str(root.ts), "not a member")


def test_client_default_queue_handles_are_transient(tmp_path: Path) -> None:
    van = client(tmp_path, "van")

    first = van.queue("general")
    second = van.queue("general")

    assert first.__class__ is Queue
    assert second.__class__ is Queue
    assert first is not second
    assert first._persistent is False
    assert second._persistent is False


def test_persistent_client_reuses_queue_handles_and_closes_them(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    TautClient.init(db_path=tmp_path / ".taut.db")
    van = TautClient(db_path=tmp_path / ".taut.db", as_name="van", persistent=True)
    closed: list[str] = []
    real_close = Queue.close

    def close_spy(queue: Queue) -> None:
        closed.append(queue.name)
        real_close(queue)

    monkeypatch.setattr(Queue, "close", close_spy)

    first = van.queue("general")
    second = van.queue("general")
    first.has_pending()

    assert first is second
    assert first._persistent is True

    van.close()

    assert closed.count(META_QUEUE_NAME) == 1
    assert closed.count("general") == 1


def test_reply_rejects_missing_short_and_ambiguous_message_ids(
    tmp_path: Path,
) -> None:
    van = client(tmp_path, "van")
    van.join("general")
    queue = van.queue("general")
    queue.insert_messages(
        [
            (
                encode_envelope(
                    from_id=van.whoami().member_id,
                    from_name="van",
                    kind="message",
                    text="first collision",
                ),
                1000000000000004321,
            ),
            (
                encode_envelope(
                    from_id=van.whoami().member_id,
                    from_name="van",
                    kind="message",
                    text="second collision",
                ),
                2000000000000004321,
            ),
        ]
    )

    with pytest.raises(NotFoundError, match="suffix must be at least 4 digits"):
        van.reply("general", "123", "bad")
    with pytest.raises(NotFoundError, match="message not found"):
        van.reply("general", "1234567890123456789", "missing")
    with pytest.raises(AmbiguousMessageError, match="ambiguous message id suffix"):
        van.reply("general", "4321", "ambiguous")


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


def test_set_persona_by_token_updates_persona_and_activity(tmp_path: Path) -> None:
    van = client(tmp_path, "van")
    van.join("general")
    created = van.last_created_member
    assert created is not None
    assert created.token is not None
    before = van.whoami()

    updated = TautClient(
        db_path=tmp_path / ".taut.db", token=created.token
    ).set_persona("reviewer")

    assert updated.member_id == before.member_id
    assert updated.persona == "reviewer"
    assert updated.last_active_ts > before.last_active_ts


def test_set_persona_updates_activity_once_in_the_persona_transaction(
    tmp_path: Path,
) -> None:
    van = client(tmp_path, "van")
    van.join("general")
    created = van.last_created_member
    assert created is not None
    assert created.token is not None
    with van._meta_queue.sidecar(transaction=True) as session:
        session.run("CREATE TABLE persona_activity_audit (updates INTEGER NOT NULL)")
        session.run("INSERT INTO persona_activity_audit (updates) VALUES (0)")
        session.run(
            f"""
            CREATE TRIGGER audit_persona_activity
            AFTER UPDATE OF last_active_ts ON taut_members
            WHEN NEW.member_id = '{created.member_id}'
            BEGIN
                UPDATE persona_activity_audit SET updates = updates + 1;
            END
            """
        )

    TautClient(db_path=tmp_path / ".taut.db", token=created.token).set_persona(
        "reviewer"
    )

    with van._meta_queue.sidecar() as session:
        rows = list(
            session.run(
                "SELECT updates FROM persona_activity_audit",
                fetch=True,
            )
        )
    assert rows == [(1,)]


def test_set_persona_failure_does_not_update_activity(tmp_path: Path) -> None:
    van = client(tmp_path, "van")
    van.join("general")
    created = van.last_created_member
    assert created is not None
    assert created.token is not None
    before = van._state.get_member(created.member_id)
    assert before is not None
    with van._meta_queue.sidecar(transaction=True) as session:
        session.run(
            """
            CREATE TRIGGER reject_persona_update
            BEFORE UPDATE OF meta ON taut_members
            BEGIN
                SELECT RAISE(ABORT, 'persona write blocked');
            END
            """
        )

    with pytest.raises(IntegrityError, match="persona write blocked"):
        TautClient(db_path=tmp_path / ".taut.db", token=created.token).set_persona(
            "reviewer"
        )

    after = van._state.get_member(created.member_id)
    assert after is not None
    assert after["last_active_ts"] == before["last_active_ts"]
    assert after["meta"] == before["meta"]


def test_set_persona_none_clears_persona(tmp_path: Path) -> None:
    van = client(tmp_path, "van")
    van.join("general", persona="reviewer")
    created = van.last_created_member
    assert created is not None
    assert created.token is not None

    cleared = TautClient(
        db_path=tmp_path / ".taut.db", token=created.token
    ).set_persona(None)

    assert cleared.persona is None


def test_set_persona_requires_resolved_member(tmp_path: Path) -> None:
    TautClient.init(db_path=tmp_path / ".taut.db")

    with pytest.raises(IdentityError, match="unrecognized caller"):
        TautClient(db_path=tmp_path / ".taut.db").set_persona("reviewer")


def test_set_persona_missing_named_selector_is_identity_error(tmp_path: Path) -> None:
    TautClient.init(db_path=tmp_path / ".taut.db")

    with pytest.raises(IdentityError, match="unrecognized caller"):
        TautClient(db_path=tmp_path / ".taut.db", as_name="missing").set_persona(
            "reviewer"
        )


def test_set_persona_does_not_change_membership_cursor_or_notices(
    tmp_path: Path,
) -> None:
    van = client(tmp_path, "van")
    van.join("general")
    created = van.last_created_member
    assert created is not None
    assert created.token is not None
    member_id = created.member_id
    memberships_before = van._state.list_memberships(member_id)
    messages_before = [
        (message.ts, message.kind, message.text) for message in van.log("general")
    ]

    token_client = TautClient(db_path=tmp_path / ".taut.db", token=created.token)
    token_client.set_persona("reviewer")

    assert token_client._state.list_memberships(member_id) == memberships_before
    assert [
        (message.ts, message.kind, message.text)
        for message in token_client.log("general")
    ] == messages_before


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


def test_direct_message_reply_keeps_existing_unread_cursor(tmp_path: Path) -> None:
    van = client(tmp_path, "van")
    bob = existing_client(tmp_path, "bob")
    van.join("general")
    bob.join("general")

    first = van.say("@bob", "first")
    second = bob.say("@van", "second")

    assert first.thread == second.thread
    listed = next(
        thread
        for thread in bob.list_threads(all_threads=True)
        if thread.name == first.thread
    )
    assert listed.unread_count == 2


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


def test_reply_notifies_parent_author_until_they_join_child(tmp_path: Path) -> None:
    van = client(tmp_path, "van")
    van.join("general")
    bob = existing_client(tmp_path, "bob")
    bob.join("general")
    root = van.say("general", "root")

    reply = bob.reply("general", str(root.ts), "answer")

    notifications = van.inbox()
    assert [(item.type, item.thread, item.message_ts) for item in notifications] == [
        ("reply", reply.thread, reply.ts)
    ]
    with pytest.raises(EmptyResultError):
        van.inbox()
    assert [message.text for message in van.log(reply.thread)] == ["answer"]


def test_reply_notifications_repeat_stop_on_join_and_resume_after_leave(
    tmp_path: Path,
) -> None:
    van = client(tmp_path, "van")
    van.join("general")
    bob = existing_client(tmp_path, "bob")
    bob.join("general")
    root = van.say("general", "root")

    first = bob.reply("general", str(root.ts), "first")
    second = bob.reply("general", str(root.ts), "second")
    assert [item.message_ts for item in van.inbox()] == [first.ts, second.ts]

    van.read(first.thread)
    bob.reply("general", str(root.ts), "while joined")
    with pytest.raises(EmptyResultError):
        van.inbox()

    van.leave(first.thread)
    after_leave = bob.reply("general", str(root.ts), "after leave")
    assert [item.message_ts for item in van.inbox()] == [after_leave.ts]


def test_reply_join_race_may_emit_one_stale_pointer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """[IAN-7.2] post-commit membership observation permits one stale pointer."""

    van = client(tmp_path, "van")
    van.join("general")
    bob = existing_client(tmp_path, "bob")
    bob.join("general")
    root = van.say("general", "root")
    child_thread = f"general.{root.ts}"
    van_id = van.whoami().member_id
    observed_absence = threading.Event()
    joined = threading.Event()
    real_get_membership = SqlSidecarTautState.get_membership
    gated = False

    def get_membership_with_join_barrier(
        state: SqlSidecarTautState,
        *,
        thread: str,
        member_id: str,
    ) -> MembershipRow | None:
        nonlocal gated
        membership = real_get_membership(
            state,
            thread=thread,
            member_id=member_id,
        )
        if (
            state is bob._state
            and not gated
            and membership is None
            and thread == child_thread
            and member_id == van_id
        ):
            gated = True
            observed_absence.set()
            if not joined.wait(timeout=3.0):
                raise AssertionError("parent did not join before notification dispatch")
        return membership

    monkeypatch.setattr(
        SqlSidecarTautState,
        "get_membership",
        get_membership_with_join_barrier,
    )
    replies: list[Message] = []
    errors: list[BaseException] = []

    def post_reply() -> None:
        try:
            replies.append(bob.reply("general", str(root.ts), "raced reply"))
        except BaseException as exc:  # pragma: no cover - asserted below
            errors.append(exc)

    worker = threading.Thread(target=post_reply)
    worker.start()
    try:
        assert observed_absence.wait(timeout=3.0)
        assert [message.text for message in van.read(child_thread)] == ["raced reply"]
    finally:
        joined.set()
        worker.join(timeout=3.0)

    assert not worker.is_alive()
    assert errors == []
    assert len(replies) == 1
    stale = van.inbox()
    assert [(item.type, item.thread) for item in stale] == [("reply", child_thread)]

    bob.reply("general", str(root.ts), "after join")
    with pytest.raises(EmptyResultError):
        van.inbox()


def test_reply_mention_to_parent_author_is_not_duplicated(tmp_path: Path) -> None:
    van = client(tmp_path, "van")
    van.join("general")
    bob = existing_client(tmp_path, "bob")
    bob.join("general")
    root = van.say("general", "root")

    reply = bob.reply("general", str(root.ts), "answer @van")

    notifications = van.inbox()
    assert [(item.type, item.message_ts) for item in notifications] == [
        ("reply", reply.ts)
    ]


def test_self_reply_and_foreign_parent_do_not_create_reply_notifications(
    tmp_path: Path,
) -> None:
    van = client(tmp_path, "van")
    van.join("general")
    own_root = van.say("general", "own root")
    van.reply("general", str(own_root.ts), "self reply")
    with pytest.raises(EmptyResultError):
        van.inbox()

    bob = existing_client(tmp_path, "bob")
    bob.join("general")
    queue = bob.queue("general")
    foreign_ts = queue.generate_timestamp()
    queue.insert_messages([("foreign parent", foreign_ts)])
    bob.reply("general", str(foreign_ts), "foreign reply")

    with pytest.raises(EmptyResultError):
        van.inbox()


def test_self_and_unknown_mentions_do_not_create_notifications(tmp_path: Path) -> None:
    van = client(tmp_path, "van")
    van.join("general")

    van.say("general", "hello @van and @missing")

    with pytest.raises(EmptyResultError):
        van.inbox()


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


def test_log_validates_limit_since_and_empty_result(tmp_path: Path) -> None:
    van = client(tmp_path, "van")
    notice = van.join("general")

    with pytest.raises(ValueError, match="limit must be positive"):
        van.log("general", limit=0)
    with pytest.raises(ValueError):
        van.log("general", since="not-a-timestamp")
    with pytest.raises(EmptyResultError, match="empty"):
        van.log("general", since=notice.ts)

    van.say("general", "one")
    van.say("general", "two")

    assert [message.text for message in van.log("general", limit=1)] == ["two"]


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


def _start_rename_marker(
    tmp_path: Path,
    *,
    old_name: str,
    new_name: str,
    affected: list[dict[str, str]],
) -> None:
    # White-box setup: public APIs never leave this crash-window marker behind.
    # This simulates a rename interrupted between the broker queue-rename pass
    # and the sidecar apply/complete transaction.
    queue = Queue(META_QUEUE_NAME, db_path=str(tmp_path / ".taut.db"))
    try:
        state = SqlSidecarTautState(queue, SQLITE_SQL_DIALECT)
        state.start_channel_rename(
            old_name=old_name,
            new_name=new_name,
            affected=affected,
            started_ts=queue.generate_timestamp(),
        )
    finally:
        queue.close()


def test_rename_resume_completes_interrupted_rename(tmp_path: Path) -> None:
    van = client(tmp_path, "van")
    van.join("general")
    root = van.say("general", "root")
    van.reply("general", str(root.ts), "threaded")
    sub_old = f"general.{root.ts}"
    sub_new = f"ops.{root.ts}"
    affected = [
        {"old": "general", "new": "ops"},
        {"old": sub_old, "new": sub_new},
    ]
    _start_rename_marker(
        tmp_path, old_name="general", new_name="ops", affected=affected
    )
    # Crash-window simulation, continued: only a strict subset of the affected
    # queues was renamed before the interruption.
    with open_broker(str(tmp_path / ".taut.db")) as broker:
        broker.rename_queue("general", "ops", retarget_aliases=False)

    blocked = "run 'taut rename general ops' to finish it"
    with pytest.raises(TautError, match=blocked):
        van.say("general", "blocked")
    with pytest.raises(TautError, match=blocked):
        van.join("elsewhere")
    with pytest.raises(TautError, match=blocked):
        van.list_threads()

    renamed = van.rename_channel("general", "ops")

    assert renamed.name == "ops"
    # Full history is readable under the new name; message bodies untouched.
    assert [message.text for message in van.log("ops")] == [
        "van created #general",
        "root",
    ]
    assert [message.text for message in van.log(sub_new)] == ["threaded"]
    # Membership moved with the registry row: van posts without rejoining.
    assert van.say("ops", "after recovery").thread == "ops"
    # No marker left: rerunning the rename is a normal channel-not-found error.
    with pytest.raises(NotFoundError, match="channel not found: general"):
        van.rename_channel("general", "ops")


def test_rename_resume_requires_matching_names(tmp_path: Path) -> None:
    van = client(tmp_path, "van")
    van.join("alpha")
    _start_rename_marker(
        tmp_path,
        old_name="alpha",
        new_name="beta",
        affected=[{"old": "alpha", "new": "beta"}],
    )

    with pytest.raises(
        TautError,
        match=(
            "incomplete channel rename exists: alpha -> beta; "
            "run 'taut rename alpha beta' to finish it"
        ),
    ):
        van.rename_channel("alpha", "gamma")


def test_rename_resume_aborts_when_foreign_queue_occupies_target(
    tmp_path: Path,
) -> None:
    van = client(tmp_path, "van")
    van.join("general")
    van.say("general", "root")
    _start_rename_marker(
        tmp_path,
        old_name="general",
        new_name="ops",
        affected=[{"old": "general", "new": "ops"}],
    )
    # Crash-window simulation, continued: a foreign queue appears at the
    # target name before recovery runs.
    queue = Queue("ops", db_path=str(tmp_path / ".taut.db"))
    try:
        queue.write("foreign occupant")
    finally:
        queue.close()

    with pytest.raises(TautError, match="target queue already exists: ops"):
        van.rename_channel("general", "ops")

    # Nothing merged or overwritten; the marker still blocks other commands.
    with pytest.raises(TautError, match="run 'taut rename general ops'"):
        van.say("general", "still blocked")


def test_rename_resume_converges_registry_when_queues_are_absent(
    tmp_path: Path,
) -> None:
    van = client(tmp_path, "van")
    van.join("quiet")
    # White-box setup: drain the channel queue so both the old and new queue
    # names are absent (the normal broker state for an empty channel), then
    # leave a crash-window marker behind.
    queue = Queue("quiet", db_path=str(tmp_path / ".taut.db"))
    try:
        while queue.read_one() is not None:
            pass
    finally:
        queue.close()
    _start_rename_marker(
        tmp_path,
        old_name="quiet",
        new_name="calm",
        affected=[{"old": "quiet", "new": "calm"}],
    )

    renamed = van.rename_channel("quiet", "calm")

    assert renamed.name == "calm"
    assert van.say("calm", "hello").thread == "calm"
    with pytest.raises(NotFoundError, match="channel not found: quiet"):
        van.rename_channel("quiet", "calm")


# ---------------------------------------------------------------------------
# [IAN-3.3] step 4 (agent anchor match) and [IAN-9] first-contact retry.
# Synthetic captures are injected only through the public
# ``TautClient(identity_capture=...)`` seam.
# ---------------------------------------------------------------------------


def _anchor_capture(
    *,
    pid: int = 4242,
    start_time: str = "anchor-start",
    cwd: str = "/workspace/one",
    host_id: str = "host:test",
    executable: str = "workerbot",
) -> identity.IdentityCapture:
    process = identity.ProcessInfo(
        pid=pid,
        ppid=1,
        start_time=start_time,
        exe=f"/usr/local/bin/{executable}",
        argv=(executable,),
        uid=501,
        pgid=pid,
        session_id=99,
        tty="ttys009",
        cwd=cwd,
    )
    return identity.IdentityCapture(
        chain=(process,),
        host=identity.HostIdentity(host_id, "test-host"),
        uid=501,
        login="tester",
        anchor=process,
        kind="agent",
        rule="test capture",
    )


def _human_capture(*, login: str = "van") -> identity.IdentityCapture:
    return identity.IdentityCapture(
        chain=(),
        host=identity.HostIdentity("host:test", "test-host"),
        uid=501,
        login=login,
        anchor=None,
        kind="human",
        rule="test capture",
    )


def test_automatic_agent_name_capitalizes_first_ascii_letter(tmp_path: Path) -> None:
    TautClient.init(db_path=tmp_path / ".taut.db")
    client = TautClient(
        db_path=tmp_path / ".taut.db",
        identity_capture=_anchor_capture(executable="codex"),
    )

    client.join("general")

    assert client.whoami().name == "Codex"


def test_automatic_human_name_capitalizes_first_ascii_letter(tmp_path: Path) -> None:
    TautClient.init(db_path=tmp_path / ".taut.db")
    client = TautClient(
        db_path=tmp_path / ".taut.db",
        identity_capture=_human_capture(login="van"),
    )

    client.join("general")

    assert client.whoami().name == "Van"


def test_repeated_pi_agents_use_capitalized_curated_names(
    tmp_path: Path,
) -> None:
    TautClient.init(db_path=tmp_path / ".taut.db")
    db = tmp_path / ".taut.db"
    pi = TautClient(
        db_path=db,
        identity_capture=_anchor_capture(
            pid=101,
            start_time="pi-start",
            executable="pi",
        ),
    )
    tau = TautClient(
        db_path=db,
        identity_capture=_anchor_capture(
            pid=202,
            start_time="tau-start",
            executable="pi",
        ),
    )
    phi = TautClient(
        db_path=db,
        identity_capture=_anchor_capture(
            pid=303,
            start_time="phi-start",
            executable="pi",
        ),
    )

    pi.join("general")
    tau.join("general")
    phi.join("general")

    assert pi.whoami().name == "Pi"
    assert tau.whoami().name == "Tau"
    assert phi.whoami().name == "Phi"
    assert (
        TautClient(db_path=db, as_name="pi").whoami().member_id == pi.whoami().member_id
    )


def test_automatic_name_skips_alias_owned_route(tmp_path: Path) -> None:
    TautClient.init(db_path=tmp_path / ".taut.db")
    db = tmp_path / ".taut.db"
    owner = TautClient(db_path=db, as_name="owner")
    owner.join("general")
    owner._state.add_member_alias(
        member_id=owner.whoami().member_id,
        alias="codex",
        created_ts=1,
    )
    automatic = TautClient(
        db_path=db,
        identity_capture=_anchor_capture(
            pid=505,
            start_time="alias-collision-start",
            executable="codex",
        ),
    )

    automatic.join("general")

    assert automatic.whoami().name == "Codette"


def test_anchor_match_recovers_member_after_anchor_chdir(tmp_path: Path) -> None:
    """[IAN-3.3] step 4: a live anchor that chdir()s keeps its member."""
    TautClient.init(db_path=tmp_path / ".taut.db")
    db = tmp_path / ".taut.db"
    before = _anchor_capture(cwd="/workspace/one")
    after = _anchor_capture(cwd="/workspace/two")
    established = TautClient(db_path=db, identity_capture=before)
    established.join("general")
    member = established.whoami()

    moved = TautClient(db_path=db, identity_capture=after).whoami(explain=True)

    assert moved.member_id == member.member_id
    assert moved.explain is not None
    assert moved.explain["rule"] == "anchor match"

    # The healing claim was recorded: a subsequent client with the same
    # post-chdir capture resolves at step 3 (identity claim), not step 4.
    healed = TautClient(db_path=db, identity_capture=after).whoami(explain=True)
    assert healed.member_id == member.member_id
    assert healed.explain is not None
    assert healed.explain["rule"] == "identity claim"


def test_join_persona_applies_through_anchor_match(tmp_path: Path) -> None:
    """``join --persona`` resolving via anchor match must set the persona."""
    TautClient.init(db_path=tmp_path / ".taut.db")
    db = tmp_path / ".taut.db"
    first = TautClient(db_path=db, identity_capture=_anchor_capture())
    first.join("general")
    member = first.whoami()

    after = _anchor_capture(cwd="/workspace/two")
    TautClient(db_path=db, identity_capture=after).join("general", persona="reviewer")

    resolved = TautClient(db_path=db, identity_capture=after).whoami()
    assert resolved.member_id == member.member_id
    assert resolved.persona == "reviewer"


def test_anchor_match_never_matches_across_hosts(tmp_path: Path) -> None:
    TautClient.init(db_path=tmp_path / ".taut.db")
    db = tmp_path / ".taut.db"
    established = TautClient(db_path=db, identity_capture=_anchor_capture())
    established.join("general")
    member = established.whoami()

    other_host = _anchor_capture(cwd="/workspace/two", host_id="host:elsewhere")
    with pytest.raises(IdentityError, match="unrecognized caller"):
        TautClient(db_path=db, identity_capture=other_host).whoami()

    stranger = TautClient(db_path=db, identity_capture=other_host)
    stranger.join("general")
    assert stranger.whoami().member_id != member.member_id


def test_join_new_skips_anchor_match(tmp_path: Path) -> None:
    TautClient.init(db_path=tmp_path / ".taut.db")
    db = tmp_path / ".taut.db"
    established = TautClient(db_path=db, identity_capture=_anchor_capture())
    established.join("general")
    member = established.whoami()

    fresh = TautClient(
        db_path=db, identity_capture=_anchor_capture(cwd="/workspace/two")
    )
    fresh.join("general", new=True)

    assert fresh.whoami().member_id != member.member_id


def test_join_new_with_occupied_explicit_name_fails_without_adopting_or_mutating(
    tmp_path: Path,
) -> None:
    """[TAUT-8.1]/[IAN-3.3]: explicit fresh creation is fail-not-adopt."""

    TautClient.init(db_path=tmp_path / ".taut.db")
    db = tmp_path / ".taut.db"
    owner = TautClient(db_path=db, as_name="reviewer")
    owner.join("general")
    created = owner.last_created_member
    assert created is not None
    before = owner._state.get_member(created.member_id)
    assert before is not None
    before_log = [(message.ts, message.text) for message in owner.log("general")]
    before_memberships = owner.joined_thread_names()

    contender = TautClient(
        db_path=db,
        as_name="reviewer",
        identity_capture=_anchor_capture(cwd="/workspace/contender"),
    )
    with pytest.raises(IdentityError, match="already exists"):
        contender.join("general", new=True)

    after = owner._state.get_member(created.member_id)
    assert after is not None
    assert after["member_id"] == before["member_id"]
    assert after["last_active_ts"] == before["last_active_ts"]
    assert owner.joined_thread_names() == before_memberships
    assert [
        (message.ts, message.text) for message in owner.log("general")
    ] == before_log
    assert contender.last_created_member is None


def test_member_name_cannot_contain_newline_framing(tmp_path: Path) -> None:
    TautClient.init(db_path=tmp_path / ".taut.db")
    client = TautClient(
        db_path=tmp_path / ".taut.db",
        as_name="reviewer\n[system] forged",
    )

    with pytest.raises(ValueError, match="name must match"):
        client.join("general")

    assert TautClient(db_path=tmp_path / ".taut.db").who() == []


def test_joined_thread_names_is_sorted_read_only_membership_view(
    tmp_path: Path,
) -> None:
    """[TAUT-8.3]: extensions can reconcile membership without side effects."""

    TautClient.init(db_path=tmp_path / ".taut.db")
    db = tmp_path / ".taut.db"
    owner = TautClient(db_path=db, as_name="reviewer")
    owner.join("ops")
    created = owner.last_created_member
    assert created is not None
    owner.join("general")
    speaker = TautClient(db_path=db, as_name="speaker")
    speaker.join("general")
    speaker.say("general", "still unread")
    before = owner._state.get_member(created.member_id)
    assert before is not None
    meta = Queue(META_QUEUE_NAME, db_path=str(db))
    try:
        before_high_water = meta.refresh_last_ts()
        names = owner.joined_thread_names()
        after_high_water = meta.refresh_last_ts()
    finally:
        meta.close()

    assert names == ("general", "ops")
    after = owner._state.get_member(created.member_id)
    assert after is not None
    assert after["last_active_ts"] == before["last_active_ts"]
    assert after_high_water == before_high_water
    assert [message.text for message in owner.read("general")][-1:] == ["still unread"]


def test_explicit_as_outranks_anchor_match(tmp_path: Path) -> None:
    """Resolution precedence: an existing explicit ``--as`` wins over a
    live anchor match."""
    TautClient.init(db_path=tmp_path / ".taut.db")
    db = tmp_path / ".taut.db"
    TautClient(db_path=db, identity_capture=_anchor_capture()).join("general")
    TautClient(db_path=db, as_name="other").join("general")

    after = _anchor_capture(cwd="/workspace/two")
    resolved = TautClient(db_path=db, as_name="other", identity_capture=after).whoami(
        explain=True
    )

    assert resolved.name == "other"
    assert resolved.explain is not None
    assert resolved.explain["rule"] == "explicit --as"


def test_first_contact_join_retries_next_name_after_losing_race(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """[IAN-9] first-contact retry, deterministic form.

    This is the plan-named fallback for the racing-join proof (S3 in
    docs/plans/2026-07-06-evaluation-findings-remediation-plan.md): forcing a
    reliable 5-process overlap is inherently flaky, so the concurrent winner
    is injected between the loser's name snapshot and its ``insert_member``
    call through the real state API. The state layer is not mocked: the
    wrapper delegates to the real ``route_keys_in_use`` and the injected
    winner performs a real ``join``.
    """
    TautClient.init(db_path=tmp_path / ".taut.db")
    db = tmp_path / ".taut.db"
    winner = TautClient(
        db_path=db, identity_capture=_anchor_capture(pid=101, start_time="w-start")
    )
    loser = TautClient(
        db_path=db, identity_capture=_anchor_capture(pid=202, start_time="l-start")
    )

    original = SqlSidecarTautState.route_keys_in_use
    fired = {"done": False}

    def racing(self: SqlSidecarTautState) -> set[str]:
        names = original(self)
        if self is loser._state and not fired["done"]:
            fired["done"] = True
            winner.join("general")
        return names

    monkeypatch.setattr(SqlSidecarTautState, "route_keys_in_use", racing)

    loser.join("general")

    winner_member = winner.whoami()
    loser_member = loser.whoami()
    assert winner_member.member_id != loser_member.member_id
    assert winner_member.name != loser_member.name


def test_first_contact_retry_is_bounded_and_names_last_candidate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The retry loop is bounded at 5 attempts and fails naming the last
    auto-chosen candidate."""
    TautClient.init(db_path=tmp_path / ".taut.db")
    db = tmp_path / ".taut.db"
    joiner = TautClient(
        db_path=db, identity_capture=_anchor_capture(pid=303, start_time="b-start")
    )

    original = SqlSidecarTautState.route_keys_in_use
    counter = {"ts": 1000}

    def always_racing(self: SqlSidecarTautState) -> set[str]:
        names = original(self)
        # Steal exactly the candidate the joiner is about to choose, via the
        # real state API, then hand back the now-stale snapshot.
        candidate = identity.choose_name(
            seed="workerbot", taken=names, fallback="agent"
        )
        counter["ts"] += 1
        original_insert(
            self,
            member_id=identity.random_member_id(),
            display_name=candidate,
            kind="agent",
            uid=501,
            host_id="host:test",
            host_label="test-host",
            anchor_pid=None,
            anchor_start_time=None,
            fingerprint=None,
            token=identity.mint_token(),
            meta={},
            created_ts=counter["ts"],
        )
        return names

    original_insert = SqlSidecarTautState.insert_member
    monkeypatch.setattr(SqlSidecarTautState, "route_keys_in_use", always_racing)

    with pytest.raises(IdentityError, match="last candidate"):
        joiner.join("general")


def test_explicit_name_collision_keeps_failing_loudly(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The first-contact retry applies only to auto-chosen names: an explicit
    ``--as`` name that loses the create race fails, never renames."""
    TautClient.init(db_path=tmp_path / ".taut.db")
    db = tmp_path / ".taut.db"
    winner = TautClient(
        db_path=db,
        as_name="dup",
        identity_capture=_anchor_capture(pid=101, start_time="w-start"),
    )
    loser = TautClient(
        db_path=db,
        as_name="dup",
        identity_capture=_anchor_capture(pid=202, start_time="l-start"),
    )

    original_insert = SqlSidecarTautState.insert_member
    fired = {"done": False}

    def racing_insert(self: SqlSidecarTautState, **kwargs: object) -> object:
        # The winner claims the explicit name between the loser's
        # route-availability check and its insert (real state API, no mock).
        if not fired["done"]:
            fired["done"] = True
            winner.join("general")
        return original_insert(self, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(SqlSidecarTautState, "insert_member", racing_insert)

    with pytest.raises(IdentityError):
        loser.join("general")

    assert [member.name for member in winner.who()] == ["dup"]


def test_dm_mention_of_non_participant_creates_no_notification(tmp_path: Path) -> None:
    van = client(tmp_path, "van")
    bob = existing_client(tmp_path, "bob")
    carol = existing_client(tmp_path, "carol")
    van.join("general")
    bob.join("general")
    carol.join("general")

    van.say("@bob", "ask @carol about the rollout")

    with pytest.raises(EmptyResultError):
        carol.inbox()
    assert [item.type for item in bob.inbox()] == ["dm_started"]


def test_dm_first_message_mentioning_partner_notifies_mention_once(
    tmp_path: Path,
) -> None:
    van = client(tmp_path, "van")
    bob = existing_client(tmp_path, "bob")
    van.join("general")
    bob.join("general")

    message = van.say("@bob", "ping @bob")

    # A first DM message legitimately carries two notifications: the mention
    # written during message insert plus dm_started after it — assert
    # per-type counts, never a bare total.
    notifications = bob.inbox()
    mentions = [item for item in notifications if item.type == "mention"]
    started = [item for item in notifications if item.type == "dm_started"]
    assert len(mentions) == 1
    assert mentions[0].message_ts == message.ts
    assert len(started) == 1


def test_dm_started_notification_precedes_sender_cursor_probe_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Task 2 ordering: a failed catch-up cannot suppress a committed DM pointer."""

    van = client(tmp_path, "van")
    bob = existing_client(tmp_path, "bob")
    van.join("general")
    bob.join("general")

    def fail_cursor_probe(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("cursor probe failed")

    monkeypatch.setattr(
        TautClient,
        "_advance_sender_if_no_intervening",
        fail_cursor_probe,
    )

    with pytest.raises(RuntimeError, match="cursor probe failed"):
        van.say("@bob", "committed before catch-up")

    assert [item.type for item in bob.inbox()] == ["dm_started"]
    assert [message.text for message in bob.read()] == ["committed before catch-up"]


def test_dm_mentions_suppressed_when_registry_row_lacks_members_meta(
    tmp_path: Path,
) -> None:
    van = client(tmp_path, "van")
    bob = existing_client(tmp_path, "bob")
    van.join("general")
    bob.join("general")
    van_id = van.whoami().member_id
    bob_id = bob.whoami().member_id
    thread = addressing.dm_queue_name(van_id, bob_id)

    # White-box seeding (corrupted-registry simulation): the public API
    # always writes members meta on DM registry rows; fabricate the DM row
    # without it so the participant lookup has nothing to scope by.
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

    van.say("@bob", "hello @bob")

    assert van.last_notification_warnings == [
        "mention notifications suppressed: direct-message registry row for "
        f"{thread} lacks participant metadata"
    ]
    with pytest.raises(EmptyResultError):
        bob.inbox()


@pytest.mark.parametrize(
    "members_builder",
    [
        pytest.param(lambda van_id, bob_id, eve_id: [], id="zero-members"),
        pytest.param(lambda van_id, bob_id, eve_id: [van_id], id="one-member"),
        pytest.param(
            lambda van_id, bob_id, eve_id: [van_id, bob_id, eve_id],
            id="three-members",
        ),
        pytest.param(
            lambda van_id, bob_id, eve_id: [van_id, van_id], id="duplicate-member"
        ),
    ],
)
def test_dm_mentions_suppressed_on_wrong_participant_cardinality(
    tmp_path: Path,
    members_builder: Callable[[str, str, str], list[str]],
) -> None:
    """[IAN-5.2]/[IAN-6.4]: a DM has exactly two distinct participants; any
    other ``members`` cardinality is corrupt metadata and must scope every
    mention out — a three-member list must not let the third id receive a
    notification carrying the ``dm.d_*`` queue name."""

    van = client(tmp_path, "van")
    bob = existing_client(tmp_path, "bob")
    eve = existing_client(tmp_path, "eve")
    van.join("general")
    bob.join("general")
    eve.join("general")
    van_id = van.whoami().member_id
    bob_id = bob.whoami().member_id
    eve_id = eve.whoami().member_id
    thread = addressing.dm_queue_name(van_id, bob_id)

    # White-box seeding (corrupted-registry simulation), as above.
    queue = Queue(META_QUEUE_NAME, db_path=str(tmp_path / ".taut.db"))
    try:
        SqlSidecarTautState(queue, SQLITE_SQL_DIALECT).upsert_thread(
            name=thread,
            kind="dm",
            parent=None,
            origin_ts=None,
            created_by=van_id,
            meta={"members": members_builder(van_id, bob_id, eve_id)},
            created_ts=queue.generate_timestamp(),
        )
    finally:
        queue.close()

    van.say("@bob", "hello @bob and @eve")

    assert van.last_notification_warnings == [
        "mention notifications suppressed: direct-message registry row for "
        f"{thread} lacks participant metadata"
    ]
    with pytest.raises(EmptyResultError):
        eve.inbox()
    with pytest.raises(EmptyResultError):
        bob.inbox()


def test_reply_suffix_miss_names_the_scan_window(tmp_path: Path) -> None:
    van = client(tmp_path, "van")
    van.join("general")
    van.say("general", "root")

    with pytest.raises(
        NotFoundError,
        match="message not found in the most recent 1,000 messages of general; "
        "use the full 19-digit id",
    ):
        van.reply("general", "1234509876", "missing")


def test_reply_suffix_prefers_in_window_match_over_evicted_older_message(
    tmp_path: Path,
) -> None:
    # [TAUT-8.1]: suffix resolution scans only the most recent 1,000 message
    # ids, so a suffix shared by an evicted older message and an in-window
    # recent message resolves to the recent one instead of raising ambiguity.
    van = client(tmp_path, "van")
    van.join("general")
    member_id = van.whoami().member_id
    old_ts = 1000000000000994321
    recent_ts = 1200000000000994321

    def envelope(text: str) -> str:
        return encode_envelope(
            from_id=member_id, from_name="van", kind="message", text=text
        )

    queue = van.queue("general")
    queue.insert_messages([(envelope("old collision"), old_ts)])
    queue.insert_messages(
        [(envelope(f"filler {i}"), 1100000000000000000 + i) for i in range(1000)]
    )
    queue.insert_messages([(envelope("recent collision"), recent_ts)])

    reply = van.reply("general", "994321", "resolved to recent")

    assert reply.thread == f"general.{recent_ts}"
