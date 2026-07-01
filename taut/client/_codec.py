"""Internal message and notification decoding helpers."""

from __future__ import annotations

import json

from taut.envelope import DecodedEnvelope, decode_envelope

from ._models import Message, Notification


def message_from_body(thread: str, body: str, ts: int) -> Message:
    return message_from_decoded(thread, decode_envelope(body), ts)


def message_from_decoded(
    thread: str,
    decoded: DecodedEnvelope,
    ts: int,
) -> Message:
    return Message(
        thread=thread,
        ts=ts,
        from_id=decoded.from_id,
        from_name=decoded.from_name,
        kind=decoded.kind,
        text=decoded.text,
        warning=decoded.warning,
    )


def notification_from_body(body: str, ts: int) -> Notification:
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError:
        return Notification(
            type="foreign",
            to_id=None,
            actor_id=None,
            actor_name=None,
            thread=None,
            message_ts=None,
            ts=ts,
            warning="malformed notification",
            raw=body,
        )
    if not isinstance(parsed, dict):
        return Notification(
            type="foreign",
            to_id=None,
            actor_id=None,
            actor_name=None,
            thread=None,
            message_ts=None,
            ts=ts,
            warning="malformed notification",
            raw=body,
        )
    notification_type = parsed.get("type")
    to_id = parsed.get("to_id")
    actor_id = parsed.get("actor_id")
    actor_name = parsed.get("actor_name")
    thread = parsed.get("thread")
    message_ts = parsed.get("message_ts")
    matched = parsed.get("matched")
    if (
        notification_type not in {"mention", "dm_started"}
        or not isinstance(to_id, str)
        or not isinstance(actor_id, str)
        or not isinstance(actor_name, str)
        or not isinstance(thread, str)
        or not isinstance(message_ts, int)
        or (notification_type == "mention" and not isinstance(matched, str))
    ):
        return Notification(
            type="foreign",
            to_id=None,
            actor_id=None,
            actor_name=None,
            thread=None,
            message_ts=None,
            ts=ts,
            warning="malformed notification",
            raw=body,
        )
    return Notification(
        type=notification_type,
        to_id=to_id,
        actor_id=actor_id,
        actor_name=actor_name,
        thread=thread,
        message_ts=message_ts,
        matched=matched if isinstance(matched, str) else None,
        ts=ts,
        raw=body,
    )
