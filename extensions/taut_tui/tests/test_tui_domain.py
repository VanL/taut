"""Native extension action mapping to public Taut operations.

Spec references:
- docs/specs/10-taut-tui.md [TUI-2.3], [TUI-6], [TUI-7]
"""

from __future__ import annotations

from pathlib import Path

import pytest

from taut.client import TautClient
from taut_tui.actions import ActionId

pytestmark = pytest.mark.sqlite_only


def _seed(db_path: Path) -> tuple[TautClient, TautClient]:
    TautClient.init(db_path=db_path)
    alice = TautClient(db_path=db_path, as_name="alice")
    bob = TautClient(db_path=db_path, as_name="bob")
    for client in (alice, bob):
        client.join("general")
    return alice, bob


def test_every_nonvisual_nonsummon_action_has_native_domain_ownership() -> None:
    from taut_tui.domain import CORE_DOMAIN_ACTIONS

    visual = {
        ActionId.COMPOSE_ENTER,
        ActionId.COMMAND_OPEN,
        ActionId.HELP_OPEN,
        ActionId.APPLICATION_QUIT,
    }
    summon = {
        ActionId.SUMMON_START,
        ActionId.SUMMON_LIST,
        ActionId.SUMMON_STATUS,
        ActionId.SUMMON_DISMISS,
    }

    assert CORE_DOMAIN_ACTIONS == set(ActionId) - visual - summon


def test_native_identity_channel_message_search_and_context_flow(
    tmp_path: Path,
) -> None:
    from taut_tui.domain import TuiDomainActions
    from taut_tui.session import TuiSession
    from taut_tui.system import TuiSystemOperations

    db_path = tmp_path / "chat.db"
    alice, bob = _seed(db_path)
    session = TuiSession(db_path=str(db_path), as_name="alice", continuity_token=None)
    system = TuiSystemOperations(db_path=str(db_path))
    actions = TuiDomainActions(
        session=session,
        system=system,
        db_path=str(db_path),
    )
    try:
        assert actions.show_identity().result(timeout=5).name == "alice"
        assert actions.set_persona("reviewer").result(timeout=5).persona == "reviewer"
        assert actions.members("general").result(timeout=5)
        topic = actions.set_topic("general", "Release coordination").result(timeout=5)
        assert topic.topic == "Release coordination"
        assert actions.show_topic("general").result(timeout=5) == topic

        sent = actions.send_message("general", "searchable marker").result(timeout=5)
        hits = actions.search("searchable marker").result(timeout=5)
        hit = next(item for item in hits if item.ts == sent.ts)
        context = actions.open_search_result(hit, before=1, after=1).result(timeout=5)
        assert any(message.ts == sent.ts for message in context)

        reaction = actions.react_message(sent.ts, "ack").result(timeout=5)
        assert reaction.message_ts == sent.ts
        deletion = actions.delete_message(sent.ts).result(timeout=5)
        assert deletion.ts == sent.ts
        assert actions.clear_topic("general").result(timeout=5).topic is None
    finally:
        session.close()
        system.close()
        alice.close()
        bob.close()


def test_direct_message_and_reply_flows_keep_core_target_semantics(
    tmp_path: Path,
) -> None:
    from taut_tui.domain import TuiDomainActions
    from taut_tui.session import TuiSession
    from taut_tui.system import TuiSystemOperations

    db_path = tmp_path / "chat.db"
    alice, bob = _seed(db_path)
    origin = bob.say("general", "please review")
    session = TuiSession(db_path=str(db_path), as_name="alice", continuity_token=None)
    system = TuiSystemOperations(db_path=str(db_path))
    actions = TuiDomainActions(
        session=session,
        system=system,
        db_path=str(db_path),
    )
    try:
        direct = actions.start_direct_message("bob", "hello privately").result(
            timeout=5
        )
        reply = actions.reply_message("general", origin.ts, "reviewed").result(
            timeout=5
        )
    finally:
        session.close()
        system.close()
        alice.close()
        bob.close()

    assert direct.thread.startswith("dm.")
    assert reply.thread == f"general.{origin.ts}"


def test_empty_real_search_returns_the_domain_empty_collection(tmp_path: Path) -> None:
    from taut_tui.domain import TuiDomainActions
    from taut_tui.session import TuiSession
    from taut_tui.system import TuiSystemOperations

    db_path = tmp_path / "empty-search.db"
    alice, bob = _seed(db_path)
    session = TuiSession(db_path=str(db_path), as_name="alice", continuity_token=None)
    system = TuiSystemOperations(db_path=str(db_path))
    actions = TuiDomainActions(
        session=session,
        system=system,
        db_path=str(db_path),
    )
    try:
        assert actions.search("nothing-can-match-this").result(timeout=5) == []
    finally:
        session.close()
        system.close()
        alice.close()
        bob.close()


# --- Slice 6 of docs/plans/2026-08-18-tui-deep-review-remediation-plan.md ---


def test_empty_read_inbox_log_and_dm_list_return_empty_collections(
    tmp_path: Path,
) -> None:
    """[TUI-12.1] empty results are results, not errors."""

    from taut_tui.domain import TuiDomainActions
    from taut_tui.session import TuiSession
    from taut_tui.system import TuiSystemOperations

    db_path = tmp_path / "empty.db"
    alice, bob = _seed(db_path)
    session = TuiSession(db_path=str(db_path), as_name="alice", continuity_token=None)
    system = TuiSystemOperations(db_path=str(db_path))
    actions = TuiDomainActions(
        session=session,
        system=system,
        db_path=str(db_path),
    )
    from contextlib import suppress

    with suppress(Exception):
        alice.read()  # consume anything unread so every surface is empty
    try:
        assert actions.read_messages().result(timeout=10) == []
        assert actions.inbox().result(timeout=10) == []
        assert actions.list_threads(direct_messages=True).result(timeout=10) == []
    finally:
        session.close()
        system.close()
        alice.close()
        bob.close()


def test_start_direct_message_normalizes_leading_at(tmp_path: Path) -> None:
    from taut_tui.domain import TuiDomainActions
    from taut_tui.session import TuiSession
    from taut_tui.system import TuiSystemOperations

    db_path = tmp_path / "dm.db"
    alice, bob = _seed(db_path)
    session = TuiSession(db_path=str(db_path), as_name="alice", continuity_token=None)
    system = TuiSystemOperations(db_path=str(db_path))
    actions = TuiDomainActions(
        session=session,
        system=system,
        db_path=str(db_path),
    )
    try:
        sent = actions.start_direct_message("@bob", "typed with an at").result(
            timeout=10
        )
        assert sent.text == "typed with an at"
        replies = [
            message
            for message in bob.read()
            if message.text == "typed with an at"
        ]
        assert len(replies) == 1
    finally:
        session.close()
        system.close()
        alice.close()
        bob.close()


def test_commit_returned_message_ignores_unrelated_threads(tmp_path: Path) -> None:
    from taut.client import Message
    from taut_tui.session import ConversationSnapshot, TuiSession

    db_path = tmp_path / "commit.db"
    alice, bob = _seed(db_path)
    session = TuiSession(db_path=str(db_path), as_name="alice", continuity_token=None)
    try:
        snapshot = ConversationSnapshot(
            generation=1,
            target="general",
            messages=(),
        )
        with session._state_lock:
            session._conversation = snapshot
        unrelated = Message("elsewhere", 99, "m_bob", "bob", "message", "hi")
        assert session.commit_returned_message(unrelated) is None
        related = Message("general", 100, "m_bob", "bob", "message", "hi")
        committed = session.commit_returned_message(related)
        assert committed is not None
        assert committed.messages[-1].ts == 100
    finally:
        session.close()
        alice.close()
        bob.close()


def test_session_close_without_wait_returns_promptly_despite_parked_commit(
    tmp_path: Path,
) -> None:
    """[TUI-12.3] teardown must not stall behind a parked worker commit."""

    import time
    from threading import Event

    from taut_tui.session import TuiSession

    db_path = tmp_path / "close.db"
    alice, bob = _seed(db_path)
    bob.say("general", "content to commit")
    release = Event()
    parked = Event()

    def blocking_commit(snapshot: object) -> bool:
        parked.set()
        release.wait(10)
        return True

    session = TuiSession(
        db_path=str(db_path),
        as_name="alice",
        continuity_token=None,
        commit_conversation=blocking_commit,
    )
    try:
        session.open_conversation("general")
        assert parked.wait(10)
        started = time.monotonic()
        session.close(wait=False)
        elapsed = time.monotonic() - started
        assert elapsed < 1.0
    finally:
        release.set()
        alice.close()
        bob.close()


def test_rejected_reply_open_does_not_claim_unread_replies(tmp_path: Path) -> None:
    from taut_tui.session import TuiSession

    db_path = tmp_path / "reply-claim.db"
    alice, bob = _seed(db_path)
    origin = bob.say("general", "origin message")
    bob.reply("general", str(origin.ts), "unread reply for alice")
    reply_thread = next(
        thread.name
        for thread in alice.list_threads(all_threads=True)
        if thread.kind == "subthread"
    )

    session = TuiSession(
        db_path=str(db_path),
        as_name="alice",
        continuity_token=None,
        commit_conversation=lambda _snapshot: False,  # superseded open
    )
    try:
        result = session.open_conversation(
            "general", reply_thread=reply_thread
        ).result(timeout=10)
        assert result is None
        still_unread = session.submit_client_operation(
            lambda client: client.read_unread(reply_thread)
        ).result(timeout=10)
        assert any(
            message.text == "unread reply for alice" for message in still_unread
        )
    finally:
        session.close()
        alice.close()
        bob.close()
