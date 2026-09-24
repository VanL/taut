"""Real POSIX process-domain invariants for [SUM-7.1]."""

from __future__ import annotations

import errno
import json
import os
import select
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import pytest
import taut_summon._process_domain_posix as process_domain_module
import taut_summon._pty_posix as pty_posix_module
from taut_summon._adapter import AdapterError, ExitEvent
from taut_summon._process_domain_posix import PosixProcessDomain, spawn_process
from taut_summon._pty import PtyAdapter, PtySpec

from taut.identity import capture_process

pytestmark = [
    pytest.mark.posix_only,
    pytest.mark.sqlite_only,
    pytest.mark.xdist_group("process"),
]


class _FakeProcess:
    def __init__(
        self,
        *,
        pid: int = 4312,
        returncode: int = 7,
        wait_error: BaseException | None = None,
    ) -> None:
        self.pid = pid
        self.returncode: int | None = None
        self._wait_returncode = returncode
        self._wait_error = wait_error
        self.wait_calls: list[float | None] = []

    def wait(self, timeout: float | None = None) -> int:
        self.wait_calls.append(timeout)
        if self._wait_error is not None:
            raise self._wait_error
        self.returncode = self._wait_returncode
        return self._wait_returncode


def _domain_for_fake(proc: _FakeProcess) -> PosixProcessDomain:
    return PosixProcessDomain(cast(subprocess.Popen[Any], proc))


def _eventually_observe(
    observe: Callable[[], tuple[int, int, int] | None],
    *,
    timeout: float = 5.0,
) -> tuple[int, int, int]:
    deadline = time.monotonic() + timeout
    while True:
        result = observe()
        if result is not None:
            return result
        assert time.monotonic() < deadline, "child exit was not observable"
        time.sleep(0.01)


def _fixture_entries(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _open_fds() -> set[int]:
    fd_dir = Path("/dev/fd")
    if not fd_dir.is_dir():
        fd_dir = Path("/proc/self/fd")
    return {int(entry.name) for entry in fd_dir.iterdir() if entry.name.isdigit()}


def _pid_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def _wait_for_pids_to_exit(pids: set[int], *, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while True:
        live = {
            pid
            for pid in pids
            if (
                status := subprocess.run(
                    ["ps", "-o", "stat=", "-p", str(pid)],
                    capture_output=True,
                    text=True,
                    check=False,
                ).stdout.strip()
            )
            and not status.startswith("Z")
        }
        if not live:
            return
        assert time.monotonic() < deadline, f"processes survived PTY hangup: {live}"
        time.sleep(0.01)


def test_posix_wait_until_quiet_holds_unknown_query_through_stall_threshold(
    tmp_path: Path,
) -> None:
    """POSIX exposes unknown terminal queries that ConPTY consumes itself."""

    stall_s = 0.2
    received = tmp_path / "received.jsonl"
    fake_tui = Path(__file__).with_name("fixtures") / "fake_tui.py"
    config = {
        "queries": False,
        "modes": False,
        "unknown_query": "[?15n",
        "unknown_blocks": True,
    }
    handle = PtyAdapter(
        PtySpec(
            name="posix-unknown-query",
            argv=(sys.executable, str(fake_tui)),
            stall_s=stall_s,
            quiet_ms=50,
            max_settle_s=0.5,
        )
    ).spawn(
        system_prompt="unused",
        env={
            "TAUT_FAKE_TUI_CONFIG": json.dumps(config),
            "TAUT_FAKE_TUI_LOG": str(received),
        },
    )
    observed: list[object] = []
    pump = threading.Thread(
        target=lambda: observed.extend(handle.events()), daemon=True
    )
    pump.start()
    try:
        started = time.monotonic()
        handle.wait_until_quiet()
        elapsed = time.monotonic() - started

        assert elapsed >= stall_s * 0.8
        assert handle.status_fields()["awaiting_query"] == "[?15n"
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            if any(
                entry.get("event") == "unknown_reply_window"
                for entry in _fixture_entries(received)
            ):
                break
            time.sleep(0.05)
        else:
            pytest.fail(f"unknown query window missing: {_fixture_entries(received)!r}")
    finally:
        handle.close()
        pump.join(timeout=5.0)

    assert not pump.is_alive()
    assert any(isinstance(event, ExitEvent) for event in observed)


def test_spawn_process_starts_new_session_and_publishes_io() -> None:
    spawned = spawn_process(
        (
            sys.executable,
            "-c",
            "import os; print(os.getpid() == os.getpgrp(), flush=True)",
        ),
        stdout=subprocess.PIPE,
        text=True,
    )
    domain = cast(PosixProcessDomain, spawned.domain)
    try:
        assert spawned.process.pid > 0
        assert spawned.process.stdout is not None
        assert spawned.process.stdout.readline().strip() == "True"
        assert domain.wait_for_leader_exit(5.0) == 0
        assert domain.finalize(graceful_timeout=0.0) == 0
    finally:
        domain.finalize(graceful_timeout=0.0)


def test_stream_spawn_does_not_acquire_a_controlling_terminal() -> None:
    spawned = spawn_process(
        (
            sys.executable,
            "-c",
            (
                "import os; "
                "\ntry: os.open('/dev/tty', os.O_RDWR)"
                "\nexcept OSError: print('no-tty', flush=True)"
                "\nelse: print('unexpected-tty', flush=True)"
            ),
        ),
        stdout=subprocess.PIPE,
        text=True,
    )
    domain = cast(PosixProcessDomain, spawned.domain)
    try:
        assert spawned.process.stdout is not None
        assert spawned.process.stdout.readline().strip() == "no-tty"
        assert domain.wait_for_leader_exit(5.0) == 0
    finally:
        domain.finalize(graceful_timeout=0.0)


def test_spawn_process_can_acquire_borrowed_tty_as_controlling_terminal() -> None:
    master_fd, slave_fd = os.openpty()
    spawned = None
    try:
        spawned = spawn_process(
            (
                sys.executable,
                "-c",
                (
                    "import json, os; tty_fd = os.open('/dev/tty', os.O_RDWR); "
                    "os.close(tty_fd); print(json.dumps({'sid': os.getsid(0), "
                    "'pgrp': os.getpgrp(), 'foreground_pgrp': os.tcgetpgrp(0), "
                    "'opened_dev_tty': True}), flush=True)"
                ),
            ),
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            controlling_terminal=True,
        )
        os.close(slave_fd)
        slave_fd = -1
        ready, _, _ = select.select([master_fd], [], [], 5.0)
        assert ready, "provider did not report its terminal ownership"
        report = json.loads(os.read(master_fd, 4096).decode().strip())
        assert report == {
            "sid": spawned.process.pid,
            "pgrp": spawned.process.pid,
            "foreground_pgrp": spawned.process.pid,
            "opened_dev_tty": True,
        }
        assert spawned.domain.wait_for_leader_exit(5.0) == 0
    finally:
        if slave_fd >= 0:
            os.close(slave_fd)
        if master_fd >= 0:
            os.close(master_fd)
        if spawned is not None:
            cast(PosixProcessDomain, spawned.domain).finalize(graceful_timeout=0.0)


def test_controlling_terminal_setup_failure_is_atomic_and_reaped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created: list[subprocess.Popen[Any]] = []
    real_popen = subprocess.Popen

    def recording_popen(*args: Any, **kwargs: Any) -> subprocess.Popen[Any]:
        proc = real_popen(*args, **kwargs)
        created.append(proc)
        return proc

    monkeypatch.setattr(process_domain_module.subprocess, "Popen", recording_popen)
    before_fds = _open_fds()

    with pytest.raises(AdapterError, match="terminal setup failed"):
        spawn_process(
            (sys.executable, "-c", "raise SystemExit('must not exec')"),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            controlling_terminal=True,
        )

    assert len(created) == 1
    assert created[0].returncode is not None
    assert not _pid_exists(created[0].pid)
    assert _open_fds() == before_fds


def test_exec_trampoline_must_report_ready_before_eof(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        process_domain_module,
        "_CONTROLLING_TERMINAL_TRAMPOLINE",
        "raise SystemExit(91)",
    )
    master_fd, slave_fd = os.openpty()
    try:
        with pytest.raises(AdapterError, match="trampoline exited before readiness"):
            spawn_process(
                (sys.executable, "-c", "raise AssertionError('must not exec')"),
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                controlling_terminal=True,
            )
    finally:
        os.close(master_fd)
        os.close(slave_fd)


def test_pty_spawn_closes_both_fds_when_status_wait_is_interrupted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    close_calls: list[int] = []
    monkeypatch.setattr(pty_posix_module.pty, "openpty", lambda: (40, 41))
    monkeypatch.setattr(pty_posix_module, "_set_winsize", lambda *_args: None)
    monkeypatch.setattr(pty_posix_module, "_set_nonblocking", lambda _fd: None)
    monkeypatch.setattr(
        pty_posix_module,
        "spawn_process",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(KeyboardInterrupt()),
    )
    monkeypatch.setattr(pty_posix_module.os, "close", close_calls.append)

    with pytest.raises(KeyboardInterrupt):
        PtyAdapter(PtySpec(name="interrupted", argv=("provider",))).spawn(
            system_prompt="unused",
            env={},
        )

    assert close_calls == [40, 41]


def test_final_provider_exec_failure_is_atomic_and_reaped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created: list[subprocess.Popen[Any]] = []
    real_popen = subprocess.Popen

    def recording_popen(*args: Any, **kwargs: Any) -> subprocess.Popen[Any]:
        proc = real_popen(*args, **kwargs)
        created.append(proc)
        return proc

    monkeypatch.setattr(process_domain_module.subprocess, "Popen", recording_popen)
    before_fds = _open_fds()
    master_fd, slave_fd = os.openpty()
    try:
        with pytest.raises(AdapterError, match="provider exec failed"):
            spawn_process(
                ("/taut/definitely-not-a-provider",),
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                controlling_terminal=True,
            )
    finally:
        os.close(master_fd)
        os.close(slave_fd)

    assert len(created) == 1
    assert created[0].returncode is not None
    assert not _pid_exists(created[0].pid)
    assert _open_fds() == before_fds


def test_master_holder_death_hangs_up_foreground_provider_tree(tmp_path: Path) -> None:
    fixtures = Path(__file__).with_name("fixtures")
    pid_log = tmp_path / "terminal-tree-pids.jsonl"
    holder = subprocess.Popen(
        [
            sys.executable,
            str(fixtures / "controlling_terminal_holder.py"),
            str(fixtures / "controlling_terminal_tree.py"),
            str(pid_log),
        ],
        stdout=subprocess.PIPE,
        text=True,
    )
    provider_pids: set[int] = set()
    provider_identities: dict[int, tuple[str, int]] = {}
    try:
        assert holder.stdout is not None
        ready, _, _ = select.select([holder.stdout], [], [], 5.0)
        assert ready, "master holder did not publish the provider pid"
        provider_leader = int(holder.stdout.readline())
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            provider_pids = {int(entry["pid"]) for entry in _fixture_entries(pid_log)}
            if len(provider_pids) == 2:
                break
            time.sleep(0.01)
        assert len(provider_pids) == 2
        assert provider_leader in provider_pids
        for pid in provider_pids:
            identity = capture_process(pid)
            assert identity is not None
            assert identity.start_time is not None
            assert identity.pgid is not None
            provider_identities[pid] = (identity.start_time, identity.pgid)

        holder.kill()
        holder.wait(timeout=5.0)
        _wait_for_pids_to_exit(provider_pids)
        provider_identities.clear()
    finally:
        if holder.poll() is None:
            holder.kill()
            holder.wait(timeout=5.0)
        for pid, (start_time, pgid) in provider_identities.items():
            identity = capture_process(pid)
            if (
                identity is None
                or identity.start_time != start_time
                or identity.pgid != pgid
            ):
                continue
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass


def test_escape_domain_descendant_has_no_controlling_terminal(tmp_path: Path) -> None:
    result = tmp_path / "escape-terminal.json"
    probe = Path(__file__).with_name("fixtures") / "escape_terminal_probe.py"
    handle = PtyAdapter(
        PtySpec(name="escape-terminal", argv=(sys.executable, str(probe), str(result)))
    ).spawn(system_prompt="unused", env={})
    observed: list[object] = []
    pump = threading.Thread(
        target=lambda: observed.extend(handle.events()), daemon=True
    )
    pump.start()
    try:
        deadline = time.monotonic() + 5.0
        while not result.exists():
            assert time.monotonic() < deadline, "escape-domain probe did not finish"
            time.sleep(0.01)
        pump.join(timeout=5.0)
        assert not pump.is_alive()
        assert json.loads(result.read_text(encoding="utf-8")) == {
            "opened_dev_tty": False
        }
    finally:
        handle.close()
        pump.join(timeout=5.0)


def test_canonical_terminal_interrupt_delivers_exactly_one_sigint(
    tmp_path: Path,
) -> None:
    interrupt_log = tmp_path / "interrupts.jsonl"
    fixture = Path(__file__).with_name("fixtures") / "terminal_signal_counter.py"
    handle = PtyAdapter(
        PtySpec(
            name="terminal-signal-counter",
            argv=(sys.executable, str(fixture), str(interrupt_log)),
            quiet_ms=20,
            max_settle_s=1.0,
        )
    ).spawn(system_prompt="unused", env={})
    observed: list[object] = []
    pump = threading.Thread(
        target=lambda: observed.extend(handle.events()), daemon=True
    )
    pump.start()
    try:
        deadline = time.monotonic() + 5.0
        while "ready" not in handle.output_tail():
            assert time.monotonic() < deadline, "signal fixture did not become ready"
            time.sleep(0.01)
        handle.interrupt()
        pump.join(timeout=5.0)
        assert not pump.is_alive()
        assert _fixture_entries(interrupt_log) == [{"signal": signal.SIGINT}]
    finally:
        handle.close()
        pump.join(timeout=5.0)


@pytest.mark.skipif(
    sys.platform != "darwin" or hasattr(os, "waitid"),
    reason="direct Darwin libc fallback proof",
)
@pytest.mark.parametrize(
    ("child", "expected_code", "expected_status", "expected_returncode"),
    [
        ("raise SystemExit(7)", 1, 7, 7),
        (
            "import os,signal; os.kill(os.getpid(), signal.SIGTERM)",
            2,
            signal.SIGTERM,
            -signal.SIGTERM,
        ),
    ],
)
def test_darwin_waitid_observes_without_reaping(
    child: str,
    expected_code: int,
    expected_status: int,
    expected_returncode: int,
) -> None:
    """The compatibility ABI preserves terminal status until one real reap."""

    from taut_summon._darwin_wait import observe_exit

    proc = subprocess.Popen([sys.executable, "-c", child])
    try:
        expected = (proc.pid, expected_code, expected_status)
        assert _eventually_observe(lambda: observe_exit(proc.pid)) == expected
        assert observe_exit(proc.pid) == expected
        assert proc.returncode is None
        assert proc.wait(timeout=5.0) == expected_returncode
    finally:
        if proc.returncode is None:
            proc.kill()
            proc.wait(timeout=5.0)


def test_finalize_signals_only_before_the_one_leader_reap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Natural leader exit still runs the pinned ladder, never post-reap."""

    proc = subprocess.Popen(
        [sys.executable, "-c", "raise SystemExit(9)"],
        start_new_session=True,
    )
    domain = PosixProcessDomain(proc)
    real_killpg = os.killpg
    signals: list[int] = []

    def reject_post_reap(pgid: int, sig: int) -> None:
        assert domain._reaped is False, "killpg called after leader reap"
        assert pgid == proc.pid
        signals.append(sig)
        real_killpg(pgid, sig)

    monkeypatch.setattr(os, "killpg", reject_post_reap)
    try:
        assert domain.wait_for_leader_exit(5.0) == 9
        assert proc.returncode is None
        assert domain.finalize(graceful_timeout=0.0) == 9
        assert signals
        count_after_reap = len(signals)
        assert domain.finalize(graceful_timeout=0.0) == 9
        assert len(signals) == count_after_reap
        assert proc.returncode == 9
    finally:
        if proc.returncode is None:
            proc.kill()
            proc.wait(timeout=5.0)


@pytest.mark.skipif(
    not sys.platform.startswith("linux"),
    reason="Linux zombie process-group regression",
)
def test_linux_natural_exit_does_not_require_zero_signal_group_absence() -> None:
    """Linux keeps the unreaped zombie leader visible to killpg(..., 0)."""

    proc = subprocess.Popen(
        [sys.executable, "-c", "raise SystemExit(9)"],
        start_new_session=True,
    )
    domain = PosixProcessDomain(proc)
    try:
        assert domain.wait_for_leader_exit(5.0) == 9
        assert proc.returncode is None
        os.killpg(proc.pid, 0)
        assert (
            domain.finalize(
                graceful_timeout=0.0,
                term_timeout=0.01,
                kill_timeout=1.0,
            )
            == 9
        )
        assert proc.returncode == 9
    finally:
        if proc.returncode is None:
            proc.kill()
            proc.wait(timeout=5.0)


def test_finalize_uses_bounded_signal_stages_without_zero_signal_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unreaped Linux zombie leader must not be mistaken for a live group."""

    proc = _FakeProcess()
    domain = _domain_for_fake(proc)
    signals: list[int] = []
    stages: list[tuple[str, float | int | None]] = []

    monkeypatch.setattr(process_domain_module, "_observe_exit", lambda pid: (1, 7))

    def record_signal(pgid: int, sig: int) -> None:
        assert domain._reaped is False, "killpg called after leader reap"
        assert pgid == proc.pid
        assert sig != 0, "finalization must not use group emptiness as its oracle"
        signals.append(sig)
        stages.append(("signal", sig))

    def record_wait(event: threading.Event, timeout: float | None = None) -> bool:
        del event
        stages.append(("wait", timeout))
        return True

    monkeypatch.setattr(os, "killpg", record_signal)
    monkeypatch.setattr(process_domain_module.threading.Event, "wait", record_wait)

    assert (
        domain.finalize(
            graceful_timeout=0.0,
            term_timeout=0.25,
            kill_timeout=0.0,
        )
        == 7
    )
    assert signals == [signal.SIGTERM, signal.SIGKILL]
    assert stages == [
        ("signal", signal.SIGTERM),
        ("wait", 0.25),
        ("signal", signal.SIGKILL),
    ]
    assert proc.wait_calls == [0.0]

    domain.signal_group(signal.SIGTERM)
    assert signals == [signal.SIGTERM, signal.SIGKILL]


def test_finalize_reaps_terminal_leader_after_term_delivery_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A TERM-stage diagnostic must not strand an already-terminal leader."""

    proc = _FakeProcess()
    domain = _domain_for_fake(proc)
    signals: list[int] = []
    monkeypatch.setattr(process_domain_module, "_observe_exit", lambda pid: (1, 7))

    def fail_term(pgid: int, sig: int) -> None:
        assert domain._reaped is False, "killpg called after leader reap"
        assert pgid == proc.pid
        signals.append(sig)
        if sig == signal.SIGTERM:
            raise OSError(errno.EIO, "TERM delivery failed")

    monkeypatch.setattr(os, "killpg", fail_term)

    with pytest.raises(AdapterError, match="process-group signal 15 failed"):
        domain.finalize(
            graceful_timeout=0.0,
            term_timeout=0.0,
            kill_timeout=0.0,
        )

    assert signals == [signal.SIGTERM, signal.SIGKILL]
    assert proc.wait_calls == [0.0]
    assert domain._reaped is True


def test_finalize_aggregates_signal_errors_and_rethrows_without_reentry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Both signal-stage failures survive the one terminal leader reap."""

    proc = _FakeProcess()
    domain = _domain_for_fake(proc)
    signals: list[int] = []
    monkeypatch.setattr(process_domain_module, "_observe_exit", lambda pid: (1, 7))

    def fail_signal(pgid: int, sig: int) -> None:
        assert domain._reaped is False, "killpg called after leader reap"
        assert pgid == proc.pid
        signals.append(sig)
        raise OSError(errno.EIO, f"signal {sig} failed")

    monkeypatch.setattr(os, "killpg", fail_signal)

    with pytest.raises(AdapterError, match="process-group signal 15 failed") as first:
        domain.finalize(
            graceful_timeout=0.0,
            term_timeout=0.0,
            kill_timeout=0.0,
        )

    assert getattr(first.value, "__notes__", []) == [
        (
            "provider process-domain finalization also failed: "
            "provider process-group signal 9 failed: [Errno 5] signal 9 failed"
        )
    ]
    assert signals == [signal.SIGTERM, signal.SIGKILL]
    assert proc.wait_calls == [0.0]
    assert domain._reaped is True

    with pytest.raises(AdapterError) as repeated:
        domain.finalize(
            graceful_timeout=0.0,
            term_timeout=0.0,
            kill_timeout=0.0,
        )

    assert repeated.value is first.value
    assert signals == [signal.SIGTERM, signal.SIGKILL]
    assert proc.wait_calls == [0.0]


@pytest.mark.parametrize(
    "wait_error",
    [
        OSError(errno.ECHILD, "wait failed"),
        subprocess.TimeoutExpired(("provider",), 0.0),
    ],
)
def test_finalize_rethrows_leader_reap_failure_without_second_wait(
    monkeypatch: pytest.MonkeyPatch,
    wait_error: BaseException,
) -> None:
    """A failed reap attempt is terminal and cannot become success on retry."""

    proc = _FakeProcess(wait_error=wait_error)
    domain = _domain_for_fake(proc)
    signals: list[int] = []
    monkeypatch.setattr(process_domain_module, "_observe_exit", lambda pid: (1, 7))
    monkeypatch.setattr(os, "killpg", lambda pgid, sig: signals.append(sig))

    with pytest.raises(AdapterError, match="provider leader reap failed") as first:
        domain.finalize(
            graceful_timeout=0.0,
            term_timeout=0.0,
            kill_timeout=0.0,
        )

    assert domain._reaped is False
    assert proc.wait_calls == [0.0]
    assert signals == [signal.SIGTERM, signal.SIGKILL]

    with pytest.raises(AdapterError) as repeated:
        domain.finalize(
            graceful_timeout=0.0,
            term_timeout=0.0,
            kill_timeout=0.0,
        )

    assert repeated.value is first.value
    assert proc.wait_calls == [0.0]
    assert signals == [signal.SIGTERM, signal.SIGKILL]


def test_finalize_accepts_esrch_for_each_signal_stage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A vanished group is successful best-effort retirement, not emptiness proof."""

    proc = _FakeProcess()
    domain = _domain_for_fake(proc)
    signals: list[int] = []
    monkeypatch.setattr(process_domain_module, "_observe_exit", lambda pid: (1, 7))

    def no_target(pgid: int, sig: int) -> None:
        signals.append(sig)
        raise ProcessLookupError(errno.ESRCH, "group not found")

    monkeypatch.setattr(os, "killpg", no_target)

    assert (
        domain.finalize(
            graceful_timeout=0.0,
            term_timeout=0.0,
            kill_timeout=0.0,
        )
        == 7
    )
    assert signals == [signal.SIGTERM, signal.SIGKILL]
    assert proc.wait_calls == [0.0]


def test_darwin_eperm_is_accepted_only_after_terminal_observation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Darwin's narrow no-target result depends on cached waitid evidence."""

    terminal_proc = _FakeProcess()
    terminal_domain = _domain_for_fake(terminal_proc)
    monkeypatch.setattr(process_domain_module.sys, "platform", "darwin")
    monkeypatch.setattr(process_domain_module, "_observe_exit", lambda pid: (1, 7))

    def fail_permission(pgid: int, sig: int) -> None:
        assert pgid in (terminal_proc.pid, 4313)
        assert sig in (signal.SIGTERM, signal.SIGKILL)
        raise PermissionError(errno.EPERM, "permission denied")

    monkeypatch.setattr(os, "killpg", fail_permission)

    assert (
        terminal_domain.finalize(
            graceful_timeout=0.0,
            term_timeout=0.0,
            kill_timeout=0.0,
        )
        == 7
    )
    assert terminal_proc.wait_calls == [0.0]

    live_domain = _domain_for_fake(_FakeProcess(pid=4313))
    monkeypatch.setattr(process_domain_module, "_observe_exit", lambda pid: None)

    with pytest.raises(AdapterError, match="process-group signal 15 failed"):
        live_domain.signal_group(signal.SIGTERM)


def test_finalize_stores_terminal_observation_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No terminal waitid evidence means no reap and one stable cleanup error."""

    proc = _FakeProcess()
    domain = _domain_for_fake(proc)
    signals: list[int] = []
    monkeypatch.setattr(process_domain_module, "_observe_exit", lambda pid: None)
    monkeypatch.setattr(os, "killpg", lambda pgid, sig: signals.append(sig))

    with pytest.raises(AdapterError, match="did not exit after SIGKILL") as first:
        domain.finalize(
            graceful_timeout=0.0,
            term_timeout=0.0,
            kill_timeout=0.0,
        )

    assert domain._reaped is False
    assert proc.wait_calls == []
    assert signals == [signal.SIGTERM, signal.SIGKILL]

    with pytest.raises(AdapterError) as repeated:
        domain.finalize(
            graceful_timeout=0.0,
            term_timeout=0.0,
            kill_timeout=0.0,
        )

    assert repeated.value is first.value
    assert proc.wait_calls == []
    assert signals == [signal.SIGTERM, signal.SIGKILL]
