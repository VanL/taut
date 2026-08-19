"""Host-interaction contract tests ([SUM-7.4], [SUM-13])."""

from __future__ import annotations

import ast
import dataclasses
import inspect
import io
import json
import os
import select
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager, suppress
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


class _BlockingReadStream:
    """Real blocking readline boundary with test-owned completion."""

    def __init__(self, *, line: str = "", error: BaseException | None = None) -> None:
        self.line = line
        self.error = error
        self.started = threading.Event()
        self.release = threading.Event()
        self.read_calls = 0

    def readline(self) -> str:
        self.read_calls += 1
        self.started.set()
        if not self.release.wait(timeout=5.0):
            raise RuntimeError("test did not release blocking readline")
        if self.error is not None:
            raise self.error
        return self.line


class _ReleaseHookLock:
    def __init__(self, *, trigger_release: int, trigger: Callable[[], None]) -> None:
        self._lock = threading.Lock()
        self._trigger_release = trigger_release
        self._trigger = trigger
        self.release_count = 0

    def __enter__(self) -> None:
        self._lock.acquire()

    def __exit__(self, *exc: object) -> None:
        del exc
        self.release_count += 1
        self._lock.release()
        if self.release_count == self._trigger_release:
            self._trigger()


class _InterruptingEvent:
    def __init__(self, error: BaseException) -> None:
        self._event = threading.Event()
        self._error = error
        self.wait_calls = 0

    def wait(self, timeout: float | None = None) -> bool:
        self.wait_calls += 1
        if self.wait_calls == 1:
            raise self._error
        return self._event.wait(timeout)

    def is_set(self) -> bool:
        return self._event.is_set()

    def set(self) -> None:
        self._event.set()


class _InterruptingLock:
    def __init__(self, error: BaseException) -> None:
        self._lock = threading.Lock()
        self._error = error
        self.enter_calls = 0

    def __enter__(self) -> None:
        self.enter_calls += 1
        if self.enter_calls == 1:
            raise self._error
        self._lock.acquire()

    def __exit__(self, *exc: object) -> None:
        del exc
        self._lock.release()


class _InterruptingSetEvent:
    def __init__(self, error: BaseException) -> None:
        self._event = threading.Event()
        self._error = error
        self.set_calls = 0

    def wait(self, timeout: float | None = None) -> bool:
        return self._event.wait(timeout)

    def set(self) -> None:
        self.set_calls += 1
        if self.set_calls == 1:
            raise self._error
        self._event.set()


def _set_cancel_after_read_starts(
    stream: _BlockingReadStream, cancel: threading.Event
) -> None:
    if not stream.started.wait(timeout=5.0):
        raise RuntimeError("test reader did not start")
    cancel.set()


class _HostAbort(BaseException):
    pass


class _PtyHostInteraction:
    """Deterministic rich host that owns real non-default terminal fds."""

    def __init__(self, *, input_fd: int, output_fd: int) -> None:
        self._lease = (input_fd, output_fd)
        self.availability_calls: list[Any] = []
        self.confirmation_notices: list[Any] = []
        self.lease_events: list[str] = []

    def terminal_availability(self, intent: Any) -> Any:
        from taut_summon import TerminalAvailability

        self.availability_calls.append(intent)
        return TerminalAvailability.AVAILABLE

    def confirm_terminal_attach(
        self, notice: Any, *, cancel: threading.Event | None = None
    ) -> bool:
        del cancel
        self.confirmation_notices.append(notice)
        return True

    @contextmanager
    def terminal_lease(self) -> Iterator[Any]:
        from taut_summon import TerminalLease

        self.lease_events.append("enter")
        try:
            yield TerminalLease(input_fd=self._lease[0], output_fd=self._lease[1])
        finally:
            self.lease_events.append("exit")

    def supports_setup_recovery(self) -> bool:
        return True


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


class _GatedAttachDecisionInteraction(_PtyHostInteraction):
    """Hold the real foreground run at its pre-spawn attach decision."""

    def __init__(
        self,
        *,
        input_fd: int,
        output_fd: int,
        decision: bool | BaseException,
    ) -> None:
        super().__init__(input_fd=input_fd, output_fd=output_fd)
        self.decision = decision
        self.confirmation_entered = threading.Event()
        self.allow_confirmation = threading.Event()

    def confirm_terminal_attach(
        self, notice: Any, *, cancel: threading.Event | None = None
    ) -> bool:
        self.confirmation_notices.append(notice)
        self.confirmation_entered.set()
        deadline = time.monotonic() + 10.0
        while not self.allow_confirmation.wait(timeout=0.05):
            if cancel is not None and cancel.is_set():
                return False
            if time.monotonic() >= deadline:
                raise RuntimeError("test did not release terminal confirmation")
        if isinstance(self.decision, BaseException):
            raise self.decision
        return self.decision


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
    *,
    db: Path,
    request: Any,
    interaction: _PtyHostInteraction,
    on_ready: Callable[[Any], None] | None = None,
) -> tuple[threading.Thread, list[BaseException]]:
    from taut_summon import SummonController

    failures: list[BaseException] = []

    def run() -> None:
        try:
            SummonController(db_path=db).run_foreground(
                request,
                interaction,
                on_ready=on_ready,
            )
        except BaseException as exc:  # noqa: BLE001 approved [DOM-10.2.1] [RUFF-SUP-070] exception
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
    # modes:True makes the fake provider enable bracketed paste — a
    # confirmed input prompt — so wired detached resumes keep today's
    # inject-after-settle flow under the [SUM-7.4] setup-recovery spec.
    monkeypatch.setenv(
        "TAUT_FAKE_TUI_CONFIG",
        json.dumps({"queries": False, "modes": True, "redraw": False}),
    )
    monkeypatch.setenv("TAUT_FAKE_TUI_LOG", str(tmp_path / "host-fake-tui.jsonl"))


def test_shipped_interactions_declare_setup_recovery_support() -> None:
    from taut_summon.interaction import ShellSummonInteraction

    # [SUM-13]: the shell declares setup-recovery support; structural test
    # hosts in this file mirror the shell so driver proofs can exercise the
    # escalation path over real fds.
    assert ShellSummonInteraction().supports_setup_recovery() is True
    assert (
        _PtyHostInteraction(input_fd=-1, output_fd=-1).supports_setup_recovery() is True
    )


def test_public_interaction_models_have_exact_stable_shape() -> None:
    from taut_summon import (
        SummonInteraction,
        TerminalAttachNotice,
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
    assert [field.name for field in dataclasses.fields(TerminalAttachNotice)] == [
        "member",
        "provider",
        "detach_hint",
    ]
    notice = TerminalAttachNotice(
        member="grok",
        provider="grok",
        detach_hint="Ctrl-\\ Ctrl-\\",
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        notice.member = "other"  # type: ignore[misc]
    lease = TerminalLease(input_fd=7, output_fd=9)
    with pytest.raises(dataclasses.FrozenInstanceError):
        lease.input_fd = 11  # type: ignore[misc]
    assert SummonInteraction.__module__ == "taut_summon.interaction"


def test_shell_interaction_requires_enter_after_explaining_attach(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from taut_summon import ShellSummonInteraction, TerminalAttachNotice

    input_stream = io.StringIO("\n")
    output_stream = io.StringIO()
    monkeypatch.setattr(sys, "stdin", input_stream)
    monkeypatch.setattr(sys, "stderr", output_stream)

    proceeded = ShellSummonInteraction().confirm_terminal_attach(
        TerminalAttachNotice(
            member="grok\x1b]0;member\a",
            provider="grok\x1b[31m",
            detach_hint="Ctrl-\\ Ctrl-\\",
        )
    )

    assert proceeded is True
    rendered = output_stream.getvalue()
    assert "provider setup, not Taut chat" in rendered
    assert "trust, login, model, or equivalent setup" in rendered
    assert "Ctrl-\\ Ctrl-\\" in rendered
    assert "keeps running" in rendered
    assert "another terminal" in rendered
    assert "Press Enter to continue" in rendered
    assert "\x1b" not in rendered
    assert r"\x1b" in rendered


def test_shell_interaction_eof_cancels_attach(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from taut_summon import ShellSummonInteraction, TerminalAttachNotice

    monkeypatch.setattr(sys, "stdin", io.StringIO(""))
    monkeypatch.setattr(sys, "stderr", io.StringIO())

    assert (
        ShellSummonInteraction().confirm_terminal_attach(
            TerminalAttachNotice(
                member="grok",
                provider="grok",
                detach_hint="Ctrl-\\ Ctrl-\\",
            )
        )
        is False
    )


def test_shell_interaction_uses_complete_partial_pipe_line_after_writer_close() -> None:
    from taut_summon import ShellSummonInteraction, TerminalAttachNotice

    read_fd, write_fd = os.pipe()
    os.write(write_fd, b"not-enter")
    os.close(write_fd)
    input_stream = os.fdopen(read_fd, "r", encoding="utf-8")
    try:
        assert (
            ShellSummonInteraction(
                input_stream=input_stream,
                output_stream=io.StringIO(),
            ).confirm_terminal_attach(
                TerminalAttachNotice(
                    member="grok",
                    provider="grok",
                    detach_hint="Ctrl-\\ Ctrl-\\",
                )
            )
            is False
        )
    finally:
        input_stream.close()


def test_shell_interaction_cancel_event_interrupts_pending_acknowledgement() -> None:
    from taut_summon import ShellSummonInteraction, TerminalAttachNotice

    read_fd, write_fd = os.pipe()
    input_stream = os.fdopen(read_fd, "r", encoding="utf-8")
    output_stream = io.StringIO()
    cancel = threading.Event()
    decisions: list[bool] = []
    thread = threading.Thread(
        target=lambda: decisions.append(
            ShellSummonInteraction(
                input_stream=input_stream,
                output_stream=output_stream,
            ).confirm_terminal_attach(
                TerminalAttachNotice(
                    member="grok",
                    provider="grok",
                    detach_hint="Ctrl-\\ Ctrl-\\",
                ),
                cancel=cancel,
            )
        ),
        daemon=True,
    )
    thread.start()
    try:
        wait_until(
            lambda: "Press Enter to continue" in output_stream.getvalue(),
            message="shell acknowledgement prompt",
        )
        cancel.set()
        thread.join(timeout=2.0)
        assert not thread.is_alive()
        assert decisions == [False]
    finally:
        cancel.set()
        os.close(write_fd)
        input_stream.close()


def test_shell_interaction_windows_pipe_uses_owned_reader_not_select(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import taut_summon.interaction as interaction_module
    from taut_summon import ShellSummonInteraction, TerminalAttachNotice

    cancel = threading.Event()
    input_stream = io.StringIO("")
    observed: list[tuple[object, threading.Event]] = []

    def cancelable_readline(stream: object, event: threading.Event) -> str | None:
        observed.append((stream, event))
        return None

    monkeypatch.setattr(interaction_module, "_is_windows", lambda: True)
    monkeypatch.setattr(
        interaction_module, "_windows_cancelable_readline", cancelable_readline
    )
    monkeypatch.setattr(
        interaction_module.select,
        "select",
        lambda *_args: pytest.fail("Windows ordinary handles are not sockets"),
    )

    assert (
        ShellSummonInteraction(
            input_stream=input_stream,
            output_stream=io.StringIO(),
        ).confirm_terminal_attach(
            TerminalAttachNotice(
                member="grok",
                provider="grok",
                detach_hint="Ctrl-\\ Ctrl-\\",
            ),
            cancel=cancel,
        )
        is False
    )
    assert observed == [(input_stream, cancel)]


def test_windows_cancelable_readline_returns_completed_line_and_closes_handle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import taut_summon.interaction as interaction_module

    stream = _BlockingReadStream(line="\n")
    stream.release.set()
    events: list[tuple[str, int]] = []

    def open_thread(native_id: int) -> int:
        events.append(("open", native_id))
        return 41

    def cancel_read(handle: int) -> bool:
        events.append(("cancel", handle))
        return True

    def close_handle(handle: int) -> None:
        assert not any(
            thread.name == "taut-summon-shell-input" and thread.is_alive()
            for thread in threading.enumerate()
        )
        events.append(("close", handle))

    monkeypatch.setattr(
        interaction_module,
        "_open_windows_thread",
        open_thread,
    )
    monkeypatch.setattr(
        interaction_module,
        "_cancel_windows_synchronous_io",
        cancel_read,
    )
    monkeypatch.setattr(
        interaction_module,
        "_close_windows_handle",
        close_handle,
    )

    assert (
        interaction_module._windows_cancelable_readline(stream, threading.Event())
        == "\n"
    )
    assert stream.read_calls == 1
    assert events[0][0] == "open"
    assert events[-1] == ("close", 41)
    assert not any(event == ("cancel", 41) for event in events)


def test_windows_cancelable_readline_terminal_action_is_first_wins() -> None:
    import taut_summon.interaction as interaction_module

    line_first = interaction_module._WindowsReadState()
    assert interaction_module._claim_windows_terminal_action(line_first, "line")
    assert not interaction_module._claim_windows_terminal_action(line_first, "cancel")

    cancel_first = interaction_module._WindowsReadState()
    assert interaction_module._claim_windows_terminal_action(cancel_first, "cancel")
    assert not interaction_module._claim_windows_terminal_action(cancel_first, "line")


def test_windows_cancelable_readline_line_publication_is_atomic_with_ownership(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import taut_summon.interaction as interaction_module

    cancel = threading.Event()
    stream = _BlockingReadStream(line="\n")
    stream.release.set()
    owner = interaction_module._WindowsCancelableReadOwner(stream, cancel)
    lock = _ReleaseHookLock(trigger_release=5, trigger=cancel.set)
    owner._state.lock = lock  # type: ignore[assignment]
    monkeypatch.setattr(interaction_module, "_open_windows_thread", lambda _id: 51)
    monkeypatch.setattr(
        interaction_module,
        "_cancel_windows_synchronous_io",
        lambda _handle: pytest.fail("published line must own the action"),
    )
    monkeypatch.setattr(interaction_module, "_close_windows_handle", lambda _h: None)

    assert owner.run() == "\n"
    assert cancel.is_set()
    assert lock.release_count >= 5


def test_windows_cancelable_readline_cancels_before_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import taut_summon.interaction as interaction_module

    stream = _BlockingReadStream()
    cancel = threading.Event()
    cancel.set()
    closed: list[int] = []
    monkeypatch.setattr(interaction_module, "_open_windows_thread", lambda _id: 42)
    monkeypatch.setattr(
        interaction_module,
        "_cancel_windows_synchronous_io",
        lambda _handle: pytest.fail("no read exists to cancel"),
    )
    monkeypatch.setattr(interaction_module, "_close_windows_handle", closed.append)

    assert interaction_module._windows_cancelable_readline(stream, cancel) is None
    assert stream.read_calls == 0
    assert closed == [42]


def test_windows_cancelable_readline_owns_aborted_read_and_joins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import taut_summon.interaction as interaction_module

    aborted = OSError("operation aborted")
    aborted.winerror = 995  # type: ignore[attr-defined]
    stream = _BlockingReadStream(error=aborted)
    cancel = threading.Event()
    cancel_calls: list[int] = []
    closed: list[int] = []

    def cancel_read(handle: int) -> bool:
        cancel_calls.append(handle)
        stream.release.set()
        return True

    monkeypatch.setattr(interaction_module, "_open_windows_thread", lambda _id: 43)
    monkeypatch.setattr(
        interaction_module, "_cancel_windows_synchronous_io", cancel_read
    )
    monkeypatch.setattr(interaction_module, "_close_windows_handle", closed.append)
    setter = threading.Thread(
        target=_set_cancel_after_read_starts, args=(stream, cancel)
    )
    setter.start()
    try:
        assert interaction_module._windows_cancelable_readline(stream, cancel) is None
    finally:
        setter.join(timeout=5.0)

    assert not setter.is_alive()
    assert cancel_calls == [43]
    assert closed == [43]
    assert not any(
        thread.name == "taut-summon-shell-input" and thread.is_alive()
        for thread in threading.enumerate()
    )


def test_windows_cancelable_readline_owns_cpython_pipe_cancel_translation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import taut_summon.interaction as interaction_module

    translated = OSError(22, "Invalid argument")
    stream = _BlockingReadStream(error=translated)
    cancel = threading.Event()

    def cancel_read(_handle: int) -> bool:
        stream.release.set()
        return True

    monkeypatch.setattr(interaction_module, "_open_windows_thread", lambda _id: 431)
    monkeypatch.setattr(
        interaction_module, "_cancel_windows_synchronous_io", cancel_read
    )
    monkeypatch.setattr(interaction_module, "_close_windows_handle", lambda _h: None)
    setter = threading.Thread(
        target=_set_cancel_after_read_starts, args=(stream, cancel)
    )
    setter.start()
    try:
        assert interaction_module._windows_cancelable_readline(stream, cancel) is None
    finally:
        setter.join(timeout=5.0)

    assert not setter.is_alive()


def test_windows_cancelable_readline_does_not_swallow_unowned_abort(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import taut_summon.interaction as interaction_module

    aborted = OSError("operation aborted")
    aborted.winerror = 995  # type: ignore[attr-defined]
    stream = _BlockingReadStream(error=aborted)
    stream.release.set()
    monkeypatch.setattr(interaction_module, "_open_windows_thread", lambda _id: 44)
    monkeypatch.setattr(
        interaction_module,
        "_cancel_windows_synchronous_io",
        lambda _handle: pytest.fail("completed read must win"),
    )
    monkeypatch.setattr(interaction_module, "_close_windows_handle", lambda _h: None)

    with pytest.raises(OSError, match="operation aborted"):
        interaction_module._windows_cancelable_readline(stream, threading.Event())


def test_windows_cancelable_readline_does_not_swallow_unowned_invalid_argument(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import taut_summon.interaction as interaction_module

    translated = OSError(22, "Invalid argument")
    stream = _BlockingReadStream(error=translated)
    stream.release.set()
    monkeypatch.setattr(interaction_module, "_open_windows_thread", lambda _id: 441)
    monkeypatch.setattr(
        interaction_module,
        "_cancel_windows_synchronous_io",
        lambda _handle: pytest.fail("completed read must win"),
    )
    monkeypatch.setattr(interaction_module, "_close_windows_handle", lambda _h: None)

    with pytest.raises(OSError, match="Invalid argument"):
        interaction_module._windows_cancelable_readline(stream, threading.Event())


def test_windows_cancelable_readline_requires_token_for_invalid_argument(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import taut_summon.interaction as interaction_module

    translated = OSError(22, "Invalid argument")
    stream = _BlockingReadStream(error=translated)
    cancel = threading.Event()

    def missed_cancel(_handle: int) -> bool:
        stream.release.set()
        return False

    monkeypatch.setattr(interaction_module, "_open_windows_thread", lambda _id: 442)
    monkeypatch.setattr(
        interaction_module, "_cancel_windows_synchronous_io", missed_cancel
    )
    monkeypatch.setattr(interaction_module, "_close_windows_handle", lambda _h: None)
    setter = threading.Thread(
        target=_set_cancel_after_read_starts, args=(stream, cancel)
    )
    setter.start()
    try:
        with pytest.raises(OSError, match="Invalid argument"):
            interaction_module._windows_cancelable_readline(stream, cancel)
    finally:
        setter.join(timeout=5.0)

    assert not setter.is_alive()


def test_windows_cancelable_readline_retries_read_entry_race(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import taut_summon.interaction as interaction_module

    aborted = OSError("operation aborted")
    aborted.winerror = 995  # type: ignore[attr-defined]
    stream = _BlockingReadStream(error=aborted)
    cancel = threading.Event()
    attempts = 0

    def cancel_read(_handle: int) -> bool:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return False
        stream.release.set()
        return True

    monkeypatch.setattr(interaction_module, "_open_windows_thread", lambda _id: 45)
    monkeypatch.setattr(
        interaction_module, "_cancel_windows_synchronous_io", cancel_read
    )
    monkeypatch.setattr(interaction_module, "_close_windows_handle", lambda _h: None)
    setter = threading.Thread(
        target=_set_cancel_after_read_starts, args=(stream, cancel)
    )
    setter.start()
    try:
        assert interaction_module._windows_cancelable_readline(stream, cancel) is None
    finally:
        setter.join(timeout=5.0)
    assert attempts == 2


def test_windows_cancelable_readline_preserves_first_cancel_error_after_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import taut_summon.interaction as interaction_module

    aborted = OSError("operation aborted")
    aborted.winerror = 995  # type: ignore[attr-defined]
    primary = OSError("cancel failed")
    stream = _BlockingReadStream(error=aborted)
    cancel = threading.Event()
    attempts = 0

    def cancel_read(_handle: int) -> bool:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise primary
        stream.release.set()
        return True

    monkeypatch.setattr(interaction_module, "_open_windows_thread", lambda _id: 46)
    monkeypatch.setattr(
        interaction_module, "_cancel_windows_synchronous_io", cancel_read
    )
    monkeypatch.setattr(interaction_module, "_close_windows_handle", lambda _h: None)
    setter = threading.Thread(
        target=_set_cancel_after_read_starts, args=(stream, cancel)
    )
    setter.start()
    try:
        with pytest.raises(OSError, match="cancel failed") as caught:
            interaction_module._windows_cancelable_readline(stream, cancel)
    finally:
        setter.join(timeout=5.0)
    assert caught.value is primary
    assert attempts == 2
    assert not any(
        thread.name == "taut-summon-shell-input" and thread.is_alive()
        for thread in threading.enumerate()
    )


def test_windows_cancelable_readline_open_failure_aborts_before_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import taut_summon.interaction as interaction_module

    primary = OSError("open failed")
    stream = _BlockingReadStream()
    closed: list[int] = []

    def fail_open(_native_id: int) -> int:
        raise primary

    monkeypatch.setattr(interaction_module, "_open_windows_thread", fail_open)
    monkeypatch.setattr(
        interaction_module,
        "_cancel_windows_synchronous_io",
        lambda _handle: pytest.fail("no handle was opened"),
    )
    monkeypatch.setattr(interaction_module, "_close_windows_handle", closed.append)

    with pytest.raises(OSError, match="open failed") as caught:
        interaction_module._windows_cancelable_readline(stream, threading.Event())
    assert caught.value is primary
    assert stream.read_calls == 0
    assert closed == []


def test_windows_cancelable_readline_interruption_after_start_reaps_and_closes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import taut_summon.interaction as interaction_module

    primary = KeyboardInterrupt("interrupted after start")
    abort_lock_error = KeyboardInterrupt("abort lock interrupted")
    abort_start_error = SystemExit("abort start interrupted")
    join_error = SystemExit("abort join interrupted")
    stream = _BlockingReadStream()
    owner = interaction_module._WindowsCancelableReadOwner(stream, threading.Event())
    events: list[str] = []
    wait_calls = 0
    original_wait_until_ready = owner._wait_until_ready
    abort_lock = _InterruptingLock(abort_lock_error)
    start_event = _InterruptingSetEvent(abort_start_error)
    owner._state.start = start_event  # type: ignore[assignment]
    original_abort_before_read = owner._abort_before_read

    def interrupt_after_start() -> None:
        nonlocal wait_calls
        wait_calls += 1
        if wait_calls == 1:
            raise primary
        original_wait_until_ready()

    def interrupt_abort_lock() -> None:
        owner._state.lock = abort_lock  # type: ignore[assignment]
        original_abort_before_read()

    join_calls = 0
    original_join = owner._reader.join

    def interrupt_join(timeout: float | None = None) -> None:
        nonlocal join_calls
        join_calls += 1
        if join_calls == 1:
            raise join_error
        original_join(timeout)

    original_is_alive = owner._reader.is_alive
    forced_alive = True

    def is_alive_after_done() -> bool:
        nonlocal forced_alive
        if owner._state.done.is_set() and forced_alive:
            forced_alive = False
            return True
        return original_is_alive()

    def close_handle(_handle: int) -> None:
        assert owner._state.done.is_set()
        assert not original_is_alive()
        events.append("close")

    monkeypatch.setattr(interaction_module, "_open_windows_thread", lambda _id: 52)
    monkeypatch.setattr(owner, "_wait_until_ready", interrupt_after_start)
    monkeypatch.setattr(owner, "_abort_before_read", interrupt_abort_lock)
    monkeypatch.setattr(owner._reader, "join", interrupt_join)
    monkeypatch.setattr(owner._reader, "is_alive", is_alive_after_done)
    monkeypatch.setattr(interaction_module, "_close_windows_handle", close_handle)

    with pytest.raises(KeyboardInterrupt, match="interrupted after start") as caught:
        owner.run()
    assert caught.value is primary
    assert stream.read_calls == 0
    assert wait_calls == 2
    assert abort_lock.enter_calls >= 2
    assert start_event.set_calls >= 2
    assert join_calls >= 1
    assert events == ["close"]


@pytest.mark.parametrize("line", ["", "not-enter\n"])
def test_windows_cancelable_readline_preserves_nonblank_and_eof(
    monkeypatch: pytest.MonkeyPatch,
    line: str,
) -> None:
    import taut_summon.interaction as interaction_module

    stream = _BlockingReadStream(line=line)
    stream.release.set()
    monkeypatch.setattr(interaction_module, "_open_windows_thread", lambda _id: 47)
    monkeypatch.setattr(
        interaction_module,
        "_cancel_windows_synchronous_io",
        lambda _handle: pytest.fail("completed line owns the decision"),
    )
    monkeypatch.setattr(interaction_module, "_close_windows_handle", lambda _h: None)

    assert (
        interaction_module._windows_cancelable_readline(stream, threading.Event())
        == line
    )


def test_windows_cancelable_readline_preserves_reader_error_over_close_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import taut_summon.interaction as interaction_module

    read_error = UnicodeError("read failed")
    close_error = OSError("close failed")
    stream = _BlockingReadStream(error=read_error)
    stream.release.set()
    monkeypatch.setattr(interaction_module, "_open_windows_thread", lambda _id: 48)
    monkeypatch.setattr(
        interaction_module,
        "_cancel_windows_synchronous_io",
        lambda _handle: pytest.fail("completed reader owns the decision"),
    )

    def fail_close(_handle: int) -> None:
        raise close_error

    monkeypatch.setattr(interaction_module, "_close_windows_handle", fail_close)

    with pytest.raises(UnicodeError, match="read failed") as caught:
        interaction_module._windows_cancelable_readline(stream, threading.Event())
    assert caught.value is read_error


def test_windows_cancelable_readline_close_failure_is_fatal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import taut_summon.interaction as interaction_module

    close_error = OSError("close failed")
    stream = _BlockingReadStream(line="\n")
    stream.release.set()
    monkeypatch.setattr(interaction_module, "_open_windows_thread", lambda _id: 49)
    monkeypatch.setattr(
        interaction_module,
        "_cancel_windows_synchronous_io",
        lambda _handle: pytest.fail("completed line owns the decision"),
    )

    def fail_close(_handle: int) -> None:
        raise close_error

    monkeypatch.setattr(interaction_module, "_close_windows_handle", fail_close)

    with pytest.raises(OSError, match="close failed") as caught:
        interaction_module._windows_cancelable_readline(stream, threading.Event())
    assert caught.value is close_error


def test_windows_cancelable_readline_owner_error_cancels_and_joins_before_close(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import taut_summon.interaction as interaction_module

    owner_error = KeyboardInterrupt("owner interrupted")
    aborted = OSError("operation aborted")
    aborted.winerror = 995  # type: ignore[attr-defined]
    stream = _BlockingReadStream(error=aborted)
    events: list[str] = []
    wait_error = SystemExit("cleanup wait interrupted")
    join_error = KeyboardInterrupt("cleanup join interrupted")
    done = _InterruptingEvent(wait_error)
    owner = interaction_module._WindowsCancelableReadOwner(stream, threading.Event())
    owner._state.done = done  # type: ignore[assignment]

    def fail_observe(_handle: int) -> str | None:
        owner._state.start.set()
        if not stream.started.wait(timeout=5.0):
            raise RuntimeError("reader did not start")
        raise owner_error

    def cancel_read(_handle: int) -> bool:
        events.append("cancel")
        stream.release.set()
        return True

    def close_handle(_handle: int) -> None:
        assert not any(
            thread.name == "taut-summon-shell-input" and thread.is_alive()
            for thread in threading.enumerate()
        )
        events.append("close")

    original_join = owner._reader.join
    join_calls = 0

    def interrupt_join(timeout: float | None = None) -> None:
        nonlocal join_calls
        join_calls += 1
        if join_calls == 1:
            raise join_error
        original_join(timeout)

    original_is_alive = owner._reader.is_alive
    forced_alive = True

    def is_alive_after_done() -> bool:
        nonlocal forced_alive
        if done.is_set() and forced_alive:
            forced_alive = False
            return True
        return original_is_alive()

    monkeypatch.setattr(interaction_module, "_open_windows_thread", lambda _id: 50)
    monkeypatch.setattr(owner, "_observe", fail_observe)
    monkeypatch.setattr(owner._reader, "join", interrupt_join)
    monkeypatch.setattr(owner._reader, "is_alive", is_alive_after_done)
    monkeypatch.setattr(
        interaction_module, "_cancel_windows_synchronous_io", cancel_read
    )
    monkeypatch.setattr(interaction_module, "_close_windows_handle", close_handle)

    with pytest.raises(KeyboardInterrupt, match="owner interrupted") as caught:
        owner.run()
    assert caught.value is owner_error
    assert done.wait_calls >= 2
    assert join_calls >= 1
    assert events == ["cancel", "close"]


def test_windows_cancelable_readline_cleanup_claim_retries_interrupted_lock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import taut_summon.interaction as interaction_module

    primary = KeyboardInterrupt("owner interrupted")
    claim_error = SystemExit("cancel claim interrupted")
    aborted = OSError("operation aborted")
    aborted.winerror = 995  # type: ignore[attr-defined]
    stream = _BlockingReadStream(error=aborted)
    owner = interaction_module._WindowsCancelableReadOwner(stream, threading.Event())
    lock = _InterruptingLock(claim_error)
    events: list[str] = []

    def cancel_read(_handle: int) -> bool:
        events.append("cancel")
        stream.release.set()
        return True

    def close_handle(_handle: int) -> None:
        assert owner._state.done.is_set()
        assert not owner._reader.is_alive()
        events.append("close")

    monkeypatch.setattr(interaction_module, "_open_windows_thread", lambda _id: 53)
    monkeypatch.setattr(
        interaction_module, "_cancel_windows_synchronous_io", cancel_read
    )
    monkeypatch.setattr(interaction_module, "_close_windows_handle", close_handle)

    owner._reader.start()
    owner._wait_until_ready()
    owner._state.start.set()
    assert stream.started.wait(timeout=5.0)
    owner._primary_error = primary
    owner._state.lock = lock  # type: ignore[assignment]

    assert owner._finish_reader(53) is None
    assert owner._primary_error is primary
    assert lock.enter_calls >= 2
    assert events == ["cancel", "close"]


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

    with pytest.raises(RuntimeError, match="terminal is not available"):  # noqa: SIM117 approved [DOM-10.2.1] [RUFF-SUP-074] exception
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
        "on_ready",
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
        except BaseException as exc:  # noqa: BLE001 approved [DOM-10.2.1] [RUFF-SUP-070] exception
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

    prior_handlers: dict[str, tuple[Any, Any]] = {
        "callable": (prior_sigint, prior_sigterm),
        "default": (signal.SIG_DFL, signal.SIG_DFL),
        "ignore": (signal.SIG_IGN, signal.SIG_IGN),
    }
    prior_sigint_value, prior_sigterm_value = prior_handlers[prior_kind]

    def run_driver(_driver: SummonDriver) -> int:
        failures: dict[str, BaseException] = {
            "translated": DriverError("driver failure"),
            "exception": RuntimeError("host failure"),
            "base-exception": _HostAbort("host abort"),
        }
        failure = failures.get(exit_kind)
        if failure is not None:
            raise failure
        return 0

    signal.signal(signal.SIGINT, prior_sigint_value)
    signal.signal(signal.SIGTERM, prior_sigterm_value)
    monkeypatch.setattr(SummonDriver, "_run", run_driver)
    try:
        expected_failures: dict[str, tuple[type[BaseException], str]] = {
            "translated": (SummonOperationError, "driver failure"),
            "exception": (RuntimeError, "host failure"),
            "base-exception": (_HostAbort, "host abort"),
        }
        expected = expected_failures.get(exit_kind)
        if expected is None:
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
            expected_type, expected_message = expected
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
        except BaseException as exc:  # noqa: BLE001 approved [DOM-10.2.1] [RUFF-SUP-070] exception
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
            with suppress(Exception):  # noqa: SIM117 approved [DOM-10.2.1] [RUFF-SUP-074] exception
                with monkeypatch.context() as stop_environment:
                    stop_environment.delenv("TAUT_AS")
                    stop_environment.delenv("TAUT_TOKEN")
                    controller.stop("hosted")
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
@pytest.mark.parametrize(
    "decision",
    [False, RuntimeError("prompt failed")],
    ids=["cancel", "failure"],
)
def test_rich_host_attach_decision_ends_before_real_pty_spawn(
    summon_db: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    decision: bool | BaseException,
) -> None:
    from taut_summon import SummonOperationError, SummonRequest
    from taut_summon._driver import SummonDriver

    pty = pytest.importorskip("pty", reason="host interaction requires a POSIX PTY")
    _configure_fake_pty(monkeypatch, tmp_path=tmp_path)
    user_master, user_slave = pty.openpty()
    interaction = _GatedAttachDecisionInteraction(
        input_fd=user_slave,
        output_fd=user_slave,
        decision=decision,
    )
    request = SummonRequest(
        name="cancelled-host",
        threads=("general",),
        terminal=False,
        persona=None,
        system_prompt_file=None,
        rate_limit=None,
        provider_flag="pty",
    )
    drivers: list[SummonDriver] = []
    real_driver_init = SummonDriver.__init__

    def observed_driver_init(driver: SummonDriver, *args: Any, **kwargs: Any) -> None:
        real_driver_init(driver, *args, **kwargs)
        drivers.append(driver)

    monkeypatch.setattr(SummonDriver, "__init__", observed_driver_init)
    readiness: list[Any] = []
    thread, failures = _start_foreground_run(
        db=summon_db,
        request=request,
        interaction=interaction,
        on_ready=readiness.append,
    )
    try:
        fake_log = tmp_path / "host-fake-tui.jsonl"
        wait_until(
            lambda: (
                interaction.confirmation_entered.is_set()
                or bool(fake_log.exists() and fake_log.read_text(encoding="utf-8"))
            ),
            timeout=5.0,
            message="pre-spawn confirmation or forbidden provider spawn",
        )
        assert interaction.confirmation_entered.is_set()
        assert not fake_log.exists()

        interaction.allow_confirmation.set()
        thread.join(timeout=10.0)

        assert not thread.is_alive()
        if isinstance(decision, BaseException):
            assert len(failures) == 1
            assert isinstance(failures[0], SummonOperationError)
            assert "terminal acknowledgement failed: prompt failed" in str(failures[0])
        else:
            assert failures == []
        assert readiness == []
        assert len(interaction.confirmation_notices) == 1
        notice = interaction.confirmation_notices[0]
        assert (notice.member, notice.provider, notice.detach_hint) == (
            "cancelled-host",
            "pty",
            "Ctrl-\\ Ctrl-\\",
        )
        assert interaction.lease_events == []
        member = _member_by_name(summon_db, "cancelled-host")
        assert member is not None
        row = _session_row(summon_db, member.member_id)
        assert row is not None
        assert row["wired"] is False
        assert row["driver_pid"] is None
    finally:
        interaction.allow_confirmation.set()
        for driver in drivers:
            driver.request_stop()
        if thread.is_alive():
            try:
                os.write(user_master, b"\x1c\x1c")
            except OSError:
                pass
            thread.join(timeout=10.0)
        os.close(user_master)
        os.close(user_slave)


@pytest.mark.xdist_group("process")
@pytest.mark.sqlite_only
def test_rich_host_real_pty_lease_wires_once_then_wired_resume_skips_lease(  # noqa: C901 approved [DOM-10.2.1] [RUFF-SUP-040] exception
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
            except BaseException as exc:  # noqa: BLE001 approved [DOM-10.2.1] [RUFF-SUP-070] exception
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
        except BaseException as exc:  # noqa: BLE001 approved [DOM-10.2.1] [RUFF-SUP-070] exception
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


# --- [SUM-7.4] setup-recovery escalation matrix -----------------------------


def _configure_gate_pty(
    monkeypatch: pytest.MonkeyPatch,
    *,
    tmp_path: Path,
    pretrusted: bool,
) -> Path:
    gate = Path(__file__).with_name("fixtures") / "gate_harness.py"
    log = tmp_path / "gate-harness.jsonl"
    monkeypatch.setenv("TAUT_SUMMON_PTY_ARGV", json.dumps([sys.executable, str(gate)]))
    monkeypatch.setenv("TAUT_SUMMON_PTY_ROWS", "24")
    monkeypatch.setenv("TAUT_SUMMON_PTY_COLS", "80")
    monkeypatch.setenv("TAUT_SUMMON_PTY_STALL_S", "0.5")
    monkeypatch.setenv("TAUT_SUMMON_PTY_QUIET_MS", "50")
    monkeypatch.setenv("TAUT_SUMMON_PTY_MAX_SETTLE_S", "1.0")
    monkeypatch.setenv("TAUT_GATE_LOG", str(log))
    if pretrusted:
        monkeypatch.setenv("TAUT_GATE_PRETRUSTED", "1")
    else:
        monkeypatch.delenv("TAUT_GATE_PRETRUSTED", raising=False)
    return log


def _gate_events(log: Path) -> list[dict[str, Any]]:
    if not log.exists():
        return []
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]


def _gate_request(name: str, prompt_path: Path, *, detach: bool = False) -> Any:
    from taut_summon import SummonRequest

    return SummonRequest(
        name=name,
        threads=("general",),
        terminal=False,
        persona=None,
        system_prompt_file=str(prompt_path),
        rate_limit=None,
        detach=detach,
        provider_flag="pty",
    )


class _NoTtyPtyHostInteraction(_PtyHostInteraction):
    """Host whose availability probe reports NO_TTY."""

    def terminal_availability(self, intent: Any) -> Any:
        from taut_summon import TerminalAvailability

        self.availability_calls.append(intent)
        return TerminalAvailability.NO_TTY


class _NonRecoveryPtyHostInteraction(_PtyHostInteraction):
    """Host that declares no setup-recovery support (the v1 TUI posture)."""

    def supports_setup_recovery(self) -> bool:
        return False


def _wire_member_through_pretrusted_first_attach(
    *,
    db: Path,
    request: Any,
    user_master: int,
    user_slave: int,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Run 1: first attach against the pretrusted chat prompt wires the row."""

    from taut_summon import SummonController

    _configure_gate_pty(monkeypatch, tmp_path=tmp_path, pretrusted=True)
    interaction = _PtyHostInteraction(input_fd=user_slave, output_fd=user_slave)
    thread, failures = _start_foreground_run(
        db=db, request=request, interaction=interaction
    )
    try:
        assert b"chat>" in _read_pty_until(user_master, b"chat>")
        os.write(user_master, b"\x1c\x1c")
        # Drain the bridge's reset blast so its TCSADRAIN restore completes.
        assert b"\x1b[?2004l" in _read_pty_until(user_master, b"\x1b[?2004l")

        def wired() -> bool:
            member = _member_by_name(db, request.name)
            if member is None:
                return False
            row = _session_row(db, member.member_id)
            return bool(row and row["wired"])

        wait_until(wired, message="pretrusted first attach wired transition")
        SummonController(db_path=db).stop(request.name)
    finally:
        thread.join(timeout=10.0)
    assert not thread.is_alive()
    assert failures == []


@pytest.mark.xdist_group("process")
@pytest.mark.sqlite_only
def test_setup_gate_offers_single_recovery_attach_and_completes_setup(
    summon_db: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("pty", reason="setup recovery requires a POSIX PTY")
    import pty as pty_module

    prompt_marker = "gate-orientation-probe"
    prompt_path = tmp_path / "gate-prompt.txt"
    prompt_path.write_text(prompt_marker, encoding="utf-8")
    request = _gate_request("gated", prompt_path)
    user_master, user_slave = pty_module.openpty()
    try:
        _wire_member_through_pretrusted_first_attach(
            db=summon_db,
            request=request,
            user_master=user_master,
            user_slave=user_slave,
            monkeypatch=monkeypatch,
            tmp_path=tmp_path,
        )

        # Run 2: the wired re-summon hits the trust menu (no paste mode).
        gate_log = _configure_gate_pty(
            monkeypatch, tmp_path=tmp_path / "run2", pretrusted=False
        )
        (tmp_path / "run2").mkdir(exist_ok=True)
        interaction = _PtyHostInteraction(input_fd=user_slave, output_fd=user_slave)
        thread, failures = _start_foreground_run(
            db=summon_db, request=request, interaction=interaction
        )
        try:
            # The offer arrives without any injection into the menu.
            wait_until(
                lambda: len(interaction.confirmation_notices) == 1,
                message="setup-recovery acknowledgement request",
            )
            events = _gate_events(gate_log)
            assert [e["event"] for e in events if e["event"] == "input"] == []

            # Proceed: the recovery generation bridges; answer the gate.
            assert b"Trust this folder?" in _read_pty_until(
                user_master, b"Trust this folder?"
            )
            os.write(user_master, b"\x14")
            assert b"chat>" in _read_pty_until(user_master, b"chat>")
            os.write(user_master, b"\x1c\x1c")
            # Drain the reset blast so the bridge's TCSADRAIN restore returns.
            assert b"\x1b[?2004l" in _read_pty_until(user_master, b"\x1b[?2004l")

            # Detach resumes the detached flow: orientation reaches the chat.
            def oriented() -> bool:
                return any(
                    e["event"] == "input" and prompt_marker in e.get("raw", "")
                    for e in _gate_events(gate_log)
                )

            wait_until(oriented, message="post-recovery orientation injection")
            assert len(interaction.confirmation_notices) == 1
            # Invariant 3: availability is sampled exactly once per
            # foreground run; the escalation reuses the cached value.
            from taut_summon import TerminalIntent

            assert interaction.availability_calls == [TerminalIntent.PREFERRED]
            # [SUM-13] matrix: the recovery generation reaches watcher
            # readiness — chat posted by another member arrives through the
            # watcher's injection path.
            from taut import TautClient

            witness = TautClient(db_path=summon_db, as_name="Witness")
            try:
                witness.join("general")
                witness.say("general", "watcher-readiness-probe")
            finally:
                witness.close()

            def watcher_delivered() -> bool:
                return any(
                    e["event"] == "input"
                    and "watcher-readiness-probe" in e.get("raw", "")
                    for e in _gate_events(gate_log)
                )

            wait_until(watcher_delivered, message="watcher injection after recovery")
            from taut_summon import SummonController

            SummonController(db_path=summon_db).stop(request.name)
        finally:
            thread.join(timeout=15.0)
        assert not thread.is_alive()
        assert failures == []
        assert interaction.lease_events.count("enter") == 1
    finally:
        os.close(user_master)
        os.close(user_slave)


@pytest.mark.xdist_group("process")
@pytest.mark.sqlite_only
def test_setup_gate_decline_continues_detached_and_enriches_give_up(
    summon_db: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("pty", reason="setup recovery requires a POSIX PTY")
    import pty as pty_module

    from taut_summon import SummonOperationError

    prompt_path = tmp_path / "gate-prompt.txt"
    prompt_path.write_text("decline-orientation-probe", encoding="utf-8")
    request = _gate_request("declined", prompt_path)
    monkeypatch.setenv("TAUT_SUMMON_RESUME_BACKOFF", "0.1,0.1")
    user_master, user_slave = pty_module.openpty()
    try:
        _wire_member_through_pretrusted_first_attach(
            db=summon_db,
            request=request,
            user_master=user_master,
            user_slave=user_slave,
            monkeypatch=monkeypatch,
            tmp_path=tmp_path,
        )

        (tmp_path / "run2").mkdir(exist_ok=True)
        gate_log = _configure_gate_pty(
            monkeypatch, tmp_path=tmp_path / "run2", pretrusted=False
        )
        interaction = _GatedAttachDecisionInteraction(
            input_fd=user_slave, output_fd=user_slave, decision=False
        )
        thread, failures = _start_foreground_run(
            db=summon_db, request=request, interaction=interaction
        )
        try:
            assert interaction.confirmation_entered.wait(timeout=15.0)
            interaction.allow_confirmation.set()
            # Declined: detached continuation feeds Enter into fresh menus
            # until the ladder exhausts; exactly one offer was ever made.
            thread.join(timeout=30.0)
            assert not thread.is_alive()
        finally:
            if thread.is_alive():  # pragma: no cover - cleanup guard
                from taut_summon import SummonController

                SummonController(db_path=summon_db).stop(request.name)
                thread.join(timeout=10.0)
        assert len(interaction.confirmation_notices) == 1
        assert len(failures) == 1
        failure = failures[0]
        # The public controller boundary wraps the driver give-up error.
        assert isinstance(failure, SummonOperationError)
        message = str(failure)
        assert "exited" in message and "giving up" in message
        assert "last screen output:" in message
        assert "Trust this folder?" in message
        assert "taut summon --attach declined" in message
        declined_defaults = [
            e for e in _gate_events(gate_log) if e["event"] == "declined_default"
        ]
        assert declined_defaults, "detached continuation should reach the menu"
    finally:
        os.close(user_master)
        os.close(user_slave)


@pytest.mark.xdist_group("process")
@pytest.mark.sqlite_only
def test_setup_gate_shutdown_during_offer_ends_cleanly(
    summon_db: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("pty", reason="setup recovery requires a POSIX PTY")
    import pty as pty_module

    from taut_summon._driver import SummonDriver

    prompt_path = tmp_path / "gate-prompt.txt"
    prompt_path.write_text("shutdown-orientation-probe", encoding="utf-8")
    request = _gate_request("stopped", prompt_path)
    drivers: list[SummonDriver] = []
    real_driver_init = SummonDriver.__init__

    def observed_driver_init(driver: SummonDriver, *args: Any, **kwargs: Any) -> None:
        real_driver_init(driver, *args, **kwargs)
        drivers.append(driver)

    monkeypatch.setattr(SummonDriver, "__init__", observed_driver_init)
    user_master, user_slave = pty_module.openpty()
    try:
        _wire_member_through_pretrusted_first_attach(
            db=summon_db,
            request=request,
            user_master=user_master,
            user_slave=user_slave,
            monkeypatch=monkeypatch,
            tmp_path=tmp_path,
        )

        (tmp_path / "run2").mkdir(exist_ok=True)
        gate_log = _configure_gate_pty(
            monkeypatch, tmp_path=tmp_path / "run2", pretrusted=False
        )
        interaction = _GatedAttachDecisionInteraction(
            input_fd=user_slave, output_fd=user_slave, decision=False
        )
        thread, failures = _start_foreground_run(
            db=summon_db, request=request, interaction=interaction
        )
        try:
            assert interaction.confirmation_entered.wait(timeout=15.0)
            drivers[-1].request_stop()
            interaction.allow_confirmation.set()
            thread.join(timeout=15.0)
            assert not thread.is_alive()
        finally:
            if thread.is_alive():  # pragma: no cover - cleanup guard
                drivers[-1].request_stop()
                thread.join(timeout=10.0)
        assert failures == []
        # Shutdown during the offer spawns nothing further and injects nothing.
        inputs = [e for e in _gate_events(gate_log) if e["event"] == "input"]
        assert inputs == []
    finally:
        os.close(user_master)
        os.close(user_slave)


@pytest.mark.xdist_group("process")
@pytest.mark.sqlite_only
def test_confirmed_input_prompt_never_offers_setup_recovery(
    summon_db: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("pty", reason="setup recovery requires a POSIX PTY")
    import pty as pty_module

    from taut_summon import SummonController

    prompt_marker = "confirmed-orientation-probe"
    prompt_path = tmp_path / "gate-prompt.txt"
    prompt_path.write_text(prompt_marker, encoding="utf-8")
    request = _gate_request("prompted", prompt_path)
    user_master, user_slave = pty_module.openpty()
    try:
        _wire_member_through_pretrusted_first_attach(
            db=summon_db,
            request=request,
            user_master=user_master,
            user_slave=user_slave,
            monkeypatch=monkeypatch,
            tmp_path=tmp_path,
        )

        (tmp_path / "run2").mkdir(exist_ok=True)
        gate_log = _configure_gate_pty(
            monkeypatch, tmp_path=tmp_path / "run2", pretrusted=True
        )
        interaction = _PtyHostInteraction(input_fd=user_slave, output_fd=user_slave)
        thread, failures = _start_foreground_run(
            db=summon_db, request=request, interaction=interaction
        )
        try:

            def oriented() -> bool:
                return any(
                    e["event"] == "input" and prompt_marker in e.get("raw", "")
                    for e in _gate_events(gate_log)
                )

            wait_until(oriented, message="confirmed-prompt orientation injection")
            assert interaction.confirmation_notices == []
            SummonController(db_path=summon_db).stop(request.name)
        finally:
            thread.join(timeout=15.0)
        assert not thread.is_alive()
        assert failures == []
    finally:
        os.close(user_master)
        os.close(user_slave)


@pytest.mark.xdist_group("process")
@pytest.mark.sqlite_only
@pytest.mark.parametrize(
    ("member", "variant"),
    [
        ("fallkill", "kill-switch"),
        ("falldetach", "forced-detach"),
        ("fallnotty", "no-tty"),
        ("fallhost", "non-supporting-host"),
    ],
)
def test_setup_gate_fall_through_variants_inject_after_settle(
    summon_db: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    member: str,
    variant: str,
) -> None:
    """[SUM-13] matrix: each failed escalation condition falls through to
    today's inject-after-settle behavior with zero offers, through a real
    driver run against the real gate child."""

    pytest.importorskip("pty", reason="setup recovery requires a POSIX PTY")
    import pty as pty_module

    from taut_summon import SummonOperationError

    prompt_path = tmp_path / "gate-prompt.txt"
    prompt_path.write_text("fall-through-orientation-probe", encoding="utf-8")
    request = _gate_request(member, prompt_path)
    monkeypatch.setenv("TAUT_SUMMON_RESUME_BACKOFF", "0.1")
    user_master, user_slave = pty_module.openpty()
    try:
        _wire_member_through_pretrusted_first_attach(
            db=summon_db,
            request=request,
            user_master=user_master,
            user_slave=user_slave,
            monkeypatch=monkeypatch,
            tmp_path=tmp_path,
        )

        (tmp_path / "run2").mkdir(exist_ok=True)
        gate_log = _configure_gate_pty(
            monkeypatch, tmp_path=tmp_path / "run2", pretrusted=False
        )
        interaction: _PtyHostInteraction
        run2_request = request
        if variant == "kill-switch":
            monkeypatch.setenv("TAUT_SUMMON_SETUP_RECOVERY", "0")
            interaction = _PtyHostInteraction(input_fd=user_slave, output_fd=user_slave)
        elif variant == "forced-detach":
            run2_request = _gate_request(member, prompt_path, detach=True)
            interaction = _PtyHostInteraction(input_fd=user_slave, output_fd=user_slave)
        elif variant == "no-tty":
            interaction = _NoTtyPtyHostInteraction(
                input_fd=user_slave, output_fd=user_slave
            )
        else:
            interaction = _NonRecoveryPtyHostInteraction(
                input_fd=user_slave, output_fd=user_slave
            )
        thread, failures = _start_foreground_run(
            db=summon_db, request=run2_request, interaction=interaction
        )
        thread.join(timeout=30.0)
        try:
            assert not thread.is_alive()
        finally:
            if thread.is_alive():  # pragma: no cover - cleanup guard
                from taut_summon import SummonController

                SummonController(db_path=summon_db).stop(member)
                thread.join(timeout=10.0)
        # Zero offers: no acknowledgement request reached the host.
        assert interaction.confirmation_notices == []
        assert interaction.lease_events == []
        # Inject-after-settle reached the menu: the gate saw its default
        # answer and exited, and the ladder ended in the enriched give-up.
        declined = [
            e for e in _gate_events(gate_log) if e["event"] == "declined_default"
        ]
        assert declined, "orientation injection should reach the gate menu"
        assert len(failures) == 1
        failure = failures[0]
        assert isinstance(failure, SummonOperationError)
        message = str(failure)
        assert "giving up" in message
        assert "last screen output:" in message
        assert f"taut summon --attach {member}" in message
    finally:
        os.close(user_master)
        os.close(user_slave)
