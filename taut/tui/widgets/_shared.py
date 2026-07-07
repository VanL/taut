"""Shared widget primitives for the Taut TUI."""

from __future__ import annotations

from textual.widgets import Static

# Control characters that must never reach the terminal from remote content:
# all C0 except tab/newline (kept for multi-line labels like the help overlay),
# DEL, and the C1 range. Stripping them at the widget boundary neutralizes ANSI
# and OSC escape injection alongside the markup=False guard (review F1).
_ALLOWED_CONTROL = {"\n", "\t"}
_CONTROL_CHARS = frozenset(
    chr(codepoint)
    for codepoint in [*range(0x00, 0x20), 0x7F, *range(0x80, 0xA0)]
    if chr(codepoint) not in _ALLOWED_CONTROL
)
_CONTROL_TRANSLATION = {ord(char): None for char in _CONTROL_CHARS}


def sanitize_text(text: str) -> str:
    """Drop terminal control characters from untrusted text (review F1)."""

    return text.translate(_CONTROL_TRANSLATION)


class TextStatic(Static):
    """A Static that remembers its plain text for structural assertions.

    Tests assert on ``renderable_text`` (roles + substrings), never on
    rendered glyph output ([TUI-6.3]; testing-patterns Pattern 5).

    Remote-controlled strings (message bodies, sender/member names,
    notification fields) flow through here, so rendering is a trust
    boundary (review F1): ``markup=False`` stops a peer's ``[/]`` from
    raising ``MarkupError`` (a persistent crash-loop, since history
    re-renders on launch) and stops well-formed markup from spoofing
    separators/notices/links; :func:`sanitize_text` strips control-character
    (ANSI/OSC) injection. Trusted labels render identically under both.
    """

    def __init__(
        self,
        text: str = "",
        *,
        id: str | None = None,  # noqa: A002 - Textual's own keyword name
        classes: str | None = None,
    ) -> None:
        text = sanitize_text(text)
        super().__init__(text, id=id, classes=classes, markup=False)
        self._text = text

    def update_text(self, text: str) -> None:
        text = sanitize_text(text)
        self._text = text
        self.update(text)

    @property
    def renderable_text(self) -> str:
        return self._text
