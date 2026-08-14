"""TUI extension Summon worker, exact-run, and terminal-lease behavior.

Spec references:
- docs/specs/10-taut-tui.md [TUI-11], [TUI-12.3]
"""

from __future__ import annotations

from contextlib import contextmanager
from threading import Event, Lock, Thread
from typing import Any

import pytest

pytestmark = pytest.mark.sqlite_only


class _Member:
    def __init__(self, name: str) -> None:
        self.member_id = f"id-{name}"
        self.name = name
        self.provider = "scripted"
        self.provider_session_id = "session-1"


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
            terminal=True,
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
        terminal=True,
        persona="careful",
        system_prompt_file="prompt.txt",
        rate_limit=12,
        attach=True,
        detach=False,
        provider_flag="scripted",
        takeover=True,
    )


class _LeaseApp:
    def __init__(self, *, accept: bool = True) -> None:
        self.accept = accept
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
        self._handler = Thread(target=message.hold, args=(self,))
        self._handler.start()
        return True

    def join_handler(self) -> None:
        if self._handler is not None:
            self._handler.join(timeout=5)
            assert not self._handler.is_alive()


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

    with (
        pytest.raises(RuntimeError, match="not accepting"),
        interaction.terminal_lease(),
    ):
        pytest.fail("rejected lease body must not run")

    app.accept = True
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
