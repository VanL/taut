"""Minimal interactive setup-gate harness modeling Kimi Code 0.37.2.

Renders a full-screen trust menu WITHOUT enabling bracketed paste. Enter
while the menu is up selects the default "Don't trust" and exits 0 —
exactly the behavior that turned a wired re-summon into a crash loop on
2026-08-18. The setup key is ``Ctrl-T`` (``0x14``) — a byte Summon's
sanitized injection can never submit, mirroring real gates that ignore
typed text — which selects "Trust", switches to a chat prompt that enables
bracketed paste, echoes submitted turns, and stays alive.

Environment:
  TAUT_GATE_LOG: optional JSONL event-log path.
  TAUT_GATE_PRETRUSTED: "1" skips the menu and opens the chat prompt
    directly (a provider whose gate has already been answered).
"""

from __future__ import annotations

import json
import os
from typing import Any

INPUT: Any


def _log(event: str, **fields: object) -> None:
    path = os.environ.get("TAUT_GATE_LOG")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"event": event, **fields}) + "\n")


def _write(data: bytes) -> None:
    os.write(1, data)


def _chat_loop(initial: bytes = b"") -> int:
    _write(b"\x1b[?2004h\r\nchat> ")
    _log("chat_ready")
    buffer = initial
    while True:
        while b"\r" in buffer:
            line, _, buffer = buffer.partition(b"\r")
            _log("input", raw=line.decode("latin1"))
            _write(b"\r\necho:" + line.replace(b"\x1b", b"") + b"\r\nchat> ")
        chunk = INPUT.receive()
        if chunk is None:
            return 0
        if chunk == b"":
            continue
        buffer += chunk


def _decline(initial: bytes = b"") -> int:
    _log("declined_default")
    if os.environ.get("TAUT_GATE_WAIT_FOR_INJECT_RETURN") == "1":
        if b"\0" in initial:
            _write(b"\r\nBye!\r\n")
            return 0
        while True:
            release = INPUT.receive()
            if release is None:
                return 0
            if b"\0" in release:
                break
    _write(b"\r\nBye!\r\n")
    return 0


def _gate_loop() -> int:
    _write(
        b"\x1b[2J\x1b[H  Trust this folder?\r\n\r\n"
        b"     Trust this folder\r\n"
        b"   > Don't trust\r\n"
    )
    _log("menu")
    while True:
        chunk = INPUT.receive()
        if chunk is None:
            return 0
        if chunk == b"":
            continue
        for index, char in enumerate(chunk):
            byte = bytes((char,))
            if byte == b"\x14":
                _log("trusted")
                return _chat_loop(chunk[index + 1 :])
            if byte in (b"\r", b"\n"):
                return _decline(chunk[index + 1 :])


def main() -> int:
    global INPUT

    from terminal_io import TerminalInput, configure_raw_input

    configure_raw_input()
    INPUT = TerminalInput()
    _log("start", pid=os.getpid())
    if os.environ.get("TAUT_GATE_PRETRUSTED") == "1":
        return _chat_loop()
    return _gate_loop()


if __name__ == "__main__":
    raise SystemExit(main())
