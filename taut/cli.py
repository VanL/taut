"""Thin console entry point for the registry-backed Taut CLI."""

from __future__ import annotations

import sys
from collections.abc import Sequence

from taut.commands._dispatch import dispatch


def main(argv: Sequence[str] | None = None) -> int:
    """Dispatch explicit argv, or the current process arguments when omitted."""

    return dispatch(sys.argv[1:] if argv is None else argv)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
