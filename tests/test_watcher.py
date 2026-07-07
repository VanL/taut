from __future__ import annotations

import logging
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Sequence
from functools import partial
from pathlib import Path
from typing import Any, TypeVar

import psutil
import pytest
from simplebroker import Queue

from taut._exceptions import EmptyResultError, MembershipError
from taut.client import Message, Notification, TautClient
from taut.client._watching import _watch_runtime_for_client
from taut.watcher import (
    MultiQueueWatcher,
    QueueMessageContext,
    QueueRuntimeConfig,
    TautWatcher,
)
from tests.conftest import run_cli

pytestmark = pytest.mark.sqlite_only

_TautWatcherT = TypeVar("_TautWatcherT", bound=TautWatcher)


def _wait_until(predicate: Callable[[], bool], *, timeout: float = 3.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("condition was not satisfied before timeout")


def _spawn_cli(cwd: Path, *args: object) -> subprocess.Popen[str]:
    return subprocess.Popen(
        [sys.executable, "-m", "taut", *map(str, args)],
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def _record_message_texts(seen: list[str]) -> Callable[[Message | Notification], None]:
    def record(item: Message | Notification) -> None:
        if isinstance(item, Message):
            seen.append(item.text)

    return record


def _record_message_threads(
    seen: list[tuple[str, str]],
) -> Callable[[Message | Notification], None]:
    def record(item: Message | Notification) -> None:
        if isinstance(item, Message):
            seen.append((item.thread, item.text))

    return record


def _record_message_timestamps(
    seen: list[int],
) -> Callable[[Message | Notification], None]:
    def record(item: Message | Notification) -> None:
        if isinstance(item, Message):
            seen.append(item.ts)

    return record


def _drain_unread(client: TautClient, thread: str | None = None) -> None:
    try:
        client.read(thread)
    except EmptyResultError:
        pass


def _thread_is_read(client: TautClient, thread: str) -> bool:
    for item in client.list_threads(all_threads=True):
        if item.name == thread:
            return not item.unread
    return False


class FakeWaiter:
    def __init__(self) -> None:
        self.wait_calls: list[float | None] = []
        self.close_calls = 0

    def wait(self, timeout: float | None) -> bool:
        self.wait_calls.append(timeout)
        return False

    def close(self) -> None:
        self.close_calls += 1


def test_multi_queue_watcher_uses_base_retry_loop() -> None:
    assert "_run_with_retries" not in MultiQueueWatcher.__dict__


def test_start_strategy_uses_multi_queue_activity_waiter(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    received: dict[str, Any] = {}
    fake_waiter = FakeWaiter()

    def handler(
        _message: str,
        _timestamp: int,
        _context: QueueMessageContext,
    ) -> None:
        pass

    def fake_create(
        queues: Sequence[Any],
        *,
        stop_event: threading.Event,
    ) -> FakeWaiter:
        received["queues"] = list(queues)
        received["stop_event"] = stop_event
        return fake_waiter

    monkeypatch.setattr(
        "taut.watcher.create_activity_waiter_for_queues",
        fake_create,
    )

    watcher = MultiQueueWatcher(
        queue_configs={
            "strategy.one": {"handler": handler},
            "strategy.two": {"handler": handler},
        },
        db=tmp_path / ".taut.db",
    )

    try:
        watcher._start_strategy()

        assert [queue.name for queue in received["queues"]] == [
            "strategy.one",
            "strategy.two",
        ]
        assert watcher._strategy.uses_native_activity() is True
        assert (
            watcher._strategy.detach_activity_waiter(
                expected=fake_waiter,
            )
            is fake_waiter
        )
        assert fake_waiter.close_calls == 0
    finally:
        watcher.stop(join=False)


def test_reset_multi_activity_waiter_detaches_strategy_waiter(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_waiter = FakeWaiter()

    def handler(
        _message: str,
        _timestamp: int,
        _context: QueueMessageContext,
    ) -> None:
        pass

    def fake_create(
        _queues: Sequence[Any],
        *,
        stop_event: threading.Event,
    ) -> FakeWaiter:
        del stop_event
        return fake_waiter

    monkeypatch.setattr(
        "taut.watcher.create_activity_waiter_for_queues",
        fake_create,
    )

    watcher = MultiQueueWatcher(
        queue_configs={"reset.one": {"handler": handler}},
        db=tmp_path / ".taut.db",
    )

    try:
        watcher._start_strategy()
        assert watcher._strategy.uses_native_activity() is True

        watcher._reset_multi_activity_waiter()

        assert fake_waiter.close_calls == 1
        assert watcher._strategy.uses_native_activity() is False
    finally:
        watcher.stop(join=False)


def _white_box_watcher_cls(
    watcher_cls: type[_TautWatcherT],
    client: TautClient,
    handler: Callable[[Message | Notification], None],
    *,
    threads: list[str] | None = None,
    membership_refresh_interval: float = 0.05,
) -> _TautWatcherT:
    """Build watcher tests through the internal runtime seam.

    These tests need constructor knobs and internal counters that the public
    `TautClient.watch()` API intentionally does not expose.
    """

    return watcher_cls(
        _watch_runtime_for_client(client),
        client.whoami().member_id,
        handler,
        threads=threads,
        membership_refresh_interval=membership_refresh_interval,
    )


def _white_box_watcher(
    client: TautClient,
    handler: Callable[[Message | Notification], None],
    *,
    threads: list[str] | None = None,
    membership_refresh_interval: float = 0.05,
) -> TautWatcher:
    return _white_box_watcher_cls(
        TautWatcher,
        client,
        handler,
        threads=threads,
        membership_refresh_interval=membership_refresh_interval,
    )


def test_explicit_watch_filter_drops_left_thread_on_refresh(tmp_path: Path) -> None:
    TautClient.init(db_path=tmp_path / ".taut.db")
    client = TautClient(db_path=tmp_path / ".taut.db", as_name="van")
    client.join("foo")
    client.join("bar")
    watcher = client.watch(lambda _message: None, threads=["foo", "bar"])
    watcher._failures[("foo", 1)] = 2

    client.leave("foo")
    watcher._refresh_memberships()

    assert watcher.list_queues() == ["bar"]
    assert ("foo", 1) not in watcher._failures
    watcher.stop()


def test_client_watch_filter_delivers_selected_threads_only(tmp_path: Path) -> None:
    TautClient.init(db_path=tmp_path / ".taut.db")
    van = TautClient(db_path=tmp_path / ".taut.db", as_name="van")
    bob = TautClient(db_path=tmp_path / ".taut.db", as_name="bob")
    van.join("foo")
    van.join("bar")
    bob.join("foo")
    bob.join("bar")
    _drain_unread(van)
    seen: list[tuple[str, str]] = []
    watcher = van.watch(_record_message_threads(seen), threads=["bar"])
    thread = watcher.start()
    try:
        _wait_until(thread.is_alive)

        bob.say("foo", "hidden")
        bob.say("bar", "visible")

        _wait_until(lambda: ("bar", "visible") in seen)
        assert ("foo", "hidden") not in seen
        _wait_until(lambda: _thread_is_read(van, "bar"))
        with pytest.raises(EmptyResultError):
            van.read("bar")
        assert [message.text for message in van.read("foo")] == ["hidden"]
    finally:
        watcher.stop()
        thread.join(timeout=2)
        assert not thread.is_alive()


def test_live_watch_filter_drops_left_thread_without_killing_watcher(
    tmp_path: Path,
) -> None:
    TautClient.init(db_path=tmp_path / ".taut.db")
    van = TautClient(db_path=tmp_path / ".taut.db", as_name="van")
    bob = TautClient(db_path=tmp_path / ".taut.db", as_name="bob")
    van.join("foo")
    van.join("bar")
    bob.join("foo")
    bob.join("bar")
    van.read("foo")
    van.read("bar")
    seen: list[tuple[str, str]] = []
    watcher = _white_box_watcher(
        van,
        _record_message_threads(seen),
        threads=["foo", "bar"],
        membership_refresh_interval=0.05,
    )
    thread = watcher.start()
    try:
        _wait_until(thread.is_alive)

        van.leave("foo")
        _wait_until(lambda: watcher.list_queues() == ["bar"])

        bob.say("foo", "should not display")
        bob.say("bar", "still watching")

        _wait_until(lambda: ("bar", "still watching") in seen)
        assert ("foo", "should not display") not in seen
        _wait_until(lambda: _thread_is_read(van, "bar"))
        with pytest.raises(EmptyResultError):
            van.read("bar")
        assert thread.is_alive()
    finally:
        watcher.stop()
        thread.join(timeout=2)
        assert not thread.is_alive()


def test_live_watcher_receives_message_from_cli_subprocess(tmp_path: Path) -> None:
    TautClient.init(db_path=tmp_path / ".taut.db")
    bob = TautClient(db_path=tmp_path / ".taut.db", as_name="bob")
    van = TautClient(db_path=tmp_path / ".taut.db", as_name="van")
    bob.join("foo")
    van.join("foo")
    seen: list[str] = []
    watcher = van.watch(_record_message_texts(seen))
    thread = watcher.start()
    try:
        _wait_until(thread.is_alive)

        rc, _out, err = run_cli(
            "--as",
            "bob",
            "say",
            "foo",
            "from subprocess",
            cwd=tmp_path,
        )

        assert rc == 0, err
        _wait_until(lambda: "from subprocess" in seen)
        assert thread.is_alive()
    finally:
        watcher.stop()
        thread.join(timeout=2)
        assert not thread.is_alive()


def test_concurrent_writer_processes_persist_all_messages(
    tmp_path: Path,
) -> None:
    TautClient.init(db_path=tmp_path / ".taut.db")
    van = TautClient(db_path=tmp_path / ".taut.db", as_name="van")
    van.join("foo")
    for name in ("bob", "codex"):
        TautClient(db_path=tmp_path / ".taut.db", as_name=name).join("foo")

    target_texts = {"from bob", "from codex"}
    processes = [
        _spawn_cli(tmp_path, "--as", "bob", "say", "foo", "from bob"),
        _spawn_cli(tmp_path, "--as", "codex", "say", "foo", "from codex"),
    ]
    try:
        for process in processes:
            stdout, stderr = process.communicate(timeout=8)
            assert process.returncode == 0, stdout + stderr
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()

    messages = [message for message in van.log("foo") if message.text in target_texts]

    assert {message.text for message in messages} == target_texts
    assert {message.from_name for message in messages} == {"bob", "codex"}
    assert [message.ts for message in messages] == sorted(
        message.ts for message in messages
    )


def test_live_watcher_picks_up_mid_watch_join_via_add_queue(tmp_path: Path) -> None:
    TautClient.init(db_path=tmp_path / ".taut.db")
    van = TautClient(db_path=tmp_path / ".taut.db", as_name="van")
    bob = TautClient(db_path=tmp_path / ".taut.db", as_name="bob")
    van.join("foo")
    bob.join("foo")
    seen: list[tuple[str, str]] = []
    watcher = _white_box_watcher(
        van,
        _record_message_threads(seen),
        membership_refresh_interval=0.05,
    )
    thread = watcher.start()
    try:
        _wait_until(thread.is_alive)

        van.join("bar")
        bob.join("bar")
        bob.say("bar", "new room")

        _wait_until(lambda: "bar" in watcher.list_queues())
        _wait_until(lambda: ("bar", "new room") in seen)
        assert "foo" in watcher.list_queues()
    finally:
        watcher.stop()
        thread.join(timeout=2)
        assert not thread.is_alive()


def test_idle_peek_queue_does_not_busy_fetch_after_cursor_advance(
    tmp_path: Path,
) -> None:
    TautClient.init(db_path=tmp_path / ".taut.db")
    van = TautClient(db_path=tmp_path / ".taut.db", as_name="van")
    van.join("foo")
    seen: list[int] = []

    class CountingWatcher(TautWatcher):
        pending_checks = 0
        fetches = 0

        def _queue_has_pending(self, queue: Any) -> bool:
            self.pending_checks += 1
            return super()._queue_has_pending(queue)

        def _fetch_next_message(
            self,
            config: QueueRuntimeConfig,
        ) -> tuple[str, int] | None:
            self.fetches += 1
            return super()._fetch_next_message(config)

    watcher = _white_box_watcher_cls(
        CountingWatcher,
        van,
        _record_message_timestamps(seen),
        membership_refresh_interval=60.0,
    )
    try:
        message = van.say("foo", "once")

        watcher._drain_queue()
        assert seen == [message.ts]
        fetches_after_message = watcher.fetches
        pending_checks_after_message = watcher.pending_checks

        for _ in range(5):
            watcher._drain_queue()

        assert watcher.fetches == fetches_after_message
        assert watcher.pending_checks <= pending_checks_after_message + 5
    finally:
        watcher.stop()


def test_live_watcher_drop_to_zero_then_rejoin_continues(tmp_path: Path) -> None:
    TautClient.init(db_path=tmp_path / ".taut.db")
    van = TautClient(db_path=tmp_path / ".taut.db", as_name="van")
    bob = TautClient(db_path=tmp_path / ".taut.db", as_name="bob")
    van.join("foo")
    seen: list[tuple[str, str]] = []
    watcher = _white_box_watcher(
        van,
        _record_message_threads(seen),
        membership_refresh_interval=0.05,
    )
    thread = watcher.start()
    try:
        _wait_until(thread.is_alive)

        van.leave("foo")
        _wait_until(lambda: watcher.list_queues() == [])
        van.join("bar")
        bob.join("bar")
        bob.say("bar", "after rejoin")

        _wait_until(lambda: ("bar", "after rejoin") in seen)
        assert thread.is_alive()
    finally:
        watcher.stop()
        thread.join(timeout=2)
        assert not thread.is_alive()


def test_watcher_membership_refresh_timer_counts_as_pending(tmp_path: Path) -> None:
    TautClient.init(db_path=tmp_path / ".taut.db")
    client = TautClient(db_path=tmp_path / ".taut.db", as_name="van")
    client.join("foo")
    watcher = _white_box_watcher(
        client,
        lambda _message: None,
        membership_refresh_interval=60.0,
    )
    try:
        watcher._next_membership_refresh_at = time.monotonic() - 1

        assert watcher._has_pending_messages()
    finally:
        watcher.stop()


def test_live_watcher_does_not_redispatch_after_cursor_advance(
    tmp_path: Path,
) -> None:
    TautClient.init(db_path=tmp_path / ".taut.db")
    van = TautClient(db_path=tmp_path / ".taut.db", as_name="van")
    bob = TautClient(db_path=tmp_path / ".taut.db", as_name="bob")
    van.join("foo")
    bob.join("foo")
    _drain_unread(van, "foo")
    seen: list[int] = []
    watcher = van.watch(_record_message_timestamps(seen))
    thread = watcher.start()
    try:
        _wait_until(thread.is_alive)

        message = bob.say("foo", "once")
        _wait_until(lambda: seen.count(message.ts) == 1)
        _wait_until(lambda: _thread_is_read(van, "foo"))

        assert seen.count(message.ts) == 1
        with pytest.raises(EmptyResultError):
            van.list_threads()
    finally:
        watcher.stop()
        thread.join(timeout=2)
        assert not thread.is_alive()


def test_watcher_poison_message_advances_after_three_failures(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    TautClient.init(db_path=tmp_path / ".taut.db")
    client = TautClient(db_path=tmp_path / ".taut.db", as_name="van")
    client.join("foo")
    attempts: list[int] = []
    caplog.set_level(logging.WARNING, logger="taut.watcher")

    def fail(item: Message | Notification) -> None:
        if not isinstance(item, Message):
            return
        attempts.append(item.ts)
        raise RuntimeError("boom")

    watcher = _white_box_watcher(
        client,
        fail,
        membership_refresh_interval=0.05,
    )
    thread = watcher.start()
    try:
        _wait_until(thread.is_alive)

        message = client.say("foo", "poison")
        failure_key = (message.thread, message.ts)

        def poison_message_advanced() -> bool:
            if attempts.count(message.ts) != 3 or failure_key in watcher._failures:
                return False
            try:
                client.list_threads()
            except EmptyResultError:
                return True
            return False

        _wait_until(poison_message_advanced)

        assert attempts.count(message.ts) == 3
        assert failure_key not in watcher._failures
        with pytest.raises(EmptyResultError):
            client.list_threads()
        assert thread.is_alive()
        assert f"advancing past poison message {message.ts} in foo" in caplog.text
    finally:
        watcher.stop()
        thread.join(timeout=2)
        assert not thread.is_alive()


def test_watcher_claims_mention_notification_without_consuming_chat(
    tmp_path: Path,
) -> None:
    TautClient.init(db_path=tmp_path / ".taut.db")
    van = TautClient(db_path=tmp_path / ".taut.db", as_name="van")
    bob = TautClient(db_path=tmp_path / ".taut.db", as_name="bob")
    van.join("foo")
    bob.join("foo")
    seen_notifications: list[Notification] = []
    seen_messages: list[Message] = []

    def collect(item: Message | Notification) -> None:
        if isinstance(item, Notification):
            seen_notifications.append(item)
        if isinstance(item, Message):
            seen_messages.append(item)

    watcher = bob.watch(collect, threads=["foo"])
    thread = watcher.start()
    try:
        _wait_until(thread.is_alive)

        written = van.say("foo", "hello @bob")

        _wait_until(
            lambda: any(item.message_ts == written.ts for item in seen_notifications)
        )
        _wait_until(lambda: any(item.ts == written.ts for item in seen_messages))
        with pytest.raises(EmptyResultError):
            bob.inbox()
        assert "hello @bob" in [message.text for message in bob.log("foo")]
    finally:
        watcher.stop()
        thread.join(timeout=2)
        assert not thread.is_alive()


def test_taut_watcher_client_constructor_warns_and_still_works(
    tmp_path: Path,
) -> None:
    TautClient.init(db_path=tmp_path / ".taut.db")
    client = TautClient(db_path=tmp_path / ".taut.db", as_name="van")
    client.join("foo")

    with pytest.warns(DeprecationWarning, match=r"TautWatcher\(client,"):
        watcher = TautWatcher(
            client,
            client.whoami().member_id,
            lambda _message: None,
        )
    try:
        assert watcher.list_queues() == ["foo"]
    finally:
        watcher.stop()


def _make_recording_handler(
    name: str,
    seen: list[tuple[str, str]],
) -> Callable[[str, int, QueueMessageContext], None]:
    def handler(
        message: str,
        _timestamp: int,
        _context: QueueMessageContext,
    ) -> None:
        seen.append((name, message))

    return handler


def test_multi_queue_watcher_remove_first_queue_keeps_data_version_polling(
    tmp_path: Path,
) -> None:
    """Removing the first configured queue must not close the shared
    data-version queue (BaseWatcher._queue_obj) — see the vendor-header
    deviation note in taut/watcher.py."""
    seen: list[tuple[str, str]] = []
    watcher = MultiQueueWatcher(
        queue_configs={
            "guard.first": {"handler": _make_recording_handler("guard.first", seen)},
            "guard.second": {"handler": _make_recording_handler("guard.second", seen)},
        },
        db=tmp_path / ".taut.db",
    )
    thread = None
    try:
        first = watcher.get_queue("guard.first")
        assert first is not None
        # White-box: the first configured queue IS BaseWatcher's shared
        # data-version queue — the exact object remove_queue must not close.
        assert first is watcher._get_queue_for_data_version()

        watcher.remove_queue("guard.first")

        # White-box (labeled): dispatch alone can be masked by the live
        # multi-queue activity waiter, so pin data-version polling directly:
        # the shared first queue must still answer get_data_version().
        assert isinstance(watcher._get_queue_for_data_version().get_data_version(), int)
        # White-box (labeled): Queue.close() detaches the finalizer; a live
        # finalizer proves the data-version queue was not closed.
        assert first._finalizer.alive

        thread = watcher.start()
        _wait_until(thread.is_alive)

        with Queue("guard.second", db_path=str(tmp_path / ".taut.db")) as writer:
            writer.write("still alive")

        _wait_until(lambda: ("guard.second", "still alive") in seen)
        assert not any(name == "guard.first" for name, _ in seen)
    finally:
        watcher.stop()
        if thread is not None:
            thread.join(timeout=2)
            assert not thread.is_alive()


def test_multi_queue_watcher_remove_non_data_version_queue_closes_it(
    tmp_path: Path,
) -> None:
    seen: list[tuple[str, str]] = []
    watcher = MultiQueueWatcher(
        queue_configs={
            "close.first": {"handler": _make_recording_handler("close.first", seen)},
            "close.second": {"handler": _make_recording_handler("close.second", seen)},
        },
        db=tmp_path / ".taut.db",
    )
    thread = None
    try:
        second = watcher.get_queue("close.second")
        assert second is not None
        assert second is not watcher._get_queue_for_data_version()

        watcher.remove_queue("close.second")

        # White-box (labeled): Queue.close() detaches the finalizer, so a
        # dead finalizer is the deterministic "this queue was closed" signal.
        assert second._finalizer.alive is False
        # The shared data-version queue is untouched by the close.
        assert isinstance(watcher._get_queue_for_data_version().get_data_version(), int)

        thread = watcher.start()
        _wait_until(thread.is_alive)

        with Queue("close.first", db_path=str(tmp_path / ".taut.db")) as writer:
            writer.write("first still watched")

        _wait_until(lambda: ("close.first", "first still watched") in seen)
    finally:
        watcher.stop()
        if thread is not None:
            thread.join(timeout=2)
            assert not thread.is_alive()


def test_watch_filter_naming_unjoined_thread_raises_membership_error(
    tmp_path: Path,
) -> None:
    TautClient.init(db_path=tmp_path / ".taut.db")
    client = TautClient(db_path=tmp_path / ".taut.db", as_name="van")
    client.join("foo")

    with pytest.raises(MembershipError, match="ghost"):
        client.watch(lambda _item: None, threads=["foo", "ghost"])


def _open_db_handle_count(db_path: Path) -> int | None:
    """Count this process's open file handles on the taut db (plus -wal/-shm).

    Returns None where psutil cannot enumerate open files reliably.
    """
    prefix = str(db_path.resolve())
    try:
        open_files = psutil.Process().open_files()
    except (psutil.Error, NotImplementedError, OSError):
        return None
    return sum(1 for item in open_files if item.path.startswith(prefix))


def test_taut_watcher_membership_churn_does_not_leak_db_handles(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / ".taut.db"
    TautClient.init(db_path=db_path)
    van = TautClient(db_path=db_path, as_name="van")
    bob = TautClient(db_path=db_path, as_name="bob")
    van.join("home")
    bob.join("home")
    seen: list[tuple[str, str]] = []
    watcher = _white_box_watcher(
        van,
        _record_message_threads(seen),
        membership_refresh_interval=0.05,
    )
    thread = watcher.start()
    handles_observable = _open_db_handle_count(db_path) is not None
    handle_counts: list[int] = []

    def queue_listed(name: str) -> bool:
        return name in watcher.list_queues()

    def queue_absent(name: str) -> bool:
        return name not in watcher.list_queues()

    try:
        _wait_until(thread.is_alive)

        for cycle in range(10):
            name = f"churn{cycle}"
            van.join(name)
            _wait_until(partial(queue_listed, name))
            van.leave(name)
            _wait_until(partial(queue_absent, name))
            if handles_observable:
                count = _open_db_handle_count(db_path)
                assert count is not None
                handle_counts.append(count)

        # Functional assertion — unconditional on every platform: the
        # watcher still delivers messages after ten join/leave cycles.
        bob.say("home", "after churn")
        _wait_until(lambda: ("home", "after churn") in seen)

        if handles_observable:
            # A per-cycle connection leak would grow the handle count
            # monotonically with cycle count (~+1 per cycle); a bounded
            # watcher stays flat.  Platform-skip: on platforms where
            # psutil.Process().open_files() is unavailable or unreliable
            # this block is skipped and the MultiQueueWatcher close
            # assertions above carry the close-on-remove proof.
            assert handle_counts[-1] - handle_counts[0] <= 2, handle_counts
    finally:
        watcher.stop()
        thread.join(timeout=2)
        assert not thread.is_alive()


def test_watcher_runs_with_no_chat_threads_for_notification_inbox(
    tmp_path: Path,
) -> None:
    TautClient.init(db_path=tmp_path / ".taut.db")
    bob = TautClient(db_path=tmp_path / ".taut.db", as_name="bob")
    bob.join("scratch")
    bob.leave("scratch")
    van = TautClient(db_path=tmp_path / ".taut.db", as_name="van")
    van.join("foo")
    seen: list[Notification] = []

    def collect(item: Message | Notification) -> None:
        if isinstance(item, Notification):
            seen.append(item)

    watcher = bob.watch(collect)
    thread = watcher.start()
    try:
        _wait_until(thread.is_alive)

        written = van.say("foo", "ping @bob")

        _wait_until(lambda: any(item.message_ts == written.ts for item in seen))
        assert thread.is_alive()
    finally:
        watcher.stop()
        thread.join(timeout=2)
        assert not thread.is_alive()
