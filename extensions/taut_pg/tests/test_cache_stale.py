"""Real PG source coverage for cache invalidation [TAUT-8.4], [IAN-7.4]."""

from __future__ import annotations

import threading
from contextlib import closing
from pathlib import Path

import pytest

from taut._constants import CACHE_STALE_QUEUE_NAME
from taut.client import Message, TautClient

pytestmark = pytest.mark.pg_only


def test_peer_join_wakes_existing_watcher_without_membership_timer(
    taut_pg_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(taut_pg_project)
    TautClient.init()
    with (
        closing(TautClient(as_name="listener")) as listener,
        closing(TautClient(as_name="peer")) as peer,
    ):
        listener.join("general")
        peer.join("other")
        delivered = threading.Event()

        def handle(item: object) -> None:
            if isinstance(item, Message) and item.text == "new membership delivery":
                delivered.set()

        watcher = listener.watch(handle)
        ready = threading.Event()
        watcher.notify_ready_after_initial_drain(ready)
        thread = watcher.start()
        try:
            assert ready.wait(5)
            assert watcher.next_wait_timeout() is None
            with closing(TautClient(as_name="listener")) as writer:
                writer.join("other")
            peer.say("other", "new membership delivery")
            assert delivered.wait(5)
        finally:
            watcher.stop()
            thread.join(5)
        assert not thread.is_alive()


def test_normal_peer_claim_publishes_bounded_hint_on_postgres(
    taut_pg_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(taut_pg_project)
    TautClient.init()
    with (
        closing(TautClient(as_name="alice")) as alice,
        closing(TautClient(as_name="bob")) as bob,
    ):
        alice.join("general")
        bob.join("general")
        alice.say("general", "hello @bob")
        hints = alice.queue(CACHE_STALE_QUEUE_NAME)
        before = hints.peek_many(1, with_timestamps=True)[0][1]
        with closing(TautClient(as_name="bob")) as peer:
            assert peer.inbox()
        assert not bob.peek_inbox()
        rows = hints.peek_many(10, with_timestamps=True)
        assert len(rows) == 1 and rows[0][1] > before
