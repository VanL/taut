from __future__ import annotations

import os
import sys
import threading
import time
from collections.abc import Callable
from typing import Any, Protocol, cast

import psutil
import pytest
from taut_summon._adapter import AdapterError
from taut_summon._pty import _DetachChordMatcher

pytestmark = [
    pytest.mark.windows_only,
    pytest.mark.xdist_group("process"),
    pytest.mark.sqlite_only,
]


def test_win32_process_structures_match_x64_abi() -> None:
    import ctypes

    from taut_summon._win32_io import (
        PROCESS_INFORMATION,
        STARTUPINFOEXW,
        STARTUPINFOW,
    )

    assert ctypes.sizeof(ctypes.c_void_p) == 8
    assert ctypes.sizeof(STARTUPINFOW) == 104
    assert ctypes.sizeof(STARTUPINFOEXW) == 112
    assert ctypes.sizeof(PROCESS_INFORMATION) == 24
    assert STARTUPINFOW.dwFlags.offset == 60


class _Terminal:
    def __init__(self) -> None:
        self.data = bytearray()

    def encode_injection(self, text: str) -> bytes:
        return (
            text.replace("\x00", "").replace("\r", " ").replace("\n", " ").encode()
            + b"\r"
        )

    def observe_output(
        self, data: bytes, *, answer_queries: bool = True
    ) -> tuple[bytes, ...]:
        del answer_queries
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


def _wait_until_true(predicate: Callable[[], bool], timeout: float = 10.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


class _TrackingSerializer:
    def __init__(self, queued_waiting: threading.Event) -> None:
        self.lock = threading.Lock()
        self.queued_waiting = queued_waiting

    def __enter__(self) -> None:
        if threading.current_thread().name.startswith("queued"):
            self.queued_waiting.set()
        self.lock.acquire()

    def __exit__(self, *_args: object) -> None:
        self.lock.release()


def _blocked_epoch_write(writer: Any, errors: list[BaseException]) -> None:
    try:
        writer.write(b"x" * 1_000_000)
    except AdapterError as exc:
        errors.append(exc)


def _drain_windows_pipe(api: Any, read_handle: int, marker: bytes) -> None:
    observed = b""
    try:
        while marker not in observed:
            observed = (observed + api.read(read_handle))[-4096:]
    except OSError:
        return


def _epoch_writer_active(writer: Any) -> bool:
    with writer._state:
        return writer._active is not None


class _DrainApi:
    def __init__(self, release_second: threading.Event) -> None:
        self.release_second = release_second
        self.reads = 0

    def open_current_thread(self) -> int:
        return 91

    def close_handle(self, _handle: int) -> None:
        return

    def read(self, _handle: int) -> bytes:
        from taut_summon._win32_io import ERROR_BROKEN_PIPE, Win32IoError

        self.reads += 1
        if self.reads == 1:
            return b"one-shot prompt"
        assert self.release_second.wait(timeout=10.0)
        if self.reads == 2:
            return b"detached output"
        raise Win32IoError("ReadFile", ERROR_BROKEN_PIPE)


class _DrainOwner:
    def __init__(self) -> None:
        self.observed: list[tuple[bytes, bool]] = []
        self.ended = threading.Event()

    def _observe_output(self, data: bytes, *, answer_queries: bool = True) -> None:
        self.observed.append((data, answer_queries))

    def _output_ended(self) -> None:
        self.ended.set()


class _DrainSink:
    def __init__(self) -> None:
        self.items: list[bytes] = []
        self.received = threading.Event()

    def enqueue(self, generation: int, data: bytes) -> None:
        assert generation == 7
        self.items.append(data)
        self.received.set()


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
def test_public_pty_adapter_closes_before_output_consumption() -> None:
    from taut_summon._pty import PtyAdapter, PtySpec

    handle = PtyAdapter(
        PtySpec(
            name="windows-close-before-consumption",
            argv=(sys.executable, "-c", "import time; time.sleep(300)"),
        )
    ).spawn(system_prompt="unused", env={})

    started = time.monotonic()
    handle.close()

    assert time.monotonic() - started < 10.0


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
    handle.interrupt()
    _wait_for_tail(handle, "INT byte")
    handle.inject("after")
    _wait_for_tail(handle, "ECHO after")

    started = time.monotonic()
    handle.request_close()
    assert time.monotonic() - started < 0.5
    with pytest.raises(AdapterError, match="closed"):
        handle.inject("rejected")
    handle.close()
    pump.join(timeout=10.0)
    assert not pump.is_alive()
    assert sum(isinstance(event, ExitEvent) for event in events) == 1
    assert not leader.is_running()
    assert not descendant.is_running()


@pytest.mark.skipif(os.name != "nt", reason="requires Windows pipe cancellation")
def test_epoch_writer_cancels_a_real_blocked_windows_write() -> None:
    from taut_summon._adapter import AdapterError
    from taut_summon._pty_windows import NativeApi, _EpochWriter

    api = NativeApi()
    read_handle, write_handle = api.create_pipe()
    writer = _EpochWriter(api, write_handle)
    errors: list[BaseException] = []
    queued_waiting = threading.Event()
    writer._serializer = _TrackingSerializer(queued_waiting)  # type: ignore[assignment]

    def start_blocked_pair(label: str) -> tuple[threading.Thread, threading.Thread]:
        queued_waiting.clear()
        active = threading.Thread(
            target=lambda: _blocked_epoch_write(writer, errors),
            name=f"active-{label}",
        )
        queued = threading.Thread(
            target=lambda: _blocked_epoch_write(writer, errors),
            name=f"queued-{label}",
        )
        active.start()
        assert _wait_until_true(lambda: _epoch_writer_active(writer))
        queued.start()
        assert queued_waiting.wait(timeout=10.0)
        return active, queued

    threads: list[threading.Thread] = []
    try:
        active, queued = start_blocked_pair("interrupt")
        threads.extend((active, queued))
        interrupted = threading.Thread(target=writer.interrupt)
        interrupted.start()
        drainer = threading.Thread(
            target=_drain_windows_pipe, args=(api, read_handle, b"\x03")
        )
        drainer.start()
        threads.extend((interrupted, drainer))
        for thread in threads:
            thread.join(timeout=10.0)
            assert not thread.is_alive()
        assert len(errors) == 2
        assert all("interrupted" in str(error) for error in errors)

        active, queued = start_blocked_pair("close")
        threads.extend((active, queued))
        writer.request_close()
        with pytest.raises(AdapterError, match="closed"):
            writer.write(b"rejected")
        closer_drain = threading.Thread(
            target=_drain_windows_pipe, args=(api, read_handle, b"\x03")
        )
        closer_drain.start()
        threads.append(closer_drain)
        writer.finish_close_request()
        for thread in (active, queued, closer_drain):
            thread.join(timeout=10.0)
            assert not thread.is_alive()
        assert len(errors) == 4
        assert all("interrupted" in str(error) for error in errors)
    finally:
        writer.request_close()
        cleanup_drain = threading.Thread(
            target=_drain_windows_pipe, args=(api, read_handle, b"\x03")
        )
        cleanup_drain.start()
        try:
            writer.finish_close_request()
        finally:
            api.close_handle(write_handle)
            cleanup_drain.join(timeout=10.0)
            for thread in threads:
                thread.join(timeout=1.0)
        api.close_handle(read_handle)


def test_output_drain_routes_before_start_and_observes_attach_passively() -> None:
    from taut_summon._pty_windows import _OutputDrain

    release_second = threading.Event()
    owner = _DrainOwner()
    sink = _DrainSink()
    drain = _OutputDrain(cast(Any, _DrainApi(release_second)), 41, cast(Any, owner))

    drain.route(7, cast(Any, sink))
    assert sink.received.wait(timeout=10.0)
    assert sink.items == [b"one-shot prompt"]
    assert owner.observed == [(b"one-shot prompt", False)]

    assert drain.unroute(7) is sink
    release_second.set()
    drain.join_after_close()
    assert owner.ended.is_set()
    assert owner.observed[-1] == (b"detached output", True)


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


def test_console_lease_supports_console_input_with_redirected_output() -> None:
    from taut_summon._win32_io import ConsoleLease, Win32IoError

    class RedirectedOutputApi:
        def __init__(self) -> None:
            self.input_mode = 0x1F7
            self.input_cp = 437
            self.calls: list[tuple[str, int]] = []

        def get_console_mode(self, handle: int) -> int:
            if handle == 12:
                raise Win32IoError("GetConsoleMode", 6)
            return self.input_mode

        def set_console_mode(self, handle: int, value: int) -> None:
            self.calls.append((f"mode-{handle}", value))

        def get_console_cp(self) -> int:
            return self.input_cp

        def set_console_cp(self, value: int) -> None:
            self.calls.append(("input-cp", value))

        def get_console_output_cp(self) -> int:
            raise AssertionError("redirected output has no console code page")

        def set_console_output_cp(self, value: int) -> None:
            raise AssertionError(f"unexpected output code-page write: {value}")

    api = RedirectedOutputApi()
    lease = ConsoleLease(api=api, input_handle=11, output_handle=12)

    lease.enter()
    lease.restore()

    assert api.calls == [
        ("mode-11", 0x3B1),
        ("input-cp", 65001),
        ("mode-11", 0x1F7),
        ("input-cp", 437),
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


def test_environment_block_is_sorted_and_exactly_double_terminated() -> None:
    from taut_summon._pty_windows import _environment_block

    block = _environment_block({"z_key": "last", "A_KEY": "first"})

    assert "".join(block) == "A_KEY=first\0z_key=last\0\0"


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
