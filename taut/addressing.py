"""Conversation target parsing and internal queue-name helpers.

Spec references:
- docs/specs/03-identity-addressing-notifications.md [IAN-5], [IAN-6], [IAN-7]
"""

from __future__ import annotations

import base64
import hashlib
import re
from dataclasses import dataclass
from typing import Literal

from taut._constants import (
    MEMBER_ID_RE,
    MESSAGE_ID_RE,
    RESERVED_QUEUE_PREFIXES,
    route_key,
    validate_channel_name,
    validate_member_name,
)
from taut._exceptions import ThreadNameError

TargetKind = Literal["channel", "subthread", "dm"]

MENTION_RE = re.compile(r"(?<![A-Za-z0-9_-])@([A-Za-z0-9][A-Za-z0-9_-]{0,63})")


@dataclass(frozen=True, slots=True)
class TargetAddress:
    kind: TargetKind
    thread: str | None = None
    channel: str | None = None
    origin_ts: int | None = None
    route_key: str | None = None
    raw_route: str | None = None


def parse_target(value: str, *, allow_dm: bool = True) -> TargetAddress:
    """Parse a command conversation target."""

    if value.startswith("@"):
        if not allow_dm:
            raise ThreadNameError("direct-message targets are not valid here")
        raw = value[1:]
        try:
            validate_member_name(raw)
        except ValueError as exc:
            raise ThreadNameError(str(exc)) from exc
        return TargetAddress(kind="dm", route_key=route_key(raw), raw_route=raw)

    raw_thread = value[1:] if value.startswith("#") else value
    if "." in raw_thread:
        channel, dot, origin = raw_thread.partition(".")
        if not dot or "." in origin:
            raise ThreadNameError("sub-threads support exactly one level")
        try:
            validate_channel_name(channel)
        except ValueError as exc:
            raise ThreadNameError(str(exc)) from exc
        if MESSAGE_ID_RE.fullmatch(origin) is None:
            raise ThreadNameError(f"invalid sub-thread name: {raw_thread}")
        return TargetAddress(
            kind="subthread",
            thread=raw_thread,
            channel=channel,
            origin_ts=int(origin),
        )

    try:
        validate_channel_name(raw_thread)
    except ValueError as exc:
        raise ThreadNameError(str(exc)) from exc
    return TargetAddress(kind="channel", thread=raw_thread, channel=raw_thread)


def validate_chat_thread_name(value: str, *, allow_subthread: bool) -> str:
    """Validate and normalize a channel or sub-thread argument."""

    target = parse_target(value, allow_dm=False)
    if target.kind == "subthread" and not allow_subthread:
        raise ThreadNameError("sub-thread names are not valid channel names")
    if target.thread is None:
        raise ThreadNameError(f"invalid thread name: {value}")
    return target.thread


def classify_registered_queue(name: str) -> str:
    """Return the queue namespace class for a registered queue name."""

    if name.startswith("dm."):
        return "dm"
    if name.startswith("notify."):
        return "notification"
    if name.startswith("sys.") or name.startswith("taut."):
        return "system"
    if "." in name:
        return "subthread"
    return "channel"


def dm_queue_name(member_id_a: str, member_id_b: str) -> str:
    """Return the deterministic direct-message queue for two member ids."""

    _validate_member_id(member_id_a)
    _validate_member_id(member_id_b)
    first, second = sorted((member_id_a, member_id_b))
    digest = hashlib.sha256(
        b"taut-dm\0" + first.encode("utf-8") + b"\0" + second.encode("utf-8")
    ).digest()
    dm_id = _base32_lower(digest)[:26]
    return f"dm.d_{dm_id}"


def notification_queue_name(member_id: str) -> str:
    """Return the notification inbox queue for a member id."""

    _validate_member_id(member_id)
    return f"notify.{member_id}"


def mentioned_route_keys(text: str) -> list[tuple[str, str]]:
    """Return unique mention route keys and matched tokens in encounter order."""

    seen: set[str] = set()
    result: list[tuple[str, str]] = []
    for match in MENTION_RE.finditer(text):
        raw = match.group(1)
        key = route_key(raw)
        if key in seen:
            continue
        seen.add(key)
        result.append((key, "@" + raw))
    return result


def is_special_queue_name(name: str) -> bool:
    prefix = name.split(".", 1)[0]
    return prefix in RESERVED_QUEUE_PREFIXES


def _validate_member_id(member_id: str) -> None:
    if MEMBER_ID_RE.fullmatch(member_id) is None:
        raise ValueError(f"invalid member id: {member_id}")


def _base32_lower(raw: bytes) -> str:
    return base64.b32encode(raw).decode("ascii").lower().rstrip("=")
