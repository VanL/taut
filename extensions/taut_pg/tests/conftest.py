"""Shared fixtures for Taut Postgres extension tests."""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import psycopg
import pytest
from simplebroker.ext import get_backend_plugin

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def unique_schema(prefix: str = "taut_pg_test") -> str:
    """Return a short unique schema name for an individual test."""

    return f"{prefix}_{uuid.uuid4().hex[:12]}"


@pytest.fixture
def pg_dsn() -> str:
    """Return the configured Postgres DSN or skip when unavailable."""

    dsn = os.environ.get("SIMPLEBROKER_PG_TEST_DSN")
    if not dsn:
        pytest.skip("Set SIMPLEBROKER_PG_TEST_DSN to run Postgres extension tests")
    return dsn


@pytest.fixture
def pg_schema() -> str:
    """Return a unique schema name."""

    return unique_schema()


@pytest.fixture
def taut_pg_project(tmp_path: Path, pg_dsn: str, pg_schema: str) -> Iterator[Path]:
    """Return a Taut project root configured for a fresh Postgres schema."""

    config_path = tmp_path / ".taut.toml"
    config_path.write_text(
        "\n".join(
            [
                "version = 1",
                'backend = "postgres"',
                f'target = "{pg_dsn}"',
                "",
                "[backend_options]",
                f'schema = "{pg_schema}"',
                "",
            ]
        ),
        encoding="utf-8",
    )
    try:
        yield tmp_path
    finally:
        get_backend_plugin("postgres").cleanup_target(
            pg_dsn,
            backend_options={"schema": pg_schema},
        )


@pytest.fixture
def raw_pg_conn(pg_dsn: str) -> Iterator[psycopg.Connection[Any]]:
    """Return an autocommit raw psycopg connection for inspection helpers."""

    with psycopg.connect(pg_dsn, autocommit=True) as conn:
        yield conn


def run_taut_cli(
    *args: object,
    cwd: Path,
    timeout: float = 20.0,
) -> tuple[int, str, str]:
    """Run the in-repo Taut CLI in a subprocess."""

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUNBUFFERED"] = "1"
    pythonpath = [str(PROJECT_ROOT)]
    if existing := env.get("PYTHONPATH"):
        pythonpath.append(existing)
    env["PYTHONPATH"] = os.pathsep.join(pythonpath)

    completed = subprocess.run(
        [sys.executable, "-m", "taut", *map(str, args)],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return completed.returncode, completed.stdout.strip(), completed.stderr.strip()


@pytest.fixture
def taut_cli() -> Callable[..., tuple[int, str, str]]:
    """Return the CLI subprocess helper."""

    return run_taut_cli
