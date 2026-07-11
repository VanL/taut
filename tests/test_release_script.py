from __future__ import annotations

import http.client
import importlib.util
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RELEASE_SCRIPT = PROJECT_ROOT / "bin" / "release.py"

pytestmark = pytest.mark.sqlite_only


def _load_release_module() -> Any:
    spec = importlib.util.spec_from_file_location("taut_release", RELEASE_SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _release_state(
    release: Any,
    *,
    target: Any | None = None,
    github_release_exists: bool = False,
    local_tag_commit: str | None = None,
    remote_tag_commit: str | None = None,
) -> Any:
    if target is None:
        target = release.ROOT_TARGET
    return release.ReleaseState(
        target=target,
        version="0.1.1",
        tag_name=target.tag_for_version("0.1.1"),
        github_release_exists=github_release_exists,
        local_tag_commit=local_tag_commit,
        remote_tag_commit=remote_tag_commit,
    )


def test_validate_version_accepts_strict_semver() -> None:
    release = _load_release_module()

    release.validate_version("1.2.3")

    with pytest.raises(SystemExit, match="Invalid version"):
        release.validate_version("1.2")

    with pytest.raises(SystemExit, match="Invalid version"):
        release.validate_version("v1.2.3")


def test_read_current_version_rejects_mismatch(
    tmp_path: Path,
) -> None:
    release = _load_release_module()
    pyproject_path = tmp_path / "pyproject.toml"
    constants_path = tmp_path / "taut" / "_constants.py"
    constants_path.parent.mkdir()
    pyproject_path.write_text(
        '[project]\nname = "taut"\nversion = "0.1.1"\n',
        encoding="utf-8",
    )
    constants_path.write_text('__version__: Final[str] = "0.1.2"\n', encoding="utf-8")
    target = release.ReleaseTarget(
        name="temp",
        package_name="temp",
        package_dir=Path("."),
        pyproject_path=pyproject_path,
        constants_path=constants_path,
        tag_namespace=None,
        github_release=True,
        pypi_publish=False,
    )

    with pytest.raises(SystemExit, match="Version mismatch"):
        release.read_current_version(target)


def test_write_version_files_updates_pyproject_and_constants(
    tmp_path: Path,
) -> None:
    release = _load_release_module()
    pyproject_path = tmp_path / "pyproject.toml"
    constants_path = tmp_path / "taut" / "_constants.py"
    constants_path.parent.mkdir()
    pyproject_path.write_text(
        '[project]\nname = "taut"\nversion = "0.1.1"\n',
        encoding="utf-8",
    )
    constants_path.write_text('__version__: Final[str] = "0.1.1"\n', encoding="utf-8")
    target = release.ReleaseTarget(
        name="temp",
        package_name="temp",
        package_dir=Path("."),
        pyproject_path=pyproject_path,
        constants_path=constants_path,
        tag_namespace=None,
        github_release=True,
        pypi_publish=False,
    )

    release.write_version_files("0.1.2", target)

    assert 'version = "0.1.2"' in pyproject_path.read_text(encoding="utf-8")
    assert '__version__: Final[str] = "0.1.2"' in constants_path.read_text(
        encoding="utf-8"
    )


def test_write_version_files_updates_pg_dependency_floor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release = _load_release_module()
    pyproject_path = tmp_path / "extensions" / "taut_pg" / "pyproject.toml"
    pyproject_path.parent.mkdir(parents=True)
    pyproject_path.write_text(
        "\n".join(
            [
                "[project]",
                'name = "taut-pg"',
                'version = "0.1.1"',
                "dependencies = [",
                '    "taut>=0.1.1",',
                '    "simplebroker-pg>=3.0.0",',
                "]",
                "",
            ]
        ),
        encoding="utf-8",
    )
    target = release.ReleaseTarget(
        name="pg",
        package_name="taut-pg",
        package_dir=Path("extensions/taut_pg"),
        pyproject_path=pyproject_path,
        constants_path=None,
        tag_namespace="taut_pg",
        github_release=True,
        pypi_publish=False,
    )

    def fake_read_current_version(target: object = release.ROOT_TARGET) -> str:
        assert target == release.ROOT_TARGET
        return "0.2.0"

    monkeypatch.setattr(release, "read_current_version", fake_read_current_version)

    release.write_version_files("0.2.1", target)

    text = pyproject_path.read_text(encoding="utf-8")
    assert 'version = "0.2.1"' in text
    assert '"taut>=0.2.0",' in text


def test_write_version_files_updates_summon_dependency_floor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release = _load_release_module()
    pyproject_path = tmp_path / "extensions" / "taut_summon" / "pyproject.toml"
    pyproject_path.parent.mkdir(parents=True)
    pyproject_path.write_text(
        "\n".join(
            [
                "[project]",
                'name = "taut-summon"',
                'version = "0.1.1"',
                "dependencies = [",
                '    "taut>=0.1.1",',
                "]",
                "",
            ]
        ),
        encoding="utf-8",
    )
    target = release.ReleaseTarget(
        name="summon",
        package_name="taut-summon",
        package_dir=Path("extensions/taut_summon"),
        pyproject_path=pyproject_path,
        constants_path=None,
        tag_namespace="taut_summon",
        github_release=True,
        pypi_publish=False,
    )

    def fake_read_current_version(target: object = release.ROOT_TARGET) -> str:
        assert target == release.ROOT_TARGET
        return "0.5.1"

    monkeypatch.setattr(release, "read_current_version", fake_read_current_version)

    release.write_version_files("0.5.1", target)

    text = pyproject_path.read_text(encoding="utf-8")
    assert 'version = "0.5.1"' in text
    assert '"taut>=0.5.1",' in text


def test_sync_root_summon_dev_dependency_updates_root_floor(tmp_path: Path) -> None:
    release = _load_release_module()
    root_pyproject_path = tmp_path / "pyproject.toml"
    summon_pyproject_path = tmp_path / "extensions" / "taut_summon" / "pyproject.toml"
    summon_pyproject_path.parent.mkdir(parents=True)
    root_pyproject_path.write_text(
        "\n".join(
            [
                "[project]",
                'name = "taut"',
                'version = "0.4.0"',
                "[project.optional-dependencies]",
                "dev = [",
                '    "taut-summon>=0.1.0",',
                "]",
                "",
            ]
        ),
        encoding="utf-8",
    )
    summon_pyproject_path.write_text(
        '[project]\nname = "taut-summon"\nversion = "0.5.0"\n',
        encoding="utf-8",
    )

    updated_version = release.sync_root_summon_dev_dependency(
        root_pyproject_path=root_pyproject_path,
        summon_pyproject_path=summon_pyproject_path,
    )

    assert updated_version == "0.5.0"
    assert '"taut-summon>=0.5.0",' in root_pyproject_path.read_text(encoding="utf-8")


def test_sync_summon_core_dependency_updates_exact_root_floor(
    tmp_path: Path,
) -> None:
    release = _load_release_module()
    root_pyproject_path = tmp_path / "pyproject.toml"
    summon_pyproject_path = tmp_path / "extensions" / "taut_summon" / "pyproject.toml"
    summon_pyproject_path.parent.mkdir(parents=True)
    root_pyproject_path.write_text(
        '[project]\nname = "taut"\nversion = "0.6.0"\n',
        encoding="utf-8",
    )
    summon_pyproject_path.write_text(
        '[project]\nname = "taut-summon"\nversion = "0.5.1"\n'
        'dependencies = [\n    "taut>=0.5.1",\n]\n',
        encoding="utf-8",
    )

    updated_version = release.sync_summon_core_dependency(
        root_pyproject_path=root_pyproject_path,
        summon_pyproject_path=summon_pyproject_path,
    )

    assert updated_version == "0.6.0"
    assert '"taut>=0.6.0",' in summon_pyproject_path.read_text(encoding="utf-8")


def test_root_release_sync_updates_both_paired_dependency_directions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release = _load_release_module()
    calls: list[str] = []

    def sync_root_to_summon() -> str:
        calls.append("root-to-summon")
        return "0.5.1"

    def sync_summon_to_root() -> str:
        calls.append("summon-to-root")
        return "0.6.0"

    monkeypatch.setattr(
        release,
        "sync_root_summon_dev_dependency",
        sync_root_to_summon,
    )
    monkeypatch.setattr(
        release,
        "sync_summon_core_dependency",
        sync_summon_to_root,
    )

    release._sync_root_release_dependencies()  # noqa: SLF001

    assert calls == ["root-to-summon", "summon-to-root"]


def test_root_target_uses_v_prefixed_github_tag() -> None:
    release = _load_release_module()

    assert release.ROOT_TARGET.tag_for_version("0.1.1") == "v0.1.1"
    assert release.ROOT_TARGET.package_dir == Path(".")
    assert release.ROOT_TARGET.github_release is True
    assert release.ROOT_TARGET.pypi_publish is False


def test_pg_target_uses_namespaced_github_tag() -> None:
    release = _load_release_module()

    assert release.PG_TARGET.package_name == "taut-pg"
    assert release.PG_TARGET.package_dir == Path("extensions/taut_pg")
    assert release.PG_TARGET.tag_for_version("0.1.1") == "taut_pg/v0.1.1"
    assert release.PG_TARGET.github_release is True
    assert release.PG_TARGET.pypi_publish is False


def test_summon_target_uses_namespaced_github_tag() -> None:
    release = _load_release_module()

    assert release.SUMMON_TARGET.package_name == "taut-summon"
    assert release.SUMMON_TARGET.package_dir == Path("extensions/taut_summon")
    assert release.SUMMON_TARGET.tag_for_version("0.1.1") == "taut_summon/v0.1.1"
    assert release.SUMMON_TARGET.github_release is True
    assert release.SUMMON_TARGET.pypi_publish is False
    assert (
        release.SUMMON_TARGET.release_workflow
        == ".github/workflows/release-gate-summon.yml"
    )


def test_inspect_release_state_is_github_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release = _load_release_module()
    calls: list[str] = []

    def fake_github_release_exists(tag_name: str) -> bool:
        calls.append(f"github:{tag_name}")
        return False

    def fake_local_tag_commit(tag_name: str) -> str | None:
        calls.append(f"local:{tag_name}")
        return None

    def fake_remote_tag_commit(tag_name: str) -> str | None:
        calls.append(f"remote:{tag_name}")
        return None

    monkeypatch.setattr(release, "github_release_exists", fake_github_release_exists)
    monkeypatch.setattr(release, "local_tag_commit", fake_local_tag_commit)
    monkeypatch.setattr(release, "remote_tag_commit", fake_remote_tag_commit)

    state = release.inspect_release_state(release.ROOT_TARGET, "0.1.1")

    assert state.github_release_exists is False
    assert state.tag_name == "v0.1.1"
    assert calls == ["github:v0.1.1", "local:v0.1.1", "remote:v0.1.1"]


def test_resolve_target_version_rejects_existing_github_release(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release = _load_release_module()

    def fake_read_current_version(target: Any = release.ROOT_TARGET) -> str:
        assert target == release.ROOT_TARGET
        return "0.1.1"

    def fake_inspect_release_state(target: Any, version: str) -> Any:
        assert target == release.ROOT_TARGET
        assert version == "0.1.1"
        return _release_state(release, github_release_exists=True)

    monkeypatch.setattr(release, "read_current_version", fake_read_current_version)
    monkeypatch.setattr(release, "inspect_release_state", fake_inspect_release_state)

    with pytest.raises(SystemExit, match="already exists as a GitHub Release"):
        release.resolve_target_version(None)


@pytest.mark.parametrize(
    (
        "local_tag_commit",
        "remote_tag_commit",
        "version_changed",
        "head_commit",
        "retag",
        "action",
    ),
    [
        ("old", None, True, release_head := "new", False, "replace_local"),
        (release_head, None, False, release_head, False, "push_local"),
        (None, release_head, False, release_head, False, "reuse_remote"),
        (None, "old", False, release_head, True, "replace_remote"),
    ],
)
def test_plan_tag_action(
    local_tag_commit: str | None,
    remote_tag_commit: str | None,
    version_changed: bool,
    head_commit: str,
    retag: bool,
    action: str,
) -> None:
    release = _load_release_module()
    state = _release_state(
        release,
        local_tag_commit=local_tag_commit,
        remote_tag_commit=remote_tag_commit,
    )

    tag_action = release.plan_tag_action(
        state,
        version_changed=version_changed,
        head_commit=head_commit,
        retag=retag,
    )

    assert tag_action.action == action


def test_plan_tag_action_rejects_remote_tag_at_different_commit() -> None:
    release = _load_release_module()
    state = _release_state(release, remote_tag_commit="old")

    with pytest.raises(SystemExit, match="Remote tag v0.1.1 exists"):
        release.plan_tag_action(
            state,
            version_changed=False,
            head_commit="new",
            retag=False,
        )


def test_dry_run_branch_push_reports_detached_head(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    release = _load_release_module()
    pushed_commands: list[tuple[str, ...]] = []

    def fake_capture_command(command: tuple[str, ...]) -> str:
        assert command == ("git", "rev-parse", "--abbrev-ref", "HEAD")
        return "HEAD"

    def fake_run_command(command: tuple[str, ...], *, dry_run: bool = False) -> None:
        pushed_commands.append(command)

    monkeypatch.setattr(release, "capture_command", fake_capture_command)
    monkeypatch.setattr(release, "run_command", fake_run_command)

    release.push_current_branch(dry_run=True)

    assert "DRY RUN: detached HEAD" in capsys.readouterr().out
    assert pushed_commands == []


def test_real_branch_push_rejects_detached_head(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release = _load_release_module()

    def fake_capture_command(command: tuple[str, ...]) -> str:
        assert command == ("git", "rev-parse", "--abbrev-ref", "HEAD")
        return "HEAD"

    monkeypatch.setattr(release, "capture_command", fake_capture_command)

    with pytest.raises(SystemExit, match="Cannot release from a detached HEAD"):
        release.push_current_branch(dry_run=False)


def test_remote_tag_commit_fails_on_remote_inspection_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release = _load_release_module()

    def fake_run(
        command: tuple[str, ...],
        *,
        cwd: Path,
        check: bool,
        text: bool,
        capture_output: bool,
    ) -> subprocess.CompletedProcess[str]:
        assert command[:4] == ("git", "ls-remote", "--tags", "origin")
        assert cwd == release.PROJECT_ROOT
        assert check is False
        assert text is True
        assert capture_output is True
        return subprocess.CompletedProcess(command, 128, "", "network down")

    monkeypatch.setattr(release.subprocess, "run", fake_run)

    with pytest.raises(SystemExit, match="Could not inspect remote tag v0.1.1"):
        release.remote_tag_commit("v0.1.1")


@pytest.mark.parametrize(
    ("remote", "slug"),
    [
        ("git@github.com:VanL/taut.git", "VanL/taut"),
        ("https://github.com/VanL/taut.git", "VanL/taut"),
        ("https://github.com/VanL/taut", "VanL/taut"),
    ],
)
def test_github_repo_slug_from_remote(remote: str, slug: str) -> None:
    release = _load_release_module()

    assert release.github_repo_slug_from_remote(remote) == slug


def test_precheck_commands_include_typed_release_helper() -> None:
    release = _load_release_module()

    commands = release.build_precheck_commands()

    assert ("uv", "run", "pytest") in commands
    assert ("uv", "run", "./bin/pytest-pg", "--fast") in commands
    assert release.SUMMON_UNIT_TEST_COMMAND in commands
    assert release.SUMMON_PROCESS_TEST_COMMAND in commands
    assert release.SUMMON_LIVE_HARNESS_TEST_COMMAND in commands
    assert release.SUMMON_LOCAL_LLM_TEST_COMMAND in commands
    assert any(
        command[:5] == ("uv", "run", "--extra", "dev", "ruff") for command in commands
    )
    assert any("extensions/taut_pg/taut_pg" in command for command in commands)
    assert any("extensions/taut_summon/taut_summon" in command for command in commands)
    assert (
        "uv",
        "run",
        "--extra",
        "dev",
        "mypy",
        "taut",
        "tests",
        "bin/release.py",
        "--config-file",
        "pyproject.toml",
    ) in commands


def test_pg_precheck_commands_include_pg_gate_and_extension_checks() -> None:
    release = _load_release_module()

    commands = release.build_precheck_commands(release.PG_TARGET)

    assert ("uv", "run", "./bin/pytest-pg", "--fast") in commands
    assert any("extensions/taut_pg/taut_pg" in command for command in commands)
    assert any("taut/_scripts.py" in command for command in commands)
    assert all("pypi" not in " ".join(command).lower() for command in commands)


def test_summon_precheck_commands_include_extension_gate() -> None:
    release = _load_release_module()

    commands = release.build_precheck_commands(release.SUMMON_TARGET)

    assert release.SUMMON_UNIT_TEST_COMMAND in commands
    assert release.SUMMON_PROCESS_TEST_COMMAND in commands
    assert release.SUMMON_LIVE_HARNESS_TEST_COMMAND in commands
    assert release.SUMMON_LOCAL_LLM_TEST_COMMAND in commands
    assert (
        "xdist_group and not requires_live_harness and not requires_local_llm"
        in release.SUMMON_PROCESS_TEST_COMMAND
    )
    assert release.SUMMON_PROCESS_TEST_COMMAND[-4:] == (
        "-n",
        "1",
        "--dist",
        "loadgroup",
    )
    assert any("extensions/taut_summon/taut_summon" in command for command in commands)
    assert any("extensions/taut_summon/tests" in command for command in commands)
    assert all("pypi" not in " ".join(command).lower() for command in commands)


def test_summon_precheck_env_splits_live_and_local_llm_lanes() -> None:
    release = _load_release_module()

    live_env = release._precheck_env_overrides(  # noqa: SLF001
        release.SUMMON_LIVE_HARNESS_TEST_COMMAND,
    )
    local_llm_env = release._precheck_env_overrides(  # noqa: SLF001
        release.SUMMON_LOCAL_LLM_TEST_COMMAND,
        local_llm_env={
            "TAUT_SUMMON_LOCAL_LLM_ENDPOINT": "http://127.0.0.1:9999/v1",
            "TAUT_SUMMON_LOCAL_LLM_MODEL": "local-test:latest",
        },
    )

    assert live_env["PYTEST_ADDOPTS"] == "-x --maxfail=1"
    assert live_env["TAUT_SUMMON_LIVE_HARNESS_STRICT"] == "1"
    assert "TAUT_SUMMON_LOCAL_LLM" not in live_env
    assert local_llm_env["PYTEST_ADDOPTS"] == "-x --maxfail=1"
    assert local_llm_env["TAUT_SUMMON_LOCAL_LLM"] == "1"
    assert local_llm_env["TAUT_SUMMON_LOCAL_LLM_ENDPOINT"] == "http://127.0.0.1:9999/v1"
    assert local_llm_env["TAUT_SUMMON_LOCAL_LLM_MODEL"] == "local-test:latest"
    assert "TAUT_SUMMON_LIVE_HARNESS_STRICT" not in local_llm_env


def test_local_llm_model_probe_treats_startup_disconnect_as_not_ready(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release = _load_release_module()

    def disconnected(_url: str, *, timeout: float) -> dict[str, object]:
        raise http.client.RemoteDisconnected("Remote end closed connection")

    monkeypatch.setattr(release, "_read_json_url", disconnected)

    assert (
        release._endpoint_has_model(  # noqa: SLF001
            "http://127.0.0.1:9999/v1", "local-test:latest"
        )
        is False
    )


def test_prechecks_start_local_llm_before_other_release_gates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release = _load_release_module()
    events: list[tuple[str, object]] = []
    commands = (
        ("root-tests",),
        release.PG_TEST_COMMAND,
        release.SUMMON_UNIT_TEST_COMMAND,
        release.SUMMON_PROCESS_TEST_COMMAND,
        release.SUMMON_LIVE_HARNESS_TEST_COMMAND,
        release.SUMMON_LOCAL_LLM_TEST_COMMAND,
        ("lint",),
    )

    class FakeLocalLlmPreparation:
        env_overrides = {
            "TAUT_SUMMON_LOCAL_LLM": "1",
            "TAUT_SUMMON_LOCAL_LLM_ENDPOINT": "http://127.0.0.1:9999/v1",
            "TAUT_SUMMON_LOCAL_LLM_MODEL": "local-test:latest",
        }

        def __init__(self, *, dry_run: bool) -> None:
            events.append(("init", dry_run))

        def start(self) -> None:
            events.append(("start", None))

        def wait_ready(self) -> None:
            events.append(("wait", None))

        def close(self) -> None:
            events.append(("close", None))

    def fake_build_precheck_commands_for_targets(targets: tuple[object, ...]) -> Any:
        assert targets == (release.ROOT_TARGET, release.SUMMON_TARGET)
        return commands

    def fake_run_command(
        command: tuple[str, ...],
        *,
        dry_run: bool = False,
        env_overrides: dict[str, str] | None = None,
    ) -> None:
        events.append(("run", command))
        if command == release.SUMMON_LIVE_HARNESS_TEST_COMMAND:
            assert env_overrides is not None
            assert env_overrides["TAUT_SUMMON_LIVE_HARNESS_STRICT"] == "1"
            assert "TAUT_SUMMON_LOCAL_LLM" not in env_overrides
        if command == release.SUMMON_LOCAL_LLM_TEST_COMMAND:
            assert env_overrides is not None
            assert env_overrides["TAUT_SUMMON_LOCAL_LLM"] == "1"
            assert "TAUT_SUMMON_LIVE_HARNESS_STRICT" not in env_overrides
            assert (
                env_overrides["TAUT_SUMMON_LOCAL_LLM_ENDPOINT"]
                == "http://127.0.0.1:9999/v1"
            )

    monkeypatch.setattr(release, "LocalLlmPreparation", FakeLocalLlmPreparation)
    monkeypatch.setattr(
        release,
        "build_precheck_commands_for_targets",
        fake_build_precheck_commands_for_targets,
    )
    monkeypatch.setattr(release, "run_command", fake_run_command)

    release.run_prechecks_for_targets(
        (release.ROOT_TARGET, release.SUMMON_TARGET),
        dry_run=False,
    )

    assert events == [
        ("init", False),
        ("start", None),
        ("run", ("root-tests",)),
        ("run", release.PG_TEST_COMMAND),
        ("run", release.SUMMON_UNIT_TEST_COMMAND),
        ("run", release.SUMMON_PROCESS_TEST_COMMAND),
        ("run", release.SUMMON_LIVE_HARNESS_TEST_COMMAND),
        ("wait", None),
        ("run", release.SUMMON_LOCAL_LLM_TEST_COMMAND),
        ("run", ("lint",)),
        ("close", None),
    ]


def test_pg_postupdate_builds_extension_path() -> None:
    release = _load_release_module()

    steps = release.build_postupdate_steps(release.PG_TARGET)

    assert steps[0].command == ("uv", "build", "extensions/taut_pg")


def test_summon_postupdate_locks_and_builds_extension() -> None:
    release = _load_release_module()

    steps = release.build_postupdate_steps(release.SUMMON_TARGET)

    assert steps[0].command == ("uv", "lock")
    assert steps[0].cwd == release.SUMMON_EXTENSION_DIR
    assert steps[1].command == ("uv", "build", "extensions/taut_summon")
    assert steps[2].command == (
        sys.executable,
        str(release.REACTOR_RELEASE_ARTIFACT_VERIFIER),
    )


def test_core_postupdate_verifies_fresh_paired_artifacts_after_normal_build() -> None:
    release = _load_release_module()

    steps = release.build_postupdate_steps(release.ROOT_TARGET)

    assert [step.command for step in steps] == [
        ("uv", "lock"),
        ("uv", "build"),
        (
            sys.executable,
            str(release.REACTOR_RELEASE_ARTIFACT_VERIFIER),
        ),
    ]
    assert steps[0].cwd == release.SUMMON_EXTENSION_DIR


def test_core_dry_run_executes_only_the_helpers_dry_run_plan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release = _load_release_module()
    calls: list[tuple[tuple[str, ...], bool]] = []

    def fake_run_command(
        command: tuple[str, ...],
        *,
        cwd: Path = release.PROJECT_ROOT,
        dry_run: bool = False,
        **_kwargs: object,
    ) -> None:
        if command == ("uv", "lock"):
            assert cwd == release.SUMMON_EXTENSION_DIR
        else:
            assert cwd == release.PROJECT_ROOT
        calls.append((command, dry_run))

    monkeypatch.setattr(release, "run_command", fake_run_command)

    release.run_postupdate_steps(release.ROOT_TARGET, dry_run=True)

    assert calls == [
        (("uv", "lock"), True),
        (("uv", "build"), True),
        (
            (
                sys.executable,
                str(release.REACTOR_RELEASE_ARTIFACT_VERIFIER),
                "--dry-run",
            ),
            False,
        ),
    ]


def test_pg_postupdate_skips_paired_artifact_verification() -> None:
    release = _load_release_module()

    steps = release.build_postupdate_steps(release.PG_TARGET)

    assert [step.command for step in steps] == [("uv", "build", "extensions/taut_pg")]


def test_matching_batch_verifies_once_after_all_normal_builds() -> None:
    release = _load_release_module()

    steps = release.build_postupdate_steps_for_targets(
        (release.PG_TARGET, release.SUMMON_TARGET, release.ROOT_TARGET)
    )

    assert [step.command for step in steps] == [
        ("uv", "lock"),
        ("uv", "build"),
        ("uv", "build", "extensions/taut_pg"),
        ("uv", "build", "extensions/taut_summon"),
        (sys.executable, str(release.REACTOR_RELEASE_ARTIFACT_VERIFIER)),
    ]


def test_verifier_failure_under_skip_checks_stops_release_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release = _load_release_module()
    state = _release_state(release)
    commands: list[tuple[str, ...]] = []

    monkeypatch.setattr(release, "is_dirty_worktree", lambda: False)
    monkeypatch.setattr(
        release,
        "resolve_target_version",
        lambda _version, _target: ("0.1.1", "0.1.1", state),
    )
    monkeypatch.setattr(release, "current_head_commit", lambda: "head")
    monkeypatch.setattr(release, "_require_command", lambda _name: None)
    monkeypatch.setattr(release, "_sync_root_release_dependencies", lambda: None)
    monkeypatch.setattr(
        release,
        "run_prechecks",
        lambda *_args, **_kwargs: pytest.fail("--skip-checks must skip prechecks"),
    )
    monkeypatch.setattr(
        release,
        "release_files_changed",
        lambda _target: pytest.fail("verification must precede release mutation"),
    )
    monkeypatch.setattr(
        release,
        "prepare_tag",
        lambda *_args, **_kwargs: pytest.fail("verification must precede tags"),
    )
    monkeypatch.setattr(
        release,
        "push_current_branch",
        lambda **_kwargs: pytest.fail("verification must precede pushes"),
    )

    def fake_run_command(
        command: tuple[str, ...],
        **_kwargs: object,
    ) -> None:
        commands.append(command)
        if command == (
            sys.executable,
            str(release.REACTOR_RELEASE_ARTIFACT_VERIFIER),
        ):
            raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(release, "run_command", fake_run_command)

    with pytest.raises(subprocess.CalledProcessError):
        release.main(["core", "--skip-checks"])

    assert commands == [
        ("uv", "lock"),
        ("uv", "build"),
        (sys.executable, str(release.REACTOR_RELEASE_ARTIFACT_VERIFIER)),
    ]


def test_version_changed_core_syncs_pair_before_verifier_failure_stops_git(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release = _load_release_module()
    state = _release_state(release)
    events: list[str] = []

    monkeypatch.setattr(release, "is_dirty_worktree", lambda: False)
    monkeypatch.setattr(
        release,
        "resolve_target_version",
        lambda _version, _target: ("0.5.1", "0.6.0", state),
    )
    monkeypatch.setattr(release, "current_head_commit", lambda: "head")
    monkeypatch.setattr(release, "_require_command", lambda _name: None)
    monkeypatch.setattr(
        release,
        "write_version_files",
        lambda version, target: events.append(f"write:{target.key}:{version}"),
    )
    monkeypatch.setattr(
        release,
        "_sync_root_release_dependencies",
        lambda: events.append("sync-paired-floors"),
    )
    monkeypatch.setattr(
        release,
        "prepare_tag",
        lambda *_args, **_kwargs: pytest.fail("verification must precede tags"),
    )
    monkeypatch.setattr(
        release,
        "push_current_branch",
        lambda **_kwargs: pytest.fail("verification must precede pushes"),
    )

    def fake_run_command(command: tuple[str, ...], **_kwargs: object) -> None:
        if command[:2] == ("git", "add") or command[:2] == ("git", "commit"):
            pytest.fail("verification must precede release commits")
        if command == (
            sys.executable,
            str(release.REACTOR_RELEASE_ARTIFACT_VERIFIER),
        ):
            events.append("verify")
            raise subprocess.CalledProcessError(1, command)
        events.append(":".join(command))

    monkeypatch.setattr(release, "run_command", fake_run_command)

    with pytest.raises(subprocess.CalledProcessError):
        release.main(["core", "--version", "0.6.0", "--skip-checks"])

    assert events == [
        "write:core:0.6.0",
        "sync-paired-floors",
        "uv:lock",
        "uv:build",
        "verify",
    ]


def test_version_changed_core_verifies_before_staging_paired_files(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release = _load_release_module()
    state = _release_state(release)
    events: list[tuple[str, ...]] = []

    monkeypatch.setattr(release, "is_dirty_worktree", lambda: False)
    monkeypatch.setattr(
        release,
        "resolve_target_version",
        lambda _version, _target: ("0.5.1", "0.6.0", state),
    )
    monkeypatch.setattr(release, "current_head_commit", lambda: "head")
    monkeypatch.setattr(release, "_require_command", lambda _name: None)
    monkeypatch.setattr(release, "write_version_files", lambda *_args: None)
    monkeypatch.setattr(release, "_sync_root_release_dependencies", lambda: None)
    monkeypatch.setattr(
        release,
        "run_command",
        lambda command, **_kwargs: events.append(command),
    )
    monkeypatch.setattr(
        release,
        "push_current_branch",
        lambda **_kwargs: events.append(("push-current-branch",)),
    )

    assert release.main(["core", "--version", "0.6.0", "--skip-checks"]) == 0

    verifier = (
        sys.executable,
        str(release.REACTOR_RELEASE_ARTIFACT_VERIFIER),
    )
    git_add = next(command for command in events if command[:2] == ("git", "add"))
    assert events.index(verifier) < events.index(git_add)
    assert release.display_path(release.SUMMON_PYPROJECT_PATH) in git_add
    assert release.display_path(release.SUMMON_UV_LOCK_PATH) in git_add
    assert events.index(git_add) < events.index(("git", "tag", "v0.1.1"))
    assert events.index(("git", "tag", "v0.1.1")) < events.index(
        ("push-current-branch",)
    )


def test_parse_args_accepts_positional_all_and_target_compat() -> None:
    release = _load_release_module()

    assert release.parse_args(["all"]).target == "all"
    assert release.parse_args(["--target", "pg"]).target == "pg"
    assert release.parse_args(["summon", "--skip-checks"]).target == "summon"

    with pytest.raises(SystemExit):
        release.parse_args(["pg", "--target", "summon"])


def test_discover_unpublished_releases_filters_published_targets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release = _load_release_module()

    def fake_read_target_version(target: Any) -> str:
        versions = {
            release.PG_TARGET: "0.5.0",
            release.SUMMON_TARGET: "0.5.0",
            release.ROOT_TARGET: "0.5.0",
        }
        return versions[target]

    def fake_inspect_release_state(target: Any, version: str) -> Any:
        assert version == "0.5.0"
        return _release_state(
            release,
            target=target,
            github_release_exists=target == release.PG_TARGET,
        )

    monkeypatch.setattr(release, "read_target_version", fake_read_target_version)
    monkeypatch.setattr(release, "inspect_release_state", fake_inspect_release_state)

    candidates = release.discover_unpublished_releases(
        (release.PG_TARGET, release.SUMMON_TARGET, release.ROOT_TARGET)
    )

    assert [candidate.target for candidate in candidates] == [
        release.SUMMON_TARGET,
        release.ROOT_TARGET,
    ]


def test_release_file_paths_for_targets_dedupes_root_files() -> None:
    release = _load_release_module()

    paths = release._release_file_paths_for_targets(  # noqa: SLF001
        (release.ROOT_TARGET, release.ROOT_TARGET, release.SUMMON_TARGET)
    )

    assert paths.count(release.PYPROJECT_PATH) == 1
    assert release.CONSTANTS_PATH in paths
    assert release.SUMMON_PYPROJECT_PATH in paths
    assert release.SUMMON_UV_LOCK_PATH in paths


def test_core_release_tracks_paired_summon_floor_and_retained_lock() -> None:
    release = _load_release_module()

    paths = release._release_file_paths(release.ROOT_TARGET)  # noqa: SLF001

    assert release.SUMMON_PYPROJECT_PATH in paths
    assert release.SUMMON_UV_LOCK_PATH in paths


def test_pg_lockfile_is_not_retained_and_is_ignored() -> None:
    release = _load_release_module()
    pg_lock_path = release.PG_EXTENSION_DIR / "uv.lock"

    assert not pg_lock_path.exists()
    assert (
        "extensions/taut_pg/uv.lock"
        in (release.PROJECT_ROOT / ".gitignore")
        .read_text(encoding="utf-8")
        .splitlines()
    )


def test_dry_run_publish_is_github_only_noop(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    release = _load_release_module()

    def fake_read_current_version(target: Any = release.ROOT_TARGET) -> str:
        assert target in {release.ROOT_TARGET, release.SUMMON_TARGET}
        return "0.1.1"

    def fake_inspect_release_state(target: Any, version: str) -> Any:
        assert target == release.ROOT_TARGET
        assert version == "0.1.1"
        return _release_state(release, local_tag_commit="new")

    def fake_is_dirty_worktree() -> bool:
        return False

    def fake_current_head_commit() -> str:
        return "new"

    monkeypatch.setattr(release, "read_current_version", fake_read_current_version)
    monkeypatch.setattr(release, "inspect_release_state", fake_inspect_release_state)
    monkeypatch.setattr(release, "is_dirty_worktree", fake_is_dirty_worktree)
    monkeypatch.setattr(release, "current_head_commit", fake_current_head_commit)

    release.main(["--dry-run", "--skip-checks", "--publish"])

    output = capsys.readouterr().out
    assert "--publish is ignored" in output
    assert "GitHub-only" in output
    assert "v0.1.1" in output


def test_capture_command_returns_stdout(monkeypatch: pytest.MonkeyPatch) -> None:
    release = _load_release_module()

    def fake_run(
        command: tuple[str, ...],
        *,
        cwd: Path,
        check: bool,
        text: bool,
        capture_output: bool,
    ) -> subprocess.CompletedProcess[str]:
        assert command == ("git", "rev-parse", "HEAD")
        assert cwd == release.PROJECT_ROOT
        assert check is True
        assert text is True
        assert capture_output is True
        return subprocess.CompletedProcess(command, 0, "abc123\n", "")

    monkeypatch.setattr(release.subprocess, "run", fake_run)

    assert release.capture_command(("git", "rev-parse", "HEAD")) == "abc123"
