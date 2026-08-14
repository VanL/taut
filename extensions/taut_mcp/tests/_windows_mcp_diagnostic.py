"""Temporary Windows-only discriminator for the two flaky MCP test bodies.

This module is diagnostic scaffolding, not a retained test utility.  The two
target tests import :func:`phase`; outside a diagnostic child it is a no-op.
The child protocol deliberately uses acknowledged JSON lines so a missing
entered/returned transition is distinguishable from buffered diagnostics.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import queue
import signal
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import uuid
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from types import TracebackType
from typing import IO, Any, Literal, Self, cast

import psutil
from simplebroker._runner import SQLiteRunner

PROTOCOL = "taut-mcp-windows-diagnostic/v1"
OBSERVATION_SECONDS = 15.0
MISSING_PROGRESS_SECONDS = 60.0
DEFAULT_ABSOLUTE_CAP_SECONDS = 600.0
TESTS_DIR = Path(__file__).resolve().parent
EXTENSION_ROOT = TESTS_DIR.parent
PROJECT_ROOT = EXTENSION_ROOT.parents[1]

BodyKind = Literal["tools", "stdio"]
Lane = Literal["budget", "phase"]

_TARGETS: dict[BodyKind, tuple[str, str]] = {
    "tools": (
        "test_tools.py",
        "test_explicit_dm_read_log_and_directory_use_public_core_contract",
    ),
    "stdio": (
        "test_stdio_server.py",
        "test_modern_discovery_lazy_identity_and_subscription_share_one_server",
    ),
}

_ALLOWED_EVENTS = {
    "ready",
    "body_entered",
    "terminal_complete",
    "terminal_error",
    "phase_entered",
    "phase_returned",
    "phase_error",
    "sqlite_begin_entered",
    "sqlite_begin_returned",
    "sqlite_begin_error",
    "sqlite_commit_entered",
    "sqlite_commit_returned",
    "sqlite_commit_error",
    "sqlite_close_entered",
    "sqlite_close_returned",
    "sqlite_close_error",
    "mcp_create_entered",
    "mcp_create_returned",
    "mcp_create_error",
    "mcp_stop_entered",
    "mcp_stop_returned",
    "mcp_stop_error",
    "mcp_process_created",
    "mcp_process_stopped",
}

_AGGREGATE_ONLY_PHASES = {
    "tools.scenario",
    "stdio.scenario",
    "stdio.client.lifecycle",
    "stdio.client.listen.initial",
    "stdio.client.listen.resumed",
}


@dataclass
class _BodyState:
    body: BodyKind
    body_id: str
    iteration: int
    child_started: float
    local_phases: list[dict[str, object]] = field(default_factory=list)


class _ChildReporter:
    """Serialize child events and wait for the matching parent ACK."""

    def __init__(self, *, lane: Lane, body: BodyKind, run_id: str) -> None:
        self.lane = lane
        self.body = body
        self.run_id = run_id
        self._sequence = 0
        self._protocol_lock = threading.Lock()
        self._local_lock = threading.Lock()
        self._body_state: _BodyState | None = None

    @property
    def body_state(self) -> _BodyState:
        state = self._body_state
        if state is None:
            raise RuntimeError("diagnostic body is not active")
        return state

    def start_body(self, iteration: int) -> _BodyState:
        state = _BodyState(
            body=self.body,
            body_id=uuid.uuid4().hex,
            iteration=iteration,
            child_started=time.monotonic(),
        )
        self._body_state = state
        self.emit(
            "body_entered",
            operation_id=uuid.uuid4().hex,
            child_body_started=state.child_started,
        )
        return state

    def finish_body(self) -> list[dict[str, object]]:
        with self._local_lock:
            phases = list(self.body_state.local_phases)
        self._body_state = None
        return phases

    def emit(
        self,
        event: str,
        *,
        operation_id: str,
        **details: object,
    ) -> None:
        """Write one complete record and synchronously validate its ACK."""

        with self._protocol_lock:
            self._sequence += 1
            state = self._body_state
            record: dict[str, object] = {
                "protocol": PROTOCOL,
                "run_id": self.run_id,
                "lane": self.lane,
                "body": self.body,
                "body_id": (
                    state.body_id if state is not None else f"startup-{self.run_id}"
                ),
                "iteration": state.iteration if state is not None else -1,
                "operation_id": operation_id,
                "sequence": self._sequence,
                "event": event,
                "child_monotonic": time.monotonic(),
                "process_id": os.getpid(),
                "thread_name": threading.current_thread().name,
                "thread_native_id": threading.get_native_id(),
                **details,
            }
            sys.stdout.write(json.dumps(record, sort_keys=True) + "\n")
            sys.stdout.flush()
            ack_line = sys.stdin.readline()
            if not ack_line:
                raise RuntimeError(
                    f"parent closed ACK stream after diagnostic sequence {self._sequence}"
                )
            try:
                ack = json.loads(ack_line)
            except json.JSONDecodeError as exc:
                raise RuntimeError(
                    f"invalid diagnostic ACK JSON: {ack_line!r}"
                ) from exc
            expected = {
                "protocol": PROTOCOL,
                "run_id": self.run_id,
                "ack_sequence": self._sequence,
            }
            if ack != expected:
                raise RuntimeError(
                    f"wrong diagnostic ACK: expected {expected!r}, received {ack!r}"
                )

    @contextmanager
    def phase(self, label: str) -> Iterator[None]:
        """Record a macro phase without changing the wrapped operation."""

        operation_id = uuid.uuid4().hex
        entered = time.monotonic()
        if self.lane == "phase":
            self.emit(
                "phase_entered",
                operation_id=operation_id,
                label=label,
            )
        try:
            yield
        except BaseException as exc:
            errored = time.monotonic()
            if self.lane == "phase":
                self.emit(
                    "phase_error",
                    operation_id=operation_id,
                    label=label,
                    error_type=type(exc).__name__,
                    error=str(exc),
                )
            else:
                self._append_local_phase(
                    operation_id=operation_id,
                    label=label,
                    entered=entered,
                    finished=errored,
                    outcome="error",
                )
            raise
        else:
            returned = time.monotonic()
            if self.lane == "phase":
                self.emit(
                    "phase_returned",
                    operation_id=operation_id,
                    label=label,
                )
            else:
                self._append_local_phase(
                    operation_id=operation_id,
                    label=label,
                    entered=entered,
                    finished=returned,
                    outcome="returned",
                )

    def _append_local_phase(
        self,
        *,
        operation_id: str,
        label: str,
        entered: float,
        finished: float,
        outcome: str,
    ) -> None:
        with self._local_lock:
            self.body_state.local_phases.append(
                {
                    "operation_id": operation_id,
                    "label": label,
                    "entered": entered,
                    "finished": finished,
                    "outcome": outcome,
                }
            )


_ACTIVE_REPORTER: _ChildReporter | None = None


class _ExceptionCapture:
    """Capture an ordinary exception without hiding process cleanup."""

    def __init__(self) -> None:
        self.error: BaseException | None = None
        self.formatted = ""

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        exception_traceback: TracebackType | None,
    ) -> bool:
        if exception is None:
            return False
        self.error = exception
        self.formatted = "".join(
            traceback.format_exception(
                exception_type,
                exception,
                exception_traceback,
            )
        )
        return True


@contextmanager
def phase(label: str) -> Iterator[None]:
    """Instrument one exact-test macro phase when run by the diagnostic child."""

    reporter = _ACTIVE_REPORTER
    if reporter is None:
        yield
    else:
        with reporter.phase(label):
            yield


def _runner_details(runner: SQLiteRunner) -> dict[str, object]:
    owner = runner._transaction_owner
    return {
        "runner_id": f"sqlite-runner-{runner.instance_id}",
        "runner_database": str(runner._db_path),
        "runner_pid": runner._pid,
        "tracked_connections": len(runner._all_connections),
        "transaction_owner_name": None if owner is None else owner.name,
        "transaction_owner_ident": None if owner is None else owner.ident,
        "transaction_admitted_operations": runner._transaction_admitted_operations,
        "transaction_unusable_reason": runner._transaction_unusable_reason,
    }


@contextmanager
def _sqlite_observers(reporter: _ChildReporter) -> Iterator[None]:
    """Install transparent detailed-lane observers on real SQLite methods."""

    original_begin = SQLiteRunner.begin_immediate
    original_commit = SQLiteRunner.commit
    original_close = SQLiteRunner._close_tracked_connection

    def observed_begin(runner: SQLiteRunner) -> None:
        operation_id = uuid.uuid4().hex
        reporter.emit(
            "sqlite_begin_entered",
            operation_id=operation_id,
            **_runner_details(runner),
        )
        try:
            original_begin(runner)
        except BaseException as exc:
            reporter.emit(
                "sqlite_begin_error",
                operation_id=operation_id,
                error_type=type(exc).__name__,
                error=str(exc),
                **_runner_details(runner),
            )
            raise
        reporter.emit(
            "sqlite_begin_returned",
            operation_id=operation_id,
            **_runner_details(runner),
        )

    def observed_commit(runner: SQLiteRunner) -> None:
        operation_id = uuid.uuid4().hex
        reporter.emit(
            "sqlite_commit_entered",
            operation_id=operation_id,
            **_runner_details(runner),
        )
        try:
            original_commit(runner)
        except BaseException as exc:
            reporter.emit(
                "sqlite_commit_error",
                operation_id=operation_id,
                error_type=type(exc).__name__,
                error=str(exc),
                **_runner_details(runner),
            )
            raise
        reporter.emit(
            "sqlite_commit_returned",
            operation_id=operation_id,
            **_runner_details(runner),
        )

    def observed_close(
        runner: SQLiteRunner,
        connection: sqlite3.Connection,
    ) -> bool:
        operation_id = uuid.uuid4().hex
        reporter.emit(
            "sqlite_close_entered",
            operation_id=operation_id,
            **_runner_details(runner),
        )
        try:
            result = original_close(runner, connection)
        except BaseException as exc:
            reporter.emit(
                "sqlite_close_error",
                operation_id=operation_id,
                error_type=type(exc).__name__,
                error=str(exc),
                **_runner_details(runner),
            )
            raise
        reporter.emit(
            "sqlite_close_returned",
            operation_id=operation_id,
            close_result=result,
            **_runner_details(runner),
        )
        return result

    type.__setattr__(SQLiteRunner, "begin_immediate", observed_begin)
    type.__setattr__(SQLiteRunner, "commit", observed_commit)
    type.__setattr__(SQLiteRunner, "_close_tracked_connection", observed_close)
    try:
        yield
    finally:
        type.__setattr__(SQLiteRunner, "begin_immediate", original_begin)
        type.__setattr__(SQLiteRunner, "commit", original_commit)
        type.__setattr__(SQLiteRunner, "_close_tracked_connection", original_close)


def _process_identity(process_id: int) -> dict[str, object]:
    try:
        created = psutil.Process(process_id).create_time()
    except (psutil.Error, OSError):
        created = None
    return {"mcp_process_id": process_id, "mcp_process_create_time": created}


@contextmanager
def _mcp_process_observers(reporter: _ChildReporter) -> Iterator[None]:
    """Observe MCP server create/stop and expose descendants to parent cleanup."""

    import mcp.client.stdio as mcp_stdio

    original_create = mcp_stdio._create_platform_compatible_process
    original_stop = mcp_stdio._stop_server_process

    observed_create = _make_mcp_create_observer(
        reporter,
        original_create,
        original_stop,
    )
    observed_stop = _make_mcp_stop_observer(reporter, original_stop)

    mcp_stdio.__dict__["_create_platform_compatible_process"] = observed_create
    mcp_stdio.__dict__["_stop_server_process"] = observed_stop
    try:
        yield
    finally:
        mcp_stdio.__dict__["_create_platform_compatible_process"] = original_create
        mcp_stdio.__dict__["_stop_server_process"] = original_stop


def _make_mcp_create_observer(
    reporter: _ChildReporter,
    original_create: Callable[..., Awaitable[Any]],
    original_stop: Callable[[Any], Awaitable[None]],
) -> Callable[..., Awaitable[Any]]:
    async def observed_create(*args: Any, **kwargs: Any) -> Any:
        operation_id = uuid.uuid4().hex
        if reporter.lane == "phase":
            reporter.emit("mcp_create_entered", operation_id=operation_id)
        try:
            process = await original_create(*args, **kwargs)
        except Exception as exc:
            if reporter.lane == "phase":
                reporter.emit(
                    "mcp_create_error",
                    operation_id=operation_id,
                    error_type=type(exc).__name__,
                    error=str(exc),
                )
            raise
        details = _process_identity(process.pid)
        report = _ExceptionCapture()
        with report:
            if reporter.lane == "phase":
                reporter.emit(
                    "mcp_create_returned",
                    operation_id=operation_id,
                    process_control="created",
                    **details,
                )
            else:
                reporter.emit(
                    "mcp_process_created",
                    operation_id=operation_id,
                    process_control="created",
                    timing_evidence=False,
                    **details,
                )
        if report.error is not None:
            await original_stop(process)
            raise report.error
        return process

    return observed_create


def _make_mcp_stop_observer(
    reporter: _ChildReporter,
    original_stop: Callable[[Any], Awaitable[None]],
) -> Callable[[Any], Awaitable[None]]:
    async def observed_stop(process: Any) -> None:
        operation_id = uuid.uuid4().hex
        details = _process_identity(process.pid)
        entered = _ExceptionCapture()
        with entered:
            if reporter.lane == "phase":
                reporter.emit(
                    "mcp_stop_entered",
                    operation_id=operation_id,
                    **details,
                )
        if entered.error is not None:
            await original_stop(process)
            raise entered.error
        try:
            await original_stop(process)
        except Exception as exc:
            if reporter.lane == "phase":
                reporter.emit(
                    "mcp_stop_error",
                    operation_id=operation_id,
                    error_type=type(exc).__name__,
                    error=str(exc),
                    **details,
                )
            raise
        event = (
            "mcp_stop_returned" if reporter.lane == "phase" else "mcp_process_stopped"
        )
        reporter.emit(
            event,
            operation_id=operation_id,
            process_control="stopped",
            timing_evidence=reporter.lane == "phase",
            process_returncode=process.returncode,
            **details,
        )

    return observed_stop


def _load_target(body: BodyKind) -> Any:
    filename, function_name = _TARGETS[body]
    module_name = f"_taut_mcp_diagnostic_target_{body}_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(module_name, TESTS_DIR / filename)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load diagnostic target {filename}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return getattr(module, function_name)


def _run_child(*, lane: Lane, body: BodyKind, iterations: int, run_id: str) -> int:
    global _ACTIVE_REPORTER

    reporter = _ChildReporter(lane=lane, body=body, run_id=run_id)
    _ACTIVE_REPORTER = reporter
    target = _load_target(body)
    observer = _sqlite_observers(reporter) if lane == "phase" else _null_context()
    try:
        with observer, _mcp_process_observers(reporter):
            reporter.emit("ready", operation_id=uuid.uuid4().hex)
            for iteration in range(iterations):
                state = reporter.start_body(iteration)
                target_capture = _ExceptionCapture()
                with (
                    target_capture,
                    tempfile.TemporaryDirectory(
                        prefix=f"taut-mcp-{lane}-{body}-{iteration}-"
                    ) as raw_tmp,
                ):
                    target(Path(raw_tmp))
                if target_capture.error is not None:
                    phases = reporter.finish_body()
                    reporter._body_state = state
                    reporter.emit(
                        "terminal_error",
                        operation_id=uuid.uuid4().hex,
                        final=True,
                        error_type=type(target_capture.error).__name__,
                        error=str(target_capture.error),
                        traceback=target_capture.formatted,
                        child_body_finished=time.monotonic(),
                        local_phases=phases,
                    )
                    reporter._body_state = None
                    return 1
                phases = reporter.finish_body()
                reporter._body_state = state
                reporter.emit(
                    "terminal_complete",
                    operation_id=uuid.uuid4().hex,
                    final=iteration == iterations - 1,
                    child_body_finished=time.monotonic(),
                    local_phases=phases,
                )
                reporter._body_state = None
    finally:
        _ACTIVE_REPORTER = None
    return 0


@contextmanager
def _null_context() -> Iterator[None]:
    yield


@dataclass(frozen=True)
class _TrackedProcess:
    process_id: int
    create_time: float | None


@dataclass
class _Observation:
    body_id: str
    iteration: int
    parent_entered: float
    child_entered: float
    observed_active: bool = False


@dataclass
class _ProtocolState:
    run_id: str
    lane: Lane
    body: BodyKind
    iterations: int
    next_sequence: int = 1
    saw_ready: bool = False
    saw_final_complete: bool = False
    completed_iterations: int = 0
    active: _Observation | None = None
    tracked_mcp: set[_TrackedProcess] = field(default_factory=set)
    stopped_mcp: set[_TrackedProcess] = field(default_factory=set)
    open_operations: dict[str, tuple[str, str, float]] = field(default_factory=dict)
    operation_timings: dict[str, list[float]] = field(default_factory=dict)
    event_counts: dict[str, int] = field(default_factory=dict)
    last_record: dict[str, object] | None = None
    reports: list[dict[str, object]] = field(default_factory=list)


class _LineReader(threading.Thread):
    def __init__(self, stream: IO[str], destination: queue.Queue[object]) -> None:
        super().__init__(daemon=True)
        self._stream = stream
        self._destination = destination

    def run(self) -> None:
        try:
            for line in self._stream:
                self._destination.put(line)
        except (OSError, ValueError) as exc:
            self._destination.put(exc)
        finally:
            self._destination.put(_EOF)


_EOF = object()


def _read_stderr(stream: IO[str], destination: list[str]) -> None:
    destination.extend(stream)


def _start_child(
    *, lane: Lane, body: BodyKind, iterations: int, run_id: str
) -> tuple[
    subprocess.Popen[str],
    queue.Queue[object],
    _LineReader,
    threading.Thread,
    list[str],
]:
    command = [
        sys.executable,
        "-u",
        str(Path(__file__).resolve()),
        "--child",
        "--lane",
        lane,
        "--body",
        body,
        "--iterations",
        str(iterations),
        "--run-id",
        run_id,
    ]
    if os.name == "nt":
        process = subprocess.Popen(
            command,
            cwd=PROJECT_ROOT,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            creationflags=int(getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)),
        )
    else:
        process = subprocess.Popen(
            command,
            cwd=PROJECT_ROOT,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            start_new_session=True,
        )
    records: queue.Queue[object] = queue.Queue()
    stderr: list[str] = []
    stdout_reader: _LineReader | None = None
    stderr_reader: threading.Thread | None = None
    setup = _ExceptionCapture()
    with setup:
        if process.stdout is None or process.stderr is None:
            raise AssertionError("diagnostic child pipes were not created")
        stdout_reader = _LineReader(process.stdout, records)
        stderr_reader = threading.Thread(
            target=_read_stderr,
            args=(process.stderr, stderr),
            daemon=True,
        )
        stdout_reader.start()
        stderr_reader.start()
    if setup.error is not None:
        teardown = _ExceptionCapture()
        with teardown:
            _force_kill(process, set())
            process.wait(timeout=10)
        _close_endpoint(process.stdin)
        _close_endpoint(process.stdout)
        _close_endpoint(process.stderr)
        raise teardown.error or setup.error
    assert stdout_reader is not None
    assert stderr_reader is not None
    return process, records, stdout_reader, stderr_reader, stderr


def _validate_record(raw: object, state: _ProtocolState) -> dict[str, object]:
    if not isinstance(raw, str):
        if isinstance(raw, BaseException):
            raise raw
        if raw is _EOF:
            raise EOFError("diagnostic child reached EOF before final completion")
        raise TypeError(f"unexpected diagnostic queue item: {raw!r}")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise AssertionError(
            f"diagnostic child emitted non-JSON stdout: {raw!r}"
        ) from exc
    if not isinstance(parsed, dict):
        raise TypeError(f"diagnostic child emitted non-object JSON: {parsed!r}")
    required = {
        "protocol": PROTOCOL,
        "run_id": state.run_id,
        "lane": state.lane,
        "body": state.body,
        "sequence": state.next_sequence,
    }
    wrong = {
        key: (value, parsed.get(key))
        for key, value in required.items()
        if parsed.get(key) != value
    }
    if wrong:
        raise AssertionError(
            f"diagnostic protocol mismatch: {wrong!r}; record={parsed!r}"
        )
    for key in ("body_id", "operation_id", "iteration", "event"):
        if key not in parsed:
            raise AssertionError(f"diagnostic record missing {key}: {parsed!r}")
    if parsed["event"] not in _ALLOWED_EVENTS:
        raise AssertionError(f"unknown diagnostic event: {parsed!r}")
    state.next_sequence += 1
    return cast(dict[str, object], parsed)


def _ack(process: subprocess.Popen[str], state: _ProtocolState, sequence: int) -> None:
    if process.stdin is None:
        raise AssertionError("diagnostic child ACK endpoint is absent")
    ack = {
        "protocol": PROTOCOL,
        "run_id": state.run_id,
        "ack_sequence": sequence,
    }
    try:
        process.stdin.write(json.dumps(ack, sort_keys=True) + "\n")
        process.stdin.flush()
    except (BrokenPipeError, OSError) as exc:
        raise AssertionError(
            f"diagnostic child closed before ACK sequence {sequence}"
        ) from exc


def _record_process_control(record: dict[str, object], state: _ProtocolState) -> None:
    control = record.get("process_control")
    if control is None:
        return
    process_id = record.get("mcp_process_id")
    create_time = record.get("mcp_process_create_time")
    if not isinstance(process_id, int):
        raise TypeError(f"MCP process record lacks integer pid: {record!r}")
    if create_time is not None and not isinstance(create_time, (float, int)):
        raise TypeError(f"MCP process record has invalid create time: {record!r}")
    tracked = _TrackedProcess(
        process_id=process_id,
        create_time=None if create_time is None else float(create_time),
    )
    if control == "created":
        if tracked in state.tracked_mcp:
            raise AssertionError(f"duplicate MCP process creation record: {record!r}")
        state.tracked_mcp.add(tracked)
    elif control == "stopped":
        if tracked not in state.tracked_mcp:
            raise AssertionError(f"MCP stop preceded creation record: {record!r}")
        state.stopped_mcp.add(tracked)
    else:
        raise AssertionError(f"unknown MCP process control {control!r}")


def _record_operation(record: dict[str, object], state: _ProtocolState) -> None:
    event = str(record["event"])
    state.event_counts[event] = state.event_counts.get(event, 0) + 1
    state.last_record = record
    if state.lane != "phase":
        return
    if not event.startswith(("phase_", "sqlite_", "mcp_create_", "mcp_stop_")):
        return
    operation_id = str(record["operation_id"])
    if event.endswith("_entered"):
        if operation_id in state.open_operations:
            raise AssertionError(f"duplicate operation entry: {record!r}")
        label = str(record.get("label", event.removesuffix("_entered")))
        state.open_operations[operation_id] = (
            event,
            label,
            float(cast(float, record["child_monotonic"])),
        )
    elif event.endswith(("_returned", "_error")):
        if operation_id not in state.open_operations:
            if event == "terminal_error":
                return
            raise AssertionError(f"operation completed without entry: {record!r}")
        _, label, entered = state.open_operations.pop(operation_id)
        duration = float(cast(float, record["child_monotonic"])) - entered
        state.operation_timings.setdefault(label, []).append(duration)


def _handle_record(
    record: dict[str, object], state: _ProtocolState, now: float
) -> None:
    event = record["event"]
    _record_operation(record, state)
    if event == "ready":
        _handle_ready(record, state)
        return
    if not state.saw_ready:
        raise AssertionError(f"diagnostic body event arrived before ready: {record!r}")
    if event == "body_entered":
        _handle_body_entered(record, state, now)
        return
    if event in {"terminal_complete", "terminal_error"}:
        _handle_terminal(record, state, now)


def _handle_ready(record: dict[str, object], state: _ProtocolState) -> None:
    if state.saw_ready or state.active is not None:
        raise AssertionError(f"duplicate or late ready record: {record!r}")
    state.saw_ready = True


def _handle_body_entered(
    record: dict[str, object], state: _ProtocolState, now: float
) -> None:
    if state.active is not None:
        raise AssertionError(f"overlapping diagnostic bodies: {record!r}")
    state.active = _Observation(
        body_id=str(record["body_id"]),
        iteration=int(cast(int, record["iteration"])),
        parent_entered=now,
        child_entered=float(cast(float, record["child_body_started"])),
    )


def _summarize_local_phases(
    local_phases: list[object],
) -> dict[str, dict[str, object]]:
    timings: dict[str, list[float]] = {}
    outcomes: dict[str, set[str]] = {}
    for item in local_phases:
        if not isinstance(item, dict):
            continue
        label = item.get("label")
        entered = item.get("entered")
        finished = item.get("finished")
        if not isinstance(label, str) or not isinstance(entered, (float, int)):
            continue
        if not isinstance(finished, (float, int)):
            continue
        timings.setdefault(label, []).append(float(finished) - float(entered))
        outcomes.setdefault(label, set()).add(str(item.get("outcome")))
    return {
        label: {
            "count": len(durations),
            "total_seconds": round(sum(durations), 6),
            "max_seconds": round(max(durations), 6),
            "outcomes": sorted(outcomes[label]),
        }
        for label, durations in sorted(timings.items())
    }


def _budget_post_observation_progress(
    local_phases: list[object], active: _Observation
) -> list[str]:
    threshold = active.child_entered + OBSERVATION_SECONDS
    return sorted(
        str(item["label"])
        for item in local_phases
        if isinstance(item, dict)
        and item.get("label") not in _AGGREGATE_ONLY_PHASES
        and isinstance(item.get("label"), str)
        and isinstance(item.get("finished"), (float, int))
        and float(cast(float, item["finished"])) >= threshold
    )


def _handle_terminal(
    record: dict[str, object], state: _ProtocolState, now: float
) -> None:
    event = record["event"]
    active = state.active
    if active is None or active.body_id != record["body_id"]:
        raise AssertionError(f"terminal record has no matching body: {record!r}")
    if now - active.parent_entered >= OBSERVATION_SECONDS:
        active.observed_active = True
    local_phases = record.get("local_phases", [])
    if not isinstance(local_phases, list):
        raise TypeError(f"terminal record phases are not a list: {record!r}")
    post_observation_labels: list[str] = []
    if state.lane == "budget":
        post_observation_labels = _budget_post_observation_progress(
            cast(list[object], local_phases), active
        )
    state.reports.append(
        {
            "body": state.body,
            "iteration": active.iteration,
            "duration_seconds": round(now - active.parent_entered, 6),
            "active_at_15_seconds": active.observed_active,
            "post_observation_inner_progress": bool(post_observation_labels),
            "post_observation_inner_labels": post_observation_labels,
            "macro_phase_count": len(local_phases),
            "macro_phase_timings": _summarize_local_phases(
                cast(list[object], local_phases)
            ),
        }
    )
    state.active = None
    if event == "terminal_error":
        raise AssertionError(
            "diagnostic target failed:\n" + str(record.get("traceback", record))
        )
    state.completed_iterations += 1
    if record.get("final") is True:
        if state.completed_iterations != state.iterations:
            raise AssertionError(f"premature final completion: {record!r}")
        state.saw_final_complete = True


def _pid_matches(tracked: _TrackedProcess) -> bool:
    try:
        process = psutil.Process(tracked.process_id)
        if (
            tracked.create_time is not None
            and abs(process.create_time() - tracked.create_time) > 0.001
        ):
            return False
        return process.is_running() and process.status() != psutil.STATUS_ZOMBIE
    except (psutil.Error, OSError):
        return False


def _descendants(process_id: int) -> set[_TrackedProcess]:
    try:
        children = psutil.Process(process_id).children(recursive=True)
    except (psutil.Error, OSError):
        return set()
    found: set[_TrackedProcess] = set()
    for child in children:
        try:
            found.add(_TrackedProcess(child.pid, child.create_time()))
        except (psutil.Error, OSError):
            continue
    return found


def _is_windows() -> bool:
    return os.name == "nt"


def _force_kill(process: subprocess.Popen[str], tracked: set[_TrackedProcess]) -> None:
    driver_is_live = process.poll() is None
    all_tracked = {item for item in tracked if _pid_matches(item)}
    if driver_is_live:
        all_tracked |= _descendants(process.pid)
    if _is_windows():
        process_ids = [
            *([process.pid] if driver_is_live else []),
            *(item.process_id for item in all_tracked),
        ]
        for process_id in process_ids:
            subprocess.run(
                ["taskkill", "/PID", str(process_id), "/T", "/F"],
                capture_output=True,
                text=True,
                check=False,
            )
    else:
        driver = [_TrackedProcess(process.pid, None)] if driver_is_live else []
        for item in [*all_tracked, *driver]:
            if item.process_id != process.pid and not _pid_matches(item):
                continue
            try:
                os.killpg(item.process_id, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                continue


def _wait_reaped(tracked: set[_TrackedProcess], *, cap_seconds: float = 5.0) -> None:
    deadline = time.monotonic() + cap_seconds
    live = {item for item in tracked if _pid_matches(item)}
    while live and time.monotonic() < deadline:
        time.sleep(0.02)
        live = {item for item in live if _pid_matches(item)}
    if live:
        raise AssertionError(
            "diagnostic cleanup left live process identities: "
            + repr(sorted((item.process_id, item.create_time) for item in live))
        )


def _close_endpoint(endpoint: IO[str] | None) -> None:
    if endpoint is None:
        return
    try:
        endpoint.close()
    except OSError:
        pass


def _check_parent_deadlines(
    *,
    process: subprocess.Popen[str],
    state: _ProtocolState,
    now: float,
    progress_deadline: float,
    absolute_deadline: float,
    absolute_cap: float,
) -> None:
    if now >= absolute_deadline:
        raise AssertionError(
            f"diagnostic absolute cap expired after {absolute_cap:.1f}s"
        )
    if now >= progress_deadline:
        raise AssertionError(
            "diagnostic missing-progress cap expired after "
            f"{MISSING_PROGRESS_SECONDS:.1f}s; active={state.active!r}; "
            f"open_operations={state.open_operations!r}; "
            f"last_record={state.last_record!r}"
        )
    if process.poll() not in (None, 0):
        raise AssertionError(
            f"diagnostic child exited early with code {process.returncode}"
        )


def _next_parent_wait(
    state: _ProtocolState,
    *,
    now: float,
    progress_deadline: float,
    absolute_deadline: float,
) -> float:
    deadlines = [progress_deadline, absolute_deadline]
    if state.active is not None and not state.active.observed_active:
        deadlines.append(state.active.parent_entered + OBSERVATION_SECONDS)
    return max(0.001, min(deadlines) - now)


def _pump_parent_protocol(
    *,
    process: subprocess.Popen[str],
    records: queue.Queue[object],
    state: _ProtocolState,
    absolute_cap: float,
    absolute_deadline: float,
) -> None:
    started = time.monotonic()
    progress_deadline = started + MISSING_PROGRESS_SECONDS
    while not state.saw_final_complete:
        now = time.monotonic()
        if state.active is not None and (
            now - state.active.parent_entered >= OBSERVATION_SECONDS
        ):
            state.active.observed_active = True
        _check_parent_deadlines(
            process=process,
            state=state,
            now=now,
            progress_deadline=progress_deadline,
            absolute_deadline=absolute_deadline,
            absolute_cap=absolute_cap,
        )
        try:
            raw = records.get(
                timeout=_next_parent_wait(
                    state,
                    now=now,
                    progress_deadline=progress_deadline,
                    absolute_deadline=absolute_deadline,
                )
            )
        except queue.Empty:
            continue
        record = _validate_record(raw, state)
        # A created PID is cleanup authority even if the following ACK write
        # fails. Process control is intentionally not timing evidence.
        _record_process_control(record, state)
        _ack(process, state, int(cast(int, record["sequence"])))
        progress_deadline = time.monotonic() + MISSING_PROGRESS_SECONDS
        _handle_record(record, state, time.monotonic())


def _validate_parent_completion(
    process: subprocess.Popen[str], state: _ProtocolState
) -> None:
    if state.active is not None:
        raise AssertionError(f"final completion left active body: {state.active!r}")
    if state.open_operations:
        raise AssertionError(
            f"final completion left open operations: {state.open_operations!r}"
        )
    _close_endpoint(process.stdin)
    try:
        returncode = process.wait(timeout=10)
    except subprocess.TimeoutExpired as exc:
        raise AssertionError("diagnostic child did not exit after final ACK") from exc
    if returncode != 0:
        raise AssertionError(
            f"diagnostic child exited {returncode} after final completion"
        )
    if state.stopped_mcp != state.tracked_mcp:
        raise AssertionError(
            "not every created MCP process reported a stop: "
            f"created={sorted((item.process_id, item.create_time) for item in state.tracked_mcp)}, "
            f"stopped={sorted((item.process_id, item.create_time) for item in state.stopped_mcp)}"
        )


def _cleanup_parent_process(
    *,
    process: subprocess.Popen[str],
    tracked: set[_TrackedProcess],
    stdout_reader: threading.Thread,
    stderr_reader: threading.Thread,
    force: bool,
) -> None:
    cleanup = _ExceptionCapture()
    with cleanup:
        if force or process.poll() is None:
            _force_kill(process, tracked)
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired as exc:
            raise AssertionError(
                "diagnostic child survived process-tree termination"
            ) from exc
    _close_endpoint(process.stdin)
    _close_endpoint(process.stdout)
    _close_endpoint(process.stderr)
    stdout_reader.join(timeout=2)
    stderr_reader.join(timeout=2)
    if cleanup.error is not None:
        raise cleanup.error
    _wait_reaped(tracked)


def _run_one_parent(
    *,
    lane: Lane,
    body: BodyKind,
    iterations: int,
    absolute_cap: float,
    absolute_deadline: float,
) -> dict[str, object]:
    run_id = uuid.uuid4().hex
    state = _ProtocolState(
        run_id=run_id,
        lane=lane,
        body=body,
        iterations=iterations,
    )
    process, records, stdout_reader, stderr_reader, stderr = _start_child(
        lane=lane,
        body=body,
        iterations=iterations,
        run_id=run_id,
    )
    execution = _ExceptionCapture()
    with execution:
        _pump_parent_protocol(
            process=process,
            records=records,
            state=state,
            absolute_cap=absolute_cap,
            absolute_deadline=absolute_deadline,
        )
        _validate_parent_completion(process, state)
    tracked = state.tracked_mcp | _descendants(process.pid)
    cleanup = _ExceptionCapture()
    with cleanup:
        _cleanup_parent_process(
            process=process,
            tracked=tracked,
            stdout_reader=stdout_reader,
            stderr_reader=stderr_reader,
            force=execution.error is not None,
        )
    failure = execution.error or cleanup.error
    if failure is not None:
        stderr_text = "".join(stderr)
        if isinstance(failure, (KeyboardInterrupt, SystemExit)):
            raise failure
        raise AssertionError(f"{failure}\nchild stderr:\n{stderr_text}") from failure
    operation_timings = {
        label: {
            "count": len(durations),
            "total_seconds": round(sum(durations), 6),
            "max_seconds": round(max(durations), 6),
        }
        for label, durations in sorted(state.operation_timings.items())
    }
    return {
        "protocol": PROTOCOL,
        "lane": lane,
        "body": body,
        "iterations": iterations,
        "records": state.next_sequence - 1,
        "mcp_processes": len(state.tracked_mcp),
        "event_counts": dict(sorted(state.event_counts.items())),
        "operation_timings": operation_timings,
        "bodies": state.reports,
        "aggregate_progress_evidence": _aggregate_progress_evidence(state.reports),
    }


def _aggregate_progress_evidence(reports: list[dict[str, object]]) -> bool:
    """Accept only one budget body that crossed 15s and then made inner progress."""

    return any(
        report["active_at_15_seconds"] is True
        and report["post_observation_inner_progress"] is True
        for report in reports
    )


def run_diagnostic(*, lane: Lane, iterations: int) -> list[dict[str, object]]:
    """Run both exact bodies under a bounded, process-isolated diagnostic."""

    if iterations < 1:
        raise ValueError("diagnostic iterations must be positive")
    absolute_cap = float(
        os.environ.get(
            "TAUT_MCP_DIAGNOSTIC_ABSOLUTE_CAP_SECONDS",
            DEFAULT_ABSOLUTE_CAP_SECONDS,
        )
    )
    if absolute_cap <= MISSING_PROGRESS_SECONDS:
        raise ValueError(
            "diagnostic absolute cap must exceed the 60-second missing-progress cap"
        )
    absolute_deadline = time.monotonic() + absolute_cap
    reports: list[dict[str, object]] = []
    bodies: tuple[BodyKind, ...] = ("tools", "stdio")
    for body in bodies:
        reports.append(
            _run_one_parent(
                lane=lane,
                body=body,
                iterations=iterations,
                absolute_cap=absolute_cap,
                absolute_deadline=absolute_deadline,
            )
        )
    return reports


def _parse_child_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--child", action="store_true", required=True)
    parser.add_argument("--lane", choices=("budget", "phase"), required=True)
    parser.add_argument("--body", choices=("tools", "stdio"), required=True)
    parser.add_argument("--iterations", type=int, required=True)
    parser.add_argument("--run-id", required=True)
    return parser.parse_args(argv)


def _main(argv: list[str]) -> int:
    args = _parse_child_args(argv)
    if args.iterations < 1:
        raise ValueError("diagnostic iterations must be positive")
    return _run_child(
        lane=cast(Lane, args.lane),
        body=cast(BodyKind, args.body),
        iterations=args.iterations,
        run_id=args.run_id,
    )


if __name__ == "__main__":
    # The loaded exact tests import this module by name.  Reuse the executing
    # module so their phase() calls see the active reporter rather than a second
    # module instance with a separate global.
    sys.modules["_windows_mcp_diagnostic"] = sys.modules[__name__]
    raise SystemExit(_main(sys.argv[1:]))
