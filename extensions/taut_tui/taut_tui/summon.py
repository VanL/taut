"""Optional public Summon adapter owned by the TUI extension.

Spec references:
- docs/specs/10-taut-tui.md [TUI-11], [TUI-12.3]
"""

from __future__ import annotations

import importlib
import logging
import os
import sys
import threading
import uuid
from collections import deque
from collections.abc import Callable, Iterator
from concurrent.futures import Future, ThreadPoolExecutor, wait
from contextlib import contextmanager, suppress
from dataclasses import dataclass, field
from typing import Any, Protocol, cast

from textual.message import Message as TextualMessage

from taut_tui.widgets import escape_display_text


class SummonUnavailable(RuntimeError):
    """The optional Summon extension is not installed."""


def load_summon_api(
    *,
    import_module: Callable[[str], object] = importlib.import_module,
) -> Any:
    """Load only the public optional facade with exact missing-package diagnosis."""

    try:
        return import_module("taut_summon")
    except ModuleNotFoundError as exc:
        if exc.name != "taut_summon":
            raise
        raise SummonUnavailable(
            "Summon support requires the optional taut-summon package."
        ) from None


class _RunHandle(Protocol):
    member: Any

    def request_stop(self) -> None: ...


class _TerminalLease(Protocol):
    input_fd: int
    output_fd: int


class _TerminalAttachNotice(Protocol):
    @property
    def member(self) -> str: ...

    @property
    def provider(self) -> str: ...

    @property
    def detach_hint(self) -> str: ...


class _Controller(Protocol):
    def provider_names(self) -> tuple[str, ...]: ...

    def list_live(self) -> tuple[object, ...]: ...

    def status(self, name: str) -> object: ...

    def stop(self, name: str) -> object: ...

    def run_foreground(
        self,
        request: object,
        interaction: object,
        *,
        install_signal_handlers: bool,
        on_ready: Callable[[_RunHandle], None],
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class OwnedSummonRun:
    """Public visual projection of one TUI-owned foreground worker."""

    token: str
    pending: bool
    member_id: str | None
    member_name: str | None


@dataclass(frozen=True, slots=True)
class OwnedSummonShutdown:
    """Bounded result of stopping the exact TUI-owned foreground workers."""

    completed_tokens: tuple[str, ...]
    unresolved: tuple[OwnedSummonRun, ...]
    errors: tuple[OwnedSummonFailure, ...]

    @property
    def complete(self) -> bool:
        return not self.unresolved and not self.errors


@dataclass(frozen=True, slots=True)
class OwnedSummonFailure:
    """One exact foreground worker failure with stable ownership context."""

    token: str
    member_name: str | None
    error: str


@dataclass(slots=True)
class _OwnedRecord:
    token: str
    handle: _RunHandle | None = None
    future: Future[None] | None = None
    cancel: threading.Event = field(default_factory=threading.Event)


class TuiSummonOperations:
    """Supervise exact foreground runs without inspecting Summon internals."""

    def __init__(
        self,
        *,
        controller: _Controller | None = None,
        db_path: str | None = None,
        ready_callback: Callable[[OwnedSummonRun], None] | None = None,
    ) -> None:
        if controller is None:
            api = load_summon_api()
            controller_type = api.SummonController
            controller = controller_type(db_path=db_path)
        self._controller = controller
        self._ready_callback = ready_callback
        self._control_executor = ThreadPoolExecutor(
            max_workers=2,
            thread_name_prefix="taut-tui-summon-control",
        )
        self._supervisor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="taut-tui-summon-supervisor",
        )
        self._lock = threading.Lock()
        self._owned: dict[str, _OwnedRecord] = {}
        self._closed = False

    def provider_names(self) -> tuple[str, ...]:
        return self._controller.provider_names()

    def build_request(
        self,
        *,
        name: str,
        threads: tuple[str, ...],
        terminal: bool,
        persona: str | None,
        system_prompt_file: str | None,
        rate_limit: int | None,
        attach: bool,
        detach: bool,
        provider_flag: str | None,
        takeover: bool,
    ) -> object:
        """Construct the public typed request without reusing CLI parsing."""

        api = load_summon_api()
        return api.SummonRequest(
            name=name,
            threads=threads,
            terminal=terminal,
            persona=persona,
            system_prompt_file=system_prompt_file,
            rate_limit=rate_limit,
            attach=attach,
            detach=detach,
            provider_flag=provider_flag,
            takeover=takeover,
        )

    def list_live(self) -> tuple[object, ...]:
        return self._controller.list_live()

    def submit_list(self) -> Future[tuple[object, ...]]:
        with self._lock:
            self._ensure_open()
        return self._control_executor.submit(self._controller.list_live)

    def submit_status(self, name: str) -> Future[object]:
        with self._lock:
            self._ensure_open()
        return self._control_executor.submit(self._controller.status, name)

    def submit_stop(self, name: str) -> Future[object]:
        with self._lock:
            self._ensure_open()
        return self._control_executor.submit(self._controller.stop, name)

    def start(
        self,
        request: object,
        interaction: object,
    ) -> tuple[str, Future[None]]:
        with self._lock:
            if self._closed:
                raise RuntimeError("Summon operation owner is closed")
            token = uuid.uuid4().hex
            record = _OwnedRecord(token=token)
            self._owned[token] = record

        def on_ready(handle: _RunHandle) -> None:
            callback: Callable[[OwnedSummonRun], None] | None = None
            stop_after_close = False
            with self._lock:
                current = self._owned.get(token)
                if current is not record:
                    return
                if self._closed:
                    stop_after_close = True
                else:
                    current.handle = handle
                    projection = self._project(current)
                    callback = self._ready_callback
            if stop_after_close:
                handle.request_stop()
                return
            if callback is not None:
                callback(projection)

        def run() -> None:
            self._run_owned(record, request, interaction, on_ready)

        future = self._submit_foreground(run)
        with self._lock:
            record.future = future
        return token, future

    def _run_owned(
        self,
        record: _OwnedRecord,
        request: object,
        interaction: object,
        on_ready: Callable[[_RunHandle], None],
    ) -> None:
        try:
            if record.cancel.is_set():
                return
            self._controller.run_foreground(
                request,
                interaction,
                install_signal_handlers=False,
                on_ready=on_ready,
            )
        finally:
            release_worker = getattr(interaction, "release_current_worker", None)
            if callable(release_worker):
                release_worker()
            with self._lock:
                if self._owned.get(record.token) is record:
                    self._owned.pop(record.token, None)

    def _submit_foreground(self, run: Callable[[], None]) -> Future[None]:
        """Run one foreground worker on a daemon thread with Future semantics.

        Daemon threads keep a hung provider bootstrap from pinning interpreter
        exit; orderly shutdown still flows through ``stop_owned_and_wait``.
        """

        future: Future[None] = Future()

        def target() -> None:
            if not future.set_running_or_notify_cancel():
                return
            try:
                run()
            except BaseException as exc:  # noqa: BLE001 approved [DOM-10.2.1] [RUFF-SUP-087] exception
                future.set_exception(exc)
            else:
                future.set_result(None)

        threading.Thread(
            target=target,
            name="taut-tui-summon-foreground",
            daemon=True,
        ).start()
        return future

    def owned_runs(self) -> tuple[OwnedSummonRun, ...]:
        with self._lock:
            return tuple(self._project(record) for record in self._owned.values())

    def request_owned_stops(self) -> None:
        with self._lock:
            handles = tuple(
                record.handle
                for record in self._owned.values()
                if record.handle is not None
            )
        for handle in handles:
            handle.request_stop()

    def quit_block_reason(self) -> str | None:
        runs = self.owned_runs()
        if not runs:
            return None
        pending = sum(run.pending for run in runs)
        ready = len(runs) - pending
        parts: list[str] = []
        if pending:
            parts.append(f"{pending} Summon run(s) still starting")
        if ready:
            parts.append(f"{ready} TUI-owned Summon run(s) still live")
        return "; ".join(parts) + "."

    def has_pending_owned(self) -> bool:
        return any(run.pending for run in self.owned_runs())

    def stop_owned_and_wait(
        self, *, timeout: float = 90.0
    ) -> Future[OwnedSummonShutdown]:
        """Stop exact ready handles and supervise their retained workers."""

        with self._lock:
            self._ensure_open()
            records = tuple(self._owned.values())

        def supervise() -> OwnedSummonShutdown:
            for record in records:
                if record.handle is not None:
                    record.handle.request_stop()
                else:
                    record.cancel.set()
            future_records = tuple(
                (record, record.future)
                for record in records
                if record.future is not None
            )
            done, _not_done = wait(
                tuple(future for _record, future in future_records),
                timeout=timeout,
            )
            completed: list[str] = []
            unresolved: list[OwnedSummonRun] = []
            errors: list[OwnedSummonFailure] = []
            for record in records:
                future = record.future
                if future is None or future not in done:
                    unresolved.append(self._project(record))
                    continue
                completed.append(record.token)
                error = future.exception()
                if error is not None:
                    projection = self._project(record)
                    errors.append(
                        OwnedSummonFailure(
                            token=record.token,
                            member_name=projection.member_name,
                            error=str(error) or type(error).__name__,
                        )
                    )
            return OwnedSummonShutdown(
                completed_tokens=tuple(completed),
                unresolved=tuple(unresolved),
                errors=tuple(errors),
            )

        return self._supervisor.submit(supervise)

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            records = tuple(self._owned.values())
        for record in records:
            record.cancel.set()
        self.request_owned_stops()
        self._control_executor.shutdown(wait=False, cancel_futures=False)
        self._supervisor.shutdown(wait=False, cancel_futures=False)

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("Summon operation owner is closed")

    @staticmethod
    def _project(record: _OwnedRecord) -> OwnedSummonRun:
        member = record.handle.member if record.handle is not None else None
        return OwnedSummonRun(
            token=record.token,
            pending=member is None,
            member_id=None if member is None else str(member.member_id),
            member_name=None if member is None else str(member.name),
        )


class TerminalLeaseRequest(TextualMessage):
    """Thread-safe request whose handler owns one complete suspension scope."""

    def __init__(self, bridge: SummonLogBridge | None = None) -> None:
        super().__init__()
        self.acquired = threading.Event()
        self.release = threading.Event()
        self.restored = threading.Event()
        self.error: BaseException | None = None
        self._bridge = bridge

    def hold(self, app: Any) -> None:
        """Run entirely on the UI thread until the worker releases the lease."""

        try:
            if self._bridge is not None:
                self._bridge.begin_lease()
            with app.suspend():
                self.acquired.set()
                self.release.wait()
            app.refresh(layout=True)
        except BaseException as exc:  # noqa: BLE001 approved [DOM-10.2.1] [RUFF-SUP-087] exception
            # [TUI-11.3]: exception exit from the suspend scope is a fatal
            # lease failure. Application mode cannot be safely re-entered, so
            # the TUI exits completely through normal teardown, leaving the
            # terminal restored for the shell.
            self.error = exc
            self.acquired.set()
            exit_app = getattr(app, "exit", None)
            if callable(exit_app):
                with suppress(Exception):
                    exit_app()
        finally:
            if self._bridge is not None:
                self._bridge.end_lease()
            self.restored.set()


class TerminalAttachConfirmationRequest(TextualMessage):
    """Thread-safe pre-spawn decision rendered while Textual remains active."""

    def __init__(self, notice: _TerminalAttachNotice) -> None:
        super().__init__()
        self.notice = notice
        self.resolved = threading.Event()
        self.decision: bool | None = None
        self.error: BaseException | None = None
        self.on_resolved: Callable[[], None] | None = None
        self._lock = threading.Lock()

    def resolve(self, decision: bool) -> None:
        with self._lock:
            if self.resolved.is_set():
                return
            self.decision = bool(decision)
            self.resolved.set()
            callback = self.on_resolved
        self._notify(callback)

    def fail(self, error: BaseException) -> None:
        with self._lock:
            if self.resolved.is_set():
                return
            self.error = error
            self.resolved.set()
            callback = self.on_resolved
        self._notify(callback)

    @staticmethod
    def _notify(callback: Callable[[], None] | None) -> None:
        if callback is None:
            return
        try:
            callback()
        except Exception:  # noqa: BLE001 approved [DOM-10.2.1] [RUFF-SUP-086] exception
            return


class TuiSummonInteraction:
    """Cooperative public Summon interaction over Textual's suspend seam."""

    def __init__(
        self,
        app: Any,
        *,
        log_bridge: SummonLogBridge | None = None,
        timeout: float = 30.0,
    ) -> None:
        self._app = app
        self._log_bridge = log_bridge
        self._timeout = timeout
        self._lock = threading.Lock()
        self._closed = False
        self._terminal_owner: int | None = None
        self._pending_confirmation: TerminalAttachConfirmationRequest | None = None
        self._lease_active = False
        self._lease_broken = False

    def terminal_availability(self, intent: object) -> object:
        del intent
        api = load_summon_api()
        if not _standard_terminal_is_suitable():
            return api.TerminalAvailability.NO_TTY
        if not _framework_can_suspend(self._app):
            return api.TerminalAvailability.UNAVAILABLE
        with self._lock:
            if self._closed or self._terminal_owner is not None or self._lease_broken:
                return api.TerminalAvailability.UNAVAILABLE
        return api.TerminalAvailability.AVAILABLE

    def confirm_terminal_attach(
        self,
        notice: _TerminalAttachNotice,
        *,
        cancel: threading.Event | None = None,
    ) -> bool:
        owner = threading.get_ident()
        request = TerminalAttachConfirmationRequest(notice)
        with self._lock:
            if self._closed:
                return False
            if self._lease_broken:
                raise RuntimeError(
                    "Summon terminal is unavailable after a failed lease"
                )
            if self._terminal_owner is not None:
                # [TUI-11.3]: losing the confirm race degrades to the same
                # graceful decline as unavailability instead of failing the
                # whole run with a hard error.
                return False
            self._terminal_owner = owner
            self._pending_confirmation = request
        try:
            if not self._app.post_message(request):
                raise RuntimeError(
                    "Textual application is not accepting attach confirmations"
                )
            self._wait_for_confirmation(request, cancel)
            if request.error is not None:
                raise RuntimeError(
                    "Textual attach confirmation failed"
                ) from request.error
            decision = request.decision
            if decision is None:
                raise RuntimeError("Textual attach confirmation returned no decision")
            if not decision:
                self._release_owner(owner)
            return decision
        except BaseException:
            self._release_owner(owner)
            raise
        finally:
            with self._lock:
                if self._pending_confirmation is request:
                    self._pending_confirmation = None

    @staticmethod
    def _wait_for_confirmation(
        request: TerminalAttachConfirmationRequest,
        cancel: threading.Event | None,
    ) -> None:
        while not request.resolved.wait(timeout=0.05):
            if cancel is not None and cancel.is_set():
                request.resolve(False)
                return

    def close(self) -> None:
        with self._lock:
            self._closed = True
            pending = self._pending_confirmation
        if pending is not None:
            pending.resolve(False)

    def release_current_worker(self) -> None:
        self._release_owner(threading.get_ident())

    def _release_owner(self, owner: int) -> None:
        with self._lock:
            if self._terminal_owner == owner and not self._lease_active:
                self._terminal_owner = None

    @contextmanager
    def terminal_lease(self) -> Iterator[_TerminalLease]:  # noqa: C901 approved [DOM-10.2.1] [RUFF-SUP-088] exception
        api = load_summon_api()
        owner = threading.get_ident()
        with self._lock:
            if self._closed:
                raise RuntimeError("Summon terminal interaction is closed")
            if self._lease_broken:
                raise RuntimeError(
                    "Summon terminal is unavailable after a failed lease"
                )
            if self._terminal_owner != owner:
                raise RuntimeError(
                    "Summon terminal attach was not acknowledged by this worker"
                )
            if self._lease_active:
                raise RuntimeError("another Summon terminal lease is active")
            self._lease_active = True
        request = TerminalLeaseRequest(self._log_bridge)
        posted = False
        primary_error: BaseException | None = None
        try:
            if not self._app.post_message(request):
                raise RuntimeError(
                    "Textual application is not accepting terminal leases"
                )
            posted = True
            if not request.acquired.wait(self._timeout):
                if request.error is not None:
                    raise RuntimeError(
                        "Textual terminal suspension failed"
                    ) from request.error
                raise RuntimeError("Textual terminal suspension timed out")
            if request.error is not None:
                raise RuntimeError(
                    "Textual terminal suspension failed"
                ) from request.error
            yield cast(
                _TerminalLease,
                api.TerminalLease(input_fd=0, output_fd=1),
            )
        except BaseException as exc:
            primary_error = exc
            raise
        finally:
            cleanup_error: RuntimeError | None = None
            if posted:
                request.release.set()
                if not request.restored.wait(self._timeout):
                    cleanup_error = RuntimeError(
                        "Textual terminal restoration timed out"
                    )
                elif request.error is not None:
                    cleanup_error = RuntimeError("Textual terminal lease failed")
                    cleanup_error.__cause__ = request.error
            with self._lock:
                self._lease_active = False
                if self._terminal_owner == owner:
                    self._terminal_owner = None
                if cleanup_error is not None:
                    self._lease_broken = True
            if cleanup_error is not None:
                if primary_error is None:
                    raise cleanup_error
                primary_error.add_note(f"terminal cleanup also failed: {cleanup_error}")


def _standard_terminal_is_suitable() -> bool:
    try:
        return (
            sys.stdin.isatty()
            and sys.stdout.isatty()
            and sys.stdin.fileno() == 0
            and sys.stdout.fileno() == 1
            and os.isatty(0)
            and os.isatty(1)
        )
    except (AttributeError, OSError, ValueError):
        return False


def _framework_can_suspend(app: object) -> bool:
    return callable(getattr(app, "suspend", None)) and callable(
        getattr(app, "post_message", None)
    )


class _ForwardingHandler(logging.Handler):
    def __init__(self, owner: SummonLogBridge) -> None:
        super().__init__()
        self._owner = owner

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self._owner.accept(self.format(record))
        except Exception:  # noqa: BLE001 approved [DOM-10.2.1] [RUFF-SUP-086] exception
            self.handleError(record)


_SUMMON_LOGGER_OWNERSHIP_LOCK = threading.RLock()
_SUMMON_LOGGER_OWNERS: list[Any] = []
_SUMMON_LOGGER_PRIOR: tuple[list[logging.Handler], int, bool] | None = None


class SummonLogBridge:
    """Scoped `taut_summon` logger capture with exact state restoration."""

    def __init__(
        self,
        callback: Callable[[str], None],
        *,
        limit: int = 200,
    ) -> None:
        self._callback = callback
        self._buffer: deque[str] = deque(maxlen=limit)
        self._logger = logging.getLogger("taut_summon")
        self._handler = _ForwardingHandler(self)
        self._installed = False
        self._leased = False
        self._lock = threading.Lock()

    def install(self) -> None:
        global _SUMMON_LOGGER_PRIOR

        with _SUMMON_LOGGER_OWNERSHIP_LOCK:
            if self._installed:
                return
            if not _SUMMON_LOGGER_OWNERS:
                _SUMMON_LOGGER_PRIOR = (
                    list(self._logger.handlers),
                    self._logger.level,
                    self._logger.propagate,
                )
            _SUMMON_LOGGER_OWNERS.append(self)
            self._installed = True
            self._logger.handlers = [owner._handler for owner in _SUMMON_LOGGER_OWNERS]
            self._logger.setLevel(logging.INFO)
            self._logger.propagate = False

    def restore(self) -> None:
        global _SUMMON_LOGGER_PRIOR

        with _SUMMON_LOGGER_OWNERSHIP_LOCK:
            if not self._installed:
                return
            _SUMMON_LOGGER_OWNERS.remove(self)
            self._installed = False
            if _SUMMON_LOGGER_OWNERS:
                self._logger.handlers = [
                    owner._handler for owner in _SUMMON_LOGGER_OWNERS
                ]
                self._logger.setLevel(logging.INFO)
                self._logger.propagate = False
                return
            if _SUMMON_LOGGER_PRIOR is None:
                raise RuntimeError("Summon logger ownership state was lost")
            handlers, level, propagate = _SUMMON_LOGGER_PRIOR
            self._logger.handlers = handlers
            self._logger.setLevel(level)
            self._logger.propagate = propagate
            _SUMMON_LOGGER_PRIOR = None

    def begin_lease(self) -> None:
        with self._lock:
            self._leased = True

    def end_lease(self) -> None:
        with self._lock:
            self._leased = False
            buffered = tuple(self._buffer)
            self._buffer.clear()
        for message in buffered:
            self._deliver(message)

    def accept(self, message: str) -> None:
        safe = escape_display_text(message)
        with self._lock:
            if self._leased:
                self._buffer.append(safe)
                return
        self._deliver(safe)

    def _deliver(self, message: str) -> None:
        try:
            self._callback(message)
        except Exception:  # noqa: BLE001 approved [DOM-10.2.1] [RUFF-SUP-086] exception
            return


__all__ = [
    "OwnedSummonFailure",
    "OwnedSummonRun",
    "OwnedSummonShutdown",
    "SummonLogBridge",
    "SummonUnavailable",
    "TerminalAttachConfirmationRequest",
    "TerminalLeaseRequest",
    "TuiSummonInteraction",
    "TuiSummonOperations",
    "load_summon_api",
]
