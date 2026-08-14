"""Session-only view state owned by the human-first TUI extension.

This module deliberately contains no domain client, cursor, unread, storage,
or framework state. It is the immutable presentation state retained while the
same logical surfaces are rearranged.

Spec references:
- docs/specs/10-taut-tui.md [TUI-4.2], [TUI-4.3], [TUI-5.1], [TUI-9.2]
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import StrEnum


class InteractionMode(StrEnum):
    """The four visible interaction modes from [TUI-4.3]."""

    NORMAL = "NORMAL"
    COMPOSE = "COMPOSE"
    COMMAND = "COMMAND"
    SEARCH = "SEARCH"


class LayoutMode(StrEnum):
    """Physical arrangements selected only from terminal dimensions."""

    WIDE = "wide"
    MEDIUM = "medium"
    COMPACT = "compact"
    TOO_SMALL = "too-small"


class LogicalSurface(StrEnum):
    """Stable logical surfaces independent of their physical placement."""

    NAVIGATION = "navigation"
    CONVERSATION = "conversation"
    INSPECTOR = "inspector"
    RESIZE_HINT = "resize-hint"


class InspectorKind(StrEnum):
    """Version-1 inspector content kinds."""

    REPLIES = "replies"
    MEMBERS = "members"
    MESSAGE = "message"
    NOTIFICATIONS = "notifications"
    SYSTEM = "system"
    SUMMON = "summon"


@dataclass(frozen=True, slots=True)
class TerminalSize:
    """One observed terminal size."""

    width: int
    height: int

    def __post_init__(self) -> None:
        if self.width < 0 or self.height < 0:
            raise ValueError("terminal dimensions must be non-negative")


@dataclass(frozen=True, slots=True)
class FocusTarget:
    """Logical focus plus the stable widget/model key within that surface."""

    surface: LogicalSurface
    widget_id: str

    def __post_init__(self) -> None:
        if not self.widget_id:
            raise ValueError("focus widget_id must not be empty")


@dataclass(frozen=True, slots=True)
class DraftState:
    """One target-keyed single-line draft and editing cursor."""

    target: str
    text: str = ""
    cursor_position: int = 0
    revision: int = 0

    def __post_init__(self) -> None:
        if not self.target:
            raise ValueError("draft target must not be empty")
        if not 0 <= self.cursor_position <= len(self.text):
            raise ValueError("draft cursor_position must be within the text")
        if self.revision < 0:
            raise ValueError("draft revision must be non-negative")


@dataclass(frozen=True, slots=True)
class ScrollAnchor:
    """Tail pin or stable message-and-row-offset history anchor."""

    tail_pinned: bool
    message_id: int | None = None
    intra_row_offset: int = 0

    def __post_init__(self) -> None:
        if self.intra_row_offset < 0:
            raise ValueError("scroll intra_row_offset must be non-negative")
        if self.tail_pinned and (
            self.message_id is not None or self.intra_row_offset != 0
        ):
            raise ValueError("a tail-pinned anchor cannot name a history row")
        if self.message_id is not None and self.message_id <= 0:
            raise ValueError("scroll message_id must be positive")

    @classmethod
    def tail(cls) -> ScrollAnchor:
        return cls(tail_pinned=True)

    @classmethod
    def history(
        cls,
        message_id: int | None,
        *,
        intra_row_offset: int = 0,
    ) -> ScrollAnchor:
        return cls(
            tail_pinned=False,
            message_id=message_id,
            intra_row_offset=intra_row_offset,
        )


@dataclass(frozen=True, slots=True)
class InspectorState:
    """Open inspector kind and its optional stable selected-item key."""

    kind: InspectorKind
    selected_item: str | None = None


@dataclass(frozen=True, slots=True)
class VisualState:
    """All domain-free session state that resize and focus must preserve."""

    active_conversation: str | None = None
    open_reply_thread: str | None = None
    selected_navigation: str | None = None
    selected_message_id: int | None = None
    drafts: tuple[DraftState, ...] = ()
    command_input: str = ""
    search_input: str = ""
    mode: InteractionMode = InteractionMode.NORMAL
    pane_choice: LogicalSurface = LogicalSurface.CONVERSATION
    focus: FocusTarget = FocusTarget(LogicalSurface.CONVERSATION, "transcript")
    return_focus: FocusTarget | None = None
    inspector: InspectorState | None = None
    scroll_anchor: ScrollAnchor = field(default_factory=ScrollAnchor.tail)
    folded_groups: frozenset[str] = frozenset()
    model_generation: int = 0

    def __post_init__(self) -> None:
        targets = [draft.target for draft in self.drafts]
        if len(targets) != len(set(targets)):
            raise ValueError("draft targets must be unique")
        if self.pane_choice is LogicalSurface.RESIZE_HINT:
            raise ValueError("resize hint is not a selectable content pane")
        if self.selected_message_id is not None and self.selected_message_id <= 0:
            raise ValueError("selected_message_id must be positive")
        if self.model_generation < 0:
            raise ValueError("model_generation must be non-negative")

    def draft_for(self, target: str) -> DraftState | None:
        """Return the immutable draft for one public target, if any."""

        return next((draft for draft in self.drafts if draft.target == target), None)

    def with_draft(self, draft: DraftState) -> VisualState:
        """Replace one target draft without disturbing any other visual state."""

        remaining = tuple(item for item in self.drafts if item.target != draft.target)
        return replace(self, drafts=(*remaining, draft))


__all__ = [
    "DraftState",
    "FocusTarget",
    "InspectorKind",
    "InspectorState",
    "InteractionMode",
    "LayoutMode",
    "LogicalSurface",
    "ScrollAnchor",
    "TerminalSize",
    "VisualState",
]
