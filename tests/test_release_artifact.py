from __future__ import annotations

import importlib.util
import json
import sys
import tarfile
import zipfile
from pathlib import Path
from types import ModuleType

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = PROJECT_ROOT / "bin" / "release-artifact.py"

pytestmark = pytest.mark.sqlite_only


def _load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("release_artifact", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _package(tmp_path: Path, *, name: str = "taut-pg", version: str = "1.2.3") -> Path:
    package = tmp_path / "package"
    package.mkdir()
    (package / "pyproject.toml").write_text(
        f'[project]\nname = "{name}"\nversion = "{version}"\n',
        encoding="utf-8",
    )
    return package


def _distributions(
    tmp_path: Path, *, name: str = "taut-pg", version: str = "1.2.3"
) -> Path:
    dist = tmp_path / "dist"
    dist.mkdir()
    stem = name.replace("-", "_")
    metadata = f"Metadata-Version: 2.4\nName: {name}\nVersion: {version}\n\n"
    wheel = dist / f"{stem}-{version}-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr(f"{stem}-{version}.dist-info/METADATA", metadata)
    sdist = dist / f"{name}-{version}.tar.gz"
    payload = tmp_path / "PKG-INFO"
    payload.write_text(metadata, encoding="utf-8")
    with tarfile.open(sdist, "w:gz") as archive:
        archive.add(payload, arcname=f"{name}-{version}/PKG-INFO")
    (dist / ".gitignore").write_text("*\n", encoding="utf-8")
    return dist


def _bundle(tmp_path: Path) -> tuple[ModuleType, Path, Path, str]:
    module = _load_module()
    package = _package(tmp_path)
    dist = _distributions(tmp_path)
    bundle = tmp_path / "bundle"
    commit = "a" * 40
    module.create_bundle(
        package_dir=package,
        dist_dir=dist,
        output_dir=bundle,
        commit=commit,
    )
    return module, package, bundle, commit


def test_create_and_verify_bundle_with_normalized_package_name(tmp_path: Path) -> None:
    module, package, bundle, commit = _bundle(tmp_path)
    publish = tmp_path / "publish"

    files = module.verify_bundle(
        package_dir=package,
        bundle_dir=bundle,
        expected_commit=commit,
        expected_tag_name="taut_pg/v1.2.3",
        output_dir=publish,
    )

    manifest = json.loads((bundle / "release-manifest.json").read_text("utf-8"))
    assert manifest["format"] == 1
    assert manifest["commit"] == commit
    assert manifest["package"] == {"name": "taut-pg", "version": "1.2.3"}
    assert {entry["name"] for entry in manifest["files"]} == {
        "taut_pg-1.2.3-py3-none-any.whl",
        "taut-pg-1.2.3.tar.gz",
    }
    assert {path.name for path in files} == {path.name for path in publish.iterdir()}


def test_verify_bundle_accepts_only_mcp_tag_family(tmp_path: Path) -> None:
    module = _load_module()
    package = _package(tmp_path, name="taut-mcp")
    dist = _distributions(tmp_path, name="taut-mcp")
    bundle = tmp_path / "bundle"
    commit = "a" * 40
    module.create_bundle(
        package_dir=package,
        dist_dir=dist,
        output_dir=bundle,
        commit=commit,
    )

    module.verify_bundle(
        package_dir=package,
        bundle_dir=bundle,
        expected_commit=commit,
        expected_tag_name="taut_mcp/v1.2.3",
        output_dir=None,
    )
    for invalid_tag in (
        "v1.2.3",
        "taut_mcp/1.2.3",
        "taut_mcp/v1.2.4",
        "taut_pg/v1.2.3",
    ):
        with pytest.raises(module.ReleaseArtifactError, match="release tag"):
            module.verify_bundle(
                package_dir=package,
                bundle_dir=bundle,
                expected_commit=commit,
                expected_tag_name=invalid_tag,
                output_dir=None,
            )


@pytest.mark.parametrize(
    ("mutation", "message"),
    (
        ("commit", "commit"),
        ("format", "format"),
        ("version", "version"),
        ("digest", "digest"),
        ("extra", "allowlist"),
        ("extra-directory", "allowlist"),
        ("missing", "allowlist"),
        ("malformed-tag", "release tag"),
        ("wrong-tag-family", "release tag"),
        ("wrong-tag-version", "release tag"),
    ),
)
def test_verify_bundle_fails_closed_for_each_manifest_contract(
    tmp_path: Path, mutation: str, message: str
) -> None:
    module, package, bundle, commit = _bundle(tmp_path)
    manifest_path = bundle / "release-manifest.json"
    manifest = json.loads(manifest_path.read_text("utf-8"))
    tag_name = "taut_pg/v1.2.3"

    if mutation == "commit":
        commit = "b" * 40
    elif mutation == "format":
        manifest["format"] = 2
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    elif mutation == "version":
        manifest["package"]["version"] = "1.2.4"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    elif mutation == "digest":
        artifact = bundle / manifest["files"][0]["name"]
        artifact.write_bytes(artifact.read_bytes() + b"corrupt")
    elif mutation == "extra":
        (bundle / "unexpected.whl").write_bytes(b"extra")
    elif mutation == "extra-directory":
        unexpected = bundle / "unexpected"
        unexpected.mkdir()
        (unexpected / "payload").write_bytes(b"extra")
    elif mutation == "missing":
        (bundle / manifest["files"][0]["name"]).unlink()
    elif mutation == "malformed-tag":
        tag_name = "taut_pg/1.2.3"
    elif mutation == "wrong-tag-family":
        tag_name = "v1.2.3"
    elif mutation == "wrong-tag-version":
        tag_name = "taut_pg/v1.2.4"

    with pytest.raises(module.ReleaseArtifactError, match=message):
        module.verify_bundle(
            package_dir=package,
            bundle_dir=bundle,
            expected_commit=commit,
            expected_tag_name=tag_name,
            output_dir=None,
        )


def test_cli_failure_is_concise_without_traceback(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    module = _load_module()
    package = _package(tmp_path)

    result = module.main(
        [
            "verify",
            "--package-dir",
            str(package),
            "--bundle-dir",
            str(tmp_path / "missing"),
            "--commit",
            "a" * 40,
            "--tag-name",
            "taut_pg/v1.2.3",
        ]
    )

    assert result == 1
    stderr = capsys.readouterr().err
    assert "release artifact verification failed:" in stderr
    assert "Traceback" not in stderr
