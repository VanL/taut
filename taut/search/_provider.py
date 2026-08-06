"""Minimal internal physical-index contract for search providers."""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Protocol

from simplebroker.ext import SidecarSession


@dataclass(frozen=True, slots=True)
class IndexedDocument:
    """Canonical projection identity supplied to a physical provider."""

    message_ts: int
    thread: str
    text_sha256: str
    text_bytes: int
    segments: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SearchCandidate:
    """Provider candidate that core must later hydrate and revalidate."""

    message_ts: int
    thread: str
    text_sha256: str
    text_bytes: int


@dataclass(frozen=True, slots=True)
class ThreadWatermark:
    """Durable source frontier for one registered searchable thread."""

    known: bool
    message_ts: int | None


class SidecarAccessor(Protocol):
    """Bound ``Queue.sidecar`` shape supplied by core."""

    def __call__(
        self,
        *,
        transaction: bool = False,
    ) -> AbstractContextManager[SidecarSession]: ...


class SearchProvider(Protocol):
    """Small physical-index seam implemented by each SQL backend."""

    def ensure_schema(self) -> None: ...

    def replace_document(
        self,
        document: IndexedDocument,
        *,
        revision: int | None = None,
    ) -> bool: ...

    def delete_document(
        self,
        *,
        message_ts: int,
        thread: str,
        revision: int,
    ) -> bool: ...

    def applied_revision(self, message_ts: int) -> int | None: ...

    def retarget_threads(
        self,
        affected: tuple[tuple[str, str], ...],
        *,
        revision: int,
    ) -> None: ...

    def thread_watermark(self, thread: str) -> ThreadWatermark: ...

    def indexed_message_ids(self, thread: str) -> tuple[int, ...]: ...

    def record_reconciliation(
        self,
        thread: str,
        *,
        watermark: int | None,
        revision: int,
    ) -> bool: ...

    def next_reconciliation_thread(
        self,
        threads: tuple[str, ...],
    ) -> str | None: ...

    def requires_rebuild(self) -> bool: ...

    def begin_rebuild(self, scan_revision: int) -> int: ...

    def replace_rebuild_document(
        self,
        document: IndexedDocument,
        *,
        generation: int,
        revision: int,
    ) -> bool: ...

    def finish_rebuild(self, generation: int) -> None: ...

    def abort_rebuild(self, generation: int) -> None: ...

    def query(
        self,
        chunks: tuple[str, ...],
        *,
        before: int | None = None,
        limit: int,
    ) -> list[SearchCandidate]: ...

    def close(self) -> None: ...
