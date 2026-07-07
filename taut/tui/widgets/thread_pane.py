"""Right-side thread pane: parent context, replies, reply composer ([TUI-7.3])."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.widgets import Input

from taut._format import format_message_time
from taut.client import Message
from taut.tui.widgets._shared import TextStatic


class ThreadPane(Vertical):
    """Borrows the presence column while open; Escape closes it."""

    def compose(self) -> ComposeResult:
        yield TextStatic("", id="thread-pane-label")
        yield TextStatic("", id="thread-pane-parent")
        yield VerticalScroll(id="thread-pane-replies")
        yield Input(placeholder="›", id="thread-pane-input")

    async def show_thread(
        self,
        *,
        name: str,
        parent_text: str,
        replies: list[Message],
    ) -> None:
        self.query_one("#thread-pane-label", TextStatic).update_text(
            f"↳ reply in {name} · esc closes"
        )
        self.query_one("#thread-pane-parent", TextStatic).update_text(parent_text)
        container = self.query_one("#thread-pane-replies", VerticalScroll)
        await container.remove_children()
        rows = [
            TextStatic(
                f"{format_message_time(reply.ts)}  {reply.from_name}  {reply.text}",
                classes="thread-reply",
            )
            for reply in replies
        ]
        await container.mount_all(rows)
