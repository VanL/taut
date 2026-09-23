"""The control plane ([SUM-9]) and the rate backstop ([SUM-10]).

Congruent with Weft's task control-queue contract (``command``/``request_id``
JSON subset; verbs STOP / STATUS / PING). Two roles live here:

- **Driver side** (:class:`ControlPolicy`): a reactor-owned consumer lane that
  reads ``sys.ctl_<member-id>`` with the public ``simplebroker`` queue surface,
  dispatches the verbs, and replies on the requester's
  **per-request** queue ``sys.rsp_<member-id>_<request_id>`` (see below).
  ``TautClient.watch`` is chat-only and knows nothing about ``sys.*``
  ([SUM-9]). The owner runs the [SUM-10] rate audit when its reactor deadline is due, because the watch stream is not a complete source for the member's
  own sends ([TAUT-7.4]).
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
import time
from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from simplebroker import Queue
from simplebroker.ext import BrokerError

from taut import TautClient, TautError
from taut.envelope import decode_envelope
from taut.watcher import (
    BaseReactor,
    QueueMessageContext,
    QueueMode,
    TautWatcher,
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
_CONTROL_REQUEST_RETRY_INTERVAL_SECONDS = 5.0
_IDEMPOTENT_RETRY_COMMANDS = frozenset({CONTROL_STATUS, CONTROL_PING})
_STATUS_RESERVED_KEYS = frozenset(
    {
        "command",
        "status",
        "request_id",
        "driver",
        "rate_limited",
        "rate_breaches",
        "provider",
        "thread_count",
        "cursor_lag",
    }
)
_CONTROL_FAULT_PLANE_ATTR = "_taut_summon_control_fault_plane"


def _tag_control_fault(exc: Exception, plane: str) -> None:
    setattr(exc, _CONTROL_FAULT_PLANE_ATTR, plane)


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


# --- driver-side control policy -------------------------------------------------


@dataclass(frozen=True, slots=True)
class StatusSnapshot:
    """The [SUM-9] STATUS payload the driver reports for its member."""

    provider: str
    thread_count: int
    cursor_lag: dict[str, int]
    rate_limited: bool
    rate_breaches: int

    def as_fields(self) -> dict[str, Any]:
        fields: dict[str, Any] = {
            "driver": "alive",
            "rate_limited": self.rate_limited,
            "rate_breaches": self.rate_breaches,
            "provider": self.provider,
            "thread_count": self.thread_count,
            "cursor_lag": self.cursor_lag,
        }
        return fields


@dataclass(frozen=True, slots=True)
class StopShutdownOutcome:
    """Final foreground teardown and release facts observed by STOP."""

    release_confirmed: bool
    teardown_error: str | None = None
    release_error: str | None = None

    def error_detail(self) -> str | None:
        if self.teardown_error is not None:
            detail = f"driver teardown failed: {self.teardown_error}"
            if self.release_error is not None:
                detail += f"; driver slot release also failed: {self.release_error}"
            elif not self.release_confirmed:
                detail += "; driver slot release also could not be confirmed"
            return detail
        if self.release_error is not None:
            return f"driver slot release failed: {self.release_error}"
        if not self.release_confirmed:
            return "driver slot release could not be confirmed"
        return None


class ControlPolicy:
    """Control and rate policy invoked by the single Summon reactor owner."""

    def __init__(
        self,
        *,
        client: TautClient,
        reactor: TautWatcher,
        member_id: str,
        provider: str,
        threads: Sequence[str],
        handle_provider: Callable[[], AdapterHandle | None],
        request_stop: Callable[[], None],
        send_nudge: Callable[[str], None],
        interrupt: Callable[[], None],
        rate_limit: int | None,
        ledger_queue_name: str,
        driver_pid: int,
        driver_start_time: str,
        audit_start_ts: int = 0,
    ) -> None:
        self._client = client
        self._reactor = reactor
        self._member_id = member_id
        self._provider = provider
        self._threads = tuple(threads)
        self._handle_provider = handle_provider
        self._request_stop = request_stop
        self._send_nudge = send_nudge
        self._interrupt = interrupt
        self._rate_limit = _DEFAULT_RATE_LIMIT if rate_limit is None else rate_limit
        self._driver_pid = driver_pid
        self._driver_start_time = driver_start_time
        self._audit_start_ts = audit_start_ts
        self._ledger = reactor._queue(ledger_queue_name)
        self._interval = max(
            0.01, float(os.environ.get("TAUT_SUMMON_CONTROL_INTERVAL", "1"))
        )
        self._next_rate_audit_at = time.monotonic() + self._interval
        self._pending_stop: str | None = None
        self._pending_stop_reply_to: str | None = None
        self._pending_stop_seen = False
        self._audit_cursor: dict[str, int] = {}
        self._own_posts: deque[int] = deque()
        self._own_posts_seen: set[int] = set()
        self._nudged = False
        self._hard_breached = False
        self._hard_breach_count = 0
        self._thread_queues: dict[str, Queue] = {}

    def install(self) -> None:
        self._reactor.add_queue(
            control_in_queue_name(self._member_id),
            self._handle_control_message,
            mode=QueueMode.READ,
            error_handler=self._handle_control_error,
        )

    def _handle_control_message(
        self, body: str, timestamp: int, context: QueueMessageContext
    ) -> None:
        del timestamp, context
        self._dispatch(body)

    def _handle_control_error(
        self, exc: Exception, _message: str, _timestamp: int
    ) -> bool | None:
        raise exc

    def turn(self) -> None:
        now = time.monotonic()
        if self._pending_stop_seen or now < self._next_rate_audit_at:
            return
        self._next_rate_audit_at = now + self._interval
        self._audit_pass()

    def _reply(self, body: str, *, reply_to: str | None = None) -> None:
        queue: Queue | None = None
        try:
            queue = self._client.queue(
                reply_to or control_out_queue_name(self._member_id), persistent=False
            )
            queue.write(body)
        except (BrokerError, OSError) as error:
            logger.warning(
                "control reply skipped after broker error; "
                "idempotent STATUS/PING clients may retry: %s",
                error,
            )
        finally:
            if queue is not None:
                queue.close()

    def finish_stop(self, outcome: StopShutdownOutcome) -> None:
        if not self._pending_stop_seen:
            return
        error = outcome.error_detail()
        fields: dict[str, Any] = {} if error is None else {"error": error}
        self._reply(
            encode_control_reply(
                CONTROL_STOP,
                "ack" if error is None else "error",
                request_id=self._pending_stop,
                **fields,
            ),
            reply_to=self._pending_stop_reply_to,
        )

    def _reconcile_audit_threads(self) -> None:
        current = self._reactor._chat_queue_names
        self._thread_queues = {
            name: managed
            for name in sorted(current)
            if (managed := self._reactor.get_queue(name)) is not None
        }
        self._threads = tuple(self._thread_queues)

    def _soft_breach(self, count: int, limit: int) -> None:
        self._nudged = True
        logger.warning("rate backstop: %d posts (limit %d); nudging", count, limit)
        self._send_nudge(
            f"[system] you have posted {count} messages recently "
            f"(soft limit {limit}); slow down and post only when it adds value."
        )

    def _hard_breach(self, count: int, limit: int) -> None:
        self._hard_breached = True
        self._hard_breach_count += 1
        logger.error(
            "rate backstop HARD breach #%d: %d > %d",
            self._hard_breach_count,
            count,
            limit,
        )
        self._interrupt()

    def _dispatch(self, body: str) -> None:
        request = parse_control_request(body)
        logger.debug("control policy dispatching %s", request.command or "<invalid>")
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
            thread_count=len(self._threads),
            cursor_lag=self._cursor_lag(),
            rate_limited=self._hard_breached,
            rate_breaches=self._hard_breach_count,
        )

    def _cursor_lag(self) -> dict[str, int]:
        client = self._client
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

    def _audit_pass(self) -> None:
        ledger = self._ledger
        now_ts = ledger.generate_timestamp()
        cutoff = now_ts - int(_RATE_WINDOW_SECONDS * 1_000_000_000)
        self._reconcile_audit_threads()
        for thread, queue in self._thread_queues.items():
            self._audit_thread(thread, queue, cutoff)
        self._prune(cutoff)
        self._enforce()

    def _audit_thread(self, thread: str, queue: Queue, cutoff: int) -> None:
        cursor = max(
            0,
            self._audit_start_ts,
            cutoff - 1,
            self._audit_cursor.get(thread, 0),
        )
        highest = cursor
        # A direct log-semantics peek after the driver-local audit cursor —
        # never touching the member cursor ([SUM-10]/[TAUT-7.4]).
        rows = queue.peek_many(with_timestamps=True, after_timestamp=cursor)
        for row in rows:
            body, ts = row
            highest = max(highest, ts)
            if (
                ts >= cutoff
                and decode_envelope(body).from_id == self._member_id
                and ts not in self._own_posts_seen
            ):
                self._own_posts.append(ts)
                self._own_posts_seen.add(ts)
        self._audit_cursor[thread] = highest

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
        self._own_posts_seen = set(retained)

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


# --- client side (stop / status) ----------------------------------------------


class _ReplyReactor(BaseReactor):
    """One request, one reply source, and owned timeout/retry deadlines."""

    def __init__(
        self,
        reply_queue: Queue,
        request_queue: Queue,
        body: str,
        *,
        timeout: float,
        retry: bool,
    ) -> None:
        self._reply_queue = reply_queue
        self._request_queue = request_queue
        self._request_body = body
        self._deadline = time.monotonic() + timeout
        self._retry = retry
        self._next_retry = time.monotonic() + _CONTROL_REQUEST_RETRY_INTERVAL_SECONDS
        self.result: dict[str, Any] | None = None
        super().__init__(
            {
                reply_queue.name: {
                    "handler": self._receive,
                    "mode": QueueMode.READ,
                    "error_handler": self._fail,
                }
            },
            db=reply_queue.db_target,
            persistent=True,
        )

    def _receive(self, body: str, timestamp: int, context: QueueMessageContext) -> None:
        del timestamp, context
        try:
            payload = json.loads(body)
        except (json.JSONDecodeError, ValueError):
            return
        if isinstance(payload, dict):
            self.result = payload
            self.request_stop()

    @staticmethod
    def _fail(error: Exception, _body: str, _timestamp: int) -> bool | None:
        raise error

    def _fetch_next_message(self, config: Any) -> tuple[str, int] | None:
        del config
        try:
            body = self._reply_queue.read_one()
        except Exception as exc:
            _tag_control_fault(exc, "control_read")
            raise
        return (str(body), 0) if body is not None else None

    def _process_reactor_turn(self) -> None:
        now = time.monotonic()
        if now >= self._deadline:
            self.request_stop()
            return
        if self._retry and now >= self._next_retry:
            try:
                self._request_queue.write(self._request_body)
            except Exception as exc:
                _tag_control_fault(exc, "control_write")
                raise
            self._next_retry = now + _CONTROL_REQUEST_RETRY_INTERVAL_SECONDS
        super()._process_reactor_turn()

    def next_wait_timeout(self) -> float | None:
        deadline = (
            min(self._deadline, self._next_retry) if self._retry else self._deadline
        )
        return max(0.0, deadline - time.monotonic())


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
        reactor: _ReplyReactor | None = None
        try:
            try:
                self._ctl_in.write(body_out)
            except Exception as exc:
                _tag_control_fault(exc, "control_write")
                raise
            reactor = _ReplyReactor(
                reply_queue,
                self._ctl_in,
                body_out,
                timeout=timeout,
                retry=retry_on_timeout,
            )
            reactor.run()
            return reactor.result
        finally:
            try:
                if reactor is not None:
                    reactor.stop(join=False)
            finally:
                # Claims consume replies; timeout leftovers remain inert.
                reply_queue.close()

    def close(self) -> None:
        if not self._owns_request_queue:
            return
        try:
            self._ctl_in.close()
        except Exception:  # pragma: no cover - defensive
            logger.debug("control client queue close failed", exc_info=True)
