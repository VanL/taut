"""Postgres firing tests for the shared Taut reactor contract."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import pytest
from simplebroker import Queue

import taut.watcher as watcher_module
from taut._exceptions import EmptyResultError
from taut.client import Message, Notification, TautClient
from taut.client._watching import _watch_runtime_for_client
from taut.watcher import TautWatcher

pytestmark = pytest.mark.pg_only


def _wait_until(predicate: Callable[[], bool], *, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("condition was not satisfied before timeout")


class RecordingNativeWaiter:
    """Thread-safe evidence wrapper around one real PostgreSQL waiter."""

    def __init__(self, delegate: Any, queue_names: frozenset[str]) -> None:
        self._delegate = delegate
        self.queue_names = queue_names
        self._lock = threading.Lock()
        self._true_wakes = 0
        self._close_calls = 0

    @property
    def true_wakes(self) -> int:
        with self._lock:
            return self._true_wakes

    @property
    def close_calls(self) -> int:
        with self._lock:
            return self._close_calls

    def wait(self, timeout: float | None) -> bool:
        woke = bool(self._delegate.wait(timeout))
        if woke:
            with self._lock:
                self._true_wakes += 1
        return woke

    def close(self) -> None:
        with self._lock:
            self._close_calls += 1
        self._delegate.close()


def test_taut_watcher_polls_and_refreshes_membership_without_native_waiter(
    taut_pg_project: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(taut_pg_project)
    TautClient.init()
    van = TautClient(as_name="van")
    bob = TautClient(as_name="bob")
    van.join("home")
    bob.join("home")
    try:
        van.read("home")
    except EmptyResultError:
        pass

    waiter_factory_observed = threading.Event()

    def no_native_waiter(
        _queues: Sequence[Queue],
        *,
        stop_event: threading.Event,
    ) -> None:
        del stop_event
        waiter_factory_observed.set()
        return None

    monkeypatch.setattr(
        watcher_module,
        "create_activity_waiter_for_queues",
        no_native_waiter,
    )

    seen: list[tuple[str, str, int]] = []
    observation_lock = threading.Lock()
    drive_errors: list[BaseException] = []
    ready = threading.Event()

    def record(item: Message | Notification) -> None:
        if not isinstance(item, Message):
            return
        with observation_lock:
            seen.append((item.thread, item.text, item.ts))

    def record_drive_error(args: threading.ExceptHookArgs) -> None:
        if args.exc_value is None:
            drive_errors.append(RuntimeError("drive thread exited without exception"))
        else:
            drive_errors.append(args.exc_value)

    def new_room_is_read() -> bool:
        return any(
            row.name == "new-room" and not row.unread
            for row in van.list_threads(all_threads=True)
        )

    def wait_while_drive_is_healthy(predicate: Callable[[], bool]) -> None:
        def check() -> bool:
            if drive_errors:
                raise AssertionError("watcher drive thread failed") from drive_errors[0]
            return predicate()

        _wait_until(check)

    monkeypatch.setattr(threading, "excepthook", record_drive_error)

    watcher = TautWatcher(
        _watch_runtime_for_client(van),
        van.whoami().member_id,
        record,
        membership_refresh_interval=0.05,
    )
    watcher.notify_ready_after_initial_drain(ready)
    thread = watcher.start()
    try:
        assert ready.wait(timeout=5.0), f"drive errors: {drive_errors!r}"
        assert waiter_factory_observed.wait(timeout=5.0), (
            f"drive errors: {drive_errors!r}"
        )

        van.join("new-room")
        bob.join("new-room")
        wait_while_drive_is_healthy(lambda: "new-room" in watcher.list_queues())

        written = bob.say("new-room", "polled delivery")
        expected = (written.thread, written.text, written.ts)

        def delivery_seen() -> bool:
            with observation_lock:
                return expected in seen

        wait_while_drive_is_healthy(delivery_seen)
        wait_while_drive_is_healthy(new_room_is_read)
        with pytest.raises(EmptyResultError):
            van.read("new-room")
        with observation_lock:
            assert seen.count(expected) == 1
        assert thread.is_alive()
    finally:
        watcher.stop()
        thread.join(timeout=5.0)
        van.close()
        bob.close()

    assert not thread.is_alive()
    assert drive_errors == []


def test_taut_watcher_native_waiter_rebinds_on_membership_topology_change(
    taut_pg_project: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(taut_pg_project)
    TautClient.init()
    van = TautClient(as_name="van")
    bob = TautClient(as_name="bob")
    van.join("home")
    bob.join("home")
    try:
        van.read("home")
    except EmptyResultError:
        pass

    real_create = watcher_module.create_activity_waiter_for_queues
    proxies: list[RecordingNativeWaiter] = []
    proxies_lock = threading.Lock()

    def recording_create(
        queues: Sequence[Queue],
        *,
        stop_event: threading.Event,
    ) -> RecordingNativeWaiter | None:
        delegate = real_create(queues, stop_event=stop_event)
        if delegate is None:
            return None
        proxy = RecordingNativeWaiter(
            delegate,
            frozenset(queue.name for queue in queues),
        )
        with proxies_lock:
            proxies.append(proxy)
        return proxy

    monkeypatch.setattr(
        watcher_module,
        "create_activity_waiter_for_queues",
        recording_create,
    )

    seen: list[tuple[str, str]] = []
    refresh_count = 0
    observation_lock = threading.Lock()
    new_room_wake_floor = 0
    new_room_native_before_handler: list[bool] = []
    home_native_before_handler: list[bool] = []
    drive_errors: list[BaseException] = []
    watcher: TautWatcher

    def handle(item: Message | Notification) -> None:
        nonlocal refresh_count
        if not isinstance(item, Message):
            return
        with proxies_lock:
            proxy_snapshot = list(proxies)
        if item.text == "native-wake":
            current_proxy = proxy_snapshot[-1]
            new_room_native_before_handler.append(
                "new-room" in current_proxy.queue_names
                and current_proxy.true_wakes > new_room_wake_floor
            )
        if item.text == "remaining-wake":
            current_proxy = proxy_snapshot[-1]
            home_native_before_handler.append(
                "new-room" not in current_proxy.queue_names
                and current_proxy.true_wakes > 0
            )
        with observation_lock:
            seen.append((item.thread, item.text))
        if item.thread == "home" and item.text.startswith("refresh"):
            watcher._refresh_memberships()
            with observation_lock:
                refresh_count += 1

    def record_drive_error(args: threading.ExceptHookArgs) -> None:
        if args.exc_value is None:
            drive_errors.append(RuntimeError("drive thread exited without exception"))
        else:
            drive_errors.append(args.exc_value)

    monkeypatch.setattr(threading, "excepthook", record_drive_error)

    watcher = TautWatcher(
        _watch_runtime_for_client(van),
        van.whoami().member_id,
        handle,
        membership_refresh_interval=60.0,
    )
    thread = watcher.start()
    try:
        _wait_until(thread.is_alive)
        _wait_until(lambda: len(proxies) == 1)
        initial_proxy = proxies[0]
        assert "home" in initial_proxy.queue_names
        assert "new-room" not in initial_proxy.queue_names

        van.join("new-room")
        bob.join("new-room")
        bob.say("home", "refresh-add")
        _wait_until(lambda: refresh_count >= 1)
        _wait_until(lambda: "new-room" in watcher.list_queues())
        _wait_until(lambda: len(proxies) >= 2 and initial_proxy.close_calls == 1)
        add_proxy = proxies[-1]
        assert "new-room" in add_proxy.queue_names

        new_room_wake_floor = add_proxy.true_wakes
        bob.say("new-room", "native-wake")
        _wait_until(lambda: ("new-room", "native-wake") in seen, timeout=3.0)
        assert new_room_native_before_handler == [True]

        van.leave("new-room")
        bob.say("home", "refresh-remove")
        _wait_until(lambda: refresh_count >= 2)
        _wait_until(lambda: "new-room" not in watcher.list_queues())
        _wait_until(lambda: len(proxies) >= 3 and add_proxy.close_calls == 1)
        remaining_proxy = proxies[-1]
        assert "home" in remaining_proxy.queue_names
        assert "new-room" not in remaining_proxy.queue_names
        assert remaining_proxy.close_calls == 0

        removed_baseline = remaining_proxy.true_wakes
        bob.say("new-room", "removed-no-wake")
        time.sleep(0.2)
        assert remaining_proxy.true_wakes == removed_baseline
        with observation_lock:
            assert ("new-room", "removed-no-wake") not in seen

        bob.say("home", "remaining-wake")
        _wait_until(lambda: ("home", "remaining-wake") in seen)
        assert remaining_proxy.true_wakes > removed_baseline
        assert home_native_before_handler == [True]
    finally:
        watcher.stop()
        thread.join(timeout=5.0)
        van.close()
        bob.close()

    assert not thread.is_alive()
    assert drive_errors == []
    assert len(proxies) == 3
    assert [proxy.close_calls for proxy in proxies] == [1, 1, 1]
