"""Opt-in bounded phase diagnostics; no scheduling, polling, or content export."""

from __future__ import annotations

import json
import os
import platform
import sys
import threading
import time
from collections.abc import Callable
from concurrent.futures import Future
from functools import wraps
from pathlib import Path
from typing import Any, cast

import pytest

_PHASES = frozenset(
    {
        "observer.attached",
        "worker.completed",
        "callback.applied",
        "navigation.requested",
        "navigation.source",
        "navigation.applied",
        "confirmation.requested",
        "confirmation.resolved",
        "lease.requested",
        "lease.acquired",
        "lease.restored",
        "lease.hold_returned",
        "provider.injected",
        "provider.consumed",
        "summon.ready_applied",
        "summon.return_applied",
        "resource.closed",
        "attach.retired",
        "recorder.tripwire",
    }
)
_OUTCOMES = frozenset(
    {"started", "success", "error", "cancelled", "declined", "superseded", "truncated"}
)
_REQUIRED_TERMINALS = {
    "navigation": {"navigation.source", "navigation.applied"},
    "recovery": {
        "confirmation.resolved",
        "lease.acquired",
        "lease.restored",
        "lease.hold_returned",
        "provider.injected",
        "provider.consumed",
        "resource.closed",
        "attach.retired",
    },
}


class PhaseEvidence:
    """One test's synchronized, content-free JSONL sink with retained identities."""

    def __init__(
        self,
        path: Path,
        *,
        clock: Callable[[], float] = time.monotonic,
        max_records: int = 1024,
    ) -> None:
        if max_records < 1:
            raise ValueError("record limit must be positive")
        path.parent.mkdir(parents=True, exist_ok=True)
        self._stream = path.open("x", encoding="utf-8")
        self._clock = clock
        self._started = clock()
        self._lock = threading.Lock()
        self._owners: list[object] = []
        self._sequence = 0
        self._closed = False
        self._max_records = max_records
        self._records: list[dict[str, object]] = []
        self._published: set[tuple[int, str, int | None]] = set()
        self._aliases: list[tuple[object, int]] = []
        self._markers: list[bytes] = []

    def register_marker(self, marker: str) -> None:
        """Retain the fixture's exact marker privately before provider startup."""

        encoded = marker.encode("utf-8")
        if not encoded or len(encoded) > 256:
            raise ValueError("fixture marker must be between 1 and 256 bytes")
        with self._lock:
            if not self._closed and encoded not in self._markers:
                if len(self._markers) >= 128:
                    raise ValueError("too many fixture markers")
                self._markers.append(encoded)

    def marker_for(self, text: str) -> bytes | None:
        encoded = text.encode("utf-8")
        with self._lock:
            matches = [marker for marker in self._markers if marker in encoded]
            return matches[0] if len(matches) == 1 else None

    def now(self) -> float:
        """Capture transition time independently of serialized log-write order."""

        return self._clock()

    def bind(self, owner: object, request: object) -> None:
        """Bind a returned future to its already-recorded request entry."""

        with self._lock:
            if not self._closed and len(self._aliases) < self._max_records:
                self._aliases.append((owner, self._request(request)))

    def emit(
        self,
        owner: object,
        phase: str,
        outcome: str,
        *,
        generation: int | None = None,
        error: BaseException | None = None,
        source_dm_count: int | None = None,
        rendered_dm_count: int | None = None,
        once: bool = False,
        source: object | None = None,
        at: float | None = None,
    ) -> None:
        if phase not in _PHASES or outcome not in _OUTCOMES:
            raise ValueError("unknown diagnostic phase or outcome")
        with self._lock:
            if self._closed:
                return
            if self._sequence > self._max_records:
                return
            if self._sequence == self._max_records:
                owner = self
                phase, outcome = "recorder.tripwire", "truncated"
                generation = source_dm_count = rendered_dm_count = None
                error = None
            request = self._request(owner)
            key = (request, phase, generation)
            if once and key in self._published:
                return
            self._published.add(key)
            self._sequence += 1
            record: dict[str, object] = {
                "sequence": self._sequence,
                "request": request,
                "phase": phase,
                "outcome": outcome,
                "elapsed_s": round(
                    (self._clock() if at is None else at) - self._started, 6
                ),
            }
            record.update(_counts(generation, source_dm_count, rendered_dm_count))
            if error is not None:
                record["error_type"] = type(error).__name__[:96]
            if source is not None:
                record["source_request"] = self._request(source)
            self._stream.write(json.dumps(record, separators=(",", ":")) + "\n")
            self._stream.flush()
            self._records.append(record)

    def _request(self, owner: object) -> int:
        for item, request in self._aliases:
            if item is owner:
                return request
        for index, item in enumerate(self._owners, 1):
            if item is owner:
                return index
        self._owners.append(owner)
        return len(self._owners)

    def close(self, *, test_kind: str = "other") -> None:
        if test_kind not in {"other", "navigation", "recovery"}:
            raise ValueError("unknown diagnostic test kind")
        with self._lock:
            if not self._closed:
                missing = self._missing(test_kind)
                violations = _phase_violations(self._records, test_kind)
                if violations:
                    self._sequence += 1
                    self._stream.write(
                        json.dumps(
                            {
                                "sequence": self._sequence,
                                "request": self._request(self),
                                "phase": "recorder.tripwire",
                                "outcome": "error",
                                "elapsed_s": round(self._clock() - self._started, 6),
                                "violations": violations,
                            },
                            separators=(",", ":"),
                        )
                        + "\n"
                    )
                    missing.extend(violations)
                if any(row["outcome"] == "truncated" for row in self._records):
                    missing.append("recorder.capacity")
                self._sequence += 1
                summary = {
                    "sequence": self._sequence,
                    "request": 0,
                    "phase": "test.summary",
                    "outcome": "error" if missing else "success",
                    "elapsed_s": round(self._clock() - self._started, 6),
                    "test_kind": test_kind,
                    "complete": not missing,
                    "missing": missing,
                    "python_version": sys.version,
                    "platform": platform.platform(),
                }
                self._stream.write(json.dumps(summary, separators=(",", ":")) + "\n")
                self._closed = True
                self._owners.clear()
                self._records.clear()
                self._published.clear()
                self._aliases.clear()
                self._markers.clear()
                self._stream.close()

    def _missing(self, test_kind: str) -> list[str]:
        success = [row for row in self._records if row["outcome"] == "success"]
        if test_kind == "navigation":
            source = {
                row["request"]
                for row in success
                if row["phase"] == "navigation.source"
                and row.get("source_dm_count", 0) != 0
            }
            applied = {
                row["request"]
                for row in success
                if row["phase"] == "navigation.applied"
                and row.get("rendered_dm_count", 0) != 0
            }
            return [] if source & applied else ["navigation.dm_applied"]
        if test_kind == "recovery":
            return _missing_recovery(success)
        return []


def _missing_recovery(records: list[dict[str, object]]) -> list[str]:
    owners: dict[object, set[object]] = {}
    for row in records:
        owners.setdefault(row["request"], set()).add(row["phase"])
    lease = {"lease.acquired", "lease.restored", "lease.hold_returned"}
    provider = {"provider.injected", "provider.consumed", "resource.closed"}
    missing = []
    if not any(row["phase"] == "confirmation.resolved" for row in records):
        missing.append("confirmation.resolved")
    if not any(lease <= phases for phases in owners.values()):
        missing.append("lease.lifecycle")
    if sum(provider <= phases for phases in owners.values()) < 2:
        missing.append("provider.two_consumed_and_retired")
    if os.name == "nt" and not any(row["phase"] == "attach.retired" for row in records):
        missing.append("attach.retired")
    return missing


def _phase_violations(records: list[dict[str, object]], test_kind: str) -> list[str]:
    edges = {
        "navigation": (("navigation.source", "navigation.applied"),),
        "recovery": (
            ("lease.acquired", "lease.restored"),
            ("lease.restored", "lease.hold_returned"),
            ("provider.injected", "resource.closed"),
            ("provider.consumed", "resource.closed"),
        ),
    }.get(test_kind, ())
    observed: dict[object, dict[str, list[float]]] = {}
    phases = _REQUIRED_TERMINALS.get(test_kind, set())
    terminals: set[tuple[object, str]] = set()
    violations = set()
    for row in records:
        phase = str(row["phase"])
        if row["outcome"] == "started" or phase not in phases:
            continue
        key = (row["request"], phase)
        if key in terminals:
            violations.add("recorder.duplicate_terminal")
        terminals.add(key)
        if row["outcome"] == "success":
            observed.setdefault(row["request"], {}).setdefault(phase, []).append(
                cast(float, row["elapsed_s"])
            )
    for owner in observed.values():
        for before, after in edges:
            if (
                before in owner
                and after in owner
                and min(owner[before]) > min(owner[after])
            ):
                violations.add("recorder.phase_order")
    return sorted(violations)


def _counts(
    generation: int | None, source_dm_count: int | None, rendered_dm_count: int | None
) -> dict[str, int]:
    result = {}
    for key, value in (
        ("generation", generation),
        ("source_dm_count", source_dm_count),
        ("rendered_dm_count", rendered_dm_count),
    ):
        if value is not None:
            if type(value) is not int or value < 0:
                raise ValueError("diagnostic counts must be nonnegative integers")
            result[key] = value
    return result


def _future_result(future: Future[Any]) -> tuple[str, BaseException | None, Any]:
    if future.cancelled():
        return "cancelled", None, None
    error = future.exception()
    if error is not None:
        return "error", error, None
    return "success", None, future.result()


def _install_app_observers(patch: pytest.MonkeyPatch, evidence: PhaseEvidence) -> None:
    from taut_tui.app import TautApp
    from taut_tui.session import NavigationSnapshot

    original_watch = TautApp._watch_future
    original_navigation = TautApp._apply_navigation_result

    @wraps(original_watch)
    def watch(app: Any, future: Future[Any], apply: Callable[..., Any]) -> None:
        observation = object()
        evidence.emit(observation, "observer.attached", "started", source=future)

        def completed(done: Future[Any]) -> None:
            outcome, error, result = _future_result(done)
            evidence.emit(done, "worker.completed", outcome, error=error, once=True)
            if (
                isinstance(result, NavigationSnapshot)
                or getattr(apply, "__name__", "") == "_apply_navigation_result"
            ):
                evidence.emit(
                    done,
                    "navigation.source",
                    outcome,
                    error=error,
                    once=True,
                    source_dm_count=(
                        len(result.direct_messages)
                        if isinstance(result, NavigationSnapshot)
                        else None
                    ),
                )

        def applied(done: Future[Any]) -> Any:
            outcome, error, _result = _future_result(done)
            try:
                result = apply(done)
            except BaseException as exc:
                evidence.emit(
                    observation, "callback.applied", "error", error=exc, source=done
                )
                raise
            evidence.emit(
                observation, "callback.applied", outcome, error=error, source=done
            )
            return result

        future.add_done_callback(completed)
        original_watch(app, future, applied)

    @wraps(original_navigation)
    def navigation(app: Any, future: Future[Any]) -> None:
        outcome, error, snapshot = _future_result(future)
        try:
            original_navigation(app, future)
        except BaseException as exc:
            evidence.emit(future, "navigation.applied", "error", error=exc)
            raise
        rendered = (
            sum(
                thread.name in app._navigation_targets
                for thread in snapshot.direct_messages
            )
            if isinstance(snapshot, NavigationSnapshot)
            else None
        )
        evidence.emit(
            future,
            "navigation.applied",
            outcome,
            error=error,
            rendered_dm_count=rendered,
        )

    patch.setattr(TautApp, "_watch_future", watch)
    patch.setattr(TautApp, "_apply_navigation_result", navigation)


def _install_navigation_request(
    patch: pytest.MonkeyPatch, evidence: PhaseEvidence
) -> None:
    from taut_tui.session import TuiSession

    original = TuiSession.refresh_navigation

    @wraps(original)
    def requested(session: Any) -> Future[Any]:
        request = object()
        evidence.emit(request, "navigation.requested", "started")
        try:
            future = original(session)
        except BaseException as exc:
            evidence.emit(request, "navigation.source", "error", error=exc)
            raise
        evidence.bind(future, request)

        def completed(done: Future[Any]) -> None:
            outcome, error, result = _future_result(done)
            evidence.emit(
                done,
                "navigation.source",
                outcome,
                error=error,
                source_dm_count=len(result.direct_messages)
                if result is not None
                else None,
                once=True,
            )

        future.add_done_callback(completed)
        return future

    patch.setattr(TuiSession, "refresh_navigation", requested)


def _install_summon_application(
    patch: pytest.MonkeyPatch, evidence: PhaseEvidence
) -> None:
    from taut_tui.app import TautApp

    original_ready = TautApp._apply_summon_ready
    original_return = TautApp._apply_summon_return

    @wraps(original_ready)
    def ready(app: Any, run: Any) -> None:
        owned = run.token in app._owned_summon_tokens
        try:
            original_ready(app, run)
        except BaseException as exc:
            evidence.emit(run, "summon.ready_applied", "error", error=exc)
            raise
        evidence.emit(run, "summon.ready_applied", "success" if owned else "superseded")

    @wraps(original_return)
    def returned(app: Any, token: str, future: Future[Any]) -> None:
        outcome, error, _result = _future_result(future)
        try:
            original_return(app, token, future)
        except BaseException as exc:
            evidence.emit(future, "summon.return_applied", "error", error=exc)
            raise
        evidence.emit(future, "summon.return_applied", outcome, error=error)

    patch.setattr(TautApp, "_apply_summon_ready", ready)
    patch.setattr(TautApp, "_apply_summon_return", returned)


def install_phase_observers(
    patch: pytest.MonkeyPatch,
    evidence: PhaseEvidence,
    *,
    gate_module: Any = None,
) -> None:
    """Install delegating observers before the test initiates any operation."""

    _install_app_observers(patch, evidence)
    _install_navigation_request(patch, evidence)
    _install_summon_application(patch, evidence)
    _install_summon_observers(patch, evidence)
    _install_pty_observers(patch, evidence)
    if gate_module is not None:
        _install_fixture_markers(patch, evidence, gate_module)


def _install_fixture_markers(
    patch: pytest.MonkeyPatch, evidence: PhaseEvidence, module: Any
) -> None:
    def wrap(original: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(original)
        def registered(*args: Any, **kwargs: Any) -> Any:
            evidence.register_marker(kwargs["marker"])
            return original(*args, **kwargs)

        return registered

    for name in ("_wire_gate_member", "_prepare_gate_recovery"):
        original = getattr(module, name, None)
        if original is not None:
            patch.setattr(module, name, wrap(original))


def _install_summon_observers(
    patch: pytest.MonkeyPatch, evidence: PhaseEvidence
) -> None:
    from taut_tui.summon import TerminalAttachConfirmationRequest, TerminalLeaseRequest

    original_confirmation = TerminalAttachConfirmationRequest.__init__
    original_lease = TerminalLeaseRequest.__init__
    original_hold = TerminalLeaseRequest.hold

    def observe_event(request: Any, event: threading.Event, phase: str) -> None:
        original_set = event.set

        def completed() -> None:
            # The fields are committed before the wake. Another thread may
            # publish first after waking, so sequence is write order only.
            transition = evidence.now()
            original_set()
            outcome = "error" if request.error is not None else "success"
            if phase == "confirmation.resolved" and request.decision is False:
                outcome = "declined"
            evidence.emit(
                request, phase, outcome, error=request.error, once=True, at=transition
            )

        patch.setattr(event, "set", completed)

    @wraps(original_confirmation)
    def confirmation(request: Any, notice: Any) -> None:
        original_confirmation(request, notice)
        evidence.emit(request, "confirmation.requested", "started")
        observe_event(request, request.resolved, "confirmation.resolved")

    @wraps(original_lease)
    def lease(request: Any, bridge: Any = None) -> None:
        original_lease(request, bridge)
        evidence.emit(request, "lease.requested", "started")
        observe_event(request, request.acquired, "lease.acquired")
        observe_event(request, request.restored, "lease.restored")

    @wraps(original_hold)
    def hold(request: Any, app: Any) -> None:
        try:
            original_hold(request, app)
        except BaseException as exc:
            evidence.emit(request, "lease.hold_returned", "error", error=exc)
            raise
        evidence.emit(
            request,
            "lease.hold_returned",
            "error" if request.error is not None else "success",
            error=request.error,
        )

    patch.setattr(TerminalAttachConfirmationRequest, "__init__", confirmation)
    patch.setattr(TerminalLeaseRequest, "__init__", lease)
    patch.setattr(TerminalLeaseRequest, "hold", hold)


class EchoCapture:
    """Recognize the gate fixture's post-consumption echo on the existing reader."""

    def __init__(self, evidence: PhaseEvidence, owner: object, needle: bytes) -> None:
        self._evidence = evidence
        self._owner = owner
        self._needle = b" ".join(needle.split())
        self._buffer = b""
        self._complete = False
        self._lock = threading.Lock()
        if not needle or len(needle) > 8192:
            evidence.emit(owner, "recorder.tripwire", "truncated")
            self._complete = True
            self._needle = b""

    def feed(self, data: bytes) -> None:
        with self._lock:
            if self._complete:
                return
            self._buffer = (self._buffer + data.replace(b"\r", b""))[-32768:]
            while b"\nchat> " in self._buffer:
                frame, _, self._buffer = self._buffer.partition(b"\nchat> ")
                prefix = frame.find(b"\necho:")
                if prefix >= 0 and self._needle in b" ".join(
                    frame[prefix + 6 :].split()
                ):
                    self._complete = True
                    self._buffer = self._needle = b""
                    self._evidence.emit(self._owner, "provider.consumed", "success")
                    return


def _observe_retirement(
    patch: pytest.MonkeyPatch,
    evidence: PhaseEvidence,
    owner_class: type[Any],
    method: str,
    phase: str,
) -> None:
    original = getattr(owner_class, method)

    @wraps(original)
    def retired(owner: Any) -> Any:
        try:
            result = original(owner)
        except BaseException as exc:
            evidence.emit(owner, phase, "error", error=exc, once=True)
            raise
        evidence.emit(
            owner,
            phase,
            "error" if getattr(owner, "_close_error", None) else "success",
            once=True,
        )
        return result

    patch.setattr(owner_class, method, retired)


def _install_pty_observers(patch: pytest.MonkeyPatch, evidence: PhaseEvidence) -> None:
    from taut_summon._pty_windows import WindowsPtyHandle, _AttachSession
    from tests.helpers.terminal_probe import HostTerminal

    if os.name != "nt":
        from taut_summon._pty_posix import PosixPtyHandle

        _install_pty_handle(patch, evidence, PosixPtyHandle, windows=False)
    _install_pty_handle(patch, evidence, WindowsPtyHandle, windows=True)
    _observe_retirement(patch, evidence, HostTerminal, "close", "resource.closed")
    _observe_retirement(patch, evidence, _AttachSession, "_cleanup", "attach.retired")


def _install_pty_handle(
    patch: pytest.MonkeyPatch,
    evidence: PhaseEvidence,
    handle_class: type[Any],
    *,
    windows: bool,
) -> None:
    original_inject = handle_class.inject
    original_observe = handle_class._observe_output
    captures: dict[object, EchoCapture] = {}
    lock = threading.Lock()

    @wraps(original_inject)
    def inject(handle: Any, text: str) -> Any:
        marker = evidence.marker_for(text)
        if marker is not None:
            with lock:
                if len(captures) >= 128:
                    evidence.emit(handle, "recorder.tripwire", "truncated")
                else:
                    captures[handle] = EchoCapture(evidence, handle, marker)
        try:
            result = original_inject(handle, text)
        except BaseException as exc:
            evidence.emit(handle, "provider.injected", "error", error=exc)
            raise
        evidence.emit(handle, "provider.injected", "success")
        return result

    def observed(handle: Any, data: bytes) -> None:
        with lock:
            capture = captures.get(handle)
        if capture is not None:
            capture.feed(data)

    if windows:

        @wraps(original_observe)
        def windows_output(
            handle: Any, data: bytes, *, answer_queries: bool = True
        ) -> None:
            original_observe(handle, data, answer_queries=answer_queries)
            observed(handle, data)

        patch.setattr(handle_class, "_observe_output", windows_output)
    else:
        _install_posix_output(patch, handle_class, observed)
    patch.setattr(handle_class, "inject", inject)
    _observe_retirement(patch, evidence, handle_class, "close", "resource.closed")


def _install_posix_output(
    patch: pytest.MonkeyPatch,
    handle_class: type[Any],
    observed: Callable[[Any, bytes], None],
) -> None:
    original_init = handle_class.__init__

    @wraps(original_init)
    def initialized(handle: Any, *args: Any, **kwargs: Any) -> None:
        original_init(handle, *args, **kwargs)
        original_output = handle._terminal.observe_output

        @wraps(original_output)
        def output(data: bytes, *, answer_queries: bool = True) -> Any:
            result = original_output(data, answer_queries=answer_queries)
            observed(handle, data)
            return result

        # Both live POSIX paths call terminal state directly, not the handle's
        # convenience _observe_output method. Keep its reply result intact.
        patch.setattr(handle._terminal, "observe_output", output)

    patch.setattr(handle_class, "__init__", initialized)
