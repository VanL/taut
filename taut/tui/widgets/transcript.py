"""Transcript pane: messages, notices, unread separator ([TUI-6.3])."""

from __future__ import annotations

from textual.containers import VerticalScroll
from textual.widget import Widget

from taut._format import format_message_time
from taut.client import Message, Thread
from taut.tui.widgets._shared import TextStatic


class TranscriptView(VerticalScroll):
    """The active conversation's reading surface.

    The unread separator is anchored at the caller-provided cursor value —
    the mount-time snapshot, never a re-read cursor ([TUI-10.8]). Inline
    sub-threads render under their parent message ([TUI-7.1]); folding is
    display-only ([TUI-7.2]).
    """

    async def show_conversation(
        self,
        *,
        header: str,
        messages: list[Message],
        cursor: int | None,
        inline_threads: list[Thread] | None = None,
        folded: set[str] | None = None,
        thread_replies: dict[str, list[Message]] | None = None,
    ) -> None:
        await self.remove_children()
        by_origin = {
            sub.origin_ts: sub
            for sub in (inline_threads or [])
            if sub.origin_ts is not None
        }
        folded = folded or set()
        thread_replies = thread_replies or {}
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
            sub = by_origin.get(message.ts)
            if sub is not None:
                fold_hint = "z unfold" if sub.name in folded else "z fold"
                rows.append(
                    TextStatic(
                        f"↳ {sub.name} · {sub.reply_count} replies · {fold_hint}",
                        classes="thread-stub",
                    )
                )
                if sub.name not in folded:
                    for reply in thread_replies.get(sub.name, []):
                        rows.append(
                            TextStatic(
                                f"    {format_message_time(reply.ts)}  "
                                f"{reply.from_name}  {reply.text}",
                                classes="thread-reply",
                            )
                        )
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
        stamp = format_message_time(message.ts)
        if message.kind == "notice":
            return TextStatic(
                f"{stamp}  · {message.text}",
                classes="transcript-row notice",
            )
        return TextStatic(
            f"{stamp}  {message.from_name}  {message.text}",
            classes="transcript-row message",
        )
