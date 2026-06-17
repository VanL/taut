"""Developer script helpers for Taut.

Spec references:
- docs/specs/02-taut-core.md [TAUT-12.1]
"""

from __future__ import annotations

import argparse
import importlib
import os
import shlex
import shutil
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any, cast
from urllib.parse import quote, urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parents[1]
POSTGRES_IMAGE = os.environ.get("SIMPLEBROKER_PG_TEST_IMAGE", "postgres:18")
POSTGRES_DB = os.environ.get("SIMPLEBROKER_PG_TEST_DB", "taut_test")
POSTGRES_USER = os.environ.get("SIMPLEBROKER_PG_TEST_USER", "postgres")
POSTGRES_PASSWORD = os.environ.get("SIMPLEBROKER_PG_TEST_PASSWORD", "postgres")


def _run(
    cmd: list[str],
    *,
    cwd: Path = ROOT,
    env: dict[str, str] | None = None,
    capture_output: bool = False,
) -> subprocess.CompletedProcess[str]:
    """Run a subprocess from the repository root and echo the command."""

    print(f"+ {shlex.join(cmd)}", flush=True)
    return subprocess.run(
        cmd,
        cwd=cwd,
        env=env,
        check=True,
        capture_output=capture_output,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def redact_backend_target(target: str) -> str:
    """Return a display-safe backend target with password material redacted."""

    parsed = urlsplit(target)
    if parsed.password is None:
        return target
    username = parsed.username or ""
    hostname = parsed.hostname or ""
    port = f":{parsed.port}" if parsed.port is not None else ""
    netloc = f"{username}:<redacted>@{hostname}{port}"
    return urlunsplit(
        (parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment)
    )


def _docker_port(container_name: str) -> str | None:
    """Return the published host port for Postgres or None if not ready yet."""

    result = subprocess.run(
        ["docker", "port", container_name, "5432/tcp"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        return None
    output = result.stdout.strip()
    if not output:
        return None
    return output.rsplit(":", 1)[1]


def _cleanup_container(container_name: str) -> None:
    """Remove the temporary Docker container if it still exists."""

    subprocess.run(
        ["docker", "rm", "-f", container_name],
        cwd=ROOT,
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _host_port_accepts_connections(
    port: str,
    *,
    timeout_seconds: float = 1.0,
) -> tuple[bool, str]:
    try:
        port_number = int(port)
    except ValueError as exc:
        return False, f"invalid published port {port!r}: {exc}"

    try:
        with socket.create_connection(("127.0.0.1", port_number), timeout_seconds):
            return True, ""
    except OSError as exc:
        return False, str(exc)


def _wait_for_postgres(container_name: str, *, timeout_seconds: float = 60.0) -> str:
    """Wait for the Postgres container to accept connections and return its port."""

    deadline = time.monotonic() + timeout_seconds
    last_error = "container did not start"

    while time.monotonic() < deadline:
        port = _docker_port(container_name)
        if port is None:
            last_error = "waiting for published port"
            time.sleep(1.0)
            continue

        result = subprocess.run(
            [
                "docker",
                "exec",
                container_name,
                "pg_isready",
                "-U",
                POSTGRES_USER,
                "-d",
                POSTGRES_DB,
            ],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if result.returncode == 0:
            host_ready, host_error = _host_port_accepts_connections(port)
            if host_ready:
                return port
            last_error = (
                f"waiting for host connection to 127.0.0.1:{port}: {host_error}"
            )
            time.sleep(1.0)
            continue

        last_error = (
            result.stderr.strip() or result.stdout.strip() or "pg_isready failed"
        )
        time.sleep(1.0)

    raise RuntimeError(f"Postgres did not become ready: {last_error}")


def _start_postgres_container() -> tuple[str, str]:
    """Start the temporary Postgres container and return its name and DSN."""

    container_name = f"taut-pg-test-{os.getpid()}-{uuid.uuid4().hex[:8]}"
    _run(
        [
            "docker",
            "run",
            "--detach",
            "--rm",
            "--name",
            container_name,
            "--env",
            f"POSTGRES_PASSWORD={POSTGRES_PASSWORD}",
            "--env",
            f"POSTGRES_USER={POSTGRES_USER}",
            "--env",
            f"POSTGRES_DB={POSTGRES_DB}",
            "--publish-all",
            POSTGRES_IMAGE,
            "-c",
            "max_connections=300",
        ],
        capture_output=True,
    )
    port = _wait_for_postgres(container_name)
    encoded_user = quote(POSTGRES_USER, safe="")
    encoded_password = quote(POSTGRES_PASSWORD, safe="")
    encoded_database = quote(POSTGRES_DB, safe="")
    dsn = (
        f"postgresql://{encoded_user}:{encoded_password}"
        f"@127.0.0.1:{port}/{encoded_database}"
    )
    return container_name, dsn


def _build_test_env(*, dsn: str, include_backend_marker: bool) -> dict[str, str]:
    """Build the environment used for PG-backed test runs."""

    env = os.environ.copy()
    env["SIMPLEBROKER_PG_TEST_DSN"] = dsn
    if include_backend_marker:
        env["BROKER_TEST_BACKEND"] = "postgres"
    return env


def _pg_test_uv_command(*args: str) -> list[str]:
    """Build a uv command with the dependencies used by PG-backed tests."""

    return [
        "uv",
        "run",
        "--extra",
        "dev",
        "--with-editable",
        ".",
        "--with-editable",
        "./extensions/taut_pg[dev]",
        *args,
    ]


_POSTGRES_DSN_VERIFY_COMMAND = (
    "from taut._scripts import _verify_postgres_test_dsn_from_env; "
    "_verify_postgres_test_dsn_from_env()"
)


def _verify_postgres_test_dsn_from_env() -> None:
    """Verify the PG test DSN from the current process environment."""

    psycopg = cast(Any, importlib.import_module("psycopg"))

    dsn = os.environ["SIMPLEBROKER_PG_TEST_DSN"]
    deadline = time.monotonic() + float(
        os.environ.get("SIMPLEBROKER_PG_TEST_DSN_READY_TIMEOUT", "60")
    )
    retry_interval = float(
        os.environ.get("SIMPLEBROKER_PG_TEST_DSN_RETRY_INTERVAL", "0.5")
    )
    last_error = "connection not attempted"

    while True:
        try:
            with psycopg.connect(dsn, connect_timeout=5) as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1")
                    assert cur.fetchone() == (1,)
            return
        except psycopg.OperationalError as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            if time.monotonic() >= deadline:
                print(f"Postgres test DSN was not ready: {last_error}", file=sys.stderr)
                raise
            time.sleep(retry_interval)


def _verify_postgres_test_dsn(dsn: str, *, timeout_seconds: float = 60.0) -> None:
    """Verify the test runner can connect to the exact host DSN before pytest."""

    env = _build_test_env(dsn=dsn, include_backend_marker=False)
    env["SIMPLEBROKER_PG_TEST_DSN_READY_TIMEOUT"] = f"{timeout_seconds:.6f}"
    _run(
        _pg_test_uv_command("python", "-c", _POSTGRES_DSN_VERIFY_COMMAND),
        env=env,
    )


def _merge_marker_expressions(base: str, extra: str | None) -> str:
    """Combine marker expressions while preserving the base filter."""

    if not extra:
        return base
    return f"({base}) and ({extra})"


def _append_marker_expression(current: str | None, extra: str) -> str:
    """Accumulate multiple user-supplied marker expressions."""

    if not current:
        return extra
    return f"({current}) and ({extra})"


def _classify_pytest_target(arg: str) -> str | None:
    """Map a pytest path or node id to the shared or extension suite."""

    if arg.startswith("-"):
        return None

    path_part = arg.split("::", 1)[0]
    if not path_part:
        return None

    candidate = Path(path_part)
    if not candidate.is_absolute():
        candidate = (ROOT / candidate).resolve()

    try:
        relative = candidate.relative_to(ROOT).as_posix()
    except ValueError:
        return None

    if relative == "tests" or relative.startswith("tests/"):
        return "shared"
    if relative == "extensions/taut_pg/tests" or relative.startswith(
        "extensions/taut_pg/tests/"
    ):
        return "extension"
    return None


def _with_default_suite_path(args: list[str], default_path: str) -> list[str]:
    """Append a default test path unless a target was routed."""

    if any(_classify_pytest_target(arg) is not None for arg in args):
        return list(args)
    return [*args, default_path]


def _extract_pytest_runner_overrides(
    pytest_args: list[str],
) -> tuple[list[str], str | None, str | None, str | None]:
    """Extract pytest args that need to be merged with runner defaults."""

    remaining: list[str] = []
    marker_expr: str | None = None
    numprocesses: str | None = None
    dist: str | None = None

    index = 0
    while index < len(pytest_args):
        arg = pytest_args[index]

        if arg == "--":
            index += 1
            continue
        if arg == "-m":
            if index + 1 >= len(pytest_args):
                raise SystemExit("pytest-pg: -m requires an argument")
            marker_expr = _append_marker_expression(marker_expr, pytest_args[index + 1])
            index += 2
            continue
        if arg.startswith("-m") and arg != "-m":
            marker_expr = _append_marker_expression(marker_expr, arg[2:])
            index += 1
            continue
        if arg == "-n":
            if index + 1 >= len(pytest_args):
                raise SystemExit("pytest-pg: -n requires an argument")
            numprocesses = pytest_args[index + 1]
            index += 2
            continue
        if arg.startswith("-n") and arg != "-n":
            numprocesses = arg[2:]
            index += 1
            continue
        if arg == "--dist":
            if index + 1 >= len(pytest_args):
                raise SystemExit("pytest-pg: --dist requires an argument")
            dist = pytest_args[index + 1]
            index += 2
            continue
        if arg.startswith("--dist="):
            dist = arg.split("=", 1)[1]
            index += 1
            continue

        remaining.append(arg)
        index += 1

    return remaining, marker_expr, numprocesses, dist


def _route_pytest_args(
    pytest_args: list[str],
) -> tuple[list[str], list[str], bool, bool, str | None, str | None, str | None]:
    """Split passthrough pytest args between root and extension suites."""

    filtered_args, marker_expr, numprocesses, dist = _extract_pytest_runner_overrides(
        pytest_args
    )

    shared_args: list[str] = []
    extension_args: list[str] = []
    shared_selected = False
    extension_selected = False

    for arg in filtered_args:
        target = _classify_pytest_target(arg)
        if target == "shared":
            shared_selected = True
            shared_args.append(arg)
            continue
        if target == "extension":
            extension_selected = True
            extension_args.append(arg)
            continue

        shared_args.append(arg)
        extension_args.append(arg)

    has_explicit_targets = shared_selected or extension_selected
    return (
        shared_args,
        extension_args,
        not has_explicit_targets or shared_selected,
        not has_explicit_targets or extension_selected,
        marker_expr,
        numprocesses,
        dist,
    )


def pytest_pg_main(argv: list[str] | None = None) -> int:
    """Run the Postgres-backed Taut test suites with Docker setup."""

    parser = argparse.ArgumentParser(
        description="Run PG-backed Taut tests with automatic Docker setup."
    )
    parser.add_argument(
        "--fast",
        action="store_true",
        help="Run the release-gate subset (shared and not slow).",
    )
    parser.add_argument(
        "--keep-container",
        action="store_true",
        help="Leave the temporary Postgres container running for debugging.",
    )
    args, pytest_args = parser.parse_known_args(argv)

    if shutil.which("docker") is None:
        print("docker is required to run PG-backed tests", file=sys.stderr)
        return 1
    if shutil.which("uv") is None:
        print("uv is required to run PG-backed tests", file=sys.stderr)
        return 1

    shared_marker = "shared and not slow" if args.fast else "shared"
    (
        shared_pytest_args,
        extension_pytest_args,
        run_shared_suite,
        run_extension_suite,
        extra_marker_expr,
        numprocesses,
        dist_mode,
    ) = _route_pytest_args(pytest_args)
    shared_marker = _merge_marker_expressions(shared_marker, extra_marker_expr)
    extension_marker = _merge_marker_expressions("pg_only", extra_marker_expr)
    numprocesses = numprocesses or "auto"
    dist_mode = dist_mode or "loadgroup"
    container_name: str | None = None

    try:
        container_name, dsn = _start_postgres_container()
        print(f"Postgres test DSN: {redact_backend_target(dsn)}", flush=True)
        _verify_postgres_test_dsn(dsn)

        shared_env = _build_test_env(dsn=dsn, include_backend_marker=True)
        extension_env = _build_test_env(dsn=dsn, include_backend_marker=False)

        if run_shared_suite:
            _run(
                _pg_test_uv_command(
                    "pytest",
                    *_with_default_suite_path(shared_pytest_args, "tests"),
                    "-m",
                    shared_marker,
                    "-n",
                    numprocesses,
                    "--dist",
                    dist_mode,
                ),
                env=shared_env,
            )

        if run_extension_suite:
            _run(
                _pg_test_uv_command(
                    "pytest",
                    *_with_default_suite_path(
                        extension_pytest_args, "extensions/taut_pg/tests"
                    ),
                    "-m",
                    extension_marker,
                    "-n",
                    numprocesses,
                    "--dist",
                    dist_mode,
                ),
                env=extension_env,
            )
        return 0
    except subprocess.CalledProcessError as exc:
        return exc.returncode or 1
    except KeyboardInterrupt:
        print("Interrupted", file=sys.stderr)
        return 130
    except Exception as exc:  # pragma: no cover - defensive CLI wrapper
        print(str(exc), file=sys.stderr)
        return 1
    finally:
        if container_name and not args.keep_container:
            _cleanup_container(container_name)
