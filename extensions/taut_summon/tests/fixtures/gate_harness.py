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
import sys
import tty


def _log(event: str, **fields: object) -> None:
    path = os.environ.get("TAUT_GATE_LOG")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"event": event, **fields}) + "\n")


def _write(data: bytes) -> None:
    os.write(1, data)


def _chat_loop() -> int:
    _write(b"\x1b[?2004h\r\nchat> ")
    _log("chat_ready")
    buffer = b""
    while True:
        chunk = os.read(0, 1024)
        if not chunk:
            return 0
        buffer += chunk
        while b"\r" in buffer:
            line, _, buffer = buffer.partition(b"\r")
            _log("input", raw=line.decode("latin1"))
            _write(b"\r\necho:" + line.replace(b"\x1b", b"") + b"\r\nchat> ")


def main() -> int:
    tty.setraw(sys.stdin.fileno())
    _log("start", pid=os.getpid())
    if os.environ.get("TAUT_GATE_PRETRUSTED") == "1":
        return _chat_loop()
    _write(
        b"\x1b[2J\x1b[H  Trust this folder?\r\n\r\n"
        b"     Trust this folder\r\n"
        b"   > Don't trust\r\n"
    )
    _log("menu")
    while True:
        char = os.read(0, 1)
        if not char:
            return 0
        if char in (b"\r", b"\n"):
            _log("declined_default")
            if os.environ.get("TAUT_GATE_WAIT_FOR_INJECT_RETURN") == "1":
                while True:
                    release = os.read(0, 1)
                    if not release:
                        return 0
                    if release == b"\0":
                        break
            _write(b"\r\nBye!\r\n")
            return 0
        if char == b"\x14":
            _log("trusted")
            return _chat_loop()


if __name__ == "__main__":
    raise SystemExit(main())
