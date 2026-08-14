"""Typed native-form contracts for the TUI extension.

Spec references:
- docs/specs/10-taut-tui.md [TUI-2.2], [TUI-2.3], [TUI-3.3], [TUI-7]
"""

from __future__ import annotations

import pytest

from taut_tui.actions import ActionId, ConfirmationPolicy, action_spec
from taut_tui.forms import (
    ACTION_INPUT_SPECS,
    FORM_SPECS,
    ActionInputKind,
    ConfirmationTarget,
    ContextRequirement,
    FieldKind,
    VisualValidationCode,
    form_spec,
    input_spec,
    validate_visual_input,
)

pytestmark = pytest.mark.sqlite_only


EXPECTED_FORM_FIELDS = {
    ActionId.IDENTITY_REJOIN: (
        ("name_or_alias", "Name or alias", FieldKind.TEXT, False, True, False),
        (
            "continuity_token",
            "Continuity token",
            FieldKind.SECRET,
            False,
            True,
            True,
        ),
    ),
    ActionId.IDENTITY_SET_NAME: (
        ("name", "Display name", FieldKind.TEXT, True, True, False),
    ),
    ActionId.IDENTITY_SET_PERSONA: (
        ("persona", "Persona", FieldKind.TEXT, False, False, False),
    ),
    ActionId.CHANNEL_JOIN: (("channel", "Channel", FieldKind.TEXT, True, True, False),),
    ActionId.DIRECT_MESSAGE_START: (
        ("member", "Member", FieldKind.TEXT, True, True, False),
        ("message", "Message", FieldKind.TEXT, True, True, False),
    ),
    ActionId.CHANNEL_SET_TOPIC: (
        ("topic", "Topic", FieldKind.TEXT, True, True, False),
    ),
    ActionId.CHANNEL_RENAME: (
        ("new_name", "New channel name", FieldKind.TEXT, True, True, False),
    ),
    ActionId.MESSAGE_REPLY: (("message", "Reply", FieldKind.TEXT, True, True, False),),
    ActionId.MESSAGE_REACT: (
        ("reaction", "Reaction", FieldKind.TEXT, True, True, False),
    ),
    ActionId.SYSTEM_DUMP: (
        ("output_path", "Output path", FieldKind.PATH, True, True, False),
    ),
    ActionId.SYSTEM_LOAD_HELP: (
        ("input_path", "Input dump path", FieldKind.PATH, True, True, False),
    ),
}

EXPECTED_SUBMIT_LABELS = {
    ActionId.IDENTITY_REJOIN: "Rejoin",
    ActionId.IDENTITY_SET_NAME: "Save name",
    ActionId.IDENTITY_SET_PERSONA: "Save persona",
    ActionId.CHANNEL_JOIN: "Join",
    ActionId.DIRECT_MESSAGE_START: "Start direct message",
    ActionId.CHANNEL_SET_TOPIC: "Save topic",
    ActionId.CHANNEL_RENAME: "Rename",
    ActionId.MESSAGE_REPLY: "Send reply",
    ActionId.MESSAGE_REACT: "Add reaction",
    ActionId.SYSTEM_DUMP: "Create dump",
    ActionId.SYSTEM_LOAD_HELP: "Show command",
}

EXPECTED_CONTEXT = {
    ActionId.CONVERSATION_OPEN: (ContextRequirement.SELECTED_TARGET,),
    ActionId.CHANNEL_LEAVE: (ContextRequirement.ACTIVE_TARGET,),
    ActionId.MEMBERS_OPEN: (ContextRequirement.ACTIVE_TARGET,),
    ActionId.CHANNEL_SHOW_TOPIC: (ContextRequirement.ACTIVE_TARGET,),
    ActionId.CHANNEL_SET_TOPIC: (ContextRequirement.ACTIVE_TARGET,),
    ActionId.CHANNEL_CLEAR_TOPIC: (ContextRequirement.ACTIVE_TARGET,),
    ActionId.CHANNEL_RENAME: (ContextRequirement.ACTIVE_TARGET,),
    ActionId.COMPOSE_ENTER: (ContextRequirement.ACTIVE_TARGET,),
    ActionId.MESSAGE_SEND: (
        ContextRequirement.ACTIVE_TARGET,
        ContextRequirement.DRAFT,
    ),
    ActionId.MESSAGE_REPLY: (
        ContextRequirement.ACTIVE_TARGET,
        ContextRequirement.SELECTED_MESSAGE,
    ),
    ActionId.MESSAGE_REACT: (ContextRequirement.SELECTED_MESSAGE,),
    ActionId.MESSAGE_DELETE: (ContextRequirement.SELECTED_MESSAGE,),
    ActionId.SEARCH_OPEN_RESULT: (ContextRequirement.SELECTED_SEARCH_RESULT,),
}


def test_every_non_summon_action_has_one_closed_input_classification() -> None:
    non_summon = {
        action_id
        for action_id in ActionId
        if not action_spec(action_id).requires_summon
    }

    assert set(ACTION_INPUT_SPECS) == non_summon
    assert set(FORM_SPECS) == set(EXPECTED_FORM_FIELDS)
    assert {
        action_id
        for action_id, spec in ACTION_INPUT_SPECS.items()
        if spec.kind is ActionInputKind.FORM
    } == set(EXPECTED_FORM_FIELDS)
    assert all(
        input_spec(action_id).kind is ActionInputKind.DIRECT
        for action_id in non_summon - set(EXPECTED_FORM_FIELDS)
    )


def test_every_form_has_exact_typed_fields_labels_and_focus_order() -> None:
    for action_id, expected_fields in EXPECTED_FORM_FIELDS.items():
        form = form_spec(action_id)
        assert (
            tuple(
                (
                    field.field_id,
                    field.label,
                    field.kind,
                    field.required,
                    field.nonblank,
                    field.masked,
                )
                for field in form.fields
            )
            == expected_fields
        )
        assert tuple(field.focus_order for field in form.fields) == tuple(
            range(len(expected_fields))
        )
        assert form.submit.label == EXPECTED_SUBMIT_LABELS[action_id]
        assert form.cancel.label == "Cancel"
        assert form.focus_order == (
            *(field.field_id for field in form.fields),
            form.submit.control_id,
            form.cancel.control_id,
        )


def test_continuity_token_is_masked_and_cleared_when_form_closes() -> None:
    token = form_spec(ActionId.IDENTITY_REJOIN).field("continuity_token")

    assert token.kind is FieldKind.SECRET
    assert token.masked is True
    assert token.clear_on_close is True
    assert "continuity" in token.label.lower()


def test_context_requirements_are_explicit_and_exact() -> None:
    assert {
        action_id: spec.context
        for action_id, spec in ACTION_INPUT_SPECS.items()
        if spec.context
    } == EXPECTED_CONTEXT
    assert all(
        spec.contextual is bool(spec.context) for spec in ACTION_INPUT_SPECS.values()
    )


def test_confirmation_metadata_is_the_actions_registry_contract() -> None:
    for action_id, spec in ACTION_INPUT_SPECS.items():
        action = action_spec(action_id)
        assert spec.confirmation is action.confirmation
        assert spec.confirmation_prompt == action.confirmation_prompt

    expected_targets = {
        ActionId.CHANNEL_LEAVE: (ConfirmationTarget.CONTEXT, None),
        ActionId.CHANNEL_RENAME: (ConfirmationTarget.CONTEXT, None),
        ActionId.MESSAGE_DELETE: (ConfirmationTarget.CONTEXT, None),
        ActionId.SYSTEM_DUMP: (ConfirmationTarget.FIELD, "output_path"),
    }
    assert {
        action_id: (spec.confirmation_target, spec.confirmation_field)
        for action_id, spec in ACTION_INPUT_SPECS.items()
        if spec.confirmation is not ConfirmationPolicy.NEVER
    } == expected_targets


def test_visual_validation_only_marks_required_or_nonblank_fields() -> None:
    join = form_spec(ActionId.CHANNEL_JOIN)

    missing = validate_visual_input(join, {})
    blank = validate_visual_input(join, {"channel": "   "})
    domain_invalid = validate_visual_input(join, {"channel": "bad.name"})

    assert [(error.field_id, error.code) for error in missing] == [
        ("channel", VisualValidationCode.REQUIRED)
    ]
    assert [(error.field_id, error.code) for error in blank] == [
        ("channel", VisualValidationCode.NONBLANK)
    ]
    assert domain_invalid == ()


def test_visual_validation_does_not_duplicate_cross_field_or_domain_rules() -> None:
    rejoin = form_spec(ActionId.IDENTITY_REJOIN)
    topic = form_spec(ActionId.CHANNEL_SET_TOPIC)

    assert validate_visual_input(rejoin, {}) == ()
    assert validate_visual_input(topic, {"topic": "line one\nline two"}) == ()


def test_field_lookup_rejects_unknown_native_field() -> None:
    with pytest.raises(KeyError, match="unknown field"):
        form_spec(ActionId.CHANNEL_JOIN).field("argv")
