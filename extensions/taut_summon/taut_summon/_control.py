"""The control plane ([SUM-9]) and the rate backstop ([SUM-10]).

Congruent with Weft's task control-queue contract (``command``/``request_id``
JSON subset; verbs STOP / STATUS / PING). Two roles live here:

- **Driver side** (:class:`ControlLoop`): a dedicated consumer thread that
  claim-consumes ``sys.ctl_<member-id>`` with the public ``simplebroker``
  ``read_one`` (at-most-once — a command lost to a driver crash is moot:
  STOP on a dead driver is meaningless, and STATUS/PING requesters retry on
  timeout), dispatches the verbs, and replies on the requester's
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
from simplebroker.ext import BrokerError, OperationalError

from taut import TautClient, TautError
from taut.envelope import decode_envelope
from taut_summon._adapter import AdapterError, AdapterHandle
from taut_summon._broker_retry import broker_retry, is_transient_broker_error
from taut_summon._state import SummonStateError, get_session

logger = logging.getLogger("taut_summon.control")

# Verbs mirrored from weft's task control contract ([SUM-9]).
CONTROL_STOP = "STOP"
CONTROL_STATUS = "STATUS"
CONTROL_PING = "PING"
_KNOWN_COMMANDS = frozenset({CONTROL_STOP, CONTROL_STATUS, CONTROL_PING})

_DEFAULT_RATE_LIMIT = 60
_RATE_WINDOW_SECONDS = 60.0
_STOP_ACK_TIMEOUT_SECONDS = 60.0
_CONTROL_DRAIN_RETRY_ATTEMPTS = 90
_CONTROL_REPLY_RETRY_ATTEMPTS = 120
_CONTROL_REQUEST_RETRY_INTERVAL_SECONDS = 5.0
_IDEMPOTENT_RETRY_COMMANDS = frozenset({CONTROL_STATUS, CONTROL_PING})
_RATE_AUDIT_RECOVERABLE_FAILURES_BEFORE_DEGRADED = 3
_CONTROL_DRAIN_RECOVERABLE_FAILURES_BEFORE_DEGRADED = 3
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


def _is_recoverable_control_broker_error(exc: Exception) -> bool:
    if is_transient_broker_error(exc):
        return True
    message = str(exc).lower()
    return isinstance(exc, OperationalError) and "disk i/o error" in message


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
        self._own_posts: deque[float] = deque()
        self._nudged = False
        self._hard_breached = False
        self._hard_breach_count = 0
        self._control_drain_recoverable_failures = 0
        self._rate_audit_recoverable_failures = 0
        # All db handles are opened ON THIS THREAD in _open and reused for
        # the loop's life — no per-tick Queue/connection churn (which, under
        # WAL, provokes transient malformed-page reads across the process).
        self._client: TautClient | None = None
        self._ctl_in: Queue | None = None
        self._ctl_out: Queue | None = None
        self._ledger: Queue | None = None
        self._thread_queues: dict[str, Queue] = {}

    def run(self) -> None:
        try:
            self._open()
            while not self._shutdown.is_set():
                self._tick()
                if self._pending_stop_seen:
                    break
                self._shutdown.wait(timeout=self._interval)
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
                if completed and self._release_confirmed():
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
                                else "driver slot release could not be confirmed"
                            ),
                        ),
                        reply_to=self._pending_stop_reply_to,
                    )
        except Exception:  # pragma: no cover - defensive: never kill the driver
            logger.exception("control loop crashed")
        finally:
            self._close()

    def _tick(self) -> None:
        # One cadence step: drain commands, then run the audit. A transient
        # WAL blip is already ridden out inside broker_retry; anything that
        # reaches here is a *non-transient* error that survived the bounded
        # retry budget — genuine corruption or a persistent operational
        # fault. It must NOT be swallowed as debug (that would leave control
        # silently dead while the driver runs): surface it loudly and mark
        # control unhealthy so STATUS reports the degradation. The loop
        # keeps running so that health stays reportable ([SUM-9]).
        try:
            self._drain_commands()
        except BrokerError as exc:
            self._mark_control_drain_failure(exc)
            return
        else:
            self._control_drain_recoverable_failures = 0
        if self._pending_stop_seen:
            return
        try:
            self._audit_pass()
        except BrokerError as exc:
            self._mark_rate_audit_failure(exc)
        else:
            self._rate_audit_recoverable_failures = 0

    def _mark_unhealthy(self, where: str, exc: Exception) -> None:
        detail = f"{where}: {type(exc).__name__}: {exc}"
        self._unhealthy = detail
        logger.error(
            "control plane degraded — %s survived the retry budget; "
            "STATUS will report 'degraded'",
            detail,
        )

    def _mark_control_drain_failure(self, exc: BrokerError) -> None:
        if not _is_recoverable_control_broker_error(exc):
            self._mark_unhealthy("control drain", exc)
            return

        self._control_drain_recoverable_failures += 1
        reopened = self._reopen_broker_handles("control drain", exc)
        if (
            self._control_drain_recoverable_failures
            >= _CONTROL_DRAIN_RECOVERABLE_FAILURES_BEFORE_DEGRADED
        ):
            self._mark_unhealthy(
                "control drain "
                f"({self._control_drain_recoverable_failures} consecutive "
                "recoverable broker failures)",
                exc,
            )
            return

        logger.warning(
            "control drain skipped after recoverable broker error "
            "(%d/%d, reopened=%s); STATUS/PING clients will retry: %s",
            self._control_drain_recoverable_failures,
            _CONTROL_DRAIN_RECOVERABLE_FAILURES_BEFORE_DEGRADED,
            reopened,
            exc,
        )

    def _mark_rate_audit_failure(self, exc: BrokerError) -> None:
        if not _is_recoverable_control_broker_error(exc):
            self._mark_unhealthy("rate audit", exc)
            return

        self._rate_audit_recoverable_failures += 1
        self._reopen_broker_handles("rate audit", exc)
        if (
            self._rate_audit_recoverable_failures
            >= _RATE_AUDIT_RECOVERABLE_FAILURES_BEFORE_DEGRADED
        ):
            self._mark_unhealthy(
                "rate audit "
                f"({self._rate_audit_recoverable_failures} consecutive "
                "recoverable broker failures)",
                exc,
            )
            return

        logger.warning(
            "rate audit skipped after recoverable broker errors survived the retry "
            "budget (%d/%d); STATUS remains healthy unless this repeats: %s",
            self._rate_audit_recoverable_failures,
            _RATE_AUDIT_RECOVERABLE_FAILURES_BEFORE_DEGRADED,
            exc,
        )

    # --- setup / teardown -------------------------------------------------

    def _open(self) -> None:
        self._install_broker_handles(self._make_broker_handles())
        self._init_audit_cursor()

    def _close(self) -> None:
        self._close_handles()

    def _reopen_broker_handles(self, where: str, exc: BrokerError) -> bool:
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
        old_ctl_in = self._ctl_in
        old_ctl_out = self._ctl_out
        old_ledger = self._ledger
        old_thread_queues = dict(self._thread_queues)
        self._install_broker_handles(handles)
        self._close_queue_handles(
            ctl_in=old_ctl_in,
            ctl_out=old_ctl_out,
            ledger=old_ledger,
            thread_queues=old_thread_queues,
        )
        return True

    def _make_broker_handles(self) -> _BrokerHandles:
        client = TautClient(db_path=self._db_path, token=self._token)
        return _BrokerHandles(
            client=client,
            ctl_in=client.queue(control_in_queue_name(self._member_id)),
            ctl_out=client.queue(control_out_queue_name(self._member_id)),
            ledger=client.queue(self._ledger_queue_name),
            thread_queues={thread: client.queue(thread) for thread in self._threads},
        )

    def _install_broker_handles(self, handles: _BrokerHandles) -> None:
        self._client = handles.client
        self._ctl_in = handles.ctl_in
        self._ctl_out = handles.ctl_out
        self._ledger = handles.ledger
        self._thread_queues = handles.thread_queues

    def _close_handles(self) -> None:
        self._close_queue_handles(
            ctl_in=self._ctl_in,
            ctl_out=self._ctl_out,
            ledger=self._ledger,
            thread_queues=self._thread_queues,
        )
        self._client = None
        self._ctl_in = None
        self._ctl_out = None
        self._ledger = None
        self._thread_queues = {}

    def _close_queue_handles(
        self,
        *,
        ctl_in: Queue | None,
        ctl_out: Queue | None,
        ledger: Queue | None,
        thread_queues: dict[str, Queue],
    ) -> None:
        # Do not hard-delete sys.* queues during shutdown. Commands and replies
        # that completed were already claim-consumed via read_one(); leftovers
        # are invisible to core, and delete-all maintenance under high process
        # churn is a worse failure mode than an inert stale control row.
        queues: list[Queue | None] = [ctl_in, ctl_out, ledger]
        queues.extend(thread_queues.values())
        for queue in queues:
            if queue is not None:
                try:
                    queue.close()
                except Exception:  # pragma: no cover - defensive
                    logger.debug("control queue close failed", exc_info=True)

    # --- command dispatch -------------------------------------------------

    def _drain_commands(self) -> None:
        ctl_in = self._ctl_in
        assert ctl_in is not None
        while not self._shutdown.is_set():
            body = broker_retry(
                ctl_in.read_one,
                what="control read",
                attempts=_CONTROL_DRAIN_RETRY_ATTEMPTS,
            )
            if body is None:
                return
            self._dispatch(body if isinstance(body, str) else str(body))
            if self._pending_stop_seen:
                return

    def _dispatch(self, body: str) -> None:
        request = parse_control_request(body)
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
            self._pending_stop_seen = True
            self._request_stop()
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
        try:
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
        except Exception as exc:  # pragma: no cover - defensive snapshot boundary
            logger.debug("status snapshot failed: %s", exc)
            return {"driver": "alive", "error": "status unavailable"}

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
        ledger = self._ledger
        if ledger is None:  # pragma: no cover - open() always runs first
            return None
        try:
            row = get_session(ledger, self._member_id)
        except SummonStateError:  # pragma: no cover - defensive
            return None
        return row["provider_session_id"] if row is not None else None

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
            queue = client.queue(reply_to)
            try:
                broker_retry(
                    lambda: queue.write(body),
                    what="control reply",
                    attempts=_CONTROL_REPLY_RETRY_ATTEMPTS,
                )
            except Exception as exc:  # noqa: BLE001 - a lost reply must not crash
                logger.warning("per-request control reply failed: %s", exc)
            finally:
                queue.close()
            return
        ctl_out = self._ctl_out
        if ctl_out is None:  # pragma: no cover - open() always runs first
            return
        try:
            broker_retry(
                lambda: ctl_out.write(body),
                what="control reply",
                attempts=_CONTROL_REPLY_RETRY_ATTEMPTS,
            )
        except Exception as exc:  # noqa: BLE001 - a lost reply must not crash
            logger.warning("control reply write failed after retries: %s", exc)

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
            rows = queue.peek_many(with_timestamps=True)
        except BrokerError:
            return 0
        stamped = cast("list[tuple[str, int]]", rows)
        return max((ts for _body, ts in stamped), default=0)

    def _audit_pass(self) -> None:
        now = time.monotonic()
        for thread, queue in self._thread_queues.items():
            self._audit_thread(thread, queue, now)
        self._prune(now)
        self._enforce()

    def _audit_thread(self, thread: str, queue: Queue, now: float) -> None:
        cursor = self._audit_cursor.get(thread, 0)
        highest = cursor
        # A direct log-semantics peek after the driver-local audit cursor —
        # never touching the member cursor ([SUM-10]/[TAUT-7.4]).
        for row in queue.peek_generator(with_timestamps=True, after_timestamp=cursor):
            body, ts = cast("tuple[str, int]", row)
            highest = max(highest, ts)
            if decode_envelope(body).from_id == self._member_id:
                self._own_posts.append(now)
        self._audit_cursor[thread] = highest

    def _prune(self, now: float) -> None:
        cutoff = now - _RATE_WINDOW_SECONDS
        while self._own_posts and self._own_posts[0] < cutoff:
            self._own_posts.popleft()

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
        driver_pid: int | None = None,
        driver_start_time: str | None = None,
    ) -> None:
        self._queue_factory = queue_factory
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
        reply_queue = self._queue_factory(reply_to)
        body_out = encode_control_command(
            command,
            request_id,
            reply_to=reply_to,
            driver_pid=self._driver_pid,
            driver_start_time=self._driver_start_time,
        )
        try:
            broker_retry(lambda: self._ctl_in.write(body_out), what="control request")
            deadline = time.monotonic() + timeout
            next_retry = time.monotonic() + _CONTROL_REQUEST_RETRY_INTERVAL_SECONDS
            while time.monotonic() < deadline:
                try:
                    body = broker_retry(reply_queue.read_one, what="control reply read")
                except Exception as exc:
                    if not is_transient_broker_error(exc):
                        raise
                    time.sleep(0.03)
                    continue
                if body is None:
                    now = time.monotonic()
                    if retry_on_timeout and now >= next_retry:
                        broker_retry(
                            lambda: self._ctl_in.write(body_out),
                            what="control request retry",
                        )
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
        try:
            self._ctl_in.close()
        except Exception:  # pragma: no cover - defensive
            logger.debug("control client queue close failed", exc_info=True)
