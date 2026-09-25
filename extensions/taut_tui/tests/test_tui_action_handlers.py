"""Executable concrete-handler outcomes for every native TUI action."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from concurrent.futures import Future
from contextlib import ExitStack
from dataclasses import dataclass, field, replace
from pathlib import Path
from threading import Event
from typing import Any

import pytest
from _action_completion import (
    AppliedRequest,
    focus_widget,
    observe_focus,
    palette_query,
)
from _completion import CompletionKey, CompletionScope
from _screen_completion import ScreenCompletions
from textual import events
from textual.widgets import Button, Input, OptionList, Select

from taut import EmptyResultError, NotFoundError
from taut.client import InitResult, TautClient
from taut_tui.actions import ActionContext, ActionId, ActionRoute, action_spec
from taut_tui.app import TautApp
from taut_tui.models import DraftState, InspectorKind, InteractionMode, LogicalSurface
from taut_tui.screens import (
    CommandLineScreen,
    CommandPaletteScreen,
    ConfirmationScreen,
    DraftRecoveryScreen,
    NamedActionScreen,
    NativeFormScreen,
    SearchScreen,
    SummonStartScreen,
)
from taut_tui.session import ConversationSnapshot, NavigationSnapshot
from taut_tui.summon import TuiSummonInteraction, TuiSummonOperations
from taut_tui.system import ReplacementConfirmationRequired
from taut_tui.viewport import ViewportEffect
from taut_tui.widgets import TautComposer, TautOptionList

pytestmark = pytest.mark.sqlite_only


@dataclass(slots=True)
class HandlerContext:
    app: TautApp
    pilot: Any
    db_path: Path
    message_ts: int
    alice_token: str
    monkeypatch: pytest.MonkeyPatch
    scope: CompletionScope = field(default_factory=CompletionScope)
    deadline: float = 0
    submit_generation: int = 0
    screens: ScreenCompletions = field(init=False)

    def __post_init__(self) -> None:
        self.screens = ScreenCompletions(self.app, self.scope, self.monkeypatch)


HandlerCase = Callable[[HandlerContext], Awaitable[None]]


async def _applied(
    context: HandlerContext,
    method: str,
    trigger: Callable[[], Awaitable[Any]],
    *,
    producer: Any = None,
) -> Any:
    with context.monkeypatch.context() as patch:
        screen = context.app.screen
        observed = AppliedRequest(
            context.scope,
            patch,
            context.app,
            context.app._domain if producer is None else producer,
            method,
        )
        result = await trigger()
        await observed.wait(context.deadline)
        if (
            isinstance(screen, NativeFormScreen)
            and screen not in context.app.screen_stack
        ):
            await context.screens.retired(screen).wait(
                deadline=context.deadline, description="completed form retired"
            )
        return result


def _successful_conversation(
    future: Future[ConversationSnapshot | None],
) -> ConversationSnapshot | None:
    if future.cancelled() or future.exception() is not None:
        return None
    return future.result()


def _inspector(context: HandlerContext) -> str:
    return str(context.app.query_one("#inspector-body").render())


def _observe(context: HandlerContext, *, as_name: str = "alice") -> TautClient:
    return TautClient(db_path=context.db_path, as_name=as_name)


def _is_joined(context: HandlerContext, channel: str) -> bool:
    observer = _observe(context)
    try:
        return channel in observer.joined_thread_names()
    finally:
        observer.close()


def _topic_is(context: HandlerContext, expected: str | None) -> bool:
    observer = _observe(context)
    try:
        return observer.get_channel("general").topic == expected
    finally:
        observer.close()


def _thread_has_text(context: HandlerContext, thread: str, text: str) -> bool:
    observer = _observe(context)
    try:
        try:
            messages = observer.log(thread)
        except EmptyResultError:
            return False
        return any(message.text == text for message in messages)
    finally:
        observer.close()


async def _select_palette(context: HandlerContext, action_id: ActionId) -> None:
    assert ActionRoute.PALETTE in action_spec(action_id).routes
    deadline = context.scope.now() + 5
    context.app.action_open_command()
    screen = context.app.screen
    assert isinstance(screen, CommandPaletteScreen)
    await context.screens.ready(screen, deadline=deadline)
    with context.monkeypatch.context() as patch:
        await palette_query(context.scope, patch, screen, action_id.value)
    options = screen.query_one("#palette-results", OptionList)
    option_index = next(
        index
        for index in range(options.option_count)
        if options.get_option_at_index(index).id == action_id.value
    )
    assert options.get_option_at_index(option_index).disabled is False
    options.highlighted = option_index
    context.deadline = context.scope.now() + 5
    options.action_select()
    await context.screens.result_applied(screen).wait(
        deadline=context.deadline, description="palette action dispatched"
    )
    await context.screens.retired(screen).wait(
        deadline=context.deadline, description="palette retired"
    )
    if context.app.is_running and context.app.screen is not context.app._base_screen:
        await context.screens.ready(context.app.screen, deadline=context.deadline)


async def _open_general(context: HandlerContext) -> None:
    observed_snapshots: list[ConversationSnapshot | None] = []
    apply_optional_conversation = context.app._apply_optional_conversation
    expected_intent = context.app._conversation_intent + 1
    conversation_applied = context.scope.expect(
        CompletionKey(context.app, "conversation.applied", generation=expected_intent)
    )

    def observe_general(
        intent: int,
        future: Future[ConversationSnapshot | None],
    ) -> None:
        apply_optional_conversation(intent, future)
        if intent == expected_intent:
            observed_snapshots.append(_successful_conversation(future))
            conversation_applied.succeed(conversation_applied.key, future)

    with context.monkeypatch.context() as patch:
        patch.setattr(
            context.app,
            "_apply_optional_conversation",
            observe_general,
        )
        deadline = context.scope.now() + 5
        context.app._dispatch_tui_action(
            ActionId.CONVERSATION_OPEN,
            source=ActionRoute.NAVIGATION,
            context=ActionContext(
                target="general",
                target_label="#general",
                surface=LogicalSurface.NAVIGATION,
            ),
        )
        await conversation_applied.wait(
            deadline=deadline, description="general applied"
        )
    assert len(observed_snapshots) == 1
    snapshot = observed_snapshots[0]
    assert snapshot is not None
    assert snapshot.intent_token == expected_intent
    assert snapshot.target == "general"
    assert any(message.ts == context.message_ts for message in snapshot.messages)
    assert context.app.visual_state.active_conversation == "general"


async def _select_message(context: HandlerContext) -> None:
    await _open_general(context)
    assert any(row.ts == context.message_ts for row in context.app._message_rows)
    context.app.visual_state = replace(
        context.app.visual_state,
        selected_message_id=context.message_ts,
    )


async def _submit_form(
    context: HandlerContext,
    values: dict[str, str],
) -> NativeFormScreen:
    assert isinstance(context.app.screen, NativeFormScreen)
    screen = context.app.screen
    for field_id, value in values.items():
        selector = f"#field-{field_id.replace('_', '-')}"
        screen.query_one(selector, Input).value = value
    context.submit_generation += 1
    submitted = context.scope.expect(
        CompletionKey(
            context.app,
            "form.submitted",
            request=screen,
            generation=context.submit_generation,
        )
    )
    original_complete = context.app._complete_form
    expected_screen = screen

    def complete(submission: Any, *, screen: NativeFormScreen) -> None:
        original_complete(submission, screen=screen)
        if screen is expected_screen:
            submitted.succeed(submitted.key, submission)

    with context.monkeypatch.context() as patch:
        patch.setattr(context.app, "_complete_form", complete)
        context.deadline = context.scope.now() + 5
        screen.query_one("#form-submit", Button).press()
        await submitted.wait(deadline=context.deadline, description="form submitted")
    if (
        context.app.screen is not screen
        and context.app.screen is not context.app._base_screen
    ):
        await context.screens.ready(context.app.screen, deadline=context.deadline)
    return screen


async def _cancel_confirmation(context: HandlerContext, exact_target: str) -> None:
    await _resolve_confirmation(context, exact_target, confirmed=False)


async def _accept_confirmation(context: HandlerContext, exact_target: str) -> None:
    await _resolve_confirmation(context, exact_target, confirmed=True)


async def _resolve_confirmation(
    context: HandlerContext, exact_target: str, *, confirmed: bool
) -> None:
    screen = context.app.screen
    assert isinstance(screen, ConfirmationScreen)
    assert exact_target in screen.prompt
    await context.screens.ready(screen, deadline=context.deadline)
    context.deadline = context.scope.now() + 5
    control = "#confirmation-confirm" if confirmed else "#confirmation-cancel"
    screen.query_one(control, Button).press()
    assert (
        await context.screens.result_applied(screen).wait(
            deadline=context.deadline, description="confirmation result applied"
        )
        is confirmed
    )
    await context.screens.retired(screen).wait(
        deadline=context.deadline, description="confirmation retired"
    )


async def _submit_modal(context: HandlerContext, selector: str) -> None:
    screen = context.app.screen
    context.deadline = context.scope.now() + 5
    screen.query_one(selector, Button).press()
    await context.screens.result_applied(screen).wait(
        deadline=context.deadline, description="modal result applied"
    )
    await context.screens.retired(screen).wait(
        deadline=context.deadline, description="modal retired"
    )
    if context.app.screen is not context.app._base_screen:
        await context.screens.ready(context.app.screen, deadline=context.deadline)


async def _workspace_initialize(context: HandlerContext) -> None:
    assert not context.db_path.exists()
    with context.monkeypatch.context() as patch:
        observed = AppliedRequest(
            context.scope,
            patch,
            context.app,
            context.app._domain,
            "initialize_workspace",
        )
        await _select_palette(context, ActionId.WORKSPACE_INITIALIZE)
        await observed.wait(context.deadline)
    future = observed.future
    assert future is not None
    assert not future.cancelled()
    assert future.exception() is None
    assert future.result() == InitResult(db=str(context.db_path), created=True)
    assert context.db_path.is_file()
    assert "Workspace created" in _inspector(context)


async def _identity_rejoin(context: HandlerContext) -> None:
    await _select_palette(context, ActionId.IDENTITY_REJOIN)
    await _applied(
        context,
        "rejoin_identity",
        lambda: _submit_form(
            context, {"name_or_alias": "", "continuity_token": context.alice_token}
        ),
    )
    assert not isinstance(context.app.screen, NativeFormScreen)
    assert context.app._domain is not None
    deadline = context.scope.now() + 5
    identity = context.scope.observe_future(
        context.app._domain.show_identity(),
        owner=context.app._domain,
        phase="identity.verification",
    )
    assert (
        await identity.wait(deadline=deadline, description="rejoined identity")
    ).name == "alice"


async def _identity_show(context: HandlerContext) -> None:
    await _applied(
        context,
        "show_identity",
        lambda: _select_palette(context, ActionId.IDENTITY_SHOW),
    )
    assert "alice" in _inspector(context)


async def _identity_set_name(context: HandlerContext) -> None:
    await _select_palette(context, ActionId.IDENTITY_SET_NAME)
    await _applied(
        context, "set_name", lambda: _submit_form(context, {"name": "alice-renamed"})
    )
    assert "alice-renamed" in _inspector(context)
    observer = _observe(context, as_name="alice-renamed")
    try:
        assert observer.whoami().name == "alice-renamed"
    finally:
        observer.close()


async def _identity_set_persona(context: HandlerContext) -> None:
    await _select_palette(context, ActionId.IDENTITY_SET_PERSONA)
    await _applied(
        context, "set_persona", lambda: _submit_form(context, {"persona": "reviewer"})
    )
    assert "reviewer" in _inspector(context)
    observer = _observe(context)
    try:
        assert observer.whoami().persona == "reviewer"
    finally:
        observer.close()


async def _conversation_open(context: HandlerContext) -> None:
    context.app.visual_state = replace(
        context.app.visual_state,
        selected_navigation="general",
    )
    await _applied(
        context,
        "open_conversation",
        lambda: _select_palette(context, ActionId.CONVERSATION_OPEN),
    )
    assert context.app.visual_state.active_conversation == "general"


async def _channel_join(context: HandlerContext) -> None:
    await _select_palette(context, ActionId.CHANNEL_JOIN)
    await _applied(
        context,
        "join_channel",
        lambda: _submit_form(context, {"channel": "joined-by-handler"}),
    )
    assert not isinstance(context.app.screen, NativeFormScreen)
    observer = _observe(context)
    try:
        assert "joined-by-handler" in observer.joined_thread_names()
    finally:
        observer.close()


async def _channel_leave(context: HandlerContext) -> None:
    await _open_general(context)
    await _select_palette(context, ActionId.CHANNEL_LEAVE)
    await _cancel_confirmation(context, "general")
    observer = _observe(context)
    try:
        assert "general" in observer.joined_thread_names()
    finally:
        observer.close()
    await _select_palette(context, ActionId.CHANNEL_LEAVE)
    await _applied(
        context, "leave_channel", lambda: _accept_confirmation(context, "general")
    )
    assert not _is_joined(context, "general")


async def _direct_message_start(context: HandlerContext) -> None:
    await _select_palette(context, ActionId.DIRECT_MESSAGE_START)
    await _applied(
        context,
        "start_direct_message",
        lambda: _submit_form(context, {"member": "bob", "message": "private hello"}),
    )
    assert not isinstance(context.app.screen, NativeFormScreen)
    observer = _observe(context)
    try:
        assert any(
            thread.name.startswith("dm.") for thread in observer.list_direct_messages()
        )
    finally:
        observer.close()


async def _notifications_open(context: HandlerContext) -> None:
    await _select_palette(context, ActionId.NOTIFICATIONS_OPEN)
    inspector = context.app.visual_state.inspector
    assert inspector is not None
    assert inspector.kind is InspectorKind.NOTIFICATIONS
    assert "Notification" in _inspector(context) or "No notifications" in _inspector(
        context
    )


async def _members_open(context: HandlerContext) -> None:
    await _open_general(context)
    await _applied(
        context, "members", lambda: _select_palette(context, ActionId.MEMBERS_OPEN)
    )
    assert "alice" in _inspector(context) and "bob" in _inspector(context)


async def _channel_show_topic(context: HandlerContext) -> None:
    await _open_general(context)
    await _applied(
        context,
        "show_topic",
        lambda: _select_palette(context, ActionId.CHANNEL_SHOW_TOPIC),
    )
    assert "Initial topic" in _inspector(context)


async def _channel_set_topic(context: HandlerContext) -> None:
    await _open_general(context)
    await _select_palette(context, ActionId.CHANNEL_SET_TOPIC)
    await _applied(
        context, "set_topic", lambda: _submit_form(context, {"topic": "Changed topic"})
    )
    assert "Changed topic" in _inspector(context)
    observer = _observe(context)
    try:
        assert observer.get_channel("general").topic == "Changed topic"
    finally:
        observer.close()


async def _channel_clear_topic(context: HandlerContext) -> None:
    await _open_general(context)
    await _applied(
        context,
        "clear_topic",
        lambda: _select_palette(context, ActionId.CHANNEL_CLEAR_TOPIC),
    )
    assert _topic_is(context, None)
    observer = _observe(context)
    try:
        assert observer.get_channel("general").topic is None
    finally:
        observer.close()


async def _channel_rename(context: HandlerContext) -> None:
    await _open_general(context)
    observer = _observe(context)
    try:
        observer.reply("general", str(context.message_ts), "reply before rename")
    finally:
        observer.close()
    context.app.visual_state = replace(
        context.app.visual_state.with_draft(
            DraftState(
                target="general",
                text="first line\nsecond line",
                cursor_position=6,
                revision=4,
            )
        ),
        open_reply_thread=f"general.{context.message_ts}",
    )
    composer = context.app.query_one("#composer", TautComposer)
    composer.text = "first line\nsecond line"
    composer.cursor_position = 6
    await _select_palette(context, ActionId.CHANNEL_RENAME)
    form = await _submit_form(context, {"new_name": "renamed-channel"})
    await _cancel_confirmation(context, "general")
    assert isinstance(context.app.screen, NativeFormScreen)
    assert context.app.screen is form
    observer = _observe(context)
    try:
        assert observer.get_channel("general").name == "general"
    finally:
        observer.close()
    await _submit_form(context, {})
    with context.monkeypatch.context() as patch:
        reopened = AppliedRequest(
            context.scope, patch, context.app, context.app._session, "open_conversation"
        )
        await _applied(
            context, "rename_channel", lambda: _accept_confirmation(context, "general")
        )
        await reopened.wait(context.deadline)
    assert context.app.visual_state.active_conversation == "renamed-channel"
    draft = context.app.visual_state.draft_for("renamed-channel")
    assert draft == DraftState(
        target="renamed-channel",
        text="first line\nsecond line",
        cursor_position=6,
        revision=4,
    )
    assert context.app.visual_state.open_reply_thread == (
        f"renamed-channel.{context.message_ts}"
    )
    assert composer.text == draft.text
    assert composer.cursor_position == draft.cursor_position
    observer = _observe(context)
    try:
        assert observer.get_channel("renamed-channel").name == "renamed-channel"
    finally:
        observer.close()

    async def send() -> None:
        context.deadline = context.scope.now() + 5
        composer.action_submit()

    await _applied(context, "send_message", send)
    assert _thread_has_text(context, "renamed-channel", "first line\nsecond line")
    generation = context.app.visual_state.model_generation
    delivered = context.scope.expect(
        CompletionKey(context.app, "incoming.applied", generation=generation)
    )
    incoming_ts: int | None = None
    original_delivery = context.app._apply_delivery

    def observe_delivery(delivery_generation: int, item: Any) -> bool:
        accepted = original_delivery(delivery_generation, item)
        if (
            delivery_generation == generation
            and getattr(item, "ts", None) == incoming_ts
        ):
            assert accepted
            delivered.succeed(delivered.key, item)
        return accepted

    with context.monkeypatch.context() as patch:
        patch.setattr(context.app, "_apply_delivery", observe_delivery)
        observer = _observe(context, as_name="bob")
        try:
            deadline = context.scope.now() + 5
            incoming_ts = observer.say("renamed-channel", "incoming after rename").ts
        finally:
            observer.close()
        await delivered.wait(
            deadline=deadline, description="renamed conversation delivery"
        )
    assert any(row.text == "incoming after rename" for row in context.app._message_rows)


async def _draft_recover(context: HandlerContext) -> None:
    context.app.visual_state = (
        context.app.visual_state.with_draft(DraftState("general", "source"))
        .with_draft(DraftState("ops", "displaced"))
        .after_channel_rename("general", "ops", remap_open_view=False)
    )
    await _select_palette(context, ActionId.DRAFT_RECOVER)
    assert isinstance(context.app.screen, DraftRecoveryScreen)
    await context.pilot.press("escape")


async def _compose_enter(context: HandlerContext) -> None:
    await _open_general(context)
    with context.monkeypatch.context() as patch:
        focused = observe_focus(
            context.scope,
            patch,
            context.app,
            context.app.query_one("#composer", TautComposer),
        )
        await _select_palette(context, ActionId.COMPOSE_ENTER)
        await focused.wait(
            deadline=context.deadline, description="compose action focus applied"
        )
    assert context.app.visual_state.mode is InteractionMode.COMPOSE
    assert context.app.query_one("#composer", TautComposer).has_focus
    assert context.app.query_one("#composer", TautComposer).text == ""


async def _message_send(context: HandlerContext) -> None:
    await _open_general(context)
    composer = context.app.query_one("#composer", TautComposer)
    with context.monkeypatch.context() as patch:
        await focus_widget(context.scope, patch, context.app, composer)
    assert composer.has_focus
    assert context.app.visual_state.mode is InteractionMode.COMPOSE
    await context.pilot.press(*"handler-send")
    assert composer.text == "handler-send"
    await context.pilot.press("escape")
    await _applied(
        context, "send_message", lambda: _select_palette(context, ActionId.MESSAGE_SEND)
    )
    assert _thread_has_text(context, "general", "handler-send")


async def _message_reply(context: HandlerContext) -> None:
    await _select_message(context)
    await _select_palette(context, ActionId.MESSAGE_REPLY)
    await _applied(
        context,
        "reply_message",
        lambda: _submit_form(context, {"message": "handler reply"}),
    )
    assert _thread_has_text(context, f"general.{context.message_ts}", "handler reply")


async def _message_react(context: HandlerContext) -> None:
    await _select_message(context)
    await _select_palette(context, ActionId.MESSAGE_REACT)
    await _applied(
        context, "react_message", lambda: _submit_form(context, {"reaction": "ack"})
    )
    assert "Reaction ack added" in _inspector(context)
    observer = _observe(context, as_name="bob")
    try:
        reactions = [
            notification
            for notification in observer.peek_inbox()
            if notification.type == "reaction"
        ]
        assert len(reactions) == 1
        assert reactions[0].message_ts == context.message_ts
        assert reactions[0].reaction == "ack"
    finally:
        observer.close()


async def _message_delete(context: HandlerContext) -> None:
    await _select_message(context)
    await _select_palette(context, ActionId.MESSAGE_DELETE)
    await _cancel_confirmation(context, str(context.message_ts))
    observer = _observe(context)
    try:
        assert observer.show_message(str(context.message_ts)).ts == context.message_ts
    finally:
        observer.close()
    await _select_palette(context, ActionId.MESSAGE_DELETE)
    await _applied(
        context,
        "delete_message",
        lambda: _accept_confirmation(context, str(context.message_ts)),
    )
    assert "Deleted message" in _inspector(context)
    observer = _observe(context)
    try:
        with pytest.raises(NotFoundError):
            observer.show_message(str(context.message_ts))
    finally:
        observer.close()


async def _search_open(context: HandlerContext) -> None:
    await _select_palette(context, ActionId.SEARCH_OPEN)
    assert isinstance(context.app.screen, SearchScreen)
    assert context.app.visual_state.mode is InteractionMode.SEARCH


async def _search_open_result(context: HandlerContext) -> None:
    await _open_general(context)
    observer = _observe(context)
    try:
        context.app._selected_search_hit = observer.search("seed handler message")[0]
    finally:
        observer.close()
    completed_search_anchors: list[int | None] = []
    observed_snapshots: list[ConversationSnapshot | None] = []
    apply_optional_conversation = context.app._apply_optional_conversation
    apply_viewport_effect = context.app._apply_viewport_effect
    expected_intent = context.app._conversation_intent + 1
    search_context_applied = context.scope.expect(
        CompletionKey(context.app, "search.context-applied", generation=expected_intent)
    )
    navigation: Future[NavigationSnapshot] = Future()
    navigation.set_result(NavigationSnapshot((), (), ()))
    navigation_refresh_applied = context.scope.expect(
        CompletionKey(context.app, "search.navigation-applied", request=navigation)
    )
    search_anchor_restore_finished = context.scope.expect(
        CompletionKey(context.app, "search.anchor-restored", generation=expected_intent)
    )

    def observe_search_context(
        intent: int,
        future: Future[ConversationSnapshot | None],
    ) -> None:
        apply_optional_conversation(intent, future)
        snapshot = _successful_conversation(future)
        if intent == expected_intent:
            if snapshot is not None:
                observed_snapshots.append(snapshot)
            # Reproduce navigation refresh landing after logical search
            # ownership is committed but before deferred physical restore.
            context.app._apply_navigation_result(navigation)
            navigation_refresh_applied.succeed(
                navigation_refresh_applied.key, navigation
            )
            search_context_applied.succeed(search_context_applied.key, future)

    def observe_viewport_effect(
        effect: ViewportEffect,
        messages: tuple[Any, ...],
    ) -> None:
        before = context.app.visual_state.viewport
        owned_transition_ready = (
            before.search_owned
            and before.intent == expected_intent
            and before.message_id == context.message_ts
            and before.accepts(effect)
            and not context.app._shutting_down
        )
        apply_viewport_effect(effect, messages)
        viewport = context.app.visual_state.viewport
        if (
            owned_transition_ready
            and effect.message_id == context.message_ts
            and not viewport.search_owned
            and viewport.message_id == context.message_ts
        ):
            completed_search_anchors.append(viewport.message_id)
            search_anchor_restore_finished.succeed(
                search_anchor_restore_finished.key, effect
            )

    with context.monkeypatch.context() as patch:
        patch.setattr(
            context.app,
            "_apply_optional_conversation",
            observe_search_context,
        )
        patch.setattr(
            context.app,
            "_apply_viewport_effect",
            observe_viewport_effect,
        )
        await _select_palette(context, ActionId.SEARCH_OPEN_RESULT)
        await search_context_applied.wait(
            deadline=context.deadline, description="search context applied"
        )
        await navigation_refresh_applied.wait(
            deadline=context.deadline, description="interleaved navigation applied"
        )
        await search_anchor_restore_finished.wait(
            deadline=context.deadline, description="owned search anchor restored"
        )
    assert context.app.visual_state.viewport.search_owned is False
    assert completed_search_anchors == [context.message_ts]
    assert len(observed_snapshots) == 1
    snapshot = observed_snapshots[0]
    assert snapshot is not None
    assert snapshot.intent_token == expected_intent
    assert snapshot.target == "general"
    assert any(message.ts == context.message_ts for message in snapshot.messages)
    assert any(message.ts > context.message_ts for message in snapshot.messages)
    assert any(row.ts == context.message_ts for row in context.app._message_rows)
    assert context.app.visual_state.active_conversation == "general"
    assert context.app.visual_state.selected_message_id == context.message_ts
    # One finite framework refresh fence follows the exact accepted restore;
    # it is only for measured row geometry, never worker/search liveness.
    await context.pilot.pause()
    assert ActionId.NOTIFICATIONS_OPEN in context.app._navigation_targets
    assert context.app.visual_state.viewport.search_owned is False
    transcript = context.app.query_one("#transcript", TautOptionList)
    viewport_top = int(transcript.scroll_offset.y)
    viewport_bottom = viewport_top + transcript.scrollable_content_region.height
    rendered_lines = transcript._lines
    target_index = next(
        index
        for index, message in enumerate(context.app._message_rows)
        if message.ts == context.message_ts
    )
    visible_option_indexes = {
        option_index
        for option_index, _line_offset in rendered_lines[viewport_top:viewport_bottom]
    }
    assert target_index in visible_option_indexes
    tail_pinned = transcript.is_vertical_scroll_end
    expected_anchor = (
        None
        if tail_pinned
        else context.app._message_rows[rendered_lines[viewport_top][0]].ts
    )
    context.app._capture_settled_transcript_viewport()
    assert context.app.visual_state.viewport.tail_pinned is tail_pinned
    assert context.app.visual_state.viewport.message_id == expected_anchor


async def _system_doctor(context: HandlerContext) -> None:
    await _applied(
        context, "doctor", lambda: _select_palette(context, ActionId.SYSTEM_DOCTOR)
    )
    assert "System doctor" in _inspector(context)


async def _system_dump(context: HandlerContext) -> None:
    output = context.db_path.with_suffix(".dump.json")
    output.write_text("sentinel", encoding="utf-8")
    await _select_palette(context, ActionId.SYSTEM_DUMP)
    form = await _submit_form(context, {"output_path": str(output)})
    await _cancel_confirmation(context, str(output))
    assert output.read_text(encoding="utf-8") == "sentinel"
    assert isinstance(context.app.screen, NativeFormScreen)
    assert context.app.screen is form
    await _submit_form(context, {})
    await _applied(context, "dump", lambda: _accept_confirmation(context, str(output)))
    assert output.read_text(encoding="utf-8") != "sentinel"
    assert output.stat().st_size > 0


async def _system_load_help(context: HandlerContext) -> None:
    source = context.db_path.with_suffix(".input.json")
    await _select_palette(context, ActionId.SYSTEM_LOAD_HELP)
    await _submit_form(context, {"input_path": str(source)})
    assert "system load" in _inspector(context)
    assert str(source) in _inspector(context)
    assert not source.exists()


async def _command_open(context: HandlerContext) -> None:
    deadline = context.scope.now() + 5
    await context.pilot.press("ctrl+p")
    await context.screens.ready(context.app.screen, deadline=deadline)
    assert isinstance(context.app.screen, CommandPaletteScreen)
    assert context.app.visual_state.mode is InteractionMode.COMMAND


async def _help_open(context: HandlerContext) -> None:
    await _select_palette(context, ActionId.HELP_OPEN)
    assert "Ctrl-P or Actions opens the action browser" in _inspector(context)


async def _application_quit(context: HandlerContext) -> None:
    await _select_palette(context, ActionId.APPLICATION_QUIT)
    # A single Pilot fence drains the already-issued ExitApp event. It does
    # not wait for domain work; run_test remains the shutdown/cleanup owner.
    await context.pilot.pause()
    assert not context.app.is_running


class _SummonMember:
    member_id = "m_summoned"
    name = "actual-summoned"
    provider = "scripted"


class _SummonHandle:
    member = _SummonMember()

    def request_stop(self) -> None:
        return


class _SummonController:
    def __init__(self) -> None:
        self.release = Event()
        self.ready = Event()
        self.stopped: list[str] = []

    def provider_names(self) -> tuple[str, ...]:
        return ("scripted",)

    def list_live(self) -> tuple[object, ...]:
        return (_SummonMember(),)

    def status(self, name: str) -> object:
        return ("status", name)

    def stop(self, name: str) -> object:
        self.stopped.append(name)
        return ("stop", name)

    def run_foreground(
        self,
        request: object,
        interaction: object,
        *,
        install_signal_handlers: bool,
        on_ready: Callable[[Any], None],
    ) -> None:
        del request, interaction
        assert install_signal_handlers is False
        on_ready(_SummonHandle())
        self.ready.set()
        assert self.release.wait(5)


def _install_summon(
    context: HandlerContext,
) -> tuple[_SummonController, TuiSummonOperations]:
    if context.app._summon is not None:
        context.app._summon.close()
    controller = _SummonController()
    operations = TuiSummonOperations(
        controller=controller,
        ready_callback=context.app._accept_summon_ready_from_worker,
    )
    context.app._summon = operations
    context.app._summon_interaction = TuiSummonInteraction(context.app)
    return controller, operations


async def _summon_start(context: HandlerContext) -> None:
    controller, operations = _install_summon(context)
    try:
        await _select_palette(context, ActionId.SUMMON_START)
        assert isinstance(context.app.screen, SummonStartScreen)
        context.app.screen.query_one("#summon-name", Input).value = "requested"
        context.app.screen.query_one("#summon-provider", Select).value = "scripted"
        with context.monkeypatch.context() as patch:
            started = context.scope.expect(
                CompletionKey(operations, "summon.started", request=controller)
            )
            ready = None
            owned_token: str | None = None
            original_start = operations.start
            original_ready = context.app._apply_summon_ready

            def start(*args: Any, **kwargs: Any) -> Any:
                nonlocal ready, owned_token
                owned_token, future = original_start(*args, **kwargs)
                ready = context.scope.expect(
                    CompletionKey(
                        context.app, "summon.ready-applied", request=owned_token
                    )
                )
                started.succeed(started.key, ready)
                return owned_token, future

            def apply_ready(run: Any) -> None:
                original_ready(run)
                if run.token == owned_token:
                    assert ready is not None
                    assert owned_token in context.app._owned_summon_tokens
                    ready.succeed(ready.key, run)

            patch.setattr(operations, "start", start)
            patch.setattr(context.app, "_apply_summon_ready", apply_ready)
            await _submit_modal(context, "#summon-submit")
            deadline = context.deadline
            ready = await started.wait(deadline=deadline, description="summon started")
            await ready.wait(deadline=deadline, description="summon readiness applied")
        assert controller.ready.is_set()
        assert operations.owned_runs()[0].member_name == "actual-summoned"
        assert context.app._owned_summon_tokens
    finally:
        controller.release.set()
        operations.close()


async def _summon_list(context: HandlerContext) -> None:
    controller, operations = _install_summon(context)
    try:
        await _applied(
            context,
            "submit_list",
            lambda: _select_palette(context, ActionId.SUMMON_LIST),
            producer=operations,
        )
        assert "actual-summoned" in _inspector(context)
    finally:
        controller.release.set()
        operations.close()


async def _summon_status(context: HandlerContext) -> None:
    controller, operations = _install_summon(context)
    try:
        await _select_palette(context, ActionId.SUMMON_STATUS)
        assert isinstance(context.app.screen, NamedActionScreen)
        context.app.screen.query_one(
            "#summon-member-name", Input
        ).value = "actual-summoned"
        await _applied(
            context,
            "submit_status",
            lambda: _submit_modal(context, "#named-action-submit"),
            producer=operations,
        )
        assert "actual-summoned" in _inspector(context)
    finally:
        controller.release.set()
        operations.close()


async def _summon_dismiss(context: HandlerContext) -> None:
    controller, operations = _install_summon(context)
    try:
        await _select_palette(context, ActionId.SUMMON_DISMISS)
        assert isinstance(context.app.screen, NamedActionScreen)
        context.app.screen.query_one(
            "#summon-member-name", Input
        ).value = "actual-summoned"
        await _submit_modal(context, "#named-action-submit")
        await _cancel_confirmation(context, "actual-summoned")
        assert controller.stopped == []
        await _select_palette(context, ActionId.SUMMON_DISMISS)
        context.app.screen.query_one(
            "#summon-member-name", Input
        ).value = "actual-summoned"
        await _submit_modal(context, "#named-action-submit")
        await _applied(
            context,
            "submit_stop",
            lambda: _accept_confirmation(context, "actual-summoned"),
            producer=operations,
        )
        assert controller.stopped == ["actual-summoned"]
    finally:
        controller.release.set()
        operations.close()


HANDLER_CASES: dict[ActionId, HandlerCase] = {
    ActionId.WORKSPACE_INITIALIZE: _workspace_initialize,
    ActionId.IDENTITY_REJOIN: _identity_rejoin,
    ActionId.IDENTITY_SHOW: _identity_show,
    ActionId.IDENTITY_SET_NAME: _identity_set_name,
    ActionId.IDENTITY_SET_PERSONA: _identity_set_persona,
    ActionId.CONVERSATION_OPEN: _conversation_open,
    ActionId.CHANNEL_JOIN: _channel_join,
    ActionId.CHANNEL_LEAVE: _channel_leave,
    ActionId.DIRECT_MESSAGE_START: _direct_message_start,
    ActionId.NOTIFICATIONS_OPEN: _notifications_open,
    ActionId.MEMBERS_OPEN: _members_open,
    ActionId.CHANNEL_SHOW_TOPIC: _channel_show_topic,
    ActionId.CHANNEL_SET_TOPIC: _channel_set_topic,
    ActionId.CHANNEL_CLEAR_TOPIC: _channel_clear_topic,
    ActionId.CHANNEL_RENAME: _channel_rename,
    ActionId.DRAFT_RECOVER: _draft_recover,
    ActionId.COMPOSE_ENTER: _compose_enter,
    ActionId.MESSAGE_SEND: _message_send,
    ActionId.MESSAGE_REPLY: _message_reply,
    ActionId.MESSAGE_REACT: _message_react,
    ActionId.MESSAGE_DELETE: _message_delete,
    ActionId.SEARCH_OPEN: _search_open,
    ActionId.SEARCH_OPEN_RESULT: _search_open_result,
    ActionId.SYSTEM_DOCTOR: _system_doctor,
    ActionId.SYSTEM_DUMP: _system_dump,
    ActionId.SYSTEM_LOAD_HELP: _system_load_help,
    ActionId.COMMAND_OPEN: _command_open,
    ActionId.HELP_OPEN: _help_open,
    ActionId.APPLICATION_QUIT: _application_quit,
    ActionId.SUMMON_START: _summon_start,
    ActionId.SUMMON_LIST: _summon_list,
    ActionId.SUMMON_STATUS: _summon_status,
    ActionId.SUMMON_DISMISS: _summon_dismiss,
}


def test_handler_case_registry_is_exact() -> None:
    assert set(HANDLER_CASES) == set(ActionId)
    assert len(HANDLER_CASES) == len(ActionId)


def test_action_completion_waits_for_real_application_not_worker_return(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A completed worker cannot satisfy the UI-application phase."""

    async def exercise() -> None:
        db_path = tmp_path / "held-application.db"
        TautClient.init(db_path=db_path)
        client = TautClient(db_path=db_path, as_name="alice")
        try:
            client.join("general")
        finally:
            client.close()
        app = TautApp(db_path=str(db_path), as_name="alice", continuity_token=None)
        scope = CompletionScope()
        try:
            async with app.run_test(size=(120, 36)):
                assert app._domain is not None
                original_watch = app._watch_future
                request = object()
                queued = scope.expect(
                    CompletionKey(app, "test.application-held", request=request)
                )
                held: list[tuple[Callable[[Future[Any]], None], Future[Any]]] = []

                def hold_application(
                    future: Future[Any], apply: Callable[[Future[Any]], None]
                ) -> None:
                    def hold(done: Future[Any]) -> None:
                        held.append((apply, done))
                        queued.succeed(queued.key, None)

                    original_watch(future, hold)

                with monkeypatch.context() as patch:
                    patch.setattr(app, "_watch_future", hold_application)
                    outcome = AppliedRequest(
                        scope, patch, app, app._domain, "show_identity"
                    )
                    deadline = scope.now() + 5
                    app._dispatch_tui_action(
                        ActionId.IDENTITY_SHOW, source=ActionRoute.PALETTE
                    )
                    await queued.wait(deadline=deadline, description="apply queued")
                    assert outcome.source is not None
                    await outcome.source.wait(
                        deadline=deadline, description="identity worker returned"
                    )
                    assert outcome.applied is not None
                    assert outcome.applied.snapshot() is None
                    assert "alice" not in str(app.query_one("#inspector-body").render())
                    assert len(held) == 1
                    apply, done = held[0]
                    app.call_later(apply, done)
                    result = await outcome.wait(deadline)
                    assert result.name == "alice"
                    assert "alice" in str(app.query_one("#inspector-body").render())
        finally:
            scope.close()

    asyncio.run(exercise())


def test_action_completion_preserves_synchronous_producer_refusal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def exercise() -> None:
        output = tmp_path / "existing.json"
        output.write_text("sentinel", encoding="utf-8")
        app = TautApp(
            db_path=str(tmp_path / "refusal.db"), as_name=None, continuity_token=None
        )
        with CompletionScope() as scope, monkeypatch.context() as patch:
            async with app.run_test():
                assert app._domain is not None
                outcome = AppliedRequest(scope, patch, app, app._domain, "dump")
                deadline = scope.now() + 5
                app._submit_dump(app._domain, output)
                with pytest.raises(ReplacementConfirmationRequired) as refused:
                    await outcome.wait(deadline)
                assert refused.value.path == output
                assert "already exists" in str(
                    app.query_one("#inspector-body").render()
                )
                assert output.read_text(encoding="utf-8") == "sentinel"
                assert outcome.future is None

    asyncio.run(exercise())


@pytest.mark.parametrize("retained", [False, True])
def test_focus_observer_records_first_readiness_and_allows_real_refocus(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, retained: bool
) -> None:
    async def exercise() -> None:
        app = TautApp(
            db_path=str(tmp_path / "focus.db"), as_name=None, continuity_token=None
        )
        async with app.run_test():
            composer = app.query_one("#composer", TautComposer)
            if retained:
                with CompletionScope() as setup, monkeypatch.context() as setup_patch:
                    await focus_widget(setup, setup_patch, app, composer)
            with CompletionScope() as scope, monkeypatch.context() as patch:
                first = observe_focus(scope, patch, app, composer)
                deadline = scope.now() + 5
                composer.focus()
                assert (
                    await first.wait(deadline=deadline, description="first focus")
                    is composer
                )
                original_outcome = first.snapshot()
                navigation = app.query_one("#navigation-list", TautOptionList)
                await focus_widget(scope, patch, app, navigation)
                second = scope.expect(
                    CompletionKey(
                        app, "test.refocus-applied", request=composer, generation=2
                    )
                )
                original_dispatch = app._on_message

                async def refocused(event: Any) -> None:
                    await original_dispatch(event)
                    if (
                        isinstance(event, events.DescendantFocus)
                        and event.widget is composer
                    ):
                        second.succeed(second.key, composer)

                patch.setattr(app, "_on_message", refocused)
                deadline = scope.now() + 5
                composer.focus()
                await second.wait(deadline=deadline, description="real refocus")
                assert composer.has_focus
                assert app.visual_state.mode is InteractionMode.COMPOSE
                assert first.snapshot() is original_outcome
                scope.raise_if_invalid()

    asyncio.run(exercise())


def test_colon_command_line_executes_a_typed_native_core_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def exercise() -> None:
        db_path = tmp_path / "command-line.db"
        app = TautApp(db_path=str(db_path), as_name=None, continuity_token=None)
        with (
            CompletionScope() as scope,
            monkeypatch.context() as patch,
            ExitStack() as cleanup,
        ):
            screens = ScreenCompletions(app, scope, patch)
            cleanup.callback(screens.close)
            async with app.run_test(size=(120, 36)) as pilot:
                # run_test's ready callback follows the real app on_mount.
                assert app._domain is not None
                deadline = scope.now() + 5
                await pilot.press(":")
                screen = app.screen
                assert isinstance(screen, CommandLineScreen)
                await screens.ready(screen, deadline=deadline)
                await screens.ready(
                    screen,
                    deadline=deadline,
                    focus=screen.query_one("#command-line", Input),
                )
                observed = AppliedRequest(
                    scope, patch, app, app._domain, "initialize_workspace"
                )
                await pilot.press(*"init")
                deadline = scope.now() + 5
                await pilot.press("enter")
                await observed.wait(deadline)
                assert app._operation_state == "idle"
                assert (
                    "created" in str(app.query_one("#inspector-body").render()).lower()
                )

    asyncio.run(exercise())


def test_search_completion_counts_the_owned_transition_not_later_effects(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Later history restores and stale effects are not new search completions."""

    apply_effect = TautApp._apply_viewport_effect
    select_palette = _select_palette
    scope = CompletionScope()
    followup_phases: list[tuple[str, bool]] = []
    followups_finished = scope.expect(
        CompletionKey(apply_effect, "test.search-followups", request=followup_phases)
    )
    followups_queued = False

    def replay_after_search(
        app: TautApp,
        search_effect: ViewportEffect,
        messages: tuple[Any, ...],
    ) -> None:
        viewport, history_effect = app.visual_state.viewport.plan_render()
        assert history_effect is not None
        app.visual_state = replace(app.visual_state, viewport=viewport)
        for effect in (history_effect, search_effect):
            before = app.visual_state.viewport
            followup_phases.append((before.mode.value, before.accepts(effect)))
            app._apply_viewport_effect(effect, messages)
        followups_finished.succeed(followups_finished.key, None)

    def observe_effect(
        app: TautApp,
        effect: ViewportEffect,
        messages: tuple[Any, ...],
    ) -> None:
        nonlocal followups_queued
        before = app.visual_state.viewport
        apply_effect(app, effect, messages)
        if (
            not followups_queued
            and before.search_owned
            and before.accepts(effect)
            and not app.visual_state.viewport.search_owned
        ):
            followups_queued = True
            app.call_after_refresh(replay_after_search, app, effect, messages)

    async def select_and_observe_followups(
        context: HandlerContext,
        action_id: ActionId,
    ) -> None:
        await select_palette(context, action_id)
        if action_id is ActionId.SEARCH_OPEN_RESULT:
            await followups_finished.wait(
                deadline=context.deadline, description="forced later viewport callbacks"
            )

    monkeypatch.setattr(TautApp, "_apply_viewport_effect", observe_effect)
    monkeypatch.setitem(globals(), "_select_palette", select_and_observe_followups)
    try:
        test_every_action_reaches_a_concrete_handler(
            ActionId.SEARCH_OPEN_RESULT,
            tmp_path,
            monkeypatch,
        )
    finally:
        scope.close()
    assert followup_phases == [("history", True), ("history", False)]


@pytest.mark.parametrize(
    "command",
    (
        "system load --input backup.json",
        "watch general",
        "search --channel general phrase",
    ),
)
def test_colon_command_line_reports_cli_only_paths_and_options(
    command: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def exercise() -> None:
        app = TautApp(
            db_path=str(tmp_path / "command-line.db"),
            as_name=None,
            continuity_token=None,
        )
        with (
            CompletionScope() as scope,
            monkeypatch.context() as patch,
            ExitStack() as cleanup,
        ):
            screens = ScreenCompletions(app, scope, patch)
            cleanup.callback(screens.close)
            async with app.run_test(size=(120, 36)) as pilot:
                assert app._domain is not None
                deadline = scope.now() + 5
                await pilot.press(":")
                screen = app.screen
                await screens.ready(screen, deadline=deadline)
                await screens.ready(
                    screen,
                    deadline=deadline,
                    focus=screen.query_one("#command-line", Input),
                )
                await pilot.press(*command)
                dispatched = scope.expect(
                    CompletionKey(app, "command.dispatched", request=screen)
                )
                original_dispatch = app._dispatch_command_invocation

                def dispatch(invocation: Any) -> None:
                    original_dispatch(invocation)
                    dispatched.succeed(dispatched.key, invocation)

                patch.setattr(app, "_dispatch_command_invocation", dispatch)
                deadline = scope.now() + 5
                await pilot.press("enter")
                await dispatched.wait(
                    deadline=deadline, description="CLI-only command refused"
                )
                assert "CLI-only" in str(app.query_one("#inspector-body").render())

    asyncio.run(exercise())


@pytest.mark.parametrize("action_id", tuple(ActionId), ids=lambda item: item.value)
def test_every_action_reaches_a_concrete_handler(
    action_id: ActionId,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def exercise() -> None:
        db_path = tmp_path / f"{action_id.value}.db"
        message_ts = 0
        alice_token = ""
        if action_id is not ActionId.WORKSPACE_INITIALIZE:
            TautClient.init(db_path=db_path)
            alice = TautClient(db_path=db_path, as_name="alice")
            bob = TautClient(db_path=db_path, as_name="bob")
            try:
                alice.join("general")
                created = alice.last_created_member
                assert created is not None and created.token is not None
                alice_token = created.token
                bob.join("general")
                alice.set_channel_topic("general", "Initial topic")
                bob.say("general", "@alice handler notification")
                message_ts = alice.say("general", "seed handler message").ts
                if action_id is ActionId.SEARCH_OPEN_RESULT:
                    bob.say(
                        "general",
                        "\n".join(
                            f"post-search-anchor line {index}" for index in range(40)
                        ),
                    )
            finally:
                alice.close()
                bob.close()

        app = TautApp(
            db_path=str(db_path),
            as_name=None if action_id is ActionId.WORKSPACE_INITIALIZE else "alice",
            continuity_token=None,
        )
        async with app.run_test(size=(120, 36)) as pilot:
            context = HandlerContext(
                app,
                pilot,
                db_path,
                message_ts,
                alice_token,
                monkeypatch,
            )
            # Framework startup already returned after app.on_mount.
            assert app._system is not None
            assert action_id is ActionId.WORKSPACE_INITIALIZE or app._domain is not None
            try:
                await HANDLER_CASES[action_id](context)
            finally:
                context.screens.close()
                context.scope.close()
            context.scope.raise_if_invalid()

    asyncio.run(exercise())
