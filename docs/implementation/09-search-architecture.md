# Search Architecture

## Purpose and Governing Contract

This note explains why Taut search is a disposable, source-hydrated view and
where its backend, queue, and freshness boundaries live. The intended behavior
is governed by `docs/specs/06-search.md` [SRCH-1] through [SRCH-12]. The
delivery record is `docs/plans/2026-08-06-taut-search-plan.md`.

## Ownership and Boundaries

Core owns the public query grammar, scope, DM visibility, author and kind
filters, newest-first pagination, exact source hydration, durable work bodies,
claim timeout, reconciliation, and result facets. These rules live in
`taut/client/_searching.py` and `taut/search/`. The CLI adapter in
`taut/commands/search.py` parses and renders only; it delegates semantics to
`TautClient.search()`.

The SQLite physical provider lives in core at `taut/search/_sqlite.py` because
FTS5 is part of the default runtime. PostgreSQL SQL lives only in
`extensions/taut_pg/taut_pg/_search.py`. Core discovers that provider lazily
through the strict first-party descriptor in `taut/search/_discovery.py`.
Both providers receive a bound `Queue.sidecar()` accessor. Neither opens a
connection or reads broker-private tables.

Search tables store derived lexical representations, message IDs, canonical
thread names, projection digests and lengths, revisions, and generation state.
They do not store the exact message body. Every candidate is fetched again
from its registered SimpleBroker source queue and checked against its digest
and current visibility before it becomes a `SearchHit`. This makes stale
postings safe omissions, never authoritative chat records.

## Lexical Analysis Decision

The providers intentionally share an interface rather than exact Unicode
result identity. Core creates safe UTF-8 query chunks and never accepts raw
FTS query syntax. SQLite pins FTS5 `unicode61 remove_diacritics 2`;
PostgreSQL pins the built-in `pg_catalog.simple` configuration and built-in
GIN. No PostgreSQL server extension is required or probed.

Exact cross-backend result equality was rejected because opaque ASCII token
carriers would replace useful native lexical behavior and make search look
like an authoritative computation. The portable contract is exact for the
documented ASCII floor. Backend-specific Unicode and lexeme-limit behavior is
versioned and tested. Public fields, filters, visibility, pagination, and
ordering remain backend-neutral.

## Deferred Work and Recovery

Every Taut-authored source write, delete, or completed channel rename enqueues
one content-free invalidation in `taut.search_index`. Indexing never runs in
the source mutation. Enqueue failure leaves the source result successful and
adds a warning to `TautClient.last_search_warnings`; CLI source commands emit
that warning on stderr unless quiet.

Workers claim one row by exact broker move into
`taut.search_index.claimed`, then publish a unique lease in
`taut_search_claims`. Provider commit precedes acknowledgement. A missing
lease is immediately reclaimable; an active lease becomes visible again after
60 seconds. The timeout is evidence for retry, not proof of worker death, so
all provider mutations use monotonic revisions. Malformed jobs go to a
content-free failed envelope.

The claim record stores both the required HLC `claimed_at` and wall-clock
nanoseconds. The HLC is durable diagnostic order; wall time owns the 60-second
elapsed-time decision because comparing a packed logical clock to elapsed
nanoseconds would couple core to private timestamp representation.

A search captures pending and claimed work through a fixed frontier. It claims
pending IDs exactly and idempotently reads through valid work already owned by
another worker, so it does not wait for the visibility timeout. Reconciliation
then repairs public-source changes that bypassed enqueue. One registered thread
is fully reconciled per invocation using a durable rotation cursor; per-thread
watermarks provide the cheaper ordinary path. Explicit `--reindex` and schema
or projection changes build a new generation while the old one remains live.
Normal mutations dual-write an active generation when their revision is new
enough. The provider switches only after the scan and frontier drain succeed.

## Process Rollout Decision

The first release does not launch a process or thread after every source
mutation. Durable enqueue plus search-time bounded work gives correctness and
keeps the write path free of process startup, PostgreSQL connection bursts,
and SQLite lock amplification. The spec permits, but does not require, a
short-lived detached worker. Enabling it later requires the benchmark gate in
[SRCH-9.1] and does not change job or provider semantics.

## Verification and Operational Signals

Behavioral proof is split by owner:

- `tests/test_search.py` covers projection, SQLite FTS, revision fences,
  generations, retargeting, and no exact-body copy.
- `tests/test_search_jobs.py` and `tests/test_search_worker.py` cover strict job
  shapes, claim/reclaim races, quarantine, acknowledgement, and work frontiers.
- `tests/test_search_client.py` and `tests/test_search_cli.py` cover public
  scope, hydration, filters, reconciliation, warnings, and rendering.
- `extensions/taut_pg/tests/test_pg_search_provider.py` runs the corresponding
  physical provider proof against real PostgreSQL.

Operators should treat growing pending/claimed depth, a claimed row older than
60 seconds, repeat failed envelopes for well-formed work, rebuild failure, or
search-triggered cursor/activity changes as defects. The index is disposable:
rollback can disable the command/provider path while preserving source chat,
and a later `--reindex` recreates derived state.

Known non-corrupting limits are intentional for version 1. A SQLite query that
races a cross-process generation switch can omit a page and succeed on retry;
completed rename-marker name reuse can transiently misdirect old work until
reconciliation; and SQLite common-term lookup materializes each term's match
set before intersection. These affect transient recall or memory, not source
truth, access control, or stale-positive prevention.
