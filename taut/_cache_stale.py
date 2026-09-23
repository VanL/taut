"""Publish advisory cache invalidation after commit [IAN-6.1], [IAN-7.4]."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable

from simplebroker import Queue

logger = logging.getLogger(__name__)


def publish_cache_stale(queue: Callable[[], Queue], *, reason: str) -> None:
    """Use an owner's queue factory; failed hints never undo committed work.

    Readers must refresh for every hint, including their own: this write can
    coalesce an unseen peer's hint. Payload is for inspection, never filtering.
    """

    try:
        queue().write(json.dumps({"reason": reason}), keep_newest=1)
    except Exception:  # noqa: BLE001 - post-commit advisory publication boundary
        logger.warning("cache invalidation publication failed (%s)", reason)
