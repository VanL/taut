"""Real Textual lifecycle fences, distinct from object/result existence."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from _completion import CompletionScope, CompletionSuperseded, CompletionTimeout
from _screen_completion import ScreenCompletions
from textual import events
from textual.app import App, ComposeResult
from textual.screen import Screen
from textual.widgets import Input


def test_mount_observation_waits_for_actual_mount(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def exercise() -> None:
        entered, release = asyncio.Event(), asyncio.Event()

        class HeldScreen(Screen[None]):
            AUTO_FOCUS = "#query"

            def compose(self) -> ComposeResult:
                yield Input(id="query")

            async def on_mount(self) -> None:
                entered.set()
                await release.wait()

            def on_input_submitted(self, event: Input.Submitted) -> None:
                received.append(event.value)

        app: App[None] = App()
        received: list[str] = []
        with CompletionScope() as scope:
            screens = ScreenCompletions(app, scope, monkeypatch)
            async with app.run_test() as pilot:
                screen = HeldScreen()
                returned = app.push_screen(screen)
                try:
                    await asyncio.wait_for(entered.wait(), 2)
                    assert app.screen is screen
                    assert screens.mounted(screen).snapshot() is None
                    release.set()
                    assert (
                        await screens.mounted(screen).wait(
                            deadline=scope.now() + 2, description="screen mount"
                        )
                        is screen
                    )
                    assert screen.query_one("#query", Input).is_mounted
                    await screens.ready(
                        screen, deadline=scope.now() + 2, focus=screen.query_one(Input)
                    )
                    await pilot.press("x", "enter")
                    assert received == ["x"]
                    # The optional awaitable remains the original framework object.
                    await returned
                    scope.raise_if_invalid()
                finally:
                    release.set()
            screens.close()

    asyncio.run(exercise())


def test_pop_before_mount_supersedes_readiness_without_late_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def exercise() -> None:
        entered, release = asyncio.Event(), asyncio.Event()
        input_sent: list[bool] = []

        class HeldScreen(Screen[None]):
            async def on_mount(self) -> None:
                entered.set()
                await release.wait()

        app: App[None] = App()
        with CompletionScope() as scope:
            screens = ScreenCompletions(app, scope, monkeypatch)
            async with app.run_test():
                screen = HeldScreen()
                app.push_screen(screen)

                async def act_when_ready() -> None:
                    await screens.ready(screen, deadline=scope.now() + 2)
                    input_sent.append(True)

                try:
                    await asyncio.wait_for(entered.wait(), 2)
                    waiter = asyncio.create_task(act_when_ready())
                    removal = app.pop_screen()
                    with pytest.raises(CompletionSuperseded):
                        await waiter
                    assert input_sent == []
                finally:
                    release.set()
                await removal
                assert input_sent == []
                scope.raise_if_invalid()
            screens.close()

    asyncio.run(exercise())


def test_repush_has_distinct_lifecycle_and_rejects_old_readiness(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def exercise() -> None:
        app: App[None] = App()
        screen: Screen[None] = Screen()
        app.install_screen(screen, "reused")
        with CompletionScope() as scope:
            screens = ScreenCompletions(app, scope, monkeypatch)
            async with app.run_test():
                app.push_screen("reused")
                first_mount = screens.mounted(screen)
                await screens.ready(screen, deadline=scope.now() + 2)
                app.pop_screen()
                await screens.retired(screen).wait(
                    deadline=scope.now() + 2, description="first retirement"
                )
                with pytest.raises(CompletionSuperseded):
                    await screens.ready(screen, deadline=scope.now() + 2)
                app.push_screen("reused")
                assert screens.mounted(screen) is not first_mount
                assert (
                    screens.mounted(screen).key.generation != first_mount.key.generation
                )
                await screens.ready(screen, deadline=scope.now() + 2)
                assert screens.history == [screen, screen]
            screens.close()

    asyncio.run(exercise())


def test_focus_observation_follows_real_policy_handler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def exercise() -> None:
        entered, release = asyncio.Event(), asyncio.Event()
        applied: list[object] = []

        class FocusApp(App[None]):
            async def on_descendant_focus(self, event: events.DescendantFocus) -> None:
                entered.set()
                await release.wait()
                applied.append(event.widget)

        class QueryScreen(Screen[None]):
            AUTO_FOCUS = "#query"

            def compose(self) -> ComposeResult:
                yield Input(id="query")

        app = FocusApp()
        with CompletionScope() as scope:
            screens = ScreenCompletions(app, scope, monkeypatch)
            async with app.run_test():
                screen = QueryScreen()
                app.push_screen(screen)
                try:
                    await screens.mounted(screen).wait(
                        deadline=scope.now() + 2, description="mount"
                    )
                    widget = screen.query_one(Input)
                    await asyncio.wait_for(entered.wait(), 2)
                    assert widget.has_focus
                    assert screens.focused(widget).snapshot() is None
                    assert applied == []
                    release.set()
                    assert (
                        await screens.ready(
                            screen, deadline=scope.now() + 2, focus=widget
                        )
                        is screen
                    )
                    assert applied == [widget]
                finally:
                    release.set()
            screens.close()

    asyncio.run(exercise())


def test_inflight_old_focus_cannot_complete_a_reused_screen_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def exercise() -> None:
        entered, release = asyncio.Event(), asyncio.Event()
        finished = asyncio.Event()
        later_entered, later_release = asyncio.Event(), asyncio.Event()
        handled: list[object] = []

        class FocusApp(App[None]):
            async def on_descendant_focus(self, event: events.DescendantFocus) -> None:
                if not entered.is_set():
                    entered.set()
                    await release.wait()
                    handled.append(event.widget)
                    finished.set()
                else:
                    later_entered.set()
                    await later_release.wait()
                    handled.append(event.widget)

        class QueryScreen(Screen[None]):
            AUTO_FOCUS = "#query"

            def compose(self) -> ComposeResult:
                yield Input(id="query")

        app, screen = FocusApp(), QueryScreen()
        app.install_screen(screen, "reused")
        with CompletionScope() as scope:
            screens = ScreenCompletions(app, scope, monkeypatch)
            try:
                async with app.run_test():
                    app.push_screen("reused")
                    await screens.mounted(screen).wait(
                        deadline=scope.now() + 2, description="first mount"
                    )
                    widget = screen.query_one(Input)
                    try:
                        await asyncio.wait_for(entered.wait(), 2)
                        first = screens.focused(widget)
                        removal = app.pop_screen()
                        app.push_screen("reused")
                        second = screens.focused(widget)
                        assert first.key.generation != second.key.generation
                        release.set()
                        await asyncio.wait_for(finished.wait(), 2)
                        assert handled == [widget]
                        assert second.snapshot() is None

                        # Only a new generation's real focus application may
                        # complete its readiness, even for the same widget.
                        screen.set_focus(None)
                        widget.focus()
                        await asyncio.wait_for(later_entered.wait(), 2)
                        assert second.snapshot() is None
                        later_release.set()
                        assert (
                            await second.wait(
                                deadline=scope.now() + 2,
                                description="new focus applied",
                            )
                            is widget
                        )
                        await removal
                    finally:
                        release.set()
                        later_release.set()
            finally:
                screens.close()

    asyncio.run(exercise())


def test_detached_focus_during_teardown_does_not_replace_the_test_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def exercise() -> None:
        delivered = asyncio.Event()

        class FocusApp(App[None]):
            def on_descendant_focus(self, event: events.DescendantFocus) -> None:
                delivered.set()

        app = FocusApp()
        with CompletionScope() as scope:
            screens = ScreenCompletions(app, scope, monkeypatch)
            with pytest.raises(AssertionError, match="original test failure"):
                async with app.run_test():
                    app.post_message(events.DescendantFocus(Input()))
                    await asyncio.wait_for(delivered.wait(), 2)
                    raise AssertionError("original test failure")
            screens.close()

    asyncio.run(exercise())


def test_result_callback_error_remains_visible_to_framework_and_observer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def exercise() -> None:
        app: App[None] = App()
        failure = ValueError("real result callback failed")

        async def failed_result(value: object) -> None:
            raise failure

        with CompletionScope() as scope:
            screens = ScreenCompletions(app, scope, monkeypatch)
            with pytest.raises(ValueError, match="real result callback failed"):
                async with app.run_test():
                    screen: Screen[None] = Screen()
                    app.push_screen(screen, failed_result)
                    await screens.ready(screen, deadline=scope.now() + 2)
                    screen.dismiss()
                    with pytest.raises(ValueError) as caught:
                        await screens.result_applied(screen).wait(
                            deadline=scope.now() + 2, description="result"
                        )
                    assert caught.value is failure
            screens.close()

    asyncio.run(exercise())


def test_result_delivery_does_not_complete_held_removal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def exercise() -> None:
        app: App[None] = App()
        entered, release = asyncio.Event(), asyncio.Event()
        received: list[Any] = []
        original = app._replace_screen

        async def held_replace(screen: Screen[Any]) -> Screen[Any]:
            entered.set()
            await release.wait()
            return await original(screen)

        monkeypatch.setattr(app, "_replace_screen", held_replace)
        with CompletionScope() as scope:
            screens = ScreenCompletions(app, scope, monkeypatch)
            async with app.run_test():
                screen: Screen[int] = Screen()
                app.push_screen(screen, lambda value: received.append(value))
                await screens.mounted(screen).wait(
                    deadline=scope.now() + 2, description="mount"
                )
                removal = screen.dismiss(7)
                try:
                    assert (
                        await screens.result_applied(screen).wait(
                            deadline=scope.now() + 2, description="result"
                        )
                        == 7
                    )
                    await asyncio.wait_for(entered.wait(), 2)
                    assert received == [7]
                    assert screens.retired(screen).snapshot() is None
                    assert removal.is_done is False
                    release.set()
                    assert (
                        await screens.retired(screen).wait(
                            deadline=scope.now() + 2, description="retirement"
                        )
                        is screen
                    )
                    assert removal.is_done is True
                finally:
                    release.set()
            screens.close()

    asyncio.run(exercise())


@pytest.mark.parametrize("cancel", [False, True])
def test_observer_disposal_does_not_cancel_shared_removal(
    monkeypatch: pytest.MonkeyPatch, cancel: bool
) -> None:
    async def exercise() -> None:
        app: App[None] = App()
        entered, release = asyncio.Event(), asyncio.Event()
        original = app._replace_screen

        async def held_replace(screen: Screen[Any]) -> Screen[Any]:
            entered.set()
            await release.wait()
            return await original(screen)

        monkeypatch.setattr(app, "_replace_screen", held_replace)
        with CompletionScope() as scope:
            screens = ScreenCompletions(app, scope, monkeypatch)
            async with app.run_test():
                screen: Screen[None] = Screen()
                app.push_screen(screen)
                await screens.mounted(screen).wait(
                    deadline=scope.now() + 2, description="mount"
                )
                removal = app.pop_screen()
                try:
                    await asyncio.wait_for(entered.wait(), 2)
                    task = asyncio.create_task(
                        screens.retired(screen).wait(
                            deadline=scope.now() + (2 if cancel else 0),
                            description="retirement",
                        )
                    )
                    if cancel:
                        asyncio.get_running_loop().call_soon(task.cancel)
                    with pytest.raises(
                        asyncio.CancelledError if cancel else CompletionTimeout
                    ):
                        await task
                    assert removal._future.cancelled() is False
                    assert removal.is_done is False
                    release.set()
                    await removal
                    assert removal._future.cancelled() is False
                finally:
                    release.set()
            screens.close()

    asyncio.run(exercise())
