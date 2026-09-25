"""Exact app-owner completion seams for the real SQLite/Textual tests."""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Future
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

import pytest
from _action_completion import AppliedRequest
from _completion import Completion, CompletionKey, CompletionScope
from _screen_completion import ScreenCompletions
from textual import events
from textual.widgets import Button, Input

from taut.client import Message
from taut_tui.actions import ActionId
from taut_tui.screens import NativeFormScreen
from taut_tui.session import TuiSession
from taut_tui.viewport import TranscriptViewport, ViewportEffect, ViewportEffectKind
from taut_tui.widgets import TautComposer, TautOptionList


@dataclass(frozen=True)
class _ViewportSubscription:
    model: int
    intent: int
    epoch: int
    owner: TranscriptViewport
    record: Completion[Any]


class AppCompletions:
    """Installed before run_test; observations never advance product work."""

    def __init__(self, app: Any, patch: pytest.MonkeyPatch) -> None:
        self.app = app
        self.scope = CompletionScope()
        self.patch = patch
        self.screens = ScreenCompletions(app, self.scope, patch)
        self._closed = False
        self._conversation: dict[int, Completion[Any]] = {}
        self._sends: dict[int, Completion[Any]] = {}
        self._conversation_started: dict[int, float] = {}
        self._send_started: dict[int, float] = {}
        self._focus_waiters: dict[object, Completion[Any]] = {}
        self._focus_applied: dict[object, Completion[Any]] = {}
        self._highlight_waiters: dict[tuple[object, int], Completion[Any]] = {}
        self._highlight_applied: dict[tuple[object, int], Completion[Any]] = {}
        self._form_waiters: dict[object, Completion[Any]] = {}
        self._posted_requests: dict[int, tuple[object, Completion[Any]]] = {}
        self._button_cooldowns: dict[Completion[Any], Completion[Any]] = {}
        self._presenting: Completion[Any] | None = None
        self._screen_started: dict[Completion[Any], float] = {}
        self._deliveries: dict[tuple[int, str, int], Completion[Any]] = {}
        self._viewports: dict[int, Completion[Any]] = {}
        self._resizes: dict[int, Completion[Any]] = {}
        self._viewport_started: dict[int, float] = {}
        self._viewport_waiter: _ViewportSubscription | None = None
        self._viewport_owner_epoch = 0
        self._user_viewport_waiter: tuple[Completion[Any], int | None] | None = None
        self._dispatch_event: ContextVar[Any] = ContextVar(
            "app_completion_dispatch", default=None
        )
        self._user_viewport_event: Any = None
        self._recovery_tail: tuple[TranscriptViewport, Completion[Any]] | None = None
        self._optional_capture: list[tuple[Any, bool]] | None = None
        self.initial_navigation = self.scope.expect(
            CompletionKey(app, "initial_navigation.requested", request=self)
        )
        self.navigation_deadline: float | None = None
        self.navigation_future: Future[Any] | None = None
        self.navigation_source: Completion[Any] | None = None
        self._navigation_applied: Completion[Any] | None = None
        self._install_navigation_request()
        self._original_message = app._on_message
        self._original_push = app.push_screen
        self._original_navigation = app._apply_navigation_result
        self._original_advance = app._advance_conversation_intent
        self._original_conversation = app._apply_conversation
        self._original_optional = app._apply_optional_conversation
        self._original_submit = app._submit_composer
        self._original_send = app._apply_send_result
        self._original_delivery = app._apply_delivery
        self._original_render = app._render_messages
        self._original_effect = app._apply_viewport_effect
        self._original_tail = app._reapply_tail_effect
        self._original_user_intent = app._on_transcript_user_viewport_intent
        self._original_capture = app._capture_settled_transcript_viewport
        self._original_arm = app._arm_search_anchor
        self._original_clear = app._clear_pending_search_anchor
        self._original_commit = app._commit_transcript_viewport_observation
        self._original_resize_render = app._render_latest_resize
        patch.setattr(app, "push_screen", self._observe_push)
        patch.setattr(app, "_on_message", self._observe_on_message)
        patch.setattr(app, "_apply_navigation_result", self._observe_navigation)
        patch.setattr(app, "_advance_conversation_intent", self._observe_advance)
        patch.setattr(app, "_apply_conversation", self._observe_conversation)
        patch.setattr(app, "_apply_optional_conversation", self._observe_optional)
        patch.setattr(app, "_submit_composer", self._observe_submit)
        patch.setattr(app, "_apply_send_result", self._observe_send)
        patch.setattr(app, "_apply_delivery", self._observe_delivery)
        patch.setattr(app, "_render_messages", self._observe_render)
        patch.setattr(app, "_apply_viewport_effect", self._observe_effect)
        patch.setattr(app, "_reapply_tail_effect", self._observe_tail)
        patch.setattr(
            app, "_on_transcript_user_viewport_intent", self._observe_user_intent
        )
        patch.setattr(
            app, "_capture_settled_transcript_viewport", self._observe_capture
        )
        patch.setattr(app, "_arm_search_anchor", self._observe_arm)
        patch.setattr(app, "_clear_pending_search_anchor", self._observe_clear)
        patch.setattr(
            app, "_commit_transcript_viewport_observation", self._observe_commit
        )
        patch.setattr(app, "_render_latest_resize", self._observe_resize_render)

    def _observe_resize_render(self, generation: int) -> None:
        self._original_resize_render(generation)
        if not self._closed:
            record = self._resize_record(generation)
            if generation == self.app._resize_generation:
                record.succeed(record.key, generation)
            else:
                record.supersede(record.key)

    def _resize_record(self, generation: int) -> Completion[Any]:
        if generation not in self._resizes:
            self._resizes[generation] = self.scope.expect(
                CompletionKey(self.app, "resize.render_returned", generation=generation)
            )
        return self._resizes[generation]

    async def resize_render(self, *, deadline: float) -> None:
        await self._resize_record(self.app._resize_generation).wait(
            deadline=deadline, description="latest resize callback returned"
        )

    def _observe_push(self, *args: Any, **kwargs: Any) -> Any:
        record = self._presenting
        returned = self._original_push(*args, **kwargs)
        if not self._closed and record is not None:
            record.succeed(record.key, self.app.screen)
        return returned

    async def _observe_on_message(self, event: Any) -> None:
        effect = self._message_effect(event)
        pending = self._posted_requests.pop(id(event), None)
        posted = pending[1] if pending is not None and pending[0] is event else None
        focused = (
            self._focus_waiters.get(event.widget)
            if isinstance(event, events.DescendantFocus)
            else None
        )
        highlighted = (
            self._highlight_waiters.get((event.option_list, event.option_index))
            if isinstance(event, TautOptionList.OptionHighlighted)
            else None
        )
        submitted = (
            self._form_waiters.get(event.screen)
            if isinstance(event, NativeFormScreen.Submitted)
            else None
        )
        token = self._dispatch_event.set(event)
        try:
            await self._original_message(event)
        except BaseException as error:
            if not self._closed and posted is not None and posted.snapshot() is None:
                posted.fail(posted.key, error)
            raise
        finally:
            self._dispatch_event.reset(token)
        self._retain_message_effect(event, effect)
        if not self._closed and posted is not None and posted.snapshot() is None:
            posted.succeed(posted.key, event)
        if not self._closed and focused is not None:
            if self._focus_waiters.get(event.widget) is focused:
                self._focus_waiters.pop(event.widget)
            focused.succeed(focused.key, event.widget)
        if not self._closed and highlighted is not None:
            identity = (event.option_list, event.option_index)
            if self._highlight_waiters.get(identity) is highlighted:
                self._highlight_waiters.pop(identity)
            highlighted.succeed(highlighted.key, event.option_index)
        if not self._closed and submitted is not None:
            if self._form_waiters.get(event.screen) is submitted:
                self._form_waiters.pop(event.screen)
            submitted.succeed(submitted.key, event)

    def _message_effect(self, event: Any) -> Completion[Any] | None:
        if self._closed:
            return None
        if isinstance(event, events.DescendantFocus):
            return self.scope.expect(
                CompletionKey(event.widget, "focus.dispatched", request=event)
            )
        if isinstance(event, TautOptionList.OptionHighlighted):
            return self.scope.expect(
                CompletionKey(event.option_list, "highlight.dispatched", request=event)
            )
        return None

    def _retain_message_effect(
        self, event: Any, record: Completion[Any] | None
    ) -> None:
        if self._closed or record is None:
            return
        if isinstance(event, events.DescendantFocus):
            record.succeed(record.key, event.widget)
            self._focus_applied[event.widget] = record
        else:
            record.succeed(record.key, self.app.visual_state.selected_message_id)
            self._highlight_applied[(event.option_list, event.option_index)] = record

    def _observe_user_intent(self) -> None:
        self._original_user_intent()
        self._viewport_owner_changed()
        if self._user_viewport_waiter is not None:
            record, generation = self._user_viewport_waiter
            event = self._dispatch_event.get()
            if generation is None or event is self._user_viewport_event:
                self._user_viewport_event = event
                self._user_viewport_waiter = (
                    record,
                    self.app.visual_state.viewport.generation,
                )
            else:
                record.supersede(record.key)
                self._user_viewport_waiter = None

    def _observe_commit(self, observation: Any) -> None:
        generation = self.app.visual_state.viewport.generation
        self._original_commit(observation)
        if not self._closed and self._user_viewport_waiter is not None:
            record, expected = self._user_viewport_waiter
            if expected == generation:
                record.succeed(record.key, self.app.visual_state.viewport)
                self._user_viewport_waiter = None

    def _observe_capture(self) -> None:
        self._original_capture()
        self._viewport_owner_changed()

    def _observe_arm(self, intent: int, message_id: int) -> None:
        self._original_arm(intent, message_id)
        self._viewport_owner_changed()

    def _observe_clear(self, **kwargs: Any) -> bool:
        changed = self._original_clear(**kwargs)
        if changed:
            self._viewport_owner_changed()
        return bool(changed)

    def _observe_render(self, *args: Any, **kwargs: Any) -> None:
        started = self.scope.now()
        self._original_render(*args, **kwargs)
        if not self._closed and self.app._message_rows:
            generation = self.app.visual_state.viewport.generation
            self._viewport_started.setdefault(generation, started)
            self._viewport_record(generation)

    def _observe_effect(self, effect: ViewportEffect, messages: Any) -> None:
        owner = self.app.visual_state.viewport
        accepted = owner.accepts(effect) and not self.app._shutting_down
        self._original_effect(effect, messages)
        if self._closed:
            return
        record = self._viewport_record(effect.generation)
        if record.snapshot() is not None:
            return
        if not accepted or not self.app.visual_state.viewport.accepts(effect):
            record.supersede(record.key)
            if accepted and self._recovery_tail is not None:
                source, recovery = self._recovery_tail
                if (
                    owner.mode is source.mode
                    and owner.message_id == source.message_id
                    and owner.generation >= source.generation
                    and self.app.visual_state.viewport.tail_pinned
                ):
                    self._recovery_tail = None
                    self._viewport_waiter = _ViewportSubscription(
                        self.app.visual_state.model_generation,
                        self.app._conversation_intent,
                        self._viewport_owner_epoch,
                        self.app.visual_state.viewport,
                        recovery,
                    )
        elif effect.kind is ViewportEffectKind.RESTORE:
            record.succeed(record.key, effect)
            self._viewport_settled(effect, owner)

    def _observe_tail(self, effect: ViewportEffect) -> None:
        owner = self.app.visual_state.viewport
        accepted = (
            self.app.visual_state.viewport.accepts(effect)
            and self.app.visual_state.viewport.tail_pinned
            and not self.app._shutting_down
        )
        self._original_tail(effect)
        if self._closed:
            return
        record = self._viewport_record(effect.generation)
        if record.snapshot() is None:
            if accepted:
                record.succeed(record.key, effect)
                self._viewport_settled(effect, owner)
            else:
                record.supersede(record.key)

    def _observe_delivery(self, generation: int, item: Any) -> bool:
        accepted = self._original_delivery(generation, item)
        if not self._closed and isinstance(item, Message):
            record = self._delivery_record(generation, item)
            if record.snapshot() is not None:
                return bool(accepted)
            if accepted:
                record.succeed(record.key, item)
            else:
                record.supersede(record.key)
        return bool(accepted)

    def _observe_navigation(self, future: Future[Any]) -> None:
        self._original_navigation(future)
        if not self._closed and future is self.navigation_future:
            record = self._navigation_applied
            assert record is not None
            record.succeed(record.key, future)

    def _install_navigation_request(self) -> None:
        original = TuiSession.refresh_navigation

        def refresh(session: TuiSession) -> Future[Any]:
            selected = (
                not self._closed
                and session is self.app._session
                and self.navigation_future is None
            )
            if selected:
                self.navigation_deadline = self.scope.now() + 5
            future = original(session)
            if selected:
                self.navigation_future = future
                self.navigation_source = self.scope.observe_future(
                    future, owner=session, phase="navigation.source"
                )
                self._navigation_applied = self.scope.expect(
                    CompletionKey(self.app, "navigation.applied", request=future)
                )
                self.initial_navigation.succeed(
                    self.initial_navigation.key, self._navigation_applied
                )
            return future

        self.patch.setattr(TuiSession, "refresh_navigation", refresh)

    def _observe_advance(self, *args: Any, **kwargs: Any) -> int:
        started = self.scope.now()
        intent = self._original_advance(*args, **kwargs)
        if not self._closed:
            self._viewport_owner_changed()
            self._conversation_started.setdefault(intent, started)
            self._conversation_record(intent)
        return int(intent)

    def _observe_conversation(self, snapshot: Any) -> bool:
        accepted = self._original_conversation(snapshot)
        if self._optional_capture is not None:
            self._optional_capture.append((snapshot, accepted))
        return bool(accepted)

    def _observe_optional(
        self, intent: int, future: Future[Any], **kwargs: Any
    ) -> None:
        captured: list[tuple[Any, bool]] = []
        prior, self._optional_capture = self._optional_capture, captured
        try:
            self._original_optional(intent, future, **kwargs)
        finally:
            self._optional_capture = prior
        if self._closed:
            return
        record = self._conversation_record(intent)
        if record.snapshot() is not None:
            return
        if future.cancelled():
            record.cancel(record.key)
        elif (error := future.exception()) is not None:
            record.fail(record.key, error)
        elif captured and captured[-1][0] is future.result() and captured[-1][1]:
            record.succeed(record.key, future.result())
        else:
            record.supersede(record.key)

    def _observe_submit(self, text: str) -> None:
        started = self.scope.now()
        previous = self.app._next_send_token
        self._original_submit(text)
        if not self._closed and self.app._next_send_token != previous:
            self._send_started.setdefault(self.app._next_send_token, started)
            self._send_record(self.app._next_send_token)

    def _observe_send(self, token: int, future: Future[Any]) -> None:
        self._original_send(token, future)
        if self._closed:
            return
        record = self._send_record(token)
        if future.cancelled():
            record.cancel(record.key)
        elif (error := future.exception()) is not None:
            record.fail(record.key, error)
        else:
            record.succeed(record.key, future.result())

    def _viewport_record(self, generation: int) -> Completion[Any]:
        if generation not in self._viewports:
            self._viewports[generation] = self.scope.expect(
                CompletionKey(self.app, "viewport.applied", generation=generation)
            )
        return self._viewports[generation]

    def _viewport_owner_changed(self) -> None:
        if self._closed:
            return
        self._viewport_owner_epoch += 1
        if self._viewport_waiter is not None:
            record = self._viewport_waiter.record
            record.supersede(record.key)
            self._viewport_waiter = None
        if self._recovery_tail is not None:
            record = self._recovery_tail[1]
            record.supersede(record.key)
            self._recovery_tail = None

    def _viewport_settled(
        self, effect: ViewportEffect, owner: TranscriptViewport
    ) -> None:
        pending = self._viewport_waiter
        if pending is None:
            return
        record = pending.record
        if (
            pending.model != self.app.visual_state.model_generation
            or pending.intent != self.app._conversation_intent
            or pending.epoch != self._viewport_owner_epoch
            or (
                pending.owner.mode,
                pending.owner.intent,
                pending.owner.message_id,
                pending.owner.offset,
            )
            != (owner.mode, owner.intent, owner.message_id, owner.offset)
        ):
            record.supersede(record.key)
            self._viewport_waiter = None
        elif effect.generation >= pending.owner.generation:
            record.succeed(record.key, effect)
            self._viewport_waiter = None

    def _delivery_record(self, generation: int, message: Message) -> Completion[Any]:
        identity = (generation, message.thread, message.ts)
        if identity not in self._deliveries:
            self._deliveries[identity] = self.scope.expect(
                CompletionKey(self.app, "delivery.applied", message, generation)
            )
        return self._deliveries[identity]

    def _conversation_record(self, intent: int) -> Completion[Any]:
        if intent not in self._conversation:
            self._conversation[intent] = self.scope.expect(
                CompletionKey(self.app, "conversation.applied", generation=intent)
            )
        return self._conversation[intent]

    def _send_record(self, token: int) -> Completion[Any]:
        if token not in self._sends:
            self._sends[token] = self.scope.expect(
                CompletionKey(self.app, "send.applied", generation=token)
            )
        return self._sends[token]

    def close(self) -> None:
        self._closed = True
        self.screens.close()
        self.scope.close()
        self._focus_waiters.clear()
        self._focus_applied.clear()
        self._highlight_waiters.clear()
        self._highlight_applied.clear()
        self._form_waiters.clear()
        self._posted_requests.clear()
        self._button_cooldowns.clear()
        self._conversation.clear()
        self._sends.clear()
        self._screen_started.clear()
        self._deliveries.clear()
        self._viewports.clear()
        self._resizes.clear()
        self._viewport_waiter = self._user_viewport_waiter = self._recovery_tail = None
        self.scope.raise_if_invalid()

    async def navigation(self) -> None:
        deadline = self.navigation_deadline
        assert deadline is not None, (
            "run_test must start the session before navigation wait"
        )
        applied = await self.initial_navigation.wait(
            deadline=deadline, description="initial navigation requested"
        )
        # Source error/cancellation remains retained separately: rendering the
        # missing-identity/error navigation is itself a valid UI apply phase.
        await applied.wait(deadline=deadline, description="initial navigation applied")

    async def focus(self, widget: Any, *, deadline: float) -> None:
        if widget.screen is not self.app._base_screen:
            await self.screens.ready(widget.screen, deadline=deadline, focus=widget)
            return
        # Owner-state check and subscription are atomic on Textual's loop.
        prior = self._focus_applied.get(widget)
        if (
            prior is not None
            and widget.has_focus
            and self.app.visual_state.focus.widget_id == widget.id
        ):
            await prior.wait(deadline=deadline, description="retained focus applied")
            return
        record = self.scope.expect(
            CompletionKey(widget, "focus.applied", request=object())
        )
        self._focus_waiters[widget] = record
        await record.wait(deadline=deadline, description="focus applied")

    async def highlighted(self, widget: Any, index: int, *, deadline: float) -> None:
        message = self.app._message_rows[index]
        if (
            widget.highlighted == index
            and self.app.visual_state.selected_message_id == message.ts
        ):
            prior = self._highlight_applied.get((widget, index))
            if prior is not None:
                applied = await prior.wait(
                    deadline=deadline, description="retained highlight applied"
                )
                if applied == message.ts:
                    return
        record = self.scope.expect(
            CompletionKey(widget, "highlight.applied", request=message)
        )
        self._highlight_waiters[(widget, index)] = record
        await record.wait(deadline=deadline, description="highlight applied")

    def pointer_release(self, widget: Any) -> Completion[Any]:
        record = self.scope.expect(
            CompletionKey(widget, "pointer.released", request=object())
        )
        original = widget._on_message

        async def on_message(event: Any) -> None:
            await original(event)
            if isinstance(event, events.MouseUp) and record.snapshot() is None:
                record.succeed(record.key, None)

        self.patch.setattr(widget, "_on_message", on_message)
        return record

    def _presentation_record(self, request: object) -> Completion[Any]:
        record = self.scope.expect(
            CompletionKey(self.app, "screen.pushed", request=request)
        )
        self._screen_started[record] = self.scope.now()
        return record

    def screen_for_action(self, action: ActionId) -> Completion[Any]:
        record = self._presentation_record(object())
        method = (
            "_dispatch_system_or_summon_action"
            if action is ActionId.SUMMON_START
            else "_open_native_form"
        )
        original = getattr(self.app, method)

        def present(action_id: ActionId, *args: Any, **kwargs: Any) -> Any:
            if action_id is not action or record.snapshot() is not None:
                return original(action_id, *args, **kwargs)
            return self._within_presentation(
                record, original, action_id, *args, **kwargs
            )

        self.patch.setattr(self.app, method, present)
        return record

    def command_line(self) -> Completion[Any]:
        record = self._presentation_record(object())
        original = self.app.action_open_command_line

        def present(**kwargs: Any) -> None:
            self._within_presentation(record, original, **kwargs)

        self.patch.setattr(self.app, "action_open_command_line", present)
        return record

    def form_submission(self, screen: NativeFormScreen) -> Completion[Any]:
        record = self.scope.expect(
            CompletionKey(screen, "form.submitted", request=object())
        )
        self._form_waiters[screen] = record
        return record

    def composer_edit(self, widget: TautComposer) -> Completion[Any]:
        record = self.scope.expect(
            CompletionKey(widget, "composer.edit_applied", request=object())
        )
        original = widget.post_message

        def post(event: Any) -> bool:
            if (
                not self._closed
                and isinstance(event, TautComposer.Changed)
                and event.text_area is widget
                and record.snapshot() is None
            ):
                self._posted_requests[id(event)] = (event, record)
            return bool(original(event))

        self.patch.setattr(widget, "post_message", post)
        return record

    def button_press(self, widget: Button) -> Completion[Any]:
        record = self.scope.expect(
            CompletionKey(widget, "button.press_applied", request=object())
        )
        cooldown = self.scope.expect(
            CompletionKey(widget, "button.cooldown", request=record)
        )
        self._button_cooldowns[record] = cooldown
        original = widget.post_message
        original_remove = widget.remove_class

        def remove(*names: str, **kwargs: Any) -> Any:
            returned = original_remove(*names, **kwargs)
            if not self._closed and "-active" in names and cooldown.snapshot() is None:
                cooldown.succeed(cooldown.key, None)
            return returned

        def post(event: Any) -> bool:
            if (
                not self._closed
                and isinstance(event, Button.Pressed)
                and event.button is widget
                and record.snapshot() is None
            ):
                self._posted_requests[id(event)] = (event, record)
                if widget.active_effect_duration <= 0:
                    cooldown.succeed(cooldown.key, None)
            return bool(original(event))

        self.patch.setattr(widget, "post_message", post)
        self.patch.setattr(widget, "remove_class", remove)
        return record

    def option_activation(self, widget: TautOptionList) -> Completion[Any]:
        """Bind the real widget activation message to its post-handler result."""
        record = self.scope.expect(
            CompletionKey(widget, "option.activation_applied", request=object())
        )
        original = widget.post_message

        def post(event: Any) -> bool:
            if (
                not self._closed
                and isinstance(event, TautOptionList.Activated)
                and event.option_list is widget
                and record.snapshot() is None
            ):
                self._posted_requests[id(event)] = (event, record)
            return bool(original(event))

        self.patch.setattr(widget, "post_message", post)
        return record

    async def button_ready(self, record: Completion[Any], *, deadline: float) -> None:
        await self._button_cooldowns[record].wait(
            deadline=deadline, description="button active effect retired"
        )

    def input_edit(self, widget: Input) -> Completion[Any]:
        record = self.scope.expect(
            CompletionKey(widget, "input.edit_applied", request=object())
        )
        original_post, original_dispatch = (
            widget.post_message,
            widget.screen._on_message,
        )
        posted: dict[int, object] = {}

        def post(event: Any) -> bool:
            if isinstance(event, Input.Changed) and event.input is widget:
                posted[id(event)] = event
            return bool(original_post(event))

        async def dispatch(event: Any) -> None:
            selected = posted.pop(id(event), None) is event
            await original_dispatch(event)
            if selected and not self._closed and record.snapshot() is None:
                record.succeed(record.key, event)

        self.patch.setattr(widget, "post_message", post)
        self.patch.setattr(widget.screen, "_on_message", dispatch)
        return record

    def rows_measured(self, widget: TautOptionList) -> Completion[Any]:
        """Subscribe before adding rows; Textual alone invokes the real measurer."""
        record = self.scope.expect(
            CompletionKey(widget, "rows.measured", request=object())
        )
        original = widget._update_lines
        queued = False

        def refreshed() -> None:
            if not self._closed:
                record.succeed(record.key, widget.virtual_size)

        def measure() -> None:
            nonlocal queued
            original()
            if not self._closed and widget.scrollable_content_region and not queued:
                queued = True
                widget.call_after_refresh(refreshed)

        self.patch.setattr(widget, "_update_lines", measure)
        return record

    def attach_confirmation(self, notice: object) -> Completion[Any]:
        import taut_tui.app as app_module

        record = self._presentation_record(notice)
        original = app_module._present_attach_confirmation

        def present(app: Any, event: Any, **kwargs: Any) -> None:
            if app is self.app and event.notice is notice:
                self._within_presentation(record, original, app, event, **kwargs)
            else:
                original(app, event, **kwargs)

        self.patch.setattr(app_module, "_present_attach_confirmation", present)
        return record

    def _within_presentation(
        self,
        record: Completion[Any],
        present: Callable[..., Any],
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        self._screen_started[record] = self.scope.now()
        prior, self._presenting = self._presenting, record
        try:
            return present(*args, **kwargs)
        finally:
            self._presenting = prior

    async def pushed(
        self, record: Completion[Any], *, focus: str | None = None, timeout: float = 5
    ) -> Any:
        deadline = self._screen_started[record] + timeout
        screen = await record.wait(
            deadline=deadline, description="requested screen pushed"
        )
        # If the caller subscribed before a worker delivered the named request,
        # the actual presentation callback, not that admission, starts readiness.
        deadline = self._screen_started[record] + timeout
        await self.screens.ready(screen, deadline=deadline)
        if focus is not None:
            await self.screens.ready(
                screen, deadline=deadline, focus=screen.query_one(focus)
            )
        return screen

    def opening(self) -> Completion[Any]:
        intent = self.app._conversation_intent + 1
        self._conversation_started.setdefault(intent, self.scope.now())
        return self._conversation_record(intent)

    async def conversation(
        self,
        completion: Completion[Any] | None = None,
        *,
        timeout: float = 5,
        deadline: float | None = None,
    ) -> None:
        intent = (
            self.app._conversation_intent
            if completion is None
            else completion.key.generation
        )
        assert intent is not None
        completion = (
            self._conversation_record(intent) if completion is None else completion
        )
        await completion.wait(
            deadline=(
                self._conversation_started.get(intent, self.scope.now()) + timeout
            )
            if deadline is None
            else deadline,
            description="conversation intent applied",
        )

    def action(self, method: str) -> AppliedRequest:
        assert self.app._domain is not None
        return AppliedRequest(
            self.scope, self.patch, self.app, self.app._domain, method
        )

    async def delivery(self, message: Message, *, deadline: float) -> None:
        record = self._delivery_record(self.app.visual_state.model_generation, message)
        await record.wait(
            deadline=deadline, description="exact message delivery applied"
        )

    async def viewport(self, *, deadline: float | None = None) -> None:
        viewport = self.app.visual_state.viewport
        generation = viewport.generation
        prior = self._viewports.get(generation)
        if prior is not None and prior.snapshot() is not None:
            record = prior
        else:
            record = self.scope.expect(
                CompletionKey(
                    self.app,
                    "viewport.owner_settled",
                    request=object(),
                    generation=generation,
                )
            )
            assert self._viewport_waiter is None
            self._viewport_waiter = _ViewportSubscription(
                self.app.visual_state.model_generation,
                self.app._conversation_intent,
                self._viewport_owner_epoch,
                viewport,
                record,
            )
        try:
            await record.wait(
                deadline=(self._viewport_started.get(generation, self.scope.now()) + 5)
                if deadline is None
                else deadline,
                description="viewport effect applied after row measurement",
            )
        finally:
            if (
                self._viewport_waiter is not None
                and self._viewport_waiter.record is record
            ):
                self._viewport_waiter = None

    def user_viewport(self) -> Completion[Any]:
        """Subscribe before the next real user scroll/selection intent."""
        assert self._user_viewport_waiter is None
        record = self.scope.expect(
            CompletionKey(self.app, "viewport.user_settled", request=object())
        )
        self._user_viewport_waiter = (record, None)
        self._user_viewport_event = None
        widget = self.app.query_one("#transcript", TautOptionList)
        original = widget._on_message

        async def dispatch(event: Any) -> None:
            token = self._dispatch_event.set(event)
            try:
                await original(event)
            finally:
                self._dispatch_event.reset(token)

        self.patch.setattr(widget, "_on_message", dispatch)
        return record

    def recovering_tail(self) -> Completion[Any]:
        """Bind missing-anchor recovery to this history owner before rendering."""
        assert self._recovery_tail is None and self._viewport_waiter is None
        owner = self.app.visual_state.viewport
        record = self.scope.expect(
            CompletionKey(self.app, "viewport.recovery_tail", request=owner)
        )
        self._recovery_tail = (owner, record)
        return record

    def sending(self) -> Completion[Any]:
        token = self.app._next_send_token + 1
        self._send_started.setdefault(token, self.scope.now())
        return self._send_record(token)

    async def send(
        self, completion: Completion[Any] | None = None, *, timeout: float = 5
    ) -> None:
        token = (
            self.app._next_send_token
            if completion is None
            else completion.key.generation
        )
        assert token is not None
        completion = self._send_record(token) if completion is None else completion
        await completion.wait(
            deadline=self._send_started.get(token, self.scope.now()) + timeout,
            description="send applied",
        )


def observed(app: Any) -> AppCompletions:
    return app._test_completions  # type: ignore[no-any-return]
