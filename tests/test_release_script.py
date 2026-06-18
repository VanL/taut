from __future__ import annotations

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
                '    "simplebroker-pg>=2.2.1",',
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
    assert ("uv", "run", "ruff", "check", "taut", "tests", "bin") in commands
    assert (
        "uv",
        "run",
        "ruff",
        "format",
        "--check",
        "taut",
        "tests",
        "bin",
    ) in commands
    assert ("uv", "run", "mypy", "taut", "tests", "bin/release.py") in commands


def test_pg_precheck_commands_include_pg_gate_and_extension_checks() -> None:
    release = _load_release_module()

    commands = release.build_precheck_commands(release.PG_TARGET)

    assert ("uv", "run", "./bin/pytest-pg", "--fast") in commands
    assert ("uv", "build", "extensions/taut_pg") in commands
    assert any("extensions/taut_pg/taut_pg" in command for command in commands)
    assert any("taut/_scripts.py" in command for command in commands)
    assert all("pypi" not in " ".join(command).lower() for command in commands)


def test_pg_postupdate_builds_extension_path() -> None:
    release = _load_release_module()

    steps = release.build_postupdate_steps(release.PG_TARGET)

    assert steps[0].command == ("uv", "build", "extensions/taut_pg")


def test_dry_run_publish_is_github_only_noop(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    release = _load_release_module()

    def fake_read_current_version(target: Any = release.ROOT_TARGET) -> str:
        assert target == release.ROOT_TARGET
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
