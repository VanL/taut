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
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

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


def test_registry_knows_scripted_and_rejects_unknown_names() -> None:
    assert "scripted" in adapter_names()
    adapter = get_adapter("scripted")
    assert adapter.supports_terminal_mode is True
    assert adapter.supports_attach is False
    assert adapter.orientation_via_inject is False

    with pytest.raises(UnknownAdapterError, match="scripted"):
        get_adapter("nope")


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


def test_close_reaps_the_child_process(tmp_path: Path) -> None:
    scenario = {"default_response": [{"assistant_text": "echo: {text}"}]}
    with scripted_handle(tmp_path, scenario) as handle:
        pump = EventPump(handle)
        pump.next_of(SessionEvent)
        child_pid = handle.pid

    # close() ran on context exit: the child must be terminated AND reaped
    # (a zombie would still answer kill(pid, 0)).
    with pytest.raises(ProcessLookupError):
        os.kill(child_pid, 0)


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
