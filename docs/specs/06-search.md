# Taut Search Specification

Status: Active

## 1. Purpose and Scope [SRCH-1]

Search lets a person or agent find messages in the Taut history already visible
to them without changing chat history, membership, notification state, read
cursors, or activity. The primary surface is:

```text
taut search QUERY...
```

The Python API owns the behavior. The CLI is a thin parser and renderer over
that API, as required by [TAUT-8.3]. SQLite uses FTS5 in core. PostgreSQL uses
`tsvector` and a GIN index supplied by `taut-pg` through the provider contract
in [SRCH-7].

This spec governs query semantics, visible scope, result data, derived index
state, deferred indexing, crash recovery, reconciliation, backend interface
parity, and verification.

The optional `taut-mcp` extension exposes the same operation as its explicit
`search` tool under [MCP-5]. That adapter delegates one `TautClient.search`
call and inherits this specification's query, visibility, hydration,
reconciliation, result, and backend-quality contracts. It adds no search
language, ranking rule, or retry.

Out of scope for the first version:

- fuzzy, semantic, vector, regular-expression, prefix, and raw backend-query
  syntax
- aggregate facet counts, saved searches, alerts, and search subscriptions
- attachment or file indexing
- a resident search daemon or a required long-running service
- authentication or a new authorization model

## 2. Mental Model and Invariants [SRCH-2]

### [SRCH-2.1] Search is a derived view

SimpleBroker chat queues remain the only authoritative message bodies. The
search index is disposable derived state. It may store analyzer-derived
lexemes, segment data, stable message identifiers, and projection digests,
but it must not store a second verbatim message body. Rebuilding the index from
public SimpleBroker queue APIs plus Taut registry state must restore all search
behavior.

Taut persistence dumps exclude every search table and work queue. A restored
workspace starts with no search generation or jobs; the existing absent-
watermark reconciliation or explicit `--reindex` rebuilds from canonical
broker history and registry state. Load never gates on indexing.

"No second content copy" does not mean "no indexed representation." FTS5 and
`tsvector` necessarily store derived lexemes and positions. It means that exact
message text has one authority and every returned hit is hydrated from that
authority.

### [SRCH-2.2] Search cannot become a chat state transition

Search and its maintenance paths must not:

- consume, claim, move, rewrite, or delete chat rows
- advance `last_seen_ts`
- join or leave a thread
- create a member, identity claim, channel, sub-thread, DM, or notification
- update member activity or heal an identity claim
- make a chat write, delete, or rename fail because indexing failed

Search may mutate only its unregistered internal work queues and its
`taut_search_*` derived tables.

### [SRCH-2.3] Shared interface, backend-native lexical results

Core owns query validation and grammar, scope, visibility, ordering,
pagination, hydration, result fields, exit classes, and recovery policy.
Providers own physical index DDL and their pinned lexical analyzer. Raw FTS5
`MATCH`, PostgreSQL `tsquery`, ranking scores, and ambient database text-search
configuration are not public Taut interfaces.

SQLite and PostgreSQL expose the same Python/CLI interface and safety
invariants, but they are not required to return the same message IDs for every
Unicode query. Search is a lexical retrieval aid rather than an authoritative
state computation. SQLite uses [SRCH-11.1]'s pinned FTS5 analyzer; PostgreSQL
uses [SRCH-11.2]'s pinned built-in analyzer. Each analyzer is deterministic and
versioned within its backend, while normalization and token boundaries may
differ between backends. A provider-specific score must never appear in a
public result, and ordering of the hits a provider does return remains the
shared newest-first contract.

This is a deliberate deviation from the promoted plan's exact-result parity.
The exact-parity design required opaque hashed carriers, discarded useful
built-in analyzer behavior, and treated search results as authoritative when
only the API and visibility rules need to be authoritative. The portable floor
is ASCII letters/digits separated by ASCII punctuation or whitespace: shared
tests require identical results there. Unicode normalization, diacritic, and
backend lexeme-limit cases have explicit backend-specific tests and may differ.

## 3. Query Contract [SRCH-3]

### [SRCH-3.1] Query chunks and provider analysis

Core converts the query and every indexed `text` value to UTF-8 text without a
hashed or reversible ASCII carrier. It performs only the shared safe-query
split: Unicode `casefold()`, split where Python `str.isalnum()` is false,
discard empty chunks, retain first-occurrence order, and deduplicate. The
resulting Unicode chunks are supplied as data to the provider, never
interpolated as raw backend query syntax. Providers apply their pinned analyzer
to those chunks and to source projections.

Underscores, dots, slashes, colons, hyphens, and other punctuation are shared
separators. Thus `src/search_index.py` becomes `src`, `search`, `index`, `py`.
Backend normalization of each chunk may still differ. Version 1 requests no
stemming, stop-word list, locale-dependent ambient configuration, or camel-case
splitting; only behavior intrinsic to the pinned analyzer applies.

A query whose joined positional text yields no chunk is invalid and raises
`ValueError("search query must contain at least one alphanumeric token")`. A
query with more than 256 distinct chunks is invalid and raises
`ValueError("search query must contain at most 256 distinct query chunks")`. The
bound prevents backend expression/variable limits and unbounded intersection
work.

### [SRCH-3.2] Match and order

Every provider-analyzed term produced by every distinct query chunk is
required. A message matches when the provider's complete analyzed projection
contains every required term, even when terms fall in different physical
segments. Query-chunk order and duplicate chunks do not change the result.
Version 1 has no phrase, negation, wildcard, or OR grammar.

Results are ordered by `ts` descending, then `thread` ascending as a defensive
tie-breaker. Message IDs are globally unique under [TAUT-3.5], so the tie-breaker
must not fire for valid state. Search does not expose relevance order.

### [SRCH-3.3] Pagination and filters

`limit` defaults to 50 and accepts integers from 1 through 1,000 inclusive.
`before`, when present, is one full 19-digit message-ID string and is
exclusive. It uses the same string-only exact-ID validator as `message show`;
integers and booleans are rejected rather than silently canonicalized.

The following filters are conjunctive with the query and scope:

- zero or more `kind` values from the closed set `message`, `notice`, `foreign`;
  no values means all three kinds
- zero or one author selector; it resolves once through the current
  name-or-alias directory to a stable `member_id`, and matching uses
  `from_id`, not the historical `from` snapshot

An author filter never matches a foreign body because its `from_id` is null.

The Python method validates all arguments before incomplete-rename preflight,
provider discovery/schema setup, work processing, timestamp allocation,
reconciliation, rebuild, or identity/activity work. `query`, every channel/DM
selector, and `from_member` must be strings; `limit` must be an integer but not
`bool`; `before` is `str | None`; and `channels`, `direct_messages`, and
`kinds` must be non-string collections containing only strings. Wrong runtime
types raise `TypeError`; invalid values raise `ValueError`. The CLI maps both
to exit 1 before derived-state mutation.

## 4. Scope and Visibility [SRCH-4]

### [SRCH-4.1] Default and explicit scope

Bare search covers:

- every registered channel and one-level sub-thread
- every structurally valid DM accessible to the resolved actor under
  [IAN-5.3] and [IAN-6.4]

An unresolved actor may still search registered channels and sub-threads but
receives no DM candidates. This does not create or heal an identity.

The CLI and Python API support these scope selectors:

- repeatable channel selector: one canonical bare channel name such as
  `general` (never `#general`) and every currently registered child sub-thread
- repeatable DM selector: one existing `@name-or-alias` route or stable
  `dm.d_*` handle; a bare name without `@` is malformed
- all-DMs selector: every valid actor-accessible DM

When any explicit scope selector is present, its union replaces the default.
Duplicate resolutions collapse by canonical queue name. Every explicit
selector is validated before querying. Malformed selector syntax is a
validation error. One well-formed but absent, wrong-kind, or inaccessible
selector makes the whole operation an empty/not-found result. Search never
returns a partial scope after a selector miss.

Channel and sub-thread scope intentionally follows cursor-neutral `log`, not
membership-gated `read`: every registered non-DM chat thread is visible to a
storage peer even when the actor never joined or has left. DM visibility stays
participant-only. Search applies the existing incomplete-channel-rename
preflight after argument validation and before any derived mutation; an
incomplete marker raises the same exit-1 resume diagnostic as other
rename-sensitive operations.

### [SRCH-4.2] Candidate revalidation

An index match is only a candidate. Before returning it, core must:

1. verify that its thread is still registered as channel, sub-thread, or DM
2. re-check DM structure and actor access
3. fetch the exact pending source row through public
   `Queue.peek_one(exact_timestamp=..., with_timestamps=True)`
4. decode through the canonical tolerant message decoder
5. compare the hydrated text's SHA-256 digest and UTF-8 byte length with the
   indexed projection identity, then recompute scope and structured filters

A missing, claimed, deleted, moved, inaccessible, malformed-to-a-different
projection identity, or otherwise stale candidate is omitted and scheduled for index
repair. Hydration must continue until `limit` valid hits are found or the
candidate set is exhausted. Stale index state can cause a false negative under
the bounded foreign-write rules in [SRCH-10], but it must never cause a false
positive, expose a deleted body, or leak a DM.

Exact hydration relies on Taut's existing pending-row chat model: first-party
reads use cursors and do not claim or move chat rows. A future claim-based chat
reader must revise this contract rather than silently making canonical rows
unavailable to `peek_one()`.

## 5. Public Surfaces [SRCH-5]

### [SRCH-5.1] CLI

The core built-in command is:

```text
taut search QUERY... \
  [--channel CHANNEL]... \
  [--dm @NAME_OR_ALIAS_OR_HANDLE]... \
  [--dms] \
  [--from NAME_OR_ALIAS] \
  [--kind message|notice|foreign]... \
  [--before MSG_ID] \
  [--limit N] \
  [--reindex]
```

`QUERY...` is one or more positional shell arguments joined with one ASCII
space before tokenization. Literal `--` retains [TAUT-8.1] behavior. `--dms`
has no optional operand; one DM uses the separate repeatable `--dm` flag.

Exit classes are:

- 0: one or more hits
- 1: usage, malformed query/filter/pagination/selector syntax, unavailable
  provider, corrupt index state that cannot be rebuilt, or backend error
- 2: no matches, unresolved author, unresolved actor for DM-only scope, or any
  well-formed explicit scope selector miss

Quiet mode emits no success output but preserves the same exit class.
`--reindex` performs [SRCH-10.3]'s full rebuild before this query; it is not a
separate maintenance command.

### [SRCH-5.2] Python API and result model

Core exports this frozen, slotted value:

```python
SearchHit(
    thread: str,
    ts: int,
    from_id: str | None,
    from_name: str,
    kind: str,
    text: str,
    thread_kind: str,
    channel: str | None,
    parent: str | None,
    members: tuple[str, str] | None,
)
```

The canonical embedding method is:

```python
TautClient.search(
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
) -> list[SearchHit]
```

An empty result raises `EmptyResultError`, matching the CLI exit-2 class. The
method is the only owner of search semantics; the command adapter must not
reimplement scope, tokenization, reconciliation, or filtering.

An embedding surface that opens one `SearchHit` in surrounding history uses
core's [TAUT-7.9] `history_around(hit.thread, str(hit.ts), ...)` operation. It
must not call cursor-moving `show_message`, walk a private queue, or treat the
search page as a transcript store. A source row can disappear between search
hydration and open; the resulting exact not-found is normal convergence.

### [SRCH-5.3] JSON and human output

`--json` emits one NDJSON object per hit with this exact fixed field set:

```json
{"channel":"general","from":"van","from_id":"m_...","kind":"message","members":null,"parent":null,"text":"parser is green","thread":"general","thread_kind":"channel","ts":"1786032926849409024"}
```

`channel` is the top-level channel for channel and sub-thread hits and null for
DMs. `parent` is non-null only for sub-threads. `members` is the sorted pair of
stable member IDs only for DMs and null otherwise. `from` retains the message's
write-time display-name snapshot; the Python field is named `from_name` because
`from` is a keyword. JSON always returns the exact hydrated text, never only a
snippet. `SearchHit.ts` remains an integer in Python; the external NDJSON
adapter emits [TAUT-3.5]'s canonical 19-digit string.

These fixed fields are the facet contract. Version 1 does not emit aggregate
counts because counts over a limited page are misleading and counts over the
full match set add an independent query contract.

Human output groups nothing and prints newest first. Each hit includes its
escaped thread/DM label, author, full message ID when `--timestamps` is set, and
a bounded escaped excerpt around the first matched token. Excerpt generation
uses the hydrated body and the public terminal-text policy. Human excerpt
layout is not a stable contract.

### [SRCH-5.4] MCP surface

MCP accepts the [SRCH-5.2] arguments as named fields. JSON arrays are copied
to immutable string tuples before process transfer. A successful call returns
zero or more `search_hit` records whose fields are exactly [SRCH-5.3]'s JSON
fields. `ts` is a canonical 19-digit decimal string. Empty search is ordinary
success with no records. Search is cursor-, notification-, and member-activity
neutral, but it may reconcile disposable index state and `reindex=true`
rebuilds that state.

## 6. Projection and Physical Index [SRCH-6]

### [SRCH-6.1] Projection

Only the message `text` field is tokenized. Thread names, author names, member
IDs, and kinds are facets, not hidden content terms. Notices and tolerant
foreign bodies use the same projection as ordinary messages.

Core partitions UTF-8 source text into bounded provider segments, preferring
shared separator boundaries and never splitting a UTF-8 code point. Providers
analyze every segment. Segment boundaries cannot change the shared
newest-first/filter contract, but provider lexeme limits may omit an
unrepresentable term. In particular, PostgreSQL may omit a single lexical term
above its built-in lexeme limit; that backend-specific limitation is documented
and tested rather than hidden behind a second tokenizer or server extension.
An accepted [TAUT-6.4] body must never poison or stall indexing even when some
of its terms are not searchable.

### [SRCH-6.2] Required derived metadata

The logical index stores:

- message ID and indexed canonical thread
- SHA-256 digest and UTF-8 byte length of the exact indexed text
- projection version and ordered segment identifiers
- latest applied work revision and indexed/deleted state
- per-thread reconciliation watermark and rotation cursor

Public facets are derived from current registry state and the hydrated source,
not trusted from provider metadata. Provider filtering by stale author, kind,
or display-name data is forbidden because it could create a false negative.
The logical index stores no exact body text or display-name snapshot. Provider
tables are prefixed `taut_search_`.
The current schema requires a version read, not installation DDL. Newer
unsupported versions fail before shape-dependent mutation; supported schema 1
uses [SRCH-9.3]'s forward transition. Projection version 1 is validated for
each supported schema. A missing metadata table or singleton is fresh state.
Provider initialization and upgrade retain their backend transaction and lock
discipline. Physical column order and unrelated objects are not invariants.

Updating an unchanged indexed document advances only its accepted revision.
Postings are replaced only when thread, text digest, text byte length,
projection version, or indexed state differs. The revision fence and comparison
are atomic per generation, including an active staging generation.

### [SRCH-6.3] Deletion residue

Deleting a source row removes its live document and segment mappings before a
successful search can return it. Contentless FTS postings, PostgreSQL dead GIN
tuples, and storage pages may retain derived lexemes until rebuild, vacuum, or
ordinary database reuse. Taut promises logical removal and no second raw body;
it does not promise forensic erasure of derived index pages. `--reindex`
compacts Taut-owned logical index state but does not make a secure-erasure
claim.

## 7. Provider Boundary [SRCH-7]

Core defines one internal provider protocol. It owns no public plugin API and
does not expose provider objects from `taut` or `taut.client`. The protocol
must cover schema setup/version checks, conditional document upsert/delete,
candidate query, per-thread watermark state, rebuild, and
close. It accepts only canonical core value objects and UTF-8 projection
chunks, and returns stable message IDs, indexed thread, and projection identity.

Core constructs the resolved SimpleBroker queue and supplies the provider a
`Queue.sidecar()` session accessor. Every `taut_search_*` DDL and DML operation,
including FTS5 and PostgreSQL text-index objects, runs through that accessor,
using `transaction=True` for mutations. A provider must not construct a queue,
open an independent SQLite or PostgreSQL connection, retain a sidecar session
outside its context, or touch a non-`taut_search_*` table. This preserves the
connection, transaction, dialect, and busy-retry ownership in [TAUT-3.1] and
[TAUT-3.4].

SQLite selects the built-in core provider without reading installed metadata.
A Postgres target lazily resolves exactly one `postgres` entry point in
`taut.search_backends`, owned by distribution `taut-pg`. The entry point loads
a lightweight `SearchBackendSpec` with exactly
`search_provider_api_version: int`, `backend_name: str`, and
`implementation: str`. Version 1 requires API version integer 1 (not `bool`),
backend name `postgres`, and a strict `module:attribute` implementation target.
The implementation factory is loaded only on first search and is called as
`create_provider(*, sidecar=bound_queue_sidecar)`. It returns the internal
provider protocol; core closes it exactly once before closing the queue that
owns the accessor.

Discovery normalizes distribution ownership and filters eligible `taut-pg`
claims before counting ambiguity. Exactly one eligible official `postgres`
claim may load even when foreign distributions publish the same key; foreign
claims are never loaded. Zero or duplicate eligible official claims and the
existing manifest, load, or provider validation failures fail only search
with the actionable `taut-pg` diagnostic. Core never chooses among multiple
official claims by enumeration order. Core must not import `taut_pg` directly,
depend on `simplebroker-pg`, or
contain PostgreSQL SQL. This is a typed first-party cross-distribution seam,
not a public third-party plugin interface or root export.

The provider boundary is not permission to move domain behavior into the
extension. Tokenization, scope, hydration, warning policy, job bodies,
freshness, and public result shape remain core-owned.

## 8. Durable Work Queue and Write Ordering [SRCH-8]

### [SRCH-8.1] Internal queue

Core owns one unregistered pending invalidation queue, `taut.search_index`.
It is auxiliary search state and is excluded from logical dump/load [PIO-2.2].
It has no `taut_threads` row and never appears in chat routes, listings,
watch, or search scope. Ordinary broker tools may inspect it.

### [SRCH-8.2] Work item contract

One single-line JSON body identifies dirty source state without copying
content:

```json
{"entity":"message","message_ts":1786032926849409024,"thread":"general","v":1}
```

The closed version-1 entity set is `message` and `thread_rename`. Message
jobs identify one exact immutable message ID and a location hint. Rename jobs
carry the exact completed old/new pairs. The queue row timestamp is the work
revision. A structurally invalid job is exact-deleted after a bounded
structural warning enters `last_search_warnings`; neither its body nor a
sanitized copy enters another queue. A failed delete is a broker failure.
A successfully discarded malformed item does not block later valid work.

### [SRCH-8.3] Producer ordering and priority

After successful source writes, deletes, and completed channel renames, core
enqueues the corresponding content-free invalidation. Source success outranks
enqueue failure. That failure adds a warning to
`TautClient.last_search_warnings` and never reverses the source mutation.
Each source mutation and search clears that list on entry. CLI renders warnings
on stderr unless quiet; JSON success records do not gain a warning field.
Provider or broker failures that make search untrustworthy raise normally.
The commit-to-enqueue gap is repaired by [SRCH-10].

## 9. Pending Processing and Recovery [SRCH-9]

### [SRCH-9.1] Processing topology

Search runs pending work synchronously before querying. Indexing never runs
inside a source mutation. No detached worker, resident daemon, claim queue,
visibility timeout, worker lease, or failed-work queue is part of the contract.

### [SRCH-9.2] Pending operation

A search captures a finite pending-work frontier. It non-destructively reads
jobs through that frontier, loads current canonical source state, applies the
provider update, and only then exact-deletes the job. Concurrent searches may
duplicate processing. An already absent job after this search's successful
provider commit is success. A provider or broker failure leaves valid work
retryable and fails search.

### [SRCH-9.3] Source identity and revision order

For a message job, the provider conditionally upserts current source or records
a deletion tombstone. A job older than the latest accepted revision cannot
undo a newer update or deletion. Rename jobs remain revision-fenced hints.

The stored thread is a location hint, not message identity. Core exact-peeks
that registered thread first, then other currently registered searchable
threads by immutable message ID. A found message is indexed under its current
thread. At most one registry refresh occurs during a drain if a lookup misses.
Completed renames, cycles, and reuse of an old name remain valid. Source
hydration and reconciliation own current location and visibility.

Existing schema-1 search state upgrades forward in place to schema 2. The
transition returns claimed invalidations to pending through public queue
moves, discards failed envelopes, removes obsolete work queues and claim
tables, and updates the existing schema singleton last in the provider
transaction. Indexed documents, projection, generations, and watermarks
survive. Run the upgrade with old application processes stopped; there is
no mixed-version or downgrade contract. An interrupted transition is repeated
without rebuilding the index.

## 10. Reconciliation and Freshness [SRCH-10]

### [SRCH-10.1] Normal search freshness

Before querying, `TautClient.search()` captures the pending work frontier,
processes every valid job at or below that frontier, and compares every registered
searchable thread's public latest-pending message ID with its index watermark.
A higher source watermark triggers an incremental public
`peek_generator(after_timestamp=index_watermark)` scan. A lower source
watermark exact-checks the former latest row and reconciles its deletion. An
absent per-thread watermark triggers a full thread scan. These normal checks do
not claim to detect an overtaken mutation below an unchanged watermark.

Immediately before any in-place reconciliation scan, core allocates one fresh
`scan_revision` with `Queue.generate_timestamp()`. Every upsert and deletion
tombstone derived from that scan uses the same revision. The revision is
allocated before reading source rows: an older in-flight job therefore cannot
overwrite the scan, while a source mutation and job created after the scan
revision can supersede it. Rebuild remains generation-based under
[SRCH-10.3].

Therefore normal search must include every matching Taut-authored source row
whose message write and invalidation enqueue completed before the captured
frontier. The latest-ID comparison repairs a commit/enqueue crash gap or
foreign append while that mutation still changes the thread's latest-ID
watermark. A later append can overtake and hide the missed mutation, so the
rotating full-thread reconciliation in [SRCH-10.2], not the watermark alone,
owns eventual repair of every enqueue gap. Work arriving after the frontier
may appear in the same search but is not required to do so.

Concurrent searches may process the same pending item, relying on the provider
revision fence and delete-after-commit order in [SRCH-9.2].

### [SRCH-10.2] Foreign-write bound

Taut cannot infer every direct broker mutation from a latest-ID watermark. An
exact-ID restore below the watermark and deletion of a non-latest foreign row
may remain a false negative or dead derived posting until a full thread scan.
This limitation is explicit:

- each search invocation performs one rotating full-thread
  reconciliation after urgent work, so continued Taut activity converges
- first search on an absent index and every projection-version change performs
  a full rebuild
- `--reindex` gives the caller an immediate complete public-API rebuild
- candidate hydration still prevents stale positives before reconciliation

Reconciliation enumerates only registered channel, sub-thread, and valid
actor-independent DM queues. It uses public peek generators and Taut state; it
never reads SimpleBroker tables with SQL.

### [SRCH-10.3] Rebuild

Rebuild creates a new provider generation from canonical queues, verifies the
generation, then atomically makes it current. An interrupted build leaves the
prior current generation usable and the incomplete generation removable on
the next search. It must not empty the only current index before the replacement
is ready.

The provider marks the staging generation writable before core allocates the
rebuild scan revision. Every conditional message/delete/rename mutation then
targets both the current and writable staging generations in one provider
transaction. The rebuild scans canonical source with the one revision allocated
before source reads; later jobs have newer revisions and cannot be overwritten
by the scan. After verification, one provider transaction switches current and
clears the staging-writable state. A mutation transaction serializes on that
generation-state row, so it observes either both pre-switch writable
generations or the one post-switch current generation. This is the cutover
fence; holding a broker or sidecar transaction across the source scan is
forbidden. The ordinary commit-before-enqueue gap remains bounded by
[SRCH-10.2]'s reconciliation rule.

Persistence load creates no generation or jobs. This rebuild path is the
canonical restoration mechanism [PIO-2.2].

For actor privacy, rebuild may index all structurally valid DMs because the
derived state shares the same target and trust boundary, but query scope and
hydration always enforce actor access. Rebuild does not create chat registry or
membership state.

## 11. Backend Requirements [SRCH-11]

### [SRCH-11.1] SQLite

The core SQLite provider uses a Taut-owned metadata/segment table plus an FTS5
contentless virtual table configured with
`tokenize='unicode61 remove_diacritics 2'`. Core supplies the UTF-8 chunks from
[SRCH-3.1] as values; the provider safely quotes them and requires every
FTS5-analyzed term. Candidate queries join through live segment metadata so a
deleted mapping cannot return a stale posting. Segment row IDs are never reused
while stale contentless postings may exist. Rebuild constructs the inactive
physical FTS slot and switches generations under [SRCH-10.3].

SQLite generation publication and clearing of the now-inactive physical FTS
slot remain one writer transaction. A query racing that commit may read
generation metadata and per-chunk match sets from different committed
snapshots and may therefore omit matching candidates, including returning an
empty candidate page for that call; retry is the recovery. The race must not
expose the writer transaction's intermediate `DROP TABLE` as a
user-visible missing-table failure. Query evaluation must preserve
message-ID intersection across physical segment rows under [SRCH-3.2];
combining all chunks into one row-scoped FTS `MATCH` expression is not
behavior-equivalent.

FTS5 absence is detected when search is first used. It produces a one-line
search-unavailable error and exit 1; initialization and every non-search Taut
operation remain usable. Taut does not silently switch to a second linear-scan
query implementation.

### [SRCH-11.2] PostgreSQL

`taut-pg` owns PostgreSQL search-provider code, DDL, `to_tsvector`/`tsvector`
construction, GIN indexes, revision SQL, generation switching, and
PG-only tests. It registers the provider entry point defined by [SRCH-7]. It
uses the explicit `pg_catalog.simple` text-search configuration only as a
provider analyzer for the UTF-8 chunks from [SRCH-3.1]. It uses
`to_tsvector('pg_catalog.simple', ...)` and a safely constructed AND query; it
must not use ambient database configuration, English stemming, or stop words.

Every PostgreSQL search-schema initialization transaction acquires
`pg_advisory_xact_lock(hashtextextended('taut:search:schema', 0))` as its first
statement before DDL or schema-version reads/writes. Concurrent first-use
searches therefore converge instead of relying on `IF NOT EXISTS`
alone. Search-schema GIN creation uses ordinary transactional
`CREATE INDEX IF NOT EXISTS`, not `CREATE INDEX CONCURRENTLY`, because the
advisory-lock initialization is one transaction.

The provider stores no raw `text`, does not use `ts_headline`, and returns no
PostgreSQL rank. Queries intersect message IDs across physical segments. Terms
that exceed PostgreSQL's built-in lexeme limit may be absent as allowed by
[SRCH-6.1]; they must not fail the document or later work items.

Version 1 uses only PostgreSQL facilities available without `CREATE EXTENSION`:
`tsvector`, GIN, `pg_catalog.simple`, and built-in advisory locks. It must not
require `pg_trgm`, a compiled tokenizer, superuser access, or any other optional
server extension. A future extension-backed optimization requires its own spec
delta, an explicit capability probe, and a behavior-identical built-in
fallback.

This is the first sanctioned PostgreSQL-specific Taut behavior in
`extensions/taut_pg`; it explicitly revises [TAUT-12.1]'s previous
packaging/docs/tests-only boundary. Core remains free of PostgreSQL SQL and of
the `simplebroker-pg` dependency.

## 12. Failure and Verification Contract [SRCH-12]

System doctor reads public statistics for `taut.search_index` without
creating or processing work. It reports `{"pending": N}` using
`QueueStats.total`, or zero if absent. Pending depth is informational and
does not prove index health or freshness [DOCT-4.6].

### [SRCH-12.1] Failure priorities

- Successful source mutation outranks invalidation enqueue.
- Search correctness and DM visibility outrank returning a partial page.
- Malformed work is warned and discarded by structural code. Provider,
  source, and broker failures are not reclassified as malformed.
- A valid job remains pending if processing fails. Search fails rather than
  claim completeness it has not established.
- Search/provider schema corruption fails loudly. A future schema needs a
  forward release; explicit `--reindex` repairs disposable index content.

### [SRCH-12.2] Required proof

Real SQLite and PostgreSQL tests cover the public query, visibility, source
hydration, provider revision and generation behavior, backend analyzer edges,
and no authoritative chat side effects. Work tests cover the closed job
shapes, malformed-then-valid progress, duplicate processing, provider commit
before exact delete, and replay after a failure between commit and delete.
Forward-upgrade tests preserve hits and generation, return old claimed work,
remove obsolete work state, and resume an interrupted transition. Current
schema checks emit no installation DDL; unsupported future schema and
projection versions refuse without mutation. The unchanged-document fast path
is proved without postings replacement in both current and staging generations.

No test replaces the real broker queue or provider transaction in a claimed
integration proof. Benchmark records cover cold/warm and deletion-heavy search
at 1, 10, and 100 threads with 100 jobs for transient and persistent clients.
Record physical backend creations, queue handles, registry reads, exact source
probes, postings writes, and elapsed time. Timing is evidence, not a CI
threshold.

## Related Plans

- `docs/plans/2026-09-28-simplification-and-hot-path-plan.md`
- `docs/plans/2026-09-14-audit-remediation-plan.md`: plans exact-message source lookup and removal of obsolete segmentation proof.

- `docs/plans/2026-08-25-semantic-compatibility-hardening-plan.md` — makes
  search schema checks version-first and semantic, and filters eligible
  first-party provider ownership before ambiguity.
- retired: 2026-08-24-concurrency-and-schema-contract-alignment-plan — source `6e8c3da`; see the ledger in `docs/plans/README.md`.
- `docs/plans/2026-08-10-test-quality-remediation-plan.md` — strengthens
  backend known-answer conformance and dynamically proves the no-raw-body
  invariant across every search-owned ordinary table.
- retired: 2026-08-10-mcp-search-plan — source `58f8524`; see the ledger in `docs/plans/README.md`.
- retired: 2026-08-10-simplebroker-7-json-id-boundary-plan — source `50a67eb`; see the ledger in `docs/plans/README.md`.
- retired: 2026-08-10-system-doctor-plan — source `6ef344f`; see the ledger in `docs/plans/README.md`.
- retired: 2026-08-07-taut-dump-load-plan — source `9410b6b`; see the ledger in `docs/plans/README.md`.
- retired: 2026-08-06-taut-search-plan — source `136cdad`; see the ledger in `docs/plans/README.md`.
- retired: 2026-08-06-taut-search-spec-draft — source `136cdad`; see the ledger in `docs/plans/README.md`.
