"""Local-LLM-backed TUI harness for summon live tests.

This is a real PTY child. It waits for the summon orientation injection, sends
that prompt through a loopback OpenAI-compatible chat-completions endpoint, and
then posts the test sentinel through the ordinary `taut say` mouth.
"""

from __future__ import annotations

import json
import os
import select
import signal
import subprocess
import sys
import tty
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


def _write(data: bytes) -> None:
    os.write(sys.stdout.fileno(), data)


def _record(path: Path | None, event: str, **fields: Any) -> None:
    if path is None:
        return
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"event": event, **fields}, sort_keys=True) + "\n")


def _read_line() -> bytes | None:
    fd = sys.stdin.fileno()
    buf = b""
    while True:
        ready, _, _ = select.select([fd], [], [], 0.05)
        if not ready:
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


def _joined_endpoint(endpoint: str, path: str) -> str:
    return f"{endpoint.rstrip('/')}/{path.lstrip('/')}"


def _call_local_llm(prompt: str, *, log: Path | None) -> str:
    endpoint = os.environ["TAUT_SUMMON_LOCAL_LLM_ENDPOINT"]
    model = os.environ["TAUT_SUMMON_LOCAL_LLM_MODEL"]
    timeout = float(os.environ.get("TAUT_SUMMON_LOCAL_LLM_TIMEOUT", "180"))
    body = {
        "model": model,
        "stream": False,
        "temperature": 0,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a transport canary. Reply with exactly OK. Do not "
                    "run tools."
                ),
            },
            {"role": "user", "content": prompt},
        ],
    }
    request = urllib.request.Request(
        _joined_endpoint(endpoint, "chat/completions"),
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            payload = json.load(response)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        _record(log, "llm_error", status=exc.code, detail=detail[-1000:])
        raise
    content = payload.get("choices", [{}])[0].get("message", {}).get("content", "")
    text = str(content).strip()
    _record(log, "llm_response", text=text[:1000])
    return text


def _post_sentinel(target: str, sentinel: str, *, log: Path | None) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "taut", "say", target, sentinel],
        text=True,
        capture_output=True,
        timeout=30,
    )
    _record(
        log,
        "taut_say",
        returncode=result.returncode,
        stdout=result.stdout,
        stderr=result.stderr,
    )
    if result.returncode != 0:
        raise SystemExit(50)


def main() -> int:
    tty.setraw(sys.stdin.fileno())
    log = (
        Path(os.environ["TAUT_SUMMON_LOCAL_LLM_TUI_LOG"])
        if os.environ.get("TAUT_SUMMON_LOCAL_LLM_TUI_LOG")
        else None
    )
    target = os.environ["TAUT_SUMMON_LOCAL_LLM_TARGET"]
    sentinel = os.environ["TAUT_SUMMON_LOCAL_LLM_SENTINEL"]

    def _term(_signum: int, _frame: object) -> None:
        _record(log, "signal", signal="term")
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, _term)
    _record(log, "start", pid=os.getpid())
    _write(b"\r\nlocal-llm-ready\r\n")

    raw = _read_line()
    if raw is None:
        return 0
    if raw == b"\x03":
        _record(log, "interrupt")
        return 0
    prompt = _command_text(raw)
    _record(log, "orientation", text=prompt)
    if sentinel not in prompt:
        _record(log, "missing_sentinel", sentinel=sentinel)
        return 41

    _call_local_llm(prompt, log=log)
    _post_sentinel(target, sentinel, log=log)
    _write(b"\r\nlocal-llm-posted\r\n")

    while True:
        raw = _read_line()
        if raw is None:
            return 0
        if raw == b"\x03":
            _record(log, "interrupt")
            _write(b"\r\ninterrupted\r\n")


if __name__ == "__main__":
    raise SystemExit(main())
