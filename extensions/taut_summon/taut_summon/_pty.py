"""Universal interactive PTY adapter ([SUM-7.4]).

The adapter hosts a harness in its normal full-screen interactive mode. It
does not parse the screen as speech; the master reader exists only for coarse
liveness, finite terminal-query replies, diagnostics, and clean lifecycle
ownership.
"""

from __future__ import annotations

import errno
import fcntl
import logging
import os
import pty
import queue
import select
import signal
import struct
import subprocess
import termios
import threading
import time
import tty
from collections.abc import Iterator, Mapping
from dataclasses import dataclass

from taut_summon._adapter import (
    ActivityEvent,
    AdapterError,
    AdapterEvent,
    ExitEvent,
)

logger = logging.getLogger("taut_summon.pty")

ESC = b"\x1b"
BEL = b"\x07"
ST = ESC + b"\\"

_DEFAULT_ROWS = 24
_DEFAULT_COLS = 80
_OUTPUT_ACTIVITY_WINDOW_SECONDS = 10.0
_DEFAULT_DETACH_CHORD = b"\x1c\x1c"
_TTY_RESET = (
    b"\x18"
    + ST
    + b"\x1b[?1049l\x1b[?47l\x1b[?1047l"
    + b"\x1b[?25h\x1b[r\x1b[0m\x1b[?7h\x1b[?2026l\x1b[?1007l"
    + b"\x1b[?1l\x1b>"
    + b"\x1b[?1004l"
    + b"\x1b[?1000l\x1b[?1002l\x1b[?1003l\x1b[?1005l"
    + b"\x1b[?1006l\x1b[?1015l"
    + b"\x1b[?2004l\x1b[<u"
)


@dataclass(frozen=True, slots=True)
class PtySpec:
    """One interactive harness launch shape."""

    name: str
    argv: tuple[str, ...]
    rows: int = _DEFAULT_ROWS
    cols: int = _DEFAULT_COLS
    stall_s: float = 10.0
    quiet_ms: int = 500
    max_settle_s: float = 10.0


class PtyAdapter:
    """Spawn an interactive harness on a pseudo-terminal."""

    supports_terminal_mode: bool = False
    supports_attach: bool = True
    orientation_via_inject: bool = True

    def __init__(self, spec: PtySpec | None = None) -> None:
        self._spec = spec or PtySpec(name="pty", argv=(os.environ.get("SHELL", "sh"),))
        self.name = self._spec.name

    @property
    def argv(self) -> tuple[str, ...]:
        return self._spec.argv

    def spawn(
        self,
        *,
        session_id: str | None,
        system_prompt: str,
        env: Mapping[str, str],
    ) -> PtyHandle:
        del session_id, system_prompt
        master_fd, slave_fd = pty.openpty()
        _set_winsize(slave_fd, self._spec.rows, self._spec.cols)
        child_env = dict(os.environ)
        child_env.update(env)
        child_env["TERM"] = "xterm-256color"
        child_env.setdefault("COLORTERM", "truecolor")
        try:
            proc = subprocess.Popen(
                list(self._spec.argv),
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                env=child_env,
                close_fds=True,
                start_new_session=True,
            )
        except OSError as exc:
            os.close(master_fd)
            os.close(slave_fd)
            raise AdapterError(f"failed to spawn PTY harness: {exc}") from exc
        finally:
            try:
                os.close(slave_fd)
            except OSError:
                pass
        return PtyHandle(
            proc,
            master_fd=master_fd,
            rows=self._spec.rows,
            cols=self._spec.cols,
            stall_s=self._spec.stall_s,
            quiet_ms=self._spec.quiet_ms,
            max_settle_s=self._spec.max_settle_s,
        )


class PtyHandle:
    """Live PTY child; satisfies ``AdapterHandle`` for [SUM-7.4]."""

    def __init__(
        self,
        proc: subprocess.Popen[bytes],
        *,
        master_fd: int,
        rows: int,
        cols: int,
        stall_s: float,
        quiet_ms: int,
        max_settle_s: float,
    ) -> None:
        self._proc = proc
        self._master_fd = master_fd
        self._rows = rows
        self._cols = cols
        self._stall_s = stall_s
        self._quiet_s = quiet_ms / 1000.0
        self._max_settle_s = max_settle_s
        self._responder = _TerminalResponder(rows=rows, cols=cols)
        self._lifecycle_lock = threading.Lock()
        self._events_lock = threading.Lock()
        self._inject_lock = threading.Lock()
        self._events_claimed = False
        self._interrupt_requested = threading.Event()
        self._reader_started = False
        self._reader_started_event = threading.Event()
        self._master_closed = False
        self._exit_emitted = False
        self._bracketed_paste = False
        self._last_output_ts = time.monotonic()
        self._awaiting_query: str | None = None
        self._awaiting_onboarding = False
        self._pending_events: queue.SimpleQueue[AdapterEvent] = queue.SimpleQueue()

    @property
    def session_id(self) -> str | None:
        return None

    @property
    def pid(self) -> int:
        return self._proc.pid

    @property
    def last_output_ts(self) -> float:
        return self._last_output_ts

    def mark_awaiting_onboarding(self) -> None:
        self._awaiting_onboarding = True

    def status_fields(self) -> dict[str, str]:
        fields: dict[str, str] = {}
        if self._awaiting_query is not None:
            fields["awaiting_query"] = self._awaiting_query
        if self._awaiting_onboarding:
            fields["awaiting_onboarding"] = "true"
        return fields

    def wait_until_quiet(self) -> None:
        self._reader_started_event.wait(timeout=self._max_settle_s)
        deadline = time.monotonic() + self._max_settle_s
        while time.monotonic() < deadline:
            if time.monotonic() - self._last_output_ts >= self._quiet_s:
                return
            time.sleep(0.05)

    def attach(
        self,
        *,
        wake: threading.Event,
        shutdown: threading.Event,
        input_fd: int = 0,
        output_fd: int = 1,
        detach_chord: bytes = _DEFAULT_DETACH_CHORD,
    ) -> str:
        """Bridge a human tty to the harness until detach, EOF, or shutdown."""

        saved = termios.tcgetattr(input_fd)
        tty.setraw(input_fd)
        done = threading.Event()
        pipe_r, pipe_w = os.pipe()

        def _forward_wake() -> None:
            try:
                while not done.is_set():
                    if wake.wait(timeout=0.05) or done.is_set():
                        try:
                            os.write(pipe_w, b"x")
                        except (BrokenPipeError, OSError):
                            pass
                        return
            finally:
                pass

        forwarder = threading.Thread(
            target=_forward_wake, daemon=True, name="taut-summon-attach-waker"
        )
        forwarder.start()
        matcher = _DetachChordMatcher(detach_chord)
        result = "eof"
        try:
            while True:
                ready, _, _ = select.select(
                    [input_fd, self._master_fd, pipe_r], [], [], 0.1
                )
                if pipe_r in ready:
                    if shutdown.is_set():
                        result = "shutdown"
                        break
                    os.read(pipe_r, 4096)
                if self._master_fd in ready:
                    try:
                        data = os.read(self._master_fd, 4096)
                    except BlockingIOError:
                        continue
                    except OSError:
                        result = "eof"
                        break
                    if not data:
                        result = "eof"
                        break
                    os.write(output_fd, data)
                if input_fd in ready:
                    data = os.read(input_fd, 4096)
                    if not data:
                        result = "eof"
                        break
                    forward, detached = matcher.feed(data)
                    if forward:
                        self._write_all(forward)
                    if detached:
                        result = "detached"
                        break
        finally:
            done.set()
            forwarder.join(timeout=1.0)
            for fd in (pipe_r, pipe_w):
                try:
                    os.close(fd)
                except OSError:
                    pass
            try:
                os.write(output_fd, _TTY_RESET)
            finally:
                termios.tcsetattr(input_fd, termios.TCSADRAIN, saved)
        return result

    def inject(self, text: str) -> None:
        sanitized = _sanitize_for_pty(text)
        if self._bracketed_paste:
            payload = ESC + b"[200~" + sanitized.encode() + ESC + b"[201~\r"
        else:
            payload = sanitized.replace("\n", " ").encode() + b"\r"
        with self._inject_lock:
            self._write_all(payload)
        self._pending_events.put(ActivityEvent(description="inject"))

    def events(self) -> Iterator[AdapterEvent]:
        with self._events_lock:
            if self._events_claimed:
                raise AdapterError(
                    "events() already has a consumer; the PTY stream is single-consumer"
                )
            self._events_claimed = True
        return self._event_stream()

    def interrupt(self) -> None:
        self._interrupt_requested.set()
        if not self._write_interrupt_best_effort():
            self._signal_process_group(signal.SIGTERM)

    def close(self) -> None:
        self._interrupt_requested.set()
        with self._lifecycle_lock:
            reader_started = self._reader_started
            master_closed = self._master_closed
        self._write_interrupt_best_effort()
        self._reap_child()
        if not reader_started:
            with self._lifecycle_lock:
                if not master_closed:
                    self._close_master_unlocked()

    def _event_stream(self) -> Iterator[AdapterEvent]:
        with self._lifecycle_lock:
            self._reader_started = True
            self._last_output_ts = time.monotonic()
            self._reader_started_event.set()
            if self._master_closed:
                yield from self._emit_exit()
                return
        self._pending_events.put(ActivityEvent(description="spawn"))
        last_activity = 0.0
        try:
            while True:
                yield from self._drain_pending()
                try:
                    ready, _, _ = select.select([self._master_fd], [], [], 0.05)
                except (OSError, ValueError):
                    break
                if not ready:
                    self._maybe_mark_stall()
                    if self._proc.poll() is not None:
                        break
                    continue
                try:
                    data = os.read(self._master_fd, 4096)
                except BlockingIOError:
                    continue
                except OSError:
                    break
                if not data:
                    break
                self._last_output_ts = time.monotonic()
                replies = self._responder.feed(data)
                self._bracketed_paste = self._responder.bracketed_paste
                for reply in replies:
                    self._write_best_effort(reply)
                now = time.monotonic()
                if now - last_activity >= _OUTPUT_ACTIVITY_WINDOW_SECONDS:
                    last_activity = now
                    yield ActivityEvent(description="output")
        finally:
            with self._lifecycle_lock:
                if not self._master_closed:
                    self._close_master_unlocked()
            yield from self._emit_exit()

    def _drain_pending(self) -> Iterator[AdapterEvent]:
        while True:
            try:
                yield self._pending_events.get_nowait()
            except queue.Empty:
                return

    def _maybe_mark_stall(self) -> None:
        outstanding = self._responder.outstanding_query
        if outstanding is None or self._awaiting_query is not None:
            return
        if time.monotonic() - self._last_output_ts >= self._stall_s:
            self._awaiting_query = outstanding
            logger.warning(
                "PTY harness is awaiting an unhandled terminal report query: %s",
                outstanding,
            )

    def _emit_exit(self) -> Iterator[AdapterEvent]:
        if self._exit_emitted:
            return
        self._exit_emitted = True
        if self._proc.poll() is None:
            self._reap_child()
        returncode = self._proc.returncode
        yield ExitEvent(returncode=0 if returncode is None else int(returncode))

    def _write_all(self, data: bytes) -> None:
        offset = 0
        original_flags: int | None = None
        fd: int | None = None
        try:
            with self._lifecycle_lock:
                if self._master_closed:
                    raise AdapterError("PTY master is closed")
                if self._interrupt_requested.is_set():
                    raise AdapterError("PTY write interrupted")
                fd = self._master_fd
            original_flags = fcntl.fcntl(fd, fcntl.F_GETFL)
            fcntl.fcntl(fd, fcntl.F_SETFL, original_flags | os.O_NONBLOCK)
            while offset < len(data):
                with self._lifecycle_lock:
                    if self._master_closed:
                        raise AdapterError("PTY master is closed")
                    if self._interrupt_requested.is_set():
                        raise AdapterError("PTY write interrupted")
                    fd = self._master_fd
                if self._proc.poll() is not None:
                    raise AdapterError("PTY child exited during write")
                try:
                    written = os.write(fd, data[offset:])
                except BlockingIOError:
                    select.select([], [fd], [], 0.05)
                    continue
                except OSError as exc:
                    raise AdapterError(f"PTY write failed: {exc}") from exc
                if written <= 0:
                    raise AdapterError("PTY write wrote no bytes")
                offset += written
        finally:
            if fd is not None and original_flags is not None:
                try:
                    fcntl.fcntl(fd, fcntl.F_SETFL, original_flags)
                except OSError:
                    pass

    def _write_best_effort(self, data: bytes) -> None:
        try:
            self._write_all(data)
        except AdapterError:
            pass

    def _write_interrupt_best_effort(self) -> bool:
        with self._lifecycle_lock:
            if self._master_closed:
                return False
            fd = self._master_fd
        try:
            flags = fcntl.fcntl(fd, fcntl.F_GETFL)
            fcntl.fcntl(fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)
            try:
                os.write(fd, b"\x03")
            except BlockingIOError:
                return False
            finally:
                fcntl.fcntl(fd, fcntl.F_SETFL, flags)
            return True
        except OSError:
            return False

    def _signal_process_group(self, sig: signal.Signals) -> None:
        if self._proc.poll() is not None:
            return
        try:
            os.killpg(self._proc.pid, sig)
        except ProcessLookupError:
            return
        except OSError:
            try:
                self._proc.send_signal(sig)
            except OSError:
                return

    def _reap_child(self) -> None:
        if self._proc.poll() is not None:
            return
        try:
            self._proc.wait(timeout=0.3)
            return
        except subprocess.TimeoutExpired:
            pass
        for sig, timeout in ((signal.SIGTERM, 2.0), (signal.SIGKILL, 2.0)):
            if self._proc.poll() is not None:
                return
            self._signal_process_group(sig)
            try:
                self._proc.wait(timeout=timeout)
                return
            except subprocess.TimeoutExpired:
                continue

    def _close_master_unlocked(self) -> None:
        self._master_closed = True
        try:
            os.close(self._master_fd)
        except OSError as exc:
            if exc.errno != errno.EBADF:
                raise


class _TerminalResponder:
    def __init__(self, *, rows: int, cols: int) -> None:
        self._rows = rows
        self._cols = cols
        self._row = 1
        self._col = 1
        self._buffer = b""
        self._outstanding_query: str | None = None
        self.bracketed_paste = False

    @property
    def outstanding_query(self) -> str | None:
        return self._outstanding_query

    def feed(self, data: bytes) -> list[bytes]:
        replies: list[bytes] = []
        self._buffer += data
        while True:
            start = self._buffer.find(ESC)
            if start < 0:
                self._buffer = b""
                return replies
            if start > 0:
                self._buffer = self._buffer[start:]
            if len(self._buffer) < 2:
                return replies
            introducer = self._buffer[1:2]
            if introducer == b"[":
                parsed = self._take_csi()
            elif introducer == b"]":
                parsed = self._take_osc()
            else:
                parsed = self._buffer[:2]
                self._buffer = self._buffer[2:]
            if parsed is None:
                return replies
            reply = self._handle_sequence(parsed)
            if reply:
                replies.append(reply)

    def _take_csi(self) -> bytes | None:
        for index in range(2, len(self._buffer)):
            byte = self._buffer[index]
            if 0x40 <= byte <= 0x7E:
                seq = self._buffer[: index + 1]
                self._buffer = self._buffer[index + 1 :]
                return seq
        return None

    def _take_osc(self) -> bytes | None:
        bel = self._buffer.find(BEL, 2)
        st = self._buffer.find(ST, 2)
        ends = [pos + 1 for pos in (bel,) if pos >= 0]
        ends.extend(pos + 2 for pos in (st,) if pos >= 0)
        if not ends:
            return None
        end = min(ends)
        seq = self._buffer[:end]
        self._buffer = self._buffer[end:]
        return seq

    def _handle_sequence(self, seq: bytes) -> bytes | None:
        if seq.startswith(ESC + b"["):
            return self._handle_csi(seq)
        if seq.startswith(ESC + b"]"):
            return self._handle_osc(seq)
        return None

    def _handle_csi(self, seq: bytes) -> bytes | None:
        body = seq[2:-1]
        final = seq[-1:]
        self._track_cursor(body, final)
        self._track_modes(body, final)
        if final == b"n":
            if body == b"6":
                return f"\x1b[{self._row};{self._col}R".encode()
            if body == b"5":
                return b"\x1b[0n"
            if body == b"?996":
                return b"\x1b[?997;1n"
            self._mark_report(seq)
            return None
        if final == b"c":
            if body in (b"", b"0"):
                return b"\x1b[?1;2c"
            if body == b">":
                return b"\x1b[>0;0;0c"
            self._mark_report(seq)
            return None
        if final == b"p" and body.startswith(b"?") and body.endswith(b"$"):
            mode = body[1:-1] or b"0"
            return b"\x1b[?" + mode + b";0$y"
        if final == b"q" and body.startswith(b">"):
            return b"\x1bP>|taut-summon(0)\x1b\\"
        if final == b"q" and body.endswith(b" "):
            return None
        if final == b"u" and body == b"?":
            return b"\x1b[?0u"
        if final == b"u" and body.startswith(b">"):
            return None
        if final in (b"p", b"q", b"u"):
            self._mark_report(seq)
        return None

    def _handle_osc(self, seq: bytes) -> bytes | None:
        content = seq[2:]
        if content.endswith(BEL):
            content = content[:-1]
        elif content.endswith(ST):
            content = content[:-2]
        if content == b"10;?":
            return b"\x1b]10;rgb:ffff/ffff/ffff\x1b\\"
        if content == b"11;?":
            return b"\x1b]11;rgb:0000/0000/0000\x1b\\"
        if content.startswith((b"10;?", b"11;?")):
            self._mark_report(seq)
        return None

    def _track_cursor(self, body: bytes, final: bytes) -> None:
        if final in (b"H", b"f"):
            parts = body.split(b";")
            row = _parse_int(parts[0] if parts else b"", default=1)
            col = _parse_int(parts[1] if len(parts) > 1 else b"", default=1)
            self._row, self._col = self._clamp(row, col)
        elif final == b"C":
            self._row, self._col = self._clamp(
                self._row, self._col + _parse_int(body, default=1)
            )
        elif final == b"B":
            self._row, self._col = self._clamp(
                self._row + _parse_int(body, default=1), self._col
            )
        elif final == b"D":
            self._row, self._col = self._clamp(
                self._row, self._col - _parse_int(body, default=1)
            )
        elif final == b"A":
            self._row, self._col = self._clamp(
                self._row - _parse_int(body, default=1), self._col
            )

    def _track_modes(self, body: bytes, final: bytes) -> None:
        if b"?2004" not in body:
            return
        if final == b"h":
            self.bracketed_paste = True
        elif final == b"l":
            self.bracketed_paste = False

    def _clamp(self, row: int, col: int) -> tuple[int, int]:
        return max(1, min(self._rows, row)), max(1, min(self._cols, col))

    def _mark_report(self, seq: bytes) -> None:
        self._outstanding_query = _printable_sequence(seq)


def _set_winsize(fd: int, rows: int, cols: int) -> None:
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))


def _parse_int(raw: bytes, *, default: int) -> int:
    try:
        return int(raw or str(default).encode())
    except ValueError:
        return default


def _printable_sequence(seq: bytes) -> str:
    text = seq.decode("latin1", errors="replace")
    return text.replace("\x1b", "")


def _sanitize_for_pty(text: str) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    out: list[str] = []
    for char in normalized:
        code = ord(char)
        if char == "\t":
            out.append(" ")
        elif char == "\n":
            out.append(char)
        elif char == "\x1b" or code == 0x7F or code < 0x20:
            continue
        else:
            out.append(char)
    return "".join(out)


class _DetachChordMatcher:
    def __init__(self, chord: bytes) -> None:
        if not chord or chord.startswith(ESC):
            raise AdapterError("detach chord must be non-empty and must not start ESC")
        self._chord = chord
        self._buffer = b""

    def feed(self, data: bytes) -> tuple[bytes, bool]:
        out = bytearray()
        for byte in data:
            candidate = self._buffer + bytes([byte])
            if self._chord.startswith(candidate):
                self._buffer = candidate
                if candidate == self._chord:
                    self._buffer = b""
                    return bytes(out), True
                continue
            if self._buffer:
                out.extend(self._buffer)
                self._buffer = b""
            out.append(byte)
        return bytes(out), False
