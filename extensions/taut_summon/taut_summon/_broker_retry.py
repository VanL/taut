"""taut-summon's broker-specific retry policy, over the generic engine.

Mirrors simplebroker's own layering: the generic, re-vendorable loop lives
in ``_retry.py`` and the domain-specific policy — which errors are
transient, how many attempts, how to back off — sits on top here, the way
``simplebroker/helpers.py`` layers ``_execute_with_retry`` /
``_execute_watcher_operational_retry`` over the same engine.

``_retry.py`` is **vendored byte-for-byte** from ``simplebroker/_retry.py``
(simplebroker 5.1.0), which is published as a copy-me module for exactly
this use. It is kept pristine (no local edits) so it stays a diffable
drop-in copy; all provenance lives here, not inside that file. Re-vendor by
re-copying the upstream file when its ``__version__`` bumps. taut's
facades-only rule forbids importing ``simplebroker._retry`` directly, which
is why the engine is vendored rather than imported.

Spec reference: docs/specs/04-summon.md [SUM-9] (control-plane retry defense).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TypeVar

from simplebroker.ext import DatabaseError, OperationalError

from taut_summon._retry import execute_retry, expo, stop_after_attempt

logger = logging.getLogger("taut_summon.broker")

T = TypeVar("T")

_BROKER_RETRIES = 8
_BROKER_RETRY_DELAY = 0.05

# The two — and only two — WAL-under-concurrency transients we ride out,
# matched by message text so a genuinely broken DB is NOT masked. Lock/busy
# markers mirror simplebroker's own ``_LOCKED_ERROR_MARKERS``; the malformed
# marker is the *false* SQLITE_CORRUPT read a fresh reader can see while a
# writer checkpoints (which clears on retry, unlike true corruption — but a
# persistently-malformed DB still exhausts the bounded budget and re-raises).
_LOCKED_MARKERS = (
    "database is locked",
    "database table is locked",
    "database schema is locked",
    "database is busy",
    "database busy",
)
_MALFORMED_MARKER = "malformed"


def is_transient_broker_error(exc: Exception) -> bool:
    """Whether a broker op failure is a retryable WAL-under-concurrency blip.

    Narrow by design. Only two specific transients qualify — lock/busy
    contention (``OperationalError`` whose message is a known lock marker)
    and the *false* ``database disk image is malformed`` page read
    (``DatabaseError`` — SQLITE_CORRUPT, which does **not** subclass
    ``OperationalError``, so simplebroker's own watcher-retry predicate
    would miss it). Every other ``OperationalError``/``DatabaseError``,
    and all ``IntegrityError``/``DataError``, surface immediately — a
    generic operational failure or genuine corruption must not be masked.
    An explicit ``retryable`` attribute (non-SQLite backends set it) wins.
    """

    retryable = getattr(exc, "retryable", None)
    if retryable is not None:
        return bool(retryable)
    message = str(exc).lower()
    if isinstance(exc, OperationalError):
        return any(marker in message for marker in _LOCKED_MARKERS)
    if isinstance(exc, DatabaseError):
        return _MALFORMED_MARKER in message
    return False


def broker_retry(
    fn: Callable[[], T], *, what: str, attempts: int = _BROKER_RETRIES
) -> T:
    """Run a bare broker op, riding out transient WAL read errors.

    Bare ``read_one``/``write`` on the control queues go through this so a
    command or reply is not lost to a checkpoint-race transient (core's
    watcher retries its own ops; bare ops do not). A persistent failure —
    real corruption, or a non-transient class — is re-raised after the
    bounded budget, so nothing genuinely broken is masked.
    """

    def _log(state: object, exc: Exception, delay: float) -> None:
        logger.debug("transient broker error on %s; retrying: %s", what, exc)

    return execute_retry(
        fn,
        retry_on=is_transient_broker_error,
        wait_gen=expo,
        wait_gen_kwargs={"base": 2, "factor": _BROKER_RETRY_DELAY},
        stop=stop_after_attempt(attempts),
        before_sleep=_log,
    )
