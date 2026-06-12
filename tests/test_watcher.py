from __future__ import annotations

import time
from collections.abc import Callable

import taut.schema as schema
from taut.client import TautClient
from taut.watcher import TautWatcher
from tests.conftest import run_cli


def _wait_until(predicate: Callable[[], bool], *, timeout: float = 3.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("condition was not satisfied before timeout")


def test_explicit_watch_filter_drops_left_thread_on_refresh(tmp_path) -> None:
    TautClient.init(db_path=tmp_path / ".taut.db")
    client = TautClient(db_path=tmp_path / ".taut.db", as_handle="van")
    client.join("foo")
    client.join("bar")
    watcher = client.watch(lambda _message: None, threads=["foo", "bar"])
    watcher._failures[("foo", 1)] = 2

    client.leave("foo")
    watcher._refresh_memberships()

    assert watcher.list_queues() == ["bar"]
    assert ("foo", 1) not in watcher._failures
    watcher.stop()


def test_live_watch_filter_drops_left_thread_without_killing_watcher(tmp_path) -> None:
    TautClient.init(db_path=tmp_path / ".taut.db")
    van = TautClient(db_path=tmp_path / ".taut.db", as_handle="van")
    bob = TautClient(db_path=tmp_path / ".taut.db", as_handle="bob")
    van.join("foo")
    van.join("bar")
    bob.join("foo")
    van.read("foo")
    seen: list[tuple[str, str]] = []
    watcher = TautWatcher(
        van,
        "van",
        lambda message: seen.append((message.thread, message.text)),
        threads=["foo", "bar"],
        membership_refresh_interval=0.05,
    )
    thread = watcher.start()
    try:
        _wait_until(thread.is_alive)

        van.leave("foo")
        _wait_until(lambda: watcher.list_queues() == ["bar"])

        bob.say("foo", "should not display")
        visible = van.say("bar", "still watching")

        _wait_until(lambda: ("bar", "still watching") in seen)
        assert ("foo", "should not display") not in seen
        membership = schema.get_membership(
            van._meta_queue,
            thread="bar",
            member="van",
        )
        assert membership is not None
        assert membership["last_seen_ts"] >= visible.ts
        assert thread.is_alive()
    finally:
        watcher.stop()
        thread.join(timeout=2)
        assert not thread.is_alive()


def test_live_watcher_receives_message_from_cli_subprocess(tmp_path) -> None:
    TautClient.init(db_path=tmp_path / ".taut.db")
    bob = TautClient(db_path=tmp_path / ".taut.db", as_handle="bob")
    van = TautClient(db_path=tmp_path / ".taut.db", as_handle="van")
    bob.join("foo")
    van.join("foo")
    seen: list[str] = []
    watcher = TautWatcher(
        van,
        "van",
        lambda message: seen.append(message.text),
        membership_refresh_interval=0.05,
    )
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


def test_live_watcher_drop_to_zero_then_rejoin_continues(tmp_path) -> None:
    TautClient.init(db_path=tmp_path / ".taut.db")
    van = TautClient(db_path=tmp_path / ".taut.db", as_handle="van")
    bob = TautClient(db_path=tmp_path / ".taut.db", as_handle="bob")
    van.join("foo")
    seen: list[tuple[str, str]] = []
    watcher = TautWatcher(
        van,
        "van",
        lambda message: seen.append((message.thread, message.text)),
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


def test_watcher_membership_refresh_timer_counts_as_pending(tmp_path) -> None:
    TautClient.init(db_path=tmp_path / ".taut.db")
    client = TautClient(db_path=tmp_path / ".taut.db", as_handle="van")
    client.join("foo")
    watcher = TautWatcher(
        client,
        "van",
        lambda _message: None,
        membership_refresh_interval=60.0,
    )
    try:
        watcher._next_membership_refresh_at = time.monotonic() - 1

        assert watcher._has_pending_messages()
    finally:
        watcher.stop()


def test_live_watcher_does_not_redispatch_after_cursor_advance(tmp_path) -> None:
    TautClient.init(db_path=tmp_path / ".taut.db")
    van = TautClient(db_path=tmp_path / ".taut.db", as_handle="van")
    van.join("foo")
    seen: list[int] = []
    watcher = TautWatcher(
        van,
        "van",
        lambda message: seen.append(message.ts),
        membership_refresh_interval=0.05,
    )
    thread = watcher.start()
    try:
        _wait_until(thread.is_alive)

        message = van.say("foo", "once")
        _wait_until(lambda: seen.count(message.ts) == 1)
        time.sleep(0.2)

        assert seen.count(message.ts) == 1
        membership = schema.get_membership(
            van._meta_queue,
            thread="foo",
            member="van",
        )
        assert membership is not None
        assert membership["last_seen_ts"] >= message.ts
    finally:
        watcher.stop()
        thread.join(timeout=2)
        assert not thread.is_alive()


def test_watcher_poison_message_advances_after_three_failures(tmp_path) -> None:
    TautClient.init(db_path=tmp_path / ".taut.db")
    client = TautClient(db_path=tmp_path / ".taut.db", as_handle="van")
    client.join("foo")
    attempts: list[int] = []

    def fail(message) -> None:
        attempts.append(message.ts)
        raise RuntimeError("boom")

    watcher = TautWatcher(
        client,
        "van",
        fail,
        membership_refresh_interval=0.05,
    )
    thread = watcher.start()
    try:
        _wait_until(thread.is_alive)

        message = client.say("foo", "poison")
        _wait_until(lambda: attempts.count(message.ts) == 3)
        time.sleep(0.1)

        assert attempts.count(message.ts) == 3
        assert (message.thread, message.ts) not in watcher._failures
        membership = schema.get_membership(
            client._meta_queue,
            thread="foo",
            member="van",
        )
        assert membership is not None
        assert membership["last_seen_ts"] >= message.ts
        assert thread.is_alive()
    finally:
        watcher.stop()
        thread.join(timeout=2)
        assert not thread.is_alive()
