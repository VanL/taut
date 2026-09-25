"""Exact worker/application observations for the action test matrices."""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Future
from typing import Any

import pytest
from _completion import Completion, CompletionKey, CompletionScope
from textual import events
from textual.widgets import Input


class AppliedRequest:
    """Bind one named producer call to its real Textual apply callback.

    The producer creates the Future during the action, so request creation is
    a separate retained phase. Neither waiting for it nor waiting for apply
    restarts the caller's action deadline.
    """

    def __init__(
        self,
        scope: CompletionScope,
        patch: pytest.MonkeyPatch,
        app: Any,
        producer: Any,
        method: str,
    ) -> None:
        self.scope = scope
        self.future: Future[Any] | None = None
        self.applied: Completion[Any] | None = None
        self.source: Completion[Any] | None = None
        self.requested = scope.expect(
            CompletionKey(producer, f"{method}.requested", request=self)
        )
        original_produce = getattr(producer, method)
        original_watch = app._watch_future

        def produce(*args: Any, **kwargs: Any) -> Future[Any]:
            try:
                future: Future[Any] = original_produce(*args, **kwargs)
            except BaseException as error:
                self.requested.fail(self.requested.key, error)
                raise
            assert self.future is None, f"{method} produced more than one request"
            self.future = future
            self.source = scope.observe_future(future, owner=producer, phase=method)
            self.applied = scope.expect(
                CompletionKey(app, f"{method}.applied", request=future)
            )
            self.requested.succeed(self.requested.key, self.applied)
            return future

        def watch(future: Future[Any], apply: Callable[[Future[Any]], None]) -> None:
            if future is not self.future:
                original_watch(future, apply)
                return
            completion = self.applied
            assert completion is not None

            def applied(done: Future[Any]) -> None:
                try:
                    apply(done)
                except BaseException as error:
                    completion.fail(completion.key, error)
                    raise
                if done.cancelled():
                    completion.cancel(completion.key)
                elif (source_error := done.exception()) is not None:
                    completion.fail(completion.key, source_error)
                else:
                    completion.succeed(completion.key, done.result())

            original_watch(future, applied)

        patch.setattr(producer, method, produce)
        patch.setattr(app, "_watch_future", watch)

    async def wait(self, deadline: float) -> Any:
        applied = await self.requested.wait(
            deadline=deadline, description="action request created"
        )
        return await applied.wait(deadline=deadline, description="action applied")


async def palette_query(
    scope: CompletionScope,
    patch: pytest.MonkeyPatch,
    screen: Any,
    value: str,
) -> None:
    """Observe the render belonging to this exact palette query assignment."""
    query = screen.query_one("#palette-query", Input)
    rendered = scope.expect(
        CompletionKey(screen, "palette.query-rendered", request=query)
    )
    original_render = screen._render_results

    def render(text: str) -> None:
        original_render(text)
        if text == value:
            rendered.succeed(rendered.key, text)

    patch.setattr(screen, "_render_results", render)
    deadline = scope.now() + 5
    query.value = value
    await rendered.wait(deadline=deadline, description="palette query rendered")


def observe_focus(
    scope: CompletionScope,
    patch: pytest.MonkeyPatch,
    app: Any,
    widget: Any,
) -> Completion[Any]:
    """Wait for the app's real descendant-focus application, not focus()."""
    focused = scope.expect(CompletionKey(app, "focus.applied", request=widget))
    original_dispatch = app._on_message

    async def observe(event: Any) -> None:
        await original_dispatch(event)
        if (
            isinstance(event, events.DescendantFocus)
            and event.widget is widget
            and focused.snapshot() is None
        ):
            focused.succeed(focused.key, widget)

    patch.setattr(app, "_on_message", observe)
    # Both retained fields are owned by the loop; no yield separates the
    # check from subscription or the new request.
    if widget.has_focus and app.visual_state.focus.widget_id == widget.id:
        focused.succeed(focused.key, widget)
    return focused


async def focus_widget(
    scope: CompletionScope,
    patch: pytest.MonkeyPatch,
    app: Any,
    widget: Any,
) -> None:
    focused = observe_focus(scope, patch, app, widget)
    deadline = scope.now() + 5
    widget.focus()
    await focused.wait(deadline=deadline, description="widget focus applied")
