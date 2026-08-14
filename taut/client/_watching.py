"""Client-owned adapter for live watcher runtime needs."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from simplebroker import BrokerTarget, Queue, ResolvedConfig

from taut._constants import META_QUEUE_NAME, freeze_broker_config
from taut._watch_runtime import TautWatchRuntime, WatchedThread
from taut.state import SqlSidecarTautState, dialect_for_taut_target

from ._base import _ClientBase, _direct_message_context_for_state
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
        member_id: str | None = None,
        thread_display_names: dict[str, str] | None = None,
    ) -> None:
        self.target = target
        self.config: ResolvedConfig = freeze_broker_config(config)
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
        self._member_id = member_id
        self._thread_display_names = thread_display_names

    def list_watched_threads(self, member_id: str) -> list[WatchedThread]:
        return [
            WatchedThread(name=row["thread"], last_seen_ts=row["last_seen_ts"])
            for row in self._state.list_memberships(member_id)
        ]

    def decode_message(self, thread: str, body: str, ts: int) -> Message:
        if (
            self._member_id is not None
            and self._thread_display_names is not None
            and thread.startswith("dm.")
        ):
            actor = self._state.get_member(self._member_id)
            if actor is not None:
                context = _direct_message_context_for_state(
                    self._state,
                    thread,
                    actor,
                )
                if context is not None:
                    self._thread_display_names[thread] = (
                        f"DM with {context.other['display_name']}"
                    )
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
    member_id: str | None = None,
) -> TautWatchRuntime:
    return _OwnedWatchRuntime(
        client.target,
        client.config,
        persistent=persistent,
        member_id=member_id,
        thread_display_names=client.last_thread_display_names,
    )
