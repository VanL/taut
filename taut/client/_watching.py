"""Client-owned adapter for live watcher runtime needs."""

from __future__ import annotations

from simplebroker import BrokerSession, BrokerTarget, Config, Queue

from taut._cleanup import capture_cleanup_failure
from taut._constants import META_QUEUE_NAME
from taut._watch_runtime import WatchedThread
from taut.state import SqlSidecarTautState, dialect_for_taut_target

from ._base import _ClientBase, _direct_message_context_for_state
from ._codec import message_from_body, notification_from_body
from ._models import Message, Notification


class _OwnedWatchRuntime:
    """Watcher-owned state handle independent from the source client."""

    def __init__(
        self,
        target: BrokerTarget | str,
        config: Config,
        *,
        persistent: bool,
        member_id: str | None = None,
        thread_display_names: dict[str, str] | None = None,
    ) -> None:
        self.target = target
        self.config = config
        self._session: BrokerSession | None = None
        self._queue: Queue | None = None
        self._closed = False
        try:
            if persistent:
                self._session = BrokerSession.connect(target, config=self.config)
                queue = self._session.queue(META_QUEUE_NAME)
            else:
                queue = Queue(
                    META_QUEUE_NAME,
                    db_path=target,
                    persistent=False,
                    config=self.config,
                )
            self._queue = queue
            self._state = SqlSidecarTautState(
                queue,
                dialect_for_taut_target(target),
            )
        except BaseException as exc:
            cleanup = self._session.close if self._session is not None else None
            if cleanup is None and self._queue is not None:
                cleanup = self._queue.close
            cleanup_exc = (
                capture_cleanup_failure(None, cleanup) if cleanup is not None else None
            )
            if cleanup_exc is not None:
                exc.add_note(
                    f"watch runtime construction cleanup failed: {cleanup_exc}"
                )
            raise
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
        if self._session is not None:
            self._session.close()
            self._session = None
        elif self._queue is not None:
            self._queue.close()
        self._queue = None
        self._closed = True

    def recycle_thread(self) -> None:
        """Release construction-thread resources before watcher handoff."""

        if self._session is not None:
            self._session.recycle_thread()


def _watch_runtime_for_client(
    client: _ClientBase,
    *,
    persistent: bool = True,
    member_id: str | None = None,
) -> _OwnedWatchRuntime:
    return _OwnedWatchRuntime(
        client.target,
        client.config,
        persistent=persistent,
        member_id=member_id,
        thread_display_names=client.last_thread_display_names,
    )
