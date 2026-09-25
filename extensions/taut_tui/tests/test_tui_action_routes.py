"""Executable action-route coverage through real Textual producers.

Spec references:
- docs/specs/10-taut-tui.md [TUI-2.2], [TUI-2.3], [TUI-13.2]
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from concurrent.futures import Future
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import pytest
from _action_completion import focus_widget, palette_query
from _completion import CompletionKey, CompletionScope
from _screen_completion import ScreenCompletions
from textual.widgets import Input

from taut.client import TautClient
from taut_tui.actions import (
    ACTION_SPECS,
    ActionId,
    ActionInvocation,
    ActionRoute,
)
from taut_tui.models import DraftState
from taut_tui.screens import CommandPaletteScreen, SearchScreen
from taut_tui.widgets import TautComposer

pytestmark = pytest.mark.sqlite_only


RoutePair = tuple[ActionId, ActionRoute]


@dataclass
class RouteContext:
    app: Any
    pilot: Any
    observations: list[ActionInvocation]
    scope: CompletionScope
    screens: ScreenCompletions
    patch: pytest.MonkeyPatch
    deadline: float = 0


RouteDriver = Callable[[RouteContext, ActionId], Awaitable[None]]


KEYBOARD_GESTURES: dict[ActionId, tuple[str, ...]] = {
    ActionId.NOTIFICATIONS_OPEN: ("g", "i"),
    ActionId.COMPOSE_ENTER: ("i",),
    ActionId.SEARCH_OPEN: ("ctrl+f",),
    ActionId.COMMAND_OPEN: ("ctrl+p",),
    ActionId.HELP_OPEN: ("f1",),
    ActionId.APPLICATION_QUIT: ("ctrl+q",),
}

MOUSE_CONTROLS: dict[ActionId, str] = {
    ActionId.MEMBERS_OPEN: "#members-action",
    ActionId.MESSAGE_SEND: "#composer-send",
    ActionId.MESSAGE_REPLY: "#reply-action",
    ActionId.MESSAGE_REACT: "#react-action",
    ActionId.MESSAGE_DELETE: "#delete-action",
    ActionId.SEARCH_OPEN: "#search-affordance",
    ActionId.COMMAND_OPEN: "#commands-affordance",
    ActionId.HELP_OPEN: "#help-affordance",
}

NAVIGATION_ACTIONS = {
    ActionId.WORKSPACE_INITIALIZE,
    ActionId.IDENTITY_REJOIN,
    ActionId.CONVERSATION_OPEN,
    ActionId.CHANNEL_JOIN,
    ActionId.DIRECT_MESSAGE_START,
    ActionId.NOTIFICATIONS_OPEN,
}

CONTEXT_ACTIONS = {ActionId.SEARCH_OPEN_RESULT}

DECLARED_PAIRS: tuple[RoutePair, ...] = tuple(
    (spec.action_id, route)
    for spec in ACTION_SPECS
    for route in sorted(spec.routes, key=lambda item: item.value)
)


def _supported_pairs() -> set[RoutePair]:
    palette = {
        (spec.action_id, ActionRoute.PALETTE)
        for spec in ACTION_SPECS
        if ActionRoute.PALETTE in spec.routes
    }
    keyboard = {
        (action_id, ActionRoute.KEYBOARD) for action_id in KEYBOARD_GESTURES
    } | {(ActionId.MESSAGE_SEND, ActionRoute.KEYBOARD)}
    mouse = {(action_id, ActionRoute.MOUSE) for action_id in MOUSE_CONTROLS} | {
        (ActionId.COMPOSE_ENTER, ActionRoute.MOUSE)
    }
    navigation = {
        (action_id, ActionRoute.NAVIGATION) for action_id in NAVIGATION_ACTIONS
    }
    context = {(action_id, ActionRoute.CONTEXT) for action_id in CONTEXT_ACTIONS}
    return palette | keyboard | mouse | navigation | context


def test_route_driver_inventory_exactly_matches_declared_pairs() -> None:
    declared = set(DECLARED_PAIRS)

    assert len(DECLARED_PAIRS) == len(declared)
    assert _supported_pairs() == declared
    assert {action_id for action_id, _route in declared} == set(ActionId)


async def _drive_palette(
    context: RouteContext,
    action_id: ActionId,
) -> None:
    app, pilot = context.app, context.pilot
    deadline = context.scope.now() + 5
    await pilot.press("ctrl+p")
    screen = app.screen
    assert isinstance(screen, CommandPaletteScreen)
    await context.screens.ready(screen, deadline=deadline)
    await context.screens.ready(
        screen, deadline=deadline, focus=screen.query_one("#palette-query", Input)
    )
    context.observations.clear()
    await palette_query(context.scope, context.patch, screen, action_id.value)
    context.deadline = context.scope.now() + 5
    await pilot.press("enter")


async def _drive_navigation(
    context: RouteContext,
    action_id: ActionId,
) -> None:
    from taut_tui.widgets import TautOptionList

    app, pilot = context.app, context.pilot
    target: str | ActionId = (
        "general" if action_id is ActionId.CONVERSATION_OPEN else action_id
    )
    app._set_navigation_actions((target,), (f"Route {action_id.value}",))
    navigation = app.query_one("#navigation-list", TautOptionList)
    navigation.highlighted = 0
    await focus_widget(context.scope, context.patch, app, navigation)
    context.deadline = context.scope.now() + 5
    await pilot.press("enter")


async def _drive_context(
    context: RouteContext,
    action_id: ActionId,
) -> None:
    from taut_tui.widgets import TautOptionList

    assert action_id is ActionId.SEARCH_OPEN_RESULT
    app, pilot = context.app, context.pilot
    deadline = context.scope.now() + 5
    await pilot.press("ctrl+f")
    screen = app.screen
    assert isinstance(screen, SearchScreen)
    await context.screens.ready(screen, deadline=deadline)
    context.observations.clear()
    query = screen.query_one("#search-query", Input)
    await context.screens.ready(screen, deadline=deadline, focus=query)
    query.value = "route-matrix-needle"
    generation = screen._generation + 1
    requested = context.scope.expect(
        CompletionKey(screen, "search.requested", request=query, generation=generation)
    )
    future: Future[Any] | None = None
    applied = None
    original_search = screen._search
    original_apply = screen._apply_results

    def search(text: str) -> Future[Any]:
        nonlocal future, applied
        future = original_search(text)
        applied = context.scope.expect(
            CompletionKey(
                screen, "search.applied", request=future, generation=generation
            )
        )
        requested.succeed(requested.key, applied)
        return future

    def apply(search_generation: int, done: Future[Any]) -> None:
        original_apply(search_generation, done)
        if search_generation == generation and done is future:
            assert applied is not None
            assert app.screen is screen and screen._generation == generation
            if done.cancelled():
                applied.cancel(applied.key)
            elif (error := done.exception()) is not None:
                applied.fail(applied.key, error)
            else:
                applied.succeed(applied.key, done.result())

    context.patch.setattr(screen, "_search", search)
    context.patch.setattr(screen, "_apply_results", apply)
    deadline = context.scope.now() + 5
    await pilot.press("enter")
    result = await requested.wait(deadline=deadline, description="search requested")
    await result.wait(deadline=deadline, description="search results applied")
    results = screen.query_one("#search-results", TautOptionList)
    assert results.option_count == 1
    results.highlighted = 0
    # A named widget focus event, separate from search result application.
    await focus_widget(context.scope, context.patch, app, results)
    context.deadline = context.scope.now() + 5
    await pilot.press("enter")


async def _drive_keyboard(
    context: RouteContext,
    action_id: ActionId,
) -> None:
    app, pilot = context.app, context.pilot
    if action_id is ActionId.MESSAGE_SEND:
        composer = app.query_one("#composer", TautComposer)
        composer.text = "route-matrix-send"
        await focus_widget(context.scope, context.patch, app, composer)
        context.deadline = context.scope.now() + 5
        await pilot.press("enter")
        return
    context.deadline = context.scope.now() + 5
    await pilot.press(*KEYBOARD_GESTURES[action_id])


async def _drive_mouse(
    context: RouteContext,
    action_id: ActionId,
) -> None:
    selector = (
        "#composer"
        if action_id is ActionId.COMPOSE_ENTER
        else MOUSE_CONTROLS[action_id]
    )
    context.deadline = context.scope.now() + 5
    assert await context.pilot.click(selector) is True


ROUTE_DRIVERS: dict[ActionRoute, RouteDriver] = {
    ActionRoute.PALETTE: _drive_palette,
    ActionRoute.NAVIGATION: _drive_navigation,
    ActionRoute.CONTEXT: _drive_context,
    ActionRoute.KEYBOARD: _drive_keyboard,
    ActionRoute.MOUSE: _drive_mouse,
}


@pytest.mark.parametrize(
    ("action_id", "route"),
    DECLARED_PAIRS,
    ids=[f"{action_id.value}-{route.value}" for action_id, route in DECLARED_PAIRS],
)
def test_every_declared_route_reaches_the_central_dispatcher_through_its_real_producer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    action_id: ActionId,
    route: ActionRoute,
) -> None:
    from taut_tui.app import TautApp

    db_path = tmp_path / "route-matrix.db"
    TautClient.init(db_path=db_path)
    alice = TautClient(db_path=db_path, as_name="alice")
    bob = TautClient(db_path=db_path, as_name="bob")
    for client in (alice, bob):
        client.join("general")
    message = bob.say("general", "route-matrix-needle")

    async def exercise() -> None:
        app = TautApp(db_path=str(db_path), as_name="alice", continuity_token=None)
        observations: list[ActionInvocation] = []
        with CompletionScope() as scope, monkeypatch.context() as patch:
            screens = ScreenCompletions(app, scope, patch)
            try:
                async with app.run_test(size=(130, 34)) as pilot:
                    # Framework startup has completed the real on_mount.
                    assert app._domain is not None
                    hit = alice.search("route-matrix-needle")[0]
                    app._target_labels["general"] = "#general"
                    app._target_kinds["general"] = "channel"
                    app._message_rows = (message,)
                    app._selected_search_hit = hit
                    app.visual_state = replace(
                        app.visual_state,
                        active_conversation="general",
                        selected_navigation="general",
                        selected_message_id=message.ts,
                    )
                    if action_id is ActionId.DRAFT_RECOVER:
                        app.visual_state = (
                            app.visual_state.with_draft(DraftState("old", "source"))
                            .with_draft(DraftState("general", "displaced"))
                            .after_channel_rename(
                                "old", "general", remap_open_view=False
                            )
                        )
                    app.query_one("#composer", TautComposer).text = "route-matrix-send"
                    app._update_context_affordances()
                    # One finite queue/refresh fence commits this local composer
                    # assignment and lays out click targets before the route action.
                    await pilot.pause()

                    original_dispatch = app._dispatch_action_invocation
                    dispatched = scope.expect(
                        CompletionKey(
                            app, "route.dispatched", request=action_id, generation=1
                        )
                    )

                    def observe(invocation: ActionInvocation) -> None:
                        observations.append(invocation)
                        original_dispatch(invocation)
                        if (
                            invocation.action_id is action_id
                            and invocation.source is route
                        ):
                            dispatched.succeed(dispatched.key, invocation)

                    patch.setattr(app, "_dispatch_action_invocation", observe)
                    context = RouteContext(
                        app, pilot, observations, scope, screens, patch
                    )
                    await ROUTE_DRIVERS[route](context, action_id)
                    await dispatched.wait(
                        deadline=context.deadline,
                        description="exact action route dispatched",
                    )

                    assert [
                        (invocation.action_id, invocation.source)
                        for invocation in observations
                    ] == [(action_id, route)]
            finally:
                screens.close()

    try:
        asyncio.run(exercise())
    finally:
        alice.close()
        bob.close()
