"""Behavioral probes for the retained TUI lock's public Textual seams.

Spec references:
- docs/specs/10-taut-tui.md [TUI-3.1], [TUI-11.3]
- docs/specs/10-taut-tui.md [TUI-12.2], [TUI-13.1]
"""

from __future__ import annotations

import ast
import asyncio
import textwrap
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import pytest
from _completion import CompletionKey, CompletionScope
from tests.helpers.terminal_probe import run_terminal_child
from textual import events
from textual.app import App, ComposeResult
from textual.geometry import Size
from textual.widgets import Input, OptionList, Select, Static

pytestmark = pytest.mark.sqlite_only


def test_production_modules_cannot_bypass_owned_display_sinks() -> None:
    package = Path(__file__).parents[1] / "taut_tui"
    widget_owner = package / "widgets.py"
    app_has_owned_notify = False

    for path in sorted(package.rglob("*.py")):
        if path == widget_owner:
            continue
        tree = ast.parse(path.read_text(), filename=path.name)
        imported_raw_sinks = {
            f"{node.module}:{alias.name}"
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
            and node.module is not None
            and (
                node.module == "textual.widgets"
                or node.module.startswith("textual.widgets.")
            )
            for alias in node.names
            if not (
                node.module == "textual.widgets.option_list" and alias.name == "Option"
            )
        }
        local_escape_wrappers = {
            node.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "_display_text"
        }
        raw_rich_text = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
            and node.module is not None
            and (node.module == "rich.text" or node.module.startswith("rich.text."))
            for alias in node.names
        }
        qualified_sink_imports = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
            if alias.name == "rich.text"
            or alias.name.startswith("rich.text.")
            or alias.name == "textual.widgets"
            or alias.name.startswith("textual.widgets.")
        }
        qualified_sink_from_imports = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module in {"rich", "textual"}
            for alias in node.names
            if (node.module, alias.name) in {("rich", "text"), ("textual", "widgets")}
        }
        direct_escape_imports = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module == "taut"
            for alias in node.names
            if alias.name == "escape_terminal_text"
        }
        tooltip_writes = {
            node.lineno
            for node in ast.walk(tree)
            if (
                isinstance(node, ast.Attribute)
                and isinstance(node.ctx, ast.Store)
                and node.attr == "tooltip"
            )
            or (isinstance(node, ast.keyword) and node.arg == "tooltip")
        }
        if path == package / "app.py":
            app_has_owned_notify = any(
                isinstance(node, ast.FunctionDef) and node.name == "notify"
                for node in ast.walk(tree)
            )

        assert imported_raw_sinks == set(), (path.name, imported_raw_sinks)
        assert local_escape_wrappers == set(), (path.name, local_escape_wrappers)
        assert raw_rich_text == set(), (path.name, raw_rich_text)
        assert qualified_sink_imports == set(), (path.name, qualified_sink_imports)
        assert qualified_sink_from_imports == set(), (
            path.name,
            qualified_sink_from_imports,
        )
        assert direct_escape_imports == set(), (path.name, direct_escape_imports)
        assert tooltip_writes == set(), (path.name, tooltip_writes)

    assert app_has_owned_notify is True


def test_owned_display_sinks_escape_initial_and_updated_content() -> None:
    from rich.text import Text
    from textual.widgets import Button, Checkbox, Label
    from textual.widgets.option_list import Option

    from taut_tui.widgets import (
        DisplayText,
        TautButton,
        TautCheckbox,
        TautComposer,
        TautInput,
        TautLabel,
        TautOptionList,
        TautSelect,
        TautStatic,
        display_text,
        escape_display_text,
    )

    payload = "BEGIN\x1b]8;;https://evil.invalid\x07LOAD\x1b]8;;\x07END"
    escaped = r"BEGIN\x1b]8;;https://evil.invalid\aLOAD\x1b]8;;\aEND"

    class ProbeApp(App[None]):
        def compose(self) -> ComposeResult:
            styled = display_text((payload, "bold"))
            yield TautStatic(styled, id="display")
            yield TautOptionList(Option(payload, id="first"), id="options")
            yield TautInput(placeholder=payload, id="input")
            yield TautComposer(placeholder=payload, id="composer")
            yield TautSelect(((payload, "provider-id"),), id="select")
            yield TautLabel(payload, id="label")
            yield TautButton(payload, id="button")
            yield TautCheckbox(payload, id="checkbox")

    async def exercise() -> None:
        app = ProbeApp()
        async with app.run_test(size=(100, 30)):
            # run_test has already completed Compose/Mount; these render() and
            # property assertions read synchronous owned sink values, not a frame.
            display = app.query_one("#display", Static)
            rendered = display.render()
            assert str(rendered) == escaped
            assert cast(Any, rendered).spans[0].style.bold is True

            options = app.query_one("#options", OptionList)
            assert str(options.get_option_at_index(0).prompt) == escaped
            options.add_options((payload,))
            assert str(options.get_option_at_index(1).prompt) == escaped
            options.add_option(display_text((payload, "italic")))
            updated_prompt = options.get_option_at_index(2).prompt
            assert str(updated_prompt) == escaped
            assert isinstance(updated_prompt, DisplayText)
            assert updated_prompt.spans[0].style == "italic"
            options.replace_option_prompt("first", payload)
            assert str(options.get_option_at_index(0).prompt) == escaped
            options.replace_option_prompt_at_index(1, payload)
            assert str(options.get_option_at_index(1).prompt) == escaped
            options.set_options((payload,))
            assert str(options.get_option_at_index(0).prompt) == escaped

            input_widget = app.query_one("#input", Input)
            assert input_widget.placeholder == escaped
            input_widget.placeholder = payload
            assert input_widget.placeholder == escaped
            input_widget.value = payload
            assert input_widget.value == payload

            composer = app.query_one("#composer", TautComposer)
            assert str(composer.placeholder) == escaped
            composer.placeholder = payload
            assert str(composer.placeholder) == escaped

            label = app.query_one("#label", Label)
            assert str(label.render()) == escaped
            label.update(payload)
            assert str(label.render()) == escaped
            button = app.query_one("#button", Button)
            assert escaped in str(button.render())
            button.label = payload
            assert escaped in str(button.render())
            checkbox = app.query_one("#checkbox", Checkbox)
            assert escaped in str(checkbox.render())
            checkbox.label = payload
            assert escaped in str(checkbox.render())

            select = app.query_one("#select", Select)
            assert select.value != "provider-id"
            select.value = "provider-id"
            assert select.value == "provider-id"
            selected_label = str(select.query_one("#label").render())
            assert escaped in selected_label
            select.value = Select.NULL
            select.prompt = payload
            selected_label = str(select.query_one("#label").render())
            assert escaped in selected_label
            assert payload not in selected_label
            select.set_options(((payload, "replacement-id"),))
            select.value = "replacement-id"
            selected_label = str(select.query_one("#label").render())
            assert escaped in selected_label

            display.update(display_text((payload, "underline")))
            updated = display.render()
            assert str(updated) == escaped
            assert cast(Any, updated).spans[0].style.underline is True

            safe = escape_display_text(payload)
            assert escape_display_text(safe) is safe
            display.update(safe)
            assert str(display.render()) == escaped

            with pytest.raises(TypeError, match="raw Rich Text"):
                display.update(Text("untrusted"))
            with pytest.raises(TypeError, match="unsupported Taut display value"):
                display.update(object())  # type: ignore[arg-type]

    asyncio.run(exercise())


def test_composer_modified_keys_insert_structure_without_submitting() -> None:
    from taut_tui.widgets import TautComposer, TautInput

    class ProbeApp(App[None]):
        def __init__(self) -> None:
            super().__init__()
            self.submissions: list[str] = []

        def compose(self) -> ComposeResult:
            yield TautComposer(id="composer")
            yield TautInput(id="next-field")

        def on_taut_composer_submitted(
            self,
            event: TautComposer.Submitted,
        ) -> None:
            self.submissions.append(event.value)

    async def exercise() -> None:
        app = ProbeApp()
        async with app.run_test(size=(40, 10)) as pilot:
            composer = app.query_one(TautComposer)
            composer.focus()

            await pilot.press(
                "o",
                "n",
                "e",
                "ctrl+enter",
                "t",
                "w",
                "o",
                "shift+enter",
                "m",
                "i",
                "d",
                "ctrl+j",
                "t",
                "h",
                "r",
                "e",
                "e",
                "ctrl+tab",
                "x",
            )

            assert composer.text == "one\ntwo\nmid\nthree\tx"
            assert app.submissions == []

            await pilot.press("tab")
            assert app.query_one("#next-field", TautInput).has_focus
            await pilot.press("shift+tab")
            assert composer.has_focus

            await pilot.press("enter")

            assert composer.text == "one\ntwo\nmid\nthree\tx"
            assert app.submissions == ["one\ntwo\nmid\nthree\tx"]

    asyncio.run(exercise())


def test_composer_preserves_multiline_paste(monkeypatch: pytest.MonkeyPatch) -> None:
    from taut_tui.widgets import TautComposer

    class ProbeApp(App[None]):
        def compose(self) -> ComposeResult:
            yield TautComposer(id="composer")

    async def exercise() -> None:
        app = ProbeApp()
        async with app.run_test(size=(40, 10)):
            composer = app.query_one(TautComposer)
            composer.focus()
            paste = events.Paste("one\n\ttwo")
            with CompletionScope() as scope:
                applied = scope.expect(
                    CompletionKey(composer, "paste.applied", request=paste)
                )
                original = composer._on_message

                async def dispatch(event: Any) -> None:
                    try:
                        await original(event)
                    except BaseException as error:
                        if event is paste:
                            applied.fail(applied.key, error)
                        raise
                    if event is paste:
                        applied.succeed(applied.key, event)

                monkeypatch.setattr(composer, "_on_message", dispatch)
                deadline = scope.now() + 5
                app.post_message(paste)
                await applied.wait(
                    deadline=deadline, description="actual paste applied"
                )

            assert composer.text == "one\n\ttwo"

    asyncio.run(exercise())


def test_message_body_tabs_expand_before_escape_notation() -> None:
    from taut_tui.widgets import escape_message_body

    actual = str(escape_message_body("a\tb\n12\tc"))
    decoded = str(escape_message_body(r"a\tb"))

    assert actual == "a   b\n12  c"
    # [TUI-5.3] (2026-08-18): the literal escape decodes toward sender
    # intent and expands at the same tab stops as a real TAB.
    assert decoded == "a   b"


def test_protected_display_text_is_not_rescanned_by_owned_sink(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from taut_tui.app import TautApp
    from taut_tui.summon import SummonLogBridge

    (tmp_path / ".taut.toml").write_text(
        '[terminal_text]\nescape_patterns = ["\\\\\\\\x"]\n'
    )
    monkeypatch.chdir(tmp_path)

    async def exercise() -> None:
        app = TautApp(db_path=None, as_name=None, continuity_token=None)
        async with app.run_test(size=(80, 24)):
            SummonLogBridge(app._apply_summon_log).accept("\x1b")
            rendered = str(app.query_one("#inspector-body", Static).render())
            assert rendered == "Summon\n" + r"\x1b"

    asyncio.run(exercise())


def test_taut_app_owns_terminal_safe_notification_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from taut_tui.app import TautApp

    captured: list[tuple[str, dict[str, object]]] = []

    def capture(_app: App[None], message: str, **kwargs: object) -> None:
        captured.append((message, kwargs))

    monkeypatch.setattr(App, "notify", capture)
    payload = "PAY\x1b]8;;https://evil.invalid\x07LOAD"
    app = TautApp(db_path=None, as_name=None, continuity_token=None)
    app.notify(payload, title=payload, markup=True)

    assert captured == [
        (
            r"PAY\x1b]8;;https://evil.invalid\aLOAD",
            {
                "title": r"PAY\x1b]8;;https://evil.invalid\aLOAD",
                "severity": "information",
                "timeout": None,
                "markup": False,
            },
        )
    ]


def test_retained_textual_pilot_click_focus_and_resize() -> None:
    class ProbeApp(App[None]):
        def __init__(self) -> None:
            super().__init__()
            self.last_resize: Size | None = None

        def compose(self) -> ComposeResult:
            yield Input(id="first")
            yield Input(id="second")

        def on_resize(self, event: events.Resize) -> None:
            self.last_resize = event.size

    async def exercise() -> None:
        app = ProbeApp()

        async with app.run_test(size=(100, 30)) as pilot:
            # Initial Resize is synchronously dispatched before Mount/ready in
            # retained Textual; run_test's startup boundary already covers it.
            assert app.size == Size(100, 30)
            assert app.last_resize == Size(100, 30)

            assert await pilot.click("#second") is True
            assert app.query_one("#second", Input).has_focus

            await pilot.resize_terminal(49, 19)
            assert app.size == Size(49, 19)
            assert app.last_resize == Size(49, 19)

    asyncio.run(exercise())


def test_retained_textual_selection_and_osc52_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """[TUI-8.2] pins the framework seams used by transcript selection."""

    import base64
    import inspect

    from textual.screen import Screen
    from textual.widget import Widget

    assert OptionList.ALLOW_SELECT is False
    assert events.TextSelected.bubble is True

    selection_watch = inspect.getsource(Screen._watch_selections)
    assert "widget.selection_updated(selections.get(widget, None))" in selection_watch

    forwarding = inspect.getsource(Screen._forward_event)
    selection_start = forwarding.index("self._select_state = SelectState(")
    widget_forward = forwarding.index("widget._forward_event(")
    mouse_up_completion = forwarding.index("self.post_message(events.TextSelected())")
    assert selection_start < widget_forward
    assert mouse_up_completion < widget_forward

    widget_selection = inspect.getsource(Widget.selection_updated)
    assert "self.refresh()" in widget_selection

    async def exercise() -> None:
        app: App[None] = App()
        async with app.run_test():
            writes: list[str] = []
            assert app._driver is not None
            monkeypatch.setattr(app._driver, "write", writes.append)

            app.copy_to_clipboard("policy-filtered")

            encoded = base64.b64encode(b"policy-filtered").decode()
            assert app._clipboard == "policy-filtered"
            assert writes == [f"\x1b]52;c;{encoded}\a"]

    asyncio.run(exercise())


@pytest.mark.parametrize(
    ("control_byte", "label"),
    ((b"\x03", "Ctrl-C"), (b"\x04", "Ctrl-D")),
)
def test_shipped_tui_translates_real_pty_quit_control_bytes(
    control_byte: bytes,
    label: str,
    tmp_path: Path,
) -> None:
    _assert_real_pty_quit_control_bytes(control_byte, label, tmp_path)


def _assert_real_pty_quit_control_bytes(
    control_byte: bytes, label: str, tmp_path: Path
) -> None:
    receipt_path = tmp_path / "quit-control-receipts.txt"
    child_source = f"PROBE_RECEIPT = {str(receipt_path)!r}\n" + textwrap.dedent(
        r"""
        import os
        import platform

        import textual

        import taut_tui.app as app_module
        from taut_tui._launch import run_tui
        from taut_tui.actions import ActionId


        def record(marker: str) -> None:
            # Rendered frames are not a lossless write/event log.
            # Closing each write publishes it before the real quit continues.
            with open(PROBE_RECEIPT, "a", encoding="utf-8") as receipt:
                receipt.write(marker + "\n")


        class ProbeApp(app_module.TautApp):
            def on_mount(self) -> None:
                super().on_mount()
                detail = (
                    f"PROBE-PLATFORM os={os.name} "
                    f"platform={platform.platform()} textual={textual.__version__}"
                )
                os.write(1, detail.encode("utf-8", errors="replace"))
                os.write(1, b"TAUT-TUI-QUIT-CONTROL-PROBE-MOUNTED")

            def action_quit_tui_anywhere(self) -> None:
                record("DECODED-QUIT-BINDING")
                os.write(1, b"DECODED-QUIT-BINDING")
                super().action_quit_tui_anywhere()

            def _dispatch_action_invocation(self, invocation) -> None:
                if invocation.action_id is ActionId.APPLICATION_QUIT:
                    record("GUARDED-QUIT")
                    os.write(1, b"GUARDED-QUIT")
                super()._dispatch_action_invocation(invocation)


        app_module.TautApp = ProbeApp
        raise SystemExit(
            run_tui(db_path=None, as_name=None, continuity_token=None)
        )
        """
    )

    try:
        result = run_terminal_child(
            child_source,
            input_when_output_contains=(
                b"TAUT-TUI-QUIT-CONTROL-PROBE-MOUNTED",
                control_byte,
            ),
            timeout=15,
        )
    except TimeoutError as exc:
        pytest.fail(f"{label} shipped-TUI PTY probe timed out: {exc}")
    captured = result.output
    assert result.input_sent, captured.decode(errors="replace")
    assert result.returncode == 0, captured.decode(errors="replace")
    # The real child and its attach have retired. Read once; no file polling or
    # second control loop, and no claim that a screen frame is an event log.
    assert receipt_path.exists(), captured.decode(errors="replace")
    receipts = receipt_path.read_text(encoding="utf-8").splitlines()
    assert "DECODED-QUIT-BINDING" in receipts
    assert "GUARDED-QUIT" in receipts


def test_quit_control_probe_retains_hooks_when_terminal_markers_are_suppressed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    real_run = run_terminal_child

    def suppress_live_markers(source: str, **kwargs: Any) -> Any:
        # ConPTY reports screen frames, not every write. Force the corresponding
        # observation loss without changing the real app, input, or dispatch.
        source = (
            textwrap.dedent(
                """
            import os

            original_write = os.write

            def write_without_live_markers(fd, data):
                if data in (b"DECODED-QUIT-BINDING", b"GUARDED-QUIT"):
                    return len(data)
                return original_write(fd, data)

            os.write = write_without_live_markers
            """
            )
            + source
        )
        result = real_run(source, **kwargs)
        assert b"DECODED-QUIT-BINDING" not in result.output
        assert b"GUARDED-QUIT" not in result.output
        return result

    monkeypatch.setitem(globals(), "run_terminal_child", suppress_live_markers)
    _assert_real_pty_quit_control_bytes(b"\x03", "Ctrl-C", tmp_path)


@pytest.mark.parametrize("missing_marker", ("DECODED-QUIT-BINDING", "GUARDED-QUIT"))
def test_quit_control_probe_rejects_missing_hook_receipt(
    missing_marker: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    real_run = run_terminal_child

    def drop_hook_receipt(source: str, **kwargs: Any) -> Any:
        marker_call = f'record("{missing_marker}")'
        assert source.count(marker_call) == 1
        # Keep the real handler, its live marker, PTY delivery, and successful
        # exit. None can substitute for the missing exact hook receipt.
        return real_run(source.replace(marker_call, "pass"), **kwargs)

    monkeypatch.setitem(globals(), "run_terminal_child", drop_hook_receipt)
    with pytest.raises(AssertionError, match=missing_marker):
        _assert_real_pty_quit_control_bytes(b"\x03", "Ctrl-C", tmp_path)


def test_retained_textual_ctrl_d_binding_reaches_guarded_quit() -> None:
    from taut_tui.actions import ActionId
    from taut_tui.app import TautApp

    guarded_quit_seen = False

    class ProbeApp(TautApp):
        def _dispatch_action_invocation(self, invocation: Any) -> None:
            nonlocal guarded_quit_seen
            if invocation.action_id is ActionId.APPLICATION_QUIT:
                guarded_quit_seen = True
            super()._dispatch_action_invocation(invocation)

    async def exercise() -> None:
        app = ProbeApp(db_path=None, as_name=None, continuity_token=None)
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.press("ctrl+d")

    asyncio.run(exercise())
    assert guarded_quit_seen


def test_real_textual_pty_never_emits_untrusted_terminal_control_payload() -> None:
    child_source = textwrap.dedent(
        r"""
        from textual.app import App

        from taut_tui.widgets import TautStatic


        class ProbeApp(App[None]):
            def compose(self):
                payload = "BEGIN\x1b]8;;https://evil.invalid\x07LOAD\x1b]8;;\x07END"
                yield TautStatic(payload, id="payload")

            def on_mount(self) -> None:
                self.set_timer(0.05, self._update_payload)
                self.set_timer(0.15, self.exit)

            def _update_payload(self) -> None:
                payload = "UPDATE\x1b]8;;https://evil.invalid\x07LOAD\x1b]8;;\x07END"
                self.query_one("#payload", TautStatic).update(payload)


        ProbeApp().run()
        """
    )
    try:
        result = run_terminal_child(child_source, timeout=10)
    except TimeoutError:
        pytest.fail("Textual terminal-control probe timed out")
    captured = result.output
    assert result.returncode == 0, captured.decode(errors="replace")
    assert b"BEGIN" in captured
    assert b"UPDATE" in captured
    assert b"\x1b]8;;https://evil.invalid\x07" not in captured
    assert b"\\x1b]8;;https://evil.invalid\\a" in captured


def test_retained_textual_suspend_grants_exclusive_real_pty_lease(
    tmp_path: Path,
) -> None:
    _assert_exclusive_real_pty_lease(tmp_path)


def _assert_exclusive_real_pty_lease(tmp_path: Path) -> None:
    import json

    receipt_path = tmp_path / "exclusive-lease-receipts.json"
    child_source = f"PROBE_RECEIPT = {str(receipt_path)!r}\n" + textwrap.dedent(
        r"""
        import json
        import os
        import queue
        import threading
        from contextlib import nullcontext

        from textual.app import App
        from textual.drivers._writer_thread import WriterThread
        from textual.message import Message
        from textual.widgets import Static

        if os.name == "nt":
            from textual.drivers import windows_driver as driver_module
        else:
            from textual.drivers import linux_driver as driver_module

        writer_blocked = threading.Event()
        allow_writer = threading.Event()
        writer_written = threading.Event()
        handoff = queue.Queue(maxsize=2)
        ui_written = threading.Event()
        ui_receipts = set()
        receipts = []
        receipt_lock = threading.Lock()
        pending_output = "TEXTUAL-WRITER-PENDING"


        def record(value):
            with receipt_lock:
                receipts.append(value)


        class ObservedFile:
            def __init__(self, file):
                self.file = file

            def write(self, data):
                if data == pending_output:
                    writer_blocked.set()
                    if not allow_writer.wait(5):
                        raise RuntimeError("queued writer was not released")
                result = self.file.write(data)
                self.file.flush()
                if data == pending_output:
                    record("writer.during" if app.lease_active else "writer.before")
                    writer_written.set()
                for marker in ("UI-QUEUED-BEFORE", "UI-QUEUED-DURING"):
                    if marker in data and marker not in ui_receipts:
                        record(marker + (".restored" if app.restored.is_set() else ".early"))
                        ui_receipts.add(marker)
                        if len(ui_receipts) == 2:
                            ui_written.set()
                return result

            def flush(self):
                self.file.flush()


        class ObservedWriter(WriterThread):
            def __init__(self, file):
                super().__init__(ObservedFile(file))

            def stop(self):
                if writer_blocked.is_set() and not writer_written.is_set():
                    # The existing lease worker reacts to this real owner stop,
                    # or to acquisition if the suspend boundary is removed.
                    handoff.put("writer.stopping")
                super().stop()


        driver_module.WriterThread = ObservedWriter


        class LeaseRequest(Message):
            pass


        class QueuedUi(Message):
            def __init__(self, label):
                super().__init__()
                self.label = label


        class ProbeApp(App[None]):
            def __init__(self) -> None:
                super().__init__()
                self.acquired = threading.Event()
                self.release = threading.Event()
                self.restored = threading.Event()
                self.enter_thread: int | None = None
                self.exit_thread: int | None = None
                self.lease_active = False
                self.failure = None
                self.lease_worker = None

            def compose(self):
                yield Static("textual-screen", id="before")
                yield Static("textual-screen", id="during")

            def on_mount(self) -> None:
                self.lease_worker = threading.Thread(target=self._lease_worker, daemon=False)
                self.lease_worker.start()

            def _lease_worker(self) -> None:
                try:
                    assert self.post_message(LeaseRequest())
                    phase = handoff.get(timeout=5)
                    if phase == "writer.stopping":
                        allow_writer.set()
                    else:
                        assert phase == "lease.acquired"
                    assert self.acquired.wait(5), "lease not acquired"
                    os.write(1, b"\rLEASE-BEGIN")
                    # With real suspend this write has already drained. Without
                    # suspend it is released inside the lease, a semantic breach.
                    allow_writer.set()
                    assert writer_written.wait(5), "pending output not written"
                    assert self.post_message(QueuedUi("during"))
                    os.write(1, b"LEASE-END")
                    self.release.set()
                    assert self.restored.wait(5), "lease not restored"
                    assert ui_written.wait(5), "queued UI output not rendered"
                except BaseException as error:
                    self.failure = type(error).__name__
                finally:
                    allow_writer.set()
                    self.release.set()
                    self.call_from_thread(self.exit)

            def on_lease_request(self, _message: LeaseRequest) -> None:
                self.enter_thread = threading.get_ident()
                self._driver.write(pending_output)
                assert writer_blocked.wait(5), "pending writer did not enter"
                assert self.post_message(QueuedUi("before"))
                with self.suspend():
                    self.lease_active = True
                    self.acquired.set()
                    handoff.put("lease.acquired")
                    try:
                        assert self.release.wait(5), "lease not released"
                    finally:
                        self.lease_active = False
                self.exit_thread = threading.get_ident()
                self.restored.set()

            def on_queued_ui(self, message):
                self.query_one("#" + message.label, Static).update(
                    "UI-QUEUED-" + message.label.upper()
                )


        app = ProbeApp()
        try:
            app.run()
        finally:
            allow_writer.set()
            app.release.set()
            if app.lease_worker is not None:
                app.lease_worker.join(timeout=5)
                assert not app.lease_worker.is_alive(), "lease worker survived cleanup"
        with open(PROBE_RECEIPT, "w", encoding="utf-8") as receipt:
            json.dump({
                "same_ui_thread": app.enter_thread == app.exit_thread,
                "restored": app.restored.is_set(),
                "failure": app.failure,
                "receipts": receipts,
            }, receipt)
        raise SystemExit(app.return_code or 0)
        """
    )
    try:
        result = run_terminal_child(child_source, timeout=15)
    except TimeoutError:
        pytest.fail("Textual PTY suspension probe timed out")
    captured = result.output
    assert result.returncode == 0, captured.decode(errors="replace")
    result_receipts = json.loads(receipt_path.read_text(encoding="utf-8"))
    # The exact real writer's completed I/O is the semantic boundary evidence.
    # Keep raw terminal assertions below as an additional native qualifier; a
    # ConPTY frame is not a lossless log of all writes before restoration.
    assert "writer.during" not in result_receipts["receipts"], (
        "Textual writer output crossed active lease"
    )
    assert b"LEASE-BEGIN" in captured
    assert b"LEASE-END" in captured
    between = captured.split(b"LEASE-BEGIN", 1)[1].split(b"LEASE-END", 1)[0]
    assert between == b"", "Textual writer output crossed active lease"
    assert result_receipts["same_ui_thread"] is True
    assert result_receipts["restored"] is True
    assert result_receipts["failure"] is None
    assert result_receipts["receipts"] == [
        "writer.before",
        "UI-QUEUED-BEFORE.restored",
        "UI-QUEUED-DURING.restored",
    ]


@pytest.mark.parametrize("terminal_markers_visible", (False, True))
def test_real_pty_lease_probe_rejects_removed_suspend(
    terminal_markers_visible: bool, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    real_run = run_terminal_child

    def remove_suspend(source: str, **kwargs: Any) -> Any:
        assert source.count("with self.suspend():") == 1
        result = real_run(
            source.replace("with self.suspend():", "with nullcontext():"), **kwargs
        )
        # Even if a rendered frame omits the lease markers, the exact completed
        # writer I/O must reject the mutant, not fail at a missing-screen marker.
        return result if terminal_markers_visible else replace(result, output=b"")

    monkeypatch.setitem(globals(), "run_terminal_child", remove_suspend)
    with pytest.raises(
        AssertionError, match="Textual writer output crossed active lease"
    ):
        _assert_exclusive_real_pty_lease(tmp_path)


def test_message_body_decodes_closed_escape_allowlist() -> None:
    """[TUI-5.3] message bodies decode the exact inverse escape language."""

    from taut_tui.widgets import escape_message_body

    # Layout escapes become real layout.
    assert str(escape_message_body(r"one\ntwo")) == "one\ntwo"
    assert str(escape_message_body(r"para\n\npara")) == "para\n\npara"
    assert str(escape_message_body(r"a\tb")) == "a   b"
    # Numeric forms for printable characters display as themselves.
    assert str(escape_message_body(r"\x41")) == "A"
    assert str(escape_message_body(r"café")) == "café"
    assert str(escape_message_body(r"hi \U0001f600")) == "hi 😀"
    # Decoded controls other than LF/TAB round-trip through the sink.
    assert str(escape_message_body(r"x\ay")) == r"x\ay"
    assert str(escape_message_body(r"esc\x1bseq")) == r"esc\x1bseq"
    assert str(escape_message_body(r"cr\rlf")) == r"cr\rlf"
    # Short and numeric forms of the same code point decode identically.
    assert str(escape_message_body(r"a\x0ab")) == "a\nb"
    # Malformed and out-of-allowlist forms stay literal.
    assert str(escape_message_body("upper\\u00E9")) == "upper\\u00E9"
    assert str(escape_message_body(r"upper\X41")) == r"upper\X41"
    assert str(escape_message_body(r"not\qreal")) == r"not\qreal"
    assert str(escape_message_body(r"short\x4")) == r"short\x4"
    assert str(escape_message_body("trailing\\")) == "trailing\\"
    # Surrogate and beyond-Unicode code points are malformed, not decoded.
    assert str(escape_message_body(r"bad\ud800")) == r"bad\ud800"
    assert str(escape_message_body(r"big\U00110000")) == r"big\U00110000"
    # A double backslash is not an escape; the second backslash may still
    # start one — there is deliberately no suppression sequence.
    assert str(escape_message_body("a\\\\nb")) == "a\\\nb"


def test_display_text_outside_message_bodies_never_decodes() -> None:
    """Names, metadata, and search previews keep exact stored glyphs."""

    from taut_tui.widgets import escape_display_text, escape_inline_text

    assert str(escape_display_text(r"one\ntwo")) == r"one\ntwo"
    assert str(escape_inline_text(r"one\ntwo")) == r"one\ntwo"
