"""Summon's retained-delivery specialization of the shared watcher.

The blocking injection owns no broker handles. Its immutable completion is
applied by the watcher owner before another queue turn ([SUM-5.4]).
"""

from __future__ import annotations

import queue
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from taut import WatcherRejected
from taut.client import Message, Notification
from taut.watcher import QueueRuntimeConfig, TautWatcher
from taut_summon._adapter import AdapterHandle


@dataclass(frozen=True, slots=True)
class PreparedInjection:
    handle: AdapterHandle
    text: str
    generation: int


@dataclass(frozen=True, slots=True)
class _DeliveryResult:
    serial: int
    generation: int
    error: BaseException | None


class SummonReactor(TautWatcher):
    """One pending delivery, using the existing watcher cursor policy."""

    def __init__(
        self,
        runtime: Any,
        member_id: str,
        handler: Callable[[Message | Notification], None],
        **kwargs: Any,
    ) -> None:
        self.prepare_delivery: (
            Callable[[Message | Notification], PreparedInjection | None] | None
        ) = None
        self.current_generation: Callable[[], int] = lambda: 0
        self._delivery_serial = 0
        self._delivery_pending: int | None = None
        self._delivery_cursor: tuple[str, int] | None = None
        self._delivery_results: queue.SimpleQueue[_DeliveryResult] = queue.SimpleQueue()
        self._delivery_thread: threading.Thread | None = None
        self._delivery_prepared: PreparedInjection | None = None
        self.delivery_error: Callable[[BaseException], None] | None = None
        self.control_queue_name: str | None = None
        self.delivery_enabled = True
        self.owner_turn: Callable[[], None] | None = None
        self.owner_wait_timeout: Callable[[], float | None] | None = None
        super().__init__(runtime, member_id, self._begin_delivery, **kwargs)

    def _begin_delivery(self, item: Message | Notification) -> None:
        if self._delivery_pending is not None:
            raise RuntimeError("delivery dispatch while injection is pending")
        prepare = self.prepare_delivery
        if prepare is None:
            raise RuntimeError("Summon injection preparation was not configured")
        prepared = prepare(item)
        if prepared is None:
            return
        self._delivery_serial += 1
        serial = self._delivery_serial
        self._delivery_pending = serial
        self._delivery_prepared = prepared

        def inject() -> None:
            error: BaseException | None = None
            try:
                prepared.handle.inject(prepared.text)
            except BaseException as exc:  # noqa: BLE001 - transfer every worker failure to owner
                error = exc
            finally:
                self._delivery_results.put(
                    _DeliveryResult(serial, prepared.generation, error)
                )
                self.notify_activity()

        self._delivery_thread = threading.Thread(
            target=inject, name="taut-summon-inject", daemon=True
        )
        try:
            self._delivery_thread.start()
        except BaseException as error:
            self._delivery_thread = None
            self._delivery_pending = None
            self._delivery_prepared = None
            self._delivery_cursor = None
            if isinstance(error, Exception):
                raise WatcherRejected("injection worker could not start") from error
            raise

    def _advance(self, thread: str, timestamp: int) -> None:
        if self._delivery_pending is not None:
            self._delivery_cursor = (thread, timestamp)
            return
        super()._advance(thread, timestamp)

    def _queue_counts_as_wait_activity(self, config: QueueRuntimeConfig) -> bool:
        return (
            self.delivery_enabled and self._delivery_pending is None
        ) or config.name == self.control_queue_name

    def _fetch_next_message(self, config: QueueRuntimeConfig) -> tuple[str, int] | None:
        # The hook above filters discovery and wait, but an already-active PEEK
        # lane can still be reached later in this same dispatch pass.
        if not self._queue_counts_as_wait_activity(config):
            return None
        return super()._fetch_next_message(config)

    def _apply_delivery_result(self) -> None:
        try:
            result = self._delivery_results.get_nowait()
        except queue.Empty:
            return
        if result.serial != self._delivery_pending:
            return
        worker = self._delivery_thread
        if worker is not None:
            worker.join(timeout=5.0)
            if worker.is_alive():
                raise RuntimeError("injection worker did not retire after its result")
        cursor = self._delivery_cursor
        self._delivery_pending = None
        self._delivery_prepared = None
        self._delivery_cursor = None
        self._delivery_thread = None
        if result.generation != self.current_generation():
            self._mark_pending_messages_prechecked()
            return
        if result.error is not None:
            if self.delivery_error is not None:
                self.delivery_error(result.error)
            else:
                raise WatcherRejected("injection failed") from result.error
        elif cursor is not None:
            super()._advance(*cursor)
        self._mark_pending_messages_prechecked()

    def _process_reactor_turn(self) -> None:
        self._apply_delivery_result()
        if self.owner_turn is not None:
            self.owner_turn()
        if self._delivery_pending is None or self.control_queue_name is not None:
            super()._process_reactor_turn()

    def next_wait_timeout(self) -> float | None:
        if self.owner_wait_timeout is not None:
            return self.owner_wait_timeout()
        return super().next_wait_timeout()

    def _drain_queue(self) -> None:
        # Readiness is delivery, not mere worker submission. Delay the existing
        # first-drain barrier until every initial delivery has completed.
        ready = self._ready_event
        self._ready_event = None
        try:
            super()._drain_queue()
        finally:
            self._ready_event = ready
        if self._delivery_pending is not None or not self.delivery_enabled:
            self._ready_after_initial_drain = False
        elif ready is not None:
            ready.set()

    def _close_reactor_resources(self) -> None:
        try:
            prepared = self._delivery_prepared
            worker = self._delivery_thread
            if prepared is not None and worker is not None and worker.is_alive():
                # Closing the sole source ends the run. Use nonblocking adapter
                # retirement, then verify the write worker has stopped.
                prepared.handle.request_close()
            if worker is not None:
                worker.join(timeout=5.0)
                if worker.is_alive():
                    raise RuntimeError(
                        "injection worker did not stop before reactor close"
                    )
        finally:
            super()._close_reactor_resources()
