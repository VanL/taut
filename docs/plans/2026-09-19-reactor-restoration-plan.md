# Reactor Restoration and Wakeup Audit

Class: 5. Restoration crosses asynchronous ownership, signals, dependency and
lifecycle contracts, and corrects spec text that codified drift. Hardening
applies. This is restoration of the intended design, not a new reactor proposal.

Status: completed for the reviewed implementation on 2026-09-23. Native Windows
and Linux qualification remains a separately recorded platform limit.

Plan type: implementation with spec revision. Each runtime slice began with its
own concrete ownership/source audit. The final slice repeated the repository-wide
scan. Checked boxes below record implementation/inspection evidence, not a
claim that every platform has been qualified. Earlier open-state notes remain as
historical checkpoints; the closeout at the end is authoritative.

Addendum A (end of file, 2026-09-22) supersedes the serial source-recovery
items in S0-Summon and S3c and removes residual failure armor. Addendum B
records this follow-up implementation, independently evaluated cruft findings,
and the correctness/scheduling debt found at that checkpoint. Addendum C
supersedes its open dispositions with implemented corrections and reasoned
retentions; native platform qualification remains separate.

## Goal

Restore the same ownership and wait/turn shape across Taut by replacing the
drifted scheduler with an exact copy of Weft's current `MultiQueueWatcher`
implementation, then keeping Taut behavior in thin subclasses. Adopt the needed
SimpleBroker wakeup fixes and remove only machinery that independently schedules
or observes the same authoritative state. The copied scheduler is the one common
implementation path. Taut changes only the domain policy that differs: retained
chat cursors, membership and cache refresh, Summon delivery, MCP snapshots and
host-loop composition.

## Owner Direction: The Shape to Restore

### Shared Base Concepts

Every audit, spec correction and implementation slice uses the same five concepts:

1. **[BASE-1] One owner per context.** One scheduling owner mutates a context's
   state and drives its bounded turns.
2. **[BASE-2] One wake arbiter per owner.** Every Taut owner with a broker source
   subclasses the shared `BaseReactor`, which in turn subclasses an exact copy of
   Weft's `MultiQueueWatcher`; its retained `PollingStrategy` is the arbiter. A host
   loop such as asyncio or Textual is the arbiter only for an owner with no broker
   source. A peer Event/select/poll wait is not another allowed shape.
3. **[BASE-3] Three arbiter-observable inputs.** `PollingStrategy` observes only
   a backend hint, its local latch and a deadline. A backend hint is confirmed
   against real queue state. Local code publishes authoritative state and then
   calls `notify_activity()`. A deadline exists only for clock work or the
   absence of an event. A wake is coalesced and carries no payload or authority.
   In native mode, a notification raised during one waiter call is observed after
   that strategy pass, which is bounded by `max(delay, burst_sleep)` and has a
   quiet cadence controlled by `BROKER_MAX_INTERVAL` (about 100 ms by default,
   before configured jitter). Local responsiveness uses that strategy cadence,
   not a deadline. A product requiring a tighter bound changes the broker interval
   deliberately.
4. **[BASE-4] Four source origins.** Broker activity is observed directly by the
   strategy. In-process completion, including a worker result or self-write,
   publishes state and calls `notify_activity()` itself. An operating-system
   source (PTY/pipe, process exit, console read or child sentinel) cannot publish
   itself, so one adapter owns one blocking operation, publishes an immutable
   result and notifies the owner. Clock work or absence is published as a
   deadline. An OS adapter additionally preserves these rules:
   - exit and end-of-stream are separate because descendants may retain pipes;
   - quiet exit remains observable without output;
   - a final result does not prove adapter-thread retirement;
   - blocking reads remain cancellable through the platform-owned mechanism;
   - one owner holds each fd/handle, and the adapter owns no broker, cursor or
     ledger handle.
5. **[BASE-5] One in-flight delivery gate.** While Summon delivery is in flight,
   only control queues count as broker wait activity, and the owner does not
   dispatch an already-active retained PEEK row. The worker publishes its
   immutable result and calls `notify_activity()`; the owner applies that result.
   Success advances the retained-chat cursor. Cancellation is not poison and
   leaves it unchanged. Source/adapter failure leaves it unchanged and enters
   recovery. Existing malformed/user-handler poison policy remains distinct, and
   an already-consumed notification pointer is not replayable.

Multiple physical inputs and bounded adapters are compatible with one owner and
one arbiter. Independent schedulers or observers of the same state are not.
These `[BASE-*]` labels are plan shorthand, not a new normative namespace.
Before runtime work, [BASE-1] through [BASE-4] are promoted into [TAUT-8.5] as
the shared reactor/source contract. [BASE-5]'s delivery/cursor rules are promoted
into [SUM-5.4]; [SUM-9] cites them for control sharing and responsiveness. Both
cite [TAUT-8.5]. [MCP-8] and [TUI-4.1] cite the core contract and state only their
composition-specific ownership.

The two axes map to the one reactor path as follows:

| Source origin | Who publishes or observes it | Arbiter input | Weft/Taut examples |
|---------------|------------------------------|---------------|--------------------|
| Broker | The retained strategy observes backend readiness and the owner confirms real queue state. | Backend hint | Weft task queues; Taut chat, control, notification and `taut.cache_stale` queues. |
| In-process | The code that finishes the operation first publishes authoritative state, then calls the retained strategy's `notify_activity()`. | Local latch | Weft worker result; Summon injection result; MCP frontend command. |
| Operating system | One adapter owns one blocking operation, publishes an immutable result, then calls `notify_activity()`; the owner applies it. | Local latch | Weft interactive pipe/process adapters; Summon PTY, console and quiet-child adapters. |
| Clock | The owner computes the next due time for timed emission or absence detection. | Deadline | Weft service deadlines; Taut retry, pacing, shutdown and true-retirement checks. |

This is the conceptual identity to preserve. The four origins do not create four
schedulers. They collapse into the copied watcher's three observable inputs, and
that watcher returns control to the single owner turn that drives all domain work.

**Summon manages one context through one reactor after its identity and queues
exist.** Chat, control, readiness, provider lifecycle and shutdown are work of
that owner under [BASE-1] through [BASE-5]. The current separate chat watcher and
control reactor solve the real problem of synchronous injection blocking control.
Replace them only after one bounded injection worker and a cursor-aware owner
continuation preserve that property. Native transport, PTY/process and attach
helpers remain source adapters when they own only their blocking operation and
publish a result. Do not add a broker-free parent strategy, another supervisor or
a nested Summon reactor.

**MCP repeats [BASE-1] through [BASE-4] because it manages multiple contexts.** Each
workspace is a `BaseReactor` subclass over its notification and cache-stale broker
sources. Frontend commands publish to its local command queue and notify the same
retained strategy. The process owner consumes the workspace's immutable events
and never opens or observes a child database or broker queue. Because that outer
owner has no broker source, asyncio is its arbiter. `_wake_master()` is the local
publication notification from child to host loop; `_maintain()` is the parent's
clock for draining before quiet-exit/liveness inspection. Its nesting exists
because it manages multiple contexts. Do not generalize that exception into
nesting for single-context hosts.

Textual/asyncio and native I/O follow [BASE-2] through [BASE-4]. The
TUI has one live broker watcher for its active conversation; Textual owns
presentation and consumes published results. A blocking I/O worker, one-shot
join observer or bounded cancellation adapter is not another reactor if it owns
only its operation, publishes its result and returns. Every retained helper
needs that concrete explanation.

The expected direction is subtraction. Net lines and thread counts are useful
review evidence, not quotas. Do not remove cursor safety, source coverage or
cleanup ownership to make the diff smaller. Do not build an event bus, source
registry, generic reactor framework, global listener manager or second retry
policy to enforce a common shape.

### Exact-copy and subclass boundary

Reviewed compatibility exception (2026-09-22 implementation audit): retain
Taut's two-line rejection of `yield_strategy != "round_robin"` before broker
I/O in the copied constructor. Taut 0.9.8 expressly promises this rejection;
upstream silently accepts the unused value. Do not add a wrapper to preserve
it. The reproducible comparison may normalize only that exact hunk; all other
class bodies remain identical. Module-level target resolution remains a shim
so an explicit target never resolves unrelated cwd configuration.

The scheduler block from `QueueMode` through `MultiQueueWatcher` is replaced as
one unit from Weft's pinned current source. Its class and method bodies stay
identical. Taut supplies only module-level import, constant, target-resolution
and default-error-handler shims needed by that copied block. Record the upstream
commit, path, copied-block digest and reproducible source-comparison command in
the execution log. Do not add a sync framework solely for this copy. Later
scheduler edits must first be made in Weft or explained as an explicit divergence.

`BaseReactor` remains the thin Taut lifecycle template above that copied class.
It owns one non-reentrant turn/wait loop, deferred signal state and cleanup. It
does not reimplement broker waiting, waiter replacement, broker-session ownership
or queue caching. Those remain inherited from the copied scheduler. Because its
custom turn loop does not call the copied `MultiQueueWatcher.run_forever()`, it
must enter and leave the copied watcher's topology-owner scope around that loop,
including its existing reservation, mutation-failure and waiter-retirement
rules. This narrow owner-lifecycle bridge is required for dynamic Taut membership;
it must not become a second topology guard. Domain behavior remains below it:

- `TautWatcher` owns retained chat cursors and membership refresh;
- Summon owns its one-delivery in-flight policy and OS adapters;
- MCP workspace reactors own observational snapshot/cursor policy and frontend
  command publication;
- one-shot control requesters own only their reply queue and deadline.

Do not copy Weft `BaseTask`: its TaskSpec, state, control and reserved-queue policy
belong to Weft. Copy its final-template turn shape only where `BaseReactor` needs
the same owner rule. Do not introduce another scheduler, generic event bus, source
registry, supervisor or delivery framework.

### Reuse gate

Before prescribing code outside that boundary, name the existing SimpleBroker
public primitive, copied Weft mechanism or Taut hook to reuse, the old
machinery it replaces, and the concrete gap that remains. New machinery is a
warning sign. Compare subclassing, adapting domain policy or deleting compensators
first. Any new mechanism needs evidence that the shared path cannot preserve the
required behavior and independent review of that narrow necessity.

## Source Documents and Spec Baseline

Taut baseline: `70ac379e2ed31b947d0928b57c4bdf94f42a4b61`.

- `docs/program-theory.md` [THEORY-1] through [THEORY-5]: queue is history,
  consumable notification pointers, no required daemon; Taut owns chat and
  SimpleBroker owns durable broker mechanics.
- `docs/specs/02-taut-core.md` [TAUT-3.4], [TAUT-8.4], [TAUT-8.5], [TAUT-11],
  [TAUT-12.3]; `docs/specs/03-identity-addressing-notifications.md` [IAN-6.1],
  [IAN-7].
- `docs/specs/04-summon.md` [SUM-5], [SUM-7.1], [SUM-9], [SUM-11], [SUM-12],
  [SUM-13]; `docs/specs/05-taut-mcp.md` [MCP-3], [MCP-4], [MCP-7], [MCP-8],
  [MCP-12]; `docs/specs/10-taut-tui.md` [TUI-4.1], [TUI-6], [TUI-11], [TUI-12].
- `docs/implementation/04-taut-architecture.md`,
  `docs/implementation/05-taut-summon-architecture.md`,
  `docs/implementation/07-taut-mcp-architecture.md`,
  `docs/implementation/12-taut-tui.md`, and
  `docs/implementation/02-repository-map.md`.
- `docs/plans/2026-07-01-taut-watch-runtime-plan.md`,
  `docs/plans/2026-07-10-taut-dynamic-native-waiter-replacement-plan.md`,
  `docs/plans/2026-09-15-broker-session-integration-plan.md`: preserve runtime
  isolation, live waiter ownership and owner-thread cache retirement, not every
  historical loop introduced to achieve them.
- Active overlaps: `docs/plans/2026-09-15-reported-issues-followup-plan.md`,
  `docs/plans/2026-09-16-windows-lifecycle-determinism-plan.md`,
  `docs/plans/2026-08-25-semantic-compatibility-hardening-plan.md`, and
  `docs/plans/2026-08-24-extension-seams-process-containment-coverage-plan.md`.
  Reconcile actual implemented state before editing; inherit cancellation,
  generation and native-retirement constraints without reopening unrelated work.
- SimpleBroker `v8.4.0`, `28cc4730a6b7e30d674045d0d226090046bac729`:
  [SB-API-6](https://github.com/VanL/simplebroker/blob/28cc4730a6b7e30d674045d0d226090046bac729/docs/specs/16-python-library-api.md),
  `simplebroker/watcher.py`, `examples/reference_reactor.py`,
  `examples/multi_queue_watcher.py` and their tests. Functional fix `bdbacf3`;
  prior lock-free signal fix `d69b6a3`. Private source is inspection evidence,
  not a production import. Inspection of the released PostgreSQL 4.4.0
  `build_retrieve_query(..., operation="claim")` path found that it commits
  `claimed = TRUE` without emitting `pg_notify` for the source queue, while
  inserts and destination moves do emit queue activity. F12 records the narrow
  observable consequence; Taut neither patches nor privately imports the backend.
- Weft exact-copy baseline `9fc913c1` (release 0.9.105, published):
  `weft/core/tasks/multiqueue_watcher.py`. Read the pinned source from the
  Weft checkout with `git show 9fc913c1:weft/core/tasks/multiqueue_watcher.py`.
  This advances the prior `8bcf294b` baseline (deferred-SIGINT lock-reentrancy
  fix) with owner-thread topology mutation between dispatch passes ([QUEUE.8],
  Weft plan `2026-09-21-owner-thread-topology-mutation-plan.md`), which resolves
  F15 upstream. Weft 0.9.106 (`cfa5bb21`, the maintenance-worker change) does
  not touch this file: its whole-file digest is identical, so the `9fc913c1`
  pin remains exact at the current Weft release. Weft records this pin and
  digest in its [QUEUE.8] implementation mapping and has committed to noting
  any change to the file in its CHANGELOG. Earlier source milestones:
  restoration `4370bb0f`, interactive-child correction `54874c2f`, rebased
  minimal interactive-source integration `e6023028`, idle-clock/sampling follow-up
  `22913dee`, and the [CC-2.2.1] adapter-contract spec commit `ff95a4d1`. Compare from
  Taut's attributed vendor revision `7612e972a75806b8165dbf18e6bbfcbb686f27ea`.
  The pinned whole-source-file SHA-256 is
  `3afa84fc7998644cc63d40374fad9326236b73ba3e408a86086a6dc33089da89`
  (previous pin `8bcf294b`: `72274ae1…`).
  Record and explain any newer source revision before using it. The copied
  scheduler block is an implementation source, not a runtime dependency.
  Consumer worker-lane change `73e4c74f` and wait-activity filtering follow-up
  `9f690a11` are the direct in-flight-delivery comparison points.
- Consulted process guidance: AGENTS, context README, decision hierarchy,
  principles, engineering principles, required lessons, writing-plans,
  hardening-plans, testing-patterns, writing-specs, adversarial acceptance and
  review-loop runbooks; `skills/debugging/SKILL.md`,
  `skills/brainstorming-to-plan/SKILL.md`, `skills/call-agent/SKILL.md`, and
  `docs/implementation/03-agent-inventory.md`.

Promotion baseline: not established. Record a commit or baseline SHA plus exact
spec diff after the reviewed corrections are promoted and before code.

## Evidence and Upstream Limits

| ID | Finding | Required action |
|----|---------|-----------------|
| F1 | Core `BaseReactor.wait_for_activity` does not pass its remaining budget to the strategy. With real reactor/8.4 strategy and a quiet native-waiter double, a 20 ms request took 1.46 seconds. | Restore native deadline propagation and remove the extra 10 ms Event tier. |
| F2 | Core does not consume/service local strategy hints correctly with empty broker queues. Pre-latched wake took 1.26 seconds and left its drain hint unconsumed. | Restore authoritative local-state handling without fabricating queue backlog. |
| F3 | Core SIGINT calls `Event.set` in the signal frame. Real signal delivery while the Event condition was held deadlocked; subprocess watchdog stack ended at `watcher.py:1046`. | Signal-safe publication; preserve normal unwind and replacement ownership. |
| F4 | Summon signal handler logs and invokes Event/adapter operations; separate supervision waits surround chat/control reactors whose split was introduced to keep control responsive during synchronous injection. | Consolidate only after a bounded injection worker and cursor-aware owner continuation preserve control responsiveness. Prove signal and blocked-operation cancellation before deletion. |
| F5 | MCP directly multiplexes native waiting and a local Event in 10 ms slices. An always-ready test double caused 3.4 million calls in 0.5 seconds during snapshot pacing, but real PostgreSQL/Redis waiters are edge-triggered and live saturation is unproven. | Make each workspace a thin `BaseReactor` subclass over the copied Weft watcher. Notification and cache-stale queues are cursor-aware PEEK sources; frontend commands publish to the local command queue and notify the same strategy. A backend row marks snapshot work pending, and the paced snapshot confirms domain state. Do not build another wait loop or armor against the test double. |
| F6 | Readiness, control replies, release checks, watcher monitors and cancellation loops include both duplicate scheduling and valid bounded source/lifecycle adapters. | Classify each occurrence by owner and authoritative state. Delete only duplicate authorities; retain and explain bounded adapters. |
| F7 | Summon `_driver.py` and `_control.py` total 3,590 lines, and S0-Summon is not complete. | Treat S3 as a gated migration program, not one implementation slice. Split in-flight delivery, control consolidation and lifecycle deletion into separately reviewed steps after S0-Summon supplies exact maps. |
| F8 | Taut retains `_activity_wait_configs()` but lacks Weft's `_queue_counts_as_wait_activity()` filter used by Consumer while work is in flight. That hook filters wait eligibility, pending checks and inactive discovery; it does not remove a retained PEEK queue that is already active or prevent ordinary dispatch. Weft does not expose that gap because its RESERVE lane removes the work row while the worker runs. | Receive the hook with its base-true default through the exact scheduler copy, then use S0-Summon to select the smallest Taut-specific active-turn/dispatch guard for retained PEEK delivery. Prove that a row already active when delivery begins cannot be fetched again before one successful cursor advance. |
| F9 | `TautWatcher` currently performs one cursor-aware `has_pending` per joined thread after each quiet SQLite strategy pass, even when `data_version` is unchanged. | Use the existing data-version-change callback as the SQLite confirmation gate. A quiet unchanged pass performs no per-queue pending queries; add a firing SQL/query-count proof in S2 rather than waiting for S6 measurement. |
| F10 | `ControlClient` sleeps 30 ms and polls its per-request reply queue outside a broker arbiter. | Replace that loop with one persistent `BaseReactor` over the request's one reply queue, using the inherited owned-wait path and public SimpleBroker APIs. The reactor only observes readiness; `read_one()` still consumes the reply. Overall timeout and idempotent retry remain owned deadlines; do not add a requester exception to [BASE-2]. Persistent is deliberate: Weft's probe is non-persistent only because it runs inside its caller's open `session.connection()` on the same thread. `ControlClient`'s sole caller, `SummonController._control_request`, holds no open broker operation, and a retained connection keeps SQLite `data_version` valid so F9 applies unchanged. |
| F11 | `BaseReactor.run_until_stopped()` currently calls `wait_for_activity()` only when `next_wait_timeout()` returns a positive value. Removing the universal inactive-discovery timer without changing that condition would busy-spin. | Restore one shared protected owned-wait body that accepts `None`, always enter it between turns, and keep the public manual wrapper's existing `None` contract. Both paths use the same retained strategy; this is not a second arbiter. |
| F13 | Some authoritative changes can invalidate a local cache without producing activity on a queue the owner already watches. A PostgreSQL membership-topology change writes sidecar state before the new chat queue belongs to the waiter's topology; a notification claim does not notify the claimed source queue. SQLite detects a database-wide `data_version` change, but the copied cursor-aware confirmation finds no new source row for a raw claim or sidecar-only mutation. Refreshing on every such hint would also refresh on unrelated writes. A deadline would be a second poll of present state. | Add one bounded core-owned `taut.cache_stale` broker queue. Any Taut path that commits an authoritative mutation which an existing watcher may otherwise miss writes a coalescing hint after commit. Initial producers are membership-topology changes and notification-pointer claims. Interested reactors retain it as cursor-aware PEEK input and refresh their authoritative cache in the owner turn. The hint carries no authority and creates no new scheduler. See S2b. |
| F14 | Public `client.watch(persistent=False)` builds a watcher whose SQLite queue opens a fresh connection per operation. `data_version` is connection-local, so under F9 such a watcher would never confirm work. Weft hit this with its ephemeral probe. | Carry Weft's existing rule unchanged: a non-persistent watcher with no native waiter confirms pending state at the end of every strategy pass. Keep the public mode and add the firing SQLite test. F10 remains persistent because its caller holds no conflicting open broker operation. |
| F15 | Resolved upstream in Weft 0.9.105 (`9fc913c1`). At the earlier `8bcf294b` pin the copied `_submit_topology_mutation` raised when the drive owner called `add_queue`/`remove_queue`, because the only owner path (deque append, then `done.wait()`) would self-deadlock; `TautWatcher._refresh_memberships` mutates on the owner thread inside `_drain_queue`, so the exact copy would have raised on the first refresh. The pinned revision admits owner mutation synchronously between dispatch passes through the same transaction, rejects owner mutation inside a dispatch pass (a handler) and reentrant owner mutation before effects, and closes removed dynamic queues in the transaction. Weft covers it with owner-thread add/remove/duplicate tests, a nested-reentrancy test and a PostgreSQL native-rebind test parametrized over foreign and owner origins. | No Taut seam over copied private state and no owner decision remain. `TautWatcher` keeps its refresh at the top of `_drain_queue` (outside the copied dispatch-pass flag) and drops `_remove_thread_queue`'s own `queue.close()`, since the copied transaction closes the removed queue. Taut still owns two firing tests Weft does not have: a foreign-thread mutation during a live `BaseReactor` drive (the task-shaped loop, which Weft never runs with dynamic topology), and owner mutations racing stop under that loop. |
| F12 | `simplebroker-pg` 4.4.0 notifies notification-queue inserts but not a successful claim of that source queue. If a second process shares the attached member identity and consumes a pointer, MCP's observational snapshot can remain stale without another event. Atomic claim still prevents duplicate consumption; a later MCP `inbox` call returns only rows it actually claims. | Route normal Taut notification claims through the generic F13 cache-stale publication path. MCP observes that broker hint through the same reactor and refreshes its snapshot. Preserve atomic claim and the rule that one-time handling acts only on records returned by `inbox`. A crash after commit but before hint publication, a raw SimpleBroker claim or a mixed-version writer may leave the cache stale until an event explicitly schedules the affected cache refresh; document that limitation on both backends, with no time bound, instead of adding a timer or changing SimpleBroker. |

The existing 104 watcher tests passed with sibling 8.4 loaded through
PYTHONPATH; six focused MCP tests passed. These are compatibility observations,
not regression proof. Root manifests/lock still name 8.3.1. Reproduce defects
before fixes; do not make those measured durations portable test thresholds.

Load-bearing upstream facts:

1. The 8.4 timeout bounds native waiting, not SQLite's ordinary polling pass.
2. `notify_activity` only latches state. It does not interrupt the waiter call
   already in progress, but the native strategy loops in passes bounded by
   `max(delay, burst_sleep)` and checks the latch after every pass. With the
   default interval, local wake is therefore observed after about 100 ms in the
   quiet case (before configured jitter) without a reactor deadline.
3. A timeout is a maximum wait for actual clock work or absence, not local wake
   or pacing. The always-ready double is not evidence that an edge-triggered
   production waiter needs an anti-hot-loop exclusion path.
4. SQLite same-connection writes need explicit local publication; ephemeral
   connections do not provide a persistent data-version comparison. The copied
   Weft transient-fallback rule is therefore required for public non-persistent
   watchers.
5. PostgreSQL 4.4.0 does not emit source-queue activity for a committed claim.
   That creates no duplicate delivery: broker claim remains atomic. Taut's normal
   claim path therefore emits F13's generic cache-stale hint after commit, just as
   membership-topology mutation does. The hint is advisory: failure between
   commit and publication, a raw broker claim or a mixed-version writer can leave
   a cache stale until an event explicitly schedules the affected cache refresh.
6. A worker's result or final envelope is not proof that its thread has exited.
7. Weft's follow-up had to restore observation of interactive child exit. Quiet
   children and inherited-open descriptors must remain visible without a write.
8. A quiet SQLite strategy pass with unchanged `data_version` is negative backend
   evidence. It must not fan out into per-queue pending queries. Broad discovery
   runs inside a real owner turn or the strategy's own idle safety pass.
9. Weft's current `MultiQueueWatcher` already contains the retained strategy,
   wait-activity hook, hint classification, topology ownership and transient
   SQLite fallback needed here. Re-copying that block and subclassing it is
   smaller and more regular than independently recreating those mechanisms.

A qualifying cache-refresh trigger is a new `taut.cache_stale` row or an
explicit local operation that refreshes that cache. For MCP's inbox snapshot,
a new notification row also qualifies. Unrelated broker traffic, an arbitrary
local wake, a quiet strategy return, or a SQLite data-version change with no
cursor-qualified source row does not by itself require a cache refresh. The
advisory gap has no time bound on either SQLite or PostgreSQL.

## Open Evidence Gates

The following are not established at plan-authoring time. Do not turn the current
fallback or adapter into a permanent requirement, and do not delete it, until its
own S0 gate records backend/platform-real evidence:

- PostgreSQL notification coverage for sidecar writes and source-queue claims is
  closed by inspection: neither supplies every interested owner with an event.
  The answer is the generic `taut.cache_stale` broker hint, not a PG-only
  convergence deadline or workspace freshness timer. Own-connection work still
  publishes local state explicitly when its synchronous result does not already
  refresh that state.
- `keep_newest` is documented upstream as intended for a dedicated
  single-producer queue. F13 uses `keep_newest=1` with several producers for a hint where
  only the newest timestamp matters. S0-core confirms against SimpleBroker's
  spec that concurrent `keep_newest` writers always leave the newest row
  pending, and records the result before S2b.
- The cache-stale event is not transactional with the sidecar mutation or queue
  claim. S0-core records the exact commit-then-hint boundary and its accepted
  stale-until-later-event failure mode. Do not claim a bound the mechanism does
  not provide and do not add repair or a polling backstop.
- Summon's full chat/control/foreground handshake graph. The one-owner direction
  is fixed, but deletion order and exact continuation points remain S0-Summon
  outputs.
- Windows and POSIX PTY/process/attach adapters. Treat them as [BASE-4]
  operating-system source adapters until platform-real tracing proves a duplicate
  authority or a smaller existing mechanism.

## Accepted Observable Differences

| Surface | Current behavior | Restored behavior | Disposition |
|---------|------------------|-------------------|-------------|
| First MCP frontend command after an otherwise quiet native wait | SQLite observes the local Event immediately; PostgreSQL checks it in 10 ms slices. | The command is published and wakes the shared reactor's local latch. If one native strategy pass is already in progress, the owner observes it after that pass: nominally about 100 ms before configured jitter. Once active, the strategy uses burst cadence. | Accepted. This is the same local-event contract as Weft and removes a peer scheduler. MCP currently uses the preconstructed strategy defaults; it did not previously support workspace polling overrides. A future tighter bound belongs in strategy configuration, never a separate command deadline. |
| Peer notification claim and membership-topology mutation | SQLite may notice through database-wide `data_version`; PostgreSQL can leave the relevant cache stale until an unrelated event or periodic backstop. | Normal Taut topology/claim paths write `taut.cache_stale`, and the existing reactor refreshes authoritative state. A crash between commit and hint, raw broker operation or mixed-version caller can still delay convergence until an event explicitly schedules the affected cache refresh. | Accepted advisory-event boundary. Atomic claim and authoritative sidecar state are unchanged; no timer or repair path is added. |

## Invariants Before Deletion

- One context has one [BASE-1] owner and one [BASE-2] arbiter. A broker-owning
  arbiter observes only [BASE-3]'s backend hint, local latch and deadline. A
  higher-level MCP owner gets domain progress from the inner event stream and may
  observe only lifecycle objects/deadlines it owns, not child broker state. Do
  not move a watcher strategy between driving threads.
- Chat uses peek-after-cursor and advances only after successful delivery.
  Summon must not enqueue injection to a worker, return success and advance the
  cursor before that worker actually accepts/completes delivery. Preserve poison,
  terminal rejection, initial-drain readiness and replay semantics.
- Normal watchers consume notification pointers; MCP observes them. Preserve
  their existing crash-loss contract; no fabricated pointer replay guarantee.
- Persistent queue, state and topology operations remain serialized on their
  owner. Closing/recycling a scope must not close a peer's scope or recycle a
  foreign owner's cache. Preserve constructor rollback and exception precedence.
- Signals do no logging, Event/Condition operations, adapter calls, clocks,
  database work, joins or cleanup. Core's existing immediate KeyboardInterrupt
  may remain outside the waiter-replacement critical section; retain its deferred
  raise inside that section. Actual cleanup occurs through normal stack unwind.
- Publish authoritative results, ready/failure/cancel state and retirement before
  notifying. Check state even when hints coalesce or are downgraded. Keep
  pending-queue discovery flags separate from broker-free local activity.
- Control STOP remains responsive during blocked injection/output. It succeeds
  only after required teardown/release evidence. No self-wait or cyclic handshake
  may survive moving formerly separate owners into one reactor.
- Preserve cancellation during bootstrap, attach, orientation, readiness,
  backoff, dispatch and finalization. A change limited to idle waiting fails.
- Preserve generation fencing, one live attempt, checked retirement, original
  readiness budgets, MCP admission/isolation and fairness between work sources.
- Rate audit, pacing, retry, stall and shutdown deadlines remain real obligations.
  Membership and observational freshness use the cache-stale broker source plus
  ordinary queue activity, not a deadline. Carry each valid clock/absence
  deadline through its owner's scheduling path; do not rename an independent
  poll of present state as a timer.
- Keep necessary native I/O/source adapters and bounded operation workers.
  They may publish immutable local results, not operate another owner's broker
  handles or add a supervisory reactor. Preserve non-reaping process identity,
  exclusive terminal readers, fd/handle leases and cleanup bounds.
- No runtime dependency on Weft, daemon, schema migration,
  manager/task protocol, global session/listener singleton or copied broker retry.
  The vendored scheduler is pinned source copied into Taut, with Taut policy in
  subclasses. `taut.cache_stale` is one bounded advisory system queue, not a new
  state store or event framework.

## Full Audit Inventory and Context

The per-slice S0 maps expand this seed into a per-occurrence matrix: file/symbol,
context, current owner, source, authoritative state, publication, deadline, failure path,
consuming/observational mode, intended owner, delete/move/retain and firing proof.
Every retention must explain Taut semantics or a concrete source/OS constraint.

| Files and current machinery | Audit/restoration target |
|-----------------------------|--------------------------|
| `taut/watcher.py`: drifted copied scheduler, `BaseReactor`, `TautWatcher` | Replace the scheduler block wholesale with the exact pinned Weft `MultiQueueWatcher`; keep Taut shims outside the copied class. Make `BaseReactor` the thin final-template lifecycle subclass and keep cursor/cache policy in domain subclasses. Remove the parallel Event wait. Quiet unchanged SQLite passes do no per-queue I/O; non-persistent SQLite uses the copied transient fallback. Membership/cache refresh is driven by `taut.cache_stale` and explicit local publication, never a timer. Preserve owner topology, replacement critical section and scope cleanup. |
| `taut/client/_watching.py`, `taut/_watch_runtime.py`, `taut/commands/watch.py` | Independent runtime, initial drain, public callback semantics, CLI signals/pipe exit. No duplicate watcher or retry. |
| `extensions/taut_summon/taut_summon/_driver.py` | Separate chat watcher, control thread, event pump, readiness 50 ms checks, supervisor 200 ms waits, signals, restart/backoff and acknowledgment handshakes. Restore one reactor for this context; map every lifecycle phase into it. |
| `extensions/taut_summon/taut_summon/_control.py` | Fold driver control policy into the same Summon reactor; delete separate ControlLoop drive/supervision. Keep correlation, rate policy, serial source recovery and release-before-ack. Replace `ControlClient`'s 30 ms polling with one persistent `BaseReactor` over that request's per-request reply queue (F10); do not fold the requester into the driver. |
| `extensions/taut_summon/taut_summon/controller.py` | After a successful STOP reply, confirm committed release once; the driver owner has already established causality. Preserve real failure evidence without a second 50 ms observation loop. |
| `extensions/taut_summon/taut_summon/_pty_posix.py` | Retain settle/attach, Event-to-pipe forwarding, select/read/write deadlines and quiet-child observation as bounded fd/process adapters. They publish results and do not own broker policy. |
| `extensions/taut_summon/taut_summon/_process_domain_posix.py`, `_darwin_wait.py` | Retained leader identity, non-reaping child exit and TERM/KILL deadlines. Do not replace them with reaping Popen.poll or unsafe numeric-PID probes. |
| `extensions/taut_summon/taut_summon/_pty_windows.py` | Retain the native process monitor, output/reply/input workers, cancellable console read and bounded settle/attach waits. Keep required blocking-source isolation and handle lifetimes; workers publish results and own no broker policy. |
| `extensions/taut_summon/taut_summon/interaction.py` | Console read/cancel completion, POSIX input and attach handshakes; include cancellation before a chat watcher currently exists. |
| `extensions/taut_mcp/taut_mcp/_workspace_reactor.py` | Make the workspace a thin `BaseReactor` subclass over the notification queue and `taut.cache_stale`, both cursor-aware PEEK sources. A source row marks paced snapshot work pending; `peek_inbox()` confirms domain state. Frontend command producers publish to the local queue and notify the inherited strategy. SQLite `data_version` triggers cursor-aware source confirmation, not automatic snapshots; after an own-connection command, preserve direct refresh or mark a snapshot pending. Remove the 0.5-second workspace backstop. A pacing deadline exists only while a snapshot is pending. |
| `extensions/taut_mcp/taut_mcp/_process_reactor.py`, `server.py` | Retain multi-context composition and the child-to-parent publication path: a workspace enqueues one immutable event, then `_wake_master()` asks the asyncio owner to drain it. Retain 0.5-second process maintenance as a clock that drains before checking true `Thread.is_alive()` retirement, plus phase deadlines and bounded shutdown. A `call_soon_threadsafe()` `RuntimeError` normally means the loop is closed; do not claim that maintenance on that loop recovers it. Verify late-shutdown handling and that the parent never observes child broker/domain state. |
| `extensions/taut_tui/taut_tui/session.py` | Retain the serialized client worker, independent public watcher runtime and one-shot join observer. The observer publishes true watcher retirement to the session owner and does not observe broker state. |
| `extensions/taut_tui/taut_tui/app.py`, `summon.py` | Retain Textual callbacks, generation fencing, terminal leases and the bounded local confirmation/cancellation adapter. It touches no broker state. S0-TUI may make cancellation resolve the existing request Event if that preserves ordering and is smaller; no cross-package seam is required. |
| `extensions/taut_pg/taut_pg` | Duplicate listeners, pool/scope ownership, sidecar and deletion notification coverage. Reuse the released SimpleBroker public backend boundary; do not issue PostgreSQL notifications directly from Taut. |
| `taut/search`, `taut/persistence`, `taut/terminal.py`, `taut/identity.py` | Include actual background/wait work. Mark bounded synchronous scans as such rather than treating every loop as a reactor. |
| `taut/_scripts.py`, `bin`, `.github`, test fixtures, `scripted_provider.py` | Inventory separately as tooling or controlled stimulus. Preserve intentional delays, watchdogs and release observers; this is not a CI redesign. |

Additional change surfaces: root/MCP/PG manifests, root and Summon/MCP/TUI
retained locks, README, CHANGELOG, source specs, implementation notes, existing
tests and repository map. PG has no retained lock; do not create one.

## Exact Reuse and Taut Specialization Rules

| Upstream idea | Taut disposition |
|---------------|------------------|
| Weft `MultiQueueWatcher` scheduler block | Copy exactly at the pinned source revision. Keep dependency/config resolver shims outside the copied class; verify the copied block against its recorded digest. Delete Taut's divergent broker-wait implementation. |
| Taut `BaseReactor` | Keep as the thin owner/turn template over the copied watcher. Broker-owning core, Summon, MCP and one-shot request contexts subclass it rather than creating direct `PollingStrategy` loops. |
| Taut persistent `BaseReactor` over public SimpleBroker APIs | Use for `ControlClient`'s one-shot per-request reply queue (F10). Weft's ephemeral probe shape is the comparison, but its non-persistent mode is rejected here: Taut's requester holds no open broker operation, so a persistent reactor closes cleanly and keeps `data_version` valid. Timeout and retry are deadlines owned by that requester, not a 30 ms queue poll. |
| SimpleBroker `Queue.write(..., keep_newest=1)` | Use for bounded `taut.cache_stale` publication (F13). Do not build a Taut trimming or cleanup lifecycle. |
| Weft `_queue_counts_as_wait_activity` and transient SQLite fallback | Receive both through the exact copy. Summon overrides only the hook; public non-persistent watchers use the fallback unchanged. The hook does not suppress dispatch from an already-active retained PEEK queue, so S0-Summon pairs it with the smallest owner-turn guard. |
| Cursor-aware PEEK confirmation | Keep it as Taut domain policy below `BaseReactor`. Both subclasses use the same public `peek_many(..., after_timestamp=...)` and `has_pending(after_timestamp=...)` primitives. `TautWatcher` owns chat/cache cursor meaning; MCP owns notification/cache-stale snapshot cursor meaning. Do not change the copied watcher's generic PEEK behavior or add a cursor framework merely to hide those small policy overrides. |
| Results and retirement publish separately | Apply to existing bounded worker/source adapters. Do not import a task-result protocol or supervisor. |
| Interactive-exit follow-up | Preserve the lesson and real quiet-child proof, not necessarily Weft's polling implementation. |
| Foreign-thread topology mutation and session inventories | Adopt with the copy. Taut's drive-owner-only mutation rule, parallel broker session, queue cache and waiter-replacement implementation are deleted by S2 in favor of the copied ownership; the owner-thread membership refresh uses the copied owner-synchronous admission (F15, resolved upstream). Taut retains only its scope/cache lifetime tests as behavior proofs against the new implementation. |
| Head-peek/task backlog semantics | Reject for durable chat cursors; MCP is observational. Reuse Taut's existing policy and prove injection completion before advancement. |
| Manager, heartbeat, PONG routing and task protocol | Reject: outside Taut's chat/domain model. |
| Public manual wait None semantics | Inspect the exact method; Weft internal and public methods differ. Preserve Taut's existing public behavior unless an exact reviewed correction is necessary. |
| Any fix that merely adds a wrapper loop | Reject; solve at the existing source/owner, or name a public upstream capability gap and its required resolution. |

For the copied scheduler record the source SHA, path and copied-block digest.
For every subclass record only the Taut-owned override and why the domain needs
it. Do not describe edits inside the copied scheduler as harmless adaptation.

## S0: Per-Slice Ownership and Source Maps

Audit is a gate for the slice it governs, not a global blocker. Complete
S0-core before S1/S2, S0-Summon before S3, S0-MCP before S4 and S0-TUI before
S5. S6 repeats the repository-wide scan after all accepted slices. Each map
records file/symbol, owner, authoritative state, input, publication order,
deadline, failure path, consuming/observational mode, retain/move/delete and a
firing proof. Retention is the default when a bounded adapter owns distinct
state and no smaller existing seam preserves its obligation.
Every map explicitly dispositions [BASE-1] through [BASE-4]; Summon also
dispositions [BASE-5].

### S0-core

- [x] Confirm SimpleBroker 8.4 signatures and semantics through public APIs.
  Pin the current Weft source revision and copied-block digest. Produce an exact
  scheduler-block comparison, record the command, and list the module-level Taut shims;
  any class-body difference beyond the reviewed yield-strategy guard blocks S2
  unless independently reviewed as a required divergence.
- [x] Map one protected `BaseReactor` notification hook to
  `PollingStrategy.notify_activity()`. It publishes no payload. A notification
  raised during one native waiter call is observed after that bounded strategy
  pass, whose nominal quiet cadence is controlled by `BROKER_MAX_INTERVAL`; do
  not add a reactor deadline for local responsiveness.
- [x] Receive Weft's `_queue_counts_as_wait_activity(config)` hook through the
  copied scheduler rather than designing a second queue-eligibility seam. Its
  base implementation returns true. `_activity_wait_configs`,
  `_has_pending_messages` and broad inactive discovery all use it.
- [x] Map local, native and downgraded/empty-check hint outcomes. Local activity
  returns control without fabricating queue backlog; native activity is confirmed
  against authoritative queue state; every consumed hint is cleared or rebound
  before another wait. In `TautWatcher`, use the existing
  `_on_data_version_change` callback to record the SQLite backend hint. S2b then
  removes the membership refresh from that callback. An unchanged quiet SQLite pass returns to the strategy
  without calling cursor-aware `has_pending` for joined threads.
- [x] Preserve `_pending_messages_precheck_confirmed`,
  `_mark_pending_messages_prechecked`, replacement critical-section safety and
  public `wait_for_activity(None)` behavior unless an exact reviewed correction
  is necessary. Retain the copied `_next_inactive_probe_at` internal throttle for
  broad scans; stop publishing the inactive-probe interval through
  `BaseReactor.next_wait_timeout()` as a universal reactor deadline.
- [x] Trace `run_until_stopped()` before removing that timer. Use one shared
  protected owned-wait body for reactor and public waiting, matching current Weft:
  the drive loop enters it even when the composed timer deadline is `None`; the
  public manual wrapper retains its existing `None` behavior. Both call the same
  retained strategy and hint classifier.
- [x] Separate inactive queue discovery from cache convergence. Broad
  inactive discovery runs within a turn supported by a backend/local hint or by
  the strategy's own idle safety return; it is not published through
  `next_wait_timeout()`. Membership and other derived caches publish no timer on
  any backend. They refresh when `taut.cache_stale` has a row after the owner's
  cursor and on explicit own-connection publication. Replace [TAUT-8.4]'s
  refresh-interval bound with that event contract.
- [x] Resolve signal observation through the existing deferred pending state and
  normal unwind. A signal frame performs no Event/Condition, logging, clock,
  adapter or resource operation.
- [x] Record F13's closed evidence: no PostgreSQL notification covers a sidecar
  membership-topology write or a source-queue claim. Specify `taut.cache_stale`
  before S2b: namespace ownership under [IAN-6.1], topology and claim producers,
  commit-then-write ordering, `keep_newest=1`, inspection-only payload,
  startup cursor and exclusion from chat projection. Every event means only
  "an owned cache may be stale"; the owner rereads authoritative state. Confirm
  the multi-producer behavior recorded under Open Evidence Gates.
- [x] Carry Weft's F14 transient-fallback rule unchanged for public
  `client.watch(persistent=False)` and name its SQLite firing test. Record exact
  core spec changes and tests before S1/S2.

### S0-Summon

- [x] Draw the current chat/control/foreground graph and the one-owner graph.
  Trace `_halt_ack`, `_shutdown_complete`, injection cancellation, watcher
  readiness/rebuild and STOP reply ordering. Remove only handshakes that become
  owner-local; shutdown requested is not reactor retirement or successful STOP.
- [x] Start from the restored `_queue_counts_as_wait_activity` hook. While one
  Summon delivery is in flight, its override returns true only for the fixed
  control queue. Local worker results are broker-free owner activity: the worker
  publishes an immutable result and notifies, and the owner applies it before the
  next queue turn. Record explicitly that this hook filters wait eligibility,
  pending checks and inactive discovery, but does not remove an already-active
  PEEK queue or stop ordinary dispatch from it. Select the smallest owner-turn or
  dispatch guard that closes only that residual gap.
- [x] Trace existing `_make_taut_handler`, `_advance`, failure/poison policy and
  worker-result hooks before adding any cursor API. The wait-activity hook does
  not itself defer `_make_taut_handler`'s immediate cursor advance. Reuse those
  existing protected methods if they can preserve one owner and one policy. If
  they cannot, record the exact residual cursor-disposition gap and independently
  review the smallest Taut-specific hook; do not prescribe a generic delivery
  seam in advance.
- [x] Add a firing retained-row proof before S3: begin with the chat PEEK queue
  already active, hold one delivery in flight, drive several bounded turns, and
  observe no second fetch or handler call until the owner applies one successful
  result and advances the cursor exactly once.
- [x] Preserve the copied watcher's exact signature behavior. Its waiter signature
  is the ordered result of `_activity_wait_configs()`, so changing Summon's
  in-flight eligibility rebuilds the native waiter when delivery starts and again
  when it finishes. Do not suppress or duplicate that replacement. Backend hints
  for excluded chat/cache queues may still occur while delivery is pending;
  immediately after the owner applies a delivery result, force one broad
  inactive-queue discovery so existing rows do not wait for the strategy's idle
  safety pass.
- [x] Use existing `QueueMode` to identify lanes within the hook: dynamic chat is
  `PEEK`; notification and fixed control are `READ`. Correct membership refresh,
  pending checks and public chat projection to identify chat by `PEEK`, excluding
  the fixed `taut.cache_stale` queue by name exactly as the notification queue is
  excluded today (F13 makes `PEEK` alone insufficient); do not add a role
  registry. While delivery is in flight, the exact broker wait set is the fixed
  control queue only: chat, notification and `taut.cache_stale` are all excluded.
  The forced broad discovery after the owner applies the worker result then
  observes any deferred row. Keep control in the bounded ordinary pass so floods
  cannot starve completion or deadlines.
- [x] Keep the continuous transport pump and bounded injection, settle, attach,
  quiet-child, process and console-read adapters. They publish immutable result,
  failure and retirement envelopes; broker/state/lifecycle policy stays on the
  Summon owner.
- [x] Give every Summon operating-system source a named [BASE-4] adapter or a
  recorded reason why the owner observes it directly: PTY output, PTY end-of-
  stream, quiet child exit, attach input/output, console read and child sentinel.
  For each one prove exit versus EOF, quiet exit, result versus true retirement,
  cancellation, exclusive fd/handle ownership and absence of broker/cursor/ledger
  access. Removing wait caps is not completion evidence.
- [x] With broker queues quiet, prove that a worker completion and a quiet child
  exit reach the owner within one strategy pass under the configured broker
  cadence and jitter, with no application deadline or peer wait.
- [x] Specify serial chat-source recovery: a failed reactor/source turn unwinds;
  the same owner retires the complete source bundle, constructs one replacement,
  preserves the provider generation and original readiness deadline, and never
  drives two instances concurrently. Retry delay is an owned deadline, not a
  supervising loop.
- [x] Keep synchronous bootstrap on the foreground owner until identity/control
  queues exist. Use signal-safe pending state and bounded phase checkpoints.
  Construct the reactor before later blocking adapter phases.
- [x] Store pending STOP correlation (`request_id`, `reply_to`) rather than a
  persistent per-request queue handle. After teardown and committed release, the
  owner creates/writes/closes the transient reply route. A successful STOP reply
  permits one release-evidence read; remove the controller's 50 ms loop.
- [x] Treat `ControlClient` as a separate bounded request context. Replace its
  30 ms `read_one()`/sleep loop with one persistent `BaseReactor` over that
  request's per-request reply queue (F10). The reactor observes readiness only;
  `read_one()` still consumes the reply. The requester owns its overall timeout
  and idempotent-retry deadlines. It is never part of the driver reactor. Prove
  clean reactor close beside the caller's open client session.
- [x] Record exact [SUM-5.4], [SUM-7.1], [SUM-9], [SUM-10], [SUM-11], [SUM-12]
  and [SUM-13] corrections plus the symbol deletion/movement map before S3.

### S0-MCP

- [x] Confirm that MCP has no [BASE-4] operating-system source. Its workspace
   inputs originate in broker state, in-process queues/completions and clocks;
   child-thread retirement is parent-owned lifecycle evidence, not an OS adapter.
- [x] Map inbound `queue.Queue` control, SQLite `data_version`, PostgreSQL native
   readiness, snapshot freshness/pacing, parent event publication, parent phase
   deadlines, immediate `_wake_master()` notification, maintenance-clock draining
   and true thread retirement to their owners.
- [x] Make the workspace a `BaseReactor` subclass, using the same copied Weft
  `MultiQueueWatcher` path as core and Summon. Configure the member notification
  queue and `taut.cache_stale` as fixed cursor-aware PEEK sources. Override only
  the Taut domain operations needed to peek after each in-memory cursor and mark
  paced snapshot work pending; do not add a direct `PollingStrategy` loop or
  modify the copied scheduler's generic PEEK semantics.
- [x] Replace `_Owner.wake` with the retained strategy's bound local-notification
  callback. The process owner may construct the inert strategy and its stop token
  before thread start, pass both into the workspace `BaseReactor`, and retain only
  `notify_activity` for producers; the workspace thread exclusively starts,
  waits, replaces waiters and closes the strategy. `_Owner.send()` enqueues the
  command before calling that callback. A pre-start notification stays latched,
  so bootstrap and send-versus-start races need no Event or readiness handshake.
  Add a firing race test and keep the parent unable to wait on child sources.
- [x] Inbound controls remain authoritative in the local `queue.Queue`; the
  producer writes them and calls the inherited `notify_activity()` seam. The
  reactor turn drains those commands and broker rows, then performs due snapshot
  work. No payload travels through the wake. First idle response is bounded by one
  strategy pass without another deadline; subsequent work uses burst cadence.
- [x] Confirm a notification or cache-stale row by taking the paced `peek_inbox`
  snapshot itself. The two source cursors prevent retained rows from staying
  perpetually ready. Do not call generic `has_pending()` without a cursor, exclude
  the watched queue, rebuild its waiter per snapshot, or add anti-hot-loop state
  for the always-ready test double. Real PG/Redis waiters are edge-triggered; a row
  first marks a snapshot pending and may then advance the source cursor; that
  pending obligation remains until the snapshot succeeds. A pacing deadline delays
  only that timed emission. The row carries no domain authority.
- [x] Record F12's exact boundary in [MCP-7], [MCP-8] and agent-facing notification
  guidance. A normal Taut `inbox` claim writes `taut.cache_stale` after the atomic
  claim commits, so another workspace reactor refreshes. One-time handling still
  uses only records returned by `inbox`. A crash in the commit-to-hint gap, a raw
  SimpleBroker claim or a mixed-version caller may leave the cached pointer visible
  until a source row or command explicitly schedules the snapshot; there is no duplicate claim and no freshness timer.
- [x] On SQLite, `data_version` triggers cursor-aware source confirmation; it
  does not itself require a snapshot. A raw or mixed-version peer claim can
  change `data_version` without leaving a row after either source cursor, so
  the copied watcher continues waiting. The advisory gap applies on SQLite
  and PostgreSQL alike. Prove normal peer-claim freshness through `taut.cache_stale`
  on both backends, and prove the no-hint case stays stale until a source row or
  command explicitly schedules the snapshot. Do not add a refresh on every
  database change or a second polling path.
   Current `_execute_command()` already calls synchronous
   `_refresh_after_command()` for every command except non-mutating `channel_show`.
  Preserve that own-connection confirmation; if S4 folds it into the paced
  snapshot path, mark the snapshot pending immediately after command completion
  and confirm it before re-waiting. Do not retain a timer to discover the
  workspace's own writes.
- [x] Split the two jobs currently hidden behind
  `NOTIFICATION_BACKSTOP_SECONDS`. Remove the unconditional child snapshot
   deadline on both backends after SQLite publication proofs pass. Retain a pacing
   deadline only after a real hint has made a snapshot pending; when no snapshot
   is pending, pacing contributes no deadline. A quiet native idle-safety return
   and a quiet unchanged SQLite pass perform no MCP snapshot query. F12 is
   covered by the cache-stale broker source plus the explicit exceptional gap,
   not periodic confirmation.
- [x] Retain the child-to-parent path: `_emit()` publishes an immutable event to
  the parent queue, then `_wake_master()` uses `call_soon_threadsafe()` to request
  an immediate owner-thread drain. Retain process `_maintain` as the parent's
  clock: each maintenance turn drains already-published events before checking
  `Thread.is_alive()` so a quiet child exit is eventually observed. A swallowed
  `call_soon_threadsafe()` `RuntimeError` normally means the loop is closed and is
  not recoverable by maintenance on that loop; replace the current misleading
  recovery comment and prove only the late-shutdown behavior it actually owns.
  Retain bounded shutdown resampling unless a smaller primitive preserves its
  bound. This process clock is independent of workspace notification freshness
  and must not be renamed or reused as its fallback.
- [x] Preserve publication before wake, generation admission, peek-only snapshots,
   cursor initialization, failure-before-publication handling and actual
   retirement. Record exact MCP spec changes and tests before S4.

### S0-TUI and remaining consumers

- [x] Confirm the Textual loop owns presentation, the serialized session worker
  owns its `TautClient`, and one public watcher owns active-conversation broker
  observation. No host adapter may inspect broker state independently.
- [x] Retain `_monitor_watcher_exit` as a one-shot `Thread.join()` adapter that
  publishes true watcher retirement. Retain executor/Future marshalling,
  terminal lease waits and generation fences.
- [x] Retain confirmation cancellation sampling unless the Summon slice first
  proves that the existing cancellation path can resolve the same request Event
  directly with the same ordering. The current 50 ms Event wait touches no broker
  state and is a valid bounded local adapter, not an idle broker poll.
- [x] Classify remaining production and tooling occurrences. Do not infer drift
  from `wait`, `poll`, `Event`, `Thread` or timer syntax alone.

Done signal for each map: no unresolved ownership edge, cyclic handshake,
missing source, capability gap or signal-phase question remains in that slice.
Stop that slice if it needs a new dependency, upstream capability or changed
chat promise; record the prerequisite instead of adding compensating machinery.

## Required Comprehension Checks

Implementer writes answers in the execution log before editing. Wrong answers
block editing until the owning source is reread.

1. How many Summon reactors after identity exists? Expected: one for one context.
   Blocking source adapters may publish results; chat/control/supervision are not
   nested reactors. Synchronous pre-identity bootstrap remains foreground work.
2. Why is MCP nested? Expected: multiple contexts. Higher levels derive domain
   progress from inner `BaseReactor` events while retaining parent-owned
   maintenance deadlines and proof of actual child-thread retirement.
   `_wake_master()` requests prompt delivery of already-published events to the
   broker-free asyncio owner; it is not a workspace polling path.
3. What permits a chat cursor to advance? Expected: successful delivery on the
   owning continuation, not enqueueing work or receiving a wake hint.
4. Why not simply delete every timeout? Expected: deadlines and unnotified OS or
   backend state still need coverage in the same owner/source, and pacing is real
   clock work. Local publication needs no timeout: the strategy observes its latch
   within one bounded pass. An always-ready test double is not grounds for another
   scheduling path.

## Required Spec Corrections and Promotion

Promotion strategy A: correct existing spec text before dependent implementation,
without premature implementation-link claims. Add code links with each code
slice. Do not rewrite program theory; this restores its declared boundaries.
The exact D0-D6 text below, including D2a/D2b and split D3a/D3b ownership, is review material
until promotion. The applicable
per-slice S0 supplies exact additional replacements for mechanism-specific
paragraphs and acceptance text; those replacements require review before
promotion, not implementation guesses.

### D0: [TAUT-8.5], replace its first sentence

> `BaseReactor` subclasses Taut's exact pinned copy of Weft's
> `MultiQueueWatcher` and owns the process/wait/request-stop/stop template shared
> by Taut's long-lived queue reactors.

Retain the rest of the first paragraph's owner, non-reentrancy, inspection,
protected-hook and compatibility-alias contract. Remove the claim that
`BaseReactor` derives from SimpleBroker's reference reactor. SimpleBroker still
owns the public wait primitives; Weft is the copied scheduling implementation.

### D1: [TAUT-8.5], replace the first two sentences of "Stop has two stages"

> Stop has two stages. Ordinary owner or foreign-thread `request_stop()`
> publishes stop state and wakes its reactor without joining or closing owned
> resources. Python signal handlers publish plain pending state and use only
> the supported signal-safe notifier; they perform no Event, lock, logging,
> adapter or resource operation. Core synchronous watch preserves immediate
> `KeyboardInterrupt` outside waiter replacement and defers that raise until
> ownership transfer commits inside the replacement critical section. Normal
> stack unwind and owner execution perform cleanup.

Retain the rest of the existing stop paragraph, including finalization,
thread-cache ownership, abnormal cleanup and observable failures.

### D2: [TAUT-8.5], append after polling/activity ownership

> Each context has one scheduling owner and one wake arbiter. Where the context
> has a broker source, the retained SimpleBroker `PollingStrategy` is that arbiter;
> a host loop is the arbiter only where no broker source exists. The arbiter
> observes exactly three inputs: backend readiness, its local latch and an owned
> deadline. Broker readiness is SQLite data-version or PostgreSQL native activity
> through the retained strategy. In-process work and OS adapters publish
> authoritative state before notifying the local latch. OS readiness never enters
> the arbiter directly.
> Local work and deferred signals publish authoritative state before notifying
> the owner; a wake carries no payload and never authorizes dispatch. Pass the
> remaining native-wait budget, but do not promise a shorter SQLite polling pass.
> Local work must be serviced with empty broker queues and coalesced or downgraded
> hints. Notification is a latch observed on strategy return, not a guaranteed
> interrupt of the waiter call already in progress. The native strategy checks
> that latch after each pass bounded by `max(delay, burst_sleep)`, so the default
> local response arrives after one roughly 100 ms quiet pass (before configured
> jitter) without a deadline. `BROKER_MAX_INTERVAL` is the product tuning knob.
>
> Inputs have four origins. Broker activity is observed directly by the strategy.
> In-process completion or a self-write publishes state and calls
> `notify_activity()`. An operating-system source cannot publish itself: one
> adapter owns one blocking operation, publishes an immutable result and notifies
> the owner. Clock work and absence are represented by a deadline. For every OS
> source, exit and end-of-stream remain separate; quiet exit remains observable;
> a final result does not prove adapter retirement; blocking reads are cancellable;
> and one owner holds each fd/handle. The adapter owns no broker, cursor or ledger
> handle.
>
> Do not layer another scheduler or observer of the same domain state around this
> mechanism. A timer exists only for clock work or absence, never as a second poll
> of present state that already has an event source. Required blocking source
> adapters and one-shot lifecycle observers may publish immutable results into
> the owner. Multi-context composition may nest the same shape:
> a higher-level owner derives domain progress from inner events while retaining
> deadlines and lifecycle evidence for objects it owns. It does not watch or poll
> child broker state independently.
>
> On SQLite, an unchanged `data_version` after a quiet strategy pass performs no
> per-queue pending checks. The exception is a non-persistent watcher without a
> native waiter: because each operation opens a fresh connection and
> `data_version` is connection-local, it confirms pending state at the end of each
> strategy pass. Inactive queue discovery otherwise runs inside a confirmed owner
> turn or the strategy's own idle safety return.
>
> Derived-cache convergence has no timer on any backend. A Taut mutation that can
> invalidate an existing owner's cache without activity on an already-watched
> queue commits its authoritative change and then writes one coalescing event to
> the core-owned `taut.cache_stale` queue with `keep_newest=1`. Membership-topology mutations and
> notification-pointer claims are the initial producers. Interested owners hold
> that queue as a fixed retained PEEK source with an in-memory cursor. They capture
> the initial cursor before the first authoritative snapshot so a concurrent event
> remains pending. A new row means only that owned cache may be stale; the owner
> either rereads authoritative state before advancing past the observed hint or
> first publishes an owner-local pending-refresh obligation that remains set until
> the paced refresh succeeds. This rule also applies to the owner's own hint:
> its write may replace an unseen peer hint, so the returned write timestamp
> alone does not justify advancing the consumer cursor. This permits coalescing
> without a retained-row spin.
> A crash between commit and hint, a raw broker operation or a mixed-version
> writer may delay convergence on either backend until a new cache-stale row or
> an explicit local operation schedules that cache's refresh. The hint does not
> make the mutation atomic and does not justify a polling backstop. Failure to publish
> the advisory hint after commit is diagnosed but does not turn the committed
> authoritative operation into a reported failure or trigger an automatic retry.
>
> A reactor with no timer still enters its retained strategy with no deadline; it
> does not skip waiting. Reactor and manual callers share one protected owned-wait
> body and hint classifier. The public manual wrapper may preserve its existing
> `None` surface without creating another scheduling path.

### D2a: [TAUT-8.4], replace the membership-refresh paragraph

> Membership changes apply while running through the existing owner-thread
> `add_queue`/`remove_queue` path. Core membership-topology operations commit authoritative
> sidecar state and then publish [TAUT-8.5]'s bounded `taut.cache_stale` hint. A
> watcher retains that queue as cursor-aware PEEK input, rereads membership when a
> newer hint exists, and updates topology on its owner. No membership refresh
> interval remains. A crash between commit and hint, a raw state mutation or a
> mixed-version writer can delay convergence on either backend until a new
> cache-stale row or explicit local membership refresh. The hint does not make
> sidecar and queue publication atomic.
>
> Chat delivery remains governed by membership rows and per-thread cursors.
> Watcher queue operations use SimpleBroker's public `Queue` behavior directly.
> Taut does not add a second retry policy or substring classification around
> broker or row-decode failures.

### D2b: [IAN-6.1] and [IAN-7.4], define cache-stale publication

Append to [IAN-6.1]:

> Core owns one unregistered `taut.cache_stale` system queue. It is a bounded,
> coalescing advisory source for an authoritative change that an already-running
> owner may not observe on its current queue set. It is invisible to chat routes
> and listings. Payloads are inspection-only; consumers reread authoritative
> state. Membership-topology mutations and notification-pointer claims are its initial
> producers.

Append to [IAN-7.4]'s consuming-inbox contract:

> After a normal Taut notification claim commits, the client publishes one
> `taut.cache_stale` hint through the shared core helper. Atomic claim remains the
> consumption authority. Failure after claim and before hint, a raw SimpleBroker
> claim or a mixed-version caller may leave an observer's cache stale on either
> backend until a new notification/cache-stale row or a refreshing local command.
> None permits duplicate claim or adds a freshness timer.
> Hint-publication failure must not discard the already-claimed rows returned to
> the caller.

### D3a: [SUM-5.4], append to "Cursor as injection ledger"

> A first-party Summon driver may hold exactly one retained-chat delivery in
> flight so control remains responsive while `inject()` blocks. The reactor owner
> retains the message and cursor disposition. The injection worker owns only the
> blocking call, publishes one immutable result and then notifies the owner's
> local latch under [TAUT-8.5]. Enqueuing work is not successful delivery.
>
> While a retained delivery is pending, only the fixed control queue counts as
> broker wait activity. The owner also excludes that retained PEEK source from
> dispatch even when it was already active before the delivery began. It continues
> to service control, local results and owned deadlines. Actual injection success
> advances the retained-chat cursor exactly once. Cancellation is not poison and
> leaves the cursor unchanged. A source or adapter failure also leaves the cursor
> unchanged and enters the source's existing recovery path. Malformed delivery or
> user-handler failure retains the existing poison policy. A notification pointer
> already claim-consumed before an unsuccessful injection is not replayable.

This is a Summon delivery contract, not a generic asynchronous-handler feature in
core. The restored core wait-activity hook supplies queue eligibility, while the
Summon owner supplies the narrow active-turn/dispatch guard required by retained
PEEK semantics.

### D3b: [SUM-9], replace the dedicated control-thread paragraph

Replace the paragraph beginning "The driver consumes control queues with a
long-lived control reactor on a dedicated thread" through the final sentence
before "The control reactor follows SimpleBroker" with:

> Under [TAUT-8.5], Summon owns one context through one reactor. Chat and control
> queue activity, local completion, readiness, provider lifecycle and shutdown
> are processed by that owner. Control commands are consumed; chat remains
> cursor-aware retained history under [SUM-5.4]. Blocking transport/injection
> operations use bounded source adapters when necessary, publishing immutable
> results for the reactor to apply. They do not acquire broker/state handles or
> become nested supervisory reactors.
>
> STOP remains responsive while injection is blocked. During [SUM-5.4]'s one
> in-flight delivery, the shared reactor continues control, local-result and
> deadline turns without redispatching retained chat. The lifecycle owner
> requests nonblocking adapter retirement through normal execution, completes
> required teardown and release, and only then publishes a successful STOP reply.
> A signal handler publishes pending state without calling the adapter.
> Independent watcher supervision and cross-owner acknowledgment handshakes are
> removed when their work moves into this single reactor.
>
> A one-shot control requester owns one persistent `BaseReactor` over its
> per-request reply queue, backed only by public SimpleBroker APIs. The reactor
> observes readiness; the requester still consumes its reply. Its overall timeout and idempotent retry are owned
> deadlines. It does not sleep and poll `read_one()` on that queue.

S0-Summon must reconcile subsequent control-reactor-specific wording, [SUM-5]
watcher rebuild/readiness language and [SUM-7.1]/[SUM-12] signal-reentry
requirements with this one-owner restoration. Chat-source failure unwinds the
current instance and the same owner installs one serial replacement without
restarting a healthy provider. Preserve provider-generation versus chat-source
recovery distinctions and one-graceful-signal/cleanup tests.

### D4: [MCP-8], insert after its first two ownership paragraphs

> Under [TAUT-8.5], the hierarchy repeats the same reactor shape because the
> process manages multiple contexts. Each workspace is a `BaseReactor` subclass
> over the shared exact copy of Weft's `MultiQueueWatcher`. Its fixed broker sources are
> the member notification queue and `taut.cache_stale`, observed as cursor-aware
> PEEK inputs. Its local command queue publishes state and then calls the inherited
> notification seam; it is not a peer Event wait. The process owner may retain
> only that bound notification callback after constructing the inert strategy and
> common stop token; the workspace thread owns strategy startup, waiting and
> cleanup. The broker-free process owner
> uses the asyncio host loop as its arbiter and consumes workspace event streams.
> Higher levels do not introduce independent context watchers or inspect child
> broker/domain state.
>
> A notification or cache-stale source row marks snapshot work pending. The paced
> `peek_inbox` snapshot confirms domain state; source cursors confirm broker
> readiness without consuming notification pointers or leaving retained rows
> permanently ready. The owner records pending snapshot state before advancing the
> source cursor and does not clear it until the snapshot succeeds. The workspace
> does not rebuild its waiter or add a parallel
> wait to defend against an always-ready test double. A pacing deadline represents
> the timed emission itself and exists only while a snapshot is pending. Source
> rows and local wakes carry no domain authority; `peek_inbox()` remains
> authoritative. Local command completion preserves the current synchronous
> refresh or marks a snapshot pending before the next wait.
>
> A normal Taut notification claim commits atomically and then writes the generic
> cache-stale hint. Another workspace sharing that member identity refreshes on
> the hint. Atomic claim prevents duplicate consumption, and one-time handling
> uses only records returned by `inbox`. A crash between claim and hint, a raw
> SimpleBroker claim or a mixed-version caller can leave a cached pointer visible
> on either SQLite or PostgreSQL until a new notification/cache-stale row or a
> refreshing local command schedules the snapshot. A changed SQLite data version
> with no row after either source cursor does not schedule a snapshot. There is
> no unconditional workspace snapshot deadline.
>
> A workspace publishes an immutable event to the parent queue before requesting
> an immediate owner-loop drain. The process maintenance clock drains that queue
> before checking child-thread liveness so quiet exit is eventually observed; it
> is not a workspace freshness poll or recovery on a closed event loop.
>
> Phase, pacing, recovery and retirement deadlines remain explicit obligations,
> routed through the responsible owner. Preserve queued publication, generation
> admission and actual retirement.

S0-MCP supplies exact corrections for [MCP-7]/[MCP-8]/[MCP-12]. SQLite
`data_version` triggers source confirmation, not an unconditional snapshot.
Explicit publication covers own-connection commands, and F12 uses
`taut.cache_stale` for normal Taut claim paths on both backends. A raw claim or
missing hint can leave no cursor-qualified source row even when `data_version`
changes; the commit-to-hint/raw-caller gap therefore applies to SQLite too.
A quiet strategy return does not cause a snapshot,
and MCP adds no application-owned freshness timer. Preserve `_wake_master()` as
immediate notification after child event publication. Preserve process maintenance
as the parent's clock that drains events before checking true thread retirement,
plus non-consuming snapshots, framework transport ownership and the aggregate
shutdown bound. A `call_soon_threadsafe()` `RuntimeError` normally means the loop
is closed; maintenance on that loop is not its recovery path. Replace the inner
10 ms native/Event multiplexer and any other proven duplicate observation.

Within [MCP-8], replace the current `call_soon_threadsafe` failure paragraph with:

> Child threads publish immutable events to the process-owned queue before they
> request an immediate drain with `call_soon_threadsafe`. While the captured loop
> is live, that callback is the prompt notification path. A `RuntimeError` from
> `call_soon_threadsafe` means the loop is closed and may be ignored only during
> teardown; process maintenance on that loop is not a recovery path. The 0.5-second
> process maintenance turn drains already-published events before checking
> `Thread.is_alive()`, so it observes quiet owner exit without reading child
> broker or domain state. A missing or wrong running-loop handle remains a fatal
> process-reactor invariant.

In [MCP-12], replace the forced pre-teardown `call_soon_threadsafe` failure and
"missed event wake" requirements with firing proof for event-before-notification,
prompt live-loop drain, harmless redundant callbacks, loop-closed suppression
during teardown, maintenance drain-before-reap ordering and quiet child exit.
Replace the universal external-consumption/backstop freshness proof with normal
Taut peer-claim freshness through cache-stale publication on both SQLite and
PostgreSQL, same-process post-command freshness and atomic no-duplicate
consumption. Prove the commit-to-hint/raw-caller/mixed-version gap on both
backends, including a changed SQLite `data_version` with no row after either
source cursor. Prove no snapshot occurs for that hint alone, and a subsequent
cursor-qualified notification/cache-stale row or a refreshing command schedules
an authoritative snapshot that clears the stale pointer.

### D5: [TUI-4.1], append to the process model

> Runtime owners follow [TAUT-8.5]. The active conversation's public watcher owns
> its broker source and uses `PollingStrategy` as its wake arbiter. The Textual
> loop owns broker-free presentation state and is the host-loop arbiter only for
> that state. Serialized workers and the one-shot watcher-retirement observer
> publish immutable results into Textual; they do not observe broker state or
> become peer schedulers.

### D6: [TAUT-12.3], append to the watcher vendoring decision

> The multi-queue scheduler remains whole-and-faithful vendoring. Taut records the
> Weft source commit, path and copied-block digest and keeps the copied class and
> method bodies identical. Module-level imports, constants, broker-target resolution
> and default error policy may be supplied by Taut shims outside that block. Taut's
> owner lifecycle and domain policy subclass the copy: `BaseReactor` supplies the
> one turn/wait template; core watch, Summon, MCP workspace and bounded control
> requesters supply only their cursor, delivery, snapshot or deadline policy. A
> scheduler change is made upstream and recopied, or is recorded as an explicit
> reviewed divergence; it is not silently adapted in place.

### Floors and verification corrections

Change current normative `simplebroker>=8.3.1` to `simplebroker>=8.4.0` and
`simplebroker-pg>=4.3.1` to `simplebroker-pg>=4.4.0` in applicable packaging and
reactor sections; document bounded native passes, the public native timeout and
the local latch as the reason.
Historical version descriptions remain historical.

The applicable per-slice S0 writes exact acceptance additions for [TAUT-11],
[SUM-12], [MCP-12] and [TUI-12]: the source/owner graph, each removed loop's
replaced obligation, single-Summon-owner behavior, cursor-after-worker-success,
physical signals, quiet/hot work bounds and multi-context derived-event behavior.
Every enumerable
case has a firing test; structure alone is not proof.

## Implementation Slices After Their Audit/Promotion Gates

### S1. Dependency and provenance preparation

Supports [BASE-2] through [BASE-4] by establishing the exact public dependency
contract before behavior changes.

- [x] Raise root/MCP SimpleBroker and root-dev/PG floors; refresh all four retained
  locks without unrelated upgrades. Update README/current floor statements.
- [x] Require the upstream standalone `MultiQueueWatcher._sigint_handler` fix
  and owner-thread topology admission before accepting the exact copy. Pin Weft
  `9fc913c1` (0.9.105) and verify the whole-file digest recorded above. The prior source called `_stop_event.set()` in a topology-critical
  signal frame; Weft's `BaseTask` override did not protect standalone embedders.
  The fixed handler defers lock-taking work to normal owner execution. Preserve
  upstream regression provenance: real repeated SIGINT during topology publication
  while holding the Event condition or a strategy-notification lock must complete
  coherent publication and cleanup; fatal-error precedence must survive. S1 must
  not patch the copied class locally or treat a `BaseTask` test as this proof.
- [x] Confirm the recorded SimpleBroker 8.4 public signatures and semantics with
  an API probe. Record the Weft source SHA/path/digest and the exact-copy boundary.
  F12 requires no SimpleBroker change. Do not edit `taut/watcher.py` in this slice.
- [x] Run existing dependency compatibility contracts and independently review
  the floor/lock/provenance slice before core behavior changes.

### S2. Restore core source/wait/signal behavior

Implements [BASE-1] through [BASE-4] for broker-owning Taut reactors and supplies
the wait-activity hook required by [BASE-5]. Core has no blocking OS-source
adapter; signal delivery publishes deferred local state through [BASE-3].

- [x] Replace `taut/watcher.py`'s scheduler block wholesale with the S1-pinned
  Weft block. Keep only reviewed Taut module-level shims outside the copy. Record
  the post-copy digest and rerun the recorded comparison before changing
  `BaseReactor` or a domain subclass.
- [x] Keep `BaseReactor` thin over that copy: one final non-reentrant process turn,
  one owned wait body, deferred signal state and cleanup. Remove
  `_reactor_activity_event` and any broker-wait code that duplicates the copied
  watcher. Remove its parallel broker session, queue cache and waiter-replacement
  implementation in favor of inherited ownership. Bridge the custom drive loop
  into the copied watcher's existing topology reservation/owner scope so dynamic
  `add_queue`/`remove_queue` requests still serialize on that same owner and all
  pending mutations fail and retire through the copied cleanup rules. The
  owner's own membership refresh mutates topology through the copied
  owner-synchronous path (F15, resolved at the `9fc913c1` pin); keep that
  refresh outside the dispatch pass and add the two Taut-owned F15 tests for the
  task-shaped drive loop. Do not import
  Weft `BaseTask`, TaskSpec, worker-result or control policy.
- [x] Receive `_queue_counts_as_wait_activity(config)` and the transient SQLite
  fallback from the copy. Test subclass filtering and public
  `client.watch(persistent=False)` without changing ordinary watcher behavior.
- [x] Add failing F1/F2 tests; pass remaining native budgets, service local state
  and preserve broad inactive discovery inside confirmed turns and strategy idle
  safety returns. Add one protected notification forwarder to the SimpleBroker
  strategy. Remove the 10 ms Event wait tier and obsolete fields when their
  obligations belong to the restored source.
- [x] Remove the universal inactive-discovery deadline from
  `next_wait_timeout()` while retaining the exact copied watcher's internal
  `_next_inactive_probe_at` broad-scan throttle. Remove the membership refresh
  deadline as well; S2b replaces it with `taut.cache_stale`. Do not land S2 without S2b on
  PostgreSQL, because a cross-process join would otherwise have no wake source.
  Restore one shared protected owned-wait body, make the reactor call it even when
  the composed deadline is `None`, and preserve public `wait_for_activity(None)`
  behavior through its thin wrapper.
- [x] Add F3 to `tests/helpers/base_reactor_sigint_probe.py` using real signals,
  a held Event lock and a parent watchdog. Preserve prompt synchronous
  interruption and ownership-transfer deferral, with cleanup outside the frame.
- [x] Test own-connection writes, unrelated changes, empty queues, local return
  without fabricated backlog, native authoritative confirmation, consumed
  downgraded hints, topology rebind, native failure/fallback and quiet/hot
  fairness. Add a query-count proof that repeated quiet SQLite passes with
  unchanged `data_version` execute no cursor-aware `has_pending` calls and their
  queue I/O does not scale with joined-thread count. Do not manipulate private
  SimpleBroker cadence or waiter fields in production.

Files: core watcher/runtime/client integration as required by the reviewed map,
`tests/test_watcher.py`, `tests/test_architecture_boundaries.py`, the signal
probe, `extensions/taut_pg/tests/test_reactor.py`, and core architecture note.
Done: red/green proofs and real backend evidence; independent slice review.

### S2b. Give otherwise-missed cache invalidation a broker event

Implements [BASE-3] and [BASE-4] for authoritative changes that an existing owner
may not observe on its current queue set. One broker-origin hint replaces the
0.5-second membership deadline, SQLite's refresh on every unrelated
`data_version` change and MCP's workspace freshness backstop. This passes the
reuse gate on F13: no existing watched source covers cross-process membership
change or PostgreSQL source-queue claim, while SimpleBroker already supplies the
bounded queue primitive and the reactor already supplies the event path.

- [x] Name the core-owned unregistered queue `taut.cache_stale` under [IAN-6.1].
  Its payload is inspection-only and identifies the broad reason and affected
  identity/thread when available, but every consumer must treat every observed
  row as "owned cache may be stale" and must not skip its refresh based on the
  payload: with `keep_newest=1` a newer unrelated row replaces an older relevant
  one, so payload filtering is unsound. No payload field is authority. Process
  an owner's own hint through the same refresh path. Do not advance the consumer
  cursor merely because `Queue.write` returned that timestamp: the write may
  have replaced an unseen peer hint. Advance only after an authoritative refresh
  covering the observed hint, or after recording the same pending-refresh
  obligation used for peer hints. Add a firing peer-hint-then-own-hint test that
  proves the peer's change reaches the cache.
- [x] Writers: add one shared client-owned publication helper using the existing
  queue factory. Call it immediately after every public Taut membership-topology
  operation (join/create membership, leave and channel rename) returns from its
  committed `taut/state/_sql.py` mutation, and after the normal
  notification-claim path returns its claimed rows. S0 enumerates every producer
  and gives each a firing test so no path can silently omit the helper. Write one
  hint with `Queue.write(..., keep_newest=1)`. The state mutation/claim remains
  authoritative and atomic on its own; the following hint is deliberately
  advisory. Do not give the SQL state layer broker-factory ownership merely to
  hide these explicit publication sites. Cursor advancement and quiescent
  persistence load are not topology changes and do not emit this hint.
- [x] A post-commit hint-write failure emits one bounded diagnostic through the
  existing logging/warning boundary and preserves the authoritative operation's
  success result. It is never retried automatically. In particular, `inbox()`
  still returns its already-claimed rows. Add firing tests for membership and
  claim publication failure; do not build an outbox or repair worker.
- [x] Readers: `TautWatcher` and MCP workspace reactors hold the queue as a fixed
  cursor-aware `PEEK` source. Capture the newest timestamp before the initial full
  authoritative refresh and keep that pre-refresh value as the starting cursor,
  so an event racing with the snapshot remains pending for a second refresh.
  `TautWatcher` refreshes membership before moving past the observed hint. MCP
  records `snapshot_pending` before advancing its source cursor and keeps that
  obligation set until the paced snapshot succeeds. A burst causes one
  authoritative refresh, and retained rows cannot spin while pacing.
- [x] Remove the membership refresh from `_on_data_version_change` and from the
  turn-time deadline. Keep explicit own-connection publication for a process
  that changes membership on the watcher's own connection.
- [x] Exclude the queue by name from chat listing and public chat projection.
- [x] Record the accepted boundaries: a writer from an older Taut release emits no
  event; a raw SimpleBroker claim bypasses it; a crash can occur after commit and
  before hint. In each case the cache may remain stale until an event explicitly schedules the affected cache refresh.
  Do not add repair or a timer. Every interested owner may wake on an unrelated
  cache hint and pays one cursor compare plus only its relevant authoritative
  refresh.

Files: `taut/state/_sql.py`, the notification claim capability,
`taut/watcher.py`, `taut/_constants.py`, MCP workspace reactor, [IAN-6.1],
[TAUT-8.4]/[TAUT-8.5], [MCP-7]/[MCP-8], README plumbing note, CHANGELOG,
watcher/state/notification/MCP tests and `extensions/taut_pg/tests/test_reactor.py`.
Done: on real SQLite and PostgreSQL a peer join/leave reaches a running watcher
and a normal peer inbox claim reaches an MCP observer with no timer; unrelated
SQLite writes do not run membership or snapshot queries; the queue stays bounded;
an event racing with initial snapshot is not skipped; the commit-to-hint/raw-caller
limitation is tested or deterministically proved and documented; independent
review.

### S3. Restore Summon's one reactor

Implements [BASE-1] through [BASE-5]. This section is a migration program, not
one landing slice; S0-Summon must replace its provisional boundaries with exact
file/symbol/test maps before any S3 runtime edit. `_driver.py` and `_control.py`
currently total 3,590 lines; the three stages below must remain separate reviewed
slices unless S0-Summon proves a smaller safe partition.

#### S3a. Establish in-flight delivery on the current chat owner

- [x] Use the restored `_queue_counts_as_wait_activity` hook, existing
  `_process_reactor_turn`, existing Taut cursor/failure policy and a Summon-owned
  immutable result queue. Do not add a generic core delivery framework.
- [x] Permit exactly one injection in flight. The worker owns only `inject()` and
  publishes its result before `notify_activity()`. The owner applies the result;
  actual success advances the cursor exactly once. Cancellation is not poison and
  leaves the cursor unchanged. Source/adapter failure leaves the cursor unchanged
  and enters source recovery. Malformed delivery or user-handler failure follows
  the existing poison policy. A notification pointer already claim-consumed
  before an unsuccessful injection remains non-replayable.
- [x] While delivery is pending and control remains on its current owner, no chat
  or notification queue counts as wait activity, and `_process_reactor_turn`
  drains local results without calling the ordinary queue drain. Prove an already-
  active chat queue cannot redispatch: start with its PEEK row active, hold the
  first delivery, drive several bounded turns, and observe no second fetch until
  one successful result advances the cursor. Also prove no early cursor advance,
  worker-result wake and clean cancellation before proceeding.

#### S3b. Fold control into the chat reactor

- [x] Add the fixed READ control queue to the same reactor and use the wait-
  activity hook so only that queue counts during in-flight delivery. Keep control
  in a bounded control-only turn while work is active so an already-active chat
  queue cannot dispatch and control floods cannot starve completion or deadlines.
- [x] Move correlation and rate policy to the owner, then delete `_ControlReactor`,
  `ControlLoop`, its thread, duplicate broker bundle and cross-owner acknowledgments.
  Soft rate-limit nudges use the same serialized injection worker and the same
  in-flight gate as chat delivery; they do not call `handle.inject()` synchronously
  on the owner. Classify a hard interrupt separately as either a bounded owner
  operation or a named source adapter. Prove blocked-injection STOP/PING, rate-
  limit serialization, fairness and release-before-reply ordering.
- [x] Keep `ControlClient` as its own bounded request context; replace its 30 ms
  loop with one persistent `BaseReactor` over its one per-request reply queue
  (F10). Preserve `read_one()` consumption, correlated reply parsing, overall
  timeout and idempotent retry deadlines without adding an exception to [BASE-2].

#### S3c. Collapse lifecycle supervision and classify native adapters

- [x] Move readiness, retry, rate audit and release policy into reactor transitions.
  Recover a chat source by serial owner replacement after the failed turn unwinds;
  preserve one readiness deadline and do not restart a healthy provider.
- [x] Keep the continuous pump and the [BASE-4] injection, PTY, quiet-child,
  attach, process and console-read adapters. Remove broker/state/lifecycle policy
  from them. For every operating-system source, name its adapter or recorded
  direct-owner reason and prove exit versus EOF, quiet exit, result versus thread
  retirement, cancellation and exclusive fd/handle ownership. With broker queues
  silent, prove owner response to worker completion and quiet child exit within
  one configured strategy pass, without an application deadline or peer wait.
- [x] Restore signals across bootstrap/attach/orientation/dispatch/teardown. Keep
  pre-identity bootstrap synchronous with safe phase checkpoints; after reactor
  construction use the normal owner path.
- [x] Remove remaining watcher supervision, readiness polling, cyclic handshakes
  and the controller's post-ACK release loop. Read committed release evidence once.

Tests across S3a-c: existing Summon `test_driver.py`, `test_control.py`,
`test_controller.py`, `test_interaction.py`, `test_pty_adapter.py`,
`test_pty_posix.py`, `test_pty_windows.py`, plus real subprocess helpers. Each
stage gets red/green behavior proof and independent review before the next stage.
Done: one owner/arbiter after identity, blocked-injection STOP, true release-before-
reply, pre-reactor signals, no early cursor advance, no leaked or overlapping
source/provider generation, and a named [BASE-4] adapter or reason for every OS
source. Removing wait caps alone does not satisfy this gate.

### S4. Restore MCP's repeated shape and derived hierarchy

Implements [BASE-1] through [BASE-4]. [BASE-5] is Summon-specific.

- [x] Replace the workspace's 10 ms raw native/Event multiplexer by subclassing
  the shared `BaseReactor`. Configure notification and `taut.cache_stale` as fixed
  cursor-aware PEEK queues. Inbound command/cancel/stop producers publish to the
  local queue and call the inherited notification seam. Local control/STOP
  response is bounded by one strategy pass; do not add a peer wait or response
  deadline.
- [x] Replace `_Owner.wake` with the bound `notify_activity` callback from the
  exact strategy instance passed to the workspace. Use the same stop token for
  strategy and reactor. Preserve queue-before-notify ordering and prove commands
  queued before strategy start are drained on the first turn. The parent never
  calls `wait_for_activity`, replaces a waiter or observes child broker state.
- [x] Treat a new source row as a request for the paced snapshot, and use that
  `peek_inbox` snapshot as domain confirmation. Cursor-aware retained-`PEEK`
  fetch and pending checks (`_fetch_next_message` with `after_timestamp`,
  `_queue_has_pending(after_timestamp=cursor)`, the per-queue cursor map and the
  `taut.cache_stale` handling) live once in `BaseReactor`, which Taut owns
  outside the copy. `TautWatcher` already implements them today; move them up
  rather than re-implementing them in the MCP subclass. The MCP subclass then
  overrides only turn policy; broker waiting, waiter replacement, hint
  classification, fallback and cleanup remain the copied/base path. Do not
  call cursor-free `has_pending` on retained notification pointers or add
  anti-hot-loop state for the always-ready double. Replace that double with
  edge-triggered behavior evidence. Record `snapshot_pending` before advancing a
  source cursor and keep it set until a snapshot succeeds, so pacing cannot spin
  on one retained row or lose the refresh obligation. Live PG/Redis hot-loop work
  requires live evidence before it can expand this slice.
- [x] Preserve current synchronous post-command snapshot refresh. If the revised
  turn routes it through the common snapshot path, mark the snapshot pending as
  soon as the command completes and capture it before re-waiting. This is the
  explicit local publication required for SQLite own-connection writes.
- [x] Remove the child 0.5-second observational backstop on both backends after
  SQLite source-confirmation, own-command publication and `taut.cache_stale`
  proofs pass, including the no-hint peer-claim limitation on both backends. A pacing deadline exists only while a real source row has made a snapshot
  pending. A quiet PostgreSQL idle-safety return and a quiet unchanged SQLite pass
  perform no MCP snapshot query. Document F12's commit-to-hint, raw-broker and
  mixed-version limitation; none can produce a duplicate claim.
- [x] Retain `_wake_master()` as the prompt child-to-parent notification after an
  immutable event is enqueued. Retain process `_maintain`, event-queue draining
  and `Thread.is_alive()` checks as parent-owned clock work and
  actual-retirement evidence. Replace the misleading live-wake-recovery comment:
  a swallowed `call_soon_threadsafe()` `RuntimeError` normally means the loop is
  closed. Prove late-loop-close handling, maintenance drain-before-reap ordering
  and quiet child retirement. Retain bounded shutdown resampling unless S0-MCP
  proves a smaller existing primitive. The parent must not read child databases
  or broker queues.
- [x] Preserve failure-before-publication, immediate event delivery while the
  loop is live and true-exit evidence; do not equate an in-thread final envelope
  with thread exit.
- [x] Retain all context isolation, generation/admission, canonical resource,
  non-consuming freshness and dual-era transport outcomes.

Files: MCP workspace/process reactors and lifecycle wiring in `server.py`;
`test_process_reactor.py`, `test_resource.py`, `test_pg_conformance.py`,
`test_dual_era_contract.py`, and MCP architecture note.
Done: bounded quiet/hot work, commands/stop while paced, normal same-identity
claim refresh through `taut.cache_stale`, documented exceptional stale-cache
boundary without duplicate consumption, immediate child event delivery and actual
retirement through the existing parent lifecycle path; real SQLite/PG and review.

### S5. Verify TUI alignment and close remaining audit rows

Verifies [BASE-1] through [BASE-4] for the Textual composition root and preserves
[BASE-5] across its Summon bridge without making Textual a broker arbiter.

- [x] Verify that Textual owns presentation, the serialized session worker owns
  each `TautClient`, and one public watcher owns active-conversation broker state.
- [x] Retain `_monitor_watcher_exit` as a one-shot join/retirement adapter. Retain
  executor/Future marshalling, UI generation fencing, checked replacement,
  terminal lease exclusivity and rich-host signal ownership.
- [x] Keep confirmation cancellation on the worker already blocked in the wait.
  A daemon thread per confirmation stays alive after a normal answer because
  cancellation need never occur. The worker samples the caller cancel event
  between short waits and resolves the request itself. Host shutdown still
  sets stop before the refusal is visible. The first decision sticks.
- [x] Close every other production audit row with an owner/state/source/deadline
  classification. Retention needs a concrete reason; syntax alone is not grounds
  for deletion.

Files: expected documentation/test-only verification for TUI; runtime files only
if S0-TUI finds a concrete duplicate authority or correctness defect. Include any
other source explicitly added to the reviewed map. Done: source graph and
behavioral tests agree; independent review.

### S6. Reconcile, qualify and measure removal

Re-audits [BASE-1] through [BASE-5] across all accepted slices.

- [x] Repeat the full scan and compare current/restored graphs. Account for every
  moved/deleted/retained loop, observer, thread and deadline. Measure quiet SQL/
  wait work and hot-hint CPU; changing output cadence alone is not a CPU proof.
  The quiet SQLite SQL count is already a firing S2 contract, not a measurement
  deferred to this slice.
- [x] Reconcile specs, implementation notes, provenance, maps, README, CHANGELOG,
  manifests/locks, test coverage and finding dispositions. Record new durable
  lessons where warranted; evaluate used skills without a process rewrite.
- [ ] Run full backend/platform acceptance and independent final review. Native
  Windows/PG evidence cannot be replaced by a passing mock or an unexplained skip.

## Verification and Anti-Mocking

Red-green for behavior changes. Deterministic tests may control time and external
readiness but keep production strategy/owner/state transitions. They supplement
real SQLite/PG and physical-signal/child tests. Use causal barriers and existing
observational eventual helpers, not sleep duration as proof of event delivery or
liveness.

Required proof inventory: exact comparison of the copied block; native budget/fallback
and one-pass local-wake semantics; local-only work;
coalesced/downgraded hints; same-connection writes; dynamic topology; inactive
queue discovery without quiet SQLite per-queue I/O; cross-process membership
and notification-claim cache-stale events on both backends with no refresh timer;
bounded `taut.cache_stale`; initial-snapshot/cache-hint race closure;
peer invalidation coalesced by an own write still causes authoritative refresh;
post-commit hint-write failure without false operation failure or lost claimed
rows; non-persistent SQLite per-pass confirmation;
persistent one-shot requester close; signal lock interruption and synchronous unwind; blocked
injection STOP; owner-only cursor advancement after real delivery; removal of
self/cyclic waits; worker result versus retirement; quiet child exit with retained
terminal descriptors; broad discovery after a filtered in-flight hint; MCP
snapshot confirmation through cursor-aware PEEK; pending-before-source-cursor
ordering with no paced retained-row spin; MCP pre-start notification and
queue-before-notify race; PG sidecar convergence; F12's
normal claim hint, commit-to-hint/raw-caller/mixed-version gap on both backends,
changed SQLite data version without a new source row, recovery on a qualifying
snapshot trigger and atomic no-duplicate claim;
no quiet workspace snapshot query; process maintenance drain-before-reap and
late-loop-close handling; paced hot source; publication before notification and
failure before terminal publication; multi-context isolation; late generations;
constructor/cleanup failures; UI delivery/terminal restoration; every retained
domain deadline. Map each to a concrete test in S0.

Plan-authoring gates:

```bash
uv run --no-sync bin/check-plan-status-index
uv run --no-sync bin/check-doc-paths
uv run --no-sync pytest tests/test_docs_references.py
git diff --check
```

Focused execution gates from the repository root:

```bash
uv run --no-sync pytest tests/test_watcher.py tests/test_architecture_boundaries.py
uv run --no-sync pytest extensions/taut_summon/tests/test_control.py extensions/taut_summon/tests/test_controller.py extensions/taut_summon/tests/test_driver.py
uv run --no-sync pytest extensions/taut_mcp/tests/test_process_reactor.py extensions/taut_mcp/tests/test_resource.py
uv run --no-sync ./bin/pytest-pg --fast
uv run --no-sync ./bin/pytest-pg --fast extensions/taut_mcp/tests/test_pg_conformance.py
uv run --no-sync ruff check taut tests extensions
uv run --no-sync ruff format --check taut tests extensions
uv run --no-sync mypy taut tests
```

Sync the declared editable/dev environments before `--no-sync`, deliberately,
not as a probe side effect. For final acceptance use the exact current root,
Summon, MCP, TUI, PG, typing, physical-lifecycle and installed-wheel commands in
`bin/release.py` and CI. Inspect those commands; do not invent a weaker combined
collection with conflicting conftests. Publication is not a verification command.
Use `-n 0` only while diagnosing a specific test whose failure requires serial
isolation; it is not a normal plan gate.

## Rollout, Rollback and Operational Evidence

No data/schema migration. Dependency floors/locks precede new API calls. Restore
core before consumers; delete compensators only after the replacement source and
owner proofs pass. Land coherent tested slices by explicit file lists when the
owner authorizes commits. Do not retain permanent old/new runtime paths.

Before publication revert a failed coherent slice with its docs/tests; do not
roll back the dependency alone while callers use its new API. After publication
use a corrective release. Coordinated publication remains a separate explicit
release-driver action.

Positive acceptance: peer writes/membership changes reach watch; quiet control
work runs; blocked provider STOP releases before ack; MCP performs no periodic
workspace snapshot, refreshes on notification/cache-stale rows and local commands,
and never claims one notification twice across same-identity processes; TUI
replacement/close retires the old owner; idle work backs off and native bursts do
not peg CPU. Use bounded probes, not a new telemetry subsystem.

## Independent Review and Execution Gates

Different-family read-only review checks the plan, exact corrections, invariants
and actual seams. Review again after each applicable S0 migration/source map and
each coherent slice. Challenge extra structure as strongly as missing safety.
Findings are claims: reproduce, disposition and preserve rejected reasons. An
upstream solution is not accepted merely because it is upstream.

The applicable S0 must produce exact remaining spec text and decisions before its
implementation slice. This plan does not pretend every extension has already been
audited, but unresolved extension work does not block the isolated core repair.
Missing source/retirement/cancellation coverage cannot be papered over with an
extra loop or weaker promise.

## Out of Scope / No-Action Register

- No new architecture, event framework, nested Summon reactor, parent strategy,
  manager protocol, daemon, runtime Weft dependency or global backend singleton.
  The one admitted addition is S2b's bounded `taut.cache_stale` queue, which uses
  an existing SimpleBroker primitive and feeds the existing reactor. It is an
  advisory invalidation hint for authoritative changes an existing source set can
  miss, initially membership-topology mutation and notification claim. It is not a payload
  bus, state store, subscriber registry or second arbiter.
- No automatic deletion of legitimate OS source adapters, synchronous scans,
  retries, SDK transport behavior or test/release watchdogs.
- No claim that MCP's queue-before-wake/clear-before-drain ordering loses controls;
  preserve that guarantee when replacing the source path.
- No claim of live PG saturation based solely on the always-ready double.
- No runtime edits, publication, commit or unrelated maintenance sweep as part of
  this planning request. No accepted product behavior may be weakened silently.

## Deviation Log

| Spec ref | Planned behavior | Actual behavior | Rationale | Spec proposal |
|----------|------------------|-----------------|-----------|---------------|

## Decision and Review Log

- 2026-09-22: Applied the update-review corrections. Removed the own-hint
  cursor shortcut: a real SimpleBroker probe showed that an own `keep_newest=1`
  write coalesces an unseen peer hint, so skipping the returned ID loses that
  refresh obligation. Own and peer hints now use the same refresh path. Clarified
  that SQLite `data_version` only triggers cursor-aware source confirmation;
  raw/mixed-version claims and commit-to-hint failures share the advisory gap on
  both backends. Named qualifying refresh triggers and added firing proof cases
  without adding a timer or changing the copied scheduler.
  Focused independent rereview: PASS for both corrections and the MCP backlink;
  no operative conflicting claim or new scheduling mechanism remains in scope.
  Fresh verification: plan-index and documentation-path gates passed, all 12
  documentation-reference tests passed, and `git diff --check` passed. This is
  a documentation-only, uncommitted correction; runtime work remains unexecuted.


- 2026-09-21: The standalone Weft watcher had the same signal-lock hazard:
  `_sigint_handler` called `_stop_event.set()` during a topology-critical section.
  Weft tasks used `BaseTask`'s override, so their safety did not qualify the copied
  base. Fixed upstream first in local-only commit
  `8bcf294be08d71c8bb70864ec7b19eb34f771b13`; S1 pinned that revision and its
  whole-file digest (since advanced to `9fc913c1`, see the 2026-09-22 entry). Both held-lock probes reproduced the pre-fix deadlock and
  passed after repair, including repeated physical signals and fatal precedence.
  Upstream verification: 85 passed, one PostgreSQL-only test skipped; full Ruff
  and mypy (435 files) passed; independent review found no blocker. This advances
  provenance only: no scheduler has been copied into Taut and S1 remains unexecuted.
- 2026-09-19: Owner requires restoration and deletion of compensating layers.
  The final reuse direction is to copy Weft's current `MultiQueueWatcher`
  scheduler exactly and put Taut policy in subclasses, with no runtime Weft
  dependency.
- 2026-09-19: Owner clarified that Summon is one context and one reactor. MCP
  nesting is justified by multiple contexts only; higher levels source progress
  from the inner reactors. All share essentially the same shape.
- 2026-09-19: Owner's rule of thumb: building instead of reusing is evidence of
  possible drift. The reuse gate above applies before adding any mechanism.
- 2026-09-21: Fresh-eyes core, Summon, MCP and TUI audits narrowed the common
  rule to one scheduling owner and one wait/turn authority, with multiple valid
  input adapters. Core is a direct restoration; Summon needs one narrow pending-
  delivery continuation; MCP changes only its inner hot wait; TUI is retain-by-
  default. The global S0 gate was split accordingly.
- 2026-09-21: A full reread of the revised plan found one execution overlap:
  S1 and S2 both owned the core behavior edits. S1 now owns only floors, locks,
  provenance and API compatibility; S2 owns all reactor edits and red/green tests.
  The reviewer found no remaining conceptual architecture blocker.
- 2026-09-21: Owner identified Weft's `_queue_counts_as_wait_activity` as the
  missing reuse seam. Taut receives that hook through the exact copy, but it cannot by
  itself suppress an already-active retained PEEK row. S0-Summon must select the
  smallest owner-turn guard and prove no redispatch before cursor advance; it may
  not invent a generic core delivery seam. Because `_driver.py` plus `_control.py`
  total 3,590 lines, S3 is split into in-flight delivery, control consolidation
  and lifecycle/adapter stages.
- 2026-09-21: Owner separated arbiter observation from source origin. A broker
  strategy observes exactly backend hint, local latch and deadline. Inputs
  originate from broker, in-process completion, operating-system source or clock;
  OS sources require named one-operation adapters with exit/EOF, quiet-exit,
  retirement, cancellation and exclusive-handle proofs. These shared rules are
  proposed for normative [TAUT-8.5]. Summon's retained-delivery/cursor contract is
  proposed for [SUM-5.4]; [SUM-9] cites it for control responsiveness rather than
  owning a second delivery rule.
- 2026-09-21: A later fresh-eyes implementability review found that the restored
  Weft hook cannot suppress an already-active Taut PEEK row, that delivery/cursor
  disposition belongs in [SUM-5.4], that soft rate nudges must share the injection
  gate, and that quiet-backend worker/child-exit response needed an explicit proof.
  F8, D2, D3a/D3b, S0-Summon and S3 now carry those corrections; the later 8.4
  reread corrected that proof to one strategy pass rather than an application
  deadline.
- 2026-09-21: Owner corrected the 8.4 native-wait model and follow-on design.
  Local latches are checked after every bounded native pass, so all quiet-native
  response deadlines were removed. Inactive discovery now rides real turns and
  the strategy idle safety return; quiet SQLite passes do no per-queue I/O;
  membership/freshness deadlines are removed. MCP subclasses `BaseReactor` and
  uses cursor-aware broker inputs plus paced snapshot confirmation. SQLite uses
  `data_version` plus explicit own-command refresh; current
  `_refresh_after_command()` already performs that snapshot for every command
  except non-mutating `channel_show`. `ControlClient` adopts a persistent
  `BaseReactor` over its reply queue.
- 2026-09-21: Owner generalized the proposed membership event into one
  `taut.cache_stale` hint for authoritative changes an existing source set may
  miss. Membership-topology mutations and normal Taut notification claims are the first
  producers. Consumers reread authoritative state in their existing reactor. The
  queue is advisory; the commit-to-hint crash gap, raw broker operations and mixed
  versions may remain stale until a later event. No SimpleBroker change, polling
  backstop or repair path is added.
- 2026-09-21: Owner questioned why a one-shot reactor must be non-persistent.
  It need not be. Weft's reason is an open caller operation on the same thread,
  which `ControlClient`'s sole caller does not have; a scratch probe closed a
  persistent `BaseReactor` cleanly beside an open session. F10 now uses a
  persistent `BaseReactor`, which keeps `data_version` valid. The per-pass
  confirmation rule is therefore needed only for public non-persistent watch
  (F14); the owner chose Weft's minimal existing fallback and kept the public mode.
- 2026-09-21: `_wake_master()` remains the immediate child-to-parent notification
  after immutable event publication. Process maintenance remains a clock that
  drains before inspecting actual thread retirement. The earlier claim that it
  recovers a swallowed `call_soon_threadsafe()` `RuntimeError` was withdrawn:
  that error normally means the asyncio loop is closed, so maintenance on the
  same loop cannot recover it.
- 2026-09-21: Owner required the same Weft architecture with the smallest Taut
  specialization and preferred subclassing an exact copy. The copied scheduler
  now owns all broker wait mechanics; `BaseReactor`, `TautWatcher`, Summon and MCP
  supply only their owner/domain policies. MCP's first idle frontend command may
  therefore wait one nominal 100 ms strategy pass instead of its old immediate or
  10 ms Event tier; burst behavior remains fast. This accepted latency is the cost
  of removing the peer scheduler.
- 2026-09-21: Final implementability review found three conflicts with the pinned
  Weft source. The copied scheduler re-signatures and replaces its native waiter
  when Summon's dynamic wait filter changes, so the plan now preserves that
  behavior. Its `_next_inactive_probe_at` remains an internal broad-scan throttle;
  only the application deadline was removed. Because Taut's custom reactor loop
  bypasses the copied `run_forever()`, `BaseReactor` must enter the copied
  topology-owner scope explicitly. The in-flight Summon broker wait set is stated
  once as control only; notification, chat and cache-stale rows remain deferred.
- 2026-09-21: Weft 0.9.104 (`8bcf294b`) fixed the standalone
  `MultiQueueWatcher._sigint_handler` signal-frame `Event.set`; S1 pins that
  revision, closing the one signal-policy conflict with D1.
- 2026-09-22: Weft 0.9.105 (`9fc913c1`) shipped owner-thread topology mutation
  between dispatch passes with independent review and PostgreSQL owner-origin
  native-rebind coverage. S1 re-pins to that revision and digest; F15 is
  resolved upstream, leaving Taut only its task-shaped-loop tests and the
  `_remove_thread_queue` simplification. Weft 0.9.106 (`cfa5bb21`) followed the
  same day without changing the vendored file; the digest was recomputed and
  matches, and Weft's [QUEUE.8] mapping now records the Taut pin.
- 2026-09-21: Review of the exact-copy decision found that Weft's topology rule
  is the inverse of Taut's (foreign threads submit, the drive owner may not
  mutate during dispatch), so `TautWatcher`'s owner-thread membership refresh
  raises under the copy, and that Weft's dynamic-topology tests cover only the
  standalone loop. Recorded as F15 with an owner decision (upstream protected
  seam and re-pin, or a Taut seam over copied private state). Also: the stale
  "retain Taut's owner-thread membership rule" adopt row was corrected; cursor-
  aware retained-PEEK logic is placed once in `BaseReactor`; consumers must not
  filter `taut.cache_stale` rows by payload.
- 2026-09-21: The same fresh-eyes reviewer rechecked the corrected plan and
  returned PASS with no remaining implementability or conceptual-unity blocker.
  The multi-producer `keep_newest` check and per-extension S0 maps remain explicit
  pre-implementation evidence gates rather than assumed behavior.
- Historical and superseded: earlier drafts retained nested Summon chat/control
  reactors, added a broker-free parent strategy, prescribed a separate MCP paced
  Event wait or bare-strategy loop, accepted normal PostgreSQL claim staleness,
  and limited invalidation to a membership queue. Those choices were withdrawn.
  They have no implementation authority and must not be recovered from earlier
  review approval.
- Initial read-only research and source audits established F1-F12 and platform/
  lifecycle constraints; no implementation or full S0 audit was claimed.
- Claude round 1: PASS on the earlier S0 plan shape, 387 seconds, exit 0,
  success/end_turn/completed,
  read-only safe/plan mode with Read/Grep/Glob. Accepted refinements: preserve
  inactive discovery, explicit synchronous signal policy, replacement deferral,
  pinned API checks, true-retirement coverage and exact spec anchors.
- Claude round 2: PASS on those refinements and the now-withdrawn parent/pacing
  choices. Its architectural approval is superseded by the owner's clarification.
  Retained findings remain useful, but it is not approval of this revised plan.

Earlier revised-shape independent review: Claude PASS, 290 seconds, exit 0,
success/end_turn/completed, `is_error=false`; read-only safe/plan mode with
Read/Grep/Glob. That review approved the broad S0/restoration shape but predates
the later F8-F10 and 8.4/MCP corrections recorded above. It is not a completed audit
or permission to skip the promotion gate. Review evidence was checked against
the owner's corrections; suggestions are not architectural authority.

| ID | Reviewer finding (verbatim excerpt) | Disposition |
|----|--------------------------------------|-------------|
| R1 | "S0 must annotate the parent event-derivation and `_maintain` reaping as **retained obligations**" | Obligation accepted, rationale corrected. `_wake_master()` requests prompt owner-loop delivery after the child publishes an immutable event. The 0.5-second maintenance clock drains before `Thread.is_alive()` inspection so quiet exit is observed. A swallowed `call_soon_threadsafe()` `RuntimeError` normally means the loop is closed; maintenance on that loop is not its recovery path. |
| R2 | "Same shape" means fixing the *broker* source discipline, **not** forcing `BaseReactor` to absorb the command channel. | Superseded by the exact-copy/subclass direction. The command remains authoritative in its local queue and only publishes a latch, but the workspace now subclasses `BaseReactor` so broker and local inputs share the same owner/arbiter implementation. |
| R3 | "the compliant fix is either a source-level debounce or an owner state that stops re-arming the waiter" | Superseded after checking real waiters. PostgreSQL/Redis waiters are edge-triggered and live saturation is unproved. Cursor-aware PEEK source policy prevents retained rows from staying ready; the paced snapshot confirms domain state without a second scheduler. |
| R4 | "Confirm the refresh path is the named edit site for the fixed-control vs dynamic-chat split." | Accepted. S0-Summon names membership refresh and pending checks, using existing `QueueMode.PEEK` rather than a new role registry. |
| R5 | "the reply handle must outlive `shutdown_requested` until the outcome is published" | Obligation accepted, mechanism narrowed. The owner retains correlation and reply route through committed release, then creates/writes/closes the transient reply queue; it need not retain a persistent queue handle. |

Reviewer factual correction: its statement that core `_sigint_handler` "is
already signal-safe" is false at the recorded baseline. The handler calls
`_stop_event.set()` and `_reactor_activity_event.set()` before its critical-section
branch. F3's physical-signal deadlock evidence and D1 remain load-bearing. The
existing deferred-raise policy is the part to preserve, not the locking calls.

Planning verification: plan-status index and documentation-path checks passed;
`tests/test_docs_references.py` passed (12 tests); `git diff --check` passed.
Changes remain documentation-only and uncommitted. All per-slice S0 maps and all
runtime work remain unexecuted.

## Execution Log and Fresh-Eyes Gate

### 2026-09-22 implementation start: S0-core

Implementation authorized by owner. Baseline `70ac379`; existing uncommitted
plan and backlinks preserved. Core audit independently performed by `core_audit`
and checked by the implementation owner. BASE-1/2 reuse the copied topology
owner, broker session, wait body and retained strategy; BASE-3 retains the
local latch/backend confirmation/deadline classifier; BASE-4 needs no new core
OS adapter. The custom BaseReactor loop must enter the copied topology scope,
service foreign requests and discharge/fail them on exit. Cursor mechanics
remain Taut policy. Cache refresh runs before dispatch so owner topology mutation
is legal. Copy digest matches `9fc913c1`; 0.9.106 is identical.

Producer inventory: client join/leave, reply and implicit subthread membership,
both DM memberships, fresh/resumed channel rename, client inbox claims and
watcher notification claims. State mutations publish after commit; no cursor
write or persistence load publishes. All readers treat all hints alike. The
shared-queue keep-newest warning is intentional coalescing: SB-DELIVERY-9's
atomic newest-ID contract and concurrent-writer test preserve a newest pending
hint. It is a pending-window bound, not a physical storage bound.

Promotion: strategy A at baseline `70ac379` plus the working spec diff. D0/D1/D2,
D2a/D2b/D6 promoted to core/identity specs before runtime edits; obsolete interval
and owner-only admission statements corrected. Summon/MCP/TUI promotion remains
per-slice. Tests must prove public ownership and cleanup outcomes, not retain
old duplicate `_session` or `_queue_cache` fields for compatibility with tests.


At execution record comprehension answers, applicable S0 matrices/current and
restored graphs, exact reviewed spec corrections, promotion baseline, red/green
evidence, reviews and all disposition/deletion outcomes here. Planning is not
implementation.

Final fresh-eyes check: Summon has one post-identity reactor; MCP nesting serves
contexts, each workspace subclasses the shared copied scheduler path, and
its parent observes only inner events plus parent-owned lifecycle;
each owner/arbiter, arbiter-observable input and source origin is explicit; every
OS source has a named adapter/reason and every removed loop's obligation still has
proof; cache invalidation is a broker input to that same reactor rather than a
second event system; required platform/backend/traceability gates pass. Verify any owner-authorized landed
commits with `git log`; report an uncommitted review state honestly otherwise.

### 2026-09-22 S1 and cache publication checkpoint

All four retained locks changed only SimpleBroker 8.3.1→8.4.0 and applicable
PostgreSQL 4.3.1→4.4.0 entries; manifests and current floor statements updated.
Root environment installed with dev/all extras. Core source bridge review found
one preserved Taut contract upstream lacks: unsupported yield-strategy rejection.
The minimal copied-constructor guard is the reviewed divergence above; no new
wrapper or compatibility scheduler is added.

Cache publisher red: nine new assertions failed for missing hints/diagnostics
before implementation. Green: ten cache tests (including owned-runtime subclass
construction) and the full client suite, 293 passed together. Hint publication
uses one helper accepting the owner's queue factory, catching both acquisition
and write failure after commit; no exception detail or unbounded payload is
logged. Public `watch(watcher_type=...)` is the smallest reuse seam for Summon's
policy subclass and retains client-owned construction/cleanup. Root typing
checks passed for client/helper/tests. Watcher consumer/native proofs remain
in progress.

S0-MCP/TUI map accepted: two finite existing-child bootstrap/admission handoffs
precede broker construction, then the initialized workspace enters BaseReactor
on that same thread. Parent does no filesystem or broker work. Identity loss
publishes its result then stops the child; parent retains its tombstone and
must reject pending commands without waiting on a retired owner. TUI keeps its
one-shot join observer, confirmation cancellation adapter and serialized client
worker, which own distinct non-broker obligations. No parallel broker observer
was found. MCP/TUI specs promoted by their slice owner before runtime work,
with identity-loss clarification recorded as a narrow promotion-order deviation.

S0-Summon map accepted: injection, control and lifecycle share one foreground
reactor after bootstrap. Atomic S3b+c is required because the current control
thread serves STOP before orientation, while chat construction follows
orientation; separating those edits would remove that capability temporarily.
S3a independent implementation review required owner-side formatting and immutable
handle/text/generation capture, worker-start rollback and non-poison infrastructure
failure. These are correctness fixes within the agreed reuse seam.

### 2026-09-22 integration checkpoint

Core tests: 2237 passed, four platform skips, six policy failures. Five coverage
marker failures came from the in-flight old/new Summon overlap; the remaining
failure was copied upstream Ruff annotation provenance. Preserve copied bodies:
three exact source-scoped annotations map to reviewed local groups, retaining
all rule/cardinality/raw checks. Mapping red/green and scanner suite: 30 passed.
MCP retained strategy uses SB defaults, as admitted before workspace resolution;
old MCP did not honor workspace polling settings. No double initialization or
mutable strategy reconfiguration is introduced. MCP core tests 312 passed;
live-PG conformance/restoration ten passed; TUI chat/Summon adapters 53 passed.

Full PG extension run: 44 passed and two failures. One cleanup expectation
requires reconciliation with the sole copied session owner; the no-native-waiter
case exposed a real upstream capability gap under investigation. No green claim
is made for this backend fallback until its regression passes.

PG fallback disposition: successful waiter construction returning `None` is not
an error, but PostgreSQL also returns no data-version source. The copied
scheduler then had no persistent fallback hint. BaseReactor now detects this
capability combination and reuses inherited degraded confirmation on the same
strategy pass. No added timer, copied-body change or second scheduler. Full PG
extension rerun: 46 passed; shared core PostgreSQL run: 281 passed. Quiet SQLite
and physical-signal proofs remain green.

Cache payload is deliberately reason-only. The planned optional identity/thread
inspection fields carry no authority and were omitted to keep one bounded
publisher signature; consumers never filter by payload. Runtime/schema contract
is unchanged. New invalid-subclass rejection proofs pass before runtime creation.
Initial-snapshot race and peer-hint-overwritten-by-own-hint proofs both pass.

Full TUI run while Summon migration is in flight: 461 passed, one lifecycle
crash-budget mismatch (three generations instead of two on declined setup
recovery). Summon owner is correcting the regression before final verification.

### 2026-09-22 independent core/MCP implementation review

Claude safe-mode read-only review, 600-second bound, completed in560.7seconds.
Result success/end_turn, terminal_reason=completed, is_error=false, no blocker.
The reviewer attempted a write but its tool set denied it; no review write occurred.

Verbatim result:

Write is disabled, so I'll deliver the review directly.

# Review: S1/S2/S2b/S4 Reactor Restoration Runtime Delta

Baseline `70ac379`. Read-only source tools only; no commands/agents run. Summon out of scope.

## Verdict: **no blocker**

No P1. The exact-copy scheduler, the `BaseReactor` owner bridge, cursor/cache policy, and the MCP single-source workspace are internally consistent and match the accepted contracts. Four P2/nonblocking items follow — all owner-decision, none required.

## Existence / wiring verifications (positive)

- `Queue.latest_pending_timestamp`, `has_pending(after_timestamp=)`, `peek_many` exist in installed SimpleBroker 8.4.0 (`sbqueue.py:1817,1801,1092`) → new calls at `watcher.py:2081,2234` and `_workspace_reactor.py:291` resolve.
- `PollingStrategy.{consume_local_activity_hint, consume_native_activity_hint, uses_native_activity, replace_activity_waiter, detach_activity_waiter, notify_activity}` exist (`simplebroker/watcher.py:1499,1513,1525,1546,1529,1484`).
- **Critical no-lost-wake check:** `BaseWatcher._start_strategy` calls the instance hooks `self._on_data_version_change(q)` and `self._create_activity_waiter(queue)` (`simplebroker/watcher.py:535,537`). Deleting `TautWatcher._start_strategy`/`_on_data_version_change`-refresh is therefore safe — the SQLite data-version hook stays wired to `MultiQueueWatcher._on_data_version_change` (`watcher.py:1004`).
- `taut.cache_stale` (with a period) passes SimpleBroker name validation ("letters, numbers, periods…", `db.py:611-613`).
- **F9 quiet pass:** persistent-SQLite no-hint path returns `"continue"` in `_activity_hint_action` (`watcher.py:1219-1257`) without calling `_has_pending_messages()`; zero per-queue queries. Covered by `test_watcher.py:2779,2368`.
- Removed fields (`_reactor_activity_event`, watcher-owned `_session`/`_queue_cache`, `_strategy_generation`, `_waiter_replacement_critical`, `_ensure_polling_strategy_started`) have no live readers in scope; remaining `_session`/`_queue_cache` hits are the unrelated client layer. `test_watcher.py:3711` asserts the field is gone.
- SIGINT matches D1: `BaseReactor._sigint_handler` (`watcher.py:1801`) raises immediately outside the critical section, defers via `_topology_deferred_sigint` inside it; cleanup runs on unwind (`run_until_stopped` finally → `_finalize_run` → `stop()`). Membership refresh sits at the top of `_drain_queue` (`watcher.py:2232`) before `_topology_dispatch_pass` is set → F15 owner-synchronous mutation legal.

## Findings

### [P2-1] Dead `_signal_stop_requested`; normal SIGINT path no longer latches stop state
`taut/watcher.py:1807`. The attribute is assigned but never initialized and never read (sole tree hit is this write). The new normal path sets only `_stop_requested`, writes the dead attribute, then `raise KeyboardInterrupt` — loop exit depends purely on exception unwind. Traced as safe: only `StopWatching` is caught in the loop, `_dispatch`'s `except Exception` can't swallow `BaseException`, and unwind reliably reaches `stop()` (sets `_stop_event`). **Disposition (owner decision, nonblocking):** delete the dead assignment; comment the exception-only unwind if intentional.

### [P2-2] Every consumed notification triggers a full membership reread
`taut/watcher.py:2222-2228` (claim publishes `taut.cache_stale`) + `2232-2237` (`_drain_queue` runs `_refresh_memberships()` on any newer hint, reason ignored per `_cache_stale.py:18`). A claim never changes membership, yet its own coalescing hint forces a reread, fanned out to every co-watcher waking on the shared `keep_newest=1` row. Bounded (cursor advances same drain), so correct. **Disposition (nonblocking):** accepted-risk-adjacent; acceptable, note the reread is unconditional/payload-blind by design.

### [P2-3] Redundant per-turn `latest_pending_timestamp()` on the cache-stale queue
`taut/watcher.py:2233-2234` queries `latest_pending_timestamp()` each active `_drain_queue`, in addition to the cursor-aware `has_pending()` already used for wake eligibility (`watcher.py:1787`) — two reads of the same one-row queue per active turn (quiet F9 invariant still preserved). **Disposition (nonblocking):** optional consolidation onto the existing PEEK cursor; low value.

### [P2-4 / observation] Initial-snapshot cursor race is redundant, not lossy
`_workspace_reactor.py:288-292` captures cursors before the initial `peek_inbox`; a notification landing in between is double-counted (redundant later snapshot), never dropped. Matches the plan's "racing event remains pending" intent. Same safe pattern in `TautWatcher.__init__` (`watcher.py:2074-2083`). No action.

## Nonactionable observations

- `client.watch(watcher_type=...)` assigns `watcher_class` before validating, but validation short-circuits on non-types (`isinstance(..., type)` before `issubclass`) and raises before use — safe. New minimal reuse seam for the out-of-scope Summon subclass, already logged in S1.
- `MultiQueueWatcher.__init__` docstring still reads ":func:`weft._constants.load_config`" (`watcher.py:208`) — stale copied text; real shim is `taut._config`. Cosmetic.
- `taut.cache_stale` self-publish inside a dispatch pass (`watcher.py:2225`) is a plain `Queue.write`, not a topology mutation → does not trip the dispatch-pass guard. Correct.
- MCP `_source_changed` sets `snapshot_pending` before advancing the cursor (`_workspace_reactor.py:327-328`); obligation cleared only after successful `peek_inbox` (`:484`, `:423`); `next_wait_timeout` is `None` when idle, bounded only while pending (`:330-335`) — no busy loop.

## Accepted risks confirmed present, not worsened
Advisory hint absent/failed for raw/mixed-version mutators on both backends (`_cache_stale.py:21-24` swallows post-commit failure, preserves committed result; tests `test_cache_stale.py:81-111`, `test_reactor_restoration.py:84-93`); no periodic refresh; local wake after one bounded native pass; two-line `yield_strategy` guard the only divergence (`watcher.py:214-215`); one reactor per context with a broker/filesystem-free MCP parent and finite two-`queue.get` bootstrap (`run_workspace_reactor:615,630`). All consistent with stated allowances.

Note: I attempted to persist this to the plan file, but `Write` is disabled for this session, so the review is delivered inline above.

Disposition: P2-1 accepted, removed dead assignment outside copied block.
P2-2 retained: filtering own/unrelated hints is unsound with coalescing;
payload-blind refresh is the explicit contract. P2-3 retained: bounded one-row
query on a confirmed turn; avoiding it is optional optimization, not restoration.
P2-4 no action: redundant refresh closes the startup race, verified on both
backends. Copied Weft docstring stays intact for source equivalence.

### 2026-09-22 S6 measured source work

Bounded real-strategy probe (40 hot writes at nominal 50 ms spacing) counts calls
without changing returns. CPU includes writer/reader threads, excluding external
PG server CPU. These are local observations, not performance guarantees.

| Owner/source | Wall seconds | Process CPU seconds | Strategy calls | Results |
| --- | ---: | ---: | ---: | --- |
| MCP SQLite quiet | 2.0006 | 0.0130 | 40 | 0 snapshots |
| MCP SQLite hot | 2.7379 | 0.3844 | 4471 | 6 snapshots, 40 pointers |
| Core SQLite quiet | 2.0023 | 0.0197 | 36 | 0 deliveries |
| Core SQLite hot | 2.4946 | 0.2698 | 4472 | 40 deliveries |
| MCP PG quiet | 2.0011 | 0.0040 | 1 | 0 snapshots |
| MCP PG hot | 3.2585 | 0.2729 | 85 | 7 snapshots, 40 pointers |
| Core PG quiet | 2.0040 | 0.0032 | 1 | 0 deliveries |
| Core PG hot | 2.9366 | 0.2726 | 80 | 40 deliveries |

SQLite hot calls track SimpleBroker initial bursts per publication; no sustained
CPU saturation or former millions-of-calls spin. Required quiet SQLite
cursor-query count is separately pinned by firing tests with one/twenty chats.
MCP baseline race test on SQLite/PG: two passed. It inserts a source row after
the baseline query returns but before Ready and proves the pointer remains
eligible for the next snapshot.

Summon parent review identified the ControlClient custom read loop wrapped
around a shared waiter as incomplete restoration. Move it onto a bounded reply
BaseReactor subclass. Parent also suspected signal-frame locking, but the slice
owner correctly rejected that claim: installed SB8.4 notify_activity is a single
boolean assignment. Retain that upstream path, prove physical held-lock safety.
The actual signal mismatch is run_forever installing a different SIGINT handler;
Summon uses inherited run_until_stopped to preserve its installed handlers and
embedding no-install policy. No new wait or polling timer.

Core/MCP S1/S2/S2b/S4 and audited TUI S5 checkpoint is reviewed, with runtime
and focused behavioral checks green. The combined core/MCP review covered
floors and provenance after runtime implementation, rather than a separate
pre-runtime independent S1 dispatch; this sequencing deviation is explicit.
Summon S3 and final consolidated S6 gates remain active. Nothing is committed
or claimed ready to land.

Control-test migration disposition: retired ControlLoop/_ControlReactor tests
map to shared BaseReactor lifecycle proofs plus policy propagation and driver
whole-owner recovery tests. New real SQLite requester/responder proofs cover
correlation, same-request retry, non-retrying STOP, transient reply ownership,
blocked injection/control responsiveness and held cursor. Final STOP tests
require explicit finalized outcome before ACK. Focused control+architecture:
49 passed, mypy/Ruff clean. Required coverage marker parser: six passed.

### 2026-09-22 independent Summon slice review

Claude safe-mode read-only review, 600-second bound; completed in 582.7 seconds,
success/end_turn, completed, is_error=false. No file written. Verbatim result:

ExitPlanMode is unavailable, so the review above is my final deliverable (no file written, no changes made).

**Summary — Verdict: no blocker (no P1).**

The Summon S3 restoration correctly collapses to one foreground `SummonReactor(TautWatcher)` after identity, with a real in-flight delivery gate (`_reactor.py:105`,`110`), owner-only cursor advance on flushed success (`99`,`141`), STOP responsive under blocked injection/orientation, signal-frame publish-only (`_driver.py:1894`), and release-before-ack (`_driver.py:483`/`494`, `controller.py:300`). `ControlLoop`/`_ControlReactor`/the dedicated control thread are gone; `ControlPolicy` is owner-invoked and `ControlClient` uses one persistent reply `BaseReactor` with no custom read loop. I verified every base seam the subclasses depend on exists in `taut/watcher.py`, and the central proofs in `test_reactor.py` (retained-row not refetched; cancel/fail preserve cursor; poison policy; worker-start rollback) match the code.

Four nonblocking P2s for the slice owner's disposition:
- **[P2-1]** readiness deadline now covers spawn+orientation (tighter than HEAD) — confirm or re-anchor the clock.
- **[P2-2]** unguarded reply-client creation in `_run`'s `finally` can mask the outcome — wrap it.
- **[P2-3]** transient SIGINT install in `_ReplyReactor.run()` on the CLI path — benign, note it.
- **[P2-4]** departed-thread audit-queue handles linger to reactor close — bounded/accepted.

Non-actionable: worker-start failure is fatal-to-run (defensible), discarded inert `handler` arg, and nudge serialized via phase-worker rather than the delivery gate (equivalent). Accepted risks are present and not worsened.

Dispositions: P2-1 accepted, reanchor readiness after orientation to retain
the prior contract. P2-2 accepted, reuse the still-live bootstrap client for
final reply and preserve cleanup/error precedence. P2-3 retained, bounded
standalone reply reactor uses core signal wrapper. P2-4 not accepted as
harmless: fixed auxiliary chat leases could grow with unique membership churn.
Rate policy instead borrows managed chat queues from the existing watcher
topology, eliminating its duplicate membership discovery and fixed leases.
This retains the same advisory cache-hint boundary, not a new refresh timer.

Independent narrow lifecycle review added four accepted findings: source
acquisition needed immediate cleanup coverage; consumed native phase results
needed a retained broker-policy continuation; spawned handles needed ownership
publication before pump.start; cleanup failure must not skip later owners.
Tests and implementation corrections are tracked in the new owner-lifecycle
suite. The parent additionally required source recovery to respect its actual
deadline before replaying broker continuations, not merely before spawning.

Readiness callback disposition: [SUM-13.1] requires owner-inline prompt return,
and promises correlated control from other threads. The prior test's blocking
STATUS inside that callback relied on the deleted peer control loop. Keep the
inline callback; test peer STATUS after handle publication. No nested loop or
callback worker is added. TUI decline's exact spawn-count assumption likewise
needs a causal exit-before-readiness fixture, not production timing padding.

OS cancellation latch disposition: attach shutdown is the published shutdown
event, observed by the POSIX select loop and the Windows bridge between
passes. The driver wake Event was cleared by both adapters and never changed
control flow. It is removed from `AdapterHandle.attach`. Shutdown alone ends
the bridge.

### 2026-09-22 final gate execution

A combined `pytest tests extensions` invocation was rejected at collection:
package-specific strict markers and duplicate module basenames require their
own pytest roots. xdist rendered this as an internal worker-finish assertion;
serial collect isolated the three configuration/import errors. No runtime
result was inferred. Final tests use separate existing project configurations,
with coverage subprocess instrumentation and isolated coverage-data prefixes.
No marker policy or collection setting was weakened to force a monolithic run.

Static reconciliation retires suppression groups 064 and 091 with the removed
watcher supervision; 066 drops two deleted MCP catches, 067 drops four obsolete
Summon boundaries, and 070 drops six retired thread test captures. Groups
093–095 preserve the exact copied upstream annotations via source-scoped mapping.
Raw inventory reflects these deletions plus the explicit cache-publication,
worker-result, and copied cleanup boundaries; no new blanket ignore or threshold.
Registry/scanner tests: 43 passed. Core and tests mypy: 140 files passed.

Used-skill evaluation: call-agent's restricted tools successfully contained
review attempts to write, and completion signals were checked independently of
exit status. No skill rewrite needed. Long reviews must put full findings in
the final JSON result; the final brief explicitly asks for that after a slice
review returned only its summary. Testing runbook's causal barriers remain
necessary when removing scheduling layers changes race timing.

### Final independent integrated review

Restricted external Claude review completed successfully (`success`, `end_turn`,
`is_error=false`, 376.378 seconds). Full returned findings follow. Its blanket
statement that none affect correctness is too strong for P2-2: cleanup masking
is a real failure-path defect and is being corrected with a firing test.

I've existence-checked every symbol and flow in the delta against the current files and their call sites. Here is the scoped review.

## Verdict: **no blocker**

The uncommitted runtime delta is internally consistent. All eight accepted corrections are present and correctly wired, and no dangling references to removed machinery survive in runtime code.

### Accepted-correction verification (all confirmed against current files)

1. **`_open_owner_source` acquires under cleanup** — `_driver.py:820-880`. On any `BaseException`, `reactor.stop(join=False)` then `client.close()` run before re-raise; `self._watcher` cleared. Control is rebound (not re-created) on replacement (`_driver.py:867-871`). ✅ (see P2 caveat below)
2. **`_phase_result` retained until acceptance; no repeat spawn/attach; ownership before pump** — `_apply_phase_result` clears `self._phase_result` only after `_accept_phase_result` returns (`_driver.py:1082-1083`); `_accept_spawn` is idempotent on a retained `_owner_running`/handle (`1134-1144`) and publishes `self._handle`/generation before `_start_generation_pump` (`1147-1155`). Terminal unwind captures a pending spawn handle and closes it (`_retire_owner_generation`, `904-914`). ✅
3. **All cleanup owners attempted, primary preserved; STOP carries close/release failures** — `_teardown_generation` (`1499-1548`) and `_join_pump` fold secondaries via `_add_cleanup_note`; `_finalize_stop_shutdown_outcome` freezes teardown/release facts into the outcome that `finish_stop` sends (`1870-1885`, `_control.py:387-400`). ✅
4. **Retry deadline gates continuation/delivery, not terminal/STOP; no custom sleep** — `_source_recovery_pending` (`969-974`) short-circuits phase work but runs after signal/pump handling; delivery gated via `reactor.delivery_enabled` (`840-843`); wake bounded by `_owner_wait_timeout` (`951-967`), no sleep loop. ✅
5. **Rate policy borrows managed watcher topology** — `_reconcile_audit_threads` reads `reactor._chat_queue_names` + `reactor.get_queue` on the owner thread, opens no fixed leases (`_control.py:402-409`). ✅
6. **Callback inline, promptly** — `_publish_owner_ready` invokes `_on_ready` inline on the owner (`1326-1329`). ✅
7. **30s readiness anchored at listen start** — set in `_listen_owner_turn` (`1023-1027`), not spawn budget; enforced by `_check_owner_readiness_deadline` (`1010-1021`). ✅
8. **`_ReplyReactor` is a real `BaseReactor` subclass, no custom read loop** — `_control.py:613-683`; overrides only unguarded hooks, drives via `reactor.run()`. ✅

Cross-checked wiring: `client.watch(..., watcher_type=SummonReactor)` matches `watch`'s signature and instantiation (`client/__init__.py:305-358`); `SummonReactor(runtime, member_id, handler, **kwargs)` forwards correctly; `run_workspace_reactor(inbound, strategy, stop_event, outbound, wake_master)` matches its call site (`_process_reactor.py:316-318`); none of the new subclass overrides collide with `REACTOR_LIFECYCLE_METHODS`; `_shutdown_error` and `_cursors` are initialized before first use; `_LEDGER_QUEUE_NAME`, `_tag_control_fault`, `CACHE_STALE_QUEUE_NAME`, `capture_cleanup_failure` all resolve.

### Non-blocking observations [P2]

- **[P2-1] Dead module-level names in `_control.py`** left by the `ControlLoop`→`ControlPolicy` fault-recovery removal, with no remaining references: `_STOP_ACK_TIMEOUT_SECONDS` (`:66`), `_RATE_AUDIT_RECOVERABLE_FAILURES_BEFORE_DEGRADED` (`:69`), `_CONTROL_DRAIN_RECOVERABLE_FAILURES_BEFORE_DEGRADED` (`:70`), `_is_broker_surface_failure` (`:98`). (`_CONTROL_REPLY_RECOVERABLE_FAILURES_BEFORE_DEGRADED` is distinct and still used.) *Disposition: prefer removal.*

- **[P2-2] `_open_owner_source` cleanup can mask the primary** (`_driver.py:873-880`): if `reactor.stop(join=False)` or `client.close()` raises, that exception supersedes the bare `raise` of the primary — unlike the sibling `client.watch` cleanup (`client/__init__.py:361-369`) and `_close_owner_generation` (`_driver.py:882-891`), which use `capture_cleanup_failure`/`add_note`. Only reachable on a stop/close fault over a fully-constructed reactor, so consistent with accepted correction (1)'s intent but not fully preserving primary. *Disposition: mirror the `capture_cleanup_failure`+`add_note` idiom for parity.*

- **[P2-3] Unused `timeout` param retained** in `controller._confirm_released` (`controller.py:296`, `del timeout` at `:299`). The single-shot check is correct now that the STOP ack fences release; the parameter is vestigial. *Disposition: drop or document for signature stability.*

None of these affect runtime correctness; the reactor-restoration delta is sound as frozen.

Note: I did not create a plan file or call ExitPlanMode — this task was a read-only review, and its instructions ("Read-only tools … do not try Write or ExitPlanMode") govern over the generic plan-mode workflow.

### Final review dispositions and local qualification

All three final review items accepted: removed dead control-loop constants/helper;
source acquisition cleanup now attempts stop and close separately, preserves the
original failure and attaches both secondary errors; removed the unused internal
release-check timeout argument. A fault test reproduced the masked primary before
the correction. Owner/control tests: 61 passed; release tests: 3 passed.
The parent inspected the final cleanup ordering. An additional real-thread test
proved cleanup interrupts only a live injection worker, not a retired worker
whose result is pending; all 7 reactor tests passed.

Real PostgreSQL Summon probe: public foreground run with an actual scripted child
passed one readiness callback, correlated status/PING, actual chat receipt,
correlated STOP and physical owner retirement. Its disposable schema was removed.
This is execution evidence, not a durable parametrized Summon PG suite: the
existing Summon fixture remains SQLite-only. Core PG and MCP PG have durable
regression suites.

Final broad runs: core 2254 passed / 4 platform skips; MCP 316 passed; TUI
462 passed. PostgreSQL: core extension 46 passed, shared root contracts 281
passed, MCP 10 passed. The first broad Summon run loaded two stale test fixtures
before their corrections and returned 592 passed / 2 failed / 10 skipped; both
failures were reproduced as fixture contract mismatches and corrected. A fresh
portable run is the final post-correction gate. All executed live-provider tests
in the broad run passed. Skips: six Windows native paths, one Linux zombie-group
path, two Darwin libc-fallback paths, and one absent local Ollama model. Native
Windows/Linux qualification remains open; mock results do not close it.

Runtime line-count measurement includes new modules and excludes tests/docs:
Summon 10786 → 10112 lines before the final dead-name removal (674 fewer); MCP
3254 → 3271 (+17, shared lifecycle replaces raw wait arbitration); core
19752 → 20518 (+766, primarily the complete upstream scheduler copy). The
restoration removes duplicated scheduling, not every domain transition or test.

Documentation maintenance check found an existing archive backlog: 120 indexed
plans (100 completed, 5 superseded, 10 active, 1 status-review, 4 retired-pending),
102 completed/superseded non-exemplars without a retired-ledger row. Lessons have
94 dated entries, 46 past the watermark and 33 past the age floor before excluding
active-plan citations. Checked-deferred here: this work remains uncommitted and
platform qualification is open; no archive fold or watermark advance is claimed.
The index and retrieval-cue gates pass.

Final runtime scan of Summon driver/control/reactor and MCP workspace: no
`time.sleep` or direct `.wait()` arbitration remains. The three Summon thread
construction sites are the bounded injection worker, bounded native phase worker
and continuous transport pump; their results feed the owner. Core strategy
waits remain in the copied shared scheduler. The disposable PostgreSQL test
container was removed after all backend proofs. No commit, push or release was
performed; the plan stays active for outstanding native qualification and
owner-controlled landing.

Final independent narrow review of post-review corrections: no blocking
findings. It verified independent cleanup attempts/primary preservation, live
versus retired injection cancellation, and absence of callers of the removed
helper/timeout. Its focused verification passed 53 tests with zero skips.

Final post-correction Summon run: **589 passed, 9 platform skips**, 476.21s,
exit 0, excluding live-harness/local-model markers already exercised in the
preceding broad run. Combined 2053 subprocess coverage files;
`bin/check-required-coverage-paths.py` passed for every required child-process
and critical Summon path. No aggregate coverage-percentage claim is made.
Final policy/docs/scanner/coverage-parser tests: 52 passed. Ruff check and format
(266 files), core/tests mypy (140 files), documentation paths, plan index and
`git diff --check` all passed. Runtime remains uncommitted.

## Addendum A (2026-09-22): Remove residual failure armor

Status: planned, not implemented. Owner: the Summon slice (S3) of this plan.
Class: 5 (inherits). Hardening applies because this changes the Summon failure
and STATUS contracts.

### Why this addendum exists

The 2026-09-22 working-tree review found that S3 moved a supervisor retry loop
into the restored design instead of removing it. This plan asked for that
move: S0-Summon's "Specify serial chat-source recovery" and S3c's "Recover a
chat source by serial owner replacement" kept a supervisor behind the words
"owned deadline". The corrected [SUM-7.1]/[SUM-10] text then described it as
intended behavior. This addendum supersedes those two checklist items.
Retrying the arbiter is not a [BASE-4] source. It is the result of work the
owner is already doing. Weft does not rebuild a failed task reactor: an
exception from `process_once()` escapes `_drive_reactor_until()` and
`run_until_stopped()` (`weft/core/tasks/base.py:1155-1240`). Restart is the
manager's policy (`weft/core/manager.py:5944-5975`), triggered when it
observes the child process exit.

Governing rule for this addendum: armor must name a specific exception from a
specific real operation. "Something might go wrong" is not a reason to retry,
count, degrade or wrap an error.

### A1. Delete Summon source replacement

Evidence:

- `_driver.py:779-798`: a `while True` around `reactor.run_until_stopped()`
  catches `(BrokerError, OSError)`, discards the `TautClient` and
  `SummonReactor`, reopens both, and counts failures in the local `failures`
  against `_WATCHER_RESTART_BACKOFF` (`_driver.py:128`).
- The caught types are root classes. `BrokerError` covers deterministic errors
  (`QueueNameError`, `MessageError`, `IntegrityError`, `TimestampError`).
  `OSError` covers PTY I/O and `Win32IoError` (`_win32_io.py:97`), because the
  whole owner turn runs inside `run_until_stopped()`. A terminal fault is
  therefore handled as "rebuild the broker client."
- The retry delay does not gate the thing being retried. `_owner_retry_at`
  gates `_owner_turn()` (`_driver.py:973`). `SummonReactor._process_reactor_turn`
  still calls `super()._process_reactor_turn()` whenever `control_queue_name` is
  set (`_reactor.py:149-154`), so the failing broker reads rerun at once.
- `_open_owner_source()` (`_driver.py:782`) is outside the `try`, so a failure
  on reopen is fatal anyway. `failures` never resets.
- The only firing test, `test_recoverable_source_failures_replace_serially_then_exhaust`
  (`tests/test_owner_lifecycle.py:366`), injects
  `OperationalError("owner acceptance unavailable")` from `_apply_phase_result`,
  which does no broker I/O.
- Lineage: HEAD's `watcher_failures` loop (HEAD `_driver.py:1843-1951`)
  reacted to a separate watcher thread dying (`_watcher_failed`). S3 removed
  that thread, and with it the event. The reaction remained.
- SimpleBroker already owns lock/busy retry ([SUM-10]: "Queue retry remains
  SimpleBroker-owned"). The loop is a second retry layer, which the Out of
  Scope register forbids ("copied broker retry").

Required action:

- [x] Remove the loop, `_WATCHER_RESTART_BACKOFF`, the local `failures`, and the
  source-replacement write to `_owner_retry_at`. `_supervise` opens one source,
  drives it, and the `finally` performs the existing single cleanup
  (`reactor.stop`, `client.close`, `_close_owner_generation`). An exception
  from the owner turn escapes as a driver failure after that cleanup.
- [x] `_owner_retry_at` then has one meaning: the harness-crash restart deadline
  (`_driver.py:1257`). Rename it (`_harness_restart_at`) and rename
  `_source_recovery_pending` to match. Re-verify each reader: `_driver.py:830`,
  `:945-951`, `:961-966`, `:973`.
- [x] Keep the harness-crash backoff (`_owner_crashes`, `_backoff`,
  `TAUT_SUMMON_RESUME_BACKOFF`). The harness exiting is a real OS-source event,
  restarting it is Summon policy, and the delay is a real clock deadline.

Tests:

- [x] Delete `test_recoverable_source_failures_replace_serially_then_exhaust`.
  Rework `test_source_replacement_reuses_policy_and_preserves_audit_cursor`
  (`:92`) and
  `test_readiness_clock_starts_after_orientation_and_survives_source_replacement`
  (`:342`). Delete the source-replacement parts; keep any assertion that
  protects a surviving invariant.
- [x] Red/green: a real `BrokerError` from a real broker operation inside the
  owner turn escapes `_supervise` as a driver failure. After the escape, source
  resources are closed, the provider generation is retired, and the ledger
  claim is released or reclaimable by evidence ([SUM-11]). Use a real SQLite
  broker. Do not patch a broker-free method to raise a broker error.
- [x] `test_recovery_deadline_gates_retained_acceptance_and_chat_but_not_stop`
  (`:264`) keeps its intent under the harness-restart name.

Spec corrections:

- [x] [SUM-7.1] `04-summon.md:323-326`: replace "Source failure is serial source
  replacement" with: a broker or OS error escaping the owner turn ends the
  driver after normal cleanup, and restart is the caller's decision, made
  safe by cursors and the ledger.
- [x] `04-summon.md:1050-1056`: delete the source-replacement sentences. Keep
  "A healthy provider is not restarted merely because a broker source failed."
  It is now true because nothing restarts it.
- [x] `04-summon.md:1203-1206`: delete the "Broker source failure" failure-mode
  bullet, or reduce it to the driver-failure sentence.

### A2. Delete the control-reply failure counter and the `degraded` state

Evidence:

- `_control.py:344-375`: a reply write that fails with `(BrokerError, OSError)`
  increments `_control_reply_recoverable_failures`. At
  `_CONTROL_REPLY_RECOVERABLE_FAILURES_BEFORE_DEGRADED = 3` (`:68`),
  `_mark_unhealthy` sets `_unhealthy`. Nothing clears it: it is assigned only
  at `:308` (init) and `:425`. One burst of three leaves STATUS reporting
  `control_health=degraded` for the rest of the driver's life.
- `_mark_unhealthy` has one production caller (`:364`). [SUM-9]
  (`04-summon.md:593-603`) describes degradation from repeated drain failures
  and rate-audit faults, plus "closing and reopening the driver's owned broker
  handles". None of that exists: drain and audit errors now escape the owner
  turn, and `grep -i reopen taut_summon/*.py` finds nothing. The spec text
  describes the deleted `ControlLoop`.
- A failed reply means one STATUS/PING/STOP requester times out and retries.
  Its requests are idempotent ([SUM-9]; `ControlClient` retries at
  `_control.py:665`). A driver-side tally adds nothing that requester lacks.
- Consumers of `control_health`: the `SummonStatus.details` passthrough
  (`controller.py:340-354`), the live-harness readiness gate
  (`tests/test_live_harness.py:93-97`), and unit tests
  (`test_control.py:427`, `:722`, `:741`; `test_controller.py:86`, `:537`,
  `:922`). No TUI, MCP or CLI source reads it.

Required action:

- [x] A reply write failure logs a warning at the call site and is dropped;
  the requester's timeout and idempotent retry handle it. Delete
  `_control_reply_recoverable_failures`, the threshold constant,
  `_mark_control_reply_failure`, `_mark_unhealthy` and `_unhealthy`.
- [x] Remove `control_health` and `health_detail` from `_StatusSnapshot`
  (`_control.py:223-239`) and from the reserved-key list (`:80-81`). This is a
  STATUS contract change. Record it in CHANGELOG. `SummonStatus.details` is an
  open mapping, so typed consumers are unaffected. The owner may instead keep a
  constant `control_health="ok"` for one release. If so, record that as a
  deprecation, not as a health signal.
- [x] Rewrite `04-summon.md:589-603` so the reserved-key list and the
  `control_health` paragraph match. Rewrite the stale control-reactor test
  requirements at `04-summon.md:1307-1316` ("control-thread ownership",
  "partial replacement-construction stage", "between-turn reopen").

Tests:

- [x] Delete `test_status_reports_degraded_control_health_detail`,
  `test_control_reply_failures_close_transient_handle_and_report_health`
  (keep its transient-handle-close assertions as a smaller test) and
  `test_wrapped_locked_control_reply_does_not_immediately_degrade`.
- [x] Remove the `control_health` gate from `_fatal_readiness_reason`
  (`test_live_harness.py:93-97`) and its two tests (`:238`, `:244`).

### A3. Delete dead armor in `_tag_control_fault`

Evidence and scope: the fault-plane label is a reviewed, opt-in diagnostic, not
cruft (`docs/plans/2026-07-12-lazy-command-extensions-and-rich-tui-composition-plan.md:2313-2360`;
consumed at `controller.py:113,147`, `cli.py:231`, `commands/__init__.py:51`).
Only the inner guard is dead. The `try/except Exception` around `setattr` at
`_control.py:88-91` (`pragma: no cover`, "unusual immutable exception object")
guards a condition that cannot occur: every SimpleBroker exception class and
`OSError` accept attribute assignment. This was checked by instantiating each
class in `simplebroker._exceptions`.

- [x] Remove the guard. At the two call sites (`_control.py:655-656`,
  `:667-668`), replace `raise _tag_control_fault(exc, ...) from exc` with
  tag-then-bare-`raise`. The current form sets `exc.__cause__ = exc`.

### Examined and retained: [SUM-13] interaction-seam validation

The initial review proposed deleting the `except Exception -> DriverError`
wrappers and the return-type checks around `self._interaction` (`_driver.py`
`~1394`, `~1639`, `~1743-1777`). That proposal is withdrawn. `SummonInteraction`
is the public [SUM-13] embedding protocol (`interaction.py:380`). A separately
packaged host implements it (`taut_tui/summon.py:495`, which annotates
`terminal_availability` as returning `object` and loads the Summon API
dynamically). Validating what a host-supplied adapter returns, and translating
its exceptions into `DriverError`, is a real package boundary, not a
first-party type check.

### Other 2026-09-22 review findings to route (not armor)

- [x] Self-cancelled nudge/orientation write: `_handle_phase_failure`
  (`_driver.py:1081-1096`) re-raises `AdapterWriteCancelled` when the owner's
  own hard-breach interrupt cancelled the write. The owner caused that
  cancellation, so it is an expected outcome and should not be a driver
  failure. Fix the classification; do not add a catch.
- [x] Hard-breach interrupt: `_owner_interrupt` (`_driver.py:1287-1290`) calls
  `handle.interrupt()` on the owner thread. The Windows implementation blocks
  up to `_CLOSE_TIMEOUT_S` (`_pty_windows.py:183-200`). S3b required
  classifying the hard interrupt as either a bounded owner operation or a
  named source adapter. Record which it is, with the Windows bound as evidence.
- [x] Core: `TautWatcher._drain_queue` (`taut/watcher.py:2249`) can run
  `_refresh_memberships` after a foreign `stop()`. The resulting topology
  mutation raises `RuntimeError("watcher topology is stopping")`
  (`watcher.py:550`), and `run_until_stopped` does not absorb it. Skip the
  refresh once stop is set. Needs a firing test.
- [x] MCP: a degraded workspace thread now stops itself
  (`_workspace_reactor.py:346-351`). `ensure_workspace`/`detach_workspace` call
  `_reap_dead_owners()` without draining events first
  (`_process_reactor.py:404`, `:471`), so identity loss can be reported as
  `WORKSPACE_REACTOR_FAILED`. Drain events before reaping.

### Verification and rollout

- Gate: the Summon unit and owner-lifecycle suites, one real-SQLite driver
  failure test from A1, the live-harness readiness path without
  `control_health`, the docs-reference tests, and `bin/ruff_suppression_index.py`
  (removed `noqa` sites change registry counts).
- Rollback: revert the addendum commit. No persisted state changes shape;
  STATUS readers already treat `details` as open.
- Success signal after deploy: a broker failure in a live driver produces one
  driver exit with its original exception and a released or reclaimable claim.
  It does not produce a series of "source replacement" rebuilds.

## Addendum B: independent source and cruft evaluation (2026-09-22)

Owner correction: the previous local-verification summary did not establish
conceptual completion. S3 preserved an outer source-replacement supervisor and
its tests certified that machinery. Addendum A supersedes those checked items.
This pass independently traces the supplied review rather than treating its
confirmed/unconfirmed labels as authority. The baseline source documents remain
this plan's Source Documents, the program theory, startup context, hardening and
testing runbooks, and the current product specs and architecture notes.

### Event classification

The owner recalls a 2×2 with an internal/external axis and queue, timer,
OS/thread and PTY/FD events. The exact second axis has not been located; no new
matrix is asserted. Weft [CC-2.2.1] explicitly distinguishes source origin from
what the arbiter observes. Queue activity reaches the retained strategy through
its backend; in-process state publication uses its local notification; external
FD/PTY/process evidence is published by an adapter into that same local path;
clock work supplies the deadline. These are inputs, not four schedulers. MCP's
multiple contexts justify composition, not a second independent broker observer.

### Independently evaluated MCP findings

| Finding | Disposition | Boundary and evidence |
| --- | --- | --- |
| Terminal event versus reap ordering | Fixed | Ensure/detach reuse existing drain-before-reap. Two real-child regressions failed before and pass after; full MCP 318 passed, 10 PG skips. |
| Workspace `degraded` flag and required-constructor null guards | Removed | Terminal turn result owns stop; client/target/config are required and never cleared. |
| IdentityError plus TokenError tuple | Simplified | Subclass already covered. |
| Catch only TokenError on command | Retained | Ordinary duplicate-name failures are IdentityError too; widening would terminate a healthy workspace. Bound-identity disappearance has the narrower error. |
| Calling notification senders inside try | Retained | Callable returning Awaitable permits a synchronous factory failure as well as await-time failure. |
| Generation, phase, command-id and alias admission guards | Retained | Reject stale events and arbitrate different candidates; child filesystem facts are not simply trusted copies from the parent. |
| Ready event repeats already admitted metadata | Removal candidate | Same child resends frozen metadata. Keep admission guards; simplify payload/consumer together in a separate reviewed slice. |
| Optional fingerprints in live states | Narrowing candidate | Retirement legitimately clears these fields. Live-state invariant must not become fake attachment-recovery policy. |
| Dispatcher repeats server schema validation | Removal candidate | Only production caller has already validated advertised schema. Preserve defaults/extraction and core semantic validation. |
| Reaction errors identified by message text | Typed-boundary correction needed | Private text is not an error code. Coordinate core producer and CLI/MCP consumers; do not just broaden TautError handling. |
| Paced snapshot deadline and two admission Queue.get handshakes | Retained | Pending-work pacing and finite pre-owner handoff, respectively; neither is freshness polling. |
| Permanent parent maintenance timer and shutdown retirement polling | Open design debt | Thread-final publication precedes physical return. Need actual retirement evidence; deleting the timer alone can leak owners. No replacement join-thread framework added. |

### Summon corrections and separately evaluated debt

A1 removes outer source replacement. Harness restart remains an owner transition
on a real child-exit event with a real backoff deadline. A2 removes sticky
reply-health counters and STATUS health fields; request-local warning and
transient handle closure remain. A3 tags and re-raises the original exception
without making it its own cause. Pure control constructor-null guards and the
unused `_audit_peek_many(what=...)` wrapper are removed: the latter is replaced
by its existing direct Queue operation. Regression evidence: three red failures
for absent health fields/self-cause, then 41 control tests and three live-status
helper tests passed. This intentionally changes STATUS's optional details;
there is no constant pretend-health compatibility signal.

The POSIX attach wake-forwarder is a real extra polling bridge: it samples an
Event every 50 ms to feed a pipe into an already timed select. Its presence is
not justified merely by calling it an OS adapter. Removing it must preserve
shutdown, detach, terminal restoration and quiet process-exit behavior together;
no new observer is authorized by this finding. Windows interrupt runs a bounded
but potentially blocking cancellation/write operation on the owner, which needs
its own responsiveness proof. Neither is declared resolved here.

The Windows console cleanup retry loop is a separate boundary: public embedding
can execute it on a signal-receiving thread, but unconditional retries of every
BaseException are not justified by that fact. Distinguish transient interruption
from deterministic cleanup failure before changing it. Interaction return-value
validation stays because [SUM-13] is a separately implemented embedding boundary.

### Open core race: stop during membership reconciliation

A real SQLite barrier probe stopped the watcher after authoritative membership
read but before topology admission. The owner exited with
`RuntimeError("watcher topology is stopping")`. An entry-only stop check cannot
close that race: the copied scheduler checks stop during admission and again
before publication. No existing typed cancellation result or protected seam
separates expected stop from arbitrary RuntimeError. The smallest upstream fix
is a typed topology-stopping rejection (compatible RuntimeError subclass) at the
existing checks, followed by handling only that type in internal reconciliation.
This pass does not change the copied block, classify exceptions by message text,
or hold a new lock across broker work. The bug remains explicitly open.

### Independently evaluated core, TUI and tooling findings

| Finding | Disposition and owning boundary |
| --- | --- |
| Unused watcher interval/persistence fields; forwarding get_queue override | Removed; constructor inputs still reach their real base consumers. Inherited get_queue preserves the API. Existing watcher/cache regression suite is the substitute proof for behavior-preserving deletion. |
| Runtime optional close getattr | Removed; TautWatchRuntime requires close, including construction rollback. Cleanup precedence/retry behavior retained. |
| BaseReactor.cleanup and TautBaseWatcher alias | Compatibility decision remains open; absence of repository callers alone is insufficient. They add no scheduler. Lifecycle override guard stays because it enforces current ownership independently of legacy consumers. |
| TUI claimed_replies parameter | Confirmed removable private argument/empty merge. Preserve post-admission claim so superseded opens cannot consume unseen replies. Not changed in this slice. |
| Client label getattr in log/read/rendering | Confirmed removable first-party fallback. Repair incomplete fakes rather than preserve a nonexistent older object shape. Not changed here. |
| SimpleBroker iterator optional close | Retained; dependency iterator contract differs from concrete first-party runtime. |
| TUI optional release_current_worker | Retained under generic public interaction boundary. |
| TUI concrete interaction optional close | Confirmed removable first-party fallback. Not changed here. |
| Search job argument validation | Optional simplification, not reactor drift; preserve injectable clock/limit semantics used by expiration proofs. |
| Packaged defaults shape checks | Candidate for package-invariant tests; preserve actual resource/TOML failures and project-input validation. |
| Persistence dump validation | Retained: [PIO-4] explicitly requires canonical IDs, high-water checks and deterministic duplicate containment across a format boundary. |
| TUI swallowed BaseException in rendering | Needs narrow correction: retain primary domain failure and cleanup, report auxiliary presentation errors through existing path. Removing all containment would also violate [TUI-12.1]. Not changed here. |
| Debug send nested catch | Confirmed redundant because sole caller owns failure containment. Separate deduplication-search fallback has different behavior and stays. Not changed here. |
| Wheel-matrix options | Three CLI inputs are live. Private expected-return/process-group alternatives have no nondefault caller; removable separately. Platform termination/stdio owners stay. |
| Wheel list_live catch | Diagnostic defect: preserve actual startup exception in bounded failure outcome or narrow expected errors. Tooling observation itself is legitimate. |
| PG readiness environment knob | Not proven dead: operator tuning does not require a repository setter. Bounded disposable-service readiness is not production reactor polling. |
| Search provider duck typing/token clearing/TUI watcher degradation | Retained explicit extension, token-lifetime and WatcherRejected contracts. |

These dispositions are not a claim that every confirmed cleanup was implemented.
Broad validation and presentation cleanup remain separate from restoring the
central event path. No existing tests are discarded solely because they expose
an inconvenient boundary.

Summon-specific remaining inventory: `_GenerationFailure.failure` has no reader,
`completion` is test-only, and generation locking serializes owner-only callers.
The generation token is NOT dead: it fences stale pump results. Attach
cancellation is the shutdown event; the separate wake event was unused and is
removed. The
identity-selection for/else fallback is unreachable with the real name chooser;
the terminal-availability None branch is an internal invariant rather than the
claimed earlier-return proof. These are individual cleanup candidates, not
permission to delete all generation state. No changes to those paths here.

The own-cancelled nudge finding is confirmed: `_handle_phase_failure` re-raises
`AdapterWriteCancelled` after an owner hard-breach interrupt. It needs expected
cancellation classification. Windows interrupt is more serious than an assumed
bounded ten-second call: `_EpochWriter.interrupt` bounds cancellation/retirement
of the old write, then calls `_write_with_epoch(b'\\x03')` through a blocking
native write without that deadline. It cannot be classified as a bounded owner
operation. Route it through an existing native-operation worker/result seam,
with cancellation/retirement proof, rather than adding another scheduler. Both
remain OPEN and no native Windows qualification is claimed.

### Follow-up verification and limits

A1 driver/owner tests: 134 passed (115 driver + 19 lifecycle). Restoring the old
outer loop under the real SQLite relation-loss test produced the intended red
second-acquisition failure; the corrected source count, provider PID retirement,
closed client/session resources and released ledger assertions pass. Additional
cleanup-failure cases preserve the original broker exception. A1/A2 Summon spec
and implementation text now match the single-source runtime; controller fixtures
use live provider fields instead of obsolete health examples.

Controller/control: 81 passed. Core watcher/cache: 132 passed. MCP: 318 passed,
10 PostgreSQL skips in this follow-up; no new PostgreSQL qualification claimed.
Docs/reference/suppression gates: 46 passed. Mypy: 105 core/Summon source/test
files passed; MCP owner separately verified 24 source files. Ruff check/format,
path/index gates and diff check passed. Independent read-only review found no
blocker in A1–A3 or the small core deletions. The remaining defects explicitly
listed above are not covered by that no-blocker finding. No commit performed.

## Addendum C: finish identified issues (owner-authorized 2026-09-22)

The owner requests implementation of the remaining identified issues. This
supersedes Addendum B's deferral of confirmed defects/removals, not its reasoned
retention decisions. Four isolated ownership slices: core topology cancellation;
Summon native operations/cancellation and obsolete generation state; MCP
retirement/admission and duplicate schema checks; TUI/core/tooling cleanup.
Existing uncommitted work is preserved. No release/commit is authorized.

Invariants: one broker scheduler per context; only the owner changes broker,
cursor and lifecycle state; native adapters publish results without broker
access; cancellation does not advance chat cursors; terminal publication is not
physical thread retirement; cleanup preserves the original failure and reports
secondary failures. Existing public/extension validation is retained where the
audit established a real boundary. Compatibility aliases with unknown external
consumers remain unless the supported contract proves them retired.

The stop-refresh fix may require a minimal typed rejection in the copied
scheduler because its present RuntimeError has no typed cancellation identity.
Check upstream first. If still absent, record the exact local patch/provenance;
no text classification or broker-spanning lock. Native interrupt must leave the
owner responsive while reusing operation/result machinery. Parent retirement
must use existing asyncio lifecycle mechanics rather than a permanent poll or
one new joining thread per context. Real bounded native I/O waits stay distinct
from production broker polling.

Tests precede behavioral corrections, using real SQLite/children and deterministic
barriers at actual operations. Native Windows API simulation supplements but does
not claim native qualification. Existing suites/static gates prove mechanical
removals. Independent slice and final reviews check the resulting source graph.
Rollback is the corresponding source/doc change; no data migration is involved.
Post-change success: no replacement broker loop, no owner-blocking interrupt,
no lost retirement/identity cause, no exception-message classification, and no
silent presentation failure. Every B row receives a final disposition below.


### Final dispositions (supersedes Addendum B OPEN/candidate rows)

| Finding | Final action and boundary |
| --- | --- |
| Core stop versus membership refresh | Typed `_TopologyStopping(RuntimeError)` at three copied synchronous rejection sites; catch only this type during reconciliation. Upstream Weft cfa5bb21 still lacks this distinction. The three raises and existing yield guard are the recorded local divergences. Real SQLite barriers cover all three races; identical-text unrelated errors propagate. |
| Summon own-cancelled nudge/orientation | Classify owner-requested cancellation explicitly; unsolicited cancellation remains a failure. Delivery waits for operation retirement. |
| Owner-blocking hard interrupt | Reuse `_start_phase_operation`, result queue and wake latch. A concurrent interrupt slot is necessary to cancel an occupied write slot; it introduces no second scheduler. Cleanup requests close and retires both operations before provider teardown. |
| POSIX Event-to-pipe bridge | Delete its forwarding thread; the existing native select loop checks shutdown at its existing 100ms bound. Native PTY readiness remains an actual source adapter. |
| Windows deterministic cleanup failure | Retry genuine interruptions only; preserve primary failure and attach secondary cleanup failures. Native API simulation is supplementary, not Windows qualification. |
| Summon obsolete generation state | Delete unread failure/completion fields, owner-only lock, per-generation latch aliases and unreachable bootstrap fallback. Retain generation token and exit state, which have real consumers. |
| MCP parent maintenance and shutdown resampling | Delete permanent 0.5s and 10ms polls. A bounded standard executor owns workspace execution; completion callbacks use the existing master wake. Shutdown awaits owned completions once with a real deadline. Drain terminal causes before retirement. |
| MCP submission rollback | Python submit can enqueue before thread-start fails. Publish Bootstrap only after successful submit; existing Stop releases uncertain queued/running tasks at the first handshake without granting workspace authority. Two real Thread.start failure tests prove both races and successful later attachment. |
| MCP ready metadata and schema rechecks | Remove duplicate fields/checks; retain generation/admission/phase assertions, defaults and domain checks. Public server schema validation remains the single input boundary. |
| Reaction configuration classification | Export typed ReactionConfigurationError and consume that type in MCP; remove exception-message matching. Preserve packaged and project validation failures. |
| TUI claimed_replies and concrete close fallback | Remove unused parameter/empty merge and call concrete close directly. Preserve actual post-admission reply claim and generic public interaction release boundary. |
| Client labels, search job checks, debug nested catch | Remove impossible first-party fallbacks, duplicate annotated-type checks and nested failure containment. Preserve positive limit/injected clock and distinct deduplication-search behavior. |
| TUI presentation failure swallowing | Report ordinary render errors via existing notify path, preserving primary domain failure and state retirement. Interrupts propagate; no new reporter or waiter. |
| Wheel matrix private alternatives and readiness catch | Delete unused return-code/process-group alternatives. Preserve the actual ledger read failure and child cleanup; readiness polling is bounded tooling observation, not a production reactor. |
| Compatibility alias/cleanup/lifecycle guard | Retain supported public contracts. Unknown external usage is not proof of obsolescence; these create no extra scheduler. |
| Packaged defaults validation | Retain: TAUT-6.4 explicitly requires normalized resource, TOML, shape and regex failures. No optional first-party adapter fallback is being defended here. |
| Remaining retained B rows | Dependency iterator close, public interaction validation, persistence format validation, PG readiness tuning, provider duck typing, token cleanup and WatcherRejected behavior remain at their documented boundaries. Prior unused watcher fields/runtime-close fixes remain implemented. |

### Independent final review

The read-only Claude review completed with process exit 0, subtype success,
is_error false and stop_reason end_turn. Verbatim final response follows.

I have completed a rigorous, read-only review of all four Addendum C slices, verifying source against tests and the upstream schema boundary. My findings follow.

## Review summary

All four ownership slices are implemented, internally consistent, and covered by tests that precede/exercise the corrected behavior with real SQLite/children and deterministic barriers. I found no P1 defects and no new P2 defect that worsens the accepted baseline. Verification highlights:

- **Core topology cancellation** — Typed `_TopologyStopping(RuntimeError)` at the three synchronous admission/publication checks (`watcher.py:556,717,754`), provenance recorded in the module docstring (`watcher.py:1-11`) per the "record the exact local patch/provenance" instruction. `TautWatcher._drain_queue` catches only that type (`watcher.py:2249`). `test_membership_refresh_runtime_error_is_not_stop` proves a plain `RuntimeError` with the *identical* message propagates unchanged (`assert observed.value is failure`) — no message classification. `test_membership_refresh_racing_stop_is_clean` covers all three boundaries. No broker-spanning lock added.
- **Summon native operations/cancellation** — Interrupt runs as a concurrent `_interrupt_worker` via the existing `_start_phase_operation` helper, so the owner loop stays responsive (non-blocking). Self-cancellation (`AdapterWriteCancelled` + `_phase_cancel_requested`) is distinguished from failure in `_handle_phase_failure`. Cleanup uses `capture_cleanup_failure` primary-precedence. `_record_cleanup_interruption` fixes the prior infinite-retry-on-deterministic-cleanup-failure while tolerating interrupts (`test_windows_cleanup_does_not_retry_deterministic_failure`). POSIX pty uses the preexisting 100ms `select` sampling after removing the duplicate Event→pipe thread (accepted).
- **MCP retirement/admission** — `_maintain`/`MAINTENANCE_SECONDS` poll replaced by `ThreadPoolExecutor` `Future` completion + done-callback→`_wake_master` (asyncio lifecycle retirement, no permanent poll, no per-context join thread). `aclose` bounded by `asyncio.wait(timeout=SHUTDOWN_SECONDS)` with `os._exit(1)` backstop. Workspace reactor now subclasses `BaseReactor` and reuses the shared arbiter's native waiter (test patches `core_watcher.create_activity_waiter_for_queues`). Redundant `_on_ready` re-validation replaced by asserts backed by resolution-phase invariants. No dangling references to removed symbols.
- **TUI/core/tooling cleanup** — Presentation failures surface via `notify` (narrowed `BaseException`→`Exception`, preserving interrupts); `test_summon_presentation` asserts both. Typed `ReactionConfigurationError(TautError)` replaces the message-set match. `_commands.py` `cast` simplification is safe: `server.py:163` runs `validate_tool_call` before dispatch, and `_tools.py:371-377` enforces `since`'s `MAX_SAFE_JSON_INTEGER` bounds in the schema — the removed manual check is fully covered upstream.

```json
{
  "unit": "Addendum C — completion of remaining reactor/cruft defects",
  "verdict": "no blocker",
  "blocker_fids": [],
  "findings": [
    {
      "fid": "C-OBS-1",
      "severity": "P2",
      "slice": "TUI/core/tooling cleanup",
      "file": "bin/check-core-summon-wheel-matrix.py:730",
      "title": "Readiness-poll `list_live()` no longer tolerates a transient ledger read error",
      "trigger": "The 45s readiness loop now calls `controller.list_live()` directly (prior broad `except Exception: live = ()` removed). If the cross-process SQLite ledger read raised a transient error mid-poll (e.g. lock contention while the summon subprocess writes), the whole wheel-matrix check would abort instead of retrying on the next 0.05s tick.",
      "assessment": "Owner-authorized simple removal. Low real-world likelihood: simplebroker ledgers run WAL so concurrent reads do not normally raise 'database is locked', and the loop already handles driver death via `driver.poll()`. Surfacing a genuine `list_live` failure is the intended post-removal behavior; the old blanket except masked real failures too.",
      "disposition": "Accept as-is (owner-authorized). If CI flakiness later appears, wrap only the single `list_live()` call in a narrow, typed retry (broker read error) rather than reinstating a blanket `except Exception`. Not a blocker; expansion is an owner decision."
    }
  ],
  "non_actionable_observations": [
    {
      "ref": "interaction.py:311-320,218,280,299,335",
      "note": "`_record_cleanup_interruption` is invoked from `_wait_until_ready`, which also runs on the normal (non-cleanup) `run()` path (interaction.py:143). `threading.Event.wait(timeout)` does not raise except on interrupt, so on the happy path only KeyboardInterrupt/SystemExit/InterruptedError can reach it — and those are recorded-not-raised, so behavior is correct. The method name is slightly broader than its cleanup-centric intent. Naming only; no functional issue. Windows-only path; per accepted risk it cannot be natively qualified on Darwin (simulated native API proof is supplementary, not native qualification)."
    },
    {
      "ref": "interaction.py:316-320 primary-precedence",
      "note": "When an interrupt is recorded as primary first and a later non-interrupt cleanup error arrives, the earlier interrupt remains primary and the newer hard error is attached as a note before the primary is raised. First-failure-wins precedence with the secondary preserved as a note is consistent with the addendum's 'preserve original failure, report secondary'. No change needed."
    },
    {
      "ref": "_process_reactor.py executor lifetime",
      "note": "`ThreadPoolExecutor(max_workers=MAX_WORKSPACES)` threads are non-daemon (as were the prior `daemon=False` threads), so a permanently stuck workspace could block interpreter exit only if `aclose` were never called; `aclose`'s `os._exit(1)` backstop and the `len(entries)+len(candidates) >= MAX_WORKSPACES` admission gate (which matches worker count) keep the slot accounting sound. Equivalent to the accepted baseline; not worsened."
    }
  ],
  "b_row_dispositions": "Each deferred B slice is implemented and verified: (1) core topology cancellation — done, typed rejection + provenance; (2) Summon native ops/cancellation + obsolete generation state — done, concurrent interrupt worker, self-cancel vs failure, obsolete resolved-state fields removed from WorkspaceReady/reactor; (3) MCP retirement/admission + duplicate schema checks — done, executor completion replaces maintenance/shutdown poll, redundant re-validation removed, `_commands.py` trusts the retained `validate_tool_call` schema boundary; (4) TUI/core/tooling cleanup — done, notify-based presentation reporting, typed `ReactionConfigurationError`, simple bin removals. No reasoned B-retention decision (advisory cache hints/mixed-writer gap, public compatibility aliases, `TautBaseWatcher` alias) was disturbed.",
  "scope_notes": "Older accepted restoration in the HEAD diff was not re-reviewed as new; C does not worsen it. Accepted risks (POSIX 100ms select sampling, native-Windows non-runnable on Darwin, advisory cache hints, retained public aliases) were treated as governing and not re-litigated."
}
```

Review disposition: C-OBS-1 is accepted. A ledger failure must fail this diagnostic
with its original cause; blanket retries would hide defects. The new probe runs
the actual generated lifecycle block in a child and checks both original failure
and child retirement. No evidence establishes a transient read error requiring
retry. Naming and platform observations require no code change. The late
submit-ordering correction additionally received independent code review and a
fresh run of both real executor-failure tests: no blocker, no new lifecycle
mechanism. The call-agent skill's containment and completion checks were useful;
no skill change is indicated by this run.

### Final verification and residual limits

Fresh final commands/results:

- `COVERAGE_PROCESS_START=... COVERAGE_FILE=... uv run --no-sync python -m coverage run --parallel-mode -m pytest tests -n 4`: 2262 passed, 4 platform skips.
- Same coverage invocation for `extensions/taut_summon/tests -n 4 -m 'not requires_live_harness and not requires_local_llm'`: 592 passed, 9 native-platform skips. No new live-provider qualification claimed.
- Same coverage invocation for `extensions/taut_mcp/tests -n 4`: 322 passed, 10 PostgreSQL skips; this run includes the final executor rollback correction.
- Full TUI suite: 473 passed. Disposable PostgreSQL: core 46 passed and MCP conformance 8 passed; owned container removed afterward.
- Combined only the fresh core, Summon and final MCP coverage artifacts; `bin/check-required-coverage-paths.py --data-file ...` passed all required child-process/critical Summon markers.
- `uv run --no-sync mypy taut tests`: 140 files passed. Slice checks passed for Summon 29 files, MCP 24 files and changed core/TUI files.
- `uv run --no-sync ruff check .`, `ruff format --check .`, suppression registry, `uv run --no-sync bin/check-doc-paths`, plan index and `git diff --check`: passed. Documentation/reference/index/suppression pytest suite: 69 passed.

Initial broad-run failures exposed obsolete inventory entries, incomplete test
fakes and the newly exported exception's API inventory. Those fixtures and
inventories were corrected; the fresh full runs above supersede earlier failures.
Native Windows and Linux qualification remains outstanding. Source changes,
tests and aligned specs/implementation docs are uncommitted at owner direction;
no release or commit has been performed. The confirmed Addendum B defects are
resolved; retained boundaries are explicitly dispositioned above.

### Owner-authorized closeout (2026-09-23)

The owner requested closure and commit after the independent review and its
follow-up. The later native attach-interface cleanup removed an unused wake
argument on POSIX and Windows. The TUI confirmation follow-up restored its
single worker's bounded wait: a temporary daemon cancellation bridge left one
thread alive after each ordinary answer and was rejected on re-review. The
corrected path has no added thread or scheduler; focused confirmation/shutdown
tests passed. This final correction and the aligned TUI implementation note
were re-reviewed with no remaining finding.

Fresh post-review suites: Summon 592 passed, 9 native-platform skips; TUI
474 passed. Mypy passed for 44 changed Summon/TUI source files. Ruff check and
format, suppression registry, documentation paths, plan index, CLI claims,
documentation/reference pytest, and staged diff checks passed. Core, MCP and
PostgreSQL evidence appears in the preceding final-verification section; no
runtime code in those areas changed after those runs.

S6's combined backend/platform checkbox remains unchecked solely for native
Windows/Linux qualification. macOS tests, real SQLite and PostgreSQL tests,
Windows API simulations, independent review, source/doc checks and the scoped
post-review suites satisfy the implementation closeout. Native qualification
is a separately recorded limit, not a claim made by this commit. Advisory
cache-hint gaps and retained public compatibility boundaries remain as
dispositioned above. No release or deployment is part of this closeout.
