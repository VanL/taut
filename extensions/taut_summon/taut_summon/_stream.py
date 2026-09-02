"""Shared stream-json child-process plumbing for provider handles.

Both shipped adapters ([SUM-7.2]) supervise a real child process speaking
claude-style stream-json over pipes; only the output translation differs.
``StreamJsonHandle`` owns the [SUM-7.1] contract mechanics once:

- ``inject`` writes one user-role event and **flushes**, raising
  ``AdapterError`` synchronously on failure ([SUM-5.4] at-least-once to
  the process boundary depends on it). Injectors are serialized by a
  dedicated lock — deliberately not the lifecycle lock, so a blocked
  inject stays interruptible.
- ``interrupt`` is reusable cancellation. ``request_close`` publishes
  permanent retirement and sends its one graceful signal without waiting.
  ``close`` owns bounded escalation, reap, and pipe release without repeating
  the graceful signal.
- ``events`` is single-consumer, translates each stdout line through the
  subclass's ``_parse_line``, and ends with exactly one ``ExitEvent`` after
  terminal leader status is observed. The domain retains the waitable leader
  until whole-domain finalization. The ``AdapterEvent`` union is closed:
  a subclass either translates a line into one of its members, skips it
  with a warning when the provider emitted a shape it does not know, or
  raises ``AdapterError`` when a known event is malformed.

Spec references:
- docs/specs/04-summon.md [SUM-7.1], [SUM-5.4]
"""

from __future__ import annotations

import codecs
import json
import os
import select
import signal
import sys
import threading
from abc import ABC, abstractmethod
from collections.abc import Iterator
from typing import Any, Protocol

from taut_summon._adapter import (
    AdapterError,
    AdapterEvent,
    ExitEvent,
    SessionEvent,
)
from taut_summon._process_domain import ProcessDomain, ProcessIO

_RAW_READ_CHUNK_BYTES = 65_536
_RAW_READ_TURN_BYTES = 1_048_576
_RAW_READ_TURN_READS = 16


class _Utf8LineFramer:
    def __init__(self) -> None:
        self._decoder = codecs.getincrementaldecoder("utf-8")("strict")
        self._buffered = ""

    def feed(self, chunk: bytes) -> list[str]:
        self._buffered += self._decoder.decode(chunk, final=False)
        lines: list[str] = []
        while "\n" in self._buffered:
            line, self._buffered = self._buffered.split("\n", 1)
            lines.append(line)
        return lines

    def finish(self) -> list[str]:
        self._buffered += self._decoder.decode(b"", final=True)
        if not self._buffered:
            return []
        final_line = self._buffered
        self._buffered = ""
        return [final_line]


class _Utf8Lines(Protocol):
    def read_available(self) -> tuple[list[str], bool]: ...

    def finish(self) -> list[str]: ...

    def wait(self) -> None: ...

    def close(self) -> None: ...


class _NonblockingUtf8Lines:
    """Own one nonblocking POSIX stdout lease and framing state."""

    def __init__(self, stdout_fd: int) -> None:
        fd: int | None = None
        try:
            fd = os.dup(stdout_fd)
            os.set_blocking(fd, False)
        except OSError as exc:
            if fd is not None:
                try:
                    os.close(fd)
                except OSError:
                    pass
            raise AdapterError(f"provider stdout lease failed: {exc}") from exc
        self._fd = fd
        self._framer = _Utf8LineFramer()

    def read_available(self) -> tuple[list[str], bool]:
        lines: list[str] = []
        eof = False
        remaining_bytes = _RAW_READ_TURN_BYTES
        for _ in range(_RAW_READ_TURN_READS):
            try:
                chunk = os.read(
                    self._fd,
                    min(_RAW_READ_CHUNK_BYTES, remaining_bytes),
                )
            except BlockingIOError:
                break
            except OSError as exc:
                raise AdapterError(f"provider stdout read failed: {exc}") from exc
            if not chunk:
                eof = True
                break
            lines.extend(self._framer.feed(chunk))
            remaining_bytes -= len(chunk)
            if remaining_bytes == 0:
                break
        return lines, eof

    def finish(self) -> list[str]:
        return self._framer.finish()

    def wait(self) -> None:
        try:
            select.select([self._fd], [], [], 0.05)
        except (OSError, ValueError) as exc:
            raise AdapterError(f"provider stdout wait failed: {exc}") from exc

    def close(self) -> None:
        try:
            os.close(self._fd)
        except OSError:
            pass


class _WindowsUtf8Lines:
    """Own one Windows stdout lease observed through ``PeekNamedPipe``."""

    def __init__(self, stdout_fd: int) -> None:
        from taut_summon._win32_pipe import WindowsPipeReadiness

        fd: int | None = None
        try:
            fd = os.dup(stdout_fd)
            readiness = WindowsPipeReadiness.from_fd(fd)
        except (AdapterError, OSError) as exc:
            if fd is not None:
                try:
                    os.close(fd)
                except OSError:
                    pass
            raise AdapterError(f"provider stdout lease failed: {exc}") from exc
        self._fd = fd
        self._readiness = readiness
        self._framer = _Utf8LineFramer()

    def read_available(self) -> tuple[list[str], bool]:
        lines: list[str] = []
        try:
            for _ in range(_RAW_READ_TURN_READS):
                state = self._readiness.poll()
                if state.eof:
                    return lines, True
                if state.available == 0:
                    return lines, False
                chunk = os.read(
                    self._fd,
                    min(state.available, _RAW_READ_CHUNK_BYTES),
                )
                if not chunk:
                    return lines, True
                lines.extend(self._framer.feed(chunk))
        except OSError as exc:
            raise AdapterError(f"provider stdout read failed: {exc}") from exc
        return lines, False

    def finish(self) -> list[str]:
        return self._framer.finish()

    def wait(self) -> None:
        threading.Event().wait(0.05)

    def close(self) -> None:
        try:
            os.close(self._fd)
        except OSError:
            pass


class StreamJsonHandle(ABC):
    """A live stream-json harness child; satisfies ``AdapterHandle``."""

    def __init__(
        self,
        proc: ProcessIO,
        *,
        domain: ProcessDomain,
        session_id: str | None,
    ) -> None:
        self._proc = proc
        self._domain = domain
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
        self._write_epoch = 0
        self._write_waiting = threading.Event()
        self._stdin_fd: int | None = None
        stdin = proc.stdin
        if stdin is not None:
            try:
                stdin_fd = stdin.fileno()
                os.set_blocking(stdin_fd, False)
            except (AttributeError, OSError, ValueError):
                # Popen-shaped deterministic test doubles and older runtimes
                # without public pipe controls retain the buffered fallback.
                # Real pipe-cancellation tests capability-check this boundary.
                pass
            else:
                self._stdin_fd = stdin_fd

    @property
    def session_id(self) -> str | None:
        return self._session_id

    @property
    def pid(self) -> int:
        """Child pid — the [SUM-4] re-anchor evidence for the driver."""

        return self._proc.pid

    def inject(self, text: str) -> None:
        write_epoch = self._open_write_epoch()
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
        # lifecycle lock: a blocked inject must stay interruptible. The write
        # epoch publishes cancellation without waiting for the pipe or child
        # to make progress ([SUM-7.1]).
        with self._inject_lock:
            # A caller may have entered inject while another injector owned
            # the serialization gate.  Recheck after the wait so close's
            # published "closing" state is a hard no-new-delivery boundary.
            self._validate_write_epoch(write_epoch)
            if self._stdin_fd is not None:
                self._write_raw(line.encode("utf-8"), write_epoch)
                return
            try:
                stdin.write(line)
                stdin.flush()
            except (OSError, ValueError) as exc:
                # OSError covers the broken pipe of a dead/stalled-then-
                # stopped child; ValueError is a write on a closed file
                # object.
                raise AdapterError(f"inject failed: {exc}") from exc

    def _open_write_epoch(self) -> int:
        with self._lifecycle_lock:
            state = self._close_state
            if state != "open":
                raise AdapterError(f"provider child is {state}; inject refused")
            return self._write_epoch

    def _validate_write_epoch(self, write_epoch: int) -> None:
        with self._lifecycle_lock:
            state = self._close_state
            current_epoch = self._write_epoch
        if state != "open":
            raise AdapterError(f"provider child is {state}; inject refused")
        if write_epoch != current_epoch:
            raise AdapterError("provider pipe write interrupted")
        if self._domain.observe_leader_exit() is not None:
            raise AdapterError("provider child exited during inject")

    def _write_raw(self, payload: bytes, write_epoch: int) -> None:
        assert self._stdin_fd is not None
        try:
            fd = os.dup(self._stdin_fd)
        except OSError as exc:
            self._validate_write_epoch(write_epoch)
            raise AdapterError(f"inject pipe lease failed: {exc}") from exc
        offset = 0
        try:
            while offset < len(payload):
                self._validate_write_epoch(write_epoch)
                try:
                    written = os.write(fd, payload[offset:])
                except BlockingIOError:
                    written = None
                except OSError as exc:
                    self._validate_write_epoch(write_epoch)
                    raise AdapterError(f"inject failed: {exc}") from exc
                self._validate_write_epoch(write_epoch)
                if written is None:
                    self._write_waiting.set()
                    if sys.platform == "win32":  # pragma: no cover - Windows CI
                        threading.Event().wait(0.05)
                    else:
                        try:
                            select.select([], [fd], [], 0.05)
                        except (OSError, ValueError) as exc:
                            self._validate_write_epoch(write_epoch)
                            raise AdapterError(
                                f"inject pipe wait failed: {exc}"
                            ) from exc
                    continue
                if written <= 0:
                    raise AdapterError("inject wrote no bytes")
                offset += written
        finally:
            self._write_waiting.clear()
            try:
                os.close(fd)
            except OSError:
                pass

    def wait_until_quiet(self) -> None:
        """Structured streams need no terminal-output settle period."""

        return

    def mark_awaiting_onboarding(self) -> None:
        """Structured streams do not expose terminal onboarding state."""

        return

    @property
    def input_prompt_observed(self) -> bool:
        """Vacuously true: structured adapters have no terminal input prompt.

        The driver consults this only on ``orientation_via_inject`` adapters
        ([SUM-7.4]); structured streams receive the persona at spawn.
        """
        return True

    def output_tail(self) -> str:
        """Structured streams retain no raw screen tail ([SUM-7.4])."""

        return ""

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
            if self._close_state != "open":
                return
            self._write_epoch += 1
            self._send_interrupt()

    def request_close(self) -> None:
        with self._lifecycle_lock:
            if self._close_state != "open":
                return
            self._close_state = "close_requested"
            self._write_epoch += 1
            self._send_interrupt()

    def close(self) -> None:
        primary_error = sys.exception()
        self.request_close()
        owns_close = False
        with self._close_condition:
            if self._close_state == "closed":
                close_error = self._close_error
            elif self._close_state == "closing":
                self._close_condition.wait_for(lambda: self._close_state == "closed")
                close_error = self._close_error
            else:
                assert self._close_state == "close_requested"
                self._close_state = "closing"
                owns_close = True
                close_error = None

        if not owns_close:
            self._raise_close_error(close_error, primary_error)
            return

        failure: Exception | None = None
        try:
            self._domain.finalize()
        except AdapterError as exc:
            failure = exc
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
        try:
            self._domain.signal_leader(signal.SIGINT)
        except AdapterError:  # pragma: no cover - exit race remains best effort
            pass

    def _event_stream(self) -> Iterator[AdapterEvent]:
        stdout = self._proc.stdout
        if stdout is None:  # pragma: no cover - spawn always pipes stdout
            raise AdapterError("provider child has no stdout pipe")
        try:
            stdout_fd = stdout.fileno()
        except (AttributeError, OSError, ValueError):
            pass
        else:
            if os.name == "nt":  # pragma: no cover - blocking Windows CI
                yield from self._event_stream_reader(_WindowsUtf8Lines(stdout_fd))
            else:
                yield from self._event_stream_reader(_NonblockingUtf8Lines(stdout_fd))
            return
        yield from self._event_stream_text(stdout)

    def _event_stream_reader(self, reader: _Utf8Lines) -> Iterator[AdapterEvent]:
        """Decode complete provider frames without waiting for inherited EOF."""

        try:
            while True:
                lines, eof = reader.read_available()
                yield from self._events_from_lines(lines)
                returncode = self._domain.observe_leader_exit()
                if returncode is not None:
                    # Exit orders every leader write before this observation.
                    # Drain once more so a frame committed in that race is not
                    # lost, then stop even if a descendant retains the pipe.
                    final_lines, final_eof = reader.read_available()
                    yield from self._events_from_lines(final_lines)
                    # A descendant may still own the pipe and be partway
                    # through a line when the leader becomes terminal. Only
                    # EOF makes that buffered fragment a final frame; without
                    # EOF, the line protocol has not committed it.
                    if final_eof:
                        yield from self._events_from_lines(reader.finish())
                    yield ExitEvent(returncode=returncode)
                    return
                if eof:
                    returncode = self._domain.wait_for_leader_exit(5.0)
                    if returncode is None:
                        raise AdapterError("provider stdout closed before leader exit")
                    yield from self._events_from_lines(reader.finish())
                    yield ExitEvent(returncode=returncode)
                    return
                reader.wait()
        finally:
            reader.close()

    def _event_stream_text(self, stdout: Any) -> Iterator[AdapterEvent]:
        """Compatibility path for deterministic stream-shaped test doubles."""

        lines = iter(stdout)
        while True:
            try:
                line = next(lines)
            except StopIteration:
                break
            except ValueError as exc:
                with self._lifecycle_lock:
                    owned_close = (
                        type(exc) is ValueError
                        and str(exc) == "I/O operation on closed file."
                        and self._close_state != "open"
                        and stdout.closed
                    )
                if not owned_close:
                    raise
                break
            event = self._event_from_line(line)
            if event is not None:
                yield event
        returncode = self._domain.wait_for_leader_exit(5.0)
        if returncode is None:
            raise AdapterError("provider stdout closed before leader exit")
        yield ExitEvent(returncode=returncode)

    def _event_from_line(self, line: str) -> AdapterEvent | None:
        stripped = line.strip()
        if not stripped:
            return None
        event = self._parse_line(stripped)
        if isinstance(event, SessionEvent):
            self._session_id = event.session_id
        return event

    def _events_from_lines(self, lines: list[str]) -> Iterator[AdapterEvent]:
        for line in lines:
            event = self._event_from_line(line)
            if event is not None:
                yield event

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
        """Translate one stdout line; raise ``AdapterError`` on malformed known events."""
