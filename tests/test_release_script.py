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


def _load_release_module(script_path: Path = RELEASE_SCRIPT) -> Any:
    spec = importlib.util.spec_from_file_location("taut_release", script_path)
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


def test_read_manifest_version_allows_repairing_a_stale_derived_constant(
    tmp_path: Path,
) -> None:
    release = _load_release_module()
    pyproject_path = tmp_path / "pyproject.toml"
    constants_path = tmp_path / "taut" / "_constants.py"
    constants_path.parent.mkdir()
    pyproject_path.write_text(
        '[project]\nname = "taut"\nversion = "0.6.1"\n',
        encoding="utf-8",
    )
    constants_path.write_text('__version__: Final[str] = "0.6.0"\n', encoding="utf-8")
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

    assert release.read_manifest_version(target) == "0.6.1"


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

    def fake_read_manifest_version(target: object = release.ROOT_TARGET) -> str:
        assert target == release.ROOT_TARGET
        return "0.2.0"

    monkeypatch.setattr(release, "read_manifest_version", fake_read_manifest_version)

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

    def fake_read_manifest_version(target: object = release.ROOT_TARGET) -> str:
        assert target == release.ROOT_TARGET
        return "0.5.1"

    monkeypatch.setattr(release, "read_manifest_version", fake_read_manifest_version)

    release.write_version_files("0.5.1", target)

    text = pyproject_path.read_text(encoding="utf-8")
    assert 'version = "0.5.1"' in text
    assert '"taut>=0.5.1",' in text


def test_sync_readme_version_examples_updates_only_selected_artifact(
    tmp_path: Path,
) -> None:
    release = _load_release_module()
    root = tmp_path / "README.md"
    pg = tmp_path / "pg.md"
    summon = tmp_path / "summon.md"
    root.write_text(
        "core @v0.5.2\n./taut_pg-0.5.2-py3-none-any.whl\n"
        "./taut_summon-0.5.2-py3-none-any.whl\n",
        encoding="utf-8",
    )
    pg.write_text(
        "core @v0.5.2\n./taut_pg-0.5.2-py3-none-any.whl\n",
        encoding="utf-8",
    )
    summon.write_text(
        "core @v0.5.2\n./taut_summon-0.5.2-py3-none-any.whl\n",
        encoding="utf-8",
    )

    release.sync_readme_version_examples(
        release.ROOT_TARGET,
        "0.5.3",
        root_readme_path=root,
        pg_readme_path=pg,
        summon_readme_path=summon,
    )
    release.sync_readme_version_examples(
        release.PG_TARGET,
        "0.5.4",
        root_readme_path=root,
        pg_readme_path=pg,
        summon_readme_path=summon,
    )
    release.sync_readme_version_examples(
        release.SUMMON_TARGET,
        "0.5.5",
        root_readme_path=root,
        pg_readme_path=pg,
        summon_readme_path=summon,
    )

    assert root.read_text(encoding="utf-8") == (
        "core @v0.5.3\n./taut_pg-0.5.4-py3-none-any.whl\n"
        "./taut_summon-0.5.5-py3-none-any.whl\n"
    )
    assert pg.read_text(encoding="utf-8") == (
        "core @v0.5.3\n./taut_pg-0.5.4-py3-none-any.whl\n"
    )
    assert summon.read_text(encoding="utf-8") == (
        "core @v0.5.3\n./taut_summon-0.5.5-py3-none-any.whl\n"
    )


def test_sync_readme_simplebroker_requirement_replaces_every_exact_copy(
    tmp_path: Path,
) -> None:
    release = _load_release_module()
    pyproject = tmp_path / "pyproject.toml"
    readme = tmp_path / "README.md"
    pyproject.write_text(
        "\n".join(
            (
                "[project]",
                'name = "taut"',
                'version = "0.6.1"',
                "dependencies = [",
                '    "simplebroker>=5.3.2",',
                "]",
                "",
            )
        ),
        encoding="utf-8",
    )
    readme.write_text(
        "Install simplebroker>=5.3.0 here.\nThen verify `simplebroker>=5.3.1` there.\n",
        encoding="utf-8",
    )

    assert (
        release.sync_readme_simplebroker_requirement(
            root_pyproject_path=pyproject,
            root_readme_path=readme,
        )
        == "5.3.2"
    )
    text = readme.read_text(encoding="utf-8")
    assert text.count("simplebroker>=5.3.2") == 2
    assert "simplebroker>=5.3.0" not in text
    assert "simplebroker>=5.3.1" not in text


def test_prepare_release_metadata_repairs_all_derived_copies_idempotently(
    tmp_path: Path,
) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    script = bin_dir / "release.py"
    script.write_text(RELEASE_SCRIPT.read_text(encoding="utf-8"), encoding="utf-8")
    (tmp_path / "taut").mkdir()
    (tmp_path / "extensions" / "taut_pg").mkdir(parents=True)
    (tmp_path / "extensions" / "taut_summon").mkdir(parents=True)
    (tmp_path / "pyproject.toml").write_text(
        "\n".join(
            (
                "[project]",
                'name = "taut"',
                'version = "0.6.1"',
                "dependencies = [",
                '    "simplebroker>=5.3.2",',
                "]",
                "[project.optional-dependencies]",
                "dev = [",
                '    "simplebroker-pg>=3.2.0",',
                '    "taut-summon>=0.5.0",',
                "]",
                "",
            )
        ),
        encoding="utf-8",
    )
    (tmp_path / "taut" / "_constants.py").write_text(
        '__version__: Final[str] = "0.5.0"\n', encoding="utf-8"
    )
    (tmp_path / "extensions" / "taut_pg" / "pyproject.toml").write_text(
        '[project]\nname = "taut-pg"\nversion = "0.5.0"\n'
        'dependencies = [\n    "taut>=0.5.0",\n'
        '    "simplebroker-pg>=3.2.1",\n]\n',
        encoding="utf-8",
    )
    (tmp_path / "extensions" / "taut_summon" / "pyproject.toml").write_text(
        '[project]\nname = "taut-summon"\nversion = "0.5.0"\n'
        'dependencies = [\n    "taut>=0.5.0",\n]\n',
        encoding="utf-8",
    )
    (tmp_path / "README.md").write_text(
        "core @v0.5.0\n"
        "taut_pg-0.5.0-py3-none-any.whl\n"
        "taut_summon-0.5.0-py3-none-any.whl\n"
        "simplebroker>=5.3.0\nsimplebroker>=5.3.1\n",
        encoding="utf-8",
    )
    (tmp_path / "extensions" / "taut_pg" / "README.md").write_text(
        "core @v0.5.0\ntaut_pg-0.5.0-py3-none-any.whl\n",
        encoding="utf-8",
    )
    (tmp_path / "extensions" / "taut_summon" / "README.md").write_text(
        "core @v0.5.0\ntaut_summon-0.5.0-py3-none-any.whl\n",
        encoding="utf-8",
    )
    release = _load_release_module(script)
    target_versions = (
        (release.ROOT_TARGET, "0.6.1"),
        (release.PG_TARGET, "0.6.2"),
        (release.SUMMON_TARGET, "0.6.3"),
    )

    release.prepare_release_metadata(target_versions)
    first = {
        path: path.read_text(encoding="utf-8")
        for path in (
            tmp_path / "pyproject.toml",
            tmp_path / "taut" / "_constants.py",
            tmp_path / "README.md",
            tmp_path / "extensions" / "taut_pg" / "pyproject.toml",
            tmp_path / "extensions" / "taut_pg" / "README.md",
            tmp_path / "extensions" / "taut_summon" / "pyproject.toml",
            tmp_path / "extensions" / "taut_summon" / "README.md",
        )
    }
    release.prepare_release_metadata(target_versions)

    assert first == {path: path.read_text(encoding="utf-8") for path in first}
    assert (
        '__version__: Final[str] = "0.6.1"'
        in first[tmp_path / "taut" / "_constants.py"]
    )
    assert '"taut-summon>=0.6.3",' in first[tmp_path / "pyproject.toml"]
    assert '"simplebroker-pg>=3.2.1",' in first[tmp_path / "pyproject.toml"]
    assert (
        'version = "0.6.2"'
        in first[tmp_path / "extensions" / "taut_pg" / "pyproject.toml"]
    )
    assert (
        '"taut>=0.6.1",'
        in first[tmp_path / "extensions" / "taut_summon" / "pyproject.toml"]
    )
    assert first[tmp_path / "README.md"].count("simplebroker>=5.3.2") == 2
    assert "0.5.0" not in "".join(first.values())


def test_target_specific_preparation_preserves_other_manifest_versions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release = _load_release_module()
    manifest_versions = {
        release.ROOT_TARGET: "0.6.1",
        release.PG_TARGET: "0.5.9",
        release.SUMMON_TARGET: "0.5.8",
    }
    prepared_versions = dict(manifest_versions)
    prepared_versions[release.PG_TARGET] = "0.6.2"
    writes: list[tuple[Any, str]] = []
    monkeypatch.setattr(
        release,
        "read_manifest_version",
        lambda target: manifest_versions[target],
    )
    monkeypatch.setattr(
        release,
        "write_version_files",
        lambda version, target: writes.append((target, version)),
    )
    monkeypatch.setattr(release, "_sync_root_release_dependencies", lambda: None)
    monkeypatch.setattr(
        release, "sync_readme_simplebroker_requirement", lambda: "5.3.2"
    )
    monkeypatch.setattr(
        release,
        "read_current_version",
        lambda target: prepared_versions[target],
    )

    release.prepare_release_metadata(((release.PG_TARGET, "0.6.2"),))

    assert writes == [
        (release.ROOT_TARGET, "0.6.1"),
        (release.PG_TARGET, "0.6.2"),
        (release.SUMMON_TARGET, "0.5.8"),
    ]


def test_public_release_flow_commits_preparation_then_reuses_it_after_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "bin").mkdir()
    script = tmp_path / "bin" / "release.py"
    script.write_text(RELEASE_SCRIPT.read_text(encoding="utf-8"), encoding="utf-8")
    (tmp_path / "taut").mkdir()
    (tmp_path / "extensions" / "taut_pg").mkdir(parents=True)
    (tmp_path / "extensions" / "taut_summon").mkdir(parents=True)
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "taut"\nversion = "0.6.1"\n'
        'dependencies = [\n    "simplebroker>=5.3.2",\n]\n'
        "[project.optional-dependencies]\ndev = [\n"
        '    "simplebroker-pg>=3.2.0",\n'
        '    "taut-summon>=0.5.0",\n]\n',
        encoding="utf-8",
    )
    (tmp_path / "taut" / "_constants.py").write_text(
        '__version__: Final[str] = "0.5.0"\n', encoding="utf-8"
    )
    (tmp_path / "extensions" / "taut_pg" / "pyproject.toml").write_text(
        '[project]\nname = "taut-pg"\nversion = "0.6.1"\n'
        'dependencies = [\n    "taut>=0.5.0",\n'
        '    "simplebroker-pg>=3.2.1",\n]\n',
        encoding="utf-8",
    )
    (tmp_path / "extensions" / "taut_summon" / "pyproject.toml").write_text(
        '[project]\nname = "taut-summon"\nversion = "0.6.1"\n'
        'dependencies = [\n    "taut>=0.5.0",\n]\n',
        encoding="utf-8",
    )
    (tmp_path / "README.md").write_text(
        "core @v0.5.0\n"
        "taut_pg-0.5.0-py3-none-any.whl\n"
        "taut_summon-0.5.0-py3-none-any.whl\n"
        "simplebroker>=5.3.0\nsimplebroker>=5.3.1\n",
        encoding="utf-8",
    )
    (tmp_path / "extensions" / "taut_pg" / "README.md").write_text(
        "core @v0.5.0\ntaut_pg-0.5.0-py3-none-any.whl\n",
        encoding="utf-8",
    )
    (tmp_path / "extensions" / "taut_summon" / "README.md").write_text(
        "core @v0.5.0\ntaut_summon-0.5.0-py3-none-any.whl\n",
        encoding="utf-8",
    )
    (tmp_path / "extensions" / "taut_summon" / "uv.lock").write_text(
        "stale retained lock\n", encoding="utf-8"
    )
    (tmp_path / "CHANGELOG.md").write_text(
        "# Changelog\n\n## 0.6.1 - 2026-07-13\n", encoding="utf-8"
    )
    (tmp_path / ".gitignore").write_text("__pycache__/\n", encoding="utf-8")
    (tmp_path / "unrelated.txt").write_text("untouched\n", encoding="utf-8")
    for command in (
        ("git", "init", "-b", "main"),
        ("git", "config", "user.name", "Release Test"),
        ("git", "config", "user.email", "release-test@example.com"),
        ("git", "add", "."),
        ("git", "commit", "-m", "Initial stale metadata"),
    ):
        subprocess.run(command, cwd=tmp_path, check=True, capture_output=True)

    release = _load_release_module(script)
    initial_head = release.current_head_commit()
    events: list[str] = []
    precheck_count = 0

    def fake_inspect_release_state(target: Any, version: str) -> Any:
        return release.ReleaseState(
            target=target,
            version=version,
            tag_name=target.tag_for_version(version),
            github_release_exists=False,
            local_tag_commit=None,
            remote_tag_commit=None,
        )

    def fake_run_command(
        command: tuple[str, ...],
        *,
        cwd: Path = release.PROJECT_ROOT,
        **_kwargs: object,
    ) -> None:
        if command[:2] == ("uv", "lock"):
            events.append("lock")
            release.SUMMON_UV_LOCK_PATH.write_text(
                "taut=0.6.1\ntaut-summon=0.6.1\nsimplebroker=5.3.2\n",
                encoding="utf-8",
            )
            return
        if command[:2] == ("git", "add"):
            events.append("git-add")
            subprocess.run(command, cwd=cwd, check=True)
            return
        if command[:2] == ("git", "commit"):
            events.append("git-commit")
            subprocess.run(command, cwd=cwd, check=True, capture_output=True)
            return
        if command == ("uv", "build"):
            events.append("build")
            return
        if command == (sys.executable, str(release.RELEASE_WHEEL_SET_CHECKER)):
            events.append("wheel-check")
            return
        pytest.fail(f"unexpected command: {command}")

    def fake_prechecks(_target: Any, *, dry_run: bool) -> None:
        nonlocal precheck_count
        assert dry_run is False
        assert release.is_dirty_worktree() is False
        assert release.current_head_commit() != initial_head
        precheck_count += 1
        events.append(f"precheck-{precheck_count}")
        if precheck_count == 1:
            raise SystemExit("simulated proof failure")

    monkeypatch.setattr(release, "inspect_release_state", fake_inspect_release_state)
    monkeypatch.setattr(release, "run_command", fake_run_command)
    monkeypatch.setattr(release, "run_prechecks", fake_prechecks)
    monkeypatch.setattr(release, "_require_command", lambda _name: None)
    monkeypatch.setattr(
        release,
        "prepare_tag",
        lambda *_args, **_kwargs: events.append("tag"),
    )
    monkeypatch.setattr(
        release,
        "push_current_branch",
        lambda **_kwargs: events.append("push-branch"),
    )
    monkeypatch.setattr(
        release,
        "push_tag",
        lambda *_args, **_kwargs: events.append("push-tag"),
    )

    with pytest.raises(SystemExit, match="simulated proof failure"):
        release.main(["core"])

    preparation_head = release.current_head_commit()
    assert preparation_head != initial_head
    changed_paths = set(
        release.capture_command(
            ("git", "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD")
        ).splitlines()
    )
    assert changed_paths == set(release._release_file_args(release.ROOT_TARGET))  # noqa: SLF001
    assert events == ["lock", "git-add", "git-commit", "precheck-1"]
    assert release.is_dirty_worktree() is False

    events.clear()
    assert release.main(["core"]) == 0
    assert release.current_head_commit() == preparation_head
    assert events == [
        "lock",
        "precheck-2",
        "build",
        "wheel-check",
        "tag",
        "push-branch",
        "push-tag",
    ]
    assert release.is_dirty_worktree() is False


def test_summon_target_tracks_root_and_extension_readme_examples() -> None:
    release = _load_release_module()

    assert release.ROOT_README_PATH in release.target_version_files(
        release.SUMMON_TARGET
    )
    assert release.SUMMON_README_PATH in release.target_version_files(
        release.SUMMON_TARGET
    )
    assert release.ROOT_README_PATH in release._release_file_paths(  # noqa: SLF001
        release.SUMMON_TARGET
    )


def test_require_changelog_heading_rejects_missing_target(tmp_path: Path) -> None:
    release = _load_release_module()
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text(
        "# Changelog\n\n## 0.5.2 - 2026-07-11\n",
        encoding="utf-8",
    )

    release.require_changelog_heading("0.5.2", changelog_path=changelog)
    with pytest.raises(SystemExit, match="CHANGELOG.md has no heading for 0.5.3"):
        release.require_changelog_heading("0.5.3", changelog_path=changelog)


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


def test_sync_root_pg_dev_dependency_uses_pg_manifest_floor(tmp_path: Path) -> None:
    release = _load_release_module()
    root_pyproject_path = tmp_path / "pyproject.toml"
    pg_pyproject_path = tmp_path / "extensions" / "taut_pg" / "pyproject.toml"
    pg_pyproject_path.parent.mkdir(parents=True)
    root_pyproject_path.write_text(
        '[project]\nname = "taut"\nversion = "0.6.1"\n'
        "[project.optional-dependencies]\ndev = [\n"
        '    "simplebroker-pg>=3.2.0",\n]\n',
        encoding="utf-8",
    )
    pg_pyproject_path.write_text(
        '[project]\nname = "taut-pg"\nversion = "0.6.1"\n'
        'dependencies = [\n    "simplebroker-pg>=3.2.1",\n]\n',
        encoding="utf-8",
    )

    updated_floor = release.sync_root_pg_dev_dependency(
        root_pyproject_path=root_pyproject_path,
        pg_pyproject_path=pg_pyproject_path,
    )

    assert updated_floor == "3.2.1"
    assert '"simplebroker-pg>=3.2.1",' in root_pyproject_path.read_text(
        encoding="utf-8"
    )


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


def test_release_sync_updates_all_first_party_dependency_directions(
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

    def sync_pg_to_root() -> str:
        calls.append("pg-to-root")
        return "0.6.0"

    def sync_pg_runtime_to_root_dev() -> str:
        calls.append("pg-runtime-to-root-dev")
        return "3.2.1"

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
    monkeypatch.setattr(release, "sync_pg_core_dependency", sync_pg_to_root)
    monkeypatch.setattr(
        release,
        "sync_root_pg_dev_dependency",
        sync_pg_runtime_to_root_dev,
    )

    release._sync_root_release_dependencies()  # noqa: SLF001

    assert calls == [
        "root-to-summon",
        "pg-runtime-to-root-dev",
        "pg-to-root",
        "summon-to-root",
    ]


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

    def fake_read_manifest_version(target: Any = release.ROOT_TARGET) -> str:
        assert target == release.ROOT_TARGET
        return "0.1.1"

    def fake_inspect_release_state(target: Any, version: str) -> Any:
        assert target == release.ROOT_TARGET
        assert version == "0.1.1"
        return _release_state(release, github_release_exists=True)

    monkeypatch.setattr(release, "read_manifest_version", fake_read_manifest_version)
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


def test_branch_push_names_the_tested_commit_explicitly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release = _load_release_module()
    commands: list[tuple[str, ...]] = []
    monkeypatch.setattr(
        release,
        "run_command",
        lambda command, **_kwargs: commands.append(command),
    )

    release.push_current_branch(
        dry_run=False,
        branch="main",
        head_commit="prepared",
    )

    assert commands == [("git", "push", "origin", "prepared:refs/heads/main")]


def test_remote_retag_is_leased_and_all_tag_commands_pin_tested_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release = _load_release_module()
    commands: list[tuple[str, ...]] = []
    state = _release_state(
        release,
        local_tag_commit="old",
        remote_tag_commit="old",
    )
    action = release.TagAction("replace_remote", state, "prepared")
    monkeypatch.setattr(
        release,
        "run_command",
        lambda command, **_kwargs: commands.append(command),
    )

    release.prepare_tag(action, dry_run=False)
    release.push_tag(action, dry_run=False)

    assert commands == [
        ("git", "tag", "-f", "v0.1.1", "prepared"),
        (
            "git",
            "push",
            "--force-with-lease=refs/tags/v0.1.1:old",
            "origin",
            ":refs/tags/v0.1.1",
        ),
        ("git", "push", "origin", "prepared:refs/tags/v0.1.1"),
    ]


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


def test_precheck_commands_select_dev_extra_and_include_typed_release_helper() -> None:
    release = _load_release_module()

    commands = release.build_precheck_commands()

    pytest_prefix = ("uv", "run", "--extra", "dev", "pytest")
    assert release.ROOT_BROAD_TEST_COMMAND == (
        *pytest_prefix,
        "-m",
        "not slow and not installed_wheel",
    )
    assert release.ROOT_INSTALLED_WHEEL_TEST_COMMAND == (
        *pytest_prefix,
        "-m",
        "not slow and installed_wheel",
        "-n",
        "0",
    )
    assert commands[:2] == (
        release.ROOT_BROAD_TEST_COMMAND,
        release.ROOT_INSTALLED_WHEEL_TEST_COMMAND,
    )
    for command in (
        *release.ROOT_TEST_COMMANDS,
        release.SUMMON_UNIT_TEST_COMMAND,
        release.SUMMON_PROCESS_TEST_COMMAND,
        release.SUMMON_LIVE_HARNESS_TEST_COMMAND,
        release.SUMMON_LOCAL_LLM_TEST_COMMAND,
    ):
        assert command[:5] == pytest_prefix
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
        "bin/release-artifact.py",
        "bin/require-green-workflows.py",
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
        "4",
        "--dist",
        "load",
    )
    for single_resource_command in (
        release.SUMMON_LIVE_HARNESS_TEST_COMMAND,
        release.SUMMON_LOCAL_LLM_TEST_COMMAND,
    ):
        assert single_resource_command[-4:] == (
            "-n",
            "1",
            "--dist",
            "loadgroup",
        )
    assert (
        "-m",
        "requires_live_harness",
    ) in tuple(
        zip(
            release.SUMMON_LIVE_HARNESS_TEST_COMMAND,
            release.SUMMON_LIVE_HARNESS_TEST_COMMAND[1:],
            strict=False,
        )
    )
    assert (
        "-m",
        "requires_local_llm",
    ) in tuple(
        zip(
            release.SUMMON_LOCAL_LLM_TEST_COMMAND,
            release.SUMMON_LOCAL_LLM_TEST_COMMAND[1:],
            strict=False,
        )
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


def test_summon_preparation_selectively_locks_before_artifact_builds() -> None:
    release = _load_release_module()

    preparation_steps = release.build_preparation_steps_for_targets(
        (release.SUMMON_TARGET,)
    )
    build_steps = release.build_postupdate_steps(release.SUMMON_TARGET)

    assert [step.command for step in preparation_steps] == [
        ("uv", "lock", "--upgrade-package", "simplebroker")
    ]
    assert preparation_steps[0].cwd == release.SUMMON_EXTENSION_DIR
    assert build_steps[0].command == ("uv", "build", "extensions/taut_summon")
    assert build_steps[1].command == (
        sys.executable,
        str(release.RELEASE_WHEEL_SET_CHECKER),
    )


def test_pg_preparation_refreshes_retained_summon_lock() -> None:
    release = _load_release_module()

    steps = release.build_preparation_steps_for_targets((release.PG_TARGET,))

    assert [step.command for step in steps] == [
        ("uv", "lock", "--upgrade-package", "simplebroker")
    ]
    assert steps[0].cwd == release.SUMMON_EXTENSION_DIR


def test_core_postupdate_checks_fresh_paired_release_wheels_after_build() -> None:
    release = _load_release_module()

    steps = release.build_postupdate_steps(release.ROOT_TARGET)

    assert [step.command for step in steps] == [
        ("uv", "build"),
        (
            sys.executable,
            str(release.RELEASE_WHEEL_SET_CHECKER),
        ),
    ]


def test_core_dry_run_executes_preparation_then_artifact_plan(
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
        if command[:2] == ("uv", "lock"):
            assert cwd == release.SUMMON_EXTENSION_DIR
        else:
            assert cwd == release.PROJECT_ROOT
        calls.append((command, dry_run))

    monkeypatch.setattr(release, "run_command", fake_run_command)

    release.run_preparation_steps((release.ROOT_TARGET,), dry_run=True)
    release.run_postupdate_steps(release.ROOT_TARGET, dry_run=True)

    assert calls == [
        (("uv", "lock", "--upgrade-package", "simplebroker"), True),
        (("uv", "build"), True),
        (
            (
                sys.executable,
                str(release.RELEASE_WHEEL_SET_CHECKER),
                "--dry-run",
            ),
            False,
        ),
    ]


def test_pg_postupdate_skips_paired_release_wheel_check() -> None:
    release = _load_release_module()

    steps = release.build_postupdate_steps(release.PG_TARGET)

    assert [step.command for step in steps] == [("uv", "build", "extensions/taut_pg")]


def test_matching_batch_checks_once_after_all_normal_builds() -> None:
    release = _load_release_module()

    steps = release.build_postupdate_steps_for_targets(
        (release.PG_TARGET, release.SUMMON_TARGET, release.ROOT_TARGET)
    )

    assert [step.command for step in steps] == [
        ("uv", "build"),
        ("uv", "build", "extensions/taut_pg"),
        ("uv", "build", "extensions/taut_summon"),
        (sys.executable, str(release.RELEASE_WHEEL_SET_CHECKER)),
    ]


def test_release_wheel_failure_leaves_preparation_commit_and_stops_remote_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release = _load_release_module()
    state = _release_state(release)
    commands: list[tuple[str, ...]] = []
    head = "initial"

    monkeypatch.setattr(release, "is_dirty_worktree", lambda: False)
    monkeypatch.setattr(
        release,
        "resolve_target_version",
        lambda _version, _target: ("0.1.1", "0.1.1", state),
    )

    def fake_current_head_commit() -> str:
        return head

    monkeypatch.setattr(release, "current_head_commit", fake_current_head_commit)
    monkeypatch.setattr(release, "current_branch", lambda: "main")
    monkeypatch.setattr(release, "_require_command", lambda _name: None)
    monkeypatch.setattr(release, "require_changelog_heading", lambda _version: None)
    monkeypatch.setattr(release, "write_version_files", lambda *_args: None)
    monkeypatch.setattr(release, "read_manifest_version", lambda _target: "0.1.1")
    monkeypatch.setattr(release, "read_current_version", lambda _target: "0.1.1")
    monkeypatch.setattr(release, "_sync_root_release_dependencies", lambda: None)
    monkeypatch.setattr(
        release, "sync_readme_simplebroker_requirement", lambda: "5.3.2"
    )
    monkeypatch.setattr(
        release,
        "run_prechecks",
        lambda *_args, **_kwargs: pytest.fail("--skip-checks must skip prechecks"),
    )
    monkeypatch.setattr(
        release, "release_files_changed_for_targets", lambda _targets: True
    )
    monkeypatch.setattr(
        release,
        "prepare_tag",
        lambda *_args, **_kwargs: pytest.fail("wheel check must precede tags"),
    )
    monkeypatch.setattr(
        release,
        "push_current_branch",
        lambda **_kwargs: pytest.fail("wheel check must precede pushes"),
    )

    def fake_run_command(
        command: tuple[str, ...],
        **_kwargs: object,
    ) -> None:
        nonlocal head
        commands.append(command)
        if command[:2] == ("git", "commit"):
            head = "prepared"
        if command == (
            sys.executable,
            str(release.RELEASE_WHEEL_SET_CHECKER),
        ):
            raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(release, "run_command", fake_run_command)

    with pytest.raises(subprocess.CalledProcessError):
        release.main(["core", "--skip-checks"])

    assert commands == [
        ("uv", "lock", "--upgrade-package", "simplebroker"),
        (
            "git",
            "add",
            *release._release_file_args(release.ROOT_TARGET),  # noqa: SLF001
        ),
        ("git", "commit", "-m", "Release taut 0.1.1"),
        ("uv", "build"),
        (sys.executable, str(release.RELEASE_WHEEL_SET_CHECKER)),
    ]


def test_metadata_writer_failure_runs_no_commit_or_remote_action(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release = _load_release_module()
    state = _release_state(release)
    monkeypatch.setattr(release, "is_dirty_worktree", lambda: False)
    monkeypatch.setattr(
        release,
        "resolve_target_version",
        lambda _version, _target: ("0.1.1", "0.1.1", state),
    )
    monkeypatch.setattr(release, "current_branch", lambda: "main")
    monkeypatch.setattr(release, "current_head_commit", lambda: "initial")
    monkeypatch.setattr(release, "_require_command", lambda _name: None)
    monkeypatch.setattr(release, "require_changelog_heading", lambda _version: None)

    def fail_writer(*_args: object) -> None:
        raise SystemExit("writer failed")

    monkeypatch.setattr(
        release,
        "prepare_release_metadata",
        fail_writer,
    )
    monkeypatch.setattr(
        release,
        "run_command",
        lambda *_args, **_kwargs: pytest.fail("writer failure must stop commands"),
    )
    monkeypatch.setattr(
        release,
        "prepare_tag",
        lambda *_args, **_kwargs: pytest.fail("writer failure must stop tags"),
    )

    with pytest.raises(SystemExit, match="writer failed"):
        release.main(["core"])


def test_version_changed_core_prepares_and_commits_before_prechecks_and_builds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release = _load_release_module()
    state = _release_state(release)
    events: list[str] = []
    head = "initial"

    monkeypatch.setattr(release, "is_dirty_worktree", lambda: False)
    monkeypatch.setattr(
        release,
        "resolve_target_version",
        lambda _version, _target: ("0.5.1", "0.6.0", state),
    )

    def fake_current_head_commit() -> str:
        return head

    monkeypatch.setattr(release, "current_head_commit", fake_current_head_commit)
    monkeypatch.setattr(release, "current_branch", lambda: "main")
    monkeypatch.setattr(release, "_require_command", lambda _name: None)
    monkeypatch.setattr(release, "require_changelog_heading", lambda _version: None)
    prepared_versions = {
        release.ROOT_TARGET: "0.6.0",
        release.PG_TARGET: "0.5.9",
        release.SUMMON_TARGET: "0.5.8",
    }
    monkeypatch.setattr(
        release,
        "read_manifest_version",
        lambda target: prepared_versions[target],
    )
    monkeypatch.setattr(
        release,
        "write_version_files",
        lambda version, target: events.append(f"write:{target.key}:{version}"),
    )
    monkeypatch.setattr(
        release,
        "read_current_version",
        lambda target: prepared_versions[target],
    )
    monkeypatch.setattr(
        release,
        "_sync_root_release_dependencies",
        lambda: events.append("sync-paired-floors"),
    )

    def sync_simplebroker_readme() -> str:
        events.append("sync-simplebroker-readme")
        return "5.3.2"

    monkeypatch.setattr(
        release,
        "sync_readme_simplebroker_requirement",
        sync_simplebroker_readme,
    )
    monkeypatch.setattr(
        release, "release_files_changed_for_targets", lambda _targets: True
    )
    monkeypatch.setattr(
        release,
        "run_prechecks",
        lambda *_args, **_kwargs: events.append("prechecks"),
    )
    monkeypatch.setattr(
        release,
        "inspect_release_state",
        lambda target, version: state,
    )
    monkeypatch.setattr(
        release,
        "prepare_tag",
        lambda *_args, **_kwargs: events.append("tag"),
    )
    monkeypatch.setattr(
        release,
        "push_current_branch",
        lambda **_kwargs: events.append("push-branch"),
    )
    monkeypatch.setattr(
        release,
        "push_tag",
        lambda *_args, **_kwargs: events.append("push-tag"),
    )

    def fake_run_command(command: tuple[str, ...], **_kwargs: object) -> None:
        nonlocal head
        if command[:2] == ("git", "add"):
            events.append("git-add")
            return
        if command[:2] == ("git", "commit"):
            events.append("git-commit")
            head = "prepared"
            return
        if command == (sys.executable, str(release.RELEASE_WHEEL_SET_CHECKER)):
            events.append("check-release-wheels")
            return
        events.append(":".join(command))

    monkeypatch.setattr(release, "run_command", fake_run_command)

    assert release.main(["core", "--version", "0.6.0"]) == 0

    assert events == [
        "write:core:0.6.0",
        "write:pg:0.5.9",
        "write:summon:0.5.8",
        "sync-paired-floors",
        "sync-simplebroker-readme",
        "uv:lock:--upgrade-package:simplebroker",
        "git-add",
        "git-commit",
        "prechecks",
        "uv:build",
        "check-release-wheels",
        "tag",
        "push-branch",
        "push-tag",
    ]


def test_explicit_batch_version_prepares_all_manifests_but_skips_published_actions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release = _load_release_module()
    manifest_versions = {
        release.PG_TARGET: "0.5.9",
        release.SUMMON_TARGET: "0.5.8",
        release.ROOT_TARGET: "0.5.7",
    }
    writes: list[tuple[str, str]] = []
    inspected_targets: list[str] = []
    preparation_targets: list[tuple[str, ...]] = []
    build_targets: list[tuple[str, ...]] = []
    prepared_tags: list[str] = []
    pushed_tags: list[str] = []
    branch_pushes: list[tuple[str | None, str | None]] = []

    monkeypatch.setattr(
        release, "read_manifest_version", lambda target: manifest_versions[target]
    )

    def inspect_release_state(target: Any, version: str) -> Any:
        inspected_targets.append(target.key)
        return release.ReleaseState(
            target=target,
            version=version,
            tag_name=target.tag_for_version(version),
            github_release_exists=target == release.PG_TARGET,
            local_tag_commit=None,
            remote_tag_commit=None,
        )

    monkeypatch.setattr(release, "inspect_release_state", inspect_release_state)
    monkeypatch.setattr(release, "is_dirty_worktree", lambda: False)
    monkeypatch.setattr(release, "current_branch", lambda: "main")
    monkeypatch.setattr(release, "current_head_commit", lambda: "prepared")
    monkeypatch.setattr(release, "_require_command", lambda _name: None)
    monkeypatch.setattr(release, "require_changelog_heading", lambda _version: None)

    def write_version_files(version: str, target: Any) -> None:
        writes.append((target.key, version))
        manifest_versions[target] = version

    monkeypatch.setattr(release, "write_version_files", write_version_files)
    monkeypatch.setattr(
        release, "read_current_version", lambda target: manifest_versions[target]
    )
    monkeypatch.setattr(release, "_sync_root_release_dependencies", lambda: None)
    monkeypatch.setattr(
        release, "sync_readme_simplebroker_requirement", lambda: "5.3.2"
    )

    def run_preparation_steps(targets: tuple[Any, ...], *, dry_run: bool) -> None:
        assert not dry_run
        preparation_targets.append(tuple(target.key for target in targets))

    monkeypatch.setattr(release, "run_preparation_steps", run_preparation_steps)

    def commit_release_preparation(
        targets: tuple[Any, ...], *, message: str
    ) -> tuple[bool, str]:
        preparation_targets.append(tuple(target.key for target in targets))
        assert message == "Release taut-summon 0.6.0, taut 0.6.0"
        return True, "prepared"

    monkeypatch.setattr(
        release, "commit_release_preparation", commit_release_preparation
    )

    def build_postupdate_steps_for_targets(
        targets: tuple[Any, ...],
    ) -> tuple[Any, ...]:
        build_targets.append(tuple(target.key for target in targets))
        return ()

    monkeypatch.setattr(
        release,
        "build_postupdate_steps_for_targets",
        build_postupdate_steps_for_targets,
    )
    monkeypatch.setattr(
        release,
        "prepare_tag",
        lambda action, *, dry_run: prepared_tags.append(action.state.target.key),
    )
    monkeypatch.setattr(
        release,
        "push_current_branch",
        lambda *, dry_run, branch=None, head_commit=None: branch_pushes.append(
            (branch, head_commit)
        ),
    )
    monkeypatch.setattr(
        release,
        "push_tag",
        lambda action, *, dry_run: pushed_tags.append(action.state.target.key),
    )

    assert release.main(["all", "--version", "0.6.0", "--skip-checks"]) == 0

    assert writes == [
        ("core", "0.6.0"),
        ("pg", "0.6.0"),
        ("summon", "0.6.0"),
    ]
    assert preparation_targets == [
        ("pg", "summon", "core"),
        ("pg", "summon", "core"),
    ]
    assert build_targets == [("summon", "core")]
    assert inspected_targets.count("pg") == 1
    assert inspected_targets.count("summon") == 2
    assert inspected_targets.count("core") == 2
    assert prepared_tags == ["summon", "core"]
    assert pushed_tags == ["summon", "core"]
    assert branch_pushes == [("main", "prepared")]


def test_explicit_batch_version_rejects_backdating_before_remote_inspection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release = _load_release_module()
    versions = {
        release.PG_TARGET: "0.6.0",
        release.SUMMON_TARGET: "0.6.1",
        release.ROOT_TARGET: "0.6.0",
    }
    monkeypatch.setattr(
        release, "read_manifest_version", lambda target: versions[target]
    )
    monkeypatch.setattr(
        release,
        "inspect_release_state",
        lambda *_args: pytest.fail("backdating must fail before remote inspection"),
    )

    with pytest.raises(SystemExit, match="Refusing to backdate"):
        release.discover_unpublished_releases(requested_version="0.6.0")


def test_all_published_explicit_batch_is_a_non_mutating_noop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release = _load_release_module()
    monkeypatch.setattr(release, "is_dirty_worktree", lambda: False)
    monkeypatch.setattr(release, "read_manifest_version", lambda _target: "0.6.0")
    monkeypatch.setattr(
        release,
        "inspect_release_state",
        lambda target, version: release.ReleaseState(
            target=target,
            version=version,
            tag_name=target.tag_for_version(version),
            github_release_exists=True,
            local_tag_commit="published",
            remote_tag_commit="published",
        ),
    )
    monkeypatch.setattr(
        release,
        "prepare_release_metadata",
        lambda *_args: pytest.fail("all-published batch must not write"),
    )
    monkeypatch.setattr(
        release,
        "run_command",
        lambda *_args, **_kwargs: pytest.fail("all-published batch must not run"),
    )

    assert release.main(["all", "--version", "0.6.0"]) == 0


def test_clean_rerun_reuses_preparation_commit_without_duplicate_commit(
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
    monkeypatch.setattr(release, "current_branch", lambda: "main")
    monkeypatch.setattr(release, "current_head_commit", lambda: "prepared")
    monkeypatch.setattr(release, "_require_command", lambda _name: None)
    monkeypatch.setattr(release, "require_changelog_heading", lambda _version: None)
    monkeypatch.setattr(release, "write_version_files", lambda *_args: None)
    monkeypatch.setattr(release, "read_manifest_version", lambda _target: "0.1.1")
    monkeypatch.setattr(release, "read_current_version", lambda _target: "0.1.1")
    monkeypatch.setattr(release, "_sync_root_release_dependencies", lambda: None)
    monkeypatch.setattr(
        release, "sync_readme_simplebroker_requirement", lambda: "5.3.2"
    )
    monkeypatch.setattr(
        release, "release_files_changed_for_targets", lambda _targets: False
    )
    monkeypatch.setattr(release, "run_prechecks", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        release, "inspect_release_state", lambda _target, _version: state
    )
    monkeypatch.setattr(release, "prepare_tag", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(release, "push_current_branch", lambda **_kwargs: None)
    monkeypatch.setattr(release, "push_tag", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        release,
        "run_command",
        lambda command, **_kwargs: commands.append(command),
    )

    assert release.main(["core"]) == 0
    assert all(
        command[:2] not in {("git", "add"), ("git", "commit")} for command in commands
    )
    assert commands == [
        ("uv", "lock", "--upgrade-package", "simplebroker"),
        ("uv", "build"),
        (sys.executable, str(release.RELEASE_WHEEL_SET_CHECKER)),
    ]


def test_release_fence_rejects_published_state_after_checks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release = _load_release_module()
    candidate = release.ReleaseCandidate(
        target=release.ROOT_TARGET,
        current_version="0.6.0",
        release_version="0.6.1",
        state=_release_state(release),
    )
    monkeypatch.setattr(release, "current_branch", lambda: "main")
    monkeypatch.setattr(release, "current_head_commit", lambda: "prepared")
    monkeypatch.setattr(release, "is_dirty_worktree", lambda: False)
    monkeypatch.setattr(
        release,
        "inspect_release_state",
        lambda target, version: release.ReleaseState(
            target=target,
            version=version,
            tag_name=target.tag_for_version(version),
            github_release_exists=True,
            local_tag_commit="prepared",
            remote_tag_commit="prepared",
        ),
    )

    with pytest.raises(SystemExit, match="became a GitHub Release"):
        release.require_fresh_release_fence(
            (candidate,),
            preparation_branch="main",
            preparation_commit="prepared",
        )


@pytest.mark.parametrize(
    ("branch", "head", "dirty", "message"),
    [
        ("other", "prepared", False, "Release branch changed"),
        ("main", "other", False, "Release HEAD changed"),
        ("main", "prepared", True, "Worktree or index changed"),
    ],
)
def test_release_fence_rejects_local_checkout_drift(
    monkeypatch: pytest.MonkeyPatch,
    branch: str,
    head: str,
    dirty: bool,
    message: str,
) -> None:
    release = _load_release_module()
    monkeypatch.setattr(release, "current_branch", lambda: branch)
    monkeypatch.setattr(release, "current_head_commit", lambda: head)
    monkeypatch.setattr(release, "is_dirty_worktree", lambda: dirty)

    with pytest.raises(SystemExit, match=message):
        release.require_fresh_release_fence(
            (),
            preparation_branch="main",
            preparation_commit="prepared",
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

    monkeypatch.setattr(release, "read_manifest_version", fake_read_target_version)
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

    assert set(paths) == {
        release.PYPROJECT_PATH,
        release.CONSTANTS_PATH,
        release.ROOT_README_PATH,
        release.PG_PYPROJECT_PATH,
        release.PG_README_PATH,
        release.SUMMON_PYPROJECT_PATH,
        release.SUMMON_README_PATH,
        release.SUMMON_UV_LOCK_PATH,
    }
    assert len(paths) == len(set(paths))


def test_core_release_tracks_paired_summon_floor_and_retained_lock() -> None:
    release = _load_release_module()

    paths = release._release_file_paths(release.ROOT_TARGET)  # noqa: SLF001

    assert release.SUMMON_PYPROJECT_PATH in paths
    assert release.SUMMON_UV_LOCK_PATH in paths


def test_summon_release_tracks_root_dev_floor() -> None:
    release = _load_release_module()

    paths = release._release_file_paths(release.SUMMON_TARGET)  # noqa: SLF001

    assert release.PYPROJECT_PATH in paths


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

    def fake_read_manifest_version(target: Any = release.ROOT_TARGET) -> str:
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

    monkeypatch.setattr(release, "read_manifest_version", fake_read_manifest_version)
    monkeypatch.setattr(release, "inspect_release_state", fake_inspect_release_state)
    monkeypatch.setattr(release, "is_dirty_worktree", fake_is_dirty_worktree)
    monkeypatch.setattr(release, "current_head_commit", fake_current_head_commit)

    release.main(["--dry-run", "--skip-checks", "--publish"])

    output = capsys.readouterr().out
    assert "--publish is ignored" in output
    assert "GitHub-only" in output
    assert "v0.1.1" in output


def test_dry_run_treats_same_version_derived_drift_as_a_pending_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release = _load_release_module()
    commands: list[tuple[str, ...]] = []
    state = _release_state(release, remote_tag_commit="current")
    monkeypatch.setattr(release, "is_dirty_worktree", lambda: False)
    monkeypatch.setattr(release, "read_manifest_version", lambda _target: "0.1.1")
    monkeypatch.setattr(
        release, "inspect_release_state", lambda _target, _version: state
    )
    monkeypatch.setattr(release, "current_head_commit", lambda: "current")
    monkeypatch.setattr(
        release,
        "capture_command",
        lambda command: (
            "main"
            if command == ("git", "rev-parse", "--abbrev-ref", "HEAD")
            else pytest.fail(f"unexpected capture command: {command}")
        ),
    )
    monkeypatch.setattr(
        release,
        "run_command",
        lambda command, **_kwargs: commands.append(command),
    )

    assert release.main(["core", "--dry-run", "--skip-checks", "--retag"]) == 0

    assert (
        "git",
        "push",
        "--force-with-lease=refs/tags/v0.1.1:current",
        "origin",
        ":refs/tags/v0.1.1",
    ) in commands
    assert (
        "git",
        "push",
        "origin",
        f"{release.PENDING_RELEASE_COMMIT}:refs/tags/v0.1.1",
    ) in commands


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


def test_checks_only_runs_real_prechecks_then_exits_before_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release = _load_release_module()
    events: list[str] = []

    monkeypatch.setattr(release, "is_dirty_worktree", lambda: True)
    monkeypatch.setattr(
        release,
        "read_target_version",
        lambda target: "0.5.3",
    )
    monkeypatch.setattr(
        release,
        "require_changelog_heading",
        lambda version: events.append(f"changelog:{version}"),
    )
    monkeypatch.setattr(release, "_require_command", lambda name: events.append(name))
    monkeypatch.setattr(
        release,
        "run_prechecks",
        lambda target, *, dry_run: events.append(f"prechecks:{target.key}:{dry_run}"),
    )
    monkeypatch.setattr(
        release,
        "current_head_commit",
        lambda: pytest.fail("checks-only must not plan tags"),
    )
    monkeypatch.setattr(
        release,
        "write_version_files",
        lambda *_args: pytest.fail("checks-only must not write versions"),
    )
    monkeypatch.setattr(
        release,
        "run_postupdate_steps",
        lambda *_args, **_kwargs: pytest.fail("checks-only must not build artifacts"),
    )

    assert release.main(["core", "--checks-only"]) == 0
    assert events == ["changelog:0.5.3", "uv", "prechecks:core:False"]


def test_checks_only_rejects_dry_run_and_skip_checks() -> None:
    release = _load_release_module()

    with pytest.raises(SystemExit):
        release.parse_args(["--checks-only", "--dry-run"])
    with pytest.raises(SystemExit):
        release.parse_args(["--checks-only", "--skip-checks"])


@pytest.mark.parametrize("target", ("all", "core", "pg", "summon"))
@pytest.mark.parametrize("branch", ("topic/ci-work", "HEAD"))
def test_publishing_targets_reject_noncanonical_branch_before_mutation(
    target: str,
    branch: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release = _load_release_module()
    monkeypatch.setattr(release, "current_branch", lambda: branch)
    monkeypatch.setattr(
        release,
        "prepare_release_metadata",
        lambda *_args: pytest.fail("branch guard must precede metadata mutation"),
    )
    monkeypatch.setattr(
        release,
        "run_preparation_steps",
        lambda *_args, **_kwargs: pytest.fail(
            "branch guard must precede preparation commands"
        ),
    )

    with pytest.raises(SystemExit, match="main or master"):
        release.main([target])


@pytest.mark.parametrize("branch", ("main", "master"))
def test_publish_branch_guard_allows_canonical_branches(
    branch: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release = _load_release_module()
    monkeypatch.setattr(release, "current_branch", lambda: branch)

    assert release.require_publish_branch() == branch
