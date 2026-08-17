from __future__ import annotations

import hashlib
import io
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import uuid
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import psutil
import pytest

from taut._constants import PROJECT_CONFIG_NAME

PROJECT_ROOT = Path(__file__).resolve().parents[1]
POSTGRES_TEST_BACKEND = "postgres"
BACKEND_MARKERS = ("shared", "sqlite_only", "pg_only")
INSTALLED_COMMAND_FIXTURE = "installed_command_fixture"
INSTALLED_WHEEL_XDIST_GROUP = "installed-wheel"
SOURCE_SHARD_OPTION = "--taut-source-shard"
CLI_READY_FIXTURE = PROJECT_ROOT / "tests" / "fixtures" / "cli_ready.py"
CLI_READY_HOST_ENV = "TAUT_TEST_CLI_READY_HOST"
CLI_READY_PORT_ENV = "TAUT_TEST_CLI_READY_PORT"
CLI_READY_TOKEN_ENV = "TAUT_TEST_CLI_READY_TOKEN"
CLI_DIAGNOSTIC_ENV = "TAUT_TEST_CLI_DIAGNOSTIC"
CLI_CONNECT_TIMEOUT_ENV = "TAUT_TEST_CLI_CONNECT_TIMEOUT"
CLI_DIAGNOSTIC_DELAY_ENV = "TAUT_TEST_CLI_DIAGNOSTIC_DELAY"


def _parse_source_shard(value: str | None) -> tuple[int, int] | None:
    """Parse the opt-in source factor as a zero-based index and shard count."""

    if value in (None, "", "full"):
        return None
    match = re.fullmatch(r"(0|[1-9][0-9]*)/([1-9][0-9]*)", value)
    if match is None:
        raise pytest.UsageError(
            f"{SOURCE_SHARD_OPTION} must be 'full' or INDEX/COUNT; got {value!r}"
        )
    index, count = map(int, match.groups())
    if count <= 1 or index >= count:
        raise pytest.UsageError(
            f"{SOURCE_SHARD_OPTION} requires COUNT > 1 and INDEX < COUNT; got {value!r}"
        )
    return index, count


def _effective_xdist_group(item: Any) -> str | None:
    """Return the complete loadgroup identity used by pytest-xdist 3.8."""

    names: set[str] = set()
    for mark in item.iter_markers("xdist_group"):
        name = mark.args[0] if mark.args else mark.kwargs.get("name", "default")
        names.add(str(name))
    return "_".join(sorted(names)) if names else None


def _source_shard_key(item: Any) -> str:
    group = _effective_xdist_group(item)
    if group is not None:
        return f"group\0{group}"
    return f"node\0{item.nodeid}"


def _source_shard_index(key: str, count: int) -> int:
    digest = hashlib.sha256(key.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") % count


def pytest_addoption(parser: pytest.Parser) -> None:
    """Register the process-local canonical source-factor selector."""

    parser.addoption(
        SOURCE_SHARD_OPTION,
        action="store",
        default="full",
        metavar="INDEX/COUNT",
        help="run one deterministic source-factor shard (default: full)",
    )


@dataclass(frozen=True, slots=True)
class InstalledCommandFixture:
    """Fresh matrix-Python environment containing core and fixture wheels."""

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
        [uv, "venv", "--python", sys.executable, str(venv)],
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
    config_keys = {
        key
        for key in os.environ
        if key.startswith(("TAUT_", "BROKER_")) and key != "BROKER_TEST_BACKEND"
    }
    config_keys.update(("TAUT_DB", "TAUT_AS", "TAUT_TOKEN"))
    for key in config_keys:
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


def build_cli_env(
    env: dict[str, str] | None = None,
    *,
    force_unbuffered: bool = True,
) -> dict[str, str]:
    """Build a subprocess environment for invoking the in-repo CLI."""

    full_env = os.environ.copy()
    if env:
        full_env.update(env)
    full_env["PYTHONIOENCODING"] = "utf-8"
    if force_unbuffered:
        full_env["PYTHONUNBUFFERED"] = "1"
    else:
        full_env.pop("PYTHONUNBUFFERED", None)
    project_paths = [str(PROJECT_ROOT)]
    existing_pythonpath = full_env.get("PYTHONPATH")
    if existing_pythonpath:
        project_paths.append(existing_pythonpath)
    full_env["PYTHONPATH"] = os.pathsep.join(project_paths)
    return full_env


def _await_cli_readiness(
    process: subprocess.Popen[Any],
    listener: socket.socket,
    *,
    token: str,
    startup_started: float,
    startup_timeout: float,
) -> None:
    try:
        connection, _address = listener.accept()
        with connection:
            remaining = max(
                0.001, startup_timeout - (time.monotonic() - startup_started)
            )
            connection.settimeout(remaining)
            with connection.makefile("rb") as phases:
                spawned = phases.readline().decode("ascii", errors="replace").strip()
                expected_spawned = f"spawned {token}"
                if spawned != expected_spawned:
                    raise RuntimeError(
                        "CLI readiness child did not acknowledge spawn: "
                        f"expected {expected_spawned!r}, got {spawned!r}"
                    )
                remaining = max(
                    0.001, startup_timeout - (time.monotonic() - startup_started)
                )
                connection.settimeout(remaining)
                ready = phases.readline().decode("ascii", errors="replace").strip()
                expected_ready = f"ready {token}"
                if ready != expected_ready:
                    raise RuntimeError(
                        "CLI readiness child exited before application readiness: "
                        f"expected {expected_ready!r}, got {ready!r}"
                    )
    except BaseException:
        _kill_cli_process_tree(process)
        raise


def _cli_process_tree(process: subprocess.Popen[Any]) -> list[psutil.Process]:
    try:
        owner = psutil.Process(process.pid)
        return [*owner.children(recursive=True), owner]
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return []


def _kill_and_wait_psutil_processes(
    targets: list[psutil.Process],
    *,
    timeout: float,
) -> None:
    for target in targets:
        try:
            target.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    _gone, alive = psutil.wait_procs(targets, timeout=timeout)
    for target in alive:
        try:
            target.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    if alive:
        psutil.wait_procs(alive, timeout=1.0)


def _normalize_timeout_streams(
    process: subprocess.Popen[Any],
    stdout: Any,
    stderr: Any,
) -> tuple[Any, Any]:
    if isinstance(process.stdout, io.TextIOBase):
        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", errors="replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", errors="replace")
    else:
        if isinstance(stdout, str):
            stdout = stdout.encode("utf-8")
        if isinstance(stderr, str):
            stderr = stderr.encode("utf-8")
    return stdout, stderr


def _kill_cli_process_tree(
    process: subprocess.Popen[Any],
    *,
    collection_timeout: float = 5.0,
) -> tuple[Any, Any]:
    targets = _cli_process_tree(process)
    _kill_and_wait_psutil_processes(targets, timeout=collection_timeout)
    if process.poll() is None:
        process.kill()

    try:
        return process.communicate(timeout=collection_timeout)
    except subprocess.TimeoutExpired as exc:
        for stream in (process.stdin, process.stdout, process.stderr):
            if stream is not None:
                stream.close()
        try:
            process.wait(timeout=1.0)
        except subprocess.TimeoutExpired as wait_exc:
            raise RuntimeError(
                f"CLI readiness child {process.pid} could not be reaped after kill"
            ) from wait_exc
        return _normalize_timeout_streams(process, exc.output, exc.stderr)


def _communicate_ready_cli(
    process: subprocess.Popen[Any],
    command: list[str],
    *,
    input_value: str | bytes | None,
    timeout: float,
    binary: bool,
    diagnostic: Path,
) -> tuple[Any, Any]:
    try:
        return process.communicate(input=input_value, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        stdout, stderr = _kill_cli_process_tree(process)
        diagnostic_text = (
            diagnostic.read_text(encoding="utf-8", errors="replace")
            if diagnostic.exists()
            else "no child traceback was produced"
        )
        combined_stderr = (
            (stderr or b"") + b"\n" + diagnostic_text.encode("utf-8")
            if binary
            else (stderr or "") + "\n" + diagnostic_text
        )
        raise subprocess.TimeoutExpired(
            command,
            timeout,
            output=stdout,
            stderr=combined_stderr,
        ) from exc


def _new_cli_diagnostic() -> Path:
    diagnostic_fd, diagnostic_name = tempfile.mkstemp(
        prefix="taut-cli-diagnostic-",
        suffix=".log",
    )
    os.close(diagnostic_fd)
    return Path(diagnostic_name)


def _invoke_ready_cli(
    args: tuple[object, ...],
    *,
    cwd: Path,
    stdin: str | None = None,
    stdin_bytes: bytes | None = None,
    full_env: dict[str, str],
    timeout: float = 20.0,
    startup_timeout: float = 60.0,
) -> tuple[int, str, str]:
    command = [sys.executable, str(CLI_READY_FIXTURE), *map(str, args)]
    token = uuid.uuid4().hex
    diagnostic = _new_cli_diagnostic()
    binary = stdin_bytes is not None
    input_value: str | bytes | None = stdin_bytes if binary else stdin

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen(1)
            listener.settimeout(startup_timeout)
            host, port = listener.getsockname()
            full_env.update(
                {
                    CLI_READY_HOST_ENV: str(host),
                    CLI_READY_PORT_ENV: str(port),
                    CLI_READY_TOKEN_ENV: token,
                    CLI_DIAGNOSTIC_ENV: str(diagnostic),
                    CLI_CONNECT_TIMEOUT_ENV: str(startup_timeout),
                    CLI_DIAGNOSTIC_DELAY_ENV: str(min(15.0, max(0.001, timeout / 4.0))),
                }
            )
            popen_kwargs: dict[str, Any] = {
                "cwd": cwd,
                "env": full_env,
                "stdin": subprocess.PIPE,
                "stdout": subprocess.PIPE,
                "stderr": subprocess.PIPE,
                "text": not binary,
            }
            if not binary:
                popen_kwargs.update(encoding="utf-8", errors="replace")
            process = subprocess.Popen(command, **popen_kwargs)
            startup_started = time.monotonic()
            _await_cli_readiness(
                process,
                listener,
                token=token,
                startup_started=startup_started,
                startup_timeout=startup_timeout,
            )

        stdout, stderr = _communicate_ready_cli(
            process,
            command,
            input_value=input_value,
            timeout=timeout,
            binary=binary,
            diagnostic=diagnostic,
        )

        if binary:
            return (
                process.returncode,
                stdout.decode("utf-8", errors="replace").strip(),
                stderr.decode("utf-8", errors="replace").strip(),
            )
        return process.returncode, stdout.strip(), stderr.strip()
    finally:
        diagnostic.unlink(missing_ok=True)


def run_cli(
    *args: object,
    cwd: Path,
    stdin: str | None = None,
    stdin_bytes: bytes | None = None,
    env: dict[str, str] | None = None,
    timeout: float = 20.0,
    startup_timeout: float = 60.0,
) -> tuple[int, str, str]:
    """Run the real CLI with separate startup and post-readiness deadlines.

    Startup failures retain their socket/``TimeoutError`` class; only a command
    that acknowledged readiness can raise ``subprocess.TimeoutExpired``.
    """
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
    return _invoke_ready_cli(
        args,
        cwd=cwd,
        stdin=stdin,
        stdin_bytes=stdin_bytes,
        full_env=full_env,
        timeout=timeout,
        startup_timeout=startup_timeout,
    )


@pytest.hookimpl(
    hookwrapper=True,
    tryfirst=True,
    specname="pytest_collection_modifyitems",
)
def pytest_collection_modifyitems_installed_wheel(
    config: pytest.Config,
    items: list[pytest.Item],
) -> Iterator[None]:
    """Derive fixture ownership, then apply any opt-in source factor shard."""

    for item in items:
        if INSTALLED_COMMAND_FIXTURE in getattr(item, "fixturenames", ()):
            item.add_marker(pytest.mark.installed_wheel)
            item.add_marker(pytest.mark.xdist_group(INSTALLED_WHEEL_XDIST_GROUP))
    yield

    shard = _parse_source_shard(config.getoption(SOURCE_SHARD_OPTION))
    if shard is None:
        return
    index, count = shard
    selected: list[pytest.Item] = []
    deselected: list[pytest.Item] = []
    for item in items:
        destination = _source_shard_index(_source_shard_key(item), count)
        (selected if destination == index else deselected).append(item)
    items[:] = selected
    config.hook.pytest_deselected(items=deselected)


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
