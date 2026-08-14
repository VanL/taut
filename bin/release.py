#!/usr/bin/env python3
"""Repo-local PyPI and GitHub release helper governed by [TAUT-12.5]."""

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
ROOT_UV_LOCK_PATH: Final[Path] = PROJECT_ROOT / "uv.lock"
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
MCP_EXTENSION_DIR: Final[Path] = PROJECT_ROOT / "extensions" / "taut_mcp"
MCP_PYPROJECT_PATH: Final[Path] = MCP_EXTENSION_DIR / "pyproject.toml"
MCP_README_PATH: Final[Path] = MCP_EXTENSION_DIR / "README.md"
MCP_UV_LOCK_PATH: Final[Path] = MCP_EXTENSION_DIR / "uv.lock"
TUI_EXTENSION_DIR: Final[Path] = PROJECT_ROOT / "extensions" / "taut_tui"
TUI_PYPROJECT_PATH: Final[Path] = TUI_EXTENSION_DIR / "pyproject.toml"
TUI_README_PATH: Final[Path] = TUI_EXTENSION_DIR / "README.md"
TUI_UV_LOCK_PATH: Final[Path] = TUI_EXTENSION_DIR / "uv.lock"
RELEASE_DIST_PATHS: Final[tuple[Path, ...]] = (
    PROJECT_ROOT / "dist",
    PG_EXTENSION_DIR / "dist",
    SUMMON_EXTENSION_DIR / "dist",
    MCP_EXTENSION_DIR / "dist",
    TUI_EXTENSION_DIR / "dist",
)
RELEASE_WHEEL_SET_CHECKER: Final[Path] = (
    PROJECT_ROOT / "bin" / "build-and-check-release-wheels.py"
)
WORKFLOW_EVIDENCE_GATE: Final[Path] = (
    PROJECT_ROOT / "bin" / "require-green-workflows.py"
)
CANONICAL_PRODUCER_WORKFLOWS: Final[tuple[tuple[str, str], ...]] = (
    ("root", ".github/workflows/test.yml"),
    ("pg", ".github/workflows/test-pg-extension.yml"),
    ("mcp", ".github/workflows/test-mcp-extension.yml"),
)

ROOT_RELEASE_WORKFLOW: Final[str] = ".github/workflows/release-gate.yml"
PG_RELEASE_WORKFLOW: Final[str] = ".github/workflows/release-gate-pg.yml"
SUMMON_RELEASE_WORKFLOW: Final[str] = ".github/workflows/release-gate-summon.yml"
MCP_RELEASE_WORKFLOW: Final[str] = ".github/workflows/release-gate-mcp.yml"
TUI_RELEASE_WORKFLOW: Final[str] = ".github/workflows/release-gate-tui.yml"
GITHUB_API_BASE: Final[str] = "https://api.github.com"
GITHUB_API_VERSION: Final[str] = "2026-03-10"
PYPI_API_BASE: Final[str] = "https://pypi.org/pypi"
HTTP_TIMEOUT_SECONDS: Final[float] = 15.0
PENDING_RELEASE_COMMIT: Final[str] = "<pending release commit>"
ALL_RELEASE_TARGET_KEY: Final[str] = "all"
PYPI_ENVIRONMENT_TAG_PATTERNS: Final[tuple[tuple[str, str], ...]] = (
    ("tag", "v*"),
    ("tag", "taut_pg/v*"),
    ("tag", "taut_summon/v*"),
    ("tag", "taut_mcp/v*"),
    ("tag", "taut_tui/v*"),
)

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
    r'(?m)^(\s*"taut-chat>=)[^"]+(",\s*)$'
)
TAUT_PG_DEPENDENCY_PATTERN: Final[re.Pattern[str]] = re.compile(
    r'(?m)^(\s*"taut-pg>=)([^"]+)(",\s*)$'
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
MCP_WHEEL_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"taut_mcp-\d+\.\d+\.\d+-py3-none-any\.whl"
)
TUI_WHEEL_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"taut_tui-\d+\.\d+\.\d+-py3-none-any\.whl"
)

UV_RUN_PREFIX: Final[Command] = ("uv", "run", "--no-sync")
PYTEST_PREFIX: Final[Command] = (*UV_RUN_PREFIX, "--extra", "dev", "pytest")
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
PG_TEST_COMMAND: Final[Command] = (*UV_RUN_PREFIX, "./bin/pytest-pg", "--fast")
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
MCP_TEST_COMMAND: Final[Command] = (
    *UV_RUN_PREFIX,
    "--project",
    "extensions/taut_mcp",
    "--extra",
    "dev",
    "--with-editable",
    ".",
    "--with-editable",
    "extensions/taut_mcp",
    "pytest",
    "extensions/taut_mcp/tests",
    "-m",
    "not pg_only",
    "-n",
    "0",
)
TUI_TEST_COMMAND: Final[Command] = (
    *UV_RUN_PREFIX,
    "--project",
    "extensions/taut_tui",
    "--extra",
    "dev",
    "--with-editable",
    ".",
    "--with-editable",
    "extensions/taut_tui",
    "pytest",
    "extensions/taut_tui/tests",
    "-n",
    "0",
)
RUFF_CHECK_PREFIX: Final[Command] = (
    *UV_RUN_PREFIX,
    "--extra",
    "dev",
    "ruff",
    "check",
)
RUFF_FORMAT_PREFIX: Final[Command] = (
    *UV_RUN_PREFIX,
    "--extra",
    "dev",
    "ruff",
    "format",
    "--check",
)
RUFF_SUPPRESSION_CHECK_COMMAND: Final[Command] = (
    *UV_RUN_PREFIX,
    "--extra",
    "dev",
    "python",
    "bin/ruff_suppression_index.py",
    "--check",
)
MYPY_PREFIX: Final[Command] = (*UV_RUN_PREFIX, "--extra", "dev", "mypy")
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
MCP_RUFF_CHECK_COMMAND: Final[Command] = (
    *UV_RUN_PREFIX,
    "--project",
    "extensions/taut_mcp",
    "--extra",
    "dev",
    "ruff",
    "check",
    "extensions/taut_mcp/taut_mcp",
    "extensions/taut_mcp/tests",
)
MCP_RUFF_FORMAT_COMMAND: Final[Command] = (
    *UV_RUN_PREFIX,
    "--project",
    "extensions/taut_mcp",
    "--extra",
    "dev",
    "ruff",
    "format",
    "--check",
    "extensions/taut_mcp/taut_mcp",
    "extensions/taut_mcp/tests",
)
MCP_MYPY_COMMAND: Final[Command] = (
    *UV_RUN_PREFIX,
    "--project",
    "extensions/taut_mcp",
    "--extra",
    "dev",
    "mypy",
    "extensions/taut_mcp/taut_mcp",
    "extensions/taut_mcp/tests",
    "--config-file",
    "extensions/taut_mcp/pyproject.toml",
)
TUI_RUFF_CHECK_COMMAND: Final[Command] = (
    *UV_RUN_PREFIX,
    "--project",
    "extensions/taut_tui",
    "--extra",
    "dev",
    "ruff",
    "check",
    "extensions/taut_tui/taut_tui",
    "extensions/taut_tui/tests",
)
TUI_RUFF_FORMAT_COMMAND: Final[Command] = (
    *UV_RUN_PREFIX,
    "--project",
    "extensions/taut_tui",
    "--extra",
    "dev",
    "ruff",
    "format",
    "--check",
    "extensions/taut_tui/taut_tui",
    "extensions/taut_tui/tests",
)
TUI_MYPY_COMMAND: Final[Command] = (
    *UV_RUN_PREFIX,
    "--project",
    "extensions/taut_tui",
    "--extra",
    "dev",
    "mypy",
    "extensions/taut_tui/taut_tui",
    "extensions/taut_tui/tests",
    "--config-file",
    "extensions/taut_tui/pyproject.toml",
)
PRECHECK_ENV_OVERRIDES: Final[dict[str, str]] = {
    "PYTEST_ADDOPTS": "-x --maxfail=1",
    "TAUT_PG_UV_NO_SYNC": "1",
    "UV_NO_SYNC": "1",
}
LOCAL_LLM_DEFAULT_ENDPOINT: Final[str] = "http://127.0.0.1:11434/v1"
LOCAL_LLM_DEFAULT_MODEL: Final[str] = "taut-summon-local-model:latest"
LOCAL_LLM_DEFAULT_BASE_MODEL: Final[str] = "qwen2.5:0.5b"
LOCAL_LLM_DEFAULT_CONTEXT_LENGTH: Final[str] = "2048"
LOCAL_LLM_DEFAULT_NUM_PREDICT: Final[str] = "64"
# Ollama 0.32.5 includes the GCC 13 AMX fix from ollama/ollama#17244.
LOCAL_LLM_DEFAULT_IMAGE: Final[str] = (
    "ollama/ollama@"
    "sha256:4dea9fb511947e24a84237bb636b0203abcb2ff0d3fbc7b4ff865deb91362131"
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
    release_workflow: str = ""

    @property
    def key(self) -> str:
        return self.name

    @property
    def display_name(self) -> str:
        return self.package_name

    def tag_for_version(self, version: str) -> str:
        if self.tag_namespace is not None:
            return f"{self.tag_namespace}/v{version}"
        return f"v{version}"

    def tag_name(self, version: str) -> str:
        return self.tag_for_version(version)


@dataclass(frozen=True)
class ReleaseState:
    """Observed PyPI, GitHub Release, and tag state for one package version."""

    target: ReleaseTarget
    version: str
    tag_name: str
    github_release_exists: bool
    pypi_release_exists: bool
    local_tag_commit: str | None
    remote_tag_commit: str | None

    @property
    def published(self) -> bool:
        return self.github_release_exists or self.pypi_release_exists


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
    package_name="taut-chat",
    package_dir=Path("."),
    pyproject_path=PYPROJECT_PATH,
    constants_path=CONSTANTS_PATH,
    tag_namespace=None,
    release_workflow=ROOT_RELEASE_WORKFLOW,
)
PG_TARGET: Final[ReleaseTarget] = ReleaseTarget(
    name="pg",
    package_name="taut-pg",
    package_dir=Path("extensions/taut_pg"),
    pyproject_path=PG_PYPROJECT_PATH,
    constants_path=None,
    tag_namespace="taut_pg",
    release_workflow=PG_RELEASE_WORKFLOW,
)
SUMMON_TARGET: Final[ReleaseTarget] = ReleaseTarget(
    name="summon",
    package_name="taut-summon",
    package_dir=Path("extensions/taut_summon"),
    pyproject_path=SUMMON_PYPROJECT_PATH,
    constants_path=None,
    tag_namespace="taut_summon",
    release_workflow=SUMMON_RELEASE_WORKFLOW,
)
MCP_TARGET: Final[ReleaseTarget] = ReleaseTarget(
    name="mcp",
    package_name="taut-mcp",
    package_dir=Path("extensions/taut_mcp"),
    pyproject_path=MCP_PYPROJECT_PATH,
    constants_path=None,
    tag_namespace="taut_mcp",
    release_workflow=MCP_RELEASE_WORKFLOW,
)
TUI_TARGET: Final[ReleaseTarget] = ReleaseTarget(
    name="tui",
    package_name="taut-tui",
    package_dir=Path("extensions/taut_tui"),
    pyproject_path=TUI_PYPROJECT_PATH,
    constants_path=None,
    tag_namespace="taut_tui",
    release_workflow=TUI_RELEASE_WORKFLOW,
)
TARGETS: Final[dict[str, ReleaseTarget]] = {
    "core": ROOT_TARGET,
    "root": ROOT_TARGET,
    "taut": ROOT_TARGET,
    "pg": PG_TARGET,
    "summon": SUMMON_TARGET,
    "mcp": MCP_TARGET,
    "tui": TUI_TARGET,
}
CANONICAL_TARGETS: Final[dict[str, ReleaseTarget]] = {
    "core": ROOT_TARGET,
    "pg": PG_TARGET,
    "summon": SUMMON_TARGET,
    "mcp": MCP_TARGET,
    "tui": TUI_TARGET,
}
BATCH_RELEASE_TARGETS: Final[tuple[ReleaseTarget, ...]] = (
    PG_TARGET,
    SUMMON_TARGET,
    MCP_TARGET,
    TUI_TARGET,
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


def _replace_existing_examples(
    path: Path, pattern: re.Pattern[str], replacement: str
) -> None:
    text = path.read_text(encoding="utf-8")
    updated = pattern.sub(replacement, text)
    if updated != text:
        path.write_text(updated, encoding="utf-8")


def sync_readme_version_examples(
    target: ReleaseTarget,
    version: str,
    *,
    root_readme_path: Path = ROOT_README_PATH,
    pg_readme_path: Path = PG_README_PATH,
    summon_readme_path: Path = SUMMON_README_PATH,
    mcp_readme_path: Path = MCP_README_PATH,
    tui_readme_path: Path = TUI_README_PATH,
) -> None:
    normalized = validate_version(version)
    if target == ROOT_TARGET:
        for path in (
            root_readme_path,
            pg_readme_path,
            summon_readme_path,
            mcp_readme_path,
            tui_readme_path,
        ):
            _replace_existing_examples(path, CORE_README_TAG_PATTERN, f"@v{normalized}")
        return
    artifact = {
        PG_TARGET: (PG_WHEEL_PATTERN, "taut_pg", pg_readme_path),
        SUMMON_TARGET: (SUMMON_WHEEL_PATTERN, "taut_summon", summon_readme_path),
        MCP_TARGET: (MCP_WHEEL_PATTERN, "taut_mcp", mcp_readme_path),
        TUI_TARGET: (TUI_WHEEL_PATTERN, "taut_tui", tui_readme_path),
    }.get(target)
    if artifact is None:
        return
    pattern, wheel_prefix, extension_readme_path = artifact
    replacement = f"{wheel_prefix}-{normalized}-py3-none-any.whl"
    for path in (root_readme_path, extension_readme_path):
        _replace_existing_examples(path, pattern, replacement)


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
    if target in {ROOT_TARGET, PG_TARGET, SUMMON_TARGET, MCP_TARGET, TUI_TARGET}:
        sync_readme_version_examples(target, normalized)
    if target in (
        PG_TARGET,
        SUMMON_TARGET,
        MCP_TARGET,
        TUI_TARGET,
    ) or target.package_name in {
        "taut-pg",
        "taut-summon",
        "taut-mcp",
        "taut-tui",
    }:
        root_version = read_manifest_version(ROOT_TARGET)
        _replace_version(
            target.pyproject_path,
            TAUT_DEPENDENCY_PATTERN,
            rf"\g<1>{root_version}\g<2>",
            f"{display_path(target.pyproject_path)} taut-chat dependency",
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
    updated, changed = _replace_optional_dependency_floor(
        text,
        extra="dev",
        package="taut-summon",
        version=summon_version,
    )
    if not changed:
        return None
    root_pyproject_path.write_text(updated, encoding="utf-8")
    return summon_version


def sync_root_tui_dependencies(
    *,
    root_pyproject_path: Path = PYPROJECT_PATH,
    tui_pyproject_path: Path = TUI_PYPROJECT_PATH,
) -> dict[str, str]:
    """Set root TUI convenience and development floors from ``taut-tui``."""

    version = _read_version(
        tui_pyproject_path,
        PYPROJECT_VERSION_PATTERN,
        display_path(tui_pyproject_path),
    )
    text = root_pyproject_path.read_text(encoding="utf-8")
    updated_extras: dict[str, str] = {}
    for extra in ("dev", "tui"):
        text, changed = _replace_optional_dependency_floor(
            text,
            extra=extra,
            package="taut-tui",
            version=version,
        )
        if changed:
            updated_extras[extra] = version
    if updated_extras:
        root_pyproject_path.write_text(text, encoding="utf-8")
    return updated_extras


def _replace_optional_dependency_floor(
    text: str,
    *,
    extra: str,
    package: str,
    version: str,
) -> tuple[str, bool]:
    section_marker = "[project.optional-dependencies]"
    section_start = text.find(section_marker)
    if section_start < 0:
        fail("Could not find [project.optional-dependencies] in root pyproject.toml")
    section_end = text.find("\n[", section_start + len(section_marker))
    if section_end < 0:
        section_end = len(text)
    section = text[section_start:section_end]
    extra_pattern = re.compile(
        rf"(?ms)^{re.escape(extra)}\s*=\s*\[\s*\n(?P<body>.*?)^\]\s*$"
    )
    extra_match = extra_pattern.search(section)
    if extra_match is None:
        fail(f"Could not find {extra!r} optional dependency extra")
    body = extra_match.group("body")
    dependency_pattern = re.compile(
        rf'(?m)^(\s*"{re.escape(package)}>=)([^"]+)(",\s*)$'
    )
    updated_body, count = dependency_pattern.subn(
        rf"\g<1>{version}\g<3>",
        body,
        count=1,
    )
    if count != 1:
        fail(f"Expected one {package} dependency in root {extra} extra")
    if updated_body == body:
        return text, False
    body_start = section_start + extra_match.start("body")
    body_end = section_start + extra_match.end("body")
    return f"{text[:body_start]}{updated_body}{text[body_end:]}", True


def sync_root_all_dependencies(
    *,
    root_pyproject_path: Path = PYPROJECT_PATH,
    pg_pyproject_path: Path = PG_PYPROJECT_PATH,
    summon_pyproject_path: Path = SUMMON_PYPROJECT_PATH,
    mcp_pyproject_path: Path = MCP_PYPROJECT_PATH,
    tui_pyproject_path: Path = TUI_PYPROJECT_PATH,
) -> dict[str, str]:
    """Set each root all-extra floor from its owning extension manifest."""

    owners = (
        ("taut-pg", pg_pyproject_path),
        ("taut-summon", summon_pyproject_path),
        ("taut-mcp", mcp_pyproject_path),
        ("taut-tui", tui_pyproject_path),
    )
    text = root_pyproject_path.read_text(encoding="utf-8")
    updated_packages: dict[str, str] = {}
    for package, manifest_path in owners:
        version = _read_version(
            manifest_path,
            PYPROJECT_VERSION_PATTERN,
            display_path(manifest_path),
        )
        text, changed = _replace_optional_dependency_floor(
            text,
            extra="all",
            package=package,
            version=version,
        )
        if changed:
            updated_packages[package] = version
    if updated_packages:
        root_pyproject_path.write_text(text, encoding="utf-8")
    return updated_packages


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


def sync_mcp_core_dependency(
    *,
    root_pyproject_path: Path = PYPROJECT_PATH,
    mcp_pyproject_path: Path = MCP_PYPROJECT_PATH,
) -> str | None:
    """Set MCP's taut floor to the exact local core version."""

    return sync_extension_core_dependency(
        root_pyproject_path=root_pyproject_path,
        extension_pyproject_path=mcp_pyproject_path,
        extension_label="taut-mcp",
    )


def sync_tui_core_dependency(
    *,
    root_pyproject_path: Path = PYPROJECT_PATH,
    tui_pyproject_path: Path = TUI_PYPROJECT_PATH,
) -> str | None:
    """Set TUI's taut floor to the exact local core version."""

    return sync_extension_core_dependency(
        root_pyproject_path=root_pyproject_path,
        extension_pyproject_path=tui_pyproject_path,
        extension_label="taut-tui",
    )


def sync_mcp_pg_dev_dependency(
    *,
    pg_pyproject_path: Path = PG_PYPROJECT_PATH,
    mcp_pyproject_path: Path = MCP_PYPROJECT_PATH,
) -> str | None:
    """Set MCP's development-only taut-pg floor to the local PG version."""

    pg_version = _read_version(
        pg_pyproject_path,
        PYPROJECT_VERSION_PATTERN,
        display_path(pg_pyproject_path),
    )
    text = mcp_pyproject_path.read_text(encoding="utf-8")
    updated, count = TAUT_PG_DEPENDENCY_PATTERN.subn(
        rf"\g<1>{pg_version}\g<3>", text, count=1
    )
    if count != 1:
        fail(
            "Expected one taut-pg development dependency in "
            f"{display_path(mcp_pyproject_path)}"
        )
    if updated == text:
        return None
    mcp_pyproject_path.write_text(updated, encoding="utf-8")
    return pg_version


def sync_mcp_summon_dev_dependency(
    *,
    summon_pyproject_path: Path = SUMMON_PYPROJECT_PATH,
    mcp_pyproject_path: Path = MCP_PYPROJECT_PATH,
) -> str | None:
    """Set MCP's development-only Summon floor to the local version."""

    summon_version = _read_version(
        summon_pyproject_path,
        PYPROJECT_VERSION_PATTERN,
        display_path(summon_pyproject_path),
    )
    text = mcp_pyproject_path.read_text(encoding="utf-8")
    updated, changed = _replace_optional_dependency_floor(
        text,
        extra="dev",
        package="taut-summon",
        version=summon_version,
    )
    if not changed:
        return None
    mcp_pyproject_path.write_text(updated, encoding="utf-8")
    return summon_version


def sync_tui_summon_dev_dependency(
    *,
    summon_pyproject_path: Path = SUMMON_PYPROJECT_PATH,
    tui_pyproject_path: Path = TUI_PYPROJECT_PATH,
) -> str | None:
    """Set TUI's development-only Summon floor to the local version."""

    summon_version = _read_version(
        summon_pyproject_path,
        PYPROJECT_VERSION_PATTERN,
        display_path(summon_pyproject_path),
    )
    text = tui_pyproject_path.read_text(encoding="utf-8")
    updated, changed = _replace_optional_dependency_floor(
        text,
        extra="dev",
        package="taut-summon",
        version=summon_version,
    )
    if not changed:
        return None
    tui_pyproject_path.write_text(updated, encoding="utf-8")
    return summon_version


def sync_pg_tui_dev_dependency(
    *,
    pg_pyproject_path: Path = PG_PYPROJECT_PATH,
    tui_pyproject_path: Path = TUI_PYPROJECT_PATH,
) -> str | None:
    """Set PG's development-only TUI floor to the local version."""

    tui_version = _read_version(
        tui_pyproject_path,
        PYPROJECT_VERSION_PATTERN,
        display_path(tui_pyproject_path),
    )
    text = pg_pyproject_path.read_text(encoding="utf-8")
    updated, changed = _replace_optional_dependency_floor(
        text,
        extra="dev",
        package="taut-tui",
        version=tui_version,
    )
    if not changed:
        return None
    pg_pyproject_path.write_text(updated, encoding="utf-8")
    return tui_version


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
            f"Could not update {extension_label} taut-chat dependency in "
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
    ordered_targets = (ROOT_TARGET, PG_TARGET, SUMMON_TARGET, MCP_TARGET, TUI_TARGET)
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
        except BaseException as exc:  # noqa: BLE001 approved [DOM-10.2.1] [RUFF-SUP-069] exception
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


def release_observer_token() -> str:
    """Resolve local observer auth without exposing the credential."""

    supplied = os.environ.get("GITHUB_TOKEN", "").strip()
    if supplied:
        return supplied
    _require_command("gh")
    token = capture_command(("gh", "auth", "token"))
    if not token:
        fail("gh auth token returned no GitHub credential")
    return token


def wait_for_canonical_workflows(*, head_commit: str, token: str) -> None:
    """Wait for exact-SHA producer evidence without logging its credential."""

    repository = github_repo_slug_from_remote(origin_remote_url())
    if repository is None:
        fail("Origin remote is not a GitHub repository")
    command: Command = (
        sys.executable,
        str(WORKFLOW_EVIDENCE_GATE),
        "wait-workflows",
        *(
            part
            for key, path in CANONICAL_PRODUCER_WORKFLOWS
            for part in ("--workflow", f"{key}={path}")
        ),
    )
    print(f"+ {format_command(command)}", flush=True)
    child_env = os.environ.copy()
    child_env.update(
        {
            "GITHUB_TOKEN": token,
            "GITHUB_REPOSITORY": repository,
            "GITHUB_SHA": head_commit,
        }
    )
    subprocess.run(command, cwd=PROJECT_ROOT, check=True, env=child_env)


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

    path = path.removesuffix(".git")
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
        "X-GitHub-Api-Version": GITHUB_API_VERSION,
    }
    token = _github_api_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def github_release_exists(tag_name: str) -> bool:
    slug = github_repo_slug_from_remote(origin_remote_url())
    if slug is None:
        fail("Origin remote is not a GitHub repository")

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
    except (UnicodeDecodeError, json.JSONDecodeError):
        fail(f"GitHub release lookup failed for {tag_name}: invalid JSON")

    if not isinstance(data, dict) or data.get("tag_name") != tag_name:
        fail(f"GitHub release lookup failed for {tag_name}: unexpected response")
    return True


def _normalized_package_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def pypi_version_exists(package_name: str, version: str) -> bool:
    """Return whether PyPI already contains the exact package version."""

    encoded_package = urllib.parse.quote(package_name, safe="")
    encoded_version = urllib.parse.quote(version, safe="")
    url = f"{PYPI_API_BASE}/{encoded_package}/{encoded_version}/json"
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "taut-release-helper",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
            data: object = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return False
        fail(
            f"PyPI release lookup failed for {package_name} {version}: HTTP {exc.code}"
        )
    except urllib.error.URLError as exc:
        fail(f"PyPI release lookup failed for {package_name} {version}: {exc.reason}")
    except (UnicodeDecodeError, json.JSONDecodeError):
        fail(f"PyPI release lookup failed for {package_name} {version}: invalid JSON")

    if not isinstance(data, dict):
        fail(
            f"PyPI release lookup failed for {package_name} {version}: "
            "unexpected response"
        )
    info = data.get("info")
    if not isinstance(info, dict):
        fail(
            f"PyPI release lookup failed for {package_name} {version}: "
            "missing project info"
        )
    observed_name = info.get("name")
    observed_version = info.get("version")
    if (
        not isinstance(observed_name, str)
        or _normalized_package_name(observed_name)
        != _normalized_package_name(package_name)
        or observed_version != version
    ):
        fail(
            f"PyPI release lookup failed for {package_name} {version}: "
            "project identity mismatch"
        )
    return True


def _github_api_json(path: str, token: str) -> object:
    if not path.startswith("/"):
        raise RuntimeError("GitHub API path must start with /")
    request = urllib.request.Request(
        f"{GITHUB_API_BASE}{path}",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "taut-release-helper",
            "X-GitHub-Api-Version": GITHUB_API_VERSION,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(
            f"GitHub API request failed for {path}: HTTP {exc.code}"
        ) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(
            f"GitHub API request failed for {path}: {exc.reason}"
        ) from exc
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            f"GitHub API request failed for {path}: invalid JSON"
        ) from exc


def _setting_payload(
    *,
    label: str,
    path: str,
    token: str,
    issues: list[str],
) -> object | None:
    try:
        return _github_api_json(path, token)
    except RuntimeError as exc:
        issues.append(f"{label} could not be verified: {exc}")
        return None


def repository_settings_issues(repo_slug: str, token: str) -> tuple[str, ...]:
    """Return release-blocking GitHub repository-setting issues."""

    issues: list[str] = []
    encoded_repo = urllib.parse.quote(repo_slug, safe="/")
    base = f"/repos/{encoded_repo}"

    immutable = _setting_payload(
        label="immutable releases",
        path=f"{base}/immutable-releases",
        token=token,
        issues=issues,
    )
    if immutable is not None and (
        not isinstance(immutable, dict) or immutable.get("enabled") is not True
    ):
        issues.append("immutable releases must be enabled")

    environment = _setting_payload(
        label="pypi environment policy",
        path=f"{base}/environments/pypi",
        token=token,
        issues=issues,
    )
    deployment_policy: object = None
    if isinstance(environment, dict):
        deployment_policy = environment.get("deployment_branch_policy")
    if environment is not None and (
        not isinstance(deployment_policy, dict)
        or deployment_policy.get("protected_branches") is not False
        or deployment_policy.get("custom_branch_policies") is not True
    ):
        issues.append("pypi environment must use custom tag policies only")

    policies = _setting_payload(
        label="pypi environment tag policies",
        path=f"{base}/environments/pypi/deployment-branch-policies",
        token=token,
        issues=issues,
    )
    observed: set[tuple[str, str]] = set()
    raw_policies = (
        policies.get("branch_policies") if isinstance(policies, dict) else None
    )
    policy_records_valid = isinstance(raw_policies, list) and len(raw_policies) == len(
        PYPI_ENVIRONMENT_TAG_PATTERNS
    )
    if isinstance(raw_policies, list):
        for raw_policy in raw_policies:
            if not isinstance(raw_policy, dict):
                policy_records_valid = False
                continue
            policy_type = raw_policy.get("type")
            name = raw_policy.get("name")
            if isinstance(policy_type, str) and isinstance(name, str):
                before = len(observed)
                observed.add((policy_type, name))
                if len(observed) == before:
                    policy_records_valid = False
            else:
                policy_records_valid = False
    if policies is not None and (
        not policy_records_valid or observed != set(PYPI_ENVIRONMENT_TAG_PATTERNS)
    ):
        issues.append(
            "pypi environment tag policies must be exactly v*, taut_pg/v*, "
            "taut_summon/v*, taut_mcp/v*, and taut_tui/v*"
        )

    return tuple(issues)


def require_repository_settings() -> None:
    """Fail closed unless GitHub release settings match [TAUT-12.5]."""

    token = _github_api_token()
    if not token:
        fail("Authenticated GitHub access is required to verify repository settings")
    remote_url = origin_remote_url()
    repo_slug = github_repo_slug_from_remote(remote_url)
    if repo_slug is None:
        fail(f"Unable to determine GitHub repository from origin remote: {remote_url}")
    issues = repository_settings_issues(repo_slug, token)
    if issues:
        fail("Repository settings are not ready for release:\n- " + "\n- ".join(issues))
    print("repository setting ok: immutable releases enabled")
    print("repository setting ok: pypi accepts only release tags")


def inspect_release_state(target: ReleaseTarget, version: str) -> ReleaseState:
    normalized = validate_version(version)
    tag_name = target.tag_for_version(normalized)
    github_exists = github_release_exists(tag_name)
    pypi_exists = pypi_version_exists(target.package_name, normalized)
    return ReleaseState(
        target=target,
        version=normalized,
        tag_name=tag_name,
        github_release_exists=github_exists,
        pypi_release_exists=pypi_exists,
        local_tag_commit=local_tag_commit(tag_name),
        remote_tag_commit=remote_tag_commit(tag_name),
    )


def published_destinations(state: ReleaseState) -> str:
    destinations: list[str] = []
    if state.github_release_exists:
        destinations.append("GitHub Release")
    if state.pypi_release_exists:
        destinations.append("PyPI publication")
    return " and ".join(destinations) or "nowhere"


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
        destinations = published_destinations(state)
        if requested_version is None:
            fail(
                f"Current {target.package_name} version {current_version} already "
                f"has a {destinations}; pass --version with a new version"
            )
        fail(
            f"{target.package_name} {target_version} already has a "
            f"{destinations}; choose a new version"
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

    format_paths = _unique_strings(
        (*ROOT_TOOL_PATHS, *PG_TOOL_PATHS, *SUMMON_TOOL_PATHS)
    )
    return (
        *ROOT_TEST_COMMANDS,
        PG_TEST_COMMAND,
        *SUMMON_TEST_COMMANDS,
        MCP_TEST_COMMAND,
        TUI_TEST_COMMAND,
        _ruff_check_command((".",)),
        RUFF_SUPPRESSION_CHECK_COMMAND,
        _ruff_format_command(format_paths),
        MCP_RUFF_CHECK_COMMAND,
        MCP_RUFF_FORMAT_COMMAND,
        TUI_RUFF_CHECK_COMMAND,
        TUI_RUFF_FORMAT_COMMAND,
        _mypy_command(ROOT_MYPY_PATHS),
        _mypy_command(PG_MYPY_PATHS),
        _mypy_command(SUMMON_MYPY_PATHS),
        MCP_MYPY_COMMAND,
        TUI_MYPY_COMMAND,
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
            ("uv", "lock"),
            "Reconcile root all-extra and development dependencies",
            cwd=PROJECT_ROOT,
        ),
        CommandStep(
            ("uv", "lock", "--upgrade-package", "simplebroker"),
            "Refresh retained taut-summon dependencies selectively",
            cwd=SUMMON_EXTENSION_DIR,
        ),
        CommandStep(
            ("uv", "lock"),
            "Reconcile retained taut-mcp dependencies",
            cwd=MCP_EXTENSION_DIR,
        ),
        CommandStep(
            ("uv", "lock"),
            "Reconcile retained taut-tui dependencies",
            cwd=TUI_EXTENSION_DIR,
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
        steps.append(
            CommandStep(
                ("uv", "build", "--no-sources", "--out-dir", "dist", "."),
                "Build taut source and wheel",
            )
        )
    if PG_TARGET.key in target_keys:
        steps.append(
            CommandStep(
                (
                    "uv",
                    "build",
                    "--no-sources",
                    "--out-dir",
                    (PG_TARGET.package_dir / "dist").as_posix(),
                    PG_TARGET.package_dir.as_posix(),
                ),
                "Build taut-pg source and wheel",
            )
        )
    if SUMMON_TARGET.key in target_keys:
        steps.append(
            CommandStep(
                (
                    "uv",
                    "build",
                    "--no-sources",
                    "--out-dir",
                    (SUMMON_TARGET.package_dir / "dist").as_posix(),
                    SUMMON_TARGET.package_dir.as_posix(),
                ),
                "Build taut-summon source and wheel",
            )
        )
    if MCP_TARGET.key in target_keys:
        steps.append(
            CommandStep(
                (
                    "uv",
                    "build",
                    "--no-sources",
                    "--out-dir",
                    (MCP_TARGET.package_dir / "dist").as_posix(),
                    MCP_TARGET.package_dir.as_posix(),
                ),
                "Build taut-mcp source and wheel",
            )
        )
    if TUI_TARGET.key in target_keys:
        steps.append(
            CommandStep(
                (
                    "uv",
                    "build",
                    "--no-sources",
                    "--out-dir",
                    (TUI_TARGET.package_dir / "dist").as_posix(),
                    TUI_TARGET.package_dir.as_posix(),
                ),
                "Build taut-tui source and wheel",
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


def empty_release_dist_directories(
    *,
    dry_run: bool,
    dist_paths: tuple[Path, ...] | None = None,
) -> None:
    """Keep every package dist directory present and empty before building."""

    paths = RELEASE_DIST_PATHS if dist_paths is None else dist_paths
    for dist_path in paths:
        print(f"Empty release artifact directory: {display_path(dist_path)}")
        if dist_path.is_symlink():
            fail(f"Release artifact directory must not be a symlink: {dist_path}")
        if dist_path.exists() and not dist_path.is_dir():
            fail(f"Release artifact path is not a directory: {dist_path}")
        if dry_run:
            continue
        dist_path.mkdir(parents=True, exist_ok=True)
        for entry in tuple(dist_path.iterdir()):
            if entry.is_symlink() or not entry.is_dir():
                entry.unlink(missing_ok=True)
            else:
                try:
                    shutil.rmtree(entry)
                except FileNotFoundError:
                    pass
        if tuple(dist_path.iterdir()):
            fail(f"Release artifact directory is not empty: {dist_path}")


def run_postupdate_steps_for_targets(
    targets: tuple[ReleaseTarget, ...], *, dry_run: bool
) -> None:
    steps = build_postupdate_steps_for_targets(targets)
    if not steps:
        return
    empty_release_dist_directories(dry_run=dry_run)
    for step in steps:
        _run_postupdate_step(step, dry_run=dry_run)


def run_postupdate_steps(target: ReleaseTarget, *, dry_run: bool) -> None:
    run_postupdate_steps_for_targets((target,), dry_run=dry_run)


def run_preparation_steps(targets: tuple[ReleaseTarget, ...], *, dry_run: bool) -> None:
    for step in build_preparation_steps_for_targets(targets):
        _run_postupdate_step(step, dry_run=dry_run)


def _release_file_paths(_target: ReleaseTarget) -> tuple[Path, ...]:
    paths = [
        PYPROJECT_PATH,
        ROOT_UV_LOCK_PATH,
        CONSTANTS_PATH,
        ROOT_README_PATH,
        PG_PYPROJECT_PATH,
        PG_README_PATH,
        SUMMON_PYPROJECT_PATH,
        SUMMON_README_PATH,
        MCP_PYPROJECT_PATH,
        MCP_README_PATH,
        TUI_PYPROJECT_PATH,
        TUI_README_PATH,
    ]
    if SUMMON_UV_LOCK_PATH.exists():
        paths.append(SUMMON_UV_LOCK_PATH)
    if MCP_UV_LOCK_PATH.exists():
        paths.append(MCP_UV_LOCK_PATH)
    if TUI_UV_LOCK_PATH.exists():
        paths.append(TUI_UV_LOCK_PATH)
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


def plan_tag_action(  # noqa: C901 approved [DOM-10.2.1] [RUFF-SUP-008] exception
    state: ReleaseState,
    *,
    version_changed: bool,
    head_commit: str,
    retag: bool = False,
    allow_retag: bool | None = None,
) -> TagAction:
    if allow_retag is not None:
        retag = allow_retag
    if state.published:
        fail(
            f"{state.target.package_name} {state.version} is already published via "
            f"{published_destinations(state)}; choose a new version"
        )

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
    print(f"PyPI publication exists: {'yes' if state.pypi_release_exists else 'no'}")
    print(f"Local tag commit: {state.local_tag_commit or '<missing>'}")
    print(f"Remote tag commit: {state.remote_tag_commit or '<missing>'}")
    print(f"Tag action: {describe_tag_action(tag_action)}")
    print("Tag workflow publishes: PyPI and immutable GitHub Release")


def print_publish_note() -> None:
    print(
        "--publish is ignored: tag-push release-gate workflows publish the exact "
        "tested artifacts to PyPI and an immutable GitHub Release."
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
                f"became published via {published_destinations(state)} during "
                "local checks; no remote release action ran"
            )
        refreshed.append(replace(candidate, state=state))
    return tuple(refreshed)


def require_release_states_unchanged(
    expected: tuple[ReleaseCandidate, ...],
    observed: tuple[ReleaseCandidate, ...],
) -> None:
    """Reject tag or publication drift across exact-SHA observation."""

    expected_states = {candidate.target.key: candidate.state for candidate in expected}
    observed_states = {candidate.target.key: candidate.state for candidate in observed}
    if expected_states.keys() != observed_states.keys():
        fail("Release target set changed during canonical workflow observation")
    for key, expected_state in expected_states.items():
        observed_state = observed_states[key]
        if observed_state != expected_state:
            fail(
                f"Release state for {expected_state.target.package_name} changed "
                "during canonical workflow observation; no tag action ran"
            )


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
        print("    status:   unpublished on GitHub Release and PyPI")
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
            "local extension version because dependency metadata is coordinated"
        )
    else:
        print(f"dry-run: taut-summon {summon_version} would be released in this batch")
    all_floors = ", ".join(
        f"{target.package_name}>={read_manifest_version(target)}"
        for target in (PG_TARGET, SUMMON_TARGET, MCP_TARGET, TUI_TARGET)
    )
    print(f"dry-run: would ensure root all extra requires {all_floors}")


def _report_dependency_sync(
    version: str | None,
    *,
    current: str,
    updated: str,
) -> None:
    if version is None:
        print(current)
    else:
        print(f"{updated}{version}")


def _sync_root_release_dependencies() -> None:
    summon_dependency_version = sync_root_summon_dev_dependency()
    _report_dependency_sync(
        summon_dependency_version,
        current="Root dev dependency already matches taut-summon",
        updated="Updated root dev dependency: taut-summon>=",
    )
    pg_runtime_floor = sync_root_pg_dev_dependency()
    _report_dependency_sync(
        pg_runtime_floor,
        current="Root dev dependency already matches simplebroker-pg",
        updated="Updated root dev dependency: simplebroker-pg>=",
    )
    all_updates = sync_root_all_dependencies()
    if not all_updates:
        print("Root all extra already matches first-party extension versions")
    else:
        updates = ", ".join(
            f"{package}>={version}" for package, version in all_updates.items()
        )
        print(f"Updated root all extra: {updates}")
    tui_root_updates = sync_root_tui_dependencies()
    if not tui_root_updates:
        print("Root TUI and dev extras already match taut-tui")
    else:
        extras = ", ".join(sorted(tui_root_updates))
        print(
            f"Updated root {extras} extras: taut-tui>={next(iter(tui_root_updates.values()))}"
        )
    pg_dependency_version = sync_pg_core_dependency()
    _report_dependency_sync(
        pg_dependency_version,
        current="taut-pg dependency already matches taut-chat",
        updated="Updated taut-pg dependency: taut-chat>=",
    )
    core_dependency_version = sync_summon_core_dependency()
    _report_dependency_sync(
        core_dependency_version,
        current="taut-summon dependency already matches taut-chat",
        updated="Updated taut-summon dependency: taut-chat>=",
    )
    mcp_core_version = sync_mcp_core_dependency()
    _report_dependency_sync(
        mcp_core_version,
        current="taut-mcp dependency already matches taut-chat",
        updated="Updated taut-mcp dependency: taut-chat>=",
    )
    tui_core_version = sync_tui_core_dependency()
    _report_dependency_sync(
        tui_core_version,
        current="taut-tui dependency already matches taut-chat",
        updated="Updated taut-tui dependency: taut-chat>=",
    )
    mcp_pg_version = sync_mcp_pg_dev_dependency()
    _report_dependency_sync(
        mcp_pg_version,
        current="taut-mcp development dependency already matches taut-pg",
        updated="Updated taut-mcp development dependency: taut-pg>=",
    )
    mcp_summon_version = sync_mcp_summon_dev_dependency()
    _report_dependency_sync(
        mcp_summon_version,
        current="taut-mcp development dependency already matches taut-summon",
        updated="Updated taut-mcp development dependency: taut-summon>=",
    )
    tui_summon_version = sync_tui_summon_dev_dependency()
    _report_dependency_sync(
        tui_summon_version,
        current="taut-tui development dependency already matches taut-summon",
        updated="Updated taut-tui development dependency: taut-summon>=",
    )
    pg_tui_version = sync_pg_tui_dev_dependency()
    _report_dependency_sync(
        pg_tui_version,
        current="taut-pg development dependency already matches taut-tui",
        updated="Updated taut-pg development dependency: taut-tui>=",
    )


def _require_command(name: str) -> None:
    if shutil.which(name) is None:
        fail(f"Required command not found on PATH: {name}")


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare a Taut package release.")
    target_choices = (*TARGETS, ALL_RELEASE_TARGET_KEY)
    parser.add_argument(
        "target",
        nargs="?",
        choices=target_choices,
        default=None,
        help=(
            "Package to release: core, pg, summon, mcp, tui, or all current "
            "unpublished versions. Defaults to core. The root/taut aliases also "
            "select core."
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
            "all five package manifests."
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
        help=("Compatibility no-op. Tag workflows publish to PyPI and GitHub."),
    )
    parser.add_argument(
        "--check-repository-settings",
        action="store_true",
        help=(
            "Read and verify immutable-release and PyPI-environment settings, "
            "then exit."
        ),
    )
    args = parser.parse_args(argv)

    if (
        args.target_option is not None
        and args.target is not None
        and TARGETS.get(args.target_option) != TARGETS.get(args.target)
    ):
        parser.error("positional target and --target disagree")
    args.target = args.target_option or args.target or ROOT_TARGET.key
    if args.checks_only and args.skip_checks:
        parser.error("--checks-only cannot be combined with --skip-checks")
    return args


def _dry_run_postupdate_steps(targets: tuple[ReleaseTarget, ...]) -> None:
    run_postupdate_steps_for_targets(targets, dry_run=True)


@dataclass(frozen=True)
class _BatchPreparationPlan:
    candidates: tuple[ReleaseCandidate, ...]
    release_targets: tuple[ReleaseTarget, ...]
    preparation_targets: tuple[ReleaseTarget, ...]
    preparation_versions: tuple[tuple[ReleaseTarget, str], ...]
    preparation_branch: str
    tag_actions: dict[str, TagAction]


def _plan_batch_preparation(
    args: argparse.Namespace,
    candidates: tuple[ReleaseCandidate, ...],
) -> _BatchPreparationPlan:
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
    return _BatchPreparationPlan(
        candidates=candidates,
        release_targets=release_targets,
        preparation_targets=preparation_targets,
        preparation_versions=preparation_versions,
        preparation_branch=preparation_branch,
        tag_actions=tag_actions,
    )


def _run_dry_batch_release(
    args: argparse.Namespace,
    plan: _BatchPreparationPlan,
    *,
    dirty: bool,
) -> int:
    if dirty:
        print("dry-run: worktree is dirty; a real release would stop here")
    if args.publish:
        print_publish_note()
    print(
        "dry-run: would prepare "
        + ", ".join(
            f"{target.package_name} {version}"
            for target, version in plan.preparation_versions
        )
    )
    print("dry-run: would reconcile every manifest-owned derived copy")
    print(
        "dry-run: tag planning assumes reconciliation creates a local commit; "
        "the real command reuses HEAD when preparation is already exact"
    )
    _print_dry_run_root_dependency_notes(plan.candidates)
    run_preparation_steps(plan.preparation_targets, dry_run=True)
    print(
        "dry-run: would create one local preparation commit if generated "
        "release files change"
    )
    run_command(
        ("git", "add", *_release_file_args_for_targets(plan.preparation_targets)),
        dry_run=True,
    )
    run_command(
        ("git", "commit", "-m", _batch_release_commit_message(plan.candidates)),
        dry_run=True,
    )
    if not args.skip_checks:
        run_prechecks_for_targets(plan.preparation_targets, dry_run=True)
    _dry_run_postupdate_steps(plan.release_targets)
    print(
        "dry-run: would revalidate branch, HEAD, clean worktree, GitHub "
        "Release and PyPI state, and tags before remote actions"
    )
    push_current_branch(
        dry_run=True,
        head_commit=PENDING_RELEASE_COMMIT,
    )
    print(
        "dry-run: would resolve GitHub auth, wait for exact-SHA root, PG, and "
        "MCP producer workflows, then recheck repository settings and the full "
        "release fence"
    )
    for candidate in plan.candidates:
        prepare_tag(plan.tag_actions[candidate.target.key], dry_run=True)
    for candidate in plan.candidates:
        push_tag(plan.tag_actions[candidate.target.key], dry_run=True)
    print(
        "dry-run: next step is to wait for release workflows on "
        + ", ".join(candidate.state.tag_name for candidate in plan.candidates)
    )
    return 0


def _run_batch_checks(args: argparse.Namespace) -> int:
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


def _run_batch_release(  # noqa: C901 approved [DOM-10.2.1] [RUFF-SUP-063] exception
    args: argparse.Namespace,
) -> int:
    if args.checks_only:
        return _run_batch_checks(args)

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

    plan = _plan_batch_preparation(args, candidates)
    _print_batch_release_plan(plan.candidates, plan.tag_actions)

    if args.dry_run:
        return _run_dry_batch_release(args, plan, dirty=dirty)

    _require_command("uv")
    if args.publish:
        print_publish_note()

    prepare_release_metadata(plan.preparation_versions)
    run_preparation_steps(plan.preparation_targets, dry_run=False)
    release_commit_created, preparation_commit = commit_release_preparation(
        plan.preparation_targets,
        message=_batch_release_commit_message(plan.candidates),
    )

    if not args.skip_checks:
        run_prechecks_for_targets(plan.preparation_targets, dry_run=False)

    run_postupdate_steps_for_targets(plan.release_targets, dry_run=False)

    candidates = require_fresh_release_fence(
        plan.candidates,
        preparation_branch=plan.preparation_branch,
        preparation_commit=preparation_commit,
    )
    tag_actions = _plan_candidate_tag_actions(
        candidates,
        head_commit=preparation_commit,
        version_changed=release_commit_created,
        retag=args.retag,
    )

    observer_token = release_observer_token()
    push_current_branch(
        dry_run=False,
        branch=plan.preparation_branch,
        head_commit=preparation_commit,
    )
    wait_for_canonical_workflows(
        head_commit=preparation_commit,
        token=observer_token,
    )
    require_repository_settings()
    refreshed_candidates = require_fresh_release_fence(
        candidates,
        preparation_branch=plan.preparation_branch,
        preparation_commit=preparation_commit,
    )
    require_release_states_unchanged(candidates, refreshed_candidates)
    candidates = refreshed_candidates
    tag_actions = _plan_candidate_tag_actions(
        candidates,
        head_commit=preparation_commit,
        version_changed=release_commit_created,
        retag=args.retag,
    )
    for candidate in candidates:
        prepare_tag(tag_actions[candidate.target.key], dry_run=False)
    for candidate in candidates:
        push_tag(tag_actions[candidate.target.key], dry_run=False)

    print(
        "Next step: wait for release-gate workflows on "
        + ", ".join(candidate.state.tag_name for candidate in candidates)
        + ". They will publish to PyPI and immutable GitHub Releases."
    )
    return 0


def _run_single_release(
    args: argparse.Namespace,
    target: ReleaseTarget,
) -> int:
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
            "Release and PyPI state, and tags before remote actions"
        )
        push_current_branch(
            dry_run=True,
            head_commit=PENDING_RELEASE_COMMIT,
        )
        print(
            "dry-run: would resolve GitHub auth, wait for exact-SHA root, PG, and "
            "MCP producer workflows, then recheck repository settings and the "
            "full release fence"
        )
        prepare_tag(tag_action, dry_run=True)
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
    (refreshed_candidate,) = require_fresh_release_fence(
        (candidate,),
        preparation_branch=preparation_branch,
        preparation_commit=preparation_commit,
    )
    require_release_states_unchanged((candidate,), (refreshed_candidate,))
    candidate = refreshed_candidate
    tag_action = plan_tag_action(
        candidate.state,
        version_changed=release_commit_created,
        head_commit=preparation_commit,
        retag=args.retag,
    )
    observer_token = release_observer_token()
    push_current_branch(
        dry_run=False,
        branch=preparation_branch,
        head_commit=preparation_commit,
    )
    wait_for_canonical_workflows(
        head_commit=preparation_commit,
        token=observer_token,
    )
    require_repository_settings()
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
    push_tag(tag_action, dry_run=False)
    print(
        f"Next step: wait for {target.release_workflow} on {state.tag_name}. "
        "It will publish to PyPI and an immutable GitHub Release."
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.check_repository_settings:
        require_repository_settings()
        return 0
    if not args.dry_run and not args.checks_only:
        require_publish_branch()
        require_repository_settings()
    if args.target == ALL_RELEASE_TARGET_KEY:
        return _run_batch_release(args)
    return _run_single_release(args, TARGETS[args.target])


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except subprocess.CalledProcessError as exc:
        print(f"error: command failed with exit code {exc.returncode}", file=sys.stderr)
        raise SystemExit(exc.returncode) from exc
