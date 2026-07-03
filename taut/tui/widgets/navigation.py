"""Navigation pane: channels, direct messages, threads, inbox ([TUI-6.2])."""

from __future__ import annotations

from textual.widgets import ListItem, ListView

from taut.tui.widgets._shared import TextStatic


class NavRow(ListItem):
    """A selectable navigation target row."""

    def __init__(self, *, target: str, label: str, classes: str = "") -> None:
        super().__init__(TextStatic(label), classes=classes)
        self.target: str = target
        self._label = label

    @property
    def renderable_text(self) -> str:
        return self._label

    def set_label(self, label: str) -> None:
        self._label = label
        self.query_one(TextStatic).update_text(label)


class NavSection(ListItem):
    """A non-selectable section header row."""

    def __init__(self, title: str) -> None:
        super().__init__(TextStatic(title), classes="nav-section", disabled=True)
        self._title = title

    @property
    def renderable_text(self) -> str:
        return self._title


class NavigationPane(ListView):
    """Single keyboard-navigable list with section headers ([TUI-8.1])."""

    async def set_rows(self, rows: list[ListItem]) -> None:
        await self.clear()
        for row in rows:
            await self.append(row)
