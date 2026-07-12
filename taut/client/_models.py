"""Public value objects returned by the Taut client API."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class Member:
    """Public member object."""

    member_id: str
    name: str
    aliases: tuple[str, ...]
    kind: str
    presence: str
    last_active_ts: int
    persona: str | None = None
    token: str | None = None
    explain: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class Thread:
    """Public thread object."""

    name: str
    parent: str | None
    unread: bool
    last_ts: int | None
    kind: str = "channel"
    unread_count: int = 0
    members: tuple[str, ...] = ()
    display_name: str | None = None


@dataclass(frozen=True, slots=True)
class Message:
    """Public chat message object."""

    thread: str
    ts: int
    from_id: str | None
    from_name: str
    kind: str
    text: str
    warning: str | None = None


@dataclass(frozen=True, slots=True)
class Notification:
    """A consumed notification pointer."""

    type: str
    to_id: str | None
    actor_id: str | None
    actor_name: str | None
    thread: str | None
    message_ts: int | None
    matched: str | None = None
    ts: int | None = None
    warning: str | None = None
    raw: str | None = None


@dataclass(frozen=True, slots=True)
class InitResult:
    """Result of ``taut init``."""

    db: str
    created: bool


# Keep public value-object introspection aligned with the facade import path.
Member.__module__ = "taut.client"
Thread.__module__ = "taut.client"
Message.__module__ = "taut.client"
Notification.__module__ = "taut.client"
InitResult.__module__ = "taut.client"
