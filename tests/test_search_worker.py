from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from simplebroker import Queue

from taut.search._jobs import (
    PENDING_QUEUE_NAME,
    JobQueues,
    MessageJob,
    encode_thread_rename_job,
)
from taut.search._provider import IndexedDocument, SearchCandidate, ThreadWatermark
from taut.search._worker import process_one

pytestmark = pytest.mark.sqlite_only


@dataclass
class FakeProvider:
    revisions: dict[int, int] = field(default_factory=dict)
    live: dict[int, IndexedDocument] = field(default_factory=dict)
    fail_replace: bool = False
    applied_override: int | None = None
    calls: list[tuple[str, int, int]] = field(default_factory=list)
    watermarks: dict[str, tuple[int | None, int]] = field(default_factory=dict)
    rotation_cursor: str | None = None

    def schema_version(self) -> int:
        return 2

    def ensure_schema(self) -> None:
        pass

    def replace_document(
        self,
        document: IndexedDocument,
        *,
        revision: int | None = None,
    ) -> bool:
        assert revision is not None
        self.calls.append(("replace", document.message_ts, revision))
        if self.fail_replace:
            raise RuntimeError("provider unavailable")
        current = self.revisions.get(document.message_ts)
        if current is not None and revision <= current:
            return False
        self.revisions[document.message_ts] = revision
        self.live[document.message_ts] = document
        return True

    def delete_document(
        self,
        *,
        message_ts: int,
        thread: str,
        revision: int,
    ) -> bool:
        del thread
        self.calls.append(("delete", message_ts, revision))
        current = self.revisions.get(message_ts)
        if current is not None and revision <= current:
            return False
        self.revisions[message_ts] = revision
        self.live.pop(message_ts, None)
        return True

    def applied_revision(self, message_ts: int) -> int | None:
        if self.applied_override is not None:
            return self.applied_override
        return self.revisions.get(message_ts)

    def retarget_threads(
        self,
        affected: tuple[tuple[str, str], ...],
        *,
        revision: int,
    ) -> None:
        mapping = dict(affected)
        for message_ts, document in tuple(self.live.items()):
            if document.thread not in mapping:
                continue
            self.live[message_ts] = IndexedDocument(
                message_ts=document.message_ts,
                thread=mapping[document.thread],
                text_sha256=document.text_sha256,
                text_bytes=document.text_bytes,
                segments=document.segments,
            )
            self.revisions[message_ts] = revision

    def thread_watermark(self, thread: str) -> ThreadWatermark:
        if thread not in self.watermarks:
            return ThreadWatermark(known=False, message_ts=None)
        return ThreadWatermark(known=True, message_ts=self.watermarks[thread][0])

    def indexed_message_ids(self, thread: str) -> tuple[int, ...]:
        return tuple(
            sorted(
                message_ts
                for message_ts, document in self.live.items()
                if document.thread == thread
            )
        )

    def record_reconciliation(
        self,
        thread: str,
        *,
        watermark: int | None,
        revision: int,
    ) -> bool:
        current = self.watermarks.get(thread)
        if current is not None and revision < current[1]:
            return False
        self.watermarks[thread] = (watermark, revision)
        return True

    def next_reconciliation_thread(
        self,
        threads: tuple[str, ...],
    ) -> str | None:
        ordered = tuple(sorted(set(threads)))
        if not ordered:
            return None
        selected = next(
            (
                thread
                for thread in ordered
                if self.rotation_cursor is None or thread > self.rotation_cursor
            ),
            ordered[0],
        )
        self.rotation_cursor = selected
        return selected

    def requires_rebuild(self) -> bool:
        return False

    def begin_rebuild(self, scan_revision: int) -> int:
        return scan_revision

    def replace_rebuild_document(
        self,
        document: IndexedDocument,
        *,
        generation: int,
        revision: int,
    ) -> bool:
        del generation
        return self.replace_document(document, revision=revision)

    def finish_rebuild(self, generation: int) -> None:
        del generation

    def abort_rebuild(self, generation: int) -> None:
        del generation

    def query(
        self,
        chunks: tuple[str, ...],
        *,
        before: int | None = None,
        limit: int,
    ) -> list[SearchCandidate]:
        del chunks, before, limit
        return []

    def close(self) -> None:
        pass


def _queues(tmp_path: Path) -> tuple[JobQueues, Queue]:
    pending = Queue(PENDING_QUEUE_NAME, db_path=str(tmp_path / ".taut.db"))
    return JobQueues(pending=pending), pending


def _document(job: MessageJob, text: str = "parser green") -> IndexedDocument:
    encoded = text.encode("utf-8")
    return IndexedDocument(
        message_ts=job.message_ts,
        thread=job.thread,
        text_sha256=hashlib.sha256(encoded).hexdigest(),
        text_bytes=len(encoded),
        segments=(text,),
    )


def _row(pending: Queue, timestamp: int) -> tuple[str, int]:
    row = pending.peek_one(exact_timestamp=timestamp, with_timestamps=True)
    assert row is not None
    return row


def test_process_one_commits_before_exact_delete(tmp_path: Path) -> None:
    jobs, pending = _queues(tmp_path)
    provider = FakeProvider()
    job_ts = jobs.enqueue_message(
        message_ts=pending.generate_timestamp(), thread="general"
    )

    def load(job: MessageJob) -> IndexedDocument:
        assert pending.peek_one(exact_timestamp=job_ts) is not None
        return _document(job)

    try:
        assert process_one(jobs, provider, load, row=_row(pending, job_ts))
        assert pending.peek_one(exact_timestamp=job_ts) is None
        assert provider.live
    finally:
        pending.close()


def test_provider_failure_leaves_valid_work_pending(tmp_path: Path) -> None:
    jobs, pending = _queues(tmp_path)
    provider = FakeProvider(fail_replace=True)
    job_ts = jobs.enqueue_message(
        message_ts=pending.generate_timestamp(), thread="general"
    )
    try:
        with pytest.raises(RuntimeError, match="provider unavailable"):
            process_one(
                jobs, provider, lambda job: _document(job), row=_row(pending, job_ts)
            )
        assert pending.peek_one(exact_timestamp=job_ts) is not None
    finally:
        pending.close()


def test_malformed_then_valid_work_progresses_without_failed_queue(
    tmp_path: Path,
) -> None:
    jobs, pending = _queues(tmp_path)
    provider = FakeProvider()
    warnings: list[str] = []
    malformed_ts = pending.write('{"entity":"message","v":9}')
    valid_ts = jobs.enqueue_message(
        message_ts=pending.generate_timestamp(), thread="general"
    )
    try:
        for row in jobs.pending_rows_through(jobs.work_frontier() or 0):
            assert process_one(
                jobs,
                provider,
                lambda job: _document(job),
                row=row,
                warn_malformed=warnings.append,
            )
        assert pending.peek_one(exact_timestamp=malformed_ts) is None
        assert pending.peek_one(exact_timestamp=valid_ts) is None
        assert provider.live
        assert len(warnings) == 1
        assert "unexpected_fields" in warnings[0]
        assert "entity" not in warnings[0]
    finally:
        pending.close()


def test_absent_source_is_revision_fenced_tombstone(tmp_path: Path) -> None:
    jobs, pending = _queues(tmp_path)
    provider = FakeProvider()
    message_ts = pending.generate_timestamp()
    old = MessageJob(message_ts=message_ts, thread="general")
    provider.replace_document(_document(old), revision=100)
    job_ts = jobs.enqueue_message(message_ts=message_ts, thread="general")
    try:
        assert process_one(jobs, provider, lambda _job: None, row=_row(pending, job_ts))
        assert provider.revisions[message_ts] == job_ts
        assert message_ts not in provider.live
    finally:
        pending.close()


def test_rename_job_retargets_existing_document(tmp_path: Path) -> None:
    jobs, pending = _queues(tmp_path)
    provider = FakeProvider()
    message_ts = pending.generate_timestamp()
    provider.replace_document(
        _document(MessageJob(message_ts=message_ts, thread="general")),
        revision=100,
    )
    job_ts = pending.write(
        encode_thread_rename_job(
            old="general",
            new="renamed",
            affected=[{"old": "general", "new": "renamed"}],
        )
    )
    try:
        assert process_one(jobs, provider, lambda _job: None, row=_row(pending, job_ts))
        assert provider.live[message_ts].thread == "renamed"
        assert pending.peek_one(exact_timestamp=job_ts) is None
    finally:
        pending.close()


def test_duplicate_processing_is_safe_after_lost_delete(tmp_path: Path) -> None:
    jobs, pending = _queues(tmp_path)
    provider = FakeProvider()
    job_ts = jobs.enqueue_message(
        message_ts=pending.generate_timestamp(), thread="general"
    )

    def source(job: MessageJob) -> IndexedDocument:
        return _document(job)

    try:
        row = pending.peek_one(exact_timestamp=job_ts, with_timestamps=True)
        assert row is not None
        assert process_one(jobs, provider, source, row=row)
        assert process_one(jobs, provider, source, row=row)
        assert provider.revisions
        assert pending.peek_one(exact_timestamp=job_ts) is None
    finally:
        pending.close()
