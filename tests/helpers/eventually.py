"""Repository-only eventual-evidence synchronization [DOM-10.3]."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from math import isfinite

_monotonic = time.monotonic
_sleep = time.sleep
_async_sleep = asyncio.sleep


def _validate_configuration(
    *, timeout: float, interval: float, description: str
) -> None:
    if not isfinite(timeout) or timeout <= 0:
        raise ValueError("timeout must be positive and finite")
    if not isfinite(interval) or interval <= 0:
        raise ValueError("interval must be positive and finite")
    if not description.strip():
        raise ValueError("description must not be blank")


def _snapshot_suffix(snapshot: Callable[[], object] | None) -> str:
    if snapshot is None:
        return ""
    try:
        value = snapshot()
        rendered = repr(value)
    except Exception as exc:  # noqa: BLE001 approved [DOM-10.2.1] [RUFF-SUP-084] exception
        return f"; snapshot failed: {type(exc).__name__}"
    return f"; snapshot={rendered}"


class _PollState:
    def __init__(self, *, timeout: float, interval: float, description: str) -> None:
        _validate_configuration(
            timeout=timeout,
            interval=interval,
            description=description,
        )
        self.timeout = timeout
        self.interval = interval
        self.description = description
        self.started = _monotonic()
        self.deadline = self.started + timeout
        self.polls = 0

    def observe(self, predicate: Callable[[], bool]) -> bool:
        self.polls += 1
        return bool(predicate())

    def next_delay(self) -> float | None:
        remaining = self.deadline - _monotonic()
        if remaining <= 0:
            return None
        return min(self.interval, remaining)

    def timeout_error(
        self,
        snapshot: Callable[[], object] | None,
    ) -> AssertionError:
        elapsed = max(0.0, _monotonic() - self.started)
        return AssertionError(
            f"timed out waiting for {self.description}; "
            f"timeout={self.timeout:g}s; elapsed={elapsed:g}s; polls={self.polls}"
            f"{_snapshot_suffix(snapshot)}"
        )


def eventually(
    predicate: Callable[[], bool],
    *,
    timeout: float,
    description: str,
    interval: float = 0.01,
    snapshot: Callable[[], object] | None = None,
) -> None:
    """Wait until an observational predicate exposes positive evidence."""
    state = _PollState(
        timeout=timeout,
        interval=interval,
        description=description,
    )
    if state.observe(predicate):
        return
    while (delay := state.next_delay()) is not None:
        _sleep(delay)
        if state.observe(predicate):
            return
    if state.observe(predicate):
        return
    raise state.timeout_error(snapshot)


async def async_eventually(
    predicate: Callable[[], bool],
    *,
    timeout: float,
    description: str,
    interval: float = 0.01,
    snapshot: Callable[[], object] | None = None,
) -> None:
    """Yield until an observational predicate exposes positive evidence."""
    state = _PollState(
        timeout=timeout,
        interval=interval,
        description=description,
    )
    if state.observe(predicate):
        return
    while (delay := state.next_delay()) is not None:
        await _async_sleep(delay)
        if state.observe(predicate):
            return
    if state.observe(predicate):
        return
    raise state.timeout_error(snapshot)
