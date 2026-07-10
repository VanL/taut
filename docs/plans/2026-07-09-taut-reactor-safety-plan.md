# Taut reactor safety hardening plan

Date: 2026-07-09

Status: implementation complete in the current worktree, with final integrated
verification tracked by
`docs/plans/2026-07-10-taut-summon-quality-remediation-plan.md`. The former
real-process control blocker was resolved by the SimpleBroker 5.2.2 dependency
release. No 5.1.x fallback or per-turn connection cleanup was introduced.

Plan type: implementation with spec revision.

Promotion strategy: **A — in-file edits, requirement text before link claims**.
The future spec-promotion slice adds the reviewed requirements to the existing
spec files without claiming implementation. Code citations and reciprocal
implementation mappings land with the corresponding implementation slices.

Owner: the implementer of the shared reactor/core watcher slice owns
`taut/watcher.py`; the implementer of the Summon slice owns
`extensions/taut_summon/taut_summon/_control.py` and the narrow driver
supervision changes in `_driver.py`. These are two independent reactors and
must be reviewed and verified independently, but both use the same
`taut.watcher.BaseReactor` mechanism copied conceptually from the SimpleBroker
5.2.0 reference.

## Goal

Harden Taut's two long-lived reactor paths against concurrent drive, early
resource close, silent thread death, missed wakeups, and unsafe in-turn handle
replacement by adopting the `BaseReactor` process/wait/stop pattern from
SimpleBroker 5.2.0's `../simplebroker/examples/reference_reactor.py`, while
preserving Taut's own chat and control semantics.

The two reactors are:

1. **Shared mechanism:** `BaseReactor` in `taut/watcher.py`, derived from the
   SimpleBroker 5.2.0 reference and used by both policies.
2. **Core watch policy:** the cursor-aware, dynamic-topology `TautWatcher`.
3. **Summon control policy:** the fixed-topology `_ControlReactor` plus
   `ControlLoop`'s replaceable-reactor supervisor and driver-owned handles in
   `extensions/taut_summon/taut_summon/_control.py` and `_driver.py`.

`BaseReactor` is the one lifecycle mechanism, not a third policy path. Core and
Summon remain different policy subclasses with different proof obligations.
Fixing the shared mechanism does not by itself prove Summon: Summon must
separately prove fixed topology, control wake latency, inter-turn replacement,
and propagation of control-lane death to the foreground driver.

## Requested Outcomes

- [x] One shared `BaseReactor` owns the process/wait/request-stop/stop mechanism
      for both core watch and Summon control; neither policy overrides those
      public templates.
- [x] Reactor turns and waits have exactly one drive-thread owner and reject
      same-thread reentrant turns.
- [x] A stop request never closes queue handles underneath a live turn.
- [x] Clean, bounded, and exceptional exits close owned resources exactly once.
- [x] `TautWatcher.start()` drives one watcher instance, as the reference
      reactor does; the 5.1-era proxy/clone workaround is removed.
- [x] Persistent handles use SimpleBroker 5.2.0's process-local session and
      thread-local-core model; after drive begins, only the owner uses them.
- [x] Queue and stop activity wake the core loop without replacing
      SimpleBroker's retry policy.
- [x] Summon's control reactor has its own fixed topology, drive ownership,
      persistent handle ownership, and bounded wait contract.
- [x] Summon never closes/reopens the currently executing control reactor from
      inside its handler/error callback.
- [x] Unexpected Summon control-lane death stops the foreground driver loudly;
      the harness cannot remain live-but-uncontrollable.
- [x] STOP/STATUS/PING shapes, generation fences, keyed reply ownership,
      at-most-once command consumption, cursor behavior, and blocked-injection
      shutdown remain unchanged.
- [x] Core and Summon release/installation order keeps the already-published
      `taut-summon` importable; no runtime subclass-definition guard breaks an
      older extension before its coordinated update.
- [x] Specs, plan, implementation docs, code citations, and tests form two
      reciprocal traceability chains.

## Source Documents

Source specs:

- `docs/specs/02-taut-core.md` [TAUT-3.4], [TAUT-7.2], [TAUT-8.4],
  [TAUT-10], [TAUT-11], [TAUT-12.5]
- `docs/specs/03-identity-addressing-notifications.md` [IAN-8.2]
- `docs/specs/04-summon.md` [SUM-5.4], [SUM-7.1], [SUM-9], [SUM-10],
  [SUM-11], [SUM-12]
- `docs/specs/01-development-documentation-operating-model.md` [DOM-4],
  [DOM-5], [DOM-8], [DOM-10], [DOM-11]

Reference implementation and tests:

- `/Users/van/Developer/simplebroker/examples/reference_reactor.py` at
  SimpleBroker commit `37ee5e6f600828e8d23f76349258a84c1efd8d31`
- `/Users/van/Developer/simplebroker/examples/tests/test_reference_reactor.py`
  at the same commit

Related plans and implementation notes:

- `docs/plans/2026-07-08-taut-sqlite-contention-hardening-plan.md`
- `docs/plans/2026-07-01-taut-watch-runtime-plan.md`
- `docs/plans/2026-07-06-taut-summon-plan.md`
- `docs/plans/2026-07-07-taut-summon-pty-harness-adapter-plan.md`
- `docs/implementation/04-taut-architecture.md`
- `docs/implementation/05-taut-summon-architecture.md`

Required process guidance:

- `AGENTS.md`
- `docs/agent-context/decision-hierarchy.md`
- `docs/agent-context/engineering-principles.md` sections 4, 8, 9, 10,
  12, and 14
- `docs/agent-context/runbooks/testing-patterns.md`
- `docs/agent-context/runbooks/writing-plans.md`
- `docs/agent-context/runbooks/hardening-plans.md`
- `docs/agent-context/runbooks/maintaining-traceability.md`
- `docs/agent-context/runbooks/review-loops-and-agent-bootstrap.md`

## Spec Baseline

- Repository baseline: `766e3aaf84f75046a57ef769b9c802148b42e71a`.
- Governing spec baseline for this plan: the above commit **plus the current
  dirty worktree versions** of `docs/specs/02-taut-core.md` and
  `docs/specs/04-summon.md` on 2026-07-09. Those in-progress edits correctly
  establish the SimpleBroker-owned retry boundary and persistent-owned-handle
  intent, but their `simplebroker>=5.1.1` floor and per-operation core-release
  explanation are known stale text from the buggy release. They are baseline
  defects to replace during this plan's spec-promotion slice, not requirements
  to preserve. The follow-on remediation establishes `simplebroker>=5.2.2` as
  the supported floor; no implementation or verification may run against
  5.1.1.
- Exact worktree content identifiers at plan authoring:
  - `docs/specs/02-taut-core.md` SHA-256
    `a350edd4a2e0c3e056bf69d541abf330fbd01f8ad70f4fd743f6cd4628fdcee0`
  - `docs/specs/04-summon.md` SHA-256
    `f80d566fab610cc2917d0f3debeb1645e1bf7b0aa3e6bf7b1287da5050061ae9`
- Post-authoring worktree identifiers after adding only this plan's Related
  Plans backlinks:
  - `docs/specs/02-taut-core.md` SHA-256
    `6fba072b9dd5ac85e4fa6c1aa453571a17cd6bfc3357fa50a2cd74c80fadde42`
  - `docs/specs/04-summon.md` SHA-256
    `d548ab1193d4233c0b961fa8cc76dd9d6de999568bb923bd8ddc6b9f3fa75e50`
  These second identifiers are not a new behavioral spec baseline. They make
  the plan-owned backlink edits distinguishable from the pre-existing dirty
  spec worktree that the implementer must preserve.
- Rerunnable baseline inspection:

  ```bash
  git diff -- docs/specs/02-taut-core.md \
    docs/specs/03-identity-addressing-notifications.md \
    docs/specs/04-summon.md
  git diff -- docs/implementation/04-taut-architecture.md \
    docs/implementation/05-taut-summon-architecture.md
  git status --short
  ```

- Dependency baseline: the supported floor is `simplebroker>=5.2.2`; the
  Summon lock is currently stale and still resolves 5.1.0. The Taut PG manifest
  still has the old plugin floor, and its untracked lock is stale if retained.
  The promotion slice updates every governing dependency statement to the
  `simplebroker>=5.2.2` / `simplebroker-pg>=3.1.0` pair, refreshes retained
  extension locks, and records `uv lock --check` evidence. A 5.1.x environment
  is a hard failure, never a fallback test lane.
- Promotion baseline identifier: repository `766e3aaf84f75046a57ef769b9c802148b42e71a`
  plus the promoted worktree specs. Current SHA-256 identifiers after the
  reviewed [SUM-12] immutable-artifact correction are:
  - `docs/specs/02-taut-core.md`:
    `14f4500d98150f75efc34b2272914a0471abfe0ddc86dae1566932ef82af5b2d`
  - `docs/specs/03-identity-addressing-notifications.md`:
    `45306fc33539c1617de3dd66a05164ba474cea489ddce605bcf1042dd223ef45`
  - `docs/specs/04-summon.md`:
    `d1f45ce8f60d281cca722f10bd3aefb0ac9f03e3880db5d784f6f56ad54a375a`

## Current Context and Key Files

### Shared reactor and core watch policy

- `taut/watcher.py::MultiQueueWatcher` is the copied Weft scheduling
  primitive. Keep its queue modes, priority scheduling, and dynamic queue
  machinery intact unless a failing core-reactor test proves that the shared
  mechanism itself must change.
- `taut/watcher.py::TautBaseWatcher` currently adds `_queue_cache`,
  `process_once`, `wait_for_activity`, `run_until_stopped`, `run_forever`,
  `cleanup`, and `stop`. It does not claim a drive thread, does not separate a
  stop request from resource finalization, and does not start the polling
  strategy in its explicit loop.
- The implementation target renames this shared class to `BaseReactor` and
  reshapes it around SimpleBroker 5.2.0's reference `BaseReactor`. Keep a
  temporary `TautBaseWatcher = BaseReactor` compatibility alias so an older
  separately installed `taut-summon` still imports during core-first rollout.
  Do not add a runtime `__init_subclass__` rejection: the old extension still
  overrides `process_once()`, and already-published dependency metadata cannot
  be changed retroactively. First-party architecture tests, `@final` typing,
  and owner checks enforce the new path without breaking import compatibility.
- `MultiQueueWatcher.__init__()` currently calls
  `_ensure_multi_activity_waiter()` before any drive owner exists. Its explicit
  `wait_for_activity()` then waits on that waiter directly instead of driving
  `PollingStrategy.wait_for_activity()`. The shared reactor port must remove
  eager waiter creation and use the reference's one canonical authority on the
  owner: `PollingStrategy`, optionally backed by the multi-queue native waiter.
  `wait_for_activity()` must not bypass the strategy and consume that waiter
  directly.
- `taut/watcher.py::TautWatcher` adds chat cursor semantics and membership
  churn. Its dynamic `add_queue`/`remove_queue` calls are load-bearing and run
  during the watcher turn. Its background `run_in_thread()` currently builds a
  second watcher instance plus `_ThreadOwnedWatchRuntime`; that workaround came
  from the 5.1-era connection bug and creates two lifecycle owners. Under
  SimpleBroker 5.2.0, follow the reference reactor: one constructed reactor
  instance is later driven by one owner thread, and persistent sessions select
  a thread-local core for that driving thread. Remove the proxy/clone path and
  give the one `TautWatcher` an owned persistent runtime that closes with it.
- `tests/test_watcher.py` is the core contract surface. It currently contains
  a test that explicitly prevents `TautBaseWatcher` from starting its strategy;
  that expectation must be replaced, not worked around with a second startup
  path.
- `get_queue()` returns the live mutable `Queue`, not a snapshot. After drive
  begins it is owner-only. Cross-thread inspection is limited to immutable queue
  name/topology snapshots; tests must stop retrieving live background handles.

### Summon reactor

- `extensions/taut_summon/taut_summon/_control.py::_ControlReactor` is a
  fixed one-command-lane policy built on `TautBaseWatcher`. It currently
  overrides `process_once` and `wait_for_activity`, bypassing part of the core
  lifecycle. Its wait is only `stop_event.wait(timeout)`, so new control
  commands do not wake it through the broker activity waiter.
- `ControlLoop` owns control fields, rate-audit state, control handles, handle
  recovery, STOP acknowledgment ordering, and command dispatch. This policy
  remains Summon-owned even after the core lifecycle is hardened.
- `_ControlReactor` is currently constructed with `persistent=False`, while the
  current dirty [SUM-9] text and implementation note say the long-lived control
  reactor owns persistent handles. This is a contract mismatch, not an optional
  tuning difference.
- `_handle_control_error()` currently calls `_mark_control_drain_failure()`,
  which may build a new reactor and close the old one while the old reactor is
  still inside `_dispatch()` and `_process_queue_message()`. Recovery must move
  to the between-turn supervisor seam.
- `ControlLoop.run()` catches every unexpected exception, logs it, closes its
  handles, and returns. `SummonDriver` does not monitor that return. The result
  can be a live provider and watcher with no control plane.
- `extensions/taut_summon/taut_summon/_driver.py` already treats watcher
  death as first-class supervisor state. The control lane needs its own,
  separate state and policy; do not alias it to `_watcher_failed`.
- `extensions/taut_summon/tests/test_control.py` contains focused control
  tests. `test_driver.py` and `test_conformance.py` contain the real-process
  proof and must stay real.
- `ControlLoop.run()` is intentionally a thin context-specific supervisor over
  replaceable `BaseReactor` instances. `BaseReactor` owns each public
  `process_once()` and `wait_for_activity()` template; `ControlLoop` owns the
  sequence between them: audit, pending-fault classification, complete handle
  replacement, and fatal escalation. It never delegates the whole loop to one
  reactor instance because a failed instance cannot replace itself.

### Reference principles to transfer

Transfer these principles from the reference reactor:

1. One `BaseReactor` mechanism owns process/wait/request-stop/stop for both
   policies; policy subclasses use protected hooks rather than public lifecycle
   overrides.
2. One drive owner mutates reactor scheduling state and uses reactor-owned
   persistent handles during normal operation.
3. A stop request is a wakeable state transition; it is not permission for a
   foreign thread to close resources under the drive thread.
4. The drive finalizer closes resources on every exit, including unexpected
   failure, while unexpected exceptions remain observable.
5. Broker activity and stop are wake sources; wake flags are hints and pending
   state is the source of truth.
6. Work budgets and lane separation keep control responsive.
7. Durable semantics are explicit: Taut chat uses cursor-based at-least-once
   display, while Summon control intentionally uses at-most-once command
   consumption plus idempotent STATUS/PING client retries.

Do **not** transfer the reference demo's worker pool, result sidecar, outbox,
fixed input topology, or output replay tables. Taut chat already has a durable
history/cursor contract, and Summon commands deliberately are not history.
Adding those mechanisms would create a second task system and violate scope.

## Diagnosis and Findings

### Core reactor findings

| ID | Severity | Finding | Evidence and consequence |
|---|---|---|---|
| CORE-R1 | Critical | `stop(join=False)` can close owned queues while another thread is still inside `_drain_queue()`. | `TautBaseWatcher.stop()` calls `super().stop(join=False)` and then unconditionally calls `cleanup()` when a background thread was alive. A read-only scratch probe against the current worktree printed `closed_while_turn_active=True`. A handler or pending check can therefore use a closed handle. |
| CORE-R2 | High | Turns have no single-thread owner. | `process_once()` and `run_until_stopped()` mutate `_active_queues`, `_queue_iterator`, `_handler`, `_error_handler`, cursor maps, and topology without an owner guard. A second caller can interleave dispatch state. |
| CORE-R3 | High | The explicit run loop does not guarantee resource finalization. | `TautBaseWatcher.run_forever()` cleans only BaseWatcher's thread-local connection state. It does not call `cleanup()`. `TautWatcher.run_in_thread()` happens to add a wrapper cleanup, but the base and direct/manual drive paths do not own the guarantee. |
| CORE-R4 | High | The explicit loop leaves the strategy lifecycle dormant. | `run_until_stopped()` never calls `_start_strategy()`, and `test_taut_base_watcher_uses_process_wait_loop` currently enforces that absence. The direct multi-queue waiter can wake queue traffic, but `TautWatcher._on_data_version_change()` is not installed through the normal strategy lifecycle; membership convergence falls back to the timer only. |
| CORE-R5 | Medium | The BaseWatcher running-state contract is lost. | The override never sets/clears `_running_event`, so inherited `is_running()` can report false while the reactor is active. |
| CORE-R6 | High | The background live watcher uses a 5.1-era non-persistent proxy/clone workaround instead of the 5.2.0 reference ownership pattern. | `TautWatcher.run_in_thread()` constructs a second watcher with `thread_persistent=False`; Summon's `_start_watcher_thread()` calls `watch(..., persistent=False)`. SimpleBroker 5.2.0's reference constructs one reactor and later drives that instance on one owner thread with persistent handles and a thread-local backend core. |
| CORE-R7 | Medium | Stop and cleanup idempotence are not synchronized as one state machine. | `_cleanup_done` is a bare boolean. Concurrent `stop()`/`cleanup()` callers can race waiter detach, queue close, and cache clearing. |
| CORE-R8 | Medium | Dynamic topology has no drive-owner rule. | `TautWatcher` legitimately changes membership queues during a turn, but the base also permits any thread to call `add_queue`/`remove_queue`. Topology mutation and iterator replacement need the same owner rule as dispatch after driving begins. Read-only snapshots must remain safe. |
| CORE-R9 | High | Wait infrastructure is created before ownership and the explicit wait bypasses the strategy it starts. | `MultiQueueWatcher.__init__()` eagerly creates the multi-queue waiter. `MultiQueueWatcher.wait_for_activity()` consumes it directly, so merely calling `_start_strategy()` does not prove the reference process/wait path or the data-version callback path is driven. |
| CORE-R10 | High | The proxy exposes a live owner handle as if it were a cross-thread snapshot. | `TautWatcher.get_queue()` forwards the inner watcher's mutable `Queue`; callers can read, write, or close it from the foreground. The replacement contract exposes immutable topology snapshots only after drive begins. |
| CORE-R11 | High | Same-thread reentrant turns are not rejected. | A thread-identity owner check alone accepts a handler that recursively calls `process_once()`. Nested turns can corrupt scheduling state and make an inner `finally` lie about whether the outer turn is still active. |

### Summon reactor findings

| ID | Severity | Finding | Evidence and consequence |
|---|---|---|---|
| SUM-R1 | Critical | Broker-handle recovery can close the reactor that is still executing the current turn. | `_ControlReactor._handle_control_error()` delegates to `_mark_control_drain_failure()`, which can call `_reopen_broker_handles()` and `control_reactor.cleanup()`. Control returns to the old `_process_queue_message()`, which still references the old queue config and performs a pending check. |
| SUM-R2 | Critical | Unexpected control-thread exit is silent at the driver supervision boundary. | `ControlLoop.run()` catches `Exception`, logs `control loop crashed`, closes, and returns. `SummonDriver._await_wake()` watches shutdown, harness death, and watcher death only. The provider can remain live but STOP/STATUS/PING are gone. |
| SUM-R3 | High | Control commands do not use broker activity to wake the reactor. | `_ControlReactor.wait_for_activity()` waits only on the stop event, then audits. With the default cadence, a command can sit until the next interval even though `MultiQueueWatcher` has an activity waiter. |
| SUM-R4 | High | Summon bypasses the core lifecycle it claims to reuse. | `_ControlReactor.process_once()` duplicates the stop check and drain instead of calling the hardened base path. Core single-owner and finalization work would not automatically cover this override. |
| SUM-R5 | High | Long-lived Summon handles are configured transient. | `_ControlReactor(... persistent=False)`, `SummonDriver._start_watcher_thread(... persistent=False)`, and default-transient control client construction conflict with the in-progress persistent-owner design. One-shot per-request reply clients should remain transient; the dedicated control reactor, live watcher, and their owner clients should not. |
| SUM-R6 | Medium | Control topology is fixed by policy but mutable by interface. | `_ControlReactor` inherits public `add_queue`/`remove_queue`, even though command lane identity, driver evidence, and audit ownership are fixed for one generation. |
| SUM-R7 | High | Control failure and watcher failure need different driver policies. | Watcher death is recoverable by rebuilding ears over the same provider. Loss of the control plane makes the process uncontrollable and should fail the generation/driver loudly rather than spend watcher or harness retry budgets silently. |
| SUM-R8 | Medium | Audit scheduling and command waiting are coupled by an override that weakens both. | The audit needs a deadline; the command lane needs native wake. The next wait should be the minimum of the audit deadline and reactor polling bound, with command activity able to end it early. |
| SUM-R9 | Critical | Rate-audit recovery can also close the reactor while its turn is on the stack. | `_ControlReactor._drain_queue()` calls `_audit_if_due()`; `_mark_rate_audit_failure()` may reopen the full handle set and clean the old reactor before `_drain_queue()` returns. All audit and recovery decisions must move to the explicit `ControlLoop` between-turn seam. |
| SUM-R10 | High | A successful replacement can still be followed by a wait on the retired local reactor. | `ControlLoop.run()` snapshots `reactor`, calls `process_once()`, then calls `wait_for_activity()` on the same local. After installation, the loop must `continue` and reacquire the current reactor before any wait. |
| SUM-R11 | High | Partial replacement construction is not transactionally cleaned up. | `_make_broker_handles()` can create a client, reactor, and some persistent queues before a later constructor fails; its current exception path closes only the client. The replacement builder needs a local partial-handle cleanup guard and firing failure at every construction stage. |
| SUM-R12 | Medium | The proposed audit deadline has a due-now spin edge. | `_next_rate_audit_at` begins overdue. Audit must run before timeout calculation; a zero/negative deadline is work to perform now, not a reason to skip waiting forever in a hot loop. |

### Existing strengths to preserve

- Taut's cursor advances only after successful handler return; poison-message
  liveness is explicit.
- Summon keeps chat, provider event pump, and control on separate lanes.
- Adapter events are typed local values, and adapter close/interrupt is the
  explicit mechanism that unblocks a stuck inject.
- STATUS primary fields are driver-owned memory, not reconstructed from the
  durable ledger on every request.
- Per-request reply queues and driver-evidence fences prevent cross-client and
  cross-generation control confusion.
- STATUS/PING timeout retry is semantic and correlated; Taut does not recreate
  broker retry.
- Real-process tests already prove blocked-injection STOP and SQLite integrity.

## Comprehension Gate

An implementer must answer these before editing:

1. **Why can core `stop(join=False)` not call `cleanup()` when another thread
   owns a turn?** Because queue configs and handlers on that thread still hold
   the handles. Stop may signal and wake; only the owner finalizer, or a caller
   that has proved no owner is alive, may close them.
2. **Why is `SummonDriver._halt_and_raise()` a required edit even though the
   core stop method is being fixed?** It calls `watcher.stop(join=False)` from
   inside the handler/drive thread. The safe in-turn operation is a signal-only
   `request_stop()`; finalization occurs after the handler unwinds.
3. **Why can Summon not reopen handles in `_handle_control_error()`?** The old
   reactor remains on the Python stack and continues its post-dispatch work.
   Recovery must happen after `process_once()` unwinds to `ControlLoop.run()`.
4. **Why is control-lane death not handled like watcher death?** Ears can be
   rebuilt from cursors without killing the provider. A provider with no
   control plane cannot be stopped or observed; that generation must be
   interrupted and the driver must exit loudly.
5. **What retry is allowed?** SimpleBroker's own queue/connection retry and
   correlated no-reply resend for idempotent STATUS/PING. No Taut substring
   classifier and no whole-turn/whole-command retry.
6. **Which handles stay transient?** One-shot CLI clients and per-request reply
   queues. Long-lived core watcher, Summon watcher, control reactor, ledger,
   audit, and live driver clients are persistent and owned.
7. **Why is the old `TautWatcher` proxy/clone removed?** It was a workaround for
   buggy 5.1-era persistent-session behavior and creates two lifecycle owners.
   SimpleBroker 5.2.0's reference constructs one reactor and drives that same
   instance later; the persistent session supplies the driving thread's core.
8. **Why does `ControlLoop` still have a loop if `BaseReactor` centralizes the
   lifecycle?** `BaseReactor` owns the safe public turn, wait, stop request, and
   finalization templates. `ControlLoop` is a thin context wrapper that must
   regain control between those templates so it can audit and atomically replace
   a failed reactor. A failed reactor cannot replace itself from inside its own
   stack.
9. **What happens after a replacement is installed?** Close the retired complete
   set outside its turn, then `continue` so the loop reacquires the installed
   reactor. Never wait on the retired local object.

## Invariants and Constraints

### Shared floors

- No new dependency.
- No SimpleBroker private imports and no SQL against broker-owned tables.
- No Taut-level lock/busy/corruption retry classifier.
- Exactly one drive owner per reactor instance after the first driven turn.
- Resource close is idempotent and happens only after the driven loop has
  unwound. The owner may close from its own loop `finally` even though the
  Python thread has not yet returned; a foreign thread may close only after it
  proves the owner thread is no longer alive. An instance that was never driven
  may be closed by its caller.
- Unexpected exceptions remain observable after finalization; cleanup does not
  convert failure into success.
- `request_stop()` is signal-only and safe from a handler, signal path, or
  foreign thread.
- Native activity is a hint. Every wake returns to ordinary pending/cursor
  checks before dispatch.
- No drive-thread join waits while holding the lifecycle lock.

### Required shared `BaseReactor` mechanism

Port the mechanism and tests from SimpleBroker 5.2.0's `BaseReactor` into the
existing copied watcher layer. Adapt only where Taut's dynamic chat topology and
Summon's replaceable control instances require it. Do not invent a second state
machine beside the reference fields and stop path.

The shared mechanism owns:

```text
construct/configure (no concurrent use)
        |
first process_once()/wait/run claims strong Thread owner
        |
        +--> process_once() [non-reentrant public template]
        |        -> protected policy turn
        |
        +--> wait_for_activity(timeout) [owner-checked public template]
        |        -> PollingStrategy (optional native waiter; never bypassed)
        |
request_stop() [any thread: signal + wake only]
        |
run-loop finally or proven-dead foreign owner
        -> stop/finalize exactly once -> CLOSED
```

- Use the reference fields and responsibilities as the starting point:
  reactor stop/activity events, drive-owner lock, strong drive-thread reference,
  stop-once lock, stop-requested flag, resources-closed flag, and strategy-started
  flag plus a topology/waiter generation. The strong `Thread` object is
  authoritative; its numeric ident is only a diagnostic.
- `process_once()` and `wait_for_activity()` are public `@final` templates in
  Taut's type surface. Each claims/verifies the owner. `process_once()` rejects
  reentry when the same owner already has a turn active, then calls protected
  `_process_reactor_turn()`. Repeated sequential manual turns on the same owner
  remain valid.
- Define one canonical guarded lifecycle tuple and use it in the constructor
  compatibility check, the `@final` declarations, and the first-party
  architecture test: `process_once`, `wait_for_activity`,
  `run_until_stopped`, `run_forever`, `run_in_thread`, `start`, `run`,
  `request_stop`, `stop`, and `cleanup`. `run()` is guarded because it is the
  inherited synchronous entry point; context-manager methods remain unguarded
  because they delegate to guarded start/stop templates.
- Do **not** add runtime `__init_subclass__` enforcement. Preserve the temporary
  `TautBaseWatcher` alias so already-published Summon imports and class definitions
  continue to load. Add an architecture test that Taut's current first-party
  subclasses do not override any method in the canonical tuple after migration.
- Import compatibility is not permission to drive an unsafe legacy subclass.
  At `BaseReactor` construction, compare the concrete class's public lifecycle
  methods with the BaseReactor templates. An older Summon subclass that still
  overrides one fails before opening/reading a queue with a one-line actionable
  "upgrade taut-summon" error. This constructor-time gate is enabled only after
  the in-repo `TautWatcher` migration; it does not make module import fail.
- `request_stop()` is the reference signal-only operation: set stop state, set
  the local activity event, and notify the strategy. It never joins or closes.
  Repeated calls are inert.
- Remove eager `_ensure_multi_activity_waiter()` from
  `MultiQueueWatcher.__init__()`. The first owner-driven wait starts the
  reference-style `PollingStrategy` once. It creates the optional multi-queue
  waiter on that owner and supplies it to `PollingStrategy.start()`; the shared
  `wait_for_activity(timeout)` template waits only through the strategy plus the
  local activity event. It never calls `waiter.wait()` directly. When
  `create_activity_waiter_for_queues()` returns `None`, SQLite's data-version
  polling remains the strategy's authority. When it returns a native waiter,
  Postgres/Redis activity is consumed through the same strategy. The outer
  deadline loop uses bounded strategy steps so local stop remains responsive.
  After any wake, recheck authoritative pending/cursor state and invoke a
  protected post-wake policy hook. Postgres/Redis retain the existing bounded
  timer as the portable sidecar-membership fallback. Fixed-topology reactors
  bind once. When owner-thread dynamic topology changes in `TautWatcher`, mark
  the waiter generation dirty; before the next wait, rebuild the optional
  native waiter for the complete new queue set and rebind that waiter to the
  same strategy through its supported startup/reconfiguration seam. The old
  waiter closes once. After a waiter is bound, the strategy is its sole close
  owner; a newly created waiter that fails before binding is closed by the
  creator. Finalization closes the strategy, which closes the current waiter.
  Topology never adds a direct or second wait path.
- `run_until_stopped()` follows the reference process/wait loop and owns the
  `finally: stop(join=False)` path. `run_forever()` owns signal setup and the
  inherited 5.2.0 `_running_event`; it clears running state only after reactor
  resources have finalized.
- `stop(join=True)` follows the reference ordering with the Taut in-turn guard:
  request stop first; snapshot the strong owner; join only a different thread and
  never while holding the stop lock; return without close if a foreign owner is
  still alive; if called by the owner during an active turn, return after the
  signal and let the outer run-loop `finally` close. A never-driven instance may
  close on its caller.
- Finalization closes the strategy, which closes its currently bound waiter,
  then delegates supported inherited stop cleanup and invokes
  `_close_reactor_resources()` exactly once. Only a candidate that failed before
  binding is creator-owned. No plan step accesses the undocumented SimpleBroker
  `BaseWatcher._finalizer`. Close errors are logged and never mask the primary
  exception.
- Queue topology mutation methods become owner-checked after drive begins.
  `list_queues()` returns an immutable/synchronized name snapshot.
  `get_queue()` remains available only before drive or on the owner thread; the
  background watcher never proxies a live Queue to a foreign thread.
- `TautBaseWatcher = BaseReactor` is a compatibility alias, not a second class or
  behavior path. New Taut and Summon code imports/extends `BaseReactor`.

### Core-only invariants

- Preserve copied `MultiQueueWatcher` scheduling behavior and keep Taut cursor
  adaptations in `TautWatcher`.
- Preserve chat peek/history semantics and the three-strikes rule.
- Preserve membership convergence and close a removed membership queue once.
- Dynamic membership mutations occur on the drive thread after driving starts.
- `TautWatcher.start()` drives the same instance returned by
  `TautClient.watch()`, matching the SimpleBroker reference. Remove
  `_thread_watcher`, `_active_thread_watcher()`, the proxy overrides, and
  `_ThreadOwnedWatchRuntime` cloning. Replace the client-sharing
  `_ClientWatchRuntime` adapter with one watcher-owned persistent Queue/state
  runtime created from an immutable target/config snapshot. The source client
  and watcher have independent close lifetimes; the watcher closes its runtime
  with its queues.
- Direct synchronous `run()` still works with handles constructed by that
  caller, which becomes the drive owner.

### Summon-only invariants

- Preserve JSON-only STOP/STATUS/PING, `command`/`request_id`, driver evidence,
  and keyed reply routes.
- Preserve `QueueMode.READ` at-most-once command consumption. Do not turn
  control into peek/checkpoint history in this change.
- Preserve STOP acknowledgment ordering: only after driver-slot release is
  confirmed.
- Preserve control responsiveness while provider inject is blocked.
- The control reactor has fixed queue topology for one driver generation.
- Broker recovery swaps handles only between completed/failed turns on the
  control owner thread.
- A pending recoverable fault gates the supervisor loop. Until a complete
  replacement succeeds or the threshold escalates fatal, the known-faulted old
  bundle may not process another command, audit, or wait.
- One failed control reply remains recoverable through client retry; repeated
  failures remain visible in health.
- Control failure sets its own driver failure state, wakes the supervisor,
  interrupts the adapter immediately, stops ears, releases the driver claim,
  and exits nonzero. It must not consume watcher-rebuild or harness-crash
  budgets.
- Rate audit remains on the control thread and retains its cursor across a
  successful in-generation handle reopen.
- Rate audit runs in `ControlLoop` after a reactor turn has returned, never from
  `_ControlReactor._drain_queue()` or a reactor wait override.
- After successful replacement, `ControlLoop` closes the retired complete set
  and immediately continues to reacquire the installed reactor. It never waits
  or dispatches through the retired local.

### Fatal versus best-effort failures

- Fatal: second drive owner; invariant/programming exception in control
  dispatch; control reactor unexpected exit; inability to create the initial
  control reactor; or
  `_CONTROL_DRAIN_RECOVERABLE_FAILURES_BEFORE_DEGRADED` consecutive surfaced
  control faults for which a complete between-turn handle replacement could
  not be constructed. The last case escalates to the same driver-visible
  control-failure path instead of leaving a live but unusable plane.
- Recoverable in place: a surfaced broker fault on a long-lived control handle
  when handle reopen succeeds between turns; one lost STATUS/PING reply; one
  skipped rate audit.
- Best effort during finalization: logging and duplicate close attempts. A
  close error is logged but does not mask the primary exception.
- Data-integrity and row-shape errors remain loud. This plan does not label
  them transient by message text.

### Stop-and-re-evaluate gates

Stop and revise this plan if implementation requires any of the following:

- a second retry engine or a private SimpleBroker import;
- any runtime or test resolution to SimpleBroker 5.1.x;
- a new worker pool, durable outbox, checkpoint table, or control history;
- a fourth Summon runtime lane;
- changing chat cursor, poison-message, control JSON, or STOP-ack semantics;
- closing a live owner's queues to make a test pass;
- sharing a persistent Queue object across reactor threads;
- restoring the `TautWatcher` proxy/clone instead of the one-instance reference
  pattern;
- changing ledger schema, CLI syntax, or message envelopes;
- making control-lane failure look like clean exit 0;
- broad edits to copied `MultiQueueWatcher` without a focused failing test.

## Rollback and Rollout

### Rollback

- The shared `BaseReactor` and core watcher slice keeps
  `TautBaseWatcher = BaseReactor`, so the already-published Summon package remains
  importable while the new Summon package is prepared. Core behavior and Summon
  policy commits remain independently revertible until Summon starts importing
  `BaseReactor` directly. After that point, revert Summon before or with core.
- Rollback restores code and its exact spec paragraphs together. Never leave
  [TAUT-8.5] or [SUM-9] claiming guarantees that reverted code no longer
  provides.
- No data migration, queue deletion, or one-way storage change occurs. Existing
  chat history, cursors, control residue, and session rows remain readable.
- If persistent handles expose a SimpleBroker defect, hold release and fix or
  upgrade SimpleBroker. Do not roll back by restoring Taut retry wrappers.
- Never roll back to SimpleBroker 5.1.1. The minimum supported and tested runtime
  for this work is 5.2.2; the 5.2.0 reference remains design provenance only.

### Rollout

1. Land the shared `BaseReactor` plus core `TautWatcher` change while preserving
   the `TautBaseWatcher` alias. Build an installed wheel and prove that both the
   current worktree Summon and the last published Summon import against it; the
   old extension's reactor construction must fail before I/O with the explicit
   upgrade diagnostic rather than silently bypass ownership.
2. Land Summon against that exact Taut version; change its production import to
   `BaseReactor`, synchronize the extension's `taut>=` floor through the release
   helper, refresh `extensions/taut_summon/uv.lock`, and run `uv lock --check`.
3. Release core and Summon as one coordinated batch. Core may publish first only
   because the compatibility alias keeps the old extension importable; do not
   remove that alias in this release.
4. Release Summon only after its unit, deterministic process, blocked-inject,
   fatal-control-exit, and Postgres/shared-backend proofs pass against the built
   core wheel and SimpleBroker 5.2.2 or newer.
5. Canary for one installed-wheel process lane: require idle and busy PING within
   the existing request timeout, STOP completion within 30 seconds, nonzero exit
   plus released ledger after injected fatal control death, and no unhandled
   thread traceback. The release owner records the command, start/end time, and
   driver stderr tail. A live harness without PING or a Queue close overlapping a
   handler is a rollback-level incident.

One-way doors: none in storage or public CLI. The compatibility edge is the
separately packaged extension moving to the new core mechanism. The temporary
alias and absence of a runtime subclass-definition guard keep older packages
loadable; release notes tell first-party and advanced subclass authors to move
policy into protected hooks. Alias removal is a separate future compatibility
change and is out of scope.

## Proposed Spec Delta

Do not apply this section during plan authoring. The future implementation
starts with the spec-promotion slice after independent review.

| Spec file | Strategy | Sections touched |
|---|---|---|
| `docs/specs/02-taut-core.md` | A — in-file, text before link claims | [TAUT-3.4], [TAUT-8.3], [TAUT-8.4], new [TAUT-8.5], [TAUT-11], [TAUT-12.5], Related Plans |
| `docs/specs/03-identity-addressing-notifications.md` | A — in-file dependency correction | [IAN-8.2] |
| `docs/specs/04-summon.md` | A — in-file, text before link claims | [SUM-9], [SUM-11], [SUM-12], Related Plans |

### `docs/specs/02-taut-core.md` — replace the final paragraph of [TAUT-3.4]'s ownership bullet

> The `simplebroker>=5.2.2` floor is load-bearing. Persistent Queue handles for
> one resolved target share a process-local broker session; each driving thread
> receives its own thread-local backend core. Releasing an ordinary operation
> ends only its active-operation lease; it does not recycle the owning thread's
> cached core or end the Queue lease. `Queue.cleanup_connections()` explicitly
> recycles active handles while retaining the Queue lease, and `Queue.close()`
> ends the owned persistent lifetime. Taut follows the 5.2.0 reference-reactor
> rule: after drive begins, only the reactor owner performs normal Queue and
> sidecar work. Taut does not recreate SimpleBroker connection release or retry
> policy.

### `docs/specs/02-taut-core.md` — replace the dependency sentence in [TAUT-8.3]

> Core runtime dependencies: exactly `simplebroker>=5.2.2` and `psutil`.

### `docs/specs/02-taut-core.md` — replace the background ownership paragraph in [TAUT-8.4]

> `TautWatcher` uses the shared [TAUT-8.5] `BaseReactor` mechanism. The watcher
> returned by `TautClient.watch()` is the same instance driven by synchronous
> `run()` or background `start()`; it does not create a proxy/clone watcher.
> It owns persistent SimpleBroker Queue/runtime handles under the 5.2.0
> process-local-session and thread-local-core contract. While the owner thread
> is alive after drive begins,
> normal Queue operations, cursor writes, membership topology mutation, and
> handle close occur only on the drive owner. A foreign thread may request stop
> and inspect immutable queue-name snapshots, but it may not receive or use a
> live owned Queue. Removed membership handles close once; one-shot CLI/client
> paths remain transient.

### `docs/specs/02-taut-core.md` — insert after [TAUT-8.4]

> ### [TAUT-8.5] Reactor lifecycle and ownership
>
> `BaseReactor`, derived from SimpleBroker 5.2.0's executable reference reactor,
> owns the process/wait/request-stop/stop mechanism shared by Taut's long-lived
> queue reactors. One reactor instance has exactly one drive-thread
> owner after its first driven turn. `process_once()`, waiting, scheduling-state
> mutation, and dynamic topology mutation must run on that owner; a second
> drive caller and a same-owner reentrant turn fail before touching a queue.
> Read-only inspection may cross threads only through an immutable synchronized
> queue-name/topology snapshot; a live Queue is owner-only after drive begins.
> First-party policy subclasses extend protected turn/resource hooks rather than
> replacing the public lifecycle templates. The strong `Thread` object is
> authoritative and its numeric ident is diagnostic. A temporary internal
> `TautBaseWatcher` alias preserves compatibility for separately packaged older
> Summon versions; it is the same class, not a second behavior path. A legacy
> subclass that overrides a public lifecycle template may import but
> must fail construction before broker I/O with an actionable extension-upgrade
> diagnostic rather than drive unsafely.
>
> Stop has two stages. `request_stop()` only sets stop state and wakes local
> and broker waits; it is safe from handlers, signals, and foreign threads.
> `stop(join=...)` may join an owner from another thread, but it must not close
> reactor-owned handles while that owner is driving. The drive finalizer runs
> only after the turn loop has unwound, and closes owned queues, waiters,
> strategy resources, and runtime state exactly once on clean stop, bounded-run
> return, or unexpected failure. A foreign caller may close only after the owner
> thread exits; an instance that was never driven may be closed by its caller.
> Unexpected exceptions remain observable after finalization.
>
> Polling/activity infrastructure initializes only after drive ownership is
> claimed. One shared wait template follows the reference reactor and waits
> through `PollingStrategy` only. The strategy owns an optional native
> multi-queue waiter when the backend supplies one; otherwise it uses
> SimpleBroker's data-version path. No caller consumes the native waiter
> directly. A fixed-topology reactor binds its waiter once. Owner-thread dynamic
> topology mutation rebuilds and rebinds only the optional waiter for the new
> complete queue set; the strategy remains the sole authority and the retired
> waiter closes once. Broker activity, local activity, and stop are wake hints; after
> every wake the
> reactor rechecks authoritative pending/cursor state before dispatch. Taut
> does not wrap turns or queue operations in a second retry policy:
> SimpleBroker owns broker retry under [TAUT-3.4].
>
> A background `TautWatcher` drives the same instance returned by
> `TautClient.watch()`. Construction/configuration may precede drive with no
> concurrent use, as in the SimpleBroker reference; after ownership is claimed,
> only the live owner uses and closes its dedicated persistent handles. Its
> runtime does not share the source `TautClient` state handle; closing either
> object does not close the other. A removed membership queue is closed once.
> One-shot client and CLI paths remain transient.

### `docs/specs/02-taut-core.md` — append to [TAUT-11]

> - Reactor lifecycle tests must prove single drive ownership, signal-only
>   in-turn stop, `stop(join=False)` without early close, manual and background
>   drive finalization, exceptional-exit cleanup with the primary exception
>   preserved, idempotent concurrent stop, rejection of same-thread reentrant
>   turns and foreign-thread waits, owner-created strategy/waiter setup and
>   owner-thread native-waiter rebinding after dynamic topology changes,
>   local/broker wake, and drive-thread-only dynamic membership mutation. Queue close and
>   handler overlap must be tested with real broker queues in a temporary
>   database; shared construction/drive/close and native-wake conformance also
>   run against Postgres. The broker and watcher core path are not mocked.

### `docs/specs/02-taut-core.md` — append to [TAUT-12.5]

> Core and `taut-summon` reactor changes ship as a paired release. The release
> helper synchronizes the Summon `taut>=` floor to the exact new core version,
> refreshes every retained extension lock, and rejects any resolved
> `simplebroker<5.2.2` or `simplebroker-pg<3.1.0`. Release evidence includes an
> installed-artifact canary built from the paired wheels, not only source-tree
> tests. Core may publish first only as Summon's immediate dependency; neither
> package is announced until the paired canary passes.

### `docs/specs/03-identity-addressing-notifications.md` — replace the dependency paragraph in [IAN-8.2]

> Taut requires `simplebroker>=5.2.2` and `taut-pg` requires
> `simplebroker-pg>=3.1.0`. This compatible pair supplies the rename-capable
> backend handshake and the safe persistent-reactor ownership contract. The
> implementation must use `simplebroker.open_broker(...).rename_queue(...)`
> against Taut's resolved broker target; it must not assume `Queue.rename()` or
> a module-level `simplebroker.rename_queue()` exists.

### `docs/specs/04-summon.md` — replace the final SimpleBroker dependency paragraph in [SUM-9]

> The control reactor follows SimpleBroker 5.2.0's persistent-session and
> thread-local-core ownership contract. Operation release ends only the active
> lease; the owner thread retains its core until explicit cleanup or close.
> Summon must not recreate that release policy in extension-specific retry or
> cleanup code, and it must not run on SimpleBroker 5.1.x.

### `docs/specs/04-summon.md` — insert into [SUM-9] after that replacement

> The Summon control reactor is a fixed-topology policy subclass of the shared
> [TAUT-8.5] `BaseReactor`. It is constructed, driven, recovered, and closed on the
> dedicated control thread; its command topology is fixed for one driver
> generation; and its long-lived command, shared-reply, ledger, audit, and
> owner-client handles are persistent and owned. Per-request reply queues and
> one-shot control clients remain transient.
>
> `ControlLoop` is the thin context-specific supervisor for replaceable reactor
> instances. It invokes the shared public turn and wait templates, but regains
> control between them for audit, recovery, and fatal escalation.
> Control-handle recovery occurs only between turns. A handler, audit, or error
> callback may classify and record the failed turn, but it must not replace or
> close the reactor that remains on the dispatch stack. After the turn unwinds,
> `ControlLoop` may build a complete replacement handle set, atomically install
> it on the same owner thread, close the old set, and continue so the next loop
> iteration reacquires the installed reactor. Partial construction failure
> closes every new partial handle and leaves the old complete set installed. A
> failed replacement leaves the old set installed and reports degraded health.
> While the fault is pending, the supervisor retries replacement before any
> further process/audit/wait call on that old set, using the existing bounded,
> stop-interruptible backoff. Taut does not retry the consumed command or
> classify broker failures by message substring.
> Repeated replacement failure is bounded: once the existing control-drain
> failure threshold is reached without a successful complete replacement, the
> control loop reports a fatal control-plane failure to the driver supervisor.
> It must not remain alive indefinitely with unusable handles.
>
> Control waiting combines broker activity, local stop/wake activity, and the
> next rate-audit deadline. A due audit runs before timeout calculation, so a
> zero deadline cannot create a hot loop. A queued command can wake the loop
> before the audit cadence. The rate audit runs only at the between-turn
> supervisor seam, remains control-thread-owned, and preserves its in-memory
> cursor across successful handle replacement.
>
> Unexpected control-loop exit is a first-class driver failure. The control
> thread reports the failure to the foreground supervisor, which immediately
> interrupts the current adapter, stops the chat watcher, releases the driver
> claim, and exits nonzero. It must never leave a live harness without
> STOP/STATUS/PING, and it must not spend watcher-rebuild or harness-crash retry
> budgets. Expected STOP and driver shutdown remain clean exits and preserve
> the existing release-before-ack ordering.

### `docs/specs/04-summon.md` — append to [SUM-11]

> - Control reactor failure: a surfaced broker fault may reopen the complete
>   owned handle set between turns and continue under [SUM-9]. An unexpected
>   control-thread exit, programming failure, or exhausted consecutive
>   replacement-failure threshold wakes the foreground supervisor,
>   interrupts the harness, stops ears, releases the driver slot, and exits
>   loudly. A live-but-uncontrollable provider is forbidden.

### `docs/specs/04-summon.md` — append to [SUM-12]

> - Control-reactor tests are independent of core reactor tests. They must
>   prove fixed topology, control-thread ownership, persistent long-lived
>   handles, broker-activity wake before a long audit interval, no in-turn
>   handle close/reopen from dispatch or audit, cleanup of every partial
>   replacement-construction stage, no method call on a retired reactor,
>   due-now audit without spin, audit-cursor preservation across between-turn
>   reopen, and driver-visible initial-open/unexpected-return/fatal-exit cases.
>   At least the wake,
>   STOP-during-blocked-inject, fatal-exit, and cleanup cases run through a real
>   SQLite broker and real driver/scripted-provider process; mocks may cover
>   only adapter or clock boundaries, never broker/control dispatch.
> - Installed-artifact compatibility must prove four combinations: the new
>   core alone; the new core with the previously published Summon package
>   importing successfully but refusing obsolete reactor construction before
>   broker I/O; the new core and new Summon package completing live control
>   operations; and dependency resolution rejecting new Summon with an older
>   core.

### Related-plan backlinks present from plan authoring

Plan authoring added this plan to both specs' `## Related Plans` sections. The
promotion slice confirms and preserves these rows without duplicating them:

> - `docs/plans/2026-07-09-taut-reactor-safety-plan.md` — planned reactor
>   ownership, shutdown ordering, activity wake, inter-turn control recovery,
>   and control-thread supervision hardening. Do not cite proposed requirement
>   codes here until the promotion slice has created resolvable headings.

## Deviation Log

| Spec ref | Planned behavior | Actual behavior | Rationale | Spec proposal |
|---|---|---|---|---|
| [SUM-12], task 29 case 2 | The `taut_summon/v0.5.0` artifact imports against the new core, then its obsolete reactor construction is rejected before broker I/O. | The immutable tag at required commit `766e3aaf84f75046a57ef769b9c802148b42e71a` imports no reactor subclass at all: it has no `_ControlReactor`, `TautBaseWatcher` import, or other `*Reactor` class. The verifier records `legacy_reactor_surface=absent` and treats import isolation as the applicable v0.5.0 proof. If a selected prior artifact does expose `_ControlReactor`, the same probe requires the pre-I/O upgrade diagnostic. | A construction guard cannot fire for a class that does not exist. Fabricating such a class would not test the published artifact and would violate the immutable-ref requirement. | Applied to `docs/specs/04-summon.md` [SUM-12]: prior-artifact import plus capability detection is canonical; the pre-I/O construction diagnostic is required only when the legacy artifact actually exports a reactor class. |
| [SUM-12], core-first artifact import | Removing Taut's obsolete retry modules does not break the previously published Summon import. | Core retains `taut._broker_retry.is_transient_broker_error` as an import-only fail-closed shim. Calling it raises an actionable upgrade diagnostic; it does not classify or retry an error. | Immutable Summon v0.5.0 imports that private symbol at module load. Deleting the module breaks the promised core-first import before any reactor capability check can run. | No behavioral spec change: this is the narrow compatibility mechanism required to satisfy [SUM-12] without restoring 5.1-era retry policy. |
| [SUM-9], real-process persistent control visibility | A persistent owner-thread control Queue sees an external PING and replies before the audit interval. | Unit and same-process/subprocess-writer reactor gates pass, but the full driver process currently retains an old SQLite view on the persistent control Queue; a fresh transient Queue sees the row. Per-turn `cleanup_connections()` made it visible but reproduced `database disk image is malformed` / `disk I/O error`, so it was removed. | The observed failure crosses the SimpleBroker persistent-session boundary and cannot be masked without violating the promoted ownership and no-5.1-cleanup requirements. | No spec weakening. Resolve the persistent-session integration defect, then rerun ordinary PING/STATUS/STOP and the paired installed-artifact smoke before closeout. |

During delivery, append a row before continuing whenever code cannot match the
promoted text. `pending` is not permitted in the final column at closeout.

## Implementation Phases and TDD Tasks

Every behavior task below is a vertical red-green slice: write one behavioral
test, run it and observe the expected failure, make only that test green, then
continue. Do not write all tests first. Do not refactor while red.

### Phase 0 — independent review and spec promotion

1. **Confirm the completed independent plan/spec-delta review and baseline.**
   - The plan-level review is recorded below and has no open blocker. Re-run it
     if the proposed delta, shared mechanism, or release matrix changes before
     promotion.
   - Read first: this plan, both governing specs at the recorded baseline,
     both implementation docs, the reference reactor and its full test file,
     and all current touched code/tests.
   - Reviewer stance: identify unsafe ownership, incompatibility with the
     current dirty contention work, missing failure paths, and any test that
     mocks away the reactor interaction.
   - Required question: “Could you implement both reactor tracks confidently
     and independently, and does either track falsely rely on the other?”
   - Record each finding and disposition in `## Review Record` below.
   - Stop gate: do not promote while a reviewer cannot answer yes.

   Verify every ledger claim marked “Already covered” or used as an existing
   contrary-contract guard. Run exact nodes, not only `--collect-only`:

   ```bash
   PYTHONPATH=/Users/van/Developer/simplebroker uv run --no-sync pytest \
     tests/test_watcher.py::test_live_watcher_does_not_redispatch_after_cursor_advance \
     tests/test_watcher.py::test_watcher_claims_mention_notification_without_consuming_chat \
     tests/test_watcher.py::test_watcher_poison_message_advances_after_three_failures \
     extensions/taut_summon/tests/test_control.py::test_stale_command_for_old_driver_evidence_is_dropped \
     -q -n0

   PYTHONPATH=/Users/van/Developer/simplebroker uv run --no-sync pytest \
     extensions/taut_summon/tests/test_driver.py::test_dismiss_leaves_no_unclaimed_control_rows \
     extensions/taut_summon/tests/test_driver.py::test_ping_responds_while_harness_busy \
     extensions/taut_summon/tests/test_driver.py::test_stop_while_inject_blocked_completes \
     extensions/taut_summon/tests/test_conformance.py::test_control_responsive_mid_turn \
     extensions/taut_summon/tests/test_conformance.py::test_restart_replays_conversation_tail \
     -q -n 1 --dist loadgroup
   ```

   If a node is absent or does not fire the ledger claim, reclassify it as an
   adapted port and add its red-green task before spec promotion.

2. **Promote the exact spec delta using strategy A.**
   - Files: `docs/specs/02-taut-core.md`,
     `docs/specs/03-identity-addressing-notifications.md`, and
     `docs/specs/04-summon.md`.
   - Add requirement text and confirm the existing Related Plans backlinks.
     Do not duplicate them or add implementation mapping claims yet.
   - Reconcile manifests and retained locks to the supported pair:
     `simplebroker>=5.2.2` and `simplebroker-pg>=3.1.0`. The root manifest is
     already correct; update `extensions/taut_pg/pyproject.toml`, refresh
     `extensions/taut_summon/uv.lock`, and refresh the Taut PG lock if it will
     remain tracked. A resolved 5.1.x package is a stop failure.
   - Pin the executable reference, not just its version label. Require tag
     `v5.2.0` to resolve to
     `37ee5e6f600828e8d23f76349258a84c1efd8d31`, with SHA-256
     `a00a89fafb4dfd3207b5f4602a6fa92b86b949af8592c014e94093f8973b69ac`
     for `reference_reactor.py`,
     `97bf56f5cec9a78286f341e402a7348c34fe51b3139b9061410478ffe9c19c60`
     for its test file, and
     `6c3b6b63c666b257fa63fa9c8b5f80054622a5b58cd0ec46ae785d530e58b59d`
     for the ordered test-name stream. Stop and re-review if any pin changes.
   - Record the promotion baseline identifier in this plan.
   - Verify:

     ```bash
     uv run pytest tests/test_docs_references.py -q -n0
     uv lock --directory extensions/taut_summon --check
     uv lock --directory extensions/taut_pg --check  # if retained
     git diff --check -- docs/specs/02-taut-core.md \
       docs/specs/03-identity-addressing-notifications.md \
       docs/specs/04-summon.md \
       docs/plans/2026-07-09-taut-reactor-safety-plan.md
     ```

### Phase 1 — core reactor ownership and stop safety

This phase changes only the core reactor. Summon does not count as green yet.

3. **RED→GREEN: establish the shared `BaseReactor` seam.**
   - Rename the current shared class in `taut/watcher.py` to `BaseReactor` and
     retain `TautBaseWatcher = BaseReactor` as a one-release import alias. Do
     not export either from `taut.__init__`.
   - Port the 5.2.0 reference's public lifecycle templates:
     `process_once()`, `wait_for_activity()`, `run_until_stopped()`,
     `run_forever()`, `run_in_thread()`/`start()`, a trivial `run()` template
     that delegates to `run_forever()`,
     `request_stop()`, `stop()`, and compatibility `cleanup()`. Move Taut policy behind protected turn,
     wait/deadline, post-wake, topology, and resource-close hooks.
   - Add `test_base_reactor_rejects_empty_queue_configs` and require
     `ValueError` before Queue or database creation. If the inherited guard is
     already green, record it as inherited coverage rather than manufacturing
     a production change.
   - Add alias identity/import coverage. Do not add `__init_subclass__`; class
     definition by a previously published Summon package must remain possible.

4. **RED→GREEN CORE-R2/CORE-R11: claim one non-reentrant drive owner.**
   - Add real-queue tests proving a second drive thread, a foreign-thread wait,
     and same-thread recursive `process_once()` all fail before a second queue
     read or handler call. Use a strong `Thread` object as authority; keep the
     ident diagnostic only.
   - Do not yet mark the templates `@final` or add the compatibility
     construction check because the in-repository `TautWatcher` migration is
     task 10; task 10 enables both only after first-party core overrides are
     gone.
   - Do not hold the owner lock while waiting, joining, dispatching, or closing.
   - Add use-after-close and recycled-ident regressions.

5. **RED→GREEN CORE-R1: split stop request from close.**
   - Add a real-queue test whose handler blocks while a foreign thread calls
     `stop(join=False)`. Assert stop returns, the turn is signaled, and no
     Queue closes until the handler is released and the drive thread exits.
   - Add signal-only `request_stop()` using the existing stop event and
     strategy/wait notification. Make `stop()` request first, optionally join
     without holding locks, and defer close while a foreign drive owner is
     alive.
   - In a second red-green subcycle, arm a long idle wait, call
     `request_stop()` from another thread, and prove the loop exits well before
     the wait deadline without closing from the requesting thread.
   - The current scratch diagnosis must flip from
     `closed_while_turn_active=True` to false when converted into the test.
   - Green command targets that single test.

6. **RED→GREEN CORE-R3/CORE-R7: finalize exactly once on all exits.**
   - Port the reference shutdown tests one red-green subcycle at a time:
     delayed strategy startup must not close before the owner exits; a manual
     `threading.Thread(target=run_until_stopped)` must be joined before close;
     an external `stop(join=False)` must let that manual owner self-close; and
     a `_drain_queue()` exception escaping `run_until_stopped()` must close in
     the loop's `finally` after unwind while preserving the original exception.
   - After those are green, add a concurrent double-stop test proving each
     owned Queue and waiter is closed once and no caller deadlocks.
   - Add deterministic startup and active-turn cases: the intended background
     owner is registered before `Thread.start()`; start failure rolls state
     back; stop at the startup barrier does not close early; owner-thread stop
     inside a handler defers close until unwind; `stop(join=True)` on the owner
     never self-joins; start after a manual owner is rejected; stop after
     `CLOSED` is inert.
   - Implement the shared lifecycle mechanism above. `cleanup()` must defer
     or refuse unsafe external close while an owner is live; the owner
     finalization path is authoritative. Do not call inherited
     `BaseWatcher.stop()` as if it could see a manual owner. Move `TautWatcher`
     runtime close into its
     protected `_close_reactor_resources()` override so deferred base cleanup
     also defers runtime cleanup.
   - Add a strategy/resource assertion for the owner-thread path: after a
     background `start()` loop returns, the strategy and optional waiter, queues,
     and owned runtime are released once even though finalization ran before
     the Python thread itself returned.
   - Name the non-reference additions explicitly:
     `test_base_reactor_concurrent_stop_closes_once`,
     `test_base_reactor_exception_finalizes_and_reraises`,
     `test_base_reactor_owner_self_stop_defers_until_unwind`,
     `test_base_reactor_start_after_manual_foreign_owner_is_rejected`,
     `test_base_reactor_same_owner_run_after_manual_turn_is_allowed`, and
     `test_base_reactor_stop_after_closed_is_inert`.
   - Use supported `Queue.close()`, waiter/strategy close, and owned-runtime
     cleanup seams. Do not inspect or detach SimpleBroker's private
     `BaseWatcher._finalizer`.
   - Focused gate:

     ```bash
     PYTHONPATH=/Users/van/Developer/simplebroker uv run --no-sync pytest \
       tests/test_watcher.py \
       -k 'stop_during_startup or manual_drive or concurrent_stop or exception_finalizes or owner_self_stop or start_after_manual or same_owner_run or stop_after_closed or running_state' \
       -vv -n0
     ```
   - Preserve the primary exception if close also fails.

7. **RED→GREEN CORE-R5: restore running-state truth.**
   - Add a public `is_running()` test spanning start, active handler, stop, and
     joined exit.
   - Set/clear inherited `_running_event` in the explicit loop with the same
     finalizer nesting as cleanup.

8. **RED→GREEN CORE-R4/CORE-R9: start one owner-created strategy authority.**
   - Replace `test_taut_base_watcher_uses_process_wait_loop` with
     `test_base_reactor_centralizes_process_wait_stop_loop`. Prove wait setup
     occurs once on the drive owner, the initial turn runs before waiting,
     broker activity wakes the loop, and `process_once()` is not wrapped in a
     Taut retry layer.
   - Directly adapt the reference central-loop test: one subclass turn must go
     through `process_once → wait_for_activity → stop/finalize`, rather than a
     second BaseWatcher loop.
   - Add the reference input-activity wake as a real Queue adaptation: a writer
     process or independent Queue writes after the long wait is armed and the
     handler runs well before the configured timeout.
   - Adapt the reference first-driven-turn initialization guard: seed pending
     chat history, construct a subclass whose handler depends on subclass
     initialization completing, assert construction does not dispatch, then
     assert the first driven turn delivers safely.
   - Remove eager waiter construction from `MultiQueueWatcher.__init__`. On the
     first owner wait, call `create_activity_waiter_for_queues()` exactly once
     for the initial topology generation,
     pass its waiter-or-`None` result to `PollingStrategy.start()`, and consume
     broker activity only through `_strategy.wait_for_activity()`. Delete the
     direct `waiter.wait(timeout)` path. Use a bounded outer deadline loop with
     the local activity event so stop remains responsive.
   - Make waiter close ownership explicit: before binding, the creator owns a
     candidate; after binding, `PollingStrategy` owns it. Reconfiguration lets
     the strategy retire the prior waiter, and finalization calls strategy close
     once. No reset helper may detach/close the same waiter independently.
   - Add branch-specific tests: no waiter before ownership; setup/use/close on
     the owner; SQLite input and sidecar-only membership wake before a long
     fallback; Postgres native drive/wake/close through the strategy; and stop
     wakes the strategy in both backend modes. Every wake is only a hint and must be followed by an
     authoritative pending/cursor check.

   Canonical loop decisions, each with a firing assertion:

   | State at loop entry/turn exit | Required action |
   |---|---|
   | stop already requested | no turn; finalize once |
   | normal entry | claim owner, initialize the strategy for the current topology generation, run one turn, then wait |
   | input already pending | first driven turn dispatches only after construction is complete |
   | `max_iterations` reached | no further turn; finalize even if input remains |
   | turn raises unexpected exception | finalize, then re-raise the same primary exception |
   | `StopWatching` with stop requested | normal finalization |
   | `StopWatching` without stop requested | finalize, then re-raise; do not turn a policy defect into clean exit |
   | owner-thread stop inside a standalone turn | finish the active stack, then self-finalize |

9. **RED→GREEN CORE-R8: drive-owned topology mutation.**
   - Add a TautWatcher membership-churn test that proves add/remove still occur
     on the drive owner and removed Queue close happens after removal on that
     owner.
   - Add a second-thread mutation test that fails loudly once the reactor is
     driven. `list_queues()` may expose a synchronized immutable name snapshot;
     `get_queue()` becomes owner-only after drive begins and must never return
     a background-owned live Queue to the foreground.
   - Make fixed topology the `BaseReactor` default. `TautWatcher` explicitly
     opts into dynamic topology because membership churn is required.
   - On each owner-thread add/remove, increment the topology generation and
     mark the optional waiter binding dirty. Before the next wait, rebuild the
     native waiter from the complete new queue set, rebind it to the same
     strategy, and close the retired waiter once. Add a Postgres test proving a
     newly added queue wakes, a removed queue no longer participates, and no
     stale waiter survives the generation swap. An unchanged generation must
     not rebuild the waiter on every wait.
   - Put the Postgres firing proof in
     `extensions/taut_pg/tests/test_reactor.py` as
     `test_taut_watcher_native_waiter_rebinds_on_membership_topology_change`,
     marked `pg_only`. `tests/test_watcher.py` is module-wide `sqlite_only` and
     cannot satisfy this gate.

### Phase 2 — core TautWatcher integration

10. **RED→GREEN CORE-R6/CORE-R10: drive the same persistent watcher instance.**
   - Replace `test_taut_watcher_start_uses_nonpersistent_thread_clone` with a
     test proving the exact `TautWatcher` returned by `TautClient.watch()` is
     the object driven by synchronous `run()` and background `start()`.
   - Delete `_thread_watcher`, `_active_thread_watcher()`, proxy lifecycle
     overrides, and clone construction. In `taut/client/_watching.py`, replace
     `_ClientWatchRuntime(state=client._state)` with a watcher-owned runtime
     built from immutable `target`/`config` values and its own persistent
     metadata Queue plus `SqlSidecarTautState`. Reuse/reshape the existing
     `_ThreadOwnedWatchRuntime` implementation rather than leaving two runtime
     adapters. Construction and initial configuration/I/O may precede drive
     without concurrent use; after ownership is claimed, only the drive owner
     uses and closes it.
   - Prove construction, first use, topology mutation, and close thread ids;
     replace cross-thread Queue inspection with recorded owner-thread evidence.
     One-shot client paths remain transient.
   - Add bidirectional isolation tests: closing or continuing to use the source
     `TautClient` must not close or perturb a running watcher, and watcher close
     must not close the source client's state/Queue. A partial owned-runtime
     construction failure closes its Queue before propagating.
   - Register the intended background owner before `Thread.start()`, roll back
     on start failure, and do not begin a turn when stop is already requested.
   - Now enable the `BaseReactor` construction compatibility check using the
     canonical guarded-method tuple. A legacy
     subclass that replaces a public lifecycle template must import and define
     successfully, then fail construction before broker I/O with an actionable
     “upgrade taut-summon” diagnostic. Do not use `__init_subclass__`.
   - Mark the shared public lifecycle templates `@final` in the type surface
     only after the core subclass has stopped overriding them. Summon's source
     remains intentionally red until its independent migration in task 16.
   - Update Summon's existing fake-client expectation later in the Summon
     phase; a core green result does not prove Summon uses it correctly.

11. **RED→GREEN reference restart replay adaptation for chat cursors.**
    - Add a real SQLite `TautWatcher` test that forces cursor persistence to
      fail after the user handler observes a message, lets the first watcher
      exit, then starts a fresh watcher for the same member. The message must be
      delivered again from durable history and advance only after the second
      handler succeeds.
    - This is the chat-cursor analogue of
      `test_crash_after_result_record_replays_pending_output_on_restart`; do not
      add a result sidecar or outbox.
    - Keep `test_taut_watcher_keeps_memory_cursor_when_advance_exhausts` as the
      narrow supporting proof, not the acceptance substitute.

12. **RED→GREEN reference per-queue ordering adaptation.**
    - Add a real multi-queue watcher test with messages in two chat threads.
      Assert each thread is delivered in timestamp order and no two handlers
      overlap, because the core reactor is deliberately single-threaded.
    - Cross-thread global order remains unspecified. The expected literal is
      per-thread order, not a recomputation of implementation scheduling.

13. **Run the independent core gate.**
    - Commands:

      ```bash
      PYTHONPATH=/Users/van/Developer/simplebroker uv run --no-sync \
        pytest tests/test_watcher.py -q -n0
      PYTHONPATH=/Users/van/Developer/simplebroker uv run --no-sync \
        pytest tests/test_client.py -q -n0
      ./bin/pytest-pg --fast \
        extensions/taut_pg/tests/test_reactor.py::test_taut_watcher_native_waiter_rebinds_on_membership_topology_change \
        -n0
      ./bin/pytest-pg --fast
      ```

    - Required result: all core lifecycle, cursor, membership, notification,
      SQLite wait, Postgres native-wake, and subprocess-writer tests pass.
    - Build the core wheel and test the compatibility boundary in isolated
      environments: both current pre-migration Summon source and the previously
      published Summon package import, but obsolete reactor construction fails
      before broker I/O with the upgrade diagnostic. New Summon is not expected
      to work until task 16; its live installed-artifact proof is a final paired
      gate. Do not begin Summon by waiving a core failure as “unrelated” without
      reproducing it on the recorded baseline.

### Phase 3 — Summon control reactor ownership and wait

This phase gives Summon its own proof. It must not merely inherit core tests.

14. **RED→GREEN Summon integration bridge: in-handler halt safety.**
   - This is the first Summon-owned slice and depends on the green core
     `request_stop()` contract. It is not part of the independent core gate.
   - In `extensions/taut_summon/tests/test_driver.py`, first add a narrow test
     showing `_halt_and_raise()` calls signal-only `request_stop()` and does
     not close the live watcher from inside the handler.
   - Change `_driver.py::_halt_and_raise()` from
     `watcher.stop(join=False)` to the new signal-only seam.
   - Run that exact driver node immediately, and include it in the Phase 4
     driver gate. Keep the existing real-process
     `test_repeated_failed_injects_do_not_advance_cursor` green; it remains the
     cursor/injection proof.

15. **RED→GREEN reference role-distinctness adaptation.**
    - Add a table-driven `test_control_reactor_derived_roles_are_distinct` in
      `extensions/taut_summon/tests/test_control.py` covering command input,
      shared reply, per-request reply, ledger, and audited chat queues.
   - These names are derived rather than user configured, so the port asserts
     the invariant instead of adding a new runtime rejection surface. Cover
     every `_BrokerHandles` queue role (command input, shared reply, ledger,
     each audited chat thread) and a representative per-request reply route as
     a separate client-owned role. Do not inaccurately claim the per-request
     queue is stored in `_BrokerHandles`.

16. **RED→GREEN SUM-R4: centralize the Summon process/wait loop and claim one
    owner.**
    - In `extensions/taut_summon/tests/test_control.py`, add tests that
      one control turn goes through the core process/wait lifecycle and that a
      second drive caller is rejected before a second command read.
    - In separate red-green subcycles, prove a pending command is not dispatched
      during constructor/subclass initialization and prove multiple commands
      are consumed in queue order with no overlapping handler execution.
    - Change `_ControlReactor` to inherit `BaseReactor` directly. Delete its
      public `process_once()` and `wait_for_activity()` overrides; its command
      drain becomes the protected turn hook. Move rate audit out of
      `_drain_queue()` so no audit or recovery can replace handles while a
      reactor turn remains on the stack.
    - `ControlLoop` is the explicit thin supervisor. At loop head, resolve any
      pending fault before reacquiring or touching a reactor. Otherwise,
      reacquire the installed reactor, run one public turn, run any due audit
      after unwind, resolve a newly pending fault/replacement, and only then
      wait through that same still-installed reactor. It must not duplicate
      owner, stop, or cleanup machinery.
    - Structural gate:

     ```bash
     rg -n '^    def process_once' taut extensions/taut_summon/taut_summon
     ```

      Expected: only `BaseReactor` defines the public method.
    - Add an architecture test that both first-party subclasses inherit every
      method in the canonical guarded lifecycle tuple unchanged. This is the
      enforcement for first-party code; do not add a runtime class-definition
      guard.
    - The control reactor and Core TautWatcher remain different modules with
      separate tests.

17. **RED→GREEN SUM-R6: reject dynamic control topology mutation.**
    - Directly port the reference dynamic-mutator rejection test to
      `_ControlReactor.add_queue()` and `remove_queue()`.
    - Reject both operations with the `BaseReactor` default fixed-topology
      diagnostic. Core `TautWatcher` remains the explicit dynamic exception;
      `_ControlReactor` must not override the public mutators.

18. **RED→GREEN reference malformed/unknown-control matrices.**
   - Extend the real control-lane robustness proof to the reference non-object
     matrix: JSON array, `null`, number, boolean, and JSON string. A non-object
     cannot carry `request_id` or `reply_to`; in an isolated test, assert its
     error on the driver's existing shared `sys.rsp_<member>` fallback queue,
     then use a later correlated PING on a per-request reply queue as the
     progress barrier.
    - In the next red-green subcycle, parameterize empty and unknown object
      commands, assert the correlated error body, and prove a following PING
      still succeeds.
    - Keep Summon's JSON-only contract. Do not port the reference plain-text
      command compatibility.

19. **RED→GREEN SUM-R3/SUM-R8: broker activity wakes before the audit
    interval.**
    - Add a real SQLite control-reactor test with a deliberately long audit
      interval. Start the reactor on its owner thread, write PING through a
      separate Queue, and require the correlated handling event/reply well
      before that interval.
    - Have `ControlLoop` run a due audit at the between-turn seam before it
      computes a timeout. Its timeout is the minimum of the core inactive-probe
      bound and the next audit deadline, and it passes that value to the
      inherited `BaseReactor.wait_for_activity()` template.
    - Add a due-now regression proving an audit is run before timeout
      calculation and cannot create a zero-deadline hot loop.
    - Do not assert exact milliseconds; use a generous bound that distinguishes
      native wake from the configured multi-second cadence.

20. **RED→GREEN SUM-R5: persistent, control-thread-owned handles.**
    - Add a test that records construction/use/close thread ids for the
      dedicated control reactor and its long-lived Taut client/ledger/audit
      queues, and asserts `persistent=True`.
    - Change `_ControlReactor` and the `ControlLoop` owner `TautClient` to
      persistent.
    - In `_driver.py`, use the existing `_persistent_client()` ownership path
      for the driver-lifetime ledger client; construct the generation-lifetime
      pump/mouth client as persistent on the pump thread; and construct the
      Summon watcher client as persistent on the watcher thread. Keep rejoin,
      bootstrap/setup, CLI, and `ControlClient` per-request reply queues
      transient.
    - Add separate driver tests for ledger, pump/mouth, and watcher construction
      and close thread ids. Do not infer these guarantees from the control-loop
      test.
    - In `test_driver.py`, update the independent Summon watcher test to require
      `watch(..., persistent=True)` and prove creation/close on the Summon
      watcher thread.

### Phase 4 — Summon inter-turn recovery and driver supervision

21. **RED→GREEN reference shutdown ports for the Summon control owner.**
    - Port three shutdown cases independently in
      `extensions/taut_summon/tests/test_control.py` or `test_driver.py`:
      delayed `_open()`/strategy startup is not closed underneath; a manually
      driven `_ControlReactor` is joined before close; and external
      `stop(join=False)` lets the control owner finalize its own handles.
    - The tests must instrument real Queue close timing. Core shutdown tests are
      not accepted as coverage because `ControlLoop` adds handle sets, STOP ack,
      and driver thread ownership.
    - Expected driver STOP still follows release-before-ack.

22. **RED→GREEN SUM-R1: defer handle replacement until the turn unwinds.**
    - Add a focused control test with a real reactor and instrumented Queue
      close that forces a broker-surface handler failure. Assert no old handle
      closes while the handler/`process_once()` stack is active; after the
      exception reaches `ControlLoop.run`, install the complete replacement and
      close the old set.
   - Add one owner-thread-only pending fault field to `ControlLoop`, with an
     explicit broker-recoverable versus fatal classification. Change
     `_handle_control_error()` to record that fault only. It must never call
     `_reopen_broker_handles()` or close a handle.
   - For a broker-surface handler failure, return the current continue/consume
     disposition, let `_process_queue_message()` finish, then have
     `ControlLoop.run()` check the pending fault immediately after
     `reactor.process_once()` and before any wait or next turn. Reopen the
     complete handle set there. Do not replay the already READ-consumed command.
   - For a non-broker/programming failure, preserve the pending primary
     exception. If the watcher converts the error-handler `False` result into
     `StopWatching`, `ControlLoop.run()` must inspect the pending fatal fault
     before treating `StopWatching` as expected. Only shutdown or a processed
     STOP may make `StopWatching` a clean control-loop exit.
   - Build a complete replacement bundle off to the side. If any construction
     stage fails, close every newly created partial resource, keep the old
     complete bundle installed, and retain the diagnostic. On success,
     atomically install the complete new bundle, close the retired bundle,
     reset the consecutive-failure count, then `continue` the supervisor loop
     so the next iteration reacquires the installed reactor. No method may be
     called on the retired instance.
   - If replacement fails, use the existing capped exponential recovery delay
     through `_shutdown.wait(delay)` and `continue`. At the next loop head,
     retry replacement before any process, audit, or wait on the known-faulted
     old bundle. A wait fault enters the same branch after the wait unwinds.
     Stop interrupts the delay. Reaching the existing threshold escalates fatal
     without one more old-reactor turn.
   - Clear a pending fault exactly once after successful recovery or after it
     is transferred to the driver-failure state. A failed replacement leaves
     the old handle set installed and records degraded health for the bounded
     retry window; it does not silently discard the pending diagnostic. At
     `_CONTROL_DRAIN_RECOVERABLE_FAILURES_BEFORE_DEGRADED` consecutive failed
     replacements, transfer the primary/latest diagnostic to the fatal control
     failure state from task 23.
   - Add a deterministic repeated-reopen-failure test proving attempts below
     the threshold stay degraded/retryable without another old-reactor turn,
     audit, or wait, and the threshold attempt wakes the driver fatal path. Do
     not add an independent retry counter or timer.
   - Repeat the same between-turn assertion for audit and wait faults. Dispatch,
     audit, and wait failures share one replacement seam; none may reopen from
     inside a callback or inherited lifecycle template.
    - Preserve `_audit_cursor` across successful replacement. Add a
      table-driven failure injection for every partial construction stage and
      assert exact close ownership for each created resource.
    - Do not retry the consumed command. STATUS/PING client correlation remains
      the recovery contract.

23. **RED→GREEN SUM-R2/SUM-R7: surface unexpected control-lane death.**
    - Add separate driver fields/events for control failure and the primary
      exception. Do not reuse watcher state.
    - Add `test_control_loop_exception_is_driver_fatal`, in which
      `ControlLoop.run()` raises after startup. Require the wrapper to record the
      error, wake the supervisor, request immediate adapter interruption, and
      produce `DriverError`/exit 1.
    - Add a real-process scripted-provider test with an explicit test-only fault
      injection at the control boundary. Use a test fixture `sitecustomize.py`
      placed first on that subprocess's `PYTHONPATH` to monkeypatch one private
      ControlLoop turn method to raise a sentinel exception after readiness; do
      not add a production environment flag, control verb, or permanent fault
      hook. Prove: the driver exits nonzero, the
      provider is reaped, the watcher stops, the driver ledger evidence is
      released, and later `status` reports nothing live. Never use a broker mock
      for this acceptance proof.
    - Add `test_unexpected_clean_control_loop_return_is_driver_fatal`. Expected
      STOP and `_control_stop` shutdown remain normal; a return without either
      condition must use the same fatal supervisor path.
    - Add `test_initial_control_open_failure_is_driver_fatal`. Initial `_open()`
      failure is fatal and uses the same supervisor path; it is not counted as
      a recoverable replacement attempt.
    - Focused unit gate:

      ```bash
      PYTHONPATH=/Users/van/Developer/simplebroker uv run --no-sync pytest \
        extensions/taut_summon/tests/test_driver.py::test_control_loop_exception_is_driver_fatal \
        extensions/taut_summon/tests/test_driver.py::test_unexpected_clean_control_loop_return_is_driver_fatal \
        extensions/taut_summon/tests/test_driver.py::test_initial_control_open_failure_is_driver_fatal \
        -q -n0
      ```

24. **Re-prove STOP and busy control independently.**
    - Run real-process:

      ```bash
      PYTHONPATH=/Users/van/Developer/simplebroker uv run --no-sync pytest \
        extensions/taut_summon/tests/test_driver.py \
        -k 'stop_from_another_terminal or ping_responds_while_harness_busy or stop_while_inject_blocked_completes or control' \
        -q -n 1 --dist loadgroup
      ```

    - Required result: STOP still acks after ledger release, PING remains live
      during a busy harness, and blocked inject is interrupted without early
      queue close.

25. **Run the independent Summon reactor gate.**
    - Commands:

      ```bash
      PYTHONPATH=/Users/van/Developer/simplebroker uv run --no-sync pytest \
        extensions/taut_summon/tests/test_control.py -q -n0
      PYTHONPATH=/Users/van/Developer/simplebroker uv run --no-sync pytest \
        extensions/taut_summon/tests/test_conformance.py \
        -q -n 1 --dist loadgroup
      PYTHONPATH=/Users/van/Developer/simplebroker uv run --no-sync pytest \
        extensions/taut_summon/tests/test_driver.py \
        -m 'xdist_group and not requires_live_harness and not requires_local_llm' \
        -q -n 1 --dist loadgroup
      PYTHONPATH=/Users/van/Developer/simplebroker uv run --no-sync pytest \
        extensions/taut_summon/tests/test_driver.py::test_control_loop_exception_is_driver_fatal \
        extensions/taut_summon/tests/test_driver.py::test_unexpected_clean_control_loop_return_is_driver_fatal \
        extensions/taut_summon/tests/test_driver.py::test_initial_control_open_failure_is_driver_fatal \
        -q -n0
      ```

    - Core tests are necessary but not accepted as a substitute for these
      results.

### Phase 5 — implementation docs and reciprocal traceability

26. **Close the core traceability chain.**
    - Update `docs/implementation/04-taut-architecture.md` with the core
      lifecycle rationale, drive-owner state machine, signal/finalize split,
      one-instance persistent watcher, single strategy wait authority, and why
      no watcher-level retry was added.
    - Update its Spec-Code Trace row to cite [TAUT-8.5], `BaseReactor`,
      `TautWatcher`, and the exact lifecycle tests.
    - Update `docs/implementation/02-repository-map.md` to name the shared
      reactor owner, and correct active SimpleBroker version text in
      `README.md`. Do not rewrite historical changelog entries; add the new
      release note in the normal release slice.
    - Add nearby code comments/docstrings in `taut/watcher.py` citing
      [TAUT-8.5].
    - Add implementation mapping text to the promoted [TAUT-8.5] only in this
      reciprocal-link slice.

27. **Close the Summon traceability chain independently.**
    - Update `docs/implementation/05-taut-summon-architecture.md` with the
      fixed control topology, control-thread handle ownership, between-turn
      recovery, audit deadline, and fatal control-lane supervision.
    - Update its Spec-Code Trace [SUM-9]/[SUM-11] row to cite
      `_ControlReactor`, `ControlLoop`, driver control-failure state, and the
      exact control/driver tests.
    - Add code comments/docstrings in `_control.py` and `_driver.py` citing
      [SUM-9]/[SUM-11].
    - Add implementation mapping text to the promoted Summon sections only in
      this reciprocal-link slice.

28. **Evaluate durable guidance.**
    - Mark the stale 5.1.1 conclusion in `docs/lessons.md` as corrected by the
      5.2.0 contract. Update the still-active
      `docs/plans/2026-07-08-taut-sqlite-contention-hardening-plan.md` to mark
      its 5.1.1 mechanism and verification direction superseded; do not rewrite
      older completed plans as if history had changed.
    - Add a separate concise dated lesson only if implementation exposes a
      reusable rule not already captured by “signal before close,” engineering
      principle 14, the corrected broker-lifetime lesson, or the existing
      long-lived-thread-death lesson. Do not duplicate the reference reactor
      narrative.

### Phase 6 — installed-artifact compatibility

29. **RED→GREEN the paired release compatibility matrix.**
    - Add `bin/verify-reactor-artifact-compat.py` plus focused CLI tests. The
      verifier accepts the new core and Summon wheel paths and immutable prior
      refs `v0.5.0` and `taut_summon/v0.5.0`. It verifies the refs exist on
      `origin`, exports each with `git archive` into a temporary source tree,
      builds prior wheels there, and records commit and wheel SHA-256 values.
      Do not depend on GitHub Release assets: those tag publications currently
      have no release asset records.
    - For each case, create a fresh temporary virtual environment, remove
      `PYTHONPATH`, install only wheels plus resolved third-party dependencies,
      and assert imports resolve under that environment's `site-packages`, not
      this checkout:
      1. new core alone imports and exercises the base reactor construction
         guard with SimpleBroker 5.2.0 or newer;
      2. new core plus the prior Summon wheel imports and records whether the
         immutable prior artifact exposes a legacy reactor surface. The pinned
         v0.5.0 artifact has no such class, so its applicable result is
         `legacy_reactor_surface=absent`. If a prior artifact does export
         `_ControlReactor`, construction must fail before Queue/database
         creation with the upgrade diagnostic;
      3. new core plus new Summon completes a real SQLite PING/STATUS/STOP
         control smoke and releases its ledger;
      4. one resolver invocation with the prior core wheel plus new Summon
         fails specifically because the new Summon `taut>=` floor excludes
         version 0.5.0.
    - Assert both previous refs resolve on `origin` to
      `766e3aaf84f75046a57ef769b9c802148b42e71a`, and that the new wheels'
      METADATA contains a single unmarked `simplebroker>=X.Y.Z` floor with
      `X.Y.Z >= 5.2.2`, plus the exact new
      Summon-to-core floor before executing the environments.
    - Acceptance command:

      ```bash
      uv run --no-sync python bin/verify-reactor-release-artifacts.py
      ```

    - Any checkout path in a probe's `sys.path`, any SimpleBroker below 5.2.2,
      a prior artifact with an exposed reactor that bypasses the expected
      compatibility diagnostic, an error other than the expected dependency
      resolution conflict, or a live control smoke without ledger release
      fails the gate.

## Reference-Test Applicability Ledger

Source of truth: every `test_*` function in
`/Users/van/Developer/simplebroker/examples/tests/test_reference_reactor.py`
at commit `37ee5e6f600828e8d23f76349258a84c1efd8d31`. There are 25 functions.
Each is classified separately for the core Taut reactor and the Summon control
reactor. “Already covered” always names the exact current test. “Direct port”
or “Adapted port” names the red-green task that must add the missing firing
test. “Not applicable” states the conflicting or absent contract; it is not a
silent skip.

| Reference test | Core Taut reactor | Taut Summon control reactor |
|---|---|---|
| `test_reactor_rejects_overlapping_queue_roles` | **Not applicable:** core watch has chat/notification queue classes validated by Taut addressing, not configurable input/output/control roles. | **Adapted port (task 15):** derived command/shared-reply/per-request-reply/ledger/audit role names must be pairwise distinct. |
| `test_reactor_rejects_empty_input_queues` | **Direct port (task 3):** `BaseReactor` must reject empty `queue_configs` before Queue creation. | **Not applicable:** `_ControlReactor` always has one derived command lane; callers cannot supply an empty lane set. |
| `test_base_reactor_centralizes_process_wait_stop_loop` | **Adapted port (task 8):** replace the old Taut base-watcher loop test with the complete shared process/wait/stop/finalize proof. | **Adapted port (task 16):** independent `_ControlReactor` policy-on-shared-template proof. |
| `test_worker_result_event_wakes_background_reactor` | **Not applicable:** core Taut has no worker or local-result lane. Adding a generic local wake API solely to imitate this test would violate YAGNI; stop wake and broker input wake have separate firing tests. | **Not applicable:** the control reactor has no worker-result lane; provider events remain on the separate event pump and do not mutate control turns. |
| `test_input_activity_wakes_background_reactor` | **Adapted port (task 8):** real Queue input must wake a long core wait. | **Adapted port (task 19):** a real control command must wake before a long rate-audit cadence. |
| `test_reactor_turns_have_single_thread_owner` | **Direct port (task 4):** second core drive caller fails before I/O. | **Adapted port (task 16):** second control drive caller fails before command read. |
| `test_reactor_rejects_dynamic_queue_mutators` | **Not applicable:** `TautWatcher` requires dynamic membership add/remove under [TAUT-8.4]; task 9 instead restricts mutation to its drive owner. | **Direct port (task 17):** Summon's one-generation control topology is fixed and rejects add/remove. |
| `test_stop_during_startup_waits_for_drive_thread_before_closing` | **Direct port (task 6):** delayed core strategy startup cannot be closed underneath. | **Adapted port (task 21):** delayed control `_open()`/strategy startup cannot be closed underneath. |
| `test_stop_waits_for_manual_drive_thread_before_closing_queues` | **Direct port (task 6):** external stop joins a manually driven core owner before close. | **Adapted port (task 21):** control owner receives an independent manual-drive/join-before-close proof. |
| `test_manual_drive_thread_self_closes_after_external_stop_join_false` | **Direct port (task 6):** manual core owner finalizes after external signal-only stop. | **Adapted port (task 21):** manual control owner finalizes its full handle set after external `join=False`. |
| `test_control_lane_is_peek_checkpointed_not_consumed` | **Already covered (chat-history adaptation):** `tests/test_watcher.py::test_live_watcher_does_not_redispatch_after_cursor_advance` plus `test_watcher_claims_mention_notification_without_consuming_chat` prove peek/cursor chat history and the explicit consumable notification exception. | **Not applicable:** [SUM-9] deliberately claim-consumes commands with `read_one`; `extensions/taut_summon/tests/test_driver.py::test_dismiss_leaves_no_unclaimed_control_rows` proves the contrary at-most-once contract. |
| `test_non_object_control_payload_returns_error_and_lane_progresses` | **Not applicable:** core watch has no JSON control lane. | **Adapted port (task 18):** complete the array/null/number/bool/string matrix through the real lane, observe the uncorrelated error on the shared fallback reply queue, and prove progress with a following per-request PING. Existing `test_control.py::test_parse_malformed_body_yields_empty_command` and `test_driver.py::test_malformed_control_body_does_not_crash_loop` are partial coverage. |
| `test_plain_text_control_command_remains_supported` | **Not applicable:** core watch has no control commands. | **Not applicable:** [SUM-9] intentionally requires JSON; plain text is a documented divergence from Weft/reference compatibility. |
| `test_unknown_object_control_command_returns_error` | **Not applicable:** core watch has no control commands. | **Adapted port (task 18):** existing `extensions/taut_summon/tests/test_driver.py::test_malformed_control_body_does_not_crash_loop` proves progress after `BOGUS` but does not assert the correlated error body; add the complete error-and-progress proof. |
| `test_checkpointed_control_is_not_reprocessed_after_restart` | **Not applicable:** core chat restart semantics are cursor/history, not a control checkpoint. | **Not applicable:** Summon consumes commands at most once and generation-fences residue instead of replaying checkpointed control. Exact guards: `test_control.py::test_stale_command_for_old_driver_evidence_is_dropped` and `test_driver.py::test_dismiss_leaves_no_unclaimed_control_rows`. |
| `test_pending_output_replay_waits_for_first_driven_turn` | **Adapted port (task 8):** pending chat history must not dispatch during construction; first driven turn may deliver only after subclass initialization is complete. No output sidecar is added. | **Adapted port (task 16):** a queued command must wait for the first control turn and must not dispatch from constructor setup. No durable reply backlog is added. |
| `test_pending_output_rejects_configured_route_drift` | **Not applicable:** core watch has no stored output route. | **Not applicable:** reply routes are per-request input fields and are not durable replay rows; driver evidence, not route migration, fences generations. |
| `test_pending_output_drain_budget_fetches_one_backlog_sentinel` | **Not applicable:** core has no durable output backlog or replay budget. | **Not applicable:** Summon has no durable output backlog; one command is consumed per control turn and rate audit is a separate policy. |
| `test_existing_output_exact_id_replay_marks_written_without_duplicate` | **Not applicable:** core watcher writes no output messages. | **Not applicable:** control replies are not exact-id durable outbox records. |
| `test_pending_output_retries_in_process_after_transient_publish_failure` | **Not applicable:** core has no output publisher, and [TAUT-3.4] forbids a Taut retry layer. | **Not applicable:** Summon does not retry broker exceptions in-process; idempotent clients resend STATUS/PING after no reply under [SUM-9]. |
| `test_output_backlog_blocks_new_input_but_not_control_lane` | **Not applicable:** core watch has neither worker output backlog nor a control lane. | **Already covered (backpressure adaptation):** `test_conformance.py::test_control_responsive_mid_turn`, `test_driver.py::test_ping_responds_while_harness_busy`, and `test_driver.py::test_stop_while_inject_blocked_completes` prove control stays live while the data/injection lane is blocked. |
| `test_crash_after_result_record_replays_pending_output_on_restart` | **Adapted port (task 11):** a failed cursor commit followed by watcher restart must replay chat history; no outbox is added. | **Not applicable to the control reactor:** commands are intentionally at-most-once and have no durable result row to replay. Summon's separate ears lane already has conversation replay coverage in `test_conformance.py::test_restart_replays_conversation_tail`. |
| `test_processor_error_publishes_error_envelope_and_advances_checkpoint` | **Already covered (different poison contract):** `tests/test_watcher.py::test_watcher_poison_message_advances_after_three_failures` proves Taut's specified three-attempt warning/advance behavior; Taut does not publish worker error envelopes. | **Not applicable:** provider/harness failure follows [SUM-11] resume/exit and never publishes a reactor result envelope. |
| `test_non_json_processor_result_publishes_error_and_advances_checkpoint` | **Not applicable:** core handlers return `None`; there is no processor result serialization or output envelope. | **Not applicable:** adapters yield a closed typed event union, not arbitrary JSON processor results. |
| `test_per_queue_single_inflight_preserves_source_order` | **Adapted port (task 12):** core is single-threaded, so prove per-thread order and no handler overlap across two queues. | **Adapted port (task 16):** control is single-threaded, so prove command queue order and no overlapping dispatch. The existing injection-order test covers the separate ears reactor, not control. |

Ledger reconciliation gate:

```bash
test "$(git -C /Users/van/Developer/simplebroker rev-parse v5.2.0^{commit})" = \
  37ee5e6f600828e8d23f76349258a84c1efd8d31
test "$(shasum -a 256 \
  /Users/van/Developer/simplebroker/examples/reference_reactor.py | cut -d' ' -f1)" = \
  a00a89fafb4dfd3207b5f4602a6fa92b86b949af8592c014e94093f8973b69ac
test "$(shasum -a 256 \
  /Users/van/Developer/simplebroker/examples/tests/test_reference_reactor.py | cut -d' ' -f1)" = \
  97bf56f5cec9a78286f341e402a7348c34fe51b3139b9061410478ffe9c19c60
test "$(rg '^def test_' \
  /Users/van/Developer/simplebroker/examples/tests/test_reference_reactor.py | \
  sed -E 's/^def ([^(]+).*/\1/' | shasum -a 256 | cut -d' ' -f1)" = \
  6c3b6b63c666b257fa63fa9c8b5f80054622a5b58cd0ec46ae785d530e58b59d
test "$(rg -c '^def test_' \
  /Users/van/Developer/simplebroker/examples/tests/test_reference_reactor.py)" \
  -eq 25
```

If any reference pin or count changes before implementation, stop. Review the
new executable reference, then update this ledger and firing matrix before
promotion or code work. A version label without matching content is not enough.

## Reference-Port Firing-Test Matrix

Every applicable reference test not already covered above has a named future
Taut test. Implement these one red-green subcycle at a time.

| Reference test | Reactor | Required Taut firing test | Task |
|---|---|---|---|
| `test_reactor_rejects_empty_input_queues` | Core | `tests/test_watcher.py::test_base_reactor_rejects_empty_queue_configs` | 3 |
| `test_base_reactor_centralizes_process_wait_stop_loop` | Core | `tests/test_watcher.py::test_base_reactor_centralizes_process_wait_stop_loop` | 8 |
| `test_input_activity_wakes_background_reactor` | Core | `tests/test_watcher.py::test_base_reactor_input_activity_wakes_background_reactor` | 8 |
| `test_reactor_turns_have_single_thread_owner` | Core | `tests/test_watcher.py::test_base_reactor_turns_have_single_thread_owner` | 4 |
| `test_stop_during_startup_waits_for_drive_thread_before_closing` | Core | `tests/test_watcher.py::test_base_reactor_stop_during_startup_waits_before_close` | 6 |
| `test_stop_waits_for_manual_drive_thread_before_closing_queues` | Core | `tests/test_watcher.py::test_base_reactor_stop_waits_for_manual_drive_thread` | 6 |
| `test_manual_drive_thread_self_closes_after_external_stop_join_false` | Core | `tests/test_watcher.py::test_base_reactor_manual_drive_self_closes_after_stop_join_false` | 6 |
| `test_pending_output_replay_waits_for_first_driven_turn` | Core | `tests/test_watcher.py::test_taut_watcher_pending_history_waits_for_first_driven_turn` | 8 |
| `test_crash_after_result_record_replays_pending_output_on_restart` | Core | `tests/test_watcher.py::test_taut_watcher_cursor_failure_replays_after_restart` | 11 |
| `test_per_queue_single_inflight_preserves_source_order` | Core | `tests/test_watcher.py::test_taut_watcher_preserves_per_thread_order_without_handler_overlap` | 12 |
| `test_reactor_rejects_overlapping_queue_roles` | Summon | `extensions/taut_summon/tests/test_control.py::test_control_reactor_derived_roles_are_distinct` | 15 |
| `test_base_reactor_centralizes_process_wait_stop_loop` | Summon | `extensions/taut_summon/tests/test_control.py::test_control_reactor_centralizes_process_wait_stop_loop` | 16 |
| `test_input_activity_wakes_background_reactor` | Summon | `extensions/taut_summon/tests/test_control.py::test_control_reactor_input_activity_wakes_before_audit_deadline` | 19 |
| `test_reactor_turns_have_single_thread_owner` | Summon | `extensions/taut_summon/tests/test_control.py::test_control_reactor_turns_have_single_thread_owner` | 16 |
| `test_pending_output_replay_waits_for_first_driven_turn` | Summon | `extensions/taut_summon/tests/test_control.py::test_control_reactor_pending_command_waits_for_first_driven_turn` | 16 |
| `test_per_queue_single_inflight_preserves_source_order` | Summon | `extensions/taut_summon/tests/test_control.py::test_control_reactor_consumes_commands_in_queue_order_without_overlap` | 16 |
| `test_reactor_rejects_dynamic_queue_mutators` | Summon | `extensions/taut_summon/tests/test_control.py::test_control_reactor_rejects_dynamic_queue_mutators` | 17 |
| `test_stop_during_startup_waits_for_drive_thread_before_closing` | Summon | `extensions/taut_summon/tests/test_control.py::test_control_reactor_stop_during_startup_waits_before_close` | 21 |
| `test_stop_waits_for_manual_drive_thread_before_closing_queues` | Summon | `extensions/taut_summon/tests/test_control.py::test_control_reactor_stop_waits_for_manual_drive_thread` | 21 |
| `test_manual_drive_thread_self_closes_after_external_stop_join_false` | Summon | `extensions/taut_summon/tests/test_control.py::test_control_reactor_manual_drive_self_closes_after_stop_join_false` | 21 |
| `test_non_object_control_payload_returns_error_and_lane_progresses` | Summon | `extensions/taut_summon/tests/test_control.py::test_non_object_control_payload_returns_error_and_lane_progresses` | 18 |
| `test_unknown_object_control_command_returns_error` | Summon | `extensions/taut_summon/tests/test_control.py::test_unknown_object_control_command_returns_error_and_lane_progresses` | 18 |

Final reference-port gate: every row in this matrix must collect and fire in
the focused test commands. No `xfail`, skip, placeholder parameter, or test
name without an exercised assertion satisfies the gate.

## Testing Plan

### Anti-mocking posture

- Real SimpleBroker Queue + temporary SQLite database for ownership, stop,
  wake, dynamic topology, and close-order tests.
- Real `TautWatcher`/`TautClient` for cursor and membership behavior.
- Real Summon driver process plus real scripted provider subprocess for
  control-lane fatal exit, STOP, busy PING, and blocked inject.
- Fakes are allowed only for clock/deadline control, adapter failure injection,
  and recording thread ids. A fake must not replace broker command dispatch,
  queue consumption, stop ordering, or driver process cleanup in the acceptance
  proof.
- Do not assert private flags as the only proof. Pair them with observable
  thread exit, queue close timing, control reply, cursor state, ledger release,
  or process exit.

### Behavior matrix

| Reactor | Behavior | Primary proof |
|---|---|---|
| Core | second drive caller rejected before I/O | focused `BaseReactor` real-queue test |
| Core | `stop(join=False)` signals but does not early-close | blocked-turn close-order test |
| Core | manual/background/exception exits close once | lifecycle tests + close spy on real Queue |
| Core | owner initializes the strategy and rebinds only on topology generation change; broker input and stop wake | live Queue writer, topology churn, and blocked-stop tests |
| Core | dynamic membership stays owner-threaded | live Taut membership churn test |
| Core | background live handles persistent and thread-owned | construction/use/close thread-id test |
| Summon | fixed single control owner | focused `_ControlReactor` owner/topology test |
| Summon | PING wakes before long audit cadence | real SQLite control wake test |
| Summon | reopen happens after unwind | close-order fault/recovery test |
| Summon | unexpected control death kills driver loudly | real driver + scripted provider process test |
| Summon | STOP during blocked inject remains clean | existing real-process regression |
| Summon | audit cursor survives handle reopen | focused control test |

### Red-green record

During implementation, append one line per test to the execution record with:

- test name;
- exact red command and failure reason;
- minimal green change;
- exact green command/result.

A test that was green before its implementation slice is not a red proof. If a
new test unexpectedly passes, strengthen it until it detects the diagnosed
gap or record that the finding was invalid and revise the plan.

## Verification and Gates

### Current diagnostic evidence

- Existing focused baseline:

  ```text
  PYTHONPATH=/Users/van/Developer/simplebroker uv run --no-sync pytest
    tests/test_watcher.py extensions/taut_summon/tests/test_control.py -q -n0
  result: 67 passed
  ```

- Current read-only scratch stop probe:

  ```text
  closed_while_turn_active=True
  drive_thread_alive=False
  ```

  This is diagnosis, not an acceptance test. Phase 1 converts it into a firing
  regression test.

### Per-phase gates

- Each red-green task runs its one test first.
- Phase 1/2: full `tests/test_watcher.py` and neighboring client tests.
- Phase 3/4: full control unit file, then fresh one-worker deterministic process
  invocations.
- Phase 5: docs reference check and diff inspection for reciprocal links.

### Final gates

Use a resolved SimpleBroker 5.2.2 or newer for source-tree gates, then repeat
the release canary against fresh built artifacts with dependency resolution
rejecting every SimpleBroker version below 5.2.2:

```bash
uv run --no-sync pytest \
  tests/test_watcher.py tests/test_client.py \
  extensions/taut_summon/tests/test_control.py -q -n0

uv run --no-sync pytest -q -n0

uv run --no-sync pytest \
  extensions/taut_summon/tests \
  -m 'not xdist_group and not requires_live_harness and not requires_local_llm' \
  -q

uv run --no-sync pytest \
  extensions/taut_summon/tests \
  -m 'xdist_group and not requires_live_harness and not requires_local_llm' \
  -q -n 1 --dist loadgroup

uv run --no-sync ./bin/pytest-pg --fast
uv lock --directory extensions/taut_summon --check
uv lock --directory extensions/taut_pg --check  # if retained

uv run pytest tests/test_docs_references.py tests/test_architecture_boundaries.py \
  -q -n0

uv run ruff check taut tests bin extensions/taut_summon/taut_summon \
  extensions/taut_summon/tests
uv run ruff format --check taut tests bin extensions/taut_summon/taut_summon \
  extensions/taut_summon/tests
uv run --extra dev mypy taut tests --config-file pyproject.toml
uv run --extra dev mypy extensions/taut_summon/taut_summon \
  extensions/taut_summon/tests \
  --config-file pyproject.toml
python -m compileall -q taut extensions/taut_summon/taut_summon
uv run --no-sync python bin/verify-reactor-release-artifacts.py
git diff --check
```

The verifier is the executable [SUM-12] four-combination gate. Preserve its
temporary-environment logs, resolved versions, ref commits, and wheel hashes as
release evidence. A source checkout on `PYTHONPATH` does not satisfy the gate.

External-live and local-LLM lanes remain release gates under the existing
plans. If implementation touches PTY/adapter code unexpectedly, run both before
claiming ready; otherwise record them as pending release verification rather
than pretending the deterministic scripted lane covers provider onboarding.

### Success signals after rollout

- deterministic close-order tests and absence of post-close broker exceptions in
  existing watcher/control error logs remain green; no new post-close logging
  mechanism is required;
- no live Summon driver fails PING while its process is otherwise healthy;
- unexpected control failure produces nonzero driver exit and released ledger
  evidence, not a silent log-only event;
- STOP latency stays bounded during idle, busy, and blocked inject;
- no increase in cursor replays beyond the documented at-least-once tail;
- SQLite integrity remains `ok` before and after control churn.

## Independent Review Loop

Repository policy requires independent review for this non-trivial async
lifecycle change.

Plan-review prompt:

> Read `docs/plans/2026-07-09-taut-reactor-safety-plan.md`, including the
> exact Proposed Spec Delta and strategy A. Read the current dirty versions of
> specs 02/04, implementation docs 04/05, `taut/watcher.py`, Summon
> `_control.py`/`_driver.py`, and the SimpleBroker reference reactor/tests.
> Treat core watch and Summon control as independent reactors. Look for unsafe
> ownership, early close, silent failure, contract drift, and mocked-away
> proof. Could you implement both tracks confidently and correctly without
> assuming that a core fix automatically fixes Summon?

Implementation review runs twice:

1. after the core reactor and core watcher slices, before Summon edits;
2. after Summon plus traceability reconciliation, before completion.

Give each reviewer the promoted spec baseline, this plan, both implementation
docs, touched files, and current commands/results. Record every finding below
as accepted/fixed, rejected with reason, or out of scope with reason.

Plan authoring received an independent source review and a separate Claude
adversarial review. Completed-work review remains required at the two slice
boundaries above.

## Review Record

| Stage | Reviewer | Finding | Disposition | Evidence |
|---|---|---|---|---|
| Plan authoring | independent source review | Core and Summon were initially easy to collapse into one lifecycle task. | Fixed: separate findings, phases, red tests, docs mappings, and gates now exist. | This plan's split structure. |
| Plan authoring | independent source review | A core-safe stop still fails if Summon's in-handler path invokes close semantics. | Fixed: the first Summon integration slice changes `_halt_and_raise()` to signal-only `request_stop()`. | Phase 3 task 14. |
| Plan authoring | independent source review | Reopen-in-error-handler can close the executing reactor even if close is idempotent; malformed non-object JSON cannot carry `reply_to`. | Fixed: recovery is an explicit pending-fault state handled after unwind; non-object errors use the shared fallback queue and a later keyed PING barrier. | [SUM-9], tasks 18 and 22. |
| Plan authoring | Claude adversarial review | Exceptional exit and standalone-versus-loop finalization transitions were underspecified. | Fixed: explicit drive-owner/active-turn state, terminal paths, and self-join behavior. | Required shared mechanism and task 6. |
| Plan authoring | Claude adversarial review | Repeated failed handle replacement could leave a live-but-uncontrollable driver. | Fixed: the existing consecutive-failure threshold now escalates to the fatal control-supervision path. | Fatal classification, [SUM-9]/[SUM-11], tasks 22-23. |
| Plan authoring | Claude adversarial review | Existing-coverage claims were not executed; one `-k` selector matched no planned test; the structural gate was in the wrong phase. | Fixed: exact-node baseline gates, corrected selector, and the structural audit now lives with task 16. | Phase 0, tasks 4 and 16. |
| Plan authoring | Claude adversarial review | The in-handler driver edit sat inside the core phase, and real-process fault injection was ambiguous. | Fixed: moved to the first Summon-owned slice; test-only `sitecustomize` monkeypatch is specified with no production flag. | Tasks 14 and 23. |
| Plan revision | independent mechanism review | A runtime `__init_subclass__` guard would make an already-published Summon package fail during class definition and could make the repository unloadable during migration. | Fixed: public templates are `@final`; first-party overrides fail an architecture test; obsolete external subclasses may import but fail construction before broker I/O with an upgrade diagnostic. | Shared mechanism, tasks 10 and 16, rollout compatibility gate. |
| Plan revision | fresh-eyes source review | A fixed native waiter would miss later-added Taut membership queues, and close ownership was split between the strategy and reset helper. | Fixed: `PollingStrategy` is the sole wait/close authority; owner-thread topology generations rebind its optional native waiter and close the retired waiter once. | Shared wait mechanism, tasks 8-9, named PG test. |
| Plan revision | fresh-eyes source review | Removing the clone without replacing `_ClientWatchRuntime` would leave the watcher sharing the foreground client's state handle and close lifetime. | Fixed: task 10 replaces it with a dedicated persistent runtime and adds bidirectional source-client/watcher isolation tests. | Core invariants and task 10. |
| Plan revision | fresh-eyes source review | A failed replacement could leave a pending fault, then process another at-most-once command on the known-faulted old reactor. | Fixed: loop-head fault gating retries replacement before process/audit/wait, with stop-interruptible backoff and fatal threshold. | [SUM-9], tasks 16 and 22. |
| Plan revision | fresh-eyes source review | Proposed close ownership, guarded lifecycle methods, Postgres collection, and fatal-control cases were not internally complete. | Fixed: owner-alive wording, one canonical guarded tuple with a local `run()` wrapper, an exact `pg_only` node, and named initial-open/clean-return/raised-exception tests. | [TAUT-8.4]/[TAUT-8.5], tasks 3, 9, 13, 16, 23, and 25. |
| Plan revision | fresh-eyes source review | The four installed-artifact combinations were requirements without an executable gate. | Fixed: task 29 builds prior wheels from immutable origin refs, runs four isolated environments without checkout paths, and records ref/wheel/dependency evidence. | [SUM-12], task 29, final gate. |
| Plan authoring | Claude post-correction confidence pass | No blockers; asked for task-6 names, cleanup-seam verification, terminal idempotency, and same-owner manual/run clarification. Answered the required confidence question “Yes.” | Fixed all four minor gaps. | Required shared mechanism and task 6. |
| Implementation, task 29 | independent artifact-gate review | Canonical [SUM-12] contradicted the immutable v0.5.0 surface; resolver classification was too broad; interrupt cleanup could orphan children; STATUS semantics and pre-I/O guard evidence were weak. | Fixed all findings: promoted capability-detection wording, strict uv conflict shape plus negative test, process-group teardown on timeout/interrupt, live STATUS field assertion, and a nonempty sentinel queue/database guard probe. | `tests/test_reactor_artifact_compat.py` focused gate; follow-up review found no remaining blocker after correcting the live health literal to `control_health=ok`. |
| Implementation | pending independent reviewer | pending | pending | pending |

## Out of Scope

- Weft implementation changes; its sibling plan/work owns that reactor.
- Porting the reference worker pool, result sidecar, durable outbox, or replay
  schema.
- Changing chat cursor durability, notification at-most-once behavior, or the
  poison-message threshold.
- Changing control consumption from READ to peek/checkpoint, or retrying STOP.
- New monitor tables, manager election, task lifecycle, or agent protocol.
- PTY query-response, attach/detach, provider protocol, persona, and session
  ledger schema changes.
- Redis state mapping, Postgres-specific redesign, CLI syntax, JSON field, or
  exit-code changes.
- Reformatting or cleaning unrelated dirty worktree changes.

## Fresh-Eyes Review

Completed for the revised plan on 2026-07-09:

- Exact current owners and files are named for both reactors.
- The dirty spec baseline and dependency on the existing contention work are
  explicit.
- Each diagnosed race has a firing red test before implementation.
- Core and Summon each have independent lifecycle, ownership, failure, docs,
  and verification tasks.
- All 25 reference test functions are classified for both reactors; the
  applicable uncovered cases have named firing tests and task numbers.
- Stop request, join, and close are separate operations; no task authorizes
  early close.
- `PollingStrategy` is the sole wait authority; dynamic waiter rebinding and
  close ownership have an exact Postgres firing test.
- The same-instance watcher owns state independent of its source client, and
  failed control replacement blocks further work on the known-faulted bundle.
- The plan states what must not be mocked and retains real process proof.
- Fatal, recoverable, and best-effort failures are distinguished.
- Rollback and rollout order precede implementation.
- Proposed spec text is exact and promotion is a future first slice, not a
  plan-only implementation target.
- No dependency, storage migration, second retry path, or new runtime lane is
  introduced.
- Independent findings have explicit dispositions. The final fresh-eyes pass
  found no remaining blocker after the recorded corrections.

## Execution Record

2026-07-09 to 2026-07-10: the promoted reactor requirements, shared
`BaseReactor`, core watcher migration, fixed-topology Summon control reactor,
inter-turn replacement, fatal driver supervision, documentation, and isolated
artifact compatibility verifier were implemented in the worktree. The
persistent-control PING blocker reproduced under the earlier dependency and
cleared with SimpleBroker 5.2.2; the rejected per-turn cleanup workaround was
not restored. Follow-on release orchestration and lifecycle findings are
tracked in the 2026-07-10 Summon quality remediation plan.

2026-07-10 follow-on: task 9's dynamic waiter behavior was initially delivered
by repeating strategy startup for each topology generation. SimpleBroker 5.3.0
now exposes the correct live replacement interface. The correction, ownership
rules, and native PostgreSQL proof are tracked in
`docs/plans/2026-07-10-taut-dynamic-native-waiter-replacement-plan.md`.

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|---|---|---|---:|---|---|
| CEO Review | `/plan-ceo-review` | Scope and strategy | 0 | — | Not required for this backend hardening plan. |
| Codex Review | `/codex review` | Independent second opinion | 0 | — | Independent repository subagent reviews are recorded above. |
| Eng Review | `/plan-eng-review` | Architecture and tests (required) | 1 | CLEAR | 10 issues found and folded into the plan; 0 critical gaps remain. |
| Design Review | `/plan-design-review` | UI/UX gaps | 0 | — | Not applicable; no UI scope. |
| DX Review | `/plan-devex-review` | Developer experience gaps | 0 | — | Not required before spec promotion. |

**VERDICT:** ENG CLEARED. The reviewed plan was promoted and implemented; final
integrated evidence is recorded by the 2026-07-10 Summon quality remediation
plan.

NO UNRESOLVED DECISIONS
