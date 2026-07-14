from __future__ import annotations

import json
import logging
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Sequence
from functools import partial
from pathlib import Path
from typing import Any, TypeVar, cast

import pytest
from simplebroker import Queue
from simplebroker.ext import OperationalError, PollingStrategy, StopWatching

from taut._exceptions import EmptyResultError, MembershipError
from taut.client import Message, Notification, TautClient
from taut.client._watching import _watch_runtime_for_client
from taut.watcher import (
    BaseReactor,
    MultiQueueWatcher,
    QueueMessageContext,
    QueueMode,
    QueueRuntimeConfig,
    TautWatcher,
)
from tests.conftest import run_cli

pytestmark = pytest.mark.sqlite_only

_TautWatcherT = TypeVar("_TautWatcherT", bound=TautWatcher)
_BASE_REACTOR_SIGINT_PROBE_MODULE = "tests.helpers.base_reactor_sigint_probe"
_BASE_REACTOR_SIGINT_PROBE_TIMEOUT = 3.0
_BASE_REACTOR_SIGINT_PROBE_GROUP = pytest.mark.xdist_group("base-reactor-sigint-probe")


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


def _run_base_reactor_sigint_probe(
    *,
    mode: str = "probe",
    timeout: float = _BASE_REACTOR_SIGINT_PROBE_TIMEOUT,
) -> dict[str, object]:
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            _BASE_REACTOR_SIGINT_PROBE_MODULE,
            "--mode",
            mode,
        ],
        cwd=Path(__file__).resolve().parents[1],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        stdout, stderr = process.communicate()
        raise AssertionError(
            f"BaseReactor SIGINT probe timed out after {timeout:.1f}s and was killed; "
            f"stdout={stdout!r}; stderr={stderr!r}"
        ) from None

    if process.returncode != 0:
        raise AssertionError(
            f"BaseReactor SIGINT probe exited with code {process.returncode}; "
            f"stdout={stdout!r}; stderr={stderr!r}"
        )

    lines = [line for line in stdout.splitlines() if line.strip()]
    if len(lines) != 1:
        raise AssertionError(
            "BaseReactor SIGINT probe did not emit exactly one structured result; "
            f"stdout={stdout!r}; stderr={stderr!r}"
        )
    try:
        payload = json.loads(lines[0])
    except json.JSONDecodeError as exc:
        raise AssertionError(
            "BaseReactor SIGINT probe emitted an invalid structured result; "
            f"stdout={stdout!r}; stderr={stderr!r}"
        ) from exc
    if not isinstance(payload, dict):
        raise AssertionError(
            "BaseReactor SIGINT probe result must be an object; "
            f"stdout={stdout!r}; stderr={stderr!r}"
        )
    return cast(dict[str, object], payload)


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


class RecordingPollingStrategy(PollingStrategy):
    def __init__(self, stop_event: threading.Event) -> None:
        super().__init__(stop_event)
        self.start_calls = 0
        self.replacements: list[Any | None] = []

    def start(
        self,
        data_version_provider: Callable[[], int | None] | None = None,
        *,
        on_data_version_change: Callable[[], None] | None = None,
        activity_waiter: Any | None = None,
    ) -> None:
        self.start_calls += 1
        super().start(
            data_version_provider,
            on_data_version_change=on_data_version_change,
            activity_waiter=activity_waiter,
        )

    def replace_activity_waiter(self, activity_waiter: Any | None) -> Any | None:
        self.replacements.append(activity_waiter)
        return super().replace_activity_waiter(activity_waiter)


def test_multi_queue_watcher_has_no_retry_or_wait_authority() -> None:
    assert "_run_with_retries" not in MultiQueueWatcher.__dict__
    assert "wait_for_activity" not in MultiQueueWatcher.__dict__
    assert "_reset_multi_activity_waiter" not in MultiQueueWatcher.__dict__


def test_base_reactor_rejects_empty_queue_configs(tmp_path: Path) -> None:
    db_path = tmp_path / ".taut.db"

    with pytest.raises(ValueError, match="queue_configs cannot be empty"):
        BaseReactor(queue_configs={}, db=db_path)

    assert not db_path.exists()


def test_base_reactor_rejects_legacy_lifecycle_override_before_broker_io(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class LegacyReactor(BaseReactor):
        def process_once(self) -> None:  # type: ignore[misc]
            raise AssertionError("must never drive")

    monkeypatch.setattr(
        "taut.watcher.Queue",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("broker I/O happened before compatibility check")
        ),
    )

    with pytest.raises(RuntimeError, match="upgrade taut-summon"):
        LegacyReactor(
            queue_configs={"legacy.input": {"handler": lambda *_args: None}},
            db=tmp_path / ".taut.db",
        )


def test_base_reactor_rejects_transient_background_start(tmp_path: Path) -> None:
    watcher = BaseReactor(
        queue_configs={"transient.input": {"handler": lambda *_args: None}},
        db=tmp_path / ".taut.db",
        persistent=False,
    )
    try:
        with pytest.raises(RuntimeError, match="persistent=True"):
            watcher.start()
        watcher.process_once()
    finally:
        watcher.stop(join=False)


def test_base_reactor_turns_have_single_thread_owner(tmp_path: Path) -> None:
    entered = threading.Event()
    release = threading.Event()
    handled: list[str] = []

    def handler(
        body: str,
        _timestamp: int,
        _context: QueueMessageContext,
    ) -> None:
        handled.append(body)
        entered.set()
        assert release.wait(timeout=3.0)

    watcher = BaseReactor(
        queue_configs={"owner.input": {"handler": handler}},
        db=tmp_path / ".taut.db",
    )
    with Queue("owner.input", db_path=str(tmp_path / ".taut.db")) as writer:
        writer.write("one")

    drive_error: list[BaseException] = []

    def drive() -> None:
        try:
            watcher.process_once()
        except BaseException as exc:  # pragma: no cover - diagnostic capture
            drive_error.append(exc)

    thread = threading.Thread(target=drive)
    thread.start()
    try:
        assert entered.wait(timeout=3.0)
        with pytest.raises(RuntimeError, match="single-owner"):
            watcher.process_once()
        assert handled == ["one"]
    finally:
        release.set()
        thread.join(timeout=3.0)
        watcher.stop(join=False)

    assert not thread.is_alive()
    assert drive_error == []


def test_base_reactor_wait_is_owner_only(tmp_path: Path) -> None:
    watcher = BaseReactor(
        queue_configs={"owner.wait": {"handler": lambda *_args: None}},
        db=tmp_path / ".taut.db",
    )
    watcher.process_once()
    errors: list[BaseException] = []

    def foreign_wait() -> None:
        try:
            watcher.wait_for_activity(timeout=0.01)
        except BaseException as exc:  # pragma: no cover - diagnostic capture
            errors.append(exc)

    thread = threading.Thread(target=foreign_wait)
    thread.start()
    thread.join(timeout=3.0)
    watcher.stop(join=False)

    assert not thread.is_alive()
    assert len(errors) == 1
    assert isinstance(errors[0], RuntimeError)
    assert "single-owner" in str(errors[0])


def test_base_reactor_rejects_same_owner_reentrant_turn(tmp_path: Path) -> None:
    class ReentrantReactor(BaseReactor):
        def _process_reactor_turn(self) -> None:
            self.process_once()

    watcher = ReentrantReactor(
        queue_configs={"reentrant.input": {"handler": lambda *_args: None}},
        db=tmp_path / ".taut.db",
    )
    try:
        with pytest.raises(RuntimeError, match="non-reentrant"):
            watcher.process_once()
    finally:
        watcher.stop(join=False)


def test_base_reactor_stop_join_false_does_not_close_active_turn(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entered = threading.Event()
    release = threading.Event()

    def handler(
        _body: str,
        _timestamp: int,
        _context: QueueMessageContext,
    ) -> None:
        entered.set()
        assert release.wait(timeout=3.0)

    watcher = BaseReactor(
        queue_configs={"stop.input": {"handler": handler}},
        db=tmp_path / ".taut.db",
    )
    managed_queue = watcher.get_queue("stop.input")
    assert managed_queue is not None
    with Queue("stop.input", db_path=str(tmp_path / ".taut.db")) as writer:
        writer.write("block")

    close_threads: list[threading.Thread] = []
    real_close = Queue.close

    def close_spy(queue: Queue) -> None:
        if queue is managed_queue:
            close_threads.append(threading.current_thread())
        real_close(queue)

    monkeypatch.setattr(Queue, "close", close_spy)
    thread = threading.Thread(target=watcher.run_until_stopped)
    thread.start()
    try:
        assert entered.wait(timeout=3.0)
        watcher.stop(join=False)
        assert close_threads == []
    finally:
        release.set()
        thread.join(timeout=3.0)

    assert not thread.is_alive()
    assert close_threads == [thread]


def test_base_reactor_exception_finalizes_and_reraises(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingReactor(BaseReactor):
        def _process_reactor_turn(self) -> None:
            raise RuntimeError("turn exploded")

    watcher = FailingReactor(
        queue_configs={"failure.input": {"handler": lambda *_args: None}},
        db=tmp_path / ".taut.db",
    )
    managed_queue = watcher.get_queue("failure.input")
    assert managed_queue is not None
    close_calls = 0
    real_close = Queue.close

    def close_spy(queue: Queue) -> None:
        nonlocal close_calls
        if queue is managed_queue:
            close_calls += 1
        real_close(queue)

    monkeypatch.setattr(Queue, "close", close_spy)

    with pytest.raises(RuntimeError, match="turn exploded"):
        watcher.run_until_stopped()

    assert close_calls == 1


def test_base_reactor_background_owner_closes_current_waiter(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_waiter = FakeWaiter()
    monkeypatch.setattr(
        "taut.watcher.create_activity_waiter_for_queues",
        lambda _queues, *, stop_event: fake_waiter,
    )
    watcher = BaseReactor(
        queue_configs={"waiter.input": {"handler": lambda *_args: None}},
        db=tmp_path / ".taut.db",
    )
    thread = watcher.start()
    try:
        _wait_until(watcher._strategy.uses_native_activity)
    finally:
        watcher.stop()
        thread.join(timeout=3.0)

    assert not thread.is_alive()
    assert fake_waiter.close_calls == 1


def test_base_reactor_waiter_close_error_does_not_skip_remaining_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingCloseWaiter(FakeWaiter):
        def close(self) -> None:
            self.close_calls += 1
            raise RuntimeError("close boom")

    fake_waiter = FailingCloseWaiter()
    monkeypatch.setattr(
        "taut.watcher.create_activity_waiter_for_queues",
        lambda _queues, *, stop_event: fake_waiter,
    )

    class ResourceReactor(BaseReactor):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self.policy_close_calls = 0
            super().__init__(*args, **kwargs)

        def _close_reactor_resources(self) -> None:
            super()._close_reactor_resources()
            self.policy_close_calls += 1

    watcher = ResourceReactor(
        queue_configs={"waiter.input": {"handler": lambda *_args: None}},
        db=tmp_path / ".taut.db",
    )
    watcher.wait_for_activity(timeout=0.001)

    watcher.stop(join=False)
    watcher.stop(join=False)

    assert fake_waiter.close_calls == 1
    assert watcher.policy_close_calls == 1
    assert watcher._queue_cache == {}


@pytest.mark.parametrize("background", [False, True])
def test_base_reactor_failed_initial_start_closes_uninstalled_waiter(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    background: bool,
) -> None:
    fake_waiter = FakeWaiter()

    def stop_during_create(
        _queues: Sequence[Queue],
        *,
        stop_event: threading.Event,
    ) -> FakeWaiter:
        stop_event.set()
        return fake_waiter

    monkeypatch.setattr(
        "taut.watcher.create_activity_waiter_for_queues",
        stop_during_create,
    )
    watcher = BaseReactor(
        queue_configs={"waiter.input": {"handler": lambda *_args: None}},
        db=tmp_path / ".taut.db",
    )

    if background:
        thread = watcher.start()
        thread.join(timeout=3.0)
        assert not thread.is_alive()
    else:
        watcher.run_until_stopped()

    assert fake_waiter.close_calls == 1
    assert watcher._multi_activity_waiter is None
    assert watcher._multi_activity_waiter_generation is None
    assert watcher._multi_activity_waiter_signature is None
    assert watcher._strategy.uses_native_activity() is False


def test_base_reactor_defers_waiter_creation_until_drive_owner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    creation_threads: list[threading.Thread] = []

    def fake_create(
        _queues: Sequence[Queue],
        *,
        stop_event: threading.Event,
    ) -> None:
        del stop_event
        creation_threads.append(threading.current_thread())
        return None

    monkeypatch.setattr(
        "taut.watcher.create_activity_waiter_for_queues",
        fake_create,
    )
    watcher = BaseReactor(
        queue_configs={"waiter.input": {"handler": lambda *_args: None}},
        db=tmp_path / ".taut.db",
    )

    try:
        assert creation_threads == []
        watcher.wait_for_activity(timeout=0.01)
        assert creation_threads == [threading.current_thread()]
    finally:
        watcher.stop(join=False)


def test_base_reactor_waits_only_through_polling_strategy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_waiter = FakeWaiter()

    def fake_create(
        _queues: Sequence[Queue],
        *,
        stop_event: threading.Event,
    ) -> FakeWaiter:
        del stop_event
        return fake_waiter

    monkeypatch.setattr(
        "taut.watcher.create_activity_waiter_for_queues",
        fake_create,
    )
    watcher = BaseReactor(
        queue_configs={"strategy.input": {"handler": lambda *_args: None}},
        db=tmp_path / ".taut.db",
    )
    strategy_waits = 0

    def record_strategy_wait() -> None:
        nonlocal strategy_waits
        strategy_waits += 1

    monkeypatch.setattr(watcher._strategy, "wait_for_activity", record_strategy_wait)

    try:
        watcher.wait_for_activity(timeout=0.01)
        assert watcher._strategy.uses_native_activity() is True
        assert strategy_waits > 0
        assert fake_waiter.wait_calls == []
    finally:
        watcher.stop(join=False)


def test_base_reactor_rebinds_waiter_after_topology_change(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    waiters = [FakeWaiter(), FakeWaiter()]
    created_for: list[list[str]] = []
    stop_event = threading.Event()

    strategy = RecordingPollingStrategy(stop_event)

    def fake_create(
        queues: Sequence[Queue],
        *,
        stop_event: threading.Event,
    ) -> FakeWaiter:
        del stop_event
        created_for.append([queue.name for queue in queues])
        return waiters[len(created_for) - 1]

    monkeypatch.setattr(
        "taut.watcher.create_activity_waiter_for_queues",
        fake_create,
    )

    class DynamicReactor(BaseReactor):
        _dynamic_topology = True

    watcher = DynamicReactor(
        queue_configs={"dynamic.one": {"handler": lambda *_args: None}},
        db=tmp_path / ".taut.db",
        stop_event=stop_event,
        polling_strategy=strategy,
    )
    watcher.wait_for_activity(timeout=0.001)
    assert created_for == [["dynamic.one"]]
    assert strategy.start_calls == 1
    assert strategy.replacements == []

    watcher.add_queue("dynamic.two", lambda *_args: None)
    assert waiters[0].close_calls == 0

    watcher.wait_for_activity(timeout=0.001)
    assert created_for == [["dynamic.one"], ["dynamic.one", "dynamic.two"]]
    assert strategy.start_calls == 1
    assert strategy.replacements == [waiters[1]]
    assert waiters[0].close_calls == 1

    watcher.wait_for_activity(timeout=0.001)
    assert created_for == [["dynamic.one"], ["dynamic.one", "dynamic.two"]]
    assert strategy.start_calls == 1
    assert strategy.replacements == [waiters[1]]

    watcher.stop(join=False)
    assert waiters[1].close_calls == 1


def test_base_reactor_replacement_can_fall_back_then_restore_native_waiting(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_waiter = FakeWaiter()
    restored_waiter = FakeWaiter()
    candidates = iter(
        (first_waiter, RuntimeError("native waiter unavailable"), restored_waiter)
    )
    stop_event = threading.Event()
    strategy = RecordingPollingStrategy(stop_event)

    def fake_create(
        _queues: Sequence[Queue],
        *,
        stop_event: threading.Event,
    ) -> FakeWaiter | None:
        del stop_event
        candidate = next(candidates)
        if isinstance(candidate, RuntimeError):
            raise candidate
        return candidate

    monkeypatch.setattr(
        "taut.watcher.create_activity_waiter_for_queues",
        fake_create,
    )

    class DynamicReactor(BaseReactor):
        _dynamic_topology = True

    watcher = DynamicReactor(
        queue_configs={"dynamic.one": {"handler": lambda *_args: None}},
        db=tmp_path / ".taut.db",
        stop_event=stop_event,
        polling_strategy=strategy,
    )
    try:
        watcher.wait_for_activity(timeout=0.001)
        watcher.add_queue("dynamic.two", lambda *_args: None)
        watcher.wait_for_activity(timeout=0.001)

        assert strategy.start_calls == 1
        assert strategy.replacements == [None]
        assert strategy.uses_native_activity() is False
        assert first_waiter.close_calls == 1

        watcher.add_queue("dynamic.three", lambda *_args: None)
        watcher.wait_for_activity(timeout=0.001)

        assert strategy.start_calls == 1
        assert strategy.replacements == [None, restored_waiter]
        assert strategy.uses_native_activity() is True
        with pytest.raises(StopIteration):
            next(candidates)
    finally:
        watcher.stop(join=False)

    assert restored_waiter.close_calls == 1


def test_base_reactor_replacement_failure_preserves_installed_waiter(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    installed_waiter = FakeWaiter()
    rejected_candidate = FakeWaiter()
    candidates = iter((installed_waiter, rejected_candidate))
    stop_event = threading.Event()

    class RejectingStrategy(RecordingPollingStrategy):
        def replace_activity_waiter(self, activity_waiter: Any | None) -> Any | None:
            self.replacements.append(activity_waiter)
            raise RuntimeError("replacement rejected")

    strategy = RejectingStrategy(stop_event)

    monkeypatch.setattr(
        "taut.watcher.create_activity_waiter_for_queues",
        lambda _queues, *, stop_event: next(candidates),
    )

    class DynamicReactor(BaseReactor):
        _dynamic_topology = True

    watcher = DynamicReactor(
        queue_configs={"dynamic.one": {"handler": lambda *_args: None}},
        db=tmp_path / ".taut.db",
        stop_event=stop_event,
        polling_strategy=strategy,
    )
    try:
        watcher.wait_for_activity(timeout=0.001)
        original_generation = watcher._strategy_generation
        original_signature = watcher._multi_activity_waiter_signature
        watcher.add_queue("dynamic.two", lambda *_args: None)

        with pytest.raises(RuntimeError, match="replacement rejected"):
            watcher.wait_for_activity(timeout=0.001)

        assert strategy.start_calls == 1
        assert strategy.replacements == [rejected_candidate]
        assert strategy.uses_native_activity() is True
        assert watcher._multi_activity_waiter is installed_waiter
        assert watcher._multi_activity_waiter_generation == original_generation
        assert watcher._multi_activity_waiter_signature == original_signature
        assert watcher._strategy_generation == original_generation
        assert installed_waiter.close_calls == 0
        assert rejected_candidate.close_calls == 1
    finally:
        watcher.stop(join=False)

    assert installed_waiter.close_calls == 1


def test_base_reactor_does_not_retry_interrupted_candidate_close(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    installed_waiter = FakeWaiter()

    class InterruptingCloseWaiter(FakeWaiter):
        def close(self) -> None:
            self.close_calls += 1
            raise KeyboardInterrupt

    rejected_candidate = InterruptingCloseWaiter()
    candidates = iter((installed_waiter, rejected_candidate))
    stop_event = threading.Event()

    class RejectingStrategy(RecordingPollingStrategy):
        def replace_activity_waiter(self, activity_waiter: Any | None) -> Any | None:
            raise RuntimeError("replacement rejected")

    monkeypatch.setattr(
        "taut.watcher.create_activity_waiter_for_queues",
        lambda _queues, *, stop_event: next(candidates),
    )

    class DynamicReactor(BaseReactor):
        _dynamic_topology = True

    watcher = DynamicReactor(
        queue_configs={"dynamic.one": {"handler": lambda *_args: None}},
        db=tmp_path / ".taut.db",
        stop_event=stop_event,
        polling_strategy=RejectingStrategy(stop_event),
    )
    try:
        watcher.wait_for_activity(timeout=0.001)
        watcher.add_queue("dynamic.two", lambda *_args: None)
        with pytest.raises(KeyboardInterrupt):
            watcher.wait_for_activity(timeout=0.001)
        assert rejected_candidate.close_calls == 1
    finally:
        watcher.stop(join=False)


def test_base_reactor_same_waiter_replacement_transfers_no_close_ownership(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reused_waiter = FakeWaiter()
    stop_event = threading.Event()
    strategy = RecordingPollingStrategy(stop_event)
    monkeypatch.setattr(
        "taut.watcher.create_activity_waiter_for_queues",
        lambda _queues, *, stop_event: reused_waiter,
    )

    class DynamicReactor(BaseReactor):
        _dynamic_topology = True

    watcher = DynamicReactor(
        queue_configs={"dynamic.one": {"handler": lambda *_args: None}},
        db=tmp_path / ".taut.db",
        stop_event=stop_event,
        polling_strategy=strategy,
    )
    try:
        watcher.wait_for_activity(timeout=0.001)
        watcher.add_queue("dynamic.two", lambda *_args: None)
        watcher.wait_for_activity(timeout=0.001)

        assert strategy.start_calls == 1
        assert strategy.replacements == [reused_waiter]
        assert watcher._multi_activity_waiter is reused_waiter
        assert watcher._multi_activity_waiter_generation == watcher._queue_generation
        assert reused_waiter.close_calls == 0
    finally:
        watcher.stop(join=False)

    assert reused_waiter.close_calls == 1


def test_base_reactor_rebinds_callback_topology_before_second_strategy_wait(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FrozenTime:
        @staticmethod
        def monotonic() -> float:
            return 100.0

    monkeypatch.setattr("taut.watcher.time", FrozenTime)
    waiters = iter((FakeWaiter(), FakeWaiter()))
    stop_event = threading.Event()

    class CallbackStrategy(RecordingPollingStrategy):
        def __init__(self) -> None:
            super().__init__(stop_event)
            self.callback: Callable[[], None] | None = None
            self.wait_calls = 0

        def start(
            self,
            data_version_provider: Callable[[], int | None] | None = None,
            *,
            on_data_version_change: Callable[[], None] | None = None,
            activity_waiter: Any | None = None,
        ) -> None:
            self.callback = on_data_version_change
            super().start(
                data_version_provider,
                on_data_version_change=on_data_version_change,
                activity_waiter=activity_waiter,
            )

        def wait_for_activity(self) -> None:
            self.wait_calls += 1
            if self.wait_calls == 1:
                assert self.callback is not None
                self.callback()
                return
            if self.wait_calls == 2:
                assert len(self.replacements) == 1
                stop_event.set()
                return
            raise AssertionError("strategy waited more than twice")

    strategy = CallbackStrategy()
    monkeypatch.setattr(
        "taut.watcher.create_activity_waiter_for_queues",
        lambda _queues, *, stop_event: next(waiters),
    )

    class DynamicReactor(BaseReactor):
        _dynamic_topology = True

        def _on_data_version_change(self, queue: Queue) -> None:
            del queue
            self.add_queue("dynamic.two", lambda *_args: None)

    watcher = DynamicReactor(
        queue_configs={"dynamic.one": {"handler": lambda *_args: None}},
        db=tmp_path / ".taut.db",
        stop_event=stop_event,
        polling_strategy=strategy,
    )
    try:
        watcher.wait_for_activity(timeout=0.1)
        assert strategy.wait_calls == 2
        assert strategy.start_calls == 1
        assert len(strategy.replacements) == 1
        assert watcher._strategy_generation == watcher._queue_generation
    finally:
        watcher.stop(join=False)


def test_base_reactor_defers_reentrant_sigint_until_waiter_replacement_commits() -> (
    None
):
    result = _run_base_reactor_sigint_probe()

    assert result == {
        "installed_close_calls": 1,
        "keyboard_interrupt": True,
        "multi_generation_matches": True,
        "multi_waiter_is_replacement": True,
        "replacement_close_calls": 1,
        "replacement_count": 1,
        "replacement_is_expected": True,
        "start_calls": 1,
        "status": "ok",
        "strategy_generation_matches": True,
    }


@_BASE_REACTOR_SIGINT_PROBE_GROUP
def test_base_reactor_sigint_probe_watchdog_reports_hung_child_as_failure() -> None:
    assert _BASE_REACTOR_SIGINT_PROBE_TIMEOUT == 3.0
    with pytest.raises(AssertionError, match="timed out.*was killed") as exc_info:
        _run_base_reactor_sigint_probe(mode="hang", timeout=1.0)

    assert '"status": "hanging"' in str(exc_info.value)


@_BASE_REACTOR_SIGINT_PROBE_GROUP
def test_base_reactor_sigint_probe_watchdog_same_worker_sentinel() -> None:
    assert _BASE_REACTOR_SIGINT_PROBE_TIMEOUT == 3.0


def test_base_reactor_sigint_defers_cleanup_outside_signal_handler(
    tmp_path: Path,
) -> None:
    stop_event = threading.Event()
    strategy = RecordingPollingStrategy(stop_event)
    watcher = BaseReactor(
        queue_configs={"signal.input": {"handler": lambda *_args: None}},
        db=tmp_path / ".taut.db",
        stop_event=stop_event,
        polling_strategy=strategy,
    )

    with pytest.raises(KeyboardInterrupt):
        watcher._sigint_handler(signal.SIGINT, None)

    assert stop_event.is_set()
    assert watcher._stop_requested is True
    assert watcher._resources_closed is False

    watcher.stop(join=False)

    assert watcher._resources_closed is True


def test_base_reactor_run_restores_signal_and_cleans_up_if_install_is_interrupted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    watcher = BaseReactor(
        queue_configs={"signal.install": {"handler": lambda *_args: None}},
        db=tmp_path / ".taut.db",
    )
    original_handler = signal.getsignal(signal.SIGINT)
    installed: list[object] = []

    def interrupting_signal(signum: int, handler: object) -> object:
        assert signum == signal.SIGINT
        installed.append(handler)
        if len(installed) == 1:
            assert callable(handler)
            handler(signum, None)
        return original_handler

    monkeypatch.setattr(signal, "signal", interrupting_signal)

    with pytest.raises(KeyboardInterrupt):
        watcher.run_forever()

    assert installed == [watcher._sigint_handler, original_handler]
    assert watcher._resources_closed is True
    assert watcher.is_running() is False


def test_base_reactor_run_cleans_up_if_sigint_preempts_drive_claim(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    watcher = BaseReactor(
        queue_configs={"signal.claim": {"handler": lambda *_args: None}},
        db=tmp_path / ".taut.db",
    )
    original_handler = signal.getsignal(signal.SIGINT)
    monkeypatch.setattr(
        watcher,
        "_claim_reactor_thread",
        lambda: watcher._sigint_handler(signal.SIGINT, None),
    )

    with pytest.raises(KeyboardInterrupt):
        watcher.run_forever()

    assert signal.getsignal(signal.SIGINT) == original_handler
    assert watcher._resources_closed is True
    assert watcher.is_running() is False


def test_base_reactor_run_cleans_up_if_running_state_publication_is_interrupted(
    tmp_path: Path,
) -> None:
    watcher = BaseReactor(
        queue_configs={"signal.running": {"handler": lambda *_args: None}},
        db=tmp_path / ".taut.db",
    )

    class InterruptingRunningEvent:
        def __init__(self) -> None:
            self.clear_calls = 0

        def set(self) -> None:
            raise KeyboardInterrupt

        def clear(self) -> None:
            self.clear_calls += 1

        def is_set(self) -> bool:
            return False

    running_event = InterruptingRunningEvent()
    watcher._running_event = cast(Any, running_event)

    with pytest.raises(KeyboardInterrupt):
        watcher.run_forever()

    assert running_event.clear_calls == 1
    assert watcher._resources_closed is True


def test_base_reactor_discovers_pending_dynamic_queue_before_waiter_rebind(
    tmp_path: Path,
) -> None:
    seen: list[str] = []

    class DynamicReactor(BaseReactor):
        _dynamic_topology = True

    db_path = tmp_path / ".taut.db"
    watcher = DynamicReactor(
        queue_configs={"dynamic.one": {"handler": lambda *_args: None}},
        db=db_path,
        inactive_probe_interval=60.0,
    )
    try:
        watcher.process_once()
        watcher.wait_for_activity(timeout=0.001)
        watcher.add_queue(
            "dynamic.two",
            lambda body, _timestamp, _context: seen.append(body),
        )

        with Queue("dynamic.two", db_path=str(db_path)) as writer:
            writer.write("already pending")

        watcher.wait_for_activity(timeout=0.001)
        watcher.process_once()

        assert seen == ["already pending"]
    finally:
        watcher.stop(join=False)


@pytest.mark.parametrize("operation", ["add", "remove"])
def test_base_reactor_rejects_dynamic_queue_mutators(
    tmp_path: Path,
    operation: str,
) -> None:
    watcher = BaseReactor(
        queue_configs={"fixed.one": {"handler": lambda *_args: None}},
        db=tmp_path / ".taut.db",
    )
    try:
        with pytest.raises(NotImplementedError, match="fixed at construction"):
            if operation == "add":
                watcher.add_queue("fixed.two", lambda *_args: None)
            else:
                watcher.remove_queue("fixed.one")
    finally:
        watcher.stop(join=False)


def test_base_reactor_live_queue_is_owner_only_after_drive(tmp_path: Path) -> None:
    watcher = BaseReactor(
        queue_configs={"owned.queue": {"handler": lambda *_args: None}},
        db=tmp_path / ".taut.db",
    )
    watcher.process_once()
    errors: list[BaseException] = []

    def foreign_get() -> None:
        try:
            watcher.get_queue("owned.queue")
        except BaseException as exc:  # pragma: no cover - diagnostic capture
            errors.append(exc)

    thread = threading.Thread(target=foreign_get)
    thread.start()
    thread.join(timeout=3.0)
    watcher.stop(join=False)

    assert len(errors) == 1
    assert isinstance(errors[0], RuntimeError)
    assert "drive-owner-only" in str(errors[0])


def test_multi_queue_watcher_does_not_layer_retry_over_queue_operation(
    tmp_path: Path,
) -> None:
    watcher = BaseReactor(
        queue_configs={"retry.probe": {"handler": lambda _body, _ts: None}},
        db=tmp_path / ".taut.db",
    )
    attempts = 0

    class FlakyQueue:
        def has_pending(self) -> bool:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise OperationalError("database is locked")
            return False

    try:
        with pytest.raises(OperationalError, match="locked"):
            watcher._queue_has_pending(cast(Any, FlakyQueue()))
        assert attempts == 1
    finally:
        watcher.stop(join=False)


def test_taut_watcher_keeps_memory_cursor_when_advance_exhausts() -> None:
    watcher = object.__new__(TautWatcher)
    watcher._cursors = {"foo": 10}
    watcher._stop_event = threading.Event()
    watcher.member_id = "m_reviewer"

    class FailingRuntime:
        def advance_cursor(
            self,
            *,
            thread: str,
            member_id: str,
            seen_ts: int,
        ) -> None:
            assert (thread, member_id, seen_ts) == ("foo", "m_reviewer", 11)
            raise OperationalError("database is locked")

    cast(Any, watcher)._runtime = FailingRuntime()

    with pytest.raises(OperationalError, match="locked"):
        watcher._advance("foo", 11)

    assert watcher._cursors["foo"] == 10


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

    watcher = BaseReactor(
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


def test_base_reactor_centralizes_process_wait_stop_loop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order: list[tuple[str, threading.Thread]] = []

    class OneTurnReactor(BaseReactor):
        def _process_reactor_turn(self) -> None:
            order.append(("turn", threading.current_thread()))
            self.request_stop()

    watcher = OneTurnReactor(
        queue_configs={"base.loop": {"handler": lambda *_args: None}},
        db=tmp_path / ".taut.db",
    )
    real_start_strategy = watcher._start_strategy

    def record_start_strategy() -> None:
        order.append(("strategy", threading.current_thread()))
        real_start_strategy()

    monkeypatch.setattr(watcher, "_start_strategy", record_start_strategy)
    watcher.run_forever()

    assert order == [
        ("strategy", threading.current_thread()),
        ("turn", threading.current_thread()),
    ]
    assert watcher.is_running() is False


def test_multi_queue_watcher_drains_higher_priority_queue_first(
    tmp_path: Path,
) -> None:
    seen: list[str] = []
    db = tmp_path / ".taut.db"
    watcher = BaseReactor(
        {
            "priority.low": {
                "handler": lambda body, *_args: seen.append(body),
                "priority": 20,
            },
            "priority.high": {
                "handler": lambda body, *_args: seen.append(body),
                "priority": 0,
            },
        },
        db=db,
    )
    low = Queue("priority.low", db_path=str(db))
    high = Queue("priority.high", db_path=str(db))
    try:
        low.write("low")
        high.write("high")

        watcher.process_once()

        assert seen == ["high", "low"]
    finally:
        watcher.stop(join=False)
        low.close()
        high.close()


def test_multi_queue_watcher_reserve_moves_message_before_dispatch(
    tmp_path: Path,
) -> None:
    seen: list[tuple[str, str | None]] = []
    db = tmp_path / ".taut.db"
    watcher = BaseReactor(
        {
            "reserve.source": {
                "handler": lambda body, _ts, context: seen.append(
                    (body, context.reserved_queue_name)
                ),
                "mode": QueueMode.RESERVE,
                "reserved_queue": "reserve.target",
            }
        },
        db=db,
    )
    source = Queue("reserve.source", db_path=str(db))
    target = Queue("reserve.target", db_path=str(db))
    try:
        source.write("reserved")

        watcher.process_once()

        assert seen == [("reserved", "reserve.target")]
        assert source.peek_many() == []
        assert target.peek_many() == ["reserved"]
    finally:
        watcher.stop(join=False)
        source.close()
        target.close()


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


def test_taut_watcher_uses_persistent_queue_handles(tmp_path: Path) -> None:
    TautClient.init(db_path=tmp_path / ".taut.db")
    van = TautClient(db_path=tmp_path / ".taut.db", as_name="van")
    van.join("foo")

    watcher = _white_box_watcher(van, lambda _item: None, threads=["foo"])
    try:
        queue = watcher.get_queue("foo")
        assert queue is not None
        assert watcher._persistent is True
    finally:
        watcher.stop()


def test_client_watch_can_use_nonpersistent_queue_handles(tmp_path: Path) -> None:
    TautClient.init(db_path=tmp_path / ".taut.db")
    van = TautClient(db_path=tmp_path / ".taut.db", as_name="van")
    van.join("foo")

    watcher = van.watch(lambda _item: None, threads=["foo"], persistent=False)
    try:
        queue = watcher.get_queue("foo")
        assert queue is not None
        assert watcher._persistent is False
    finally:
        watcher.stop()


def test_client_watch_closes_owned_runtime_when_construction_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """[TAUT-8.4] A rejected explicit filter must not leak its runtime."""

    from taut.client import _watching

    TautClient.init(db_path=tmp_path / ".taut.db")
    client = TautClient(db_path=tmp_path / ".taut.db", as_name="van")
    client.join("foo")
    created: list[Any] = []
    close_calls: list[Any] = []
    real_factory = _watching._watch_runtime_for_client

    def capture_runtime(
        source: TautClient,
        *,
        persistent: bool = True,
    ) -> Any:
        runtime = real_factory(source, persistent=persistent)
        real_close = runtime.close

        def track_real_close() -> None:
            close_calls.append(runtime)
            real_close()

        cast(Any, runtime).close = track_real_close
        created.append(runtime)
        return runtime

    monkeypatch.setattr(_watching, "_watch_runtime_for_client", capture_runtime)

    with pytest.raises(MembershipError, match="ghost"):
        client.watch(lambda _item: None, threads=["foo", "ghost"])

    assert len(created) == 1
    runtime = created[0]
    assert close_calls == [runtime]
    assert runtime._closed is True


def test_multi_queue_watcher_explicit_db_skips_broken_cwd_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """[TAUT-8.4] An explicit target must not resolve an irrelevant cwd."""

    cwd = tmp_path / "cwd"
    cwd.mkdir()
    (cwd / ".taut.toml").write_text("not = [valid", encoding="utf-8")
    explicit_db = tmp_path / "explicit.db"
    monkeypatch.chdir(cwd)

    watcher = MultiQueueWatcher(
        {"explicit.input": {"handler": lambda *_args: None}},
        db=explicit_db,
        persistent=False,
    )
    try:
        assert str(watcher._db_path) == str(explicit_db)
        assert not (cwd / ".taut.db").exists()
    finally:
        watcher.stop(join=False)


def test_taut_watcher_start_drives_the_same_persistent_instance(tmp_path: Path) -> None:
    TautClient.init(db_path=tmp_path / ".taut.db")
    van = TautClient(db_path=tmp_path / ".taut.db", as_name="van")
    van.join("foo")

    watcher = van.watch(lambda _item: None, threads=["foo"])
    thread = watcher.start()
    try:
        _wait_until(lambda: watcher._drive_thread is thread)
        assert watcher._persistent is True
        assert not hasattr(watcher, "_thread_watcher")
        assert watcher.is_running()
    finally:
        watcher.stop()
        thread.join(timeout=2)
        assert not thread.is_alive()


def test_taut_watcher_runtime_survives_source_client_close(tmp_path: Path) -> None:
    TautClient.init(db_path=tmp_path / ".taut.db")
    van = TautClient(db_path=tmp_path / ".taut.db", as_name="van")
    bob = TautClient(db_path=tmp_path / ".taut.db", as_name="bob")
    van.join("foo")
    bob.join("foo")
    _drain_unread(van, "foo")
    seen: list[str] = []
    watcher = van.watch(_record_message_texts(seen), threads=["foo"])

    van.close()
    bob.say("foo", "independent runtime")
    try:
        watcher.process_once()
        assert seen == ["independent runtime"]
    finally:
        watcher.stop(join=False)


def test_taut_watcher_uses_native_multi_queue_activity_waiter(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_waiter = FakeWaiter()
    watched_queue_names: list[str] = []

    def fake_create(
        queues: Sequence[Queue],
        *,
        stop_event: threading.Event,
    ) -> FakeWaiter:
        del stop_event
        watched_queue_names[:] = [queue.name for queue in queues]
        return fake_waiter

    monkeypatch.setattr(
        "taut.watcher.create_activity_waiter_for_queues",
        fake_create,
    )
    TautClient.init(db_path=tmp_path / ".taut.db")
    van = TautClient(db_path=tmp_path / ".taut.db", as_name="van")
    van.join("foo")

    watcher = _white_box_watcher(van, lambda _item: None, threads=["foo"])
    try:
        watcher._start_strategy()
        assert watcher._strategy.uses_native_activity() is True
        assert set(watched_queue_names) == {watcher._notification_queue_name, "foo"}
    finally:
        watcher.stop(join=False)


def test_taut_watcher_data_version_change_does_not_refresh_last_ts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    TautClient.init(db_path=tmp_path / ".taut.db")
    van = TautClient(db_path=tmp_path / ".taut.db", as_name="van")
    van.join("foo")
    watcher = _white_box_watcher(van, lambda _item: None, threads=["foo"])
    queue = watcher.get_queue("foo")
    assert queue is not None

    def fail_data_version(_self: MultiQueueWatcher, _queue: Queue) -> None:
        raise AssertionError("TautWatcher must not refresh SimpleBroker last_ts")

    monkeypatch.setattr(MultiQueueWatcher, "_on_data_version_change", fail_data_version)
    try:
        watcher._on_data_version_change(queue)
    finally:
        watcher.stop()


def test_taut_watcher_data_version_change_still_refreshes_memberships(
    tmp_path: Path,
) -> None:
    TautClient.init(db_path=tmp_path / ".taut.db")
    van = TautClient(db_path=tmp_path / ".taut.db", as_name="van")
    van.join("foo")
    van.join("bar")
    watcher = _white_box_watcher(van, lambda _item: None)
    try:
        assert "bar" in watcher.list_queues()
        van.join("baz")
        queue = watcher.get_queue("foo")
        assert queue is not None
        watcher._on_data_version_change(queue)
        assert "baz" in watcher.list_queues()
    finally:
        watcher.stop()


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


def test_taut_watcher_pending_history_waits_for_first_driven_turn(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / ".taut.db"
    TautClient.init(db_path=db_path)
    van = TautClient(db_path=db_path, as_name="van")
    bob = TautClient(db_path=db_path, as_name="bob")
    van.join("foo")
    bob.join("foo")
    _drain_unread(van, "foo")
    bob.say("foo", "pending")
    seen: list[str] = []

    watcher = van.watch(_record_message_texts(seen))
    try:
        assert seen == []
        watcher.process_once()
        assert seen == ["pending"]
    finally:
        watcher.stop(join=False)


def test_taut_watcher_cursor_failure_replays_after_restart(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / ".taut.db"
    TautClient.init(db_path=db_path)
    van = TautClient(db_path=db_path, as_name="van")
    bob = TautClient(db_path=db_path, as_name="bob")
    van.join("foo")
    bob.join("foo")
    _drain_unread(van, "foo")
    message = bob.say("foo", "replay me")
    first_seen: list[int] = []
    first = van.watch(_record_message_timestamps(first_seen))

    def fail_first_advance(*, thread: str, member_id: str, seen_ts: int) -> None:
        first.request_stop()
        raise OperationalError("cursor commit failed")

    monkeypatch.setattr(first._runtime, "advance_cursor", fail_first_advance)
    first_thread = first.start()
    first_thread.join(timeout=3.0)
    assert not first_thread.is_alive()
    assert first_seen == [message.ts]

    # The source client remains usable and the failed durable advance left the
    # message pending for a fresh watcher generation.
    second_seen: list[int] = []
    second = van.watch(_record_message_timestamps(second_seen))
    second_thread = second.start()
    try:
        _wait_until(lambda: second_seen == [message.ts])
        _wait_until(lambda: _thread_is_read(van, "foo"))
    finally:
        second.stop()
        second_thread.join(timeout=3.0)
        assert not second_thread.is_alive()


def test_taut_watcher_preserves_per_queue_order_without_handler_overlap(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / ".taut.db"
    TautClient.init(db_path=db_path)
    van = TautClient(db_path=db_path, as_name="van")
    bob = TautClient(db_path=db_path, as_name="bob")
    for thread_name in ("alpha", "beta"):
        van.join(thread_name)
        bob.join(thread_name)
        _drain_unread(van, thread_name)

    seen: list[tuple[str, str]] = []
    handler_active = False

    def record(item: Message | Notification) -> None:
        nonlocal handler_active
        if not isinstance(item, Message):
            return
        assert handler_active is False
        handler_active = True
        seen.append((item.thread, item.text))
        handler_active = False

    watcher = van.watch(record)
    watcher_thread = watcher.start()
    try:
        bob.say("alpha", "a1")
        bob.say("beta", "b1")
        bob.say("alpha", "a2")
        bob.say("beta", "b2")
        _wait_until(lambda: len(seen) == 4)
    finally:
        watcher.stop()
        watcher_thread.join(timeout=3.0)
        assert not watcher_thread.is_alive()

    assert [text for thread, text in seen if thread == "alpha"] == ["a1", "a2"]
    assert [text for thread, text in seen if thread == "beta"] == ["b1", "b2"]


def test_taut_watcher_ready_signal_fires_after_initial_drain(tmp_path: Path) -> None:
    TautClient.init(db_path=tmp_path / ".taut.db")
    van = TautClient(db_path=tmp_path / ".taut.db", as_name="van")
    bot = TautClient(db_path=tmp_path / ".taut.db", as_name="bot")
    van.join("foo")
    bot.join("foo")
    van.say("foo", "before-ready")
    seen: list[str] = []
    ready = threading.Event()
    watcher = bot.watch(_record_message_texts(seen))
    watcher.notify_ready_after_initial_drain(ready)
    thread = watcher.start()
    try:
        assert ready.wait(timeout=3.0)
        assert "before-ready" in seen
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


def test_stop_watching_from_refreshed_chat_queue_does_not_poison_advance(
    tmp_path: Path,
) -> None:
    """[TAUT-8.4] Terminal sink failure stops even on a late-added queue."""

    TautClient.init(db_path=tmp_path / ".taut.db")
    van = TautClient(db_path=tmp_path / ".taut.db", as_name="van")
    bob = TautClient(db_path=tmp_path / ".taut.db", as_name="bob")
    van.join("home")
    bob.join("home")
    _drain_unread(van, "home")
    attempted: list[Message] = []

    def closed_sink(item: Message | Notification) -> None:
        if not isinstance(item, Message) or item.thread != "late":
            return
        if item.text == "terminal sink probe":
            attempted.append(item)
            raise StopWatching

    watcher = _white_box_watcher(
        van,
        closed_sink,
        membership_refresh_interval=0.05,
    )
    thread = watcher.start()
    try:
        _wait_until(thread.is_alive)
        van.join("late")
        bob.join("late")
        _wait_until(lambda: "late" in watcher.list_queues())
        bob.say("late", "terminal sink probe")
        _wait_until(lambda: not thread.is_alive())

        assert len(attempted) == 1
        unread = van.read_unread("late")
        assert [message.ts for message in unread] == [attempted[0].ts]
    finally:
        watcher.stop()
        thread.join(timeout=2)
        assert not thread.is_alive()


def test_stop_watching_from_notification_queue_stops_reactor(tmp_path: Path) -> None:
    """[TAUT-8.4] Notification handlers share terminal-stop classification."""

    TautClient.init(db_path=tmp_path / ".taut.db")
    van = TautClient(db_path=tmp_path / ".taut.db", as_name="van")
    bob = TautClient(db_path=tmp_path / ".taut.db", as_name="bob")
    van.join("foo")
    bob.join("foo")
    _drain_unread(van, "foo")
    attempted: list[Notification] = []

    def closed_sink(item: Message | Notification) -> None:
        if isinstance(item, Notification):
            attempted.append(item)
            raise StopWatching

    watcher = _white_box_watcher(van, closed_sink)
    thread = watcher.start()
    try:
        _wait_until(thread.is_alive)
        bob.say("foo", "@van ping")
        _wait_until(lambda: not thread.is_alive())

        assert len(attempted) == 1
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
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
        closed_queues: list[str] = []
        real_close = Queue.close

        def close_spy(queue: Queue) -> None:
            closed_queues.append(queue.name)
            real_close(queue)

        monkeypatch.setattr(Queue, "close", close_spy)

        watcher.remove_queue("guard.first")

        # White-box (labeled): dispatch alone can be masked by the live
        # multi-queue activity waiter, so pin data-version polling directly:
        # the shared first queue must still answer get_data_version().
        assert isinstance(watcher._get_queue_for_data_version().get_data_version(), int)
        assert "guard.first" not in closed_queues

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


def test_multi_queue_watcher_remove_non_data_version_queue_unregisters_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
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
        closed_queues: list[str] = []
        real_close = Queue.close

        def close_spy(queue: Queue) -> None:
            closed_queues.append(queue.name)
            real_close(queue)

        monkeypatch.setattr(Queue, "close", close_spy)
        watcher.remove_queue("close.second")

        assert "close.second" not in watcher.list_queues()
        assert "close.second" not in closed_queues
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


def test_taut_watcher_membership_churn_closes_removed_queues(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
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
    closed_queues: list[tuple[str, threading.Thread]] = []
    real_close = Queue.close

    def close_spy(queue: Queue) -> None:
        closed_queues.append((queue.name, threading.current_thread()))
        real_close(queue)

    monkeypatch.setattr(Queue, "close", close_spy)

    def queue_listed(name: str) -> bool:
        return name in watcher.list_queues()

    def queue_absent(name: str) -> bool:
        return name not in watcher.list_queues()

    def queue_removed_and_closed(name: str) -> bool:
        return queue_absent(name) and any(
            queue_name == name for queue_name, _close_thread in closed_queues
        )

    try:
        _wait_until(thread.is_alive)

        for cycle in range(10):
            name = f"churn{cycle}"
            van.join(name)
            _wait_until(partial(queue_listed, name))
            assert watcher._persistent is True
            van.leave(name)
            _wait_until(partial(queue_removed_and_closed, name))
            assert (name, thread) in closed_queues

        # Functional assertion — unconditional on every platform: the
        # watcher still delivers messages after ten join/leave cycles.
        bob.say("home", "after churn")
        _wait_until(lambda: ("home", "after churn") in seen)
    finally:
        watcher.stop()
        thread.join(timeout=2)
        assert not thread.is_alive()


def test_taut_watcher_stop_closes_persistent_queues(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / ".taut.db"
    TautClient.init(db_path=db_path)
    van = TautClient(db_path=db_path, as_name="van")
    van.join("home")
    seen: list[Message | Notification] = []
    watcher = _white_box_watcher(van, seen.append)
    closed_queues: list[str] = []
    real_close = Queue.close

    def close_spy(queue: Queue) -> None:
        closed_queues.append(queue.name)
        real_close(queue)

    monkeypatch.setattr(Queue, "close", close_spy)
    thread = watcher.start()
    try:
        _wait_until(thread.is_alive)
    finally:
        watcher.stop()
        thread.join(timeout=2)
        assert not thread.is_alive()

    assert "home" in closed_queues
    assert watcher._notification_queue_name in closed_queues


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
