"""Check that combined coverage executed every required cross-process path."""  # noqa: N999 approved [DOM-10.2.1] [RUFF-SUP-075] exception

from __future__ import annotations

import argparse
from pathlib import Path

from coverage import CoverageData

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# These are behavior-bearing lines, not import lines. The two entry-point lines
# can execute only in child interpreters in the configured coverage probes.
REQUIRED_MARKERS = {
    Path("taut/__main__.py"): "raise SystemExit(main())",
    Path("extensions/taut_summon/taut_summon/scripted_provider.py"): (
        "raise SystemExit(main())"
    ),
    Path("extensions/taut_summon/taut_summon/_driver.py"): (").run()"),
    Path("extensions/taut_summon/taut_summon/_control.py"): (
        "self._reconcile_audit_threads()"
    ),
    Path("extensions/taut_summon/taut_summon/cli.py"): (
        "args = parser.parse_args(list(argv) if argv is not None else sys.argv[1:])"
    ),
    Path("extensions/taut_mcp/taut_mcp/_process_reactor.py"): (
        "self._bucket_tokens -= 1.0"
    ),
}


def _marker_line(path: Path, marker: str) -> int:
    matches = [
        number
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if marker in line
    ]
    if len(matches) != 1:
        raise ValueError(f"expected one coverage marker {marker!r} in {path}")
    return matches[0]


def _has_relative_suffix(candidate: str, relative_path: Path) -> bool:
    candidate_parts = tuple(
        part for part in candidate.replace("\\", "/").split("/") if part
    )
    relative_parts = relative_path.parts
    return candidate_parts[-len(relative_parts) :] == relative_parts


def missing_required_paths(
    data_file: Path,
    *,
    project_root: Path = PROJECT_ROOT,
) -> list[str]:
    data = CoverageData(basename=str(data_file))
    data.read()
    measured = {
        candidate: data.lines(candidate) or [] for candidate in data.measured_files()
    }
    missing: list[str] = []
    for relative_path, marker in REQUIRED_MARKERS.items():
        source = (project_root / relative_path).resolve()
        line = _marker_line(source, marker)
        matching_files = [
            (candidate, lines)
            for candidate, lines in measured.items()
            if _has_relative_suffix(candidate, relative_path)
        ]
        description = f"{relative_path.as_posix()}:{line} ({marker})"
        if len(matching_files) > 1:
            missing.append(
                f"{description} [ambiguous coverage data: "
                f"{len(matching_files)} files match]"
            )
            continue
        covered_lines = matching_files[0][1] if matching_files else []
        if line not in covered_lines:
            missing.append(description)
    return missing


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check required child-process and critical Summon coverage paths."
    )
    parser.add_argument(
        "--data-file",
        type=Path,
        default=PROJECT_ROOT / ".coverage",
        help="Combined Coverage data file (default: repository .coverage).",
    )
    args = parser.parse_args()
    missing = missing_required_paths(args.data_file)
    if missing:
        parser.error("required coverage paths were not executed: " + "; ".join(missing))
    print("Every required child-process and critical Summon path was executed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
