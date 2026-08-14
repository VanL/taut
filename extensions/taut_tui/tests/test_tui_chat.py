"""Serialized extension session ownership and active-only live delivery tests.

Spec references:
- docs/specs/10-taut-tui.md [TUI-4.1], [TUI-6]
"""

from __future__ import annotations

import time
from pathlib import Path
from threading import Event, Lock

import pytest

from taut.client import Message, Notification, TautClient

pytestmark = pytest.mark.sqlite_only


def _wait_until(predicate: object, *, timeout: float = 5.0) -> None:
    check = predicate
    assert callable(check)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if check():
            return
        time.sleep(0.01)
    pytest.fail("condition did not become true")


def _seed(db_path: Path) -> tuple[TautClient, TautClient]:
    TautClient.init(db_path=db_path)
    alice = TautClient(db_path=db_path, as_name="alice")
    bob = TautClient(db_path=db_path, as_name="bob")
    for client in (alice, bob):
        client.join("general")
        client.join("quiet")
    return alice, bob


def test_navigation_uses_public_joined_channels_and_actor_scoped_dms(
    tmp_path: Path,
) -> None:
    from taut_tui.session import TuiSession

    db_path = tmp_path / "chat.db"
    alice, bob = _seed(db_path)
    alice.say("@bob", "hello")
    session = TuiSession(db_path=str(db_path), as_name="alice", continuity_token=None)
    try:
        navigation = session.refresh_navigation().result(timeout=5)
    finally:
        session.close()
        alice.close()
        bob.close()

    assert [thread.name for thread in navigation.channels] == ["general", "quiet"]
    assert len(navigation.direct_messages) == 1
    assert navigation.direct_messages[0].display_name == "DM with bob"
    assert navigation.direct_messages[0].name != "DM with bob"


def test_only_active_conversation_advances_while_inactive_stays_unread(
    tmp_path: Path,
) -> None:
    from taut_tui.session import ConversationSnapshot, TuiSession

    db_path = tmp_path / "chat.db"
    alice, bob = _seed(db_path)
    deliveries: list[Message | Notification] = []
    committed: list[ConversationSnapshot] = []
    lock = Lock()

    def commit(snapshot: ConversationSnapshot) -> bool:
        with lock:
            committed.append(snapshot)
        return True

    def accept(_generation: int, item: Message | Notification) -> bool:
        with lock:
            deliveries.append(item)
        return True

    session = TuiSession(
        db_path=str(db_path),
        as_name="alice",
        continuity_token=None,
        commit_conversation=commit,
        accept_delivery=accept,
    )
    try:
        session.open_conversation("general").result(timeout=5)
        bob.say("general", "active")
        quiet_message = bob.say("quiet", "inactive")
        _wait_until(
            lambda: any(
                isinstance(item, Message) and item.text == "active"
                for item in deliveries
            )
        )
        navigation = session.refresh_navigation().result(timeout=5)
    finally:
        session.close()
        alice.close()
        bob.close()

    assert committed[-1].target == "general"
    assert not any(
        isinstance(item, Message) and item.ts == quiet_message.ts for item in deliveries
    )
    quiet = next(item for item in navigation.channels if item.name == "quiet")
    assert quiet.unread is True
    assert quiet.unread_count >= 1


def test_latest_switch_wins_and_stops_old_watcher_before_replacement(
    tmp_path: Path,
) -> None:
    from taut_tui.session import ConversationSnapshot, TuiSession

    db_path = tmp_path / "chat.db"
    alice, bob = _seed(db_path)
    commits: list[ConversationSnapshot] = []
    deliveries: list[Message | Notification] = []

    def commit(snapshot: ConversationSnapshot) -> bool:
        commits.append(snapshot)
        return True

    def accept(_generation: int, item: Message | Notification) -> bool:
        deliveries.append(item)
        return True

    session = TuiSession(
        db_path=str(db_path),
        as_name="alice",
        continuity_token=None,
        commit_conversation=commit,
        accept_delivery=accept,
    )
    try:
        first = session.open_conversation("general")
        second = session.open_conversation("quiet")
        first.result(timeout=5)
        second.result(timeout=5)
        general_message = bob.say("general", "old inactive")
        bob.say("quiet", "new active")
        _wait_until(
            lambda: any(
                isinstance(item, Message) and item.text == "new active"
                for item in deliveries
            )
        )
    finally:
        session.close()
        alice.close()
        bob.close()

    assert commits[-1].target == "quiet"
    assert not any(
        isinstance(item, Message) and item.ts == general_message.ts
        for item in deliveries
    )


def test_shutdown_rejection_does_not_acknowledge_chat_message(tmp_path: Path) -> None:
    from taut_tui.session import TuiSession

    db_path = tmp_path / "chat.db"
    alice, bob = _seed(db_path)
    rejected = Event()

    def reject(_generation: int, _item: Message | Notification) -> bool:
        rejected.set()
        return False

    session = TuiSession(
        db_path=str(db_path),
        as_name="alice",
        continuity_token=None,
        accept_delivery=reject,
    )
    try:
        session.open_conversation("general").result(timeout=5)
        sent = bob.say("general", "must replay")
        assert rejected.wait(5)
    finally:
        session.close()

    replay = alice.read_unread("general")
    alice.close()
    bob.close()

    assert any(message.ts == sent.ts for message in replay)


def test_current_delivery_rejection_reports_visible_degradation_owner_event(
    tmp_path: Path,
) -> None:
    from taut_tui.session import TuiSession

    db_path = tmp_path / "degraded.db"
    alice, bob = _seed(db_path)
    degraded: list[tuple[int, str]] = []
    reported = Event()

    def reject(_generation: int, _item: Message | Notification) -> bool:
        return False

    def report(generation: int, detail: str) -> None:
        degraded.append((generation, detail))
        reported.set()

    session = TuiSession(
        db_path=str(db_path),
        as_name="alice",
        continuity_token=None,
        accept_delivery=reject,
        report_watcher_degraded=report,
    )
    try:
        session.open_conversation("general").result(timeout=5)
        bob.say("general", "reject and degrade")
        assert reported.wait(5)
        assert degraded == [(1, "watcher exited unexpectedly")]
    finally:
        session.close()
        alice.close()
        bob.close()


def test_close_attempts_client_cleanup_when_watcher_stop_times_out() -> None:
    from taut_tui.session import TuiSession, WatcherStopTimeout

    class StuckThread:
        def is_alive(self) -> bool:
            return True

    class StuckWatcher:
        def request_stop(self) -> None:
            return None

        def stop(self, *, join: bool, timeout: float | None = None) -> None:
            del join, timeout

    class ClosingClient:
        def __init__(self) -> None:
            self.closed = False

        def close(self) -> None:
            self.closed = True

    session = TuiSession(db_path=None, as_name=None, continuity_token=None)
    client = ClosingClient()
    session._watcher = (StuckWatcher(), StuckThread())  # type: ignore[assignment]
    session._client = client  # type: ignore[assignment]

    with pytest.raises(WatcherStopTimeout):
        session.close()

    assert client.closed is True


def test_explicit_reply_open_commits_claimed_history_and_watches_both_surfaces(
    tmp_path: Path,
) -> None:
    from taut_tui.session import ConversationSnapshot, TuiSession

    db_path = tmp_path / "chat.db"
    alice, bob = _seed(db_path)
    origin = alice.say("general", "root")
    first_reply = bob.reply("general", str(origin.ts), "first reply")
    commits: list[ConversationSnapshot] = []
    deliveries: list[Message | Notification] = []

    def commit(snapshot: ConversationSnapshot) -> bool:
        commits.append(snapshot)
        return True

    def accept(_generation: int, item: Message | Notification) -> bool:
        deliveries.append(item)
        return True

    session = TuiSession(
        db_path=str(db_path),
        as_name="alice",
        continuity_token=None,
        commit_conversation=commit,
        accept_delivery=accept,
    )
    try:
        snapshot = session.open_conversation(
            "general",
            reply_thread=first_reply.thread,
        ).result(timeout=5)
        assert snapshot is not None
        assert any(message.ts == first_reply.ts for message in snapshot.reply_messages)

        parent_live = bob.say("general", "parent live")
        reply_live = bob.reply("general", str(origin.ts), "reply live")
        _wait_until(
            lambda: {parent_live.ts, reply_live.ts}.issubset(
                {item.ts for item in deliveries if isinstance(item, Message)}
            )
        )

        closed = session.open_conversation("general").result(timeout=5)
        assert closed is not None
        assert closed.reply_thread is None
        later_reply = bob.reply("general", str(origin.ts), "inactive reply")
        time.sleep(0.1)
    finally:
        session.close()

    replay = alice.read_unread(first_reply.thread)
    alice.close()
    bob.close()

    assert commits[0].reply_thread == first_reply.thread
    assert any(message.ts == later_reply.ts for message in replay)
