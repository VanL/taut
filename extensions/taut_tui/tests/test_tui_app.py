"""Real TUI extension behavior over the pure action and layout models.

Spec references:
- docs/specs/10-taut-tui.md [TUI-4.3], [TUI-5], [TUI-8], [TUI-9]
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from concurrent.futures import Future
from pathlib import Path
from typing import Any

import pytest
from textual.widgets import Button, Input

from taut.client import TautClient
from taut_tui.models import InteractionMode, LayoutMode

pytestmark = pytest.mark.sqlite_only


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


def _option_index_containing(option_list: Any, text: str) -> int:
    """Resolve a semantic row without depending on navigation ordering."""

    return next(
        index
        for index in range(option_list.option_count)
        if text in str(option_list.get_option_at_index(index).prompt)
    )


def _has_option_containing(option_list: Any, text: str) -> bool:
    return any(
        text in str(option_list.get_option_at_index(index).prompt)
        for index in range(option_list.option_count)
    )


def test_real_app_exposes_low_chrome_surfaces_and_mode_status() -> None:
    from taut_tui.app import TautApp

    async def exercise() -> None:
        app = TautApp(db_path=None, as_name="van", continuity_token=None)
        async with app.run_test(size=(130, 34)) as pilot:
            await pilot.pause()
            assert app.layout_mode is LayoutMode.WIDE
            assert app.query_one("#navigation").display is True
            assert app.query_one("#conversation").display is True
            assert app.query_one("#inspector").display is True
            assert "NORMAL" in str(app.query_one("#status-line").render())
            assert "van" not in str(app.query_one("#status-line").render())

    asyncio.run(exercise())


def test_watched_future_drops_result_if_shutdown_starts_after_queueing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from taut_tui.app import TautApp

    app = TautApp(db_path=None, as_name=None, continuity_token=None)
    queued: list[tuple[Callable[..., None], tuple[object, ...]]] = []
    applied: list[Future[None]] = []

    def queue(callback: Callable[..., None], *args: object) -> None:
        queued.append((callback, args))

    monkeypatch.setattr(app, "call_later", queue)
    future: Future[None] = Future()
    app._watch_future(future, applied.append)
    future.set_result(None)
    assert len(queued) == 1

    app._shutting_down = True
    callback, args = queued[0]
    callback(*args)

    assert applied == []


def test_watched_future_contains_missing_widget_during_screen_teardown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from textual.css.query import NoMatches

    from taut_tui.app import TautApp

    app = TautApp(db_path=None, as_name=None, continuity_token=None)
    queued: list[tuple[Callable[..., None], tuple[object, ...]]] = []

    def queue(callback: Callable[..., None], *args: object) -> None:
        queued.append((callback, args))

    def detached_apply(_future: Future[None]) -> None:
        raise NoMatches("screen detached")

    monkeypatch.setattr(app, "call_later", queue)
    future: Future[None] = Future()
    app._watch_future(future, detached_apply)
    future.set_result(None)

    callback, args = queued[0]
    callback(*args)


def test_token_only_rejoin_form_reaches_the_real_public_client(tmp_path: Path) -> None:
    from taut_tui.actions import ActionId
    from taut_tui.app import TautApp
    from taut_tui.screens import FormSubmission

    db_path = tmp_path / "token-only-rejoin.db"
    TautClient.init(db_path=db_path)
    creator = TautClient(db_path=db_path, as_name="alice")
    creator.join("general")
    created = creator.last_created_member
    assert created is not None
    assert created.token is not None
    creator.close()

    class ScreenProbe:
        def __init__(self) -> None:
            self.completed = False
            self.error: str | None = None

        def complete(self) -> None:
            self.completed = True

        def show_domain_error(self, message: str) -> None:
            self.error = message

    async def exercise() -> None:
        app = TautApp(db_path=str(db_path), as_name=None, continuity_token=None)
        async with app.run_test(size=(100, 34)) as pilot:
            assert app._domain is not None
            screen = ScreenProbe()
            assert app._complete_identity_form(
                FormSubmission(
                    ActionId.IDENTITY_REJOIN,
                    {"name_or_alias": "", "continuity_token": created.token or ""},
                ),
                app._domain,
                screen=screen,  # type: ignore[arg-type]
            )
            await _pause_until(
                pilot, lambda: screen.completed or screen.error is not None
            )
            assert screen.completed is True
            assert screen.error is None
            assert (
                app._domain.show_identity().result(timeout=5).member_id
                == created.member_id
            )

    asyncio.run(exercise())


def test_help_teaches_consumable_shared_notification_pointers() -> None:
    from taut_tui.app import TautApp

    async def exercise() -> None:
        app = TautApp(db_path=None, as_name=None, continuity_token=None)
        async with app.run_test(size=(100, 34)):
            app.action_open_help()
            rendered = str(app.query_one("#inspector-body").render())
            assert "consumable and shared by sessions" in rendered
            assert "chat history remains durable" in rendered

    asyncio.run(exercise())


def test_real_empty_search_renders_no_matches_in_the_native_screen(
    tmp_path: Path,
) -> None:
    from textual.widgets import Input, Static

    from taut_tui.app import TautApp

    db_path = tmp_path / "empty-search-screen.db"
    TautClient.init(db_path=db_path)
    setup = TautClient(db_path=db_path, as_name="alice")
    setup.join("general")
    setup.close()

    async def exercise() -> None:
        app = TautApp(db_path=str(db_path), as_name="alice", continuity_token=None)
        async with app.run_test(size=(100, 34)) as pilot:
            app.action_open_search()
            await pilot.pause()
            query = app.screen.query_one("#search-query", Input)
            query.value = "nothing-can-match-this"
            await pilot.press("enter")
            errors = app.screen.query_one("#search-errors", Static)
            await _pause_until(pilot, lambda: "No matches" in str(errors.render()))

            assert str(errors.render()) == "No matches"

    asyncio.run(exercise())


def test_vi_and_conventional_keys_share_mode_actions_without_stealing_text() -> None:
    from dataclasses import replace

    from taut_tui.app import TautApp

    async def exercise() -> None:
        app = TautApp(db_path=None, as_name=None, continuity_token=None)
        async with app.run_test(size=(100, 34)) as pilot:
            app.visual_state = replace(
                app.visual_state,
                active_conversation="general",
            )
            await pilot.press("i")
            assert app.visual_state.mode is InteractionMode.COMPOSE
            composer = app.query_one("#composer", Input)
            assert composer.has_focus
            await pilot.press("q", "/", ":")
            assert composer.value == "q/:"
            assert app.visual_state.mode is InteractionMode.COMPOSE
            await pilot.press("escape")
            assert app.visual_state.mode is InteractionMode.NORMAL
            await pilot.press("ctrl+p")
            assert app.visual_state.mode is InteractionMode.COMMAND
            await pilot.press("escape", "ctrl+f")
            assert app.visual_state.mode is InteractionMode.SEARCH

    asyncio.run(exercise())


def test_real_resize_reflows_without_replacing_visual_state() -> None:
    from dataclasses import replace

    from taut_tui.app import TautApp

    async def exercise() -> None:
        app = TautApp(db_path=None, as_name=None, continuity_token=None)
        async with app.run_test(size=(130, 34)) as pilot:
            app.visual_state = replace(
                app.visual_state,
                active_conversation="general",
            )
            await pilot.press("i", "d", "r", "a", "f", "t")
            await pilot.resize_terminal(64, 34)
            assert app.layout_mode is LayoutMode.COMPACT
            assert app.query_one("#navigation").display is False
            assert app.query_one("#conversation").display is True
            assert app.query_one("#composer", Input).value == "draft"

            await pilot.resize_terminal(40, 15)
            assert app.layout_mode is LayoutMode.TOO_SMALL
            assert app.query_one("#resize-hint").display is True

            await pilot.resize_terminal(130, 34)
            assert app.layout_mode is LayoutMode.WIDE
            assert app.query_one("#composer", Input).value == "draft"

    asyncio.run(exercise())


def test_app_can_start_at_too_small_and_recover_to_the_base_screen() -> None:
    from taut_tui.app import TautApp, TerminalTooSmallScreen

    async def exercise() -> None:
        app = TautApp(db_path=None, as_name=None, continuity_token=None)
        async with app.run_test(size=(40, 15)) as pilot:
            assert app.layout_mode is LayoutMode.TOO_SMALL
            assert isinstance(app.screen, TerminalTooSmallScreen)
            assert app.focused is not None
            assert app.focused.id == "resize-hint"

            await pilot.resize_terminal(100, 34)
            assert not isinstance(app.screen, TerminalTooSmallScreen)
            assert app.query_one("#conversation").display is True

    asyncio.run(exercise())


def test_too_small_hides_active_modal_and_restores_its_typed_input(
    tmp_path: Path,
) -> None:
    from taut_tui.app import TautApp
    from taut_tui.models import LogicalSurface

    db_path = tmp_path / "modal-resize.db"
    TautClient.init(db_path=db_path)

    async def exercise() -> None:
        app = TautApp(db_path=str(db_path), as_name=None, continuity_token=None)
        async with app.run_test(size=(100, 34)) as pilot:
            await pilot.press("ctrl+p", *"doctor")
            query = app.screen.query_one("#palette-query", Input)
            assert query.value == "doctor"

            await pilot.resize_terminal(40, 15)
            assert app.layout_mode is LayoutMode.TOO_SMALL
            assert app._query_base("#resize-hint").display is True
            assert app.visual_state.focus.surface is LogicalSurface.RESIZE_HINT
            assert app.focused is not None
            assert app.focused.id == "resize-hint"
            await pilot.press("x")
            assert query.value == "doctor"

            await pilot.resize_terminal(100, 34)
            assert app.screen.query_one("#palette-query", Input).value == "doctor"
            assert app.screen.query_one("#palette-query", Input).has_focus

    asyncio.run(exercise())


def test_too_small_shields_a_nested_modal_stack_and_restores_exact_focus(
    tmp_path: Path,
) -> None:
    from taut_tui.actions import ActionId
    from taut_tui.app import TautApp
    from taut_tui.forms import form_spec
    from taut_tui.screens import ConfirmationScreen, NativeFormScreen

    db_path = tmp_path / "nested-modal-resize.db"
    TautClient.init(db_path=db_path)

    async def exercise() -> None:
        app = TautApp(db_path=str(db_path), as_name=None, continuity_token=None)
        async with app.run_test(size=(100, 34)) as pilot:
            form = NativeFormScreen(form_spec(ActionId.IDENTITY_SET_NAME))
            app.push_screen(form)
            await pilot.pause()
            field = form.query_one("#field-name", Input)
            field.value = "kept"
            confirmation = ConfirmationScreen("Rename exact target?")
            app.push_screen(confirmation)
            await pilot.pause()
            confirmation.query_one("#confirmation-confirm", Button).focus()

            await pilot.resize_terminal(40, 15)
            assert app.focused is not None
            assert app.focused.id == "resize-hint"
            await pilot.press("x", "escape")
            assert field.value == "kept"

            await pilot.resize_terminal(100, 34)
            assert app.screen is confirmation
            assert confirmation.query_one("#confirmation-confirm", Button).has_focus
            assert field.value == "kept"

    asyncio.run(exercise())


def test_real_transcript_viewport_anchor_survives_width_reflow(
    tmp_path: Path,
) -> None:
    from taut_tui.app import TautApp
    from taut_tui.widgets import TautOptionList

    db_path = tmp_path / "viewport-reflow.db"
    TautClient.init(db_path=db_path)
    alice = TautClient(db_path=db_path, as_name="alice")
    alice.join("general")
    for index in range(30):
        alice.say(
            "general",
            f"message {index:02d} " + ("wrap this transcript row " * 8),
        )

    async def exercise() -> None:
        app = TautApp(db_path=str(db_path), as_name="alice", continuity_token=None)
        async with app.run_test(size=(100, 24)) as pilot:
            navigation = app.query_one("#navigation-list", TautOptionList)
            await _pause_until(
                pilot,
                lambda: _has_option_containing(navigation, "#general"),
            )
            navigation.highlighted = _option_index_containing(navigation, "#general")
            navigation.focus()
            await pilot.press("enter")
            await _pause_until(
                pilot,
                lambda: len(app._message_rows) >= 30,
            )
            transcript = app.query_one("#transcript", TautOptionList)
            transcript.scroll_to(y=18, animate=False, force=True)
            await pilot.pause()
            app._capture_scroll_anchor()
            before = app.visual_state.scroll_anchor
            assert before.tail_pinned is False
            assert before.message_id is not None

            await pilot.resize_terminal(64, 24)
            await pilot.pause()
            assert app.visual_state.scroll_anchor == before
            assert await pilot.click("#pane-affordance") is True
            await pilot.pause()
            app._capture_scroll_anchor()
            after = app.visual_state.scroll_anchor
            assert after.message_id == before.message_id
            assert after.intra_row_offset == before.intra_row_offset

            compact_width = max(1, transcript.scrollable_content_region.width)
            anchor_index = next(
                index
                for index, message in enumerate(app._message_rows)
                if message.ts == after.message_id
            )
            compact_height = app._message_row_height(
                app._message_rows[anchor_index], compact_width
            )
            deep_offset = max(0, compact_height - 1)
            app._restore_transcript_anchor(
                app._message_rows,
                anchor_index,
                deep_offset,
            )
            await pilot.pause()
            app._capture_scroll_anchor()
            compact_anchor = app.visual_state.scroll_anchor
            assert compact_anchor.message_id == after.message_id

            await pilot.resize_terminal(100, 24)
            await pilot.pause()
            app._capture_scroll_anchor()
            widened = app.visual_state.scroll_anchor
            assert widened.message_id == compact_anchor.message_id

    try:
        asyncio.run(exercise())
    finally:
        alice.close()


def test_mouse_click_focuses_composer() -> None:
    from taut_tui.app import TautApp

    async def exercise() -> None:
        app = TautApp(db_path=None, as_name=None, continuity_token=None)
        async with app.run_test(size=(100, 34)) as pilot:
            assert await pilot.click("#composer") is True
            assert app.query_one("#composer").has_focus
            assert app.visual_state.mode is InteractionMode.COMPOSE

    asyncio.run(exercise())


def test_mouse_command_affordance_dispatches_the_native_palette() -> None:
    from taut_tui.app import TautApp

    async def exercise() -> None:
        app = TautApp(db_path=None, as_name=None, continuity_token=None)
        async with app.run_test(size=(100, 34)) as pilot:
            assert await pilot.click("#commands-affordance") is True
            assert app.visual_state.mode is InteractionMode.COMMAND
            assert list(app.screen.query("#palette-query"))

    asyncio.run(exercise())


def test_command_palette_excludes_command_open_action() -> None:
    from taut_tui.actions import (
        ActionId,
        ActionRoute,
        available_action_specs,
    )
    from taut_tui.app import TautApp
    from taut_tui.widgets import TautOptionList

    async def exercise() -> None:
        app = TautApp(db_path=None, as_name=None, continuity_token=None)
        async with app.run_test(size=(100, 34)) as pilot:
            await pilot.press("ctrl+p")
            results = app.screen.query_one("#palette-results", TautOptionList)
            visible_ids = {
                results.get_option_at_index(index).id
                for index in range(results.option_count)
            }
            expected_ids = {
                spec.action_id.value
                for spec in available_action_specs(
                    summon_available=app._summon is not None,
                    route=ActionRoute.PALETTE,
                )
            }
            assert visible_ids == expected_ids
            assert ActionId.COMMAND_OPEN.value not in visible_ids

    asyncio.run(exercise())


def test_command_palette_double_click_dismisses_only_once() -> None:
    from taut_tui.app import TautApp

    async def exercise() -> None:
        app = TautApp(db_path=None, as_name=None, continuity_token=None)
        async with app.run_test(size=(100, 34)) as pilot:
            await pilot.press("ctrl+p")
            assert await pilot.click("#palette-results", offset=(1, 0), times=2)
            await pilot.pause()
            assert app.screen is app._base_screen
            assert app.visual_state.mode is InteractionMode.NORMAL

    asyncio.run(exercise())


def test_empty_state_actions_use_the_navigation_route(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from taut_tui.actions import ActionId, ActionInvocation, ActionRoute
    from taut_tui.app import TautApp
    from taut_tui.models import LogicalSurface
    from taut_tui.widgets import TautOptionList

    initialized_path = tmp_path / "empty-navigation.db"
    TautClient.init(db_path=initialized_path)
    cases = (
        (None, ActionId.WORKSPACE_INITIALIZE),
        (str(initialized_path), ActionId.CHANNEL_JOIN),
        (str(initialized_path), ActionId.IDENTITY_REJOIN),
    )

    async def exercise(db_path: str | None, expected: ActionId) -> None:
        seen: list[ActionInvocation] = []
        app = TautApp(db_path=db_path, as_name=None, continuity_token=None)
        async with app.run_test(size=(100, 34)) as pilot:
            navigation = app.query_one("#navigation-list", TautOptionList)
            await _pause_until(
                pilot,
                lambda: expected in app._navigation_targets,
            )
            navigation.highlighted = app._navigation_targets.index(expected)
            navigation.focus()
            monkeypatch.setattr(app, "_dispatch_action_invocation", seen.append)
            await pilot.press("enter")

            assert len(seen) == 1
            assert seen[0].action_id is expected
            assert seen[0].source is ActionRoute.NAVIGATION
            assert seen[0].context.surface is LogicalSurface.NAVIGATION

    for db_path, expected in cases:
        asyncio.run(exercise(db_path, expected))


def test_explicit_mouse_controls_use_the_typed_action_dispatcher(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from taut_tui.actions import ActionId, ActionInvocation, ActionRoute
    from taut_tui.app import TautApp
    from taut_tui.widgets import TautOptionList

    db_path = tmp_path / "mouse-context-actions.db"
    TautClient.init(db_path=db_path)
    alice = TautClient(db_path=db_path, as_name="alice")
    alice.join("general")
    alice.say("general", "select me")
    seen: list[ActionInvocation] = []

    async def exercise() -> None:
        app = TautApp(db_path=str(db_path), as_name="alice", continuity_token=None)
        async with app.run_test(size=(130, 34)) as pilot:
            navigation = app.query_one("#navigation-list", TautOptionList)
            await _pause_until(
                pilot,
                lambda: _has_option_containing(navigation, "#general"),
            )
            navigation.highlighted = _option_index_containing(navigation, "#general")
            navigation.focus()
            await pilot.press("enter")
            await _pause_until(pilot, lambda: bool(app._message_rows))
            transcript = app.query_one("#transcript", TautOptionList)
            transcript.highlighted = 0
            await _pause_until(
                pilot,
                lambda: all(
                    app.query_one(selector).display
                    for selector in (
                        "#composer-send",
                        "#members-action",
                        "#reply-action",
                        "#react-action",
                        "#delete-action",
                    )
                ),
            )

            monkeypatch.setattr(app, "_dispatch_action_invocation", seen.append)
            for selector in (
                "#composer-send",
                "#members-action",
                "#reply-action",
                "#react-action",
                "#delete-action",
            ):
                assert await pilot.click(selector) is True

            assert [item.action_id for item in seen] == [
                ActionId.MESSAGE_SEND,
                ActionId.MEMBERS_OPEN,
                ActionId.MESSAGE_REPLY,
                ActionId.MESSAGE_REACT,
                ActionId.MESSAGE_DELETE,
            ]
            assert all(item.source is ActionRoute.MOUSE for item in seen)

    try:
        asyncio.run(exercise())
    finally:
        alice.close()


@pytest.mark.parametrize("width", [100, 120, 130])
def test_context_mouse_controls_fit_inside_the_visible_inspector(
    tmp_path: Path,
    width: int,
) -> None:
    from dataclasses import replace

    from taut_tui.app import TautApp

    db_path = tmp_path / f"context-fit-{width}.db"
    TautClient.init(db_path=db_path)

    async def exercise() -> None:
        app = TautApp(db_path=str(db_path), as_name=None, continuity_token=None)
        async with app.run_test(size=(width, 34)):
            app.visual_state = replace(
                app.visual_state,
                active_conversation="general",
                selected_message_id=1,
            )
            app._message_rows = (
                Message("general", 1, "m_alice", "alice", "message", "hi"),
            )
            app._update_context_affordances()
            actions = app.query_one("#context-actions")
            if not actions.display:
                app.visual_state = replace(
                    app.visual_state,
                    inspector=InspectorState(InspectorKind.MESSAGE),
                    pane_choice=LogicalSurface.INSPECTOR,
                    focus=FocusTarget(LogicalSurface.INSPECTOR, "inspector-body"),
                )
                app._apply_placement(app._accepted_size)
            region = actions.content_region
            for selector in (
                "#members-action",
                "#reply-action",
                "#react-action",
                "#delete-action",
            ):
                button = app.query_one(selector, Button)
                assert button.region.x >= region.x
                assert button.region.right <= region.right

    from taut.client import Message
    from taut_tui.models import (
        FocusTarget,
        InspectorKind,
        InspectorState,
        LogicalSurface,
    )

    asyncio.run(exercise())


def test_composer_enter_uses_the_typed_keyboard_action_dispatcher(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from taut_tui.actions import ActionId, ActionInvocation, ActionRoute
    from taut_tui.app import TautApp

    seen: list[ActionInvocation] = []

    async def exercise() -> None:
        app = TautApp(db_path=None, as_name=None, continuity_token=None)
        async with app.run_test(size=(100, 34)) as pilot:
            composer = app.query_one("#composer", Input)
            composer.value = "route this send"
            composer.focus()
            monkeypatch.setattr(app, "_dispatch_action_invocation", seen.append)

            await pilot.press("enter")

            assert len(seen) == 1
            assert seen[0].action_id is ActionId.MESSAGE_SEND
            assert seen[0].source is ActionRoute.KEYBOARD

    asyncio.run(exercise())


def test_summon_public_status_and_live_members_keep_correlated_fields() -> None:
    from taut_summon import SummonedMember, SummonStatus

    from taut_tui.app import _safe_projection

    status = SummonStatus(
        member_id="m_agent",
        name="agent",
        driver="codex",
        provider="openai",
        provider_session_id="session-1",
        thread_count=2,
        cursor_lag={"general": 3},
        details={"state": "ready"},
    )
    member = SummonedMember(
        member_id="m_agent",
        name="agent",
        provider="openai",
        provider_session_id="session-1",
    )

    rendered_status = _safe_projection(status)
    for expected in (
        "agent",
        "provider=openai",
        "driver=codex",
        "session=session-1",
        "threads=2",
        "#general:3",
        "state=ready",
    ):
        assert expected in rendered_status
    rendered_member = _safe_projection(member)
    for expected in ("agent", "openai", "live", "session=session-1"):
        assert expected in rendered_member


def test_summon_internal_tokens_never_render_as_human_identity() -> None:
    from taut_tui.app import TautApp
    from taut_tui.summon import OwnedSummonRun

    token = "0123456789abcdef"

    async def exercise() -> None:
        app = TautApp(db_path=None, as_name=None, continuity_token=None)
        async with app.run_test(size=(100, 34)):
            app._owned_summon_tokens.add(token)
            app._summon_names[token] = "requested-agent"
            app._operation_state = "summon requested-agent starting"
            app._update_status()
            assert token[:8] not in str(app.query_one("#status-line").render())

            app._apply_summon_ready(
                OwnedSummonRun(
                    token=token,
                    pending=False,
                    member_id="member-1",
                    member_name="actual-agent",
                )
            )
            completed: Future[None] = Future()
            completed.set_result(None)
            app._apply_summon_return(token, completed)

            rendered = str(app.query_one("#inspector-body").render())
            assert "actual-agent" in rendered
            assert token[:8] not in rendered

    asyncio.run(exercise())


def test_broken_summon_startup_and_sync_operations_stay_visible(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from taut_tui import app as app_module
    from taut_tui.actions import ActionId, ActionRoute
    from taut_tui.app import TautApp
    from taut_tui.screens import SummonStartSubmission

    class BrokenStartup:
        def __init__(self, **_kwargs: object) -> None:
            raise RuntimeError("summon controller startup failed")

    db_path = tmp_path / "broken-summon.db"
    TautClient.init(db_path=db_path)

    async def startup() -> None:
        monkeypatch.setattr(app_module, "TuiSummonOperations", BrokenStartup)
        app = TautApp(db_path=str(db_path), as_name=None, continuity_token=None)
        async with app.run_test(size=(100, 34)):
            assert app._summon is None
            assert "summon controller startup failed" in str(
                app.query_one("#inspector-body").render()
            )

    asyncio.run(startup())

    class BrokenOperations:
        def close(self) -> None:
            return

        def provider_names(self) -> tuple[str, ...]:
            raise RuntimeError("provider discovery failed")

        def build_request(self, **_kwargs: object) -> object:
            raise RuntimeError("request construction failed")

    async def synchronous() -> None:
        monkeypatch.undo()
        app = TautApp(db_path=str(db_path), as_name=None, continuity_token=None)
        async with app.run_test(size=(100, 34)):
            app._summon = BrokenOperations()  # type: ignore[assignment]
            app._dispatch_tui_action(
                ActionId.SUMMON_START,
                source=ActionRoute.PALETTE,
            )
            assert "provider discovery failed" in str(
                app.query_one("#inspector-body").render()
            )

            app._summon_interaction = object()  # type: ignore[assignment]
            app._complete_summon_start(
                SummonStartSubmission(
                    name="agent",
                    threads=("general",),
                    provider=None,
                    persona=None,
                    system_prompt_file=None,
                    rate_limit=None,
                    terminal=False,
                    attach=False,
                    detach=False,
                    takeover=False,
                )
            )
            assert "request construction failed" in str(
                app.query_one("#inspector-body").render()
            )

    asyncio.run(synchronous())


def test_palette_entries_report_current_scope_gestures_and_disabled_reasons(
    tmp_path: Path,
) -> None:
    from dataclasses import replace

    from taut_tui.actions import ActionId
    from taut_tui.app import TautApp

    db_path = tmp_path / "palette-scope.db"
    TautClient.init(db_path=db_path)

    async def exercise() -> None:
        app = TautApp(db_path=str(db_path), as_name=None, continuity_token=None)
        async with app.run_test(size=(100, 34)):
            target = "dm.d_example"
            app._target_labels[target] = "DM with bob"
            app._target_kinds[target] = "dm"
            app.visual_state = replace(
                app.visual_state,
                active_conversation=target,
            )
            entries = {
                entry.action.action_id: entry for entry in app._palette_entries()
            }

            leave = entries[ActionId.CHANNEL_LEAVE]
            assert leave.enabled is False
            assert leave.reason == "Select a channel first"
            assert leave.scope == "DM with bob"
            assert entries[ActionId.MESSAGE_DELETE].reason == "Select a message first"
            assert entries[ActionId.COMPOSE_ENTER].enabled is True
            assert entries[ActionId.COMPOSE_ENTER].scope == "DM with bob"
            assert entries[ActionId.COMPOSE_ENTER].gesture_hint is not None

    asyncio.run(exercise())


def test_palette_applicability_is_driven_by_current_visual_facts(
    tmp_path: Path,
) -> None:
    from dataclasses import replace

    from taut.client import Message, SearchHit
    from taut_tui.actions import ActionId
    from taut_tui.app import TautApp
    from taut_tui.models import DraftState

    db_path = tmp_path / "palette-applicability.db"
    TautClient.init(db_path=db_path)

    async def exercise() -> None:
        app = TautApp(db_path=str(db_path), as_name=None, continuity_token=None)
        async with app.run_test(size=(100, 34)):

            def entries() -> dict[ActionId, Any]:
                return {
                    entry.action.action_id: entry for entry in app._palette_entries()
                }

            assert entries()[ActionId.CHANNEL_LEAVE].reason == (
                "Select a channel first"
            )
            assert entries()[ActionId.MEMBERS_OPEN].reason == (
                "Select a conversation first"
            )

            target = "dm.d_example"
            app._target_kinds[target] = "dm"
            app.visual_state = replace(
                app.visual_state,
                active_conversation=target,
            )
            assert entries()[ActionId.CHANNEL_LEAVE].reason == (
                "Select a channel first"
            )
            assert entries()[ActionId.MESSAGE_SEND].reason == "Enter a message first"

            app.visual_state = app.visual_state.with_draft(
                DraftState(target=target, text="   ", cursor_position=3, revision=1)
            )
            assert entries()[ActionId.MESSAGE_SEND].reason == "Enter a message first"

            app.visual_state = app.visual_state.with_draft(
                DraftState(target=target, text="ready", cursor_position=5, revision=2)
            )
            assert entries()[ActionId.MESSAGE_SEND].enabled is True

            app.visual_state = replace(app.visual_state, selected_message_id=7)
            app._message_rows = ()
            assert entries()[ActionId.MESSAGE_REACT].reason == "Select a message first"
            app._message_rows = (
                Message(target, 7, "m_alice", "alice", "message", "hello"),
            )
            assert entries()[ActionId.MESSAGE_REACT].enabled is True

            assert entries()[ActionId.SEARCH_OPEN_RESULT].reason == (
                "Select a search result first"
            )
            app._selected_search_hit = SearchHit(
                thread=target,
                ts=7,
                from_id="m_alice",
                from_name="alice",
                kind="message",
                text="hello",
                thread_kind="dm",
                channel=None,
                parent=None,
                members=("m_alice", "m_bob"),
            )
            assert entries()[ActionId.SEARCH_OPEN_RESULT].enabled is True

            app._target_kinds[target] = "channel"
            assert entries()[ActionId.CHANNEL_LEAVE].enabled is True

    asyncio.run(exercise())


def test_central_dispatch_enforces_applicability_before_forms_and_mouse_handlers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from dataclasses import replace

    from taut_tui.actions import ActionId, ActionRoute
    from taut_tui.app import TautApp

    db_path = tmp_path / "dispatch-applicability.db"
    TautClient.init(db_path=db_path)

    async def exercise() -> None:
        app = TautApp(db_path=str(db_path), as_name=None, continuity_token=None)
        async with app.run_test(size=(130, 34)) as pilot:
            await _pause_until(pilot, lambda: app._domain is not None)
            target = "general"
            app._target_kinds[target] = "channel"
            app.visual_state = replace(
                app.visual_state,
                active_conversation=target,
            )
            app._update_context_affordances()
            reached: list[str] = []
            monkeypatch.setattr(
                app,
                "_submit_composer",
                lambda _text: reached.append("send"),
            )

            send_entry = next(
                entry
                for entry in app._palette_entries()
                if entry.action.action_id is ActionId.MESSAGE_SEND
            )
            assert send_entry.enabled is False
            assert send_entry.reason == "Enter a message first"
            assert app.query_one("#composer-send").display is True
            app.query_one("#composer-send", Button).press()
            await pilot.pause()
            assert reached == []
            assert send_entry.reason in str(app.query_one("#inspector-body").render())

            app.visual_state = replace(app.visual_state, selected_message_id=99)
            app._message_rows = ()
            app._dispatch_tui_action(
                ActionId.MESSAGE_REPLY,
                source=ActionRoute.PALETTE,
            )
            assert app.screen is app._base_screen
            assert "Select a message first" in str(
                app.query_one("#inspector-body").render()
            )

    asyncio.run(exercise())


def test_conversation_open_evaluates_after_navigation_target_projection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from taut_tui.actions import ActionContext, ActionId, ActionRoute, invoke_action
    from taut_tui.app import TautApp

    db_path = tmp_path / "projected-applicability.db"
    TautClient.init(db_path=db_path)

    async def exercise() -> None:
        app = TautApp(db_path=str(db_path), as_name=None, continuity_token=None)
        async with app.run_test(size=(100, 34)) as pilot:
            await _pause_until(pilot, lambda: app._domain is not None)
            reached: list[ActionId] = []

            def dispatch(action_id: ActionId, _domain: object) -> bool:
                reached.append(action_id)
                return True

            monkeypatch.setattr(
                app,
                "_dispatch_simple_domain_action",
                dispatch,
            )

            app._dispatch_action_invocation(
                invoke_action(
                    ActionId.CONVERSATION_OPEN,
                    ActionContext(target="general"),
                    source=ActionRoute.NAVIGATION,
                )
            )

            assert app.visual_state.selected_navigation == "general"
            assert reached == [ActionId.CONVERSATION_OPEN]

    asyncio.run(exercise())


def test_navigation_single_click_selects_while_enter_and_double_click_activate(
    tmp_path: Path,
) -> None:
    from taut_tui.app import TautApp
    from taut_tui.widgets import TautOptionList

    db_path = tmp_path / "pointer.db"
    TautClient.init(db_path=db_path)
    setup = TautClient(db_path=db_path, as_name="alice")
    setup.join("general")
    setup.close()

    async def exercise() -> None:
        app = TautApp(db_path=str(db_path), as_name="alice", continuity_token=None)
        async with app.run_test(size=(100, 34)) as pilot:
            navigation = app.query_one("#navigation-list", TautOptionList)
            await _pause_until(
                pilot,
                lambda: app._navigation_targets[:1] == ["general"],
            )
            assert await pilot.click("#navigation-list", offset=(1, 0)) is True
            await _pause_until(pilot, lambda: navigation.highlighted == 0)
            assert navigation.highlighted == 0
            assert app.visual_state.active_conversation is None

            await pilot.press("enter")
            for _ in range(100):
                await pilot.pause(0.01)
                if app.visual_state.active_conversation == "general":
                    break
            assert app.visual_state.active_conversation == "general"

        second = TautApp(db_path=str(db_path), as_name="alice", continuity_token=None)
        async with second.run_test(size=(100, 34)) as pilot:
            navigation = second.query_one("#navigation-list", TautOptionList)
            await _pause_until(
                pilot,
                lambda: second._navigation_targets[:1] == ["general"],
            )
            assert await pilot.click("#navigation-list", offset=(1, 0), times=2) is True
            for _ in range(100):
                await pilot.pause(0.01)
                if second.visual_state.active_conversation == "general":
                    break
            assert second.visual_state.active_conversation == "general"

    asyncio.run(exercise())


def test_navigation_drag_out_does_not_swallow_next_keyboard_enter(
    tmp_path: Path,
) -> None:
    from taut_tui.app import TautApp
    from taut_tui.widgets import TautOptionList

    db_path = tmp_path / "pointer-drag-out.db"
    TautClient.init(db_path=db_path)
    setup = TautClient(db_path=db_path, as_name="alice")
    setup.join("general")
    setup.close()

    async def exercise() -> None:
        app = TautApp(db_path=str(db_path), as_name="alice", continuity_token=None)
        async with app.run_test(size=(100, 34)) as pilot:
            navigation = app.query_one("#navigation-list", TautOptionList)
            await _pause_until(
                pilot,
                lambda: app._navigation_targets[:1] == ["general"],
            )
            navigation.highlighted = 0
            navigation.focus()
            await _pause_until(pilot, lambda: navigation.has_focus)

            assert await pilot.mouse_down("#navigation-list", offset=(1, 0)) is True
            assert await pilot.mouse_up("#transcript", offset=(1, 0)) is True
            await _pause_until(pilot, lambda: not navigation._pointer_pending)
            await pilot.press("enter")
            await _pause_until(
                pilot,
                lambda: app.visual_state.active_conversation == "general",
            )

            assert app.visual_state.active_conversation == "general"

    asyncio.run(exercise())


def test_direct_message_header_and_composer_use_actor_scoped_label(
    tmp_path: Path,
) -> None:
    from taut_tui.app import TautApp
    from taut_tui.widgets import TautOptionList

    db_path = tmp_path / "dm.db"
    TautClient.init(db_path=db_path)
    alice = TautClient(db_path=db_path, as_name="alice")
    bob = TautClient(db_path=db_path, as_name="bob")
    alice.join("general")
    bob.join("general")
    alice.say("@bob", "hello")

    async def exercise() -> None:
        app = TautApp(db_path=str(db_path), as_name="alice", continuity_token=None)
        async with app.run_test(size=(100, 34)) as pilot:
            navigation = app.query_one("#navigation-list", TautOptionList)
            await _pause_until(
                pilot,
                lambda: any(
                    isinstance(target, str) and target != "general"
                    for target in app._navigation_targets
                ),
            )
            dm_index = next(
                index
                for index, target in enumerate(app._navigation_targets)
                if isinstance(target, str) and target != "general"
            )
            navigation.highlighted = dm_index
            navigation.focus()
            await pilot.press("enter")
            for _ in range(100):
                await pilot.pause(0.01)
                if app.visual_state.active_conversation is not None:
                    break
            assert "DM with bob" in str(app.query_one("#target-header").render())
            assert (
                app.query_one("#composer", Input).placeholder == "Message DM with bob"
            )

    try:
        asyncio.run(exercise())
    finally:
        alice.close()
        bob.close()


def test_help_and_errors_open_a_visible_inspector_at_medium_and_compact_sizes(
    tmp_path: Path,
) -> None:
    from taut_tui.app import TautApp

    async def exercise() -> None:
        db_path = tmp_path / "help.db"
        TautClient.init(db_path=db_path)
        app = TautApp(db_path=str(db_path), as_name=None, continuity_token=None)
        async with app.run_test(size=(100, 34)) as pilot:
            await pilot.press("f1")
            assert app.query_one("#inspector").display is True
            help_text = str(app.query_one("#inspector-body").render())
            for expected in (
                "gg / Home",
                "G / End",
                "Ctrl-U / PageUp",
                "Ctrl-D / PageDown",
                "Tab / Shift-Tab",
                "g i",
                "Pane",
                "Replies",
            ):
                assert expected in help_text

            await pilot.resize_terminal(64, 34)
            app._show_error("visible failure")
            await pilot.pause()
            assert app.query_one("#inspector").display is True
            assert "visible failure" in str(app.query_one("#inspector-body").render())

    asyncio.run(exercise())


def test_system_findings_and_failures_render_without_escaping_the_app() -> None:
    from taut.client import DoctorCheck, DoctorReport, DumpReport
    from taut_tui.app import TautApp

    async def exercise() -> None:
        app = TautApp(db_path=None, as_name=None, continuity_token=None)
        async with app.run_test(size=(100, 34)):
            findings: Future[DoctorReport] = Future()
            findings.set_result(
                DoctorReport(
                    db="chat.db",
                    healthy=False,
                    checks=(DoctorCheck("broker", "fail", "not reachable", {}),),
                )
            )
            app._apply_action_result(findings, refresh_navigation=False)
            assert "FAIL  broker: not reachable" in str(
                app.query_one("#inspector-body").render()
            )

            doctor_failure: Future[DoctorReport] = Future()
            doctor_failure.set_exception(RuntimeError("doctor framework failed"))
            app._apply_action_result(doctor_failure, refresh_navigation=False)
            assert "doctor framework failed" in str(
                app.query_one("#inspector-body").render()
            )

            dump_failure: Future[DumpReport] = Future()
            dump_failure.set_exception(PermissionError("dump output not writable"))
            app._apply_action_result(dump_failure, refresh_navigation=False)
            assert "dump output not writable" in str(
                app.query_one("#inspector-body").render()
            )

    asyncio.run(exercise())


def test_compose_send_failure_is_visible_and_preserves_the_draft(
    tmp_path: Path,
) -> None:
    from dataclasses import replace

    from taut.client import Message
    from taut_tui.app import TautApp
    from taut_tui.models import DraftState

    db_path = tmp_path / "send-error.db"
    TautClient.init(db_path=db_path)

    async def exercise() -> None:
        app = TautApp(db_path=str(db_path), as_name=None, continuity_token=None)
        async with app.run_test(size=(64, 34)) as pilot:
            composer = app.query_one("#composer", Input)
            composer.value = "keep me"
            composer.focus()
            app.visual_state = replace(
                app.visual_state,
                active_conversation="general",
                drafts=(DraftState("general", "keep me", 7, 3),),
                mode=InteractionMode.COMPOSE,
            )
            app._pending_sends[1] = ("general", 3)
            failed: Future[Message] = Future()
            failed.set_exception(RuntimeError("send failed visibly"))

            app._apply_send_result(1, failed)
            await pilot.pause()

            assert app.query_one("#conversation").display is True
            assert "send failed visibly" in str(app.query_one("#status-line").render())
            assert app.query_one("#composer", Input).has_focus
            assert app.visual_state.draft_for("general") is not None
            assert app.visual_state.draft_for("general").text == "keep me"  # type: ignore[union-attr]

    asyncio.run(exercise())


def test_retired_summon_readiness_cannot_resurrect_visual_state() -> None:
    from taut_tui.app import TautApp
    from taut_tui.summon import OwnedSummonRun

    async def exercise() -> None:
        app = TautApp(db_path=None, as_name=None, continuity_token=None)
        async with app.run_test(size=(100, 34)):
            app._render_inspector("newer state")
            retired = OwnedSummonRun(
                token="retired-token",
                pending=False,
                member_id="member-1",
                member_name="Retired",
            )

            app._apply_summon_ready(retired)

            assert app._operation_state == "idle"
            rendered = str(app.query_one("#inspector-body").render())
            assert "newer state" in rendered
            assert "Retired" not in rendered

    asyncio.run(exercise())


def test_live_reply_notification_refreshes_the_contextual_reply_marker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from taut_tui.app import TautApp
    from taut_tui.widgets import TautOptionList

    db_path = tmp_path / "live-reply-marker.db"
    TautClient.init(db_path=db_path)
    alice = TautClient(db_path=db_path, as_name="alice")
    bob = TautClient(db_path=db_path, as_name="bob")
    alice.join("general")
    bob.join("general")
    root = alice.say("general", "root awaiting a reply")

    async def exercise() -> None:
        app = TautApp(db_path=str(db_path), as_name="alice", continuity_token=None)
        async with app.run_test(size=(100, 34)) as pilot:
            navigation = app.query_one("#navigation-list", TautOptionList)
            await _pause_until(
                pilot,
                lambda: app._navigation_targets[:1] == ["general"],
            )
            navigation.highlighted = 0
            navigation.focus()
            await pilot.press("enter")
            await _pause_until(
                pilot,
                lambda: any(message.ts == root.ts for message in app._message_rows),
            )

            reply_navigation_applied = asyncio.Event()
            apply_navigation_result = app._apply_navigation_result

            def observe_navigation_result(future: Future[Any]) -> None:
                apply_navigation_result(future)
                if ("general", root.ts) in app._reply_threads:
                    reply_navigation_applied.set()

            monkeypatch.setattr(
                app,
                "_apply_navigation_result",
                observe_navigation_result,
            )

            bob.reply("general", str(root.ts), "a live contextual reply")
            await asyncio.wait_for(reply_navigation_applied.wait(), timeout=5)
            transcript = app.query_one("#transcript", TautOptionList)
            root_index = next(
                index
                for index, message in enumerate(app._message_rows)
                if message.ts == root.ts
            )
            assert "replies" in str(transcript.get_option_at_index(root_index).prompt)

    try:
        asyncio.run(exercise())
    finally:
        alice.close()
        bob.close()


def test_notification_delivery_preserves_non_notification_inspector_content() -> None:
    from taut.client import Notification
    from taut_tui.app import TautApp
    from taut_tui.models import InspectorKind

    notification = Notification(
        type="mention",
        to_id=None,
        actor_id=None,
        actor_name="bob",
        thread="general",
        message_ts=1,
    )

    async def exercise() -> None:
        app = TautApp(db_path=None, as_name=None, continuity_token=None)
        async with app.run_test(size=(100, 34)):
            for kind, content in (
                (InspectorKind.MESSAGE, "selected message details"),
                (InspectorKind.SYSTEM, "help content"),
                (InspectorKind.SUMMON, "summon status content"),
            ):
                app._render_inspector(content, kind=kind)
                assert app._apply_delivery(0, notification) is True
                assert content in str(app.query_one("#inspector-body").render())
                assert app.visual_state.inspector is not None
                assert app.visual_state.inspector.kind is kind

    asyncio.run(exercise())


def test_deletion_refresh_preserves_open_reply_surface(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from dataclasses import replace

    from taut_tui.app import TautApp
    from taut_tui.session import ConversationSnapshot

    db_path = tmp_path / "delete-reply.db"
    TautClient.init(db_path=db_path)
    pending: Future[object] = Future()
    opened: list[tuple[str, str | None, int | None]] = []

    async def exercise() -> None:
        app = TautApp(db_path=str(db_path), as_name=None, continuity_token=None)
        async with app.run_test(size=(100, 34)):
            assert app._session is not None

            def open_conversation(
                target: str,
                *,
                reply_thread: str | None = None,
                intent_token: int | None = None,
            ) -> Future[object]:
                opened.append((target, reply_thread, intent_token))
                return pending

            monkeypatch.setattr(app._session, "open_conversation", open_conversation)
            app._conversation_intent = 4
            app.visual_state = replace(
                app.visual_state,
                active_conversation="general",
                open_reply_thread="general.123",
            )

            app._refresh_after_deletion(target="general", intent=4)

            assert opened == [("general", "general.123", 4)]
            app.visual_state = replace(app.visual_state, selected_message_id=123)
            app._apply_conversation(
                ConversationSnapshot(
                    generation=2,
                    target="general",
                    messages=(),
                    reply_thread="general.123",
                    intent_token=4,
                )
            )
            assert app.visual_state.selected_message_id is None
            assert app.visual_state.open_reply_thread == "general.123"

    asyncio.run(exercise())


def test_superseding_navigation_clears_and_rejects_stale_search(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from taut.client import Message
    from taut_tui.actions import ActionId, ActionRoute
    from taut_tui.app import TautApp
    from taut_tui.widgets import TautOptionList

    db_path = tmp_path / "superseded-search.db"
    TautClient.init(db_path=db_path)
    alice = TautClient(db_path=db_path, as_name="alice")
    alice.join("general")
    alice.join("random")
    alice.say("general", "needle from the old search")
    hit = alice.search("needle")[0]
    context: list[Message] = alice.history_around("general", str(hit.ts))
    pending: Future[list[Message]] = Future()

    async def exercise() -> None:
        app = TautApp(db_path=str(db_path), as_name="alice", continuity_token=None)
        async with app.run_test(size=(100, 34)) as pilot:
            assert app._domain is not None
            monkeypatch.setattr(
                app._domain,
                "open_search_result",
                lambda _hit: pending,
            )
            app._selected_search_hit = hit
            app._dispatch_tui_action(
                ActionId.SEARCH_OPEN_RESULT,
                source=ActionRoute.CONTEXT,
            )
            await pilot.pause()
            assert app._operation_state == "searching"

            navigation = app.query_one("#navigation-list", TautOptionList)
            await _pause_until(
                pilot,
                lambda: _has_option_containing(navigation, "#random"),
            )
            navigation.highlighted = _option_index_containing(navigation, "#random")
            navigation.focus()
            await pilot.press("enter")
            await _pause_until(
                pilot,
                lambda: app.visual_state.active_conversation == "random",
            )
            assert app._operation_state == "idle"
            assert "searching" not in str(app.query_one("#status-line").render())

            pending.set_result(context)
            await pilot.pause()
            assert app.visual_state.active_conversation == "random"
            assert app._operation_state == "idle"

    try:
        asyncio.run(exercise())
    finally:
        alice.close()


def test_current_watcher_degradation_is_visible_in_the_status_line() -> None:
    from dataclasses import replace

    from taut_tui.app import TautApp

    async def exercise() -> None:
        app = TautApp(db_path=None, as_name=None, continuity_token=None)
        async with app.run_test(size=(100, 34)):
            app.visual_state = replace(app.visual_state, model_generation=7)

            app._apply_watcher_degraded(7, "delivery was rejected")

            status = str(app.query_one("#status-line").render())
            assert "live updates stopped" in status
            assert "delivery was rejected" in status

    asyncio.run(exercise())


def test_unmount_contains_session_cleanup_failure_without_skipping_system_close() -> (
    None
):
    from taut_tui.app import TautApp

    class FailingSession:
        def close(self) -> None:
            raise RuntimeError("watcher remained live")

    class SystemProbe:
        def __init__(self) -> None:
            self.closed = False

        def close(self) -> None:
            self.closed = True

    async def exercise() -> None:
        app = TautApp(db_path=None, as_name=None, continuity_token=None)
        system = SystemProbe()
        async with app.run_test(size=(100, 34)):
            assert app._session is not None
            app._session.close()
            app._session = FailingSession()  # type: ignore[assignment]
            assert app._system is not None
            app._system.close()
            app._system = system  # type: ignore[assignment]

        assert system.closed is True
        assert app._operation_state == "cleanup failed: watcher remained live"

    asyncio.run(exercise())


def test_summon_worker_base_exception_and_presentation_failure_stay_visible_or_contained(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from taut_tui.app import TautApp
    from taut_tui.summon import OwnedSummonRun

    async def exercise() -> None:
        app = TautApp(db_path=None, as_name=None, continuity_token=None)
        async with app.run_test(size=(100, 34)):
            app._owned_summon_tokens.add("failed-token")
            failed: Future[None] = Future()
            failed.set_exception(KeyboardInterrupt("worker interrupted"))
            app._apply_summon_return("failed-token", failed)
            assert "worker interrupted" in str(
                app.query_one("#inspector-body").render()
            )

            app._owned_summon_tokens.add("live-token")
            ready = OwnedSummonRun(
                token="live-token",
                pending=False,
                member_id="member-2",
                member_name="Live",
            )

            def broken_projection(*_args: object, **_kwargs: object) -> None:
                raise ValueError("presentation only")

            monkeypatch.setattr(app, "_render_inspector", broken_projection)
            app._apply_summon_ready(ready)
            app._apply_summon_log("diagnostic")

    asyncio.run(exercise())


def test_compact_mouse_pane_affordance_reaches_each_logical_surface(
    tmp_path: Path,
) -> None:
    from taut_tui.app import TautApp
    from taut_tui.models import InspectorKind

    async def exercise() -> None:
        db_path = tmp_path / "panes.db"
        TautClient.init(db_path=db_path)
        app = TautApp(db_path=str(db_path), as_name=None, continuity_token=None)
        async with app.run_test(size=(64, 34)) as pilot:
            app._render_inspector("context", kind=InspectorKind.SYSTEM)
            await pilot.pause()
            seen: set[str] = set()
            for _ in range(4):
                for widget_id in ("navigation", "conversation", "inspector"):
                    if app.query_one(f"#{widget_id}").display:
                        seen.add(widget_id)
                assert await pilot.click("#pane-affordance") is True
                await pilot.pause()
            assert seen == {"navigation", "conversation", "inspector"}

    asyncio.run(exercise())


def test_real_app_opens_active_conversation_and_sends_through_public_client(
    tmp_path: Path,
) -> None:
    from textual.widgets import OptionList

    from taut_tui.app import TautApp

    db_path = tmp_path / "chat.db"
    TautClient.init(db_path=db_path)
    alice = TautClient(db_path=db_path, as_name="alice")
    bob = TautClient(db_path=db_path, as_name="bob")
    for client in (alice, bob):
        client.join("general")

    async def exercise() -> None:
        app = TautApp(db_path=str(db_path), as_name="alice", continuity_token=None)
        async with app.run_test(size=(100, 34)) as pilot:
            navigation = app.query_one("#navigation-list", OptionList)
            for _ in range(100):
                await pilot.pause(0.01)
                if navigation.option_count and "#general" in str(
                    navigation.get_option_at_index(0).prompt
                ):
                    break
            else:
                pytest.fail("navigation did not load")

            navigation.highlighted = 0
            navigation.focus()
            await pilot.press("enter")
            for _ in range(100):
                await pilot.pause(0.01)
                if app.visual_state.active_conversation == "general":
                    break
            else:
                pytest.fail("conversation did not open")

            await pilot.press("i")
            await pilot.press(*"hello from tui")
            await pilot.press("enter")
            for _ in range(100):
                await pilot.pause(0.01)
                if app.query_one("#composer", Input).value == "":
                    break
            else:
                pytest.fail("send did not complete")

    try:
        asyncio.run(exercise())
        assert any(message.text == "hello from tui" for message in bob.log("general"))
    finally:
        alice.close()
        bob.close()


def test_command_palette_opens_native_form_and_applies_public_identity_change(
    tmp_path: Path,
) -> None:
    from taut_tui.app import TautApp

    db_path = tmp_path / "identity.db"
    TautClient.init(db_path=db_path)
    alice = TautClient(db_path=db_path, as_name="alice")
    alice.join("general")

    async def exercise() -> None:
        app = TautApp(db_path=str(db_path), as_name="alice", continuity_token=None)
        async with app.run_test(size=(100, 34)) as pilot:
            await pilot.press("ctrl+p")
            assert app.visual_state.mode is InteractionMode.COMMAND
            await pilot.press(*"set persona", "enter")
            for _ in range(100):
                await pilot.pause(0.01)
                if list(app.screen.query("#field-persona")):
                    break
            else:
                pytest.fail("persona form did not open")
            field = app.screen.query_one("#field-persona", Input)
            field.value = "reviewer"
            app.screen.query_one("#form-submit", Button).press()
            for _ in range(100):
                await pilot.pause(0.01)
                if alice.whoami().persona == "reviewer":
                    break
            else:
                pytest.fail("persona action did not complete")

    try:
        asyncio.run(exercise())
    finally:
        alice.close()


def test_native_form_keeps_values_and_renders_domain_error_inline(
    tmp_path: Path,
) -> None:
    from taut_tui.actions import ActionId, ActionRoute
    from taut_tui.app import TautApp

    db_path = tmp_path / "inline-error.db"
    TautClient.init(db_path=db_path)
    alice = TautClient(db_path=db_path, as_name="alice")
    alice.join("general")

    async def exercise() -> None:
        app = TautApp(db_path=str(db_path), as_name="alice", continuity_token=None)
        async with app.run_test(size=(100, 34)) as pilot:
            app._dispatch_tui_action(
                ActionId.IDENTITY_SET_NAME,
                source=ActionRoute.PALETTE,
            )
            await pilot.pause()
            field = app.screen.query_one("#field-name", Input)
            field.value = "bad name"
            app.screen.query_one("#form-submit", Button).press()
            for _ in range(100):
                await pilot.pause(0.01)
                error = str(app.screen.query_one("#form-errors").render())
                if error and error != "Working…":
                    break
            assert app.screen.query_one("#field-name", Input).value == "bad name"
            assert app.screen.query_one("#form-submit", Button).disabled is False
            assert "name" in str(app.screen.query_one("#form-errors").render()).lower()

    try:
        asyncio.run(exercise())
    finally:
        alice.close()


def test_stale_search_failure_cannot_replace_newer_ui_state(tmp_path: Path) -> None:
    from taut.client import Message
    from taut_tui.app import TautApp
    from taut_tui.session import ConversationSnapshot

    db_path = tmp_path / "stale-search.db"
    TautClient.init(db_path=db_path)

    async def exercise() -> None:
        app = TautApp(db_path=str(db_path), as_name=None, continuity_token=None)
        async with app.run_test(size=(100, 34)):
            app._render_inspector("newer state")
            app._conversation_intent = 2
            failed: Future[list[Message]] = Future()
            failed.set_exception(RuntimeError("stale search failure"))

            app._apply_search_context(1, failed)

            rendered = str(app.query_one("#inspector-body").render())
            assert "newer state" in rendered
            assert "stale search failure" not in rendered
            stale = ConversationSnapshot(
                generation=1,
                target="stale-target",
                messages=(),
                intent_token=1,
            )
            assert app._commit_conversation_from_worker(stale) is False
            completed: Future[ConversationSnapshot | None] = Future()
            completed.set_result(stale)
            app._apply_optional_conversation(1, completed)
            assert app.visual_state.active_conversation != "stale-target"

    asyncio.run(exercise())


def test_open_search_result_anchors_exact_hit_without_advancing_cursor(
    tmp_path: Path,
) -> None:
    from taut_tui.app import TautApp
    from taut_tui.widgets import TautOptionList

    db_path = tmp_path / "search-anchor.db"
    TautClient.init(db_path=db_path)
    alice = TautClient(db_path=db_path, as_name="alice")
    alice.join("general")
    for index in range(12):
        text = "exact anchor needle" if index == 6 else f"ordinary message {index}"
        alice.say("general", text)
    hit = alice.search("exact anchor needle")[0]

    async def exercise() -> None:
        app = TautApp(db_path=str(db_path), as_name="alice", continuity_token=None)
        async with app.run_test(size=(100, 24)) as pilot:
            app._selected_search_hit = hit
            app._open_selected_search_result()
            await _pause_until(
                pilot,
                lambda: (
                    app.visual_state.active_conversation == "general"
                    and any(message.ts == hit.ts for message in app._message_rows)
                ),
            )
            assert app.visual_state.scroll_anchor.message_id == hit.ts
            transcript = app.query_one("#transcript", TautOptionList)
            assert app._message_rows[transcript.highlighted or 0].ts == hit.ts

    try:
        asyncio.run(exercise())
    finally:
        alice.close()


def test_delete_refresh_cannot_supersede_newer_navigation_intent(
    tmp_path: Path,
) -> None:
    from dataclasses import replace

    from taut_tui.app import TautApp

    db_path = tmp_path / "stale-delete.db"
    TautClient.init(db_path=db_path)

    class RecordingSession:
        def __init__(self) -> None:
            self.targets: list[str] = []

        def open_conversation(self, target: str, **_kwargs: object) -> Future[None]:
            self.targets.append(target)
            future: Future[None] = Future()
            future.set_result(None)
            return future

    async def exercise() -> None:
        app = TautApp(db_path=str(db_path), as_name=None, continuity_token=None)
        async with app.run_test(size=(100, 34)):
            real_session = app._session
            recording = RecordingSession()
            app._session = recording  # type: ignore[assignment]
            app.visual_state = replace(
                app.visual_state,
                active_conversation="general",
            )
            app._conversation_intent = 2
            app._refresh_after_deletion(target="general", intent=1)
            assert recording.targets == []
            app._session = real_session

    asyncio.run(exercise())


def test_overlapping_send_completion_only_clears_its_own_draft(
    tmp_path: Path,
) -> None:
    from taut.client import Message
    from taut_tui.app import TautApp
    from taut_tui.widgets import TautOptionList

    db_path = tmp_path / "overlapping-sends.db"
    TautClient.init(db_path=db_path)
    alice = TautClient(db_path=db_path, as_name="alice")
    alice.join("general")
    sends: list[Future[Message]] = []

    class DeferredDomain:
        def send_message(self, _target: str, _text: str) -> Future[Message]:
            future: Future[Message] = Future()
            sends.append(future)
            return future

    async def exercise() -> None:
        app = TautApp(db_path=str(db_path), as_name="alice", continuity_token=None)
        async with app.run_test(size=(100, 34)) as pilot:
            navigation = app.query_one("#navigation-list", TautOptionList)
            await _pause_until(
                pilot,
                lambda: _has_option_containing(navigation, "#general"),
            )
            navigation.highlighted = _option_index_containing(navigation, "#general")
            navigation.focus()
            await pilot.press("enter")
            await _pause_until(
                pilot,
                lambda: app.visual_state.active_conversation == "general",
            )

            app._domain = DeferredDomain()  # type: ignore[assignment]
            composer = app.query_one("#composer", Input)
            composer.value = "first"
            await pilot.pause()
            app._submit_composer("first")
            composer.value = "second"
            await pilot.pause()
            app._submit_composer("second")

            first = alice.say("general", "first")
            sends[0].set_result(first)
            await pilot.pause()
            assert composer.value == "second"

            second = alice.say("general", "second")
            sends[1].set_result(second)
            for _ in range(100):
                await pilot.pause(0.01)
                if composer.value == "":
                    break
            assert composer.value == ""

    try:
        asyncio.run(exercise())
    finally:
        alice.close()


def test_reply_markers_and_close_restore_conversation_focus(tmp_path: Path) -> None:
    from taut_tui.app import TautApp
    from taut_tui.models import LogicalSurface
    from taut_tui.widgets import TautOptionList

    db_path = tmp_path / "reply-surface.db"
    TautClient.init(db_path=db_path)
    alice = TautClient(db_path=db_path, as_name="alice")
    bob = TautClient(db_path=db_path, as_name="bob")
    for client in (alice, bob):
        client.join("general")
    origin = alice.say("general", "root message")
    bob.reply("general", str(origin.ts), "first reply")

    async def exercise() -> None:
        app = TautApp(db_path=str(db_path), as_name="alice", continuity_token=None)
        async with app.run_test(size=(100, 34)) as pilot:
            navigation = app.query_one("#navigation-list", TautOptionList)
            await _pause_until(
                pilot,
                lambda: bool(navigation.option_count and app._reply_threads),
            )
            navigation.highlighted = 0
            navigation.focus()
            await pilot.press("enter")
            await _pause_until(
                pilot,
                lambda: app.visual_state.active_conversation == "general",
            )

            transcript = app.query_one("#transcript", TautOptionList)
            origin_index = next(
                index
                for index in range(transcript.option_count)
                if "root message" in str(transcript.get_option_at_index(index).prompt)
            )
            prompt = str(transcript.get_option_at_index(origin_index).prompt)
            assert "replies" in prompt.lower()
            transcript.highlighted = origin_index
            transcript.focus()
            await pilot.press("enter")
            await _pause_until(
                pilot,
                lambda: app.visual_state.open_reply_thread is not None,
            )
            assert app.visual_state.open_reply_thread is not None

            assert await pilot.click("#reply-affordance") is True
            await _pause_until(
                pilot,
                lambda: app.visual_state.open_reply_thread is None,
            )
            assert app.visual_state.focus.surface is LogicalSurface.CONVERSATION
            assert app.visual_state.pane_choice is LogicalSurface.CONVERSATION
            assert transcript.has_focus

    try:
        asyncio.run(exercise())
    finally:
        alice.close()
        bob.close()


def test_terminal_controls_are_escaped_at_every_app_text_projection(
    tmp_path: Path,
) -> None:
    from taut.client import Channel, Message, Notification
    from taut_tui.app import TautApp
    from taut_tui.session import ConversationSnapshot
    from taut_tui.widgets import TautOptionList

    payload = "PAY\x1b]8;;https://evil.invalid\x07LOAD"
    db_path = tmp_path / "control-payload.db"
    TautClient.init(db_path=db_path)

    def assert_safe(rendered: object) -> None:
        text = str(rendered)
        assert "\x1b" not in text
        assert "\x07" not in text
        assert r"\x1b" in text
        assert r"\a" in text

    async def exercise() -> None:
        app = TautApp(db_path=str(db_path), as_name=None, continuity_token=None)
        async with app.run_test(size=(100, 34)):
            message = Message(
                thread="general",
                ts=1,
                from_id=None,
                from_name=payload,
                kind="message",
                text=payload,
            )
            app._target_labels["general"] = payload
            app._apply_conversation(
                ConversationSnapshot(
                    generation=1,
                    target="general",
                    messages=(message,),
                    intent_token=app._conversation_intent,
                )
            )
            assert_safe(app.query_one("#target-header").render())
            assert_safe(app.query_one("#composer", Input).placeholder)
            transcript = app.query_one("#transcript", TautOptionList)
            assert_safe(transcript.get_option_at_index(0).prompt)

            app._select_message(0)
            assert_safe(app.query_one("#inspector-body").render())
            app._set_navigation_actions(("general",), (payload,))
            navigation = app.query_one("#navigation-list", TautOptionList)
            assert_safe(navigation.get_option_at_index(0).prompt)

            app._render_notifications(
                (
                    Notification(
                        type="mention",
                        to_id=None,
                        actor_id=None,
                        actor_name=payload,
                        thread=payload,
                        message_ts=1,
                    ),
                )
            )
            assert_safe(app.query_one("#inspector-body").render())
            app._render_domain_result(
                Channel(
                    name=payload,
                    topic=payload,
                    topic_updated_ts=None,
                    topic_updated_by_id=None,
                    topic_updated_by_name=None,
                )
            )
            assert_safe(app.query_one("#inspector-body").render())
            app._show_error(payload)
            assert_safe(app.query_one("#inspector-body").render())
            app._update_status()
            assert_safe(app.query_one("#status-line").render())

    asyncio.run(exercise())
