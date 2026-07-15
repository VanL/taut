#!/usr/bin/env python3
"""Create and verify immutable release-distribution bundles."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
import tarfile
import tomllib
import zipfile
from email.parser import Parser
from pathlib import Path
from typing import Any, NoReturn

MANIFEST_NAME = "release-manifest.json"
MANIFEST_FORMAT = 1
RELEASE_TAG_PREFIXES = {
    "taut": "",
    "taut-pg": "taut_pg/",
    "taut-summon": "taut_summon/",
    "taut-mcp": "taut_mcp/",
}


class ReleaseArtifactError(RuntimeError):
    """One fail-closed release artifact diagnostic."""


def _fail(message: str) -> NoReturn:
    raise ReleaseArtifactError(message)


def _normalized_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _package_identity(package_dir: Path) -> tuple[str, str]:
    pyproject = package_dir / "pyproject.toml"
    try:
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        _fail(f"cannot read package manifest {pyproject}: {exc}")
    project = data.get("project")
    if not isinstance(project, dict):
        _fail(f"package manifest {pyproject} has no [project] table")
    name = project.get("name")
    version = project.get("version")
    if not isinstance(name, str) or not name:
        _fail(f"package manifest {pyproject} has no project name")
    if not isinstance(version, str) or not version:
        _fail(f"package manifest {pyproject} has no project version")
    return name, version


def _validate_commit(commit: str) -> None:
    if re.fullmatch(r"[0-9a-fA-F]{40}", commit) is None:
        _fail("commit must be an exact 40-character Git SHA")


def _validate_release_tag(*, package_name: str, version: str, tag_name: str) -> None:
    normalized_name = _normalized_name(package_name)
    prefix = RELEASE_TAG_PREFIXES.get(normalized_name)
    if prefix is None:
        _fail(f"release tag mapping is undefined for package {package_name!r}")
    expected = f"{prefix}v{version}"
    if tag_name != expected:
        _fail(
            f"release tag {tag_name!r} does not match {package_name} {version}; "
            f"expected {expected!r}"
        )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _metadata_identity(text: str, *, label: str) -> tuple[str, str]:
    metadata = Parser().parsestr(text)
    name = metadata.get("Name")
    version = metadata.get("Version")
    if not name or not version:
        _fail(f"{label} metadata must contain Name and Version")
    return name, version


def _wheel_identity(path: Path) -> tuple[str, str]:
    try:
        with zipfile.ZipFile(path) as archive:
            members = [
                name
                for name in archive.namelist()
                if name.endswith(".dist-info/METADATA")
            ]
            if len(members) != 1:
                _fail(f"wheel {path.name} must contain exactly one METADATA file")
            text = archive.read(members[0]).decode("utf-8")
    except (OSError, UnicodeDecodeError, zipfile.BadZipFile) as exc:
        _fail(f"cannot inspect wheel {path.name}: {exc}")
    return _metadata_identity(text, label=f"wheel {path.name}")


def _sdist_identity(path: Path) -> tuple[str, str]:
    try:
        with tarfile.open(path, "r:gz") as archive:
            members = [
                member
                for member in archive.getmembers()
                if member.isfile() and member.name.endswith("/PKG-INFO")
            ]
            if len(members) != 1:
                _fail(f"sdist {path.name} must contain exactly one PKG-INFO file")
            stream = archive.extractfile(members[0])
            if stream is None:
                _fail(f"cannot read sdist metadata from {path.name}")
            text = stream.read().decode("utf-8")
    except (OSError, UnicodeDecodeError, tarfile.TarError) as exc:
        _fail(f"cannot inspect sdist {path.name}: {exc}")
    return _metadata_identity(text, label=f"sdist {path.name}")


def _distribution_files(directory: Path) -> tuple[Path, Path]:
    try:
        files = sorted(
            path
            for path in directory.iterdir()
            if path.is_file() and path.name not in {MANIFEST_NAME, ".gitignore"}
        )
    except OSError as exc:
        _fail(f"cannot list distribution directory {directory}: {exc}")
    wheels = [path for path in files if path.name.endswith(".whl")]
    sdists = [path for path in files if path.name.endswith(".tar.gz")]
    if len(files) != 2 or len(wheels) != 1 or len(sdists) != 1:
        _fail(
            "distribution allowlist requires exactly one wheel and one .tar.gz "
            f"sdist; found {[path.name for path in files]}"
        )
    return wheels[0], sdists[0]


def _validate_distributions(
    directory: Path, *, expected_name: str, expected_version: str
) -> tuple[Path, Path]:
    wheel, sdist = _distribution_files(directory)
    for label, identity in (
        (wheel.name, _wheel_identity(wheel)),
        (sdist.name, _sdist_identity(sdist)),
    ):
        name, version = identity
        if _normalized_name(name) != _normalized_name(expected_name):
            _fail(f"{label} package name {name!r} does not match {expected_name!r}")
        if version != expected_version:
            _fail(
                f"{label} version {version!r} does not match expected version "
                f"{expected_version!r}"
            )
    return wheel, sdist


def _new_directory(path: Path, *, label: str) -> None:
    try:
        path.mkdir(parents=True, exist_ok=False)
    except FileExistsError:
        _fail(f"{label} already exists: {path}")
    except OSError as exc:
        _fail(f"cannot create {label} {path}: {exc}")


def create_bundle(
    *, package_dir: Path, dist_dir: Path, output_dir: Path, commit: str
) -> tuple[Path, ...]:
    """Copy one wheel/sdist pair into a manifest-bound bundle."""

    _validate_commit(commit)
    package_name, version = _package_identity(package_dir)
    distributions = _validate_distributions(
        dist_dir, expected_name=package_name, expected_version=version
    )
    _new_directory(output_dir, label="bundle directory")
    copied: list[Path] = []
    for source in distributions:
        target = output_dir / source.name
        shutil.copy2(source, target)
        copied.append(target)
    manifest = {
        "format": MANIFEST_FORMAT,
        "commit": commit.lower(),
        "package": {"name": package_name, "version": version},
        "files": [
            {"name": path.name, "sha256": _sha256(path)} for path in sorted(copied)
        ],
    }
    (output_dir / MANIFEST_NAME).write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return tuple(copied)


def _read_manifest(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        _fail(f"cannot read release manifest {path}: {exc}")
    if not isinstance(value, dict):
        _fail("release manifest must be a JSON object")
    if set(value) != {"format", "commit", "package", "files"}:
        _fail("release manifest has an invalid top-level field allowlist")
    return value


def verify_bundle(
    *,
    package_dir: Path,
    bundle_dir: Path,
    expected_commit: str,
    expected_tag_name: str,
    output_dir: Path | None,
) -> tuple[Path, ...]:
    """Verify provenance and bytes, then optionally copy publishable files."""

    _validate_commit(expected_commit)
    expected_name, expected_version = _package_identity(package_dir)
    _validate_release_tag(
        package_name=expected_name,
        version=expected_version,
        tag_name=expected_tag_name,
    )
    manifest = _read_manifest(bundle_dir / MANIFEST_NAME)
    if manifest["format"] != MANIFEST_FORMAT:
        _fail(f"unsupported release manifest format {manifest['format']!r}")
    if manifest["commit"] != expected_commit.lower():
        _fail("release manifest commit does not match the checked-out tag commit")
    package = manifest["package"]
    if not isinstance(package, dict) or set(package) != {"name", "version"}:
        _fail("release manifest package field has an invalid field allowlist")
    name = package["name"]
    version = package["version"]
    if not isinstance(name, str) or _normalized_name(name) != _normalized_name(
        expected_name
    ):
        _fail("release manifest package name does not match the package manifest")
    if version != expected_version:
        _fail("release manifest package version does not match the expected version")

    entries = manifest["files"]
    if not isinstance(entries, list) or len(entries) != 2:
        _fail("release manifest file allowlist must contain exactly two entries")
    expected_digests: dict[str, str] = {}
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {"name", "sha256"}:
            _fail("release manifest file entry has an invalid field allowlist")
        filename = entry["name"]
        digest = entry["sha256"]
        if (
            not isinstance(filename, str)
            or Path(filename).name != filename
            or filename == MANIFEST_NAME
        ):
            _fail("release manifest file allowlist contains an invalid filename")
        if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            _fail(f"release manifest digest is invalid for {filename!r}")
        if filename in expected_digests:
            _fail("release manifest file allowlist contains a duplicate filename")
        expected_digests[filename] = digest

    try:
        bundle_entries = sorted(bundle_dir.iterdir())
    except OSError as exc:
        _fail(f"cannot list release bundle {bundle_dir}: {exc}")
    expected_entries = {MANIFEST_NAME, *expected_digests}
    if {path.name for path in bundle_entries} != expected_entries or any(
        path.is_symlink() or not path.is_file() for path in bundle_entries
    ):
        _fail("release bundle files do not match the manifest allowlist")
    actual_files = tuple(path for path in bundle_entries if path.name != MANIFEST_NAME)
    _validate_distributions(
        bundle_dir, expected_name=expected_name, expected_version=expected_version
    )
    for path in actual_files:
        if _sha256(path) != expected_digests[path.name]:
            _fail(f"release bundle digest mismatch for {path.name}")

    if output_dir is None:
        return tuple(actual_files)
    _new_directory(output_dir, label="publish directory")
    copied: list[Path] = []
    for source in actual_files:
        target = output_dir / source.name
        shutil.copy2(source, target)
        copied.append(target)
    return tuple(copied)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    create = subparsers.add_parser("create", help="Create one release bundle.")
    create.add_argument("--package-dir", type=Path, required=True)
    create.add_argument("--dist-dir", type=Path, required=True)
    create.add_argument("--output-dir", type=Path, required=True)
    create.add_argument("--commit", required=True)
    verify = subparsers.add_parser("verify", help="Verify one release bundle.")
    verify.add_argument("--package-dir", type=Path, required=True)
    verify.add_argument("--bundle-dir", type=Path, required=True)
    verify.add_argument("--commit", required=True)
    verify.add_argument("--tag-name", required=True)
    verify.add_argument("--output-dir", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "create":
            create_bundle(
                package_dir=args.package_dir,
                dist_dir=args.dist_dir,
                output_dir=args.output_dir,
                commit=args.commit,
            )
        else:
            verify_bundle(
                package_dir=args.package_dir,
                bundle_dir=args.bundle_dir,
                expected_commit=args.commit,
                expected_tag_name=args.tag_name,
                output_dir=args.output_dir,
            )
    except (OSError, ReleaseArtifactError) as exc:
        action = "creation" if args.command == "create" else "verification"
        print(f"release artifact {action} failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
