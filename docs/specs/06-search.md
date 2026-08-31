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
provider discovery/schema setup, work claiming, timestamp allocation,
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
Schema creation is idempotent and additive. A newer unsupported search schema
or projection version fails search with an upgrade diagnostic but must not
block non-search Taut operations.

Each provider may create the metadata table if absent, because that statement
is a no-op for an existing table. It then reads the singleton's stored schema
and projection versions before any insert, update, or provider-object DDL
that assumes the current shape. No singleton row is the fresh-initialization
case. An existing row whose stable version fields cannot be read is not
fresh; it fails without being rewritten. Older or newer versions follow
their declared refusal or transition path. Provider schema checks require
owned names, types, constraints, and indexes as semantic subsets. Physical
column order, unrelated additional objects, and unowned additional columns
are not provider invariants.

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
candidate query, per-thread watermark state, claim metadata, rebuild, and
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
extension. Tokenization, scope, hydration, warning policy, job bodies, claim
timeout, freshness, and public result shape remain core-owned.

## 8. Durable Work Queue and Write Ordering [SRCH-8]

### [SRCH-8.1] Internal queues

Core owns three unregistered system queues in the resolved SimpleBroker target:

```text
taut.search_index
taut.search_index.claimed
taut.search_index.failed
```

They have no `taut_threads` row, never appear in `list`, `read`, `log`,
`watch`, or search scope, and are inspectable with ordinary broker tooling.
Only search code reads, moves, writes, or deletes them.

The queues are excluded from Taut persistence I/O [PIO-2.2].

### [SRCH-8.2] Work item contract

One single-line JSON body identifies dirty source state without copying
content:

```json
{"entity":"message","message_ts":1786032926849409024,"thread":"general","v":1}
```

This work item is an internal stored broker body. Its `message_ts` remains a
JSON integer and decodes strictly to a Python integer; the external-output
string rule does not rewrite durable search work.

The closed version-1 entity set is:

- `message`: refresh or remove one exact message from current source state
- `thread_rename`: update the affected channel/sub-thread facets after a
  completed canonical rename; the body also carries `old`, `new`, and the
  exact affected old/new name pairs from the durable rename marker

The work queue row timestamp is the work revision. Unknown versions, unknown
entities, missing fields, wrong types, and non-JSON bodies are quarantined
without copying their content: the worker writes one failed-queue JSON envelope
containing version 1, the original job ID, UTF-8 byte length, SHA-256 digest,
and a bounded structural error code, then exact-deletes the claimed original
only after that write succeeds. A failed quarantine write leaves the original
claimed for timeout recovery. Malformed foreign content therefore cannot make
the no-content-copy rule false. Failed work does not stall later jobs or crash
the worker, and no automatic retry reads the failed queue.

### [SRCH-8.3] Producer ordering and priority

After every successful Taut-authored chat or notice `Queue.write()`, the common
message-write path writes a `message` invalidation. After physical message
delete, it writes the same invalidation. After channel rename has fully
committed and marked its durable recovery marker complete, it writes
`thread_rename`.

The source operation is already successful before invalidation enqueue. An
enqueue failure or worker-launch failure is best-effort: it records a warning
on the client/CLI diagnostic surface but never changes the source result or
causes a Taut retry. Cursor and notification ordering remain governed by
[TAUT-7.4], [IAN-7.3], and [TAUT-10]; search invalidation is auxiliary derived
work and is not inserted into those correctness chains.

The Python warning carrier is `TautClient.last_search_warnings: list[str]`.
Each public source mutation and each search call clears it on entry, then
appends one escaped, self-describing diagnostic per enqueue/launch/quarantine
warning. The CLI renders those warnings to stderr after the primary successful
result; `--quiet` suppresses both success output and these best-effort warnings.
JSON success records never gain a warning field. Search/provider failures that
make the requested result untrustworthy raise normally rather than entering
this warning list. A detached worker cannot mutate its launching client's
memory; its quarantine events are observable through the durable failed queue,
while inline/search-time draining may also append the warning locally.

This ordering deliberately leaves a crash window between source commit and
invalidation enqueue. Reconciliation in [SRCH-10] owns that gap. Taut never
attempts a cross-transaction fiction between a chat queue and search work.

## 9. Workers, Claims, and Recovery [SRCH-9]

### [SRCH-9.1] Worker topology

Indexing must never run inline with a source mutation. A producer may make a
best-effort detached launch of a fresh short-lived worker process after
enqueue. Long-lived first-party processes may also request bounded drain work,
but all contexts call the same core worker function. Taut requires no resident
daemon, service manager, background thread, or user configuration.

A detached worker opens fresh queue and provider handles. It must not inherit
live broker connections through `fork`, resolve a member, update activity, or
write to inherited stdout/stderr. It drains available work, observes one short
quiet check, and exits. Concurrent worker processes are legal.

The implementation plan must benchmark detached launch overhead, burst process
count, SQLite busy incidence, PostgreSQL connection count, and time to
searchability before making launch-on-every-write the default. This is a
rollout gate, not a wall-clock CI assertion.

### [SRCH-9.2] Claim operation

A worker claims exactly one job immediately before processing it by atomically
moving its exact ID from `taut.search_index` to
`taut.search_index.claimed`. It then writes search-owned claim metadata keyed
by job ID with `claimed_at` from `Queue.generate_timestamp()`, an opaque
diagnostic worker ID, and a unique lease ID. SimpleBroker move preserves the
original job timestamp, so that timestamp must not be treated as claim time.

A claimed item with no claim record or a `claimed_at` at least 60 seconds old
is reclaimable by moving it back to pending and removing its claim record.
Sixty seconds is a visibility timeout, not proof of death. A slow worker may
therefore overlap a retry; idempotency and revision ordering are required.

Workers claim one item at a time. Batch reservation is forbidden because an
item waiting behind its batch peers could expire before processing begins.

### [SRCH-9.3] Success, failure, and monotonic revision

For a `message` job, the worker reads current canonical source state. Existing
source means project and conditionally upsert; absent source means conditionally
mark deleted. The provider applies the operation only when the job revision is
not older than the document's latest revision. A deletion retains a small
revision tombstone so a timed-out older worker cannot resurrect stale index
state after a newer deletion.

Before source lookup, the worker consults durable completed channel-rename
markers through a new core state accessor that returns completed affected
mappings. It follows mappings transitively to the current queue; a cycle or
malformed chain is corruption and fails search work. This redirect depends on
completed rename markers remaining durable; pruning them requires a future
replacement mapping and spec revision. The `thread_rename` job conditionally
retargets every affected indexed document at its own revision. Thus an older
old-name message job cannot tombstone a renamed live document, while a message
job enqueued after one or more renames resolves and indexes the current queue.
Both relative orderings and a two-rename chain require real tests.

After the provider transaction commits, the worker rechecks that claim metadata
still contains its lease ID, exact-deletes the job from claimed, and removes
claim metadata only with a conditional lease-ID match. A changed lease means a
new claimant owns acknowledgement, so the old worker exits successfully without
deleting either row. If exact delete loses to a concurrent acknowledger, it is
success only after the provider proves its applied revision is at least the job
revision; otherwise it remains a failure. A crash has these outcomes:

| Crash point | Durable result | Recovery |
|-------------|----------------|----------|
| before move | pending job | another worker claims it |
| after move, before claim metadata | claimed without lease | immediately reclaimable; duplicate processing is safe |
| after claim metadata, before index commit | claimed with lease | reclaim after 60 seconds |
| after index commit, before acknowledgement | indexed plus claimed | retry is a conditional idempotent no-op |
| after claimed delete, before claim-row delete | stale claim metadata only | cleanup removes it |

A transient provider or broker failure leaves the valid job claimed and exits
the worker so timeout recovery applies. A structurally bad job follows
[SRCH-8.2]'s failed-queue path instead.

A crash after writing a sanitized failed envelope but before deleting the
claimed malformed job may produce another envelope after timeout recovery.
Duplicate quarantine envelopes for one `original_job_ts` are valid and
diagnostic consumers must deduplicate if they need counts by original job.

## 10. Reconciliation and Freshness [SRCH-10]

### [SRCH-10.1] Normal search freshness

Before querying, `TautClient.search()` captures the current pending and claimed
work frontier, processes every valid job at or below that frontier (duplicate
processing with an active worker is allowed), and compares every registered
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

Search never waits 60 seconds for a non-expired claim. It may safely process
that claimed source state concurrently and acknowledge it after a successful
conditional index commit.

### [SRCH-10.2] Foreign-write bound

Taut cannot infer every direct broker mutation from a latest-ID watermark. An
exact-ID restore below the watermark and deletion of a non-latest foreign row
may remain a false negative or dead derived posting until a full thread scan.
This limitation is explicit:

- each worker/search invocation performs one rotating full-thread
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
construction, GIN indexes, claim/revision SQL, generation switching, and
PG-only tests. It registers the provider entry point defined by [SRCH-7]. It
uses the explicit `pg_catalog.simple` text-search configuration only as a
provider analyzer for the UTF-8 chunks from [SRCH-3.1]. It uses
`to_tsvector('pg_catalog.simple', ...)` and a safely constructed AND query; it
must not use ambient database configuration, English stemming, or stop words.

Every PostgreSQL search-schema initialization transaction acquires
`pg_advisory_xact_lock(hashtextextended('taut:search:schema', 0))` as its first
statement before DDL or schema-version reads/writes. Concurrent first-use
searches and workers therefore converge instead of relying on `IF NOT EXISTS`
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

The fixed system doctor observes exactly the three search work queues from
[SRCH-8.1]: pending, claimed, and failed. It reports their `QueueStats.total`
depths without claiming, moving, acknowledging, rebuilding, or loading a search
provider. Nonzero failed depth is a finding; pending or claimed depth is
informational. The check does not prove work freshness, inspect physical search
tables, reclaim leases, or replace [SRCH-8.2] and [SRCH-9] recovery behavior
[DOCT-5].

### [SRCH-12.1] Failure priorities

- Source chat mutation success outranks invalidation enqueue and worker launch.
- Search correctness and DM visibility outrank returning a partially hydrated
  page.
- A malformed job is isolated to the failed queue; a provider/storage failure
  is not misclassified as malformed input.
- A malformed job is non-authoritative foreign work: quarantine warns and
  reconciliation remains the correctness owner. A structurally valid job whose
  source cannot be projected or whose provider mutation fails remains claimed;
  a search processing that job fails with exit 1 because its selected-scope
  completeness cannot be established. Neither class stalls unrelated later
  work permanently.
- Search/provider schema corruption fails search loudly without traceback or
  silent repair. Explicit rebuild is the forward repair for disposable index
  contents; a newer schema requires an upgrade.

### [SRCH-12.2] Required proof

Every enumerable CLI flag, exit class, result field, job entity/version, crash
window, message kind, scope mode, provider failure, and reconciliation mode
requires a firing test. At minimum, real SQLite and PostgreSQL tests prove:

- identical results over the portable ASCII floor, pinned backend-specific
  results over an adversarial Unicode/diacritic/lexeme-limit matrix,
  cross-segment AND matching, digest-based stale-candidate rejection,
  newest-first pagination, filters, fixed JSON fields, and terminal-safe human
  output
- default channel/sub-thread/DM scope, explicit union scope, selector failure,
  malformed-selector exit 1, well-formed selector-miss exit 2, and corrupt-DM
  fail-closed behavior
- zero cursor, membership, activity, identity-claim, notification, and chat-row
  side effects
- successful chat write despite enqueue and detached-launch failure
- broker acceptance of every `taut.search_index*` queue name and exclusion of
  those queues from every chat route, listing, watch, and search surface
- real pending-to-claimed move, lease-conditional acknowledgement after
  provider commit, acknowledgement-loser proof, all crash-window recoveries,
  60-second expiration under a controlled timestamp, concurrent duplicate
  workers, and old-revision suppression after delete and rename
- first-use bootstrap, ordinary enqueue-gap repair, foreign append repair,
  scan-revision ordering against an older worker and a newer mutation, an
  enqueue gap overtaken by a later append, rotating reconciliation, explicit
  rebuild, interrupted-generation rollback, and projection-version rebuild
- physical message deletion and channel rename never return stale text/name
- no raw message body or display-name snapshot in any `taut_search_*` ordinary
  table or Taut-produced valid/quarantine queue payload
- FTS5 absence, missing/incompatible PG provider, and concurrent PG
  search-schema initialization fail or converge exactly as specified
- PostgreSQL initialization issues no `CREATE EXTENSION` statement and works
  for a role that can create ordinary schema objects but cannot install server
  extensions
- the [MCP-5] adapter accepts every public scope/filter argument, freezes
  selector arrays before process transfer, delegates exactly one
  `TautClient.search` call, emits [SRCH-5.3]'s exact external record fields and
  string IDs, returns a typed empty success for no matches, preserves cursor,
  activity, and notification state, and exercises reconciliation and rebuild
  through real SQLite and PostgreSQL providers without requiring identical
  backend-native Unicode hit sets

Do not mock SimpleBroker move/delete/peek, the provider database, source
hydration, process launch integration, or DM state in the tests that claim
those contracts. A launcher unit may mock `Popen` only to prove exact detachment
arguments; at least one real child-process test must prove fresh handles,
bounded exit, crash residue, and later recovery. Async visibility tests use
deterministic barriers or bounded polling, never fixed sleeps as correctness
proof.

Operational acceptance records, without turning host timing into CI truth:

- added source-write latency distribution with detached launch enabled and
  disabled
- time from write commit to normal-search visibility
- maximum concurrent worker and PostgreSQL connection count under a burst
- pending, claimed, expired, and failed queue depths
- full rebuild duration and index size relative to source body bytes

## Related Plans

- `docs/plans/2026-08-25-semantic-compatibility-hardening-plan.md` — makes
  search schema checks version-first and semantic, and filters eligible
  first-party provider ownership before ambiguity.
- `docs/plans/2026-08-24-concurrency-and-schema-contract-alignment-plan.md` —
  makes the accepted SQLite generation-switch omission and cross-segment query
  boundary explicit.
- `docs/plans/2026-08-10-test-quality-remediation-plan.md` — strengthens
  backend known-answer conformance and dynamically proves the no-raw-body
  invariant across every search-owned ordinary table.
- `docs/plans/2026-08-10-mcp-search-plan.md` — exposes this operation through
  one explicit MCP tool while preserving core-owned semantics and backend-
  native lexical quality.
- `docs/plans/2026-08-10-simplebroker-7-json-id-boundary-plan.md` — formats
  public search hit ids while preserving numeric internal work items.
- `docs/plans/2026-08-10-system-doctor-plan.md` defines the passive fixed
  search-work observation and its non-repair boundary.
- `docs/plans/2026-08-07-taut-dump-load-plan.md` defines search exclusion and
  post-load rebuild behavior.
- `docs/plans/2026-08-06-taut-search-plan.md` defines the reviewed promotion,
  implementation slices, hardening gates, and independent review.
- `docs/plans/2026-08-06-taut-search-spec-draft.md` preserves the reviewed
  pre-promotion contract and exact companion deltas.
