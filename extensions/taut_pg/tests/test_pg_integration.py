from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import psycopg
import pytest
from psycopg import sql
from simplebroker.ext import get_backend_plugin

from taut.client import TautClient

pytestmark = pytest.mark.pg_only


def test_extension_import_and_plugin_resolution() -> None:
    import taut_pg

    assert taut_pg.__all__ == []
    assert get_backend_plugin("postgres").name == "postgres"


def test_taut_init_and_messages_use_configured_postgres_project(
    taut_pg_project: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(taut_pg_project)

    result = TautClient.init()
    van = TautClient(as_name="van")
    bob = TautClient(as_name="bob")

    van.join("general")
    bob.join("general")
    message = van.say("general", "hello from pg")

    assert result.created is False
    assert result.db.startswith("postgresql://")
    assert message.text == "hello from pg"
    assert bob.read("general")[-1].text == "hello from pg"


def test_taut_client_discovers_postgres_project_from_nested_directory(
    taut_pg_project: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    nested = taut_pg_project / "nested" / "worktree"
    nested.mkdir(parents=True)
    monkeypatch.chdir(nested)

    TautClient.init()
    van = TautClient(as_name="van")
    bob = TautClient(as_name="bob")
    van.join("general")
    bob.join("general")

    van.say("general", "hello from nested pg")

    assert bob.read("general")[-1].text == "hello from nested pg"


def test_taut_cli_uses_postgres_project_config(
    taut_pg_project: Path,
    taut_cli: Callable[..., tuple[int, str, str]],
) -> None:
    rc, out, err = taut_cli("init", "--json", cwd=taut_pg_project)
    assert rc == 0, err
    init_result = json.loads(out)
    assert init_result["created"] is False
    assert init_result["db"].startswith("postgresql://")

    rc, out, err = taut_cli(
        "--as",
        "van",
        "join",
        "general",
        "--json",
        cwd=taut_pg_project,
    )
    assert rc == 0, err
    assert json.loads(out.splitlines()[0])["name"] == "van"

    rc, out, err = taut_cli(
        "--as",
        "van",
        "say",
        "general",
        "hello from pg cli",
        "--json",
        cwd=taut_pg_project,
    )
    assert rc == 0, err
    assert json.loads(out)["text"] == "hello from pg cli"

    rc, out, err = taut_cli("log", "general", "--json", cwd=taut_pg_project)
    assert rc == 0, err
    assert [json.loads(line)["text"] for line in out.splitlines()] == [
        "van created #general",
        "hello from pg cli",
    ]


def test_postgres_cleanup_drops_only_created_schema(
    pg_dsn: str,
    pg_schema: str,
    raw_pg_conn: psycopg.Connection[Any],
) -> None:
    plugin = get_backend_plugin("postgres")
    plugin.initialize_target(pg_dsn, backend_options={"schema": pg_schema})
    sentinel_schema = f"{pg_schema}_sentinel"
    try:
        with raw_pg_conn.cursor() as cursor:
            cursor.execute(
                sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(sentinel_schema))
            )
            cursor.execute(
                sql.SQL("CREATE TABLE {}.sentinel (value TEXT NOT NULL)").format(
                    sql.Identifier(sentinel_schema)
                )
            )
            cursor.execute(
                sql.SQL("INSERT INTO {}.sentinel (value) VALUES (%s)").format(
                    sql.Identifier(sentinel_schema)
                ),
                ("unrelated-schema-survives",),
            )
            cursor.execute(
                "SELECT schema_name FROM information_schema.schemata "
                "WHERE schema_name = %s",
                (pg_schema,),
            )
            assert cursor.fetchone() == (pg_schema,)

        assert (
            plugin.cleanup_target(pg_dsn, backend_options={"schema": pg_schema}) is True
        )

        with raw_pg_conn.cursor() as cursor:
            cursor.execute(
                "SELECT schema_name FROM information_schema.schemata "
                "WHERE schema_name = %s",
                (pg_schema,),
            )
            assert cursor.fetchone() is None
            cursor.execute(
                sql.SQL("SELECT value FROM {}.sentinel").format(
                    sql.Identifier(sentinel_schema)
                )
            )
            assert cursor.fetchall() == [("unrelated-schema-survives",)]
    finally:
        with raw_pg_conn.cursor() as cursor:
            cursor.execute(
                sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(
                    sql.Identifier(sentinel_schema)
                )
            )


def test_postgres_delete_tombstone_binds_search_projection_version(
    taut_pg_project: Path,
    raw_pg_conn: psycopg.Connection[Any],
    pg_schema: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import taut_pg._search as pg_search_mod
    from simplebroker.ext import SidecarSession

    import taut.search._provider as provider_mod
    from taut._constants import META_QUEUE_NAME
    from taut.search import query_chunks
    from taut.search._jobs import PENDING_QUEUE_NAME, JobQueues
    from taut.search._provider import IndexedDocument
    from taut.search._worker import process_one

    monkeypatch.chdir(taut_pg_project)
    TautClient.init()
    client = TautClient(as_name="van")
    queue = client.queue(META_QUEUE_NAME)
    pending = client.queue(PENDING_QUEUE_NAME)
    jobs = JobQueues(pending=pending)
    provider = pg_search_mod.create_provider(sidecar=queue.sidecar)
    try:
        provider.ensure_schema()
        monkeypatch.setattr(provider_mod, "SEARCH_PROJECTION_VERSION", 2)
        monkeypatch.setattr(pg_search_mod, "SEARCH_PROJECTION_VERSION", 2)
        with raw_pg_conn.cursor() as cursor:
            cursor.execute(
                f"UPDATE {pg_schema}.taut_search_metadata SET projection_version = 2 WHERE singleton = 1"
            )

        # Unit recording check on _delete_in_generation parameter binding.
        recorded: list[tuple[str, tuple[Any, ...]]] = []

        def fake_run(
            stmt: str,
            params: tuple[Any, ...] = (),
            *,
            fetch: bool = False,
        ) -> list[tuple[Any, ...]]:
            recorded.append((stmt, params))
            return [(123,)] if fetch else []

        assert pg_search_mod.PostgresSearchProvider._delete_in_generation(
            SidecarSession(fake_run),
            message_ts=123,
            thread="general",
            generation=1,
            revision=456,
        )
        assert 2 in recorded[0][1]

        # Live pending-job drain via process_one before any reconciliation scan runs.
        drained_ts = queue.generate_timestamp()
        assert provider.replace_document(
            IndexedDocument(
                message_ts=drained_ts,
                thread="general",
                text_sha256="abc",
                text_bytes=6,
                segments=("needle",),
            ),
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
        assert provider.query(query_chunks("needle"), limit=10) == []

        with raw_pg_conn.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT message_ts, projection_version, indexed
                FROM {pg_schema}.taut_search_documents
                WHERE message_ts IN (%s, %s)
                ORDER BY message_ts
                """,
                (drained_ts, direct_ts),
            )
            rows = cursor.fetchall()
        assert rows == [
            (drained_ts, 2, False),
            (direct_ts, 2, False),
        ]
    finally:
        provider.close()
        pending.close()
        queue.close()
        client.close()


def test_postgres_thread_index_ddl_fresh_upgrade_and_schema2_steady_state(
    taut_pg_project: Path,
    raw_pg_conn: psycopg.Connection[Any],
    pg_schema: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from contextlib import contextmanager

    from simplebroker.ext import SidecarSession
    from taut_pg._search import create_provider

    from taut._constants import META_QUEUE_NAME

    monkeypatch.chdir(taut_pg_project)
    TautClient.init()
    client = TautClient(as_name="van")
    client.join("general")
    msg = client.say("general", "pg index needle")
    queue = client.queue(META_QUEUE_NAME)
    provider = create_provider(sidecar=queue.sidecar)
    try:
        provider.ensure_schema()
        with raw_pg_conn.cursor() as cursor:
            cursor.execute(
                "SELECT indexname FROM pg_indexes WHERE schemaname = %s",
                (pg_schema,),
            )
            indexes = {row[0] for row in cursor.fetchall()}
        assert "taut_search_documents_thread_idx" in indexes

        # Schema-1 upgrade creates taut_search_documents_thread_idx.
        with raw_pg_conn.cursor() as cursor:
            cursor.execute(f"DROP INDEX {pg_schema}.taut_search_documents_thread_idx")
            cursor.execute(
                f"UPDATE {pg_schema}.taut_search_metadata SET schema_version = 1 WHERE singleton = 1"
            )
        provider.ensure_schema()
        with raw_pg_conn.cursor() as cursor:
            cursor.execute(
                "SELECT indexname FROM pg_indexes WHERE schemaname = %s",
                (pg_schema,),
            )
            upgraded_indexes = {row[0] for row in cursor.fetchall()}
        assert "taut_search_documents_thread_idx" in upgraded_indexes

        # Pre-fix schema-2 database without the index runs zero DDL on search.
        with raw_pg_conn.cursor() as cursor:
            cursor.execute(f"DROP INDEX {pg_schema}.taut_search_documents_thread_idx")
        statements: list[str] = []

        def recording_provider(meta: Any) -> Any:
            @contextmanager
            def sidecar(*, transaction: bool = False) -> Any:
                with meta.sidecar(transaction=transaction) as session:

                    def run(
                        stmt: str,
                        params: tuple[Any, ...] = (),
                        *,
                        fetch: bool = False,
                    ) -> Any:
                        statements.append(" ".join(stmt.split()))
                        return session.run(stmt, params, fetch=fetch)

                    yield SidecarSession(run)

            return create_provider(sidecar=sidecar)

        monkeypatch.setattr(client, "_search_provider", recording_provider)
        hits = client.search("needle", channels=("general",))
        assert [hit.ts for hit in hits] == [msg.ts]
        assert not any(stmt.upper().startswith("CREATE INDEX") for stmt in statements)
        with raw_pg_conn.cursor() as cursor:
            cursor.execute(
                "SELECT indexname FROM pg_indexes WHERE schemaname = %s",
                (pg_schema,),
            )
            after_indexes = {row[0] for row in cursor.fetchall()}
        assert "taut_search_documents_thread_idx" not in after_indexes
    finally:
        provider.close()
        queue.close()
        client.close()


def _run_search_capturing_meta_revisions(
    monkeypatch: pytest.MonkeyPatch,
    client: TautClient,
    query: str,
    *,
    channels: tuple[str, ...],
) -> tuple[list[Any], list[int]]:
    from simplebroker import Queue

    from taut._constants import META_QUEUE_NAME

    allocated: list[int] = []
    orig_gen_ts = Queue.generate_timestamp

    def spy_gen_ts(self: Queue) -> int:
        ts = orig_gen_ts(self)
        if self.name == META_QUEUE_NAME:
            allocated.append(ts)
        return ts

    with monkeypatch.context() as rev_patch:
        rev_patch.setattr(Queue, "generate_timestamp", spy_gen_ts)
        hits = client.search(query, channels=channels)
    return hits, allocated


def test_postgres_reconcile_quiescent_fast_path_and_cross_generation_fences(
    taut_pg_project: Path,
    raw_pg_conn: psycopg.Connection[Any],
    pg_schema: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from contextlib import contextmanager

    from taut_pg._search import create_provider

    import taut.client._searching as searching_mod
    from taut._constants import META_QUEUE_NAME
    from taut.search import _provider as provider_mod
    from taut.search import projection_segments, query_chunks
    from taut.search._provider import IndexedDocument, SearchCandidate

    monkeypatch.chdir(taut_pg_project)
    TautClient.init()
    client = TautClient(as_name="van")
    try:
        client.join("general")
        seeded_ids: list[int] = []
        last_msg = None
        for idx in range(300):
            last_msg = client.say("general", f"pg quiescent item {idx:03d} needle")
            seeded_ids.append(last_msg.ts)
        assert last_msg is not None
        assert client.search("item 299", channels=("general",))

        projection_calls = 0
        write_tx_count = 0

        def count_projection(text: str, *, max_segment_bytes: int) -> tuple[str, ...]:
            nonlocal projection_calls
            projection_calls += 1
            return projection_segments(text, max_segment_bytes=max_segment_bytes)

        monkeypatch.setattr(searching_mod, "projection_segments", count_projection)

        def tracked_provider(meta: Any) -> Any:
            from simplebroker.ext import SidecarSession

            @contextmanager
            def sidecar(*, transaction: bool = False) -> Any:
                nonlocal write_tx_count
                mutated = False
                with meta.sidecar(transaction=transaction) as session:

                    def run(
                        stmt: str,
                        params: tuple[Any, ...] = (),
                        *,
                        fetch: bool = False,
                    ) -> Any:
                        nonlocal mutated
                        upper = " ".join(stmt.split()).upper()
                        if transaction and (
                            "FOR UPDATE" in upper
                            or upper.startswith(("INSERT ", "UPDATE ", "DELETE "))
                        ):
                            mutated = True
                        return session.run(stmt, params, fetch=fetch)

                    yield SidecarSession(run)
                if mutated:
                    write_tx_count += 1

            return create_provider(sidecar=sidecar)

        monkeypatch.setattr(client, "_search_provider", tracked_provider)
        queue = client.queue(META_QUEUE_NAME)
        provider = create_provider(sidecar=queue.sidecar)
        try:
            before_rev = provider.applied_revision(last_msg.ts)
            assert before_rev is not None

            hits, allocated_revisions = _run_search_capturing_meta_revisions(
                monkeypatch,
                client,
                "item 299",
                channels=("general",),
            )
            assert [hit.ts for hit in hits] == [last_msg.ts]
            assert projection_calls == 0
            assert write_tx_count <= 6
            assert len(allocated_revisions) == 1
            scan_rev = allocated_revisions[0]
            assert scan_rev > before_rev
            with raw_pg_conn.cursor() as cursor:
                cursor.execute(
                    f"SELECT current_generation FROM {pg_schema}.taut_search_metadata WHERE singleton = 1"
                )
                current_gen_row = cursor.fetchone()
                assert current_gen_row is not None
                cursor.execute(
                    f"""
                    SELECT message_ts, latest_revision
                    FROM {pg_schema}.taut_search_documents
                    WHERE generation = %s AND message_ts = ANY(%s)
                    """,
                    (current_gen_row[0], seeded_ids),
                )
                rev_by_ts = {int(ts): int(rev) for ts, rev in cursor.fetchall()}
            assert set(rev_by_ts) == set(seeded_ids)
            assert set(rev_by_ts.values()) == {scan_rev}

            check_cls = provider_mod.DocumentCheck

            def make_doc(text: str) -> tuple[IndexedDocument, Any]:
                ts = queue.generate_timestamp()
                encoded = text.encode("utf-8")
                import hashlib

                digest = hashlib.sha256(encoded).hexdigest()
                doc = IndexedDocument(
                    message_ts=ts,
                    thread="general",
                    text_sha256=digest,
                    text_bytes=len(encoded),
                    segments=projection_segments(text, max_segment_bytes=1024),
                )
                return doc, check_cls(
                    message_ts=ts,
                    thread="general",
                    text_sha256=digest,
                    text_bytes=len(encoded),
                )

            # Newer tombstone preserved.
            tomb_doc, tomb_check = make_doc("pg tombstoned marker")
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

            # Matching current + matching staging advances both.
            both_doc, both_check = make_doc("pg both match")
            assert provider.replace_document(both_doc, revision=100)
            gen_ok = provider.begin_rebuild(scan_revision=200)
            assert provider.replace_rebuild_document(
                both_doc, generation=gen_ok, revision=200
            )
            assert (
                provider.reconcile_unchanged_batch([both_check], revision=300)
                == frozenset()
            )
            with raw_pg_conn.cursor() as cursor:
                cursor.execute(
                    f"SELECT latest_revision FROM {pg_schema}.taut_search_documents WHERE message_ts = %s ORDER BY generation",
                    (both_doc.message_ts,),
                )
                assert [int(r[0]) for r in cursor.fetchall()] == [300, 300]
            provider.abort_rebuild(gen_ok)

            # R2-02: Mixed current match + missing active staging must NOT bump current prematurely.
            mixed_doc, mixed_check = make_doc("pg mixed staging repair")
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
                SearchCandidate(
                    message_ts=mixed_doc.message_ts,
                    thread="general",
                    text_sha256=mixed_doc.text_sha256,
                    text_bytes=mixed_doc.text_bytes,
                )
            ]
        finally:
            provider.close()
            queue.close()
    finally:
        client.close()


def test_postgres_query_pushes_down_before_and_threads(
    taut_pg_project: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import hashlib
    from contextlib import contextmanager

    from simplebroker.ext import SidecarSession
    from taut_pg._search import create_provider

    from taut._constants import META_QUEUE_NAME
    from taut.search import projection_segments
    from taut.search._provider import IndexedDocument, SearchCandidate

    monkeypatch.chdir(taut_pg_project)
    TautClient.init()
    client = TautClient(as_name="van")
    queue = client.queue(META_QUEUE_NAME)
    calls: list[tuple[str, tuple[Any, ...]]] = []

    @contextmanager
    def recording_sidecar(*, transaction: bool = False) -> Any:
        with queue.sidecar(transaction=transaction) as session:

            def run(
                stmt: str,
                params: tuple[Any, ...] = (),
                *,
                fetch: bool = False,
            ) -> Any:
                calls.append((" ".join(stmt.split()), params))
                return session.run(stmt, params, fetch=fetch)

            yield SidecarSession(run)

    provider = create_provider(sidecar=recording_sidecar)
    try:
        provider.ensure_schema()

        def doc_for(ts: int, text: str, thread: str) -> IndexedDocument:
            encoded = text.encode("utf-8")
            return IndexedDocument(
                message_ts=ts,
                thread=thread,
                text_sha256=hashlib.sha256(encoded).hexdigest(),
                text_bytes=len(encoded),
                segments=projection_segments(text, max_segment_bytes=1024),
            )

        doc_match = doc_for(100, "alpha beta", "general")
        doc_other = doc_for(200, "alpha beta", "random")
        doc_after = doc_for(300, "alpha beta", "ops")
        for doc in (doc_match, doc_other, doc_after):
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
        assert result == [
            SearchCandidate(
                message_ts=doc_match.message_ts,
                thread=doc_match.thread,
                text_sha256=doc_match.text_sha256,
                text_bytes=doc_match.text_bytes,
            )
        ]
        select_queries = [
            (stmt, params)
            for stmt, params in calls
            if "FROM taut_search_documents AS d" in stmt
        ]
        assert len(select_queries) == 1
        stmt, params = select_queries[0]
        assert "d.message_ts < ?" in stmt
        assert "d.thread IN (?, ?)" in stmt
        assert 280 in params
        assert "general" in params and "ops" in params
    finally:
        provider.close()
        queue.close()
        client.close()
