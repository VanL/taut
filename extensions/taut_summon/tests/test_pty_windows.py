from __future__ import annotations

import os
import sys
import threading
import time
from typing import Any, Protocol, cast

import psutil
import pytest
from taut_summon._pty import _DetachChordMatcher

pytestmark = [
    pytest.mark.windows_only,
    pytest.mark.xdist_group("process"),
    pytest.mark.sqlite_only,
]


class _Terminal:
    def __init__(self) -> None:
        self.data = bytearray()

    def encode_injection(self, text: str) -> bytes:
        return (
            text.replace("\x00", "").replace("\r", " ").replace("\n", " ").encode()
            + b"\r"
        )

    def observe_output(self, data: bytes) -> tuple[bytes, ...]:
        self.data.extend(data)
        return ()

    def mark_stalled(self, *, now: float | None = None) -> None:
        del now

    def mark_awaiting_onboarding(self) -> None:
        pass

    @staticmethod
    def detach_matcher(chord: bytes) -> _DetachChordMatcher:
        return _DetachChordMatcher(chord)

    @property
    def input_prompt_observed(self) -> bool:
        return False

    def output_tail(self) -> str:
        return bytes(self.data[-4096:]).decode("utf-8", errors="replace")

    def status_fields(self) -> dict[str, str]:
        return {}


class _TailHandle(Protocol):
    def output_tail(self) -> str: ...


def _wait_for_tail(handle: _TailHandle, marker: str, timeout: float = 10.0) -> str:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        tail = handle.output_tail()
        if marker in tail:
            return tail
        time.sleep(0.02)
    pytest.fail(f"ConPTY tail did not contain {marker!r}: {tail!r}")


def _child_argv() -> tuple[str, ...]:
    source = r"""
import msvcrt, os, signal, subprocess, sys, time
signal.signal(signal.SIGINT, lambda *_: print("INT signal", flush=True))
sys.stdout.write("\x1b[6n")
sys.stdout.flush()
report = ""
while not report.endswith("R"):
    report += msvcrt.getwch()
print("QUERY_REPLY " + repr(report), flush=True)
desc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(300)"])
print(
    f"READY {os.getpid()} {desc.pid} "
    f"{os.environ.get('TAUT_AS')} {os.environ.get('TAUT_TOKEN')}",
    flush=True,
)
line = ""
discard = False
while True:
    char = msvcrt.getwch()
    if char == "\x03":
        line = ""
        discard = False
        print("INT byte", flush=True)
        continue
    if discard:
        continue
    if char not in ("\r", "\n"):
        line += char
        continue
    if line:
        if line.startswith("PAUSE"):
            discard = True
            print("PAUSED " + line, flush=True)
            time.sleep(2)
        else:
            print("ECHO " + line, flush=True)
        line = ""
"""
    return (sys.executable, "-c", source)


@pytest.mark.skipif(os.name != "nt", reason="requires Windows ConPTY")
def test_public_pty_adapter_reports_natural_exit_without_close_error() -> None:
    from taut_summon._adapter import ExitEvent
    from taut_summon._pty import PtyAdapter, PtySpec

    handle = PtyAdapter(
        PtySpec(
            name="windows-natural-exit",
            argv=(
                sys.executable,
                "-c",
                "print('done', flush=True); raise SystemExit(7)",
            ),
        )
    ).spawn(system_prompt="unused", env={})
    events: list[object] = []
    pump = threading.Thread(target=lambda: events.extend(handle.events()))
    pump.start()
    pump.join(timeout=10.0)
    assert not pump.is_alive()
    assert [event.returncode for event in events if isinstance(event, ExitEvent)] == [7]
    handle.close()


@pytest.mark.skipif(os.name != "nt", reason="requires Windows ConPTY")
def test_public_pty_adapter_surfaces_unknown_query_stall() -> None:
    from taut_summon._pty import PtyAdapter, PtySpec

    source = "import sys,time; sys.stdout.write('\\x1b[?15n'); sys.stdout.flush(); time.sleep(30)"
    handle = PtyAdapter(
        PtySpec(
            name="windows-query-stall",
            argv=(sys.executable, "-c", source),
            stall_s=0.1,
            quiet_ms=10,
            max_settle_s=1.0,
        )
    ).spawn(system_prompt="unused", env={})
    pump = threading.Thread(target=lambda: list(handle.events()))
    pump.start()
    try:
        handle.wait_until_quiet()
        assert handle.status_fields()["awaiting_query"] == "[?15n"
    finally:
        handle.close()
        pump.join(timeout=10.0)
        assert not pump.is_alive()


@pytest.mark.skipif(os.name != "nt", reason="requires Windows ConPTY")
def test_public_pty_adapter_runs_conpty_and_retires_domain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from taut_summon._adapter import AdapterError, ExitEvent
    from taut_summon._pty import PtyAdapter, PtySpec

    monkeypatch.setenv("taut_as", "stale-as")
    monkeypatch.setenv("taut_token", "stale-token")
    handle = PtyAdapter(
        PtySpec(
            name="windows-proof",
            argv=_child_argv(),
            stall_s=2.0,
            quiet_ms=10,
            max_settle_s=2.0,
        )
    ).spawn(
        system_prompt="unused",
        env={"TAUT_AS": "proof-as", "TAUT_TOKEN": "proof-token"},
    )
    events: list[object] = []
    pump = threading.Thread(target=lambda: events.extend(handle.events()))
    pump.start()
    ready = _wait_for_tail(handle, "READY")
    ready_line = next(line for line in ready.splitlines() if "READY" in line)
    _, leader_text, descendant_text, child_as, child_token = ready_line.split()[-5:]
    assert child_as == "proof-as"
    assert child_token == "proof-token"
    assert "QUERY_REPLY '\\x1b[1;1R'" in ready
    leader = psutil.Process(int(leader_text))
    descendant = psutil.Process(int(descendant_text))

    handle.inject("héllo")
    _wait_for_tail(handle, "ECHO héllo")
    handle.inject("PAUSE_INTERRUPT")
    _wait_for_tail(handle, "PAUSED PAUSE_INTERRUPT")
    write_errors: list[AdapterError] = []

    def blocked_inject(payload: str) -> None:
        try:
            handle.inject(payload)
        except AdapterError as exc:
            write_errors.append(exc)

    active = threading.Thread(target=blocked_inject, args=("x" * (64 * 1024 * 1024),))
    queued = threading.Thread(target=blocked_inject, args=("old queued writer",))
    active.start()
    time.sleep(0.1)
    queued.start()
    time.sleep(0.1)
    handle.interrupt()
    active.join(timeout=10.0)
    queued.join(timeout=10.0)
    assert not active.is_alive()
    assert not queued.is_alive()
    assert len(write_errors) == 2
    assert all("interrupted" in str(error) for error in write_errors)
    _wait_for_tail(handle, "INT byte")
    handle.inject("after")
    _wait_for_tail(handle, "ECHO after")

    handle.inject("PAUSE_CLOSE")
    _wait_for_tail(handle, "PAUSED PAUSE_CLOSE")
    closing = threading.Thread(target=lambda: blocked_inject("y" * (64 * 1024 * 1024)))
    closing.start()
    time.sleep(0.1)
    started = time.monotonic()
    handle.request_close()
    assert time.monotonic() - started < 0.5
    with pytest.raises(AdapterError, match="closed"):
        handle.inject("rejected")
    handle.close()
    closing.join(timeout=10.0)
    assert not closing.is_alive()
    assert len(write_errors) == 3
    assert "interrupted" in str(write_errors[-1])
    pump.join(timeout=10.0)
    assert not pump.is_alive()
    assert sum(isinstance(event, ExitEvent) for event in events) == 1
    assert not leader.is_running()
    assert not descendant.is_running()


def test_console_snapshot_restores_exact_values_after_partial_setup() -> None:
    from taut_summon._adapter import AdapterError
    from taut_summon._win32_io import ConsoleLease

    class FakeConsoleApi:
        def __init__(self) -> None:
            self.input_mode = 0x1F7
            self.output_mode = 0x003
            self.input_cp = 437
            self.output_cp = 1252
            self.calls: list[tuple[str, int]] = []

        def get_console_mode(self, handle: int) -> int:
            return self.input_mode if handle == 11 else self.output_mode

        def set_console_mode(self, handle: int, value: int) -> None:
            self.calls.append((f"mode-{handle}", value))

        def get_console_cp(self) -> int:
            return self.input_cp

        def set_console_cp(self, value: int) -> None:
            self.calls.append(("input-cp", value))

        def get_console_output_cp(self) -> int:
            return self.output_cp

        def set_console_output_cp(self, value: int) -> None:
            self.calls.append(("output-cp", value))
            if value == 65001:
                raise AdapterError("injected output code-page failure")

    api = FakeConsoleApi()
    lease = ConsoleLease(api=api, input_handle=11, output_handle=12)
    with pytest.raises(AdapterError, match="injected output code-page failure"):
        lease.enter()
    assert api.calls[-4:] == [
        ("mode-11", 0x1F7),
        ("mode-12", 0x003),
        ("input-cp", 437),
        ("output-cp", 1252),
    ]


@pytest.mark.skipif(os.name != "nt", reason="requires public Windows dispatch")
def test_public_adapter_reports_missing_conpty_export(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from taut_summon import _pty_windows
    from taut_summon._adapter import AdapterError
    from taut_summon._pty import PtyAdapter, PtySpec
    from taut_summon._win32_io import NativeApi as RealNativeApi

    class Function:
        argtypes: object
        restype: object

        def __call__(self, *_args: object) -> int:
            return 1

    class MissingConPtyLibrary:
        CreatePipe = Function()

    monkeypatch.setattr(
        _pty_windows,
        "NativeApi",
        lambda: RealNativeApi(library=MissingConPtyLibrary(), last_error=lambda: 127),
    )
    with pytest.raises(
        AdapterError,
        match="Windows ConPTY initialization is unavailable: missing CreatePseudoConsole",
    ):
        PtyAdapter(PtySpec(name="missing-conpty", argv=("cmd.exe",))).spawn(
            system_prompt="unused",
            env={},
        )


def test_attach_partial_duplicate_failure_closes_first_duplicate() -> None:
    from taut_summon._adapter import AdapterError
    from taut_summon._pty_windows import _AttachSession

    class Api:
        def __init__(self) -> None:
            self.calls = 0
            self.closed: list[int | None] = []

        def duplicate_fd_handle(self, _fd: int) -> int:
            self.calls += 1
            if self.calls == 2:
                raise AdapterError("injected second duplicate failure")
            return 41

        def close_handle(self, handle: int | None) -> None:
            self.closed.append(handle)

    api = Api()
    owner = type("Owner", (), {"_api": api})()
    with pytest.raises(AdapterError, match="injected second duplicate failure"):
        _AttachSession(
            cast(Any, owner),
            wake=threading.Event(),
            shutdown=threading.Event(),
            input_fd=0,
            output_fd=1,
            detach_chord=b"xx",
        )
    assert api.closed == [41]


def test_attach_route_failure_retires_started_sink_before_handles_close() -> None:
    from taut_summon._adapter import AdapterError
    from taut_summon._pty_windows import _AttachSession
    from taut_summon._win32_io import ERROR_INVALID_HANDLE, Win32IoError

    class Api:
        def __init__(self) -> None:
            self.next_handle = iter((41, 42))
            self.closed: list[int | None] = []

        def duplicate_fd_handle(self, _fd: int) -> int:
            return next(self.next_handle)

        def close_handle(self, handle: int | None) -> None:
            self.closed.append(handle)

        def get_console_mode(self, _handle: int) -> int:
            raise Win32IoError("GetConsoleMode", ERROR_INVALID_HANDLE)

        def open_current_thread(self) -> int:
            return 99

        def write(self, _handle: int, _data: bytes) -> None:
            return

    class Drain:
        def __init__(self) -> None:
            self.sink: object | None = None
            self.unroute_called = False

        def route(self, _generation: int, sink: object) -> None:
            self.sink = sink
            raise AdapterError("injected route publication failure")

        def unroute(self, _generation: int) -> object:
            self.unroute_called = True
            raise AssertionError("an unpublished route must not be unregistered")

    api = Api()
    drain = Drain()
    owner = type(
        "Owner",
        (),
        {
            "_api": api,
            "_attach_generation": 0,
            "_drain": drain,
            "_terminal": _Terminal(),
        },
    )()
    session = _AttachSession(
        cast(Any, owner),
        wake=threading.Event(),
        shutdown=threading.Event(),
        input_fd=0,
        output_fd=1,
        detach_chord=b"xx",
    )
    with pytest.raises(AdapterError, match="injected route publication failure"):
        session.run()
    sink = cast(Any, drain.sink)
    assert sink._done.is_set()
    assert not sink._thread.is_alive()
    assert drain.unroute_called is False
    assert api.closed.count(42) == 1
    assert api.closed[-2:] == [41, 42]
