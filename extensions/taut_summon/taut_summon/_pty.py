"""Universal interactive PTY adapter ([SUM-7.4]).

The adapter hosts a harness in its normal full-screen interactive mode. It
does not parse the screen as speech; the master reader exists only for coarse
liveness, finite terminal-query replies, diagnostics, and clean lifecycle
ownership.
"""

from __future__ import annotations

import logging
import math
import os
import re
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass

from taut_summon._adapter import AdapterError, AdapterHandle

logger = logging.getLogger("taut_summon.pty")

ESC = b"\x1b"
BEL = b"\x07"
ST = ESC + b"\\"

_DEFAULT_ROWS = 24
_DEFAULT_COLS = 80
_OUTPUT_ACTIVITY_WINDOW_SECONDS = 10.0
_DEFAULT_DETACH_CHORD = b"\x1c\x1c"
_OUTPUT_TAIL_RAW_CAP = 4096
_OUTPUT_TAIL_TEXT_CAP = 1024
# Complete terminal sequences, removed with their parameter/string bodies so
# the diagnostic tail carries no printable residue such as "[38;2;..m" or
# "]8;;url" ([SUM-7.4]). Ordered alternation: string-bodied and CSI forms
# match before the generic ESC form; well-formed dangling forms at the end
# of the rolling buffer are dropped rather than leaked. C1 single-byte
# introducers are guarded against UTF-8 continuation bytes (s-acute is
# C5 9B) by a not-after-lead/continuation lookbehind; remaining C1
# codepoints are stripped after decoding.
_NOT_UTF8_TAIL = rb"(?<![\x80-\xbf\xc2-\xf4])"
_TERMINAL_SEQUENCE = re.compile(
    rb"(?:\x1b\[|" + _NOT_UTF8_TAIL + rb"\x9b)[0-?]*[ -/]*[@-~]"  # CSI
    rb"|(?:\x1b\]|" + _NOT_UTF8_TAIL + rb"\x9d)[^\x07\x9c\x1b]*"  # OSC
    rb"(?:\x07|\x1b\\|\x9c)"
    rb"|(?:\x1bP|\x1bX|\x1b\^|\x1b_|"  # DCS/SOS/PM/APC
     + _NOT_UTF8_TAIL + rb"[\x90\x98\x9e\x9f])[^\x1b\x9c]*(?:\x1b\\|\x9c)"
    rb"|(?:\x1b\[|" + _NOT_UTF8_TAIL + rb"\x9b)[0-?]*[ -/]*\Z"  # dangling CSI
    rb"|(?:\x1b\]|" + _NOT_UTF8_TAIL + rb"\x9d)[^\x07\x9c\x1b]*\Z"  # dangling OSC
    rb"|(?:\x1bP|\x1bX|\x1b\^|\x1b_|"  # dangling DCS/SOS/PM/APC
     + _NOT_UTF8_TAIL + rb"[\x90\x98\x9e\x9f])[^\x1b\x9c]*\Z"
    rb"|\x1b[ -/]*[0-~]"  # other ESC sequences (ESC=, ESC(B, ...)
    rb"|\x1b[ -/]*\Z"  # dangling ESC form at buffer end
)
_TERMINAL_RESPONSE_BUFFER_LIMIT = 4096
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
    """One validated launch shape.

    Dimensions must fit the unsigned-short PTY winsize fields. Stall and
    settle deadlines are finite and positive; a zero quiet interval is valid.
    """

    name: str
    argv: tuple[str, ...]
    rows: int = _DEFAULT_ROWS
    cols: int = _DEFAULT_COLS
    stall_s: float = 10.0
    quiet_ms: int = 500
    max_settle_s: float = 10.0


class PtyAdapter:
    """Spawn an interactive harness on the platform pseudo-terminal backend."""

    supports_attach: bool = True
    orientation_via_inject: bool = True

    def __init__(self, spec: PtySpec | None = None) -> None:
        self._spec = spec or PtySpec(name="pty", argv=(_default_shell(),))
        _validate_spec(self._spec)
        self.name = self._spec.name

    @property
    def argv(self) -> tuple[str, ...]:
        return self._spec.argv

    def spawn(
        self,
        *,
        system_prompt: str,
        env: Mapping[str, str],
    ) -> AdapterHandle:
        del system_prompt
        child_env = _child_environment(env)
        terminal = _TerminalState(
            rows=self._spec.rows,
            cols=self._spec.cols,
            stall_s=self._spec.stall_s,
        )
        if os.name == "nt":
            from taut_summon._pty_windows import spawn_windows_pty

            return spawn_windows_pty(
                argv=self._spec.argv,
                env=child_env,
                rows=self._spec.rows,
                cols=self._spec.cols,
                quiet_ms=self._spec.quiet_ms,
                max_settle_s=self._spec.max_settle_s,
                terminal=terminal,
            )
        from taut_summon._pty_posix import spawn_posix_pty

        return spawn_posix_pty(
            spec=self._spec,
            env=child_env,
            terminal=terminal,
        )


def _default_shell() -> str:
    if os.name == "nt":
        return os.environ.get("COMSPEC", "cmd.exe")
    return os.environ.get("SHELL", "sh")


def _child_environment(overrides: Mapping[str, str]) -> dict[str, str]:
    if os.name != "nt":
        result = dict(os.environ)
        result.pop("TAUT_AS", None)
        result.pop("TAUT_TOKEN", None)
        result.update(overrides)
    else:
        # Windows environment names are case-insensitive. Rebuild through a
        # folded index so inherited spellings cannot retain stale credentials.
        folded = {key.casefold(): (key, value) for key, value in os.environ.items()}
        folded.pop("taut_as", None)
        folded.pop("taut_token", None)
        for key, value in overrides.items():
            folded[key.casefold()] = (key, value)
        folded["term"] = ("TERM", "xterm-256color")
        folded.setdefault("colorterm", ("COLORTERM", "truecolor"))
        result = dict(folded.values())
    if os.name != "nt":
        result["TERM"] = "xterm-256color"
        result.setdefault("COLORTERM", "truecolor")
    return result


class _TerminalInputModeTracker:
    """Passively retain the bounded terminal input modes needed for injection."""

    def __init__(self) -> None:
        self._buffer = b""
        self.bracketed_paste = False
        # Latched once an enable is seen; a later disable never clears it
        # ([SUM-7.4] input-prompt confirmation).
        self.paste_enable_seen = False

    def feed(self, data: bytes) -> None:
        self._buffer += data
        while (sequence := self._take_csi()) is not None:
            body = sequence[2:-1]
            final = sequence[-1:]
            if b"?2004" not in body:
                continue
            if final == b"h":
                self.bracketed_paste = True
                self.paste_enable_seen = True
            elif final == b"l":
                self.bracketed_paste = False

    def _take_csi(self) -> bytes | None:
        while True:
            start = self._buffer.find(ESC)
            if start < 0:
                self._buffer = b""
                return None
            if start > 0:
                self._buffer = self._buffer[start:]
            if len(self._buffer) < 2:
                return None
            if self._buffer[1:2] != b"[":
                self._buffer = self._buffer[2:]
                continue
            final_index = next(
                (
                    index
                    for index in range(2, len(self._buffer))
                    if 0x40 <= self._buffer[index] <= 0x7E
                ),
                None,
            )
            if final_index is None:
                if len(self._buffer) > _TERMINAL_RESPONSE_BUFFER_LIMIT:
                    self._buffer = self._buffer[-_TERMINAL_RESPONSE_BUFFER_LIMIT:]
                return None
            sequence = self._buffer[: final_index + 1]
            self._buffer = self._buffer[final_index + 1 :]
            return sequence


class _TerminalState:
    """Thread-safe terminal semantics shared by all PTY backends."""

    def __init__(self, *, rows: int, cols: int, stall_s: float) -> None:
        self._lock = threading.RLock()
        self._responder = _TerminalResponder(rows=rows, cols=cols)
        self._input_modes = _TerminalInputModeTracker()
        self._tail_buffer = bytearray()
        self._last_output_ts = time.monotonic()
        self._seen_output = False
        self._stall_s = stall_s
        self._awaiting_query: str | None = None
        self._awaiting_onboarding = False

    @property
    def last_output_ts(self) -> float:
        with self._lock:
            return self._last_output_ts

    @property
    def seen_output(self) -> bool:
        with self._lock:
            return self._seen_output

    @property
    def input_prompt_observed(self) -> bool:
        with self._lock:
            return self._input_modes.paste_enable_seen

    @property
    def unhandled_query_pending(self) -> bool:
        with self._lock:
            return (
                self._responder.outstanding_query is not None
                and self._awaiting_query is None
            )

    @property
    def bracketed_paste(self) -> bool:
        with self._lock:
            return self._input_modes.bracketed_paste

    def encode_injection(self, text: str) -> bytes:
        sanitized = _sanitize_for_pty(text)
        with self._lock:
            bracketed_paste = self._input_modes.bracketed_paste
        if bracketed_paste:
            return ESC + b"[200~" + sanitized.encode() + ESC + b"[201~\r"
        return sanitized.replace("\n", " ").encode() + b"\r"

    def observe_output(
        self, data: bytes, *, answer_queries: bool = True
    ) -> tuple[bytes, ...]:
        with self._lock:
            self._last_output_ts = time.monotonic()
            self._seen_output = True
            self._input_modes.feed(data)
            self._tail_buffer.extend(data)
            if len(self._tail_buffer) > _OUTPUT_TAIL_RAW_CAP:
                del self._tail_buffer[: len(self._tail_buffer) - _OUTPUT_TAIL_RAW_CAP]
            if answer_queries:
                return tuple(self._responder.feed(data))
            return ()

    def mark_stalled(self, *, now: float | None = None) -> None:
        with self._lock:
            outstanding = self._responder.outstanding_query
            if outstanding is None or self._awaiting_query is not None:
                return
            observed_now = time.monotonic() if now is None else now
            if observed_now - self._last_output_ts < self._stall_s:
                return
            self._awaiting_query = outstanding
        logger.warning(
            "PTY harness is awaiting an unhandled terminal report query: %s",
            outstanding,
        )

    def mark_awaiting_onboarding(self) -> None:
        with self._lock:
            self._awaiting_onboarding = True

    def output_tail(self) -> str:
        with self._lock:
            raw_tail = bytes(self._tail_buffer)
        stripped = _TERMINAL_SEQUENCE.sub(b"", raw_tail)
        text = stripped.decode("utf-8", errors="replace")
        kept: list[str] = []
        for char in text:
            code = ord(char)
            if char == "\n":
                kept.append(char)
            elif char == "\x1b" or code == 0x7F or code < 0x20 or 0x80 <= code <= 0x9F:
                continue
            else:
                kept.append(char)
        return "".join(kept)[-_OUTPUT_TAIL_TEXT_CAP:]

    def status_fields(self) -> dict[str, str]:
        with self._lock:
            fields: dict[str, str] = {}
            if self._awaiting_query is not None:
                fields["awaiting_query"] = self._awaiting_query
            if self._awaiting_onboarding:
                fields["awaiting_onboarding"] = "true"
            return fields

    @staticmethod
    def detach_matcher(chord: bytes) -> _DetachChordMatcher:
        return _DetachChordMatcher(chord)


def _validate_spec(spec: PtySpec) -> None:
    """Validate the one central PTY construction boundary."""

    if not spec.argv or not all(isinstance(item, str) and item for item in spec.argv):
        raise AdapterError(
            "argv (TAUT_SUMMON_PTY_ARGV) must be a non-empty string sequence"
        )
    for field, env_name, dimension_value in (
        ("rows", "TAUT_SUMMON_PTY_ROWS", spec.rows),
        ("cols", "TAUT_SUMMON_PTY_COLS", spec.cols),
    ):
        _validate_dimension(field, env_name, dimension_value)
    for field, env_name, timing_value in (
        ("stall_s", "TAUT_SUMMON_PTY_STALL_S", spec.stall_s),
        ("max_settle_s", "TAUT_SUMMON_PTY_MAX_SETTLE_S", spec.max_settle_s),
    ):
        _validate_positive_timing(field, env_name, timing_value)
    _validate_quiet_ms(spec.quiet_ms)


def _validate_dimension(field: str, env_name: str, value: object) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not 1 <= value <= 65_535
    ):
        raise AdapterError(f"{field} ({env_name}) must be between 1 and 65535")


def _validate_positive_timing(field: str, env_name: str, value: object) -> None:
    error = f"{field} ({env_name}) must be a finite positive number"
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise AdapterError(error)
    try:
        finite_timing = float(value)
    except OverflowError as exc:
        raise AdapterError(error) from exc
    if not math.isfinite(finite_timing) or finite_timing <= 0:
        raise AdapterError(error)


def _validate_quiet_ms(quiet_ms: object) -> None:
    if isinstance(quiet_ms, bool) or not isinstance(quiet_ms, int) or quiet_ms < 0:
        raise AdapterError(
            "quiet_ms (TAUT_SUMMON_PTY_QUIET_MS) must be a non-negative integer"
        )
    try:
        quiet_seconds = quiet_ms / 1000.0
    except OverflowError as exc:
        raise AdapterError(
            "quiet_ms (TAUT_SUMMON_PTY_QUIET_MS) must produce finite seconds"
        ) from exc
    if not math.isfinite(quiet_seconds):
        raise AdapterError(
            "quiet_ms (TAUT_SUMMON_PTY_QUIET_MS) must produce finite seconds"
        )


class _TerminalResponder:
    def __init__(self, *, rows: int, cols: int) -> None:
        self._rows = rows
        self._cols = cols
        self._row = 1
        self._col = 1
        self._buffer = b""
        self._scan_index = 2
        # Deterministic work counter for the parser's contract tests. This is
        # byte-inspection evidence, not a wall-clock performance metric.
        self._scan_steps = 0
        self._outstanding_query: str | None = None

    @property
    def outstanding_query(self) -> str | None:
        return self._outstanding_query

    @property
    def buffered_bytes(self) -> int:
        return len(self._buffer)

    @property
    def scan_steps(self) -> int:
        return self._scan_steps

    def feed(self, data: bytes) -> list[bytes]:
        replies: list[bytes] = []
        self._buffer += data
        while True:
            start = self._find_escape()
            if start < 0:
                self._buffer = b""
                self._scan_index = 2
                return replies
            if start > 0:
                self._buffer = self._buffer[start:]
                self._scan_index = 2
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
                self._scan_index = 2
            if parsed is None:
                self._bound_incomplete_buffer()
                return replies
            reply = self._handle_sequence(parsed)
            if reply:
                replies.append(reply)

    def _find_escape(self) -> int:
        for index, byte in enumerate(self._buffer):
            self._scan_steps += 1
            if byte == ESC[0]:
                return index
        return -1

    def _bound_incomplete_buffer(self) -> None:
        if len(self._buffer) <= _TERMINAL_RESPONSE_BUFFER_LIMIT:
            return
        window_start = len(self._buffer) - _TERMINAL_RESPONSE_BUFFER_LIMIT
        suffix = self._buffer[window_start:]
        self._scan_steps += len(suffix)
        relative = suffix.rfind(ESC)
        if relative < 0:
            self._buffer = b""
        else:
            self._buffer = suffix[relative:]
        self._scan_index = 2

    def _take_csi(self) -> bytes | None:
        for index in range(max(2, self._scan_index), len(self._buffer)):
            self._scan_steps += 1
            byte = self._buffer[index]
            if 0x40 <= byte <= 0x7E:
                seq = self._buffer[: index + 1]
                self._buffer = self._buffer[index + 1 :]
                self._scan_index = 2
                return seq
        self._scan_index = len(self._buffer)
        return None

    def _take_osc(self) -> bytes | None:
        index = max(2, self._scan_index)
        while index < len(self._buffer):
            self._scan_steps += 1
            byte = self._buffer[index]
            if byte == BEL[0]:
                end = index + 1
                seq = self._buffer[:end]
                self._buffer = self._buffer[end:]
                self._scan_index = 2
                return seq
            if byte == ESC[0]:
                if index + 1 >= len(self._buffer):
                    self._scan_index = index
                    return None
                self._scan_steps += 1
                if self._buffer[index + 1] == ord("\\"):
                    end = index + 2
                    seq = self._buffer[:end]
                    self._buffer = self._buffer[end:]
                    self._scan_index = 2
                    return seq
            index += 1
        self._scan_index = len(self._buffer)
        return None

    def _handle_sequence(self, seq: bytes) -> bytes | None:
        if seq.startswith(ESC + b"["):
            return self._handle_csi(seq)
        if seq.startswith(ESC + b"]"):
            return self._handle_osc(seq)
        return None

    def _handle_csi(self, seq: bytes) -> bytes | None:  # noqa: C901 approved [DOM-10.2.1] [RUFF-SUP-034] exception
        body = seq[2:-1]
        final = seq[-1:]
        self._track_cursor(body, final)
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

    def _clamp(self, row: int, col: int) -> tuple[int, int]:
        return max(1, min(self._rows, row)), max(1, min(self._cols, col))

    def _mark_report(self, seq: bytes) -> None:
        self._outstanding_query = _printable_sequence(seq)


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
        elif char == "\x1b" or code == 0x7F or code < 0x20 or 0x80 <= code <= 0x9F:
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
