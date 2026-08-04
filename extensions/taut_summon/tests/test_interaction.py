"""Host-interaction contract tests ([SUM-7.4], [SUM-13])."""

from __future__ import annotations

import ast
import dataclasses
import inspect
import json
import os
import select
import signal
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


class _HostAbort(BaseException):
    pass


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

    assert list(parameters) == [
        "self",
        "request",
        "interaction",
        "install_signal_handlers",
    ]
    assert parameters["interaction"].default is inspect.Parameter.empty
    assert parameters["install_signal_handlers"].kind is inspect.Parameter.KEYWORD_ONLY
    assert parameters["install_signal_handlers"].default is False


def test_controller_default_never_inspects_or_installs_signal_handlers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from taut_summon import ShellSummonInteraction, SummonController, SummonRequest
    from taut_summon._driver import SummonDriver

    monkeypatch.setattr(SummonDriver, "_run", lambda _driver: 0)

    def unexpected_signal_access(*_args: object) -> None:
        pytest.fail("rich-host default accessed process signal state")

    monkeypatch.setattr(signal, "getsignal", unexpected_signal_access)
    monkeypatch.setattr(signal, "signal", unexpected_signal_access)

    SummonController().run_foreground(
        SummonRequest(
            name="scripted",
            threads=("general",),
            terminal=False,
            persona=None,
            system_prompt_file=None,
            rate_limit=None,
        ),
        ShellSummonInteraction(),
    )


def test_controller_rejects_worker_thread_signal_opt_in_before_lifecycle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from taut_summon import (
        ShellSummonInteraction,
        SummonController,
        SummonOperationError,
        SummonRequest,
    )
    from taut_summon._driver import SummonDriver

    lifecycle_started = threading.Event()

    def run_driver(_driver: SummonDriver) -> int:
        lifecycle_started.set()
        return 0

    monkeypatch.setattr(SummonDriver, "_run", run_driver)
    failures: list[BaseException] = []

    def run() -> None:
        try:
            SummonController().run_foreground(
                SummonRequest(
                    name="scripted",
                    threads=("general",),
                    terminal=False,
                    persona=None,
                    system_prompt_file=None,
                    rate_limit=None,
                ),
                ShellSummonInteraction(),
                install_signal_handlers=True,
            )
        except BaseException as exc:  # noqa: BLE001 - relayed to test owner
            failures.append(exc)

    thread = threading.Thread(target=run)
    thread.start()
    thread.join(timeout=5.0)

    assert not thread.is_alive()
    assert len(failures) == 1
    assert isinstance(failures[0], SummonOperationError)
    assert "main thread" in str(failures[0])
    assert not lifecycle_started.is_set()


@pytest.mark.parametrize("prior_kind", ["callable", "default", "ignore"])
@pytest.mark.parametrize(
    "exit_kind", ["clean", "translated", "exception", "base-exception"]
)
def test_controller_signal_opt_in_restores_exact_handlers(
    monkeypatch: pytest.MonkeyPatch,
    prior_kind: str,
    exit_kind: str,
) -> None:
    from taut_summon import (
        ShellSummonInteraction,
        SummonController,
        SummonOperationError,
        SummonRequest,
    )
    from taut_summon._driver import DriverError, SummonDriver

    original_sigint = signal.getsignal(signal.SIGINT)
    original_sigterm = signal.getsignal(signal.SIGTERM)

    def prior_sigint(_signum: int, _frame: object) -> None:
        return None

    def prior_sigterm(_signum: int, _frame: object) -> None:
        return None

    prior_sigint_value: Any
    prior_sigterm_value: Any
    if prior_kind == "callable":
        prior_sigint_value = prior_sigint
        prior_sigterm_value = prior_sigterm
    elif prior_kind == "default":
        prior_sigint_value = signal.SIG_DFL
        prior_sigterm_value = signal.SIG_DFL
    else:
        prior_sigint_value = signal.SIG_IGN
        prior_sigterm_value = signal.SIG_IGN

    def run_driver(_driver: SummonDriver) -> int:
        if exit_kind == "translated":
            raise DriverError("driver failure")
        if exit_kind == "exception":
            raise RuntimeError("host failure")
        if exit_kind == "base-exception":
            raise _HostAbort("host abort")
        return 0

    signal.signal(signal.SIGINT, prior_sigint_value)
    signal.signal(signal.SIGTERM, prior_sigterm_value)
    monkeypatch.setattr(SummonDriver, "_run", run_driver)
    try:
        if exit_kind == "clean":
            SummonController().run_foreground(
                SummonRequest(
                    name="scripted",
                    threads=("general",),
                    terminal=False,
                    persona=None,
                    system_prompt_file=None,
                    rate_limit=None,
                ),
                ShellSummonInteraction(),
                install_signal_handlers=True,
            )
        else:
            expected_type: type[BaseException]
            expected_message: str
            if exit_kind == "translated":
                expected_type = SummonOperationError
                expected_message = "driver failure"
            elif exit_kind == "exception":
                expected_type = RuntimeError
                expected_message = "host failure"
            else:
                expected_type = _HostAbort
                expected_message = "host abort"
            with pytest.raises(expected_type, match=expected_message):
                SummonController().run_foreground(
                    SummonRequest(
                        name="scripted",
                        threads=("general",),
                        terminal=False,
                        persona=None,
                        system_prompt_file=None,
                        rate_limit=None,
                    ),
                    ShellSummonInteraction(),
                    install_signal_handlers=True,
                )

        assert signal.getsignal(signal.SIGINT) is prior_sigint_value
        assert signal.getsignal(signal.SIGTERM) is prior_sigterm_value
    finally:
        signal.signal(signal.SIGINT, original_sigint)
        signal.signal(signal.SIGTERM, original_sigterm)


@pytest.mark.parametrize("failure_signum", [signal.SIGINT, signal.SIGTERM])
def test_signal_install_failure_rolls_back_before_lifecycle(
    monkeypatch: pytest.MonkeyPatch,
    failure_signum: int,
) -> None:
    from taut_summon import (
        ShellSummonInteraction,
        SummonController,
        SummonOperationError,
        SummonRequest,
    )
    from taut_summon._driver import SummonDriver

    prior_int = object()
    prior_term = object()
    handlers: dict[int, object] = {
        signal.SIGINT: prior_int,
        signal.SIGTERM: prior_term,
    }
    lifecycle_started = False

    def get_handler(signum: int) -> object:
        return handlers[signum]

    def set_handler(signum: int, handler: object) -> None:
        prior = prior_int if signum == signal.SIGINT else prior_term
        if signum == failure_signum and handler is not prior:
            raise OSError("signal install refused")
        handlers[signum] = handler

    def run_driver(_driver: SummonDriver) -> int:
        nonlocal lifecycle_started
        lifecycle_started = True
        return 0

    monkeypatch.setattr(signal, "getsignal", get_handler)
    monkeypatch.setattr(signal, "signal", set_handler)
    monkeypatch.setattr(SummonDriver, "_run", run_driver)

    with pytest.raises(SummonOperationError, match="signal install refused"):
        SummonController().run_foreground(
            SummonRequest(
                name="scripted",
                threads=("general",),
                terminal=False,
                persona=None,
                system_prompt_file=None,
                rate_limit=None,
            ),
            ShellSummonInteraction(),
            install_signal_handlers=True,
        )

    assert handlers == {signal.SIGINT: prior_int, signal.SIGTERM: prior_term}
    assert lifecycle_started is False


@pytest.mark.parametrize("primary_failure", [False, True])
def test_signal_restore_failure_preserves_primary_failure_precedence(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    primary_failure: bool,
) -> None:
    from taut_summon import (
        ShellSummonInteraction,
        SummonController,
        SummonOperationError,
        SummonRequest,
    )
    from taut_summon._driver import SummonDriver

    prior_int = object()
    prior_term = object()
    handlers: dict[int, object] = {
        signal.SIGINT: prior_int,
        signal.SIGTERM: prior_term,
    }

    def get_handler(signum: int) -> object:
        return handlers[signum]

    def set_handler(signum: int, handler: object) -> None:
        if signum == signal.SIGTERM and handler is prior_term:
            raise OSError("term restore refused")
        handlers[signum] = handler

    def run_driver(_driver: SummonDriver) -> int:
        if primary_failure:
            raise _HostAbort("primary host abort")
        return 0

    monkeypatch.setattr(signal, "getsignal", get_handler)
    monkeypatch.setattr(signal, "signal", set_handler)
    monkeypatch.setattr(SummonDriver, "_run", run_driver)
    caplog.set_level("ERROR", logger="taut_summon.driver")

    def invocation() -> None:
        SummonController().run_foreground(
            SummonRequest(
                name="scripted",
                threads=("general",),
                terminal=False,
                persona=None,
                system_prompt_file=None,
                rate_limit=None,
            ),
            ShellSummonInteraction(),
            install_signal_handlers=True,
        )

    if primary_failure:
        with pytest.raises(_HostAbort, match="primary host abort"):
            invocation()
        assert "could not restore summon signal handlers" in caplog.text
        assert f"prior disposition {prior_term!r}" in caplog.text
    else:
        with pytest.raises(
            SummonOperationError, match="term restore refused"
        ) as caught:
            invocation()
        assert f"prior disposition {prior_term!r}" in str(caught.value)
    assert handlers[signal.SIGINT] is prior_int


def test_controller_foreground_run_preserves_host_identity_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from taut_summon import (
        ShellSummonInteraction,
        SummonController,
        SummonRequest,
    )
    from taut_summon._driver import SummonDriver

    monkeypatch.setenv("TAUT_AS", "Host Persona")
    monkeypatch.setenv("TAUT_TOKEN", "host-token")
    monkeypatch.setattr(SummonDriver, "_run", lambda _driver: 0)
    controller = SummonController()
    request = SummonRequest(
        name="scripted",
        threads=("general",),
        terminal=False,
        persona=None,
        system_prompt_file=None,
        rate_limit=None,
    )

    for expected_as, expected_token in (
        ("Host Persona", "host-token"),
        ("Changed Host", "changed-token"),
    ):
        monkeypatch.setenv("TAUT_AS", expected_as)
        monkeypatch.setenv("TAUT_TOKEN", expected_token)
        controller.run_foreground(request, ShellSummonInteraction())
        assert os.environ["TAUT_AS"] == expected_as
        assert os.environ["TAUT_TOKEN"] == expected_token


def test_controller_foreground_run_preserves_absent_host_identity_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from taut_summon import ShellSummonInteraction, SummonController, SummonRequest
    from taut_summon._driver import SummonDriver

    monkeypatch.delenv("TAUT_AS", raising=False)
    monkeypatch.delenv("TAUT_TOKEN", raising=False)
    monkeypatch.setattr(SummonDriver, "_run", lambda _driver: 0)

    SummonController().run_foreground(
        SummonRequest(
            name="scripted",
            threads=("general",),
            terminal=False,
            persona=None,
            system_prompt_file=None,
            rate_limit=None,
        ),
        ShellSummonInteraction(),
    )

    assert "TAUT_AS" not in os.environ
    assert "TAUT_TOKEN" not in os.environ


def test_rich_host_identity_remains_usable_while_scripted_driver_runs(
    summon_db: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from taut_summon import (
        ShellSummonInteraction,
        SummonController,
        SummonRequest,
    )

    from taut import TautClient

    host_client = TautClient(db_path=summon_db, as_name="HostPersona")
    try:
        host_client.join("general", new=True)
        host_member = host_client.last_created_member
        assert host_member is not None
        assert host_member.token is not None
    finally:
        host_client.close()

    monkeypatch.setenv("TAUT_AS", host_member.name)
    monkeypatch.setenv("TAUT_TOKEN", host_member.token)
    failures: list[BaseException] = []

    def run() -> None:
        try:
            SummonController(db_path=summon_db).run_foreground(
                SummonRequest(
                    name="hosted",
                    threads=("general",),
                    terminal=False,
                    persona=None,
                    system_prompt_file=None,
                    rate_limit=None,
                    provider_flag="scripted",
                ),
                ShellSummonInteraction(),
            )
        except BaseException as exc:  # noqa: BLE001 - relayed to test owner
            failures.append(exc)

    thread = threading.Thread(target=run, daemon=True, name="rich-host-identity")
    thread.start()
    controller = SummonController(db_path=summon_db)
    try:

        def driver_ready_or_failed() -> bool:
            member = _member_by_name(summon_db, "hosted")
            row = None if member is None else _session_row(summon_db, member.member_id)
            return bool(failures or (row is not None and row["driver_pid"] is not None))

        wait_until(driver_ready_or_failed, message="rich-host scripted driver")
        assert failures == []
        assert os.environ["TAUT_AS"] == host_member.name
        assert os.environ["TAUT_TOKEN"] == host_member.token

        ambient_client = TautClient(db_path=summon_db)
        try:
            assert ambient_client.whoami().member_id == host_member.member_id
        finally:
            ambient_client.close()

        with monkeypatch.context() as stop_environment:
            stop_environment.delenv("TAUT_AS")
            stop_environment.delenv("TAUT_TOKEN")
            assert controller.stop("hosted").name == "hosted"
        thread.join(timeout=10.0)
        assert not thread.is_alive()
        assert failures == []
        assert os.environ["TAUT_AS"] == host_member.name
        assert os.environ["TAUT_TOKEN"] == host_member.token
    finally:
        if thread.is_alive():
            try:
                with monkeypatch.context() as stop_environment:
                    stop_environment.delenv("TAUT_AS")
                    stop_environment.delenv("TAUT_TOKEN")
                    controller.stop("hosted")
            except Exception:
                pass
            thread.join(timeout=10.0)


@pytest.mark.parametrize(
    "module_name",
    ("taut_summon._driver", "taut_summon._control"),
)
def test_driver_owned_clients_never_inherit_host_environment_identity(
    module_name: str,
) -> None:
    module = __import__(module_name, fromlist=["unused"])
    tree = ast.parse(inspect.getsource(module))
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "TautClient"
    ]

    assert calls
    for call in calls:
        setting = next(
            (
                keyword.value
                for keyword in call.keywords
                if keyword.arg == "inherit_environment_identity"
            ),
            None,
        )
        assert isinstance(setting, ast.Constant), (
            f"missing setting at line {call.lineno}"
        )
        assert setting.value is False, f"unsafe setting at line {call.lineno}"


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
        control_close_request_completed = threading.Event()
        block_orientation_write = threading.Event()
        real_write = os.write
        real_request_close = PtyHandle.request_close

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

        def observed_request_close(handle: PtyHandle) -> None:
            real_request_close(handle)
            if (
                block_orientation_write.is_set()
                and threading.current_thread().name == "taut-summon-control"
            ):
                control_close_request_completed.set()

        monkeypatch.setattr(os, "write", controlled_write)
        monkeypatch.setattr(PtyHandle, "request_close", observed_request_close)

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
        assert control_close_request_completed.wait(timeout=10.0)
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
