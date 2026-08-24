# Concurrency and Schema Contract Alignment Plan

Class: 5. This plan revises normative persistence, search, and core-schema
contracts. Hardening is required because the work touches public compatibility
and destructive-load boundaries.

Plan type: implementation with spec revision.

Promotion strategy: A. Promote the reviewed in-file spec text before tests,
diagnostics, or implementation notes rely on it. The promoted text adds no
implementation-link claims, so no temporary reciprocal-link debt is created.

## Goal

Resolve the four concurrency and schema-evolution review findings without
adopting fixes that contradict Taut's program theory or existing behavior.
Make the live logical-dump boundary, SQLite search-rotation residual, and
quiescent-load input boundary unambiguous; add deterministic characterization
tests for the two claimed races; and make the owner-selected SimpleBroker-style
ordered `ensure_schema` migration ladder binding before the next breaking core
schema version. Preserve schema 1 to schema 2 as an explicit historical cutoff
unless a separate compatibility decision adds that missing rung.

This plan does not claim that C1, C2, or C3 is a current correctness defect. It
turns the accepted behavior and reconsideration conditions into agent-usable
contracts so the rejected fixes are not proposed again from the same premises.

## Source Documents

Source specs:

- `docs/specs/02-taut-core.md` [TAUT-3.3], [TAUT-12.1]
- `docs/specs/06-search.md` [SRCH-3.2], [SRCH-10.3], [SRCH-11.1]
- `docs/specs/08-persistence-io.md` [PIO-2.3], [PIO-2.4], [PIO-7.4],
  [PIO-8.2], [PIO-9]
- `docs/program-theory.md` A2 and A6

Historical decisions and implementation context:

- `docs/plans/2026-08-12-live-point-in-time-dump-plan.md`
- `docs/plans/2026-08-07-taut-dump-load-plan.md`
- `docs/plans/2026-08-06-taut-search-plan.md`
- `docs/plans/2026-06-18-member-identity-addressing-plan.md`
- `docs/implementation/04-taut-architecture.md`
- `docs/implementation/09-search-architecture.md`
- `docs/implementation/10-persistence-io.md`
- SimpleBroker's named, ordered migration-rung precedent:
  `/Users/van/Developer/simplebroker/simplebroker/_backends/sqlite/schema.py`

## Spec Baseline

- `0eacc00adf33c0ab8feef46d35b7909c33f8c40e`:
  `docs/specs/02-taut-core.md`, `docs/specs/06-search.md`, and
  `docs/specs/08-persistence-io.md` at plan authoring time.
- Authoring overlay: `docs/specs/06-search.md` and
  `docs/specs/08-persistence-io.md` match that commit. The exact current-tree
  diff for `docs/specs/02-taut-core.md` has SHA-256
  `8e81c418d106285174731c2c7d8acc5f0299b3aa3c5f6c4149604baddb8a0bc6`
  and only raises the documented floors from SimpleBroker 7.3.2 to 7.4.1 and
  SimpleBroker-PG 3.8.0 to 3.9.1, including the 7.4.1 ownership rationale. It
  does not touch [TAUT-3.3]. Before promotion, reproduce this three-file diff
  hash. If it differs, inspect the new delta and revise this baseline before
  applying spec text; do not mix an unreviewed overlay into promotion.
- Promotion baseline: `0eacc00adf33c0ab8feef46d35b7909c33f8c40e` plus
  current-tree diff SHA-256
  `9a4ded829374606f352f60380d2315ed4cfa250bfd691a76a1b747c28980683e`
  for `docs/specs/02-taut-core.md`, `docs/specs/06-search.md`, and
  `docs/specs/08-persistence-io.md`. This includes the reviewed spec delta and
  the separately pinned dependency-floor overlay above.

## Current Structure and Key Files

### Files to modify during implementation

- `docs/specs/02-taut-core.md`
  - [TAUT-3.3] owns the core schema-version and migration policy.
  - Add this plan under `## Related Plans` during spec promotion.
- `docs/specs/06-search.md`
  - [SRCH-11.1] owns SQLite FTS5 and generation-switch behavior.
  - [SRCH-3.2] already requires matching across physical segments.
  - Add this plan under `## Related Plans` during spec promotion.
- `docs/specs/08-persistence-io.md`
  - [PIO-2.4] and [PIO-8.2] own live logical-projection consistency.
  - [PIO-7.4] owns undefined outcomes under overlapping filesystem mutation.
  - Add this plan under `## Related Plans` during spec promotion.
- `taut/state/_sql.py`
  - `ensure_schema()` currently acquires the Taut schema advisory lock inside
    one `Queue.sidecar(transaction=True)` scope, initializes fresh targets at
    `SCHEMA_VERSION`, refuses newer versions, and emits a development-database
    recreation message for every older version.
  - Change only the unsupported-old-version diagnostic in this plan. Do not
    add an empty migration dispatcher or change `SCHEMA_VERSION`.
- `tests/test_state_contract.py`
  - Add backend-shared proof that the schema-1 historical cutoff fails without
    mutating the stored version and names a usable recovery boundary.
- `tests/test_persistence_io_adversarial.py`
  - Add real-SQLite, scheduler-controlled dump probes at the boundary between
    the thread and membership scans.
- `tests/test_search.py`
  - Add a real-SQLite generation-switch query probe. Preserve the existing
    `test_sqlite_provider_requires_chunks_across_physical_segments` as the
    firing guard against the proposed one-row `MATCH` rewrite.
- `docs/implementation/04-taut-architecture.md`
  - Explain the future ordered core-migration ladder, the retained Taut
    transaction/advisory-lock boundary, and the explicit schema-1 cutoff.
- `docs/implementation/09-search-architecture.md`
  - Explain why transactional drop/recreate produces a documented transient
    omission rather than a missing-table window, and why intersection stays
    across message IDs instead of one FTS row.
- `docs/implementation/10-persistence-io.md`
  - Explain the multi-statement logical projection and stable-input
    precondition without implying validation-time byte retention.
- `docs/plans/README.md`
  - Keep this plan's lifecycle row current.

### Existing production seams that must be reused

- `taut/state/_sql.py::persistence_records()` is the one core logical dump
  projection used by dump and passive doctor inspection. It opens a default
  sidecar and reads members, aliases, claims, threads, memberships, and rename
  markers in deterministic order.
- `taut/persistence/_format.py::_CoreValidator.finish()` is the final authority
  for missing member/thread references and other illegal composites. Tests
  must reach it through `TautClient.dump()`; do not call only the validator.
- `taut/search/_sqlite.py::SQLiteSearchProvider.query()` reads current
  generation metadata, then performs one safe quoted `MATCH` per chunk and
  intersects candidates by message ID in Python.
- `taut/search/_sqlite.py::SQLiteSearchProvider.finish_rebuild()` switches
  metadata and clears the now-inactive slot in one transactional sidecar.
- `taut/state/_sql.py::ensure_schema()` owns fresh initialization, version
  refusal, current-version DDL reconciliation, and the Taut advisory lock. A
  future ladder belongs inside this owner; it must not be delegated to CLI or
  client construction.

### Required-reading comprehension gate

Before editing, the implementer records answers to these questions in the
Execution Log. A wrong answer blocks implementation until the cited source is
reread.

1. **What does a successful live dump promise when core rows are read by
   multiple statements?**
   - Expected answer: a validated, importable logical projection. Racing
     mutations may appear in this dump or a later one. It does not promise one
     MVCC snapshot, and an illegal final composite fails before publication.
2. **Why can SQLite rotation omit matching candidates, including returning an
   empty candidate page, without exposing `no such table`?**
   - Expected answer: generation publication, inactive-slot deletion, `DROP`,
     and `CREATE` commit as one writer transaction. A reader can mix committed
     snapshots across its metadata/chunk statements, but cannot observe the
     writer's intermediate DDL state.
3. **Why is one combined FTS `MATCH` expression not equivalent?**
   - Expected answer: physical segments are separate FTS rows; [SRCH-3.2]
     requires terms in different rows of the same message to match.
4. **Which source-dump mutation does load currently defend against?**
   - Expected answer: none once concurrent filesystem mutation begins. Digests
     validate bytes while read, while [PIO-7.4] and A6 require the operator to
     keep the source stable. Extension and broker spans may be reopened.
5. **What is borrowed from SimpleBroker's schema ladder, and what remains
   Taut-specific?**
   - Expected answer: Taut borrows named, ordered, one-version rungs and
     version-after-rung progression. Taut strengthens that precedent by
     requiring an explicit postcondition for every rung, and retains its
     existing single `sidecar(transaction=True)` scope and schema advisory
     lock, portable dialect boundary, and supported-version policy.

## Invariants and Constraints

1. **No point-in-time dump claim.** The change must not promise one transaction
   or one physical instant within core, within an extension, or across broker,
   core, and extensions.
2. **No new dump lock.** Do not change `persistence_records()` to
   `transaction=True`, add a write reservation, retry until stable, or split
   doctor onto new production behavior under this plan.
3. **Validation remains fatal.** A racing mutation that yields a dangling or
   otherwise illegal final composite must still fail before output
   publication. Documentation must not describe every race as acceptable.
4. **Search remains cross-segment.** Keep one safe chunk query at a time or an
   exactly equivalent message-ID intersection. Do not collapse chunks into one
   row-scoped FTS expression.
5. **No stale-positive relaxation.** The accepted SQLite residual is transient
   omission during a cross-process generation switch. It does not permit
   bypassing generation/slot filters, hydration authorization, or source
   validation.
6. **Load remains destructive by contract.** Do not add input snapshots,
   retained descriptors, replay hashing, temp-file cleanup, or authenticity
   claims. Those require a new product decision, temp-artifact lifecycle, and
   separate hardened plan.
7. **Schema 1 remains an explicit historical cutoff.** This plan does not
   invent a `1 -> 2` transformation or imply that current Taut can export a
   schema-1 workspace. A separate owner decision and authentic schema-1 fixture
   are required to change that boundary.
8. **Future core migrations are sequential.** A supported stored version may
   advance only through adjacent, named rungs in ascending order. Missing rungs
   fail closed; versions may not be skipped.
9. **Taut coordination remains load-bearing.** Future rungs run inside the
   existing Taut transaction and advisory lock. A rung verifies its target
   shape before updating `schema_version`; any later failure rolls the whole
   `ensure_schema()` attempt back to the original durable version and shape.
10. **Fresh initialization remains direct.** A new target installs the current
    schema and current version without replaying historical rungs.
11. **Both backends remain authoritative.** Any future rung must use portable
    qmark SQL through the supplied sidecar/dialect seam, or explicitly plan and
    test a justified backend split. SQLite-only proof is insufficient.
12. **No speculative migration framework.** Do not add a dispatcher with zero
    executable rungs. The first future breaking schema plan adds the ladder and
    its first real rung together against an authentic old-version fixture.
13. **No unrelated cleanup or dependencies.** Preserve current file ownership,
    dependency floors, public APIs, dump format versions, search projection
    versions, and schema versions.
14. **The current-version tail still runs.** After migration reaches the
    current version, `ensure_schema()` runs the current idempotent DDL
    reconciliation and load-guard check before returning, inside the same
    transaction and rollback boundary. Migration must not bypass either tail.

## Failure Priorities

- A dangling dump composite, digest failure on stable input, unsupported schema
  version, failed migration postcondition, or failed migration transaction is
  fatal.
- A SQLite query racing generation publication may return a transient empty or
  omitted page. It must not raise because it observed the writer's intermediate
  table drop.
- Source dump mutation overlapping load remains outside the guarantee. Do not
  add deterministic outcome assertions for that undefined case.
- Documentation or test evidence that contradicts actual SQLite or PostgreSQL
  behavior is a plan blocker, not a reason to weaken the assertion.

## Hidden Couplings

- `doctor_persistence_records()` reuses `persistence_records()`. A seemingly
  local dump transaction change would also make passive doctor inspection take
  SQLite's write reservation.
- SimpleBroker's SQLite `transaction=True` begins `IMMEDIATE`, while its
  PostgreSQL runner uses plain `BEGIN`; the same call does not create the same
  repeatable-read guarantee across backends.
- `_clamp_core_cursors()` couples copied membership cursors to broker high-water
  H. It does not repair multi-statement core projection consistency and must
  not be rewritten under C1.
- SQLite FTS postings are per physical segment row. Query results become
  message-level only after joining segment metadata and intersecting message
  IDs across chunks.
- Core `ensure_schema()` is reached by ordinary initialization and by
  load-target preparation. A future migration must preserve the load-guard
  check and current-schema DDL reconciliation after migration.
- PostgreSQL's Taut schema advisory lock is transaction-scoped. Splitting
  future rungs into separately committed transactions would release the lock
  between rungs and needs a different coordination design.

## Rollback, Rollout, and One-Way Doors

The planned current work changes specifications, implementation notes,
characterization tests, and one diagnostic. It performs no schema migration
and has no data one-way door. Roll it back as one unit by reverting the promoted
text, tests, notes, and diagnostic; stored workspaces are untouched.

Promote the specs first, then land tests, diagnostic, and implementation notes
against that promotion baseline. The diagnostic remains a refusal and is safe
to roll back independently, but keeping it aligned with the schema-1 text is
preferred.

A future schema rung is a one-way data transition even when transactionally
safe. The future breaking-schema plan must repeat hardening, carry an authentic
source-version fixture, state upgrade and downgrade release order, prove
rollback before commit, and identify post-release signals. This plan does not
authorize that migration or a `SCHEMA_VERSION` bump.

## Proposed Spec Delta

Promotion strategy:

| Spec file | Strategy | Sections touched |
|-----------|----------|------------------|
| `docs/specs/02-taut-core.md` | A: in-file text before dependent work | [TAUT-3.3] |
| `docs/specs/06-search.md` | A: in-file text before dependent work | [SRCH-11.1] |
| `docs/specs/08-persistence-io.md` | A: in-file text before dependent work | [PIO-2.4], [PIO-7.4], [PIO-8.2] |

### [TAUT-3.3]: replace the schema-evolution paragraph

> Schema evolution is additive within the current schema generation when
> possible (new tables, new nullable columns). Breaking changes bump
> `schema_version` and use an ordered `ensure_schema` migration ladder: one
> named rung advances exactly one version, and every supported older version
> reaches the current version only by applying each adjacent rung in ascending
> order. A breaking version bump is incomplete unless the same change supplies
> the new rung, an authentic source-version fixture, and backend-shared firing
> tests.
>
> Core reads and migrates the stored version inside the existing
> `Queue.sidecar(transaction=True)` and Taut schema-advisory-lock boundary.
> Each rung inspects the actual source shape, applies only its owned
> transformation, verifies the target postcondition, and only then updates
> `schema_version`. A missing rung, failed postcondition, or later rung failure
> is fatal and leaves the durable schema and version at their pre-attempt
> state. Fresh targets install the current schema directly rather than replaying
> historical rungs. Older Taut versions encountering a newer version refuse
> with a clear upgrade error rather than guess; unsupported historical source
> versions likewise refuse without mutation and name the stored version,
> current version, and recovery boundary.
>
> The development-stage schema 1 to schema 2 cutover remains an explicit
> unsupported historical boundary. It gains a `1 -> 2` rung only through a
> separate compatibility plan with an authentic schema-1 fixture; the existence
> of the future ladder does not infer that transformation.
>
> After a fresh initialization or migration reaches the current version,
> `ensure_schema` runs the current idempotent DDL reconciliation and enforces
> the core load guard before returning. These steps remain inside the same
> transaction and rollback boundary; migration cannot bypass them.

### [SRCH-11.1]: insert after the first SQLite provider paragraph

> SQLite generation publication and clearing of the now-inactive physical FTS
> slot remain one writer transaction. A query racing that commit may read
> generation metadata and per-chunk match sets from different committed
> snapshots and may therefore omit matching candidates, including returning an
> empty candidate page for that call; retry is the recovery. The race must not
> expose the writer transaction's intermediate `DROP TABLE` as a
> user-visible missing-table failure. Query evaluation must preserve
> message-ID intersection across physical segment rows under [SRCH-3.2];
> combining all chunks into one row-scoped FTS `MATCH` expression is not
> behavior-equivalent.

### [PIO-2.4]: append to the live-dump contract

> A core or extension contributor may assemble its projection from multiple
> reads that do not share one MVCC snapshot. “Coherent” and “individually
> consistent” mean that the published component and final composite satisfy
> their logical validators and are importable; they do not mean that every
> emitted row coexisted at one database instant. A row committed after the read
> that owns it may appear only in a later dump. A race that leaves a dangling
> reference, incomplete transition, or otherwise illegal composite remains
> fatal before publication.

### [PIO-7.4]: insert after the overlapping-mutation paragraph

> Filesystem mutation includes replacement, in-place writing, truncation, or
> deletion of the named input dump after validation begins. Component digests
> assume the source bytes remain stable for the operation; load is not required
> to retain one descriptor, rehash component spans during replay, or copy the
> dump into a private snapshot. A future requirement to apply exactly the bytes
> observed during validation despite concurrent source mutation changes the A6
> destructive-operation contract and requires a separate specification and
> temp-artifact lifecycle design.

### [PIO-8.2]: append to the contributor projection paragraph

> “Individually consistent” has [PIO-2.4]'s logical meaning. It does not require
> the contributor to hold one SQL transaction across every projection read.

## Tasks

### 1. Promote the reviewed contract text

- Files: `docs/specs/02-taut-core.md`, `docs/specs/06-search.md`,
  `docs/specs/08-persistence-io.md`, this plan.
- Apply the exact Proposed Spec Delta using strategy A.
- Add this plan to each touched spec's `## Related Plans` section without
  adding implementation claims.
- Record the promotion baseline identifier in this plan.
- Recompute the Spec Baseline's three-file diff hash before editing. A mismatch
  blocks promotion until the intervening spec delta is reviewed and recorded.
- Run `uv run --locked bin/check-doc-paths` immediately.
- Stop and re-review if promotion requires changing A2, A6, dump format,
  search match semantics, or the schema-1 support decision.
- Done signal: the active specs contain the reviewed text, related-plan links
  resolve, and the promotion baseline is recorded.

### 2. Characterize the live core projection boundary with real SQLite

- Files: `tests/test_persistence_io_adversarial.py`.
- Add a test that creates an existing member and existing thread before dump,
  then uses a scheduler-only monkeypatch around `taut.state._sql._all` to commit
  that member's new membership immediately after the thread query returns and
  before the membership query begins.
- Recognize that boundary by normalizing whitespace in the SQL string and
  matching both `FROM taut_threads` and `ORDER BY name`. Call the real `_all`
  first, set a one-shot guard before invoking the writer to prevent recursive
  hooks, then perform the membership write and return the real rows.
- Reach the production path through `TautClient.dump()` and
  `TautClient.load()`. Assert that the late membership is emitted and restored.
- Add the adjacent new-thread case: create a new thread and membership at the
  same boundary, then assert final validation refuses publication because the
  thread was not in the earlier thread projection. Seed the named output with
  `b"previous complete backup\n"` and assert [PIO-6.2]'s failure-before-replace
  guarantee leaves those exact bytes unchanged and removes staging files.
- Keep real Queue, sidecar, formatter, validator, filesystem, and load paths.
  The monkeypatch may control only the exact interleaving; it must not fabricate
  rows or replace validation.
- These are characterization-only proofs for unchanged runtime behavior, so
  testing-patterns rule 5's behavior-change red-green rule is not applicable.
  Record that classification in the execution log; production code must not
  change to make these tests pass.
- Stop if the existing-member case is omitted, the illegal new-thread case is
  published, or the test requires changing production code to expose a hook.
- Done signal: both deterministic cases pass repeatedly with `-n 0` and prove
  the two distinct logical outcomes.

### 3. Characterize SQLite query/rotation behavior without weakening matching

- Files: `tests/test_search.py`.
- Use two real `Queue`/`SQLiteSearchProvider` instances against one SQLite
  target. Build a current generation and a ready staging generation containing
  a cross-segment two-chunk document.
- Use two bounded `threading.Event` objects, `metadata_read` and
  `release_query`, plus a scheduler-only monkeypatch of
  `SQLiteSearchProvider._state` that delegates to the original and pauses only
  the query thread after it has read the old generation. The hook sets
  `metadata_read`, then waits with a bounded assertion for `release_query`.
  The coordinator waits boundedly for `metadata_read`, completes
  `finish_rebuild()` synchronously through the second provider, and only then
  sets `release_query`. A `finally` block always sets `release_query`; the query
  future or thread join is bounded so a failure cannot hang pytest.
- Arm the hook only after fixture setup. Install it as
  `staticmethod(observed_state)` so descriptor behavior does not change. Count
  query-thread calls and assert exactly one coordinated `_state` call fired;
  writer-thread `_state` calls delegate without waiting.
- Seed exactly one two-chunk matching document and one one-chunk nonmatch.
  Before arming the scheduler hook, assert the stable current-generation query
  returns exactly `[matching_candidate]`; an empty baseline blocks the race test
  as a vacuous fixture.
  Assert the query completes without `OperationalError` and its result is
  exactly either `[]` or `[matching_candidate]`; every other list fails.
- Retain and run
  `test_sqlite_provider_requires_chunks_across_physical_segments`; do not
  rewrite it around one-row matching.
- Keep SQLite, FTS5, both sidecar transactions, DDL, and query SQL real. Mock
  only scheduler timing.
- Run this root SQLite test on every supported OS/Python CI lane. Do not
  hardcode a host SQLite version into the product contract; a supported lane
  reproducing `no such table` triggers the stop gate below.
- This is a characterization-only proof for unchanged runtime behavior, so the
  behavior-change red-green rule is not applicable.
- Stop if SQLite can expose `no such table`, if the test can pass without both
  handshake events firing in order, or if reliable scheduling requires a
  production-only hook.
  A reproduced crash is a new correctness finding and requires replanning.
- Done signal: the coordinated test proves completion without a table-missing
  error, and the cross-segment contract test remains green.

### 4. Align the historical schema diagnostic and future ladder guidance

- Files: `taut/state/_sql.py`, `tests/test_state_contract.py`,
  `docs/implementation/04-taut-architecture.md`.
- Replace the generic “recreate the development database” error with this exact
  interpolated diagnostic: `taut schema version {version} has no supported
  migration path to version {SCHEMA_VERSION}; use a taut release that supports
  schema version {version}, or recreate a fresh target`. Do not claim that
  schema 1 supports full-workspace export.
- Add a backend-shared test that initializes a real current schema, changes
  only its version marker to schema 1 as a labeled white-box gate, calls the
  public state `ensure_schema()`, and proves refusal leaves the marker and
  exact core sentinel unchanged. The sentinel is one member, one channel
  thread, and that member's membership, with their ids, names, timestamps, and
  cursor captured before the marker change and compared by direct read after
  refusal. This test protects the current cutoff and diagnostic; it is not an
  authentic schema-1 migration fixture.
- Add a second backend-shared case with the same exact sentinel and a stored
  marker of `SCHEMA_VERSION + 1`. Assert the existing exact newer-version
  diagnostic, `taut schema version {version} is newer than supported version
  {SCHEMA_VERSION}; upgrade taut`, and prove the marker and sentinel remain
  unchanged. This is the firing test for [TAUT-3.3]'s newer-version refusal.
- Document the future ladder shape in the architecture note: adjacent named
  rungs, actual-shape inspection, postcondition before version update, all
  rungs inside Taut's existing transaction/advisory lock, direct fresh
  initialization, backend-shared proof, and the current-version DDL
  reconciliation plus load-guard tail before return.
- Do not add an empty migration registry, `1 -> 2` rung, schema bump, or fake
  multi-rung unit test. The first real breaking-schema plan owns those changes.
- Stop if the diagnostic cannot be changed without affecting newer-version
  refusal or load-guard handling, or if an authentic schema-1 preservation
  requirement emerges.
- Done signal: SQLite and PostgreSQL shared tests prove both exact refusal and
  non-mutation cases; the architecture note gives a zero-context engineer the
  future ladder boundary without pretending it already exists.

### 5. Reconcile durable implementation explanations

- Files: `docs/implementation/09-search-architecture.md`,
  `docs/implementation/10-persistence-io.md`, and the mapping row in
  `docs/implementation/04-taut-architecture.md` if its test inventory changes.
- Persistence note: state that core projection can be multi-statement and that
  logical consistency is validator/import consistency. State that source dump
  stability is an operator precondition and that no private input snapshot is
  retained.
- Search note: retain the known transient-omission paragraph; add the
  transactional DDL visibility reason and the cross-segment reason the proposed
  combined `MATCH` is invalid.
- Architecture mapping: include the new shared schema-cutoff test and the
  future ladder ownership under [TAUT-3.3].
- Do not duplicate normative prose verbatim. Explain why, ownership, and
  reconsideration conditions; link back to the specs.
- Done signal: each rejected finding can be resolved from durable docs without
  reading the historical review conversation.

### 6. Reconcile traceability and close implementation evidence

- Files: the three specs, three implementation notes, this plan,
  `docs/plans/README.md`.
- Confirm every proposed delta is present exactly or record a closed deviation.
- Confirm the Related Plans links and architecture mapping are accurate.
- Run all final gates below from the current tree.
- Obtain an independent completed-work review after implementation. Plan review
  does not substitute for completed-work review.
- Update the status-index row to `completed` only after the owner authorizes
  closeout and the completion commit exists. Do not commit on the owner's
  behalf merely to satisfy the lifecycle gate.
- Done signal: zero pending deviations, all gates pass, completed-work feedback
  is disposed, and lifecycle status states only what the evidence supports.

## Testing Plan

### Red/green posture

- Tasks 2 and 3 add characterization-only tests for behavior that already
  exists; the behavior-change red-green rule is not applicable. Their proof is
  deterministic scheduler control over real SQLite, FTS5, Queue, persistence
  format, and load paths, plus inspection that each scheduling handshake fired.
- Task 4 changes an observable diagnostic. Add the shared failing assertion
  for the new message before changing production text, then make it green.
- No test asserts an exact outcome for source-dump mutation during load because
  [PIO-7.4] deliberately leaves it undefined.
- No migration-ladder runtime test is due until there is a real rung. The
  future schema-bump plan must begin red with an authentic prior-version
  fixture, then prove one-rung, multi-rung when enumerable, postcondition
  failure, transaction rollback, concurrent initialization, and both backends.

### Anti-mocking rules

- Keep Queue, SQLite, FTS5, sidecar transaction boundaries, dump framing,
  validators, filesystem publication, and load application real.
- A monkeypatch may coordinate an exact statement boundary but may not return
  synthetic database rows, suppress exceptions, replace a validator, or alter
  transaction semantics.
- The schema diagnostic test uses a direct metadata write only to create an
  unsupported-version precondition. It must call production `ensure_schema()`
  and inspect real durable state afterward.
- PostgreSQL evidence runs through `bin/pytest-pg`; no fake dialect or mocked
  advisory-lock result substitutes.

### Targeted commands

```bash
uv run --locked --extra dev pytest -q -n 0 \
  tests/test_persistence_io_adversarial.py \
  -k 'membership and thread_projection'

uv run --locked --extra dev pytest -q -n 0 \
  tests/test_search.py \
  -k 'generation_switch or requires_chunks_across_physical_segments'

uv run --locked --extra dev pytest -q -n 0 \
  tests/test_state_contract.py -k 'schema_version or schema_1'

uv run --locked bin/pytest-pg --fast \
  tests/test_state_contract.py -k 'schema_version or schema_1'
```

The implementer may tighten the `-k` expressions to the final exact test names
after adding them, but must record those exact names in the execution log.

## Verification and Gates

### Per-slice gates

```bash
uv run --locked bin/check-doc-paths
bin/check-plan-status-index

uv run --locked --extra dev pytest -q -n 0 \
  tests/test_persistence_io.py \
  tests/test_persistence_io_adversarial.py \
  tests/test_search.py \
  tests/test_state_contract.py

uv run --locked ruff check \
  taut/state/_sql.py \
  tests/test_persistence_io_adversarial.py \
  tests/test_search.py \
  tests/test_state_contract.py

uv run --locked ruff format --check \
  taut/state/_sql.py \
  tests/test_persistence_io_adversarial.py \
  tests/test_search.py \
  tests/test_state_contract.py

uv run --locked --extra dev mypy \
  taut/state/_sql.py \
  tests/test_persistence_io_adversarial.py \
  tests/test_search.py \
  tests/test_state_contract.py \
  --config-file pyproject.toml
```

### Final gates

```bash
uv run --locked --extra dev pytest -q -n 0 \
  tests/test_persistence_io.py \
  tests/test_persistence_io_adversarial.py \
  tests/test_search.py \
  tests/test_state_contract.py

uv run --locked bin/pytest-pg --fast tests/test_state_contract.py

uv run --locked ruff check taut tests
uv run --locked ruff format --check taut tests
uv run --locked --extra dev mypy taut tests --config-file pyproject.toml

uv run --locked bin/check-doc-paths
bin/check-plan-status-index
```

Success means:

- the exact C1 interleaving includes an existing membership or fails an illegal
  new-thread composite, never silently publishing the claimed loss;
- the exact C2 rotation completes without a missing-table error while the
  cross-segment match test remains green;
- both unsupported schema-1 and newer-than-current refusals are explicit and
  non-mutating on SQLite and PostgreSQL;
- specs and implementation docs state the same boundaries;
- no current schema, dump format, search projection, public API, dependency, or
  unrelated test behavior changes.

Post-deploy observation for the current change is limited to the improved
unsupported-schema diagnostic. There is no runtime rollout for the clarified
dump, search, or load behavior. For the first future schema rung, release
acceptance must positively open an authentic prior-version fixture on SQLite
and PostgreSQL, preserve representative state, and report the current version;
absence of errors alone is insufficient.

## Independent Review Loop

Before spec promotion, a fresh reviewer from a different agent context reads:

- this entire plan, especially `## Proposed Spec Delta`;
- `docs/program-theory.md` A2 and A6;
- [TAUT-3.3], [SRCH-3.2], [SRCH-10.3], [SRCH-11.1], [PIO-2.4],
  [PIO-7.4], [PIO-8.2], and [PIO-9];
- the production functions and existing tests named in Current Structure;
- SimpleBroker's real ordered schema ladder.

Review prompt:

> Verify every named surface first. Then review the plan and exact spec delta
> for factual errors, contradictions with program theory, ambiguous ownership,
> weak or mock-heavy proof, and performative overengineering. Check especially
> that C1-C3 are documented as accepted boundaries rather than silently
> “fixed,” that the search test cannot pass without exercising the race, and
> that the future schema ladder is executable without pretending a `1 -> 2`
> rung exists. Could a zero-context engineer implement this confidently and
> correctly after promotion? Do not implement anything.

Every finding is appended to the Review Log with one disposition: applied,
rejected with evidence, or out of scope with a reconsideration condition. A
reviewer answer of “no” blocks spec promotion.

After implementation and all local gates, a separate completed-work reviewer
checks the diff against the promotion baseline, reruns or inspects the firing
tests, and verifies that no runtime consistency mechanism or speculative
migration framework entered through scope drift.

## Reader-Test Questions

A fresh zero-context reader should be able to answer these from the plan:

1. Does Taut promise that all core dump rows came from one database snapshot?
2. What happens for the exact membership race claimed in C1?
3. Why does SQLite search rotation permit omission but not an intermediate
   missing-table error?
4. Why is one combined FTS expression forbidden?
5. Does load promise to apply validation-time bytes if the input is rewritten?
6. Will current Taut migrate schema 1 to schema 2?
7. Where will the first real core migration rung live, and what must prove it?
8. Which proposed changes affect runtime behavior now?

Reader testing fails if the answers imply point-in-time dump, stable-byte load,
schema-1 preservation, or an already-implemented migration ladder.

## Out of Scope

- Point-in-time or repeatable-read dump semantics.
- `transaction=True` for core dump projection.
- A high-water/re-read-until-stable core projection protocol.
- Splitting passive doctor projection from dump projection.
- Rewriting SQLite search into one combined FTS expression.
- Eliminating the documented SQLite cross-process false-negative residual.
- Private dump snapshots, retained input descriptors, replay rehashing, temp
  cleanup, authenticity, or hostile-input mutation defenses.
- A schema-1 to schema-2 migrator or claim that old schema-1 Taut can export the
  current logical dump format.
- A `SCHEMA_VERSION` bump, empty migration registry, or speculative future rung.
- Summon schema-migration changes; it remains a precedent, not a shared owner.
- Dump format, component format, search schema/projection version, dependency,
  CLI grammar, or public API changes.

## Stop and Re-plan Conditions

Stop this plan rather than documenting over contradictory evidence if:

- the exact existing-member C1 interleaving omits the membership or publishes
  another legal-looking loss;
- the exact C2 race produces a missing-table exception on a supported SQLite
  runtime;
- a stable source dump can fail digest integrity without overlapping mutation;
- the owner decides load must apply validation-time bytes despite input
  mutation;
- schema 1 becomes a supported migration source;
- a real schema bump is pulled into this work;
- PostgreSQL cannot preserve the proposed all-rungs-under-one-lock transaction
  boundary;
- deterministic tests require production scheduling hooks or a second runtime
  implementation path.

Each condition changes intended behavior or blast radius and requires a new
classification, exact spec delta, and independent review.

## Deviation Log

| Spec ref | Planned behavior | Actual behavior | Rationale | Spec proposal |
|----------|------------------|-----------------|-----------|---------------|

## Revision Log

| Date | Revision | Reason | Review required |
|------|----------|--------|-----------------|
| 2026-08-24 | Initial hardened draft | Address C1-C4 with contract alignment, deterministic characterization, and a future ordered schema ladder | Independent plan and spec-delta review required before promotion |
| 2026-08-24 | Reader-test hardening | Removed implementer choice from the dump publication assertion, search result oracle, schema diagnostic/sentinel, and scheduling boundary | Rerun fresh-reader test; independent technical review remains required |
| 2026-08-24 | Independent-review hardening | Pinned the current spec overlay, replaced the search barrier with a two-event handshake, added newer-version proof, specified the current-DDL/load-guard tail, and corrected the SimpleBroker precedent and TDD posture | Independent reviewer recheck and fresh-reader retest required |
| 2026-08-24 | Review polish | Added a non-vacuous stable search baseline and made both schema refusal directions explicit in final success | No further plan review required unless scope, invariants, or blast radius changes |

## Review Log

| Date | Reviewer | Finding | Disposition |
|------|----------|---------|-------------|
| 2026-08-24 | Fresh zero-context reader | Core decisions were understood, but exact diagnostic text, dump failure assertion, search oracle, schema sentinel, and scheduling mechanics required guessing | Applied: each assertion, fixture, and one-shot scheduling seam is now explicit; reader retest pending |
| 2026-08-24 | Independent technical reviewer | Promotion blocked by an incomplete spec baseline, weak one-barrier search recipe, missing newer-version proof, omitted current-DDL/load-guard migration tail, conditional dump assertion, overstated SimpleBroker postconditions, and misclassified characterization TDD posture | Applied all findings: baseline overlay is pinned; two-event scheduling and both version refusals are exact; ladder tail is normative; dump sentinel is mandatory; precedent and test posture are corrected; reviewer recheck pending |
| 2026-08-24 | Fresh zero-context reader recheck | Prior ambiguities were resolved; only non-material choices such as timeout literals and final test names remain | Passed: zero-context implementation verdict is yes |
| 2026-08-24 | Independent technical reviewer recheck | F1-F7 resolved; suggested an explicit stable pre-race search assertion and both-version success summary | Applied both polish items; spec-promotion readiness is yes |
| 2026-08-24 | Characterization-slice reviewer | Initial C2 test covered only post-commit stale metadata and used executor teardown that could wait indefinitely; the first DDL-boundary revision signaled before the real read completed | Applied: retained the bounded provider race, added a separate real transactional DDL probe, moved its event after the fetched old-slot `MATCH`, required the exact old rows, and used bounded daemon-thread release/join paths |
| 2026-08-24 | Characterization-slice reviewer recheck | The corrected DDL probe causally completes the real read while the writer remains paused after uncommitted `DROP`; exact oracle and cleanup are sound | Passed with no blocker after `30/30` repeated focused executions |
| 2026-08-24 | Independent completed-work reviewer | No blocking correctness, contract-alignment, program-theory, or scope-drift findings; requested append-only traceability for the later third C2 proof and 145-test slice | Passed; applied the traceability note by restoring the historical execution row and appending the hardening evidence separately |

## Execution Log

| Date | Slice | Evidence and result |
|------|-------|---------------------|
| 2026-08-24 | Plan authoring | Spec overlay hash reproduced as `8e81c418d106285174731c2c7d8acc5f0299b3aa3c5f6c4149604baddb8a0bc6`; `bin/check-plan-status-index`, `uv run --locked bin/check-doc-paths`, and `git diff --check` passed; fresh-reader and independent technical rechecks both returned implementation-ready/spec-promotion-ready yes |
| 2026-08-24 | Pre-edit comprehension gate | (1) Live dump promises a validated, importable logical projection, not one MVCC snapshot; illegal composites fail. (2) SQLite rotation commits publication and inactive-slot DDL atomically, so separately committed query reads may omit candidates but cannot observe the intermediate drop. (3) One FTS `MATCH` is not equivalent because one message's terms may occupy different segment rows. (4) Load defends against no source-file mutation after validation starts; stable input is the A6 precondition. (5) Taut borrows named ordered adjacent rungs and version progression from SimpleBroker, strengthens every rung with an explicit postcondition, and retains one transaction, the advisory lock, portable dialect ownership, current DDL reconciliation, and load-guard enforcement. All answers match the reviewed expected answers; implementation may proceed. |
| 2026-08-24 | Spec promotion | Applied the reviewed [TAUT-3.3], [SRCH-11.1], [PIO-2.4], [PIO-7.4], and [PIO-8.2] text plus Related Plans links. Promotion baseline is HEAD `0eacc00adf33c0ab8feef46d35b7909c33f8c40e` plus three-spec diff SHA-256 `9a4ded829374606f352f60380d2315ed4cfa250bfd691a76a1b747c28980683e`; documentation path, status-index, and diff checks passed. |
| 2026-08-24 | Dump and search characterization | Added real-SQLite coordinated proofs for both C1 interleavings and the C2 generation switch, plus the existing cross-segment search proof. The two focused persistence tests and two focused search tests each passed `2/2`; the combined planned SQLite slice later passed `144/144`. No dump or search runtime code changed. |
| 2026-08-24 | Schema refusal TDD | The older-version case first failed only on the legacy `recreate the development database` text. After the narrow diagnostic change, both older- and newer-version cases passed on SQLite. `uv run --locked bin/pytest-pg --fast tests/test_state_contract.py` then passed `38/38`, proving both refusal directions and sentinel preservation on PostgreSQL. No migration rung, schema bump, or load-guard change was added. |
| 2026-08-24 | Durable explanations and local gates | Aligned the schema, search, and persistence implementation notes and trace mapping. `ruff check`, `ruff format --check`, and mypy passed across `taut` and `tests`; `check-doc-paths`, `check-plan-status-index`, and `git diff --check` passed. The work remains uncommitted and the plan remains `active` pending completed-work review and owner-authorized closeout. |
| 2026-08-24 | C2 proof hardening and final review | Replaced unbounded executor teardown with bounded daemon-thread release/join paths and added the direct transactional-DDL proof. The real old-slot `MATCH` completes with exact pre-transaction rows while the writer is paused after real uncommitted `DROP` and before `CREATE`; the three C2/cross-segment tests passed `30/30` repeated executions, the final SQLite slice passed `145/145`, and the independent completed-work review passed with no blocker. PostgreSQL remained `38/38`; repository-wide Ruff, format, mypy, documentation-path, status-index, and diff gates passed on the final tree. The plan remains `active` because the work is uncommitted and owner-authorized closeout has not occurred. |
| 2026-08-24 | Owner-authorized closeout | The owner requested a targeted completion commit after implementation, final verification, and independent review passed. This plan and its status-index row transition to `completed` in that commit; unrelated worktree changes remain unstaged. |
