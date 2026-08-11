"""Firing tests for eventual-evidence synchronization [DOM-10.3]."""

from __future__ import annotations

import asyncio
from collections.abc import Callable

import pytest

from tests.helpers import eventually as eventually_module

pytestmark = pytest.mark.sqlite_only


class _FakeTime:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, delay: float) -> None:
        self.sleeps.append(delay)
        self.now += delay

    async def async_sleep(self, delay: float) -> None:
        self.sleep(delay)


class _BrokenRepr:
    def __repr__(self) -> str:
        raise LookupError("repr unavailable")


def _raise_snapshot_error() -> object:
    raise RuntimeError("snapshot unavailable")


def test_eventually_returns_immediately_without_waiting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    predicate_calls = 0
    snapshot_calls = 0

    def predicate() -> bool:
        nonlocal predicate_calls
        predicate_calls += 1
        return True

    def snapshot() -> object:
        nonlocal snapshot_calls
        snapshot_calls += 1
        return {"state": "unexpected"}

    def unexpected_sleep(_delay: float) -> None:
        raise AssertionError("immediate evidence must not sleep")

    monkeypatch.setattr(eventually_module, "_sleep", unexpected_sleep)

    eventually_module.eventually(
        predicate,
        timeout=1.0,
        description="immediate evidence",
        snapshot=snapshot,
    )
    assert predicate_calls == 1
    assert snapshot_calls == 0


def test_eventually_observes_until_evidence_appears(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_time = _FakeTime()
    outcomes = iter((False, False, True))
    monkeypatch.setattr(eventually_module, "_monotonic", fake_time.monotonic)
    monkeypatch.setattr(eventually_module, "_sleep", fake_time.sleep)

    eventually_module.eventually(
        lambda: next(outcomes),
        timeout=0.25,
        interval=0.1,
        description="scripted evidence",
    )

    assert fake_time.sleeps == [0.1, 0.1]


def test_eventually_uses_one_deadline_and_reports_timeout_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_time = _FakeTime()
    predicate_calls = 0

    def predicate() -> bool:
        nonlocal predicate_calls
        predicate_calls += 1
        return False

    monkeypatch.setattr(eventually_module, "_monotonic", fake_time.monotonic)
    monkeypatch.setattr(eventually_module, "_sleep", fake_time.sleep)

    with pytest.raises(AssertionError) as raised:
        eventually_module.eventually(
            predicate,
            timeout=0.25,
            interval=0.1,
            description="never-visible evidence",
        )

    message = str(raised.value)
    assert "never-visible evidence" in message
    assert "timeout=0.25s" in message
    assert "elapsed=0.25s" in message
    assert "polls=5" in message
    assert fake_time.sleeps == pytest.approx([0.1, 0.1, 0.05])
    assert predicate_calls == 5


def test_eventually_succeeds_when_evidence_appears_on_final_recheck(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_time = _FakeTime()
    outcomes = iter((False, False, True))
    monkeypatch.setattr(eventually_module, "_monotonic", fake_time.monotonic)
    monkeypatch.setattr(eventually_module, "_sleep", fake_time.sleep)

    eventually_module.eventually(
        lambda: next(outcomes),
        timeout=0.1,
        interval=0.1,
        description="deadline evidence",
    )

    assert fake_time.sleeps == [0.1]


def test_eventually_adds_snapshot_only_to_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_time = _FakeTime()
    snapshot_calls = 0

    def snapshot() -> object:
        nonlocal snapshot_calls
        snapshot_calls += 1
        return {"thread_alive": True, "seen": 0}

    monkeypatch.setattr(eventually_module, "_monotonic", fake_time.monotonic)
    monkeypatch.setattr(eventually_module, "_sleep", fake_time.sleep)

    with pytest.raises(AssertionError) as raised:
        eventually_module.eventually(
            lambda: False,
            timeout=0.1,
            interval=0.1,
            description="snapshot evidence",
            snapshot=snapshot,
        )

    assert snapshot_calls == 1
    assert "snapshot={'thread_alive': True, 'seen': 0}" in str(raised.value)


@pytest.mark.parametrize(
    ("snapshot", "error_type"),
    [
        (_raise_snapshot_error, "RuntimeError"),
        (lambda: _BrokenRepr(), "LookupError"),
    ],
)
def test_eventually_keeps_snapshot_failure_secondary(
    monkeypatch: pytest.MonkeyPatch,
    snapshot: Callable[[], object],
    error_type: str,
) -> None:
    fake_time = _FakeTime()
    monkeypatch.setattr(eventually_module, "_monotonic", fake_time.monotonic)
    monkeypatch.setattr(eventually_module, "_sleep", fake_time.sleep)

    with pytest.raises(AssertionError) as raised:
        eventually_module.eventually(
            lambda: False,
            timeout=0.1,
            interval=0.1,
            description="snapshot failure",
            snapshot=snapshot,
        )

    message = str(raised.value)
    assert "timed out waiting for snapshot failure" in message
    assert f"snapshot failed: {error_type}" in message


@pytest.mark.parametrize(
    ("timeout", "interval", "description", "field"),
    [
        (0.0, 0.1, "evidence", "timeout"),
        (-1.0, 0.1, "evidence", "timeout"),
        (float("inf"), 0.1, "evidence", "timeout"),
        (float("nan"), 0.1, "evidence", "timeout"),
        (1.0, 0.0, "evidence", "interval"),
        (1.0, -1.0, "evidence", "interval"),
        (1.0, float("inf"), "evidence", "interval"),
        (1.0, float("nan"), "evidence", "interval"),
        (1.0, 0.1, "  ", "description"),
    ],
)
def test_eventually_rejects_invalid_configuration_before_observation(
    timeout: float,
    interval: float,
    description: str,
    field: str,
) -> None:
    predicate_calls = 0

    def predicate() -> bool:
        nonlocal predicate_calls
        predicate_calls += 1
        return False

    with pytest.raises(ValueError, match=field):
        eventually_module.eventually(
            predicate,
            timeout=timeout,
            interval=interval,
            description=description,
        )

    assert predicate_calls == 0


def test_async_eventually_returns_immediately_without_yielding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def unexpected_sleep(_delay: float) -> None:
        raise AssertionError("immediate evidence must not yield")

    monkeypatch.setattr(eventually_module, "_async_sleep", unexpected_sleep)

    async def scenario() -> None:
        await eventually_module.async_eventually(
            lambda: True,
            timeout=1.0,
            description="immediate async evidence",
        )

    asyncio.run(scenario())


def test_async_eventually_matches_sync_deadline_and_diagnostics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_time = _FakeTime()
    predicate_calls = 0

    def predicate() -> bool:
        nonlocal predicate_calls
        predicate_calls += 1
        return False

    monkeypatch.setattr(eventually_module, "_monotonic", fake_time.monotonic)
    monkeypatch.setattr(eventually_module, "_async_sleep", fake_time.async_sleep)

    async def scenario() -> None:
        with pytest.raises(AssertionError) as raised:
            await eventually_module.async_eventually(
                predicate,
                timeout=0.15,
                interval=0.1,
                description="async deadline evidence",
                snapshot=lambda: {"pending": 2},
            )

        message = str(raised.value)
        assert "async deadline evidence" in message
        assert "timeout=0.15s" in message
        assert "elapsed=0.15s" in message
        assert "polls=4" in message
        assert "snapshot={'pending': 2}" in message

    asyncio.run(scenario())

    assert fake_time.sleeps == pytest.approx([0.1, 0.05])
    assert predicate_calls == 4


def test_predicate_exceptions_propagate_from_both_interfaces(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class SentinelError(Exception):
        pass

    sentinel = SentinelError("predicate failed")
    snapshot_calls = 0

    def predicate() -> bool:
        raise sentinel

    def snapshot() -> object:
        nonlocal snapshot_calls
        snapshot_calls += 1
        return "unexpected"

    with pytest.raises(SentinelError) as sync_raised:
        eventually_module.eventually(
            predicate,
            timeout=1.0,
            description="sync predicate failure",
            snapshot=snapshot,
        )

    async def scenario() -> None:
        with pytest.raises(SentinelError) as async_raised:
            await eventually_module.async_eventually(
                predicate,
                timeout=1.0,
                description="async predicate failure",
                snapshot=snapshot,
            )
        assert async_raised.value is sentinel

    asyncio.run(scenario())

    assert sync_raised.value is sentinel
    assert snapshot_calls == 0


def test_async_eventually_succeeds_on_final_recheck(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_time = _FakeTime()
    outcomes = iter((False, False, True))
    monkeypatch.setattr(eventually_module, "_monotonic", fake_time.monotonic)
    monkeypatch.setattr(eventually_module, "_async_sleep", fake_time.async_sleep)

    async def scenario() -> None:
        await eventually_module.async_eventually(
            lambda: next(outcomes),
            timeout=0.1,
            interval=0.1,
            description="async deadline evidence",
        )

    asyncio.run(scenario())

    assert fake_time.sleeps == [0.1]


def test_async_eventually_propagates_cancellation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        sleep_started = asyncio.Event()

        async def blocked_sleep(_delay: float) -> None:
            sleep_started.set()
            await asyncio.Future()

        monkeypatch.setattr(eventually_module, "_async_sleep", blocked_sleep)
        task = asyncio.create_task(
            eventually_module.async_eventually(
                lambda: False,
                timeout=1.0,
                description="cancelled evidence",
            )
        )
        await sleep_started.wait()
        task.cancel()

        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())
