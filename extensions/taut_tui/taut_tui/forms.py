"""Typed native-form and direct-action input contracts.

This module describes TUI-owned fields and visual preflight only. It does not
parse command lines, call the domain, or reproduce core validation.

Spec references:
- docs/specs/10-taut-tui.md [TUI-2.2], [TUI-2.3], [TUI-3.3], [TUI-7]
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType

from taut_tui.actions import (
    ActionId,
    ConfirmationPolicy,
    action_spec,
)


class ActionInputKind(StrEnum):
    """Whether an action opens a native form or dispatches existing state."""

    FORM = "form"
    DIRECT = "direct"


class FieldKind(StrEnum):
    """Native input rendering roles, not domain value types."""

    TEXT = "text"
    SECRET = "secret"
    PATH = "path"


class FormControlKind(StrEnum):
    SUBMIT = "submit"
    CANCEL = "cancel"


class ContextRequirement(StrEnum):
    """Typed visual state an action needs in addition to form values."""

    ACTIVE_TARGET = "active-target"
    SELECTED_TARGET = "selected-target"
    SELECTED_MESSAGE = "selected-message"
    SELECTED_SEARCH_RESULT = "selected-search-result"
    DRAFT = "draft"


class ConfirmationTarget(StrEnum):
    """Where the dispatcher obtains the exact target named by a prompt."""

    CONTEXT = "context"
    FIELD = "field"


class VisualValidationCode(StrEnum):
    """The complete, deliberately small visual validation vocabulary."""

    REQUIRED = "required"
    NONBLANK = "nonblank"


@dataclass(frozen=True, slots=True)
class FieldSpec:
    """One labelled native field in explicit Tab order."""

    field_id: str
    label: str
    kind: FieldKind
    focus_order: int
    required: bool = False
    nonblank: bool = False
    masked: bool = False
    clear_on_close: bool = False

    def __post_init__(self) -> None:
        if not self.field_id:
            raise ValueError("field_id must not be empty")
        if not self.label:
            raise ValueError("field label must not be empty")
        if self.focus_order < 0:
            raise ValueError("field focus_order must be non-negative")
        if self.kind is FieldKind.SECRET:
            if not self.masked or not self.clear_on_close:
                raise ValueError("secret fields must be masked and cleared on close")
        elif self.masked:
            raise ValueError("only secret fields may be masked")


@dataclass(frozen=True, slots=True)
class FormControlSpec:
    """One explicit submit or cancel control."""

    control_id: str
    label: str
    kind: FormControlKind
    focus_order: int

    def __post_init__(self) -> None:
        if not self.control_id or not self.label:
            raise ValueError("form controls require an id and label")
        if self.focus_order < 0:
            raise ValueError("control focus_order must be non-negative")


@dataclass(frozen=True, slots=True)
class FormSpec:
    """One native form, including exact confirmation and focus metadata."""

    action_id: ActionId
    title: str
    fields: tuple[FieldSpec, ...]
    submit: FormControlSpec
    cancel: FormControlSpec
    confirmation: ConfirmationPolicy
    confirmation_prompt: str | None
    confirmation_target: ConfirmationTarget | None = None
    confirmation_field: str | None = None

    def __post_init__(self) -> None:
        if not self.title:
            raise ValueError("form title must not be empty")
        field_ids = tuple(field.field_id for field in self.fields)
        if len(field_ids) != len(set(field_ids)):
            raise ValueError("form field ids must be unique")
        if self.submit.kind is not FormControlKind.SUBMIT:
            raise ValueError("form submit control must have the submit role")
        if self.cancel.kind is not FormControlKind.CANCEL:
            raise ValueError("form cancel control must have the cancel role")
        focus_orders = (
            *(field.focus_order for field in self.fields),
            self.submit.focus_order,
            self.cancel.focus_order,
        )
        if focus_orders != tuple(range(len(focus_orders))):
            raise ValueError("form focus order must be contiguous and explicit")

        action = action_spec(self.action_id)
        if (
            self.confirmation is not action.confirmation
            or self.confirmation_prompt != action.confirmation_prompt
        ):
            raise ValueError("form confirmation must match the action registry")
        self._validate_confirmation_target(field_ids)

    def _validate_confirmation_target(self, field_ids: tuple[str, ...]) -> None:
        if self.confirmation is ConfirmationPolicy.NEVER:
            if (
                self.confirmation_target is not None
                or self.confirmation_field is not None
            ):
                raise ValueError("non-destructive forms have no confirmation target")
            return
        if self.confirmation_target is None:
            raise ValueError("destructive forms require an exact confirmation target")
        if self.confirmation_target is ConfirmationTarget.FIELD:
            if self.confirmation_field not in field_ids:
                raise ValueError("confirmation field must name a field in the form")
        elif self.confirmation_field is not None:
            raise ValueError("context confirmation cannot name a form field")

    @property
    def focus_order(self) -> tuple[str, ...]:
        """Stable Tab order for fields followed by submit and cancel."""

        return (
            *(field.field_id for field in self.fields),
            self.submit.control_id,
            self.cancel.control_id,
        )

    def field(self, field_id: str) -> FieldSpec:
        """Return a named native field without accepting arbitrary arguments."""

        for field in self.fields:
            if field.field_id == field_id:
                return field
        raise KeyError(f"unknown field {field_id!r} for {self.action_id.value}")


@dataclass(frozen=True, slots=True)
class ActionInputSpec:
    """Closed input classification for one non-Summon action."""

    action_id: ActionId
    kind: ActionInputKind
    context: tuple[ContextRequirement, ...]
    form: FormSpec | None
    confirmation: ConfirmationPolicy
    confirmation_prompt: str | None
    confirmation_target: ConfirmationTarget | None = None
    confirmation_field: str | None = None

    def __post_init__(self) -> None:
        action = action_spec(self.action_id)
        if action.requires_summon:
            raise ValueError("Summon input belongs to its optional native adapter")
        if len(self.context) != len(set(self.context)):
            raise ValueError("action context requirements must be unique")
        if (self.kind is ActionInputKind.FORM) != (self.form is not None):
            raise ValueError("form actions require exactly one native form")
        if self.form is not None and self.form.action_id is not self.action_id:
            raise ValueError("native form action id must match its input contract")
        if (
            self.confirmation is not action.confirmation
            or self.confirmation_prompt != action.confirmation_prompt
        ):
            raise ValueError("input confirmation must match the action registry")
        if self.form is not None and (
            self.confirmation_target is not self.form.confirmation_target
            or self.confirmation_field != self.form.confirmation_field
        ):
            raise ValueError("form and action input confirmation targets must match")
        if self.confirmation is ConfirmationPolicy.NEVER:
            if (
                self.confirmation_target is not None
                or self.confirmation_field is not None
            ):
                raise ValueError("non-destructive actions have no confirmation target")
        elif self.confirmation_target is None:
            raise ValueError("destructive actions require an exact confirmation target")

    @property
    def contextual(self) -> bool:
        return bool(self.context)


@dataclass(frozen=True, slots=True)
class VisualValidationError:
    field_id: str
    code: VisualValidationCode
    message: str


def _field(
    field_id: str,
    label: str,
    *,
    order: int,
    kind: FieldKind = FieldKind.TEXT,
    required: bool = False,
    nonblank: bool = False,
    masked: bool = False,
    clear_on_close: bool = False,
) -> FieldSpec:
    return FieldSpec(
        field_id=field_id,
        label=label,
        kind=kind,
        focus_order=order,
        required=required,
        nonblank=nonblank,
        masked=masked,
        clear_on_close=clear_on_close,
    )


def _form(
    action_id: ActionId,
    title: str,
    fields: tuple[FieldSpec, ...],
    submit_label: str,
    *,
    confirmation_target: ConfirmationTarget | None = None,
    confirmation_field: str | None = None,
) -> FormSpec:
    action = action_spec(action_id)
    return FormSpec(
        action_id=action_id,
        title=title,
        fields=fields,
        submit=FormControlSpec(
            control_id="submit",
            label=submit_label,
            kind=FormControlKind.SUBMIT,
            focus_order=len(fields),
        ),
        cancel=FormControlSpec(
            control_id="cancel",
            label="Cancel",
            kind=FormControlKind.CANCEL,
            focus_order=len(fields) + 1,
        ),
        confirmation=action.confirmation,
        confirmation_prompt=action.confirmation_prompt,
        confirmation_target=confirmation_target,
        confirmation_field=confirmation_field,
    )


_FORM_SPECS = (
    _form(
        ActionId.IDENTITY_REJOIN,
        "Rejoin identity",
        (
            _field("name_or_alias", "Name or alias", order=0, nonblank=True),
            _field(
                "continuity_token",
                "Continuity token",
                order=1,
                kind=FieldKind.SECRET,
                nonblank=True,
                masked=True,
                clear_on_close=True,
            ),
        ),
        "Rejoin",
    ),
    _form(
        ActionId.IDENTITY_SET_NAME,
        "Set display name",
        (_field("name", "Display name", order=0, required=True, nonblank=True),),
        "Save name",
    ),
    _form(
        ActionId.IDENTITY_SET_PERSONA,
        "Set persona",
        (_field("persona", "Persona", order=0),),
        "Save persona",
    ),
    _form(
        ActionId.CHANNEL_JOIN,
        "Join channel",
        (_field("channel", "Channel", order=0, required=True, nonblank=True),),
        "Join",
    ),
    _form(
        ActionId.DIRECT_MESSAGE_START,
        "Start direct message",
        (
            _field("member", "Member", order=0, required=True, nonblank=True),
            _field("message", "Message", order=1, required=True, nonblank=True),
        ),
        "Start direct message",
    ),
    _form(
        ActionId.CHANNEL_SET_TOPIC,
        "Set channel topic",
        (_field("topic", "Topic", order=0, required=True, nonblank=True),),
        "Save topic",
    ),
    _form(
        ActionId.CHANNEL_RENAME,
        "Rename channel",
        (
            _field(
                "new_name",
                "New channel name",
                order=0,
                required=True,
                nonblank=True,
            ),
        ),
        "Rename",
        confirmation_target=ConfirmationTarget.CONTEXT,
    ),
    _form(
        ActionId.MESSAGE_REPLY,
        "Reply to message",
        (_field("message", "Reply", order=0, required=True, nonblank=True),),
        "Send reply",
    ),
    _form(
        ActionId.MESSAGE_REACT,
        "React to message",
        (_field("reaction", "Reaction", order=0, required=True, nonblank=True),),
        "Add reaction",
    ),
    _form(
        ActionId.SYSTEM_DUMP,
        "Dump workspace",
        (
            _field(
                "output_path",
                "Output path",
                order=0,
                kind=FieldKind.PATH,
                required=True,
                nonblank=True,
            ),
        ),
        "Create dump",
        confirmation_target=ConfirmationTarget.FIELD,
        confirmation_field="output_path",
    ),
    _form(
        ActionId.SYSTEM_LOAD_HELP,
        "Restore from the CLI",
        (
            _field(
                "input_path",
                "Input dump path",
                order=0,
                kind=FieldKind.PATH,
                required=True,
                nonblank=True,
            ),
        ),
        "Show command",
    ),
)

FORM_SPECS: Mapping[ActionId, FormSpec] = MappingProxyType(
    {form.action_id: form for form in _FORM_SPECS}
)


def form_spec(action_id: ActionId) -> FormSpec:
    return FORM_SPECS[action_id]


def _input(
    action_id: ActionId,
    *,
    context: tuple[ContextRequirement, ...] = (),
    confirmation_target: ConfirmationTarget | None = None,
    confirmation_field: str | None = None,
) -> ActionInputSpec:
    action = action_spec(action_id)
    form = FORM_SPECS.get(action_id)
    if form is not None:
        confirmation_target = form.confirmation_target
        confirmation_field = form.confirmation_field
    return ActionInputSpec(
        action_id=action_id,
        kind=ActionInputKind.FORM if form is not None else ActionInputKind.DIRECT,
        context=context,
        form=form,
        confirmation=action.confirmation,
        confirmation_prompt=action.confirmation_prompt,
        confirmation_target=confirmation_target,
        confirmation_field=confirmation_field,
    )


_ACTION_INPUT_SPECS = (
    _input(ActionId.WORKSPACE_INITIALIZE),
    _input(ActionId.IDENTITY_REJOIN),
    _input(ActionId.IDENTITY_SHOW),
    _input(ActionId.IDENTITY_SET_NAME),
    _input(ActionId.IDENTITY_SET_PERSONA),
    _input(
        ActionId.CONVERSATION_OPEN,
        context=(ContextRequirement.SELECTED_TARGET,),
    ),
    _input(ActionId.CHANNEL_JOIN),
    _input(
        ActionId.CHANNEL_LEAVE,
        context=(ContextRequirement.ACTIVE_TARGET,),
        confirmation_target=ConfirmationTarget.CONTEXT,
    ),
    _input(ActionId.DIRECT_MESSAGE_START),
    _input(ActionId.NOTIFICATIONS_OPEN),
    _input(
        ActionId.MEMBERS_OPEN,
        context=(ContextRequirement.ACTIVE_TARGET,),
    ),
    _input(
        ActionId.CHANNEL_SHOW_TOPIC,
        context=(ContextRequirement.ACTIVE_TARGET,),
    ),
    _input(
        ActionId.CHANNEL_SET_TOPIC,
        context=(ContextRequirement.ACTIVE_TARGET,),
    ),
    _input(
        ActionId.CHANNEL_CLEAR_TOPIC,
        context=(ContextRequirement.ACTIVE_TARGET,),
    ),
    _input(
        ActionId.CHANNEL_RENAME,
        context=(ContextRequirement.ACTIVE_TARGET,),
    ),
    _input(
        ActionId.COMPOSE_ENTER,
        context=(ContextRequirement.ACTIVE_TARGET,),
    ),
    _input(
        ActionId.MESSAGE_SEND,
        context=(ContextRequirement.ACTIVE_TARGET, ContextRequirement.DRAFT),
    ),
    _input(
        ActionId.MESSAGE_REPLY,
        context=(
            ContextRequirement.ACTIVE_TARGET,
            ContextRequirement.SELECTED_MESSAGE,
        ),
    ),
    _input(
        ActionId.MESSAGE_REACT,
        context=(ContextRequirement.SELECTED_MESSAGE,),
    ),
    _input(
        ActionId.MESSAGE_DELETE,
        context=(ContextRequirement.SELECTED_MESSAGE,),
        confirmation_target=ConfirmationTarget.CONTEXT,
    ),
    _input(ActionId.SEARCH_OPEN),
    _input(
        ActionId.SEARCH_OPEN_RESULT,
        context=(ContextRequirement.SELECTED_SEARCH_RESULT,),
    ),
    _input(ActionId.SYSTEM_DOCTOR),
    _input(ActionId.SYSTEM_DUMP),
    _input(ActionId.SYSTEM_LOAD_HELP),
    _input(ActionId.COMMAND_OPEN),
    _input(ActionId.HELP_OPEN),
    _input(ActionId.APPLICATION_QUIT),
)

ACTION_INPUT_SPECS: Mapping[ActionId, ActionInputSpec] = MappingProxyType(
    {spec.action_id: spec for spec in _ACTION_INPUT_SPECS}
)


def input_spec(action_id: ActionId) -> ActionInputSpec:
    return ACTION_INPUT_SPECS[action_id]


def validate_visual_input(
    form: FormSpec,
    values: Mapping[str, str],
) -> tuple[VisualValidationError, ...]:
    """Return only missing/nonblank cues; the public core validates values."""

    errors: list[VisualValidationError] = []
    for field in form.fields:
        value = values.get(field.field_id)
        if value is None or value == "":
            if field.required:
                errors.append(
                    VisualValidationError(
                        field.field_id,
                        VisualValidationCode.REQUIRED,
                        f"{field.label} is required.",
                    )
                )
            continue
        if field.nonblank and not value.strip():
            errors.append(
                VisualValidationError(
                    field.field_id,
                    VisualValidationCode.NONBLANK,
                    f"{field.label} must not be blank.",
                )
            )
    return tuple(errors)


__all__ = [
    "ACTION_INPUT_SPECS",
    "FORM_SPECS",
    "ActionInputKind",
    "ActionInputSpec",
    "ConfirmationTarget",
    "ContextRequirement",
    "FieldKind",
    "FieldSpec",
    "FormControlKind",
    "FormControlSpec",
    "FormSpec",
    "VisualValidationCode",
    "VisualValidationError",
    "form_spec",
    "input_spec",
    "validate_visual_input",
]
