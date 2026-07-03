"""Transcript pane: messages, notices, unread separator ([TUI-6.3])."""

from __future__ import annotations

from textual.containers import VerticalScroll
from textual.widget import Widget

from taut.cli import _format_message_time
from taut.client import Message
from taut.tui.widgets._shared import TextStatic


class TranscriptView(VerticalScroll):
    """The active conversation's reading surface.

    The unread separator is anchored at the caller-provided cursor value —
    the mount-time snapshot, never a re-read cursor ([TUI-10.8]).
    """

    async def show_conversation(
        self,
        *,
        header: str,
        messages: list[Message],
        cursor: int | None,
    ) -> None:
        await self.remove_children()
        rows: list[Widget] = [TextStatic(header, classes="transcript-header")]
        separator_placed = False
        for message in messages:
            if not separator_placed and cursor is not None and message.ts > cursor:
                rows.append(
                    TextStatic(
                        "── new messages ──",
                        classes="transcript-row separator",
                    )
                )
                separator_placed = True
            rows.append(self._row(message))
        if not messages:
            rows.append(TextStatic("no messages yet", classes="transcript-empty"))
        await self.mount_all(rows)

    async def append_message(self, message: Message) -> None:
        """Live tail: mount one row and keep the newest content visible."""

        await self.mount(self._row(message))
        self.scroll_end(animate=False)

    async def show_error(self, message: str) -> None:
        await self.remove_children()
        await self.mount(TextStatic(f"⚠ {message}", classes="error-banner"))

    def _row(self, message: Message) -> TextStatic:
        stamp = _format_message_time(message.ts)
        if message.kind == "notice":
            return TextStatic(
                f"{stamp}  · {message.text}",
                classes="transcript-row notice",
            )
        return TextStatic(
            f"{stamp}  {message.from_name}  {message.text}",
            classes="transcript-row message",
        )
