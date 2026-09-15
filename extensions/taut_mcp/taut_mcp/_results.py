"""Shared result plumbing: record types and the result object.

Governed by [MCP-6]. Imports only the standard library so the manifest stays
importable without the Taut client.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

MESSAGE_ID_PATTERN = r"^[0-9]{19}$"

RECORD_TYPE_BY_TOOL: dict[str, str] = {
    "attach_workspace": "workspace",
    "detach_workspace": "workspace",
    "list_workspaces": "workspace",
    "join": "message",
    "leave": "message",
    "set_name": "member",
    "say": "message",
    "reply": "message",
    "message_show": "message",
    "message_delete": "deletion",
    "message_react": "reaction",
    "read": "message",
    "inbox": "notification",
    "log": "message",
    "search": "search_hit",
    "list": "thread",
    "channel_show": "channel",
    "channel_topic": "channel",
    "channel_rename": "thread",
    "who": "member",
    "whoami": "member",
}
DOMAIN_TOOL_NAMES: frozenset[str] = frozenset(RECORD_TYPE_BY_TOOL) - {
    "attach_workspace",
    "detach_workspace",
    "list_workspaces",
}


def tool_result(
    records: Sequence[dict[str, Any]],
    *,
    warnings: Sequence[str] = (),
) -> dict[str, Any]:
    """Build the one [MCP-6] result object; ``warnings`` appears only if nonempty."""

    payload: dict[str, Any] = {"records": list(records)}
    if warnings:
        payload["warnings"] = list(warnings)
    return payload
