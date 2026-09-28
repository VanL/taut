"""Real PostgreSQL firing tests for the physical search provider."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import psycopg
import pytest
from simplebroker import Queue
from simplebroker.ext import OperationalError, SidecarSession

from taut._constants import META_QUEUE_NAME
from taut._exceptions import EmptyResultError
from taut.client import TautClient
from taut.search._jobs import CLAIMED_QUEUE_NAME, PENDING_QUEUE_NAME
from taut.search._provider import (
    IndexedDocument,
    SearchCandidate,
    SidecarAccessor,
    ThreadWatermark,
)

pytestmark = pytest.mark.pg_only


def _search_metadata_snapshot(
    connection: psycopg.Connection[Any],
    *,
    schema: str,
) -> tuple[list[tuple[Any, ...]], list[tuple[Any, ...]]]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT column_name, data_type, is_nullable
            FROM information_schema.columns
            WHERE table_schema = %s
              AND table_name = 'taut_search_metadata'
            ORDER BY column_name
            """,
            (schema,),
        )
        columns = cursor.fetchall()
        cursor.execute(
            f"""
            SELECT pg_catalog.to_jsonb(metadata)
            FROM {schema}.taut_search_metadata AS metadata
            ORDER BY singleton
            """
        )
        return columns, cursor.fetchall()


def _recording_sidecar(
    queue: Queue,
    calls: list[tuple[str, tuple[object, ...]]],
) -> SidecarAccessor:
    @contextmanager
    def sidecar(*, transaction: bool = False) -> Iterator[SidecarSession]:
        with queue.sidecar(transaction=transaction) as session:

            def run(
                sql: str,
                params: tuple[Any, ...] = (),
                *,
                fetch: bool = False,
            ) -> Iterable[tuple[Any, ...]]:
                calls.append((sql, params))
                return session.run(sql, params, fetch=fetch)

            yield SidecarSession(run)

    return sidecar


def _assert_version_read_without_shape_work(
    calls: list[tuple[str, tuple[object, ...]]],
) -> None:
    normalized = [" ".join(sql.split()).upper() for sql, _ in calls]
    assert any(
        statement.startswith(
            "SELECT SCHEMA_VERSION, PROJECTION_VERSION FROM TAUT_SEARCH_METADATA"
        )
        for statement in normalized
    )
    assert all(
        "PG_ADVISORY_XACT_LOCK" not in statement
        and not statement.startswith(
            ("CREATE ", "ALTER ", "DROP ", "INSERT ", "UPDATE ", "DELETE ")
        )
        for statement in normalized
    )
    assert all(
        object_name not in statement
        for statement in normalized
        for object_name in (
            "TAUT_SEARCH_DOCUMENTS",
            "TAUT_SEARCH_SEGMENTS",
            "TAUT_SEARCH_THREAD_STATE",
        )
    )


def test_postgres_current_search_schema_skips_installation_ddl(
    taut_pg_project: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from taut_pg._search import create_provider

    monkeypatch.chdir(taut_pg_project)
    TautClient.init()
    client = TautClient(as_name="author")
    queue = client.queue(META_QUEUE_NAME)
    calls: list[tuple[str, tuple[object, ...]]] = []
    try:
        initial = create_provider(sidecar=queue.sidecar)
        initial.ensure_schema()
        warm = create_provider(sidecar=_recording_sidecar(queue, calls))
        warm.ensure_schema()
        assert all(
            not sql.lstrip().upper().startswith(("CREATE ", "DROP ", "ALTER "))
            for sql, _params in calls
        )
        assert all("PG_ADVISORY_XACT_LOCK" not in sql.upper() for sql, _ in calls)
    finally:
        queue.close()
        client.close()


def test_postgres_public_search_pins_unicode_diacritic_and_lexeme_limit(
    taut_pg_project: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """[SRCH-12.2] Backend-native edge results are explicit and non-poisoning."""

    monkeypatch.chdir(taut_pg_project)
    TautClient.init()
    author = TautClient(as_name="author")
    reader = TautClient(as_name="reader")
    author.join("general")
    reader.join("general")
    unicode_message = author.say("general", "café naïve 東京")
    oversized = "x" * 3_000
    oversized_message = author.say("general", f"stable {oversized} tail")

    try:
        assert [
            (hit.ts, hit.text)
            for hit in reader.search(
                "café",
                channels=("general",),
                reindex=True,
            )
        ] == [(unicode_message.ts, "café naïve 東京")]
        with pytest.raises(EmptyResultError, match="no search results"):
            reader.search("cafe", channels=("general",))
        assert [hit.ts for hit in reader.search("東京", channels=("general",))] == [
            unicode_message.ts
        ]
        with pytest.raises(EmptyResultError, match="no search results"):
            reader.search(oversized, channels=("general",))
        assert [hit.ts for hit in reader.search("stable", channels=("general",))] == [
            oversized_message.ts
        ]
    finally:
        reader.close()
        author.close()


def test_postgres_unchanged_document_advances_without_replacing_postings(
    taut_pg_project: Path,
    raw_pg_conn: psycopg.Connection[Any],
    pg_schema: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from taut_pg._search import create_provider

    monkeypatch.chdir(taut_pg_project)
    TautClient.init()
    client = TautClient(as_name="author")
    queue = client.queue(META_QUEUE_NAME)
    provider = create_provider(sidecar=queue.sidecar)
    document = IndexedDocument(
        message_ts=queue.generate_timestamp(),
        thread="general",
        text_sha256="stable",
        text_bytes=12,
        segments=("stable words",),
    )
    try:
        provider.ensure_schema()
        assert provider.replace_document(document, revision=100)
        generation = provider.begin_rebuild(scan_revision=200)
        assert provider.replace_rebuild_document(
            document, generation=generation, revision=200
        )
        with raw_pg_conn.cursor() as cursor:
            cursor.execute(
                f"SELECT generation, xmin::text FROM {pg_schema}.taut_search_segments "
                "WHERE message_ts = %s ORDER BY generation",
                (document.message_ts,),
            )
            before = cursor.fetchall()
        assert len(before) == 2
        assert provider.replace_document(document, revision=300)
        with raw_pg_conn.cursor() as cursor:
            cursor.execute(
                f"SELECT generation, xmin::text FROM {pg_schema}.taut_search_segments "
                "WHERE message_ts = %s ORDER BY generation",
                (document.message_ts,),
            )
            after = cursor.fetchall()
        assert after == before
        assert provider.applied_revision(document.message_ts) == 300
    finally:
        provider.close()
        queue.close()
        client.close()


def test_postgres_search_upgrade_preserves_index_and_returns_claimed_work(
    taut_pg_project: Path,
    raw_pg_conn: psycopg.Connection[Any],
    pg_schema: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(taut_pg_project)
    TautClient.init()
    client = TautClient(as_name="author")
    client.join("general")
    first = client.say("general", "first upgrade needle")
    assert [hit.ts for hit in client.search("needle")] == [first.ts]
    second = client.say("general", "second upgrade needle")
    pending = client.queue(PENDING_QUEUE_NAME)
    claimed = client.queue(CLAIMED_QUEUE_NAME)
    try:
        rows = pending.peek_many(10, with_timestamps=True)
        second_job = next(job_ts for body, job_ts in rows if str(second.ts) in body)
        assert (
            pending.move_one(claimed, exact_timestamp=second_job, with_timestamps=True)
            is not None
        )
        with raw_pg_conn.cursor() as cursor:
            cursor.execute(
                f"SELECT current_generation FROM {pg_schema}.taut_search_metadata"
            )
            before = cursor.fetchone()
            assert before is not None
            cursor.execute(
                f"UPDATE {pg_schema}.taut_search_metadata SET schema_version = 1"
            )
            cursor.execute(
                f"CREATE TABLE {pg_schema}.taut_search_claims (job_ts BIGINT PRIMARY KEY)"
            )
            cursor.execute(
                f"CREATE TABLE {pg_schema}.taut_search_housekeeping (key TEXT PRIMARY KEY)"
            )
        raw_pg_conn.commit()

        assert [hit.ts for hit in client.search("needle")] == [second.ts, first.ts]
        with raw_pg_conn.cursor() as cursor:
            cursor.execute(
                f"SELECT current_generation, schema_version "
                f"FROM {pg_schema}.taut_search_metadata"
            )
            assert cursor.fetchone() == (before[0], 2)
            cursor.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = %s AND table_name IN "
                "('taut_search_claims', 'taut_search_housekeeping')",
                (pg_schema,),
            )
            assert cursor.fetchall() == []
        assert claimed.peek_many(10) == []
    finally:
        claimed.close()
        pending.close()
        client.close()


def test_postgres_search_schema_uses_only_additive_builtin_objects(
    taut_pg_project: Path,
    pg_schema: str,
    raw_pg_conn: psycopg.Connection[Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from taut_pg._search import create_provider

    monkeypatch.chdir(taut_pg_project)
    TautClient.init()
    client = TautClient(as_name="van")
    queue = client.queue(META_QUEUE_NAME)
    calls: list[tuple[str, tuple[object, ...]]] = []

    @contextmanager
    def recording_sidecar(*, transaction: bool = False) -> Iterator[SidecarSession]:
        with queue.sidecar(transaction=transaction) as session:

            def run(
                sql: str,
                params: tuple[Any, ...] = (),
                *,
                fetch: bool = False,
            ) -> Iterable[tuple[Any, ...]]:
                calls.append((sql, params))
                return session.run(sql, params, fetch=fetch)

            yield SidecarSession(run)

    provider = create_provider(sidecar=recording_sidecar)
    try:
        provider.ensure_schema()
        initialization_calls = list(calls)
        calls.clear()
        provider.ensure_schema()
        warm_calls = list(calls)
        with raw_pg_conn.cursor() as cursor:
            cursor.execute(
                f"UPDATE {pg_schema}.taut_search_metadata SET schema_version = 1"
            )
        calls.clear()
        provider.ensure_schema()
        upgrade_calls = list(calls)
    finally:
        provider.close()
        queue.close()

    normalized_initialization = [
        " ".join(sql.split()).upper() for sql, _ in initialization_calls
    ]
    lock_index = next(
        index
        for index, statement in enumerate(normalized_initialization)
        if "PG_ADVISORY_XACT_LOCK" in statement
    )
    first_ddl_index = next(
        index
        for index, statement in enumerate(normalized_initialization)
        if statement.startswith("CREATE TABLE IF NOT EXISTS TAUT_SEARCH_METADATA")
    )
    assert lock_index < first_ddl_index
    assert initialization_calls[lock_index][1] == ("taut:search:schema",)
    assert all(
        "CREATE EXTENSION" not in statement for statement in normalized_initialization
    )
    _assert_version_read_without_shape_work(warm_calls)
    normalized_upgrade = [" ".join(sql.split()).upper() for sql, _ in upgrade_calls]
    upgrade_lock_index = next(
        index
        for index, statement in enumerate(normalized_upgrade)
        if "PG_ADVISORY_XACT_LOCK" in statement
    )
    upgrade_ddl_index = next(
        index
        for index, statement in enumerate(normalized_upgrade)
        if statement.startswith("CREATE TABLE IF NOT EXISTS TAUT_SEARCH_METADATA")
    )
    assert upgrade_lock_index < upgrade_ddl_index
    assert upgrade_calls[upgrade_lock_index][1] == ("taut:search:schema",)

    with raw_pg_conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = %s
              AND table_name LIKE 'taut_search_%%'
            ORDER BY table_name
            """,
            (pg_schema,),
        )
        required_tables = {
            "taut_search_documents",
            "taut_search_metadata",
            "taut_search_segments",
            "taut_search_thread_state",
        }
        assert required_tables <= {row[0] for row in cursor.fetchall()}
        cursor.execute(
            """
            SELECT column_name, data_type
            FROM information_schema.columns
            WHERE table_schema = %s
              AND table_name = 'taut_search_segments'
            """,
            (pg_schema,),
        )
        required_columns = {
            ("generation", "bigint"),
            ("message_ts", "bigint"),
            ("segment_index", "bigint"),
            ("projection", "tsvector"),
        }
        assert required_columns <= set(cursor.fetchall())
        cursor.execute(
            """
            SELECT access_method.amname,
                   index_state.indisvalid,
                   index_state.indisready,
                   index_state.indexprs,
                   index_state.indpred,
                   pg_catalog.array_agg(
                       indexed_column.attname ORDER BY indexed_key.ordinality
                   )
            FROM pg_catalog.pg_class AS index_relation
            JOIN pg_catalog.pg_namespace AS namespace
              ON namespace.oid = index_relation.relnamespace
            JOIN pg_catalog.pg_index AS index_state
              ON index_state.indexrelid = index_relation.oid
            JOIN pg_catalog.pg_class AS indexed_relation
              ON indexed_relation.oid = index_state.indrelid
            JOIN pg_catalog.pg_am AS access_method
              ON access_method.oid = index_relation.relam
            JOIN LATERAL pg_catalog.unnest(index_state.indkey)
              WITH ORDINALITY AS indexed_key(attnum, ordinality) ON TRUE
            JOIN pg_catalog.pg_attribute AS indexed_column
              ON indexed_column.attrelid = indexed_relation.oid
             AND indexed_column.attnum = indexed_key.attnum
            WHERE namespace.nspname = %s
              AND indexed_relation.relname = 'taut_search_segments'
              AND index_relation.relname = 'taut_search_segments_projection_idx'
            GROUP BY access_method.amname,
                     index_state.indisvalid,
                     index_state.indisready,
                     index_state.indexprs,
                     index_state.indpred
            """,
            (pg_schema,),
        )
        assert cursor.fetchone() == ("gin", True, True, None, None, ["projection"])


def test_postgres_search_initially_requires_rebuild_and_finish_clears_it(
    taut_pg_project: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from taut_pg._search import create_provider

    monkeypatch.chdir(taut_pg_project)
    TautClient.init()
    client = TautClient(as_name="van")
    queue = client.queue(META_QUEUE_NAME)
    provider = create_provider(sidecar=queue.sidecar)
    try:
        provider.ensure_schema()
        assert provider.requires_rebuild()

        generation = provider.begin_rebuild(scan_revision=200)
        provider.finish_rebuild(generation)

        assert not provider.requires_rebuild()
    finally:
        provider.close()
        queue.close()


def test_postgres_search_replaces_a_document_with_derived_lexemes_only(
    taut_pg_project: Path,
    pg_schema: str,
    raw_pg_conn: psycopg.Connection[Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from taut_pg._search import create_provider

    monkeypatch.chdir(taut_pg_project)
    TautClient.init()
    client = TautClient(as_name="van")
    queue = client.queue(META_QUEUE_NAME)
    calls: list[tuple[str, tuple[object, ...]]] = []

    @contextmanager
    def recording_sidecar(*, transaction: bool = False) -> Iterator[SidecarSession]:
        with queue.sidecar(transaction=transaction) as session:

            def run(
                sql: str,
                params: tuple[Any, ...] = (),
                *,
                fetch: bool = False,
            ) -> Iterable[tuple[Any, ...]]:
                calls.append((sql, params))
                return session.run(sql, params, fetch=fetch)

            yield SidecarSession(run)

    provider = create_provider(sidecar=recording_sidecar)
    try:
        provider.ensure_schema()
        provider.replace_document(
            IndexedDocument(
                message_ts=100,
                thread="general",
                text_sha256="digest-one",
                text_bytes=17,
                segments=("O'Reilly", "the parser"),
            )
        )
        provider.replace_document(
            IndexedDocument(
                message_ts=100,
                thread="renamed",
                text_sha256="digest-two",
                text_bytes=11,
                segments=("replacement",),
            )
        )
    finally:
        provider.close()
        queue.close()

    assert all("O'Reilly" not in statement for statement, _ in calls)
    assert all("replacement" not in statement for statement, _ in calls)
    bound_values = tuple(value for _, params in calls for value in params)
    assert "O'Reilly" in bound_values
    assert "replacement" in bound_values

    with raw_pg_conn.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT generation, message_ts, thread, text_sha256, text_bytes,
                   projection_version
            FROM {pg_schema}.taut_search_documents
            """
        )
        assert cursor.fetchall() == [(1, 100, "renamed", "digest-two", 11, 1)]
        cursor.execute(
            f"""
            SELECT segment_index, projection::text
            FROM {pg_schema}.taut_search_segments
            ORDER BY segment_index
            """
        )
        assert cursor.fetchall() == [(0, "'replacement':1")]


def test_postgres_search_requires_all_chunks_across_segments_newest_first(
    taut_pg_project: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from taut_pg._search import create_provider

    monkeypatch.chdir(taut_pg_project)
    TautClient.init()
    client = TautClient(as_name="van")
    queue = client.queue(META_QUEUE_NAME)
    calls: list[tuple[str, tuple[object, ...]]] = []

    @contextmanager
    def recording_sidecar(*, transaction: bool = False) -> Iterator[SidecarSession]:
        with queue.sidecar(transaction=transaction) as session:

            def run(
                sql: str,
                params: tuple[Any, ...] = (),
                *,
                fetch: bool = False,
            ) -> Iterable[tuple[Any, ...]]:
                calls.append((sql, params))
                return session.run(sql, params, fetch=fetch)

            yield SidecarSession(run)

    provider = create_provider(sidecar=recording_sidecar)
    try:
        provider.ensure_schema()
        documents = (
            IndexedDocument(100, "zeta", "digest-100", 10, ("the", "parser")),
            IndexedDocument(200, "beta", "digest-200", 10, ("the parser",)),
            IndexedDocument(300, "alpha", "digest-300", 6, ("parser",)),
            IndexedDocument(400, "omega", "digest-400", 10, ("the", "parser")),
        )
        for document in documents:
            provider.replace_document(document)

        assert provider.query(("the", "parser"), limit=2) == [
            SearchCandidate(400, "omega", "digest-400", 10),
            SearchCandidate(200, "beta", "digest-200", 10),
        ]
        assert provider.query((), limit=2) == []
        assert provider.query(("parser",), limit=0) == []
    finally:
        provider.close()
        queue.close()

    query_calls = [call for call in calls if "plainto_tsquery" in call[0]]
    assert len(query_calls) == 1
    query_sql, query_params = query_calls[0]
    assert "the" not in query_sql
    assert "parser" not in query_sql
    assert query_params == (1, "the", "parser", 2)


def test_postgres_search_revision_tombstone_prevents_old_worker_resurrection(
    taut_pg_project: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from taut_pg._search import create_provider

    monkeypatch.chdir(taut_pg_project)
    TautClient.init()
    client = TautClient(as_name="van")
    queue = client.queue(META_QUEUE_NAME)
    provider = create_provider(sidecar=queue.sidecar)
    document = IndexedDocument(100, "general", "digest", 12, ("current body",))
    try:
        provider.ensure_schema()

        assert provider.replace_document(document, revision=100)
        assert provider.delete_document(
            message_ts=100,
            thread="general",
            revision=300,
        )
        assert not provider.replace_document(document, revision=200)
        assert provider.applied_revision(100) == 300
        assert provider.query(("current",), limit=10) == []

        assert provider.replace_document(document, revision=400)
        assert provider.applied_revision(100) == 400
        assert provider.query(("current",), limit=10) == [
            SearchCandidate(100, "general", "digest", 12)
        ]
    finally:
        provider.close()
        queue.close()


def test_postgres_reconciliation_state_and_rotation_are_durable(
    taut_pg_project: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from taut_pg._search import create_provider

    monkeypatch.chdir(taut_pg_project)
    TautClient.init()
    client = TautClient(as_name="van")
    queue = client.queue(META_QUEUE_NAME)
    provider = create_provider(sidecar=queue.sidecar)
    documents = (
        IndexedDocument(100, "general", "digest-100", 10, ("first marker",)),
        IndexedDocument(200, "general", "digest-200", 10, ("second marker",)),
    )
    try:
        provider.ensure_schema()
        assert provider.thread_watermark("general") == ThreadWatermark(False, None)
        for document in documents:
            assert provider.replace_document(document, revision=100)
        assert provider.indexed_message_ids("general") == (100, 200)

        assert provider.record_reconciliation(
            "general",
            watermark=200,
            revision=300,
        )
        assert not provider.record_reconciliation(
            "general",
            watermark=100,
            revision=200,
        )
        assert provider.thread_watermark("general") == ThreadWatermark(True, 200)
        assert provider.next_reconciliation_thread(("zeta", "alpha")) == "alpha"
        assert provider.next_reconciliation_thread(("alpha", "zeta")) == "zeta"
        assert provider.next_reconciliation_thread(("zeta", "alpha")) == "alpha"
    finally:
        provider.close()
        queue.close()


def test_postgres_retargets_current_live_and_tombstone_documents_in_place(
    taut_pg_project: Path,
    raw_pg_conn: psycopg.Connection[Any],
    pg_schema: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from taut_pg._search import create_provider

    monkeypatch.chdir(taut_pg_project)
    TautClient.init()
    client = TautClient(as_name="van")
    queue = client.queue(META_QUEUE_NAME)
    provider = create_provider(sidecar=queue.sidecar)
    live = IndexedDocument(100, "general", "live-digest", 11, ("live marker",))
    tombstone = IndexedDocument(200, "general", "gone-digest", 12, ("gone marker",))
    try:
        provider.ensure_schema()
        assert provider.replace_document(live, revision=100)
        assert provider.replace_document(tombstone, revision=100)
        assert provider.delete_document(
            message_ts=200,
            thread="general",
            revision=150,
        )

        provider.retarget_threads((("general", "renamed"),), revision=300)

        assert provider.query(("live",), limit=10) == [
            SearchCandidate(100, "renamed", "live-digest", 11)
        ]
        with raw_pg_conn.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT message_ts, thread, latest_revision, indexed
                FROM {pg_schema}.taut_search_documents
                ORDER BY message_ts
                """
            )
            assert cursor.fetchall() == [
                (100, "renamed", 300, True),
                (200, "renamed", 300, False),
            ]
            cursor.execute(f"SELECT count(*) FROM {pg_schema}.taut_search_segments")
            assert cursor.fetchone() == (1,)
    finally:
        provider.close()
        queue.close()


def test_postgres_stale_thread_retarget_is_ignored(
    taut_pg_project: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from taut_pg._search import create_provider

    monkeypatch.chdir(taut_pg_project)
    TautClient.init()
    client = TautClient(as_name="van")
    queue = client.queue(META_QUEUE_NAME)
    provider = create_provider(sidecar=queue.sidecar)
    document = IndexedDocument(100, "general", "digest", 11, ("safe marker",))
    try:
        provider.ensure_schema()
        assert provider.replace_document(document, revision=300)

        provider.retarget_threads((("general", "stale-name"),), revision=200)

        assert provider.applied_revision(100) == 300
        assert provider.query(("safe",), limit=10) == [
            SearchCandidate(100, "general", "digest", 11)
        ]
    finally:
        provider.close()
        queue.close()


def test_postgres_thread_retarget_dual_writes_active_rebuild(
    taut_pg_project: Path,
    raw_pg_conn: psycopg.Connection[Any],
    pg_schema: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from taut_pg._search import create_provider

    monkeypatch.chdir(taut_pg_project)
    TautClient.init()
    client = TautClient(as_name="van")
    queue = client.queue(META_QUEUE_NAME)
    provider = create_provider(sidecar=queue.sidecar)
    document = IndexedDocument(100, "general", "digest", 11, ("safe marker",))
    try:
        provider.ensure_schema()
        assert provider.replace_document(document, revision=100)
        generation = provider.begin_rebuild(scan_revision=200)
        assert provider.replace_rebuild_document(
            document,
            generation=generation,
            revision=200,
        )

        provider.retarget_threads((("general", "renamed"),), revision=300)

        assert provider.query(("safe",), limit=10) == [
            SearchCandidate(100, "renamed", "digest", 11)
        ]
        with raw_pg_conn.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT generation, thread, latest_revision
                FROM {pg_schema}.taut_search_documents
                ORDER BY generation
                """
            )
            assert cursor.fetchall() == [
                (1, "renamed", 300),
                (generation, "renamed", 300),
            ]
            cursor.execute(f"SELECT count(*) FROM {pg_schema}.taut_search_segments")
            assert cursor.fetchone() == (2,)

        provider.finish_rebuild(generation)

        assert provider.query(("safe",), limit=10) == [
            SearchCandidate(100, "renamed", "digest", 11)
        ]
    finally:
        provider.close()
        queue.close()


def test_postgres_rebuild_is_invisible_until_atomic_generation_switch(
    taut_pg_project: Path,
    raw_pg_conn: psycopg.Connection[Any],
    pg_schema: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from taut_pg._search import create_provider

    monkeypatch.chdir(taut_pg_project)
    TautClient.init()
    client = TautClient(as_name="van")
    queue = client.queue(META_QUEUE_NAME)
    provider = create_provider(sidecar=queue.sidecar)
    current = IndexedDocument(100, "general", "old-digest", 10, ("old marker",))
    rebuilt = IndexedDocument(200, "general", "new-digest", 10, ("new marker",))
    try:
        provider.ensure_schema()
        assert provider.replace_document(current, revision=100)
        generation = provider.begin_rebuild(scan_revision=200)
        assert provider.replace_rebuild_document(
            rebuilt,
            generation=generation,
            revision=200,
        )

        assert provider.query(("old",), limit=10) == [
            SearchCandidate(100, "general", "old-digest", 10)
        ]
        assert provider.query(("new",), limit=10) == []

        provider.finish_rebuild(generation)

        assert provider.query(("old",), limit=10) == []
        assert provider.query(("new",), limit=10) == [
            SearchCandidate(200, "general", "new-digest", 10)
        ]
        with raw_pg_conn.cursor() as cursor:
            cursor.execute(
                f"SELECT DISTINCT generation FROM {pg_schema}.taut_search_documents"
            )
            assert cursor.fetchall() == [(generation,)]
    finally:
        provider.close()
        queue.close()


def test_postgres_later_mutation_wins_over_rebuild_scan(
    taut_pg_project: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from taut_pg._search import create_provider

    monkeypatch.chdir(taut_pg_project)
    TautClient.init()
    client = TautClient(as_name="van")
    queue = client.queue(META_QUEUE_NAME)
    provider = create_provider(sidecar=queue.sidecar)
    stale = IndexedDocument(100, "general", "stale-digest", 12, ("stale marker",))
    later = IndexedDocument(100, "general", "later-digest", 12, ("later marker",))
    deleted = IndexedDocument(200, "general", "delete-digest", 14, ("delete marker",))
    try:
        provider.ensure_schema()
        assert provider.replace_document(deleted, revision=100)
        generation = provider.begin_rebuild(scan_revision=200)

        assert provider.replace_document(later, revision=300)
        assert not provider.replace_rebuild_document(
            stale,
            generation=generation,
            revision=200,
        )
        assert provider.delete_document(
            message_ts=200,
            thread="general",
            revision=300,
        )
        assert not provider.replace_rebuild_document(
            deleted,
            generation=generation,
            revision=200,
        )
        provider.finish_rebuild(generation)

        assert provider.applied_revision(100) == 300
        assert provider.query(("stale",), limit=10) == []
        assert provider.query(("later",), limit=10) == [
            SearchCandidate(100, "general", "later-digest", 12)
        ]
        assert provider.applied_revision(200) == 300
        assert provider.query(("delete",), limit=10) == []
    finally:
        provider.close()
        queue.close()


def test_postgres_abort_rebuild_preserves_current_and_fences_stale_writer(
    taut_pg_project: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from taut_pg._search import create_provider

    monkeypatch.chdir(taut_pg_project)
    TautClient.init()
    client = TautClient(as_name="van")
    queue = client.queue(META_QUEUE_NAME)
    provider = create_provider(sidecar=queue.sidecar)
    current = IndexedDocument(100, "general", "safe-digest", 11, ("safe marker",))
    staged = IndexedDocument(200, "general", "stage-digest", 12, ("stage marker",))
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

        assert provider.query(("safe",), limit=10) == [
            SearchCandidate(100, "general", "safe-digest", 11)
        ]
        assert provider.query(("stage",), limit=10) == []
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
def test_postgres_rejects_newer_search_schema_or_projection(
    taut_pg_project: Path,
    raw_pg_conn: psycopg.Connection[Any],
    pg_schema: str,
    monkeypatch: pytest.MonkeyPatch,
    column: str,
    diagnostic: str,
) -> None:
    from taut_pg._search import create_provider

    monkeypatch.chdir(taut_pg_project)
    TautClient.init()
    client = TautClient(as_name="van")
    queue = client.queue(META_QUEUE_NAME)
    provider = create_provider(sidecar=queue.sidecar)
    try:
        provider.ensure_schema()
        with raw_pg_conn.cursor() as cursor:
            cursor.execute(
                f"UPDATE {pg_schema}.taut_search_metadata SET {column} = "
                f"{3 if column == 'schema_version' else 2} "
                "WHERE singleton = 1"
            )
        raw_pg_conn.commit()

        with pytest.raises(RuntimeError, match=f"^{diagnostic}$"):
            provider.ensure_schema()
    finally:
        provider.close()
        queue.close()


@pytest.mark.parametrize(
    ("schema_version", "projection_version", "diagnostic_fragment"),
    [
        (3, 1, "search schema version 3"),
        (1, 2, "search projection version 2"),
    ],
    ids=("schema", "projection"),
)
def test_postgres_source_shaped_version_refuses_before_current_shape_work(
    taut_pg_project: Path,
    raw_pg_conn: psycopg.Connection[Any],
    pg_schema: str,
    monkeypatch: pytest.MonkeyPatch,
    schema_version: int,
    projection_version: int,
    diagnostic_fragment: str,
) -> None:
    from taut_pg._search import create_provider

    monkeypatch.chdir(taut_pg_project)
    TautClient.init()
    with raw_pg_conn.cursor() as cursor:
        cursor.execute(
            f"""
            CREATE TABLE {pg_schema}.taut_search_metadata (
                singleton BIGINT PRIMARY KEY CHECK (singleton = 1),
                schema_version BIGINT NOT NULL,
                projection_version BIGINT NOT NULL
            )
            """
        )
        cursor.execute(
            f"""
            INSERT INTO {pg_schema}.taut_search_metadata (
                singleton, schema_version, projection_version
            ) VALUES (1, %s, %s)
            """,
            (schema_version, projection_version),
        )
    source_before = _search_metadata_snapshot(raw_pg_conn, schema=pg_schema)

    client = TautClient(as_name="van")
    queue = client.queue(META_QUEUE_NAME)
    calls: list[tuple[str, tuple[object, ...]]] = []
    provider = create_provider(sidecar=_recording_sidecar(queue, calls))
    try:
        with pytest.raises(RuntimeError, match=diagnostic_fragment):
            provider.ensure_schema()
    finally:
        provider.close()
        queue.close()
        client.close()

    _assert_version_read_without_shape_work(calls)
    assert _search_metadata_snapshot(raw_pg_conn, schema=pg_schema) == source_before


def test_postgres_missing_stable_search_version_fails_before_shape_work(
    taut_pg_project: Path,
    raw_pg_conn: psycopg.Connection[Any],
    pg_schema: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from taut_pg._search import create_provider

    monkeypatch.chdir(taut_pg_project)
    TautClient.init()
    with raw_pg_conn.cursor() as cursor:
        cursor.execute(
            f"""
            CREATE TABLE {pg_schema}.taut_search_metadata (
                singleton BIGINT PRIMARY KEY CHECK (singleton = 1),
                schema_version BIGINT NOT NULL,
                current_generation BIGINT NOT NULL,
                staging_generation BIGINT,
                staging_scan_revision BIGINT,
                next_generation BIGINT NOT NULL,
                initialized BIGINT NOT NULL,
                rotation_cursor TEXT
            )
            """
        )
        cursor.execute(
            f"""
            INSERT INTO {pg_schema}.taut_search_metadata (
                singleton, schema_version, current_generation,
                next_generation, initialized
            ) VALUES (1, 1, 1, 2, 0)
            """
        )
    source_before = _search_metadata_snapshot(raw_pg_conn, schema=pg_schema)

    client = TautClient(as_name="van")
    queue = client.queue(META_QUEUE_NAME)
    calls: list[tuple[str, tuple[object, ...]]] = []
    provider = create_provider(sidecar=_recording_sidecar(queue, calls))
    try:
        with pytest.raises(OperationalError, match="projection_version"):
            provider.ensure_schema()
    finally:
        provider.close()
        queue.close()
        client.close()

    _assert_version_read_without_shape_work(calls)
    assert _search_metadata_snapshot(raw_pg_conn, schema=pg_schema) == source_before
