"""TUI extension Summon worker, exact-run, and terminal-lease behavior.

Spec references:
- docs/specs/10-taut-tui.md [TUI-11], [TUI-12.3]
"""

from __future__ import annotations

import json
import sys
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from threading import Event, Lock, Thread
from typing import Any, cast

import pytest
from _summon_completion import LeaseOrStop, ProviderConsumption, SummonObservations
from tests.helpers.terminal_probe import HostTerminal

pytestmark = pytest.mark.sqlite_only


@pytest.fixture(autouse=True)
def _observe_summon_apps(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Preinstall exact per-app observations before any startup or action."""
    from taut_tui.app import TautApp

    original = TautApp.__init__
    observations: list[SummonObservations] = []

    def initialize(app: Any, *args: Any, **kwargs: Any) -> None:
        original(app, *args, **kwargs)
        probe = SummonObservations(app, monkeypatch)
        app._summon_test_observations = probe
        observations.append(probe)

    monkeypatch.setattr(TautApp, "__init__", initialize)
    try:
        yield
    finally:
        for probe in observations:
            probe.close()


def test_request_completion_retains_the_real_first_resolution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from _completion import CompletionScope
    from _summon_completion import request_phase
    from taut_summon import TerminalAttachNotice

    from taut_tui.summon import TerminalAttachConfirmationRequest

    request = TerminalAttachConfirmationRequest(
        TerminalAttachNotice(member="member", provider="scripted", detach_hint="x")
    )
    callbacks: list[bool | None] = []
    request.set_on_resolved(lambda: callbacks.append(request.decision))
    with CompletionScope() as scope:
        resolved = request_phase(scope, monkeypatch, request, "resolved")
        deadline = scope.now() + 2
        request.resolve(True)
        request.resolve(False)
        assert (
            resolved.wait_sync(deadline=deadline, description="first decision") is True
        )
        assert callbacks == [True]
        assert request.decision is True


def test_request_completion_preserves_failure_and_late_disposal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from _completion import CompletionScope
    from _summon_completion import request_phase
    from taut_summon import TerminalAttachNotice

    from taut_tui.summon import TerminalAttachConfirmationRequest

    request = TerminalAttachConfirmationRequest(
        TerminalAttachNotice(member="member", provider="scripted", detach_hint="x")
    )
    error = ValueError("request failed")
    with CompletionScope() as scope:
        resolved = request_phase(scope, monkeypatch, request, "resolved")
        deadline = scope.now() + 2
        request.fail(error)
        with pytest.raises(ValueError) as caught:
            resolved.wait_sync(deadline=deadline, description="failed decision")
        assert caught.value is error
    request.resolve(True)
    assert request.error is error


def test_request_completion_preserves_competing_resolve_and_fail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from threading import Barrier

    from _completion import CompletionScope
    from _summon_completion import request_phase
    from taut_summon import TerminalAttachNotice

    from taut_tui.summon import TerminalAttachConfirmationRequest

    request = TerminalAttachConfirmationRequest(
        TerminalAttachNotice(member="member", provider="scripted", detach_hint="x")
    )
    error = ValueError("competing failure")
    callbacks: list[tuple[bool | None, BaseException | None]] = []
    request.set_on_resolved(lambda: callbacks.append((request.decision, request.error)))
    contenders = (
        lambda: request.resolve(True),
        lambda: request.resolve(False),
        lambda: request.fail(error),
    )
    ready = Barrier(len(contenders) + 1)
    failures: list[BaseException] = []

    def compete(action: Callable[[], None]) -> None:
        try:
            ready.wait(timeout=2)
            action()
        except BaseException as failure:  # noqa: BLE001 - retain test thread outcome
            failures.append(failure)

    with CompletionScope() as scope:
        resolved = request_phase(scope, monkeypatch, request, "resolved")
        workers = [
            Thread(target=compete, args=(action,), daemon=True) for action in contenders
        ]
        deadline = scope.now() + 2
        try:
            for worker in workers:
                worker.start()
            ready.wait(timeout=max(0, deadline - scope.now()))
            for worker in workers:
                worker.join(timeout=max(0, deadline - scope.now()))
            assert not any(worker.is_alive() for worker in workers)
            assert failures == []
            assert callbacks == [(request.decision, request.error)]
            if request.error is not None:
                with pytest.raises(ValueError) as caught:
                    resolved.wait_sync(
                        deadline=deadline, description="competing result"
                    )
                assert caught.value is error is request.error
            else:
                assert (
                    resolved.wait_sync(
                        deadline=deadline, description="competing result"
                    )
                    is request.decision
                )
            outcome = resolved.snapshot()
            request.resolve(True)
            request.fail(RuntimeError("late losing failure"))
            assert resolved.snapshot() is outcome
            assert callbacks == [(request.decision, request.error)]
        finally:
            ready.abort()
            for worker in workers:
                worker.join(timeout=2)
                assert not worker.is_alive()


def test_confirmation_completion_does_not_drive_the_pilot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio

    from taut_summon import TerminalAttachNotice
    from textual.widgets import Button

    from taut_tui.app import TautApp
    from taut_tui.summon import TerminalAttachConfirmationRequest

    async def exercise() -> None:
        app = TautApp(db_path=None, as_name=None, continuity_token=None)
        async with app.run_test() as pilot:

            async def forbidden_pause(*args: Any, **kwargs: Any) -> None:
                raise AssertionError("completion observer must not drive the pilot")

            monkeypatch.setattr(pilot, "pause", forbidden_pause)
            request = TerminalAttachConfirmationRequest(
                TerminalAttachNotice(
                    member="member", provider="scripted", detach_hint="x"
                )
            )
            deadline = time.monotonic() + 2
            app.post_message(request)
            screen = await _pushed_confirmation(pilot, app, deadline=deadline)
            assert screen.query_one("#confirmation-confirm", Button).is_mounted
            request.resolve(False)

    asyncio.run(exercise())


@pytest.mark.parametrize("ready_before_start_return", [False, True])
def test_owned_run_completion_ignores_other_tokens_and_futures(
    monkeypatch: pytest.MonkeyPatch, ready_before_start_return: bool
) -> None:
    import asyncio
    from concurrent.futures import Future

    from taut_tui.app import TautApp
    from taut_tui.summon import OwnedSummonRun, TuiSummonOperations

    allow_ready = Event()

    class HeldController(_Controller):
        def run_foreground(self, *args: Any, **kwargs: Any) -> None:
            assert allow_ready.wait(5)
            super().run_foreground(*args, **kwargs)

    async def exercise() -> None:
        app = TautApp(db_path=None, as_name=None, continuity_token=None)
        probe: SummonObservations = cast(Any, app)._summon_test_observations
        probe.observe_owned_run()
        controller = HeldController()
        if ready_before_start_return:
            allow_ready.set()
            original_submit = TuiSummonOperations._submit_foreground

            def submit(owner: Any, run: Any) -> Any:
                future = original_submit(owner, run)
                assert controller.started.wait(5)
                app._accept_summon_ready_from_worker(
                    OwnedSummonRun("early-stale", False, "other", "other")
                )
                return future

            monkeypatch.setattr(TuiSummonOperations, "_submit_foreground", submit)
        async with app.run_test():
            operations = TuiSummonOperations(
                controller=controller,
                ready_callback=app._accept_summon_ready_from_worker,
            )
            app._summon = operations
            try:
                request = object()
                token, future = operations.start(request, object())
                origin_before_stale = probe.ready_started_at
                assert (origin_before_stale is not None) is ready_before_start_return
                unrelated = OwnedSummonRun("stale", False, "other", "other")
                app._accept_summon_ready_from_worker(unrelated)
                app._apply_summon_ready(unrelated)
                other: Future[None] = Future()
                other.set_result(None)
                app._apply_summon_return("stale", other)
                app._apply_summon_return(token, other)
                assert probe.ready is not None and probe.ready.snapshot() is None
                assert probe.returned is not None and probe.returned.snapshot() is None
                assert probe.ready_started_at == origin_before_stale

                app._owned_summon_tokens.add(token)
                deadline = probe.scope.now() + 5
                allow_ready.set()
                run = await probe.ready.wait(
                    deadline=deadline, description="exact ready"
                )
                assert run.token == token
                first_handoff = probe.ready_started_at
                assert first_handoff is not None
                controller.release.set()
                finished = probe.scope.observe_future(
                    future, owner=operations, phase="test.worker_returned"
                )
                await finished.wait(
                    deadline=deadline, description="exact worker returned"
                )
                app._apply_summon_return(token, future)
                returned_token, returned_future = await probe.returned.wait(
                    deadline=deadline, description="exact return applied"
                )
                assert returned_token == token and returned_future is future
                assert probe.ready_started_at == first_handoff
            finally:
                allow_ready.set()
                controller.release.set()
                operations.close()

    asyncio.run(exercise())


class _Member:
    def __init__(self, name: str) -> None:
        self.member_id = f"id-{name}"
        self.name = name
        self.provider = "scripted"


class _Handle:
    def __init__(self, name: str) -> None:
        self.member = _Member(name)
        self.stop_requests = 0
        self.stop_requested = Event()

    def request_stop(self) -> None:
        self.stop_requests += 1
        self.stop_requested.set()


class _Controller:
    def __init__(self) -> None:
        self.started = Event()
        self.release = Event()
        self.handle = _Handle("actual-auto-name")
        self.signal_flags: list[bool] = []

    def provider_names(self) -> tuple[str, ...]:
        return ("scripted",)

    def list_live(self) -> tuple[object, ...]:
        return ()

    def status(self, name: str) -> object:
        return ("status", name)

    def stop(self, name: str) -> object:
        return ("stop", name)

    def run_foreground(
        self,
        request: object,
        interaction: object,
        *,
        install_signal_handlers: bool,
        on_ready: object,
    ) -> None:
        del request, interaction
        self.signal_flags.append(install_signal_handlers)
        assert callable(on_ready)
        on_ready(self.handle)
        self.started.set()
        assert self.release.wait(5)


def test_owned_run_tracks_exact_ready_handle_and_never_installs_signals() -> None:
    from taut_tui.summon import TuiSummonOperations

    controller = _Controller()
    operations = TuiSummonOperations(controller=controller)
    try:
        token, worker = operations.start(object(), object())
        assert controller.started.wait(5)
        owned = operations.owned_runs()
        assert len(owned) == 1
        assert owned[0].token == token
        assert owned[0].member_name == "actual-auto-name"
        assert owned[0].pending is False
        assert controller.signal_flags == [False]
        assert operations.quit_block_reason() is not None

        operations.request_owned_stops()
        assert controller.handle.stop_requests == 1
        controller.release.set()
        assert worker.result(timeout=5) is None
        assert operations.owned_runs() == ()
        assert operations.quit_block_reason() is None
    finally:
        controller.release.set()
        operations.close()


def test_pending_owned_run_blocks_quit_until_readiness_or_return() -> None:
    from taut_tui.summon import TuiSummonOperations

    ready_gate = Event()

    class PendingController(_Controller):
        def run_foreground(
            self,
            request: object,
            interaction: object,
            *,
            install_signal_handlers: bool,
            on_ready: object,
        ) -> None:
            ready_gate.wait(5)
            super().run_foreground(
                request,
                interaction,
                install_signal_handlers=install_signal_handlers,
                on_ready=on_ready,
            )

    controller = PendingController()
    operations = TuiSummonOperations(controller=controller)
    try:
        _token, worker = operations.start(object(), object())
        assert operations.owned_runs()[0].pending is True
        assert "starting" in (operations.quit_block_reason() or "")
        ready_gate.set()
        assert controller.started.wait(5)
        controller.release.set()
        worker.result(timeout=5)
    finally:
        ready_gate.set()
        controller.release.set()
        operations.close()


def test_control_work_is_not_starved_by_eight_blocked_foreground_runs() -> None:
    from taut_tui.summon import TuiSummonOperations

    class SaturatingController(_Controller):
        def __init__(self) -> None:
            super().__init__()
            self.start_count = 0
            self.start_lock = Lock()
            self.all_started = Event()

        def run_foreground(
            self,
            request: object,
            interaction: object,
            *,
            install_signal_handlers: bool,
            on_ready: object,
        ) -> None:
            del request, interaction, install_signal_handlers, on_ready
            with self.start_lock:
                self.start_count += 1
                if self.start_count == 8:
                    self.all_started.set()
            assert self.release.wait(5)

    controller = SaturatingController()
    operations = TuiSummonOperations(controller=controller)
    workers = [operations.start(object(), object())[1] for _ in range(8)]
    try:
        assert controller.all_started.wait(5)
        assert operations.submit_status("agent").result(timeout=1) == (
            "status",
            "agent",
        )
        assert operations.submit_stop("agent").result(timeout=1) == (
            "stop",
            "agent",
        )
    finally:
        controller.release.set()
        for worker in workers:
            worker.result(timeout=5)
        operations.close()


def test_close_before_readiness_stops_late_handle_without_ready_callback() -> None:
    from taut_tui.summon import OwnedSummonRun, TuiSummonOperations

    class LateReadyController(_Controller):
        def __init__(self) -> None:
            super().__init__()
            self.awaiting_readiness = Event()
            self.publish_readiness = Event()
            self.stop_seen = False

        def run_foreground(
            self,
            request: object,
            interaction: object,
            *,
            install_signal_handlers: bool,
            on_ready: object,
        ) -> None:
            del request, interaction, install_signal_handlers
            assert callable(on_ready)
            self.awaiting_readiness.set()
            assert self.publish_readiness.wait(5)
            on_ready(self.handle)
            self.stop_seen = self.handle.stop_requested.wait(1)

    ready_updates: list[OwnedSummonRun] = []
    controller = LateReadyController()
    operations = TuiSummonOperations(
        controller=controller,
        ready_callback=ready_updates.append,
    )
    try:
        _token, worker = operations.start(object(), object())
        assert controller.awaiting_readiness.wait(5)

        operations.close()
        controller.publish_readiness.set()
        assert worker.result(timeout=5) is None

        assert controller.stop_seen is True
        assert controller.handle.stop_requests == 1
        assert ready_updates == []
    finally:
        controller.publish_readiness.set()
        operations.close()


def test_owned_exit_waits_exact_worker_and_reports_completion() -> None:
    from taut_tui.summon import TuiSummonOperations

    controller = _Controller()
    operations = TuiSummonOperations(controller=controller)
    try:
        token, worker = operations.start(object(), object())
        assert controller.started.wait(5)
        shutdown = operations.stop_owned_and_wait(timeout=5)
        assert controller.handle.stop_requested.wait(5)
        assert controller.handle.stop_requests == 1
        controller.release.set()
        assert worker.result(timeout=5) is None
        result = shutdown.result(timeout=5)
        assert result.complete is True
        assert result.completed_tokens == (token,)
        assert result.unresolved == ()
        assert result.errors == ()
    finally:
        controller.release.set()
        operations.close()


def test_pending_owned_exit_is_not_treated_as_stoppable_ready_run() -> None:
    from taut_tui.summon import TuiSummonOperations

    ready_gate = Event()

    class PendingController(_Controller):
        def run_foreground(
            self,
            request: object,
            interaction: object,
            *,
            install_signal_handlers: bool,
            on_ready: object,
        ) -> None:
            ready_gate.wait(5)
            super().run_foreground(
                request,
                interaction,
                install_signal_handlers=install_signal_handlers,
                on_ready=on_ready,
            )

    controller = PendingController()
    operations = TuiSummonOperations(controller=controller)
    try:
        _token, worker = operations.start(object(), object())
        assert operations.has_pending_owned() is True
        result = operations.stop_owned_and_wait(timeout=0.01).result(timeout=5)
        assert result.complete is False
        assert len(result.unresolved) == 1
        assert result.unresolved[0].pending is True
        ready_gate.set()
        assert controller.started.wait(5)
        controller.release.set()
        worker.result(timeout=5)
    finally:
        ready_gate.set()
        controller.release.set()
        operations.close()


def test_absent_summon_has_one_install_hint() -> None:
    from taut_tui.summon import SummonUnavailable, load_summon_api

    def missing(_name: str) -> object:
        raise ModuleNotFoundError("No module named 'taut_summon'", name="taut_summon")

    with pytest.raises(SummonUnavailable, match="taut-summon"):
        load_summon_api(import_module=missing)


def test_scoped_log_bridge_restores_namespace_logger() -> None:
    import logging

    from taut_tui.summon import SummonLogBridge

    logger = logging.getLogger("taut_summon")
    prior_handlers = list(logger.handlers)
    prior_level = logger.level
    prior_propagate = logger.propagate
    records: list[str] = []
    bridge = SummonLogBridge(records.append)
    try:
        bridge.install()
        logging.getLogger("taut_summon.driver").warning("bad\x1b]0;title\x07")
        assert records
        assert "\x1b" not in records[-1]
    finally:
        bridge.restore()

    assert logger.handlers == prior_handlers
    assert logger.level == prior_level
    assert logger.propagate == prior_propagate


def test_overlapping_log_bridges_restore_out_of_order_without_stale_owner() -> None:
    import logging

    from taut_tui.summon import SummonLogBridge

    logger = logging.getLogger("taut_summon")
    prior_handlers = list(logger.handlers)
    prior_level = logger.level
    prior_propagate = logger.propagate
    first_records: list[str] = []
    second_records: list[str] = []
    first = SummonLogBridge(first_records.append)
    second = SummonLogBridge(second_records.append)
    first_installed = Event()
    second_installed = Event()
    restore_first = Event()
    restore_second = Event()

    def hold_scope(
        bridge: SummonLogBridge,
        installed: Event,
        restore: Event,
    ) -> None:
        bridge.install()
        installed.set()
        restore.wait(5)
        bridge.restore()

    first_thread = Thread(
        target=hold_scope,
        args=(first, first_installed, restore_first),
    )
    second_thread = Thread(
        target=hold_scope,
        args=(second, second_installed, restore_second),
    )
    try:
        first_thread.start()
        assert first_installed.wait(5)
        second_thread.start()
        assert second_installed.wait(5)

        restore_first.set()
        first_thread.join(timeout=5)
        assert not first_thread.is_alive()
        logging.getLogger("taut_summon.driver").warning("second remains active")
        assert first_records == []
        assert second_records == ["second remains active"]

        restore_second.set()
        second_thread.join(timeout=5)
        assert not second_thread.is_alive()
        assert logger.handlers == prior_handlers
        assert logger.level == prior_level
        assert logger.propagate == prior_propagate
    finally:
        restore_first.set()
        restore_second.set()
        if first_thread.ident is not None:
            first_thread.join(timeout=5)
        if second_thread.ident is not None:
            second_thread.join(timeout=5)
        first.restore()
        second.restore()
        logger.handlers = prior_handlers
        logger.setLevel(prior_level)
        logger.propagate = prior_propagate


def test_controller_queries_run_off_caller_thread() -> None:
    from taut_tui.summon import TuiSummonOperations

    controller = _Controller()
    operations = TuiSummonOperations(controller=controller)
    try:
        assert operations.submit_list().result(timeout=5) == ()
        assert operations.submit_status("agent").result(timeout=5) == (
            "status",
            "agent",
        )
        assert operations.submit_stop("agent").result(timeout=5) == (
            "stop",
            "agent",
        )
    finally:
        operations.close()


def test_native_request_builder_populates_every_public_field() -> None:
    from taut_summon import SummonRequest

    from taut_tui.summon import TuiSummonOperations

    controller = _Controller()
    operations = TuiSummonOperations(controller=controller)
    try:
        request = operations.build_request(
            name="reviewer",
            threads=("dev", "ops"),
            persona="careful",
            system_prompt_file="prompt.txt",
            rate_limit=12,
            attach=True,
            detach=False,
            provider_flag="scripted",
            takeover=True,
        )
    finally:
        operations.close()

    assert request == SummonRequest(
        name="reviewer",
        threads=("dev", "ops"),
        persona="careful",
        system_prompt_file="prompt.txt",
        rate_limit=12,
        attach=True,
        detach=False,
        provider_flag="scripted",
        takeover=True,
    )


class _LeaseApp:
    def __init__(
        self,
        *,
        accept: bool = True,
        confirmation_decision: bool | None = True,
    ) -> None:
        self.accept = accept
        self.confirmation_decision = confirmation_decision
        self.messages: list[Any] = []
        self.confirmation_posted = Event()
        self.suspended = Event()
        self.restored = Event()
        self.refreshed = Event()
        self._handler: Thread | None = None

    @contextmanager
    def suspend(self) -> Any:
        self.suspended.set()
        try:
            yield
        finally:
            self.restored.set()

    def refresh(self, *, layout: bool) -> None:
        assert layout is True
        self.refreshed.set()

    def post_message(self, message: Any) -> bool:
        if not self.accept:
            return False
        from taut_tui.summon import TerminalAttachConfirmationRequest

        self.messages.append(message)
        if isinstance(message, TerminalAttachConfirmationRequest):
            self.confirmation_posted.set()
            if self.confirmation_decision is not None:
                message.resolve(self.confirmation_decision)
            return True
        self._handler = Thread(target=message.hold, args=(self,))
        self._handler.start()
        return True

    def join_handler(self) -> None:
        if self._handler is not None:
            self._handler.join(timeout=5)
            assert not self._handler.is_alive()


def _confirm_attach(interaction: Any) -> None:
    from taut_summon import TerminalAttachNotice

    assert interaction.confirm_terminal_attach(
        TerminalAttachNotice(
            member="grok",
            provider="grok",
            detach_hint="Ctrl-\\ Ctrl-\\",
        )
    )


def test_terminal_attach_confirmation_is_exclusive_and_precedes_lease(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from taut_summon import (
        TerminalAttachNotice,
        TerminalAvailability,
        TerminalIntent,
    )

    from taut_tui import summon as tui_summon

    monkeypatch.setattr(tui_summon, "_standard_terminal_is_suitable", lambda: True)
    app = _LeaseApp(confirmation_decision=None)
    interaction = tui_summon.TuiSummonInteraction(app, timeout=2.0)
    lease_granted = Event()
    leave_lease = Event()
    failures: list[BaseException] = []

    def run() -> None:
        try:
            assert interaction.confirm_terminal_attach(
                TerminalAttachNotice(
                    member="grok",
                    provider="grok",
                    detach_hint="Ctrl-\\ Ctrl-\\",
                )
            )
            with interaction.terminal_lease():
                lease_granted.set()
                assert leave_lease.wait(timeout=2.0)
        except BaseException as exc:  # noqa: BLE001 approved [DOM-10.2.1] [RUFF-SUP-070] exception
            failures.append(exc)

    worker = Thread(target=run, daemon=True)
    deadline = time.monotonic() + 2.0
    worker.start()
    try:
        assert app.confirmation_posted.wait(max(0.0, deadline - time.monotonic()))
        assert len(app.messages) == 1
        request = app.messages[0]
        assert isinstance(request, tui_summon.TerminalAttachConfirmationRequest)
        assert not app.suspended.is_set()
        assert (
            interaction.terminal_availability(TerminalIntent.PREFERRED)
            is TerminalAvailability.UNAVAILABLE
        )
        assert interaction.confirm_terminal_attach(request.notice) is False
        with (
            pytest.raises(RuntimeError, match="not acknowledged by this worker"),
            interaction.terminal_lease(),
        ):
            pass
        assert len(app.messages) == 1

        request.resolve(True)
        assert lease_granted.wait(timeout=2.0)
        assert app.suspended.is_set()
        assert len(app.messages) == 2
    finally:
        leave_lease.set()
        worker.join(timeout=5.0)
        app.join_handler()
    assert not worker.is_alive()
    assert failures == []
    assert app.restored.is_set()


def test_terminal_lease_ownership_survives_distinct_driver_phase_threads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """[TUI-11.3] ownership follows one run, not a recycled thread id."""

    from taut_summon import TerminalAttachNotice

    from taut_tui import summon as tui_summon

    monkeypatch.setattr(tui_summon, "_standard_terminal_is_suitable", lambda: True)
    app = _LeaseApp(confirmation_decision=True)
    interaction = tui_summon.TuiSummonInteraction(app, timeout=2.0)
    operation = interaction.operation_scope()
    decisions: list[bool] = []
    confirmation_done = Event()
    keep_confirmation_thread = Event()

    def confirm_on_first_phase() -> None:
        decisions.append(
            operation.confirm_terminal_attach(
                TerminalAttachNotice(
                    member="grok",
                    provider="grok",
                    detach_hint="Ctrl-\\ Ctrl-\\",
                )
            )
        )
        confirmation_done.set()
        assert keep_confirmation_thread.wait(timeout=2.0)

    confirmation = Thread(
        target=confirm_on_first_phase,
        daemon=True,
    )
    deadline = time.monotonic() + 2.0
    confirmation.start()
    assert confirmation_done.wait(max(0.0, deadline - time.monotonic()))
    assert decisions == [True]
    assert confirmation.is_alive()

    leased = Event()

    def lease_on_later_phase() -> None:
        with operation.terminal_lease():
            leased.set()

    lease = Thread(target=lease_on_later_phase, daemon=True)
    lease.start()
    lease.join(timeout=2.0)
    app.join_handler()
    keep_confirmation_thread.set()
    confirmation.join(timeout=2.0)
    assert not confirmation.is_alive()
    assert not lease.is_alive()
    assert leased.is_set()
    assert app.restored.is_set()
    operation.release_current_worker()
    operation.release_current_worker()
    with pytest.raises(RuntimeError, match="operation is closed"):
        operation.supports_setup_recovery()


def test_owned_run_uses_and_releases_one_operation_interaction_scope() -> None:
    from taut_tui.summon import TuiSummonOperations

    released = Event()

    class Scope:
        def release_current_worker(self) -> None:
            released.set()

    scope = Scope()

    class Interaction:
        def operation_scope(self) -> Scope:
            return scope

    class CapturingController(_Controller):
        def run_foreground(
            self,
            request: object,
            interaction: object,
            *,
            install_signal_handlers: bool,
            on_ready: object,
        ) -> None:
            del request, on_ready
            assert interaction is scope
            assert install_signal_handlers is False

    operations = TuiSummonOperations(controller=CapturingController())
    try:
        _token, worker = operations.start(object(), Interaction())
        assert worker.result(timeout=2.0) is None
        assert released.is_set()
    finally:
        operations.close()


def test_terminal_attach_confirmation_close_and_post_failure_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from taut_summon import TerminalAttachNotice

    from taut_tui import summon as tui_summon

    monkeypatch.setattr(tui_summon, "_standard_terminal_is_suitable", lambda: True)
    notice = TerminalAttachNotice(
        member="grok",
        provider="grok",
        detach_hint="Ctrl-\\ Ctrl-\\",
    )
    app = _LeaseApp(confirmation_decision=None)
    interaction = tui_summon.TuiSummonInteraction(app, timeout=2.0)
    decisions: list[bool] = []
    worker = Thread(
        target=lambda: decisions.append(interaction.confirm_terminal_attach(notice)),
        daemon=True,
    )
    deadline = time.monotonic() + 2.0
    worker.start()
    assert app.confirmation_posted.wait(max(0.0, deadline - time.monotonic()))
    assert len(app.messages) == 1

    interaction.close()
    worker.join(timeout=2.0)
    assert not worker.is_alive()
    assert decisions == [False]
    assert not app.suspended.is_set()

    rejected = _LeaseApp(accept=False)
    recoverable = tui_summon.TuiSummonInteraction(rejected, timeout=0.1)
    with pytest.raises(RuntimeError, match="not accepting attach confirmations"):
        recoverable.confirm_terminal_attach(notice)
    rejected.accept = True
    assert recoverable.confirm_terminal_attach(notice) is True
    recoverable.release_current_worker()


def test_tui_interaction_declares_setup_recovery_support() -> None:
    from taut_tui import summon as tui_summon

    # [TUI-11.1]: the TUI presents the same native acknowledgement for a
    # [SUM-7.4] setup-recovery offer arriving outside the bootstrap window.
    interaction = tui_summon.TuiSummonInteraction(object(), timeout=0.1)
    assert interaction.supports_setup_recovery() is True


def test_host_shutdown_requests_the_run_stop_before_refusing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """[TUI-11.3] a shutdown-produced refusal takes the [SUM-7.4] shutdown class.

    The driver reads its own shutdown event immediately after a ``False``
    acknowledgement, so the stop request must already be visible there.
    """

    from taut_summon import TerminalAttachNotice

    from taut_tui import summon as tui_summon

    monkeypatch.setattr(tui_summon, "_standard_terminal_is_suitable", lambda: True)
    app = _LeaseApp(confirmation_decision=None)
    interaction = tui_summon.TuiSummonInteraction(app, timeout=2.0)
    shutdown = Event()
    observed: list[tuple[bool, bool]] = []
    notice = TerminalAttachNotice(
        member="kimi",
        provider="kimi",
        detach_hint="Ctrl-\\ Ctrl-\\",
        screen_excerpt="Trust this folder?",
    )

    def worker() -> None:
        decision = interaction.confirm_terminal_attach(notice, cancel=shutdown)
        observed.append((decision, shutdown.is_set()))

    thread = Thread(target=worker, daemon=True)
    deadline = time.monotonic() + 2.0
    thread.start()
    assert app.confirmation_posted.wait(max(0.0, deadline - time.monotonic()))
    assert len(app.messages) == 1

    interaction.close()
    thread.join(timeout=5.0)
    assert not thread.is_alive()
    assert observed == [(False, True)]

    # A request that arrives after teardown is refused the same way.
    late = Event()
    assert interaction.confirm_terminal_attach(notice, cancel=late) is False
    assert late.is_set()


def test_successful_confirmation_leaves_no_cancel_thread() -> None:
    """A normal answer must not retain a cancellation waiter."""

    import threading

    from taut_summon import TerminalAttachNotice

    from taut_tui.summon import TerminalAttachConfirmationRequest, TuiSummonInteraction

    def cancel_threads() -> list[threading.Thread]:
        return [
            thread
            for thread in threading.enumerate()
            if thread.name == "taut-tui-attach-cancel" and thread.is_alive()
        ]

    def notice() -> TerminalAttachNotice:
        return TerminalAttachNotice(
            member="kimi",
            provider="kimi",
            detach_hint="Ctrl-\\ Ctrl-\\",
        )

    before = len(cancel_threads())
    for _ in range(5):
        request = TerminalAttachConfirmationRequest(notice())
        entered = Event()
        real_wait = request.resolved.wait

        def wait(
            timeout: float | None = None,
            *,
            real_wait: Callable[..., bool] = real_wait,
            entered: Event = entered,
        ) -> bool:
            entered.set()
            return bool(real_wait(timeout))

        request.resolved.wait = wait  # type: ignore[method-assign]

        def answer(
            request: TerminalAttachConfirmationRequest = request,
            entered: Event = entered,
        ) -> None:
            assert entered.wait(2)
            request.resolve(True)

        Thread(target=answer, daemon=True).start()
        TuiSummonInteraction._wait_for_confirmation(request, Event())
        assert request.decision is True
    assert len(cancel_threads()) == before


def test_foreground_return_releases_confirmed_prelease_reservation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from taut_summon import (
        TerminalAttachNotice,
        TerminalAvailability,
        TerminalIntent,
    )

    from taut_tui import summon as tui_summon

    class FailingAfterConfirmationController(_Controller):
        def run_foreground(
            self,
            request: object,
            interaction: object,
            *,
            install_signal_handlers: bool,
            on_ready: object,
        ) -> None:
            del request, install_signal_handlers, on_ready
            assert interaction.confirm_terminal_attach(  # type: ignore[attr-defined]
                TerminalAttachNotice(
                    member="grok",
                    provider="grok",
                    detach_hint="Ctrl-\\ Ctrl-\\",
                )
            )
            raise RuntimeError("provider failed before lease")

    monkeypatch.setattr(tui_summon, "_standard_terminal_is_suitable", lambda: True)
    app = _LeaseApp()
    interaction = tui_summon.TuiSummonInteraction(app, timeout=1.0)
    operations = tui_summon.TuiSummonOperations(
        controller=FailingAfterConfirmationController()
    )
    try:
        _token, worker = operations.start(object(), interaction)
        with pytest.raises(RuntimeError, match="provider failed before lease"):
            worker.result(timeout=5.0)
        assert (
            interaction.terminal_availability(TerminalIntent.PREFERRED)
            is TerminalAvailability.AVAILABLE
        )
    finally:
        operations.close()


def test_terminal_lease_handoff_is_exclusive_and_restores(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from taut_summon import TerminalAvailability, TerminalIntent

    from taut_tui import summon as tui_summon

    monkeypatch.setattr(tui_summon, "_standard_terminal_is_suitable", lambda: True)
    app = _LeaseApp()
    bridge_records: list[str] = []
    bridge = tui_summon.SummonLogBridge(bridge_records.append)
    interaction = tui_summon.TuiSummonInteraction(
        app,
        log_bridge=bridge,
        timeout=1.0,
    )

    assert (
        interaction.terminal_availability(TerminalIntent.PREFERRED)
        is TerminalAvailability.AVAILABLE
    )
    _confirm_attach(interaction)
    with interaction.terminal_lease() as lease:
        assert app.suspended.is_set()
        assert (lease.input_fd, lease.output_fd) == (0, 1)
        assert (
            interaction.terminal_availability(TerminalIntent.PREFERRED)
            is TerminalAvailability.UNAVAILABLE
        )
        bridge.accept("buffered")
        assert bridge_records == []

    app.join_handler()
    assert app.restored.is_set()
    assert app.refreshed.is_set()
    assert bridge_records == ["buffered"]
    assert (
        interaction.terminal_availability(TerminalIntent.PREFERRED)
        is TerminalAvailability.AVAILABLE
    )


def test_terminal_lease_rejected_post_fails_fast_and_recovers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from taut_tui import summon as tui_summon

    monkeypatch.setattr(tui_summon, "_standard_terminal_is_suitable", lambda: True)
    app = _LeaseApp(accept=False)
    interaction = tui_summon.TuiSummonInteraction(app, timeout=0.01)

    app.accept = True
    _confirm_attach(interaction)
    app.accept = False
    with (
        pytest.raises(RuntimeError, match="not accepting"),
        interaction.terminal_lease(),
    ):
        pytest.fail("rejected lease body must not run")

    app.accept = True
    _confirm_attach(interaction)
    with interaction.terminal_lease():
        pass
    app.join_handler()


def test_terminal_suspension_failure_never_yields_and_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from taut_summon import TerminalAvailability, TerminalIntent

    from taut_tui import summon as tui_summon

    class BrokenSuspendApp(_LeaseApp):
        @contextmanager
        def suspend(self) -> Any:
            raise RuntimeError("cannot suspend")
            yield  # pragma: no cover - contextmanager shape only

    monkeypatch.setattr(tui_summon, "_standard_terminal_is_suitable", lambda: True)
    app = BrokenSuspendApp()
    interaction = tui_summon.TuiSummonInteraction(app, timeout=1.0)

    _confirm_attach(interaction)
    with (
        pytest.raises(RuntimeError, match="terminal suspension failed"),
        interaction.terminal_lease(),
    ):
        pytest.fail("a failed Textual suspension must never grant terminal fds")

    app.join_handler()
    assert (
        interaction.terminal_availability(TerminalIntent.REQUIRED)
        is TerminalAvailability.UNAVAILABLE
    )


def test_terminal_restoration_failure_is_visible_and_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from taut_summon import TerminalAvailability, TerminalIntent

    from taut_tui import summon as tui_summon

    class BrokenRefreshApp(_LeaseApp):
        def refresh(self, *, layout: bool) -> None:
            assert layout is True
            raise RuntimeError("cannot redraw")

    monkeypatch.setattr(tui_summon, "_standard_terminal_is_suitable", lambda: True)
    app = BrokenRefreshApp()
    interaction = tui_summon.TuiSummonInteraction(app, timeout=1.0)

    _confirm_attach(interaction)
    with (
        pytest.raises(RuntimeError, match="terminal lease failed"),
        interaction.terminal_lease(),
    ):
        pass

    app.join_handler()
    assert (
        interaction.terminal_availability(TerminalIntent.REQUIRED)
        is TerminalAvailability.UNAVAILABLE
    )

    granted_again = False
    with (
        pytest.raises(RuntimeError, match="unavailable after a failed lease"),
        interaction.terminal_lease(),
    ):
        granted_again = True
    assert granted_again is False


def test_terminal_availability_requires_supported_suspend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from taut_summon import TerminalAvailability, TerminalIntent

    from taut_tui import summon as tui_summon

    monkeypatch.setattr(tui_summon, "_standard_terminal_is_suitable", lambda: True)
    interaction = tui_summon.TuiSummonInteraction(object())

    assert (
        interaction.terminal_availability(TerminalIntent.REQUIRED)
        is TerminalAvailability.UNAVAILABLE
    )


# --- Slice 2 of docs/plans/2026-08-18-tui-deep-review-remediation-plan.md ---


class _ExitRecordingLeaseApp(_LeaseApp):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.exit_calls = 0

    def exit(self) -> None:
        self.exit_calls += 1


class _RaisingWait:
    """Stand-in for the release event whose wait is interrupted."""

    def __init__(self, error: BaseException) -> None:
        self._error = error

    def wait(self, timeout: float | None = None) -> bool:
        raise self._error

    def set(self) -> None:  # pragma: no cover - parity with Event
        return

    def is_set(self) -> bool:
        return False


def test_lease_exception_records_failure_and_exits_app_completely() -> None:
    """[TUI-11.3] exception exit from the suspend body is a fatal full exit."""

    from taut_tui.summon import TerminalLeaseRequest

    app = _ExitRecordingLeaseApp()
    request = TerminalLeaseRequest()
    interrupt = KeyboardInterrupt()
    request.release = _RaisingWait(interrupt)  # type: ignore[assignment]

    request.hold(app)

    assert request.error is interrupt
    assert request.restored.is_set()
    assert app.exit_calls == 1
    assert not app.refreshed.is_set()


def test_real_app_lease_suspension_failure_exits_instead_of_lingering(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A suspend failure inside the real handler exits the TUI completely."""

    import asyncio

    from _summon_completion import request_phase
    from textual.app import SuspendNotSupported

    from taut_tui.app import TautApp
    from taut_tui.summon import TerminalLeaseRequest

    async def exercise() -> None:
        app = TautApp(db_path=None, as_name=None, continuity_token=None)
        async with app.run_test(size=(100, 30)) as pilot:
            del pilot
            probe: SummonObservations = cast(Any, app)._summon_test_observations
            request = TerminalLeaseRequest()
            restored = request_phase(probe.scope, monkeypatch, request, "restored")
            assert app._task is not None
            exited = probe.scope.observe_future(app._task, owner=app, phase="app.run")
            deadline = probe.scope.now() + 5
            app.post_message(request)
            with pytest.raises(SuspendNotSupported) as caught:
                await restored.wait(
                    deadline=deadline, description="failed lease restored"
                )
            assert caught.value is request.error
            assert request.error is not None
            await exited.wait(deadline=deadline, description="failed lease app exit")
            assert not app.is_running

    asyncio.run(exercise())


def test_stale_or_shutdown_lease_request_never_suspends_or_exits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A lease request whose worker already gave up is refused inertly."""

    import asyncio

    from _summon_completion import request_phase

    from taut_tui.app import TautApp
    from taut_tui.summon import TerminalLeaseRequest

    async def exercise() -> None:
        app = TautApp(db_path=None, as_name=None, continuity_token=None)
        async with app.run_test(size=(100, 30)) as pilot:
            del pilot
            probe: SummonObservations = cast(Any, app)._summon_test_observations
            request = TerminalLeaseRequest()
            request.release.set()  # worker timed out and moved on
            restored = request_phase(probe.scope, monkeypatch, request, "restored")
            deadline = probe.scope.now() + 5
            app.post_message(request)
            with pytest.raises(
                RuntimeError, match="terminal lease request is stale"
            ) as caught:
                await restored.wait(
                    deadline=deadline, description="stale lease refused"
                )
            assert caught.value is request.error
            assert request.restored.is_set()
            assert request.error is not None
            assert app.is_running

    asyncio.run(exercise())


def test_pending_worker_cancelled_before_start_never_runs_controller() -> None:
    """Confirmed cancel-and-quit cancels workers that have not started."""

    from taut_tui.summon import TuiSummonOperations

    class NeverController(_Controller):
        def run_foreground(self, *args: object, **kwargs: object) -> None:
            raise AssertionError("cancelled pending worker must not start")

    captured: list[Any] = []

    class DeferredStart(TuiSummonOperations):
        def _submit_foreground(self, run: Any) -> Any:
            from concurrent.futures import Future

            future: Future[None] = Future()
            captured.append((run, future))
            return future

    controller = NeverController()
    operations = DeferredStart(controller=controller)
    try:
        _token, _worker = operations.start(object(), object())
        shutdown = operations.stop_owned_and_wait(timeout=1.0)
        ((run, future),) = captured
        future.set_running_or_notify_cancel()
        run()
        future.set_result(None)
        result = shutdown.result(timeout=5)
        assert result.complete is True
        assert operations.owned_runs() == ()
    finally:
        operations.close()


def test_foreground_worker_retains_keyboard_interrupt_on_returned_future() -> None:
    """The daemon worker settles its Future for control-flow exceptions."""

    from taut_tui.summon import TuiSummonOperations

    interrupt = KeyboardInterrupt("provider interrupted")

    class InterruptingController(_Controller):
        def run_foreground(self, *args: object, **kwargs: object) -> None:
            raise interrupt

    operations = TuiSummonOperations(controller=InterruptingController())
    try:
        _token, worker = operations.start(object(), object())
        with pytest.raises(KeyboardInterrupt) as captured:
            worker.result(timeout=5)
        assert captured.value is interrupt
        assert operations.owned_runs() == ()
    finally:
        operations.close()


@pytest.mark.parametrize("resolve_first", [False, True])
def test_attach_resolution_callback_is_race_safe_and_subordinate(
    resolve_first: bool,
) -> None:
    """Registration cannot miss resolution or replace its exact decision."""

    from taut_tui.summon import TerminalAttachConfirmationRequest

    class _Notice:
        member = "grok"
        provider = "grok"
        detach_hint = "Ctrl-\\ Ctrl-\\"
        screen_excerpt: str | None = None

    request = TerminalAttachConfirmationRequest(_Notice())
    calls: list[str] = []

    def broken_callback() -> None:
        calls.append("called")
        raise RuntimeError("presentation callback failed")

    if resolve_first:
        request.resolve(False)
    request.set_on_resolved(broken_callback)
    if not resolve_first:
        request.resolve(False)

    assert calls == ["called"]
    assert request.decision is False
    assert request.resolved.is_set()


def test_quit_with_pending_run_offers_cancel_and_quit_dialog() -> None:
    """[TUI-11.2] pending runs get the exit decision, not a dead-end error."""

    import asyncio
    from concurrent.futures import Future

    from taut_tui.app import TautApp
    from taut_tui.screens import ConfirmationScreen
    from taut_tui.summon import OwnedSummonShutdown

    class PendingStub:
        def __init__(self) -> None:
            self.stop_calls = 0

        def close(self) -> None:
            return

        def quit_block_reason(self) -> str:
            return "1 Summon run(s) still starting."

        def has_pending_owned(self) -> bool:
            return True

        def stop_owned_and_wait(self, **_kwargs: object) -> Future[OwnedSummonShutdown]:
            self.stop_calls += 1
            done: Future[OwnedSummonShutdown] = Future()
            done.set_result(
                OwnedSummonShutdown(completed_tokens=("t",), unresolved=(), errors=())
            )
            return done

    async def exercise() -> None:
        app = TautApp(db_path=None, as_name=None, continuity_token=None)
        stub = PendingStub()
        async with app.run_test(size=(100, 30)) as pilot:
            del pilot
            probe: SummonObservations = cast(Any, app)._summon_test_observations
            assert app._task is not None
            exited = probe.scope.observe_future(app._task, owner=app, phase="app.run")
            app._summon = stub  # type: ignore[assignment]
            deadline = probe.scope.now() + 5
            app.action_quit_tui()
            await probe.screens.ready(app.screen, deadline=deadline)
            assert isinstance(app.screen, ConfirmationScreen)
            deadline = probe.scope.now() + 5
            app.screen.action_confirm()
            await exited.wait(deadline=deadline, description="confirmed app exit")
            assert stub.stop_calls == 1

    asyncio.run(exercise())


def test_cancelled_attach_confirmation_dismisses_stale_dialog() -> None:
    """Worker-side resolution removes the lying confirmation modal."""

    import asyncio

    from taut_tui.app import TautApp
    from taut_tui.screens import ConfirmationScreen
    from taut_tui.summon import TerminalAttachConfirmationRequest

    class _Notice:
        member = "grok"
        provider = "grok"
        detach_hint = "Ctrl-\\ Ctrl-\\"
        screen_excerpt: str | None = None

    async def exercise() -> None:
        app = TautApp(db_path=None, as_name=None, continuity_token=None)
        async with app.run_test(size=(100, 30)) as pilot:
            request = TerminalAttachConfirmationRequest(_Notice())
            deadline = time.monotonic() + 5
            app.post_message(request)
            screen = await _pushed_confirmation(pilot, app, deadline=deadline)
            assert isinstance(app.screen, ConfirmationScreen)
            deadline = time.monotonic() + 5
            request.resolve(False)
            probe: SummonObservations = cast(Any, app)._summon_test_observations
            await probe.screens.retired(screen).wait(
                deadline=deadline, description="stale confirmation removed"
            )
            assert not isinstance(app.screen, ConfirmationScreen)
            assert app.is_running

    asyncio.run(exercise())


def test_cancelled_attach_dismiss_failure_cannot_replace_resolution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A deferred presentation failure stays subordinate to the decision."""

    import asyncio
    from concurrent.futures import Future

    from textual.await_complete import AwaitComplete

    from taut_tui import app as tui_app
    from taut_tui.screens import ConfirmationScreen
    from taut_tui.summon import TerminalAttachConfirmationRequest

    class _Notice:
        member = "grok"
        provider = "grok"
        detach_hint = "Ctrl-\\ Ctrl-\\"
        screen_excerpt: str | None = None

    dismiss_calls = 0
    dismiss_failure: Future[None] = Future()

    class FailingOnceConfirmation(ConfirmationScreen):
        def dismiss(self, result: bool | None = None) -> AwaitComplete:
            nonlocal dismiss_calls
            dismiss_calls += 1
            if dismiss_calls == 1:
                error = RuntimeError("dismiss failed")
                dismiss_failure.set_exception(error)
                raise error
            return super().dismiss(result)

    monkeypatch.setattr(tui_app, "ConfirmationScreen", FailingOnceConfirmation)

    async def exercise() -> None:
        app = tui_app.TautApp(db_path=None, as_name=None, continuity_token=None)
        async with app.run_test(size=(100, 30)) as pilot:
            probe: SummonObservations = cast(Any, app)._summon_test_observations
            failed = probe.scope.observe_future(
                dismiss_failure, owner=app, phase="confirmation.dismiss_failed"
            )
            request = TerminalAttachConfirmationRequest(_Notice())
            deadline = time.monotonic() + 5
            app.post_message(request)
            screen = await _pushed_confirmation(pilot, app, deadline=deadline)
            assert isinstance(app.screen, FailingOnceConfirmation)
            deadline = time.monotonic() + 5
            request.resolve(False)
            with pytest.raises(RuntimeError, match="dismiss failed"):
                await failed.wait(
                    deadline=deadline, description="subordinate dismissal failure"
                )
            assert dismiss_calls == 1
            assert request.decision is False
            assert request.resolved.is_set()
            assert app.is_running
            assert isinstance(app.screen, FailingOnceConfirmation)
            deadline = time.monotonic() + 5
            app.screen.dismiss(False)
            await probe.screens.retired(screen).wait(
                deadline=deadline, description="confirmation removed"
            )

    asyncio.run(exercise())


def test_attach_resolution_during_push_retries_failed_dismiss_schedule(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A resolve/push race cannot strand an already-decided modal."""

    import asyncio

    from taut_tui.app import TautApp
    from taut_tui.screens import ConfirmationScreen
    from taut_tui.summon import TerminalAttachConfirmationRequest

    class _Notice:
        member = "grok"
        provider = "grok"
        detach_hint = "Ctrl-\\ Ctrl-\\"
        screen_excerpt: str | None = None

    async def exercise() -> None:
        app = TautApp(db_path=None, as_name=None, continuity_token=None)
        async with app.run_test(size=(100, 30)) as pilot:
            del pilot
            probe: SummonObservations = cast(Any, app)._summon_test_observations
            request = TerminalAttachConfirmationRequest(_Notice())
            real_push_screen = app.push_screen
            real_call_later = app.call_later
            schedule_attempts = 0

            def flaky_call_later(callback: Any, *args: Any, **kwargs: Any) -> bool:
                nonlocal schedule_attempts
                if getattr(callback, "__name__", "") == "dismiss_stale":
                    schedule_attempts += 1
                    if schedule_attempts == 1:
                        raise RuntimeError("first schedule failed")
                return real_call_later(callback, *args, **kwargs)

            def resolving_push(
                screen: Any,
                callback: Any = None,
                wait_for_dismiss: bool = False,
                *,
                mode: str | None = None,
            ) -> Any:
                request.resolve(False)
                return cast(Any, real_push_screen)(
                    screen,
                    callback,
                    wait_for_dismiss,
                    mode=mode,
                )

            monkeypatch.setattr(app, "call_later", flaky_call_later)
            monkeypatch.setattr(app, "push_screen", resolving_push)
            deadline = time.monotonic() + 5
            app.post_message(request)
            screen = await probe.first.wait(
                deadline=deadline, description="resolved-during-push presentation"
            )
            await probe.screens.retired(screen).wait(
                deadline=deadline, description="resolved-during-push removal"
            )
            assert request.decision is False
            assert schedule_attempts == 2
            assert not isinstance(app.screen, ConfirmationScreen)
            assert app.is_running

    asyncio.run(exercise())


_BOOTSTRAP_ATTACH_PROMPT = (
    "Open provider setup for grok with grok?\n\n"
    "This is provider setup, not Taut chat. Complete only trust, "
    "login, model, or equivalent setup.\n"
    "Return to Taut with Ctrl-\\ Ctrl-\\. The TUI will resume and "
    "keep this Summon run active."
)

_GATE_EXCERPT = "Trust this folder?\n\x1b[31m> Don't trust\x1b[0m"


async def _pushed_confirmation(
    pilot: Any,
    app: Any,
    *,
    replacing: Any = None,
    deadline: float,
) -> Any:
    """Await the exact request's actual mounted presentation, without driving it."""
    del pilot
    probe: SummonObservations = cast(Any, app)._summon_test_observations
    return await probe.confirmation(deadline=deadline, replacing=replacing)


async def _settled_decision(
    pilot: Any, request: Any, *, deadline: float
) -> bool | None:
    probe: SummonObservations = pilot.app._summon_test_observations
    return cast(bool | None, await probe.settled(request, deadline=deadline))


def test_setup_recovery_offer_leads_with_member_and_escaped_excerpt() -> None:
    """[TUI-11.1] an excerpt-bearing notice asks to attach before the facts."""

    import asyncio

    from taut_summon import TerminalAttachNotice

    from taut_tui.app import TautApp
    from taut_tui.summon import TerminalAttachConfirmationRequest

    async def exercise() -> None:
        app = TautApp(db_path=None, as_name=None, continuity_token=None)
        async with app.run_test(size=(100, 30)) as pilot:
            request = TerminalAttachConfirmationRequest(
                TerminalAttachNotice(
                    member="kimi",
                    provider="kimi",
                    detach_hint="Ctrl-\\ Ctrl-\\",
                    screen_excerpt=_GATE_EXCERPT,
                )
            )
            deadline = time.monotonic() + 2
            app.post_message(request)
            offer = await _pushed_confirmation(pilot, app, deadline=deadline)

            assert "Looks like kimi needs interaction." in offer.prompt
            assert "Trust this folder?" in offer.prompt
            assert "Don't trust" in offer.prompt
            assert "Attach?" in offer.prompt
            assert "\x1b" not in offer.prompt
            assert r"\x1b" in offer.prompt
            assert "This is provider setup" not in offer.prompt
            assert not request.resolved.is_set()

            deadline = time.monotonic() + 2
            offer.action_confirm()
            acknowledgement = await _pushed_confirmation(
                pilot, app, replacing=offer, deadline=deadline
            )
            assert "This is provider setup, not Taut chat." in acknowledgement.prompt
            assert (
                "Enter Ctrl-\\ Ctrl-\\ (Control-Backslash twice) to return to Taut."
                in acknowledgement.prompt
            )
            assert not request.resolved.is_set()

            deadline = time.monotonic() + 2
            acknowledgement.action_confirm()
            assert await _settled_decision(pilot, request, deadline=deadline) is True

    asyncio.run(exercise())


def test_setup_recovery_offer_decline_skips_the_acknowledgement_phase() -> None:
    """[SUM-7.4] declining the offer resolves False without a second modal."""

    import asyncio

    from taut_summon import TerminalAttachNotice

    from taut_tui.app import TautApp
    from taut_tui.screens import ConfirmationScreen
    from taut_tui.summon import TerminalAttachConfirmationRequest

    async def exercise() -> None:
        app = TautApp(db_path=None, as_name=None, continuity_token=None)
        async with app.run_test(size=(100, 30)) as pilot:
            request = TerminalAttachConfirmationRequest(
                TerminalAttachNotice(
                    member="kimi",
                    provider="kimi",
                    detach_hint="Ctrl-\\ Ctrl-\\",
                    screen_excerpt=_GATE_EXCERPT,
                )
            )
            deadline = time.monotonic() + 2
            app.post_message(request)
            offer = await _pushed_confirmation(pilot, app, deadline=deadline)
            assert "Attach?" in offer.prompt

            started = time.monotonic()
            deadline = started + 2
            offer.action_reject()
            assert await _settled_decision(pilot, request, deadline=deadline) is False
            probe: SummonObservations = cast(Any, app)._summon_test_observations
            await probe.screens.retired(offer).wait(
                deadline=started + 5, description="offer removed"
            )
            assert probe.presented == [offer]
            assert not isinstance(app.screen, ConfirmationScreen)
            assert app.is_running

    asyncio.run(exercise())


def test_setup_recovery_acknowledgement_decline_resolves_false() -> None:
    """Declining the four-facts phase is still the [SUM-7.4] decline."""

    import asyncio

    from taut_summon import TerminalAttachNotice

    from taut_tui.app import TautApp
    from taut_tui.screens import ConfirmationScreen
    from taut_tui.summon import TerminalAttachConfirmationRequest

    async def exercise() -> None:
        app = TautApp(db_path=None, as_name=None, continuity_token=None)
        async with app.run_test(size=(100, 30)) as pilot:
            request = TerminalAttachConfirmationRequest(
                TerminalAttachNotice(
                    member="kimi",
                    provider="kimi",
                    detach_hint="Ctrl-\\ Ctrl-\\",
                    screen_excerpt=_GATE_EXCERPT,
                )
            )
            deadline = time.monotonic() + 2
            app.post_message(request)
            offer = await _pushed_confirmation(pilot, app, deadline=deadline)
            deadline = time.monotonic() + 2
            offer.action_confirm()
            acknowledgement = await _pushed_confirmation(
                pilot, app, replacing=offer, deadline=deadline
            )
            started = time.monotonic()
            deadline = started + 2
            acknowledgement.action_reject()

            assert await _settled_decision(pilot, request, deadline=deadline) is False
            probe: SummonObservations = cast(Any, app)._summon_test_observations
            await probe.screens.retired(acknowledgement).wait(
                deadline=started + 5, description="acknowledgement removed"
            )
            assert probe.presented == [offer, acknowledgement]
            assert not isinstance(app.screen, ConfirmationScreen)
            assert app.is_running

    asyncio.run(exercise())


def test_worker_resolution_dismisses_the_pending_offer_modal() -> None:
    """A worker-side decision cannot strand the offer phase on screen."""

    import asyncio

    from taut_summon import TerminalAttachNotice

    from taut_tui.app import TautApp
    from taut_tui.screens import ConfirmationScreen
    from taut_tui.summon import TerminalAttachConfirmationRequest

    async def exercise() -> None:
        app = TautApp(db_path=None, as_name=None, continuity_token=None)
        async with app.run_test(size=(100, 30)) as pilot:
            request = TerminalAttachConfirmationRequest(
                TerminalAttachNotice(
                    member="kimi",
                    provider="kimi",
                    detach_hint="Ctrl-\\ Ctrl-\\",
                    screen_excerpt=_GATE_EXCERPT,
                )
            )
            deadline = time.monotonic() + 2
            app.post_message(request)
            offer = await _pushed_confirmation(pilot, app, deadline=deadline)
            assert "Attach?" in offer.prompt

            deadline = time.monotonic() + 5
            request.resolve(False)
            probe: SummonObservations = cast(Any, app)._summon_test_observations
            await probe.screens.retired(offer).wait(
                deadline=deadline, description="decided offer removed"
            )
            assert not isinstance(app.screen, ConfirmationScreen)
            assert request.decision is False
            assert app.is_running

    asyncio.run(exercise())


def test_bootstrap_attach_confirmation_content_is_unchanged() -> None:
    """[TUI-11.1] invariant: a notice without an excerpt renders as today."""

    import asyncio

    from taut_summon import TerminalAttachNotice

    from taut_tui.app import TautApp
    from taut_tui.screens import ConfirmationScreen
    from taut_tui.summon import TerminalAttachConfirmationRequest

    async def exercise() -> None:
        app = TautApp(db_path=None, as_name=None, continuity_token=None)
        async with app.run_test(size=(100, 30)) as pilot:
            request = TerminalAttachConfirmationRequest(
                TerminalAttachNotice(
                    member="grok",
                    provider="grok",
                    detach_hint="Ctrl-\\ Ctrl-\\",
                )
            )
            deadline = time.monotonic() + 2
            app.post_message(request)
            acknowledgement = await _pushed_confirmation(pilot, app, deadline=deadline)

            assert acknowledgement.prompt == _BOOTSTRAP_ATTACH_PROMPT
            assert "Control-Backslash" not in acknowledgement.prompt
            assert "Looks like" not in acknowledgement.prompt

            started = time.monotonic()
            deadline = started + 2
            acknowledgement.action_confirm()
            assert await _settled_decision(pilot, request, deadline=deadline) is True
            probe: SummonObservations = cast(Any, app)._summon_test_observations
            await probe.screens.retired(acknowledgement).wait(
                deadline=started + 5, description="acknowledgement removed"
            )
            assert not isinstance(app.screen, ConfirmationScreen)

    asyncio.run(exercise())


def test_confirm_owner_contention_declines_instead_of_raising() -> None:
    """[TUI-11.3] losing a confirm race degrades to a graceful decline."""

    from taut_summon import TerminalAttachNotice

    from taut_tui import summon as tui_summon

    app = _LeaseApp(confirmation_decision=None)
    interaction = tui_summon.TuiSummonInteraction(app, timeout=2.0)
    first_blocked = Event()
    first_done = Event()
    results: list[object] = []

    notice = TerminalAttachNotice(
        member="grok", provider="grok", detach_hint="Ctrl-\\ Ctrl-\\"
    )

    def first() -> None:
        cancel = Event()

        def cancel_soon() -> None:
            first_blocked.wait(5)
            cancel.set()

        Thread(target=cancel_soon).start()
        try:
            results.append(interaction.confirm_terminal_attach(notice, cancel=cancel))
        finally:
            first_done.set()

    worker = Thread(target=first)
    deadline = time.monotonic() + 2.0
    worker.start()
    assert app.confirmation_posted.wait(max(0.0, deadline - time.monotonic()))
    second = interaction.confirm_terminal_attach(notice)
    assert second is False
    first_blocked.set()
    assert first_done.wait(5)
    worker.join(timeout=5)


def test_summon_status_transitions_do_not_clobber_unrelated_operation() -> None:
    """Summon ready/return only own summon-shaped operation states."""

    import asyncio
    from concurrent.futures import Future

    from taut_tui.app import TautApp
    from taut_tui.summon import OwnedSummonRun

    async def exercise() -> None:
        app = TautApp(db_path=None, as_name=None, continuity_token=None)
        async with app.run_test(size=(100, 30)):
            app._owned_summon_tokens.add("tok")
            run = OwnedSummonRun(
                token="tok", pending=False, member_id="m", member_name="grok"
            )
            app._operation_state = "working"
            app._apply_summon_ready(run)
            assert app._operation_state == "working"
            app._operation_state = "summon grok starting"
            app._apply_summon_ready(run)
            assert app._operation_state == "summon live"

            done: Future[None] = Future()
            done.set_result(None)
            app._owned_summon_tokens.add("tok")
            app._operation_state = "working"
            app._apply_summon_return("tok", done)
            assert app._operation_state == "working"
            app._owned_summon_tokens.add("tok2")
            app._operation_state = "summon live"
            app._apply_summon_return("tok2", done)
            assert app._operation_state == "idle"

    asyncio.run(exercise())


# --- [TUI-13.2] setup-recovery offer over real Summon machinery -------------

_GATE_FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "taut_summon"
    / "tests"
    / "fixtures"
    / "gate_harness.py"
)


def _configure_gate_pty(
    monkeypatch: pytest.MonkeyPatch,
    *,
    log_dir: Path,
    pretrusted: bool,
) -> Path:
    """Point the PTY provider at the real interactive setup-gate harness."""

    log_dir.mkdir(parents=True, exist_ok=True)
    log = log_dir / "gate-harness.jsonl"
    monkeypatch.setenv(
        "TAUT_SUMMON_PTY_ARGV", json.dumps([sys.executable, str(_GATE_FIXTURE)])
    )
    monkeypatch.setenv("TAUT_SUMMON_PTY_ROWS", "24")
    monkeypatch.setenv("TAUT_SUMMON_PTY_COLS", "80")
    monkeypatch.setenv("TAUT_SUMMON_PTY_STALL_S", "0.5")
    monkeypatch.setenv("TAUT_SUMMON_PTY_QUIET_MS", "50")
    monkeypatch.setenv("TAUT_SUMMON_PTY_MAX_SETTLE_S", "1.0")
    monkeypatch.setenv("TAUT_GATE_LOG", str(log))
    if pretrusted:
        monkeypatch.setenv("TAUT_GATE_PRETRUSTED", "1")
    else:
        monkeypatch.delenv("TAUT_GATE_PRETRUSTED", raising=False)
    return log


def _gate_events(log: Path) -> list[dict[str, Any]]:
    if not log.exists():
        return []
    text = log.read_text(encoding="utf-8")
    lines = text.splitlines()
    events: list[dict[str, Any]] = []
    for index, line in enumerate(lines):
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            # The fixture appends complete JSONL records, but a concurrent
            # reader is not guaranteed to observe the final write atomically.
            if index == len(lines) - 1 and not text.endswith("\n"):
                break
            raise
    return events


def _gate_inputs(log: Path) -> list[str]:
    return [
        str(event.get("raw", ""))
        for event in _gate_events(log)
        if event["event"] == "input"
    ]


def _gate_starts(log: Path) -> int:
    return sum(1 for event in _gate_events(log) if event["event"] == "start")


def _gate_menu_answers(log: Path) -> list[str]:
    """Menu selections the harness accepted, whoever produced the bytes."""

    return [
        str(event["event"])
        for event in _gate_events(log)
        if event["event"] in {"declined_default", "trusted"}
    ]


class _GateHostInteraction:
    """Shell-equivalent host owning the wiring run's real terminal fds."""

    def __init__(self, *, input_fd: int, output_fd: int) -> None:
        self._input_fd = input_fd
        self._output_fd = output_fd
        self.notices: list[Any] = []

    def terminal_availability(self, intent: Any) -> Any:
        from taut_summon import TerminalAvailability

        del intent
        return TerminalAvailability.AVAILABLE

    def confirm_terminal_attach(self, notice: Any, *, cancel: Any = None) -> bool:
        del cancel
        self.notices.append(notice)
        return True

    @contextmanager
    def terminal_lease(self) -> Iterator[Any]:
        from taut_summon import TerminalLease

        yield TerminalLease(input_fd=self._input_fd, output_fd=self._output_fd)

    def supports_setup_recovery(self) -> bool:
        return True


class _GateAnswerer(Thread):
    """Answer the provider's trust gate through the leased terminal fds."""

    def __init__(self, terminal: HostTerminal, *, lease_acquired: LeaseOrStop) -> None:
        super().__init__(daemon=True, name="tui-gate-answerer")
        self._terminal = terminal
        self._lease_acquired = lease_acquired
        self.failures: list[str] = []
        self.answered = Event()
        self.finished = Event()
        from concurrent.futures import Future

        self.completion: Future[None] = Future()
        self.stage = "waiting for terminal lease"
        self.detach_started_at: float | None = None

    def request_stop(self) -> None:
        self._lease_acquired.stop()

    def run(self) -> None:
        try:
            if not self._lease_acquired.wait():
                return
            self.stage = "terminal lease acquired; waiting for gate menu"
            output = self._terminal.read_until(b"Trust this folder?")
            if b"Trust this folder?" not in output:
                self.failures.append(
                    f"the gate menu never reached the leased terminal: {output[-256:]!r}"
                )
                return
            self.stage = "gate menu reached; sending trust"
            self._terminal.write(b"\x14")
            self.stage = "waiting for chat prompt"
            output = self._terminal.read_until(b"chat>")
            if b"chat>" not in output:
                self.failures.append(
                    f"trusting the folder never opened the chat prompt: {output[-256:]!r}"
                )
                return
            self.answered.set()
            self.stage = "chat prompt reached; sending detach"
            self.detach_started_at = time.monotonic()
            self._terminal.write(b"\x1c\x1c")
            self.stage = "waiting for detach reset"
            output = self._terminal.read_until(b"\x1b[?2004l")
            if b"\x1b[?2004l" not in output:
                self.failures.append(
                    f"the detach reset blast never arrived: {output[-256:]!r}"
                )
                return
            self.stage = "detach reset reached"
        except BaseException as error:
            self.completion.set_exception(error)
            raise
        finally:
            self.finished.set()
            if self.completion.done():
                pass
            elif self.failures:
                self.completion.set_exception(AssertionError("; ".join(self.failures)))
            else:
                self.completion.set_result(None)


@pytest.mark.parametrize(
    ("transitions", "acquired", "stopped", "proceed"),
    [
        (("set",), True, False, True),
        (("stop",), False, True, False),
        (("set", "stop"), True, True, False),
        (("stop", "set"), True, True, False),
    ],
)
def test_gate_answerer_wake_retains_lease_and_stop_as_distinct_sources(
    transitions: tuple[str, ...], acquired: bool, stopped: bool, proceed: bool
) -> None:
    signal = LeaseOrStop()
    for transition in transitions:
        getattr(signal, transition)()
    assert signal.wait() is proceed
    assert signal.acquired is acquired
    assert signal.stopped is stopped


def test_gate_answerer_preserves_terminal_failure_in_its_completion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    terminal = HostTerminal.open()
    signal = LeaseOrStop()
    answerer = _GateAnswerer(terminal, lease_acquired=signal)
    error = RuntimeError("terminal read failed")

    def fail_read(*args: Any, **kwargs: Any) -> bytes:
        raise error

    monkeypatch.setattr(terminal, "read_until", fail_read)
    signal.set()
    try:
        with pytest.raises(RuntimeError) as caught:
            answerer.run()
        assert caught.value is error
        assert answerer.completion.exception() is error
        assert answerer.finished.is_set()
    finally:
        terminal.close()


def test_provider_consumption_retains_success_but_surfaces_later_injection_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from _completion import CompletionKey

    handle = object()
    failure = RuntimeError("inject failed after child acknowledgement")
    with (
        pytest.raises(RuntimeError) as teardown,
        ProviderConsumption(monkeypatch, "bounded-marker", 5) as probe,
    ):
        consumed = probe.scope.expect(CompletionKey(handle, "provider.consumed", probe))

        def inject() -> None:
            consumed.succeed(consumed.key, handle)
            raise failure

        with pytest.raises(RuntimeError) as source:
            probe._orient(inject, consumed)
        assert source.value is failure
        assert (
            consumed.wait_sync(
                deadline=probe.scope.now() + 5,
                description="actual child consumption",
            )
            is handle
        )
    assert teardown.value is failure


def _gate_db(tmp_path: Path) -> Path:
    from taut import TautClient

    db = tmp_path / ".taut.db"
    TautClient.init(db_path=db)
    peer = TautClient(db_path=db, as_name="van")
    try:
        peer.join("general")
    finally:
        peer.close()
    return db


def _wire_gate_member(
    *,
    db: Path,
    name: str,
    prompt_path: Path,
    marker: str,
    terminal: HostTerminal,
    monkeypatch: pytest.MonkeyPatch,
    log_dir: Path,
) -> None:
    """Run 1: a pretrusted first attach leaves the member durably wired."""

    from taut_summon import SummonController, SummonRequest

    log = _configure_gate_pty(monkeypatch, log_dir=log_dir, pretrusted=True)
    request = SummonRequest(
        name=name,
        threads=("general",),
        persona=None,
        system_prompt_file=str(prompt_path),
        rate_limit=None,
        provider_flag="pty",
    )
    interaction = _GateHostInteraction(
        input_fd=terminal.lease_input_fd,
        output_fd=terminal.lease_output_fd,
    )
    failures: list[BaseException] = []

    def run() -> None:
        try:
            SummonController(db_path=db).run_foreground(request, interaction)
        except BaseException as exc:  # noqa: BLE001 approved [DOM-10.2.1] [RUFF-SUP-070] exception
            failures.append(exc)

    thread = Thread(target=run, daemon=True, name="tui-gate-wiring")
    with ProviderConsumption(monkeypatch, marker, 30) as consumed:
        thread.start()
        try:
            assert b"chat>" in terminal.read_until(b"chat>")
            deadline = time.monotonic() + 30
            terminal.write(b"\x1c\x1c")
            assert b"\x1b[?2004l" in terminal.read_until(b"\x1b[?2004l")
            consumed.wait_sync(deadline=deadline)
            assert any(marker in raw for raw in _gate_inputs(log))
            SummonController(db_path=db).stop(name)
        finally:
            thread.join(timeout=20.0)
        assert not thread.is_alive()
    assert failures == []
    assert len(interaction.notices) == 1
    assert interaction.notices[0].screen_excerpt is None


def _gate_app(db: Path) -> Any:
    """The real TUI whose only fake is Textual's headless-unsupported suspend."""

    from taut_tui.app import TautApp

    class _GatePilotApp(TautApp):
        def __init__(self, **kwargs: Any) -> None:
            super().__init__(**kwargs)
            self.suspensions = 0
            self.lease_threads: list[Thread] = []

        @contextmanager
        def suspend(self) -> Iterator[None]:
            self.suspensions += 1
            yield

        def post_message(self, message: Any) -> bool:
            # Textual's headless pilot and the app share one asyncio loop,
            # while the production handler deliberately blocks that loop for
            # the full terminal suspension. Confirmation messages still use
            # Textual; only the unsupported headless lease body gets the same
            # test-owned thread seam as the focused lease protocol tests.
            from taut_tui.summon import TerminalLeaseRequest

            if not isinstance(message, TerminalLeaseRequest):
                return super().post_message(message)
            thread = Thread(
                target=message.hold,
                args=(self,),
                daemon=True,
                name="tui-gate-terminal-lease",
            )
            self.lease_threads.append(thread)
            thread.start()
            return True

    return _GatePilotApp(db_path=str(db), as_name="van", continuity_token=None)


def _gate_submission(name: str, prompt_path: Path) -> Any:
    from taut_tui.screens import SummonStartSubmission

    return SummonStartSubmission(
        name=name,
        threads=("general",),
        provider="pty",
        persona=None,
        system_prompt_file=str(prompt_path),
        rate_limit=None,
        attach=False,
        detach=False,
        takeover=False,
    )


def _start_owned_gate_run(app: Any, name: str, prompt_path: Path) -> Any:
    summon = app._summon
    assert summon is not None
    request = summon.build_request(
        name=name,
        threads=("general",),
        persona=None,
        system_prompt_file=str(prompt_path),
        rate_limit=None,
        attach=False,
        detach=False,
        provider_flag="pty",
        takeover=False,
    )
    _token, future = summon.start(request, app._summon_interaction)
    return future


def _prepare_gate_recovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    name: str,
    marker: str,
    terminal: HostTerminal,
    lease_acquired: LeaseOrStop | None = None,
) -> tuple[Path, Path, Path]:
    """Wire the member, then arm the un-trusted re-summon the TUI will own."""

    from taut_tui import summon as tui_summon

    prompt_path = tmp_path / "gate-prompt.txt"
    prompt_path.write_text(marker, encoding="utf-8")
    db = _gate_db(tmp_path)
    # Each foreground attach owns one host-terminal session.  In particular,
    # do not reuse a Windows anonymous-pipe lease after its prior attach reader
    # was cancelled: unread reset bytes and cancelled-I/O state belong to that
    # completed session, not to the recovery attach this test is proving.
    wiring_terminal = HostTerminal.open()
    try:
        _wire_gate_member(
            db=db,
            name=name,
            prompt_path=prompt_path,
            marker=marker,
            terminal=wiring_terminal,
            monkeypatch=monkeypatch,
            log_dir=tmp_path / "run1",
        )
    finally:
        wiring_terminal.close()
    log = _configure_gate_pty(monkeypatch, log_dir=tmp_path / "run2", pretrusted=False)
    monkeypatch.setattr(tui_summon, "_standard_terminal_is_suitable", lambda: True)

    def terminal_fds() -> tuple[int, int]:
        if lease_acquired is not None:
            lease_acquired.set()
        return terminal.lease_input_fd, terminal.lease_output_fd

    monkeypatch.setattr(tui_summon, "_standard_terminal_fds", terminal_fds)
    return db, prompt_path, log


def test_setup_recovery_offer_reaches_a_pending_owned_tui_and_completes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """[TUI-13.2] the mid-run offer arrives pre-readiness and can be accepted.

    Concurrent-owner exclusion for this same coordinator is proven by
    ``test_confirm_owner_contention_declines_instead_of_raising``; the
    single worker request here cannot race a second acknowledgement.
    """

    import asyncio

    marker = "tui-gate-orientation-probe"
    terminal = HostTerminal.open()
    lease_acquired = LeaseOrStop()
    try:
        db, prompt_path, log = _prepare_gate_recovery(
            tmp_path,
            monkeypatch,
            name="gated",
            marker=marker,
            terminal=terminal,
            lease_acquired=lease_acquired,
        )

        async def exercise() -> None:
            app = _gate_app(db)
            probe: SummonObservations = cast(Any, app)._summon_test_observations
            probe.observe_owned_run()
            answerer = _GateAnswerer(terminal, lease_acquired=lease_acquired)
            answerer_finished = probe.scope.observe_future(
                answerer.completion, owner=answerer, phase="answerer.finished"
            )
            answerer.start()
            try:
                with ProviderConsumption(monkeypatch, marker, 45) as consumed:
                    async with app.run_test(size=(100, 30)) as pilot:
                        deadline = time.monotonic() + 45
                        app._complete_summon_start(
                            _gate_submission("gated", prompt_path)
                        )
                        offer = await _pushed_confirmation(
                            pilot, app, deadline=deadline
                        )
                        assert "Looks like gated needs interaction." in offer.prompt
                        assert "Trust this folder?" in offer.prompt
                        assert "Attach?" in offer.prompt
                        assert "This is provider setup" not in offer.prompt
                        # The offer precedes readiness: the run is still pending-owned
                        # and nothing has been injected into the menu.
                        assert [run.pending for run in app._summon.owned_runs()] == [
                            True
                        ]
                        assert app._operation_state == "summon gated starting"
                        assert _gate_starts(log) == 1
                        assert _gate_inputs(log) == []
                        assert _gate_menu_answers(log) == []

                        deadline = time.monotonic() + 10
                        offer.action_confirm()
                        acknowledgement = await _pushed_confirmation(
                            pilot, app, replacing=offer, deadline=deadline
                        )
                        assert (
                            "This is provider setup, not Taut chat."
                            in acknowledgement.prompt
                        )
                        assert (
                            "Enter Ctrl-\\ Ctrl-\\ (Control-Backslash twice) to return to Taut."
                            in acknowledgement.prompt
                        )
                        deadline = time.monotonic() + 45
                        acknowledgement.action_confirm()

                        try:
                            await answerer_finished.wait(
                                deadline=deadline,
                                description="terminal answerer completion",
                            )
                        except (AssertionError, TimeoutError) as exc:
                            exc.add_note(f"terminal answerer stage: {answerer.stage}")
                            exc.add_note(
                                f"terminal answerer failures: {answerer.failures!r}"
                            )
                            exc.add_note(f"gate events: {_gate_events(log)!r}")
                            raise
                        assert answerer.failures == []
                        assert answerer.answered.is_set()
                        try:
                            assert answerer.detach_started_at is not None
                            await consumed.wait(
                                deadline=answerer.detach_started_at + 45
                            )
                            assert any(marker in raw for raw in _gate_inputs(log))
                        except (AssertionError, TimeoutError) as exc:
                            exc.add_note(f"terminal answerer stage: {answerer.stage}")
                            exc.add_note(f"gate events: {_gate_events(log)!r}")
                            exc.add_note(f"operation state: {app._operation_state!r}")
                            exc.add_note(f"owned runs: {app._summon.owned_runs()!r}")
                            raise
                        assert probe.ready is not None
                        assert probe.ready_handoff is not None
                        deadline = probe.scope.now() + 45
                        ready_origin = await probe.ready_handoff.wait(
                            deadline=deadline, description="exact ready handoff"
                        )
                        run = await probe.ready.wait(
                            deadline=min(deadline, ready_origin + 45),
                            description="post-recovery readiness",
                        )
                        assert probe.ready_started_at is not None
                        ready_outcome = probe.ready.snapshot()
                        assert ready_outcome is not None
                        assert ready_outcome.published_at <= probe.ready_started_at + 45
                        assert run.token in app._owned_summon_tokens
                        assert app._operation_state == "summon live"
                        assert app.suspensions == 1
                        assert [run.pending for run in app._summon.owned_runs()] == [
                            False
                        ]
                        deadline = time.monotonic() + 45
                        app._summon.request_owned_stops()
                        assert probe.returned is not None
                        token, future = await probe.returned.wait(
                            deadline=deadline, description="owned worker return"
                        )
                        assert token == run.token and future.done()
                        assert not app._owned_summon_tokens

            finally:
                answerer.request_stop()
                answerer.join(timeout=20.0)
                for lease_thread in app.lease_threads:
                    lease_thread.join(timeout=20.0)
            assert answerer.finished.is_set()
            assert answerer.failures == []
            assert answerer.answered.is_set()
            assert app.lease_threads
            assert not any(thread.is_alive() for thread in app.lease_threads)

        asyncio.run(exercise())
    finally:
        terminal.close()


def test_setup_recovery_decline_continues_detached_with_enriched_give_up(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """[SUM-7.4] declining the TUI offer continues the run detached.

    The decline consumes the single attempt: no second offer, no lease, and
    the next generation starts without an acknowledged attach.
    """

    import asyncio

    # Flushed input does not imply that the child has processed it. Hold the
    # orientation completion until the real PTY pump retires, making this
    # explicitly the pre-readiness death case instead of racing two workers.
    from taut_summon._driver import SummonDriver

    from taut_tui.screens import ConfirmationScreen

    original_start = SummonDriver._start_phase_operation

    def start_after_exit(self: Any, name: str, operation: Any) -> None:
        if name == "orientation":
            original_operation = operation
            pump = self._owner_running.pump

            def operation() -> Any:
                value = original_operation()
                pump.join(15)
                assert not pump.is_alive(), "real PTY pump did not retire"
                return value

        original_start(self, name, operation)

    monkeypatch.setattr(SummonDriver, "_start_phase_operation", start_after_exit)

    monkeypatch.setenv("TAUT_SUMMON_RESUME_BACKOFF", "0.1")
    terminal = HostTerminal.open()
    try:
        db, prompt_path, log = _prepare_gate_recovery(
            tmp_path,
            monkeypatch,
            name="declined",
            marker="tui-decline-orientation-probe",
            terminal=terminal,
        )
        errors: list[BaseException] = []

        async def exercise() -> None:
            app = _gate_app(db)
            async with app.run_test(size=(100, 30)) as pilot:
                probe: SummonObservations = cast(Any, app)._summon_test_observations
                deadline = time.monotonic() + 45
                future = _start_owned_gate_run(app, "declined", prompt_path)
                returned = probe.scope.observe_future(
                    future, owner=app._summon, phase="declined.run_returned"
                )
                offer = await _pushed_confirmation(pilot, app, deadline=deadline)
                assert "Trust this folder?" in offer.prompt
                seen = len(probe.screens.history)
                deadline = time.monotonic() + 90
                offer.action_reject()
                from taut_summon import SummonOperationError

                with pytest.raises(SummonOperationError) as caught:
                    await returned.wait(
                        deadline=deadline, description="declined run completion"
                    )
                await probe.screens.retired(offer).wait(
                    deadline=deadline, description="declined offer removed"
                )
                assert not any(
                    isinstance(screen, ConfirmationScreen)
                    for screen in probe.screens.history[seen:]
                )
                assert probe.presented == [offer]
                assert app.suspensions == 0
                error = future.exception()
                assert caught.value is error
                assert error is not None
                errors.append(error)

        asyncio.run(exercise())
        from taut_summon import SummonOperationError

        # The decline never ends the run at the offer: a second generation
        # starts detached and injects into the still-unanswered menu.
        assert _gate_starts(log) == 2
        assert _gate_menu_answers(log) == ["declined_default"]
        # A TUI-owned run registers a readiness callback, so a generation that
        # dies before readiness is reported as that abort rather than through
        # the shell's crash-ladder give-up.
        assert isinstance(errors[0], SummonOperationError)
        assert "exited before foreground readiness" in str(errors[0])
    finally:
        terminal.close()


def test_host_shutdown_during_offer_spawns_nothing_further(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """[TUI-11.3] closing the TUI over a pending offer takes the shutdown class."""

    import asyncio

    terminal = HostTerminal.open()
    try:
        db, prompt_path, log = _prepare_gate_recovery(
            tmp_path,
            monkeypatch,
            name="stopped",
            marker="tui-shutdown-orientation-probe",
            terminal=terminal,
        )
        futures: list[Any] = []

        async def exercise() -> None:
            app = _gate_app(db)
            async with app.run_test(size=(100, 30)) as pilot:
                deadline = time.monotonic() + 45
                futures.append(_start_owned_gate_run(app, "stopped", prompt_path))
                offer = await _pushed_confirmation(pilot, app, deadline=deadline)
                assert "Trust this folder?" in offer.prompt
                assert _gate_starts(log) == 1
                app.exit()
            assert app.suspensions == 0

        asyncio.run(exercise())
        future = futures[0]
        assert future.exception(timeout=60.0) is None
        # Shutdown ends the run: no recovery generation, no injection.
        assert _gate_starts(log) == 1
        assert _gate_inputs(log) == []
        assert _gate_menu_answers(log) == []
        assert not any(event["event"] == "chat_ready" for event in _gate_events(log))
    finally:
        terminal.close()
