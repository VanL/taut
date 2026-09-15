from __future__ import annotations

import json
import os
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol, cast

import psutil
import pytest
from taut_summon._adapter import AdapterError
from taut_summon._pty import _DetachChordMatcher

pytestmark = [
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


def _jsonl_entries(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _same_process(identity: tuple[int, float]) -> bool:
    try:
        process = psutil.Process(identity[0])
        return process.create_time() == identity[1] and process.is_running()
    except psutil.Error:
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


class _EpochRaceApi:
    def __init__(self) -> None:
        self.first_write_started = threading.Event()
        self.release_first_write = threading.Event()
        self.cancel_started = threading.Event()
        self.release_cancel = threading.Event()
        self.closed: list[int] = []
        self.writes: list[bytes] = []
        self.fail_cancel = False
        self._next_thread_handle = 90

    def open_current_thread(self) -> int:
        self._next_thread_handle += 1
        return self._next_thread_handle

    def close_handle(self, handle: int) -> None:
        self.closed.append(handle)

    def write(self, _handle: int, data: bytes) -> None:
        self.writes.append(data)
        if len(self.writes) == 1:
            self.first_write_started.set()
            assert self.release_first_write.wait(2.0)

    def cancel_thread(self, handle: int, *, retiring: bool) -> bool:
        from taut_summon._win32_io import ERROR_INVALID_HANDLE, Win32IoError

        del retiring
        assert handle not in self.closed
        if self.fail_cancel:
            raise Win32IoError("CancelSynchronousIo", ERROR_INVALID_HANDLE)
        self.cancel_started.set()
        assert self.release_cancel.wait(2.0)
        assert handle not in self.closed
        return True


def test_epoch_writer_keeps_active_thread_handle_live_during_cancel() -> None:
    from taut_summon._pty_windows import _EpochWriter

    api = _EpochRaceApi()
    writer = _EpochWriter(cast(Any, api), 41)
    write_errors: list[BaseException] = []
    interrupt_errors: list[BaseException] = []

    writing = threading.Thread(
        target=lambda: _blocked_epoch_write(writer, write_errors)
    )
    writing.start()
    assert api.first_write_started.wait(1.0)

    def run_interrupt() -> None:
        try:
            writer.interrupt()
        except AdapterError as exc:
            interrupt_errors.append(exc)

    interrupting = threading.Thread(target=run_interrupt)
    interrupting.start()
    assert api.cancel_started.wait(1.0)
    api.release_first_write.set()
    assert not _wait_until_true(lambda: 91 in api.closed, timeout=0.05)
    api.release_cancel.set()

    writing.join(1.0)
    interrupting.join(1.0)
    assert not writing.is_alive()
    assert not interrupting.is_alive()
    assert [str(error) for error in write_errors] == ["PTY write interrupted"]
    assert interrupt_errors == []
    assert api.closed.count(91) == 1
    assert api.writes[-1] == b"\x03"


def test_epoch_writer_skips_cancel_after_snapshotted_write_completes() -> None:
    from taut_summon._pty_windows import _EpochWriter

    api = _EpochRaceApi()
    writer = _EpochWriter(cast(Any, api), 41)
    write_errors: list[BaseException] = []
    original_cancel = writer._cancel_active

    def complete_then_cancel(active: object) -> None:
        api.release_first_write.set()
        assert _wait_until_true(lambda: 91 in api.closed)
        original_cancel(cast(Any, active))

    writer._cancel_active = complete_then_cancel  # type: ignore[method-assign]
    writing = threading.Thread(
        target=lambda: _blocked_epoch_write(writer, write_errors)
    )
    writing.start()
    assert api.first_write_started.wait(1.0)
    writer.interrupt()
    writing.join(1.0)
    assert not writing.is_alive()
    assert [str(error) for error in write_errors] == ["PTY write interrupted"]
    assert not api.cancel_started.is_set()
    assert api.writes == [b"x" * 1_000_000, b"\x03"]


def test_epoch_writer_cancel_failure_does_not_poison_later_write() -> None:
    from taut_summon._pty_windows import _ActiveWrite, _EpochWriter

    api = _EpochRaceApi()
    api.fail_cancel = True
    writer = _EpochWriter(cast(Any, api), 41)
    with writer._state:
        writer._active = _ActiveWrite(epoch=0, thread_handle=91)

    with pytest.raises(AdapterError, match="write cancellation failed"):
        writer.interrupt()

    with writer._state:
        writer._active = None
    api.release_first_write.set()
    writer.write(b"after")
    assert api.writes == [b"after"]


def test_epoch_writer_close_reports_cancellation_failure() -> None:
    from taut_summon._pty_windows import _ActiveWrite, _EpochWriter

    api = _EpochRaceApi()
    api.fail_cancel = True
    writer = _EpochWriter(cast(Any, api), 41)
    with writer._state:
        writer._active = _ActiveWrite(epoch=0, thread_handle=91)

    writer.request_close()
    with pytest.raises(AdapterError, match="write cancellation failed"):
        writer.finish_close_request()


def test_epoch_writer_inactivity_timeout_does_not_poison_later_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from taut_summon import _pty_windows
    from taut_summon._pty_windows import _ActiveWrite, _EpochWriter

    monkeypatch.setattr(_pty_windows, "_CLOSE_TIMEOUT_S", 0.01)
    api = _EpochRaceApi()
    api.release_cancel.set()
    writer = _EpochWriter(cast(Any, api), 41)
    with writer._state:
        writer._active = _ActiveWrite(epoch=0, thread_handle=91)

    with pytest.raises(AdapterError, match="did not stop after interrupt"):
        writer.interrupt()

    with writer._state:
        writer._active = None
    api.release_first_write.set()
    writer.write(b"after")
    assert api.writes == [b"after"]


def test_overlapping_interrupts_emit_only_the_current_epoch_signal() -> None:
    from taut_summon._pty_windows import _EpochWriter

    api = _EpochRaceApi()
    api.release_first_write.set()
    writer = _EpochWriter(cast(Any, api), 41)
    errors: list[AdapterError] = []
    writer._serializer.acquire()

    def interrupt() -> None:
        try:
            writer.interrupt()
        except AdapterError as exc:
            errors.append(exc)

    first = threading.Thread(target=interrupt)
    second = threading.Thread(target=interrupt)
    first.start()
    assert _wait_until_true(lambda: writer._epoch == 1)
    second.start()
    assert _wait_until_true(lambda: writer._epoch == 2)
    writer._serializer.release()
    first.join(1.0)
    second.join(1.0)
    assert not first.is_alive() and not second.is_alive()
    assert api.writes == [b"\x03"]
    assert [str(error) for error in errors] == ["PTY write interrupted"]


def test_close_supersedes_pending_reusable_interrupt() -> None:
    from taut_summon._pty_windows import _EpochWriter

    api = _EpochRaceApi()
    api.release_first_write.set()
    writer = _EpochWriter(cast(Any, api), 41)
    interrupt_errors: list[AdapterError] = []
    writer._serializer.acquire()

    def interrupt() -> None:
        try:
            writer.interrupt()
        except AdapterError as exc:
            interrupt_errors.append(exc)

    interrupted = threading.Thread(target=interrupt)
    interrupted.start()
    assert _wait_until_true(lambda: writer._epoch == 1)
    writer.request_close()
    assert _wait_until_true(lambda: writer._epoch == 2)
    writer._serializer.release()
    interrupted.join(1.0)
    writer.finish_close_request()
    assert not interrupted.is_alive()
    assert api.writes == [b"\x03"]
    assert [str(error) for error in interrupt_errors] == ["PTY write interrupted"]


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
@pytest.mark.windows_only
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
@pytest.mark.windows_only
def test_public_pty_adapter_allows_graceful_cleanup(
    tmp_path: Path,
) -> None:
    from taut_summon._adapter import ExitEvent
    from taut_summon._pty import PtyAdapter, PtySpec

    scenario = tmp_path / "scenario.json"
    received = tmp_path / "received.jsonl"
    scenario.write_text(json.dumps({"sigint_cleanup_seconds": 0.5}), encoding="utf-8")
    handle = PtyAdapter(
        PtySpec(
            name="windows-graceful-close",
            argv=(sys.executable, "-m", "taut_summon.scripted_provider"),
        )
    ).spawn(
        system_prompt="unused",
        env={
            "TAUT_SUMMON_SCENARIO": str(scenario),
            "TAUT_SUMMON_RECEIVED_LOG": str(received),
        },
    )
    events: list[object] = []
    pump = threading.Thread(target=lambda: events.extend(handle.events()))
    pump.start()
    provider_identity: tuple[int, float] | None = None
    try:
        assert _wait_until_true(
            lambda: any(
                entry.get("event") == "provider-ready"
                for entry in _jsonl_entries(received)
            )
        )
        start = next(
            entry for entry in _jsonl_entries(received) if entry.get("event") == "start"
        )
        provider = psutil.Process(int(start["pid"]))
        provider_identity = (provider.pid, provider.create_time())
        handle.request_close()
        handle.close()
        pump.join(10.0)
        assert not pump.is_alive()
        entries = _jsonl_entries(received)
        assert [
            entry["count"] for entry in entries if entry.get("event") == "signal"
        ] == [1]
        assert any(entry.get("event") == "first-signal-entered" for entry in entries)
        assert any(
            entry.get("event") == "cleanup-release"
            and entry.get("source") == "watchdog"
            for entry in entries
        )
        assert [
            event.returncode for event in events if isinstance(event, ExitEvent)
        ] == [0]
        assert _wait_until_true(
            lambda: not _same_process(provider_identity), timeout=5.0
        )
    finally:
        try:
            handle.close()
        finally:
            pump.join(10.0)
            if provider_identity is not None and _same_process(provider_identity):
                psutil.Process(provider_identity[0]).kill()


@pytest.mark.skipif(os.name != "nt", reason="requires Windows ConPTY")
@pytest.mark.windows_only
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
@pytest.mark.windows_only
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
@pytest.mark.windows_only
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
@pytest.mark.windows_only
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


class _AttachApi:
    """Fake native API for attach-cleanup proofs: one input read, then blocked."""

    def __init__(self, *, console: bool) -> None:
        self.console = console
        self.next_handle = iter((41, 42))
        self.closed: list[int | None] = []
        self.writes: list[tuple[int, bytes]] = []
        self.cancelled = threading.Event()
        self.read_calls = 0
        self.restore_failures = 0
        self.mode_calls: list[tuple[int, int]] = []

    def duplicate_fd_handle(self, _fd: int) -> int:
        return next(self.next_handle)

    def close_handle(self, handle: int | None) -> None:
        self.closed.append(handle)

    def open_current_thread(self) -> int:
        return 99

    def cancel_thread(self, _handle: int, *, retiring: bool) -> bool:
        del retiring
        self.cancelled.set()
        return True

    def read(self, _handle: int) -> bytes:
        from taut_summon._win32_io import ERROR_OPERATION_ABORTED, Win32IoError

        self.read_calls += 1
        if self.read_calls == 1:
            return b""
        self.cancelled.wait(10.0)
        raise Win32IoError("ReadFile", ERROR_OPERATION_ABORTED)

    def write(self, handle: int, data: bytes) -> None:
        self.writes.append((handle, data))

    def get_console_mode(self, handle: int) -> int:
        from taut_summon._win32_io import ERROR_INVALID_HANDLE, Win32IoError

        if not self.console:
            raise Win32IoError("GetConsoleMode", ERROR_INVALID_HANDLE)
        return 0x1F7 if handle == 41 else 0x003

    def set_console_mode(self, handle: int, value: int) -> None:
        self.mode_calls.append((handle, value))
        if value in (0x1F7, 0x003):
            self.restore_failures += 1
            raise AdapterError("injected console restore failure")

    def get_console_cp(self) -> int:
        return 437

    def set_console_cp(self, _value: int) -> None:
        return

    def get_console_output_cp(self) -> int:
        return 1252

    def set_console_output_cp(self, _value: int) -> None:
        return


class _AttachDrain:
    def __init__(self, *, unroute_error: str | None) -> None:
        self.sink: Any = None
        self.unroute_error = unroute_error

    def route(self, _generation: int, sink: object) -> None:
        self.sink = sink

    def unroute(self, _generation: int) -> object:
        if self.unroute_error is not None:
            raise AdapterError(self.unroute_error)
        return self.sink


def _attach_owner(api: _AttachApi, drain: _AttachDrain) -> Any:
    return type(
        "Owner",
        (),
        {
            "_api": api,
            "_attach_generation": 0,
            "_drain": drain,
            "_terminal": _Terminal(),
            "_exit_ready": threading.Event(),
        },
    )()


def _run_attach(api: _AttachApi, drain: _AttachDrain) -> None:
    from taut_summon._pty_windows import _AttachSession

    session = _AttachSession(
        _attach_owner(api, drain),
        wake=threading.Event(),
        shutdown=threading.Event(),
        input_fd=0,
        output_fd=1,
        detach_chord=b"xx",
    )
    try:
        session.run()
    finally:
        if drain.sink is not None and not drain.sink._done.is_set():
            drain.sink.retire(close_handle=False)


def test_attach_cleanup_survives_adapter_error_from_unroute() -> None:
    from taut_summon._pty_windows import _DETACH_RESET

    api = _AttachApi(console=False)
    drain = _AttachDrain(unroute_error="attach output generation changed")

    with pytest.raises(AdapterError, match="attach output generation changed"):
        _run_attach(api, drain)

    assert api.cancelled.is_set()
    assert (42, _DETACH_RESET) in api.writes
    assert api.closed.count(41) == 1
    assert api.closed.count(42) == 1


def test_attach_cleanup_closes_handles_after_console_restore_failure() -> None:
    from taut_summon._pty_windows import _DETACH_RESET

    api = _AttachApi(console=True)
    drain = _AttachDrain(unroute_error=None)

    with pytest.raises(AdapterError, match="console restoration failed"):
        _run_attach(api, drain)

    assert api.restore_failures == 2
    assert (42, _DETACH_RESET) in api.writes
    assert api.closed.count(41) == 1
    assert api.closed.count(42) == 1


class _HandleApi:
    """Fake native API for a ConPTY child that never exits after console close."""

    def __init__(
        self,
        *,
        fail_wait: bool = False,
        fail_exit_query: bool = False,
        fail_duplicate_close: bool = False,
    ) -> None:
        self.child_exits = threading.Event()
        self.pipe_closed = threading.Event()
        self.monitor_waiting = threading.Event()
        self.monitor_done = threading.Event()
        self.closed: list[int | None] = []
        self.close_attempts: list[int | None] = []
        self.writes: list[tuple[int, bytes]] = []
        self._active_waits: set[int] = set()
        self.fail_exit_query = fail_exit_query
        self.fail_duplicate_close = fail_duplicate_close
        self.fail_wait = fail_wait
        self.read_started = threading.Event()

    def duplicate_handle(self, handle: int) -> int:
        assert handle == 74
        return 75

    def require_bool(self, name: str, ok: object) -> None:
        if not ok:
            raise AssertionError(name)

    def WaitForSingleObject(self, handle: object, _timeout: int) -> int:
        from taut_summon._win32_io import WAIT_OBJECT_0

        value = cast(Any, handle).value
        assert value not in self.closed
        self._active_waits.add(value)
        self.monitor_waiting.set()
        self.child_exits.wait(10.0)
        self._active_waits.remove(value)
        if self.fail_wait:
            return 0xFFFFFFFF
        return WAIT_OBJECT_0

    def GetExitCodeProcess(self, handle: object, status: Any) -> bool:
        assert cast(Any, handle).value not in self.closed
        if self.fail_exit_query:
            raise AdapterError("exit query failed")
        status._obj.value = 0
        return True

    def ClosePseudoConsole(self, _hpcon: object) -> None:
        self.pipe_closed.set()

    def open_current_thread(self) -> int:
        return 99

    def close_handle(self, handle: int | None) -> None:
        self.close_attempts.append(handle)
        assert handle not in self._active_waits
        if handle == 75 and self.fail_duplicate_close:
            self.fail_duplicate_close = False
            self.monitor_done.set()
            raise AdapterError("duplicate close failed")
        self.closed.append(handle)
        if handle == 75:
            self.monitor_done.set()

    def write(self, handle: int, data: bytes) -> None:
        self.writes.append((handle, data))

    def cancel_thread(self, _handle: int, *, retiring: bool) -> bool:
        del retiring
        return True

    def read(self, _handle: int) -> bytes:
        from taut_summon._win32_io import ERROR_BROKEN_PIPE, Win32IoError

        self.read_started.set()
        self.pipe_closed.wait(10.0)
        raise Win32IoError("ReadFile", ERROR_BROKEN_PIPE)


def test_handle_constructor_retires_reply_writer_when_duplicate_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from taut_summon import _pty_windows
    from taut_summon._pty_windows import WindowsPtyHandle

    calls: list[str] = []

    class ReplyWriter:
        def __init__(self, _writer: object) -> None:
            calls.append("created")

        def start(self) -> None:
            calls.append("started")

        def request_close(self) -> None:
            calls.append("requested")

        def finish(self) -> None:
            calls.append("finished")

    class Api:
        def duplicate_handle(self, _handle: int) -> int:
            raise AdapterError("duplicate failed")

        def close_handle(self, handle: int | None) -> None:
            assert handle is None

    monkeypatch.setattr(_pty_windows, "_TerminalReplyWriter", ReplyWriter)
    with pytest.raises(AdapterError, match="duplicate failed"):
        WindowsPtyHandle(
            api=cast(Any, Api()),
            hpcon=71,
            input_write=72,
            output_read=73,
            process_handle=74,
            pid=4242,
            quiet_ms=10,
            max_settle_s=0.1,
            terminal=cast(Any, _Terminal()),
        )
    assert calls == ["created", "started", "requested", "finished"]


def test_handle_constructor_closes_monitor_duplicate_when_start_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from taut_summon import _pty_windows
    from taut_summon._pty_windows import WindowsPtyHandle

    reply_calls: list[str] = []
    closed: list[int | None] = []

    class ReplyWriter:
        def __init__(self, _writer: object) -> None:
            reply_calls.append("created")

        def start(self) -> None:
            reply_calls.append("started")

        def request_close(self) -> None:
            reply_calls.append("requested")

        def finish(self) -> None:
            reply_calls.append("finished")

    class MonitorThread:
        def __init__(self, **_kwargs: object) -> None:
            pass

        def start(self) -> None:
            raise RuntimeError("monitor start failed")

    class Api:
        def duplicate_handle(self, _handle: int) -> int:
            return 75

        def close_handle(self, handle: int | None) -> None:
            closed.append(handle)

    monkeypatch.setattr(_pty_windows, "_TerminalReplyWriter", ReplyWriter)
    monkeypatch.setattr(_pty_windows.threading, "Thread", MonitorThread)
    with pytest.raises(RuntimeError, match="monitor start failed"):
        WindowsPtyHandle(
            api=cast(Any, Api()),
            hpcon=71,
            input_write=72,
            output_read=73,
            process_handle=74,
            pid=4242,
            quiet_ms=10,
            max_settle_s=0.1,
            terminal=cast(Any, _Terminal()),
        )
    assert reply_calls == ["created", "started", "requested", "finished"]
    assert closed == [75]


def test_handle_constructor_keeps_start_failure_primary_when_retirement_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from taut_summon import _pty_windows
    from taut_summon._pty_windows import WindowsPtyHandle

    calls: list[str] = []
    closed: list[int | None] = []

    class ReplyWriter:
        def __init__(self, _writer: object) -> None:
            pass

        def start(self) -> None:
            pass

        def request_close(self) -> None:
            calls.append("requested")
            raise AdapterError("retirement failed")

        def finish(self) -> None:
            calls.append("finished")

    class MonitorThread:
        def __init__(self, **_kwargs: object) -> None:
            pass

        def start(self) -> None:
            raise RuntimeError("monitor start failed")

    class Api:
        def duplicate_handle(self, _handle: int) -> int:
            return 75

        def close_handle(self, handle: int | None) -> None:
            closed.append(handle)

    monkeypatch.setattr(_pty_windows, "_TerminalReplyWriter", ReplyWriter)
    monkeypatch.setattr(_pty_windows.threading, "Thread", MonitorThread)
    with pytest.raises(RuntimeError, match="monitor start failed") as caught:
        WindowsPtyHandle(
            api=cast(Any, Api()),
            hpcon=71,
            input_write=72,
            output_read=73,
            process_handle=74,
            pid=4242,
            quiet_ms=10,
            max_settle_s=0.1,
            terminal=cast(Any, _Terminal()),
        )
    assert calls == ["requested", "finished"]
    assert closed == [75]
    assert caught.value.__notes__ == [
        "partial ConPTY constructor cleanup failed: retirement failed"
    ]


def test_close_records_unexited_child_and_releases_handles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from taut_summon import _pty_windows
    from taut_summon._pty_windows import WindowsPtyHandle

    monkeypatch.setattr(_pty_windows, "_CLOSE_TIMEOUT_S", 0.2)
    monkeypatch.setattr(_pty_windows, "_GRACEFUL_TIMEOUT_S", 0.01)
    api = _HandleApi()
    handle = WindowsPtyHandle(
        api=cast(Any, api),
        hpcon=71,
        input_write=72,
        output_read=73,
        process_handle=74,
        pid=4242,
        quiet_ms=10,
        max_settle_s=0.1,
        terminal=cast(Any, _Terminal()),
    )
    try:
        assert api.monitor_waiting.wait(1.0)
        with pytest.raises(AdapterError, match="did not exit after terminal close"):
            handle.close()

        assert handle._close_state == "closed"
        assert {74, 72, 73} <= set(api.closed)
        assert 75 not in api.closed
        assert (72, b"\x03") in api.writes

        second: list[BaseException] = []

        def close_again() -> None:
            try:
                handle.close()
            except AdapterError as exc:
                second.append(exc)

        waiter = threading.Thread(target=close_again, daemon=True)
        waiter.start()
        waiter.join(2.0)
        assert not waiter.is_alive(), "second close() must not wait forever"
        assert second and "did not exit after terminal close" in str(second[0])
    finally:
        api.child_exits.set()
        assert api.monitor_done.wait(1.0)
        handle._exit_monitor.join(1.0)
        assert not handle._exit_monitor.is_alive()
        assert api.closed.count(75) == 1
        from taut_summon._adapter import ExitEvent

        assert [
            event.returncode
            for event in handle.events()
            if isinstance(event, ExitEvent)
        ] == [0]


@pytest.mark.parametrize(
    ("api", "message"),
    [
        (_HandleApi(fail_wait=True), "wait failed"),
        (_HandleApi(fail_exit_query=True), "exit query failed"),
        (_HandleApi(fail_duplicate_close=True), "duplicate close failed"),
    ],
)
def test_monitor_failure_releases_foreground_handles(
    monkeypatch: pytest.MonkeyPatch, api: _HandleApi, message: str
) -> None:
    from taut_summon import _pty_windows
    from taut_summon._pty_windows import WindowsPtyHandle

    monkeypatch.setattr(_pty_windows, "_GRACEFUL_TIMEOUT_S", 0.01)
    api.child_exits.set()
    handle = WindowsPtyHandle(
        api=cast(Any, api),
        hpcon=71,
        input_write=72,
        output_read=73,
        process_handle=74,
        pid=4242,
        quiet_ms=10,
        max_settle_s=0.1,
        terminal=cast(Any, _Terminal()),
    )
    with pytest.raises(AdapterError, match=message):
        handle.close()
    assert handle._close_state == "closed"
    assert {74, 72, 73} <= set(api.closed)
    assert api.monitor_done.is_set()
    assert api.close_attempts.count(75) == 1


def test_close_continues_cleanup_when_output_drain_start_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from taut_summon import _pty_windows
    from taut_summon._pty_windows import WindowsPtyHandle

    class FailingStartDrain:
        def __init__(self) -> None:
            self.starts = 0

        def start(self) -> None:
            self.starts += 1
            if self.starts == 1:
                raise RuntimeError("drain start failed")

        def join_after_close(self) -> None:
            pass

    monkeypatch.setattr(_pty_windows, "_GRACEFUL_TIMEOUT_S", 0.01)
    api = _HandleApi()
    api.child_exits.set()
    handle = WindowsPtyHandle(
        api=cast(Any, api),
        hpcon=71,
        input_write=72,
        output_read=73,
        process_handle=74,
        pid=4242,
        quiet_ms=10,
        max_settle_s=0.1,
        terminal=cast(Any, _Terminal()),
    )
    drain = FailingStartDrain()
    handle._drain = cast(Any, drain)
    with pytest.raises(AdapterError, match="drain start failed"):
        handle.close()
    assert drain.starts == 2
    assert {74, 72, 73, 75} <= set(api.closed)
    with pytest.raises(AdapterError, match="drain start failed"):
        handle.close()


def test_close_continues_finalization_after_graceful_write_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from taut_summon import _pty_windows
    from taut_summon._pty_windows import WindowsPtyHandle

    class FailingWriter:
        def request_close(self) -> None:
            pass

        def finish_close_request(self) -> None:
            raise AdapterError("write cancellation failed")

    monkeypatch.setattr(_pty_windows, "_GRACEFUL_TIMEOUT_S", 0.2)
    api = _HandleApi()
    api.child_exits.set()
    handle = WindowsPtyHandle(
        api=cast(Any, api),
        hpcon=71,
        input_write=72,
        output_read=73,
        process_handle=74,
        pid=4242,
        quiet_ms=10,
        max_settle_s=0.1,
        terminal=cast(Any, _Terminal()),
    )
    handle._writer = cast(Any, FailingWriter())
    with pytest.raises(AdapterError, match="write cancellation failed"):
        handle.close()
    assert {74, 72, 73, 75} <= set(api.closed)


def test_close_starts_drain_and_observes_graceful_exit_before_console_close(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from taut_summon import _pty_windows
    from taut_summon._pty_windows import WindowsPtyHandle

    class GracefulExitApi(_HandleApi):
        def write(self, handle: int, data: bytes) -> None:
            assert self.read_started.wait(1.0)
            super().write(handle, data)
            if data == b"\x03":
                self.child_exits.set()

        def ClosePseudoConsole(self, hpcon: object) -> None:
            assert self.monitor_done.wait(1.0)
            super().ClosePseudoConsole(hpcon)

    monkeypatch.setattr(_pty_windows, "_GRACEFUL_TIMEOUT_S", 0.2)
    api = GracefulExitApi()
    handle = WindowsPtyHandle(
        api=cast(Any, api),
        hpcon=71,
        input_write=72,
        output_read=73,
        process_handle=74,
        pid=4242,
        quiet_ms=10,
        max_settle_s=0.1,
        terminal=cast(Any, _Terminal()),
    )
    handle.close()
    assert handle._close_state == "closed"
    assert api.closed.count(75) == 1


@pytest.mark.parametrize("graceful_timeout", [0.0, 0.2])
def test_close_uses_configured_grace_before_forced_console_retirement(
    monkeypatch: pytest.MonkeyPatch, graceful_timeout: float
) -> None:
    from taut_summon import _pty_windows
    from taut_summon._pty_windows import WindowsPtyHandle

    class RecordingEvent(threading.Event):
        def __init__(self) -> None:
            super().__init__()
            self.waits: list[float | None] = []

        def wait(self, timeout: float | None = None) -> bool:
            self.waits.append(timeout)
            return False

    monkeypatch.setattr(_pty_windows, "_GRACEFUL_TIMEOUT_S", graceful_timeout)
    monkeypatch.setattr(_pty_windows, "_CLOSE_TIMEOUT_S", 0.01)
    api = _HandleApi()
    handle = WindowsPtyHandle(
        api=cast(Any, api),
        hpcon=71,
        input_write=72,
        output_read=73,
        process_handle=74,
        pid=4242,
        quiet_ms=10,
        max_settle_s=0.1,
        terminal=cast(Any, _Terminal()),
    )
    recorded = RecordingEvent()
    handle._exit_monitor_done = recorded
    try:
        with pytest.raises(AdapterError, match="did not exit after terminal close"):
            handle.close()
        assert recorded.waits[:2] == [graceful_timeout, 0.01]
        assert api.pipe_closed.is_set()
    finally:
        api.child_exits.set()
        handle._exit_monitor.join(1.0)


def test_concurrent_closers_observe_same_recorded_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from taut_summon import _pty_windows
    from taut_summon._pty_windows import WindowsPtyHandle

    monkeypatch.setattr(_pty_windows, "_CLOSE_TIMEOUT_S", 0.05)
    monkeypatch.setattr(_pty_windows, "_GRACEFUL_TIMEOUT_S", 0.01)
    api = _HandleApi()
    handle = WindowsPtyHandle(
        api=cast(Any, api),
        hpcon=71,
        input_write=72,
        output_read=73,
        process_handle=74,
        pid=4242,
        quiet_ms=10,
        max_settle_s=0.1,
        terminal=cast(Any, _Terminal()),
    )
    failures: list[str] = []

    def close() -> None:
        try:
            handle.close()
        except AdapterError as exc:
            failures.append(str(exc))

    first = threading.Thread(target=close)
    second = threading.Thread(target=close)
    first.start()
    assert api.pipe_closed.wait(1.0)
    second.start()
    first.join(1.0)
    second.join(1.0)
    try:
        assert not first.is_alive() and not second.is_alive()
        assert len(failures) == 2
        assert all("did not exit after terminal close" in item for item in failures)
        assert failures[0] == failures[1]
    finally:
        api.child_exits.set()
        handle._exit_monitor.join(1.0)
