from __future__ import annotations

import pytest

from taut._message_text import is_blank_message_text

pytestmark = pytest.mark.sqlite_only


@pytest.mark.parametrize(
    "text",
    [
        "",
        " \t\r\n",
        "\u00a0\u2003\u2028",
        "\u00ad",
        "\u200b\u200c\u200d",
        "\u2060\ufeff",
        "\u202a\u202c\u2066\u2069",
        " \u200b\t\u2060\n",
    ],
)
def test_blank_message_text_uses_builtin_whitespace_and_cf(text: str) -> None:
    """[TAUT-6.5] Common whitespace and format-only text is blank."""

    assert is_blank_message_text(text)


@pytest.mark.parametrize(
    "text",
    [
        "x",
        " \u200bvisible\u2060 ",
        "\U0001f469\u200d\U0001f4bb",
        "\ufe0f",
    ],
)
def test_nonblank_message_text_is_accepted_without_visibility_claim(text: str) -> None:
    """[TAUT-6.5] One nonblank character makes the exact string acceptable."""

    assert not is_blank_message_text(text)
