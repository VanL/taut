"""Helpers for cleanup paths that must preserve an earlier failure."""

from __future__ import annotations

from collections.abc import Callable


def capture_cleanup_failure(
    failure: Exception | None,
    action: Callable[[], None],
) -> Exception | None:
    """Run cleanup and retain the first ordinary failure for later reporting."""

    try:
        action()
    except Exception as exc:  # noqa: BLE001 approved [DOM-10.2.1] [RUFF-SUP-092] exception
        return failure if failure is not None else exc
    return failure
