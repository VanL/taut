"""Presence pane: members, presence state, acting member ([TUI-6.5])."""

from __future__ import annotations

from textual.containers import VerticalScroll
from textual.widget import Widget

from taut.client import Member
from taut.tui.widgets._shared import TextStatic


class PresencePane(VerticalScroll):
    async def show_members(self, *, members: list[Member], me: Member | None) -> None:
        await self.remove_children()
        here = sum(1 for member in members if member.presence == "here")
        rows: list[Widget] = [
            TextStatic(f"Members · here {here}", classes="presence-header")
        ]
        for member in members:
            dot = "●" if member.presence == "here" else "○"
            # Presence is text, never color/glyph-only ([TUI-8.4]).
            rows.append(
                TextStatic(
                    f"{dot} {member.name} {member.presence}",
                    classes="member-row",
                )
            )
        if me is not None:
            rows.append(TextStatic(f"You: ● {me.name} · {me.kind}", id="presence-you"))
        await self.mount_all(rows)
