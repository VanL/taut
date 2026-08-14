"""Executable action-route coverage through real Textual producers.

Spec references:
- docs/specs/10-taut-tui.md [TUI-2.2], [TUI-2.3], [TUI-13.2]
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from textual.widgets import Input

from taut.client import TautClient
from taut_tui.actions import (
    ACTION_SPECS,
    ActionId,
    ActionInvocation,
    ActionRoute,
)

pytestmark = pytest.mark.sqlite_only


RoutePair = tuple[ActionId, ActionRoute]
RouteDriver = Callable[[Any, Any, ActionId, list[ActionInvocation]], Awaitable[None]]


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


async def _pause_until(
    pilot: Any,
    predicate: Callable[[], bool],
    *,
    attempts: int = 100,
) -> None:
    for _ in range(attempts):
        await pilot.pause(0.01)
        if predicate():
            return
    pytest.fail("condition did not become true")


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
    app: Any,
    pilot: Any,
    action_id: ActionId,
    observations: list[ActionInvocation],
) -> None:
    await pilot.press("ctrl+p")
    await _pause_until(pilot, lambda: bool(app.screen.query("#palette-query")))
    observations.clear()
    query = app.screen.query_one("#palette-query", Input)
    query.value = action_id.value
    await pilot.pause()
    await pilot.press("enter")


async def _drive_navigation(
    app: Any,
    pilot: Any,
    action_id: ActionId,
    observations: list[ActionInvocation],
) -> None:
    from taut_tui.widgets import TautOptionList

    del observations
    target: str | ActionId = (
        "general" if action_id is ActionId.CONVERSATION_OPEN else action_id
    )
    app._set_navigation_actions((target,), (f"Route {action_id.value}",))
    navigation = app.query_one("#navigation-list", TautOptionList)
    navigation.highlighted = 0
    navigation.focus()
    await pilot.press("enter")


async def _drive_context(
    app: Any,
    pilot: Any,
    action_id: ActionId,
    observations: list[ActionInvocation],
) -> None:
    from taut_tui.widgets import TautOptionList

    assert action_id is ActionId.SEARCH_OPEN_RESULT
    await pilot.press("ctrl+f")
    await _pause_until(pilot, lambda: bool(app.screen.query("#search-query")))
    observations.clear()
    query = app.screen.query_one("#search-query", Input)
    query.value = "route-matrix-needle"
    await pilot.press("enter")
    results = app.screen.query_one("#search-results", TautOptionList)
    await _pause_until(pilot, lambda: results.option_count == 1)
    results.highlighted = 0
    results.focus()
    await pilot.press("enter")


async def _drive_keyboard(
    app: Any,
    pilot: Any,
    action_id: ActionId,
    observations: list[ActionInvocation],
) -> None:
    del observations
    if action_id is ActionId.MESSAGE_SEND:
        composer = app.query_one("#composer", Input)
        composer.value = "route-matrix-send"
        composer.focus()
        await pilot.press("enter")
        return
    await pilot.press(*KEYBOARD_GESTURES[action_id])


async def _drive_mouse(
    app: Any,
    pilot: Any,
    action_id: ActionId,
    observations: list[ActionInvocation],
) -> None:
    del observations
    selector = (
        "#composer"
        if action_id is ActionId.COMPOSE_ENTER
        else MOUSE_CONTROLS[action_id]
    )
    assert await pilot.click(selector) is True


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
        async with app.run_test(size=(130, 34)) as pilot:
            await _pause_until(pilot, lambda: app._domain is not None)
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
            app.query_one("#composer", Input).value = "route-matrix-send"
            app._update_context_affordances()
            await pilot.pause()

            original_dispatch = app._dispatch_action_invocation

            def observe(invocation: ActionInvocation) -> None:
                observations.append(invocation)
                original_dispatch(invocation)

            monkeypatch.setattr(app, "_dispatch_action_invocation", observe)
            await ROUTE_DRIVERS[route](app, pilot, action_id, observations)
            await _pause_until(pilot, lambda: bool(observations))

            assert [
                (invocation.action_id, invocation.source) for invocation in observations
            ] == [(action_id, route)]

    try:
        asyncio.run(exercise())
    finally:
        alice.close()
        bob.close()
