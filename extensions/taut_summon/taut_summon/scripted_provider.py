"""A deterministic interactive terminal child for Summon conformance tests.

The packaged ``scripted`` provider is the anti-mocking seam for the one PTY
adapter. It is a real subprocess attached to a POSIX PTY or Windows ConPTY.
It announces readiness by enabling bracketed paste, accepts bracketed-paste or
plain line input, and records received turns. Screen output is terminal
activity only. It is never interpreted as a model reply.

The program is deliberately standalone: stdlib only, no Taut imports, and
runnable by file path without a ``PYTHONPATH`` arrangement.

``TAUT_SUMMON_SCENARIO`` may name a JSON object with ``on_start``, indexed
``responses``, and ``default_response`` step lists. Supported steps are:

- ``{"terminal_text": TEXT}`` writes terminal output; ``{text}`` expands to
  the incoming turn.
- ``{"activity": NAME}`` and ``{"flood_activity": N}`` write deterministic
  terminal activity.
- ``{"sleep": SECONDS}`` — delay scenario.
- ``{"exit": CODE}`` — crash scenario: exit immediately with CODE.
- ``{"stall": true}`` — stop reading stdin forever (blocked-inject
  scenario; only an interrupt/kill ends the process).
- ``{"close_stdin": true}`` — close the stdin file descriptor (fd 0) then
  block forever: an inject large enough to overflow the pipe buffer fails
  with a broken pipe while the process stays alive (the repeated-failed-
  inject scenario for [SUM-5.4]/[TAUT-8.4]).
- ``{"spawn_descendant": {...}}`` — spawn one real descendant and publish its
  PID to the required ``pid_file``. The options exercise [SUM-12] process-
  domain cases: ``inherit_stdout``, ``ignore_sigint``, ``ignore_sigterm``,
  ``escape_domain``, ``leader_ignore_sigint``, ``leader_ignore_sigterm``,
  ``max_seconds``, ``leader_exit_code``, ``stdout_payload``, and
  ``stdout_repeat``. ``leader_exit_release_file`` can hold leader exit behind a
  test-owned release fence, and ``linger_after_stdout_close`` keeps a repeating
  writer alive for domain-retirement proof after its output closes. A
  configured payload is written before PID publication; repeat mode then writes
  it continuously until retirement or ``max_seconds``.
- ``{"exec_taut": {"args": [...], "count": N, "interval": S}}`` — run
  ``python -m taut ARGS`` as a real subprocess ``N`` times (default 1),
  using the child's own environment. The environment always carries
  ``TAUT_TOKEN`` and carries ``TAUT_DB`` only for path-addressed backends
  ([SUM-6]); this is the agent speaking through its mouth for real — the
  end-to-end mouth-credential proof, and the flood source for the [SUM-10]
  rate-backstop test.
The top-level ``sigint_cleanup_seconds`` option enables the [SUM-12]
terminal-retirement probe. The provider records every SIGINT, keeps the first
handler inside one bounded cleanup gate so a reentrant signal remains
observable, then exits normally. A second signal releases the gate early; a
watchdog releases it at the configured upper bound when no second signal
arrives.

When ``TAUT_SUMMON_RECEIVED_LOG`` names a file, the provider appends one
JSON line per observable step. The start entry records mouth credentials and
the per-turn entry records the exact terminal text received.
- per injected message: ``{"event": "message", "pid": ..., "text": ...}``.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import threading
import time
from typing import Any

_BRACKETED_PASTE_ENABLE = b"\x1b[?2004h"
_BRACKETED_PASTE_START = b"\x1b[200~"
_BRACKETED_PASTE_END = b"\x1b[201~"


class _SignalCleanupComplete(Exception):
    """Unwind the provider's main loop after bounded SIGINT cleanup."""


def _record(payload: dict[str, Any]) -> None:
    path = os.environ.get("TAUT_SUMMON_RECEIVED_LOG")
    if not path:
        return
    payload = {**payload, "pid": os.getpid()}
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, separators=(",", ":")) + "\n")
        handle.flush()


def _write_stderr(body: str) -> None:
    rendered = body.encode("unicode_escape", errors="backslashreplace").decode()
    print(rendered, file=sys.stderr, flush=True)


def _write_terminal(body: str) -> None:
    os.write(1, body.encode("utf-8", errors="replace"))


def _load_scenario() -> dict[str, Any]:
    path = os.environ.get("TAUT_SUMMON_SCENARIO")
    if not path:
        return {}
    with open(path, encoding="utf-8") as handle:
        loaded = json.load(handle)
    if not isinstance(loaded, dict):
        raise ValueError("scenario file must hold a JSON object")  # noqa: TRY004 approved [DOM-10.2.1] [RUFF-SUP-073] exception
    return loaded


class _InterruptController:
    """Record terminal interrupts and expose the bounded cleanup scenario."""

    def __init__(self, scenario: dict[str, Any]) -> None:
        self._seconds: float | None = None
        self._cleanup_release = threading.Event()
        self._signal_count = 0
        self._release_source = "watchdog"

        raw_seconds = scenario.get("sigint_cleanup_seconds")
        if raw_seconds is not None:
            seconds = float(raw_seconds)
            if seconds <= 0:
                raise ValueError("sigint_cleanup_seconds must be greater than zero")
            self._seconds = seconds

    def install(self) -> None:
        signal.signal(signal.SIGINT, self._handle_signal)

    def _handle_signal(self, _signum: int, _frame: Any) -> None:
        self.interrupt()

    def interrupt(self) -> None:
        self._signal_count += 1
        _record(
            {"event": "signal", "signal": "SIGINT", "count": self._signal_count}
        )
        if self._seconds is None:
            raise KeyboardInterrupt
        if self._signal_count > 1:
            self._release_source = "reentrant"
            self._cleanup_release.set()
            return

        _record({"event": "first-signal-entered"})
        watchdog = threading.Timer(self._seconds, self._release_from_watchdog)
        watchdog.daemon = True
        watchdog.start()
        self._cleanup_release.wait(timeout=self._seconds + 1.0)
        watchdog.cancel()
        _record({"event": "cleanup-release", "source": self._release_source})
        raise _SignalCleanupComplete

    def _release_from_watchdog(self) -> None:
        self._release_source = "watchdog"
        self._cleanup_release.set()


def _install_sigint_cleanup(scenario: dict[str, Any]) -> _InterruptController:
    controller = _InterruptController(scenario)
    controller.install()
    return controller


class _TerminalInputParser:
    """Incrementally decode bracketed-paste frames and plain terminal lines."""

    def __init__(self) -> None:
        self._buffer = bytearray()
        self._in_paste = False

    def feed(self, data: bytes) -> tuple[list[str], int]:
        self._buffer.extend(data)
        turns: list[str] = []
        interrupts = 0
        while self._buffer:
            if self._in_paste:
                if not self._consume_paste(turns):
                    break
            else:
                progressed, found_interrupt = self._consume_normal(turns)
                interrupts += found_interrupt
                if not progressed:
                    break
        return turns, interrupts

    def _consume_paste(self, turns: list[str]) -> bool:
        end = self._buffer.find(_BRACKETED_PASTE_END)
        if end < 0:
            return False
        turns.append(bytes(self._buffer[:end]).decode("utf-8", errors="replace"))
        del self._buffer[: end + len(_BRACKETED_PASTE_END)]
        self._in_paste = False
        return True

    def _consume_normal(self, turns: list[str]) -> tuple[bool, int]:
        start = self._buffer.find(_BRACKETED_PASTE_START)
        line_end = _first_line_end(self._buffer)
        interrupt = self._buffer.find(3)
        candidates = [index for index in (start, line_end, interrupt) if index >= 0]
        if not candidates:
            return False, 0
        next_index = min(candidates)
        raw = bytes(self._buffer[:next_index])
        if raw:
            turns.append(raw.decode("utf-8", errors="replace"))
        if next_index == start:
            del self._buffer[: start + len(_BRACKETED_PASTE_START)]
            self._in_paste = True
        elif next_index == interrupt:
            del self._buffer[: interrupt + 1]
            return True, 1
        else:
            del self._buffer[: line_end + 1]
            if self._buffer[:1] in (b"\r", b"\n"):
                del self._buffer[:1]
        return True, 0


def _first_line_end(buffer: bytearray) -> int:
    carriage = buffer.find(13)
    newline = buffer.find(10)
    found = [index for index in (carriage, newline) if index >= 0]
    return min(found) if found else -1


class _State:
    def __init__(self) -> None:
        self.activity_index = 0


def _run_steps(  # noqa: C901 approved [DOM-10.2.1] [RUFF-SUP-036] exception
    steps: list[dict[str, Any]],
    state: _State,
    message_text: str,
) -> None:
    for step in steps:
        if "terminal_text" in step:
            text = str(step["terminal_text"]).replace("{text}", message_text)
            _write_terminal(text)
        elif "activity" in step:
            state.activity_index += 1
            _write_terminal(
                f"[activity {state.activity_index}: {step['activity']}]\r\n"
            )
        elif "flood_activity" in step:
            for _ in range(int(step["flood_activity"])):
                state.activity_index += 1
                _write_terminal(f"[activity {state.activity_index}: flood]\r\n")
        elif "sleep" in step:
            time.sleep(float(step["sleep"]))
        elif "exit" in step:
            sys.exit(int(step["exit"]))
        elif "stall" in step:
            while True:
                time.sleep(3600)
        elif "close_stdin" in step:
            # Close the underlying fd (fd 0) so the pipe's read end is truly
            # gone; a large enough inject then fails with EPIPE. Closing the
            # Python wrapper alone does not close the fd on CPython.
            try:
                os.close(0)
            except OSError:
                pass
            while True:
                time.sleep(3600)
        elif "spawn_descendant" in step:
            _spawn_descendant(step["spawn_descendant"])
        elif "exec_taut" in step:
            _exec_taut(step["exec_taut"])
        else:
            raise ValueError(f"unknown scenario step: {step!r}")


def _descendant_stdout_spec(raw_spec: dict[str, Any]) -> tuple[bool, str, bool]:
    inherit_stdout = bool(raw_spec.get("inherit_stdout", False))
    raw_stdout_payload = raw_spec.get("stdout_payload", "")
    if not isinstance(raw_stdout_payload, str):
        raise TypeError("spawn_descendant.stdout_payload must be a string")
    stdout_repeat = bool(raw_spec.get("stdout_repeat", False))
    if raw_stdout_payload and not inherit_stdout:
        raise ValueError("spawn_descendant.stdout_payload requires inherit_stdout")
    if stdout_repeat and not raw_stdout_payload:
        raise ValueError("spawn_descendant.stdout_repeat requires stdout_payload")
    return inherit_stdout, raw_stdout_payload, stdout_repeat


def _descendant_lifetime_spec(
    raw_spec: dict[str, Any], *, stdout_repeat: bool
) -> tuple[float, bool]:
    max_seconds = float(raw_spec.get("max_seconds", 30.0))
    if not 1.0 <= max_seconds <= 120.0:
        raise ValueError("spawn_descendant.max_seconds must be in 1..120")
    linger_after_stdout_close = bool(raw_spec.get("linger_after_stdout_close", False))
    if linger_after_stdout_close and not stdout_repeat:
        raise ValueError("linger_after_stdout_close requires stdout_repeat")
    return max_seconds, linger_after_stdout_close


def _configure_descendant_leader_signals(raw_spec: dict[str, Any]) -> None:
    if raw_spec.get("leader_ignore_sigint", False):
        signal.signal(signal.SIGINT, signal.SIG_IGN)
    if raw_spec.get("leader_ignore_sigterm", False):
        signal.signal(signal.SIGTERM, signal.SIG_IGN)


def _wait_for_descendant_pid(proc: subprocess.Popen[bytes], pid_file: str) -> None:
    deadline = time.monotonic() + 5.0
    while not os.path.exists(pid_file):
        if proc.poll() is not None:
            raise RuntimeError(
                f"scripted descendant exited before PID publication: {proc.returncode}"
            )
        if time.monotonic() >= deadline:
            proc.kill()
            proc.wait(timeout=5.0)
            raise RuntimeError("scripted descendant PID publication timed out")
        time.sleep(0.01)


def _descendant_leader_release_path(raw_release_file: Any) -> str | None:
    if raw_release_file is None:
        return None
    if not isinstance(raw_release_file, str) or not raw_release_file:
        raise ValueError("leader_exit_release_file must be a non-empty string")
    return os.path.abspath(raw_release_file)


def _wait_for_descendant_leader_release(
    proc: subprocess.Popen[bytes], release_file: str | None
) -> None:
    if release_file is None:
        return
    deadline = time.monotonic() + 5.0
    while not os.path.exists(release_file):
        if proc.poll() is not None:
            raise RuntimeError(
                f"scripted descendant exited before leader release: {proc.returncode}"
            )
        if time.monotonic() >= deadline:
            proc.kill()
            proc.wait(timeout=5.0)
            raise RuntimeError("scripted descendant leader release timed out")
        time.sleep(0.01)


def _spawn_descendant(raw_spec: Any) -> None:
    """Spawn one bounded-test descendant without importing Taut internals."""

    if not isinstance(raw_spec, dict):
        raise TypeError("spawn_descendant must be an object")
    raw_pid_file = raw_spec.get("pid_file")
    if not isinstance(raw_pid_file, str) or not raw_pid_file:
        raise ValueError("spawn_descendant.pid_file must be a non-empty string")
    pid_file = os.path.abspath(raw_pid_file)
    child_program = """
import json
import os
import signal
import sys
import time

pid_file = sys.argv[1]
ignore_sigint = sys.argv[2] == "1"
ignore_sigterm = sys.argv[3] == "1"
max_seconds = float(sys.argv[4])
stdout_payload = sys.argv[5].encode("utf-8")
stdout_repeat = sys.argv[6] == "1"
linger_after_stdout_close = sys.argv[7] == "1"
if ignore_sigint:
    signal.signal(signal.SIGINT, signal.SIG_IGN)
if ignore_sigterm:
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
if linger_after_stdout_close and hasattr(signal, "SIGHUP"):
    signal.signal(signal.SIGHUP, signal.SIG_IGN)

def write_payload():
    offset = 0
    while offset < len(stdout_payload):
        try:
            written = os.write(1, stdout_payload[offset:])
        except OSError:
            return False
        if written <= 0:
            return False
        offset += written
    return True

if stdout_payload:
    write_payload()
temporary = f"{pid_file}.{os.getpid()}.tmp"
with open(temporary, "x", encoding="utf-8") as handle:
    json.dump({"pid": os.getpid()}, handle)
    handle.flush()
os.replace(temporary, pid_file)
deadline = time.monotonic() + max_seconds
while time.monotonic() < deadline:
    if stdout_payload and stdout_repeat:
        if not write_payload():
            if not linger_after_stdout_close:
                break
            stdout_repeat = False
    else:
        time.sleep(min(1.0, deadline - time.monotonic()))
"""
    inherit_stdout, raw_stdout_payload, stdout_repeat = _descendant_stdout_spec(
        raw_spec
    )
    max_seconds, linger_after_stdout_close = _descendant_lifetime_spec(
        raw_spec, stdout_repeat=stdout_repeat
    )
    leader_release_file = _descendant_leader_release_path(
        raw_spec.get("leader_exit_release_file")
    )
    _configure_descendant_leader_signals(raw_spec)
    proc = subprocess.Popen(
        [
            sys.executable,
            "-c",
            child_program,
            pid_file,
            "1" if raw_spec.get("ignore_sigint", False) else "0",
            "1" if raw_spec.get("ignore_sigterm", False) else "0",
            str(max_seconds),
            raw_stdout_payload,
            "1" if stdout_repeat else "0",
            "1" if linger_after_stdout_close else "0",
        ],
        stdin=subprocess.DEVNULL,
        stdout=None if inherit_stdout else subprocess.DEVNULL,
        stderr=None if inherit_stdout else subprocess.DEVNULL,
        close_fds=True,
        start_new_session=bool(raw_spec.get("escape_domain", False)),
    )
    _wait_for_descendant_pid(proc, pid_file)
    _record({"event": "descendant", "child_pid": proc.pid})
    _wait_for_descendant_leader_release(proc, leader_release_file)
    if "leader_exit_code" in raw_spec:
        raise SystemExit(int(raw_spec["leader_exit_code"]))


def _exec_taut(spec: Any) -> None:
    """Run ``python -m taut ARGS`` as a real child, using our own env.

    The environment carries ``TAUT_TOKEN`` and, for a path backend,
    ``TAUT_DB`` ([SUM-6]), so this
    is the summoned agent speaking through its mouth for real. Best-effort:
    a non-zero taut exit is logged to stderr but does not stop the scenario.
    """

    if isinstance(spec, list):
        spec = {"args": spec}
    args = [str(a) for a in spec.get("args", [])]
    count = int(spec.get("count", 1))
    interval = float(spec.get("interval", 0.0))
    for i in range(count):
        result = subprocess.run(
            [sys.executable, "-m", "taut", *args],
            env=os.environ.copy(),
            check=False,
        )
        if result.returncode != 0:
            _write_stderr(f"scripted provider: taut exited {result.returncode}")
        if interval and i + 1 < count:
            time.sleep(interval)


def main() -> int:
    try:
        scenario = _load_scenario()
        interrupts = _install_sigint_cleanup(scenario)
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        _write_stderr(f"scripted provider: bad scenario: {exc}")
        return 2

    state = _State()
    parser = _TerminalInputParser()
    try:
        _record(
            {
                "event": "start",
                "env_as": os.environ.get("TAUT_AS"),
                "env_token": os.environ.get("TAUT_TOKEN"),
                "env_db": os.environ.get("TAUT_DB"),
            }
        )
        os.write(1, _BRACKETED_PASTE_ENABLE)
        _write_terminal("scripted> ")
        _record({"event": "provider-ready"})

        responses = scenario.get("responses", [])
        default_response = scenario.get("default_response", [])
        _run_steps(list(scenario.get("on_start", [])), state, "")

        index = 0
        while True:
            data = os.read(0, 4096)
            if not data:
                return 0
            turns, interrupt_count = parser.feed(data)
            for _ in range(interrupt_count):
                interrupts.interrupt()
            for text in turns:
                _record({"event": "message", "text": text})
                steps = responses[index] if index < len(responses) else default_response
                index += 1
                _run_steps(list(steps), state, text)
    except _SignalCleanupComplete:
        return 0
    except KeyboardInterrupt:
        return 130
    except (OSError, TypeError, ValueError) as exc:
        _write_stderr(f"scripted provider: terminal error: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
