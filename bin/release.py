#!/usr/bin/env python3
"""Repo-local GitHub-only release helper governed by [TAUT-12.5]."""

from __future__ import annotations

import argparse
import http.client
import json
import os
import re
import shlex
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, replace
from functools import lru_cache
from pathlib import Path
from typing import Final, Literal, NoReturn

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[1]
PYPROJECT_PATH: Final[Path] = PROJECT_ROOT / "pyproject.toml"
CONSTANTS_PATH: Final[Path] = PROJECT_ROOT / "taut" / "_constants.py"
CHANGELOG_PATH: Final[Path] = PROJECT_ROOT / "CHANGELOG.md"
ROOT_README_PATH: Final[Path] = PROJECT_ROOT / "README.md"
PG_EXTENSION_DIR: Final[Path] = PROJECT_ROOT / "extensions" / "taut_pg"
PG_PYPROJECT_PATH: Final[Path] = PG_EXTENSION_DIR / "pyproject.toml"
PG_README_PATH: Final[Path] = PG_EXTENSION_DIR / "README.md"
SUMMON_EXTENSION_DIR: Final[Path] = PROJECT_ROOT / "extensions" / "taut_summon"
SUMMON_PYPROJECT_PATH: Final[Path] = SUMMON_EXTENSION_DIR / "pyproject.toml"
SUMMON_README_PATH: Final[Path] = SUMMON_EXTENSION_DIR / "README.md"
SUMMON_UV_LOCK_PATH: Final[Path] = SUMMON_EXTENSION_DIR / "uv.lock"
RELEASE_WHEEL_SET_CHECKER: Final[Path] = (
    PROJECT_ROOT / "bin" / "build-and-check-release-wheels.py"
)

ROOT_RELEASE_WORKFLOW: Final[str] = ".github/workflows/release-gate.yml"
PG_RELEASE_WORKFLOW: Final[str] = ".github/workflows/release-gate-pg.yml"
SUMMON_RELEASE_WORKFLOW: Final[str] = ".github/workflows/release-gate-summon.yml"
GITHUB_API_BASE: Final[str] = "https://api.github.com"
HTTP_TIMEOUT_SECONDS: Final[float] = 15.0
PENDING_RELEASE_COMMIT: Final[str] = "<pending release commit>"
ALL_RELEASE_TARGET_KEY: Final[str] = "all"

Command = tuple[str, ...]
TagActionName = Literal[
    "create",
    "replace_local",
    "replace_remote",
    "reuse_remote",
    "push_local",
]

SEMVER_PATTERN: Final[re.Pattern[str]] = re.compile(r"\d+\.\d+\.\d+")
PYPROJECT_VERSION_PATTERN: Final[re.Pattern[str]] = re.compile(
    r'(?m)^version = "([^"]+)"$'
)
CONSTANTS_VERSION_PATTERN: Final[re.Pattern[str]] = re.compile(
    r'(?m)^__version__(?::[^=]+)? = "([^"]+)"$'
)
TAUT_DEPENDENCY_PATTERN: Final[re.Pattern[str]] = re.compile(
    r'(?m)^(\s*"taut>=)[^"]+(",\s*)$'
)
TAUT_SUMMON_DEPENDENCY_PATTERN: Final[re.Pattern[str]] = re.compile(
    r'(?m)^(\s*"taut-summon>=)([^"]+)(",\s*)$'
)
SIMPLEBROKER_DEPENDENCY_PATTERN: Final[re.Pattern[str]] = re.compile(
    r'(?m)^\s*"simplebroker>=(\d+\.\d+\.\d+)",\s*$'
)
SIMPLEBROKER_PG_DEPENDENCY_PATTERN: Final[re.Pattern[str]] = re.compile(
    r'(?m)^(\s*"simplebroker-pg>=)([^"]+)(",\s*)$'
)
README_SIMPLEBROKER_DEPENDENCY_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"simplebroker>=\d+\.\d+\.\d+"
)
CORE_README_TAG_PATTERN: Final[re.Pattern[str]] = re.compile(r"@v\d+\.\d+\.\d+")
PG_WHEEL_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"taut_pg-\d+\.\d+\.\d+-py3-none-any\.whl"
)
SUMMON_WHEEL_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"taut_summon-\d+\.\d+\.\d+-py3-none-any\.whl"
)

PYTEST_PREFIX: Final[Command] = ("uv", "run", "--extra", "dev", "pytest")
ROOT_BROAD_TEST_COMMAND: Final[Command] = (
    *PYTEST_PREFIX,
    "-m",
    "not slow and not installed_wheel",
)
ROOT_INSTALLED_WHEEL_TEST_COMMAND: Final[Command] = (
    *PYTEST_PREFIX,
    "-m",
    "not slow and installed_wheel",
    "-n",
    "0",
)
ROOT_TEST_COMMANDS: Final[tuple[Command, ...]] = (
    ROOT_BROAD_TEST_COMMAND,
    ROOT_INSTALLED_WHEEL_TEST_COMMAND,
)
PUBLISH_BRANCHES: Final[frozenset[str]] = frozenset({"main", "master"})
PG_TEST_COMMAND: Final[Command] = ("uv", "run", "./bin/pytest-pg", "--fast")
SUMMON_UNIT_TEST_COMMAND: Final[Command] = (
    *PYTEST_PREFIX,
    "extensions/taut_summon/tests",
    "-m",
    "not xdist_group",
)
SUMMON_PROCESS_TEST_COMMAND: Final[Command] = (
    *PYTEST_PREFIX,
    "extensions/taut_summon/tests",
    "-m",
    "xdist_group and not requires_live_harness and not requires_local_llm",
    "-n",
    "4",
    "--dist",
    "load",
)
SUMMON_LIVE_HARNESS_TEST_COMMAND: Final[Command] = (
    *PYTEST_PREFIX,
    "extensions/taut_summon/tests/test_live_harness.py",
    "-m",
    "requires_live_harness",
    "-n",
    "1",
    "--dist",
    "loadgroup",
)
SUMMON_LOCAL_LLM_TEST_COMMAND: Final[Command] = (
    *PYTEST_PREFIX,
    "extensions/taut_summon/tests/test_live_local_llm.py",
    "-m",
    "requires_local_llm",
    "-n",
    "1",
    "--dist",
    "loadgroup",
)
SUMMON_TEST_COMMANDS: Final[tuple[Command, ...]] = (
    SUMMON_UNIT_TEST_COMMAND,
    SUMMON_PROCESS_TEST_COMMAND,
    SUMMON_LIVE_HARNESS_TEST_COMMAND,
    SUMMON_LOCAL_LLM_TEST_COMMAND,
)
RUFF_CHECK_PREFIX: Final[Command] = ("uv", "run", "--extra", "dev", "ruff", "check")
RUFF_FORMAT_PREFIX: Final[Command] = (
    "uv",
    "run",
    "--extra",
    "dev",
    "ruff",
    "format",
    "--check",
)
MYPY_PREFIX: Final[Command] = ("uv", "run", "--extra", "dev", "mypy")
MYPY_SUFFIX: Final[Command] = ("--config-file", "pyproject.toml")
ROOT_TOOL_PATHS: Final[Command] = ("taut", "tests", "bin")
PG_TOOL_PATHS: Final[Command] = (
    "extensions/taut_pg/taut_pg",
    "extensions/taut_pg/tests",
    "bin/pytest-pg",
)
SUMMON_TOOL_PATHS: Final[Command] = (
    "extensions/taut_summon/taut_summon",
    "extensions/taut_summon/tests",
)
ROOT_MYPY_PATHS: Final[Command] = (
    "taut",
    "tests",
    "bin/release.py",
    "bin/release-artifact.py",
    "bin/require-green-workflows.py",
)
# The trailing explicit ``tests/conftest.py`` re-includes the conftest that
# ``[tool.mypy] exclude`` drops from directory discovery (see pyproject): the
# gate still type-checks it, while ad-hoc combined runs avoid the duplicate
# ``conftest`` module clash under ``no_namespace_packages``.
PG_MYPY_PATHS: Final[Command] = (
    "taut/_scripts.py",
    "extensions/taut_pg/taut_pg",
    "extensions/taut_pg/tests",
    "extensions/taut_pg/tests/conftest.py",
)
SUMMON_MYPY_PATHS: Final[Command] = (
    "extensions/taut_summon/taut_summon",
    "extensions/taut_summon/tests",
    "extensions/taut_summon/tests/conftest.py",
)
PRECHECK_ENV_OVERRIDES: Final[dict[str, str]] = {"PYTEST_ADDOPTS": "-x --maxfail=1"}
LOCAL_LLM_DEFAULT_ENDPOINT: Final[str] = "http://127.0.0.1:11434/v1"
LOCAL_LLM_DEFAULT_MODEL: Final[str] = "taut-summon-local-model:latest"
LOCAL_LLM_DEFAULT_BASE_MODEL: Final[str] = "qwen2.5:0.5b"
LOCAL_LLM_DEFAULT_CONTEXT_LENGTH: Final[str] = "2048"
LOCAL_LLM_DEFAULT_NUM_PREDICT: Final[str] = "64"
LOCAL_LLM_DEFAULT_IMAGE: Final[str] = (
    "ollama/ollama@"
    "sha256:f1a705f2bd113fb8d15f85f7c217f0dc5f6bebda6b0cc42b82c3ad165ffcb9dc"
)
LOCAL_LLM_HTTP_TIMEOUT_SECONDS: Final[float] = 10.0
LOCAL_LLM_SERVER_WAIT_SECONDS: Final[float] = 180.0
LOCAL_LLM_MODEL_WAIT_SECONDS: Final[float] = 180.0
LOCAL_LLM_SETUP_COMMAND_TIMEOUT_SECONDS: Final[float] = 900.0
LOCAL_LLM_RETRYABLE_HTTP_ERRORS: Final[tuple[type[BaseException], ...]] = (
    urllib.error.URLError,
    urllib.error.HTTPError,
    TimeoutError,
    http.client.RemoteDisconnected,
)


@dataclass(frozen=True)
class ReleaseTarget:
    """Release metadata for one publishable package in this repository."""

    name: str
    package_name: str
    package_dir: Path
    pyproject_path: Path
    constants_path: Path | None
    tag_namespace: str | None
    github_release: bool
    pypi_publish: bool
    release_workflow: str = ""

    @property
    def key(self) -> str:
        return self.name

    @property
    def display_name(self) -> str:
        return self.package_name

    @property
    def github_release_enabled(self) -> bool:
        return self.github_release

    def tag_for_version(self, version: str) -> str:
        if self.tag_namespace is not None:
            return f"{self.tag_namespace}/v{version}"
        return f"v{version}"

    def tag_name(self, version: str) -> str:
        return self.tag_for_version(version)


@dataclass(frozen=True)
class ReleaseState:
    """Observed GitHub publication and tag state for one package version."""

    target: ReleaseTarget
    version: str
    tag_name: str
    github_release_exists: bool
    local_tag_commit: str | None
    remote_tag_commit: str | None

    @property
    def published(self) -> bool:
        return self.github_release_exists


@dataclass(frozen=True)
class ReleaseCandidate:
    """One package version selected for a batch release."""

    target: ReleaseTarget
    current_version: str
    release_version: str
    state: ReleaseState


@dataclass(frozen=True)
class TagAction:
    action: TagActionName
    state: ReleaseState
    head_commit: str


@dataclass(frozen=True)
class CommandStep:
    command: Command
    description: str
    cwd: Path = PROJECT_ROOT


ROOT_TARGET: Final[ReleaseTarget] = ReleaseTarget(
    name="core",
    package_name="taut",
    package_dir=Path("."),
    pyproject_path=PYPROJECT_PATH,
    constants_path=CONSTANTS_PATH,
    tag_namespace=None,
    github_release=True,
    pypi_publish=False,
    release_workflow=ROOT_RELEASE_WORKFLOW,
)
PG_TARGET: Final[ReleaseTarget] = ReleaseTarget(
    name="pg",
    package_name="taut-pg",
    package_dir=Path("extensions/taut_pg"),
    pyproject_path=PG_PYPROJECT_PATH,
    constants_path=None,
    tag_namespace="taut_pg",
    github_release=True,
    pypi_publish=False,
    release_workflow=PG_RELEASE_WORKFLOW,
)
SUMMON_TARGET: Final[ReleaseTarget] = ReleaseTarget(
    name="summon",
    package_name="taut-summon",
    package_dir=Path("extensions/taut_summon"),
    pyproject_path=SUMMON_PYPROJECT_PATH,
    constants_path=None,
    tag_namespace="taut_summon",
    github_release=True,
    pypi_publish=False,
    release_workflow=SUMMON_RELEASE_WORKFLOW,
)
TARGETS: Final[dict[str, ReleaseTarget]] = {
    "core": ROOT_TARGET,
    "root": ROOT_TARGET,
    "taut": ROOT_TARGET,
    "pg": PG_TARGET,
    "summon": SUMMON_TARGET,
}
CANONICAL_TARGETS: Final[dict[str, ReleaseTarget]] = {
    "core": ROOT_TARGET,
    "pg": PG_TARGET,
    "summon": SUMMON_TARGET,
}
BATCH_RELEASE_TARGETS: Final[tuple[ReleaseTarget, ...]] = (
    PG_TARGET,
    SUMMON_TARGET,
    ROOT_TARGET,
)


def fail(message: str) -> NoReturn:
    raise SystemExit(message)


def display_path(path: Path) -> str:
    try:
        return path.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def validate_version(version: str) -> str:
    normalized = version.strip()
    if SEMVER_PATTERN.fullmatch(normalized) is None:
        fail(f"Invalid version {version!r}; expected X.Y.Z")
    return normalized


def _version_key(version: str) -> tuple[int, int, int]:
    normalized = validate_version(version)
    major, minor, patch = normalized.split(".")
    return int(major), int(minor), int(patch)


def require_not_backdated(current_version: str, target_version: str) -> None:
    if _version_key(target_version) < _version_key(current_version):
        fail(
            f"Refusing to backdate package version {current_version} to "
            f"{target_version}"
        )


def require_changelog_heading(
    version: str,
    *,
    changelog_path: Path = CHANGELOG_PATH,
) -> None:
    normalized = validate_version(version)
    heading = re.compile(rf"(?m)^## {re.escape(normalized)}(?:\s+-\s+[^\n]+)?$")
    if heading.search(changelog_path.read_text(encoding="utf-8")) is None:
        fail(f"CHANGELOG.md has no heading for {normalized}")


def _read_version(path: Path, pattern: re.Pattern[str], label: str) -> str:
    text = path.read_text(encoding="utf-8")
    match = pattern.search(text)
    if match is None:
        fail(f"Could not find {label} version in {display_path(path)}")
    version = validate_version(match.group(1))
    return version


def read_current_version(target: ReleaseTarget = ROOT_TARGET) -> str:
    pyproject_version = read_manifest_version(target)
    if target.constants_path is None:
        return pyproject_version
    constants_version = _read_version(
        target.constants_path,
        CONSTANTS_VERSION_PATTERN,
        display_path(target.constants_path),
    )
    if pyproject_version != constants_version:
        fail(
            "Version mismatch: "
            f"{display_path(target.pyproject_path)} has {pyproject_version}, "
            f"{display_path(target.constants_path)} has {constants_version}"
        )
    return pyproject_version


def read_manifest_version(target: ReleaseTarget = ROOT_TARGET) -> str:
    """Read the package-owned version without consulting derived copies."""

    return _read_version(
        target.pyproject_path,
        PYPROJECT_VERSION_PATTERN,
        display_path(target.pyproject_path),
    )


def read_target_version(target: ReleaseTarget) -> str:
    return read_current_version(target)


def _replace_version(
    path: Path, pattern: re.Pattern[str], replacement: str, label: str
) -> None:
    text = path.read_text(encoding="utf-8")
    updated, count = pattern.subn(replacement, text, count=1)
    if count != 1:
        fail(f"Could not update {label} version in {display_path(path)}")
    path.write_text(updated, encoding="utf-8")


def target_version_files(target: ReleaseTarget) -> tuple[Path, ...]:
    paths = [target.pyproject_path]
    if target.constants_path is not None:
        paths.append(target.constants_path)
    if target == ROOT_TARGET:
        paths.extend((ROOT_README_PATH, PG_README_PATH, SUMMON_README_PATH))
    elif target == PG_TARGET:
        paths.extend((ROOT_README_PATH, PG_README_PATH))
    elif target == SUMMON_TARGET:
        paths.extend((ROOT_README_PATH, SUMMON_README_PATH))
    return tuple(paths)


def _replace_all(path: Path, pattern: re.Pattern[str], replacement: str) -> None:
    text = path.read_text(encoding="utf-8")
    updated, count = pattern.subn(replacement, text)
    if count == 0:
        fail(f"Could not update release example in {display_path(path)}")
    path.write_text(updated, encoding="utf-8")


def sync_readme_version_examples(
    target: ReleaseTarget,
    version: str,
    *,
    root_readme_path: Path = ROOT_README_PATH,
    pg_readme_path: Path = PG_README_PATH,
    summon_readme_path: Path = SUMMON_README_PATH,
) -> None:
    normalized = validate_version(version)
    if target == ROOT_TARGET:
        for path in (root_readme_path, pg_readme_path, summon_readme_path):
            _replace_all(path, CORE_README_TAG_PATTERN, f"@v{normalized}")
        return
    if target == PG_TARGET:
        replacement = f"taut_pg-{normalized}-py3-none-any.whl"
        for path in (root_readme_path, pg_readme_path):
            _replace_all(path, PG_WHEEL_PATTERN, replacement)
        return
    if target == SUMMON_TARGET:
        replacement = f"taut_summon-{normalized}-py3-none-any.whl"
        for path in (root_readme_path, summon_readme_path):
            _replace_all(path, SUMMON_WHEEL_PATTERN, replacement)


def sync_readme_simplebroker_requirement(
    *,
    root_pyproject_path: Path = PYPROJECT_PATH,
    root_readme_path: Path = ROOT_README_PATH,
) -> str:
    """Copy the root manifest's exact SimpleBroker floor to every README copy."""

    manifest_text = root_pyproject_path.read_text(encoding="utf-8")
    matches = SIMPLEBROKER_DEPENDENCY_PATTERN.findall(manifest_text)
    if len(matches) != 1:
        fail(
            "Expected one exact unmarked simplebroker>=X.Y.Z dependency in "
            f"{display_path(root_pyproject_path)}"
        )
    floor = validate_version(matches[0])
    readme_text = root_readme_path.read_text(encoding="utf-8")
    updated, count = README_SIMPLEBROKER_DEPENDENCY_PATTERN.subn(
        f"simplebroker>={floor}", readme_text
    )
    if count == 0:
        fail(
            "Expected at least one simplebroker>=X.Y.Z requirement in "
            f"{display_path(root_readme_path)}"
        )
    if updated != readme_text:
        root_readme_path.write_text(updated, encoding="utf-8")
    return floor


def write_version_files(version: str, target: ReleaseTarget = ROOT_TARGET) -> None:
    normalized = validate_version(version)
    _replace_version(
        target.pyproject_path,
        re.compile(r'(?m)^version = "[^"]+"$'),
        f'version = "{normalized}"',
        display_path(target.pyproject_path),
    )
    if target.constants_path is not None:
        _replace_version(
            target.constants_path,
            re.compile(r'(?m)^(__version__(?::[^=]+)? = )"[^"]+"$'),
            rf'\g<1>"{normalized}"',
            display_path(target.constants_path),
        )
    if target in {ROOT_TARGET, PG_TARGET, SUMMON_TARGET}:
        sync_readme_version_examples(target, normalized)
    if target in (PG_TARGET, SUMMON_TARGET) or target.package_name in {
        "taut-pg",
        "taut-summon",
    }:
        root_version = read_manifest_version(ROOT_TARGET)
        _replace_version(
            target.pyproject_path,
            TAUT_DEPENDENCY_PATTERN,
            rf"\g<1>{root_version}\g<2>",
            f"{display_path(target.pyproject_path)} taut dependency",
        )


def read_summon_extension_version(
    *, summon_pyproject_path: Path = SUMMON_PYPROJECT_PATH
) -> str:
    return _read_version(
        summon_pyproject_path,
        PYPROJECT_VERSION_PATTERN,
        display_path(summon_pyproject_path),
    )


def sync_root_summon_dev_dependency(
    *,
    root_pyproject_path: Path = PYPROJECT_PATH,
    summon_pyproject_path: Path = SUMMON_PYPROJECT_PATH,
) -> str | None:
    """Set the root dev dependency to the local taut-summon version."""

    summon_version = read_summon_extension_version(
        summon_pyproject_path=summon_pyproject_path
    )
    text = root_pyproject_path.read_text(encoding="utf-8")

    def replace_dependency(match: re.Match[str]) -> str:
        prefix, current_version, suffix = match.groups()
        if current_version == summon_version:
            return match.group(0)
        return f"{prefix}{summon_version}{suffix}"

    updated, count = TAUT_SUMMON_DEPENDENCY_PATTERN.subn(
        replace_dependency,
        text,
        count=1,
    )
    if count != 1:
        fail("Expected one taut-summon dependency in root pyproject.toml")
    if updated == text:
        return None
    root_pyproject_path.write_text(updated, encoding="utf-8")
    return summon_version


def sync_root_pg_dev_dependency(
    *,
    root_pyproject_path: Path = PYPROJECT_PATH,
    pg_pyproject_path: Path = PG_PYPROJECT_PATH,
) -> str | None:
    """Set the root dev SimpleBroker PG floor from the PG manifest."""

    pg_text = pg_pyproject_path.read_text(encoding="utf-8")
    pg_matches = SIMPLEBROKER_PG_DEPENDENCY_PATTERN.findall(pg_text)
    if len(pg_matches) != 1:
        fail(
            "Expected one exact simplebroker-pg>=X.Y.Z dependency in "
            f"{display_path(pg_pyproject_path)}"
        )
    floor = validate_version(pg_matches[0][1])
    root_text = root_pyproject_path.read_text(encoding="utf-8")
    updated, count = SIMPLEBROKER_PG_DEPENDENCY_PATTERN.subn(
        rf"\g<1>{floor}\g<3>", root_text, count=1
    )
    if count != 1:
        fail("Expected one simplebroker-pg dependency in root pyproject.toml")
    if updated == root_text:
        return None
    root_pyproject_path.write_text(updated, encoding="utf-8")
    return floor


def sync_summon_core_dependency(
    *,
    root_pyproject_path: Path = PYPROJECT_PATH,
    summon_pyproject_path: Path = SUMMON_PYPROJECT_PATH,
) -> str | None:
    """Set Summon's taut floor to the exact local core version."""

    return sync_extension_core_dependency(
        root_pyproject_path=root_pyproject_path,
        extension_pyproject_path=summon_pyproject_path,
        extension_label="taut-summon",
    )


def sync_pg_core_dependency(
    *,
    root_pyproject_path: Path = PYPROJECT_PATH,
    pg_pyproject_path: Path = PG_PYPROJECT_PATH,
) -> str | None:
    """Set PG's taut floor to the exact local core version."""

    return sync_extension_core_dependency(
        root_pyproject_path=root_pyproject_path,
        extension_pyproject_path=pg_pyproject_path,
        extension_label="taut-pg",
    )


def sync_extension_core_dependency(
    *,
    root_pyproject_path: Path,
    extension_pyproject_path: Path,
    extension_label: str,
) -> str | None:
    """Set one first-party extension's taut floor to the local core version."""

    root_version = _read_version(
        root_pyproject_path,
        PYPROJECT_VERSION_PATTERN,
        display_path(root_pyproject_path),
    )
    text = extension_pyproject_path.read_text(encoding="utf-8")
    updated, count = TAUT_DEPENDENCY_PATTERN.subn(
        rf"\g<1>{root_version}\g<2>", text, count=1
    )
    if count != 1:
        fail(
            f"Could not update {extension_label} taut dependency in "
            f"{display_path(extension_pyproject_path)}"
        )
    if updated == text:
        return None
    extension_pyproject_path.write_text(updated, encoding="utf-8")
    return root_version


def prepare_release_metadata(
    target_versions: tuple[tuple[ReleaseTarget, str], ...],
) -> None:
    """Reconcile all deterministic metadata owned by the selected manifests."""

    if not target_versions:
        fail("At least one release target is required")
    requested_versions = {
        target.key: validate_version(version) for target, version in target_versions
    }
    ordered_targets = (ROOT_TARGET, PG_TARGET, SUMMON_TARGET)
    versions = {
        target.key: (
            requested_versions[target.key]
            if target.key in requested_versions
            else read_manifest_version(target)
        )
        for target in ordered_targets
    }
    for target in ordered_targets:
        write_version_files(versions[target.key], target)

    _sync_root_release_dependencies()
    floor = sync_readme_simplebroker_requirement()
    print(f"Synchronized README requirement: simplebroker>={floor}")

    for target in ordered_targets:
        actual = read_current_version(target)
        expected = versions[target.key]
        if actual != expected:
            fail(
                f"Prepared {target.package_name} version {actual}, expected {expected}"
            )


def format_command(command: Command) -> str:
    return " ".join(shlex.quote(part) for part in command)


def _format_command_prefix(env_overrides: dict[str, str] | None) -> str:
    if not env_overrides:
        return ""
    return " ".join(
        f"{key}={shlex.quote(value)}" for key, value in sorted(env_overrides.items())
    )


def _format_cwd_suffix(cwd: Path) -> str:
    if cwd == PROJECT_ROOT:
        return ""
    return f"  (cwd={display_path(cwd)})"


def _merge_command_env(
    env_overrides: dict[str, str] | None,
    *,
    base_env: dict[str, str] | None = None,
) -> dict[str, str] | None:
    if not env_overrides:
        return None

    merged = os.environ.copy() if base_env is None else base_env.copy()
    for key, value in env_overrides.items():
        if key == "PYTEST_ADDOPTS":
            existing = merged.get(key, "").strip()
            merged[key] = f"{existing} {value}".strip() if existing else value
            continue
        if key == "PYTHONPATH":
            existing = merged.get(key, "").strip()
            merged[key] = os.pathsep.join(part for part in (existing, value) if part)
            continue
        merged[key] = value
    return merged


def run_command(
    command: Command,
    *,
    cwd: Path = PROJECT_ROOT,
    dry_run: bool = False,
    env_overrides: dict[str, str] | None = None,
) -> None:
    prefix = _format_command_prefix(env_overrides)
    formatted = format_command(command)
    command_text = f"+ {prefix} {formatted}" if prefix else f"+ {formatted}"
    print(f"{command_text}{_format_cwd_suffix(cwd)}", flush=True)
    if dry_run:
        return
    subprocess.run(
        command,
        cwd=cwd,
        check=True,
        env=_merge_command_env(env_overrides),
    )


def _run_setup_command(command: Command, *, timeout: float) -> None:
    print(f"+ {format_command(command)}")
    subprocess.run(command, cwd=PROJECT_ROOT, check=True, timeout=timeout)


def _endpoint_origin(endpoint: str) -> str:
    parsed = urllib.parse.urlsplit(endpoint)
    if not parsed.scheme or not parsed.netloc:
        fail(f"local LLM endpoint must be absolute, got {endpoint!r}")
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))


def _joined_endpoint(endpoint: str, path: str) -> str:
    return f"{endpoint.rstrip('/')}/{path.lstrip('/')}"


def _assert_loopback_endpoint(endpoint: str) -> None:
    if os.environ.get("TAUT_SUMMON_LOCAL_LLM_ALLOW_NONLOCAL") == "1":
        return
    parsed = urllib.parse.urlsplit(endpoint)
    if parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        fail(
            "TAUT_SUMMON_LOCAL_LLM_ENDPOINT must be loopback during release "
            "prechecks; set TAUT_SUMMON_LOCAL_LLM_ALLOW_NONLOCAL=1 only for a "
            f"deliberate non-local endpoint (got {endpoint!r})"
        )


def _read_json_url(url: str, *, timeout: float) -> dict[str, object]:
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.load(response)
    if not isinstance(payload, dict):
        fail(f"{url} returned non-object JSON: {payload!r}")
    return payload


def _endpoint_has_model(endpoint: str, model: str) -> bool:
    try:
        payload = _read_json_url(
            _joined_endpoint(endpoint, "models"),
            timeout=LOCAL_LLM_HTTP_TIMEOUT_SECONDS,
        )
    except LOCAL_LLM_RETRYABLE_HTTP_ERRORS:
        return False
    raw_data = payload.get("data")
    if not isinstance(raw_data, list):
        return False
    return any(isinstance(item, dict) and item.get("id") == model for item in raw_data)


def _wait_for_http_endpoint(origin: str, *, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            urllib.request.urlopen(
                origin, timeout=LOCAL_LLM_HTTP_TIMEOUT_SECONDS
            ).close()
            return
        except LOCAL_LLM_RETRYABLE_HTTP_ERRORS:
            time.sleep(2)
    fail(f"local LLM server did not become ready at {origin}")


def _wait_for_model(endpoint: str, model: str, *, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _endpoint_has_model(endpoint, model):
            return
        time.sleep(2)
    fail(f"local LLM endpoint {endpoint!r} did not list model {model!r}")


def _free_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class LocalLlmPreparation:
    """Background setup for the required local-LLM summon release lane."""

    def __init__(self, *, dry_run: bool) -> None:
        self.dry_run = dry_run
        self.endpoint = os.environ.get(
            "TAUT_SUMMON_LOCAL_LLM_ENDPOINT", LOCAL_LLM_DEFAULT_ENDPOINT
        )
        self.model = os.environ.get(
            "TAUT_SUMMON_LOCAL_LLM_MODEL", LOCAL_LLM_DEFAULT_MODEL
        )
        self.base_model = os.environ.get(
            "OLLAMA_BASE_MODEL", LOCAL_LLM_DEFAULT_BASE_MODEL
        )
        self.context_length = os.environ.get(
            "OLLAMA_CONTEXT_LENGTH", LOCAL_LLM_DEFAULT_CONTEXT_LENGTH
        )
        self.num_predict = os.environ.get(
            "OLLAMA_NUM_PREDICT", LOCAL_LLM_DEFAULT_NUM_PREDICT
        )
        self.image = os.environ.get("OLLAMA_IMAGE", LOCAL_LLM_DEFAULT_IMAGE)
        self.container_name: str | None = None
        self._thread: threading.Thread | None = None
        self._error: BaseException | None = None
        self._ready = False

    @property
    def env_overrides(self) -> dict[str, str]:
        return {
            "TAUT_SUMMON_LOCAL_LLM": "1",
            "TAUT_SUMMON_LOCAL_LLM_ENDPOINT": self.endpoint,
            "TAUT_SUMMON_LOCAL_LLM_MODEL": self.model,
        }

    def start(self) -> None:
        print("Preparing taut-summon local LLM release gate")
        if self.dry_run:
            print(
                "dry-run: would use an existing loopback local LLM endpoint or "
                "start a disposable Ollama container in parallel with prechecks"
            )
            return

        _assert_loopback_endpoint(self.endpoint)
        if _endpoint_has_model(self.endpoint, self.model):
            print(
                f"Using existing local LLM endpoint {self.endpoint} "
                f"with model {self.model}"
            )
            self._ready = True
            return

        configured_endpoint = os.environ.get("TAUT_SUMMON_LOCAL_LLM_ENDPOINT")
        if configured_endpoint and configured_endpoint != LOCAL_LLM_DEFAULT_ENDPOINT:
            fail(
                f"Configured local LLM endpoint {self.endpoint!r} did not list "
                f"model {self.model!r}; refusing to test a different endpoint"
            )

        _require_command("docker")
        port = _free_loopback_port()
        self.endpoint = f"http://127.0.0.1:{port}/v1"
        self.container_name = f"taut-summon-release-llm-{os.getpid()}-{port}"
        print(
            "Starting local Ollama preparation in the background "
            f"({self.container_name} on {self.endpoint})"
        )
        self._thread = threading.Thread(
            target=self._prepare_container,
            daemon=True,
            name="taut-summon-local-llm-prep",
        )
        self._thread.start()

    def wait_ready(self) -> None:
        if self.dry_run or self._ready:
            return
        if self._thread is None:
            fail("local LLM preparation did not start")
        self._thread.join()
        if self._error is not None:
            fail(f"local LLM preparation failed: {self._error}")
        _wait_for_model(
            self.endpoint,
            self.model,
            timeout=LOCAL_LLM_MODEL_WAIT_SECONDS,
        )
        self._ready = True
        print(f"Local LLM model ready: {self.model} at {self.endpoint}")

    def close(self) -> None:
        if self.dry_run:
            return
        if self.container_name is None:
            return
        if self._thread is not None and self._thread.is_alive():
            subprocess.run(
                ("docker", "rm", "-f", self.container_name),
                cwd=PROJECT_ROOT,
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self._thread.join(timeout=10.0)
        subprocess.run(
            ("docker", "rm", "-f", self.container_name),
            cwd=PROJECT_ROOT,
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def _prepare_container(self) -> None:
        try:
            assert self.container_name is not None
            _run_setup_command(
                (
                    "docker",
                    "run",
                    "-d",
                    "--name",
                    self.container_name,
                    "-p",
                    f"127.0.0.1:{urllib.parse.urlsplit(self.endpoint).port}:11434",
                    self.image,
                ),
                timeout=LOCAL_LLM_SETUP_COMMAND_TIMEOUT_SECONDS,
            )
            _wait_for_http_endpoint(
                _endpoint_origin(self.endpoint),
                timeout=LOCAL_LLM_SERVER_WAIT_SECONDS,
            )
            _run_setup_command(
                (
                    "docker",
                    "exec",
                    self.container_name,
                    "ollama",
                    "pull",
                    self.base_model,
                ),
                timeout=LOCAL_LLM_SETUP_COMMAND_TIMEOUT_SECONDS,
            )
            if self.model != self.base_model:
                with tempfile.TemporaryDirectory() as temp_dir:
                    modelfile = Path(temp_dir) / "TautSummonModelfile"
                    modelfile.write_text(
                        "\n".join(
                            [
                                f"FROM {self.base_model}",
                                f"PARAMETER num_ctx {self.context_length}",
                                f"PARAMETER num_predict {self.num_predict}",
                                "PARAMETER temperature 0",
                                "",
                            ]
                        ),
                        encoding="utf-8",
                    )
                    _run_setup_command(
                        (
                            "docker",
                            "cp",
                            str(modelfile),
                            f"{self.container_name}:/tmp/TautSummonModelfile",
                        ),
                        timeout=LOCAL_LLM_SETUP_COMMAND_TIMEOUT_SECONDS,
                    )
                _run_setup_command(
                    (
                        "docker",
                        "exec",
                        self.container_name,
                        "ollama",
                        "create",
                        self.model,
                        "-f",
                        "/tmp/TautSummonModelfile",
                    ),
                    timeout=LOCAL_LLM_SETUP_COMMAND_TIMEOUT_SECONDS,
                )
            _wait_for_model(
                self.endpoint,
                self.model,
                timeout=LOCAL_LLM_MODEL_WAIT_SECONDS,
            )
        except BaseException as exc:  # noqa: BLE001 - propagated at wait gate
            self._error = exc


def capture_command(command: Command, *, cwd: Path = PROJECT_ROOT) -> str:
    result = subprocess.run(
        command,
        cwd=cwd,
        check=True,
        text=True,
        capture_output=True,
    )
    return result.stdout.strip()


def capture_optional_command(
    command: Command, *, cwd: Path = PROJECT_ROOT
) -> str | None:
    result = subprocess.run(
        command,
        cwd=cwd,
        check=False,
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        return None
    output = result.stdout.strip()
    return output or None


def current_head_commit() -> str:
    return capture_command(("git", "rev-parse", "HEAD"))


def current_branch() -> str:
    branch = capture_command(("git", "rev-parse", "--abbrev-ref", "HEAD"))
    if branch == "HEAD":
        fail("Cannot release from a detached HEAD")
    return branch


def require_publish_branch() -> str:
    """Require the canonical branch that owns push-triggered release evidence."""

    branch = current_branch()
    if branch not in PUBLISH_BRANCHES:
        fail(
            "Publishing releases requires branch main or master; "
            f"current branch is {branch!r}"
        )
    return branch


def push_current_branch(
    *,
    dry_run: bool,
    branch: str | None = None,
    head_commit: str | None = None,
) -> None:
    if branch is None:
        branch = capture_command(("git", "rev-parse", "--abbrev-ref", "HEAD"))
    if branch == "HEAD":
        if dry_run:
            print(
                "DRY RUN: detached HEAD; a real release would stop before branch push"
            )
            return
        fail("Cannot release from a detached HEAD")
    if head_commit is None:
        head_commit = current_head_commit()
    run_command(
        ("git", "push", "origin", f"{head_commit}:refs/heads/{branch}"),
        dry_run=dry_run,
    )


def is_dirty_worktree() -> bool:
    return bool(capture_command(("git", "status", "--porcelain")))


def local_tag_commit(tag_name: str) -> str | None:
    return capture_optional_command(
        ("git", "rev-parse", "-q", "--verify", f"refs/tags/{tag_name}^{{commit}}")
    )


def remote_tag_commit(tag_name: str) -> str | None:
    result = subprocess.run(
        (
            "git",
            "ls-remote",
            "--tags",
            "origin",
            f"refs/tags/{tag_name}",
            f"refs/tags/{tag_name}^{{}}",
        ),
        cwd=PROJECT_ROOT,
        check=False,
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or "unknown error"
        fail(f"Could not inspect remote tag {tag_name}: {detail}")

    tag_ref = f"refs/tags/{tag_name}"
    peeled_ref = f"{tag_ref}^{{}}"
    tag_sha: str | None = None
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) != 2:
            continue
        sha, ref = parts
        if ref == peeled_ref:
            return sha
        if ref == tag_ref:
            tag_sha = sha
    return tag_sha


def origin_remote_url() -> str:
    return capture_command(("git", "remote", "get-url", "origin"))


def github_repo_slug_from_remote(remote_url: str) -> str | None:
    stripped = remote_url.strip()
    if stripped.startswith("git@github.com:"):
        path = stripped.removeprefix("git@github.com:")
    elif stripped.startswith("ssh://git@github.com/"):
        path = stripped.removeprefix("ssh://git@github.com/")
    elif stripped.startswith(("https://github.com/", "http://github.com/")):
        path = urllib.parse.urlparse(stripped).path.lstrip("/")
    else:
        return None

    if path.endswith(".git"):
        path = path[:-4]
    if path.count("/") != 1:
        return None
    owner, repo = path.split("/", maxsplit=1)
    if not owner or not repo:
        return None
    return f"{owner}/{repo}"


@lru_cache(maxsize=1)
def _github_api_token() -> str | None:
    for env_var in ("GITHUB_TOKEN", "GH_TOKEN"):
        token = os.environ.get(env_var, "").strip()
        if token:
            return token

    if shutil.which("gh") is None:
        return None

    gh_token = capture_optional_command(("gh", "auth", "token"))
    return gh_token or None


def github_api_headers() -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "taut-release-helper",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = _github_api_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def github_release_exists(tag_name: str) -> bool:
    slug = github_repo_slug_from_remote(origin_remote_url())
    if slug is None:
        fail("Origin remote is not a GitHub repository; taut releases are GitHub-only")

    encoded_tag = urllib.parse.quote(tag_name, safe="")
    url = f"{GITHUB_API_BASE}/repos/{slug}/releases/tags/{encoded_tag}"
    request = urllib.request.Request(url, headers=github_api_headers())
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
            data: object = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return False
        fail(f"GitHub release lookup failed for {tag_name}: HTTP {exc.code}")
    except urllib.error.URLError as exc:
        fail(f"GitHub release lookup failed for {tag_name}: {exc.reason}")

    return isinstance(data, dict) and data.get("tag_name") == tag_name


def inspect_release_state(target: ReleaseTarget, version: str) -> ReleaseState:
    normalized = validate_version(version)
    tag_name = target.tag_for_version(normalized)
    exists = github_release_exists(tag_name) if target.github_release else False
    return ReleaseState(
        target=target,
        version=normalized,
        tag_name=tag_name,
        github_release_exists=exists,
        local_tag_commit=local_tag_commit(tag_name),
        remote_tag_commit=remote_tag_commit(tag_name),
    )


def published_destinations(state: ReleaseState) -> str:
    return "GitHub Release" if state.github_release_exists else "nowhere"


def resolve_target_version(
    requested_version: str | None,
    target: ReleaseTarget = ROOT_TARGET,
) -> tuple[str, str, ReleaseState]:
    current_version = read_manifest_version(target)
    target_version = current_version if requested_version is None else requested_version
    target_version = validate_version(target_version)
    require_not_backdated(current_version, target_version)
    state = inspect_release_state(target, target_version)
    if state.published:
        if requested_version is None:
            fail(
                f"Current {target.package_name} version {current_version} already "
                "exists as a GitHub Release; pass --version with a new version"
            )
        fail(
            f"{target.package_name} {target_version} already exists as a "
            "GitHub Release; choose a new version"
        )
    return current_version, target_version, state


def _unique_strings(parts: tuple[str, ...]) -> tuple[str, ...]:
    seen: set[str] = set()
    unique: list[str] = []
    for part in parts:
        if part in seen:
            continue
        seen.add(part)
        unique.append(part)
    return tuple(unique)


def _ruff_check_command(paths: Command) -> Command:
    return (*RUFF_CHECK_PREFIX, *paths)


def _ruff_format_command(paths: Command) -> Command:
    return (*RUFF_FORMAT_PREFIX, *paths)


def _mypy_command(paths: Command) -> Command:
    return (*MYPY_PREFIX, *paths, *MYPY_SUFFIX)


def build_precheck_commands_for_targets(
    targets: tuple[ReleaseTarget, ...],
) -> tuple[Command, ...]:
    if not targets:
        fail("At least one release target is required")

    tool_paths = _unique_strings((*ROOT_TOOL_PATHS, *PG_TOOL_PATHS, *SUMMON_TOOL_PATHS))
    return (
        *ROOT_TEST_COMMANDS,
        PG_TEST_COMMAND,
        *SUMMON_TEST_COMMANDS,
        _ruff_check_command(tool_paths),
        _ruff_format_command(tool_paths),
        _mypy_command(ROOT_MYPY_PATHS),
        _mypy_command(PG_MYPY_PATHS),
        _mypy_command(SUMMON_MYPY_PATHS),
    )


def build_precheck_commands(target: ReleaseTarget = ROOT_TARGET) -> tuple[Command, ...]:
    return build_precheck_commands_for_targets((target,))


def _unique_steps(steps: tuple[CommandStep, ...]) -> tuple[CommandStep, ...]:
    seen: set[tuple[Path, Command]] = set()
    unique: list[CommandStep] = []
    for step in steps:
        key = (step.cwd, step.command)
        if key in seen:
            continue
        seen.add(key)
        unique.append(step)
    return tuple(unique)


def build_preparation_steps_for_targets(
    targets: tuple[ReleaseTarget, ...],
) -> tuple[CommandStep, ...]:
    if not targets:
        fail("At least one release target is required")
    return (
        CommandStep(
            ("uv", "lock", "--upgrade-package", "simplebroker"),
            "Refresh retained taut-summon dependencies selectively",
            cwd=SUMMON_EXTENSION_DIR,
        ),
    )


def build_postupdate_steps_for_targets(
    targets: tuple[ReleaseTarget, ...],
) -> tuple[CommandStep, ...]:
    if not targets:
        fail("At least one release target is required")

    target_keys = {target.key for target in targets}
    steps: list[CommandStep] = []
    if ROOT_TARGET.key in target_keys:
        steps.append(CommandStep(("uv", "build"), "Build taut source and wheel"))
    if PG_TARGET.key in target_keys:
        steps.append(
            CommandStep(
                ("uv", "build", PG_TARGET.package_dir.as_posix()),
                "Build taut-pg source and wheel",
            )
        )
    if SUMMON_TARGET.key in target_keys:
        steps.append(
            CommandStep(
                ("uv", "build", SUMMON_TARGET.package_dir.as_posix()),
                "Build taut-summon source and wheel",
            )
        )
    if target_keys & {ROOT_TARGET.key, SUMMON_TARGET.key}:
        steps.append(
            CommandStep(
                (sys.executable, str(RELEASE_WHEEL_SET_CHECKER)),
                "Build and check fresh paired core/Summon release wheels",
            )
        )
    return _unique_steps(tuple(steps))


def build_postupdate_steps(
    target: ReleaseTarget = ROOT_TARGET,
) -> tuple[CommandStep, ...]:
    return build_postupdate_steps_for_targets((target,))


def _precheck_env_overrides(
    command: Command,
    *,
    local_llm_env: dict[str, str] | None = None,
) -> dict[str, str]:
    overrides = dict(PRECHECK_ENV_OVERRIDES)
    if command == SUMMON_LIVE_HARNESS_TEST_COMMAND:
        overrides["TAUT_SUMMON_LIVE_HARNESS"] = "1"
        overrides["TAUT_SUMMON_LIVE_HARNESS_STRICT"] = "1"
    if command == SUMMON_LOCAL_LLM_TEST_COMMAND:
        overrides["TAUT_SUMMON_LOCAL_LLM"] = "1"
        if local_llm_env is not None:
            overrides.update(local_llm_env)
    return overrides


def _targets_need_local_llm_preparation(targets: tuple[ReleaseTarget, ...]) -> bool:
    return bool(targets)


def run_prechecks_for_targets(
    targets: tuple[ReleaseTarget, ...],
    *,
    dry_run: bool,
) -> None:
    local_llm: LocalLlmPreparation | None = None
    if _targets_need_local_llm_preparation(targets):
        local_llm = LocalLlmPreparation(dry_run=dry_run)
        local_llm.start()
    try:
        for command in build_precheck_commands_for_targets(targets):
            local_llm_env: dict[str, str] | None = None
            if command == SUMMON_LOCAL_LLM_TEST_COMMAND and local_llm is not None:
                local_llm.wait_ready()
                local_llm_env = local_llm.env_overrides
            run_command(
                command,
                dry_run=dry_run,
                env_overrides=_precheck_env_overrides(
                    command,
                    local_llm_env=local_llm_env,
                ),
            )
    finally:
        if local_llm is not None:
            local_llm.close()


def run_prechecks(target: ReleaseTarget, *, dry_run: bool) -> None:
    run_prechecks_for_targets((target,), dry_run=dry_run)


def _run_postupdate_step(step: CommandStep, *, dry_run: bool) -> None:
    print(step.description)
    if dry_run and step.command == (
        sys.executable,
        str(RELEASE_WHEEL_SET_CHECKER),
    ):
        run_command((*step.command, "--dry-run"), cwd=step.cwd)
        return
    run_command(step.command, cwd=step.cwd, dry_run=dry_run)


def run_postupdate_steps(target: ReleaseTarget, *, dry_run: bool) -> None:
    for step in build_postupdate_steps(target):
        _run_postupdate_step(step, dry_run=dry_run)


def run_preparation_steps(targets: tuple[ReleaseTarget, ...], *, dry_run: bool) -> None:
    for step in build_preparation_steps_for_targets(targets):
        _run_postupdate_step(step, dry_run=dry_run)


def _release_file_paths(_target: ReleaseTarget) -> tuple[Path, ...]:
    paths = [
        PYPROJECT_PATH,
        CONSTANTS_PATH,
        ROOT_README_PATH,
        PG_PYPROJECT_PATH,
        PG_README_PATH,
        SUMMON_PYPROJECT_PATH,
        SUMMON_README_PATH,
    ]
    if SUMMON_UV_LOCK_PATH.exists():
        paths.append(SUMMON_UV_LOCK_PATH)
    return tuple(paths)


def _release_file_args(target: ReleaseTarget) -> tuple[str, ...]:
    return tuple(display_path(path) for path in _release_file_paths(target))


def _unique_paths(paths: tuple[Path, ...]) -> tuple[Path, ...]:
    seen: set[Path] = set()
    unique: list[Path] = []
    for path in paths:
        if path in seen:
            continue
        seen.add(path)
        unique.append(path)
    return tuple(unique)


def _release_file_paths_for_targets(
    targets: tuple[ReleaseTarget, ...],
) -> tuple[Path, ...]:
    return _unique_paths(
        tuple(path for target in targets for path in _release_file_paths(target))
    )


def _release_file_args_for_targets(
    targets: tuple[ReleaseTarget, ...],
) -> tuple[str, ...]:
    return tuple(
        display_path(path) for path in _release_file_paths_for_targets(targets)
    )


def release_files_changed(target: ReleaseTarget) -> bool:
    return release_files_changed_for_targets((target,))


def release_files_changed_for_targets(targets: tuple[ReleaseTarget, ...]) -> bool:
    result = subprocess.run(
        ("git", "diff", "--quiet", "--", *_release_file_args_for_targets(targets)),
        cwd=PROJECT_ROOT,
        check=False,
        text=True,
        capture_output=True,
    )
    if result.returncode == 0:
        return False
    if result.returncode == 1:
        return True
    detail = result.stderr.strip() or result.stdout.strip() or "unknown git error"
    fail(f"Unable to inspect release file changes: {detail}")


def commit_release_preparation(
    targets: tuple[ReleaseTarget, ...], *, message: str
) -> tuple[bool, str]:
    """Commit only the deterministic release allowlist and return its HEAD."""

    changed = release_files_changed_for_targets(targets)
    if changed:
        run_command(("git", "add", *_release_file_args_for_targets(targets)))
        run_command(("git", "commit", "-m", message))
    else:
        print("No release commit needed; release files already match manifests")
    preparation_commit = current_head_commit()
    if is_dirty_worktree():
        fail(
            "Release preparation did not leave a clean worktree; no remote "
            "release action ran"
        )
    return changed, preparation_commit


def _short_commit(commit: str) -> str:
    return commit[:12]


def plan_tag_action(
    state: ReleaseState,
    *,
    version_changed: bool,
    head_commit: str,
    retag: bool = False,
    allow_retag: bool | None = None,
) -> TagAction:
    if allow_retag is not None:
        retag = allow_retag

    local_commit = state.local_tag_commit
    remote_commit = state.remote_tag_commit
    tag_name = state.tag_name

    if version_changed:
        if remote_commit is not None:
            if retag:
                return TagAction("replace_remote", state, head_commit)
            fail(
                f"Remote tag {tag_name} exists at {_short_commit(remote_commit)}; "
                "pass --retag to replace it"
            )
        if local_commit is not None:
            return TagAction("replace_local", state, head_commit)
        return TagAction("create", state, head_commit)

    if remote_commit is not None and remote_commit != head_commit:
        if retag:
            return TagAction("replace_remote", state, head_commit)
        fail(
            f"Remote tag {tag_name} exists at {_short_commit(remote_commit)}, "
            f"not current HEAD {_short_commit(head_commit)}; pass --retag to replace it"
        )

    if local_commit is not None and local_commit != head_commit:
        if remote_commit is None:
            return TagAction("replace_local", state, head_commit)
        fail(
            f"Local tag {tag_name} exists at {_short_commit(local_commit)}, "
            f"not current HEAD {_short_commit(head_commit)}"
        )

    if remote_commit is not None:
        return TagAction("reuse_remote", state, head_commit)
    if local_commit is not None:
        return TagAction("push_local", state, head_commit)
    return TagAction("create", state, head_commit)


def describe_tag_action(action: TagAction) -> str:
    tag_name = action.state.tag_name
    descriptions = {
        "create": f"create local tag {tag_name}",
        "replace_local": f"replace stale local tag {tag_name}",
        "replace_remote": f"replace remote tag {tag_name}",
        "reuse_remote": f"reuse existing remote tag {tag_name}",
        "push_local": f"push existing local tag {tag_name}",
    }
    return descriptions[action.action]


def _remote_tag_reuse_note(state: ReleaseState) -> str:
    return (
        f"Tag {state.tag_name} already exists on origin at HEAD. Pushing the same "
        f"tag again will not retrigger {state.target.release_workflow}; rerun the "
        "existing release-gate workflow manually in GitHub Actions if needed."
    )


def prepare_tag(action: TagAction, *, dry_run: bool) -> None:
    tag_name = action.state.tag_name
    if action.action == "reuse_remote":
        return

    if action.action == "push_local":
        print(f"Local tag {tag_name} already points at {action.head_commit}")
        return

    if action.action in {"replace_local", "replace_remote"}:
        run_command(
            ("git", "tag", "-f", tag_name, action.head_commit),
            dry_run=dry_run,
        )
    else:
        run_command(
            ("git", "tag", tag_name, action.head_commit),
            dry_run=dry_run,
        )

    if action.action == "replace_remote":
        expected = action.state.remote_tag_commit
        if expected is None:
            fail(f"Cannot lease remote tag replacement for missing {tag_name}")
        run_command(
            (
                "git",
                "push",
                f"--force-with-lease=refs/tags/{tag_name}:{expected}",
                "origin",
                f":refs/tags/{tag_name}",
            ),
            dry_run=dry_run,
        )


def push_tag(action: TagAction, *, dry_run: bool) -> None:
    tag_name = action.state.tag_name
    if action.action == "reuse_remote":
        print(_remote_tag_reuse_note(action.state))
        return
    run_command(
        (
            "git",
            "push",
            "origin",
            f"{action.head_commit}:refs/tags/{tag_name}",
        ),
        dry_run=dry_run,
    )


def print_release_summary(
    *,
    current_version: str,
    target_version: str,
    state: ReleaseState,
    version_changed: bool,
    tag_action: TagAction,
) -> None:
    print(f"Package: {state.target.package_name}")
    print(f"Package directory: {state.target.package_dir}")
    print(f"Current version: {current_version}")
    print(f"Target version: {target_version}")
    print(f"Version change: {'yes' if version_changed else 'no'}")
    print(f"Tag: {state.tag_name}")
    print(f"Release workflow: {state.target.release_workflow}")
    print(f"GitHub Release exists: {'yes' if state.github_release_exists else 'no'}")
    print(f"Local tag commit: {state.local_tag_commit or '<missing>'}")
    print(f"Remote tag commit: {state.remote_tag_commit or '<missing>'}")
    print(f"Tag action: {describe_tag_action(tag_action)}")
    print("PyPI publish: disabled")


def print_publish_note() -> None:
    print(
        "--publish is ignored: taut is GitHub-only until PyPI name clearance; "
        "pushing the GitHub tag is the publish boundary."
    )


def discover_unpublished_releases(
    targets: tuple[ReleaseTarget, ...] = BATCH_RELEASE_TARGETS,
    *,
    requested_version: str | None = None,
) -> tuple[ReleaseCandidate, ...]:
    normalized_requested = (
        validate_version(requested_version) if requested_version is not None else None
    )
    planned_versions: list[tuple[ReleaseTarget, str, str]] = []
    for target in targets:
        current_version = read_manifest_version(target)
        release_version = normalized_requested or current_version
        require_not_backdated(current_version, release_version)
        planned_versions.append((target, current_version, release_version))

    candidates: list[ReleaseCandidate] = []
    for target, current_version, release_version in planned_versions:
        state = inspect_release_state(target, release_version)
        if state.published:
            continue
        candidates.append(
            ReleaseCandidate(
                target=target,
                current_version=current_version,
                release_version=release_version,
                state=state,
            )
        )
    return tuple(candidates)


def require_fresh_release_fence(
    candidates: tuple[ReleaseCandidate, ...],
    *,
    preparation_branch: str,
    preparation_commit: str,
) -> tuple[ReleaseCandidate, ...]:
    """Revalidate the tested checkout and remote state before mutation."""

    branch = current_branch()
    if branch != preparation_branch:
        fail(
            f"Release branch changed from {preparation_branch} to {branch}; "
            "no remote release action ran"
        )
    head = current_head_commit()
    if head != preparation_commit:
        fail(
            f"Release HEAD changed from {_short_commit(preparation_commit)} to "
            f"{_short_commit(head)}; no remote release action ran"
        )
    if is_dirty_worktree():
        fail(
            "Worktree or index changed after release checks; no remote release "
            "action ran"
        )

    refreshed: list[ReleaseCandidate] = []
    for candidate in candidates:
        state = inspect_release_state(candidate.target, candidate.release_version)
        if state.published:
            fail(
                f"{candidate.target.package_name} {candidate.release_version} "
                "became a GitHub Release during local checks; no remote release "
                "action ran"
            )
        refreshed.append(replace(candidate, state=state))
    return tuple(refreshed)


def _candidate_targets(
    candidates: tuple[ReleaseCandidate, ...],
) -> tuple[ReleaseTarget, ...]:
    return tuple(candidate.target for candidate in candidates)


def _candidate_for_target(
    candidates: tuple[ReleaseCandidate, ...],
    target: ReleaseTarget,
) -> ReleaseCandidate | None:
    for candidate in candidates:
        if candidate.target.key == target.key:
            return candidate
    return None


def _format_release_candidate(candidate: ReleaseCandidate) -> str:
    return f"{candidate.target.display_name} {candidate.release_version}"


def _batch_release_commit_message(candidates: tuple[ReleaseCandidate, ...]) -> str:
    if len(candidates) == 1:
        candidate = candidates[0]
        return f"Release {candidate.target.display_name} {candidate.release_version}"
    releases = ", ".join(
        _format_release_candidate(candidate) for candidate in candidates
    )
    return f"Release {releases}"


def _plan_candidate_tag_actions(
    candidates: tuple[ReleaseCandidate, ...],
    *,
    head_commit: str,
    version_changed: bool,
    retag: bool,
) -> dict[str, TagAction]:
    return {
        candidate.target.key: plan_tag_action(
            candidate.state,
            head_commit=head_commit,
            version_changed=version_changed,
            retag=retag,
        )
        for candidate in candidates
    }


def _print_batch_release_plan(
    candidates: tuple[ReleaseCandidate, ...],
    tag_actions: dict[str, TagAction],
) -> None:
    print("targets:")
    for candidate in candidates:
        action = tag_actions[candidate.target.key]
        print(f"  {candidate.target.display_name}:")
        print(f"    current:  {candidate.current_version}")
        print(f"    release:  {candidate.release_version}")
        print("    status:   unpublished on GitHub Release")
        print(f"    tag:      {candidate.state.tag_name} ({action.action})")
        print(f"    workflow: {candidate.target.release_workflow}")


def _print_dry_run_root_dependency_notes(
    candidates: tuple[ReleaseCandidate, ...],
) -> None:
    if _candidate_for_target(candidates, ROOT_TARGET) is None:
        return
    summon_version = read_manifest_version(SUMMON_TARGET)
    print(
        "dry-run: would ensure root dev dependency requires "
        f"taut-summon>={summon_version}"
    )
    if _candidate_for_target(candidates, SUMMON_TARGET) is None:
        print(
            "dry-run: taut-summon is not in this batch; root still syncs to the "
            "local extension version because publishing is GitHub-only"
        )
    else:
        print(f"dry-run: taut-summon {summon_version} would be released in this batch")


def _sync_root_release_dependencies() -> None:
    summon_dependency_version = sync_root_summon_dev_dependency()
    if summon_dependency_version is None:
        print("Root dev dependency already matches taut-summon")
    else:
        print(f"Updated root dev dependency: taut-summon>={summon_dependency_version}")
    pg_runtime_floor = sync_root_pg_dev_dependency()
    if pg_runtime_floor is None:
        print("Root dev dependency already matches simplebroker-pg")
    else:
        print(f"Updated root dev dependency: simplebroker-pg>={pg_runtime_floor}")
    pg_dependency_version = sync_pg_core_dependency()
    if pg_dependency_version is None:
        print("taut-pg dependency already matches taut")
    else:
        print(f"Updated taut-pg dependency: taut>={pg_dependency_version}")
    core_dependency_version = sync_summon_core_dependency()
    if core_dependency_version is None:
        print("taut-summon dependency already matches taut")
    else:
        print(f"Updated taut-summon dependency: taut>={core_dependency_version}")


def _require_command(name: str) -> None:
    if shutil.which(name) is None:
        fail(f"Required command not found on PATH: {name}")


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare a taut GitHub-only release.")
    target_choices = (*TARGETS, ALL_RELEASE_TARGET_KEY)
    parser.add_argument(
        "target",
        nargs="?",
        choices=target_choices,
        default=None,
        help=(
            "Package to release: core, pg, summon, or all current unpublished "
            "versions. Defaults to core. The root/taut aliases also select core."
        ),
    )
    parser.add_argument(
        "--target",
        dest="target_option",
        choices=target_choices,
        help="Compatibility form for selecting the release target.",
    )
    parser.add_argument(
        "-v",
        "--version",
        help=(
            "Target version in X.Y.Z form. Defaults to the current package "
            "version when it has not been published yet. With all, coordinates "
            "all three package manifests."
        ),
    )
    execution_mode = parser.add_mutually_exclusive_group()
    execution_mode.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the release plan without changing files, tags, or remotes.",
    )
    execution_mode.add_argument(
        "--checks-only",
        action="store_true",
        help=(
            "Run the real precheck commands and exit before version writes, "
            "builds, commits, tags, or pushes."
        ),
    )
    parser.add_argument(
        "--skip-checks",
        action="store_true",
        help=(
            "Explicit human override: skip pytest, ruff, and mypy prechecks. "
            "Artifact build and compatibility gates still run."
        ),
    )
    parser.add_argument(
        "--retag",
        action="store_true",
        help="Replace an existing remote tag if it points at the wrong commit.",
    )
    parser.add_argument(
        "--publish",
        action="store_true",
        help="Compatibility no-op. Taut releases are GitHub-only for now.",
    )
    args = parser.parse_args(argv)

    if args.target_option is not None and args.target is not None:
        if TARGETS.get(args.target_option) != TARGETS.get(args.target):
            parser.error("positional target and --target disagree")
    args.target = args.target_option or args.target or ROOT_TARGET.key
    if args.checks_only and args.skip_checks:
        parser.error("--checks-only cannot be combined with --skip-checks")
    return args


def _dry_run_postupdate_steps(targets: tuple[ReleaseTarget, ...]) -> None:
    for step in build_postupdate_steps_for_targets(targets):
        _run_postupdate_step(step, dry_run=True)


def _run_batch_release(args: argparse.Namespace) -> int:
    if args.checks_only:
        release_targets = tuple(CANONICAL_TARGETS.values())
        if args.version is not None:
            target_version = validate_version(args.version)
            require_changelog_heading(target_version)
        else:
            for target in release_targets:
                require_changelog_heading(read_target_version(target))
        _require_command("uv")
        run_prechecks_for_targets(release_targets, dry_run=False)
        print("Checks passed; no release files, artifacts, tags, or remotes changed.")
        return 0

    dirty = is_dirty_worktree()
    if dirty and not args.dry_run:
        fail("Worktree is dirty; commit or stash changes before releasing")

    candidates = discover_unpublished_releases(requested_version=args.version)
    if not candidates:
        if dirty:
            print("dry-run: worktree is dirty; a real release would stop here")
        if args.publish:
            print_publish_note()
        print("No unpublished release targets found.")
        return 0

    for candidate in candidates:
        require_changelog_heading(candidate.release_version)

    release_targets = _candidate_targets(candidates)
    preparation_targets = (
        BATCH_RELEASE_TARGETS if args.version is not None else release_targets
    )
    if args.version is not None:
        target_version = validate_version(args.version)
        preparation_versions = tuple(
            (target, target_version) for target in preparation_targets
        )
    else:
        preparation_versions = tuple(
            (candidate.target, candidate.release_version) for candidate in candidates
        )
    preparation_branch = "<dry-run>" if args.dry_run else current_branch()
    initial_head_commit = current_head_commit()
    version_change_planned = any(
        candidate.current_version != candidate.release_version
        for candidate in candidates
    )
    planning_head = PENDING_RELEASE_COMMIT if args.dry_run else initial_head_commit
    tag_actions = _plan_candidate_tag_actions(
        candidates,
        head_commit=planning_head,
        version_changed=version_change_planned or args.dry_run,
        retag=args.retag,
    )
    _print_batch_release_plan(candidates, tag_actions)

    if args.dry_run:
        if dirty:
            print("dry-run: worktree is dirty; a real release would stop here")
        if args.publish:
            print_publish_note()
        print(
            "dry-run: would prepare "
            + ", ".join(
                f"{target.package_name} {version}"
                for target, version in preparation_versions
            )
        )
        print("dry-run: would reconcile every manifest-owned derived copy")
        print(
            "dry-run: tag planning assumes reconciliation creates a local commit; "
            "the real command reuses HEAD when preparation is already exact"
        )
        _print_dry_run_root_dependency_notes(candidates)
        run_preparation_steps(preparation_targets, dry_run=True)
        print(
            "dry-run: would create one local preparation commit if generated "
            "release files change"
        )
        run_command(
            ("git", "add", *_release_file_args_for_targets(preparation_targets)),
            dry_run=True,
        )
        run_command(
            ("git", "commit", "-m", _batch_release_commit_message(candidates)),
            dry_run=True,
        )
        if not args.skip_checks:
            run_prechecks_for_targets(preparation_targets, dry_run=True)
        _dry_run_postupdate_steps(release_targets)
        print(
            "dry-run: would revalidate branch, HEAD, clean worktree, GitHub "
            "Release state, and tags before remote actions"
        )
        for candidate in candidates:
            prepare_tag(tag_actions[candidate.target.key], dry_run=True)
        push_current_branch(
            dry_run=True,
            head_commit=PENDING_RELEASE_COMMIT,
        )
        for candidate in candidates:
            push_tag(tag_actions[candidate.target.key], dry_run=True)
        print(
            "dry-run: next step is to wait for release workflows on "
            + ", ".join(candidate.state.tag_name for candidate in candidates)
        )
        return 0

    _require_command("uv")
    if args.publish:
        print_publish_note()

    prepare_release_metadata(preparation_versions)
    run_preparation_steps(preparation_targets, dry_run=False)
    release_commit_created, preparation_commit = commit_release_preparation(
        preparation_targets,
        message=_batch_release_commit_message(candidates),
    )

    if not args.skip_checks:
        run_prechecks_for_targets(preparation_targets, dry_run=False)

    for step in build_postupdate_steps_for_targets(release_targets):
        _run_postupdate_step(step, dry_run=False)

    candidates = require_fresh_release_fence(
        candidates,
        preparation_branch=preparation_branch,
        preparation_commit=preparation_commit,
    )
    tag_actions = _plan_candidate_tag_actions(
        candidates,
        head_commit=preparation_commit,
        version_changed=release_commit_created,
        retag=args.retag,
    )

    for candidate in candidates:
        prepare_tag(tag_actions[candidate.target.key], dry_run=False)
    push_current_branch(
        dry_run=False,
        branch=preparation_branch,
        head_commit=preparation_commit,
    )
    for candidate in candidates:
        push_tag(tag_actions[candidate.target.key], dry_run=False)

    print(
        "Next step: wait for release-gate workflows on "
        + ", ".join(candidate.state.tag_name for candidate in candidates)
        + ". They will create GitHub Releases and upload artifacts."
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.dry_run and not args.checks_only:
        require_publish_branch()
    if args.target == ALL_RELEASE_TARGET_KEY:
        return _run_batch_release(args)

    target = TARGETS[args.target]
    if args.checks_only:
        target_version = validate_version(
            args.version if args.version is not None else read_target_version(target)
        )
        require_changelog_heading(target_version)
        _require_command("uv")
        run_prechecks(target, dry_run=False)
        print("Checks passed; no release files, artifacts, tags, or remotes changed.")
        return 0

    dirty = is_dirty_worktree()
    if dirty and not args.dry_run:
        fail("Worktree is dirty; commit or stash changes before releasing")

    if args.publish:
        print_publish_note()

    current_version, target_version, state = resolve_target_version(
        args.version,
        target,
    )
    require_changelog_heading(target_version)
    version_changed = target_version != current_version
    preparation_branch = "<dry-run>" if args.dry_run else current_branch()
    initial_head_commit = current_head_commit()
    planning_head = PENDING_RELEASE_COMMIT if args.dry_run else initial_head_commit
    tag_action = plan_tag_action(
        state,
        version_changed=version_changed or args.dry_run,
        head_commit=planning_head,
        retag=args.retag,
    )
    print_release_summary(
        current_version=current_version,
        target_version=target_version,
        state=state,
        version_changed=version_changed,
        tag_action=tag_action,
    )

    if args.dry_run:
        if dirty:
            print("dry-run: worktree is dirty; a real release would stop here")
        print(
            "dry-run: would reconcile deterministic release metadata for "
            f"{target.package_name} {target_version}"
        )
        print(
            "dry-run: tag planning assumes reconciliation creates a local commit; "
            "the real command reuses HEAD when preparation is already exact"
        )
        if target == ROOT_TARGET:
            summon_version = read_manifest_version(SUMMON_TARGET)
            print(
                "dry-run: would ensure root dev dependency requires "
                f"taut-summon>={summon_version}"
            )
        run_preparation_steps((target,), dry_run=True)
        print("dry-run: would commit the exact release-file allowlist if changed")
        run_command(("git", "add", *_release_file_args(target)), dry_run=True)
        run_command(
            (
                "git",
                "commit",
                "-m",
                f"Release {target.package_name} {target_version}",
            ),
            dry_run=True,
        )
        if not args.skip_checks:
            run_prechecks(target, dry_run=True)
        run_postupdate_steps(target, dry_run=True)
        print(
            "dry-run: would revalidate branch, HEAD, clean worktree, GitHub "
            "Release state, and tags before remote actions"
        )
        prepare_tag(tag_action, dry_run=True)
        push_current_branch(
            dry_run=True,
            head_commit=PENDING_RELEASE_COMMIT,
        )
        push_tag(tag_action, dry_run=True)
        print(
            f"dry-run: next step is to wait for {target.release_workflow} "
            f"on {state.tag_name}"
        )
        return 0

    _require_command("uv")

    prepare_release_metadata(((target, target_version),))
    run_preparation_steps((target,), dry_run=False)
    release_commit_created, preparation_commit = commit_release_preparation(
        (target,),
        message=f"Release {target.package_name} {target_version}",
    )

    if not args.skip_checks:
        run_prechecks(target, dry_run=False)

    run_postupdate_steps(target, dry_run=False)

    candidate = ReleaseCandidate(
        target=target,
        current_version=current_version,
        release_version=target_version,
        state=state,
    )
    (candidate,) = require_fresh_release_fence(
        (candidate,),
        preparation_branch=preparation_branch,
        preparation_commit=preparation_commit,
    )
    tag_action = plan_tag_action(
        candidate.state,
        version_changed=release_commit_created,
        head_commit=preparation_commit,
        retag=args.retag,
    )
    prepare_tag(tag_action, dry_run=False)
    push_current_branch(
        dry_run=False,
        branch=preparation_branch,
        head_commit=preparation_commit,
    )
    push_tag(tag_action, dry_run=False)
    print(
        f"Next step: wait for {target.release_workflow} on {state.tag_name}. "
        "It will create the GitHub Release and upload artifacts."
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except subprocess.CalledProcessError as exc:
        print(f"error: command failed with exit code {exc.returncode}", file=sys.stderr)
        raise SystemExit(exc.returncode) from exc
