"""Control protocol and owner-called policy proofs ([SUM-9], [SUM-10]).

The single SummonReactor drives control alongside chat. This suite preserves
protocol, rate, ordering, fault and final STOP obligations without reconstructing
the retired ControlLoop/_ControlReactor scheduling layer.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
import taut_summon._control as control_module
from simplebroker import Queue
from simplebroker.ext import DatabaseError, OperationalError
from taut_summon._control import (
    ControlClient,
    ControlPolicy,
    StopShutdownOutcome,
    control_in_queue_name,
    control_out_queue_name,
    encode_control_command,
    encode_control_reply,
    parse_control_request,
)
from taut_summon._reactor import PreparedInjection, SummonReactor

from taut.client import TautClient
from taut.envelope import encode_envelope
from taut.watcher import BaseReactor

pytestmark = pytest.mark.sqlite_only


def _make_policy(rate_limit: int) -> ControlPolicy:
    # Pure rate/status tests own no storage. Integration tests below use real
    # client/runtime/reactor owners, not a fake scheduler.
    return ControlPolicy(
        client=cast(Any, SimpleNamespace(list_threads=lambda **kwargs: [])),
        reactor=cast(Any, SimpleNamespace(_queue=lambda _name: None)),
        member_id="m_" + "a" * 26,
        provider="scripted",
        threads=("general",),
        handle_provider=lambda: None,
        request_stop=lambda: None,
        send_nudge=lambda _text: None,
        interrupt=lambda: None,
        rate_limit=rate_limit,
        ledger_queue_name="taut_meta",
        driver_pid=123,
        driver_start_time="driver-start",
        audit_start_ts=0,
    )


def _install_policy(client: TautClient, reactor: SummonReactor) -> ControlPolicy:
    policy = ControlPolicy(
        client=client,
        reactor=reactor,
        member_id=client.whoami().member_id,
        provider="scripted",
        threads=("general",),
        handle_provider=lambda: None,
        request_stop=reactor.request_stop,
        send_nudge=lambda _text: None,
        interrupt=lambda: None,
        rate_limit=60,
        ledger_queue_name="taut_meta",
        driver_pid=123,
        driver_start_time="driver-start",
        audit_start_ts=0,
    )
    policy.install()
    reactor.control_queue_name = control_in_queue_name(policy._member_id)
    reactor.owner_turn = policy.turn
    return policy


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


class _RecordingReplyQueue:
    def __init__(self) -> None:
        self.closed = False
        self.writes: list[str] = []

    def write(self, body: str) -> None:
        self.writes.append(body)

    def close(self) -> None:
        self.closed = True


class _ReplyClient:
    def __init__(self, queue: _FailingReplyQueue | _RecordingReplyQueue) -> None:
        self.queue_obj = queue
        self.names: list[str] = []
        self.persistent_flags: list[object] = []

    def queue(
        self, name: str, *, persistent: bool | None = None
    ) -> _FailingReplyQueue | _RecordingReplyQueue:
        self.names.append(name)
        self.persistent_flags.append(persistent)
        return self.queue_obj


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


def test_status_snapshot_never_reads_session_ledger() -> None:
    loop = _make_policy(rate_limit=60)
    loop._ledger = cast(Queue, _ExplodingLedger())

    fields = loop._status_snapshot().as_fields()

    assert "session_id" not in fields
    assert fields["driver"] == "alive"


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
    assert caught.value.__cause__ is not caught.value


def test_rate_audit_does_not_layer_retry_over_peek_many_failure() -> None:
    loop = _make_policy(rate_limit=60)
    queue = _FlakyPeekQueue()

    with pytest.raises(OperationalError, match="locked"):
        loop._audit_thread("general", cast(Queue, queue), cutoff=100)

    assert queue.calls == 1
    assert list(loop._own_posts) == []
    assert loop._audit_cursor.get("general") is None


def test_rate_audit_uses_plain_queue_peek_many_once() -> None:
    loop = _make_policy(rate_limit=60)
    queue = _RecordingPeekQueue()

    loop._audit_thread("general", cast(Queue, queue), cutoff=0)

    assert queue.calls == [{"with_timestamps": True, "after_timestamp": 0}]
    assert list(loop._own_posts) == [9]
    assert loop._audit_cursor["general"] == 9


def test_rate_audit_excludes_old_backlog_at_inclusive_hybrid_cutoff() -> None:
    loop = _make_policy(rate_limit=60)

    loop._audit_thread("general", cast(Queue, _BacklogPeekQueue()), 100)

    assert list(loop._own_posts) == [100, 101]
    assert loop._audit_cursor["general"] == 101


def test_rate_audit_derives_one_cutoff_from_public_broker_timestamp() -> None:
    class TimestampQueue:
        calls = 0

        def generate_timestamp(self) -> int:
            self.calls += 1
            return int(control_module._RATE_WINDOW_SECONDS * 1_000_000_000) + 100

    loop = _make_policy(rate_limit=60)
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

    loop = _make_policy(rate_limit=60)
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


def _assert_stop_error_reply(
    replies: list[tuple[dict[str, Any], str | None]],
    *,
    request_id: str,
    reply_to: str,
    causal_fragments: tuple[str, ...],
) -> None:
    assert len(replies) == 1
    payload, observed_reply_to = replies[0]
    assert observed_reply_to == reply_to
    assert set(payload) == {"command", "status", "error", "request_id"}
    assert payload["command"] == "STOP"
    assert payload["status"] == "error"
    assert payload["request_id"] == request_id
    error = str(payload["error"])
    for fragment in causal_fragments:
        assert fragment in error


@pytest.mark.parametrize(
    ("outcome", "causal_fragments"),
    [
        (
            StopShutdownOutcome(
                release_confirmed=True,
                teardown_error="PTY child cleanup failed",
            ),
            ("teardown", "PTY child cleanup failed"),
        ),
        (
            StopShutdownOutcome(
                release_confirmed=False,
                release_error="database is locked",
            ),
            ("release", "database is locked"),
        ),
        (
            StopShutdownOutcome(
                release_confirmed=False,
                teardown_error="PTY write failed",
                release_error="database is locked",
            ),
            ("teardown", "PTY write failed", "release", "database is locked"),
        ),
        (
            StopShutdownOutcome(
                release_confirmed=False,
                teardown_error="PTY write failed",
            ),
            ("teardown", "PTY write failed", "release", "confirm"),
        ),
    ],
)
def test_stop_replies_with_structured_finalized_shutdown_failure(
    outcome: StopShutdownOutcome,
    causal_fragments: tuple[str, ...],
) -> None:
    loop = _make_policy(rate_limit=60)
    loop._pending_stop = "req-exact-shutdown-error"
    loop._pending_stop_seen = True
    loop._pending_stop_reply_to = "sys.rsp_exact_shutdown_error"
    replies: list[tuple[dict[str, Any], str | None]] = []
    dynamic_loop = cast(Any, loop)
    dynamic_loop._reply = lambda body, *, reply_to: replies.append(
        (json.loads(body), reply_to)
    )

    loop.finish_stop(outcome)

    _assert_stop_error_reply(
        replies,
        request_id="req-exact-shutdown-error",
        reply_to="sys.rsp_exact_shutdown_error",
        causal_fragments=causal_fragments,
    )


def test_rate_breaker_rearms_after_flood_subsides() -> None:
    # [SUM-10] circuit-breaker: hard breach is not one-shot. Once the rate
    # falls back under the limit the breaker re-arms and can trip again.
    loop = _make_policy(rate_limit=2)
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


def test_queue_names_derive_from_member_id() -> None:
    assert control_in_queue_name("m_abc123") == "sys.ctl_m_abc123"
    assert control_out_queue_name("m_abc123") == "sys.rsp_m_abc123"


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


def test_control_policy_has_no_independent_drive_or_wait() -> None:
    assert not issubclass(ControlPolicy, BaseReactor)
    for name in (
        "run",
        "start",
        "wait_for_activity",
        "_open",
        "_reopen_broker_handles",
    ):
        assert not hasattr(ControlPolicy, name)
    for name in ("process_once", "wait_for_activity", "stop", "cleanup"):
        assert getattr(SummonReactor, name) is getattr(BaseReactor, name)


def test_control_pending_commands_wait_for_same_owner_turn_and_remain_ordered(
    tmp_path: Path,
) -> None:
    db = tmp_path / ".taut.db"
    TautClient.init(db_path=db)
    client = TautClient(db_path=db, as_name="bot")
    client.join("general")
    reactor = client.watch(lambda _: None, watcher_type=SummonReactor)
    assert isinstance(reactor, SummonReactor)
    reactor.delivery_enabled = False
    policy = _install_policy(client, reactor)
    seen: list[str] = []
    active = False

    def dispatch(body: str) -> None:
        nonlocal active
        assert not active
        active = True
        seen.append(body)
        active = False

    cast(Any, policy)._dispatch = dispatch
    try:
        with Queue(control_in_queue_name(policy._member_id), db_path=str(db)) as source:
            source.write("one")
            source.write("two")
        assert seen == []
        reactor.process_once()
        reactor.process_once()
        assert seen == ["one", "two"]
        assert policy._reactor is reactor
    finally:
        reactor.stop(join=False)
        client.close()


def test_control_policy_correlated_ping_is_serviced_while_injection_blocks(
    tmp_path: Path,
) -> None:
    db = tmp_path / ".taut.db"
    TautClient.init(db_path=db)
    client = TautClient(db_path=db, as_name="bot")
    peer = TautClient(db_path=db, as_name="human")
    client.join("general")
    peer.join("general")
    entered = threading.Event()
    release = threading.Event()

    class BlockingInjection:
        def inject(self, _text: str) -> None:
            entered.set()
            assert release.wait(3)

        def request_close(self) -> None:
            release.set()

    reactor = client.watch(lambda _: None, watcher_type=SummonReactor)
    assert isinstance(reactor, SummonReactor)
    reactor.prepare_delivery = lambda _item: PreparedInjection(
        cast(Any, BlockingInjection()), "input", 0
    )
    policy = _install_policy(client, reactor)
    reply_name = "sys.rsp_test_blocked"
    try:
        message = peer.say("general", "keep this cursor pending")
        reactor.process_once()
        assert entered.wait(2)
        assert reactor._cursors["general"] < message.ts
        with Queue(control_in_queue_name(policy._member_id), db_path=str(db)) as source:
            source.write(
                encode_control_command(
                    "PING",
                    "correlated",
                    reply_to=reply_name,
                    driver_pid=123,
                    driver_start_time="driver-start",
                )
            )
        reactor.wait_for_activity(0.2)
        reactor.process_once()
        with Queue(reply_name, db_path=str(db)) as replies:
            payload = json.loads(cast(str, replies.read_one()))
        assert payload["request_id"] == "correlated"
        assert payload["message"] == "PONG"
        assert reactor._cursors["general"] < message.ts
    finally:
        release.set()
        reactor.stop(join=False)
        client.close()
        peer.close()


@pytest.mark.parametrize("command", ["STOP", "STATUS", "PING"])
def test_stale_command_for_old_driver_evidence_is_dropped(command: str) -> None:
    policy = _make_policy(60)
    stops: list[bool] = []
    replies: list[str] = []
    policy._request_stop = lambda: stops.append(True)
    cast(Any, policy)._reply = lambda body, **_kwargs: replies.append(body)
    policy._dispatch(
        encode_control_command(
            command, "old", driver_pid=1, driver_start_time="old-driver"
        )
    )
    assert stops == [] and replies == []
    assert not policy._pending_stop_seen


def test_stop_reply_is_deferred_until_explicit_final_outcome() -> None:
    policy = _make_policy(60)
    stops: list[bool] = []
    replies: list[dict[str, Any]] = []
    policy._request_stop = lambda: stops.append(True)
    cast(Any, policy)._reply = lambda body, **_kwargs: replies.append(json.loads(body))
    policy._dispatch(
        encode_control_command(
            "STOP", "stop-1", driver_pid=123, driver_start_time="driver-start"
        )
    )
    assert stops == [True]
    assert replies == []
    policy.finish_stop(StopShutdownOutcome(release_confirmed=True))
    assert replies == [{"command": "STOP", "status": "ack", "request_id": "stop-1"}]


def test_stop_unconfirmed_release_is_error_not_ack() -> None:
    policy = _make_policy(60)
    replies: list[dict[str, Any]] = []
    policy._pending_stop_seen = True
    policy._pending_stop = "unconfirmed"
    cast(Any, policy)._reply = lambda body, **_kwargs: replies.append(json.loads(body))
    policy.finish_stop(StopShutdownOutcome(release_confirmed=False))
    assert replies[0]["status"] == "error"
    assert "confirm" in replies[0]["error"]


@pytest.mark.parametrize(
    "error", [OperationalError("database is locked"), ValueError("programming failure")]
)
def test_control_source_failure_returns_to_single_owner_without_policy_retry(
    error: Exception,
) -> None:
    policy = _make_policy(60)
    with pytest.raises(type(error)) as caught:
        policy._handle_control_error(error, "body", 1)
    assert caught.value is error


def test_control_audit_clock_runs_only_when_due() -> None:
    policy = _make_policy(60)
    audits: list[bool] = []
    cast(Any, policy)._audit_pass = lambda: audits.append(True)
    policy._next_rate_audit_at = float("inf")
    policy.turn()
    assert audits == []
    policy._next_rate_audit_at = 0
    policy.turn()
    policy.turn()
    assert audits == [True]


def test_rate_audit_reconciles_real_memberships_without_moving_chat_cursor(
    tmp_path: Path,
) -> None:
    db = tmp_path / ".taut.db"
    TautClient.init(db_path=db)
    client = TautClient(db_path=db, as_name="bot")
    client.join("general")
    reactor = client.watch(lambda _: None, watcher_type=SummonReactor)
    assert isinstance(reactor, SummonReactor)
    policy = _install_policy(client, reactor)
    # Membership belongs to the watcher. Drive its normal retained cache hint
    # while delivery is disabled, so auditing cannot move the chat cursor.
    reactor.delivery_enabled = False
    fixed_sources = set(reactor._owned_fixed_queues)
    try:
        client.join("late")
        written = client.say("late", "own rate evidence")
        prior_cursor = client._state.get_membership(
            thread="late", member_id=policy._member_id
        )
        reactor.process_once()
        policy._audit_pass()
        assert "late" in policy._thread_queues
        assert written.ts in policy._own_posts_seen
        assert (
            client._state.get_membership(thread="late", member_id=policy._member_id)
            == prior_cursor
        )
        client.leave("late")
        reactor.process_once()
        policy._audit_pass()
        assert "late" not in policy._thread_queues
        client.join("late")
        reactor.process_once()
        policy._audit_pass()
        assert "late" in policy._thread_queues
        assert list(policy._own_posts).count(written.ts) == 1
        assert set(reactor._owned_fixed_queues) == fixed_sources
        assert policy._thread_queues["late"] is reactor.get_queue("late")
    finally:
        reactor.stop(join=False)
        client.close()


@pytest.mark.parametrize("failures", [1, 3])
def test_control_reply_failure_is_local_to_request_and_closes_handle(
    failures: int, caplog: pytest.LogCaptureFixture
) -> None:
    policy = _make_policy(60)
    for _ in range(failures):
        queue = _FailingReplyQueue(OperationalError("database is locked"))
        client = _ReplyClient(queue)
        policy._client = cast(Any, client)
        policy._reply(encode_control_reply("PING", "ok", request_id="req"))
        assert queue.closed
        assert queue.writes == 1
        assert client.persistent_flags == [False]
    policy._client = cast(Any, SimpleNamespace(list_threads=lambda **kwargs: []))
    fields = policy._status_snapshot().as_fields()
    assert "control_health" not in fields
    assert "health_detail" not in fields
    assert len(caplog.records) == failures
    assert all("control reply skipped" in record.message for record in caplog.records)
    reply_queue = _RecordingReplyQueue()
    policy._client = cast(Any, _ReplyClient(reply_queue))
    policy._reply(encode_control_reply("PING", "ok", request_id="next"))
    assert reply_queue.closed
    assert len(reply_queue.writes) == 1


def test_control_client_retries_status_with_same_reply_route(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(control_module, "_CONTROL_REQUEST_RETRY_INTERVAL_SECONDS", 0.01)
    db = tmp_path / "retry.db"
    requests: list[dict[str, Any]] = []

    def respond(body: str, *_args: Any) -> None:
        payload = json.loads(body)
        requests.append(payload)
        if len(requests) == 2:
            with Queue(payload["reply_to"], db_path=str(db)) as reply:
                reply.write(
                    encode_control_reply(
                        "STATUS", "ok", request_id=payload["request_id"]
                    )
                )
            responder.request_stop()

    responder = BaseReactor({"sys.ctl_m_abc": {"handler": respond}}, db=db)
    thread = responder.start()
    client = ControlClient(
        lambda name: Queue(name, db_path=str(db)),
        "m_abc",
        driver_pid=123,
        driver_start_time="driver-start",
    )
    try:
        reply = client.request("STATUS", timeout=2)
        assert reply is not None and reply["status"] == "ok"
        assert len(requests) == 2
        assert requests[0]["request_id"] == requests[1]["request_id"]
        assert requests[0]["reply_to"] == requests[1]["reply_to"]
        assert requests[0]["driver_pid"] == 123
        assert requests[0]["driver_start_time"] == "driver-start"
    finally:
        client.close()
        responder.stop()
        thread.join(2)
    assert not thread.is_alive()


def test_control_client_can_borrow_request_queue_and_close_transient_reply(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = tmp_path / "borrowed.db"
    request = Queue("sys.ctl_m_abc", db_path=str(db), persistent=True)
    reply_queues: list[Queue] = []
    closed: list[Queue] = []
    original_close = Queue.close

    def close(queue: Queue) -> None:
        closed.append(queue)
        original_close(queue)

    def replies(name: str) -> Queue:
        queue = Queue(name, db_path=str(db), persistent=False)
        reply_queues.append(queue)
        return queue

    monkeypatch.setattr(Queue, "close", close)
    client = ControlClient(
        lambda _: request,
        "m_abc",
        reply_queue_factory=replies,
        owns_request_queue=False,
    )
    try:
        assert client.request("STOP", timeout=0.02) is None
        client.close()
        assert request not in closed
        assert len(reply_queues) == 1 and reply_queues[0] in closed
        assert request.read_one() is not None
        request.write("still owned by caller")
        assert request.read_one() == "still owned by caller"
    finally:
        request.close()


def test_control_client_does_not_retry_stop_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(control_module, "_CONTROL_REQUEST_RETRY_INTERVAL_SECONDS", 0.01)
    db = tmp_path / "stop-once.db"
    client = ControlClient(
        lambda name: Queue(name, db_path=str(db)),
        "m_abc",
        driver_pid=123,
        driver_start_time="driver-start",
    )
    try:
        assert client.request("STOP", timeout=0.08) is None
        with Queue("sys.ctl_m_abc", db_path=str(db)) as requests:
            rows = requests.peek_many()
        assert len(rows) == 1
        assert json.loads(rows[0])["command"] == "STOP"
    finally:
        client.close()


def test_control_registration_precedes_initial_readiness(tmp_path: Path) -> None:
    db = tmp_path / "ready.db"
    TautClient.init(db_path=db)
    client = TautClient(db_path=db, as_name="bot")
    client.join("general")
    reactor = client.watch(lambda _: None, watcher_type=SummonReactor)
    assert isinstance(reactor, SummonReactor)
    reactor.prepare_delivery = lambda _item: None
    policy = _install_policy(client, reactor)
    ready = threading.Event()
    reactor.notify_ready_after_initial_drain(ready)
    try:
        assert not ready.is_set()
        assert reactor.get_queue(control_in_queue_name(policy._member_id)) is not None
        reactor.process_once()
        assert ready.is_set()
    finally:
        reactor.stop(join=False)
        client.close()


@pytest.mark.parametrize(
    "error",
    [
        OperationalError("database is locked"),
        ValueError("audit implementation failure"),
    ],
)
def test_audit_failure_reaches_owner_without_policy_reopen(error: Exception) -> None:
    policy = _make_policy(60)
    policy._next_rate_audit_at = 0

    def fail() -> None:
        raise error

    cast(Any, policy)._audit_pass = fail
    with pytest.raises(type(error)) as caught:
        policy.turn()
    assert caught.value is error


def test_reserved_status_collision_is_not_mislabeled_as_broker_fault() -> None:
    from taut_summon._adapter import AdapterError

    policy = _make_policy(60)
    policy._handle_provider = lambda: cast(
        Any, SimpleNamespace(status_fields=lambda: {"provider": "forged"})
    )
    with pytest.raises(AdapterError, match="reserved STATUS key"):
        policy._status_fields()
