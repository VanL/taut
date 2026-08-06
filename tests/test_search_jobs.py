from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest
from simplebroker import Queue

from taut._constants import META_QUEUE_NAME
from taut.search._jobs import (
    CLAIM_TIMEOUT_NS,
    CLAIMED_QUEUE_NAME,
    FAILED_QUEUE_NAME,
    PENDING_QUEUE_NAME,
    JobQueues,
    MalformedSearchJob,
    MessageJob,
    decode_message_job,
    decode_thread_rename_job,
    encode_message_job,
    encode_thread_rename_job,
    sanitized_failure_body,
)

pytestmark = pytest.mark.sqlite_only


def _queues(tmp_path: Path) -> tuple[JobQueues, tuple[Queue, ...]]:
    db_path = str(tmp_path / ".taut.db")
    pending = Queue(PENDING_QUEUE_NAME, db_path=db_path)
    claimed = Queue(CLAIMED_QUEUE_NAME, db_path=db_path)
    failed = Queue(FAILED_QUEUE_NAME, db_path=db_path)
    meta = Queue(META_QUEUE_NAME, db_path=db_path)
    queues = JobQueues(
        pending=pending,
        claimed=claimed,
        failed=failed,
        meta=meta,
    )
    queues.ensure_schema()
    return queues, (pending, claimed, failed, meta)


def test_message_job_codec_is_exact_content_free_and_strict() -> None:
    """[SRCH-8.2] Version-one message jobs have one closed JSON shape."""

    message_ts = 1786032926849409024
    body = encode_message_job(message_ts=message_ts, thread="general")

    assert body == (
        '{"entity":"message","message_ts":1786032926849409024,"thread":"general","v":1}'
    )
    assert "parser is green" not in body
    assert decode_message_job(body) == MessageJob(
        message_ts=message_ts,
        thread="general",
    )


def test_thread_rename_job_codec_preserves_exact_content_free_mapping() -> None:
    body = encode_thread_rename_job(
        old="general",
        new="ops",
        affected=[
            {"old": "general", "new": "ops"},
            {"old": "general.1786032926849409024", "new": "ops.1786032926849409024"},
        ],
    )

    assert decode_thread_rename_job(body).affected == (
        ("general", "ops"),
        ("general.1786032926849409024", "ops.1786032926849409024"),
    )
    assert "message text" not in body


def test_thread_rename_job_rejects_mismatched_top_level_mapping() -> None:
    body = (
        '{"affected":[{"new":"other","old":"general"}],'
        '"entity":"thread_rename","new":"ops","old":"general","v":1}'
    )

    with pytest.raises(MalformedSearchJob) as raised:
        decode_thread_rename_job(body)

    assert raised.value.code == "invalid_rename"


@pytest.mark.parametrize(
    ("body", "code"),
    [
        ("not-json", "invalid_json"),
        ("[]", "not_object"),
        (
            (
                '{"entity":"message","message_ts":1786032926849409024,'
                '"thread":"general","v":1,"x":0}'
            ),
            "unexpected_fields",
        ),
        (
            (
                '{"entity":"message","entity":"message",'
                '"message_ts":1786032926849409024,"thread":"general","v":1}'
            ),
            "duplicate_field",
        ),
        (
            (
                '{"entity":"message","message_ts":1786032926849409024,'
                '"thread":"general"}'
            ),
            "unexpected_fields",
        ),
        (
            (
                '{"entity":"message","message_ts":1786032926849409024,'
                '"thread":"general","v":2}'
            ),
            "invalid_version",
        ),
        (
            (
                '{"entity":"thread_rename","message_ts":1786032926849409024,'
                '"thread":"general","v":1}'
            ),
            "invalid_entity",
        ),
        (
            ('{"entity":"message","message_ts":true,"thread":"general","v":1}'),
            "invalid_message_ts",
        ),
        (
            ('{"entity":"message","message_ts":1,"thread":"general","v":1}'),
            "invalid_message_ts",
        ),
        (
            ('{"entity":"message","message_ts":1786032926849409024,"thread":7,"v":1}'),
            "invalid_thread",
        ),
        (
            (
                '{"entity":"message","message_ts":1786032926849409024,'
                '"thread":"taut.search_index","v":1}'
            ),
            "invalid_thread",
        ),
        (
            (
                '{"entity":"message","message_ts":1786032926849409024,'
                '"thread":"dm.bad","v":1}'
            ),
            "invalid_thread",
        ),
    ],
)
def test_message_job_decoder_reports_bounded_structural_codes(
    body: str,
    code: str,
) -> None:
    with pytest.raises(MalformedSearchJob) as raised:
        decode_message_job(body)

    assert raised.value.code == code
    assert len(raised.value.code.encode("ascii")) <= 32


def test_sanitized_failure_body_has_digest_and_never_copies_input() -> None:
    """[SRCH-8.2] Quarantine diagnostics retain structure, never content."""

    raw = "secret message body\nwith another line"
    body = sanitized_failure_body(
        raw,
        original_job_ts=1786032926849409024,
        error_code="invalid_json",
    )
    decoded = json.loads(body)

    assert decoded == {
        "error": "invalid_json",
        "original_job_ts": 1786032926849409024,
        "sha256": hashlib.sha256(raw.encode("utf-8")).hexdigest(),
        "utf8_bytes": len(raw.encode("utf-8")),
        "v": 1,
    }
    assert raw not in body
    assert "secret" not in body
    assert "\n" not in body


def test_claim_one_moves_exactly_one_and_records_a_fresh_unique_lease(
    tmp_path: Path,
) -> None:
    """[SRCH-9.2] Reservation preserves job id and records claim time after move."""

    jobs, owned = _queues(tmp_path)
    try:
        first_ts = jobs.enqueue_message(
            message_ts=owned[3].generate_timestamp(), thread="a"
        )
        second_ts = jobs.enqueue_message(
            message_ts=owned[3].generate_timestamp(), thread="b"
        )

        first = jobs.claim_one()
        second = jobs.claim_one()

        assert first is not None and second is not None
        assert (first.job_ts, second.job_ts) == (first_ts, second_ts)
        assert first.claimed_at > first.job_ts
        assert first.worker_id == second.worker_id
        assert first.lease_id != second.lease_id
        assert jobs.pending.peek_one() is None
        assert jobs.claimed.peek_one(
            exact_timestamp=first.job_ts,
            with_timestamps=True,
        ) == (first.body, first.job_ts)
        assert jobs.lease_matches(first.job_ts, first.lease_id)
        assert not jobs.lease_matches(first.job_ts, second.lease_id)
        assert jobs.claim_one() is None
    finally:
        for queue in owned:
            queue.close()


def test_distinct_workers_receive_distinct_worker_and_lease_ids(tmp_path: Path) -> None:
    jobs, owned = _queues(tmp_path)
    other = JobQueues(
        pending=jobs.pending,
        claimed=jobs.claimed,
        failed=jobs.failed,
        meta=jobs.meta,
    )
    try:
        jobs.enqueue_message(message_ts=jobs.meta.generate_timestamp(), thread="a")
        jobs.enqueue_message(message_ts=jobs.meta.generate_timestamp(), thread="b")

        first = jobs.claim_one()
        second = other.claim_one()

        assert first is not None and second is not None
        assert first.worker_id != second.worker_id
        assert first.lease_id != second.lease_id
    finally:
        for queue in owned:
            queue.close()


def test_work_frontier_snapshots_pending_and_claimed_without_content(
    tmp_path: Path,
) -> None:
    """[SRCH-10.1] Search can bound urgent work despite active claim leases."""

    jobs, owned = _queues(tmp_path)
    try:
        first_ts = jobs.enqueue_message(
            message_ts=jobs.meta.generate_timestamp(), thread="a"
        )
        second_ts = jobs.enqueue_message(
            message_ts=jobs.meta.generate_timestamp(), thread="b"
        )
        claim = jobs.claim_one(exact_timestamp=first_ts)

        assert claim is not None
        assert jobs.work_frontier() == second_ts
        assert jobs.pending_ids_through(second_ts) == (second_ts,)
        assert jobs.claimed_rows_through(second_ts) == ((claim.body, first_ts),)
    finally:
        for queue in owned:
            queue.close()


def test_two_real_workers_cannot_claim_the_same_exact_job(tmp_path: Path) -> None:
    """[SRCH-9.2] Exact broker move is the concurrent claim arbiter."""

    jobs, owned = _queues(tmp_path)
    db_path = str(tmp_path / ".taut.db")
    job_ts = jobs.enqueue_message(
        message_ts=jobs.meta.generate_timestamp(),
        thread="general",
    )
    barrier = Barrier(2)

    def claim() -> int | None:
        local_owned = (
            Queue(PENDING_QUEUE_NAME, db_path=db_path),
            Queue(CLAIMED_QUEUE_NAME, db_path=db_path),
            Queue(FAILED_QUEUE_NAME, db_path=db_path),
            Queue(META_QUEUE_NAME, db_path=db_path),
        )
        local = JobQueues(
            pending=local_owned[0],
            claimed=local_owned[1],
            failed=local_owned[2],
            meta=local_owned[3],
        )
        try:
            barrier.wait()
            claimed = local.claim_one(exact_timestamp=job_ts)
            return None if claimed is None else claimed.job_ts
        finally:
            for queue in local_owned:
                queue.close()

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = tuple(pool.map(lambda _index: claim(), range(2)))

        assert sorted(result for result in results if result is not None) == [job_ts]
        assert results.count(None) == 1
    finally:
        for queue in owned:
            queue.close()


def test_missing_claim_metadata_is_immediately_reclaimable(tmp_path: Path) -> None:
    jobs, owned = _queues(tmp_path)
    try:
        job_ts = jobs.enqueue_message(
            message_ts=jobs.meta.generate_timestamp(), thread="general"
        )
        moved = jobs.pending.move_one(
            jobs.claimed,
            exact_timestamp=job_ts,
            with_timestamps=True,
        )
        assert moved is not None

        assert jobs.reclaim_expired(now=jobs.meta.generate_timestamp()) == [job_ts]
        assert jobs.pending.peek_one(exact_timestamp=job_ts) is not None
        assert jobs.claimed.peek_one(exact_timestamp=job_ts) is None
    finally:
        for queue in owned:
            queue.close()


def test_claim_reclaims_at_exact_visibility_timeout_without_sleep(
    tmp_path: Path,
) -> None:
    jobs, owned = _queues(tmp_path)
    try:
        jobs.enqueue_message(
            message_ts=jobs.meta.generate_timestamp(), thread="general"
        )
        claim = jobs.claim_one()
        assert claim is not None
        deadline = claim.claimed_unix_ns + CLAIM_TIMEOUT_NS

        assert jobs.reclaim_expired(now=deadline - 1) == []
        assert jobs.reclaim_expired(now=deadline) == [claim.job_ts]
        assert not jobs.lease_matches(claim.job_ts, claim.lease_id)
        assert jobs.pending.peek_one(exact_timestamp=claim.job_ts) is not None
    finally:
        for queue in owned:
            queue.close()


def test_late_claim_metadata_cannot_overwrite_a_new_claimant(tmp_path: Path) -> None:
    jobs, owned = _queues(tmp_path)
    try:
        job_ts = jobs.enqueue_message(
            message_ts=jobs.meta.generate_timestamp(), thread="general"
        )
        moved = jobs.pending.move_one(
            jobs.claimed,
            exact_timestamp=job_ts,
            with_timestamps=True,
        )
        assert moved is not None
        late_claimed_at = jobs.meta.generate_timestamp()
        assert jobs.reclaim_expired(now=jobs.meta.generate_timestamp()) == [job_ts]

        current = jobs.claim_one()
        assert current is not None
        assert not jobs._publish_claim(
            job_ts=job_ts,
            claimed_at=late_claimed_at,
            claimed_unix_ns=jobs.clock_ns(),
            worker_id="late-worker",
            lease_id="late-lease",
        )
        assert jobs.lease_matches(job_ts, current.lease_id)
        assert not jobs.lease_matches(job_ts, "late-lease")
    finally:
        for queue in owned:
            queue.close()


def test_expired_old_worker_cannot_delete_a_new_claimants_row(tmp_path: Path) -> None:
    jobs, owned = _queues(tmp_path)
    try:
        jobs.enqueue_message(
            message_ts=jobs.meta.generate_timestamp(), thread="general"
        )
        old = jobs.claim_one()
        assert old is not None
        deadline = old.claimed_unix_ns + CLAIM_TIMEOUT_NS
        assert jobs.reclaim_expired(now=deadline) == [old.job_ts]
        current = jobs.claim_one()
        assert current is not None

        assert not jobs.acknowledge(old.job_ts, old.lease_id)
        assert jobs.claimed.peek_one(exact_timestamp=current.job_ts) is not None
        assert jobs.lease_matches(current.job_ts, current.lease_id)
    finally:
        for queue in owned:
            queue.close()


def test_terminal_claim_recovery_finishes_ack_without_requeue(tmp_path: Path) -> None:
    jobs, owned = _queues(tmp_path)
    try:
        jobs.enqueue_message(
            message_ts=jobs.meta.generate_timestamp(), thread="general"
        )
        claim = jobs.claim_one()
        assert claim is not None
        assert jobs._mark_terminal(claim.job_ts, claim.lease_id)

        assert jobs.reclaim_expired(now=jobs.meta.generate_timestamp()) == []
        assert jobs.claimed.peek_one(exact_timestamp=claim.job_ts) is None
        assert jobs.pending.peek_one(exact_timestamp=claim.job_ts) is None
        assert not jobs.lease_matches(claim.job_ts, claim.lease_id)
    finally:
        for queue in owned:
            queue.close()


def test_orphan_claim_cleanup_rotates_past_live_prefix(tmp_path: Path) -> None:
    jobs, owned = _queues(tmp_path)
    try:
        jobs.enqueue_message(message_ts=jobs.meta.generate_timestamp(), thread="a")
        jobs.enqueue_message(message_ts=jobs.meta.generate_timestamp(), thread="b")
        live = jobs.claim_one()
        orphan = jobs.claim_one()
        assert live is not None and orphan is not None
        assert jobs.claimed.delete(message_id=orphan.job_ts)

        assert jobs.cleanup_orphan_claims(limit=1) == []
        assert jobs.cleanup_orphan_claims(limit=1) == [orphan.job_ts]
        assert jobs.lease_matches(live.job_ts, live.lease_id)
        assert not jobs.lease_matches(orphan.job_ts, orphan.lease_id)
    finally:
        for queue in owned:
            queue.close()


@pytest.mark.parametrize("version_json", ["1.0", "1e0", "true"])
def test_message_job_decoder_rejects_non_integer_version_types(
    version_json: str,
) -> None:
    body = (
        '{"entity":"message","message_ts":1786032926849409024,'
        f'"thread":"general","v":{version_json}}}'
    )

    with pytest.raises(MalformedSearchJob) as raised:
        decode_message_job(body)

    assert raised.value.code == "invalid_version"


def test_acknowledge_and_claim_removal_are_lease_conditional(tmp_path: Path) -> None:
    jobs, owned = _queues(tmp_path)
    try:
        jobs.enqueue_message(
            message_ts=jobs.meta.generate_timestamp(), thread="general"
        )
        claim = jobs.claim_one()
        assert claim is not None

        assert not jobs.acknowledge(claim.job_ts, "wrong-lease")
        assert jobs.claimed.peek_one(exact_timestamp=claim.job_ts) is not None
        assert not jobs.remove_claim_if_lease(claim.job_ts, "wrong-lease")
        assert jobs.acknowledge(claim.job_ts, claim.lease_id)
        assert jobs.claimed.peek_one(exact_timestamp=claim.job_ts) is None
        assert not jobs.lease_matches(claim.job_ts, claim.lease_id)
    finally:
        for queue in owned:
            queue.close()


def test_quarantine_writes_sanitized_envelope_before_exact_delete(
    tmp_path: Path,
) -> None:
    jobs, owned = _queues(tmp_path)
    try:
        raw = "not-json secret source text"
        job_ts = jobs.pending.write(raw)
        claim = jobs.claim_one()
        assert claim is not None and claim.job_ts == job_ts

        assert jobs.quarantine(claim, error_code="invalid_json")

        assert jobs.claimed.peek_one(exact_timestamp=job_ts) is None
        failed_body = jobs.failed.peek_one()
        assert isinstance(failed_body, str)
        assert json.loads(failed_body)["original_job_ts"] == job_ts
        assert raw not in failed_body
        assert "secret" not in failed_body
        assert not jobs.lease_matches(job_ts, claim.lease_id)
    finally:
        for queue in owned:
            queue.close()
