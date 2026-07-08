"""PTY adapter tests against the fake interactive TUI subprocess.

Contract under test: docs/specs/04-summon.md [SUM-7.4]. The PTY, subprocess,
terminal-query responder, and injection path are real; only the model/TUI is
fake and deterministic.
"""

from __future__ import annotations

import json
import os
import queue
import select
import sys
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from taut_summon._adapter import (
    ActivityEvent,
    AdapterEvent,
    AdapterHandle,
    ExitEvent,
    UnknownAdapterError,
    adapter_names,
    get_adapter,
)

pty = pytest.importorskip("pty", reason="POSIX PTY tests require the pty module")
if TYPE_CHECKING:
    from taut_summon._pty import (
        PtyAdapter,
        PtyHandle,
        PtySpec,
        _TerminalResponder,
    )
else:
    _pty_module = pytest.importorskip(
        "taut_summon._pty", reason="POSIX PTY tests require fcntl/termios"
    )
    PtyAdapter = _pty_module.PtyAdapter
    PtyHandle = _pty_module.PtyHandle
    PtySpec = _pty_module.PtySpec
    _TerminalResponder = _pty_module._TerminalResponder

FAKE_TUI = Path(__file__).with_name("fixtures") / "fake_tui.py"

# These tests allocate real PTYs and intentionally exercise full input queues,
# signal/close races, and fake TUI startup. They run under xdist, but in the
# process-heavy group so host PTY/process pressure does not become the behavior
# under test.
pytestmark = pytest.mark.xdist_group("process")


class EventPump:
    def __init__(self, handle: AdapterHandle) -> None:
        self._items: queue.Queue[AdapterEvent | Exception] = queue.Queue()
        self._thread = threading.Thread(target=self._run, args=(handle,), daemon=True)
        self._thread.start()

    def _run(self, handle: AdapterHandle) -> None:
        try:
            for event in handle.events():
                self._items.put(event)
        except Exception as exc:  # noqa: BLE001 - relayed to the test thread
            self._items.put(exc)

    def next(self, timeout: float = 10.0) -> AdapterEvent:
        try:
            item = self._items.get(timeout=timeout)
        except queue.Empty:
            raise AssertionError("timed out waiting for a PTY event") from None
        if isinstance(item, Exception):
            raise item
        return item

    def drain_until_exit(self, timeout: float = 10.0) -> ExitEvent:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            event = self.next(timeout=deadline - time.monotonic())
            if isinstance(event, ExitEvent):
                return event
        raise AssertionError("timed out waiting for PTY exit")


def _spawn_fake(
    tmp_path: Path,
    config: dict[str, Any],
    *,
    rows: int = 24,
    cols: int = 80,
    stall_s: float = 0.5,
) -> tuple[PtyHandle, Path]:
    log = tmp_path / "fake-tui.jsonl"
    spec = PtySpec(
        name="fake",
        argv=(sys.executable, str(FAKE_TUI)),
        rows=rows,
        cols=cols,
        stall_s=stall_s,
        quiet_ms=50,
        max_settle_s=0.5,
    )
    handle = PtyAdapter(spec).spawn(
        session_id=None,
        system_prompt="ignored for PTY",
        env={
            "TAUT_FAKE_TUI_CONFIG": json.dumps(config),
            "TAUT_FAKE_TUI_LOG": str(log),
            "TAUT_FAKE_TUI_ROWS": str(rows),
            "TAUT_FAKE_TUI_COLS": str(cols),
        },
    )
    assert isinstance(handle, PtyHandle)
    return handle, log


def _entries(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _wait_for(path: Path, event: str, *, timeout: float = 10.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for entry in _entries(path):
            if entry.get("event") == event:
                return entry
        time.sleep(0.05)
    raise AssertionError(f"timed out waiting for {event}: {_entries(path)!r}")


def _read_fd_until(fd: int, needle: bytes, *, timeout: float = 5.0) -> bytes:
    deadline = time.monotonic() + timeout
    out = b""
    while time.monotonic() < deadline:
        ready, _, _ = select.select([fd], [], [], 0.05)
        if not ready:
            continue
        out += os.read(fd, 4096)
        if needle in out:
            return out
    return out


def test_registry_maps_named_harnesses_to_pty_specs() -> None:
    expected = {
        "claude": "claude",
        "codex": "codex",
        "coder": "coder",
        "grok": "grok",
        "qwen": "qwen",
        "kimi": "kimi",
        "opencode": "opencode",
        "pi": "pi",
    }
    assert expected.keys() <= set(adapter_names())
    for name, binary in expected.items():
        adapter = get_adapter(name)
        assert isinstance(adapter, PtyAdapter)
        assert adapter.name == name
        assert adapter.argv == (binary,)
    with pytest.raises(UnknownAdapterError, match="known adapters"):
        get_adapter("code")


def test_pty_responder_answers_startup_queries_and_clamps_size(
    tmp_path: Path,
) -> None:
    handle, log = _spawn_fake(
        tmp_path, {"queries": True, "modes": False}, rows=31, cols=97
    )
    pump = EventPump(handle)
    try:
        _wait_for(log, "query")
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            queries = [entry for entry in _entries(log) if entry["event"] == "query"]
            if len(queries) >= 10:
                break
            time.sleep(0.05)
        else:
            raise AssertionError(f"missing query records: {_entries(log)!r}")

        by_name = {entry["name"]: entry for entry in queries}
        assert all(entry["ok"] for entry in queries)
        assert by_name["absolute-size"]["expected"] == "\x1b[31;97R"
        assert by_name["relative-size"]["expected"] == "\x1b[31;97R"
        assert "999;999R" not in by_name["absolute-size"]["got"]
        assert "1;1R" not in by_name["relative-size"]["got"]
    finally:
        handle.close()
        assert isinstance(pump.drain_until_exit(), ExitEvent)


def test_pty_responder_handles_live_observed_parameterized_queries() -> None:
    responder = _TerminalResponder(rows=31, cols=97)

    replies = responder.feed(b"\x1b[>0q\x1b[>7u\x1b[>1u\x1b[0 q\x1b[1 q\x1b[?996n")

    assert replies == [
        b"\x1bP>|taut-summon(0)\x1b\\",
        b"\x1b[?997;1n",
    ]
    assert responder.outstanding_query is None


def test_line_mode_inject_collapses_newlines_and_strips_controls(
    tmp_path: Path,
) -> None:
    handle, log = _spawn_fake(
        tmp_path, {"queries": False, "modes": False, "redraw": False}
    )
    pump = EventPump(handle)
    try:
        _wait_for(log, "start")
        handle.inject("one\r\ntwo\t\x1b[201~\x7f")
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            inputs = [entry for entry in _entries(log) if entry["event"] == "input"]
            if inputs:
                raw = inputs[-1]["raw"]
                assert raw == "one two [201~\r"
                break
            time.sleep(0.05)
        else:
            raise AssertionError(f"no input recorded: {_entries(log)!r}")
    finally:
        handle.close()
    assert isinstance(pump.drain_until_exit(), ExitEvent)


def test_bracketed_paste_preserves_newlines_after_sanitizing(
    tmp_path: Path,
) -> None:
    handle, log = _spawn_fake(tmp_path, {"queries": False, "modes": True})
    pump = EventPump(handle)
    try:
        # Wait until the reader has observed the fake TUI's bracketed-paste enable.
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline and not handle._bracketed_paste:  # noqa: SLF001
            time.sleep(0.05)
        assert handle._bracketed_paste is True  # noqa: SLF001

        handle.inject("one\ntwo\x1b[201~\x7f")
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            inputs = [entry for entry in _entries(log) if entry["event"] == "input"]
            if inputs:
                raw = inputs[-1]["raw"]
                assert raw == "\x1b[200~one\ntwo[201~\x1b[201~\r"
                break
            time.sleep(0.05)
        else:
            raise AssertionError(f"no input recorded: {_entries(log)!r}")
    finally:
        handle.close()
    assert isinstance(pump.drain_until_exit(), ExitEvent)


def test_unknown_report_shaped_query_sets_status_without_reply(
    tmp_path: Path,
) -> None:
    handle, log = _spawn_fake(
        tmp_path,
        {
            "queries": False,
            "modes": False,
            "unknown_query": "[?15n",
            "unknown_blocks": True,
        },
        stall_s=0.2,
    )
    pump = EventPump(handle)
    try:
        _wait_for(log, "unknown_reply_window")
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            fields = handle.status_fields()
            if fields.get("awaiting_query") == "[?15n":
                break
            time.sleep(0.05)
        else:
            raise AssertionError(f"awaiting_query not set: {handle.status_fields()}")
        window = [
            entry for entry in _entries(log) if entry["event"] == "unknown_reply_window"
        ][-1]
        assert window["got"] == ""
    finally:
        handle.close()
    assert isinstance(pump.drain_until_exit(), ExitEvent)


def test_close_does_not_block_behind_full_pty_input_queue(tmp_path: Path) -> None:
    handle, log = _spawn_fake(
        tmp_path,
        {
            "queries": False,
            "modes": False,
            "unknown_query": "[?15n",
            "unknown_blocks": True,
        },
        stall_s=0.2,
    )
    pump = EventPump(handle)
    _wait_for(log, "unknown_reply_window")
    injected: list[BaseException] = []

    def _inject_large() -> None:
        try:
            handle.inject("x" * 5_000_000)
        except BaseException as exc:  # noqa: BLE001 - asserted after close
            injected.append(exc)

    injector = threading.Thread(target=_inject_large, daemon=True)
    injector.start()
    time.sleep(0.2)
    assert injector.is_alive()

    closer = threading.Thread(target=handle.close, daemon=True)
    closer.start()
    closer.join(timeout=3.0)
    assert not closer.is_alive()
    pump.drain_until_exit(timeout=5.0)
    injector.join(timeout=5.0)
    assert not injector.is_alive()


def test_interrupt_unblocks_full_pty_input_queue(tmp_path: Path) -> None:
    handle, log = _spawn_fake(
        tmp_path,
        {
            "queries": False,
            "modes": False,
            "unknown_query": "[?15n",
            "unknown_blocks": True,
        },
        stall_s=0.2,
    )
    pump = EventPump(handle)
    _wait_for(log, "unknown_reply_window")

    injected: list[BaseException] = []

    def _inject_large() -> None:
        try:
            handle.inject("x" * 5_000_000)
        except BaseException as exc:  # noqa: BLE001 - expected after interrupt
            injected.append(exc)

    injector = threading.Thread(target=_inject_large, daemon=True)
    injector.start()
    time.sleep(0.2)
    assert injector.is_alive()

    handle.interrupt()
    injector.join(timeout=3.0)
    assert not injector.is_alive()
    handle.close()
    pump.drain_until_exit(timeout=5.0)


def test_activity_is_coarse_not_per_redraw(tmp_path: Path) -> None:
    handle, _log = _spawn_fake(tmp_path, {"queries": False, "modes": False})
    pump = EventPump(handle)
    try:
        seen = [pump.next(timeout=3.0) for _ in range(2)]
        assert sum(isinstance(event, ActivityEvent) for event in seen) <= 2
        with pytest.raises(AssertionError, match="timed out"):
            pump.next(timeout=0.4)
    finally:
        handle.close()
    assert isinstance(pump.drain_until_exit(), ExitEvent)


def test_attach_bridges_and_split_chord_detaches_with_reset(
    tmp_path: Path,
) -> None:
    handle, log = _spawn_fake(
        tmp_path, {"queries": False, "modes": False, "redraw": False}
    )
    user_master, user_slave = pty.openpty()
    wake = threading.Event()
    shutdown = threading.Event()
    result: list[str] = []
    thread = threading.Thread(
        target=lambda: result.append(
            handle.attach(
                wake=wake, shutdown=shutdown, input_fd=user_slave, output_fd=user_slave
            )
        ),
        daemon=True,
    )
    thread.start()
    try:
        assert b"ready" in _read_fd_until(user_master, b"ready")
        os.write(user_master, b"hello\r")
        wait_deadline = time.monotonic() + 5.0
        while time.monotonic() < wait_deadline:
            inputs = [entry for entry in _entries(log) if entry["event"] == "input"]
            if inputs:
                assert inputs[-1]["raw"] == "hello\r"
                break
            time.sleep(0.05)
        else:
            raise AssertionError(f"no bridged input: {_entries(log)!r}")

        os.write(user_master, b"\x1c")
        time.sleep(0.1)
        assert thread.is_alive()
        os.write(user_master, b"\x1c")
        reset = _read_fd_until(user_master, b"\x1b[?2004l", timeout=1.0)
        thread.join(timeout=5.0)
        assert result == ["detached"]
        assert b"\x18\x1b\\" in reset
        assert b"\x1b[?1049l" in reset
        assert b"\x1b[0m" in reset
    finally:
        handle.close()
        os.close(user_master)
        os.close(user_slave)


def test_attach_forwards_escape_prefixed_input(
    tmp_path: Path,
) -> None:
    handle, log = _spawn_fake(tmp_path, {"queries": False, "modes": False})
    user_master, user_slave = pty.openpty()
    wake = threading.Event()
    shutdown = threading.Event()
    thread = threading.Thread(
        target=lambda: handle.attach(
            wake=wake, shutdown=shutdown, input_fd=user_slave, output_fd=user_slave
        ),
        daemon=True,
    )
    thread.start()
    try:
        assert b"ready" in _read_fd_until(user_master, b"ready")
        os.write(user_master, b"\x1b[A\r")
        wait_deadline = time.monotonic() + 5.0
        while time.monotonic() < wait_deadline:
            inputs = [entry for entry in _entries(log) if entry["event"] == "input"]
            if inputs:
                assert inputs[-1]["raw"] == "\x1b[A\r"
                break
            time.sleep(0.05)
        else:
            raise AssertionError(f"ESC input not forwarded: {_entries(log)!r}")
        os.write(user_master, b"\x1c\x1c")
        thread.join(timeout=5.0)
    finally:
        handle.close()
        os.close(user_master)
        os.close(user_slave)


def test_attach_shutdown_wake_exits_bridge(
    tmp_path: Path,
) -> None:
    handle, _log = _spawn_fake(
        tmp_path, {"queries": False, "modes": False, "redraw": False}
    )
    user_master, user_slave = pty.openpty()
    wake = threading.Event()
    shutdown = threading.Event()
    result: list[str] = []
    thread = threading.Thread(
        target=lambda: result.append(
            handle.attach(
                wake=wake, shutdown=shutdown, input_fd=user_slave, output_fd=user_slave
            )
        ),
        daemon=True,
    )
    thread.start()
    try:
        assert b"ready" in _read_fd_until(user_master, b"ready")
        shutdown.set()
        wake.set()
        reset = _read_fd_until(user_master, b"\x1b[?2004l", timeout=1.0)
        thread.join(timeout=5.0)
        assert result == ["shutdown"]
        assert b"\x1b[?1049l" in reset
    finally:
        handle.close()
        os.close(user_master)
        os.close(user_slave)
