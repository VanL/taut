"""Typed row shapes for Taut-owned state."""

from __future__ import annotations

from typing import Any, Literal, TypedDict

ThreadKind = Literal["channel", "subthread", "dm", "notification", "system"]


class MemberRow(TypedDict):
    member_id: str
    display_name: str
    name_key: str
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


class IdentityClaimRow(TypedDict):
    claim_hash: str
    member_id: str
    claim_kind: str
    host_id: str | None
    host_label: str | None
    evidence: dict[str, Any]
    first_seen_ts: int
    last_seen_ts: int


class ThreadRow(TypedDict):
    name: str
    kind: str
    parent: str | None
    origin_ts: int | None
    created_by: str
    meta: dict[str, Any]
    created_ts: int


class MembershipRow(TypedDict):
    thread: str
    member_id: str
    joined_ts: int
    last_seen_ts: int


class ChannelRenameRow(TypedDict):
    old_name: str
    new_name: str
    state: str
    affected: list[dict[str, str]]
    started_ts: int
    updated_ts: int
