from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in ("TAUT_DB", "TAUT_AS", "TAUT_TOKEN"):
        monkeypatch.delenv(key, raising=False)


def run_cli(
    *args: object,
    cwd: Path,
    stdin: str | None = None,
    env: dict[str, str] | None = None,
    timeout: float = 20.0,
) -> tuple[int, str, str]:
    full_env = os.environ.copy()
    if env:
        full_env.update(env)
    cmd = [sys.executable, "-m", "taut", *map(str, args)]
    kwargs: dict[str, Any] = {
        "cwd": cwd,
        "env": full_env,
        "capture_output": True,
        "text": True,
        "timeout": timeout,
    }
    if stdin is not None:
        kwargs["input"] = stdin
    completed = subprocess.run(cmd, **kwargs)
    return (
        completed.returncode,
        completed.stdout.strip(),
        completed.stderr.strip(),
    )
