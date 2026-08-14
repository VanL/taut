"""Executable concrete-handler outcomes for every native TUI action."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from pathlib import Path
from threading import Event
from typing import Any, cast

import pytest
from textual.widgets import Button, Input, OptionList, Select

from taut import EmptyResultError, NotFoundError
from taut.client import TautClient
from taut_tui.actions import ActionContext, ActionId, ActionRoute, action_spec
from taut_tui.app import TautApp
from taut_tui.models import InspectorKind, InteractionMode, LogicalSurface
from taut_tui.screens import (
    CommandPaletteScreen,
    ConfirmationScreen,
    NamedActionScreen,
    NativeFormScreen,
    SearchScreen,
    SummonStartScreen,
)
from taut_tui.summon import TuiSummonOperations

pytestmark = pytest.mark.sqlite_only


@dataclass(slots=True)
class HandlerContext:
    app: TautApp
    pilot: Any
    db_path: Path
    message_ts: int
    alice_token: str


HandlerCase = Callable[[HandlerContext], Awaitable[None]]


async def _eventually(
    pilot: Any,
    predicate: Callable[[], bool],
    *,
    attempts: int = 200,
) -> None:
    for _ in range(attempts):
        await pilot.pause(0.01)
        if predicate():
            return
    app = pilot.app
    errors = ""
    if isinstance(app.screen, NativeFormScreen):
        errors = str(app.screen.query_one("#form-errors").render())
    pytest.fail(
        "handler outcome did not become observable: "
        f"screen={type(app.screen).__name__}, form_errors={errors!r}, "
        f"inspector={str(app.query_one('#inspector-body').render())!r}, "
        f"messages={[(row.thread, row.text) for row in app._message_rows]!r}"
    )


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
    context.app.action_open_command()
    await context.pilot.pause()
    assert isinstance(context.app.screen, CommandPaletteScreen)
    query = context.app.screen.query_one("#palette-query", Input)
    query.value = action_id.value
    await context.pilot.pause()
    options = context.app.screen.query_one("#palette-results", OptionList)
    option_index = next(
        index
        for index in range(options.option_count)
        if options.get_option_at_index(index).id == action_id.value
    )
    assert options.get_option_at_index(option_index).disabled is False
    options.highlighted = option_index
    options.focus()
    await context.pilot.press("enter")
    await context.pilot.pause()


async def _open_general(context: HandlerContext) -> None:
    context.app._dispatch_tui_action(
        ActionId.CONVERSATION_OPEN,
        source=ActionRoute.NAVIGATION,
        context=ActionContext(
            target="general",
            target_label="#general",
            surface=LogicalSurface.NAVIGATION,
        ),
    )
    await _eventually(
        context.pilot,
        lambda: context.app.visual_state.active_conversation == "general",
    )


async def _select_message(context: HandlerContext) -> None:
    await _open_general(context)
    await _eventually(
        context.pilot,
        lambda: any(row.ts == context.message_ts for row in context.app._message_rows),
    )
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
    screen.query_one("#form-submit", Button).press()
    await context.pilot.pause()
    return screen


async def _cancel_confirmation(context: HandlerContext, exact_target: str) -> None:
    assert isinstance(context.app.screen, ConfirmationScreen)
    assert exact_target in context.app.screen.prompt
    context.app.screen.query_one("#confirmation-cancel", Button).press()
    await context.pilot.pause()


async def _accept_confirmation(context: HandlerContext, exact_target: str) -> None:
    assert isinstance(context.app.screen, ConfirmationScreen)
    assert exact_target in context.app.screen.prompt
    context.app.screen.query_one("#confirmation-confirm", Button).press()
    await context.pilot.pause()


async def _workspace_initialize(context: HandlerContext) -> None:
    assert not context.db_path.exists()
    await _select_palette(context, ActionId.WORKSPACE_INITIALIZE)
    await _eventually(context.pilot, context.db_path.is_file)
    await _eventually(
        context.pilot,
        lambda: "Workspace created" in _inspector(context),
    )


async def _identity_rejoin(context: HandlerContext) -> None:
    await _select_palette(context, ActionId.IDENTITY_REJOIN)
    await _submit_form(
        context,
        {"name_or_alias": "", "continuity_token": context.alice_token},
    )
    await _eventually(
        context.pilot, lambda: not isinstance(context.app.screen, NativeFormScreen)
    )
    assert context.app._domain is not None
    assert context.app._domain.show_identity().result(timeout=5).name == "alice"


async def _identity_show(context: HandlerContext) -> None:
    await _select_palette(context, ActionId.IDENTITY_SHOW)
    await _eventually(context.pilot, lambda: "alice" in _inspector(context))


async def _identity_set_name(context: HandlerContext) -> None:
    await _select_palette(context, ActionId.IDENTITY_SET_NAME)
    await _submit_form(context, {"name": "alice-renamed"})
    await _eventually(context.pilot, lambda: "alice-renamed" in _inspector(context))
    observer = _observe(context, as_name="alice-renamed")
    try:
        assert observer.whoami().name == "alice-renamed"
    finally:
        observer.close()


async def _identity_set_persona(context: HandlerContext) -> None:
    await _select_palette(context, ActionId.IDENTITY_SET_PERSONA)
    await _submit_form(context, {"persona": "reviewer"})
    await _eventually(context.pilot, lambda: "reviewer" in _inspector(context))
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
    await _select_palette(context, ActionId.CONVERSATION_OPEN)
    await _eventually(
        context.pilot,
        lambda: context.app.visual_state.active_conversation == "general",
    )


async def _channel_join(context: HandlerContext) -> None:
    await _select_palette(context, ActionId.CHANNEL_JOIN)
    await _submit_form(context, {"channel": "joined-by-handler"})
    await _eventually(
        context.pilot, lambda: not isinstance(context.app.screen, NativeFormScreen)
    )
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
    await _accept_confirmation(context, "general")
    await _eventually(context.pilot, lambda: not _is_joined(context, "general"))


async def _direct_message_start(context: HandlerContext) -> None:
    await _select_palette(context, ActionId.DIRECT_MESSAGE_START)
    await _submit_form(context, {"member": "bob", "message": "private hello"})
    await _eventually(
        context.pilot, lambda: not isinstance(context.app.screen, NativeFormScreen)
    )
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
    await _select_palette(context, ActionId.MEMBERS_OPEN)
    await _eventually(
        context.pilot,
        lambda: "alice" in _inspector(context) and "bob" in _inspector(context),
    )


async def _channel_show_topic(context: HandlerContext) -> None:
    await _open_general(context)
    await _select_palette(context, ActionId.CHANNEL_SHOW_TOPIC)
    await _eventually(context.pilot, lambda: "Initial topic" in _inspector(context))


async def _channel_set_topic(context: HandlerContext) -> None:
    await _open_general(context)
    await _select_palette(context, ActionId.CHANNEL_SET_TOPIC)
    await _submit_form(context, {"topic": "Changed topic"})
    await _eventually(context.pilot, lambda: "Changed topic" in _inspector(context))
    observer = _observe(context)
    try:
        assert observer.get_channel("general").topic == "Changed topic"
    finally:
        observer.close()


async def _channel_clear_topic(context: HandlerContext) -> None:
    await _open_general(context)
    await _select_palette(context, ActionId.CHANNEL_CLEAR_TOPIC)
    await _eventually(context.pilot, lambda: _topic_is(context, None))
    observer = _observe(context)
    try:
        assert observer.get_channel("general").topic is None
    finally:
        observer.close()


async def _channel_rename(context: HandlerContext) -> None:
    await _open_general(context)
    await _select_palette(context, ActionId.CHANNEL_RENAME)
    form = await _submit_form(context, {"new_name": "renamed-channel"})
    await _cancel_confirmation(context, "general")
    assert isinstance(context.app.screen, NativeFormScreen)
    observer = _observe(context)
    try:
        assert observer.get_channel("general").name == "general"
    finally:
        observer.close()
    form.query_one("#form-submit", Button).press()
    await context.pilot.pause()
    await _accept_confirmation(context, "general")
    await _eventually(context.pilot, lambda: "renamed-channel" in _inspector(context))
    observer = _observe(context)
    try:
        assert observer.get_channel("renamed-channel").name == "renamed-channel"
    finally:
        observer.close()


async def _compose_enter(context: HandlerContext) -> None:
    await _open_general(context)
    await _select_palette(context, ActionId.COMPOSE_ENTER)
    assert context.app.visual_state.mode is InteractionMode.COMPOSE
    assert context.app.query_one("#composer", Input).has_focus
    assert context.app.query_one("#composer", Input).value == ""


async def _message_send(context: HandlerContext) -> None:
    await _open_general(context)
    composer = context.app.query_one("#composer", Input)
    composer.focus()
    await context.pilot.press(*"handler-send")
    assert composer.value == "handler-send"
    await context.pilot.press("escape")
    await _select_palette(context, ActionId.MESSAGE_SEND)
    await _eventually(
        context.pilot,
        lambda: _thread_has_text(context, "general", "handler-send"),
    )


async def _message_reply(context: HandlerContext) -> None:
    await _select_message(context)
    await _select_palette(context, ActionId.MESSAGE_REPLY)
    await _submit_form(context, {"message": "handler reply"})
    await _eventually(
        context.pilot,
        lambda: _thread_has_text(
            context, f"general.{context.message_ts}", "handler reply"
        ),
    )


async def _message_react(context: HandlerContext) -> None:
    await _select_message(context)
    await _select_palette(context, ActionId.MESSAGE_REACT)
    await _submit_form(context, {"reaction": "ack"})
    await _eventually(
        context.pilot, lambda: "Reaction ack added" in _inspector(context)
    )
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
    await _accept_confirmation(context, str(context.message_ts))
    await _eventually(context.pilot, lambda: "Deleted message" in _inspector(context))
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
    await _select_palette(context, ActionId.SEARCH_OPEN_RESULT)
    await _eventually(
        context.pilot,
        lambda: any(row.ts == context.message_ts for row in context.app._message_rows),
    )
    assert context.app.visual_state.active_conversation == "general"
    assert context.app.visual_state.scroll_anchor.message_id == context.message_ts


async def _system_doctor(context: HandlerContext) -> None:
    await _select_palette(context, ActionId.SYSTEM_DOCTOR)
    await _eventually(context.pilot, lambda: "System doctor" in _inspector(context))


async def _system_dump(context: HandlerContext) -> None:
    output = context.db_path.with_suffix(".dump.json")
    output.write_text("sentinel", encoding="utf-8")
    await _select_palette(context, ActionId.SYSTEM_DUMP)
    form = await _submit_form(context, {"output_path": str(output)})
    await _cancel_confirmation(context, str(output))
    assert output.read_text(encoding="utf-8") == "sentinel"
    assert isinstance(context.app.screen, NativeFormScreen)
    form.query_one("#form-submit", Button).press()
    await context.pilot.pause()
    await _accept_confirmation(context, str(output))
    await _eventually(
        context.pilot,
        lambda: output.read_text(encoding="utf-8") != "sentinel",
    )
    assert output.stat().st_size > 0


async def _system_load_help(context: HandlerContext) -> None:
    source = context.db_path.with_suffix(".input.json")
    await _select_palette(context, ActionId.SYSTEM_LOAD_HELP)
    await _submit_form(context, {"input_path": str(source)})
    assert "system load" in _inspector(context)
    assert str(source) in _inspector(context)
    assert not source.exists()


async def _command_open(context: HandlerContext) -> None:
    await context.pilot.press(":")
    await context.pilot.pause()
    assert isinstance(context.app.screen, CommandPaletteScreen)
    assert context.app.visual_state.mode is InteractionMode.COMMAND


async def _help_open(context: HandlerContext) -> None:
    await _select_palette(context, ActionId.HELP_OPEN)
    assert "Ctrl-P commands" in _inspector(context)


async def _application_quit(context: HandlerContext) -> None:
    await _select_palette(context, ActionId.APPLICATION_QUIT)
    await context.pilot.pause()
    assert not context.app.is_running


class _SummonMember:
    member_id = "m_summoned"
    name = "actual-summoned"
    provider = "scripted"
    provider_session_id = "session-handler"


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
        ready_callback=context.app._apply_summon_ready,
    )
    context.app._summon = operations
    context.app._summon_interaction = cast(
        Any, object()
    )  # deterministic controller ignores I/O
    return controller, operations


async def _summon_start(context: HandlerContext) -> None:
    controller, operations = _install_summon(context)
    try:
        await _select_palette(context, ActionId.SUMMON_START)
        assert isinstance(context.app.screen, SummonStartScreen)
        context.app.screen.query_one("#summon-name", Input).value = "requested"
        context.app.screen.query_one("#summon-provider", Select).value = "scripted"
        context.app.screen.query_one("#summon-submit", Button).press()
        await _eventually(context.pilot, controller.ready.is_set)
        assert operations.owned_runs()[0].member_name == "actual-summoned"
        assert context.app._owned_summon_tokens
    finally:
        controller.release.set()
        operations.close()


async def _summon_list(context: HandlerContext) -> None:
    controller, operations = _install_summon(context)
    try:
        await _select_palette(context, ActionId.SUMMON_LIST)
        await _eventually(
            context.pilot, lambda: "actual-summoned" in _inspector(context)
        )
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
        context.app.screen.query_one("#named-action-submit", Button).press()
        await _eventually(
            context.pilot, lambda: "actual-summoned" in _inspector(context)
        )
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
        context.app.screen.query_one("#named-action-submit", Button).press()
        await context.pilot.pause()
        await _cancel_confirmation(context, "actual-summoned")
        assert controller.stopped == []
        await _select_palette(context, ActionId.SUMMON_DISMISS)
        context.app.screen.query_one(
            "#summon-member-name", Input
        ).value = "actual-summoned"
        context.app.screen.query_one("#named-action-submit", Button).press()
        await context.pilot.pause()
        await _accept_confirmation(context, "actual-summoned")
        await _eventually(
            context.pilot, lambda: controller.stopped == ["actual-summoned"]
        )
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


@pytest.mark.parametrize("action_id", tuple(ActionId), ids=lambda item: item.value)
def test_every_action_reaches_a_concrete_handler(
    action_id: ActionId,
    tmp_path: Path,
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
            finally:
                alice.close()
                bob.close()

        app = TautApp(
            db_path=str(db_path),
            as_name=None if action_id is ActionId.WORKSPACE_INITIALIZE else "alice",
            auth_token=None,
        )
        async with app.run_test(size=(120, 36)) as pilot:
            context = HandlerContext(app, pilot, db_path, message_ts, alice_token)
            await _eventually(
                pilot,
                lambda: (
                    app._system is not None
                    and (
                        action_id is ActionId.WORKSPACE_INITIALIZE
                        or app._domain is not None
                    )
                ),
            )
            await HANDLER_CASES[action_id](context)

    asyncio.run(exercise())
