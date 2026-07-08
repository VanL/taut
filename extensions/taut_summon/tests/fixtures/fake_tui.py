"""Fake full-screen TUI harness for PTY adapter tests.

This program runs as a real child on a PTY slave. It emits terminal report
requests, optional full-screen mode enables, and records raw bytes received
from summon. It intentionally uses only stdlib so the PTY seam stays identical
to production.
"""

from __future__ import annotations

import json
import os
import select
import signal
import subprocess
import sys
import time
import tty
from pathlib import Path
from typing import Any

ESC = b"\x1b"
BEL = b"\x07"
ST = ESC + b"\\"
REDRAW = True


def _write(data: bytes) -> None:
    os.write(sys.stdout.fileno(), data)


def _read_until(pattern: bytes, *, timeout: float = 5.0) -> bytes:
    deadline = time.monotonic() + timeout
    buf = b""
    fd = sys.stdin.fileno()
    while time.monotonic() < deadline:
        ready, _, _ = select.select([fd], [], [], 0.05)
        if not ready:
            continue
        chunk = os.read(fd, 4096)
        if not chunk:
            break
        buf += chunk
        if pattern in buf:
            return buf
    return buf


def _record(path: Path | None, event: str, **fields: Any) -> None:
    if path is None:
        return
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"event": event, **fields}, sort_keys=True) + "\n")


def _expect_reply(
    *,
    record_path: Path | None,
    name: str,
    query: bytes,
    expected: bytes,
    timeout: float = 5.0,
) -> None:
    _write(query)
    got = _read_until(expected, timeout=timeout)
    _record(
        record_path,
        "query",
        name=name,
        query=query.decode("latin1"),
        expected=expected.decode("latin1"),
        got=got.decode("latin1"),
        ok=expected in got,
    )
    if expected not in got:
        raise SystemExit(40)


def _run_queries(record_path: Path | None, rows: int, cols: int) -> None:
    pos = f"\x1b[{rows};{cols}R".encode()
    _expect_reply(
        record_path=record_path,
        name="absolute-size",
        query=b"\x1b[999;999H\x1b[6n",
        expected=pos,
    )
    _expect_reply(
        record_path=record_path,
        name="relative-size",
        query=b"\x1b[1;1H\x1b[9999C\x1b[9999B\x1b[6n",
        expected=pos,
    )
    _expect_reply(
        record_path=record_path,
        name="dsr-status",
        query=b"\x1b[5n",
        expected=b"\x1b[0n",
    )
    _expect_reply(
        record_path=record_path,
        name="primary-da",
        query=b"\x1b[c",
        expected=b"\x1b[?1;2c",
    )
    _expect_reply(
        record_path=record_path,
        name="secondary-da",
        query=b"\x1b[>c",
        expected=b"\x1b[>0;0;0c",
    )
    _expect_reply(
        record_path=record_path,
        name="decrqm",
        query=b"\x1b[?2004$p",
        expected=b"\x1b[?2004;0$y",
    )
    _expect_reply(
        record_path=record_path,
        name="xtversion",
        query=b"\x1b[>q",
        expected=b"\x1bP>|taut-summon(0)\x1b\\",
    )
    _expect_reply(
        record_path=record_path,
        name="osc-fg",
        query=b"\x1b]10;?\x07",
        expected=b"\x1b]10;rgb:",
    )
    _expect_reply(
        record_path=record_path,
        name="osc-bg",
        query=b"\x1b]11;?\x07",
        expected=b"\x1b]11;rgb:",
    )
    _expect_reply(
        record_path=record_path,
        name="kitty-keyboard",
        query=b"\x1b[?u",
        expected=b"\x1b[?0u",
    )


def _read_line() -> bytes | None:
    fd = sys.stdin.fileno()
    buf = b""
    while True:
        ready, _, _ = select.select([fd], [], [], 0.05)
        if not ready:
            if REDRAW:
                _write(b"\x1b[2K\rready")
            continue
        chunk = os.read(fd, 4096)
        if not chunk:
            return None
        buf += chunk
        if b"\x03" in chunk:
            return b"\x03"
        if buf.startswith(b"\x1b[200~"):
            if b"\x1b[201~\r" in buf or b"\x1b[201~\n" in buf:
                return buf
            continue
        if b"\r" in buf or b"\n" in buf:
            return buf


def _command_text(raw: bytes) -> str:
    text = raw
    if text.startswith(b"\x1b[200~") and b"\x1b[201~" in text:
        text = text[len(b"\x1b[200~") : text.index(b"\x1b[201~")]
    text = text.replace(b"\r", b"").replace(b"\n", b"")
    return text.decode("utf-8", errors="replace")


def main() -> int:
    global REDRAW
    tty.setraw(sys.stdin.fileno())
    config = json.loads(os.environ.get("TAUT_FAKE_TUI_CONFIG", "{}"))
    REDRAW = bool(config.get("redraw", True))
    record_path = (
        Path(os.environ["TAUT_FAKE_TUI_LOG"])
        if os.environ.get("TAUT_FAKE_TUI_LOG")
        else None
    )
    rows = int(os.environ.get("TAUT_FAKE_TUI_ROWS", "24"))
    cols = int(os.environ.get("TAUT_FAKE_TUI_COLS", "80"))

    def _term(_signum: int, _frame: object) -> None:
        _record(record_path, "signal", signal="term")
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, _term)
    _record(record_path, "start", pid=os.getpid())

    if config.get("modes", True):
        _write(
            b"\x1b[?1049h\x1b[?25l\x1b[31m\x1b[?7l\x1b[?2026h"
            b"\x1b[?1007h\x1b[?1h\x1b=\x1b[?1004h"
            b"\x1b[?1000h\x1b[?1002h\x1b[?1003h\x1b[?1005h"
            b"\x1b[?1006h\x1b[?1015h\x1b[?2004h\x1b[>1u"
        )
    if config.get("queries", True):
        _run_queries(record_path, rows, cols)
    if unknown := config.get("unknown_query"):
        query = str(unknown).encode("ascii")
        if not query.startswith(ESC):
            query = ESC + query
        _write(query)
        _record(record_path, "unknown_query", query=query.decode("latin1"))
        if config.get("unknown_blocks", False):
            got = _read_until(b"\x00", timeout=0.3)
            _record(
                record_path,
                "unknown_reply_window",
                got=got.decode("latin1"),
            )
            while True:
                time.sleep(1)
    if config.get("onboarding"):
        _write(b"\r\nTrust this directory? Type yes and press enter.\r\n")
        onboarding = _read_line()
        _record(
            record_path,
            "onboarding_input",
            raw=(onboarding or b"").decode("latin1"),
        )
    _write(b"\r\nready\r\n")

    while True:
        raw = _read_line()
        if raw is None:
            return 0
        _record(record_path, "input", raw=raw.decode("latin1"))
        if raw == b"\x03":
            _record(record_path, "interrupt")
            _write(b"\r\ninterrupted\r\n")
            continue
        text = _command_text(raw)
        if text.startswith("RUN "):
            result = subprocess.run(
                text[4:],
                shell=True,
                text=True,
                capture_output=True,
                timeout=30,
            )
            _record(
                record_path,
                "run",
                returncode=result.returncode,
                stdout=result.stdout,
                stderr=result.stderr,
            )
        else:
            _write(("echo:" + text + "\r\n").encode())


if __name__ == "__main__":
    raise SystemExit(main())
