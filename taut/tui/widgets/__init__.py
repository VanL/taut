"""Widgets for the Taut TUI (spec: docs/specs/04-taut-tui.md [TUI-6])."""

from __future__ import annotations

from taut.tui.widgets._shared import TextStatic
from taut.tui.widgets.composer import Composer
from taut.tui.widgets.navigation import NavigationPane, NavRow, NavSection
from taut.tui.widgets.presence import PresencePane
from taut.tui.widgets.transcript import TranscriptView

__all__ = [
    "Composer",
    "NavRow",
    "NavSection",
    "NavigationPane",
    "PresencePane",
    "TextStatic",
    "TranscriptView",
]
