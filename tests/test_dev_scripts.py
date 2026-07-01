from __future__ import annotations

import subprocess
from pathlib import Path
from types import TracebackType
from typing import Any

import pytest

import taut._scripts as scripts

pytestmark = pytest.mark.sqlite_only


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


def test_pytest_pg_main_reports_missing_uv(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fake_which(command: str) -> str | None:
        return None if command == "uv" else f"/usr/bin/{command}"

    monkeypatch.setattr(scripts.shutil, "which", fake_which)

    assert scripts.pytest_pg_main([]) == 1
    assert "uv is required" in capsys.readouterr().err


def test_run_echoes_command_and_invokes_subprocess(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    captured: dict[str, Any] = {}

    def fake_run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(cmd, 0, "ok", "")

    monkeypatch.setattr(scripts.subprocess, "run", fake_run)
    env = {"EXAMPLE": "1"}

    result = scripts._run(
        ["uv", "run", "pytest"],
        cwd=Path("/tmp"),
        env=env,
        capture_output=True,
    )

    assert result.stdout == "ok"
    assert capsys.readouterr().out == "+ uv run pytest\n"
    assert captured["cmd"] == ["uv", "run", "pytest"]
    assert captured["kwargs"]["cwd"] == Path("/tmp")
    assert captured["kwargs"]["env"] == env
    assert captured["kwargs"]["check"] is True
    assert captured["kwargs"]["capture_output"] is True
    assert captured["kwargs"]["text"] is True


def test_redact_backend_target_hides_password() -> None:
    redacted = scripts.redact_backend_target(
        "postgresql://postgres:secret@127.0.0.1:5432/taut_test"
    )

    assert redacted == "postgresql://postgres:<redacted>@127.0.0.1:5432/taut_test"


def test_redact_backend_target_leaves_passwordless_targets_unchanged() -> None:
    target = "postgresql://postgres@127.0.0.1:5432/taut_test?sslmode=disable"

    assert scripts.redact_backend_target(target) == target


def test_docker_port_returns_none_until_port_is_published(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    responses = iter(
        [
            subprocess.CompletedProcess(["docker"], 1, "", "missing"),
            subprocess.CompletedProcess(["docker"], 0, "\n", ""),
            subprocess.CompletedProcess(["docker"], 0, "0.0.0.0:15432\n", ""),
        ]
    )

    def fake_run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        assert cmd == ["docker", "port", "container", "5432/tcp"]
        assert kwargs["check"] is False
        return next(responses)

    monkeypatch.setattr(scripts.subprocess, "run", fake_run)

    assert scripts._docker_port("container") is None
    assert scripts._docker_port("container") is None
    assert scripts._docker_port("container") == "15432"


def test_cleanup_container_removes_docker_container(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []

    def fake_run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append(cmd)
        assert kwargs["check"] is False
        assert kwargs["stdout"] is subprocess.DEVNULL
        assert kwargs["stderr"] is subprocess.DEVNULL
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(scripts.subprocess, "run", fake_run)

    scripts._cleanup_container("container")

    assert calls == [["docker", "rm", "-f", "container"]]


def test_host_port_accepts_connections_reports_invalid_success_and_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeConnection:
        def __enter__(self) -> FakeConnection:
            return self

        def __exit__(
            self,
            exc_type: type[BaseException] | None,
            exc: BaseException | None,
            tb: TracebackType | None,
        ) -> None:
            return None

    assert scripts._host_port_accepts_connections("not-a-port")[0] is False

    monkeypatch.setattr(
        scripts.socket,
        "create_connection",
        lambda _address, _timeout: FakeConnection(),
    )
    assert scripts._host_port_accepts_connections("15432") == (True, "")

    def refused(_address: tuple[str, int], _timeout: float) -> FakeConnection:
        raise OSError("connection refused")

    monkeypatch.setattr(scripts.socket, "create_connection", refused)
    ready, message = scripts._host_port_accepts_connections("15432")
    assert ready is False
    assert message == "connection refused"


def test_wait_for_postgres_polls_until_host_port_accepts_connections(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ports = iter([None, "15432", "15432"])
    host_results = iter([(False, "connection refused"), (True, "")])
    times = iter([0.0, 0.0, 0.0, 0.0])
    sleeps: list[float] = []

    monkeypatch.setattr(scripts.time, "monotonic", lambda: next(times))
    monkeypatch.setattr(scripts.time, "sleep", lambda seconds: sleeps.append(seconds))
    monkeypatch.setattr(scripts, "_docker_port", lambda _container: next(ports))
    monkeypatch.setattr(
        scripts,
        "_host_port_accepts_connections",
        lambda _port: next(host_results),
    )

    def fake_run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        assert cmd[:3] == ["docker", "exec", "container"]
        assert kwargs["check"] is False
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(scripts.subprocess, "run", fake_run)

    assert scripts._wait_for_postgres("container") == "15432"
    assert sleeps == [1.0, 1.0]


def test_wait_for_postgres_raises_last_readiness_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    times = iter([0.0, 0.0, 2.0])

    monkeypatch.setattr(scripts.time, "monotonic", lambda: next(times))
    monkeypatch.setattr(scripts.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(scripts, "_docker_port", lambda _container: "15432")

    def fake_run(cmd: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(cmd, 1, "", "database is starting")

    monkeypatch.setattr(scripts.subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match="database is starting"):
        scripts._wait_for_postgres("container", timeout_seconds=1.0)


def test_start_postgres_container_builds_encoded_host_dsn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeUuid:
        hex = "abcdef1234567890"

    commands: list[list[str]] = []

    monkeypatch.setattr(scripts.os, "getpid", lambda: 321)
    monkeypatch.setattr(scripts.uuid, "uuid4", lambda: FakeUuid())
    monkeypatch.setattr(scripts, "POSTGRES_USER", "post gres")
    monkeypatch.setattr(scripts, "POSTGRES_PASSWORD", "p@ss/word")
    monkeypatch.setattr(scripts, "POSTGRES_DB", "taut test")
    monkeypatch.setattr(scripts, "POSTGRES_IMAGE", "postgres:test")
    monkeypatch.setattr(scripts, "_wait_for_postgres", lambda _container: "15432")

    def fake_run(
        cmd: list[str],
        *,
        cwd: Path = scripts.ROOT,
        env: dict[str, str] | None = None,
        capture_output: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        del cwd, env
        commands.append(cmd)
        assert capture_output is True
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(scripts, "_run", fake_run)

    container, dsn = scripts._start_postgres_container()

    assert container == "taut-pg-test-321-abcdef12"
    assert dsn == "postgresql://post%20gres:p%40ss%2Fword@127.0.0.1:15432/taut%20test"
    assert commands[0][commands[0].index("--name") + 1] == container
    assert "POSTGRES_PASSWORD=p@ss/word" in commands[0]
    assert commands[0][-3:] == ["postgres:test", "-c", "max_connections=300"]


def test_build_test_env_sets_backend_marker_only_when_requested(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("BROKER_TEST_BACKEND", raising=False)

    without_marker = scripts._build_test_env(
        dsn="postgresql://example",
        include_backend_marker=False,
    )
    with_marker = scripts._build_test_env(
        dsn="postgresql://example",
        include_backend_marker=True,
    )

    assert without_marker["SIMPLEBROKER_PG_TEST_DSN"] == "postgresql://example"
    assert "BROKER_TEST_BACKEND" not in without_marker
    assert with_marker["BROKER_TEST_BACKEND"] == "postgres"


def test_build_pg_test_uv_command_installs_extension() -> None:
    command = scripts._pg_test_uv_command("pytest")

    assert command[:2] == ["uv", "run"]
    assert "--with-editable" in command
    assert "./extensions/taut_pg[dev]" in command
    assert command[-1] == "pytest"


def test_verify_postgres_test_dsn_from_env_connects_until_select_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeCursor:
        def __enter__(self) -> FakeCursor:
            return self

        def __exit__(
            self,
            exc_type: type[BaseException] | None,
            exc: BaseException | None,
            tb: TracebackType | None,
        ) -> None:
            return None

        def execute(self, sql: str) -> None:
            assert sql == "SELECT 1"

        def fetchone(self) -> tuple[int]:
            return (1,)

    class FakeConnection:
        def __enter__(self) -> FakeConnection:
            return self

        def __exit__(
            self,
            exc_type: type[BaseException] | None,
            exc: BaseException | None,
            tb: TracebackType | None,
        ) -> None:
            return None

        def cursor(self) -> FakeCursor:
            return FakeCursor()

    class FakeOperationalError(Exception):
        pass

    class FakePsycopg:
        OperationalError = FakeOperationalError

        @staticmethod
        def connect(dsn: str, *, connect_timeout: int) -> FakeConnection:
            assert dsn == "postgresql://example"
            assert connect_timeout == 5
            return FakeConnection()

    monkeypatch.setattr(scripts.importlib, "import_module", lambda _name: FakePsycopg)
    monkeypatch.setenv("SIMPLEBROKER_PG_TEST_DSN", "postgresql://example")

    scripts._verify_postgres_test_dsn_from_env()


def test_verify_postgres_test_dsn_from_env_reports_timeout(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    class FakeOperationalError(Exception):
        pass

    class FakePsycopg:
        OperationalError = FakeOperationalError

        @staticmethod
        def connect(_dsn: str, *, connect_timeout: int) -> object:
            assert connect_timeout == 5
            raise FakeOperationalError("not ready")

    monkeypatch.setattr(scripts.importlib, "import_module", lambda _name: FakePsycopg)
    monkeypatch.setenv("SIMPLEBROKER_PG_TEST_DSN", "postgresql://example")
    monkeypatch.setenv("SIMPLEBROKER_PG_TEST_DSN_READY_TIMEOUT", "0")
    monkeypatch.setattr(scripts.time, "monotonic", lambda: 0.0)

    with pytest.raises(FakeOperationalError):
        scripts._verify_postgres_test_dsn_from_env()

    assert "Postgres test DSN was not ready" in capsys.readouterr().err


def test_verify_postgres_test_dsn_invokes_uv_verify_subprocess(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_run(
        cmd: list[str],
        *,
        cwd: Path = scripts.ROOT,
        env: dict[str, str] | None = None,
        capture_output: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        del cwd, capture_output
        captured["cmd"] = cmd
        captured["env"] = env
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(scripts, "_run", fake_run)

    scripts._verify_postgres_test_dsn("postgresql://example", timeout_seconds=3.5)

    assert captured["cmd"] == scripts._pg_test_uv_command(
        "python",
        "-c",
        scripts._POSTGRES_DSN_VERIFY_COMMAND,
    )
    env = captured["env"]
    assert env is not None
    assert env["SIMPLEBROKER_PG_TEST_DSN"] == "postgresql://example"
    assert env["SIMPLEBROKER_PG_TEST_DSN_READY_TIMEOUT"] == "3.500000"


def test_marker_expression_helpers_preserve_base_filters() -> None:
    assert scripts._merge_marker_expressions("shared", None) == "shared"
    assert scripts._merge_marker_expressions("shared", "not slow") == (
        "(shared) and (not slow)"
    )
    assert scripts._append_marker_expression(None, "shared") == "shared"
    assert scripts._append_marker_expression("shared", "not slow") == (
        "(shared) and (not slow)"
    )


def test_pytest_target_classification_handles_options_absolute_and_foreign_paths(
    tmp_path: Path,
) -> None:
    assert scripts._classify_pytest_target("-q") is None
    assert scripts._classify_pytest_target("::test_name") is None
    assert scripts._classify_pytest_target(str(tmp_path / "test_foreign.py")) is None
    assert scripts._classify_pytest_target(str(scripts.ROOT / "tests")) == "shared"
    assert (
        scripts._classify_pytest_target(
            str(scripts.ROOT / "extensions/taut_pg/tests/test_pg.py::test_pg")
        )
        == "extension"
    )


def test_with_default_suite_path_only_appends_when_no_suite_target() -> None:
    assert scripts._with_default_suite_path(["-q"], "tests") == ["-q", "tests"]
    assert scripts._with_default_suite_path(["tests/test_client.py"], "tests") == [
        "tests/test_client.py"
    ]


def test_extract_pytest_runner_overrides_accepts_inline_and_separate_options() -> None:
    remaining, marker, workers, dist = scripts._extract_pytest_runner_overrides(
        ["--", "-q", "-mfast", "-n2", "--dist", "loadfile"]
    )

    assert remaining == ["-q"]
    assert marker == "fast"
    assert workers == "2"
    assert dist == "loadfile"


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (["-m"], "pytest-pg: -m requires an argument"),
        (["-n"], "pytest-pg: -n requires an argument"),
        (["--dist"], "pytest-pg: --dist requires an argument"),
    ],
)
def test_extract_pytest_runner_overrides_rejects_missing_option_values(
    args: list[str],
    message: str,
) -> None:
    with pytest.raises(SystemExit, match=message):
        scripts._extract_pytest_runner_overrides(args)


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


def test_pytest_pg_main_runs_only_selected_extension_suite_with_overrides(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands: list[list[str]] = []
    cleaned: list[str] = []

    monkeypatch.setattr(scripts.shutil, "which", lambda _command: "/usr/bin/tool")
    monkeypatch.setattr(
        scripts,
        "_start_postgres_container",
        lambda: ("container", "postgresql://postgres:postgres@127.0.0.1:1/taut_test"),
    )
    monkeypatch.setattr(scripts, "_verify_postgres_test_dsn", lambda _dsn: None)
    monkeypatch.setattr(
        scripts, "_cleanup_container", lambda name: cleaned.append(name)
    )

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

    assert (
        scripts.pytest_pg_main(
            [
                "--keep-container",
                "extensions/taut_pg/tests/test_pg.py",
                "-mfast",
                "-n2",
                "--dist",
                "loadfile",
            ]
        )
        == 0
    )

    assert cleaned == []
    assert len(commands) == 1
    command = commands[0]
    assert "extensions/taut_pg/tests/test_pg.py" in command
    assert "tests" not in command
    assert command[command.index("-m") + 1] == "(pg_only) and (fast)"
    assert command[command.index("-n") + 1] == "2"
    assert command[command.index("--dist") + 1] == "loadfile"


def test_pytest_pg_main_returns_subprocess_failure_and_cleans_up(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cleaned: list[str] = []

    monkeypatch.setattr(scripts.shutil, "which", lambda _command: "/usr/bin/tool")
    monkeypatch.setattr(
        scripts,
        "_start_postgres_container",
        lambda: ("container", "postgresql://postgres:postgres@127.0.0.1:1/taut_test"),
    )
    monkeypatch.setattr(
        scripts,
        "_verify_postgres_test_dsn",
        lambda _dsn: (_ for _ in ()).throw(
            subprocess.CalledProcessError(7, ["verify"])
        ),
    )
    monkeypatch.setattr(
        scripts, "_cleanup_container", lambda name: cleaned.append(name)
    )

    assert scripts.pytest_pg_main([]) == 7
    assert cleaned == ["container"]


def test_pytest_pg_main_reports_keyboard_interrupt(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def interrupted() -> tuple[str, str]:
        raise KeyboardInterrupt

    monkeypatch.setattr(scripts.shutil, "which", lambda _command: "/usr/bin/tool")
    monkeypatch.setattr(scripts, "_start_postgres_container", interrupted)

    assert scripts.pytest_pg_main([]) == 130
    assert "Interrupted" in capsys.readouterr().err


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
