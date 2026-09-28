"""Pending search work state transition.

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


def process_one(
    jobs: JobQueues,
    provider: SearchProvider,
    load_source: SourceLoader,
    *,
    row: tuple[str, int],
    warn_malformed: Callable[[str], None] | None = None,
) -> bool:
    """Apply one pending job, then exact-delete it after provider commit."""

    body, job_ts = row
    try:
        job = decode_search_job(body)
    except MalformedSearchJob as exc:
        if warn_malformed is not None:
            warn_malformed(f"discarded malformed search job {job_ts}: {exc.code}")
        jobs.pending.delete(message_id=job_ts)
        return True

    apply_job(job, revision=job_ts, provider=provider, load_source=load_source)
    jobs.pending.delete(message_id=job_ts)
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
    "apply_job",
    "process_one",
]
