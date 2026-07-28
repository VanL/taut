"""Channel-topic metadata validation.

Spec reference: docs/specs/02-taut-core.md [TAUT-4.4].
"""

from __future__ import annotations

from typing import Any, TypedDict

from simplebroker.ext import TimestampError, TimestampGenerator

from taut._constants import MEMBER_ID_RE
from taut._exceptions import TautError
from taut._message_text import is_blank_message_text

CHANNEL_TOPIC_KEYS = frozenset({"text", "updated_ts", "updated_by_id"})


class ChannelTopicRecord(TypedDict):
    """The exact persisted value stored below ``taut_threads.meta.topic``."""

    text: str
    updated_ts: int
    updated_by_id: str


def validate_channel_topic_text(topic: object) -> str | None:
    """Validate one public topic mutation value without rewriting it."""

    if topic is None:
        return None
    if not isinstance(topic, str):
        raise TypeError("topic must be a string or None")
    if is_blank_message_text(topic):
        raise ValueError("topic must not be blank")
    if "\r" in topic or "\n" in topic:
        raise ValueError("topic must be one line")
    if len(topic) > 500:
        raise ValueError("topic must be at most 500 Unicode code points")
    return topic


def decode_channel_topic(
    meta: dict[str, Any],
    *,
    context: str = "taut_threads.meta.topic",
) -> ChannelTopicRecord | None:
    """Decode the exact topic object, rejecting incompatible stored shapes."""

    if "topic" not in meta:
        return None
    raw = meta["topic"]
    if not isinstance(raw, dict):
        raise TautError(f"{context}: expected an object")
    if set(raw) != CHANNEL_TOPIC_KEYS:
        raise TautError(
            f"{context}: expected exactly text, updated_ts, and updated_by_id"
        )
    text = raw["text"]
    updated_ts = raw["updated_ts"]
    updated_by_id = raw["updated_by_id"]
    if not isinstance(text, str):
        raise TautError(f"{context}.text: expected a string")
    try:
        validate_channel_topic_text(text)
    except (TypeError, ValueError) as exc:
        raise TautError(f"{context}.text: {exc}") from exc
    if isinstance(updated_ts, bool) or not isinstance(updated_ts, int):
        raise TautError(f"{context}.updated_ts: expected an integer")
    try:
        TimestampGenerator.validate(str(updated_ts), exact=True)
    except TimestampError as exc:
        raise TautError(f"{context}.updated_ts: expected a Taut timestamp") from exc
    if (
        not isinstance(updated_by_id, str)
        or MEMBER_ID_RE.fullmatch(updated_by_id) is None
    ):
        raise TautError(f"{context}.updated_by_id: expected a member id")
    return {
        "text": text,
        "updated_ts": updated_ts,
        "updated_by_id": updated_by_id,
    }


def require_topic_compatible_kind(*, kind: str, meta: dict[str, Any]) -> None:
    """Reject topic metadata outside a registered top-level channel."""

    if kind != "channel" and "topic" in meta:
        raise TautError(
            "taut_threads.meta.topic: topic metadata belongs only to channels"
        )
