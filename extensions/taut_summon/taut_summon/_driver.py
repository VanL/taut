"""The summon driver: bootstrap, ears, event pump, resume ([SUM-4]/[SUM-5]).

One foreground process per summoned member — a terminal emulator, not a
manager ([SUM-2]). The driver owns exactly three runtime lanes:

- **Bootstrap** in [SUM-4]'s six-step order (claim → temp-name create →
  rename → ledger → spawn → token-only rejoin), entirely over public core
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
  of the child ([SUM-7.1]) — session ids to the ledger, activity to the
  member's liveness through rate-limited token-selected ``whoami()``,
  assistant text to the thread in terminal mode or to the log otherwise,
  ``exit`` to the [SUM-11] resume path (one session-id resume attempt,
  fresh-session cursor replay as the fallback, bounded backoff then a
  loud exit).

Shutdown ordering ([SUM-9], shared by SIGINT): stop injection (stop the
watcher) → adapter interrupt (unblocks any in-flight inject) → pump
drains to exit or bounded timeout → ownership-checked driver release →
exit 0.

Test/ops knob: ``TAUT_SUMMON_RESUME_BACKOFF`` (comma-separated seconds,
e.g. ``"0.2,0.2"``) overrides the default resume backoff schedule; the
schedule length bounds the consecutive-crash retries.

Spec references:
- docs/specs/04-summon.md [SUM-3], [SUM-4], [SUM-5], [SUM-6], [SUM-7.1],
  [SUM-8], [SUM-11]
"""

from __future__ import annotations

import getpass
import logging
import os
import secrets
import signal
import sys
import threading
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from simplebroker import Queue

from taut import (
    IdentityError,
    NotFoundError,
    NotInitializedError,
    TautClient,
    TautError,
)
from taut.addressing import classify_registered_queue
from taut.client import Member, Message, Notification, database_path_from_target
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
    AdapterHandle,
    AssistantTextEvent,
    ExitEvent,
    ProviderAdapter,
    SessionEvent,
    UnknownAdapterError,
    get_adapter,
)
from taut_summon._control import ControlLoop
from taut_summon._persona import render_default_persona
from taut_summon._state import (
    ClaimConflictError,
    DriverConflictError,
    SummonStateError,
    capture_driver_evidence,
    claim_driver,
    claim_name,
    ensure_summon_schema,
    get_session,
    get_wired,
    record_session,
    release_claim,
    release_driver,
    set_wired,
    update_session,
)

if TYPE_CHECKING:
    from taut_summon.cli import RunRequest

logger = logging.getLogger("taut_summon.driver")

_LEDGER_QUEUE_NAME = "taut_summon_state"
_DEFAULT_RESUME_BACKOFF = (1.0, 2.0, 4.0)
_HEALTHY_RUN_SECONDS = 60.0
_ACTIVITY_WINDOW_SECONDS = 10.0
_HALT_ACK_TIMEOUT_SECONDS = 30.0
_NAME_RETRY_ATTEMPTS = 5


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
    if item.kind == "notice":
        return f"{prefix} · {item.text}"
    return f"{prefix} {item.from_name}: {item.text}"


def _notify_location(thread: str | None) -> str:
    if not thread:
        return "?"
    if classify_registered_queue(thread) == "dm":
        return "dm"
    return f"#{thread}"


@dataclass(frozen=True, slots=True)
class _BootstrapResult:
    member_id: str
    member_name: str
    token: str
    provider: str
    provider_session_id: str | None


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
    except Exception:  # pragma: no cover - platform-specific lookup gaps
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
        request: RunRequest,
        *,
        install_signal_handlers: bool = True,
    ) -> None:
        self._request = request
        self._install_signal_handlers = install_signal_handlers
        self._backoff = _resume_backoff_from_env()
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
        # Terminates the control thread on driver exit for any reason
        # (a control STOP breaks its loop earlier, via the pending-stop
        # flag). Set in _run's finally.
        self._control_stop = threading.Event()
        self._control_thread: threading.Thread | None = None
        self._handle: AdapterHandle | None = None
        # The live watcher, published so the ears handler can stop it
        # directly on adapter death — the wedged-supervisor-safe halt
        # ([TAUT-8.4]: a per-message raise loop would poison-advance).
        self._watcher: Any | None = None
        self._member_id: str | None = None
        self._exit_code: int | None = None
        self._queue: Queue | None = None
        self._evidence: tuple[int, str] | None = None

    # --- public entry ----------------------------------------------------

    def run(self) -> int:
        # The driver process is nobody: its clients are explicitly
        # selected (as_name/token/capture), and ambient TAUT_AS/TAUT_TOKEN
        # from the launching shell must not leak into them — or into
        # rejoin's exactly-one-selector contract.
        os.environ.pop("TAUT_AS", None)
        os.environ.pop("TAUT_TOKEN", None)
        if self._install_signal_handlers:
            self._install_signals()
        try:
            return self._run()
        except NotInitializedError:
            # The CLI owns this diagnostic: with no database there can be
            # no session row, so [SUM-3] resolution may still surface the
            # unknown-adapter error instead ([SUM-3] step 3).
            raise
        except DriverError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        except (SummonStateError, AdapterError, TautError) as exc:
            print(str(exc), file=sys.stderr)
            return 1

    def request_stop(self) -> None:
        self._shutdown.set()
        handle = self._handle
        if handle is not None:
            try:
                handle.interrupt()
            except AdapterError:
                logger.debug("adapter interrupt during stop failed", exc_info=True)
        self._wake.set()

    # --- bootstrap ([SUM-4]) ----------------------------------------------

    def _run(self) -> int:
        request = self._request
        client = TautClient(db_path=request.db_path)
        db_display = database_path_from_target(client.target)
        self._queue = client.queue(_LEDGER_QUEUE_NAME)
        try:
            ensure_summon_schema(self._queue)
            self._evidence = capture_driver_evidence()
            boot = self._bootstrap(client)
            self._member_id = boot.member_id
            try:
                return self._supervise(boot, db_display)
            finally:
                # Ownership-checked release covering EVERY post-claim fatal
                # path once member_id is set (bad --system-prompt-file,
                # watch() failure, TautError in _ensure_threads, any error
                # inside _supervise). Release BEFORE letting the control
                # thread ack a STOP, so the stop client sees the reply only
                # after the ledger is clear ([SUM-9]). Idempotent — a second
                # release is a no-op.
                self._release()
                self._shutdown_complete.set()
                self._control_stop.set()
                if self._control_thread is not None:
                    self._control_thread.join(timeout=_HALT_ACK_TIMEOUT_SECONDS)
        finally:
            self._queue.close()

    def _bootstrap(self, client: TautClient) -> _BootstrapResult:
        request = self._request
        requested = request.name
        implied = request.provider_flag is None
        member = self._find_member(client, requested)
        row = (
            get_session(self._ledger(), member.member_id)
            if member is not None
            else None
        )

        if row is not None:
            assert member is not None
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
            return _BootstrapResult(
                member_id=member.member_id,
                member_name=member.name,
                token=row["token"],
                provider=row["provider"],
                provider_session_id=row["provider_session_id"],
            )

        # First summon (or a foreign, never-summoned member holds the
        # name). Resolve the provider first: --provider, else the name
        # itself as an adapter ([SUM-3] steps 1 and 3).
        provider = request.provider_flag or requested
        self._require_adapter(provider)

        target = requested
        if member is not None:
            # A member exists but was never summoned: never adopt.
            if not implied:
                raise DriverError(
                    f"member '{requested}' already exists and was not "
                    "summoned; pick another name"
                )
            target = self._fallback_name(client, requested, set())
            logger.warning("summoned as '%s' — '%s' is taken", target, requested)
        return self._first_summon(client, requested, target, provider, implied)

    def _first_summon(
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

        # Step 0: claim the (name, provider) slot. A concurrent loser
        # applies the [SUM-4] collision rule: implied names retry through
        # the pool, chosen names refuse loudly.
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
                break
            except ClaimConflictError as exc:
                if not implied:
                    raise DriverError(str(exc)) from exc
                target = self._fallback_name(client, requested, attempted)
                attempted.add(target)
                logger.warning(
                    "summon of '%s' is already in flight; trying '%s'",
                    requested,
                    target,
                )
        else:
            raise DriverError(
                f"could not claim a name for '{requested}' after "
                f"{_NAME_RETRY_ATTEMPTS} attempts"
            )

        # Step 1: create under a collision-proof temp name with a
        # driver-anchored agent capture. A fresh name cannot adopt;
        # creation is asserted via the public last_created_member signal.
        temp = f"{target[:48]}-{secrets.token_hex(4)}"
        creator = TautClient(
            db_path=self._request.db_path,
            as_name=temp,
            identity_capture=_agent_capture(
                os.getpid(), rule="summon driver bootstrap anchor"
            ),
        )
        first_thread = self._request.threads[0]
        creator.join(first_thread, persona=self._request.persona)
        created = creator.last_created_member
        if created is None or created.token is None:
            release_claim(
                queue,
                name=target,
                provider=provider,
                driver_pid=pid,
                driver_start_time=start,
            )
            raise DriverError("bootstrap failed: the temp-named member was not created")

        # Step 2: take the target name (fail-loud core rename). A
        # mid-bootstrap collision falls back for implied and chosen names
        # alike ([SUM-4] round-13 rule) — refusal here would strand the
        # temp-named member, fallback leaves no debris.
        for _ in range(_NAME_RETRY_ATTEMPTS):
            try:
                creator.set_name(target)
                break
            except IdentityError:
                release_claim(
                    queue,
                    name=target,
                    provider=provider,
                    driver_pid=pid,
                    driver_start_time=start,
                )
                fallback = self._fallback_name(client, requested, attempted)
                attempted.add(fallback)
                logger.warning(
                    "requested name '%s' was taken mid-summon; member will "
                    "be '%s' — rename with 'taut set name' if needed",
                    target,
                    fallback,
                )
                target = fallback
                try:
                    claim_name(
                        queue,
                        name=target,
                        provider=provider,
                        driver_pid=pid,
                        driver_start_time=start,
                        claimed_ts=queue.generate_timestamp(),
                    )
                except ClaimConflictError:
                    continue
        else:
            raise DriverError(
                f"could not settle a name for '{requested}' after "
                f"{_NAME_RETRY_ATTEMPTS} attempts"
            )

        # Join the remaining threads BEFORE recording the session row.
        # record_session is the readiness signal (stop/status resolve off
        # it, and callers wait on it): a summon thread joined only later, in
        # _supervise, would silently drop anything said into it between
        # readiness and that join ([TAUT-7.4]: joining starts you at now).
        # Idempotent (skips threads[0], already joined at creation).
        self._ensure_threads(creator, created.member_id)

        # Step 3: record the durable session row, then release the claim —
        # old names free up the moment they stop being load-bearing.
        record_session(
            queue,
            member_id=created.member_id,
            token=created.token,
            provider=provider,
            provider_session_id=None,
            driver_pid=pid,
            driver_start_time=start,
            updated_ts=queue.generate_timestamp(),
        )
        release_claim(
            queue,
            name=target,
            provider=provider,
            driver_pid=pid,
            driver_start_time=start,
        )
        return _BootstrapResult(
            member_id=created.member_id,
            member_name=target,
            token=created.token,
            provider=provider,
            provider_session_id=None,
        )

    # --- supervision loop (steps 4-5, ears, pump, resume) ------------------

    def _supervise(self, boot: _BootstrapResult, db_display: str) -> int:
        request = self._request
        adapter = self._require_adapter(boot.provider)
        env = {"TAUT_TOKEN": boot.token, "TAUT_DB": db_display}
        system_prompt = self._system_prompt(boot, db_display)
        terminal_thread = (
            request.threads[0]
            if (
                request.terminal
                and adapter.supports_terminal_mode
                and len(request.threads) == 1
            )
            else None
        )
        if request.terminal and not adapter.supports_terminal_mode:
            logger.warning(
                "--terminal is not supported by provider '%s'; assistant text "
                "will go to the log",
                adapter.name,
            )
        elif request.terminal and terminal_thread is None:
            logger.warning(
                "--terminal requires exactly one thread; assistant text "
                "will go to the log"
            )
        watch_client = TautClient(db_path=request.db_path, token=boot.token)
        mouth_client = TautClient(db_path=request.db_path, token=boot.token)

        self._start_control_thread(boot)

        session_id = boot.provider_session_id
        consecutive_crashes = 0
        first_generation = True
        while True:
            started_at = time.monotonic()
            handle = self._spawn(adapter, session_id, system_prompt, env)
            self._handle = handle
            self._harness_dead.clear()
            self._halt_ack.clear()
            self._exit_code = None
            pump: threading.Thread | None = None
            try:
                if self._should_start_pump_before_bootstrap(request, adapter):
                    pump = self._start_pump(
                        handle,
                        mouth_client,
                        boot.member_id,
                        terminal_thread,
                    )
                self._rejoin(handle, boot)
                self._ensure_threads(watch_client, boot.member_id)
                if adapter.supports_attach:
                    wired = get_wired(self._ledger(), boot.member_id)
                    attach_result = self._attach_if_needed(
                        handle,
                        boot=boot,
                        wired=wired,
                        first_generation=first_generation,
                    )
                    if attach_result == "shutdown":
                        handle.close()
                        return 0
                    if attach_result == "detached":
                        set_wired(
                            self._ledger(),
                            member_id=boot.member_id,
                            value=True,
                            updated_ts=self._ledger().generate_timestamp(),
                        )
                        wired = True
                    if not wired and hasattr(handle, "mark_awaiting_onboarding"):
                        handle.mark_awaiting_onboarding()
                if pump is None:
                    pump = self._start_pump(
                        handle,
                        mouth_client,
                        boot.member_id,
                        terminal_thread,
                    )
            except Exception:
                handle.close()
                if pump is not None:
                    pump.join(timeout=10.0)
                raise
            assert pump is not None
            if self._shutdown.is_set():
                return self._shutdown_current_generation(handle, pump, boot)
            if first_generation:
                first_generation = False
            if adapter.orientation_via_inject:
                try:
                    self._settle_for_orientation(handle)
                    if self._shutdown.is_set():
                        return self._shutdown_current_generation(handle, pump, boot)
                    handle.inject(system_prompt)
                except AdapterError as exc:
                    if self._shutdown.is_set():
                        return self._shutdown_current_generation(handle, pump, boot)
                    handle.close()
                    pump.join(timeout=10.0)
                    raise DriverError(f"cannot orient the harness: {exc}") from exc
            try:
                watcher = watch_client.watch(self._on_item)
            except TautError as exc:
                handle.close()
                pump.join(timeout=10.0)
                raise DriverError(f"cannot watch chat: {exc}") from exc
            self._watcher = watcher
            watcher_ready = threading.Event()
            notify_ready = getattr(watcher, "notify_ready_after_initial_drain", None)
            if callable(notify_ready):
                notify_ready(watcher_ready)
            else:  # pragma: no cover - TautClient.watch returns TautWatcher today
                watcher_ready.set()
            watcher_thread = self._start_watcher_thread(watcher)
            deadline = time.monotonic() + 30.0
            while (
                not watcher_ready.is_set()
                and not self._harness_dead.is_set()
                and not self._shutdown.is_set()
                and time.monotonic() < deadline
            ):
                watcher_ready.wait(timeout=0.05)
            if (
                not watcher_ready.is_set()
                and not self._harness_dead.is_set()
                and not self._shutdown.is_set()
            ):
                watcher.stop(join=False)
                handle.close()
                pump.join(timeout=10.0)
                raise DriverError("cannot watch chat: watcher did not become ready")
            if watcher_ready.is_set():
                logger.info(
                    "summoned '%s' (member %s, provider %s, threads %s)",
                    boot.member_name,
                    boot.member_id,
                    boot.provider,
                    ", ".join(request.threads),
                )

            self._await_wake()

            # Shutdown ordering ([SUM-9]): stop injection, unblock any
            # in-flight inject via interrupt, drain the pump, release.
            watcher.stop(join=False)
            self._halt_ack.set()
            if self._shutdown.is_set():
                handle.interrupt()
                handle.close()
            watcher_thread.join(timeout=30.0)
            watcher.stop(join=True)

            if self._shutdown.is_set():
                return self._shutdown_current_generation(handle, pump, boot)

            # Harness death ([SUM-11]): one resume attempt with the stored
            # session id; a failed spawn falls back to a fresh session
            # whose cursor replay recovers the conversation.
            handle.close()
            pump.join(timeout=10.0)
            lived = time.monotonic() - started_at
            consecutive_crashes = (
                1 if lived >= _HEALTHY_RUN_SECONDS else consecutive_crashes + 1
            )
            if consecutive_crashes > len(self._backoff):
                raise DriverError(
                    f"harness for '{boot.member_name}' exited "
                    f"{consecutive_crashes} times in a row (last exit code "
                    f"{self._exit_code}); giving up"
                )
            delay = self._backoff[consecutive_crashes - 1]
            logger.warning(
                "harness exited (code %s); resuming in %.1fs (attempt %d/%d)",
                self._exit_code,
                delay,
                consecutive_crashes,
                len(self._backoff),
            )
            self._shutdown.wait(timeout=delay)
            if self._shutdown.is_set():
                return 0
            stored = get_session(self._ledger(), boot.member_id)
            session_id = (
                stored["provider_session_id"] if stored is not None else None
            ) or handle.session_id

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

        Stop the watcher **directly** before raising, so re-delivery — and
        with it [TAUT-8.4]'s 3-strikes poison advance — cannot happen even
        if the supervisor is wedged and never acks. ``stop(join=False)``
        only signals the stop event; it is safe to call from inside the
        watcher's own handler thread and is idempotent. Then wake the
        supervisor and raise so this delivery's cursor stays put for
        re-injection on resume ([SUM-5.4]). The ``_halt_ack`` wait is a
        courtesy for ordering, no longer the safety mechanism, so its
        timeout firing early can never cause a poison advance.
        """

        watcher = self._watcher
        if watcher is not None:
            try:
                watcher.stop(join=False)
            except Exception:  # pragma: no cover - defensive: stop is idempotent
                logger.debug("watcher stop during halt failed", exc_info=True)
        self._harness_dead.set()
        self._wake.set()
        self._halt_ack.wait(timeout=_HALT_ACK_TIMEOUT_SECONDS)
        raise _InjectionHalted("injection halted pending harness resume") from cause

    # --- event pump ([SUM-7.1]) --------------------------------------------

    def _pump(
        self,
        handle: AdapterHandle,
        mouth: TautClient,
        member_id: str,
        terminal_thread: str | None,
    ) -> None:
        queue = mouth.queue(_LEDGER_QUEUE_NAME)
        last_activity = 0.0
        try:
            for event in handle.events():
                last_activity = self._pump_event(
                    event, queue, mouth, member_id, terminal_thread, last_activity
                )
        except AdapterError as exc:
            logger.error("adapter event stream failed: %s", exc)
        finally:
            queue.close()
            self._harness_dead.set()
            self._wake.set()

    def _pump_event(
        self,
        event: AdapterEvent,
        queue: Queue,
        mouth: TautClient,
        member_id: str,
        terminal_thread: str | None,
        last_activity: float,
    ) -> float:
        if isinstance(event, SessionEvent):
            logger.debug("session id: %s", event.session_id)
            try:
                update_session(
                    queue,
                    member_id=member_id,
                    provider_session_id=event.session_id,
                    updated_ts=queue.generate_timestamp(),
                )
            except SummonStateError as exc:
                logger.error("could not record session id: %s", exc)
        elif isinstance(event, ActivityEvent):
            logger.debug("activity: %s", event.description)
            now = time.monotonic()
            if now - last_activity >= _ACTIVITY_WINDOW_SECONDS:
                last_activity = now
                try:
                    # The public activity seam: token-selected whoami()
                    # updates last_active_ts ([SUM-7.1]/[IAN-3.3]).
                    mouth.whoami()
                except TautError as exc:
                    logger.debug("activity resolution failed: %s", exc)
        elif isinstance(event, AssistantTextEvent):
            if terminal_thread is not None:
                try:
                    mouth.say(terminal_thread, event.text)
                except TautError as exc:
                    logger.error("terminal-mode post failed: %s", exc)
            else:
                # stdout is diagnostics, not speech ([SUM-6]).
                logger.info("assistant: %s", event.text)
        elif isinstance(event, ExitEvent):
            self._exit_code = event.returncode
            logger.info("harness exited with code %s", event.returncode)
        return last_activity

    # --- helpers ------------------------------------------------------------

    def _spawn(
        self,
        adapter: ProviderAdapter,
        session_id: str | None,
        system_prompt: str,
        env: dict[str, str],
    ) -> AdapterHandle:
        if session_id is not None:
            try:
                return adapter.spawn(
                    session_id=session_id,
                    system_prompt=system_prompt,
                    env=env,
                )
            except AdapterError as exc:
                logger.warning(
                    "resume with session '%s' failed (%s); starting a fresh "
                    "session with cursor replay",
                    session_id,
                    exc,
                )
        try:
            return adapter.spawn(session_id=None, system_prompt=system_prompt, env=env)
        except AdapterError as exc:
            # Release is centralized in _run's finally ([SUM-8] cleanup).
            raise DriverError(f"cannot spawn the harness: {exc}") from exc

    def _rejoin(self, handle: AdapterHandle, boot: _BootstrapResult) -> None:
        """Step 5: re-anchor presence at the harness child (token-only)."""

        capture = _agent_capture(
            handle.pid, rule=f"summon harness child for {boot.member_name}"
        )
        rejoin_client = TautClient(
            db_path=self._request.db_path,
            token=boot.token,
            identity_capture=capture,
        )
        try:
            rejoin_client.rejoin()
        except (NotFoundError, IdentityError) as exc:
            handle.close()
            # Release is centralized in _run's finally ([SUM-8] cleanup).
            raise DriverError(f"cannot re-anchor member: {exc}") from exc

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
        wait_until_quiet = getattr(handle, "wait_until_quiet", None)
        if callable(wait_until_quiet):
            wait_until_quiet()

    def _should_start_pump_before_bootstrap(
        self, request: RunRequest, adapter: ProviderAdapter
    ) -> bool:
        """Return whether no attach path can consume early provider terminal IO."""

        if not adapter.supports_attach:
            return False
        if request.attach:
            return False
        if request.detach:
            return True
        if os.environ.get("TAUT_HOST_TUI") == "1":
            return True
        return not sys.stdin.isatty()

    def _start_pump(
        self,
        handle: AdapterHandle,
        mouth_client: TautClient,
        member_id: str,
        terminal_thread: str | None,
    ) -> threading.Thread:
        pump = threading.Thread(
            target=self._pump,
            args=(handle, mouth_client, member_id, terminal_thread),
            daemon=True,
            name="taut-summon-pump",
        )
        pump.start()
        return pump

    def _shutdown_current_generation(
        self,
        handle: AdapterHandle,
        pump: threading.Thread,
        boot: _BootstrapResult,
    ) -> int:
        handle.interrupt()
        handle.close()
        pump.join(timeout=5.0)
        # Release + control-thread STOP ack are ordered by _run's finally
        # ([SUM-9]); nothing to release here.
        logger.info("dismissed '%s' cleanly", boot.member_name)
        return 0

    def _attach_if_needed(
        self,
        handle: AdapterHandle,
        *,
        boot: _BootstrapResult,
        wired: bool,
        first_generation: bool,
    ) -> str | None:
        request = self._request
        nested = os.environ.get("TAUT_HOST_TUI") == "1"
        has_tty = sys.stdin.isatty()
        if request.attach:
            if not has_tty:
                raise DriverError("--attach requires a tty")
            if nested:
                raise DriverError("--attach is not available inside TAUT_HOST_TUI=1")
        should_attach = first_generation and (
            request.attach
            or (not wired and has_tty and not nested and not request.detach)
        )
        if not should_attach:
            if not wired and not has_tty:
                logger.warning(
                    "provider '%s' is not wired yet and no tty is available; "
                    "run taut summon --attach %s from a real terminal",
                    boot.provider,
                    boot.member_name,
                )
            elif not wired and nested:
                logger.warning(
                    "provider '%s' is not wired yet but attach is refused inside "
                    "TAUT_HOST_TUI=1; run from a real terminal or pane",
                    boot.provider,
                )
            return None
        attach = getattr(handle, "attach", None)
        if not callable(attach):
            raise DriverError(f"provider '{boot.provider}' does not support attach")
        logger.info("attaching '%s'; detach with Ctrl-\\ Ctrl-\\", boot.member_name)
        return str(attach(wake=self._wake, shutdown=self._shutdown))

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

    def _find_member(self, client: TautClient, name: str) -> Member | None:
        wanted = name.lower()
        for member in client.who():
            if member.name.lower() == wanted:
                return member
            if any(alias.lower() == wanted for alias in member.aliases):
                return member
        return None

    def _fallback_name(
        self, client: TautClient, requested: str, attempted: set[str]
    ) -> str:
        taken = {requested, *attempted}
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

    def _require_evidence(self) -> tuple[int, str]:
        assert self._evidence is not None
        return self._evidence

    def _start_control_thread(self, boot: _BootstrapResult) -> None:
        """Start the [SUM-9] control consumer + [SUM-10] rate backstop.

        The loop owns all its db handles, opened on its own thread — the
        driver hands it only plain values and a stop callback, so no
        connection is shared across threads.
        """

        driver_pid, driver_start_time = self._require_evidence()
        loop = ControlLoop(
            member_id=boot.member_id,
            db_path=self._request.db_path,
            token=boot.token,
            provider=boot.provider,
            threads=self._request.threads,
            handle_provider=lambda: self._handle,
            request_stop=self.request_stop,
            shutdown=self._control_stop,
            shutdown_complete=self._shutdown_complete,
            release_confirmed=lambda: self._release_confirmed,
            rate_limit=self._request.rate_limit,
            ledger_queue_name=_LEDGER_QUEUE_NAME,
            driver_pid=driver_pid,
            driver_start_time=driver_start_time,
        )
        thread = threading.Thread(
            target=loop.run, daemon=True, name="taut-summon-control"
        )
        self._control_thread = thread
        thread.start()

    def _start_watcher_thread(self, watcher: Any) -> threading.Thread:
        """Run the chat watcher and wake the supervisor if it exits early."""

        def _run_watcher() -> None:
            try:
                watcher.run()
            except Exception:
                if not self._shutdown.is_set() and not self._harness_dead.is_set():
                    logger.exception("watcher failed; resuming harness from cursor")
            finally:
                if (
                    not self._shutdown.is_set()
                    and not self._harness_dead.is_set()
                    and not self._halt_ack.is_set()
                ):
                    self._harness_dead.set()
                    self._wake.set()

        thread = threading.Thread(
            target=_run_watcher, daemon=True, name="taut-summon-watcher"
        )
        thread.start()
        return thread

    def _release(self) -> None:
        if self._member_id is None or self._evidence is None:
            # Nothing was claimed: the slot is trivially clear of us.
            self._release_confirmed = True
            return
        pid, start = self._evidence
        try:
            release_driver(
                self._ledger(),
                member_id=self._member_id,
                driver_pid=pid,
                driver_start_time=start,
                updated_ts=self._ledger().generate_timestamp(),
            )
            # release_driver returns True (we cleared it) or False (the row
            # is no longer ours — already released or taken over). Either
            # way the slot is not held by *us*, which is what STOP must
            # confirm before the control loop acks ([SUM-9]).
            self._release_confirmed = True
        except Exception as exc:  # noqa: BLE001 - cleanup must never crash exit
            # The ledger release is best-effort cleanup: a stale claim is
            # reclaimable by evidence ([SUM-11]), so a transient broker
            # failure here (e.g. a WAL malformed-page read under load) must
            # not turn a clean shutdown into a non-zero exit. But we could
            # NOT confirm the slot is clear, so a STOP ack must not claim it
            # is — the control loop replies an error instead.
            self._release_confirmed = False
            logger.error("could not release the driver slot: %s", exc)

    def _await_wake(self) -> None:
        while not (self._shutdown.is_set() or self._harness_dead.is_set()):
            self._wake.wait(timeout=0.2)
            self._wake.clear()

    def _install_signals(self) -> None:
        if threading.current_thread() is not threading.main_thread():
            return  # pragma: no cover - the CLI always runs on the main thread
        for signum in (signal.SIGINT, signal.SIGTERM):
            try:
                signal.signal(signum, self._on_signal)
            except (ValueError, OSError):  # pragma: no cover - odd embeddings
                pass

    def _on_signal(self, signum: int, _frame: object) -> None:
        logger.info("received signal %s; stopping", signum)
        self.request_stop()


def run_driver(request: RunRequest) -> int:
    """CLI entry: run one summon driver in the foreground."""

    return SummonDriver(request).run()
