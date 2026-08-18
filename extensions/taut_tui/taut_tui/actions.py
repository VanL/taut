"""Closed semantic action and gesture vocabulary for the TUI.

Widgets and bindings translate user input into these values. They do not call
domain APIs. The application dispatcher later decides applicability and opens
native forms or sends typed work to its owner.

Spec references:
- docs/specs/10-taut-tui.md [TUI-2.2], [TUI-2.3], [TUI-7.1], [TUI-8]
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from enum import StrEnum
from types import MappingProxyType

from taut_tui.models import InteractionMode, LogicalSurface


class ActionId(StrEnum):
    """Exact version-1 action identifiers from [TUI-2.3]."""

    WORKSPACE_INITIALIZE = "workspace.initialize"
    IDENTITY_REJOIN = "identity.rejoin"
    IDENTITY_SHOW = "identity.show"
    IDENTITY_SET_NAME = "identity.set-name"
    IDENTITY_SET_PERSONA = "identity.set-persona"
    CONVERSATION_OPEN = "conversation.open"
    CHANNEL_JOIN = "channel.join"
    CHANNEL_LEAVE = "channel.leave"
    DIRECT_MESSAGE_START = "direct-message.start"
    NOTIFICATIONS_OPEN = "notifications.open"
    MEMBERS_OPEN = "members.open"
    CHANNEL_SHOW_TOPIC = "channel.show-topic"
    CHANNEL_SET_TOPIC = "channel.set-topic"
    CHANNEL_CLEAR_TOPIC = "channel.clear-topic"
    CHANNEL_RENAME = "channel.rename"
    COMPOSE_ENTER = "compose.enter"
    MESSAGE_SEND = "message.send"
    MESSAGE_REPLY = "message.reply"
    MESSAGE_REACT = "message.react"
    MESSAGE_DELETE = "message.delete"
    SEARCH_OPEN = "search.open"
    SEARCH_OPEN_RESULT = "search.open-result"
    SYSTEM_DOCTOR = "system.doctor"
    SYSTEM_DUMP = "system.dump"
    SYSTEM_LOAD_HELP = "system.load-help"
    COMMAND_OPEN = "command.open"
    HELP_OPEN = "help.open"
    APPLICATION_QUIT = "application.quit"
    SUMMON_START = "summon.start"
    SUMMON_LIST = "summon.list"
    SUMMON_STATUS = "summon.status"
    SUMMON_DISMISS = "summon.dismiss"


class ActionFamily(StrEnum):
    WORKSPACE_IDENTITY = "workspace-identity"
    NAVIGATION = "navigation"
    CHANNEL_CONTEXT = "channel-context"
    MESSAGES = "messages"
    RETRIEVAL = "retrieval"
    SYSTEM = "system"
    APPLICATION = "application"
    SUMMON = "summon"


_DISPLAY_GROUPS = {
    ActionFamily.WORKSPACE_IDENTITY: "Workspace & identity",
    ActionFamily.NAVIGATION: "Conversations",
    ActionFamily.CHANNEL_CONTEXT: "Channels",
    ActionFamily.MESSAGES: "Messages",
    ActionFamily.RETRIEVAL: "Search",
    ActionFamily.SYSTEM: "System",
    ActionFamily.APPLICATION: "System",
    ActionFamily.SUMMON: "Summon",
}


class ActionRoute(StrEnum):
    """Discoverable routes, all converging on the same action id."""

    PALETTE = "palette"
    NAVIGATION = "navigation"
    CONTEXT = "context"
    KEYBOARD = "keyboard"
    MOUSE = "mouse"


class ConfirmationPolicy(StrEnum):
    """Whether native dispatch requires an exact-target confirmation."""

    NEVER = "never"
    ALWAYS = "always"
    IF_TARGET_EXISTS = "if-target-exists"


@dataclass(frozen=True, slots=True)
class ActionSpec:
    action_id: ActionId
    family: ActionFamily
    label: str
    routes: frozenset[ActionRoute]
    confirmation: ConfirmationPolicy = ConfirmationPolicy.NEVER
    confirmation_prompt: str | None = None
    requires_summon: bool = False
    display_group: str = ""
    display_order: int = 0

    def __post_init__(self) -> None:
        if not self.label:
            raise ValueError("action label must not be empty")
        if not self.routes:
            raise ValueError("an action must have a discoverable route")
        if self.confirmation is ConfirmationPolicy.NEVER:
            if self.confirmation_prompt is not None:
                raise ValueError("non-destructive action cannot have confirmation text")
        elif (
            self.confirmation_prompt is None
            or "{target}" not in self.confirmation_prompt
        ):
            raise ValueError("destructive confirmation must name {target}")
        if not self.display_group:
            raise ValueError("action display group must not be empty")
        if self.display_order < 0:
            raise ValueError("action display order must not be negative")


def _spec(
    action_id: ActionId,
    family: ActionFamily,
    label: str,
    *,
    routes: tuple[ActionRoute, ...] = (ActionRoute.PALETTE,),
    confirmation: ConfirmationPolicy = ConfirmationPolicy.NEVER,
    prompt: str | None = None,
    requires_summon: bool = False,
    display_group: str | None = None,
    display_order: int = 0,
) -> ActionSpec:
    return ActionSpec(
        action_id=action_id,
        family=family,
        label=label,
        routes=frozenset(routes),
        confirmation=confirmation,
        confirmation_prompt=prompt,
        requires_summon=requires_summon,
        display_group=display_group or _DISPLAY_GROUPS[family],
        display_order=display_order,
    )


_P = ActionRoute.PALETTE
_N = ActionRoute.NAVIGATION
_C = ActionRoute.CONTEXT
_K = ActionRoute.KEYBOARD
_M = ActionRoute.MOUSE

_ACTION_SPECS = (
    _spec(
        ActionId.WORKSPACE_INITIALIZE,
        ActionFamily.WORKSPACE_IDENTITY,
        "Initialize workspace",
        routes=(_P, _N),
    ),
    _spec(
        ActionId.IDENTITY_REJOIN,
        ActionFamily.WORKSPACE_IDENTITY,
        "Rejoin identity",
        routes=(_P, _N),
    ),
    _spec(ActionId.IDENTITY_SHOW, ActionFamily.WORKSPACE_IDENTITY, "Show identity"),
    _spec(
        ActionId.IDENTITY_SET_NAME, ActionFamily.WORKSPACE_IDENTITY, "Set display name"
    ),
    _spec(
        ActionId.IDENTITY_SET_PERSONA, ActionFamily.WORKSPACE_IDENTITY, "Set persona"
    ),
    _spec(
        ActionId.CONVERSATION_OPEN,
        ActionFamily.NAVIGATION,
        "Open conversation",
        routes=(_P, _N),
    ),
    _spec(
        ActionId.CHANNEL_JOIN, ActionFamily.NAVIGATION, "Join channel", routes=(_P, _N)
    ),
    _spec(
        ActionId.CHANNEL_LEAVE,
        ActionFamily.NAVIGATION,
        "Leave channel",
        routes=(_P,),
        confirmation=ConfirmationPolicy.ALWAYS,
        prompt="Leave {target}?",
    ),
    _spec(
        ActionId.DIRECT_MESSAGE_START,
        ActionFamily.NAVIGATION,
        "Start direct message",
        routes=(_P, _N),
    ),
    _spec(
        ActionId.NOTIFICATIONS_OPEN,
        ActionFamily.NAVIGATION,
        "Open notifications",
        routes=(_P, _N, _K),
    ),
    _spec(
        ActionId.MEMBERS_OPEN,
        ActionFamily.NAVIGATION,
        "Open members",
        routes=(_P, _M),
    ),
    _spec(
        ActionId.CHANNEL_SHOW_TOPIC,
        ActionFamily.CHANNEL_CONTEXT,
        "Show channel topic",
        routes=(_P,),
    ),
    _spec(
        ActionId.CHANNEL_SET_TOPIC,
        ActionFamily.CHANNEL_CONTEXT,
        "Set channel topic",
        routes=(_P,),
    ),
    _spec(
        ActionId.CHANNEL_CLEAR_TOPIC,
        ActionFamily.CHANNEL_CONTEXT,
        "Clear channel topic",
        routes=(_P,),
    ),
    _spec(
        ActionId.CHANNEL_RENAME,
        ActionFamily.CHANNEL_CONTEXT,
        "Rename channel",
        routes=(_P,),
        confirmation=ConfirmationPolicy.ALWAYS,
        prompt="Rename {target}?",
    ),
    _spec(
        ActionId.COMPOSE_ENTER,
        ActionFamily.MESSAGES,
        "Compose message",
        routes=(_P, _K, _M),
    ),
    _spec(
        ActionId.MESSAGE_SEND,
        ActionFamily.MESSAGES,
        "Send message",
        routes=(_P, _K, _M),
    ),
    _spec(
        ActionId.MESSAGE_REPLY,
        ActionFamily.MESSAGES,
        "Reply to message",
        routes=(_P, _M),
    ),
    _spec(
        ActionId.MESSAGE_REACT,
        ActionFamily.MESSAGES,
        "React to message",
        routes=(_P, _M),
    ),
    _spec(
        ActionId.MESSAGE_DELETE,
        ActionFamily.MESSAGES,
        "Delete message",
        routes=(_P, _M),
        confirmation=ConfirmationPolicy.ALWAYS,
        prompt="Delete message {target}?",
    ),
    _spec(
        ActionId.SEARCH_OPEN,
        ActionFamily.RETRIEVAL,
        "Search history",
        routes=(_P, _K, _M),
    ),
    _spec(
        ActionId.SEARCH_OPEN_RESULT,
        ActionFamily.RETRIEVAL,
        "Open search result",
        routes=(_P, _C),
    ),
    _spec(ActionId.SYSTEM_DOCTOR, ActionFamily.SYSTEM, "Run system doctor"),
    _spec(
        ActionId.SYSTEM_DUMP,
        ActionFamily.SYSTEM,
        "Dump workspace",
        confirmation=ConfirmationPolicy.IF_TARGET_EXISTS,
        prompt="Replace existing dump {target}?",
    ),
    _spec(ActionId.SYSTEM_LOAD_HELP, ActionFamily.SYSTEM, "Show CLI load help"),
    _spec(
        ActionId.COMMAND_OPEN,
        ActionFamily.APPLICATION,
        "Open command palette",
        routes=(_K, _M),
    ),
    _spec(
        ActionId.HELP_OPEN, ActionFamily.APPLICATION, "Open help", routes=(_P, _K, _M)
    ),
    _spec(
        ActionId.APPLICATION_QUIT,
        ActionFamily.APPLICATION,
        "Quit Taut",
        routes=(_P, _K),
    ),
    _spec(
        ActionId.SUMMON_START,
        ActionFamily.SUMMON,
        "Start summoned member",
        requires_summon=True,
    ),
    _spec(
        ActionId.SUMMON_LIST,
        ActionFamily.SUMMON,
        "List summoned members",
        requires_summon=True,
    ),
    _spec(
        ActionId.SUMMON_STATUS,
        ActionFamily.SUMMON,
        "Show summoned-member status",
        requires_summon=True,
    ),
    _spec(
        ActionId.SUMMON_DISMISS,
        ActionFamily.SUMMON,
        "Dismiss summoned member",
        confirmation=ConfirmationPolicy.ALWAYS,
        prompt="Dismiss {target}?",
        requires_summon=True,
    ),
)

# Keep declaration order as the explicit within-group presentation order. The
# browser may sort/filter the registry, but it does not depend on enum values
# or internal action ids for its visual arrangement.
ACTION_SPECS = tuple(
    replace(spec, display_order=index) for index, spec in enumerate(_ACTION_SPECS)
)

ACTION_REGISTRY: Mapping[ActionId, ActionSpec] = MappingProxyType(
    {spec.action_id: spec for spec in ACTION_SPECS}
)


def action_spec(action_id: ActionId) -> ActionSpec:
    return ACTION_REGISTRY[action_id]


def available_action_specs(
    *,
    summon_available: bool,
    route: ActionRoute | None = None,
) -> tuple[ActionSpec, ...]:
    """Return available actions, optionally constrained to one real route."""

    return tuple(
        spec
        for spec in ACTION_SPECS
        if (summon_available or not spec.requires_summon)
        and (route is None or route in spec.routes)
    )


@dataclass(frozen=True, slots=True)
class ActionContext:
    """Typed visual selection attached to an action invocation."""

    target: str | None = None
    target_label: str | None = None
    message_id: int | None = None
    member: str | None = None
    surface: LogicalSurface | None = None


@dataclass(frozen=True, slots=True)
class ActionInvocation:
    action_id: ActionId
    context: ActionContext
    source: ActionRoute

    def __post_init__(self) -> None:
        if self.source not in action_spec(self.action_id).routes:
            raise ValueError(
                f"{self.action_id.value} does not declare route {self.source.value}"
            )


def invoke_action(
    action_id: ActionId,
    context: ActionContext,
    *,
    source: ActionRoute,
) -> ActionInvocation:
    """Build the one typed invocation shape used by every input route."""

    return ActionInvocation(action_id=action_id, context=context, source=source)


class InteractionIntent(StrEnum):
    ITEM_PREVIOUS = "item.previous"
    ITEM_NEXT = "item.next"
    SURFACE_PREVIOUS = "surface.previous"
    SURFACE_NEXT = "surface.next"
    ITEM_FIRST = "item.first"
    ITEM_LAST = "item.last"
    PAGE_UP = "page.up"
    PAGE_DOWN = "page.down"
    ACTIVATE_SELECTION = "selection.activate"
    LEAVE_TRANSIENT = "mode.leave-transient"
    FOCUS_NEXT = "focus.next"
    FOCUS_PREVIOUS = "focus.previous"
    FOCUS_POINTER = "focus.pointer"
    SELECT_POINTER = "selection.pointer"
    SCROLL_UP = "scroll.up"
    SCROLL_DOWN = "scroll.down"
    DISPATCH_ACTION = "action.dispatch"
    OPEN_COMMAND_LINE = "command.open-line"


@dataclass(frozen=True, slots=True)
class Interaction:
    intent: InteractionIntent
    action_id: ActionId | None = None

    def __post_init__(self) -> None:
        if (self.intent is InteractionIntent.DISPATCH_ACTION) != (
            self.action_id is not None
        ):
            raise ValueError("only action dispatch interactions carry an action id")


@dataclass(frozen=True, slots=True)
class GesturePair:
    intent: InteractionIntent
    vi: tuple[str, ...]
    conventional: tuple[str, ...]
    action_id: ActionId | None = None


def _pair(
    intent: InteractionIntent,
    vi: str | None,
    conventional: str,
    *,
    action_id: ActionId | None = None,
) -> GesturePair:
    return GesturePair(intent, () if vi is None else (vi,), (conventional,), action_id)


NORMAL_GESTURE_PAIRS = (
    _pair(InteractionIntent.ITEM_PREVIOUS, "k", "up"),
    _pair(InteractionIntent.ITEM_NEXT, "j", "down"),
    _pair(InteractionIntent.SURFACE_PREVIOUS, "h", "left"),
    _pair(InteractionIntent.SURFACE_NEXT, "l", "right"),
    _pair(InteractionIntent.ITEM_FIRST, "gg", "home"),
    _pair(InteractionIntent.ITEM_LAST, "G", "end"),
    _pair(InteractionIntent.PAGE_UP, "ctrl+u", "pageup"),
    _pair(InteractionIntent.PAGE_DOWN, None, "pagedown"),
    _pair(
        InteractionIntent.DISPATCH_ACTION,
        "i",
        "focus:composer",
        action_id=ActionId.COMPOSE_ENTER,
    ),
    _pair(InteractionIntent.ACTIVATE_SELECTION, "enter", "enter"),
    _pair(InteractionIntent.LEAVE_TRANSIENT, "escape", "escape"),
    _pair(
        InteractionIntent.OPEN_COMMAND_LINE,
        ":",
        "colon",
    ),
    _pair(
        InteractionIntent.DISPATCH_ACTION,
        "ctrl+p",
        "ctrl+p",
        action_id=ActionId.COMMAND_OPEN,
    ),
    _pair(
        InteractionIntent.DISPATCH_ACTION, "/", "ctrl+f", action_id=ActionId.SEARCH_OPEN
    ),
    _pair(InteractionIntent.DISPATCH_ACTION, "?", "f1", action_id=ActionId.HELP_OPEN),
    _pair(
        InteractionIntent.DISPATCH_ACTION,
        "q",
        "ctrl+q",
        action_id=ActionId.APPLICATION_QUIT,
    ),
)

_NORMAL_GESTURES = {
    gesture: Interaction(pair.intent, pair.action_id)
    for pair in NORMAL_GESTURE_PAIRS
    for gesture in (*pair.vi, *pair.conventional)
}
_NORMAL_GESTURES["g g"] = _NORMAL_GESTURES["gg"]
_NORMAL_GESTURES["shift+g"] = _NORMAL_GESTURES["G"]
_NORMAL_GESTURES["g i"] = Interaction(
    InteractionIntent.DISPATCH_ACTION,
    ActionId.NOTIFICATIONS_OPEN,
)
_MODE_INDEPENDENT_GESTURES = {
    "tab": Interaction(InteractionIntent.FOCUS_NEXT),
    "shift+tab": Interaction(InteractionIntent.FOCUS_PREVIOUS),
    "enter": Interaction(InteractionIntent.ACTIVATE_SELECTION),
    "escape": Interaction(InteractionIntent.LEAVE_TRANSIENT),
}


def resolve_gesture(
    gesture: str,
    *,
    mode: InteractionMode,
) -> Interaction | None:
    """Resolve a canonical key/route without stealing text-entry keys."""

    independent = _MODE_INDEPENDENT_GESTURES.get(gesture)
    if independent is not None:
        return independent
    if mode is not InteractionMode.NORMAL:
        return None
    return _NORMAL_GESTURES.get(gesture)


class MouseGesture(StrEnum):
    FOCUS = "focus"
    SELECT = "select"
    ACTIVATE = "activate"
    SCROLL_UP = "scroll-up"
    SCROLL_DOWN = "scroll-down"
    COMPOSER = "composer"


_MOUSE_GESTURES = {
    MouseGesture.FOCUS: Interaction(InteractionIntent.FOCUS_POINTER),
    MouseGesture.SELECT: Interaction(InteractionIntent.SELECT_POINTER),
    MouseGesture.ACTIVATE: Interaction(InteractionIntent.ACTIVATE_SELECTION),
    MouseGesture.SCROLL_UP: Interaction(InteractionIntent.SCROLL_UP),
    MouseGesture.SCROLL_DOWN: Interaction(InteractionIntent.SCROLL_DOWN),
    MouseGesture.COMPOSER: Interaction(
        InteractionIntent.DISPATCH_ACTION,
        ActionId.COMPOSE_ENTER,
    ),
}


def resolve_mouse(gesture: MouseGesture) -> Interaction:
    return _MOUSE_GESTURES[gesture]


def gesture_hint(action_id: ActionId) -> str | None:
    """Return the paired vi/conventional discoverability hint for an action."""

    for pair in NORMAL_GESTURE_PAIRS:
        if pair.action_id is action_id:
            return f"{pair.vi[0]} / {pair.conventional[0]}"
    if action_id is ActionId.NOTIFICATIONS_OPEN:
        return "g i / palette"
    return None


__all__ = [
    "ACTION_REGISTRY",
    "ACTION_SPECS",
    "NORMAL_GESTURE_PAIRS",
    "ActionContext",
    "ActionFamily",
    "ActionId",
    "ActionInvocation",
    "ActionRoute",
    "ActionSpec",
    "ConfirmationPolicy",
    "GesturePair",
    "Interaction",
    "InteractionIntent",
    "MouseGesture",
    "action_spec",
    "available_action_specs",
    "gesture_hint",
    "invoke_action",
    "resolve_gesture",
    "resolve_mouse",
]
