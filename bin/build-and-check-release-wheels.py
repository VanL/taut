"""Build and check one fresh paired Taut/Taut Summon release-wheel set."""  # noqa: N999 approved [DOM-10.2.1] [RUFF-SUP-075] exception

from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import NoReturn

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SUMMON_ROOT = PROJECT_ROOT / "extensions" / "taut_summon"
WHEEL_MATRIX_CHECKER = PROJECT_ROOT / "bin" / "check-core-summon-wheel-matrix.py"
HISTORICAL_SUMMON_REF = "taut_summon/v0.5.4"
HISTORICAL_MCP_REF = "taut_mcp/v0.9.5"


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


def _print_dry_run_plan(
    *,
    core_output: Path,
    summon_output: Path,
    core_wheel: Path | None = None,
    summon_wheel: Path | None = None,
) -> None:
    commands: list[tuple[str, ...]] = []
    if core_wheel is None or summon_wheel is None:
        core_wheel = core_output / "<exactly-one-wheel>"
        summon_wheel = summon_output / "<exactly-one-wheel>"
        commands.extend(
            (
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
            )
        )
    commands.extend(
        (
            (
                sys.executable,
                str(WHEEL_MATRIX_CHECKER),
                "--new-core",
                str(core_wheel),
                "--new-summon",
                str(summon_wheel),
                "--historical-summon-ref",
                HISTORICAL_SUMMON_REF,
                "--historical-mcp-ref",
                HISTORICAL_MCP_REF,
            ),
        )
    )
    for command in commands:
        print("[release-wheels] + " + shlex.join(command), flush=True)


def build_and_check(
    *,
    dry_run: bool = False,
    core_wheel: Path | None = None,
    summon_wheel: Path | None = None,
) -> None:
    """Build wheels in fresh outputs, then check their explicit paths."""

    if (core_wheel is None) != (summon_wheel is None):
        _fail("core and Summon wheel paths must be supplied together")

    with tempfile.TemporaryDirectory(prefix="taut-release-wheels-") as temporary:
        artifact_root = Path(temporary)
        core_output = artifact_root / "core"
        summon_output = artifact_root / "summon"
        core_output.mkdir()
        summon_output.mkdir()

        if dry_run:
            _print_dry_run_plan(
                core_output=core_output,
                summon_output=summon_output,
                core_wheel=core_wheel,
                summon_wheel=summon_wheel,
            )
            return

        if core_wheel is None or summon_wheel is None:
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
        else:
            for wheel, label in ((core_wheel, "core"), (summon_wheel, "Summon")):
                if not wheel.is_file():
                    _fail(f"explicit {label} wheel does not exist: {wheel}")
                if wheel.suffix != ".whl":
                    _fail(f"explicit {label} artifact is not a wheel: {wheel}")

        _run(
            (
                sys.executable,
                str(WHEEL_MATRIX_CHECKER),
                "--new-core",
                str(core_wheel),
                "--new-summon",
                str(summon_wheel),
                "--historical-summon-ref",
                HISTORICAL_SUMMON_REF,
                "--historical-mcp-ref",
                HISTORICAL_MCP_REF,
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
    parser.add_argument(
        "--core-wheel",
        type=Path,
        help="Use this already-built current core wheel instead of building one.",
    )
    parser.add_argument(
        "--summon-wheel",
        type=Path,
        help="Use this already-built current Summon wheel instead of building one.",
    )
    args = parser.parse_args(argv)
    try:
        if args.core_wheel is None and args.summon_wheel is None:
            build_and_check(dry_run=args.dry_run)
        else:
            build_and_check(
                dry_run=args.dry_run,
                core_wheel=args.core_wheel,
                summon_wheel=args.summon_wheel,
            )
    except ReleaseWheelCheckError as exc:
        print(f"release-wheel check failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
