"""Adapter-interface tests against the real scripted provider subprocess.

Contract under test: docs/specs/04-summon.md [SUM-7.1] (spawn / inject /
events / interrupt, the closed ``AdapterEvent`` union, synchronous inject
failure, interrupt unblocking an in-flight inject) and [SUM-7.2] (the
``scripted`` adapter ships in the package).

Anti-mocking posture ([SUM-12]): every test spawns the real scripted
provider program as a child process and speaks to it over real pipes with
real stream-json framing. Only the model is fake.
"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, cast

import psutil
import pytest
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


class _ReentrantInterruptProcess:
    """Popen-shaped boundary fake for deterministic signal reentry."""

    pid = 12345

    def __init__(self) -> None:
        self.stdin = _CountingStream()
        self.stdout = _CountingStream()
        self.returncode: int | None = None
        self.signal_calls = 0
        self.on_first_signal: Callable[[], None] | None = None

    def poll(self) -> int | None:
        return self.returncode

    def send_signal(self, _signum: int) -> None:
        self.signal_calls += 1
        self.returncode = 0
        if self.signal_calls == 1 and self.on_first_signal is not None:
            self.on_first_signal()

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
        except Exception as exc:  # noqa: BLE001 - relayed to the test thread
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
    handle = ScriptedHandle(cast(Any, proc), session_id=None)

    handle.wait_until_quiet()
    handle.mark_awaiting_onboarding()
    with pytest.raises(AdapterError, match="does not support terminal attach"):
        handle.attach(wake=threading.Event(), shutdown=threading.Event())

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

        assert seen == flood_size


def test_interrupt_unblocks_blocked_inject(tmp_path: Path) -> None:
    # The provider announces its session and then stops reading stdin, so
    # a large inject fills the real pipe and blocks; interrupt() must
    # unblock it ([SUM-7.1], the [SUM-9] stuck-harness dependency).
    scenario = {"on_start": [{"stall": True}]}
    with scripted_handle(tmp_path, scenario) as handle:
        pump = EventPump(handle)
        pump.next_of(SessionEvent)

        failures: list[Exception] = []
        blocked = threading.Event()

        def blocked_inject() -> None:
            blocked.set()
            try:
                handle.inject("x" * 8_000_000)
            except Exception as exc:  # noqa: BLE001 - inspected below
                failures.append(exc)

        injector = threading.Thread(target=blocked_inject, daemon=True)
        injector.start()
        assert blocked.wait(timeout=5.0)
        time.sleep(0.5)  # let the write reach the full-pipe block
        assert injector.is_alive(), "inject did not block on the stalled harness"

        handle.interrupt()

        injector.join(timeout=10.0)
        assert not injector.is_alive(), "interrupt left inject blocked"
        assert len(failures) == 1
        assert isinstance(failures[0], AdapterError)

        exit_event = pump.next_of(ExitEvent)
        assert isinstance(exit_event, ExitEvent)


def test_inject_refuses_after_close_publishes_closing() -> None:
    proc = _BlockingCloseProcess()
    handle = ScriptedHandle(cast(Any, proc), session_id=None)
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
    handle = ScriptedHandle(cast(Any, proc), session_id=None)
    gate = _BlockingInjectLock()
    handle._inject_lock = cast(Any, gate)  # noqa: SLF001 - lifecycle race seam
    failures: list[BaseException] = []

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

    assert not injector.is_alive()
    assert not closer.is_alive()
    assert len(failures) == 1
    assert isinstance(failures[0], AdapterError)
    assert "closing" in str(failures[0])
    assert proc.stdin.writes == []
    assert proc.stdin.flush_calls == 0


def test_interrupt_can_reenter_close_while_lifecycle_state_is_owned() -> None:
    proc = _ReentrantInterruptProcess()
    handle = ScriptedHandle(cast(Any, proc), session_id=None)
    proc.on_first_signal = handle.interrupt
    failures: list[BaseException] = []

    def close() -> None:
        try:
            handle.close()
        except BaseException as exc:  # noqa: BLE001 - asserted below
            failures.append(exc)

    closer = threading.Thread(target=close, daemon=True)
    closer.start()
    closer.join(timeout=1.0)

    assert not closer.is_alive(), "same-thread interrupt reentry deadlocked close"
    assert failures == []


def test_interrupt_can_reenter_close_during_process_wait() -> None:
    proc = _InterruptDuringWaitProcess()
    handle = ScriptedHandle(cast(Any, proc), session_id=None)
    proc.on_wait = handle.interrupt
    failures: list[BaseException] = []

    def close() -> None:
        try:
            handle.close()
        except BaseException as exc:  # noqa: BLE001 - asserted below
            failures.append(exc)

    closer = threading.Thread(target=close, daemon=True)
    closer.start()
    closer.join(timeout=1.0)

    assert not closer.is_alive(), "same-thread interrupt reentry deadlocked wait"
    assert failures == []
    assert proc.signal_calls == 2


def test_real_second_sigint_returns_while_close_waits() -> None:
    runner = """
import os
import signal
import subprocess
import sys
import threading
import time
from taut_summon._scripted import ScriptedHandle

provider = subprocess.Popen(
    [
        sys.executable,
        "-c",
        "import signal,time; signal.signal(signal.SIGINT, signal.SIG_IGN); print('ready', flush=True); time.sleep(0.5)",
    ],
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    text=True,
)
assert provider.stdout is not None
assert provider.stdout.readline().strip() == "ready"
handle = ScriptedHandle(provider, session_id=None)
signal.signal(signal.SIGINT, lambda _signum, _frame: handle.interrupt())
os.kill(os.getpid(), signal.SIGINT)
threading.Thread(
    target=lambda: (time.sleep(0.1), os.kill(os.getpid(), signal.SIGINT)),
    daemon=True,
).start()
handle.close()
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
    handle = ScriptedHandle(cast(Any, proc), session_id=None)
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
    proc.release_wait.set()
    first.join(timeout=2.0)
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
    handle = ScriptedHandle(cast(Any, proc), session_id=None)

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
    handle = ScriptedHandle(cast(Any, proc), session_id=None)
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
