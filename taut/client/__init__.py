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

from taut import addressing
from taut._constants import (
    META_QUEUE_NAME,
    load_config,
)
from taut._exceptions import MembershipError, TautError
from taut.state import MemberRow, SqlSidecarTautState, dialect_for_taut_target

from ._base import (
    _ClientBase,
    _raise_invalid_project_config,
    _raise_with_backend_install_hint,
)
from ._identity import IdentityMixin
from ._messaging import MessagingMixin
from ._models import (
    Channel,
    InitResult,
    Member,
    Message,
    MessageDeletion,
    MessageReaction,
    Notification,
    SearchHit,
    Thread,
)
from ._notifications import NotificationsMixin
from ._searching import SearchingMixin
from ._threads import ThreadsMixin

if TYPE_CHECKING:
    from taut.watcher import TautWatcher

logger = logging.getLogger(__name__)


def _validate_sqlite_path(
    path: Path,
    *,
    platform: str | None = None,
) -> None:
    """Reject Windows control-bearing paths before broker lock setup."""

    effective_platform = os.name if platform is None else platform
    if effective_platform == "nt" and any(
        ord(character) < 0x20 for character in str(path)
    ):
        raise TautError(
            "invalid SQLite database path on Windows: control characters are not allowed"
        )


__all__ = [
    "Channel",
    "InitResult",
    "Member",
    "Message",
    "MessageDeletion",
    "MessageReaction",
    "Notification",
    "SearchHit",
    "TautClient",
    "Thread",
    "database_path_from_target",
]


class TautClient(
    IdentityMixin,
    MessagingMixin,
    NotificationsMixin,
    SearchingMixin,
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
        if db_file is not None:
            _validate_sqlite_path(db_file)
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

    def _canonical_watch_threads(
        self,
        parsed_threads: list[tuple[str, addressing.TargetAddress | None]],
        member: MemberRow,
    ) -> list[str]:
        canonical_threads: list[str] = []
        seen: set[str] = set()
        missing: set[str] = set()
        for selector, dm_selector in parsed_threads:
            if dm_selector is not None:
                canonical = self._resolve_direct_message(
                    selector,
                    member,
                ).thread["name"]
            else:
                canonical = addressing.validate_chat_thread_name(
                    selector,
                    allow_subthread=True,
                )
                if (
                    self._state.get_membership(
                        thread=canonical,
                        member_id=member["member_id"],
                    )
                    is None
                ):
                    missing.add(canonical)
            if canonical not in seen:
                canonical_threads.append(canonical)
                seen.add(canonical)
        if missing:
            raise MembershipError(
                "not a member of watched thread(s): " + ", ".join(sorted(missing))
            )
        return canonical_threads

    def watch(
        self,
        handler: Callable[[Message | Notification], None],
        *,
        threads: list[str] | None = None,
        persistent: bool = True,
    ) -> TautWatcher:
        from taut.client._watching import _watch_runtime_for_client
        from taut.watcher import TautWatcher

        self.last_thread_display_names.clear()
        self._ensure_no_incomplete_channel_rename()
        parsed_threads = (
            [(selector, addressing.parse_dm_selector(selector)) for selector in threads]
            if threads is not None
            else None
        )
        has_dm_selector = bool(
            parsed_threads
            and any(
                dm_selector is not None for _selector, dm_selector in parsed_threads
            )
        )
        resolved = self._resolve_member(
            create=False,
            _heal_claim=not has_dm_selector,
        )
        member = self._require_member(resolved)
        for membership in self._state.list_memberships(member["member_id"]):
            row = self._state.get_thread(membership["thread"])
            if row is None or row["kind"] != "dm":
                continue
            context = self._direct_message_context(row["name"], member)
            if context is not None:
                self._remember_direct_message_display_name(context)
        canonical_threads = (
            self._canonical_watch_threads(parsed_threads, member)
            if parsed_threads is not None
            else None
        )
        runtime = _watch_runtime_for_client(
            self,
            persistent=persistent,
            member_id=member["member_id"],
        )
        try:
            return TautWatcher(
                runtime,
                member["member_id"],
                handler,
                threads=canonical_threads,
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
