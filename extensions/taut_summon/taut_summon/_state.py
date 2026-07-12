"""Summon session ledger and single-driver guard over sidecar SQL.

All summon-owned SQL lives in this module, mirroring core's
``taut/state/_sql.py`` shapes: ``CREATE TABLE IF NOT EXISTS`` inside
``Queue.sidecar(transaction=True)``, qmark parameters only, and
single-transaction read-modify-write for every mutation.

The ledger is split by lifetime per [SUM-8]:

- ``taut_summon_claims`` — transient. One row per in-flight bootstrap,
  keyed ``(name, provider)`` (the concurrent-summon serialization point,
  [SUM-4]). Rows are deleted after session publication; a row whose
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
from typing import Any, Literal, TypedDict, cast

from simplebroker import Queue
from simplebroker.ext import DatabaseError, IntegrityError, SidecarSession

from taut.identity import capture_process

SUMMON_SCHEMA_VERSION = 2
SUMMON_SCHEMA_VERSION_KEY = "summon_schema_version"
LEDGER_QUEUE_NAME = "taut.summon_state"

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


_SELECT_SUMMON_SCHEMA_VERSION = """
SELECT value FROM taut_meta WHERE key = ?
"""
_INSERT_SUMMON_SCHEMA_VERSION = """
INSERT INTO taut_meta (key, value) VALUES (?, ?)
"""
_SELECT_CLAIM_BY_NAME_PROVIDER = """
SELECT name, provider, driver_pid, driver_start_time, claimed_ts
FROM taut_summon_claims
WHERE name = ? AND provider = ?
"""
_SELECT_CLAIM_EVIDENCE_BY_NAME_PROVIDER = """
SELECT driver_pid, driver_start_time
FROM taut_summon_claims
WHERE name = ? AND provider = ?
"""
_DELETE_CLAIM_BY_EXACT_EVIDENCE = """
DELETE FROM taut_summon_claims
WHERE name = ? AND provider = ?
  AND driver_pid = ? AND driver_start_time = ?
"""
_INSERT_CLAIM = """
INSERT INTO taut_summon_claims (
    name, provider, driver_pid, driver_start_time, claimed_ts
)
VALUES (?, ?, ?, ?, ?)
"""
_SESSION_SELECT_BY_MEMBER = """
SELECT member_id, token, provider, provider_session_id,
       driver_pid, driver_start_time, wired, updated_ts
FROM taut_summon_sessions
WHERE member_id = ?
"""
_SESSION_SELECT_ALL = """
SELECT member_id, token, provider, provider_session_id,
       driver_pid, driver_start_time, wired, updated_ts
FROM taut_summon_sessions
ORDER BY updated_ts DESC
"""
_SELECT_SESSION_EXISTS_BY_MEMBER = """
SELECT member_id FROM taut_summon_sessions WHERE member_id = ?
"""
_INSERT_SESSION = """
INSERT INTO taut_summon_sessions (
    member_id, token, provider, provider_session_id,
    driver_pid, driver_start_time, wired, updated_ts
)
VALUES (?, ?, ?, ?, ?, ?, ?, ?)
"""
_UPDATE_SESSION_RECORD = """
UPDATE taut_summon_sessions
SET token = ?, provider = ?, provider_session_id = ?,
    driver_pid = ?, driver_start_time = ?, updated_ts = ?
WHERE member_id = ?
"""
_UPDATE_SESSION_PROVIDER_SESSION_ID = """
UPDATE taut_summon_sessions
SET provider_session_id = ?, updated_ts = ?
WHERE member_id = ?
"""
_UPDATE_SESSION_WIRED = """
UPDATE taut_summon_sessions
SET wired = ?, updated_ts = ?
WHERE member_id = ?
"""
_UPDATE_DRIVER_FROM_EMPTY = """
UPDATE taut_summon_sessions
SET driver_pid = ?, driver_start_time = ?, updated_ts = ?
WHERE member_id = ? AND driver_pid IS NULL AND driver_start_time IS NULL
"""
_UPDATE_DRIVER_FROM_EXPECTED_EVIDENCE = """
UPDATE taut_summon_sessions
SET driver_pid = ?, driver_start_time = ?, updated_ts = ?
WHERE member_id = ?
  AND (driver_pid = ? OR (driver_pid IS NULL AND ? IS NULL))
  AND (
      driver_start_time = ?
      OR (driver_start_time IS NULL AND ? IS NULL)
  )
"""
_RELEASE_DRIVER_BY_EXACT_EVIDENCE = """
UPDATE taut_summon_sessions
SET driver_pid = NULL, driver_start_time = NULL, updated_ts = ?
WHERE member_id = ? AND driver_pid = ? AND driver_start_time = ?
"""


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

    with queue.sidecar(transaction=True) as session:
        session.run(_META_DDL)
        row = _one(
            session,
            _SELECT_SUMMON_SCHEMA_VERSION,
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
            _INSERT_SUMMON_SCHEMA_VERSION,
            (SUMMON_SCHEMA_VERSION_KEY, str(SUMMON_SCHEMA_VERSION)),
        )


def get_summon_schema_version(queue: Queue) -> int | None:
    """Return the stored summon schema version, if any."""

    with queue.sidecar() as session:
        row = _one(
            session,
            _SELECT_SUMMON_SCHEMA_VERSION,
            (SUMMON_SCHEMA_VERSION_KEY,),
        )
    return None if row is None else int(row[0])


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


# --- transient bootstrap claims ([SUM-4]) ------------------------------------


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

    existing = get_claim(queue, name=name, provider=provider)
    if existing is not None:
        held_pid = existing["driver_pid"]
        held_start = existing["driver_start_time"]
        same_driver = held_pid == driver_pid and held_start == driver_start_time
        if not same_driver:
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

    with queue.sidecar(transaction=True) as session:
        current = _claim_row(
            _one(session, _SELECT_CLAIM_BY_NAME_PROVIDER, (name, provider))
        )
        if current is not None:
            if existing is None or (
                current["driver_pid"],
                current["driver_start_time"],
                current["claimed_ts"],
            ) != (
                existing["driver_pid"],
                existing["driver_start_time"],
                existing["claimed_ts"],
            ):
                raise ClaimConflictError(
                    f"summon of '{name}' ({provider}) is already in flight"
                )
            session.run(
                _DELETE_CLAIM_BY_EXACT_EVIDENCE,
                (
                    name,
                    provider,
                    current["driver_pid"],
                    current["driver_start_time"],
                ),
            )
        try:
            session.run(
                _INSERT_CLAIM,
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


def get_claim(queue: Queue, *, name: str, provider: str) -> SummonClaimRow | None:
    with queue.sidecar() as session:
        row = _one(
            session,
            _SELECT_CLAIM_BY_NAME_PROVIDER,
            (name, provider),
        )
    return _claim_row(row)


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

    with queue.sidecar(transaction=True) as session:
        row = _one(
            session,
            _SELECT_CLAIM_EVIDENCE_BY_NAME_PROVIDER,
            (name, provider),
        )
        if row is None or int(row[0]) != driver_pid or row[1] != driver_start_time:
            return False
        # Evidence predicates on the delete for read-committed backends
        # (see release_driver).
        session.run(
            _DELETE_CLAIM_BY_EXACT_EVIDENCE,
            (name, provider, driver_pid, driver_start_time),
        )
        confirm = _one(
            session,
            _SELECT_CLAIM_BY_NAME_PROVIDER,
            (name, provider),
        )
    return confirm is None


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

    if (driver_pid is None) != (driver_start_time is None):
        raise SummonStateError(
            "driver_pid and driver_start_time must be both set or both null"
        )

    with queue.sidecar(transaction=True) as session:
        row = _one(
            session,
            _SELECT_SESSION_EXISTS_BY_MEMBER,
            (member_id,),
        )
        if row is None:
            session.run(
                _INSERT_SESSION,
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
                _UPDATE_SESSION_RECORD,
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
        stored = _session_row(_one(session, _SESSION_SELECT_BY_MEMBER, (member_id,)))
        if stored is None:
            raise SummonStateError("recorded session could not be read back")
    return stored


def get_session(queue: Queue, member_id: str) -> SummonSessionRow | None:
    with queue.sidecar() as session:
        row = _one(session, _SESSION_SELECT_BY_MEMBER, (member_id,))
    return _session_row(row)


def list_sessions(queue: Queue) -> list[SummonSessionRow]:
    """Return every durable session row (the bare ``status`` listing)."""

    with queue.sidecar() as session:
        rows = list(
            session.run(
                _SESSION_SELECT_ALL,
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


def driver_liveness(row: SummonSessionRow) -> _Liveness:
    """Classify a session row's recorded driver evidence ([SUM-8] guard).

    ``dead`` covers the absent case too: a row with no driver evidence
    (both fields NULL) means nothing is summoned right now.
    """

    pid = row["driver_pid"]
    start = row["driver_start_time"]
    if pid is None and start is None:
        return "dead"
    if pid is None or start is None:
        return "indeterminate"
    return _evidence_liveness(pid, start)


def update_session(
    queue: Queue,
    *,
    member_id: str,
    provider_session_id: str | None,
    updated_ts: int,
) -> SummonSessionRow:
    """Update the provider session id (the event pump's ledger write)."""

    with queue.sidecar(transaction=True) as session:
        row = _one(session, _SESSION_SELECT_BY_MEMBER, (member_id,))
        if row is None:
            raise SummonStateError(f"no summon session for member '{member_id}'")
        session.run(
            _UPDATE_SESSION_PROVIDER_SESSION_ID,
            (provider_session_id, updated_ts, member_id),
        )
    stored = get_session(queue, member_id)
    if stored is None:
        raise SummonStateError("updated session could not be read back")
    return stored


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

    with queue.sidecar(transaction=True) as session:
        row = _one(session, _SESSION_SELECT_BY_MEMBER, (member_id,))
        if row is None:
            raise SummonStateError(f"no summon session for member '{member_id}'")
        session.run(
            _UPDATE_SESSION_WIRED,
            (1 if value else 0, updated_ts, member_id),
        )
    stored = get_session(queue, member_id)
    if stored is None:
        raise SummonStateError("updated session could not be read back")
    return stored


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

    stored = get_session(queue, member_id)
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

    with queue.sidecar(transaction=True) as session:
        current = _session_row(_one(session, _SESSION_SELECT_BY_MEMBER, (member_id,)))
        if current is None:
            raise SummonStateError(f"no summon session for member '{member_id}'")
        current_evidence = (current["driver_pid"], current["driver_start_time"])
        expected_evidence = (held_pid, held_start)
        if current_evidence != expected_evidence:
            raise DriverConflictError(
                f"member '{member_id}' driver slot changed while claiming"
            )
        if held_pid is None and held_start is None:
            session.run(
                _UPDATE_DRIVER_FROM_EMPTY,
                (driver_pid, driver_start_time, updated_ts, member_id),
            )
        else:
            session.run(
                _UPDATE_DRIVER_FROM_EXPECTED_EVIDENCE,
                (
                    driver_pid,
                    driver_start_time,
                    updated_ts,
                    member_id,
                    held_pid,
                    held_pid,
                    held_start,
                    held_start,
                ),
            )
        # This readback must stay in the write transaction. Under Postgres
        # read committed, a competing writer can win after ``current`` was
        # read and make the evidence-predicated UPDATE affect zero rows.
        claimed = _session_row(_one(session, _SESSION_SELECT_BY_MEMBER, (member_id,)))
        if claimed is None or (
            claimed["driver_pid"],
            claimed["driver_start_time"],
        ) != (driver_pid, driver_start_time):
            raise DriverConflictError(
                f"member '{member_id}' driver claim did not acquire the slot"
            )
    return claimed


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
    clear it. The result confirms that the row is absent, both evidence values
    are null, or complete different evidence owns it. Partial evidence and a
    failed conditional clear return ``False``. The read, conditional write,
    and confirmation share one transaction.
    """

    with queue.sidecar(transaction=True) as session:
        row = _one(session, _SESSION_SELECT_BY_MEMBER, (member_id,))
        stored = _session_row(row)
        if stored is None:
            return True
        stored_evidence = (stored["driver_pid"], stored["driver_start_time"])
        caller_evidence = (driver_pid, driver_start_time)
        if stored_evidence != caller_evidence:
            return release_evidence_confirmed(stored_evidence, caller_evidence)
        # Evidence predicates on the write itself: SQLite's BEGIN IMMEDIATE
        # already serializes read-and-write, but simplebroker-pg maps
        # begin_immediate to plain BEGIN (read committed), where the read
        # alone cannot exclude a concurrent takeover.
        session.run(
            _RELEASE_DRIVER_BY_EXACT_EVIDENCE,
            (updated_ts, member_id, driver_pid, driver_start_time),
        )
        confirm = _session_row(_one(session, _SESSION_SELECT_BY_MEMBER, (member_id,)))
        if confirm is None:
            return True
        return release_evidence_confirmed(
            (confirm["driver_pid"], confirm["driver_start_time"]),
            caller_evidence,
        )


# --- helpers ------------------------------------------------------------------

_Liveness = Literal["live", "dead", "indeterminate"]


def release_evidence_confirmed(
    stored: tuple[int | None, str | None],
    caller: tuple[int | None, str | None],
) -> bool:
    """Return whether complete row evidence proves the caller no longer owns it.

    This predicate owns both transactional release confirmation and the CLI's
    later polling projection ([SUM-9]).
    """

    pid, start = stored
    if pid is None and start is None:
        return True
    if pid is None or start is None:
        return False
    return stored != caller


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
        if len(row) != 8:
            raise ValueError(f"expected 8 columns, got {len(row)}")
        return {
            "member_id": _required_str(row[0], "member_id"),
            "token": _required_str(row[1], "token"),
            "provider": _required_str(row[2], "provider"),
            "provider_session_id": _optional_str(row[3], "provider_session_id"),
            "driver_pid": _optional_int(row[4], "driver_pid"),
            "driver_start_time": _optional_str(row[5], "driver_start_time"),
            "wired": _required_bool_int(row[6], "wired"),
            "updated_ts": _required_int(row[7], "updated_ts"),
        }
    except (IndexError, TypeError, ValueError) as exc:
        raise DatabaseError("malformed summon session row") from exc


def _required_str(value: Any, column: str) -> str:
    if not isinstance(value, str) or value == "":
        raise ValueError(f"{column} must be a non-empty string")
    return value


def _optional_str(value: Any, column: str) -> str | None:
    if value is None or isinstance(value, str):
        return value
    raise ValueError(f"{column} must be a string or NULL")


def _required_int(value: Any, column: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{column} must be an integer")
    return int(value)


def _optional_int(value: Any, column: str) -> int | None:
    if value is None:
        return None
    return _required_int(value, column)


def _required_bool_int(value: Any, column: str) -> bool:
    parsed = _required_int(value, column)
    if parsed not in (0, 1):
        raise ValueError(f"{column} must be 0 or 1")
    return bool(parsed)
