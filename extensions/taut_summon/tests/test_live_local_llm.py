"""Local-LLM-backed live PTY smoke for summon.

This is the CI-safe live lane: a real PTY child calls a real loopback
OpenAI-compatible model endpoint, then speaks through `taut say`. It does not
replace the local-only matrix in `test_live_harness.py`; that matrix still
targets real installed harness CLIs.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from conftest import _base_env, summon_cli, taut_cli
from simplebroker import Queue
from taut_summon._state import (
    ensure_summon_schema,
    get_session,
    record_session,
    set_wired,
)

from taut import identity
from taut.client import TautClient

LOCAL_LLM_TUI = Path(__file__).with_name("fixtures") / "local_llm_tui.py"
DEFAULT_LOCAL_ENDPOINT = "http://127.0.0.1:11434/v1"
DEFAULT_LOCAL_MODEL = "taut-summon-local-model:latest"
LOCAL_HTTP_TIMEOUT_SECONDS = 10.0
LOCAL_SENTINEL_TIMEOUT_SECONDS = 240.0
_FALSEY_ENV = {"", "0", "false", "no", "off"}


@dataclass
class _CountingProxy:
    upstream_endpoint: str
    server: Any | None = None
    thread: threading.Thread | None = None
    request_bodies: list[str] = field(default_factory=list)

    def __enter__(self) -> _CountingProxy:
        import http.server

        proxy = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802 - stdlib hook name
                self._forward()

            def do_POST(self) -> None:  # noqa: N802 - stdlib hook name
                self._forward()

            def log_message(self, format: str, *args: object) -> None:
                return

            def _forward(self) -> None:
                length = int(self.headers.get("Content-Length", "0") or "0")
                body = self.rfile.read(length) if length else b""
                if self.command == "POST" and _is_completion_path(self.path):
                    proxy.request_bodies.append(body.decode("utf-8", errors="replace"))
                headers = {
                    key: value
                    for key, value in self.headers.items()
                    if key.lower()
                    not in {"host", "content-length", "connection", "accept-encoding"}
                }
                request = urllib.request.Request(
                    proxy.forward_url(self.path),
                    data=body if body else None,
                    headers=headers,
                    method=self.command,
                )
                try:
                    try:
                        with urllib.request.urlopen(
                            request, timeout=LOCAL_SENTINEL_TIMEOUT_SECONDS
                        ) as response:
                            payload = response.read()
                            self._send_response(
                                response.status,
                                response.headers.items(),
                                payload,
                            )
                    except urllib.error.HTTPError as exc:
                        self._send_response(exc.code, exc.headers.items(), exc.read())
                except Exception as exc:  # noqa: BLE001 - keep proxy diagnostics
                    payload = f"proxy forwarding error: {exc}".encode()
                    self.send_response(502)
                    self.send_header("Content-Type", "text/plain; charset=utf-8")
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)

            def _send_response(
                self,
                status: int,
                headers: Any,
                payload: bytes,
            ) -> None:
                self.send_response(status)
                for key, value in headers:
                    if key.lower() in {
                        "connection",
                        "content-length",
                        "transfer-encoding",
                    }:
                        continue
                    self.send_header(key, value)
                self.send_header("Content-Length", str(len(payload)))
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(payload)

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *exc_info: object) -> None:
        if self.server is not None:
            self.server.shutdown()
            self.server.server_close()
        if self.thread is not None:
            self.thread.join(timeout=5)

    @property
    def endpoint(self) -> str:
        assert self.server is not None
        return f"http://127.0.0.1:{self.server.server_port}/v1"

    def forward_url(self, path: str) -> str:
        if path == "/v1" or path.startswith("/v1/"):
            return _joined_endpoint(self.upstream_endpoint, path[len("/v1") :])
        origin = _endpoint_origin(self.upstream_endpoint)
        return f"{origin}{path}"


def _env_truthy(name: str) -> bool:
    value = os.environ.get(name)
    if value is None:
        return False
    return value.strip().lower() not in _FALSEY_ENV


def _env_falsey(name: str) -> bool:
    value = os.environ.get(name)
    return value is not None and value.strip().lower() in _FALSEY_ENV


def _local_llm_enabled() -> bool:
    if _env_falsey("TAUT_SUMMON_LOCAL_LLM"):
        return False
    if _env_truthy("TAUT_SUMMON_LOCAL_LLM"):
        return True
    return not _env_truthy("CI")


def _local_llm_required() -> bool:
    return _env_truthy("TAUT_SUMMON_LOCAL_LLM")


def _resolve_endpoint() -> str:
    endpoint = os.environ.get("TAUT_SUMMON_LOCAL_LLM_ENDPOINT", DEFAULT_LOCAL_ENDPOINT)
    _assert_loopback_endpoint(endpoint)
    return endpoint


def _resolve_model() -> str:
    return os.environ.get("TAUT_SUMMON_LOCAL_LLM_MODEL", DEFAULT_LOCAL_MODEL)


def _endpoint_origin(endpoint: str) -> str:
    parsed = urllib.parse.urlsplit(endpoint)
    if not parsed.scheme or not parsed.netloc:
        pytest.fail(f"local LLM endpoint must be absolute, got {endpoint!r}")
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))


def _joined_endpoint(endpoint: str, path: str) -> str:
    return f"{endpoint.rstrip('/')}/{path.lstrip('/')}"


def _is_completion_path(path: str) -> bool:
    return path.startswith("/v1/") and "completions" in path


def _assert_loopback_endpoint(endpoint: str) -> None:
    if os.environ.get("TAUT_SUMMON_LOCAL_LLM_ALLOW_NONLOCAL") == "1":
        return
    parsed = urllib.parse.urlsplit(endpoint)
    if parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        pytest.fail(
            "TAUT_SUMMON_LOCAL_LLM requires a loopback endpoint; set "
            "TAUT_SUMMON_LOCAL_LLM_ALLOW_NONLOCAL=1 only for a deliberate "
            f"non-local test endpoint (got {endpoint!r})"
        )


def _read_json_url(url: str) -> dict[str, object]:
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(
        request, timeout=LOCAL_HTTP_TIMEOUT_SECONDS
    ) as response:
        payload = json.load(response)
    if not isinstance(payload, dict):
        pytest.fail(f"{url} returned non-object JSON: {payload!r}")
    return payload


def _endpoint_has_model(endpoint: str, model: str) -> bool:
    try:
        payload = _read_json_url(_joined_endpoint(endpoint, "models"))
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError):
        return False
    raw_data = payload.get("data")
    if not isinstance(raw_data, list):
        return False
    ids = [
        str(item.get("id"))
        for item in raw_data
        if isinstance(item, dict) and item.get("id") is not None
    ]
    return model in ids


def _entries(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _sentinel_posted(db: Path, sentinel: str) -> bool:
    return any(
        message.text == sentinel for message in TautClient(db_path=db).log("general")
    )


def _tail(path: Path, *, limit: int = 4000) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")[-limit:]


def _local_llm_capture() -> identity.IdentityCapture:
    process = identity.ProcessInfo(
        pid=os.getpid(),
        ppid=1,
        start_time="local-llm-live-test",
        exe=str(LOCAL_LLM_TUI),
        argv=(sys.executable, str(LOCAL_LLM_TUI)),
        uid=os.getuid() if hasattr(os, "getuid") else 0,
        pgid=os.getpgrp() if hasattr(os, "getpgrp") else os.getpid(),
        session_id=os.getsid(0) if hasattr(os, "getsid") else None,
        tty=None,
        cwd="/taut-local-llm-live-test",
    )
    return identity.IdentityCapture(
        chain=(process,),
        host=identity.HostIdentity("host:taut-local-llm", "taut-local-llm"),
        uid=process.uid or 0,
        login="taut-local-llm",
        anchor=process,
        kind="agent",
        rule="local LLM live test setup",
    )


def _prewire_local_llm(db: Path) -> None:
    client = TautClient(
        db_path=db,
        as_name="local-llm",
        identity_capture=_local_llm_capture(),
    )
    client.join("general")
    member = client.last_created_member or client.whoami()
    assert member.token is not None
    queue = Queue("taut_summon_state", db_path=str(db))
    try:
        ensure_summon_schema(queue)
        record_session(
            queue,
            member_id=member.member_id,
            token=member.token,
            provider="pty",
            provider_session_id=None,
            driver_pid=None,
            driver_start_time=None,
            updated_ts=queue.generate_timestamp(),
        )
        set_wired(
            queue,
            member_id=member.member_id,
            value=True,
            updated_ts=queue.generate_timestamp(),
        )
    finally:
        queue.close()


def test_local_llm_runs_locally_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TAUT_SUMMON_LOCAL_LLM", raising=False)
    monkeypatch.delenv("CI", raising=False)

    assert _local_llm_enabled()


def test_local_llm_skips_unprepared_ci_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("TAUT_SUMMON_LOCAL_LLM", raising=False)
    monkeypatch.setenv("CI", "true")

    assert not _local_llm_enabled()


def test_local_llm_env_can_enable_ci(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CI", "true")
    monkeypatch.setenv("TAUT_SUMMON_LOCAL_LLM", "1")

    assert _local_llm_enabled()


def test_local_llm_env_can_disable_local(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.setenv("TAUT_SUMMON_LOCAL_LLM", "0")

    assert not _local_llm_enabled()


def test_local_llm_prewire_marks_pty_member_wired(tmp_path: Path) -> None:
    db = tmp_path / ".taut.db"
    TautClient.init(db_path=db)
    taut_cli("join", "general", db=db, cwd=tmp_path, as_name="van")

    _prewire_local_llm(db)

    member = next(
        member for member in TautClient(db_path=db).who() if member.name == "local-llm"
    )
    queue = Queue("taut_summon_state", db_path=str(db))
    try:
        row = get_session(queue, member.member_id)
    finally:
        queue.close()
    assert row is not None
    assert row["provider"] == "pty"
    assert row["wired"] is True


@pytest.mark.requires_local_llm
@pytest.mark.xdist_group("process")
def test_local_llm_pty_harness_posts_sentinel(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if not _local_llm_enabled():
        pytest.skip(
            "local LLM live tests run locally by default; set "
            "TAUT_SUMMON_LOCAL_LLM=1 in prepared CI or 0 to skip locally"
        )

    upstream = _resolve_endpoint()
    model = _resolve_model()
    if not _endpoint_has_model(upstream, model):
        message = (
            f"local LLM endpoint {upstream!r} did not list model {model!r}; "
            "start Ollama and pull/create the model before running this lane"
        )
        if _local_llm_required():
            pytest.fail(message)
        pytest.skip(message)

    db = tmp_path / ".taut.db"
    TautClient.init(db_path=db)
    rc, _out, err = taut_cli("join", "general", db=db, cwd=tmp_path, as_name="van")
    assert rc == 0, err
    _prewire_local_llm(db)

    sentinel = f"local-llm-sentinel-{time.monotonic_ns()}"
    prompt = tmp_path / "orientation.txt"
    prompt.write_text(
        "This is a local LLM transport smoke. After reading this message, "
        f"post sentinel {sentinel!r} to #general through taut say.\n",
        encoding="utf-8",
    )
    tui_log = tmp_path / "local-llm-tui.jsonl"
    driver_stderr = tmp_path / "local-llm-driver.err"

    with _CountingProxy(upstream) as proxy:
        env = _base_env()
        env.update(
            {
                "TAUT_SUMMON_PTY_ARGV": json.dumps(
                    [sys.executable, str(LOCAL_LLM_TUI)]
                ),
                "TAUT_SUMMON_PTY_QUIET_MS": "50",
                "TAUT_SUMMON_PTY_MAX_SETTLE_S": "0.5",
                "TAUT_SUMMON_LOCAL_LLM_ENDPOINT": proxy.endpoint,
                "TAUT_SUMMON_LOCAL_LLM_MODEL": model,
                "TAUT_SUMMON_LOCAL_LLM_TARGET": "general",
                "TAUT_SUMMON_LOCAL_LLM_SENTINEL": sentinel,
                "TAUT_SUMMON_LOCAL_LLM_TUI_LOG": str(tui_log),
            }
        )
        stderr_handle = driver_stderr.open("w", encoding="utf-8")
        proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "taut_summon",
                "run",
                "local-llm",
                "general",
                "--provider",
                "pty",
                "--detach",
                "--system-prompt-file",
                str(prompt),
                "--db",
                str(db),
            ],
            cwd=tmp_path,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=stderr_handle,
            text=True,
        )
        try:
            deadline = time.monotonic() + LOCAL_SENTINEL_TIMEOUT_SECONDS
            while time.monotonic() < deadline:
                if _sentinel_posted(db, sentinel):
                    break
                if proc.poll() is not None:
                    pytest.fail(
                        "local LLM summon driver exited before sentinel landed: "
                        f"{_tail(driver_stderr)}"
                    )
                time.sleep(0.5)
            else:
                rc, out, err = summon_cli(
                    "status", "local-llm", db=db, cwd=tmp_path, timeout=10.0
                )
                pytest.fail(
                    "local LLM PTY harness did not post sentinel; "
                    f"driver_rc={proc.poll()!r}; "
                    f"status_rc={rc}; status_out={out!r}; status_err={err!r}; "
                    f"log={_entries(tui_log)!r}; stderr={_tail(driver_stderr)}"
                )
        finally:
            summon_cli("stop", "local-llm", db=db, cwd=tmp_path, timeout=30.0)
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=10.0)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=10.0)
            stderr_handle.close()

    assert proxy.request_bodies, "local LLM TUI did not call the counting proxy"
    bodies = [json.loads(body) for body in proxy.request_bodies]
    assert all(body.get("model") == model for body in bodies)
    entries = _entries(tui_log)
    assert any(entry.get("event") == "orientation" for entry in entries)
    assert any(entry.get("event") == "llm_response" for entry in entries)
    assert any(entry.get("event") == "taut_say" for entry in entries)
