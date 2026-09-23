"""Owner-boundary proofs replacing removed peer-watcher handshakes."""

from __future__ import annotations

import queue
import signal
import sqlite3
import subprocess
import sys
import threading
import time
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import psutil
import pytest
from simplebroker.ext import OperationalError
from taut_summon import _driver as module
from taut_summon._adapter import ActivityEvent, ExitEvent
from taut_summon._control import ControlPolicy
from taut_summon._driver import (
    DriverError,
    _BootstrapResult,
    _GenerationAttachDecision,
    _PhaseResult,
)
from taut_summon._state import capture_driver_evidence
from test_driver import _new_driver, _run_request

from taut import TautClient


def _owner(summon_db: Path) -> Any:
    client = TautClient(db_path=str(summon_db), as_name="owner")
    client.join("general")
    member = client.last_created_member
    assert member is not None and member.token is not None
    client.close()
    driver = _new_driver(_run_request())
    driver._db_path = str(summon_db)
    driver._owner_boot = _BootstrapResult(
        member.member_id, "owner", member.token, "scripted"
    )
    driver._pending_nudge = None
    driver._owner_control = None
    driver._owner_client = None
    driver._owner_phase = "listen"
    driver._harness_restart_at = 0.0
    driver._owner_readiness_at = time.monotonic() + 30
    driver._owner_running = None
    driver._owner_last_activity = 0.0
    driver._owner_crashes = 0
    driver._owner_first = True
    driver._owner_availability = None
    driver._owner_attach = _GenerationAttachDecision(True, False)
    driver._owner_adapter = type("Adapter", (), {"supports_attach": False})()
    driver._phase_worker = None
    driver._phase_result = None
    driver._phase_results = queue.SimpleQueue()
    driver._pump_results = queue.SimpleQueue()
    driver._evidence = capture_driver_evidence()
    return driver


@pytest.mark.parametrize("boundary", ["watch", "install"])
def test_partial_source_acquisition_closes_all_created_owners(
    summon_db: Path,
    monkeypatch: pytest.MonkeyPatch,
    boundary: str,
) -> None:
    driver = _owner(summon_db)
    closed: list[object] = []
    original_close = TautClient.close

    def close(client: TautClient) -> None:
        closed.append(client)
        original_close(client)

    monkeypatch.setattr(TautClient, "close", close)

    def fail(*_args: Any, **_kwargs: Any) -> None:
        raise OperationalError("source setup failed")

    if boundary == "watch":
        monkeypatch.setattr(TautClient, "watch", fail)
    else:
        monkeypatch.setattr(ControlPolicy, "install", fail)
    with pytest.raises(OperationalError, match="source setup failed"):
        driver._open_owner_source()
    assert closed
    assert driver._watcher is None


def test_control_policy_uses_the_driver_owned_source(summon_db: Path) -> None:
    driver = _owner(summon_db)
    client, source = driver._open_owner_source()
    try:
        policy = driver._owner_control
        assert policy._client is client
        assert policy._reactor is source
        assert source.get_queue(source.control_queue_name) is not None
    finally:
        source.stop(join=False)
        client.close()


def test_successful_spawn_result_remains_owned_after_acceptance_failure(
    summon_db: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    driver = _owner(summon_db)
    calls: list[str] = []

    class Handle:
        def request_close(self) -> None:
            calls.append("request-close")

        def close(self) -> None:
            calls.append("close")

    handle = Handle()

    def rejoin(_handle: object, _boot: object) -> None:
        raise RuntimeError("acceptance failed")

    monkeypatch.setattr(driver, "_rejoin", rejoin)
    driver._phase_results.put(_PhaseResult("spawn", handle, None))
    with pytest.raises(RuntimeError, match="acceptance failed"):
        driver._apply_phase_result()
    assert driver._phase_result is not None
    assert driver._owner_running.handle is handle
    driver._close_owner_generation()
    assert calls == ["request-close", "close"]
    assert driver._active_generation is None


def test_pump_start_failure_retains_handle_for_cleanup(
    summon_db: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    driver = _owner(summon_db)
    closed: list[str] = []

    class Handle:
        def request_close(self) -> None:
            closed.append("request")

        def close(self) -> None:
            closed.append("close")

    handle = Handle()
    monkeypatch.setattr(
        driver, "_should_start_pump_before_bootstrap", lambda *_args, **_kw: True
    )

    def fail(*_args: object) -> None:
        raise RuntimeError("pump thread unavailable")

    monkeypatch.setattr(driver, "_start_generation_pump", fail)
    with pytest.raises(RuntimeError, match="pump thread unavailable"):
        driver._accept_spawn(cast(Any, handle))
    driver._close_owner_generation()
    assert closed == ["request", "close"]


def test_terminal_unwind_owns_spawn_result_before_acceptance(summon_db: Path) -> None:
    driver = _owner(summon_db)
    closed: list[bool] = []

    class Handle:
        def close(self) -> None:
            closed.append(True)

    driver._start_phase_operation("spawn", Handle)
    driver._phase_worker.join(2)
    driver._close_owner_generation()
    assert closed == [True]


def test_transport_pump_has_no_broker_client_and_owner_rejects_stale_results(
    summon_db: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    driver = _owner(summon_db)
    stale = driver._activate_generation()
    current = driver._activate_generation()

    class Handle:
        def events(self) -> Any:
            yield ActivityEvent("output")
            yield ExitEvent(13)

    def forbidden(*_args: Any, **_kwargs: Any) -> None:
        pytest.fail("transport worker constructed a Taut client")

    monkeypatch.setattr(module, "TautClient", forbidden)
    thread = threading.Thread(
        target=driver._pump, args=(stale, Handle(), None, "unused")
    )
    thread.start()
    thread.join(2)
    assert not thread.is_alive()
    driver._apply_pump_results()
    assert current.exit.returncode is None
    assert not driver._harness_dead.is_set()


def test_cancelled_delivery_does_not_mark_provider_dead(summon_db: Path) -> None:
    from taut_summon._adapter import AdapterWriteCancelled

    driver = _owner(summon_db)
    driver._owner_delivery_error(AdapterWriteCancelled("cancelled"))
    assert not driver._harness_dead.is_set()


def test_original_readiness_deadline_survives_cancellation(summon_db: Path) -> None:
    driver = _owner(summon_db)
    driver._on_ready = lambda _handle: pytest.fail("ready after deadline")
    driver._owner_readiness_at = time.monotonic() - 1
    with pytest.raises(DriverError, match="startup deadline"):
        driver._check_owner_readiness_deadline()
    assert driver._shutdown.is_set()


@pytest.mark.parametrize("signum", [signal.SIGINT, signal.SIGTERM])
def test_signal_under_event_lock_only_publishes_pending_owner_intent(
    signum: int,
) -> None:
    script = """
import signal, threading
from taut_summon._driver import SummonDriver
from taut.watcher import BaseReactor
from simplebroker.watcher import PollingStrategy
r = object.__new__(BaseReactor)
event = threading.Event()
r._strategy = PollingStrategy(event)
d = object.__new__(SummonDriver)
d._signal_pending = False
d._watcher = r
d._shutdown = event
signal.signal(SIGNUM, d._on_signal)
with event._cond:
    signal.raise_signal(SIGNUM)
assert d._signal_pending
r._strategy.wait_for_activity(timeout=0.01)
assert r._strategy.consume_local_activity_hint()
print("pending-only")
""".replace("SIGNUM", str(int(signum)))
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "pending-only"


def test_harness_restart_deadline_gates_acceptance_and_chat_but_not_stop(
    summon_db: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    driver = _owner(summon_db)
    driver._harness_restart_at = time.monotonic() + 30
    client, reactor = driver._open_owner_source()
    accepted: list[bool] = []
    monkeypatch.setattr(driver, "_apply_phase_result", lambda: accepted.append(True))
    try:
        assert not reactor.delivery_enabled
        driver._owner_turn()
        assert accepted == []
        assert driver._owner_wait_timeout() > 20
        driver._signal_pending = True
        driver._owner_turn()
        assert accepted == [True]
        assert driver._shutdown.is_set()
    finally:
        reactor.stop(join=False)
        client.close()


def test_rate_audit_reuses_only_managed_chat_sources(summon_db: Path) -> None:
    driver = _owner(summon_db)
    client, reactor = driver._open_owner_source()
    try:
        fixed = tuple(reactor._owned_fixed_queues)
        for index in range(25):
            name = f"audit{index}"
            client.join(name)
            reactor._refresh_memberships()
            driver._owner_control._reconcile_audit_threads()
            assert name in driver._owner_control._thread_queues
            client.leave(name)
            reactor._refresh_memberships()
            driver._owner_control._reconcile_audit_threads()
            assert name not in driver._owner_control._thread_queues
        assert tuple(reactor._owned_fixed_queues) == fixed
    finally:
        reactor.stop(join=False)
        client.close()


def test_native_close_failure_is_preserved_in_stop_outcome(summon_db: Path) -> None:
    driver = _owner(summon_db)
    failure = RuntimeError("native close failed")
    driver._shutdown.set()
    driver._phase_results.put(_PhaseResult("close", None, failure))
    with pytest.raises(RuntimeError, match="native close failed"):
        driver._apply_phase_result()
    driver._release_confirmed = True
    driver._finalize_stop_shutdown_outcome()
    assert "native close failed" in driver._control_shutdown_outcome().error_detail()


def test_terminal_cleanup_preserves_primary_and_records_shutdown_failure(
    summon_db: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    driver = _owner(summon_db)
    primary = RuntimeError("broker primary")
    cleanup = RuntimeError("native retirement failed")

    def fail() -> None:
        raise cleanup

    monkeypatch.setattr(driver, "_retire_owner_generation", fail)
    with pytest.raises(RuntimeError, match="broker primary") as caught:
        try:
            raise primary
        finally:
            driver._close_owner_generation()
    assert caught.value is primary
    assert driver._shutdown_error is cleanup
    assert any("native retirement failed" in note for note in primary.__notes__)


def test_readiness_clock_starts_after_orientation_once(
    summon_db: Path,
) -> None:
    driver = _owner(summon_db)
    driver._owner_readiness_at = None
    driver._on_ready = lambda _handle: None
    driver._check_owner_readiness_deadline()
    client, reactor = driver._open_owner_source()
    try:
        driver._listen_owner_turn(reactor)
        deadline = driver._owner_readiness_at
        assert deadline is not None and deadline > time.monotonic()
        driver._listen_owner_turn(reactor)
        assert driver._owner_readiness_at == deadline
    finally:
        reactor.stop(join=False)
        client.close()


@pytest.mark.parametrize("cleanup_fails", [False, True])
def test_real_broker_read_failure_ends_driver_and_releases_owners(
    summon_db: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    cleanup_fails: bool,
) -> None:
    from conftest import _session_row
    from simplebroker.ext import BrokerError

    scenario = tmp_path / "scenario.json"
    scenario.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("TAUT_SUMMON_SCENARIO", str(scenario))
    monkeypatch.setenv("TAUT_SUMMON_RECEIVED_LOG", str(tmp_path / "received.jsonl"))
    driver = _new_driver(
        replace(_run_request(detach=True), name="scripted"), db_path=str(summon_db)
    )
    sources: list[Any] = []
    handles: list[Any] = []
    original_open = driver._open_owner_source

    def open_source() -> Any:
        # Count attempted acquisition too: a failed reopen is still a second owner.
        sources.append(None)
        assert len(sources) == 1, "driver attempted to replace its central event source"
        client, reactor = original_open()
        sources[-1] = reactor
        if cleanup_fails:
            original_stop = reactor.stop
            original_close = client.close

            def stop(**kwargs: Any) -> None:
                original_stop(**kwargs)
                raise RuntimeError("source cleanup failed")

            def close() -> None:
                original_close()
                raise RuntimeError("client cleanup failed")

            monkeypatch.setattr(reactor, "stop", stop)
            monkeypatch.setattr(client, "close", close)
        return client, reactor

    def corrupt_after_ready(_run_handle: Any) -> None:
        handles.append(driver._handle)
        # Remove a real broker relation after startup. The next actual control
        # read fails in SimpleBroker, not in a patched broker-free callback.
        with sqlite3.connect(summon_db) as connection:
            connection.execute("DROP TABLE messages")
        assert driver._watcher is not None
        driver._watcher.notify_activity()

    monkeypatch.setattr(driver, "_open_owner_source", open_source)
    driver._on_ready = corrupt_after_ready
    driver._run_completion = threading.Event()
    with pytest.raises(BrokerError, match="messages") as caught:
        driver._run()
    if cleanup_fails:
        assert any("source cleanup failed" in note for note in caught.value.__notes__)
    assert len(sources) == 1
    assert sources[0]._resources_closed
    assert driver._watcher is None
    assert driver._owner_running is None
    assert driver._active_generation is None
    assert handles and not psutil.pid_exists(handles[0].pid)
    assert driver._owned_clients == []
    assert driver._owner_client is not None
    assert driver._owner_client._session is None
    assert driver._owner_client._queue_cache == {}
    assert driver._member_id is not None
    row = _session_row(summon_db, driver._member_id)
    assert row is not None and row["driver_pid"] is None


def test_source_install_failure_preserves_primary_and_attempts_all_cleanup(
    summon_db: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from taut_summon._reactor import SummonReactor

    from taut.watcher import BaseReactor

    driver = _owner(summon_db)
    primary = OperationalError("control install failed")
    calls: list[str] = []
    original_stop = SummonReactor.stop
    original_close = TautClient.close

    def install(_policy: ControlPolicy) -> None:
        raise primary

    def stop(source: SummonReactor, **kwargs: Any) -> None:
        calls.append("stop")
        original_stop(source, **kwargs)
        raise RuntimeError("source stop failed")

    def close(client: TautClient) -> None:
        calls.append("close")
        original_close(client)
        raise RuntimeError("client close failed")

    monkeypatch.setattr(ControlPolicy, "install", install)
    monkeypatch.setattr(BaseReactor, "stop", stop)
    monkeypatch.setattr(TautClient, "close", close)
    with pytest.raises(OperationalError, match="control install failed") as caught:
        driver._open_owner_source()
    assert caught.value is primary
    assert calls == ["stop", "close"]
    assert driver._watcher is None
    assert any("source stop failed" in note for note in primary.__notes__)
    assert any("client close failed" in note for note in primary.__notes__)


@pytest.mark.parametrize("phase", ["orientation", "nudge"])
def test_owner_interrupt_retires_cancelled_phase_without_failing_run(
    summon_db: Path,
    phase: str,
) -> None:
    from taut_summon._adapter import AdapterWriteCancelled

    driver = _owner(summon_db)
    started = threading.Event()
    cancel = threading.Event()
    interrupt_entered = threading.Event()
    release_interrupt = threading.Event()

    class Handle:
        def interrupt(self) -> None:
            interrupt_entered.set()
            cancel.set()
            assert release_interrupt.wait(5)

    def inject() -> None:
        started.set()
        assert cancel.wait(5)
        raise AdapterWriteCancelled("owner cancelled write")

    driver._handle = Handle()
    driver._start_phase_operation(phase, inject)
    assert started.wait(5)
    # An owner interrupt must return while the native interrupt is still blocked.
    release = threading.Timer(1, release_interrupt.set)
    release.start()
    try:
        before = time.monotonic()
        driver._owner_interrupt()
        assert time.monotonic() - before < 0.5
        assert interrupt_entered.wait(5)
        release_interrupt.set()
        driver._phase_worker.join(5)
        driver._interrupt_worker.join(5)
        for _ in range(2):
            driver._apply_phase_result()
        assert driver._phase_worker is None
        assert driver._interrupt_worker is None
        assert driver._owner_phase == "listen"
    finally:
        cancel.set()
        release_interrupt.set()
        release.cancel()
        driver._phase_worker and driver._phase_worker.join(5)


def test_unrequested_phase_cancellation_remains_failure(summon_db: Path) -> None:
    from taut_summon._adapter import AdapterWriteCancelled

    driver = _owner(summon_db)
    with pytest.raises(AdapterWriteCancelled):
        driver._handle_phase_failure(
            _PhaseResult("nudge", None, AdapterWriteCancelled("unexpected"))
        )


def test_windows_native_interrupt_write_keeps_control_live_and_stop_retires_it(
    summon_db: Path,
) -> None:
    import json

    from simplebroker import Queue
    from taut_summon._control import control_in_queue_name, encode_control_command
    from taut_summon._pty_windows import _EpochWriter
    from taut_summon._win32_io import ERROR_OPERATION_ABORTED, Win32IoError

    driver = _owner(summon_db)
    entered = threading.Event()
    cancelled = threading.Event()
    closed: list[int] = []

    class Api:
        def open_current_thread(self) -> int:
            return threading.get_native_id()

        def write(self, _handle: int, payload: bytes) -> None:
            assert payload == b"\x03"
            if not entered.is_set():
                entered.set()
                assert cancelled.wait(5)
                raise Win32IoError("cancelled", ERROR_OPERATION_ABORTED)

        def cancel_thread(self, _handle: int, *, retiring: bool = False) -> bool:
            cancelled.set()
            return True

        def close_handle(self, handle: int) -> None:
            closed.append(handle)

    writer = _EpochWriter(cast(Any, Api()), 41)
    driver._handle = writer
    client, source = driver._open_owner_source()
    try:
        driver._owner_control = None
        driver._owner_interrupt()
        assert entered.wait(5)
        worker = driver._interrupt_worker
        assert worker is not None and worker.is_alive()
        # Same broker owner serves a correlated PING while native Ctrl-C waits.
        with Queue(
            control_in_queue_name(driver._owner_boot.member_id), db_path=str(summon_db)
        ) as commands:
            commands.write(
                encode_control_command(
                    "PING",
                    "blocked-interrupt",
                    reply_to="sys.interrupt_reply",
                    driver_pid=driver._evidence[0],
                    driver_start_time=driver._evidence[1],
                )
            )
        before = time.monotonic()
        source.process_once()
        assert time.monotonic() - before < 0.5
        with Queue("sys.interrupt_reply", db_path=str(summon_db)) as replies:
            reply = json.loads(cast(str, replies.read_one()))
        assert reply["request_id"] == "blocked-interrupt"
        assert reply["message"] == "PONG"
        with Queue(
            control_in_queue_name(driver._owner_boot.member_id),
            db_path=str(summon_db),
        ) as commands:
            commands.write(
                encode_control_command(
                    "STOP",
                    "stop-interrupt",
                    reply_to="sys.interrupt_reply",
                    driver_pid=driver._evidence[0],
                    driver_start_time=driver._evidence[1],
                )
            )
        source.wait_for_activity(0.2)
        source.process_once()
        assert driver._shutdown.is_set()
        driver._close_owner_generation()
        assert not worker.is_alive()
        writer.finish_close_request()
        assert len(closed) == 2
    finally:
        cancelled.set()
        writer.request_close()
        writer.finish_close_request()
        source.stop(join=False)
        client.close()


def test_phase_join_failure_still_retires_interrupt_and_provider(
    summon_db: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    driver = _owner(summon_db)
    release = threading.Event()
    entered = threading.Event()
    retired: list[str] = []

    class Handle:
        def interrupt(self) -> None:
            entered.set()
            assert release.wait(5)

        def request_close(self) -> None:
            release.set()

        def close(self) -> None:
            retired.append("provider")

    handle = Handle()
    driver._handle = handle
    driver._owner_running = module._RunningGeneration(
        time.monotonic(), cast(Any, handle), driver._activate_generation(), None
    )
    driver._start_phase_operation("nudge", lambda: None)
    worker = driver._phase_worker
    worker.join(5)
    driver._owner_interrupt()
    interrupt = driver._interrupt_worker
    assert entered.wait(5)

    def fail_join(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("phase join failed")

    monkeypatch.setattr(worker, "join", fail_join)
    with pytest.raises(RuntimeError, match="phase join failed"):
        driver._close_owner_generation()
    assert not interrupt.is_alive()
    assert retired == ["provider"]
    assert driver._active_generation is None
