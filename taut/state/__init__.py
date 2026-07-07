"""Internal Taut state interface and SQL sidecar adapter.

Spec references:
- docs/specs/02-taut-core.md [TAUT-3.3], [TAUT-3.4], [TAUT-7.2], [TAUT-12.2]
"""

from __future__ import annotations

from typing import Any, Protocol

from taut.state._dialect import (
    PORTABLE_SQL_DIALECT,
    POSTGRES_SQL_DIALECT,
    SQLITE_SQL_DIALECT,
    SqlDialect,
    dialect_for_taut_target,
)
from taut.state._sql import SCHEMA_VERSION_KEY, SqlSidecarTautState
from taut.state._types import (
    ChannelRenameRow,
    IdentityClaimRow,
    MemberRow,
    MembershipRow,
    ThreadKind,
    ThreadRow,
)


class TautState(Protocol):
    """Internal state interface crossed by client and watcher code."""

    def ensure_schema(self) -> None: ...

    def get_schema_version(self) -> int | None: ...

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
    ) -> MemberRow: ...

    def update_member_activity(self, member_id: str, active_ts: int) -> None: ...

    def update_member_persona(
        self, member_id: str, persona: str | None
    ) -> MemberRow | None: ...

    def update_member_name(self, member_id: str, display_name: str) -> MemberRow: ...

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
    ) -> MemberRow: ...

    def add_member_alias(
        self, *, member_id: str, alias: str, created_ts: int
    ) -> None: ...

    def list_member_aliases(self, member_id: str) -> list[str]: ...

    def get_member(self, member_id: str) -> MemberRow | None: ...

    def get_member_by_route_key(self, key: str) -> MemberRow | None: ...

    def get_member_by_token(self, token: str) -> MemberRow | None: ...

    def get_member_by_uid(self, *, host_id: str, uid: int) -> MemberRow | None: ...

    def list_members(self) -> list[MemberRow]: ...

    def list_thread_members(self, thread: str) -> list[MemberRow]: ...

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
    ) -> IdentityClaimRow: ...

    def get_identity_claim(self, claim_hash: str) -> IdentityClaimRow | None: ...

    def get_member_by_claim_hash(self, claim_hash: str) -> MemberRow | None: ...

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
    ) -> ThreadRow: ...

    def get_thread(self, name: str) -> ThreadRow | None: ...

    def list_threads(self, *, include_internal: bool = False) -> list[ThreadRow]: ...

    def add_membership(
        self,
        *,
        thread: str,
        member_id: str,
        joined_ts: int,
        last_seen_ts: int,
    ) -> MembershipRow: ...

    def remove_membership(self, *, thread: str, member_id: str) -> bool: ...

    def get_membership(
        self, *, thread: str, member_id: str
    ) -> MembershipRow | None: ...

    def list_memberships(self, member_id: str) -> list[MembershipRow]: ...

    def list_thread_memberships(self, thread: str) -> list[MembershipRow]: ...

    def advance_cursor(self, *, thread: str, member_id: str, seen_ts: int) -> None: ...

    def start_channel_rename(
        self,
        *,
        old_name: str,
        new_name: str,
        affected: list[dict[str, str]],
        started_ts: int,
    ) -> ChannelRenameRow: ...

    def get_channel_rename(self, old_name: str) -> ChannelRenameRow | None: ...

    def incomplete_channel_renames(self) -> list[ChannelRenameRow]: ...

    def apply_channel_rename_state(
        self,
        *,
        old_name: str,
        new_name: str,
        affected: list[dict[str, str]],
        updated_ts: int,
    ) -> None: ...

    def member_names_in_use(self) -> set[str]: ...


__all__ = [
    "ChannelRenameRow",
    "IdentityClaimRow",
    "MemberRow",
    "MembershipRow",
    "PORTABLE_SQL_DIALECT",
    "POSTGRES_SQL_DIALECT",
    "SCHEMA_VERSION_KEY",
    "SQLITE_SQL_DIALECT",
    "SqlDialect",
    "SqlSidecarTautState",
    "TautState",
    "ThreadKind",
    "ThreadRow",
    "dialect_for_taut_target",
]
