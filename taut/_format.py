"""Shared display formatting helpers.

Lives outside ``cli.py`` so the TUI widgets can format timestamps without
importing the argparse-heavy CLI module (review F7: removes the
widget → CLI layering inversion). Both ``taut.cli`` and ``taut.tui`` import
from here.
"""

from __future__ import annotations

from datetime import datetime


def format_message_time(ts: int) -> str:
    """Render a nanosecond timestamp as a local ``HH:MM`` clock label."""

    return datetime.fromtimestamp(ts / 1_000_000_000).strftime("%H:%M")
