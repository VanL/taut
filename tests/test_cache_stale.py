"""Advisory invalidation publication after authoritative operations [IAN-6.1]."""

from contextlib import closing
from pathlib import Path
from typing import Any

import pytest
from simplebroker import Queue

from taut.client import TautClient
from taut.state import SqlSidecarTautState
from taut.watcher import TautWatcher

pytestmark = pytest.mark.sqlite_only
CACHE = "taut.cache_stale"


@pytest.mark.parametrize("watcher_type", [object, lambda: None])
def test_watch_rejects_invalid_policy_before_runtime_acquisition(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, watcher_type: Any
) -> None:
    import taut.client._watching as client_module

    db = tmp_path / ".taut.db"
    TautClient.init(db_path=db)
    with closing(TautClient(db_path=db, as_name="alice")) as client:

        def unexpected_runtime(*args: Any, **kwargs: Any) -> None:
            raise AssertionError("invalid policy must fail before runtime creation")

        monkeypatch.setattr(
            client_module, "_watch_runtime_for_client", unexpected_runtime
        )
        with pytest.raises(TypeError, match="watcher_type"):
            client.watch(lambda _: None, watcher_type=watcher_type)


def test_client_watch_constructs_policy_subclass_with_owned_runtime(
    tmp_path: Path,
) -> None:
    class PolicyWatcher(TautWatcher):
        pass

    db = tmp_path / ".taut.db"
    TautClient.init(db_path=db)
    client = TautClient(db_path=db, as_name="alice")
    client.join("general")
    try:
        watcher = client.watch(lambda item: None, watcher_type=PolicyWatcher)
        try:
            assert isinstance(watcher, PolicyWatcher)
            client.close()
            watcher.process_once()
        finally:
            watcher.stop()
    finally:
        client.close()


@pytest.mark.parametrize(
    "operation", ["join", "leave", "reply", "implicit", "dm", "rename", "claim"]
)
def test_authoritative_operations_publish_cache_hint(
    tmp_path: Path, operation: str
) -> None:
    db = tmp_path / ".taut.db"
    TautClient.init(db_path=db)
    with (
        closing(TautClient(db_path=db, as_name="alice")) as alice,
        closing(TautClient(db_path=db, as_name="bob")) as bob,
    ):
        alice.join("general")
        bob.join("general")
        origin = alice.say("general", "hello @bob")
        child = alice.reply("general", str(origin.ts), "child")
        with Queue(CACHE, db_path=str(db)) as hints:
            before = hints.peek_many(1, with_timestamps=True)
            cursor = before[0][1] if before else 0
            if operation == "join":
                alice.join("other")
            elif operation == "leave":
                alice.leave("general")
            elif operation == "reply":
                bob.reply("general", str(origin.ts), "reply")
            elif operation == "implicit":
                bob.read_unread(child.thread)
            elif operation == "dm":
                alice.say("@bob", "private")
            elif operation == "rename":
                alice.rename_channel("general", "renamed")
            else:
                assert bob.inbox()
            rows = hints.peek_many(10, with_timestamps=True)
            assert len(rows) == 1
            assert rows[0][1] > cursor
        assert CACHE not in {
            thread.name for thread in alice.list_threads(all_threads=True)
        }


@pytest.mark.parametrize("operation", ["join", "claim"])
def test_hint_failure_preserves_committed_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    operation: str,
) -> None:
    db = tmp_path / ".taut.db"
    TautClient.init(db_path=db)
    with (
        closing(TautClient(db_path=db, as_name="alice")) as alice,
        closing(TautClient(db_path=db, as_name="bob")) as bob,
    ):
        alice.join("general")
        bob.join("general")
        alice.say("general", "hello @bob")
        original = Queue.write

        def fail_hint(self: Queue, message: str, **kwargs: Any) -> int:
            if self.name == CACHE:
                raise RuntimeError("hint unavailable")
            return original(self, message, **kwargs)

        monkeypatch.setattr(Queue, "write", fail_hint)
        if operation == "join":
            joined = bob.join("other")
            assert joined is not None
            assert joined.thread == "other"
            assert "other" in bob.joined_thread_names()
        else:
            assert bob.inbox()
            assert not bob.peek_inbox()
        assert "cache invalidation publication failed" in caplog.text


def test_resumed_rename_publishes_after_sidecar_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = tmp_path / ".taut.db"
    TautClient.init(db_path=db)
    with closing(TautClient(db_path=db, as_name="alice")) as client:
        client.join("general")
        original = SqlSidecarTautState.apply_channel_rename_state

        def fail_before_commit(self: SqlSidecarTautState, **kwargs: Any) -> None:
            raise RuntimeError("interrupted rename")

        monkeypatch.setattr(
            SqlSidecarTautState, "apply_channel_rename_state", fail_before_commit
        )
        with pytest.raises(RuntimeError, match="interrupted rename"):
            client.rename_channel("general", "renamed")
        with Queue(CACHE, db_path=str(db)) as hints:
            before = hints.peek_many(1, with_timestamps=True)[0][1]
            monkeypatch.setattr(
                SqlSidecarTautState, "apply_channel_rename_state", original
            )
            assert client.rename_channel("general", "renamed").name == "renamed"
            assert hints.has_pending(after_timestamp=before)


def test_queue_acquisition_failure_does_not_fail_committed_membership(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    db = tmp_path / ".taut.db"
    TautClient.init(db_path=db)
    with closing(TautClient(db_path=db, as_name="alice")) as client:
        original = client.queue

        def fail_acquisition(name: str, **kwargs: Any) -> Queue:
            if name == CACHE:
                raise RuntimeError("cannot open advisory source")
            return original(name, **kwargs)

        monkeypatch.setattr(client, "queue", fail_acquisition)
        joined = client.join("general")
        assert joined is not None
        assert joined.thread == "general"
        assert client.joined_thread_names() == ("general",)
        assert "cache invalidation publication failed" in caplog.text


def test_cursor_updates_and_empty_claim_do_not_publish_hints(tmp_path: Path) -> None:
    from taut import EmptyResultError

    db = tmp_path / ".taut.db"
    TautClient.init(db_path=db)
    with closing(TautClient(db_path=db, as_name="alice")) as alice:
        alice.join("general")
        with closing(TautClient(db_path=db, as_name="bob")) as bob:
            bob.join("general")
            bob.say("general", "no mention")
        with Queue(CACHE, db_path=str(db)) as hints:
            before = hints.peek_many(1, with_timestamps=True)[0][1]
            assert alice.read_unread("general")
            with pytest.raises(EmptyResultError):
                alice.inbox()
            assert not hints.has_pending(after_timestamp=before)
