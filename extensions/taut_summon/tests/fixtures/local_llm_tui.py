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
from typing import Any, NoReturn


class _LocalLLMFailure(Exception):
    def __init__(self, kind: str, detail: str) -> None:
        super().__init__(detail)
        self.kind = kind
        self.detail = detail


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


def _concise_detail(value: object, *, limit: int = 300) -> str:
    text = " ".join(str(value).split())
    if len(text) <= limit:
        return text
    return f"{text[: limit - 3]}..."


def _llm_failure(
    log: Path | None,
    kind: str,
    detail: str,
    **fields: Any,
) -> NoReturn:
    concise = _concise_detail(detail)
    _record(log, "llm_error", kind=kind, detail=concise, **fields)
    raise _LocalLLMFailure(kind, concise)


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
            raw_payload = response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        _llm_failure(
            log,
            "http_error",
            f"HTTP {exc.code}: {detail[-1000:]}",
            status=exc.code,
        )
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, TimeoutError):
            _llm_failure(log, "timeout", f"request timed out after {timeout:g}s")
        _llm_failure(log, "url_error", f"request failed: {exc.reason}")
    except TimeoutError:
        _llm_failure(log, "timeout", f"request timed out after {timeout:g}s")

    try:
        payload = json.loads(raw_payload)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        _llm_failure(log, "invalid_json", f"invalid JSON response: {exc}")
    if not isinstance(payload, dict):
        _llm_failure(
            log,
            "response_not_object",
            f"response must be an object, got {type(payload).__name__}",
        )
    choices = payload.get("choices")
    if not isinstance(choices, list):
        _llm_failure(log, "missing_choices", "response choices must be a list")
    if not choices:
        _llm_failure(log, "empty_choices", "response choices list is empty")
    choice = choices[0]
    if not isinstance(choice, dict) or not isinstance(choice.get("message"), dict):
        _llm_failure(log, "missing_message", "first choice has no message object")
    message = choice["message"]
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        _llm_failure(log, "missing_content", "first choice message has no content")
    text = content.strip()
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

    try:
        _call_local_llm(prompt, log=log)
    except _LocalLLMFailure as exc:
        print(
            f"local LLM request failed ({exc.kind}): {exc.detail}",
            file=sys.stderr,
        )
        return 42
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
