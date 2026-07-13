"""Host-interaction contract tests ([SUM-7.4], [SUM-13])."""

from __future__ import annotations

import dataclasses
import inspect
import json
import os
import select
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from pathlib import Path
from typing import Any

import pytest
from conftest import _member_by_name, _session_row, wait_until

pytestmark = pytest.mark.sqlite_only


class _TTYStream:
    def __init__(self, *, is_tty: bool) -> None:
        self._is_tty = is_tty

    def isatty(self) -> bool:
        return self._is_tty


class _PtyHostInteraction:
    """Deterministic rich host that owns real non-default terminal fds."""

    def __init__(self, *, input_fd: int, output_fd: int) -> None:
        self._lease = (input_fd, output_fd)
        self.availability_calls: list[Any] = []
        self.lease_events: list[str] = []

    def terminal_availability(self, intent: Any) -> Any:
        from taut_summon import TerminalAvailability

        self.availability_calls.append(intent)
        return TerminalAvailability.AVAILABLE

    @contextmanager
    def terminal_lease(self) -> Iterator[Any]:
        from taut_summon import TerminalLease

        self.lease_events.append("enter")
        try:
            yield TerminalLease(input_fd=self._lease[0], output_fd=self._lease[1])
        finally:
            self.lease_events.append("exit")


class _GatedPtyHostInteraction(_PtyHostInteraction):
    """Hold the pre-spawn availability return until the test arms a phase."""

    def __init__(self, *, input_fd: int, output_fd: int) -> None:
        super().__init__(input_fd=input_fd, output_fd=output_fd)
        self.availability_entered = threading.Event()
        self.allow_availability = threading.Event()

    def terminal_availability(self, intent: Any) -> Any:
        availability = super().terminal_availability(intent)
        self.availability_entered.set()
        if not self.allow_availability.wait(timeout=10.0):
            raise RuntimeError("test did not release terminal availability")
        return availability


def _read_pty_until(fd: int, needle: bytes, *, timeout: float = 10.0) -> bytes:
    deadline = time.monotonic() + timeout
    output = b""
    while time.monotonic() < deadline:
        ready, _, _ = select.select([fd], [], [], 0.05)
        if not ready:
            continue
        output += os.read(fd, 4096)
        if needle in output:
            return output
    return output


def _start_foreground_run(
    *, db: Path, request: Any, interaction: _PtyHostInteraction
) -> tuple[threading.Thread, list[BaseException]]:
    from taut_summon import SummonController

    failures: list[BaseException] = []

    def run() -> None:
        try:
            SummonController(db_path=db).run_foreground(request, interaction)
        except BaseException as exc:  # noqa: BLE001 - relayed to the test thread
            failures.append(exc)

    thread = threading.Thread(target=run, daemon=True, name="rich-host-summon")
    thread.start()
    return thread, failures


def _configure_fake_pty(monkeypatch: pytest.MonkeyPatch, *, tmp_path: Path) -> None:
    fake_tui = Path(__file__).with_name("fixtures") / "fake_tui.py"
    monkeypatch.setenv(
        "TAUT_SUMMON_PTY_ARGV", json.dumps([sys.executable, str(fake_tui)])
    )
    monkeypatch.setenv("TAUT_SUMMON_PTY_ROWS", "24")
    monkeypatch.setenv("TAUT_SUMMON_PTY_COLS", "80")
    monkeypatch.setenv("TAUT_SUMMON_PTY_STALL_S", "0.5")
    monkeypatch.setenv("TAUT_SUMMON_PTY_QUIET_MS", "50")
    monkeypatch.setenv("TAUT_SUMMON_PTY_MAX_SETTLE_S", "1.0")
    monkeypatch.setenv(
        "TAUT_FAKE_TUI_CONFIG",
        json.dumps({"queries": False, "modes": False, "redraw": False}),
    )
    monkeypatch.setenv("TAUT_FAKE_TUI_LOG", str(tmp_path / "host-fake-tui.jsonl"))


def test_public_interaction_models_have_exact_stable_shape() -> None:
    from taut_summon import (
        SummonInteraction,
        TerminalAvailability,
        TerminalIntent,
        TerminalLease,
    )

    assert [(item.name, item.value) for item in TerminalIntent] == [
        ("REQUIRED", "required"),
        ("PREFERRED", "preferred"),
    ]
    assert [(item.name, item.value) for item in TerminalAvailability] == [
        ("AVAILABLE", "available"),
        ("NO_TTY", "no-tty"),
        ("NESTED_HOST", "nested-host"),
        ("UNAVAILABLE", "unavailable"),
    ]
    assert [field.name for field in dataclasses.fields(TerminalLease)] == [
        "input_fd",
        "output_fd",
    ]
    lease = TerminalLease(input_fd=7, output_fd=9)
    with pytest.raises(dataclasses.FrozenInstanceError):
        lease.input_fd = 11  # type: ignore[misc]
    assert not hasattr(lease, "__dict__")
    assert SummonInteraction.__module__ == "taut_summon.interaction"


@pytest.mark.parametrize(
    ("stdin_tty", "stdout_tty", "nested", "expected"),
    [
        (True, True, False, "AVAILABLE"),
        (False, True, False, "NO_TTY"),
        (True, False, False, "AVAILABLE"),
        (True, True, True, "NESTED_HOST"),
        (False, False, True, "NO_TTY"),
    ],
)
def test_shell_interaction_reports_host_terminal_availability(
    monkeypatch: pytest.MonkeyPatch,
    *,
    stdin_tty: bool,
    stdout_tty: bool,
    nested: bool,
    expected: str,
) -> None:
    from taut_summon import (
        ShellSummonInteraction,
        TerminalAvailability,
        TerminalIntent,
    )

    monkeypatch.setattr(sys, "stdin", _TTYStream(is_tty=stdin_tty))
    monkeypatch.setattr(sys, "stdout", _TTYStream(is_tty=stdout_tty))
    if nested:
        monkeypatch.setenv("TAUT_HOST_TUI", "1")
    else:
        monkeypatch.delenv("TAUT_HOST_TUI", raising=False)

    availability = ShellSummonInteraction().terminal_availability(
        TerminalIntent.PREFERRED
    )

    assert availability is TerminalAvailability[expected]


def test_shell_interaction_grants_only_standard_fds_after_available_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from taut_summon import ShellSummonInteraction, TerminalIntent, TerminalLease

    monkeypatch.setattr(sys, "stdin", _TTYStream(is_tty=True))
    monkeypatch.setattr(sys, "stdout", _TTYStream(is_tty=True))
    monkeypatch.delenv("TAUT_HOST_TUI", raising=False)
    interaction = ShellSummonInteraction()

    assert interaction.terminal_availability(TerminalIntent.PREFERRED).value == (
        "available"
    )
    manager = interaction.terminal_lease()

    assert isinstance(manager, AbstractContextManager)
    with manager as lease:
        assert lease == TerminalLease(input_fd=0, output_fd=1)


def test_shell_interaction_refuses_lease_after_unavailable_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from taut_summon import ShellSummonInteraction, TerminalIntent

    monkeypatch.setattr(sys, "stdin", _TTYStream(is_tty=False))
    monkeypatch.setattr(sys, "stdout", _TTYStream(is_tty=True))
    monkeypatch.delenv("TAUT_HOST_TUI", raising=False)
    interaction = ShellSummonInteraction()
    interaction.terminal_availability(TerminalIntent.REQUIRED)

    with pytest.raises(RuntimeError, match="terminal is not available"):
        with interaction.terminal_lease():
            pytest.fail("unavailable shell interaction granted a lease")


def test_interaction_module_has_no_runtime_or_state_dependencies() -> None:
    script = "import json,sys; import taut_summon.interaction; print(json.dumps(sorted(sys.modules)))"
    result = subprocess.run(
        [sys.executable, "-c", script],
        text=True,
        capture_output=True,
        check=False,
        env={**os.environ, "PYTHONPATH": os.pathsep.join(sys.path)},
    )

    assert result.returncode == 0, result.stderr
    imported = set(json.loads(result.stdout))
    assert "taut_summon.interaction" in imported
    assert "taut_summon._adapter" not in imported
    assert "taut_summon._driver" not in imported
    assert "taut_summon._pty" not in imported
    assert "taut_summon._state" not in imported
    assert "taut_summon._control" not in imported


def test_controller_foreground_run_requires_explicit_interaction() -> None:
    from taut_summon import SummonController

    parameters = inspect.signature(SummonController.run_foreground).parameters

    assert list(parameters) == ["self", "request", "interaction"]
    assert parameters["interaction"].default is inspect.Parameter.empty


def test_controller_rejects_attach_and_detach_as_typed_request_error() -> None:
    from taut_summon import (
        ShellSummonInteraction,
        SummonController,
        SummonOperationError,
        SummonRequest,
    )

    with pytest.raises(
        SummonOperationError, match="--attach and --detach cannot be used together"
    ):
        SummonController().run_foreground(
            SummonRequest(
                name="reviewer",
                threads=("general",),
                terminal=False,
                persona=None,
                system_prompt_file=None,
                rate_limit=None,
                attach=True,
                detach=True,
                provider_flag="scripted",
            ),
            ShellSummonInteraction(),
        )


@pytest.mark.xdist_group("process")
@pytest.mark.sqlite_only
def test_rich_host_real_pty_lease_wires_once_then_wired_resume_skips_lease(
    summon_db: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from taut_summon import (
        SummonController,
        SummonRequest,
        TerminalIntent,
    )
    from taut_summon._driver import SummonDriver
    from taut_summon._pty import PtyHandle

    pty = pytest.importorskip("pty", reason="host interaction requires a POSIX PTY")
    _configure_fake_pty(monkeypatch, tmp_path=tmp_path)
    user_master, user_slave = pty.openpty()
    prompt_marker = "orientation-race-probe"
    prompt_path = tmp_path / "orientation-race-prompt.txt"
    prompt_path.write_text(prompt_marker, encoding="utf-8")
    request = SummonRequest(
        name="hosted",
        threads=("general",),
        terminal=False,
        persona=None,
        system_prompt_file=str(prompt_path),
        rate_limit=None,
        provider_flag="pty",
    )
    drivers: list[SummonDriver] = []
    real_driver_init = SummonDriver.__init__

    def observed_driver_init(driver: SummonDriver, *args: Any, **kwargs: Any) -> None:
        real_driver_init(driver, *args, **kwargs)
        drivers.append(driver)

    monkeypatch.setattr(SummonDriver, "__init__", observed_driver_init)
    first = _PtyHostInteraction(input_fd=user_slave, output_fd=user_slave)
    first_thread, first_failures = _start_foreground_run(
        db=summon_db, request=request, interaction=first
    )
    second_thread: threading.Thread | None = None
    stop_thread: threading.Thread | None = None
    allow_orientation_write = threading.Event()
    try:
        assert b"ready" in _read_pty_until(user_master, b"ready")
        os.write(user_master, b"\x1c\x1c")
        assert b"\x1b[?2004l" in _read_pty_until(user_master, b"\x1b[?2004l")

        def first_row_is_wired() -> bool:
            member = _member_by_name(summon_db, "hosted")
            if member is None:
                return False
            row = _session_row(summon_db, member.member_id)
            return bool(row and row["wired"])

        wait_until(first_row_is_wired, message="rich-host wired transition")
        stopped = SummonController(db_path=summon_db).stop("hosted")
        assert stopped.name == "hosted"
        first_thread.join(timeout=10.0)
        assert not first_thread.is_alive()
        assert first_failures == []
        assert first.availability_calls == [TerminalIntent.PREFERRED]
        assert first.lease_events == ["enter", "exit"]

        orientation_write_entered = threading.Event()
        control_interrupt_completed = threading.Event()
        block_orientation_write = threading.Event()
        real_write = os.write
        real_interrupt = PtyHandle.interrupt

        def controlled_write(fd: int, data: bytes) -> int:
            if (
                block_orientation_write.is_set()
                and threading.current_thread().name == "rich-host-summon"
                and prompt_marker.encode() in data
                and not orientation_write_entered.is_set()
            ):
                orientation_write_entered.set()
                if not allow_orientation_write.wait(timeout=10.0):
                    raise RuntimeError("test did not release the orientation write")
            return real_write(fd, data)

        def observed_interrupt(handle: PtyHandle) -> None:
            real_interrupt(handle)
            if (
                block_orientation_write.is_set()
                and threading.current_thread().name == "taut-summon-control"
            ):
                control_interrupt_completed.set()

        monkeypatch.setattr(os, "write", controlled_write)
        monkeypatch.setattr(PtyHandle, "interrupt", observed_interrupt)

        second = _GatedPtyHostInteraction(input_fd=user_slave, output_fd=user_slave)
        second_thread, second_failures = _start_foreground_run(
            db=summon_db, request=request, interaction=second
        )
        assert second.availability_entered.wait(timeout=10.0)
        assert second.availability_calls == [TerminalIntent.PREFERRED]
        block_orientation_write.set()
        second.allow_availability.set()
        assert orientation_write_entered.wait(timeout=10.0)

        stop_failures: list[BaseException] = []

        def stop_second() -> None:
            try:
                SummonController(db_path=summon_db).stop("hosted")
            except BaseException as exc:  # noqa: BLE001 - relayed to test owner
                stop_failures.append(exc)

        stop_thread = threading.Thread(
            target=stop_second,
            daemon=True,
            name="second-stop-client",
        )
        stop_thread.start()
        assert control_interrupt_completed.wait(timeout=10.0)
        allow_orientation_write.set()
        stop_thread.join(timeout=10.0)
        assert not stop_thread.is_alive()
        assert stop_failures == []
        second_thread.join(timeout=10.0)
        assert not second_thread.is_alive()
        assert second_failures == []
        assert second.availability_calls == [TerminalIntent.PREFERRED]
        assert second.lease_events == []
    finally:
        allow_orientation_write.set()
        if "second" in locals():
            second.allow_availability.set()
        for driver in drivers:
            driver.request_stop()
        if stop_thread is not None and stop_thread.is_alive():
            stop_thread.join(timeout=1.0)
        if first_thread.is_alive():
            first_thread.join(timeout=1.0)
        if second_thread is not None and second_thread.is_alive():
            second_thread.join(timeout=1.0)
        os.close(user_master)
        os.close(user_slave)


@pytest.mark.xdist_group("process")
@pytest.mark.sqlite_only
def test_driver_stop_during_rich_host_attach_restores_and_releases_lease(
    summon_db: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from taut_summon import SummonRequest, TerminalIntent
    from taut_summon._driver import SummonDriver

    pty = pytest.importorskip("pty", reason="host interaction requires a POSIX PTY")
    _configure_fake_pty(monkeypatch, tmp_path=tmp_path)
    user_master, user_slave = pty.openpty()
    interaction = _PtyHostInteraction(input_fd=user_slave, output_fd=user_slave)
    driver = SummonDriver(
        SummonRequest(
            name="stopped-host",
            threads=("general",),
            terminal=False,
            persona=None,
            system_prompt_file=None,
            rate_limit=None,
            provider_flag="pty",
        ),
        interaction=interaction,
        db_path=str(summon_db),
        install_signal_handlers=False,
    )
    failures: list[BaseException] = []

    def run() -> None:
        try:
            driver.run()
        except BaseException as exc:  # noqa: BLE001 - relayed to the test thread
            failures.append(exc)

    thread = threading.Thread(target=run, daemon=True, name="stopped-rich-host")
    thread.start()
    try:
        assert b"ready" in _read_pty_until(user_master, b"ready")
        driver.request_stop()
        assert b"\x1b[?2004l" in _read_pty_until(user_master, b"\x1b[?2004l")
        thread.join(timeout=10.0)

        assert not thread.is_alive()
        assert failures == []
        assert interaction.availability_calls == [TerminalIntent.PREFERRED]
        assert interaction.lease_events == ["enter", "exit"]
        member = _member_by_name(summon_db, "stopped-host")
        assert member is not None
        row = _session_row(summon_db, member.member_id)
        assert row is not None
        assert row["driver_pid"] is None
        assert row["wired"] is False
    finally:
        if thread.is_alive():
            driver.request_stop()
            thread.join(timeout=10.0)
        os.close(user_master)
        os.close(user_slave)


@pytest.mark.xdist_group("process")
@pytest.mark.sqlite_only
def test_controller_wraps_invalid_host_fd_failure_as_public_summon_error(
    summon_db: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from taut_summon import SummonController, SummonOperationError, SummonRequest

    _configure_fake_pty(monkeypatch, tmp_path=tmp_path)
    interaction = _PtyHostInteraction(input_fd=-1, output_fd=-1)

    with pytest.raises(SummonOperationError, match="terminal attach failed"):
        SummonController(db_path=summon_db).run_foreground(
            SummonRequest(
                name="invalid-host-fd",
                threads=("general",),
                terminal=False,
                persona=None,
                system_prompt_file=None,
                rate_limit=None,
                provider_flag="pty",
            ),
            interaction,
        )

    assert interaction.lease_events == ["enter", "exit"]
    member = _member_by_name(summon_db, "invalid-host-fd")
    assert member is not None
    row = _session_row(summon_db, member.member_id)
    assert row is not None
    assert row["driver_pid"] is None
    assert row["wired"] is False
