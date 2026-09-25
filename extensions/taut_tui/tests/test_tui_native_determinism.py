"""Native owner proofs, not a diagnosis of historical Windows failures."""

from __future__ import annotations

import os
import sys
import threading
import time
from collections.abc import Callable, Iterator
from concurrent.futures import FIRST_COMPLETED, Future, wait
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from _completion import Completion, CompletionKey, CompletionScope, CompletionTimeout
from tests.helpers.terminal_probe import HostTerminal

pytestmark = pytest.mark.sqlite_only


@pytest.mark.skipif(os.name != "nt", reason="requires native Windows ConPTY")
def test_quiet_native_exit_is_published_before_output_drain_starts() -> None:
    from taut_summon._adapter import AdapterEvent, ExitEvent
    from taut_summon._pty import PtyAdapter, PtySpec
    from taut_summon._pty_windows import WindowsPtyHandle

    # The existing native adapter tests use ten-second owner containment.
    # This phase starts at spawn and is not restarted by the monitor wakeup.
    deadline = time.monotonic() + 10.0
    handle = PtyAdapter(
        PtySpec(
            name="quiet-native-exit",
            argv=(sys.executable, "-c", "raise SystemExit(7)"),
        )
    ).spawn(system_prompt="unused", env={})
    assert isinstance(handle, WindowsPtyHandle)
    events: list[AdapterEvent] = []
    failures: list[BaseException] = []
    consumer: threading.Thread | None = None

    def consume_events() -> None:
        try:
            events.extend(handle.events())
        except BaseException as exc:  # noqa: BLE001 - retain for the observing test
            failures.append(exc)

    try:
        assert handle._drain._started is False
        assert handle._exit_monitor_done.wait(max(0.0, deadline - time.monotonic()))
        # The Event precedes final exit publication in the real monitor. Its
        # retirement, not that earlier wakeup, is the publication fence.
        handle._exit_monitor.join(max(0.0, deadline - time.monotonic()))
        assert not handle._exit_monitor.is_alive()
        assert handle._exit_monitor_failure is None
        assert handle._returncode == 7
        assert handle._exit_emitted is True
        assert handle._events_claimed is False
        assert handle._drain._started is False
        assert not handle._drain._thread.is_alive()

        # Only now create the one public event consumer. No output read or
        # EOF was needed to make the quiet child's real process exit visible.
        consumer = threading.Thread(target=consume_events, daemon=True)
        consumer.start()
        consumer.join(timeout=10.0)
        assert not consumer.is_alive()
        assert failures == []
        assert [
            event.returncode for event in events if isinstance(event, ExitEvent)
        ] == [7]
    finally:
        try:
            handle.close()
        finally:
            if consumer is not None:
                consumer.join(timeout=10.0)
                assert not consumer.is_alive()
            assert not handle._exit_monitor.is_alive()
            assert not handle._drain._thread.is_alive()
            assert not handle._reply_writer._thread.is_alive()

    assert handle._close_state == "closed"
    assert handle._process_handle is None
    assert handle._input_write is None
    assert handle._output_read is None


class _NativeAttachProof:
    """Observe actual attach I/O owners without adding a terminal reader."""

    def __init__(
        self, patch: pytest.MonkeyPatch, scope: CompletionScope, marker: bytes
    ) -> None:
        from taut_summon._pty import PtyAdapter
        from taut_summon._pty_windows import _AttachSession

        self.scope = scope
        self.patch = patch
        self.marker = marker
        self.handle: Any = None
        self.providers: list[tuple[Any, tuple[int, float]]] = []
        self._provider_capacity = 2
        self.session: Any = None
        self.provider_identity: tuple[int, float] | None = None
        self.input_identity: tuple[Any, int, threading.Thread] | None = None
        self.cancel_results: list[bool] = []
        self.aborted_reads: list[tuple[Any, int, threading.Thread]] = []
        self.output = b""
        self.input_tail = b""
        self.detach_read = False
        self.detach_deadline: float | None = None
        self.lock = threading.Lock()
        self.started: Completion[Any] = scope.expect(
            CompletionKey(self, "attach.started", self)
        )
        self.retired: Completion[str] | None = None
        self.menu: Completion[None] | None = None
        self.chat: Completion[None] | None = None
        self.echo: Completion[None] | None = None
        self.next_read: Completion[None] | None = None
        original_spawn = PtyAdapter.spawn
        original_run = _AttachSession.run

        def spawn(adapter: Any, **kwargs: Any) -> Any:
            import psutil  # type: ignore[import-untyped]

            # An already-wired member first starts detached, then the existing
            # recovery transition retires it and starts the attached generation.
            assert len(self.providers) < self._provider_capacity, (
                "bounded initial/recovery generations"
            )
            if self.providers:
                assert self.providers[-1][0]._close_state == "closed", (
                    "previous provider must retire before recovery spawn"
                )
            handle = original_spawn(adapter, **kwargs)
            try:
                identity = (handle.pid, psutil.Process(handle.pid).create_time())
            except BaseException:
                handle.close()
                raise
            self.providers.append((handle, identity))
            return handle

        def run(session: Any) -> str:
            matches = [
                identity
                for handle, identity in self.providers
                if handle is session.owner
            ]
            assert len(matches) == 1, "attach belongs to an observed generation"
            self.handle = session.owner
            self.provider_identity = matches[0]
            assert self.session is None, "one attach per native run"
            self._observe_session(session)
            assert self.retired is not None
            try:
                result = original_run(session)
            except BaseException as error:
                self.retired.fail(self.retired.key, error)
                raise
            self.retired.succeed(self.retired.key, result)
            return str(result)

        patch.setattr(PtyAdapter, "spawn", spawn)
        patch.setattr(_AttachSession, "run", run)

    def observe_driver_return(self, finished: Future[None]) -> None:
        """Retain early producer failure instead of reporting an attach timeout."""

        def returned(done: Future[None]) -> None:
            with self.lock:
                if self.started.snapshot() is not None:
                    return
                if done.cancelled():
                    self.started.cancel(self.started.key)
                elif (error := done.exception()) is not None:
                    self.started.fail(self.started.key, error)
                else:
                    self.started.fail(
                        self.started.key,
                        AssertionError("driver returned before native attach"),
                    )

        finished.add_done_callback(returned)

    def _observe_session(self, session: Any) -> None:
        self.session = session
        self.retired = self.scope.expect(
            CompletionKey(session.owner, "attach.retired", session)
        )
        self.menu = self.scope.expect(CompletionKey(session, "host.menu", session))
        self.chat = self.scope.expect(CompletionKey(session, "host.chat", session))
        self.echo = self.scope.expect(CompletionKey(session, "host.echo", session))
        self.next_read = self.scope.expect(
            CompletionKey(session, "input.read_after_detach", session)
        )
        original_read = session.api.read
        original_cancel = session.api.cancel_thread
        original_write = session.api.write
        original_cleanup = session._cleanup

        def read(handle: int, size: int = 4096) -> bytes:
            return self._read(session, original_read, handle, size)

        def cancel(handle: int, *, retiring: bool) -> bool:
            is_input = handle == session.input_thread_handle
            result = bool(original_cancel(handle, retiring=retiring))
            if is_input:
                with self.lock:
                    self.cancel_results.append(result)
            return result

        def write(handle: int, data: bytes) -> None:
            original_write(handle, data)
            if handle == session.output_handle:
                self._host_write(data)

        def cleanup() -> None:
            try:
                if self.detach_read and self.detach_deadline is not None:
                    assert self.next_read is not None
                    # Hold the real cleanup before its done transition until
                    # the reader has advanced beyond that check. Entry alone
                    # is not pending-I/O evidence: success + 995 remain required.
                    self.next_read.wait_sync(
                        deadline=self.detach_deadline,
                        description="next real input read after detach",
                    )
            finally:
                original_cleanup()

        self.patch.setattr(session.api, "read", read)
        self.patch.setattr(session.api, "cancel_thread", cancel)
        self.patch.setattr(session.api, "write", write)
        self.patch.setattr(session, "_cleanup", cleanup)
        with self.lock:
            self.started.succeed(self.started.key, session)

    def _read(
        self,
        session: Any,
        original: Callable[[int, int], bytes],
        handle: int,
        size: int,
    ) -> bytes:
        from taut_summon._win32_io import ERROR_OPERATION_ABORTED, Win32IoError

        identity = None
        if handle == session.input_handle:
            identity = (session, handle, threading.current_thread())
            with self.lock:
                if self.input_identity is None:
                    self.input_identity = identity
                assert self.input_identity == identity
                assert self.next_read is not None
                if self.detach_read and self.next_read.snapshot() is None:
                    self.next_read.succeed(self.next_read.key, None)
        try:
            result = original(handle, size)
        except Win32IoError as error:
            if identity is not None and error.error_code == ERROR_OPERATION_ABORTED:
                with self.lock:
                    self.aborted_reads.append(identity)
            raise
        if identity is not None:
            with self.lock:
                self.detach_read |= b"\x1c\x1c" in self.input_tail + result
                self.input_tail = result[-1:]
        return result

    def _host_write(self, data: bytes) -> None:
        with self.lock:
            self.output += data
            assert len(self.output) <= 32768, "bounded native host transcript"
            for record, needle in (
                (self.menu, b"Trust this folder?"),
                (self.chat, b"chat>"),
                (self.echo, b"echo:" + self.marker),
            ):
                assert record is not None
                if record.snapshot() is None and needle in self.output:
                    record.succeed(record.key, None)


def test_native_host_prompt_observer_does_not_require_terminal_padding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # ConPTY presents a terminal screen, not the provider's original write
    # bytes. The prompt token is stable; a trailing blank is not its identity.
    with CompletionScope() as scope:
        proof = _NativeAttachProof(monkeypatch, scope, b"marker")
        proof.menu = scope.expect(CompletionKey(proof, "host.menu", proof))
        proof.chat = scope.expect(CompletionKey(proof, "host.chat", proof))
        proof.echo = scope.expect(CompletionKey(proof, "host.echo", proof))
        deadline = scope.now() + 2
        proof._host_write(b"\x1b[?2004h\r\ncha")
        assert proof.chat.snapshot() is None
        proof._host_write(b"t>")
        proof.chat.wait_sync(deadline=deadline, description="complete chat prompt")
        assert proof.echo.snapshot() is None


@pytest.mark.parametrize("fault", ["none", "one-provider", "after-recovery"])
def test_native_observer_retains_both_real_recovery_provider_generations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fault: str,
) -> None:
    """Real driver recovery through the same observer; no native-I/O claim."""
    from _summon_completion import LeaseOrStop, ProviderConsumption
    from taut_summon import SummonController, SummonOperationError, SummonRequest
    from taut_summon._driver import DriverError
    from test_tui_summon import (
        _gate_starts,
        _GateAnswerer,
        _GateHostInteraction,
        _prepare_gate_recovery,
    )

    signal = LeaseOrStop()

    class Interaction(_GateHostInteraction):
        @contextmanager
        def terminal_lease(self) -> Iterator[Any]:
            with super().terminal_lease() as lease:
                signal.set()
                yield lease

    terminal = HostTerminal.open()
    try:
        marker = "real-recovery-generation"
        db, prompt, log = _prepare_gate_recovery(
            tmp_path,
            monkeypatch,
            name="recovery-observer",
            marker=marker,
            terminal=terminal,
        )
        controller = SummonController(db_path=db)
        request = SummonRequest(
            name="recovery-observer",
            threads=("general",),
            persona=None,
            system_prompt_file=str(prompt),
            rate_limit=None,
            provider_flag="pty",
        )
        interaction = Interaction(
            input_fd=terminal.lease_input_fd, output_fd=terminal.lease_output_fd
        )
        with (
            CompletionScope() as scope,
            ProviderConsumption(monkeypatch, marker, 45) as consumed,
        ):
            proof = _NativeAttachProof(monkeypatch, scope, marker.encode())
            if fault == "one-provider":
                # Restore only the rejected one-provider assumption, before
                # allocation, so the causal mutant cannot orphan a new child.
                proof._provider_capacity = 1
            worker, finished = _gate_driver(controller, request, interaction)
            answerer = _GateAnswerer(terminal, lease_acquired=signal)
            deadline = scope.now() + 45
            answerer.start()
            worker.start()

            def complete_recovery() -> None:
                done, _pending = wait(
                    (finished, answerer.completion),
                    timeout=max(0, deadline - scope.now()),
                    return_when=FIRST_COMPLETED,
                )
                assert done, "real recovery did not publish a terminal phase"
                if finished in done:
                    finished.result()  # Original driver failure, never timeout blame.
                    raise AssertionError("driver returned before recovery answerer")
                answerer.completion.result()
                assert answerer.detach_started_at is not None
                owner = consumed.wait_sync(deadline=answerer.detach_started_at + 45)
                assert len(proof.providers) == 2
                assert owner is proof.providers[1][0]
                assert proof.providers[0][1] != proof.providers[1][1]
                assert proof.providers[0][0]._close_state == "closed"
                assert len(interaction.notices) == 1
                excerpt = interaction.notices[0].screen_excerpt
                assert excerpt is not None and "Trust this folder?" in excerpt
                assert _gate_starts(log) == 2
                if fault == "after-recovery":
                    raise RuntimeError("probe failed after real recovery")
                controller.stop(request.name)
                finished.result(timeout=20)

            try:
                if fault == "one-provider":
                    with pytest.raises(
                        SummonOperationError,
                        match="bounded initial/recovery generations",
                    ) as caught:
                        complete_recovery()
                    assert isinstance(caught.value.__cause__, DriverError)
                    assert isinstance(caught.value.__cause__.__cause__, AssertionError)
                    assert len(proof.providers) == 1
                elif fault == "after-recovery":
                    with pytest.raises(
                        RuntimeError, match="probe failed after real recovery"
                    ):
                        complete_recovery()
                else:
                    complete_recovery()
            finally:
                answerer.request_stop()
                try:
                    _retire_gate_run(
                        controller, request.name, finished, worker, proof.providers
                    )
                finally:
                    answerer.join(timeout=20)
                    assert not answerer.is_alive()
            assert all(handle._close_state == "closed" for handle, _ in proof.providers)
            if fault != "one-provider":
                assert finished.result() is None
    finally:
        terminal.close()


def _gate_driver(
    controller: Any, request: Any, interaction: Any
) -> tuple[threading.Thread, Future[None]]:
    finished: Future[None] = Future()

    def run() -> None:
        try:
            controller.run_foreground(request, interaction)
        except BaseException as error:  # noqa: BLE001 - retain for the observing test
            finished.set_exception(error)
        else:
            finished.set_result(None)

    return threading.Thread(
        target=run, daemon=True, name="native-gate-driver"
    ), finished


def _retire_gate_run(
    controller: Any,
    name: str,
    finished: Future[None],
    worker: threading.Thread,
    providers: list[tuple[Any, tuple[int, float]]],
) -> None:
    from taut._cleanup import capture_cleanup_failure

    primary = sys.exception()
    failure: Exception | None = None
    if not finished.done():
        stop_error = capture_cleanup_failure(None, lambda: controller.stop(name))
        # Retirement can win between the pending check and the public STOP
        # request. It is then already contained, not a cleanup failure.
        if not finished.done():
            failure = stop_error
    for handle, _ in providers:
        failure = capture_cleanup_failure(failure, handle.close)
    failure = capture_cleanup_failure(failure, lambda: worker.join(timeout=20))
    if worker.is_alive():
        failure = failure or AssertionError("gate driver did not retire")
    if failure is not None:
        if primary is None:
            raise failure
        primary.add_note(f"gate cleanup also failed: {type(failure).__name__}")


def test_native_gate_cleanup_closes_every_real_provider_after_a_close_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from taut_summon._pty import PtyAdapter, PtySpec

    adapter = PtyAdapter(
        PtySpec(name="cleanup-proof", argv=(sys.executable, "-c", "input()"))
    )
    handles: list[Any] = []
    with ExitStack() as cleanup:
        for _ in range(2):
            handle = adapter.spawn(system_prompt="unused", env={})
            cleanup.callback(handle.close)
            handles.append(handle)
        error = ValueError("first provider close failed after real retirement")
        finished: Future[None] = Future()
        finished.set_result(None)
        worker = threading.Thread(target=lambda: None)
        worker.start()
        cleanup.callback(worker.join, timeout=20)
        original_close = handles[0].close

        def first_close() -> None:
            original_close()
            raise error

        monkeypatch.setattr(handles[0], "close", first_close)
        with pytest.raises(ValueError) as caught:
            _retire_gate_run(
                None,
                "unused",
                finished,
                worker,
                [(handle, (handle.pid, 0.0)) for handle in handles],
            )
        assert caught.value is error
        assert all(handle._close_state == "closed" for handle in handles)
        assert not worker.is_alive()


@pytest.mark.parametrize("outcome", ["error", "cancelled", "returned"])
def test_native_attach_observer_retains_early_driver_outcome(
    monkeypatch: pytest.MonkeyPatch, outcome: str
) -> None:
    from _completion import CompletionCancelled

    error = RuntimeError("real retained driver failure")
    finished: Future[None] = Future()
    if outcome == "error":
        finished.set_exception(error)
        expected: type[BaseException] = RuntimeError
    elif outcome == "cancelled":
        finished.cancel()
        expected = CompletionCancelled
    else:
        finished.set_result(None)
        expected = AssertionError
    with CompletionScope() as scope:
        proof = _NativeAttachProof(monkeypatch, scope, b"early-return")
        proof.observe_driver_return(finished)
        with pytest.raises(expected) as raised:
            proof.started.wait_sync(
                deadline=scope.now() + 2, description="early driver outcome"
            )
        if outcome == "error":
            assert raised.value is error
        elif outcome == "returned":
            assert str(raised.value) == "driver returned before native attach"


def test_native_attach_observer_does_not_replace_started_on_driver_return(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with CompletionScope() as scope:
        proof = _NativeAttachProof(monkeypatch, scope, b"started")
        finished: Future[None] = Future()
        proof.observe_driver_return(finished)
        session = object()
        proof.started.succeed(proof.started.key, session)
        finished.set_result(None)
        assert (
            proof.started.wait_sync(
                deadline=scope.now() + 2, description="retained attach owner"
            )
            is session
        )


@dataclass(frozen=True)
class _NativeGateEvidence:
    terminal: HostTerminal
    log: Path
    provider_identity: tuple[int, float]
    probe: _NativeAttachProof


def _native_gate_run(
    *,
    patch: pytest.MonkeyPatch,
    db: Path,
    directory: Path,
    terminal: HostTerminal,
    pretrusted: bool,
    marker: str,
) -> _NativeGateEvidence:
    from _summon_completion import ProviderConsumption
    from taut_summon import SummonController, SummonRequest
    from test_tui_summon import _configure_gate_pty, _GateHostInteraction

    log = _configure_gate_pty(patch, log_dir=directory, pretrusted=pretrusted)
    orientation = marker + "-orientation"
    prompt = directory / "prompt.txt"
    prompt.write_text(orientation, encoding="utf-8")
    request = SummonRequest(
        name="native-isolation",
        threads=("general",),
        persona=None,
        system_prompt_file=str(prompt),
        rate_limit=None,
        provider_flag="pty",
    )
    controller = SummonController(db_path=db)
    interaction = _GateHostInteraction(
        input_fd=terminal.lease_input_fd, output_fd=terminal.lease_output_fd
    )
    worker, finished = _gate_driver(controller, request, interaction)

    with (
        CompletionScope() as scope,
        ProviderConsumption(patch, orientation, 30) as consumed,
    ):
        proof = _NativeAttachProof(patch, scope, marker.encode())
        proof.observe_driver_return(finished)
        returned = scope.observe_future(
            finished, owner=controller, phase="run.returned"
        )
        deadline = scope.now() + 30
        worker.start()
        try:
            proof.started.wait_sync(deadline=deadline, description="native attach")
            assert proof.chat is not None and proof.menu is not None
            if not pretrusted:
                proof.menu.wait_sync(
                    deadline=deadline, description="recovery menu write"
                )
                terminal.write(b"\x14")
            try:
                proof.chat.wait_sync(
                    deadline=deadline, description="native chat prompt write"
                )
            except CompletionTimeout as error:
                # Content-free boundary diagnostics, not timeout-based blame.
                error.add_note(
                    str(
                        {
                            "host_bytes": len(proof.output),
                            "prompt_token_seen": b"chat>" in proof.output,
                            "padded_prompt_seen": b"chat> " in proof.output,
                            "driver_returned": finished.done(),
                            "attach_retired": proof.retired.snapshot() is not None
                            if proof.retired is not None
                            else False,
                        }
                    )
                )
                raise
            echo_deadline = scope.now() + 15
            terminal.write(marker.encode() + b"\r")
            assert proof.echo is not None
            proof.echo.wait_sync(
                deadline=echo_deadline, description="native echo write"
            )
            # The old echo is now in the actual host pipe, deliberately unread.
            detach_deadline = scope.now() + 30
            proof.detach_deadline = detach_deadline
            terminal.write(b"\x1c\x1c")
            assert proof.retired is not None
            assert (
                proof.retired.wait_sync(
                    deadline=detach_deadline, description="native attach retirement"
                )
                == "detached"
            )
            consumed.wait_sync(deadline=detach_deadline)
            controller.stop("native-isolation")
            returned.wait_sync(
                deadline=scope.now() + 20, description="driver retirement"
            )
        finally:
            _retire_gate_run(
                controller, request.name, finished, worker, proof.providers
            )

        assert proof.provider_identity is not None
        assert len(proof.providers) == (1 if pretrusted else 2)
        assert proof.session.reader is not None
        assert not proof.session.reader.is_alive()
        assert proof.session.input_thread_handle is None
        assert proof.session.output_handle is None
        for handle, _ in proof.providers:
            assert not handle._exit_monitor.is_alive()
            assert not handle._drain._thread.is_alive()
            assert not handle._reply_writer._thread.is_alive()
        return _NativeGateEvidence(terminal, log, proof.provider_identity, proof)


@pytest.mark.skipif(
    os.name != "nt", reason="requires native Windows cancelled ReadFile"
)
@pytest.mark.parametrize("reuse_host", [False, True], ids=["isolated", "reuse-mutant"])
def test_cancelled_native_attach_cannot_leak_unread_output_into_recovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, reuse_host: bool
) -> None:
    from taut_summon._pty_windows import _DETACH_RESET
    from test_tui_summon import _gate_db, _gate_inputs

    db = _gate_db(tmp_path)
    old_marker = "native-old-unread-output"
    new_marker = "native-new-recovery-output"
    first_terminal = HostTerminal.open()
    second_terminal: HostTerminal | None = None
    try:
        # This narrow fixture mutant restores the former shared host session.
        # Both cases still run real providers, reads, cancellation and cleanup.
        second_terminal = first_terminal if reuse_host else HostTerminal.open()
        with monkeypatch.context() as first_patch:
            first = _native_gate_run(
                patch=first_patch,
                db=db,
                directory=tmp_path / "first",
                terminal=first_terminal,
                pretrusted=True,
                marker=old_marker,
            )
        with monkeypatch.context() as second_patch:
            second = _native_gate_run(
                patch=second_patch,
                db=db,
                directory=tmp_path / "second",
                terminal=second_terminal,
                pretrusted=False,
                marker=new_marker,
            )

        # Check only after both source-owned retirements, never after a quiet
        # interval. A reused host object exposes the first run's unread bytes.
        second_bytes = second_terminal.read_available()
        assert first.log != second.log
        assert first.provider_identity != second.provider_identity
        assert any(
            new_marker + "-orientation" in raw for raw in _gate_inputs(second.log)
        )
        assert all(old_marker not in raw for raw in _gate_inputs(second.log))

        identity = first.probe.input_identity
        assert identity is not None and identity[0] is first.probe.session
        assert identity[2] is first.probe.session.reader
        assert first.probe.cancel_results == [True], (
            "native cancellation proof not established: the real reader did not "
            f"have a successfully cancelled ReadFile: {first.probe.cancel_results!r}"
        )
        assert first.probe.aborted_reads == [identity], (
            "native cancellation proof not established: no matching aborted ReadFile"
        )

        def assert_output_isolation() -> None:
            assert new_marker.encode() in second_bytes
            assert old_marker.encode() not in second_bytes, (
                "old unread host output crossed into the recovery session"
            )

        if reuse_host:
            assert first.terminal is second.terminal
            assert _DETACH_RESET in second_bytes
            with pytest.raises(AssertionError, match="old unread host output crossed"):
                assert_output_isolation()
        else:
            assert_output_isolation()
            first_bytes = first_terminal.read_available()
            assert old_marker.encode() in first_bytes
            assert _DETACH_RESET in first_bytes
            assert first.terminal is not second.terminal
    finally:
        first_terminal.close()
        if second_terminal is not None and second_terminal is not first_terminal:
            second_terminal.close()
