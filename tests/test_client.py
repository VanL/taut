from __future__ import annotations

import json
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any, Self, cast

import pytest
from simplebroker import (
    BrokerTarget,
    Queue,
    dump_lines,
    open_broker,
    resolve_broker_target,
)
from simplebroker.ext import IntegrityError

import taut.client._base as client_base
import taut.client._messaging as messaging
from taut import addressing, identity
from taut._constants import META_QUEUE_NAME, NO_DATABASE_MESSAGE, load_config
from taut._exceptions import (
    AmbiguousMessageError,
    BlankMessageError,
    EmptyResultError,
    IdentityError,
    MembershipError,
    NotFoundError,
    NotInitializedError,
    TautError,
    ThreadNameError,
    TokenError,
)
from taut.client import Channel, Message, MessageDeletion, MessageReaction, TautClient
from taut.commands._rendering import format_unread_count
from taut.envelope import encode_envelope
from taut.state import (
    SQLITE_SQL_DIALECT,
    MemberRow,
    MembershipRow,
    SqlSidecarTautState,
)

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


def capture_requests(
    client: TautClient,
    monkeypatch: pytest.MonkeyPatch,
) -> list[identity.IdentityCapture]:
    """Observe full capture selection while preserving the real capture path."""

    real_capture = client._capture
    requests: list[identity.IdentityCapture] = []

    def counted_capture() -> identity.IdentityCapture:
        capture = real_capture()
        requests.append(capture)
        return capture

    monkeypatch.setattr(client, "_capture", counted_capture)
    return requests


def test_explicit_missing_path_does_not_auto_create(tmp_path: Path) -> None:
    with pytest.raises(NotInitializedError):
        TautClient(db_path=tmp_path / ".taut.db")

    assert not (tmp_path / ".taut.db").exists()


@pytest.mark.parametrize("selector", ["db_path", "TAUT_DB"])
def test_explicit_database_selector_rejects_directory_with_init_hint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    selector: str,
) -> None:
    monkeypatch.delenv("TAUT_DB", raising=False)
    if selector == "TAUT_DB":
        monkeypatch.setenv("TAUT_DB", str(tmp_path))

    with pytest.raises(NotInitializedError) as raised:
        if selector == "db_path":
            TautClient(db_path=tmp_path)
        else:
            TautClient()

    assert str(raised.value) == NO_DATABASE_MESSAGE
    assert raised.value.__cause__ is None


def test_resolved_target_config_handoff_bypasses_ambient_resolution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """[TAUT-3.2] A resolved target is frozen without process-global cwd."""

    project = tmp_path / "project"
    project.mkdir()
    db = project / ".taut.db"
    TautClient.init(db_path=db)
    config = dict(load_config({"TAUT_BUSY_TIMEOUT": 1234}))
    target = resolve_broker_target(
        project,
        config=load_config({"TAUT_BUSY_TIMEOUT": 1234}),
    )
    assert target is not None
    target.backend_options["nested"] = {"value": "frozen"}
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    ambient_db = elsewhere / "ambient.db"
    monkeypatch.chdir(elsewhere)
    monkeypatch.setenv("TAUT_DB", str(ambient_db))

    def unexpected_ambient_config(*_: object, **__: object) -> dict[str, object]:
        raise AssertionError("resolved handoff must not reload ambient config")

    monkeypatch.setattr(client_base, "load_config", unexpected_ambient_config)

    client = TautClient(
        broker_target=target,
        broker_config=config,
        as_name="van",
    )
    client.join("general")

    assert client.target == target
    assert isinstance(client.target, BrokerTarget)
    assert client.config["BROKER_BUSY_TIMEOUT"] == 1234
    assert client.joined_thread_names() == ("general",)
    assert not ambient_db.exists()
    config["BROKER_BUSY_TIMEOUT"] = 9999
    assert client.config["BROKER_BUSY_TIMEOUT"] == 1234
    target.backend_options["nested"]["value"] = "mutated"
    assert client.target.backend_options["nested"] == {"value": "frozen"}


def test_client_can_ignore_ambient_identity_for_explicit_token(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """[TAUT-8.3] Multi-workspace embedders isolate explicit identity."""

    db = tmp_path / ".taut.db"
    TautClient.init(db_path=db)
    selected = TautClient(db_path=db, as_name="selected")
    selected.join("general")
    selected_member = selected.last_created_member
    assert selected_member is not None
    assert selected_member.token is not None
    ambient = TautClient(db_path=db, as_name="ambient")
    ambient.join("general")
    ambient_member = ambient.last_created_member
    assert ambient_member is not None

    monkeypatch.setenv("TAUT_AS", "ambient")
    monkeypatch.setenv("TAUT_TOKEN", "wrong-ambient-token")

    isolated = TautClient(
        db_path=db,
        token=selected_member.token,
        inherit_environment_identity=False,
    )

    assert isolated.whoami().member_id == selected_member.member_id
    assert isolated.whoami().member_id != ambient_member.member_id


def test_show_message_returns_exact_row_and_advances_high_water_cursor(
    tmp_path: Path,
) -> None:
    reader = client(tmp_path, "reader")
    reader.join("general")
    writer = existing_client(tmp_path, "writer")
    writer.join("general")
    reader.read("general")
    earlier = writer.say("general", "earlier unread")
    target = writer.say("general", "exact target")
    later = writer.say("general", "later unread")

    shown = reader.show_message(str(target.ts))

    assert shown == target
    membership = reader._state.get_membership(
        thread="general",
        member_id=reader.whoami().member_id,
    )
    assert membership is not None
    assert membership["last_seen_ts"] == target.ts
    assert [message.ts for message in reader.read("general")] == [later.ts]
    assert reader.queue("general").peek_one(exact_timestamp=earlier.ts) is not None
    assert reader.queue("general").peek_one(exact_timestamp=target.ts) is not None


def test_history_around_returns_nearest_context_without_moving_cursor(
    tmp_path: Path,
) -> None:
    reader = client(tmp_path, "reader")
    reader.join("general")
    writer = existing_client(tmp_path, "writer")
    writer.join("general")
    reader.read("general")
    older = writer.say("general", "older")
    previous = writer.say("general", "previous")
    target = writer.say("general", "target")
    following = writer.say("general", "following")
    newer = writer.say("general", "newer")
    reader_id = reader.whoami().member_id
    before = reader._state.get_membership(thread="general", member_id=reader_id)
    assert before is not None

    context = reader.history_around(
        "general",
        str(target.ts),
        before=1,
        after=1,
    )

    assert context == [previous, target, following]
    assert older not in context
    assert newer not in context
    assert reader._state.get_membership(thread="general", member_id=reader_id) == before


def test_history_around_supports_anchor_only_and_reports_exact_miss(
    tmp_path: Path,
) -> None:
    viewer = client(tmp_path, "viewer")
    viewer.join("general")
    viewer.join("other")
    target = viewer.say("general", "target")

    assert viewer.history_around(
        "general",
        str(target.ts),
        before=0,
        after=0,
    ) == [target]
    with pytest.raises(
        NotFoundError,
        match=rf"^message not found in other: {target.ts}$",
    ):
        viewer.history_around("other", str(target.ts))


def test_history_around_uses_actor_scoped_direct_message_visibility(
    tmp_path: Path,
) -> None:
    alice = client(tmp_path, "alice")
    alice.join("general")
    bob = existing_client(tmp_path, "bob")
    bob.join("general")
    outsider = existing_client(tmp_path, "outsider")
    outsider.join("general")
    previous = alice.say("@bob", "previous")
    target = bob.say("@alice", "target")
    following = alice.say("@bob", "following")
    bob_id = bob.whoami().member_id
    member_before = bob._state.get_member(bob_id)
    assert member_before is not None

    assert bob.history_around(
        target.thread,
        str(target.ts),
        before=1,
        after=1,
    ) == [previous, target, following]
    assert bob._state.get_member(bob_id) == member_before
    with pytest.raises(NotFoundError):
        outsider.history_around(target.thread, str(target.ts))


def test_history_around_uses_log_visibility_for_unjoined_channel(
    tmp_path: Path,
) -> None:
    author = client(tmp_path, "author")
    author.join("general")
    target = author.say("general", "visible storage history")
    viewer = existing_client(tmp_path, "viewer")
    viewer.join("other")
    viewer_id = viewer.whoami().member_id

    assert viewer.history_around(
        "general",
        str(target.ts),
        before=0,
        after=0,
    ) == [target]
    assert viewer._state.get_membership(thread="general", member_id=viewer_id) is None


@pytest.mark.parametrize(
    ("value", "exception", "message"),
    [
        (None, TypeError, "msg_id must be a string"),
        ("1234", ValueError, "msg_id must be a full 19-digit message id"),
    ],
)
def test_history_around_validates_exact_id_before_state_work(
    tmp_path: Path,
    value: object,
    exception: type[Exception],
    message: str,
) -> None:
    viewer = client(tmp_path, "viewer")
    initial_threads = viewer._state.list_threads(include_internal=True)

    with pytest.raises(exception, match=rf"^{message}$"):
        viewer.history_around("general", value)  # type: ignore[arg-type]

    assert viewer._state.list_threads(include_internal=True) == initial_threads


@pytest.mark.parametrize(
    ("before", "after", "exception", "message"),
    [
        (True, 0, TypeError, "before must be an integer"),
        (0, False, TypeError, "after must be an integer"),
        (-1, 0, ValueError, "before must be between 0 and 999"),
        (0, 1000, ValueError, "after must be between 0 and 999"),
        (500, 500, ValueError, "before and after must total at most 999"),
    ],
)
def test_history_around_validates_bounds_before_state_work(
    tmp_path: Path,
    before: object,
    after: object,
    exception: type[Exception],
    message: str,
) -> None:
    viewer = client(tmp_path, "viewer")
    initial_threads = viewer._state.list_threads(include_internal=True)

    with pytest.raises(exception, match=rf"^{message}$"):
        viewer.history_around(
            "general",
            "1234567890123456789",
            before=before,  # type: ignore[arg-type]
            after=after,  # type: ignore[arg-type]
        )

    assert viewer._state.list_threads(include_internal=True) == initial_threads


def test_react_to_message_broadcasts_to_current_members_and_advances_cursor(
    tmp_path: Path,
) -> None:
    alice = client(tmp_path, "alice")
    bob = existing_client(tmp_path, "bob")
    carol = existing_client(tmp_path, "carol")
    for member in (alice, bob, carol):
        member.join("general")
    target = bob.say("general", "status?")

    receipt = alice.react_to_message(str(target.ts), "ack")

    assert (
        receipt.thread,
        receipt.message_ts,
        receipt.reaction,
        receipt.audience_count,
    ) == ("general", target.ts, "ack", 2)
    for recipient in (bob, carol):
        notifications = recipient.inbox()
        assert [
            (
                item.type,
                item.to_id,
                item.actor_name,
                item.thread,
                item.message_ts,
                item.reaction,
            )
            for item in notifications
        ] == [("reaction", None, "alice", "general", target.ts, "ack")]
    with pytest.raises(EmptyResultError):
        alice.inbox()
    membership = alice._state.get_membership(
        thread="general",
        member_id=alice.whoami().member_id,
    )
    assert membership is not None
    assert membership["last_seen_ts"] == target.ts
    assert alice.queue("general").peek_one(exact_timestamp=target.ts) is not None


def test_react_to_message_uses_monotonic_high_water_cursor_semantics(
    tmp_path: Path,
) -> None:
    alice = client(tmp_path, "alice")
    bob = existing_client(tmp_path, "bob")
    alice.join("general")
    bob.join("general")
    alice.read("general")
    earlier = bob.say("general", "earlier")
    target = bob.say("general", "target")
    later = bob.say("general", "later")

    alice.react_to_message(str(target.ts), "ack")

    assert [item.ts for item in alice.read("general")] == [later.ts]
    alice.react_to_message(str(earlier.ts), "ack")
    membership = alice._state.get_membership(
        thread="general",
        member_id=alice.whoami().member_id,
    )
    assert membership is not None
    assert membership["last_seen_ts"] == later.ts
    assert [item.reaction for item in bob.inbox()] == ["ack", "ack"]


@pytest.mark.parametrize(
    ("reaction", "exception", "message"),
    [
        (None, TypeError, "reaction must be a string"),
        (True, TypeError, "reaction must be a string"),
        ("Ack", ValueError, r"reaction must match \^\[a-z0-9\]"),
        ("not-enabled", ValueError, "reaction must be one of: ack, blocked"),
    ],
)
def test_react_to_message_validates_reaction_before_state_work(
    tmp_path: Path,
    reaction: object,
    exception: type[Exception],
    message: str,
) -> None:
    actor = client(tmp_path, "actor")
    before_threads = actor._state.list_threads(include_internal=True)
    before_members = actor._state.list_members()

    with pytest.raises(exception, match=message):
        actor.react_to_message("1800000000000000001", reaction)  # type: ignore[arg-type]

    assert actor._state.list_threads(include_internal=True) == before_threads
    assert actor._state.list_members() == before_members


def test_react_to_message_reports_disabled_project_policy_before_state_work(
    tmp_path: Path,
) -> None:
    actor = client(tmp_path, "actor")
    actor._reaction_values = ()
    before_threads = actor._state.list_threads(include_internal=True)

    with pytest.raises(
        ValueError,
        match="^message reactions are disabled by project configuration$",
    ):
        actor.react_to_message("1800000000000000001", "ack")

    assert actor._state.list_threads(include_internal=True) == before_threads


def test_react_to_message_requires_an_ordinary_message(tmp_path: Path) -> None:
    actor = client(tmp_path, "actor")
    notice = actor.join("general")

    with pytest.raises(
        NotFoundError,
        match=rf"^message not found or not reactable: {notice.ts}$",
    ):
        actor.react_to_message(str(notice.ts), "ack")


def test_react_to_message_allows_self_authored_target_with_other_recipient(
    tmp_path: Path,
) -> None:
    alice = client(tmp_path, "alice")
    bob = existing_client(tmp_path, "bob")
    alice.join("general")
    bob.join("general")
    target = alice.say("general", "my message")

    receipt = alice.react_to_message(str(target.ts), "ack")

    assert receipt.audience_count == 1
    assert [item.reaction for item in bob.inbox()] == ["ack"]


def test_react_to_message_requires_a_nonempty_audience_before_cursor_advance(
    tmp_path: Path,
) -> None:
    actor = client(tmp_path, "actor")
    actor.join("general")
    target = actor.say("general", "only member")
    actor_id = actor.whoami().member_id
    before = actor._state.get_membership(thread="general", member_id=actor_id)
    assert before is not None

    with pytest.raises(EmptyResultError, match="^no reaction recipients$"):
        actor.react_to_message(str(target.ts), "ack")

    after = actor._state.get_membership(thread="general", member_id=actor_id)
    assert after == before


def test_react_to_message_uses_exact_subthread_membership(tmp_path: Path) -> None:
    alice = client(tmp_path, "alice")
    bob = existing_client(tmp_path, "bob")
    carol = existing_client(tmp_path, "carol")
    outsider = existing_client(tmp_path, "outsider")
    for member in (alice, bob, carol, outsider):
        member.join("general")
    root = alice.say("general", "root")
    target = bob.reply("general", str(root.ts), "subthread target")
    carol.reply("general", str(root.ts), "joining the subthread")
    alice.reply("general", str(root.ts), "joining to react")

    receipt = alice.react_to_message(str(target.ts), "blocked")

    assert receipt.audience_count == 2
    assert [item.reaction for item in bob.inbox()] == ["blocked"]
    assert [item.reaction for item in carol.inbox()] == ["blocked"]
    with pytest.raises(EmptyResultError):
        outsider.inbox()


def test_react_to_message_snapshots_current_members_not_send_time_members(
    tmp_path: Path,
) -> None:
    alice = client(tmp_path, "alice")
    bob = existing_client(tmp_path, "bob")
    departed = existing_client(tmp_path, "departed")
    for member in (alice, bob, departed):
        member.join("general")
    target = bob.say("general", "target")
    departed.leave("general")
    late = existing_client(tmp_path, "late")
    late.join("general")

    receipt = alice.react_to_message(str(target.ts), "ack")

    assert receipt.audience_count == 2
    assert [item.reaction for item in bob.inbox()] == ["ack"]
    assert [item.reaction for item in late.inbox()] == ["ack"]
    with pytest.raises(EmptyResultError):
        departed.inbox()


def test_react_to_message_keeps_invocation_snapshot_across_membership_race(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    alice = client(tmp_path, "alice")
    bob = existing_client(tmp_path, "bob")
    departed = existing_client(tmp_path, "departed")
    late = existing_client(tmp_path, "late")
    for member in (alice, bob, departed):
        member.join("general")
    late.join("staging")
    target = bob.say("general", "target")
    departed_id = departed.whoami().member_id
    late_id = late.whoami().member_id
    real_list = SqlSidecarTautState.list_thread_members
    snapshots = 0

    def snapshot_then_change(
        state: SqlSidecarTautState,
        thread: str,
    ) -> list[MemberRow]:
        nonlocal snapshots
        rows = real_list(state, thread)
        if state is alice._state and thread == "general" and snapshots == 0:
            snapshots += 1
            departed._state.remove_membership(
                thread="general",
                member_id=departed_id,
            )
            late._state.add_membership(
                thread="general",
                member_id=late_id,
                joined_ts=target.ts,
                last_seen_ts=target.ts,
            )
        return rows

    monkeypatch.setattr(
        SqlSidecarTautState,
        "list_thread_members",
        snapshot_then_change,
    )

    receipt = alice.react_to_message(str(target.ts), "ack")

    assert snapshots == 1
    assert receipt.audience_count == 2
    assert [item.reaction for item in bob.inbox()] == ["ack"]
    assert [item.reaction for item in departed.inbox()] == ["ack"]
    with pytest.raises(EmptyResultError):
        late.inbox()


def test_react_to_message_intersects_dm_membership_with_valid_participants(
    tmp_path: Path,
) -> None:
    alice = client(tmp_path, "alice")
    bob = existing_client(tmp_path, "bob")
    outsider = existing_client(tmp_path, "outsider")
    for member in (alice, bob, outsider):
        member.join("general")
    target = alice.say("@bob", "private target")
    assert [item.type for item in bob.inbox()] == ["dm_started"]
    outsider_id = outsider.whoami().member_id
    outsider._state.add_membership(
        thread=target.thread,
        member_id=outsider_id,
        joined_ts=target.ts,
        last_seen_ts=0,
    )

    receipt = alice.react_to_message(str(target.ts), "ack")

    assert receipt.audience_count == 1
    assert [item.reaction for item in bob.inbox()] == ["ack"]
    with pytest.raises(EmptyResultError):
        outsider.inbox()
    with pytest.raises(
        NotFoundError,
        match=rf"^message not found or not reactable: {target.ts}$",
    ):
        outsider.react_to_message(str(target.ts), "ack")


def test_react_to_message_fails_closed_for_malformed_dm_metadata(
    tmp_path: Path,
) -> None:
    alice = client(tmp_path, "alice")
    bob = existing_client(tmp_path, "bob")
    alice.join("general")
    bob.join("general")
    target = alice.say("@bob", "private target")
    assert [item.type for item in bob.inbox()] == ["dm_started"]
    with alice._meta_queue.sidecar(transaction=True) as session:
        session.run(
            "UPDATE taut_threads SET meta = ? WHERE name = ?",
            ("{}", target.thread),
        )

    with pytest.raises(
        NotFoundError,
        match=rf"^message not found or not reactable: {target.ts}$",
    ):
        alice.react_to_message(str(target.ts), "ack")

    with pytest.raises(EmptyResultError):
        bob.inbox()


def test_react_to_message_is_best_effort_after_cursor_advance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    alice = client(tmp_path, "alice")
    bob = existing_client(tmp_path, "bob")
    alice.join("general")
    bob.join("general")
    target = bob.say("general", "target")
    calls: list[tuple[str, ...]] = []

    class FailingBroker:
        def __enter__(self) -> Self:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def broadcast(
            self,
            _body: str,
            *,
            queue_names: tuple[str, ...],
            create_missing: bool,
        ) -> None:
            assert create_missing is True
            calls.append(queue_names)
            raise RuntimeError("offline")

    monkeypatch.setattr(
        messaging, "open_broker", lambda *_args, **_kwargs: FailingBroker()
    )

    receipt = alice.react_to_message(str(target.ts), "ack")

    assert receipt == MessageReaction(
        thread="general",
        message_ts=target.ts,
        reaction="ack",
        audience_count=1,
    )
    assert calls == [(addressing.notification_queue_name(bob.whoami().member_id),)]
    assert alice.last_notification_warnings == [
        "reaction notification broadcast failed: offline"
    ]
    membership = alice._state.get_membership(
        thread="general",
        member_id=alice.whoami().member_id,
    )
    assert membership is not None
    assert membership["last_seen_ts"] == target.ts


def test_react_to_message_does_not_broadcast_when_cursor_advance_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    alice = client(tmp_path, "alice")
    bob = existing_client(tmp_path, "bob")
    alice.join("general")
    bob.join("general")
    target = bob.say("general", "target")

    def fail_cursor(_state: SqlSidecarTautState, **_kwargs: object) -> None:
        raise RuntimeError("cursor unavailable")

    monkeypatch.setattr(SqlSidecarTautState, "advance_cursor", fail_cursor)
    monkeypatch.setattr(
        messaging,
        "open_broker",
        lambda *_args, **_kwargs: pytest.fail("broadcast ran before cursor commit"),
    )

    with pytest.raises(RuntimeError, match="^cursor unavailable$"):
        alice.react_to_message(str(target.ts), "ack")

    with pytest.raises(EmptyResultError):
        bob.inbox()


def test_react_to_message_repeats_as_distinct_consumable_events(
    tmp_path: Path,
) -> None:
    alice = client(tmp_path, "alice")
    bob = existing_client(tmp_path, "bob")
    alice.join("general")
    bob.join("general")
    target = bob.say("general", "target")

    alice.react_to_message(str(target.ts), "ack")
    alice.react_to_message(str(target.ts), "ack")

    assert [item.reaction for item in bob.inbox()] == ["ack", "ack"]


def test_reaction_notification_peek_is_observational_and_inbox_consumes(
    tmp_path: Path,
) -> None:
    alice = client(tmp_path, "alice")
    bob = existing_client(tmp_path, "bob")
    alice.join("general")
    bob.join("general")
    target = bob.say("general", "target")
    alice.react_to_message(str(target.ts), "ack")

    assert [item.reaction for item in bob.peek_inbox()] == ["ack"]
    assert [item.reaction for item in bob.peek_inbox()] == ["ack"]
    assert [item.reaction for item in bob.inbox()] == ["ack"]
    with pytest.raises(EmptyResultError):
        bob.inbox()


def test_reaction_pointer_survives_source_message_deletion(tmp_path: Path) -> None:
    alice = client(tmp_path, "alice")
    bob = existing_client(tmp_path, "bob")
    alice.join("general")
    bob.join("general")
    target = alice.say("general", "temporary")
    bob.react_to_message(str(target.ts), "ack")

    alice.delete_message(str(target.ts))

    notification = alice.inbox()[0]
    assert notification.type == "reaction"
    assert notification.message_ts == target.ts
    assert notification.reaction == "ack"


def test_react_to_message_may_emit_stale_pointer_after_lookup_race(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    alice = client(tmp_path, "alice")
    bob = existing_client(tmp_path, "bob")
    alice.join("general")
    bob.join("general")
    target = bob.say("general", "delete after reaction lookup")
    alice_id = alice.whoami().member_id
    real_advance = SqlSidecarTautState.advance_cursor
    deletions: list[MessageDeletion] = []

    def advance_after_delete(
        state: SqlSidecarTautState,
        *,
        thread: str,
        member_id: str,
        seen_ts: int,
    ) -> None:
        if (
            state is alice._state
            and member_id == alice_id
            and seen_ts == target.ts
            and not deletions
        ):
            deletions.append(bob.delete_message(str(target.ts)))
        real_advance(
            state,
            thread=thread,
            member_id=member_id,
            seen_ts=seen_ts,
        )

    monkeypatch.setattr(
        SqlSidecarTautState,
        "advance_cursor",
        advance_after_delete,
    )

    receipt = alice.react_to_message(str(target.ts), "ack")

    assert receipt.audience_count == 1
    assert deletions == [MessageDeletion(thread="general", ts=target.ts)]
    assert bob.queue("general").peek_one(exact_timestamp=target.ts) is None
    notification = bob.inbox()[0]
    assert notification.type == "reaction"
    assert notification.message_ts == target.ts


def test_delete_message_removes_only_owned_exact_row_and_returns_receipt(
    tmp_path: Path,
) -> None:
    van = client(tmp_path, "van")
    van.join("general")
    before = van.say("general", "before")
    target = van.say("general", "delete me")
    after = van.say("general", "after")

    deleted = van.delete_message(str(target.ts))

    assert deleted == MessageDeletion(
        thread="general",
        ts=target.ts,
        deleted=True,
    )
    queue = van.queue("general")
    assert queue.peek_one(exact_timestamp=before.ts) is not None
    assert queue.peek_one(exact_timestamp=target.ts) is None
    assert queue.peek_one(exact_timestamp=after.ts) is not None
    with pytest.raises(
        NotFoundError,
        match=rf"^message not found or not deletable: {target.ts}$",
    ):
        van.delete_message(str(target.ts))


@pytest.mark.parametrize("method_name", ["show_message", "delete_message"])
@pytest.mark.parametrize(
    ("value", "exception", "message"),
    [
        (None, TypeError, "msg_id must be a string"),
        (True, TypeError, "msg_id must be a string"),
        (1234567890123456789, TypeError, "msg_id must be a string"),
        ("1234", ValueError, "msg_id must be a full 19-digit message id"),
        ("123456789012345678", ValueError, "msg_id must be a full 19-digit message id"),
        (
            "12345678901234567890",
            ValueError,
            "msg_id must be a full 19-digit message id",
        ),
        (
            "123456789012345678x",
            ValueError,
            "msg_id must be a full 19-digit message id",
        ),
        (
            "+1234567890123456789",
            ValueError,
            "msg_id must be a full 19-digit message id",
        ),
        (
            "-1234567890123456789",
            ValueError,
            "msg_id must be a full 19-digit message id",
        ),
        (
            " 1234567890123456789",
            ValueError,
            "msg_id must be a full 19-digit message id",
        ),
        (
            "١٢٣٤٥٦٧٨٩٠١٢٣٤٥٦٧٨٩",
            ValueError,
            "msg_id must be a full 19-digit message id",
        ),
        (
            "9223372036854775808",
            ValueError,
            "msg_id must be a full 19-digit message id",
        ),
    ],
)
def test_message_operations_validate_exact_id_before_state_work(
    tmp_path: Path,
    method_name: str,
    value: object,
    exception: type[Exception],
    message: str,
) -> None:
    van = client(tmp_path, "van")
    before_threads = van._state.list_threads(include_internal=True)
    before_members = van._state.list_members()

    with pytest.raises(exception, match=rf"^{message}$"):
        getattr(van, method_name)(value)

    assert van._state.list_threads(include_internal=True) == before_threads
    assert van._state.list_members() == before_members


@pytest.mark.parametrize(
    ("value", "exception", "message"),
    [
        (None, TypeError, "msg_id must be a string"),
        (True, TypeError, "msg_id must be a string"),
        ("1234", ValueError, "msg_id must be a full 19-digit message id"),
        (
            "123456789012345678x",
            ValueError,
            "msg_id must be a full 19-digit message id",
        ),
    ],
)
def test_react_to_message_validates_exact_id_before_state_work(
    tmp_path: Path,
    value: object,
    exception: type[Exception],
    message: str,
) -> None:
    actor = client(tmp_path, "actor")
    before_threads = actor._state.list_threads(include_internal=True)

    with pytest.raises(exception, match=rf"^{message}$"):
        actor.react_to_message(value, "ack")  # type: ignore[arg-type]

    assert actor._state.list_threads(include_internal=True) == before_threads


def test_show_message_is_limited_to_current_memberships(tmp_path: Path) -> None:
    alice = client(tmp_path, "alice")
    alice.join("general")
    bob = existing_client(tmp_path, "bob")
    bob.join("general")
    outsider = existing_client(tmp_path, "outsider")
    outsider.join("general")
    direct = alice.say("@bob", "private to alice and bob")

    with pytest.raises(
        NotFoundError,
        match=rf"^message not found: {direct.ts}$",
    ):
        outsider.show_message(str(direct.ts))


def test_show_message_returns_participant_dm_and_advances_its_cursor(
    tmp_path: Path,
) -> None:
    alice = client(tmp_path, "alice")
    alice.join("general")
    bob = existing_client(tmp_path, "bob")
    bob.join("general")
    direct = alice.say("@bob", "private to alice and bob")
    bob_id = bob.whoami().member_id

    assert bob.show_message(str(direct.ts)) == direct
    membership = bob._state.get_membership(
        thread=direct.thread,
        member_id=bob_id,
    )
    assert membership is not None
    assert membership["last_seen_ts"] == direct.ts
    assert bob.queue(direct.thread).peek_one(exact_timestamp=direct.ts) is not None


def test_show_message_does_not_implicitly_join_an_unjoined_subthread(
    tmp_path: Path,
) -> None:
    alice = client(tmp_path, "alice")
    alice.join("general")
    bob = existing_client(tmp_path, "bob")
    bob.join("general")
    outsider = existing_client(tmp_path, "outsider")
    outsider.join("general")
    root = alice.say("general", "root")
    reply = bob.reply("general", str(root.ts), "child message")
    outsider_id = outsider.whoami().member_id

    with pytest.raises(
        NotFoundError,
        match=rf"^message not found: {reply.ts}$",
    ):
        outsider.show_message(str(reply.ts))

    assert (
        outsider._state.get_membership(
            thread=reply.thread,
            member_id=outsider_id,
        )
        is None
    )


def test_show_message_skips_notification_and_dangling_memberships(
    tmp_path: Path,
) -> None:
    viewer = client(tmp_path, "viewer")
    viewer.join("general")
    member = viewer.whoami()
    body = encode_envelope(
        from_id=member.member_id,
        from_name=member.name,
        kind="message",
        text="must remain out of chat lookup",
    )
    notification_thread = addressing.notification_queue_name(member.member_id)
    notification_ts = viewer.queue(notification_thread).write(body)
    viewer._state.upsert_thread(
        name=notification_thread,
        kind="notification",
        parent=None,
        origin_ts=None,
        created_by=member.member_id,
        meta={},
        created_ts=notification_ts,
    )
    viewer._state.add_membership(
        thread=notification_thread,
        member_id=member.member_id,
        joined_ts=notification_ts,
        last_seen_ts=0,
    )
    dangling_thread = "dangling"
    dangling_ts = viewer.queue(dangling_thread).write(body)
    viewer._state.add_membership(
        thread=dangling_thread,
        member_id=member.member_id,
        joined_ts=dangling_ts,
        last_seen_ts=0,
    )

    for timestamp in (notification_ts, dangling_ts):
        with pytest.raises(
            NotFoundError,
            match=rf"^message not found: {timestamp}$",
        ):
            viewer.show_message(str(timestamp))


def test_show_message_returns_notice_and_foreign_message_shapes(
    tmp_path: Path,
) -> None:
    viewer = client(tmp_path, "viewer")
    notice = viewer.join("general")
    foreign_ts = viewer.queue("general").write("foreign body")

    assert viewer.show_message(str(notice.ts)) == notice
    foreign = viewer.show_message(str(foreign_ts))

    assert foreign.thread == "general"
    assert foreign.ts == foreign_ts
    assert foreign.kind == "foreign"
    assert foreign.text == "foreign body"


def test_show_message_never_regresses_an_equal_or_later_cursor(
    tmp_path: Path,
) -> None:
    reader = client(tmp_path, "reader")
    reader.join("general")
    writer = existing_client(tmp_path, "writer")
    writer.join("general")
    reader.read("general")
    earlier = writer.say("general", "earlier")
    later = writer.say("general", "later")
    reader_id = reader.whoami().member_id
    reader._state.advance_cursor(
        thread="general",
        member_id=reader_id,
        seen_ts=later.ts,
    )

    assert reader.show_message(str(earlier.ts)) == earlier
    assert reader.show_message(str(later.ts)) == later
    membership = reader._state.get_membership(
        thread="general",
        member_id=reader_id,
    )
    assert membership is not None
    assert membership["last_seen_ts"] == later.ts


def test_show_message_cursor_failure_emits_no_result_and_preserves_row(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    author = client(tmp_path, "author")
    author.join("general")
    reader = existing_client(tmp_path, "reader")
    reader.join("general")
    target = author.say("general", "cursor write must succeed first")
    reader_id = reader.whoami().member_id
    before = reader._state.get_membership(
        thread="general",
        member_id=reader_id,
    )
    assert before is not None

    def fail_cursor_write(
        _state: SqlSidecarTautState,
        *,
        thread: str,
        member_id: str,
        seen_ts: int,
    ) -> None:
        raise RuntimeError("injected cursor failure")

    monkeypatch.setattr(SqlSidecarTautState, "advance_cursor", fail_cursor_write)

    with pytest.raises(RuntimeError, match="injected cursor failure"):
        reader.show_message(str(target.ts))

    assert reader.queue("general").peek_one(exact_timestamp=target.ts) is not None
    assert (
        reader._state.get_membership(
            thread="general",
            member_id=reader_id,
        )
        == before
    )


def test_show_message_scans_candidates_once_and_stops_at_match(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    viewer = client(tmp_path, "viewer")
    viewer.join("one")
    viewer.join("two")
    member_id = viewer.whoami().member_id
    candidate_order = [
        row["thread"] for row in viewer._state.list_memberships(member_id)
    ]
    target_thread = candidate_order[0]
    target = viewer.say(target_thread, "first candidate owns target")
    calls: list[str] = []
    found = False
    real_peek = Queue.peek_one

    def track_peek(queue: Queue, *args: object, **kwargs: object) -> object:
        nonlocal found
        if found:
            raise AssertionError("locator continued after its first exact match")
        calls.append(queue.name)
        result = cast(Any, real_peek)(queue, *args, **kwargs)
        if result is not None:
            found = True
        return result

    monkeypatch.setattr(Queue, "peek_one", track_peek)

    assert viewer.show_message(str(target.ts)) == target
    assert calls == candidate_order[: calls.index(target_thread) + 1]
    assert len(calls) == len(set(calls))


def test_delete_message_is_author_only(tmp_path: Path) -> None:
    alice = client(tmp_path, "alice")
    alice.join("general")
    bob = existing_client(tmp_path, "bob")
    bob.join("general")
    target = bob.say("general", "bob owns this")

    with pytest.raises(
        NotFoundError,
        match=rf"^message not found or not deletable: {target.ts}$",
    ):
        alice.delete_message(str(target.ts))

    assert alice.queue("general").peek_one(exact_timestamp=target.ts) is not None
    assert bob.delete_message(str(target.ts)).ts == target.ts


def test_unrelated_dm_delete_error_does_not_reveal_target_details(
    tmp_path: Path,
) -> None:
    alice = client(tmp_path, "alice")
    alice.join("general")
    bob = existing_client(tmp_path, "bob")
    bob.join("general")
    outsider = existing_client(tmp_path, "outsider")
    outsider.join("general")
    secret = "private body that must not leak"
    direct = alice.say("@bob", secret)

    with pytest.raises(NotFoundError) as ineligible:
        outsider.delete_message(str(direct.ts))
    alice.delete_message(str(direct.ts))
    with pytest.raises(NotFoundError) as missing:
        outsider.delete_message(str(direct.ts))

    expected = f"message not found or not deletable: {direct.ts}"
    assert str(ineligible.value) == expected
    assert str(missing.value) == expected
    for sensitive in (secret, direct.thread, "alice", "bob"):
        assert sensitive not in str(ineligible.value)


def test_delete_message_allows_author_after_leaving_channel(tmp_path: Path) -> None:
    van = client(tmp_path, "van")
    van.join("general")
    target = van.say("general", "delete after departure")
    member_id = van.whoami().member_id
    van.leave("general")
    assert van._state.get_membership(thread="general", member_id=member_id) is None

    with pytest.raises(
        NotFoundError,
        match=rf"^message not found: {target.ts}$",
    ):
        van.show_message(str(target.ts))
    deletion = van.delete_message(str(target.ts))

    assert deletion == MessageDeletion(thread="general", ts=target.ts)
    assert van.queue("general").peek_one(exact_timestamp=target.ts) is None


def test_delete_message_allows_author_after_leaving_subthread(tmp_path: Path) -> None:
    van = client(tmp_path, "van")
    van.join("general")
    root = van.say("general", "root")
    target = van.reply("general", str(root.ts), "delete after child departure")
    member_id = van.whoami().member_id
    van.leave(target.thread)
    assert (
        van._state.get_membership(
            thread=target.thread,
            member_id=member_id,
        )
        is None
    )

    assert van.delete_message(str(target.ts)) == MessageDeletion(
        thread=target.thread,
        ts=target.ts,
    )
    assert (
        van._state.get_membership(
            thread=target.thread,
            member_id=member_id,
        )
        is None
    )


def test_delete_message_rejects_notice_and_foreign_rows(tmp_path: Path) -> None:
    van = client(tmp_path, "van")
    notice = van.join("general")
    queue = van.queue("general")
    foreign_ts = queue.write("foreign body")

    for timestamp in (notice.ts, foreign_ts):
        with pytest.raises(
            NotFoundError,
            match=rf"^message not found or not deletable: {timestamp}$",
        ):
            van.delete_message(str(timestamp))
        assert queue.peek_one(exact_timestamp=timestamp) is not None


def test_delete_message_always_passes_one_non_null_exact_id(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    van = client(tmp_path, "van")
    van.join("general")
    target = van.say("general", "never purge the queue")
    message_ids: list[int | str | None] = []
    real_delete = Queue.delete

    def track_delete(
        queue: Queue,
        *,
        message_id: int | str | None = None,
    ) -> bool:
        message_ids.append(message_id)
        return real_delete(queue, message_id=message_id)

    monkeypatch.setattr(Queue, "delete", track_delete)

    assert van.delete_message(str(target.ts)).ts == target.ts
    assert message_ids == [target.ts]


def test_delete_message_skips_notification_and_unregistered_queues(
    tmp_path: Path,
) -> None:
    van = client(tmp_path, "van")
    van.join("general")
    member = van.whoami()
    body = encode_envelope(
        from_id=member.member_id,
        from_name=member.name,
        kind="message",
        text="not registered chat history",
    )
    notification_thread = addressing.notification_queue_name(member.member_id)
    notification_ts = van.queue(notification_thread).write(body)
    van._state.upsert_thread(
        name=notification_thread,
        kind="notification",
        parent=None,
        origin_ts=None,
        created_by=member.member_id,
        meta={},
        created_ts=notification_ts,
    )
    unregistered_ts = van.queue("unregistered").write(body)

    for timestamp in (notification_ts, unregistered_ts):
        with pytest.raises(
            NotFoundError,
            match=rf"^message not found or not deletable: {timestamp}$",
        ):
            van.delete_message(str(timestamp))

    assert (
        van.queue(notification_thread).peek_one(exact_timestamp=notification_ts)
        is not None
    )
    assert (
        van.queue("unregistered").peek_one(exact_timestamp=unregistered_ts) is not None
    )


def test_deleted_cursor_target_leaves_later_reads_working(tmp_path: Path) -> None:
    reader = client(tmp_path, "reader")
    reader.join("general")
    author = existing_client(tmp_path, "author")
    author.join("general")
    reader.read("general")
    target = author.say("general", "cursor target")
    assert reader.show_message(str(target.ts)) == target

    author.delete_message(str(target.ts))
    later = author.say("general", "after the deleted cursor gap")

    assert [message.ts for message in reader.read("general")] == [later.ts]


@pytest.mark.parametrize("target_position", ["below", "at", "above"])
def test_delete_message_never_changes_other_member_cursor(
    tmp_path: Path,
    target_position: str,
) -> None:
    reader = client(tmp_path, "reader")
    reader.join("general")
    author = existing_client(tmp_path, "author")
    author.join("general")
    reader.read("general")
    below = author.say("general", "below cursor")
    at = author.say("general", "cursor target")
    above = author.say("general", "above cursor")
    reader_id = reader.whoami().member_id
    reader._state.advance_cursor(
        thread="general",
        member_id=reader_id,
        seen_ts=at.ts,
    )

    target = {"below": below, "at": at, "above": above}[target_position]
    author.delete_message(str(target.ts))

    membership = reader._state.get_membership(
        thread="general",
        member_id=reader_id,
    )
    assert membership is not None
    assert membership["last_seen_ts"] == at.ts


def test_delete_newest_message_recomputes_list_metadata_from_survivors(
    tmp_path: Path,
) -> None:
    reader = client(tmp_path, "reader")
    reader.join("general")
    author = existing_client(tmp_path, "author")
    author.join("general")
    reader.read("general")
    survivor = author.say("general", "survives")
    newest = author.say("general", "deleted newest")
    before = next(
        thread for thread in reader.list_threads() if thread.name == "general"
    )
    assert before.last_ts == newest.ts

    author.delete_message(str(newest.ts))

    after = next(thread for thread in reader.list_threads() if thread.name == "general")
    assert after.last_ts == survivor.ts
    assert after.unread


def test_concurrent_list_delete_staleness_converges_on_next_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reader = client(tmp_path, "reader")
    reader.join("general")
    author = existing_client(tmp_path, "author")
    author.join("general")
    reader.read("general")
    survivor = author.say("general", "survives")
    newest = author.say("general", "deleted during list")
    real_latest = Queue.latest_pending_timestamp
    deleted = False

    def latest_then_delete(queue: Queue) -> int | None:
        nonlocal deleted
        result = real_latest(queue)
        if queue.name == "general" and not deleted:
            deleted = True
            author.delete_message(str(newest.ts))
        return result

    monkeypatch.setattr(Queue, "latest_pending_timestamp", latest_then_delete)

    raced = next(thread for thread in reader.list_threads() if thread.name == "general")
    assert raced.last_ts == newest.ts
    converged = next(
        thread for thread in reader.list_threads() if thread.name == "general"
    )
    assert converged.last_ts == survivor.ts


def test_claimed_before_lookup_is_invisible_to_show_and_delete(
    tmp_path: Path,
) -> None:
    van = client(tmp_path, "van")
    van.join("general")
    target = van.say("general", "claimed before lookup")
    queue = van.queue("general")
    claimed = queue.read_one(exact_timestamp=target.ts, with_timestamps=True)
    assert claimed is not None

    with pytest.raises(
        NotFoundError,
        match=rf"^message not found: {target.ts}$",
    ):
        van.show_message(str(target.ts))
    with pytest.raises(
        NotFoundError,
        match=rf"^message not found or not deletable: {target.ts}$",
    ):
        van.delete_message(str(target.ts))

    assert (
        queue.peek_one(
            exact_timestamp=target.ts,
            with_timestamps=True,
            include_claimed=True,
        )
        == claimed
    )


def test_delete_message_physically_deletes_row_claimed_after_lookup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    van = client(tmp_path, "van")
    van.join("general")
    target = van.say("general", "claim between locate and delete")
    claimer = van.queue("general")
    real_delete = Queue.delete
    claims: list[tuple[str, int] | None] = []

    def delete_after_claim(
        queue: Queue,
        *,
        message_id: int | str | None = None,
    ) -> bool:
        if queue.name == "general" and message_id == target.ts and not claims:
            claimed = claimer.read_one(
                exact_timestamp=target.ts,
                with_timestamps=True,
            )
            claims.append(cast(tuple[str, int] | None, claimed))
        return real_delete(queue, message_id=message_id)

    monkeypatch.setattr(Queue, "delete", delete_after_claim)

    deletion = van.delete_message(str(target.ts))

    assert deletion == MessageDeletion(thread="general", ts=target.ts)
    assert claims and claims[0] is not None
    assert claims[0][1] == target.ts
    assert (
        claimer.peek_one(
            exact_timestamp=target.ts,
            include_claimed=True,
        )
        is None
    )


def test_concurrent_delete_message_has_exactly_one_winner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = client(tmp_path, "van")
    first.join("general")
    target = first.say("general", "one winner")
    second = existing_client(tmp_path, "van")
    delete_barrier = threading.Barrier(2, timeout=3.0)
    real_delete = Queue.delete

    def synchronized_delete(
        queue: Queue,
        *,
        message_id: int | str | None = None,
    ) -> bool:
        if queue.name == "general" and message_id == target.ts:
            delete_barrier.wait()
        return real_delete(queue, message_id=message_id)

    monkeypatch.setattr(Queue, "delete", synchronized_delete)
    outcomes: list[MessageDeletion | BaseException | None] = [None, None]

    def delete(index: int, actor: TautClient) -> None:
        try:
            outcomes[index] = actor.delete_message(str(target.ts))
        except BaseException as exc:  # pragma: no cover  # noqa: BLE001 approved [DOM-10.2.1] [RUFF-SUP-070] exception
            outcomes[index] = exc

    workers = [
        threading.Thread(target=delete, args=(0, first)),
        threading.Thread(target=delete, args=(1, second)),
    ]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=5.0)

    assert not any(worker.is_alive() for worker in workers)
    receipts = [item for item in outcomes if isinstance(item, MessageDeletion)]
    errors = [item for item in outcomes if isinstance(item, BaseException)]
    assert receipts == [MessageDeletion(thread="general", ts=target.ts)]
    assert len(errors) == 1
    assert isinstance(errors[0], NotFoundError)
    assert str(errors[0]) == f"message not found or not deletable: {target.ts}"


def test_show_message_may_return_after_concurrent_delete(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    author = client(tmp_path, "author")
    author.join("general")
    reader = existing_client(tmp_path, "reader")
    reader.join("general")
    target = author.say("general", "delete after show lookup")
    reader_id = reader.whoami().member_id
    real_advance_cursor = SqlSidecarTautState.advance_cursor
    deletions: list[MessageDeletion] = []

    def advance_after_delete(
        state: SqlSidecarTautState,
        *,
        thread: str,
        member_id: str,
        seen_ts: int,
    ) -> None:
        if (
            state is reader._state
            and thread == "general"
            and member_id == reader_id
            and seen_ts == target.ts
            and not deletions
        ):
            deletions.append(author.delete_message(str(target.ts)))
        real_advance_cursor(
            state,
            thread=thread,
            member_id=member_id,
            seen_ts=seen_ts,
        )

    monkeypatch.setattr(
        SqlSidecarTautState,
        "advance_cursor",
        advance_after_delete,
    )

    shown = reader.show_message(str(target.ts))

    assert shown == target
    assert deletions == [MessageDeletion(thread="general", ts=target.ts)]
    assert reader.queue("general").peek_one(exact_timestamp=target.ts) is None
    membership = reader._state.get_membership(
        thread="general",
        member_id=reader_id,
    )
    assert membership is not None
    assert membership["last_seen_ts"] == target.ts


def test_show_message_may_return_after_concurrent_leave(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    author = client(tmp_path, "author")
    author.join("general")
    reader = existing_client(tmp_path, "reader")
    reader.join("general")
    target = author.say("general", "leave after show lookup")
    reader_id = reader.whoami().member_id
    real_advance_cursor = SqlSidecarTautState.advance_cursor
    leave_notices: list[Message] = []

    def advance_after_leave(
        state: SqlSidecarTautState,
        *,
        thread: str,
        member_id: str,
        seen_ts: int,
    ) -> None:
        if (
            state is reader._state
            and thread == "general"
            and member_id == reader_id
            and seen_ts == target.ts
            and not leave_notices
        ):
            leave_notices.append(reader.leave("general"))
        real_advance_cursor(
            state,
            thread=thread,
            member_id=member_id,
            seen_ts=seen_ts,
        )

    monkeypatch.setattr(
        SqlSidecarTautState,
        "advance_cursor",
        advance_after_leave,
    )

    shown = reader.show_message(str(target.ts))

    assert shown == target
    assert len(leave_notices) == 1
    assert reader._state.get_membership(thread="general", member_id=reader_id) is None


def test_deleting_only_dm_message_preserves_thread_for_reuse(
    tmp_path: Path,
) -> None:
    van = client(tmp_path, "van")
    van.join("general")
    bob = existing_client(tmp_path, "bob")
    bob.join("general")
    first = van.say("@bob", "first and temporarily only")
    van_id = van.whoami().member_id
    bob_id = bob.whoami().member_id
    first_notifications = bob.peek_inbox()
    assert [(item.type, item.message_ts) for item in first_notifications] == [
        ("dm_started", first.ts)
    ]
    thread_before = van._state.get_thread(first.thread)
    memberships_before = {
        member_id: van._state.get_membership(
            thread=first.thread,
            member_id=member_id,
        )
        for member_id in (van_id, bob_id)
    }

    van.delete_message(str(first.ts))
    assert van._state.get_thread(first.thread) == thread_before
    assert {
        member_id: van._state.get_membership(
            thread=first.thread,
            member_id=member_id,
        )
        for member_id in (van_id, bob_id)
    } == memberships_before
    empty_dm = next(
        thread
        for thread in van.list_threads(all_threads=True)
        if thread.name == first.thread
    )
    assert empty_dm.last_ts is None
    assert not empty_dm.unread
    second = van.say("@bob", "reuse the existing dm")

    assert second.thread == first.thread
    assert van._state.get_thread(first.thread) == thread_before
    memberships_after = {
        member_id: van._state.get_membership(
            thread=first.thread,
            member_id=member_id,
        )
        for member_id in (van_id, bob_id)
    }
    assert all(row is not None for row in memberships_after.values())
    assert {
        member_id: row["joined_ts"]
        for member_id, row in memberships_after.items()
        if row is not None
    } == {
        member_id: row["joined_ts"]
        for member_id, row in memberships_before.items()
        if row is not None
    }
    assert bob.peek_inbox() == first_notifications


def test_deleting_origin_preserves_orphan_subthread_and_listing(
    tmp_path: Path,
) -> None:
    van = client(tmp_path, "van")
    van.join("general")
    root = van.say("general", "root")
    child_message = van.reply("general", str(root.ts), "child survives")

    van.delete_message(str(root.ts))

    child = next(
        thread
        for thread in van.list_threads(all_threads=True)
        if thread.name == child_message.thread
    )
    assert child.kind == "subthread"
    assert child.parent == "general"
    assert child.last_ts == child_message.ts
    assert van.log(child.name) == [child_message]
    continued = van.say(child.name, "still usable")
    assert continued.thread == child.name
    with pytest.raises(
        NotFoundError,
        match=rf"^message not found: {root.ts}$",
    ):
        van.reply("general", str(root.ts), "cannot recreate origin")


def test_deleting_mentioned_message_leaves_stale_notification_pointer(
    tmp_path: Path,
) -> None:
    author = client(tmp_path, "author")
    author.join("general")
    recipient = existing_client(tmp_path, "recipient")
    recipient.join("general")
    source = author.say("general", "hello @recipient")
    before = recipient.peek_inbox()
    assert [(item.type, item.message_ts) for item in before] == [("mention", source.ts)]

    author.delete_message(str(source.ts))

    assert recipient.peek_inbox() == before
    assert recipient.inbox() == before
    with pytest.raises(
        NotFoundError,
        match=rf"^message not found: {source.ts}$",
    ):
        recipient.show_message(str(source.ts))


def test_deleting_reply_leaves_stale_reply_notification_pointer(
    tmp_path: Path,
) -> None:
    parent_author = client(tmp_path, "parent")
    parent_author.join("general")
    replier = existing_client(tmp_path, "replier")
    replier.join("general")
    root = parent_author.say("general", "root")
    reply = replier.reply("general", str(root.ts), "answer")
    before = parent_author.peek_inbox()
    assert [(item.type, item.message_ts) for item in before] == [("reply", reply.ts)]

    replier.delete_message(str(reply.ts))

    assert parent_author.peek_inbox() == before
    assert parent_author.inbox() == before


def test_resolved_target_config_handoff_rejects_incomplete_or_conflicting_args(
    tmp_path: Path,
) -> None:
    """[TAUT-3.2] Resolved target/config are an exclusive argument pair."""

    db = tmp_path / ".taut.db"
    TautClient.init(db_path=db)
    config = load_config()
    target = BrokerTarget("sqlite", str(db))

    with pytest.raises(ValueError, match="broker_target and broker_config"):
        TautClient(broker_target=target)
    with pytest.raises(ValueError, match="broker_target and broker_config"):
        TautClient(broker_config=config)
    with pytest.raises(ValueError, match="broker_target and broker_config"):
        TautClient(db_path=db, broker_config=config)
    with pytest.raises(
        ValueError, match="broker_target cannot be combined with db_path"
    ):
        TautClient(
            db_path=db,
            broker_target=target,
            broker_config=config,
        )


def test_resolved_sqlite_target_handoff_does_not_create_database(
    tmp_path: Path,
) -> None:
    """[TAUT-3.2] A handed-off SQLite target must already exist."""

    missing = tmp_path / "missing.db"

    with pytest.raises(NotInitializedError):
        TautClient(
            broker_target=BrokerTarget("sqlite", str(missing)),
            broker_config=load_config(),
        )

    assert not missing.exists()


def test_resolved_sqlite_target_handoff_rejects_relative_path_or_directory(
    tmp_path: Path,
) -> None:
    """[TAUT-3.2] A handed-off SQLite target is one absolute database file."""

    with pytest.raises(ValueError, match="SQLite path must be absolute"):
        TautClient(
            broker_target=BrokerTarget("sqlite", "relative.db"),
            broker_config=load_config(),
        )
    with pytest.raises(NotInitializedError):
        TautClient(
            broker_target=BrokerTarget("sqlite", str(tmp_path)),
            broker_config=load_config(),
        )


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


def test_rejoin_keeps_existing_unread_cursor(tmp_path: Path) -> None:
    alice = client(tmp_path, "alice")
    alice.join("general")
    bob = existing_client(tmp_path, "bob")
    bob.join("general")
    unread = alice.say("general", "still unread after rejoin")

    rejoin_notice = bob.join("general")

    assert [message.ts for message in bob.read("general")] == [
        unread.ts,
        rejoin_notice.ts,
    ]


def test_blank_channel_say_precedes_routing_and_leaves_state_unchanged(
    tmp_path: Path,
) -> None:
    """[TAUT-6.5] Blank input is rejected before identity or message work."""

    van = client(tmp_path, "van")
    van.join("general")
    created = van.last_created_member
    assert created is not None
    before_member = van._state.get_member(created.member_id)
    before_membership = van._state.get_membership(
        thread="general", member_id=created.member_id
    )
    before_threads = van._state.list_threads(include_internal=True)
    before_messages = [(item.ts, item.text) for item in van.log("general")]

    with pytest.raises(BlankMessageError):
        van.say("not a valid target!", " \t\u200b\u2060\n")

    assert van._state.get_member(created.member_id) == before_member
    assert (
        van._state.get_membership(thread="general", member_id=created.member_id)
        == before_membership
    )
    assert van._state.list_threads(include_internal=True) == before_threads
    assert [(item.ts, item.text) for item in van.log("general")] == before_messages


def test_blank_first_dm_creates_no_thread_membership_or_notification(
    tmp_path: Path,
) -> None:
    """[TAUT-6.5, IAN-7.3] A filtered first DM has no domain footprint."""

    van = client(tmp_path, "van")
    bob = existing_client(tmp_path, "bob")
    van.join("general")
    bob.join("general")
    van_member = van.whoami()
    before_member = van._state.get_member(van_member.member_id)
    before_threads = van._state.list_threads(include_internal=True)
    before_memberships = van._state.list_memberships(van_member.member_id)

    with pytest.raises(BlankMessageError):
        van.say("@bob", "\ufeff")

    assert van._state.get_member(van_member.member_id) == before_member
    assert van._state.list_threads(include_internal=True) == before_threads
    assert van._state.list_memberships(van_member.member_id) == before_memberships
    with pytest.raises(EmptyResultError):
        bob.inbox()


def test_blank_stable_dm_say_precedes_target_parsing_and_state_access(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """[TAUT-6.5, IAN-10] Stable targets retain the universal blank guard."""

    van = client(tmp_path, "van")
    bob = existing_client(tmp_path, "bob")
    van.join("general")
    bob.join("general")
    stable = van.say("@bob", "seed").thread
    state = cast(SqlSidecarTautState, van._state)

    def snapshot() -> tuple[object, ...]:
        with open_broker(van.target, config=van.config) as broker:
            broker_lines = tuple(dump_lines(broker))[1:]
        return (
            state.persistence_meta(),
            state.persistence_records(),
            van._state.list_members(),
            broker_lines,
        )

    before = snapshot()

    def fail_state_access() -> None:
        raise AssertionError("blank stable send reached the first state guard")

    monkeypatch.setattr(
        van,
        "_ensure_no_incomplete_channel_rename",
        fail_state_access,
    )
    with pytest.raises(BlankMessageError):
        van.say(stable, " \t\u200b\u2060\n")
    with pytest.raises(BlankMessageError):
        van.say("dm.d_short", "\ufeff")

    assert snapshot() == before


def test_blank_say_precedes_existing_member_membership_failure(
    tmp_path: Path,
) -> None:
    """[TAUT-6.5] Blank-first also wins for a known nonmember."""

    van = client(tmp_path, "van")
    bob = existing_client(tmp_path, "bob")
    van.join("general")
    bob.join("general")
    bob.leave("general")
    member = bob.whoami()
    before_member = bob._state.get_member(member.member_id)
    before_messages = [(item.ts, item.text) for item in van.log("general")]

    with pytest.raises(BlankMessageError):
        bob.say("general", " \u200b")

    assert bob._state.get_member(member.member_id) == before_member
    assert (
        bob._state.get_membership(thread="general", member_id=member.member_id) is None
    )
    assert [(item.ts, item.text) for item in van.log("general")] == before_messages


def test_blank_say_and_reply_create_no_mention_or_reply_notifications(
    tmp_path: Path,
) -> None:
    """[TAUT-6.5, IAN-7.3] Blank input never reaches notification dispatch."""

    van = client(tmp_path, "van")
    bob = existing_client(tmp_path, "bob")
    van.join("general")
    bob.join("general")
    root = bob.say("general", "root")
    before_messages = [(item.ts, item.text) for item in van.log("general")]

    with pytest.raises(BlankMessageError):
        van.say("general", "\u00a0\u200b")
    with pytest.raises(BlankMessageError):
        van.reply("general", str(root.ts), "\u200d")

    assert [(item.ts, item.text) for item in van.log("general")] == before_messages
    with pytest.raises(EmptyResultError):
        bob.inbox()


def test_blank_first_reply_precedes_parent_lookup_and_creates_no_subthread(
    tmp_path: Path,
) -> None:
    """[TAUT-6.5] A filtered reply resolves no parent and creates no state."""

    van = client(tmp_path, "van")
    van.join("general")
    root = van.say("general", "root")
    member = van.whoami()
    before_member = van._state.get_member(member.member_id)
    before_threads = van._state.list_threads(include_internal=True)
    before_memberships = van._state.list_memberships(member.member_id)
    before_messages = [(item.ts, item.text) for item in van.log("general")]

    with pytest.raises(BlankMessageError):
        van.reply("general", "missing-parent", "\u00a0\u200d")

    assert van._state.get_member(member.member_id) == before_member
    assert van._state.list_threads(include_internal=True) == before_threads
    assert van._state.list_memberships(member.member_id) == before_memberships
    assert [(item.ts, item.text) for item in van.log("general")] == before_messages
    assert van._state.get_thread(f"general.{root.ts}") is None


def test_blank_message_precedes_incomplete_rename_guard(tmp_path: Path) -> None:
    """[TAUT-6.5] Blank classification is the public method's first operation."""

    van = client(tmp_path, "van")
    van.join("general")
    _start_rename_marker(
        tmp_path,
        old_name="general",
        new_name="ops",
        affected=[{"old": "general", "new": "ops"}],
    )

    with pytest.raises(BlankMessageError):
        van.say("general", "\u200b")
    with pytest.raises(BlankMessageError):
        van.reply("general", "1234", "\u200b")


def test_nonblank_text_round_trips_exactly_with_blank_class_characters(
    tmp_path: Path,
) -> None:
    """[TAUT-6.5] Accepted text is neither trimmed nor normalized."""

    van = client(tmp_path, "van")
    van.join("general")
    text = " \u200b\U0001f469\u200d\U0001f4bb\u2060 \n"

    message = van.say("general", text)

    assert message.text == text
    assert van.log("general")[-1].text == text


def test_historical_blank_envelopes_and_foreign_bodies_remain_readable(
    tmp_path: Path,
) -> None:
    """[TAUT-6.3, TAUT-6.5] Filtering is write-entry-only, not read-side."""

    van = client(tmp_path, "van")
    van.join("general")
    created = van.last_created_member
    assert created is not None
    queue = van.queue("general")
    blank_envelope_ts = queue.generate_timestamp()
    foreign_ts = queue.generate_timestamp()
    queue.insert_messages(
        [
            (
                encode_envelope(
                    from_id=created.member_id,
                    from_name="van",
                    kind="message",
                    text="",
                ),
                blank_envelope_ts,
            ),
            ("", foreign_ts),
        ]
    )

    by_ts = {item.ts: item for item in van.log("general")}

    assert by_ts[blank_envelope_ts].text == ""
    assert by_ts[blank_envelope_ts].kind == "message"
    assert by_ts[foreign_ts].text == ""
    assert by_ts[foreign_ts].kind == "foreign"


def test_read_without_thread_reads_all_membership_unread(tmp_path: Path) -> None:
    van = client(tmp_path, "van")
    van.join("general")
    bob = existing_client(tmp_path, "bob")
    bob.join("general")

    bob.say("general", "broadcast")
    unread = van.read()

    assert [message.text for message in unread] == ["bob joined", "broadcast"]


def test_unread_limit_without_thread_applies_per_joined_thread(
    tmp_path: Path,
) -> None:
    reader = client(tmp_path, "reader")
    reader.join("alpha")
    reader.join("beta")
    writer = existing_client(tmp_path, "writer")
    writer.join("alpha")
    writer.join("beta")
    reader.read()
    writer.say("alpha", "alpha 1")
    writer.say("alpha", "alpha 2")
    writer.say("beta", "beta 1")
    writer.say("beta", "beta 2")

    first_pages = reader.read(limit=1)
    second_pages = reader.read_unread(limit=1)

    assert len(first_pages) == 2
    assert {(message.thread, message.text) for message in first_pages} == {
        ("alpha", "alpha 1"),
        ("beta", "beta 1"),
    }
    assert len(second_pages) == 2
    assert {(message.thread, message.text) for message in second_pages} == {
        ("alpha", "alpha 2"),
        ("beta", "beta 2"),
    }
    with pytest.raises(EmptyResultError):
        reader.read(limit=1)


@pytest.mark.parametrize(
    ("method_name", "limit"),
    [("read", 0), ("read", 1001), ("read_unread", 0), ("read_unread", 1001)],
)
def test_unread_limit_rejects_out_of_range_before_peek_or_cursor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    method_name: str,
    limit: int,
) -> None:
    van = client(tmp_path, "van")
    van.join("general")
    bob = existing_client(tmp_path, "bob")
    bob.join("general")
    bob.say("general", "still unread")
    member_id = van.whoami().member_id
    membership_before = van._state.get_membership(
        thread="general",
        member_id=member_id,
    )
    assert membership_before is not None
    peek_calls: list[object] = []

    def reject_peek(*args: object, **kwargs: object) -> object:
        peek_calls.append((args, kwargs))
        raise AssertionError("invalid limit reached Queue.peek_many")

    monkeypatch.setattr(Queue, "peek_many", reject_peek)

    method = getattr(van, method_name)
    with pytest.raises(
        ValueError,
        match="^limit must be between 1 and 1000$",
    ):
        method("general", limit=limit)

    membership_after = van._state.get_membership(
        thread="general",
        member_id=member_id,
    )
    assert membership_after == membership_before
    assert peek_calls == []


@pytest.mark.parametrize("method_name", ["read", "read_unread"])
@pytest.mark.parametrize("limit", [True, 1.0, "1"])
def test_unread_limit_rejects_non_integer_before_peek_or_cursor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    method_name: str,
    limit: object,
) -> None:
    van = client(tmp_path, "van")
    van.join("general")
    bob = existing_client(tmp_path, "bob")
    bob.join("general")
    bob.say("general", "still unread")
    member_id = van.whoami().member_id
    membership_before = van._state.get_membership(
        thread="general",
        member_id=member_id,
    )
    assert membership_before is not None
    peek_calls: list[object] = []

    def reject_peek(*args: object, **kwargs: object) -> object:
        peek_calls.append((args, kwargs))
        raise AssertionError("invalid limit reached Queue.peek_many")

    monkeypatch.setattr(Queue, "peek_many", reject_peek)

    method = getattr(van, method_name)
    with pytest.raises(TypeError, match="^limit must be an integer$"):
        method("general", limit=limit)

    membership_after = van._state.get_membership(
        thread="general",
        member_id=member_id,
    )
    assert membership_after == membership_before
    assert peek_calls == []


def test_invalid_unread_limit_does_not_implicitly_join_subthread(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reader = client(tmp_path, "reader")
    reader.join("general")
    writer = existing_client(tmp_path, "writer")
    writer.join("general")
    root = writer.say("general", "root")
    reply = writer.reply("general", str(root.ts), "threaded")
    reader_id = reader.whoami().member_id
    parent_before = reader._state.get_membership(
        thread="general",
        member_id=reader_id,
    )
    assert parent_before is not None
    assert (
        reader._state.get_membership(thread=reply.thread, member_id=reader_id) is None
    )
    peek_calls: list[object] = []

    def reject_peek(*args: object, **kwargs: object) -> object:
        peek_calls.append((args, kwargs))
        raise AssertionError("invalid limit reached Queue.peek_many")

    monkeypatch.setattr(Queue, "peek_many", reject_peek)

    with pytest.raises(ValueError, match="^limit must be between 1 and 1000$"):
        reader.read(reply.thread, limit=0)

    assert (
        reader._state.get_membership(thread=reply.thread, member_id=reader_id) is None
    )
    assert (
        reader._state.get_membership(thread="general", member_id=reader_id)
        == parent_before
    )
    assert peek_calls == []


def test_read_unread_advances_cursor_once_for_returned_page(
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
        for index in range(3)
    ]
    first_ts = queue.generate_timestamp() + 1
    timestamps = [first_ts + offset for offset in range(len(bodies))]
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

    assert [message.ts for message in unread] == timestamps
    assert counting.advance_calls == [timestamps[-1]]
    membership = delegate.get_membership(thread="general", member_id=member_id)
    assert membership is not None
    assert membership["last_seen_ts"] == timestamps[-1]


def test_unread_limit_accepts_one_and_one_thousand(tmp_path: Path) -> None:
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
        for index in range(1001)
    ]
    first_ts = queue.generate_timestamp() + 1
    timestamps = [first_ts + offset for offset in range(len(bodies))]
    queue.insert_messages(list(zip(bodies, timestamps, strict=True)))

    first = van.read_unread("general", limit=1)
    membership = van._state.get_membership(thread="general", member_id=member_id)
    assert [message.ts for message in first] == timestamps[:1]
    assert membership is not None
    assert membership["last_seen_ts"] == timestamps[0]

    remaining = van.read("general", limit=1000)
    membership = van._state.get_membership(thread="general", member_id=member_id)
    assert [message.ts for message in remaining] == timestamps[1:]
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
        van.read_unread("general", limit=2)

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


def test_member_creation_explicit_conflict_does_not_adopt_matching_claim(
    tmp_path: Path,
) -> None:
    van = client(tmp_path, "van")
    van.join("general")
    existing = van.whoami()
    capture = van._capture()
    claim = identity.claim_for_capture(capture)

    with pytest.raises(IdentityError):
        van._create_member(
            capture,
            claim=claim,
            name="van",
            persona=None,
            active_ts=next_meta_timestamp(tmp_path),
            force_new=False,
        )

    assert van.whoami().member_id == existing.member_id


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


def test_unknown_dm_target_fails_before_missing_actor_capture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """[IAN-3.3]: DM target validation precedes actor creation."""

    TautClient.init(db_path=tmp_path / ".taut.db")
    missing_actor = TautClient(
        db_path=tmp_path / ".taut.db",
        as_name="alice",
        identity_capture=_anchor_capture(cwd="/workspace/alice"),
    )
    capture_calls = capture_requests(missing_actor, monkeypatch)

    with pytest.raises(NotFoundError, match="member not found: @bob"):
        missing_actor.say("@bob", "no target")

    assert capture_calls == []
    assert missing_actor._state.get_member_by_route_key("alice") is None


def test_dm_existing_target_allows_missing_actor_creation_with_one_capture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """[IAN-3.3]: a viable DM may create its explicitly named actor."""

    TautClient.init(db_path=tmp_path / ".taut.db")
    db = tmp_path / ".taut.db"
    bob = TautClient(db_path=db, as_name="bob")
    bob.join("general")
    bob_member = bob.last_created_member
    assert bob_member is not None
    actor_capture = _anchor_capture(cwd="/workspace/alice")
    actor_claim = identity.claim_for_capture(actor_capture)
    alice = TautClient(
        db_path=db,
        as_name="alice",
        identity_capture=actor_capture,
    )
    capture_calls = capture_requests(alice, monkeypatch)

    message = alice.say("@bob", "hello")

    assert capture_calls == [actor_capture]
    created = alice.last_created_member
    assert created is not None
    assert message.from_id == created.member_id
    assert message.thread == addressing.dm_queue_name(
        created.member_id, bob_member.member_id
    )
    claim_row = alice._state.get_identity_claim(actor_claim.claim_hash)
    assert claim_row is not None
    assert claim_row["member_id"] == created.member_id


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


def test_peek_inbox_repeats_without_claiming_or_touching_member(
    tmp_path: Path,
) -> None:
    """[TAUT-8.3]/[IAN-7.4] Peek is a repeatable observational view."""

    van = client(tmp_path, "van")
    bob = existing_client(tmp_path, "bob")
    van.join("general")
    bob.join("general")
    member = bob.whoami()
    message = van.say("general", "hello @bob")
    before_member = bob._state.get_member(member.member_id)

    first = bob.peek_inbox()
    second = bob.peek_inbox()

    assert [(item.type, item.message_ts) for item in first] == [("mention", message.ts)]
    assert second == first
    assert bob._state.get_member(member.member_id) == before_member
    assert bob.inbox() == first
    with pytest.raises(EmptyResultError):
        bob.inbox()


@pytest.mark.parametrize("limit", [0, -1])
def test_peek_inbox_rejects_nonpositive_limit_before_identity_resolution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    limit: int,
) -> None:
    """[TAUT-8.3] Invalid bounds do not enter identity selection."""

    owner = client(tmp_path, "owner")
    before_members = owner._state.list_members()
    ghost = existing_client(tmp_path, "ghost")

    def unexpected_resolution(**_: object) -> None:
        raise AssertionError("identity resolution must not run")

    monkeypatch.setattr(ghost, "_resolve_member", unexpected_resolution)

    with pytest.raises(ValueError, match="limit must be positive"):
        ghost.peek_inbox(limit=limit)

    assert owner._state.list_members() == before_members


def test_peek_inbox_missing_token_binding_does_not_recreate_member(
    tmp_path: Path,
) -> None:
    """[TAUT-8.3] A removed token binding is not healed or recreated."""

    owner = client(tmp_path, "owner")
    owner.join("general")
    created = owner.last_created_member
    assert created is not None
    assert created.token is not None
    member_id = created.member_id
    observer = TautClient(
        db_path=tmp_path / ".taut.db",
        token=created.token,
    )
    with owner._meta_queue.sidecar(transaction=True) as session:
        session.run(
            "UPDATE taut_members SET token = NULL WHERE member_id = ?", (member_id,)
        )
    member_after_unbind = owner._state.get_member(member_id)
    members_after_unbind = owner._state.list_members()
    assert member_after_unbind is not None

    with pytest.raises(TokenError, match="TAUT_TOKEN does not match a taut member"):
        observer.peek_inbox()

    assert owner._state.get_member(member_id) == member_after_unbind
    assert owner._state.list_members() == members_after_unbind


def test_peek_inbox_removed_bound_member_is_not_recreated(tmp_path: Path) -> None:
    """[TAUT-11] A deleted token-bound member stays deleted after peek."""

    owner = client(tmp_path, "owner")
    owner.join("general")
    created = owner.last_created_member
    assert created is not None
    assert created.token is not None
    member_id = created.member_id
    observer = TautClient(db_path=tmp_path / ".taut.db", token=created.token)
    with owner._meta_queue.sidecar(transaction=True) as session:
        session.run(
            "DELETE FROM taut_identity_claims WHERE member_id = ?", (member_id,)
        )
        session.run("DELETE FROM taut_member_aliases WHERE member_id = ?", (member_id,))
        session.run("DELETE FROM taut_membership WHERE member_id = ?", (member_id,))
        session.run("DELETE FROM taut_members WHERE member_id = ?", (member_id,))
    members_after_removal = owner._state.list_members()

    with pytest.raises(TokenError, match="TAUT_TOKEN does not match a taut member"):
        observer.peek_inbox()

    assert owner._state.list_members() == members_after_removal


def test_peek_inbox_decodes_malformed_pointer_without_claiming_it(
    tmp_path: Path,
) -> None:
    """[TAUT-8.3] Peek and inbox share the core notification decoder."""

    bob = client(tmp_path, "bob")
    bob.join("general")
    member_id = bob.whoami().member_id
    queue = bob.queue(addressing.notification_queue_name(member_id))
    ts = queue.generate_timestamp()
    queue.insert_messages([("not json", ts)])

    peeked = bob.peek_inbox()
    consumed = bob.inbox()

    assert peeked == consumed
    assert peeked[0].type == "foreign"
    assert peeked[0].warning == "malformed notification"


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
        except BaseException as exc:  # pragma: no cover  # noqa: BLE001 approved [DOM-10.2.1] [RUFF-SUP-070] exception
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


def test_reaction_notification_decodes_without_recipient_specific_id(
    tmp_path: Path,
) -> None:
    """[IAN-7.2] Inbound reaction syntax is independent of emission config."""

    bob = client(tmp_path, "bob")
    bob.join("general")
    member_id = bob.whoami().member_id
    queue = bob.queue(addressing.notification_queue_name(member_id))
    ts = queue.generate_timestamp()
    queue.insert_messages(
        [
            (
                json.dumps(
                    {
                        "type": "reaction",
                        "actor_id": "m_" + "a" * 26,
                        "actor_name": "alice",
                        "thread": "general",
                        "message_ts": 1_800_000_000_000_000_001,
                        "reaction": "done",
                    }
                ),
                ts,
            )
        ]
    )

    notification = bob.inbox()[0]

    assert notification.type == "reaction"
    assert notification.to_id is None
    assert notification.actor_name == "alice"
    assert notification.message_ts == 1_800_000_000_000_000_001
    assert notification.reaction == "done"


@pytest.mark.parametrize(
    "payload_update",
    [
        pytest.param({"reaction": None}, id="missing-reaction"),
        pytest.param({"reaction": 1}, id="non-string-reaction"),
        pytest.param({"reaction": "Ack"}, id="invalid-reaction-slug"),
        pytest.param({"message_ts": "1800000000000000001"}, id="non-integer-message"),
        pytest.param({"message_ts": True}, id="boolean-message"),
        pytest.param({"actor_id": None}, id="missing-actor"),
    ],
)
def test_malformed_reaction_notifications_decode_as_foreign(
    tmp_path: Path,
    payload_update: dict[str, object],
) -> None:
    bob = client(tmp_path, "bob")
    bob.join("general")
    payload: dict[str, object] = {
        "type": "reaction",
        "actor_id": "m_" + "a" * 26,
        "actor_name": "alice",
        "thread": "general",
        "message_ts": 1_800_000_000_000_000_001,
        "reaction": "ack",
    }
    payload.update(payload_update)
    queue = bob.queue(addressing.notification_queue_name(bob.whoami().member_id))
    queue.write(json.dumps(payload))

    notification = bob.inbox()[0]

    assert notification.type == "foreign"
    assert notification.warning == "malformed notification"


def test_reaction_notification_ignores_unknown_fields(tmp_path: Path) -> None:
    bob = client(tmp_path, "bob")
    bob.join("general")
    queue = bob.queue(addressing.notification_queue_name(bob.whoami().member_id))
    queue.write(
        json.dumps(
            {
                "type": "reaction",
                "actor_id": "m_" + "a" * 26,
                "actor_name": "alice",
                "thread": "general",
                "message_ts": 1_800_000_000_000_000_001,
                "reaction": "ack",
                "to_id": "m_" + "b" * 26,
                "matched": "@bob",
                "future_field": {"ignored": True},
            }
        )
    )

    notification = bob.inbox()[0]

    assert notification.type == "reaction"
    assert notification.to_id is None
    assert notification.matched is None
    assert notification.reaction == "ack"


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


def test_channel_topic_round_trip_populates_public_channel_and_thread_values(
    tmp_path: Path,
) -> None:
    van = client(tmp_path, "van")
    van.join("general")
    member = van.whoami()

    empty = van.get_channel("general")
    updated = van.set_channel_topic(
        "general",
        " Current implementation and review coordination ",
    )

    assert empty == Channel(
        name="general",
        topic=None,
        topic_updated_ts=None,
        topic_updated_by_id=None,
        topic_updated_by_name=None,
    )
    assert updated.name == "general"
    assert updated.topic == " Current implementation and review coordination "
    assert updated.topic_updated_ts is not None
    assert updated.topic_updated_by_id == member.member_id
    assert updated.topic_updated_by_name == "van"
    assert van.get_channel("general") == updated
    listed = van.list_threads(all_threads=True)
    assert [(thread.name, thread.topic) for thread in listed] == [
        ("general", updated.topic)
    ]


def test_channel_topic_merge_preserves_reserved_and_unknown_meta_and_noops(
    tmp_path: Path,
) -> None:
    van = client(tmp_path, "van")
    van.join("general")
    created = van.last_created_member
    assert created is not None
    member_id = created.member_id
    with van._meta_queue.sidecar(transaction=True) as session:
        session.run(
            "UPDATE taut_threads SET meta = ? WHERE name = ?",
            (
                json.dumps(
                    {
                        "closed": {"future": True},
                        "owner": "coordination",
                    }
                ),
                "general",
            ),
        )

    first = van.set_channel_topic("general", "coordination")
    first_member = van._state.get_member(member_id)
    first_row = van._state.get_thread("general")
    assert first_member is not None
    assert first_row is not None
    assert first_row["meta"] == {
        "closed": {"future": True},
        "owner": "coordination",
        "topic": {
            "text": "coordination",
            "updated_ts": first.topic_updated_ts,
            "updated_by_id": member_id,
        },
    }

    assert van.set_channel_topic("general", "coordination") == first
    assert van._state.get_member(member_id) == first_member
    assert van._state.get_thread("general") == first_row

    cleared = van.set_channel_topic("general", None)
    cleared_row = van._state.get_thread("general")
    assert cleared.topic is None
    assert cleared_row is not None
    assert cleared_row["meta"] == {
        "closed": {"future": True},
        "owner": "coordination",
    }
    cleared_member = van._state.get_member(member_id)

    assert van.set_channel_topic("general", None) == cleared
    assert van._state.get_member(member_id) == cleared_member
    assert van._state.get_thread("general") == cleared_row


@pytest.mark.parametrize(
    ("topic", "error", "message"),
    [
        (False, TypeError, "topic must be a string or None"),
        ("", ValueError, "topic must not be blank"),
        ("\u00a0\u200b", ValueError, "topic must not be blank"),
        ("line\rbreak", ValueError, "topic must be one line"),
        ("line\nbreak", ValueError, "topic must be one line"),
        ("x" * 501, ValueError, "topic must be at most 500 Unicode code points"),
    ],
)
def test_channel_topic_validation_precedes_identity_and_channel_state(
    tmp_path: Path,
    topic: object,
    error: type[Exception],
    message: str,
) -> None:
    actor = client(tmp_path, "uncreated")
    before_threads = actor._state.list_threads(include_internal=True)
    before_members = actor._state.list_members()

    with pytest.raises(error, match=rf"^{message}$"):
        actor.set_channel_topic("invalid.name", topic)  # type: ignore[arg-type]

    assert actor._state.list_threads(include_internal=True) == before_threads
    assert actor._state.list_members() == before_members


def test_channel_topic_accepts_exact_500_code_point_boundary(tmp_path: Path) -> None:
    van = client(tmp_path, "van")
    van.join("general")
    topic = "🧭" * 500

    assert van.set_channel_topic("general", topic).topic == topic


def test_get_channel_is_actor_free_and_state_observational(tmp_path: Path) -> None:
    owner = client(tmp_path, "owner")
    owner.join("general")
    owner.set_channel_topic("general", "read only")
    viewer = existing_client(tmp_path, "missing")
    before_members = viewer._state.list_members()
    before_thread = viewer._state.get_thread("general")
    before_memberships = {
        member["member_id"]: viewer._state.list_memberships(member["member_id"])
        for member in before_members
    }
    before_high_water = viewer._meta_queue.refresh_last_ts()

    shown = viewer.get_channel("general")

    assert shown.topic == "read only"
    assert viewer._state.list_members() == before_members
    assert viewer._state.get_thread("general") == before_thread
    assert {
        member["member_id"]: viewer._state.list_memberships(member["member_id"])
        for member in before_members
    } == before_memberships
    assert viewer._meta_queue.refresh_last_ts() == before_high_water


def test_set_channel_topic_requires_existing_actor_membership_without_side_effects(
    tmp_path: Path,
) -> None:
    owner = client(tmp_path, "owner")
    owner.join("general")
    outsider = existing_client(tmp_path, "outsider")
    outsider.join("elsewhere")
    outsider_row = outsider._state.get_member_by_route_key("outsider")
    assert outsider_row is not None
    before_outsider = dict(outsider_row)
    before_general = outsider._state.get_thread("general")

    with pytest.raises(MembershipError, match="not a member of general"):
        outsider.set_channel_topic("general", "not allowed")

    assert outsider._state.get_member(outsider_row["member_id"]) == before_outsider
    assert outsider._state.get_thread("general") == before_general

    missing = existing_client(tmp_path, "missing")
    before_members = missing._state.list_members()
    with pytest.raises(NotFoundError, match="member not found: missing"):
        missing.set_channel_topic("general", "not allowed")
    assert missing._state.list_members() == before_members


def test_channel_topic_rejects_wrong_kind_and_topic_on_non_channel(
    tmp_path: Path,
) -> None:
    van = client(tmp_path, "van")
    van.join("general")
    member = van._state.get_member_by_route_key("van")
    assert member is not None
    before_member = dict(member)
    with van._meta_queue.sidecar(transaction=True) as session:
        session.run(
            "UPDATE taut_threads SET kind = 'subthread' WHERE name = ?",
            ("general",),
        )

    with pytest.raises(NotFoundError, match="channel not found: general"):
        van.get_channel("general")
    with pytest.raises(NotFoundError, match="channel not found: general"):
        van.set_channel_topic("general", "not allowed")
    assert van._state.get_member(member["member_id"]) == before_member

    corrupt_meta = {
        "topic": {
            "text": "wrong kind",
            "updated_ts": van._meta_queue.generate_timestamp(),
            "updated_by_id": member["member_id"],
        }
    }
    with van._meta_queue.sidecar(transaction=True) as session:
        session.run(
            "UPDATE taut_threads SET meta = ? WHERE name = ?",
            (json.dumps(corrupt_meta), "general"),
        )
    with pytest.raises(
        TautError,
        match="topic metadata belongs only to channels",
    ):
        van.list_threads(all_threads=True)


def test_corrupt_channel_topic_blocks_show_list_mutation_and_rename_preflight(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    van = client(tmp_path, "van")
    van.join("general")
    van.say("general", "history remains")
    corrupt_meta = {
        "closed": {"future": True},
        "topic": {
            "text": "broken",
            "updated_ts": 1_800_000_000_000_000_001,
            "updated_by_id": "m_aaaaaaaaaaaaaaaaaaaaaaaaaa",
            "extra": True,
        },
    }
    with van._meta_queue.sidecar(transaction=True) as session:
        session.run(
            "UPDATE taut_threads SET meta = ? WHERE name = ?",
            (json.dumps(corrupt_meta), "general"),
        )

    for operation in (
        lambda: van.get_channel("general"),
        lambda: van.list_threads(all_threads=True),
        lambda: van.set_channel_topic("general", "replacement"),
    ):
        with pytest.raises(TautError, match=r"taut_threads\.meta\.topic"):
            operation()

    def broker_access_is_too_late(*_: object, **__: object) -> object:
        raise AssertionError("rename touched the broker before topic validation")

    monkeypatch.setattr("taut.client._threads.open_broker", broker_access_is_too_late)
    with pytest.raises(TautError, match=r"taut_threads\.meta\.topic"):
        van.rename_channel("general", "ops")

    assert van._state.incomplete_channel_renames() == []
    row = van._state.get_thread("general")
    assert row is not None
    assert row["meta"] == corrupt_meta


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
    target = van.say("general", "blocked exact operation")
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
    with pytest.raises(TautError, match="incomplete channel rename"):
        van.show_message(str(target.ts))
    with pytest.raises(TautError, match="incomplete channel rename"):
        van.delete_message(str(target.ts))


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

    blocked = "run 'taut channel rename general ops' to finish it"
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
            "run 'taut channel rename alpha beta' to finish it"
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
    with pytest.raises(TautError, match="run 'taut channel rename general ops'"):
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


def test_anchor_match_recovers_member_after_anchor_chdir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """[IAN-3.3] step 4: a live anchor that chdir()s keeps its member."""
    TautClient.init(db_path=tmp_path / ".taut.db")
    db = tmp_path / ".taut.db"
    before = _anchor_capture(cwd="/workspace/one")
    after = _anchor_capture(cwd="/workspace/two")
    established = TautClient(db_path=db, identity_capture=before)
    established.join("general")
    member = established.whoami()

    moved_client = TautClient(db_path=db, identity_capture=after)
    capture_calls = capture_requests(moved_client, monkeypatch)

    moved = moved_client.whoami(explain=True)

    assert capture_calls == [after]
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
    monkeypatch: pytest.MonkeyPatch,
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
    capture_calls = capture_requests(contender, monkeypatch)
    with pytest.raises(IdentityError, match="already exists"):
        contender.join("general", new=True)

    assert capture_calls == []
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


def test_existing_explicit_selector_skips_capture_and_preserves_process_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """[TAUT-5]/[IAN-3.3]: ``as`` selects without teaching identity."""

    TautClient.init(db_path=tmp_path / ".taut.db")
    db = tmp_path / ".taut.db"
    established_capture = _anchor_capture(cwd="/workspace/established")
    owner = TautClient(
        db_path=db,
        as_name="reviewer",
        identity_capture=established_capture,
    )
    owner.join("general")
    created = owner.last_created_member
    assert created is not None
    established_claim = identity.claim_for_capture(established_capture)
    established_claim_before = owner._state.get_identity_claim(
        established_claim.claim_hash
    )
    assert established_claim_before is not None
    before = owner._state.get_member(created.member_id)
    assert before is not None

    selected_capture = _anchor_capture(cwd="/workspace/selected")
    selected_claim = identity.claim_for_capture(selected_capture)
    speaker = TautClient(
        db_path=db,
        as_name="reviewer",
        identity_capture=selected_capture,
    )
    assert speaker._state.get_identity_claim(selected_claim.claim_hash) is None
    capture_calls = capture_requests(speaker, monkeypatch)

    message = speaker.say("general", "selected explicitly")

    assert capture_calls == []
    assert message.from_id == created.member_id
    assert message.from_name == "reviewer"
    after = speaker._state.get_member(created.member_id)
    assert after is not None
    assert after["last_active_ts"] > before["last_active_ts"]
    assert after["anchor_pid"] == before["anchor_pid"]
    assert after["anchor_start_time"] == before["anchor_start_time"]
    assert after["fingerprint"] == before["fingerprint"]
    assert (
        speaker._state.get_identity_claim(established_claim.claim_hash)
        == established_claim_before
    )
    assert speaker._state.get_identity_claim(selected_claim.claim_hash) is None


def test_valid_token_selector_skips_capture_and_preserves_token_activity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """[TAUT-5]/[IAN-3.3]: token selection keeps token, not process, claims."""

    TautClient.init(db_path=tmp_path / ".taut.db")
    db = tmp_path / ".taut.db"
    established_capture = _anchor_capture(cwd="/workspace/established")
    owner = TautClient(
        db_path=db,
        as_name="reviewer",
        identity_capture=established_capture,
    )
    owner.join("general")
    created = owner.last_created_member
    assert created is not None
    assert created.token is not None
    established_claim = identity.claim_for_capture(established_capture)
    established_claim_before = owner._state.get_identity_claim(
        established_claim.claim_hash
    )
    assert established_claim_before is not None
    before = owner._state.get_member(created.member_id)
    assert before is not None

    selected_capture = _anchor_capture(cwd="/workspace/token-selected")
    selected_claim = identity.claim_for_capture(selected_capture)
    token_claim = identity.claim_for_token(created.token)
    speaker = TautClient(
        db_path=db,
        token=created.token,
        identity_capture=selected_capture,
    )
    assert speaker._state.get_identity_claim(selected_claim.claim_hash) is None
    assert speaker._state.get_identity_claim(token_claim.claim_hash) is None
    capture_calls = capture_requests(speaker, monkeypatch)

    message = speaker.say("general", "selected by token")

    assert capture_calls == []
    assert message.from_id == created.member_id
    token_claim_row = speaker._state.get_identity_claim(token_claim.claim_hash)
    assert token_claim_row is not None
    assert token_claim_row["member_id"] == created.member_id
    assert token_claim_row["claim_kind"] == "continuity_token"
    after_first = speaker._state.get_member(created.member_id)
    assert after_first is not None
    assert after_first["last_active_ts"] > before["last_active_ts"]

    second_message = speaker.say("general", "selected by token again")

    assert capture_calls == []
    assert second_message.from_id == created.member_id
    refreshed_token_claim = speaker._state.get_identity_claim(token_claim.claim_hash)
    assert refreshed_token_claim is not None
    assert refreshed_token_claim["last_seen_ts"] > token_claim_row["last_seen_ts"]
    after_second = speaker._state.get_member(created.member_id)
    assert after_second is not None
    assert after_second["last_active_ts"] > after_first["last_active_ts"]
    assert refreshed_token_claim["last_seen_ts"] == after_second["last_active_ts"]
    assert after_second["anchor_pid"] == before["anchor_pid"]
    assert after_second["anchor_start_time"] == before["anchor_start_time"]
    assert after_second["fingerprint"] == before["fingerprint"]
    assert (
        speaker._state.get_identity_claim(established_claim.claim_hash)
        == established_claim_before
    )
    assert speaker._state.get_identity_claim(selected_claim.claim_hash) is None


def test_existing_alias_selector_skips_capture_and_selects_owner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """[IAN-2.3]/[IAN-3.3]: an alias is a sufficient explicit selector."""

    TautClient.init(db_path=tmp_path / ".taut.db")
    db = tmp_path / ".taut.db"
    owner = TautClient(
        db_path=db,
        as_name="reviewer",
        identity_capture=_anchor_capture(cwd="/workspace/established"),
    )
    owner.join("general")
    created = owner.last_created_member
    assert created is not None
    owner._state.add_member_alias(
        member_id=created.member_id,
        alias="review-alias",
        created_ts=next_meta_timestamp(tmp_path),
    )
    selected_capture = _anchor_capture(cwd="/workspace/alias-selected")
    selected_claim = identity.claim_for_capture(selected_capture)
    speaker = TautClient(
        db_path=db,
        as_name="review-alias",
        identity_capture=selected_capture,
    )
    capture_calls = capture_requests(speaker, monkeypatch)

    message = speaker.say("general", "selected by alias")

    assert capture_calls == []
    assert message.from_id == created.member_id
    assert message.from_name == "reviewer"
    assert speaker._state.get_identity_claim(selected_claim.claim_hash) is None


def test_explicit_selector_outranks_token_without_touching_token_member(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """[IAN-3.3]: ordinary ``as`` precedence does not consume the token."""

    TautClient.init(db_path=tmp_path / ".taut.db")
    db = tmp_path / ".taut.db"
    explicit_owner = TautClient(
        db_path=db,
        as_name="explicit-owner",
        identity_capture=_anchor_capture(pid=101, start_time="explicit-start"),
    )
    explicit_owner.join("general")
    explicit_member = explicit_owner.last_created_member
    assert explicit_member is not None
    token_owner = TautClient(
        db_path=db,
        as_name="token-owner",
        identity_capture=_anchor_capture(pid=202, start_time="token-start"),
    )
    token_owner.join("general")
    token_member = token_owner.last_created_member
    assert token_member is not None
    assert token_member.token is not None
    token_before = token_owner._state.get_member(token_member.member_id)
    assert token_before is not None
    token_claim = identity.claim_for_token(token_member.token)
    assert token_owner._state.get_identity_claim(token_claim.claim_hash) is None

    speaker = TautClient(
        db_path=db,
        as_name="explicit-owner",
        token=token_member.token,
        identity_capture=_anchor_capture(cwd="/workspace/selected"),
    )
    capture_calls = capture_requests(speaker, monkeypatch)

    message = speaker.say("general", "explicit wins")

    assert capture_calls == []
    assert message.from_id == explicit_member.member_id
    token_after = speaker._state.get_member(token_member.member_id)
    assert token_after is not None
    assert token_after["last_active_ts"] == token_before["last_active_ts"]
    assert speaker._state.get_identity_claim(token_claim.claim_hash) is None


def test_invalid_token_fails_without_capture_or_inferred_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """[IAN-9]: an invalid deterministic selector is a terminal error."""

    TautClient.init(db_path=tmp_path / ".taut.db")
    db = tmp_path / ".taut.db"
    owner = TautClient(
        db_path=db,
        as_name="reviewer",
        identity_capture=_anchor_capture(),
    )
    owner.join("general")
    before_log = [(message.ts, message.text) for message in owner.log("general")]
    invalid = TautClient(
        db_path=db,
        token="not-a-member-token",
        identity_capture=_anchor_capture(cwd="/workspace/would-match"),
    )
    capture_calls = capture_requests(invalid, monkeypatch)

    with pytest.raises(TokenError, match="TAUT_TOKEN does not match"):
        invalid.say("general", "must not fall back")
    with pytest.raises(TokenError, match="TAUT_TOKEN does not match"):
        invalid.whoami(explain=True)

    assert capture_calls == []
    assert [
        (message.ts, message.text) for message in owner.log("general")
    ] == before_log


def test_missing_explicit_channel_actor_fails_without_capture_or_creation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """[IAN-3.3]: membership-gated writes never create throwaway actors."""

    TautClient.init(db_path=tmp_path / ".taut.db")
    db = tmp_path / ".taut.db"
    owner = TautClient(db_path=db, as_name="reviewer")
    owner.join("general")
    before_members = [member.member_id for member in owner.who()]
    before_log = [(message.ts, message.text) for message in owner.log("general")]
    missing = TautClient(
        db_path=db,
        as_name="missing",
        identity_capture=_anchor_capture(cwd="/workspace/missing"),
    )
    capture_calls = capture_requests(missing, monkeypatch)

    with pytest.raises(NotFoundError, match="member not found: missing"):
        missing.say("general", "must not create")

    assert capture_calls == []
    assert missing._state.get_member_by_route_key("missing") is None
    assert [member.member_id for member in owner.who()] == before_members
    assert [
        (message.ts, message.text) for message in owner.log("general")
    ] == before_log


def test_missing_explicit_read_only_selector_remains_guest_without_capture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """[IAN-3.3]/[IAN-9]: allow-guest resolution stays read-only."""

    TautClient.init(db_path=tmp_path / ".taut.db")
    db = tmp_path / ".taut.db"
    owner = TautClient(db_path=db, as_name="reviewer")
    owner.join("general")
    created = owner.last_created_member
    assert created is not None
    before = owner._state.get_member(created.member_id)
    assert before is not None
    guest = TautClient(
        db_path=db,
        as_name="missing",
        identity_capture=_anchor_capture(cwd="/workspace/missing-guest"),
    )
    capture_calls = capture_requests(guest, monkeypatch)

    members = guest.who()

    assert capture_calls == []
    assert [member.member_id for member in members] == [created.member_id]
    assert guest._state.get_member_by_route_key("missing") is None
    after = guest._state.get_member(created.member_id)
    assert after is not None
    assert after["last_active_ts"] == before["last_active_ts"]


def test_missing_explicit_join_captures_once_and_associates_unclaimed_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """[IAN-3.3]: creation-capable first contact captures exactly once."""

    TautClient.init(db_path=tmp_path / ".taut.db")
    db = tmp_path / ".taut.db"
    creation_capture = _anchor_capture(cwd="/workspace/first-contact")
    creation_claim = identity.claim_for_capture(creation_capture)
    newcomer = TautClient(
        db_path=db,
        as_name="newcomer",
        identity_capture=creation_capture,
    )
    capture_calls = capture_requests(newcomer, monkeypatch)

    newcomer.join("general")

    assert capture_calls == [creation_capture]
    created = newcomer.last_created_member
    assert created is not None
    assert created.name == "newcomer"
    assert newcomer.joined_thread_names() == ("general",)
    claim_row = newcomer._state.get_identity_claim(creation_claim.claim_hash)
    assert claim_row is not None
    assert claim_row["member_id"] == created.member_id


def test_missing_explicit_creation_never_steals_an_owned_process_claim(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """[IAN-3.3]: explicit creation stays reachable when its claim is owned."""

    TautClient.init(db_path=tmp_path / ".taut.db")
    db = tmp_path / ".taut.db"
    shared_capture = _anchor_capture(cwd="/workspace/shared")
    shared_claim = identity.claim_for_capture(shared_capture)
    owner = TautClient(
        db_path=db,
        as_name="owner",
        identity_capture=shared_capture,
    )
    owner.join("general")
    owner_member = owner.last_created_member
    assert owner_member is not None
    newcomer = TautClient(
        db_path=db,
        as_name="newcomer",
        identity_capture=shared_capture,
    )
    capture_calls = capture_requests(newcomer, monkeypatch)

    newcomer.join("general")

    assert capture_calls == [shared_capture]
    created = newcomer.last_created_member
    assert created is not None
    assert created.token is not None
    assert created.member_id != owner_member.member_id
    claim_row = newcomer._state.get_identity_claim(shared_claim.claim_hash)
    assert claim_row is not None
    assert claim_row["member_id"] == owner_member.member_id
    assert newcomer.whoami().member_id == created.member_id
    assert (
        TautClient(db_path=db, token=created.token).whoami().member_id
        == created.member_id
    )


def test_selector_free_claim_resolution_still_captures_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """[IAN-3.3]: automatic identity remains the selector-free default."""

    TautClient.init(db_path=tmp_path / ".taut.db")
    db = tmp_path / ".taut.db"
    automatic_capture = _anchor_capture(cwd="/workspace/automatic")
    owner = TautClient(db_path=db, identity_capture=automatic_capture)
    owner.join("general")
    created = owner.last_created_member
    assert created is not None
    actor = TautClient(db_path=db, identity_capture=automatic_capture)
    capture_calls = capture_requests(actor, monkeypatch)

    message = actor.say("general", "automatic")

    assert capture_calls == [automatic_capture]
    assert message.from_id == created.member_id


@pytest.mark.parametrize("selector_kind", ["name", "token"])
def test_rejoin_selector_captures_once_and_associates_process_claim(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    selector_kind: str,
) -> None:
    """[IAN-3.4]: rejoin is deliberate caller-chosen process association."""

    TautClient.init(db_path=tmp_path / ".taut.db")
    db = tmp_path / ".taut.db"
    owner = TautClient(
        db_path=db,
        as_name="reviewer",
        identity_capture=_anchor_capture(pid=101, start_time="owner-start"),
    )
    owner.join("general")
    created = owner.last_created_member
    assert created is not None
    assert created.token is not None
    rejoin_capture = _anchor_capture(
        pid=202,
        start_time="rejoin-start",
        cwd="/workspace/rejoin",
    )
    assert rejoin_capture.anchor is not None
    rejoin_claim = identity.claim_for_capture(rejoin_capture)
    claimant = TautClient(db_path=db, identity_capture=rejoin_capture)
    capture_calls = capture_requests(claimant, monkeypatch)

    if selector_kind == "name":
        member = claimant.rejoin("reviewer")
    else:
        member = claimant.rejoin(token=created.token)

    assert capture_calls == [rejoin_capture]
    assert member.member_id == created.member_id
    claim_row = claimant._state.get_identity_claim(rejoin_claim.claim_hash)
    assert claim_row is not None
    assert claim_row["member_id"] == created.member_id
    updated = claimant._state.get_member(created.member_id)
    assert updated is not None
    assert updated["anchor_pid"] == rejoin_capture.anchor.pid
    assert updated["anchor_start_time"] == rejoin_capture.anchor.start_time


@pytest.mark.parametrize("selector_kind", ["name", "token"])
def test_rejoin_claim_collision_captures_once_without_mutating_members(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    selector_kind: str,
) -> None:
    """[IAN-3.4]/[IAN-9]: rejoin never steals an owned process claim."""

    TautClient.init(db_path=tmp_path / ".taut.db")
    db = tmp_path / ".taut.db"
    target = TautClient(
        db_path=db,
        as_name="target",
        identity_capture=_anchor_capture(pid=101, start_time="target-start"),
    )
    target.join("general")
    target_member = target.last_created_member
    assert target_member is not None
    assert target_member.token is not None
    occupied_capture = _anchor_capture(pid=202, start_time="occupied-start")
    occupied_claim = identity.claim_for_capture(occupied_capture)
    occupied = TautClient(
        db_path=db,
        as_name="occupied",
        identity_capture=occupied_capture,
    )
    occupied.join("general")
    occupied_member = occupied.last_created_member
    assert occupied_member is not None
    target_before = occupied._state.get_member(target_member.member_id)
    occupied_before = occupied._state.get_member(occupied_member.member_id)
    claim_before = occupied._state.get_identity_claim(occupied_claim.claim_hash)
    assert target_before is not None
    assert occupied_before is not None
    assert claim_before is not None
    claimant = TautClient(db_path=db, identity_capture=occupied_capture)
    capture_calls = capture_requests(claimant, monkeypatch)

    with pytest.raises(
        IdentityError,
        match="current identity claim already belongs to occupied",
    ):
        if selector_kind == "name":
            claimant.rejoin("target")
        else:
            claimant.rejoin(token=target_member.token)

    assert capture_calls == [occupied_capture]
    assert claimant._state.get_member(target_member.member_id) == target_before
    assert claimant._state.get_member(occupied_member.member_id) == occupied_before
    assert claimant._state.get_identity_claim(occupied_claim.claim_hash) == claim_before


@pytest.mark.parametrize(
    ("selector_kind", "expected_rule"),
    [("as", "explicit --as"), ("token", "continuity token")],
)
def test_selector_whoami_explain_captures_without_associating_process_claim(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    selector_kind: str,
    expected_rule: str,
) -> None:
    """[IAN-3.2]: explanation observes evidence without persisting it."""

    TautClient.init(db_path=tmp_path / ".taut.db")
    db = tmp_path / ".taut.db"
    owner = TautClient(
        db_path=db,
        as_name="reviewer",
        identity_capture=_anchor_capture(pid=101, start_time="owner-start"),
    )
    owner.join("general")
    created = owner.last_created_member
    assert created is not None
    assert created.token is not None
    before = owner._state.get_member(created.member_id)
    assert before is not None
    diagnostic_capture = _anchor_capture(
        pid=202,
        start_time="diagnostic-start",
        cwd="/workspace/diagnostic",
    )
    diagnostic_claim = identity.claim_for_capture(diagnostic_capture)
    if selector_kind == "as":
        observer = TautClient(
            db_path=db,
            as_name="reviewer",
            identity_capture=diagnostic_capture,
        )
    else:
        observer = TautClient(
            db_path=db,
            token=created.token,
            identity_capture=diagnostic_capture,
        )
    capture_calls = capture_requests(observer, monkeypatch)

    explained = observer.whoami(explain=True)

    assert capture_calls == [diagnostic_capture]
    assert explained.member_id == created.member_id
    assert explained.explain is not None
    assert explained.explain["rule"] == expected_rule
    explained_anchor = explained.explain["anchor"]
    assert isinstance(explained_anchor, dict)
    assert explained_anchor["pid"] == 202
    assert observer._state.get_identity_claim(diagnostic_claim.claim_hash) is None
    after = observer._state.get_member(created.member_id)
    assert after is not None
    assert after["anchor_pid"] == before["anchor_pid"]
    assert after["anchor_start_time"] == before["anchor_start_time"]
    assert after["fingerprint"] == before["fingerprint"]


@pytest.mark.parametrize("selector_kind", ["as", "token"])
def test_read_only_selector_resolution_skips_capture_and_state_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    selector_kind: str,
) -> None:
    """[TAUT-8.3]/[IAN-3.3]: read-only selection stays fully read-only."""

    TautClient.init(db_path=tmp_path / ".taut.db")
    db = tmp_path / ".taut.db"
    owner = TautClient(db_path=db, as_name="reviewer")
    owner.join("general")
    created = owner.last_created_member
    assert created is not None
    assert created.token is not None
    before = owner._state.get_member(created.member_id)
    assert before is not None
    token_claim = identity.claim_for_token(created.token)
    assert owner._state.get_identity_claim(token_claim.claim_hash) is None
    meta = Queue(META_QUEUE_NAME, db_path=str(db))
    try:
        before_high_water = meta.refresh_last_ts()
        if selector_kind == "as":
            viewer = TautClient(
                db_path=db,
                as_name="reviewer",
                identity_capture=_anchor_capture(cwd="/workspace/read-only"),
            )
        else:
            viewer = TautClient(
                db_path=db,
                token=created.token,
                identity_capture=_anchor_capture(cwd="/workspace/read-only"),
            )
        capture_calls = capture_requests(viewer, monkeypatch)

        names = viewer.joined_thread_names()
        after_high_water = meta.refresh_last_ts()
    finally:
        meta.close()

    assert names == ("general",)
    assert capture_calls == []
    assert viewer._state.get_member(created.member_id) == before
    assert after_high_water == before_high_water
    assert viewer._state.get_identity_claim(token_claim.claim_hash) is None


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


def test_explicit_name_collision_never_adopts_current_claim_owner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """[IAN-3.3]: a name race cannot override explicit selector authority."""

    TautClient.init(db_path=tmp_path / ".taut.db")
    db = tmp_path / ".taut.db"
    owner_capture = _anchor_capture(pid=301, start_time="owner-start")
    owner = TautClient(db_path=db, as_name="owner", identity_capture=owner_capture)
    owner.join("general")
    owner_member = owner.whoami()
    winner = TautClient(
        db_path=db,
        as_name="newcomer",
        identity_capture=_anchor_capture(pid=302, start_time="winner-start"),
    )
    loser = TautClient(
        db_path=db,
        as_name="newcomer",
        identity_capture=owner_capture,
    )

    original_insert = SqlSidecarTautState.insert_member
    fired = {"done": False}

    def racing_insert(self: SqlSidecarTautState, **kwargs: object) -> object:
        if (
            self is loser._state
            and kwargs.get("display_name") == "newcomer"
            and not fired["done"]
        ):
            fired["done"] = True
            winner.join("general")
        return original_insert(self, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(SqlSidecarTautState, "insert_member", racing_insert)

    with pytest.raises(IdentityError):
        loser.join("general")

    assert loser.last_created_member is None
    assert owner.whoami().member_id == owner_member.member_id
    assert winner.whoami().name == "newcomer"


def test_explicit_creation_claim_race_keeps_new_member_authoritative(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """[IAN-3.3]: a claim race cannot replace a newly inserted explicit member."""

    TautClient.init(db_path=tmp_path / ".taut.db")
    db = tmp_path / ".taut.db"
    owner = TautClient(
        db_path=db,
        as_name="owner",
        identity_capture=_anchor_capture(pid=401, start_time="owner-start"),
    )
    owner.join("owners")
    owner_member = owner.whoami()
    selected_capture = _anchor_capture(pid=402, start_time="selected-start")
    selected_claim = identity.claim_for_capture(selected_capture)
    creator = TautClient(
        db_path=db,
        as_name="newcomer",
        identity_capture=selected_capture,
    )

    original_add = SqlSidecarTautState.add_identity_claim
    fired = {"done": False}

    def racing_add(self: SqlSidecarTautState, **kwargs: object) -> object:
        if (
            self is creator._state
            and kwargs.get("claim_hash") == selected_claim.claim_hash
            and kwargs.get("member_id") != owner_member.member_id
            and not fired["done"]
        ):
            fired["done"] = True
            owner_kwargs = dict(kwargs)
            owner_kwargs["member_id"] = owner_member.member_id
            original_add(self, **owner_kwargs)  # type: ignore[arg-type]
        return original_add(self, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(SqlSidecarTautState, "add_identity_claim", racing_add)

    creator.join("general")

    created = creator.last_created_member
    assert created is not None
    assert created.name == "newcomer"
    assert creator.joined_thread_names() == ("general",)
    assert owner.joined_thread_names() == ("owners",)
    claim_row = creator._state.get_identity_claim(selected_claim.claim_hash)
    assert claim_row is not None
    assert claim_row["member_id"] == owner_member.member_id


def test_explicit_creation_unowned_claim_integrity_failure_remains_fatal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """[IAN-3.3]: recovery requires proof that another member owns the claim."""

    TautClient.init(db_path=tmp_path / ".taut.db")
    db = tmp_path / ".taut.db"
    selected_capture = _anchor_capture(pid=403, start_time="selected-start")
    selected_claim = identity.claim_for_capture(selected_capture)
    creator = TautClient(
        db_path=db,
        as_name="newcomer",
        identity_capture=selected_capture,
    )

    def failing_add(self: SqlSidecarTautState, **kwargs: object) -> object:
        raise IntegrityError("injected claim integrity failure")

    monkeypatch.setattr(SqlSidecarTautState, "add_identity_claim", failing_add)

    with pytest.raises(IntegrityError, match="injected claim integrity failure"):
        creator.join("general")

    assert creator._state.get_identity_claim(selected_claim.claim_hash) is None


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
        (
            "mention notifications suppressed: direct-message registry row for "
            f"{thread} lacks participant metadata"
        )
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
        (
            "mention notifications suppressed: direct-message registry row for "
            f"{thread} lacks participant metadata"
        )
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
