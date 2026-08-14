"""Behavioral probes for the retained TUI lock's public Textual seams.

Spec references:
- docs/specs/10-taut-tui.md [TUI-3.1], [TUI-11.3]
- docs/specs/10-taut-tui.md [TUI-12.2], [TUI-13.1]
"""

from __future__ import annotations

import ast
import asyncio
import os
import select
import struct
import subprocess
import sys
import textwrap
import time
from pathlib import Path
from typing import Any, cast

import pytest
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
            yield TautSelect(((payload, "provider-id"),), id="select")
            yield TautLabel(payload, id="label")
            yield TautButton(payload, id="button")
            yield TautCheckbox(payload, id="checkbox")

    async def exercise() -> None:
        app = ProbeApp()
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
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
            await pilot.pause()
            assert app.size == Size(100, 30)
            assert app.last_resize == Size(100, 30)

            assert await pilot.click("#second") is True
            assert app.query_one("#second", Input).has_focus

            await pilot.resize_terminal(49, 19)
            assert app.size == Size(49, 19)
            assert app.last_resize == Size(49, 19)

    asyncio.run(exercise())


def test_real_textual_pty_never_emits_untrusted_terminal_control_payload() -> None:
    if os.name == "nt":
        pytest.skip("stdlib PTY proof is POSIX-only")

    fcntl = pytest.importorskip("fcntl")
    pty = pytest.importorskip("pty")
    termios = pytest.importorskip("termios")
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
    master_fd, slave_fd = pty.openpty()
    process: subprocess.Popen[bytes] | None = None
    output = bytearray()
    try:
        fcntl.ioctl(
            slave_fd,
            termios.TIOCSWINSZ,
            struct.pack("HHHH", 24, 80, 0, 0),
        )
        process = subprocess.Popen(
            [sys.executable, "-c", child_source],
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            close_fds=True,
        )
        os.close(slave_fd)
        slave_fd = -1
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            readable, _, _ = select.select([master_fd], [], [], 0.1)
            if readable:
                try:
                    chunk = os.read(master_fd, 65_536)
                except OSError:
                    break
                if not chunk:
                    break
                output.extend(chunk)
                continue
            if process.poll() is not None:
                break
        else:
            process.kill()
            pytest.fail("Textual terminal-control probe timed out")
        returncode = process.wait(timeout=3)
    finally:
        if slave_fd >= 0:
            os.close(slave_fd)
        os.close(master_fd)
        if process is not None and process.poll() is None:
            process.kill()
            process.wait(timeout=3)

    captured = bytes(output)
    assert returncode == 0, captured.decode(errors="replace")
    assert b"BEGIN" in captured
    assert b"UPDATE" in captured
    assert b"\x1b]8;;https://evil.invalid\x07" not in captured
    assert b"\\x1b]8;;https://evil.invalid\\a" in captured


def test_retained_textual_suspend_grants_exclusive_real_pty_lease() -> None:
    if os.name == "nt":
        pytest.skip("stdlib PTY proof is POSIX-only")

    fcntl = pytest.importorskip("fcntl")
    pty = pytest.importorskip("pty")
    termios = pytest.importorskip("termios")
    child_source = textwrap.dedent(
        r"""
        import json
        import os
        import threading
        import time

        from textual.app import App
        from textual.message import Message
        from textual.widgets import Static


        class LeaseRequest(Message):
            pass


        class ProbeApp(App[None]):
            def __init__(self) -> None:
                super().__init__()
                self.acquired = threading.Event()
                self.release = threading.Event()
                self.restored = threading.Event()
                self.enter_thread: int | None = None
                self.exit_thread: int | None = None

            def compose(self):
                yield Static("textual-screen")

            def on_mount(self) -> None:
                threading.Thread(target=self._lease_worker, daemon=False).start()

            def _lease_worker(self) -> None:
                if not self.post_message(LeaseRequest()):
                    os._exit(20)
                if not self.acquired.wait(5):
                    os._exit(21)
                os.write(1, b"LEASE-BEGIN")
                time.sleep(0.25)
                os.write(1, b"LEASE-END")
                self.release.set()
                if not self.restored.wait(5):
                    os._exit(22)
                self.call_from_thread(self.exit)

            def on_lease_request(self, _message: LeaseRequest) -> None:
                self.enter_thread = threading.get_ident()
                with self.suspend():
                    self.acquired.set()
                    if not self.release.wait(5):
                        os._exit(23)
                self.exit_thread = threading.get_ident()
                self.restored.set()


        app = ProbeApp()
        app.run()
        print(
            "RESULT:"
            + json.dumps(
                {
                    "same_ui_thread": app.enter_thread == app.exit_thread,
                    "restored": app.restored.is_set(),
                }
            ),
            flush=True,
        )
        """
    )
    master_fd, slave_fd = pty.openpty()
    process: subprocess.Popen[bytes] | None = None
    output = bytearray()
    try:
        fcntl.ioctl(
            slave_fd,
            termios.TIOCSWINSZ,
            struct.pack("HHHH", 24, 80, 0, 0),
        )
        process = subprocess.Popen(
            [sys.executable, "-c", child_source],
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            close_fds=True,
        )
        os.close(slave_fd)
        slave_fd = -1
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            readable, _, _ = select.select([master_fd], [], [], 0.1)
            if readable:
                try:
                    chunk = os.read(master_fd, 65_536)
                except OSError:
                    break
                if not chunk:
                    break
                output.extend(chunk)
                continue
            if process.poll() is not None:
                break
        else:
            process.kill()
            pytest.fail("Textual PTY suspension probe timed out")
        returncode = process.wait(timeout=3)
    finally:
        if slave_fd >= 0:
            os.close(slave_fd)
        os.close(master_fd)
        if process is not None and process.poll() is None:
            process.kill()
            process.wait(timeout=3)

    captured = bytes(output)
    assert returncode == 0, captured.decode(errors="replace")
    assert b"LEASE-BEGIN" in captured
    assert b"LEASE-END" in captured
    between = captured.split(b"LEASE-BEGIN", 1)[1].split(b"LEASE-END", 1)[0]
    assert between == b""
    assert b'"same_ui_thread": true' in captured
    assert b'"restored": true' in captured
