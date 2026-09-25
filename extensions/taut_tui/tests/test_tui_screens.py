"""Native extension forms and action palettes through real Textual screens."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from concurrent.futures import Future
from functools import wraps
from types import MappingProxyType
from typing import Any, cast

import pytest
from _completion import Completion, CompletionKey, CompletionScope
from _screen_completion import ScreenCompletions
from textual.app import App, ComposeResult
from textual.widgets import Button, Checkbox, Input, OptionList, Select, Static

from taut_tui.actions import ActionId, action_spec
from taut_tui.forms import form_spec

pytestmark = pytest.mark.sqlite_only


class _ScreenProbe:
    def __init__(self, app: App[Any], patch: pytest.MonkeyPatch) -> None:
        self.scope = CompletionScope()
        self.screens = ScreenCompletions(app, self.scope, patch)
        self.patch = patch

    def called(
        self, owner: Any, method: str, *, arguments: tuple[Any, ...] | None = None
    ) -> Completion[Any]:
        completion = self.scope.expect(CompletionKey(owner, method, request=object()))
        original = getattr(owner, method)

        @wraps(original)
        def call(*args: Any, **kwargs: Any) -> Any:
            matches = arguments is None or args == arguments
            try:
                value = original(*args, **kwargs)
            except BaseException as error:
                if matches and completion.snapshot() is None:
                    completion.fail(completion.key, error)
                raise
            if matches and completion.snapshot() is None:
                completion.succeed(completion.key, value)
            return value

        self.patch.setattr(owner, method, call)
        return completion

    def message(self, owner: Any, kind: type[Any], **fields: Any) -> Completion[Any]:
        record = self.scope.expect(
            CompletionKey(owner, f"{kind.__name__}.handled", request=object())
        )
        original = owner._on_message

        async def handle(event: Any) -> None:
            matches = isinstance(event, kind) and all(
                getattr(event, field) == value for field, value in fields.items()
            )
            try:
                await original(event)
            except BaseException as error:
                if matches and record.snapshot() is None:
                    record.fail(record.key, error)
                raise
            if matches and record.snapshot() is None:
                record.succeed(record.key, event)

        self.patch.setattr(owner, "_on_message", handle)
        return record

    async def result(self, screen: Any, *, deadline: float) -> Any:
        value = await self.screens.result_applied(screen).wait(
            deadline=deadline, description="screen result applied"
        )
        await self.screens.retired(screen).wait(
            deadline=deadline, description="screen retired"
        )
        return value

    def search(self, screen: Any, future: Future[Any]) -> Completion[Any]:
        generation = screen._generation + 1
        record = self.scope.expect(
            CompletionKey(screen, "search.applied", future, generation)
        )
        original = screen._apply_results

        def apply(actual_generation: int, actual_future: Future[Any]) -> None:
            accepted = actual_generation == screen._generation and screen.is_mounted
            matches = actual_generation == generation and actual_future is future
            try:
                original(actual_generation, actual_future)
            except BaseException as error:
                if matches:
                    record.fail(record.key, error)
                raise
            if not matches:
                return
            if not accepted:
                record.supersede(record.key)
            elif future.cancelled():
                record.cancel(record.key)
            elif (source_error := future.exception()) is not None:
                record.fail(record.key, source_error)
            else:
                record.succeed(record.key, tuple(screen._results))

        self.patch.setattr(screen, "_apply_results", apply)
        return record

    def close(self) -> None:
        self.screens.close()
        self.scope.close()
        self.scope.raise_if_invalid()


def _observed(app: App[Any]) -> _ScreenProbe:
    return cast(_ScreenProbe, cast(Any, app)._screen_test_completions)


@pytest.fixture(autouse=True)
def _observe_screen_hosts(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    original = App.__init__
    probes: list[_ScreenProbe] = []

    def initialize(app: Any, *args: Any, **kwargs: Any) -> None:
        original(app, *args, **kwargs)
        probe = _ScreenProbe(app, monkeypatch)
        app._screen_test_completions = probe
        probes.append(probe)

    monkeypatch.setattr(App, "__init__", initialize)
    try:
        yield
    finally:
        for probe in probes:
            probe.close()


def test_draft_recovery_screen_previews_multiline_and_escape_retains() -> None:
    from taut_tui.models import DraftState, RecoveredDraft
    from taut_tui.screens import DraftRecoveryScreen

    selected: list[str | None] = []
    recovery = RecoveredDraft(
        "draft-1",
        DraftState("old", "first line\n[bold]literal[/bold]\n[", 5, 2),
        "ops",
        "rename collision",
    )

    class RecoveryHost(App[None]):
        def on_mount(self) -> None:
            self.push_screen(DraftRecoveryScreen((recovery,)), selected.append)

    async def exercise() -> None:
        app = RecoveryHost()
        async with app.run_test(size=(80, 24)) as pilot:
            probe = _observed(app)
            screen = app.screen
            await probe.screens.ready(screen, deadline=probe.scope.now() + 30)
            preview = str(app.screen.query_one("#recovery-preview", Static).render())
            assert "Original: old" in preview
            assert "Intended: ops" in preview
            assert "first line\n[bold]literal[/bold]\n[" in preview
            deadline = probe.scope.now() + 5
            await pilot.press("escape")
            await probe.result(screen, deadline=deadline)

    asyncio.run(exercise())
    assert selected == [None]


def test_native_form_is_labelled_masked_clickable_and_validates_visually() -> None:
    from taut_tui.screens import FormSubmission, NativeFormScreen

    results: list[FormSubmission | None] = []

    class FormHost(App[None]):
        def compose(self) -> ComposeResult:
            yield Input(id="underlay")

        def on_mount(self) -> None:
            self.push_screen(NativeFormScreen(form_spec(ActionId.IDENTITY_REJOIN)))

        def on_native_form_screen_submitted(
            self,
            event: NativeFormScreen.Submitted,
        ) -> None:
            results.append(event.submission)
            event.screen.complete()

    async def exercise() -> None:
        app = FormHost()
        async with app.run_test(size=(80, 24)) as pilot:
            token = app.screen.query_one("#field-continuity-token", Input)
            assert token.password is True
            assert await pilot.click("#field-name-or-alias") is True
            await pilot.press("space", "space", "tab", "s", "e", "c", "r", "e", "t")
            await pilot.click("#form-submit")
            assert "must not be blank" in str(
                app.screen.query_one("#form-errors").render()
            )
            name = app.screen.query_one("#field-name-or-alias", Input)
            name.value = "alice"
            assert token.value == "secret"
            probe = _observed(app)
            screen = app.screen
            deadline = probe.scope.now() + 5
            app.screen.query_one("#form-submit", Button).press()
            await probe.result(screen, deadline=deadline)
            assert results

    asyncio.run(exercise())
    assert results == [
        FormSubmission(
            ActionId.IDENTITY_REJOIN,
            {"name_or_alias": "alice", "continuity_token": "secret"},
        )
    ]


def test_native_form_enter_and_tab_follow_field_submit_cancel_order() -> None:
    from taut_tui.screens import FormSubmission, NativeFormScreen

    results: list[FormSubmission] = []

    class FormHost(App[None]):
        def on_mount(self) -> None:
            self.push_screen(NativeFormScreen(form_spec(ActionId.IDENTITY_SET_NAME)))

        def on_native_form_screen_submitted(
            self,
            event: NativeFormScreen.Submitted,
        ) -> None:
            results.append(event.submission)
            event.screen.complete()

    async def exercise() -> None:
        app = FormHost()
        async with app.run_test(size=(80, 24)) as pilot:
            field = app.screen.query_one("#field-name", Input)
            assert field.has_focus
            await pilot.press(*"alice", "tab")
            assert app.screen.query_one("#form-submit", Button).has_focus
            await pilot.press("tab")
            assert app.screen.query_one("#form-cancel", Button).has_focus
            await pilot.press("shift+tab")
            assert app.screen.query_one("#form-submit", Button).has_focus
            probe = _observed(app)
            screen = app.screen
            deadline = probe.scope.now() + 5
            await pilot.press("enter")
            await probe.result(screen, deadline=deadline)

    asyncio.run(exercise())
    assert results == [FormSubmission(ActionId.IDENTITY_SET_NAME, {"name": "alice"})]


def test_native_form_ignores_duplicate_submit_while_domain_work_is_pending() -> None:
    from taut_tui.screens import FormSubmission, NativeFormScreen

    results: list[FormSubmission] = []

    class FormHost(App[None]):
        def on_mount(self) -> None:
            self.push_screen(NativeFormScreen(form_spec(ActionId.IDENTITY_SET_NAME)))

        def on_native_form_screen_submitted(
            self,
            event: NativeFormScreen.Submitted,
        ) -> None:
            results.append(event.submission)

    async def exercise() -> None:
        app = FormHost()
        async with app.run_test(size=(80, 24)) as pilot:
            probe = _observed(app)
            submitted = probe.message(
                app, NativeFormScreen.Submitted, screen=app.screen
            )
            deadline = probe.scope.now() + 5
            await pilot.press(*"alice", "enter")
            await submitted.wait(
                deadline=deadline, description="host applied submission"
            )
            refused = probe.called(app.screen, "_submit")
            deadline = probe.scope.now() + 5
            await pilot.press("enter")
            await refused.wait(
                deadline=deadline, description="duplicate submit refused"
            )
            assert app.screen.query_one("#form-submit", Button).disabled is True

    asyncio.run(exercise())
    assert results == [FormSubmission(ActionId.IDENTITY_SET_NAME, {"name": "alice"})]


def test_native_form_escape_waits_for_pending_domain_work() -> None:
    from taut_tui.screens import NativeFormScreen

    class FormHost(App[None]):
        def on_mount(self) -> None:
            self.push_screen(NativeFormScreen(form_spec(ActionId.IDENTITY_SET_NAME)))

    async def exercise() -> None:
        app = FormHost()
        async with app.run_test(size=(80, 24)) as pilot:
            probe = _observed(app)
            submitted = probe.called(app.screen, "_submit")
            deadline = probe.scope.now() + 5
            await pilot.press(*"alice", "enter")
            await submitted.wait(
                deadline=deadline, description="pending submit applied"
            )
            refused = probe.called(app.screen, "action_cancel")
            deadline = probe.scope.now() + 5
            await pilot.press("escape")
            await refused.wait(deadline=deadline, description="pending cancel refused")

            assert isinstance(app.screen, NativeFormScreen)
            assert app.screen.query_one("#field-name", Input).value == "alice"
            assert (
                str(app.screen.query_one("#form-errors", Static).render()) == "Working…"
            )

    asyncio.run(exercise())


def test_command_palette_filters_and_returns_the_same_action_id() -> None:
    from taut_tui.screens import (
        CommandPaletteScreen,
        PaletteCommandHandoff,
        PaletteEntry,
    )

    selected: list[ActionId | PaletteCommandHandoff | None] = []
    entries = (
        PaletteEntry(action_spec(ActionId.IDENTITY_SHOW)),
        PaletteEntry(action_spec(ActionId.SYSTEM_DOCTOR)),
        PaletteEntry(
            action_spec(ActionId.MESSAGE_DELETE),
            enabled=False,
            reason="Select a message first",
        ),
    )

    class PaletteHost(App[None]):
        def on_mount(self) -> None:
            self.push_screen(CommandPaletteScreen(entries), selected.append)

    async def exercise() -> None:
        app = PaletteHost()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.press(*"doc")
            options = app.screen.query_one("#palette-results", OptionList)
            assert options.option_count == 1
            assert "Run system doctor" in str(options.get_option_at_index(0).prompt)
            probe = _observed(app)
            screen = app.screen
            deadline = probe.scope.now() + 5
            await pilot.press("down", "enter")
            await probe.result(screen, deadline=deadline)

    asyncio.run(exercise())
    assert selected == [ActionId.SYSTEM_DOCTOR]


def test_command_line_screen_shows_colon_affordance_and_returns_typed_input() -> None:
    from taut.commands.syntax import core_command_syntax
    from taut_tui.screens import CommandLineScreen, CommandLineSubmission

    results: list[CommandLineSubmission | None] = []

    class CommandHost(App[None]):
        def on_mount(self) -> None:
            self.push_screen(CommandLineScreen(core_command_syntax()), results.append)

    async def exercise() -> None:
        app = CommandHost()
        async with app.run_test(size=(80, 24)) as pilot:
            assert str(app.screen.query_one("#command-marker", Static).render()) == ":"
            field = app.screen.query_one("#command-line", Input)
            await pilot.click(field)
            await pilot.press(*"channel topic general focus")
            probe = _observed(app)
            screen = app.screen
            deadline = probe.scope.now() + 5
            await pilot.press("enter")
            await probe.result(screen, deadline=deadline)

    asyncio.run(exercise())
    assert results[0] is not None
    assert results[0].invocation.path == ("channel", "topic")
    assert results[0].invocation.values["topic"] == "focus"


def test_command_line_screen_accepts_summon_provider_syntax() -> None:
    from taut_summon.command_syntax import provide_syntax

    from taut.commands.syntax import core_command_syntax, merge_command_syntax
    from taut_tui.screens import CommandLineScreen, CommandLineSubmission

    results: list[CommandLineSubmission | None] = []

    class CommandHost(App[None]):
        def on_mount(self) -> None:
            syntax = merge_command_syntax(core_command_syntax(), (provide_syntax(),))
            self.push_screen(CommandLineScreen(syntax), results.append)

    async def exercise() -> None:
        app = CommandHost()
        async with app.run_test(size=(80, 24)) as pilot:
            probe = _observed(app)
            screen = app.screen
            deadline = probe.scope.now() + 5
            await pilot.press(*"summon grok", "enter")
            await probe.result(screen, deadline=deadline)

    asyncio.run(exercise())
    assert results[0] is not None
    assert results[0].invocation.path == ("summon",)
    assert results[0].invocation.values["name"] == "grok"


def test_command_line_tab_completion_keeps_argument_input_active() -> None:
    from taut_summon.command_syntax import provide_syntax

    from taut.commands.syntax import core_command_syntax, merge_command_syntax
    from taut_tui.screens import CommandLineScreen

    class CommandHost(App[None]):
        def on_mount(self) -> None:
            syntax = merge_command_syntax(core_command_syntax(), (provide_syntax(),))
            self.push_screen(CommandLineScreen(syntax))

    async def exercise() -> None:
        app = CommandHost()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.press(*"sum", "tab")
            command = app.screen.query_one("#command-line", Input)
            assert command.value == "summon "
            assert command.has_focus
            assert isinstance(app.screen, CommandLineScreen)

            await pilot.press(*"grok")
            assert command.value == "summon grok"

    asyncio.run(exercise())


def test_command_line_keyboard_selection_keeps_argument_input_active() -> None:
    from taut_summon.command_syntax import provide_syntax

    from taut.commands.syntax import core_command_syntax, merge_command_syntax
    from taut_tui.screens import CommandLineScreen

    class CommandHost(App[None]):
        def on_mount(self) -> None:
            syntax = merge_command_syntax(core_command_syntax(), (provide_syntax(),))
            self.push_screen(CommandLineScreen(syntax))

    async def exercise() -> None:
        app = CommandHost()
        async with app.run_test(size=(80, 24)) as pilot:
            # Down cycles the ghost shadow; Tab accepts it ([TUI-7.1] as
            # revised 2026-08-18 — there is no selectable completion list).
            await pilot.press(*"sum", "down", "tab")
            command = app.screen.query_one("#command-line", Input)
            assert command.value == "summon "
            assert command.has_focus
            assert isinstance(app.screen, CommandLineScreen)

            await pilot.press(*"grok")
            assert command.value == "summon grok"

    asyncio.run(exercise())


def test_summon_start_screen_collects_every_typed_request_field() -> None:
    from taut_tui.screens import SummonStartScreen, SummonStartSubmission

    results: list[SummonStartSubmission | None] = []

    class SummonHost(App[None]):
        def on_mount(self) -> None:
            self.push_screen(
                SummonStartScreen(("claude", "codex")),
                results.append,
            )

    async def exercise() -> None:
        app = SummonHost()
        async with app.run_test(size=(100, 40)):
            app.screen.query_one("#summon-name", Input).value = "reviewer"
            app.screen.query_one("#summon-threads", Input).value = "dev, ops"
            app.screen.query_one("#summon-provider", Select).value = "codex"
            app.screen.query_one("#summon-persona", Input).value = "careful"
            app.screen.query_one("#summon-system-prompt", Input).value = "prompt.md"
            app.screen.query_one("#summon-rate-limit", Input).value = "12"
            for selector in (
                "#summon-attach",
                "#summon-takeover",
            ):
                app.screen.query_one(selector, Checkbox).value = True
            probe = _observed(app)
            screen = app.screen
            deadline = probe.scope.now() + 5
            app.screen.query_one("#summon-submit", Button).press()
            await probe.result(screen, deadline=deadline)

    asyncio.run(exercise())
    assert results == [
        SummonStartSubmission(
            name="reviewer",
            threads=("dev", "ops"),
            provider="codex",
            persona="careful",
            system_prompt_file="prompt.md",
            rate_limit=12,
            attach=True,
            detach=False,
            takeover=True,
        )
    ]


@pytest.mark.parametrize("rate_text", ["-", "not-a-number"])
def test_summon_start_screen_reports_invalid_rate_inline(rate_text: str) -> None:
    from taut_tui.screens import SummonStartScreen, SummonStartSubmission

    results: list[SummonStartSubmission | None] = []

    class SummonHost(App[None]):
        def on_mount(self) -> None:
            self.push_screen(SummonStartScreen(("codex",)), results.append)

    async def exercise() -> None:
        app = SummonHost()
        async with app.run_test(size=(100, 40)):
            app.screen.query_one("#summon-name", Input).value = "reviewer"
            rate = app.screen.query_one("#summon-rate-limit", Input)
            rate.value = rate_text
            probe = _observed(app)
            submitted = probe.called(app.screen, "_submit")
            deadline = probe.scope.now() + 5
            app.screen.query_one("#summon-submit", Button).press()
            await submitted.wait(deadline=deadline, description="invalid rate rejected")
            await probe.screens.ready(app.screen, deadline=deadline, focus=rate)

            assert isinstance(app.screen, SummonStartScreen)
            assert "whole number" in str(
                app.screen.query_one("#form-errors", Static).render()
            )
            assert rate.has_focus

    asyncio.run(exercise())
    assert results == []


def test_search_result_terminal_controls_are_escaped_even_for_fast_completion() -> None:
    from taut.client import SearchHit
    from taut_tui.screens import SearchScreen

    payload = "PAY\x1b]8;;https://evil.invalid\x07LOAD"
    completed: Future[list[SearchHit]] = Future()
    completed.set_result(
        [
            SearchHit(
                thread=payload,
                ts=1,
                from_id=None,
                from_name=payload,
                kind="message",
                text=payload,
                thread_kind="channel",
                channel=payload,
                parent=None,
                members=None,
            )
        ]
    )

    class SearchHost(App[None]):
        def on_mount(self) -> None:
            self.push_screen(
                SearchScreen(lambda _query: completed, MappingProxyType({}))
            )

    async def exercise() -> None:
        app = SearchHost()
        async with app.run_test(size=(80, 24)) as pilot:
            probe = _observed(app)
            applied = probe.search(app.screen, completed)
            deadline = probe.scope.now() + 5
            await pilot.press("x", "enter")
            await applied.wait(deadline=deadline, description="search result rendered")
            options = app.screen.query_one("#search-results", OptionList)
            assert options.option_count == 1
            rendered = str(options.get_option_at_index(0).prompt)
            assert "\x1b" not in rendered
            assert "\x07" not in rendered
            assert r"\x1b" in rendered
            assert r"\a" in rendered

    asyncio.run(exercise())


def test_search_results_use_actor_scoped_dm_labels_without_exposing_queue_names() -> (
    None
):
    from taut.client import SearchHit
    from taut_tui.screens import SearchScreen

    labelled_thread = "dm.d_1234567890abcdef"
    unknown_thread = "dm.d_fedcba0987654321"
    completed: Future[list[SearchHit]] = Future()
    completed.set_result(
        [
            SearchHit(
                thread=labelled_thread,
                ts=1,
                from_id=None,
                from_name="Alice",
                kind="message",
                text="known peer",
                thread_kind="dm",
                channel=None,
                parent=None,
                members=("member-a", "member-b"),
            ),
            SearchHit(
                thread=unknown_thread,
                ts=2,
                from_id=None,
                from_name="Bob",
                kind="message",
                text="unknown peer",
                thread_kind="dm",
                channel=None,
                parent=None,
                members=("member-a", "member-c"),
            ),
        ]
    )

    class SearchHost(App[None]):
        def on_mount(self) -> None:
            self.push_screen(
                SearchScreen(
                    lambda _query: completed,
                    MappingProxyType({labelled_thread: "Alice"}),
                )
            )

    async def exercise() -> None:
        app = SearchHost()
        async with app.run_test(size=(80, 24)) as pilot:
            probe = _observed(app)
            applied = probe.search(app.screen, completed)
            deadline = probe.scope.now() + 5
            await pilot.press("x", "enter")
            await applied.wait(deadline=deadline, description="search results rendered")
            options = app.screen.query_one("#search-results", OptionList)
            assert options.option_count == 2
            labelled = str(options.get_option_at_index(0).prompt)
            unknown = str(options.get_option_at_index(1).prompt)
            assert "Alice  Alice  known peer" in labelled
            assert "Direct message  Bob  unknown peer" in unknown
            assert "dm.d_" not in labelled
            assert "dm.d_" not in unknown

    asyncio.run(exercise())


def test_search_completion_after_escape_is_ignored() -> None:
    from _completion import CompletionSuperseded

    from taut.client import SearchHit
    from taut_tui.screens import SearchScreen

    pending: Future[list[SearchHit]] = Future()

    class SearchHost(App[None]):
        def on_mount(self) -> None:
            self.push_screen(SearchScreen(lambda _query: pending, MappingProxyType({})))

    async def exercise() -> None:
        app = SearchHost()
        async with app.run_test(size=(80, 24)) as pilot:
            probe = _observed(app)
            screen = app.screen
            applied = probe.search(screen, pending)
            deadline = probe.scope.now() + 5
            await pilot.press("x", "enter", "escape")
            await probe.result(screen, deadline=deadline)
            assert not isinstance(app.screen, SearchScreen)

            deadline = probe.scope.now() + 5
            pending.set_result([])
            with pytest.raises(CompletionSuperseded):
                await applied.wait(
                    deadline=deadline, description="late search rejected"
                )
            assert not isinstance(app.screen, SearchScreen)

    asyncio.run(exercise())


def test_search_observation_rejects_another_future_and_old_generation() -> None:
    from taut.client import SearchHit
    from taut_tui.screens import SearchScreen

    pending: Future[list[SearchHit]] = Future()
    unrelated: Future[list[SearchHit]] = Future()
    unrelated.set_result([])

    class SearchHost(App[None]):
        def on_mount(self) -> None:
            self.push_screen(SearchScreen(lambda _query: pending, MappingProxyType({})))

    async def exercise() -> None:
        app = SearchHost()
        async with app.run_test(size=(80, 24)) as pilot:
            probe = _observed(app)
            screen = cast(SearchScreen, app.screen)
            applied = probe.search(screen, pending)
            deadline = probe.scope.now() + 5
            await pilot.press("x", "enter")
            screen._apply_results(screen._generation, unrelated)
            screen._apply_results(screen._generation - 1, pending)
            assert applied.snapshot() is None
            pending.set_result([])
            result = await applied.wait(
                deadline=deadline, description="exact search applied"
            )
            assert result == ()
            assert "No matches" in str(
                screen.query_one("#search-errors", Static).render()
            )

    asyncio.run(exercise())


def test_palette_confirmation_and_form_errors_escape_terminal_controls() -> None:
    from taut_tui.screens import (
        CommandPaletteScreen,
        ConfirmationScreen,
        NativeFormScreen,
        PaletteEntry,
    )

    payload = "PAY\x1b]8;;https://evil.invalid\x07LOAD"

    def assert_safe(rendered: object) -> None:
        text = str(rendered)
        assert "\x1b" not in text
        assert "\x07" not in text
        assert r"\x1b" in text
        assert r"\a" in text

    class ModalHost(App[None]):
        pass

    async def exercise() -> None:
        palette = ModalHost()
        async with palette.run_test(size=(80, 24)):
            probe = _observed(palette)
            deadline = probe.scope.now() + 5
            palette.push_screen(
                CommandPaletteScreen(
                    (
                        PaletteEntry(
                            action_spec(ActionId.IDENTITY_SHOW),
                            scope=payload,
                            gesture_hint=payload,
                        ),
                    )
                )
            )
            await probe.screens.ready(palette.screen, deadline=deadline)
            options = palette.screen.query_one("#palette-results", OptionList)
            assert_safe(options.get_option_at_index(0).prompt)

        confirmation = ModalHost()
        async with confirmation.run_test(size=(80, 24)):
            probe = _observed(confirmation)
            deadline = probe.scope.now() + 5
            confirmation.push_screen(ConfirmationScreen(payload))
            await probe.screens.ready(confirmation.screen, deadline=deadline)
            projected = [
                widget.render()
                for widget in confirmation.screen.query(Static)
                if r"\x1b" in str(widget.render())
            ]
            assert len(projected) == 1
            assert_safe(projected[0])

        form_host = ModalHost()
        async with form_host.run_test(size=(80, 24)):
            probe = _observed(form_host)
            deadline = probe.scope.now() + 5
            screen = NativeFormScreen(form_spec(ActionId.IDENTITY_SET_NAME))
            form_host.push_screen(screen)
            await probe.screens.ready(screen, deadline=deadline)
            screen.show_domain_error(payload)
            assert_safe(screen.query_one("#form-errors", Static).render())

    asyncio.run(exercise())


def test_summon_provider_projection_escapes_terminal_controls() -> None:
    from taut_tui.screens import SummonStartScreen

    payload = "PAY\x1b]8;;https://evil.invalid\x07LOAD"

    class SummonHost(App[None]):
        def on_mount(self) -> None:
            self.push_screen(SummonStartScreen((payload,)))

    async def exercise() -> None:
        app = SummonHost()
        async with app.run_test(size=(100, 40)):
            select = app.screen.query_one("#summon-provider", Select)
            probe = _observed(app)
            changed = probe.called(select, "_watch_value", arguments=(payload,))
            deadline = probe.scope.now() + 5
            select.value = payload
            await changed.wait(
                deadline=deadline, description="provider projection applied"
            )
            projected = "\n".join(str(widget.render()) for widget in select.query("*"))
            assert "\x1b" not in projected
            assert "\x07" not in projected
            assert r"\x1b" in projected
            assert r"\a" in projected

    asyncio.run(exercise())


# --- Slice 4 of docs/plans/2026-08-18-tui-deep-review-remediation-plan.md ---


def test_palette_opens_highlighted_and_updown_select_from_query() -> None:
    """[TUI-7.1] Up/Down move the highlight from the query; Enter runs it."""

    from taut_tui.screens import CommandPaletteScreen, PaletteEntry

    selected: list[ActionId | object | None] = []
    entries = (
        PaletteEntry(action_spec(ActionId.IDENTITY_SHOW)),
        PaletteEntry(action_spec(ActionId.SYSTEM_DOCTOR)),
        PaletteEntry(
            action_spec(ActionId.MESSAGE_DELETE),
            enabled=False,
            reason="Select a message first",
        ),
    )

    class PaletteHost(App[None]):
        def on_mount(self) -> None:
            self.push_screen(CommandPaletteScreen(entries), selected.append)

    async def exercise() -> None:
        app = PaletteHost()
        async with app.run_test(size=(80, 24)) as pilot:
            probe = _observed(app)
            screen = app.screen
            await probe.screens.ready(screen, deadline=probe.scope.now() + 30)
            options = app.screen.query_one("#palette-results", OptionList)
            assert options.highlighted is not None
            first = options.get_option_at_index(options.highlighted)
            assert not first.disabled
            deadline = probe.scope.now() + 5
            await pilot.press("down", "enter")
            await probe.result(screen, deadline=deadline)

    asyncio.run(exercise())
    # Down moved past the first enabled entry to the second one.
    assert selected == [ActionId.SYSTEM_DOCTOR]


def test_palette_no_match_shows_empty_state_and_enter_stays_inert() -> None:
    from taut_tui.screens import CommandPaletteScreen, PaletteEntry

    selected: list[ActionId | object | None] = []
    entries = (PaletteEntry(action_spec(ActionId.IDENTITY_SHOW)),)

    class PaletteHost(App[None]):
        def on_mount(self) -> None:
            self.push_screen(CommandPaletteScreen(entries), selected.append)

    async def exercise() -> None:
        app = PaletteHost()
        async with app.run_test(size=(80, 24)) as pilot:
            probe = _observed(app)
            screen = app.screen
            rendered = probe.called(screen, "_render_results", arguments=("zzz zzz",))
            deadline = probe.scope.now() + 5
            await pilot.press(*"zzz zzz")
            await rendered.wait(deadline=deadline, description="empty palette rendered")
            options = app.screen.query_one("#palette-results", OptionList)
            assert options.option_count == 1
            empty_state = options.get_option_at_index(0)
            assert empty_state.disabled
            assert ":" in str(empty_state.prompt)
            refused = probe.message(
                screen,
                Input.Submitted,
                input=screen.query_one("#palette-query", Input),
                value="zzz zzz",
            )
            deadline = probe.scope.now() + 5
            await pilot.press("enter")
            await refused.wait(deadline=deadline, description="inert enter handled")
            assert isinstance(app.screen, CommandPaletteScreen)
            assert selected == []
            deadline = probe.scope.now() + 5
            await pilot.press("escape")
            await probe.result(screen, deadline=deadline)

    asyncio.run(exercise())
    assert selected == [None]


def test_palette_offers_run_as_command_handoff_for_known_root() -> None:
    from taut_tui.screens import (
        CommandPaletteScreen,
        PaletteCommandHandoff,
        PaletteEntry,
    )

    selected: list[object | None] = []
    entries = (PaletteEntry(action_spec(ActionId.IDENTITY_SHOW)),)

    class PaletteHost(App[None]):
        def on_mount(self) -> None:
            self.push_screen(
                CommandPaletteScreen(
                    entries,
                    command_roots=frozenset({"summon"}),
                ),
                selected.append,
            )

    async def exercise() -> None:
        app = PaletteHost()
        async with app.run_test(size=(80, 24)) as pilot:
            probe = _observed(app)
            screen = app.screen
            rendered = probe.called(
                screen, "_render_results", arguments=("summon kimi",)
            )
            deadline = probe.scope.now() + 5
            await pilot.press(*"summon kimi")
            await rendered.wait(
                deadline=deadline, description="command handoff rendered"
            )
            options = app.screen.query_one("#palette-results", OptionList)
            prompts = [
                str(options.get_option_at_index(i).prompt)
                for i in range(options.option_count)
            ]
            assert any("Run as command" in prompt for prompt in prompts)
            deadline = probe.scope.now() + 5
            await pilot.press("enter")
            await probe.result(screen, deadline=deadline)

    asyncio.run(exercise())
    assert selected == [PaletteCommandHandoff("summon kimi")]


def test_command_line_has_no_completion_list_and_reconciles_on_mount() -> None:
    """[TUI-7.1] vi-like line: no browsable list; mount reads the composer."""

    from taut.commands.syntax import core_command_syntax
    from taut_tui.screens import CommandLineScreen

    class CommandHost(App[None]):
        def on_mount(self) -> None:
            self.push_screen(
                CommandLineScreen(
                    core_command_syntax(),
                    initial_text="say ",
                    reconcile=lambda: "say general raced",
                )
            )

    async def exercise() -> None:
        app = CommandHost()
        async with app.run_test(size=(80, 24)):
            probe = _observed(app)
            await probe.screens.ready(app.screen, deadline=probe.scope.now() + 30)
            assert not app.screen.query(OptionList)
            field = app.screen.query_one("#command-line", Input)
            assert field.value == "say general raced"

    asyncio.run(exercise())


def test_command_line_shadow_cycles_and_tab_accepts() -> None:
    from taut_summon.command_syntax import provide_syntax
    from textual.suggester import SuggestionReady

    from taut.commands.syntax import core_command_syntax, merge_command_syntax
    from taut_tui.screens import CommandLineScreen

    class CommandHost(App[None]):
        def on_mount(self) -> None:
            syntax = merge_command_syntax(core_command_syntax(), (provide_syntax(),))
            self.push_screen(CommandLineScreen(syntax))

    async def exercise() -> None:
        app = CommandHost()
        async with app.run_test(size=(80, 24)) as pilot:
            probe = _observed(app)
            screen = app.screen
            field = screen.query_one("#command-line", Input)
            suggestion = probe.message(field, SuggestionReady, value="s")
            deadline = probe.scope.now() + 5
            await pilot.press(*"s")
            await suggestion.wait(deadline=deadline, description="exact shadow applied")
            first_shadow = field._suggestion
            assert first_shadow.startswith("s") and len(first_shadow) > 1
            cycled = probe.called(screen, "_cycle_shadow", arguments=(1,))
            deadline = probe.scope.now() + 5
            await pilot.press("down")
            await cycled.wait(deadline=deadline, description="shadow cycle applied")
            second_shadow = field._suggestion
            assert second_shadow != first_shadow
            accepted = probe.called(screen, "action_accept_shadow")
            deadline = probe.scope.now() + 5
            await pilot.press("tab")
            await accepted.wait(deadline=deadline, description="shadow accepted")
            assert field.value == second_shadow.rstrip() + " "
            assert field.has_focus
            assert isinstance(app.screen, CommandLineScreen)

    asyncio.run(exercise())
