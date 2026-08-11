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


def _project(path: str) -> dict[str, object]:
    return _manifest(path)["project"]  # type: ignore[return-value]


def _dependency_floor(project: dict[str, object], name: str) -> str:
    dependencies = project["dependencies"]
    assert isinstance(dependencies, list)
    matches = [item for item in dependencies if str(item).startswith(f"{name}>=")]
    assert len(matches) == 1
    return str(matches[0]).removeprefix(f"{name}>=")


def _version_tuple(version: str) -> tuple[int, int, int]:
    parts = version.split(".")
    assert len(parts) == 3
    return tuple(int(part) for part in parts)  # type: ignore[return-value]


def test_package_versions_and_derived_metadata_match_their_owners() -> None:
    root_manifest = _manifest("pyproject.toml")
    pg_manifest = _manifest("extensions/taut_pg/pyproject.toml")
    mcp_manifest = _manifest("extensions/taut_mcp/pyproject.toml")
    summon_manifest = _manifest("extensions/taut_summon/pyproject.toml")
    root = root_manifest["project"]
    pg = pg_manifest["project"]
    mcp = mcp_manifest["project"]
    summon = summon_manifest["project"]
    assert isinstance(root, dict)
    assert isinstance(pg, dict)
    assert isinstance(mcp, dict)
    assert isinstance(summon, dict)
    root_version = str(root["version"])
    mcp_version = str(mcp["version"])
    pg_version = str(pg["version"])
    summon_version = str(summon["version"])
    constants = (REPO_ROOT / "taut" / "_constants.py").read_text(encoding="utf-8")
    constant_match = re.search(r'__version__(?::[^=]+)? = "([^"]+)"', constants)

    assert constant_match is not None
    assert constant_match.group(1) == root_version
    assert root["name"] == "taut-chat"
    assert pg["name"] == "taut-pg"
    assert summon["name"] == "taut-summon"
    assert mcp["name"] == "taut-mcp"
    simplebroker_floor = _dependency_floor(root, "simplebroker")
    assert simplebroker_floor == "7.0.0"
    assert _dependency_floor(pg, "taut-chat") == root_version
    simplebroker_pg_floor = _dependency_floor(pg, "simplebroker-pg")
    assert simplebroker_pg_floor == "3.5.2"
    assert _dependency_floor(summon, "taut-chat") == root_version
    assert _dependency_floor(mcp, "taut-chat") == root_version
    for manifest in (pg_manifest, summon_manifest, mcp_manifest):
        tool = manifest["tool"]
        assert isinstance(tool, dict)
        uv = tool["uv"]
        assert isinstance(uv, dict)
        sources = uv["sources"]
        assert isinstance(sources, dict)
        assert "taut-chat" in sources
        assert "taut" not in sources
    mcp_dependencies = mcp["dependencies"]
    assert isinstance(mcp_dependencies, list)
    assert "mcp>=2.0.0,<3" in mcp_dependencies
    assert "jsonschema>=4.20,<5" in mcp_dependencies

    optional = root["optional-dependencies"]
    assert isinstance(optional, dict)
    dev = optional["dev"]
    assert isinstance(dev, list)
    assert f"simplebroker-pg>={simplebroker_pg_floor}" in dev
    assert f"taut-summon>={summon_version}" in dev

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
    locked_simplebroker = [
        package
        for package in packages
        if isinstance(package, dict) and package.get("name") == "simplebroker"
    ]
    assert len(locked_simplebroker) == 1
    locked_simplebroker_version = locked_simplebroker[0].get("version")
    assert isinstance(locked_simplebroker_version, str)
    assert _version_tuple(locked_simplebroker_version) >= _version_tuple(
        simplebroker_floor
    )
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
    assert locked_by_name["mcp"].get("version") == "2.0.0"
    mcp_metadata = locked_by_name["taut-mcp"].get("metadata")
    assert isinstance(mcp_metadata, dict)
    requirements = mcp_metadata.get("requires-dist")
    assert isinstance(requirements, list)
    assert {
        "name": "mcp",
        "specifier": ">=2.0.0,<3",
    } in requirements
    assert {
        "name": "jsonschema",
        "specifier": ">=4.20,<5",
    } in requirements
    assert {
        "name": "taut-chat",
        "editable": "../../",
    } in requirements


def test_retained_locks_resolve_at_or_above_supported_broker_floors() -> None:
    simplebroker_floor = _dependency_floor(_project("pyproject.toml"), "simplebroker")
    simplebroker_pg_floor = _dependency_floor(
        _project("extensions/taut_pg/pyproject.toml"), "simplebroker-pg"
    )
    minimum_by_lock = {
        "uv.lock": {
            "simplebroker": simplebroker_floor,
            "simplebroker-pg": simplebroker_pg_floor,
        },
        "extensions/taut_summon/uv.lock": {
            "simplebroker": simplebroker_floor,
        },
        "extensions/taut_mcp/uv.lock": {
            "simplebroker": simplebroker_floor,
            "simplebroker-pg": simplebroker_pg_floor,
        },
    }

    for path, minimums in minimum_by_lock.items():
        lock = _manifest(path)
        packages = lock["package"]
        assert isinstance(packages, list)
        resolved = {
            str(package["name"]): str(package["version"])
            for package in packages
            if isinstance(package, dict)
            and package.get("name") in minimums
            and "version" in package
        }
        assert resolved.keys() == minimums.keys()
        for name, minimum in minimums.items():
            assert _version_tuple(resolved[name]) >= _version_tuple(minimum)


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

    assert "pipx install taut-chat" in root
    assert "uv add taut-chat" in root
    assert "pipx inject --include-apps taut-chat taut-pg taut-summon taut-mcp" in root
    assert "uv add taut-chat taut-pg taut-summon taut-mcp" in root
    assert "python -m pip install taut-chat taut-pg taut-summon taut-mcp" in root
    assert "pipx inject taut-chat taut-pg" in pg
    assert "pipx inject --include-apps taut-chat taut-summon" in summon
    assert "pipx inject --include-apps taut-chat taut-mcp" in mcp


def test_mcp_user_docs_expose_the_console_and_release_target() -> None:
    root = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    mcp = (REPO_ROOT / "extensions" / "taut_mcp" / "README.md").read_text(
        encoding="utf-8"
    )

    assert "pipx inject --include-apps taut-chat taut-mcp" in mcp
    assert "uv run python bin/release.py mcp --dry-run" in root
    assert "taut_mcp/vX.Y.Z" in root
