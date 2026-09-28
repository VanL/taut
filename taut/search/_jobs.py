"""Durable pending search invalidations.

Spec references:
- docs/specs/06-search.md [SRCH-8.1], [SRCH-8.2], [SRCH-9.2]
"""

from __future__ import annotations

import json
from collections.abc import Generator
from dataclasses import dataclass
from typing import Final, Literal

from simplebroker import Queue
from simplebroker.ext import TimestampError, TimestampGenerator

from taut import addressing
from taut._exceptions import ThreadNameError

PENDING_QUEUE_NAME: Final[str] = "taut.search_index"
CLAIMED_QUEUE_NAME: Final[str] = "taut.search_index.claimed"
FAILED_QUEUE_NAME: Final[str] = "taut.search_index.failed"

StructuralErrorCode = Literal[
    "duplicate_field",
    "invalid_entity",
    "invalid_rename",
    "invalid_json",
    "invalid_message_ts",
    "invalid_thread",
    "invalid_version",
    "not_object",
    "unexpected_fields",
]
_MESSAGE_FIELDS: Final[frozenset[str]] = frozenset(
    {"entity", "message_ts", "thread", "v"}
)
_RENAME_FIELDS: Final[frozenset[str]] = frozenset(
    {"affected", "entity", "new", "old", "v"}
)


class MalformedSearchJob(ValueError):
    """A work body failed the closed version-one structural contract."""

    def __init__(self, code: StructuralErrorCode) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class MessageJob:
    """Content-free invalidation for one canonical source message."""

    message_ts: int
    thread: str


@dataclass(frozen=True, slots=True)
class ThreadRenameJob:
    """Content-free completed channel/subthread rename invalidation."""

    old: str
    new: str
    affected: tuple[tuple[str, str], ...]


SearchJob = MessageJob | ThreadRenameJob


def encode_message_job(*, message_ts: int, thread: str) -> str:
    """Encode the exact single-line version-one message work shape."""

    job = MessageJob(
        message_ts=_validate_message_ts(message_ts),
        thread=_validate_source_thread(thread),
    )
    return json.dumps(
        {
            "entity": "message",
            "message_ts": job.message_ts,
            "thread": job.thread,
            "v": 1,
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def decode_message_job(body: str) -> MessageJob:
    """Decode one strict message job or raise a bounded structural code."""

    if not isinstance(body, str):
        raise TypeError("search job body must be a string")
    try:
        value = json.loads(body, object_pairs_hook=_unique_object)
    except MalformedSearchJob:
        raise
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise MalformedSearchJob("invalid_json") from exc
    if not isinstance(value, dict):
        raise MalformedSearchJob("not_object")
    if frozenset(value) != _MESSAGE_FIELDS:
        raise MalformedSearchJob("unexpected_fields")
    if type(value["v"]) is not int or value["v"] != 1:
        raise MalformedSearchJob("invalid_version")
    if value["entity"] != "message":
        raise MalformedSearchJob("invalid_entity")
    try:
        message_ts = _validate_message_ts(value["message_ts"])
    except (TypeError, ValueError) as exc:
        raise MalformedSearchJob("invalid_message_ts") from exc
    try:
        thread = _validate_source_thread(value["thread"])
    except (TypeError, ValueError) as exc:
        raise MalformedSearchJob("invalid_thread") from exc
    return MessageJob(message_ts=message_ts, thread=thread)


def encode_thread_rename_job(
    *,
    old: str,
    new: str,
    affected: list[dict[str, str]],
) -> str:
    old_name = _validate_rename_thread(old)
    new_name = _validate_rename_thread(new)
    pairs = _validate_affected(affected)
    if pairs[0] != (old_name, new_name):
        raise ValueError("first affected rename must match old/new")
    return json.dumps(
        {
            "affected": [
                {"new": new_name, "old": old_name} for old_name, new_name in pairs
            ],
            "entity": "thread_rename",
            "new": new_name,
            "old": old_name,
            "v": 1,
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def decode_thread_rename_job(body: str) -> ThreadRenameJob:
    """Decode one strict completed-rename invalidation."""

    if not isinstance(body, str):
        raise TypeError("search job body must be a string")
    try:
        value = json.loads(body, object_pairs_hook=_unique_object)
    except MalformedSearchJob:
        raise
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise MalformedSearchJob("invalid_json") from exc
    if not isinstance(value, dict):
        raise MalformedSearchJob("not_object")
    if frozenset(value) != _RENAME_FIELDS:
        raise MalformedSearchJob("unexpected_fields")
    if type(value["v"]) is not int or value["v"] != 1:
        raise MalformedSearchJob("invalid_version")
    if value["entity"] != "thread_rename":
        raise MalformedSearchJob("invalid_entity")
    try:
        old = _validate_rename_thread(value["old"])
        new = _validate_rename_thread(value["new"])
        pairs = _validate_affected(value["affected"])
        if pairs[0] != (old, new):
            raise ValueError("first affected rename must match old/new")
    except (TypeError, ValueError) as exc:
        raise MalformedSearchJob("invalid_rename") from exc
    return ThreadRenameJob(old=old, new=new, affected=pairs)


def decode_search_job(body: str) -> SearchJob:
    """Dispatch one closed version-one work entity to its strict decoder."""

    if not isinstance(body, str):
        raise TypeError("search job body must be a string")
    try:
        value = json.loads(body, object_pairs_hook=_unique_object)
    except MalformedSearchJob:
        raise
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise MalformedSearchJob("invalid_json") from exc
    if not isinstance(value, dict):
        raise MalformedSearchJob("not_object")
    if value.get("entity") == "thread_rename":
        return decode_thread_rename_job(body)
    return decode_message_job(body)


@dataclass(slots=True)
class JobQueues:
    """Caller-owned pending invalidations. Source and index remain authoritative."""

    pending: Queue

    def enqueue_message(self, *, message_ts: int, thread: str) -> int:
        return self.pending.write(
            encode_message_job(message_ts=message_ts, thread=thread)
        )

    def work_frontier(self) -> int | None:
        """Capture a finite boundary without consuming work."""

        return self.pending.latest_pending_timestamp()

    def pending_rows_through(self, frontier: int) -> Generator[tuple[str, int]]:
        """Read the captured work without claiming it."""

        after: int | None = None
        while True:
            page = self.pending.peek_many(
                1000,
                with_timestamps=True,
                after_timestamp=after,
                before_timestamp=frontier + 1,
            )
            if not page:
                return
            yield from page
            after = page[-1][1]


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise MalformedSearchJob("duplicate_field")
        value[key] = item
    return value


def _validate_message_ts(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("message_ts must be an integer")
    try:
        return TimestampGenerator.validate(str(value), exact=True)
    except TimestampError as exc:
        raise ValueError("message_ts must be a full message id") from exc


def _validate_source_thread(value: object) -> str:
    if not isinstance(value, str):
        raise TypeError("thread must be a string")
    if value.startswith("dm."):
        if addressing.DM_SELECTOR_RE.fullmatch(value) is None:
            raise ValueError("invalid direct-message thread")
        return value
    return _validate_rename_thread(value)


def _validate_rename_thread(value: object) -> str:
    if not isinstance(value, str):
        raise TypeError("thread must be a string")
    try:
        validated = addressing.validate_chat_thread_name(
            value,
            allow_subthread=True,
        )
    except ThreadNameError as exc:
        raise ValueError("invalid search thread") from exc
    if validated != value:
        raise ValueError("thread must be canonical")
    return value


def _validate_affected(value: object) -> tuple[tuple[str, str], ...]:
    if not isinstance(value, list) or not value:
        raise TypeError("affected must be a non-empty list")
    pairs: list[tuple[str, str]] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, dict) or frozenset(item) != {"old", "new"}:
            raise ValueError("affected entries require exact old/new fields")
        old = _validate_rename_thread(item["old"])
        new = _validate_rename_thread(item["new"])
        if old in seen:
            raise ValueError("affected old names must be unique")
        seen.add(old)
        pairs.append((old, new))
    return tuple(pairs)


__all__ = [
    "PENDING_QUEUE_NAME",
    "JobQueues",
    "MalformedSearchJob",
    "MessageJob",
    "SearchJob",
    "ThreadRenameJob",
    "decode_message_job",
    "decode_search_job",
    "decode_thread_rename_job",
    "encode_message_job",
    "encode_thread_rename_job",
]
