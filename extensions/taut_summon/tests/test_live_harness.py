"""Live PTY harness reachability checks ([SUM-12]).

Local pytest runs attempt this matrix by default after the target harness has
been onboarded/authed through ``taut summon --attach`` at least once. CI skips
the matrix unless ``TAUT_SUMMON_LIVE_HARNESS=1`` is set; local fast loops can
set ``TAUT_SUMMON_LIVE_HARNESS=0``.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest
from conftest import _base_env, summon_cli, taut_cli
from simplebroker import Queue
from taut_summon._state import ensure_summon_schema, record_session, set_wired

from taut import identity
from taut.client import TautClient

_HARNESSES = (
    pytest.param("claude", marks=pytest.mark.requires_claude),
    pytest.param("codex", marks=pytest.mark.requires_codex),
    pytest.param("coder", marks=pytest.mark.requires_coder),
    pytest.param("grok", marks=pytest.mark.requires_grok),
    pytest.param("qwen", marks=pytest.mark.requires_qwen),
    pytest.param("kimi", marks=pytest.mark.requires_kimi),
    pytest.param("opencode", marks=pytest.mark.requires_opencode),
    pytest.param("pi", marks=pytest.mark.requires_pi),
)

_FALSEY_ENV = {"", "0", "false", "no", "off"}


def _env_truthy(name: str) -> bool:
    value = os.environ.get(name)
    if value is None:
        return False
    return value.strip().lower() not in _FALSEY_ENV


def _live_harness_enabled() -> bool:
    configured = os.environ.get("TAUT_SUMMON_LIVE_HARNESS")
    if configured is not None:
        return configured.strip().lower() not in _FALSEY_ENV
    return not _env_truthy("CI")


def _strict_live_harness() -> bool:
    return _env_truthy("TAUT_SUMMON_LIVE_HARNESS_STRICT")


def _live_harness_timeout() -> float:
    return float(os.environ.get("TAUT_SUMMON_LIVE_HARNESS_TIMEOUT", "45.0"))


def _not_ready_reason(status_text: str) -> str | None:
    if "awaiting_onboarding=true" in status_text:
        return (
            "driver reports awaiting_onboarding=true; run "
            "`taut summon --attach <name>` from a real terminal for this "
            "provider/database before expecting detached live reachability"
        )
    return None


def _status_field(status_text: str, key: str) -> str | None:
    prefix = f"{key}="
    for part in status_text.split("\t"):
        if part.startswith(prefix):
            return part.removeprefix(prefix)
    return None


def _file_tail(path: Path, limit: int = 2_000) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")[-limit:]


def _fatal_readiness_reason(status_text: str) -> str | None:
    if "awaiting_query=" in status_text:
        return (
            "driver reports an unanswered terminal query; the PTY responder "
            f"needs coverage for this harness ({status_text})"
        )
    error = _status_field(status_text, "error")
    if error is not None:
        return f"driver status is unavailable: {error}"
    control_health = _status_field(status_text, "control_health")
    if control_health != "ok":
        detail = _status_field(status_text, "health_detail")
        suffix = f": {detail}" if detail else ""
        return f"driver control health is {control_health or 'missing'}{suffix}"
    return None


def _harness_capture(provider: str) -> identity.IdentityCapture:
    process = identity.ProcessInfo(
        pid=os.getpid(),
        ppid=1,
        start_time=f"live-harness-{provider}",
        exe=f"/usr/local/bin/{provider}",
        argv=(provider,),
        uid=os.getuid() if hasattr(os, "getuid") else 0,
        pgid=os.getpgrp() if hasattr(os, "getpgrp") else os.getpid(),
        session_id=os.getsid(0) if hasattr(os, "getsid") else None,
        tty=None,
        cwd=f"/taut-live-harness/{provider}",
    )
    return identity.IdentityCapture(
        chain=(process,),
        host=identity.HostIdentity("host:taut-live-harness", "taut-live-harness"),
        uid=process.uid or 0,
        login="taut-live-harness",
        anchor=process,
        kind="agent",
        rule="live harness test setup",
    )


def _prewire_live_harness(db: Path, provider: str) -> None:
    client = TautClient(
        db_path=db,
        as_name=provider,
        identity_capture=_harness_capture(provider),
    )
    client.join("general")
    member = client.last_created_member or client.whoami()
    assert member.token is not None
    queue = Queue("taut.summon_state", db_path=str(db))
    ensure_summon_schema(queue)
    record_session(
        queue,
        member_id=member.member_id,
        token=member.token,
        provider=provider,
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


def _finished_stderr_tail(proc: subprocess.Popen[str], *, limit: int = 500) -> str:
    if proc.stderr is None or proc.poll() is None:
        return ""
    tail = proc.stderr.read()
    if not isinstance(tail, str):
        return ""
    return tail[-limit:]


def test_live_harness_runs_locally_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TAUT_SUMMON_LIVE_HARNESS", raising=False)
    monkeypatch.delenv("CI", raising=False)

    assert _live_harness_enabled()


def test_live_harness_skips_in_ci_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("TAUT_SUMMON_LIVE_HARNESS", raising=False)
    monkeypatch.setenv("CI", "true")

    assert not _live_harness_enabled()


def test_live_harness_env_overrides_ci(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CI", "true")
    monkeypatch.setenv("TAUT_SUMMON_LIVE_HARNESS", "1")

    assert _live_harness_enabled()


def test_live_harness_env_can_disable_local(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.setenv("TAUT_SUMMON_LIVE_HARNESS", "0")

    assert not _live_harness_enabled()


def test_live_harness_strict_mode_is_explicit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("TAUT_SUMMON_LIVE_HARNESS_STRICT", raising=False)
    assert not _strict_live_harness()

    monkeypatch.setenv("TAUT_SUMMON_LIVE_HARNESS_STRICT", "1")
    assert _strict_live_harness()


def test_live_status_not_ready_reason_names_onboarding() -> None:
    reason = _not_ready_reason(
        "claude\tprovider=claude\tdriver=alive\tawaiting_onboarding=true"
    )

    assert reason is not None
    assert "awaiting_onboarding=true" in reason
    assert "taut summon --attach" in reason


def test_live_status_not_ready_reason_names_query_gap() -> None:
    reason = _fatal_readiness_reason("codex\tprovider=codex\tawaiting_query=[?15n")

    assert reason is not None
    assert "terminal query" in reason
    assert "[?15n" in reason


def test_live_status_fatal_reason_names_control_health_gap() -> None:
    reason = _fatal_readiness_reason(
        "codex\tprovider=codex\tdriver=alive\tcontrol_health=degraded"
    )

    assert reason == "driver control health is degraded"


def test_live_status_fatal_reason_names_status_error() -> None:
    reason = _fatal_readiness_reason(
        "codex\tprovider=codex\tdriver=alive\terror=status unavailable"
    )

    assert reason == "driver status is unavailable: status unavailable"


def test_live_status_not_ready_reason_allows_plain_alive_status() -> None:
    status = "claude\tprovider=claude\tdriver=alive\tcontrol_health=ok"

    assert _fatal_readiness_reason(status) is None
    assert _not_ready_reason(status) is None


@pytest.mark.requires_live_harness
@pytest.mark.xdist_group("process")
@pytest.mark.parametrize("provider", _HARNESSES)
def test_live_pty_harness_reaches_ready_and_accepts_injection(
    tmp_path: Path, provider: str
) -> None:
    if not _live_harness_enabled():
        pytest.skip(
            "live harness tests run locally by default; set "
            "TAUT_SUMMON_LIVE_HARNESS=1 in CI or 0 to skip locally"
        )
    if shutil.which(provider) is None:
        if _strict_live_harness():
            pytest.fail(f"{provider} binary is absent")
        pytest.skip(f"{provider} binary is absent")

    db = tmp_path / ".taut.db"
    TautClient.init(db_path=db)
    rc, _out, err = taut_cli("join", "general", db=db, cwd=tmp_path, as_name="van")
    assert rc == 0, err
    if _strict_live_harness():
        _prewire_live_harness(db, provider)

    prompt = tmp_path / "orientation.txt"
    prompt.write_text(
        "You are a summoned taut member. Stay idle and wait for chat. "
        "Do not run shell commands for this reachability smoke.\n",
        encoding="utf-8",
    )
    env = _base_env()
    env["TAUT_SUMMON_LOG"] = "DEBUG"
    stderr_path = tmp_path / f"{provider}.err"
    stderr_file = open(stderr_path, "w", encoding="utf-8")
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "taut_summon",
            "run",
            provider,
            "general",
            "--provider",
            provider,
            "--detach",
            "--system-prompt-file",
            str(prompt),
            "--db",
            str(db),
        ],
        cwd=tmp_path,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=stderr_file,
        text=True,
    )
    try:
        deadline = time.monotonic() + _live_harness_timeout()
        last_status = ""
        ready_status = ""

        while time.monotonic() < deadline:
            if proc.poll() is not None:
                stderr = _finished_stderr_tail(proc)
                if _strict_live_harness():
                    pytest.fail(
                        f"{provider} did not reach a ready detached session: "
                        f"{stderr[-500:]}"
                    )
                pytest.skip(
                    f"{provider} did not reach a ready detached session: {stderr[-500:]}"
                )
            try:
                rc, status_out, status_err = summon_cli(
                    "status", provider, db=db, cwd=tmp_path, timeout=10.0
                )
            except subprocess.TimeoutExpired as exc:
                detail = f"status command timed out after {exc.timeout}s"
                if _strict_live_harness():
                    pytest.fail(f"{provider} did not reach a ready prompt: {detail}")
                pytest.skip(f"{provider} did not reach a ready prompt: {detail}")
            if rc == 0:
                last_status = status_out
                reason = _not_ready_reason(status_out)
                if reason is not None:
                    if _strict_live_harness():
                        pytest.fail(
                            f"{provider} did not reach a ready prompt: {reason}"
                        )
                    pytest.skip(f"{provider} did not reach a ready prompt: {reason}")
                fatal_reason = _fatal_readiness_reason(status_out)
                if fatal_reason is not None:
                    pytest.fail(
                        f"{provider} did not reach a ready prompt: {fatal_reason}; "
                        f"stderr: {_file_tail(stderr_path)}"
                    )
                ready_status = status_out
                break
            elif status_err:
                last_status = status_err
            time.sleep(0.5)
        else:
            stderr = _finished_stderr_tail(proc)
            raise AssertionError(
                f"{provider} did not reach a ready detached session; "
                f"last status: {last_status[-500:]}; stderr: {stderr[-500:]}"
            )

        assert f"{provider}\tprovider={provider}\tdriver=alive" in ready_status
        probe = f"live-probe-{provider}-{time.monotonic_ns()}"
        rc, _out, err = taut_cli(
            "say",
            "general",
            "-",
            db=db,
            cwd=tmp_path,
            as_name="van",
            stdin=probe,
        )
        assert rc == 0, err
        deadline = time.monotonic() + _live_harness_timeout()
        while time.monotonic() < deadline:
            rc, status_out, status_err = summon_cli(
                "status", provider, db=db, cwd=tmp_path, timeout=10.0
            )
            if rc == 0:
                fatal_reason = _fatal_readiness_reason(status_out)
                if fatal_reason is not None:
                    pytest.fail(
                        f"{provider} lost ready control status: {fatal_reason}; "
                        f"stderr: {_file_tail(stderr_path)}"
                    )
                if "lag=#general:0" in status_out:
                    break
            if status_err:
                last_status = status_err
            elif status_out:
                last_status = status_out
            time.sleep(0.5)
        else:
            stderr = _finished_stderr_tail(proc)
            raise AssertionError(
                f"{provider} did not catch up after injected probe {probe!r}; "
                f"last status: {last_status[-500:]}; stderr: {stderr[-500:]}"
            )
    finally:
        try:
            summon_cli("stop", provider, db=db, cwd=tmp_path, timeout=30.0)
        except subprocess.TimeoutExpired:
            pass
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=10.0)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=10.0)
        stderr_file.close()
