"""Cursor-neutral search behavior for :class:`taut.client.TautClient`.

Spec references:
- docs/specs/06-search.md [SRCH-2], [SRCH-3], [SRCH-4], [SRCH-5], [SRCH-10]
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Collection, Generator, Sequence
from contextlib import ExitStack, closing
from dataclasses import dataclass
from itertools import islice
from typing import cast

from simplebroker import BrokerSession, Queue

from taut import addressing
from taut._constants import META_QUEUE_NAME, route_key, validate_member_name
from taut._exceptions import EmptyResultError, NotFoundError
from taut.search import projection_segments, query_chunks
from taut.search._discovery import load_search_provider
from taut.search._provider import IndexedDocument, SearchCandidate, SearchProvider
from taut.search._sqlite import SQLiteSearchProvider
from taut.state import MemberRow, ThreadRow

from ._base import _ClientBase
from ._codec import message_from_body
from ._messaging import _validate_exact_message_id
from ._models import Message, SearchHit

_INDEX_SEGMENT_BYTES = 64 * 1024
_INDEX_QUERY_BATCH = 100_000
_KINDS = frozenset({"message", "notice", "foreign"})


def _is_higher_watermark(current: int | None, previous: int | None) -> bool:
    return current is not None and (previous is None or current > previous)


def _is_lower_watermark(current: int | None, previous: int | None) -> bool:
    return previous is not None and (current is None or current < previous)


@dataclass(frozen=True, slots=True)
class _SearchRequest:
    chunks: tuple[str, ...]
    channels: tuple[str, ...]
    direct_messages: tuple[str, ...]
    all_direct_messages: bool
    from_member: str | None
    kinds: frozenset[str]
    before_ts: int | None
    limit: int
    reindex: bool


def _probe_search_message(
    job_ts: int,
    names: Sequence[str],
    queue_for: Callable[[str], Queue],
    seen: set[str],
) -> Message | None:
    """Exact-peek each currently registered source once for one message ID."""

    for thread in names:
        if thread in seen:
            continue
        seen.add(thread)
        found = queue_for(thread).peek_one(
            exact_timestamp=job_ts,
            with_timestamps=True,
        )
        if found is not None:
            body, timestamp = found
            return message_from_body(thread, body, timestamp)
    return None


class SearchingMixin(_ClientBase):
    """Own the backend-neutral search contract."""

    def search(
        self,
        query: str,
        *,
        channels: Sequence[str] = (),
        direct_messages: Sequence[str] = (),
        all_direct_messages: bool = False,
        from_member: str | None = None,
        kinds: Collection[str] = (),
        before: str | None = None,
        limit: int = 50,
        reindex: bool = False,
    ) -> list[SearchHit]:
        """Return hydrated full-text hits without changing chat state."""

        request = _validate_search_request(
            query=query,
            channels=channels,
            direct_messages=direct_messages,
            all_direct_messages=all_direct_messages,
            from_member=from_member,
            kinds=kinds,
            before=before,
            limit=limit,
            reindex=reindex,
        )
        self.last_search_warnings.clear()
        self._ensure_no_incomplete_channel_rename()
        rows = self._state.list_threads()
        by_name = {row["name"]: row for row in rows}
        actor = self._resolve_member(
            create=False,
            allow_guest=True,
            _touch_activity=False,
            _heal_claim=False,
        ).row
        scope = self._search_scope(
            rows=rows,
            channel_selectors=request.channels,
            dm_selectors=request.direct_messages,
            all_direct_messages=request.all_direct_messages,
            actor=actor,
        )

        author_id: str | None = None
        if request.from_member is not None:
            author = self._state.get_member_by_route_key(route_key(request.from_member))
            if author is None:
                raise EmptyResultError(f"member not found: {request.from_member}")
            author_id = author["member_id"]

        with (
            BrokerSession.connect(self.target, config=self.config),
            self._search_source_queue(META_QUEUE_NAME) as meta,
        ):
            provider = self._search_provider(meta)
            try:
                self._ensure_search_schema(provider)
                if request.reindex or provider.requires_rebuild():
                    self._rebuild_search_index(provider, rows, meta=meta)
                    # Close work committed during the drain-to-switch interval.
                    self._drain_search_jobs(provider)
                else:
                    self._drain_search_jobs(provider)
                    self._reconcile_search_index(provider, rows, meta=meta)
                hits = self._query_search_hits(
                    provider=provider,
                    request=request,
                    scope=scope,
                    by_name=by_name,
                    actor=actor,
                    author_id=author_id,
                )
            finally:
                provider.close()
        if not hits:
            raise EmptyResultError("no search results")
        return hits

    def _ensure_search_schema(self, provider: SearchProvider) -> None:
        """Advance the one supported prior work format before provider DDL."""

        from taut.search._provider import SEARCH_SCHEMA_VERSION

        version = provider.schema_version()
        if version == 1:
            self._upgrade_search_work_queues()
        if version != SEARCH_SCHEMA_VERSION:
            provider.ensure_schema()

    def _upgrade_search_work_queues(self) -> None:
        """Return old claimed work to pending under operator quiescence."""

        from simplebroker import open_broker

        from taut.search._jobs import (
            CLAIMED_QUEUE_NAME,
            FAILED_QUEUE_NAME,
            PENDING_QUEUE_NAME,
        )

        with open_broker(self.target, config=self.config) as broker:
            names = {item.queue for item in broker.list_queue_stats()}
        if CLAIMED_QUEUE_NAME in names:
            with BrokerSession.connect(self.target, config=self.config):
                claimed = Queue(
                    CLAIMED_QUEUE_NAME,
                    db_path=self.target,
                    persistent=True,
                    config=self.config,
                )
                pending = Queue(
                    PENDING_QUEUE_NAME,
                    db_path=self.target,
                    persistent=True,
                    config=self.config,
                )
                try:
                    while True:
                        moved = claimed.move_one(pending, with_timestamps=True)
                        if moved is None:
                            break
                finally:
                    pending.close()
                    claimed.close()
        with open_broker(self.target, config=self.config) as broker:
            for name in (CLAIMED_QUEUE_NAME, FAILED_QUEUE_NAME):
                if name in names:
                    broker.delete(name)

    def _drain_search_jobs(self, provider: SearchProvider) -> None:
        from taut.search._jobs import PENDING_QUEUE_NAME, JobQueues, MessageJob
        from taut.search._worker import process_one

        with ExitStack() as owned:
            handles: dict[str, Queue] = {}

            def queue_for(name: str) -> Queue:
                source = handles.get(name)
                if source is None:
                    source = Queue(
                        name,
                        db_path=self.target,
                        persistent=True,
                        config=self.config,
                    )
                    handles[name] = source
                    owned.callback(source.close)
                return source

            pending = queue_for(PENDING_QUEUE_NAME)
            jobs = JobQueues(pending=pending)
            frontier = jobs.work_frontier()
            if frontier is None:
                return
            names = [
                row["name"]
                for row in self._registered_searchable_rows(self._state.list_threads())
            ]
            refreshed = False

            def load_source(job: MessageJob) -> IndexedDocument | None:
                nonlocal names, refreshed
                candidates = (
                    [job.thread, *(name for name in names if name != job.thread)]
                    if job.thread in names
                    else names
                )
                seen: set[str] = set()
                message = _probe_search_message(
                    job.message_ts, candidates, queue_for, seen
                )
                if message is None and not refreshed:
                    names = [
                        row["name"]
                        for row in self._registered_searchable_rows(
                            self._state.list_threads()
                        )
                    ]
                    refreshed = True
                    message = _probe_search_message(
                        job.message_ts, names, queue_for, seen
                    )
                if message is None:
                    return None
                encoded = message.text.encode("utf-8")
                return IndexedDocument(
                    message_ts=message.ts,
                    thread=message.thread,
                    text_sha256=hashlib.sha256(encoded).hexdigest(),
                    text_bytes=len(encoded),
                    segments=projection_segments(
                        message.text,
                        max_segment_bytes=_INDEX_SEGMENT_BYTES,
                    ),
                )

            with closing(jobs.pending_rows_through(frontier)) as pending_rows:
                for row in pending_rows:
                    process_one(
                        jobs,
                        provider,
                        load_source,
                        row=row,
                        warn_malformed=self.last_search_warnings.append,
                    )

    def _query_search_hits(
        self,
        *,
        provider: SearchProvider,
        request: _SearchRequest,
        scope: set[str],
        by_name: dict[str, ThreadRow],
        actor: MemberRow | None,
        author_id: str | None,
    ) -> list[SearchHit]:
        hits: list[SearchHit] = []
        candidate_before = request.before_ts
        with ExitStack() as owned:
            handles: dict[str, Queue] = {}

            def queue_for(thread: str) -> Queue:
                queue = handles.get(thread)
                if queue is None:
                    queue = self._search_source_queue(thread)
                    handles[thread] = queue
                    owned.callback(queue.close)
                return queue

            while len(hits) < request.limit:
                candidates = provider.query(
                    request.chunks,
                    before=candidate_before,
                    limit=_INDEX_QUERY_BATCH,
                )
                if not candidates:
                    break
                hits.extend(
                    self._collect_search_hits(
                        candidates=candidates,
                        request=request,
                        scope=scope,
                        by_name=by_name,
                        actor=actor,
                        author_id=author_id,
                        queue_for=queue_for,
                    )
                )
                if len(candidates) < _INDEX_QUERY_BATCH:
                    break
                candidate_before = candidates[-1].message_ts
        return hits[: request.limit]

    def _search_provider(self, meta: Queue) -> SearchProvider:
        backend_name = (
            self.target.backend_name if not isinstance(self.target, str) else "sqlite"
        )
        if backend_name == "sqlite":
            return SQLiteSearchProvider(sidecar=meta.sidecar)
        return load_search_provider(
            backend_name=backend_name,
            sidecar=meta.sidecar,
        )

    def _search_source_queue(self, thread: str) -> Queue:
        """A short-lived handle on the operation's shared broker core."""

        return Queue(
            thread,
            db_path=self.target,
            persistent=True,
            config=self.config,
        )

    def _rebuild_search_index(
        self,
        provider: SearchProvider,
        rows: list[ThreadRow],
        *,
        meta: Queue,
    ) -> None:
        scan_revision = meta.generate_timestamp()
        generation = provider.begin_rebuild(scan_revision)
        watermarks: dict[str, int | None] = {}
        try:
            for row in self._registered_searchable_rows(rows):
                thread = row["name"]
                with self._search_source_queue(thread) as queue:
                    watermarks[thread] = queue.latest_pending_timestamp()
                    with closing(
                        self._thread_source_documents(queue, thread=thread)
                    ) as documents:
                        for document in documents:
                            provider.replace_rebuild_document(
                                document,
                                generation=generation,
                                revision=scan_revision,
                            )
            self._drain_search_jobs(provider)
            provider.finish_rebuild(generation)
            for thread, watermark in watermarks.items():
                provider.record_reconciliation(
                    thread,
                    watermark=watermark,
                    revision=scan_revision,
                )
        except BaseException:
            provider.abort_rebuild(generation)
            raise

    def _reconcile_search_index(
        self,
        provider: SearchProvider,
        rows: list[ThreadRow],
        *,
        meta: Queue,
    ) -> None:
        """Repair urgent watermarks, then fully reconcile one durable rotation."""

        searchable = self._registered_searchable_rows(rows)
        for row in searchable:
            self._reconcile_search_thread(provider, row, meta=meta, force_full=False)
        by_name = {row["name"]: row for row in searchable}
        selected = provider.next_reconciliation_thread(tuple(by_name))
        if selected is not None:
            self._reconcile_search_thread(
                provider,
                by_name[selected],
                meta=meta,
                force_full=True,
            )

    def _reconcile_search_thread(
        self,
        provider: SearchProvider,
        row: ThreadRow,
        *,
        meta: Queue,
        force_full: bool,
    ) -> None:
        """Apply one revision-fenced public-queue scan to one thread."""

        thread = row["name"]
        with self._search_source_queue(thread) as queue:
            state = provider.thread_watermark(thread)
            initial_latest = queue.latest_pending_timestamp()
            if not force_full and state.known and initial_latest == state.message_ts:
                return

            scan_revision = meta.generate_timestamp()
            source_latest = queue.latest_pending_timestamp()
            if force_full or not state.known:
                self._reconcile_full_thread(
                    provider,
                    queue,
                    thread=thread,
                    scan_revision=scan_revision,
                )
            elif _is_higher_watermark(source_latest, state.message_ts):
                with closing(
                    self._thread_source_documents(
                        queue,
                        thread=thread,
                        after=state.message_ts,
                    )
                ) as documents:
                    for document in documents:
                        provider.replace_document(document, revision=scan_revision)
            elif _is_lower_watermark(source_latest, state.message_ts):
                assert state.message_ts is not None
                found = queue.peek_one(
                    exact_timestamp=state.message_ts,
                    with_timestamps=True,
                )
                if found is None:
                    provider.delete_document(
                        message_ts=state.message_ts,
                        thread=thread,
                        revision=scan_revision,
                    )
                else:
                    body, timestamp = found
                    provider.replace_document(
                        self._search_document(thread, body, timestamp),
                        revision=scan_revision,
                    )
            provider.record_reconciliation(
                thread,
                watermark=source_latest,
                revision=scan_revision,
            )

    def _reconcile_full_thread(
        self,
        provider: SearchProvider,
        queue: Queue,
        *,
        thread: str,
        scan_revision: int,
    ) -> None:
        source_ids: set[int] = set()
        with closing(self._thread_source_documents(queue, thread=thread)) as documents:
            for document in documents:
                source_ids.add(document.message_ts)
                provider.replace_document(document, revision=scan_revision)
        for message_ts in provider.indexed_message_ids(thread):
            if message_ts not in source_ids:
                provider.delete_document(
                    message_ts=message_ts,
                    thread=thread,
                    revision=scan_revision,
                )

    def _registered_searchable_rows(
        self,
        rows: list[ThreadRow],
    ) -> list[ThreadRow]:
        return [
            row
            for row in rows
            if row["kind"] in {"channel", "subthread", "dm"}
            and (row["kind"] != "dm" or self._valid_search_dm_row(row))
        ]

    def _thread_source_documents(
        self,
        queue: Queue,
        *,
        thread: str,
        after: int | None = None,
    ) -> Generator[IndexedDocument]:
        cursor = after
        while True:
            generator = queue.peek_generator(
                with_timestamps=True,
                after_timestamp=cursor,
            )
            try:
                batch = cast(
                    list[tuple[str, int]],
                    list(islice(generator, 100)),
                )
            finally:
                close = getattr(generator, "close", None)
                if close is not None:
                    close()
            if not batch:
                return
            for body, timestamp in batch:
                yield self._search_document(thread, body, timestamp)
            cursor = batch[-1][1]

    @staticmethod
    def _search_document(thread: str, body: str, timestamp: int) -> IndexedDocument:
        message = message_from_body(thread, body, timestamp)
        encoded = message.text.encode("utf-8")
        return IndexedDocument(
            message_ts=timestamp,
            thread=thread,
            text_sha256=hashlib.sha256(encoded).hexdigest(),
            text_bytes=len(encoded),
            segments=projection_segments(
                message.text,
                max_segment_bytes=_INDEX_SEGMENT_BYTES,
            ),
        )

    def _valid_search_dm_row(self, row: ThreadRow) -> bool:
        members = row["meta"].get("members")
        if (
            not isinstance(members, list)
            or len(members) != 2
            or not all(isinstance(member_id, str) for member_id in members)
            or len(set(members)) != 2
        ):
            return False
        member_ids = cast(list[str], members)
        try:
            canonical = addressing.dm_queue_name(member_ids[0], member_ids[1])
        except ValueError:
            return False
        return row["name"] == canonical and all(
            self._state.get_membership(thread=row["name"], member_id=member_id)
            is not None
            for member_id in member_ids
        )

    def _search_scope(
        self,
        *,
        rows: list[ThreadRow],
        channel_selectors: tuple[str, ...],
        dm_selectors: tuple[str, ...],
        all_direct_messages: bool,
        actor: MemberRow | None,
    ) -> set[str]:
        by_name = {row["name"]: row for row in rows}
        explicit = bool(channel_selectors or dm_selectors or all_direct_messages)
        scope: set[str] = set()

        if not explicit:
            scope.update(
                row["name"] for row in rows if row["kind"] in {"channel", "subthread"}
            )
        for channel in channel_selectors:
            row = by_name.get(channel)
            if row is None or row["kind"] != "channel":
                raise NotFoundError(f"channel not found: {channel}")
            scope.add(channel)
            scope.update(
                child["name"]
                for child in rows
                if child["kind"] == "subthread" and child["parent"] == channel
            )

        self._add_direct_message_scope(
            scope=scope,
            rows=rows,
            selectors=dm_selectors,
            include_all=not explicit or all_direct_messages,
            require_actor=bool(dm_selectors or all_direct_messages),
            actor=actor,
        )

        return scope

    def _add_direct_message_scope(
        self,
        *,
        scope: set[str],
        rows: list[ThreadRow],
        selectors: tuple[str, ...],
        include_all: bool,
        require_actor: bool,
        actor: MemberRow | None,
    ) -> None:
        if actor is None:
            if require_actor:
                raise EmptyResultError("direct messages require a recognized caller")
            return
        if include_all:
            for row in rows:
                if row["kind"] != "dm":
                    continue
                context = self._direct_message_context(row["name"], actor)
                if context is not None:
                    self._remember_direct_message_display_name(context)
                    scope.add(row["name"])
        for selector in selectors:
            context = self._resolve_direct_message(selector, actor)
            scope.add(context.thread["name"])

    def _collect_search_hits(
        self,
        *,
        candidates: list[SearchCandidate],
        request: _SearchRequest,
        scope: set[str],
        by_name: dict[str, ThreadRow],
        actor: MemberRow | None,
        author_id: str | None,
        queue_for: Callable[[str], Queue],
    ) -> list[SearchHit]:
        hits: list[SearchHit] = []
        for candidate in candidates:
            if (
                request.before_ts is not None
                and candidate.message_ts >= request.before_ts
            ):
                continue
            row = by_name.get(candidate.thread)
            if (
                candidate.thread not in scope
                or row is None
                or row["kind"] not in {"channel", "subthread", "dm"}
                or (
                    row["kind"] == "dm"
                    and (
                        actor is None
                        or self._direct_message_context(row["name"], actor) is None
                    )
                )
            ):
                continue
            hit = self._hydrate_search_candidate(
                candidate=candidate,
                row=row,
                author_id=author_id,
                kinds=request.kinds,
                queue_for=queue_for,
            )
            if hit is not None:
                hits.append(hit)
            if len(hits) == request.limit:
                break
        return hits

    def _hydrate_search_candidate(
        self,
        *,
        candidate: SearchCandidate,
        row: ThreadRow,
        author_id: str | None,
        kinds: frozenset[str],
        queue_for: Callable[[str], Queue],
    ) -> SearchHit | None:
        found = queue_for(candidate.thread).peek_one(
            exact_timestamp=candidate.message_ts,
            with_timestamps=True,
        )
        if found is None:
            self._enqueue_search_message(
                message_ts=candidate.message_ts,
                thread=candidate.thread,
            )
            return None
        body, timestamp = found
        message = message_from_body(candidate.thread, body, timestamp)
        encoded = message.text.encode("utf-8")
        projection_changed = (
            len(encoded) != candidate.text_bytes
            or hashlib.sha256(encoded).hexdigest() != candidate.text_sha256
        )
        if projection_changed:
            self._enqueue_search_message(
                message_ts=candidate.message_ts,
                thread=candidate.thread,
            )
            return None
        if (author_id is not None and message.from_id != author_id) or (
            kinds and message.kind not in kinds
        ):
            return None
        return _search_hit(message, row)


def _validate_string_collection(name: str, value: object) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Collection):
        raise TypeError(f"{name} must be a non-string collection")
    result = tuple(value)
    if not all(isinstance(item, str) for item in result):
        raise TypeError(f"{name} must contain only strings")
    return cast(tuple[str, ...], result)


def _validate_kinds(value: object) -> frozenset[str]:
    kinds = frozenset(_validate_string_collection("kinds", value))
    unknown = kinds - _KINDS
    if unknown:
        raise ValueError(f"invalid search kind: {min(unknown)}")
    return kinds


def _validate_scope_syntax(
    channels: tuple[str, ...], direct_messages: tuple[str, ...]
) -> None:
    for channel in channels:
        if channel.startswith("#"):
            raise ValueError("search channel selectors must be bare channel names")
        addressing.validate_chat_thread_name(channel, allow_subthread=False)
    for selector in direct_messages:
        if addressing.parse_dm_selector(selector) is None:
            raise ValueError("direct-message selectors must start with '@' or 'dm.'")


def _validate_search_request(
    *,
    query: object,
    channels: object,
    direct_messages: object,
    all_direct_messages: object,
    from_member: object,
    kinds: object,
    before: object,
    limit: object,
    reindex: object,
) -> _SearchRequest:
    chunks = query_chunks(cast(str, query))
    channel_selectors = _validate_string_collection("channels", channels)
    dm_selectors = _validate_string_collection("direct_messages", direct_messages)
    kind_values = _validate_kinds(kinds)
    if not isinstance(all_direct_messages, bool):
        raise TypeError("all_direct_messages must be a boolean")
    if from_member is not None:
        if not isinstance(from_member, str):
            raise TypeError("from_member must be a string")
        validate_member_name(from_member)
    if before is not None and not isinstance(before, str):
        raise TypeError("before must be a string")
    before_ts = None if before is None else _validate_exact_message_id(before)
    if isinstance(limit, bool) or not isinstance(limit, int):
        raise TypeError("limit must be an integer")
    if not 1 <= limit <= 1_000:
        raise ValueError("limit must be between 1 and 1000")
    if not isinstance(reindex, bool):
        raise TypeError("reindex must be a boolean")
    _validate_scope_syntax(channel_selectors, dm_selectors)
    return _SearchRequest(
        chunks=chunks,
        channels=channel_selectors,
        direct_messages=dm_selectors,
        all_direct_messages=all_direct_messages,
        from_member=from_member,
        kinds=kind_values,
        before_ts=before_ts,
        limit=limit,
        reindex=reindex,
    )


def _search_hit(message: Message, row: ThreadRow) -> SearchHit:
    kind = row["kind"]
    raw_members = row["meta"].get("members")
    members = (
        cast(tuple[str, str], tuple(sorted(raw_members)))
        if kind == "dm"
        and isinstance(raw_members, list)
        and len(raw_members) == 2
        and all(isinstance(item, str) for item in raw_members)
        else None
    )
    return SearchHit(
        thread=message.thread,
        ts=message.ts,
        from_id=message.from_id,
        from_name=message.from_name,
        kind=message.kind,
        text=message.text,
        thread_kind=kind,
        channel=(row["parent"] if kind == "subthread" else row["name"])
        if kind in {"channel", "subthread"}
        else None,
        parent=row["parent"] if kind == "subthread" else None,
        members=members,
    )
