"""Bounded retained delivery observations at the real session callback."""

from __future__ import annotations

from collections.abc import Callable
from threading import Event, Lock
from typing import Any

from _completion import Completion, CompletionKey, CompletionScope

from taut.client import Message, Notification


class InitialDrainEvent(Event):
    """Retain the real watcher's ready signal, including its publication time."""

    def __init__(self, scope: CompletionScope, watcher: object) -> None:
        super().__init__()
        self.completion = scope.expect(
            CompletionKey(watcher, "watcher.initial_drain", request=self)
        )
        self._publish_lock = Lock()
        self._published = False

    def set(self) -> None:
        super().set()
        with self._publish_lock:
            if not self._published:
                self._published = True
                self.completion.succeed(self.completion.key, None)


class SessionDeliveries:
    """One session's exact generation/thread/timestamp delivery outcomes."""

    def __init__(self, accept: Callable[[int, Message | Notification], bool]) -> None:
        self.scope = CompletionScope()
        self._accept = accept
        self._owner: Any = None
        self._lock = Lock()
        self._records: dict[tuple[int, str, int], Completion[Message]] = {}
        self._closed = False

    def bind(self, session: Any) -> None:
        if self._owner is not None:
            raise AssertionError("one session per delivery observation")
        self._owner = session

    def _record(self, generation: int, item: Message) -> Completion[Message]:
        identity = (generation, item.thread, item.ts)
        if identity not in self._records:
            if self._owner is None or len(self._records) >= 16:
                raise AssertionError("unbound or overflowing delivery observation")
            self._records[identity] = self.scope.expect(
                CompletionKey(self._owner, "delivery.accepted", item, generation)
            )
        return self._records[identity]

    def accept(self, generation: int, item: Message | Notification) -> bool:
        accepted = self._accept(generation, item)
        if isinstance(item, Message):
            with self._lock:
                if not self._closed:
                    record = self._record(generation, item)
                    if accepted:
                        record.succeed(record.key, item)
                    else:
                        record.supersede(record.key)
        return accepted

    def wait(self, generation: int, item: Message, *, deadline: float) -> Message:
        with self._lock:
            record = self._record(generation, item)
        return record.wait_sync(deadline=deadline, description="session delivery")

    def close(self) -> None:
        with self._lock:
            self._closed = True
            self.scope.close()
            self.scope.raise_if_invalid()
            self._records.clear()
