"""Plain single-item search worker state transition.

Spec references:
- docs/specs/06-search.md [SRCH-8.2], [SRCH-9.2], [SRCH-9.3]
"""

from __future__ import annotations

from collections.abc import Callable

from taut.search._jobs import (
    JobQueues,
    MalformedSearchJob,
    MessageJob,
    ThreadRenameJob,
    decode_search_job,
)
from taut.search._provider import IndexedDocument, SearchProvider

SourceLoader = Callable[[MessageJob], IndexedDocument | None]


class UnconfirmedAcknowledgementError(RuntimeError):
    """A lost acknowledgement lacked proof of the required provider revision."""


def process_one(
    jobs: JobQueues,
    provider: SearchProvider,
    load_source: SourceLoader,
    *,
    exact_timestamp: int | None = None,
) -> bool:
    """Process at most one pending job through provider commit and acknowledgement.

    ``False`` means the pending queue was empty. A quarantined malformed item is
    successful work, so callers may immediately invoke this function again.
    Exceptions from source, provider, or broker boundaries deliberately leave a
    valid item claimed for visibility-timeout recovery.
    """

    claim = jobs.claim_one(exact_timestamp=exact_timestamp)
    if claim is None:
        return False
    try:
        job = decode_search_job(claim.body)
    except MalformedSearchJob as exc:
        jobs.quarantine(claim, error_code=exc.code)
        return True

    apply_job(job, revision=claim.job_ts, provider=provider, load_source=load_source)

    if jobs.acknowledge(claim.job_ts, claim.lease_id):
        return True
    if isinstance(job, ThreadRenameJob):
        raise UnconfirmedAcknowledgementError(
            "search rename acknowledgement lost without applied revision proof"
        )
    applied = provider.applied_revision(job.message_ts)
    if applied is not None and applied >= claim.job_ts:
        return True
    raise UnconfirmedAcknowledgementError(
        "search job acknowledgement lost without applied revision proof"
    )


def apply_claimed_snapshot(
    body: str,
    *,
    revision: int,
    provider: SearchProvider,
    load_source: SourceLoader,
) -> bool:
    """Idempotently apply valid already-claimed work without acknowledging it."""

    try:
        job = decode_search_job(body)
    except MalformedSearchJob:
        return False
    apply_job(job, revision=revision, provider=provider, load_source=load_source)
    return True


def apply_job(
    job: MessageJob | ThreadRenameJob,
    *,
    revision: int,
    provider: SearchProvider,
    load_source: SourceLoader,
) -> None:
    """Apply one decoded work item through the provider revision fence."""

    if isinstance(job, ThreadRenameJob):
        provider.retarget_threads(job.affected, revision=revision)
        return
    source = load_source(job)
    if source is None:
        provider.delete_document(
            message_ts=job.message_ts,
            thread=job.thread,
            revision=revision,
        )
    else:
        provider.replace_document(source, revision=revision)


__all__ = [
    "SourceLoader",
    "UnconfirmedAcknowledgementError",
    "apply_claimed_snapshot",
    "apply_job",
    "process_one",
]
