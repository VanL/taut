"""Built-in SQLite FTS5 provider using only a supplied sidecar accessor.

Spec references:
- docs/specs/06-search.md [SRCH-2.1], [SRCH-6], [SRCH-7], [SRCH-11.1]
"""

from __future__ import annotations

from dataclasses import dataclass

from simplebroker.ext import OperationalError, SidecarSession

from taut.search._provider import (
    IndexedDocument,
    SearchCandidate,
    SidecarAccessor,
    ThreadWatermark,
)


class SQLiteSearchUnavailableError(RuntimeError):
    """The active Python SQLite runtime does not provide FTS5."""


_SCHEMA_VERSION = 1
_PROJECTION_VERSION = 1
_FTS_TABLES = ("taut_search_fts", "taut_search_fts_staging")

_METADATA_DDL = """
    CREATE TABLE IF NOT EXISTS taut_search_metadata (
        singleton             BIGINT PRIMARY KEY CHECK (singleton = 1),
        schema_version        BIGINT NOT NULL,
        projection_version    BIGINT NOT NULL,
        current_generation    BIGINT NOT NULL,
        current_slot          BIGINT NOT NULL CHECK (current_slot IN (0, 1)),
        staging_generation    BIGINT,
        staging_slot          BIGINT CHECK (staging_slot IN (0, 1)),
        staging_scan_revision BIGINT,
        next_generation       BIGINT NOT NULL,
        initialized           BIGINT NOT NULL,
        rotation_cursor       TEXT,
        CHECK (
            (staging_generation IS NULL
             AND staging_slot IS NULL
             AND staging_scan_revision IS NULL)
            OR
            (staging_generation IS NOT NULL
             AND staging_slot IS NOT NULL
             AND staging_scan_revision IS NOT NULL
             AND staging_slot <> current_slot)
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
        indexed            BIGINT NOT NULL,
        PRIMARY KEY (generation, message_ts)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS taut_search_segments (
        segment_rowid INTEGER PRIMARY KEY AUTOINCREMENT,
        generation    BIGINT NOT NULL,
        message_ts    BIGINT NOT NULL,
        segment_index BIGINT NOT NULL,
        fts_slot      BIGINT NOT NULL CHECK (fts_slot IN (0, 1)),
        UNIQUE (generation, message_ts, segment_index)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS taut_search_segments_message_idx
        ON taut_search_segments (generation, message_ts)
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


def _fts_ddl(table: str) -> str:
    return f"""
        CREATE VIRTUAL TABLE IF NOT EXISTS {table} USING fts5(
            projection,
            content='',
            tokenize='unicode61 remove_diacritics 2'
        )
    """


@dataclass(slots=True)
class SQLiteSearchProvider:
    """Contentless FTS5 index whose storage lifetime is owned by core."""

    sidecar: SidecarAccessor

    def ensure_schema(self) -> None:
        try:
            with self.sidecar(transaction=True) as session:
                session.run(_METADATA_DDL)
                session.run(
                    """
                    INSERT OR IGNORE INTO taut_search_metadata (
                        singleton, schema_version, projection_version,
                        current_generation, current_slot, next_generation,
                        initialized
                    ) VALUES (1, ?, ?, 1, 0, 2, 0)
                    """,
                    (_SCHEMA_VERSION, _PROJECTION_VERSION),
                )
                version_rows = list(
                    session.run(
                        """
                        SELECT schema_version, projection_version
                        FROM taut_search_metadata
                        WHERE singleton = 1
                        """,
                        fetch=True,
                    )
                )
                schema_version, projection_version = map(int, version_rows[0])
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
                for table in _FTS_TABLES:
                    session.run(_fts_ddl(table))
        except OperationalError as exc:
            if "no such module: fts5" not in str(exc).casefold():
                raise
            raise SQLiteSearchUnavailableError(
                "SQLite FTS5 search is unavailable in this Python runtime"
            ) from exc

    def replace_document(
        self,
        document: IndexedDocument,
        *,
        revision: int | None = None,
    ) -> bool:
        """Replace live mappings while allowing stale contentless postings."""

        effective_revision = document.message_ts if revision is None else revision
        with self.sidecar(transaction=True) as session:
            current_generation, current_slot, staging = self._state(session)
            applied = self._replace_in_generation(
                session,
                document,
                generation=current_generation,
                slot=current_slot,
                revision=effective_revision,
            )
            if staging is not None:
                staging_generation, staging_slot, scan_revision = staging
                if effective_revision >= scan_revision:
                    self._replace_in_generation(
                        session,
                        document,
                        generation=staging_generation,
                        slot=staging_slot,
                        revision=effective_revision,
                    )
        return applied

    def _replace_in_generation(
        self,
        session: SidecarSession,
        document: IndexedDocument,
        *,
        generation: int,
        slot: int,
        revision: int,
    ) -> bool:
        applied = list(
            session.run(
                """
                INSERT INTO taut_search_documents (
                    generation, message_ts, thread, text_sha256, text_bytes,
                    projection_version, latest_revision, indexed
                ) VALUES (?, ?, ?, ?, ?, 1, ?, 1)
                ON CONFLICT (generation, message_ts) DO UPDATE SET
                    thread = excluded.thread,
                    text_sha256 = excluded.text_sha256,
                    text_bytes = excluded.text_bytes,
                    projection_version = excluded.projection_version,
                    latest_revision = excluded.latest_revision,
                    indexed = 1
                WHERE excluded.latest_revision >= taut_search_documents.latest_revision
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
        fts_table = _FTS_TABLES[slot]
        for segment_index, projection in enumerate(document.segments):
            rows = list(
                session.run(
                    """
                    INSERT INTO taut_search_segments (
                        generation, message_ts, segment_index, fts_slot
                    ) VALUES (?, ?, ?, ?)
                    RETURNING segment_rowid
                    """,
                    (generation, document.message_ts, segment_index, slot),
                    fetch=True,
                )
            )
            segment_rowid = int(rows[0][0])
            session.run(
                f"""
                INSERT INTO {fts_table} (rowid, projection)
                VALUES (?, ?)
                """,
                (segment_rowid, projection),
            )
        return True

    def delete_document(
        self,
        *,
        message_ts: int,
        thread: str,
        revision: int,
    ) -> bool:
        """Conditionally retain a revision tombstone and remove live mappings."""

        with self.sidecar(transaction=True) as session:
            current_generation, _current_slot, staging = self._state(session)
            applied = self._delete_in_generation(
                session,
                message_ts=message_ts,
                thread=thread,
                generation=current_generation,
                revision=revision,
            )
            if staging is not None:
                staging_generation, _staging_slot, scan_revision = staging
                if revision >= scan_revision:
                    self._delete_in_generation(
                        session,
                        message_ts=message_ts,
                        thread=thread,
                        generation=staging_generation,
                        revision=revision,
                    )
        return applied

    def _delete_in_generation(
        self,
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
                    INSERT INTO taut_search_documents (
                        generation, message_ts, thread, text_sha256, text_bytes,
                        projection_version, latest_revision, indexed
                    ) VALUES (?, ?, ?, '', 0, 1, ?, 0)
                    ON CONFLICT (generation, message_ts) DO UPDATE SET
                        thread = excluded.thread,
                        text_sha256 = '',
                        text_bytes = 0,
                        projection_version = excluded.projection_version,
                        latest_revision = excluded.latest_revision,
                        indexed = 0
                    WHERE excluded.latest_revision
                          >= taut_search_documents.latest_revision
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
        with self.sidecar() as session:
            current_generation, _current_slot, _staging = self._state(session)
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

        with self.sidecar(transaction=True) as session:
            if not affected:
                return
            current_generation, _current_slot, staging = self._state(session)
            self._retarget_generation(
                session,
                affected,
                generation=current_generation,
                revision=revision,
            )
            if staging is not None:
                staging_generation, _staging_slot, _scan_revision = staging
                self._retarget_generation(
                    session,
                    affected,
                    generation=staging_generation,
                    revision=revision,
                )

    def thread_watermark(self, thread: str) -> ThreadWatermark:
        """Return whether a current-generation source frontier is known."""

        with self.sidecar() as session:
            current_generation, _current_slot, _staging = self._state(session)
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

        with self.sidecar() as session:
            current_generation, _current_slot, _staging = self._state(session)
            rows = session.run(
                """
                SELECT message_ts
                FROM taut_search_documents
                WHERE generation = ? AND thread = ? AND indexed = 1
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
            current_generation, _current_slot, _staging = self._state(session)
            rows = list(
                session.run(
                    """
                    INSERT INTO taut_search_thread_state (
                        generation, thread, watermark, latest_revision
                    ) VALUES (?, ?, ?, ?)
                    ON CONFLICT (generation, thread) DO UPDATE SET
                        watermark = excluded.watermark,
                        latest_revision = excluded.latest_revision
                    WHERE excluded.latest_revision
                          >= taut_search_thread_state.latest_revision
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
        """Publish one writable staging generation without holding the scan open."""

        with self.sidecar(transaction=True) as session:
            current_generation, current_slot, staging = self._state(session)
            if staging is not None:
                old_generation, old_slot, _old_revision = staging
                self._clear_generation(session, old_generation, old_slot)
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
            staging_slot = 1 - current_slot
            self._reset_fts_slot(session, staging_slot)
            session.run(
                """
                UPDATE taut_search_metadata
                SET staging_generation = ?,
                    staging_slot = ?,
                    staging_scan_revision = ?,
                    next_generation = ?
                WHERE singleton = 1
                  AND current_generation = ?
                """,
                (
                    generation,
                    staging_slot,
                    scan_revision,
                    generation + 1,
                    current_generation,
                ),
            )
        return generation

    def replace_rebuild_document(
        self,
        document: IndexedDocument,
        *,
        generation: int,
        revision: int,
    ) -> bool:
        """Conditionally populate only the caller's active staging generation."""

        with self.sidecar(transaction=True) as session:
            _current_generation, _current_slot, staging = self._state(session)
            if staging is None or staging[0] != generation:
                return False
            _staging_generation, staging_slot, scan_revision = staging
            if revision != scan_revision:
                raise ValueError("rebuild document revision must equal scan revision")
            return self._replace_in_generation(
                session,
                document,
                generation=generation,
                slot=staging_slot,
                revision=revision,
            )

    def finish_rebuild(self, generation: int) -> None:
        """Atomically publish staging and compact the now-inactive FTS slot."""

        with self.sidecar(transaction=True) as session:
            current_generation, current_slot, staging = self._state(session)
            if staging is None or staging[0] != generation:
                raise ValueError("search rebuild generation is not active")
            _staging_generation, _staging_slot, _scan_revision = staging
            session.run(
                """
                UPDATE taut_search_metadata
                SET current_generation = staging_generation,
                    current_slot = staging_slot,
                    initialized = 1,
                    staging_generation = NULL,
                    staging_slot = NULL,
                    staging_scan_revision = NULL
                WHERE singleton = 1 AND staging_generation = ?
                """,
                (generation,),
            )
            self._clear_generation(session, current_generation, current_slot)

    def abort_rebuild(self, generation: int) -> None:
        """Discard matching staging state while preserving the current index."""

        with self.sidecar(transaction=True) as session:
            _current_generation, _current_slot, staging = self._state(session)
            if staging is None or staging[0] != generation:
                return
            staging_generation, staging_slot, _scan_revision = staging
            self._clear_generation(session, staging_generation, staging_slot)
            session.run(
                """
                UPDATE taut_search_metadata
                SET staging_generation = NULL,
                    staging_slot = NULL,
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
        """Return candidates containing every supplied safe query chunk."""

        if not chunks or limit < 1:
            return []
        matches: dict[int, SearchCandidate] | None = None
        with self.sidecar() as session:
            current_generation, current_slot, _staging = self._state(session)
            fts_table = _FTS_TABLES[current_slot]
            for chunk in chunks:
                expression = f'"{chunk.replace(chr(34), chr(34) * 2)}"'
                rows = session.run(
                    f"""
                    SELECT d.message_ts, d.thread, d.text_sha256, d.text_bytes
                    FROM {fts_table} AS f
                    JOIN taut_search_segments AS s
                      ON s.segment_rowid = f.rowid
                    JOIN taut_search_documents AS d
                      ON d.generation = s.generation
                     AND d.message_ts = s.message_ts
                    WHERE {fts_table} MATCH ?
                      AND s.generation = ?
                      AND s.fts_slot = ?
                      AND d.indexed = 1
                    """,
                    (expression, current_generation, current_slot),
                    fetch=True,
                )
                current = {
                    int(row[0]): SearchCandidate(
                        message_ts=int(row[0]),
                        thread=str(row[1]),
                        text_sha256=str(row[2]),
                        text_bytes=int(row[3]),
                    )
                    for row in rows
                }
                if matches is None:
                    matches = current
                else:
                    matches = {
                        message_ts: candidate
                        for message_ts, candidate in matches.items()
                        if message_ts in current
                    }
                if not matches:
                    return []
        assert matches is not None
        candidates = (
            candidate
            for candidate in matches.values()
            if before is None or candidate.message_ts < before
        )
        return sorted(
            candidates,
            key=lambda candidate: (-candidate.message_ts, candidate.thread),
        )[:limit]

    @staticmethod
    def _state(
        session: SidecarSession,
    ) -> tuple[int, int, tuple[int, int, int] | None]:
        rows = list(
            session.run(
                """
                SELECT current_generation, current_slot,
                       staging_generation, staging_slot, staging_scan_revision
                FROM taut_search_metadata
                WHERE singleton = 1
                """,
                fetch=True,
            )
        )
        current_generation, current_slot, staging_generation, staging_slot, revision = (
            rows[0]
        )
        staging = (
            None
            if staging_generation is None
            else (int(staging_generation), int(staging_slot), int(revision))
        )
        return int(current_generation), int(current_slot), staging

    @staticmethod
    def _reset_fts_slot(session: SidecarSession, slot: int) -> None:
        table = _FTS_TABLES[slot]
        session.run(f"DROP TABLE IF EXISTS {table}")
        session.run(_fts_ddl(table))

    def _clear_generation(
        self,
        session: SidecarSession,
        generation: int,
        slot: int,
    ) -> None:
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
        self._reset_fts_slot(session, slot)

    def close(self) -> None:
        """The supplied accessor owns all storage resources."""
