"""Multi-queue watcher and taut cursor-aware live follower.

`MultiQueueWatcher` is copied from Weft's
`weft/core/tasks/multiqueue_watcher.py`; Taut-specific behavior belongs in
subclasses such as `TautWatcher`.

Spec references:
- docs/specs/02-taut-core.md [TAUT-8.4]
"""

from __future__ import annotations

import itertools
import logging
import threading
import time
import warnings
import weakref
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast, final

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

TASK_INACTIVE_QUEUE_DISCOVERY_INTERVAL_SECONDS = WATCH_MEMBERSHIP_REFRESH_SECONDS

REACTOR_LIFECYCLE_METHODS = (
    "process_once",
    "wait_for_activity",
    "run_until_stopped",
    "run_forever",
    "run_in_thread",
    "start",
    "run",
    "request_stop",
    "stop",
    "cleanup",
)


def resolve_context_broker_target(
    starting_dir: str | Path | None = None,
    *,
    config: dict[str, Any] | None = None,
) -> BrokerTarget:
    target = resolve_broker_target(starting_dir, config=config)
    if target is None:
        root = Path.cwd() if starting_dir is None else Path(starting_dir)
        return BrokerTarget("sqlite", str(root / ".taut.db"))
    return target


class QueueMode(StrEnum):
    """Supported queue processing behaviours (Spec: [CC-2.1])."""

    READ = "read"
    RESERVE = "reserve"
    PEEK = "peek"


@dataclass
class QueueMessageContext:
    """Context passed to queue handlers describing the active message (Spec: [CC-2.1])."""

    queue_name: str
    queue: Queue
    mode: QueueMode
    timestamp: int
    reserved_queue_name: str | None = None


@dataclass
class QueueRuntimeConfig:
    """Internal representation of a queue configuration (Spec: [CC-2.1])."""

    name: str
    queue: Queue
    handler: Callable[[str, int, QueueMessageContext], None]
    mode: QueueMode
    error_handler: Callable[[Exception, str, int], bool | None]
    reserved_queue_name: str | None = None
    priority: int = QUEUE_PRIORITY_NORMAL


def _resolve_db_target(
    db: BrokerTarget | str | Path | None,
    fallback: BrokerTarget,
) -> BrokerTarget | str:
    """Derive a broker target shared across Queue instances."""
    if isinstance(db, BrokerTarget):
        return db
    if isinstance(db, (str, Path)):
        return str(db)
    return fallback


def _detach_queue_stop_event(queue: Queue) -> None:
    """Keep queue connections usable after the watcher stop event is set."""
    if hasattr(queue, "set_stop_event"):
        queue.set_stop_event(None)


class MultiQueueWatcher(BaseWatcher):
    """Monitor multiple queues with per-queue processing semantics (Spec: [CC-2.1], [SB-0.4])."""

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
        inactive_probe_interval: float = TASK_INACTIVE_QUEUE_DISCOVERY_INTERVAL_SECONDS,
        default_error_handler_fn: Callable[
            [Exception, str, int], bool | None
        ] = default_error_handler,
        config: Mapping[str, Any] | None = None,
    ) -> None:
        """Initialize the watcher with queue-specific configurations.

        Args:
            queue_configs: Mapping of queue name to configuration dict with keys:
                - handler (callable): required, signature (message, timestamp, context)
                - mode (QueueMode or str): optional, defaults to QueueMode.READ
                - error_handler (callable): optional override per queue
            db: Explicit broker target or filesystem path for the watched queues
            stop_event: Event used to signal watcher shutdown
            persistent: Whether queues should be persistent
            polling_strategy: Optional SimpleBroker polling strategy override
            yield_strategy: Queue iteration strategy (currently round_robin)
            check_interval: Legacy turn-count discovery setting retained for
                existing callers; inactive discovery is now time-bounded.
            inactive_probe_interval: Minimum seconds between broad inactive
                queue discovery probes when no native activity hint is pending.
            default_error_handler_fn: Fallback error handler when queue config
                does not supply one (defaults to SimpleBroker's default)
            config: Optional SimpleBroker configuration dictionary. If omitted,
                :func:`weft._constants.load_config` is used.

        Spec: [CC-2.1], [SB-0.4]
        """
        if not queue_configs:
            raise ValueError("queue_configs cannot be empty")

        config_dict: dict[str, Any] = (
            dict(config) if config is not None else load_config()
        )
        self._config: dict[str, Any] = config_dict

        self._persistent = persistent
        self._yield_strategy = yield_strategy
        self._check_interval = check_interval
        self._inactive_probe_interval = max(0.0, float(inactive_probe_interval))
        self._default_error_handler = default_error_handler_fn
        self._handler: Callable[[str, int], None] | None = None
        self._error_handler: Callable[[Exception, str, int], bool | None] | None = None

        # Establish primary queue and shared broker target
        first_queue_name = next(iter(queue_configs.keys()))
        shared_target = _resolve_db_target(
            db,
            resolve_context_broker_target(Path.cwd(), config=self._config),
        )
        # Direct Queue ok here: MultiQueueWatcher is creating its owned primary
        # handle; see runtime-and-context-patterns.md section 2.
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

        # Build runtime configs for each queue
        self._queues: dict[str, QueueRuntimeConfig] = {}
        for queue_name, raw_config in queue_configs.items():
            handler_obj = raw_config.get("handler")
            if not callable(handler_obj):
                raise TypeError(
                    f"handler for queue '{queue_name}' must be callable, "
                    f"got {type(handler_obj).__name__}"
                )
            handler = cast(Callable[[str, int, QueueMessageContext], None], handler_obj)

            mode_value = raw_config.get("mode", QueueMode.READ)
            mode = (
                mode_value
                if isinstance(mode_value, QueueMode)
                else QueueMode(str(mode_value))
            )

            if queue_name == first_queue_name:
                queue_obj = initial_queue
            else:
                # Direct Queue ok here: MultiQueueWatcher owns watched queue
                # handles by design; see runtime-and-context-patterns.md section 2.
                queue_obj = Queue(
                    queue_name,
                    db_path=self._db_path,
                    persistent=persistent,
                    config=self._config,
                )

            _detach_queue_stop_event(queue_obj)

            error_handler_obj = raw_config.get("error_handler")
            if error_handler_obj is not None and not callable(error_handler_obj):
                raise TypeError(
                    f"error_handler for queue '{queue_name}' must be callable, "
                    f"got {type(error_handler_obj).__name__}"
                )
            error_handler = (
                cast(Callable[[Exception, str, int], bool | None], error_handler_obj)
                if error_handler_obj is not None
                else None
            )

            reserved_name_obj = raw_config.get("reserved_queue")
            reserved_name: str | None
            if reserved_name_obj is None:
                reserved_name = None
            elif isinstance(reserved_name_obj, str):
                reserved_name = reserved_name_obj
            else:
                raise TypeError(
                    f"reserved_queue for '{queue_name}' must be a string, "
                    f"got {type(reserved_name_obj).__name__}"
                )

            if mode is QueueMode.RESERVE and not reserved_name:
                raise ValueError(
                    f"Queue '{queue_name}' configured in reserve mode must supply 'reserved_queue'"
                )

            priority_obj = raw_config.get("priority", QUEUE_PRIORITY_NORMAL)
            if not isinstance(priority_obj, int):
                raise TypeError(
                    f"priority for '{queue_name}' must be an int, "
                    f"got {type(priority_obj).__name__}"
                )

            runtime_config = QueueRuntimeConfig(
                name=queue_name,
                queue=queue_obj,
                handler=handler,
                mode=mode,
                error_handler=error_handler or default_error_handler_fn,
                reserved_queue_name=reserved_name,
                priority=priority_obj,
            )
            self._queues[queue_name] = runtime_config

        # Processing state
        self._active_queues: list[str] = []
        self._queue_iterator: itertools.cycle[str] = itertools.cycle([])
        self._check_counter = 0
        self._queue_generation = 0
        self._multi_activity_waiter: Any | None = None
        self._multi_activity_waiter_generation: int | None = None
        self._multi_activity_waiter_signature: tuple[str, ...] | None = None
        self._pending_messages_precheck_confirmed = False
        self._next_inactive_probe_at = time.monotonic()

        logger.debug(
            "MultiQueueWatcher initialized with queues: %s",
            list(self._queues.keys()),
        )

    # ------------------------------------------------------------------ #
    # Public API                                                         #
    # ------------------------------------------------------------------ #

    def list_queues(self) -> list[str]:
        """Return all configured queue names.

        Spec: [CC-2.1]
        """
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
        """Dynamically add a queue to the watcher.

        Spec: [CC-2.1], [SB-0.4]
        """
        if queue_name in self._queues:
            raise ValueError(f"Queue '{queue_name}' already exists")
        if not callable(handler):
            raise TypeError(f"handler must be callable, got {type(handler).__name__}")
        if error_handler is not None and not callable(error_handler):
            raise TypeError(
                f"error_handler must be callable, got {type(error_handler).__name__}"
            )
        if mode is QueueMode.RESERVE and reserved_queue is None:
            raise ValueError("reserve mode requires reserved_queue")
        if not isinstance(priority, int):
            raise TypeError(f"priority must be an int, got {type(priority).__name__}")

        # Direct Queue ok here: MultiQueueWatcher owns dynamically watched queue
        # handles by design; see runtime-and-context-patterns.md section 2.
        queue_obj = Queue(
            queue_name,
            db_path=self._db_path,
            persistent=self._persistent,
            config=self._config,
        )

        _detach_queue_stop_event(queue_obj)

        self._queues[queue_name] = QueueRuntimeConfig(
            name=queue_name,
            queue=queue_obj,
            handler=handler,
            mode=mode,
            error_handler=error_handler or self._default_error_handler,
            reserved_queue_name=reserved_queue,
            priority=priority,
        )
        self._queue_generation += 1

    def remove_queue(self, queue_name: str) -> None:
        """Remove a queue from the watcher.

        Spec: [CC-2.1]
        """
        if queue_name not in self._queues:
            raise ValueError(f"Queue '{queue_name}' not found")
        del self._queues[queue_name]
        if queue_name in self._active_queues:
            self._active_queues = [q for q in self._active_queues if q != queue_name]
            self._queue_iterator = (
                itertools.cycle(self._active_queues)
                if self._active_queues
                else itertools.cycle([])
            )
        self._queue_generation += 1

    def get_queue(self, queue_name: str) -> Queue | None:
        """Return the managed Queue instance for *queue_name* if present.

        Spec: [SB-0.1]
        """
        config = self._queues.get(queue_name)
        return config.queue if config else None

    # ------------------------------------------------------------------ #
    # Internal helpers                                                   #
    # ------------------------------------------------------------------ #
    def _queue_counts_as_wait_activity(self, config: QueueRuntimeConfig) -> bool:
        """Return whether *config* should wake ``wait_for_activity``."""

        del config
        return True

    def _activity_wait_configs(self) -> list[QueueRuntimeConfig]:
        """Return queue configs that should wake ``wait_for_activity``."""

        return [
            config
            for config in self._queues.values()
            if self._queue_counts_as_wait_activity(config)
        ]

    def _activity_wait_queues(self) -> list[Queue]:
        """Return queues watched by the multi-queue activity waiter."""

        return [config.queue for config in self._activity_wait_configs()]

    def _mark_pending_messages_prechecked(self) -> None:
        """Force the next drain to run broad inactive-queue discovery."""

        self._pending_messages_precheck_confirmed = True

    def _mark_queue_active(self, queue_name: str) -> None:
        """Mark one configured queue as active based on explicit caller evidence."""

        if queue_name not in self._queues:
            raise ValueError(f"Queue '{queue_name}' is not configured")
        if queue_name in self._active_queues:
            return
        self._active_queues.append(queue_name)
        self._queue_iterator = itertools.cycle(self._active_queues)

    def _ensure_multi_activity_waiter(self) -> Any | None:
        """Create or return the SimpleBroker multi-queue activity waiter."""
        signature = tuple(config.name for config in self._activity_wait_configs())
        if (
            self._multi_activity_waiter_generation == self._queue_generation
            and self._multi_activity_waiter_signature == signature
        ):
            return self._multi_activity_waiter

        waiter, signature = self._build_multi_activity_waiter()
        self._multi_activity_waiter = waiter
        self._multi_activity_waiter_generation = self._queue_generation
        self._multi_activity_waiter_signature = signature
        return waiter

    def _build_multi_activity_waiter(self) -> tuple[Any | None, tuple[str, ...]]:
        """Build one candidate waiter without publishing cache ownership."""

        wait_configs = self._activity_wait_configs()
        signature = tuple(config.name for config in wait_configs)
        if not wait_configs:
            return None, signature

        try:
            waiter = create_activity_waiter_for_queues(
                [config.queue for config in wait_configs],
                stop_event=self._stop_event,
            )
        except (BrokerError, OSError, RuntimeError, TypeError, ValueError):
            logger.debug(
                "Multi-queue activity waiter unavailable; falling back to polling",
                exc_info=True,
            )
            waiter = None
        return waiter, signature

    def _create_activity_waiter(self, queue: Queue) -> Any | None:
        """Supply Weft's multi-queue waiter to SimpleBroker strategy startup."""
        del queue
        return self._ensure_multi_activity_waiter()

    def _has_pending_messages(self) -> bool:
        """Return ``True`` when any configured queue still has pending messages.

        Spec: [CC-2.1]
        """
        return any(
            self._queue_counts_as_wait_activity(config)
            and self._queue_has_pending(config.queue)
            for config in self._queues.values()
        )

    def _queue_has_pending(self, queue: Queue) -> bool:
        """Return pending state without querying stopped queue connections."""
        if self._stop_event.is_set():
            return False
        try:
            return queue.has_pending()
        except BrokerError:
            if self._stop_event.is_set():
                return False
            raise

    def _update_active_queues(self) -> None:
        """Refresh the round-robin iterator with queues that still have work pending.

        Spec: [CC-2.1]
        """
        if self._stop_event.is_set():
            self._active_queues = []
            self._queue_iterator = itertools.cycle([])
            return

        still_active: list[str] = [
            name
            for name in self._active_queues
            if self._queue_has_pending(self._queues[name].queue)
        ]

        now = time.monotonic()
        precheck_confirmed = self._pending_messages_precheck_confirmed
        discovery_due = now >= self._next_inactive_probe_at
        should_probe_all = precheck_confirmed or discovery_due
        if should_probe_all:
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
        """Fetch the next message for a queue based on its configured processing mode.

        Spec: [CC-2.1], [SB-0.3]
        """
        if config.mode is QueueMode.READ:
            return cast(
                tuple[str, int] | None,
                config.queue.read_one(with_timestamps=True),
            )
        if config.mode is QueueMode.PEEK:
            return cast(
                tuple[str, int] | None,
                config.queue.peek_one(with_timestamps=True),
            )
        if config.mode is QueueMode.RESERVE:
            if not config.reserved_queue_name:
                raise RuntimeError(
                    f"Queue '{config.name}' configured for reserve mode missing reserved queue"
                )
            return cast(
                tuple[str, int] | None,
                config.queue.move_one(
                    config.reserved_queue_name,
                    with_timestamps=True,
                ),
            )
        raise ValueError(f"Unsupported queue mode: {config.mode}")

    @staticmethod
    def _make_handler_wrapper(
        handler: Callable[[str, int, QueueMessageContext], None],
        context: QueueMessageContext,
    ) -> Callable[[str, int], None]:
        """Wrap a queue handler so the watcher can invoke it with the expected signature.

        Spec: [CC-2.1]
        """

        def wrapper(message: str, timestamp: int) -> None:
            handler(message, timestamp, context)

        return wrapper

    def _active_queue_priorities(self) -> set[int]:
        """Return priorities for active queues.

        Spec: [CC-2.1], [CC-2.5]
        """
        return {self._queues[name].priority for name in self._active_queues}

    def _process_queue_message(
        self,
        queue_name: str,
        inactive_candidates: set[str],
    ) -> bool:
        """Process one message for one active queue.

        Spec: [CC-2.1], [CC-2.5]
        """
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

        handler_wrapper = self._make_handler_wrapper(config.handler, context)
        original_handler = self._handler
        original_error_handler = self._error_handler

        self._handler = handler_wrapper
        self._error_handler = config.error_handler

        try:
            self._dispatch(body, timestamp, config=self._config)
        finally:
            self._handler = original_handler
            self._error_handler = original_error_handler

        if self._stop_event.is_set():
            inactive_candidates.add(queue_name)
        elif not self._queue_has_pending(config.queue):
            inactive_candidates.add(queue_name)

        return True

    def _remove_inactive_queues(self, inactive_candidates: set[str]) -> None:
        """Remove inactive queue names from the active scheduling set."""
        if not inactive_candidates:
            return

        self._active_queues = [
            q for q in self._active_queues if q not in inactive_candidates
        ]
        self._queue_iterator = (
            itertools.cycle(self._active_queues)
            if self._active_queues
            else itertools.cycle([])
        )

    def _drain_round_robin_pass(
        self,
        *,
        queue_names: Sequence[str] | None = None,
    ) -> int:
        """Process one round-robin scheduling pass.

        Spec: [CC-2.1], [CC-2.5]
        """
        messages_processed = 0
        inactive_candidates: set[str] = set()

        if queue_names is None:
            iterations = len(self._active_queues)
            selected_queue_names: list[str] = []
        else:
            iterations = len(queue_names)
            selected_queue_names = list(queue_names)

        for index in range(iterations):
            if self._stop_event.is_set():
                break

            if queue_names is None:
                try:
                    queue_name = next(self._queue_iterator)
                except StopIteration:
                    break
            else:
                queue_name = selected_queue_names[index]
                if queue_name not in self._active_queues:
                    continue

            if self._process_queue_message(queue_name, inactive_candidates):
                messages_processed += 1

            if self._stop_event.is_set():
                break

        self._remove_inactive_queues(inactive_candidates)
        return messages_processed

    def _pending_non_peek_priorities(self) -> set[int]:
        """Return priorities for pending queues that can be drained repeatedly."""
        priorities: set[int] = set()
        for queue_name in self._active_queues:
            config = self._queues[queue_name]
            if config.mode is QueueMode.PEEK:
                continue
            if self._queue_has_pending(config.queue):
                priorities.add(config.priority)
        return priorities

    def _drain_priority_queues(self) -> int:
        """Drain the highest-priority non-PEEK queues before one normal pass.

        Spec: [CC-2.1], [CC-2.5]
        """
        messages_processed = 0
        priorities = self._pending_non_peek_priorities()
        if priorities:
            priority = min(priorities)
            while not self._stop_event.is_set():
                queue_names = [
                    name
                    for name in self._active_queues
                    if self._queues[name].priority == priority
                    and self._queues[name].mode is not QueueMode.PEEK
                ]
                if not queue_names:
                    break

                processed = self._drain_round_robin_pass(queue_names=queue_names)
                messages_processed += processed
                if processed == 0:
                    break

                self._update_active_queues()
                if priority not in self._pending_non_peek_priorities():
                    break

        if self._stop_event.is_set():
            return messages_processed

        self._update_active_queues()
        lower_priority_queue_names = [
            name
            for name in self._active_queues
            if self._queues[name].mode is not QueueMode.PEEK
        ]
        if lower_priority_queue_names:
            messages_processed += self._drain_round_robin_pass(
                queue_names=lower_priority_queue_names
            )

        if self._active_queues and not self._stop_event.is_set():
            peek_queue_names = [
                name
                for name in self._active_queues
                if self._queues[name].mode is QueueMode.PEEK
            ]
            if peek_queue_names:
                messages_processed += self._drain_round_robin_pass(
                    queue_names=peek_queue_names
                )

        return messages_processed

    def _drain_queue(self) -> None:
        """Process one scheduling pass across all active queues.

        Spec: [CC-2.1], [CC-2.5]
        """
        self._update_active_queues()
        if not self._active_queues:
            return

        if len(self._active_queue_priorities()) <= 1:
            messages_processed = self._drain_round_robin_pass()
        else:
            messages_processed = self._drain_priority_queues()

        if messages_processed > 0:
            self._strategy.notify_activity()


class BaseReactor(MultiQueueWatcher):
    """Shared reactor lifecycle seam for long-lived Taut queue owners."""

    _dynamic_topology = False

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._reject_legacy_lifecycle_overrides()
        self._drive_owner_lock = threading.Lock()
        self._topology_lock = threading.RLock()
        self._drive_thread: threading.Thread | None = None
        self._drive_thread_starting = False
        self._turn_active = False
        self._drive_loop_active = False
        self._reactor_activity_event = threading.Event()
        self._stop_once_lock = threading.Lock()
        self._stop_requested = False
        self._resources_closed = False
        self._strategy_started = False
        self._strategy_generation: int | None = None
        self._waiter_replacement_critical = False
        self._waiter_replacement_sigint_pending = False
        self._queue_cache: dict[str, Queue] = {}
        super().__init__(*args, **kwargs)
        for runtime_config in self._queues.values():
            self._queue_cache[runtime_config.name] = runtime_config.queue

    def _reject_legacy_lifecycle_overrides(self) -> None:
        """Reject unsafe old subclasses at construction, not import time."""

        concrete = type(self)
        overridden = [
            method_name
            for method_name in REACTOR_LIFECYCLE_METHODS
            if getattr(concrete, method_name) is not getattr(BaseReactor, method_name)
        ]
        if overridden:
            methods = ", ".join(overridden)
            raise RuntimeError(
                "reactor subclass overrides guarded lifecycle methods "
                f"({methods}); upgrade taut-summon to a BaseReactor-compatible "
                "release"
            )

    def _queue(self, name: str) -> Queue:
        """Return a persistent queue owned by this reactor."""

        cached = self._queue_cache.get(name)
        if cached is not None:
            return cached

        managed = self.get_queue(name)
        if managed is not None:
            self._queue_cache[name] = managed
            return managed

        queue_obj = Queue(
            name,
            db_path=self._db_path,
            persistent=self._persistent,
            config=self._config,
        )
        _detach_queue_stop_event(queue_obj)
        self._queue_cache[name] = queue_obj
        return queue_obj

    def get_queue(self, queue_name: str) -> Queue | None:
        """Return a live Queue only before drive or on the drive owner."""

        current = threading.current_thread()
        with self._drive_owner_lock:
            owner = self._drive_thread
        if owner is not None and owner is not current:
            raise RuntimeError("live reactor queues are drive-owner-only")
        with self._topology_lock:
            return super().get_queue(queue_name)

    def list_queues(self) -> list[str]:
        """Return a detached queue-name snapshot safe for foreign readers."""

        with self._topology_lock:
            return super().list_queues()

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
        self._check_topology_mutation()
        with self._topology_lock:
            super().add_queue(
                queue_name,
                handler,
                mode=mode,
                reserved_queue=reserved_queue,
                error_handler=error_handler,
                priority=priority,
            )
            managed = self.get_queue(queue_name)
            if managed is not None:
                self._queue_cache[queue_name] = managed

    def remove_queue(self, queue_name: str) -> None:
        self._check_topology_mutation()
        with self._topology_lock:
            super().remove_queue(queue_name)
            self._queue_cache.pop(queue_name, None)

    def _check_topology_mutation(self) -> None:
        if not self._dynamic_topology:
            raise NotImplementedError("reactor queues are fixed at construction")
        current = threading.current_thread()
        with self._drive_owner_lock:
            owner = self._drive_thread
        if owner is not None and owner is not current:
            raise RuntimeError("reactor topology mutation is drive-owner-only")

    def _claim_reactor_thread(self) -> None:
        """Claim or verify the one thread allowed to drive this reactor."""

        current = threading.current_thread()
        with self._drive_owner_lock:
            if self._drive_thread is None:
                self._drive_thread = current
                self._drive_thread_starting = False
                return
            if self._drive_thread is current:
                self._drive_thread_starting = False
                return
            if self._drive_thread is not current:
                raise RuntimeError(
                    "reactor turns are single-owner; a second thread cannot drive "
                    "this reactor"
                )

    @final
    def process_once(self) -> None:
        """Run one non-reentrant reactor turn on the drive owner."""

        self._claim_reactor_thread()
        with self._drive_owner_lock:
            if self._turn_active:
                raise RuntimeError("reactor turns are non-reentrant")
            self._turn_active = True
        try:
            self._process_reactor_turn()
        finally:
            should_finalize = False
            with self._drive_owner_lock:
                self._turn_active = False
                should_finalize = self._stop_requested and not self._drive_loop_active
            if should_finalize:
                self.stop(join=False)

    def _process_reactor_turn(self) -> None:
        """Execute policy work for one reactor turn."""

        if self._stop_event.is_set():
            return
        self._drain_queue()

    def next_wait_timeout(self) -> float | None:
        """Return the next wait timeout for the BaseTask-shaped loop."""

        return self._inactive_probe_interval

    def _ensure_polling_strategy_started(self) -> None:
        if not self._strategy_started:
            try:
                self._start_strategy()
            except BaseException:
                self._discard_failed_strategy_start_waiter()
                raise
            self._strategy_started = True
            self._strategy_generation = self._queue_generation
            return
        if self._strategy_generation == self._queue_generation:
            return
        self._replace_polling_strategy_waiter()

    @staticmethod
    def _close_activity_waiter(waiter: Any | None) -> None:
        """Close a caller-owned waiter once, without retrying close failures."""

        if waiter is None:
            return
        try:
            waiter.close()
        except Exception:  # pragma: no cover - defensive third-party cleanup
            logger.debug("failed to close displaced activity waiter", exc_info=True)

    def _discard_failed_strategy_start_waiter(self) -> None:
        """Close a startup candidate whether or not strategy accepted it."""

        cached = self._multi_activity_waiter
        self._multi_activity_waiter = None
        self._multi_activity_waiter_generation = None
        self._multi_activity_waiter_signature = None
        if cached is None:
            return
        detached = self._strategy.detach_activity_waiter(expected=cached)
        self._close_activity_waiter(detached if detached is not None else cached)

    def _replace_polling_strategy_waiter(self) -> None:
        """Commit the current topology generation through the strategy API."""

        prior_waiter = self._multi_activity_waiter
        candidate: Any | None = None
        candidate_caller_owned = False
        try:
            candidate, signature = self._build_multi_activity_waiter()
            candidate_caller_owned = candidate is not prior_waiter
            self._waiter_replacement_critical = True
            try:
                displaced = self._strategy.replace_activity_waiter(candidate)
            except BaseException:
                if candidate_caller_owned:
                    candidate_caller_owned = False
                    self._close_activity_waiter(candidate)
                raise

            candidate_caller_owned = False
            self._multi_activity_waiter = candidate
            self._multi_activity_waiter_generation = self._queue_generation
            self._multi_activity_waiter_signature = signature
            self._strategy_generation = self._queue_generation
            if displaced is not candidate:
                self._close_activity_waiter(displaced)
        finally:
            if candidate_caller_owned:
                candidate_caller_owned = False
                self._close_activity_waiter(candidate)
            self._waiter_replacement_critical = False
            pending_sigint = self._waiter_replacement_sigint_pending
            self._waiter_replacement_sigint_pending = False
            if pending_sigint:
                raise KeyboardInterrupt

    def _sigint_handler(self, signum: int, frame: Any) -> None:
        """Defer SIGINT only while native waiter ownership is transferring."""

        if self._waiter_replacement_critical:
            already_pending = self._waiter_replacement_sigint_pending
            self._waiter_replacement_sigint_pending = True
            self._stop_requested = True
            self._stop_event.set()
            self._reactor_activity_event.set()
            if not already_pending:
                self._strategy.notify_activity()
            return
        super()._sigint_handler(signum, frame)

    @final
    def wait_for_activity(self, timeout: float | None = None) -> None:
        self._claim_reactor_thread()
        if timeout is None or timeout <= 0 or self._stop_event.is_set():
            return
        if self._has_pending_messages():
            self._mark_pending_messages_prechecked()
            return

        self._ensure_polling_strategy_started()
        deadline = time.monotonic() + timeout
        while not self._stop_event.is_set():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            if self._reactor_activity_event.wait(timeout=min(remaining, 0.01)):
                self._reactor_activity_event.clear()
                return
            self._strategy.wait_for_activity()
            if not self._stop_event.is_set():
                self._ensure_polling_strategy_started()
            if self._has_pending_messages():
                self._mark_pending_messages_prechecked()
                return

    @final
    def run_until_stopped(self, *, max_iterations: int | None = None) -> None:
        """Run the explicit process/wait reactor loop used by Weft BaseTask."""

        self._claim_reactor_thread()
        with self._drive_owner_lock:
            self._drive_loop_active = True
        iterations = 0
        try:
            if self._stop_event.is_set():
                return
            self._ensure_polling_strategy_started()
            while not self._stop_event.is_set():
                self.process_once()
                iterations += 1
                if max_iterations is not None and iterations >= max_iterations:
                    break
                if self._stop_event.is_set():
                    break

                wait_timeout = self.next_wait_timeout()
                if wait_timeout is not None and wait_timeout > 0:
                    self.wait_for_activity(timeout=wait_timeout)
        except StopWatching:
            if not (self._stop_requested or self._stop_event.is_set()):
                raise
        finally:
            with self._drive_owner_lock:
                self._drive_loop_active = False
            self.stop(join=False)

    @final
    def run_forever(self) -> None:
        """Run with the BaseTask-shaped reactor loop instead of data-version polling."""

        signal_context = None
        self._running_event.set()
        try:
            signal_context = self._setup_signal_handler()
            self.run_until_stopped()
        finally:
            try:
                if signal_context is not None:
                    signal_context.__exit__(None, None, None)
            finally:
                self._running_event.clear()

    @final
    def run_in_thread(self) -> threading.Thread:
        """Start this reactor instance on its reserved background owner."""

        if not self._persistent:
            raise RuntimeError(
                "background reactors require persistent=True; use synchronous "
                "process_once() for transient handles"
            )
        with self._drive_owner_lock:
            if self._resources_closed:
                raise RuntimeError("cannot start a closed reactor")
            if self._drive_thread is not None:
                raise RuntimeError("reactor already has a drive owner")
            thread = threading.Thread(target=self.run_forever, daemon=True)
            self._drive_thread = thread
            self._drive_thread_starting = True
            self._thread = weakref.ref(thread)
        try:
            thread.start()
        except BaseException:
            with self._drive_owner_lock:
                if self._drive_thread is thread:
                    self._drive_thread = None
                    self._drive_thread_starting = False
                    self._thread = None
            if self._stop_requested:
                self.stop(join=False)
            raise
        return thread

    @final
    def start(self) -> threading.Thread:
        """Start this reactor instance on a background owner."""

        return self.run_in_thread()

    @final
    def run(self) -> None:
        """Drive this reactor instance synchronously."""

        self.run_forever()

    @final
    def cleanup(self) -> None:
        """Compatibility close entry point with reactor-safe ordering."""

        self.stop(join=False)

    def _close_reactor_resources(self) -> None:
        """Close queue handles after the drive owner has unwound."""

        try:
            self._strategy.close()
        except Exception:  # pragma: no cover - defensive third-party cleanup
            logger.debug("failed to close reactor polling strategy", exc_info=True)

        seen: set[int] = set()
        queues = list(self._queue_cache.values()) + [
            config.queue for config in self._queues.values()
        ]
        for queue in queues:
            if id(queue) in seen:
                continue
            seen.add(id(queue))
            try:
                queue.close()
            except (BrokerError, OSError, RuntimeError):
                logger.debug("failed to close reactor queue", exc_info=True)
        self._queue_cache.clear()

    @final
    def request_stop(self) -> None:
        """Signal the reactor without joining or closing owned resources."""

        with self._stop_once_lock:
            self._stop_requested = True
            self._stop_event.set()
            self._reactor_activity_event.set()
            self._strategy.notify_activity()

    @final
    def stop(self, *, join: bool = True, timeout: float = 2.0) -> None:
        """Request stop, then close only after the drive owner has unwound."""

        self.request_stop()
        current = threading.current_thread()
        with self._drive_owner_lock:
            drive_thread = self._drive_thread
            drive_thread_starting = self._drive_thread_starting
            turn_active = self._turn_active

        if drive_thread_starting:
            return

        if (
            join
            and drive_thread is not None
            and drive_thread is not current
            and drive_thread.is_alive()
        ):
            drive_thread.join(timeout)

        if (
            drive_thread is not None
            and drive_thread is not current
            and drive_thread.is_alive()
        ):
            return
        if drive_thread is current and turn_active:
            return

        with self._stop_once_lock:
            if self._resources_closed:
                return
            self._resources_closed = True

        try:
            super().stop(join=False, timeout=timeout)
        except Exception:  # pragma: no cover - defensive third-party cleanup
            logger.debug("inherited reactor cleanup failed", exc_info=True)
        finally:
            self._close_reactor_resources()


TautBaseWatcher = BaseReactor
"""Compatibility alias for extensions released before ``BaseReactor``."""


class TautWatcher(BaseReactor):
    """Cursor-aware taut live follower."""

    _dynamic_topology = True

    def __init__(
        self,
        runtime: TautWatchRuntime | TautClient,
        member_id: str,
        handler: Callable[[Message | Notification], None],
        *,
        threads: list[str] | None = None,
        stop_event: threading.Event | None = None,
        membership_refresh_interval: float = WATCH_MEMBERSHIP_REFRESH_SECONDS,
        persistent: bool = True,
        strict_membership: bool = True,
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
            runtime = _watch_runtime_for_client(runtime, persistent=persistent)
        self._runtime = runtime
        self.member_id = member_id
        self._user_handler = handler
        self._cursors: dict[str, int] = {}
        self._failures: dict[tuple[str, int], int] = {}
        self._ready_event: threading.Event | None = None
        self._ready_after_initial_drain = False
        self._thread_filter = set(threads) if threads else None
        self._membership_refresh_interval = membership_refresh_interval
        self._watch_persistent = persistent
        self._next_membership_refresh_at = time.monotonic()
        self._notification_queue_name = addressing.notification_queue_name(member_id)
        self._runtime_cleanup_done = False
        memberships = self._current_memberships(strict=strict_membership)
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
            persistent=persistent,
            inactive_probe_interval=membership_refresh_interval,
            config=self._runtime.config,
        )

    def list_queues(self) -> list[str]:
        return [
            name
            for name in super().list_queues()
            if name != self._notification_queue_name
        ]

    def get_queue(self, queue_name: str) -> Queue | None:
        return super().get_queue(queue_name)

    def notify_ready_after_initial_drain(self, event: threading.Event) -> None:
        """Signal ``event`` once the watcher has started and completed one drain."""

        self._ready_event = event
        if self._ready_after_initial_drain:
            event.set()

    def _close_reactor_resources(self) -> None:
        super()._close_reactor_resources()
        if self._runtime_cleanup_done:
            return
        self._runtime_cleanup_done = True
        close_runtime = getattr(self._runtime, "close", None)
        if callable(close_runtime):
            try:
                close_runtime()
            except (BrokerError, OSError, RuntimeError):
                logger.debug("failed to close watcher runtime", exc_info=True)

    def _current_memberships(self, *, strict: bool) -> list[WatchedThread]:
        rows = self._runtime.list_watched_threads(self.member_id)
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
        self._runtime.advance_cursor(
            thread=thread,
            member_id=self.member_id,
            seen_ts=timestamp,
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
            config.queue.peek_many(
                1,
                with_timestamps=True,
                after_timestamp=cursor,
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
            return queue.has_pending(after_timestamp=cursor)
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

    def _start_strategy(self) -> None:
        queue = self._get_queue_for_data_version()
        self._check_stop()

        def data_version_getter(q: Queue = queue) -> int | None:
            return q.get_data_version()

        def on_data_version_change(q: Queue = queue) -> None:
            self._on_data_version_change(q)

        activity_waiter = self._create_activity_waiter(queue)
        self._check_stop()
        self._strategy.start(
            data_version_getter,
            on_data_version_change=on_data_version_change,
            activity_waiter=activity_waiter,
        )
        self._check_stop()

    def _on_data_version_change(self, queue: Queue) -> None:
        del queue
        self._refresh_memberships()

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
            self._remove_thread_queue(thread)
            self._cursors.pop(thread, None)
            self._clear_failures_for_thread(thread)

    def _remove_thread_queue(self, thread: str) -> None:
        queue = self.get_queue(thread)
        self.remove_queue(thread)
        if queue is None:
            return
        try:
            queue.close()
        except (BrokerError, OSError, RuntimeError):
            logger.debug(
                "failed to close removed thread queue '%s'", thread, exc_info=True
            )

    def _clear_failures_for_thread(self, thread: str) -> None:
        stale_keys = [key for key in self._failures if key[0] == thread]
        for key in stale_keys:
            self._failures.pop(key, None)
