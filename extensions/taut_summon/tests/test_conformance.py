"""[SUM-12] conformance suite — portable, parameterized over the adapter.

This is the obligation [TAUT-12.3]/[SUM-12] name: the summon behaviors a
*second project* (Weft) must be able to run against its own agent lane. It
expresses the six named [SUM-12] conformance items as tests written against
a small, provider-agnostic :class:`ConformanceHarness` interface and
parameterized over a harness *factory*, so the same assertions run against
the ``scripted`` adapter today and slot a Weft adapter in by supplying another
factory.

The anti-mocking floor is inherited whole from the shared harness in
``conftest.py``: real ``taut-summon run`` subprocess driver, real
``taut`` CLI peer writers, real scripted-provider child, real queues. No
mocks anywhere; the ``scripted`` adapter *is* the blessed provider seam
([SUM-12]) — a real subprocess speaking the real stream shapes, only the
model faked.

Relationship to ``test_driver.py``
----------------------------------
``test_driver.py`` holds the taut-specific *deep* proofs (six-step
bootstrap, name-collision rules, event-pump flood, rename discipline, the
concurrent-summon race). This module does not re-litigate those; it is the
*portable* layer, asserting only the provider-agnostic conformance contract
through the harness interface so it cannot silently diverge from the deep
proofs — both drive the identical ``DriverProcess`` harness.

[SUM-12] coverage map (named item -> conformance test here -> deep proof)
------------------------------------------------------------------------
1. Control responsiveness while idle AND mid-turn
   - here: ``test_control_responsive_when_idle`` (idle PING),
     ``test_control_responsive_mid_turn`` (busy STATUS)
   - deep: ``test_driver.py::test_ping_responds_while_harness_busy``,
     ``::test_status_reports_live_driver_fields``
2. Restart with conversation scope intact — session resume AND fresh replay
   - here: ``test_restart_resumes_stored_session`` (resume),
     ``test_restart_replays_conversation_tail`` (fresh replay)
   - deep: ``test_driver.py::test_crash_resume_offers_stored_session_and_replays``,
     ``::test_resummon_replays_tail_and_filters_own_messages``
3. Backpressure when the agent is slower than the chat
   - here: ``test_backpressure_surfaces_as_unread``
   - deep: ``test_driver.py::test_backpressure_blocked_inject_grows_unread_and_stop_still_works``
     (the Phase-D deterministic barrier keyed on ``driver_pid`` replaced the
     old ``time.sleep(0.5)`` race settle — no sleep-based synchronization is
     used here or there; this suite adds none)
4. Clean shutdown on stop with no double-speak
   - here: ``test_clean_shutdown_releases_and_no_double_speak``
   - deep: ``test_driver.py::test_stop_from_another_terminal``,
     ``::test_first_summon_creates_agent_member_with_ledger_row`` (stop tail)
5. Single-driver guard
   - here: ``test_single_driver_guard_refuses_second``
   - deep: ``test_driver.py::test_second_summon_of_live_member_is_refused``
6. Injection format stability
   - here: ``test_injection_format_is_stable`` (unit golden, provider-agnostic)
   - deep: ``test_driver.py`` format goldens + ``test_injection_round_trip_*``

Live provider proof belongs in dedicated live tests, not in a collected
placeholder conformance parameter. The local-only PTY harness matrix lives in
``test_live_harness.py``; the CI-safe local LLM lane lives in
``test_live_local_llm.py``.

What a second project (Weft) supplies to reuse this suite
---------------------------------------------------------
A harness *factory* — a callable ``(request) -> ConformanceHarness`` — added
to ``HARNESS_FACTORIES`` (or contributed from the runner's own conftest)
whose harness implements :class:`ConformanceHarness` against its agent lane:

- ``start(...)`` — spawn a driver that hosts the agent under the adapter and
  return a handle exposing ``stop()``/``wait()``/liveness;
- ``wait_ready(driver)`` — block until the member is present and its session
  ledger row exists (provider-agnostic readiness, no received-log needed);
- ``peer_say(thread, text)`` — a peer writes chat the agent should hear;
- ``control(name, command)`` / ``stop_via_cli(name)`` — the [SUM-9] control
  round-trip;
- ledger/identity reads (``session_row``/``member``/``member_token``);
- capability flags ``supports_scenarios`` (can the harness script agent
  behavior: echo/stall/sleep/session-id?) and ``has_received_log`` (can it
  observe exactly what the agent's ears received?). Items needing a
  capability the harness lacks ``skip`` with a precise reason rather than
  weakening the assertion. The taut ``scripted`` harness supplies both; a
  Weft-style harness supplies whatever its agent lane can, and items it
cannot express skip themselves.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from conftest import (
    DriverProcess,
    _await_control_request,
    _base_env,
    _member_by_name,
    _member_token,
    _session_row,
    _wait_for_session_row,
    say,
    summon_cli,
    taut_cli,
    wait_until,
)
from taut_summon._driver import format_injection

from taut.client import Message, Notification, TautClient

pytestmark = [pytest.mark.xdist_group("process"), pytest.mark.sqlite_only]

# --- the portable harness interface ------------------------------------------


@dataclass
class ConformanceHarness:
    """Provider-agnostic operations the [SUM-12] assertions program against.

    The taut binding wraps the shared ``DriverProcess`` harness; a second
    project supplies its own binding with the same surface (see the module
    docstring's portability contract).
    """

    provider: str
    summon_db: Path
    tmp_path: Path
    driver_factory: Callable[..., DriverProcess]
    supports_scenarios: bool
    has_received_log: bool
    _tag_seq: list[int] = field(default_factory=lambda: [0])

    # -- capability gates (skip, never weaken) --------------------------------

    def require_scenarios(self) -> None:
        if not self.supports_scenarios:
            pytest.skip(
                f"the {self.provider!r} harness cannot script agent behavior; "
                "the scripted adapter is the conformance seam; live providers "
                "belong in the dedicated live harness lanes"
            )

    def require_received_log(self) -> None:
        if not self.has_received_log:
            pytest.skip(
                f"the {self.provider!r} harness cannot observe the agent's "
                "ears (no received-log); the scripted adapter is the "
                "observation seam ([SUM-12])"
            )

    # -- lifecycle ------------------------------------------------------------

    def start(
        self,
        name: str,
        *threads: str,
        scenario: dict[str, Any] | None = None,
        **run_opts: Any,
    ) -> DriverProcess:
        """Spawn a driver hosting the agent under this harness's adapter.

        ``scenario`` scripts the (scripted) provider's behavior; passing one
        requires ``supports_scenarios`` (callers gate with
        ``require_scenarios`` first). ``--provider`` is always supplied so
        the member name is a *chosen* name ([SUM-3]/[SUM-4]) — deterministic
        for the guard/collision items.
        """

        self._tag_seq[0] += 1
        tag = f"{self.provider}-conf-{self._tag_seq[0]}"
        return self.driver_factory(
            self.summon_db,
            name,
            *threads,
            provider=self.provider,
            scenario=scenario,
            tag=tag,
            **run_opts,
        )

    def wait_ready(self, driver: DriverProcess) -> Any:
        """Block until the member exists, is present, and has a ledger row.

        The scripted conformance harness has a received-log, so it can use the
        same full readiness barrier as the deep driver tests: provider start,
        bootstrap, watcher initial drain, and a control PING. Future live
        harness factories without a received-log keep the weaker portable
        presence/session barrier and should add their own provider-specific
        readiness proof before they send control traffic.
        """

        if self.has_received_log:
            driver.wait_for_start()
        member = None

        def present_member() -> bool:
            nonlocal member
            candidate = _member_by_name(self.summon_db, driver.name)
            if candidate is None:
                return False
            if getattr(candidate, "presence", None) != "here":
                return False
            member = candidate
            return True

        wait_until(
            present_member,
            message=f"summoned member '{driver.name}'; stderr: {driver.stderr_tail()}",
        )
        assert member is not None
        _wait_for_session_row(
            self.summon_db,
            member.member_id,
            message=f"session row for '{driver.name}'",
        )
        return member

    def _ready_member(self, name: str) -> Any | None:
        member = _member_by_name(self.summon_db, name)
        if member is None:
            return None
        if getattr(member, "presence", None) != "here":
            return None
        if _session_row(self.summon_db, member.member_id) is None:
            return None
        return member

    # -- observation ----------------------------------------------------------

    def member(self, name: str) -> Any | None:
        return _member_by_name(self.summon_db, name)

    def session_row(self, member_id: str) -> dict[str, Any] | None:
        return _session_row(self.summon_db, member_id)

    def member_token(self, name: str) -> str:
        return _member_token(self.summon_db, name)

    def peer_say(self, thread: str, text: str, *, as_name: str = "van") -> None:
        say(self.summon_db, self.tmp_path, thread, text, as_name=as_name)

    def unread(self, name: str, thread: str) -> int:
        token = self.member_token(name)
        client = TautClient(db_path=self.summon_db, token=token)
        try:
            for entry in client.list_threads(all_threads=True):
                if entry.name == thread:
                    return entry.unread_count
        except Exception:  # noqa: BLE001 - transient during teardown
            return -1
        return -1

    def speech_by_member(self, name: str, thread: str) -> list[Message]:
        """Chat *speech* (kind ``message``) authored by the member.

        Deliberately excludes membership notices (e.g. the bootstrap
        temp-name join notice, kind ``notice``): those are ordinary member
        events, not the driver speaking on the member's behalf. "No
        double-speak" ([SUM-9]/[SUM-6]) is about chat, not notices.
        """

        member = _member_by_name(self.summon_db, name)
        if member is None:
            return []
        try:
            log = TautClient(db_path=self.summon_db).log(thread)
        except Exception:  # noqa: BLE001 - transient during teardown
            return []
        return [m for m in log if m.from_id == member.member_id and m.kind == "message"]

    # -- control ([SUM-9]) ----------------------------------------------------

    def control(self, name: str, command: str) -> dict[str, Any] | None:
        member = _member_by_name(self.summon_db, name)
        assert member is not None, f"no member named {name}"
        return _await_control_request(self.summon_db, member.member_id, command)

    def stop_via_cli(self, name: str) -> tuple[int, str, str]:
        return summon_cli("stop", name, db=self.summon_db, cwd=self.tmp_path)


# --- harness factories: the parameterization axis ----------------------------


def _scripted_harness(
    summon_db: Path,
    tmp_path: Path,
    driver_factory: Callable[..., DriverProcess],
) -> ConformanceHarness:
    return ConformanceHarness(
        provider="scripted",
        summon_db=summon_db,
        tmp_path=tmp_path,
        driver_factory=driver_factory,
        supports_scenarios=True,
        has_received_log=True,
    )


HARNESS_FACTORIES = [
    pytest.param(_scripted_harness, id="scripted"),
]


@pytest.fixture(params=HARNESS_FACTORIES)
def harness(
    request: pytest.FixtureRequest,
    summon_db: Path,
    tmp_path: Path,
    driver_factory: Callable[..., DriverProcess],
) -> ConformanceHarness:
    factory: Callable[..., ConformanceHarness] = request.param
    return factory(summon_db, tmp_path, driver_factory)


# --- item 6: injection format stability (provider-agnostic unit) -------------


def test_injection_format_is_stable() -> None:
    """[SUM-5.2] injection format is a frozen contract personas program on.

    Provider-agnostic and adapter-free: the rendering helper is one shared
    seam ([SUM-5.2]), so a golden here pins the exact bytes every adapter and
    every persona depends on, independent of any harness.
    """

    channel = Message(
        thread="general",
        ts=1837000000000000024,
        from_id="m_x",
        from_name="van",
        kind="message",
        text="anyone awake?",
    )
    assert format_injection(channel) == "[#general] van: anyone awake?"

    dm = Message(
        thread="dm.d_abcdefghijklmnopqrstuvwxyz",
        ts=1,
        from_id="m_x",
        from_name="bob",
        kind="message",
        text="can you look at the parser branch?",
    )
    assert format_injection(dm) == "[dm] bob: can you look at the parser branch?"

    notice = Message(
        thread="general",
        ts=1,
        from_id="m_x",
        from_name="claude",
        kind="notice",
        text="claude joined",
    )
    assert format_injection(notice) == "[#general] · claude joined"

    mention = Notification(
        type="mention",
        to_id="m_y",
        actor_id="m_x",
        actor_name="van",
        thread="ops",
        message_ts=1837000000000000024,
    )
    assert (
        format_injection(mention)
        == "[notify] mention by van in #ops (message 1837000000000000024)"
    )


# --- item 1: control responsiveness, idle and mid-turn -----------------------


def test_control_responsive_when_idle(harness: ConformanceHarness) -> None:
    """[SUM-9]: the control plane answers while the harness sits idle.

    Capability-free for any real conformance harness factory.
    """

    driver = harness.start("reviewer", "general", control_interval=0.1)
    harness.wait_ready(driver)

    reply = harness.control("reviewer", "PING")
    assert reply is not None
    assert reply.get("status") == "ok"
    assert reply.get("message") == "PONG"

    assert driver.stop() == 0


def test_control_responsive_mid_turn(harness: ConformanceHarness) -> None:
    """[SUM-9]: STATUS answers while the harness is busy mid-turn.

    Needs a scripted busy turn (the harness stops reading stdin while it
    "works"); control stays responsive on its own thread.
    """

    harness.require_scenarios()
    driver = harness.start(
        "reviewer",
        "general",
        "dev",
        scenario={"on_start": [{"sleep": 30}]},
        control_interval=0.1,
    )
    harness.wait_ready(driver)

    reply = harness.control("reviewer", "STATUS")
    assert reply is not None
    assert reply.get("status") == "ok"
    assert reply.get("provider") == harness.provider
    assert reply.get("thread_count") == 2

    assert driver.stop() == 0


# --- item 2: restart with conversation scope intact --------------------------


def test_restart_resumes_stored_session(harness: ConformanceHarness) -> None:
    """[SUM-7.3]/[SUM-11]: a crash resume offers the stored session id back
    and replays the tail missed while the harness was dead ([SUM-5.4])."""

    harness.require_scenarios()
    harness.require_received_log()
    driver = harness.start(
        "scripted", "general", scenario={"session_id": "sess-conf-resume"}
    )
    driver.wait_for_start()
    harness.peer_say("general", "before-crash")
    driver.wait_for_message("before-crash")

    member = harness.member("scripted")
    assert member is not None
    wait_until(
        lambda: (
            (harness.session_row(member.member_id) or {}).get("provider_session_id")
            == "sess-conf-resume"
        ),
        message="stored session id in the ledger",
    )

    if hasattr(signal, "SIGKILL"):
        os.kill(driver.child_pid(), signal.SIGKILL)
    else:
        os.kill(driver.child_pid(), signal.SIGTERM)
    harness.peer_say("general", "after-crash")

    driver.wait_for_start(2)
    assert driver.starts()[1]["session"] == "sess-conf-resume"
    driver.wait_for_message("after-crash", generation=1)
    assert sum("before-crash" in m for m in driver.messages()) == 1

    assert driver.stop() == 0


def test_restart_replays_conversation_tail(harness: ConformanceHarness) -> None:
    """[SUM-5.4]/[SUM-7.3]: a fresh driver (no resumable session) replays
    everything after each stored cursor — the chat history is the durable
    conversation, and the member's own sends are never re-injected."""

    harness.require_scenarios()
    harness.require_received_log()
    first = harness.start("scripted", "general")
    first.wait_for_start()
    harness.peer_say("general", "seen-live")
    first.wait_for_message("seen-live")
    member = harness.member("scripted")
    assert member is not None
    assert first.stop() == 0

    # While down: a peer writes, and the member itself speaks through its
    # token-selected mouth ([SUM-6]).
    token = harness.member_token("scripted")
    harness.peer_say("general", "missed-while-down")
    rc, _out, err = _say_as_member(harness, "general", "self-while-down", token=token)
    assert rc == 0, err

    second = harness.start("scripted", "general")
    second.wait_for_start()
    second.wait_for_message("missed-while-down")

    again = harness.member("scripted")
    assert again is not None
    assert again.member_id == member.member_id

    harness.peer_say("general", "settle-marker")
    second.wait_for_message("settle-marker")
    assert not any("self-while-down" in m for m in second.messages())

    assert second.stop() == 0


# --- item 3: backpressure ----------------------------------------------------


def test_backpressure_surfaces_as_unread(harness: ConformanceHarness) -> None:
    """[SUM-5.4]: a stalled harness makes cursors stop advancing and unread
    accumulate honestly — the member falls behind exactly as a person would;
    the driver buffers nothing beyond the write in flight."""

    harness.require_scenarios()
    harness.require_received_log()
    driver = harness.start(
        "scripted", "general", scenario={"on_start": [{"stall": True}]}
    )
    driver.wait_for_start()

    # A message larger than the pipe buffer blocks the in-flight inject;
    # later messages accumulate as honest unread.
    harness.peer_say("general", "x" * 200_000)
    harness.peer_say("general", "tail-1")
    harness.peer_say("general", "tail-2")

    wait_until(
        lambda: harness.unread("scripted", "general") >= 2,
        message="unread growth under stall",
    )
    # Nothing beyond the write in flight reached the harness.
    assert driver.messages() == []

    assert driver.stop() == 0


# --- item 4: clean shutdown, no double-speak ---------------------------------


def test_clean_shutdown_releases_and_no_double_speak(
    harness: ConformanceHarness,
) -> None:
    """[SUM-9]/[SUM-11]: stop is a clean shutdown — exit 0, ledger driver
    evidence cleared, presence ``gone``, and the driver posted nothing on the
    member's behalf (no double-speak). Capability-free for any real
    conformance harness factory."""

    driver = harness.start("reviewer", "general", control_interval=0.1)
    member = harness.wait_ready(driver)

    rc, out, err = harness.stop_via_cli("reviewer")
    assert rc == 0, err
    assert "stopped 'reviewer'" in out
    assert driver.wait() == 0

    row = harness.session_row(member.member_id)
    assert row is not None
    assert row["driver_pid"] is None
    gone = harness.member("reviewer")
    assert gone is not None
    assert gone.presence == "gone"
    # No double-speak: the driver never speaks as the member ([SUM-6]); a
    # non-terminal, un-prompted run leaves the thread free of member chat
    # (the bootstrap join notice is a membership event, not speech).
    assert harness.speech_by_member("reviewer", "general") == []


# --- item 5: single-driver guard ---------------------------------------------


def test_single_driver_guard_refuses_second(harness: ConformanceHarness) -> None:
    """[SUM-8]: a second summon of a live member is refused — two drivers
    injecting into two harness sessions as one member would double-speak.
    Capability-free for any real conformance harness factory."""

    first = harness.start("reviewer", "general")
    harness.wait_ready(first)

    second = harness.start("reviewer", "general")
    assert second.wait() == 1
    assert "live" in second.stderr_tail()

    # The winner is unharmed.
    assert first.stop() == 0


# --- shared helper -----------------------------------------------------------


def _say_as_member(
    harness: ConformanceHarness, thread: str, text: str, *, token: str
) -> tuple[int, str, str]:
    """The member speaks through its own token-selected mouth ([SUM-6])."""

    return taut_cli(
        "say", thread, text, db=harness.summon_db, cwd=harness.tmp_path, token=token
    )


# --- adversarial probe floor for the new CLI ([SUM-3], probe runbook) ---------
#
# The probe-floor runbook demands the parser and driver fail cleanly on bad
# input: the right exit class, a one-line stderr, and no Python traceback.
# The exit classes themselves are pinned in test_summon_cli.py (no db,
# unknown provider, usage errors) and test_driver.py (dead ledger claim);
# these probes add the *shape* assertions those do not: a single stderr line
# and no traceback leakage.


def _no_traceback(err: str) -> bool:
    return "Traceback (most recent call last)" not in err


def _run_summon(*args: str, cwd: Path, env: dict[str, str]) -> tuple[int, str, str]:
    completed = subprocess.run(
        [sys.executable, "-m", "taut_summon", *args],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60.0,
    )
    return completed.returncode, completed.stdout.strip(), completed.stderr.strip()


def test_probe_no_db_fails_clean(tmp_path: Path) -> None:
    rc, out, err = _run_summon("run", "scripted", cwd=tmp_path, env=_base_env())
    assert rc == 1
    assert out == ""
    assert "No taut database found" in err
    assert _no_traceback(err)
    assert len(err.splitlines()) == 1


def test_probe_unknown_provider_fails_clean(tmp_path: Path) -> None:
    rc, out, err = _run_summon("run", "zz-unknown", cwd=tmp_path, env=_base_env())
    assert rc == 1
    assert out == ""
    assert "no adapter named 'zz-unknown'" in err
    assert _no_traceback(err)
    assert len(err.splitlines()) == 1


def test_probe_garbage_scenario_file_fails_clean(
    summon_db: Path, tmp_path: Path
) -> None:
    # A malformed scenario makes the scripted provider child fail to start;
    # the driver exhausts its bounded resume budget and exits 1 with a
    # one-line reason on ITS stderr — never a raw traceback ([SUM-11]).
    garbage = tmp_path / "garbage-scenario.json"
    garbage.write_text("{ this is not valid json", encoding="utf-8")
    env = _base_env()
    env["TAUT_SUMMON_SCENARIO"] = str(garbage)
    env["TAUT_SUMMON_RESUME_BACKOFF"] = "0.1,0.1"
    rc, out, err = _run_summon(
        "run", "scripted", "general", "--db", str(summon_db), cwd=tmp_path, env=env
    )
    assert rc == 1
    assert out == ""
    assert "giving up" in err
    assert _no_traceback(err)
