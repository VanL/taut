"""Local-LLM-backed live PTY smoke for summon.

This is the CI-safe live lane: a real PTY child calls a real loopback
OpenAI-compatible model endpoint, then speaks through `taut say`. It does not
replace the local-only matrix in `test_live_harness.py`; that matrix still
targets real installed harness CLIs.
"""

from __future__ import annotations

import json
import os
import select
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, NoReturn

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


@dataclass
class _StubCompletionEndpoint:
    payload: bytes
    status: int = 200
    delay_seconds: float = 0.0
    server: Any | None = None
    thread: threading.Thread | None = None

    def __enter__(self) -> _StubCompletionEndpoint:
        import http.server

        stub = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802 - stdlib hook name
                length = int(self.headers.get("Content-Length", "0") or "0")
                if length:
                    self.rfile.read(length)
                if stub.delay_seconds:
                    time.sleep(stub.delay_seconds)
                self.send_response(stub.status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(stub.payload)))
                self.end_headers()
                try:
                    self.wfile.write(stub.payload)
                except (BrokenPipeError, ConnectionResetError):
                    pass

            def log_message(self, format: str, *args: object) -> None:
                return

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *exc_info: object) -> None:
        if self.server is not None:
            self.server.shutdown()
            self.server.server_close()
        if self.thread is not None:
            self.thread.join(timeout=2.0)

    @property
    def endpoint(self) -> str:
        assert self.server is not None
        return f"http://127.0.0.1:{self.server.server_port}/v1"


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


def _local_llm_failure_message(
    reason: str,
    *,
    driver_stderr: Path,
    tui_log: Path,
    proxy_request_count: int,
    detail: str | None = None,
) -> str:
    fields = [reason]
    if detail:
        fields.append(detail)
    fields.extend(
        [
            f"proxy_request_count={proxy_request_count}",
            f"tui_event_log={_tail(tui_log)!r}",
            f"driver_stderr={_tail(driver_stderr)!r}",
        ]
    )
    return "; ".join(fields)


def _fail_local_llm_smoke(
    reason: str,
    *,
    driver_stderr: Path,
    tui_log: Path,
    proxy_request_count: int,
    detail: str | None = None,
) -> NoReturn:
    pytest.fail(
        _local_llm_failure_message(
            reason,
            driver_stderr=driver_stderr,
            tui_log=tui_log,
            proxy_request_count=proxy_request_count,
            detail=detail,
        )
    )


def _driver_used_harness_recovery(stderr: str) -> bool:
    return any(
        marker in stderr
        for marker in (
            "harness exited",
            "resuming in ",
        )
    )


def _run_failing_local_llm_child(
    tmp_path: Path,
    *,
    endpoint: str,
    request_timeout: float = 0.2,
) -> tuple[int, str, list[dict[str, object]]]:
    pty = pytest.importorskip("pty", reason="local LLM child requires a POSIX PTY")
    master_fd, slave_fd = pty.openpty()
    event_log = tmp_path / "child-events.jsonl"
    sentinel = "expected-child-error-sentinel"
    env = os.environ.copy()
    env.update(
        {
            "TAUT_SUMMON_LOCAL_LLM_ENDPOINT": endpoint,
            "TAUT_SUMMON_LOCAL_LLM_MODEL": "stub-model",
            "TAUT_SUMMON_LOCAL_LLM_TARGET": "general",
            "TAUT_SUMMON_LOCAL_LLM_SENTINEL": sentinel,
            "TAUT_SUMMON_LOCAL_LLM_TIMEOUT": str(request_timeout),
            "TAUT_SUMMON_LOCAL_LLM_TUI_LOG": str(event_log),
        }
    )
    proc = subprocess.Popen(
        [sys.executable, str(LOCAL_LLM_TUI)],
        stdin=slave_fd,
        stdout=slave_fd,
        stderr=subprocess.PIPE,
        cwd=tmp_path,
        env=env,
    )
    os.close(slave_fd)
    try:
        output = b""
        deadline = time.monotonic() + 2.0
        while b"local-llm-ready" not in output and time.monotonic() < deadline:
            ready, _, _ = select.select([master_fd], [], [], 0.05)
            if ready:
                output += os.read(master_fd, 4096)
            elif proc.poll() is not None:
                break
        assert b"local-llm-ready" in output, output
        os.write(master_fd, f"orientation {sentinel}\r".encode())
        _stdout, stderr = proc.communicate(timeout=4.0)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=2.0)
        os.close(master_fd)
    assert stderr is not None
    return proc.returncode, stderr.decode(errors="replace"), _entries(event_log)


def _assert_concise_child_error(
    result: tuple[int, str, list[dict[str, object]]],
    *,
    expected_kind: str,
) -> None:
    returncode, stderr, events = result
    assert returncode != 0
    assert "Traceback" not in stderr
    assert len(stderr) < 500
    assert stderr.count("\n") == 1
    assert any(
        event.get("event") == "llm_error" and event.get("kind") == expected_kind
        for event in events
    ), events


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
    queue = Queue("taut.summon_state", db_path=str(db))
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


def test_local_llm_child_reports_url_failure_without_traceback(tmp_path: Path) -> None:
    result = _run_failing_local_llm_child(
        tmp_path,
        endpoint="gopher://127.0.0.1/v1",
    )

    _assert_concise_child_error(result, expected_kind="url_error")


def test_local_llm_child_reports_timeout_without_traceback(tmp_path: Path) -> None:
    with _StubCompletionEndpoint(
        b'{"choices":[{"message":{"content":"OK"}}]}',
        delay_seconds=0.25,
    ) as endpoint:
        result = _run_failing_local_llm_child(
            tmp_path,
            endpoint=endpoint.endpoint,
            request_timeout=0.05,
        )

    _assert_concise_child_error(result, expected_kind="timeout")


def test_local_llm_child_reports_http_failure_without_traceback(tmp_path: Path) -> None:
    with _StubCompletionEndpoint(b'{"error":"model failed"}', status=500) as endpoint:
        result = _run_failing_local_llm_child(
            tmp_path,
            endpoint=endpoint.endpoint,
        )

    _assert_concise_child_error(result, expected_kind="http_error")


@pytest.mark.parametrize(
    ("payload", "expected_kind"),
    [
        pytest.param(b"{", "invalid_json", id="invalid-json"),
        pytest.param(b"[]", "response_not_object", id="wrong-top-level-type"),
        pytest.param(
            b'{"choices":42}',
            "missing_choices",
            id="choices-not-list",
        ),
        pytest.param(b'{"choices":[]}', "empty_choices", id="empty-choices"),
        pytest.param(b'{"choices":[{}]}', "missing_message", id="missing-message"),
        pytest.param(
            b'{"choices":[{"message":{}}]}',
            "missing_content",
            id="missing-content",
        ),
    ],
)
def test_local_llm_child_reports_malformed_response_without_traceback(
    tmp_path: Path,
    payload: bytes,
    expected_kind: str,
) -> None:
    with _StubCompletionEndpoint(payload) as endpoint:
        result = _run_failing_local_llm_child(
            tmp_path,
            endpoint=endpoint.endpoint,
        )

    _assert_concise_child_error(result, expected_kind=expected_kind)


def test_local_llm_driver_early_exit_diagnostic_retains_evidence(
    tmp_path: Path,
) -> None:
    driver_stderr = tmp_path / "driver.err"
    driver_stderr.write_text("driver exploded\n", encoding="utf-8")
    tui_log = tmp_path / "tui.jsonl"
    tui_log.write_text('{"event":"llm_error","kind":"url_error"}\n', encoding="utf-8")

    with pytest.raises(pytest.fail.Exception) as exc_info:
        _fail_local_llm_smoke(
            "local LLM summon driver exited before sentinel landed",
            driver_stderr=driver_stderr,
            tui_log=tui_log,
            proxy_request_count=2,
        )

    message = str(exc_info.value)
    assert "driver exploded" in message
    assert "url_error" in message
    assert "proxy_request_count=2" in message


def test_local_llm_sentinel_timeout_diagnostic_retains_evidence(
    tmp_path: Path,
) -> None:
    driver_stderr = tmp_path / "driver.err"
    driver_stderr.write_text("driver still running\n", encoding="utf-8")
    tui_log = tmp_path / "tui.jsonl"
    tui_log.write_text('{"event":"llm_response","text":"OK"}\n', encoding="utf-8")

    with pytest.raises(pytest.fail.Exception) as exc_info:
        _fail_local_llm_smoke(
            "local LLM PTY harness did not post sentinel",
            driver_stderr=driver_stderr,
            tui_log=tui_log,
            proxy_request_count=1,
            detail="driver_rc=None; status_rc=0; status_out='RUNNING'",
        )

    message = str(exc_info.value)
    assert "driver still running" in message
    assert "llm_response" in message
    assert "proxy_request_count=1" in message
    assert "status_out='RUNNING'" in message


@pytest.mark.parametrize(
    "line",
    [
        "harness exited with code 1",
        "harness exited (code 1); resuming in 1.0s",
    ],
)
def test_local_llm_lifecycle_evidence_detects_harness_recovery(line: str) -> None:
    assert _driver_used_harness_recovery(f"INFO {line}\n")
    assert not _driver_used_harness_recovery("INFO summoned 'local-llm'\n")


def test_local_llm_prewire_marks_pty_member_wired(tmp_path: Path) -> None:
    db = tmp_path / ".taut.db"
    TautClient.init(db_path=db)
    taut_cli("join", "general", db=db, cwd=tmp_path, as_name="van")

    _prewire_local_llm(db)

    member = next(
        member for member in TautClient(db_path=db).who() if member.name == "local-llm"
    )
    queue = Queue("taut.summon_state", db_path=str(db))
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
                "TAUT_SUMMON_PTY_QUIET_MS": "250",
                "TAUT_SUMMON_PTY_MAX_SETTLE_S": "5.0",
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
                    lifecycle_stderr = _tail(driver_stderr)
                    if _driver_used_harness_recovery(lifecycle_stderr):
                        _fail_local_llm_smoke(
                            "local LLM harness exited or resumed before "
                            "sentinel success",
                            driver_stderr=driver_stderr,
                            tui_log=tui_log,
                            proxy_request_count=len(proxy.request_bodies),
                        )
                    break
                if proc.poll() is not None:
                    _fail_local_llm_smoke(
                        "local LLM summon driver exited before sentinel landed",
                        driver_stderr=driver_stderr,
                        tui_log=tui_log,
                        proxy_request_count=len(proxy.request_bodies),
                    )
                time.sleep(0.5)
            else:
                rc, out, err = summon_cli(
                    "status", "local-llm", db=db, cwd=tmp_path, timeout=10.0
                )
                _fail_local_llm_smoke(
                    "local LLM PTY harness did not post sentinel",
                    driver_stderr=driver_stderr,
                    tui_log=tui_log,
                    proxy_request_count=len(proxy.request_bodies),
                    detail=(
                        f"driver_rc={proc.poll()!r}; status_rc={rc}; "
                        f"status_out={out!r}; status_err={err!r}"
                    ),
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

    if len(proxy.request_bodies) != 1:
        _fail_local_llm_smoke(
            "local LLM TUI must make exactly one completion request",
            driver_stderr=driver_stderr,
            tui_log=tui_log,
            proxy_request_count=len(proxy.request_bodies),
        )
    bodies = [json.loads(body) for body in proxy.request_bodies]
    assert all(body.get("model") == model for body in bodies)
    entries = _entries(tui_log)
    assert any(entry.get("event") == "orientation" for entry in entries)
    assert any(entry.get("event") == "llm_response" for entry in entries)
    assert any(entry.get("event") == "taut_say" for entry in entries)
