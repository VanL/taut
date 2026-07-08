"""Driver tests: bootstrap, ears, event pump, resume — against real processes.

Contract under test: docs/specs/04-summon.md [SUM-4] (six-step bootstrap,
name/collision rules, re-summon re-anchoring), [SUM-5] (injection format,
self-filter, cursor-as-ledger, backpressure), [SUM-6] (mouth env),
[SUM-7.1] (event pump), [SUM-8] (ledger lifecycle), [SUM-11] (crash and
resume), and [SUM-3] (name/provider resolution shared with the CLI).

Anti-mocking posture ([SUM-12]): every test drives the real
``taut-summon run`` entry point as a foreground subprocess against a real
SQLite taut database; peer writers are real ``taut`` CLI subprocesses;
the harness is the real scripted provider child. What reached the harness
process is asserted through the provider's received-log
(``TAUT_SUMMON_RECEIVED_LOG``), the observable form of [SUM-5.4]'s
process-boundary delivery guarantee.
"""

from __future__ import annotations

import json
import os
import pty
import re
import select
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from conftest import (
    _DEADLINE,
    DriverProcess,
    _base_env,
    _client,
    _control_request,
    _ctl_out_messages,
    _member_by_name,
    _member_token,
    _session_row,
    say,
    summon_cli,
    taut_cli,
    wait_until,
)
from simplebroker import Queue
from taut_summon._driver import format_injection

from taut.client import Message, Notification, TautClient
from taut.identity import capture_process

FAKE_TUI = Path(__file__).with_name("fixtures") / "fake_tui.py"
PROCESS_XDIST_GROUP = pytest.mark.xdist_group("process")
PTY_XDIST_GROUP = PROCESS_XDIST_GROUP
pytestmark = PROCESS_XDIST_GROUP

# The real-process driver harness (DriverProcess), the peer-writer helpers
# (taut_cli/say/summon_cli), the ledger/identity accessors
# (_member_by_name/_session_row/_member_token/_control_request/
# _ctl_out_messages), and the summon_db/driver_factory fixtures all live in
# conftest.py so this file and the portable conformance suite
# (test_conformance.py) share one harness, never a divergent copy ([SUM-12]).


def _fake_pty_env(
    log: Path,
    config: dict[str, Any],
    *,
    stall_s: float = 0.5,
) -> dict[str, str]:
    return {
        "TAUT_SUMMON_PTY_ARGV": json.dumps([sys.executable, str(FAKE_TUI)]),
        "TAUT_SUMMON_PTY_ROWS": "24",
        "TAUT_SUMMON_PTY_COLS": "80",
        "TAUT_SUMMON_PTY_STALL_S": str(stall_s),
        "TAUT_SUMMON_PTY_QUIET_MS": "50",
        "TAUT_SUMMON_PTY_MAX_SETTLE_S": "0.5",
        "TAUT_FAKE_TUI_CONFIG": json.dumps(config),
        "TAUT_FAKE_TUI_LOG": str(log),
    }


def _fake_tui_entries(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _read_pty_until(fd: int, needle: bytes, *, timeout: float = 5.0) -> bytes:
    deadline = time.monotonic() + timeout
    out = b""
    while time.monotonic() < deadline:
        ready, _, _ = select.select([fd], [], [], 0.05)
        if not ready:
            continue
        out += os.read(fd, 4096)
        if needle in out:
            return out
    return out


# --- [SUM-5.2] format golden tests -------------------------------------------


def test_format_channel_message_golden() -> None:
    message = Message(
        thread="general",
        ts=1837000000000000024,
        from_id="m_x",
        from_name="van",
        kind="message",
        text="anyone awake?",
    )
    assert format_injection(message) == "[#general] van: anyone awake?"


def test_format_dm_message_golden() -> None:
    message = Message(
        thread="dm.d_abcdefghijklmnopqrstuvwxyz",
        ts=1,
        from_id="m_x",
        from_name="bob",
        kind="message",
        text="can you look at the parser branch?",
    )
    assert format_injection(message) == "[dm] bob: can you look at the parser branch?"


def test_format_notice_golden() -> None:
    message = Message(
        thread="general",
        ts=1,
        from_id="m_x",
        from_name="claude",
        kind="notice",
        text="claude joined",
    )
    assert format_injection(message) == "[#general] · claude joined"


def test_format_mention_notification_golden() -> None:
    notification = Notification(
        type="mention",
        to_id="m_y",
        actor_id="m_x",
        actor_name="van",
        thread="ops",
        message_ts=1837000000000000024,
    )
    assert (
        format_injection(notification)
        == "[notify] mention by van in #ops (message 1837000000000000024)"
    )


# --- bootstrap and lifecycle --------------------------------------------------


def test_first_summon_creates_agent_member_with_ledger_row(
    summon_db: Path, tmp_path: Path, driver_factory: Callable[..., DriverProcess]
) -> None:
    driver = driver_factory(summon_db, "scripted", "general", "dev")
    driver.wait_for_start()

    wait_until(
        lambda: _member_by_name(summon_db, "scripted") is not None,
        message="summoned member",
    )
    member = _member_by_name(summon_db, "scripted")
    assert member is not None
    assert member.kind == "agent"

    # Presence anchors at the harness child ([SUM-4]): here while it runs.
    wait_until(
        lambda: (
            getattr(_member_by_name(summon_db, "scripted"), "presence", None) == "here"
        ),
        message="presence 'here'",
    )

    # Thread membership is ordinary membership for every requested thread.
    client = _client(summon_db)
    for thread in ("general", "dev"):
        assert any(m.member_id == member.member_id for m in client.who(thread))

    # Durable session row; transient claim gone after bootstrap ([SUM-8]).
    row = _session_row(summon_db, member.member_id)
    assert row is not None
    assert row["provider"] == "scripted"
    assert row["token"]
    assert row["driver_pid"] == driver.proc.pid

    # Mouth env carries the member token and the db path ([SUM-6]).
    start = driver.starts()[0]
    assert start["env_token"] == row["token"]
    assert start["env_db"] == str(summon_db)

    queue = Queue("taut_summon_test_reader", db_path=str(summon_db))
    try:
        from taut_summon._state import get_claim

        assert get_claim(queue, name="scripted", provider="scripted") is None
    finally:
        queue.close()

    # Clean stop releases the driver slot and the child: exit 0, row
    # cleared, presence gone.
    assert driver.stop() == 0
    row = _session_row(summon_db, member.member_id)
    assert row is not None
    assert row["driver_pid"] is None
    member = _member_by_name(summon_db, "scripted")
    assert member is not None
    assert member.presence == "gone"


def test_injection_round_trip_message_and_notice(
    summon_db: Path, tmp_path: Path, driver_factory: Callable[..., DriverProcess]
) -> None:
    driver = driver_factory(summon_db, "scripted", "general")
    driver.wait_for_start()

    say(summon_db, tmp_path, "general", "anyone awake?")
    driver.wait_for_message("[#general] van: anyone awake?")

    # A join notice injects in notice shape ([SUM-5.2]).
    rc, _out, err = taut_cli(
        "join", "general", db=summon_db, cwd=tmp_path, as_name="bob"
    )
    assert rc == 0, err
    driver.wait_for_message("[#general] · bob joined")

    assert driver.stop() == 0


def test_arrival_order_per_thread_and_dm_and_mention(
    summon_db: Path, tmp_path: Path, driver_factory: Callable[..., DriverProcess]
) -> None:
    driver = driver_factory(summon_db, "scripted", "general", "dev")
    driver.wait_for_start()

    say(summon_db, tmp_path, "general", "g-one")
    say(summon_db, tmp_path, "dev", "d-one")
    say(summon_db, tmp_path, "general", "g-two")
    say(summon_db, tmp_path, "@scripted", "psst")
    say(summon_db, tmp_path, "general", "@scripted ping")

    driver.wait_for_message("g-two")
    driver.wait_for_message("[dm] van: psst")
    driver.wait_for_message("@scripted ping")
    wait_until(
        lambda: any(
            re.search(r"\[notify\] mention by van in #general \(message \d+\)", m)
            for m in driver.messages()
        ),
        message=f"mention notification injection; got {driver.messages()!r}",
    )
    # dm_started notification pointer also injects ([SUM-5.1] inbox source).
    wait_until(
        lambda: any(
            re.search(r"\[notify\] dm_started by van in dm \(message \d+\)", m)
            for m in driver.messages()
        ),
        message=f"dm_started notification injection; got {driver.messages()!r}",
    )

    # Queues deliver independently (watcher delivery order — [SUM-5.1]
    # makes no cross-queue timing claim), so the dev queue's message gets
    # its own wait like every other before the log is read.
    driver.wait_for_message("[#dev] van: d-one")

    # Per-thread chronological order ([SUM-5.1]); no cross-thread claim.
    injected = driver.messages()
    general = [m for m in injected if m.startswith("[#general] van:")]
    assert general.index("[#general] van: g-one") < general.index(
        "[#general] van: g-two"
    )
    assert "[#dev] van: d-one" in injected

    assert driver.stop() == 0


def test_resummon_replays_tail_and_filters_own_messages(
    summon_db: Path, tmp_path: Path, driver_factory: Callable[..., DriverProcess]
) -> None:
    driver = driver_factory(summon_db, "scripted", "general", tag="gen-a")
    driver.wait_for_start()
    say(summon_db, tmp_path, "general", "seen-live")
    driver.wait_for_message("seen-live")
    member = _member_by_name(summon_db, "scripted")
    assert member is not None
    assert driver.stop() == 0

    # While no driver runs: a peer writes, and the member itself speaks
    # through its mouth (token-selected CLI, [SUM-6]).
    token = _member_token(summon_db, "scripted")
    say(summon_db, tmp_path, "general", "missed-while-down")
    rc, _out, err = taut_cli(
        "say",
        "general",
        "self-while-down",
        db=summon_db,
        cwd=tmp_path,
        token=token,
    )
    assert rc == 0, err

    # Re-summon by name alone: the session row supplies the provider
    # ([SUM-3] step 2); same member, fresh anchor; the cursor tail
    # replays; the member's own message is never injected ([SUM-5.3]).
    second = driver_factory(summon_db, "scripted", "general", tag="gen-b")
    second.wait_for_start()
    second.wait_for_message("missed-while-down")

    member_again = _member_by_name(summon_db, "scripted")
    assert member_again is not None
    assert member_again.member_id == member.member_id
    wait_until(
        lambda: (
            getattr(_member_by_name(summon_db, "scripted"), "presence", "") == "here"
        ),
        message="fresh anchor presence",
    )
    # Bounded settle, then assert the self-filter held.
    say(summon_db, tmp_path, "general", "settle-marker")
    second.wait_for_message("settle-marker")
    assert not any("self-while-down" in m for m in second.messages())

    assert second.stop() == 0


def test_crash_resume_offers_stored_session_and_replays(
    summon_db: Path, tmp_path: Path, driver_factory: Callable[..., DriverProcess]
) -> None:
    driver = driver_factory(
        summon_db,
        "scripted",
        "general",
        scenario={"session_id": "sess-crash-test"},
    )
    driver.wait_for_start()
    say(summon_db, tmp_path, "general", "m-one")
    driver.wait_for_message("m-one")

    member = _member_by_name(summon_db, "scripted")
    assert member is not None
    wait_until(
        lambda: (
            (_session_row(summon_db, member.member_id) or {}).get("provider_session_id")
            == "sess-crash-test"
        ),
        message="ledger session id",
    )

    # Kill the harness child (crash scenario, [SUM-11]) and write while
    # it is dead.
    os.kill(driver.child_pid(), signal.SIGKILL)
    say(summon_db, tmp_path, "general", "m-two")

    # One resume attempt with the stored session id: the scripted
    # provider records the offered TAUT_SUMMON_SESSION; the missed
    # message replays from the cursor (at-least-once, [SUM-5.4]).
    driver.wait_for_start(2)
    assert driver.starts()[1]["session"] == "sess-crash-test"
    driver.wait_for_message("m-two", generation=1)
    assert sum("m-one" in m for m in driver.messages()) == 1

    assert driver.stop() == 0


def test_repeated_crashes_back_off_and_exit_with_reason(
    summon_db: Path, tmp_path: Path, driver_factory: Callable[..., DriverProcess]
) -> None:
    driver = driver_factory(
        summon_db,
        "scripted",
        "general",
        scenario={"on_start": [{"exit": 9}]},
        backoff="0.1,0.1",
    )
    rc = driver.wait(timeout=_DEADLINE)
    assert rc == 1
    stderr = driver.stderr_tail()
    assert "giving up" in stderr
    # The bounded retry actually ran: one spawn plus one per backoff step.
    assert len(driver.starts()) == 3
    # The driver slot was released on the way out.
    member = _member_by_name(summon_db, "scripted")
    assert member is not None
    row = _session_row(summon_db, member.member_id)
    assert row is not None
    assert row["driver_pid"] is None


def test_event_pump_survives_flood_and_updates_session_ledger(
    summon_db: Path, tmp_path: Path, driver_factory: Callable[..., DriverProcess]
) -> None:
    driver = driver_factory(
        summon_db,
        "scripted",
        "general",
        scenario={
            "session_id": "sess-initial",
            "on_start": [{"flood_activity": 500}, {"session": "sess-updated"}],
        },
    )
    driver.wait_for_start()
    wait_until(
        lambda: _member_by_name(summon_db, "scripted") is not None,
        message="summoned member",
    )
    member = _member_by_name(summon_db, "scripted")
    assert member is not None

    # The pump drained the flood (no stdout deadlock) and the session-id
    # update landed in the ledger ([SUM-7.1]).
    wait_until(
        lambda: (
            (_session_row(summon_db, member.member_id) or {}).get("provider_session_id")
            == "sess-updated"
        ),
        message="session id ledger update",
    )
    # Injection still works after the flood.
    say(summon_db, tmp_path, "general", "post-flood")
    driver.wait_for_message("post-flood")

    assert driver.stop() == 0


def test_terminal_mode_posts_assistant_text_to_single_thread(
    summon_db: Path, tmp_path: Path, driver_factory: Callable[..., DriverProcess]
) -> None:
    driver = driver_factory(
        summon_db,
        "scripted",
        "general",
        extra_args=("--terminal",),
    )
    driver.wait_for_start()

    say(summon_db, tmp_path, "general", "hi")
    driver.wait_for_message("[#general] van: hi")

    def _echo_posted() -> bool:
        try:
            log = _client(summon_db).log("general")
        except Exception:
            return False
        return any(
            m.from_name == "scripted" and m.text == "echo: [#general] van: hi"
            for m in log
        )

    wait_until(_echo_posted, message="terminal-mode assistant post")

    # Anti-loop ([SUM-5.3]/[SUM-6]): the member's own terminal-mode post is
    # never re-injected into the harness. Settle behind a fresh marker, then
    # assert the echoed text never appears in the provider's received log.
    say(summon_db, tmp_path, "general", "settle-marker")
    driver.wait_for_message("settle-marker")
    assert not any("echo:" in m for m in driver.messages())

    assert driver.stop() == 0


@PTY_XDIST_GROUP
def test_pty_terminal_mode_is_disabled_by_capability(
    summon_db: Path, tmp_path: Path, driver_factory: Callable[..., DriverProcess]
) -> None:
    pty_log = tmp_path / "pty-terminal-disabled.jsonl"
    driver = driver_factory(
        summon_db,
        "ptybot",
        "general",
        provider="pty",
        extra_args=("--terminal", "--detach"),
        extra_env=_fake_pty_env(pty_log, {"queries": True, "modes": False}),
        tag="pty-terminal-disabled",
    )
    wait_until(
        lambda: _member_by_name(summon_db, "ptybot") is not None,
        message="pty member",
    )
    member = _member_by_name(summon_db, "ptybot")
    assert member is not None
    wait_until(
        lambda: _session_row(summon_db, member.member_id) is not None,
        message="pty session row",
    )

    assert "not supported by provider 'pty'" in driver.stderr_tail()
    assert driver.stop() == 0


@PTY_XDIST_GROUP
def test_pty_detached_orientation_is_injected_before_chat(
    summon_db: Path, tmp_path: Path, driver_factory: Callable[..., DriverProcess]
) -> None:
    pty_log = tmp_path / "pty-orientation.jsonl"
    driver = driver_factory(
        summon_db,
        "ptybot",
        "general",
        provider="pty",
        extra_args=("--detach",),
        extra_env=_fake_pty_env(pty_log, {"queries": True, "modes": False}),
        tag="pty-orientation",
    )
    wait_until(
        lambda: any(entry["event"] == "input" for entry in _fake_tui_entries(pty_log)),
        message="orientation input",
    )

    say(summon_db, tmp_path, "general", "hello pty")
    wait_until(
        lambda: (
            len(
                [
                    entry
                    for entry in _fake_tui_entries(pty_log)
                    if entry["event"] == "input"
                ]
            )
            >= 2
        ),
        message="chat input after orientation",
    )
    inputs = [
        entry for entry in _fake_tui_entries(pty_log) if entry["event"] == "input"
    ]
    queries = [
        entry for entry in _fake_tui_entries(pty_log) if entry["event"] == "query"
    ]
    assert len(queries) >= 10
    assert all(entry["ok"] for entry in queries)
    assert "You are" in inputs[0]["raw"]
    assert "[#general] van: hello pty" in inputs[-1]["raw"]
    assert driver.stop() == 0


@PTY_XDIST_GROUP
def test_pty_status_reports_awaiting_query(
    summon_db: Path, tmp_path: Path, driver_factory: Callable[..., DriverProcess]
) -> None:
    pty_log = tmp_path / "pty-awaiting-query.jsonl"
    driver = driver_factory(
        summon_db,
        "ptybot",
        "general",
        provider="pty",
        extra_args=("--detach",),
        extra_env=_fake_pty_env(
            pty_log,
            {
                "queries": False,
                "modes": False,
                "unknown_query": "[?15n",
                "unknown_blocks": True,
            },
            stall_s=0.2,
        ),
        control_interval=0.1,
        tag="pty-awaiting-query",
    )
    wait_until(
        lambda: _member_by_name(summon_db, "ptybot") is not None,
        message="pty member",
    )
    member = _member_by_name(summon_db, "ptybot")
    assert member is not None
    wait_until(
        lambda: _session_row(summon_db, member.member_id) is not None,
        message="pty session row",
    )

    def _status_has_query() -> bool:
        try:
            reply = _control_request(summon_db, member.member_id, "STATUS", timeout=5.0)
        except Exception:
            return False
        return reply is not None and reply.get("awaiting_query") == "[?15n"

    wait_until(_status_has_query, timeout=10.0, message="awaiting_query status")
    rc, out, err = summon_cli("status", "ptybot", db=summon_db, cwd=tmp_path)
    assert rc == 0, err
    assert "awaiting_query=[?15n" in out
    assert driver.stop() == 0


@PTY_XDIST_GROUP
def test_pty_detached_pre_pump_failure_reaps_child(
    summon_db: Path, tmp_path: Path, driver_factory: Callable[..., DriverProcess]
) -> None:
    first_log = tmp_path / "pty-prepump-first.jsonl"
    first = driver_factory(
        summon_db,
        "ptybot",
        "general",
        provider="pty",
        extra_args=("--detach",),
        extra_env=_fake_pty_env(first_log, {"queries": False, "modes": False}),
        tag="pty-prepump-first",
    )
    wait_until(
        lambda: _member_by_name(summon_db, "ptybot") is not None,
        message="pty member",
    )
    member = _member_by_name(summon_db, "ptybot")
    assert member is not None
    wait_until(
        lambda: _session_row(summon_db, member.member_id) is not None,
        message="pty session row",
    )
    assert first.stop() == 0

    second_log = tmp_path / "pty-prepump-second.jsonl"
    failed = driver_factory(
        summon_db,
        "ptybot",
        "bad.name",
        extra_args=("--detach",),
        extra_env=_fake_pty_env(second_log, {"queries": False, "modes": False}),
        tag="pty-prepump-second",
    )
    assert failed.wait(timeout=30.0) == 1
    starts = [
        entry for entry in _fake_tui_entries(second_log) if entry["event"] == "start"
    ]
    assert starts
    child_pid = int(starts[-1]["pid"])
    wait_until(
        lambda: capture_process(child_pid) is None,
        timeout=10.0,
        message="pre-pump child reaped",
    )


@PTY_XDIST_GROUP
def test_pty_first_run_attaches_until_chord_and_sets_wired(
    summon_db: Path, tmp_path: Path
) -> None:
    pty_log = tmp_path / "pty-attach-driver.jsonl"
    env = _base_env()
    env.update(
        _fake_pty_env(
            pty_log,
            {"queries": False, "modes": False, "redraw": False, "onboarding": True},
        )
    )
    user_master, user_slave = pty.openpty()
    stderr_path = tmp_path / "pty-attach-driver.err"
    stderr_file = open(stderr_path, "w", encoding="utf-8")
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "taut_summon",
            "run",
            "ptybot",
            "general",
            "--provider",
            "pty",
            "--db",
            str(summon_db),
        ],
        cwd=tmp_path,
        env=env,
        stdin=user_slave,
        stdout=user_slave,
        stderr=stderr_file,
        text=False,
    )
    try:
        assert b"Trust this directory" in _read_pty_until(
            user_master, b"Trust this directory"
        )
        os.write(user_master, b"yes\r")
        assert b"ready" in _read_pty_until(user_master, b"ready")
        member = _member_by_name(summon_db, "ptybot")
        assert member is not None
        row = _session_row(summon_db, member.member_id)
        assert row is not None
        assert row["wired"] is False
        assert proc.poll() is None

        # Quiet ready prompt is not a readiness heuristic. Only the chord
        # detaches and marks the pair wired.
        time.sleep(0.3)
        row = _session_row(summon_db, member.member_id)
        assert row is not None
        assert row["wired"] is False

        os.write(user_master, b"\x1c")
        time.sleep(0.1)
        os.write(user_master, b"\x1c")
        assert b"\x1b[?2004l" in _read_pty_until(user_master, b"\x1b[?2004l")
        wait_until(
            lambda: bool(
                (_session_row(summon_db, member.member_id) or {}).get("wired")
            ),
            timeout=10.0,
            message="wired flag after attach detach",
        )
        rc, _out, err = summon_cli("stop", "ptybot", db=summon_db, cwd=tmp_path)
        assert rc == 0, err
        proc.wait(timeout=10.0)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=10.0)
        stderr_file.close()
        os.close(user_master)
        os.close(user_slave)


def test_backpressure_blocked_inject_grows_unread_and_stop_still_works(
    summon_db: Path, tmp_path: Path, driver_factory: Callable[..., DriverProcess]
) -> None:
    driver = driver_factory(
        summon_db,
        "scripted",
        "general",
        scenario={"on_start": [{"stall": True}]},
    )
    driver.wait_for_start()

    # A message larger than the pipe buffer blocks the in-flight inject;
    # later messages accumulate as honest unread ([SUM-5.4]).
    say(summon_db, tmp_path, "general", "x" * 200_000)
    say(summon_db, tmp_path, "general", "tail-1")
    say(summon_db, tmp_path, "general", "tail-2")

    token = _member_token(summon_db, "scripted")

    def _unread() -> int:
        client = TautClient(db_path=summon_db, token=token)
        try:
            threads = client.list_threads(all_threads=True)
        except Exception:
            return -1
        for thread in threads:
            if thread.name == "general":
                return thread.unread_count
        return -1

    wait_until(lambda: _unread() >= 2, message="unread growth under stall")
    # Nothing beyond the write in flight reached the harness: the stalled
    # provider records no message events at all.
    assert driver.messages() == []

    # Stop completes despite the blocked inject: interrupt unblocks it
    # ([SUM-7.1]/[SUM-9] ordering), and the cursor lag survives.
    assert driver.stop() == 0
    assert _unread() >= 2


def test_midrun_join_injects_from_join_cursor(
    summon_db: Path, tmp_path: Path, driver_factory: Callable[..., DriverProcess]
) -> None:
    driver = driver_factory(summon_db, "scripted", "general")
    driver.wait_for_start()
    wait_until(
        lambda: _member_by_name(summon_db, "scripted") is not None,
        message="summoned member",
    )

    rc, _out, err = taut_cli("join", "later", db=summon_db, cwd=tmp_path, as_name="van")
    assert rc == 0, err
    say(summon_db, tmp_path, "later", "before-join")

    # The member itself joins mid-run through its mouth ([SUM-4] thread
    # membership is ordinary membership).
    token = _member_token(summon_db, "scripted")
    rc, _out, err = taut_cli("join", "later", db=summon_db, cwd=tmp_path, token=token)
    assert rc == 0, err

    say(summon_db, tmp_path, "later", "after-join")
    driver.wait_for_message("[#later] van: after-join")
    assert not any("before-join" in m for m in driver.messages())

    assert driver.stop() == 0


# --- concurrency and guards ---------------------------------------------------


def _hold_claim(db: Path, name: str, provider: str) -> subprocess.Popen[bytes]:
    """Plant a live in-flight claim: a real sleeping child is the driver."""

    from taut_summon._state import (
        capture_driver_evidence,
        claim_name,
        ensure_summon_schema,
    )

    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
    pid, start = capture_driver_evidence(child.pid)
    queue = Queue("taut_summon_test_reader", db_path=str(db))
    try:
        ensure_summon_schema(queue)
        claim_name(
            queue,
            name=name,
            provider=provider,
            driver_pid=pid,
            driver_start_time=start,
            claimed_ts=queue.generate_timestamp(),
        )
    finally:
        queue.close()
    return child


def test_step0_claim_collision_refuses_chosen_name(
    summon_db: Path, tmp_path: Path, driver_factory: Callable[..., DriverProcess]
) -> None:
    # A live in-flight claim on a *chosen* name refuses loudly at step 0:
    # nothing exists yet, so refusal is clean ([SUM-4] round-14 rule).
    child = _hold_claim(summon_db, "reviewer", "scripted")
    try:
        driver = driver_factory(
            summon_db, "reviewer", "general", provider="scripted", tag="chosen"
        )
        assert driver.wait() == 1
        assert "in flight" in driver.stderr_tail()
        assert _member_by_name(summon_db, "reviewer") is None
    finally:
        child.kill()
        child.wait()


def test_step0_claim_collision_falls_back_for_implied_name(
    summon_db: Path, tmp_path: Path, driver_factory: Callable[..., DriverProcess]
) -> None:
    # The same collision on an *implied* name retries through the
    # choose_name pool: the user asked for *a* scripted ([SUM-4] step 0).
    child = _hold_claim(summon_db, "scripted", "scripted")
    try:
        driver = driver_factory(summon_db, "scripted", "general", tag="implied")
        # bootstrap=False: the pool fallback means the final member name is
        # not the run argument; the wait below is this test's own barrier.
        driver.wait_for_start(bootstrap=False)
        wait_until(
            lambda: any(
                m.name != "scripted"
                and _session_row(summon_db, m.member_id) is not None
                for m in _client(summon_db).who()
            ),
            message="pool-fallback member with a session row",
        )
        assert _member_by_name(summon_db, "scripted") is None
        assert driver.stop() == 0
    finally:
        child.kill()
        child.wait()


def test_concurrent_implied_summons_never_share_a_member(
    summon_db: Path, tmp_path: Path, driver_factory: Callable[..., DriverProcess]
) -> None:
    # Two implied-name summons race through the claim table ([SUM-4]
    # step 0). Started back-to-back their bootstraps overlap; whichever
    # interleaving wins, the invariant is: two distinct members, or one
    # member plus one clean refusal — never one shared member.
    a = driver_factory(summon_db, "scripted", "general", tag="race-a")
    b = driver_factory(summon_db, "scripted", "general", tag="race-b")

    # Deterministic barrier (no sleep): each racer is "settled" once it has
    # either exited (refused/finished) or written its own session row —
    # attributable by driver_pid, since a pool-fallback winner's member name
    # is unknown. Snapshotting before both settle is the old race the 0.5s
    # sleep papered over.
    def _settled(d: DriverProcess) -> bool:
        if d.proc.poll() is not None:
            return True
        return any(
            (row := _session_row(summon_db, m.member_id)) is not None
            and row["driver_pid"] == d.proc.pid
            for m in _client(summon_db).who()
        )

    wait_until(
        lambda: _settled(a) and _settled(b),
        message="both racers settled (exited or session row written)",
    )

    # Summoned members are exactly the ones holding a session row; the
    # peer writer 'van' is python-anchored and classifies as an agent
    # too, so kind alone cannot identify them.
    summoned = [
        m
        for m in _client(summon_db).who()
        if _session_row(summon_db, m.member_id) is not None
    ]
    live = [d for d in (a, b) if d.proc.poll() is None]
    if len(live) == 2:
        assert len(summoned) == 2
        assert len({m.member_id for m in summoned}) == 2
        assert len({m.name for m in summoned}) == 2
    else:
        # The loser refused cleanly (exit 1), leaving exactly one member.
        assert len(live) == 1
        loser = a if live[0] is b else b
        assert loser.proc.returncode == 1
        assert len(summoned) == 1

    for d in live:
        assert d.stop() == 0


def test_second_summon_of_live_member_is_refused(
    summon_db: Path, tmp_path: Path, driver_factory: Callable[..., DriverProcess]
) -> None:
    driver = driver_factory(
        summon_db, "reviewer", "general", provider="scripted", tag="live"
    )
    driver.wait_for_start()
    wait_until(
        lambda: _member_by_name(summon_db, "reviewer") is not None,
        message="summoned member",
    )

    second = driver_factory(
        summon_db, "reviewer", "general", provider="scripted", tag="second"
    )
    assert second.wait() == 1
    assert "live" in second.stderr_tail()

    # The winner is unharmed: injection still round-trips.
    say(summon_db, tmp_path, "general", "still-alive")
    driver.wait_for_message("still-alive")
    assert driver.stop() == 0


def test_explicit_name_collision_with_foreign_member_refuses(
    summon_db: Path, tmp_path: Path, driver_factory: Callable[..., DriverProcess]
) -> None:
    # 'van' exists and was never summoned: a chosen name must refuse
    # loudly, never adopt ([SUM-4] resolution-time collision rule).
    driver = driver_factory(
        summon_db, "van", "general", provider="scripted", tag="collide"
    )
    assert driver.wait() == 1
    stderr = driver.stderr_tail()
    assert "van" in stderr
    member = _member_by_name(summon_db, "van")
    assert member is not None
    assert member.kind != "agent" or _session_row(summon_db, member.member_id) is None


def test_implied_name_collision_falls_back_through_pool(
    summon_db: Path, tmp_path: Path, driver_factory: Callable[..., DriverProcess]
) -> None:
    # A non-summoned member already holds the implied name: the driver
    # falls back through choose_name with a console note ([SUM-3]/[SUM-4]).
    rc, _out, err = taut_cli(
        "join", "general", db=summon_db, cwd=tmp_path, as_name="scripted"
    )
    assert rc == 0, err
    foreign = _member_by_name(summon_db, "scripted")
    assert foreign is not None

    driver = driver_factory(summon_db, "scripted", "general", tag="fallback")
    # bootstrap=False: the pool fallback means the member's final name is
    # NOT the run argument, so the default name-keyed barrier can never
    # pass; the wait below is this test's own bootstrap barrier.
    driver.wait_for_start(bootstrap=False)
    wait_until(
        lambda: any(
            m.kind == "agent"
            and m.member_id != foreign.member_id
            and _session_row(summon_db, m.member_id) is not None
            for m in _client(summon_db).who()
        ),
        message="fallback member with session row",
    )
    # The foreign member was never adopted.
    assert _session_row(summon_db, foreign.member_id) is None
    fresh = _member_by_name(summon_db, "scripted")
    assert fresh is not None
    assert fresh.member_id == foreign.member_id
    assert driver.stop() == 0


# --- rename discipline (deferred S3 named tests, Deviation Log row 1) ---------


def test_resummon_after_rename_reaches_same_member(
    summon_db: Path, tmp_path: Path, driver_factory: Callable[..., DriverProcess]
) -> None:
    driver = driver_factory(summon_db, "scripted", "general", tag="pre-rename")
    driver.wait_for_start()
    member = None

    def _found() -> bool:
        nonlocal member
        member = _member_by_name(summon_db, "scripted")
        return member is not None

    wait_until(_found, message="summoned member")
    assert member is not None
    token = _member_token(summon_db, "scripted")

    # Rename the summoned member mid-run, like anyone else ([IAN-2.2]).
    rc, _out, err = taut_cli(
        "set", "name", "reviewer", db=summon_db, cwd=tmp_path, token=token
    )
    assert rc == 0, err
    assert driver.stop() == 0

    # Re-summon by the *new* name: current-name -> member_id -> session
    # row -> stored provider; same member ([SUM-8] lookup discipline).
    renamed = driver_factory(summon_db, "reviewer", "general", tag="post-rename")
    renamed.wait_for_start()
    again = _member_by_name(summon_db, "reviewer")
    assert again is not None
    assert again.member_id == member.member_id
    assert renamed.stop() == 0


def test_resummon_by_old_name_creates_fresh_member(
    summon_db: Path, tmp_path: Path, driver_factory: Callable[..., DriverProcess]
) -> None:
    driver = driver_factory(summon_db, "scripted", "general", tag="orig")
    driver.wait_for_start()
    member = None

    def _found() -> bool:
        nonlocal member
        member = _member_by_name(summon_db, "scripted")
        return member is not None

    wait_until(_found, message="summoned member")
    assert member is not None
    token = _member_token(summon_db, "scripted")
    rc, _out, err = taut_cli(
        "set", "name", "reviewer", db=summon_db, cwd=tmp_path, token=token
    )
    assert rc == 0, err
    assert driver.stop() == 0

    # The old name finds no member and no claim: fresh member, never
    # adoption ([SUM-8]).
    fresh = driver_factory(summon_db, "scripted", "general", tag="fresh")
    fresh.wait_for_start()
    wait_until(
        lambda: (
            (_member_by_name(summon_db, "scripted") or member).member_id
            != member.member_id
        ),
        message="fresh member under the old name",
    )
    recreated = _member_by_name(summon_db, "scripted")
    assert recreated is not None
    assert recreated.member_id != member.member_id
    assert fresh.stop() == 0


def test_provider_conflict_with_stored_session_row_errors(
    summon_db: Path, tmp_path: Path, driver_factory: Callable[..., DriverProcess]
) -> None:
    driver = driver_factory(
        summon_db, "reviewer", "general", provider="scripted", tag="stored"
    )
    driver.wait_for_start()
    assert driver.stop() == 0

    # --provider that disagrees with the stored provider is a loud error:
    # members do not switch harnesses implicitly ([SUM-3]).
    conflicted = driver_factory(
        summon_db, "reviewer", "general", provider="claude", tag="conflict"
    )
    assert conflicted.wait() == 1
    assert "scripted" in conflicted.stderr_tail()


# --- S7: persona template and the mouth credential path ([SUM-6], [SUM-10]) ---


def test_default_persona_reaches_provider(
    summon_db: Path, tmp_path: Path, driver_factory: Callable[..., DriverProcess]
) -> None:
    # The [SUM-10] default template is the system prompt handed to the
    # harness, parameterized by the member name.
    driver = driver_factory(summon_db, "scripted", "general", tag="persona")
    driver.wait_for_start()
    prompt = driver.starts()[0]["env_system_prompt"]
    assert "## Your mouth" in prompt
    assert "'scripted'" in prompt
    assert "#general" in prompt
    assert driver.stop() == 0


def test_system_prompt_file_overrides_template(
    summon_db: Path, tmp_path: Path, driver_factory: Callable[..., DriverProcess]
) -> None:
    # --system-prompt-file replaces the template wholesale ([SUM-10]); the
    # override reaches the provider (observable on the start line).
    prompt_file = tmp_path / "prompt.md"
    prompt_file.write_text("CUSTOM SYSTEM PROMPT MARKER", encoding="utf-8")
    driver = driver_factory(
        summon_db,
        "scripted",
        "general",
        extra_args=("--system-prompt-file", str(prompt_file)),
        tag="override",
    )
    driver.wait_for_start()
    start = driver.starts()[0]
    assert start["env_system_prompt"] == "CUSTOM SYSTEM PROMPT MARKER"
    assert driver.stop() == 0


def test_mouth_proof_scripted_runs_taut_say(
    summon_db: Path, tmp_path: Path, driver_factory: Callable[..., DriverProcess]
) -> None:
    # The closest test to the real thing (L1 proof, [SUM-6]/S7): the
    # scripted provider *actually runs* `taut say` as a subprocess using the
    # injected TAUT_TOKEN/TAUT_DB, so the reply appears in the thread posted
    # by the member itself.
    driver = driver_factory(
        summon_db,
        "scripted",
        "general",
        scenario={
            "responses": [
                [{"exec_taut": {"args": ["say", "general", "pong-from-mouth"]}}]
            ]
        },
        tag="mouth",
    )
    driver.wait_for_start()
    say(summon_db, tmp_path, "general", "ping")
    driver.wait_for_message("[#general] van: ping")

    def _posted_by_member() -> bool:
        try:
            log = _client(summon_db).log("general")
        except Exception:
            return False
        return any(
            m.from_name == "scripted" and m.text == "pong-from-mouth" for m in log
        )

    wait_until(_posted_by_member, message="mouth-posted reply from the member")
    assert driver.stop() == 0


# --- carry-in: repeated failed injects never poison-advance the cursor --------


def test_repeated_failed_injects_do_not_advance_cursor(
    summon_db: Path, tmp_path: Path, driver_factory: Callable[..., DriverProcess]
) -> None:
    # The provider closes its stdin fd every generation, so a large inject
    # fails with a broken pipe (the child stays alive — this is the
    # inject-failure halt path, not a harness exit). The halt stops the
    # watcher directly, so [TAUT-8.4]'s 3-strikes poison advance can never
    # fire; the cursor stays put and a later driver re-sees the message
    # ([SUM-5.4]).
    marker = "must-survive-" + "x" * 200_000  # larger than the pipe buffer
    wedged = driver_factory(
        summon_db,
        "scripted",
        "general",
        scenario={"on_start": [{"close_stdin": True}]},
        backoff="0.1,0.1",
        tag="wedged",
    )
    wedged.wait_for_start()
    say(summon_db, tmp_path, "general", marker)

    # It never delivers the message: it exhausts its resume budget on
    # repeated inject failures and gives up.
    assert wedged.wait() == 1
    assert "giving up" in wedged.stderr_tail()
    assert not any("must-survive" in m for m in wedged.messages())

    # A fresh, echoing driver replays it from the intact cursor.
    recover = driver_factory(summon_db, "scripted", "general", tag="recover")
    recover.wait_for_start()
    recover.wait_for_message("must-survive-")
    assert recover.stop() == 0


# --- carry-in: post-claim fatal error releases the driver slot ----------------


def test_post_claim_fatal_error_releases_ledger(
    summon_db: Path, tmp_path: Path, driver_factory: Callable[..., DriverProcess]
) -> None:
    # A fatal error after the session row is claimed (an unreadable
    # --system-prompt-file, raised in _supervise before spawn) must leave NO
    # live driver evidence on the ledger row — the centralized, ownership-
    # checked release in the supervisor's finally ([SUM-8] cleanup).
    driver = driver_factory(
        summon_db,
        "scripted",
        "general",
        extra_args=("--system-prompt-file", str(tmp_path / "does-not-exist.md")),
        tag="badprompt",
    )
    assert driver.wait() == 1
    assert "system-prompt-file" in driver.stderr_tail()

    member = _member_by_name(summon_db, "scripted")
    assert member is not None  # bootstrap created the member before the fatal read
    row = _session_row(summon_db, member.member_id)
    assert row is not None
    assert row["driver_pid"] is None


# --- S8: control plane ([SUM-9]) and the rate backstop ([SUM-10]) -------------


def test_stop_from_another_terminal(
    summon_db: Path, tmp_path: Path, driver_factory: Callable[..., DriverProcess]
) -> None:
    driver = driver_factory(
        summon_db,
        "reviewer",
        "general",
        provider="scripted",
        control_interval=0.1,
        tag="stoppable",
    )
    driver.wait_for_start()
    member = _member_by_name(summon_db, "reviewer")
    assert member is not None

    # A control STOP from a second terminal: clean shutdown, correlated ack,
    # exit 0, ledger released ([SUM-9]).
    rc, out, err = summon_cli("stop", "reviewer", db=summon_db, cwd=tmp_path)
    assert rc == 0, err
    assert "stopped 'reviewer'" in out

    assert driver.wait() == 0
    row = _session_row(summon_db, member.member_id)
    assert row is not None
    assert row["driver_pid"] is None
    # The correlated STOP ack was delivered to the client's per-request
    # reply queue (proven by rc==0 + "stopped" above) — NOT to the shared
    # base rsp queue, so concurrent clients never cross replies ([SUM-9]).
    base_acks = [
        m
        for m in _ctl_out_messages(summon_db, member.member_id)
        if m.get("command") == "STOP"
    ]
    assert base_acks == []


def test_stop_by_current_name_after_rename(
    summon_db: Path, tmp_path: Path, driver_factory: Callable[..., DriverProcess]
) -> None:
    # Deviation-Log row 1 (deferred from S3): names never key durable state
    # ([SUM-8]). After a mid-run rename, `stop` resolves the *current* name
    # through core to the member_id and reaches the same session row.
    driver = driver_factory(
        summon_db, "scripted", "general", control_interval=0.1, tag="rename-stop"
    )
    driver.wait_for_start()
    member = _member_by_name(summon_db, "scripted")
    assert member is not None
    token = _member_token(summon_db, "scripted")

    rc, _out, err = taut_cli(
        "set", "name", "reviewer", db=summon_db, cwd=tmp_path, token=token
    )
    assert rc == 0, err

    # Stopping by the OLD name finds no member: nothing summoned (exit 2).
    rc, _out, err = summon_cli("stop", "scripted", db=summon_db, cwd=tmp_path)
    assert rc == 2
    assert "nothing summoned as 'scripted'" in err

    # Stopping by the CURRENT name reaches the same member and stops it.
    rc, out, err = summon_cli("stop", "reviewer", db=summon_db, cwd=tmp_path)
    assert rc == 0, err
    assert "stopped 'reviewer'" in out
    assert driver.wait() == 0
    row = _session_row(summon_db, member.member_id)
    assert row is not None
    assert row["driver_pid"] is None


def test_status_reports_live_driver_fields(
    summon_db: Path, tmp_path: Path, driver_factory: Callable[..., DriverProcess]
) -> None:
    driver = driver_factory(
        summon_db,
        "reviewer",
        "general",
        "dev",
        provider="scripted",
        control_interval=0.1,
        tag="statusable",
    )
    driver.wait_for_start()

    rc, out, err = summon_cli("status", "reviewer", db=summon_db, cwd=tmp_path)
    assert rc == 0, err
    # [SUM-9] STATUS fields: provider, driver liveness, session id, thread
    # count, cursor-lag summary.
    assert "reviewer" in out
    assert "provider=scripted" in out
    assert "driver=alive" in out
    assert "session=" in out
    assert "threads=2" in out
    assert "lag=" in out
    assert driver.stop() == 0


def test_concurrent_status_clients_each_get_their_own_reply(
    summon_db: Path, tmp_path: Path, driver_factory: Callable[..., DriverProcess]
) -> None:
    # [SUM-9] "usable from any terminal": per-request reply queues mean two
    # simultaneous STATUS clients never consume each other's reply. With a
    # shared reply queue this raced and both could time out.
    driver = driver_factory(
        summon_db,
        "reviewer",
        "general",
        provider="scripted",
        control_interval=0.1,
        tag="concurrent",
    )
    driver.wait_for_start()
    member = _member_by_name(summon_db, "reviewer")
    assert member is not None

    replies: dict[int, dict[str, Any] | None] = {}

    def _ask(slot: int) -> None:
        replies[slot] = _control_request(
            summon_db, member.member_id, "STATUS", timeout=40.0
        )

    # Two simultaneous clients is enough to prove reply isolation ([SUM-9]):
    # on the old shared reply queue they consumed each other and both timed
    # out; per-request queues give each its own answer.
    threads = [threading.Thread(target=_ask, args=(i,)) for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=45.0)
        assert not t.is_alive()

    assert len(replies) == 2
    for reply in replies.values():
        assert reply is not None
        assert reply["command"] == "STATUS"
        assert reply["status"] == "ok"
    assert driver.stop() == 0


def test_dismiss_leaves_no_unclaimed_control_rows(
    summon_db: Path, tmp_path: Path, driver_factory: Callable[..., DriverProcess]
) -> None:
    # Lifecycle hygiene: control messages must not accumulate as unclaimed
    # rows in the member's durable sys.* namespace (auto-vacuum reclaims
    # only *claimed* rows). Per-request reply queues are client-deleted; the
    # driver reaps ctl_in and the shared rsp queue on shutdown. After a
    # full summon → several STATUS round-trips → dismiss, nothing pending
    # remains in either control queue.
    from taut_summon._control import control_in_queue_name, control_out_queue_name

    driver = driver_factory(
        summon_db,
        "reviewer",
        "general",
        provider="scripted",
        control_interval=0.1,
        tag="reap",
    )
    driver.wait_for_start()
    member = _member_by_name(summon_db, "reviewer")
    assert member is not None

    for _ in range(3):
        reply = _control_request(summon_db, member.member_id, "STATUS")
        assert reply is not None and reply["status"] == "ok"

    assert driver.stop() == 0

    def _pending(name: str) -> bool:
        queue = Queue(name, db_path=str(summon_db))
        try:
            return queue.has_pending()
        finally:
            queue.close()

    # ctl_in and the shared rsp queue are empty of pending (unclaimed) rows.
    assert not _pending(control_in_queue_name(member.member_id))
    assert not _pending(control_out_queue_name(member.member_id))


def test_status_absent_member_exits_2(summon_db: Path, tmp_path: Path) -> None:
    rc, out, err = summon_cli("status", "ghost", db=summon_db, cwd=tmp_path)
    assert rc == 2
    assert "nothing summoned as 'ghost'" in err
    assert out == ""


def test_status_dead_driver_exits_2(
    summon_db: Path, tmp_path: Path, driver_factory: Callable[..., DriverProcess]
) -> None:
    # A session row exists but no live driver: exit 2 (nothing summoned).
    driver = driver_factory(
        summon_db, "reviewer", "general", provider="scripted", tag="dead"
    )
    driver.wait_for_start()
    assert driver.stop() == 0

    rc, _out, err = summon_cli("status", "reviewer", db=summon_db, cwd=tmp_path)
    assert rc == 2
    assert "nothing summoned as 'reviewer'" in err


def test_ping_responds_while_harness_busy(
    summon_db: Path, tmp_path: Path, driver_factory: Callable[..., DriverProcess]
) -> None:
    # The harness is mid-turn (busy, not reading stdin); control stays
    # responsive on its own thread ([SUM-9] idle AND busy conformance).
    driver = driver_factory(
        summon_db,
        "scripted",
        "general",
        scenario={"on_start": [{"sleep": 30}]},
        control_interval=0.1,
        tag="busy",
    )
    driver.wait_for_start()
    member = _member_by_name(summon_db, "scripted")
    assert member is not None

    reply = _control_request(summon_db, member.member_id, "PING")
    assert reply is not None
    assert reply.get("status") == "ok"
    assert reply.get("message") == "PONG"
    assert driver.stop() == 0


def test_malformed_control_body_does_not_crash_loop(
    summon_db: Path, tmp_path: Path, driver_factory: Callable[..., DriverProcess]
) -> None:
    driver = driver_factory(
        summon_db, "scripted", "general", control_interval=0.1, tag="robust"
    )
    driver.wait_for_start()
    member = _member_by_name(summon_db, "scripted")
    assert member is not None

    from taut_summon._control import control_in_queue_name

    queue = Queue(control_in_queue_name(member.member_id), db_path=str(summon_db))
    try:
        queue.write("this is not json at all")
        queue.write('{"command": "BOGUS", "request_id": "b1"}')
    finally:
        queue.close()

    # The loop dropped the garbage and reported the unknown verb, without
    # crashing: a subsequent PING still gets a PONG ([IAN-9] robustness).
    reply = _control_request(summon_db, member.member_id, "PING")
    assert reply is not None
    assert reply.get("message") == "PONG"
    assert driver.stop() == 0


def test_stop_while_inject_blocked_completes(
    summon_db: Path, tmp_path: Path, driver_factory: Callable[..., DriverProcess]
) -> None:
    # The stuck-harness kill proof ([SUM-9]): a control STOP completes even
    # while an inject is blocked on a stalled harness — interrupt unblocks it.
    driver = driver_factory(
        summon_db,
        "scripted",
        "general",
        scenario={"on_start": [{"stall": True}]},
        control_interval=0.1,
        tag="stalled-stop",
    )
    driver.wait_for_start()
    say(summon_db, tmp_path, "general", "x" * 200_000)
    say(summon_db, tmp_path, "general", "more")

    token = _member_token(summon_db, "scripted")

    def _unread() -> int:
        client = TautClient(db_path=summon_db, token=token)
        try:
            threads = client.list_threads(all_threads=True)
        except Exception:
            return -1
        for thread in threads:
            if thread.name == "general":
                return thread.unread_count
        return -1

    wait_until(lambda: _unread() >= 1, message="blocked inject grows unread")

    rc, _out, err = summon_cli("stop", "scripted", db=summon_db, cwd=tmp_path)
    assert rc == 0, err
    assert driver.wait() == 0


def test_rate_backstop_nudges_and_hard_breaches_on_flood(
    summon_db: Path, tmp_path: Path, driver_factory: Callable[..., DriverProcess]
) -> None:
    # The persona's restraint failed: the harness posts in a loop through
    # its mouth. The backstop trips at the configured threshold — soft
    # breach injects a nudge and logs; hard breach interrupts and is
    # surfaced through STATUS + the log, never as chat and never as an
    # unconsumed control message ([SUM-10]).
    driver = driver_factory(
        summon_db,
        "scripted",
        "general",
        scenario={
            "on_start": [
                {"exec_taut": {"args": ["say", "general", "spam"], "count": 8}}
            ]
        },
        extra_args=("--rate-limit", "1"),
        control_interval=0.1,
        tag="flood",
    )
    driver.wait_for_start()
    member = _member_by_name(summon_db, "scripted")
    assert member is not None

    def _hard_breached() -> bool:
        reply = _control_request(summon_db, member.member_id, "STATUS")
        return bool(reply and reply.get("rate_limited") is True)

    wait_until(_hard_breached, message="rate hard-breach surfaced in STATUS")

    status = _control_request(summon_db, member.member_id, "STATUS")
    assert status is not None
    assert status["rate_limited"] is True
    assert status["rate_breaches"] >= 1
    # The soft-breach nudge fired first and was logged by the backstop.
    assert "rate backstop" in driver.stderr_tail()
    # The breach is NOT written as an unconsumed control-queue message.
    assert _ctl_out_messages(summon_db, member.member_id) == []

    driver.stop()
