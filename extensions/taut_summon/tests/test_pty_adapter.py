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
from typing import TYPE_CHECKING, Any, Self, cast

import psutil
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
from taut_summon._process_domain import ProcessIO

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
    def __init__(
        self, handle: AdapterHandle, *, thread_name: str | None = None
    ) -> None:
        self._items: queue.Queue[AdapterEvent | Exception] = queue.Queue()
        self._thread = threading.Thread(
            target=self._run,
            args=(handle,),
            daemon=True,
            name=thread_name,
        )
        self._thread.start()

    def _run(self, handle: AdapterHandle) -> None:
        try:
            for event in handle.events():
                self._items.put(event)
        except Exception as exc:  # noqa: BLE001 approved [DOM-10.2.1] [RUFF-SUP-071] exception
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


class _FakePtyDomain:
    """Lifecycle owner for Popen-shaped boundary fakes only."""

    def __init__(self, proc: _ScheduledPtyProcess) -> None:
        self._proc = proc
        self._lock = threading.RLock()

    def observe_leader_exit(self) -> int | None:
        return self._proc.poll()

    def wait_for_leader_exit(self, timeout: float) -> int | None:
        status = self.observe_leader_exit()
        if status is not None:
            return status
        try:
            return self._proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            return None

    def signal_leader(self, sig: signal.Signals) -> None:
        self._proc.send_signal(sig)

    def signal_group(self, sig: signal.Signals) -> None:
        self._proc.send_signal(sig)

    def finalize(self) -> int:
        with self._lock:
            status = self.observe_leader_exit()
            if status is not None:
                return status
            last_timeout: subprocess.TimeoutExpired | None = None
            for sig, timeout in (
                (None, 0.3),
                (signal.SIGTERM, 2.0),
                (signal.SIGKILL, 2.0),
            ):
                if sig is not None:
                    self.signal_group(sig)
                try:
                    return self._proc.wait(timeout=timeout)
                except subprocess.TimeoutExpired as exc:
                    last_timeout = exc
            raise AdapterError("PTY child did not exit after SIGKILL") from last_timeout


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


class _TrackingCondition:
    """Expose when one named non-owner waits for lifecycle completion."""

    def __init__(self, lock: threading.RLock, *, tracked_thread: str) -> None:
        self._condition = threading.Condition(lock)
        self._tracked_thread = tracked_thread
        self.wait_entered = threading.Event()

    def __enter__(self) -> Self:
        self._condition.__enter__()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: types.TracebackType | None,
    ) -> None:
        self._condition.__exit__(exc_type, exc_value, traceback)

    def wait_for(self, predicate: Any, timeout: float | None = None) -> bool:
        if threading.current_thread().name == self._tracked_thread:
            self.wait_entered.set()
        return bool(self._condition.wait_for(predicate, timeout))

    def notify_all(self) -> None:
        self._condition.notify_all()


def _boundary_pty_handle(proc: Any, master_fd: int) -> PtyHandle:
    return PtyHandle(
        ProcessIO(pid=proc.pid, stdin=None, stdout=None),
        domain=_FakePtyDomain(proc),
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
    env: dict[str, str] | None = None,
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
            **(env or {}),
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


def _capture_process_identity(pid_file: Path) -> tuple[int, float]:
    deadline = time.monotonic() + 5.0
    while True:
        assert time.monotonic() < deadline, "descendant did not publish its PID"
        try:
            payload = json.loads(pid_file.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            time.sleep(0.01)
            continue
        pid = int(payload["pid"])
        return pid, psutil.Process(pid).create_time()


def _same_process(identity: tuple[int, float]) -> bool:
    pid, created_at = identity
    try:
        return psutil.Process(pid).create_time() == created_at
    except psutil.NoSuchProcess:
        return False


def _cleanup_exact_process(identity: tuple[int, float]) -> None:
    if not _same_process(identity):
        return
    pid, created_at = identity
    process = psutil.Process(pid)
    if process.create_time() != created_at:
        return
    process.kill()
    process.wait(timeout=5.0)


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


def test_spawn_replaces_inherited_host_identity_in_real_pty_child(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TAUT_AS", "HostPersona")
    monkeypatch.setenv("TAUT_TOKEN", "host-token")
    handle, log = _spawn_fake(
        tmp_path,
        {"queries": False, "modes": False, "redraw": False},
        env={"TAUT_TOKEN": "summoned-token"},
    )
    pump = EventPump(handle)
    try:
        start = _wait_for(log, "start")
    finally:
        handle.close()
        pump.drain_until_exit(timeout=5.0)

    assert start["env_as"] is None
    assert start["env_token"] == "summoned-token"
    assert os.environ["TAUT_AS"] == "HostPersona"
    assert os.environ["TAUT_TOKEN"] == "host-token"


def test_pty_close_retires_descendant_after_leader_exits_first(
    tmp_path: Path,
) -> None:
    """[SUM-7.4]/[SUM-12] PTY EOF cannot bypass domain retirement."""

    pid_file = tmp_path / "pty-descendant.json"
    scenario_path = tmp_path / "pty-domain-scenario.json"
    scenario_path.write_text(
        json.dumps(
            {
                "on_start": [
                    {
                        "spawn_descendant": {
                            "pid_file": str(pid_file),
                            "leader_exit_code": 0,
                        }
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    handle = PtyAdapter(
        PtySpec(
            name="scripted-domain",
            argv=(sys.executable, "-m", "taut_summon.scripted_provider"),
        )
    ).spawn(
        session_id=None,
        system_prompt="ignored for PTY",
        env={"TAUT_SUMMON_SCENARIO": str(scenario_path)},
    )
    identity: tuple[int, float] | None = None
    try:
        pump = EventPump(handle)
        identity = _capture_process_identity(pid_file)
        assert pump.drain_until_exit(timeout=5.0).returncode == 0

        handle.close()

        deadline = time.monotonic() + 5.0
        while _same_process(identity) and time.monotonic() < deadline:
            time.sleep(0.05)
        assert not _same_process(identity)
    finally:
        handle.close()
        if identity is not None:
            _cleanup_exact_process(identity)


def test_pty_observes_leader_exit_while_descendant_continuously_writes(
    tmp_path: Path,
) -> None:
    """[SUM-7.1]/[SUM-7.4] Busy PTY output cannot starve leader exit."""

    pid_file = tmp_path / "pty-busy-descendant.json"
    scenario_path = tmp_path / "pty-busy-domain-scenario.json"
    scenario_path.write_text(
        json.dumps(
            {
                "on_start": [
                    {
                        "spawn_descendant": {
                            "pid_file": str(pid_file),
                            "inherit_stdout": True,
                            "stdout_payload": "x" * 2_000,
                            "stdout_repeat": True,
                            "leader_exit_code": 0,
                        }
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    handle = PtyAdapter(
        PtySpec(
            name="scripted-busy-domain",
            argv=(sys.executable, "-m", "taut_summon.scripted_provider"),
        )
    ).spawn(
        session_id=None,
        system_prompt="ignored for PTY",
        env={"TAUT_SUMMON_SCENARIO": str(scenario_path)},
    )
    identity: tuple[int, float] | None = None
    try:
        pump = EventPump(handle)
        identity = _capture_process_identity(pid_file)

        assert pump.drain_until_exit(timeout=2.0).returncode == 0
        assert _same_process(identity)

        handle.close()

        deadline = time.monotonic() + 5.0
        while _same_process(identity) and time.monotonic() < deadline:
            time.sleep(0.05)
        assert not _same_process(identity)
    finally:
        handle.close()
        if identity is not None:
            _cleanup_exact_process(identity)


def test_pty_observes_terminal_leader_after_each_readable_output_turn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """[SUM-7.1] Readable PTY data cannot defer terminal observation."""

    master_fd, writer_fd = os.pipe()
    proc = _ScheduledPtyProcess()
    proc.returncode = 0
    handle = _boundary_pty_handle(proc, master_fd)
    read_calls = 0

    def always_readable(
        readers: list[int], _writers: list[int], _errors: list[int], _timeout: float
    ) -> tuple[list[int], list[int], list[int]]:
        return readers, [], []

    def read_once(fd: int, _size: int) -> bytes:
        nonlocal read_calls
        assert fd == master_fd
        read_calls += 1
        assert read_calls == 1, "leader status was not checked after readable output"
        return b"busy output"

    monkeypatch.setattr(_pty_module.select, "select", always_readable)
    monkeypatch.setattr(_pty_module.os, "read", read_once)
    try:
        events = list(handle.events())
    finally:
        os.close(writer_fd)

    assert read_calls == 1
    assert events[-1] == ExitEvent(returncode=0)


@pytest.mark.parametrize(
    ("ignore_sigterm", "expected_returncode"),
    [(False, -signal.SIGTERM), (True, -signal.SIGKILL)],
    ids=["term", "kill"],
)
def test_pty_close_retires_domain_through_forced_signal_stages(
    tmp_path: Path,
    ignore_sigterm: bool,
    expected_returncode: int,
) -> None:
    """[SUM-7.1]/[SUM-12] PTY finalization owns the real group ladder."""

    pid_file = tmp_path / f"pty-forced-{ignore_sigterm}.json"
    scenario_path = tmp_path / f"pty-forced-{ignore_sigterm}.jsonl"
    scenario_path.write_text(
        json.dumps(
            {
                "on_start": [
                    {
                        "spawn_descendant": {
                            "pid_file": str(pid_file),
                            "ignore_sigint": True,
                            "ignore_sigterm": ignore_sigterm,
                            "leader_ignore_sigint": True,
                            "leader_ignore_sigterm": ignore_sigterm,
                        }
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    handle = PtyAdapter(
        PtySpec(
            name="scripted-domain",
            argv=(sys.executable, "-m", "taut_summon.scripted_provider"),
        )
    ).spawn(
        session_id=None,
        system_prompt="ignored for PTY",
        env={"TAUT_SUMMON_SCENARIO": str(scenario_path)},
    )
    identity: tuple[int, float] | None = None
    try:
        pump = EventPump(handle)
        identity = _capture_process_identity(pid_file)

        handle.close()

        assert pump.drain_until_exit(timeout=12.0).returncode == expected_returncode
        assert not _same_process(identity)
    finally:
        handle.close()
        if identity is not None:
            _cleanup_exact_process(identity)


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


def test_wait_until_quiet_waits_for_first_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handle = object.__new__(PtyHandle)
    handle._reader_started_event = threading.Event()
    handle._reader_started_event.set()
    handle._seen_output = threading.Event()
    handle._lifecycle_lock = threading.RLock()
    handle._retired = False
    handle._master_closed = False
    handle._last_output_ts = 0.0
    handle._quiet_s = 0.1
    handle._max_settle_s = 1.0
    now = 100.0
    sleeps: list[float] = []
    first_output_at: float | None = None

    def monotonic() -> float:
        return now

    def advance(seconds: float) -> None:
        nonlocal first_output_at, now
        sleeps.append(seconds)
        now += seconds
        if first_output_at is None:
            first_output_at = now
            handle._last_output_ts = now
            handle._seen_output.set()

    class ControlledWake:
        def wait(self, timeout: float | None = None) -> bool:
            assert timeout is not None
            advance(timeout)
            return False

        def clear(self) -> None:
            pass

    handle._settle_wake = cast(Any, ControlledWake())

    monkeypatch.setattr(
        _pty_module,
        "time",
        types.SimpleNamespace(monotonic=monotonic),
    )

    handle.wait_until_quiet()

    assert first_output_at is not None
    assert sleeps
    assert now - first_output_at >= handle._quiet_s


def test_wait_until_quiet_spends_one_total_settle_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handle = object.__new__(PtyHandle)
    now = 10.0

    class ReaderStart:
        def is_set(self) -> bool:
            return False

    class BudgetWake:
        def wait(self, timeout: float | None = None) -> bool:
            nonlocal now
            assert timeout is not None
            now += timeout
            return False

        def clear(self) -> None:
            pass

    handle._reader_started_event = cast(Any, ReaderStart())
    handle._settle_wake = cast(Any, BudgetWake())
    handle._seen_output = threading.Event()
    handle._lifecycle_lock = threading.RLock()
    handle._retired = False
    handle._master_closed = False
    handle._last_output_ts = 0.0
    handle._quiet_s = 0.1
    handle._max_settle_s = 1.0
    monkeypatch.setattr(
        _pty_module.time,
        "monotonic",
        lambda: now,
    )

    handle.wait_until_quiet()

    assert now == pytest.approx(11.0)


def test_request_close_interrupts_pty_settle_wait(tmp_path: Path) -> None:
    handle, _log = _spawn_fake(
        tmp_path, {"queries": False, "modes": False, "redraw": False}
    )
    pump = EventPump(handle)
    handle._quiet_s = 10.0
    handle._max_settle_s = 10.0
    settled = threading.Event()

    def wait_for_settle() -> None:
        handle.wait_until_quiet()
        settled.set()

    waiter = threading.Thread(target=wait_for_settle)
    waiter.start()
    assert handle._reader_started_event.wait(timeout=2.0)
    handle.request_close()
    assert settled.wait(timeout=1.0)
    waiter.join(timeout=1.0)
    handle.close()
    assert isinstance(pump.drain_until_exit(), ExitEvent)


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
        _pty_module,
        "spawn_process",
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
    expected_names = {
        "absolute-size",
        "relative-size",
        "dsr-status",
        "primary-da",
        "secondary-da",
        "decrqm",
        "xtversion",
        "osc-fg",
        "osc-bg",
        "kitty-keyboard",
    }
    handle, log = _spawn_fake(
        tmp_path, {"queries": True, "modes": False}, rows=31, cols=97
    )
    pump = EventPump(handle)
    try:
        _wait_for(log, "query")
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            queries = [entry for entry in _entries(log) if entry["event"] == "query"]
            if len(queries) >= len(expected_names):
                break
            time.sleep(0.05)
        else:
            raise AssertionError(f"missing query records: {_entries(log)!r}")

        by_name = {entry["name"]: entry for entry in queries}
        assert len(queries) == len(expected_names)
        assert set(by_name) == expected_names
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
    writer_lock = _TrackingWriterLock(tracked_thread="query-reply-pump")
    handle._normal_writer_lock = cast(Any, writer_lock)
    injection_started = threading.Event()
    release_injection = threading.Event()
    first_injection_write = True

    def controlled_write(fd: int, data: bytes) -> int:
        nonlocal first_injection_write
        if data.startswith(b"serialize-me") and first_injection_write:
            first_injection_write = False
            written = real_write(fd, data[:1])
            injection_started.set()
            assert release_injection.wait(timeout=2.0)
            return written
        return real_write(fd, data)

    monkeypatch.setattr(_pty_module.os, "write", controlled_write)
    failures: list[BaseException] = []

    def inject() -> None:
        try:
            handle.inject("serialize-me")
        except BaseException as exc:  # noqa: BLE001 approved [DOM-10.2.1] [RUFF-SUP-070] exception
            failures.append(exc)

    injector = threading.Thread(target=inject)
    injector.start()
    pump: EventPump | None = None
    try:
        assert injection_started.wait(timeout=1.0)
        pump = EventPump(handle, thread_name="query-reply-pump")
        assert writer_lock.tracked_acquire.wait(timeout=2.0)
        assert injector.is_alive()
        release_injection.set()
        injector.join(timeout=2.0)
        _wait_for(log, "query")
    finally:
        release_injection.set()
        handle.close()
        injector.join(timeout=2.0)
        if pump is not None:
            pump.drain_until_exit(timeout=5.0)

    assert not injector.is_alive()
    assert failures == []


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
        handle.inject("one\r\ntwo\t\x1b[201~\x7f\u009b201~")
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            inputs = [entry for entry in _entries(log) if entry["event"] == "input"]
            if inputs:
                raw = inputs[-1]["raw"]
                assert raw == "one two [201~201~\r"
                assert "\u009b" not in raw
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
        while time.monotonic() < deadline and not handle._bracketed_paste:
            time.sleep(0.05)
        assert handle._bracketed_paste is True

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
        except BaseException as exc:  # noqa: BLE001 approved [DOM-10.2.1] [RUFF-SUP-070] exception
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
        except BaseException as exc:  # noqa: BLE001 approved [DOM-10.2.1] [RUFF-SUP-070] exception
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
    close_condition = _TrackingCondition(
        handle._lifecycle_lock,
        tracked_thread="second-pty-closer",
    )
    handle._close_condition = cast(Any, close_condition)
    failures: list[BaseException] = []

    def close() -> None:
        try:
            handle.close()
        except BaseException as exc:  # noqa: BLE001 approved [DOM-10.2.1] [RUFF-SUP-070] exception
            failures.append(exc)

    first = threading.Thread(target=close, name="first-pty-closer")
    second = threading.Thread(target=close, name="second-pty-closer")
    first.start()
    try:
        assert proc.wait_entered.wait(timeout=1.0)
        second.start()
        assert close_condition.wait_entered.wait(timeout=1.0)
    finally:
        proc.release_wait.set()
        first.join(timeout=2.0)
        if second.ident is not None:
            second.join(timeout=2.0)
    os.close(writer_fd)

    assert not first.is_alive()
    assert not second.is_alive()
    assert failures == []
    assert proc.wait_calls == 1
    assert handle._master_closed is True


def test_request_close_sends_one_ctrl_c_before_final_reap() -> None:
    master_socket, child_socket = socket.socketpair()
    proc = _ScheduledPtyProcess()
    handle = _boundary_pty_handle(proc, master_socket.detach())

    handle.request_close()
    handle.request_close()
    handle.interrupt()

    child_socket.settimeout(1.0)
    assert child_socket.recv(4096) == b"\x03"
    child_socket.settimeout(0.05)
    with pytest.raises(TimeoutError):
        child_socket.recv(1)
    assert proc.wait_calls == 0
    assert not proc.wait_entered.is_set()

    closer = threading.Thread(target=handle.close)
    closer.start()
    assert proc.wait_entered.wait(timeout=1.0)
    child_socket.settimeout(0.05)
    with pytest.raises(TimeoutError):
        child_socket.recv(1)
    proc.release_wait.set()
    closer.join(timeout=2.0)
    child_socket.close()

    assert not closer.is_alive()
    assert proc.wait_calls == 1
    assert handle._master_closed is True


def test_request_close_cancels_active_and_queued_pty_writes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    master_socket, child_socket = socket.socketpair()
    proc = _ScheduledPtyProcess()
    handle = _boundary_pty_handle(proc, master_socket.detach())
    writer_lock = _TrackingWriterLock(tracked_thread="queued-injector")
    # Install a white-box writer-serialization seam.
    handle._normal_writer_lock = cast(Any, writer_lock)
    real_write = os.write
    active_write_started = threading.Event()
    release_active_write = threading.Event()
    queued_write_started = threading.Event()
    first_active_write = True
    failures: list[BaseException] = []

    def controlled_write(fd: int, data: bytes) -> int:
        nonlocal first_active_write
        if data.startswith(b"old-active") and first_active_write:
            first_active_write = False
            written = real_write(fd, data[:1])
            active_write_started.set()
            assert release_active_write.wait(timeout=2.0)
            return written
        if data.startswith(b"old-queued"):
            queued_write_started.set()
        return real_write(fd, data)

    monkeypatch.setattr(_pty_module.os, "write", controlled_write)

    def inject(text: str) -> None:
        try:
            handle.inject(text)
        except BaseException as exc:  # noqa: BLE001 approved [DOM-10.2.1] [RUFF-SUP-070] exception
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

    handle.request_close()
    release_active_write.set()
    active.join(timeout=2.0)
    queued.join(timeout=2.0)

    with pytest.raises(AdapterError, match="closed"):
        handle.inject("after-terminal-request")
    child_socket.settimeout(1.0)
    assert child_socket.recv(4096) == b"o\x03"
    proc.returncode = 0
    handle.close()
    child_socket.close()

    assert not active.is_alive()
    assert not queued.is_alive()
    assert len(failures) == 2
    assert all(isinstance(exc, AdapterError) for exc in failures)
    assert {str(exc) for exc in failures} == {"PTY write interrupted"}
    assert not queued_write_started.is_set()


def test_request_close_dup_failure_commits_retirement_before_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    master_socket, child_socket = socket.socketpair()
    master_fd = master_socket.detach()
    proc = _ScheduledPtyProcess()
    handle = _boundary_pty_handle(proc, master_fd)
    fallback_signals: list[signal.Signals] = []

    def failing_dup(fd: int) -> int:
        assert fd == master_fd
        raise OSError(errno.EMFILE, "sentinel close-request dup exhaustion")

    monkeypatch.setattr(_pty_module.os, "dup", failing_dup)
    monkeypatch.setattr(
        handle,
        "_signal_process_group",
        lambda sig: fallback_signals.append(sig),
    )

    handle.request_close()

    assert fallback_signals == [signal.SIGTERM]
    assert proc.wait_calls == 0
    with pytest.raises(AdapterError, match="closed"):
        handle.inject("must stay retired")

    proc.returncode = 0
    handle.close()
    child_socket.close()

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
    # Install a white-box writer-serialization seam.
    handle._normal_writer_lock = cast(Any, gate)

    def inject() -> None:
        try:
            handle.inject("queued before close")
        except BaseException as exc:  # noqa: BLE001 approved [DOM-10.2.1] [RUFF-SUP-070] exception
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


def test_request_close_is_safe_when_signal_reenters_fd_lease_registration(
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
        signal.SIGUSR1, lambda _signum, _frame: handle.request_close()
    )
    try:
        handle.request_close()
    finally:
        signal.signal(signal.SIGUSR1, prior_handler)

    child_socket.settimeout(1.0)
    assert child_socket.recv(4096) == b"\x03"
    child_socket.settimeout(0.05)
    with pytest.raises(TimeoutError):
        child_socket.recv(1)
    proc.returncode = 0
    handle.close()
    child_socket.close()

    assert raised


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
        except BaseException as exc:  # noqa: BLE001 approved [DOM-10.2.1] [RUFF-SUP-070] exception
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
        except BaseException as exc:  # noqa: BLE001 approved [DOM-10.2.1] [RUFF-SUP-070] exception
            failures.append(exc)

    injector = threading.Thread(target=inject, name="injector")
    injector.start()
    assert write_entered.wait(timeout=1.0)
    handle.interrupt()
    # Drive the private close path while holding its documented owner lock.
    with handle._lifecycle_lock:
        handle._close_master_unlocked()
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
    real_close_operation_fd = handle._close_operation_fd
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
        except BaseException as exc:  # noqa: BLE001 approved [DOM-10.2.1] [RUFF-SUP-070] exception
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
    # Install a white-box writer-serialization seam.
    handle._normal_writer_lock = cast(Any, writer_lock)
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
        except BaseException as exc:  # noqa: BLE001 approved [DOM-10.2.1] [RUFF-SUP-070] exception
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


def test_activity_is_coarse_not_per_redraw(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    master_fd, writer_fd = os.pipe()
    proc = _ScheduledPtyProcess()
    handle = _boundary_pty_handle(proc, master_fd)
    chunks = [b"redraw-1", b"redraw-2", b"redraw-3", b"redraw-next-window"]
    read_times = [100.0, 105.0, 109.0, 111.0]
    now = 100.0
    real_read = os.read
    real_select = select.select

    def monotonic() -> float:
        return now

    def controlled_select(
        readers: list[int], writers: list[int], errors: list[int], timeout: float
    ) -> tuple[list[int], list[int], list[int]]:
        if readers == [master_fd]:
            if chunks:
                return [master_fd], [], []
            proc.returncode = 0
            return [], [], []
        return real_select(readers, writers, errors, timeout)

    def controlled_read(fd: int, size: int) -> bytes:
        nonlocal now
        if fd == master_fd:
            now = read_times.pop(0)
            return chunks.pop(0)
        return real_read(fd, size)

    monkeypatch.setattr(
        _pty_module,
        "time",
        types.SimpleNamespace(monotonic=monotonic, sleep=lambda _seconds: None),
    )
    monkeypatch.setattr(_pty_module.select, "select", controlled_select)
    monkeypatch.setattr(_pty_module.os, "read", controlled_read)

    events = handle.events()
    try:
        spawn = next(events)
        first_output = next(events)
        first_output_at = now
        second_output = next(events)
        second_output_at = now
        exit_event = next(events)
        with pytest.raises(StopIteration):
            next(events)

        assert isinstance(spawn, ActivityEvent) and spawn.description == "spawn"
        assert isinstance(first_output, ActivityEvent)
        assert first_output.description == "output"
        assert first_output_at == 100.0
        assert isinstance(second_output, ActivityEvent)
        assert second_output.description == "output"
        assert second_output_at == 111.0
        assert isinstance(exit_event, ExitEvent)
    finally:
        proc.returncode = 0
        handle.close()
        os.close(writer_fd)


def test_attach_bridges_and_split_chord_detaches_with_reset(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handle, log = _spawn_fake(
        tmp_path, {"queries": False, "modes": False, "redraw": False}
    )
    user_master, user_slave = pty.openpty()
    saved_termios = termios.tcgetattr(user_slave)
    wake = threading.Event()
    shutdown = threading.Event()
    result: list[str] = []
    first_chord_processed = threading.Event()
    first_chord_result: list[tuple[bytes, bool]] = []
    real_matcher = _pty_module._DetachChordMatcher

    class ObservedMatcher:
        def __init__(self, chord: bytes) -> None:
            self._delegate = real_matcher(chord)

        def feed(self, data: bytes) -> tuple[bytes, bool]:
            matched = self._delegate.feed(data)
            if (
                data == b"\x1c"
                and threading.current_thread().name == "split-chord-attach"
                and not first_chord_processed.is_set()
            ):
                first_chord_result.append(matched)
                first_chord_processed.set()
            return matched

    monkeypatch.setattr(_pty_module, "_DetachChordMatcher", ObservedMatcher)
    thread = threading.Thread(
        target=lambda: result.append(
            handle.attach(
                wake=wake, shutdown=shutdown, input_fd=user_slave, output_fd=user_slave
            )
        ),
        daemon=True,
        name="split-chord-attach",
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
        assert first_chord_processed.wait(timeout=2.0)
        assert first_chord_result == [(b"", False)]
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


def test_attach_passively_retains_output_and_bracketed_paste_mode(
    tmp_path: Path,
) -> None:
    handle, log = _spawn_fake(
        tmp_path,
        {"queries": False, "modes": True, "redraw": False},
    )
    user_master, user_slave = pty.openpty()
    wake = threading.Event()
    shutdown = threading.Event()
    result: list[str] = []
    thread = threading.Thread(
        target=lambda: result.append(
            handle.attach(
                wake=wake,
                shutdown=shutdown,
                input_fd=user_slave,
                output_fd=user_slave,
            )
        ),
        daemon=True,
        name="passive-mode-attach",
    )
    thread.start()
    try:
        assert b"ready" in _read_fd_until(user_master, b"ready")
        os.write(user_master, b"\x1c\x1c")
        _read_fd_until(user_master, b"\x1b[?2004l", timeout=1.0)
        thread.join(timeout=5.0)

        assert result == ["detached"]
        assert handle._seen_output.is_set()
        assert handle._bracketed_paste is True

        handle.inject("first line\nsecond line")
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            inputs = [entry for entry in _entries(log) if entry["event"] == "input"]
            if inputs:
                assert inputs[-1]["raw"] == (
                    "\x1b[200~first line\nsecond line\x1b[201~\r"
                )
                break
            time.sleep(0.05)
        else:
            raise AssertionError(f"no bracketed input after attach: {_entries(log)!r}")
    finally:
        handle.close()
        os.close(user_master)
        os.close(user_slave)


def test_passive_input_mode_tracker_carries_split_enable_and_disable() -> None:
    tracker = _pty_module._TerminalInputModeTracker()

    tracker.feed(b"screen\x1b[?20")
    assert tracker.bracketed_paste is False
    tracker.feed(b"04h")
    assert tracker.bracketed_paste is True
    tracker.feed(b"\x1b[")
    tracker.feed(b"?2004l")
    assert tracker.bracketed_paste is False


def test_input_prompt_observed_latches_across_paste_disable(
    tmp_path: Path,
) -> None:
    handle, _log = _spawn_fake(tmp_path, {"queries": False, "modes": True})
    pump = EventPump(handle)
    try:
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline and not handle.input_prompt_observed:
            time.sleep(0.05)
        assert handle.input_prompt_observed is True
        # A later paste-mode disable (alt-screen exit) must not unconfirm.
        handle._observe_output(b"\x1b[?2004l")
        assert handle._bracketed_paste is False
        assert handle.input_prompt_observed is True
    finally:
        handle.close()
    assert isinstance(pump.drain_until_exit(), ExitEvent)


def test_input_prompt_not_observed_without_paste_mode(tmp_path: Path) -> None:
    handle, log = _spawn_fake(tmp_path, {"queries": False, "modes": False})
    pump = EventPump(handle)
    try:
        _wait_for(log, "start")
        handle.wait_until_quiet()
        assert handle.input_prompt_observed is False
    finally:
        handle.close()
    assert isinstance(pump.drain_until_exit(), ExitEvent)


def test_input_prompt_latch_survives_enable_and_disable_in_one_chunk(
    tmp_path: Path,
) -> None:
    handle, _log = _spawn_fake(tmp_path, {"queries": False, "modes": False})
    pump = EventPump(handle)
    try:
        handle._observe_output(b"\x1b[?2004hmenu\x1b[?2004l")
        assert handle._bracketed_paste is False
        assert handle.input_prompt_observed is True
    finally:
        handle.close()
    assert isinstance(pump.drain_until_exit(), ExitEvent)


def test_output_tail_is_bounded_control_stripped_text(tmp_path: Path) -> None:
    handle, _log = _spawn_fake(tmp_path, {"queries": False, "modes": False})
    pump = EventPump(handle)
    try:
        handle._observe_output(
            b"\x1b[2J\x1b[H  Trust this folder?\x07\r\n\x9b1m  > Don't trust\x1b[0m"
        )
        tail = handle.output_tail()
        assert "Trust this folder?" in tail
        assert "> Don't trust" in tail
        assert "\x1b" not in tail
        assert "\x9b" not in tail
        assert "\x07" not in tail
        assert "\r" not in tail
        # Complete sequences are removed, not just their control bytes:
        # truecolor SGR parameters, OSC-8 hyperlink bodies, private-mode
        # sets, and split-across-chunks sequences leave no printable residue
        # (observed residue from the 2026-08-19 Kimi give-up: "[38;2;..m",
        # "]8;;", "[?2026l").
        assert "[2J" not in tail
        assert "1m" not in tail

        handle._observe_output(
            b"\x1b[38;2;232;168;56mmodel-monster (http)\x1b[39m\x1b[0m"
            b"\x1b]8;;https://example.invalid\x07link\x1b]8;;\x1b\\"
            b"\x1b[?2026l\x1b[?25h\x1b[?2004l Bye!"
        )
        handle._observe_output(b"\x1b[38;2;10;")  # split CSI, continued...
        handle._observe_output(b"20;30mtail-after-split\x1b[0m")
        tail = handle.output_tail()
        assert "model-monster (http)" in tail
        assert "link" in tail
        assert "Bye!" in tail
        assert "tail-after-split" in tail
        assert "38;2" not in tail
        assert "]8;;" not in tail
        assert "?2026" not in tail
        assert "?25h" not in tail
        assert "example.invalid" not in tail

        # UTF-8 text whose continuation bytes collide with C1 introducer
        # values (s-acute is C5 9B, the CSI C1 byte) must survive intact.
        handle._observe_output("menü für ś-tests: żółć\r\n".encode())
        tail = handle.output_tail()
        assert "ś-tests" in tail
        assert "żółć" in tail
        assert "menü für" in tail

        # Unterminated string-bodied and intermediate forms dangling at the
        # buffer end are dropped, not leaked as printable body text.
        handle._observe_output(b"before-dcs\x1bPq#0;sixel-body-noise")
        tail = handle.output_tail()
        assert "before-dcs" in tail
        assert "sixel-body-noise" not in tail
        handle._observe_output(b"after-dcs ok\r\ncharset\x1b(")
        tail = handle.output_tail()
        assert "after-dcs ok" in tail
        assert not tail.endswith("(")

        handle._observe_output(b"x" * 8192 + b"FINAL")
        tail = handle.output_tail()
        assert len(tail) <= 1024
        assert tail.endswith("FINAL")

        handle._observe_output(b"\xff\xfe broken utf8")
        assert "broken utf8" in handle.output_tail()
    finally:
        handle.close()
    assert isinstance(pump.drain_until_exit(), ExitEvent)


def test_attach_passive_observation_emits_no_query_reply_or_diagnostic(
    tmp_path: Path,
) -> None:
    handle, log = _spawn_fake(
        tmp_path,
        {
            "queries": False,
            "modes": False,
            "redraw": False,
            "unknown_query": "[?15n",
            "unknown_blocks": True,
        },
        stall_s=0.1,
    )
    user_master, user_slave = pty.openpty()
    wake = threading.Event()
    shutdown = threading.Event()
    result: list[str] = []
    thread = threading.Thread(
        target=lambda: result.append(
            handle.attach(
                wake=wake,
                shutdown=shutdown,
                input_fd=user_slave,
                output_fd=user_slave,
            )
        ),
        daemon=True,
        name="passive-query-attach",
    )
    thread.start()
    pump: EventPump | None = None
    try:
        assert b"\x1b[?15n" in _read_fd_until(user_master, b"\x1b[?15n")
        _wait_for(log, "unknown_reply_window")
        window = [
            entry for entry in _entries(log) if entry["event"] == "unknown_reply_window"
        ][-1]
        assert window["got"] == ""

        os.write(user_master, b"\x1c\x1c")
        _read_fd_until(user_master, b"\x1b[?2004l", timeout=1.0)
        thread.join(timeout=5.0)
        assert result == ["detached"]

        pump = EventPump(handle)
        time.sleep(0.25)
        assert "awaiting_query" not in handle.status_fields()
    finally:
        handle.close()
        if pump is not None:
            assert isinstance(pump.drain_until_exit(), ExitEvent)
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
        probe = b"\x1b]52;c;Y2xpcGJvYXJk\x07\x1b[31m"
        os.write(user_master, probe + b"\r")
        echoed = _read_fd_until(user_master, b"echo:" + probe)
        assert b"echo:" + probe in echoed
        wait_deadline = time.monotonic() + 5.0
        while time.monotonic() < wait_deadline:
            inputs = [entry for entry in _entries(log) if entry["event"] == "input"]
            if inputs:
                assert inputs[-1]["raw"] == (probe + b"\r").decode("latin1")
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
    writer_lock = _TrackingWriterLock(tracked_thread="agent-injector")
    handle._normal_writer_lock = cast(Any, writer_lock)
    forwarding_started = threading.Event()
    release_forwarding = threading.Event()
    first_forwarding_write = True

    def controlled_write(fd: int, data: bytes) -> int:
        nonlocal first_forwarding_write
        if (
            threading.current_thread().name == "attach-bridge"
            and data.startswith(b"human")
            and first_forwarding_write
        ):
            first_forwarding_write = False
            written = real_write(fd, data[:1])
            forwarding_started.set()
            assert release_forwarding.wait(timeout=2.0)
            return written
        return real_write(fd, data)

    monkeypatch.setattr(_pty_module.os, "write", controlled_write)
    failures: list[BaseException] = []

    def inject() -> None:
        try:
            handle.inject("agent")
        except BaseException as exc:  # noqa: BLE001 approved [DOM-10.2.1] [RUFF-SUP-070] exception
            failures.append(exc)

    injector = threading.Thread(target=inject, name="agent-injector")
    try:
        os.write(user_master, b"human\r")
        assert forwarding_started.wait(timeout=1.0)
        injector.start()
        assert writer_lock.tracked_acquire.wait(timeout=2.0)
        assert injector.is_alive()
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
    inputs = [entry["raw"] for entry in _entries(_log) if entry["event"] == "input"]
    input_stream = "".join(inputs).split("\x03", 1)[0]
    assert input_stream == "human\ragent\r"


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
        except BaseException as exc:  # noqa: BLE001 approved [DOM-10.2.1] [RUFF-SUP-070] exception
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
