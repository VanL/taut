"""Isolated research-preview Claude channel notification adapter."""

from __future__ import annotations

from typing import Literal, cast

from mcp import types
from mcp.server.session import ServerSession

CLAUDE_CHANNEL_METHOD: Literal["notifications/claude/channel"] = (
    "notifications/claude/channel"
)
CLAUDE_CHANNEL_CUE = "Taut notifications changed; read taut://notifications/current."


class ClaudeChannelParams(types.NotificationParams):
    """The fixed, metadata-free channel payload."""

    content: str


class ClaudeChannelNotification(
    types.Notification[
        ClaudeChannelParams,
        Literal["notifications/claude/channel"],
    ]
):
    """Experimental notification shape understood by capable Claude hosts."""

    method: Literal["notifications/claude/channel"] = CLAUDE_CHANNEL_METHOD
    params: ClaudeChannelParams


async def send_claude_channel(session: ServerSession) -> None:
    """Send one fixed best-effort wake through the public SDK session API."""

    notification = ClaudeChannelNotification(
        params=ClaudeChannelParams(content=CLAUDE_CHANNEL_CUE)
    )
    await session.send_notification(cast(types.ServerNotification, notification))
