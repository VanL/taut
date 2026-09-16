# BrokerSession Integration Plan

Class: 5. This changes the normative persistent-resource ownership and supported
SimpleBroker floor in [TAUT-3.4], with worker-thread cleanup, constructor
failure, and replacement-lifecycle boundaries. Hardening is required.

Plan type: implementation with spec revision.

Status: active. Both plan-review rounds passed; all findings are dispositioned
below. The compatibility prerequisite is committed as `b9eaada`; the reviewed
spec delta and dependency floors are promoted from implementation baseline
`b9eaada`. BrokerSession runtime implementation is in progress.

## Goal

Adopt SimpleBroker 8.3's public `BrokerSession` for Taut-owned persistent
lifetimes. Make client and reactor shutdown release their own thread's cached
backend resources while peer owners remain usable. Fix the new reactor-worker
retention regression and the existing client-worker retention gap without
changing chat semantics, adding a global session manager, or making transient
CLI work persistent.

## Source Documents and Baseline

- Owner request: evaluate SimpleBroker 8.3.0, then plan proper BrokerSession
  integration rather than only the narrow reactor cleanup patch.
- Taut spec baseline: `c79b448351f0e0df1276ceefb41cb17dc34f7bf0`.
- Runtime prerequisite: `b9eaada`, owner-thread Queue cleanup repair with real
  peer-held tests on 8.2.2 and 8.3.0. Preserve this protection during migration.
- `docs/program-theory.md` [THEORY-2] through [THEORY-5]: Taut owns chat and
  application lifetimes; SimpleBroker owns broker mechanics and resource reuse.
- `docs/specs/02-taut-core.md` [TAUT-3.2], [TAUT-3.4], [TAUT-8.3],
  [TAUT-8.4], [TAUT-8.5], [TAUT-12.2], [TAUT-12.5].
- `docs/specs/03-identity-addressing-notifications.md` [IAN-8.2].
- `docs/specs/04-summon.md` [SUM-9];
  `docs/specs/05-taut-mcp.md` [MCP-3], [MCP-4], [MCP-8], [MCP-12];
  `docs/specs/10-taut-tui.md` [TUI-4.1], [TUI-6], [TUI-11.2].
- `docs/implementation/04-taut-architecture.md`,
  `docs/implementation/05-taut-summon-architecture.md`,
  `docs/implementation/07-taut-mcp-architecture.md`,
  `docs/implementation/10-persistence-io.md`,
  `docs/implementation/12-taut-tui.md`.
- Prior integration: `docs/plans/2026-09-14-simplebroker-8-2-config-migration-plan.md`.
  Preserve its resolved nominal Config handoff; do not resolve ambient inputs again.
- Upstream: SimpleBroker tag `v8.3.0`, commit
  `d5d5c81d32f325e27566e936b5ae77fd57259bed`,
  [Python library contract](https://github.com/VanL/simplebroker/blob/d5d5c81d32f325e27566e936b5ae77fd57259bed/docs/specs/16-python-library-api.md)
  [SB-API-3], [SB-API-6], [SB-API-11], and its
  `simplebroker/session.py`, `simplebroker/sbqueue.py`,
  `simplebroker/watcher.py`, `simplebroker/_broker_session.py`.
  Those last private modules are inspection/test evidence, never production imports.
- Process consulted: AGENTS, shared context, decision hierarchy, principles,
  engineering principles, testing and review runbooks, writing-plans,
  hardening-plans, adversarial-acceptance-probes, required lessons,
  agent inventory, and `skills/call-agent/SKILL.md`.

Promotion baseline: implementation begins from `b9eaada`; the exact reviewed
spec delta in this plan is now the governing contract for the runtime slices.

## Verified Problem and Upstream Semantics

The evaluation used real SQLite, a live same-target/same-Config peer queue,
and three successive `BaseReactor` workers. Every worker consumed a message,
requested stop, and joined. The peer kept the process session alive:

| Probe | 8.2.2 cores after successive worker exits | 8.3.0 |
|-------|------------------------------------------|-------|
| Reactor worker retirement | 1, 1, 1 | 2, 3, 4 |
| Persistent TautClient worker retirement | 2, 3, 4 | 2, 3, 4 |

Closing the last peer cleared all cores. An isolated diagnostic patch calling
public Queue cleanup on the retiring reactor owner restored 1, 1, 1 on 8.3.
The durable regression and narrow owner-thread cleanup are prerequisites in
`2026-09-15-reactor-worker-cache-compatibility-plan.md`. That repair is committed as `b9eaada`; slice 1 retains and extends its real-peer proof.

`Queue.close()` was already lease-only in 8.2.2. The new regression is the
8.3 change to upstream idle-watcher cleanup: Taut's custom run loop bypasses
`BaseWatcher.run()`, and `super().stop()` therefore takes the upstream idle
path, which no longer recycles a thread cache. Do not fix this by manipulating
upstream `_run_thread` or other private lifecycle slots. The upstream changelog
describes the idle-stop change as a feature without explaining custom-loop
subclasses; that omission is an upstream documentation gap.

The earlier isolated compatibility runs passed 460 core/client/state/watcher/
search tests, 97 TUI/persistence tests, 248 Summon control/controller/driver
tests, and 309 MCP tests. Seven MCP PostgreSQL tests skipped for lack of a DSN.
These are evaluation evidence, not acceptance evidence for implementation.

Load-bearing upstream details:

1. Equal target, backend options, and complete Config identify one process
   session. Separate BrokerSession handles on that key share one cache per
   thread. They are lifetime scopes, not isolated connections or transactions.
2. `session.queue(name)` makes a persistent scope-owned Queue. The session
   strongly retains every minted Queue until scope exit, including queues
   closed early. It does not deduplicate names.
3. `session.close()` recycles the calling thread, closes minted queues, then
   drops the scope lease. It rejects any active same-key operation on that
   thread before mutation, including an iterator from a different owner.
4. `recycle_thread()` releases only the calling thread's cache, deferring until
   operation unwind if necessary. It keeps the scope and queue leases alive.
5. Closing one scope must not invalidate another scope's queues; a later peer
   operation can reacquire a recycled cache. Pooled backend checkout return
   need not physically disconnect a server connection.
6. Scope exit preserves an active body exception and attaches ordinary cleanup
   failures. A cleanup BaseException retains upstream priority and can leave
   the scope partially closed for an explicit later close attempt.
7. Sessions are process-local. Do not send one through fork/spawn or replace
   Taut's existing process bootstrap with inherited live handles.

## Context, Files, and Ownership Design

### Files to modify during implementation

| Files | Current owner and required change |
|-------|-----------------------------------|
| `taut/client/_base.py` | Owns meta Queue and persistent name cache; introduce one lazily acquired scope for persistent queue requests and close it at owned lifetime end. |
| `taut/client/_watching.py`, `taut/client/__init__.py` | Own independent watcher state runtime and construction rollback; bound runtime scope and construction-thread cache without using the source client's scope. |
| `taut/watcher.py` | Keep direct queue construction and active-map ownership. BaseReactor gains a scope for thread-cache lifetime; TautWatcher retains membership churn/runtime close. Constructor rollback remains explicit. |
| `extensions/taut_summon/taut_summon/_control.py` | Fixed command queues, auxiliary queue retirement, and overlapping replacement keep direct Queue ownership. Change only if an owner/failure proof identifies a required repair. |
| Root `pyproject.toml`, `extensions/taut_mcp/pyproject.toml`, `extensions/taut_pg/pyproject.toml` | Core/MCP SimpleBroker floor 8.3.0; root dev and PG extension SimpleBroker-PG floor 4.3.0. No new dependency. |
| `uv.lock`, `extensions/taut_summon/uv.lock`, `extensions/taut_mcp/uv.lock`, `extensions/taut_tui/uv.lock` | Refresh all retained resolutions, preserving unrelated package selections where possible. |
| `README.md`, `CHANGELOG.md`, governing specs and implementation notes above | Current floor and lifecycle rationale, backlinks, and Unreleased note; historical releases/plans are not rewritten. |
| Existing tests named below | Real lifetime, churn, failure, peer-survival, and backend acceptance evidence. |

Read, and modify only if a new proof identifies a necessary owner-boundary
repair: `extensions/taut_tui/taut_tui/session.py`,
`extensions/taut_mcp/taut_mcp/_workspace_reactor.py`,
`extensions/taut_summon/taut_summon/_driver.py`.
Their clients already open/use/close on dedicated owners. Do not rewrite those
hosts merely to mention BrokerSession. `taut/_watch_runtime.py` need not gain
an upstream-session requirement for third-party runtime implementations.

### Client scope

- `_ClientBase.queue()` decides persistence using the existing per-call
  override. Acquire a BrokerSession only at the first persistent request,
  passing the already resolved `self.target` and full `self.config`.
- Persistent name-cache misses use `session.queue(name)`; hits return the same
  plain public Queue. The existing cache already retains one Queue per name
  for the client's lifetime. Do not mint again on every call.
- A default transient client can still own a persistent scope:
  `notification_activity_queue()` explicitly asks for `persistent=True`.
  Conversely, `persistent=False` on a persistent client stays uncached and
  transient, as required for Summon request-specific reply queues.
- Persistent meta state uses the same client scope. A transient meta queue
  remains separately owned. `close()` calls scope close rather than separately
  closing every minted queue, then releases any separately owned transient
  meta handle. It is idempotent and does not create a session just to close it.
- Do not drop references or clear ownership markers before a close attempt
  that upstream may reject. On failure preserve the references needed for an
  explicit retry; let the upstream scope own its internal partial progress.
  Constructor/schema failure closes the partially built scope and keeps the
  original construction error primary over ordinary cleanup failures.
- Client ownership ends at close. First-party hosts create a fresh client for
  another lifetime. Do not add automatic client resurrection or claim new
  cross-thread safety. Retained public Queue objects continue to have upstream
  close/reuse semantics; this plan does not change Queue itself.

### Reactor scope and bounded queue retention

One persistent reactor owns one BrokerSession solely for the lifetime of its
thread-local backend cache. Resolve it from the reactor's existing exact
`_db_path` and full `_config`, after normal queue setup has resolved that target.
Initialize the optional scope slot before fallible setup so rollback can tell
whether a scope was acquired. Transient synchronous reactors acquire no scope.

Keep **all reactor queues directly constructed and owned as today**, including
initial queues, dynamic memberships, and auxiliary/audit queues. They share the
scope's process-session key without being minted by it. Existing active maps
and their identity-deduplicated close loop retain queue-lease ownership;
removed queues are evicted and closed immediately. The reactor session holds
no minted queues, so it cannot retain closed membership history. Do not add a
per-queue lifetime flag, a `queue.session` classifier, new factory indirection,
or a fixed-versus-dynamic construction split in the neutral scheduler.

This consumes [SB-API-3]'s public same-key recycling contract: one owner-thread
`session.close()` recycles the cache used by all same-key direct queues and
releases the scope lease. The explicit scope keeps backend lifetime anchored
independently of the current queue set and supplies cleanup without choosing
a surviving Queue. Queue cleanup alone remains a valid narrow bug fix; this
plan intentionally adopts explicit lifetime ownership as requested. Queue creation through the session is useful for the
client and the single-handle metadata runtime, but is unnecessary for the
reactor's already explicit, changing queue topology. Keep those mechanisms
separate by their real lifetimes, not by a blanket construction convention.

On partial queue construction failure, close each acquired direct handle
locally even if base construction never returns; on failure after scope
acquisition, also close that scope. Preserve the original construction error
over ordinary cleanup errors. Scope adoption does not excuse existing partial
queue ownership gaps.

The single owner still runs turns, native-waiter replacement, and shutdown.
After queue/sidecar operations unwind, close the strategy/current waiter, then
call `session.recycle_thread()` before `session.close()` on the owner. Close
direct queue handles through independent cleanup paths so a scope failure cannot
skip their lease release. Recycling first schedules cache release at operation
unwind even if a remaining same-key operation makes scope close refuse. It does
not guarantee immediate release while that operation remains open, and ordinary
backend cleanup failures still need reporting. Scope close
must not be delegated to a stop caller while the worker lives, and normal
cleanup must no longer depend on upstream idle-stop cache recycling.

A never-driven reactor may be closed by its caller. A foreign stop after a
normally completed worker is idempotent; it must not recycle the stop caller's
unrelated cache. Abnormal foreign cleanup after owner exit may release residual
leases and recycle only its caller's cache, never reclaim the dead worker's cache.

### Watcher runtime and construction-to-drive handoff

The source client, reactor queues, and watcher metadata are independently
owned. `_OwnedWatchRuntime` uses its own small BrokerSession for its single
persistent metadata queue (no session for transient mode). This preserves the
existing runtime protocol and avoids passing a session through third-party
`TautWatchRuntime` implementations. Its scope is closed on the watcher owner
from the existing runtime teardown hook. Equal configuration makes its cache
shared with the reactor scope, so this is an additional lease, not another pool.

`client.watch()` constructs and queries the runtime on its caller before a
background watcher may drive elsewhere. Before returning the constructed
watcher, recycle that construction thread through the live runtime scope,
without closing either scope or the source client. Use an internal concrete
runtime helper, not a new required method on TautWatchRuntime. Cover failure
before and after reactor construction. This intentionally may recycle a
same-key source-client cache on the caller; the next source-client operation
reacquires. No queue ownership transfers to the source client.

Ordinary reactor construction must not create a cached backend core merely by
constructing its Queue handles; prove this with the real backend. If a constructor path does
perform owned I/O, close/recycle its construction-thread resource before
handoff. Advanced callers doing their own pre-drive Queue operations retain
responsibility for recycling those operations' thread before it retires.

### Extension lifetimes

| Host | Required boundary and proof |
|------|-----------------------------|
| TUI session | `_client_owned` and `_close_owned` stay on the serialized executor. Watcher creation on that executor then `start()` on another thread exercises handoff. Stop watcher before client close; still attempt client cleanup after watcher timeout without closing a live watcher's queues. |
| MCP workspace | `_validate` and `_cleanup` stay on workspace owner. Close activity waiter before client scope. Detach/rejected candidate releases the worker cache even while another workspace scope on the same target survives. Preserve deadlines and forced-exit policy. |
| Summon control | `ControlLoop._open` constructs on control thread, not `__init__`. `_make_broker_handles` partial failure closes new owners. Install replacements between turns before retiring old scopes; replacement handles must work after same-thread cache recycling. |
| Summon pump/watcher attempt | `_pump` and `_run_watcher_attempt` retain local try/finally ownership. Watcher and client scopes are distinct; both close after their work unwinds. |
| Borrowed control handles | `ControlClient(owns_request_queue=False)` and injected factories never gain ownership of a borrowed Queue or BrokerSession. |

### Comprehension gate

Before editing, implementers record answers in Execution Evidence. A wrong
answer blocks implementation until the named source is reread:

1. Why not mint every membership queue from one long-lived session? Expected:
   upstream retains closed minted queues until scope exit; churn would grow
   retained objects without bound. All reactor queues remain directly owned
   in active maps; the explicit scope still recycles their shared-key cache.
2. Does one session per client mean one isolated connection per client?
   Expected: no; same-key scopes share a per-thread core, including same-thread
   active-operation and recycling effects.
3. Why does parent-thread close not fix a retired worker cache? Expected:
   cleanup addresses only the calling thread; worker finally owns release.
4. Why must a transient client sometimes have a scope? Expected: explicit
   persistent notification/activity queue requests override its default.

## Invariants, Errors, and Hidden Couplings

- Only public `simplebroker` / `simplebroker.ext` production APIs. No private
  process-session access, runner cleanup, backend retry, or `_run_thread` repair.
- Preserve Config object semantics, custom fields, namespace, target resolution,
  source-client independence, message IDs, cursor order, notification claims,
  broadcast atomicity, history/search behavior, and all CLI/MCP record shapes.
- No schema, stored format, identity, trust, or transaction-boundary change.
  `session.connection()` is not a cross-call transaction and is not needed here;
  leave `open_broker()` persistence and broadcast scopes alone.
- Cache invalidation on one thread must not close another thread's cache or
  invalidate a peer's live handles. Same-thread recycling between operations is
  allowed; active same-key operations must finish before scope close.
- All queue iterators and sidecar/connection contexts unwind before retirement.
  Closing from a handler, signal, active operation, or recovery callback is
  forbidden; retain stop-intent and between-turn recovery seams.
- Clean success: queues released, thread cache returned, peer still usable.
  Failed constructor: partial scopes released and original error remains primary.
  Active-operation close refusal: no ownership markers cleared and caller can
  finish the operation then close successfully. Repeated close: no new resources.
- Do not set terminal cleanup-complete flags before upstream preconditions pass.
  Preserve existing stop/join synchronization; distinguish cleanup-in-progress,
  cleanup-complete, and retained failure where needed in that same mechanism.
  Concurrent callers cannot become a second closer. Do not hold a lock across
  a join or broker I/O needed by the worker.
- Ordinary cleanup failures must not hide a running application exception.
  Direct client close with no body exception surfaces its error. Reactor
  cleanup must attempt independent owned resources even after an ordinary
  failure, preserve the active run exception, and keep failure visible through
  its existing error/diagnostic boundary. Do not silently label incomplete
  cleanup successful or add retry-by-error-string logic. Respect upstream
  BaseException partial-progress semantics; do not blindly repeat a failed
  iterator close.
- `TautClient` is not generally thread-safe. Preserve existing worker ownership;
  do not assert total field isolation (the watch runtime still shares the
  display-name dictionary). No new public process/fork or post-close reuse
  guarantee; first-party hosts use fresh clients in new processes/lifetimes.
- No detached work, new executor, daemon, temporary persistence, or extra user
  configuration. Existing host stop/cancellation bounds do not expand.

## Rollout and Rollback

Use the coordinated published floor pair SimpleBroker 8.3.0 / SimpleBroker-PG
4.3.0. Root and MCP directly require the core floor; PG extension and root dev
require the PG floor; Summon/TUI receive core through their existing paired
Taut dependency. Do not add redundant direct dependency declarations.

Promote text first, then implement and test in slices, but ship the runtime
changes and floor refresh as one coherent version. This task does not publish,
tag, or change Taut package versions. Existing `>=8.2.2` already admits 8.3,
so the separate worker-cache compatibility repair was landed first as `b9eaada`. That repair must
be released to protect fresh installations; the lock is not a compatibility
guard. The new floor declares use of BrokerSession, not the first exposure.

There is no 8.3-specific storage migration or one-way data change. Rollback is
reverting this code/spec/manifest/lock unit and restarting affected processes
with the previous resolved 8.2.2 / 4.2.1 pair. Preserve the prerequisite worker-cache repair when reverting this integration.
Reverting that repair too while leaving 8.3 selected restores the reactor leak. Never suggest
an in-place package swap inside a running process or a rollback to pre-v8
storage readers. Publication, if later requested, follows [TAUT-12.5] separately.

After deployment, exercise repeated TUI target switches and MCP attach/detach
while a peer stays active; database handles or checked-out resources should
stabilize, workers should join, and peer reads/writes/control replies should
continue. Use existing diagnostics or a local probe; no new telemetry subsystem.

## Proposed Spec Delta

Promotion strategy: A, text in existing files before implementation-link claims.
The promotion slice also adds this plan's backlink. Below is exact replacement
or insertion text; it is proposed until that slice executes.

### [TAUT-3.4] ownership paragraph

In `docs/specs/02-taut-core.md`, replace the paragraph beginning
“Persistent Queue handles for one resolved target” through “Taut does not
recreate SimpleBroker connection release or retry policy” with:

> Taut uses SimpleBroker's public `BrokerSession` to own persistent client and
> reactor lifetimes. A scope is acquired from the already resolved target and
> complete Config; it does not reread environment or project configuration.
> Scopes with equal process-session keys share backend resources and one cached
> core per driving thread. They are not isolated connections or transactions.
>
> A client acquires its scope lazily on its first persistent queue request,
> including an explicit persistent request on an otherwise transient client.
> Its name cache returns plain public Queue handles minted by that scope.
> Explicit transient requests remain transient and uncached. `TautClient.close()`
> ends the owned lifetime on its resource-owning thread, closes the scope and
> separately owned transient metadata handle, and is idempotent. It must not
> create a scope solely for cleanup. First-party callers close every open
> same-key iterator and sidecar/connection context before close and use a fresh
> client for a new lifetime. No general cross-thread client safety is implied.
>
> A reactor owns a separate scope from its source client for its thread-cache
> lifetime. Reactor queues remain directly owned, same-target/same-Config
> persistent Queues in the existing active maps. Queue creation through the
> scope is not required for same-key cache recycling. Membership and auxiliary
> queues are evicted and closed at retirement; their objects must not accumulate
> in the scope. The watcher metadata runtime has its own independently closed
> scope for its metadata queue, sharing the reactor's process-session key
> without sharing the source client's ownership.
>
> Queue close releases that Queue's lease; scope close also recycles the
> calling thread's cache. Scope close requires that no same-key operation is
> active on that thread, even through another owner. A rejected close leaves
> ownership intact for a later valid close. Closing another same-key scope
> between operations may recycle this thread's shared cache, but surviving
> handles remain usable and reacquire it. Workers release their cache on their
> own thread before retirement; a foreign stop caller cannot reclaim that
> worker cache. Construction-thread I/O is recycled before handing a watcher
> to its drive owner. Taut does not recreate SimpleBroker's connection,
> session-registry, or retry policy.

Append to the compatibility-history paragraph:

> Version 8.3.0 supplies public BrokerSession scope ownership and explicit
> per-thread recycling. Taut integrates these lifetimes rather than relying
> on an upstream watcher's idle-stop path to clean its custom reactor loop.

### [TAUT-8.5] shutdown paragraph

Replace “A foreign caller may close only after the owner thread exits; an
instance that was never driven may be closed by its caller.” with:

> A normally completed owner has already released its thread cache and scopes;
> subsequent foreign stop calls are idempotent and do not recycle the foreign
> caller's cache. A never-driven instance may be closed by its caller. Abnormal
> foreign cleanup after owner exit may release residual leases and recycle only
> its caller's cache; it cannot reclaim the dead worker's cache.

Append after that shutdown paragraph:

> The owner closes active queue/sidecar operations before its BrokerSession
> scopes, including on exception, stop during a turn, and bounded-run return.
> The reactor calls `recycle_thread()` before scope `close()`, so an active
> same-key operation that refuses close still has cache recycling scheduled
> for its unwind. Failed finalization remains observable and retains incomplete
> scope ownership for explicit cleanup.
> Activity waiters and strategy resources are retired before their owning
> scope. Client, reactor, and metadata runtime scopes are independently owned;
> closing the source client cannot close a live watcher's queues. Repeated
> membership and auxiliary-queue churn retains objects in proportion to live
> topology, not the number of prior joins and leaves. Partial constructor
> failure releases every acquired scope without replacing the constructor's
> original exception with an ordinary cleanup error.

### [TAUT-8.3] notification lifetime clarification

After the paragraph documenting `notification_activity_queue()`, insert:

> A persistent activity queue requested on a transient client belongs to that
> client's lazy BrokerSession scope and ends with `TautClient.close()` under
> [TAUT-3.4]. This does not make the client's ordinary operations persistent.

### [SUM-9] resource-release clarification

In `docs/specs/04-summon.md`, replace the paragraph beginning “Operation release
ends only the active lease” with:

> Operation release ends only the active lease. The control reactor and its
> client own independent BrokerSession scopes under [TAUT-3.4] and close them
> on the control owner after the current turn unwinds. Retirable auxiliary
> queues are not retained for the scope's full lifetime. Recovery may install
> a complete replacement before closing the old scope; same-thread cache
> recycling must leave replacement handles usable. Summon must not recreate
> broker release/retry policy, and borrowed request queues remain borrowed.

### [MCP-3] and [TUI-4.1] owner teardown clarification

In `docs/specs/05-taut-mcp.md` [MCP-3], after the frozen target/config paragraph:

> Each resident workspace closes its client-owned BrokerSession on the workspace
> owner, after activity-waiter and active-operation cleanup, including rejected
> attachment and detach. Another resident owner on the same target may keep the
> process session alive; this does not defer the retiring worker's cache release.

In `docs/specs/10-taut-tui.md` [TUI-4.1], after the worker ownership paragraph:

> The session worker closes its client scope on that worker. A watcher built
> there has independent scope ownership: construction-thread I/O is recycled
> before handoff, and the watcher drive thread releases its own cache and
> scopes before exiting. Client shutdown does not close a surviving watcher's
> queues, including when its bounded stop times out.

### Exact supported-floor substitutions

Apply these literal substitutions to maintained current claims only:
`simplebroker>=8.2.2` becomes `simplebroker>=8.3.0`;
`simplebroker-pg>=4.2.1` becomes `simplebroker-pg>=4.3.0`.
Normative homes are `docs/specs/02-taut-core.md` [TAUT-3.4] and its Core runtime
requirements paragraph, `docs/specs/03-identity-addressing-notifications.md`
[IAN-8.2], and `docs/specs/04-summon.md` [SUM-9]. Do not rewrite historical
version provenance or claim that 8.3 changed the SQL schema/backend API version.
Align README and the maintained implementation claims listed above in the
implementation/documentation slices. Preserve the persistence-format version.

## Tasks and Gates

0. **Immediate compatibility prerequisite: complete.** The separately reviewed
   `2026-09-15-reactor-worker-cache-compatibility-plan.md` repair is committed as
   `b9eaada`. Keep its regression test when replacing Queue cleanup.

1. **Spec-promotion and dependency preparation.** Apply only the reviewed delta
   to the five named specs; add backlinks and record promotion baseline.
   Raise the exact manifest floors and refresh four locks through uv. Keep
   unrelated dependency upgrades out. Read the prior config migration first.
   Verify metadata consistency, resolved core/plugin versions, documentation
   paths, and plan index. Stop if resolution demands unrelated upgrades or
   a schema/backend-version change appears. Done: one explicit contract and
   reproducible 8.3.0/4.3.0 development environment, no compatibility shim.

2. **Client scope and runtime owner.** Add failing real tests to
   `tests/test_client.py` for retained peer + client-worker retirement,
   persistent overrides, independent clients, constructor failure, idempotent
   close, and active same-key close refusal with a later successful close.
   Implement client scope in `_base.py` and runtime scope/handoff in
   `_watching.py` / client `__init__.py`. Preserve ephemeral helpers and cache
   identity. Update core architecture rationale. Stop if this requires passing
   private sessions through public runtime protocols or automatic resurrection.
   Done: tests demonstrate actual cache release and peer usability, not merely
   that a mocked close method was called. Independent slice review.

3. **Reactor scope, handoff, and churn.** Add failing tests to
   `tests/test_watcher.py` before changing the existing constructors/factories,
   `BaseReactor` finalization, and TautWatcher runtime cleanup. Prove the 8.3
   retained-peer regression and constructor handoff. Keep every reactor Queue
   directly owned in the existing maps; the reactor scope owns cache lifetime
   only. Replace the interim Queue cleanup with `recycle_thread()` before
   scope `close()`; prove deferred recycling when close refuses. Do not change Summon's `_control.py` construction/retirement merely to
   adopt session minting; repair it only if a new owner/failure proof requires
   it. Preserve waiter replacement and
   all final lifecycle templates. Test scope precondition rejection, partial
   construction, stop races, and failure priority. In particular, the nested
   `run_forever()` finally blocks must preserve an active handler/run exception
   if ordinary scope cleanup also fails; use a firing BS-8 fault-injection proof. Stop if another lifecycle
   engine or upstream private state is proposed. Done: no retired-worker core,
   no retained historical membership handles, no peer disruption. Independent
   slice review with special attention to constructor/cleanup exception paths.

4. **Host integration and real backend proof.** Extend existing TUI, MCP, and
   Summon tests with the owner scenarios below. Repair hosts only where tests
   show actual gaps; their existing executor/thread topology remains intact.
   Run real PostgreSQL proof with a held peer and checked-out resource return,
   including native-waiter replacement and fallback polling. Stop if a backend
   fault would be hidden with mocks or timeout increases. Done: owner retirement
   is demonstrated on SQLite and PostgreSQL and all affected host contracts pass.

5. **Traceability and closeout.** Align all maintained dependency and ownership
   prose, add Unreleased changelog note, rerun final gates, and obtain independent
   completed-work review. Record each finding disposition and any justified
   deviation. Evaluate the heavily used skill/runbooks for improvement; promote
   nothing without a concrete reusable correction and its own required scope.
   Update related maps only if ownership/files actually moved. Implementation
   completion requires owner-authorized landing verified with git log; otherwise
   report exact changed files as uncommitted, not implementation complete.

## Testing Plan

Real Queue, BrokerSession, SQLite, sidecar SQL, thread coordination, and peer
handles must stay real. Keep an anchor on exactly the same target and Config
through every worker exit; otherwise last-lease shutdown masks a missing
worker cleanup. Synchronize via events and checked joins, not sleep-as-proof.
Never close a live worker's resources to make a timeout pass.

A narrow test-only resource observer may inspect/spy on upstream cached-core or
checkout release, as existing tests already instrument broker internals.
Centralize that observer in a new `tests/helpers/broker_resources.py` if needed
(new file, not an existing API). Do not change production code to expose private
session state, and do not infer resource release merely from Queue.close calls.
Pair observer evidence with public read/write, cursor, and peer-survival checks.
For pooled PostgreSQL, measure returned checkout, not physical socket closure.
Root `tests/test_watcher.py` is marked SQLite-only: add the corresponding
retained-peer client proofs in `extensions/taut_pg/tests/test_pg_sidecar.py`
and reactor/handoff proofs in `extensions/taut_pg/tests/test_reactor.py`,
marked `pg_only`. Passing the root watcher file to a shared PG selector would
not run those proofs.
Ordinary cleanup fault injection may wrap a real public cleanup method and
raise after/before its real work as the particular test states; do not replace
the entire broker or duplicate its lifecycle implementation in a fake.

Every case below needs a firing test; group parametrized variants where useful:

| ID | Required proof | Test home |
|----|----------------|-----------|
| BS-1 | Persistent client handle identity; upstream public queue.session identifies the owning scope only for client/runtime-minted queues; directly owned reactor queues have queue.session is None; two clients share backend key but closing one leaves peer read/write working | `tests/test_client.py` |
| BS-2 | Default transient client creates no scope for ordinary work; explicit persistent activity queue gets one; persistent client's transient override stays transient | `tests/test_client.py` |
| BS-3 | Three real client workers retire while peer remains: no worker cores/checkouts retained; repeated close creates no new connection | `tests/test_client.py` |
| BS-4 | Meta/schema construction failure after lease acquisition releases all partial resources and preserves original error | `tests/test_client.py` |
| BS-5 | Open real same-key iterator/sidecar through a peer: assert public RuntimeError base (never import the private refusal class), no ownership cleared; unwind, close succeeds; peer remains usable | `tests/test_client.py`, `tests/test_shared_contract.py` |
| BS-6 | Three real reactors retire with peer held: clean stop, handler failure, bounded run, and stop during active turn all release only after unwind | `tests/test_watcher.py` |
| BS-7 | Caller-thread watch construction then worker drive; caller cache recycled before handoff; worker cache released after join; source client and another watcher survive | `tests/test_watcher.py` |
| BS-8 | Recycle-before-close with a real open same-key operation: close refuses with `RuntimeError`, cache retires on unwind, peer remains usable. Never-driven stop, thread-start failure, repeated/foreign stop, concurrent stop, partial constructor failure, and ordinary/BaseException cleanup preserve ownership and error priority | `tests/test_watcher.py` |
| BS-9 | Repeated membership leave/rejoin and auxiliary retirement free removed Queue objects; retained count bounded by live topology; no stale cached handle reuse | `tests/test_watcher.py`, Summon `test_control.py` |
| BS-10 | Replacement constructed before old scope closes; partial replacement failure and between-turn recovery preserve complete installed set and control replies | `extensions/taut_summon/tests/test_control.py` |
| BS-11 | Borrowed request queue not closed; one-shot reply queues remain transient; worker pump/watch attempt teardown releases resources | Summon `test_control.py`, `test_driver.py` |
| BS-12 | Repeated TUI target switches/worker shutdown; client cleanup still attempted after watcher timeout while independent watcher queue remains usable | TUI `test_tui_chat.py`, `test_tui_domain.py` |
| BS-13 | MCP same-target peers, detach/re-attach, rejected/failed candidate, and shutdown release worker caches on owner with waiter-before-scope ordering | MCP `test_process_reactor.py`, `test_pg_conformance.py` |
| BS-14 | Resolved Config/target retained with ambient env changed; assert the supplied Config is retained across session acquisition, including namespace/custom fields; public facade and isolated-wheel checks stay green | `tests/test_constants.py`, `test_project_config.py`, `test_project_metadata_consistency.py` and installed-wheel lane |

New cases get exact test names in the execution log. Existing acceptance seams
include `test_persistent_client_reuses_queue_handles_and_closes_them`,
`test_notification_activity_queue_is_reused_and_closed_by_client`,
`test_taut_watcher_membership_churn_closes_removed_queues`,
`test_control_loop_constructs_and_closes_persistent_handles_on_owner_thread`,
`test_partial_control_handle_construction_closes_every_created_owner`,
`test_control_loop_recovery_never_waits_on_retired_reactor`,
`test_reopen_preserves_rate_audit_cursor_and_closes_old_handles`, and
`test_session_close_without_wait_returns_promptly_despite_parked_commit`.
Rerun them, but do not confuse call-count checks with the added resource proof.

The CLI/parser itself does not change. Apply adversarial floors through existing
CLI failure, cancellation, and repeated-invocation suites; no synthetic new
input grammar or new error code is introduced. Any observable error-shape or
exit-class drift requires a declared spec revision, not a blanket snapshot update.

## Verification Commands

During dependency preparation, use `uv lock --upgrade-package simplebroker
--upgrade-package simplebroker-pg` at root, then `uv lock --directory
extensions/taut_summon`, `uv lock --directory extensions/taut_mcp`, and
`uv lock --directory extensions/taut_tui`. Inspect selected versions and all
manifest copies. Do not refresh packages simply to reach today's latest versions.

Per slice, run the relevant files with the resolved root dev/extension extras.
Final local gate commands (normal current platform; do not run Windows native
cases on POSIX):

```bash
uv sync --extra dev --extra all
.venv/bin/python -m pytest tests/test_client.py tests/test_state_sqlite.py tests/test_shared_contract.py tests/test_watcher.py tests/test_search.py -n 4 --dist loadgroup
.venv/bin/python -m pytest tests/test_persistence_io.py tests/test_persistence_io_adversarial.py -n 4 --dist loadgroup
.venv/bin/python -m pytest extensions/taut_summon/tests -m 'not windows_only and not requires_live_harness and not requires_local_llm' -n 4 --dist loadgroup
.venv/bin/python -m pytest extensions/taut_mcp/tests -m 'not pg_only' -n 4 --dist loadgroup
.venv/bin/python -m pytest extensions/taut_tui/tests -n 2 --dist loadfile
TAUT_PG_UV_NO_SYNC=1 .venv/bin/python bin/pytest-pg --fast tests/test_shared_contract.py extensions/taut_pg/tests extensions/taut_mcp/tests/test_pg_conformance.py -n 2 --dist loadgroup
.venv/bin/python -m pytest -m 'not slow and not installed_wheel' -n 4 --dist loadgroup
.venv/bin/python -m pytest -m 'not slow and installed_wheel' -n 0
.venv/bin/python -m mypy taut tests --config-file pyproject.toml
.venv/bin/python -m mypy extensions/taut_summon/taut_summon extensions/taut_summon/tests --config-file pyproject.toml
.venv/bin/python -m mypy extensions/taut_mcp/taut_mcp extensions/taut_mcp/tests --config-file pyproject.toml
.venv/bin/python -m mypy extensions/taut_tui/taut_tui extensions/taut_tui/tests --config-file pyproject.toml
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/python bin/check-doc-paths
.venv/bin/python bin/check-plan-status-index
```

Read `bin/pytest-pg` and `taut/_scripts.py` before PG invocation; they own real
Docker setup, marker selection, and DSN validation. A missing backend/driver or
skipped PG suite is not acceptance. Hosted supported-platform lanes remain
required for release; local macOS evidence alone cannot establish Windows
shutdown behavior. Record backend/interpreter versions with observed results.

Plan-only verification: document path/index gates, exact upstream API and source
inspection, independent review, and diff check. No runtime implementation or
version refresh is performed merely to author this plan.

## Independent Review Loop

Before spec promotion, obtain a different-family review via the repository
call-agent skill. Give the reviewer this complete plan/delta, baseline sources,
upstream lifecycle clauses, touched-file list, and the real proof design.
Require existence-check first, then assess implementability, ownership ambiguity,
correctness, and unnecessary machinery. Review the same coherent client,
reactor, and host slices independently after implementation, and review the
final integrated change. Same-family fallback is allowed only under the
review-loop runbook's bounded, evidenced failure policy.

Full findings and author dispositions belong below. An implementation-ready
claim needs all actionable plan defects addressed, not merely a reviewer label.

## Out of Scope

No public session-injection API, global registry, automatic client sharing,
connection-level broadcast/persistence rewrite, transaction changes, new backend,
new CLI option, package publication, unrelated TUI/Summon refactor, or general
client thread-safety/fork support. Do not broaden existing best-effort message
notification semantics or change join/stop deadlines. Upstream session semantics
are consumed, not reimplemented.

## Deviation Log

| Spec ref | Planned behavior | Actual behavior | Rationale | Spec proposal |
|----------|------------------|-----------------|-----------|---------------|

No implementation deviations recorded.

## Review Log

### Round 1 — 2026-09-15

Claude 2.1.207, default `claude-opus-4-8[1m]`, reviewed the complete plan and
pinned upstream contract/source extracts with read-only Read/Grep/Glob tools.
Invocation matched the inventory's safe/plan mode, strict MCP configuration,
closed stdin, no session persistence, and JSON output. Bound: 900 seconds;
observed 346 seconds, exit 0, success/end_turn, terminal_reason=completed.
Verdict: PASS with two findings. The reviewed draft is preserved in the
review invocation; the following revision changes only the dispositioned items.

| ID | Finding | Disposition |
|----|---------|-------------|
| R1-F1 (P2) | Selective reactor queue minting adds unnecessary classification to the neutral queue seam. | Accepted. The reactor scope owns the thread-cache lifetime only; all reactor queues remain directly owned in the existing active maps. Client/runtime scopes still mint their cached/fixed handles. Revised design, exact spec delta, comprehension answer, task 3, and file ownership table together. |
| R1-F2 (P3) | Active-operation refusal type is private. | Accepted. BS-5 asserts public RuntimeError plus unchanged ownership and successful close after operation unwind. No private exception import. |
| R1-O1 | Constructor rollback is net-new. | Already included; retain explicit partial-direct-handle cleanup even before scope acquisition. |
| R1-O2 | Scope cleanup failure must not mask an active handler/run exception. | Existing required BS-8, made explicit in task 3 to prevent a nested-finally implementation mistake. |
| R1-O3 | Resolved Config handoff should be explicitly asserted. | Accepted as a BS-14 clarification: supplied object and namespace/custom fields survive session acquisition. |
| R1-O4 | No independent PG lock exists. | Confirmed; no change. |

The original findings follow verbatim for traceability; proposed dispositions
above, rather than historical reviewer wording, govern the revised plan.

#### Round-1 review (verbatim)

I've completed the existence-checks and read the units under review. All named methods, paths, test seams, markers, and spec anchors resolve at baseline `c79b448`. Here is the review.

---

# Review: BrokerSession Integration Plan — **PASS** (with findings)

## Existence-check results (all confirmed present)

| Claimed seam | Status |
|---|---|
| `_ClientBase.queue(name, *, persistent)`, `_queue_cache`, `_meta_queue`, `close()`, `_release_if_ephemeral`, `self.target`/`self.config`/`_persistent` | ✓ `taut/client/_base.py:198,203,191,216,268` |
| `__init__` meta+schema sequence with **no** try/except around `ensure_schema()` | ✓ `_base.py:191-196` (rollback is net-new, as the plan states) |
| `_OwnedWatchRuntime`, `_watch_runtime_for_client`, runtime `close()` | ✓ `taut/client/_watching.py:16,91,84` |
| `watch()` constructs runtime then `TautWatcher` with `BaseException` rollback | ✓ `taut/client/__init__.py:298,338,344-359` |
| `notification_activity_queue()` → `self.queue(..., persistent=True)` | ✓ `taut/client/_notifications.py:18-29` |
| `MultiQueueWatcher` uniform direct `Queue(...)` construction | ✓ `taut/watcher.py:234,274,385` |
| `BaseReactor._queue()`, `_close_reactor_resources()`, `stop()`/`_stop_once_lock`/`_resources_closed`, `run_forever`/`run_until_stopped`/`process_once` | ✓ `watcher.py:822,1168,1200,1231,793,795` |
| `TautWatcher._close_reactor_resources` → runtime close; `_remove_thread_queue` churn-close | ✓ `watcher.py:1327,1488` |
| Summon `_open`/`_make_broker_handles`/`_reopen_broker_handles` (construct-new-before-close-old)/`_close_queue_handles`/`ControlClient(owns_request_queue=)` | ✓ `_control.py:729,765,737,820,1143` |
| Spec anchors: [TAUT-3.4] "Persistent Queue handles for one / resolved target … does not recreate SimpleBroker connection release or retry policy" | ✓ `02-taut-core.md:510-520` (wraps across lines) |
| [TAUT-8.5] "A foreign caller may close only after the owner thread exits…" | ✓ `02-taut-core.md:1639-1640` |
| [SUM-9] "Operation release ends only the active lease" | ✓ `04-summon.md:1066` |
| Floors `simplebroker>=8.2.2` / `simplebroker-pg>=4.2.1` in root/mcp/pg manifests + specs + README | ✓ |
| 8 named existing acceptance tests | ✓ all present (`test_client.py`, `test_watcher.py`, `test_control.py`, `test_tui_domain.py`) |
| Lock set (root + summon/mcp/tui `uv.lock`); `taut_pg` has **no** independent lock | ✓ correctly omits `taut_pg` |
| PG proof homes `test_pg_sidecar.py`, `test_reactor.py`; `pg_only` marker | ✓ |
| No existing `BrokerSession`/`session.queue` usage in `taut/` | ✓ confirms no implementation present |

## Verdict rationale (the two gating questions)

**Could I implement this confidently and correctly?** Yes, for the load-bearing parts. The upstream model is understood correctly and maps to real seams:

- **Regression fix is sound.** `session.close()` calls `_process_session.cleanup_current_thread()` on the calling thread (`session.py`), and the process session is *keyed* — the worker's single shared core (used by minted *and* directly-constructed same-key queues) is recycled by one close. The existing `stop()` structure already routes `_close_reactor_resources()` onto the worker: `run_forever`'s `finally` calls `stop(join=False)` (`watcher.py:1115`) *before the thread terminates*, so it wins the `_resources_closed` once-guard over any foreign joiner (`watcher.py:1214-1234`). Dropping `session.close()` into `_close_reactor_resources` therefore recycles the **worker's** core — matching the diagnostic patch that restored `1,1,1`. Foreign-fallback-recycles-caller and never-driven-closed-by-caller both fall out of the same code path.
- **Construction handoff is correct.** Runtime, reactor, and source client share one process-session key, so a single `recycle_thread()` on the runtime scope after `TautWatcher` construction recycles the caller's shared core — including the source-client's cache — exactly as the plan states. No queue ownership transfers.
- **Ordering / lock discipline holds.** `stop()` joins outside `_stop_once_lock` and runs cleanup I/O after releasing it (`watcher.py:1231-1241`), satisfying "no lock across join or broker I/O."
- **Client scope, idempotent close, active-op refusal, Summon overlapping replacement** all map to existing seams (`_reopen_broker_handles` already constructs-new-before-close-old).

**Would implementing this degrade robustness?** No. It preserves stop/join synchronization, the single-closer guard, error-priority ordering, borrowed-handle non-ownership, and adds real (not mock-count) acceptance floors. No robustness impairment is introduced.

Neither gating question fails at the level that blocks. → **PASS.**

## Findings

**[P2] client/reactor — "mint fixed-lifetime queues from the session" is under-specified at the neutral seam and is unnecessary work.**
*Section:* "Reactor scope and bounded queue retention"; comprehension gate Q1. *Files:* `taut/watcher.py:234/274/385` (uniform `MultiQueueWatcher.__init__` construction), `watcher.py:822` (`BaseReactor._queue`), `_control.py:765-784`.
The regression is fully fixed by holding **one** `BrokerSession` on the reactor's key and closing it on the worker; `cleanup_current_thread` is keyed, so recycling does **not** depend on any queue being minted. Minting only the *fixed* queues (notification queue + control topology) while constructing membership/aux queues directly requires new per-queue distinguishing surface in a layer the plan itself tells implementers to keep neutral — the notification/initial queues are built uniformly from `queue_configs` inside `MultiQueueWatcher.__init__`, and Summon's fixed vs thread queues both flow through the single `_queue()` path. The split then *adds* `queue.session` classification and double-close guards without reducing close bookkeeping (each queue is still closed once). *Suggested disposition:* prefer holding the reactor session **solely for thread-cache recycling**, constructing all queues directly as today — this removes the neutral-layer intrusion, the minted/direct classification, and the upstream strong-retention concern in one stroke. If minting is retained, the plan must specify the exact `MultiQueueWatcher`/`_queue` seam that mints one config's queue while others stay direct. Not a blocker: the regression fix is implementable independently and the plan supplies the classification tool.

**[P3] test BS-5 — refusal type is private.** *Section:* Testing Plan, BS-5. `session.close()` raises `_ActiveOperationCloseError` (`session.py`, underscore-private). BS-5 and the "public APIs only" invariant conflict if the test matches the class name. *Disposition:* assert refusal by `RuntimeError` base + observable "no ownership cleared / later close succeeds" behavior, not the private symbol.

## Observations (not actionable this pass)

- **Constructor rollback is net-new but correctly named.** `_base.py:191-196` has no try/except today; the plan's "constructor/schema failure closes the partial scope, original error primary" is confirmed-absent work, not a plan defect. Implementation attention: keep the original `ensure_schema` error primary over an ordinary scope-cleanup failure (mirror upstream `__exit__` attach semantics).
- **`session.close()` now raises aggregated cleanup failures** where `_close_reactor_resources` currently swallows them (`watcher.py:1176-1188`). The nested `finally` in `run_forever` must not let an ordinary cleanup failure mask an active `StopWatching`/handler exception. Flagged by BS-8; call it out in slice 3.
- **`resolve_config(config=self.config)` idempotency.** `BrokerSession.connect()` re-runs `resolve_config` on the already-resolved client Config; the plan relies on the resolved-Config handoff from the 8.2 migration being idempotent. Consistent with SB-API-3 retain-supplied-Config, but worth an explicit assertion in BS-14.
- **`taut_pg/uv.lock` correctly omitted** — no independent lock exists; PG floor rides root/extension resolution. No gap.

No blocker traces to either gating question. Independent post-implementation slice review (already required by the plan) remains the right place to confirm the exception-path tests (BS-8/BS-10) fire as designed.

### Round 2

Claude 2.1.207 verified R1-F1, R1-F2, and the related BS-8/BS-14
clarifications only, with the same read-only invocation and a 540-second bound.
Observed: 342 seconds, exit 0, success/end_turn, terminal_reason=completed.
Verdict: PASS. No accepted finding remained open.

| ID | Finding or observation | Disposition |
|----|------------------------|-------------|
| R2-F1 (P3) | BS-1 could misread queue.session as required on directly owned reactor queues. | Accepted. Qualified the client/runtime-minted queue assertion and explicitly required None for direct reactor queues. This reads upstream's public property; it does not add a reactor classifier. Author cross-checked the property contract and the BS-1 wording. |
| R2-O1 | Cite same-key recycling in the design body. | Accepted. Added [SB-API-3] provenance to the design, already pinned in Source Documents. |
| R2-O2 | Explain why a reactor scope is still useful beyond Queue cleanup. | Accepted as rationale only. The explicit scope anchors backend lifetime independently of queue topology and avoids selecting a surviving Queue for cleanup. The narrower fix remains valid, but proper explicit scope ownership is the requested integration. No redesign or scope expansion. |

The minor wording/rationale edits above do not change ownership or blast radius;
they implement the passing review's requested clarification. Both rounds are
complete. The historical report follows verbatim.

#### Round-2 review (verbatim)

The `Write` tool isn't available in this context (only read-only tools are enabled), so I'll deliver the round-2 verification directly.

# Round-2 Verification — BrokerSession Integration Plan

**Scope:** Verification only of accepted R1 findings (R1-F1, R1-F2) plus the BS-8 / BS-14 clarifications, at baseline `c79b448`. No runtime code exists. Rest of plan not re-reviewed; accepted risks treated as unchanged.

**Verdict: PASS.** The accepted findings and clarifications are consistently incorporated across the revised design, the exact spec delta, the comprehension gate, the task list, and the test matrix. R1-F1's load-bearing recycle claim is upstream-verified in the plan's own review log. One minor new wording inconsistency (R2-F1, P3) is worth fixing but does not block.

I confirmed the on-disk file matches the reviewed text and preserves the Round-1 verbatim review.

---

## Accepted findings — verification

### R1-F1 — reactor queues stay directly owned; one session for thread-cache lifecycle only
The disposition (l.646) promised the change land in five surfaces "together." All five are consistent, with no residual reactor-minting language:
- **Ownership table** — `watcher.py`: "Keep direct queue construction and active-map ownership. BaseReactor gains a scope for thread-cache lifetime" (l.113); `_control.py` keeps "direct Queue ownership" (l.114).
- **Design** — "Keep **all reactor queues directly constructed and owned as today**… The reactor session holds no minted queues… Do not add a per-queue lifetime flag, a `queue.session` classifier, new factory indirection, or a fixed-versus-dynamic construction split" (l.162-169).
- **Spec delta** — [TAUT-3.4]: "Reactor queues remain directly owned… Queue creation through the scope is not required for same-key cache recycling" (l.346-348); [TAUT-8.5] ties retained objects to live topology (l.391-393).
- **Comprehension gate Q1** (l.243-244) and **Task 3** (l.472-475) — both explicit that the reactor scope owns cache lifetime only and forbid adopting session minting in `_control.py`.
- **Tests** — BS-6/BS-9 exercise direct active-map churn/retirement, not minting.

No new correctness defect. R1-F1's one load-bearing claim — that an owner-thread `session.close()` recycles the shared per-thread core used by **directly-constructed (non-minted)** same-key queues — is exactly what the R1 verbatim review already confirmed by upstream source inspection: `session.close()` → `_process_session.cleanup_current_thread()`, keyed process session, one shared core covering minted **and** direct same-key queues (l.690). Recycling does not depend on minting. Sound.

### R1-F2 — refusal asserted as public RuntimeError, not the private class
Consistent: BS-5 asserts "public RuntimeError base (never import the private refusal class), no ownership cleared; unwind, close succeeds; peer remains usable" (l.533); invariant restates observable refusal/retry (l.271-272); [TAUT-3.4] delta "A rejected close leaves ownership intact for a later valid close" (l.356-357). No private-symbol dependency remains. No new defect.

### BS-8 clarification — nested-finally active-exception preservation
Present: Task 3 requires the nested `run_forever()` finally blocks to preserve an active handler/run exception if ordinary scope cleanup also fails, via a firing BS-8 fault-injection proof (l.477-479); BS-8 covers "ordinary/BaseException cleanup preserve ownership and error priority" (l.536); invariants preserve the active run exception and forbid silently labeling incomplete cleanup successful (l.278-285). No new defect.

### BS-14 clarification — resolved Config retention
Present: BS-14 asserts the supplied Config is retained across session acquisition, including namespace/custom fields (l.542); invariant preserves Config object semantics/custom fields/namespace (l.257-259). No new defect.

---

## New defect

**R2-F1 (P3) — BS-1 still asserts `queue.session` while the revised reactor design forbids adding a `queue.session` classifier.**
*Location:* BS-1 (l.529) vs. design l.167-169.
BS-1 requires "queue.session identifies owning scope," but the R1-F1 revision newly added "Do not add … a `queue.session` classifier." These coexist only if `queue.session` is an **upstream** attribute read on **client/runtime-minted** (session-owned) queues, while the prohibition targets a Taut-side classifier in the neutral reactor scheduler. Directly-constructed reactor queues are not minted by a scope and have no owning session, so BS-1's unqualified wording could be read as requiring the attribute on all queues — contradicting the design.
*Suggested disposition:* qualify BS-1 to read upstream `queue.session` only on minted queues, and assert reactor direct queues have no owning scope; confirm `queue.session` is an existing upstream public attribute (not Taut-added). Not a blocker.

---

## Observations (non-blocking; not reopening prior scope)

- **O1 — recycle claim is verified, not merely asserted.** The design body states the direct-queue recycle behavior as fact (l.171-172) without inline citation; the R1 verbatim review in the same file grounds it in upstream `cleanup_current_thread` keying (l.690). Optional: surface that citation in the design body so a reader needn't rely on the review log.
- **O2 — "remove unnecessary work" candidate (author's call).** Since the reactor now mints nothing, holding a full `BrokerSession` solely to invoke recycle adds scope-acquisition ordering (l.157-160), foreign-fallback scope-close (l.190-199), and active-op-refusal handling to the reactor. The evaluation's *proven* fix used "public Queue cleanup on the retiring reactor owner" (l.67-68), recycling the same keyed thread cache without a session. A one-line justification for still preferring the session (uniform public-recycle handle, shared key with the metadata-runtime scope, R1-reviewer confirmation) would settle this — no redesign warranted; the chosen approach is coherent and verified.

---

**Summary:** R1-F1 and R1-F2 and the BS-8 / BS-14 clarifications are faithfully and consistently threaded through design, spec delta, comprehension gate, tasks, and tests, and R1-F1 introduces no cache-recycle correctness regression (upstream-verified in the plan's review log). The only new issue is a P3 wording inconsistency in BS-1 around `queue.session`. **PASS** over the scoped findings and new defects.


## Execution Evidence

Plan-authoring verification: `bin/check-plan-status-index`,
`bin/check-doc-paths`, and `bin/check-dom15-fixtures` passed. A separate scan
confirmed every named repository path and all eight existing test seams.
`pytest tests/test_docs_references.py -n 0`: 12 passed. `git diff --check`
passed. These checks validate this plan's references, not the proposed runtime.
The call-agent skill was evaluated: no new skill change is justified by this
successful invocation; its stricter supported Claude flags are already recorded
in the agent inventory.

Implementation started from prerequisite `b9eaada`. The promoted dependency
floors are SimpleBroker 8.3.0 and simplebroker-pg 4.3.0. Clients now lazily own
one persistent BrokerSession; watcher runtimes own an independent scope;
reactors retain direct Queue ownership and use one session only for keyed
thread-cache lifetime. Reactor finalization recycles before close and retains
failed ownership for retry.

Red/green proof covers lazy acquisition, transient overrides, constructor
rollback, construction-thread handoff, active-operation refusal, cleanup error
priority, direct Queue retry, retained SQLite peers, repeated worker retirement,
and retained PostgreSQL peers. The PostgreSQL observers assert that checkout
depth returns to the retained-peer baseline after both client and reactor worker
shutdown.

Verification completed on 2026-09-15:

- `.venv/bin/pytest -q`: passed; four platform-specific skips.
- `TAUT_PG_UV_NO_SYNC=1 .venv/bin/python bin/pytest-pg --fast
  tests/test_shared_contract.py extensions/taut_pg/tests
  extensions/taut_mcp/tests/test_pg_conformance.py -n 2 --dist loadgroup`:
  56 shared and 51 PostgreSQL tests passed.
- `.venv/bin/pytest -q extensions/taut_mcp/tests -m 'not pg_only'`: passed.
- `.venv/bin/pytest -q extensions/taut_tui/tests`: passed.
- the full Summon test suite passed with three platform-specific skips.
- `.venv/bin/ruff check .`, core mypy, the Ruff suppression index,
  documentation path gate, plan-status gate, and `git diff --check`: passed.

Independent implementation review required two correction rounds. Round 1
found swallowed strategy/direct Queue failures, masked watch-construction
cleanup, and incomplete arbitrary runtime-error handling. Each was corrected
with a firing retry/error-priority test. Round 2 found the missing
post-construction handoff failure proof; that proof was added. The final verdict
was **READY** with no open correctness finding. The TDD and call-agent workflows
need no durable skill change from this implementation.

## Fresh-Eyes Review

Author inspection and review dispositions checked the upstream strong retention rule, active-operation
close precondition, same-thread shared cache, default-transient persistent
notification override, watcher construction handoff, existing host ownership,
and Summon overlapping replacement. Round-1 independent review passed; scoped
round-2 verification passed and its final wording finding was incorporated.
The implementation and host verification are complete; the status remains
active only until the reviewed change is committed and its identifier is
recorded.


## Owner review follow-up (2026-09-15)

| Finding | Disposition |
|---------|-------------|
| Live 8.3 exposure before integration | Accepted. Separate Class 4 compatibility repair committed as `b9eaada`; release remains necessary to reach fresh installs. |
| Recycle reactor scope before close | Accepted. Design, TAUT-8.5 delta, and BS-8 now require this order and distinguish deferred release from immediate release. |
| New client close refusal | Host-review note retained: callers must unwind all same-key operations, including peers' iterators. Correction: current `TautClient.close()` already propagates queue-close errors, rather than swallowing them; active-operation refusal is the new case. |
| Heavy foreign fallback wording | Accepted. Reduced to one sentence in the spec delta; normal owner finalization remains the required path. |

The prior review transcripts below their dated headings are historical evidence;
the owner changes above supersede their earlier finalization-order descriptions.

Independent follow-up review: native reviewer `ordering_review`, read-only,
returned **no blocker** after checking upstream `session.py` and
`_broker_session.py`, the revised finalization/spec/test requirements, interim
prerequisite, and actual client-close behavior. No findings or scope expansion.
