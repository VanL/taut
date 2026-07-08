"""Summon session ledger and single-driver guard over sidecar SQL.

All summon-owned SQL lives in this module, mirroring core's
``taut/state/_sql.py`` shapes: ``CREATE TABLE IF NOT EXISTS`` inside
``Queue.sidecar(transaction=True)``, qmark parameters only, and
single-transaction read-modify-write for every mutation.

The ledger is split by lifetime per [SUM-8]:

- ``taut_summon_claims`` — transient. One row per in-flight bootstrap,
  keyed ``(name, provider)`` (the concurrent-summon serialization point,
  [SUM-4] step 0). Rows are deleted at bootstrap step 3; a row whose
  driver evidence is dead is reclaimable.
- ``taut_summon_sessions`` — durable. One row per summoned member, keyed
  ``member_id`` (created only after the member exists). Names never key
  durable state ([SUM-8]): callers resolve the current name through core
  to a member_id first.

Versioning rides the shared ``taut_meta`` table under the extension-owned
``summon_schema_version`` key, with core's fail-closed gate shape: a
newer stored version refuses to run (upgrade taut-summon), an older one
refuses too (recreate the development database). Core's own
``schema_version`` key is never read or written here.

Single-driver guard ([SUM-8]): driver evidence is pid + start-time,
live-checked the same way presence does (``taut.identity`` — a blessed
extension surface per [SUM-4]). Guard semantics, applied by both
``claim_name`` and ``claim_driver``:

- evidence provably live (pid exists, start-time matches) → refuse,
  always. ``--takeover`` replaces a dead or abandoned claim, never a
  live driver (two drivers as one member would double-speak).
- evidence provably dead (pid gone, or start-time mismatch) → reclaim
  without ceremony ([SUM-11]: a stale claim is reclaimable by evidence,
  so a plain restart works after a driver crash).
- evidence unverifiable (process exists but its start-time cannot be
  read) → fail closed unless ``takeover=True`` (the "abandoned" case
  [SUM-8] gives ``--takeover`` for).

Spec references:
- docs/specs/04-summon.md [SUM-8], [SUM-11], [SUM-4]
- docs/specs/02-taut-core.md [TAUT-3.3] (sidecar table rules)
"""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any, Literal, TypedDict, TypeVar, cast

from simplebroker import Queue
from simplebroker.ext import DatabaseError, IntegrityError, SidecarSession

from taut.identity import capture_process
from taut_summon._broker_retry import broker_retry

SUMMON_SCHEMA_VERSION = 2
SUMMON_SCHEMA_VERSION_KEY = "summon_schema_version"

_META_DDL = """
CREATE TABLE IF NOT EXISTS taut_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
)
"""

_DDL: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS taut_summon_claims (
        name              TEXT NOT NULL,
        provider          TEXT NOT NULL,
        driver_pid        BIGINT NOT NULL,
        driver_start_time TEXT NOT NULL,
        claimed_ts        BIGINT NOT NULL,
        PRIMARY KEY (name, provider)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS taut_summon_sessions (
        member_id           TEXT PRIMARY KEY,
        token               TEXT NOT NULL,
        provider            TEXT NOT NULL,
        provider_session_id TEXT,
        driver_pid          BIGINT,
        driver_start_time   TEXT,
        wired               INTEGER NOT NULL DEFAULT 0,
        updated_ts          BIGINT NOT NULL
    )
    """,
)


T = TypeVar("T")


def _state_retry(fn: Callable[[], T], *, what: str) -> T:
    return broker_retry(fn, what=f"summon state {what}")


class SummonStateError(Exception):
    """Base error for summon ledger operations."""


class SummonSchemaVersionError(SummonStateError):
    """The stored summon schema version is incompatible with this package."""


class ClaimConflictError(SummonStateError):
    """A live or unverifiable bootstrap claim already holds (name, provider)."""


class DriverConflictError(SummonStateError):
    """A live or unverifiable driver already holds the session row."""


class SummonClaimRow(TypedDict):
    """One transient bootstrap claim."""

    name: str
    provider: str
    driver_pid: int
    driver_start_time: str
    claimed_ts: int


class SummonSessionRow(TypedDict):
    """One durable summoned-member session."""

    member_id: str
    token: str
    provider: str
    provider_session_id: str | None
    driver_pid: int | None
    driver_start_time: str | None
    wired: bool
    updated_ts: int


def ensure_summon_schema(queue: Queue) -> None:
    """Install or validate the summon sidecar schema (fail-closed gate)."""

    def _op() -> None:
        with queue.sidecar(transaction=True) as session:
            session.run(_META_DDL)
            row = _one(
                session,
                "SELECT value FROM taut_meta WHERE key = ?",
                (SUMMON_SCHEMA_VERSION_KEY,),
            )
            if row is not None:
                version = int(row[0])
                if version > SUMMON_SCHEMA_VERSION:
                    raise SummonSchemaVersionError(
                        f"summon schema version {version} is newer than supported "
                        f"version {SUMMON_SCHEMA_VERSION}; upgrade taut-summon"
                    )
                if version < SUMMON_SCHEMA_VERSION:
                    raise SummonSchemaVersionError(
                        f"summon schema version {version} is incompatible with "
                        f"version {SUMMON_SCHEMA_VERSION}; recreate the "
                        "development database"
                    )
                for statement in _DDL:
                    session.run(statement)
                return
            for statement in _DDL:
                session.run(statement)
            session.run(
                "INSERT INTO taut_meta (key, value) VALUES (?, ?)",
                (SUMMON_SCHEMA_VERSION_KEY, str(SUMMON_SCHEMA_VERSION)),
            )

    _state_retry(_op, what="ensure schema")


def get_summon_schema_version(queue: Queue) -> int | None:
    """Return the stored summon schema version, if any."""

    def _op() -> int | None:
        with queue.sidecar() as session:
            row = _one(
                session,
                "SELECT value FROM taut_meta WHERE key = ?",
                (SUMMON_SCHEMA_VERSION_KEY,),
            )
        return None if row is None else int(row[0])

    return _state_retry(_op, what="get schema version")


def capture_driver_evidence(pid: int | None = None) -> tuple[int, str]:
    """Return (pid, start_time) liveness evidence for a real process.

    Defaults to the calling process — the summon driver claims with its
    own evidence. Raises when the start-time token cannot be read, because
    unverifiable evidence could never be reclaimed safely.
    """

    target = os.getpid() if pid is None else pid
    proc = capture_process(target)
    if proc is None or proc.start_time is None:
        raise SummonStateError(f"cannot capture start-time evidence for pid {target}")
    return target, proc.start_time


# --- transient claims ([SUM-4] step 0) ---------------------------------------


def claim_name(
    queue: Queue,
    *,
    name: str,
    provider: str,
    driver_pid: int,
    driver_start_time: str,
    claimed_ts: int,
    takeover: bool = False,
) -> SummonClaimRow:
    """Transactionally claim (name, provider) for an in-flight bootstrap.

    An existing claim is honored while its driver evidence is live,
    reclaimed when it is dead, and held (unless ``takeover``) when it
    cannot be verified. A concurrent loser surfaces as
    ``ClaimConflictError`` for the caller's [SUM-4] collision rule.
    """

    def _op() -> SummonClaimRow:
        with queue.sidecar(transaction=True) as session:
            row = _one(
                session,
                """
                SELECT name, provider, driver_pid, driver_start_time, claimed_ts
                FROM taut_summon_claims
                WHERE name = ? AND provider = ?
                """,
                (name, provider),
            )
            if row is not None:
                held_pid = int(row[2])
                held_start = cast(str, row[3])
                if held_pid != driver_pid or held_start != driver_start_time:
                    liveness = _evidence_liveness(held_pid, held_start)
                    if liveness == "live":
                        raise ClaimConflictError(
                            f"summon of '{name}' ({provider}) is already in "
                            f"flight: driver pid {held_pid} is live"
                        )
                    if liveness == "indeterminate" and not takeover:
                        raise ClaimConflictError(
                            f"cannot verify the driver (pid {held_pid}) holding "
                            f"the claim on '{name}' ({provider}); rerun with "
                            "--takeover to replace it"
                        )
                session.run(
                    "DELETE FROM taut_summon_claims WHERE name = ? AND provider = ?",
                    (name, provider),
                )
            try:
                session.run(
                    """
                    INSERT INTO taut_summon_claims (
                        name, provider, driver_pid, driver_start_time, claimed_ts
                    )
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (name, provider, driver_pid, driver_start_time, claimed_ts),
                )
            except IntegrityError as exc:
                raise ClaimConflictError(
                    f"summon of '{name}' ({provider}) is already in flight"
                ) from exc
        claim = get_claim(queue, name=name, provider=provider)
        if claim is None:
            raise SummonStateError("inserted claim could not be read back")
        return claim

    return _state_retry(_op, what="claim name")


def get_claim(queue: Queue, *, name: str, provider: str) -> SummonClaimRow | None:
    def _op() -> SummonClaimRow | None:
        with queue.sidecar() as session:
            row = _one(
                session,
                """
                SELECT name, provider, driver_pid, driver_start_time, claimed_ts
                FROM taut_summon_claims
                WHERE name = ? AND provider = ?
                """,
                (name, provider),
            )
        return _claim_row(row)

    return _state_retry(_op, what="get claim")


def release_claim(
    queue: Queue,
    *,
    name: str,
    provider: str,
    driver_pid: int,
    driver_start_time: str,
) -> bool:
    """Delete a bootstrap claim owned by this driver; return whether it did.

    Ownership-checked like ``release_driver``: after another driver
    reclaims or takes over the (name, provider) slot, the replaced
    driver's cleanup is a no-op returning ``False``.
    """

    def _op() -> bool:
        with queue.sidecar(transaction=True) as session:
            row = _one(
                session,
                """
                SELECT driver_pid, driver_start_time
                FROM taut_summon_claims
                WHERE name = ? AND provider = ?
                """,
                (name, provider),
            )
            if row is None or int(row[0]) != driver_pid or row[1] != driver_start_time:
                return False
            # Evidence predicates on the delete for read-committed backends
            # (see release_driver).
            session.run(
                """
                DELETE FROM taut_summon_claims
                WHERE name = ? AND provider = ?
                  AND driver_pid = ? AND driver_start_time = ?
                """,
                (name, provider, driver_pid, driver_start_time),
            )
            confirm = _one(
                session,
                "SELECT 1 FROM taut_summon_claims WHERE name = ? AND provider = ?",
                (name, provider),
            )
        return confirm is None

    return _state_retry(_op, what="release claim")


# --- durable sessions ---------------------------------------------------------


def record_session(
    queue: Queue,
    *,
    member_id: str,
    token: str,
    provider: str,
    provider_session_id: str | None = None,
    driver_pid: int | None = None,
    driver_start_time: str | None = None,
    updated_ts: int,
) -> SummonSessionRow:
    """Idempotently upsert the member's durable session row."""

    def _op() -> SummonSessionRow:
        with queue.sidecar(transaction=True) as session:
            row = _one(
                session,
                "SELECT member_id FROM taut_summon_sessions WHERE member_id = ?",
                (member_id,),
            )
            if row is None:
                session.run(
                    """
                    INSERT INTO taut_summon_sessions (
                        member_id, token, provider, provider_session_id,
                        driver_pid, driver_start_time, wired, updated_ts
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        member_id,
                        token,
                        provider,
                        provider_session_id,
                        driver_pid,
                        driver_start_time,
                        0,
                        updated_ts,
                    ),
                )
            else:
                session.run(
                    """
                    UPDATE taut_summon_sessions
                    SET token = ?, provider = ?, provider_session_id = ?,
                        driver_pid = ?, driver_start_time = ?, updated_ts = ?
                    WHERE member_id = ?
                    """,
                    (
                        token,
                        provider,
                        provider_session_id,
                        driver_pid,
                        driver_start_time,
                        updated_ts,
                        member_id,
                    ),
                )
        stored = get_session(queue, member_id)
        if stored is None:
            raise SummonStateError("recorded session could not be read back")
        return stored

    return _state_retry(_op, what="record session")


def get_session(queue: Queue, member_id: str) -> SummonSessionRow | None:
    def _op() -> SummonSessionRow | None:
        with queue.sidecar() as session:
            row = _one(session, _SESSION_SELECT, (member_id,))
        return _session_row(row)

    return _state_retry(_op, what="get session")


def list_sessions(queue: Queue) -> list[SummonSessionRow]:
    """Return every durable session row (the bare ``status`` listing)."""

    def _op() -> list[SummonSessionRow]:
        with queue.sidecar() as session:
            rows = list(
                session.run(
                    """
                    SELECT member_id, token, provider, provider_session_id,
                           driver_pid, driver_start_time, wired, updated_ts
                    FROM taut_summon_sessions
                    ORDER BY updated_ts DESC
                    """,
                    (),
                    fetch=True,
                )
            )
        result: list[SummonSessionRow] = []
        for row in rows:
            parsed = _session_row(row)
            if parsed is not None:
                result.append(parsed)
        return result

    return _state_retry(_op, what="list sessions")


def driver_liveness(row: SummonSessionRow) -> _Liveness:
    """Classify a session row's recorded driver evidence ([SUM-8] guard).

    ``dead`` covers the absent case too: a row with no driver evidence
    (both fields NULL) means nothing is summoned right now.
    """

    pid = row["driver_pid"]
    start = row["driver_start_time"]
    if pid is None or start is None:
        return "dead"
    return _evidence_liveness(pid, start)


def update_session(
    queue: Queue,
    *,
    member_id: str,
    provider_session_id: str | None,
    updated_ts: int,
) -> SummonSessionRow:
    """Update the provider session id (the event pump's ledger write)."""

    def _op() -> SummonSessionRow:
        with queue.sidecar(transaction=True) as session:
            row = _one(session, _SESSION_SELECT, (member_id,))
            if row is None:
                raise SummonStateError(f"no summon session for member '{member_id}'")
            session.run(
                """
                UPDATE taut_summon_sessions
                SET provider_session_id = ?, updated_ts = ?
                WHERE member_id = ?
                """,
                (provider_session_id, updated_ts, member_id),
            )
        stored = get_session(queue, member_id)
        if stored is None:
            raise SummonStateError("updated session could not be read back")
        return stored

    return _state_retry(_op, what="update session")


def get_wired(queue: Queue, member_id: str) -> bool:
    """Return whether this summoned member/provider has completed attach."""

    row = get_session(queue, member_id)
    if row is None:
        raise SummonStateError(f"no summon session for member '{member_id}'")
    return row["wired"]


def set_wired(
    queue: Queue,
    *,
    member_id: str,
    value: bool,
    updated_ts: int,
) -> SummonSessionRow:
    """Set the PTY onboarding flag; the only writer for ``wired`` ([SUM-8])."""

    def _op() -> SummonSessionRow:
        with queue.sidecar(transaction=True) as session:
            row = _one(session, _SESSION_SELECT, (member_id,))
            if row is None:
                raise SummonStateError(f"no summon session for member '{member_id}'")
            session.run(
                """
                UPDATE taut_summon_sessions
                SET wired = ?, updated_ts = ?
                WHERE member_id = ?
                """,
                (1 if value else 0, updated_ts, member_id),
            )
        stored = get_session(queue, member_id)
        if stored is None:
            raise SummonStateError("updated session could not be read back")
        return stored

    return _state_retry(_op, what="set wired")


def claim_driver(
    queue: Queue,
    *,
    member_id: str,
    driver_pid: int,
    driver_start_time: str,
    updated_ts: int,
    takeover: bool = False,
) -> SummonSessionRow:
    """Claim the single-driver slot on a session row ([SUM-8] guard)."""

    def _op() -> SummonSessionRow:
        with queue.sidecar(transaction=True) as session:
            row = _one(session, _SESSION_SELECT, (member_id,))
            stored = _session_row(row)
            if stored is None:
                raise SummonStateError(f"no summon session for member '{member_id}'")
            held_pid = stored["driver_pid"]
            held_start = stored["driver_start_time"]
            held = held_pid is not None or held_start is not None
            same_driver = held_pid == driver_pid and held_start == driver_start_time
            if held and not same_driver:
                if held_pid is None or held_start is None:
                    liveness: _Liveness = "indeterminate"
                else:
                    liveness = _evidence_liveness(held_pid, held_start)
                if liveness == "live":
                    raise DriverConflictError(
                        f"member '{member_id}' already has a live summon driver "
                        f"(pid {held_pid}); a member speaks from one place"
                    )
                if liveness == "indeterminate" and not takeover:
                    raise DriverConflictError(
                        f"cannot verify the existing driver (pid {held_pid}) for "
                        f"member '{member_id}'; rerun with --takeover to "
                        "replace it"
                    )
            session.run(
                """
                UPDATE taut_summon_sessions
                SET driver_pid = ?, driver_start_time = ?, updated_ts = ?
                WHERE member_id = ?
                """,
                (driver_pid, driver_start_time, updated_ts, member_id),
            )
        claimed = get_session(queue, member_id)
        if claimed is None:
            raise SummonStateError("claimed session could not be read back")
        return claimed

    return _state_retry(_op, what="claim driver")


def release_driver(
    queue: Queue,
    *,
    member_id: str,
    driver_pid: int,
    driver_start_time: str,
    updated_ts: int,
) -> bool:
    """Clear the driver evidence on clean exit ([SUM-9] STOP path).

    Ownership-checked: only the driver whose evidence is on the row may
    clear it. After a takeover, the replaced driver's cleanup must be a
    no-op (returns ``False``) — it must never erase its successor's
    live claim. The read and conditional write share one transaction.
    """

    def _op() -> bool:
        with queue.sidecar(transaction=True) as session:
            row = _one(session, _SESSION_SELECT, (member_id,))
            stored = _session_row(row)
            if (
                stored is None
                or stored["driver_pid"] != driver_pid
                or stored["driver_start_time"] != driver_start_time
            ):
                return False
            # Evidence predicates on the write itself: SQLite's BEGIN IMMEDIATE
            # already serializes read-and-write, but simplebroker-pg maps
            # begin_immediate to plain BEGIN (read committed), where the read
            # alone cannot exclude a concurrent takeover.
            session.run(
                """
                UPDATE taut_summon_sessions
                SET driver_pid = NULL, driver_start_time = NULL, updated_ts = ?
                WHERE member_id = ? AND driver_pid = ? AND driver_start_time = ?
                """,
                (updated_ts, member_id, driver_pid, driver_start_time),
            )
            confirm = _session_row(_one(session, _SESSION_SELECT, (member_id,)))
        return confirm is not None and confirm["driver_pid"] is None

    return _state_retry(_op, what="release driver")


# --- helpers ------------------------------------------------------------------

_SESSION_SELECT = """
    SELECT member_id, token, provider, provider_session_id,
           driver_pid, driver_start_time, wired, updated_ts
    FROM taut_summon_sessions
    WHERE member_id = ?
"""

_Liveness = Literal["live", "dead", "indeterminate"]


def _evidence_liveness(pid: int, start_time: str) -> _Liveness:
    """Classify stored driver evidence the way presence does.

    ``live``: the pid exists and its start-time token matches. ``dead``:
    the pid is gone or belongs to a different (reused-pid) process.
    ``indeterminate``: a process exists but its start time cannot be read
    — fail closed and let ``--takeover`` decide.
    """

    proc = capture_process(pid)
    if proc is None:
        return "dead"
    if proc.start_time is None:
        return "indeterminate"
    return "live" if proc.start_time == start_time else "dead"


def _one(
    session: SidecarSession,
    sql: str,
    params: tuple[Any, ...] = (),
) -> tuple[Any, ...] | None:
    rows = list(session.run(sql, params, fetch=True))
    return rows[0] if rows else None


def _claim_row(row: tuple[Any, ...] | None) -> SummonClaimRow | None:
    if row is None:
        return None
    try:
        return {
            "name": cast(str, row[0]),
            "provider": cast(str, row[1]),
            "driver_pid": int(row[2]),
            "driver_start_time": cast(str, row[3]),
            "claimed_ts": int(row[4]),
        }
    except (IndexError, TypeError, ValueError) as exc:
        raise DatabaseError("malformed summon claim row") from exc


def _session_row(row: tuple[Any, ...] | None) -> SummonSessionRow | None:
    if row is None:
        return None
    try:
        return {
            "member_id": cast(str, row[0]),
            "token": cast(str, row[1]),
            "provider": cast(str, row[2]),
            "provider_session_id": cast(str | None, row[3]),
            "driver_pid": None if row[4] is None else int(row[4]),
            "driver_start_time": cast(str | None, row[5]),
            "wired": bool(int(row[6])),
            "updated_ts": int(row[7]),
        }
    except (IndexError, TypeError, ValueError) as exc:
        raise DatabaseError("malformed summon session row") from exc
