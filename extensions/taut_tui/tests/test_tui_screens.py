"""Native extension forms and action palettes through real Textual screens."""

from __future__ import annotations

import asyncio
from concurrent.futures import Future

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Button, Checkbox, Input, OptionList, Select, Static

from taut_tui.actions import ActionId, action_spec
from taut_tui.forms import form_spec

pytestmark = pytest.mark.sqlite_only


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
            await pilot.pause()
            app.screen.query_one("#form-submit", Button).press()
            await pilot.pause()
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
            await pilot.press("enter")
            await pilot.pause()

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
            await pilot.press(*"alice", "enter")
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
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
            await pilot.press(*"alice", "enter")
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()

            assert isinstance(app.screen, NativeFormScreen)
            assert app.screen.query_one("#field-name", Input).value == "alice"
            assert (
                str(app.screen.query_one("#form-errors", Static).render()) == "Working…"
            )

    asyncio.run(exercise())


def test_command_palette_filters_and_returns_the_same_action_id() -> None:
    from taut_tui.screens import CommandPaletteScreen, PaletteEntry

    selected: list[ActionId | None] = []
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
            await pilot.press("down", "enter")
            await pilot.pause()

    asyncio.run(exercise())
    assert selected == [ActionId.SYSTEM_DOCTOR]


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
        async with app.run_test(size=(100, 40)) as pilot:
            app.screen.query_one("#summon-name", Input).value = "reviewer"
            app.screen.query_one("#summon-threads", Input).value = "dev, ops"
            app.screen.query_one("#summon-provider", Select).value = "codex"
            app.screen.query_one("#summon-persona", Input).value = "careful"
            app.screen.query_one("#summon-system-prompt", Input).value = "prompt.md"
            app.screen.query_one("#summon-rate-limit", Input).value = "12"
            for selector in (
                "#summon-terminal",
                "#summon-attach",
                "#summon-takeover",
            ):
                app.screen.query_one(selector, Checkbox).value = True
            app.screen.query_one("#summon-submit", Button).press()
            await pilot.pause()

    asyncio.run(exercise())
    assert results == [
        SummonStartSubmission(
            name="reviewer",
            threads=("dev", "ops"),
            provider="codex",
            persona="careful",
            system_prompt_file="prompt.md",
            rate_limit=12,
            terminal=True,
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
        async with app.run_test(size=(100, 40)) as pilot:
            app.screen.query_one("#summon-name", Input).value = "reviewer"
            rate = app.screen.query_one("#summon-rate-limit", Input)
            rate.value = rate_text
            app.screen.query_one("#summon-submit", Button).press()
            await pilot.pause()

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
    completed: Future[list[object]] = Future()
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
            self.push_screen(SearchScreen(lambda _query: completed))

    async def exercise() -> None:
        app = SearchHost()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.press("x", "enter")
            for _ in range(100):
                await pilot.pause(0.01)
                options = app.screen.query_one("#search-results", OptionList)
                if options.option_count:
                    break
            assert options.option_count == 1
            rendered = str(options.get_option_at_index(0).prompt)
            assert "\x1b" not in rendered
            assert "\x07" not in rendered
            assert r"\x1b" in rendered
            assert r"\a" in rendered

    asyncio.run(exercise())


def test_search_completion_after_escape_is_ignored() -> None:
    from taut_tui.screens import SearchScreen

    pending: Future[list[object]] = Future()

    class SearchHost(App[None]):
        def on_mount(self) -> None:
            self.push_screen(SearchScreen(lambda _query: pending))

    async def exercise() -> None:
        app = SearchHost()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.press("x", "enter", "escape")
            await pilot.pause()
            assert not isinstance(app.screen, SearchScreen)

            pending.set_result([])
            await pilot.pause(0.1)
            assert not isinstance(app.screen, SearchScreen)

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
        async with palette.run_test(size=(80, 24)) as pilot:
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
            await pilot.pause()
            options = palette.screen.query_one("#palette-results", OptionList)
            assert_safe(options.get_option_at_index(0).prompt)

        confirmation = ModalHost()
        async with confirmation.run_test(size=(80, 24)) as pilot:
            confirmation.push_screen(ConfirmationScreen(payload))
            await pilot.pause()
            projected = [
                widget.render()
                for widget in confirmation.screen.query(Static)
                if r"\x1b" in str(widget.render())
            ]
            assert len(projected) == 1
            assert_safe(projected[0])

        form_host = ModalHost()
        async with form_host.run_test(size=(80, 24)) as pilot:
            screen = NativeFormScreen(form_spec(ActionId.IDENTITY_SET_NAME))
            form_host.push_screen(screen)
            await pilot.pause()
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
        async with app.run_test(size=(100, 40)) as pilot:
            select = app.screen.query_one("#summon-provider", Select)
            select.value = payload
            await pilot.pause()
            projected = "\n".join(str(widget.render()) for widget in select.query("*"))
            assert "\x1b" not in projected
            assert "\x07" not in projected
            assert r"\x1b" in projected
            assert r"\a" in projected

    asyncio.run(exercise())
