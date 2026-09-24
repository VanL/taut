"""Transcript text-selection and OSC 52 clipboard behavior.

Spec references:
- docs/specs/10-taut-tui.md [TUI-8.1], [TUI-8.2], [TUI-12.2], [TUI-13.2]
"""

from __future__ import annotations

import asyncio
import base64
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from textual.app import App, ComposeResult
from textual.widgets.option_list import Option

from taut.client import TautClient
from taut_tui.widgets import TautTranscript, display_text

pytestmark = pytest.mark.sqlite_only


def test_transcript_drag_selects_wrapped_display_lines_without_moving_row() -> None:
    class ProbeApp(App[None]):
        def compose(self) -> ComposeResult:
            yield TautTranscript(
                Option(display_text("first row alpha wraps here")),
                Option(display_text("second row beta")),
                Option(display_text("third row gamma")),
                id="transcript",
            )

    async def exercise() -> None:
        app = ProbeApp()
        async with app.run_test(size=(24, 10)) as pilot:
            transcript = app.query_one(TautTranscript)
            transcript.highlighted = 1
            await pilot.pause()
            assert (
                transcript.get_component_styles("option-list--option").padding.width
                == 0
            )

            assert await pilot.mouse_down(transcript, offset=(3, 1)) is True
            assert await pilot.mouse_up(transcript, offset=(10, 5)) is True
            await pilot.pause()

            assert app.screen.get_selected_text() == (
                "irst row alpha\nwraps here\nsecond row beta\nthird row gamma"
            )
            assert transcript.highlighted == 1

    asyncio.run(exercise())


def test_transcript_selection_preserves_displayed_trailing_spaces() -> None:
    class ProbeApp(App[None]):
        def compose(self) -> ComposeResult:
            yield TautTranscript(
                Option(display_text("kept  ")),
                Option(display_text("next")),
                id="transcript",
            )

    async def exercise() -> None:
        app = ProbeApp()
        async with app.run_test(size=(24, 8)) as pilot:
            transcript = app.query_one(TautTranscript)
            await pilot.pause()

            assert await pilot.mouse_down(transcript, offset=(2, 1)) is True
            assert await pilot.mouse_up(transcript, offset=(20, 2)) is True
            await pilot.pause()

            assert app.screen.get_selected_text() == "kept  \nnext"

    asyncio.run(exercise())


def test_real_app_uses_selectable_transcript_only(tmp_path: Path) -> None:
    from taut_tui.app import TautApp
    from taut_tui.widgets import TautOptionList

    db_path = tmp_path / "selection.db"
    TautClient.init(db_path=db_path)

    async def exercise() -> None:
        app = TautApp(db_path=str(db_path), as_name=None, continuity_token=None)
        async with app.run_test(size=(100, 30)):
            transcript = app.query_one("#transcript", TautOptionList)
            navigation = app.query_one("#navigation-list", TautOptionList)

            assert isinstance(transcript, TautTranscript)
            assert transcript.allow_select is True
            assert isinstance(navigation, TautTranscript) is False
            assert navigation.allow_select is False

    asyncio.run(exercise())


def test_single_click_selects_row_without_arming_auto_copy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from taut_tui.app import TautApp

    db_path = tmp_path / "selection-click.db"
    TautClient.init(db_path=db_path)
    alice = TautClient(db_path=db_path, as_name="alice")
    alice.join("general")
    messages = (
        alice.say("general", "first row"),
        alice.say("general", "second row"),
    )

    async def exercise() -> None:
        app = TautApp(db_path=str(db_path), as_name="alice", continuity_token=None)
        async with app.run_test(size=(100, 30)) as pilot:
            app.visual_state = replace(
                app.visual_state,
                active_conversation="general",
                selected_message_id=messages[0].ts,
            )
            app._render_messages(messages)
            await pilot.pause()
            scheduled: list[float] = []

            def capture_timer(delay: float, *_args: object, **_kwargs: object) -> Any:
                scheduled.append(delay)
                return None

            monkeypatch.setattr(app, "set_timer", capture_timer)
            transcript = app.query_one("#transcript", TautTranscript)

            assert await pilot.click(transcript, offset=(8, 3)) is True
            await pilot.pause()

            assert app.visual_state.selected_message_id == messages[1].ts
            assert app.screen.get_selected_text() is None
            assert 0.5 not in scheduled

    asyncio.run(exercise())


def test_y_copies_current_selection_through_textual_osc52(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from taut_tui.app import TautApp

    db_path = tmp_path / "yank.db"
    TautClient.init(db_path=db_path)
    alice = TautClient(db_path=db_path, as_name="alice")
    alice.join("general")
    messages = (
        alice.say("general", "first row alpha"),
        alice.say("general", "danger \x1b]52;c;RAW\a payload"),
        alice.say("general", "third row gamma"),
    )
    threads_before = alice.list_threads(all_threads=True)

    async def exercise() -> None:
        app = TautApp(db_path=str(db_path), as_name="alice", continuity_token=None)
        async with app.run_test(size=(100, 30)) as pilot:
            app.visual_state = replace(
                app.visual_state,
                active_conversation="general",
                selected_message_id=messages[1].ts,
            )
            app._render_messages(messages)
            await pilot.pause()

            transcript = app.query_one("#transcript", TautTranscript)
            assert await pilot.mouse_down(transcript, offset=(4, 1)) is True
            assert await pilot.mouse_up(transcript, offset=(18, 5)) is True
            await pilot.pause()
            selected = app.screen.get_selected_text()
            assert selected
            assert "\x1b" not in selected
            assert r"\x1b]52;c;RAW\a" in selected
            assert app.visual_state.selected_message_id == messages[1].ts
            assert app.visual_state.active_conversation == "general"
            assert alice.list_threads(all_threads=True) == threads_before

            writes: list[str] = []
            assert app._driver is not None
            monkeypatch.setattr(app._driver, "write", writes.append)

            await pilot.press("y")

            encoded = base64.b64encode(selected.encode()).decode()
            assert app._clipboard == selected
            assert writes == [f"\x1b]52;c;{encoded}\a"]
            assert "copied " in str(app.query_one("#status-line").render())

    asyncio.run(exercise())


def test_transcript_rebuild_cancels_pending_auto_copy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from taut_tui.app import TautApp

    class CapturedTimer:
        def __init__(self) -> None:
            self.stopped = False

        def stop(self) -> None:
            self.stopped = True

    db_path = tmp_path / "rebuild-copy.db"
    TautClient.init(db_path=db_path)
    alice = TautClient(db_path=db_path, as_name="alice")
    alice.join("general")
    messages = (
        alice.say("general", "first row alpha"),
        alice.say("general", "second row beta"),
    )

    async def exercise() -> None:
        app = TautApp(db_path=str(db_path), as_name="alice", continuity_token=None)
        async with app.run_test(size=(100, 30)) as pilot:
            app.visual_state = replace(
                app.visual_state,
                active_conversation="general",
                selected_message_id=messages[0].ts,
            )
            app._render_messages(messages)
            await pilot.pause()

            scheduled: list[tuple[float, Callable[[], Any] | None, CapturedTimer]] = []

            def capture_timer(
                delay: float,
                callback: Callable[[], Any] | None = None,
                **_kwargs: object,
            ) -> Any:
                timer = CapturedTimer()
                scheduled.append((delay, callback, timer))
                return timer

            monkeypatch.setattr(app, "set_timer", capture_timer)
            writes: list[str] = []
            assert app._driver is not None
            monkeypatch.setattr(app._driver, "write", writes.append)
            transcript = app.query_one("#transcript", TautTranscript)

            assert await pilot.mouse_down(transcript, offset=(4, 1)) is True
            assert await pilot.mouse_up(transcript, offset=(18, 3)) is True
            await pilot.pause()
            assert scheduled[0][0] == 0.5
            callback = scheduled[0][1]
            assert callback is not None

            app._render_messages(messages)
            await pilot.pause()

            assert scheduled[0][2].stopped is True
            callback()
            assert [write for write in writes if write.startswith("\x1b]52;")] == []

    asyncio.run(exercise())


def test_copy_failure_is_safe_and_keeps_selection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from taut_tui.app import TautApp

    db_path = tmp_path / "copy-failure.db"
    TautClient.init(db_path=db_path)
    alice = TautClient(db_path=db_path, as_name="alice")
    alice.join("general")
    messages = (alice.say("general", "copy me"),)

    async def exercise() -> None:
        app = TautApp(db_path=str(db_path), as_name="alice", continuity_token=None)
        async with app.run_test(size=(100, 30)) as pilot:
            app.visual_state = replace(
                app.visual_state,
                active_conversation="general",
                selected_message_id=messages[0].ts,
            )
            app._render_messages(messages)
            await pilot.pause()
            transcript = app.query_one("#transcript", TautTranscript)
            assert await pilot.mouse_down(transcript, offset=(4, 0)) is True
            assert await pilot.mouse_up(transcript, offset=(24, 1)) is True
            await pilot.pause()
            selected = app.screen.get_selected_text()
            assert selected

            notices: list[tuple[str, str]] = []

            def fail_write(_payload: str) -> None:
                raise OSError("driver closed")

            def capture_notice(
                message: str,
                *,
                severity: str = "information",
                **_kwargs: object,
            ) -> None:
                notices.append((message, severity))

            assert app._driver is not None
            monkeypatch.setattr(app._driver, "write", fail_write)
            monkeypatch.setattr(app, "notify", capture_notice)
            clipboard_before = app._clipboard

            await pilot.press("y")

            assert app.screen.get_selected_text() == selected
            assert app._clipboard == clipboard_before
            assert notices == [("Unable to copy selection: driver closed", "error")]

    asyncio.run(exercise())


def test_help_names_y_auto_copy_and_osc52_limits() -> None:
    from taut_tui.app import TautApp

    async def exercise() -> None:
        app = TautApp(db_path=None, as_name=None, continuity_token=None)
        async with app.run_test(size=(100, 30)):
            app.action_open_help()
            help_text = str(app.query_one("#inspector-body").render())
            assert "y copies" in help_text
            assert "500 ms" in help_text
            assert "macOS Terminal.app" in help_text
            assert "tmux without set-clipboard on" in help_text
            assert "Modified drag" in help_text

    asyncio.run(exercise())


def test_copy_status_note_never_overwrites_operation_failure() -> None:
    from taut_tui.app import TautApp

    async def exercise() -> None:
        app = TautApp(db_path=None, as_name=None, continuity_token=None)
        async with app.run_test(size=(100, 30)):
            app._operation_state = "send failed: retained primary error"
            app._set_copy_status_note("copied 12 characters")

            status = str(app.query_one("#status-line").render())
            assert "send failed: retained primary error" in status
            assert "copied 12 characters" not in status

    asyncio.run(exercise())


def test_completed_selection_auto_copy_resets_for_changed_selection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from taut_tui.app import TautApp

    class CapturedTimer:
        def __init__(self) -> None:
            self.stopped = False

        def stop(self) -> None:
            self.stopped = True

    db_path = tmp_path / "auto-copy.db"
    TautClient.init(db_path=db_path)
    alice = TautClient(db_path=db_path, as_name="alice")
    alice.join("general")
    messages = (
        alice.say("general", "first row alpha"),
        alice.say("general", "second row beta"),
        alice.say("general", "third row gamma"),
    )

    async def exercise() -> None:
        app = TautApp(db_path=str(db_path), as_name="alice", continuity_token=None)
        async with app.run_test(size=(100, 30)) as pilot:
            app.visual_state = replace(
                app.visual_state,
                active_conversation="general",
                selected_message_id=messages[1].ts,
            )
            app._render_messages(messages)
            await pilot.pause()

            scheduled: list[tuple[float, Callable[[], Any] | None, CapturedTimer]] = []

            def capture_timer(
                delay: float,
                callback: Callable[[], Any] | None = None,
                **_kwargs: object,
            ) -> Any:
                timer = CapturedTimer()
                scheduled.append((delay, callback, timer))
                return timer

            monkeypatch.setattr(app, "set_timer", capture_timer)
            writes: list[str] = []
            assert app._driver is not None
            monkeypatch.setattr(app._driver, "write", writes.append)
            transcript = app.query_one("#transcript", TautTranscript)

            assert await pilot.mouse_down(transcript, offset=(4, 1)) is True
            assert await pilot.mouse_up(transcript, offset=(18, 3)) is True
            await pilot.pause()
            first_text = app.screen.get_selected_text()
            assert first_text
            assert scheduled[0][0] == 0.5
            assert [write for write in writes if write.startswith("\x1b]52;")] == []

            assert await pilot.mouse_down(transcript, offset=(6, 2)) is True
            assert await pilot.mouse_up(transcript, offset=(24, 5)) is True
            await pilot.pause()
            second_text = app.screen.get_selected_text()
            assert second_text and second_text != first_text
            assert scheduled[0][2].stopped is True
            assert scheduled[1][0] == 0.5

            first_callback = scheduled[0][1]
            second_callback = scheduled[1][1]
            assert first_callback is not None
            assert second_callback is not None
            first_callback()
            assert [write for write in writes if write.startswith("\x1b]52;")] == []
            second_callback()

            encoded = base64.b64encode(second_text.encode()).decode()
            assert app._clipboard == second_text
            assert [write for write in writes if write.startswith("\x1b]52;")] == [
                f"\x1b]52;c;{encoded}\a"
            ]

    asyncio.run(exercise())
