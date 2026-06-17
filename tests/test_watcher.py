from __future__ import annotations

import logging
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

import taut.schema as schema
from taut.client import Message, TautClient
from taut.watcher import QueueRuntimeConfig, TautWatcher
from tests.conftest import run_cli


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
    )


def test_explicit_watch_filter_drops_left_thread_on_refresh(tmp_path: Path) -> None:
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


def test_live_watch_filter_drops_left_thread_without_killing_watcher(
    tmp_path: Path,
) -> None:
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


def test_live_watcher_receives_message_from_cli_subprocess(tmp_path: Path) -> None:
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


def test_concurrent_writer_processes_persist_all_messages(
    tmp_path: Path,
) -> None:
    TautClient.init(db_path=tmp_path / ".taut.db")
    van = TautClient(db_path=tmp_path / ".taut.db", as_handle="van")
    van.join("foo")
    for handle in ("bob", "codex"):
        TautClient(db_path=tmp_path / ".taut.db", as_handle=handle).join("foo")

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
    assert {message.from_handle for message in messages} == {"bob", "codex"}
    assert [message.ts for message in messages] == sorted(
        message.ts for message in messages
    )


def test_live_watcher_picks_up_mid_watch_join_via_add_queue(tmp_path: Path) -> None:
    TautClient.init(db_path=tmp_path / ".taut.db")
    van = TautClient(db_path=tmp_path / ".taut.db", as_handle="van")
    bob = TautClient(db_path=tmp_path / ".taut.db", as_handle="bob")
    van.join("foo")
    bob.join("foo")
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
    van = TautClient(db_path=tmp_path / ".taut.db", as_handle="van")
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

    watcher = CountingWatcher(
        van,
        "van",
        lambda message: seen.append(message.ts),
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


def test_watcher_membership_refresh_timer_counts_as_pending(tmp_path: Path) -> None:
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


def test_live_watcher_does_not_redispatch_after_cursor_advance(
    tmp_path: Path,
) -> None:
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


def test_watcher_poison_message_advances_after_three_failures(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    TautClient.init(db_path=tmp_path / ".taut.db")
    client = TautClient(db_path=tmp_path / ".taut.db", as_handle="van")
    client.join("foo")
    attempts: list[int] = []
    caplog.set_level(logging.WARNING, logger="taut.watcher")

    def fail(message: Message) -> None:
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
        assert f"advancing past poison message {message.ts} in foo" in caplog.text
    finally:
        watcher.stop()
        thread.join(timeout=2)
        assert not thread.is_alive()
