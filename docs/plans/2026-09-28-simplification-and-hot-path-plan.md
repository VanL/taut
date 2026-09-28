# Simplification and hot-path implementation plan

Date: 2026-09-28
Class: 5 — changes specified failure policies, internal stored search state,
and Summon name allocation; hardening applies to storage and owner lifecycles.
Plan type: implementation with spec revision.
Owner: implementing engineer; independent reviewer checks each completed slice.
Lifecycle status: `docs/plans/README.md` is authoritative.

## Goal

Remove mechanisms that do not serve the current product, make routine search
and reads cheaper, and replace tests of deleted machinery with tests of useful
behavior. Preserve authoritative messages, identities, memberships, cursors,
native terminal ownership, and the existing SimpleBroker resource boundary.
This document plans implementation; its creation does not implement or publish
the changes.

## Owner decisions and scope

The owner explicitly rejected mixed-version-process support, search quarantine,
and an index rebuild as the upgrade strategy. Use existing database versioning
and forward-only transitions. Search is derived state, not an authoritative
record. Do not add leases, a migration framework, a daemon, a rollback mode,
a runtime attachment census, or a replacement failure queue.

Accepted implementation scope: S1–S10 below. Each slice includes its own test
simplification. This is not a line-count reduction target or a whole-repository
rewrite. Changes to current behavior are intentional where stated in the exact
spec delta; elsewhere existing public behavior remains the target.

## Source Documents

Consulted: `AGENTS.md`, `docs/program-theory.md`,
`docs/agent-context/README.md`, decision hierarchy, principles, engineering
principles, testing-patterns, writing-plans, hardening-plans, writing-specs,
review-loops-and-agent-bootstrap, the lessons ledger and coalescing state,
`docs/implementation/03-agent-inventory.md`, and the planning/reviewer skills.

Product sources:

- `docs/specs/02-taut-core.md` [TAUT-3.4], [TAUT-7.2], [TAUT-7.3],
  [TAUT-8.4], [TAUT-8.5], [TAUT-13].
- `docs/specs/03-identity-addressing-notifications.md` [IAN-3], [IAN-4].
- `docs/specs/04-summon.md` [SUM-4], [SUM-7.4], [SUM-8], [SUM-9],
  [SUM-10], [SUM-11], [SUM-12], [SUM-13].
- `docs/specs/05-taut-mcp.md` [MCP-4], [MCP-5], [MCP-10], [MCP-12].
- `docs/specs/06-search.md` [SRCH-6], [SRCH-8], [SRCH-9], [SRCH-10],
  [SRCH-11], [SRCH-12].
- `docs/specs/09-system-doctor.md` [DOCT-4].
- `docs/specs/08-persistence-io.md` [PIO-2.2], [PIO-5.2].
- `docs/specs/10-taut-tui.md` [TUI-2.2], [TUI-2.3], [TUI-6.1], [TUI-13.2].
- `docs/implementation/04-taut-architecture.md`,
  `docs/implementation/05-taut-summon-architecture.md`,
  `docs/implementation/07-taut-mcp-architecture.md`,
  `docs/implementation/09-search-architecture.md`,
  `docs/implementation/12-taut-tui.md`.
- `docs/plans/2026-09-15-reported-issues-followup-plan.md` (search cost),
  `docs/plans/2026-09-24-cli-read-delivery-and-agent-recipes-plan.md`
  (delivery ordering), `docs/plans/2026-09-24-watch-interrupt-drain-plan.md`
  (keep the active signal policy).
- Sibling SimpleBroker program theory, public Queue/BrokerSession contract,
  and SQLite validation lock-safety evidence were consulted during the audit.
  This plan changes no SimpleBroker code and requires no new upstream API.

## Spec Baseline

`4a825b69d20c912e23c38bd4ca39ab62dace2c91` is the code and spec baseline.
The pasted external report is a leads list, not authority or accepted numerical
evidence. Its scratchpad measurements are unavailable in this checkout.

Promotion strategy: **B, atomic per slice**. The exact delta assigned to a slice
is applied with its implementation, tests, implementation note, and backlinks.
Do not promote all changes ahead of their code. Record the resulting baseline
identifier for each slice in the Execution Log; never claim plan-only prose is
the active spec. Existing stable section codes remain, with obsolete mechanism
text replaced rather than leaving contradictory paragraphs.

## Invariants and constraints

1. Source messages and Taut sidecar state remain authoritative. Search failures
   cannot roll back a successful chat write. Hydration, search scope, DM
   visibility, native backend analyzers, and explicit `--reindex` remain.
2. Pending invalidations are non-consuming reads until processing commits.
   Delete an exact job only after its index update commits. Already absent
   after our successful update is success. A provider/broker failure leaves
   valid work pending and fails the search; malformed work is warned and
   discarded. Do not catch all failures as malformed input.
3. Retain revision ordering and deletion tombstones for overlapping same-version
   operations. Removing ownership leases does not remove stale-update ordering.
4. Upgrade existing search state in place. Do not rebuild/drop FTS documents,
   projections, current generation, or watermarks to remove job bookkeeping.
   No mixed-version execution, downgrade, or reverse migration is supported.
5. Reuse SimpleBroker public Queue/session/sidecar operations. No raw SQL against
   broker tables, no raw database header reads, no per-queue backend stacks.
6. CLI delivery still flushes each record before durable cursor advancement.
   Bind that read's stable member ID once. Ordinary public identity selection
   outside that operation remains live; do not cache a mutable name forever.
7. Ordinary watch handler failure stops the attempt, preserves its unread chat
   cursor, and surfaces the error. Notification consumption stays as specified
   in [THEORY-5.A1]; this plan does not add notification redelivery.
8. Keep the single-driver guard, checked native-worker joins, cancellation/write
   ownership, owner-thread resource cleanup, and general SIGINT flag-and-drain.
   A failed join must still prevent a successor generation.
9. No new generic executor, observation bus, compatibility adapter, test-only
   product API, rate-control replacement, or configuration flag.

## Rollout and forward recovery

Upgrade with application processes stopped, as an operator precondition. Do
not build a process census or a live-upgrade coordinator. Run the new version's
normal schema initialization on the selected workspace before reopening other
long-lived clients: the first new-version search initializes search; Summon
driver/controller startup initializes its ledger. There is no new upgrade CLI.
Passive dump/validation is not a Summon upgrade entry point. Search uses its
existing schema singleton (version 1 at
baseline); Summon uses `summon_schema_version` (version 3 at baseline).

S2 introduces search version 2; S7 introduces Summon version 4. Both retain
normal unsupported-newer-version refusal. Keep supported older-to-current
forward paths; do not mistake removal of the claims table for permission to
strand a previously supported Summon version 2 database.

For search, move old claimed rows back to pending using timestamp-preserving
public queue operations, remove the obsolete failed queue, then remove claim
and housekeeping tables and publish version 2. Repeating an interrupted
transition must finish the same transition without reconstructing the index.
This is one version branch, not a journal/protocol. S2 specifies the public
Queue calls and version-write ordering below. There is no `taut upgrade`
command at baseline: upgrade is the first new-version search under quiescence.

For Summon, preserve every session row while removing transient name-claim
state; finish at version 4. A deployed storage transition is a one-way door.
Recovery is a corrected forward release, not running the old binary against
new state. No automatic rebuild, backup restoration, or downgrade is proposed.
Source-only slices can be reverted in development before release; changes
already coupled to a stored version must be corrected forward.

## Investigation disposition and ownership

| Finding | Disposition | Slice |
|---|---|---|
| Search unchanged FTS writes, transient job queues, repeated DDL | Remove repeated work | S1, S2 |
| Search leases, quarantine, detached-worker scaffolding, lost-ack proof | Delete mechanisms and their specs/tests | S2 |
| Per-job registry listing and transient candidate handles | Snapshot registry and reuse S1 handles; retain indexed point lookups, measure before redesign | S3 |
| MCP token hardening and global rate bucket | Remove; retain same/different-token binding and busy/cap limits | S4 |
| Vendor redaction rules | Remove vendor formats; retain structural scrub | S5 |
| Empty-result debug capture and repeated target discovery | Fix boundary and reuse resolved target | S5 |
| CLI read identity recapture / rename failure | Bind stable actor once; preserve per-record cursor durability | S6 |
| Full-body peeks for boolean unread consumers | Add a count-free core projection path | S6 |
| Poison retry/skip | Replace with fail-stop and explicit replay | S6 |
| Summon transient name claims | Remove; core atomic creation owns route exclusion | S7 |
| Generation tags / duplicate generation state | Replace with generation-owned result transport | S8 |
| Dead TUI metadata / duplicated domain execution | Targeted deletion and shared semantic dispatch | S9 |
| Test-only close sequences, polling, private-state mirrors | Replace where touched, preserve causal ownership proofs | Every slice, S10 |
| Workflow formatting prefix assertion misses dropped Summon coverage | Check effective intended formatting/type-check coverage with removal mutation proofs | S10 |
| Cleanup secondary failures and inaccurate one-file wording | Preserve exception notes; clarify sidecars | S10 |

### No-action and deferred register

SQLite pre-open validation optimization is declined in both Taut and
SimpleBroker. Validation belongs to SimpleBroker; the owner's SimpleBroker
audit found the cost minuscule and unlikely to occur in practice. No action,
reopen condition, or upstream follow-up is assigned by this plan.

| Unit | Disposition / reason | Reopens when |
|---|---|---|
| BrokerSession ownership, retryable unfinished cleanup | Keep: demonstrated owner/core lifecycle requirements | A concrete simpler owner model preserves the same effects |
| Summon audit source and bounded STATUS/PING resend | Keep: own sends are absent from unread watching; a reply can be dropped | Replacement supplies the same observations/recovery |
| CLI cursor batching | Deferred: replay window is a separate product choice; S6 removes recapture now | Profiling after S6 still shows cursor writes dominate and owner selects batching |
| Global TUI identity caching, macOS host-ID fallback redesign | Deferred: stable cross-invocation identity needs a separate choice | A concrete identity failure/profile motivates that design |
| Remove route provenance validation, resize/focus model, CSI parser redesign | No blanket removal; distinct UI/terminal semantics remain | A bounded refactor proves the same current behavior |
| Scripted provider wheel packaging | Keep current real installed-provider qualification | A test-only child arrangement demonstrates equivalent installed-adapter coverage |
| Always-true setup-recovery capability | Deferred protocol trim, not a dependency of S8; keep disable switch | Supported-host contract is explicitly narrowed and current embedder use is checked |
| Control fallback route, borrowed queue constructor seams, TUI direct wrappers | Deferred API cleanup, not required by retained slices | Supported caller inventory establishes the narrowed API |
| Repository-wide private-name census / recorder-suite deletion | Reject as a deletion criterion | A behavior-preserving alternative demonstrates lower cost and equal evidence |
| Whole workflow/release-tool rewrite, new suppression policy | Separate process change; do not expand this product plan | A scoped tooling request; update existing suppression inventory for changed code here |

## Context and key files

| Area | Existing owner and edit surfaces |
|---|---|
| Search | `taut/client/_searching.py` orchestrates search/drain/reconciliation; `taut/client/_base.py` enqueues; `taut/search/_jobs.py` owns old queues/leases; `taut/search/_worker.py` applies jobs; `taut/search/_provider.py` is backend boundary; `taut/search/_sqlite.py` and `extensions/taut_pg/taut_pg/_search.py` own index SQL |
| Search integration | `taut/_doctor.py`, `taut/persistence/_operations.py`, `taut/persistence/_components.py`, `tests/test_search_jobs.py`, `tests/test_search_worker.py`, `tests/test_search_client.py`, `tests/test_search.py`, `tests/test_system_doctor.py`, `tests/test_persistence_io.py` |
| MCP | `extensions/taut_mcp/taut_mcp/_process_reactor.py` owns resident registry, token fingerprints and bucket; `extensions/taut_mcp/taut_mcp/server.py` owns rate-error transport translation; public admission/response behavior is tested by `test_process_reactor.py`, `test_stdio_server.py`, `test_resource.py` in that package's tests |
| Debug/read/watch | `taut/_redact.py`, `taut/debug.py`, `taut/commands/_dispatch.py`, `taut/commands/_protocol.py`, `taut/commands/read.py`, `taut/commands/list.py`, `taut/client/_messaging.py`, `taut/client/_threads.py`, `taut/watcher.py`, `taut/_cleanup.py` |
| Summon | `extensions/taut_summon/taut_summon/_state.py` owns ledger versions; `_driver.py` owns creation/generations; `_reactor.py` publishes delivery results; `persistence.py` owns logical projection; `_control.py` behavior retained |
| TUI | `extensions/taut_tui/taut_tui/actions.py`, `forms.py`, `command_bindings.py`, `screens.py`, `app.py`, `session.py` own registration, presentation and serialized domain work |

Before the first storage/owner slice, the implementer records answers to these
two questions in the Execution Log. Expected answers are included; an incorrect
answer requires rereading the owning code before edits, not additional design:

1. What does removing a search lease permit, and what prevents a stale index
   write? Duplicate work is permitted; provider revision ordering still applies.
2. What prevents an old native result affecting a new Summon generation? A
   result transport owned by that generation plus checked retirement before
   starting its successor; an unsuccessful join prevents the successor.

## Proposed Spec Delta

The following is exact replacement/insertion text. Apply the relevant blocks
atomically with their slice. Remove directly contradictory verification and
implementation-mapping claims in the same edit; preserve unrelated paragraphs.

### D1 — search, S1–S3

Replace [SRCH-8.1], quarantine paragraphs of [SRCH-8.2], worker/claim sections
[SRCH-9.1–9.3], and claim-specific language in [SRCH-10.1] with:

> Core owns one unregistered pending invalidation queue, `taut.search_index`.
> It is auxiliary search state and is excluded from logical dump/load. Search
> runs pending work synchronously before querying; source mutations enqueue
> best-effort invalidations after their authoritative commit. No detached worker,
> claim queue, visibility timeout, worker lease, or failed-work queue is part of
> the current search contract.
>
> A search captures a finite pending-work frontier. It non-destructively reads
> jobs through that frontier, loads current canonical source state, applies the
> existing revision-fenced provider update, and only then exact-deletes the job.
> Duplicate processing by concurrent calls is allowed. An already absent job
> after this call's successful provider commit is success. A provider or broker
> failure leaves valid work retryable and fails the search normally.
>
> A structurally invalid job is discarded after a bounded structural warning
> is added to `last_search_warnings`; its body is not copied into the warning or
> another queue. Failure to delete is an ordinary broker failure. The next
> valid job is not blocked by a successfully discarded malformed job.
>
> Message IDs remain immutable identity; stored thread names are location hints.
> Rename/name-reuse correctness, current source hydration, revision ordering,
> and reconciliation remain required. These requirements do not mandate one
> registry listing or an all-thread exact-probe loop per job.
>
> Existing index state is upgraded forward in place using the search schema
> version. Upgrade preserves indexed documents and current generation, returns
> outstanding claimed invalidations to pending, and removes obsolete claim,
> housekeeping and failed-work state. No mixed-version execution, downgrade,
> or index rebuild is required for this transition.

Insert into [SRCH-6.2] and update provider verification in [SRCH-12]:

> A current schema requires a version check, not installation DDL. Newer
> unsupported versions fail before shape-dependent mutation; older supported
> versions follow the declared forward transition. Initialization and upgrade
> preserve each backend's existing transaction/lock ownership.
>
> Updating an unchanged indexed document advances only its accepted revision.
> Postings are replaced only when thread, text hash, text length, projection
> version or indexed state differs. The revision fence and comparison are
> atomic per generation, including an existing staging generation.

Replace [DOCT-4.6] with:

> Read public statistics for `taut.search_index` without creating or processing
> work. Report `search_work` data as `{"pending": N}`, where N is QueueStats.total,
> or zero if absent. Pending depth is informational and passes; it does not prove
> index health or freshness. Claimed/failed work
> fields and quarantine-derived health failure are removed.

In [PIO-2.2]/[PIO-5.2] and [IAN-6.1], replace the obsolete three-queue search
inventory with the pending queue. Preserve omission of derived search tables,
index state and internal work from logical dump/load; add no dump format.

Retain [SRCH-10.2] reconciliation and [SRCH-10.3] explicit rebuild semantics.
Replace tests enumerating leases/quarantine with duplicate-processing,
commit-before-delete, malformed-item progress and forward-upgrade tests.

### D2 — MCP, S4

Replace fingerprint/HMAC/reference-blanking requirements throughout [MCP-4],
[MCP-10], [MCP-12], and bucket requirements in [MCP-5]/[MCP-10] with:

> A resident workspace binds the exact supplied continuity token. The same
> token permits resident reuse; a different token conflicts until detach.
> Exact ordinary string equality implements this selector comparison. There is
> no cryptographic comparison, live-frame scrubbing, or zeroization contract.
> Retirement releases the owning entry normally. Expected diagnostics and
> protocol results do not echo tokens; host-owned copies remain outside Taut's
> control. Storage access remains the trust boundary.
>
> Admission retains the workspace busy slot and resident cap. There is no
> process-wide request-rate bucket. Cached resource polling cannot consume a
> quota needed by another valid tool call. Remove the Taut-specific
> RATE_LIMIT_EXCEEDED / -31999 result and its advertised policy.

### D3 — debug capture and redaction, S5

Replace vendor-format rule family 4 and compiler-specific requirements in
[TAUT-13.3.1] with:

> Redaction covers the existing structural rules for labeled credentials,
> Authorization values, credential-bearing connection strings and private-key
> PEM bodies. It does not recognize bare credentials by vendor prefix. Debug
> events remain sensitive and are not safe-to-share artifacts. Redaction
> preserves valid JSON and has bounded work for bounded event input; a scrub
> failure drops the event without an unredacted fallback. The contract does not
> prescribe regex compilation counts or a private detector manifest.

Insert into [TAUT-13.2] and qualify totality in [TAUT-13.5]:

> Expected CLI domain outcomes (`TautError`, including empty/not-found results,
> and declared `CommandError` outcomes) are rendered without debug capture.
> Unexpected execution/load/cleanup exceptions remain eligible. When a command
> has already resolved its target/config, capture reuses them; capture must not
> create a client merely to obtain them. The workspace debug setting is still
> read per eligible event. Ordinary diagnostic failures never replace the
> primary exception. A fresh KeyboardInterrupt during capture propagates;
> changing a process-control exception into a silent return is not required.

### D4 — reads and watcher failures, S6

Insert into [TAUT-7.2]:

> One CLI read binds the stable member ID used to select its unread page and
> uses that ID for every delivery acknowledgement. A concurrent member rename
> or reuse of the old name cannot redirect or abort those acknowledgements.
> Each record is flushed before its cursor update; this change does not batch
> delivery commits or change the crash replay window.

Insert into [TAUT-7.3]:

> Boolean-only thread consumers use existing pending-timestamp metadata, not full message
> bodies to compute a count they do not display. Human CLI and TUI consumers
> may request the existing bounded display counts. The default Python result
> continues to include those counts.

Replace the ordinary-handler poison policy in [TAUT-8.4]:

> The first ordinary chat handler exception stops the watcher attempt, leaves
> that record unread and surfaces the failure. There is no automatic handler
> replay or count-based cursor skip. An explicit subsequent watch may deliver
> the same record again. Earlier successful records remain acknowledged.
> StopWatching and WatcherRejected retain their terminal-control behavior.
> Notification claim/consumption behavior is unchanged.

Insert into [TUI-6.1] as part of S6:

> When the current conversation watcher exits because of a captured failure,
> its visible degraded report includes the original exception type and message.
> An exit without a captured cause uses a generic fallback. A retired watcher's
> failure cannot degrade a newer conversation/session generation.

Replace the user-handler poison clause in [SUM-5.4] as part of S6:

> Summon inherits ordinary chat user-handler fail-stop, including synchronous
> formatting/preparation failures. The agent cursor remains unchanged. The
> operator fixes the handler/configuration cause and restarts Summon for the
> same member; the unread record is delivered again. This adds no automatic
> skip, replay command, quarantine or recovery ledger. Decode and asynchronous
> adapter/source failure policies, and claim-consumed notifications, remain
> unchanged.

### D5 — Summon names and generations, S7–S8

Replace transient name-claim and post-claim fallback clauses in [SUM-4]/[SUM-8]:

> Core's atomic `join(..., new=True)` under the final name owns route
> exclusion. Summon never adopts an existing member while creating a new one.
> A chosen-name collision refuses whether discovered before or during create.
> An implied-name collision uses the existing bounded name fallback.
> No separate transient name-claim table is maintained. Session publication,
> token recovery after partial creation, and the existing member's single-driver
> guard remain. Ledger upgrades preserve session rows and discard obsolete
> transient name claims through a forward version transition.

Replace representation-specific generation-token clauses in [SUM-11]:

> Each running generation owns its native workers and their immutable result
> transport. Only its owner applies those results. Retirement completes checked
> worker joins before a successor generation starts; a failed join prevents
> that successor. Retired results cannot affect successor state or external
> effects. This contract requires generation isolation, not numeric tags on
> every intermediate result object.

### D6 — TUI and documentation, S9–S10

Insert into [TUI-2.2] and align [TUI-13.2] verification:

> Forms, commands and direct gestures resolve inputs for the same semantic
> action execution. Confirmation text comes from the action definition.
> Presentation-specific validation, stale-context checks and asynchronous
> completion remain on their owning surface. Metadata with no rendering,
> dispatch or user-visible validation consumer is not a required contract.

For one-file wording in [TAUT-2]/[TAUT-3.1], README and [THEORY-1], replace the
literal no-lock-file assertion with:

> A SQLite workspace has one primary durable data file. SQLite and SimpleBroker
> may maintain coordination, journal and WAL sidecars; those are owned by the
> storage layer. Taut requires no separate application state directory or daemon.

## Dependency-ordered implementation tasks

Each slice uses red-green tests for changed behavior. Pure deletions/refactors
use the retained behavioral suite plus a recorded inspection showing the old
mechanism is absent; do not invent implementation-mirror tests to get a RED.
After each coherent slice, run independent review, disposition its findings,
and update the implementation note. Do not defer all review until the end.

### S1 — make unchanged search maintenance cheap

- [ ] Edit both provider files from the context table. In the existing provider
  transaction and per-generation function, apply revision ordering before the
  equality fast path. Same revision with changed content must still update.
  Current and staging generations are checked independently.
- [ ] Use a search-operation `BrokerSession` anchor and directly created
  persistent job/source Queue handles. Cache probed source handles for one
  drain only; do not mint each through `session.queue()` or retain them in
  the long-lived client cache. Keep source-hydration/reconciliation in this
  same scope where practical. Close a partially consumed source generator before
  its Queue and close the operation anchor last. The operation may hold one
  handle per probed thread until the drain ends; measured physical connections
  remain flat. No change to global client persistence defaults.
- [ ] Add real SQLite and PG provider tests: identical document/newer revision
  causes no postings replacement; changed text/thread and unindexed tombstone
  still update; stale revision cannot undo newer content; staging stays correct.
  A SQL spy may count real executed postings writes, not replace transactions.
- [ ] Record cold/warm/deletion-drain cost for 1, 10 and 100 threads with 100
  jobs, both transient and persistent clients. Counts distinguish physical
  backend creation, Queue handles, source probes and postings writes. Record
  timings as evidence, not brittle CI thresholds. Stop if scope-close leaks or
  a change requires private SimpleBroker access.
- Done: same hits/visibility, zero postings churn for unchanged warm documents,
  and bounded backend lifetime per operation rather than per queue operation.

### S2 — remove the search work protocol and upgrade in place

- [ ] Replace `_jobs.py` claim operations with pending peek/exact-delete;
  simplify `_worker.py` to decode, load, apply, delete. Delete lease IDs,
  worker IDs, clocks, reclaim sweeps, failed envelopes and lost-ack exceptions.
  Retain the current closed job grammar and useful structural warning codes.
- [ ] Add `schema_version() -> int | None` to the existing internal provider
  protocol and both backends. The backend owns metadata-table absence detection
  and returns the stored version without shape-dependent writes. For supported
  schema versions it also validates projection version 1 before returning;
  unsupported newer schema refusal must precede shape-dependent projection
  queries. A current schema number alone must not bypass projection checks.
  One shared
  search version constant in `_provider.py` replaces the two local constants.
  Core checks it once: current 2 proceeds without DDL; unsupported newer/older
  refuses; absent or 1 enters the explicit initialization/forward path. No new
  `taut_meta` marker or generic migration API is introduced.
  Update the provider-method validator in `taut/search/_discovery.py` and
  `tests/test_search_discovery.py` with this internal seam; a provider missing
  it still receives the existing actionable invalid-provider diagnostic.
- [ ] Under the quiescent upgrade precondition, return each legacy claimed row
  with `claimed.move_one(pending, with_timestamps=True)`.
  It preserves the original body and job timestamp. Normal broker timestamp
  uniqueness makes a duplicate destination an invalid state: fail loudly rather
  than inventing a merge protocol. Delete the empty legacy claimed queue and
  obsolete failed queue via `open_broker(...).delete(name)`, using public queue
  statistics to avoid opening absent legacy queues. Then call the provider's
  initialization/upgrade transaction. Discard failed envelopes. Drop only
  `taut_search_claims` and `taut_search_housekeeping` and obsolete work queues.
  Update the existing search singleton version last in that transaction. Fresh
  schema 2 omits obsolete objects entirely. Interrupted pre-transaction moves
  are naturally repeatable; an absent old queue needs no move. No queue calls
  occur inside the provider's write transaction. The existing physical index
  schema/projection stays intact; this version also describes work processing.
- [ ] Split each provider's `ensure_schema` into cheap current-version read and
  existing initialization/upgrade transaction. Detect metadata absence without
  leaving PostgreSQL in an aborted transaction. Preserve PG advisory lock on
  the initialization path; do not take an installation lock for a current schema.
- [ ] Check doctor/persistence consumers and named tests from the context table
  for removed queue/table assumptions; update only actual consumers. Logical
  dump/load continues omitting derived search state, with no new dump fields.
  Update `tests/test_shared_contract.py` for the pending-only doctor object.
- [ ] Real backend proofs: two searches process one job safely; interruption
  after index commit leaves replayable pending work; malformed then valid job
  progresses with a warning; provider failure does not discard valid work;
  upgrade fixture retains hits/generation and moves old claimed work; interrupted
  upgrade resumes; warm current schema emits no installation DDL; future schema
  and projection versions refuse without mutation. No concurrent old/new-version
  test matrix.
- Done: pending-only processing and existing-index forward upgrade work on both
  backends. Stop if upgrading requires rebuilding the index or a new subsystem.

### S3 — eliminate per-job registry work and repeated fallback setup

- [ ] In `_drain_search_jobs`, capture frontier, read the searchable registry
  once, and reuse S1's operation-scoped handles. Keep indexed exact-ID probes
  for each candidate thread. Use the job hint only after canonical verification;
  do not rebuild the candidate registry for each job.
- [ ] Preserve rename/name-reuse behavior with at most one topology refresh per
  drain when needed, not one refresh per missing job. Missing IDs remain
  revision-fenced deletions. No range-scan implementation, permanent redirect
  cache, new identity table or background index is required by this slice.
- [ ] Run the S1 benchmark after handle reuse and the single registry snapshot,
  covering ordinary hits, missing messages, deletion-heavy drains and renames.
  Record connections, registry reads, point probes and elapsed time separately.
  Remaining fallback work may be O(jobs × threads) indexed point probes; do not
  claim that registry/connection savings remove that cost. Only measured material
  residual probe cost justifies proposing a further lookup redesign. Range scans
  are not a landing requirement and must not be preselected without comparison.
- [ ] Preserve delayed-job/reused-name tests in `tests/test_search_client.py`.
  Add real queued-work tests with many deletions and a rename barrier. Assert
  bounded registry reads per drain and handle/core lifetime; do not assert
  `Queue.close()` invocation choreography. Include sparse, widely separated IDs
  in deletion-heavy benchmark inputs so any later range-scan proposal has a
  representative comparison baseline.
- Done: one ordinary registry snapshot, bounded refresh, shared operation
  resources, retained indexed point lookups and recorded measurements. No new
  thread identity: `created_ts`
  is not schema-unique, and making it job identity would add another contract.

### S4 — simplify MCP resident binding and admission

- [ ] `_process_reactor.py`: store/compare the exact token on its owning entry;
  remove digest/HMAC generation, scattered blanking and fingerprint-only cleanup
  helpers. Delete the process bucket, rate-limit response and advertised policy.
  Preserve candidate/canonical path arbitration, hidden-seat lifecycle,
  cancellation, resident cap and per-workspace busy slot.
  Remove the rate-limit translation in `extensions/taut_mcp/taut_mcp/server.py`
  as well; do not leave dead response vocabulary at the transport boundary.
- [ ] Remove frame-local traversal and bucket/starvation tests. Keep public
  same-token reuse, different-token conflict, detach/reattach, cancellation and
  no-token-in-error-output tests. Exercise a burst of resource reads followed by
  a valid tool call; prove no Taut quota rejection and busy/cap still fire.
- Done: same resident identity semantics with no secret-handling or global rate
  mechanism. Stop if cleanup lifecycle is redesigned beyond removed fields.

### S5 — narrow debug work and structural redaction

- [ ] Remove bare vendor-key detectors from `_redact.py`, retaining the existing
  structural rules and bounded serialized-JSON boundary. Delete private rule-ID
  and compile-count tests; keep structural examples, near misses, valid JSON,
  bounded hostile input, fail-closed behavior and real sink tests.
- [ ] `_capture_boundary_exception`: exclude declared domain/command outcomes;
  `CommandContext` exposes already-created client target/config without creating
  a new client. Reuse `capture_exception`'s existing resolved-target parameters.
  Load failures without a client retain bounded existing discovery.
- [ ] In `debug.py`, preserve ordinary failure containment but explicitly allow
  KeyboardInterrupt to propagate at every enclosing capture layer, including
  object rendering. Ordinary errors in a user object's repr remain contained;
  no attempt is made to distinguish a raised KeyboardInterrupt from a signal.
- [ ] Tests in `tests/test_redact.py` and `tests/test_debug_capture.py`: empty
  read produces no event/discovery; unexpected exception still captures; resolved
  target reused; real action interruption is observable; structural secret absent
  at both sinks, while bare vendor-shaped text is not promised redacted.
- Done: normal empty results incur no diagnostic DB work; unexpected diagnostics
  retain bounded structural protection and interruption behavior.

### S6 — stable read identity, cheap boolean unread, fail-stop watch

- [ ] Factor the existing unread selection in `_messaging.py` into one internal
  routine returning stable member ID plus messages. `read_unread` keeps its
  existing public signature and return shape. The CLI adapter uses that same
  routine and an internal cursor-update seam taking the bound member ID; no
  receipt class, ticket protocol or new public acknowledgement object.
  Keep existing per-record write/flush/update ordering and error precedence.
- [ ] Add keyword-only `include_unread_counts: bool = True` to thread-list APIs
  that currently compute counts. Count-free mode derives `unread` from the
  already fetched `latest_pending_ts`: membership exists, timestamp is not
  None, and timestamp exceeds `last_seen_ts`. Add no extra existence query.
  Leave unused `unread_count` at zero; document that
  mode. JSON/quiet CLI listing selects false, including MCP's CLI-shaped path;
  human CLI and TUI retain true. Update mirrored base declarations and owned
  command/test fakes with the same signature.
- [ ] Remove watcher `_failures` accounting. Change the Taut handler/error
  path so an ordinary user-handler exception stops this run and is propagated
  by the driving owner instead of the vendored scheduler logging and retrying.
  Use one owner-only slot for the exact ordinary `_user_handler` exception.
  A chat-only error handler, wired for initial and dynamically added chat
  queues, marks `_stop_requested` and returns false only for that recorded
  object; other errors delegate to the existing default. In the existing
  `_drain_queue` override, translate the paired StopWatching back to the original
  exception after dispatch cleanup. In direct `process_once`, route requested
  stop cleanup through `_finalize_run` so cleanup errors become notes rather
  than masking the primary error. Keep decode outside this capture; notification
  error handling, unpaired StopWatching and WatcherRejected are unchanged.
  Do not change copied Weft scheduling or introduce a general failure framework.
- [ ] Transfer a captured watcher failure through the owned watcher/session
  lifecycle to the TUI degraded report in `extensions/taut_tui/taut_tui/session.py`.
  Show its original type and message, with a generic fallback only when no cause
  is available. Joining a thread alone does not retrieve its exception. Preserve
  the current generation/owned-watcher checks; do not install a global exception
  hook or expose traceback internals as the UI contract.
- [ ] Real proofs in `tests/test_cli.py`, `tests/test_client.py`, and
  `tests/test_watcher.py`: rename plus old-name reuse during delivery advances
  only original member; partial pipe/encoding failure keeps undelivered records;
  count-free list issues no body peek and returns correct boolean; a failing
  handler runs once, leaves cursor, raises the original exception, closes
  resources, preserves cleanup notes, and succeeds after an explicit fresh watch.
  Require firing behavioral cases for driven execution, direct `process_once`,
  dynamically added chat queues, and cleanup failure during stop (both driving
  entry points). Assert one failing delivery, unchanged failed-record cursor,
  original exception propagation and resource cleanup; a secondary cleanup
  failure adds a note without replacing the primary. Do not assert the bridge's
  private slot, callback return sequence or paired-exception choreography.
  Keep separate proofs for unchanged decoding, notification handling and
  unpaired StopWatching/WatcherRejected behavior. These core cases pass before
  the Summon suite. Add a real SummonReactor
  preparation/formatting failure proof and run the Summon suite in this slice:
  failure preserves the agent cursor; restart after fixing the cause delivers
  that record. Existing decode and notification semantics continue to pass.
- [ ] TUI tests assert the human-visible degraded cause, the no-cause fallback,
  and that a retired watcher's failure cannot degrade a newer session. Exercise
  the real owned lifecycle rather than assert private exception storage. Run the
  TUI suite as an S6 integration gate, not only after S9.
- Done: no per-record identity capture, correct actor under rename, cheap boolean
  reads, and no hidden handler replay/skip. Cursor transaction batching is deferred.

### S7 — remove Summon name claims

- [ ] In `_state.py`, add forward version 4 preserving session rows and dropping
  claims/index. Preserve supported version 2 upgrade by transitioning directly
  to claim-free state; do not run obsolete duplicate-claim normalization merely
  to drop its output. Remove claim dataclasses, exceptions and state methods.
- [ ] `_driver.py`: remove acquire/release-name-claim branches. Final-name core
  `join(new=True)` arbitrates creation. Chosen collision refuses at every timing;
  implied collision uses existing bounded fallback. Keep recovery for a created
  member whose session publication fails and keep the single-driver guard.
- [ ] Update `persistence.py` version validation/projection and its tests where
  affected. Real concurrent creation tests cover chosen/implied and different
  providers: no existing member adopted, no shared newly created member. Upgrade
  fixtures preserve sessions/tokens/wired state. Remove synthetic claim-row tests.
- Done: no name-claim protocol, normal core exclusion, forward-only ledger upgrade.

### S8 — one owner per Summon generation

- [ ] `_driver.py` and `_reactor.py`: consolidate running-generation state and
  bind pump/delivery result publication to that generation's transport. Retired
  transports are not consumed by the successor. Remove redundant context/exit
  wrappers, numeric tags and dead `_pump` parameters only after binding results
  this way. Keep checked join, cancellation and native resource ownership.
  The reactor outlives generations: retirement must also retire its in-flight
  injection worker with a checked join, clear `_delivery_pending`, prepared
  payload, cursor and worker references without advancing the cursor, then call
  `_mark_pending_messages_prechecked`. Do not strand its delivery gate by merely
  abandoning the old result queue. A failed join prevents successor activation.
- [ ] Replace private double-activation tests with real generation turnover,
  cancellation and failed-retirement proofs in `test_owner_lifecycle.py`,
  `test_driver.py`, `test_reactor.py` and `test_control.py` under Summon tests.
  Use the existing scripted real child and causal events. Assert no successor
  starts after failed join and no retired result changes successor status.
  Turn over during injection and prove the successor can fetch and deliver the
  same unread record, with no acknowledgement from the retired delivery.
- Done: generation isolation expressed once through ownership. Stop if this
  requires a new state-machine framework or weaker native teardown.

### S9 — trim TUI metadata and share semantic execution

- [ ] Remove confirmed non-consumers: form `focus_order`, `FormControlKind`,
  redundant confirmation target declarations, unused validation code values,
  and unread `TuiCommandBinding.action_id`. Preserve `FieldKind` masking and
  actual route filtering/validation; no blanket `in_palette` replacement.
- [ ] Source confirmation wording from action definitions. Reuse current action
  dispatch and serialized session client-operation path. Extract only duplicated
  domain execution shared by form/command/direct inputs; preserve surface-local
  validation, draft state, stale checks and asynchronous completion.
- [ ] Delete self-consistency tests for removed metadata. Retain pilot-based
  public actions against a real temporary workspace in `test_tui_action_handlers.py`,
  `test_tui_action_routes.py`, `test_tui_forms.py`, `test_tui_command_bindings.py`.
  Each changed semantic operation needs a real outcome and its destructive
  confirmation, not every redundant internal call sequence.
- Done: no dead metadata or copied confirmation text; equivalent user operations
  reach one domain implementation. Stop before creating a generic command engine.

### S10 — close remaining proof and documentation gaps

- [ ] In touched tests, relay thread exceptions through futures/owner capture;
  replace repeated status CLI polling after a causal event with one assertion;
  use bounded parent watchdogs for real child reaping. Keep real PTY/ConPTY
  coverage and Windows qualification. Replace exact debug prose parsing with
  existing structured fixture evidence where available, without a product bus.
- [ ] `taut/_cleanup.py`: keep the first failure and attach later cleanup errors
  as notes; eliminate wrapper duplication only when call sites remain clearer.
  Preserve resource-close retry when a close actually remains unfinished.
- [ ] In `tests/test_github_workflows.py`, replace the weak formatting-command
  prefix assertion with a small coverage property over parsed workflow `run:`
  steps. Check that Ruff formatting and mypy invocations cover their intended
  source/test trees, including Summon. Resolve actual working directories and
  tool exclusions; distinguish path inclusion from effective checking. Retain
  separate mypy invocations where module naming requires them. Add mutation
  proofs: removing Summon from formatting or type-check coverage makes the
  property fail. Support the repository's actual command forms, not a general
  shell interpreter or a new workflow framework. This targeted gate fix is in
  scope; the deferred whole-workflow rewrite remains out of scope.
- [ ] Update each owning implementation note, spec mapping, README, CHANGELOG,
  repository map if symbols/modules move, and old active-plan overlap notes.
  Correct literal one-file wording and foreground-process examples in theory
  without expanding theory into a command inventory. Record a durable lesson
  only if it adds to existing guidance: specs should not fossilize incidental
  mechanisms. Evaluate heavily used planning/review guidance; no process rewrite.
- [ ] Final independent review of the combined diff and verification evidence.
- Done: no unsupported old-mechanism claims, all slice findings dispositioned,
  and published behavior/tests describe the simplified contract.

## Testing and verification commands

Run each extension suite in its own project environment: mixed `conftest`
imports are not a valid combined gate. Keep SQLite/PG, queue storage, schema
transitions, child processes and PTYs real. Fault injection may interrupt a
boundary or observe real SQL; it must not replace the storage/lifecycle under
test. Use events/barriers for ordering and timeouts only as deadlock caps.

Per-slice commands (from repository root; select only the owning files above):

```sh
uv run --extra dev pytest tests/test_search.py tests/test_search_jobs.py tests/test_search_worker.py tests/test_search_client.py tests/test_search_cli.py -n 0
uv run --project extensions/taut_pg --extra dev pytest extensions/taut_pg/tests/test_pg_search_provider.py extensions/taut_pg/tests/test_persistence_io.py -n 0
uv run --project extensions/taut_mcp --extra dev pytest extensions/taut_mcp/tests/test_process_reactor.py extensions/taut_mcp/tests/test_stdio_server.py extensions/taut_mcp/tests/test_resource.py -n 0
uv run --extra dev pytest tests/test_redact.py tests/test_debug_capture.py -n 0
uv run --extra dev pytest tests/test_client.py tests/test_cli.py tests/test_watcher.py -n 0
uv run --project extensions/taut_summon --extra dev pytest extensions/taut_summon/tests -n 0
uv run --project extensions/taut_tui --extra dev pytest extensions/taut_tui/tests -n 0
```

PostgreSQL qualification requires `SIMPLEBROKER_PG_TEST_DSN` and actual executed
tests. Skipped PG tests are an explicit remaining verification limit, never a
pass. Same rule for native Windows PTY/ConPTY qualification.

Final implementation gates: the existing per-project Ruff, mypy and pytest
commands declared by `bin/release.py` and CI, run without invoking publication;
no new gate wrapper. Include changed persistence/doctor tests and real installed
artifact coverage from existing fixtures. Run:

```sh
uv run --extra dev pytest tests/test_docs_references.py tests/test_cli_claims.py tests/test_github_workflows.py -n 0
uv run bin/check-plan-status-index
uv run bin/check-doc-paths
uv run --no-sync --extra dev python bin/ruff_suppression_index.py --check
```

At plan authoring, verification is document/path inspection and the two `bin/`
documentation gates; product tests wait for implementation. No RED is needed
for this documentation-only deliverable. Evidence records files, command,
observed result and remaining platform limitations. Completion/landing claims
follow the repository commit gate; do not manufacture a commit without authority.

Post-deploy signals require no monitor: repeat the S1 workload with the built
artifact, observe no warm postings churn, lower queue setup/registry work, normal
search hits after deletion/rename, no per-record identity capture, and explicit
watch-handler failure without cursor skip. No new telemetry infrastructure.

## Independent review loop

Use `skills/call-agent/SKILL.md`: a different-family reviewer, read-only, sees
this complete plan and exact deltas plus the baseline owners. Accepted risks:
no mixed-version support/downgrade, no search quarantine, duplicate search work,
no MCP process bucket, structural-only redaction, fail-stop watch behavior and
uniform chosen-name refusal. Review cannot reinstate those by calling the old
spec authoritative. It must identify a concrete violation of retained behavior.

Ask: can this be implemented confidently as written, and would it impair a
retained guarantee? Prefer removing unnecessary work. Pre-existing concerns
stay observations unless worsened here. Return PASS/BLOCKED, findings with
suggested dispositions, and a separate observations section. Rejected theory
alternatives [THEORY-5.A1–A6] remain in force; the review brief quotes them.
Record every finding and author disposition below; verify accepted corrections.

## Assumptions and Open Questions

- Search upgrades and Summon ledger upgrades run under the owner's existing
  quiescent, forward-only policy. No additional permission or runtime proof of
  quiescence is required. Implementer owns call-order verification in S2/S7.
- S3 retains indexed point probes. The implementer records measurements after
  handle/registry fixes; a further lookup redesign is proposed only if residual
  probe cost is material. It is not a prerequisite for completing this plan.
- Cursor batching, supported-host narrowing and fixture relocation are explicitly
  severed from this plan's implementation acceptance; their reopen conditions
  are in the deferred register, not hidden prerequisites.

## Deviation Log

| Spec ref | Planned behavior | Actual behavior | Rationale | Spec proposal |
|---|---|---|---|---|
| [SRCH-9.2] | Move each legacy claimed row by exact timestamp. | Move the oldest claimed row repeatedly, preserving its original timestamp. | The upgrade requires quiescence, so order does not affect the resulting pending set; avoids a separate timestamp read. | None. |
| [SRCH-8.2] | Reuse source handles without holding every queue open. | Cache each probed source handle until its drain ends. | The operation anchor keeps physical connections flat; handles are released at drain exit. Indexed point probes remain proportional to jobs times candidate threads. | None. |

## Review Log

2026-09-28, narrow different-family follow-up: Claude Opus rechecked the four
accepted integration-review documentation fixes against the live code, specs,
and theory. All four now match the implementation; it found no new
contradiction or reconsideration trigger. Its only non-blocking wording note
was that the changelog groups core debug redaction with MCP admission; the
redaction statement itself is accurate, so no further behavior or scope change
was made.

2026-09-28, final different-family integration review: Claude Opus reviewed
the combined implementation delta, full plan, applicable theory records, and
verification evidence read-only. Verdict `no blocker`; no theory
reconsideration. F1 removed a stale MCP `-31999` rate-limit claim; F2 updated
the required-coverage marker description; F3 added changelog notices for the
MCP response removal, bare vendor-key redaction limit, and one-way quiescent
upgrades; F4 published the old-process-stop precondition for Summon v2/v3→v4.
All four documentation findings were accepted and corrected. Observation O1
about broker-claimed rows in the legacy search claimed queue does not occur
on the baseline path: `JobQueues.claim_one` moves an unclaimed pending row to
the claimed *queue* and records its lease in the search sidecar; it never sets
SimpleBroker's row-level `claimed` flag. The forward upgrade's public move
therefore selects those rows. An external consumer claiming that internal
queue is outside the quiescent upgrade contract; no new recovery machinery was
added. Other observations are accepted derived-search lag and checked-retire
latency or pre-existing terminal traceback behavior, not new requirements.

2026-09-28, owner suppression challenge: no added directive was approved by
the initial implementation or by a count-only request. Two refactor attempts
removed both added BLE001 sites. Summon folds delivery retirement and pump join
under its existing teardown catch; a triple-failure test proves the inherited
primary receives both secondary diagnostics. The TUI exit monitor reports
after the joined drive's own finalizer and leaves the stopped watcher owned
for cleanup retry on switch or close, so it needs no new catch. Independent
read-only judgment chose the Summon combination and TUI refactor over their
original new catches. Only obsolete RUF015 and SIM117 directives were removed;
the owner explicitly allowed suppression removals. The human registry and
generated index were updated for those removals only, and `--check` passes.

2026-09-28, independent watcher/Summon implementation review: F1 corrected
passive Summon validation for upgradeable v2/v3 ledgers without mutating them;
F2 added deterministic real-core implied-name collision and five-attempt
exhaustion proofs; F3 added scripted-child turnover during blocked injection
and successor replay; F4 added a stale TUI watcher callback proof. F5 removed
the duplicate generation callback/fence, F6 centralized the failed-retirement
latch and tested the previously missed teardown call site, and F7 corrected
two active prose statements. A separate S6-S8 read-only pass found no further
blocker after the TUI cleanup-cause fix. The vendored scheduler bridge remains
a multi-part boundary, guarded by firing driven/direct/late-queue and cleanup
tests. No theory reconsideration was requested.

2026-09-28, second independent S6/S9/S10 review: count-free list, bound-ID
read acknowledgement, real leave/delete confirmation, and resource-close
notes had no further finding. Two concrete gaps were accepted and corrected.
The TUI exit monitor now reports the original watcher failure even when
the drive's cleanup fails; a real watcher test went red then green with
persistent runtime-close failure. The stopped watcher remains owned for a
later cleanup retry. The workflow coverage property now rejects job/step
`continue-on-error` and common shell success overrides; twelve mutation
cases went red then green. A separate independent S6-S8 read-only pass
rechecked the settled watcher/Summon code and the TUI fix and found no further
blocker. No theory reconsideration was requested.

2026-09-28, independent search implementation review: F1/F2 found stale
doctor and persistence spec references to the removed three-queue search
model; corrected to pending-only. F4 requested real SQLite proofs for
duplicate processing and same-revision changed content/thread; these were
added. F5/F6/F7 removed a duplicate import, a production-dead fallback
read, and hard-coded projection literals. F3 was accepted as a plan wording
error: per-drain cached handles can grow with threads, while measured
physical connections stay flat. F8's oldest-first legacy queue move is
recorded in the deviation log under the quiescence precondition. The reviewer
found no code correctness failure or theory reconsideration.

2026-09-28, independent MCP implementation review: no blocking finding. F1
(malformed spec prose), F2 (duplicate timeout decorator), F4 (resource-read
burst should exercise concurrency), and F5 (interrupt should arise from a real
object's `__repr__`) were accepted and corrected in their owned files. F3
(restore a SHA-256 oracle for the whole instruction string) was declined:
[MCP-9] requires the same advisory instructions across discovery surfaces,
not byte-stable wording. The protocol test checks 20 contract-bearing phrases
in the returned instructions, so a full-text digest would turn harmless prose
edits into test failures without proving agent behavior. The local-render
interrupt test did not itself satisfy S5's separate action proof, so an
isolated driver now runs the real action subprocess, receives its SIGINT, and
proves `KeyboardInterrupt` reaches the capture caller without signalling the
pytest process. The two focused interrupt tests pass.

2026-09-28, owner-requested revision after further feedback: S3 now retains
indexed point probes and measures after handle/registry fixes; the mandatory
range scan and its acceptance condition are removed. S6 specifies firing
behavioral failure cases and TUI-visible original causes with generation guards.
S10 adds targeted effective workflow coverage and Summon-removal mutation proofs.
SQLite pre-open optimization is declined in both projects, with no follow-up.
These decisions supersede the earlier range-scan design and the round-1 TUI
observation below. Prior review verdicts apply to their recorded revisions.

Independent scoped re-review of this revision: **NO BLOCKER**. The reviewer
verified measurement-first S3, S6's firing behavioral cases and owned TUI cause
transfer, targeted effective CI coverage, and the closed pre-open decision.
No THEORY-5.A1–A6 policy was reopened; no active range-scan requirement remains.

2026-09-28, round 1: Claude Opus 5.5, read-only CLI, complete plan and theory
alternatives supplied. Exit 0, `is_error=false`, `stop_reason=end_turn`.
Verdict BLOCKED pending the following plan corrections (no implementation).

| ID | Finding | Disposition |
|---|---|---|
| F1 P1 | S6 also changes Summon; SUM-5.4 and recovery/proof omitted | Accepted: D4 explicitly changes SUM-5.4; S6 tests real reactor failure and restart for the same member; no new recovery mechanism |
| F2 P2 | Existing topology fatal propagation does not surface dispatch errors | Accepted: S6 specifies a chat-only original-exception bridge and cleanup precedence; native test reviewer independently verified the seam |
| F3 P2 | Current schema probe could bypass projection refusal | Accepted: S2 explicitly validates projection before returning; this was added while review ran; test future projection as well as schema refusal |
| F4 P2 | Abandoned delivery transport can strand reactor pending gate | Accepted: S8 checked injection retirement clears gate without cursor advance and tests successor redelivery |
| F5 P3 | No provider API supplies existing index location | Accepted: remove that unsupported hint rather than add an API |
| F6 P3 | has_pending duplicates already available metadata query | Accepted: derive boolean from existing latest timestamp and membership |
| F7 nit | MCP server error-code translation omitted from surface | Accepted: server.py added while review ran |
| F8 nit | Doctor skipped/null state has no prerequisite | Accepted: remove invented skipped state |

No THEORY-5.A1–A6 reconsideration condition was found. Existing Summon upgrade
entry-point limitations and pre-upgrade doctor visibility are not new projects.

2026-09-28, round 2: independent native implementation-review agent checked
accepted corrections F1–F8 against code. Verdict: READY FOR IMPLEMENTATION
PLANNING, no remaining blockers. Verified the original-exception dispatch
bridge, Summon restart recovery and injection-gate retirement, projection
validation inside the provider probe, metadata-only unread projection, actual
upgrade entry points, and removal of unsupported hints/doctor states.
This is plan approval, not implementation or platform qualification.

Fresh-eyes author pass: checked the ten slices against the owner exclusions,
the exact deltas and all accepted findings. Corrected the MCP context table and
made upgrade entry points explicit. No mixed-version, quarantine, lease,
index-rebuild or generic recovery mechanism was reintroduced.

<details>
<summary>Independent round-1 report (verbatim; dispositions above govern)</summary>

**Verdict: BLOCKED** on F1, F2, F3 and F4.

I read the code at the baseline, the retained spec text for [SRCH-6.2], [TAUT-8.4] and [SUM-5.4], and the installed SimpleBroker watcher, to see how handler errors travel. These parts hold up and have no findings: S2's upgrade order (move claimed rows back to pending, then delete the queues, then one provider transaction), commit-before-delete with duplicate processing, S1's revision-first fast path, S5, S6's single read identity, and S7's claim removal.

## Findings

**F1 — P1 — S6 / D4 / D5; `extensions/taut_summon/taut_summon/_reactor.py:35,60`; `docs/specs/04-summon.md:298-300`**
- **Defect:** `SummonReactor` subclasses `TautWatcher`, and its `_begin_delivery` runs through `TautWatcher._make_taut_handler` (`taut/watcher.py:2197-2226`). So S6's fail-stop also changes Summon.
  - [SUM-5.4] says "malformed delivery and user-handler failures retain the existing poison policy". D4 and D5 leave that sentence in place, and S6 never runs the Summon suite.
  - After S6, an ordinary exception from `_prepare_injection` / `format_injection` stops the Summon owner. A restart delivers the same unread record again and fails again. The explicit-replay recovery D4 relies on does not exist for an agent's cursor.
- **Disposition:** Decide explicitly. The recommended option, matching the accepted scope, is that Summon inherits fail-stop:
  - Add [SUM-5.4] replacement text to the delta.
  - Name the operator recovery for an agent member.
  - Add a real `SummonReactor` handler-failure test to S6 and the Summon suite to its gate.

**F2 — P2 — S6 bullet 3; `taut/watcher.py:1616-1625, 1878-1881`**
- **Defect:** The plan says to "reuse existing fatal-owner propagation". That mechanism only covers topology transactions (`watcher.py:835-897`), not message dispatch. At the real seam:
  - If the error handler returns `False`, SimpleBroker raises `StopWatching` (`simplebroker/watcher.py:665-668`). `run_until_stopped` swallows that at line 1878, so a handler failure becomes a silent clean exit.
  - If the error handler raises, the caller gets SimpleBroker's private `_ErrorHandlerFailure` plus an ERROR log line, not the user's exception.
  - Either obvious implementation breaks D4's "surfaces the failure".
- **Disposition:** Specify the mechanism:
  - The Taut handler records the original exception on the owner, and the error handler returns `False` for it.
  - `run_until_stopped` / `run_forever` re-raise that recorded exception after `_finalize_run`, keeping any cleanup notes.
  - `StopWatching` / `WatcherRejected` still end cleanly.
  - Tests assert the exact user exception type.
  - Also say whether a notification-handler exception stops the watcher too. D4 only covers chat, but both queue types share the default error handler (`watcher.py:2140`).

**F3 — P2 — S2 bullet 2 / D1 [SRCH-6.2] insert; `taut/search/_sqlite.py:137-158`, `extensions/taut_pg/taut_pg/_search.py:123-143`**
- **Defect:** `schema_version() -> int | None` returns only the schema version. The retained [SRCH-6.2] text (`06-search.md:372-381`) requires refusing a newer *projection* version before any mutation, and both providers check it today. With the new no-DDL fast path for a current schema, a store with a newer projection would be accepted and written with the old projection.
- **Disposition:** Have the probe return both stored versions (for example, a tuple). Refuse a newer or unsupported projection before any work moves or DDL runs. Keep a test for that refusal.

**F4 — P2 — S8 bullet 1 / D5 [SUM-11]; `_reactor.py:50-53, 110-139`; `_driver.py:1242`**
- **Defect:** The delivery transport and its gate (`_delivery_pending`, `_delivery_cursor`, `_delivery_thread`) belong to the reactor, which outlives generations.
  - Fetching is blocked while a delivery is pending (`_reactor.py:110-118`).
  - Only `_apply_delivery_result` clears that state. It deliberately consumes results from a stale generation to clear the gate without advancing the cursor (`_reactor.py:125-139`).
  - If "retired transports are not consumed by the successor" applies to delivery results, the gate stays set and the reactor never fetches chat again.
- **Disposition:** State that retiring a generation also retires the reactor's in-flight delivery: a checked join of the inject worker, clearing the pending state without advancing the cursor, then `_mark_pending_messages_prechecked`. Alternatively, limit S8's transport change to pump results. Add a turnover-during-injection test where the successor delivers the same record again.

**F5 — P3 — S3 bullet 1**
- **Defect:** "any existing index location" is used as a hint, but `SearchProvider` (`taut/search/_provider.py:51-121`) has no way to look up a document's thread. It only has `applied_revision`.
- **Disposition:** Drop that phrase, or list the new provider method for both backends in S3.

**F6 — P3 — S6 bullet 2; `taut/client/_threads.py:378-383, 449-454`**
- **Defect:** `_thread_from_row` already computes `latest_pending_ts`. In count-free mode, `unread` is exactly `latest_pending_ts > last_seen_ts`. `Queue.has_pending` adds a broker query nothing needs.
- **Disposition:** Derive `unread` from the value already computed.

**F7 — nit — S4 edit surface**
- **Defect:** `RATE_LIMIT_CODE = -31999` and its mapping live in `extensions/taut_mcp/taut_mcp/server.py:44, 208-212`, which isn't in the context table.
- **Disposition:** Add it there.

**F8 — nit — D1 [DOCT-4.6]**
- **Defect:** "When skipped, pending is null" — `search_work` has no prerequisite check at baseline (`taut/_doctor.py:270-293`).
- **Disposition:** Name the prerequisite, or drop the sentence.

## Observations (not actionable this pass)

- **Summon upgrade trigger:** Only the Summon driver and controller (`controller.py:233,242`) and logical load run `ensure_summon_schema`. The passive `validate_summon_schema`, used by dump and extension validation, refuses a v3 ledger under v4 code with "upgrade taut-summon". This is the same pre-existing pattern as v2→v3. The plan's "run normal schema initialization" has no Summon entry point besides running summon.
- **Doctor before the first upgraded search:** On an old store, doctor reports only pending work until a new-version search runs, so legacy claimed rows don't show. This is informational only and allowed by the pending-only contract.
- **TUI:** Under fail-stop, an ordinary TUI handler exception ends the background watcher thread (`taut_tui/session.py:398-439`, degraded path). The traceback goes to `threading.excepthook`. This is within the accepted fail-stop policy.
- **Oversized messages (pre-existing):** For a chat record over `MAX_MESSAGE_SIZE`, SimpleBroker `_dispatch` calls the error handler without ever calling the Taut handler (`simplebroker/watcher.py:1090-1106`). Under fail-stop this record would stop watch every time. It is unreachable given the matching write limits.

## RECONSIDERATION REQUESTED

None. No reconsider condition in THEORY-5.A1 through A6 has fired.

</details>

## Execution Log

- 2026-09-28: Final verification after the suppression-free refactors and
  documentation corrections: root non-slow/non-wheel suite and its 28
  installed-wheel tests passed; full TUI, Summon, Summon driver, and MCP
  suites passed with only their documented platform or PostgreSQL skips.
  PostgreSQL extension suite passed 49/49 against ephemeral PostgreSQL 18;
  the 10 MCP PostgreSQL cases also passed against the canonical runner.
  Root, TUI, Summon, MCP, and PostgreSQL Ruff, format, and mypy gates passed.
  `git diff --check`, documentation path and plan-index checks, the parsed
  workflow/doc/Ruff-policy tests, and suppression-index `--check` passed.
  The PostgreSQL containers were removed by the runners. Windows-native
  paths were not exercised on this macOS host. The worktree remains
  uncommitted, so this active plan is not claimed as landed.
- 2026-09-28: Implementation started at baseline `4a825b69d20c912e23c38bd4ca39ab62dace2c91`.
  Plan status is active. Search lease removal permits duplicate concurrent
  processing; provider revision fencing prevents stale writes. Summon result
  ownership is generation-local, and checked worker retirement prevents a
  failed old owner from starting a successor. These are the required storage
  and owner comprehension checks before code edits.
- 2026-09-28: S10 workflow gate: new parsed-command coverage test first failed
  because root CI's mypy command omitted Summon's excluded `conftest.py`.
  The workflow now names it explicitly; three targeted coverage/mutation
  tests and the 31-test workflow module pass. S6 CLI read test first found the
  rename/reused-name cursor defect, then passed with a bound member ID.
  Count-free list tests cover core and JSON/quiet CLI; reader and CLI suites
  passed locally. S10 cleanup-note test first failed and now passes.
  This is a partial checkpoint, not slice completion or release qualification.
- 2026-09-28: S1/S3 SQLite benchmark used 100 queued jobs and 1, 10, and
  100 registered threads. Operation-scoped persistence held physical
  connections at one across warm and deletion-heavy cases; transient mode
  used four warm and six deletion-heavy connections in each thread-count
  case. Registry reads were one for warm work and three for deletion-heavy
  work across the search call. Deletion-heavy exact-ID probes were 101, 1,010,
  and 10,100, with observed elapsed times of about 0.048, 0.088, and 0.366
  seconds in transient mode. A sparse 100-thread/100-job deletion input cost
  10,000 point probes and about 0.317 seconds. The residual indexed probe cost
  is explicit; no range scan was added without comparative measurement.
- 2026-09-28: Applied the owner's four follow-up revisions to this plan only.
  Re-ran plan-index and doc-path gates, `git diff --check`, and documentation
  reference tests (15 passed). Product/workflow tests remain implementation
  gates, not evidence claimed by this planning edit. No source, active spec or
  workflow changes were made; the plan remains uncommitted.
- 2026-09-28: Plan authored against the pinned baseline after source-backed
  reassessment. Source code/spec implementation changes have not been made by
  this planning task. The report's unavailable numeric artifacts are not used
  as acceptance thresholds.
- 2026-09-28: Documentation verification passed: `uv run bin/check-plan-status-index`,
  `uv run bin/check-doc-paths`, `git diff --check`, and
  `uv run --extra dev pytest tests/test_docs_references.py -n 0` (15 passed).
  Changed deliverables are this plan, its index row and the required independent
  reviewer capability-probe record in the agent inventory. No product tests run
  or product behavior changed. Files remain uncommitted.
- Planning/reviewer skill evaluation: brainstorming-to-plan supplied explicit
  scope, delta and proof boundaries; call-agent supplied a contained independent
  review. Neither needs a task-specific process extension. Reuse the existing
  review disposition table rather than introduce another tracking system.

## Parent-Slice Implementation Review (2026-09-28)

Read-only Claude Opus 5.5 reviewed the exact S6 read/list, S9 TUI and S10
CI/cleanup delta at baseline `4a825b69`. It returned `blocker: F1`; completion
signals were success/end_turn/completed, with no reviewer write. Its findings
were checked against live code, not treated as automatic scope changes:

| ID | Claim | Disposition |
|----|-------|-------------|
| F1 P2 | Cleanup notes were only exercised through a helper; real client and watcher two-resource close paths dropped the later failure. | Accepted. Both owners now add a note while retaining each resource's retry flag. Replaced helper-only proof with a real client close test and extended the watcher close test. |
| F2 P2 | Command-path leave/delete tests mocked confirmation and deletion instead of proving a user-visible destructive outcome. | Accepted. Replaced the mock test with live Textual command-line confirmation and real SQLite leave/delete outcomes. |
| F3 P2 | Public `mark_seen()` was unused and still re-resolved a name at acknowledgement time. | Accepted. Removed the undocumented method introduced for the CLI adapter; CLI now uses only the bound-ID private seam. Compatibility cost is called out in CHANGELOG. |
| F4 P3 | `FormControlSpec.control_id` was unread metadata after focus-order removal. | Accepted. Forms keep only the variable submit label; the screen owns fixed control IDs and Cancel wording. |
| F5 P3 | Five confirmation paths still repeated registry lookup, formatting, and modal setup. | Accepted. The existing `_confirm_command` owner now handles optional cancel behavior; context, delete, Summon dismiss and dump delegate to it. No generic command engine was added. |
| F6 P3 | Old Ruff/mypy substring assertions remained beside the new effective-coverage property. | Accepted. Removed the brittle assertions. |
| F7 nit | The static-coverage helper repeated Git discovery and mypy parsing and left Ruff exclusions implicit. | Accepted. One tracked-file snapshot and one parse collect explicit files; the test fails if Ruff exclusions are introduced without updating the resolver. |
| F8 nit | Count-free list proof covered unread=true only. | Accepted. The same real client test now checks caught-up unread=false with body peeks forbidden. |

Observations: the transcript teardown guard is owned by S6 TUI integration;
the extra mention-reply list count was a cheap S6 hot-path hit, so it now uses
count-free list with a firing CLI test. The CHANGELOG's cross-slice claims are
subject to final combined review. No [THEORY-5] reconsideration was requested.
