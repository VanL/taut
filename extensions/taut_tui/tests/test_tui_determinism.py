"""The completion interface observes real transitions without driving them."""

from __future__ import annotations

import asyncio
import gc
import threading
import weakref
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import FrozenInstanceError

import _completion
import pytest
from _completion import (
    CompletionKey,
    CompletionScope,
    CompletionStatus,
    CompletionTimeout,
)


def test_completion_retains_success_before_any_wait() -> None:
    scope = CompletionScope(clock=lambda: 12.5)
    key = CompletionKey(object(), "navigation.applied", request=object())
    completion = scope.expect(key)

    assert completion.succeed(key, "rendered") is True
    outcome = completion.snapshot()
    assert outcome is not None
    assert outcome.key is key
    assert outcome.status is CompletionStatus.SUCCESS
    assert outcome.value == "rendered"
    assert outcome.published_at == 12.5


def test_scope_history_is_bounded_without_touching_the_producer() -> None:
    scope = CompletionScope()
    owner = object()
    first = scope.expect(CompletionKey(owner, "first", request=object()))
    for generation in range(4095):
        scope.expect(CompletionKey(owner, "phase", generation=generation))
    source: Future[str] = Future()
    with pytest.raises(AssertionError, match="completion history capacity"):
        scope.observe_future(source, owner=owner, phase="overflow")
    assert len(scope._records) == 4096
    assert source.cancelled() is False
    source.set_result("real producer still completes")
    assert source.result() == "real producer still completes"
    first.succeed(first.key, "retained")
    assert first.wait_sync(deadline=scope.now() + 1, description="first") == "retained"
    scope.close()
    assert not scope._records
    with pytest.raises(AssertionError, match="completion history capacity"):
        scope.raise_if_invalid()


@pytest.mark.parametrize("mismatch", ["owner", "request", "generation", "phase"])
def test_wrong_identity_never_completes_a_registered_phase(mismatch: str) -> None:
    scope = CompletionScope()
    key = CompletionKey(object(), "navigation.applied", object(), 7)
    completion = scope.expect(key)
    incoming = CompletionKey(
        object() if mismatch == "owner" else key.owner,
        "navigation.source" if mismatch == "phase" else key.phase,
        object() if mismatch == "request" else key.request,
        6 if mismatch == "generation" else key.generation,
    )

    assert completion.succeed(incoming, "stale") is False
    assert completion.snapshot() is None
    with pytest.raises(AssertionError, match="identity"):
        scope.raise_if_invalid()


def test_duplicate_publication_keeps_first_terminal_outcome() -> None:
    scope = CompletionScope(clock=lambda: 12.5)
    key = CompletionKey(object(), "navigation.applied", request=object())
    completion = scope.expect(key)
    assert completion.succeed(key, "first") is True
    first = completion.snapshot()

    assert completion.succeed(key, "second") is False
    assert completion.snapshot() is first
    with pytest.raises(AssertionError, match="duplicate"):
        scope.raise_if_invalid()


def test_async_wait_handles_early_and_scheduled_completion() -> None:
    async def exercise() -> None:
        scope = CompletionScope()
        owner = object()
        early_key = CompletionKey(owner, "navigation.source", request=object())
        early = scope.expect(early_key)
        early.succeed(early_key, "source")
        assert (
            await early.wait(deadline=scope.now() + 1, description="source") == "source"
        )

        applied_key = CompletionKey(owner, "navigation.applied", request=object())
        applied = scope.expect(applied_key)
        asyncio.get_running_loop().call_soon(applied.succeed, applied_key, "applied")
        assert (
            await applied.wait(deadline=scope.now() + 1, description="apply")
            == "applied"
        )

    asyncio.run(exercise())


def test_overlapping_wait_is_rejected_without_disrupting_the_first_wait() -> None:
    async def exercise() -> None:
        with CompletionScope() as scope:
            key = CompletionKey(object(), "worker.returned", request=object())
            completion = scope.expect(key)
            first = asyncio.create_task(
                completion.wait(deadline=scope.now() + 1, description="first")
            )
            # A loop fence, not a predicate loop: the first task registers its wait.
            fence = asyncio.get_running_loop().create_future()
            asyncio.get_running_loop().call_soon(fence.set_result, None)
            await fence
            with pytest.raises(
                _completion.CompletionProtocolError, match="active wait"
            ):
                await completion.wait(deadline=scope.now(), description="overlap")
            assert completion.succeed(key, "finished") is True
            assert await first == "finished"

    asyncio.run(exercise())


@pytest.mark.parametrize("kind", ["asyncio", "concurrent"])
@pytest.mark.parametrize("already_done", [False, True])
def test_future_adapter_preserves_producer_and_observes_retained_result(
    kind: str, already_done: bool
) -> None:
    async def exercise() -> None:
        scope = CompletionScope(clock=lambda: 20.0)
        producer: asyncio.Future[str] | Future[str] = (
            asyncio.get_running_loop().create_future()
            if kind == "asyncio"
            else Future()
        )
        if already_done:
            producer.set_result("real result")
        completion = scope.observe_future(
            producer, owner=object(), phase="worker.source"
        )
        if not already_done:
            asyncio.get_running_loop().call_soon(producer.set_result, "real result")
        assert (
            await completion.wait(deadline=21.0, description="source") == "real result"
        )
        assert completion.key.request is producer
        assert producer.result() == "real result"
        outcome = completion.snapshot()
        assert outcome is not None
        assert outcome.published_at == 20.0

    asyncio.run(exercise())


@pytest.mark.parametrize("terminal", ["error", "cancelled", "superseded"])
def test_producer_terminal_outcomes_are_not_timeouts_or_observer_cancellation(
    terminal: str,
) -> None:
    async def exercise() -> None:
        scope = CompletionScope(clock=lambda: 10.0)
        key = CompletionKey(object(), "worker.returned", request=object())
        completion = scope.expect(key)
        error = ValueError("same producer exception")
        expected: type[Exception]
        if terminal == "error":
            completion.fail(key, error)
            expected = ValueError
        elif terminal == "cancelled":
            completion.cancel(key)
            expected = _completion.CompletionCancelled
        else:
            completion.supersede(key)
            expected = _completion.CompletionSuperseded
        with pytest.raises(expected) as raised:
            await completion.wait(deadline=11.0, description="worker")
        if terminal == "error":
            assert raised.value is error
        assert not isinstance(raised.value, (TimeoutError, asyncio.CancelledError))
        outcome = completion.snapshot()
        assert outcome is not None
        assert outcome.status.value == terminal

    asyncio.run(exercise())


@pytest.mark.parametrize("invalid", ["missing_request", "missing_phase"])
def test_key_rejects_unidentified_or_unnamed_completion(invalid: str) -> None:
    with pytest.raises(ValueError):
        CompletionKey(
            object(),
            "" if invalid == "missing_phase" else "worker.source",
            request=object() if invalid == "missing_phase" else None,
        )


@pytest.mark.parametrize("publication_time", [10.0, 10.000001, 11.0])
def test_delayed_wake_accepts_only_publication_at_or_before_deadline(
    publication_time: float, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def exercise() -> None:
        now = 10.0
        scope = CompletionScope(clock=lambda: now)
        key = CompletionKey(object(), "navigation.applied", request=object())
        completion = scope.expect(key)
        delayed_wakes: list[asyncio.Future[None]] = []
        monkeypatch.setattr(_completion, "_wake", delayed_wakes.append)

        def publish_before_timeout_is_serviced() -> None:
            nonlocal now
            now = publication_time
            completion.succeed(key, "applied")
            now = 12.0

        asyncio.get_running_loop().call_soon(publish_before_timeout_is_serviced)
        if publication_time <= 10.000001:
            assert (
                await completion.wait(deadline=10.000001, description="apply")
                == "applied"
            )
        else:
            with pytest.raises(CompletionTimeout, match="apply"):
                await completion.wait(deadline=10.000001, description="apply")
        assert len(delayed_wakes) == 1
        assert completion.snapshot() is not None

    asyncio.run(exercise())


@pytest.mark.parametrize("ending", ["timeout", "observer_cancel", "dispose"])
def test_abandoned_observation_ignores_late_publication(ending: str) -> None:
    async def exercise() -> None:
        scope = CompletionScope()
        key = CompletionKey(object(), "worker.returned", request=object())
        completion = scope.expect(key)
        loop = asyncio.get_running_loop()
        if ending == "timeout":
            with pytest.raises(CompletionTimeout):
                await completion.wait(deadline=scope.now(), description="worker")
        elif ending == "observer_cancel":
            current = asyncio.current_task()
            assert current is not None
            loop.call_soon(current.cancel)
            with pytest.raises(asyncio.CancelledError):
                await completion.wait(deadline=scope.now() + 1, description="worker")
        else:
            loop.call_soon(completion.dispose)
            with pytest.raises(_completion.CompletionDisposed):
                await completion.wait(deadline=scope.now() + 1, description="worker")
        assert completion.succeed(key, "late") is False
        assert completion.snapshot() is None
        scope.raise_if_invalid()

    asyncio.run(exercise())


def test_scope_exit_releases_records_and_makes_retained_producer_callback_inert() -> (
    None
):
    producer: Future[str] = Future()
    with CompletionScope() as scope:
        completion = scope.observe_future(
            producer, owner=object(), phase="worker.source"
        )
        record_reference = weakref.ref(completion)
        scope_reference = weakref.ref(scope)
        del completion
    gc.collect()
    assert record_reference() is None
    del scope
    gc.collect()
    assert scope_reference() is None
    assert not producer.cancelled()
    producer.set_result("late actual result")
    assert producer.result() == "late actual result"


def test_sync_wait_observes_the_same_record_from_its_existing_thread_owner() -> None:
    with CompletionScope() as scope:
        key = CompletionKey(object(), "lease.restored", request=object())
        completion = scope.expect(key)
        ready = threading.Event()
        results: list[str] = []

        def existing_owner() -> None:
            ready.set()
            results.append(
                completion.wait_sync(
                    deadline=scope.now() + 1, description="lease restoration"
                )
            )

        thread = threading.Thread(target=existing_owner)
        thread.start()
        try:
            assert ready.wait(1)
            completion.succeed(key, "restored")
        finally:
            thread.join(1)
        assert not thread.is_alive()
        assert results == ["restored"]


def test_sync_wait_rejects_the_running_event_loop_even_for_early_completion() -> None:
    async def exercise() -> None:
        with CompletionScope() as scope:
            key = CompletionKey(object(), "focus.applied", request=object())
            completion = scope.expect(key)
            completion.succeed(key, "focused")
            with pytest.raises(RuntimeError, match="event loop"):
                completion.wait_sync(deadline=scope.now() + 1, description="focus")

    asyncio.run(exercise())


def test_scope_rejects_duplicate_registration_for_one_exact_phase() -> None:
    with (
        pytest.raises(_completion.CompletionProtocolError, match="registered"),
        CompletionScope() as scope,
    ):
        key = CompletionKey(object(), "navigation.applied", request=object())
        first = scope.expect(key)
        equal_key = CompletionKey(key.owner, key.phase, request=key.request)
        assert scope.expect(equal_key) is first


@pytest.mark.parametrize("kind", ["asyncio", "concurrent"])
@pytest.mark.parametrize("ending", ["timeout", "observer_cancel", "scope_close"])
def test_observer_exit_does_not_cancel_shared_future(kind: str, ending: str) -> None:
    async def exercise() -> None:
        with CompletionScope() as scope:
            loop = asyncio.get_running_loop()
            producer: asyncio.Future[str] | Future[str] = (
                loop.create_future() if kind == "asyncio" else Future()
            )
            completion = scope.observe_future(
                producer, owner=object(), phase="worker.source"
            )
            if ending == "timeout":
                with pytest.raises(CompletionTimeout):
                    await completion.wait(deadline=scope.now(), description="source")
            elif ending == "observer_cancel":
                current = asyncio.current_task()
                assert current is not None
                loop.call_soon(current.cancel)
                with pytest.raises(asyncio.CancelledError):
                    await completion.wait(
                        deadline=scope.now() + 1, description="source"
                    )
            else:
                scope.close()
            assert not producer.done()
            producer.set_result("producer survives")
            assert producer.result() == "producer survives"
            assert completion.snapshot() is None

    asyncio.run(exercise())


@pytest.mark.parametrize("kind", ["asyncio", "concurrent"])
@pytest.mark.parametrize("terminal", ["error", "cancelled"])
def test_future_adapter_retains_real_failure_or_cancellation(
    kind: str, terminal: str
) -> None:
    async def exercise() -> None:
        with CompletionScope() as scope:
            producer: asyncio.Future[str] | Future[str] = (
                asyncio.get_running_loop().create_future()
                if kind == "asyncio"
                else Future()
            )
            completion = scope.observe_future(
                producer, owner=object(), phase="worker.source"
            )
            error = ValueError("original error")
            expected: type[Exception]
            if terminal == "error":
                producer.set_exception(error)
                expected = ValueError
            else:
                producer.cancel()
                expected = _completion.CompletionCancelled
            with pytest.raises(expected) as raised:
                await completion.wait(deadline=scope.now() + 1, description="source")
            if terminal == "error":
                assert raised.value is error

    asyncio.run(exercise())


def test_existing_worker_thread_publishes_state_before_waking_async_waiter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def exercise() -> None:
        with CompletionScope() as scope, ThreadPoolExecutor(max_workers=1) as worker:
            release = threading.Event()

            def produce() -> str:
                assert release.wait(1)
                return "worker result"

            producer = worker.submit(produce)
            completion = scope.observe_future(
                producer, owner=worker, phase="worker.source"
            )
            wake = _completion._wake
            observed: list[str] = []

            def inspect_before_wake(waiter: asyncio.Future[None]) -> None:
                outcome = completion.snapshot()
                assert outcome is not None
                assert outcome.value is not None
                observed.append(outcome.value)
                wake(waiter)

            monkeypatch.setattr(_completion, "_wake", inspect_before_wake)
            asyncio.get_running_loop().call_soon(release.set)
            assert (
                await completion.wait(
                    deadline=scope.now() + 1, description="thread source"
                )
                == "worker result"
            )
            assert observed == ["worker result"]

    asyncio.run(exercise())


def test_cross_thread_disposal_detaches_on_the_asyncio_future_owner() -> None:
    async def exercise() -> None:
        loop = asyncio.get_running_loop()
        detached = loop.create_future()

        class OwnedFuture(asyncio.Future[str]):
            def remove_done_callback(self, callback: Callable[..., object]) -> int:
                assert asyncio.get_running_loop() is loop
                count = super().remove_done_callback(callback)
                detached.set_result(count)
                return count

        producer = OwnedFuture()
        scope = CompletionScope()
        completion = scope.observe_future(
            producer, owner=object(), phase="worker.source"
        )
        await asyncio.to_thread(scope.close)
        assert await asyncio.wait_for(detached, 1) == 1
        producer.set_result("survives")
        assert completion.snapshot() is None

    asyncio.run(exercise())


@pytest.mark.parametrize("deadline", [float("nan"), float("inf"), -float("inf")])
def test_nonfinite_deadline_is_rejected_even_for_retained_success(
    deadline: float,
) -> None:
    async def exercise() -> None:
        with CompletionScope(clock=lambda: 10.0) as scope:
            key = CompletionKey(object(), "worker.source", generation=1)
            completion = scope.expect(key)
            completion.succeed(key, "already complete")
            with pytest.raises(ValueError, match="finite"):
                await completion.wait(deadline=deadline, description="source")

    asyncio.run(exercise())


def test_wrong_identity_wakes_waiter_without_waiting_for_its_behavior_deadline() -> (
    None
):
    async def exercise() -> None:
        scope = CompletionScope()
        key = CompletionKey(object(), "navigation.applied", request=object())
        completion = scope.expect(key)
        wrong = CompletionKey(key.owner, key.phase, request=object())
        asyncio.get_running_loop().call_soon(completion.succeed, wrong, "wrong")
        try:
            with pytest.raises(_completion.CompletionProtocolError, match="identity"):
                await asyncio.wait_for(
                    completion.wait(deadline=scope.now() + 10, description="apply"),
                    timeout=0.1,
                )
        finally:
            scope.close()

    asyncio.run(exercise())


@pytest.mark.parametrize("first", ["success", "error", "cancelled", "superseded"])
@pytest.mark.parametrize("second", ["success", "error", "cancelled", "superseded"])
def test_every_conflicting_terminal_preserves_the_first_record(
    first: str, second: str
) -> None:
    scope = CompletionScope(clock=lambda: 3.0)
    key = CompletionKey(object(), "worker.returned", request=object())
    completion = scope.expect(key)

    def publish(status: str) -> bool:
        if status == "success":
            return completion.succeed(key, "first value")
        if status == "error":
            return completion.fail(key, ValueError("source failed"))
        if status == "cancelled":
            return completion.cancel(key)
        return completion.supersede(key)

    assert publish(first) is True
    retained = completion.snapshot()
    assert publish(second) is False
    assert completion.snapshot() is retained
    assert retained is not None
    assert retained.status.value == first
    with pytest.raises(_completion.CompletionProtocolError, match="duplicate"):
        scope.raise_if_invalid()
    scope.close()


def test_competing_publications_have_one_atomic_winner() -> None:
    scope = CompletionScope()
    key = CompletionKey(object(), "worker.source", request=object())
    completion = scope.expect(key)
    ready = threading.Barrier(2)

    def publish(value: str) -> bool:
        ready.wait(timeout=1)
        return completion.succeed(key, value)

    with ThreadPoolExecutor(max_workers=2) as workers:
        first = workers.submit(publish, "one")
        second = workers.submit(publish, "two")
        accepted = [first.result(timeout=1), second.result(timeout=1)]
    assert sorted(accepted) == [False, True]
    outcome = completion.snapshot()
    assert outcome is not None
    assert outcome.value == ("one" if accepted[0] else "two")
    with pytest.raises(_completion.CompletionProtocolError, match="duplicate"):
        scope.raise_if_invalid()
    scope.close()


def test_sync_spurious_wake_preserves_the_absolute_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = 10.0
    with CompletionScope(clock=lambda: now) as scope:
        key = CompletionKey(object(), "lease.restored", request=object())
        completion = scope.expect(key)
        first_wait, second_wait = threading.Event(), threading.Event()
        remaining: list[float | None] = []
        real_wait = completion._condition.wait

        def mark_wait(timeout: float | None = None) -> bool:
            remaining.append(timeout)
            (first_wait if len(remaining) == 1 else second_wait).set()
            return real_wait(timeout)

        # Only this helper's condition is instrumented. No shared threading patch.
        monkeypatch.setattr(completion._condition, "wait", mark_wait)
        with ThreadPoolExecutor(max_workers=1) as worker:
            result = worker.submit(
                completion.wait_sync, deadline=12.0, description="restore"
            )
            assert first_wait.wait(1)
            with completion._condition:
                now = 11.0
                completion._condition.notify_all()
            assert second_wait.wait(1)
            with completion._condition:
                now = 12.0
                completion.succeed(key, "restored")
            assert result.result(timeout=1) == "restored"
        assert remaining == [2.0, 1.0]


def test_scope_error_does_not_replace_primary_test_failure() -> None:
    original = ValueError("primary failure")
    with pytest.raises(ValueError) as raised, CompletionScope() as scope:
        key = CompletionKey(object(), "worker.source", generation=1)
        completion = scope.expect(key)
        completion.succeed(key, "once")
        completion.succeed(key, "duplicate")
        raise original
    assert raised.value is original
    assert completion.succeed(key, "late") is False


def test_scope_close_is_idempotent_and_prevents_new_observation() -> None:
    scope = CompletionScope()
    scope.close()
    scope.close()
    with pytest.raises(_completion.CompletionDisposed):
        scope.expect(CompletionKey(object(), "worker.source", generation=1))


def test_disposal_at_wait_registration_cannot_install_an_unnotified_waiter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def exercise() -> None:
        scope = CompletionScope()
        key = CompletionKey(object(), "worker.source", generation=1)
        completion = scope.expect(key)
        begin = completion._begin_wait

        def dispose_after_registration(deadline: float) -> None:
            begin(deadline)
            completion.dispose()

        monkeypatch.setattr(completion, "_begin_wait", dispose_after_registration)
        pending = completion.wait(deadline=scope.now() + 1, description="source")
        try:
            with pytest.raises(_completion.CompletionDisposed):
                pending.send(None)
        finally:
            pending.close()
            scope.close()

    asyncio.run(exercise())


def test_scope_retains_protocol_failure_after_releasing_its_records() -> None:
    scope = CompletionScope()
    key = CompletionKey(object(), "worker.source", generation=1)
    completion = scope.expect(key)
    completion.succeed(key, "first")
    completion.succeed(key, "duplicate")
    reference = weakref.ref(completion)
    del completion
    scope.close()
    gc.collect()
    assert reference() is None
    with pytest.raises(_completion.CompletionProtocolError, match="duplicate"):
        scope.raise_if_invalid()


def test_disposal_before_future_subscription_does_not_install_a_late_callback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registrations: list[Callable[..., object]] = []

    class RetainedFuture(Future[str]):
        def add_done_callback(self, fn: Callable[[Future[str]], object]) -> None:
            registrations.append(fn)
            super().add_done_callback(fn)

    scope = CompletionScope()
    expect = scope.expect

    def dispose_before_subscription(key: CompletionKey) -> _completion.Completion[str]:
        completion = expect(key)
        scope.close()
        return completion

    monkeypatch.setattr(scope, "expect", dispose_before_subscription)
    producer = RetainedFuture()
    completion = scope.observe_future(producer, owner=object(), phase="worker.source")
    assert registrations == []
    producer.set_result("late real result")
    assert completion.snapshot() is None


@pytest.mark.parametrize("publication_time", [9.0, 10.0, 11.0])
def test_sync_wait_uses_the_same_retained_publication_deadline(
    publication_time: float,
) -> None:
    with CompletionScope(clock=lambda: publication_time) as scope:
        key = CompletionKey(object(), "worker.source", generation=1)
        completion = scope.expect(key)
        completion.succeed(key, "result")
        if publication_time <= 10.0:
            assert completion.wait_sync(deadline=10.0, description="source") == "result"
        else:
            with pytest.raises(CompletionTimeout):
                completion.wait_sync(deadline=10.0, description="source")
            assert completion.succeed(key, "late") is False


def test_sync_expiry_disposes_observation_without_cancelling_producer() -> None:
    with CompletionScope(clock=lambda: 10.0) as scope:
        producer: Future[str] = Future()
        completion = scope.observe_future(
            producer, owner=object(), phase="worker.source"
        )
        with pytest.raises(CompletionTimeout):
            completion.wait_sync(deadline=10.0, description="source")
        producer.set_result("actual result")
        assert producer.result() == "actual result"
        assert completion.snapshot() is None


def test_equal_but_distinct_owner_and_request_cannot_satisfy_identity() -> None:
    class EqualObject:
        def __eq__(self, other: object) -> bool:
            return isinstance(other, EqualObject)

    scope = CompletionScope()
    key = CompletionKey(EqualObject(), "navigation.applied", request=EqualObject())
    completion = scope.expect(key)
    assert (
        completion.succeed(
            CompletionKey(EqualObject(), key.phase, request=EqualObject()), "wrong"
        )
        is False
    )
    assert completion.snapshot() is None
    scope.close()


def test_retained_outcome_is_an_immutable_record() -> None:
    with CompletionScope() as scope:
        key = CompletionKey(object(), "worker.source", generation=1)
        completion = scope.expect(key)
        completion.succeed(key, "actual result")
        outcome = completion.snapshot()
        assert outcome is not None
        with pytest.raises(FrozenInstanceError):
            outcome.published_at = 0.0  # type: ignore[misc]  # Verify runtime immutability.
