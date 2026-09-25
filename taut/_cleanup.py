"""Helpers for cleanup paths that must preserve an earlier failure."""

from __future__ import annotations

from collections.abc import Callable


def cleanup_failure(action: Callable[[], None]) -> Exception | None:
    """Run one cleanup action and return its ordinary failure, if any."""

    try:
        action()
    except Exception as exc:  # noqa: BLE001 approved [DOM-10.2.1] [RUFF-SUP-092] exception
        return exc
    return None


def capture_cleanup_failure(
    failure: Exception | None,
    action: Callable[[], None],
) -> Exception | None:
    """Run cleanup and retain the first ordinary failure for later reporting."""

    current = cleanup_failure(action)
    return failure if failure is not None else current
