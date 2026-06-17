"""Taut sidecar schema and state access helpers.

All taut-owned SQL lives in this module. Code outside this file should operate
through these helpers so a future non-SQL state mapping has one boundary.

Spec references:
- docs/specs/02-taut-core.md [TAUT-3.3], [TAUT-3.4], [TAUT-7.2], [TAUT-12.2]
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any, TypedDict, cast

from simplebroker import Queue
from simplebroker.ext import IntegrityError, SidecarSession

from taut._constants import SCHEMA_VERSION
from taut._exceptions import SchemaVersionError

SCHEMA_VERSION_KEY = "schema_version"


class MemberRow(TypedDict):
    handle: str
    kind: str
    uid: int
    host_id: str
    host_label: str | None
    anchor_pid: int | None
    anchor_start_time: str | None
    fingerprint: str | None
    token: str | None
    meta: dict[str, Any]
    created_ts: int
    last_active_ts: int


class ThreadRow(TypedDict):
    name: str
    parent: str | None
    origin_ts: int | None
    created_by: str
    created_ts: int


class MembershipRow(TypedDict):
    thread: str
    member: str
    joined_ts: int
    last_seen_ts: int


DDL: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS taut_meta (
        key   TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS taut_members (
        handle            TEXT PRIMARY KEY,
        kind              TEXT NOT NULL CHECK (kind IN ('human', 'agent')),
        uid               BIGINT NOT NULL,
        host_id           TEXT NOT NULL,
        host_label        TEXT,
        anchor_pid        BIGINT,
        anchor_start_time TEXT,
        fingerprint       TEXT,
        token             TEXT UNIQUE,
        meta              TEXT,
        created_ts        BIGINT NOT NULL,
        last_active_ts    BIGINT NOT NULL
    )
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS taut_members_anchor_unique
        ON taut_members (host_id, anchor_pid, anchor_start_time)
        WHERE anchor_pid IS NOT NULL
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS taut_members_human_unique
        ON taut_members (host_id, uid)
        WHERE kind = 'human'
    """,
    """
    CREATE TABLE IF NOT EXISTS taut_threads (
        name       TEXT PRIMARY KEY,
        parent     TEXT,
        origin_ts  BIGINT,
        created_by TEXT NOT NULL,
        created_ts BIGINT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS taut_membership (
        thread       TEXT NOT NULL,
        member       TEXT NOT NULL,
        joined_ts    BIGINT NOT NULL,
        last_seen_ts BIGINT NOT NULL DEFAULT 0,
        PRIMARY KEY (thread, member)
    )
    """,
)


def ensure_schema(queue: Queue) -> None:
    """Install or validate the v1 sidecar schema."""

    with queue.sidecar(transaction=True) as session:
        for statement in DDL:
            session.run(statement)
        row = _one(
            session,
            "SELECT value FROM taut_meta WHERE key = ?",
            (SCHEMA_VERSION_KEY,),
        )
        if row is None:
            session.run(
                "INSERT INTO taut_meta (key, value) VALUES (?, ?)",
                (SCHEMA_VERSION_KEY, str(SCHEMA_VERSION)),
            )
            return
        version = int(row[0])
        if version > SCHEMA_VERSION:
            raise SchemaVersionError(
                f"taut schema version {version} is newer than supported "
                f"version {SCHEMA_VERSION}; upgrade taut"
            )
        if version < SCHEMA_VERSION:
            session.run(
                "UPDATE taut_meta SET value = ? WHERE key = ?",
                (str(SCHEMA_VERSION), SCHEMA_VERSION_KEY),
            )


def get_schema_version(queue: Queue) -> int | None:
    """Return the stored taut schema version, if any."""

    with queue.sidecar() as session:
        row = _one(
            session,
            "SELECT value FROM taut_meta WHERE key = ?",
            (SCHEMA_VERSION_KEY,),
        )
    return None if row is None else int(row[0])


def insert_member(
    queue: Queue,
    *,
    handle: str,
    kind: str,
    uid: int,
    host_id: str,
    host_label: str | None,
    anchor_pid: int | None,
    anchor_start_time: str | None,
    fingerprint: str | None,
    token: str,
    meta: dict[str, Any] | None,
    created_ts: int,
) -> MemberRow:
    """Insert a member, resolving anchor/human lost races to the winning row."""

    meta_json = json.dumps(meta or {}, sort_keys=True, separators=(",", ":"))
    try:
        with queue.sidecar(transaction=True) as session:
            session.run(
                """
                INSERT INTO taut_members (
                    handle, kind, uid, host_id, host_label, anchor_pid,
                    anchor_start_time, fingerprint, token, meta, created_ts,
                    last_active_ts
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    handle,
                    kind,
                    uid,
                    host_id,
                    host_label,
                    anchor_pid,
                    anchor_start_time,
                    fingerprint,
                    token,
                    meta_json,
                    created_ts,
                    created_ts,
                ),
            )
    except IntegrityError:
        winner = None
        if anchor_pid is not None and anchor_start_time is not None:
            winner = get_member_by_anchor(
                queue,
                host_id=host_id,
                anchor_pid=anchor_pid,
                anchor_start_time=anchor_start_time,
            )
        if winner is None and kind == "human":
            winner = get_member_by_uid(queue, host_id=host_id, uid=uid)
        if winner is None:
            winner = get_member(queue, handle)
        if winner is None:
            raise
        return winner
    member = get_member(queue, handle)
    if member is None:
        raise RuntimeError("inserted member could not be read back")
    return member


def update_member_activity(queue: Queue, handle: str, active_ts: int) -> None:
    with queue.sidecar(transaction=True) as session:
        session.run(
            """
            UPDATE taut_members
            SET last_active_ts = CASE
                WHEN last_active_ts < ? THEN ? ELSE last_active_ts END
            WHERE handle = ?
            """,
            (active_ts, active_ts, handle),
        )


def update_member_persona(
    queue: Queue, handle: str, persona: str | None
) -> MemberRow | None:
    member = get_member(queue, handle)
    if member is None:
        return None
    meta = dict(member["meta"])
    if persona is None:
        meta.pop("persona", None)
    else:
        meta["persona"] = persona
    with queue.sidecar(transaction=True) as session:
        session.run(
            "UPDATE taut_members SET meta = ? WHERE handle = ?",
            (json.dumps(meta, sort_keys=True, separators=(",", ":")), handle),
        )
    return get_member(queue, handle)


def update_member_anchor(
    queue: Queue,
    *,
    handle: str,
    host_id: str,
    host_label: str | None,
    anchor_pid: int,
    anchor_start_time: str,
    fingerprint: str,
    active_ts: int,
) -> MemberRow:
    with queue.sidecar(transaction=True) as session:
        session.run(
            """
            UPDATE taut_members
            SET host_id = ?, host_label = ?, anchor_pid = ?,
                anchor_start_time = ?, fingerprint = ?,
                last_active_ts = CASE
                    WHEN last_active_ts < ? THEN ? ELSE last_active_ts END
            WHERE handle = ?
            """,
            (
                host_id,
                host_label,
                anchor_pid,
                anchor_start_time,
                fingerprint,
                active_ts,
                active_ts,
                handle,
            ),
        )
    member = get_member(queue, handle)
    if member is None:
        raise RuntimeError("updated member could not be read back")
    return member


def get_member(queue: Queue, handle: str) -> MemberRow | None:
    with queue.sidecar() as session:
        row = _one(session, _member_select("handle = ?"), (handle,))
    return _member_row(row)


def get_member_by_token(queue: Queue, token: str) -> MemberRow | None:
    with queue.sidecar() as session:
        row = _one(session, _member_select("token = ?"), (token,))
    return _member_row(row)


def get_member_by_uid(queue: Queue, *, host_id: str, uid: int) -> MemberRow | None:
    with queue.sidecar() as session:
        row = _one(
            session,
            _member_select("host_id = ? AND uid = ? AND kind = 'human'"),
            (host_id, uid),
        )
    return _member_row(row)


def get_member_by_anchor(
    queue: Queue,
    *,
    host_id: str,
    anchor_pid: int,
    anchor_start_time: str,
) -> MemberRow | None:
    with queue.sidecar() as session:
        row = _one(
            session,
            _member_select("host_id = ? AND anchor_pid = ? AND anchor_start_time = ?"),
            (host_id, anchor_pid, anchor_start_time),
        )
    return _member_row(row)


def list_members(queue: Queue) -> list[MemberRow]:
    with queue.sidecar() as session:
        rows = _all(session, f"{_member_select('1 = 1')} ORDER BY handle")
    return [_require_member_row(row) for row in rows]


def list_thread_members(queue: Queue, thread: str) -> list[MemberRow]:
    with queue.sidecar() as session:
        rows = _all(
            session,
            """
            SELECT m.handle, m.kind, m.uid, m.host_id, m.host_label,
                   m.anchor_pid, m.anchor_start_time, m.fingerprint, m.token,
                   m.meta, m.created_ts, m.last_active_ts
            FROM taut_members m
            JOIN taut_membership tm ON tm.member = m.handle
            WHERE tm.thread = ?
            ORDER BY m.handle
            """,
            (thread,),
        )
    return [_require_member_row(row) for row in rows]


def upsert_thread(
    queue: Queue,
    *,
    name: str,
    parent: str | None,
    origin_ts: int | None,
    created_by: str,
    created_ts: int,
) -> ThreadRow:
    with queue.sidecar(transaction=True) as session:
        session.run(
            """
            INSERT INTO taut_threads (
                name, parent, origin_ts, created_by, created_ts
            )
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(name) DO NOTHING
            """,
            (name, parent, origin_ts, created_by, created_ts),
        )
    thread = get_thread(queue, name)
    if thread is None:
        raise RuntimeError("upserted thread could not be read back")
    return thread


def get_thread(queue: Queue, name: str) -> ThreadRow | None:
    with queue.sidecar() as session:
        row = _one(
            session,
            """
            SELECT name, parent, origin_ts, created_by, created_ts
            FROM taut_threads
            WHERE name = ?
            """,
            (name,),
        )
    return _thread_row(row)


def list_threads(queue: Queue) -> list[ThreadRow]:
    with queue.sidecar() as session:
        rows = _all(
            session,
            """
            SELECT name, parent, origin_ts, created_by, created_ts
            FROM taut_threads
            ORDER BY name
            """,
        )
    return [_require_thread_row(row) for row in rows]


def add_membership(
    queue: Queue,
    *,
    thread: str,
    member: str,
    joined_ts: int,
    last_seen_ts: int,
) -> MembershipRow:
    with queue.sidecar(transaction=True) as session:
        session.run(
            """
            INSERT INTO taut_membership (
                thread, member, joined_ts, last_seen_ts
            )
            VALUES (?, ?, ?, ?)
            ON CONFLICT(thread, member) DO NOTHING
            """,
            (thread, member, joined_ts, last_seen_ts),
        )
    membership = get_membership(queue, thread=thread, member=member)
    if membership is None:
        raise RuntimeError("membership could not be read back")
    return membership


def remove_membership(queue: Queue, *, thread: str, member: str) -> bool:
    existed = get_membership(queue, thread=thread, member=member) is not None
    if not existed:
        return False
    with queue.sidecar(transaction=True) as session:
        session.run(
            "DELETE FROM taut_membership WHERE thread = ? AND member = ?",
            (thread, member),
        )
    return True


def get_membership(queue: Queue, *, thread: str, member: str) -> MembershipRow | None:
    with queue.sidecar() as session:
        row = _one(
            session,
            """
            SELECT thread, member, joined_ts, last_seen_ts
            FROM taut_membership
            WHERE thread = ? AND member = ?
            """,
            (thread, member),
        )
    return _membership_row(row)


def list_memberships(queue: Queue, member: str) -> list[MembershipRow]:
    with queue.sidecar() as session:
        rows = _all(
            session,
            """
            SELECT thread, member, joined_ts, last_seen_ts
            FROM taut_membership
            WHERE member = ?
            ORDER BY thread
            """,
            (member,),
        )
    return [_require_membership_row(row) for row in rows]


def list_thread_memberships(queue: Queue, thread: str) -> list[MembershipRow]:
    with queue.sidecar() as session:
        rows = _all(
            session,
            """
            SELECT thread, member, joined_ts, last_seen_ts
            FROM taut_membership
            WHERE thread = ?
            ORDER BY member
            """,
            (thread,),
        )
    return [_require_membership_row(row) for row in rows]


def advance_cursor(
    queue: Queue,
    *,
    thread: str,
    member: str,
    seen_ts: int,
) -> None:
    """Advance a cursor without allowing concurrent writers to regress it."""

    with queue.sidecar(transaction=True) as session:
        session.run(
            """
            UPDATE taut_membership
            SET last_seen_ts = CASE
                WHEN last_seen_ts < ? THEN ? ELSE last_seen_ts END
            WHERE thread = ? AND member = ?
            """,
            (seen_ts, seen_ts, thread, member),
        )


def _member_select(where: str) -> str:
    return f"""
        SELECT handle, kind, uid, host_id, host_label, anchor_pid,
               anchor_start_time, fingerprint, token, meta, created_ts,
               last_active_ts
        FROM taut_members
        WHERE {where}
    """


def _one(
    session: SidecarSession,
    sql: str,
    params: tuple[Any, ...] = (),
) -> tuple[Any, ...] | None:
    rows = list(session.run(sql, params, fetch=True))
    return rows[0] if rows else None


def _all(
    session: SidecarSession,
    sql: str,
    params: tuple[Any, ...] = (),
) -> list[tuple[Any, ...]]:
    return list(session.run(sql, params, fetch=True))


def _member_row(row: tuple[Any, ...] | None) -> MemberRow | None:
    if row is None:
        return None
    raw_meta = row[9]
    meta: dict[str, Any]
    if isinstance(raw_meta, str) and raw_meta:
        try:
            decoded = json.loads(raw_meta)
            meta = decoded if isinstance(decoded, dict) else {}
        except json.JSONDecodeError:
            meta = {}
    else:
        meta = {}
    return {
        "handle": cast(str, row[0]),
        "kind": cast(str, row[1]),
        "uid": int(row[2]),
        "host_id": cast(str, row[3]),
        "host_label": cast(str | None, row[4]),
        "anchor_pid": None if row[5] is None else int(row[5]),
        "anchor_start_time": cast(str | None, row[6]),
        "fingerprint": cast(str | None, row[7]),
        "token": cast(str | None, row[8]),
        "meta": meta,
        "created_ts": int(row[10]),
        "last_active_ts": int(row[11]),
    }


def _thread_row(row: tuple[Any, ...] | None) -> ThreadRow | None:
    if row is None:
        return None
    return {
        "name": cast(str, row[0]),
        "parent": cast(str | None, row[1]),
        "origin_ts": None if row[2] is None else int(row[2]),
        "created_by": cast(str, row[3]),
        "created_ts": int(row[4]),
    }


def _membership_row(row: tuple[Any, ...] | None) -> MembershipRow | None:
    if row is None:
        return None
    return {
        "thread": cast(str, row[0]),
        "member": cast(str, row[1]),
        "joined_ts": int(row[2]),
        "last_seen_ts": int(row[3]),
    }


def _require_member_row(row: tuple[Any, ...]) -> MemberRow:
    member = _member_row(row)
    if member is None:
        raise RuntimeError("expected member row")
    return member


def _require_thread_row(row: tuple[Any, ...]) -> ThreadRow:
    thread = _thread_row(row)
    if thread is None:
        raise RuntimeError("expected thread row")
    return thread


def _require_membership_row(row: tuple[Any, ...]) -> MembershipRow:
    membership = _membership_row(row)
    if membership is None:
        raise RuntimeError("expected membership row")
    return membership


def handles_in_use(queue: Queue) -> set[str]:
    return {member["handle"] for member in list_members(queue)}


def membership_threads(rows: Iterable[MembershipRow]) -> set[str]:
    return {row["thread"] for row in rows}
