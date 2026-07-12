"""Public TautClient API.

Spec references:
- docs/specs/02-taut-core.md [TAUT-3], [TAUT-4], [TAUT-5], [TAUT-7], [TAUT-8.3]
- docs/specs/03-identity-addressing-notifications.md [IAN-3], [IAN-4],
  [IAN-5], [IAN-6], [IAN-7], [IAN-8]
"""

from __future__ import annotations

import logging
import os
import tomllib
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from simplebroker import (
    BrokerTarget,
    Queue,
    target_for_directory,
)

from taut._constants import (
    META_QUEUE_NAME,
    load_config,
)
from taut._exceptions import TautError
from taut.state import SqlSidecarTautState, dialect_for_taut_target

from ._base import (
    _ClientBase,
    _raise_invalid_project_config,
    _raise_with_backend_install_hint,
)
from ._identity import IdentityMixin
from ._messaging import MessagingMixin
from ._models import InitResult, Member, Message, Notification, Thread
from ._notifications import NotificationsMixin
from ._threads import ThreadsMixin

if TYPE_CHECKING:
    from taut.watcher import TautWatcher

logger = logging.getLogger(__name__)

__all__ = [
    "InitResult",
    "Member",
    "Message",
    "Notification",
    "TautClient",
    "Thread",
    "database_path_from_target",
]


class TautClient(
    IdentityMixin,
    MessagingMixin,
    NotificationsMixin,
    ThreadsMixin,
    _ClientBase,
):
    """Embedding surface for taut.

    The CLI is a renderer over this class; command semantics live here.
    """

    @classmethod
    def init(
        cls,
        *,
        db_path: str | Path | None = None,
    ) -> InitResult:
        """Create a taut database and install sidecar tables."""

        config = load_config()
        explicit = db_path or os.environ.get("TAUT_DB")
        db_file: Path | None
        if explicit is not None:
            path = Path(explicit).expanduser()
            target: BrokerTarget | str = str(path)
            db_file = path
        else:
            try:
                target_obj = target_for_directory(Path.cwd(), config=config)
            except tomllib.TOMLDecodeError as exc:
                _raise_invalid_project_config(exc)
            except RuntimeError as exc:
                _raise_with_backend_install_hint(exc)
            target = target_obj
            db_file = (
                Path(target_obj.target) if target_obj.backend_name == "sqlite" else None
            )
        created = False if db_file is None else not db_file.exists()
        if db_file is not None and created:
            # Fail fast with a one-line diagnostic: without this check an
            # unwritable target stalls for the full SimpleBroker setup
            # phase-lock timeout (~60s) before surfacing a lock-centric
            # error that buries the PermissionError.
            parent = db_file.parent
            if not parent.is_dir():
                raise TautError(f"cannot create {db_file}: {parent} is not a directory")
            if not os.access(parent, os.W_OK | os.X_OK):
                raise TautError(f"cannot create {db_file}: {parent} is not writable")
        queue = Queue(META_QUEUE_NAME, db_path=target, config=config)
        try:
            SqlSidecarTautState(
                queue,
                dialect_for_taut_target(target),
            ).ensure_schema()
        finally:
            queue.close()
        display_target = (
            str(db_file) if isinstance(target, str) else target.display_target
        )
        return InitResult(db=display_target, created=created)

    def watch(
        self,
        handler: Callable[[Message | Notification], None],
        *,
        threads: list[str] | None = None,
        persistent: bool = True,
    ) -> TautWatcher:
        from taut.client._watching import _watch_runtime_for_client
        from taut.watcher import TautWatcher

        self._ensure_no_incomplete_channel_rename()
        resolved = self._resolve_member(create=False)
        member = self._require_member(resolved)
        runtime = _watch_runtime_for_client(self, persistent=persistent)
        try:
            return TautWatcher(
                runtime,
                member["member_id"],
                handler,
                threads=threads,
                persistent=persistent,
            )
        except BaseException:
            try:
                runtime.close()
            except Exception:  # pragma: no cover - defensive third-party cleanup
                logger.debug(
                    "failed to close watch runtime after construction failure",
                    exc_info=True,
                )
            raise


def database_path_from_target(target: BrokerTarget | str) -> str:
    """Return a display path for a resolved target."""

    if isinstance(target, str):
        return target
    return target.target
