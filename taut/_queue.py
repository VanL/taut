"""Taut queue adapter with Taut's broker retry policy."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from typing import Any, Literal, TypeVar

from simplebroker import Queue
from simplebroker.ext import SidecarSession

from taut._broker_retry import broker_retry

T = TypeVar("T")
MessageIdInput = int | str


class _RetryingSidecarSession:
    def __init__(self, session: SidecarSession, *, queue_name: str) -> None:
        self._session = session
        self._queue_name = queue_name

    def run(
        self,
        sql: str,
        params: tuple[Any, ...] = (),
        *,
        fetch: bool = False,
    ) -> Iterable[tuple[Any, ...]]:
        return broker_retry(
            lambda: self._session.run(sql, params, fetch=fetch),
            what=f"sidecar SQL for {self._queue_name}",
        )

    def close(self) -> None:
        self._session.close()


class RetryingQueue(Queue):
    """SimpleBroker queue whose public operations use Taut's retry policy."""

    def generate_timestamp(self) -> int:
        return broker_retry(
            super().generate_timestamp,
            what=f"generate timestamp for {self.name}",
        )

    def has_pending(self, after_timestamp: int | None = None) -> bool:
        return broker_retry(
            lambda: super(RetryingQueue, self).has_pending(after_timestamp),
            what=f"has pending for {self.name}",
        )

    def insert_messages(self, records: Iterable[tuple[str, MessageIdInput]]) -> None:
        materialized = tuple(records)
        broker_retry(
            lambda: super(RetryingQueue, self).insert_messages(materialized),
            what=f"insert messages for {self.name}",
        )

    def peek_many(
        self,
        limit: int = 1000,
        *,
        with_timestamps: bool = False,
        after_timestamp: int | None = None,
        before_timestamp: int | None = None,
        include_claimed: bool = False,
    ) -> list[str] | list[tuple[str, int]]:
        return broker_retry(
            lambda: super(RetryingQueue, self).peek_many(
                limit,
                with_timestamps=with_timestamps,
                after_timestamp=after_timestamp,
                before_timestamp=before_timestamp,
                include_claimed=include_claimed,
            ),
            what=f"peek {self.name}",
        )

    def read_many(
        self,
        limit: int,
        *,
        with_timestamps: bool = False,
        delivery_guarantee: Literal["exactly_once", "at_least_once"] = "exactly_once",
        after_timestamp: int | None = None,
        before_timestamp: int | None = None,
    ) -> list[str] | list[tuple[str, int]]:
        return broker_retry(
            lambda: super(RetryingQueue, self).read_many(
                limit,
                with_timestamps=with_timestamps,
                delivery_guarantee=delivery_guarantee,
                after_timestamp=after_timestamp,
                before_timestamp=before_timestamp,
            ),
            what=f"read {self.name}",
        )

    def latest_pending_timestamp(self) -> int | None:
        return broker_retry(
            super().latest_pending_timestamp,
            what=f"latest pending timestamp for {self.name}",
        )

    @contextmanager
    def sidecar(self, *, transaction: bool = False) -> Iterator[Any]:
        holder: dict[str, Any] = {}

        def open_session() -> SidecarSession:
            manager = super(RetryingQueue, self).sidecar(transaction=transaction)
            session = manager.__enter__()
            holder["manager"] = manager
            return session

        session = broker_retry(open_session, what=f"open sidecar for {self.name}")
        wrapped = _RetryingSidecarSession(session, queue_name=self.name)
        manager = holder["manager"]
        try:
            yield wrapped
        except Exception as exc:
            suppress = manager.__exit__(type(exc), exc, exc.__traceback__)
            if not suppress:
                raise
        else:
            manager.__exit__(None, None, None)


__all__ = ["RetryingQueue"]
