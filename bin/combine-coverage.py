"""Validate and combine raw Coverage data shards."""  # noqa: N999 approved [DOM-10.2.1] [RUFF-SUP-075] exception

from __future__ import annotations

import argparse
import warnings
from collections.abc import Sequence
from pathlib import Path

from coverage import Coverage, CoverageData
from coverage.exceptions import CoverageException, CoverageWarning

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class CoverageCombineError(Exception):
    """A raw shard could not be validated or combined."""


def _raw_shards(input_directory: Path) -> tuple[Path, ...]:
    try:
        shards = tuple(
            sorted(path for path in input_directory.rglob("*") if path.is_file())
        )
    except OSError as exc:
        raise CoverageCombineError(
            f"could not enumerate coverage shards in {input_directory}: {exc}"
        ) from exc

    if not shards:
        raise CoverageCombineError(
            f"no coverage shard files found in {input_directory}"
        )

    for shard in shards:
        try:
            size = shard.stat().st_size
        except OSError as exc:
            raise CoverageCombineError(
                f"could not inspect coverage shard {shard}: {exc}"
            ) from exc
        if size == 0:
            raise CoverageCombineError(f"coverage shard is zero-byte: {shard}")

    return shards


def _validate_shard(shard: Path) -> None:
    try:
        data = CoverageData(basename=str(shard))
        data.read()
    except (CoverageException, OSError) as exc:
        raise CoverageCombineError(
            f"could not read coverage shard {shard}: {exc}"
        ) from exc


def combine_coverage(input_directory: Path, output: Path) -> None:
    """Validate all raw shards, combine them, and save ``output``."""
    shards = _raw_shards(input_directory)
    for shard in shards:
        _validate_shard(shard)

    coverage = Coverage(data_file=str(output))
    data_paths = sorted({str(shard.parent) for shard in shards})
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", CoverageWarning)
            coverage.combine(data_paths=data_paths, strict=True, keep=True)
        coverage.save()
    except CoverageWarning as exc:
        raise CoverageCombineError(f"coverage combine warning: {exc}") from exc
    except (CoverageException, OSError) as exc:
        raise CoverageCombineError(
            f"could not combine coverage shards from {input_directory}: {exc}"
        ) from exc


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate and combine raw Coverage data shards."
    )
    parser.add_argument(
        "input_directory",
        type=Path,
        help="Directory containing raw Coverage data shards.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / ".coverage",
        help="Combined Coverage data file (default: repository .coverage).",
    )
    args = parser.parse_args(argv)
    try:
        combine_coverage(args.input_directory, args.output)
    except CoverageCombineError as exc:
        parser.error(str(exc))
    print(f"Combined validated coverage shards into {args.output}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
