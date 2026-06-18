from __future__ import annotations

import os
import re
import subprocess
import sys
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

import pytest

from taut._constants import PROJECT_CONFIG_NAME

PROJECT_ROOT = Path(__file__).resolve().parents[1]
POSTGRES_TEST_BACKEND = "postgres"
BACKEND_MARKERS = ("shared", "sqlite_only", "pg_only")


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in ("TAUT_DB", "TAUT_AS", "TAUT_TOKEN"):
        monkeypatch.delenv(key, raising=False)


def active_backend(env: Mapping[str, str] | None = None) -> str:
    """Return the backend selected for test harness behavior."""

    if env and env.get("BROKER_TEST_BACKEND"):
        return env["BROKER_TEST_BACKEND"]
    return os.environ.get("BROKER_TEST_BACKEND", "sqlite")


def pg_test_dsn(env: Mapping[str, str] | None = None) -> str | None:
    """Return the configured Postgres test DSN, if any."""

    if env and env.get("SIMPLEBROKER_PG_TEST_DSN"):
        return env["SIMPLEBROKER_PG_TEST_DSN"]
    return os.environ.get("SIMPLEBROKER_PG_TEST_DSN")


def _schema_safe(value: str) -> str:
    safe = re.sub(r"[^a-z0-9_]+", "_", value.lower()).strip("_")
    return safe or "master"


def postgres_schema_for_worker(worker_id: str) -> str:
    """Return the worker-scoped schema name for root shared tests."""

    return f"taut_pytest_{_schema_safe(worker_id)}"


@pytest.fixture(scope="session")
def pg_worker_schema(worker_id: str) -> str | None:
    """Expose one Postgres schema name per xdist worker."""

    if active_backend() != POSTGRES_TEST_BACKEND:
        return None
    schema = postgres_schema_for_worker(worker_id)
    os.environ["SIMPLEBROKER_PG_TEST_SCHEMA"] = schema
    return schema


@pytest.fixture(autouse=True, scope="session")
def _pg_worker_bootstrap(pg_worker_schema: str | None) -> None:
    """Ensure worker-scoped PG env is initialized in each xdist worker."""


def cleanup_postgres_schema(dsn: str, schema: str) -> None:
    """Drop a test-owned Postgres schema through the public backend API."""

    from simplebroker.ext import get_backend_plugin

    get_backend_plugin(POSTGRES_TEST_BACKEND).cleanup_target(
        dsn,
        backend_options={"schema": schema},
    )


def ensure_taut_project_config(root: Path, *, dsn: str, schema: str) -> Path:
    """Create a project-local Postgres `.taut.toml` unless it already exists."""

    config_path = root / PROJECT_CONFIG_NAME
    if config_path.exists():
        return config_path
    root.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        "\n".join(
            [
                "version = 1",
                'backend = "postgres"',
                f'target = "{dsn}"',
                "",
                "[backend_options]",
                f'schema = "{schema}"',
                "",
            ]
        ),
        encoding="utf-8",
    )
    return config_path


def _requires_explicit_shared_marker(path: Path) -> bool:
    """Return whether a test module name promises backend-shared coverage."""

    return path.name.startswith("test_shared")


def _has_backend_marker(item: pytest.Item) -> bool:
    """Return whether a test item explicitly declares backend coverage."""

    return any(
        item.get_closest_marker(marker) is not None for marker in BACKEND_MARKERS
    )


@pytest.fixture
def taut_project(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    pg_worker_schema: str | None,
) -> Iterator[Path]:
    """Return a project root prepared for the active test backend."""

    root = tmp_path
    if active_backend() == POSTGRES_TEST_BACKEND:
        dsn = pg_test_dsn()
        if not dsn or not pg_worker_schema:
            raise RuntimeError(
                "BROKER_TEST_BACKEND=postgres requires SIMPLEBROKER_PG_TEST_DSN"
            )
        cleanup_postgres_schema(dsn, pg_worker_schema)
        ensure_taut_project_config(root, dsn=dsn, schema=pg_worker_schema)
    monkeypatch.chdir(root)
    try:
        yield root
    finally:
        if active_backend() == POSTGRES_TEST_BACKEND:
            dsn = pg_test_dsn()
            if dsn and pg_worker_schema:
                cleanup_postgres_schema(dsn, pg_worker_schema)


def build_cli_env(env: dict[str, str] | None = None) -> dict[str, str]:
    """Build a subprocess environment for invoking the in-repo CLI."""

    full_env = os.environ.copy()
    if env:
        full_env.update(env)
    full_env["PYTHONIOENCODING"] = "utf-8"
    full_env["PYTHONUNBUFFERED"] = "1"
    project_paths = [str(PROJECT_ROOT)]
    existing_pythonpath = full_env.get("PYTHONPATH")
    if existing_pythonpath:
        project_paths.append(existing_pythonpath)
    full_env["PYTHONPATH"] = os.pathsep.join(project_paths)
    return full_env


def run_cli(
    *args: object,
    cwd: Path,
    stdin: str | None = None,
    env: dict[str, str] | None = None,
    timeout: float = 20.0,
) -> tuple[int, str, str]:
    full_env = build_cli_env(env)
    if active_backend(full_env) == POSTGRES_TEST_BACKEND:
        dsn = pg_test_dsn(full_env)
        if not dsn:
            raise RuntimeError(
                "BROKER_TEST_BACKEND=postgres requires SIMPLEBROKER_PG_TEST_DSN"
            )
        schema = full_env.get(
            "SIMPLEBROKER_PG_TEST_SCHEMA"
        ) or postgres_schema_for_worker("master")
        config_root = cwd.resolve()
        ensure_taut_project_config(config_root, dsn=dsn, schema=schema)
    cmd = [sys.executable, "-m", "taut", *map(str, args)]
    kwargs: dict[str, Any] = {
        "cwd": cwd,
        "env": full_env,
        "capture_output": True,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
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


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Require explicit backend coverage markers on root tests."""

    for item in items:
        if (
            _requires_explicit_shared_marker(Path(str(item.path)))
            and item.get_closest_marker("shared") is None
        ):
            raise pytest.UsageError(
                f"{item.path} is named as a shared contract test but is not "
                "marked with @pytest.mark.shared"
            )
        if _has_backend_marker(item):
            continue
        raise pytest.UsageError(
            f"{item.nodeid} has no backend marker; add @pytest.mark.shared, "
            "@pytest.mark.sqlite_only, or @pytest.mark.pg_only"
        )
