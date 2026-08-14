from __future__ import annotations

import re
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


def test_package_versions_and_derived_metadata_match_their_owners() -> None:
    root_manifest = _manifest("pyproject.toml")
    pg_manifest = _manifest("extensions/taut_pg/pyproject.toml")
    mcp_manifest = _manifest("extensions/taut_mcp/pyproject.toml")
    summon_manifest = _manifest("extensions/taut_summon/pyproject.toml")
    tui_manifest = _manifest("extensions/taut_tui/pyproject.toml")
    root = root_manifest["project"]
    pg = pg_manifest["project"]
    mcp = mcp_manifest["project"]
    summon = summon_manifest["project"]
    tui = tui_manifest["project"]
    assert isinstance(root, dict)
    assert isinstance(pg, dict)
    assert isinstance(mcp, dict)
    assert isinstance(summon, dict)
    assert isinstance(tui, dict)
    root_version = str(root["version"])
    mcp_version = str(mcp["version"])
    pg_version = str(pg["version"])
    summon_version = str(summon["version"])
    tui_version = str(tui["version"])
    constants = (REPO_ROOT / "taut" / "_constants.py").read_text(encoding="utf-8")
    constant_match = re.search(r'__version__(?::[^=]+)? = "([^"]+)"', constants)

    assert constant_match is not None
    assert constant_match.group(1) == root_version
    assert root["name"] == "taut-chat"
    assert pg["name"] == "taut-pg"
    assert summon["name"] == "taut-summon"
    assert mcp["name"] == "taut-mcp"
    assert tui["name"] == "taut-tui"
    assert _dependency_floor(pg, "taut-chat") == root_version
    assert _dependency_floor(summon, "taut-chat") == root_version
    assert _dependency_floor(mcp, "taut-chat") == root_version
    assert _dependency_floor(tui, "taut-chat") == root_version
    for manifest in (pg_manifest, summon_manifest, mcp_manifest, tui_manifest):
        tool = manifest["tool"]
        assert isinstance(tool, dict)
        uv = tool["uv"]
        assert isinstance(uv, dict)
        sources = uv["sources"]
        assert isinstance(sources, dict)
        assert "taut-chat" in sources
        assert "taut" not in sources
    optional = root["optional-dependencies"]
    assert isinstance(optional, dict)
    dev = optional["dev"]
    assert isinstance(dev, list)
    assert f"taut-summon>={summon_version}" in dev
    assert f"taut-tui>={tui_version}" in dev
    assert optional["tui"] == [f"taut-tui>={tui_version}"]
    assert optional["all"] == [
        f"taut-pg>={pg_version}",
        f"taut-summon>={summon_version}",
        f"taut-mcp>={mcp_version}",
        f"taut-tui>={tui_version}",
    ]

    root_tool = root_manifest["tool"]
    assert isinstance(root_tool, dict)
    root_uv = root_tool["uv"]
    assert isinstance(root_uv, dict)
    root_sources = root_uv["sources"]
    assert isinstance(root_sources, dict)
    assert root_sources["taut-mcp"] == {
        "path": "./extensions/taut_mcp",
        "editable": True,
    }
    assert root_sources["taut-tui"] == {
        "path": "./extensions/taut_tui",
        "editable": True,
    }

    mcp_optional = mcp["optional-dependencies"]
    assert isinstance(mcp_optional, dict)
    mcp_dev = mcp_optional["dev"]
    assert isinstance(mcp_dev, list)
    assert f"taut-pg>={pg_version}" in mcp_dev

    summon_lock = _manifest("extensions/taut_summon/uv.lock")
    packages = summon_lock["package"]
    assert isinstance(packages, list)
    for package_name, expected_version in (
        ("taut-chat", root_version),
        ("taut-summon", summon_version),
    ):
        locked = [
            package
            for package in packages
            if isinstance(package, dict) and package.get("name") == package_name
        ]
        assert len(locked) == 1
        assert locked[0].get("version") == expected_version
    locked_summon = next(
        package
        for package in packages
        if isinstance(package, dict) and package.get("name") == "taut-summon"
    )
    summon_metadata = locked_summon.get("metadata")
    assert isinstance(summon_metadata, dict)
    summon_requirements = summon_metadata.get("requires-dist")
    assert isinstance(summon_requirements, list)
    assert {
        "name": "taut-chat",
        "editable": "../../",
    } in summon_requirements

    mcp_lock = _manifest("extensions/taut_mcp/uv.lock")
    mcp_packages = mcp_lock["package"]
    assert isinstance(mcp_packages, list)
    locked_by_name = {
        str(package["name"]): package
        for package in mcp_packages
        if isinstance(package, dict) and "name" in package
    }
    assert locked_by_name["taut-chat"].get("version") == root_version
    assert locked_by_name["taut-pg"].get("version") == pg_version
    assert locked_by_name["taut-mcp"].get("version") == mcp_version
    mcp_metadata = locked_by_name["taut-mcp"].get("metadata")
    assert isinstance(mcp_metadata, dict)
    requirements = mcp_metadata.get("requires-dist")
    assert isinstance(requirements, list)
    assert {
        "name": "taut-chat",
        "editable": "../../",
    } in requirements

    tui_lock = _manifest("extensions/taut_tui/uv.lock")
    tui_packages = tui_lock["package"]
    assert isinstance(tui_packages, list)
    tui_locked_by_name = {
        str(package["name"]): package
        for package in tui_packages
        if isinstance(package, dict) and "name" in package
    }
    assert tui_locked_by_name["taut-chat"].get("version") == root_version
    assert tui_locked_by_name["taut-tui"].get("version") == tui_version


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
