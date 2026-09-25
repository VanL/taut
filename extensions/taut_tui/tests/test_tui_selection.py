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
from _app_completion import AppCompletions, observed
from _completion import Completion, CompletionKey, CompletionScope
from textual import events
from textual.app import App, ComposeResult
from textual.widgets.option_list import Option

from taut.client import TautClient
from taut_tui.widgets import TautTranscript, display_text

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


class _SelectionApplied:
    """One exact TextSelected produced by this transcript's mouse release."""

    def __init__(
        self,
        transcript: TautTranscript,
        scope: CompletionScope,
        patch: pytest.MonkeyPatch,
    ) -> None:
        self.record: Completion[Any] | None = None
        screen = transcript.screen
        app = transcript.app
        original_forward = screen._forward_event
        original_post = screen.post_message
        original_dispatch = app._on_message
        release: events.MouseUp | None = None

        def forward(event: events.Event) -> None:
            nonlocal release
            previous = release
            if isinstance(event, events.MouseUp) and event.widget is transcript:
                release = event
            try:
                original_forward(event)
            finally:
                release = previous

        def post(event: Any) -> bool:
            if release is not None and isinstance(event, events.TextSelected):
                assert self.record is None, "one mouse release per observer"
                self.record = scope.expect(
                    CompletionKey(screen, "selection.applied", request=event)
                )
            return original_post(event)

        async def dispatch(event: Any) -> None:
            record = self.record
            selected = record is not None and event is record.key.request
            try:
                await original_dispatch(event)
            except BaseException as error:
                if selected and record is not None:
                    record.fail(record.key, error)
                raise
            if selected and record is not None:
                record.succeed(record.key, event)

        patch.setattr(screen, "_forward_event", forward)
        patch.setattr(screen, "post_message", post)
        patch.setattr(app, "_on_message", dispatch)

    async def wait(self, *, deadline: float) -> None:
        assert self.record is not None, "mouse release did not post TextSelected"
        await self.record.wait(
            deadline=deadline, description="selection handler applied"
        )


async def _drag_selection(
    pilot: Any,
    transcript: TautTranscript,
    start: tuple[int, int],
    end: tuple[int, int],
) -> None:
    with CompletionScope() as scope, pytest.MonkeyPatch.context() as patch:
        applied = _SelectionApplied(transcript, scope, patch)
        deadline = scope.now() + 5
        assert await pilot.mouse_down(transcript, offset=start) is True
        assert await pilot.mouse_up(transcript, offset=end) is True
        await applied.wait(deadline=deadline)


async def _plain_transcript_refreshed(transcript: TautTranscript) -> None:
    # These plain Textual fixtures have no session/worker work. The framework's
    # exact next refresh owns initial layout and the synchronous highlight edit;
    # this finite act fence does not assert arbitrary future domain readiness.
    with CompletionScope() as scope:

        def refreshed() -> None:
            record.succeed(record.key, transcript.virtual_size)

        record = scope.expect(
            CompletionKey(transcript, "fixture.refreshed", request=refreshed)
        )
        # Preserve Pilot's existing 30-second framework readiness watchdog.
        deadline = scope.now() + 30
        transcript.call_after_refresh(refreshed)
        await record.wait(deadline=deadline, description="fixture transcript refresh")


async def _render_messages(app: Any, messages: Any) -> None:
    observer = observed(app)
    transcript = app.query_one("#transcript", TautTranscript)
    measured = observer.rows_measured(transcript)
    deadline = observer.scope.now() + 5
    app._render_messages(messages)
    await measured.wait(deadline=deadline, description="rendered transcript measured")
    await observer.viewport(deadline=deadline)


@pytest.mark.parametrize("handler_error", (False, True))
def test_selection_completion_waits_for_its_exact_real_handler(
    handler_error: bool,
) -> None:
    failure = RuntimeError("selection handler failed")
    handled: list[events.TextSelected] = []
    unrelated_applied = asyncio.Event()
    unrelated = events.TextSelected()

    class ProbeApp(App[None]):
        def compose(self) -> ComposeResult:
            yield TautTranscript(Option(display_text("select this text")))

        def on_text_selected(self, event: events.TextSelected) -> None:
            if event is unrelated:
                unrelated_applied.set()
            elif handler_error:
                raise failure
            handled.append(event)

    async def exercise() -> None:
        app = ProbeApp()
        async with app.run_test(size=(24, 8)) as pilot:
            transcript = app.query_one(TautTranscript)
            await _plain_transcript_refreshed(transcript)
            with CompletionScope() as scope, pytest.MonkeyPatch.context() as patch:
                held: list[events.TextSelected] = []
                real_post = app.screen.post_message

                def hold(event: Any) -> bool:
                    if isinstance(event, events.TextSelected):
                        held.append(event)
                        return True
                    return real_post(event)

                patch.setattr(app.screen, "post_message", hold)
                applied = _SelectionApplied(transcript, scope, patch)
                deadline = scope.now() + 5
                assert await pilot.mouse_down(transcript, offset=(2, 1)) is True
                assert await pilot.mouse_up(transcript, offset=(15, 1)) is True
                assert len(held) == 1
                assert applied.record is not None
                assert applied.record.key.request is held[0]
                assert applied.record.snapshot() is None

                real_post(unrelated)
                await asyncio.wait_for(
                    unrelated_applied.wait(), timeout=deadline - scope.now()
                )
                assert handled == [unrelated]
                assert applied.record.snapshot() is None

                if handler_error:
                    with pytest.raises(RuntimeError) as dispatched:
                        await app._on_message(held[0])
                    with pytest.raises(RuntimeError) as observed_error:
                        await applied.wait(deadline=deadline)
                    assert dispatched.value is failure
                    assert observed_error.value is failure
                else:
                    real_post(held[0])
                    await applied.wait(deadline=deadline)
                    assert handled == [unrelated, held[0]]

    asyncio.run(exercise())


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
            await _plain_transcript_refreshed(transcript)
            assert (
                transcript.get_component_styles("option-list--option").padding.width
                == 0
            )

            await _drag_selection(pilot, transcript, (3, 1), (10, 5))

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
            await _plain_transcript_refreshed(transcript)

            await _drag_selection(pilot, transcript, (2, 1), (20, 2))

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
            await observed(app).navigation()
            app.visual_state = replace(
                app.visual_state,
                active_conversation="general",
                selected_message_id=messages[0].ts,
            )
            await _render_messages(app, messages)
            scheduled: list[float] = []

            def capture_timer(delay: float, *_args: object, **_kwargs: object) -> Any:
                scheduled.append(delay)
                return None

            monkeypatch.setattr(app, "set_timer", capture_timer)
            transcript = app.query_one("#transcript", TautTranscript)

            with CompletionScope() as scope, pytest.MonkeyPatch.context() as patch:
                selection = _SelectionApplied(transcript, scope, patch)
                viewport = observed(app).user_viewport()
                deadline = scope.now() + 5
                assert await pilot.click(transcript, offset=(8, 3)) is True
                await selection.wait(deadline=deadline)
                await viewport.wait(
                    deadline=deadline, description="clicked row applied"
                )

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
            await observed(app).navigation()
            app.visual_state = replace(
                app.visual_state,
                active_conversation="general",
                selected_message_id=messages[1].ts,
            )
            await _render_messages(app, messages)

            transcript = app.query_one("#transcript", TautTranscript)
            await _drag_selection(pilot, transcript, (4, 1), (18, 5))
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
            await observed(app).navigation()
            app.visual_state = replace(
                app.visual_state,
                active_conversation="general",
                selected_message_id=messages[0].ts,
            )
            await _render_messages(app, messages)

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

            await _drag_selection(pilot, transcript, (4, 1), (18, 3))
            assert scheduled[0][0] == 0.5
            callback = scheduled[0][1]
            assert callback is not None

            await _render_messages(app, messages)

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
            await observed(app).navigation()
            app.visual_state = replace(
                app.visual_state,
                active_conversation="general",
                selected_message_id=messages[0].ts,
            )
            await _render_messages(app, messages)
            transcript = app.query_one("#transcript", TautTranscript)
            await _drag_selection(pilot, transcript, (4, 0), (24, 1))
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
            await observed(app).navigation()
            app.visual_state = replace(
                app.visual_state,
                active_conversation="general",
                selected_message_id=messages[1].ts,
            )
            await _render_messages(app, messages)

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

            await _drag_selection(pilot, transcript, (4, 1), (18, 3))
            first_text = app.screen.get_selected_text()
            assert first_text
            assert scheduled[0][0] == 0.5
            assert [write for write in writes if write.startswith("\x1b]52;")] == []

            await _drag_selection(pilot, transcript, (6, 2), (24, 5))
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
