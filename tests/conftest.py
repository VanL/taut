from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from taut._constants import PROJECT_CONFIG_NAME

PROJECT_ROOT = Path(__file__).resolve().parents[1]
POSTGRES_TEST_BACKEND = "postgres"
BACKEND_MARKERS = ("shared", "sqlite_only", "pg_only")


@dataclass(frozen=True, slots=True)
class InstalledCommandFixture:
    """Fresh Python 3.11 environment containing current core and fixture wheels."""

    python: Path
    root: Path
    core_wheel: Path
    plugin_wheel: Path
    summon_wheel: Path

    def create_isolated(self, root: Path) -> InstalledCommandFixture:
        """Install the already-built wheels into a disposable environment."""

        uv = shutil.which("uv")
        if uv is None:
            raise RuntimeError("uv is required for installed command fixture tests")
        root.mkdir(parents=True, exist_ok=True)
        python = _install_command_fixture_environment(
            uv,
            root,
            self.core_wheel,
            self.plugin_wheel,
        )
        return InstalledCommandFixture(
            python=python,
            root=root,
            core_wheel=self.core_wheel,
            plugin_wheel=self.plugin_wheel,
            summon_wheel=self.summon_wheel,
        )

    def install_wheels(self, *wheels: Path) -> subprocess.CompletedProcess[str]:
        """Install additional artifacts into this isolated environment."""

        uv = shutil.which("uv")
        if uv is None:
            raise RuntimeError("uv is required for installed command fixture tests")
        return subprocess.run(
            [
                uv,
                "pip",
                "install",
                "--python",
                str(self.python),
                *(str(wheel) for wheel in wheels),
            ],
            cwd=self.root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=180,
            check=False,
        )

    def run_python(self, code: str, *args: str) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env.pop("PYTHONPATH", None)
        return subprocess.run(
            [str(self.python), "-c", code, *args],
            cwd=self.root,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
            check=False,
        )

    def run_console(self, *args: str) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env.pop("PYTHONPATH", None)
        executable = self.python.parent / ("taut.exe" if os.name == "nt" else "taut")
        return subprocess.run(
            [str(executable), *args],
            cwd=self.root,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
            check=False,
        )

    def run_summon_console(self, *args: str) -> subprocess.CompletedProcess[str]:
        """Run the installed standalone Summon console without checkout imports."""

        env = os.environ.copy()
        env.pop("PYTHONPATH", None)
        executable = self.python.parent / (
            "taut-summon.exe" if os.name == "nt" else "taut-summon"
        )
        return subprocess.run(
            [str(executable), *args],
            cwd=self.root,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
            check=False,
        )

    def uninstall_plugin(self) -> subprocess.CompletedProcess[str]:
        uv = shutil.which("uv")
        if uv is None:
            raise RuntimeError("uv is required for installed command fixture tests")
        return subprocess.run(
            [
                uv,
                "pip",
                "uninstall",
                "--python",
                str(self.python),
                "taut-command-plugin-fixture",
            ],
            cwd=self.root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
            check=False,
        )


def _install_command_fixture_environment(
    uv: str,
    root: Path,
    core_wheel: Path,
    plugin_wheel: Path,
) -> Path:
    venv = root / "venv"
    subprocess.run(
        [uv, "venv", "--python", "3.11", str(venv)],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    )
    python = (
        venv / "Scripts" / "python.exe" if os.name == "nt" else venv / "bin" / "python"
    )
    subprocess.run(
        [
            uv,
            "pip",
            "install",
            "--python",
            str(python),
            str(core_wheel),
            str(plugin_wheel),
        ],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
        timeout=180,
    )
    return python


@pytest.fixture(scope="session")
def installed_command_fixture(
    tmp_path_factory: pytest.TempPathFactory,
) -> InstalledCommandFixture:
    """Build and install real core/plugin wheels with no checkout import path."""

    uv = shutil.which("uv")
    if uv is None:
        raise RuntimeError("uv is required for installed command fixture tests")
    root = tmp_path_factory.mktemp("installed-command-fixture")
    core_dist = root / "core-dist"
    plugin_dist = root / "plugin-dist"
    summon_dist = root / "summon-dist"
    fixture_project = PROJECT_ROOT / "tests" / "fixtures" / "taut_command_plugin"
    for source, destination in (
        (PROJECT_ROOT, core_dist),
        (fixture_project, plugin_dist),
        (PROJECT_ROOT / "extensions" / "taut_summon", summon_dist),
    ):
        subprocess.run(
            [uv, "build", "--wheel", "--out-dir", str(destination), str(source)],
            cwd=PROJECT_ROOT,
            check=True,
            capture_output=True,
            text=True,
            timeout=120,
        )
    core_wheels = tuple(core_dist.glob("*.whl"))
    plugin_wheels = tuple(plugin_dist.glob("*.whl"))
    summon_wheels = tuple(summon_dist.glob("*.whl"))
    if len(core_wheels) != 1 or len(plugin_wheels) != 1 or len(summon_wheels) != 1:
        raise RuntimeError(
            "installed command fixture must build exactly one core, plugin, and "
            "Summon wheel"
        )
    python = _install_command_fixture_environment(
        uv,
        root,
        core_wheels[0],
        plugin_wheels[0],
    )
    return InstalledCommandFixture(
        python=python,
        root=root,
        core_wheel=core_wheels[0],
        plugin_wheel=plugin_wheels[0],
        summon_wheel=summon_wheels[0],
    )


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
    stdin_bytes: bytes | None = None,
    env: dict[str, str] | None = None,
    timeout: float = 20.0,
) -> tuple[int, str, str]:
    if stdin is not None and stdin_bytes is not None:
        raise ValueError("stdin and stdin_bytes are mutually exclusive")
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
        "timeout": timeout,
    }
    if stdin_bytes is not None:
        # Binary-stdin branch: carries bytes the text-mode pipe cannot
        # (e.g. invalid UTF-8 probes). Output is decoded back to str here
        # so the (int, str, str) return contract is identical.
        kwargs["input"] = stdin_bytes
        completed = subprocess.run(cmd, text=False, **kwargs)
        return (
            completed.returncode,
            completed.stdout.decode("utf-8", errors="replace").strip(),
            completed.stderr.decode("utf-8", errors="replace").strip(),
        )
    kwargs.update(text=True, encoding="utf-8", errors="replace")
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
