# Taut Search: Proposed Spec Draft

Date: 2026-08-06

Status: draft. This file is the review target for
`docs/plans/2026-08-06-taut-search-plan.md`. The spec-promotion slice copies
the accepted text to `docs/specs/06-search.md` with `Status: Active` and applies
the companion core and addressing deltas in section 13. Until that slice, the
governing contract remains the spec tree at
`9318e3b64ffda6106c00a32b9842f914d815c49f`.

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
state, deferred indexing, crash recovery, reconciliation, backend parity, and
verification.

Out of scope for the first version:

- fuzzy, semantic, vector, regular-expression, prefix, and raw backend-query
  syntax
- aggregate facet counts, saved searches, alerts, and search subscriptions
- attachment or file indexing
- an MCP search tool; adding one requires an explicit [MCP-*] spec revision
- a resident search daemon or a required long-running service
- authentication or a new authorization model

## 2. Mental Model and Invariants [SRCH-2]

### [SRCH-2.1] Search is a derived view

SimpleBroker chat queues remain the only authoritative message bodies. The
search index is disposable derived state. It may store fixed-width canonical
token carriers, segment data, stable message identifiers, and facet metadata,
but it must not store a second verbatim message body. Rebuilding the index from
public SimpleBroker queue APIs plus Taut registry state must restore all search
behavior.

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

### [SRCH-2.3] Backend-neutral behavior

Core owns tokenization, query validation, scope, visibility, ordering,
pagination, hydration, result fields, exit classes, and recovery policy.
Providers own physical index DDL and the translation of a canonical query into
backend operations. Raw FTS5 `MATCH`, PostgreSQL `tsquery`, ranking scores, and
backend tokenizer behavior are not public Taut contracts.

SQLite and PostgreSQL must return the same ordered message IDs for the same
canonical source state and query. A provider-specific score must never appear
in a public result.

## 3. Query Contract [SRCH-3]

### [SRCH-3.1] Canonical tokens

The query and every indexed `text` value use one core tokenizer:

1. apply Unicode `casefold()`
2. split at every character for which Python `str.isalnum()` is false
3. discard empty tokens
4. retain the resulting token sequence for canonical match verification

The physical projection deduplicates the tokens because version 1 has only
token-presence AND matching. It converts every distinct token to this ASCII
carrier before passing it to either provider:

```text
u + lowercase_hex(sha256(token.encode("utf-8")))
```

The carrier is exactly 65 ASCII alphanumeric characters. Providers must index
and match carriers byte-for-byte and must not drop or further transform one.
A SHA-256 collision can add only a candidate: [SRCH-4.2] recomputes the
unhashed canonical tokens from the source and removes the false positive. It
cannot create a returned false match or a backend-specific result.

Underscores, dots, slashes, colons, hyphens, and other punctuation are
separators. Thus `src/search_index.py` becomes `src`, `search`, `index`, `py`,
and the same spelling in a query resolves identically. There is no stemming,
stop-word removal, locale-dependent configuration, or camel-case splitting.

A query whose joined positional text yields no token is invalid and raises
`ValueError("search query must contain at least one alphanumeric token")`.

### [SRCH-3.2] Match and order

Every distinct query token is required. A message matches when its complete
canonical token projection contains every query token, even when the tokens
fall in different physical index segments. Query-token order and duplicate
query tokens do not change the result. Version 1 has no phrase, negation,
wildcard, or OR grammar.

Results are ordered by `ts` descending, then `thread` ascending as a defensive
tie-breaker. Message IDs are globally unique under [TAUT-3.5], so the tie-breaker
must not fire for valid state. Search does not expose relevance order.

### [SRCH-3.3] Pagination and filters

`limit` defaults to 50 and accepts integers from 1 through 1,000 inclusive.
`before`, when present, is one full 19-digit message ID and is exclusive.

The following filters are conjunctive with the query and scope:

- zero or more `kind` values from the closed set `message`, `notice`, `foreign`;
  no values means all three kinds
- zero or one author selector; it resolves once through the current
  name-or-alias directory to a stable `member_id`, and matching uses
  `from_id`, not the historical `from` snapshot

An author filter never matches a foreign body because its `from_id` is null.

## 4. Scope and Visibility [SRCH-4]

### [SRCH-4.1] Default and explicit scope

Bare search covers:

- every registered channel and one-level sub-thread
- every structurally valid DM accessible to the resolved actor under
  [IAN-5.3] and [IAN-6.4]

An unresolved actor may still search registered channels and sub-threads but
receives no DM candidates. This does not create or heal an identity.

The CLI and Python API support these scope selectors:

- repeatable channel selector: one registered top-level channel and every
  currently registered child sub-thread
- repeatable DM selector: one existing current route or stable `dm.d_*` handle
- all-DMs selector: every valid actor-accessible DM

When any explicit scope selector is present, its union replaces the default.
Duplicate resolutions collapse by canonical queue name. Every explicit
selector is validated before querying. Malformed selector syntax is a
validation error. One well-formed but absent, wrong-kind, or inaccessible
selector makes the whole operation an empty/not-found result. Search never
returns a partial scope after a selector miss.

### [SRCH-4.2] Candidate revalidation

An index match is only a candidate. Before returning it, core must:

1. verify that its thread is still registered as channel, sub-thread, or DM
2. re-check DM structure and actor access
3. fetch the exact pending source row through public
   `Queue.peek_one(exact_timestamp=..., with_timestamps=True)`
4. decode through the canonical tolerant message decoder
5. recompute tokens and filters against the hydrated source

A missing, claimed, deleted, moved, inaccessible, malformed-to-a-different
projection, or otherwise stale candidate is omitted and scheduled for index
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
  [--dm NAME_OR_ALIAS_OR_HANDLE]... \
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
    before: int | str | None = None,
    limit: int = 50,
    reindex: bool = False,
) -> list[SearchHit]
```

An empty result raises `EmptyResultError`, matching the CLI exit-2 class. The
method is the only owner of search semantics; the command adapter must not
reimplement scope, tokenization, reconciliation, or filtering.

### [SRCH-5.3] JSON and human output

`--json` emits one NDJSON object per hit with this exact fixed field set:

```json
{"channel":"general","from":"van","from_id":"m_...","kind":"message","members":null,"parent":null,"text":"parser is green","thread":"general","thread_kind":"channel","ts":1786032926849409024}
```

`channel` is the top-level channel for channel and sub-thread hits and null for
DMs. `parent` is non-null only for sub-threads. `members` is the sorted pair of
stable member IDs only for DMs and null otherwise. `from` retains the message's
write-time display-name snapshot; the Python field is named `from_name` because
`from` is a keyword. JSON always returns the exact hydrated text, never only a
snippet.

These fixed fields are the facet contract. Version 1 does not emit aggregate
counts because counts over a limited page are misleading and counts over the
full match set add an independent query contract.

Human output groups nothing and prints newest first. Each hit includes its
escaped thread/DM label, author, full message ID when `--timestamps` is set, and
a bounded escaped excerpt around the first matched token. Excerpt generation
uses the hydrated body and the public terminal-text policy. Human excerpt
layout is not a stable contract.

## 6. Projection and Physical Index [SRCH-6]

### [SRCH-6.1] Projection

Only the message `text` field is tokenized. Thread names, author names, member
IDs, and kinds are facets, not hidden content terms. Notices and tolerant
foreign bodies use the same projection as ordinary messages.

Core partitions the deduplicated carrier stream into bounded provider segments
so every accepted [TAUT-6.4] body, including one 10 MB alphanumeric token, can
be indexed without exceeding PostgreSQL `tsvector` limits. Segment boundaries
cannot change match behavior because [SRCH-3.2] intersects message IDs per
query carrier across all segments. The exact segment byte bound is an internal
provider constant and must have a cross-backend boundary test; it is not a
public query limit.

### [SRCH-6.2] Required derived metadata

The logical index stores:

- message ID and canonical thread
- thread kind, top-level channel or parent, and DM members
- stable `from_id`, display-name snapshot, and message kind
- projection version and ordered segment identifiers
- latest applied work revision and indexed/deleted state
- per-thread reconciliation watermark and rotation cursor

It stores no exact body text. Provider tables are prefixed `taut_search_`.
Schema creation is idempotent and additive. A newer unsupported search schema
or projection version fails search with an upgrade diagnostic but must not
block non-search Taut operations.

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
close. It accepts only canonical core value objects, including ASCII token
carriers, and returns stable message IDs plus facet metadata.

Core constructs the resolved SimpleBroker queue and supplies the provider a
`Queue.sidecar()` session accessor. Every `taut_search_*` DDL and DML operation,
including FTS5 and PostgreSQL text-index objects, runs through that accessor,
using `transaction=True` for mutations. A provider must not construct a queue,
open an independent SQLite or PostgreSQL connection, retain a sidecar session
outside its context, or touch a non-`taut_search_*` table. This preserves the
connection, transaction, dialect, and busy-retry ownership in [TAUT-3.1] and
[TAUT-3.4].

SQLite selects the built-in core provider. A Postgres target resolves one
installed provider from a versioned `taut.search_backends` entry point owned by
`taut-pg`. Missing, duplicate, incompatible, or broken providers fail only
search with an actionable `taut-pg` upgrade/install diagnostic. Core must not
import `taut_pg` directly, depend on `simplebroker-pg`, or contain PostgreSQL
SQL.

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

### [SRCH-8.2] Work item contract

One single-line JSON body identifies dirty source state without copying
content:

```json
{"entity":"message","message_ts":1786032926849409024,"thread":"general","v":1}
```

The closed version-1 entity set is:

- `message`: refresh or remove one exact message from current source state
- `thread_rename`: update the affected channel/sub-thread facets after a
  completed canonical rename; the body also carries `old`, `new`, and the
  exact affected old/new name pairs from the durable rename marker

The work queue row timestamp is the work revision. Unknown versions, unknown
entities, missing fields, wrong types, and non-JSON bodies are moved from
claimed to `taut.search_index.failed` with their original body and ID; they do
not stall later jobs or crash the worker. No automatic retry reads failed work.

### [SRCH-8.3] Producer ordering and priority

After every successful Taut-authored chat or notice `Queue.write()`, the common
message-write path writes a `message` invalidation. After physical message
delete, it writes the same invalidation. After channel rename has fully
committed and cleared its recovery marker, it writes `thread_rename`.

The source operation is already successful before invalidation enqueue. An
enqueue failure or worker-launch failure is best-effort: it records a warning
on the client/CLI diagnostic surface but never changes the source result or
causes a Taut retry. Cursor and notification ordering remain governed by
[TAUT-7.4], [IAN-7.3], and [TAUT-10]; search invalidation is auxiliary derived
work and is not inserted into those correctness chains.

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
by job ID with `claimed_at` from `Queue.generate_timestamp()` and an opaque
diagnostic worker ID. SimpleBroker move preserves the original job timestamp,
so that timestamp must not be treated as claim time.

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

After the provider transaction commits, the worker exact-deletes the job from
claimed and removes claim metadata. A crash has these outcomes:

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

For actor privacy, rebuild may index all structurally valid DMs because the
derived state shares the same target and trust boundary, but query scope and
hydration always enforce actor access. Rebuild does not create chat registry or
membership state.

## 11. Backend Requirements [SRCH-11]

### [SRCH-11.1] SQLite

The core SQLite provider uses a Taut-owned metadata/segment table plus an FTS5
contentless virtual table configured with
`tokenize='unicode61 remove_diacritics 0'`. FTS rows contain only the
65-character ASCII carriers from [SRCH-3.1]. Exact whole-carrier queries must
return every segment containing that carrier; SQLite tokenization must never
be applied to raw canonical tokens. Candidate queries join through live
segment metadata so a deleted mapping cannot return a stale posting. Segment
row IDs are never reused while stale contentless postings may exist. Rebuild
uses FTS5's documented full-reset path and constructs a new logical generation.

FTS5 absence is detected when search is first used. It produces a one-line
search-unavailable error and exit 1; initialization and every non-search Taut
operation remain usable. Taut does not silently switch to a second linear-scan
query implementation.

### [SRCH-11.2] PostgreSQL

`taut-pg` owns PostgreSQL search-provider code, DDL, `to_tsvector`/`tsvector`
construction, GIN indexes, claim/revision SQL, generation switching, and
PG-only tests. It registers the provider entry point defined by [SRCH-7]. It
uses the explicit `pg_catalog.simple` text-search configuration only as a
carrier for the 65-character ASCII values from [SRCH-3.1]; PostgreSQL text
search must never receive raw canonical tokens. It must not use ambient
database configuration, English stemming, or stop words.

Every PostgreSQL search-schema initialization transaction acquires
`pg_advisory_xact_lock(hashtextextended('taut:search:schema', 0))` as its first
statement before DDL or schema-version reads/writes. Concurrent first-use
searches and workers therefore converge instead of relying on `IF NOT EXISTS`
alone. Search-schema GIN creation uses ordinary transactional
`CREATE INDEX IF NOT EXISTS`, not `CREATE INDEX CONCURRENTLY`, because the
advisory-lock initialization is one transaction.

The provider stores no raw `text`, does not use `ts_headline`, and returns no
PostgreSQL rank. Physical segments keep every canonical token below backend
limits and queries intersect message IDs across segments.

This is the first sanctioned PostgreSQL-specific Taut behavior in
`extensions/taut_pg`; it explicitly revises [TAUT-12.1]'s previous
packaging/docs/tests-only boundary. Core remains free of PostgreSQL SQL and of
the `simplebroker-pg` dependency.

## 12. Failure and Verification Contract [SRCH-12]

### [SRCH-12.1] Failure priorities

- Source chat mutation success outranks invalidation enqueue and worker launch.
- Search correctness and DM visibility outrank returning a partially hydrated
  page.
- A malformed job is isolated to the failed queue; a provider/storage failure
  is not misclassified as malformed input.
- One poison message projection cannot stall other jobs. Its failure remains
  inspectable and causes search to warn or fail when completeness for the
  current query cannot be established.
- Search/provider schema corruption fails search loudly without traceback or
  silent repair. Explicit rebuild is the forward repair for disposable index
  contents; a newer schema requires an upgrade.

### [SRCH-12.2] Required proof

Every enumerable CLI flag, exit class, result field, job entity/version, crash
window, message kind, scope mode, provider failure, and reconciliation mode
requires a firing test. At minimum, real SQLite and PostgreSQL tests prove:

- identical canonical tokenization and ASCII carriers over an adversarial
  Unicode matrix, direct proof that each provider emits one unchanged carrier
  lexeme, collision-safe hydration, cross-segment AND matching, newest-first
  pagination, filters, fixed JSON fields, and terminal-safe human output
- default channel/sub-thread/DM scope, explicit union scope, selector failure,
  malformed-selector exit 1, well-formed selector-miss exit 2, and corrupt-DM
  fail-closed behavior
- zero cursor, membership, activity, identity-claim, notification, and chat-row
  side effects
- successful chat write despite enqueue and detached-launch failure
- broker acceptance of every `taut.search_index*` queue name and exclusion of
  those queues from every chat route, listing, watch, and search surface
- real pending-to-claimed move, acknowledgement after provider commit, all
  crash-window recoveries, 60-second expiration under a controlled timestamp,
  concurrent duplicate workers, and old-revision suppression after delete
- first-use bootstrap, ordinary enqueue-gap repair, foreign append repair,
  scan-revision ordering against an older worker and a newer mutation, an
  enqueue gap overtaken by a later append, rotating reconciliation, explicit
  rebuild, interrupted-generation rollback, and projection-version rebuild
- physical message deletion and channel rename never return stale text/name
- no raw message body in any `taut_search_*` ordinary table or queue payload
- FTS5 absence, missing/incompatible PG provider, and concurrent PG
  search-schema initialization fail or converge exactly as specified

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

## 13. Proposed Companion Spec Deltas

These changes promote atomically with `docs/specs/06-search.md`.

### [SRCH-D1] `docs/specs/02-taut-core.md` [TAUT-1]

Add search to the governed core surface and point its full contract to
`docs/specs/06-search.md` [SRCH-1] through [SRCH-12].

### [SRCH-D2] `docs/specs/02-taut-core.md` [TAUT-3.3] and [TAUT-3.4]

Append to [TAUT-3.3]:

> Search adds disposable `taut_search_*` provider tables under [SRCH-6] and
> [SRCH-11]. They are derived state inside the resolved SimpleBroker target,
> not a second message authority. Search schema/version failure is isolated
> from the core sidecar schema and cannot block non-search operations.

Replace [TAUT-3.4]'s final sentence, `Taut does not query private broker tables
or maintain a message-id index or cache.`, with:

> Exact-message operations do not query private broker tables and do not rely
> on the disposable search index. Search may map message IDs to derived
> segments solely for [SRCH-4.2] candidate hydration; canonical lookup and
> deletion still locate registered chat queues and use public exact-ID APIs.

### [SRCH-D3] `docs/specs/02-taut-core.md` [TAUT-8.1]

Add this verb row:

> | `search QUERY... [--channel CHANNEL]... [--dm TARGET]... [--dms] [--from MEMBER] [--kind KIND]... [--before MSG_ID] [--limit N] [--reindex]` | Cursor-neutral search over registered chat and actor-accessible DMs. Query, scope, freshness, and repair follow spec 06. | 0 hits; 1 usage, malformed selector, provider, or index error; 2 no hits or well-formed explicit selector miss |

Help must teach token-AND semantics, default and explicit scope, newest-first
order, full-ID exclusive `--before`, the 1..1,000 limit, and `--reindex` cost.

### [SRCH-D4] `docs/specs/02-taut-core.md` [TAUT-8.2]

Add:

> Search hit objects have exactly `thread`, `ts`, `from_id`, `from`, `kind`,
> `text`, `thread_kind`, `channel`, `parent`, and `members`, with nullability
> and facet semantics defined by [SRCH-5.3]. They always contain hydrated
> source text and never a provider score or snippet-only substitute.

### [SRCH-D5] `docs/specs/02-taut-core.md` [TAUT-8.3]

Add `SearchHit` to the public exports and add the exact
`TautClient.search(...) -> list[SearchHit]` signature from [SRCH-5.2]. State
that the CLI adapter owns only argument translation and rendering.

### [SRCH-D6] `docs/specs/02-taut-core.md` [TAUT-10]

Append to the compound-operation ordering rule:

> Search invalidation enqueue and detached worker launch occur only after the
> source operation's existing success point. Both are auxiliary best-effort
> work: failure warns but never downgrades the source result or changes cursor
> or notification ordering. [SRCH-10] reconciles the deliberate
> commit-before-enqueue crash window.

### [SRCH-D7] `docs/specs/02-taut-core.md` [TAUT-12.1]

Replace the first implementation-boundary bullet with:

> `extensions/taut_pg` owns packaging, docs, PG-only tests, and the installed
> PostgreSQL search provider defined by [SRCH-7] and [SRCH-11.2]. It owns no
> target resolution, queue construction, identity, general CLI behavior,
> watcher behavior, or search domain semantics. PostgreSQL search DDL and
> query translation stay in the extension, but operate only through the
> core-supplied public `Queue.sidecar()` accessor and the fixed search-schema
> advisory lock. All other Taut sidecar SQL remains core-owned.

### [SRCH-D8] `docs/specs/03-identity-addressing-notifications.md` [IAN-6.1]

Append after the `sys.*` paragraph:

> Core-owned unregistered system queues use the reserved `taut.*` namespace.
> Search owns `taut.search_index`, `taut.search_index.claimed`, and
> `taut.search_index.failed` under [SRCH-8]. They are invisible to every chat
> route and listing surface; only the owning core subsystem consumes them.

## Related Plans

- `docs/plans/2026-08-06-taut-search-plan.md` (draft) defines promotion,
  implementation slices, hardening gates, and independent review.
