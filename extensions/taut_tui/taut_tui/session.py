"""Serialized public-client ownership for the Taut TUI extension session.

Spec references:
- docs/specs/10-taut-tui.md [TUI-4.1], [TUI-6]
"""

from __future__ import annotations

import threading
from collections import deque
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, TypeVar

from taut import EmptyResultError
from taut.client import Message, Notification, TautClient, Thread

if TYPE_CHECKING:
    from taut.watcher import TautWatcher

Delivery = Message | Notification
_ResultT = TypeVar("_ResultT")


@dataclass(frozen=True, slots=True)
class NavigationSnapshot:
    """Actor-scoped navigation assembled only from public projections."""

    channels: tuple[Thread, ...]
    direct_messages: tuple[Thread, ...]
    subthreads: tuple[Thread, ...]


@dataclass(frozen=True, slots=True)
class ConversationSnapshot:
    """One bounded cursor-neutral transcript ready for UI-loop commit."""

    generation: int
    target: str
    messages: tuple[Message, ...]
    reply_thread: str | None = None
    reply_messages: tuple[Message, ...] = ()
    intent_token: int | None = None


class WatcherStopTimeout(RuntimeError):
    """The prior watcher did not release its owner within the bounded join."""


class TuiSession:
    """Own one persistent client on one serialized worker thread."""

    def __init__(
        self,
        *,
        db_path: str | None,
        as_name: str | None,
        auth_token: str | None,
        commit_conversation: Callable[[ConversationSnapshot], bool] | None = None,
        accept_delivery: Callable[[int, Delivery], bool] | None = None,
        history_limit: int = 200,
        watcher_stop_timeout: float = 2.0,
    ) -> None:
        self._db_path = db_path
        self._as_name = as_name
        self._auth_token = auth_token
        self._commit_conversation = commit_conversation or (lambda _snapshot: True)
        self._accept_delivery = accept_delivery or (lambda _generation, _item: True)
        self._history_limit = history_limit
        self._watcher_stop_timeout = watcher_stop_timeout
        self._executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="taut-tui-session",
        )
        self._state_lock = threading.Lock()
        self._desired_generation = 0
        self._closed = False
        self._client: TautClient | None = None
        self._watcher: tuple[TautWatcher, threading.Thread] | None = None
        self._conversation: ConversationSnapshot | None = None
        self._notification_feed: deque[Notification] = deque(maxlen=200)

    def refresh_navigation(self) -> Future[NavigationSnapshot]:
        self._ensure_accepting()
        return self._executor.submit(self._refresh_navigation_owned)

    def submit_client_operation(
        self,
        operation: Callable[[TautClient], _ResultT],
    ) -> Future[_ResultT]:
        """Run one public-client operation on the serialized client owner."""

        self._ensure_accepting()
        return self._executor.submit(self._invoke_owned, operation)

    def conversation_snapshot(self) -> ConversationSnapshot | None:
        with self._state_lock:
            return self._conversation

    def notification_feed(self) -> tuple[Notification, ...]:
        with self._state_lock:
            return tuple(self._notification_feed)

    def commit_returned_message(self, item: Message) -> ConversationSnapshot | None:
        """Commit a successful send result without waiting for watcher replay."""

        with self._state_lock:
            snapshot = self._conversation
            if snapshot is None or item.thread not in {
                snapshot.target,
                snapshot.reply_thread,
            }:
                return snapshot
            if item.thread == snapshot.reply_thread:
                snapshot = replace(
                    snapshot,
                    reply_messages=_append_unique(snapshot.reply_messages, item),
                )
            elif item.thread == snapshot.target:
                snapshot = replace(
                    snapshot,
                    messages=_append_unique(snapshot.messages, item),
                )
            else:
                return snapshot
            self._conversation = snapshot
            return snapshot

    def open_conversation(
        self,
        target: str,
        *,
        reply_thread: str | None = None,
        intent_token: int | None = None,
    ) -> Future[ConversationSnapshot | None]:
        with self._state_lock:
            if self._closed:
                raise RuntimeError("TUI session is closed")
            self._desired_generation += 1
            generation = self._desired_generation
        return self._executor.submit(
            self._open_conversation_owned,
            generation,
            target,
            reply_thread,
            intent_token,
        )

    def open_history_context(
        self,
        target: str,
        messages: tuple[Message, ...],
        *,
        intent_token: int | None = None,
    ) -> Future[ConversationSnapshot | None]:
        """Open already-hydrated cursor-neutral context, then watch its target."""

        with self._state_lock:
            if self._closed:
                raise RuntimeError("TUI session is closed")
            self._desired_generation += 1
            generation = self._desired_generation
        return self._executor.submit(
            self._open_history_context_owned,
            generation,
            target,
            messages,
            intent_token,
        )

    def close(self) -> None:
        with self._state_lock:
            if self._closed:
                return
            self._closed = True
            self._desired_generation += 1
        future = self._executor.submit(self._close_owned)
        try:
            future.result(timeout=self._watcher_stop_timeout + 5.0)
        finally:
            self._executor.shutdown(wait=False, cancel_futures=False)

    def _ensure_accepting(self) -> None:
        with self._state_lock:
            if self._closed:
                raise RuntimeError("TUI session is closed")

    def _current_generation(self, generation: int) -> bool:
        with self._state_lock:
            return not self._closed and generation == self._desired_generation

    def _client_owned(self) -> TautClient:
        if self._client is None:
            self._client = TautClient(
                db_path=self._db_path,
                as_name=self._as_name,
                token=self._auth_token,
                persistent=True,
            )
        return self._client

    def _invoke_owned(
        self,
        operation: Callable[[TautClient], _ResultT],
    ) -> _ResultT:
        client = self._client_owned()
        return operation(client)

    def _refresh_navigation_owned(self) -> NavigationSnapshot:
        client = self._client_owned()
        joined = set(client.joined_thread_names())
        threads = client.list_threads(all_threads=True)
        channels = tuple(
            sorted(
                (
                    thread
                    for thread in threads
                    if thread.kind == "channel" and thread.name in joined
                ),
                key=lambda thread: thread.name,
            )
        )
        subthreads = tuple(
            sorted(
                (thread for thread in threads if thread.kind == "subthread"),
                key=lambda thread: (thread.parent or "", thread.name),
            )
        )
        try:
            direct_messages = tuple(client.list_direct_messages())
        except EmptyResultError:
            direct_messages = ()
        return NavigationSnapshot(
            channels=channels,
            direct_messages=direct_messages,
            subthreads=subthreads,
        )

    def _open_conversation_owned(
        self,
        generation: int,
        target: str,
        reply_thread: str | None,
        intent_token: int | None,
    ) -> ConversationSnapshot | None:
        self._stop_watcher_owned()
        if not self._current_generation(generation):
            return None
        client = self._client_owned()
        claimed_replies = self._open_reply_owned(client, reply_thread)
        snapshot = self._load_snapshot_owned(
            client,
            generation,
            target,
            reply_thread,
            claimed_replies,
            intent_token,
        )
        if snapshot is None or not self._commit_conversation(snapshot):
            return None
        with self._state_lock:
            self._conversation = snapshot
        if not self._current_generation(generation):
            return None
        self._start_watcher_owned(client, snapshot)
        return snapshot

    def _open_history_context_owned(
        self,
        generation: int,
        target: str,
        messages: tuple[Message, ...],
        intent_token: int | None,
    ) -> ConversationSnapshot | None:
        self._stop_watcher_owned()
        if not self._current_generation(generation):
            return None
        client = self._client_owned()
        snapshot = ConversationSnapshot(
            generation=generation,
            target=target,
            messages=messages,
            intent_token=intent_token,
        )
        if not self._commit_conversation(snapshot):
            return None
        with self._state_lock:
            self._conversation = snapshot
        if not self._current_generation(generation):
            return None
        self._start_watcher_owned(client, snapshot)
        return snapshot

    def _open_reply_owned(
        self,
        client: TautClient,
        reply_thread: str | None,
    ) -> tuple[Message, ...]:
        if reply_thread is None:
            return ()
        try:
            return tuple(client.read_unread(reply_thread))
        except EmptyResultError:
            return ()

    def _load_snapshot_owned(
        self,
        client: TautClient,
        generation: int,
        target: str,
        reply_thread: str | None,
        claimed_replies: tuple[Message, ...],
        intent_token: int | None,
    ) -> ConversationSnapshot | None:
        try:
            messages = tuple(client.log(target, limit=self._history_limit))
        except EmptyResultError:
            messages = ()
        reply_messages = claimed_replies
        if reply_thread is not None:
            try:
                reply_history = tuple(
                    client.log(reply_thread, limit=self._history_limit)
                )
            except EmptyResultError:
                pass
            else:
                reply_messages = _merge_messages(reply_history, claimed_replies)
        if not self._current_generation(generation):
            return None
        return ConversationSnapshot(
            generation=generation,
            target=target,
            messages=messages,
            reply_thread=reply_thread,
            reply_messages=reply_messages,
            intent_token=intent_token,
        )

    def _start_watcher_owned(
        self,
        client: TautClient,
        snapshot: ConversationSnapshot,
    ) -> None:
        generation = snapshot.generation

        def handle(item: Delivery) -> None:
            from taut import WatcherRejected

            if isinstance(item, Notification):
                with self._state_lock:
                    self._notification_feed.append(item)
                self._accept_delivery(generation, item)
                return
            if isinstance(item, Message) and not self._current_generation(generation):
                raise WatcherRejected
            if isinstance(item, Message):
                self._append_message(generation, item)
            if not self._accept_delivery(generation, item):
                if isinstance(item, Message):
                    self._remove_message(generation, item)
                raise WatcherRejected

        filters = [snapshot.target]
        if (
            snapshot.reply_thread is not None
            and snapshot.reply_thread != snapshot.target
        ):
            filters.append(snapshot.reply_thread)
        watcher = client.watch(handle, threads=filters)
        try:
            thread = watcher.start()
        except BaseException:
            watcher.stop(join=False)
            raise
        self._watcher = (watcher, thread)

    def _append_message(self, generation: int, item: Message) -> None:
        with self._state_lock:
            snapshot = self._conversation
            if snapshot is None or snapshot.generation != generation:
                return
            if item.thread == snapshot.reply_thread:
                self._conversation = replace(
                    snapshot,
                    reply_messages=_append_unique(snapshot.reply_messages, item),
                )
            elif item.thread == snapshot.target:
                self._conversation = replace(
                    snapshot,
                    messages=_append_unique(snapshot.messages, item),
                )

    def _remove_message(self, generation: int, item: Message) -> None:
        with self._state_lock:
            snapshot = self._conversation
            if snapshot is None or snapshot.generation != generation:
                return
            if item.thread == snapshot.reply_thread:
                self._conversation = replace(
                    snapshot,
                    reply_messages=_without_message(snapshot.reply_messages, item),
                )
            else:
                self._conversation = replace(
                    snapshot,
                    messages=_without_message(snapshot.messages, item),
                )

    def _stop_watcher_owned(self) -> None:
        owned = self._watcher
        if owned is None:
            return
        watcher, thread = owned
        watcher.request_stop()
        watcher.stop(join=True, timeout=self._watcher_stop_timeout)
        if thread.is_alive():
            raise WatcherStopTimeout(
                "active watcher did not stop; refusing to start a replacement"
            )
        watcher.stop(join=False)
        self._watcher = None

    def _close_owned(self) -> None:
        self._stop_watcher_owned()
        if self._client is not None:
            self._client.close()
            self._client = None


def _append_unique(messages: tuple[Message, ...], item: Message) -> tuple[Message, ...]:
    identity = (item.thread, item.ts)
    if any((message.thread, message.ts) == identity for message in messages):
        return messages
    return tuple(sorted((*messages, item), key=lambda row: row.ts))


def _merge_messages(
    *groups: tuple[Message, ...],
) -> tuple[Message, ...]:
    by_identity = {
        (message.thread, message.ts): message for group in groups for message in group
    }
    return tuple(sorted(by_identity.values(), key=lambda row: row.ts))


def _without_message(
    messages: tuple[Message, ...],
    item: Message,
) -> tuple[Message, ...]:
    return tuple(
        message
        for message in messages
        if (message.thread, message.ts) != (item.thread, item.ts)
    )


__all__ = [
    "ConversationSnapshot",
    "Delivery",
    "NavigationSnapshot",
    "TuiSession",
    "WatcherStopTimeout",
]
