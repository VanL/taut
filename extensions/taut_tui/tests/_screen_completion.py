"""Observe Textual's existing lifecycle work without starting another driver."""

from __future__ import annotations

import asyncio
import weakref
from collections.abc import Callable, Generator
from dataclasses import dataclass, field
from functools import partial
from typing import Any

import pytest
from _completion import Completion, CompletionKey, CompletionScope, CompletionSuperseded
from textual import events
from textual._callback import invoke
from textual.app import App
from textual.await_complete import AwaitComplete
from textual.dom import NoScreen
from textual.message import Message
from textual.screen import Screen
from textual.widget import AwaitMount, Widget


@dataclass
class _Lifecycle:
    screen: Screen[Any]
    generation: int
    mounted: Completion[Screen[Any]]
    retired: Completion[Screen[Any]]
    result: Completion[Any]
    focus: dict[Widget, Completion[Widget]] = field(default_factory=dict)
    popped: bool = False


class ScreenCompletions:
    """Install before push; each push owns a distinct retained lifecycle.

    Mount observation delegates the framework's already scheduled AwaitMount.
    Retirement observes the existing AwaitComplete future, never awaits/cancels
    it on the observer's behalf. Focus means the first committed focus of a
    widget in this push generation. Call ``ready`` before input to additionally
    reject a screen which was retired after its earlier successful mount.
    """

    def __init__(
        self, app: App[Any], scope: CompletionScope, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self.app, self.scope = app, scope
        self.history: list[Screen[Any]] = []
        self._lifecycles: dict[Screen[Any], _Lifecycle] = {}
        self._mounts: dict[AwaitMount, _Lifecycle] = {}
        self._closed = False
        self._pushing = False
        self._current: _Lifecycle | None = None
        self._generation = 0
        self._original_get = app._get_screen
        self._original_push: Callable[..., Any] = app.push_screen
        self._original_pop = app.pop_screen
        self._original_on_message = app._on_message
        original_await = AwaitMount.__await__

        def await_mount(mount: AwaitMount) -> Generator[Any, None, None]:
            life = self._mounts.get(mount)
            try:
                yield from original_await(mount)
            except BaseException as error:
                if life is not None and life.mounted.snapshot() is None:
                    life.mounted.fail(life.mounted.key, error)
                raise
            else:
                if life is not None and life.mounted.snapshot() is None:
                    if life.popped:
                        life.mounted.supersede(life.mounted.key)
                    else:
                        life.mounted.succeed(life.mounted.key, life.screen)

        monkeypatch.setattr(app, "_get_screen", self._get_screen)
        monkeypatch.setattr(app, "push_screen", self._push_screen)
        monkeypatch.setattr(app, "pop_screen", self._pop_screen)
        monkeypatch.setattr(AwaitMount, "__await__", await_mount)
        monkeypatch.setattr(app, "_on_message", self._on_message)

    def _get_screen(self, screen: Screen[Any] | str) -> tuple[Screen[Any], AwaitMount]:
        actual, mount = self._original_get(screen)
        if self._pushing and not self._closed:
            life = self._new_lifecycle(actual)
            self._mounts[mount] = life
            self._current = life
        return actual, mount

    def _push_screen(
        self,
        screen: Screen[Any] | str,
        callback: Any = None,
        wait_for_dismiss: bool = False,
        *,
        mode: str | None = None,
    ) -> Any:
        if self._closed:
            return self._original_push(screen, callback, wait_for_dismiss, mode=mode)
        life: _Lifecycle | None = None

        async def result_applied(value: Any) -> None:
            assert life is not None
            try:
                if callback is not None:
                    # ResultCallback.call_next prebinds the result before
                    # invoke. Preserve that convention for bound built-ins.
                    await invoke(partial(callback, value))
            except BaseException as error:
                life.result.fail(life.result.key, error)
                raise
            else:
                life.result.succeed(life.result.key, value)

        self._pushing = True
        try:
            returned = self._original_push(
                screen, result_applied, wait_for_dismiss, mode=mode
            )
            life = self._current
            return returned
        finally:
            self._pushing = False
            self._current = None

    def _pop_screen(self) -> AwaitComplete:
        screen = self.app.screen
        life = self._lifecycles.get(screen)
        returned = self._original_pop()
        if life is not None and not self._closed:
            life.popped = True
            pending_records: list[Completion[Any]] = [
                life.mounted,
                *life.focus.values(),
            ]
            for pending in pending_records:
                if pending.snapshot() is None:
                    pending.supersede(pending.key)
            reference = weakref.ref(life.retired)

            def retired(source: asyncio.Future[Any]) -> None:
                completion = reference()
                if completion is None:
                    return
                if source.cancelled():
                    completion.cancel(completion.key)
                elif (error := source.exception()) is not None:
                    completion.fail(completion.key, error)
                else:
                    target = completion.key.request
                    assert isinstance(target, Screen)
                    completion.succeed(completion.key, target)

            returned._future.add_done_callback(retired)
        return returned

    async def _on_message(self, event: Message) -> None:
        # Textual discovers handlers on the class, not the instance. Observe
        # after its real dispatch returns, including all applicable handlers.
        life: _Lifecycle | None = None
        if not self._closed and isinstance(event, events.DescendantFocus):
            try:
                life = self._lifecycles.get(event.widget.screen)
            except NoScreen:
                pass
        await self._original_on_message(event)
        if self._closed or life is None or not isinstance(event, events.DescendantFocus):
            return
        try:
            screen = event.widget.screen
        except NoScreen:
            # A queued focus event can outlive the widget during teardown.
            return
        if self._lifecycles.get(screen) is life and not life.popped:
            focus = self.focused(event.widget)
            if focus.snapshot() is None:
                focus.succeed(focus.key, event.widget)

    def _new_lifecycle(self, screen: Screen[Any]) -> _Lifecycle:
        if len(self.history) >= 128:
            raise AssertionError("screen observation exceeds per-test lifecycle bound")
        self._generation += 1
        generation = self._generation

        def expect(phase: str) -> Completion[Any]:
            return self.scope.expect(CompletionKey(self.app, phase, screen, generation))

        life = _Lifecycle(
            screen,
            generation,
            expect("screen.mounted"),
            expect("screen.retired"),
            expect("screen.result_applied"),
        )
        self._lifecycles[screen] = life
        self.history.append(screen)
        return life

    def mounted(self, screen: Screen[Any]) -> Completion[Screen[Any]]:
        return self._lifecycles[screen].mounted

    def retired(self, screen: Screen[Any]) -> Completion[Screen[Any]]:
        return self._lifecycles[screen].retired

    def result_applied(self, screen: Screen[Any]) -> Completion[Any]:
        return self._lifecycles[screen].result

    def focused(self, widget: Widget) -> Completion[Widget]:
        life = self._lifecycles[widget.screen]
        if widget not in life.focus:
            focus: Completion[Widget] = self.scope.expect(
                CompletionKey(
                    life.screen, "screen.focus_applied", widget, life.generation
                )
            )
            life.focus[widget] = focus
            if life.popped:
                focus.supersede(focus.key)
        return life.focus[widget]

    async def ready(
        self, screen: Screen[Any], *, deadline: float, focus: Widget | None = None
    ) -> Screen[Any]:
        life = self._lifecycles[screen]
        await life.mounted.wait(deadline=deadline, description="screen mounted")
        if focus is not None:
            await self.focused(focus).wait(
                deadline=deadline, description="focus applied"
            )
        if life.popped or self.app.screen is not screen:
            raise CompletionSuperseded("screen no longer active")
        return screen

    def close(self) -> None:
        self._closed = True
        for life in self._mounts.values():
            for completion in (
                life.mounted,
                life.retired,
                life.result,
                *life.focus.values(),
            ):
                completion.dispose()
        self._mounts.clear()
        self._lifecycles.clear()
        self.history.clear()
