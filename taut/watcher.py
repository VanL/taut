"""Multi-queue scheduler copied from Weft, with Taut lifecycle and cursor policy.

Provenance: Weft 9fc913c1, weft/core/tasks/multiqueue_watcher.py.
The scheduler classes (QueueMode through MultiQueueWatcher) are exact upstream
bodies except the reviewed yield_strategy validation and typed stop rejection
at the three synchronous topology checks (see [TAUT-12.3]).
Module shims preserve Taut configuration and lazy explicit-target resolution.
BaseReactor and TautWatcher below the copy own Taut policy only.

Spec: docs/specs/02-taut-core.md [TAUT-8.4], [TAUT-8.5].
"""

from __future__ import annotations

import itertools
import logging
import signal
import sys
import threading
import time
import weakref
from collections import deque
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal, cast, final

from simplebroker import (
    BrokerSession,
    BrokerTarget,
    Config,
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
from taut._cleanup import capture_cleanup_failure
from taut._config import TAUT_CONFIG_DEFAULTS, load_config
from taut._constants import (
    CACHE_STALE_QUEUE_NAME,
    QUEUE_PRIORITY_NORMAL,
    WATCH_MEMBERSHIP_REFRESH_SECONDS,
)
from taut._exceptions import MembershipError, WatcherRejected
from taut._watch_runtime import TautWatchRuntime, WatchedThread
from taut.client import Message, Notification

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


def resolve_runtime_config(config: Mapping[str, Any] | None = None) -> Config:
    """Resolve defaults once, preserving an explicitly supplied snapshot."""
    if config is None:
        return load_config()
    if isinstance(config, Config):
        return config
    return Config(config, prefix="TAUT", defaults=TAUT_CONFIG_DEFAULTS)


def resolve_context_broker_target(
    starting_dir: str | Path | None = None,
    *,
    config: Config | None = None,
) -> Callable[[], BrokerTarget]:
    """Defer cwd fallback until the copied target shim actually needs it."""

    def resolve() -> BrokerTarget:
        target = resolve_broker_target(starting_dir, config=config)
        if target is None:
            root = Path.cwd() if starting_dir is None else Path(starting_dir)
            return BrokerTarget("sqlite", str(root / ".taut.db"))
        return target

    return resolve


class _TopologyStopping(RuntimeError):
    """Expected topology admission rejection after terminal stop publication."""


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


@dataclass(slots=True)
class _TopologyMutation:
    """One synchronous dynamic-topology request owned by the drive thread."""

    kind: str
    queue_name: str
    handler: Callable[[str, int, QueueMessageContext], None] | None = None
    mode: QueueMode = QueueMode.READ
    reserved_queue_name: str | None = None
    error_handler: Callable[[Exception, str, int], bool | None] | None = None
    priority: int = QUEUE_PRIORITY_NORMAL
    done: threading.Event = field(default_factory=threading.Event)
    error: BaseException | None = None


class _TopologyDriveError(Exception):
    """Wrap an owner transaction defect that must enter inherited retry."""

    def __init__(self, cause: Exception) -> None:
        super().__init__(str(cause))
        self.cause = cause


def _resolve_db_target(
    db: BrokerTarget | str | Path | None,
    fallback: Callable[[], BrokerTarget],
) -> BrokerTarget | str:
    """Derive a broker target shared across Queue instances."""
    if isinstance(db, BrokerTarget):
        return db
    if isinstance(db, (str, Path)):
        return str(db)
    return fallback()


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
            inactive_probe_interval: Minimum seconds between broad inactive
                queue discovery probes when no native activity hint is pending.
            default_error_handler_fn: Fallback error handler when queue config
                does not supply one (defaults to SimpleBroker's default)
            config: Optional resolved Config or canonical runtime mapping. If omitted,
                :func:`weft._constants.load_config` is used.

        Spec: [CC-2.1], [SB-0.4]
        """
        if not queue_configs:
            raise ValueError("queue_configs cannot be empty")
        if yield_strategy != "round_robin":
            raise ValueError("yield_strategy must be 'round_robin'")

        broker_config = resolve_runtime_config(config)
        self._weft_config: dict[str, Any] = dict(broker_config)

        self._persistent = persistent
        self._yield_strategy = yield_strategy
        self._inactive_probe_interval = max(0.0, float(inactive_probe_interval))
        self._default_error_handler = default_error_handler_fn
        self._handler: Callable[[str, int], None] | None = None
        self._error_handler: Callable[[Exception, str, int], bool | None] | None = None
        self._broker_session: BrokerSession | None = None
        self._owned_fixed_queues: list[Queue] = []
        self._owned_dynamic_queues: dict[int, Queue] = {}

        # Establish primary queue and shared broker target
        first_queue_name = next(iter(queue_configs.keys()))
        shared_target = _resolve_db_target(
            db,
            resolve_context_broker_target(Path.cwd(), config=broker_config),
        )
        try:
            if persistent:
                self._broker_session = BrokerSession.connect(
                    shared_target,
                    config=broker_config,
                )
                initial_queue = self._open_fixed_queue(first_queue_name)
            else:
                initial_queue = Queue(
                    first_queue_name,
                    db_path=shared_target,
                    persistent=False,
                    config=broker_config,
                )
                self._owned_fixed_queues.append(initial_queue)

            super().__init__(
                initial_queue,
                stop_event=stop_event,
                polling_strategy=polling_strategy,
                config=broker_config,
            )
            _detach_queue_stop_event(initial_queue)

            self._db_path = initial_queue.db_target

            # Build runtime configs for each queue
            self._queues: dict[str, QueueRuntimeConfig] = {}
            for queue_name, raw_config in queue_configs.items():
                self._add_initial_runtime_config(
                    queue_name,
                    raw_config,
                    first_queue_name=first_queue_name,
                    initial_queue=initial_queue,
                    default_error_handler_fn=default_error_handler_fn,
                )

            # Processing state
            self._active_queues: list[str] = []
            self._queue_iterator: itertools.cycle[str] = itertools.cycle([])
            self._queue_generation = 0
            self._multi_activity_waiter: Any | None = None
            self._multi_activity_waiter_generation: int | None = None
            self._multi_activity_waiter_signature: tuple[str, ...] | None = None
            self._strategy_started = False
            self._data_version_activity_pending = False
            self._native_activity_degraded = False
            self._pending_messages_precheck_confirmed = False
            self._next_inactive_probe_at = time.monotonic()
            self._topology_lock = threading.RLock()
            self._topology_mutations: deque[_TopologyMutation] = deque()
            self._topology_pending = threading.Event()
            self._topology_inflight: _TopologyMutation | None = None
            self._topology_dispatch_pass = False
            self._topology_owner_thread: threading.Thread | None = None
            self._topology_reserved_thread: threading.Thread | None = None
            self._topology_manual_wait_thread: threading.Thread | None = None
            self._topology_stopping = False
            self._topology_sigint_critical = False
            self._topology_deferred_sigint = False

            logger.debug(
                "MultiQueueWatcher initialized with queues: %s",
                list(self._queues.keys()),
            )
            self._ensure_multi_activity_waiter()
            if self._broker_session is not None:
                self._broker_session.recycle_thread()
        except BaseException as exc:
            try:
                self._close_owned_broker_resources()
            except BaseException as cleanup_exc:  # noqa: BLE001 - cleanup boundary
                exc.add_note(
                    "MultiQueueWatcher construction cleanup also failed: "
                    f"{cleanup_exc!r}"
                )
            raise

    def _open_fixed_queue(self, queue_name: str) -> Queue:
        """Open one construction-fixed queue under the inventory owner."""

        session = self._broker_session
        if session is None:
            queue = Queue(
                queue_name,
                db_path=self._db_path,
                persistent=self._persistent,
                config=self._broker_config,
            )
        else:
            queue = session.queue(queue_name)
        self._owned_fixed_queues.append(queue)
        return queue

    def _add_initial_runtime_config(
        self,
        queue_name: str,
        raw_config: Mapping[str, object],
        *,
        first_queue_name: str,
        initial_queue: Queue,
        default_error_handler_fn: Callable[[Exception, str, int], bool | None],
    ) -> None:
        """Validate and install one construction-fixed queue configuration."""

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
            queue_obj = self._open_fixed_queue(queue_name)

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

    @property
    def _broker_config(self) -> Config:
        """Return the retained SimpleBroker watcher configuration snapshot."""

        return self._config

    # ------------------------------------------------------------------ #
    # Public API                                                         #
    # ------------------------------------------------------------------ #

    def list_queues(self) -> list[str]:
        """Return all configured queue names.

        Spec: [CC-2.1]
        """
        with self._topology_lock:
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

        Spec: [CC-2.1], [SB-0.4], [QUEUE.8]
        """
        self._validate_add_arguments(
            handler=handler,
            mode=mode,
            reserved_queue=reserved_queue,
            error_handler=error_handler,
            priority=priority,
        )
        request = _TopologyMutation(
            kind="add",
            queue_name=queue_name,
            handler=handler,
            mode=mode,
            reserved_queue_name=reserved_queue,
            error_handler=error_handler,
            priority=priority,
        )
        self._submit_topology_mutation(request)

    def remove_queue(self, queue_name: str) -> None:
        """Remove a queue from the watcher.

        Spec: [CC-2.1], [SB-0.4], [QUEUE.8]
        """
        self._submit_topology_mutation(
            _TopologyMutation(kind="remove", queue_name=queue_name)
        )

    def get_queue(self, queue_name: str) -> Queue | None:
        """Return the managed Queue instance for *queue_name* if present.

        Spec: [SB-0.1]
        """
        with self._topology_lock:
            config = self._queues.get(queue_name)
        return config.queue if config else None

    # ------------------------------------------------------------------ #
    # Internal helpers                                                   #
    # ------------------------------------------------------------------ #
    @staticmethod
    def _validate_add_arguments(
        *,
        handler: Callable[[str, int, QueueMessageContext], None],
        mode: QueueMode,
        reserved_queue: str | None,
        error_handler: Callable[[Exception, str, int], bool | None] | None,
        priority: int,
    ) -> None:
        """Validate one public add request before it can have effects."""
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

    def _open_runtime_config(self, request: _TopologyMutation) -> QueueRuntimeConfig:
        """Open the queue facade for an already validated add request."""
        handler = request.handler
        if handler is None:  # pragma: no cover - internal invariant
            raise RuntimeError("add mutation is missing its handler")
        # Direct Queue ok here: MultiQueueWatcher owns dynamically watched queue
        # handles by design; see runtime-and-context-patterns.md section 2.
        queue_obj = Queue(
            request.queue_name,
            db_path=self._db_path,
            persistent=self._persistent,
            config=self._broker_config,
        )
        _detach_queue_stop_event(queue_obj)
        return QueueRuntimeConfig(
            name=request.queue_name,
            queue=queue_obj,
            handler=handler,
            mode=request.mode,
            error_handler=request.error_handler or self._default_error_handler,
            reserved_queue_name=request.reserved_queue_name,
            priority=request.priority,
        )

    def _register_dynamic_queue(self, queue: Queue) -> None:
        """Retain one dynamic queue until removal or watcher teardown."""

        self._owned_dynamic_queues[id(queue)] = queue

    def _close_dynamic_queue(self, queue: Queue) -> None:
        """Release one displaced dynamic queue, retaining it after failure."""

        try:
            queue.close()
        except BaseException:
            logger.warning(
                "Failed to close removed queue %s; retaining it for teardown",
                queue.name,
                exc_info=True,
            )
            raise
        else:
            self._owned_dynamic_queues.pop(id(queue), None)

    def _submit_topology_mutation(self, request: _TopologyMutation) -> None:
        """Apply before drive start or synchronously submit to the drive owner."""
        current = threading.current_thread()
        with self._topology_lock:
            if self._topology_stopping or self._stop_event.is_set():
                raise _TopologyStopping("watcher topology is stopping")
            if self._topology_manual_wait_thread is not None:
                raise RuntimeError("watcher topology is owned by a manual wait")
            if self._topology_owner_thread is current:
                self._claim_owner_topology_mutation_locked(request)
                owner_synchronous = True
            elif (
                self._topology_owner_thread is None
                and self._topology_reserved_thread is None
            ):
                self._apply_topology_mutation_before_start_locked(request)
                return
            else:
                owner_synchronous = False
                self._topology_mutations.append(request)
                self._topology_pending.set()
                self._strategy.notify_activity()

        if owner_synchronous:
            # The owner applies its own request through the same transaction the
            # apply loop uses, between dispatch passes, so no deque wait is needed.
            retry_error, fatal_error = self._run_owner_topology_transaction(request)
            self._finish_topology_sigint_critical(fatal_error=fatal_error)
            if retry_error is not None:
                raise retry_error
        else:
            request.done.wait()
        if request.error is not None:
            raise request.error

    def _claim_owner_topology_mutation_locked(self, request: _TopologyMutation) -> None:
        """Admit one synchronous owner mutation between dispatch passes.

        A handler runs inside a dispatch pass that iterates the active queue set
        and may hold the Queue a removal would close, so mutation from there is
        rejected before effects. A second mutation while one transaction is in
        flight is likewise rejected.

        Spec: [QUEUE.8]
        """
        if self._topology_dispatch_pass:
            raise RuntimeError(
                "drive owner cannot mutate topology during a dispatch pass"
            )
        if self._topology_inflight is not None:
            raise RuntimeError("topology mutation is reentrant")
        self._topology_inflight = request

    def _apply_topology_mutation_before_start_locked(
        self,
        request: _TopologyMutation,
    ) -> None:
        """Apply one mutation synchronously while no drive can exist."""
        if request.kind == "add":
            if request.queue_name in self._queues:
                raise ValueError(f"Queue '{request.queue_name}' already exists")
            runtime = self._open_runtime_config(request)
            self._queues[request.queue_name] = runtime
            self._register_dynamic_queue(runtime.queue)
            self._pending_messages_precheck_confirmed = True
        elif request.kind == "remove":
            if request.queue_name not in self._queues:
                raise ValueError(f"Queue '{request.queue_name}' not found")
            runtime = self._queues.pop(request.queue_name)
            self._active_queues = [
                name for name in self._active_queues if name != request.queue_name
            ]
            self._queue_iterator = itertools.cycle(self._active_queues)
        else:  # pragma: no cover - internal invariant
            raise RuntimeError(f"unknown topology mutation: {request.kind}")
        self._queue_generation += 1
        self._reset_multi_activity_waiter()
        if request.kind == "remove":
            self._close_dynamic_queue(runtime.queue)

    def _create_candidate_activity_waiter(
        self,
        mapping: Mapping[str, QueueRuntimeConfig],
    ) -> tuple[Any | None, tuple[str, ...], bool]:
        """Build the optional native waiter for an exact candidate mapping."""
        wait_configs = self._activity_wait_configs(mapping=mapping)
        signature = tuple(config.name for config in wait_configs)
        if not wait_configs:
            return None, signature, False
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
            return waiter, signature, True
        return waiter, signature, False

    @staticmethod
    def _close_candidate_resource_once(resource: Any | None) -> None:
        """Close one rollback-owned resource without masking the cause."""
        if resource is None:
            return
        try:
            resource.close()
        except Exception:  # pragma: no cover - defensive backend cleanup
            logger.debug("Failed to close candidate topology resource", exc_info=True)

    def _close_activity_waiter_once(self, waiter: Any | None) -> None:
        """Close a displaced waiter through its idempotent resource contract.

        ActivityWaiter.close is terminal, including after cleanup errors
        (SimpleBroker [SB-API-6]); object ids are not lifetime identities.
        """
        if waiter is None:
            return
        try:
            waiter.close()
        except Exception:  # pragma: no cover - defensive backend cleanup
            logger.debug("Failed to close multi-queue activity waiter", exc_info=True)

    def _publish_topology_locked(
        self,
        *,
        mapping: dict[str, QueueRuntimeConfig],
        generation: int,
        signature: tuple[str, ...],
        waiter: Any | None,
        active_queues: list[str],
        queue_iterator: itertools.cycle[str],
        force_discovery: bool,
        native_degraded: bool,
    ) -> None:
        """Publish prebuilt topology state after strategy replacement."""
        self._queues = mapping
        self._queue_generation = generation
        self._multi_activity_waiter = waiter
        self._multi_activity_waiter_generation = generation
        self._multi_activity_waiter_signature = signature
        self._native_activity_degraded = native_degraded
        self._active_queues = active_queues
        self._queue_iterator = queue_iterator
        if force_discovery:
            self._pending_messages_precheck_confirmed = True

    def _apply_topology_mutation_on_owner(self, request: _TopologyMutation) -> None:  # noqa: C901 approved [TS-3.1] [RUFF-SUP-045] exception
        """Build, replace, and publish one mutation on the drive owner.

        Spec: [CC-2.1], [SB-0.4], [QUEUE.8]
        """
        candidate_config: QueueRuntimeConfig | None = None
        candidate_waiter: Any | None = None
        candidate_installed = False
        candidate_rollback_owned = False
        topology_published = False
        strategy_changed = False
        prior_installed_waiter: Any | None = None
        displaced_waiter: Any | None = None

        with self._topology_lock:
            if self._topology_stopping or self._stop_event.is_set():
                raise _TopologyStopping("watcher topology is stopping")
            generation = self._queue_generation
            prior_mapping = self._queues
            prior_cached_waiter = self._multi_activity_waiter
            strategy_had_native = self._strategy.uses_native_activity()
            prior_installed_waiter = (
                prior_cached_waiter if strategy_had_native else None
            )
            if request.kind == "add" and request.queue_name in prior_mapping:
                raise ValueError(f"Queue '{request.queue_name}' already exists")
            if request.kind == "remove" and request.queue_name not in prior_mapping:
                raise ValueError(f"Queue '{request.queue_name}' not found")

        try:
            candidate_mapping = dict(prior_mapping)
            if request.kind == "add":
                candidate_config = self._open_runtime_config(request)
                candidate_mapping[request.queue_name] = candidate_config
            else:
                del candidate_mapping[request.queue_name]

            (
                candidate_waiter,
                signature,
                native_degraded,
            ) = self._create_candidate_activity_waiter(candidate_mapping)
            candidate_rollback_owned = (
                candidate_waiter is not None
                and candidate_waiter is not prior_cached_waiter
            )
            active_queues = [
                name for name in self._active_queues if name in candidate_mapping
            ]
            queue_iterator = itertools.cycle(active_queues)

            with self._topology_lock:
                if self._topology_stopping or self._stop_event.is_set():
                    raise _TopologyStopping("watcher topology is stopping")
                if self._queue_generation != generation:
                    raise _TopologyDriveError(
                        RuntimeError("topology generation changed outside drive owner")
                    )

                self._topology_sigint_critical = True
                try:
                    strategy_changed = candidate_waiter is not prior_installed_waiter
                    displaced_waiter = self._strategy.replace_activity_waiter(
                        candidate_waiter
                    )
                    candidate_installed = (
                        strategy_changed and candidate_waiter is not None
                    )
                    try:
                        self._publish_topology_locked(
                            mapping=candidate_mapping,
                            generation=generation + 1,
                            signature=signature,
                            waiter=candidate_waiter,
                            active_queues=active_queues,
                            queue_iterator=queue_iterator,
                            force_discovery=request.kind == "add",
                            native_degraded=native_degraded,
                        )
                        topology_published = True
                    except BaseException:
                        if strategy_changed:
                            restored_candidate = self._strategy.replace_activity_waiter(
                                displaced_waiter
                            )
                            if candidate_rollback_owned:
                                self._close_activity_waiter_once(restored_candidate)
                            candidate_rollback_owned = False
                            candidate_installed = False
                        raise
                except Exception as exc:
                    raise _TopologyDriveError(exc) from exc

            if request.kind == "add":
                assert candidate_config is not None
                self._register_dynamic_queue(candidate_config.queue)
            close_candidates: list[Any] = []
            for waiter in (prior_cached_waiter, displaced_waiter):
                if (
                    waiter is not None
                    and waiter is not candidate_waiter
                    and all(waiter is not seen for seen in close_candidates)
                ):
                    close_candidates.append(waiter)
            for waiter in close_candidates:
                self._close_activity_waiter_once(waiter)
            if request.kind == "remove":
                self._close_dynamic_queue(prior_mapping[request.queue_name].queue)
        finally:
            if not topology_published:
                if candidate_waiter is not None and not candidate_installed:  # noqa: SIM102 approved [TS-3.1] [RUFF-SUP-242] exception
                    if candidate_rollback_owned:
                        self._close_candidate_resource_once(candidate_waiter)
                if candidate_config is not None:
                    self._close_candidate_resource_once(candidate_config.queue)

    def _apply_pending_topology_mutations(self) -> None:
        """Complete queued mutations in FIFO order on the drive owner."""
        if threading.current_thread() is not self._topology_owner_thread:
            return
        if not self._topology_pending.is_set():
            return
        while True:
            with self._topology_lock:
                if not self._topology_mutations:
                    self._topology_pending.clear()
                    return
                request = self._topology_mutations.popleft()
                self._topology_inflight = request
            retry_error, fatal_error = self._run_owner_topology_transaction(request)
            self._finish_topology_sigint_critical(fatal_error=fatal_error)
            if retry_error is not None:
                raise retry_error

    def _run_owner_topology_transaction(
        self, request: _TopologyMutation
    ) -> tuple[Exception | None, BaseException | None]:
        """Run one owner transaction with shared error precedence and cleanup.

        Returns ``(retry_error, fatal_error)``. Ordinary failures are recorded
        on the request only. The caller finishes the SIGINT-critical boundary.

        Spec: [QUEUE.8]
        """
        retry_error: Exception | None = None
        fatal_error: BaseException | None = None
        try:
            self._apply_topology_mutation_on_owner(request)
        except _TopologyDriveError as exc:
            request.error = exc.cause
            retry_error = exc.cause
        except Exception as exc:  # noqa: BLE001 approved [TS-3.1] [RUFF-SUP-339] exception
            # One ordinary request failure stays local; later FIFO requests run.
            request.error = exc
        except BaseException as exc:  # noqa: BLE001 approved [TS-3.1] [RUFF-SUP-339] exception
            # A fatal owner exit releases every caller before exact re-raise.
            request.error = RuntimeError(
                "watcher drive exited during topology mutation"
            )
            with self._topology_lock:
                while self._topology_mutations:
                    pending = self._topology_mutations.popleft()
                    pending.error = RuntimeError(
                        "watcher drive exited during topology mutation"
                    )
                    pending.done.set()
            fatal_error = exc
        finally:
            with self._topology_lock:
                if self._topology_inflight is request:
                    self._topology_inflight = None
                if not self._topology_mutations:
                    self._topology_pending.clear()
            request.done.set()
        return retry_error, fatal_error

    def _finish_topology_sigint_critical(
        self,
        *,
        fatal_error: BaseException | None = None,
    ) -> None:
        """Finish one atomic topology transaction and deliver its fatal outcome.

        A fatal mutation failure is the transaction's specific unwind cause,
        so it has priority over the generic interrupt.  The deferred SIGINT
        still stops the watcher and is consumed before the exact fatal object
        is re-raised.
        """
        self._topology_sigint_critical = False
        deferred_sigint = self._topology_deferred_sigint
        if deferred_sigint:
            self._topology_deferred_sigint = False
            self.stop(join=False)
        if fatal_error is not None:
            raise fatal_error
        if deferred_sigint:
            raise KeyboardInterrupt

    def _sigint_handler(self, signum: int, frame: Any) -> None:
        """Defer SIGINT only while waiter replacement is half-published.

        Spec: docs/specifications/07-System_Invariants.md [QUEUE.8]
        """
        if self._topology_sigint_critical:
            # Only assign plain state here: Event.set or strategy callbacks can
            # reacquire a lock held by the interrupted thread. The finish boundary
            # performs stop/wake effects after the transaction and request settle.
            self._topology_deferred_sigint = True
            return
        super()._sigint_handler(signum, frame)

    def _queue_counts_as_wait_activity(self, config: QueueRuntimeConfig) -> bool:
        """Return whether *config* should wake ``wait_for_activity``."""

        del config
        return True

    def _activity_wait_configs(
        self,
        *,
        mapping: Mapping[str, QueueRuntimeConfig] | None = None,
    ) -> list[QueueRuntimeConfig]:
        """Return queue configs that should wake ``wait_for_activity``."""

        return [
            config
            for config in (self._queues if mapping is None else mapping).values()
            if self._queue_counts_as_wait_activity(config)
        ]

    def _activity_wait_queues(self) -> list[Queue]:
        """Return queues watched by the multi-queue activity waiter."""

        return [config.queue for config in self._activity_wait_configs()]

    def _reset_multi_activity_waiter(self) -> None:
        """Close the caller-owned multi-queue waiter if one is active."""
        waiter = self._multi_activity_waiter
        self._multi_activity_waiter = None
        self._multi_activity_waiter_generation = None
        self._multi_activity_waiter_signature = None
        if waiter is None:
            return

        self._strategy.detach_activity_waiter(expected=waiter)
        self._close_activity_waiter_once(waiter)

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
            logger.debug(
                "Multi-queue activity waiter unavailable; falling back to polling",
                exc_info=True,
            )
            self._multi_activity_waiter = None
            self._native_activity_degraded = True
        else:
            self._native_activity_degraded = False
        return self._multi_activity_waiter

    def _create_activity_waiter(self, queue: Queue) -> Any | None:
        """Supply Weft's multi-queue waiter to SimpleBroker strategy startup."""
        del queue
        self._apply_pending_topology_mutations()
        return self._ensure_multi_activity_waiter()

    def _start_strategy(self) -> None:
        """Start or restart the retained strategy and record successful ownership."""

        super()._start_strategy()
        self._strategy_started = True
        if self._strategy.uses_native_activity():
            self._native_activity_degraded = False

    def _on_data_version_change(self, queue: Queue) -> None:
        """Record one SQLite backend hint after inherited cache synchronization."""

        super()._on_data_version_change(queue)
        self._data_version_activity_pending = True

    def run_in_thread(self) -> threading.Thread:
        """Reserve and start exactly one background drive thread.

        Spec: [CC-2.1], [QUEUE.8]
        """
        with self._topology_lock:
            if self._topology_stopping or self._stop_event.is_set():
                raise RuntimeError("cannot start a stopped watcher")
            if self._topology_manual_wait_thread is not None:
                raise RuntimeError("cannot start a drive during a manual wait")
            if (
                self._topology_owner_thread is not None
                or self._topology_reserved_thread is not None
            ):
                raise RuntimeError("watcher already has a drive owner")
            thread = threading.Thread(target=self.run_forever, daemon=True)
            self._topology_reserved_thread = thread
            self._thread = weakref.ref(thread)
            try:
                thread.start()
            except BaseException:
                if self._topology_reserved_thread is thread:
                    self._topology_reserved_thread = None
                thread_ref = self._thread
                if thread_ref is not None and thread_ref() is thread:
                    self._thread = None
                raise
            return thread

    def run_forever(self) -> None:
        """Claim the drive owner around SimpleBroker's inherited retry loop.

        Spec: [CC-2.1], [SB-0.4], [QUEUE.8]
        """
        current = threading.current_thread()
        with self._topology_lock:
            reservation = self._topology_reserved_thread
            if (
                self._topology_stopping or self._stop_event.is_set()
            ) and reservation is not current:
                raise RuntimeError("cannot start a stopped watcher")
            if self._topology_owner_thread is not None:
                raise RuntimeError("watcher already has a drive owner")
            if self._topology_manual_wait_thread is not None:
                raise RuntimeError("cannot start a drive during a manual wait")
            if reservation is not None and reservation is not current:
                raise RuntimeError("watcher drive is reserved by another thread")
            self._topology_owner_thread = current
            if reservation is current:
                self._topology_reserved_thread = None
            else:
                self._thread = weakref.ref(current)
        try:
            super().run_forever()
        finally:
            with self._topology_lock:
                self._reset_multi_activity_waiter()
                if self._topology_inflight is not None:
                    request = self._topology_inflight
                    request.error = RuntimeError("watcher drive stopped")
                    request.done.set()
                    self._topology_inflight = None
                if self._topology_owner_thread is current:
                    self._topology_owner_thread = None
                while self._topology_mutations:
                    request = self._topology_mutations.popleft()
                    request.error = RuntimeError("watcher drive stopped")
                    request.done.set()
                self._topology_pending.clear()
                thread_ref = self._thread
                if thread_ref is not None and thread_ref() is current:
                    self._thread = None

    def _cleanup_runtime_resources(self) -> None:
        """Detach Weft-owned waiters before inherited strategy cleanup."""

        try:
            self._reset_multi_activity_waiter()
            super()._cleanup_runtime_resources()
        finally:
            self._strategy_started = False

    def _close_owned_broker_resources(self) -> None:
        """Close every queue lease before the inventory session lease."""

        failures: list[BaseException] = []
        queues = [*self._owned_fixed_queues, *self._owned_dynamic_queues.values()]
        seen: set[int] = set()
        for queue in queues:
            queue_id = id(queue)
            if queue_id in seen:
                continue
            seen.add(queue_id)
            try:
                queue.close()
            except BaseException as exc:
                failures.append(exc)
                logger.warning(
                    "Failed to close owned queue %s",
                    queue.name,
                    exc_info=True,
                )

        session = self._broker_session
        if session is not None:
            try:
                session.close()
            except BaseException as exc:
                failures.append(exc)
                logger.warning("Failed to close watcher broker session", exc_info=True)
            else:
                self._broker_session = None

        if not failures:
            self._owned_fixed_queues.clear()
            self._owned_dynamic_queues.clear()
            return
        primary = failures[0]
        for secondary in failures[1:]:
            primary.add_note(f"Additional broker cleanup failure: {secondary!r}")
        raise primary

    def _cleanup_owned_resources(self) -> None:
        """Attempt strategy and broker cleanup without skipping later phases."""

        failures: list[BaseException] = []
        for operation in (
            self._cleanup_runtime_resources,
            self._close_owned_broker_resources,
        ):
            try:
                operation()
            except BaseException as exc:  # noqa: BLE001 - cleanup boundary
                failures.append(exc)
        if failures:
            primary = failures[0]
            for secondary in failures[1:]:
                primary.add_note(f"Additional watcher cleanup failure: {secondary!r}")
            raise primary

    def _cleanup_stop_resources(self) -> None:
        """Release idle watcher resources without claiming another thread's cache."""

        self._cleanup_owned_resources()

    def _cleanup_run_resources(self) -> None:
        """Release run-thread resources through the inventory session owner."""

        self._cleanup_owned_resources()

    def _wait_for_activity_body(self, timeout: float | None) -> None:
        """Drive the retained strategy until broker, local, stop, or timer work.

        Strategy returns are readiness hints. Backend hints are confirmed with
        live queue state before dispatch, while a consumed local hint always
        returns to the owner so broker-free source state can run.

        Spec: [CC-2.1], [SB-0.4]
        """
        if self._stop_event.is_set() or (timeout is not None and timeout <= 0):
            return

        self._ensure_wait_strategy_started()

        deadline = None if timeout is None else time.monotonic() + timeout
        while not self._stop_event.is_set():
            remaining = None if deadline is None else deadline - time.monotonic()
            if remaining is not None and remaining <= 0:
                return

            try:
                self._strategy.wait_for_activity(timeout=remaining)
            except (BrokerError, OSError, RuntimeError, TypeError, ValueError):
                if self._multi_activity_waiter is None:
                    raise
                logger.debug(
                    "Multi-queue activity waiter failed; falling back to polling",
                    exc_info=True,
                )
                self._native_activity_degraded = True
                self._reset_multi_activity_waiter()
                continue

            if self._stop_event.is_set():
                return

            if self._activity_hint_action(deadline=deadline) == "return":
                return

    def _ensure_wait_strategy_started(self) -> None:
        """Start the strategy or reinstall a waiter displaced by topology."""

        if not self._strategy_started:
            self._start_strategy()
            return
        waiter = self._ensure_multi_activity_waiter()
        if waiter is None or self._strategy.uses_native_activity():
            return
        displaced = self._strategy.replace_activity_waiter(waiter)
        if displaced is not None and displaced is not waiter:
            self._close_activity_waiter_once(displaced)

    def _activity_hint_action(
        self,
        *,
        deadline: float | None,
    ) -> Literal["return", "continue"]:
        """Validate strategy hints and decide whether the owner gets a turn."""

        local_hint = self._strategy.consume_local_activity_hint()
        native_hint = self._strategy.consume_native_activity_hint()
        data_version_hint = self._data_version_activity_pending
        self._data_version_activity_pending = False

        if local_hint:
            if self._has_pending_messages():
                self._mark_pending_messages_prechecked()
            return "return"

        if native_hint or data_version_hint:
            if self._has_pending_messages():
                self._mark_pending_messages_prechecked()
                return "return"
            return "continue"

        deadline_reached = deadline is not None and time.monotonic() >= deadline
        if self._strategy.uses_native_activity() and not deadline_reached:
            if self._has_pending_messages():
                self._mark_pending_messages_prechecked()
                return "return"
            return "continue"
        if deadline_reached:
            return "return"
        # A nonpersistent SQLite queue opens a fresh connection for each
        # operation, so its connection-local PRAGMA data_version cannot be a
        # durable change detector across strategy turns. Confirm readiness at
        # the end of each fallback turn. PostgreSQL still uses its native
        # activity waiter, and persistent SQLite tasks retain data_version as
        # their quiet-path filter.
        transient_fallback = (
            not self._persistent and not self._strategy.uses_native_activity()
        )
        if (
            self._native_activity_degraded or transient_fallback
        ) and self._has_pending_messages():
            self._mark_pending_messages_prechecked()
            return "return"
        return "continue"

    def wait_for_activity(self, timeout: float | None) -> None:
        """Run one manual wait while excluding drive and topology ownership.

        Spec: [CC-2.1], [SB-0.4], [QUEUE.8]
        """
        if timeout is None or timeout <= 0:
            return
        current = threading.current_thread()
        with self._topology_lock:
            if self._topology_stopping or self._stop_event.is_set():
                return
            if (
                self._topology_owner_thread is not None
                or self._topology_reserved_thread is not None
            ):
                raise RuntimeError("manual wait cannot overlap a background drive")
            if self._topology_manual_wait_thread is not None:
                raise RuntimeError("watcher already has a manual wait owner")
            self._topology_manual_wait_thread = current

        deferred_stop = False
        try:
            self._wait_for_activity_body(timeout)
        finally:
            with self._topology_lock:
                if self._topology_manual_wait_thread is current:
                    if self._topology_stopping or self._stop_event.is_set():
                        self._reset_multi_activity_waiter()
                        deferred_stop = True
                    self._topology_manual_wait_thread = None
            if deferred_stop:
                super().stop(join=False)

    def stop(self, *, join: bool = True, timeout: float = 2.0) -> None:
        """Stop the watcher and close its multi-queue activity waiter.

        Spec: [CC-2.1], [QUEUE.8]
        """
        with self._topology_lock:
            self._topology_stopping = True
            self._stop_event.set()
            self._strategy.notify_activity()
            while self._topology_mutations:
                request = self._topology_mutations.popleft()
                request.error = RuntimeError("watcher topology is stopping")
                request.done.set()
            if self._topology_inflight is None:
                self._topology_pending.clear()
            no_owner = (
                self._topology_owner_thread is None
                and self._topology_reserved_thread is None
                and self._topology_manual_wait_thread is None
            )
            if no_owner:
                self._reset_multi_activity_waiter()
            manual_wait_active = self._topology_manual_wait_thread is not None
        if manual_wait_active:
            return
        super().stop(join=join, timeout=timeout)

    def _has_pending_messages(self) -> bool:
        """Return ``True`` when any configured queue still has pending messages.

        Spec: [CC-2.1]
        """
        self._apply_pending_topology_mutations()
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

    def _fetch_next_message(self, config: QueueRuntimeConfig) -> tuple[str, int] | None:
        """Fetch the next message for a queue based on its configured processing mode.

        Spec: [CC-2.1], [SB-0.3]
        """
        if config.mode is QueueMode.READ:
            return config.queue.read_one(with_timestamps=True)
        if config.mode is QueueMode.PEEK:
            return config.queue.peek_one(with_timestamps=True)
        if config.mode is QueueMode.RESERVE:
            if not config.reserved_queue_name:
                raise RuntimeError(
                    f"Queue '{config.name}' configured for reserve mode missing reserved queue"
                )
            return config.queue.move_one(
                config.reserved_queue_name,
                with_timestamps=True,
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
            self._dispatch(body, timestamp, config=self._broker_config)
        finally:
            self._handler = original_handler
            self._error_handler = original_error_handler

        if self._stop_event.is_set() or not self._queue_has_pending(config.queue):
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
        self._apply_pending_topology_mutations()
        self._update_active_queues()
        if not self._active_queues:
            return

        self._topology_dispatch_pass = True
        try:
            if len(self._active_queue_priorities()) <= 1:
                messages_processed = self._drain_round_robin_pass()
            else:
                messages_processed = self._drain_priority_queues()
        finally:
            self._topology_dispatch_pass = False

        if messages_processed > 0:
            self._strategy.notify_activity()


def _taut_default_error_handler(
    exc: Exception,
    message: str,
    timestamp: int,
) -> bool | None:
    """Stop on terminal sink closure; preserve broker policy otherwise."""

    if isinstance(exc, (StopWatching, WatcherRejected)):
        return False
    return default_error_handler(exc, message, timestamp)


class BaseReactor(MultiQueueWatcher):
    """Shared reactor lifecycle seam for long-lived Taut queue owners."""

    _dynamic_topology = False

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._reject_legacy_lifecycle_overrides()
        self._drive_owner_lock = threading.Lock()
        self._drive_thread: threading.Thread | None = None
        self._drive_thread_starting = False
        self._turn_active = False
        self._drive_loop_active = False
        self._stop_once_lock = threading.Lock()
        self._stop_requested = False
        self._pending_interrupt = False
        self._resources_closed = False
        self._resources_closing = False
        if not hasattr(self, "_cursors"):
            self._cursors: dict[str, int] = {}
        super().__init__(*args, **kwargs)

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
        """Reuse a configured queue or the copied inventory's fixed lease."""
        managed = self.get_queue(name)
        if managed is not None:
            return managed
        for queue in self._owned_fixed_queues:
            if queue.name == name:
                return queue
        queue = self._open_fixed_queue(name)
        _detach_queue_stop_event(queue)
        return queue

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
        super().add_queue(
            queue_name,
            handler,
            mode=mode,
            reserved_queue=reserved_queue,
            error_handler=error_handler,
            priority=priority,
        )

    def remove_queue(self, queue_name: str) -> None:
        self._check_topology_mutation()
        super().remove_queue(queue_name)

    def _check_topology_mutation(self) -> None:
        if not self._dynamic_topology:
            raise NotImplementedError("reactor queues are fixed at construction")
        with self._drive_owner_lock:
            owner = self._drive_thread
            if (
                owner is not None
                and owner is not threading.current_thread()
                and not self._drive_loop_active
                and not self._drive_thread_starting
            ):
                raise RuntimeError("manual reactor topology is drive-owner-only")

    def _claim_reactor_thread(self) -> None:
        """Claim or verify the one thread allowed to drive this reactor."""

        current = threading.current_thread()
        with self._drive_owner_lock:
            if self._drive_thread is None:
                self._drive_thread = current
                self._drive_thread_starting = False
                self._topology_owner_thread = current
                return
            if self._drive_thread is current:
                self._drive_thread_starting = False
                self._topology_owner_thread = current
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

    def _fetch_next_message(self, config: QueueRuntimeConfig) -> tuple[str, int] | None:
        if config.mode is not QueueMode.PEEK:
            return super()._fetch_next_message(config)
        rows = config.queue.peek_many(
            1, with_timestamps=True, after_timestamp=self._cursors.get(config.name, 0)
        )
        return rows[0] if rows else None

    def _queue_has_pending(self, queue: Queue) -> bool:
        if self._stop_event.is_set():
            return False
        config = self._queues.get(queue.name)
        if config is None or config.mode is not QueueMode.PEEK:
            return super()._queue_has_pending(queue)
        try:
            return queue.has_pending(after_timestamp=self._cursors.get(queue.name, 0))
        except BrokerError:
            if self._stop_event.is_set():
                return False
            raise

    def _activity_hint_action(
        self, *, deadline: float | None
    ) -> Literal["return", "continue"]:
        # Upstream treats a successful None waiter as ordinary SQLite polling.
        # A backend without data_version has no hint in that mode; reuse its
        # existing degraded-source confirmation on the same strategy pass.
        if (
            not self._strategy.uses_native_activity()
            and not self._native_activity_degraded
            and self._get_queue_for_data_version().get_data_version() is None
        ):
            self._native_activity_degraded = True
        return super()._activity_hint_action(deadline=deadline)

    def next_wait_timeout(self) -> float | None:
        """Return a deadline only for actual domain clock work."""
        return None

    def notify_activity(self) -> None:
        """Notify the retained arbiter after publishing owner-visible state."""
        self._strategy.notify_activity()

    def _sigint_handler(self, signum: int, frame: Any) -> None:
        """Latch one graceful interrupt; let a second escape immediately."""
        del signum, frame
        if self._pending_interrupt:
            raise KeyboardInterrupt
        self._pending_interrupt = True
        self._stop_requested = True
        self._strategy.notify_activity()

    def _raise_if_interrupt_pending(self) -> None:
        if self._pending_interrupt:
            raise KeyboardInterrupt

    @final
    def wait_for_activity(self, timeout: float | None = None) -> None:
        self._claim_reactor_thread()
        if timeout is None or timeout <= 0 or self._stop_event.is_set():
            return
        self._wait_for_activity_body(timeout)

    @final
    def run_until_stopped(self, *, max_iterations: int | None = None) -> None:
        """Run the explicit process/wait reactor loop used by Weft BaseTask."""

        self._claim_reactor_thread()
        with self._drive_owner_lock:
            self._drive_loop_active = True
        current = threading.current_thread()
        with self._topology_lock:
            reservation = self._topology_reserved_thread
            if self._topology_owner_thread not in (None, current):
                raise RuntimeError("watcher already has a drive owner")
            if self._topology_manual_wait_thread is not None:
                raise RuntimeError("cannot start a drive during a manual wait")
            if reservation is not None and reservation is not current:
                raise RuntimeError("watcher drive is reserved by another thread")
            self._topology_owner_thread = current
            self._topology_reserved_thread = None
            self._thread = weakref.ref(current)
        iterations = 0
        try:
            self._raise_if_interrupt_pending()
            if self._stop_event.is_set():
                return
            self._ensure_wait_strategy_started()
            while not self._stop_event.is_set():
                self._raise_if_interrupt_pending()
                self.process_once()
                iterations += 1
                self._raise_if_interrupt_pending()
                if max_iterations is not None and iterations >= max_iterations:
                    break
                if self._stop_event.is_set():
                    break

                wait_timeout = self.next_wait_timeout()
                self._wait_for_activity_body(wait_timeout)
        except StopWatching:
            # SimpleBroker uses this exception as terminal handler control flow.
            # The handler may raise it before the reactor stop flag is visible.
            pass
        finally:
            with self._drive_owner_lock:
                self._drive_loop_active = False
            try:
                self._finalize_run()
            finally:
                self._retire_topology_owner()

    def _retire_topology_owner(self) -> None:
        """Leave the copied scheduler's owner scope after the custom loop."""
        with self._topology_lock:
            self._reset_multi_activity_waiter()
            if self._topology_inflight is not None:
                request = self._topology_inflight
                request.error = RuntimeError("watcher drive stopped")
                request.done.set()
                self._topology_inflight = None
            self._topology_owner_thread = None
            while self._topology_mutations:
                request = self._topology_mutations.popleft()
                request.error = RuntimeError("watcher drive stopped")
                request.done.set()
            self._topology_pending.clear()
            self._thread = None

    def _finalize_run(self) -> None:
        """Finalize without replacing an exception already leaving the run."""

        active_failure = sys.exception()
        try:
            self.stop(join=False)
        except Exception as cleanup_failure:
            if active_failure is None:
                raise
            note = f"reactor cleanup failed: {cleanup_failure}"
            if note not in getattr(active_failure, "__notes__", ()):
                active_failure.add_note(note)

    @final
    def run_forever(self) -> None:
        """Run with the BaseTask-shaped reactor loop instead of data-version polling."""

        previous_sigint_handler: Any = None
        restore_sigint_handler = False
        try:
            self._running_event.set()
            if threading.current_thread() is threading.main_thread():
                previous_sigint_handler = signal.getsignal(signal.SIGINT)
                restore_sigint_handler = True
                signal.signal(signal.SIGINT, self._sigint_handler)
            self.run_until_stopped()
        finally:
            try:
                if restore_sigint_handler:
                    signal.signal(signal.SIGINT, previous_sigint_handler)
            finally:
                try:
                    if self._pending_interrupt and sys.exception() is None:
                        try:
                            raise KeyboardInterrupt
                        finally:
                            self._finalize_run()
                    else:
                        self._finalize_run()
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
            self._topology_reserved_thread = thread
        try:
            thread.start()
        except BaseException:
            with self._drive_owner_lock:
                if self._drive_thread is thread:
                    self._drive_thread = None
                    self._drive_thread_starting = False
                    self._thread = None
                    self._topology_reserved_thread = None
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
        """Use the copied scheduler's sole broker and strategy cleanup owner."""
        self._cleanup_owned_resources()

    @final
    def request_stop(self) -> None:
        """Signal the reactor without joining or closing owned resources."""

        with self._stop_once_lock:
            self._stop_requested = True
            self._stop_event.set()
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
            if self._resources_closed or self._resources_closing:
                return
            self._resources_closing = True

        with self._topology_lock:
            self._topology_stopping = True
            while self._topology_mutations:
                request = self._topology_mutations.popleft()
                request.error = RuntimeError("watcher topology is stopping")
                request.done.set()
            self._topology_pending.clear()
        try:
            self._close_reactor_resources()
            with self._stop_once_lock:
                self._resources_closed = True
        finally:
            with self._stop_once_lock:
                self._resources_closing = False


TautBaseWatcher = BaseReactor
"""Compatibility alias for extensions released before ``BaseReactor``."""


class TautWatcher(BaseReactor):
    """Cursor-aware taut live follower."""

    _dynamic_topology = True

    def __init__(
        self,
        runtime: TautWatchRuntime,
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
            raise TypeError(
                "TautWatcher requires a TautWatchRuntime; use client.watch(...)"
            )
        self._runtime = runtime
        self.member_id = member_id
        self._user_handler = handler
        self._cursors: dict[str, int] = {}
        self._failures: dict[tuple[str, int], int] = {}
        self._ready_event: threading.Event | None = None
        self._ready_after_initial_drain = False
        self._thread_filter = set(threads) if threads else None
        self._notification_queue_name = addressing.notification_queue_name(member_id)
        self._runtime_cleanup_done = False
        try:
            # Establish the hint cursor before the initial authoritative snapshot.
            with Queue(
                CACHE_STALE_QUEUE_NAME,
                db_path=self._runtime.target,
                persistent=False,
                config=resolve_runtime_config(self._runtime.config),
            ) as cache_queue:
                self._cursors[CACHE_STALE_QUEUE_NAME] = (
                    cache_queue.latest_pending_timestamp() or 0
                )
            memberships = self._current_memberships(strict=strict_membership)
            self._chat_queue_names = {row.name for row in memberships}
            queue_configs = {
                CACHE_STALE_QUEUE_NAME: {
                    "handler": lambda *_args: None,
                    "mode": QueueMode.PEEK,
                },
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
                default_error_handler_fn=_taut_default_error_handler,
                config=self._runtime.config,
            )
        except BaseException as exc:
            cleanup_exc = capture_cleanup_failure(None, self._runtime.close)
            if cleanup_exc is not None:
                exc.add_note(
                    f"watcher runtime construction cleanup failed: {cleanup_exc}"
                )
            else:
                self._runtime_cleanup_done = True
            raise

    def list_queues(self) -> list[str]:
        return [
            name for name in super().list_queues() if name in self._chat_queue_names
        ]

    def notify_ready_after_initial_drain(self, event: threading.Event) -> None:
        """Signal ``event`` once the watcher has started and completed one drain."""

        self._ready_event = event
        if self._ready_after_initial_drain:
            event.set()

    def _close_reactor_resources(self) -> None:
        failure: Exception | None = None
        failure = capture_cleanup_failure(failure, super()._close_reactor_resources)
        if not self._runtime_cleanup_done:
            runtime_failure = capture_cleanup_failure(None, self._runtime.close)
            if runtime_failure is None:
                self._runtime_cleanup_done = True
            elif failure is None:
                failure = runtime_failure
        if failure is not None:
            raise failure

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
            except (StopWatching, WatcherRejected):
                # Terminal sink failure is not poison content. Its error handler
                # stops the reactor without advancing this durable chat cursor.
                raise
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
        if config.name == CACHE_STALE_QUEUE_NAME:
            # Cache work runs before dispatch, where topology mutation is legal.
            return None
        if (
            config.name not in self._chat_queue_names
            or config.mode is not QueueMode.PEEK
        ):
            result = super()._fetch_next_message(config)
            if result is not None and config.name == self._notification_queue_name:
                from taut._cache_stale import publish_cache_stale

                publish_cache_stale(
                    lambda: self._queue(CACHE_STALE_QUEUE_NAME),
                    reason="notification-claim",
                )
            return result
        return super()._fetch_next_message(config)

    def _drain_queue(self) -> None:
        cache_queue = self._queue(CACHE_STALE_QUEUE_NAME)
        timestamp = cache_queue.latest_pending_timestamp() or 0
        if timestamp > self._cursors[CACHE_STALE_QUEUE_NAME]:
            try:
                self._refresh_memberships()
            except _TopologyStopping:
                # Stop can win admission or publication after the membership read.
                # Only that typed rejection ends reconciliation; other errors escape.
                return
            self._cursors[CACHE_STALE_QUEUE_NAME] = timestamp
        super()._drain_queue()
        if not self._ready_after_initial_drain:
            self._ready_after_initial_drain = True
            if self._ready_event is not None:
                self._ready_event.set()

    def _refresh_memberships(self) -> None:
        rows = self._current_memberships(strict=False)
        current = {row.name for row in rows}
        configured = set(self._chat_queue_names)
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
                self._chat_queue_names.add(thread)
        for thread in sorted(configured - current):
            self._remove_thread_queue(thread)
            self._cursors.pop(thread, None)
            self._clear_failures_for_thread(thread)

    def _remove_thread_queue(self, thread: str) -> None:
        self.remove_queue(thread)
        self._chat_queue_names.discard(thread)

    def _clear_failures_for_thread(self, thread: str) -> None:
        stale_keys = [key for key in self._failures if key[0] == thread]
        for key in stale_keys:
            self._failures.pop(key, None)
