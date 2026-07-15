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
    root = _project("pyproject.toml")
    pg = _project("extensions/taut_pg/pyproject.toml")
    mcp = _project("extensions/taut_mcp/pyproject.toml")
    summon = _project("extensions/taut_summon/pyproject.toml")
    root_version = str(root["version"])
    mcp_version = str(mcp["version"])
    pg_version = str(pg["version"])
    summon_version = str(summon["version"])
    constants = (REPO_ROOT / "taut" / "_constants.py").read_text(encoding="utf-8")
    constant_match = re.search(r'__version__(?::[^=]+)? = "([^"]+)"', constants)

    assert constant_match is not None
    assert constant_match.group(1) == root_version
    simplebroker_floor = _dependency_floor(root, "simplebroker")
    assert _version_tuple(simplebroker_floor) >= (5, 3, 2)
    assert _dependency_floor(pg, "taut") == root_version
    simplebroker_pg_floor = _dependency_floor(pg, "simplebroker-pg")
    assert _version_tuple(simplebroker_pg_floor) >= (3, 2, 1)
    assert _dependency_floor(summon, "taut") == root_version
    assert _dependency_floor(mcp, "taut") == root_version
    assert "mcp>=1.28.1,<2" in mcp["dependencies"]  # type: ignore[operator]

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
        ("taut", root_version),
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

    mcp_lock = _manifest("extensions/taut_mcp/uv.lock")
    mcp_packages = mcp_lock["package"]
    assert isinstance(mcp_packages, list)
    locked_by_name = {
        str(package["name"]): package
        for package in mcp_packages
        if isinstance(package, dict) and "name" in package
    }
    assert locked_by_name["taut"].get("version") == root_version
    assert locked_by_name["taut-pg"].get("version") == pg_version
    assert locked_by_name["taut-mcp"].get("version") == mcp_version
    assert locked_by_name["mcp"].get("version") == "1.28.1"
    mcp_metadata = locked_by_name["taut-mcp"].get("metadata")
    assert isinstance(mcp_metadata, dict)
    requirements = mcp_metadata.get("requires-dist")
    assert isinstance(requirements, list)
    assert {
        "name": "mcp",
        "specifier": ">=1.28.1,<2",
    } in requirements


def test_readme_install_examples_match_current_manifests() -> None:
    root_project = _project("pyproject.toml")
    root_version = str(root_project["version"])
    pg_version = str(_project("extensions/taut_pg/pyproject.toml")["version"])
    summon_version = str(_project("extensions/taut_summon/pyproject.toml")["version"])
    mcp_version = str(_project("extensions/taut_mcp/pyproject.toml")["version"])
    simplebroker_floor = _dependency_floor(root_project, "simplebroker")
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

    assert f"@v{root_version}" in root
    assert f"@v{root_version}" in pg
    assert f"@v{root_version}" in summon
    assert f"@v{root_version}" in mcp
    assert f"taut_pg-{pg_version}-py3-none-any.whl" in root
    assert f"taut_pg-{pg_version}-py3-none-any.whl" in pg
    assert f"taut_summon-{summon_version}-py3-none-any.whl" in root
    assert f"taut_summon-{summon_version}-py3-none-any.whl" in summon
    assert f"taut_mcp-{mcp_version}-py3-none-any.whl" in root
    assert f"taut_mcp-{mcp_version}-py3-none-any.whl" in mcp
    assert "taut_summon-X.Y.Z-py3-none-any.whl" not in root
    readme_simplebroker_floors = re.findall(r"simplebroker>=(\d+\.\d+\.\d+)", root)
    assert readme_simplebroker_floors
    assert set(readme_simplebroker_floors) == {simplebroker_floor}

    stale_tag = re.compile(r"@v(?!" + re.escape(root_version) + r"\b)\d+\.\d+\.\d+")
    for text in (root, pg, summon, mcp):
        assert stale_tag.search(text) is None

    stale_pg_wheel = re.compile(
        r"taut_pg-(?!" + re.escape(pg_version) + r"\b)\d+\.\d+\.\d+-py3-none-any\.whl"
    )
    stale_summon_wheel = re.compile(
        r"taut_summon-(?!"
        + re.escape(summon_version)
        + r"\b)\d+\.\d+\.\d+-py3-none-any\.whl"
    )
    stale_mcp_wheel = re.compile(
        r"taut_mcp-(?!" + re.escape(mcp_version) + r"\b)\d+\.\d+\.\d+-py3-none-any\.whl"
    )
    for text in (root, pg):
        assert stale_pg_wheel.search(text) is None
    for text in (root, summon):
        assert stale_summon_wheel.search(text) is None
    for text in (root, mcp):
        assert stale_mcp_wheel.search(text) is None


def test_mcp_user_docs_expose_the_console_and_release_target() -> None:
    root = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    mcp = (REPO_ROOT / "extensions" / "taut_mcp" / "README.md").read_text(
        encoding="utf-8"
    )

    install_command = "pipx inject --include-apps taut ./taut_mcp-"
    assert install_command in root
    assert install_command in mcp
    assert "uv run python bin/release.py mcp --dry-run" in root
    assert "taut_mcp/vX.Y.Z" in root
