"""Policy tests for the repository's canonical Ruff environments."""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from bin.ruff_suppression_index import REGISTRY_HEADING, run

ROOT = Path(__file__).resolve().parent.parent
pytestmark = pytest.mark.sqlite_only
EXTENSIONLESS_PYTHON = {
    "bin/check-cli-claims",
    "bin/check-doc-paths",
    "bin/check-dom15-fixtures",
    "bin/check-plan-status-index",
    "bin/coalesce-check",
    "bin/pytest-pg",
    "bin/render-tui-screens",
}
REVIEWED_FAMILIES = ["E", "W", "F", "I", "B", "C901", "C4", "UP"]
GLOBAL_IGNORES = ["E501", "B008"]


def _enabled_rules(*args: str, source: str = "taut/__init__.py") -> set[str]:
    command = [
        sys.executable,
        "-m",
        "ruff",
        "check",
        "--no-cache",
        "--show-settings",
        *args,
        source,
    ]
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
    codes = set(re.findall(r"\(([A-Z]+\d+)\)", match.group("rules")))
    assert codes, f"No enabled rule codes parsed from Ruff settings:\n{result.stdout}"
    return codes


def _ruff(
    *args: str, input_text: str | None = None
) -> subprocess.CompletedProcess[str]:
    command = [sys.executable, "-m", "ruff", args[0], "--no-cache", *args[1:]]
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
        if relative.endswith((".py", ".pyi")) and path.is_file():
            paths.add(relative)
        elif path.is_file():
            with path.open("rb") as stream:
                first_line = stream.readline()
            if first_line.startswith(b"#!") and b"python" in first_line.lower():
                paths.add(relative)
    return paths


def test_tracked_python_inventory_includes_all_extensionless_tools() -> None:
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
    tui = tomllib.loads(
        (ROOT / "extensions" / "taut_tui" / "pyproject.toml").read_text(
            encoding="utf-8"
        )
    )

    assert root["tool"]["ruff"]["extend-include"] == ["bin/*"]
    for project in (root, mcp, tui):
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


def test_effective_ruff_rules_extend_current_defaults() -> None:
    # Independent CLI selections protect effective config discovery too:
    # a shadowing ruff.toml must not silently replace pyproject's defaults.
    defaults = _enabled_rules("--isolated")
    explicit = _enabled_rules("--isolated", "--select", ",".join(REVIEWED_FAMILIES))
    expected = (defaults | explicit) - set(GLOBAL_IGNORES)
    assert _enabled_rules(source="taut/__init__.py") == expected
    assert (
        _enabled_rules(
            source="extensions/taut_mcp/taut_mcp/__init__.py",
        )
        == expected
    )
    assert (
        _enabled_rules(
            source="extensions/taut_tui/taut_tui/__init__.py",
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


def test_real_ruff_preserves_default_diagnostics_and_legacy_rules() -> None:
    probe = """\
def probe() -> None:
    try:
        raise ValueError
    except Exception:
        raise RuntimeError("probe")
"""
    default_result = _ruff(
        "check",
        "--isolated",
        "--stdin-filename",
        "probe.py",
        "--output-format",
        "json",
        "-",
        input_text=probe,
    )
    assert default_result.returncode in (0, 1), default_result.stderr
    default_codes = {
        diagnostic["code"] for diagnostic in json.loads(default_result.stdout)
    } - set(GLOBAL_IGNORES)
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
    assert default_codes <= codes
    assert "B904" in codes  # Explicitly selected B family, not an upstream default.


def test_root_ruff_discovers_every_tracked_python_source() -> None:
    result = _ruff("check", "--show-files", ".")
    assert result.returncode == 0, result.stderr
    discovered = {
        Path(line).resolve().relative_to(ROOT).as_posix()
        for line in result.stdout.splitlines()
        if line
    }
    assert _tracked_python_files() <= discovered


def test_spec_owned_ruff_inventory_and_registry_are_current() -> None:
    run(
        repo_root=ROOT,
        spec=ROOT
        / "docs"
        / "specs"
        / "01-development-documentation-operating-model.md",
        write=False,
    )


def test_normal_repository_ruff_and_documented_registry_commands_are_current() -> None:
    result = _ruff("check", ".")
    assert result.returncode == 0, result.stdout + result.stderr
    spec = (
        ROOT / "docs" / "specs" / "01-development-documentation-operating-model.md"
    ).read_text(encoding="utf-8")
    assert (
        "uv run --no-sync --extra dev python\nbin/ruff_suppression_index.py --check"
    ) in spec
    assert (
        "uv run --no-sync --extra dev python\nbin/ruff_suppression_index.py --write"
    ) in spec
