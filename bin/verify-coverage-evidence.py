#!/usr/bin/env python3
"""Verify that combined coverage contains the plan's named execution evidence."""

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
    Path("extensions/taut_summon/taut_summon/_driver.py"): (
        "return SummonDriver(request).run()"
    ),
    Path("extensions/taut_summon/taut_summon/_control.py"): (
        "self._reconcile_audit_threads()"
    ),
    Path("extensions/taut_summon/taut_summon/cli.py"): (
        "args = parser.parse_args(list(argv) if argv is not None else sys.argv[1:])"
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


def missing_evidence(
    data_file: Path,
    *,
    project_root: Path = PROJECT_ROOT,
) -> list[str]:
    data = CoverageData(basename=str(data_file))
    data.read()
    measured = {
        str(Path(candidate).resolve()): data.lines(candidate) or []
        for candidate in data.measured_files()
    }
    missing: list[str] = []
    for relative_path, marker in REQUIRED_MARKERS.items():
        source = (project_root / relative_path).resolve()
        line = _marker_line(source, marker)
        if line not in measured.get(str(source), []):
            missing.append(f"{relative_path}:{line} ({marker})")
    return missing


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Require named child-process and critical Summon coverage lines."
    )
    parser.add_argument(
        "--data-file",
        type=Path,
        default=PROJECT_ROOT / ".coverage",
        help="Combined Coverage data file (default: repository .coverage).",
    )
    args = parser.parse_args()
    missing = missing_evidence(args.data_file)
    if missing:
        parser.error("missing executed coverage evidence: " + "; ".join(missing))
    print("Named child-process and critical Summon coverage evidence is present.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
