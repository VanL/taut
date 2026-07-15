"""Notification inbox behavior for TautClient."""

from __future__ import annotations

from typing import Any, cast

from taut import addressing
from taut._exceptions import EmptyResultError

from ._base import _ClientBase, _json_dumps
from ._codec import notification_from_body
from ._models import Notification


class NotificationsMixin(_ClientBase):
    def peek_inbox(self, *, limit: int = 1000) -> list[Notification]:
        """Return pending notifications without claiming them.

        Governed by [TAUT-8.3] and [IAN-7.4].
        """

        if limit < 1:
            raise ValueError("limit must be positive")
        return self._notification_records(limit=limit, consume=False)

    def inbox(self, *, limit: int = 1000) -> list[Notification]:
        notifications = self._notification_records(limit=limit, consume=True)
        if not notifications:
            raise EmptyResultError("nothing pending")
        return notifications

    def _notification_records(
        self,
        *,
        limit: int,
        consume: bool,
    ) -> list[Notification]:
        """Select and decode notification records through the core-owned path."""

        resolved = self._resolve_member(
            create=False,
            _touch_activity=consume,
        )
        member = self._require_member(resolved)
        queue = self.queue(addressing.notification_queue_name(member["member_id"]))
        read = queue.read_many if consume else queue.peek_many
        rows = cast(list[tuple[str, int]], read(limit, with_timestamps=True))
        return [notification_from_body(body, ts) for body, ts in rows]

    def _write_notification(self, *, to_id: str, payload: dict[str, Any]) -> None:
        queue = self.queue(addressing.notification_queue_name(to_id))
        try:
            queue.write(_json_dumps(payload))
        except Exception as exc:  # pragma: no cover - backend-specific warning path.
            # Entries carry their own context; the CLI renders each one
            # verbatim under a bare "warning: " prefix.
            self.last_notification_warnings.append(
                f"notification delivery failed: {exc}"
            )
