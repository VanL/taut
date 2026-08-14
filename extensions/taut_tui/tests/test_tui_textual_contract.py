"""Behavioral probes for the retained TUI lock's public Textual seams.

Spec references:
- docs/specs/10-taut-tui.md [TUI-3.1], [TUI-11.3]
"""

from __future__ import annotations

import asyncio
import os
import select
import struct
import subprocess
import sys
import textwrap
import time

import pytest
from textual import events
from textual.app import App, ComposeResult
from textual.geometry import Size
from textual.widgets import Input

pytestmark = pytest.mark.sqlite_only


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
        from rich.text import Text
        from textual.app import App
        from textual.widgets import Static

        from taut_tui.app import _display_text


        class ProbeApp(App[None]):
            def compose(self):
                payload = "BEGIN\x1b]8;;https://evil.invalid\x07LOAD\x1b]8;;\x07END"
                yield Static(Text(_display_text(payload)))

            def on_mount(self) -> None:
                self.set_timer(0.1, self.exit)


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
