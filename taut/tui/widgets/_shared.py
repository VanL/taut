"""Shared widget primitives for the Taut TUI."""

from __future__ import annotations

from textual.widgets import Static


class TextStatic(Static):
    """A Static that remembers its plain text for structural assertions.

    Tests assert on ``renderable_text`` (roles + substrings), never on
    rendered glyph output ([TUI-6.3]; testing-patterns Pattern 5).
    """

    def __init__(
        self,
        text: str = "",
        *,
        id: str | None = None,  # noqa: A002 - Textual's own keyword name
        classes: str | None = None,
    ) -> None:
        super().__init__(text, id=id, classes=classes)
        self._text = text

    def update_text(self, text: str) -> None:
        self._text = text
        self.update(text)

    @property
    def renderable_text(self) -> str:
        return self._text
