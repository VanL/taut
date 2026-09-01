"""Adapter-interface tests against the real scripted provider subprocess.

Contract under test: docs/specs/04-summon.md [SUM-7.1] (spawn / inject /
events / interrupt, the closed ``AdapterEvent`` union, synchronous inject
failure, interrupt unblocking an in-flight inject) and [SUM-7.2] (the
``scripted`` adapter ships in the package).

Anti-mocking posture ([SUM-12]): behavior and integration cases spawn the real
scripted provider and speak over real pipes. Lifecycle-lock and failure-priority
cases use deterministic ``Popen``-shaped boundary doubles to force otherwise
uncontrollable interleavings through the production handle implementation.
"""

from __future__ import annotations

import json
import os
import queue
import select
import signal
import subprocess
import sys
import textwrap
import threading
import time
import types
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Self, cast

import psutil
import pytest
from taut_summon import _stream as _stream_module
from taut_summon._adapter import (
    ActivityEvent,
    AdapterError,
    AdapterEvent,
    AdapterHandle,
    AssistantTextEvent,
    ExitEvent,
    SessionEvent,
    UnknownAdapterError,
    adapter_names,
    get_adapter,
)
from taut_summon._process_domain import ProcessIO, spawn_process
from taut_summon._scripted import ScriptedHandle


class _CountingStream:
    def __init__(self) -> None:
        self.close_calls = 0
        self.writes: list[str] = []
        self.flush_calls = 0

    def write(self, value: str) -> int:
        self.writes.append(value)
        return len(value)

    def flush(self) -> None:
        self.flush_calls += 1

    def close(self) -> None:
        self.close_calls += 1


class _CloseRacingReadStream(_CountingStream):
    """Expose a reader blocked while its lifecycle owner closes the stream."""

    def __init__(self) -> None:
        super().__init__()
        self.read_entered = threading.Event()
        self.close_released_read = threading.Event()
        self.closed = False

    def __iter__(self) -> _CloseRacingReadStream:
        return self

    def __next__(self) -> str:
        self.read_entered.set()
        assert self.close_released_read.wait(timeout=2.0)
        raise ValueError("I/O operation on closed file.")

    def close(self) -> None:
        super().close()
        self.closed = True
        self.close_released_read.set()


class _UnexpectedReadFailureStream(_CountingStream):
    closed = False

    def __iter__(self) -> _UnexpectedReadFailureStream:
        return self

    def __next__(self) -> str:
        raise ValueError("unexpected open-stream failure")


class _ClosedSingleLineStream(_CountingStream):
    closed = True

    def __iter__(self) -> Iterator[str]:
        return iter(["one complete provider frame\n"])


class _ClosedDecodeFailureStream(_CountingStream):
    closed = True

    def __iter__(self) -> _ClosedDecodeFailureStream:
        return self

    def __next__(self) -> str:
        raise UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte")


class _ReentrantInterruptProcess:
    """Popen-shaped boundary fake for deterministic signal reentry."""

    pid = 12345

    def __init__(self) -> None:
        self.stdin = _CountingStream()
        self.stdout = _CountingStream()
        self.returncode: int | None = None
        self.signal_calls = 0
        self.terminate_calls = 0
        self.on_first_signal: Callable[[], None] | None = None

    def poll(self) -> int | None:
        return self.returncode

    def send_signal(self, _signum: int) -> None:
        self.signal_calls += 1
        self.returncode = 0
        if self.signal_calls == 1 and self.on_first_signal is not None:
            self.on_first_signal()

    def terminate(self) -> None:
        self.terminate_calls += 1
        self.send_signal(signal.SIGTERM)

    def wait(self, timeout: float | None = None) -> int:
        del timeout
        self.returncode = 0
        return 0

    def kill(self) -> None:
        self.returncode = -9


class _BlockingCloseProcess(_ReentrantInterruptProcess):
    def __init__(self) -> None:
        super().__init__()
        self.wait_entered = threading.Event()
        self.release_wait = threading.Event()
        self.wait_calls = 0

    def send_signal(self, _signum: int) -> None:
        self.signal_calls += 1

    def wait(self, timeout: float | None = None) -> int:
        del timeout
        self.wait_calls += 1
        self.wait_entered.set()
        assert self.release_wait.wait(timeout=2.0)
        self.returncode = 0
        return 0


class _BlockingInjectLock:
    """Expose the point where inject has entered its serialization gate."""

    def __init__(self) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()

    def __enter__(self) -> None:
        self.entered.set()
        assert self.release.wait(timeout=2.0)

    def __exit__(self, *_args: object) -> None:
        return None


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


class _SignalReleasedBlockingStream(_CountingStream):
    """Stay inside write until the process receives its terminal signal."""

    def __init__(self) -> None:
        super().__init__()
        self.write_entered = threading.Event()
        self.signal_received = threading.Event()

    def write(self, value: str) -> int:
        self.writes.append(value)
        self.write_entered.set()
        assert self.signal_received.wait(timeout=2.0)
        raise BrokenPipeError("sentinel signal broke blocked write")


class _SignalReleasesWriteProcess(_ReentrantInterruptProcess):
    def __init__(self) -> None:
        super().__init__()
        self.stdin = _SignalReleasedBlockingStream()

    def send_signal(self, _signum: int) -> None:
        self.signal_calls += 1
        self.returncode = 0
        assert isinstance(self.stdin, _SignalReleasedBlockingStream)
        self.stdin.signal_received.set()


class _NeverReapsProcess(_ReentrantInterruptProcess):
    def __init__(self) -> None:
        super().__init__()
        self.kill_calls = 0
        self.wait_calls = 0

    def send_signal(self, _signum: int) -> None:
        self.signal_calls += 1

    def wait(self, timeout: float | None = None) -> int:
        self.wait_calls += 1
        raise subprocess.TimeoutExpired("never-reaps", timeout or 0.0)

    def kill(self) -> None:
        self.kill_calls += 1


class _InterruptDuringWaitProcess(_ReentrantInterruptProcess):
    def __init__(self) -> None:
        super().__init__()
        self.on_wait: Callable[[], None] | None = None

    def send_signal(self, _signum: int) -> None:
        self.signal_calls += 1

    def wait(self, timeout: float | None = None) -> int:
        del timeout
        if self.on_wait is not None:
            self.on_wait()
        self.returncode = 0
        return 0


class _FakeProcessDomain:
    """Deterministic lifecycle boundary for Popen-shaped concurrency doubles."""

    def __init__(self, proc: Any) -> None:
        self._proc = proc

    def observe_leader_exit(self) -> int | None:
        return cast(int | None, self._proc.poll())

    def wait_for_leader_exit(self, timeout: float) -> int | None:
        try:
            return int(self._proc.wait(timeout=timeout))
        except subprocess.TimeoutExpired:
            return None

    def signal_leader(self, sig: signal.Signals) -> None:
        if self.observe_leader_exit() is not None:
            return
        if _stream_module.sys.platform == "win32":
            self._proc.terminate()
        else:
            self._proc.send_signal(sig)

    def finalize(self) -> int:
        if self._proc.poll() is None:
            try:
                return int(self._proc.wait(timeout=5.0))
            except subprocess.TimeoutExpired:
                self._proc.kill()
                try:
                    return int(self._proc.wait(timeout=5.0))
                except subprocess.TimeoutExpired as exc:
                    raise AdapterError(
                        "provider child did not exit after SIGKILL"
                    ) from exc
        return int(self._proc.returncode or 0)


class _FakeProcessIO:
    """Borrow the fake's replaceable streams without lifecycle methods."""

    def __init__(self, proc: Any) -> None:
        self._proc = proc

    @property
    def pid(self) -> int:
        return int(self._proc.pid)

    @property
    def stdin(self) -> Any:
        return self._proc.stdin

    @property
    def stdout(self) -> Any:
        return self._proc.stdout


def _fake_handle(proc: Any) -> ScriptedHandle:
    return ScriptedHandle(
        cast(ProcessIO, _FakeProcessIO(proc)),
        domain=cast(Any, _FakeProcessDomain(proc)),
        session_id=None,
    )


class EventPump:
    """Drain ``handle.events()`` on a thread so tests can bound their waits.

    This is the same continuous-drain discipline [SUM-7.1] demands of the
    driver; the thread reads the real child stdout pipe.
    """

    def __init__(self, handle: AdapterHandle) -> None:
        self._items: queue.Queue[AdapterEvent | Exception] = queue.Queue()
        self._thread = threading.Thread(target=self._run, args=(handle,), daemon=True)
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
            raise AssertionError("timed out waiting for an adapter event") from None
        if isinstance(item, Exception):
            raise item
        return item

    def next_of(self, event_type: type, timeout: float = 10.0) -> AdapterEvent:
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            assert remaining > 0, f"timed out waiting for {event_type.__name__}"
            event = self.next(timeout=remaining)
            if isinstance(event, event_type):
                return event


def _write_scenario(tmp_path: Path, scenario: dict[str, Any]) -> Path:
    path = tmp_path / "scenario.json"
    path.write_text(json.dumps(scenario), encoding="utf-8")
    return path


@contextmanager
def scripted_handle(
    tmp_path: Path,
    scenario: dict[str, Any],
    *,
    session_id: str | None = None,
) -> Iterator[ScriptedHandle]:
    scenario_path = _write_scenario(tmp_path, scenario)
    adapter = get_adapter("scripted")
    handle = adapter.spawn(
        session_id=session_id,
        system_prompt="you are a scripted test provider",
        env={"TAUT_SUMMON_SCENARIO": str(scenario_path)},
    )
    assert isinstance(handle, ScriptedHandle)
    try:
        yield handle
    finally:
        handle.close()


def _process_exists(pid: int) -> bool:
    if os.name == "nt":
        return psutil.pid_exists(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def _capture_process_identity(pid_file: Path) -> tuple[int, float]:
    deadline = time.monotonic() + 5.0
    payload: object | None = None
    while payload is None:
        assert time.monotonic() < deadline, "descendant did not publish its PID"
        try:
            payload = json.loads(pid_file.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            time.sleep(0.01)
    assert isinstance(payload, dict)
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
    try:
        process.wait(timeout=5.0)
    except psutil.TimeoutExpired as exc:
        raise AssertionError(f"descendant {pid} survived bounded cleanup") from exc


def _fill_real_stdin_pipe(handle: ScriptedHandle) -> threading.Event:
    """Fill the shipped provider's real pipe and expose inject arrival."""

    stdin = handle._proc.stdin
    assert stdin is not None
    fd = stdin.fileno()
    was_blocking = os.get_blocking(fd)
    filled = 0
    os.set_blocking(fd, False)
    try:
        while True:
            try:
                filled += os.write(fd, b"x" * 65_536)
            except BlockingIOError:
                break
    finally:
        os.set_blocking(fd, was_blocking)
    assert filled > 0
    return handle._write_waiting


_REAL_PIPE_NONBLOCKING = pytest.mark.skipif(
    not hasattr(os, "get_blocking") or not hasattr(os, "set_blocking"),
    reason="real pipe-full proof requires public nonblocking pipe controls",
)


def test_registry_knows_scripted_and_rejects_unknown_names() -> None:
    assert "scripted" in adapter_names()
    adapter = get_adapter("scripted")
    assert adapter.supports_terminal_mode is True
    assert adapter.supports_attach is False
    assert adapter.orientation_via_inject is False

    with pytest.raises(UnknownAdapterError, match="scripted"):
        get_adapter("nope")


def test_structured_handle_has_explicit_non_terminal_defaults() -> None:
    proc = _ReentrantInterruptProcess()
    handle = _fake_handle(proc)

    handle.wait_until_quiet()
    handle.mark_awaiting_onboarding()
    # Vacuous [SUM-7.4] facts: structured adapters never gate on a terminal
    # input prompt and retain no raw screen tail.
    assert handle.input_prompt_observed is True
    assert handle.output_tail() == ""
    with pytest.raises(AdapterError, match="does not support terminal attach"):
        handle.attach(wake=threading.Event(), shutdown=threading.Event())

    handle.close()


def test_windows_interrupt_uses_process_terminate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proc = _ReentrantInterruptProcess()
    handle = _fake_handle(proc)
    monkeypatch.setattr(
        _stream_module,
        "sys",
        types.SimpleNamespace(platform="win32"),
    )

    handle.interrupt()

    assert proc.terminate_calls == 1
    assert proc.signal_calls == 1


def test_windows_terminal_request_terminates_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proc = _ReentrantInterruptProcess()
    handle = _fake_handle(proc)
    monkeypatch.setattr(
        _stream_module,
        "sys",
        types.SimpleNamespace(platform="win32", exception=sys.exception),
    )

    handle.request_close()
    handle.request_close()
    handle.interrupt()
    handle.close()

    assert proc.terminate_calls == 1
    assert proc.signal_calls == 1


def test_owned_close_ends_a_blocked_event_reader_without_thread_failure() -> None:
    proc = _ReentrantInterruptProcess()
    stream = _CloseRacingReadStream()
    proc.stdout = stream
    handle = _fake_handle(proc)
    with ThreadPoolExecutor(max_workers=1) as executor:
        reader = executor.submit(lambda: list(handle.events()))
        assert stream.read_entered.wait(timeout=1.0)

        handle.close()

        assert reader.result(timeout=2.0) == [ExitEvent(returncode=0)]


def test_open_event_stream_value_error_remains_fatal() -> None:
    proc = _ReentrantInterruptProcess()
    proc.stdout = _UnexpectedReadFailureStream()
    handle = _fake_handle(proc)

    try:
        with pytest.raises(ValueError, match="unexpected open-stream failure"):
            list(handle.events())
    finally:
        handle.close()


def test_closed_event_stream_translation_value_error_remains_fatal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proc = _ReentrantInterruptProcess()
    proc.stdout = _ClosedSingleLineStream()
    handle = _fake_handle(proc)

    def fail_translation(_line: str) -> AdapterEvent:
        raise ValueError("translation failure")

    monkeypatch.setattr(handle, "_parse_line", fail_translation)
    handle.request_close()

    try:
        with pytest.raises(ValueError, match="translation failure"):
            list(handle.events())
    finally:
        handle.close()


def test_closed_event_stream_decode_failure_remains_fatal() -> None:
    proc = _ReentrantInterruptProcess()
    proc.stdout = _ClosedDecodeFailureStream()
    handle = _fake_handle(proc)
    handle.request_close()

    try:
        with pytest.raises(UnicodeDecodeError, match="invalid start byte"):
            list(handle.events())
    finally:
        handle.close()


def test_echo_round_trip_through_real_pipes(tmp_path: Path) -> None:
    scenario = {"default_response": [{"assistant_text": "echo: {text}"}]}
    with scripted_handle(tmp_path, scenario) as handle:
        pump = EventPump(handle)
        pump.next_of(SessionEvent)

        handle.inject("hello")

        event = pump.next_of(AssistantTextEvent)
        assert isinstance(event, AssistantTextEvent)
        assert event.text == "echo: hello"


def test_session_event_updates_handle_session_id(tmp_path: Path) -> None:
    scenario = {"session_id": "sess-1", "on_start": [{"session": "sess-2"}]}
    with scripted_handle(tmp_path, scenario) as handle:
        pump = EventPump(handle)

        first = pump.next_of(SessionEvent)
        assert isinstance(first, SessionEvent)
        assert first.session_id == "sess-1"

        second = pump.next_of(SessionEvent)
        assert isinstance(second, SessionEvent)
        assert second.session_id == "sess-2"
        assert handle.session_id == "sess-2"


def test_spawn_session_id_resumes_that_session(tmp_path: Path) -> None:
    # [SUM-7.3]: the driver offers the stored session id back at spawn.
    scenario = {"session_id": "ignored-when-resuming"}
    with scripted_handle(tmp_path, scenario, session_id="resume-9") as handle:
        pump = EventPump(handle)

        first = pump.next_of(SessionEvent)
        assert isinstance(first, SessionEvent)
        assert first.session_id == "resume-9"
        assert handle.session_id == "resume-9"


def test_spawn_replaces_inherited_host_identity_in_real_child(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log = tmp_path / "received.jsonl"
    monkeypatch.setenv("TAUT_AS", "HostPersona")
    monkeypatch.setenv("TAUT_TOKEN", "host-token")
    adapter = get_adapter("scripted")
    handle = adapter.spawn(
        session_id=None,
        system_prompt="identity boundary",
        env={
            "TAUT_TOKEN": "summoned-token",
            "TAUT_SUMMON_RECEIVED_LOG": str(log),
        },
    )
    try:
        EventPump(handle).next_of(SessionEvent)
    finally:
        handle.close()

    start = next(
        json.loads(line)
        for line in log.read_text(encoding="utf-8").splitlines()
        if json.loads(line).get("event") == "start"
    )
    assert start["env_as"] is None
    assert start["env_token"] == "summoned-token"
    assert os.environ["TAUT_AS"] == "HostPersona"
    assert os.environ["TAUT_TOKEN"] == "host-token"


def test_crash_scenario_yields_exit_event(tmp_path: Path) -> None:
    scenario = {"responses": [[{"exit": 3}]]}
    with scripted_handle(tmp_path, scenario) as handle:
        pump = EventPump(handle)
        pump.next_of(SessionEvent)

        handle.inject("trigger the crash")

        event = pump.next_of(ExitEvent)
        assert isinstance(event, ExitEvent)
        assert event.returncode == 3


def test_inject_after_exit_fails_synchronously(tmp_path: Path) -> None:
    scenario = {"responses": [[{"exit": 3}]]}
    with scripted_handle(tmp_path, scenario) as handle:
        pump = EventPump(handle)
        pump.next_of(SessionEvent)
        handle.inject("trigger the crash")
        pump.next_of(ExitEvent)

        with pytest.raises(AdapterError):
            handle.inject("anyone there?")


def test_flood_drains_without_deadlock_while_nothing_injects(
    tmp_path: Path,
) -> None:
    flood_size = 2000
    scenario = {"on_start": [{"flood_activity": flood_size}]}
    with scripted_handle(tmp_path, scenario) as handle:
        pump = EventPump(handle)
        pump.next_of(SessionEvent)

        seen = 0
        deadline = time.monotonic() + 30.0
        while seen < flood_size:
            remaining = deadline - time.monotonic()
            assert remaining > 0, f"flood stalled after {seen} events"
            event = pump.next(timeout=remaining)
            if isinstance(event, ActivityEvent):
                seen += 1


@pytest.mark.parametrize("terminal_action", ["interrupt", "request_close"])
def test_terminal_action_unblocks_write_after_stream_entry(
    terminal_action: str,
) -> None:
    proc = _SignalReleasesWriteProcess()
    handle = _fake_handle(proc)
    failures: list[Exception] = []

    def blocked_inject() -> None:
        try:
            handle.inject("blocked after stream entry")
        except Exception as exc:  # noqa: BLE001 approved [DOM-10.2.1] [RUFF-SUP-071] exception
            failures.append(exc)

    injector = threading.Thread(target=blocked_inject)
    injector.start()
    assert isinstance(proc.stdin, _SignalReleasedBlockingStream)
    assert proc.stdin.write_entered.wait(timeout=1.0)

    getattr(handle, terminal_action)()

    injector.join(timeout=2.0)
    assert not injector.is_alive()
    assert proc.signal_calls == 1
    assert len(failures) == 1
    assert isinstance(failures[0], AdapterError)
    if terminal_action == "request_close":
        with pytest.raises(AdapterError, match="close_requested"):
            handle.inject("must stay retired")
    handle.close()


def test_interrupt_cancels_current_stream_write_and_handle_rearms() -> None:
    proc = _SignalReleasesWriteProcess()
    handle = _fake_handle(proc)
    failures: list[Exception] = []

    def blocked_inject() -> None:
        try:
            handle.inject("blocked turn")
        except Exception as exc:  # noqa: BLE001 approved [DOM-10.2.1] [RUFF-SUP-071] exception
            failures.append(exc)

    injector = threading.Thread(target=blocked_inject)
    injector.start()
    assert isinstance(proc.stdin, _SignalReleasedBlockingStream)
    assert proc.stdin.write_entered.wait(timeout=1.0)

    handle.interrupt()
    injector.join(timeout=2.0)
    assert not injector.is_alive()
    assert len(failures) == 1
    assert isinstance(failures[0], AdapterError)

    replacement = _CountingStream()
    proc.stdin = replacement
    proc.returncode = None
    handle.inject("after interrupt")
    assert len(replacement.writes) == 1
    assert "after interrupt" in replacement.writes[0]
    proc.returncode = 0
    handle.close()


@pytest.mark.skipif(
    os.name == "nt", reason="real cooperative SIGINT probe is POSIX-only"
)
@_REAL_PIPE_NONBLOCKING
def test_interrupt_cancels_full_pipe_and_real_child_accepts_next_turn() -> None:
    control_r, control_w = os.pipe()
    child_code = textwrap.dedent(
        """
        import json
        import os
        import signal
        import sys

        signal.signal(signal.SIGINT, signal.SIG_IGN)
        print("ready", flush=True)
        os.read(int(sys.argv[1]), 1)
        buffered = b""
        while b"\\n" not in buffered:
            buffered += os.read(0, 65536)
        _, buffered = buffered.split(b"\\n", 1)
        while True:
            while b"\\n" not in buffered:
                chunk = os.read(0, 65536)
                if not chunk:
                    raise SystemExit(0)
                buffered += chunk
            line, buffered = buffered.split(b"\\n", 1)
            payload = json.loads(line.decode())
            text = payload["message"]["content"][0]["text"]
            print(text, flush=True)
        """
    )
    spawned = spawn_process(
        [sys.executable, "-c", child_code, str(control_r)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        bufsize=1,
        pass_fds=(control_r,),
    )
    proc = spawned.process
    os.close(control_r)
    handle = ScriptedHandle(proc, domain=spawned.domain, session_id=None)
    assert proc.stdout is not None
    assert proc.stdout.readline() == "ready\n"
    _fill_real_stdin_pipe(handle)
    failures: list[Exception] = []

    def blocked_inject() -> None:
        try:
            handle.inject("x" * 1_000_000)
        except Exception as exc:  # noqa: BLE001 approved [DOM-10.2.1] [RUFF-SUP-071] exception
            failures.append(exc)

    injector = threading.Thread(target=blocked_inject, daemon=True)
    injector.start()
    assert handle._write_waiting.wait(timeout=2.0)
    try:
        handle.interrupt()
        injector.join(timeout=1.0)
        assert not injector.is_alive()
        assert len(failures) == 1
        assert isinstance(failures[0], AdapterError)
        assert spawned.domain.observe_leader_exit() is None

        os.write(control_w, b"d")
        assert proc.stdin is not None
        deadline = time.monotonic() + 2.0
        while True:
            try:
                os.write(proc.stdin.fileno(), b"\n")
                break
            except BlockingIOError:
                assert time.monotonic() < deadline
                time.sleep(0.01)
        handle.inject("after interrupt")
        ready, _, _ = select.select([proc.stdout], [], [], 2.0)
        assert ready, "child did not echo the post-interrupt turn"
        assert proc.stdout.readline() == "after interrupt\n"
    finally:
        os.close(control_w)
        handle.close()


@pytest.mark.skipif(os.name == "nt", reason="real SIGINT-ignore probe is POSIX-only")
@_REAL_PIPE_NONBLOCKING
def test_request_close_cancels_full_pipe_when_child_ignores_sigint() -> None:
    child_code = (
        "import signal,time; signal.signal(signal.SIGINT, signal.SIG_IGN); "
        "print('ready', flush=True); time.sleep(60)"
    )
    spawned = spawn_process(
        [
            sys.executable,
            "-c",
            child_code,
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        bufsize=1,
    )
    proc = spawned.process
    handle = ScriptedHandle(proc, domain=spawned.domain, session_id=None)
    assert proc.stdout is not None
    assert proc.stdout.readline() == "ready\n"
    stdin = proc.stdin
    assert stdin is not None
    fd = stdin.fileno()
    while True:
        try:
            os.write(fd, b"x" * 65_536)
        except BlockingIOError:
            break
    failures: list[Exception] = []

    def blocked_inject() -> None:
        try:
            handle.inject("x" * 1_000_000)
        except Exception as exc:  # noqa: BLE001 approved [DOM-10.2.1] [RUFF-SUP-071] exception
            failures.append(exc)

    injector = threading.Thread(target=blocked_inject, daemon=True)
    injector.start()
    assert handle._write_waiting.wait(timeout=2.0)
    try:
        handle.request_close()
        injector.join(timeout=1.0)
        assert not injector.is_alive()
        assert len(failures) == 1
        assert isinstance(failures[0], AdapterError)
        assert spawned.domain.observe_leader_exit() is None
    finally:
        handle.close()


@_REAL_PIPE_NONBLOCKING
def test_interrupt_retires_inject_at_real_full_pipe_boundary(tmp_path: Path) -> None:
    # The provider announces its session and then stops reading stdin, so
    # a large inject fills the real pipe and blocks; interrupt() must
    # unblock it ([SUM-7.1], the [SUM-9] stuck-harness dependency).
    scenario = {"on_start": [{"stall": True}]}
    with scripted_handle(tmp_path, scenario) as handle:
        pump = EventPump(handle)
        pump.next_of(SessionEvent)

        failures: list[Exception] = []
        write_waiting = _fill_real_stdin_pipe(handle)

        def blocked_inject() -> None:
            try:
                handle.inject("x" * 8_000_000)
            except Exception as exc:  # noqa: BLE001 approved [DOM-10.2.1] [RUFF-SUP-071] exception
                failures.append(exc)

        injector = threading.Thread(target=blocked_inject, daemon=True)
        injector.start()
        assert write_waiting.wait(timeout=5.0)

        handle.interrupt()

        injector.join(timeout=10.0)
        assert not injector.is_alive(), "interrupt left inject blocked"
        assert len(failures) == 1
        assert isinstance(failures[0], AdapterError)

        exit_event = pump.next_of(ExitEvent)
        assert isinstance(exit_event, ExitEvent)


@_REAL_PIPE_NONBLOCKING
def test_request_close_retires_inject_at_real_full_pipe_boundary(
    tmp_path: Path,
) -> None:
    scenario = {"on_start": [{"stall": True}]}
    with scripted_handle(tmp_path, scenario) as handle:
        pump = EventPump(handle)
        pump.next_of(SessionEvent)
        failures: list[Exception] = []
        write_waiting = _fill_real_stdin_pipe(handle)

        def blocked_inject() -> None:
            try:
                handle.inject("x" * 8_000_000)
            except Exception as exc:  # noqa: BLE001 approved [DOM-10.2.1] [RUFF-SUP-071] exception
                failures.append(exc)

        injector = threading.Thread(target=blocked_inject, daemon=True)
        injector.start()
        assert write_waiting.wait(timeout=5.0)

        handle.request_close()

        injector.join(timeout=10.0)
        assert not injector.is_alive(), "terminal close request left inject blocked"
        assert len(failures) == 1
        assert isinstance(failures[0], AdapterError)
        with pytest.raises(AdapterError, match="close_requested"):
            handle.inject("must stay retired")
        assert isinstance(pump.next_of(ExitEvent), ExitEvent)


def test_request_close_is_nonblocking_terminal_and_signals_once() -> None:
    proc = _BlockingCloseProcess()
    handle = _fake_handle(proc)

    handle.request_close()
    handle.request_close()
    handle.interrupt()

    assert proc.signal_calls == 1
    assert proc.wait_calls == 0
    assert not proc.wait_entered.is_set()
    with pytest.raises(AdapterError, match="close_requested"):
        handle.inject("must not be delivered")

    closer = threading.Thread(target=handle.close)
    closer.start()
    assert proc.wait_entered.wait(timeout=1.0)
    assert proc.signal_calls == 1
    proc.release_wait.set()
    closer.join(timeout=2.0)

    assert not closer.is_alive()
    assert proc.signal_calls == 1
    assert proc.wait_calls == 1


def test_inject_refuses_after_close_publishes_closing() -> None:
    proc = _BlockingCloseProcess()
    handle = _fake_handle(proc)
    closer = threading.Thread(target=handle.close)
    closer.start()
    assert proc.wait_entered.wait(timeout=1.0)

    try:
        with pytest.raises(AdapterError, match="closing"):
            handle.inject("must not be delivered")
        assert proc.stdin.writes == []
        assert proc.stdin.flush_calls == 0
    finally:
        proc.release_wait.set()
        closer.join(timeout=2.0)


def test_queued_inject_rechecks_close_state_under_serialization() -> None:
    proc = _BlockingCloseProcess()
    handle = _fake_handle(proc)
    gate = _BlockingInjectLock()
    # Install a white-box lifecycle race seam.
    handle._inject_lock = cast(Any, gate)
    failures: list[BaseException] = []

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

    assert not injector.is_alive()
    assert not closer.is_alive()
    assert len(failures) == 1
    assert isinstance(failures[0], AdapterError)
    assert "closing" in str(failures[0])
    assert proc.stdin.writes == []
    assert proc.stdin.flush_calls == 0


def test_interrupt_can_reenter_close_while_lifecycle_state_is_owned() -> None:
    proc = _ReentrantInterruptProcess()
    handle = _fake_handle(proc)
    proc.on_first_signal = handle.interrupt
    failures: list[BaseException] = []

    def close() -> None:
        try:
            handle.close()
        except BaseException as exc:  # noqa: BLE001 approved [DOM-10.2.1] [RUFF-SUP-070] exception
            failures.append(exc)

    closer = threading.Thread(target=close, daemon=True)
    closer.start()
    closer.join(timeout=1.0)

    assert not closer.is_alive(), "same-thread interrupt reentry deadlocked close"
    assert failures == []


def test_request_close_can_reenter_itself_while_lifecycle_state_is_owned() -> None:
    proc = _ReentrantInterruptProcess()
    handle = _fake_handle(proc)
    proc.on_first_signal = handle.request_close

    handle.close()

    assert proc.signal_calls == 1


def test_interrupt_can_reenter_close_during_process_wait() -> None:
    proc = _InterruptDuringWaitProcess()
    handle = _fake_handle(proc)
    proc.on_wait = handle.interrupt
    failures: list[BaseException] = []

    def close() -> None:
        try:
            handle.close()
        except BaseException as exc:  # noqa: BLE001 approved [DOM-10.2.1] [RUFF-SUP-070] exception
            failures.append(exc)

    closer = threading.Thread(target=close, daemon=True)
    closer.start()
    closer.join(timeout=1.0)

    assert not closer.is_alive(), "same-thread interrupt reentry deadlocked wait"
    assert failures == []
    assert proc.signal_calls == 1


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="real SIGINT handler reentry is a POSIX process-signal proof",
)
def test_real_second_sigint_returns_while_close_waits() -> None:
    runner = """
import os
import signal
import subprocess
import sys
import threading
from taut_summon._scripted import ScriptedHandle

provider = subprocess.Popen(
    [
        sys.executable,
        "-c",
        "import signal,time; signal.signal(signal.SIGINT, signal.SIG_IGN); print('ready', flush=True); time.sleep(60)",
    ],
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    text=True,
)
assert provider.stdout is not None
assert provider.stdout.readline().strip() == "ready"
wait_entered = threading.Event()
second_handled = threading.Event()
second_sent = threading.Event()
sender_joined = threading.Event()

class ObservedDomain:
    def observe_leader_exit(self):
        return provider.returncode

    def wait_for_leader_exit(self, timeout):
        del timeout
        return provider.returncode

    def signal_leader(self, sig):
        provider.send_signal(sig)

    def finalize(self):
        wait_entered.set()
        return provider.wait(timeout=5.0)

handle = ScriptedHandle(provider, domain=ObservedDomain(), session_id=None)
signal_count = 0

def interrupt_handle(_signum, _frame):
    global signal_count
    signal_count += 1
    handle.interrupt()
    if signal_count == 2:
        second_handled.set()

signal.signal(signal.SIGINT, interrupt_handle)
os.kill(os.getpid(), signal.SIGINT)

def send_second_sigint():
    assert wait_entered.wait(timeout=1.0)
    os.kill(os.getpid(), signal.SIGINT)
    second_sent.set()
    assert second_handled.wait(timeout=1.0)
    provider.terminate()
    sender_joined.set()

sender = threading.Thread(target=send_second_sigint, daemon=True)
sender.start()
handle.close()
sender.join(timeout=1.0)
assert wait_entered.is_set()
assert second_sent.is_set()
assert second_handled.is_set()
assert sender_joined.is_set()
assert not sender.is_alive()
print("closed", flush=True)
"""

    completed = subprocess.run(
        [sys.executable, "-c", runner],
        capture_output=True,
        text=True,
        timeout=2.0,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "closed"


def test_concurrent_close_has_one_escalation_and_stream_closer() -> None:
    proc = _BlockingCloseProcess()
    handle = _fake_handle(proc)
    close_condition = _TrackingCondition(
        handle._lifecycle_lock,
        tracked_thread="second-stream-closer",
    )
    handle._close_condition = cast(Any, close_condition)
    failures: list[BaseException] = []

    def close() -> None:
        try:
            handle.close()
        except BaseException as exc:  # noqa: BLE001 approved [DOM-10.2.1] [RUFF-SUP-070] exception
            failures.append(exc)

    first = threading.Thread(target=close, name="first-stream-closer")
    second = threading.Thread(target=close, name="second-stream-closer")
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

    assert not first.is_alive()
    assert not second.is_alive()
    assert failures == []
    assert proc.signal_calls == 1
    assert proc.wait_calls == 1
    assert proc.stdin.close_calls == 1
    assert proc.stdout.close_calls == 1


def test_post_kill_timeout_is_one_terminal_adapter_error() -> None:
    proc = _NeverReapsProcess()
    handle = _fake_handle(proc)

    with pytest.raises(AdapterError, match="did not exit after SIGKILL"):
        handle.close()
    with pytest.raises(AdapterError, match="did not exit after SIGKILL"):
        handle.close()

    assert proc.signal_calls == 1
    assert proc.kill_calls == 1
    assert proc.wait_calls == 2
    assert proc.stdin.close_calls == 1
    assert proc.stdout.close_calls == 1


def test_close_failure_does_not_mask_an_active_primary_error() -> None:
    proc = _NeverReapsProcess()
    handle = _fake_handle(proc)
    primary = RuntimeError("primary provider failure")

    try:
        raise primary
    except RuntimeError:
        handle.close()

    assert primary.__notes__ == [
        "adapter cleanup also failed: provider child did not exit after SIGKILL"
    ]


def test_close_reaps_the_child_process(tmp_path: Path) -> None:
    scenario = {"default_response": [{"assistant_text": "echo: {text}"}]}
    with scripted_handle(tmp_path, scenario) as handle:
        pump = EventPump(handle)
        pump.next_of(SessionEvent)
        child_pid = handle.pid

    # close() ran on context exit: the child must be terminated AND reaped
    # (a zombie would still answer kill(pid, 0)).
    deadline = time.monotonic() + 5.0
    while _process_exists(child_pid) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not _process_exists(child_pid)


@pytest.mark.xdist_group("process")
def test_close_retires_same_domain_descendant_after_leader_exits_first(
    tmp_path: Path,
) -> None:
    """[SUM-7.1]/[SUM-12] Leader exit cannot orphan its process domain."""

    pid_file = tmp_path / "descendant.json"
    scenario = {
        "on_start": [
            {
                "spawn_descendant": {
                    "pid_file": str(pid_file),
                    "leader_exit_code": 0,
                }
            }
        ]
    }
    scenario_path = _write_scenario(tmp_path, scenario)
    handle = get_adapter("scripted").spawn(
        session_id=None,
        system_prompt="process-domain tracer",
        env={"TAUT_SUMMON_SCENARIO": str(scenario_path)},
    )
    assert isinstance(handle, ScriptedHandle)
    identity: tuple[int, float] | None = None
    try:
        pump = EventPump(handle)
        pump.next_of(SessionEvent)
        identity = _capture_process_identity(pid_file)
        exit_event = pump.next_of(ExitEvent)
        assert isinstance(exit_event, ExitEvent)
        assert exit_event.returncode == 0

        handle.close()

        deadline = time.monotonic() + 5.0
        while _same_process(identity) and time.monotonic() < deadline:
            time.sleep(0.05)
        assert not _same_process(identity)
    finally:
        handle.close()
        if identity is not None:
            _cleanup_exact_process(identity)


@pytest.mark.skipif(os.name == "nt", reason="POSIX explicit-domain escape")
@pytest.mark.xdist_group("process")
def test_close_does_not_claim_a_descendant_that_creates_a_new_session(
    tmp_path: Path,
) -> None:
    """[SUM-7.1] An explicit external lifetime is outside the owned domain."""

    pid_file = tmp_path / "escaped-descendant.json"
    scenario_path = _write_scenario(
        tmp_path,
        {
            "on_start": [
                {
                    "spawn_descendant": {
                        "pid_file": str(pid_file),
                        "escape_domain": True,
                        "leader_exit_code": 0,
                    }
                }
            ]
        },
    )
    handle = get_adapter("scripted").spawn(
        session_id=None,
        system_prompt="external-lifetime boundary",
        env={"TAUT_SUMMON_SCENARIO": str(scenario_path)},
    )
    assert isinstance(handle, ScriptedHandle)
    identity: tuple[int, float] | None = None
    try:
        pump = EventPump(handle)
        pump.next_of(SessionEvent)
        identity = _capture_process_identity(pid_file)
        exit_event = pump.next_of(ExitEvent)
        assert isinstance(exit_event, ExitEvent)
        assert exit_event.returncode == 0

        handle.close()

        assert _same_process(identity)
    finally:
        handle.close()
        if identity is not None:
            _cleanup_exact_process(identity)


@pytest.mark.xdist_group("process")
def test_leader_exit_is_observed_while_descendant_holds_stdout(
    tmp_path: Path,
) -> None:
    """[SUM-7.1]/[SUM-12] Inherited stdout cannot hide terminal leader exit."""

    pid_file = tmp_path / "stdout-descendant.json"
    scenario = {
        "on_start": [
            {
                "spawn_descendant": {
                    "pid_file": str(pid_file),
                    "inherit_stdout": True,
                    "leader_exit_code": 0,
                }
            }
        ]
    }
    scenario_path = _write_scenario(tmp_path, scenario)
    handle = get_adapter("scripted").spawn(
        session_id=None,
        system_prompt="inherited-stdout tracer",
        env={"TAUT_SUMMON_SCENARIO": str(scenario_path)},
    )
    assert isinstance(handle, ScriptedHandle)
    identity: tuple[int, float] | None = None
    try:
        pump = EventPump(handle)
        pump.next_of(SessionEvent)
        identity = _capture_process_identity(pid_file)

        exit_event = pump.next_of(ExitEvent, timeout=2.0)

        assert isinstance(exit_event, ExitEvent)
        assert exit_event.returncode == 0
    finally:
        handle.close()
        if identity is not None:
            _cleanup_exact_process(identity)


@pytest.mark.skipif(os.name == "nt", reason="POSIX raw-pipe fairness regression")
@pytest.mark.xdist_group("process")
def test_leader_exit_is_observed_while_descendant_continuously_writes_stdout(
    tmp_path: Path,
) -> None:
    """[SUM-7.1] Busy inherited stdout cannot starve leader observation."""

    pid_file = tmp_path / "busy-stdout-descendant.json"
    busy_frame = (
        json.dumps(
            {
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "x" * 2_000}],
                },
                "session_id": "scripted-session",
            },
            separators=(",", ":"),
        )
        + "\n"
    )
    scenario_path = _write_scenario(
        tmp_path,
        {
            "on_start": [
                {
                    "spawn_descendant": {
                        "pid_file": str(pid_file),
                        "inherit_stdout": True,
                        "stdout_payload": busy_frame,
                        "stdout_repeat": True,
                        "leader_exit_code": 0,
                    }
                }
            ]
        },
    )
    handle = get_adapter("scripted").spawn(
        session_id=None,
        system_prompt="busy inherited-stdout tracer",
        env={"TAUT_SUMMON_SCENARIO": str(scenario_path)},
    )
    assert isinstance(handle, ScriptedHandle)
    identity: tuple[int, float] | None = None
    try:
        pump = EventPump(handle)
        identity = _capture_process_identity(pid_file)

        exit_event = pump.next_of(ExitEvent, timeout=2.0)

        assert isinstance(exit_event, ExitEvent)
        assert exit_event.returncode == 0
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


@pytest.mark.skipif(os.name == "nt", reason="POSIX raw-pipe read budget")
def test_posix_raw_stdout_turn_has_strict_read_and_byte_bounds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """[SUM-7.1] One saturated drain turn must return to lifecycle work."""

    read_fd, write_fd = os.pipe()
    reader = _stream_module._NonblockingUtf8Lines(read_fd)
    requests: list[int] = []

    def saturated_read(_fd: int, requested: int) -> bytes:
        requests.append(requested)
        return b"x" * requested

    monkeypatch.setattr(_stream_module.os, "read", saturated_read)
    try:
        lines, eof = reader.read_available()
    finally:
        reader.close()
        os.close(read_fd)
        os.close(write_fd)

    assert lines == []
    assert eof is False
    assert 0 < len(requests) <= 16
    assert sum(requests) <= 1_048_576


@pytest.mark.skipif(os.name == "nt", reason="POSIX inherited-pipe framing")
@pytest.mark.xdist_group("process")
def test_leader_exit_does_not_promote_an_incomplete_inherited_stdout_frame(
    tmp_path: Path,
) -> None:
    """[SUM-7.1] A non-EOF line fragment is not a committed frame."""

    pid_file = tmp_path / "partial-stdout-descendant.json"
    scenario_path = _write_scenario(
        tmp_path,
        {
            "on_start": [
                {
                    "spawn_descendant": {
                        "pid_file": str(pid_file),
                        "inherit_stdout": True,
                        "stdout_payload": '{"type":"assistant"',
                        "leader_exit_code": 0,
                    }
                }
            ]
        },
    )
    handle = get_adapter("scripted").spawn(
        session_id=None,
        system_prompt="partial inherited-frame tracer",
        env={"TAUT_SUMMON_SCENARIO": str(scenario_path)},
    )
    assert isinstance(handle, ScriptedHandle)
    identity: tuple[int, float] | None = None
    try:
        pump = EventPump(handle)
        identity = _capture_process_identity(pid_file)

        exit_event = pump.next_of(ExitEvent, timeout=2.0)

        assert isinstance(exit_event, ExitEvent)
        assert exit_event.returncode == 0
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


@pytest.mark.skipif(os.name != "nt", reason="real Windows Job Object proof")
@pytest.mark.xdist_group("process")
def test_windows_job_is_nonempty_before_terminal_domain_retirement(
    tmp_path: Path,
) -> None:
    """[SUM-7.1]/[SUM-12] The retained job owns leader plus descendant."""

    pid_file = tmp_path / "windows-job-descendant.json"
    scenario_path = _write_scenario(
        tmp_path,
        {
            "on_start": [
                {
                    "spawn_descendant": {
                        "pid_file": str(pid_file),
                        "ignore_sigint": True,
                        "ignore_sigterm": True,
                        "leader_ignore_sigint": True,
                        "leader_ignore_sigterm": True,
                    }
                },
                {"activity": "descendant-ready"},
                {"stall": True},
            ]
        },
    )
    handle = get_adapter("scripted").spawn(
        session_id=None,
        system_prompt="Windows Job Object tracer",
        env={"TAUT_SUMMON_SCENARIO": str(scenario_path)},
    )
    assert isinstance(handle, ScriptedHandle)
    identity: tuple[int, float] | None = None
    try:
        pump = EventPump(handle)
        pump.next_of(SessionEvent)
        ready = pump.next_of(ActivityEvent)
        assert isinstance(ready, ActivityEvent)
        assert ready.description == "descendant-ready"
        descendants = psutil.Process(handle.pid).children(recursive=False)
        assert len(descendants) == 1
        identity = (descendants[0].pid, descendants[0].create_time())
        domain = cast(Any, handle._domain)
        assert domain.active_processes() >= 2

        handle.close()

        exit_event = pump.next_of(ExitEvent, timeout=12.0)
        assert isinstance(exit_event, ExitEvent)
        assert not _same_process(identity)
        assert domain.final_active_processes == 0
    finally:
        handle.close()
        if identity is not None:
            _cleanup_exact_process(identity)


@pytest.mark.skipif(os.name == "nt", reason="POSIX process-group tracer")
@pytest.mark.xdist_group("process")
def test_close_force_kills_leader_and_same_domain_descendant(
    tmp_path: Path,
) -> None:
    """[SUM-7.1]/[SUM-12] The pinned ladder reaches its SIGKILL stage."""

    pid_file = tmp_path / "forced-descendant.json"
    scenario = {
        "on_start": [
            {
                "spawn_descendant": {
                    "pid_file": str(pid_file),
                    "ignore_sigint": True,
                    "ignore_sigterm": True,
                    "leader_ignore_sigint": True,
                    "leader_ignore_sigterm": True,
                }
            }
        ]
    }
    scenario_path = _write_scenario(tmp_path, scenario)
    handle = get_adapter("scripted").spawn(
        session_id=None,
        system_prompt="forced-domain tracer",
        env={"TAUT_SUMMON_SCENARIO": str(scenario_path)},
    )
    assert isinstance(handle, ScriptedHandle)
    identity: tuple[int, float] | None = None
    try:
        pump = EventPump(handle)
        pump.next_of(SessionEvent)
        identity = _capture_process_identity(pid_file)

        handle.close()

        exit_event = pump.next_of(ExitEvent, timeout=2.0)
        assert isinstance(exit_event, ExitEvent)
        assert exit_event.returncode == -signal.SIGKILL
        assert not _same_process(identity)
    finally:
        handle.close()
        if identity is not None:
            _cleanup_exact_process(identity)


def test_unknown_event_shape_is_rejected_loudly(tmp_path: Path) -> None:
    scenario = {"on_start": [{"raw_line": '{"type": "mystery"}'}]}
    with scripted_handle(tmp_path, scenario) as handle:
        pump = EventPump(handle)
        pump.next_of(SessionEvent)

        with pytest.raises(AdapterError, match="mystery"):
            while True:
                pump.next(timeout=10.0)


def test_events_is_single_consumer(tmp_path: Path) -> None:
    scenario = {"default_response": [{"assistant_text": "echo: {text}"}]}
    with scripted_handle(tmp_path, scenario) as handle:
        iterator = handle.events()
        next(iterator)  # consume the init session event

        with pytest.raises(AdapterError, match="already"):
            next(handle.events())


def test_concurrent_injectors_never_interleave_protocol_lines(
    tmp_path: Path,
) -> None:
    # Two injector threads race 40 sends; the echo responses prove every
    # protocol line arrived whole (an interleaved partial line would fail
    # the provider's JSON parse and surface as a non-echo event or a
    # missing response).
    scenario: dict[str, Any] = {}
    per_thread = 20
    with scripted_handle(tmp_path, scenario) as handle:
        pump = EventPump(handle)

        def injector(tag: str) -> None:
            for i in range(per_thread):
                handle.inject(f"{tag}-{i}")

        threads = [
            threading.Thread(target=injector, args=(tag,), daemon=True)
            for tag in ("a", "b")
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=20.0)
            assert not t.is_alive()

        seen: set[str] = set()
        for _ in range(2 * per_thread):
            event = pump.next_of(AssistantTextEvent)
            assert isinstance(event, AssistantTextEvent)
            assert event.text.startswith("echo: ")
            seen.add(event.text.removeprefix("echo: "))
    expected = {f"{tag}-{i}" for tag in ("a", "b") for i in range(per_thread)}
    assert seen == expected
