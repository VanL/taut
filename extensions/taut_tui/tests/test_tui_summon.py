"""TUI extension Summon worker, exact-run, and terminal-lease behavior.

Spec references:
- docs/specs/10-taut-tui.md [TUI-11], [TUI-12.3]
"""

from __future__ import annotations

import json
import os
import select
import sys
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from threading import Event, Lock, Thread
from typing import Any, cast

import pytest

pytestmark = pytest.mark.sqlite_only


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
    worker.start()
    try:
        deadline = time.monotonic() + 2.0
        while not app.messages and time.monotonic() < deadline:
            time.sleep(0.01)
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
    worker.start()
    deadline = time.monotonic() + 2.0
    while not app.messages and time.monotonic() < deadline:
        time.sleep(0.01)
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
    thread.start()
    deadline = time.monotonic() + 2.0
    while not app.messages and time.monotonic() < deadline:
        time.sleep(0.01)
    assert len(app.messages) == 1

    interaction.close()
    thread.join(timeout=5.0)
    assert not thread.is_alive()
    assert observed == [(False, True)]

    # A request that arrives after teardown is refused the same way.
    late = Event()
    assert interaction.confirm_terminal_attach(notice, cancel=late) is False
    assert late.is_set()


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


def test_real_app_lease_suspension_failure_exits_instead_of_lingering() -> None:
    """A suspend failure inside the real handler exits the TUI completely."""

    import asyncio

    from taut_tui.app import TautApp
    from taut_tui.summon import TerminalLeaseRequest

    async def exercise() -> None:
        app = TautApp(db_path=None, as_name=None, continuity_token=None)
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            request = TerminalLeaseRequest()
            app.post_message(request)
            for _ in range(100):
                await pilot.pause(0.01)
                if request.restored.is_set():
                    break
            assert request.error is not None
            for _ in range(100):
                await pilot.pause(0.01)
                if not app.is_running:
                    return
            raise AssertionError("app kept running after a failed lease")

    asyncio.run(exercise())


def test_stale_or_shutdown_lease_request_never_suspends_or_exits() -> None:
    """A lease request whose worker already gave up is refused inertly."""

    import asyncio

    from taut_tui.app import TautApp
    from taut_tui.summon import TerminalLeaseRequest

    async def exercise() -> None:
        app = TautApp(db_path=None, as_name=None, continuity_token=None)
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            request = TerminalLeaseRequest()
            request.release.set()  # worker timed out and moved on
            app.post_message(request)
            for _ in range(100):
                await pilot.pause(0.01)
                if request.restored.is_set():
                    break
            assert request.restored.is_set()
            assert request.error is not None
            assert app.is_running
            await pilot.pause(0.05)
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
            await pilot.pause()
            app._summon = stub  # type: ignore[assignment]
            app.action_quit_tui()
            await pilot.pause()
            assert isinstance(app.screen, ConfirmationScreen)
            app.screen.action_confirm()
            for _ in range(100):
                await pilot.pause(0.01)
                if not app.is_running:
                    break
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
            await pilot.pause()
            request = TerminalAttachConfirmationRequest(_Notice())
            app.post_message(request)
            for _ in range(100):
                await pilot.pause(0.01)
                if isinstance(app.screen, ConfirmationScreen):
                    break
            assert isinstance(app.screen, ConfirmationScreen)
            request.resolve(False)
            for _ in range(100):
                await pilot.pause(0.01)
                if not isinstance(app.screen, ConfirmationScreen):
                    break
            assert not isinstance(app.screen, ConfirmationScreen)
            assert app.is_running

    asyncio.run(exercise())


def test_cancelled_attach_dismiss_failure_cannot_replace_resolution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A deferred presentation failure stays subordinate to the decision."""

    import asyncio

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

    class FailingOnceConfirmation(ConfirmationScreen):
        def dismiss(self, result: bool | None = None) -> AwaitComplete:
            nonlocal dismiss_calls
            dismiss_calls += 1
            if dismiss_calls == 1:
                raise RuntimeError("dismiss failed")
            return super().dismiss(result)

    monkeypatch.setattr(tui_app, "ConfirmationScreen", FailingOnceConfirmation)

    async def exercise() -> None:
        app = tui_app.TautApp(db_path=None, as_name=None, continuity_token=None)
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            request = TerminalAttachConfirmationRequest(_Notice())
            app.post_message(request)
            for _ in range(100):
                await pilot.pause(0.01)
                if isinstance(app.screen, FailingOnceConfirmation):
                    break
            assert isinstance(app.screen, FailingOnceConfirmation)
            request.resolve(False)
            for _ in range(100):
                await pilot.pause(0.01)
                if dismiss_calls == 1:
                    break
            assert dismiss_calls == 1
            assert request.decision is False
            assert request.resolved.is_set()
            assert app.is_running
            assert isinstance(app.screen, FailingOnceConfirmation)
            app.screen.dismiss(False)
            await pilot.pause()

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
            await pilot.pause()
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
            app.post_message(request)
            for _ in range(100):
                await pilot.pause(0.01)
                if schedule_attempts >= 2 and not isinstance(
                    app.screen, ConfirmationScreen
                ):
                    break
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
    timeout: float = 2.0,
) -> Any:
    """Wait for the next confirmation modal that is not ``replacing``."""

    from taut_tui.screens import ConfirmationScreen

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        await pilot.pause(0.01)
        screen = app.screen
        if isinstance(screen, ConfirmationScreen) and screen is not replacing:
            return screen
    raise AssertionError("no confirmation modal was presented")


async def _settled_decision(pilot: Any, request: Any) -> bool | None:
    for _ in range(200):
        await pilot.pause(0.01)
        if request.resolved.is_set():
            break
    assert request.resolved.is_set()
    decision: bool | None = request.decision
    return decision


def test_setup_recovery_offer_leads_with_member_and_escaped_excerpt() -> None:
    """[TUI-11.1] an excerpt-bearing notice asks to attach before the facts."""

    import asyncio

    from taut_summon import TerminalAttachNotice

    from taut_tui.app import TautApp
    from taut_tui.summon import TerminalAttachConfirmationRequest

    async def exercise() -> None:
        app = TautApp(db_path=None, as_name=None, continuity_token=None)
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            request = TerminalAttachConfirmationRequest(
                TerminalAttachNotice(
                    member="kimi",
                    provider="kimi",
                    detach_hint="Ctrl-\\ Ctrl-\\",
                    screen_excerpt=_GATE_EXCERPT,
                )
            )
            app.post_message(request)
            offer = await _pushed_confirmation(pilot, app)

            assert "Looks like kimi needs interaction." in offer.prompt
            assert "Trust this folder?" in offer.prompt
            assert "Don't trust" in offer.prompt
            assert "Attach?" in offer.prompt
            assert "\x1b" not in offer.prompt
            assert r"\x1b" in offer.prompt
            assert "This is provider setup" not in offer.prompt
            assert not request.resolved.is_set()

            offer.action_confirm()
            acknowledgement = await _pushed_confirmation(pilot, app, replacing=offer)
            assert "This is provider setup, not Taut chat." in acknowledgement.prompt
            assert (
                "Enter Ctrl-\\ Ctrl-\\ (Control-Backslash twice) to return to Taut."
                in acknowledgement.prompt
            )
            assert not request.resolved.is_set()

            acknowledgement.action_confirm()
            assert await _settled_decision(pilot, request) is True

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
            await pilot.pause()
            request = TerminalAttachConfirmationRequest(
                TerminalAttachNotice(
                    member="kimi",
                    provider="kimi",
                    detach_hint="Ctrl-\\ Ctrl-\\",
                    screen_excerpt=_GATE_EXCERPT,
                )
            )
            app.post_message(request)
            offer = await _pushed_confirmation(pilot, app)
            assert "Attach?" in offer.prompt

            offer.action_reject()
            assert await _settled_decision(pilot, request) is False
            for _ in range(20):
                await pilot.pause(0.01)
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
            await pilot.pause()
            request = TerminalAttachConfirmationRequest(
                TerminalAttachNotice(
                    member="kimi",
                    provider="kimi",
                    detach_hint="Ctrl-\\ Ctrl-\\",
                    screen_excerpt=_GATE_EXCERPT,
                )
            )
            app.post_message(request)
            offer = await _pushed_confirmation(pilot, app)
            offer.action_confirm()
            acknowledgement = await _pushed_confirmation(pilot, app, replacing=offer)
            acknowledgement.action_reject()

            assert await _settled_decision(pilot, request) is False
            for _ in range(20):
                await pilot.pause(0.01)
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
            await pilot.pause()
            request = TerminalAttachConfirmationRequest(
                TerminalAttachNotice(
                    member="kimi",
                    provider="kimi",
                    detach_hint="Ctrl-\\ Ctrl-\\",
                    screen_excerpt=_GATE_EXCERPT,
                )
            )
            app.post_message(request)
            offer = await _pushed_confirmation(pilot, app)
            assert "Attach?" in offer.prompt

            request.resolve(False)
            for _ in range(100):
                await pilot.pause(0.01)
                if not isinstance(app.screen, ConfirmationScreen):
                    break
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
            await pilot.pause()
            request = TerminalAttachConfirmationRequest(
                TerminalAttachNotice(
                    member="grok",
                    provider="grok",
                    detach_hint="Ctrl-\\ Ctrl-\\",
                )
            )
            app.post_message(request)
            acknowledgement = await _pushed_confirmation(pilot, app)

            assert acknowledgement.prompt == _BOOTSTRAP_ATTACH_PROMPT
            assert "Control-Backslash" not in acknowledgement.prompt
            assert "Looks like" not in acknowledgement.prompt

            acknowledgement.action_confirm()
            assert await _settled_decision(pilot, request) is True
            for _ in range(20):
                await pilot.pause(0.01)
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
    worker.start()
    for _ in range(200):
        with interaction._lock:
            if interaction._terminal_owner is not None:
                break
        time.sleep(0.01)
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
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
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
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]


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


def _read_pty_until(fd: int, needle: bytes, *, timeout: float = 15.0) -> bytes:
    deadline = time.monotonic() + timeout
    output = b""
    while time.monotonic() < deadline:
        ready, _, _ = select.select([fd], [], [], 0.05)
        if not ready:
            continue
        output += os.read(fd, 4096)
        if needle in output:
            return output
    return output


def _wait_until(
    predicate: Callable[[], bool],
    *,
    message: str,
    timeout: float = 30.0,
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.05)
    raise AssertionError(f"timed out waiting for {message}")


async def _await_until(
    pilot: Any,
    predicate: Callable[[], bool],
    *,
    message: str,
    timeout: float = 45.0,
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        await pilot.pause(0.02)
    raise AssertionError(f"timed out waiting for {message}")


class _GateHostInteraction:
    """Shell-equivalent host owning the wiring run's real terminal fds."""

    def __init__(self, *, fd: int) -> None:
        self._fd = fd
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

        yield TerminalLease(input_fd=self._fd, output_fd=self._fd)

    def supports_setup_recovery(self) -> bool:
        return True


class _GateAnswerer(Thread):
    """Answer the provider's trust gate through the leased terminal fds."""

    def __init__(self, master_fd: int) -> None:
        super().__init__(daemon=True, name="tui-gate-answerer")
        self._fd = master_fd
        self.failures: list[str] = []
        self.answered = Event()

    def run(self) -> None:
        if b"Trust this folder?" not in _read_pty_until(
            self._fd, b"Trust this folder?"
        ):
            self.failures.append("the gate menu never reached the leased terminal")
            return
        os.write(self._fd, b"\x14")
        if b"chat>" not in _read_pty_until(self._fd, b"chat>"):
            self.failures.append("trusting the folder never opened the chat prompt")
            return
        self.answered.set()
        os.write(self._fd, b"\x1c\x1c")
        if b"\x1b[?2004l" not in _read_pty_until(self._fd, b"\x1b[?2004l"):
            self.failures.append("the detach reset blast never arrived")


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
    user_master: int,
    user_slave: int,
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
    interaction = _GateHostInteraction(fd=user_slave)
    failures: list[BaseException] = []

    def run() -> None:
        try:
            SummonController(db_path=db).run_foreground(request, interaction)
        except BaseException as exc:  # noqa: BLE001 approved [DOM-10.2.1] [RUFF-SUP-070] exception
            failures.append(exc)

    thread = Thread(target=run, daemon=True, name="tui-gate-wiring")
    thread.start()
    try:
        assert b"chat>" in _read_pty_until(user_master, b"chat>")
        os.write(user_master, b"\x1c\x1c")
        assert b"\x1b[?2004l" in _read_pty_until(user_master, b"\x1b[?2004l")
        _wait_until(
            lambda: any(marker in raw for raw in _gate_inputs(log)),
            message="wiring-run orientation injection",
        )
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

        @contextmanager
        def suspend(self) -> Iterator[None]:
            self.suspensions += 1
            yield

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
    user_master: int,
    user_slave: int,
) -> tuple[Path, Path, Path]:
    """Wire the member, then arm the un-trusted re-summon the TUI will own."""

    from taut_tui import summon as tui_summon

    prompt_path = tmp_path / "gate-prompt.txt"
    prompt_path.write_text(marker, encoding="utf-8")
    db = _gate_db(tmp_path)
    _wire_gate_member(
        db=db,
        name=name,
        prompt_path=prompt_path,
        marker=marker,
        user_master=user_master,
        user_slave=user_slave,
        monkeypatch=monkeypatch,
        log_dir=tmp_path / "run1",
    )
    log = _configure_gate_pty(monkeypatch, log_dir=tmp_path / "run2", pretrusted=False)
    monkeypatch.setattr(tui_summon, "_standard_terminal_is_suitable", lambda: True)
    monkeypatch.setattr(
        tui_summon, "_standard_terminal_fds", lambda: (user_slave, user_slave)
    )
    return db, prompt_path, log


@pytest.mark.posix_only
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
    import pty as pty_module

    marker = "tui-gate-orientation-probe"
    user_master, user_slave = pty_module.openpty()
    try:
        db, prompt_path, log = _prepare_gate_recovery(
            tmp_path,
            monkeypatch,
            name="gated",
            marker=marker,
            user_master=user_master,
            user_slave=user_slave,
        )
        answerer = _GateAnswerer(user_master)

        async def exercise() -> None:
            app = _gate_app(db)
            async with app.run_test(size=(100, 30)) as pilot:
                await pilot.pause()
                app._complete_summon_start(_gate_submission("gated", prompt_path))

                offer = await _pushed_confirmation(pilot, app, timeout=45.0)
                assert "Looks like gated needs interaction." in offer.prompt
                assert "Trust this folder?" in offer.prompt
                assert "Attach?" in offer.prompt
                assert "This is provider setup" not in offer.prompt
                # The offer precedes readiness: the run is still pending-owned
                # and nothing has been injected into the menu.
                assert [run.pending for run in app._summon.owned_runs()] == [True]
                assert app._operation_state == "summon gated starting"
                assert _gate_starts(log) == 1
                assert _gate_inputs(log) == []
                assert _gate_menu_answers(log) == []

                answerer.start()
                offer.action_confirm()
                acknowledgement = await _pushed_confirmation(
                    pilot, app, replacing=offer, timeout=10.0
                )
                assert (
                    "This is provider setup, not Taut chat." in acknowledgement.prompt
                )
                assert (
                    "Enter Ctrl-\\ Ctrl-\\ (Control-Backslash twice) to return to Taut."
                    in acknowledgement.prompt
                )
                acknowledgement.action_confirm()

                await _await_until(
                    pilot,
                    lambda: any(marker in raw for raw in _gate_inputs(log)),
                    message="post-recovery orientation injection",
                )
                await _await_until(
                    pilot,
                    lambda: app._operation_state == "summon live",
                    message="post-recovery readiness",
                )
                assert app.suspensions == 1
                assert [run.pending for run in app._summon.owned_runs()] == [False]
                app._summon.request_owned_stops()
                await _await_until(
                    pilot,
                    lambda: not app._owned_summon_tokens,
                    message="owned worker return",
                )

        asyncio.run(exercise())
        answerer.join(timeout=10.0)
        assert answerer.failures == []
        assert answerer.answered.is_set()
    finally:
        os.close(user_master)
        os.close(user_slave)


@pytest.mark.posix_only
def test_setup_recovery_decline_continues_detached_with_enriched_give_up(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """[SUM-7.4] declining the TUI offer continues the run detached.

    The decline consumes the single attempt: no second offer, no lease, and
    the next generation starts without an acknowledged attach.
    """

    import asyncio
    import pty as pty_module

    from taut_tui.screens import ConfirmationScreen

    monkeypatch.setenv("TAUT_SUMMON_RESUME_BACKOFF", "0.1")
    user_master, user_slave = pty_module.openpty()
    try:
        db, prompt_path, log = _prepare_gate_recovery(
            tmp_path,
            monkeypatch,
            name="declined",
            marker="tui-decline-orientation-probe",
            user_master=user_master,
            user_slave=user_slave,
        )
        errors: list[BaseException] = []

        async def exercise() -> None:
            app = _gate_app(db)
            async with app.run_test(size=(100, 30)) as pilot:
                await pilot.pause()
                future = _start_owned_gate_run(app, "declined", prompt_path)

                offer = await _pushed_confirmation(pilot, app, timeout=45.0)
                assert "Trust this folder?" in offer.prompt
                offer.action_reject()

                modals: list[Any] = []

                def finished() -> bool:
                    if isinstance(app.screen, ConfirmationScreen):
                        modals.append(app.screen)
                    return bool(future.done())

                await _await_until(
                    pilot, finished, message="declined run completion", timeout=90.0
                )
                assert modals == []
                assert app.suspensions == 0
                error = future.exception()
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
        os.close(user_master)
        os.close(user_slave)


@pytest.mark.posix_only
def test_host_shutdown_during_offer_spawns_nothing_further(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """[TUI-11.3] closing the TUI over a pending offer takes the shutdown class."""

    import asyncio
    import pty as pty_module

    user_master, user_slave = pty_module.openpty()
    try:
        db, prompt_path, log = _prepare_gate_recovery(
            tmp_path,
            monkeypatch,
            name="stopped",
            marker="tui-shutdown-orientation-probe",
            user_master=user_master,
            user_slave=user_slave,
        )
        futures: list[Any] = []

        async def exercise() -> None:
            app = _gate_app(db)
            async with app.run_test(size=(100, 30)) as pilot:
                await pilot.pause()
                futures.append(_start_owned_gate_run(app, "stopped", prompt_path))
                offer = await _pushed_confirmation(pilot, app, timeout=45.0)
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
        os.close(user_master)
        os.close(user_slave)
