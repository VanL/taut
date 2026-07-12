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


def test_package_versions_and_dependency_floors_are_coordinated() -> None:
    root = _project("pyproject.toml")
    pg = _project("extensions/taut_pg/pyproject.toml")
    summon = _project("extensions/taut_summon/pyproject.toml")
    version = str(root["version"])
    constants = (REPO_ROOT / "taut" / "_constants.py").read_text(encoding="utf-8")
    constant_match = re.search(r'__version__(?::[^=]+)? = "([^"]+)"', constants)

    assert constant_match is not None
    assert constant_match.group(1) == version
    assert str(pg["version"]) == version
    assert str(summon["version"]) == version
    assert _dependency_floor(root, "simplebroker") == "5.3.1"
    assert _dependency_floor(pg, "taut") == version
    assert _dependency_floor(pg, "simplebroker-pg") == "3.2.1"
    assert _dependency_floor(summon, "taut") == version

    optional = root["optional-dependencies"]
    assert isinstance(optional, dict)
    dev = optional["dev"]
    assert isinstance(dev, list)
    assert "simplebroker-pg>=3.2.1" in dev
    assert f"taut-summon>={version}" in dev


def test_readme_install_examples_match_current_manifests() -> None:
    version = str(_project("pyproject.toml")["version"])
    root = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    pg = (REPO_ROOT / "extensions" / "taut_pg" / "README.md").read_text(
        encoding="utf-8"
    )
    summon = (REPO_ROOT / "extensions" / "taut_summon" / "README.md").read_text(
        encoding="utf-8"
    )

    assert f"@v{version}" in root
    assert f"@v{version}" in pg
    assert f"@v{version}" in summon
    assert f"taut_pg-{version}-py3-none-any.whl" in root
    assert f"taut_pg-{version}-py3-none-any.whl" in pg
    assert f"taut_summon-{version}-py3-none-any.whl" in root
    assert f"taut_summon-{version}-py3-none-any.whl" in summon
    assert "taut_summon-X.Y.Z-py3-none-any.whl" not in root
    assert "simplebroker>=5.3.1" in root

    stale_tag = re.compile(r"@v(?!" + re.escape(version) + r"\b)\d+\.\d+\.\d+")
    stale_wheel = re.compile(
        r"taut_(?:pg|summon)-(?!"
        + re.escape(version)
        + r"\b)\d+\.\d+\.\d+-py3-none-any\.whl"
    )
    for text in (root, pg, summon):
        assert stale_tag.search(text) is None
        assert stale_wheel.search(text) is None
