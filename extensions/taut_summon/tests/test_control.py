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
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, cast

import pytest
import taut_summon._control as control_module
from simplebroker import Queue
from simplebroker.ext import (
    DatabaseError,
    OperationalError,
    StopWatching,
)
from taut_summon._control import (
    _CONTROL_DRAIN_RECOVERABLE_FAILURES_BEFORE_DEGRADED,
    _CONTROL_REPLY_RECOVERABLE_FAILURES_BEFORE_DEGRADED,
    _RATE_AUDIT_RECOVERABLE_FAILURES_BEFORE_DEGRADED,
    ControlClient,
    ControlLoop,
    StopShutdownOutcome,
    _BrokerHandles,
    control_in_queue_name,
    control_out_queue_name,
    encode_control_command,
    encode_control_reply,
    parse_control_request,
)

from taut.envelope import encode_envelope
from taut.watcher import BaseReactor

pytestmark = pytest.mark.sqlite_only


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


class _ReplyOnlyQueues(_FakeControlQueues):
    def __init__(
        self, *, reply_after_writes: int | None, requests: _FakeControlQueues
    ) -> None:
        super().__init__(reply_after_writes=reply_after_writes)
        self._requests = requests

    def read_reply(self, name: str) -> str | None:
        ctl_writes = [
            payload
            for queue_name, payload in self._requests.writes
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
        self.persistent_flags: list[object] = []

    def queue(self, name: str, *, persistent: bool | None = None) -> _FailingReplyQueue:
        self.names.append(name)
        self.persistent_flags.append(persistent)
        return self.queue_obj


class _FlakyStatusControl:
    def __init__(self, failures: int) -> None:
        self.failures = failures
        self.calls = 0

    def request(self, command: str, *, timeout: float) -> dict[str, Any] | None:
        assert command == "STATUS"
        assert timeout == 1.0
        self.calls += 1
        if self.calls <= self.failures:
            raise OperationalError("database is locked")
        return {"status": "ok"}


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
        shutdown_outcome=lambda: StopShutdownOutcome(release_confirmed=True),
        rate_limit=rate_limit,
        ledger_queue_name="taut_meta",
        driver_pid=123,
        driver_start_time="driver-start",
        audit_start_ts=0,
    )


def test_rate_audit_reconciles_late_join_leave_and_rejoin_with_real_queues(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """[SUM-10]: membership is live, while cursors survive handle churn."""

    db_path = tmp_path / ".taut.db"
    control_module.TautClient.init(db_path=db_path)
    bot = control_module.TautClient(db_path=db_path, as_name="bot")
    bot.join("general")
    created = bot.last_created_member
    assert created is not None and created.token is not None
    with Queue("audit-clock", db_path=str(db_path)) as clock:
        audit_start = clock.generate_timestamp()

    loop = ControlLoop(
        member_id=created.member_id,
        db_path=str(db_path),
        token=created.token,
        provider="scripted",
        threads=("general",),
        handle_provider=lambda: None,
        request_stop=lambda: None,
        shutdown=threading.Event(),
        shutdown_complete=threading.Event(),
        shutdown_outcome=lambda: StopShutdownOutcome(release_confirmed=True),
        rate_limit=100,
        ledger_queue_name="taut.summon_state",
        driver_pid=123,
        driver_start_time="driver-start",
        audit_start_ts=audit_start,
    )
    closed: list[int] = []
    real_close = Queue.close

    def close_spy(queue: Queue) -> None:
        closed.append(id(queue))
        real_close(queue)

    monkeypatch.setattr(Queue, "close", close_spy)
    actor = control_module.TautClient(db_path=db_path, token=created.token)
    try:
        loop._open()
        loop._audit_pass()

        actor.join("ops")
        actor.say("ops", "late post")
        loop._audit_pass()
        first_handle = loop._thread_queues["ops"]
        assert loop._status_snapshot().thread_count == 2
        assert any(ts > audit_start for ts in loop._own_posts)

        actor.leave("ops")
        loop._audit_pass()
        assert "ops" not in loop._thread_queues
        assert closed.count(id(first_handle)) == 1

        actor.join("ops")
        actor.say("ops", "after rejoin")
        loop._audit_pass()
        second_handle = loop._thread_queues["ops"]
        assert second_handle is not first_handle
        assert loop._status_snapshot().thread_count == 2
        assert len(loop._own_posts) == len(set(loop._own_posts))
    finally:
        loop._close()
        actor.close()
        bot.close()


def test_control_handle_recovery_with_cwd_discovery_keeps_same_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A db_path=None recovery re-runs the same public cwd resolver."""

    monkeypatch.chdir(tmp_path)
    control_module.TautClient.init()
    bot = control_module.TautClient(as_name="bot")
    bot.join("general")
    created = bot.last_created_member
    assert created is not None and created.token is not None
    loop = ControlLoop(
        member_id=created.member_id,
        db_path=None,
        token=created.token,
        provider="scripted",
        threads=("general",),
        handle_provider=lambda: None,
        request_stop=lambda: None,
        shutdown=threading.Event(),
        shutdown_complete=threading.Event(),
        shutdown_outcome=lambda: StopShutdownOutcome(release_confirmed=True),
        rate_limit=60,
        ledger_queue_name="taut.summon_state",
        driver_pid=123,
        driver_start_time="driver-start",
        audit_start_ts=0,
    )
    try:
        loop._open()
        first_client = loop._client
        assert first_client is not None
        target = first_client.target

        assert loop._reopen_broker_handles(
            "rate audit", OperationalError("forced recovery")
        )
        assert loop._client is not first_client
        assert loop._client is not None
        assert loop._client.target == target
    finally:
        loop._close()
        bot.close()


class _ExplodingLedger:
    def sidecar(self, *_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("STATUS must not read the session ledger")


class _FlakyPeekQueue:
    name = "general"

    def __init__(self) -> None:
        self.calls = 0

    def peek_many(self, *args: Any, **kwargs: Any) -> list[tuple[str, int]]:
        assert args == ()
        assert kwargs == {"with_timestamps": True, "after_timestamp": 99}
        self.calls += 1
        raise OperationalError("database is locked")


class _RecordingPeekQueue:
    name = "general"

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def peek_many(self, *args: Any, **kwargs: Any) -> list[tuple[str, int]]:
        assert args == ()
        self.calls.append(dict(kwargs))
        return [
            (
                encode_envelope(
                    from_id="m_" + "a" * 26,
                    from_name="ptybot",
                    kind="message",
                    text="own post",
                ),
                9,
            )
        ]


class _BacklogPeekQueue:
    name = "general"

    def peek_many(self, *args: Any, **kwargs: Any) -> list[tuple[str, int]]:
        assert args == ()
        assert kwargs == {"with_timestamps": True, "after_timestamp": 99}
        body = encode_envelope(
            from_id="m_" + "a" * 26,
            from_name="ptybot",
            kind="message",
            text="own post",
        )
        return [(body, 99), (body, 100), (body, 101)]


class _WriteFailingControlQueue:
    def write(self, _body: str) -> None:
        raise DatabaseError("database disk image is malformed")

    def read_one(self) -> None:
        return None

    def close(self) -> None:
        return None


def _reopen_ok(_where: str, _exc: Exception) -> bool:
    return True


def test_control_reactor_derived_roles_are_distinct() -> None:
    member_id = "m_" + "a" * 26
    request_id = "request-1"
    roles = {
        "command": control_in_queue_name(member_id),
        "shared_reply": control_out_queue_name(member_id),
        "per_request_reply": f"{control_out_queue_name(member_id)}_{request_id}",
        "ledger": "taut.summon_state",
        "audit_general": "general",
        "audit_ops": "ops",
    }

    assert len(set(roles.values())) == len(roles), roles


def test_control_reactor_pending_command_waits_for_first_driven_turn(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / ".taut.db"
    control_module.TautClient.init(db_path=db_path)
    loop = _make_loop(rate_limit=60)
    seen: list[str] = []
    cast(Any, loop)._dispatch = seen.append
    with Queue(control_in_queue_name(loop._member_id), db_path=str(db_path)) as writer:
        writer.write("queued-before-construction")

    client = control_module.TautClient(db_path=db_path, persistent=True)
    reactor = control_module._ControlReactor(
        loop,
        db=client.target,
        config=client.config,
    )
    try:
        assert seen == []
        reactor.process_once()
        assert seen == ["queued-before-construction"]
    finally:
        reactor.stop(join=False)
        client.close()


def test_control_reactor_consumes_in_order_without_handler_overlap(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / ".taut.db"
    control_module.TautClient.init(db_path=db_path)
    loop = _make_loop(rate_limit=60)
    seen: list[str] = []
    active = False

    def dispatch(body: str) -> None:
        nonlocal active
        assert active is False
        active = True
        seen.append(body)
        active = False

    cast(Any, loop)._dispatch = dispatch
    client = control_module.TautClient(db_path=db_path, persistent=True)
    reactor = control_module._ControlReactor(
        loop,
        db=client.target,
        config=client.config,
    )
    with Queue(control_in_queue_name(loop._member_id), db_path=str(db_path)) as writer:
        writer.write("one")
        writer.write("two")
    try:
        reactor.process_once()
        reactor.process_once()
        assert seen == ["one", "two"]
    finally:
        reactor.stop(join=False)
        client.close()


def test_control_reactor_rejects_second_drive_caller(tmp_path: Path) -> None:
    db_path = tmp_path / ".taut.db"
    control_module.TautClient.init(db_path=db_path)
    loop = _make_loop(rate_limit=60)
    client = control_module.TautClient(db_path=db_path, persistent=True)
    reactor = control_module._ControlReactor(
        loop,
        db=client.target,
        config=client.config,
    )
    errors: list[BaseException] = []
    try:
        reactor.process_once()

        def drive() -> None:
            try:
                reactor.process_once()
            except BaseException as exc:
                errors.append(exc)

        thread = threading.Thread(target=drive)
        thread.start()
        thread.join(timeout=3.0)
        assert not thread.is_alive()
        assert len(errors) == 1
        assert isinstance(errors[0], RuntimeError)
        assert "single-owner" in str(errors[0])
    finally:
        reactor.stop(join=False)
        client.close()


@pytest.mark.parametrize("operation", ["add", "remove"])
def test_control_reactor_rejects_dynamic_topology(
    tmp_path: Path,
    operation: str,
) -> None:
    db_path = tmp_path / ".taut.db"
    control_module.TautClient.init(db_path=db_path)
    loop = _make_loop(rate_limit=60)
    client = control_module.TautClient(db_path=db_path, persistent=True)
    reactor = control_module._ControlReactor(
        loop,
        db=client.target,
        config=client.config,
    )
    try:
        with pytest.raises(NotImplementedError, match="fixed at construction"):
            if operation == "add":
                reactor.add_queue("other", lambda *_args: None)
            else:
                reactor.remove_queue(control_in_queue_name(loop._member_id))
    finally:
        reactor.stop(join=False)
        client.close()


def test_status_snapshot_uses_live_session_id_without_ledger_read() -> None:
    loop = _make_loop(rate_limit=60)
    loop._ledger = cast(Queue, _ExplodingLedger())

    loop.update_session_id("sess-live")
    fields = loop._status_snapshot().as_fields()

    assert fields["session_id"] == "sess-live"
    assert fields["driver"] == "alive"


def test_control_reactor_inherits_shared_lifecycle_templates() -> None:
    reactor_cls = control_module._ControlReactor

    assert reactor_cls.process_once is BaseReactor.process_once
    assert reactor_cls.wait_for_activity is BaseReactor.wait_for_activity
    assert reactor_cls.stop is BaseReactor.stop
    assert reactor_cls.cleanup is BaseReactor.cleanup


def test_control_client_tags_write_fault_plane() -> None:
    client = ControlClient(
        lambda _name: cast(Queue, _WriteFailingControlQueue()),
        "m_abc",
        driver_pid=1,
        driver_start_time="start",
    )

    with pytest.raises(DatabaseError) as caught:
        client.request("STATUS", timeout=0.01)

    assert (
        getattr(caught.value, control_module._CONTROL_FAULT_PLANE_ATTR)
        == "control_write"
    )


def test_rate_audit_does_not_layer_retry_over_peek_many_failure() -> None:
    loop = _make_loop(rate_limit=60)
    queue = _FlakyPeekQueue()

    with pytest.raises(OperationalError, match="locked"):
        loop._audit_thread("general", cast(Queue, queue), cutoff=100)

    assert queue.calls == 1
    assert list(loop._own_posts) == []
    assert loop._audit_cursor.get("general") is None


def test_rate_audit_uses_plain_queue_peek_many_once() -> None:
    loop = _make_loop(rate_limit=60)
    queue = _RecordingPeekQueue()

    loop._audit_thread("general", cast(Queue, queue), cutoff=0)

    assert queue.calls == [{"with_timestamps": True, "after_timestamp": 0}]
    assert list(loop._own_posts) == [9]
    assert loop._audit_cursor["general"] == 9


def test_rate_audit_excludes_old_backlog_at_inclusive_hybrid_cutoff() -> None:
    loop = _make_loop(rate_limit=60)

    loop._audit_thread("general", cast(Queue, _BacklogPeekQueue()), 100)

    assert list(loop._own_posts) == [100, 101]
    assert loop._audit_cursor["general"] == 101


def test_rate_audit_derives_one_cutoff_from_public_broker_timestamp() -> None:
    class TimestampQueue:
        calls = 0

        def generate_timestamp(self) -> int:
            self.calls += 1
            return int(control_module._RATE_WINDOW_SECONDS * 1_000_000_000) + 100

    loop = _make_loop(rate_limit=60)
    ledger = TimestampQueue()
    loop._ledger = cast(Queue, ledger)
    loop._thread_queues = {"general": cast(Queue, _BacklogPeekQueue())}
    loop._reconcile_audit_threads = lambda: None  # type: ignore[method-assign]

    loop._audit_pass()

    assert ledger.calls == 1
    assert list(loop._own_posts) == [100, 101]


def test_rate_audit_prunes_expired_posts_across_interleaved_threads() -> None:
    class TimestampQueue:
        timestamps = iter(
            (
                int(control_module._RATE_WINDOW_SECONDS * 1_000_000_000) + 100,
                int(control_module._RATE_WINDOW_SECONDS * 1_000_000_000) + 175,
            )
        )

        def generate_timestamp(self) -> int:
            return next(self.timestamps)

    class ThreadQueue:
        def __init__(self, timestamp: int) -> None:
            self.timestamp = timestamp

        def peek_many(self, *args: Any, **kwargs: Any) -> list[tuple[str, int]]:
            assert args == ()
            assert kwargs["with_timestamps"] is True
            assert kwargs["after_timestamp"] >= 0
            if kwargs["after_timestamp"] >= self.timestamp:
                return []
            return [
                (
                    encode_envelope(
                        from_id="m_" + "a" * 26,
                        from_name="ptybot",
                        kind="message",
                        text="own post",
                    ),
                    self.timestamp,
                )
            ]

    loop = _make_loop(rate_limit=60)
    loop._ledger = cast(Queue, TimestampQueue())
    loop._thread_queues = {
        "general": cast(Queue, ThreadQueue(200)),
        "dev": cast(Queue, ThreadQueue(150)),
    }
    loop._reconcile_audit_threads = lambda: None  # type: ignore[method-assign]

    loop._audit_pass()
    assert list(loop._own_posts) == [200, 150]
    loop._audit_pass()

    assert list(loop._own_posts) == [200]


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


def test_control_client_can_split_persistent_request_from_transient_reply(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(control_module, "_CONTROL_REQUEST_RETRY_INTERVAL_SECONDS", 0.01)
    request_queues = _FakeControlQueues(reply_after_writes=None)
    reply_queues = _ReplyOnlyQueues(reply_after_writes=1, requests=request_queues)
    client = ControlClient(
        cast(Any, request_queues.queue),
        "m_abc",
        reply_queue_factory=cast(Any, reply_queues.queue),
        driver_pid=123,
        driver_start_time="driver-start",
    )

    reply = client.request("STATUS", timeout=1.0)

    assert reply is not None
    assert reply["status"] == "ok"
    assert [name for name, _payload in request_queues.writes] == ["sys.ctl_m_abc"]
    assert cast(str, request_queues.writes[0][1]["reply_to"]).startswith(
        "sys.rsp_m_abc_"
    )
    assert reply_queues.writes == []
    assert request_queues.closed == []
    assert request_queues.writes[0][1]["reply_to"] in reply_queues.closed
    client.close()
    assert request_queues.closed == ["sys.ctl_m_abc"]


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


def test_stop_replies_error_when_driver_release_is_unconfirmed() -> None:
    loop = _make_loop(rate_limit=60)
    loop._db_path = "unused"
    loop._pending_stop = "req-release-error"
    loop._pending_stop_seen = True
    loop._pending_stop_reply_to = "sys.rsp_release_error"
    loop._shutdown_complete.set()
    loop._shutdown_outcome = lambda: StopShutdownOutcome(release_confirmed=False)
    replies: list[tuple[dict[str, Any], str | None]] = []
    dynamic_loop = cast(Any, loop)
    dynamic_loop._open = lambda: None
    dynamic_loop._close = lambda: None
    dynamic_loop._reply = lambda body, *, reply_to: replies.append(
        (json.loads(body), reply_to)
    )

    loop.run()

    assert replies == [
        (
            {
                "command": "STOP",
                "status": "error",
                "error": "driver slot release could not be confirmed",
                "request_id": "req-release-error",
            },
            "sys.rsp_release_error",
        )
    ]


def test_stop_replies_error_when_driver_release_confirmation_raises() -> None:
    loop = _make_loop(rate_limit=60)
    loop._db_path = "unused"
    loop._pending_stop = "req-release-exception"
    loop._pending_stop_seen = True
    loop._pending_stop_reply_to = "sys.rsp_release_exception"
    loop._shutdown_complete.set()
    loop._shutdown_outcome = lambda: (_ for _ in ()).throw(
        OperationalError("release ledger unavailable")
    )
    replies: list[tuple[dict[str, Any], str | None]] = []
    dynamic_loop = cast(Any, loop)
    dynamic_loop._open = lambda: None
    dynamic_loop._close = lambda: None
    dynamic_loop._reply = lambda body, *, reply_to: replies.append(
        (json.loads(body), reply_to)
    )

    loop.run()

    assert replies == [
        (
            {
                "command": "STOP",
                "status": "error",
                "error": (
                    "driver slot release confirmation failed: "
                    "release ledger unavailable"
                ),
                "request_id": "req-release-exception",
            },
            "sys.rsp_release_exception",
        )
    ]


@pytest.mark.parametrize(
    ("outcome", "expected_error"),
    [
        (
            StopShutdownOutcome(
                release_confirmed=True,
                teardown_error="PTY child cleanup failed",
            ),
            "driver teardown failed: PTY child cleanup failed",
        ),
        (
            StopShutdownOutcome(
                release_confirmed=False,
                release_error="database is locked",
            ),
            "driver slot release failed: database is locked",
        ),
        (
            StopShutdownOutcome(
                release_confirmed=False,
                teardown_error="PTY write failed",
                release_error="database is locked",
            ),
            (
                "driver teardown failed: PTY write failed; "
                "driver slot release also failed: database is locked"
            ),
        ),
        (
            StopShutdownOutcome(
                release_confirmed=False,
                teardown_error="PTY write failed",
            ),
            (
                "driver teardown failed: PTY write failed; "
                "driver slot release also could not be confirmed"
            ),
        ),
    ],
)
def test_stop_replies_with_exact_finalized_shutdown_failure(
    outcome: StopShutdownOutcome,
    expected_error: str,
) -> None:
    loop = _make_loop(rate_limit=60)
    loop._db_path = "unused"
    loop._pending_stop = "req-exact-shutdown-error"
    loop._pending_stop_seen = True
    loop._pending_stop_reply_to = "sys.rsp_exact_shutdown_error"
    loop._shutdown_complete.set()
    loop._shutdown_outcome = lambda: outcome
    replies: list[dict[str, Any]] = []
    dynamic_loop = cast(Any, loop)
    dynamic_loop._open = lambda: None
    dynamic_loop._close = lambda: None
    dynamic_loop._reply = lambda body, *, reply_to: replies.append(json.loads(body))

    loop.run()

    assert replies == [
        {
            "command": "STOP",
            "status": "error",
            "error": expected_error,
            "request_id": "req-exact-shutdown-error",
        }
    ]


def test_rate_breaker_rearms_after_flood_subsides() -> None:
    # [SUM-10] circuit-breaker: hard breach is not one-shot. Once the rate
    # falls back under the limit the breaker re-arms and can trip again.
    loop = _make_loop(rate_limit=2)
    loop._own_posts.extend([0] * 6)  # 6 > 2*limit -> hard breach
    loop._enforce()
    assert loop._hard_breached is True

    loop._own_posts.clear()  # flood subsided (rate back under limit)
    loop._enforce()
    assert loop._hard_breached is False  # re-armed
    assert loop._nudged is False

    loop._own_posts.extend([0] * 6)  # floods again
    loop._enforce()
    assert loop._hard_breached is True  # trips a second time


def test_status_reports_degraded_control_health_detail() -> None:
    # Repeated broker errors mark the control plane unhealthy, and STATUS
    # surfaces the detail ([SUM-9]) instead of swallowing the failure.
    loop = _make_loop(rate_limit=60)
    healthy = loop._status_snapshot().as_fields()
    assert healthy["control_health"] == "ok"
    assert "health_detail" not in healthy

    loop._mark_unhealthy("control drain", DatabaseError("disk I/O error"))
    degraded = loop._status_snapshot().as_fields()
    assert degraded["control_health"] == "degraded"
    assert "disk I/O error" in degraded["health_detail"]


def test_single_rate_audit_broker_failure_does_not_degrade_status() -> None:
    # The rate audit is a safety backstop, not the STOP/STATUS control drain.
    # One broker-surface failure in the safety audit should skip that audit and
    # let the next cadence try again rather than permanently poisoning control
    # health.
    loop = _make_loop(rate_limit=60)
    cast(Any, loop)._reopen_broker_handles = _reopen_ok

    loop._mark_rate_audit_failure(OperationalError("database is locked"))

    healthy = loop._status_snapshot().as_fields()
    assert healthy["control_health"] == "ok"
    assert "health_detail" not in healthy


def test_repeated_rate_audit_reopen_failures_escalate_fatal() -> None:
    loop = _make_loop(rate_limit=60)
    cast(Any, loop)._reopen_broker_handles = lambda _where, _exc: False

    loop._mark_rate_audit_failure(OperationalError("database is locked"))
    for _ in range(_RATE_AUDIT_RECOVERABLE_FAILURES_BEFORE_DEGRADED - 1):
        assert loop._recover_pending_control_fault() is False
    with pytest.raises(RuntimeError, match="rate audit recovery exhausted"):
        loop._recover_pending_control_fault()

    degraded = loop._status_snapshot().as_fields()
    assert degraded["control_health"] == "degraded"
    assert "consecutive broker failures" in degraded["health_detail"]


def test_disk_io_rate_audit_failure_uses_same_reopen_path() -> None:
    loop = _make_loop(rate_limit=60)
    reopened: list[tuple[str, str]] = []

    def reopen(where: str, exc: Exception) -> bool:
        reopened.append((where, str(exc)))
        return True

    loop._reopen_broker_handles = reopen  # type: ignore[method-assign]

    loop._mark_rate_audit_failure(DatabaseError("disk I/O error"))
    assert reopened == []
    assert loop._recover_pending_control_fault() is True

    assert reopened == [("rate audit", "disk I/O error")]
    assert loop._status_snapshot().as_fields()["control_health"] == "ok"


def test_control_drain_failure_reopens_only_after_turn_unwinds() -> None:
    loop = _make_loop(rate_limit=60)
    reopened: list[tuple[str, str]] = []

    def reopen(where: str, exc: Exception) -> bool:
        reopened.append((where, str(exc)))
        return True

    loop._reopen_broker_handles = reopen  # type: ignore[method-assign]

    loop._mark_control_drain_failure(OperationalError("database is locked"))
    assert reopened == []

    assert loop._recover_pending_control_fault() is True
    assert reopened == [("control drain", "database is locked")]
    assert loop._pending_control_fault is None


def test_control_loop_recovery_never_waits_on_retired_reactor() -> None:
    loop = _make_loop(rate_limit=60)
    loop._db_path = "unused"
    calls: list[str] = []

    class OldReactor:
        def process_once(self) -> None:
            calls.append("old.process")
            loop._mark_control_drain_failure(OperationalError("database is locked"))

        def wait_for_activity(self, *, timeout: float) -> None:
            del timeout
            calls.append("old.wait")
            raise AssertionError("retired reactor was waited")

    loop._control_reactor = cast(Any, OldReactor())
    loop._open = lambda: None  # type: ignore[method-assign]
    loop._close = lambda: None  # type: ignore[method-assign]

    def reopen(where: str, exc: Exception) -> bool:
        calls.append(f"reopen:{where}:{exc}")
        loop._shutdown.set()
        return True

    loop._reopen_broker_handles = reopen  # type: ignore[method-assign]

    loop.run()

    assert calls == [
        "old.process",
        "reopen:control drain:database is locked",
    ]


def test_control_loop_retries_replacement_without_another_old_turn() -> None:
    loop = _make_loop(rate_limit=60)
    loop._db_path = "unused"
    process_calls = 0
    wait_calls = 0
    reopen_calls = 0
    delays: list[float] = []

    class ImmediateRetryStop:
        def is_set(self) -> bool:
            return False

        def wait(self, delay: float) -> bool:
            delays.append(delay)
            return False

    class FaultingReactor:
        def process_once(self) -> None:
            nonlocal process_calls
            process_calls += 1
            loop._mark_control_drain_failure(OperationalError("database is locked"))

        def wait_for_activity(self, *, timeout: float) -> None:
            nonlocal wait_calls
            del timeout
            wait_calls += 1

    loop._shutdown = cast(Any, ImmediateRetryStop())
    loop._control_reactor = cast(Any, FaultingReactor())
    loop._open = lambda: None  # type: ignore[method-assign]
    loop._close = lambda: None  # type: ignore[method-assign]

    def fail_reopen(_where: str, _exc: Exception) -> bool:
        nonlocal reopen_calls
        reopen_calls += 1
        return False

    cast(Any, loop)._reopen_broker_handles = fail_reopen

    with pytest.raises(RuntimeError, match="control drain recovery exhausted"):
        loop.run()

    assert process_calls == 1
    assert wait_calls == 0
    assert reopen_calls == _CONTROL_DRAIN_RECOVERABLE_FAILURES_BEFORE_DEGRADED
    assert len(delays) == _CONTROL_DRAIN_RECOVERABLE_FAILURES_BEFORE_DEGRADED - 1


def test_control_loop_wait_fault_uses_between_turn_recovery() -> None:
    loop = _make_loop(rate_limit=60)
    loop._db_path = "unused"
    calls: list[str] = []

    class WaitFaultReactor:
        def process_once(self) -> None:
            calls.append("process")

        def wait_for_activity(self, *, timeout: float) -> None:
            assert timeout > 0
            calls.append("wait")
            raise OperationalError("wait failed")

    loop._control_reactor = cast(Any, WaitFaultReactor())
    loop._open = lambda: None  # type: ignore[method-assign]
    loop._close = lambda: None  # type: ignore[method-assign]
    loop._audit_if_due = lambda: None  # type: ignore[method-assign]

    def reopen(where: str, exc: Exception) -> bool:
        calls.append(f"reopen:{where}:{exc}")
        loop._shutdown.set()
        return True

    loop._reopen_broker_handles = reopen  # type: ignore[method-assign]

    loop.run()

    assert calls == ["process", "wait", "reopen:control wait:wait failed"]


def test_due_audit_runs_before_positive_wait_timeout() -> None:
    loop = _make_loop(rate_limit=60)
    loop._interval = 60.0
    audited: list[bool] = []
    loop._audit_pass = lambda: audited.append(True)  # type: ignore[method-assign]
    loop._next_rate_audit_at = 0.0

    loop._audit_if_due()
    timeout = loop._next_control_wait_timeout()

    assert audited == [True]
    assert 0.0 < timeout <= 60.0


def test_non_broker_audit_failure_is_fatal_not_recoverable() -> None:
    loop = _make_loop(rate_limit=60)
    loop._audit_pass = (  # type: ignore[method-assign]
        lambda: (_ for _ in ()).throw(RuntimeError("audit logic bug"))
    )
    loop._next_rate_audit_at = 0.0

    loop._audit_if_due()

    assert loop._pending_control_fault is not None
    assert loop._pending_control_fault.recoverable is False
    with pytest.raises(RuntimeError, match="audit logic bug"):
        loop._recover_pending_control_fault()


def test_successful_recovery_clears_matching_transient_degraded_health() -> None:
    loop = _make_loop(rate_limit=60)
    outcomes = iter((False, True))
    cast(Any, loop)._reopen_broker_handles = lambda _where, _exc: next(outcomes)
    loop._mark_control_drain_failure(OperationalError("database is locked"))

    # Mirror the real failed-reopen path's temporary health report.
    loop._mark_unhealthy("control drain reopen", RuntimeError("still locked"))
    assert loop._recover_pending_control_fault() is False
    assert loop._status_snapshot().control_health == "degraded"

    assert loop._recover_pending_control_fault() is True
    assert loop._status_snapshot().control_health == "ok"


def test_control_reactor_native_activity_wakes_before_probe_interval(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / ".taut.db"
    control_module.TautClient.init(db_path=db_path)
    loop = _make_loop(rate_limit=60)
    loop._interval = 10.0
    handled = threading.Event()
    waiting = threading.Event()
    errors: list[BaseException] = []
    cast(Any, loop)._dispatch = lambda _body: handled.set()
    client = control_module.TautClient(db_path=db_path, persistent=True)
    reactor = control_module._ControlReactor(
        loop,
        db=client.target,
        config=client.config,
    )

    def drive() -> None:
        try:
            reactor.process_once()
            waiting.set()
            reactor.wait_for_activity(timeout=10.0)
            reactor.process_once()
        except BaseException as exc:
            errors.append(exc)
        finally:
            reactor.stop(join=False)

    thread = threading.Thread(target=drive)
    thread.start()
    try:
        assert waiting.wait(timeout=3.0)
        with Queue(
            control_in_queue_name(loop._member_id), db_path=str(db_path)
        ) as writer:
            writer.write("wake")
        assert handled.wait(timeout=2.0)
    finally:
        reactor.request_stop()
        thread.join(timeout=3.0)
        client.close()

    assert not thread.is_alive()
    assert errors == []


def test_control_reactor_stops_on_non_broker_dispatch_error(tmp_path: Path) -> None:
    loop = _make_loop(rate_limit=60)
    db_path = tmp_path / ".taut.db"
    control_module.TautClient.init(db_path=db_path)
    client = control_module.TautClient(db_path=db_path)
    reactor = control_module._ControlReactor(
        loop,
        db=client.target,
        config=client.config,
    )
    loop._request_stop = lambda: (_ for _ in ()).throw(RuntimeError("logic bug"))
    queue = reactor._queue(control_in_queue_name(loop._member_id))
    queue.write(
        encode_control_command(
            "STOP",
            "req-1",
            driver_pid=123,
            driver_start_time="driver-start",
        )
    )

    try:
        with pytest.raises(StopWatching):
            reactor.process_once()
    finally:
        reactor.cleanup()
        client.close()

    assert loop._control_drain_recoverable_failures == 0
    assert loop._unhealthy is not None
    assert "control dispatch" in loop._unhealthy
    assert "logic bug" in loop._unhealthy


def test_control_reactor_treats_status_key_collision_as_fatal(tmp_path: Path) -> None:
    class ReservedStatusHandle:
        def status_fields(self) -> dict[str, str]:
            return {"provider": "wrong-owner"}

    loop = _make_loop(rate_limit=60)
    loop._handle_provider = lambda: cast(Any, ReservedStatusHandle())
    db_path = tmp_path / ".taut.db"
    control_module.TautClient.init(db_path=db_path)
    client = control_module.TautClient(db_path=db_path)
    reactor = control_module._ControlReactor(
        loop,
        db=client.target,
        config=client.config,
    )
    queue = reactor._queue(control_in_queue_name(loop._member_id))
    queue.write(
        encode_control_command(
            "STATUS",
            "req-status-collision",
            driver_pid=123,
            driver_start_time="driver-start",
        )
    )

    try:
        with pytest.raises(StopWatching):
            reactor.process_once()
    finally:
        reactor.cleanup()
        client.close()

    assert loop._unhealthy is not None
    assert "reserved STATUS key" in loop._unhealthy


def test_control_loop_run_surfaces_stop_request_programming_failure(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / ".taut.db"
    control_module.TautClient.init(db_path=db_path)
    loop = _make_loop(rate_limit=60)
    loop._db_path = str(db_path)
    loop._request_stop = lambda: (_ for _ in ()).throw(RuntimeError("logic bug"))
    queue = Queue(control_in_queue_name(loop._member_id), db_path=str(db_path))
    try:
        queue.write(
            encode_control_command(
                "STOP",
                "req-1",
                driver_pid=123,
                driver_start_time="driver-start",
            )
        )
    finally:
        queue.close()

    with pytest.raises(RuntimeError, match="logic bug"):
        loop.run()


def test_repeated_control_drain_reopen_failures_escalate_fatal() -> None:
    loop = _make_loop(rate_limit=60)

    cast(Any, loop)._reopen_broker_handles = lambda _where, _exc: False

    loop._mark_control_drain_failure(OperationalError("database is locked"))
    for _ in range(_CONTROL_DRAIN_RECOVERABLE_FAILURES_BEFORE_DEGRADED - 1):
        assert loop._recover_pending_control_fault() is False
    with pytest.raises(RuntimeError, match="control drain recovery exhausted"):
        loop._recover_pending_control_fault()

    degraded = loop._status_snapshot().as_fields()
    assert degraded["control_health"] == "degraded"
    assert "consecutive broker failures" in degraded["health_detail"]


def test_single_control_reply_failure_does_not_reopen_or_degrade() -> None:
    loop = _make_loop(rate_limit=60)
    reply_queue = _FailingReplyQueue(OperationalError("database is locked"))
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

    assert reopened == []
    assert reply_queue.closed is True
    assert loop._client is not None
    assert cast(_ReplyClient, loop._client).persistent_flags == [False]
    loop._client = None
    assert loop._status_snapshot().as_fields()["control_health"] == "ok"


def test_repeated_control_reply_failures_degrade_status() -> None:
    loop = _make_loop(rate_limit=60)
    loop._reopen_broker_handles = _reopen_ok  # type: ignore[assignment,method-assign]

    for _ in range(_CONTROL_REPLY_RECOVERABLE_FAILURES_BEFORE_DEGRADED):
        reply_queue = _FailingReplyQueue(OperationalError("database is locked"))
        loop._client = cast(Any, _ReplyClient(reply_queue))
        loop._reply(
            encode_control_reply("PING", "ok", request_id="req"),
            reply_to="sys.rsp_m_abc_req",
        )

    loop._client = None
    degraded = loop._status_snapshot().as_fields()
    assert degraded["control_health"] == "degraded"
    assert "consecutive broker failures" in degraded["health_detail"]


def test_wrapped_locked_control_reply_does_not_reopen_or_degrade() -> None:
    loop = _make_loop(rate_limit=60)
    reopened: list[tuple[str, str]] = []

    def reopen(where: str, exc: Exception) -> bool:
        reopened.append((where, str(exc)))
        return True

    loop._reopen_broker_handles = reopen  # type: ignore[method-assign]

    loop._mark_control_reply_failure(
        RuntimeError("Failed to get database connection: database is locked")
    )

    assert reopened == []
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


@pytest.mark.parametrize(
    "failure_stage",
    ["reactor", "command", "shared_reply", "ledger", "thread"],
)
def test_partial_control_handle_construction_closes_every_created_owner(
    failure_stage: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loop = _make_loop(rate_limit=60)
    loop._db_path = "unused"
    client_closes: list[str] = []
    reactor_cleanups: list[str] = []
    persistent_flags: list[bool] = []

    class FakeClient:
        target = "unused"
        config: dict[str, Any] = {}

        def __init__(
            self,
            *,
            db_path: str,
            token: str,
            persistent: bool,
        ) -> None:
            assert (db_path, token) == ("unused", "taut-tok")
            persistent_flags.append(persistent)

        def close(self) -> None:
            client_closes.append("client")

    class FakeReactor:
        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            if failure_stage == "reactor":
                raise RuntimeError("failed at reactor")

        def _queue(self, name: str) -> Queue:
            role = {
                control_in_queue_name(loop._member_id): "command",
                control_out_queue_name(loop._member_id): "shared_reply",
                "taut_meta": "ledger",
                "general": "thread",
            }[name]
            if failure_stage == role:
                raise RuntimeError(f"failed at {role}")
            return cast(Queue, _CloseableQueue())

        def cleanup(self) -> None:
            reactor_cleanups.append("reactor")

    monkeypatch.setattr(control_module, "TautClient", FakeClient)
    monkeypatch.setattr(control_module, "_ControlReactor", FakeReactor)

    with pytest.raises(RuntimeError, match=f"failed at {failure_stage}"):
        loop._make_broker_handles()

    assert persistent_flags == [True]
    assert client_closes == ["client"]
    assert reactor_cleanups == ([] if failure_stage == "reactor" else ["reactor"])


def test_control_loop_constructs_and_closes_persistent_handles_on_owner_thread(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / ".taut.db"
    control_module.TautClient.init(db_path=db_path)
    # The control loop audits immediately after publishing its handles. Use a
    # real token-selected member so this ownership test cannot race an
    # unrelated TokenError from an invented identity.
    bootstrap = control_module.TautClient(db_path=db_path, as_name="bot")
    bootstrap.join("general")
    created = bootstrap.last_created_member
    assert created is not None and created.token is not None
    bootstrap.join("dev")
    bootstrap.close()
    construction: list[tuple[bool, threading.Thread]] = []
    client_closes: list[threading.Thread] = []

    class RecordingClient(control_module.TautClient):
        def __init__(self, *args: Any, persistent: bool = False, **kwargs: Any) -> None:
            construction.append((persistent, threading.current_thread()))
            super().__init__(*args, persistent=persistent, **kwargs)

        def close(self) -> None:
            client_closes.append(threading.current_thread())
            super().close()

    monkeypatch.setattr(control_module, "TautClient", RecordingClient)
    monkeypatch.setenv("TAUT_SUMMON_CONTROL_INTERVAL", "0.05")
    shutdown = threading.Event()
    loop = ControlLoop(
        member_id=created.member_id,
        db_path=str(db_path),
        token=created.token,
        provider="scripted",
        threads=("general", "dev"),
        handle_provider=lambda: None,
        request_stop=lambda: None,
        shutdown=shutdown,
        shutdown_complete=threading.Event(),
        shutdown_outcome=lambda: StopShutdownOutcome(release_confirmed=True),
        rate_limit=60,
        ledger_queue_name="taut.summon_state",
        driver_pid=123,
        driver_start_time="driver-start",
    )
    errors: list[BaseException] = []

    def run() -> None:
        try:
            loop.run()
        except BaseException as exc:
            errors.append(exc)

    owner = threading.Thread(target=run)
    owner.start()
    deadline = time.monotonic() + 3.0
    while loop._control_reactor is None and time.monotonic() < deadline:
        time.sleep(0.01)
    reactor = loop._control_reactor
    assert reactor is not None
    shutdown.set()
    reactor.request_stop()
    owner.join(timeout=3.0)

    assert not owner.is_alive()
    assert errors == []
    assert construction == [(True, owner)]
    assert client_closes == [owner]


def test_control_loop_real_correlated_ping_round_trip(tmp_path: Path) -> None:
    db_path = tmp_path / ".taut.db"
    control_module.TautClient.init(db_path=db_path)
    peer = control_module.TautClient(db_path=db_path, as_name="peer")
    peer.join("general")
    peer.join("dev")
    bot = control_module.TautClient(db_path=db_path, as_name="bot")
    bot.join("general")
    created = bot.last_created_member
    assert created is not None and created.token is not None
    bot.join("dev")
    ledger_owner = control_module.TautClient(db_path=db_path, persistent=True)
    ledger_owner.queue("taut.summon_state")
    pump_ready = threading.Event()
    release_pump = threading.Event()

    def own_pump_client() -> None:
        pump_client = control_module.TautClient(
            db_path=db_path,
            token=created.token,
            persistent=True,
        )
        pump_client.queue("taut.summon_state")
        pump_client.whoami()
        pump_ready.set()
        release_pump.wait(timeout=5.0)
        pump_client.close()

    pump_owner = threading.Thread(target=own_pump_client)
    pump_owner.start()
    assert pump_ready.wait(timeout=3.0)
    shutdown = threading.Event()
    loop = ControlLoop(
        member_id=created.member_id,
        db_path=str(db_path),
        token=created.token,
        provider="scripted",
        threads=("general", "dev"),
        handle_provider=lambda: None,
        request_stop=lambda: None,
        shutdown=shutdown,
        shutdown_complete=threading.Event(),
        shutdown_outcome=lambda: StopShutdownOutcome(release_confirmed=True),
        rate_limit=60,
        ledger_queue_name="taut.summon_state",
        driver_pid=123,
        driver_start_time="driver-start",
    )
    errors: list[BaseException] = []

    def run() -> None:
        try:
            loop.run()
        except BaseException as exc:
            errors.append(exc)

    owner = threading.Thread(target=run)
    owner.start()
    deadline = time.monotonic() + 3.0
    while loop._control_reactor is None and time.monotonic() < deadline:
        time.sleep(0.01)
    assert loop._control_reactor is not None
    while not loop._control_reactor._strategy_started and time.monotonic() < deadline:
        time.sleep(0.01)
    assert loop._control_reactor._strategy_started
    watcher_box: list[Any] = []
    watcher_constructed = threading.Event()

    def own_watcher() -> None:
        watcher_client = control_module.TautClient(
            db_path=db_path,
            token=created.token,
            persistent=True,
        )
        owned_watcher = watcher_client.watch(lambda _item: None, persistent=True)
        watcher_box.append(owned_watcher)
        watcher_constructed.set()
        try:
            owned_watcher.run()
        finally:
            owned_watcher.stop(join=False)
            watcher_client.close()

    watcher_owner = threading.Thread(target=own_watcher)
    watcher_owner.start()
    assert watcher_constructed.wait(timeout=3.0)

    request_id = "driver-shape"
    reply_name = f"{control_out_queue_name(loop._member_id)}_{request_id}"
    reply_queue = Queue(reply_name, db_path=str(db_path))
    body = encode_control_command(
        "PING",
        request_id,
        reply_to=reply_name,
        driver_pid=123,
        driver_start_time="driver-start",
    )
    writer_script = (
        "from simplebroker import Queue; import sys; "
        "q=Queue(sys.argv[1], db_path=sys.argv[2]); "
        "q.write(sys.argv[3]); q.close()"
    )
    try:
        subprocess.run(
            [
                sys.executable,
                "-c",
                writer_script,
                control_in_queue_name(loop._member_id),
                str(db_path),
                body,
            ],
            check=True,
            env=os.environ.copy(),
        )
        reply_body: str | None = None
        reply_deadline = time.monotonic() + 3.0
        while reply_body is None and time.monotonic() < reply_deadline:
            reply_body = cast(str | None, reply_queue.read_one())
            if reply_body is None:
                time.sleep(0.01)
        reply = json.loads(reply_body) if reply_body is not None else None
        assert reply is not None
        request_id = reply.pop("request_id")
        assert isinstance(request_id, str) and request_id
        assert reply == {
            "command": "PING",
            "status": "ok",
            "message": "PONG",
        }
    finally:
        reply_queue.close()
        shutdown.set()
        if loop._control_reactor is not None:
            loop._control_reactor.request_stop()
        owner.join(timeout=3.0)
        watcher_box[0].request_stop()
        watcher_owner.join(timeout=3.0)
        release_pump.set()
        pump_owner.join(timeout=3.0)
        ledger_owner.close()
        bot.close()
        peer.close()

    assert not owner.is_alive()
    assert not watcher_owner.is_alive()
    assert not pump_owner.is_alive()
    assert errors == []


def test_control_loop_cross_process_ping_wakes_and_replies(tmp_path: Path) -> None:
    db_path = tmp_path / ".taut.db"
    control_module.TautClient.init(db_path=db_path)
    bot = control_module.TautClient(db_path=db_path, as_name="bot")
    bot.join("general")
    created = bot.last_created_member
    assert created is not None and created.token is not None
    member_id = created.member_id
    shutdown = threading.Event()
    loop = ControlLoop(
        member_id=member_id,
        db_path=str(db_path),
        token=created.token,
        provider="scripted",
        threads=(),
        handle_provider=lambda: None,
        request_stop=lambda: None,
        shutdown=shutdown,
        shutdown_complete=threading.Event(),
        shutdown_outcome=lambda: StopShutdownOutcome(release_confirmed=True),
        rate_limit=60,
        ledger_queue_name="taut.summon_state",
        driver_pid=123,
        driver_start_time="driver-start",
    )
    errors: list[BaseException] = []

    def run() -> None:
        try:
            loop.run()
        except BaseException as exc:
            errors.append(exc)

    owner = threading.Thread(target=run)
    owner.start()
    deadline = time.monotonic() + 3.0
    while loop._control_reactor is None and time.monotonic() < deadline:
        time.sleep(0.01)

    request_id = "cross-process"
    reply_name = f"{control_out_queue_name(member_id)}_{request_id}"
    reply_queue = Queue(reply_name, db_path=str(db_path))
    body = encode_control_command(
        "PING",
        request_id,
        reply_to=reply_name,
        driver_pid=123,
        driver_start_time="driver-start",
    )
    writer_script = (
        "from simplebroker import Queue; import sys; "
        "q=Queue(sys.argv[1], db_path=sys.argv[2]); "
        "q.write(sys.argv[3]); q.close()"
    )
    try:
        subprocess.run(
            [
                sys.executable,
                "-c",
                writer_script,
                control_in_queue_name(member_id),
                str(db_path),
                body,
            ],
            check=True,
            env=os.environ.copy(),
        )
        reply: str | None = None
        deadline = time.monotonic() + 3.0
        while reply is None and time.monotonic() < deadline:
            reply = cast(str | None, reply_queue.read_one())
            if reply is None:
                time.sleep(0.01)
        assert reply is not None
        assert json.loads(reply)["message"] == "PONG"
    finally:
        reply_queue.close()
        shutdown.set()
        if loop._control_reactor is not None:
            loop._control_reactor.request_stop()
        owner.join(timeout=3.0)
        bot.close()

    assert not owner.is_alive()
    assert errors == []


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
        shutdown_outcome=lambda: StopShutdownOutcome(release_confirmed=True),
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
