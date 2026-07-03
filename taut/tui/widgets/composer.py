"""Composer: target-labelled input anchored below the transcript ([TUI-6.4])."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Input

from taut.tui.widgets._shared import TextStatic


class Composer(Vertical):
    def compose(self) -> ComposeResult:
        yield TextStatic("", id="composer-label")
        yield Input(placeholder="›", id="composer-input")

    def set_target_label(self, label: str) -> None:
        self.query_one("#composer-label", TextStatic).update_text(label)
