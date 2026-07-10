"""Shared stream-json child-process plumbing for provider handles.

Both shipped adapters ([SUM-7.2]) supervise a real child process speaking
claude-style stream-json over pipes; only the output translation differs.
``StreamJsonHandle`` owns the [SUM-7.1] contract mechanics once:

- ``inject`` writes one user-role event and **flushes**, raising
  ``AdapterError`` synchronously on failure ([SUM-5.4] at-least-once to
  the process boundary depends on it). Injectors are serialized by a
  dedicated lock — deliberately not the lifecycle lock, so a blocked
  inject stays interruptible.
- ``interrupt``/``close`` are thread-safe; they stop the child (SIGINT,
  escalating to kill inside ``close``), which breaks the pipe and thereby
  unblocks any in-flight ``inject``.
- ``events`` is single-consumer, translates each stdout line through the
  subclass's ``_parse_line``, and ends with exactly one ``ExitEvent``
  after the child is reaped. Unknown stream shapes are rejected loudly —
  the ``AdapterEvent`` union is closed, and a quiet skip would hide
  protocol drift.

Spec references:
- docs/specs/04-summon.md [SUM-7.1], [SUM-5.4]
"""

from __future__ import annotations

import json
import signal
import subprocess
import sys
import threading
from abc import ABC, abstractmethod
from collections.abc import Iterator
from typing import Any

from taut_summon._adapter import (
    AdapterError,
    AdapterEvent,
    ExitEvent,
    SessionEvent,
)


class StreamJsonHandle(ABC):
    """A live stream-json harness child; satisfies ``AdapterHandle``."""

    def __init__(
        self,
        proc: subprocess.Popen[str],
        *,
        session_id: str | None,
    ) -> None:
        self._proc = proc
        self._session_id = session_id
        # A Python signal handler may call interrupt() reentrantly on the
        # main thread while close() is transitioning lifecycle state.  RLock
        # keeps that same-thread path bounded; normal injection remains on its
        # separate lock so interrupt can still break a blocked pipe write.
        self._lifecycle_lock = threading.RLock()
        self._events_lock = threading.Lock()
        self._inject_lock = threading.Lock()
        self._events_claimed = False
        self._close_condition = threading.Condition(self._lifecycle_lock)
        self._close_state = "open"
        self._close_error: str | None = None

    @property
    def session_id(self) -> str | None:
        return self._session_id

    @property
    def pid(self) -> int:
        """Child pid — the [SUM-4] re-anchor evidence for the driver."""

        return self._proc.pid

    def inject(self, text: str) -> None:
        self._require_open_for_inject()
        stdin = self._proc.stdin
        if stdin is None:  # pragma: no cover - spawn always pipes stdin
            raise AdapterError("provider child has no stdin pipe")
        payload = {
            "type": "user",
            "message": {
                "role": "user",
                "content": [{"type": "text", "text": text}],
            },
        }
        line = json.dumps(payload, separators=(",", ":")) + "\n"
        # Serialize injectors against each other so concurrent injects can
        # never interleave partial protocol lines. Deliberately NOT the
        # lifecycle lock: a blocked inject must stay interruptible —
        # interrupt()/close() kill the child, which breaks the pipe and
        # unblocks the writer ([SUM-7.1]).
        with self._inject_lock:
            # A caller may have entered inject while another injector owned
            # the serialization gate.  Recheck after the wait so close's
            # published "closing" state is a hard no-new-delivery boundary.
            self._require_open_for_inject()
            try:
                stdin.write(line)
                stdin.flush()
            except (OSError, ValueError) as exc:
                # OSError covers the broken pipe of a dead/stalled-then-
                # stopped child; ValueError is a write on a closed file
                # object.
                raise AdapterError(f"inject failed: {exc}") from exc

    def _require_open_for_inject(self) -> None:
        with self._lifecycle_lock:
            state = self._close_state
        if state != "open":
            raise AdapterError(f"provider child is {state}; inject refused")

    def wait_until_quiet(self) -> None:
        """Structured streams need no terminal-output settle period."""

        return None

    def mark_awaiting_onboarding(self) -> None:
        """Structured streams do not expose terminal onboarding state."""

        return None

    def attach(
        self,
        *,
        wake: threading.Event,
        shutdown: threading.Event,
        input_fd: int = 0,
        output_fd: int = 1,
        detach_chord: bytes = b"\x1c\x1c",
    ) -> str:
        del wake, shutdown, input_fd, output_fd, detach_chord
        raise AdapterError("structured provider does not support terminal attach")

    def events(self) -> Iterator[AdapterEvent]:
        with self._events_lock:
            if self._events_claimed:
                raise AdapterError(
                    "events() already has a consumer; the stream is single-consumer"
                )
            self._events_claimed = True
        return self._event_stream()

    def interrupt(self) -> None:
        with self._lifecycle_lock:
            if self._close_state == "closed":
                return
            self._send_interrupt()

    def close(self) -> None:
        primary_error = sys.exception()
        owns_close = False
        with self._close_condition:
            if self._close_state == "closed":
                close_error = self._close_error
            elif self._close_state == "closing":
                self._close_condition.wait_for(lambda: self._close_state == "closed")
                close_error = self._close_error
            else:
                self._close_state = "closing"
                owns_close = True
                close_error = None
                # Keep the state transition and first graceful signal atomic
                # with respect to concurrent close callers.  The RLock still
                # permits same-thread signal-handler reentry through interrupt.
                self._send_interrupt()

        if not owns_close:
            self._raise_close_error(close_error, primary_error)
            return

        failure: Exception | None = None
        try:
            if self._proc.poll() is None:
                try:
                    self._proc.wait(timeout=5.0)
                except subprocess.TimeoutExpired:
                    try:
                        self._proc.kill()
                        self._proc.wait(timeout=5.0)
                    except subprocess.TimeoutExpired as exc:
                        failure = AdapterError(
                            "provider child did not exit after SIGKILL"
                        )
                        failure.__cause__ = exc
                    except OSError as exc:
                        failure = AdapterError(f"provider child kill failed: {exc}")
                        failure.__cause__ = exc
        except OSError as exc:
            failure = AdapterError(f"provider child close failed: {exc}")
            failure.__cause__ = exc
        finally:
            for stream in (self._proc.stdin, self._proc.stdout):
                if stream is None:
                    continue
                try:
                    stream.close()
                except (OSError, ValueError):
                    # Closing stdin flushes; a dead child makes that a
                    # broken pipe, which is exactly what close() expects.
                    pass
            close_error = str(failure) if failure is not None else None
            with self._close_condition:
                self._close_error = close_error
                self._close_state = "closed"
                self._close_condition.notify_all()

        self._raise_close_error(close_error, primary_error)

    @staticmethod
    def _raise_close_error(
        close_error: str | None, primary_error: BaseException | None
    ) -> None:
        if close_error is None:
            return
        if primary_error is not None:
            primary_error.add_note(f"adapter cleanup also failed: {close_error}")
            return
        raise AdapterError(close_error)

    def status_fields(self) -> dict[str, str]:
        """Structured adapters have no adapter-specific STATUS fields."""

        return {}

    def _send_interrupt(self) -> None:
        if self._proc.poll() is not None:
            return
        try:
            if sys.platform == "win32":  # pragma: no cover - POSIX dev floor
                self._proc.terminate()
            else:
                self._proc.send_signal(signal.SIGINT)
        except (ProcessLookupError, OSError):  # pragma: no cover - exit race
            pass

    def _event_stream(self) -> Iterator[AdapterEvent]:
        stdout = self._proc.stdout
        if stdout is None:  # pragma: no cover - spawn always pipes stdout
            raise AdapterError("provider child has no stdout pipe")
        for line in stdout:
            stripped = line.strip()
            if not stripped:
                continue
            event = self._parse_line(stripped)
            if isinstance(event, SessionEvent):
                self._session_id = event.session_id
            yield event
        returncode = self._proc.wait()
        yield ExitEvent(returncode=returncode)

    def _decode_object(self, line: str) -> dict[str, Any]:
        """Parse one stdout line as a JSON object, loudly on any drift."""

        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise AdapterError(
                f"provider emitted a non-JSON line: {line[:200]!r}"
            ) from exc
        if not isinstance(payload, dict):
            raise AdapterError(f"provider event is not an object: {line[:200]!r}")
        return payload

    @abstractmethod
    def _parse_line(self, line: str) -> AdapterEvent:
        """Translate one stdout line; raise ``AdapterError`` on unknown shapes."""
