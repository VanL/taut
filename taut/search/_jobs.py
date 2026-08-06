"""Durable search work-item and claim primitives.

Spec references:
- docs/specs/06-search.md [SRCH-8.1], [SRCH-8.2], [SRCH-9.2]
"""

from __future__ import annotations

import hashlib
import json
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Final, Literal, cast

from simplebroker import Queue
from simplebroker.ext import TimestampError, TimestampGenerator

from taut import addressing
from taut._exceptions import ThreadNameError

PENDING_QUEUE_NAME: Final[str] = "taut.search_index"
CLAIMED_QUEUE_NAME: Final[str] = "taut.search_index.claimed"
FAILED_QUEUE_NAME: Final[str] = "taut.search_index.failed"
CLAIM_TIMEOUT_NS: Final[int] = 60_000_000_000

StructuralErrorCode = Literal[
    "duplicate_field",
    "invalid_entity",
    "invalid_rename",
    "invalid_json",
    "invalid_message_ts",
    "invalid_thread",
    "invalid_version",
    "not_object",
    "unexpected_fields",
]
_ERROR_CODES: Final[frozenset[str]] = frozenset(
    {
        "duplicate_field",
        "invalid_entity",
        "invalid_rename",
        "invalid_json",
        "invalid_message_ts",
        "invalid_thread",
        "invalid_version",
        "not_object",
        "unexpected_fields",
    }
)
_MESSAGE_FIELDS: Final[frozenset[str]] = frozenset(
    {"entity", "message_ts", "thread", "v"}
)
_RENAME_FIELDS: Final[frozenset[str]] = frozenset(
    {"affected", "entity", "new", "old", "v"}
)
_CLAIMS_DDL: Final[str] = """
CREATE TABLE IF NOT EXISTS taut_search_claims (
    job_ts     BIGINT PRIMARY KEY,
    claimed_at BIGINT NOT NULL,
    claimed_unix_ns BIGINT NOT NULL,
    worker_id  TEXT NOT NULL,
    lease_id   TEXT NOT NULL UNIQUE,
    phase      TEXT NOT NULL
)
"""
_HOUSEKEEPING_DDL: Final[str] = """
CREATE TABLE IF NOT EXISTS taut_search_housekeeping (
    key   TEXT PRIMARY KEY,
    value BIGINT NOT NULL
)
"""


class MalformedSearchJob(ValueError):
    """A work body failed the closed version-one structural contract."""

    def __init__(self, code: StructuralErrorCode) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class MessageJob:
    """Content-free invalidation for one canonical source message."""

    message_ts: int
    thread: str


@dataclass(frozen=True, slots=True)
class ThreadRenameJob:
    """Content-free completed channel/subthread rename invalidation."""

    old: str
    new: str
    affected: tuple[tuple[str, str], ...]


SearchJob = MessageJob | ThreadRenameJob


@dataclass(frozen=True, slots=True)
class ClaimedJob:
    """One exactly moved work row plus its durable lease evidence."""

    body: str
    job_ts: int
    claimed_at: int
    claimed_unix_ns: int
    worker_id: str
    lease_id: str


@dataclass(frozen=True, slots=True)
class _ClaimRow:
    claimed_at: int
    claimed_unix_ns: int
    worker_id: str
    lease_id: str
    phase: str


def encode_message_job(*, message_ts: int, thread: str) -> str:
    """Encode the exact single-line version-one message work shape."""

    job = MessageJob(
        message_ts=_validate_message_ts(message_ts),
        thread=_validate_source_thread(thread),
    )
    return json.dumps(
        {
            "entity": "message",
            "message_ts": job.message_ts,
            "thread": job.thread,
            "v": 1,
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def decode_message_job(body: str) -> MessageJob:
    """Decode one strict message job or raise a bounded structural code."""

    if not isinstance(body, str):
        raise TypeError("search job body must be a string")
    try:
        value = json.loads(body, object_pairs_hook=_unique_object)
    except MalformedSearchJob:
        raise
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise MalformedSearchJob("invalid_json") from exc
    if not isinstance(value, dict):
        raise MalformedSearchJob("not_object")
    if frozenset(value) != _MESSAGE_FIELDS:
        raise MalformedSearchJob("unexpected_fields")
    if type(value["v"]) is not int or value["v"] != 1:
        raise MalformedSearchJob("invalid_version")
    if value["entity"] != "message":
        raise MalformedSearchJob("invalid_entity")
    try:
        message_ts = _validate_message_ts(value["message_ts"])
    except (TypeError, ValueError) as exc:
        raise MalformedSearchJob("invalid_message_ts") from exc
    try:
        thread = _validate_source_thread(value["thread"])
    except (TypeError, ValueError) as exc:
        raise MalformedSearchJob("invalid_thread") from exc
    return MessageJob(message_ts=message_ts, thread=thread)


def encode_thread_rename_job(
    *,
    old: str,
    new: str,
    affected: list[dict[str, str]],
) -> str:
    old_name = _validate_rename_thread(old)
    new_name = _validate_rename_thread(new)
    pairs = _validate_affected(affected)
    if pairs[0] != (old_name, new_name):
        raise ValueError("first affected rename must match old/new")
    return json.dumps(
        {
            "affected": [
                {"new": new_name, "old": old_name} for old_name, new_name in pairs
            ],
            "entity": "thread_rename",
            "new": new_name,
            "old": old_name,
            "v": 1,
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def decode_thread_rename_job(body: str) -> ThreadRenameJob:
    """Decode one strict completed-rename invalidation."""

    if not isinstance(body, str):
        raise TypeError("search job body must be a string")
    try:
        value = json.loads(body, object_pairs_hook=_unique_object)
    except MalformedSearchJob:
        raise
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise MalformedSearchJob("invalid_json") from exc
    if not isinstance(value, dict):
        raise MalformedSearchJob("not_object")
    if frozenset(value) != _RENAME_FIELDS:
        raise MalformedSearchJob("unexpected_fields")
    if type(value["v"]) is not int or value["v"] != 1:
        raise MalformedSearchJob("invalid_version")
    if value["entity"] != "thread_rename":
        raise MalformedSearchJob("invalid_entity")
    try:
        old = _validate_rename_thread(value["old"])
        new = _validate_rename_thread(value["new"])
        pairs = _validate_affected(value["affected"])
        if pairs[0] != (old, new):
            raise ValueError("first affected rename must match old/new")
    except (TypeError, ValueError) as exc:
        raise MalformedSearchJob("invalid_rename") from exc
    return ThreadRenameJob(old=old, new=new, affected=pairs)


def decode_search_job(body: str) -> SearchJob:
    """Dispatch one closed version-one work entity to its strict decoder."""

    if not isinstance(body, str):
        raise TypeError("search job body must be a string")
    try:
        value = json.loads(body, object_pairs_hook=_unique_object)
    except MalformedSearchJob:
        raise
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise MalformedSearchJob("invalid_json") from exc
    if not isinstance(value, dict):
        raise MalformedSearchJob("not_object")
    if value.get("entity") == "thread_rename":
        return decode_thread_rename_job(body)
    return decode_message_job(body)


def sanitized_failure_body(
    body: str,
    *,
    original_job_ts: int,
    error_code: str,
) -> str:
    """Return content-free diagnostic JSON for one malformed claimed body."""

    if not isinstance(body, str):
        raise TypeError("search job body must be a string")
    if error_code not in _ERROR_CODES:
        raise ValueError("unknown search job structural error code")
    encoded = body.encode("utf-8")
    return json.dumps(
        {
            "error": error_code,
            "original_job_ts": _validate_message_ts(original_job_ts),
            "sha256": hashlib.sha256(encoded).hexdigest(),
            "utf8_bytes": len(encoded),
            "v": 1,
        },
        separators=(",", ":"),
        sort_keys=True,
    )


@dataclass(slots=True)
class JobQueues:
    """Caller-owned queues plus search-owned durable lease metadata."""

    pending: Queue
    claimed: Queue
    failed: Queue
    meta: Queue
    worker_id: str = field(default_factory=lambda: secrets.token_hex(16))
    clock_ns: Callable[[], int] = time.time_ns

    def ensure_schema(self) -> None:
        with self.meta.sidecar(transaction=True) as session:
            session.run(_CLAIMS_DDL)
            session.run(_HOUSEKEEPING_DDL)

    def enqueue_message(self, *, message_ts: int, thread: str) -> int:
        return self.pending.write(
            encode_message_job(message_ts=message_ts, thread=thread)
        )

    def claim_one(self, *, exact_timestamp: int | None = None) -> ClaimedJob | None:
        """Atomically move one pending row, then publish a fresh lease."""

        moved = self.pending.move_one(
            self.claimed,
            exact_timestamp=exact_timestamp,
            with_timestamps=True,
        )
        if moved is None:
            return None
        body, job_ts = cast(tuple[str, int], moved)
        claimed_at = self.meta.generate_timestamp()
        claimed_unix_ns = self.clock_ns()
        lease_id = secrets.token_hex(16)
        if not self._publish_claim(
            job_ts=job_ts,
            claimed_at=claimed_at,
            claimed_unix_ns=claimed_unix_ns,
            worker_id=self.worker_id,
            lease_id=lease_id,
        ):
            return None
        return ClaimedJob(
            body=body,
            job_ts=job_ts,
            claimed_at=claimed_at,
            claimed_unix_ns=claimed_unix_ns,
            worker_id=self.worker_id,
            lease_id=lease_id,
        )

    def work_frontier(self) -> int | None:
        """Capture the greatest pending or claimed job ID currently visible."""

        latest: int | None = None
        for queue in (self.pending, self.claimed):
            after: int | None = None
            while True:
                rows = cast(
                    list[tuple[str, int]],
                    queue.peek_many(
                        1000,
                        with_timestamps=True,
                        after_timestamp=after,
                    ),
                )
                if not rows:
                    break
                latest = max(latest or 0, rows[-1][1])
                after = rows[-1][1]
        return latest

    def pending_ids_through(self, frontier: int) -> tuple[int, ...]:
        """Snapshot pending job IDs no newer than ``frontier``."""

        return tuple(
            job_ts for _body, job_ts in self._queue_rows_through(self.pending, frontier)
        )

    def claimed_rows_through(self, frontier: int) -> tuple[tuple[str, int], ...]:
        """Snapshot claimed bodies no newer than ``frontier`` for read-through."""

        return self._queue_rows_through(self.claimed, frontier)

    @staticmethod
    def _queue_rows_through(
        queue: Queue,
        frontier: int,
    ) -> tuple[tuple[str, int], ...]:
        rows: list[tuple[str, int]] = []
        after: int | None = None
        while True:
            page = cast(
                list[tuple[str, int]],
                queue.peek_many(
                    1000,
                    with_timestamps=True,
                    after_timestamp=after,
                    before_timestamp=frontier + 1,
                ),
            )
            if not page:
                break
            rows.extend(page)
            after = page[-1][1]
        return tuple(rows)

    def lease_matches(self, job_ts: int, lease_id: str) -> bool:
        row = self._claim_row(job_ts)
        return row is not None and secrets.compare_digest(row.lease_id, lease_id)

    def remove_claim_if_lease(self, job_ts: int, lease_id: str) -> bool:
        """Delete claim metadata only when the caller still owns its lease."""

        with self.meta.sidecar(transaction=True) as session:
            rows = list(
                session.run(
                    """
                    DELETE FROM taut_search_claims
                    WHERE job_ts = ? AND lease_id = ?
                    RETURNING 1
                    """,
                    (job_ts, lease_id),
                    fetch=True,
                )
            )
        return bool(rows)

    def acknowledge(self, job_ts: int, lease_id: str) -> bool:
        """Make committed work terminal, then exact-delete its claimed row."""

        if not self._mark_terminal(job_ts, lease_id):
            return False
        deleted = self.claimed.delete(message_id=job_ts)
        self.remove_claim_if_lease(job_ts, lease_id)
        return deleted

    def reclaim_expired(
        self, *, now: int | None = None, limit: int = 1000
    ) -> list[int]:
        """Return missing-lease or expired rows to pending without sleeps."""

        if now is None:
            now = self.clock_ns()
        if isinstance(now, bool) or not isinstance(now, int):
            raise TypeError("now must be an integer timestamp")
        if isinstance(limit, bool) or not isinstance(limit, int):
            raise TypeError("limit must be an integer")
        if limit < 1:
            raise ValueError("limit must be positive")
        rows = cast(
            list[tuple[str, int]],
            self.claimed.peek_many(limit, with_timestamps=True),
        )
        reclaimed: list[int] = []
        for _body, job_ts in rows:
            if self._recover_claimed_job(job_ts=job_ts, now=now):
                reclaimed.append(job_ts)
        self.cleanup_orphan_claims(limit=limit)
        return reclaimed

    def _recover_claimed_job(self, *, job_ts: int, now: int) -> bool:
        claim = self._claim_row(job_ts)
        if claim is None:
            return self._move_claimed_to_pending(job_ts)
        if claim.phase == "terminal":
            self.claimed.delete(message_id=job_ts)
            self.remove_claim_if_lease(job_ts, claim.lease_id)
            return False
        if claim.phase == "active" and not _claim_expired(
            claimed_unix_ns=claim.claimed_unix_ns,
            now=now,
        ):
            return False
        if claim.phase == "active" and not self._mark_reclaiming(job_ts, claim):
            return False
        moved = self._move_claimed_to_pending(job_ts)
        self.remove_claim_if_lease(job_ts, claim.lease_id)
        return moved

    def quarantine(self, claim: ClaimedJob, *, error_code: str) -> bool:
        """Write sanitized failure evidence before deleting malformed work."""

        if not self.lease_matches(claim.job_ts, claim.lease_id):
            return False
        failure = sanitized_failure_body(
            claim.body,
            original_job_ts=claim.job_ts,
            error_code=error_code,
        )
        self.failed.write(failure)
        if not self._mark_terminal(claim.job_ts, claim.lease_id):
            return False
        deleted = self.claimed.delete(message_id=claim.job_ts)
        self.remove_claim_if_lease(claim.job_ts, claim.lease_id)
        return deleted

    def cleanup_orphan_claims(self, *, limit: int = 1000) -> list[int]:
        """Remove lease rows whose claimed queue row no longer exists."""

        cursor = self._housekeeping_cursor("claim_cleanup")
        rows = self._claim_cleanup_page(after=cursor, limit=limit)
        if not rows and cursor:
            cursor = 0
            rows = self._claim_cleanup_page(after=cursor, limit=limit)
        if rows:
            self._set_housekeeping_cursor("claim_cleanup", int(rows[-1][0]))
        elif cursor:
            self._set_housekeeping_cursor("claim_cleanup", 0)
        removed: list[int] = []
        for raw_job_ts, raw_lease_id in rows:
            job_ts = int(raw_job_ts)
            if self.claimed.peek_one(exact_timestamp=job_ts) is not None:
                continue
            if self.remove_claim_if_lease(job_ts, str(raw_lease_id)):
                removed.append(job_ts)
        return removed

    def _claim_cleanup_page(self, *, after: int, limit: int) -> list[tuple[Any, ...]]:
        with self.meta.sidecar() as session:
            return list(
                session.run(
                    """
                    SELECT job_ts, lease_id
                    FROM taut_search_claims
                    WHERE job_ts > ?
                    ORDER BY job_ts
                    LIMIT ?
                    """,
                    (after, limit),
                    fetch=True,
                )
            )

    def _housekeeping_cursor(self, key: str) -> int:
        with self.meta.sidecar() as session:
            rows = list(
                session.run(
                    "SELECT value FROM taut_search_housekeeping WHERE key = ?",
                    (key,),
                    fetch=True,
                )
            )
        return 0 if not rows else int(rows[0][0])

    def _set_housekeeping_cursor(self, key: str, value: int) -> None:
        with self.meta.sidecar(transaction=True) as session:
            session.run(
                """
                INSERT INTO taut_search_housekeeping (key, value)
                VALUES (?, ?)
                ON CONFLICT (key) DO UPDATE SET value = excluded.value
                """,
                (key, value),
            )

    def _publish_claim(
        self,
        *,
        job_ts: int,
        claimed_at: int,
        claimed_unix_ns: int,
        worker_id: str,
        lease_id: str,
    ) -> bool:
        """Publish only into an empty claim slot; a late mover never wins."""

        with self.meta.sidecar(transaction=True) as session:
            rows = list(
                session.run(
                    """
                    INSERT INTO taut_search_claims (
                        job_ts, claimed_at, claimed_unix_ns,
                        worker_id, lease_id, phase
                    ) VALUES (?, ?, ?, ?, ?, 'active')
                    ON CONFLICT (job_ts) DO NOTHING
                    RETURNING 1
                    """,
                    (job_ts, claimed_at, claimed_unix_ns, worker_id, lease_id),
                    fetch=True,
                )
            )
        return bool(rows)

    def _mark_terminal(self, job_ts: int, lease_id: str) -> bool:
        """CAS active work into a state recovery will only acknowledge."""

        with self.meta.sidecar(transaction=True) as session:
            rows = list(
                session.run(
                    """
                    UPDATE taut_search_claims
                    SET phase = 'terminal'
                    WHERE job_ts = ?
                      AND lease_id = ?
                      AND phase IN ('active', 'terminal')
                    RETURNING 1
                    """,
                    (job_ts, lease_id),
                    fetch=True,
                )
            )
        return bool(rows)

    def _mark_reclaiming(self, job_ts: int, claim: _ClaimRow) -> bool:
        with self.meta.sidecar(transaction=True) as session:
            rows = list(
                session.run(
                    """
                    UPDATE taut_search_claims
                    SET phase = 'reclaiming'
                    WHERE job_ts = ?
                      AND lease_id = ?
                      AND phase = 'active'
                      AND claimed_at = ?
                    RETURNING 1
                    """,
                    (job_ts, claim.lease_id, claim.claimed_at),
                    fetch=True,
                )
            )
        return bool(rows)

    def _move_claimed_to_pending(self, job_ts: int) -> bool:
        moved = self.claimed.move_one(
            self.pending,
            exact_timestamp=job_ts,
            with_timestamps=True,
        )
        return moved is not None

    def _claim_row(self, job_ts: int) -> _ClaimRow | None:
        with self.meta.sidecar() as session:
            rows = list(
                session.run(
                    """
                    SELECT claimed_at, claimed_unix_ns, worker_id, lease_id, phase
                    FROM taut_search_claims
                    WHERE job_ts = ?
                    """,
                    (job_ts,),
                    fetch=True,
                )
            )
        if not rows:
            return None
        row = rows[0]
        return _ClaimRow(
            claimed_at=int(row[0]),
            claimed_unix_ns=int(row[1]),
            worker_id=str(row[2]),
            lease_id=str(row[3]),
            phase=str(row[4]),
        )


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise MalformedSearchJob("duplicate_field")
        value[key] = item
    return value


def _validate_message_ts(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("message_ts must be an integer")
    try:
        return TimestampGenerator.validate(str(value), exact=True)
    except TimestampError as exc:
        raise ValueError("message_ts must be a full message id") from exc


def _validate_source_thread(value: object) -> str:
    if not isinstance(value, str):
        raise TypeError("thread must be a string")
    if value.startswith("dm."):
        if addressing.DM_SELECTOR_RE.fullmatch(value) is None:
            raise ValueError("invalid direct-message thread")
        return value
    return _validate_rename_thread(value)


def _validate_rename_thread(value: object) -> str:
    if not isinstance(value, str):
        raise TypeError("thread must be a string")
    try:
        validated = addressing.validate_chat_thread_name(
            value,
            allow_subthread=True,
        )
    except ThreadNameError as exc:
        raise ValueError("invalid search thread") from exc
    if validated != value:
        raise ValueError("thread must be canonical")
    return value


def _validate_affected(value: object) -> tuple[tuple[str, str], ...]:
    if not isinstance(value, list) or not value:
        raise TypeError("affected must be a non-empty list")
    pairs: list[tuple[str, str]] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, dict) or frozenset(item) != {"old", "new"}:
            raise ValueError("affected entries require exact old/new fields")
        old = _validate_rename_thread(item["old"])
        new = _validate_rename_thread(item["new"])
        if old in seen:
            raise ValueError("affected old names must be unique")
        seen.add(old)
        pairs.append((old, new))
    return tuple(pairs)


def _claim_expired(*, claimed_unix_ns: int, now: int) -> bool:
    return now - claimed_unix_ns >= CLAIM_TIMEOUT_NS


__all__ = [
    "CLAIMED_QUEUE_NAME",
    "CLAIM_TIMEOUT_NS",
    "FAILED_QUEUE_NAME",
    "PENDING_QUEUE_NAME",
    "ClaimedJob",
    "JobQueues",
    "MalformedSearchJob",
    "MessageJob",
    "SearchJob",
    "ThreadRenameJob",
    "decode_message_job",
    "decode_search_job",
    "decode_thread_rename_job",
    "encode_message_job",
    "encode_thread_rename_job",
    "sanitized_failure_body",
]
