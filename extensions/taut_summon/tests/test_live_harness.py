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


@pytest.mark.requires_live_harness
@pytest.mark.parametrize("provider", _HARNESSES)
def test_live_pty_harness_posts_sentinel(tmp_path: Path, provider: str) -> None:
    if not _live_harness_enabled():
        pytest.skip(
            "live harness tests run locally by default; set "
            "TAUT_SUMMON_LIVE_HARNESS=1 in CI or 0 to skip locally"
        )
    if shutil.which(provider) is None:
        pytest.skip(f"{provider} binary is absent")

    db = tmp_path / ".taut.db"
    TautClient.init(db_path=db)
    rc, _out, err = taut_cli("join", "general", db=db, cwd=tmp_path, as_name="van")
    assert rc == 0, err

    sentinel = f"live-sentinel-{provider}-{time.monotonic_ns()}"
    prompt = tmp_path / "orientation.txt"
    prompt.write_text(
        "You are a summoned taut member. Immediately run exactly this command "
        f"and then wait: taut say general {sentinel!r}\n",
        encoding="utf-8",
    )
    env = _base_env()
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
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.monotonic() + 120.0

        def _sentinel_posted() -> bool:
            return any(
                message.text == sentinel
                for message in TautClient(db_path=db).log("general")
            )

        while time.monotonic() < deadline:
            if proc.poll() is not None:
                stderr = proc.stderr.read() if proc.stderr is not None else ""
                pytest.skip(
                    f"{provider} did not reach a ready detached session: {stderr[-500:]}"
                )
            if _sentinel_posted():
                break
            time.sleep(0.5)
        else:
            raise AssertionError(f"{provider} was ready but did not post {sentinel!r}")
    finally:
        summon_cli("stop", provider, db=db, cwd=tmp_path, timeout=30.0)
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=10.0)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=10.0)
