"""Pure responsive-layout and latest-wins transition planning.

No function in this module performs I/O, creates a task, touches a cursor, or
knows about domain clients. The Textual composition root applies one returned
plan in one UI batch.

Spec references:
- docs/specs/10-taut-tui.md [TUI-5], [TUI-9]
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from enum import StrEnum

from taut_tui.models import (
    FocusTarget,
    LayoutMode,
    LogicalSurface,
    TerminalSize,
    VisualState,
)


class TranscriptMetadataLayout(StrEnum):
    ALIGNED = "aligned"
    STACKED = "stacked"
    HIDDEN = "hidden"


@dataclass(frozen=True, slots=True)
class SurfaceRegion:
    surface: LogicalSurface
    columns: int

    def __post_init__(self) -> None:
        if self.columns < 0:
            raise ValueError("surface columns must be non-negative")


@dataclass(frozen=True, slots=True)
class LayoutPlacement:
    mode: LayoutMode
    regions: tuple[SurfaceRegion, ...]

    @property
    def visible_surfaces(self) -> tuple[LogicalSurface, ...]:
        return tuple(region.surface for region in self.regions)


@dataclass(frozen=True, slots=True)
class LayoutTransition:
    from_mode: LayoutMode
    to_mode: LayoutMode
    accepted_size: TerminalSize
    placement: LayoutPlacement
    state: VisualState
    focus_moved: bool
    observed_resize_count: int = 1
    layout_passes: int = 1


def layout_mode(width: int, height: int) -> LayoutMode:
    """Return the exact [TUI-9.1] layout mode for a terminal size."""

    size = TerminalSize(width, height)
    if size.width < 50 or size.height < 20:
        return LayoutMode.TOO_SMALL
    if size.width < 80:
        return LayoutMode.COMPACT
    if size.width < 120:
        return LayoutMode.MEDIUM
    return LayoutMode.WIDE


def _compact_surface(state: VisualState) -> LogicalSurface:
    if state.pane_choice is LogicalSurface.INSPECTOR and state.inspector is None:
        return LogicalSurface.CONVERSATION
    return state.pane_choice


def layout_placement(size: TerminalSize, state: VisualState) -> LayoutPlacement:
    """Arrange the current logical surfaces without mutating view state."""

    mode = layout_mode(size.width, size.height)
    regions: tuple[SurfaceRegion, ...]
    if mode is LayoutMode.TOO_SMALL:
        regions = (SurfaceRegion(LogicalSurface.RESIZE_HINT, size.width),)
    elif mode is LayoutMode.COMPACT:
        regions = (SurfaceRegion(_compact_surface(state), size.width),)
    elif mode is LayoutMode.MEDIUM:
        side_columns = min(30, max(20, size.width // 3))
        conversation_columns = size.width - side_columns
        inspector_selected = state.inspector is not None and (
            state.pane_choice is LogicalSurface.INSPECTOR
            or state.focus.surface is LogicalSurface.INSPECTOR
        )
        if not inspector_selected:
            regions = (
                SurfaceRegion(LogicalSurface.NAVIGATION, side_columns),
                SurfaceRegion(LogicalSurface.CONVERSATION, conversation_columns),
            )
        else:
            regions = (
                SurfaceRegion(LogicalSurface.CONVERSATION, conversation_columns),
                SurfaceRegion(LogicalSurface.INSPECTOR, side_columns),
            )
    else:
        navigation_columns = min(30, max(20, size.width // 5))
        inspector_columns = min(36, max(24, size.width // 4))
        conversation_columns = size.width - navigation_columns - inspector_columns
        regions = (
            SurfaceRegion(LogicalSurface.NAVIGATION, navigation_columns),
            SurfaceRegion(LogicalSurface.CONVERSATION, conversation_columns),
            SurfaceRegion(LogicalSurface.INSPECTOR, inspector_columns),
        )
    return LayoutPlacement(mode=mode, regions=regions)


def transcript_metadata_layout(mode: LayoutMode) -> TranscriptMetadataLayout:
    if mode in (LayoutMode.WIDE, LayoutMode.MEDIUM):
        return TranscriptMetadataLayout.ALIGNED
    if mode is LayoutMode.COMPACT:
        return TranscriptMetadataLayout.STACKED
    return TranscriptMetadataLayout.HIDDEN


def _fallback_focus(placement: LayoutPlacement) -> FocusTarget:
    preferred = (
        LogicalSurface.CONVERSATION
        if LogicalSurface.CONVERSATION in placement.visible_surfaces
        else placement.visible_surfaces[0]
    )
    widget_by_surface = {
        LogicalSurface.NAVIGATION: "navigation",
        LogicalSurface.CONVERSATION: "transcript",
        LogicalSurface.INSPECTOR: "inspector",
        LogicalSurface.RESIZE_HINT: "resize-hint",
    }
    return FocusTarget(preferred, widget_by_surface[preferred])


def _prepare_for_compact(state: VisualState) -> VisualState:
    focused = state.focus.surface
    if focused in (LogicalSurface.NAVIGATION, LogicalSurface.CONVERSATION):
        return replace(state, pane_choice=focused)
    if focused is LogicalSurface.INSPECTOR and state.inspector is not None:
        return replace(state, pane_choice=focused)
    return state


def transition_layout(
    state: VisualState,
    *,
    current_size: TerminalSize,
    new_size: TerminalSize,
    observed_resize_count: int = 1,
) -> LayoutTransition:
    """Build one state-preserving plan for the accepted terminal size."""

    if observed_resize_count <= 0:
        raise ValueError("observed_resize_count must be positive")
    from_mode = layout_mode(current_size.width, current_size.height)
    to_mode = layout_mode(new_size.width, new_size.height)
    next_state = state

    if to_mode is LayoutMode.TOO_SMALL:
        return_focus = (
            state.focus
            if state.focus.surface is not LogicalSurface.RESIZE_HINT
            else state.return_focus
        )
        next_state = replace(
            state,
            focus=FocusTarget(LogicalSurface.RESIZE_HINT, "resize-hint"),
            return_focus=return_focus,
        )
    else:
        if from_mode is LayoutMode.TOO_SMALL:
            next_state = replace(
                state,
                focus=state.return_focus
                or FocusTarget(LogicalSurface.CONVERSATION, "transcript"),
                return_focus=None,
            )
        if to_mode is LayoutMode.COMPACT:
            next_state = _prepare_for_compact(next_state)

    placement = layout_placement(new_size, next_state)
    if next_state.focus.surface not in placement.visible_surfaces:
        next_state = replace(next_state, focus=_fallback_focus(placement))
        placement = layout_placement(new_size, next_state)

    return LayoutTransition(
        from_mode=from_mode,
        to_mode=to_mode,
        accepted_size=new_size,
        placement=placement,
        state=next_state,
        focus_moved=next_state.focus != state.focus,
        observed_resize_count=observed_resize_count,
    )


def plan_latest_resize(
    state: VisualState,
    *,
    current_size: TerminalSize,
    observed_sizes: Sequence[TerminalSize],
) -> LayoutTransition:
    """Coalesce a burst into one synchronous plan for its latest size."""

    if not observed_sizes:
        raise ValueError("a resize burst must contain at least one size")
    return transition_layout(
        state,
        current_size=current_size,
        new_size=observed_sizes[-1],
        observed_resize_count=len(observed_sizes),
    )


__all__ = [
    "LayoutPlacement",
    "LayoutTransition",
    "SurfaceRegion",
    "TranscriptMetadataLayout",
    "layout_mode",
    "layout_placement",
    "plan_latest_resize",
    "transcript_metadata_layout",
    "transition_layout",
]
