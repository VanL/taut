"""Policy tests for the repository's canonical Ruff environments."""

from __future__ import annotations

import json
import re
import subprocess
import tomllib
from collections import Counter
from pathlib import Path

import pytest

from bin.ruff_suppression_index import REGISTRY_HEADING, run

ROOT = Path(__file__).resolve().parent.parent
pytestmark = pytest.mark.sqlite_only
RUFF_VERSION = "0.16.1"
RULE_FIXTURE = ROOT / "tests" / "fixtures" / "ruff-enabled-rules.txt"
MANIFESTS = (
    ROOT / "pyproject.toml",
    ROOT / "extensions" / "taut_pg" / "pyproject.toml",
    ROOT / "extensions" / "taut_summon" / "pyproject.toml",
    ROOT / "extensions" / "taut_mcp" / "pyproject.toml",
)
LOCKS = (
    ROOT / "extensions" / "taut_summon" / "uv.lock",
    ROOT / "extensions" / "taut_mcp" / "uv.lock",
)
EXTENSIONLESS_PYTHON = {
    "bin/check-cli-claims",
    "bin/check-doc-paths",
    "bin/check-dom15-fixtures",
    "bin/check-plan-status-index",
    "bin/coalesce-check",
    "bin/pytest-pg",
}
REVIEWED_FAMILIES = ["E", "W", "F", "I", "B", "C901", "C4", "UP"]
GLOBAL_IGNORES = ["E501", "B008"]
RAW_RULE_COUNTS = {
    "BLE001": 89,
    "C901": 38,
    "DTZ006": 1,
    "F401": 1,
    "FLY002": 16,
    "FURB122": 1,
    "LOG001": 1,
    "N999": 6,
    "PYI041": 1,
    "RUF015": 2,
    "SIM115": 3,
    "SIM117": 7,
    "TRY004": 15,
}
RETIRED_GROUP_NUMBERS = {
    1,
    6,
    7,
    9,
    10,
    13,
    17,
    20,
    23,
    25,
    27,
    28,
    29,
    33,
    37,
    38,
    39,
    41,
    42,
    45,
    49,
    50,
    51,
    57,
    59,
    62,
}


def _manifest_ruff_pin(path: Path) -> str:
    with path.open("rb") as stream:
        dev = tomllib.load(stream)["project"]["optional-dependencies"]["dev"]
    pins = [item for item in dev if item.startswith("ruff")]
    assert len(pins) == 1, path
    pin = pins[0]
    assert isinstance(pin, str)
    return pin


def _locked_ruff_version(path: Path) -> str:
    with path.open("rb") as stream:
        packages = tomllib.load(stream)["package"]
    matches = [package["version"] for package in packages if package["name"] == "ruff"]
    assert len(matches) == 1, path
    version = matches[0]
    assert isinstance(version, str)
    return version


def _ruff_version(*command: str) -> str:
    result = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    prefix, version = result.stdout.strip().split()
    assert prefix == "ruff"
    return version


def _enabled_rules(*, project: str | None, source: str) -> set[str]:
    command = ["uv", "run"]
    if project is not None:
        command.extend(("--project", project))
    command.extend(("--extra", "dev", "ruff", "check", "--show-settings", source))
    result = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    match = re.search(
        r"linter\.rules\.enabled = \[\n(?P<rules>.*?)\n\]",
        result.stdout,
        re.DOTALL,
    )
    assert match is not None, result.stdout
    return set(re.findall(r"\(([A-Z]+\d+)\)", match.group("rules")))


def _ruff(
    *args: str, project: str | None = None, input_text: str | None = None
) -> subprocess.CompletedProcess[str]:
    command = ["uv", "run"]
    if project is not None:
        command.extend(("--project", project))
    command.extend(("--extra", "dev", "ruff", *args))
    return subprocess.run(
        command,
        cwd=ROOT,
        input=input_text,
        text=True,
        capture_output=True,
        check=False,
    )


def _tracked_python_files() -> set[str]:
    result = subprocess.run(
        ("git", "ls-files", "-z"),
        cwd=ROOT,
        capture_output=True,
        check=True,
    )
    paths: set[str] = set()
    for raw_path in result.stdout.split(b"\0"):
        if not raw_path:
            continue
        relative = raw_path.decode()
        path = ROOT / relative
        if relative.endswith((".py", ".pyi")):
            paths.add(relative)
        elif path.is_file():
            with path.open("rb") as stream:
                first_line = stream.readline()
            if first_line.startswith(b"#!") and b"python" in first_line.lower():
                paths.add(relative)
    return paths


def test_all_development_manifests_pin_the_same_exact_ruff() -> None:
    assert {_manifest_ruff_pin(path) for path in MANIFESTS} == {f"ruff=={RUFF_VERSION}"}


def test_existing_extension_locks_resolve_the_exact_ruff_pin() -> None:
    assert not (ROOT / "uv.lock").exists()
    assert not (ROOT / "extensions" / "taut_pg" / "uv.lock").exists()
    assert {_locked_ruff_version(path) for path in LOCKS} == {RUFF_VERSION}


def test_running_root_and_mcp_ruff_binaries_match_the_pin() -> None:
    assert (
        _ruff_version("uv", "run", "--extra", "dev", "ruff", "--version")
        == RUFF_VERSION
    )
    assert (
        _ruff_version(
            "uv",
            "run",
            "--project",
            "extensions/taut_mcp",
            "--extra",
            "dev",
            "ruff",
            "--version",
        )
        == RUFF_VERSION
    )


def test_tracked_python_inventory_includes_all_six_extensionless_tools() -> None:
    tracked = _tracked_python_files()
    assert EXTENSIONLESS_PYTHON <= tracked
    assert all(
        path.endswith((".py", ".pyi")) or path in EXTENSIONLESS_PYTHON
        for path in tracked
    )


def test_active_configs_extend_defaults_with_reviewed_families() -> None:
    root = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    mcp = tomllib.loads(
        (ROOT / "extensions" / "taut_mcp" / "pyproject.toml").read_text(
            encoding="utf-8"
        )
    )

    assert root["tool"]["ruff"]["extend-include"] == ["bin/*"]
    for project in (root, mcp):
        lint = project["tool"]["ruff"]["lint"]
        assert "select" not in lint
        assert lint["extend-select"] == REVIEWED_FAMILIES
        assert lint["ignore"] == GLOBAL_IGNORES
        assert lint["mccabe"] == {"max-complexity": 10}
        assert lint.get("preview", False) is False
        assert lint.get("per-file-ignores", {}) == {}


def test_generator_registry_heading_matches_the_promoted_spec() -> None:
    spec = (
        ROOT / "docs" / "specs" / "01-development-documentation-operating-model.md"
    ).read_text(encoding="utf-8")

    assert REGISTRY_HEADING == "#### [DOM-10.2.1] Approved Ruff suppression registry"
    assert spec.count(REGISTRY_HEADING) == 1


def test_effective_root_and_mcp_rules_match_the_reviewed_fixture() -> None:
    expected = set(RULE_FIXTURE.read_text(encoding="utf-8").splitlines())
    assert expected
    assert _enabled_rules(project=None, source="taut/__init__.py") == expected
    assert (
        _enabled_rules(
            project="extensions/taut_mcp",
            source="extensions/taut_mcp/taut_mcp/__init__.py",
        )
        == expected
    )


def test_configured_complexity_boundary_fires_only_at_eleven() -> None:
    def probe(complexity: int) -> str:
        branches = "\n".join(
            f"    if value == {branch}:\n        return {branch}"
            for branch in range(1, complexity)
        )
        return (
            f"def complexity_{complexity}(value: int) -> int:\n"
            f"{branches}\n    return 0\n"
        )

    result = _ruff(
        "check",
        "--config",
        str(ROOT / "pyproject.toml"),
        "--select",
        "C901",
        "--output-format",
        "json",
        "--stdin-filename",
        "complexity_probe.py",
        "-",
        input_text=probe(10) + "\n" + probe(11),
    )
    assert result.returncode == 1, result.stderr
    diagnostics = json.loads(result.stdout)
    assert [(item["code"], item["noqa_row"]) for item in diagnostics] == [("C901", 22)]
    assert "`complexity_11` is too complex (11 > 10)" in diagnostics[0]["message"]


def test_real_ruff_fires_stable_default_and_retained_legacy_rules() -> None:
    probe = """\
def probe() -> None:
    try:
        raise ValueError
    except Exception:
        raise RuntimeError("probe")
"""
    result = _ruff(
        "check",
        "--config",
        str(ROOT / "pyproject.toml"),
        "--stdin-filename",
        "probe.py",
        "--output-format",
        "json",
        "-",
        input_text=probe,
    )
    assert result.returncode == 1, result.stderr
    codes = {diagnostic["code"] for diagnostic in json.loads(result.stdout)}
    assert {"BLE001", "B904"} <= codes


def test_root_ruff_discovers_every_tracked_python_source() -> None:
    result = _ruff("check", "--show-files", ".")
    assert result.returncode == 0, result.stderr
    discovered = {
        str(Path(line).resolve().relative_to(ROOT))
        for line in result.stdout.splitlines()
        if line
    }
    assert _tracked_python_files() <= discovered


def test_raw_active_rule_inventory_and_registry_are_exact() -> None:
    result = _ruff("check", "--ignore-noqa", "--output-format", "json", ".")
    assert result.returncode == 1, result.stderr
    counts = Counter(item["code"] for item in json.loads(result.stdout))
    assert counts == RAW_RULE_COUNTS

    snapshot = run(
        repo_root=ROOT,
        spec=ROOT
        / "docs"
        / "specs"
        / "01-development-documentation-operating-model.md",
        write=False,
    )
    assert [group.group_id for group in snapshot.groups] == [
        f"RUFF-SUP-{number:03d}"
        for number in range(1, 82)
        if number not in RETIRED_GROUP_NUMBERS
    ]
    assert len(snapshot.directives) == 180


def test_normal_repository_ruff_and_documented_registry_commands_are_current() -> None:
    result = _ruff("check", ".")
    assert result.returncode == 0, result.stdout + result.stderr
    spec = (
        ROOT / "docs" / "specs" / "01-development-documentation-operating-model.md"
    ).read_text(encoding="utf-8")
    assert "uv run --extra dev python\nbin/ruff_suppression_index.py --check" in spec
    assert "uv run --extra dev python\nbin/ruff_suppression_index.py --write" in spec
