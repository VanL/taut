"""Test-local retained observations, never a second owner of product work.

Register exact owner/request/phase handles before the initiating action, then
publish after the real callback. Compute every absolute deadline with scope.now().
There are no predicates, domain reads, action retries, or default time budgets.
Scope closure disables observers only; product stop/join remains the test's job.
"""

from __future__ import annotations

import asyncio
import math
import threading
import time
import weakref
from collections.abc import Callable
from concurrent.futures import Future as ConcurrentFuture
from dataclasses import dataclass
from enum import Enum
from types import TracebackType
from typing import Any, Generic, Self, TypeVar, cast

T = TypeVar("T")


class CompletionStatus(Enum):
    SUCCESS = "success"
    ERROR = "error"
    CANCELLED = "cancelled"
    SUPERSEDED = "superseded"


@dataclass(frozen=True, eq=False)
class CompletionKey:
    """Object identities plus value-based phase/generation, held against reuse."""

    owner: object
    phase: str
    request: object | None = None
    generation: int | None = None

    def __post_init__(self) -> None:
        if not self.phase or (self.request is None and self.generation is None):
            raise ValueError("completion requires a phase and a request or generation")

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, CompletionKey):
            return NotImplemented
        return (
            self.owner is other.owner
            and self.request is other.request
            and self.phase == other.phase
            and self.generation == other.generation
        )

    def __hash__(self) -> int:
        return hash((id(self.owner), id(self.request), self.phase, self.generation))


class CompletionProtocolError(AssertionError):
    """An observer violated its exact-identity or once-only contract."""


class CompletionTimeout(TimeoutError):
    """The named phase did not publish within its absolute deadline."""


class CompletionCancelled(RuntimeError):
    """The producer cancelled, distinct from cancelling the observing task."""


class CompletionSuperseded(RuntimeError):
    """The exact observed request was superseded, not the newer request."""


class CompletionDisposed(RuntimeError):
    """Observation was disposed without changing the producer."""


def _wake(waiter: asyncio.Future[None]) -> None:
    if not waiter.done():
        waiter.set_result(None)


def _notify(
    waiter: tuple[asyncio.AbstractEventLoop, asyncio.Future[None]] | None,
) -> None:
    if waiter is not None:
        try:
            waiter[0].call_soon_threadsafe(_wake, waiter[1])
        except RuntimeError:
            # A loop may close after disposal took its waiter snapshot.
            if not waiter[0].is_closed():
                raise


def _detach_async_future(
    source: asyncio.Future[T], callback: Callable[[asyncio.Future[T]], object]
) -> None:
    loop = source.get_loop()
    try:
        current_loop = asyncio.get_running_loop()
    except RuntimeError:
        current_loop = None
    if current_loop is loop:
        source.remove_done_callback(callback)
    elif not loop.is_closed():
        try:
            loop.call_soon_threadsafe(source.remove_done_callback, callback)
        except RuntimeError:
            if not loop.is_closed():
                raise


@dataclass(frozen=True)
class CompletionOutcome(Generic[T]):
    key: CompletionKey
    status: CompletionStatus
    published_at: float
    value: T | None = None
    error: BaseException | None = None


class Completion(Generic[T]):
    """One immutable outcome and at most one active sync or async observer wait.

    Terminal publication is thread-safe and never raises an observer protocol error
    through the producer. Inspect violations with wait or the owning scope. A timeout
    or observing-task cancellation disables this observation, never its producer.
    """

    def __init__(self, key: CompletionKey, clock: Callable[[], float]) -> None:
        self.key = key
        self._clock = clock
        self._outcome: CompletionOutcome[T] | None = None
        self._violation: str | None = None
        self._condition = threading.Condition()
        self._waiter: tuple[asyncio.AbstractEventLoop, asyncio.Future[None]] | None = (
            None
        )
        self._active = True
        self._waiting = False
        self._detach: Callable[[], object] | None = None

    def snapshot(self) -> CompletionOutcome[T] | None:
        with self._condition:
            return self._outcome

    def succeed(self, key: CompletionKey, value: T) -> bool:
        return self._publish(key, CompletionStatus.SUCCESS, value=value)

    def fail(self, key: CompletionKey, error: BaseException) -> bool:
        return self._publish(key, CompletionStatus.ERROR, error=error)

    def cancel(self, key: CompletionKey) -> bool:
        return self._publish(key, CompletionStatus.CANCELLED)

    def supersede(self, key: CompletionKey) -> bool:
        return self._publish(key, CompletionStatus.SUPERSEDED)

    def _publish(
        self,
        key: CompletionKey,
        status: CompletionStatus,
        *,
        value: T | None = None,
        error: BaseException | None = None,
    ) -> bool:
        with self._condition:
            if not self._active:
                return False
            if key != self.key:
                self._invalidate("completion identity mismatch")
                return False
            if self._outcome is not None:
                self._invalidate("duplicate terminal publication")
                return False
            self._outcome = CompletionOutcome(
                self.key, status, self._clock(), value=value, error=error
            )
            waiter = self._waiter
            self._condition.notify_all()
        _notify(waiter)
        return True

    def _invalidate(self, message: str) -> None:
        with self._condition:
            self._violation = self._violation or f"{self.key.phase}: {message}"
            waiter = self._waiter
            self._condition.notify_all()
        _notify(waiter)

    def dispose(self) -> None:
        with self._condition:
            self._active = False
            detach, self._detach = self._detach, None
            waiter = self._waiter
            self._condition.notify_all()
        if detach is not None:
            detach()
        _notify(waiter)

    def _capture_future(self, source: asyncio.Future[T] | ConcurrentFuture[T]) -> None:
        with self._condition:
            if not self._active:
                return
            if source.cancelled():
                self.cancel(self.key)
                return
            try:
                value = source.result()
            except BaseException as error:  # noqa: BLE001 - retain for the observing caller
                self.fail(self.key, error)
            else:
                self.succeed(self.key, value)

    def _raise_if_invalid(self) -> None:
        with self._condition:
            if self._violation is not None:
                raise CompletionProtocolError(self._violation)

    async def wait(self, *, deadline: float, description: str) -> T:
        loop = asyncio.get_running_loop()
        with self._condition:
            self._begin_wait(deadline)
        try:
            with self._condition:
                self._raise_if_invalid()
                if not self._active or self._outcome is not None:
                    return self._result(deadline, description)
                wake = loop.create_future()
                self._waiter = (loop, wake)
            try:
                await asyncio.wait_for(wake, max(0.0, deadline - self._clock()))
            except TimeoutError:
                pass
            with self._condition:
                self._raise_if_invalid()
                return self._result(deadline, description)
        except (CompletionTimeout, asyncio.CancelledError):
            self.dispose()
            raise
        finally:
            with self._condition:
                self._waiter = None
                self._waiting = False

    def _begin_wait(self, deadline: float) -> None:
        if not math.isfinite(deadline):
            raise ValueError("completion deadline must be finite")
        self._raise_if_invalid()
        if not self._active:
            raise CompletionDisposed(self.key.phase)
        if self._waiting:
            raise CompletionProtocolError(
                f"{self.key.phase}: already has an active wait"
            )
        self._waiting = True

    def _result(self, deadline: float, description: str) -> T:
        if not self._active:
            raise CompletionDisposed(self.key.phase)
        outcome = self._outcome
        if outcome is None or outcome.published_at > deadline:
            raise CompletionTimeout(f"{description}: {self.key.phase}")
        if outcome.status is CompletionStatus.ERROR:
            assert outcome.error is not None
            raise outcome.error
        if outcome.status is CompletionStatus.CANCELLED:
            raise CompletionCancelled(f"{description}: {self.key.phase}")
        if outcome.status is CompletionStatus.SUPERSEDED:
            raise CompletionSuperseded(f"{description}: {self.key.phase}")
        return cast(T, outcome.value)

    def wait_sync(self, *, deadline: float, description: str) -> T:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            pass
        else:
            raise RuntimeError("wait_sync cannot run on an event loop thread")
        with self._condition:
            self._begin_wait(deadline)
        try:
            with self._condition:
                while self._outcome is None:
                    self._raise_if_invalid()
                    if not self._active or self._clock() >= deadline:
                        break
                    self._condition.wait(deadline - self._clock())
                self._raise_if_invalid()
                return self._result(deadline, description)
        except CompletionTimeout:
            self.dispose()
            raise
        finally:
            with self._condition:
                self._waiting = False


class CompletionScope:
    """Finite test/run ownership; successful context exit checks protocol errors.

    Optional/background records need not finish. Only an explicit wait requires a
    phase by its deadline. At most 4096 records are retained per scope; overflow
    fails the test rather than evicting an outcome or growing without bound.
    The scope drops its record references when closed.
    """

    def __init__(self, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._records: dict[CompletionKey, Completion[Any]] = {}
        self._lock = threading.RLock()
        self._closed = False
        self._violation: str | None = None

    def now(self) -> float:
        return self._clock()

    def expect(self, key: CompletionKey) -> Completion[Any]:
        with self._lock:
            if self._closed:
                raise CompletionDisposed("completion scope is closed")
            existing = self._records.get(key)
            if existing is not None:
                existing._invalidate("already registered")
                return existing
            if len(self._records) >= 4096:
                self._violation = "completion history capacity exceeded (4096)"
                raise CompletionProtocolError(self._violation)
            record: Completion[Any] = Completion(key, self._clock)
            self._records[key] = record
            return record

    def raise_if_invalid(self) -> None:
        with self._lock:
            if self._violation is not None:
                raise CompletionProtocolError(self._violation)
            for record in self._records.values():
                record._raise_if_invalid()

    def close(self) -> None:
        with self._lock:
            self._closed = True
            records, self._records = self._records, {}
            for record in records.values():
                record.dispose()
                self._violation = self._violation or record._violation

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()
        if exc_type is None:
            self.raise_if_invalid()

    def observe_future(
        self,
        source: asyncio.Future[T] | ConcurrentFuture[T],
        *,
        owner: object,
        phase: str,
        generation: int | None = None,
    ) -> Completion[T]:
        """Observe a retained future, with its own identity and no backdating.

        For asyncio futures, register in their owning loop just like add_done_callback.
        Concurrent-future callbacks keep only a weak record reference because that API
        cannot remove callbacks. Do not pass a lazy coroutine or framework awaitable.
        """
        record: Completion[T] = self.expect(
            CompletionKey(owner, phase, source, generation)
        )
        reference = weakref.ref(record)

        def completed(future: asyncio.Future[T] | ConcurrentFuture[T]) -> None:
            retained = reference()
            if retained is not None:
                retained._capture_future(future)

        with record._condition:
            if record._active:
                if isinstance(source, asyncio.Future):
                    record._detach = lambda: _detach_async_future(source, completed)
                source.add_done_callback(completed)
        return record
