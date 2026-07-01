"""Taut chat envelope encode/decode.

Spec references:
- docs/specs/02-taut-core.md [TAUT-6]
- docs/specs/03-identity-addressing-notifications.md [IAN-4.5]
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Literal

EnvelopeKind = Literal["message", "notice"]
DecodedKind = Literal["message", "notice", "foreign"]


@dataclass(frozen=True, slots=True)
class DecodedEnvelope:
    """A body decoded into taut's rendering contract."""

    from_id: str | None
    from_name: str
    kind: DecodedKind
    text: str
    raw: str
    warning: str | None = None

    @property
    def is_foreign(self) -> bool:
        return self.kind == "foreign"


def encode_envelope(
    *,
    from_id: str,
    from_name: str,
    kind: EnvelopeKind,
    text: str,
) -> str:
    """Encode a taut chat envelope."""

    if kind not in ("message", "notice"):
        raise ValueError("kind must be 'message' or 'notice'")
    return json.dumps(
        {"from_id": from_id, "from": from_name, "kind": kind, "text": text},
        ensure_ascii=False,
        separators=(",", ":"),
    )


def decode_envelope(body: str) -> DecodedEnvelope:
    """Decode a broker body without raising on malformed or foreign input."""

    try:
        parsed: Any = json.loads(body)
    except (TypeError, json.JSONDecodeError):
        return _foreign(body)

    if not isinstance(parsed, dict):
        return _foreign(body)

    from_id = parsed.get("from_id")
    from_name = parsed.get("from")
    kind = parsed.get("kind")
    text = parsed.get("text")
    if (
        not isinstance(from_id, str)
        or not isinstance(from_name, str)
        or kind not in ("message", "notice")
        or not isinstance(text, str)
    ):
        return _foreign(body)

    return DecodedEnvelope(
        from_id=from_id,
        from_name=from_name,
        kind=kind,
        text=text,
        raw=body,
    )


def _foreign(body: str, *, warning: str | None = None) -> DecodedEnvelope:
    return DecodedEnvelope(
        from_id=None,
        from_name="?",
        kind="foreign",
        text=body,
        raw=body,
        warning=warning,
    )
