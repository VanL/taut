"""PTY adapter tests against the fake interactive TUI subprocess.

Contract under test: docs/specs/04-summon.md [SUM-7.4]. The PTY, subprocess,
terminal-query responder, and injection path are real; only the model/TUI is
fake and deterministic.
"""

from __future__ import annotations

import errno
import importlib.util
import json
import os
import queue
import select
import signal
import socket
import subprocess
import sys
import threading
import time
import types
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import pytest
from taut_summon._adapter import (
    ActivityEvent,
    AdapterError,
    AdapterEvent,
    AdapterHandle,
    ExitEvent,
    UnknownAdapterError,
    adapter_names,
    get_adapter,
)

pty = pytest.importorskip("pty", reason="POSIX PTY tests require the pty module")
termios = pytest.importorskip(
    "termios", reason="POSIX PTY tests require terminal attributes"
)
if TYPE_CHECKING:
    import taut_summon._pty as _pty_module
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

_TERMINAL_RESPONSE_BUFFER_LIMIT = _pty_module._TERMINAL_RESPONSE_BUFFER_LIMIT

FAKE_TUI = Path(__file__).with_name("fixtures") / "fake_tui.py"

# These tests allocate real PTYs and intentionally exercise full input queues,
# signal/close races, and fake TUI startup. They run under xdist, but in the
# process-heavy group so host PTY/process pressure does not become the behavior
# under test.
pytestmark = [pytest.mark.xdist_group("process"), pytest.mark.sqlite_only]


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


class _ScheduledPtyProcess:
    """Popen-shaped boundary fake for deterministic reap scheduling."""

    pid = 999_999

    def __init__(self) -> None:
        self.returncode: int | None = None
        self.wait_entered = threading.Event()
        self.release_wait = threading.Event()
        self.wait_calls = 0

    def poll(self) -> int | None:
        return self.returncode

    def wait(self, timeout: float | None = None) -> int:
        del timeout
        self.wait_calls += 1
        self.wait_entered.set()
        assert self.release_wait.wait(timeout=2.0)
        self.returncode = 0
        return 0

    def send_signal(self, _signum: int) -> None:
        pass


class _NeverReapsPtyProcess(_ScheduledPtyProcess):
    def wait(self, timeout: float | None = None) -> int:
        self.wait_calls += 1
        raise subprocess.TimeoutExpired("never-reaps-pty", timeout or 0.0)


class _BlockingWriterLock:
    def __init__(self) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()

    def __enter__(self) -> None:
        self.entered.set()
        assert self.release.wait(timeout=2.0)

    def __exit__(self, *_args: object) -> None:
        return None


class _TrackingWriterLock:
    """Expose when a named queued writer reaches the real serializer."""

    def __init__(self, *, tracked_thread: str) -> None:
        self._lock = threading.Lock()
        self._tracked_thread = tracked_thread
        self.tracked_acquire = threading.Event()

    def __enter__(self) -> None:
        if threading.current_thread().name == self._tracked_thread:
            self.tracked_acquire.set()
        self._lock.acquire()

    def __exit__(self, *_args: object) -> None:
        self._lock.release()


def _boundary_pty_handle(proc: Any, master_fd: int) -> PtyHandle:
    return PtyHandle(
        proc,
        master_fd=master_fd,
        rows=24,
        cols=80,
        stall_s=1.0,
        quiet_ms=10,
        max_settle_s=1.0,
    )


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


def _fake_tui_module() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location("taut_fake_tui", FAKE_TUI)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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


def _assert_termios_restored(fd: int, saved: list[Any]) -> None:
    """Compare host-controlled modes while ignoring the kernel PENDIN bit."""

    current = termios.tcgetattr(fd)
    assert current[:3] == saved[:3]
    assert current[3] & ~termios.PENDIN == saved[3] & ~termios.PENDIN
    assert current[4:] == saved[4:]


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
        assert adapter.emits_session_events is False
    with pytest.raises(UnknownAdapterError, match="known adapters"):
        get_adapter("code")


def test_fake_tui_preserves_input_that_arrives_before_query_reply() -> None:
    fake_tui = _fake_tui_module()

    prompt = b"orientation payload\r"
    assert (
        fake_tui._query_input_prefix(prompt + b"\x1b[24;80R", b"\x1b[24;80R") == prompt
    )
    assert (
        fake_tui._query_input_prefix(
            b"\x1b]10;rgb:ffff/ffff/ffff\x1b\\",
            b"\x1b]10;rgb:",
        )
        == b""
    )


def test_wait_until_quiet_waits_for_first_output() -> None:
    handle = object.__new__(PtyHandle)
    handle._reader_started_event = threading.Event()
    handle._reader_started_event.set()
    handle._seen_output = threading.Event()
    handle._last_output_ts = time.monotonic() - 10.0
    handle._quiet_s = 0.01
    handle._max_settle_s = 1.0
    returned = threading.Event()

    def wait_and_mark_returned() -> None:
        handle.wait_until_quiet()
        returned.set()

    thread = threading.Thread(target=wait_and_mark_returned, daemon=True)
    thread.start()
    time.sleep(0.1)
    assert not returned.is_set()

    handle._last_output_ts = time.monotonic() - 10.0
    handle._seen_output.set()
    thread.join(timeout=1.0)
    assert returned.is_set()


def test_master_is_published_nonblocking_once_without_losing_flags(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_openpty = pty.openpty
    real_fcntl = _pty_module.fcntl.fcntl
    set_calls: list[int] = []

    def openpty_with_unrelated_flag() -> tuple[int, int]:
        master_fd, slave_fd = real_openpty()
        flags = real_fcntl(master_fd, _pty_module.fcntl.F_GETFL)
        real_fcntl(
            master_fd,
            _pty_module.fcntl.F_SETFL,
            flags | os.O_APPEND,
        )
        return master_fd, slave_fd

    def recording_fcntl(fd: int, operation: int, argument: int = 0) -> int:
        if operation == _pty_module.fcntl.F_SETFL:
            set_calls.append(argument)
        return int(real_fcntl(fd, operation, argument))

    monkeypatch.setattr(pty, "openpty", openpty_with_unrelated_flag)
    monkeypatch.setattr(_pty_module.fcntl, "fcntl", recording_fcntl)
    handle, log = _spawn_fake(
        tmp_path, {"queries": False, "modes": False, "redraw": False}
    )
    pump = EventPump(handle)
    try:
        _wait_for(log, "start")
        handle.inject("hello")
    finally:
        handle.close()
        pump.drain_until_exit(timeout=5.0)

    assert len(set_calls) == 1
    assert set_calls[0] & os.O_NONBLOCK
    assert set_calls[0] & os.O_APPEND


def test_spawn_failure_closes_master_and_slave_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    close_calls: list[int] = []
    monkeypatch.setattr(pty, "openpty", lambda: (40, 41))
    monkeypatch.setattr(_pty_module, "_set_winsize", lambda *_args: None)
    monkeypatch.setattr(_pty_module, "_set_nonblocking", lambda _fd: None)
    monkeypatch.setattr(
        _pty_module.subprocess,
        "Popen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("spawn failed")),
    )
    monkeypatch.setattr(_pty_module.os, "close", close_calls.append)

    with pytest.raises(AdapterError, match="failed to spawn PTY harness"):
        PtyAdapter(PtySpec(name="broken", argv=("broken",))).spawn(
            session_id=None,
            system_prompt="ignored",
            env={},
        )

    assert close_calls == [40, 41]


@pytest.mark.parametrize(
    ("spec", "message"),
    (
        (PtySpec(name="bad", argv=()), "argv"),
        (PtySpec(name="bad", argv=("sh",), rows=0), "rows"),
        (PtySpec(name="bad", argv=("sh",), rows=65_536), "rows"),
        (PtySpec(name="bad", argv=("sh",), cols=0), "cols"),
        (PtySpec(name="bad", argv=("sh",), cols=65_536), "cols"),
        (PtySpec(name="bad", argv=("sh",), stall_s=0.0), "stall_s"),
        (PtySpec(name="bad", argv=("sh",), stall_s=float("nan")), "stall_s"),
        (PtySpec(name="bad", argv=("sh",), stall_s=10**400), "stall_s"),
        (PtySpec(name="bad", argv=("sh",), quiet_ms=-1), "quiet_ms"),
        (PtySpec(name="bad", argv=("sh",), quiet_ms=10**400), "quiet_ms"),
        (PtySpec(name="bad", argv=("sh",), max_settle_s=0.0), "max_settle_s"),
        (
            PtySpec(name="bad", argv=("sh",), max_settle_s=10**400),
            "max_settle_s",
        ),
        (
            PtySpec(name="bad", argv=("sh",), max_settle_s=float("inf")),
            "max_settle_s",
        ),
    ),
)
def test_pty_spec_rejects_unsafe_spawn_and_timing_values(
    spec: PtySpec, message: str
) -> None:
    with pytest.raises(AdapterError, match=message):
        PtyAdapter(spec)


def test_write_select_close_race_is_adapter_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    master_socket, peer_socket = socket.socketpair()
    master_fd = master_socket.detach()
    proc = _ScheduledPtyProcess()
    handle = _boundary_pty_handle(proc, master_fd)

    monkeypatch.setattr(
        _pty_module.os,
        "write",
        lambda _fd, _data: (_ for _ in ()).throw(BlockingIOError()),
    )
    monkeypatch.setattr(
        _pty_module.select,
        "select",
        lambda *_args: (_ for _ in ()).throw(ValueError("fd closed")),
    )

    try:
        with pytest.raises(AdapterError, match="PTY write wait failed"):
            handle.inject("race")
    finally:
        proc.returncode = 0
        handle.close()
        peer_socket.close()


def test_failed_best_effort_query_reply_does_not_kill_event_pump(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    handle, log = _spawn_fake(
        tmp_path, {"queries": True, "modes": False, "redraw": False}
    )
    real_write = os.write
    real_select = select.select
    reply_blocked = threading.Event()
    fail_reply_wait = True

    def controlled_write(fd: int, data: bytes) -> int:
        if data.startswith(b"\x1b"):
            reply_blocked.set()
            raise BlockingIOError()
        return real_write(fd, data)

    def controlled_select(
        readers: list[int], writers: list[int], errors: list[int], timeout: float
    ) -> tuple[list[int], list[int], list[int]]:
        nonlocal fail_reply_wait
        if writers and fail_reply_wait:
            fail_reply_wait = False
            raise OSError("master closed during reply wait")
        return real_select(readers, writers, errors, timeout)

    monkeypatch.setattr(_pty_module.os, "write", controlled_write)
    monkeypatch.setattr(_pty_module.select, "select", controlled_select)
    pump = EventPump(handle)
    assert reply_blocked.wait(timeout=2.0)
    try:
        _wait_for(log, "query")
    finally:
        handle.close()

    assert isinstance(pump.drain_until_exit(timeout=5.0), ExitEvent)


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


def test_query_reply_waits_for_partial_injection_writer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    handle, log = _spawn_fake(
        tmp_path,
        {"queries": True, "modes": False, "redraw": False},
    )
    real_write = os.write
    injection_started = threading.Event()
    release_injection = threading.Event()
    reply_reached_write = threading.Event()
    first_injection_write = True

    def controlled_write(fd: int, data: bytes) -> int:
        nonlocal first_injection_write
        if data.startswith(b"serialize-me"):
            if first_injection_write:
                first_injection_write = False
                written = real_write(fd, data[:1])
                injection_started.set()
                assert release_injection.wait(timeout=2.0)
                return written
        elif data.startswith(b"\x1b"):
            reply_reached_write.set()
        return real_write(fd, data)

    monkeypatch.setattr(_pty_module.os, "write", controlled_write)
    failures: list[BaseException] = []

    def inject() -> None:
        try:
            handle.inject("serialize-me")
        except BaseException as exc:  # noqa: BLE001 - asserted below
            failures.append(exc)

    injector = threading.Thread(target=inject)
    injector.start()
    assert injection_started.wait(timeout=1.0)
    pump = EventPump(handle)
    reply_interleaved = reply_reached_write.wait(timeout=0.2)
    release_injection.set()
    injector.join(timeout=2.0)
    try:
        _wait_for(log, "query")
    finally:
        handle.close()
        pump.drain_until_exit(timeout=5.0)

    assert not injector.is_alive()
    assert failures == []
    assert not reply_interleaved, "terminal reply interleaved with partial injection"


def test_pty_responder_handles_live_observed_parameterized_queries() -> None:
    responder = _TerminalResponder(rows=31, cols=97)

    replies = responder.feed(b"\x1b[>0q\x1b[>7u\x1b[>1u\x1b[0 q\x1b[1 q\x1b[?996n")

    assert replies == [
        b"\x1bP>|taut-summon(0)\x1b\\",
        b"\x1b[?997;1n",
    ]
    assert responder.outstanding_query is None


@pytest.mark.parametrize("introducer", (b"\x1b[", b"\x1b]"))
def test_pty_responder_bounds_oversized_incomplete_sequences_and_recovers(
    introducer: bytes,
) -> None:
    responder = _TerminalResponder(rows=31, cols=97)

    responder.feed(introducer + b"1" * (_TERMINAL_RESPONSE_BUFFER_LIMIT * 2))

    assert responder.buffered_bytes <= _TERMINAL_RESPONSE_BUFFER_LIMIT
    assert responder.feed(b"\x1b[6n") == [b"\x1b[1;1R"]


def test_pty_responder_incomplete_scan_work_is_linear_in_input_bytes() -> None:
    responder = _TerminalResponder(rows=31, cols=97)
    payload = b"\x1b]10;?" + b"x" * (_TERMINAL_RESPONSE_BUFFER_LIMIT * 2)

    for byte in payload:
        responder.feed(bytes((byte,)))

    assert responder.buffered_bytes <= _TERMINAL_RESPONSE_BUFFER_LIMIT
    assert responder.scan_steps <= len(payload) * 4


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


def test_close_does_not_block_behind_full_pty_input_queue(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
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
    _wait_for(log, "unknown_reply_window")
    injected: list[BaseException] = []
    input_queue_full = threading.Event()
    real_write = os.write

    def observed_write(fd: int, data: bytes) -> int:
        try:
            return real_write(fd, data)
        except BlockingIOError:
            if threading.current_thread().name == "large-injector":
                input_queue_full.set()
            raise

    monkeypatch.setattr(_pty_module.os, "write", observed_write)

    def _inject_large() -> None:
        try:
            handle.inject("x" * 5_000_000)
        except BaseException as exc:  # noqa: BLE001 - asserted after close
            injected.append(exc)

    injector = threading.Thread(
        target=_inject_large, daemon=True, name="large-injector"
    )
    injector.start()
    assert input_queue_full.wait(timeout=5.0)
    assert injector.is_alive()

    closer = threading.Thread(target=handle.close, daemon=True)
    closer.start()
    closer.join(timeout=3.0)
    assert not closer.is_alive()
    pump.drain_until_exit(timeout=5.0)
    injector.join(timeout=5.0)
    assert not injector.is_alive()


def test_close_rereads_reader_ownership_after_reap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    master_fd, writer_fd = os.pipe()
    proc = _ScheduledPtyProcess()
    handle = _boundary_pty_handle(proc, master_fd)
    real_close = os.close
    close_threads: list[threading.Thread] = []

    def recording_close(fd: int) -> None:
        if fd == master_fd:
            close_threads.append(threading.current_thread())
        real_close(fd)

    monkeypatch.setattr(_pty_module.os, "close", recording_close)
    failures: list[BaseException] = []

    def close() -> None:
        try:
            handle.close()
        except BaseException as exc:  # noqa: BLE001 - asserted below
            failures.append(exc)

    closer = threading.Thread(target=close, name="scheduled-closer")
    closer.start()
    assert proc.wait_entered.wait(timeout=1.0)
    pump = EventPump(handle)
    assert handle._reader_started_event.wait(timeout=1.0)
    proc.release_wait.set()
    closer.join(timeout=2.0)
    exit_event = pump.drain_until_exit(timeout=2.0)
    real_close(writer_fd)

    assert not closer.is_alive()
    assert failures == []
    assert isinstance(exit_event, ExitEvent)
    assert len(close_threads) == 1
    assert close_threads[0] is not closer


def test_concurrent_close_has_one_reap_and_fd_owner() -> None:
    master_fd, writer_fd = os.pipe()
    proc = _ScheduledPtyProcess()
    handle = _boundary_pty_handle(proc, master_fd)
    failures: list[BaseException] = []

    def close() -> None:
        try:
            handle.close()
        except BaseException as exc:  # noqa: BLE001 - asserted below
            failures.append(exc)

    first = threading.Thread(target=close)
    second = threading.Thread(target=close)
    first.start()
    assert proc.wait_entered.wait(timeout=1.0)
    second.start()
    time.sleep(0.1)
    proc.release_wait.set()
    first.join(timeout=2.0)
    second.join(timeout=2.0)
    os.close(writer_fd)

    assert not first.is_alive()
    assert not second.is_alive()
    assert failures == []
    assert proc.wait_calls == 1
    assert handle._master_closed is True


def test_inject_refuses_after_pty_close_publishes_closing() -> None:
    master_socket, child_socket = socket.socketpair()
    proc = _ScheduledPtyProcess()
    handle = _boundary_pty_handle(proc, master_socket.detach())
    closer = threading.Thread(target=handle.close)
    closer.start()
    assert proc.wait_entered.wait(timeout=1.0)

    try:
        with pytest.raises(AdapterError, match="closed"):
            handle.inject("must not be delivered")
        child_socket.settimeout(1.0)
        assert child_socket.recv(4096) == b"\x03"
    finally:
        proc.release_wait.set()
        closer.join(timeout=2.0)
        child_socket.close()


def test_queued_pty_inject_rechecks_retirement_under_serialization() -> None:
    master_socket, child_socket = socket.socketpair()
    proc = _ScheduledPtyProcess()
    handle = _boundary_pty_handle(proc, master_socket.detach())
    failures: list[BaseException] = []
    gate = _BlockingWriterLock()
    handle._normal_writer_lock = cast(Any, gate)  # noqa: SLF001

    def inject() -> None:
        try:
            handle.inject("queued before close")
        except BaseException as exc:  # noqa: BLE001 - asserted below
            failures.append(exc)

    injector = threading.Thread(target=inject)
    injector.start()
    assert gate.entered.wait(timeout=1.0)
    closer = threading.Thread(target=handle.close)
    closer.start()
    assert proc.wait_entered.wait(timeout=1.0)
    gate.release.set()
    injector.join(timeout=2.0)
    proc.release_wait.set()
    closer.join(timeout=2.0)
    child_socket.settimeout(1.0)
    delivered = child_socket.recv(4096)
    child_socket.close()

    assert not injector.is_alive()
    assert not closer.is_alive()
    assert len(failures) == 1
    assert isinstance(failures[0], AdapterError)
    assert delivered == b"\x03"


def test_interrupt_write_is_atomic_with_close_and_retirement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    master_socket, child_socket = socket.socketpair()
    master_fd = master_socket.detach()
    proc = _ScheduledPtyProcess()
    proc.returncode = 0
    handle = _boundary_pty_handle(proc, master_fd)
    real_write = os.write
    interrupt_at_write = threading.Event()
    release_interrupt = threading.Event()
    close_waiting_for_operations = threading.Event()
    real_wait_for_operations = handle._wait_for_active_operations

    def observed_wait_for_operations() -> None:
        close_waiting_for_operations.set()
        real_wait_for_operations()

    def controlled_write(fd: int, data: bytes) -> int:
        if data == b"\x03" and threading.current_thread().name == "interruptor":
            interrupt_at_write.set()
            assert release_interrupt.wait(timeout=2.0)
        return real_write(fd, data)

    monkeypatch.setattr(_pty_module.os, "write", controlled_write)
    monkeypatch.setattr(
        handle, "_wait_for_active_operations", observed_wait_for_operations
    )
    interruptor = threading.Thread(target=handle.interrupt, name="interruptor")
    closer = threading.Thread(target=handle.close, name="closer")
    interruptor.start()
    assert interrupt_at_write.wait(timeout=1.0)
    closer.start()
    assert close_waiting_for_operations.wait(timeout=1.0)
    close_waited_for_interrupt = closer.is_alive()
    release_interrupt.set()
    interruptor.join(timeout=2.0)
    closer.join(timeout=2.0)
    child_socket.close()

    reuse_sender, reuse_peer = socket.socketpair()
    reuse_sender_fd = reuse_sender.detach()
    if reuse_sender_fd != master_fd:
        os.dup2(reuse_sender_fd, master_fd)
        os.close(reuse_sender_fd)
    reuse_peer.settimeout(0.1)
    handle.interrupt()
    with pytest.raises(TimeoutError):
        reuse_peer.recv(1)
    os.close(master_fd)
    reuse_peer.close()

    assert close_waited_for_interrupt
    assert not interruptor.is_alive()
    assert not closer.is_alive()


def test_interrupt_dup_failure_keeps_close_from_reaping_before_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    master_socket, peer_socket = socket.socketpair()
    master_fd = master_socket.detach()
    proc = _ScheduledPtyProcess()
    handle = _boundary_pty_handle(proc, master_fd)
    real_dup = os.dup
    fallback_started = threading.Event()
    release_fallback = threading.Event()
    close_waiting_for_operations = threading.Event()
    real_wait_for_operations = handle._wait_for_active_operations

    def controlled_dup(fd: int) -> int:
        if threading.current_thread().name == "interruptor":
            raise OSError(errno.EMFILE, "sentinel interrupt dup exhaustion")
        return real_dup(fd)

    def controlled_fallback(_sig: signal.Signals) -> None:
        fallback_started.set()
        assert release_fallback.wait(timeout=2.0)

    def observed_wait_for_operations() -> None:
        close_waiting_for_operations.set()
        real_wait_for_operations()

    monkeypatch.setattr(_pty_module.os, "dup", controlled_dup)
    monkeypatch.setattr(handle, "_signal_process_group", controlled_fallback)
    monkeypatch.setattr(
        handle, "_wait_for_active_operations", observed_wait_for_operations
    )
    interruptor = threading.Thread(target=handle.interrupt, name="interruptor")
    closer = threading.Thread(target=handle.close, name="closer")
    interruptor.start()
    assert fallback_started.wait(timeout=1.0)
    closer.start()
    assert close_waiting_for_operations.wait(timeout=1.0)

    assert closer.is_alive()
    assert not proc.wait_entered.is_set()

    release_fallback.set()
    interruptor.join(timeout=2.0)
    assert proc.wait_entered.wait(timeout=1.0)
    proc.release_wait.set()
    closer.join(timeout=2.0)
    peer_socket.close()

    assert not interruptor.is_alive()
    assert not closer.is_alive()


def test_interrupt_lease_survives_canonical_fd_close_and_numeric_reuse(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    master_socket, original_peer = socket.socketpair()
    master_fd = master_socket.detach()
    proc = _ScheduledPtyProcess()
    handle = _boundary_pty_handle(proc, master_fd)
    real_write = os.write
    interrupt_at_write = threading.Event()
    release_interrupt = threading.Event()

    def controlled_write(fd: int, data: bytes) -> int:
        if data == b"\x03" and threading.current_thread().name == "interruptor":
            interrupt_at_write.set()
            assert release_interrupt.wait(timeout=2.0)
        return real_write(fd, data)

    monkeypatch.setattr(_pty_module.os, "write", controlled_write)
    interruptor = threading.Thread(target=handle.interrupt, name="interruptor")
    interruptor.start()
    assert interrupt_at_write.wait(timeout=1.0)

    with handle._lifecycle_lock:
        handle._close_master_unlocked()
    reuse_sender, reuse_peer = socket.socketpair()
    reuse_sender_fd = reuse_sender.detach()
    if reuse_sender_fd != master_fd:
        os.dup2(reuse_sender_fd, master_fd)
        os.close(reuse_sender_fd)

    release_interrupt.set()
    interruptor.join(timeout=2.0)
    original_peer.settimeout(1.0)
    reuse_peer.settimeout(0.1)

    assert original_peer.recv(1) == b"\x03"
    with pytest.raises(TimeoutError):
        reuse_peer.recv(1)

    proc.returncode = 0
    handle.close()
    os.close(master_fd)
    original_peer.close()
    reuse_peer.close()

    assert not interruptor.is_alive()


def test_interrupt_is_safe_when_signal_reenters_fd_lease_registration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    master_socket, child_socket = socket.socketpair()
    master_fd = master_socket.detach()
    proc = _ScheduledPtyProcess()
    handle = _boundary_pty_handle(proc, master_fd)
    real_dup = os.dup
    raised = False

    def controlled_dup(fd: int) -> int:
        nonlocal raised
        if fd == master_fd and not raised:
            raised = True
            signal.raise_signal(signal.SIGUSR1)
        return real_dup(fd)

    monkeypatch.setattr(_pty_module.os, "dup", controlled_dup)
    prior_handler = signal.signal(
        signal.SIGUSR1, lambda _signum, _frame: handle.interrupt()
    )
    try:
        with pytest.raises(AdapterError, match="interrupted"):
            handle.inject("old-epoch")
    finally:
        signal.signal(signal.SIGUSR1, prior_handler)

    child_socket.settimeout(1.0)
    received = child_socket.recv(4096)
    proc.returncode = 0
    handle.close()
    child_socket.close()

    assert received == b"\x03"


@pytest.mark.parametrize("failure_point", ["write", "select", "zero"])
def test_interrupt_wins_over_inflight_pty_io_error(
    monkeypatch: pytest.MonkeyPatch,
    failure_point: str,
) -> None:
    master_socket, child_socket = socket.socketpair()
    proc = _ScheduledPtyProcess()
    handle = _boundary_pty_handle(proc, master_socket.detach())
    real_write = os.write
    io_entered = threading.Event()
    release_io = threading.Event()
    failures: list[BaseException] = []

    def controlled_write(fd: int, data: bytes) -> int:
        if threading.current_thread().name == "injector" and data.startswith(
            b"old-epoch"
        ):
            if failure_point == "write":
                io_entered.set()
                assert release_io.wait(timeout=2.0)
                raise OSError(errno.EBADF, "sentinel write race")
            if failure_point == "zero":
                io_entered.set()
                assert release_io.wait(timeout=2.0)
                return 0
            raise BlockingIOError()
        return real_write(fd, data)

    def controlled_select(
        readers: list[int], writers: list[int], errors: list[int], timeout: float
    ) -> tuple[list[int], list[int], list[int]]:
        del readers, writers, errors, timeout
        assert failure_point == "select"
        io_entered.set()
        assert release_io.wait(timeout=2.0)
        raise OSError(errno.EBADF, "sentinel select race")

    monkeypatch.setattr(_pty_module.os, "write", controlled_write)
    if failure_point == "select":
        monkeypatch.setattr(_pty_module.select, "select", controlled_select)

    def inject() -> None:
        try:
            handle.inject("old-epoch")
        except BaseException as exc:  # noqa: BLE001 - asserted below
            failures.append(exc)

    injector = threading.Thread(target=inject, name="injector")
    injector.start()
    assert io_entered.wait(timeout=1.0)
    handle.interrupt()
    release_io.set()
    injector.join(timeout=2.0)
    proc.returncode = 0
    handle.close()
    child_socket.close()

    assert not injector.is_alive()
    assert len(failures) == 1
    assert isinstance(failures[0], AdapterError)
    assert str(failures[0]) == "PTY write interrupted"


def test_interrupt_cancellation_outranks_concurrent_reader_close(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    master_socket, child_socket = socket.socketpair()
    proc = _ScheduledPtyProcess()
    handle = _boundary_pty_handle(proc, master_socket.detach())
    real_write = os.write
    write_entered = threading.Event()
    release_write = threading.Event()
    failures: list[BaseException] = []

    def controlled_write(fd: int, data: bytes) -> int:
        if threading.current_thread().name == "injector" and data.startswith(
            b"old-epoch"
        ):
            write_entered.set()
            assert release_write.wait(timeout=2.0)
            raise BlockingIOError()
        return real_write(fd, data)

    monkeypatch.setattr(_pty_module.os, "write", controlled_write)

    def inject() -> None:
        try:
            handle.inject("old-epoch")
        except BaseException as exc:  # noqa: BLE001 - asserted below
            failures.append(exc)

    injector = threading.Thread(target=inject, name="injector")
    injector.start()
    assert write_entered.wait(timeout=1.0)
    handle.interrupt()
    with handle._lifecycle_lock:  # noqa: SLF001 - deterministic reader-close race
        handle._close_master_unlocked()  # noqa: SLF001
    release_write.set()
    injector.join(timeout=2.0)
    proc.returncode = 0
    handle.close()
    child_socket.close()

    assert not injector.is_alive()
    assert len(failures) == 1
    assert isinstance(failures[0], AdapterError)
    assert str(failures[0]) == "PTY write interrupted"


def test_interrupt_at_write_lease_retirement_cancels_completed_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    master_socket, child_socket = socket.socketpair()
    proc = _ScheduledPtyProcess()
    handle = _boundary_pty_handle(proc, master_socket.detach())
    real_close_operation_fd = handle._close_operation_fd  # noqa: SLF001
    interrupt_published = False

    def interrupt_before_close(fd: int) -> None:
        nonlocal interrupt_published
        if not interrupt_published:
            interrupt_published = True
            handle.interrupt()
        real_close_operation_fd(fd)

    monkeypatch.setattr(handle, "_close_operation_fd", interrupt_before_close)

    try:
        with pytest.raises(AdapterError, match="PTY write interrupted"):
            handle.inject("old-epoch")
        child_socket.settimeout(1.0)
        assert child_socket.recv(4096) == b"old-epoch\r\x03"
    finally:
        proc.returncode = 0
        handle.close()
        child_socket.close()

    assert interrupt_published


def test_final_reap_failure_retires_master_and_is_terminal() -> None:
    master_socket, peer_socket = socket.socketpair()
    master_fd = master_socket.detach()
    proc = _NeverReapsPtyProcess()
    handle = _boundary_pty_handle(proc, master_fd)

    with pytest.raises(AdapterError, match="did not exit after SIGKILL"):
        handle.close()
    with pytest.raises(AdapterError, match="did not exit after SIGKILL"):
        handle.close()

    assert proc.wait_calls == 3
    assert handle._master_closed is True
    with pytest.raises(OSError):
        os.fstat(master_fd)
    peer_socket.close()


def test_final_reap_failure_unblocks_reader_without_second_reap() -> None:
    master_socket, peer_socket = socket.socketpair()
    proc = _NeverReapsPtyProcess()
    handle = _boundary_pty_handle(proc, master_socket.detach())
    pump = EventPump(handle)
    assert handle._reader_started_event.wait(timeout=1.0)

    with pytest.raises(AdapterError, match="did not exit after SIGKILL"):
        handle.close()
    with pytest.raises(AdapterError, match="did not exit after SIGKILL"):
        pump.drain_until_exit(timeout=2.0)

    assert proc.wait_calls == 3
    assert handle._master_closed is True
    peer_socket.close()


def test_final_reap_failure_does_not_mask_active_primary_error() -> None:
    master_socket, peer_socket = socket.socketpair()
    proc = _NeverReapsPtyProcess()
    handle = _boundary_pty_handle(proc, master_socket.detach())
    primary = RuntimeError("primary PTY failure")

    try:
        raise primary
    except RuntimeError:
        handle.close()

    assert primary.__notes__ == [
        "adapter cleanup also failed: PTY child did not exit after SIGKILL"
    ]
    assert proc.wait_calls == 3
    assert handle._master_closed is True
    peer_socket.close()


def test_fd_cleanup_error_does_not_replace_reap_or_active_primary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    master_socket, peer_socket = socket.socketpair()
    master_fd = master_socket.detach()
    proc = _NeverReapsPtyProcess()
    handle = _boundary_pty_handle(proc, master_fd)
    real_close = os.close
    primary = RuntimeError("primary PTY failure")

    def failing_close(fd: int) -> None:
        if fd == master_fd:
            raise OSError("sentinel fd cleanup failure")
        real_close(fd)

    monkeypatch.setattr(_pty_module.os, "close", failing_close)
    try:
        try:
            raise primary
        except RuntimeError:
            handle.close()
    finally:
        real_close(master_fd)
        peer_socket.close()

    assert primary.__notes__ == [
        "adapter cleanup also failed: PTY child did not exit after SIGKILL"
    ]
    assert handle._close_error == "PTY child did not exit after SIGKILL"


def test_close_dup_failure_still_retires_reaps_and_closes_master(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    master_socket, peer_socket = socket.socketpair()
    master_fd = master_socket.detach()
    proc = _NeverReapsPtyProcess()
    handle = _boundary_pty_handle(proc, master_fd)
    real_dup = os.dup
    dup_attempted = threading.Event()

    def failing_dup(fd: int) -> int:
        if fd == master_fd:
            dup_attempted.set()
            raise OSError(errno.EMFILE, "sentinel dup exhaustion")
        return real_dup(fd)

    monkeypatch.setattr(_pty_module.os, "dup", failing_dup)

    with pytest.raises(AdapterError, match="did not exit after SIGKILL"):
        handle.close()

    assert dup_attempted.is_set()
    assert proc.wait_calls == 3
    assert handle._master_closed is True
    with pytest.raises(OSError):
        os.fstat(master_fd)
    peer_socket.close()


def test_interrupt_unblocks_full_pty_input_queue(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
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
    _wait_for(log, "unknown_reply_window")

    injected: list[BaseException] = []
    input_queue_full = threading.Event()
    real_write = os.write

    def observed_write(fd: int, data: bytes) -> int:
        try:
            return real_write(fd, data)
        except BlockingIOError:
            if threading.current_thread().name == "large-injector":
                input_queue_full.set()
            raise

    monkeypatch.setattr(_pty_module.os, "write", observed_write)

    def _inject_large() -> None:
        try:
            handle.inject("x" * 5_000_000)
        except BaseException as exc:  # noqa: BLE001 - expected after interrupt
            injected.append(exc)

    injector = threading.Thread(
        target=_inject_large, daemon=True, name="large-injector"
    )
    injector.start()
    assert input_queue_full.wait(timeout=5.0)
    assert injector.is_alive()

    handle.interrupt()
    injector.join(timeout=3.0)
    assert not injector.is_alive()
    assert len(injected) == 1
    assert isinstance(injected[0], AdapterError)
    assert str(injected[0]) == "PTY write interrupted"
    handle.close()
    pump.drain_until_exit(timeout=5.0)


def test_interrupt_cancels_active_and_queued_writes_then_rearms(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    handle, log = _spawn_fake(
        tmp_path, {"queries": False, "modes": False, "redraw": False}
    )
    pump = EventPump(handle)
    _wait_for(log, "start")
    real_write = os.write
    active_write_started = threading.Event()
    release_active_write = threading.Event()
    writer_lock = _TrackingWriterLock(tracked_thread="queued-injector")
    handle._normal_writer_lock = cast(Any, writer_lock)  # noqa: SLF001
    first_active_write = True
    old_queued_write = threading.Event()

    def controlled_write(fd: int, data: bytes) -> int:
        nonlocal first_active_write
        if data.startswith(b"old-active") and first_active_write:
            first_active_write = False
            written = real_write(fd, data[:1])
            active_write_started.set()
            assert release_active_write.wait(timeout=2.0)
            return written
        if data.startswith(b"old-queued"):
            old_queued_write.set()
        return real_write(fd, data)

    monkeypatch.setattr(_pty_module.os, "write", controlled_write)
    failures: list[BaseException] = []

    def inject(text: str) -> None:
        try:
            handle.inject(text)
        except BaseException as exc:  # noqa: BLE001 - asserted below
            failures.append(exc)

    active = threading.Thread(
        target=inject, args=("old-active",), name="active-injector"
    )
    queued = threading.Thread(
        target=inject, args=("old-queued",), name="queued-injector"
    )
    active.start()
    assert active_write_started.wait(timeout=1.0)
    queued.start()
    assert writer_lock.tracked_acquire.wait(timeout=1.0)
    assert queued.is_alive()

    interruptor = threading.Thread(target=handle.interrupt)
    interruptor.start()
    interruptor.join(timeout=1.0)
    interrupt_completed_before_active_write = not interruptor.is_alive()
    release_active_write.set()
    interruptor.join(timeout=2.0)
    active.join(timeout=2.0)
    queued.join(timeout=2.0)
    _wait_for(log, "interrupt")
    try:
        handle.inject("after-interrupt")
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            inputs = [entry for entry in _entries(log) if entry["event"] == "input"]
            if any(entry["raw"] == "after-interrupt\r" for entry in inputs):
                break
            time.sleep(0.05)
        else:
            raise AssertionError(f"new-epoch injection not observed: {_entries(log)!r}")
    finally:
        handle.close()
        pump.drain_until_exit(timeout=5.0)

    assert not active.is_alive()
    assert not queued.is_alive()
    assert not interruptor.is_alive()
    assert interrupt_completed_before_active_write
    assert len(failures) == 2
    assert all(isinstance(exc, AdapterError) for exc in failures)
    assert {str(exc) for exc in failures} == {"PTY write interrupted"}
    assert not old_queued_write.is_set()


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
    saved_termios = termios.tcgetattr(user_slave)
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
        _assert_termios_restored(user_slave, saved_termios)
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


def test_attach_forwarding_serializes_with_injection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    handle, _log = _spawn_fake(
        tmp_path, {"queries": False, "modes": False, "redraw": False}
    )
    user_master, user_slave = pty.openpty()
    wake = threading.Event()
    shutdown = threading.Event()
    attach_result: list[str] = []
    attach = threading.Thread(
        target=lambda: attach_result.append(
            handle.attach(
                wake=wake,
                shutdown=shutdown,
                input_fd=user_slave,
                output_fd=user_slave,
            )
        ),
        daemon=True,
        name="attach-bridge",
    )
    attach.start()
    assert b"ready" in _read_fd_until(user_master, b"ready")

    real_write = os.write
    forwarding_started = threading.Event()
    release_forwarding = threading.Event()
    injection_reached_write = threading.Event()
    first_forwarding_write = True

    def controlled_write(fd: int, data: bytes) -> int:
        nonlocal first_forwarding_write
        if threading.current_thread().name == "attach-bridge" and data.startswith(
            b"human"
        ):
            if first_forwarding_write:
                first_forwarding_write = False
                written = real_write(fd, data[:1])
                forwarding_started.set()
                assert release_forwarding.wait(timeout=2.0)
                return written
        elif data.startswith(b"agent"):
            injection_reached_write.set()
        return real_write(fd, data)

    monkeypatch.setattr(_pty_module.os, "write", controlled_write)
    failures: list[BaseException] = []

    def inject() -> None:
        try:
            handle.inject("agent")
        except BaseException as exc:  # noqa: BLE001 - asserted below
            failures.append(exc)

    injector = threading.Thread(target=inject)
    try:
        os.write(user_master, b"human\r")
        assert forwarding_started.wait(timeout=1.0)
        injector.start()
        injection_interleaved = injection_reached_write.wait(timeout=0.2)
        release_forwarding.set()
        injector.join(timeout=2.0)
        os.write(user_master, b"\x1c\x1c")
        reset = _read_fd_until(user_master, b"\x1b[?2004l", timeout=2.0)
        attach.join(timeout=2.0)
    finally:
        release_forwarding.set()
        handle.close()
        os.close(user_master)
        os.close(user_slave)

    assert not injector.is_alive()
    assert not attach.is_alive()
    assert attach_result == ["detached"]
    assert b"\x1b[?2004l" in reset
    assert failures == []
    assert not injection_interleaved


def test_attach_shutdown_wake_exits_bridge(
    tmp_path: Path,
) -> None:
    handle, _log = _spawn_fake(
        tmp_path, {"queries": False, "modes": False, "redraw": False}
    )
    user_master, user_slave = pty.openpty()
    saved_termios = termios.tcgetattr(user_slave)
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
        _assert_termios_restored(user_slave, saved_termios)
    finally:
        handle.close()
        os.close(user_master)
        os.close(user_slave)


def test_attach_output_failure_still_restores_input_termios(tmp_path: Path) -> None:
    handle, _log = _spawn_fake(
        tmp_path, {"queries": False, "modes": False, "redraw": False}
    )
    user_master, user_slave = pty.openpty()
    saved_termios = termios.tcgetattr(user_slave)
    output_r, output_w = os.pipe()
    os.close(output_w)
    failures: list[BaseException] = []

    def attach() -> None:
        try:
            handle.attach(
                wake=threading.Event(),
                shutdown=threading.Event(),
                input_fd=user_slave,
                output_fd=output_w,
            )
        except BaseException as exc:  # noqa: BLE001 - asserted below
            failures.append(exc)

    thread = threading.Thread(target=attach, daemon=True)
    thread.start()
    try:
        thread.join(timeout=5.0)
        assert not thread.is_alive()
        assert len(failures) == 1
        assert isinstance(failures[0], OSError)
        _assert_termios_restored(user_slave, saved_termios)
    finally:
        handle.close()
        os.close(output_r)
        os.close(user_master)
        os.close(user_slave)
