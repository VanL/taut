"""Public search behavior through the real client and SQLite provider.

Spec references:
- docs/specs/06-search.md [SRCH-2], [SRCH-3], [SRCH-4], [SRCH-5], [SRCH-11.1]
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import cast

import pytest
from simplebroker import Queue, open_broker

from taut._constants import META_QUEUE_NAME
from taut._exceptions import EmptyResultError
from taut.client import TautClient
from taut.client import _searching as searching
from taut.client._searching import SearchingMixin
from taut.envelope import encode_envelope
from taut.search._jobs import (
    CLAIMED_QUEUE_NAME,
    FAILED_QUEUE_NAME,
    PENDING_QUEUE_NAME,
    ThreadRenameJob,
    decode_message_job,
    decode_search_job,
)
from taut.search._sqlite import SQLiteSearchProvider
from taut.state import ThreadRow

pytestmark = pytest.mark.sqlite_only


def test_search_bootstraps_index_and_returns_hydrated_source(tmp_path: Path) -> None:
    db_path = tmp_path / ".taut.db"
    TautClient.init(db_path=db_path)
    client = TautClient(db_path=db_path, as_name="alice")
    client.join("general")
    source = client.say("general", "find this needle")

    hits = client.search("needle")

    assert [
        (
            hit.thread,
            hit.ts,
            hit.from_id,
            hit.from_name,
            hit.kind,
            hit.text,
            hit.thread_kind,
            hit.channel,
            hit.parent,
            hit.members,
        )
        for hit in hits
    ] == [
        (
            "general",
            source.ts,
            source.from_id,
            "alice",
            "message",
            "find this needle",
            "channel",
            "general",
            None,
            None,
        )
    ]


def test_search_upgrades_legacy_claimed_work_without_rebuilding_index(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / ".taut.db"
    TautClient.init(db_path=db_path)
    client = TautClient(db_path=db_path, as_name="alice")
    client.join("general")
    first = client.say("general", "first stable needle")
    assert [hit.ts for hit in client.search("needle")] == [first.ts]
    second = client.say("general", "second stable needle")
    pending = Queue(PENDING_QUEUE_NAME, db_path=str(db_path))
    claimed = Queue(CLAIMED_QUEUE_NAME, db_path=str(db_path))
    failed = Queue(FAILED_QUEUE_NAME, db_path=str(db_path))
    try:
        work = pending.peek_many(10, with_timestamps=True)
        second_job = next(
            job_ts
            for body, job_ts in work
            if decode_message_job(body).message_ts == second.ts
        )
        assert (
            pending.move_one(claimed, exact_timestamp=second_job, with_timestamps=True)
            is not None
        )
        failed.write("obsolete failure")
        with client._meta_queue.sidecar(transaction=True) as session:
            before = list(
                session.run(
                    "SELECT current_generation FROM taut_search_metadata",
                    fetch=True,
                )
            )
            session.run(
                "UPDATE taut_search_metadata SET schema_version = 1 WHERE singleton = 1"
            )
            session.run("CREATE TABLE taut_search_claims (job_ts BIGINT PRIMARY KEY)")
            session.run("CREATE TABLE taut_search_housekeeping (key TEXT PRIMARY KEY)")

        assert [hit.ts for hit in client.search("needle")] == [second.ts, first.ts]
        with client._meta_queue.sidecar() as session:
            after = list(
                session.run(
                    "SELECT current_generation, schema_version FROM taut_search_metadata",
                    fetch=True,
                )
            )
            obsolete = list(
                session.run(
                    "SELECT name FROM sqlite_master WHERE name LIKE 'taut_search_%' "
                    "AND type = 'table'",
                    fetch=True,
                )
            )
        assert after == [(before[0][0], 2)]
        assert ("taut_search_claims",) not in obsolete
        assert ("taut_search_housekeeping",) not in obsolete
        with open_broker(str(db_path)) as broker:
            totals = {item.queue: item.total for item in broker.list_queue_stats()}
        assert totals.get(CLAIMED_QUEUE_NAME, 0) == 0
        assert totals.get(FAILED_QUEUE_NAME, 0) == 0
    finally:
        failed.close()
        claimed.close()
        pending.close()
        client.close()


def test_interrupted_search_upgrade_repeats_without_losing_work(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / ".taut.db"
    TautClient.init(db_path=db_path)
    client = TautClient(db_path=db_path, as_name="alice")
    client.join("general")
    with pytest.raises(EmptyResultError, match="no search results"):
        client.search("seed")
    message = client.say("general", "upgrade retry needle")
    pending = Queue(PENDING_QUEUE_NAME, db_path=str(db_path))
    claimed = Queue(CLAIMED_QUEUE_NAME, db_path=str(db_path))
    try:
        row = pending.peek_many(1, with_timestamps=True)[0]
        assert (
            pending.move_one(claimed, exact_timestamp=row[1], with_timestamps=True)
            is not None
        )
        with client._meta_queue.sidecar(transaction=True) as session:
            session.run(
                "UPDATE taut_search_metadata SET schema_version = 1 WHERE singleton = 1"
            )
        original = SQLiteSearchProvider.ensure_schema
        failed = False

        def fail_once(provider: SQLiteSearchProvider) -> None:
            nonlocal failed
            if not failed:
                failed = True
                raise RuntimeError("upgrade interrupted")
            original(provider)

        monkeypatch.setattr(SQLiteSearchProvider, "ensure_schema", fail_once)
        with pytest.raises(RuntimeError, match="upgrade interrupted"):
            client.search("needle")
        assert claimed.peek_many(10) == []
        assert pending.peek_one(exact_timestamp=row[1]) is not None
        assert [hit.ts for hit in client.search("needle")] == [message.ts]
    finally:
        claimed.close()
        pending.close()
        client.close()


def test_search_replays_pending_work_after_commit_before_delete_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / ".taut.db"
    TautClient.init(db_path=db_path)
    client = TautClient(db_path=db_path, as_name="alice")
    client.join("general")
    with pytest.raises(EmptyResultError, match="no search results"):
        client.search("needle")
    message = client.say("general", "replayable search needle")
    real_delete = Queue.delete
    failed = False

    def fail_once(queue: Queue, *args: object, **kwargs: object) -> bool:
        nonlocal failed
        if queue.name == PENDING_QUEUE_NAME and not failed:
            failed = True
            raise RuntimeError("broker delete failed")
        return real_delete(queue, *args, **kwargs)

    monkeypatch.setattr(Queue, "delete", fail_once)
    with pytest.raises(RuntimeError, match="broker delete failed"):
        client.search("needle")
    provider = SQLiteSearchProvider(sidecar=client._meta_queue.sidecar)
    try:
        assert provider.applied_revision(message.ts) is not None
        assert client.queue(PENDING_QUEUE_NAME).peek_many(10)
        assert [hit.ts for hit in client.search("needle")] == [message.ts]
        assert client.queue(PENDING_QUEUE_NAME).peek_many(10) == []
    finally:
        provider.close()
        client.close()


def test_search_discards_malformed_job_and_continues_to_valid_work(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / ".taut.db"
    TautClient.init(db_path=db_path)
    client = TautClient(db_path=db_path, as_name="alice")
    client.join("general")
    pending = Queue(PENDING_QUEUE_NAME, db_path=str(db_path))
    try:
        pending.write("private malformed body")
        message = client.say("general", "healthy search needle")
        assert [hit.ts for hit in client.search("needle")] == [message.ts]
        assert client.last_search_warnings
        assert "invalid_json" in client.last_search_warnings[0]
        assert "private malformed body" not in client.last_search_warnings[0]
        assert pending.peek_many(10) == []
    finally:
        pending.close()
        client.close()


def test_search_closes_provider_when_schema_setup_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / ".taut.db"
    TautClient.init(db_path=db_path)
    client = TautClient(db_path=db_path, as_name="alice")

    class FailingProvider:
        closed = 0

        def schema_version(self) -> None:
            return None

        def ensure_schema(self) -> None:
            raise RuntimeError("schema failed")

        def close(self) -> None:
            self.closed += 1

    provider = FailingProvider()
    monkeypatch.setattr(
        SearchingMixin,
        "_search_provider",
        lambda _self, _meta: provider,
    )

    with pytest.raises(RuntimeError, match="schema failed"):
        client.search("needle")

    assert provider.closed == 1


def test_search_pages_provider_candidates_until_scope_limit_is_filled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / ".taut.db"
    TautClient.init(db_path=db_path)
    alice = TautClient(db_path=db_path, as_name="alice")
    alice.join("general")
    expected = alice.say("general", "shared needle")
    alice.join("other")
    alice.say("other", "newer shared needle")
    monkeypatch.setattr(searching, "_INDEX_QUERY_BATCH", 1)

    hits = alice.search("shared needle", channels=("general",), limit=1)

    assert [(hit.thread, hit.ts) for hit in hits] == [("general", expected.ts)]


def test_message_write_enqueues_content_free_search_invalidation(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / ".taut.db"
    TautClient.init(db_path=db_path)
    alice = TautClient(db_path=db_path, as_name="alice")
    alice.join("general")
    message = alice.say("general", "secret source text")
    pending = alice.queue(PENDING_QUEUE_NAME)
    try:
        rows = pending.peek_many(10, with_timestamps=True)
    finally:
        pending.close()

    bodies = [body for body, _job_ts in rows]
    matching = [decode_message_job(body) for body in bodies]
    assert any(
        job.message_ts == message.ts and job.thread == "general" for job in matching
    )
    assert all("secret source text" not in body for body in bodies)


def test_search_enqueue_failure_never_fails_committed_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """[SRCH-8.3] The source result wins over derived-work failure."""

    db_path = tmp_path / ".taut.db"
    TautClient.init(db_path=db_path)
    alice = TautClient(db_path=db_path, as_name="alice")
    alice.join("general")

    real_write = Queue.write

    def failing_write(queue: Queue, body: str) -> int:
        if queue.name == PENDING_QUEUE_NAME:
            raise RuntimeError("index queue offline")
        return real_write(queue, body)

    monkeypatch.setattr(Queue, "write", failing_write)

    message = alice.say("general", "source still commits")

    assert alice.queue("general").peek_one(exact_timestamp=message.ts) is not None
    assert alice.last_search_warnings == [
        (
            f"search invalidation enqueue failed for general/{message.ts}: "
            "index queue offline"
        )
    ]


def test_search_filters_author_scope_before_and_kind_after_hydration(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / ".taut.db"
    TautClient.init(db_path=db_path)
    alice = TautClient(db_path=db_path, as_name="alice")
    bob = TautClient(db_path=db_path, as_name="bob")
    alice.join("general")
    bob.join("general")
    older = alice.say("general", "shared parser")
    newer = bob.say("general", "shared parser")

    assert [hit.ts for hit in alice.search("shared", limit=2)] == [newer.ts, older.ts]
    assert [
        hit.ts
        for hit in alice.search(
            "shared",
            from_member="alice",
            kinds=("message",),
            before=str(newer.ts),
        )
    ] == [older.ts]


def test_search_dm_scope_is_current_participant_only(tmp_path: Path) -> None:
    db_path = tmp_path / ".taut.db"
    TautClient.init(db_path=db_path)
    alice = TautClient(db_path=db_path, as_name="alice")
    bob = TautClient(db_path=db_path, as_name="bob")
    charlie = TautClient(db_path=db_path, as_name="charlie")
    for client in (alice, bob, charlie):
        client.join("general")
    sent = alice.say("@bob", "private rendezvous needle")

    assert [(hit.thread, hit.ts) for hit in alice.search("rendezvous")] == [
        (sent.thread, sent.ts)
    ]
    with pytest.raises(EmptyResultError, match="no search results"):
        charlie.search("rendezvous")


def test_search_follows_message_identity_across_reused_channel_names(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / ".taut.db"
    TautClient.init(db_path=db_path)
    alice = TautClient(db_path=db_path, as_name="alice")
    alice.join("alpha")
    original = alice.say("alpha", "original rename needle")
    alice.rename_channel("alpha", "beta")
    alice.rename_channel("beta", "alpha")
    alice.rename_channel("alpha", "gamma")
    alice.join("aardvark")

    assert [(hit.thread, hit.ts) for hit in alice.search("original needle")] == [
        ("gamma", original.ts)
    ]

    alice.join("alpha")
    reused = alice.say("alpha", "reused channel needle")
    assert [(hit.thread, hit.ts) for hit in alice.search("reused needle")] == [
        ("alpha", reused.ts)
    ]


def test_search_reconciles_two_rename_jobs_committed_newest_first(
    tmp_path: Path,
) -> None:
    """[SRCH-9.3] B→C before A→B converges through the canonical C queue."""

    db_path = tmp_path / ".taut.db"
    TautClient.init(db_path=db_path)
    alice = TautClient(db_path=db_path, as_name="alice")
    alice.join("general")
    message = alice.say("general", "out of order rename needle")
    assert alice.search("rename needle")[0].ts == message.ts
    alice.rename_channel("general", "ops")
    alice.rename_channel("ops", "final")

    pending = alice.queue(PENDING_QUEUE_NAME)
    rename_rows: list[tuple[ThreadRenameJob, int]] = []
    for body, job_ts in pending.peek_many(100, with_timestamps=True):
        job = decode_search_job(body)
        if isinstance(job, ThreadRenameJob):
            rename_rows.append((job, job_ts))
            assert pending.delete(message_id=job_ts)
    assert [(job.old, job.new) for job, _job_ts in rename_rows] == [
        ("general", "ops"),
        ("ops", "final"),
    ]

    provider = SQLiteSearchProvider(sidecar=alice.queue(META_QUEUE_NAME).sidecar)
    try:
        provider.ensure_schema()
        for job, revision in reversed(rename_rows):
            provider.retarget_threads(job.affected, revision=revision)
        assert message.ts in provider.indexed_message_ids("ops")
        assert provider.indexed_message_ids("final") == ()
    finally:
        provider.close()

    assert [(hit.thread, hit.ts) for hit in alice.search("rename needle")] == [
        ("final", message.ts)
    ]


def test_deletion_heavy_drain_uses_one_registry_snapshot_and_one_refresh(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / ".taut.db"
    TautClient.init(db_path=db_path)
    alice = TautClient(db_path=db_path, as_name="alice")
    alice.join("general")
    messages = [alice.say("general", f"delete batch {i}") for i in range(30)]
    assert len(alice.search("delete batch", limit=30)) == 30
    for message in messages:
        alice.delete_message(str(message.ts))

    reads = 0
    original = alice._state.list_threads

    def counted(_self: object, *, include_internal: bool = False) -> list[ThreadRow]:
        nonlocal reads
        reads += 1
        return original(include_internal=include_internal)

    monkeypatch.setattr(type(alice._state), "list_threads", counted)
    with pytest.raises(EmptyResultError, match="no search results"):
        alice.search("delete batch")
    assert 2 <= reads <= 3  # scope, drain snapshot, at most one refresh


def test_search_incremental_reconciliation_repairs_missed_append_before_later_append(
    tmp_path: Path,
) -> None:
    """[SRCH-10.1] A later append does not hide an earlier enqueue gap."""

    db_path = tmp_path / ".taut.db"
    TautClient.init(db_path=db_path)
    alice = TautClient(db_path=db_path, as_name="alice")
    alice.join("general")
    initial = alice.say("general", "initial searchable marker")
    assert alice.search("initial")[0].ts == initial.ts

    queue = alice.queue("general")
    missed_ts = queue.write(
        encode_envelope(
            from_id=cast(str, initial.from_id),
            from_name="alice",
            kind="message",
            text="missed incremental needle",
        )
    )
    later = alice.say("general", "later append marker")

    assert later.ts > missed_ts
    assert [hit.ts for hit in alice.search("incremental needle")] == [missed_ts]


def test_rebuild_records_only_the_pre_scan_source_watermark(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """[SRCH-10.1]/[SRCH-10.3] A during-scan append stays above the watermark."""

    db_path = tmp_path / ".taut.db"
    TautClient.init(db_path=db_path)
    alice = TautClient(db_path=db_path, as_name="alice")
    alice.join("general")
    initial = alice.say("general", "initial rebuild marker")
    real_peek_generator = Queue.peek_generator
    injected: list[object] = []

    def inject_append(
        queue: Queue,
        *,
        with_timestamps: bool = False,
        after_timestamp: int | None = None,
        before_timestamp: int | None = None,
        exact_timestamp: int | str | None = None,
        include_claimed: bool = False,
    ) -> Iterator[str | tuple[str, int]]:
        if queue.name == "general" and not injected:
            injected.append(alice.say("general", "raced rebuild sentinel"))
        return real_peek_generator(
            queue,
            with_timestamps=with_timestamps,
            after_timestamp=after_timestamp,
            before_timestamp=before_timestamp,
            exact_timestamp=exact_timestamp,
            include_claimed=include_claimed,
        )

    monkeypatch.setattr(Queue, "peek_generator", inject_append)

    raced = alice.search("raced sentinel", reindex=True)[0]
    provider = SQLiteSearchProvider(sidecar=alice.queue(META_QUEUE_NAME).sidecar)
    try:
        provider.ensure_schema()
        assert provider.thread_watermark("general").message_ts == initial.ts
    finally:
        provider.close()

    assert alice.search("raced sentinel")[0].ts == raced.ts
    provider = SQLiteSearchProvider(sidecar=alice.queue(META_QUEUE_NAME).sidecar)
    try:
        provider.ensure_schema()
        assert provider.thread_watermark("general").message_ts == raced.ts
    finally:
        provider.close()


def test_search_rotation_removes_non_latest_foreign_delete(tmp_path: Path) -> None:
    """[SRCH-10.2] Full rotation removes stale derived non-latest rows."""

    db_path = tmp_path / ".taut.db"
    TautClient.init(db_path=db_path)
    alice = TautClient(db_path=db_path, as_name="alice")
    alice.join("general")
    target = alice.say("general", "deleted rotation needle")
    alice.say("general", "newer watermark holder")
    assert alice.search("rotation needle")[0].ts == target.ts
    assert alice.queue("general").delete(message_id=target.ts)

    with pytest.raises(EmptyResultError, match="no search results"):
        alice.search("rotation needle")

    provider = SQLiteSearchProvider(sidecar=alice.queue(META_QUEUE_NAME).sidecar)
    try:
        provider.ensure_schema()
        assert target.ts not in provider.indexed_message_ids("general")
    finally:
        provider.close()


def test_search_lower_watermark_repairs_deleted_latest_before_rotation(
    tmp_path: Path,
) -> None:
    """[SRCH-10.1] The former latest ID is exact-checked before rotation."""

    db_path = tmp_path / ".taut.db"
    TautClient.init(db_path=db_path)
    alice = TautClient(db_path=db_path, as_name="alice")
    alice.join("general")
    alice.join("zeta")
    target = alice.say("zeta", "latest deletion sentinel")
    assert alice.search("deletion sentinel")[0].ts == target.ts
    assert alice.queue("zeta").delete(message_id=target.ts)

    with pytest.raises(EmptyResultError, match="no search results"):
        alice.search("deletion sentinel")

    provider = SQLiteSearchProvider(sidecar=alice.queue(META_QUEUE_NAME).sidecar)
    try:
        provider.ensure_schema()
        assert target.ts not in provider.indexed_message_ids("zeta")
    finally:
        provider.close()


def test_stale_hydration_schedules_content_free_repair(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """[SRCH-4.2] A source race omits the hit and leaves repair work."""

    db_path = tmp_path / ".taut.db"
    TautClient.init(db_path=db_path)
    alice = TautClient(db_path=db_path, as_name="alice")
    alice.join("general")
    target = alice.say("general", "stale hydration needle")
    assert alice.search("hydration needle")[0].ts == target.ts
    assert alice.queue("general").delete(message_id=target.ts)
    monkeypatch.setattr(
        SearchingMixin,
        "_reconcile_search_index",
        lambda _self, _provider, _rows, *, meta: None,
    )

    with pytest.raises(EmptyResultError, match="no search results"):
        alice.search("hydration needle")

    pending = alice.queue(PENDING_QUEUE_NAME)
    jobs = [decode_message_job(body) for body in pending.peek_many(100)]
    assert any(job.message_ts == target.ts and job.thread == "general" for job in jobs)


def test_search_rotation_eventually_finds_exact_restore_below_watermark(
    tmp_path: Path,
) -> None:
    """[SRCH-10.2] One durable thread rotation per search converges."""

    db_path = tmp_path / ".taut.db"
    TautClient.init(db_path=db_path)
    alice = TautClient(db_path=db_path, as_name="alice")
    alice.join("general")
    alice.join("zeta")
    identity = alice.say("zeta", "identity marker")
    zeta = alice.queue("zeta")
    restored_ts = zeta.generate_timestamp()
    later = alice.say("zeta", "later watermark marker")
    assert alice.search("watermark marker")[0].ts == later.ts
    zeta.insert_messages(
        [
            (
                encode_envelope(
                    from_id=cast(str, identity.from_id),
                    from_name="alice",
                    kind="message",
                    text="restored rotation sentinel",
                ),
                restored_ts,
            )
        ]
    )

    with pytest.raises(EmptyResultError, match="no search results"):
        alice.search("restored sentinel")
    assert [hit.ts for hit in alice.search("restored sentinel")] == [restored_ts]
