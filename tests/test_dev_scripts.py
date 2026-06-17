from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

import taut._scripts as scripts


def test_route_pytest_args_defaults_to_both_suites() -> None:
    shared, extension, run_shared, run_extension, marker, workers, dist = (
        scripts._route_pytest_args(["-q"])
    )

    assert shared == ["-q"]
    assert extension == ["-q"]
    assert run_shared is True
    assert run_extension is True
    assert marker is None
    assert workers is None
    assert dist is None


def test_route_pytest_args_routes_extension_target_only() -> None:
    shared, extension, run_shared, run_extension, marker, workers, dist = (
        scripts._route_pytest_args(
            [
                "extensions/taut_pg/tests/test_pg_integration.py",
                "-m",
                "not slow",
                "-n",
                "0",
                "--dist=load",
            ]
        )
    )

    assert shared == []
    assert extension == ["extensions/taut_pg/tests/test_pg_integration.py"]
    assert run_shared is False
    assert run_extension is True
    assert marker == "not slow"
    assert workers == "0"
    assert dist == "load"


def test_pytest_pg_main_reports_missing_docker(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fake_which(command: str) -> str | None:
        return None if command == "docker" else f"/usr/bin/{command}"

    monkeypatch.setattr(scripts.shutil, "which", fake_which)

    assert scripts.pytest_pg_main([]) == 1
    assert "docker is required" in capsys.readouterr().err


def test_redact_backend_target_hides_password() -> None:
    redacted = scripts.redact_backend_target(
        "postgresql://postgres:secret@127.0.0.1:5432/taut_test"
    )

    assert redacted == "postgresql://postgres:<redacted>@127.0.0.1:5432/taut_test"


def test_build_pg_test_uv_command_installs_extension() -> None:
    command = scripts._pg_test_uv_command("pytest")

    assert command[:2] == ["uv", "run"]
    assert "--with-editable" in command
    assert "./extensions/taut_pg[dev]" in command
    assert command[-1] == "pytest"


def test_pytest_pg_main_starts_no_container_for_help(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def unexpected_start() -> tuple[str, str]:
        raise AssertionError("should not start Docker for --help")

    monkeypatch.setattr(scripts, "_start_postgres_container", unexpected_start)

    with pytest.raises(SystemExit) as excinfo:
        scripts.pytest_pg_main(["--help"])

    assert excinfo.value.code == 0
    assert "Run PG-backed Taut tests" in capsys.readouterr().out


def test_pg_runner_command_uses_explicit_xdist_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands: list[list[str]] = []

    monkeypatch.setattr(scripts.shutil, "which", lambda _command: "/usr/bin/tool")
    monkeypatch.setattr(
        scripts,
        "_start_postgres_container",
        lambda: ("container", "postgresql://postgres:postgres@127.0.0.1:1/taut_test"),
    )
    monkeypatch.setattr(scripts, "_verify_postgres_test_dsn", lambda _dsn: None)
    monkeypatch.setattr(scripts, "_cleanup_container", lambda _container: None)

    def fake_run(
        cmd: list[str],
        *,
        cwd: Path = scripts.ROOT,
        env: dict[str, str] | None = None,
        capture_output: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        del cwd, env, capture_output
        commands.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(scripts, "_run", fake_run)

    assert scripts.pytest_pg_main(["--fast"]) == 0

    pytest_commands = [command for command in commands if "pytest" in command]
    assert pytest_commands
    for command in pytest_commands:
        assert command[command.index("-n") + 1] == "auto"
        assert command[command.index("--dist") + 1] == "loadgroup"
