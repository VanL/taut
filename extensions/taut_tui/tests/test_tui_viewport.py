"""Contract tests for the [TUI-9.2] transcript viewport owner."""

from __future__ import annotations

import pytest

from taut_tui.viewport import (
    TranscriptViewport,
    ViewportEffectKind,
    ViewportMode,
)


def test_tail_render_emits_tokened_scroll_end_and_user_intent_stales_it() -> None:
    viewport, effect = TranscriptViewport.tail().plan_render()

    assert viewport.mode is ViewportMode.TAIL
    assert effect is not None
    assert effect.kind is ViewportEffectKind.SCROLL_END
    assert viewport.accepts(effect)

    moved = viewport.user_intent_started()

    assert moved.mode is ViewportMode.TAIL
    assert not moved.accepts(effect)


def test_settled_user_position_owns_tail_or_history() -> None:
    history = TranscriptViewport.tail().user_settled(
        at_tail=False,
        message_id=42,
        offset=3,
    )
    tail = history.user_settled(at_tail=True)

    assert history.mode is ViewportMode.HISTORY
    assert history.message_id == 42
    assert history.offset == 3
    assert tail.mode is ViewportMode.TAIL


def test_history_render_restores_exact_anchor_and_clamps_on_completion() -> None:
    viewport, effect = TranscriptViewport.history(42, offset=7).plan_render()

    assert effect is not None
    assert effect.kind is ViewportEffectKind.RESTORE
    assert effect.message_id == 42
    assert effect.offset == 7

    restored = viewport.restore_done(effect, settled_offset=2)

    assert restored.mode is ViewportMode.HISTORY
    assert restored.message_id == 42
    assert restored.offset == 2


def test_search_render_requires_matching_intent_then_becomes_history() -> None:
    search = TranscriptViewport.tail().search_armed(7, 42)

    unchanged, missing = search.plan_render(authorized_search_intent=6)
    authorized, effect = unchanged.plan_render(authorized_search_intent=7)

    assert missing is None
    assert authorized.mode is ViewportMode.SEARCH_OWNED
    assert effect is not None
    assert effect.message_id == 42

    restored = authorized.restore_done(effect, settled_offset=1)

    assert restored.mode is ViewportMode.HISTORY
    assert restored.message_id == 42
    assert restored.offset == 1


def test_matching_search_target_change_retains_owner_other_change_resets_tail() -> None:
    search = TranscriptViewport.tail().search_armed(7, 42)

    matching = search.target_changed(search_intent=7)
    superseded = matching.target_changed(search_intent=8)

    assert matching.mode is ViewportMode.SEARCH_OWNED
    assert superseded.mode is ViewportMode.TAIL


@pytest.mark.parametrize(
    "viewport",
    [TranscriptViewport.tail(), TranscriptViewport.history(42, offset=2)],
)
def test_non_search_target_change_resets_tail(
    viewport: TranscriptViewport,
) -> None:
    changed = viewport.target_changed()

    assert changed.mode is ViewportMode.TAIL
    assert changed.generation == viewport.generation + 1


def test_user_intent_supersedes_search_into_settleable_history() -> None:
    search = TranscriptViewport.tail().search_armed(7, 42)

    started = search.user_intent_started()

    assert started.mode is ViewportMode.HISTORY
    assert started.message_id == 42
    assert started.generation == search.generation + 1


def test_search_cancel_and_missing_anchor_restore_recover_to_tail() -> None:
    search = TranscriptViewport.tail().search_armed(7, 42)
    cancelled = search.cancel_search(intent=7)
    planned, effect = TranscriptViewport.history(42).plan_render()
    assert effect is not None

    failed = planned.restore_failed(effect)

    assert cancelled.mode is ViewportMode.TAIL
    assert failed.mode is ViewportMode.TAIL
    assert not failed.accepts(effect)


@pytest.mark.parametrize(
    "viewport",
    [
        TranscriptViewport.tail(),
        TranscriptViewport.history(42, offset=1),
        TranscriptViewport.tail().search_armed(7, 42),
    ],
)
def test_stale_effect_completion_cannot_change_any_state(
    viewport: TranscriptViewport,
) -> None:
    authorized_intent = 7 if viewport.mode is ViewportMode.SEARCH_OWNED else None
    planned, effect = viewport.plan_render(authorized_search_intent=authorized_intent)
    assert effect is not None

    newer = planned.user_intent_started()

    assert newer.restore_done(effect, settled_offset=0) == newer


def test_invalid_history_and_search_values_fail_at_owner_boundary() -> None:
    with pytest.raises(ValueError, match="message_id"):
        TranscriptViewport.history(0)
    with pytest.raises(ValueError, match="offset"):
        TranscriptViewport.history(42, offset=-1)
    with pytest.raises(ValueError, match="intent"):
        TranscriptViewport.tail().search_armed(-1, 42)
