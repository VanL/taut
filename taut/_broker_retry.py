"""Bounded retry policy for transient SimpleBroker/SQLite faults.

This module stays on SimpleBroker's public exception surface. It exists because
SQLite under process churn can occasionally surface retryable connection/open
or page-read faults outside SimpleBroker's ordinary lock retry paths.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import TypeVar

from simplebroker.ext import BrokerError, DatabaseError, OperationalError

logger = logging.getLogger(__name__)

T = TypeVar("T")

_BROKER_RETRIES = 30
_BROKER_RETRY_DELAY = 0.05
_BROKER_RETRY_MAX_DELAY = 0.5

_LOCKED_MARKERS = (
    "database is locked",
    "database table is locked",
    "database schema is locked",
    "database is busy",
    "database busy",
)
_MALFORMED_MARKER = "malformed"
_DISK_IO_MARKER = "disk i/o error"
_MAGIC_MISMATCH_MARKER = "database magic string mismatch"
_CONNECTION_FAILURE_MARKER = "failed to get database connection:"
_INVALID_INT_MARKER = "invalid literal for int()"
_NONE_INT_MARKER = (
    "int() argument must be a string, a bytes-like object or a real number, "
    "not 'nonetype'"
)


def is_transient_broker_error(exc: Exception) -> bool:
    """Return whether *exc* is a bounded-retry broker concurrency fault."""

    retryable = getattr(exc, "retryable", None)
    if retryable is not None:
        return bool(retryable)

    message = str(exc).lower()
    if isinstance(exc, OperationalError):
        return (
            _DISK_IO_MARKER in message
            or _MALFORMED_MARKER in message
            or any(marker in message for marker in _LOCKED_MARKERS)
        )
    if isinstance(exc, DatabaseError):
        return _MALFORMED_MARKER in message or _MAGIC_MISMATCH_MARKER in message
    if isinstance(exc, RuntimeError) and _CONNECTION_FAILURE_MARKER in message:
        return (
            _MALFORMED_MARKER in message
            or _DISK_IO_MARKER in message
            or _MAGIC_MISMATCH_MARKER in message
            or any(marker in message for marker in _LOCKED_MARKERS)
        )
    if isinstance(exc, (TypeError, ValueError, BrokerError)):
        return _INVALID_INT_MARKER in message or _NONE_INT_MARKER in message
    return False


def broker_retry(
    fn: Callable[[], T],
    *,
    what: str,
    attempts: int = _BROKER_RETRIES,
) -> T:
    """Run one broker operation, retrying only known transient failures."""

    delay = _BROKER_RETRY_DELAY
    for attempt in range(1, attempts + 1):
        try:
            return fn()
        except Exception as exc:
            if attempt >= attempts or not is_transient_broker_error(exc):
                raise
            logger.debug("transient broker error on %s; retrying: %s", what, exc)
            time.sleep(delay)
            delay = min(delay * 2, _BROKER_RETRY_MAX_DELAY)
    raise AssertionError("unreachable broker retry loop exit")


__all__ = [
    "_BROKER_RETRIES",
    "broker_retry",
    "is_transient_broker_error",
]
