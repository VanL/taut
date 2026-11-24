from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from threading import Event, Thread, get_ident
from typing import Any, cast

import pytest
from simplebroker import Queue
from simplebroker.ext import OperationalError, SidecarSession

from taut._constants import META_QUEUE_NAME
from taut.search import projection_segments, query_chunks
from taut.search._jobs import PENDING_QUEUE_NAME, JobQueues
from taut.search._provider import (
    IndexedDocument,
    SearchCandidate,
    SidecarAccessor,
    ThreadWatermark,
)
from taut.search._sqlite import (
    _FTS_TABLES,
    SQLiteSearchProvider,
    SQLiteSearchUnavailableError,
)
from taut.search._worker import process_one

pytestmark = pytest.mark.sqlite_only


def _document(
    *,
    message_ts: int,
    text: str,
    thread: str = "general",
    max_segment_bytes: int = 1024,
) -> IndexedDocument:
    encoded = text.encode("utf-8")
    return IndexedDocument(
        message_ts=message_ts,
        thread=thread,
        text_sha256=hashlib.sha256(encoded).hexdigest(),
        text_bytes=len(encoded),
        segments=projection_segments(text, max_segment_bytes=max_segment_bytes),
    )


def _join_started_thread(thread: Thread) -> None:
    if thread.ident is not None:
        thread.join(timeout=3.0)


def _candidate(document: IndexedDocument) -> SearchCandidate:
    return SearchCandidate(
        message_ts=document.message_ts,
        thread=document.thread,
        text_sha256=document.text_sha256,
        text_bytes=document.text_bytes,
    )


def test_projection_chunks_and_segments_are_canonical_and_utf8_safe() -> None:
    """[SRCH-3.1]/[SRCH-6.1] Projection packs canonical chunks in order."""

    assert query_chunks("Straße STRASSE src/search_index.py café CAFE\u0301") == (
        "strasse",
        "src",
        "search",
        "index",
        "py",
        "café",
        "cafe",
    )

    assert projection_segments(
        "Straße STRASSE src/search_index.py café CAFE\u0301",
        max_segment_bytes=12,
    ) == (
        "strasse src",
        "search index",
        "py café",
        "cafe",
    )


def test_sqlite_provider_round_trips_contentless_fts_through_sidecar(
    tmp_path: Path,
) -> None:
    """[SRCH-2.1]/[SRCH-7]/[SRCH-11.1] SQLite stores derived terms only."""

    queue = Queue(META_QUEUE_NAME, db_path=str(tmp_path / ".taut.db"))
    provider = SQLiteSearchProvider(sidecar=queue.sidecar)
    text = "Café parser rendezvous-7f3a"
    document = _document(
        message_ts=queue.generate_timestamp(),
        text=text,
    )
    try:
        provider.ensure_schema()
        provider.replace_document(document)

        assert provider.query(query_chunks("CAFE"), limit=10) == [_candidate(document)]
        with queue.sidecar() as session:
            assert list(
                session.run(
                    "SELECT projection FROM taut_search_fts",
                    fetch=True,
                )
            ) == [(None,)]
            stored = list(
                session.run(
                    """
                    SELECT message_ts, thread, text_sha256, text_bytes
                    FROM taut_search_documents
                    """,
                    fetch=True,
                )
            )
        assert stored == [
            (
                document.message_ts,
                document.thread,
                document.text_sha256,
                document.text_bytes,
            )
        ]
        assert text not in repr(stored)
    finally:
        provider.close()
        queue.close()


@pytest.mark.parametrize("text", ["Straße", "İstanbul"])
def test_sqlite_provider_uses_the_same_core_projection_for_source_and_query(
    tmp_path: Path,
    text: str,
) -> None:
    queue = Queue(META_QUEUE_NAME, db_path=str(tmp_path / ".taut.db"))
    provider = SQLiteSearchProvider(sidecar=queue.sidecar)
    document = _document(message_ts=queue.generate_timestamp(), text=text)
    try:
        provider.ensure_schema()
        provider.replace_document(document)

        assert provider.query(query_chunks(text), limit=10) == [_candidate(document)]
    finally:
        provider.close()
        queue.close()


def test_sqlite_provider_requires_chunks_across_physical_segments(
    tmp_path: Path,
) -> None:
    queue = Queue(META_QUEUE_NAME, db_path=str(tmp_path / ".taut.db"))
    provider = SQLiteSearchProvider(sidecar=queue.sidecar)
    both = _document(
        message_ts=queue.generate_timestamp(),
        text="alpha ---- beta",
        max_segment_bytes=9,
    )
    alpha_only = _document(
        message_ts=queue.generate_timestamp(),
        text="alpha only",
    )
    try:
        provider.ensure_schema()
        provider.replace_document(both)
        provider.replace_document(alpha_only)

        assert len(both.segments) > 1
        assert provider.query(query_chunks("alpha beta"), limit=10) == [
            _candidate(both)
        ]
    finally:
        provider.close()
        queue.close()


def test_sqlite_provider_binds_punctuation_as_chunks_not_match_syntax(
    tmp_path: Path,
) -> None:
    queue = Queue(META_QUEUE_NAME, db_path=str(tmp_path / ".taut.db"))
    provider = SQLiteSearchProvider(sidecar=queue.sidecar)
    complete = _document(
        message_ts=queue.generate_timestamp(),
        text="alpha quote or",
    )
    partial = _document(
        message_ts=queue.generate_timestamp(),
        text="alpha quote",
    )
    try:
        provider.ensure_schema()
        provider.replace_document(complete)
        provider.replace_document(partial)

        assert query_chunks('alpha "quote" OR *') == ("alpha", "quote", "or")
        assert provider.query(
            query_chunks('alpha "quote" OR *'),
            limit=10,
        ) == [_candidate(complete)]
    finally:
        provider.close()
        queue.close()


def test_sqlite_provider_orders_newest_first_before_applying_limit(
    tmp_path: Path,
) -> None:
    queue = Queue(META_QUEUE_NAME, db_path=str(tmp_path / ".taut.db"))
    provider = SQLiteSearchProvider(sidecar=queue.sidecar)
    documents = [
        _document(
            message_ts=queue.generate_timestamp(),
            thread=f"thread-{index}",
            text="shared result",
        )
        for index in range(3)
    ]
    try:
        provider.ensure_schema()
        for document in documents:
            provider.replace_document(document)

        assert provider.query(query_chunks("shared"), limit=2) == [
            _candidate(documents[2]),
            _candidate(documents[1]),
        ]
    finally:
        provider.close()
        queue.close()


def test_sqlite_provider_replacement_suppresses_old_live_mapping(
    tmp_path: Path,
) -> None:
    queue = Queue(META_QUEUE_NAME, db_path=str(tmp_path / ".taut.db"))
    provider = SQLiteSearchProvider(sidecar=queue.sidecar)
    message_ts = queue.generate_timestamp()
    old = _document(message_ts=message_ts, text="obsolete body")
    current = _document(message_ts=message_ts, text="current body")
    try:
        provider.ensure_schema()
        provider.replace_document(old)
        provider.replace_document(current)

        assert provider.query(query_chunks("obsolete"), limit=10) == []
        assert provider.query(query_chunks("current"), limit=10) == [
            _candidate(current)
        ]
    finally:
        provider.close()
        queue.close()


def test_sqlite_provider_revision_tombstone_prevents_old_worker_resurrection(
    tmp_path: Path,
) -> None:
    queue = Queue(META_QUEUE_NAME, db_path=str(tmp_path / ".taut.db"))
    provider = SQLiteSearchProvider(sidecar=queue.sidecar)
    message_ts = queue.generate_timestamp()
    document = _document(message_ts=message_ts, text="current body")
    try:
        provider.ensure_schema()

        assert provider.replace_document(document, revision=100)
        assert provider.delete_document(
            message_ts=message_ts,
            thread="general",
            revision=300,
        )
        assert not provider.replace_document(document, revision=200)
        assert provider.applied_revision(message_ts) == 300
        assert provider.query(query_chunks("current"), limit=10) == []

        assert provider.replace_document(document, revision=400)
        assert provider.applied_revision(message_ts) == 400
        assert provider.query(query_chunks("current"), limit=10) == [
            _candidate(document)
        ]
    finally:
        provider.close()
        queue.close()


def test_sqlite_unchanged_revision_advances_without_replacing_postings(
    tmp_path: Path,
) -> None:
    queue = Queue(META_QUEUE_NAME, db_path=str(tmp_path / ".taut.db"))
    provider = SQLiteSearchProvider(sidecar=queue.sidecar)
    document = _document(message_ts=queue.generate_timestamp(), text="stable words")
    try:
        provider.ensure_schema()
        assert provider.replace_document(document, revision=100)
        with queue.sidecar() as session:
            original = list(
                session.run(
                    "SELECT segment_rowid FROM taut_search_segments WHERE message_ts = ?",
                    (document.message_ts,),
                    fetch=True,
                )
            )
        assert provider.replace_document(document, revision=200)
        assert provider.applied_revision(document.message_ts) == 200
        with queue.sidecar() as session:
            current = list(
                session.run(
                    "SELECT segment_rowid FROM taut_search_segments WHERE message_ts = ?",
                    (document.message_ts,),
                    fetch=True,
                )
            )
        assert current == original
        assert provider.query(query_chunks("stable"), limit=10) == [
            _candidate(document)
        ]
    finally:
        provider.close()
        queue.close()


def test_sqlite_unchanged_document_keeps_current_and_staging_postings(
    tmp_path: Path,
) -> None:
    queue = Queue(META_QUEUE_NAME, db_path=str(tmp_path / ".taut.db"))
    provider = SQLiteSearchProvider(sidecar=queue.sidecar)
    document = _document(message_ts=queue.generate_timestamp(), text="stable words")
    try:
        provider.ensure_schema()
        assert provider.replace_document(document, revision=100)
        generation = provider.begin_rebuild(scan_revision=200)
        assert provider.replace_rebuild_document(
            document, generation=generation, revision=200
        )
        with queue.sidecar() as session:
            before = list(
                session.run(
                    "SELECT generation, segment_rowid FROM taut_search_segments "
                    "WHERE message_ts = ? ORDER BY generation",
                    (document.message_ts,),
                    fetch=True,
                )
            )
        assert len(before) == 2
        assert provider.replace_document(document, revision=300)
        with queue.sidecar() as session:
            after = list(
                session.run(
                    "SELECT generation, segment_rowid FROM taut_search_segments "
                    "WHERE message_ts = ? ORDER BY generation",
                    (document.message_ts,),
                    fetch=True,
                )
            )
        assert after == before
        assert provider.applied_revision(document.message_ts) == 300
    finally:
        provider.close()
        queue.close()


def test_sqlite_duplicate_pending_job_keeps_committed_postings(tmp_path: Path) -> None:
    meta = Queue(META_QUEUE_NAME, db_path=str(tmp_path / ".taut.db"))
    pending = Queue(PENDING_QUEUE_NAME, db_path=str(tmp_path / ".taut.db"))
    provider = SQLiteSearchProvider(sidecar=meta.sidecar)
    jobs = JobQueues(pending=pending)
    message_ts = meta.generate_timestamp()
    document = _document(message_ts=message_ts, text="stable replay")
    try:
        provider.ensure_schema()
        job_ts = jobs.enqueue_message(message_ts=message_ts, thread="general")
        row = pending.peek_one(exact_timestamp=job_ts, with_timestamps=True)
        assert row is not None

        def load(_job: object) -> IndexedDocument:
            return document

        assert process_one(jobs, provider, load, row=row)
        with meta.sidecar() as session:
            before = list(
                session.run(
                    "SELECT segment_rowid FROM taut_search_segments WHERE message_ts = ?",
                    (message_ts,),
                    fetch=True,
                )
            )
        assert process_one(jobs, provider, load, row=row)
        with meta.sidecar() as session:
            after = list(
                session.run(
                    "SELECT segment_rowid FROM taut_search_segments WHERE message_ts = ?",
                    (message_ts,),
                    fetch=True,
                )
            )
        assert after == before
        assert provider.query(query_chunks("replay"), limit=10) == [
            _candidate(document)
        ]
    finally:
        provider.close()
        pending.close()
        meta.close()


def test_sqlite_equal_revision_changed_content_replaces_postings(
    tmp_path: Path,
) -> None:
    queue = Queue(META_QUEUE_NAME, db_path=str(tmp_path / ".taut.db"))
    provider = SQLiteSearchProvider(sidecar=queue.sidecar)
    message_ts = queue.generate_timestamp()
    original = _document(message_ts=message_ts, text="original term")
    changed = _document(message_ts=message_ts, text="replacement term")
    try:
        provider.ensure_schema()
        assert provider.replace_document(original, revision=100)
        assert provider.replace_document(changed, revision=100)
        assert provider.query(query_chunks("original"), limit=10) == []
        assert provider.query(query_chunks("replacement"), limit=10) == [
            _candidate(changed)
        ]
    finally:
        provider.close()
        queue.close()


def test_sqlite_changed_thread_replaces_document_even_when_text_matches(
    tmp_path: Path,
) -> None:
    queue = Queue(META_QUEUE_NAME, db_path=str(tmp_path / ".taut.db"))
    provider = SQLiteSearchProvider(sidecar=queue.sidecar)
    message_ts = queue.generate_timestamp()
    original = _document(message_ts=message_ts, text="same text", thread="general")
    moved = _document(message_ts=message_ts, text="same text", thread="renamed")
    try:
        provider.ensure_schema()
        assert provider.replace_document(original, revision=100)
        assert provider.replace_document(moved, revision=200)
        assert provider.query(query_chunks("same"), limit=10) == [_candidate(moved)]
        assert provider.applied_revision(message_ts) == 200
    finally:
        provider.close()
        queue.close()


def test_sqlite_reconciliation_state_is_durable_and_revision_ordered(
    tmp_path: Path,
) -> None:
    """[SRCH-6.2]/[SRCH-10.1] Watermarks and indexed IDs share revision fences."""

    queue = Queue(META_QUEUE_NAME, db_path=str(tmp_path / ".taut.db"))
    provider = SQLiteSearchProvider(sidecar=queue.sidecar)
    first = _document(message_ts=queue.generate_timestamp(), text="first marker")
    second = _document(message_ts=queue.generate_timestamp(), text="second marker")
    try:
        provider.ensure_schema()
        assert provider.thread_watermark("general") == ThreadWatermark(
            known=False,
            message_ts=None,
        )
        assert provider.replace_document(first, revision=100)
        assert provider.replace_document(second, revision=100)
        assert provider.indexed_message_ids("general") == (
            first.message_ts,
            second.message_ts,
        )

        assert provider.record_reconciliation(
            "general",
            watermark=second.message_ts,
            revision=300,
        )
        assert not provider.record_reconciliation(
            "general",
            watermark=first.message_ts,
            revision=200,
        )
        assert provider.thread_watermark("general") == ThreadWatermark(
            known=True,
            message_ts=second.message_ts,
        )
    finally:
        provider.close()
        queue.close()


def test_sqlite_reconciliation_rotation_cursor_wraps_registered_threads(
    tmp_path: Path,
) -> None:
    """[SRCH-10.2] The durable cursor advances in canonical thread order."""

    queue = Queue(META_QUEUE_NAME, db_path=str(tmp_path / ".taut.db"))
    provider = SQLiteSearchProvider(sidecar=queue.sidecar)
    try:
        provider.ensure_schema()

        assert provider.next_reconciliation_thread(("zeta", "alpha")) == "alpha"
        assert provider.next_reconciliation_thread(("alpha", "zeta")) == "zeta"
        assert provider.next_reconciliation_thread(("zeta", "alpha")) == "alpha"
        assert provider.next_reconciliation_thread(()) is None
    finally:
        provider.close()
        queue.close()


def test_sqlite_reconciliation_scan_revision_cannot_resurrect_later_delete(
    tmp_path: Path,
) -> None:
    """[SRCH-10.1] A scan revision is older than a later source mutation."""

    queue = Queue(META_QUEUE_NAME, db_path=str(tmp_path / ".taut.db"))
    provider = SQLiteSearchProvider(sidecar=queue.sidecar)
    source = _document(
        message_ts=queue.generate_timestamp(),
        text="revision fenced marker",
    )
    try:
        provider.ensure_schema()
        assert provider.replace_document(source, revision=100)
        scan_revision = queue.generate_timestamp()
        later_revision = queue.generate_timestamp()

        assert later_revision > scan_revision
        assert provider.delete_document(
            message_ts=source.message_ts,
            thread=source.thread,
            revision=later_revision,
        )
        assert not provider.replace_document(source, revision=scan_revision)
        assert provider.query(query_chunks("fenced"), limit=10) == []
    finally:
        provider.close()
        queue.close()


def test_sqlite_thread_retarget_fences_delayed_message_work(tmp_path: Path) -> None:
    """[SRCH-8.3]/[SRCH-10.3] Rename revision owns the indexed thread."""

    queue = Queue(META_QUEUE_NAME, db_path=str(tmp_path / ".taut.db"))
    provider = SQLiteSearchProvider(sidecar=queue.sidecar)
    message_ts = queue.generate_timestamp()
    old = _document(message_ts=message_ts, thread="general", text="rename marker")
    renamed = _document(message_ts=message_ts, thread="renamed", text="rename marker")
    try:
        provider.ensure_schema()
        assert provider.replace_document(old, revision=100)

        provider.retarget_threads((("general", "renamed"),), revision=300)

        assert provider.query(query_chunks("marker"), limit=10) == [_candidate(renamed)]
        assert provider.applied_revision(message_ts) == 300
        assert not provider.replace_document(old, revision=200)
        assert not provider.delete_document(
            message_ts=message_ts,
            thread="general",
            revision=200,
        )
        assert provider.query(query_chunks("marker"), limit=10) == [_candidate(renamed)]
    finally:
        provider.close()
        queue.close()


def test_sqlite_thread_retarget_is_conditional_and_exact(tmp_path: Path) -> None:
    """[SRCH-8.3] Rename touches only exact mappings not newer documents."""

    queue = Queue(META_QUEUE_NAME, db_path=str(tmp_path / ".taut.db"))
    provider = SQLiteSearchProvider(sidecar=queue.sidecar)
    movable = _document(
        message_ts=queue.generate_timestamp(),
        thread="general.r_parent",
        text="movable marker",
    )
    newer = _document(
        message_ts=queue.generate_timestamp(),
        thread="general",
        text="newer marker",
    )
    unrelated = _document(
        message_ts=queue.generate_timestamp(),
        thread="general.r_parent.extra",
        text="unrelated marker",
    )
    try:
        provider.ensure_schema()
        assert provider.replace_document(movable, revision=100)
        assert provider.replace_document(newer, revision=400)
        assert provider.replace_document(unrelated, revision=100)

        provider.retarget_threads(
            (
                ("general", "renamed"),
                ("general.r_parent", "renamed.r_parent"),
            ),
            revision=300,
        )

        hits = provider.query(query_chunks("marker"), limit=10)
        by_ts = {hit.message_ts: hit for hit in hits}
        assert by_ts[movable.message_ts].thread == "renamed.r_parent"
        assert by_ts[newer.message_ts].thread == "general"
        assert by_ts[unrelated.message_ts].thread == "general.r_parent.extra"
        assert provider.applied_revision(movable.message_ts) == 300
        assert provider.applied_revision(newer.message_ts) == 400
        assert provider.applied_revision(unrelated.message_ts) == 100
    finally:
        provider.close()
        queue.close()


def test_sqlite_thread_retarget_dual_writes_active_staging(tmp_path: Path) -> None:
    """[SRCH-10.3] Rename retargets current and staging in one lifecycle."""

    queue = Queue(META_QUEUE_NAME, db_path=str(tmp_path / ".taut.db"))
    provider = SQLiteSearchProvider(sidecar=queue.sidecar)
    message_ts = queue.generate_timestamp()
    old = _document(
        message_ts=message_ts,
        thread="general.r_parent",
        text="staging rename",
    )
    renamed = _document(
        message_ts=message_ts,
        thread="renamed.r_parent",
        text="staging rename",
    )
    try:
        provider.ensure_schema()
        assert provider.replace_document(old, revision=100)
        generation = provider.begin_rebuild(scan_revision=200)
        assert provider.replace_rebuild_document(
            old,
            generation=generation,
            revision=200,
        )

        provider.retarget_threads(
            (("general.r_parent", "renamed.r_parent"),),
            revision=300,
        )
        assert not provider.replace_rebuild_document(
            old,
            generation=generation,
            revision=200,
        )
        provider.finish_rebuild(generation)

        assert provider.query(query_chunks("staging"), limit=10) == [
            _candidate(renamed)
        ]
        assert provider.applied_revision(message_ts) == 300
    finally:
        provider.close()
        queue.close()


def test_sqlite_rebuild_stays_invisible_until_generation_switch(
    tmp_path: Path,
) -> None:
    """[SRCH-10.3] Queries continue to use current while staging is built."""

    queue = Queue(META_QUEUE_NAME, db_path=str(tmp_path / ".taut.db"))
    provider = SQLiteSearchProvider(sidecar=queue.sidecar)
    message_ts = queue.generate_timestamp()
    current = _document(message_ts=message_ts, text="current marker")
    rebuilt = _document(message_ts=message_ts, text="rebuilt marker")
    try:
        provider.ensure_schema()
        assert provider.replace_document(current, revision=100)

        generation = provider.begin_rebuild(scan_revision=200)
        assert provider.replace_rebuild_document(
            rebuilt,
            generation=generation,
            revision=200,
        )

        assert provider.query(query_chunks("current"), limit=10) == [
            _candidate(current)
        ]
        assert provider.query(query_chunks("rebuilt"), limit=10) == []
    finally:
        provider.close()
        queue.close()


def test_sqlite_rebuild_switch_publishes_staging_and_cleans_old_slot(
    tmp_path: Path,
) -> None:
    """[SRCH-10.3]/[SRCH-11.1] Finish atomically publishes a clean slot."""

    queue = Queue(META_QUEUE_NAME, db_path=str(tmp_path / ".taut.db"))
    provider = SQLiteSearchProvider(sidecar=queue.sidecar)
    old = _document(message_ts=queue.generate_timestamp(), text="old marker")
    rebuilt = _document(message_ts=queue.generate_timestamp(), text="new marker")
    try:
        provider.ensure_schema()
        assert provider.replace_document(old, revision=100)
        generation = provider.begin_rebuild(scan_revision=200)
        assert provider.replace_rebuild_document(
            rebuilt,
            generation=generation,
            revision=200,
        )

        provider.finish_rebuild(generation)

        assert provider.query(query_chunks("old"), limit=10) == []
        assert provider.query(query_chunks("new"), limit=10) == [_candidate(rebuilt)]
        with queue.sidecar() as session:
            old_slot_rows = list(
                session.run("SELECT count(*) FROM taut_search_fts", fetch=True)
            )
        assert old_slot_rows == [(0,)]
    finally:
        provider.close()
        queue.close()


def test_sqlite_query_racing_generation_switch_never_observes_missing_table(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """[SRCH-3.2]/[SRCH-11.1] A switch permits omission, not missing DDL."""

    db_path = str(tmp_path / ".taut.db")
    query_queue = Queue(META_QUEUE_NAME, db_path=db_path)
    writer_queue = Queue(META_QUEUE_NAME, db_path=db_path)
    query_provider = SQLiteSearchProvider(sidecar=query_queue.sidecar)
    writer_provider = SQLiteSearchProvider(sidecar=writer_queue.sidecar)
    matching = _document(
        message_ts=query_queue.generate_timestamp(),
        text="alpha ---- beta",
        max_segment_bytes=9,
    )
    nonmatching = _document(
        message_ts=query_queue.generate_timestamp(),
        text="alpha only",
    )
    expected = [_candidate(matching)]
    metadata_read = Event()
    writer_completed = Event()
    release_query = Event()
    query_thread_id: int | None = None
    coordinated_state_calls = 0
    original_state = SQLiteSearchProvider._state
    query_results: list[list[SearchCandidate]] = []
    worker_errors: list[tuple[str, BaseException]] = []

    def observed_state(
        session: SidecarSession,
    ) -> tuple[int, int, tuple[int, int, int] | None]:
        nonlocal coordinated_state_calls
        state = original_state(session)
        if get_ident() == query_thread_id:
            coordinated_state_calls += 1
            metadata_read.set()
            assert release_query.wait(3.0), "query release handshake timed out"
        return state

    def run_query() -> None:
        nonlocal query_thread_id
        query_thread_id = get_ident()
        try:
            query_results.append(
                query_provider.query(query_chunks("alpha beta"), limit=10)
            )
        except (AssertionError, OperationalError, RuntimeError, ValueError) as error:
            worker_errors.append(("query", error))

    def finish_rebuild() -> None:
        try:
            writer_provider.finish_rebuild(generation)
        except (AssertionError, OperationalError, RuntimeError, ValueError) as error:
            worker_errors.append(("writer", error))
        finally:
            writer_completed.set()

    try:
        query_provider.ensure_schema()
        assert query_provider.replace_document(matching, revision=100)
        assert query_provider.replace_document(nonmatching, revision=100)
        assert query_provider.query(query_chunks("alpha beta"), limit=10) == expected

        generation = writer_provider.begin_rebuild(scan_revision=200)
        assert writer_provider.replace_rebuild_document(
            matching,
            generation=generation,
            revision=200,
        )
        assert writer_provider.replace_rebuild_document(
            nonmatching,
            generation=generation,
            revision=200,
        )
        monkeypatch.setattr(
            SQLiteSearchProvider,
            "_state",
            staticmethod(observed_state),
        )

        query_thread = Thread(target=run_query, daemon=True)
        writer_thread = Thread(target=finish_rebuild, daemon=True)
        query_thread.start()
        try:
            assert metadata_read.wait(3.0), "metadata-read handshake timed out"
            writer_thread.start()
            assert writer_completed.wait(3.0), "generation switch timed out"
        finally:
            release_query.set()
            query_thread.join(timeout=3.0)
            _join_started_thread(writer_thread)

        assert not query_thread.is_alive()
        assert not writer_thread.is_alive()
        assert worker_errors == []
        assert coordinated_state_calls == 1
        assert len(query_results) == 1
        assert query_results[0] in ([], expected)
    finally:
        release_query.set()
        writer_provider.close()
        query_provider.close()
        writer_queue.close()
        query_queue.close()


def test_sqlite_uncommitted_fts_drop_is_not_visible(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """[SRCH-11.1] Readers never observe the transactional DDL midpoint."""

    db_path = str(tmp_path / ".taut.db")
    reader_queue = Queue(META_QUEUE_NAME, db_path=db_path)
    writer_queue = Queue(META_QUEUE_NAME, db_path=db_path)
    reader_provider = SQLiteSearchProvider(sidecar=reader_queue.sidecar)
    writer_provider = SQLiteSearchProvider(sidecar=writer_queue.sidecar)
    document = _document(
        message_ts=reader_queue.generate_timestamp(),
        text="atomic visibility",
    )
    drop_completed = Event()
    fts_read_completed = Event()
    release_create = Event()
    writer_thread_id: int | None = None
    coordinated_drop_calls = 0
    original_run = SidecarSession.run
    read_results: list[list[tuple[Any, ...]]] = []
    worker_errors: list[tuple[str, BaseException]] = []

    def observed_run(
        session: SidecarSession,
        sql: str,
        params: tuple[Any, ...] = (),
        *,
        fetch: bool = False,
    ) -> Iterable[tuple[Any, ...]]:
        nonlocal coordinated_drop_calls
        normalized = " ".join(sql.split())
        result = original_run(session, sql, params, fetch=fetch)
        if (
            get_ident() == writer_thread_id
            and normalized == f"DROP TABLE IF EXISTS {old_table}"
        ):
            coordinated_drop_calls += 1
            drop_completed.set()
            assert release_create.wait(3.0), "FTS create release timed out"
        return result

    def finish_rebuild() -> None:
        nonlocal writer_thread_id
        writer_thread_id = get_ident()
        try:
            writer_provider.finish_rebuild(generation)
        except (AssertionError, OperationalError, RuntimeError, ValueError) as error:
            worker_errors.append(("writer", error))

    def read_old_slot() -> None:
        try:
            with reader_queue.sidecar() as session:
                read_results.append(
                    list(
                        session.run(
                            f"SELECT rowid FROM {old_table} "
                            f"WHERE {old_table} MATCH ? ORDER BY rowid",
                            ('"atomic"',),
                            fetch=True,
                        )
                    )
                )
            fts_read_completed.set()
        except (AssertionError, OperationalError, RuntimeError, ValueError) as error:
            worker_errors.append(("reader", error))

    try:
        reader_provider.ensure_schema()
        assert reader_provider.replace_document(document, revision=100)
        generation = writer_provider.begin_rebuild(scan_revision=200)
        assert writer_provider.replace_rebuild_document(
            document,
            generation=generation,
            revision=200,
        )
        with reader_queue.sidecar() as session:
            _generation, old_slot, _staging = SQLiteSearchProvider._state(session)
            old_table = _FTS_TABLES[old_slot]
            baseline_rows = list(
                session.run(
                    f"SELECT rowid FROM {old_table} "
                    f"WHERE {old_table} MATCH ? ORDER BY rowid",
                    ('"atomic"',),
                    fetch=True,
                )
            )
        assert baseline_rows
        monkeypatch.setattr(SidecarSession, "run", observed_run)

        writer_thread = Thread(target=finish_rebuild, daemon=True)
        reader_thread = Thread(target=read_old_slot, daemon=True)
        writer_thread.start()
        try:
            assert drop_completed.wait(3.0), "FTS drop handshake timed out"
            reader_thread.start()
            assert fts_read_completed.wait(3.0), "FTS read handshake timed out"
        finally:
            release_create.set()
            writer_thread.join(timeout=3.0)
            _join_started_thread(reader_thread)

        assert not writer_thread.is_alive()
        assert not reader_thread.is_alive()
        assert worker_errors == []
        assert coordinated_drop_calls == 1
        assert len(read_results) == 1
        assert read_results[0] == baseline_rows
    finally:
        release_create.set()
        writer_provider.close()
        reader_provider.close()
        writer_queue.close()
        reader_queue.close()


def test_sqlite_later_mutation_wins_over_older_rebuild_scan(
    tmp_path: Path,
) -> None:
    """[SRCH-10.3] Dual-write revisions fence stale rebuild scan rows."""

    queue = Queue(META_QUEUE_NAME, db_path=str(tmp_path / ".taut.db"))
    provider = SQLiteSearchProvider(sidecar=queue.sidecar)
    message_ts = queue.generate_timestamp()
    initial = _document(message_ts=message_ts, text="initial marker")
    stale_scan = _document(message_ts=message_ts, text="stale marker")
    later = _document(message_ts=message_ts, text="later marker")
    try:
        provider.ensure_schema()
        assert provider.replace_document(initial, revision=100)
        generation = provider.begin_rebuild(scan_revision=200)

        assert provider.replace_document(later, revision=300)
        assert not provider.replace_rebuild_document(
            stale_scan,
            generation=generation,
            revision=200,
        )
        provider.finish_rebuild(generation)

        assert provider.applied_revision(message_ts) == 300
        assert provider.query(query_chunks("stale"), limit=10) == []
        assert provider.query(query_chunks("later"), limit=10) == [_candidate(later)]
    finally:
        provider.close()
        queue.close()


def test_sqlite_later_delete_wins_over_older_rebuild_scan(tmp_path: Path) -> None:
    """[SRCH-10.3] Ordinary deletes dual-write into writable staging."""

    queue = Queue(META_QUEUE_NAME, db_path=str(tmp_path / ".taut.db"))
    provider = SQLiteSearchProvider(sidecar=queue.sidecar)
    message_ts = queue.generate_timestamp()
    source = _document(message_ts=message_ts, text="deleted marker")
    try:
        provider.ensure_schema()
        assert provider.replace_document(source, revision=100)
        generation = provider.begin_rebuild(scan_revision=200)

        assert provider.delete_document(
            message_ts=message_ts,
            thread="general",
            revision=300,
        )
        assert not provider.replace_rebuild_document(
            source,
            generation=generation,
            revision=200,
        )
        provider.finish_rebuild(generation)

        assert provider.applied_revision(message_ts) == 300
        assert provider.query(query_chunks("deleted"), limit=10) == []
    finally:
        provider.close()
        queue.close()


def test_sqlite_rebuild_staging_rejects_mutation_older_than_scan(
    tmp_path: Path,
) -> None:
    """[SRCH-10.3] Pre-scan work cannot contaminate the new generation."""

    queue = Queue(META_QUEUE_NAME, db_path=str(tmp_path / ".taut.db"))
    provider = SQLiteSearchProvider(sidecar=queue.sidecar)
    stale = _document(message_ts=queue.generate_timestamp(), text="stale ghost")
    try:
        provider.ensure_schema()
        generation = provider.begin_rebuild(scan_revision=200)

        assert provider.replace_document(stale, revision=150)
        provider.finish_rebuild(generation)

        assert provider.query(query_chunks("ghost"), limit=10) == []
    finally:
        provider.close()
        queue.close()


def test_sqlite_abort_rebuild_preserves_current_and_fences_stale_writer(
    tmp_path: Path,
) -> None:
    """[SRCH-10.3] Abort discards staging without risking current search."""

    queue = Queue(META_QUEUE_NAME, db_path=str(tmp_path / ".taut.db"))
    provider = SQLiteSearchProvider(sidecar=queue.sidecar)
    current = _document(message_ts=queue.generate_timestamp(), text="safe marker")
    staged = _document(message_ts=queue.generate_timestamp(), text="staged marker")
    try:
        provider.ensure_schema()
        assert provider.replace_document(current, revision=100)
        abandoned = provider.begin_rebuild(scan_revision=200)
        assert provider.replace_rebuild_document(
            staged,
            generation=abandoned,
            revision=200,
        )

        provider.abort_rebuild(abandoned)

        assert provider.query(query_chunks("safe"), limit=10) == [_candidate(current)]
        assert provider.query(query_chunks("staged"), limit=10) == []
        replacement = provider.begin_rebuild(scan_revision=300)
        assert replacement > abandoned
        assert not provider.replace_rebuild_document(
            staged,
            generation=abandoned,
            revision=200,
        )
    finally:
        provider.close()
        queue.close()


@pytest.mark.parametrize(
    ("column", "diagnostic"),
    [
        ("schema_version", "search schema version 3 is newer than supported version 2"),
        (
            "projection_version",
            "search projection version 2 is newer than supported version 1",
        ),
    ],
)
def test_sqlite_provider_rejects_newer_search_schema_or_projection(
    tmp_path: Path,
    column: str,
    diagnostic: str,
) -> None:
    """[SRCH-6.2] Newer durable formats fail with an upgrade diagnostic."""

    queue = Queue(META_QUEUE_NAME, db_path=str(tmp_path / ".taut.db"))
    provider = SQLiteSearchProvider(sidecar=queue.sidecar)
    try:
        provider.ensure_schema()
        with queue.sidecar(transaction=True) as session:
            session.run(
                f"UPDATE taut_search_metadata SET {column} = ? WHERE singleton = 1",
                (3 if column == "schema_version" else 2,),
            )

        with pytest.raises(RuntimeError, match=f"^{diagnostic}$"):
            provider.ensure_schema()
    finally:
        provider.close()
        queue.close()


class _RecordingSchemaSession:
    def __init__(
        self,
        delegate: SidecarSession,
        statements: list[str],
    ) -> None:
        self._delegate = delegate
        self._statements = statements

    def run(
        self,
        sql: str,
        params: tuple[Any, ...] = (),
        *,
        fetch: bool = False,
    ) -> Iterable[tuple[Any, ...]]:
        self._statements.append(" ".join(sql.split()))
        return self._delegate.run(sql, params, fetch=fetch)


def _record_schema_statements(
    sidecar: SidecarAccessor,
    statements: list[str],
) -> SidecarAccessor:
    @contextmanager
    def accessor(*, transaction: bool = False) -> Iterator[SidecarSession]:
        with sidecar(transaction=transaction) as session:
            yield cast(
                SidecarSession,
                _RecordingSchemaSession(session, statements),
            )

    return accessor


def test_sqlite_current_search_schema_skips_installation_ddl(tmp_path: Path) -> None:
    queue = Queue(META_QUEUE_NAME, db_path=str(tmp_path / ".taut.db"))
    statements: list[str] = []
    initial = SQLiteSearchProvider(sidecar=queue.sidecar)
    try:
        initial.ensure_schema()
        warm = SQLiteSearchProvider(
            sidecar=_record_schema_statements(queue.sidecar, statements)
        )
        warm.ensure_schema()
        assert all(
            not statement.upper().startswith(("CREATE ", "DROP ", "ALTER "))
            for statement in statements
        )
    finally:
        queue.close()


def _assert_version_read_precedes_schema_mutation(statements: list[str]) -> None:
    normalized = [statement.upper() for statement in statements]
    metadata_table = r'(?:"TAUT_SEARCH_METADATA"|TAUT_SEARCH_METADATA)'

    def reads_stable_versions(statement: str) -> bool:
        projection, separator, source = statement.partition(" FROM ")
        return (
            statement.startswith("SELECT ")
            and bool(separator)
            and re.search(r"\bSCHEMA_VERSION\b", projection) is not None
            and re.search(r"\bPROJECTION_VERSION\b", projection) is not None
            and re.match(rf"{metadata_table}(?=\s|$)", source) is not None
        )

    read_index = next(
        index
        for index, statement in enumerate(normalized)
        if reads_stable_versions(statement)
    )

    def is_schema_mutation(statement: str) -> bool:
        if statement.startswith(("INSERT ", "UPDATE ", "DELETE ")):
            return True
        if statement.startswith(("ALTER ", "DROP ")):
            return True
        return (
            statement.startswith("CREATE ")
            and re.match(
                rf"CREATE TABLE(?: IF NOT EXISTS)? {metadata_table}(?=\s|\()",
                statement,
            )
            is None
        )

    assert not any(
        is_schema_mutation(statement) for statement in normalized[:read_index]
    )
    assert not any(is_schema_mutation(statement) for statement in normalized)


@pytest.mark.parametrize(
    ("schema_version", "projection_version", "diagnostic_fragment"),
    [
        (3, 1, "search schema version 3"),
        (1, 2, "search projection version 2"),
    ],
)
def test_sqlite_provider_reads_source_shaped_versions_before_current_shape(
    tmp_path: Path,
    schema_version: int,
    projection_version: int,
    diagnostic_fragment: str,
) -> None:
    """[SRCH-6.2] Stored versions gate current-shape writes and provider DDL."""

    queue = Queue(META_QUEUE_NAME, db_path=str(tmp_path / ".taut.db"))
    statements: list[str] = []
    provider = SQLiteSearchProvider(
        sidecar=_record_schema_statements(queue.sidecar, statements)
    )
    try:
        with queue.sidecar(transaction=True) as session:
            session.run(
                """
                CREATE TABLE taut_search_metadata (
                    singleton          BIGINT PRIMARY KEY CHECK (singleton = 1),
                    schema_version     BIGINT NOT NULL,
                    projection_version BIGINT NOT NULL
                )
                """
            )
            session.run(
                """
                INSERT INTO taut_search_metadata (
                    singleton, schema_version, projection_version
                ) VALUES (1, ?, ?)
                """,
                (schema_version, projection_version),
            )
        with queue.sidecar() as session:
            columns_before = tuple(
                str(row[1])
                for row in session.run(
                    "PRAGMA table_info(taut_search_metadata)",
                    fetch=True,
                )
            )
            rows_before = list(
                session.run(
                    "SELECT * FROM taut_search_metadata WHERE singleton = 1",
                    fetch=True,
                )
            )

        with pytest.raises(RuntimeError) as raised:
            provider.ensure_schema()

        assert diagnostic_fragment in str(raised.value)
        _assert_version_read_precedes_schema_mutation(statements)
        with queue.sidecar() as session:
            columns_after = tuple(
                str(row[1])
                for row in session.run(
                    "PRAGMA table_info(taut_search_metadata)",
                    fetch=True,
                )
            )
            rows_after = list(
                session.run(
                    "SELECT * FROM taut_search_metadata WHERE singleton = 1",
                    fetch=True,
                )
            )
        assert columns_after == columns_before
        assert rows_after == rows_before
    finally:
        provider.close()
        queue.close()


def test_sqlite_provider_does_not_rewrite_missing_stable_version_field(
    tmp_path: Path,
) -> None:
    """[SRCH-6.2] An unreadable stable version field is not fresh state."""

    queue = Queue(META_QUEUE_NAME, db_path=str(tmp_path / ".taut.db"))
    statements: list[str] = []
    provider = SQLiteSearchProvider(
        sidecar=_record_schema_statements(queue.sidecar, statements)
    )
    try:
        with queue.sidecar(transaction=True) as session:
            session.run(
                """
                CREATE TABLE taut_search_metadata (
                    singleton             BIGINT PRIMARY KEY CHECK (singleton = 1),
                    schema_version        BIGINT NOT NULL,
                    current_generation    BIGINT NOT NULL,
                    current_slot          BIGINT NOT NULL CHECK (current_slot IN (0, 1)),
                    staging_generation    BIGINT,
                    staging_slot          BIGINT CHECK (staging_slot IN (0, 1)),
                    staging_scan_revision BIGINT,
                    next_generation       BIGINT NOT NULL,
                    initialized           BIGINT NOT NULL,
                    rotation_cursor       TEXT
                )
                """
            )
            session.run(
                """
                INSERT INTO taut_search_metadata (
                    singleton, schema_version, current_generation,
                    current_slot, next_generation, initialized
                ) VALUES (1, 1, 1, 0, 2, 0)
                """
            )
        with queue.sidecar() as session:
            columns_before = tuple(
                str(row[1])
                for row in session.run(
                    "PRAGMA table_info(taut_search_metadata)",
                    fetch=True,
                )
            )
            rows_before = list(
                session.run(
                    "SELECT * FROM taut_search_metadata",
                    fetch=True,
                )
            )

        with pytest.raises(OperationalError):
            provider.ensure_schema()

        _assert_version_read_precedes_schema_mutation(statements)
        with queue.sidecar() as session:
            columns_after = tuple(
                str(row[1])
                for row in session.run(
                    "PRAGMA table_info(taut_search_metadata)",
                    fetch=True,
                )
            )
            rows_after = list(
                session.run(
                    "SELECT * FROM taut_search_metadata",
                    fetch=True,
                )
            )
        assert columns_after == columns_before
        assert rows_after == rows_before
    finally:
        provider.close()
        queue.close()


def test_projection_segments_keep_large_distinct_set_and_oversized_chunk() -> None:
    tokens = [f"token{index:08x}" for index in range(80_000)]
    text = "/".join(tokens)

    segments = projection_segments(text, max_segment_bytes=4096)

    assert len(text.encode("utf-8")) > 1_000_000
    assert [chunk for segment in segments for chunk in segment.split()] == tokens
    assert all(len(segment.encode("utf-8")) <= 4096 for segment in segments)

    oversized = "東" * 32
    assert projection_segments(oversized, max_segment_bytes=16) == (oversized,)


def test_sqlite_search_schema_and_rows_store_no_raw_body(tmp_path: Path) -> None:
    queue = Queue(META_QUEUE_NAME, db_path=str(tmp_path / ".taut.db"))
    provider = SQLiteSearchProvider(sidecar=queue.sidecar)
    raw_sentinels = ("a7f3raw", "b9e1raw", "c2d4raw")
    raw_body = "a7f3raw café b9e1raw 東京 c2d4raw"
    document = _document(
        message_ts=queue.generate_timestamp(),
        text=raw_body,
        max_segment_bytes=16,
    )
    assert all(
        any(sentinel in segment for segment in document.segments)
        for sentinel in raw_sentinels
    )
    try:
        provider.ensure_schema()
        provider.replace_document(document)
        with queue.sidecar() as session:
            search_tables = list(
                session.run(
                    """
                    SELECT name, type
                    FROM pragma_table_list
                    WHERE name LIKE 'taut_search_%'
                    ORDER BY name
                    """,
                    fetch=True,
                )
            )
            ordinary_tables = {
                str(name) for name, table_type in search_tables if table_type == "table"
            }
            virtual_tables = {
                str(name)
                for name, table_type in search_tables
                if table_type == "virtual"
            }
            shadow_tables = {
                str(name)
                for name, table_type in search_tables
                if table_type == "shadow"
            }
            fts_tables = {
                "taut_search_fts",
                "taut_search_fts_staging",
            }
            fts_projections = {
                table_name: list(
                    session.run(
                        f"SELECT rowid, projection FROM {table_name}",
                        fetch=True,
                    )
                )
                for table_name in fts_tables
            }
            ordinary_values: list[object] = []
            for table_name in ordinary_tables:
                quoted_name = '"' + table_name.replace('"', '""') + '"'
                rows = session.run(
                    f"SELECT * FROM {quoted_name}",
                    fetch=True,
                )
                ordinary_values.extend(value for row in rows for value in row)

        assert {
            "taut_search_documents",
            "taut_search_metadata",
            "taut_search_segments",
            "taut_search_thread_state",
        }.issubset(ordinary_tables)
        assert virtual_tables
        assert fts_tables.issubset(virtual_tables)
        assert shadow_tables
        assert all(
            any(
                table_name.startswith(f"{virtual_name}_")
                for virtual_name in virtual_tables
            )
            for table_name in shadow_tables
        )
        assert any(fts_projections.values())
        assert all(
            projection is None
            for rows in fts_projections.values()
            for _rowid, projection in rows
        )
        for value in ordinary_values:
            if isinstance(value, str):
                assert all(sentinel not in value for sentinel in raw_sentinels)
            elif isinstance(value, (bytes, bytearray, memoryview)):
                stored = bytes(value)
                assert all(
                    sentinel.encode("utf-8") not in stored for sentinel in raw_sentinels
                )
    finally:
        provider.close()
        queue.close()


class _MissingFtsSession:
    def __init__(self, delegate: SidecarSession) -> None:
        self._delegate = delegate

    def run(
        self,
        sql: str,
        params: tuple[Any, ...] = (),
        *,
        fetch: bool = False,
    ) -> Iterator[tuple[Any, ...]]:
        if "CREATE VIRTUAL TABLE" in sql:
            raise OperationalError("no such module: fts5")
        return iter(self._delegate.run(sql, params, fetch=fetch))


def _without_fts(sidecar: SidecarAccessor) -> SidecarAccessor:
    @contextmanager
    def accessor(*, transaction: bool = False) -> Iterator[SidecarSession]:
        with sidecar(transaction=transaction) as session:
            yield cast(SidecarSession, _MissingFtsSession(session))

    return accessor


def test_sqlite_provider_reports_clear_fts5_unavailable_diagnostic(
    tmp_path: Path,
) -> None:
    queue = Queue(META_QUEUE_NAME, db_path=str(tmp_path / ".taut.db"))
    provider = SQLiteSearchProvider(sidecar=_without_fts(queue.sidecar))
    try:
        with pytest.raises(
            SQLiteSearchUnavailableError,
            match=r"^SQLite FTS5 search is unavailable in this Python runtime$",
        ):
            provider.ensure_schema()
    finally:
        provider.close()
        queue.close()


def test_sqlite_delete_tombstone_binds_search_projection_version(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import taut.search._provider as provider_mod
    import taut.search._sqlite as sqlite_mod

    db_path = str(tmp_path / ".taut.db")
    queue = Queue(META_QUEUE_NAME, db_path=db_path)
    pending = Queue(PENDING_QUEUE_NAME, db_path=db_path)
    jobs = JobQueues(pending=pending)
    provider = SQLiteSearchProvider(sidecar=queue.sidecar)
    try:
        provider.ensure_schema()
        monkeypatch.setattr(provider_mod, "SEARCH_PROJECTION_VERSION", 2)
        monkeypatch.setattr(sqlite_mod, "SEARCH_PROJECTION_VERSION", 2)
        with queue.sidecar(transaction=True) as session:
            session.run(
                "UPDATE taut_search_metadata SET projection_version = 2 WHERE singleton = 1"
            )

        drained_ts = queue.generate_timestamp()
        assert provider.replace_document(
            _document(message_ts=drained_ts, text="before delete"),
            revision=100,
        )
        job_ts = jobs.enqueue_message(message_ts=drained_ts, thread="general")
        row = pending.peek_one(exact_timestamp=job_ts, with_timestamps=True)
        assert row is not None
        assert process_one(jobs, provider, lambda _job: None, row=row)

        direct_ts = queue.generate_timestamp()
        assert provider.delete_document(
            message_ts=direct_ts,
            thread="general",
            revision=500,
        )

        with queue.sidecar() as session:
            rows = list(
                session.run(
                    """
                    SELECT message_ts, projection_version, indexed
                    FROM taut_search_documents
                    WHERE message_ts IN (?, ?)
                    ORDER BY message_ts
                    """,
                    (drained_ts, direct_ts),
                    fetch=True,
                )
            )
        assert [(int(ts), int(proj), int(idx)) for ts, proj, idx in rows] == [
            (drained_ts, 2, 0),
            (direct_ts, 2, 0),
        ]
    finally:
        provider.close()
        pending.close()
        queue.close()


def test_sqlite_thread_index_ddl_fresh_upgrade_and_schema2_steady_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from taut.client import TautClient

    monkeypatch.chdir(tmp_path)
    TautClient.init()
    client = TautClient(as_name="alice")
    client.join("general")
    msg = client.say("general", "indexed needle")
    queue = client.queue(META_QUEUE_NAME)
    provider = SQLiteSearchProvider(sidecar=queue.sidecar)
    try:
        provider.ensure_schema()
        with queue.sidecar() as session:
            indexes = {
                str(row[0])
                for row in session.run(
                    "SELECT name FROM sqlite_master WHERE type = 'index'",
                    fetch=True,
                )
            }
            plan_rows = list(
                session.run(
                    """
                    EXPLAIN QUERY PLAN
                    SELECT message_ts
                    FROM taut_search_documents
                    WHERE generation = 1 AND thread = 'general' AND indexed = 1
                    ORDER BY message_ts
                    """,
                    fetch=True,
                )
            )
        assert "taut_search_documents_thread_idx" in indexes
        assert any(
            "taut_search_documents_thread_idx" in " ".join(map(str, row))
            for row in plan_rows
        )

        # Schema-1 upgrade creates taut_search_documents_thread_idx.
        with queue.sidecar(transaction=True) as session:
            session.run("DROP INDEX taut_search_documents_thread_idx")
            session.run(
                "UPDATE taut_search_metadata SET schema_version = 1 WHERE singleton = 1"
            )
        provider.ensure_schema()
        with queue.sidecar() as session:
            upgraded_indexes = {
                str(row[0])
                for row in session.run(
                    "SELECT name FROM sqlite_master WHERE type = 'index'",
                    fetch=True,
                )
            }
        assert "taut_search_documents_thread_idx" in upgraded_indexes

        # Pre-fix schema-2 database without the index runs zero DDL on search.
        with queue.sidecar(transaction=True) as session:
            session.run("DROP INDEX taut_search_documents_thread_idx")
        statements: list[str] = []

        def recording_provider(meta: Queue) -> Any:
            return SQLiteSearchProvider(
                sidecar=_record_schema_statements(meta.sidecar, statements)
            )

        monkeypatch.setattr(client, "_search_provider", recording_provider)
        hits = client.search("needle", channels=("general",))
        assert [hit.ts for hit in hits] == [msg.ts]
        assert not any(stmt.upper().startswith("CREATE INDEX") for stmt in statements)
        with queue.sidecar() as session:
            after_indexes = {
                str(row[0])
                for row in session.run(
                    "SELECT name FROM sqlite_master WHERE type = 'index'",
                    fetch=True,
                )
            }
        assert "taut_search_documents_thread_idx" not in after_indexes
    finally:
        provider.close()
        queue.close()
        client.close()


@dataclass
class _ReconcileInstrumentation:
    open_generators: int = 0
    active_write_tx: int = 0
    yielded_counts: list[int] = field(default_factory=list)
    batches: list[tuple[int, int, int]] = field(default_factory=list)


def _wrap_peek_generator(
    orig_peek_generator: Any,
    inst: _ReconcileInstrumentation,
) -> Any:
    def spy_peek_generator(self: Queue, *args: Any, **kwargs: Any) -> Any:
        raw_gen = orig_peek_generator(self, *args, **kwargs)
        if self.name != "general":
            return raw_gen
        inst.open_generators += 1

        def wrapped() -> Iterator[Any]:
            count = 0
            try:
                for item in raw_gen:
                    count += 1
                    yield item
            finally:
                close = getattr(raw_gen, "close", None)
                if close is not None:
                    close()
                inst.yielded_counts.append(count)
                inst.open_generators -= 1

        return wrapped()

    return spy_peek_generator


def _install_reconcile_spies(
    monkeypatch: pytest.MonkeyPatch,
    client: Any,
) -> _ReconcileInstrumentation:
    import taut.client._searching as searching_mod

    inst = _ReconcileInstrumentation()
    orig_projection = searching_mod.projection_segments
    orig_batch = SQLiteSearchProvider.reconcile_unchanged_batch

    def spy_projection(text: str, *, max_segment_bytes: int) -> tuple[str, ...]:
        assert inst.open_generators == 0, "peek_generator still open during projection"
        assert inst.active_write_tx == 0, "projection_segments ran inside write tx"
        return orig_projection(text, max_segment_bytes=max_segment_bytes)

    def spy_batch(
        self: SQLiteSearchProvider,
        checks: Any,
        *,
        revision: int,
    ) -> frozenset[int]:
        assert inst.open_generators == 0, (
            "peek_generator still open during reconcile_unchanged_batch"
        )
        check_list = list(checks)
        total_bytes = sum(c.text_bytes for c in check_list)
        max_item = max((c.text_bytes for c in check_list), default=0)
        inst.batches.append((len(check_list), total_bytes, max_item))
        return orig_batch(self, check_list, revision=revision)

    def spy_search_provider(meta: Queue) -> SQLiteSearchProvider:
        base_sidecar = meta.sidecar

        @contextmanager
        def tracked_sidecar(*, transaction: bool = False) -> Iterator[SidecarSession]:
            if transaction:
                inst.active_write_tx += 1
            try:
                with base_sidecar(transaction=transaction) as session:
                    yield session
            finally:
                if transaction:
                    inst.active_write_tx -= 1

        return SQLiteSearchProvider(sidecar=tracked_sidecar)

    monkeypatch.setattr(
        Queue,
        "peek_generator",
        _wrap_peek_generator(Queue.peek_generator, inst),
    )
    monkeypatch.setattr(searching_mod, "projection_segments", spy_projection)
    monkeypatch.setattr(SQLiteSearchProvider, "reconcile_unchanged_batch", spy_batch)
    monkeypatch.setattr(client, "_search_provider", spy_search_provider)
    return inst


def test_sqlite_reconcile_per_100_generator_close_and_byte_cap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from taut.client import TautClient

    monkeypatch.chdir(tmp_path)
    TautClient.init()
    client = TautClient(as_name="alice")
    try:
        client.join("general")
        assert client.search("created", channels=("general",))

        small_payload = "needle " + ("s" * 93)
        for _ in range(110):
            client.say("general", small_payload)
        medium_payload = "needle " + ("m" * (900 * 1024 - 7))
        for _ in range(3):
            client.say("general", medium_payload)
        singleton_bytes = int(2.5 * 1024 * 1024)
        singleton_payload = "needle singleton " + ("L" * (singleton_bytes - 17))
        singleton_msg = client.say("general", singleton_payload)

        pending = client.queue(PENDING_QUEUE_NAME)
        try:
            while pending.read_one() is not None:
                pass
        finally:
            pending.close()

        inst = _install_reconcile_spies(monkeypatch, client)
        hits = client.search("singleton", channels=("general",))
        assert [hit.ts for hit in hits] == [singleton_msg.ts]
        assert inst.open_generators == 0
        assert inst.yielded_counts and all(c <= 100 for c in inst.yielded_counts)
        assert inst.batches, "expected reconcile_unchanged_batch calls"
        assert any(row_count == 100 for row_count, _, _ in inst.batches)
        for row_count, total_bytes, max_item in inst.batches:
            assert 1 <= row_count <= 100
            assert total_bytes <= max(2 * 1024 * 1024, max_item)
        assert any(
            row_count == 1 and max_item >= singleton_bytes
            for row_count, _total_bytes, max_item in inst.batches
        )
    finally:
        client.close()


def test_sqlite_reconcile_quiescent_fast_path_and_cross_generation_fences(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import taut.client._searching as searching_mod
    from taut.client import TautClient
    from taut.search import _provider as provider_mod

    monkeypatch.chdir(tmp_path)
    TautClient.init()
    client = TautClient(as_name="alice")
    try:
        client.join("general")
        seeded_ids: list[int] = []
        last_msg = None
        for idx in range(300):
            last_msg = client.say("general", f"quiescent item {idx:03d} needle")
            seeded_ids.append(last_msg.ts)
        assert last_msg is not None
        assert client.search("item 299", channels=("general",))

        projection_calls = 0
        write_tx_count = 0
        orig_projection = searching_mod.projection_segments

        def count_projection(text: str, *, max_segment_bytes: int) -> tuple[str, ...]:
            nonlocal projection_calls
            projection_calls += 1
            return orig_projection(text, max_segment_bytes=max_segment_bytes)

        monkeypatch.setattr(searching_mod, "projection_segments", count_projection)

        def tracked_provider(meta: Queue) -> Any:
            base_sidecar = meta.sidecar

            @contextmanager
            def sidecar(*, transaction: bool = False) -> Iterator[SidecarSession]:
                nonlocal write_tx_count
                if transaction:
                    write_tx_count += 1
                with base_sidecar(transaction=transaction) as session:
                    yield session

            return SQLiteSearchProvider(sidecar=sidecar)

        monkeypatch.setattr(client, "_search_provider", tracked_provider)
        before_rev_queue = client.queue(META_QUEUE_NAME)
        try:
            before_rev = SQLiteSearchProvider(
                sidecar=before_rev_queue.sidecar
            ).applied_revision(last_msg.ts)
        finally:
            before_rev_queue.close()
        assert before_rev is not None

        allocated_revisions: list[int] = []
        orig_gen_ts = Queue.generate_timestamp

        def spy_gen_ts(self: Queue) -> int:
            ts = orig_gen_ts(self)
            if self.name == META_QUEUE_NAME:
                allocated_revisions.append(ts)
            return ts

        with monkeypatch.context() as rev_patch:
            rev_patch.setattr(Queue, "generate_timestamp", spy_gen_ts)
            hits = client.search("item 299", channels=("general",))
        assert [hit.ts for hit in hits] == [last_msg.ts]
        assert projection_calls == 0
        assert write_tx_count <= 6
        assert len(allocated_revisions) == 1
        scan_rev = allocated_revisions[0]
        assert scan_rev > before_rev

        check_cls = provider_mod.DocumentCheck
        queue = client.queue(META_QUEUE_NAME)
        provider = SQLiteSearchProvider(sidecar=queue.sidecar)
        try:
            with queue.sidecar() as session:
                current_gen, _slot, _stg = SQLiteSearchProvider._state(session)
                placeholders = ", ".join("?" for _ in seeded_ids)
                rev_rows = list(
                    session.run(
                        f"""
                        SELECT message_ts, latest_revision
                        FROM taut_search_documents
                        WHERE generation = ? AND message_ts IN ({placeholders})
                        """,
                        (current_gen, *seeded_ids),
                        fetch=True,
                    )
                )
            rev_by_ts = {int(ts): int(rev) for ts, rev in rev_rows}
            assert set(rev_by_ts) == set(seeded_ids)
            assert set(rev_by_ts.values()) == {scan_rev}

            # Newer tombstone (latest_revision > scan_revision) is preserved.
            tomb_doc = _document(
                message_ts=queue.generate_timestamp(),
                text="tombstoned marker",
            )
            tomb_check = check_cls(
                message_ts=tomb_doc.message_ts,
                thread=tomb_doc.thread,
                text_sha256=tomb_doc.text_sha256,
                text_bytes=tomb_doc.text_bytes,
            )
            assert provider.delete_document(
                message_ts=tomb_doc.message_ts,
                thread="general",
                revision=500,
            )
            assert (
                provider.reconcile_unchanged_batch([tomb_check], revision=400)
                == frozenset()
            )
            assert provider.applied_revision(tomb_doc.message_ts) == 500
            assert provider.query(query_chunks("tombstoned"), limit=10) == []

            # Matching current + matching active staging advances both without projection.
            both_doc = _document(
                message_ts=queue.generate_timestamp(),
                text="both generations match",
            )
            both_check = check_cls(
                message_ts=both_doc.message_ts,
                thread=both_doc.thread,
                text_sha256=both_doc.text_sha256,
                text_bytes=both_doc.text_bytes,
            )
            assert provider.replace_document(both_doc, revision=100)
            gen_ok = provider.begin_rebuild(scan_revision=200)
            assert provider.replace_rebuild_document(
                both_doc, generation=gen_ok, revision=200
            )
            assert (
                provider.reconcile_unchanged_batch([both_check], revision=300)
                == frozenset()
            )
            with queue.sidecar() as session:
                revs = [
                    int(r[0])
                    for r in session.run(
                        "SELECT latest_revision FROM taut_search_documents WHERE message_ts = ? ORDER BY generation",
                        (both_doc.message_ts,),
                        fetch=True,
                    )
                ]
            assert revs == [300, 300]
            provider.abort_rebuild(gen_ok)

            # R2-02: Mixed current match + missing active staging must NOT bump current prematurely.
            mixed_doc = _document(
                message_ts=queue.generate_timestamp(),
                text="mixed staging repair marker",
            )
            mixed_check = check_cls(
                message_ts=mixed_doc.message_ts,
                thread=mixed_doc.thread,
                text_sha256=mixed_doc.text_sha256,
                text_bytes=mixed_doc.text_bytes,
            )
            assert provider.replace_document(mixed_doc, revision=100)
            gen_mixed = provider.begin_rebuild(scan_revision=200)
            needs = provider.reconcile_unchanged_batch([mixed_check], revision=300)
            assert needs == frozenset({mixed_doc.message_ts})
            assert provider.applied_revision(mixed_doc.message_ts) == 100
            assert provider.replace_document(mixed_doc, revision=300)
            assert not provider.delete_document(
                message_ts=mixed_doc.message_ts,
                thread="general",
                revision=250,
            )
            provider.finish_rebuild(gen_mixed)
            assert provider.applied_revision(mixed_doc.message_ts) == 300
            assert provider.query(query_chunks("mixed"), limit=10) == [
                _candidate(mixed_doc)
            ]
        finally:
            provider.close()
            queue.close()
    finally:
        client.close()


def test_sqlite_query_pushes_down_before_and_threads_and_intersects_chunks(
    tmp_path: Path,
) -> None:
    queue = Queue(META_QUEUE_NAME, db_path=str(tmp_path / ".taut.db"))
    calls: list[tuple[str, tuple[Any, ...]]] = []

    @contextmanager
    def recording_sidecar(*, transaction: bool = False) -> Iterator[SidecarSession]:
        with queue.sidecar(transaction=transaction) as session:

            def run(
                sql: str,
                params: tuple[Any, ...] = (),
                *,
                fetch: bool = False,
            ) -> Iterable[tuple[Any, ...]]:
                calls.append((" ".join(sql.split()), params))
                return session.run(sql, params, fetch=fetch)

            yield SidecarSession(run)

    provider = SQLiteSearchProvider(sidecar=recording_sidecar)
    try:
        provider.ensure_schema()
        doc_match = _document(message_ts=100, text="alpha beta", thread="general")
        doc_other_thread = _document(message_ts=200, text="alpha beta", thread="random")
        doc_after_cutoff = _document(message_ts=300, text="alpha beta", thread="ops")
        doc_partial_newer = _document(message_ts=250, text="alpha only", thread="ops")
        for doc in (doc_match, doc_other_thread, doc_after_cutoff, doc_partial_newer):
            assert provider.replace_document(doc, revision=doc.message_ts)

        calls.clear()
        assert provider.query(("alpha",), threads=(), limit=5) == []
        assert calls == []

        result = provider.query(
            ("alpha", "beta"),
            before=280,
            threads=("general", "ops"),
            limit=1,
        )
        assert result == [_candidate(doc_match)]
        fts_queries = [(sql, params) for sql, params in calls if "MATCH ?" in sql]
        assert len(fts_queries) == 2
        for sql, params in fts_queries:
            assert "d.message_ts < ?" in sql
            assert "d.thread IN (?, ?)" in sql
            assert 280 in params
            assert "general" in params and "ops" in params
    finally:
        provider.close()
        queue.close()
