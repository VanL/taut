# Taut Search Implementation Plan

Date: 2026-08-06

Class: 5, spec-changing and risky. [DOM-6] requires a new normative search
contract. [DOM-5] risky triggers also fire because the change adds a public CLI
and Python API, deferred work, new persistence and cleanup lifecycles, a
short-lived subprocess path, and the first PostgreSQL-specific Taut behavior in
`taut-pg`.

Status: completed. Implementation, local verification, and the explicit Opus
completed-work review passed. The owner authorized the final commit and plan
closure on 2026-08-06.

Plan type: implementation with spec revision.

## 1. Goal

Add cursor-neutral, agent-usable full-text message search with one public and
safety contract across SQLite and PostgreSQL, while allowing pinned native
analyzers to return different Unicode result sets. Message writes remain
independent of indexing. A SimpleBroker internal queue carries durable,
content-free invalidations; short-lived workers may index them outside the
source command; every returned candidate is rehydrated from canonical history.

Requested outcomes:

- [x] `taut search QUERY...` supports bounded scope, author, kind, and time
  filters with deterministic NDJSON and 0/1/2 exits.
- [x] `TautClient.search()` owns the same semantics and returns typed,
  decomposable facet fields.
- [x] SQLite core uses FTS5; `taut-pg` supplies PostgreSQL `tsvector`/GIN code
  through a narrow provider seam.
- [x] no second verbatim message body exists in the search store.
- [x] successful chat mutations enqueue best-effort durable invalidations but
  never wait for index completion or fail because indexing failed.
- [x] atomic move, per-item visibility timeout, revision ordering, rebuild, and
  reconciliation cover worker crashes and missed/foreign invalidations.
- [x] real SQLite, real PostgreSQL, and real concurrent-worker proof cover the
  shipped public and lifecycle contracts; detached child launch and its
  subprocess proof are explicitly deferred by the section-13 rollout decision.
- [x] specs, README, implementation docs, repository map, and code citations
  form the required closed traceability chain.

## 2. Source Documents

Source specs at the plan baseline:

- `docs/specs/01-development-documentation-operating-model.md` [DOM-5],
  [DOM-6], [DOM-10], [DOM-11], [DOM-15]
- `docs/specs/02-taut-core.md` [TAUT-1], [TAUT-2], [TAUT-3], [TAUT-6],
  [TAUT-7], [TAUT-8], [TAUT-10], [TAUT-11], [TAUT-12.1]
- `docs/specs/03-identity-addressing-notifications.md` [IAN-3], [IAN-4],
  [IAN-5], [IAN-6], [IAN-8]

Proposed full contract:

- `docs/specs/06-search.md` [SRCH-1] through [SRCH-12] is the promoted
  governing contract. The historical reviewed delta remains in
  `docs/plans/2026-08-06-taut-search-spec-draft.md`.

Process and architecture guidance:

- `docs/agent-context/runbooks/writing-plans.md`
- `docs/agent-context/runbooks/hardening-plans.md`
- `docs/agent-context/runbooks/writing-specs.md`
- `docs/agent-context/runbooks/testing-patterns.md`
- `docs/agent-context/runbooks/adversarial-acceptance-probes.md`
- `docs/agent-context/runbooks/review-loops-and-agent-bootstrap.md`
- `docs/implementation/04-taut-architecture.md`
- `docs/implementation/06-command-extensions.md`

The product/design source is the 2026-08-06 discussion that selected a
SimpleBroker durable work queue, atomic move to a claimed queue, delete only
after index commit, a 60-second per-item claim timeout, no raw content copy,
and evaluation of a detached temporary worker process.

## 3. Spec Baseline and Promotion

- Spec baseline: `9318e3b64ffda6106c00a32b9842f914d815c49f`.
- Files governed at baseline: `docs/specs/02-taut-core.md` and
  `docs/specs/03-identity-addressing-notifications.md`.
- The new search spec does not yet exist in the spec tree. The full proposed
  text lives in the adjacent draft so review can occur without presenting it
  as adopted behavior.
- This repository has no machine spec-classification tool. Prose `Status:` and
  the docs-reference gates are the available mechanisms.
- Promotion strategy: A, text before implementation-link claims. After review,
  copy the accepted draft to `docs/specs/06-search.md` with `Status: Active`,
  apply [SRCH-D1] through [SRCH-D8], add it to the specs index and docs gates,
  and add plan backlinks. Do not add implementation mapping claims or code
  citations until their reciprocal code exists.
- Promotion baseline: base
  `9318e3b64ffda6106c00a32b9842f914d815c49f` plus uncommitted promotion
  manifest SHA-256
  `0ddcf0085ff9fd929787cf68250e42d4d566302358846d2f82ea67b34bfd4bd8` over
  `docs/specs/00-specs-index.md`, `docs/specs/02-taut-core.md`,
  `docs/specs/03-identity-addressing-notifications.md`,
  `docs/specs/06-search.md`, and `tests/test_docs_references.py` before the
  recorded analyzer deviation.
- All later compliance claims are against the promotion baseline, not this
  appendix or the pre-promotion SHA.
- Post-deviation runtime baseline: base
  `9318e3b64ffda6106c00a32b9842f914d815c49f` plus manifest SHA-256
  `8f4906f80a172c2d7595cfd50d394eb0ead7fc04f8e1122d2ecb8ca6c01efc59`
  over the promotion files plus this plan. Runtime work after round 3 is
  evaluated against this reviewed revision.

## 4. Proposed Spec Delta

The exact review target is
`docs/plans/2026-08-06-taut-search-spec-draft.md`.

| Target | Proposed sections | Promotion strategy |
|--------|-------------------|--------------------|
| new `docs/specs/06-search.md` | [SRCH-1] through [SRCH-12] | A: active text first, no premature implementation claims |
| `docs/specs/02-taut-core.md` | [SRCH-D1] through [SRCH-D7] at [TAUT-1], [TAUT-3.3], [TAUT-3.4], [TAUT-8.1], [TAUT-8.2], [TAUT-8.3], [TAUT-10], [TAUT-12.1] | A: exact text in promotion slice |
| `docs/specs/03-identity-addressing-notifications.md` | [SRCH-D8] at [IAN-6.1] | A: exact text in promotion slice |
| `docs/specs/00-specs-index.md`, `docs/specs/README.md` | add search to numbered reading order | A: same promotion slice |
| `tests/test_docs_references.py` | admit and require the `[SRCH-*]` family and new spec path | promotion firing gate |

The delta is intentionally a separate file because it is a substantial new
contract. After promotion, the spec tree is canonical and the draft remains
historical review material only.

## 5. Current Structure and Required Reading

### Current owners and edit points

| Current path | Current responsibility | Search consequence |
|--------------|------------------------|--------------------|
| `taut/client/__init__.py` | `TautClient` facade, target/state construction, public client composition | compose a search mixin/runtime without putting semantics in CLI or PG |
| `taut/client/_messaging.py::_write_message` | one envelope/write/decode path used by ordinary messages and notices | enqueue create invalidations here after the existing write success point |
| `taut/client/_messaging.py::delete_message` | exact author-owned physical delete | enqueue deletion invalidation only after exact delete succeeds |
| `taut/client/_threads.py::rename_channel` and resume helpers | durable marker plus broker/state rename convergence | enqueue one completed rename invalidation after marker clearance |
| `taut/client/_base.py::_ClientBase` | resolved target, queue ownership, state lifetime, client warnings | add search provider/worker ownership without opening handles eagerly for non-search calls |
| `taut/state/` | portable Taut sidecar state and SQL dialect | do not put FTS5 or PostgreSQL search SQL into the general state interface |
| `taut/commands/_builtins.py` | static lightweight built-in manifests | register `search` lazily as a core command |
| `taut/commands/log.py`, `_rendering.py`, `_protocol.py` | nearest parser, message output, and command adapter patterns | reuse option/global/terminal/NDJSON policy; do not clone domain rules |
| `extensions/taut_pg/taut_pg/__init__.py` | currently empty public package | keep public facade small; provider implementation stays private |
| `extensions/taut_pg/pyproject.toml` | PG extension metadata, no Taut entry point today | register exactly one versioned search-provider entry point |
| `tests/test_client.py`, `tests/test_cli.py`, `tests/test_cli_probes.py` | real SQLite API/CLI/adversarial contracts | add search public and hostile-input proof |
| `tests/test_shared_contract.py` | behavior executed on SQLite and through `bin/pytest-pg` | own backend-neutral result and lifecycle parity |
| `extensions/taut_pg/tests/` | real PG-only package/provider proof | own provider discovery, DDL, GIN, schema and cleanup tests |
| `docs/implementation/04-taut-architecture.md` | why core/PG/client/CLI boundaries exist | explain the final provider and worker design after implementation |
| `docs/implementation/02-repository-map.md` | navigational ownership map | add search modules, worker entry point, provider and tests |

### Required comprehension gate

Before editing, the implementer must answer in the plan execution log:

1. Why can `_write_message` enqueue only after `Queue.write()` returns, and why
   must enqueue failure not enter [TAUT-10]'s existing message/cursor success
   chain?
2. Why does `Queue.move_one()` provide a durable reservation but not a claim
   age, and which timestamp records the 60-second visibility timeout?
3. Which search rules must remain in core when PostgreSQL DDL and query
   translation move into `taut-pg`?
4. Why must exact candidate hydration use public queue APIs even though the
   provider already has a message ID and facets?
5. Which direct broker mutations cannot be proven from a latest-message
   watermark, and what path closes that gap?

Incorrect or vague answers stop the slice before code changes.

## 6. Invariants and Constraints

1. **One body authority.** Exact text exists only in SimpleBroker chat history;
   job payloads and ordinary `taut_search_*` tables contain no raw body.
2. **Source success outranks indexing.** No enqueue, process launch, worker,
   provider, or reconciliation failure downgrades a successful message write,
   delete, or rename.
3. **No inline indexing.** Source commands may synchronously write the small
   durable invalidation and request a detached launch, but never tokenize,
   scan, or update the index before returning.
4. **No daemon requirement.** Zero long-lived Taut processes remains valid.
5. **One public contract.** Core owns grammar, scope, visibility, ordering,
   filters, hydration, exits, and facets. SQLite and PG use pinned analyzers and
   may return different Unicode matches, but cannot expose raw backend grammar,
   scores, ambient configuration, or ranking.
6. **Public broker boundary.** No SQL against SimpleBroker-owned tables and no
   private SimpleBroker import. Real `Queue.write`, `move_one`, `peek_*`,
   `delete`, latest-ID, broker queue enumeration, and core-supplied
   `Queue.sidecar()` access are the allowed seams. Providers open no independent
   connection and touch only `taut_search_*` objects through the accessor.
7. **Cursor-neutral and identity-neutral.** Search never changes activity,
   claims, membership, cursors, notifications, or chat rows.
8. **DM fail-closed.** Index metadata never grants visibility. Current registry,
   membership, and exact source hydration decide every returned DM hit.
9. **At-least-once processing.** Duplicates and timeout overlap are expected;
   conditional revision/tombstone logic prevents old work from winning.
10. **One-at-a-time claims.** Workers do not reserve batches that can expire
    while waiting behind earlier items.
11. **Bounded poison handling.** One malformed work item or oversized source
    cannot stall the queue or emit a traceback.
12. **Full accepted-body coverage.** Provider segmentation, not silent
    truncation, handles the 10 MB [TAUT-6.4] body ceiling.
13. **No hidden dependency.** Use stdlib, SQLite FTS5, and PostgreSQL facilities
    already supplied by the installed backend. Any new dependency proposal is
    a stop gate requiring user approval.
14. **No PostgreSQL server extension.** The built-in `tsvector`, GIN,
    `pg_catalog.simple`, and advisory-lock path must work without
    `CREATE EXTENSION` privilege. An optional extension fast path is separate
    future work and cannot replace the built-in path.
15. **No drive-by MCP or TUI change.** Their future search surfaces need their
    own governing delta.

## 7. Hidden Couplings and Failure Priorities

- `_write_message` also writes notices and is called by join/leave. Hooking only
  `say` and `reply` silently omits part of [SRCH-3.3]'s kind contract.
- Delete removes the only raw source. Its invalidation therefore must carry the
  exact thread and message ID, while the provider retains a newer deletion
  revision after removing live document mappings.
- Rename changes queue names, thread facets, sub-thread parents, memberships,
  and durable recovery markers. Search work is emitted only after canonical
  rename convergence; interrupted rename remains owned by [IAN-8].
- SimpleBroker move preserves the original job ID. It does not publish
  `claimed_at`; search-owned claim metadata supplies visibility timeout.
- Claim metadata and queue move cannot share one transaction. Missing metadata
  is immediately reclaimable, which admits a duplicate but not loss.
- A contentless SQLite posting may outlive its live metadata. Query joins and
  source hydration are load-bearing until rebuild compacts it.
- Backend lexical analysis is deliberately visible only through result choice.
  Core supplies safe UTF-8 chunks; SQLite `unicode61` and PostgreSQL `simple`
  are pinned, the ASCII floor is shared, and Unicode/lexeme-limit differences
  are provider-specific firing tests rather than parity failures.
- An old worker can finish after a timed-out retry or a later deletion. Revision
  comparison plus deletion tombstones, not timing assumptions, prevents
  resurrection.
- An in-place reconciliation allocates its revision before reading source state.
  This makes it newer than old workers and older than later source mutations;
  using the message ID as its revision is forbidden.
- A detached process must open fresh handles. Forking an initialized client or
  inheriting broker handles violates SimpleBroker process ownership.
- Latest-ID reconciliation catches an ordinary append or latest deletion only
  while it changes the watermark. A later append can overtake a missed enqueue
  or foreign mutation. Rotation and explicit rebuild remain necessary for
  eventual completeness.
- PostgreSQL provider discovery is a new installed-extension seam. A broken or
  old `taut-pg` must disable search with a useful diagnostic, not make the whole
  client unusable.
- Concurrent PG provider initialization uses a fixed search-schema transaction
  advisory lock as its first statement; additive DDL alone is not convergence.

Fatal to the source operation: only its pre-existing validation, state, broker,
and cursor rules. Best-effort after source success: search enqueue and process
launch. Fatal to a search call: invalid invocation, unavailable/incompatible
provider, source visibility uncertainty that cannot be repaired, or provider
corruption. Isolated and continuing: malformed work items moved to the failed
queue and stale candidates omitted after hydration.

## 8. Rollout, Rollback, and One-Way Doors

### Rollout order

1. Review and promote the spec before any code cites `[SRCH-*]`.
2. Land additive provider tables and the worker/query code while no producer
   emits jobs; exercise rebuild and direct worker tests first.
3. Add producer invalidations and detached-launch request only after rebuild,
   reconciliation, and crash recovery are green on SQLite and PostgreSQL.
4. Enable the detached-launch default only after the manual benchmark gate.
   If the data is poor, ship durable enqueue plus search-time/opportunistic
   draining first. This changes latency, not correctness or the public query
   contract.
5. Add README/public command claims only when the command and CLI-claim gate
   exist in the same slice.

### Rollback

- Disable detached launch first; pending jobs remain durable and search can
  drain them.
- Disable producer enqueue next; existing chat operations and source history
  remain valid, and explicit rebuild reconstructs search later.
- Revert command/provider code while leaving `taut.search_*` queues and
  `taut_search_*` tables inert. Older Taut versions already ignore unregistered
  queues and unknown Taut-owned additive tables.
- Do not drop search tables or queues during ordinary rollback. Cleanup is a
  separate destructive migration requiring its own plan and user authority.
- No raw body migration exists, so rollback does not need to reconcile a
  competing content authority.

The public CLI/API and provider entry-point version become compatibility
surfaces once released. The index itself is not a one-way door; it is
rebuildable. Physical table/queue removal and any future tokenizer change
without versioned rebuild are the identified one-way/destructive edges.

## 9. Dependency-Ordered Tasks

### 1. Review and promote the contract

- Files: this plan, the proposed spec draft, then
  `docs/specs/00-specs-index.md`, `docs/specs/02-taut-core.md`,
  `docs/specs/03-identity-addressing-notifications.md`, new
  `docs/specs/06-search.md`, `tests/test_docs_references.py`, and plan backlinks.
- Run an independent Claude plan review under the read-only call-agent posture;
  allow up to 15 minutes as directed by the user. Record every finding and
  disposition in section 13.
- Apply the accepted draft using promotion strategy A and record the promotion
  baseline identifier.
- Red proof: the docs-reference test must fail on the new required spec/code
  family before its grammar/fixture update, then pass after promotion.
- Stop if review changes scope, authority, query grammar, claim semantics,
  persistence boundaries, or PG ownership. Revise and re-review the delta.
- Done: active spec text and exact companion deltas exist in the spec tree;
  docs gates pass; no implementation links are claimed prematurely.

### 2. Establish red acceptance tests and canonical core values

- Files: new `tests/test_search.py`, `tests/test_cli_probes.py`,
  `tests/test_public_api.py`, `taut/client/_models.py`, new
  `taut/search/` package skeleton, and code docstrings citing promoted refs.
- Add failing tests for shared safe-query chunks, the portable ASCII floor,
  pinned backend Unicode examples, AND-across-segment semantics,
  filters, order, pagination, malformed-selector exit 1, well-formed selector
  miss exit 2, scope, fixed `SearchHit` fields, empty/error classes, and
  cursor/identity/chat no-side-effects.
- Add a provider protocol using canonical query/document/candidate values. Keep
  it internal and minimal; do not design a general third-party plugin SDK.
- Stop if the provider needs actor/member objects or renderer fields. Those
  indicate domain behavior leaked out of core.
- Done: failures prove the absent behavior through public API/CLI seams and the
  internal protocol expresses only physical-index work.

### 3. Implement projection and the SQLite provider

- Files: `taut/search/_projection.py`, `taut/search/_provider.py`,
  `taut/search/_sqlite.py`, focused SQLite tests, and any minimal schema-version
  constants owned by search.
- Implement shared safe-query chunks and bounded UTF-8 segmentation first.
  Implement contentless FTS5 with the pinned analyzer, generations,
  live segment metadata, facets, revision
  tombstones, conditional operations, token-wise message-ID intersection,
  watermarks, rebuild, and cleanup.
- Keep exact source text out of ordinary search tables. Add an inspection test
  that queries Taut-owned table columns and job bodies, not an assertion based
  only on Python objects.
- Probe the runtime FTS5 capability and pin the search-only diagnostic.
- Stop if correctness requires external-content triggers on SimpleBroker
  tables, a raised SQLite runtime floor, raw text storage, or private broker
  SQL. Return to spec review.
- Done: targeted real-SQLite provider tests pass, including 10 MB/high-token
  segmentation boundaries, logical deletion with stale postings, generation
  rollback, and no raw body copy.

### 4. Implement durable jobs, claims, and core worker

- Files: `taut/search/_jobs.py`, `taut/search/_worker.py`, a private worker
  module entry point, provider claim methods, and real queue/subprocess tests.
- Implement exact JSON validation, pending/claimed/failed queues, atomic move,
  claim metadata, 60-second expiration using the Taut timestamp domain,
  exact acknowledgement after provider commit, revision ordering, stale-claim
  cleanup, and failed-job isolation.
- Use one plain core processing function from direct tests, search-time drain,
  opportunistic hosts, and the process wrapper. Context wrappers own handles;
  the core processor owns no inherited client/process state.
- Red/green every crash-window row in [SRCH-9.3] with deterministic fault
  barriers. Include two real concurrent workers and a delayed old revision
  racing a newer delete.
- Stop if implementation adds a global worker lock, holds a broker transaction
  while indexing, reserves batches, uses fixed sleeps as proof, or lets a
  worker thread use handles created elsewhere.
- Done: no loss under each crash point; duplicates converge; poison jobs do not
  block following jobs; real child crash residue is recovered.

### 5. Implement search scope, hydration, and reconciliation

- Files: `taut/client/_searching.py`, `taut/client/__init__.py`, search runtime
  modules, and `tests/test_search.py`/`tests/test_shared_contract.py`.
- Implement actor-neutral channel scope, actor-accessible DM scope, explicit
  union selectors, stable author resolution, candidate hydration, post-hydrate
  token/filter validation, fill-to-limit behavior, work-frontier drain,
  incremental higher-watermark repair, lower-watermark exact deletion check,
  rotating full-thread reconciliation, first-use/version rebuild, and explicit
  reindex generation switch. Allocate each in-place scan revision before
  reading source state and prove it outranks an old worker but yields to a later
  mutation.
- Add a core state accessor for durable completed channel-rename mappings and
  resolve old source names transitively. Completed marker retention is
  load-bearing; prove both message/rename orderings and an A-to-B-to-C chain.
- Use existing DM validation and message decoder paths. Do not derive DM access
  from index metadata or call stateful `show_message()` for hydration.
- Stop if search needs to advance cursors, heal identity, create membership,
  or bypass incomplete-rename policy without an explicit promoted spec change.
- Done: public client tests prove result truth and byte-for-byte absence of
  unrelated chat/member/cursor mutations on real SQLite.

### 6. Add source invalidations and evaluate detached launch

- Files: `taut/client/_messaging.py`, `taut/client/_threads.py`,
  `_ClientBase` warning state if needed, worker launcher, tests, and a small
  reproducible benchmark script under `bin/` only if the measurement cannot be
  expressed by an existing harness.
- Add message/notice invalidation at `_write_message`, delete invalidation after
  exact physical delete, and rename invalidation after full rename convergence.
  Preserve every pre-existing success/cursor/notification ordering test.
- Implement a best-effort detached fresh-interpreter launch with closed or
  null standard streams and no inherited handles. Do not wait for completion.
- Benchmark launch disabled/enabled for SQLite and PG: source command
  distribution, burst child count, SQLite busy outcomes, PG connection peak,
  and commit-to-searchable latency. Record median/IQR and environment; do not
  add timing thresholds to CI.
- Decision gate: enable launch-on-every-write only when added source latency and
  resource amplification are acceptable. Otherwise retain durable enqueue and
  search-time/opportunistic workers, and revise [SRCH-9.1] if the accepted
  spec text overcommits.
- Stop if enqueue or launch failure changes a successful source return/exit,
  or if launcher cleanup introduces files outside the resolved target.
- Done: fault-injected source operations still succeed with warnings; selected
  launch policy has recorded evidence and no hidden service.

### 7. Add CLI, rendering, and public exports

- Files: new `taut/commands/search.py`, `_builtins.py`, `_rendering.py`,
  `taut/client/_models.py`, `taut/client/__init__.py`, `taut/__init__.py`,
  `tests/test_cli.py`, `tests/test_cli_claims.py`, and `tests/test_public_api.py`.
- Parse the exact [SRCH-5.1] grammar, including interspersed repeatable options
  and literal `--`. Delegate once to `TautClient.search()`.
- Render fixed NDJSON facets and terminal-safe hydrated excerpts. Pin fields
  exactly and human prose only by meaningful substrings.
- Add firing tests for every flag, kind, exit class, malformed bound, scope
  combination, global-option placement, quiet/human/JSON mode, hostile control
  text, broken pipe, and no traceback/partial output.
- Stop if the adapter parses provider syntax, computes facets, or changes root
  dispatch policy for unrelated commands.
- Done: public CLI/API/export suites and `bin/check-cli-claims` pass.

### 8. Implement the PostgreSQL provider in `taut-pg`

- Files: private modules under `extensions/taut_pg/taut_pg/`,
  `extensions/taut_pg/pyproject.toml`, `extensions/taut_pg/tests/`, and package
  README/installed-wheel tests as required by the new entry point.
- Register one versioned `taut.search_backends` provider. Implement search-owned
  PG DDL, `pg_catalog.simple` vector segments, GIN, conditional revision and
  claim operations, watermarks, generations, rebuild, and cleanup.
- Use only the core-supplied `Queue.sidecar()` accessor. Require the fixed
  `taut:search:schema` advisory lock as the first statement in every search
  schema-init transaction. Use ordinary transactional GIN creation, never
  `CREATE INDEX CONCURRENTLY`, inside that transaction.
- Do not add PostgreSQL branches to core or move query/scope/hydration into the
  extension.
- Use real Docker PostgreSQL for provider discovery, concurrent schema setup,
  all crash paths, full-size segmentation, generation rollback, and parity.
- Stop if the provider requires ambient text-search configuration, raw bodies,
  `ts_headline`, exposed rank, `CREATE EXTENSION`, an optional PostgreSQL server
  extension, a new dependency, or changes to general `TautState` SQL solely
  for PG search.
- Done: PG-only tests and the shared search contract pass through
  `bin/pytest-pg --fast`.

### 9. Close adversarial, operational, and documentation gates

- Files: README search examples/command table, `docs/implementation/04-taut-architecture.md`,
  `docs/implementation/02-repository-map.md`, implementation/spec mappings,
  plan execution/review/deviation logs, and any required acceptance fixtures.
- Apply hostile encoding/body, malformed JSON job, degenerate job, missing
  provider, unwritable/locked target, process malformed output, concurrent
  determinism, and self-application probes from the adversarial runbook.
- Record operational observations named in [SRCH-12.2], including queue depth,
  rebuild time/size, launch overhead, and PG connection peak.
- Add reciprocal code/spec/implementation links and rerun every traceability
  gate. Evaluate whether `skills/call-agent` or a runbook missed any search-plan
  review need; update only if the correction is reusable.
- Stop if a declared enumerable contract lacks a firing test, any docs example
  names an unsupported CLI path, or current behavior differs from the promoted
  spec without a deviation row.
- Done: all final commands in section 11 pass from current state, independent
  completed-work review is closed, and landing state is explicit.

## 10. Testing Plan and Anti-Mocking Rules

Red-green TDD is mandatory for every behavior slice. Docs promotion uses the
existing reproducible docs-reference failure as its red proof. The detached
launch benchmark is supplementary evidence, not a substitute for tests.

| Layer | Required proof | Primary home |
|-------|----------------|--------------|
| pure unit | tokenizer, segments, query validation, job decoding, revision ordering | `tests/test_search.py` |
| real SQLite integration | FTS schema/query, queues, claims, rebuild, hydration, deletion, rename, no-side-effects | `tests/test_search.py`, `tests/test_client.py` |
| public CLI/adversarial | grammar, exits, JSON facets, human escaping, broken inputs, no traceback | `tests/test_cli.py`, `tests/test_cli_probes.py` |
| shared backend | same API/safety/order/scope/freshness plus ASCII-floor IDs; pinned backend-specific Unicode results | `tests/test_shared_contract.py` |
| PG-only | entry point, DDL/GIN, `simple` config, concurrent schema, cleanup | `extensions/taut_pg/tests/` |
| real process | fresh handles, detached parent, crash residue, timeout recovery, bounded exit | `tests/test_search.py` helpers |
| docs/traceability | code family, backlinks, command claims, plan index | existing docs gates |

Must remain real in contract tests:

- SimpleBroker queues and atomic move/delete behavior
- SQLite FTS5 and PostgreSQL database/provider
- Taut sidecar registry, membership, rename markers, and DM metadata
- exact source hydration and canonical decoder
- at least one producer subprocess and one worker subprocess
- concurrency barriers and persisted revision/claim state

Limited mocking is allowed only for a launcher unit that verifies exact
`Popen` arguments, an injected clock/timestamp source in pure timeout logic,
and a fault seam that raises at a named crash boundary while all surrounding
storage remains real. Do not mock the broker/provider/source path and then
claim lifecycle or backend proof.

## 11. Verification Commands and Success Signals

### Per-slice commands

```bash
uv run --extra dev pytest tests/test_search.py
uv run --extra dev pytest tests/test_client.py -k 'search or delete_message or rename_channel'
uv run --extra dev pytest tests/test_cli.py tests/test_cli_probes.py -k search
uv run --extra dev pytest tests/test_public_api.py tests/test_architecture_boundaries.py
uv run ./bin/pytest-pg --fast
uv run bin/check-cli-claims
bin/check-plan-status-index
uv run bin/check-doc-paths
```

### Final repository gates

```bash
uv run --extra dev pytest
uv run --extra dev pytest extensions/taut_summon/tests
uv run --project extensions/taut_mcp --extra dev pytest extensions/taut_mcp/tests
uv run ./bin/pytest-pg --fast
uv run ruff check taut tests bin extensions/taut_pg/taut_pg extensions/taut_pg/tests extensions/taut_summon/taut_summon extensions/taut_summon/tests extensions/taut_mcp/taut_mcp extensions/taut_mcp/tests
uv run ruff format --check taut tests bin extensions/taut_pg/taut_pg extensions/taut_pg/tests extensions/taut_summon/taut_summon extensions/taut_summon/tests extensions/taut_mcp/taut_mcp extensions/taut_mcp/tests
uv run --extra dev mypy taut tests bin/release.py extensions/taut_pg/taut_pg extensions/taut_pg/tests --config-file pyproject.toml
uv run bin/check-cli-claims
bin/check-plan-status-index
uv run bin/check-doc-paths
uv run bin/coalesce-check
```

Success requires zero failing selected tests, zero lint/format/type errors,
zero stale CLI claims, a valid plan index, clean document paths, and no
unanswered independent-review finding. A status document is not evidence;
rerun results from the final state are.

Post-deploy/field signals are: bounded pending/claimed backlog, zero repeatedly
failed well-formed jobs, normal messages becoming searchable without source
command delay, stable PG connection count under burst, rebuild completion, and
no search-triggered activity/cursor changes. Any persistent claimed item older
than 60 seconds, increasing failed-queue depth, or search/provider traceback is
a rollout failure and triggers detached-launch disablement or feature rollback.

## 12. Out of Scope

- MCP, TUI, web, or notification search surfaces
- search ranking, fuzzy matching, semantic/vector search, phrase grammar,
  regular expressions, wildcards, saved queries, alerts, and aggregate facets
- indexing files, attachments, reaction pointers, member personas, topics, or
  notification payloads
- changing message envelopes to include thread or index metadata
- changing SimpleBroker private schema, adding triggers to its tables, or
  adding a new SimpleBroker visibility-timeout API in this work
- secure deletion, database vacuum policy, retention, bulk message deletion,
  and index-at-rest encryption
- a new daemon, service manager, config file/key, or runtime dependency
- cleanup of adjacent client/state modules or generalized plugin frameworks

## 13. Deviation Log

| Spec ref | Planned behavior | Actual behavior | Rationale | Spec proposal |
|----------|------------------|-----------------|-----------|---------------|
| [SRCH-2.3], [SRCH-3.1], [SRCH-4.2], [SRCH-6.1], [SRCH-11], [SRCH-12.2] | Exact ordered message-ID equality across SQLite/PG through fixed ASCII SHA-256 token carriers | Before runtime code, use safe UTF-8 query chunks plus pinned native analyzers; preserve API/safety/order parity and an exact ASCII result floor, while allowing documented Unicode and lexeme-limit result differences | User-directed 2026-08-06. Exact result equality made search an authoritative computation, hid useful built-in analysis behind opaque carriers, and was not required for Taut's API contract. Native lexical search remains deterministic per pinned backend and needs no optional PostgreSQL server extension. | Applied directly to active `docs/specs/06-search.md`; independent revision review required before runtime work resumes |
| [SRCH-9.1] rollout gate | Implement a detached worker launcher, benchmark both modes, then select the default | Retain durable enqueue plus search-time work for version 1; do not ship an unused detached-launch path | Search itself captures and drains a durable work frontier. Launch-on-every-write would add interpreter startup, SQLite lock pressure, and PostgreSQL connection bursts before field latency demonstrates a need. Omitting the dormant launcher is smaller and preserves the same queue/provider seams for later evaluation. | No spec change: [SRCH-9.1] says a producer may launch and makes enablement conditional on a future benchmark |

## 14. Independent Review Log and Dispositions

Review path: Claude, a different model family from the Codex plan author,
through `skills/call-agent/SKILL.md`. Use both `--tools "Read,Grep,Glob"` and
`--allowedTools "Read,Grep,Glob"`, plan permission mode, no implementation,
and a 15-minute timeout. The review receives the baseline SHA, this full plan,
the full proposed spec draft, current governing specs, implementation notes,
and relevant code.

Gate questions:

1. Could the reviewer implement the plan confidently and correctly as written?
2. Would implementation materially impair Taut's simplicity, correctness,
   privacy boundary, storage model, or no-daemon character?

The reviewer must attack errors, latent ambiguity, unnecessary machinery, and
places where removal is better than addition. A `BLOCKED` verdict must trace to
one of the two gate questions. Every finding is reproduced before action and
receives one disposition: accepted and fixed, rejected with evidence, or out
of scope with rationale.

| Round | Finding | Reproduction/evidence | Disposition | Result |
|-------|---------|-----------------------|-------------|--------|
| 1 | F1 (P1): raw backend tokenizers cannot guarantee the required Unicode parity | FTS5 `unicode61` and PostgreSQL `simple` do not partition or fold all Python `casefold()`/`isalnum()` tokens identically; hydration can remove over-return but cannot repair a provider false negative | accepted and fixed: [SRCH-3.1] now hashes each distinct canonical token to one 65-character ASCII carrier; [SRCH-6.1], [SRCH-11], and tests require byte-for-byte carrier lookup, a pinned FTS tokenizer, Unicode parity, and collision filtering | re-review required |
| 1 | F2 (P2): scan-driven upserts had no revision contract | [SRCH-9.3] ordered job revisions, but an in-place watermark or rotation scan could otherwise use a message ID or late revision and let an old worker overwrite it or let a stale scan overwrite a later mutation | accepted and fixed: [SRCH-10.1] allocates one fresh scan revision before reading source state; all scan upserts/tombstones use it, with explicit old-worker/new-mutation firing tests | re-review required |
| 1 | F3 (P2): malformed selector exit contradicted [TAUT-8.1] and [IAN-5.3] | the draft placed malformed selectors in exit 2 although governing syntax validation is exit 1 | accepted and fixed: [SRCH-4.1], [SRCH-5.1], [SRCH-12.2], [SRCH-D3], and the test task separate malformed syntax (1) from a well-formed miss (2) | re-review required |
| 1 | F4 (P2): provider storage-handle ownership was undefined | without an explicit seam, a provider could open a second SQLite/PG connection and bypass [TAUT-3.1]/[TAUT-3.4] sidecar transaction and retry discipline | accepted and fixed: [SRCH-7], plan invariant 6, the PG task, and [SRCH-D7] require a core-constructed queue, supplied `Queue.sidecar()` accessor, no independent connection, and only `taut_search_*` SQL | re-review required |
| 1 | F5 (P2): concurrent PG search-schema setup named a test but no convergence mechanism | multiple first-use workers can race additive DDL; `IF NOT EXISTS` alone does not meet [TAUT-12.1]'s initializer rule | accepted and fixed: [SRCH-11.2], [SRCH-12.2], plan hidden couplings/PG task, and [SRCH-D7] require the fixed `taut:search:schema` transaction advisory lock as the first init statement | re-review required |
| 2 | focused review of F1-F5 fixes and defects introduced by them | Claude verified the SimpleBroker `sidecar`, timestamp, exact peek, and move contracts; governing exit/storage deltas; PG advisory-lock SQL; and one-lexeme ASCII carrier behavior | passed with no blocking finding; all round-1 dispositions closed | PASS |
| 3 | scoped review of the backend-native analyzer deviation and pre-runtime contract clarifications | Claude verified current SimpleBroker seams, applied companion deltas, body-digest hydration, pinned analyzers, provider descriptor, lease acknowledgement, and dual-write rebuild; it found five non-blocking precision gaps | accepted: name the completed-marker accessor/retention, use the exact chunk diagnostic, resolve rename chains transitively, allow duplicate quarantine envelopes, and distinguish detached failed-queue observation from local warnings | no blocker |
| 4 | completed-work read-only review with explicit `--model opus` | Opus cross-checked the active spec, core/SQLite/PG providers, durable jobs, claims, reconciliation, hydration, CLI/API, and real tests; verdict PASS with no P0/P1. It found one P2 missing firing test and four P3 observations | P2 accepted and fixed with `test_search_reconciles_two_rename_jobs_committed_newest_first`. Detached launch is already recorded as deferred. SQLite cross-process query/switch false-negative tolerance, completed-marker name reuse, and common-term SQLite query memory remain explicit non-corrupting residuals | PASS; final affected gates rerun |

Round-1 observations were non-blocking. O1 is retained as the existing rollout
gate: detached launch starts disabled unless its benchmark supports enabling it.
O2 is deferred because a progress protocol would add a separate Python/CLI
callback contract; first-use cost remains explicit. O3 is accepted as the new
internal-queue name and route-exclusion probe in [SRCH-12.2]. O4 is accepted:
[SRCH-10.1] now distinguishes incremental higher-watermark work, exact
lower-watermark deletion checking, and full scanning for an absent watermark.

Round-2 observations were also non-blocking and are closed in the draft: PG
GIN initialization explicitly forbids `CONCURRENTLY` inside the advisory-lock
transaction; [SRCH-4.2] states the pending-row hydration dependency; and
[SRCH-12.2] now requires the portable ASCII floor plus pinned backend-specific
Unicode and lexeme-limit outcomes.

A second independent completed-work review is required after all code and docs
gates pass. Round 2 after a revision is scoped only to accepted finding IDs and
new defects introduced by their fixes.

## 15. Fresh-Eyes and Stop Conditions

Before promotion and again before implementation completion, re-read as a
zero-context engineer and verify exact files, owners, failure priorities,
anti-mocking rules, rollback, provider boundary, and completion commands.

Stop and re-plan when any of these appears:

- raw message text is needed outside canonical history
- a source operation must wait for tokenization, indexing, reconciliation, or
  a worker exit
- a new dependency, service, config key, private broker API, or core PG branch
  appears
- a timeout overlap can resurrect older state despite revision checks
- DM visibility depends on index metadata
- an accepted body can poison or stall indexing instead of applying the
  documented backend lexeme-limit omission
- detached launch has unacceptable measured source latency, process count,
  busy errors, or PG connections
- normal search cannot state its foreign-write false-negative bound clearly
- a behavior differs from the promoted spec without a deviation entry and
  explicit spec-revision slice

The plan is not implementation-ready while any section-14 disposition remains
pending or the promotion baseline is absent.
