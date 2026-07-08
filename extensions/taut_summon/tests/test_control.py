"""Unit tests for the control-plane shapes ([SUM-9]).

Contract under test: docs/specs/04-summon.md [SUM-9] — the ``sys.ctl_`` /
``sys.rsp_`` queue derivation from the member id, the single-line JSON
bodies keyed ``command``/``request_id``, and replies correlating by
``request_id`` with a ``status`` field. The mirrored weft subset is
copied by shape (../weft/weft/core/tasks/base.py), never by code.

The driver-side loop and client round-trips against a *live* driver are
exercised end-to-end in ``test_driver.py`` with the real scripted provider.
"""

from __future__ import annotations

import json
import os
import threading
from typing import Any, cast

import pytest
import taut_summon._control as control_module
from simplebroker import Queue
from simplebroker.ext import (
    DatabaseError,
    IntegrityError,
    OperationalError,
)
from taut_summon._broker_retry import (
    _BROKER_RETRIES,
    broker_retry,
    is_transient_broker_error,
)
from taut_summon._control import (
    _CONTROL_DRAIN_RECOVERABLE_FAILURES_BEFORE_DEGRADED,
    _CONTROL_DRAIN_RETRY_ATTEMPTS,
    _CONTROL_REPLY_RECOVERABLE_FAILURES_BEFORE_DEGRADED,
    _CONTROL_REPLY_RETRY_ATTEMPTS,
    _RATE_AUDIT_RECOVERABLE_FAILURES_BEFORE_DEGRADED,
    ControlClient,
    ControlLoop,
    _BrokerHandles,
    control_in_queue_name,
    control_out_queue_name,
    encode_control_command,
    encode_control_reply,
    parse_control_request,
)
from taut_summon._retry import remove_backoff


class _FakeControlQueue:
    def __init__(self, name: str, harness: _FakeControlQueues) -> None:
        self.name = name
        self._harness = harness

    def write(self, body: str) -> None:
        self._harness.writes.append((self.name, json.loads(body)))

    def read_one(self) -> str | None:
        return self._harness.read_reply(self.name)

    def delete(self) -> None:
        self._harness.deleted.append(self.name)

    def close(self) -> None:
        self._harness.closed.append(self.name)


class _FakeControlQueues:
    def __init__(self, *, reply_after_writes: int | None) -> None:
        self.reply_after_writes = reply_after_writes
        self.writes: list[tuple[str, dict[str, object]]] = []
        self.deleted: list[str] = []
        self.closed: list[str] = []

    def queue(self, name: str) -> _FakeControlQueue:
        return _FakeControlQueue(name, self)

    def read_reply(self, name: str) -> str | None:
        ctl_writes = [
            payload
            for queue_name, payload in self.writes
            if queue_name.startswith("sys.ctl_")
        ]
        if self.reply_after_writes is None:
            return None
        if len(ctl_writes) < self.reply_after_writes:
            return None
        latest = ctl_writes[-1]
        reply_to = latest.get("reply_to")
        if reply_to != name:
            return None
        return encode_control_reply(
            str(latest["command"]), "ok", request_id=str(latest["request_id"])
        )


class _CloseableQueue:
    def __init__(self) -> None:
        self.closed = False
        self.deleted = False

    def close(self) -> None:
        self.closed = True

    def delete(self) -> None:
        self.deleted = True


class _FailingReplyQueue:
    def __init__(self, exc: Exception) -> None:
        self.exc = exc
        self.closed = False
        self.writes = 0

    def write(self, _body: str) -> None:
        self.writes += 1
        raise self.exc

    def close(self) -> None:
        self.closed = True


class _ReplyClient:
    def __init__(self, queue: _FailingReplyQueue) -> None:
        self.queue_obj = queue
        self.names: list[str] = []

    def queue(self, name: str) -> _FailingReplyQueue:
        self.names.append(name)
        return self.queue_obj


def _fake_broker_handles() -> _BrokerHandles:
    return _BrokerHandles(
        client=cast(Any, object()),
        ctl_in=cast(Queue, _CloseableQueue()),
        ctl_out=cast(Queue, _CloseableQueue()),
        ledger=cast(Queue, _CloseableQueue()),
        thread_queues={"general": cast(Queue, _CloseableQueue())},
    )


def _make_loop(rate_limit: int) -> ControlLoop:
    # A control loop with no db handles (never .run()/._open()'d): enough to
    # exercise the pure in-memory rate-backstop and health logic. The audit
    # and reply paths tolerate the None handles defensively.
    return ControlLoop(
        member_id="m_" + "a" * 26,
        db_path=None,
        token="taut-tok",
        provider="scripted",
        threads=("general",),
        handle_provider=lambda: None,
        request_stop=lambda: None,
        shutdown=threading.Event(),
        shutdown_complete=threading.Event(),
        release_confirmed=lambda: True,
        rate_limit=rate_limit,
        ledger_queue_name="taut_meta",
        driver_pid=123,
        driver_start_time="driver-start",
    )


def _reopen_ok(_where: str, _exc: Exception) -> bool:
    return True


def test_transient_predicate_retries_wal_blips_not_logic_faults() -> None:
    assert is_transient_broker_error(OperationalError("database is locked"))
    assert is_transient_broker_error(OperationalError("disk I/O error"))
    assert is_transient_broker_error(DatabaseError("database disk image is malformed"))
    assert is_transient_broker_error(
        RuntimeError(
            "Failed to get database connection: database disk image is malformed"
        )
    )
    assert is_transient_broker_error(
        RuntimeError("Failed to get database connection: database is locked")
    )
    assert is_transient_broker_error(
        RuntimeError("Failed to get database connection: disk I/O error")
    )
    assert is_transient_broker_error(
        RuntimeError(
            "Failed to get database connection: Database magic string mismatch. "
            "Expected 'simplebroker-v1', found 'm_example'."
        )
    )
    # Genuine faults must surface immediately, and retryable=False is honored.
    assert not is_transient_broker_error(IntegrityError("UNIQUE constraint failed"))
    stop = OperationalError("interrupted")
    stop.retryable = False
    assert not is_transient_broker_error(stop)


def test_transient_predicate_is_narrow_not_whole_class() -> None:
    # The predicate matches only known SQLite transients by message text —
    # a generic operational failure or a non-malformed database error must
    # NOT be retried (that would mask genuine corruption / real faults).
    assert not is_transient_broker_error(OperationalError("no such column: x"))
    assert not is_transient_broker_error(DatabaseError("disk I/O error"))
    assert not is_transient_broker_error(RuntimeError("database is locked"))
    # An explicit retryable=True wins regardless of class/message.
    forced = DatabaseError("anything")
    forced.retryable = True  # type: ignore[attr-defined]
    assert is_transient_broker_error(forced)


def test_broker_retry_clears_a_transient_then_returns() -> None:
    calls: list[int] = []

    def flaky() -> str:
        calls.append(1)
        if len(calls) < 3:
            if len(calls) == 1:
                raise DatabaseError("database disk image is malformed")
            raise OperationalError("disk I/O error")
        return "ok"

    assert broker_retry(flaky, what="test") == "ok"
    assert len(calls) == 3


def test_broker_retry_reraises_persistent_failure_after_budget() -> None:
    calls: list[int] = []

    def always_malformed() -> str:
        calls.append(1)
        raise DatabaseError("database disk image is malformed")

    with remove_backoff(), pytest.raises(DatabaseError):
        broker_retry(always_malformed, what="test")
    assert len(calls) >= 2  # bounded budget spent, then re-raised


def test_broker_retry_does_not_retry_logic_faults() -> None:
    calls: list[int] = []

    def integrity_fault() -> str:
        calls.append(1)
        raise IntegrityError("UNIQUE constraint failed")

    with pytest.raises(IntegrityError):
        broker_retry(integrity_fault, what="test")
    assert len(calls) == 1  # surfaced on the first try, no retries


def test_control_drain_outlasts_normal_read_retry_budget() -> None:
    class FlakyReadQueue:
        def __init__(self, failures: int) -> None:
            self.failures = failures
            self.calls = 0

        def read_one(self) -> str | None:
            self.calls += 1
            if self.calls <= self.failures:
                raise DatabaseError("database disk image is malformed")
            return None

    queue = FlakyReadQueue(failures=_BROKER_RETRIES + 2)
    loop = _make_loop(rate_limit=60)
    loop._ctl_in = cast(Queue, queue)

    with remove_backoff():
        loop._drain_commands()

    assert queue.calls == _BROKER_RETRIES + 3
    assert _CONTROL_DRAIN_RETRY_ATTEMPTS > _BROKER_RETRIES
    assert _CONTROL_REPLY_RETRY_ATTEMPTS > _CONTROL_DRAIN_RETRY_ATTEMPTS


def test_control_client_retries_status_with_same_reply_route(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(control_module, "_CONTROL_REQUEST_RETRY_INTERVAL_SECONDS", 0.01)
    queues = _FakeControlQueues(reply_after_writes=2)
    client = ControlClient(
        cast(Any, queues.queue),
        "m_abc",
        driver_pid=123,
        driver_start_time="driver-start",
    )

    reply = client.request("STATUS", timeout=1.0)

    assert reply is not None
    assert reply["status"] == "ok"
    ctl_payloads = [
        payload
        for queue_name, payload in queues.writes
        if queue_name == "sys.ctl_m_abc"
    ]
    assert len(ctl_payloads) == 2
    assert ctl_payloads[0]["request_id"] == ctl_payloads[1]["request_id"]
    assert ctl_payloads[0]["reply_to"] == ctl_payloads[1]["reply_to"]
    assert ctl_payloads[0]["driver_pid"] == 123
    assert ctl_payloads[0]["driver_start_time"] == "driver-start"
    assert queues.deleted == []
    assert ctl_payloads[0]["reply_to"] in queues.closed


def test_summon_tests_pin_sqlite_process_env() -> None:
    assert os.environ["BROKER_AUTO_VACUUM"] == "0"
    assert os.environ["BROKER_SYNC_MODE"] == "FULL"


def test_control_client_does_not_retry_stop_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(control_module, "_CONTROL_REQUEST_RETRY_INTERVAL_SECONDS", 0.01)
    queues = _FakeControlQueues(reply_after_writes=None)
    client = ControlClient(
        cast(Any, queues.queue),
        "m_abc",
        driver_pid=123,
        driver_start_time="driver-start",
    )

    assert client.request("STOP", timeout=0.08) is None

    ctl_payloads = [
        payload
        for queue_name, payload in queues.writes
        if queue_name == "sys.ctl_m_abc"
    ]
    assert len(ctl_payloads) == 1
    assert ctl_payloads[0]["command"] == "STOP"
    assert queues.deleted == []
    assert ctl_payloads[0]["reply_to"] in queues.closed


def test_rate_breaker_rearms_after_flood_subsides() -> None:
    # [SUM-10] circuit-breaker: hard breach is not one-shot. Once the rate
    # falls back under the limit the breaker re-arms and can trip again.
    loop = _make_loop(rate_limit=2)
    loop._own_posts.extend([0.0] * 6)  # 6 > 2*limit -> hard breach
    loop._enforce()
    assert loop._hard_breached is True

    loop._own_posts.clear()  # flood subsided (rate back under limit)
    loop._enforce()
    assert loop._hard_breached is False  # re-armed
    assert loop._nudged is False

    loop._own_posts.extend([0.0] * 6)  # floods again
    loop._enforce()
    assert loop._hard_breached is True  # trips a second time


def test_status_reports_degraded_after_post_budget_failure() -> None:
    # A non-transient broker error that survives the retry budget marks the
    # control plane unhealthy, and STATUS surfaces it ([SUM-9]) instead of
    # the failure being swallowed.
    loop = _make_loop(rate_limit=60)
    healthy = loop._status_snapshot().as_fields()
    assert healthy["control_health"] == "ok"
    assert "health_detail" not in healthy

    loop._mark_unhealthy("control drain", DatabaseError("disk I/O error"))
    degraded = loop._status_snapshot().as_fields()
    assert degraded["control_health"] == "degraded"
    assert "disk I/O error" in degraded["health_detail"]


def test_single_transient_rate_audit_failure_does_not_degrade_status() -> None:
    # The rate audit is a safety backstop, not the STOP/STATUS control drain.
    # One exhausted transient SQLite read pass under process churn should skip
    # that audit and retry on the next cadence rather than permanently poison
    # control health.
    loop = _make_loop(rate_limit=60)
    loop._reopen_broker_handles = _reopen_ok  # type: ignore[assignment,method-assign]

    loop._mark_rate_audit_failure(DatabaseError("database disk image is malformed"))

    healthy = loop._status_snapshot().as_fields()
    assert healthy["control_health"] == "ok"
    assert "health_detail" not in healthy


def test_repeated_transient_rate_audit_failures_degrade_status() -> None:
    loop = _make_loop(rate_limit=60)
    loop._reopen_broker_handles = _reopen_ok  # type: ignore[assignment,method-assign]

    for _ in range(_RATE_AUDIT_RECOVERABLE_FAILURES_BEFORE_DEGRADED):
        loop._mark_rate_audit_failure(DatabaseError("database disk image is malformed"))

    degraded = loop._status_snapshot().as_fields()
    assert degraded["control_health"] == "degraded"
    assert "consecutive recoverable broker failures" in degraded["health_detail"]


def test_non_transient_rate_audit_failure_degrades_status_immediately() -> None:
    loop = _make_loop(rate_limit=60)

    loop._mark_rate_audit_failure(DatabaseError("disk I/O error"))

    degraded = loop._status_snapshot().as_fields()
    assert degraded["control_health"] == "degraded"
    assert "disk I/O error" in degraded["health_detail"]


def test_single_recoverable_control_drain_failure_reopens_without_degrading() -> None:
    loop = _make_loop(rate_limit=60)
    reopened: list[tuple[str, str]] = []

    def reopen(where: str, exc: Exception) -> bool:
        reopened.append((where, str(exc)))
        return True

    loop._reopen_broker_handles = reopen  # type: ignore[method-assign]

    loop._mark_control_drain_failure(OperationalError("disk I/O error"))

    healthy = loop._status_snapshot().as_fields()
    assert healthy["control_health"] == "ok"
    assert reopened == [("control drain", "disk I/O error")]


def test_repeated_recoverable_control_drain_failures_degrade_status() -> None:
    loop = _make_loop(rate_limit=60)

    loop._reopen_broker_handles = _reopen_ok  # type: ignore[assignment,method-assign]

    for _ in range(_CONTROL_DRAIN_RECOVERABLE_FAILURES_BEFORE_DEGRADED):
        loop._mark_control_drain_failure(OperationalError("disk I/O error"))

    degraded = loop._status_snapshot().as_fields()
    assert degraded["control_health"] == "degraded"
    assert "consecutive recoverable broker failures" in degraded["health_detail"]


def test_single_recoverable_control_reply_failure_reopens_without_degrading(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(control_module, "_CONTROL_REPLY_RETRY_ATTEMPTS", 1)
    loop = _make_loop(rate_limit=60)
    reply_queue = _FailingReplyQueue(DatabaseError("database disk image is malformed"))
    loop._client = cast(Any, _ReplyClient(reply_queue))
    reopened: list[tuple[str, str]] = []

    def reopen(where: str, exc: Exception) -> bool:
        reopened.append((where, str(exc)))
        return True

    loop._reopen_broker_handles = reopen  # type: ignore[method-assign]

    loop._reply(
        encode_control_reply("PING", "ok", request_id="req"),
        reply_to="sys.rsp_m_abc_req",
    )
    loop._client = None

    assert reopened == [("control reply", "database disk image is malformed")]
    assert reply_queue.closed is True
    assert loop._status_snapshot().as_fields()["control_health"] == "ok"


def test_repeated_recoverable_control_reply_failures_degrade_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(control_module, "_CONTROL_REPLY_RETRY_ATTEMPTS", 1)
    loop = _make_loop(rate_limit=60)
    loop._reopen_broker_handles = _reopen_ok  # type: ignore[assignment,method-assign]

    for _ in range(_CONTROL_REPLY_RECOVERABLE_FAILURES_BEFORE_DEGRADED):
        reply_queue = _FailingReplyQueue(
            DatabaseError("database disk image is malformed")
        )
        loop._client = cast(Any, _ReplyClient(reply_queue))
        loop._reply(
            encode_control_reply("PING", "ok", request_id="req"),
            reply_to="sys.rsp_m_abc_req",
        )

    loop._client = None
    degraded = loop._status_snapshot().as_fields()
    assert degraded["control_health"] == "degraded"
    assert "consecutive recoverable broker failures" in degraded["health_detail"]


def test_wrapped_control_reply_connection_failure_reopens_without_degrading() -> None:
    loop = _make_loop(rate_limit=60)
    reopened: list[tuple[str, str]] = []

    def reopen(where: str, exc: Exception) -> bool:
        reopened.append((where, str(exc)))
        return True

    loop._reopen_broker_handles = reopen  # type: ignore[method-assign]

    loop._mark_control_reply_failure(
        RuntimeError(
            "Failed to get database connection: Database magic string mismatch. "
            "Expected 'simplebroker-v1', found 'm_example'."
        )
    )

    assert reopened == [
        (
            "control reply",
            "Failed to get database connection: Database magic string mismatch. "
            "Expected 'simplebroker-v1', found 'm_example'.",
        )
    ]
    assert loop._status_snapshot().as_fields()["control_health"] == "ok"


def test_failed_reopen_preserves_existing_control_handles() -> None:
    loop = _make_loop(rate_limit=60)
    old_handles = _fake_broker_handles()
    old_ctl_in = cast(_CloseableQueue, old_handles.ctl_in)
    loop._install_broker_handles(old_handles)

    def fail_make() -> _BrokerHandles:
        raise RuntimeError("schema unavailable")

    loop._make_broker_handles = fail_make  # type: ignore[method-assign]

    assert (
        loop._reopen_broker_handles("control drain", OperationalError("disk I/O error"))
        is False
    )

    assert loop._ctl_in is old_handles.ctl_in
    assert loop._ctl_out is old_handles.ctl_out
    assert loop._ledger is old_handles.ledger
    assert loop._thread_queues == old_handles.thread_queues
    assert old_ctl_in.closed is False
    assert loop._unhealthy is not None
    assert "schema unavailable" in loop._unhealthy


def test_reopen_preserves_rate_audit_cursor_and_closes_old_handles() -> None:
    loop = _make_loop(rate_limit=60)
    old_handles = _fake_broker_handles()
    new_handles = _fake_broker_handles()
    old_ctl_in = cast(_CloseableQueue, old_handles.ctl_in)
    old_ledger = cast(_CloseableQueue, old_handles.ledger)
    loop._install_broker_handles(old_handles)
    loop._audit_cursor["general"] = 123

    def make_handles() -> _BrokerHandles:
        return new_handles

    loop._make_broker_handles = make_handles  # type: ignore[method-assign]

    assert (
        loop._reopen_broker_handles("rate audit", OperationalError("disk I/O error"))
        is True
    )

    assert loop._ctl_in is new_handles.ctl_in
    assert loop._audit_cursor["general"] == 123
    assert old_ctl_in.closed is True
    assert old_ledger.closed is True
    assert old_ctl_in.deleted is False


def test_close_closes_control_handles_without_delete_all() -> None:
    loop = _make_loop(rate_limit=60)
    handles = _fake_broker_handles()
    ctl_in = cast(_CloseableQueue, handles.ctl_in)
    ctl_out = cast(_CloseableQueue, handles.ctl_out)
    loop._install_broker_handles(handles)

    loop._close()

    assert ctl_in.closed is True
    assert ctl_out.closed is True
    assert ctl_in.deleted is False
    assert ctl_out.deleted is False


@pytest.mark.parametrize("command", ["STOP", "STATUS", "PING"])
def test_stale_command_for_old_driver_evidence_is_dropped(command: str) -> None:
    stops: list[bool] = []
    loop = ControlLoop(
        member_id="m_" + "a" * 26,
        db_path=None,
        token="taut-tok",
        provider="scripted",
        threads=("general",),
        handle_provider=lambda: None,
        request_stop=lambda: stops.append(True),
        shutdown=threading.Event(),
        shutdown_complete=threading.Event(),
        release_confirmed=lambda: True,
        rate_limit=60,
        ledger_queue_name="taut_meta",
        driver_pid=2,
        driver_start_time="new-driver",
    )
    replies: list[tuple[str, str]] = []
    loop._reply = lambda body, *, reply_to=None: replies.append(  # type: ignore[method-assign]
        (body, reply_to or "")
    )

    loop._dispatch(
        encode_control_command(
            command,
            "old",
            reply_to="sys.rsp_m_old",
            driver_pid=1,
            driver_start_time="old-driver",
        )
    )

    assert stops == []
    assert loop._pending_stop_seen is False
    assert replies == []


def test_queue_names_derive_from_member_id() -> None:
    assert control_in_queue_name("m_abc123") == "sys.ctl_m_abc123"
    assert control_out_queue_name("m_abc123") == "sys.rsp_m_abc123"
    # Both live under the reserved sys prefix ([TAUT-4.1]/D3).
    assert control_in_queue_name("m_x").startswith("sys.")
    assert control_out_queue_name("m_x").startswith("sys.")


def test_parse_uppercases_command_and_keeps_request_id() -> None:
    request = parse_control_request(
        '{"command": "stop", "request_id": "r1", '
        '"driver_pid": 123, "driver_start_time": "abc"}'
    )
    assert request.command == "STOP"
    assert request.request_id == "r1"
    assert request.driver_pid == 123
    assert request.driver_start_time == "abc"


def test_parse_tolerates_missing_request_id() -> None:
    request = parse_control_request('{"command": "PING"}')
    assert request.command == "PING"
    assert request.request_id is None


def test_parse_malformed_body_yields_empty_command() -> None:
    # A non-JSON or non-object body must not raise: the loop drops it.
    assert parse_control_request("not json at all").command == ""
    assert parse_control_request("[1, 2, 3]").command == ""
    assert parse_control_request('{"command": 5}').command == ""


def test_encode_command_is_single_line_json() -> None:
    body = encode_control_command(
        "STATUS", "req-9", driver_pid=123, driver_start_time="abc"
    )
    assert "\n" not in body
    assert json.loads(body) == {
        "command": "STATUS",
        "request_id": "req-9",
        "driver_pid": 123,
        "driver_start_time": "abc",
    }


def test_encode_reply_carries_status_and_correlation() -> None:
    body = encode_control_reply(
        "STATUS", "ok", request_id="req-9", provider="scripted", thread_count=2
    )
    payload = json.loads(body)
    assert payload["command"] == "STATUS"
    assert payload["status"] == "ok"
    assert payload["request_id"] == "req-9"
    assert payload["provider"] == "scripted"
    assert payload["thread_count"] == 2


def test_encode_reply_omits_request_id_when_absent() -> None:
    # An uncorrelated reply (request_id=None) omits the field entirely.
    payload = json.loads(encode_control_reply("PING", "ok", request_id=None))
    assert "request_id" not in payload
    assert payload["status"] == "ok"
