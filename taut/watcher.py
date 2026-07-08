"""Multi-queue watcher and taut cursor-aware live follower.

Vendored/adapted from:
- repo: ../weft
- path: weft/core/tasks/multiqueue_watcher.py
- commit: 7612e972a75806b8165dbf18e6bbfcbb686f27ea

Local deviations from the vendored source (reconcile on the next re-vendor):
- `MultiQueueWatcher.remove_queue` closes the removed config's `Queue`
  unless it is the shared data-version queue (`BaseWatcher._queue_obj`,
  built from the first configured queue), so membership churn under a
  running watcher does not leak broker connections.
- `TautWatcher.__init__` no longer raises `EmptyResultError` for an empty
  filtered membership set: `_current_memberships(strict=True)` already
  raises `MembershipError` for any filtered thread the member has not
  joined, so that branch was unreachable.

Spec references:
- docs/specs/02-taut-core.md [TAUT-8.4]
"""

from __future__ import annotations

import itertools
import logging
import threading
import time
import warnings
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypeVar, cast

from simplebroker import (
    BrokerTarget,
    Queue,
    create_activity_waiter_for_queues,
    resolve_broker_target,
)
from simplebroker.ext import (
    BaseWatcher,
    BrokerError,
    PollingStrategy,
    StopWatching,
    default_error_handler,
)

from taut import addressing
from taut._broker_retry import is_transient_broker_error
from taut._constants import (
    QUEUE_PRIORITY_NORMAL,
    WATCH_MEMBERSHIP_REFRESH_SECONDS,
    load_config,
)
from taut._exceptions import MembershipError
from taut._watch_runtime import TautWatchRuntime, WatchedThread
from taut.client import Message, Notification

if TYPE_CHECKING:
    from taut.client import TautClient

logger = logging.getLogger(__name__)

_T = TypeVar("_T")

_WATCHER_DB_RETRY_ATTEMPTS = 30
_WATCHER_DB_RETRY_DELAY_SECONDS = 0.05
_WATCHER_DB_RETRY_MAX_DELAY_SECONDS = 0.5


class QueueMode(StrEnum):
    """Supported queue processing behaviours."""

    READ = "read"
    RESERVE = "reserve"
    PEEK = "peek"


@dataclass(frozen=True, slots=True)
class QueueMessageContext:
    """Context passed to queue handlers describing the active message."""

    queue_name: str
    queue: Queue
    mode: QueueMode
    timestamp: int
    reserved_queue_name: str | None = None


@dataclass(slots=True)
class QueueRuntimeConfig:
    """Internal representation of a queue configuration."""

    name: str
    queue: Queue
    handler: Callable[[str, int, QueueMessageContext], None]
    mode: QueueMode
    error_handler: Callable[[Exception, str, int], bool | None]
    reserved_queue_name: str | None = None
    priority: int = QUEUE_PRIORITY_NORMAL


def _resolve_db_target(
    db: BrokerTarget | str | Path | None,
    fallback: BrokerTarget | None,
) -> BrokerTarget | str:
    if isinstance(db, BrokerTarget):
        return db
    if isinstance(db, (str, Path)):
        return str(db)
    if fallback is None:
        raise ValueError("no broker target available")
    return fallback


def _detach_queue_stop_event(queue: Queue) -> None:
    if hasattr(queue, "set_stop_event"):
        queue.set_stop_event(None)


def _is_transient_watcher_db_error(exc: Exception) -> bool:
    return is_transient_broker_error(exc)


class MultiQueueWatcher(BaseWatcher):
    """Monitor multiple queues with per-queue processing semantics."""

    def __init__(
        self,
        queue_configs: Mapping[str, Mapping[str, object]],
        *,
        db: BrokerTarget | str | Path | None = None,
        stop_event: threading.Event | None = None,
        persistent: bool = True,
        polling_strategy: PollingStrategy | None = None,
        yield_strategy: str = "round_robin",
        check_interval: int = 10,
        inactive_probe_interval: float = WATCH_MEMBERSHIP_REFRESH_SECONDS,
        default_error_handler_fn: Callable[
            [Exception, str, int], bool | None
        ] = default_error_handler,
        config: Mapping[str, Any] | None = None,
    ) -> None:
        if not queue_configs:
            raise ValueError("queue_configs cannot be empty")

        config_dict = dict(config) if config is not None else load_config()
        self._config: dict[str, Any] = config_dict
        self._persistent = persistent
        self._yield_strategy = yield_strategy
        self._check_interval = check_interval
        self._inactive_probe_interval = max(0.0, float(inactive_probe_interval))
        self._default_error_handler = default_error_handler_fn
        self._handler: Callable[[str, int], None] | None = None
        self._error_handler: Callable[[Exception, str, int], bool | None] | None = None

        first_queue_name = next(iter(queue_configs.keys()))
        shared_target = _resolve_db_target(
            db,
            resolve_broker_target(Path.cwd(), config=self._config),
        )
        initial_queue = Queue(
            first_queue_name,
            db_path=shared_target,
            persistent=persistent,
            config=self._config,
        )

        super().__init__(
            initial_queue,
            stop_event=stop_event,
            polling_strategy=polling_strategy,
            config=self._config,
        )
        _detach_queue_stop_event(initial_queue)
        self._db_path = initial_queue.db_target

        self._queues: dict[str, QueueRuntimeConfig] = {}
        for queue_name, raw_config in queue_configs.items():
            self._queues[queue_name] = self._runtime_config(
                queue_name,
                raw_config,
                initial_queue=initial_queue if queue_name == first_queue_name else None,
            )

        self._active_queues: list[str] = []
        self._queue_iterator: itertools.cycle[str] = itertools.cycle([])
        self._check_counter = 0
        self._queue_generation = 0
        self._multi_activity_waiter: Any | None = None
        self._multi_activity_waiter_generation: int | None = None
        self._multi_activity_waiter_signature: tuple[str, ...] | None = None
        self._pending_messages_precheck_confirmed = False
        self._next_inactive_probe_at = time.monotonic()
        self._ensure_multi_activity_waiter()

    def list_queues(self) -> list[str]:
        return list(self._queues.keys())

    def add_queue(
        self,
        queue_name: str,
        handler: Callable[[str, int, QueueMessageContext], None],
        *,
        mode: QueueMode = QueueMode.READ,
        reserved_queue: str | None = None,
        error_handler: Callable[[Exception, str, int], bool | None] | None = None,
        priority: int = QUEUE_PRIORITY_NORMAL,
    ) -> None:
        if queue_name in self._queues:
            return
        raw: dict[str, object] = {
            "handler": handler,
            "mode": mode,
            "priority": priority,
        }
        if reserved_queue is not None:
            raw["reserved_queue"] = reserved_queue
        if error_handler is not None:
            raw["error_handler"] = error_handler
        self._queues[queue_name] = self._runtime_config(queue_name, raw)
        self._queue_generation += 1
        self._reset_multi_activity_waiter()

    def remove_queue(self, queue_name: str) -> None:
        config = self._queues.pop(queue_name, None)
        if config is None:
            return
        if queue_name in self._active_queues:
            self._active_queues = [q for q in self._active_queues if q != queue_name]
            self._queue_iterator = (
                itertools.cycle(self._active_queues)
                if self._active_queues
                else itertools.cycle([])
            )
        self._queue_generation += 1
        self._reset_multi_activity_waiter()
        # The first configured queue doubles as BaseWatcher's data-version
        # queue (`_queue_obj`); closing it would kill data-version polling.
        if config.queue is not self._get_queue_for_data_version():
            try:
                config.queue.close()
            except (BrokerError, OSError, RuntimeError):
                logger.debug(
                    "failed to close removed queue '%s'", queue_name, exc_info=True
                )

    def get_queue(self, queue_name: str) -> Queue | None:
        config = self._queues.get(queue_name)
        return config.queue if config else None

    def _runtime_config(
        self,
        queue_name: str,
        raw_config: Mapping[str, object],
        *,
        initial_queue: Queue | None = None,
    ) -> QueueRuntimeConfig:
        handler_obj = raw_config.get("handler")
        if not callable(handler_obj):
            raise TypeError(f"handler for queue '{queue_name}' must be callable")
        handler = cast(Callable[[str, int, QueueMessageContext], None], handler_obj)
        mode_value = raw_config.get("mode", QueueMode.READ)
        mode = (
            mode_value
            if isinstance(mode_value, QueueMode)
            else QueueMode(str(mode_value))
        )
        queue_obj = initial_queue or Queue(
            queue_name,
            db_path=self._db_path,
            persistent=self._persistent,
            config=self._config,
        )
        _detach_queue_stop_event(queue_obj)
        error_handler_obj = raw_config.get("error_handler")
        error_handler = (
            cast(Callable[[Exception, str, int], bool | None], error_handler_obj)
            if callable(error_handler_obj)
            else self._default_error_handler
        )
        reserved_name_obj = raw_config.get("reserved_queue")
        reserved_name = (
            reserved_name_obj if isinstance(reserved_name_obj, str) else None
        )
        if mode is QueueMode.RESERVE and reserved_name is None:
            raise ValueError("reserve mode requires reserved_queue")
        priority_obj = raw_config.get("priority", QUEUE_PRIORITY_NORMAL)
        priority = (
            priority_obj if isinstance(priority_obj, int) else QUEUE_PRIORITY_NORMAL
        )
        return QueueRuntimeConfig(
            name=queue_name,
            queue=queue_obj,
            handler=handler,
            mode=mode,
            error_handler=error_handler,
            reserved_queue_name=reserved_name,
            priority=priority,
        )

    def _queue_counts_as_wait_activity(self, config: QueueRuntimeConfig) -> bool:
        del config
        return True

    def _activity_wait_configs(self) -> list[QueueRuntimeConfig]:
        return [
            config
            for config in self._queues.values()
            if self._queue_counts_as_wait_activity(config)
        ]

    def _reset_multi_activity_waiter(self) -> None:
        waiter = self._multi_activity_waiter
        self._multi_activity_waiter = None
        self._multi_activity_waiter_generation = None
        self._multi_activity_waiter_signature = None
        if waiter is None:
            return
        self._strategy.detach_activity_waiter(expected=waiter)
        try:
            cast(Any, waiter).close()
        except (BrokerError, OSError, RuntimeError):
            logger.debug("failed to close multi-queue activity waiter", exc_info=True)

    def _ensure_multi_activity_waiter(self) -> Any | None:
        wait_configs = self._activity_wait_configs()
        signature = tuple(config.name for config in wait_configs)
        if (
            self._multi_activity_waiter_generation == self._queue_generation
            and self._multi_activity_waiter_signature == signature
        ):
            return self._multi_activity_waiter
        self._reset_multi_activity_waiter()
        self._multi_activity_waiter_generation = self._queue_generation
        self._multi_activity_waiter_signature = signature
        if not wait_configs:
            return None
        try:
            self._multi_activity_waiter = create_activity_waiter_for_queues(
                [config.queue for config in wait_configs],
                stop_event=self._stop_event,
            )
        except (BrokerError, OSError, RuntimeError, TypeError, ValueError):
            logger.debug("multi-queue waiter unavailable", exc_info=True)
            self._multi_activity_waiter = None
        return self._multi_activity_waiter

    def _create_activity_waiter(self, queue: Queue) -> Any | None:
        del queue
        return self._ensure_multi_activity_waiter()

    def stop(self, *, join: bool = True, timeout: float = 2.0) -> None:
        self._reset_multi_activity_waiter()
        super().stop(join=join, timeout=timeout)

    def _has_pending_messages(self) -> bool:
        return any(
            self._queue_counts_as_wait_activity(config)
            and self._queue_has_pending(config.queue)
            for config in self._queues.values()
        )

    def _queue_has_pending(self, queue: Queue) -> bool:
        if self._stop_event.is_set():
            return False
        try:
            return self._retry_transient_db_op(queue.has_pending, what="has_pending")
        except BrokerError:
            if self._stop_event.is_set():
                return False
            raise

    def _retry_transient_db_op(
        self,
        fn: Callable[[], _T],
        *,
        what: str,
    ) -> _T:
        stop_event = getattr(self, "_stop_event", None)
        delay = _WATCHER_DB_RETRY_DELAY_SECONDS
        for attempt in range(1, _WATCHER_DB_RETRY_ATTEMPTS + 1):
            try:
                return fn()
            except Exception as exc:
                if stop_event is not None and stop_event.is_set():
                    raise StopWatching from exc
                if (
                    attempt >= _WATCHER_DB_RETRY_ATTEMPTS
                    or not _is_transient_watcher_db_error(exc)
                ):
                    raise
                logger.debug(
                    "transient watcher db error on %s; retrying: %s", what, exc
                )
                if stop_event is not None and stop_event.wait(timeout=delay):
                    raise StopWatching from exc
                if stop_event is None:
                    time.sleep(delay)
                delay = min(delay * 2, _WATCHER_DB_RETRY_MAX_DELAY_SECONDS)
        raise AssertionError("unreachable watcher retry loop exit")

    def _update_active_queues(self) -> None:
        if self._stop_event.is_set():
            self._active_queues = []
            self._queue_iterator = itertools.cycle([])
            return
        still_active = [
            name
            for name in self._active_queues
            if name in self._queues
            and self._queue_has_pending(self._queues[name].queue)
        ]
        now = time.monotonic()
        if (
            self._pending_messages_precheck_confirmed
            or now >= self._next_inactive_probe_at
        ):
            for name, config in self._queues.items():
                if (
                    name not in still_active
                    and self._queue_counts_as_wait_activity(config)
                    and self._queue_has_pending(config.queue)
                ):
                    still_active.append(name)
            self._pending_messages_precheck_confirmed = False
            self._next_inactive_probe_at = now + self._inactive_probe_interval
        if set(still_active) != set(self._active_queues):
            self._active_queues = still_active
            self._queue_iterator = (
                itertools.cycle(self._active_queues)
                if self._active_queues
                else itertools.cycle([])
            )
        self._check_counter += 1

    def _fetch_next_message(self, config: QueueRuntimeConfig) -> tuple[str, int] | None:
        if config.mode is QueueMode.READ:
            return cast(
                tuple[str, int] | None,
                self._retry_transient_db_op(
                    lambda: config.queue.read_one(with_timestamps=True),
                    what=f"read {config.name}",
                ),
            )
        if config.mode is QueueMode.PEEK:
            return cast(
                tuple[str, int] | None,
                self._retry_transient_db_op(
                    lambda: config.queue.peek_one(with_timestamps=True),
                    what=f"peek {config.name}",
                ),
            )
        if config.mode is QueueMode.RESERVE:
            reserved_queue_name = config.reserved_queue_name
            if not reserved_queue_name:
                raise RuntimeError(f"queue '{config.name}' missing reserved queue")
            return cast(
                tuple[str, int] | None,
                self._retry_transient_db_op(
                    lambda: config.queue.move_one(
                        reserved_queue_name,
                        with_timestamps=True,
                    ),
                    what=f"reserve {config.name}",
                ),
            )
        raise ValueError(f"unsupported queue mode: {config.mode}")

    @staticmethod
    def _make_handler_wrapper(
        handler: Callable[[str, int, QueueMessageContext], None],
        context: QueueMessageContext,
    ) -> Callable[[str, int], None]:
        def wrapper(message: str, timestamp: int) -> None:
            handler(message, timestamp, context)

        return wrapper

    def _process_queue_message(
        self, queue_name: str, inactive_candidates: set[str]
    ) -> bool:
        config = self._queues[queue_name]
        result = self._fetch_next_message(config)
        if not result:
            if config.mode is not QueueMode.PEEK:
                inactive_candidates.add(queue_name)
            return False
        body, timestamp = result
        context = QueueMessageContext(
            queue_name=queue_name,
            queue=config.queue,
            mode=config.mode,
            timestamp=timestamp,
            reserved_queue_name=config.reserved_queue_name,
        )
        original_handler = self._handler
        original_error_handler = self._error_handler
        self._handler = self._make_handler_wrapper(config.handler, context)
        self._error_handler = config.error_handler
        try:
            self._dispatch(body, timestamp, config=self._config)
        finally:
            self._handler = original_handler
            self._error_handler = original_error_handler
        if self._stop_event.is_set() or not self._queue_has_pending(config.queue):
            inactive_candidates.add(queue_name)
        return True

    def _drain_round_robin_pass(
        self,
        *,
        queue_names: Sequence[str] | None = None,
    ) -> int:
        messages_processed = 0
        inactive_candidates: set[str] = set()
        selected = list(queue_names) if queue_names is not None else []
        iterations = (
            len(selected) if queue_names is not None else len(self._active_queues)
        )
        for index in range(iterations):
            if self._stop_event.is_set():
                break
            if queue_names is None:
                try:
                    queue_name = next(self._queue_iterator)
                except StopIteration:
                    break
            else:
                queue_name = selected[index]
                if queue_name not in self._active_queues:
                    continue
            if queue_name in self._queues and self._process_queue_message(
                queue_name, inactive_candidates
            ):
                messages_processed += 1
        if inactive_candidates:
            self._active_queues = [
                q for q in self._active_queues if q not in inactive_candidates
            ]
            self._queue_iterator = (
                itertools.cycle(self._active_queues)
                if self._active_queues
                else itertools.cycle([])
            )
        return messages_processed

    def _drain_queue(self) -> None:
        self._update_active_queues()
        if not self._active_queues:
            return
        messages_processed = self._drain_round_robin_pass()
        if messages_processed > 0:
            self._strategy.notify_activity()


class TautWatcher(MultiQueueWatcher):
    """Cursor-aware taut live follower."""

    def __init__(
        self,
        runtime: TautWatchRuntime | TautClient,
        member_id: str,
        handler: Callable[[Message | Notification], None],
        *,
        threads: list[str] | None = None,
        stop_event: threading.Event | None = None,
        membership_refresh_interval: float = WATCH_MEMBERSHIP_REFRESH_SECONDS,
    ) -> None:
        from taut.client._base import _ClientBase

        if isinstance(runtime, _ClientBase):
            from taut.client._watching import _watch_runtime_for_client

            warnings.warn(
                "TautWatcher(client, ...) is deprecated; use client.watch(...) "
                "or pass a TautWatchRuntime",
                DeprecationWarning,
                stacklevel=2,
            )
            runtime = _watch_runtime_for_client(runtime)
        self._runtime = runtime
        self.member_id = member_id
        self._user_handler = handler
        self._cursors: dict[str, int] = {}
        self._failures: dict[tuple[str, int], int] = {}
        self._ready_event: threading.Event | None = None
        self._ready_after_initial_drain = False
        self._thread_filter = set(threads) if threads else None
        self._membership_refresh_interval = membership_refresh_interval
        self._next_membership_refresh_at = time.monotonic()
        self._notification_queue_name = addressing.notification_queue_name(member_id)
        memberships = self._current_memberships(strict=True)
        queue_configs = {
            self._notification_queue_name: {
                "handler": self._make_notification_handler(),
                "mode": QueueMode.READ,
            },
            **{
                row.name: {
                    "handler": self._make_taut_handler(row.name),
                    "mode": QueueMode.PEEK,
                }
                for row in memberships
            },
        }
        for row in memberships:
            self._cursors[row.name] = row.last_seen_ts
        super().__init__(
            queue_configs,
            db=self._runtime.target,
            stop_event=stop_event,
            # Keep SQLite watcher handles short-lived. Summon driver tests run
            # watcher, control, provider, and peer CLI subprocesses against one
            # fresh database; persistent watcher handles made rare WAL/page
            # corruption observable under that startup churn.
            persistent=False,
            inactive_probe_interval=membership_refresh_interval,
            config=self._runtime.config,
        )

    def list_queues(self) -> list[str]:
        return [
            name
            for name in super().list_queues()
            if name != self._notification_queue_name
        ]

    def _activity_wait_configs(self) -> list[QueueRuntimeConfig]:
        # Taut chat watchers use PRAGMA data_version polling instead of the
        # broker-native multi-queue activity waiter. The native waiter can miss
        # a write that lands in the startup gap after the initial drain but
        # before the first wait call is armed; data_version polling gives the
        # summon readiness barrier a stable consumer boundary.
        return []

    def notify_ready_after_initial_drain(self, event: threading.Event) -> None:
        """Signal ``event`` once the watcher has started and completed one drain."""

        self._ready_event = event
        if self._ready_after_initial_drain:
            event.set()

    def _current_memberships(self, *, strict: bool) -> list[WatchedThread]:
        rows = self._retry_transient_db_op(
            lambda: self._runtime.list_watched_threads(self.member_id),
            what="membership refresh",
        )
        if self._thread_filter is None:
            return rows
        filtered = [row for row in rows if row.name in self._thread_filter]
        missing = self._thread_filter - {row.name for row in filtered}
        if strict and missing:
            raise MembershipError(
                "not a member of watched thread(s): " + ", ".join(sorted(missing))
            )
        return filtered

    def _make_notification_handler(
        self,
    ) -> Callable[[str, int, QueueMessageContext], None]:
        def handle(body: str, timestamp: int, _context: QueueMessageContext) -> None:
            self._user_handler(self._runtime.decode_notification(body, timestamp))

        return handle

    def _make_taut_handler(
        self,
        thread: str,
    ) -> Callable[[str, int, QueueMessageContext], None]:
        def handle(body: str, timestamp: int, _context: QueueMessageContext) -> None:
            message = self._runtime.decode_message(thread, body, timestamp)
            failure_key = (thread, timestamp)
            try:
                self._user_handler(message)
            except Exception:
                count = self._failures.get(failure_key, 0) + 1
                self._failures[failure_key] = count
                if count >= 3:
                    logger.warning(
                        "advancing past poison message %s in %s after 3 failures",
                        timestamp,
                        thread,
                    )
                    self._advance(thread, timestamp)
                    self._failures.pop(failure_key, None)
                    return
                raise
            self._failures.pop(failure_key, None)
            self._advance(thread, timestamp)

        return handle

    def _advance(self, thread: str, timestamp: int) -> None:
        current = self._cursors.get(thread, 0)
        self._retry_transient_db_op(
            lambda: self._runtime.advance_cursor(
                thread=thread,
                member_id=self.member_id,
                seen_ts=timestamp,
            ),
            what=f"advance cursor {thread}",
        )
        if timestamp > current:
            self._cursors[thread] = timestamp

    def _fetch_next_message(self, config: QueueRuntimeConfig) -> tuple[str, int] | None:
        if (
            config.name == self._notification_queue_name
            or config.mode is not QueueMode.PEEK
        ):
            return super()._fetch_next_message(config)
        cursor = self._cursors.get(config.name, 0)
        rows = cast(
            list[tuple[str, int]],
            self._retry_transient_db_op(
                lambda: config.queue.peek_many(
                    1,
                    with_timestamps=True,
                    after_timestamp=cursor,
                ),
                what=f"peek {config.name}",
            ),
        )
        return rows[0] if rows else None

    def _queue_has_pending(self, queue: Queue) -> bool:
        if self._stop_event.is_set():
            return False
        if queue.name == self._notification_queue_name:
            return super()._queue_has_pending(queue)
        cursor = self._cursors.get(queue.name, 0)
        try:
            return self._retry_transient_db_op(
                lambda: queue.has_pending(after_timestamp=cursor),
                what=f"has_pending {queue.name}",
            )
        except BrokerError:
            if self._stop_event.is_set():
                return False
            raise

    def _has_pending_messages(self) -> bool:
        if (
            not self._stop_event.is_set()
            and time.monotonic() >= self._next_membership_refresh_at
        ):
            return True
        return super()._has_pending_messages()

    def _on_data_version_change(self, queue: Queue) -> None:
        try:
            super()._on_data_version_change(queue)
        except Exception as exc:
            if not _is_transient_watcher_db_error(exc):
                raise
            logger.debug(
                "transient data-version callback failure; falling back to poll",
                exc_info=True,
            )
            self._pending_messages_precheck_confirmed = True
            self._next_inactive_probe_at = 0.0
            self._strategy.notify_activity()
            return
        try:
            self._refresh_memberships()
        except Exception as exc:
            if not _is_transient_watcher_db_error(exc):
                raise
            logger.debug(
                "transient membership refresh failure; retrying on next drain",
                exc_info=True,
            )
            self._next_membership_refresh_at = time.monotonic()

    def _drain_queue(self) -> None:
        now = time.monotonic()
        if now >= self._next_membership_refresh_at:
            self._refresh_memberships()
            self._next_membership_refresh_at = now + self._membership_refresh_interval
        super()._drain_queue()
        if not self._ready_after_initial_drain:
            self._ready_after_initial_drain = True
            if self._ready_event is not None:
                self._ready_event.set()

    def _refresh_memberships(self) -> None:
        rows = self._current_memberships(strict=False)
        current = {row.name for row in rows}
        configured = set(self._queues) - {self._notification_queue_name}
        for row in rows:
            thread = row.name
            if thread not in self._cursors:
                self._cursors[thread] = row.last_seen_ts
            if thread not in configured:
                self.add_queue(
                    thread,
                    self._make_taut_handler(thread),
                    mode=QueueMode.PEEK,
                )
        for thread in sorted(configured - current):
            self.remove_queue(thread)
            self._cursors.pop(thread, None)
            self._clear_failures_for_thread(thread)

    def _clear_failures_for_thread(self, thread: str) -> None:
        stale_keys = [key for key in self._failures if key[0] == thread]
        for key in stale_keys:
            self._failures.pop(key, None)
