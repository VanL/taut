# Search Architecture

## Purpose and Governing Contract

This note explains why Taut search is a disposable, source-hydrated view and
where its backend, queue, and freshness boundaries live. The intended behavior
is governed by `docs/specs/06-search.md` [SRCH-1] through [SRCH-12]. The
core delivery record is the retired plan 2026-08-06-taut-search-plan (source `136cdad`; see the ledger in `docs/plans/README.md`); the MCP
adapter record is the retired plan 2026-08-10-mcp-search-plan (source `58f8524`; see the ledger in `docs/plans/README.md`).

## Ownership and Boundaries

Core owns the public query grammar, scope, DM visibility, author and kind
filters, newest-first pagination, exact source hydration, durable work bodies,
pending processing, reconciliation, and result facets. These rules live in
`taut/client/_searching.py` and `taut/search/`. The CLI adapter in
`taut/commands/search.py` parses and renders only; it delegates semantics to
`TautClient.search()`.

The optional MCP adapter follows the same boundary. Its manifest validates
named JSON fields, the process reactor copies selector arrays to tuples, and
the child dispatcher supplies defaults and calls `TautClient.search()` once.
It adds no query grammar, post-filter, rank rule, retry, or provider branch.
Its explicit `SearchHit` projection converts the domain timestamp to a
19-digit string and emits the same ten public facets through closed channel,
subthread, and DM result branches. An empty core result becomes an ordinary
empty `search_hit` envelope.

The SQLite physical provider lives in core at `taut/search/_sqlite.py` because
FTS5 is part of the default runtime. PostgreSQL SQL lives only in
`extensions/taut_pg/taut_pg/_search.py`. Core discovers that provider lazily
through the strict first-party descriptor in `taut/search/_discovery.py`.
Discovery filters inert entry-point metadata by backend name and normalized
`taut-pg` distribution ownership before it counts eligible claims. Foreign
same-name claims are ignored and never loaded; zero or multiple eligible
first-party claims fail search without affecting other Taut operations.
Both providers receive a bound `Queue.sidecar()` accessor. Neither opens a
connection or reads broker-private tables.

Search tables store derived lexical representations, message IDs, canonical
thread names, projection digests and lengths, revisions, and generation state.
They do not store the exact message body. Every candidate is fetched again
from its registered SimpleBroker source queue and checked against its digest
and current visibility before it becomes a `SearchHit`. This makes stale
postings safe omissions, never authoritative chat records.

Each provider reads the stable schema/projection version pair before deciding
whether installation work is needed. Current version 2 skips installation DDL.
The supported version-1 transition retains the existing index and generation;
the provider transaction removes claim tables and publishes version 2 last.
Core first returns any old claimed queue rows to pending with public broker
operations under the operator's quiescence precondition. An interrupted move
can be repeated. The move API need not select the oldest row first: original
message timestamps are preserved, and no worker drains either queue during the
upgrade. No projection or document rebuild is part of this upgrade.
The unchanged-document path advances its revision without replacing postings.
This comparison and the revision fence occur in the same provider transaction
for both current and staging generations.

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

Core case-folds, splits, orders, and deduplicates source text through the same
canonical chunk logic used for queries, then packs whole chunks into preferred
byte-sized projection segments. An indivisible chunk may exceed that preferred
size and remains intact. This is the production projection supplied to both
providers; search does not retain a second raw-text segmenter or promise that
joining projection segments reconstructs the source body.

Human excerpts search the case-folded body but slice the exact hydrated source
text. Because one source code point can fold to several code points (for
example, `ß` to `ss`), the renderer translates the folded match offset with a
constant-space scan of the original text. A match inside an expanded fold maps
to the original code point containing that folded span; a span boundary maps
to the following source code point. JSON results continue to emit the complete
hydrated source text.

## Deferred Work and Recovery

Every Taut-authored source write, delete, or completed channel rename enqueues
one content-free invalidation in `taut.search_index`. Indexing never runs in
the source mutation. Enqueue failure leaves the source result successful and
adds a warning to `TautClient.last_search_warnings`; CLI source commands emit
that warning on stderr unless quiet. The MCP child clears notification and
search warnings before every domain command, then returns notification
warnings before search warnings. Warning delivery never changes the successful
source result and cannot leak into a later operation.

Search captures a finite pending frontier, reads those jobs without consuming
them, applies the revision-fenced provider mutation, and exact-deletes each job
only after commit. Concurrent searches may duplicate work. A provider or broker
failure leaves valid work pending. Malformed bodies are discarded with a bounded
structural warning; there is no failure queue.

One operation-scoped BrokerSession anchors directly created persistent source
and work handles, which close before the anchor. The drain reads the searchable
registry once and refreshes it at most once after a source miss. It keeps
indexed exact-ID probes for unresolved messages. Reconciliation then repairs
public-source changes that bypassed enqueue. One registered thread
is fully reconciled per invocation using a durable rotation cursor; per-thread
watermarks provide the cheaper ordinary path. Explicit `--reindex` and schema
or projection changes build a new generation while the old one remains live.
Normal mutations dual-write an active generation when their revision is new
enough. The provider switches only after the scan and frontier drain succeed.

## Process Boundary

Search-time pending processing keeps the write path free of process startup,
PostgreSQL connection bursts, and SQLite lock amplification. No detached
worker is part of the current search contract.

## Verification and Operational Signals

Behavioral proof is split by owner:

- `tests/test_search.py` covers projection, SQLite FTS, revision fences,
  generations, retargeting, no exact-body copy, and real source-shaped
  version-before-mutation refusal.
- `tests/test_search_jobs.py` and `tests/test_search_worker.py` cover strict
  job shapes, commit-before-delete,
  malformed-item progress, duplicate work, and finite frontiers.
- `tests/test_search_client.py` and `tests/test_search_cli.py` cover public
  scope, hydration, filters, reconciliation, warnings, and rendering.
- `tests/test_shared_contract.py` pins the public portable ASCII result set,
  newest-first order, and state neutrality against both real backends.
- `extensions/taut_pg/tests/test_pg_search_provider.py` runs the corresponding
  physical provider proof plus public Unicode, diacritic, and oversized-lexeme
  expectations against real PostgreSQL. Schema assertions inspect required
  columns and GIN index semantics, not physical column ordinals or unrelated
  objects in the namespace.
- `extensions/taut_mcp/tests/test_tools.py` covers the adapter boundary against
  real SQLite, including facets, state neutrality, warnings, provider errors,
  empty success, reindex, and cancellation.
- `extensions/taut_mcp/tests/test_stdio_server.py` covers canonical MCP framing
  and exact discovery in both protocol eras.
- `extensions/taut_mcp/tests/test_pg_conformance.py` compares the MCP result to
  direct `TautClient.search()` over real PostgreSQL while leaving Unicode
  lexical behavior backend-native.

Operators should watch for growing pending depth, rebuild failure, or
search-triggered cursor/activity changes. Pending depth alone does not prove
index health or freshness. The index remains disposable; explicit `--reindex`
recreates derived content when needed.

Known non-corrupting limits are intentional for version 1. A SQLite query that
races a cross-process generation switch can omit a page and succeed on retry.
The writer publishes the generation switch and drops and recreates the
inactive FTS table inside one transaction, so another connection sees the
state before or after that transaction, not its intermediate missing table.
The query's metadata read and per-chunk FTS reads are separate committed
snapshots, however, so a generation change between them may produce an empty
or incomplete candidate set.

That multi-statement query is required by the physical projection. One
message may place different query terms in different segment rows, while one
combined FTS `MATCH` expression is evaluated against one row. The provider
therefore intersects each chunk's matches by message id across rows. Replacing
that intersection with one combined expression would make valid cross-segment
matches disappear even without a race. A message invalidation's stored thread
is only a fast source hint. On a miss, search exact-peeks the other current
registered searchable queues by immutable message ID and indexes the message
under the queue where it is found. This makes completed rename markers recovery
state rather than a permanent redirect graph. The accepted cost is one exact
probe per current searchable queue for a stale hint. SQLite common-term lookup
also materializes each term's match set before intersection. These limits
affect transient recall or memory, not source truth, access control, or
stale-positive prevention.

## Related Plans

- `docs/plans/2026-09-28-simplification-and-hot-path-plan.md`
- `docs/plans/2026-08-24-command-runtime-findings-remediation-plan.md`
- `docs/plans/2026-08-25-semantic-compatibility-hardening-plan.md`
- retired: 2026-08-24-concurrency-and-schema-contract-alignment-plan — source `6e8c3da`; see the ledger in `docs/plans/README.md`.
- retired: 2026-08-14-review-findings-remediation-plan — source `76b1ec4`; see the ledger in `docs/plans/README.md`.
- retired: 2026-08-10-mcp-search-plan — source `58f8524`; see the ledger in `docs/plans/README.md`.
- retired: 2026-08-06-taut-search-plan — source `136cdad`; see the ledger in `docs/plans/README.md`.
