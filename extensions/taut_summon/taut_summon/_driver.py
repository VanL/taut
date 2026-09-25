"""The summon driver: bootstrap, ears, event pump, resume ([SUM-4]/[SUM-5]).

One foreground process per summoned member hosts one shared reactor after
bootstrap ([SUM-4]). The owner applies chat policy, delivery completions,
control commands, rate audits, readiness and provider lifecycle transitions.
``SummonReactor`` retains chat cursors until bounded native injection succeeds;
no separate chat watcher, control consumer or supervisor wait is needed.

The continuous native event pump publishes immutable generation-tagged results.
It owns no broker client. The foreground applies liveness and exit policy and
rejects stale generations. Blocking spawn, attach, settle, orientation and close
operations likewise publish results to this owner through the retained arbiter.

Shutdown ([SUM-9]) retires native work and the pump, closes the reactor source,
releases the driver slot, and then sends the correlated STOP outcome. Signals
publish only pending intent and a safe strategy hint; ordinary owner execution
performs cancellation. Provider recovery remains bounded under [SUM-11].

Test/ops knob: ``TAUT_SUMMON_RESUME_BACKOFF`` (comma-separated seconds,
e.g. ``"0.2,0.2"``) overrides the default resume backoff schedule; the
schedule length bounds the consecutive-crash retries.

Test/ops knob: ``TAUT_SUMMON_SETUP_RECOVERY`` set to ``"0"`` disables the
[SUM-7.4] setup-recovery escalation offer; suspected setup gates then fall
back to inject-after-settle plus the enriched [SUM-11] give-up diagnostics.

Spec references:
- docs/specs/04-summon.md [SUM-3], [SUM-4], [SUM-5], [SUM-6], [SUM-7.1],
  [SUM-8], [SUM-11]
"""

from __future__ import annotations

import getpass
import logging
import os
import queue
import signal
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from simplebroker import BrokerTarget, Queue
from simplebroker.ext import BrokerError

from taut import (
    IdentityError,
    NotFoundError,
    NotInitializedError,
    TautClient,
    TautError,
    WatcherRejected,
)
from taut._cleanup import capture_cleanup_failure
from taut.addressing import classify_registered_queue
from taut.client import Member, Message, Notification
from taut.identity import (
    IdentityCapture,
    capture_host_identity,
    capture_process,
    choose_name,
)
from taut_summon._adapter import (
    ActivityEvent,
    AdapterError,
    AdapterEvent,
    AdapterExitedError,
    AdapterHandle,
    AdapterWriteCancelled,
    ExitEvent,
    ProviderAdapter,
    UnknownAdapterError,
    get_adapter,
)
from taut_summon._control import (
    ControlPolicy,
    StopShutdownOutcome,
    control_in_queue_name,
)
from taut_summon._members import find_member
from taut_summon._persona import render_default_persona
from taut_summon._reactor import PreparedInjection, SummonReactor
from taut_summon._state import (
    LEDGER_QUEUE_NAME,
    ClaimConflictError,
    DriverConflictError,
    SummonSessionRow,
    SummonStateError,
    capture_driver_evidence,
    claim_driver,
    claim_name,
    driver_liveness,
    ensure_summon_schema,
    get_session,
    get_wired,
    record_session,
    release_claim,
    release_driver,
    replace_legacy_provider,
    set_wired,
)
from taut_summon.interaction import (
    SummonInteraction,
    TerminalAttachNotice,
    TerminalAvailability,
    TerminalIntent,
    TerminalLease,
)
from taut_summon.models import (
    SummonedMember,
    SummonOperationError,
    SummonRequest,
    SummonRunHandle,
)

logger = logging.getLogger("taut_summon.driver")

_LEDGER_QUEUE_NAME = LEDGER_QUEUE_NAME
_DEFAULT_RESUME_BACKOFF = (1.0, 2.0, 4.0)
_HEALTHY_RUN_SECONDS = 60.0
_ACTIVITY_WINDOW_SECONDS = 10.0
_PUMP_JOIN_TIMEOUT_SECONDS = 10.0
_FOREGROUND_READINESS_TIMEOUT_SECONDS = 30.0
_NAME_RETRY_ATTEMPTS = 5


class DriverError(Exception):
    """A fatal driver condition; its message is the exit-1 diagnostic."""


# --- [SUM-5.2] injection format (the one shared helper) -----------------------


def format_injection(item: Message | Notification) -> str:
    """Render one watch event in the [SUM-5.2] injection format."""

    if isinstance(item, Notification):
        location = _notify_location(item.thread)
        actor = item.actor_name or "someone"
        message_ts = "?" if item.message_ts is None else str(item.message_ts)
        return f"[notify] {item.type} by {actor} in {location} (message {message_ts})"
    prefix = (
        "[dm]"
        if classify_registered_queue(item.thread) == "dm"
        else (f"[#{item.thread}]")
    )
    text = _indent_continuation_lines(item.text)
    if item.kind == "notice":
        return f"{prefix} · {text}"
    return f"{prefix} {item.from_name}: {text}"


def _indent_continuation_lines(text: str) -> str:
    """Keep arbitrary text intact while making its frame boundary visible.

    This is attribution hygiene only ([SUM-5.2]). It does not sanitize chat
    content or turn a user-role event into a trusted instruction. Carriage
    returns are normalized to newlines first: the PTY paste path maps a lone
    ``\\r`` to ``\\n`` after formatting, so an unnormalized ``\\r`` here would
    reach the child as an unindented continuation line and escape the frame.
    """

    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    return normalized.replace("\n", "\n    ")


def _notify_location(thread: str | None) -> str:
    if not thread:
        return "?"
    if classify_registered_queue(thread) == "dm":
        return "dm"
    return f"#{thread}"


def _harness_target_projection(
    target: BrokerTarget | str,
) -> tuple[str, str | None]:
    """Return redacted display text and the optional path-only env selector.

    ``TAUT_DB`` is a filesystem-path selector. Config-backed targets must be
    rediscovered by the child; exposing a server DSN there is both invalid for
    core and a credential leak ([SUM-6]).
    """

    if isinstance(target, str):
        return target, target
    target_path = target.target_path
    return target.display_target, None if target_path is None else str(target_path)


def _harness_environment(
    boot: _BootstrapResult,
    *,
    db_path: str | None,
) -> dict[str, str]:
    env = {"TAUT_TOKEN": boot.token}
    if db_path is not None:
        env["TAUT_DB"] = db_path
    return env


@dataclass(frozen=True, slots=True)
class _BootstrapResult:
    member_id: str
    member_name: str
    token: str
    provider: str
    resummon: bool = False


@dataclass(frozen=True, slots=True)
class _PhaseResult:
    name: str
    value: Any
    error: BaseException | None


@dataclass(frozen=True, slots=True)
class _PumpResult:
    generation: int
    event: AdapterEvent | None
    error: BaseException | None
    retired: bool


@dataclass(slots=True)
class _GenerationExit:
    """Generation-local exit state; never reused by a later spawn."""

    returncode: int | None = None


@dataclass(frozen=True, slots=True)
class _GenerationContext:
    """All pump-written state for one immutable [SUM-11] spawn identity."""

    token: int
    exit: _GenerationExit


@dataclass(frozen=True, slots=True)
class _RunningGeneration:
    """Foreground-owned resources for one fully bootstrapped generation."""

    started_at: float
    handle: AdapterHandle
    generation: _GenerationContext
    pump: threading.Thread | None


@dataclass(frozen=True, slots=True)
class _GenerationAttachDecision:
    """One immutable attach-policy result shared across ack, spawn, and lease."""

    wired: bool
    should_attach: bool


def _resume_backoff_from_env() -> tuple[float, ...]:
    raw = os.environ.get("TAUT_SUMMON_RESUME_BACKOFF")
    if not raw:
        return _DEFAULT_RESUME_BACKOFF
    try:
        parsed = tuple(float(part) for part in raw.split(",") if part.strip())
    except ValueError:
        logger.warning("ignoring invalid TAUT_SUMMON_RESUME_BACKOFF: %r", raw)
        return _DEFAULT_RESUME_BACKOFF
    return parsed or _DEFAULT_RESUME_BACKOFF


def _agent_capture(pid: int, rule: str) -> IdentityCapture:
    """Build an agent capture anchored at a real process ([SUM-4] seam)."""

    proc = capture_process(pid)
    if proc is None or proc.start_time is None:
        raise DriverError(f"cannot capture identity evidence for pid {pid}")
    try:
        login = getpass.getuser()
    except Exception:  # pragma: no cover  # noqa: BLE001 approved [DOM-10.2.1] [RUFF-SUP-067] exception
        login = "summon"
    return IdentityCapture(
        chain=(proc,),
        host=capture_host_identity(),
        uid=os.getuid() if hasattr(os, "getuid") else 0,
        login=login,
        anchor=proc,
        kind="agent",
        rule=rule,
    )


class SummonDriver:
    """Foreground driver for one summoned member."""

    def __init__(
        self,
        request: SummonRequest,
        *,
        interaction: SummonInteraction,
        db_path: str | None = None,
        install_signal_handlers: bool = False,
        on_ready: Callable[[SummonRunHandle], None] | None = None,
    ) -> None:
        if request.attach and request.detach:
            raise SummonOperationError("--attach and --detach cannot be used together")
        self._request = request
        self._interaction = interaction
        self._db_path = db_path
        self._install_signal_handlers = install_signal_handlers
        self._on_ready = on_ready
        self._ready_callback_invoked = False
        self._run_completion = threading.Event() if on_ready is not None else None
        self._backoff = _resume_backoff_from_env()
        # [SUM-7.4] setup-recovery escalation: at most one offer per
        # foreground run, consumed whether the human proceeds or declines.
        self._setup_recovery_consumed = False
        self._pending_setup_recovery_attach = False
        self._setup_recovery_excerpt: str | None = None
        self._signal_pending = False
        self._shutdown = threading.Event()
        self._harness_dead = threading.Event()
        # The final correlated STOP result is frozen only after retirement and
        # ownership-checked ledger release.
        self._release_confirmed = False
        self._release_error: BaseException | None = None
        self._stop_shutdown_outcome: StopShutdownOutcome | None = None
        self._handle: AdapterHandle | None = None
        # One foreground reactor owns broker policy and delivery continuations.
        self._watcher: Any | None = None
        self._member_id: str | None = None
        self._generation_counter = 0
        self._active_generation: _GenerationContext | None = None
        self._interrupt_worker: threading.Thread | None = None
        self._phase_cancel_requested = False
        self._shutdown_error: BaseException | None = None
        self._queue: Queue | None = None
        self._evidence: tuple[int, str] | None = None
        self._audit_start_ts: int | None = None
        self._owned_clients: list[TautClient] = []

    # --- public entry ----------------------------------------------------

    def run(self) -> None:
        previous_signals = (
            self._install_signals() if self._install_signal_handlers else {}
        )
        primary_failure: BaseException | None = None
        try:
            try:
                result = self._run()
            except NotInitializedError:
                # The controller owns this diagnostic: with no database there can be
                # no session row, so [SUM-3] resolution may still surface the
                # unknown-adapter error instead ([SUM-3] step 3).
                raise
            except DriverError as exc:
                raise SummonOperationError(str(exc)) from exc
            except (BrokerError, SummonStateError, AdapterError, TautError) as exc:
                raise SummonOperationError(str(exc)) from exc
            if result != 0:
                raise SummonOperationError(f"summon driver exited with status {result}")
        except BaseException as exc:
            primary_failure = exc
            raise
        finally:
            try:
                if previous_signals:
                    try:
                        self._restore_signals(previous_signals)
                    except SummonOperationError:
                        if primary_failure is None:
                            raise
                        logger.exception(
                            "could not restore summon signal handlers after primary failure"
                        )
            finally:
                if self._run_completion is not None:
                    self._run_completion.set()

    def request_stop(self) -> None:
        self._shutdown.set()
        handle = self._handle
        if handle is not None:
            try:
                handle.request_close()
            except AdapterError:
                logger.debug("adapter close request during stop failed", exc_info=True)
        self._publish_owner_activity()

    def _persistent_client(self, **kwargs: Any) -> TautClient:
        client = TautClient(
            **kwargs,
            persistent=True,
            inherit_environment_identity=False,
        )
        self._owned_clients.append(client)
        return client

    def _close_owned_clients(self) -> None:
        while self._owned_clients:
            client = self._owned_clients.pop()
            try:
                client.close()
            except Exception:  # pragma: no cover - defensive cleanup
                logger.debug("taut client close failed", exc_info=True)

    # --- bootstrap ([SUM-4]) ----------------------------------------------

    def _run(self) -> int:
        client = self._persistent_client(db_path=self._db_path)
        db_display, db_env_path = _harness_target_projection(client.target)
        self._queue = client.queue(_LEDGER_QUEUE_NAME)
        try:
            ensure_summon_schema(self._queue)
            self._evidence = capture_driver_evidence()
            try:
                boot = self._bootstrap(client)
                self._member_id = boot.member_id
                self._update_resummon_persona(boot)
                # Bootstrap membership notices are setup, not harness posting.
                # Fix the lower bound only after every bootstrap join and
                # immediately before the first spawn; the same bound survives
                # every later harness generation ([SUM-10]).
                self._audit_start_ts = self._queue.generate_timestamp()
                return self._supervise(boot, db_display, db_path=db_env_path)
            finally:
                # Ownership-checked release covering EVERY post-claim fatal
                # path, including a bootstrap failure after member_id becomes
                # known. Release BEFORE the owner sends a STOP acknowledgement,
                # so the stop client sees the reply only after the ledger is
                # clear ([SUM-9]). Idempotent — a second release is a no-op.
                self._release()
                self._finalize_stop_shutdown_outcome()
                control = getattr(self, "_owner_control", None)
                if control is not None and control._pending_stop_seen:
                    # The source has retired; recreate only the transient reply
                    # route after release, without retaining its old client.
                    control._client = client
                    control.finish_stop(self._control_shutdown_outcome())
        finally:
            self._close_owned_clients()

    def _bootstrap(self, client: TautClient) -> _BootstrapResult:
        request = self._request
        requested = request.name
        implied = request.provider_flag is None
        member = find_member(client, requested)
        row = (
            get_session(self._ledger(), member.member_id)
            if member is not None
            else None
        )

        if row is not None:
            assert member is not None
            if row["provider"] == "claude-stream":
                row = self._recover_legacy_provider(requested, member, row)
            # Re-summon: resolve provider from the session row; an
            # explicit --provider that disagrees is a loud error
            # ([SUM-3] — members do not switch harnesses implicitly).
            if (
                request.provider_flag is not None
                and request.provider_flag != row["provider"]
            ):
                raise DriverError(
                    f"member '{requested}' was summoned with provider "
                    f"'{row['provider']}'; refusing to switch to "
                    f"'{request.provider_flag}' (drop --provider to resume)"
                )
            self._require_adapter(row["provider"])
            pid, start = self._require_evidence()
            try:
                claim_driver(
                    self._ledger(),
                    member_id=member.member_id,
                    driver_pid=pid,
                    driver_start_time=start,
                    updated_ts=self._ledger().generate_timestamp(),
                    takeover=request.takeover,
                )
            except DriverConflictError as exc:
                raise DriverError(str(exc)) from exc
            self._member_id = member.member_id
            return _BootstrapResult(
                member_id=member.member_id,
                member_name=member.name,
                token=row["token"],
                provider=row["provider"],
                resummon=True,
            )

        # First summon (or a foreign, never-summoned member holds the
        # name). Resolve the provider first: --provider, else the name
        # itself as an adapter ([SUM-3] steps 1 and 3).
        provider = request.provider_flag or requested
        self._require_adapter(provider)

        target = (
            self._automatic_name(client, requested, set()) if implied else requested
        )
        if member is not None:
            # A member exists but was never summoned: never adopt.
            if not implied:
                raise DriverError(
                    f"member '{requested}' already exists and was not "
                    "summoned; pick another name"
                )
            logger.warning("summoned as '%s' — '%s' is taken", target, requested)
        return self._first_summon(client, requested, target, provider, implied)

    def _recover_legacy_provider(
        self,
        requested: str,
        member: Member,
        row: SummonSessionRow,
    ) -> SummonSessionRow:
        if self._request.provider_flag != "claude":
            raise DriverError(
                f"member '{requested}' has legacy provider 'claude-stream'; "
                "stop its old driver if it is live, then rerun with --provider claude"
            )
        liveness = driver_liveness(row)
        if liveness == "live":
            raise DriverError(
                f"member '{requested}' still has a live claude-stream driver; "
                "stop it before rerunning with --provider claude"
            )
        if liveness == "indeterminate":
            raise DriverError(
                f"member '{requested}' has indeterminate claude-stream driver "
                "evidence; refusing recovery"
            )
        try:
            return replace_legacy_provider(
                self._ledger(),
                member_id=member.member_id,
                expected_driver_pid=row["driver_pid"],
                expected_driver_start_time=row["driver_start_time"],
                updated_ts=self._ledger().generate_timestamp(),
            )
        except SummonStateError as exc:
            raise DriverError(str(exc)) from exc

    def _first_summon(  # noqa: C901 approved [DOM-10.2.1] [RUFF-SUP-024] exception
        self,
        client: TautClient,
        requested: str,
        target: str,
        provider: str,
        implied: bool,
    ) -> _BootstrapResult:
        queue = self._ledger()
        pid, start = self._require_evidence()
        attempted = {target}
        created: Member | None = None
        retrying_after_occupied_claim = False

        # Each candidate attempt owns one claim and one creator. A core
        # fail-not-adopt collision leaves no member to clean up: release that
        # claim, choose another candidate, and retry ([SUM-4]).
        for _ in range(_NAME_RETRY_ATTEMPTS):
            try:
                claim_name(
                    queue,
                    name=target,
                    provider=provider,
                    driver_pid=pid,
                    driver_start_time=start,
                    claimed_ts=queue.generate_timestamp(),
                    takeover=self._request.takeover,
                )
            except ClaimConflictError as exc:
                if not implied and not retrying_after_occupied_claim:
                    raise DriverError(str(exc)) from exc
                if len(attempted) >= _NAME_RETRY_ATTEMPTS:
                    raise DriverError(
                        f"could not settle a name for '{requested}' after "
                        f"{_NAME_RETRY_ATTEMPTS} attempts"
                    ) from exc
                target = self._automatic_name(client, requested, attempted)
                attempted.add(target)
                logger.warning(
                    "summon of '%s' is already in flight; trying '%s'",
                    requested,
                    target,
                )
                continue

            creator: TautClient | None = None
            try:
                creator = TautClient(
                    db_path=self._db_path,
                    as_name=target,
                    identity_capture=_agent_capture(
                        os.getpid(), rule="summon driver bootstrap anchor"
                    ),
                    persistent=True,
                    inherit_environment_identity=False,
                )
                creator.join(
                    self._request.threads[0],
                    persona=self._request.persona,
                    new=True,
                )
                created = creator.last_created_member
                if created is None or created.token is None:
                    raise DriverError(
                        "bootstrap failed: fresh final-named member was not created"
                    )
                # Join all requested threads before the session row becomes the
                # readiness signal. This preserves the no-gap rule from the old
                # bootstrap without a visible temporary identity.
                self._ensure_threads(creator, created.member_id)
            except IdentityError:
                if created is None and creator is not None:
                    created = creator.last_created_member
                self._release_name_claim_after_failure(
                    queue, target=target, provider=provider, pid=pid, start=start
                )
                if created is not None and created.token is not None:
                    raise self._residual_member_error(created) from None
                collided_target = target
                retrying_after_occupied_claim = True
                if len(attempted) >= _NAME_RETRY_ATTEMPTS:
                    raise DriverError(
                        f"could not settle a name for '{requested}' after "
                        f"{_NAME_RETRY_ATTEMPTS} attempts"
                    ) from None
                target = self._automatic_name(client, requested, attempted)
                attempted.add(target)
                logger.warning(
                    "requested name '%s' was taken mid-summon; trying '%s'",
                    collided_target,
                    target,
                )
                continue
            except BaseException as exc:
                if created is None and creator is not None:
                    created = creator.last_created_member
                self._release_name_claim_after_failure(
                    queue, target=target, provider=provider, pid=pid, start=start
                )
                if created is not None and created.token is not None:
                    raise self._residual_member_error(created) from exc
                raise
            finally:
                if creator is not None:
                    primary_error = sys.exception()
                    try:
                        creator.close()
                    except Exception as exc:
                        if primary_error is not None:
                            logger.debug(
                                "creator close after bootstrap failure also failed",
                                exc_info=True,
                            )
                        else:
                            self._release_name_claim_after_failure(
                                queue,
                                target=target,
                                provider=provider,
                                pid=pid,
                                start=start,
                            )
                            if created is not None and created.token is not None:
                                raise self._residual_member_error(created) from exc
                            raise
            break
        assert created is not None and created.token is not None

        # Publish the durable session row, then release the claim —
        # old names free up the moment they stop being load-bearing.
        self._member_id = created.member_id
        try:
            record_session(
                queue,
                member_id=created.member_id,
                token=created.token,
                provider=provider,
                driver_pid=pid,
                driver_start_time=start,
                updated_ts=queue.generate_timestamp(),
            )
        except BaseException as exc:
            self._release_name_claim_after_failure(
                queue, target=target, provider=provider, pid=pid, start=start
            )
            raise self._residual_member_error(created) from exc
        if not release_claim(
            queue,
            name=target,
            provider=provider,
            driver_pid=pid,
            driver_start_time=start,
        ):
            raise DriverError(
                f"recorded session for '{target}' but could not release its name claim"
            )
        return _BootstrapResult(
            member_id=created.member_id,
            member_name=target,
            token=created.token,
            provider=provider,
        )

    def _update_resummon_persona(self, boot: _BootstrapResult) -> None:
        persona = self._request.persona
        if not boot.resummon or persona is None:
            return
        client = TautClient(
            db_path=self._db_path,
            token=boot.token,
            inherit_environment_identity=False,
        )
        try:
            updated = client.set_persona(persona)
        finally:
            client.close()
        if updated.member_id != boot.member_id:
            raise DriverError(
                "persona update resolved a different member than the driver claim"
            )

    # --- foreground reactor (steps 4-5, ears, pump, resume) ----------------

    def _supervise(
        self,
        boot: _BootstrapResult,
        db_display: str,
        *,
        db_path: str | None = None,
    ) -> int:
        """Drive the run's single reactor; escaping failures end the run."""
        self._owner_boot = boot
        self._owner_adapter = self._require_adapter(boot.provider)
        if self._request.attach and not self._owner_adapter.supports_attach:
            raise DriverError(f"provider '{boot.provider}' does not support attach")
        self._owner_availability = self._terminal_availability(
            self._request, self._owner_adapter
        )
        self._owner_env = _harness_environment(boot, db_path=db_path)
        self._owner_prompt = self._system_prompt(boot, db_display)
        self._owner_phase = "prepare"
        self._phase_worker: threading.Thread | None = None
        self._phase_results: queue.SimpleQueue[_PhaseResult] = queue.SimpleQueue()
        self._phase_result: _PhaseResult | None = None
        self._pump_results: queue.SimpleQueue[_PumpResult] = queue.SimpleQueue()
        self._owner_running: _RunningGeneration | None = None
        self._owner_first = True
        self._owner_generation_ready = False
        self._owner_crashes = 0
        self._harness_restart_at = 0.0
        self._owner_readiness_at: float | None = None
        self._owner_last_activity = 0.0
        self._pending_nudge: str | None = None
        self._owner_control: ControlPolicy | None = None
        self._owner_client: TautClient | None = None
        try:
            client, reactor = self._open_owner_source()
            try:
                reactor.run_until_stopped()
                if self._owner_phase == "done":
                    return 0
                raise DriverError("Summon reactor exited before lifecycle retirement")
            finally:
                primary = sys.exception()
                cleanup = capture_cleanup_failure(
                    None, lambda: reactor.stop(join=False)
                )
                cleanup = capture_cleanup_failure(cleanup, client.close)
                self._watcher = None
                if cleanup is not None:
                    if primary is None:
                        raise cleanup
                    self._add_cleanup_note(primary, cleanup)
        finally:
            self._close_owner_generation()

    def _open_owner_source(self) -> tuple[TautClient, SummonReactor]:
        boot = self._owner_boot
        client = TautClient(
            db_path=self._db_path,
            token=boot.token,
            persistent=True,
            inherit_environment_identity=False,
        )
        reactor: SummonReactor | None = None
        try:
            candidate = client.watch(lambda _item: None, watcher_type=SummonReactor)
            assert isinstance(candidate, SummonReactor)
            reactor = candidate
            self._owner_client = client
            self._watcher = reactor
            reactor.prepare_delivery = self._prepare_injection
            reactor.current_generation = lambda: (
                self._active_generation.token if self._active_generation else 0
            )
            reactor.delivery_error = self._owner_delivery_error
            reactor.delivery_enabled = (
                self._owner_phase == "listen"
                and self._harness_restart_at <= time.monotonic()
            )
            reactor.control_queue_name = control_in_queue_name(boot.member_id)
            reactor.owner_turn = self._owner_turn
            reactor.owner_wait_timeout = self._owner_wait_timeout
            pid, started = self._require_evidence()
            control = ControlPolicy(
                client=client,
                reactor=reactor,
                member_id=boot.member_id,
                provider=boot.provider,
                threads=self._request.threads,
                handle_provider=lambda: self._handle,
                request_stop=self.request_stop,
                send_nudge=self._queue_rate_nudge,
                interrupt=self._owner_interrupt,
                rate_limit=self._request.rate_limit,
                ledger_queue_name=_LEDGER_QUEUE_NAME,
                driver_pid=pid,
                driver_start_time=started,
                audit_start_ts=self._audit_start_ts or 0,
            )
            self._owner_control = control
            control.install()
            return client, reactor
        except BaseException as primary:
            if reactor is not None:
                cleanup = capture_cleanup_failure(
                    None, lambda: reactor.stop(join=False)
                )
                if cleanup is not None:
                    self._add_cleanup_note(primary, cleanup)
            cleanup = capture_cleanup_failure(None, client.close)
            if cleanup is not None:
                self._add_cleanup_note(primary, cleanup)
            self._watcher = None
            raise

    def _close_owner_generation(self) -> None:
        """Cancel native work before closing its generation on terminal unwind."""
        primary = sys.exception()
        try:
            self._retire_owner_generation()
        except BaseException as error:
            self._shutdown_error = error
            if primary is None:
                raise
            self._add_cleanup_note(primary, error)

    def _retire_owner_generation(self) -> None:
        self._shutdown.set()
        handle = self._handle
        cleanup = (
            capture_cleanup_failure(None, handle.request_close) if handle else None
        )
        worker = self._phase_worker
        if worker is not None:
            cleanup = capture_cleanup_failure(
                cleanup, lambda: self._join_native_operation(worker, "native operation")
            )
            if handle is None and not worker.is_alive():
                try:
                    result = self._phase_result or self._phase_results.get_nowait()
                except queue.Empty:
                    result = None
                if (
                    result is not None
                    and result.name == "spawn"
                    and result.error is None
                ):
                    cleanup = capture_cleanup_failure(cleanup, result.value.close)
        interrupt = self._interrupt_worker
        if interrupt is not None:
            cleanup = capture_cleanup_failure(
                cleanup,
                lambda: self._join_native_operation(interrupt, "native interrupt"),
            )
            if not interrupt.is_alive():
                self._interrupt_worker = None
        running = self._owner_running
        if running is not None:
            cleanup = capture_cleanup_failure(
                cleanup,
                lambda: self._teardown_generation(
                    running.generation, running.handle, running.pump
                ),
            )
            self._owner_running = None
        if cleanup is not None:
            raise cleanup

    @staticmethod
    def _join_native_operation(worker: threading.Thread, name: str) -> None:
        worker.join(timeout=_PUMP_JOIN_TIMEOUT_SECONDS)
        if worker.is_alive():
            raise DriverError(f"{name} did not retire during shutdown")

    def _publish_owner_activity(self) -> None:
        reactor = self._watcher
        if reactor is not None:
            reactor.notify_activity()

    def _start_phase_operation(self, name: str, operation: Callable[[], Any]) -> None:
        interrupt = name == "interrupt"
        if (
            self._interrupt_worker is not None
            if interrupt
            else self._phase_worker is not None
        ):
            raise DriverError("overlapping native phase operations")
        if not interrupt:
            self._owner_phase = name
            self._phase_cancel_requested = False

        def execute() -> None:
            value: Any = None
            error: BaseException | None = None
            try:
                value = operation()
            except BaseException as exc:  # noqa: BLE001 - transfer worker failure to owner
                error = exc
            finally:
                self._phase_results.put(_PhaseResult(name, value, error))
                self._publish_owner_activity()

        worker = threading.Thread(
            target=execute, name=f"taut-summon-{name}", daemon=True
        )
        if interrupt:
            self._interrupt_worker = worker
        else:
            self._phase_worker = worker
        try:
            worker.start()
        except BaseException:
            if interrupt:
                self._interrupt_worker = None
            else:
                self._phase_worker = None
            raise

    def _owner_wait_timeout(self) -> float | None:
        now = time.monotonic()
        if self._harness_restart_at > now and not self._shutdown.is_set():
            return self._harness_restart_at - now
        deadlines = []
        if self._owner_control is not None and not self._shutdown.is_set():
            deadlines.append(self._owner_control._next_rate_audit_at)
        if self._harness_restart_at > now:
            deadlines.append(self._harness_restart_at)
        if (
            not self._ready_callback_invoked
            and self._on_ready is not None
            and not self._shutdown.is_set()
            and self._owner_readiness_at is not None
        ):
            deadlines.append(self._owner_readiness_at)
        return max(0.0, min(deadlines) - now) if deadlines else None

    def _harness_restart_pending(self) -> bool:
        return (
            self._harness_restart_at > time.monotonic()
            and not self._shutdown.is_set()
            and not self._harness_dead.is_set()
        )

    def _owner_turn(self) -> None:
        if self._signal_pending:
            self._signal_pending = False
            self.request_stop()
        self._apply_pump_results()
        if self._harness_restart_pending():
            return
        self._apply_phase_result()
        reactor = self._watcher
        assert isinstance(reactor, SummonReactor)
        if self._shutdown.is_set() and self._handle is not None:
            self._handle.request_close()
        if self._owner_control is not None and not self._shutdown.is_set():
            self._owner_control.turn()
        self._check_owner_readiness_deadline()
        if self._phase_worker is not None or self._interrupt_worker is not None:
            return
        if self._shutdown.is_set() or self._harness_dead.is_set():
            self._begin_owner_teardown()
            return
        if self._owner_phase == "prepare":
            self._prepare_owner_generation()
        elif self._owner_phase == "spawn-ready":
            adapter, prompt, env = (
                self._owner_adapter,
                self._owner_prompt,
                self._owner_env,
            )
            self._start_phase_operation(
                "spawn", lambda: adapter.spawn(system_prompt=prompt, env=env)
            )
        elif self._owner_phase == "listen":
            self._listen_owner_turn(reactor)

    def _check_owner_readiness_deadline(self) -> None:
        if (
            self._on_ready is not None
            and not self._ready_callback_invoked
            and not self._shutdown.is_set()
            and self._owner_readiness_at is not None
            and time.monotonic() >= self._owner_readiness_at
        ):
            self.request_stop()
            raise DriverError(
                "Summon reactor did not become ready within startup deadline"
            )

    def _listen_owner_turn(self, reactor: SummonReactor) -> None:
        if self._owner_readiness_at is None:
            self._owner_readiness_at = (
                time.monotonic() + _FOREGROUND_READINESS_TIMEOUT_SECONDS
            )
        reactor.delivery_enabled = True
        if self._pending_nudge is not None and reactor._delivery_pending is None:
            text = self._pending_nudge
            self._pending_nudge = None
            handle = self._handle
            assert handle is not None
            self._start_phase_operation("nudge", lambda: handle.inject(text))
            reactor.delivery_enabled = False
        if reactor._ready_after_initial_drain and reactor._delivery_pending is None:
            self._publish_owner_ready()

    def _prepare_owner_generation(self) -> None:
        decision = self._resolve_generation_attach(
            boot=self._owner_boot,
            adapter=self._owner_adapter,
            availability=self._owner_availability,
            first_generation=self._owner_first,
        )
        self._owner_attach = decision
        if decision.should_attach:
            notice = TerminalAttachNotice(
                member=self._owner_boot.member_name,
                provider=self._owner_boot.provider,
                detach_hint="Ctrl-\\ Ctrl-\\",
                screen_excerpt=self._setup_recovery_excerpt,
            )
            self._setup_recovery_excerpt = None
            interaction, cancel = self._interaction, self._shutdown
            self._start_phase_operation(
                "confirm",
                lambda: interaction.confirm_terminal_attach(notice, cancel=cancel),
            )
        else:
            self._owner_phase = "spawn-ready"
            self._publish_owner_activity()

    def _apply_phase_result(self) -> None:
        result = self._phase_result
        if result is None:
            try:
                result = self._phase_results.get_nowait()
            except queue.Empty:
                return
            self._phase_result = result
        interrupt = result.name == "interrupt"
        worker = self._interrupt_worker if interrupt else self._phase_worker
        if worker is not None:
            worker.join(timeout=_PUMP_JOIN_TIMEOUT_SECONDS)
            if worker.is_alive():
                raise DriverError("native worker published but did not retire")
        if interrupt:
            self._interrupt_worker = None
        else:
            self._phase_worker = None
        if result.error is not None:
            self._phase_result = None
            self._handle_phase_failure(result)
            return
        self._accept_phase_result(result)
        self._phase_result = None

    def _handle_phase_failure(self, result: _PhaseResult) -> None:
        assert result.error is not None
        if self._shutdown.is_set() and result.name != "close":
            return
        if (
            result.name in {"orientation", "nudge"}
            and self._phase_cancel_requested
            and isinstance(result.error, AdapterWriteCancelled)
        ):
            self._phase_cancel_requested = False
            self._owner_phase = "listen"
            return
        if result.name in {"settle", "orientation", "nudge"} and isinstance(
            result.error, AdapterExitedError
        ):
            self._harness_dead.set()
            return
        if result.name == "close":
            self._shutdown_error = result.error
        if result.name == "confirm":
            raise SummonOperationError(
                f"terminal acknowledgement failed: {result.error}"
            ) from result.error
        if result.name == "spawn":
            raise DriverError(
                f"cannot spawn the harness: {result.error}"
            ) from result.error
        raise result.error

    def _accept_phase_result(self, result: _PhaseResult) -> None:
        if result.name == "confirm":
            if type(result.value) is not bool:
                raise DriverError(
                    "terminal interaction returned non-boolean confirmation"
                )
            if not result.value:
                if self._pending_setup_recovery_attach and not self._shutdown.is_set():
                    self._owner_attach = _GenerationAttachDecision(
                        self._owner_attach.wired, False
                    )
                else:
                    self.request_stop()
            self._pending_setup_recovery_attach = False
            self._owner_phase = "spawn-ready"
        elif result.name == "spawn":
            self._accept_spawn(result.value)
        elif result.name == "attach":
            self._accept_attach(result.value)
        elif result.name == "settle":
            self._after_owner_settle()
        elif result.name in {"orientation", "nudge"}:
            self._owner_phase = "listen"

        elif result.name == "close":
            self._finish_owner_teardown()
        self._publish_owner_activity()

    def _accept_spawn(self, handle: AdapterHandle) -> None:
        running = self._owner_running
        if running is None:
            self._handle = handle
            self._owner_generation_ready = False
            generation = self._activate_generation()
            self._owner_first = False
            running = _RunningGeneration(time.monotonic(), handle, generation, None)
            self._owner_running = running
        elif running.handle is not handle:
            raise DriverError("spawn acceptance conflicts with retained generation")
        if self._shutdown.is_set():
            handle.request_close()
        if running.pump is None and self._should_start_pump_before_bootstrap(
            self._request, self._owner_adapter, availability=self._owner_availability
        ):
            pump = self._start_generation_pump(
                running.generation, handle, self._owner_boot
            )
            self._owner_running = _RunningGeneration(
                running.started_at, handle, running.generation, pump
            )
        self._rejoin(handle, self._owner_boot)
        self._ensure_generation_threads(self._owner_boot)
        if self._owner_attach.should_attach:
            self._start_phase_operation(
                "attach", lambda: self._run_terminal_attach(handle)
            )
        else:
            self._start_owner_settle()

    def _accept_attach(self, result: str) -> None:
        if result == "shutdown":
            self.request_stop()
        if result == "detached":
            set_wired(
                self._ledger(),
                member_id=self._owner_boot.member_id,
                value=True,
                updated_ts=self._ledger().generate_timestamp(),
            )
        running = self._owner_running
        assert running is not None
        pump = self._start_generation_pump(
            running.generation, running.handle, self._owner_boot
        )
        self._owner_running = _RunningGeneration(
            running.started_at, running.handle, running.generation, pump
        )
        self._start_owner_settle()

    def _start_owner_settle(self) -> None:
        running = self._owner_running
        assert running is not None
        if running.pump is None:
            pump = self._start_generation_pump(
                running.generation, running.handle, self._owner_boot
            )
            self._owner_running = _RunningGeneration(
                running.started_at, running.handle, running.generation, pump
            )
        handle = self._handle
        assert handle is not None
        if not self._owner_adapter.orientation_via_inject:
            self._owner_phase = "listen"
            return
        self._start_phase_operation("settle", handle.wait_until_quiet)

    def _after_owner_settle(self) -> None:
        running = self._owner_running
        assert running is not None
        handle = running.handle
        if self._should_offer_setup_recovery(
            handle,
            self._owner_adapter,
            self._owner_availability,
            attached_this_generation=self._owner_attach.should_attach,
        ):
            self._setup_recovery_consumed = True
            self._pending_setup_recovery_attach = True
            self._setup_recovery_excerpt = handle.output_tail() or None
            self._harness_dead.set()
            return
        if not handle.input_prompt_observed or not self._owner_attach.wired:
            handle.mark_awaiting_onboarding()
        prompt = self._owner_prompt
        self._start_phase_operation("orientation", lambda: handle.inject(prompt))

    def _begin_owner_teardown(self) -> None:
        reactor = self._watcher
        assert isinstance(reactor, SummonReactor)
        reactor.delivery_enabled = False
        running = self._owner_running
        if running is None:
            self._owner_phase = "done"
            reactor.request_stop()
            return
        running.handle.request_close()
        if reactor._delivery_pending is not None:
            return
        if self._owner_phase != "close":
            self._start_phase_operation("close", running.handle.close)

    def _finish_owner_teardown(self) -> None:
        running = self._owner_running
        assert running is not None
        if running.pump is not None:
            self._join_pump(
                running.generation, running.pump, timeout=_PUMP_JOIN_TIMEOUT_SECONDS
            )
        else:
            self._retire_generation(running.generation)
        self._owner_running = None
        self._handle = None
        self._harness_dead.clear()
        if self._shutdown.is_set():
            self._owner_phase = "done"
            assert self._watcher is not None
            self._watcher.request_stop()
            return
        if self._pending_setup_recovery_attach:
            self._owner_phase = "prepare"
            return
        if self._on_ready is not None and not self._ready_callback_invoked:
            raise DriverError("provider generation exited before foreground readiness")
        lived = time.monotonic() - running.started_at
        self._owner_crashes = (
            1 if lived >= _HEALTHY_RUN_SECONDS else self._owner_crashes + 1
        )
        if self._owner_crashes > len(self._backoff):
            raise DriverError(self._give_up_message(running))
        self._harness_restart_at = (
            time.monotonic() + self._backoff[self._owner_crashes - 1]
        )
        self._owner_phase = "prepare"

    def _give_up_message(self, running: _RunningGeneration) -> str:
        message = (
            f"harness for '{self._owner_boot.member_name}' exited "
            f"{self._owner_crashes} times in a row "
            f"(last exit code {running.generation.exit.returncode}); giving up"
        )
        try:
            tail = running.handle.output_tail()
        except Exception:  # noqa: BLE001 - diagnostics cannot replace provider failure
            tail = ""
        if tail:
            message += f"\nlast screen output:\n{tail}"
        if self._owner_adapter.supports_attach:
            message += f"\nrun: taut summon --attach {self._owner_boot.member_name}"
        return message

    def _owner_delivery_error(self, error: BaseException) -> None:
        if isinstance(error, AdapterWriteCancelled):
            return
        if isinstance(error, AdapterError):
            self._harness_dead.set()
            return
        raise error

    def _queue_rate_nudge(self, text: str) -> None:
        self._pending_nudge = text

    def _owner_interrupt(self) -> None:
        handle = self._handle
        if handle is not None and self._interrupt_worker is None:
            if self._watcher is not None:
                self._watcher.delivery_enabled = False
            if self._phase_worker is not None and self._owner_phase in {
                "orientation",
                "nudge",
            }:
                self._phase_cancel_requested = True
            self._start_phase_operation("interrupt", handle.interrupt)

    def _publish_owner_ready(self) -> None:
        if not self._owner_generation_ready:
            self._owner_generation_ready = True
            boot = self._owner_boot
            logger.info(
                "summoned '%s' (member %s, provider %s, threads %s)",
                boot.member_name,
                boot.member_id,
                boot.provider,
                ", ".join(self._request.threads),
            )
        if self._on_ready is None or self._ready_callback_invoked:
            return
        completion = self._run_completion
        assert completion is not None
        boot = self._owner_boot
        self._ready_callback_invoked = True
        handle = SummonRunHandle(
            SummonedMember(
                member_id=boot.member_id,
                name=boot.member_name,
                provider=boot.provider,
            ),
            _request_stop=self.request_stop,
            _completion=completion,
        )
        try:
            self._on_ready(handle)
        except Exception as error:
            raise SummonOperationError("summon readiness callback failed") from error

    def _apply_pump_results(self) -> None:
        while True:
            try:
                result = self._pump_results.get_nowait()
            except queue.Empty:
                return
            generation = self._active_generation
            if generation is None or result.generation != generation.token:
                continue
            if result.error is not None:
                raise DriverError(
                    f"adapter event stream failed: {result.error}"
                ) from result.error
            if isinstance(result.event, ActivityEvent):
                client = self._owner_client
                assert client is not None
                self._owner_last_activity = self._record_activity_event(
                    result.event, client, self._owner_last_activity
                )
            elif isinstance(result.event, ExitEvent):
                generation.exit.returncode = result.event.returncode
            if result.retired:
                self._harness_dead.set()

    def _start_generation_pump(
        self,
        generation: _GenerationContext,
        handle: AdapterHandle,
        boot: _BootstrapResult,
    ) -> threading.Thread:
        return self._start_pump(
            generation,
            handle,
            db_path=self._db_path,
            token=boot.token,
        )

    def _ensure_generation_threads(self, boot: _BootstrapResult) -> None:
        setup_client = TautClient(
            db_path=self._db_path,
            token=boot.token,
            inherit_environment_identity=False,
        )
        try:
            self._ensure_threads(setup_client, boot.member_id)
        finally:
            setup_client.close()

    def _should_offer_setup_recovery(
        self,
        handle: AdapterHandle,
        adapter: ProviderAdapter,
        availability: TerminalAvailability | None,
        *,
        attached_this_generation: bool,
    ) -> bool:
        """[SUM-7.4] setup-recovery escalation conditions, evaluated at settle."""

        if attached_this_generation or self._setup_recovery_consumed:
            return False
        if handle.input_prompt_observed:
            return False
        if not adapter.supports_attach or not adapter.orientation_via_inject:
            return False
        if self._request.detach:
            return False
        if availability is not TerminalAvailability.AVAILABLE:
            return False
        if os.environ.get("TAUT_SUMMON_SETUP_RECOVERY") == "0":
            return False
        try:
            supported = self._interaction.supports_setup_recovery()
        except Exception as exc:
            raise DriverError(f"terminal interaction failed: {exc}") from exc
        if type(supported) is not bool:
            raise DriverError(
                "terminal interaction returned invalid setup-recovery support"
            )
        return supported

    # --- ears: the watch handler ([SUM-5]) ---------------------------------

    def _prepare_injection(
        self, item: Message | Notification
    ) -> PreparedInjection | None:
        """Resolve immutable transport work on the owner before worker dispatch."""
        if isinstance(item, Message):
            if item.from_id == self._member_id:
                return None
        elif item.actor_id is not None and item.actor_id == self._member_id:
            return None
        handle = self._handle
        if handle is None:
            raise WatcherRejected("provider is not available for injection")
        generation = self._active_generation
        return PreparedInjection(
            handle, format_injection(item), generation.token if generation else 0
        )

    # --- event pump ([SUM-7.1]) --------------------------------------------

    def _activate_generation(self) -> _GenerationContext:
        """Publish one spawn generation and retire any prior token atomically."""

        self._generation_counter += 1
        generation = _GenerationContext(
            token=self._generation_counter,
            exit=_GenerationExit(),
        )
        self._active_generation = generation
        self._harness_dead.clear()
        return generation

    def _retire_generation(self, generation: _GenerationContext) -> None:
        """Fence a generation before its handle is abandoned or replaced."""
        if self._active_generation is generation:
            self._active_generation = None

    @staticmethod
    def _add_cleanup_note(primary: BaseException, cleanup: BaseException) -> None:
        note = f"cleanup also failed: {type(cleanup).__name__}: {cleanup}"
        add_note = getattr(primary, "add_note", None)
        if callable(add_note):
            add_note(note)
        logger.error(note)

    def _join_pump(
        self,
        generation: _GenerationContext,
        pump: threading.Thread,
        *,
        timeout: float,
        primary: BaseException | None = None,
    ) -> None:
        """Retire and join one pump; timeout is fatal unless another error is primary."""

        self._retire_generation(generation)
        try:
            pump.join(timeout=timeout)
        except BaseException as cleanup:
            if primary is not None:
                self._add_cleanup_note(primary, cleanup)
                return
            raise
        if not pump.is_alive():
            return
        error = DriverError(
            f"event pump did not stop within {timeout:.1f}s; generation "
            f"{generation.token} was retired"
        )
        self._shutdown_error = error
        if primary is not None:
            self._add_cleanup_note(primary, error)
            return
        raise error

    def _teardown_generation(  # noqa: C901 approved [DOM-10.2.1] [RUFF-SUP-026] exception
        self,
        generation: _GenerationContext,
        handle: AdapterHandle,
        pump: threading.Thread | None,
        *,
        timeout: float | None = None,
    ) -> None:
        """Retire, close, and checked-join without replacing an active failure."""

        if timeout is None:
            timeout = _PUMP_JOIN_TIMEOUT_SECONDS
        inherited = sys.exception()
        close_error: BaseException | None = None
        join_error: BaseException | None = None
        self._retire_generation(generation)
        try:
            handle.close()
        except BaseException as cleanup:  # noqa: BLE001 approved [DOM-10.2.1] [RUFF-SUP-067] exception
            if inherited is None:
                close_error = cleanup
            else:
                self._add_cleanup_note(inherited, cleanup)
        if pump is not None:
            try:
                self._join_pump(
                    generation,
                    pump,
                    timeout=timeout,
                    primary=inherited,
                )
            except BaseException as cleanup:  # noqa: BLE001 approved [DOM-10.2.1] [RUFF-SUP-067] exception
                if inherited is None:
                    join_error = cleanup
                else:
                    self._add_cleanup_note(inherited, cleanup)
        if inherited is not None:
            if self._shutdown.is_set():
                self._shutdown_error = inherited
            return
        if join_error is not None:
            if close_error is not None:
                self._add_cleanup_note(join_error, close_error)
            if self._shutdown.is_set():
                self._shutdown_error = join_error
            raise join_error
        if close_error is not None:
            if self._shutdown.is_set():
                self._shutdown_error = close_error
            raise close_error

    def _pump(
        self,
        generation: _GenerationContext,
        handle: AdapterHandle,
        db_path: str | None,
        token: str,
    ) -> None:
        del db_path, token
        error: BaseException | None = None
        try:
            for event in handle.events():
                self._pump_results.put(
                    _PumpResult(generation.token, event, None, False)
                )
                self._publish_owner_activity()
        except BaseException as exc:  # noqa: BLE001 - transfer every transport failure
            error = exc
        finally:
            self._pump_results.put(_PumpResult(generation.token, None, error, True))
            self._publish_owner_activity()

    @staticmethod
    def _record_activity_event(
        event: ActivityEvent, mouth: TautClient, last_activity: float
    ) -> float:
        logger.debug("activity: %s", event.description)
        now = time.monotonic()
        if now - last_activity < _ACTIVITY_WINDOW_SECONDS:
            return last_activity
        try:
            # The public activity seam updates last_active_ts ([SUM-7.1]/[IAN-3.3]).
            mouth.touch_identity_activity()
        except TautError as exc:
            logger.debug("activity resolution failed: %s", exc)
        return now

    # --- helpers ------------------------------------------------------------

    def _rejoin(self, handle: AdapterHandle, boot: _BootstrapResult) -> None:
        """Re-anchor presence at the harness child through token-only selection."""

        capture = _agent_capture(
            handle.pid, rule=f"summon harness child for {boot.member_name}"
        )
        anchor = capture.anchor
        assert anchor is not None
        logger.debug(
            "spawned harness child (pid %s, start %s)",
            anchor.pid,
            anchor.start_time,
        )
        rejoin_client = TautClient(
            db_path=self._db_path,
            token=boot.token,
            identity_capture=capture,
            inherit_environment_identity=False,
        )
        try:
            rejoin_client.rejoin()
        except (NotFoundError, IdentityError) as exc:
            handle.close()
            # Release is centralized in _run's finally ([SUM-8] cleanup).
            raise DriverError(f"cannot re-anchor member: {exc}") from exc
        finally:
            rejoin_client.close()

    def _ensure_threads(self, client: TautClient, member_id: str) -> None:
        for thread in self._request.threads:
            try:
                members = client.who(thread)
            except NotFoundError:
                members = None
            if members is not None and any(m.member_id == member_id for m in members):
                continue
            client.join(thread, persona=self._request.persona)

    def _should_start_pump_before_bootstrap(
        self,
        request: SummonRequest,
        adapter: ProviderAdapter,
        *,
        availability: TerminalAvailability | None,
    ) -> bool:
        """Return whether no attach path can consume early provider terminal IO."""

        if not adapter.supports_attach:
            return False
        if request.detach:
            return True
        assert availability is not None, "terminal availability was not resolved"
        return availability in {
            TerminalAvailability.NESTED_HOST,
            TerminalAvailability.UNAVAILABLE,
        }

    def _terminal_availability(
        self, request: SummonRequest, adapter: ProviderAdapter
    ) -> TerminalAvailability | None:
        """Resolve the host decision once, before provider bootstrap begins."""

        if not adapter.supports_attach or request.detach:
            return None
        intent = TerminalIntent.REQUIRED if request.attach else TerminalIntent.PREFERRED
        try:
            availability = self._interaction.terminal_availability(intent)
        except Exception as exc:
            raise DriverError(f"terminal availability failed: {exc}") from exc
        if not isinstance(availability, TerminalAvailability):
            raise DriverError("terminal interaction returned invalid availability")
        return availability

    def _start_pump(
        self,
        generation: _GenerationContext,
        handle: AdapterHandle,
        *,
        db_path: str | None,
        token: str,
    ) -> threading.Thread:
        pump = threading.Thread(
            target=self._pump,
            args=(
                generation,
                handle,
                db_path,
                token,
            ),
            daemon=True,
            name="taut-summon-pump",
        )
        pump.start()
        return pump

    def _resolve_generation_attach(
        self,
        *,
        boot: _BootstrapResult,
        adapter: ProviderAdapter,
        availability: TerminalAvailability | None,
        first_generation: bool,
    ) -> _GenerationAttachDecision:
        if not adapter.supports_attach:
            return _GenerationAttachDecision(wired=True, should_attach=False)
        request = self._request
        if request.attach:
            self._require_attach_available(availability)
        wired = get_wired(self._ledger(), boot.member_id)
        should_attach = self._pending_setup_recovery_attach or (
            first_generation
            and (
                request.attach
                or (
                    not wired
                    and availability is TerminalAvailability.AVAILABLE
                    and not request.detach
                )
            )
        )
        if not should_attach and not wired:
            self._warn_unwired_without_attach(boot, availability)
        return _GenerationAttachDecision(wired=wired, should_attach=should_attach)

    @staticmethod
    def _require_attach_available(
        availability: TerminalAvailability | None,
    ) -> None:
        errors: dict[TerminalAvailability | None, str] = {
            TerminalAvailability.NO_TTY: "--attach requires a tty",
            TerminalAvailability.NESTED_HOST: (
                "--attach is not available inside TAUT_HOST_TUI=1"
            ),
            TerminalAvailability.UNAVAILABLE: (
                "--attach requires an available terminal"
            ),
        }
        error = errors.get(availability)
        if error is not None:
            raise DriverError(error)

    @staticmethod
    def _warn_unwired_without_attach(
        boot: _BootstrapResult,
        availability: TerminalAvailability | None,
    ) -> None:
        if availability is TerminalAvailability.NO_TTY:
            logger.warning(
                "provider '%s' is not wired yet and no tty is available; "
                "run taut summon --attach %s from a real terminal",
                boot.provider,
                boot.member_name,
            )
        elif availability is TerminalAvailability.NESTED_HOST:
            logger.warning(
                "provider '%s' is not wired yet but attach is refused inside "
                "TAUT_HOST_TUI=1; run from a real terminal or pane",
                boot.provider,
            )
        elif availability is TerminalAvailability.UNAVAILABLE:
            logger.warning(
                "provider '%s' is not wired yet because the host terminal is "
                "unavailable; run taut summon --attach %s from an available terminal",
                boot.provider,
                boot.member_name,
            )

    def _run_terminal_attach(self, handle: AdapterHandle) -> str:
        try:
            lease_manager = self._interaction.terminal_lease()
            lease = lease_manager.__enter__()
        except Exception as exc:
            raise DriverError(f"terminal interaction failed: {exc}") from exc
        try:
            if not isinstance(lease, TerminalLease):
                raise DriverError("terminal interaction returned invalid lease")
            result = handle.attach(
                shutdown=self._shutdown,
                input_fd=lease.input_fd,
                output_fd=lease.output_fd,
            )
            if result not in {"detached", "eof", "shutdown"}:
                raise DriverError(
                    f"provider returned invalid attach result: {result!r}"
                )
        except BaseException as primary:
            try:
                lease_manager.__exit__(type(primary), primary, primary.__traceback__)
            except BaseException as restore_error:  # noqa: BLE001 approved [DOM-10.2.1] [RUFF-SUP-067] exception
                if restore_error is not primary:
                    logger.error(
                        "terminal lease restoration also failed: %s", restore_error
                    )
            if isinstance(primary, (AdapterError, DriverError)) or not isinstance(
                primary, Exception
            ):
                raise
            raise DriverError(f"terminal attach failed: {primary}") from primary
        try:
            lease_manager.__exit__(None, None, None)
        except Exception as exc:
            raise DriverError(f"terminal interaction failed: {exc}") from exc
        return str(result)

    def _system_prompt(self, boot: _BootstrapResult, db_display: str) -> str:
        override = self._request.system_prompt_file
        if override is not None:
            try:
                with open(override, encoding="utf-8") as handle:
                    return handle.read()
            except OSError as exc:
                raise DriverError(f"cannot read --system-prompt-file: {exc}") from exc
        return render_default_persona(
            name=boot.member_name,
            threads=self._request.threads,
            workspace=db_display,
            provider=boot.provider,
        )

    def _automatic_name(
        self, client: TautClient, requested: str, attempted: set[str]
    ) -> str:
        taken = set(attempted)
        for member in client.who():
            taken.add(member.name)
            taken.update(member.aliases)
        return choose_name(seed=requested, taken=taken, fallback="agent")

    def _require_adapter(self, provider: str) -> ProviderAdapter:
        try:
            return get_adapter(provider)
        except UnknownAdapterError as exc:
            raise DriverError(str(exc)) from exc

    def _ledger(self) -> Queue:
        assert self._queue is not None
        return self._queue

    def _release_name_claim_after_failure(
        self,
        queue: Queue,
        *,
        target: str,
        provider: str,
        pid: int,
        start: str,
    ) -> None:
        """Best-effort claim cleanup that preserves the active bootstrap error."""

        try:
            release_claim(
                queue,
                name=target,
                provider=provider,
                driver_pid=pid,
                driver_start_time=start,
            )
        except Exception:
            logger.debug(
                "name-claim cleanup after bootstrap failure failed",
                exc_info=True,
            )

    @staticmethod
    def _residual_member_error(created: Member) -> DriverError:
        """Give the initiating terminal the non-destructive recovery path."""

        assert created.token is not None
        return DriverError(
            "bootstrap failed after creating final member "
            f"'{created.name}'. Residual continuity token: {created.token}. "
            f"Recover with `TAUT_TOKEN={created.token} taut set name "
            "<unused-name>`, then summon again."
        )

    def _require_evidence(self) -> tuple[int, str]:
        assert self._evidence is not None
        return self._evidence

    def _control_shutdown_outcome(self) -> StopShutdownOutcome:
        """Return finalized teardown/release facts after shutdown completion."""

        outcome = self._stop_shutdown_outcome
        if outcome is None:
            raise RuntimeError("driver shutdown outcome was not finalized")
        return outcome

    def _finalize_stop_shutdown_outcome(self) -> StopShutdownOutcome:
        """Freeze shutdown facts before publishing ``_shutdown_complete``."""

        if self._stop_shutdown_outcome is not None:
            return self._stop_shutdown_outcome
        outcome = StopShutdownOutcome(
            release_confirmed=self._release_confirmed,
            teardown_error=(
                str(self._shutdown_error) if self._shutdown_error is not None else None
            ),
            release_error=(
                str(self._release_error) if self._release_error is not None else None
            ),
        )
        self._stop_shutdown_outcome = outcome
        return outcome

    def _release(self) -> None:
        self._release_error = None
        if self._member_id is None or self._evidence is None:
            # Nothing was claimed: the slot is trivially clear of us.
            self._release_confirmed = True
            return
        pid, start = self._evidence
        try:
            self._release_confirmed = release_driver(
                self._ledger(),
                member_id=self._member_id,
                driver_pid=pid,
                driver_start_time=start,
                updated_ts=self._ledger().generate_timestamp(),
            )
        except Exception as exc:  # noqa: BLE001 approved [DOM-10.2.1] [RUFF-SUP-067] exception
            # The ledger release is best-effort cleanup: a stale claim is
            # reclaimable by evidence ([SUM-11]), so cleanup failure must not
            # turn process exit into a second failure. But we could NOT confirm
            # the slot is clear, so a STOP ack must not claim it is — the
            # control loop replies an error instead.
            self._release_confirmed = False
            self._release_error = exc
            logger.error("could not release the driver slot: %s", exc)

    def _install_signals(self) -> dict[int, Any]:
        if threading.current_thread() is not threading.main_thread():
            raise SummonOperationError(
                "signal handler installation requires the Python main thread"
            )
        previous: dict[int, Any] = {}
        for signum in (signal.SIGINT, signal.SIGTERM):
            try:
                prior = signal.getsignal(signum)
                signal.signal(signum, self._on_signal)
            except (ValueError, OSError) as exc:
                for installed_signum, installed_prior in reversed(previous.items()):
                    try:
                        signal.signal(installed_signum, installed_prior)
                    except (ValueError, OSError):
                        logger.exception(
                            "could not roll back signal %s after installation failure",
                            installed_signum,
                        )
                raise SummonOperationError(
                    f"could not install signal handler for signal {signum}: {exc}"
                ) from exc
            previous[signum] = prior
        return previous

    @staticmethod
    def _restore_signals(previous: dict[int, Any]) -> None:
        failures: list[tuple[int, Any, BaseException]] = []
        for signum, prior in reversed(previous.items()):
            try:
                signal.signal(signum, prior)
            except (ValueError, OSError) as exc:
                failures.append((signum, prior, exc))
        if failures:
            details = "; ".join(
                f"signal {signum} to prior disposition {prior!r}: {failure}"
                for signum, prior, failure in failures
            )
            raise SummonOperationError(
                f"could not restore summon signal handlers: {details}"
            ) from failures[0][2]

    def _on_signal(self, signum: int, _frame: object) -> None:
        self._signal_pending = True
        reactor = self._watcher
        if reactor is not None:
            reactor.notify_activity()


def run_driver(
    request: SummonRequest,
    interaction: SummonInteraction,
    *,
    db_path: str | None = None,
    install_signal_handlers: bool = False,
    on_ready: Callable[[SummonRunHandle], None] | None = None,
) -> None:
    """Controller entry: run one summon driver in the foreground."""

    SummonDriver(
        request,
        interaction=interaction,
        db_path=db_path,
        install_signal_handlers=install_signal_handlers,
        on_ready=on_ready,
    ).run()
