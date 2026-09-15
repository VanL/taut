from __future__ import annotations

from taut_tui.models import DraftState, VisualState


def test_channel_rename_retains_displaced_destination_draft() -> None:
    state = VisualState(
        drafts=(
            DraftState("general", "source\ntext", 3, 4),
            DraftState("ops", "destination\ntext", 7, 9),
        )
    )

    renamed = state.after_channel_rename("general", "ops", remap_open_view=False)

    assert renamed.draft_for("ops") == DraftState("ops", "source\ntext", 3, 10)
    assert len(renamed.recovered_drafts) == 1
    recovery = renamed.recovered_drafts[0]
    assert recovery.draft == DraftState("ops", "destination\ntext", 7, 9)
    assert recovery.intended_target == "ops"
    assert recovery.reason == "channel rename replaced an existing draft"


def test_channel_rename_retains_equal_and_whitespace_destination_drafts() -> None:
    for text in ("same", " \n\t"):
        state = VisualState(
            drafts=(DraftState("general", "same", 2), DraftState("ops", text, 1))
        )
        renamed = state.after_channel_rename("general", "ops", remap_open_view=False)
        assert renamed.recovered_drafts[0].draft.text == text


def test_later_rename_keeps_existing_recoveries() -> None:
    state = VisualState(
        drafts=(DraftState("general", "one"), DraftState("ops", "two"))
    ).after_channel_rename("general", "ops", remap_open_view=False)

    renamed = state.after_channel_rename("random", "other", remap_open_view=False)

    assert renamed.recovered_drafts == state.recovered_drafts


def test_loading_recovery_swaps_occupied_draft_and_uses_fresh_revision() -> None:
    state = VisualState(
        drafts=(DraftState("general", "source", 2, 8), DraftState("ops", "old", 1, 5))
    ).after_channel_rename("general", "ops", remap_open_view=False)
    selected = state.recovered_drafts[0]
    state = state.with_draft(DraftState("ops", "newer edit", 4, 12))

    loaded = state.load_recovered_draft(selected.recovery_id)

    assert loaded.draft_for("ops") == DraftState("ops", "old", 1, 13)
    assert len(loaded.recovered_drafts) == 1
    assert loaded.recovered_drafts[0].draft == DraftState("ops", "newer edit", 4, 12)
    assert loaded.recovered_drafts[0].recovery_id != selected.recovery_id


def test_loading_one_recovery_keeps_the_others() -> None:
    first = VisualState(
        drafts=(DraftState("a", "a"), DraftState("b", "b"))
    ).after_channel_rename("a", "b", remap_open_view=False)
    second = (
        first.with_draft(DraftState("c", "c"))
        .with_draft(DraftState("d", "d"))
        .after_channel_rename("c", "d", remap_open_view=False)
    )

    loaded = second.load_recovered_draft(first.recovered_drafts[0].recovery_id)

    assert len(loaded.recovered_drafts) == 2
    loaded_draft = loaded.draft_for("b")
    assert loaded_draft is not None and loaded_draft.text == "b"
    assert any(item.draft.text == "d" for item in loaded.recovered_drafts)
    assert any(item.draft.text == "a" for item in loaded.recovered_drafts)


def test_rename_revision_cannot_match_displaced_send_ack() -> None:
    state = VisualState(
        drafts=(
            DraftState("general", "source", revision=7),
            DraftState("ops", "sent", revision=7),
        )
    )

    renamed = state.after_channel_rename(
        "general", "ops", remap_open_view=False, minimum_revision=12
    )

    moved = renamed.draft_for("ops")
    assert moved is not None
    assert moved.revision == 13


def test_zero_revision_pending_send_still_forces_fresh_rename_revision() -> None:
    state = VisualState(drafts=(DraftState("general", "source", revision=0),))

    renamed = state.after_channel_rename(
        "general", "ops", remap_open_view=False, minimum_revision=0
    )

    moved = renamed.draft_for("ops")
    assert moved is not None
    assert moved.revision == 1


def test_recovery_revision_exceeds_other_recovery_records() -> None:
    state = VisualState(
        drafts=(DraftState("a", "a", revision=2), DraftState("b", "b", revision=40))
    ).after_channel_rename("a", "b", remap_open_view=False)
    selected = state.recovered_drafts[0]
    state = state.with_draft(DraftState("b", "occupied", revision=3))

    loaded = state.load_recovered_draft(selected.recovery_id, minimum_revision=50)

    recovered = loaded.draft_for("b")
    assert recovered is not None
    assert recovered.revision == 51
