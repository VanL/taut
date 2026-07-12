"""SQL sidecar implementation of Taut state.

All taut-owned SQL lives in this module. Production code should cross the
``SqlSidecarTautState`` adapter instead of calling these module helpers
directly.

Spec references:
- docs/specs/02-taut-core.md [TAUT-3.3], [TAUT-3.4], [TAUT-7.2], [TAUT-12.2]
- docs/specs/03-identity-addressing-notifications.md [IAN-3], [IAN-4],
  [IAN-6], [IAN-8]
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, cast

from simplebroker import Queue
from simplebroker.ext import IntegrityError, SidecarSession

from taut._constants import SCHEMA_VERSION, route_key
from taut._exceptions import SchemaVersionError
from taut.state._dialect import SqlDialect
from taut.state._types import (
    ChannelRenameRow,
    IdentityClaimRow,
    MemberRow,
    MembershipRow,
    ThreadKind,
    ThreadRow,
)

SCHEMA_VERSION_KEY = "schema_version"


META_DDL = """
CREATE TABLE IF NOT EXISTS taut_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
)
"""

DDL: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS taut_members (
        member_id         TEXT PRIMARY KEY,
        display_name      TEXT NOT NULL,
        name_key          TEXT NOT NULL UNIQUE,
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
    CREATE TABLE IF NOT EXISTS taut_member_aliases (
        alias_key  TEXT PRIMARY KEY,
        member_id  TEXT NOT NULL REFERENCES taut_members(member_id),
        created_ts BIGINT NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS taut_member_aliases_member_idx
        ON taut_member_aliases (member_id)
    """,
    """
    CREATE TABLE IF NOT EXISTS taut_identity_claims (
        claim_hash    TEXT PRIMARY KEY,
        member_id     TEXT NOT NULL REFERENCES taut_members(member_id),
        claim_kind    TEXT NOT NULL,
        host_id       TEXT,
        host_label    TEXT,
        evidence_json TEXT NOT NULL,
        first_seen_ts BIGINT NOT NULL,
        last_seen_ts  BIGINT NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS taut_identity_claims_member_idx
        ON taut_identity_claims (member_id)
    """,
    """
    CREATE TABLE IF NOT EXISTS taut_threads (
        name       TEXT PRIMARY KEY,
        kind       TEXT NOT NULL CHECK (
            kind IN ('channel', 'subthread', 'dm', 'notification', 'system')
        ),
        parent     TEXT,
        origin_ts  BIGINT,
        created_by TEXT NOT NULL,
        meta       TEXT,
        created_ts BIGINT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS taut_membership (
        thread       TEXT NOT NULL,
        member_id    TEXT NOT NULL REFERENCES taut_members(member_id),
        joined_ts    BIGINT NOT NULL,
        last_seen_ts BIGINT NOT NULL DEFAULT 0,
        PRIMARY KEY (thread, member_id)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS taut_membership_member_idx
        ON taut_membership (member_id)
    """,
    """
    CREATE TABLE IF NOT EXISTS taut_channel_renames (
        old_name      TEXT PRIMARY KEY,
        new_name      TEXT NOT NULL,
        state         TEXT NOT NULL,
        affected_json TEXT NOT NULL,
        started_ts    BIGINT NOT NULL,
        updated_ts    BIGINT NOT NULL
    )
    """,
)


@dataclass(slots=True)
class SqlSidecarTautState:
    """Taut state stored in SimpleBroker sidecar SQL tables."""

    queue: Queue
    dialect: SqlDialect

    def ensure_schema(self) -> None:
        ensure_schema(self.queue, dialect=self.dialect)

    def get_schema_version(self) -> int | None:
        return get_schema_version(self.queue)

    def insert_member(
        self,
        *,
        member_id: str,
        display_name: str,
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
        return insert_member(
            self.queue,
            dialect=self.dialect,
            member_id=member_id,
            display_name=display_name,
            kind=kind,
            uid=uid,
            host_id=host_id,
            host_label=host_label,
            anchor_pid=anchor_pid,
            anchor_start_time=anchor_start_time,
            fingerprint=fingerprint,
            token=token,
            meta=meta,
            created_ts=created_ts,
        )

    def update_member_activity(self, member_id: str, active_ts: int) -> None:
        update_member_activity(self.queue, member_id, active_ts)

    def update_member_persona(
        self,
        member_id: str,
        persona: str | None,
        *,
        active_ts: int | None = None,
    ) -> MemberRow | None:
        return update_member_persona(
            self.queue,
            member_id,
            persona,
            active_ts=active_ts,
        )

    def update_member_name(self, member_id: str, display_name: str) -> MemberRow:
        return update_member_name(
            self.queue,
            member_id,
            display_name,
            dialect=self.dialect,
        )

    def update_member_anchor(
        self,
        *,
        member_id: str,
        host_id: str,
        host_label: str | None,
        anchor_pid: int,
        anchor_start_time: str,
        fingerprint: str,
        active_ts: int,
    ) -> MemberRow:
        return update_member_anchor(
            self.queue,
            member_id=member_id,
            host_id=host_id,
            host_label=host_label,
            anchor_pid=anchor_pid,
            anchor_start_time=anchor_start_time,
            fingerprint=fingerprint,
            active_ts=active_ts,
        )

    def add_member_alias(self, *, member_id: str, alias: str, created_ts: int) -> None:
        add_member_alias(
            self.queue,
            dialect=self.dialect,
            member_id=member_id,
            alias=alias,
            created_ts=created_ts,
        )

    def list_member_aliases(self, member_id: str) -> list[str]:
        return list_member_aliases(self.queue, member_id)

    def get_member(self, member_id: str) -> MemberRow | None:
        return get_member(self.queue, member_id)

    def get_member_by_route_key(self, key: str) -> MemberRow | None:
        return get_member_by_route_key(self.queue, key)

    def get_member_by_token(self, token: str) -> MemberRow | None:
        return get_member_by_token(self.queue, token)

    def get_member_by_uid(self, *, host_id: str, uid: int) -> MemberRow | None:
        return get_member_by_uid(self.queue, host_id=host_id, uid=uid)

    def list_members(self) -> list[MemberRow]:
        return list_members(self.queue)

    def list_thread_members(self, thread: str) -> list[MemberRow]:
        return list_thread_members(self.queue, thread)

    def add_identity_claim(
        self,
        *,
        claim_hash: str,
        member_id: str,
        claim_kind: str,
        host_id: str | None,
        host_label: str | None,
        evidence: dict[str, Any],
        seen_ts: int,
    ) -> IdentityClaimRow:
        return add_identity_claim(
            self.queue,
            claim_hash=claim_hash,
            member_id=member_id,
            claim_kind=claim_kind,
            host_id=host_id,
            host_label=host_label,
            evidence=evidence,
            seen_ts=seen_ts,
        )

    def get_identity_claim(self, claim_hash: str) -> IdentityClaimRow | None:
        return get_identity_claim(self.queue, claim_hash)

    def get_member_by_claim_hash(self, claim_hash: str) -> MemberRow | None:
        return get_member_by_claim_hash(self.queue, claim_hash)

    def upsert_thread(
        self,
        *,
        name: str,
        kind: ThreadKind,
        parent: str | None,
        origin_ts: int | None,
        created_by: str,
        meta: dict[str, Any] | None,
        created_ts: int,
    ) -> ThreadRow:
        return upsert_thread(
            self.queue,
            name=name,
            kind=kind,
            parent=parent,
            origin_ts=origin_ts,
            created_by=created_by,
            meta=meta,
            created_ts=created_ts,
        )

    def get_thread(self, name: str) -> ThreadRow | None:
        return get_thread(self.queue, name)

    def list_threads(self, *, include_internal: bool = False) -> list[ThreadRow]:
        return list_threads(self.queue, include_internal=include_internal)

    def add_membership(
        self,
        *,
        thread: str,
        member_id: str,
        joined_ts: int,
        last_seen_ts: int,
    ) -> MembershipRow:
        return add_membership(
            self.queue,
            thread=thread,
            member_id=member_id,
            joined_ts=joined_ts,
            last_seen_ts=last_seen_ts,
        )

    def remove_membership(self, *, thread: str, member_id: str) -> bool:
        return remove_membership(self.queue, thread=thread, member_id=member_id)

    def get_membership(self, *, thread: str, member_id: str) -> MembershipRow | None:
        return get_membership(self.queue, thread=thread, member_id=member_id)

    def list_memberships(self, member_id: str) -> list[MembershipRow]:
        return list_memberships(self.queue, member_id)

    def advance_cursor(self, *, thread: str, member_id: str, seen_ts: int) -> None:
        advance_cursor(
            self.queue,
            thread=thread,
            member_id=member_id,
            seen_ts=seen_ts,
        )

    def start_channel_rename(
        self,
        *,
        old_name: str,
        new_name: str,
        affected: list[dict[str, str]],
        started_ts: int,
    ) -> ChannelRenameRow:
        return start_channel_rename(
            self.queue,
            old_name=old_name,
            new_name=new_name,
            affected=affected,
            started_ts=started_ts,
        )

    def incomplete_channel_renames(self) -> list[ChannelRenameRow]:
        return incomplete_channel_renames(self.queue)

    def apply_channel_rename_state(
        self,
        *,
        old_name: str,
        new_name: str,
        affected: list[dict[str, str]],
        updated_ts: int,
    ) -> None:
        apply_channel_rename_state(
            self.queue,
            old_name=old_name,
            new_name=new_name,
            affected=affected,
            updated_ts=updated_ts,
        )

    def member_names_in_use(self) -> set[str]:
        return member_names_in_use(self.queue)


def ensure_schema(queue: Queue, *, dialect: SqlDialect) -> None:
    """Install or validate the current sidecar schema."""

    with queue.sidecar(transaction=True) as session:
        _acquire_advisory_lock(session, dialect, "taut:schema")
        session.run(META_DDL)
        row = _one(
            session,
            "SELECT value FROM taut_meta WHERE key = ?",
            (SCHEMA_VERSION_KEY,),
        )
        if row is not None:
            version = int(row[0])
            if version > SCHEMA_VERSION:
                raise SchemaVersionError(
                    f"taut schema version {version} is newer than supported "
                    f"version {SCHEMA_VERSION}; upgrade taut"
                )
            if version < SCHEMA_VERSION:
                raise SchemaVersionError(
                    f"taut schema version {version} is incompatible with "
                    f"version {SCHEMA_VERSION}; recreate the development database"
                )
            for statement in DDL:
                session.run(statement)
            return
        for statement in DDL:
            session.run(statement)
        session.run(
            "INSERT INTO taut_meta (key, value) VALUES (?, ?)",
            (SCHEMA_VERSION_KEY, str(SCHEMA_VERSION)),
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
    dialect: SqlDialect,
    member_id: str,
    display_name: str,
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
    """Insert a member and return the stored row."""

    key = route_key(display_name)
    meta_json = _json_dumps(meta or {})
    with queue.sidecar(transaction=True) as session:
        _acquire_advisory_lock(session, dialect, f"taut:route:{key}")
        _ensure_route_available(session, key, owner_member_id=None)
        session.run(
            """
            INSERT INTO taut_members (
                member_id, display_name, name_key, kind, uid, host_id,
                host_label, anchor_pid, anchor_start_time, fingerprint, token,
                meta, created_ts, last_active_ts
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                member_id,
                display_name,
                key,
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
    member = get_member(queue, member_id)
    if member is None:
        raise RuntimeError("inserted member could not be read back")
    return member


def update_member_activity(queue: Queue, member_id: str, active_ts: int) -> None:
    with queue.sidecar(transaction=True) as session:
        session.run(
            """
            UPDATE taut_members
            SET last_active_ts = CASE
                WHEN last_active_ts < ? THEN ? ELSE last_active_ts END
            WHERE member_id = ?
            """,
            (active_ts, active_ts, member_id),
        )


def update_member_persona(
    queue: Queue,
    member_id: str,
    persona: str | None,
    *,
    active_ts: int | None = None,
) -> MemberRow | None:
    with queue.sidecar(transaction=True) as session:
        row = _one(session, _member_select("member_id = ?"), (member_id,))
        member = _member_row(row)
        if member is None:
            return None
        meta = dict(member["meta"])
        if persona is None:
            meta.pop("persona", None)
        else:
            meta["persona"] = persona
        if active_ts is None:
            session.run(
                "UPDATE taut_members SET meta = ? WHERE member_id = ?",
                (_json_dumps(meta), member_id),
            )
        else:
            session.run(
                """
                UPDATE taut_members
                SET meta = ?, last_active_ts = CASE
                    WHEN last_active_ts < ? THEN ? ELSE last_active_ts END
                WHERE member_id = ?
                """,
                (_json_dumps(meta), active_ts, active_ts, member_id),
            )
        return _member_row(_one(session, _member_select("member_id = ?"), (member_id,)))


def update_member_name(
    queue: Queue,
    member_id: str,
    display_name: str,
    *,
    dialect: SqlDialect,
) -> MemberRow:
    key = route_key(display_name)
    with queue.sidecar(transaction=True) as session:
        _acquire_advisory_lock(session, dialect, f"taut:route:{key}")
        _ensure_route_available(session, key, owner_member_id=member_id)
        session.run(
            """
            UPDATE taut_members
            SET display_name = ?, name_key = ?
            WHERE member_id = ?
            """,
            (display_name, key, member_id),
        )
    member = get_member(queue, member_id)
    if member is None:
        raise RuntimeError("updated member could not be read back")
    return member


def update_member_anchor(
    queue: Queue,
    *,
    member_id: str,
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
            WHERE member_id = ?
            """,
            (
                host_id,
                host_label,
                anchor_pid,
                anchor_start_time,
                fingerprint,
                active_ts,
                active_ts,
                member_id,
            ),
        )
    member = get_member(queue, member_id)
    if member is None:
        raise RuntimeError("updated member could not be read back")
    return member


def add_member_alias(
    queue: Queue,
    *,
    dialect: SqlDialect,
    member_id: str,
    alias: str,
    created_ts: int,
) -> None:
    key = route_key(alias)
    with queue.sidecar(transaction=True) as session:
        _acquire_advisory_lock(session, dialect, f"taut:route:{key}")
        _ensure_route_available(session, key, owner_member_id=member_id)
        session.run(
            """
            INSERT INTO taut_member_aliases (alias_key, member_id, created_ts)
            VALUES (?, ?, ?)
            """,
            (key, member_id, created_ts),
        )


def list_member_aliases(queue: Queue, member_id: str) -> list[str]:
    with queue.sidecar() as session:
        rows = _all(
            session,
            """
            SELECT alias_key
            FROM taut_member_aliases
            WHERE member_id = ?
            ORDER BY alias_key
            """,
            (member_id,),
        )
    return [cast(str, row[0]) for row in rows]


def get_member(queue: Queue, member_id: str) -> MemberRow | None:
    with queue.sidecar() as session:
        row = _one(session, _member_select("member_id = ?"), (member_id,))
    return _member_row(row)


def get_member_by_route_key(queue: Queue, key: str) -> MemberRow | None:
    normalized = route_key(key)
    with queue.sidecar() as session:
        row = _one(session, _member_select("name_key = ?"), (normalized,))
        if row is None:
            row = _one(
                session,
                """
                SELECT m.member_id, m.display_name, m.name_key, m.kind, m.uid,
                       m.host_id, m.host_label, m.anchor_pid,
                       m.anchor_start_time, m.fingerprint, m.token, m.meta,
                       m.created_ts, m.last_active_ts
                FROM taut_members m
                JOIN taut_member_aliases a ON a.member_id = m.member_id
                WHERE a.alias_key = ?
                """,
                (normalized,),
            )
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


def list_members(queue: Queue) -> list[MemberRow]:
    with queue.sidecar() as session:
        rows = _all(session, f"{_member_select('1 = 1')} ORDER BY name_key")
    return [_require_member_row(row) for row in rows]


def list_thread_members(queue: Queue, thread: str) -> list[MemberRow]:
    with queue.sidecar() as session:
        rows = _all(
            session,
            """
            SELECT m.member_id, m.display_name, m.name_key, m.kind, m.uid,
                   m.host_id, m.host_label, m.anchor_pid, m.anchor_start_time,
                   m.fingerprint, m.token, m.meta, m.created_ts,
                   m.last_active_ts
            FROM taut_members m
            JOIN taut_membership tm ON tm.member_id = m.member_id
            WHERE tm.thread = ?
            ORDER BY m.name_key
            """,
            (thread,),
        )
    return [_require_member_row(row) for row in rows]


def add_identity_claim(
    queue: Queue,
    *,
    claim_hash: str,
    member_id: str,
    claim_kind: str,
    host_id: str | None,
    host_label: str | None,
    evidence: dict[str, Any],
    seen_ts: int,
) -> IdentityClaimRow:
    existing = get_identity_claim(queue, claim_hash)
    if existing is not None:
        if existing["member_id"] != member_id:
            raise IntegrityError("identity claim belongs to another member")
        return _refresh_identity_claim(queue, claim_hash, seen_ts)
    try:
        with queue.sidecar(transaction=True) as session:
            session.run(
                """
                INSERT INTO taut_identity_claims (
                    claim_hash, member_id, claim_kind, host_id, host_label,
                    evidence_json, first_seen_ts, last_seen_ts
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    claim_hash,
                    member_id,
                    claim_kind,
                    host_id,
                    host_label,
                    _json_dumps(evidence),
                    seen_ts,
                    seen_ts,
                ),
            )
    except IntegrityError as exc:
        # Another process can insert the same deterministic claim between
        # this function's read and insert. Treat that race as idempotent only
        # when the row now belongs to the same member; ownership collisions
        # still surface as integrity errors.
        raced = get_identity_claim(queue, claim_hash)
        if raced is None:
            raise
        if raced["member_id"] != member_id:
            raise IntegrityError("identity claim belongs to another member") from exc
        return _refresh_identity_claim(queue, claim_hash, seen_ts)
    claim = get_identity_claim(queue, claim_hash)
    if claim is None:
        raise RuntimeError("inserted identity claim could not be read back")
    return claim


def _refresh_identity_claim(
    queue: Queue, claim_hash: str, seen_ts: int
) -> IdentityClaimRow:
    with queue.sidecar(transaction=True) as session:
        session.run(
            """
            UPDATE taut_identity_claims
            SET last_seen_ts = CASE
                WHEN last_seen_ts < ? THEN ? ELSE last_seen_ts END
            WHERE claim_hash = ?
            """,
            (seen_ts, seen_ts, claim_hash),
        )
    refreshed = get_identity_claim(queue, claim_hash)
    if refreshed is None:
        raise RuntimeError("identity claim disappeared during update")
    return refreshed


def get_identity_claim(queue: Queue, claim_hash: str) -> IdentityClaimRow | None:
    with queue.sidecar() as session:
        row = _one(
            session,
            """
            SELECT claim_hash, member_id, claim_kind, host_id, host_label,
                   evidence_json, first_seen_ts, last_seen_ts
            FROM taut_identity_claims
            WHERE claim_hash = ?
            """,
            (claim_hash,),
        )
    return _identity_claim_row(row)


def get_member_by_claim_hash(queue: Queue, claim_hash: str) -> MemberRow | None:
    claim = get_identity_claim(queue, claim_hash)
    if claim is None:
        return None
    return get_member(queue, claim["member_id"])


def upsert_thread(
    queue: Queue,
    *,
    name: str,
    kind: ThreadKind,
    parent: str | None,
    origin_ts: int | None,
    created_by: str,
    meta: dict[str, Any] | None,
    created_ts: int,
) -> ThreadRow:
    with queue.sidecar(transaction=True) as session:
        session.run(
            """
            INSERT INTO taut_threads (
                name, kind, parent, origin_ts, created_by, meta, created_ts
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(name) DO NOTHING
            """,
            (
                name,
                kind,
                parent,
                origin_ts,
                created_by,
                _json_dumps(meta or {}),
                created_ts,
            ),
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
            SELECT name, kind, parent, origin_ts, created_by, meta, created_ts
            FROM taut_threads
            WHERE name = ?
            """,
            (name,),
        )
    return _thread_row(row)


def list_threads(queue: Queue, *, include_internal: bool = False) -> list[ThreadRow]:
    where = "1 = 1" if include_internal else "kind IN ('channel', 'subthread', 'dm')"
    with queue.sidecar() as session:
        rows = _all(
            session,
            f"""
            SELECT name, kind, parent, origin_ts, created_by, meta, created_ts
            FROM taut_threads
            WHERE {where}
            ORDER BY name
            """,
        )
    return [_require_thread_row(row) for row in rows]


def add_membership(
    queue: Queue,
    *,
    thread: str,
    member_id: str,
    joined_ts: int,
    last_seen_ts: int,
) -> MembershipRow:
    with queue.sidecar(transaction=True) as session:
        session.run(
            """
            INSERT INTO taut_membership (
                thread, member_id, joined_ts, last_seen_ts
            )
            VALUES (?, ?, ?, ?)
            ON CONFLICT(thread, member_id) DO NOTHING
            """,
            (thread, member_id, joined_ts, last_seen_ts),
        )
    membership = get_membership(queue, thread=thread, member_id=member_id)
    if membership is None:
        raise RuntimeError("membership could not be read back")
    return membership


def remove_membership(queue: Queue, *, thread: str, member_id: str) -> bool:
    with queue.sidecar(transaction=True) as session:
        deleted = _one(
            session,
            """
            DELETE FROM taut_membership
            WHERE thread = ? AND member_id = ?
            RETURNING 1
            """,
            (thread, member_id),
        )
    return deleted is not None


def get_membership(
    queue: Queue, *, thread: str, member_id: str
) -> MembershipRow | None:
    with queue.sidecar() as session:
        row = _one(
            session,
            """
            SELECT thread, member_id, joined_ts, last_seen_ts
            FROM taut_membership
            WHERE thread = ? AND member_id = ?
            """,
            (thread, member_id),
        )
    return _membership_row(row)


def list_memberships(queue: Queue, member_id: str) -> list[MembershipRow]:
    with queue.sidecar() as session:
        rows = _all(
            session,
            """
            SELECT thread, member_id, joined_ts, last_seen_ts
            FROM taut_membership
            WHERE member_id = ?
            ORDER BY thread
            """,
            (member_id,),
        )
    return [_require_membership_row(row) for row in rows]


def advance_cursor(
    queue: Queue,
    *,
    thread: str,
    member_id: str,
    seen_ts: int,
) -> None:
    """Advance a cursor without allowing concurrent writers to regress it."""

    with queue.sidecar(transaction=True) as session:
        session.run(
            """
            UPDATE taut_membership
            SET last_seen_ts = CASE
                WHEN last_seen_ts < ? THEN ? ELSE last_seen_ts END
            WHERE thread = ? AND member_id = ?
            """,
            (seen_ts, seen_ts, thread, member_id),
        )


def start_channel_rename(
    queue: Queue,
    *,
    old_name: str,
    new_name: str,
    affected: list[dict[str, str]],
    started_ts: int,
) -> ChannelRenameRow:
    with queue.sidecar(transaction=True) as session:
        session.run(
            """
            INSERT INTO taut_channel_renames (
                old_name, new_name, state, affected_json, started_ts, updated_ts
            )
            VALUES (?, ?, 'started', ?, ?, ?)
            """,
            (old_name, new_name, _json_dumps(affected), started_ts, started_ts),
        )
    row = get_channel_rename(queue, old_name)
    if row is None:
        raise RuntimeError("channel rename marker could not be read back")
    return row


def get_channel_rename(queue: Queue, old_name: str) -> ChannelRenameRow | None:
    with queue.sidecar() as session:
        row = _one(
            session,
            """
            SELECT old_name, new_name, state, affected_json, started_ts, updated_ts
            FROM taut_channel_renames
            WHERE old_name = ?
            """,
            (old_name,),
        )
    return _channel_rename_row(row)


def incomplete_channel_renames(queue: Queue) -> list[ChannelRenameRow]:
    with queue.sidecar() as session:
        rows = _all(
            session,
            """
            SELECT old_name, new_name, state, affected_json, started_ts, updated_ts
            FROM taut_channel_renames
            WHERE state != 'complete'
            ORDER BY started_ts
            """,
        )
    return [_require_channel_rename_row(row) for row in rows]


def apply_channel_rename_state(
    queue: Queue,
    *,
    old_name: str,
    new_name: str,
    affected: list[dict[str, str]],
    updated_ts: int,
) -> None:
    replacements = [(item["old"], item["new"]) for item in affected]
    with queue.sidecar(transaction=True) as session:
        for old_thread, new_thread in replacements:
            session.run(
                "UPDATE taut_threads SET name = ? WHERE name = ?",
                (new_thread, old_thread),
            )
            session.run(
                "UPDATE taut_membership SET thread = ? WHERE thread = ?",
                (new_thread, old_thread),
            )
        session.run(
            "UPDATE taut_threads SET parent = ? WHERE parent = ?",
            (new_name, old_name),
        )
        session.run(
            """
            UPDATE taut_channel_renames
            SET state = 'complete', updated_ts = ?
            WHERE old_name = ?
            """,
            (updated_ts, old_name),
        )


def member_names_in_use(queue: Queue) -> set[str]:
    return {member["name_key"] for member in list_members(queue)}


def _member_select(where: str) -> str:
    return f"""
        SELECT m.member_id, m.display_name, m.name_key, m.kind, m.uid,
               m.host_id, m.host_label, m.anchor_pid, m.anchor_start_time,
               m.fingerprint, m.token, m.meta, m.created_ts, m.last_active_ts
        FROM taut_members m
        WHERE {where}
    """


def _ensure_route_available(
    session: SidecarSession,
    key: str,
    *,
    owner_member_id: str | None,
) -> None:
    member = _one(
        session,
        "SELECT member_id FROM taut_members WHERE name_key = ?",
        (key,),
    )
    if member is not None and member[0] != owner_member_id:
        raise IntegrityError(f"name or alias already exists: {key}")
    alias = _one(
        session,
        "SELECT member_id FROM taut_member_aliases WHERE alias_key = ?",
        (key,),
    )
    if alias is not None and alias[0] != owner_member_id:
        raise IntegrityError(f"name or alias already exists: {key}")


def _acquire_advisory_lock(
    session: SidecarSession,
    dialect: SqlDialect,
    key: str,
) -> None:
    """Serialize a Postgres-only logical state namespace for this transaction."""

    if dialect.name != "postgres":
        return
    session.run(
        "SELECT pg_advisory_xact_lock(hashtextextended(?, 0))",
        (key,),
    )


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
    return {
        "member_id": cast(str, row[0]),
        "display_name": cast(str, row[1]),
        "name_key": cast(str, row[2]),
        "kind": cast(str, row[3]),
        "uid": int(row[4]),
        "host_id": cast(str, row[5]),
        "host_label": cast(str | None, row[6]),
        "anchor_pid": None if row[7] is None else int(row[7]),
        "anchor_start_time": cast(str | None, row[8]),
        "fingerprint": cast(str | None, row[9]),
        "token": cast(str | None, row[10]),
        "meta": _json_loads_object(row[11], context="taut_members.meta", nullable=True),
        "created_ts": int(row[12]),
        "last_active_ts": int(row[13]),
    }


def _identity_claim_row(row: tuple[Any, ...] | None) -> IdentityClaimRow | None:
    if row is None:
        return None
    return {
        "claim_hash": cast(str, row[0]),
        "member_id": cast(str, row[1]),
        "claim_kind": cast(str, row[2]),
        "host_id": cast(str | None, row[3]),
        "host_label": cast(str | None, row[4]),
        "evidence": _json_loads_object(
            row[5],
            context="taut_identity_claims.evidence_json",
            nullable=False,
        ),
        "first_seen_ts": int(row[6]),
        "last_seen_ts": int(row[7]),
    }


def _thread_row(row: tuple[Any, ...] | None) -> ThreadRow | None:
    if row is None:
        return None
    return {
        "name": cast(str, row[0]),
        "kind": cast(str, row[1]),
        "parent": cast(str | None, row[2]),
        "origin_ts": None if row[3] is None else int(row[3]),
        "created_by": cast(str, row[4]),
        "meta": _json_loads_object(row[5], context="taut_threads.meta", nullable=True),
        "created_ts": int(row[6]),
    }


def _membership_row(row: tuple[Any, ...] | None) -> MembershipRow | None:
    if row is None:
        return None
    return {
        "thread": cast(str, row[0]),
        "member_id": cast(str, row[1]),
        "joined_ts": int(row[2]),
        "last_seen_ts": int(row[3]),
    }


def _channel_rename_row(row: tuple[Any, ...] | None) -> ChannelRenameRow | None:
    if row is None:
        return None
    affected = _json_loads_rename_list(
        row[3], context="taut_channel_renames.affected_json"
    )
    return {
        "old_name": cast(str, row[0]),
        "new_name": cast(str, row[1]),
        "state": cast(str, row[2]),
        "affected": affected,
        "started_ts": int(row[4]),
        "updated_ts": int(row[5]),
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


def _require_channel_rename_row(row: tuple[Any, ...]) -> ChannelRenameRow:
    rename = _channel_rename_row(row)
    if rename is None:
        raise RuntimeError("expected channel rename row")
    return rename


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _json_loads_object(
    value: Any,
    *,
    context: str,
    nullable: bool,
) -> dict[str, Any]:
    if value is None and nullable:
        return {}
    if not isinstance(value, str) or not value:
        raise RuntimeError(f"{context}: expected JSON text")
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{context}: invalid JSON") from exc
    if not isinstance(decoded, dict):
        raise RuntimeError(f"{context}: expected an object")
    return decoded


def _json_loads_rename_list(
    value: Any,
    *,
    context: str,
) -> list[dict[str, str]]:
    if not isinstance(value, str) or not value:
        raise RuntimeError(f"{context}: expected JSON text")
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{context}: invalid JSON") from exc
    if not isinstance(decoded, list):
        raise RuntimeError(f"{context}: expected a list")
    affected: list[dict[str, str]] = []
    for index, item in enumerate(decoded):
        if not isinstance(item, dict):
            raise RuntimeError(f"{context}: item {index}: expected an object")
        old = item.get("old")
        new = item.get("new")
        if not isinstance(old, str) or not isinstance(new, str):
            raise RuntimeError(f"{context}: item {index}: expected string old and new")
        affected.append({"old": old, "new": new})
    return affected
