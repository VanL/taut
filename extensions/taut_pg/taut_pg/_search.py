"""PostgreSQL physical search provider using only a bound sidecar accessor.

Spec references: docs/specs/06-search.md [SRCH-2.1], [SRCH-3.1],
[SRCH-3.2], [SRCH-6.1], [SRCH-6.2], [SRCH-7], [SRCH-10.3], [SRCH-11.2].
"""

from __future__ import annotations

from dataclasses import dataclass

from simplebroker.ext import SidecarSession

from taut.search._provider import (
    IndexedDocument,
    SearchCandidate,
    SidecarAccessor,
    ThreadWatermark,
)

_SCHEMA_LOCK_KEY = "taut:search:schema"
_SCHEMA_VERSION = 1
_PROJECTION_VERSION = 1

_METADATA_DDL = """
    CREATE TABLE IF NOT EXISTS taut_search_metadata (
        singleton             BIGINT PRIMARY KEY CHECK (singleton = 1),
        schema_version        BIGINT NOT NULL,
        projection_version    BIGINT NOT NULL,
        current_generation    BIGINT NOT NULL,
        staging_generation    BIGINT,
        staging_scan_revision BIGINT,
        next_generation       BIGINT NOT NULL,
        initialized           BIGINT NOT NULL,
        rotation_cursor       TEXT,
        CHECK (
            (staging_generation IS NULL AND staging_scan_revision IS NULL)
            OR
            (staging_generation IS NOT NULL AND staging_scan_revision IS NOT NULL)
        )
    )
"""

_DDL = (
    """
    CREATE TABLE IF NOT EXISTS taut_search_documents (
        generation         BIGINT NOT NULL,
        message_ts         BIGINT NOT NULL,
        thread             TEXT NOT NULL,
        text_sha256        TEXT NOT NULL,
        text_bytes         BIGINT NOT NULL,
        projection_version BIGINT NOT NULL,
        latest_revision    BIGINT NOT NULL,
        indexed            BOOLEAN NOT NULL,
        PRIMARY KEY (generation, message_ts)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS taut_search_segments (
        generation    BIGINT NOT NULL,
        message_ts    BIGINT NOT NULL,
        segment_index BIGINT NOT NULL,
        projection    TSVECTOR NOT NULL,
        PRIMARY KEY (generation, message_ts, segment_index),
        FOREIGN KEY (generation, message_ts)
            REFERENCES taut_search_documents (generation, message_ts)
            ON DELETE CASCADE
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS taut_search_segments_projection_idx
        ON taut_search_segments USING GIN (projection)
    """,
    """
    CREATE TABLE IF NOT EXISTS taut_search_thread_state (
        generation      BIGINT NOT NULL,
        thread          TEXT NOT NULL,
        watermark       BIGINT,
        latest_revision BIGINT NOT NULL,
        PRIMARY KEY (generation, thread)
    )
    """,
)


@dataclass(slots=True)
class PostgresSearchProvider:
    """Built-in PostgreSQL lexical index owned by the ``taut-pg`` extension."""

    sidecar: SidecarAccessor

    def ensure_schema(self) -> None:
        with self.sidecar(transaction=True) as session:
            session.run(
                """
                SELECT pg_catalog.pg_advisory_xact_lock(
                    pg_catalog.hashtextextended(?, 0)
                )
                """,
                (_SCHEMA_LOCK_KEY,),
            )
            session.run(_METADATA_DDL)
            session.run(
                """
                INSERT INTO taut_search_metadata (
                    singleton, schema_version, projection_version,
                    current_generation, next_generation, initialized
                ) VALUES (1, ?, ?, 1, 2, 0)
                ON CONFLICT (singleton) DO NOTHING
                """,
                (_SCHEMA_VERSION, _PROJECTION_VERSION),
            )
            rows = list(
                session.run(
                    """
                    SELECT schema_version, projection_version
                    FROM taut_search_metadata
                    WHERE singleton = 1
                    """,
                    fetch=True,
                )
            )
            schema_version, projection_version = map(int, rows[0])
            if schema_version > _SCHEMA_VERSION:
                raise RuntimeError(
                    "search schema version "
                    f"{schema_version} is newer than supported version "
                    f"{_SCHEMA_VERSION}"
                )
            if projection_version > _PROJECTION_VERSION:
                raise RuntimeError(
                    "search projection version "
                    f"{projection_version} is newer than supported version "
                    f"{_PROJECTION_VERSION}"
                )
            if schema_version != _SCHEMA_VERSION:
                raise RuntimeError(
                    f"unsupported search schema version {schema_version}"
                )
            if projection_version != _PROJECTION_VERSION:
                raise RuntimeError(
                    f"unsupported search projection version {projection_version}"
                )
            for statement in _DDL:
                session.run(statement)

    def replace_document(
        self,
        document: IndexedDocument,
        *,
        revision: int | None = None,
    ) -> bool:
        effective_revision = document.message_ts if revision is None else revision
        with self.sidecar(transaction=True) as session:
            current_generation, staging = self._state(session, lock="UPDATE")
            applied = self._replace_in_generation(
                session,
                document,
                generation=current_generation,
                revision=effective_revision,
            )
            if staging is not None and effective_revision >= staging[1]:
                self._replace_in_generation(
                    session,
                    document,
                    generation=staging[0],
                    revision=effective_revision,
                )
        return applied

    @staticmethod
    def _replace_in_generation(
        session: SidecarSession,
        document: IndexedDocument,
        *,
        generation: int,
        revision: int,
    ) -> bool:
        applied = list(
            session.run(
                """
                INSERT INTO taut_search_documents AS current (
                    generation, message_ts, thread, text_sha256, text_bytes,
                    projection_version, latest_revision, indexed
                ) VALUES (?, ?, ?, ?, ?, 1, ?, TRUE)
                ON CONFLICT (generation, message_ts) DO UPDATE SET
                    thread = excluded.thread,
                    text_sha256 = excluded.text_sha256,
                    text_bytes = excluded.text_bytes,
                    projection_version = excluded.projection_version,
                    latest_revision = excluded.latest_revision,
                    indexed = TRUE
                WHERE excluded.latest_revision >= current.latest_revision
                RETURNING message_ts
                """,
                (
                    generation,
                    document.message_ts,
                    document.thread,
                    document.text_sha256,
                    document.text_bytes,
                    revision,
                ),
                fetch=True,
            )
        )
        if not applied:
            return False
        session.run(
            """
            DELETE FROM taut_search_segments
            WHERE generation = ? AND message_ts = ?
            """,
            (generation, document.message_ts),
        )
        for segment_index, projection in enumerate(document.segments):
            session.run(
                """
                INSERT INTO taut_search_segments (
                    generation, message_ts, segment_index, projection
                ) VALUES (
                    ?, ?, ?, pg_catalog.to_tsvector(
                        'pg_catalog.simple'::pg_catalog.regconfig, ?
                    )
                )
                """,
                (generation, document.message_ts, segment_index, projection),
            )
        return True

    def delete_document(
        self,
        *,
        message_ts: int,
        thread: str,
        revision: int,
    ) -> bool:
        with self.sidecar(transaction=True) as session:
            current_generation, staging = self._state(session, lock="UPDATE")
            applied = self._delete_in_generation(
                session,
                message_ts=message_ts,
                thread=thread,
                generation=current_generation,
                revision=revision,
            )
            if staging is not None and revision >= staging[1]:
                self._delete_in_generation(
                    session,
                    message_ts=message_ts,
                    thread=thread,
                    generation=staging[0],
                    revision=revision,
                )
        return applied

    @staticmethod
    def _delete_in_generation(
        session: SidecarSession,
        *,
        message_ts: int,
        thread: str,
        generation: int,
        revision: int,
    ) -> bool:
        applied = list(
            session.run(
                """
                INSERT INTO taut_search_documents AS current (
                    generation, message_ts, thread, text_sha256, text_bytes,
                    projection_version, latest_revision, indexed
                ) VALUES (?, ?, ?, '', 0, 1, ?, FALSE)
                ON CONFLICT (generation, message_ts) DO UPDATE SET
                    thread = excluded.thread,
                    text_sha256 = '',
                    text_bytes = 0,
                    projection_version = excluded.projection_version,
                    latest_revision = excluded.latest_revision,
                    indexed = FALSE
                WHERE excluded.latest_revision >= current.latest_revision
                RETURNING message_ts
                """,
                (generation, message_ts, thread, revision),
                fetch=True,
            )
        )
        if not applied:
            return False
        session.run(
            """
            DELETE FROM taut_search_segments
            WHERE generation = ? AND message_ts = ?
            """,
            (generation, message_ts),
        )
        return True

    def applied_revision(self, message_ts: int) -> int | None:
        with self.sidecar(transaction=True) as session:
            current_generation, _staging = self._state(session, lock="SHARE")
            rows = list(
                session.run(
                    """
                    SELECT latest_revision
                    FROM taut_search_documents
                    WHERE generation = ? AND message_ts = ?
                    """,
                    (current_generation, message_ts),
                    fetch=True,
                )
            )
        return None if not rows else int(rows[0][0])

    def retarget_threads(
        self,
        affected: tuple[tuple[str, str], ...],
        *,
        revision: int,
    ) -> None:
        """Conditionally move exact thread mappings across live generations."""

        if not affected:
            return
        with self.sidecar(transaction=True) as session:
            current_generation, staging = self._state(session, lock="UPDATE")
            self._retarget_generation(
                session,
                affected,
                generation=current_generation,
                revision=revision,
            )
            if staging is not None:
                self._retarget_generation(
                    session,
                    affected,
                    generation=staging[0],
                    revision=revision,
                )

    @staticmethod
    def _retarget_generation(
        session: SidecarSession,
        affected: tuple[tuple[str, str], ...],
        *,
        generation: int,
        revision: int,
    ) -> None:
        cases = " ".join("WHEN ? THEN ?" for _old, _new in affected)
        old_threads = tuple(old for old, _new in affected)
        placeholders = ", ".join("?" for _old in old_threads)
        case_params = tuple(value for pair in affected for value in pair)
        session.run(
            f"""
            UPDATE taut_search_documents
            SET thread = CASE thread {cases} ELSE thread END,
                latest_revision = ?
            WHERE generation = ?
              AND latest_revision <= ?
              AND thread IN ({placeholders})
            """,
            (*case_params, revision, generation, revision, *old_threads),
        )

    def thread_watermark(self, thread: str) -> ThreadWatermark:
        """Return whether a current-generation source frontier is known."""

        with self.sidecar(transaction=True) as session:
            current_generation, _staging = self._state(session, lock="SHARE")
            rows = list(
                session.run(
                    """
                    SELECT watermark
                    FROM taut_search_thread_state
                    WHERE generation = ? AND thread = ?
                    """,
                    (current_generation, thread),
                    fetch=True,
                )
            )
        if not rows:
            return ThreadWatermark(known=False, message_ts=None)
        value = rows[0][0]
        return ThreadWatermark(
            known=True,
            message_ts=None if value is None else int(value),
        )

    def indexed_message_ids(self, thread: str) -> tuple[int, ...]:
        """Return current live IDs for exact full-thread reconciliation."""

        with self.sidecar(transaction=True) as session:
            current_generation, _staging = self._state(session, lock="SHARE")
            rows = session.run(
                """
                SELECT message_ts
                FROM taut_search_documents
                WHERE generation = ? AND thread = ? AND indexed = TRUE
                ORDER BY message_ts
                """,
                (current_generation, thread),
                fetch=True,
            )
            return tuple(int(row[0]) for row in rows)

    def record_reconciliation(
        self,
        thread: str,
        *,
        watermark: int | None,
        revision: int,
    ) -> bool:
        """Conditionally publish a source frontier for the current generation."""

        with self.sidecar(transaction=True) as session:
            current_generation, _staging = self._state(session, lock="UPDATE")
            rows = list(
                session.run(
                    """
                    INSERT INTO taut_search_thread_state AS current (
                        generation, thread, watermark, latest_revision
                    ) VALUES (?, ?, ?, ?)
                    ON CONFLICT (generation, thread) DO UPDATE SET
                        watermark = excluded.watermark,
                        latest_revision = excluded.latest_revision
                    WHERE excluded.latest_revision >= current.latest_revision
                    RETURNING thread
                    """,
                    (current_generation, thread, watermark, revision),
                    fetch=True,
                )
            )
        return bool(rows)

    def next_reconciliation_thread(
        self,
        threads: tuple[str, ...],
    ) -> str | None:
        """Advance and return the durable rotation cursor."""

        ordered = tuple(sorted(set(threads)))
        if not ordered:
            return None
        with self.sidecar(transaction=True) as session:
            self._state(session, lock="UPDATE")
            rows = list(
                session.run(
                    """
                    SELECT rotation_cursor
                    FROM taut_search_metadata
                    WHERE singleton = 1
                    """,
                    fetch=True,
                )
            )
            cursor = rows[0][0]
            selected = next(
                (thread for thread in ordered if cursor is None or thread > cursor),
                ordered[0],
            )
            session.run(
                """
                UPDATE taut_search_metadata
                SET rotation_cursor = ?
                WHERE singleton = 1
                """,
                (selected,),
            )
        return selected

    def requires_rebuild(self) -> bool:
        with self.sidecar() as session:
            rows = list(
                session.run(
                    """
                    SELECT initialized
                    FROM taut_search_metadata
                    WHERE singleton = 1
                    """,
                    fetch=True,
                )
            )
        return int(rows[0][0]) != 1

    def begin_rebuild(self, scan_revision: int) -> int:
        with self.sidecar(transaction=True) as session:
            _current_generation, staging = self._state(session, lock="UPDATE")
            if staging is not None:
                self._clear_generation(session, staging[0])
            rows = list(
                session.run(
                    """
                    SELECT next_generation
                    FROM taut_search_metadata
                    WHERE singleton = 1
                    """,
                    fetch=True,
                )
            )
            generation = int(rows[0][0])
            session.run(
                """
                UPDATE taut_search_metadata
                SET staging_generation = ?,
                    staging_scan_revision = ?,
                    next_generation = ?
                WHERE singleton = 1
                """,
                (generation, scan_revision, generation + 1),
            )
        return generation

    def replace_rebuild_document(
        self,
        document: IndexedDocument,
        *,
        generation: int,
        revision: int,
    ) -> bool:
        with self.sidecar(transaction=True) as session:
            _current_generation, staging = self._state(session, lock="UPDATE")
            if staging is None or staging[0] != generation:
                return False
            if revision != staging[1]:
                raise ValueError("rebuild document revision must equal scan revision")
            return self._replace_in_generation(
                session,
                document,
                generation=generation,
                revision=revision,
            )

    def finish_rebuild(self, generation: int) -> None:
        with self.sidecar(transaction=True) as session:
            current_generation, staging = self._state(session, lock="UPDATE")
            if staging is None or staging[0] != generation:
                raise ValueError("search rebuild generation is not active")
            session.run(
                """
                UPDATE taut_search_metadata
                SET current_generation = staging_generation,
                    initialized = 1,
                    staging_generation = NULL,
                    staging_scan_revision = NULL
                WHERE singleton = 1 AND staging_generation = ?
                """,
                (generation,),
            )
            self._clear_generation(session, current_generation)

    def abort_rebuild(self, generation: int) -> None:
        with self.sidecar(transaction=True) as session:
            _current_generation, staging = self._state(session, lock="UPDATE")
            if staging is None or staging[0] != generation:
                return
            self._clear_generation(session, generation)
            session.run(
                """
                UPDATE taut_search_metadata
                SET staging_generation = NULL,
                    staging_scan_revision = NULL
                WHERE singleton = 1 AND staging_generation = ?
                """,
                (generation,),
            )

    def query(
        self,
        chunks: tuple[str, ...],
        *,
        before: int | None = None,
        limit: int,
    ) -> list[SearchCandidate]:
        if not chunks or limit < 1:
            return []
        required_chunk = """
            EXISTS (
                SELECT 1
                FROM taut_search_segments AS s
                WHERE s.generation = d.generation
                  AND s.message_ts = d.message_ts
                  AND s.projection @@ pg_catalog.plainto_tsquery(
                      'pg_catalog.simple'::pg_catalog.regconfig, ?
                  )
            )
        """
        requirements = " AND ".join(required_chunk for _chunk in chunks)
        before_clause = " AND d.message_ts < ?" if before is not None else ""
        statement = f"""
            SELECT d.message_ts, d.thread, d.text_sha256, d.text_bytes
            FROM taut_search_documents AS d
            WHERE d.generation = ?
              AND d.indexed = TRUE
              AND {requirements}{before_clause}
            ORDER BY d.message_ts DESC, d.thread ASC
            LIMIT ?
        """
        with self.sidecar(transaction=True) as session:
            current_generation, _staging = self._state(session, lock="SHARE")
            params: tuple[object, ...] = (current_generation, *chunks)
            if before is not None:
                params = (*params, before)
            rows = session.run(statement, (*params, limit), fetch=True)
            return [
                SearchCandidate(
                    message_ts=int(row[0]),
                    thread=str(row[1]),
                    text_sha256=str(row[2]),
                    text_bytes=int(row[3]),
                )
                for row in rows
            ]

    @staticmethod
    def _state(
        session: SidecarSession,
        *,
        lock: str | None = None,
    ) -> tuple[int, tuple[int, int] | None]:
        lock_clause = "" if lock is None else f" FOR {lock}"
        rows = list(
            session.run(
                """
                SELECT current_generation, staging_generation,
                       staging_scan_revision
                FROM taut_search_metadata
                WHERE singleton = 1
                """
                + lock_clause,
                fetch=True,
            )
        )
        current_generation, staging_generation, scan_revision = rows[0]
        staging = (
            None
            if staging_generation is None
            else (int(staging_generation), int(scan_revision))
        )
        return int(current_generation), staging

    @staticmethod
    def _clear_generation(session: SidecarSession, generation: int) -> None:
        session.run(
            "DELETE FROM taut_search_segments WHERE generation = ?",
            (generation,),
        )
        session.run(
            "DELETE FROM taut_search_documents WHERE generation = ?",
            (generation,),
        )
        session.run(
            "DELETE FROM taut_search_thread_state WHERE generation = ?",
            (generation,),
        )

    def close(self) -> None:
        """The supplied accessor owns all storage resources."""


def create_provider(*, sidecar: SidecarAccessor) -> PostgresSearchProvider:
    """Create a provider without opening or retaining a database connection."""

    return PostgresSearchProvider(sidecar=sidecar)


__all__ = ["create_provider"]
