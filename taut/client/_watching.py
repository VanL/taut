"""Client-owned adapter for live watcher runtime needs."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from simplebroker import BrokerTarget

from taut._watch_runtime import TautWatchRuntime, WatchedThread
from taut.state import TautState

from ._base import _ClientBase
from ._codec import message_from_body, notification_from_body
from ._models import Message, Notification


@dataclass(frozen=True, slots=True)
class _ClientWatchRuntime:
    target: BrokerTarget | str
    config: Mapping[str, Any]
    state: TautState

    def list_watched_threads(self, member_id: str) -> list[WatchedThread]:
        return [
            WatchedThread(name=row["thread"], last_seen_ts=row["last_seen_ts"])
            for row in self.state.list_memberships(member_id)
        ]

    def decode_message(self, thread: str, body: str, ts: int) -> Message:
        return message_from_body(thread, body, ts)

    def decode_notification(self, body: str, ts: int) -> Notification:
        return notification_from_body(body, ts)

    def advance_cursor(self, *, thread: str, member_id: str, seen_ts: int) -> None:
        self.state.advance_cursor(
            thread=thread,
            member_id=member_id,
            seen_ts=seen_ts,
        )


def _watch_runtime_for_client(client: _ClientBase) -> TautWatchRuntime:
    return _ClientWatchRuntime(
        target=client.target,
        config=client.config,
        state=client._state,
    )
