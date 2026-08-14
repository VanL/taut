"""State-preserving latest-wins resize transitions for the TUI extension.

Spec references:
- docs/specs/10-taut-tui.md [TUI-4.2], [TUI-4.3], [TUI-9.2], [TUI-9.3]
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from taut_tui.layout import plan_latest_resize, transition_layout
from taut_tui.models import (
    DraftState,
    FocusTarget,
    InspectorKind,
    InspectorState,
    InteractionMode,
    LayoutMode,
    LogicalSurface,
    ScrollAnchor,
    TerminalSize,
    VisualState,
)

pytestmark = pytest.mark.sqlite_only


def rich_state(*, tail_pinned: bool = False) -> VisualState:
    return VisualState(
        active_conversation="general",
        open_reply_thread="general.t_1234567890123456789",
        selected_navigation="channel:general",
        selected_message_id=1234567890123456799,
        drafts=(
            DraftState(
                target="general",
                text="draft text",
                cursor_position=6,
                revision=4,
            ),
        ),
        command_input="rename",
        search_input="watermark",
        mode=InteractionMode.SEARCH,
        pane_choice=LogicalSurface.INSPECTOR,
        focus=FocusTarget(LogicalSurface.INSPECTOR, "reply-list"),
        inspector=InspectorState(
            InspectorKind.REPLIES,
            selected_item="reply:1234567890123456799",
        ),
        scroll_anchor=(
            ScrollAnchor.tail()
            if tail_pinned
            else ScrollAnchor.history(1234567890123456789, intra_row_offset=3)
        ),
        folded_groups=frozenset({"author:bot"}),
        model_generation=7,
    )


PRESERVED_FIELDS = (
    "active_conversation",
    "open_reply_thread",
    "selected_navigation",
    "selected_message_id",
    "drafts",
    "command_input",
    "search_input",
    "mode",
    "inspector",
    "scroll_anchor",
    "folded_groups",
    "model_generation",
)


@pytest.mark.parametrize(
    ("start", "end", "from_mode", "to_mode"),
    [
        (
            TerminalSize(120, 20),
            TerminalSize(119, 20),
            LayoutMode.WIDE,
            LayoutMode.MEDIUM,
        ),
        (
            TerminalSize(119, 20),
            TerminalSize(120, 20),
            LayoutMode.MEDIUM,
            LayoutMode.WIDE,
        ),
        (
            TerminalSize(80, 20),
            TerminalSize(79, 20),
            LayoutMode.MEDIUM,
            LayoutMode.COMPACT,
        ),
        (
            TerminalSize(79, 20),
            TerminalSize(80, 20),
            LayoutMode.COMPACT,
            LayoutMode.MEDIUM,
        ),
        (
            TerminalSize(50, 20),
            TerminalSize(49, 20),
            LayoutMode.COMPACT,
            LayoutMode.TOO_SMALL,
        ),
        (
            TerminalSize(49, 20),
            TerminalSize(50, 20),
            LayoutMode.TOO_SMALL,
            LayoutMode.COMPACT,
        ),
        (
            TerminalSize(120, 20),
            TerminalSize(120, 19),
            LayoutMode.WIDE,
            LayoutMode.TOO_SMALL,
        ),
        (
            TerminalSize(120, 19),
            TerminalSize(120, 20),
            LayoutMode.TOO_SMALL,
            LayoutMode.WIDE,
        ),
    ],
)
def test_every_boundary_preserves_session_state_in_both_directions(
    start: TerminalSize,
    end: TerminalSize,
    from_mode: LayoutMode,
    to_mode: LayoutMode,
) -> None:
    before = rich_state()
    transition = transition_layout(before, current_size=start, new_size=end)

    assert transition.from_mode is from_mode
    assert transition.to_mode is to_mode
    for field in PRESERVED_FIELDS:
        assert getattr(transition.state, field) == getattr(before, field)


@pytest.mark.parametrize("tail_pinned", [False, True])
def test_scroll_anchor_semantics_survive_rewrap(tail_pinned: bool) -> None:
    before = rich_state(tail_pinned=tail_pinned)

    transition = transition_layout(
        before,
        current_size=TerminalSize(130, 34),
        new_size=TerminalSize(64, 34),
    )

    assert transition.state.scroll_anchor == before.scroll_anchor
    assert transition.state.scroll_anchor.tail_pinned is tail_pinned


def test_visible_focus_keeps_exact_widget_identity() -> None:
    before = replace(
        rich_state(),
        focus=FocusTarget(LogicalSurface.CONVERSATION, "composer-input"),
    )

    transition = transition_layout(
        before,
        current_size=TerminalSize(130, 34),
        new_size=TerminalSize(100, 34),
    )

    assert transition.state.focus == before.focus
    assert transition.focus_moved is False


def test_compact_reflow_keeps_focused_logical_surface_as_pane() -> None:
    before = rich_state()

    transition = transition_layout(
        before,
        current_size=TerminalSize(130, 34),
        new_size=TerminalSize(64, 34),
    )

    assert transition.state.focus == before.focus
    assert transition.state.pane_choice is LogicalSurface.INSPECTOR
    assert transition.placement.visible_surfaces == (LogicalSurface.INSPECTOR,)


def test_hidden_medium_navigation_focus_moves_deterministically() -> None:
    before = replace(
        rich_state(),
        focus=FocusTarget(LogicalSurface.NAVIGATION, "channel:general"),
    )

    transition = transition_layout(
        before,
        current_size=TerminalSize(130, 34),
        new_size=TerminalSize(100, 34),
    )

    assert transition.state.focus == FocusTarget(
        LogicalSurface.CONVERSATION,
        "transcript",
    )
    assert transition.focus_moved is True


def test_too_small_focus_returns_to_exact_prior_widget() -> None:
    before = rich_state()
    hidden = transition_layout(
        before,
        current_size=TerminalSize(130, 34),
        new_size=TerminalSize(40, 15),
    )

    assert hidden.state.focus == FocusTarget(LogicalSurface.RESIZE_HINT, "resize-hint")
    assert hidden.state.return_focus == before.focus

    recovered = transition_layout(
        hidden.state,
        current_size=TerminalSize(40, 15),
        new_size=TerminalSize(130, 34),
    )

    assert recovered.state.focus == before.focus
    assert recovered.state.return_focus is None


def test_rapid_resize_burst_builds_one_plan_for_latest_size() -> None:
    before = rich_state()
    sizes = (
        TerminalSize(119, 20),
        TerminalSize(79, 20),
        TerminalSize(49, 19),
        TerminalSize(80, 20),
        TerminalSize(64, 34),
    )

    transition = plan_latest_resize(
        before,
        current_size=TerminalSize(130, 34),
        observed_sizes=sizes,
    )

    assert transition.accepted_size == sizes[-1]
    assert transition.to_mode is LayoutMode.COMPACT
    assert transition.observed_resize_count == len(sizes)
    assert transition.layout_passes == 1


def test_model_updates_accumulate_while_too_small_and_render_on_recovery() -> None:
    hidden = transition_layout(
        rich_state(),
        current_size=TerminalSize(130, 34),
        new_size=TerminalSize(40, 15),
    )
    updated = replace(
        hidden.state,
        selected_message_id=1234567890123456888,
        model_generation=8,
    )

    recovered = transition_layout(
        updated,
        current_size=TerminalSize(40, 15),
        new_size=TerminalSize(100, 34),
    )

    assert recovered.state.model_generation == 8
    assert recovered.state.selected_message_id == 1234567890123456888
    assert LogicalSurface.CONVERSATION in recovered.placement.visible_surfaces
