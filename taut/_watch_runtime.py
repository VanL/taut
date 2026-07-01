"""Internal watcher runtime seam.

Spec references:
- docs/specs/02-taut-core.md [TAUT-8.4], [TAUT-12.2]
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

from simplebroker import BrokerTarget

if TYPE_CHECKING:
    from taut.client._models import Message, Notification


@dataclass(frozen=True, slots=True)
class WatchedThread:
    name: str
    last_seen_ts: int


class TautWatchRuntime(Protocol):
    @property
    def target(self) -> BrokerTarget | str: ...

    @property
    def config(self) -> Mapping[str, Any]: ...

    def list_watched_threads(self, member_id: str) -> list[WatchedThread]: ...

    def decode_message(self, thread: str, body: str, ts: int) -> Message: ...

    def decode_notification(self, body: str, ts: int) -> Notification: ...

    def advance_cursor(self, *, thread: str, member_id: str, seen_ts: int) -> None: ...
