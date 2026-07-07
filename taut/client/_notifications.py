"""Notification inbox behavior for TautClient."""

from __future__ import annotations

from typing import Any, cast

from taut import addressing
from taut._exceptions import EmptyResultError

from ._base import _ClientBase, _json_dumps
from ._codec import notification_from_body
from ._models import Notification


class NotificationsMixin(_ClientBase):
    def inbox(self, *, limit: int = 1000) -> list[Notification]:
        resolved = self._resolve_member(create=False)
        member = self._require_member(resolved)
        queue = self.queue(addressing.notification_queue_name(member["member_id"]))
        rows = cast(list[tuple[str, int]], queue.read_many(limit, with_timestamps=True))
        notifications = [notification_from_body(body, ts) for body, ts in rows]
        if not notifications:
            raise EmptyResultError("nothing pending")
        return notifications

    def _write_notification(self, *, to_id: str, payload: dict[str, Any]) -> None:
        queue = self.queue(addressing.notification_queue_name(to_id))
        try:
            ts = queue.generate_timestamp()
            queue.insert_messages([(_json_dumps(payload), ts)])
        except Exception as exc:  # pragma: no cover - backend-specific warning path.
            # Entries carry their own context; the CLI renders each one
            # verbatim under a bare "warning: " prefix.
            self.last_notification_warnings.append(
                f"notification delivery failed: {exc}"
            )
