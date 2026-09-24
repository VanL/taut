# Watch Interrupt Drain Plan

Status: draft — defect reproduced under load; owner chose exit 130 on
2026-09-24; awaiting independent plan review.

Class: 5 (spec-changing) and risky under [DOM-5]: the change revises the
normative signal-handling sentence in [TAUT-8.5], declares the
interrupted-watch exit code in [TAUT-8.1], corrects the tuning-knob name in
[TAUT-8.5], and touches the reactor's signal path (async/deferred work).
Hardening is required. Not process-changing.

Plan type: implementation with spec revision.

Owner: implementing engineer.

## Goal

Make Ctrl-C on `taut watch` exit cleanly and predictably. Today
`BaseReactor._sigint_handler` raises `KeyboardInterrupt` at whatever line
the main thread is executing. When that line is inside SimpleBroker's
per-operation bookkeeping (`_broker_session.py` `_end_operation`, reached
through the SQLite data-version poll), the session is left with an open
operation; `watch.py` returns 0 from the interrupt but its `finally:
watcher.stop()` raises `_ActiveOperationCloseError`, which is rendered as an
error with exit 1 and leaves four `.taut.db` handles open. Reproduced 6/60
and 3/60 under a concurrent writer, 0/80 idle. This is the "flaky"
`tests/test_cli.py::test_cli_watch_json_flushes_records_while_live`.
SimpleBroker's own `BaseWatcher._sigint_handler`, the copied Weft handler,
and Summon's `_on_signal` all record a flag instead; taut's reactor alone
raises in place. Evidence: `docs/plans/artifacts/2026-09-23-deep-dive-review.md`
§1 item 3 and §2 (tuning knob).

## Requested Outcomes

- [ ] SIGINT on the main-thread drive records pending state, wakes the
  arbiter, and lets the turn loop unwind at its next boundary; cleanup
  closes every scope; `KeyboardInterrupt` is re-raised after cleanup so
  embedders still observe it.
- [ ] A second SIGINT while the first is pending raises immediately (escape
  hatch for a blocked delivery write).
- [ ] `taut watch` interrupted by SIGINT exits 130 in every phase, with the
  one-line `interrupted` diagnostic on stderr, never 1, never a traceback.
- [ ] [TAUT-8.5] names `TAUT_MAX_INTERVAL` (the `TAUT` namespace) as the
  tuning knob, states the per-chunk recheck floor, and records the owner's
  idle-cost budget (ceiling 2.5% of one core per idle SQLite follower).
- [ ] A firing test delivers a real SIGINT while the owner thread is inside
  SimpleBroker I/O.

## Source Documents

Source specs:

- `docs/specs/02-taut-core.md` [TAUT-8.1] (`watch` row: "0 on clean stop"),
  [TAUT-8.4], [TAUT-8.5] (the "Core synchronous watch preserves immediate
  `KeyboardInterrupt` outside waiter replacement" sentence and the
  `BROKER_MAX_INTERVAL` sentence), [TAUT-12.3]
- `docs/specs/01-development-documentation-operating-model.md` [DOM-5],
  [DOM-6], [DOM-15]

Supporting context:

- `docs/program-theory.md` [THEORY-3] live-chat-watcher row and
  [REV-THEORY-002] (one wake path; a signal is a latch, not a second
  reactor).
- `docs/plans/2026-09-19-reactor-restoration-plan.md` (completed): the
  rule at line ~371 that the immediate interrupt "may remain", and reviewer
  finding P2-1 at line ~1806, which traced the immediate raise as safe
  because "unwind reliably reaches `stop()`". It does reach `stop()`; the
  defect is that `stop()` cannot close an open operation. This plan
  supersedes that disposition and records why.
- `docs/implementation/04-taut-architecture.md` reactor section.
- Installed SimpleBroker 8.4.0: `watcher.py` `BaseWatcher._sigint_handler`
  (line ~992: sets `_signal_stop_requested`, calls
  `strategy.notify_activity()`), `_broker_session.py` operation
  bookkeeping (line ~278, ~443), `db.py` `_pop_shared_operation_session`
  (line ~1012).
- `docs/plans/artifacts/2026-09-23-deep-dive-review.md` §1 item 3.

## Spec Baseline

- `c0a4616e76e954e3f9fbea93fbf487c3ee660cbe` — `docs/specs/02-taut-core.md`
  at plan authoring time; unchanged through `c894059` (0.9.9 release SHA).
- Promotion baseline identifier: recorded after the spec-promotion slice.

## Proposed Spec Delta

Promotion strategy: **A — in-file edit, text before link claims**.

| Spec file | Strategy | Sections touched |
|-----------|----------|------------------|
| `docs/specs/02-taut-core.md` | A | [TAUT-8.5] signal paragraph; [TAUT-8.5] tuning-knob sentence; [TAUT-8.1] `watch` row; `## Related Plans` |

### [TAUT-8.5] — replace the signal sentences

Current text (in the "Stop has two stages" paragraph):

> Python signal handlers publish plain pending state and use only
> the supported signal-safe notifier; they perform no Event, lock, logging,
> adapter or resource operation. Core synchronous watch preserves immediate
> `KeyboardInterrupt` outside waiter replacement and defers that raise until
> ownership transfer commits inside the replacement critical section. Normal
> stack unwind and owner execution perform cleanup.

Proposed text:

> Python signal handlers publish plain pending state and use only the
> supported signal-safe notifier; they perform no Event, lock, logging,
> adapter or resource operation, and they never raise into the interrupted
> frame. The first SIGINT on the drive owner records a pending interrupt
> and wakes the arbiter; the turn loop observes it at its next boundary,
> completes the current broker operation, unwinds through the ordinary
> finalizer that closes every owned scope, and then raises
> `KeyboardInterrupt` to the caller. A second SIGINT while one is pending
> raises immediately so a blocked delivery write can be escaped; that path
> may leave scopes for the finalizer's best-effort close. Waiter-replacement
> deferral is subsumed by this rule.

### [TAUT-8.5] — replace the tuning-knob sentence

Current: `` `BROKER_MAX_INTERVAL` is the product tuning knob. ``

Proposed (owner-approved wording 2026-09-24; task 5 fills in the measured
numbers before promotion):

> `TAUT_MAX_INTERVAL` is the product tuning knob for the SQLite backoff
> ceiling; Taut resolves its configuration in the `TAUT` namespace and
> ignores ambient `BROKER_*` values ([TAUT-3.2]). The knob bounds the
> quiet-pass interval only: the retained strategy rechecks the data
> version on every wait chunk regardless of the ceiling, so idle cost has a
> floor the knob cannot move (measured at about one percent of one core and
> roughly sixty data-version queries per second per idle SQLite follower).
> The accepted budget for an idle follower is at most 2.5 percent of one
> core; one to two percent is the deliberate trade for sub-100 ms local
> responsiveness. Lower the floor upstream in the strategy, never with a
> second Taut-side sleep ([REV-THEORY-002]).

### [TAUT-8.1] — amend the `watch` row exit cell

Replace `0 on clean stop; 1 error; 2 unrecognized member / explicit thread
or DM miss` with:

> 0 on clean programmatic stop; 130 when stopped by SIGINT, after cleanup,
> with the one-line `taut: interrupted` diagnostic on stderr (SimpleBroker's
> `EXIT_INTERRUPTED` convention); 1 error; 2 unrecognized member / explicit
> thread or DM miss. An interrupt that lands before the watcher is
> constructed uses the same 130 and prints no traceback.

### `## Related Plans` — add

> - `docs/plans/2026-09-24-watch-interrupt-drain-plan.md` — replaces the
>   immediate in-frame `KeyboardInterrupt` with flag-and-drain on the
>   reactor owner, declares the interrupted-watch exit code, and corrects
>   the tuning-knob name.

## Context and Key Files

Files to modify:

- `taut/watcher.py` — `BaseReactor._sigint_handler` (line ~1820–1828):
  sets `_stop_requested`, defers only under `_topology_sigint_critical`,
  otherwise `raise KeyboardInterrupt`; `run_forever()` (line ~1912–1935)
  installs the handler on the main thread and restores it in `finally`;
  `_finalize_run()` (line ~1900) attaches cleanup failures as notes;
  `_finish_topology_transaction` (line ~880–898) consumes the deferred
  flag; the vendored Weft `_sigint_handler` (line ~900) is the copied
  reference that already flags.
- `taut/commands/watch.py` — `run()` (line ~66–80): `except
  KeyboardInterrupt: return 0` then `finally: watcher.stop(join=True,
  timeout=5.0)`; the interrupt code is chosen here.
- `taut/commands/_dispatch.py` — `_run_prepared_invocation` re-raises
  `KeyboardInterrupt` (line ~277); confirm what exit the process produces
  when it escapes (`-2`/130 with traceback today when it lands during
  import or client construction).
- `tests/test_watcher.py` —
  `test_base_reactor_sigint_defers_cleanup_outside_signal_handler` and
  `test_reactor_restoration_real_signal_with_held_event_lock` pin the
  immediate raise and must be rewritten.
- `tests/test_cli.py` — `test_cli_watch_json_flushes_records_while_live`
  (assert exit code and capture stderr).
- `taut/_config.py` (line ~39: `resolve_config("TAUT", ...)`) for the knob
  finding — no change unless the owner picks the first knob wording.

Read first:

- [TAUT-8.5] in full; [REV-THEORY-002].
- SimpleBroker `BaseWatcher._sigint_handler` and where the loop converts
  `_signal_stop_requested` into a stop (grep `_signal_stop_requested`).
- The restoration plan's rule at ~371 and finding P2-1 at ~1806.

Comprehension gate:

1. **Why can `stop()` not close after an in-frame interrupt?** Expected:
   the interrupt can land between SimpleBroker's operation begin and end
   bookkeeping, leaving the session's active-operation count nonzero;
   `BrokerSession.close()` refuses with `_ActiveOperationCloseError`.
2. **Why is flag-and-drain not a second poll?** Expected: the handler calls
   `strategy.notify_activity()`, the same latch every other local event
   uses; the loop observes the flag on strategy return. No timer, no sleep.
3. **What is the cost of flag-and-drain?** Expected: exit latency of at
   most one handler turn plus one strategy pass (about 100 ms on SQLite);
   a blocked delivery write needs the second-SIGINT escape.

## Invariants and Constraints

- One wake path ([REV-THEORY-002]): the handler must use only
  `notify_activity`; no Event, lock, or sleep in the handler.
- Foreign-thread `request_stop()` and `stop(join=...)` semantics are
  unchanged.
- The drive finalizer still closes owned queues, waiters, strategy
  resources, and runtime state exactly once.
- Summon's driver and the MCP process reactor install their own signal
  handling; this plan must not change their behavior. Run their signal
  tests as neighbors.
- The `watch` CLI still flushes each record before handler return; no
  change to delivery.
- No new dependency; no change to SimpleBroker.

Hidden couplings:

- `_topology_sigint_critical` deferral becomes a special case of the
  general rule; remove the duplicate mechanism only if the topology test
  still passes with the general flag, otherwise keep both and document.
- The CLI dispatcher's `KeyboardInterrupt` re-raise path decides the
  process exit code when the interrupt lands before `run_forever`; the
  declared code must be produced there too (task 6).

Failure policy: a cleanup failure during the drained unwind is attached as
a note to the `KeyboardInterrupt` (existing `_finalize_run` behavior) and
does not change the exit code; a second-SIGINT escape may leave scopes
unclosed and logs one line.

## Rollout, Rollback, and One-Way Doors

- Source revert. No storage change. No one-way door.
- Post-deploy signal: 200 interrupted `taut watch --json` runs under a
  concurrent writer (the review's randomized-offset SIGINT shape) all exit with
  the declared code and empty stderr; `lsof` shows no `.taut.db` handles
  after exit.

## Dependency-Ordered Tasks

1. **Owner decision (resolved 2026-09-24): exit 130 on SIGINT**, matching
   SimpleBroker's `EXIT_INTERRUPTED` and its `interrupted` stderr line.
2. **Independent plan review** including the [TAUT-8.5] delta and the
   supersession of restoration-plan finding P2-1.
3. **Spec-promotion slice**; record the promotion baseline.
4. **Red test inside broker I/O.** `tests/test_watcher.py`: wrap the real
   `release_current_thread_connection` (the seam the review's deterministic
   reproduction used: raising at entry to that call left an open operation) so that the real SIGINT handler fires at
   entry, drive `run_forever` on the main thread, and assert: no
   `_ActiveOperationCloseError` from `stop()`, all handles closed
   (`lsof`-style check via the existing handle-lifetime helpers), and
   `KeyboardInterrupt` observed by the caller. Must fail at baseline with
   the close error. What stays real: SQLite, the strategy, the signal.
5. **Measure the knob.** Before editing [TAUT-8.5]'s knob sentence, run an
   idle `taut watch` for 30 s with and without `TAUT_MAX_INTERVAL=1.0` and
   count data-version queries (the review measured 1087 vs 900 over 15 s).
   Record the numbers; pick the knob wording.
6. **Implement flag-and-drain** in `BaseReactor._sigint_handler` (record
   `_pending_interrupt`, call `notify_activity()`, return; second signal
   raises), observe the flag in the turn loop at the boundary where
   `_stop_requested` is already observed, and raise `KeyboardInterrupt`
   after `_finalize_run` in `run_forever`. In `watch.py`, map the
   interrupt to the declared code; in `_dispatch.py`, make an interrupt
   that escapes before `run_forever` produce the same code without a
   traceback. Rewrite the two pinned tests. Stop if the change needs a
   thread, timer, or Event in the handler.
7. **Stress proof.** Add a marked-slow test that runs the review's
   concurrent-writer SIGINT scenario 60 times and asserts every exit is the
   declared code (this is the regression for the flaky CLI test). Make the
   existing CLI test capture stderr and assert it is empty.
8. **Docs, CHANGELOG, traceability, completed-work review, index flip.**
   Update `docs/implementation/04-taut-architecture.md` with the reason
   taut now matches SimpleBroker's handler and record in the restoration
   plan's Review Log (append-only) that finding P2-1's safety trace was
   incorrect and is superseded here.

## Testing Plan

- Layer: real `TautClient.watch()` reactors on real SQLite, real signals
  (`os.kill(os.getpid(), SIGINT)` from a helper thread), real
  SimpleBroker sessions. Do not mock the strategy, the session, or the
  signal.
- Files: `tests/test_watcher.py`, `tests/test_cli.py`.
- Mutation check: restore the in-frame raise and confirm task-4 fails.
- Neighbors: `extensions/taut_summon/tests/test_driver.py -k signal`,
  `extensions/taut_mcp/tests/test_process_reactor.py -k shutdown`.

## Verification and Gates

```bash
uv run --extra dev pytest tests/test_watcher.py tests/test_cli.py -n 0
uv run --extra dev pytest -n auto --dist loadgroup
uv run --extra dev pytest -m slow tests/test_watcher.py -k sigint -n 0
uv run --extra dev ruff check taut tests && uv run --extra dev mypy taut tests
bin/check-doc-paths && bin/check-plan-status-index
```

## Independent Review Loop

Reviewer: a different family from the author. Inputs: this plan, the
delta, `taut/watcher.py` signal paths, `taut/commands/watch.py`,
SimpleBroker's `BaseWatcher._sigint_handler`, restoration-plan P2-1.
Ask: "Is there any interval where flag-and-drain cannot observe the flag
within one strategy pass? Is the second-SIGINT escape necessary or armor?"

## Out of Scope

- Changing SimpleBroker's chunked data-version recheck (upstream).
- SIGTERM/SIGHUP handling for `watch` (today: default OS disposition, no
  traceback; unchanged).
- Summon and MCP signal paths.
- The vendored-Weft digest test (see the process plan).

## Assumptions and Open Questions

1. **Resolved 2026-09-24 (owner): 130.** Rationale: [TAUT-8.1] says exit
   codes match SimpleBroker, whose CLI returns `EXIT_INTERRUPTED = 130`
   with a one-line `interrupted` diagnostic; a caller can then distinguish
   a signalled stop from a requested one without parsing stderr.
2. **Resolved 2026-09-24 (owner):** name the real knob; naming the
   SimpleBroker value was always an error. The owner's idle-cost ceiling is
   2.5% of one core per idle follower, with 1–2% accepted as the trade for
   responsiveness; task 5 records the measured numbers in the sentence.

## Deviation Log

| Spec ref | Planned behavior | Actual behavior | Rationale | Spec proposal |
|----------|------------------|-----------------|-----------|---------------|

## Review Log

(append-only)

## Execution Log

(append-only)

- 2026-09-24 — Owner decision: interrupted `taut watch` exits 130 with the
  `interrupted` diagnostic, matching SimpleBroker's convention.
- 2026-09-24 — Owner decision: [TAUT-8.5] names `TAUT_MAX_INTERVAL`;
  the `BROKER_` name was an error from before the namespace split. Idle
  budget: ceiling 2.5% of one core per follower, 1–2% accepted for
  responsiveness.

## Fresh-Eyes Review

The seam most likely to be guessed wrong is where the loop observes the
flag; task 6 pins it to the existing `_stop_requested` observation point.
The dispatcher's pre-construction interrupt path is the second most likely
miss and has its own task line.
