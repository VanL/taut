"""Real POSIX process-domain invariants for [SUM-7.1]."""

from __future__ import annotations

import errno
import os
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from typing import Any, cast

import pytest
import taut_summon._process_domain_posix as process_domain_module
from taut_summon._adapter import AdapterError
from taut_summon._process_domain_posix import PosixProcessDomain, spawn_process

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
