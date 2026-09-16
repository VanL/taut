from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

pytestmark = pytest.mark.sqlite_only

REPO_ROOT = Path(__file__).resolve().parents[1]


def _manifest(path: str) -> dict[str, object]:
    with (REPO_ROOT / path).open("rb") as stream:
        return tomllib.load(stream)


def _dependency_floor(project: dict[str, object], name: str) -> str:
    dependencies = project["dependencies"]
    assert isinstance(dependencies, list)
    matches = [item for item in dependencies if str(item).startswith(f"{name}>=")]
    assert len(matches) == 1
    return str(matches[0]).removeprefix(f"{name}>=")


def test_readme_install_examples_use_public_distribution_names() -> None:
    root = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    pg = (REPO_ROOT / "extensions" / "taut_pg" / "README.md").read_text(
        encoding="utf-8"
    )
    summon = (REPO_ROOT / "extensions" / "taut_summon" / "README.md").read_text(
        encoding="utf-8"
    )
    mcp = (REPO_ROOT / "extensions" / "taut_mcp" / "README.md").read_text(
        encoding="utf-8"
    )
    tui = (REPO_ROOT / "extensions" / "taut_tui" / "README.md").read_text(
        encoding="utf-8"
    )

    assert "pipx install taut-chat" in root
    assert "uv add taut-chat" in root
    assert (
        "pipx inject --include-apps taut-chat taut-pg taut-summon taut-mcp taut-tui"
        in root
    )
    assert "uv add taut-chat taut-pg taut-summon taut-mcp taut-tui" in root
    assert (
        "python -m pip install taut-chat taut-pg taut-summon taut-mcp taut-tui" in root
    )
    assert "pipx inject taut-chat taut-pg" in pg
    assert "pipx inject --include-apps taut-chat taut-summon" in summon
    assert "pipx inject --include-apps taut-chat taut-mcp" in mcp
    assert "python -m pip install taut-chat taut-tui" in tui


def test_tui_textual_floor_prose_matches_the_manifest_owner() -> None:
    manifest = _manifest("extensions/taut_tui/pyproject.toml")
    project = manifest["project"]
    assert isinstance(project, dict)
    floor = _dependency_floor(project, "textual")

    for relative_path in (
        "README.md",
        "extensions/taut_tui/README.md",
        "docs/implementation/12-taut-tui.md",
    ):
        prose = (REPO_ROOT / relative_path).read_text(encoding="utf-8")
        assert floor in prose, relative_path


def test_mcp_user_docs_expose_the_console_and_release_target() -> None:
    root = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    mcp = (REPO_ROOT / "extensions" / "taut_mcp" / "README.md").read_text(
        encoding="utf-8"
    )

    assert "pipx inject --include-apps taut-chat taut-mcp" in mcp
    assert "uv run python bin/release.py mcp --dry-run" in root
    assert "taut_mcp/vX.Y.Z" in root
