#!/usr/bin/env python3
"""Build and check one fresh paired Taut/Taut Summon release-wheel set."""

from __future__ import annotations

import argparse
import re
import shlex
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path
from typing import NoReturn

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SUMMON_ROOT = PROJECT_ROOT / "extensions" / "taut_summon"
SUMMON_LOCK = SUMMON_ROOT / "uv.lock"
PG_ROOT = PROJECT_ROOT / "extensions" / "taut_pg"
PG_PYPROJECT = PG_ROOT / "pyproject.toml"
WHEEL_MATRIX_CHECKER = PROJECT_ROOT / "bin" / "check-core-summon-wheel-matrix.py"
PREVIOUS_CORE_REF = "v0.5.0"
PREVIOUS_SUMMON_REF = "taut_summon/v0.5.0"
PREVIOUS_COMMAND_CORE_REF = "v0.5.4"
PREVIOUS_COMMAND_SUMMON_REF = "taut_summon/v0.5.4"
MINIMUM_SIMPLEBROKER = (5, 3, 0)
MINIMUM_SIMPLEBROKER_PG = (3, 2, 0)
MINIMUM_TAUT = (0, 5, 1)


class ReleaseWheelCheckError(RuntimeError):
    """One fail-closed paired release-wheel build or check diagnostic."""


def _fail(message: str) -> NoReturn:
    raise ReleaseWheelCheckError(message)


def _run(command: tuple[str, ...]) -> None:
    print("[release-wheels] + " + shlex.join(command), flush=True)
    try:
        completed = subprocess.run(command, cwd=PROJECT_ROOT, check=False)
    except OSError as exc:
        _fail(f"could not start command: {shlex.join(command)}: {exc}")
    if completed.returncode != 0:
        _fail(
            f"command failed with exit code {completed.returncode}: "
            f"{shlex.join(command)}"
        )


def _single_wheel(output: Path, *, label: str) -> Path:
    wheels = sorted(output.glob("*.whl"))
    if len(wheels) != 1:
        _fail(f"{label} build produced {len(wheels)} wheels; expected exactly one")
    return wheels[0]


def _version_tuple(version: str, *, label: str) -> tuple[int, int, int]:
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", version)
    if match is None:
        _fail(f"{label} has unsupported version {version!r}; expected X.Y.Z")
    major, minor, patch = match.groups()
    return int(major), int(minor), int(patch)


def _check_retained_summon_lock(path: Path = SUMMON_LOCK) -> None:
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        _fail(f"cannot read retained Summon lock {path}: {exc}")
    versions = [
        package.get("version")
        for package in data.get("package", [])
        if package.get("name") == "simplebroker"
    ]
    if len(versions) != 1 or not isinstance(versions[0], str):
        _fail("retained Summon lock must resolve exactly one simplebroker version")
    version = versions[0]
    if _version_tuple(version, label="retained Summon simplebroker") < (
        MINIMUM_SIMPLEBROKER
    ):
        _fail(f"retained Summon lock resolved simplebroker {version} below 5.3.0")


def _check_pg_resolution(path: Path) -> None:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        _fail(f"cannot read ephemeral PG resolution {path}: {exc}")
    matches = re.findall(r"(?m)^simplebroker-pg==(\d+\.\d+\.\d+)$", text)
    if len(matches) != 1:
        _fail("ephemeral PG resolution must select exactly one simplebroker-pg==X.Y.Z")
    version = matches[0]
    if _version_tuple(version, label="ephemeral simplebroker-pg") < (
        MINIMUM_SIMPLEBROKER_PG
    ):
        _fail(f"ephemeral PG resolution selected simplebroker-pg {version} below 3.2.0")


def _check_pg_manifest(path: Path = PG_PYPROJECT) -> None:
    """Require explicit unmarked core and plugin floors in taut-pg metadata."""

    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        _fail(f"cannot read taut-pg manifest {path}: {exc}")
    dependencies = data.get("project", {}).get("dependencies", [])
    if not isinstance(dependencies, list) or not all(
        isinstance(dependency, str) for dependency in dependencies
    ):
        _fail("taut-pg manifest project.dependencies must be a string list")

    requirements = (
        ("taut", MINIMUM_TAUT, "0.5.1"),
        ("simplebroker-pg", MINIMUM_SIMPLEBROKER_PG, "3.2.0"),
    )
    for project, minimum, rendered_minimum in requirements:
        pattern = rf"{re.escape(project)}>=(\d+)\.(\d+)\.(\d+)"
        matches = [
            re.fullmatch(pattern, dependency)
            for dependency in dependencies
            if dependency.startswith(project)
        ]
        valid = [match for match in matches if match is not None]
        if (
            len(matches) != 1
            or len(valid) != 1
            or tuple(int(part) for part in valid[0].groups()) < minimum
        ):
            _fail(
                "taut-pg manifest must contain exactly one unmarked "
                f"{project}>=X.Y.Z with X.Y.Z >= {rendered_minimum}"
            )


def _print_dry_run_plan(*, core_output: Path, summon_output: Path) -> None:
    pg_resolution = core_output.parent / "pg-requirements.txt"
    core_wheel = core_output / "<exactly-one-wheel>"
    summon_wheel = summon_output / "<exactly-one-wheel>"
    commands = (
        (
            "uv",
            "build",
            "--wheel",
            "--out-dir",
            str(core_output),
            str(PROJECT_ROOT),
        ),
        (
            "uv",
            "build",
            "--wheel",
            "--out-dir",
            str(summon_output),
            str(SUMMON_ROOT),
        ),
        (
            "uv",
            "pip",
            "compile",
            str(PG_PYPROJECT),
            "--output-file",
            str(pg_resolution),
            "--quiet",
        ),
        (
            sys.executable,
            str(WHEEL_MATRIX_CHECKER),
            "--new-core",
            str(core_wheel),
            "--new-summon",
            str(summon_wheel),
            "--previous-core-ref",
            PREVIOUS_CORE_REF,
            "--previous-summon-ref",
            PREVIOUS_SUMMON_REF,
            "--previous-command-core-ref",
            PREVIOUS_COMMAND_CORE_REF,
            "--previous-command-summon-ref",
            PREVIOUS_COMMAND_SUMMON_REF,
        ),
    )
    for command in commands:
        print("[release-wheels] + " + shlex.join(command), flush=True)


def build_and_check(*, dry_run: bool = False) -> None:
    """Build wheels in fresh outputs, then check their explicit paths."""

    with tempfile.TemporaryDirectory(prefix="taut-release-wheels-") as temporary:
        artifact_root = Path(temporary)
        core_output = artifact_root / "core"
        summon_output = artifact_root / "summon"
        core_output.mkdir()
        summon_output.mkdir()

        if dry_run:
            _print_dry_run_plan(core_output=core_output, summon_output=summon_output)
            return

        _check_pg_manifest()
        _check_retained_summon_lock()

        _run(
            (
                "uv",
                "build",
                "--wheel",
                "--out-dir",
                str(core_output),
                str(PROJECT_ROOT),
            )
        )
        core_wheel = _single_wheel(core_output, label="core")

        _run(
            (
                "uv",
                "build",
                "--wheel",
                "--out-dir",
                str(summon_output),
                str(SUMMON_ROOT),
            )
        )
        summon_wheel = _single_wheel(summon_output, label="Summon")

        pg_resolution = artifact_root / "pg-requirements.txt"
        _run(
            (
                "uv",
                "pip",
                "compile",
                str(PG_PYPROJECT),
                "--output-file",
                str(pg_resolution),
                "--quiet",
            )
        )
        _check_pg_resolution(pg_resolution)

        _run(
            (
                sys.executable,
                str(WHEEL_MATRIX_CHECKER),
                "--new-core",
                str(core_wheel),
                "--new-summon",
                str(summon_wheel),
                "--previous-core-ref",
                PREVIOUS_CORE_REF,
                "--previous-summon-ref",
                PREVIOUS_SUMMON_REF,
                "--previous-command-core-ref",
                PREVIOUS_COMMAND_CORE_REF,
                "--previous-command-summon-ref",
                PREVIOUS_COMMAND_SUMMON_REF,
            )
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build and check fresh paired core/Summon release wheels."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the ordered fresh-build and wheel-matrix check commands.",
    )
    args = parser.parse_args(argv)
    try:
        build_and_check(dry_run=args.dry_run)
    except ReleaseWheelCheckError as exc:
        print(f"release-wheel check failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
