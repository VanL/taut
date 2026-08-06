from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from simplebroker import Queue

from taut._constants import META_QUEUE_NAME
from taut.search._jobs import (
    CLAIMED_QUEUE_NAME,
    FAILED_QUEUE_NAME,
    PENDING_QUEUE_NAME,
    JobQueues,
    MessageJob,
    encode_thread_rename_job,
)
from taut.search._provider import IndexedDocument, SearchCandidate, ThreadWatermark
from taut.search._worker import (
    UnconfirmedAcknowledgementError,
    apply_claimed_snapshot,
    process_one,
)

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


class LostAckJobQueues(JobQueues):
    def acknowledge(self, job_ts: int, lease_id: str) -> bool:
        del job_ts, lease_id
        return False


class FailingAckJobQueues(JobQueues):
    def acknowledge(self, job_ts: int, lease_id: str) -> bool:
        del job_ts, lease_id
        raise RuntimeError("broker unavailable")


def _queues(
    tmp_path: Path,
    *,
    queue_type: type[JobQueues] = JobQueues,
) -> tuple[JobQueues, tuple[Queue, ...]]:
    db_path = str(tmp_path / ".taut.db")
    pending = Queue(PENDING_QUEUE_NAME, db_path=db_path)
    claimed = Queue(CLAIMED_QUEUE_NAME, db_path=db_path)
    failed = Queue(FAILED_QUEUE_NAME, db_path=db_path)
    meta = Queue(META_QUEUE_NAME, db_path=db_path)
    jobs = queue_type(pending=pending, claimed=claimed, failed=failed, meta=meta)
    jobs.ensure_schema()
    return jobs, (pending, claimed, failed, meta)


def _document(job: MessageJob, text: str = "parser green") -> IndexedDocument:
    encoded = text.encode("utf-8")
    return IndexedDocument(
        message_ts=job.message_ts,
        thread=job.thread,
        text_sha256=hashlib.sha256(encoded).hexdigest(),
        text_bytes=len(encoded),
        segments=(text,),
    )


def test_process_one_replaces_live_source_before_acknowledgement(
    tmp_path: Path,
) -> None:
    jobs, owned = _queues(tmp_path)
    provider = FakeProvider()
    loaded: list[MessageJob] = []

    def load(job: MessageJob) -> IndexedDocument:
        loaded.append(job)
        return _document(job)

    try:
        message_ts = jobs.meta.generate_timestamp()
        job_ts = jobs.enqueue_message(message_ts=message_ts, thread="general")

        assert process_one(jobs, provider, load)

        assert loaded == [MessageJob(message_ts=message_ts, thread="general")]
        assert provider.calls == [("replace", message_ts, job_ts)]
        assert provider.applied_revision(message_ts) == job_ts
        assert jobs.claimed.peek_one(exact_timestamp=job_ts) is None
    finally:
        for queue in owned:
            queue.close()


def test_search_read_through_applies_active_claim_without_acknowledging(
    tmp_path: Path,
) -> None:
    """[SRCH-10.1] Active workers do not force search to wait for timeout."""

    jobs, owned = _queues(tmp_path)
    provider = FakeProvider()
    try:
        message_ts = jobs.meta.generate_timestamp()
        job_ts = jobs.enqueue_message(message_ts=message_ts, thread="general")
        claim = jobs.claim_one(exact_timestamp=job_ts)
        assert claim is not None

        assert apply_claimed_snapshot(
            claim.body,
            revision=claim.job_ts,
            provider=provider,
            load_source=lambda job: _document(job),
        )

        assert provider.applied_revision(message_ts) == job_ts
        assert jobs.claimed.peek_one(exact_timestamp=job_ts) == claim.body
        assert jobs.lease_matches(job_ts, claim.lease_id)
    finally:
        for queue in owned:
            queue.close()


def test_process_one_tombstones_absent_source_at_job_revision(tmp_path: Path) -> None:
    jobs, owned = _queues(tmp_path)
    provider = FakeProvider()
    try:
        message_ts = jobs.meta.generate_timestamp()
        job_ts = jobs.enqueue_message(message_ts=message_ts, thread="general")

        assert process_one(jobs, provider, lambda _job: None)

        assert provider.calls == [("delete", message_ts, job_ts)]
        assert provider.applied_revision(message_ts) == job_ts
        assert message_ts not in provider.live
    finally:
        for queue in owned:
            queue.close()


def test_older_job_cannot_replace_a_newer_tombstone(tmp_path: Path) -> None:
    jobs, owned = _queues(tmp_path)
    provider = FakeProvider()
    try:
        message_ts = jobs.meta.generate_timestamp()
        old_job_ts = jobs.enqueue_message(message_ts=message_ts, thread="general")
        newer_revision = jobs.meta.generate_timestamp()
        assert provider.delete_document(
            message_ts=message_ts,
            thread="general",
            revision=newer_revision,
        )

        assert process_one(jobs, provider, lambda job: _document(job, "stale"))

        assert provider.calls[-1] == ("replace", message_ts, old_job_ts)
        assert provider.applied_revision(message_ts) == newer_revision
        assert message_ts not in provider.live
    finally:
        for queue in owned:
            queue.close()


def test_already_applied_duplicate_is_idempotently_acknowledged(tmp_path: Path) -> None:
    jobs, owned = _queues(tmp_path)
    provider = FakeProvider()
    try:
        message_ts = jobs.meta.generate_timestamp()
        job_ts = jobs.enqueue_message(message_ts=message_ts, thread="general")
        job = MessageJob(message_ts=message_ts, thread="general")
        assert provider.replace_document(_document(job), revision=job_ts)

        assert process_one(jobs, provider, lambda current: _document(current))

        assert provider.applied_revision(message_ts) == job_ts
        assert jobs.claimed.peek_one(exact_timestamp=job_ts) is None
    finally:
        for queue in owned:
            queue.close()


def test_malformed_job_is_quarantined_and_next_valid_job_can_run(
    tmp_path: Path,
) -> None:
    jobs, owned = _queues(tmp_path)
    provider = FakeProvider()
    loaded: list[MessageJob] = []

    def load(job: MessageJob) -> IndexedDocument:
        loaded.append(job)
        return _document(job)

    try:
        malformed_ts = jobs.pending.write("not-json secret body")
        message_ts = jobs.meta.generate_timestamp()
        valid_ts = jobs.enqueue_message(message_ts=message_ts, thread="general")

        assert process_one(jobs, provider, load)
        assert process_one(jobs, provider, load)

        assert loaded == [MessageJob(message_ts=message_ts, thread="general")]
        assert jobs.claimed.peek_one(exact_timestamp=malformed_ts) is None
        assert jobs.claimed.peek_one(exact_timestamp=valid_ts) is None
        failed = jobs.failed.peek_one()
        assert isinstance(failed, str)
        assert "secret" not in failed
    finally:
        for queue in owned:
            queue.close()


def test_process_one_retargets_completed_thread_rename(tmp_path: Path) -> None:
    jobs, owned = _queues(tmp_path)
    provider = FakeProvider()
    document = IndexedDocument(100, "general", "digest", 4, ("text",))
    provider.live[100] = document
    provider.revisions[100] = 1
    try:
        body = encode_thread_rename_job(
            old="general",
            new="ops",
            affected=[{"old": "general", "new": "ops"}],
        )
        jobs.pending.write(body)

        assert process_one(
            jobs,
            provider,
            lambda _job: pytest.fail("rename must not load a message source"),
        )

        assert provider.live[100].thread == "ops"
        assert jobs.claimed.peek_one() is None
    finally:
        for queue in owned:
            queue.close()


@pytest.mark.parametrize("failure_owner", ["source", "provider"])
def test_transient_failure_leaves_valid_item_claimed(
    tmp_path: Path,
    failure_owner: str,
) -> None:
    jobs, owned = _queues(tmp_path)
    provider = FakeProvider(fail_replace=failure_owner == "provider")

    def load(job: MessageJob) -> IndexedDocument:
        if failure_owner == "source":
            raise RuntimeError("source unavailable")
        return _document(job)

    try:
        message_ts = jobs.meta.generate_timestamp()
        job_ts = jobs.enqueue_message(message_ts=message_ts, thread="general")

        with pytest.raises(RuntimeError, match="unavailable"):
            process_one(jobs, provider, load)

        assert jobs.claimed.peek_one(exact_timestamp=job_ts) is not None
        assert jobs.pending.peek_one(exact_timestamp=job_ts) is None
    finally:
        for queue in owned:
            queue.close()


def test_lost_ack_succeeds_only_with_applied_revision_proof(tmp_path: Path) -> None:
    jobs, owned = _queues(tmp_path, queue_type=LostAckJobQueues)
    provider = FakeProvider()
    try:
        message_ts = jobs.meta.generate_timestamp()
        job_ts = jobs.enqueue_message(message_ts=message_ts, thread="general")

        assert process_one(jobs, provider, lambda job: _document(job))

        assert provider.applied_revision(message_ts) == job_ts
        assert jobs.claimed.peek_one(exact_timestamp=job_ts) is not None
    finally:
        for queue in owned:
            queue.close()


def test_broker_ack_failure_occurs_after_provider_commit_and_leaves_claim(
    tmp_path: Path,
) -> None:
    jobs, owned = _queues(tmp_path, queue_type=FailingAckJobQueues)
    provider = FakeProvider()
    try:
        message_ts = jobs.meta.generate_timestamp()
        job_ts = jobs.enqueue_message(message_ts=message_ts, thread="general")

        with pytest.raises(RuntimeError, match="broker unavailable"):
            process_one(jobs, provider, lambda job: _document(job))

        assert provider.applied_revision(message_ts) == job_ts
        assert jobs.claimed.peek_one(exact_timestamp=job_ts) is not None
    finally:
        for queue in owned:
            queue.close()


def test_lost_ack_without_revision_proof_raises_and_leaves_recovery_state(
    tmp_path: Path,
) -> None:
    jobs, owned = _queues(tmp_path, queue_type=LostAckJobQueues)
    provider = FakeProvider(applied_override=1)
    try:
        message_ts = jobs.meta.generate_timestamp()
        job_ts = jobs.enqueue_message(message_ts=message_ts, thread="general")

        with pytest.raises(UnconfirmedAcknowledgementError):
            process_one(jobs, provider, lambda job: _document(job))

        assert jobs.claimed.peek_one(exact_timestamp=job_ts) is not None
    finally:
        for queue in owned:
            queue.close()


def test_empty_queue_returns_false_without_calling_source(tmp_path: Path) -> None:
    jobs, owned = _queues(tmp_path)
    provider = FakeProvider()

    def source(_job: MessageJob) -> IndexedDocument | None:
        raise AssertionError("empty queue must not call source loader")

    try:
        assert not process_one(jobs, provider, source)
    finally:
        for queue in owned:
            queue.close()
