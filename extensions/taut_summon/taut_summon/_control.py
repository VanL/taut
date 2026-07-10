"""The control plane ([SUM-9]) and the rate backstop ([SUM-10]).

Congruent with Weft's task control-queue contract (``command``/``request_id``
JSON subset; verbs STOP / STATUS / PING). Two roles live here:

- **Driver side** (:class:`ControlLoop`): a reactor-owned consumer lane that
  reads ``sys.ctl_<member-id>`` with the public ``simplebroker`` queue surface,
  dispatches the verbs, and replies on the requester's
  **per-request** queue ``sys.rsp_<member-id>_<request_id>`` (see below).
  ``TautClient.watch`` is chat-only and knows nothing about ``sys.*``
  ([SUM-9]). The same thread runs the [SUM-10] rate backstop audit on its
  cadence, because the watch stream never delivers the member's own sends
  ([TAUT-7.4]).
- **Client side** (:class:`ControlClient`): what ``taut-summon stop`` and
  ``taut-summon status`` use to write a request and await its reply. Each
  request carries a ``reply_to`` naming a per-request queue
  ``sys.rsp_<member-id>_<request_id>``, so any number of concurrent clients
  from different terminals get their own answers and never consume each
  other's. Requester-less rate-backstop breaches surface through logs and
  later STATUS snapshots, not as unsolicited control replies.

Control queues are deliberately **unregistered** plain broker queues
([IAN-6.1] as amended by D3): invisible to every core command, the same
treatment as foreign queues; only summon reads or writes them.

Spec references:
- docs/specs/04-summon.md [SUM-9], [SUM-10], [SUM-11]
- ../weft/weft/core/tasks/base.py (the mirrored command/request_id shapes)
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import threading
import time
from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, cast

from simplebroker import Queue
from simplebroker.ext import BrokerError, StopWatching

from taut import TautClient, TautError
from taut.envelope import decode_envelope
from taut.watcher import (
    BaseReactor,
    QueueMessageContext,
    QueueMode,
)
from taut_summon._adapter import AdapterError, AdapterHandle

logger = logging.getLogger("taut_summon.control")

# Verbs mirrored from weft's task control contract ([SUM-9]).
CONTROL_STOP = "STOP"
CONTROL_STATUS = "STATUS"
CONTROL_PING = "PING"
_KNOWN_COMMANDS = frozenset({CONTROL_STOP, CONTROL_STATUS, CONTROL_PING})

_DEFAULT_RATE_LIMIT = 60
_RATE_WINDOW_SECONDS = 60.0
_STOP_ACK_TIMEOUT_SECONDS = 60.0
_CONTROL_REQUEST_RETRY_INTERVAL_SECONDS = 5.0
_IDEMPOTENT_RETRY_COMMANDS = frozenset({CONTROL_STATUS, CONTROL_PING})
_RATE_AUDIT_RECOVERABLE_FAILURES_BEFORE_DEGRADED = 3
_CONTROL_DRAIN_RECOVERABLE_FAILURES_BEFORE_DEGRADED = 3
_CONTROL_REPLY_RECOVERABLE_FAILURES_BEFORE_DEGRADED = 3
_STATUS_RESERVED_KEYS = frozenset(
    {
        "command",
        "status",
        "request_id",
        "driver",
        "rate_limited",
        "rate_breaches",
        "provider",
        "session_id",
        "thread_count",
        "cursor_lag",
        "control_health",
        "health_detail",
    }
)
_CONTROL_FAULT_PLANE_ATTR = "_taut_summon_control_fault_plane"


def _tag_control_fault(exc: Exception, plane: str) -> Exception:
    try:
        setattr(exc, _CONTROL_FAULT_PLANE_ATTR, plane)
    except Exception:  # pragma: no cover - unusual immutable exception object
        logger.debug("could not tag control fault plane", exc_info=True)
    return exc


def _is_broker_surface_failure(exc: Exception) -> bool:
    return isinstance(exc, (BrokerError, OSError))


# --- queue derivation (beside taut.addressing's shapes) -----------------------


def control_in_queue_name(member_id: str) -> str:
    """The driver's inbound control queue: ``sys.ctl_<member-id>`` ([SUM-9])."""

    return f"sys.ctl_{member_id}"


def control_out_queue_name(member_id: str) -> str:
    """The driver's outbound reply queue: ``sys.rsp_<member-id>`` ([SUM-9])."""

    return f"sys.rsp_{member_id}"


# --- request/reply shapes -----------------------------------------------------


@dataclass(frozen=True, slots=True)
class ControlRequest:
    """One parsed control command: verb + optional request id + reply route."""

    command: str
    request_id: str | None
    reply_to: str | None
    driver_pid: int | None
    driver_start_time: str | None
    raw: str


def _opt_str(payload: dict[str, Any], key: str) -> str | None:
    value = payload.get(key)
    return value if isinstance(value, str) and value else None


def parse_control_request(body: str) -> ControlRequest:
    """Parse one JSON control body ([SUM-9]); tolerate malformed input.

    Summon requires a JSON object keyed ``command`` (case-insensitive) and
    optional string ``request_id`` / ``reply_to``. A malformed or non-JSON
    body yields an empty command so the caller can report and drop it — the
    loop never crashes on garbage ([IAN-9]-style robustness). ``reply_to``
    is the per-request reply queue: each client awaits its answer on its own
    queue, so concurrent ``stop``/``status`` clients never consume each
    other's replies.
    """

    raw = body.strip()
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return ControlRequest(
            command="",
            request_id=None,
            reply_to=None,
            driver_pid=None,
            driver_start_time=None,
            raw=raw,
        )
    if not isinstance(payload, dict):
        return ControlRequest(
            command="",
            request_id=None,
            reply_to=None,
            driver_pid=None,
            driver_start_time=None,
            raw=raw,
        )
    command_value = payload.get("command")
    command = command_value.strip().upper() if isinstance(command_value, str) else ""
    driver_pid_value = payload.get("driver_pid")
    driver_pid = (
        driver_pid_value
        if isinstance(driver_pid_value, int) and not isinstance(driver_pid_value, bool)
        else None
    )
    return ControlRequest(
        command=command,
        request_id=_opt_str(payload, "request_id"),
        reply_to=_opt_str(payload, "reply_to"),
        driver_pid=driver_pid,
        driver_start_time=_opt_str(payload, "driver_start_time"),
        raw=raw,
    )


def encode_control_command(
    command: str,
    request_id: str,
    *,
    reply_to: str | None = None,
    driver_pid: int | None = None,
    driver_start_time: str | None = None,
) -> str:
    """Serialize one request body ([SUM-9] client side)."""

    payload: dict[str, Any] = {"command": command, "request_id": request_id}
    if reply_to is not None:
        payload["reply_to"] = reply_to
    if driver_pid is not None:
        payload["driver_pid"] = driver_pid
    if driver_start_time is not None:
        payload["driver_start_time"] = driver_start_time
    return json.dumps(payload, separators=(",", ":"))


def encode_control_reply(
    command: str, status: str, *, request_id: str | None, **extra: Any
) -> str:
    """Serialize one reply body: ``command``/``status``/``request_id`` + extras."""

    payload: dict[str, Any] = {"command": command, "status": status}
    payload.update(extra)
    if request_id is not None:
        payload["request_id"] = request_id
    return json.dumps(payload, separators=(",", ":"))


# --- driver-side control loop -------------------------------------------------


@dataclass(frozen=True, slots=True)
class StatusSnapshot:
    """The [SUM-9] STATUS payload the driver reports for its member."""

    provider: str
    session_id: str | None
    thread_count: int
    cursor_lag: dict[str, int]
    control_health: str
    health_detail: str | None
    rate_limited: bool
    rate_breaches: int

    def as_fields(self) -> dict[str, Any]:
        fields: dict[str, Any] = {
            "driver": "alive",
            "rate_limited": self.rate_limited,
            "rate_breaches": self.rate_breaches,
            "provider": self.provider,
            "session_id": self.session_id,
            "thread_count": self.thread_count,
            "cursor_lag": self.cursor_lag,
            "control_health": self.control_health,
        }
        if self.health_detail is not None:
            fields["health_detail"] = self.health_detail
        return fields


@dataclass(frozen=True)
class _BrokerHandles:
    client: TautClient
    ctl_in: Queue
    ctl_out: Queue
    ledger: Queue
    thread_queues: dict[str, Queue]
    control_reactor: _ControlReactor | None = None


@dataclass(frozen=True, slots=True)
class _PendingControlFault:
    """A control-owner fault that may only be resolved between turns."""

    where: str
    primary: Exception
    recoverable: bool


class _ControlReactor(BaseReactor):
    """BaseTask-shaped control reactor for one summon control queue."""

    def __init__(
        self,
        owner: ControlLoop,
        *,
        db: Any,
        config: dict[str, Any],
    ) -> None:
        self._owner = owner
        self._queue_name = control_in_queue_name(owner._member_id)
        super().__init__(
            {
                self._queue_name: {
                    "handler": self._handle_control_message,
                    "mode": QueueMode.READ,
                    "error_handler": self._handle_control_error,
                }
            },
            db=db,
            stop_event=threading.Event(),
            persistent=True,
            inactive_probe_interval=owner._interval,
            config=config,
        )
        self._queue(self._queue_name)

    def _handle_control_message(
        self, body: str, timestamp: int, context: QueueMessageContext
    ) -> None:
        self._owner._handle_control_message(body, timestamp, context)

    def _handle_control_error(
        self, exc: Exception, _message: str, _timestamp: int
    ) -> bool | None:
        return self._owner._handle_control_error(exc, _message, _timestamp)

    def _drain_queue(self) -> None:
        if self._owner._pending_stop_seen:
            return
        before_failures = self._owner._control_drain_recoverable_failures
        super()._drain_queue()
        if (
            self._owner._control_drain_recoverable_failures == before_failures
            and not self._owner._pending_stop_seen
        ):
            self._owner._control_drain_recoverable_failures = 0


class ControlLoop:
    """Driver-side control consumer + rate backstop, on one dedicated thread."""

    def __init__(
        self,
        *,
        member_id: str,
        db_path: str | None,
        token: str,
        provider: str,
        threads: Sequence[str],
        handle_provider: Callable[[], AdapterHandle | None],
        request_stop: Callable[[], None],
        shutdown: threading.Event,
        shutdown_complete: threading.Event,
        release_confirmed: Callable[[], bool],
        rate_limit: int | None,
        ledger_queue_name: str,
        driver_pid: int,
        driver_start_time: str,
        provider_session_id: str | None = None,
    ) -> None:
        self._member_id = member_id
        self._db_path = db_path
        self._token = token
        self._provider = provider
        self._threads = tuple(threads)
        self._handle_provider = handle_provider
        self._request_stop = request_stop
        self._shutdown = shutdown
        self._shutdown_complete = shutdown_complete
        self._release_confirmed = release_confirmed
        self._rate_limit = _DEFAULT_RATE_LIMIT if rate_limit is None else rate_limit
        self._ledger_queue_name = ledger_queue_name
        self._driver_pid = driver_pid
        self._driver_start_time = driver_start_time
        self._status_lock = threading.Lock()
        self._provider_session_id = provider_session_id
        # The control/audit cadence. Kept gentle by default so the audit's
        # peeks do not add db contention; tests that exercise stop/status
        # latency or the rate backstop lower it via the env var.
        self._interval = float(os.environ.get("TAUT_SUMMON_CONTROL_INTERVAL", "1.0"))
        self._pending_stop: str | None = None
        self._pending_stop_reply_to: str | None = None
        self._pending_stop_seen = False
        # Post-retry-budget failure detail; None while healthy ([SUM-9]).
        self._unhealthy: str | None = None
        # Rate backstop state (driver-local, in-memory). The breaker
        # re-arms: _hard_breached clears once the windowed own-post rate
        # falls back under the limit, so a resumed harness that floods
        # again is interrupted again ([SUM-10] circuit-breaker intent).
        self._audit_cursor: dict[str, int] = {}
        self._own_posts: deque[int] = deque()
        self._nudged = False
        self._hard_breached = False
        self._hard_breach_count = 0
        self._control_drain_recoverable_failures = 0
        self._control_reply_recoverable_failures = 0
        self._rate_audit_recoverable_failures = 0
        self._pending_control_fault: _PendingControlFault | None = None
        self._next_rate_audit_at = 0.0
        # All db handles are opened ON THIS THREAD in _open and reused for the
        # loop's life. Queue-operation retry belongs to SimpleBroker; this loop
        # owns only handle lifetime and live control state.
        self._client: TautClient | None = None
        self._control_reactor: _ControlReactor | None = None
        self._ctl_in: Queue | None = None
        self._ctl_out: Queue | None = None
        self._ledger: Queue | None = None
        self._thread_queues: dict[str, Queue] = {}

    def update_session_id(self, session_id: str | None) -> None:
        """Record live provider session identity for future STATUS replies."""

        with self._status_lock:
            self._provider_session_id = session_id

    def run(self) -> None:
        if self._db_path is None:
            logger.warning("control loop exiting gracefully: no database target")
            return
        try:
            self._open()
            while not self._shutdown.is_set() and not self._pending_stop_seen:
                if self._pending_control_fault is not None:
                    if self._recover_pending_control_fault():
                        # The local reactor snapshot, if any, is retired. Always
                        # reacquire the installed generation at loop head.
                        continue
                    delay = min(
                        5.0,
                        max(self._interval, 0.25)
                        * (
                            2
                            ** max(
                                0,
                                self._control_fault_failure_count() - 1,
                            )
                        ),
                    )
                    if self._shutdown.wait(delay):
                        break
                    continue

                reactor = self._control_reactor
                if reactor is None:
                    raise RuntimeError("control reactor disappeared while running")
                try:
                    reactor.process_once()
                except StopWatching:
                    if self._pending_control_fault is not None:
                        continue
                    if self._shutdown.is_set() or self._pending_stop_seen:
                        break
                    raise
                except (BrokerError, OSError) as exc:
                    self._mark_control_drain_failure(exc)
                    continue

                if self._pending_control_fault is not None:
                    continue
                self._control_drain_recoverable_failures = 0

                # Rate audit is control-owner policy. It runs only after the
                # reactor turn has fully unwound and before the wait deadline
                # is computed.
                self._audit_if_due()
                if self._pending_control_fault is not None:
                    continue

                try:
                    reactor.wait_for_activity(timeout=self._next_control_wait_timeout())
                except StopWatching:
                    if self._pending_control_fault is not None:
                        continue
                    if self._shutdown.is_set() or self._pending_stop_seen:
                        break
                    raise
                except (BrokerError, OSError) as exc:
                    self._record_control_fault("control wait", exc, recoverable=True)
                    continue
            if self._pending_stop_seen:
                # A control STOP: wait for the clean-shutdown path to
                # release the driver slot, then reply — so the stop client
                # sees the reply only after the ledger is clear ([SUM-9]).
                # The ack asserts release; if the shutdown timed out or the
                # release could not be confirmed (persistent broker
                # failure), reply an error so the client never treats an
                # unreleased slot as stopped.
                completed = self._shutdown_complete.wait(
                    timeout=_STOP_ACK_TIMEOUT_SECONDS
                )
                release_confirmed = False
                release_error: str | None = None
                if completed:
                    try:
                        release_confirmed = self._release_confirmed()
                    except Exception as exc:
                        release_error = (
                            f"driver slot release confirmation failed: {exc}"
                        )
                        logger.error("%s", release_error)
                if completed and release_confirmed:
                    self._reply(
                        encode_control_reply(
                            CONTROL_STOP, "ack", request_id=self._pending_stop
                        ),
                        reply_to=self._pending_stop_reply_to,
                    )
                else:
                    self._reply(
                        encode_control_reply(
                            CONTROL_STOP,
                            "error",
                            request_id=self._pending_stop,
                            error=(
                                "shutdown timed out"
                                if not completed
                                else (
                                    release_error
                                    or "driver slot release could not be confirmed"
                                )
                            ),
                        ),
                        reply_to=self._pending_stop_reply_to,
                    )
        finally:
            self._close()

    def _audit_if_due(self) -> None:
        if self._pending_stop_seen:
            return
        now = time.monotonic()
        if now < self._next_rate_audit_at:
            return
        self._next_rate_audit_at = now + max(self._interval, 0.01)
        try:
            self._audit_pass()
        except (BrokerError, OSError) as exc:
            self._mark_rate_audit_failure(exc)
        except Exception as exc:
            self._record_control_fault("rate audit", exc, recoverable=False)
            self._mark_unhealthy("rate audit", exc)
        else:
            self._rate_audit_recoverable_failures = 0

    def _next_control_wait_timeout(self) -> float:
        """Bound the inherited wait by both probe and audit deadlines."""

        now = time.monotonic()
        probe_bound = max(self._interval, 0.01)
        audit_remaining = max(0.0, self._next_rate_audit_at - now)
        if audit_remaining == 0.0:
            # ``run`` calls ``_audit_if_due`` first. This floor makes a
            # misconfigured zero interval fail safe without a hot loop.
            return min(probe_bound, 0.01)
        return min(probe_bound, audit_remaining)

    def _handle_control_message(
        self, body: str, timestamp: int, context: QueueMessageContext
    ) -> None:
        self._dispatch(body if isinstance(body, str) else str(body))
        if context.mode is QueueMode.PEEK:
            self._ack_control_message(context.queue, context.queue_name, timestamp)

    def _ack_control_message(
        self, queue: Queue, queue_name: str, timestamp: int
    ) -> None:
        try:
            queue.delete(message_id=timestamp)
        except (BrokerError, OSError, RuntimeError):
            logger.debug(
                "failed to acknowledge control message for %s",
                queue_name,
                exc_info=True,
            )

    def _handle_control_error(
        self, exc: Exception, _message: str, _timestamp: int
    ) -> bool | None:
        if _is_broker_surface_failure(exc):
            self._mark_control_drain_failure(exc)
            return True
        self._record_control_fault("control dispatch", exc, recoverable=False)
        self._mark_unhealthy("control dispatch", exc)
        logger.error(
            "control dispatch failed with non-broker exception",
            exc_info=(type(exc), exc, exc.__traceback__),
        )
        return False

    def _mark_unhealthy(self, where: str, exc: Exception) -> None:
        detail = f"{where}: {type(exc).__name__}: {exc}"
        self._unhealthy = detail
        logger.error(
            "control plane degraded — %s; STATUS will report 'degraded'",
            detail,
        )

    def _mark_control_drain_failure(self, exc: Exception) -> None:
        self._record_control_fault("control drain", exc, recoverable=True)

    def _mark_rate_audit_failure(self, exc: Exception) -> None:
        self._record_control_fault("rate audit", exc, recoverable=True)

    def _record_control_fault(
        self,
        where: str,
        exc: Exception,
        *,
        recoverable: bool,
    ) -> None:
        """Record a primary fault without replacing live handles in-stack."""

        if self._pending_control_fault is None:
            self._pending_control_fault = _PendingControlFault(
                where=where,
                primary=exc,
                recoverable=recoverable,
            )

    def _control_fault_failure_count(self) -> int:
        fault = self._pending_control_fault
        if fault is not None and fault.where == "rate audit":
            return self._rate_audit_recoverable_failures
        return self._control_drain_recoverable_failures

    def _recover_pending_control_fault(self) -> bool:
        """Resolve one pending fault at the between-turn supervisor seam.

        Returns ``True`` only after a complete replacement is installed. A
        failed replacement leaves the old complete bundle installed and the
        primary fault pending. Fatal faults and exhausted recovery propagate to
        the driver wrapper.
        """

        fault = self._pending_control_fault
        if fault is None:
            return False
        if not fault.recoverable:
            self._pending_control_fault = None
            raise fault.primary

        if fault.where == "rate audit":
            self._rate_audit_recoverable_failures += 1
            failures = self._rate_audit_recoverable_failures
            threshold = _RATE_AUDIT_RECOVERABLE_FAILURES_BEFORE_DEGRADED
        else:
            self._control_drain_recoverable_failures += 1
            failures = self._control_drain_recoverable_failures
            threshold = _CONTROL_DRAIN_RECOVERABLE_FAILURES_BEFORE_DEGRADED

        if self._reopen_broker_handles(fault.where, fault.primary):
            if fault.where == "rate audit":
                self._rate_audit_recoverable_failures = 0
            else:
                self._control_drain_recoverable_failures = 0
            if self._unhealthy is not None and self._unhealthy.startswith(
                f"{fault.where} reopen:"
            ):
                self._unhealthy = None
            self._pending_control_fault = None
            return True

        if failures >= threshold:
            self._mark_unhealthy(
                f"{fault.where} ({failures} consecutive broker failures)",
                fault.primary,
            )
            self._pending_control_fault = None
            raise RuntimeError(
                f"{fault.where} recovery exhausted after {failures} attempts"
            ) from fault.primary

        logger.warning(
            "%s recovery failed (%d/%d); no further control turn will run: %s",
            fault.where,
            failures,
            threshold,
            fault.primary,
        )
        return False

    def _mark_control_reply_failure(self, exc: Exception) -> None:
        self._control_reply_recoverable_failures += 1
        if (
            self._control_reply_recoverable_failures
            >= _CONTROL_REPLY_RECOVERABLE_FAILURES_BEFORE_DEGRADED
        ):
            self._mark_unhealthy(
                "control reply "
                f"({self._control_reply_recoverable_failures} consecutive "
                "broker failures)",
                exc,
            )
            return

        logger.warning(
            "control reply skipped after broker error "
            "(%d/%d); idempotent STATUS/PING clients will retry: %s",
            self._control_reply_recoverable_failures,
            _CONTROL_REPLY_RECOVERABLE_FAILURES_BEFORE_DEGRADED,
            exc,
        )

    # --- setup / teardown -------------------------------------------------

    def _open(self) -> None:
        logger.debug("control loop opening broker handles")
        self._install_broker_handles(self._make_broker_handles())
        logger.debug("control loop initializing audit cursor")
        self._init_audit_cursor()
        logger.debug("control loop open complete")

    def _close(self) -> None:
        self._close_handles()

    def _reopen_broker_handles(self, where: str, exc: Exception) -> bool:
        old_client = self._client
        old_reactor = self._control_reactor
        old_ctl_in = self._ctl_in
        old_ctl_out = self._ctl_out
        old_ledger = self._ledger
        old_thread_queues = dict(self._thread_queues)
        try:
            handles = self._make_broker_handles()
        except Exception as reopen_exc:  # noqa: BLE001 - STATUS should expose it
            logger.exception(
                "control broker handle reopen failed after %s error: %s",
                where,
                exc,
            )
            self._mark_unhealthy(f"{where} reopen", reopen_exc)
            return False
        self._install_broker_handles(handles)
        self._close_queue_handles(
            client=old_client,
            control_reactor=old_reactor,
            ctl_in=old_ctl_in,
            ctl_out=old_ctl_out,
            ledger=old_ledger,
            thread_queues=old_thread_queues,
        )
        return True

    def _make_broker_handles(self) -> _BrokerHandles:
        if self._db_path is None:
            raise RuntimeError("control loop requires a database target")
        client = TautClient(
            db_path=self._db_path,
            token=self._token,
            persistent=True,
        )
        reactor: _ControlReactor | None = None
        try:
            reactor = _ControlReactor(self, db=client.target, config=client.config)
            return _BrokerHandles(
                client=client,
                control_reactor=reactor,
                ctl_in=reactor._queue(control_in_queue_name(self._member_id)),
                ctl_out=reactor._queue(control_out_queue_name(self._member_id)),
                ledger=reactor._queue(self._ledger_queue_name),
                thread_queues={
                    thread: reactor._queue(thread) for thread in self._threads
                },
            )
        except Exception:
            if reactor is not None:
                try:
                    reactor.cleanup()
                except Exception:
                    logger.debug(
                        "partial control reactor cleanup failed", exc_info=True
                    )
            client.close()
            raise

    def _install_broker_handles(self, handles: _BrokerHandles) -> None:
        self._client = handles.client
        self._control_reactor = handles.control_reactor
        self._ctl_in = handles.ctl_in
        self._ctl_out = handles.ctl_out
        self._ledger = handles.ledger
        self._thread_queues = handles.thread_queues

    def _close_handles(self) -> None:
        self._close_queue_handles(
            client=self._client,
            control_reactor=self._control_reactor,
            ctl_in=self._ctl_in,
            ctl_out=self._ctl_out,
            ledger=self._ledger,
            thread_queues=self._thread_queues,
        )
        self._client = None
        self._control_reactor = None
        self._ctl_in = None
        self._ctl_out = None
        self._ledger = None
        self._thread_queues = {}

    def _close_queue_handles(
        self,
        *,
        client: object | None,
        control_reactor: _ControlReactor | None = None,
        ctl_in: Queue | None,
        ctl_out: Queue | None,
        ledger: Queue | None,
        thread_queues: dict[str, Queue],
    ) -> None:
        # Do not hard-delete sys.* queues during shutdown. Commands and replies
        # that completed were already claim-consumed via read_one(); leftovers
        # are invisible to core, and delete-all maintenance under high process
        # churn is a worse failure mode than an inert stale control row.
        if control_reactor is not None:
            try:
                control_reactor.cleanup()
            except Exception:  # pragma: no cover - defensive
                logger.debug("control reactor cleanup failed", exc_info=True)

        close_client = getattr(client, "close", None)
        if callable(close_client):
            try:
                close_client()
                return
            except Exception:  # pragma: no cover - defensive
                logger.debug("control client close failed", exc_info=True)

        queues: list[Queue | None] = [ctl_in, ctl_out, ledger]
        queues.extend(thread_queues.values())
        for queue in queues:
            if queue is not None:
                try:
                    queue.close()
                except Exception:  # pragma: no cover - defensive
                    logger.debug("control queue close failed", exc_info=True)

    def _dispatch(self, body: str) -> None:
        request = parse_control_request(body)
        logger.debug("control loop dispatching %s", request.command or "<invalid>")
        if request.command in _KNOWN_COMMANDS and not self._matches_driver(request):
            logger.info(
                "dropping stale control command %s for driver evidence %r/%r",
                request.command,
                request.driver_pid,
                request.driver_start_time,
            )
            return
        if request.command == CONTROL_PING:
            self._reply(
                encode_control_reply(
                    CONTROL_PING,
                    "ok",
                    request_id=request.request_id,
                    message="PONG",
                ),
                reply_to=request.reply_to,
            )
        elif request.command == CONTROL_STATUS:
            self._reply(
                encode_control_reply(
                    CONTROL_STATUS,
                    "ok",
                    request_id=request.request_id,
                    **self._status_fields(),
                ),
                reply_to=request.reply_to,
            )
        elif request.command == CONTROL_STOP:
            self._pending_stop = request.request_id
            self._pending_stop_reply_to = request.reply_to
            self._request_stop()
            self._pending_stop_seen = True
        else:
            # Unknown or malformed verb: report, never crash ([IAN-9]).
            logger.warning("dropping unknown control body: %r", request.raw[:200])
            self._reply(
                encode_control_reply(
                    request.command or "UNKNOWN",
                    "error",
                    request_id=request.request_id,
                    error=f"unknown command: {request.command or request.raw[:80]!r}",
                ),
                reply_to=request.reply_to,
            )

    def _matches_driver(self, request: ControlRequest) -> bool:
        return (
            request.driver_pid == self._driver_pid
            and request.driver_start_time == self._driver_start_time
        )

    def _status_fields(self) -> dict[str, Any]:
        fields = self._status_snapshot().as_fields()
        handle = self._handle_provider()
        if handle is None:
            return fields
        adapter_fields = handle.status_fields()
        collisions = _STATUS_RESERVED_KEYS.intersection(adapter_fields)
        if collisions:
            raise AdapterError(
                "adapter status field collides with reserved STATUS key: "
                + ", ".join(sorted(collisions))
            )
        fields.update(adapter_fields)
        return fields

    def _status_snapshot(self) -> StatusSnapshot:
        return StatusSnapshot(
            provider=self._provider,
            session_id=self._session_id(),
            thread_count=len(self._threads),
            cursor_lag=self._cursor_lag(),
            control_health="ok" if self._unhealthy is None else "degraded",
            health_detail=self._unhealthy,
            rate_limited=self._hard_breached,
            rate_breaches=self._hard_breach_count,
        )

    def _session_id(self) -> str | None:
        with self._status_lock:
            return self._provider_session_id

    def _cursor_lag(self) -> dict[str, int]:
        client = self._client
        if client is None:  # pragma: no cover - open() always runs first
            return {}
        wanted = set(self._threads)
        lag: dict[str, int] = {}
        try:
            for thread in client.list_threads(all_threads=True):
                if thread.name in wanted:
                    lag[thread.name] = thread.unread_count
        except (TautError, BrokerError) as exc:
            # cursor_lag is a best-effort STATUS *summary*: degrade it to
            # empty rather than failing the whole STATUS. list_threads
            # resolves identity, so under concurrency it can hit a transient
            # broker error or a claim-hash race with the watcher — STATUS
            # must still report provider/session/thread_count.
            logger.debug("cursor-lag read failed: %s", exc)
        return lag

    def _reply(self, body: str, *, reply_to: str | None = None) -> None:
        # A request carrying reply_to gets its answer on its own per-request
        # queue (concurrent clients never cross replies); requests without
        # one, and the requester-less RATE report, fall back to the shared
        # sys.rsp_<member> queue.
        client = self._client
        if reply_to is not None and client is not None:
            queue: Queue | None = None
            try:
                queue = client.queue(reply_to, persistent=False)
                queue.write(body)
                logger.debug("per-request control reply wrote to %s", reply_to)
                self._control_reply_recoverable_failures = 0
            except (BrokerError, OSError) as exc:
                logger.warning("per-request control reply failed: %s", exc)
                self._mark_control_reply_failure(exc)
            except Exception as exc:
                self._mark_unhealthy("control reply", exc)
                raise
            finally:
                if queue is not None:
                    try:
                        queue.close()
                    except Exception:  # pragma: no cover - defensive
                        logger.debug("per-request reply close failed", exc_info=True)
            return
        ctl_out = self._ctl_out
        if ctl_out is None:  # pragma: no cover - open() always runs first
            return
        try:
            ctl_out.write(body)
            logger.debug("shared control reply wrote to %s", ctl_out.name)
            self._control_reply_recoverable_failures = 0
        except (BrokerError, OSError) as exc:
            logger.warning("control reply write failed: %s", exc)
            self._mark_control_reply_failure(exc)
        except Exception as exc:
            self._mark_unhealthy("control reply", exc)
            raise

    # --- rate backstop ([SUM-10]) -----------------------------------------
    #
    # Audit coverage is the summon's startup threads only. A per-tick
    # membership refresh was tried and reverted: resolving current
    # memberships (`client.list_threads()`) re-records the member's
    # continuity-token identity claim, which races the driver's watcher on
    # the same claim_hash (UNIQUE) and destabilizes both. Closing the
    # late-joined-thread gap correctly needs either idempotent claim
    # recording in core (frozen here) or an in-memory membership channel
    # from the watcher; deferred as an accepted limitation. The breaker
    # re-arm below (pure in-memory) is the load-bearing [SUM-10] fix.

    def _init_audit_cursor(self) -> None:
        # Start each audit cursor at the thread's current head so only posts
        # made *after* the summon are counted ([SUM-10]).
        for thread, queue in self._thread_queues.items():
            self._audit_cursor[thread] = self._latest_ts(queue)

    def _latest_ts(self, queue: Queue) -> int:
        try:
            rows = self._audit_peek_many(queue, cursor=0, what="rate audit init")
        except (BrokerError, OSError):
            return 0
        stamped = cast("list[tuple[str, int]]", rows)
        return max((ts for _body, ts in stamped), default=0)

    def _audit_pass(self) -> None:
        ledger = self._ledger
        if ledger is None:  # pragma: no cover - audit runs only after _open
            raise RuntimeError("rate audit ledger is not open")
        now_ts = ledger.generate_timestamp()
        cutoff = now_ts - int(_RATE_WINDOW_SECONDS * 1_000_000_000)
        for thread, queue in self._thread_queues.items():
            self._audit_thread(thread, queue, cutoff)
        self._prune(cutoff)
        self._enforce()

    def _audit_thread(self, thread: str, queue: Queue, cutoff: int) -> None:
        cursor = self._audit_cursor.get(thread, 0)
        highest = cursor
        # A direct log-semantics peek after the driver-local audit cursor —
        # never touching the member cursor ([SUM-10]/[TAUT-7.4]).
        rows = self._audit_peek_many(
            queue, cursor=cursor, what=f"rate audit peek {thread}"
        )
        for row in rows:
            body, ts = cast("tuple[str, int]", row)
            highest = max(highest, ts)
            if ts >= cutoff and decode_envelope(body).from_id == self._member_id:
                self._own_posts.append(ts)
        self._audit_cursor[thread] = highest

    def _audit_peek_many(
        self, queue: Queue, *, cursor: int, what: str
    ) -> list[str] | list[tuple[str, int]]:
        del what
        return queue.peek_many(with_timestamps=True, after_timestamp=cursor)

    def _prune(self, cutoff: int) -> None:
        # Per-thread audit cursors are ordered within each thread, but the
        # shared deque is appended in thread-iteration order. It is therefore
        # not globally timestamp-sorted. Filter the complete window instead of
        # stopping at the first retained timestamp.
        retained = tuple(
            timestamp for timestamp in self._own_posts if timestamp >= cutoff
        )
        self._own_posts.clear()
        self._own_posts.extend(retained)

    def _enforce(self) -> None:
        count = len(self._own_posts)
        limit = self._rate_limit
        if count <= limit:
            # Rate is back under control: re-arm the breaker so a resumed
            # harness that floods again is nudged and hard-breached again
            # ([SUM-10] circuit-breaker intent — not one-shot).
            self._nudged = False
            self._hard_breached = False
            return
        if count > 2 * limit and not self._hard_breached:
            self._hard_breach(count, limit)
            return
        if not self._nudged:
            self._soft_breach(count, limit)

    def _soft_breach(self, count: int, limit: int) -> None:
        self._nudged = True
        logger.warning(
            "rate backstop: %d posts in the last %ds (limit %d); nudging",
            count,
            int(_RATE_WINDOW_SECONDS),
            limit,
        )
        handle = self._handle_provider()
        if handle is None:
            return
        nudge = (
            f"[system] you have posted {count} messages recently "
            f"(soft limit {limit}); slow down and post only when it adds value."
        )
        try:
            handle.inject(nudge)
        except AdapterError as exc:
            logger.debug("rate nudge inject failed: %s", exc)

    def _hard_breach(self, count: int, limit: int) -> None:
        self._hard_breached = True
        self._hard_breach_count += 1
        # Surfaced via STATUS (rate_limited / rate_breaches) and the log —
        # NOT written to ctrl_out. A requester-less ctrl_out message has no
        # consumer, so it would sit unclaimed forever (auto-vacuum reclaims
        # only claimed rows); STATUS is the pull channel a monitor uses.
        logger.error(
            "rate backstop HARD breach #%d: %d posts in the last %ds "
            "(limit %d); interrupting the harness",
            self._hard_breach_count,
            count,
            int(_RATE_WINDOW_SECONDS),
            limit,
        )
        handle = self._handle_provider()
        if handle is not None:
            try:
                handle.interrupt()
            except AdapterError as exc:  # pragma: no cover - defensive
                logger.debug("rate hard-breach interrupt failed: %s", exc)


# --- client side (stop / status) ----------------------------------------------


class ControlClient:
    """Write a control request and await its correlated reply ([SUM-9])."""

    def __init__(
        self,
        queue_factory: Callable[[str], Queue],
        member_id: str,
        *,
        reply_queue_factory: Callable[[str], Queue] | None = None,
        owns_request_queue: bool = True,
        driver_pid: int | None = None,
        driver_start_time: str | None = None,
    ) -> None:
        self._reply_queue_factory = reply_queue_factory or queue_factory
        self._owns_request_queue = owns_request_queue
        self._member_id = member_id
        self._driver_pid = driver_pid
        self._driver_start_time = driver_start_time
        self._ctl_in = queue_factory(control_in_queue_name(member_id))

    def request(self, command: str, *, timeout: float) -> dict[str, Any] | None:
        """Write ``command`` and return its reply, or ``None`` on timeout.

        Each request routes its reply to a **per-request** queue
        (``sys.rsp_<member>_<request_id>``), so any number of concurrent
        ``stop``/``status`` clients get their own answers and never consume
        each other's ([SUM-9] "usable from any terminal").
        """

        command = command.strip().upper()
        retry_on_timeout = command in _IDEMPOTENT_RETRY_COMMANDS
        request_id = secrets.token_hex(8)
        reply_to = f"{control_out_queue_name(self._member_id)}_{request_id}"
        reply_queue = self._reply_queue_factory(reply_to)
        body_out = encode_control_command(
            command,
            request_id,
            reply_to=reply_to,
            driver_pid=self._driver_pid,
            driver_start_time=self._driver_start_time,
        )
        try:
            try:
                self._ctl_in.write(body_out)
            except Exception as exc:
                raise _tag_control_fault(exc, "control_write") from exc
            deadline = time.monotonic() + timeout
            next_retry = time.monotonic() + _CONTROL_REQUEST_RETRY_INTERVAL_SECONDS
            while time.monotonic() < deadline:
                try:
                    body = reply_queue.read_one()
                except Exception as exc:
                    raise _tag_control_fault(exc, "control_read") from exc
                if body is None:
                    now = time.monotonic()
                    if retry_on_timeout and now >= next_retry:
                        try:
                            self._ctl_in.write(body_out)
                        except Exception as exc:
                            raise _tag_control_fault(exc, "control_write") from exc
                        next_retry = now + _CONTROL_REQUEST_RETRY_INTERVAL_SECONDS
                    time.sleep(0.03)
                    continue
                try:
                    payload = json.loads(body if isinstance(body, str) else str(body))
                except (json.JSONDecodeError, ValueError):
                    continue
                if isinstance(payload, dict):
                    return payload
            return None
        finally:
            # Successful replies have already been claim-consumed by read_one().
            # Timeout leftovers use a random per-request sys.* queue name and
            # are inert; avoid delete-all maintenance in the hot control path.
            try:
                reply_queue.close()
            except Exception:  # pragma: no cover - defensive
                logger.debug("reply queue close failed", exc_info=True)

    def close(self) -> None:
        if not self._owns_request_queue:
            return
        try:
            self._ctl_in.close()
        except Exception:  # pragma: no cover - defensive
            logger.debug("control client queue close failed", exc_info=True)
