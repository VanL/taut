"""Pure responsive-layout contracts for the TUI extension.

Spec references:
- docs/specs/10-taut-tui.md [TUI-5], [TUI-9.1]
"""

from __future__ import annotations

import pytest

from taut_tui.layout import (
    TranscriptMetadataLayout,
    layout_mode,
    layout_placement,
    transcript_metadata_layout,
)
from taut_tui.models import (
    FocusTarget,
    InspectorKind,
    InspectorState,
    LayoutMode,
    LogicalSurface,
    TerminalSize,
    VisualState,
)

pytestmark = pytest.mark.sqlite_only


@pytest.mark.parametrize(
    ("width", "height", "expected"),
    [
        (49, 20, LayoutMode.TOO_SMALL),
        (50, 20, LayoutMode.COMPACT),
        (79, 20, LayoutMode.COMPACT),
        (80, 20, LayoutMode.MEDIUM),
        (119, 20, LayoutMode.MEDIUM),
        (120, 20, LayoutMode.WIDE),
        (120, 19, LayoutMode.TOO_SMALL),
    ],
)
def test_exact_layout_boundaries(
    width: int,
    height: int,
    expected: LayoutMode,
) -> None:
    assert layout_mode(width, height) is expected


def test_terminal_size_rejects_impossible_dimensions() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        TerminalSize(-1, 20)
    with pytest.raises(ValueError, match="non-negative"):
        TerminalSize(80, -1)


def test_wide_mode_has_three_nonoverlapping_logical_surfaces() -> None:
    placement = layout_placement(TerminalSize(130, 34), VisualState())

    assert placement.mode is LayoutMode.WIDE
    assert placement.visible_surfaces == (
        LogicalSurface.NAVIGATION,
        LogicalSurface.CONVERSATION,
        LogicalSurface.INSPECTOR,
    )
    assert sum(region.columns for region in placement.regions) == 130
    assert len({region.surface for region in placement.regions}) == 3


def test_medium_inspector_replaces_navigation_only_when_open() -> None:
    default = layout_placement(TerminalSize(100, 34), VisualState())
    inspector = layout_placement(
        TerminalSize(100, 34),
        VisualState(
            inspector=InspectorState(InspectorKind.MEMBERS),
            focus=FocusTarget(LogicalSurface.INSPECTOR, "members"),
        ),
    )

    assert default.visible_surfaces == (
        LogicalSurface.NAVIGATION,
        LogicalSurface.CONVERSATION,
    )
    assert inspector.visible_surfaces == (
        LogicalSurface.CONVERSATION,
        LogicalSurface.INSPECTOR,
    )


@pytest.mark.parametrize(
    "surface",
    [
        LogicalSurface.NAVIGATION,
        LogicalSurface.CONVERSATION,
        LogicalSurface.INSPECTOR,
    ],
)
def test_compact_mode_shows_one_selected_logical_surface(
    surface: LogicalSurface,
) -> None:
    inspector = (
        InspectorState(InspectorKind.MESSAGE)
        if surface is LogicalSurface.INSPECTOR
        else None
    )
    placement = layout_placement(
        TerminalSize(64, 34),
        VisualState(pane_choice=surface, inspector=inspector),
    )

    assert placement.mode is LayoutMode.COMPACT
    assert placement.visible_surfaces == (surface,)
    assert placement.regions[0].columns == 64


def test_compact_closed_inspector_falls_back_to_conversation() -> None:
    placement = layout_placement(
        TerminalSize(64, 34),
        VisualState(pane_choice=LogicalSurface.INSPECTOR),
    )

    assert placement.visible_surfaces == (LogicalSurface.CONVERSATION,)


def test_too_small_hides_content_and_uses_full_resize_hint() -> None:
    placement = layout_placement(TerminalSize(40, 15), VisualState())

    assert placement.visible_surfaces == (LogicalSurface.RESIZE_HINT,)
    assert placement.regions[0].columns == 40


def test_navigation_is_never_an_eight_column_glyph_strip() -> None:
    for size in (TerminalSize(80, 20), TerminalSize(100, 34), TerminalSize(120, 20)):
        placement = layout_placement(size, VisualState())
        navigation = [
            region
            for region in placement.regions
            if region.surface is LogicalSurface.NAVIGATION
        ]
        assert navigation
        assert navigation[0].columns >= 20


def test_transcript_metadata_stacks_only_at_compact_width() -> None:
    assert (
        transcript_metadata_layout(LayoutMode.WIDE) is TranscriptMetadataLayout.ALIGNED
    )
    assert (
        transcript_metadata_layout(LayoutMode.MEDIUM)
        is TranscriptMetadataLayout.ALIGNED
    )
    assert (
        transcript_metadata_layout(LayoutMode.COMPACT)
        is TranscriptMetadataLayout.STACKED
    )
    assert (
        transcript_metadata_layout(LayoutMode.TOO_SMALL)
        is TranscriptMetadataLayout.HIDDEN
    )
