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

from taut_tui.viewport import TranscriptViewport


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
    """One target-keyed multiline draft and scalar editing cursor."""

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
class RecoveredDraft:
    """A displaced draft retained for explicit, session-local recovery."""

    recovery_id: str
    draft: DraftState
    intended_target: str
    reason: str

    def __post_init__(self) -> None:
        if not self.recovery_id:
            raise ValueError("recovery_id must not be empty")
        if not self.intended_target:
            raise ValueError("recovery intended_target must not be empty")
        if not self.reason:
            raise ValueError("recovery reason must not be empty")


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
    recovered_drafts: tuple[RecoveredDraft, ...] = ()
    next_recovery_id: int = 1
    command_input: str = ""
    search_input: str = ""
    mode: InteractionMode = InteractionMode.NORMAL
    pane_choice: LogicalSurface = LogicalSurface.CONVERSATION
    focus: FocusTarget = FocusTarget(LogicalSurface.CONVERSATION, "transcript")
    return_focus: FocusTarget | None = None
    inspector: InspectorState | None = None
    viewport: TranscriptViewport = field(default_factory=TranscriptViewport.tail)
    folded_groups: frozenset[str] = frozenset()
    model_generation: int = 0

    def __post_init__(self) -> None:
        targets = [draft.target for draft in self.drafts]
        if len(targets) != len(set(targets)):
            raise ValueError("draft targets must be unique")
        recovery_ids = [item.recovery_id for item in self.recovered_drafts]
        if len(recovery_ids) != len(set(recovery_ids)):
            raise ValueError("recovery ids must be unique")
        if self.next_recovery_id < 1:
            raise ValueError("next_recovery_id must be positive")
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

    def after_channel_rename(
        self,
        old_name: str,
        new_name: str,
        *,
        remap_open_view: bool,
        minimum_revision: int | None = None,
    ) -> VisualState:
        """Move affected drafts and, when owned, the open channel projection."""

        drafts: dict[str, DraftState] = {}
        recoveries = self.recovered_drafts
        next_recovery_id = self.next_recovery_id
        moved: list[DraftState] = []
        for draft in self.drafts:
            mapped = remap_channel_target(draft.target, old_name, new_name)
            assert mapped is not None
            if mapped != draft.target:
                moved.append(replace(draft, target=mapped))
            else:
                drafts[draft.target] = draft
        # Mapped source drafts own the destination. Preserve any nonempty draft
        # they displace for explicit recovery, including whitespace-only text.
        for draft in moved:
            displaced = drafts.get(draft.target)
            if displaced is not None and displaced.text:
                recoveries, next_recovery_id = _append_recovery(
                    recoveries,
                    displaced,
                    next_recovery_id=next_recovery_id,
                    intended_target=draft.target,
                    reason="channel rename replaced an existing draft",
                )
            destination_revision = displaced.revision if displaced is not None else 0
            if displaced is not None or minimum_revision is not None:
                draft = replace(
                    draft,
                    revision=max(
                        draft.revision,
                        destination_revision,
                        minimum_revision or 0,
                    )
                    + 1,
                )
            drafts[draft.target] = draft
        if not remap_open_view:
            return replace(
                self,
                drafts=tuple(drafts.values()),
                recovered_drafts=recoveries,
                next_recovery_id=next_recovery_id,
            )
        return replace(
            self,
            drafts=tuple(drafts.values()),
            recovered_drafts=recoveries,
            next_recovery_id=next_recovery_id,
            active_conversation=remap_channel_target(
                self.active_conversation, old_name, new_name
            ),
            open_reply_thread=remap_channel_target(
                self.open_reply_thread, old_name, new_name
            ),
            selected_navigation=remap_channel_target(
                self.selected_navigation, old_name, new_name
            ),
        )

    def load_recovered_draft(
        self, recovery_id: str, *, minimum_revision: int | None = None
    ) -> VisualState:
        """Install one recovery and retain any occupied destination draft."""

        selected = next(
            (item for item in self.recovered_drafts if item.recovery_id == recovery_id),
            None,
        )
        if selected is None:
            raise KeyError(f"unknown recovered draft {recovery_id!r}")
        recoveries = tuple(
            item for item in self.recovered_drafts if item.recovery_id != recovery_id
        )
        occupied = self.draft_for(selected.intended_target)
        next_recovery_id = self.next_recovery_id
        if occupied is not None and occupied.text:
            recoveries, next_recovery_id = _append_recovery(
                recoveries,
                occupied,
                next_recovery_id=next_recovery_id,
                intended_target=selected.intended_target,
                reason="draft recovery replaced an existing draft",
            )
        max_revision = max(
            (
                draft.revision
                for draft in (
                    *self.drafts,
                    *(item.draft for item in self.recovered_drafts),
                )
            ),
            default=0,
        )
        loaded = replace(
            selected.draft,
            target=selected.intended_target,
            revision=max(
                max_revision,
                selected.draft.revision,
                minimum_revision or 0,
            )
            + 1,
        )
        remaining = tuple(
            draft for draft in self.drafts if draft.target != selected.intended_target
        )
        return replace(
            self,
            drafts=(*remaining, loaded),
            recovered_drafts=recoveries,
            next_recovery_id=next_recovery_id,
        )


def _append_recovery(
    recoveries: tuple[RecoveredDraft, ...],
    draft: DraftState,
    *,
    next_recovery_id: int,
    intended_target: str,
    reason: str,
) -> tuple[tuple[RecoveredDraft, ...], int]:
    recovery_id = f"draft-{next_recovery_id}"
    return (
        (
            *recoveries,
            RecoveredDraft(
                recovery_id=recovery_id,
                draft=draft,
                intended_target=intended_target,
                reason=reason,
            ),
        ),
        next_recovery_id + 1,
    )


def remap_channel_target(
    target: str | None,
    old_name: str,
    new_name: str,
) -> str | None:
    """Map one exact channel root or descendant to a returned rename target."""

    if target == old_name:
        return new_name
    prefix = f"{old_name}."
    if target is not None and target.startswith(prefix):
        return f"{new_name}{target[len(old_name) :]}"
    return target


__all__ = [
    "DraftState",
    "FocusTarget",
    "InspectorKind",
    "InspectorState",
    "InteractionMode",
    "LayoutMode",
    "LogicalSurface",
    "RecoveredDraft",
    "TerminalSize",
    "VisualState",
    "remap_channel_target",
]
