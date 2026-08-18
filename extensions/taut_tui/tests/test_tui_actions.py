"""Closed action vocabulary and input parity for the TUI extension.

Spec references:
- docs/specs/10-taut-tui.md [TUI-2.2], [TUI-2.3], [TUI-8]
"""

from __future__ import annotations

import pytest

from taut_tui.actions import (
    ACTION_SPECS,
    NORMAL_GESTURE_PAIRS,
    ActionContext,
    ActionId,
    ActionInvocation,
    ActionRoute,
    ConfirmationPolicy,
    GesturePair,
    Interaction,
    InteractionIntent,
    MouseGesture,
    action_spec,
    available_action_specs,
    invoke_action,
    resolve_gesture,
    resolve_mouse,
)
from taut_tui.models import InteractionMode, LogicalSurface

pytestmark = pytest.mark.sqlite_only


EXPECTED_ACTION_IDS = {
    "workspace.initialize",
    "identity.rejoin",
    "identity.show",
    "identity.set-name",
    "identity.set-persona",
    "conversation.open",
    "channel.join",
    "channel.leave",
    "direct-message.start",
    "notifications.open",
    "members.open",
    "channel.show-topic",
    "channel.set-topic",
    "channel.clear-topic",
    "channel.rename",
    "compose.enter",
    "message.send",
    "message.reply",
    "message.react",
    "message.delete",
    "search.open",
    "search.open-result",
    "system.doctor",
    "system.dump",
    "system.load-help",
    "command.open",
    "help.open",
    "application.quit",
    "summon.start",
    "summon.list",
    "summon.status",
    "summon.dismiss",
}

EXPECTED_NORMAL_GESTURES = (
    (InteractionIntent.ITEM_PREVIOUS, ("k",), ("up",), None),
    (InteractionIntent.ITEM_NEXT, ("j",), ("down",), None),
    (InteractionIntent.SURFACE_PREVIOUS, ("h",), ("left",), None),
    (InteractionIntent.SURFACE_NEXT, ("l",), ("right",), None),
    (InteractionIntent.ITEM_FIRST, ("gg",), ("home",), None),
    (InteractionIntent.ITEM_LAST, ("G",), ("end",), None),
    (InteractionIntent.PAGE_UP, ("ctrl+u",), ("pageup",), None),
    (InteractionIntent.PAGE_DOWN, (), ("pagedown",), None),
    (
        InteractionIntent.DISPATCH_ACTION,
        ("i",),
        ("focus:composer",),
        ActionId.COMPOSE_ENTER,
    ),
    (InteractionIntent.ACTIVATE_SELECTION, ("enter",), ("enter",), None),
    (InteractionIntent.LEAVE_TRANSIENT, ("escape",), ("escape",), None),
    (
        InteractionIntent.OPEN_COMMAND_LINE,
        (":",),
        ("colon",),
        None,
    ),
    (
        InteractionIntent.DISPATCH_ACTION,
        ("ctrl+p",),
        ("ctrl+p",),
        ActionId.COMMAND_OPEN,
    ),
    (
        InteractionIntent.DISPATCH_ACTION,
        ("/",),
        ("ctrl+f",),
        ActionId.SEARCH_OPEN,
    ),
    (
        InteractionIntent.DISPATCH_ACTION,
        ("?",),
        ("f1",),
        ActionId.HELP_OPEN,
    ),
    (
        InteractionIntent.DISPATCH_ACTION,
        ("q",),
        ("ctrl+q",),
        ActionId.APPLICATION_QUIT,
    ),
)


def test_action_inventory_is_exact_closed_and_reachable() -> None:
    assert {action_id.value for action_id in ActionId} == EXPECTED_ACTION_IDS
    assert len(ACTION_SPECS) == len(EXPECTED_ACTION_IDS)
    assert {spec.action_id for spec in ACTION_SPECS} == set(ActionId)
    assert all(spec.routes for spec in ACTION_SPECS)
    assert all(action_spec(action_id).action_id is action_id for action_id in ActionId)


@pytest.mark.parametrize("route", list(ActionRoute))
def test_available_action_specs_follow_declared_routes(route: ActionRoute) -> None:
    actual = available_action_specs(summon_available=True, route=route)

    assert tuple(spec for spec in ACTION_SPECS if route in spec.routes) == actual


def test_invocation_rejects_an_undeclared_route() -> None:
    with pytest.raises(ValueError, match="command.open.*palette"):
        ActionInvocation(
            action_id=ActionId.COMMAND_OPEN,
            context=ActionContext(),
            source=ActionRoute.PALETTE,
        )


def test_normal_gesture_inventory_exactly_matches_the_spec_parity_table() -> None:
    assert (
        tuple(
            (pair.intent, pair.vi, pair.conventional, pair.action_id)
            for pair in NORMAL_GESTURE_PAIRS
        )
        == EXPECTED_NORMAL_GESTURES
    )


def test_destructive_action_inventory_has_exact_target_confirmation() -> None:
    destructive = {
        spec.action_id: spec.confirmation
        for spec in ACTION_SPECS
        if spec.confirmation is not ConfirmationPolicy.NEVER
    }

    assert destructive == {
        ActionId.CHANNEL_LEAVE: ConfirmationPolicy.ALWAYS,
        ActionId.CHANNEL_RENAME: ConfirmationPolicy.ALWAYS,
        ActionId.MESSAGE_DELETE: ConfirmationPolicy.ALWAYS,
        ActionId.SYSTEM_DUMP: ConfirmationPolicy.IF_TARGET_EXISTS,
        ActionId.SUMMON_DISMISS: ConfirmationPolicy.ALWAYS,
    }
    for action_id in destructive:
        confirmation = action_spec(action_id).confirmation_prompt
        assert confirmation is not None
        assert "{target}" in confirmation


@pytest.mark.parametrize(
    "pair", NORMAL_GESTURE_PAIRS, ids=lambda pair: pair.intent.value
)
def test_vi_and_conventional_gestures_resolve_to_same_intent(
    pair: GesturePair,
) -> None:
    if pair.intent is InteractionIntent.PAGE_DOWN:
        assert pair.vi == ()
    else:
        assert pair.vi
    assert pair.conventional
    if pair.vi:
        assert {
            require_interaction(
                resolve_gesture(gesture, mode=InteractionMode.NORMAL)
            ).intent
            for gesture in pair.vi
        } == {pair.intent}
    assert {
        require_interaction(
            resolve_gesture(gesture, mode=InteractionMode.NORMAL)
        ).intent
        for gesture in pair.conventional
    } == {pair.intent}


def require_interaction(interaction: Interaction | None) -> Interaction:
    assert interaction is not None
    return interaction


def test_compose_inbox_and_text_entry_do_not_conflict() -> None:
    compose = resolve_gesture("i", mode=InteractionMode.NORMAL)
    inbox = resolve_gesture("g i", mode=InteractionMode.NORMAL)

    assert require_interaction(compose).action_id is ActionId.COMPOSE_ENTER
    assert require_interaction(inbox).action_id is ActionId.NOTIFICATIONS_OPEN
    for mode in (
        InteractionMode.COMPOSE,
        InteractionMode.COMMAND,
        InteractionMode.SEARCH,
    ):
        for text_key in ("q", "i", ":", "/", "?"):
            assert resolve_gesture(text_key, mode=mode) is None
        assert (
            require_interaction(resolve_gesture("escape", mode=mode)).intent
            is InteractionIntent.LEAVE_TRANSIENT
        )


def test_framework_key_aliases_preserve_vi_sequence_semantics() -> None:
    assert (
        require_interaction(resolve_gesture("g g", mode=InteractionMode.NORMAL)).intent
        is InteractionIntent.ITEM_FIRST
    )
    assert (
        require_interaction(
            resolve_gesture("shift+g", mode=InteractionMode.NORMAL)
        ).intent
        is InteractionIntent.ITEM_LAST
    )


@pytest.mark.parametrize(
    ("gesture", "intent"),
    [
        ("tab", InteractionIntent.FOCUS_NEXT),
        ("shift+tab", InteractionIntent.FOCUS_PREVIOUS),
    ],
)
@pytest.mark.parametrize("mode", list(InteractionMode))
def test_tab_focus_routes_are_mode_independent(
    gesture: str,
    intent: InteractionIntent,
    mode: InteractionMode,
) -> None:
    assert require_interaction(resolve_gesture(gesture, mode=mode)).intent is intent


def test_keyboard_mouse_and_palette_emit_same_typed_action() -> None:
    context = ActionContext(
        target="general",
        target_label="#general",
        message_id=1234567890123456789,
        surface=LogicalSurface.CONVERSATION,
    )

    invocations = {
        invoke_action(ActionId.HELP_OPEN, context, source=source)
        for source in (
            ActionRoute.KEYBOARD,
            ActionRoute.MOUSE,
            ActionRoute.PALETTE,
        )
    }

    assert {invocation.action_id for invocation in invocations} == {ActionId.HELP_OPEN}
    assert {invocation.context for invocation in invocations} == {context}
    assert {invocation.source for invocation in invocations} == {
        ActionRoute.KEYBOARD,
        ActionRoute.MOUSE,
        ActionRoute.PALETTE,
    }


def test_mouse_routes_have_keyboard_equivalents() -> None:
    assert resolve_mouse(MouseGesture.FOCUS).intent is InteractionIntent.FOCUS_POINTER
    assert resolve_mouse(MouseGesture.SELECT).intent is InteractionIntent.SELECT_POINTER
    assert (
        resolve_mouse(MouseGesture.ACTIVATE).intent
        is InteractionIntent.ACTIVATE_SELECTION
    )
    assert resolve_mouse(MouseGesture.SCROLL_UP).intent is InteractionIntent.SCROLL_UP
    assert (
        resolve_mouse(MouseGesture.SCROLL_DOWN).intent is InteractionIntent.SCROLL_DOWN
    )
    assert resolve_mouse(MouseGesture.COMPOSER).action_id is ActionId.COMPOSE_ENTER

    keyboard_intents = {
        require_interaction(
            resolve_gesture(gesture, mode=InteractionMode.NORMAL)
        ).intent
        for gesture in ("enter", "ctrl+u", "pagedown")
    }
    assert InteractionIntent.ACTIVATE_SELECTION in keyboard_intents
    assert InteractionIntent.PAGE_UP in keyboard_intents
    assert InteractionIntent.PAGE_DOWN in keyboard_intents
    assert resolve_gesture("ctrl+d", mode=InteractionMode.NORMAL) is None
