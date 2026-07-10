"""Client-owned adapter for live watcher runtime needs."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from simplebroker import BrokerTarget, Queue

from taut._constants import META_QUEUE_NAME
from taut._watch_runtime import TautWatchRuntime, WatchedThread
from taut.state import SqlSidecarTautState, dialect_for_taut_target

from ._base import _ClientBase
from ._codec import message_from_body, notification_from_body
from ._models import Message, Notification


class _OwnedWatchRuntime:
    """Watcher-owned state handle independent from the source client."""

    def __init__(
        self,
        target: BrokerTarget | str,
        config: Mapping[str, Any],
        *,
        persistent: bool,
    ) -> None:
        self.target = target
        self.config = dict(config)
        queue = Queue(
            META_QUEUE_NAME,
            db_path=target,
            persistent=persistent,
            config=self.config,
        )
        try:
            self._state = SqlSidecarTautState(
                queue,
                dialect_for_taut_target(target),
            )
        except BaseException:
            queue.close()
            raise
        self._queue = queue
        self._closed = False

    def list_watched_threads(self, member_id: str) -> list[WatchedThread]:
        return [
            WatchedThread(name=row["thread"], last_seen_ts=row["last_seen_ts"])
            for row in self._state.list_memberships(member_id)
        ]

    def decode_message(self, thread: str, body: str, ts: int) -> Message:
        return message_from_body(thread, body, ts)

    def decode_notification(self, body: str, ts: int) -> Notification:
        return notification_from_body(body, ts)

    def advance_cursor(self, *, thread: str, member_id: str, seen_ts: int) -> None:
        self._state.advance_cursor(
            thread=thread,
            member_id=member_id,
            seen_ts=seen_ts,
        )

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._queue.close()


def _watch_runtime_for_client(
    client: _ClientBase,
    *,
    persistent: bool = True,
) -> TautWatchRuntime:
    return _OwnedWatchRuntime(
        client.target,
        client.config,
        persistent=persistent,
    )
