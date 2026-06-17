from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

import tests.conftest as harness


def test_run_cli_writes_pg_config_with_worker_schema(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("BROKER_TEST_BACKEND", "postgres")
    monkeypatch.setenv(
        "SIMPLEBROKER_PG_TEST_DSN",
        "postgresql://postgres:postgres@127.0.0.1:5432/taut_test",
    )
    monkeypatch.setenv("SIMPLEBROKER_PG_TEST_SCHEMA", "taut_pytest_gw0")

    def fake_run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        assert cmd[:3] == [harness.sys.executable, "-m", "taut"]
        assert kwargs["cwd"] == tmp_path
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(harness.subprocess, "run", fake_run)

    rc, out, err = harness.run_cli("init", cwd=tmp_path)

    assert (rc, out, err) == (0, "", "")
    config = (tmp_path / ".taut.toml").read_text(encoding="utf-8")
    assert 'schema = "taut_pytest_gw0"' in config


def test_postgres_schema_for_worker_is_safe() -> None:
    assert harness.postgres_schema_for_worker("gw0") == "taut_pytest_gw0"
    assert harness.postgres_schema_for_worker("Master-1") == "taut_pytest_master_1"
