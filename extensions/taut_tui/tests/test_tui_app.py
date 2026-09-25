"""Real TUI extension behavior over the pure action and layout models.

Spec references:
- docs/specs/10-taut-tui.md [TUI-4.3], [TUI-5], [TUI-8], [TUI-9]
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable
from concurrent.futures import Future
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import pytest
from _app_completion import AppCompletions, observed
from _completion import Completion, CompletionKey
from textual.widgets import Button, Input, Select

from taut.client import TautClient
from taut_tui.models import InteractionMode, LayoutMode
from taut_tui.widgets import TautComposer

pytestmark = pytest.mark.sqlite_only


@pytest.fixture(autouse=True)
def _app_completion_observers(monkeypatch: pytest.MonkeyPatch) -> Any:
    from taut_tui.app import TautApp

    original_init = TautApp.__init__
    observers: list[AppCompletions] = []

    def initialize(app: Any, *args: Any, **kwargs: Any) -> None:
        original_init(app, *args, **kwargs)
        observer = AppCompletions(app, monkeypatch)
        app._test_completions = observer
        observers.append(observer)

    monkeypatch.setattr(TautApp, "__init__", initialize)
    yield
    for observer in observers:
        observer.close()


async def _perform_viewport_user_input(
    user_input: str,
    pilot: Any,
    transcript: Any,
) -> None:
    from textual import events

    if user_input == "wheel":
        await pilot._post_mouse_events([events.MouseScrollDown], "#transcript")
    elif user_input == "scrollbar":
        assert (
            await pilot.click(
                transcript.vertical_scrollbar,
                offset=(0, 10),
            )
            is True
        )
    elif user_input == "conventional-key":
        transcript.focus()
        await pilot.press("pagedown")
    elif user_input == "vi-key":
        transcript.focus()
        await pilot.press("shift+g")
    else:
        assert await pilot.click("#transcript", offset=(2, 2)) is True


async def _activate_transcript_message(app: Any, transcript: Any, index: int) -> None:
    """Use the real widget queue, so older highlight events precede selection."""
    applied = observed(app).option_activation(transcript)
    deadline = observed(app).scope.now() + 5
    transcript.highlighted = index
    transcript.action_select()
    await applied.wait(deadline=deadline, description="transcript activation applied")


class _ResizeAfterTranscriptActivation:
    """Retain one real resize until user input is already in the widget queue."""

    def __init__(self, app: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        self.app = app
        self.monkeypatch = monkeypatch
        self.original_resize = app._render_latest_resize
        self.pending: list[int] = []
        self.receipts: dict[int, tuple[Any, Completion[Any]]] = {}
        self.rendered = observed(app).scope.expect(
            CompletionKey(app, "held_resize.returned", request=self)
        )
        self.released = False
        monkeypatch.setattr(app, "_render_latest_resize", self.pending.append)

    def arm(self, transcript: Any) -> None:
        from taut_tui.widgets import TautOptionList

        assert self.pending and self.pending[-1] == self.app._resize_generation
        original_post = transcript.post_message
        self.original_dispatch = self.app._on_message

        def post(event: Any) -> bool:
            receipt = None
            if isinstance(
                event, (TautOptionList.OptionHighlighted, TautOptionList.Activated)
            ):
                receipt = observed(self.app).scope.expect(
                    CompletionKey(self.app, "selection_message.applied", request=event)
                )
            admitted = bool(original_post(event))
            if receipt is not None:
                if admitted:
                    self.receipts[id(event)] = (event, receipt)
                else:
                    receipt.dispose()
            if admitted and isinstance(event, TautOptionList.Activated):
                self._release()
            return admitted

        self.monkeypatch.setattr(transcript, "post_message", post)
        self.monkeypatch.setattr(self.app, "_on_message", self._dispatch)

    async def _dispatch(self, event: Any) -> None:
        retained = self.receipts.get(id(event))
        receipt = retained[1] if retained is not None else None
        try:
            await self.original_dispatch(event)
        except BaseException as error:
            if receipt is not None:
                receipt.fail(receipt.key, error)
            raise
        else:
            if receipt is not None:
                receipt.succeed(receipt.key, event)

    def _release(self) -> None:
        if not self.released:
            self.released = True
            # Activated still has to bubble through the widget's ancestors.
            # The actual resize callback can therefore run first on the app.
            assert self.app.call_later(self._render) is True

    def _render(self) -> None:
        try:
            self.original_resize(self.pending[-1])
        except BaseException as error:
            self.rendered.fail(self.rendered.key, error)
            raise
        else:
            self.rendered.succeed(self.rendered.key, None)

    async def settled(self, *, deadline: float) -> None:
        await self.rendered.wait(deadline=deadline, description="held resize returned")
        # Input production and the synchronous render have both returned. Wait
        # only for their admitted messages, not an assumed render highlight.
        # Each receipt is published after the original app handler completes.
        for _event, receipt in tuple(self.receipts.values()):
            await receipt.wait(
                deadline=deadline, description="selection handler applied"
            )
        fence = observed(self.app).scope.expect(
            CompletionKey(self.app, "selection_queue.fenced", request=self)
        )
        assert self.app.call_later(fence.succeed, fence.key, None) is True
        await fence.wait(deadline=deadline, description="selection app queue fenced")


async def _await_summon_confirmation(
    app: Any,
    started_futures: asyncio.Queue[Future[None]],
    confirmation_requests: asyncio.Queue[object],
    confirmation_type: type[Any],
) -> Future[None]:
    future = await asyncio.wait_for(started_futures.get(), timeout=5.0)
    worker_done = asyncio.Event()
    loop = asyncio.get_running_loop()
    future.add_done_callback(lambda _done: loop.call_soon_threadsafe(worker_done.set))
    confirmation_task = asyncio.create_task(confirmation_requests.get())
    worker_task = asyncio.create_task(worker_done.wait())
    done, pending = await asyncio.wait(
        {confirmation_task, worker_task},
        timeout=15.0,
        return_when=asyncio.FIRST_COMPLETED,
    )
    for task in pending:
        task.cancel()
    await asyncio.gather(*pending, return_exceptions=True)
    if not done:
        pytest.fail("foreground produced no confirmation or outcome")
    if worker_task in done and confirmation_task not in done:
        future.result()
        pytest.fail("foreground exited before attach confirmation")
    confirmation_task.result()
    assert isinstance(app.screen, confirmation_type)
    return future


async def _await_cancelled_summon_run(app: Any, future: Future[None]) -> None:
    worker_done = asyncio.Event()
    loop = asyncio.get_running_loop()
    future.add_done_callback(lambda _done: loop.call_soon_threadsafe(worker_done.set))
    await asyncio.wait_for(worker_done.wait(), timeout=15.0)
    future.result()
    assert app._summon is not None
    assert app._summon.owned_runs() == ()


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


def _quit_test_screen(surface: str, app: Any) -> Any:
    from taut_tui.actions import ActionId
    from taut_tui.app import TerminalTooSmallScreen
    from taut_tui.forms import FORM_SPECS
    from taut_tui.screens import (
        ConfirmationScreen,
        NamedActionScreen,
        NativeFormScreen,
        SummonStartScreen,
    )

    factories: dict[str, Callable[[], Any]] = {
        "native-form": lambda: NativeFormScreen(FORM_SPECS[ActionId.CHANNEL_JOIN]),
        "confirmation": lambda: ConfirmationScreen("Keep working?"),
        "summon-start": lambda: SummonStartScreen(()),
        "named-action": lambda: NamedActionScreen(ActionId.SUMMON_STATUS, "Status"),
        "terminal-too-small": TerminalTooSmallScreen,
    }
    return factories[surface]()


def test_real_app_exposes_low_chrome_surfaces_and_mode_status() -> None:
    from taut_tui.app import TautApp

    async def exercise() -> None:
        app = TautApp(db_path=None, as_name="van", continuity_token=None)
        async with app.run_test(size=(130, 34)):
            # run_test returns after the initial screen mount and layout fence.
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
        result_ready = asyncio.Event()

        class WindowScreenProbe(ScreenProbe):
            def complete(self) -> None:
                super().complete()
                result_ready.set()

            def show_domain_error(self, message: str) -> None:
                super().show_domain_error(message)
                result_ready.set()

        app = TautApp(db_path=str(db_path), as_name=None, continuity_token=None)
        async with app.run_test(size=(100, 34)) as _pilot:
            assert app._domain is not None
            screen = WindowScreenProbe()
            assert app._complete_identity_form(
                FormSubmission(
                    ActionId.IDENTITY_REJOIN,
                    {"name_or_alias": "", "continuity_token": created.token or ""},
                ),
                app._domain,
                screen=screen,  # type: ignore[arg-type]
            )
            await asyncio.wait_for(
                result_ready.wait(),
                timeout=20.0,
            )
            if not result_ready.is_set():
                pytest.fail("identity rejoin did not complete before timeout")
            assert result_ready.is_set()
            assert screen.completed
            assert screen.error is None
            identity = app._domain.show_identity().result(timeout=10)
            assert identity.member_id == created.member_id

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
    monkeypatch: pytest.MonkeyPatch,
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
            assert app._domain is not None
            search_futures: list[Future[list[object]]] = []
            real_search = app._domain.search

            def record_search(query: str, *, limit: int = 50) -> Future[list[object]]:
                future = cast(Future[list[object]], real_search(query, limit=limit))
                search_futures.append(future)
                return future

            monkeypatch.setattr(app._domain, "search", record_search)
            deadline = observed(app).scope.now() + 5
            app.action_open_search()
            await observed(app).screens.ready(app.screen, deadline=deadline)
            query = app.screen.query_one("#search-query", Input)
            query.value = "nothing-can-match-this"
            await pilot.press("enter")
            assert len(search_futures) == 1
            await asyncio.wait_for(
                asyncio.wrap_future(search_futures[0]),
                timeout=20.0,
            )
            refreshed = asyncio.Event()
            app.call_after_refresh(refreshed.set)
            await asyncio.wait_for(refreshed.wait(), timeout=5.0)
            errors = app.screen.query_one("#search-errors", Static)

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
            composer = app.query_one("#composer", TautComposer)
            assert composer.has_focus
            await pilot.press("q", "/", ":")
            assert composer.text == "q/:"
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
            await pilot.press("i", *"draft", "ctrl+enter", "ctrl+tab", *"line")
            await pilot.resize_terminal(64, 34)
            assert app.layout_mode is LayoutMode.COMPACT
            assert app.query_one("#navigation").display is False
            assert app.query_one("#conversation").display is True
            composer = app.query_one("#composer", TautComposer)
            assert composer.text == "draft\n\tline"
            assert composer.cursor_position == len(composer.text)

            await pilot.resize_terminal(40, 15)
            assert app.layout_mode is LayoutMode.TOO_SMALL
            assert app.query_one("#resize-hint").display is True

            await pilot.resize_terminal(130, 34)
            assert app.layout_mode is LayoutMode.WIDE
            composer = app.query_one("#composer", TautComposer)
            assert composer.text == "draft\n\tline"
            assert composer.cursor_position == len(composer.text)

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
            deadline = observed(app).scope.now() + 5
            app.push_screen(form)
            await observed(app).screens.ready(form, deadline=deadline)
            field = form.query_one("#field-name", Input)
            field.value = "kept"
            confirmation = ConfirmationScreen("Rename exact target?")
            deadline = observed(app).scope.now() + 5
            app.push_screen(confirmation)
            await observed(app).screens.ready(confirmation, deadline=deadline)
            confirm = confirmation.query_one("#confirmation-confirm", Button)
            deadline = observed(app).scope.now() + 5
            confirm.focus()
            await observed(app).focus(confirm, deadline=deadline)

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
    monkeypatch: pytest.MonkeyPatch,
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
            f"message {index:02d}\n\n\tcontinuation "
            + ("wrap this transcript row " * 8),
        )

    async def exercise() -> None:
        app = TautApp(db_path=str(db_path), as_name="alice", continuity_token=None)
        async with app.run_test(size=(100, 24)) as pilot:
            transcript_rendered = asyncio.Event()
            render_messages = app._render_messages

            def observe_transcript_render(
                messages: tuple[Any, ...],
                *,
                restore_owner_intent: int | None = None,
            ) -> None:
                render_messages(
                    messages,
                    restore_owner_intent=restore_owner_intent,
                )
                if len(messages) >= 30:
                    app.call_after_refresh(transcript_rendered.set)

            monkeypatch.setattr(app, "_render_messages", observe_transcript_render)
            navigation = app.query_one("#navigation-list", TautOptionList)
            await observed(app).navigation()
            assert _has_option_containing(navigation, "#general")
            navigation.highlighted = _option_index_containing(navigation, "#general")
            navigation.focus()
            await pilot.press("enter")
            await asyncio.wait_for(transcript_rendered.wait(), timeout=5)
            transcript = app.query_one("#transcript", TautOptionList)
            scroll_applied = asyncio.Event()
            transcript.scroll_to(
                y=18,
                animate=False,
                force=True,
                on_complete=scroll_applied.set,
            )
            await asyncio.wait_for(scroll_applied.wait(), timeout=5)
            assert int(transcript.scroll_offset.y) == 18
            assert transcript.is_vertical_scroll_end is False
            app._capture_settled_transcript_viewport()
            before = app.visual_state.viewport
            assert before.tail_pinned is False
            assert before.message_id is not None

            deadline = observed(app).scope.now() + 5
            await pilot.resize_terminal(64, 24)
            await observed(app).resize_render(deadline=deadline)
            assert app.visual_state.viewport == before
            pane_rows: list[Any] = []
            cycle_surface = app._cycle_surface

            def observe_pane_cycle() -> None:
                assert not pane_rows, "unexpected extra pane cycle"
                # Subscribe at this named producer, not to an earlier resize's
                # retained measurement or viewport completion.
                pane_rows.append(observed(app).rows_measured(transcript))
                cycle_surface()

            monkeypatch.setattr(app, "_cycle_surface", observe_pane_cycle)
            pressed = observed(app).button_press(
                app.query_one("#pane-affordance", Button)
            )
            deadline = observed(app).scope.now() + 5
            assert await pilot.click("#pane-affordance") is True
            await pressed.wait(deadline=deadline, description="pane cycle applied")
            assert len(pane_rows) == 1
            await pane_rows[0].wait(deadline=deadline, description="pane rows measured")
            await observed(app).viewport(deadline=deadline)
            app._capture_settled_transcript_viewport()
            after = app.visual_state.viewport
            assert after.message_id == before.message_id
            assert after.offset == before.offset

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
            # This exact restore uses scroll_to(immediate=True), so its return
            # is the applied-scroll boundary; no deferred effect is outstanding.
            app._capture_settled_transcript_viewport()
            compact_anchor = app.visual_state.viewport
            assert compact_anchor.message_id == after.message_id

            restored = asyncio.Event()
            restore_anchor = app._restore_transcript_anchor

            def observe_target_restore(
                messages: tuple[Any, ...],
                anchor_index: int,
                intra_row_offset: int,
            ) -> int:
                result = restore_anchor(messages, anchor_index, intra_row_offset)
                if (
                    messages[anchor_index].ts == compact_anchor.message_id
                    and transcript.scrollable_content_region.width > compact_width
                ):
                    app.call_after_refresh(restored.set)
                return result

            with monkeypatch.context() as patch:
                patch.setattr(
                    app,
                    "_restore_transcript_anchor",
                    observe_target_restore,
                )
                await pilot.resize_terminal(100, 24)
                await asyncio.wait_for(restored.wait(), timeout=5)
            app._capture_settled_transcript_viewport()
            widened = app.visual_state.viewport
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


def test_known_command_prefix_in_composer_promotes_to_argument_input() -> None:
    from taut_tui.app import TautApp
    from taut_tui.screens import CommandLineScreen

    async def exercise() -> None:
        app = TautApp(db_path=None, as_name=None, continuity_token=None)
        async with app.run_test(size=(100, 34)) as pilot:
            composer = app.query_one("#composer", TautComposer)
            deadline = observed(app).scope.now() + 5
            composer.focus()
            await observed(app).focus(composer, deadline=deadline)
            await pilot.press(*":summon")
            assert composer.text == ":summon"
            assert app.screen is app._base_screen

            await pilot.press("space")

            assert isinstance(app.screen, CommandLineScreen)
            command = app.screen.query_one("#command-line", Input)
            assert command.value == "summon "
            assert command.has_focus
            assert composer.text == ":summon "

            await pilot.press(*"grok")
            assert command.value == "summon grok"

    asyncio.run(exercise())


def test_direct_command_shadow_tab_keeps_argument_input_active() -> None:
    # [TUI-7.1] (2026-08-18): completion is an inline ghost shadow accepted
    # with Tab; there is no clickable completion list.
    from taut_tui.app import TautApp
    from taut_tui.screens import CommandLineScreen

    async def exercise() -> None:
        app = TautApp(db_path=None, as_name=None, continuity_token=None)
        async with app.run_test(size=(100, 34)) as pilot:
            opened = observed(app).command_line()
            await pilot.press(":", *"sum")
            await observed(app).pushed(opened, focus="#command-line")

            assert isinstance(app.screen, CommandLineScreen)
            await pilot.press("tab")
            # Tab's action_accept_shadow updates the field synchronously inside
            # this dispatched key. It does not depend on a suggestion worker.

            command = app.screen.query_one("#command-line", Input)
            assert command.value == "summon "
            assert command.has_focus
            assert command.region.width >= 20

            await pilot.press(*"grok")
            assert command.value == "summon grok"

    asyncio.run(exercise())


def test_direct_command_typing_stays_field_owned_without_a_list() -> None:
    from textual.widgets import OptionList as RawOptionList

    from taut_tui.app import TautApp
    from taut_tui.screens import CommandLineScreen

    async def exercise() -> None:
        app = TautApp(db_path=None, as_name=None, continuity_token=None)
        async with app.run_test(size=(100, 34)) as pilot:
            opened = observed(app).command_line()
            await pilot.press(":", *"summon")
            await observed(app).pushed(opened, focus="#command-line")

            assert isinstance(app.screen, CommandLineScreen)
            command = app.screen.query_one("#command-line", Input)
            assert not app.screen.query(RawOptionList)
            assert app.focused is command
            assert command.value == "summon"

            await pilot.press("space", *"grok")
            assert app.focused is command
            assert command.value == "summon grok"

    asyncio.run(exercise())


@pytest.mark.parametrize("alias", ("q", "quit"))
def test_text_command_quit_alias_uses_guarded_tui_quit(alias: str) -> None:
    from taut_tui.app import TautApp

    async def exercise() -> None:
        app = TautApp(db_path=None, as_name=None, continuity_token=None)
        async with app.run_test(size=(100, 34)) as pilot:
            await pilot.press(":", *alias)
            assert app.is_running
            command = app.screen.query_one("#command-line", Input)
            assert command.value == alias
            assert command.has_focus

            assert app._task is not None
            exited = observed(app).scope.observe_future(
                app._task, owner=app, phase="app.exited"
            )
            deadline = observed(app).scope.now() + 5
            await pilot.press("enter")
            await exited.wait(deadline=deadline, description="guarded quit exited")
            assert not app.is_running

    asyncio.run(exercise())


@pytest.mark.parametrize("alias", ("q", "quit"))
def test_composer_quit_alias_promotes_before_guarded_execution(alias: str) -> None:
    from taut_tui.app import TautApp
    from taut_tui.screens import CommandLineScreen

    async def exercise() -> None:
        app = TautApp(db_path=None, as_name=None, continuity_token=None)
        async with app.run_test(size=(100, 34)) as pilot:
            composer = app.query_one("#composer", TautComposer)
            deadline = observed(app).scope.now() + 5
            composer.focus()
            await observed(app).focus(composer, deadline=deadline)

            await pilot.press(":", *alias, "enter")
            assert app.is_running
            assert isinstance(app.screen, CommandLineScreen)
            command = app.screen.query_one("#command-line", Input)
            assert command.value == alias
            assert command.has_focus

            assert app._task is not None
            exited = observed(app).scope.observe_future(
                app._task, owner=app, phase="app.exited"
            )
            deadline = observed(app).scope.now() + 5
            await pilot.press("enter")
            await exited.wait(deadline=deadline, description="guarded quit exited")
            assert not app.is_running

    asyncio.run(exercise())


def test_text_quit_alias_preserves_guarded_quit_blocker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from _completion import CompletionKey

    from taut_tui.app import TautApp

    class BlockingSystem:
        def quit_block_reason(self) -> str:
            return "A workspace dump is still running."

        def close(self) -> None:
            pass

    async def exercise() -> None:
        app = TautApp(db_path=None, as_name=None, continuity_token=None)
        async with app.run_test(size=(100, 34)) as pilot:
            assert app._system is not None
            app._system.close()
            app._system = BlockingSystem()  # type: ignore[assignment]
            quit_applied = observed(app).scope.expect(
                CompletionKey(app, "guarded_quit.applied", request=object())
            )
            original_quit = app.action_quit_tui

            def quit_tui() -> None:
                original_quit()
                quit_applied.succeed(quit_applied.key, None)

            monkeypatch.setattr(app, "action_quit_tui", quit_tui)

            deadline = observed(app).scope.now() + 5
            await pilot.press(":", *"quit", "enter")
            await quit_applied.wait(deadline=deadline, description="quit guard applied")

            assert app.is_running
            assert (
                "workspace dump is still running"
                in str(app.query_one("#inspector-body").render()).lower()
            )

    asyncio.run(exercise())


@pytest.mark.parametrize("chord", ("ctrl+c", "ctrl+d"))
def test_global_quit_chords_use_guarded_owner_from_compose(
    chord: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from dataclasses import replace

    from _completion import CompletionKey

    from taut_tui.app import TautApp

    class BlockingSystem:
        def quit_block_reason(self) -> str:
            return "A workspace dump is still running."

        def close(self) -> None:
            pass

    async def exercise() -> None:
        app = TautApp(db_path=None, as_name=None, continuity_token=None)
        async with app.run_test(size=(100, 34)) as pilot:
            assert app._system is not None
            app._system.close()
            app._system = BlockingSystem()  # type: ignore[assignment]
            app.visual_state = replace(
                app.visual_state,
                active_conversation="general",
            )
            await pilot.press("i")
            composer = app.query_one("#composer", TautComposer)
            assert composer.has_focus
            quit_applied = observed(app).scope.expect(
                CompletionKey(app, "guarded_quit.applied", request=object())
            )
            original_quit = app.action_quit_tui

            def quit_tui() -> None:
                original_quit()
                quit_applied.succeed(quit_applied.key, None)

            monkeypatch.setattr(app, "action_quit_tui", quit_tui)

            deadline = observed(app).scope.now() + 5
            await pilot.press(chord)
            await quit_applied.wait(deadline=deadline, description="quit guard applied")

            assert app.is_running
            assert composer.has_focus
            assert app.visual_state.mode is InteractionMode.COMPOSE
            assert (
                "workspace dump is still running"
                in str(app.query_one("#inspector-body").render()).lower()
            )

    asyncio.run(exercise())


@pytest.mark.parametrize("chord", ("ctrl+c", "ctrl+d"))
@pytest.mark.parametrize(
    "surface",
    (
        "normal",
        "compose",
        "native-form",
        "confirmation",
        "command-palette",
        "command-line",
        "search",
        "summon-start",
        "named-action",
        "terminal-too-small",
    ),
)
def test_global_quit_chords_exit_from_every_tui_owned_surface(
    chord: str,
    surface: str,
) -> None:
    from taut_tui.app import TautApp

    async def exercise() -> None:
        app = TautApp(db_path=None, as_name=None, continuity_token=None)
        async with app.run_test(size=(100, 34)) as pilot:
            if surface == "compose":
                assert await pilot.click("#composer") is True
                assert app.visual_state.mode is InteractionMode.COMPOSE
            elif surface == "command-palette":
                await pilot.press("ctrl+p")
                assert app.visual_state.mode is InteractionMode.COMMAND
            elif surface == "command-line":
                await pilot.press(":")
                assert app.visual_state.mode is InteractionMode.COMMAND
            elif surface == "search":
                await pilot.press("ctrl+f")
                assert app.visual_state.mode is InteractionMode.SEARCH
            elif surface == "terminal-too-small":
                # A manually pushed shield at 100x34 is immediately retired by
                # the size owner. Exercise the actual shield-producing resize.
                from taut_tui.app import TerminalTooSmallScreen

                deadline = observed(app).scope.now() + 5
                await pilot.resize_terminal(40, 15)
                assert isinstance(app.screen, TerminalTooSmallScreen)
                await observed(app).screens.ready(app.screen, deadline=deadline)
            elif surface != "normal":
                screen = _quit_test_screen(surface, app)
                deadline = observed(app).scope.now() + 5
                app.push_screen(screen)
                await observed(app).screens.ready(screen, deadline=deadline)
            else:
                assert app.visual_state.mode is InteractionMode.NORMAL

            assert app.is_running
            assert app._task is not None
            exited = observed(app).scope.observe_future(
                app._task, owner=app, phase="app.exited"
            )
            deadline = observed(app).scope.now() + 5
            await pilot.press(chord)
            await exited.wait(deadline=deadline, description="guarded quit exited")
            assert not app.is_running

    asyncio.run(exercise())


def test_repeated_global_quit_does_not_stack_owned_run_confirmation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from _completion import CompletionKey

    from taut_tui.actions import ActionId
    from taut_tui.app import TautApp
    from taut_tui.forms import FORM_SPECS
    from taut_tui.screens import ConfirmationScreen, NativeFormScreen

    class OwnedRunSummon:
        def quit_block_reason(self) -> str:
            return "A summoned member is still running."

        def has_pending_owned(self) -> bool:
            return False

        def close(self) -> None:
            pass

    async def exercise() -> None:
        app = TautApp(db_path=None, as_name=None, continuity_token=None)
        async with app.run_test(size=(100, 34)) as pilot:
            if app._summon is not None:
                app._summon.close()
            app._summon = OwnedRunSummon()  # type: ignore[assignment]
            underlying = NativeFormScreen(FORM_SPECS[ActionId.CHANNEL_JOIN])
            deadline = observed(app).scope.now() + 5
            app.push_screen(underlying)
            await observed(app).screens.ready(underlying, deadline=deadline)
            first_quit, repeated_quit = (
                observed(app).scope.expect(
                    CompletionKey(app, "guarded_quit.applied", request=object())
                )
                for _ in range(2)
            )
            attempts = iter((first_quit, repeated_quit))
            original_quit = app.action_quit_tui

            def quit_tui() -> None:
                attempt = next(attempts)
                original_quit()
                attempt.succeed(attempt.key, app.screen)

            monkeypatch.setattr(app, "action_quit_tui", quit_tui)

            deadline = observed(app).scope.now() + 5
            await pilot.press("ctrl+c")
            confirmation = await first_quit.wait(
                deadline=deadline, description="owned quit confirmation requested"
            )
            assert isinstance(confirmation, ConfirmationScreen)
            await observed(app).screens.ready(confirmation, deadline=deadline)
            stack_depth = len(app.screen_stack)

            deadline = observed(app).scope.now() + 5
            await pilot.press("ctrl+d")
            await repeated_quit.wait(
                deadline=deadline, description="repeated quit guard applied"
            )
            assert app.screen is confirmation
            assert len(app.screen_stack) == stack_depth

            deadline = observed(app).scope.now() + 5
            await pilot.press("escape")
            await (
                observed(app)
                .screens.result_applied(confirmation)
                .wait(deadline=deadline, description="owned quit declined")
            )
            await (
                observed(app)
                .screens.retired(confirmation)
                .wait(deadline=deadline, description="owned quit confirmation retired")
            )
            assert app.screen is underlying

    asyncio.run(exercise())


@pytest.mark.parametrize("chord", ("ctrl+c", "ctrl+d"))
def test_blocked_global_quit_preserves_active_modal(
    chord: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from _completion import CompletionKey

    from taut_tui.actions import ActionId
    from taut_tui.app import TautApp
    from taut_tui.forms import FORM_SPECS
    from taut_tui.screens import NativeFormScreen

    class BlockingSystem:
        def quit_block_reason(self) -> str:
            return "A workspace dump is still running."

        def close(self) -> None:
            pass

    async def exercise() -> None:
        app = TautApp(db_path=None, as_name=None, continuity_token=None)
        async with app.run_test(size=(100, 34)) as pilot:
            assert app._system is not None
            app._system.close()
            app._system = BlockingSystem()  # type: ignore[assignment]
            modal = NativeFormScreen(FORM_SPECS[ActionId.CHANNEL_JOIN])
            deadline = observed(app).scope.now() + 5
            app.push_screen(modal)
            await observed(app).screens.ready(modal, deadline=deadline)
            quit_applied = observed(app).scope.expect(
                CompletionKey(app, "guarded_quit.applied", request=object())
            )
            original_quit = app.action_quit_tui

            def quit_tui() -> None:
                original_quit()
                quit_applied.succeed(quit_applied.key, None)

            monkeypatch.setattr(app, "action_quit_tui", quit_tui)

            deadline = observed(app).scope.now() + 5
            await pilot.press(chord)
            await quit_applied.wait(deadline=deadline, description="quit guard applied")

            assert app.is_running
            assert app.screen is modal
            assert (
                "workspace dump is still running"
                in str(app.query_one("#inspector-body").render()).lower()
            )

    asyncio.run(exercise())


def test_enter_delimits_full_command_without_capturing_shorter_root() -> None:
    from taut_tui.app import TautApp
    from taut_tui.screens import CommandLineScreen

    async def exercise() -> None:
        app = TautApp(db_path=None, as_name=None, continuity_token=None)
        async with app.run_test(size=(100, 34)) as pilot:
            composer = app.query_one("#composer", TautComposer)
            deadline = observed(app).scope.now() + 5
            composer.focus()
            await observed(app).focus(composer, deadline=deadline)

            await pilot.press(*":whoami")
            assert composer.text == ":whoami"
            assert app.screen is app._base_screen

            await pilot.press("enter")

            assert isinstance(app.screen, CommandLineScreen)
            command = app.screen.query_one("#command-line", Input)
            assert command.value == "whoami"
            assert command.has_focus
            assert composer.text == ":whoami"

    asyncio.run(exercise())


def test_unknown_colon_text_stays_message_and_command_cancel_preserves_draft() -> None:
    from taut_tui.app import TautApp
    from taut_tui.screens import CommandLineScreen

    async def exercise() -> None:
        app = TautApp(db_path=None, as_name=None, continuity_token=None)
        async with app.run_test(size=(100, 34)) as pilot:
            composer = app.query_one("#composer", TautComposer)
            deadline = observed(app).scope.now() + 5
            composer.focus()
            await observed(app).focus(composer, deadline=deadline)

            await pilot.press(*":summonship", "space")
            assert app.screen is app._base_screen
            assert composer.text == ":summonship "

            composer.text = ""
            await pilot.press(*":summon", "space")
            assert isinstance(app.screen, CommandLineScreen)
            command_screen = app.screen
            deadline = observed(app).scope.now() + 5
            await pilot.press("escape")
            await (
                observed(app)
                .screens.result_applied(command_screen)
                .wait(deadline=deadline, description="cancelled command applied")
            )
            await (
                observed(app)
                .screens.retired(command_screen)
                .wait(deadline=deadline, description="cancelled command retired")
            )
            await observed(app).focus(composer, deadline=deadline)

            assert app.screen is app._base_screen
            assert composer.text == ":summon "
            assert composer.has_focus
            assert app.visual_state.mode is InteractionMode.COMPOSE
            draft = app.visual_state.draft_for("__unselected__")
            assert draft is not None and draft.text == ":summon "

            await pilot.press("ctrl+q")
            # Negative input case: the real Key dispatch has returned; ctrl+q
            # has no binding and schedules no quit or other deferred action.
            assert app.is_running
            assert app.visual_state.mode is InteractionMode.COMPOSE

    asyncio.run(exercise())


def test_text_command_rename_preserves_draft(
    tmp_path: Path,
) -> None:
    from taut.commands.syntax import CommandInput, CommandInvocation
    from taut_tui.app import TautApp
    from taut_tui.models import DraftState
    from taut_tui.screens import ConfirmationScreen

    async def exercise() -> None:
        db_path = tmp_path / "text-rename.db"
        TautClient.init(db_path=db_path)
        client = TautClient(db_path=db_path, as_name="alice")
        try:
            client.join("general")
        finally:
            client.close()
        app = TautApp(db_path=str(db_path), as_name="alice", continuity_token=None)
        async with app.run_test(size=(100, 34)):
            await observed(app).navigation()
            assert app._domain is not None
            intent = app._advance_conversation_intent()
            app._watch_future(
                app._domain.open_conversation("general", intent_token=intent),
                lambda done: app._apply_optional_conversation(intent, done),
            )
            await observed(app).conversation()
            assert app.visual_state.active_conversation == "general"
            app.visual_state = app.visual_state.with_draft(
                DraftState("general", "source\ndraft", 4, 2)
            )
            composer = app.query_one("#composer", TautComposer)
            composer.text = "source\ndraft"
            composer.cursor_position = 4

            successful = CommandInvocation(
                path=("channel", "rename"),
                values={"old_name": "#general", "new_name": "#renamed"},
                source=CommandInput("channel rename #general #renamed"),
            )
            deadline = observed(app).scope.now() + 5
            assert app._dispatch_channel_command(successful, app._domain)
            await observed(app).screens.ready(app.screen, deadline=deadline)
            assert isinstance(app.screen, ConfirmationScreen)
            renamed = observed(app).action("rename_channel")
            deadline = observed(app).scope.now() + 5
            app.screen.query_one("#confirmation-confirm", Button).press()
            await renamed.wait(deadline)
            await observed(app).conversation(deadline=deadline)
            assert app.visual_state.active_conversation == "renamed"
            assert app.visual_state.draft_for("renamed") == DraftState(
                "renamed", "source\ndraft", 4, 2
            )
            submitted = observed(app).sending()
            composer.action_submit()
            await observed(app).send(submitted)
            assert any(row.text == "source\ndraft" for row in app._message_rows)

    asyncio.run(exercise())


def test_rename_completion_does_not_replace_newer_navigation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from taut.client import Thread
    from taut_tui.app import TautApp
    from taut_tui.models import DraftState

    class Session:
        @staticmethod
        def open_conversation(*args: object, **kwargs: object) -> Future[Any]:
            raise AssertionError("stale rename completion reopened its old view")

        @staticmethod
        def refresh_navigation() -> Future[Any]:
            return Future()

    async def exercise() -> None:
        db_path = tmp_path / "rename-intent.db"
        TautClient.init(db_path=db_path)
        app = TautApp(db_path=str(db_path), as_name="alice", continuity_token=None)
        async with app.run_test(size=(100, 34)):
            app._session = cast(Any, Session())
            app._conversation_intent = 2
            app.visual_state = replace(
                app.visual_state.with_draft(DraftState("general", "draft", 3, 1)),
                active_conversation="newer-target",
            )
            app._render_inspector("newer navigation state")
            monkeypatch.setattr(
                app,
                "_watch_future",
                lambda future, apply: apply(future) if future.done() else None,
            )
            renamed: Future[Thread] = Future()
            renamed.set_result(Thread("renamed", None, False, None))

            app._apply_channel_rename_result(
                renamed,
                old_name="general",
                intent=1,
                active_target="general",
                screen=None,
            )

            assert app.visual_state.active_conversation == "newer-target"
            assert app.visual_state.draft_for("renamed") == DraftState(
                "renamed", "draft", 3, 1
            )
            assert "newer navigation state" in str(
                app.query_one("#inspector-body").render()
            )

    asyncio.run(exercise())


def test_rename_reopen_failure_reports_without_rolling_back_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from taut.client import Thread
    from taut_tui.app import TautApp
    from taut_tui.models import DraftState

    open_calls: list[tuple[str, str | None, int | None]] = []
    rename_calls: list[tuple[str, str]] = []

    renamed: Future[Thread] = Future()
    renamed.set_result(Thread("renamed", None, False, None))

    class Domain:
        @staticmethod
        def rename_channel(old_name: str, new_name: str) -> Future[Thread]:
            rename_calls.append((old_name, new_name))
            return renamed

    class Session:
        @staticmethod
        def open_conversation(
            target: str,
            *,
            reply_thread: str | None,
            intent_token: int | None,
        ) -> Future[Any]:
            open_calls.append((target, reply_thread, intent_token))
            failed: Future[Any] = Future()
            failed.set_exception(RuntimeError("reopen unavailable"))
            return failed

        @staticmethod
        def refresh_navigation() -> Future[Any]:
            return Future()

    async def exercise() -> None:
        db_path = tmp_path / "rename-reopen.db"
        TautClient.init(db_path=db_path)
        app = TautApp(db_path=str(db_path), as_name="alice", continuity_token=None)
        async with app.run_test(size=(100, 34)):
            app._session = cast(Any, Session())
            app._conversation_intent = 1
            app.visual_state = replace(
                app.visual_state.with_draft(DraftState("general", "draft", 3, 1)),
                active_conversation="general",
            )
            composer = app.query_one("#composer", TautComposer)
            composer.text = "draft"
            composer.cursor_position = 3
            monkeypatch.setattr(
                app,
                "_watch_future",
                lambda future, apply: apply(future) if future.done() else None,
            )
            app._submit_channel_rename(
                cast(Any, Domain()),
                "general",
                "renamed",
            )

            assert rename_calls == [("general", "renamed")]
            assert open_calls == [("renamed", None, 2)]
            assert app.visual_state.active_conversation == "renamed"
            assert app.visual_state.draft_for("general") is None
            assert app.visual_state.draft_for("renamed") == DraftState(
                "renamed", "draft", 3, 1
            )
            assert (
                "Channel renamed, but reopening its view failed: reopen unavailable"
                in str(app.query_one("#inspector-body").render())
            )

    asyncio.run(exercise())


def test_successful_promoted_command_clears_unchanged_originating_draft() -> None:
    from taut_tui.app import TautApp
    from taut_tui.screens import CommandLineScreen

    async def exercise() -> None:
        app = TautApp(db_path=None, as_name=None, continuity_token=None)
        async with app.run_test(size=(100, 34)) as pilot:
            composer = app.query_one("#composer", TautComposer)
            deadline = observed(app).scope.now() + 5
            composer.focus()
            await observed(app).focus(composer, deadline=deadline)

            await pilot.press(*":whoami", "enter")
            assert isinstance(app.screen, CommandLineScreen)
            command_screen = app.screen
            deadline = observed(app).scope.now() + 5
            await pilot.press("enter")
            await (
                observed(app)
                .screens.result_applied(command_screen)
                .wait(deadline=deadline, description="promoted command applied")
            )
            await (
                observed(app)
                .screens.retired(command_screen)
                .wait(deadline=deadline, description="promoted command retired")
            )

            assert app.screen is app._base_screen
            assert composer.text == ""
            draft = app.visual_state.draft_for("__unselected__")
            assert draft is not None and draft.text == ""

    asyncio.run(exercise())


def test_promoted_command_does_not_clear_a_newer_originating_draft() -> None:
    from taut_tui.app import TautApp
    from taut_tui.screens import CommandLineScreen

    async def exercise() -> None:
        app = TautApp(db_path=None, as_name=None, continuity_token=None)
        async with app.run_test(size=(100, 34)) as pilot:
            composer = app.query_one("#composer", TautComposer)
            deadline = observed(app).scope.now() + 5
            composer.focus()
            await observed(app).focus(composer, deadline=deadline)

            await pilot.press(*":whoami", "enter")
            assert isinstance(app.screen, CommandLineScreen)
            command_screen = app.screen
            edited = observed(app).composer_edit(composer)
            deadline = observed(app).scope.now() + 5
            composer.text = "newer draft"
            await edited.wait(deadline=deadline, description="newer draft applied")
            deadline = observed(app).scope.now() + 5
            await pilot.press("enter")
            await (
                observed(app)
                .screens.result_applied(command_screen)
                .wait(deadline=deadline, description="promoted command applied")
            )
            await (
                observed(app)
                .screens.retired(command_screen)
                .wait(deadline=deadline, description="promoted command retired")
            )

            assert app.screen is app._base_screen
            assert composer.text == "newer draft"
            draft = app.visual_state.draft_for("__unselected__")
            assert draft is not None and draft.text == "newer draft"

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
                if not str(results.get_option_at_index(index).id).startswith("group:")
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


def test_command_palette_mouse_activation_opens_summon_argument_form() -> None:
    from taut_tui.actions import ActionId
    from taut_tui.app import TautApp
    from taut_tui.screens import SummonStartScreen
    from taut_tui.widgets import TautOptionList

    async def exercise() -> None:
        app = TautApp(db_path=None, as_name=None, continuity_token=None)
        async with app.run_test(size=(100, 34)) as pilot:
            deadline = observed(app).scope.now() + 5
            await pilot.press("ctrl+p")
            query = app.screen.query_one("#palette-query", Input)
            await observed(app).focus(query, deadline=deadline)
            await pilot.press(*"Start summoned member")
            # Input.Changed renders these palette results synchronously; the
            # typed-key dispatch fence includes that real handler.

            results = app.screen.query_one("#palette-results", TautOptionList)
            assert results.option_count == 1
            pushed = observed(app).screen_for_action(ActionId.SUMMON_START)
            assert await pilot.click(
                "#palette-results",
                offset=(1, 0),
                times=2,
            )
            screen = await observed(app).pushed(pushed, focus="#summon-name")
            assert isinstance(screen, SummonStartScreen)

            name = app.screen.query_one("#summon-name", Input)
            assert name.has_focus
            await pilot.press(*"grok")
            assert name.value == "grok"

    asyncio.run(exercise())


def test_command_palette_double_click_dismisses_only_once() -> None:
    from taut_tui.app import TautApp

    async def exercise() -> None:
        app = TautApp(db_path=None, as_name=None, continuity_token=None)
        async with app.run_test(size=(100, 34)) as pilot:
            await pilot.press("ctrl+p")
            palette = app.screen
            deadline = observed(app).scope.now() + 5
            assert await pilot.click("#palette-results", offset=(1, 1), times=2)
            await (
                observed(app)
                .screens.result_applied(palette)
                .wait(
                    deadline=deadline, description="double-click palette result applied"
                )
            )
            await (
                observed(app)
                .screens.retired(palette)
                .wait(deadline=deadline, description="double-click palette retired")
            )
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
            await observed(app).navigation()
            assert expected in app._navigation_targets
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
            await observed(app).navigation()
            assert _has_option_containing(navigation, "#general")
            navigation.highlighted = _option_index_containing(navigation, "#general")
            navigation.focus()
            await pilot.press("enter")
            await observed(app).conversation()
            assert app._message_rows
            transcript = app.query_one("#transcript", TautOptionList)
            deadline = observed(app).scope.now() + 5
            transcript.highlighted = 0
            await observed(app).highlighted(transcript, 0, deadline=deadline)
            assert all(
                app.query_one(selector).display
                for selector in (
                    "#composer-send",
                    "#members-action",
                    "#reply-action",
                    "#react-action",
                    "#delete-action",
                )
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
            composer = app.query_one("#composer", TautComposer)
            composer.text = "route this send"
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
        thread_count=2,
        cursor_lag={"general": 3},
        details={"state": "ready"},
    )
    member = SummonedMember(
        member_id="m_agent",
        name="agent",
        provider="openai",
    )

    rendered_status = _safe_projection(status)
    for expected in (
        "agent",
        "provider=openai",
        "driver=codex",
        "threads=2",
        "#general:3",
        "state=ready",
    ):
        assert expected in rendered_status
    rendered_member = _safe_projection(member)
    for expected in ("agent", "openai", "live"):
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

            assert app._summon_interaction is not None
            app._complete_summon_start(
                SummonStartSubmission(
                    name="agent",
                    threads=("general",),
                    provider=None,
                    persona=None,
                    system_prompt_file=None,
                    rate_limit=None,
                    attach=False,
                    detach=False,
                    takeover=False,
                )
            )
            assert "request construction failed" in str(
                app.query_one("#inspector-body").render()
            )

    asyncio.run(synchronous())


def test_native_and_textual_summon_routes_share_confirmation_before_suspend(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from taut_summon import _adapter as adapter_module
    from taut_summon._pty import PtyAdapter, PtySpec

    from taut_tui import summon as tui_summon
    from taut_tui.app import TautApp
    from taut_tui.screens import ConfirmationScreen, SummonStartScreen
    from taut_tui.widgets import TautOptionList

    db_path = tmp_path / "summon-confirmation-routes.db"
    TautClient.init(db_path=db_path)
    spawn_calls: list[str] = []

    def forbidden_spawn(self: PtyAdapter, **_kwargs: object) -> object:
        spawn_calls.append(self.name)
        raise AssertionError("provider spawned before confirmation cancellation")

    def grok_factory() -> PtyAdapter:
        return PtyAdapter(PtySpec(name="grok", argv=("unused",)))

    # This test owns host routing and the pre-spawn acknowledgement boundary,
    # not the POSIX-only PTY transport. The scripted provider is the public
    # cross-platform external-provider seam; it occupies the grok factory slot
    # so both exact route inputs still traverse provider resolution. Any
    # attempted spawn remains a firing failure.
    monkeypatch.setitem(adapter_module._FACTORIES, "grok", grok_factory)
    monkeypatch.setattr(PtyAdapter, "spawn", forbidden_spawn)
    monkeypatch.setattr(tui_summon, "_standard_terminal_is_suitable", lambda: True)

    async def exercise() -> None:
        app = TautApp(db_path=str(db_path), as_name=None, continuity_token=None)
        async with app.run_test(size=(100, 34)) as pilot:
            assert app._summon_interaction is not None
            assert app._summon is not None
            confirmation_requests: asyncio.Queue[object] = asyncio.Queue()
            started_futures: asyncio.Queue[Future[None]] = asyncio.Queue()
            real_confirmation_handler = type(
                app
            ).on_terminal_attach_confirmation_request
            real_start = app._summon.start

            def observed_confirmation(owner: TautApp, request: object) -> None:
                real_confirmation_handler(owner, request)  # type: ignore[arg-type]
                if owner is app:
                    confirmation_requests.put_nowait(request)

            def observed_start(
                request: object,
                interaction: object,
            ) -> tuple[str, Future[None]]:
                token, future = real_start(request, interaction)
                started_futures.put_nowait(future)
                return token, future

            monkeypatch.setattr(
                type(app),
                "on_terminal_attach_confirmation_request",
                observed_confirmation,
            )
            monkeypatch.setattr(app._summon, "start", observed_start)

            suspend_calls: list[str] = []
            real_suspend = app.suspend

            def observed_suspend() -> object:
                suspend_calls.append("suspend")
                return real_suspend()

            monkeypatch.setattr(app, "suspend", observed_suspend)
            deadline = observed(app).scope.now() + 5
            await pilot.press("ctrl+p")
            query = app.screen.query_one("#palette-query", Input)
            await observed(app).focus(query, deadline=deadline)
            await pilot.press(*"Start summoned member")
            results = app.screen.query_one("#palette-results", TautOptionList)
            assert results.option_count == 1
            from taut_tui.actions import ActionId

            pushed = observed(app).screen_for_action(ActionId.SUMMON_START)
            assert await pilot.click("#palette-results", offset=(1, 0), times=2)
            screen = await observed(app).pushed(pushed, focus="#summon-name")
            assert isinstance(screen, SummonStartScreen)
            app.screen.query_one("#summon-name", Input).value = "native-grok"
            app.screen.query_one("#summon-provider", Select).value = "grok"
            app.screen.query_one("#summon-submit", Button).press()
            native_future = await _await_summon_confirmation(
                app,
                started_futures,
                confirmation_requests,
                ConfirmationScreen,
            )
            confirmation = cast(ConfirmationScreen, app.screen)
            assert "provider setup" in confirmation.prompt
            assert "Ctrl-\\ Ctrl-\\" in confirmation.prompt
            assert suspend_calls == []
            await pilot.press("escape")
            await _await_cancelled_summon_run(app, native_future)

            composer = app.query_one("#composer", TautComposer)
            deadline = observed(app).scope.now() + 5
            composer.focus()
            await observed(app).focus(composer, deadline=deadline)
            await pilot.press(*":summon", "space", *"grok", "enter")
            textual_future = await _await_summon_confirmation(
                app,
                started_futures,
                confirmation_requests,
                ConfirmationScreen,
            )
            confirmation = cast(ConfirmationScreen, app.screen)
            assert "provider setup" in confirmation.prompt
            assert suspend_calls == []
            await pilot.press("escape")
            await _await_cancelled_summon_run(app, textual_future)
            assert spawn_calls == []

    asyncio.run(exercise())


def test_tui_unmount_cancels_pending_attach_confirmation(tmp_path: Path) -> None:
    from taut_summon import TerminalAttachNotice

    from taut_tui.app import TautApp
    from taut_tui.screens import ConfirmationScreen

    db_path = tmp_path / "summon-confirmation-unmount.db"
    TautClient.init(db_path=db_path)
    decisions: list[bool] = []
    worker: threading.Thread | None = None

    async def exercise() -> None:
        nonlocal worker
        app = TautApp(db_path=str(db_path), as_name=None, continuity_token=None)
        async with app.run_test(size=(100, 34)):
            interaction = app._summon_interaction
            assert interaction is not None
            notice = TerminalAttachNotice(
                member="grok",
                provider="grok",
                detach_hint="Ctrl-\\ Ctrl-\\",
            )
            worker = threading.Thread(
                target=lambda: decisions.append(
                    interaction.confirm_terminal_attach(notice)
                ),
                daemon=True,
            )
            pushed = observed(app).attach_confirmation(notice)
            worker.start()
            screen = await observed(app).pushed(pushed)
            assert isinstance(screen, ConfirmationScreen)
            assert decisions == []

    asyncio.run(exercise())
    assert worker is not None
    worker.join(timeout=5.0)
    assert not worker.is_alive()
    assert decisions == [False]


def test_resolved_attach_confirmation_never_opens_stale_modal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from _completion import CompletionKey
    from taut_summon import TerminalAttachNotice

    from taut_tui.app import TautApp
    from taut_tui.screens import ConfirmationScreen
    from taut_tui.summon import TerminalAttachConfirmationRequest

    db_path = tmp_path / "resolved-summon-confirmation.db"
    TautClient.init(db_path=db_path)
    request = TerminalAttachConfirmationRequest(
        TerminalAttachNotice(
            member="agent",
            provider="grok",
            detach_hint="Ctrl-\\ Ctrl-\\",
        )
    )
    request.resolve(False)

    async def exercise() -> None:
        app = TautApp(db_path=str(db_path), as_name=None, continuity_token=None)
        async with app.run_test(size=(100, 34)):
            applied = observed(app).scope.expect(
                CompletionKey(app, "attach_request.applied", request=request)
            )
            dispatch = app._on_message

            async def apply(event: Any) -> None:
                await dispatch(event)
                if event is request:
                    applied.succeed(applied.key, None)

            monkeypatch.setattr(app, "_on_message", apply)
            deadline = observed(app).scope.now() + 5
            assert app.post_message(request)
            await applied.wait(
                deadline=deadline, description="resolved request handled"
            )
            assert not isinstance(app.screen, ConfirmationScreen)

    asyncio.run(exercise())


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
        async with app.run_test(size=(130, 34)):
            await observed(app).navigation()
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
            button = app.query_one("#composer-send", Button)
            pressed = observed(app).button_press(button)
            deadline = observed(app).scope.now() + 5
            button.press()
            await pressed.wait(
                deadline=deadline, description="disabled send dispatched"
            )
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
        async with app.run_test(size=(100, 34)):
            await observed(app).navigation()
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
            await observed(app).navigation()
            assert app._navigation_targets[:1] == ["general"]
            assert await pilot.click("#navigation-list", offset=(1, 0)) is True
            assert navigation.highlighted == 0
            assert app.visual_state.active_conversation is None

            await pilot.press("enter")
            await observed(app).conversation()
            assert app.visual_state.active_conversation == "general"

        second = TautApp(db_path=str(db_path), as_name="alice", continuity_token=None)
        async with second.run_test(size=(100, 34)) as pilot:
            navigation = second.query_one("#navigation-list", TautOptionList)
            await observed(second).navigation()
            assert second._navigation_targets[:1] == ["general"]
            assert await pilot.click("#navigation-list", offset=(1, 0), times=2) is True
            await observed(second).conversation()
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
            await observed(app).navigation()
            assert app._navigation_targets[:1] == ["general"]
            navigation.highlighted = 0
            deadline = observed(app).scope.now() + 5
            navigation.focus()
            await observed(app).focus(navigation, deadline=deadline)

            released = observed(app).pointer_release(navigation)
            deadline = observed(app).scope.now() + 5
            assert await pilot.mouse_down("#navigation-list", offset=(1, 0)) is True
            assert await pilot.mouse_up("#transcript", offset=(1, 0)) is True
            await released.wait(
                deadline=deadline, description="navigation pointer released"
            )
            assert not navigation._pointer_pending
            await pilot.press("enter")
            await observed(app).conversation()
            assert app.visual_state.active_conversation == "general"

            assert app.visual_state.active_conversation == "general"

    asyncio.run(exercise())


def test_direct_message_header_and_composer_use_actor_scoped_label(
    tmp_path: Path,
) -> None:
    from taut_tui.app import TautApp
    from taut_tui.session import NavigationSnapshot
    from taut_tui.widgets import TautOptionList

    db_path = tmp_path / "dm.db"
    TautClient.init(db_path=db_path)
    alice = TautClient(db_path=db_path, as_name="alice")
    bob = TautClient(db_path=db_path, as_name="bob")
    alice.join("general")
    bob.join("general")
    alice.say("@bob", "hello")

    async def exercise() -> None:
        navigation_applied = asyncio.Event()
        navigation_error: BaseException | None = None
        navigation_snapshot: NavigationSnapshot | None = None
        rendered_navigation: tuple[str | object, ...] = ()

        class ObservedTautApp(TautApp):
            def _apply_navigation_result(
                self,
                future: Future[NavigationSnapshot],
            ) -> None:
                nonlocal navigation_error, navigation_snapshot, rendered_navigation
                if future.cancelled():
                    navigation_error = RuntimeError(
                        "initial navigation request was cancelled"
                    )
                else:
                    navigation_error = future.exception()
                    if navigation_error is None:
                        navigation_snapshot = future.result()
                try:
                    super()._apply_navigation_result(future)
                finally:
                    rendered_navigation = tuple(self._navigation_targets)
                    navigation_applied.set()

        app = ObservedTautApp(
            db_path=str(db_path),
            as_name="alice",
            continuity_token=None,
        )
        async with app.run_test(size=(100, 34)) as pilot:
            navigation = app.query_one("#navigation-list", TautOptionList)
            await asyncio.wait_for(navigation_applied.wait(), timeout=5)
            assert navigation_error is None
            assert navigation_snapshot is not None
            assert navigation_snapshot.direct_messages
            assert any(
                isinstance(target, str) and target != "general"
                for target in rendered_navigation
            )
            dm_index = next(
                index
                for index, target in enumerate(app._navigation_targets)
                if isinstance(target, str) and target != "general"
            )
            dm_target = app._navigation_targets[dm_index]
            assert isinstance(dm_target, str)
            navigation.highlighted = dm_index
            navigation.focus()
            await pilot.press("enter")
            await observed(app).conversation()
            assert app.visual_state.active_conversation == dm_target
            assert "DM with bob" in str(app.query_one("#target-header").render())
            assert (
                app.query_one("#composer", TautComposer).placeholder
                == "Message DM with bob"
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
                "PageDown pages down",
                "Ctrl-C / Ctrl-D quits",
                "Tab / Shift-Tab",
                "Ctrl-Enter, Shift-Enter, or Ctrl-J",
                "Ctrl-Tab",
                "g i",
                "Pane",
                "Replies",
            ):
                assert expected in help_text

            await pilot.resize_terminal(64, 34)
            app._show_error("visible failure")
            # Error projection and placement are synchronous owner operations.
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
        async with app.run_test(size=(64, 34)):
            composer = app.query_one("#composer", TautComposer)
            composer.text = "keep\n\tme"
            composer.cursor_position = 6
            deadline = observed(app).scope.now() + 5
            composer.focus()
            await observed(app).focus(composer, deadline=deadline)
            app.visual_state = replace(
                app.visual_state,
                active_conversation="general",
                drafts=(DraftState("general", "keep\n\tme", 6, 3),),
                mode=InteractionMode.COMPOSE,
            )
            app._pending_sends[1] = ("general", 3)
            failed: Future[Message] = Future()
            failed.set_exception(RuntimeError("send failed visibly"))

            app._apply_send_result(1, failed)
            # The tested failure projection is the real synchronous apply.

            assert app.query_one("#conversation").display is True
            assert "send failed visibly" in str(app.query_one("#status-line").render())
            assert app.query_one("#composer", TautComposer).has_focus
            assert app.visual_state.draft_for("general") == DraftState(
                "general", "keep\n\tme", 6, 3
            )
            assert composer.cursor_position == 6

    asyncio.run(exercise())


def test_target_switch_restores_multiline_draft_and_scalar_cursor() -> None:
    from taut_tui.app import TautApp
    from taut_tui.models import DraftState
    from taut_tui.session import ConversationSnapshot

    general = DraftState("general", "one\n\ttwo", 6, 1)
    random = DraftState("random", "other", 3, 1)

    async def exercise() -> None:
        app = TautApp(db_path=None, as_name=None, continuity_token=None)
        async with app.run_test(size=(100, 34)):
            app.visual_state = app.visual_state.with_draft(general)
            app.visual_state = app.visual_state.with_draft(random)

            app._apply_conversation(
                ConversationSnapshot(
                    1,
                    "general",
                    (),
                    intent_token=app._conversation_intent,
                )
            )
            composer = app.query_one("#composer", TautComposer)
            assert composer.text == general.text
            assert composer.cursor_position == general.cursor_position

            app._apply_conversation(
                ConversationSnapshot(
                    2,
                    "random",
                    (),
                    intent_token=app._conversation_intent,
                )
            )
            assert composer.text == random.text
            assert composer.cursor_position == random.cursor_position

            app._apply_conversation(
                ConversationSnapshot(
                    3,
                    "general",
                    (),
                    intent_token=app._conversation_intent,
                )
            )
            assert composer.text == general.text
            assert composer.cursor_position == general.cursor_position

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
            await observed(app).navigation()
            assert app._navigation_targets[:1] == ["general"]
            navigation.highlighted = 0
            navigation.focus()
            await pilot.press("enter")
            await observed(app).conversation()
            assert any(message.ts == root.ts for message in app._message_rows)

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


def test_textual_message_delete_uses_conversation_refresh_completion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from taut.commands.syntax import core_command_syntax, parse_command_line
    from taut_tui.app import TautApp

    deletion: Future[Any] = Future()
    observed: list[tuple[Future[Any], str | None, int]] = []

    class Domain:
        @staticmethod
        def delete_message(message_id: str) -> Future[Any]:
            assert message_id == "1234567890123456789"
            return deletion

    app = TautApp(db_path=None, as_name=None, continuity_token=None)
    app.visual_state = replace(app.visual_state, active_conversation="general")
    app._conversation_intent = 7
    monkeypatch.setattr(app, "_confirm_command", lambda _prompt, action: action())
    monkeypatch.setattr(
        app,
        "_run_deletion",
        lambda future, *, target, intent: observed.append((future, target, intent)),
    )
    invocation = parse_command_line(
        "message delete 1234567890123456789",
        syntax=core_command_syntax(),
    )

    app._dispatch_message_operation(invocation, Domain())  # type: ignore[arg-type]

    assert observed == [(deletion, "general", 7)]


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
            search = observed(app).action("open_search_result")
            app._selected_search_hit = hit
            app._dispatch_tui_action(
                ActionId.SEARCH_OPEN_RESULT,
                source=ActionRoute.CONTEXT,
            )
            assert app._operation_state == "searching"

            navigation = app.query_one("#navigation-list", TautOptionList)
            await observed(app).navigation()
            assert _has_option_containing(navigation, "#random")
            navigation.highlighted = _option_index_containing(navigation, "#random")
            navigation.focus()
            await pilot.press("enter")
            await observed(app).conversation()
            assert app.visual_state.active_conversation == "random"
            assert app._operation_state == "idle"
            assert "searching" not in str(app.query_one("#status-line").render())

            deadline = observed(app).scope.now() + 5
            pending.set_result(context)
            await search.wait(deadline)
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
        def close(self, *, wait: bool = True) -> None:
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
            seen: set[str] = set()
            for _ in range(4):
                for widget_id in ("navigation", "conversation", "inspector"):
                    if app.query_one(f"#{widget_id}").display:
                        seen.add(widget_id)
                button = app.query_one("#pane-affordance", Button)
                pressed = observed(app).button_press(button)
                deadline = observed(app).scope.now() + 5
                assert await pilot.click("#pane-affordance") is True
                await pressed.wait(deadline=deadline, description="pane switch applied")
                await observed(app).button_ready(pressed, deadline=deadline)
            assert seen == {"navigation", "conversation", "inspector"}

    asyncio.run(exercise())


def test_real_app_opens_active_conversation_and_sends_through_public_client(
    tmp_path: Path,
) -> None:
    from textual.widgets import OptionList

    from taut_tui.app import TautApp
    from taut_tui.widgets import TautComposer

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
            await observed(app).navigation()
            assert navigation.option_count and "#general" in str(
                navigation.get_option_at_index(0).prompt
            )

            navigation.highlighted = 0
            navigation.focus()
            await pilot.press("enter")
            await observed(app).conversation()
            assert app.visual_state.active_conversation == "general"

            await pilot.press("i")
            await pilot.press(
                *"hello",
                "ctrl+enter",
                *"from",
                "ctrl+tab",
                *"tui",
            )
            await pilot.press("enter")
            await observed(app).send()
            assert app.query_one("#composer", TautComposer).text == ""

    try:
        asyncio.run(exercise())
        assert any(message.text == "hello\nfrom\ttui" for message in bob.log("general"))
    finally:
        alice.close()
        bob.close()


def test_command_palette_opens_native_form_and_applies_public_identity_change(
    tmp_path: Path,
) -> None:
    from taut_tui.actions import ActionId
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
            pushed = observed(app).screen_for_action(ActionId.IDENTITY_SET_PERSONA)
            await pilot.press(*"set persona", "enter")
            await observed(app).pushed(pushed, focus="#field-persona")
            field = app.screen.query_one("#field-persona", Input)
            field.value = "reviewer"
            changed = observed(app).action("set_persona")
            deadline = observed(app).scope.now() + 5
            app.screen.query_one("#form-submit", Button).press()
            await changed.wait(deadline)
            assert alice.whoami().persona == "reviewer"

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
        async with app.run_test(size=(100, 34)):
            deadline = observed(app).scope.now() + 5
            app._dispatch_tui_action(
                ActionId.IDENTITY_SET_NAME,
                source=ActionRoute.PALETTE,
            )
            await observed(app).screens.ready(app.screen, deadline=deadline)
            field = app.screen.query_one("#field-name", Input)
            field.value = "bad name"
            rejected = observed(app).action("set_name")
            deadline = observed(app).scope.now() + 5
            app.screen.query_one("#form-submit", Button).press()
            with pytest.raises(ValueError, match="name must match"):
                await rejected.wait(deadline)
            error = str(app.screen.query_one("#form-errors").render())
            assert error and error != "Working…"
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
        async with app.run_test(size=(100, 24)):
            app._selected_search_hit = hit
            app._open_selected_search_result()
            await observed(app).conversation()
            assert app.visual_state.active_conversation == "general"
            assert any(message.ts == hit.ts for message in app._message_rows)
            assert app.visual_state.viewport.message_id == hit.ts
            transcript = app.query_one("#transcript", TautOptionList)
            assert app._message_rows[transcript.highlighted or 0].ts == hit.ts

    try:
        asyncio.run(exercise())
    finally:
        alice.close()


@pytest.mark.parametrize(
    "user_input",
    ["wheel", "scrollbar", "conventional-key", "vi-key", "click"],
)
def test_user_scroll_supersedes_pending_search_anchor_restore(
    user_input: str,
) -> None:
    from taut.client import Message
    from taut_tui.app import TautApp
    from taut_tui.viewport import ViewportEffect, ViewportEffectKind
    from taut_tui.widgets import TautOptionList

    messages = tuple(
        Message("general", index, "m_alice", "alice", "message", f"row {index}")
        for index in range(1, 50)
    )

    async def exercise() -> None:
        app = TautApp(db_path=None, as_name=None, continuity_token=None)
        async with app.run_test(size=(100, 24)) as pilot:
            transcript = app.query_one("#transcript", TautOptionList)
            app._conversation_intent = 7
            app._message_rows = messages
            measured = observed(app).rows_measured(transcript)
            deadline = observed(app).scope.now() + 5
            transcript.add_options(app._message_prompt(message) for message in messages)
            await measured.wait(
                deadline=deadline, description="initial scroll rows measured"
            )
            initial_offset = transcript.scroll_offset.y
            app._arm_search_anchor(7, messages[24].ts)
            search_generation = app.visual_state.viewport.generation

            settled = observed(app).user_viewport()
            deadline = observed(app).scope.now() + 5
            await _perform_viewport_user_input(user_input, pilot, transcript)
            await settled.wait(deadline=deadline, description="user viewport committed")

            def viewport_matches_widget() -> bool:
                viewport = app.visual_state.viewport
                target_y = int(transcript.scroll_target_y)
                if target_y >= int(transcript.max_scroll_y):
                    return viewport.tail_pinned
                width = max(1, transcript.scrollable_content_region.width)
                remaining = target_y
                for item in messages:
                    height = app._message_row_height(item, width)
                    if remaining < height:
                        return (
                            viewport.message_id == item.ts
                            and viewport.offset == remaining
                        )
                    remaining -= height
                return False

            assert viewport_matches_widget()
            await asyncio.wait_for(
                app.animator.wait_until_complete(),
                timeout=max(0, deadline - observed(app).scope.now()),
            )
            assert int(transcript.scroll_offset.y) == int(transcript.scroll_target_y)

            assert app.visual_state.viewport.search_owned is False
            if user_input != "click":
                assert transcript.scroll_offset.y != initial_offset
            user_anchor = app.visual_state.viewport
            user_offset = transcript.scroll_offset.y
            assert user_anchor.message_id != messages[24].ts

            rendered = asyncio.Event()
            app._render_messages(messages)
            app.call_after_refresh(rendered.set)
            await asyncio.wait_for(rendered.wait(), timeout=5)
            assert transcript.scroll_offset.y == user_offset
            assert app.visual_state.viewport.message_id == user_anchor.message_id

            app._apply_viewport_effect(
                ViewportEffect(
                    search_generation,
                    ViewportEffectKind.RESTORE,
                    message_id=messages[24].ts,
                ),
                messages,
            )
            assert transcript.scroll_offset.y == user_offset

    asyncio.run(exercise())


def test_programmatic_scroll_does_not_claim_user_viewport_intent() -> None:
    from taut.client import Message
    from taut_tui.app import TautApp
    from taut_tui.widgets import TautOptionList

    messages = tuple(
        Message("general", index, "m_alice", "alice", "message", f"row {index}")
        for index in range(1, 50)
    )

    async def exercise() -> None:
        app = TautApp(db_path=None, as_name=None, continuity_token=None)
        async with app.run_test(size=(100, 24)):
            transcript = app.query_one("#transcript", TautOptionList)
            app._message_rows = messages
            transcript.add_options(item.text for item in messages)
            app._arm_search_anchor(7, messages[24].ts)
            owner = app.visual_state.viewport

            transcript.scroll_to(y=10, animate=False, force=True, immediate=True)
            # Immediate non-animated scroll has no pending movement phase.

            assert app.visual_state.viewport == owner
            assert app.visual_state.viewport.search_owned is True

    asyncio.run(exercise())


def test_wide_pane_focus_move_does_not_stale_queued_viewport_restore() -> None:
    from taut_tui.app import TautApp
    from taut_tui.models import FocusTarget, LogicalSurface
    from taut_tui.viewport import TranscriptViewport

    async def exercise() -> None:
        app = TautApp(db_path=None, as_name=None, continuity_token=None)
        async with app.run_test(size=(130, 34)):
            planned, effect = TranscriptViewport.history(42).plan_render()
            assert effect is not None
            app.visual_state = replace(
                app.visual_state,
                focus=FocusTarget(LogicalSurface.NAVIGATION, "navigation-list"),
                pane_choice=LogicalSurface.NAVIGATION,
                viewport=planned,
            )

            app._move_surface(1)

            assert app.visual_state.viewport == planned
            assert app.visual_state.viewport.accepts(effect)

    asyncio.run(exercise())


def test_removed_history_anchor_recovers_to_tail() -> None:
    from taut.client import Message
    from taut_tui.app import TautApp
    from taut_tui.viewport import TranscriptViewport
    from taut_tui.widgets import TautOptionList

    messages = tuple(
        Message("general", index, "m_alice", "alice", "message", f"row {index}")
        for index in range(1, 30)
    )

    async def exercise() -> None:
        app = TautApp(db_path=None, as_name=None, continuity_token=None)
        async with app.run_test(size=(100, 24)):
            app.visual_state = replace(
                app.visual_state,
                viewport=TranscriptViewport.history(999),
            )
            recovered = observed(app).recovering_tail()
            deadline = observed(app).scope.now() + 5
            app._render_messages(messages)
            transcript = app.query_one("#transcript", TautOptionList)
            await recovered.wait(
                deadline=deadline,
                description="missing history anchor recovered to tail",
            )
            assert (
                app.visual_state.viewport.tail_pinned
                and transcript.is_vertical_scroll_end
            )

    asyncio.run(exercise())


def test_completed_search_restore_releases_viewport_ownership() -> None:
    from taut.client import Message
    from taut_tui.app import TautApp
    from taut_tui.widgets import TautOptionList

    messages = tuple(
        Message("general", index, "m_alice", "alice", "message", f"row {index}")
        for index in range(1, 50)
    )
    message = messages[24]

    async def exercise() -> None:
        app = TautApp(db_path=None, as_name=None, continuity_token=None)
        async with app.run_test(size=(100, 34)):
            app._conversation_intent = 7
            app._message_rows = messages
            transcript = app.query_one("#transcript", TautOptionList)
            transcript.add_options(item.text for item in messages)
            app.visual_state = replace(
                app.visual_state,
                selected_message_id=message.ts,
            )
            app._arm_search_anchor(7, message.ts)
            app._render_messages(messages, restore_owner_intent=7)
            await observed(app).viewport()
            assert app.visual_state.viewport.search_owned is False

            transcript.scroll_to(y=5, animate=False, force=True, immediate=True)
            # Explicit immediate programmatic scroll has no deferred settlement.
            app._capture_settled_transcript_viewport()
            assert app.visual_state.viewport.tail_pinned is False
            assert app.visual_state.viewport.message_id != message.ts
            assert app.visual_state.selected_message_id == message.ts
            user_offset = transcript.scroll_offset.y

            rendered = asyncio.Event()
            app._render_messages(messages)
            app.call_after_refresh(rendered.set)
            await asyncio.wait_for(rendered.wait(), timeout=5)
            assert transcript.scroll_offset.y == user_offset
            assert app.visual_state.selected_message_id == message.ts

    asyncio.run(exercise())


def test_pending_search_anchor_rejects_stale_render_highlight() -> None:
    from types import SimpleNamespace

    from taut.client import Message
    from taut_tui.app import TautApp
    from taut_tui.widgets import TautOptionList

    messages = tuple(
        Message("general", index, "m_alice", "alice", "message", f"row {index}")
        for index in range(1, 4)
    )
    hit = messages[1]

    async def exercise() -> None:
        app = TautApp(db_path=None, as_name=None, continuity_token=None)
        async with app.run_test(size=(100, 34)):
            transcript = app.query_one("#transcript", TautOptionList)
            app._render_messages(messages)
            app._conversation_intent = 7
            stale = transcript.OptionHighlighted(
                transcript,
                transcript.get_option_at_index(2),
                2,
            )
            assert transcript.post_message(stale)
            app.visual_state = replace(app.visual_state, selected_message_id=hit.ts)
            app._arm_search_anchor(7, hit.ts)
            app.on_option_list_option_highlighted(stale)

            assert app.visual_state.selected_message_id == hit.ts
            assert app.visual_state.viewport.message_id == hit.ts
            assert app.visual_state.viewport.search_owned is True

            transcript.on_click(
                SimpleNamespace(
                    style=SimpleNamespace(meta={"option": 2}),
                    chain=1,
                )
            )
            assert app.visual_state.viewport.search_owned is False

    asyncio.run(exercise())


@pytest.mark.parametrize("event_kind", ("highlight", "activation"))
@pytest.mark.parametrize("replacement", ("shifted", "removed", "other-thread"))
def test_queued_transcript_input_resolves_message_identity(
    event_kind: str,
    replacement: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from taut.client import Message
    from taut_tui.app import TautApp
    from taut_tui.widgets import TautOptionList

    messages = tuple(
        Message("general", index, "m_alice", "alice", "message", f"row {index}")
        for index in range(1, 4)
    )

    async def exercise() -> None:
        app = TautApp(db_path=None, as_name=None, continuity_token=None)
        async with app.run_test(size=(100, 34)):
            app._render_messages(messages)
            transcript = app.query_one("#transcript", TautOptionList)
            event_type = (
                TautOptionList.OptionHighlighted
                if event_kind == "highlight"
                else TautOptionList.Activated
            )
            captured = observed(app).scope.expect(
                CompletionKey(app, "queued_input.captured", request=object())
            )
            released = observed(app).scope.expect(
                CompletionKey(app, "queued_input.released", request=object())
            )
            applied = observed(app).scope.expect(
                CompletionKey(app, "queued_input.applied", request=captured)
            )
            original_dispatch = app._on_message
            deadline = observed(app).scope.now() + 5

            async def dispatch(event: Any) -> None:
                if not isinstance(event, event_type):
                    await original_dispatch(event)
                    return
                try:
                    captured.succeed(captured.key, event)
                    await released.wait(
                        deadline=deadline, description="release real input"
                    )
                    await original_dispatch(event)
                except BaseException as error:
                    applied.fail(applied.key, error)
                    raise
                else:
                    applied.succeed(applied.key, event)

            monkeypatch.setattr(app, "_on_message", dispatch)
            if event_kind == "highlight":
                transcript.action_first()
            else:
                with transcript.prevent(TautOptionList.OptionHighlighted):
                    transcript.highlighted = 0
                transcript.action_select()
            await captured.wait(
                deadline=deadline, description="real widget input captured"
            )
            rows = {
                "shifted": (messages[1], messages[0], messages[2]),
                "removed": messages[1:],
                "other-thread": tuple(
                    replace(message, thread="other") for message in messages
                ),
            }[replacement]
            app._render_messages(rows)
            before_inspector = app.visual_state.inspector
            released.succeed(released.key, None)
            await applied.wait(deadline=deadline, description="queued input applied")
            expected_id = 1 if replacement == "shifted" else 3
            expected_index = 1 if replacement != "other-thread" else 2
            assert app.visual_state.selected_message_id == expected_id
            assert transcript.highlighted == expected_index
            if replacement != "shifted":
                assert app.visual_state.inspector == before_inspector

    asyncio.run(exercise())


@pytest.mark.parametrize("render_before_second", (False, True))
def test_older_highlight_does_not_rewind_newer_keyboard_input(
    render_before_second: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from textual import events

    from taut.client import Message
    from taut_tui.app import TautApp
    from taut_tui.widgets import TautOptionList

    async def exercise() -> None:
        app = TautApp(db_path=None, as_name=None, continuity_token=None)
        async with app.run_test(size=(100, 34)):
            app._render_messages(
                tuple(
                    Message("general", index, "m_alice", "alice", "message", "row")
                    for index in range(1, 6)
                )
            )
            transcript = app.query_one("#transcript", TautOptionList)
            deadline = observed(app).scope.now() + 5
            transcript.focus()
            await observed(app).focus(transcript, deadline=deadline)
            transcript.action_first()
            await observed(app).highlighted(transcript, 0, deadline=deadline)
            scope = observed(app).scope
            entered = scope.expect(
                CompletionKey(app, "first_key.held", request=object())
            )
            release = scope.expect(
                CompletionKey(app, "first_key.release", request=object())
            )
            third = scope.expect(
                CompletionKey(app, "third_key.produced", request=object())
            )
            receipts: dict[int, Completion[Any]] = {}
            first_event: Any = None
            original_post = transcript.post_message
            original_dispatch = app._on_message

            def post(event: Any) -> bool:
                nonlocal first_event
                admitted = bool(original_post(event))
                if admitted and isinstance(event, TautOptionList.OptionHighlighted):
                    first_event = first_event or event
                    receipts[id(event)] = scope.expect(
                        CompletionKey(app, "key_highlight.applied", request=event)
                    )
                return admitted

            async def dispatch(event: Any) -> None:
                receipt = receipts.get(id(event))
                if receipt is None:
                    await original_dispatch(event)
                    return
                try:
                    if event is first_event:
                        entered.succeed(entered.key, None)
                        await release.wait(
                            deadline=deadline, description="release first key"
                        )
                        await original_dispatch(event)
                        # A raw key reaches this actual binding handler after
                        # bubbling. Admit the third key between old/new highlights.
                        await app._on_key(events.Key("down", None))
                        third.succeed(third.key, None)
                    else:
                        await original_dispatch(event)
                except BaseException as error:
                    receipt.fail(receipt.key, error)
                    raise
                else:
                    receipt.succeed(receipt.key, event)

            monkeypatch.setattr(transcript, "post_message", post)
            monkeypatch.setattr(app, "_on_message", dispatch)
            await app._on_key(events.Key("down", None))
            await entered.wait(deadline=deadline, description="first highlight held")
            try:
                if render_before_second:
                    app._render_messages(app._message_rows)
                await app._on_key(events.Key("down", None))
                second_index = transcript.highlighted
            finally:
                release.succeed(release.key, None)
            await third.wait(deadline=deadline, description="third key produced")
            await asyncio.gather(
                *(
                    receipt.wait(deadline=deadline, description="key highlight applied")
                    for receipt in tuple(receipts.values())
                )
            )
            assert second_index == 2, (
                "pending selection must survive render before next key"
            )
            assert transcript.highlighted == 3
            assert app.visual_state.selected_message_id == 4

    asyncio.run(exercise())


def test_queued_activation_opens_original_inspector_without_rewinding_newer_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from textual import events

    from taut.client import Message
    from taut_tui.app import TautApp
    from taut_tui.models import InspectorKind
    from taut_tui.widgets import TautOptionList

    async def exercise() -> None:
        app = TautApp(db_path=None, as_name=None, continuity_token=None)
        async with app.run_test(size=(100, 34)):
            app._render_messages(
                tuple(
                    Message("general", index, "m_alice", "alice", "message", "row")
                    for index in range(1, 4)
                )
            )
            transcript = app.query_one("#transcript", TautOptionList)
            deadline = observed(app).scope.now() + 5
            transcript.focus()
            await observed(app).focus(transcript, deadline=deadline)
            transcript.action_first()
            await observed(app).highlighted(transcript, 0, deadline=deadline)
            captured = observed(app).scope.expect(
                CompletionKey(app, "activation.held", request=object())
            )
            original_post = transcript.post_message

            def post(event: Any) -> bool:
                if isinstance(event, TautOptionList.Activated):
                    captured.succeed(captured.key, event)
                    return True
                return bool(original_post(event))

            monkeypatch.setattr(transcript, "post_message", post)
            applied = observed(app).option_activation(transcript)
            await app._on_key(events.Key("enter", None))
            event = await captured.wait(deadline=deadline, description="Enter held")
            await app._on_key(events.Key("down", None))
            await observed(app).highlighted(transcript, 1, deadline=deadline)
            monkeypatch.setattr(transcript, "post_message", original_post)
            assert original_post(event)
            await applied.wait(deadline=deadline, description="held Enter applied")
            assert app.visual_state.inspector is not None
            assert app.visual_state.inspector.kind is InspectorKind.MESSAGE
            assert app.visual_state.inspector.selected_item == "1"
            assert transcript.highlighted == 1

    asyncio.run(exercise())


def test_pending_search_anchor_survives_render_without_its_hit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from taut.client import Message
    from taut_tui.app import TautApp
    from taut_tui.widgets import TautOptionList

    async def exercise() -> None:
        app = TautApp(db_path=None, as_name=None, continuity_token=None)
        async with app.run_test(size=(100, 34)):
            transcript = app.query_one("#transcript", TautOptionList)
            original_post = transcript.post_message
            admitted_highlights: list[Any] = []

            def post(event: Any) -> bool:
                admitted = bool(original_post(event))
                if admitted and isinstance(event, TautOptionList.OptionHighlighted):
                    admitted_highlights.append(event)
                return admitted

            monkeypatch.setattr(transcript, "post_message", post)
            app._conversation_intent = 7
            app.visual_state = replace(app.visual_state, selected_message_id=42)
            app._arm_search_anchor(7, 42)
            app._render_messages(
                (Message("general", 1, "m_alice", "alice", "message", "old row"),)
            )
            assert app.visual_state.selected_message_id == 42
            assert app.visual_state.viewport.message_id == 42
            assert app.visual_state.viewport.search_owned
            assert transcript.highlighted == 0
            # Rendering synchronously projects state. It must not admit a new
            # selection producer, even if another guard would ignore it later.
            assert admitted_highlights == []

    asyncio.run(exercise())


def test_transcript_render_selects_default_and_clears_empty_selection() -> None:
    from taut.client import Message
    from taut_tui.app import TautApp
    from taut_tui.widgets import TautOptionList

    async def exercise() -> None:
        app = TautApp(db_path=None, as_name=None, continuity_token=None)
        async with app.run_test(size=(100, 34)):
            transcript = app.query_one("#transcript", TautOptionList)
            app._render_messages(
                tuple(
                    Message("general", index, "m_alice", "alice", "message", "row")
                    for index in range(1, 4)
                )
            )
            assert app.visual_state.selected_message_id == 3
            assert transcript.highlighted == 2
            app._render_messages(())
            assert app.visual_state.selected_message_id is None
            assert transcript.highlighted is None

    asyncio.run(exercise())


def test_search_context_sync_failure_invalidates_restore_owner() -> None:
    from taut.client import Message, SearchHit
    from taut_tui.app import TautApp

    error = RuntimeError("context setup failed")

    class RaisingSession:
        def open_history_context(self, *_args: object, **_kwargs: object) -> None:
            raise error

    app = TautApp(db_path=None, as_name=None, continuity_token=None)
    app._conversation_intent = 7
    app._search_hits_by_intent[7] = SearchHit(
        thread="general",
        ts=42,
        from_id="m_alice",
        from_name="alice",
        kind="message",
        text="hit",
        thread_kind="channel",
        channel="general",
        parent=None,
        members=None,
    )
    app._session = cast(Any, RaisingSession())
    future: Future[list[Message]] = Future()
    future.set_result([Message("general", 42, "m_alice", "alice", "message", "hit")])

    with pytest.raises(RuntimeError) as caught:
        app._apply_search_context(7, future)

    assert caught.value is error
    assert app.visual_state.viewport.tail_pinned is True


def test_superseding_intent_invalidates_pending_search_restore() -> None:
    from taut_tui.app import TautApp

    app = TautApp(db_path=None, as_name=None, continuity_token=None)
    app._conversation_intent = 7
    app._arm_search_anchor(7, 42)
    assert app._advance_conversation_intent() == 8
    assert app.visual_state.viewport.search_owned is False


@pytest.mark.parametrize(
    "outcome",
    ["none", "exception", "missing", "wrong-intent", "rejected"],
)
def test_pending_search_anchor_clears_when_context_cannot_apply(
    outcome: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from taut.client import Message
    from taut_tui.app import TautApp
    from taut_tui.session import ConversationSnapshot

    async def exercise() -> None:
        app = TautApp(db_path=None, as_name=None, continuity_token=None)
        async with app.run_test(size=(100, 34)):
            app._conversation_intent = 7
            app._arm_search_anchor(7, 42)
            future: Future[ConversationSnapshot | None] = Future()
            if outcome == "none":
                future.set_result(None)
            elif outcome == "exception":
                future.set_exception(RuntimeError("context failed"))
            else:
                messages = (
                    ()
                    if outcome == "missing"
                    else (
                        Message(
                            "general",
                            42,
                            "m_alice",
                            "alice",
                            "message",
                            "hit",
                        ),
                    )
                )
                future.set_result(
                    ConversationSnapshot(
                        generation=1,
                        target="general",
                        messages=messages,
                        intent_token=6 if outcome == "wrong-intent" else 7,
                    )
                )
            if outcome == "rejected":
                monkeypatch.setattr(app, "_apply_conversation", lambda _snapshot: False)
            app._apply_optional_conversation(7, future)
            assert app.visual_state.viewport.tail_pinned is True

    asyncio.run(exercise())


def test_teardown_invalidates_pending_search_restore() -> None:
    from taut_tui.app import TautApp
    from taut_tui.viewport import ViewportEffect, ViewportEffectKind

    app = TautApp(db_path=None, as_name=None, continuity_token=None)
    app._conversation_intent = 7
    app._arm_search_anchor(7, 42)
    generation = app.visual_state.viewport.generation
    app.on_unmount()
    assert app.visual_state.viewport.search_owned is False
    effect = ViewportEffect(
        generation,
        ViewportEffectKind.RESTORE,
        message_id=42,
    )
    assert app.visual_state.viewport.accepts(effect) is False


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
            send_results_applied: asyncio.Queue[int] = asyncio.Queue()
            apply_send_result = app._apply_send_result

            def observe_send_result(
                send_token: int,
                future: Future[Message],
            ) -> None:
                apply_send_result(send_token, future)
                send_results_applied.put_nowait(send_token)

            app._apply_send_result = observe_send_result  # type: ignore[method-assign]
            navigation = app.query_one("#navigation-list", TautOptionList)
            await observed(app).navigation()
            assert _has_option_containing(navigation, "#general")
            navigation.highlighted = _option_index_containing(navigation, "#general")
            navigation.focus()
            await pilot.press("enter")
            await observed(app).conversation()
            assert app.visual_state.active_conversation == "general"

            app._domain = DeferredDomain()  # type: ignore[assignment]
            composer = app.query_one("#composer", TautComposer)
            edited = observed(app).composer_edit(composer)
            deadline = observed(app).scope.now() + 5
            composer.text = "first\nbody"
            composer.cursor_position = 3
            await edited.wait(deadline=deadline, description="first draft edit applied")
            app._submit_composer("first\nbody")
            edited = observed(app).composer_edit(composer)
            deadline = observed(app).scope.now() + 5
            composer.text = "second\nbody"
            composer.cursor_position = 4
            await edited.wait(
                deadline=deadline, description="second draft edit applied"
            )
            app._submit_composer("second\nbody")
            expected = app.visual_state.draft_for("general")
            assert expected is not None

            first = alice.say("general", "first\nbody")
            sends[0].set_result(first)
            assert await asyncio.wait_for(send_results_applied.get(), timeout=5) == 1
            assert app.visual_state.draft_for("general") == expected
            assert composer.text == "second\nbody"
            assert composer.cursor_position == 4

            second = alice.say("general", "second\nbody")
            sends[1].set_result(second)
            assert await asyncio.wait_for(send_results_applied.get(), timeout=5) == 2
            assert composer.text == ""

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
            await observed(app).navigation()
            assert bool(navigation.option_count and app._reply_threads)
            navigation.highlighted = 0
            navigation.focus()
            await pilot.press("enter")
            await observed(app).conversation()
            assert app.visual_state.active_conversation == "general"

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
            await observed(app).conversation()
            assert app.visual_state.open_reply_thread is not None

            deadline = observed(app).scope.now() + 5
            assert await pilot.click("#reply-affordance") is True
            await observed(app).conversation(deadline=deadline)
            await observed(app).focus(transcript, deadline=deadline)
            assert app.visual_state.open_reply_thread is None
            assert app.visual_state.focus.surface is LogicalSurface.CONVERSATION
            assert app.visual_state.pane_choice is LogicalSurface.CONVERSATION
            assert transcript.has_focus

    try:
        asyncio.run(exercise())
    finally:
        alice.close()
        bob.close()


def test_transcript_preserves_whitespace_and_adds_message_gap() -> None:
    from taut.client import Message
    from taut.terminal import format_message_time
    from taut_tui.app import TautApp
    from taut_tui.widgets import TautOptionList

    messages = (
        Message(
            "general",
            1,
            "m_alice",
            "alice",
            "message",
            "a\tb\n\n  third  ",
        ),
        Message(
            "general",
            2,
            "m_bob",
            "bob",
            "message",
            r"literal\n\t",
        ),
    )

    async def exercise() -> None:
        app = TautApp(db_path=None, as_name=None, continuity_token=None)
        async with app.run_test(size=(100, 34)):
            app._render_messages(messages)
            transcript = app.query_one("#transcript", TautOptionList)
            first = str(transcript.get_option_at_index(0).prompt)
            second = str(transcript.get_option_at_index(1).prompt)

            assert first == f"{format_message_time(1)}  alice  a   b\n\n  third  \n"
            # [TUI-5.3] (2026-08-18): literal escapes decode toward sender
            # intent — the body's \n becomes a break and \t a tab stop.
            assert second == f"{format_message_time(2)}  bob  literal\n    \n"
            assert transcript.option_count == len(app._message_rows) == 2
            assert app._message_rows[1] is messages[1]
            assert app._message_row_height(messages[0], 100) == 4

    asyncio.run(exercise())


@pytest.mark.parametrize(
    ("mode", "shows_time"),
    [
        (LayoutMode.WIDE, True),
        (LayoutMode.MEDIUM, True),
        (LayoutMode.COMPACT, True),
        (LayoutMode.TOO_SMALL, False),
    ],
)
def test_transcript_uses_core_time_and_never_exposes_message_id(
    mode: LayoutMode,
    shows_time: bool,
) -> None:
    from taut.client import Message
    from taut.terminal import format_message_time
    from taut_tui.app import TautApp

    message_id = 1_723_400_002_000_000_000
    app = TautApp(db_path=None, as_name=None, continuity_token=None)
    app.layout_mode = mode

    row = str(
        app._message_prompt(
            Message("general", message_id, "m_alice", "alice", "message", "body")
        )
    )

    assert (format_message_time(message_id) in row) is shows_time
    assert str(message_id) not in row


@pytest.mark.parametrize("mode", [LayoutMode.WIDE, LayoutMode.MEDIUM])
def test_transcript_wraps_wide_and_medium_bodies_with_hanging_indent(
    mode: LayoutMode,
) -> None:
    """[TUI-5.3]: wrapped bodies stay aligned under their first body cell."""
    from taut.client import Message
    from taut.terminal import format_message_time
    from taut_tui.app import TautApp

    message = Message(
        "general",
        1,
        "m_alice",
        "alice",
        "message",
        "one two three four five",
    )
    app = TautApp(db_path=None, as_name=None, continuity_token=None)
    app.layout_mode = mode

    lines = app._message_prompt(message).wrap(app.console, 24)

    assert [str(line).rstrip() for line in lines] == [
        f"{format_message_time(1)}  alice  one two",
        "              three four",
        "              five",
        "",
    ]
    assert app._message_row_height(message, 24) == len(lines)


def test_transcript_compact_metadata_stacks_without_body_indent() -> None:
    """[TUI-5.3]: compact metadata owns its line and body uses full width."""
    from taut.client import Message
    from taut.terminal import format_message_time
    from taut_tui.app import TautApp

    message = Message(
        "general",
        1,
        "m_alice",
        "alice",
        "message",
        "one two three four five",
    )
    app = TautApp(db_path=None, as_name=None, continuity_token=None)
    app.layout_mode = LayoutMode.COMPACT

    lines = app._message_prompt(message).wrap(app.console, 14)

    assert [str(line).rstrip() for line in lines] == [
        f"alice  {format_message_time(1)}",
        "one two three",
        "four five",
        "",
    ]


def test_transcript_option_render_keeps_hanging_indent_and_height_in_sync() -> None:
    """[TUI-5.3]: Textual renders and measures the owned hanging prompt."""
    from taut.client import Message
    from taut.terminal import format_message_time
    from taut_tui.app import TautApp
    from taut_tui.widgets import TautOptionList

    message = Message(
        "general",
        1,
        "m_alice",
        "alice",
        "message",
        "word " * 30,
    )

    async def exercise() -> None:
        app = TautApp(db_path=None, as_name=None, continuity_token=None)
        async with app.run_test(size=(80, 34)):
            app._render_messages((message,))
            await observed(app).viewport()
            transcript = app.query_one("#transcript", TautOptionList)
            option = transcript.get_option_at_index(0)
            strips = transcript._get_option_render(
                option,
                transcript.get_visual_style("option-list--option"),
            )

            rendered_lines = [strip.text.rstrip() for strip in strips]
            metadata = f"{format_message_time(1)}  alice  "
            assert rendered_lines[0].startswith(f"{metadata}word")
            assert all(
                line.startswith(" " * len(metadata)) for line in rendered_lines[1:-1]
            )
            assert rendered_lines[-1] == ""
            assert app._message_row_height(
                message,
                transcript.scrollable_content_region.width,
            ) == len(strips)

    asyncio.run(exercise())


def test_message_body_structure_does_not_widen_metadata_controls() -> None:
    from taut.client import Message
    from taut.terminal import format_message_time
    from taut_tui.app import TautApp
    from taut_tui.session import ConversationSnapshot
    from taut_tui.widgets import TautOptionList

    message = Message(
        "general",
        1,
        "m_alice",
        "ali\nce\tname",
        "message",
        "body\nnext\tcolumn",
    )
    snapshot = ConversationSnapshot(
        generation=1,
        target="general",
        messages=(message,),
        reply_thread="root\nthread\tlabel",
        reply_messages=(message,),
    )

    async def exercise() -> None:
        app = TautApp(db_path=None, as_name=None, continuity_token=None)
        async with app.run_test(size=(100, 34)):
            app._render_messages((message,))
            transcript = str(
                app.query_one("#transcript", TautOptionList)
                .get_option_at_index(0)
                .prompt
            )
            assert transcript.startswith(
                f"{format_message_time(1)}  " + r"ali\nce\tname  body" + "\n"
            )
            assert "next    column\n" in transcript

            app._message_rows = (message,)
            app._select_message(0)
            selected = str(app.query_one("#inspector-body").render())
            assert selected.startswith(r"ali\nce\tname  1" + "\n")
            assert "body\nnext    column" in selected

            app._render_reply_inspector(snapshot)
            replies = str(app.query_one("#inspector-body").render())
            assert replies.startswith(r"Replies to root\nthread\tlabel" + "\n")
            assert r"1  ali\nce\tname  " in replies
            assert "body\nnext    column" in replies

    asyncio.run(exercise())


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
            assert_safe(app.query_one("#composer", TautComposer).placeholder)
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


# --- Slice 4 of docs/plans/2026-08-18-tui-deep-review-remediation-plan.md ---


def test_programmatic_draft_restore_never_promotes(tmp_path: Path) -> None:
    """[TUI-7.1] only direct user editing promotes a leading-colon draft."""

    from taut_tui.app import TautApp
    from taut_tui.screens import CommandLineScreen
    from taut_tui.widgets import TautComposer, TautOptionList

    db_path = tmp_path / "promote.db"
    TautClient.init(db_path=db_path)
    seeder = TautClient(db_path=db_path, as_name="van")
    seeder.join("general")
    seeder.join("quiet")
    seeder.close()

    async def open_target(app: Any, pilot: Any, target: str) -> None:
        navigation = app.query_one("#navigation-list", TautOptionList)
        index = next(i for i, t in enumerate(app._navigation_targets) if t == target)
        navigation.highlighted = index
        opened = observed(app).opening()
        navigation.action_select()
        await observed(app).conversation(opened)
        assert app.visual_state.active_conversation == target

    async def exercise() -> None:
        app = TautApp(db_path=str(db_path), as_name="van", continuity_token=None)
        async with app.run_test(size=(130, 34)) as pilot:
            await observed(app).navigation()
            assert app._navigation_targets
            await open_target(app, pilot, "general")
            await pilot.press("i")
            promoted = observed(app).command_line()
            for character in ":summon kimi":
                await pilot.press("space" if character == " " else character)
            screen = await observed(app).pushed(promoted)
            assert isinstance(app.screen, CommandLineScreen)
            deadline = observed(app).scope.now() + 5
            await pilot.press("escape")
            await (
                observed(app)
                .screens.result_applied(screen)
                .wait(deadline=deadline, description="promoted command result applied")
            )
            await (
                observed(app)
                .screens.retired(screen)
                .wait(deadline=deadline, description="promoted command screen retired")
            )
            composer = app.query_one("#composer", TautComposer)
            assert composer.text.startswith(":summon")
            await pilot.press("escape")
            await open_target(app, pilot, "quiet")
            await open_target(app, pilot, "general")
            assert not isinstance(app.screen, CommandLineScreen)
            assert composer.text.startswith(":summon")

    asyncio.run(exercise())


def test_command_line_open_keeps_live_deliveries_rendering(
    tmp_path: Path,
) -> None:
    """[TUI-7.1] the command line owns focus but never blocks the live view."""

    from taut_tui.app import TautApp
    from taut_tui.screens import CommandLineScreen
    from taut_tui.widgets import TautOptionList

    db_path = tmp_path / "live.db"
    TautClient.init(db_path=db_path)
    alice = TautClient(db_path=db_path, as_name="alice")
    bob = TautClient(db_path=db_path, as_name="bob")
    for client in (alice, bob):
        client.join("general")

    async def exercise() -> None:
        app = TautApp(db_path=str(db_path), as_name="alice", continuity_token=None)
        async with app.run_test(size=(130, 34)) as pilot:
            await observed(app).navigation()
            assert app._navigation_targets
            navigation = app.query_one("#navigation-list", TautOptionList)
            index = next(
                i for i, t in enumerate(app._navigation_targets) if t == "general"
            )
            navigation.highlighted = index
            opened = observed(app).opening()
            navigation.action_select()
            await observed(app).conversation(opened)
            assert app.visual_state.active_conversation == "general"
            transcript = app.query_one("#transcript", TautOptionList)
            baseline = transcript.option_count
            pushed = observed(app).command_line()
            await pilot.press("escape", "colon")
            await observed(app).pushed(pushed)
            assert isinstance(app.screen, CommandLineScreen)
            deadline = observed(app).scope.now() + 5
            message = bob.say("general", "delivered while the command line is open")
            await observed(app).delivery(message, deadline=deadline)
            assert transcript.option_count > baseline
            assert isinstance(app.screen, CommandLineScreen)

    asyncio.run(exercise())
    alice.close()
    bob.close()


def test_rapid_resize_setup_selection_survives_prior_user_highlight(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from _completion import CompletionKey

    from taut_tui.app import TautApp
    from taut_tui.widgets import TautOptionList

    path = tmp_path / "held-initial-highlight.db"
    TautClient.init(db_path=path)
    client = TautClient(db_path=path, as_name="alice")
    client.join("general")
    for index in range(24):
        client.say("general", f"seed {index}")
    client.close()

    async def exercise() -> None:
        app = TautApp(db_path=str(path), as_name="alice", continuity_token=None)
        async with app.run_test(size=(130, 34)):
            await observed(app).navigation()
            transcript = app.query_one("#transcript", TautOptionList)
            original_post = transcript.post_message
            held: list[Any] = []
            trace: list[tuple[Any, ...]] = []

            def post(event: Any) -> bool:
                if isinstance(event, TautOptionList.OptionHighlighted):
                    held.append(event)
                    trace.append(
                        (
                            "held",
                            event.option_index,
                            app.visual_state.selected_message_id,
                        )
                    )
                    return True
                return bool(original_post(event))

            navigation = app.query_one("#navigation-list", TautOptionList)
            navigation.highlighted = app._navigation_targets.index("general")
            opened = observed(app).opening()
            navigation.action_select()
            await observed(app).conversation(opened)
            await observed(app).viewport()
            monkeypatch.setattr(transcript, "post_message", post)
            transcript.action_first()
            assert held
            selected = app._message_rows[5].ts
            last = held[-1]
            applied = observed(app).scope.expect(
                CompletionKey(app, "prior_user_highlight.applied", request=last)
            )
            original_dispatch = app._on_message

            async def dispatch(event: Any) -> None:
                await original_dispatch(event)
                if event is last:
                    trace.append(
                        (
                            "prior_user_applied",
                            event.option_index,
                            app.visual_state.selected_message_id,
                        )
                    )
                    applied.succeed(applied.key, event)

            monkeypatch.setattr(app, "_on_message", dispatch)
            monkeypatch.setattr(transcript, "post_message", original_post)
            deadline = observed(app).scope.now() + 5
            for event in held:
                original_post(event)
            await _activate_transcript_message(app, transcript, 5)
            await applied.wait(
                deadline=deadline, description="prior user highlight applied"
            )
            trace.append(
                (
                    "released",
                    transcript.highlighted,
                    app.visual_state.selected_message_id,
                )
            )
            assert app.visual_state.selected_message_id == selected, trace

    asyncio.run(exercise())


def test_transcript_activation_observer_preserves_the_real_handler_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from taut.client import Message
    from taut_tui.app import TautApp
    from taut_tui.widgets import TautOptionList

    error = RuntimeError("controlled selection handler failure")

    async def exercise() -> None:
        app = TautApp(db_path=None, as_name=None, continuity_token=None)
        async with app.run_test(size=(130, 34)):
            transcript = app.query_one("#transcript", TautOptionList)
            app._render_messages(
                (Message("general", 1, "m_alice", "alice", "message", "row"),)
            )
            await observed(app).viewport()
            original_post = transcript.post_message
            arrived: asyncio.Future[Any] = asyncio.get_running_loop().create_future()

            def hold(event: Any) -> bool:
                if isinstance(event, TautOptionList.Activated):
                    arrived.set_result(event)
                    return True
                return bool(original_post(event))

            monkeypatch.setattr(transcript, "post_message", hold)
            applied = observed(app).option_activation(transcript)
            deadline = observed(app).scope.now() + 5
            transcript.action_select()
            event = await asyncio.wait_for(arrived, 5)

            def fail(_index: int) -> None:
                raise error

            monkeypatch.setattr(app, "_select_message", fail)
            with pytest.raises(RuntimeError) as dispatched:
                await app._on_message(event)
            assert dispatched.value is error
            with pytest.raises(RuntimeError) as observed_error:
                await applied.wait(
                    deadline=deadline, description="selection handler error"
                )
            assert observed_error.value is error

    asyncio.run(exercise())


@pytest.mark.parametrize("producer", ("setup-helper", "single-click"))
def test_rapid_resize_setup_selection_survives_resize_render_after_activation_post(
    producer: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from taut_tui.app import TautApp
    from taut_tui.widgets import TautOptionList

    path = tmp_path / "late-initial-resize-highlight.db"
    TautClient.init(db_path=path)
    client = TautClient(db_path=path, as_name="alice")
    client.join("general")
    for index in range(24):
        client.say("general", f"seed {index}")
    client.close()

    async def exercise() -> None:
        app = TautApp(db_path=str(path), as_name="alice", continuity_token=None)
        resize = _ResizeAfterTranscriptActivation(app, monkeypatch)
        async with app.run_test(size=(130, 34)) as pilot:
            await observed(app).navigation()
            navigation = app.query_one("#navigation-list", TautOptionList)
            navigation.highlighted = app._navigation_targets.index("general")
            opened = observed(app).opening()
            navigation.action_select()
            await observed(app).conversation(opened)
            await observed(app).viewport()
            transcript = app.query_one("#transcript", TautOptionList)
            selected = app._message_rows[5].ts
            if producer == "single-click":
                transcript.focus()
                await pilot.press("home")
            resize.arm(transcript)
            deadline = observed(app).scope.now() + 5
            if producer == "setup-helper":
                await _activate_transcript_message(app, transcript, 5)
            else:
                assert await pilot.click(
                    transcript, offset=(5, transcript._index_to_line[5] + 1)
                )
            await resize.settled(deadline=deadline)
            assert app.visual_state.selected_message_id == selected
            assert transcript.highlighted == 5

    asyncio.run(exercise())


def test_real_rapid_resize_burst_keeps_latest_state_and_live_delivery(
    tmp_path: Path,
) -> None:
    """[TUI-9.2]/[TUI-13.2]: real resize and watcher callbacks are latest-wins."""

    from taut_tui.app import TautApp
    from taut_tui.models import LayoutMode, TerminalSize
    from taut_tui.widgets import TautComposer, TautOptionList

    db_path = tmp_path / "rapid-resize-live.db"
    TautClient.init(db_path=db_path)
    alice = TautClient(db_path=db_path, as_name="alice")
    bob = TautClient(db_path=db_path, as_name="bob")
    for client in (alice, bob):
        client.join("general")
    for index in range(24):
        alice.say("general", f"seed {index:02d} " + "wrapped row " * 5)

    async def exercise() -> None:
        app = TautApp(db_path=str(db_path), as_name="alice", continuity_token=None)
        async with app.run_test(size=(130, 34)) as pilot:
            await observed(app).navigation()
            assert "general" in app._navigation_targets
            navigation = app.query_one("#navigation-list", TautOptionList)
            navigation.highlighted = app._navigation_targets.index("general")
            opened = observed(app).opening()
            navigation.action_select()
            await observed(app).conversation(opened)
            assert app.visual_state.active_conversation == "general"
            transcript = app.query_one("#transcript", TautOptionList)
            assert transcript.option_count >= 24
            await observed(app).viewport()
            selected = app._message_rows[5].ts
            await _activate_transcript_message(app, transcript, 5)
            assert app.visual_state.inspector is not None
            assert app.visual_state.selected_message_id == selected
            # Selecting a real row scrolls it into view. Establish the intended
            # tail geometry synchronously before capturing that viewport owner.
            transcript.scroll_end(animate=False, force=True, immediate=True)
            app._capture_settled_transcript_viewport()
            await pilot.press("i")
            composer = app.query_one("#composer", TautComposer)
            edited = observed(app).composer_edit(composer)
            deadline = observed(app).scope.now() + 5
            composer.text = "draft survives resize burst"
            await edited.wait(
                deadline=deadline, description="resize-burst draft applied"
            )

            async def resize_burst() -> None:
                for size in ((119, 24), (79, 24), (49, 24), (80, 24)):
                    await pilot.resize_terminal(*size)

            async def worker_result() -> None:
                domain = app._domain
                assert domain is not None
                result = observed(app).action("show_identity")
                deadline = observed(app).scope.now() + 5
                app._run_action(domain.show_identity())
                await result.wait(deadline)
                assert app._operation_state == "idle"

            deadline = observed(app).scope.now() + 5
            _resized, message, _shown = await asyncio.gather(
                resize_burst(),
                asyncio.to_thread(bob.say, "general", "delivery during resize burst"),
                worker_result(),
            )
            await observed(app).delivery(message, deadline=deadline)
            assert any(
                message.text == "delivery during resize burst"
                for message in app._message_rows
            )
            await observed(app).resize_render(deadline=deadline)
            await observed(app).viewport()
            assert transcript.is_vertical_scroll_end

            assert app._accepted_size == TerminalSize(80, 24)
            assert app.layout_mode is LayoutMode.MEDIUM
            assert app.visual_state.active_conversation == "general"
            assert app.visual_state.selected_message_id == selected
            assert app.visual_state.inspector is not None
            draft = app.visual_state.draft_for("general")
            assert draft is not None and draft.text == "draft survives resize burst"
            assert app.visual_state.viewport.tail_pinned is True
            assert transcript.is_vertical_scroll_end is True
            accepted = app._accepted_size
            generation = app.visual_state.model_generation
            # A negative late-work window, not a completion proof: the latest
            # resize callback and its real viewport effect have already returned.
            await pilot.pause(0.2)
            assert app._accepted_size == accepted
            assert app.visual_state.model_generation == generation

    try:
        asyncio.run(exercise())
    finally:
        alice.close()
        bob.close()


def test_tail_pin_survives_own_send_and_watcher_delivery(tmp_path: Path) -> None:
    """[TUI-6.2]/[TUI-9.2]: both append paths retain sticky tail ownership."""

    from taut_tui.app import TautApp
    from taut_tui.widgets import TautComposer, TautOptionList

    db_path = tmp_path / "sticky-tail.db"
    TautClient.init(db_path=db_path)
    alice = TautClient(db_path=db_path, as_name="alice")
    bob = TautClient(db_path=db_path, as_name="bob")
    for client in (alice, bob):
        client.join("general")
    for index in range(24):
        alice.say("general", f"seed {index:02d} " + "wrapped row " * 5)

    async def exercise() -> None:
        app = TautApp(db_path=str(db_path), as_name="alice", continuity_token=None)
        async with app.run_test(size=(100, 24)) as pilot:
            await observed(app).navigation()
            assert "general" in app._navigation_targets
            navigation = app.query_one("#navigation-list", TautOptionList)
            navigation.highlighted = app._navigation_targets.index("general")
            opened = observed(app).opening()
            navigation.action_select()
            await observed(app).conversation(opened)
            assert len(app._message_rows) >= 24
            transcript = app.query_one("#transcript", TautOptionList)
            await observed(app).viewport()
            assert transcript.is_vertical_scroll_end
            assert app.visual_state.viewport.tail_pinned is True

            await pilot.press("i")
            composer = app.query_one("#composer", TautComposer)
            composer.text = "own send keeps tail"
            await pilot.press("enter")
            await observed(app).send()
            assert any(
                message.text == "own send keeps tail" for message in app._message_rows
            )
            await observed(app).viewport()
            assert transcript.is_vertical_scroll_end
            assert app.visual_state.viewport.tail_pinned is True

            deadline = observed(app).scope.now() + 5
            message = await asyncio.to_thread(bob.say, "general", "watcher keeps tail")
            await observed(app).delivery(message, deadline=deadline)
            assert any(
                message.text == "watcher keeps tail" for message in app._message_rows
            )
            await observed(app).viewport()
            assert transcript.is_vertical_scroll_end
            assert app.visual_state.viewport.tail_pinned is True

    try:
        asyncio.run(exercise())
    finally:
        alice.close()
        bob.close()


def test_viewport_completion_rejects_a_newer_user_owner_even_if_both_are_tail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from _completion import CompletionSuperseded

    from taut.client import Message
    from taut_tui.app import TautApp

    async def exercise() -> None:
        app = TautApp(db_path=None, as_name=None, continuity_token=None)
        async with app.run_test(size=(100, 24)):
            messages = (Message("general", 1, "m_alice", "alice", "message", "row"),)
            held: list[Any] = []
            reached = asyncio.Event()
            real_tail = app._reapply_tail_effect

            def hold(effect: Any) -> None:
                held.append(effect)
                reached.set()

            monkeypatch.setattr(app, "_reapply_tail_effect", hold)
            app._render_messages(messages)
            await asyncio.wait_for(reached.wait(), 5)
            pending = asyncio.create_task(observed(app).viewport())
            fence = asyncio.get_running_loop().create_future()
            asyncio.get_running_loop().call_soon(fence.set_result, None)
            await fence

            app._on_transcript_user_viewport_intent()
            assert app.visual_state.viewport.tail_pinned
            reached.clear()
            app._render_messages(messages)
            await asyncio.wait_for(reached.wait(), 5)
            real_tail(held[-1])
            with pytest.raises(CompletionSuperseded):
                await pending

    asyncio.run(exercise())


def test_navigation_budget_starts_at_session_handoff_not_app_construction(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import _app_completion
    from _completion import CompletionScope

    from taut_tui.app import TautApp

    now = [0.0]
    monkeypatch.setattr(
        _app_completion,
        "CompletionScope",
        lambda: CompletionScope(clock=lambda: now[0]),
    )
    path = tmp_path / "late-bootstrap.db"
    TautClient.init(db_path=path)
    client = TautClient(db_path=path, as_name="alice")
    client.join("general")
    client.close()

    async def exercise() -> None:
        app = TautApp(db_path=str(path), as_name="alice", continuity_token=None)
        now[0] = 20.0
        async with app.run_test():
            await observed(app).navigation()
            assert "general" in app._navigation_targets
            observer = observed(app)
            assert observer.navigation_deadline == 25.0
            assert observer._navigation_applied is not None
            assert (
                observer._navigation_applied.key.request is observer.navigation_future
            )
            assert observer.navigation_source is not None
            assert observer.navigation_source.key.request is observer.navigation_future

    asyncio.run(exercise())


def test_action_screen_observer_ignores_an_unrelated_push(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import _app_completion
    from _completion import CompletionScope

    from taut_tui.actions import ActionId
    from taut_tui.app import TautApp
    from taut_tui.screens import ConfirmationScreen, NativeFormScreen

    now = [0.0]
    monkeypatch.setattr(
        _app_completion,
        "CompletionScope",
        lambda: CompletionScope(clock=lambda: now[0]),
    )

    async def exercise() -> None:
        app = TautApp(db_path=None, as_name=None, continuity_token=None)
        async with app.run_test():
            requested = observed(app).screen_for_action(ActionId.IDENTITY_SET_PERSONA)
            unrelated = ConfirmationScreen("Unrelated")
            app.push_screen(unrelated)
            assert requested.snapshot() is None
            now[0] = 20.0
            app._open_native_form(ActionId.IDENTITY_SET_PERSONA)
            screen = await observed(app).pushed(requested, focus="#field-persona")
            assert observed(app)._screen_started[requested] == 20.0
            assert isinstance(screen, NativeFormScreen)
            assert screen is not unrelated

    asyncio.run(exercise())


@pytest.mark.parametrize("cancelled", [False, True])
def test_navigation_ui_apply_retains_exact_source_error_or_cancellation(
    monkeypatch: pytest.MonkeyPatch,
    cancelled: bool,
) -> None:
    from _completion import CompletionStatus

    from taut_tui.app import TautApp
    from taut_tui.session import TuiSession

    source: Future[Any] = Future()
    error = ValueError("controlled navigation source failure")
    if cancelled:
        source.cancel()
    else:
        source.set_exception(error)
    monkeypatch.setattr(TuiSession, "refresh_navigation", lambda _session: source)

    async def exercise() -> None:
        app = TautApp(db_path=None, as_name=None, continuity_token=None)
        async with app.run_test():
            await observed(app).navigation()
            retained = observed(app).navigation_source
            assert retained is not None and retained.key.request is source
            outcome = retained.snapshot()
            assert outcome is not None
            if cancelled:
                assert outcome.status is CompletionStatus.CANCELLED
            else:
                assert outcome.status is CompletionStatus.ERROR
                assert outcome.error is error

    asyncio.run(exercise())


@pytest.mark.parametrize("phase", ["focus", "highlight"])
def test_app_observer_does_not_credit_a_message_already_in_flight(
    monkeypatch: pytest.MonkeyPatch,
    phase: str,
) -> None:
    from textual import events

    from taut.client import Message
    from taut_tui.app import TautApp
    from taut_tui.widgets import TautOptionList

    async def fence() -> None:
        done = asyncio.get_running_loop().create_future()
        asyncio.get_running_loop().call_soon(done.set_result, None)
        await done

    async def exercise() -> None:
        app = TautApp(db_path=None, as_name=None, continuity_token=None)
        async with app.run_test():
            observer = observed(app)
            widget: Any
            old: Any
            if phase == "focus":
                widget = app.query_one("#composer", TautComposer)
                old = events.DescendantFocus(widget)
            else:
                widget = app.query_one("#transcript", TautOptionList)
                app._message_rows = tuple(
                    Message("general", ts, "m_alice", "alice", "message", "row")
                    for ts in (1, 2)
                )
                widget.add_options(["one", "two"])
                deadline = observer.scope.now() + 5
                widget.highlighted = 1
                await observer.highlighted(widget, 1, deadline=deadline)
                old = TautOptionList.OptionHighlighted(
                    widget, widget.get_option_at_index(0), 0
                )
            entered, release = asyncio.Event(), asyncio.Event()
            original = observer._original_message

            async def blocked(event: Any) -> None:
                if event is old:
                    entered.set()
                    await release.wait()
                await original(event)

            monkeypatch.setattr(observer, "_original_message", blocked)
            old_dispatch = asyncio.create_task(observer._observe_on_message(old))
            await asyncio.wait_for(entered.wait(), 5)
            waiting = asyncio.create_task(
                observer.focus(widget, deadline=observer.scope.now() + 5)
                if phase == "focus"
                else observer.highlighted(widget, 0, deadline=observer.scope.now() + 5)
            )
            await fence()
            record = (
                observer._focus_waiters[widget]
                if phase == "focus"
                else observer._highlight_waiters[(widget, 0)]
            )
            release.set()
            await old_dispatch
            assert record.snapshot() is None
            if phase == "focus":
                widget.focus()
            else:
                widget.highlighted = 0
            await waiting

    asyncio.run(exercise())


def test_focus_wait_uses_retained_publication_time_not_later_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import _app_completion
    from _completion import CompletionScope, CompletionTimeout

    from taut_tui.app import TautApp

    now = [0.0]
    monkeypatch.setattr(
        _app_completion,
        "CompletionScope",
        lambda: CompletionScope(clock=lambda: now[0]),
    )

    async def exercise() -> None:
        app = TautApp(db_path=None, as_name=None, continuity_token=None)
        async with app.run_test():
            composer = app.query_one("#composer", TautComposer)
            deadline = observed(app).scope.now() + 5
            now[0] = 6.0
            composer.focus()
            # An independent later observer proves the real handler returned.
            await observed(app).focus(composer, deadline=11.0)
            assert composer.has_focus
            with pytest.raises(CompletionTimeout):
                await observed(app).focus(composer, deadline=deadline)

    asyncio.run(exercise())


def test_action_browser_and_command_line_are_named_distinctly() -> None:
    from taut_tui.app import TautApp
    from taut_tui.widgets import TautButton

    async def exercise() -> None:
        app = TautApp(db_path=None, as_name=None, continuity_token=None)
        async with app.run_test(size=(130, 34)) as pilot:
            # run_test has completed the root mount before yielding.
            button = app.query_one("#commands-affordance", TautButton)
            assert "Actions" in str(button.label)
            await pilot.press("f1")
            # press awaits the real key dispatch; inspector projection is sync.
            help_text = str(app.query_one("#inspector-body").render())
            assert "command line" in help_text
            assert "action browser" in help_text

    asyncio.run(exercise())


# --- Slice 5 of docs/plans/2026-08-18-tui-deep-review-remediation-plan.md ---


def test_history_anchor_rerender_preserves_selected_message() -> None:
    """[TUI-5.3]/[TUI-6]: scroll restoration must not rewrite selection."""

    from dataclasses import replace as dc_replace

    from taut.client import Message
    from taut_tui.app import TautApp
    from taut_tui.viewport import TranscriptViewport

    messages = tuple(
        Message("general", ts, "m_alice", "alice", "message", f"row {ts}")
        for ts in range(1, 8)
    )

    async def exercise() -> None:
        app = TautApp(db_path=None, as_name=None, continuity_token=None)
        async with app.run_test(size=(100, 34)):
            app.visual_state = dc_replace(
                app.visual_state,
                selected_message_id=5,
                viewport=TranscriptViewport.history(2),
            )
            app._render_messages(messages)
            await observed(app).viewport()
            assert app.visual_state.selected_message_id == 5

    asyncio.run(exercise())


def test_too_small_shield_clears_even_when_covered_by_a_modal() -> None:
    from taut_tui.app import TautApp, TerminalTooSmallScreen
    from taut_tui.screens import ConfirmationScreen

    async def exercise() -> None:
        app = TautApp(db_path=None, as_name=None, continuity_token=None)
        async with app.run_test(size=(100, 34)) as pilot:
            deadline = observed(app).scope.now() + 5
            await pilot.resize_terminal(40, 10)
            await observed(app).screens.ready(app.screen, deadline=deadline)
            assert isinstance(app.screen, TerminalTooSmallScreen)
            shield = app.screen
            deadline = observed(app).scope.now() + 5
            app.push_screen(ConfirmationScreen("Keep working?"))
            await observed(app).screens.ready(app.screen, deadline=deadline)
            assert isinstance(app.screen, ConfirmationScreen)
            await pilot.resize_terminal(100, 34)
            # resize_terminal returns after actual Resize message dispatch.
            assert isinstance(app.screen, ConfirmationScreen)
            modal = app.screen
            deadline = observed(app).scope.now() + 5
            app.screen.action_reject()
            await (
                observed(app)
                .screens.retired(modal)
                .wait(deadline=deadline, description="covering modal retired")
            )
            await (
                observed(app)
                .screens.retired(shield)
                .wait(deadline=deadline, description="size shield retired")
            )
            assert not any(
                isinstance(screen, TerminalTooSmallScreen)
                for screen in app.screen_stack
            )

    asyncio.run(exercise())


def test_reply_form_with_vanished_selection_stays_recoverable() -> None:
    from taut_tui.actions import ActionId
    from taut_tui.app import TautApp
    from taut_tui.forms import FORM_SPECS
    from taut_tui.screens import NativeFormScreen
    from taut_tui.widgets import TautButton

    async def exercise() -> None:
        app = TautApp(db_path=None, as_name=None, continuity_token=None)
        async with app.run_test(size=(100, 34)):
            screen = NativeFormScreen(FORM_SPECS[ActionId.MESSAGE_REPLY])
            deadline = observed(app).scope.now() + 5
            app.push_screen(screen)
            await observed(app).screens.ready(screen, deadline=deadline)
            field = screen.query_one("#field-message", Input)
            edited = observed(app).input_edit(field)
            deadline = observed(app).scope.now() + 5
            field.value = "orphaned reply"
            await edited.wait(deadline=deadline, description="reply form edit applied")
            # Selection vanished between opening the form and submitting.
            submitted = observed(app).form_submission(screen)
            deadline = observed(app).scope.now() + 5
            screen._submit()
            await submitted.wait(
                deadline=deadline, description="vanished reply selection refused"
            )
            submit = screen.query_one("#form-submit", TautButton)
            assert submit.disabled is False
            errors = str(screen.query_one("#form-errors").render())
            assert "Select a message" in errors
            deadline = observed(app).scope.now() + 5
            screen.action_cancel()
            await (
                observed(app)
                .screens.retired(screen)
                .wait(deadline=deadline, description="recoverable reply form retired")
            )
            assert not isinstance(app.screen, NativeFormScreen)

    asyncio.run(exercise())


def test_unselected_composer_draft_carries_into_first_conversation(
    tmp_path: Path,
) -> None:
    from taut_tui.app import TautApp
    from taut_tui.widgets import TautComposer, TautOptionList

    db_path = tmp_path / "draft-carry.db"
    TautClient.init(db_path=db_path)
    seeder = TautClient(db_path=db_path, as_name="van")
    seeder.join("general")
    seeder.close()

    async def exercise() -> None:
        app = TautApp(db_path=str(db_path), as_name="van", continuity_token=None)
        async with app.run_test(size=(130, 34)) as pilot:
            await observed(app).navigation()
            assert app._navigation_targets
            composer = app.query_one("#composer", TautComposer)
            deadline = observed(app).scope.now() + 5
            composer.focus()
            await observed(app).focus(composer, deadline=deadline)
            await pilot.press(*"hello there")
            # press has dispatched each Changed event before returning.
            assert app.visual_state.active_conversation is None
            navigation = app.query_one("#navigation-list", TautOptionList)
            index = next(
                i for i, t in enumerate(app._navigation_targets) if t == "general"
            )
            navigation.highlighted = index
            opened = observed(app).opening()
            navigation.action_select()
            await observed(app).conversation(opened)
            assert app.visual_state.active_conversation == "general"
            assert composer.text == "hello there"

    asyncio.run(exercise())


# -- Slice 6 of docs/plans/2026-08-18-tui-deep-review-remediation-plan.md --


@pytest.mark.parametrize(
    "error",
    [
        pytest.param("busy", id="known-operation-conflict"),
        pytest.param("backend", id="arbitrary-domain-failure"),
    ],
)
def test_dump_submission_failure_stays_recoverable(
    tmp_path: Path,
    error: str,
) -> None:
    """[TUI-12.1] any synchronous dump refusal renders instead of crashing."""

    from taut_tui.app import TautApp
    from taut_tui.system import OperationAlreadyRunning

    class BusyDomain:
        def dump(self, output: Path, *, replace_confirmed: bool = False) -> None:
            if error == "busy":
                raise OperationAlreadyRunning("a workspace dump is already running")
            raise RuntimeError("backend refused dump submission")

    async def exercise() -> None:
        app = TautApp(db_path=None, as_name=None, continuity_token=None)
        async with app.run_test(size=(100, 34)):
            app._run_command_dump(cast(Any, BusyDomain()), tmp_path / "dump.tar")
            # Synchronous submission failure projects its error before return.
            assert app.is_running
            inspector = str(app.query_one("#inspector-body").render())
            expected = "already running" if error == "busy" else "backend refused"
            assert expected in inspector

    asyncio.run(exercise())


def test_delivery_during_teardown_is_rejected_without_raising() -> None:
    from taut.client import Message
    from taut_tui.app import TautApp
    from taut_tui.session import ConversationSnapshot

    async def exercise() -> None:
        app = TautApp(db_path=None, as_name=None, continuity_token=None)
        async with app.run_test(size=(100, 34)):
            app._shutting_down = True
            item = Message("general", 1, "m_bob", "bob", "message", "late")
            assert app._apply_delivery(0, item) is False

            app._shutting_down = False

            class DetachedScreen:
                is_attached = False

                def query_one(self, *args: object) -> object:
                    raise AssertionError("detached screen must not be queried")

            app._base_screen = DetachedScreen()
            assert app._apply_delivery(0, item) is False
            snapshot = ConversationSnapshot(
                generation=1,
                target="general",
                messages=(item,),
            )
            assert app._apply_conversation(snapshot) is False

    asyncio.run(exercise())


def test_stale_intent_snapshot_is_not_applied() -> None:
    from taut_tui.app import TautApp
    from taut_tui.session import ConversationSnapshot

    async def exercise() -> None:
        app = TautApp(db_path=None, as_name=None, continuity_token=None)
        async with app.run_test(size=(100, 34)):
            app._conversation_intent = 5
            stale = ConversationSnapshot(
                generation=1,
                target="stale-target",
                messages=(),
                intent_token=3,
            )
            assert app._apply_conversation(stale) is False
            assert app.visual_state.active_conversation != "stale-target"

    asyncio.run(exercise())
