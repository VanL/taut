"""User-authored chat text classification.

Spec reference: docs/specs/02-taut-core.md [TAUT-6.5].
"""

from __future__ import annotations

import unicodedata


def is_blank_message_text(text: str) -> bool:
    """Return whether built-in Unicode rules classify all text as blank."""

    return not text or all(
        character.isspace() or unicodedata.category(character) == "Cf"
        for character in text
    )
