"""The summon driver: bootstrap, ears, event pump, resume ([SUM-4]/[SUM-5]).

One foreground process per summoned member — a terminal emulator, not a
manager ([SUM-2]). The driver owns exactly three runtime lanes:

- **Bootstrap** in [SUM-4]'s order (claim → fail-not-adopt final-name create
  → ledger → spawn → token-only rejoin), entirely over public core
  seams: ``TautClient(identity_capture=..., token=...)``, ``join``,
  ``set_name``, ``rejoin``, and the ``taut.identity`` capture surface
  blessed for extensions.
- **Ears**: a ``TautClient.watch`` handler that is exactly self-filter →
  format ([SUM-5.2]) → ``inject()`` → return. The watcher's
  handler-return contract IS the injection ledger — this module contains
  **zero cursor code** ([SUM-5.4]). Adapter death is fatal-and-resume:
  the handler halts injection on the first failed inject (blocking until
  the driver has stopped the watcher) so [TAUT-8.4]'s 3-strikes poison
  advance can never skip live chat.
- **Event pump**: a dedicated thread draining ``events()`` for the life
  of the child ([SUM-7.1]). Activity updates member liveness through
  rate-limited token-selected ``whoami()``; ``exit`` enters [SUM-11]'s
  fresh-generation recovery path with durable cursor replay, bounded
  backoff, and then a loud exit.

Shutdown ordering ([SUM-9], shared by SIGINT): publish shutdown → request
terminal close on the adapter → stop and checked-join the watcher →
foreground adapter finalization while the pump drains → checked pump join →
ownership-checked driver release → exit 0. Signal and control paths never
wait, join, or reap.

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
)
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
    ExitEvent,
    ProviderAdapter,
    UnknownAdapterError,
    get_adapter,
)
from taut_summon._control import ControlLoop, StopShutdownOutcome
from taut_summon._members import find_member
from taut_summon._persona import render_default_persona
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
_SHUTDOWN_PUMP_JOIN_TIMEOUT_SECONDS = 5.0
_HALT_ACK_TIMEOUT_SECONDS = 30.0
_WATCHER_JOIN_TIMEOUT_SECONDS = 30.0
_FOREGROUND_READINESS_TIMEOUT_SECONDS = 30.0
_NAME_RETRY_ATTEMPTS = 5
_WATCHER_RESTART_BACKOFF = (0.2, 0.5, 1.0, 2.0, 4.0, 8.0, 8.0, 8.0)


class DriverError(Exception):
    """A fatal driver condition; its message is the exit-1 diagnostic."""


class _InjectionHalted(Exception):
    """Raised out of the watch handler so the cursor stays put.

    Exactly one of these surfaces per halt: the handler waits for the
    driver to request watcher stop before raising, so [TAUT-8.4]'s
    3-strikes poison advance can never trigger on adapter death.
    """


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


@dataclass(slots=True)
class _GenerationExit:
    """Generation-local exit state; never reused by a later spawn."""

    returncode: int | None = None


@dataclass(slots=True)
class _GenerationFailure:
    """Fatal pump failure transferred from the worker to the foreground."""

    error: BaseException | None = None


@dataclass(frozen=True, slots=True)
class _GenerationContext:
    """All pump-written state for one immutable [SUM-11] spawn identity."""

    token: int
    completion: threading.Event
    harness_dead: threading.Event
    wake: threading.Event
    exit: _GenerationExit
    failure: _GenerationFailure


@dataclass(frozen=True, slots=True)
class _RunningGeneration:
    """Foreground-owned resources for one fully bootstrapped generation."""

    started_at: float
    handle: AdapterHandle
    generation: _GenerationContext
    pump: threading.Thread


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
        self._control_ready = threading.Event() if on_ready is not None else None
        self._run_completion = threading.Event() if on_ready is not None else None
        self._backoff = _resume_backoff_from_env()
        # [SUM-7.4] setup-recovery escalation: at most one offer per
        # foreground run, consumed whether the human proceeds or declines.
        self._setup_recovery_consumed = False
        self._pending_setup_recovery_attach = False
        self._setup_recovery_excerpt: str | None = None
        self._shutdown = threading.Event()
        self._harness_dead = threading.Event()
        self._halt_ack = threading.Event()
        self._wake = threading.Event()
        # Set once the clean-shutdown path has released the driver slot, so
        # the control thread can ack a STOP only after the ledger is clear
        # ([SUM-9]: the stop client observes both the reply and the
        # evidence release).
        self._shutdown_complete = threading.Event()
        # Whether _release() confirmed the slot is clear of our evidence.
        # A STOP ack asserts release ([SUM-9]); if release could not be
        # confirmed (persistent broker failure), the control loop replies
        # an error rather than a false ack.
        self._release_confirmed = False
        self._release_error: BaseException | None = None
        self._stop_shutdown_outcome: StopShutdownOutcome | None = None
        # Terminates the control thread on driver exit for any reason
        # (a control STOP breaks its loop earlier, via the pending-stop
        # flag). Set in _run's finally.
        self._control_stop = threading.Event()
        self._control_thread: threading.Thread | None = None
        self._control_loop: ControlLoop | None = None
        self._control_failed = threading.Event()
        self._control_error: BaseException | None = None
        self._control_failure_lock = threading.Lock()
        self._handle: AdapterHandle | None = None
        # The live watcher, published so the ears handler can stop it
        # directly on adapter death — the wedged-supervisor-safe halt
        # ([TAUT-8.4]: a per-message raise loop would poison-advance).
        self._watcher: Any | None = None
        self._watcher_failed = threading.Event()
        self._watcher_error: BaseException | None = None
        self._member_id: str | None = None
        self._exit_code: int | None = None
        self._generation_lock = threading.RLock()
        self._generation_counter = 0
        self._active_generation: _GenerationContext | None = None
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
        self._wake.set()

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
                inherited = sys.exception()
                # Ownership-checked release covering EVERY post-claim fatal
                # path, including a bootstrap failure after member_id becomes
                # known. Release BEFORE letting the control thread ack a STOP,
                # so the stop client sees the reply only after the ledger is
                # clear ([SUM-9]). Idempotent — a second release is a no-op.
                self._release()
                self._finalize_stop_shutdown_outcome()
                self._shutdown_complete.set()
                self._control_stop.set()
                if self._control_thread is not None:
                    self._control_thread.join(timeout=_HALT_ACK_TIMEOUT_SECONDS)
                    if self._control_thread.is_alive():
                        cleanup = DriverError(
                            "Summon control owner did not stop within "
                            "the cleanup budget"
                        )
                        if inherited is not None:
                            self._add_cleanup_note(inherited, cleanup)
                        # The public foreground run is the exact ownership
                        # boundary. Keep it live after the cleanup budget is
                        # exhausted so hosts can classify this run as
                        # unresolved until the control owner actually exits.
                        self._control_thread.join()
                        if inherited is None:
                            raise cleanup
                self._control_loop = None
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
        else:
            raise DriverError(
                f"could not claim a name for '{requested}' after "
                f"{_NAME_RETRY_ATTEMPTS} attempts"
            )
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

    # --- supervision loop (steps 4-5, ears, pump, resume) ------------------

    def _supervise(
        self,
        boot: _BootstrapResult,
        db_display: str,
        *,
        db_path: str | None = None,
    ) -> int:
        request = self._request
        adapter = self._require_adapter(boot.provider)
        if request.attach and not adapter.supports_attach:
            raise DriverError(f"provider '{boot.provider}' does not support attach")
        terminal_availability = self._terminal_availability(request, adapter)
        env = _harness_environment(boot, db_path=db_path)
        system_prompt = self._system_prompt(boot, db_display)
        consecutive_crashes = 0
        first_generation = True
        while True:
            attach_decision = self._prepare_generation_start(
                boot=boot,
                adapter=adapter,
                availability=terminal_availability,
                first_generation=first_generation,
            )
            if attach_decision is None:
                return 0
            running = self._start_live_generation(
                boot=boot,
                adapter=adapter,
                env=env,
                system_prompt=system_prompt,
                terminal_availability=terminal_availability,
                attach_decision=attach_decision,
            )
            if running is None:
                self._raise_if_foreground_readiness_pending()
                return 0
            if self._shutdown.is_set():
                return self._shutdown_before_or_after_readiness(running, boot)
            first_generation = False
            orientation = self._orient_running_generation(
                running,
                adapter,
                system_prompt,
                boot=boot,
                availability=terminal_availability,
                attached_this_generation=attach_decision.should_attach,
            )
            if orientation != "oriented":
                consecutive_crashes, result = self._finish_orientation_outcome(
                    orientation,
                    running,
                    boot,
                    consecutive_crashes,
                    adapter,
                )
                if result is not None:
                    return result
                continue
            self._await_running_generation(running, boot)
            if self._shutdown.is_set():
                return self._shutdown_running_generation(running, boot)
            consecutive_crashes, _ = self._resume_after_harness_exit(
                running, boot, consecutive_crashes, adapter=adapter
            )
            if self._shutdown.is_set():
                return 0

    def _start_live_generation(
        self,
        *,
        boot: _BootstrapResult,
        adapter: ProviderAdapter,
        env: dict[str, str],
        system_prompt: str,
        terminal_availability: TerminalAvailability | None,
        attach_decision: _GenerationAttachDecision,
    ) -> _RunningGeneration | None:
        started_at = time.monotonic()
        handle = self._spawn(adapter, system_prompt, env)
        self._handle = handle
        self._request_close_after_publication_if_needed(handle)
        generation = self._activate_generation()
        self._halt_ack.clear()
        pump: threading.Thread | None = None
        try:
            if self._should_start_pump_before_bootstrap(
                self._request, adapter, availability=terminal_availability
            ):
                pump = self._start_generation_pump(generation, handle, boot)
            self._rejoin(handle, boot)
            self._ensure_generation_threads(boot)
            if self._prepare_generation_attach(
                handle,
                boot=boot,
                attach_decision=attach_decision,
            ):
                self._teardown_generation(generation, handle, pump)
                return None
            if pump is None:
                pump = self._start_generation_pump(generation, handle, boot)
            self._raise_if_pump_failed(generation)
            self._start_control_thread(boot)
            self._raise_if_control_failed()
        except Exception:
            self._teardown_generation(generation, handle, pump)
            raise
        assert pump is not None
        return _RunningGeneration(started_at, handle, generation, pump)

    def _request_close_after_publication_if_needed(self, handle: AdapterHandle) -> None:
        if not (self._shutdown.is_set() or self._control_failed.is_set()):
            return
        try:
            handle.request_close()
        except AdapterError:
            logger.debug(
                "adapter close request after publication failed", exc_info=True
            )

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

    def _prepare_generation_attach(
        self,
        handle: AdapterHandle,
        *,
        boot: _BootstrapResult,
        attach_decision: _GenerationAttachDecision,
    ) -> bool:
        wired = attach_decision.wired
        result = (
            self._run_terminal_attach(handle) if attach_decision.should_attach else None
        )
        if result == "shutdown":
            return True
        if result == "detached":
            set_wired(
                self._ledger(),
                member_id=boot.member_id,
                value=True,
                updated_ts=self._ledger().generate_timestamp(),
            )
            wired = True
            logger.info(
                "provider setup ended for '%s'; starting the Taut listener; "
                "keep this command running and chat from another terminal",
                boot.member_name,
            )
        if not wired:
            handle.mark_awaiting_onboarding()
        return False

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

    def _orient_running_generation(
        self,
        running: _RunningGeneration,
        adapter: ProviderAdapter,
        system_prompt: str,
        *,
        boot: _BootstrapResult,
        availability: TerminalAvailability | None,
        attached_this_generation: bool,
    ) -> str:
        """Settle, then orient, escalate, or report shutdown.

        Returns ``"oriented"``, ``"shutdown"``, ``"exited"``, or
        ``"setup-recovery"``. The
        setup-recovery return has already torn the suspect generation down
        ([SUM-7.4]: teardown always precedes the acknowledgement request).
        """
        if not adapter.orientation_via_inject:
            return "oriented"
        try:
            self._settle_for_orientation(running.handle)
            if self._shutdown.is_set():
                return "shutdown"
            if self._should_offer_setup_recovery(
                running.handle,
                adapter,
                availability,
                attached_this_generation=attached_this_generation,
            ):
                self._setup_recovery_consumed = True
                self._pending_setup_recovery_attach = True
                logger.warning(
                    "provider '%s' settled without an input prompt; offering "
                    "an acknowledged setup attach instead of injecting",
                    boot.member_name,
                )
                # [SUM-7.4]: capture the suspect screen for the offer before
                # the teardown that always precedes the acknowledgement. The
                # tail is diagnostic, so its failure never changes the outcome.
                try:
                    tail = running.handle.output_tail()
                except Exception:  # noqa: BLE001 approved [DOM-10.2.1] [RUFF-SUP-067] exception
                    tail = ""
                self._setup_recovery_excerpt = tail or None
                self._teardown_generation(
                    running.generation, running.handle, running.pump
                )
                return "setup-recovery"
            if not running.handle.input_prompt_observed:
                running.handle.mark_awaiting_onboarding()
                logger.warning(
                    "provider '%s' settled without an input prompt; injecting "
                    "orientation anyway (no setup-recovery path available)",
                    boot.member_name,
                )
            running.handle.inject(system_prompt)
        except AdapterError as exc:
            try:
                self._raise_if_control_failed()
            except DriverError:
                self._teardown_generation(
                    running.generation, running.handle, running.pump
                )
                raise
            if not self._shutdown.is_set():
                if isinstance(exc, AdapterExitedError):
                    return self._orientation_exit_outcome(running, exc)
                self._teardown_generation(
                    running.generation, running.handle, running.pump
                )
                raise DriverError(f"cannot orient the harness: {exc}") from exc
        # Leave the AdapterError scope before shutdown teardown so the caught
        # write interruption cannot become the primary shutdown failure.
        return "shutdown" if self._shutdown.is_set() else "oriented"

    def _orientation_exit_outcome(
        self,
        running: _RunningGeneration,
        exc: AdapterExitedError,
    ) -> str:
        if self._on_ready is None or self._ready_callback_invoked:
            return "exited"
        self._teardown_generation(running.generation, running.handle, running.pump)
        raise DriverError(
            "provider generation exited before foreground readiness"
        ) from exc

    def _finish_orientation_outcome(
        self,
        outcome: str,
        running: _RunningGeneration,
        boot: _BootstrapResult,
        consecutive_crashes: int,
        adapter: ProviderAdapter,
    ) -> tuple[int, int | None]:
        if outcome == "shutdown":
            return consecutive_crashes, self._shutdown_running_generation(running, boot)
        if outcome == "exited":
            crashes, _ = self._resume_after_harness_exit(
                running, boot, consecutive_crashes, adapter=adapter
            )
            return crashes, None
        assert outcome == "setup-recovery"
        return consecutive_crashes, None

    def _await_running_generation(
        self, running: _RunningGeneration, boot: _BootstrapResult
    ) -> None:
        try:
            self._watch_until_wake(boot)
            self._raise_if_pump_failed(running.generation)
            if self._on_ready is not None and not self._ready_callback_invoked:
                self._raise_if_readiness_aborted(running.generation.harness_dead)
        except BaseException:
            self._teardown_generation(running.generation, running.handle, running.pump)
            raise

    def _shutdown_running_generation(
        self, running: _RunningGeneration, boot: _BootstrapResult
    ) -> int:
        return self._shutdown_current_generation(
            running.generation, running.handle, running.pump, boot
        )

    def _shutdown_before_or_after_readiness(
        self, running: _RunningGeneration, boot: _BootstrapResult
    ) -> int:
        result = self._shutdown_running_generation(running, boot)
        self._raise_if_foreground_readiness_pending()
        return result

    def _raise_if_foreground_readiness_pending(self) -> None:
        if getattr(self, "_on_ready", None) is not None and not getattr(
            self, "_ready_callback_invoked", False
        ):
            raise DriverError("foreground readiness aborted by driver shutdown")

    def _resume_after_harness_exit(
        self,
        running: _RunningGeneration,
        boot: _BootstrapResult,
        consecutive_crashes: int,
        *,
        adapter: ProviderAdapter,
    ) -> tuple[int, str | None]:
        self._teardown_generation(running.generation, running.handle, running.pump)
        lived = time.monotonic() - running.started_at
        crashes = 1 if lived >= _HEALTHY_RUN_SECONDS else consecutive_crashes + 1
        if crashes > len(self._backoff):
            message = (
                f"harness for '{boot.member_name}' exited {crashes} times in a row "
                f"(last exit code {running.generation.exit.returncode}); giving up"
            )
            # [SUM-11]: the tail is best-effort diagnostics — its failure
            # never changes the driver outcome.
            try:
                tail = running.handle.output_tail()
            except Exception:  # noqa: BLE001 approved [DOM-10.2.1] [RUFF-SUP-067] exception
                tail = ""
            if tail:
                message += f"\nlast screen output:\n{tail}"
            if adapter.supports_attach:
                message += (
                    "\nprovider may be waiting on interactive setup; "
                    f"run: taut summon --attach {boot.member_name}"
                )
            raise DriverError(message)
        delay = self._backoff[crashes - 1]
        logger.warning(
            "harness exited (code %s); resuming in %.1fs (attempt %d/%d)",
            running.generation.exit.returncode,
            delay,
            crashes,
            len(self._backoff),
        )
        self._shutdown.wait(timeout=delay)
        if self._shutdown.is_set():
            return crashes, None
        return crashes, None

    # --- ears: the watch handler ([SUM-5]) ---------------------------------

    def _on_item(self, item: Message | Notification) -> None:
        if self._halt_ack.is_set() or self._harness_dead.is_set():
            self._halt_and_raise(None)
        if isinstance(item, Message):
            if item.from_id == self._member_id:
                return
        elif item.actor_id is not None and item.actor_id == self._member_id:
            return
        handle = self._handle
        if handle is None:  # pragma: no cover - watcher runs only with a handle
            self._halt_and_raise(None)
            return
        line = format_injection(item)
        try:
            handle.inject(line)
        except AdapterError as exc:
            logger.warning("inject failed; halting injection: %s", exc)
            self._halt_and_raise(exc)

    def _halt_and_raise(self, cause: Exception | None) -> None:
        """Adapter death is fatal-and-resume, never a per-message error.

        Signal the watcher before raising so re-delivery, and with it
        [TAUT-8.4]'s poison-advance budget, cannot run while the supervisor
        unwinds the failed generation. Final close belongs to the watcher
        drive owner; an in-handler callback must never close live reactor
        resources ([SUM-9]). Then wake the supervisor and preserve this
        delivery's cursor for re-injection on resume ([SUM-5.4]).
        """

        watcher = self._watcher
        if watcher is not None:
            try:
                watcher.request_stop()
            except Exception:  # pragma: no cover - defensive signal path
                logger.debug("watcher stop request during halt failed", exc_info=True)
        self._harness_dead.set()
        self._wake.set()
        self._halt_ack.wait(timeout=_HALT_ACK_TIMEOUT_SECONDS)
        raise _InjectionHalted("injection halted pending harness resume") from cause

    # --- event pump ([SUM-7.1]) --------------------------------------------

    def _activate_generation(self) -> _GenerationContext:
        """Publish one spawn generation and retire any prior token atomically."""

        with self._generation_lock:
            self._generation_counter += 1
            generation = _GenerationContext(
                token=self._generation_counter,
                completion=threading.Event(),
                harness_dead=threading.Event(),
                wake=threading.Event(),
                exit=_GenerationExit(),
                failure=_GenerationFailure(),
            )
            self._active_generation = generation
            # Compatibility aliases for the foreground/watch paths. A stale
            # pump retains only its context objects and can never reach these
            # aliases after the next generation is published.
            self._harness_dead = generation.harness_dead
            self._wake = generation.wake
            self._exit_code = None
            return generation

    def _retire_generation(self, generation: _GenerationContext) -> None:
        """Fence a generation before its handle is abandoned or replaced."""

        with self._generation_lock:
            if self._active_generation is generation:
                self._active_generation = None

    def _finish_generation(self, generation: _GenerationContext) -> None:
        """Publish pump completion only to the generation that produced it."""

        generation.completion.set()
        generation.harness_dead.set()
        with self._generation_lock:
            if self._active_generation is generation:
                generation.wake.set()

    def _report_pump_failure(
        self,
        generation: _GenerationContext,
        error: BaseException,
    ) -> None:
        """Publish a storage/setup failure only to its still-active owner."""

        with self._generation_lock:
            if self._active_generation is not generation:
                return
            if generation.failure.error is None:
                generation.failure.error = error
            generation.harness_dead.set()
            generation.wake.set()

    def _raise_if_pump_failed(self, generation: _GenerationContext) -> None:
        """Raise a worker failure on the foreground supervision lane."""

        with self._generation_lock:
            error = generation.failure.error
        if error is None:
            return
        raise DriverError(f"event pump storage failed: {error}") from error

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
        mouth: TautClient | None = None
        last_activity = 0.0
        try:
            with self._generation_lock:
                if self._active_generation is not generation:
                    return
                mouth = TautClient(
                    db_path=db_path,
                    token=token,
                    persistent=True,
                    inherit_environment_identity=False,
                )
            for event in handle.events():
                last_activity = self._pump_event(
                    event,
                    mouth,
                    last_activity,
                    generation=generation,
                )
        except AdapterError as exc:
            logger.error("adapter event stream failed: %s", exc)
        except (BrokerError, TautError) as exc:
            logger.error("event pump storage failed: %s", exc)
            self._report_pump_failure(generation, exc)
        finally:
            if mouth is not None:
                try:
                    mouth.close()
                except Exception:  # pragma: no cover - defensive cleanup
                    logger.debug("event pump client close failed", exc_info=True)
            self._finish_generation(generation)

    def _pump_event(
        self,
        event: AdapterEvent,
        mouth: TautClient,
        last_activity: float,
        *,
        generation: _GenerationContext,
    ) -> float:
        # Hold the generation lock across the side effect. A check followed by
        # an unlocked write would let retirement race between the two.
        with self._generation_lock:
            if self._active_generation is not generation:
                return last_activity
            if isinstance(event, ActivityEvent):
                last_activity = self._record_activity_event(event, mouth, last_activity)
            elif isinstance(event, ExitEvent):
                self._record_exit_event(event, generation)
        return last_activity

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
            mouth.whoami()
        except TautError as exc:
            logger.debug("activity resolution failed: %s", exc)
        return now

    def _record_exit_event(
        self, event: ExitEvent, generation: _GenerationContext
    ) -> None:
        generation.exit.returncode = event.returncode
        self._exit_code = event.returncode
        logger.info("harness exited with code %s", event.returncode)

    # --- helpers ------------------------------------------------------------

    def _spawn(
        self,
        adapter: ProviderAdapter,
        system_prompt: str,
        env: dict[str, str],
    ) -> AdapterHandle:
        try:
            return adapter.spawn(system_prompt=system_prompt, env=env)
        except AdapterError as exc:
            # Release is centralized in _run's finally ([SUM-8] cleanup).
            raise DriverError(f"cannot spawn the harness: {exc}") from exc

    def _rejoin(self, handle: AdapterHandle, boot: _BootstrapResult) -> None:
        """Re-anchor presence at the harness child through token-only selection."""

        capture = _agent_capture(
            handle.pid, rule=f"summon harness child for {boot.member_name}"
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

    def _settle_for_orientation(self, handle: AdapterHandle) -> None:
        handle.wait_until_quiet()

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
        if availability is None:
            raise DriverError("terminal availability was not resolved")
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

    def _shutdown_current_generation(
        self,
        generation: _GenerationContext,
        handle: AdapterHandle,
        pump: threading.Thread,
        boot: _BootstrapResult,
    ) -> int:
        self._teardown_generation(
            generation,
            handle,
            pump,
            timeout=_SHUTDOWN_PUMP_JOIN_TIMEOUT_SECONDS,
        )
        # Release + control-thread STOP ack are ordered by _run's finally
        # ([SUM-9]); nothing to release here.
        logger.info("dismissed '%s' cleanly", boot.member_name)
        return 0

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

    def _prepare_generation_start(
        self,
        *,
        boot: _BootstrapResult,
        adapter: ProviderAdapter,
        availability: TerminalAvailability | None,
        first_generation: bool,
    ) -> _GenerationAttachDecision | None:
        decision = self._resolve_generation_attach(
            boot=boot,
            adapter=adapter,
            availability=availability,
            first_generation=first_generation,
        )
        setup_recovery = self._pending_setup_recovery_attach
        self._pending_setup_recovery_attach = False
        if not decision.should_attach:
            return decision
        if not self._confirm_terminal_attach(boot):
            if setup_recovery and not self._shutdown.is_set():
                # [SUM-7.4]: an explicit human decline of the setup-recovery
                # offer continues the detached path; only shutdown ends here.
                logger.info(
                    "declined provider setup recovery for '%s'; continuing detached",
                    boot.member_name,
                )
                return _GenerationAttachDecision(
                    wired=decision.wired, should_attach=False
                )
            logger.info("cancelled provider setup for '%s'", boot.member_name)
            return None
        if self._shutdown.is_set():
            return None
        return decision

    def _confirm_terminal_attach(self, boot: _BootstrapResult) -> bool:
        notice = TerminalAttachNotice(
            member=boot.member_name,
            provider=boot.provider,
            detach_hint="Ctrl-\\ Ctrl-\\",
            screen_excerpt=self._setup_recovery_excerpt,
        )
        self._setup_recovery_excerpt = None
        try:
            proceed = self._interaction.confirm_terminal_attach(
                notice,
                cancel=self._shutdown,
            )
        except Exception as exc:
            raise DriverError(f"terminal acknowledgement failed: {exc}") from exc
        if type(proceed) is not bool:
            raise DriverError("terminal interaction returned invalid acknowledgement")
        if proceed:
            logger.info(
                "attaching '%s'; detach with Ctrl-\\ Ctrl-\\",
                boot.member_name,
            )
        return proceed

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
                wake=self._wake,
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

    def _watch_until_wake(
        self,
        boot: _BootstrapResult,
    ) -> None:
        """Keep the chat watcher alive until shutdown or harness death.

        Watcher storage failures are not harness failures. Rebuild the
        watcher against the same provider generation first; the provider crash
        budget belongs to pump exit and injection failure.
        """

        self._raise_if_control_failed()
        watcher_failures = 0
        harness_dead = self._harness_dead
        while not (
            self._shutdown.is_set()
            or harness_dead.is_set()
            or self._control_failed.is_set()
        ):
            self._watcher_failed.clear()
            self._watcher_error = None
            self._halt_ack.clear()
            attempt_stop = threading.Event()
            watcher_ready = threading.Event()
            watcher_thread = self._start_watcher_thread(
                db_path=self._db_path,
                token=boot.token,
                ready_event=watcher_ready,
                attempt_stop=attempt_stop,
                harness_dead=harness_dead,
            )
            deadline = time.monotonic() + 30.0
            while (
                not watcher_ready.is_set()
                and not self._watcher_failed.is_set()
                and not harness_dead.is_set()
                and not self._shutdown.is_set()
                and not self._control_failed.is_set()
                and time.monotonic() < deadline
            ):
                watcher_ready.wait(timeout=0.05)
            if (
                not watcher_ready.is_set()
                and not self._watcher_failed.is_set()
                and not harness_dead.is_set()
                and not self._shutdown.is_set()
                and not self._control_failed.is_set()
            ):
                self._halt_ack.set()
                self._request_watcher_attempt_stop(attempt_stop)
                self._join_watcher_attempt(watcher_thread)
                raise DriverError("cannot watch chat: watcher did not become ready")
            if watcher_ready.is_set():
                if getattr(self, "_on_ready", None) is not None and not getattr(
                    self, "_ready_callback_invoked", False
                ):
                    try:
                        self._await_control_and_publish_ready(boot, harness_dead)
                    except BaseException:
                        self._halt_ack.set()
                        self._request_watcher_attempt_stop(attempt_stop)
                        self._join_watcher_attempt(watcher_thread)
                        raise
                logger.info(
                    "summoned '%s' (member %s, provider %s, threads %s)",
                    boot.member_name,
                    boot.member_id,
                    boot.provider,
                    ", ".join(self._request.threads),
                )

            self._await_wake()

            # Watcher coordination owns only watcher stop and checked join.
            # The signal/control path already requested terminal retirement;
            # foreground generation teardown owns blocking adapter close.
            self._halt_ack.set()
            self._request_watcher_attempt_stop(attempt_stop)
            self._join_watcher_attempt(watcher_thread)

            self._raise_if_control_failed()

            if (
                self._watcher_failed.is_set()
                and not self._shutdown.is_set()
                and not harness_dead.is_set()
            ):
                watcher_failures += 1
                if watcher_failures > len(_WATCHER_RESTART_BACKOFF):
                    detail = (
                        f": {self._watcher_error}"
                        if self._watcher_error is not None
                        else ""
                    )
                    raise DriverError(
                        "watcher exited "
                        f"{watcher_failures} times in a row{detail}; giving up"
                    )
                delay = _WATCHER_RESTART_BACKOFF[watcher_failures - 1]
                logger.warning(
                    "watcher exited; rebuilding in %.1fs (attempt %d/%d)",
                    delay,
                    watcher_failures,
                    len(_WATCHER_RESTART_BACKOFF),
                )
                self._watcher_failed.clear()
                self._watcher_error = None
                self._shutdown.wait(timeout=delay)
                continue
            return
        self._raise_if_control_failed()

    def _await_control_and_publish_ready(
        self,
        boot: _BootstrapResult,
        harness_dead: threading.Event,
    ) -> None:
        """Join first-generation identity, watcher, and public-control readiness."""

        callback = self._on_ready
        control_ready = self._control_ready
        completion = self._run_completion
        if callback is None or self._ready_callback_invoked:
            return
        assert control_ready is not None
        assert completion is not None

        deadline = time.monotonic() + _FOREGROUND_READINESS_TIMEOUT_SECONDS
        while not control_ready.is_set():
            self._raise_if_readiness_aborted(harness_dead)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                self.request_stop()
                raise DriverError(
                    "control loop did not become ready within "
                    f"{_FOREGROUND_READINESS_TIMEOUT_SECONDS:.1f}s"
                )
            control_ready.wait(timeout=min(0.05, remaining))

        self._raise_if_readiness_aborted(harness_dead)

        live_handle = self._handle
        if live_handle is None:
            raise DriverError("provider handle disappeared before foreground readiness")
        member = SummonedMember(
            member_id=boot.member_id,
            name=boot.member_name,
            provider=boot.provider,
        )
        run_handle = SummonRunHandle(
            member,
            _request_stop=self.request_stop,
            _completion=completion,
        )
        self._ready_callback_invoked = True
        try:
            callback(run_handle)
        except Exception as exc:
            raise SummonOperationError("summon readiness callback failed") from exc

    def _raise_if_readiness_aborted(self, harness_dead: threading.Event) -> None:
        self._raise_if_control_failed()
        if self._shutdown.is_set():
            raise DriverError("foreground readiness aborted by driver shutdown")
        if harness_dead.is_set():
            raise DriverError("provider generation exited before foreground readiness")
        if self._watcher_failed.is_set():
            detail = (
                f": {self._watcher_error}" if self._watcher_error is not None else ""
            )
            raise DriverError(f"watcher exited before foreground readiness{detail}")

    def _request_watcher_attempt_stop(
        self,
        attempt_stop: threading.Event,
    ) -> None:
        """Publish attempt-local stop before signaling a published watcher."""

        attempt_stop.set()
        watcher = self._watcher
        if watcher is None:
            return
        try:
            watcher.request_stop()
        except Exception:  # pragma: no cover - checked join remains authoritative
            logger.debug("watcher stop request failed", exc_info=True)

    @staticmethod
    def _join_watcher_attempt(watcher_thread: threading.Thread) -> None:
        """Require one watcher owner to exit before another can be started."""

        watcher_thread.join(timeout=_WATCHER_JOIN_TIMEOUT_SECONDS)
        if watcher_thread.is_alive():
            raise DriverError(
                f"watcher did not stop within {_WATCHER_JOIN_TIMEOUT_SECONDS:.1f}s"
            )

    def _start_control_thread(self, boot: _BootstrapResult) -> None:
        """Start the [SUM-9] control consumer + [SUM-10] rate backstop.

        The loop owns all its db handles, opened on its own thread — the
        driver hands it only plain values and a stop callback, so no
        connection is shared across threads.
        """

        if self._control_thread is not None and self._control_thread.is_alive():
            return
        self._raise_if_control_failed()

        self._control_stop.clear()
        driver_pid, driver_start_time = self._require_evidence()
        if self._audit_start_ts is None:
            raise DriverError("rate audit start timestamp was not initialized")
        loop = ControlLoop(
            member_id=boot.member_id,
            db_path=self._db_path,
            token=boot.token,
            provider=boot.provider,
            threads=self._request.threads,
            handle_provider=lambda: self._handle,
            request_stop=self.request_stop,
            shutdown=self._control_stop,
            shutdown_complete=self._shutdown_complete,
            shutdown_outcome=self._control_shutdown_outcome,
            rate_limit=self._request.rate_limit,
            ledger_queue_name=_LEDGER_QUEUE_NAME,
            driver_pid=driver_pid,
            driver_start_time=driver_start_time,
            audit_start_ts=self._audit_start_ts,
            ready=self._control_ready,
        )
        self._control_loop = loop
        thread = threading.Thread(
            target=self._run_control_loop,
            args=(loop,),
            daemon=True,
            name="taut-summon-control",
        )
        self._control_thread = thread
        thread.start()

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

    def _run_control_loop(self, loop: ControlLoop) -> None:
        """Transfer unexpected [SUM-9]/[SUM-11] control death to the owner."""

        try:
            loop.run()
        except BaseException as exc:
            if self._control_stop.is_set() or self._shutdown.is_set():
                logger.debug(
                    "control loop stopped during driver shutdown", exc_info=True
                )
                return
            self._report_control_failure(exc)
            return
        if not (self._control_stop.is_set() or self._shutdown.is_set()):
            self._report_control_failure(
                RuntimeError("control loop exited unexpectedly without a stop request")
            )

    def _report_control_failure(self, error: BaseException) -> None:
        """Publish the primary control error and wake the foreground supervisor."""

        with self._control_failure_lock:
            if self._control_failed.is_set():
                return
            self._control_error = error
            self._control_failed.set()

        watcher = self._watcher
        if watcher is not None:
            try:
                watcher.request_stop()
            except Exception:  # pragma: no cover - preserve the primary failure
                logger.debug(
                    "watcher stop request after control failure failed", exc_info=True
                )
        handle = self._handle
        if handle is not None:
            try:
                handle.request_close()
            except Exception:  # pragma: no cover - preserve the primary failure
                logger.debug(
                    "adapter close request after control failure failed",
                    exc_info=True,
                )
        self._wake.set()

    def _raise_if_control_failed(self) -> None:
        if not self._control_failed.is_set():
            return
        error = self._control_error
        if error is None:  # pragma: no cover - Event publication follows assignment
            error = RuntimeError("control loop failed without a diagnostic")
        raise DriverError(f"control loop failed: {error}") from error

    def _stop_control_thread_for_handoff(self) -> None:
        thread = self._control_thread
        if thread is None:
            return
        self._control_stop.set()
        thread.join(timeout=_HALT_ACK_TIMEOUT_SECONDS)
        if thread.is_alive():
            logger.warning("control thread did not stop during handoff")
            return
        self._control_thread = None
        self._control_loop = None
        self._control_stop.clear()

    def _start_watcher_thread(
        self,
        *,
        db_path: str | None,
        token: str,
        ready_event: threading.Event,
        attempt_stop: threading.Event,
        harness_dead: threading.Event,
    ) -> threading.Thread:
        """Open and run the chat watcher on its owning thread."""

        thread = threading.Thread(
            target=self._run_watcher_attempt,
            kwargs={
                "db_path": db_path,
                "token": token,
                "ready_event": ready_event,
                "attempt_stop": attempt_stop,
                "harness_dead": harness_dead,
            },
            daemon=True,
            name="taut-summon-watcher",
        )
        thread.start()
        return thread

    def _watcher_stop_requested(
        self, attempt_stop: threading.Event, harness_dead: threading.Event
    ) -> bool:
        return (
            attempt_stop.is_set()
            or harness_dead.is_set()
            or self._shutdown.is_set()
            or self._control_failed.is_set()
        )

    def _run_watcher_attempt(  # noqa: C901 approved [DOM-10.2.1] [RUFF-SUP-064] exception
        self,
        *,
        db_path: str | None,
        token: str,
        ready_event: threading.Event,
        attempt_stop: threading.Event,
        harness_dead: threading.Event,
    ) -> None:
        """Own one watcher attempt from construction through cleanup."""

        failed = False
        client: TautClient | None = None
        watcher: Any | None = None
        try:
            client = TautClient(
                db_path=db_path,
                token=token,
                persistent=True,
                inherit_environment_identity=False,
            )
            watcher = client.watch(self._on_item, persistent=True)
            self._watcher = watcher
            if self._watcher_stop_requested(attempt_stop, harness_dead):
                return
            notify_ready = getattr(watcher, "notify_ready_after_initial_drain", None)
            if callable(notify_ready):
                notify_ready(ready_event)
            else:  # pragma: no cover - TautClient.watch returns TautWatcher today
                ready_event.set()
            if self._watcher_stop_requested(attempt_stop, harness_dead):
                return
            watcher.run()
        except Exception as exc:
            if (
                not self._watcher_stop_requested(attempt_stop, harness_dead)
                and not self._halt_ack.is_set()
            ):
                failed = True
                self._watcher_error = exc
                self._watcher_failed.set()
                logger.exception("watcher failed; rebuilding watcher from cursor")
        finally:
            if watcher is not None and self._watcher is watcher:
                self._watcher = None
            if watcher is not None:
                try:
                    watcher.stop(join=False)
                except Exception:  # pragma: no cover - defensive cleanup
                    logger.debug("watcher stop during cleanup failed", exc_info=True)
            if client is not None:
                try:
                    client.close()
                except Exception:  # pragma: no cover - defensive cleanup
                    logger.debug("watcher client close failed", exc_info=True)
            if not (
                self._watcher_stop_requested(attempt_stop, harness_dead)
                or self._halt_ack.is_set()
            ):
                if not failed:
                    self._watcher_error = None
                    self._watcher_failed.set()
                    logger.warning("watcher exited; rebuilding watcher")
                self._wake.set()

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

    def _await_wake(self) -> None:
        while not (
            self._shutdown.is_set()
            or self._harness_dead.is_set()
            or self._watcher_failed.is_set()
            or self._control_failed.is_set()
        ):
            self._wake.wait(timeout=0.2)
            self._wake.clear()

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
        logger.info("received signal %s; stopping", signum)
        self.request_stop()


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
