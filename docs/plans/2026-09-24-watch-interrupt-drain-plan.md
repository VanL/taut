# Watch Interrupt Drain Plan

Status: completed — 2026-09-24; implementation and verification complete;
owner chose exit 130; independent plan and completed-work reviews passed with
dispositions recorded below.

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

- [x] SIGINT on the main-thread drive records pending state, wakes the
  arbiter, and lets the turn loop unwind at its next boundary; cleanup
  closes every scope; `KeyboardInterrupt` is re-raised after cleanup so
  embedders still observe it.
- [x] A second SIGINT while the first is pending raises immediately (escape
  hatch for a blocked delivery write).
- [x] `taut watch` interrupted by SIGINT exits 130 in every phase, with the
  one-line `interrupted` diagnostic on stderr, never 1, never a traceback.
- [x] [TAUT-8.5] names `TAUT_MAX_INTERVAL` (the `TAUT` namespace) as the
  tuning knob, states the per-chunk recheck floor, and records the owner's
  idle-cost budget (ceiling 2.5% of one core per idle SQLite follower).
- [x] A firing test delivers a real SIGINT while the owner thread is inside
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
- Promotion baseline identifier: `docs/specs/02-taut-core.md` at worktree
  SHA-256 `8112a261759fa209887a35ce0cffa193f1302cc9cb463e4375efb01041dbdd3e`
  over Git base `cfd8799`. The worktree already contained concurrent,
  unrelated edits in [TAUT-3.2], [TAUT-7.2], other [TAUT-8.1] rows, and the
  related-plans list; the interrupt delta was applied without replacing them.

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

Proposed (owner-approved wording 2026-09-24; task 3 fills in the measured
numbers before promotion):

> `TAUT_MAX_INTERVAL` is the product tuning knob for the SQLite backoff
> ceiling; Taut resolves its configuration in the `TAUT` namespace and
> ignores ambient `BROKER_*` values ([TAUT-3.2]). The knob bounds the
> quiet-pass interval only: the retained strategy rechecks the data
> version on every wait chunk regardless of the ceiling, so idle cost has a
> floor the knob cannot move (the 2026-09-24 30-second local probe measured
> 1.41 percent of one core and 63.8 data-version queries per second at the
> default, versus 1.17 percent and 51.6 queries per second with
> `TAUT_MAX_INTERVAL=1.0`).
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

In the exit-code rule after the command table, add:

> Signal-interrupted `watch` is the fourth exit class: 130 after cleanup,
> matching SimpleBroker's `EXIT_INTERRUPTED` convention.

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
  the declared code and exactly `taut: interrupted\n` on stderr; `lsof` shows
  no `.taut.db` handles after exit.

## Dependency-Ordered Tasks

1. **Owner decision (resolved 2026-09-24): exit 130 on SIGINT**, matching
   SimpleBroker's `EXIT_INTERRUPTED` and its `interrupted` stderr line.
2. **Independent plan review** including the [TAUT-8.5] delta and the
   supersession of restoration-plan finding P2-1.
3. **Measure the knob.** Before editing [TAUT-8.5]'s knob sentence, run an
   idle `taut watch` for 30 s with and without `TAUT_MAX_INTERVAL=1.0` and
   count backend data-version queries (not only calls through the public
   `Queue.get_data_version` method). Record the numbers; pick the knob wording.
4. **Spec-promotion slice**; record the promotion baseline.
5. **Red test inside broker I/O.** `tests/test_watcher.py`: wrap the real
   `release_current_thread_connection` (the seam the review's deterministic
   reproduction used: raising at entry to that call left an open operation) so that the real SIGINT handler fires at
   entry, drive `run_forever` on the main thread, and assert: no
   `_ActiveOperationCloseError` from `stop()`, all handles closed
   (`lsof`-style check via the existing handle-lifetime helpers), and
   `KeyboardInterrupt` observed by the caller. Must fail at baseline with
   the close error. What stays real: SQLite, the strategy, the signal.
6. **Implement flag-and-drain** in `BaseReactor._sigint_handler` (record
   `_pending_interrupt`, call `notify_activity()`, return; second signal
   raises), observe the flag in the turn loop at the boundary where
   `_stop_requested` is already observed, and raise `KeyboardInterrupt`
   after `_finalize_run` in `run_forever`. Let `watch.py` unwind its existing
   `finally: watcher.stop(...)`; do not convert the exception to a command
   return there. Catch the escaping interrupt once in `dispatch()` after
   confirming the selected verb is `watch`, print the diagnostic, and return
   130. This covers pre-construction interruption without widening the command
   adapter return-code validator beyond 0/1/2. Rewrite every test pinned to the
   immediate raise, including the command-registry interrupt cases. Stop if the
   change needs a thread, timer, or Event in the handler.
7. **Stress proof.** Add a marked-slow test that runs the review's
   concurrent-writer SIGINT scenario 60 times and asserts every exit is the
   declared code (this is the regression for the flaky CLI test). Make the
   existing CLI test capture stderr and assert the one-line interrupt
   diagnostic with no traceback.
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
   responsiveness; task 3 records the measured numbers in the sentence.

## Deviation Log

| Spec ref | Planned behavior | Actual behavior | Rationale | Spec proposal |
|----------|------------------|-----------------|-----------|---------------|
| [TAUT-8.1] | `watch.py` maps the interrupt to 130 and `_dispatch.py` covers pre-construction interruption | `watch.py` performs cleanup and re-raises; public `dispatch()` maps only selected `watch` interrupts to the diagnostic and 130 | One boundary covers every watch phase, avoids duplicate diagnostics, and preserves the 0/1/2 command-adapter return contract | No semantic change; promoted text still declares 130 for interrupted watch |

## Review Log

(append-only)

- 2026-09-24 — Independent plan review attempt 1: Claude 2.1.273,
  read-only safe/plan mode with matched `Read,Grep,Glob` tools, strict MCP
  configuration, closed stdin, and no session persistence. The 540-second
  bound expired with no response or verdict (exit 124); no approval is
  inferred and no repository write occurred. Relaunch with a 900-second bound
  is a distinct attempt calibrated to this machine's prior 561–583 second
  reviews.
- 2026-09-24 — Independent plan review attempt 2: Claude Opus 4.6,
  identical read-only containment, 900-second bound. Completed in 558 seconds
  with success/end-turn signals and verdict PASS. P1-1 (the adapter validator
  rejects a returned 130) accepted as a design constraint and avoided: the
  command adapter re-raises, while `dispatch()` owns the selected-watch exit
  mapping. P1-2 (catch location underspecified) accepted and fixed in task 6.
  P2-2 (the general exit-code paragraph omitted 130) accepted in the proposed
  spec delta. P2-1 (claimed `_ActiveOperationCloseError` did not exist) rejected
  after checking the project `uv` environment: SimpleBroker 8.4.0 defines it
  in `simplebroker/session.py`, and `BrokerSession.close()` raises it when the
  current thread retains an operation depth. The reviewer had inspected only
  `_broker_session.py`. No repository write occurred.
- 2026-09-24 — Independent completed-work review: Claude Opus 4.6 under the
  same read-only containment returned PASS with no blockers. P1-1 observed
  that the copied scheduler's narrow `_topology_sigint_critical` /
  `_topology_deferred_sigint` path is now dead for `BaseReactor`; accepted as
  out-of-scope cleanup because the general flag-and-drain rule deliberately
  subsumes it. P2-1 observed that the dispatch boundary re-parses `argv` after
  an interrupt and a concurrent malformed invocation could replace the
  interrupt with `_UsageError`; accepted because valid `watch` invocations
  cover the declared contract and refactoring the dispatcher for this compound
  edge is disproportionate. The reviewer separately noted that a broken stderr
  could replace the diagnostic with `BrokenPipeError`; accepted as pre-existing
  terminal-loss behavior outside this signal-lifecycle delta. No repository
  write occurred.

## Execution Log

(append-only)

- 2026-09-24 — Owner decision: interrupted `taut watch` exits 130 with the
  `interrupted` diagnostic, matching SimpleBroker's convention.
- 2026-09-24 — Owner decision: [TAUT-8.5] names `TAUT_MAX_INTERVAL`;
  the `BROKER_` name was an error from before the namespace split. Idle
  budget: ceiling 2.5% of one core per follower, 1–2% accepted for
  responsiveness.
- 2026-09-24 — Task 3 measurement, real `taut watch --json`, real SQLite,
  backend `PRAGMA data_version` boundary, 30 seconds each. Default: 1.41% of
  one core, 1,915 queries (63.8/s). `TAUT_MAX_INTERVAL=1.0`: 1.17%, 1,549
  queries (51.6/s). A first high-level counter was discarded because it missed
  the strategy's retained bound callback. Both accepted measurements remain
  within the owner's 2.5% ceiling and demonstrate the 20 ms recheck floor.
- 2026-09-24 — Task 4 spec promotion completed with strategy A. Promoted
  [TAUT-8.1]'s watch exit and global interrupt class, [TAUT-8.5]'s signal
  drain and measured tuning-knob text, and the reciprocal related-plan link.
  The promotion baseline is recorded above; `git diff --check` passed for the
  spec and plan.
- 2026-09-24 — Task 5 RED observed before production edits:
  `uv run --extra dev pytest tests/test_watcher.py::test_base_reactor_sigint_drains_real_broker_operation_before_cleanup -n 0 -q`
  failed because the real SIGINT interrupted
  `release_current_thread_connection`; the child reported
  `_ActiveOperationCloseError`, the interrupt carried the reactor-cleanup
  failure note, and `_resources_closed` remained false. The first probe run
  exposed a test-wrapper signature error and was corrected before this valid
  behavioral RED.
- 2026-09-24 — Tasks 6–8 completed. The first SIGINT now latches pending state,
  wakes the existing activity strategy, and raises only at a turn boundary;
  the second signal remains an immediate escape. `watch.py` performs cleanup
  and re-raises, while the public dispatcher maps only `watch` interrupts to
  exit 130 and `taut: interrupted\n`. A non-watch interrupt firing test proves
  the boundary did not widen. The terminal-sink inventory records the added
  diagnostic write.
- 2026-09-24 — Verification: the focused watcher, CLI, and command-registry
  suites passed; the real 60-run randomized concurrent-writer SIGINT stress
  passed; Summon signal neighbors passed 3 tests and MCP shutdown neighbors
  passed 2 tests; touched-code Ruff and repository-wide mypy passed;
  `check-doc-paths`, `check-plan-status-index`, `check-cli-claims`, and
  `git diff --check` passed. The repository-wide suite reached 2,314 passed
  and 5 skipped before the terminal-sink inventory correction; that corrected
  gate then passed independently. Three residual full-suite failures are from
  concurrent out-of-scope identity and terminal/TUI/Summon edits: one reply
  semantic assertion and two Ruff-policy gates. Repository-wide Ruff reports
  the same unrelated new-file/import and complexity findings. The mutation
  requirement is satisfied by the recorded baseline RED, which ran the old
  in-frame handler against the real broker-operation probe.

## Fresh-Eyes Review

The seam most likely to be guessed wrong is where the loop observes the
flag; task 6 pins it to the existing `_stop_requested` observation point.
The dispatcher's pre-construction interrupt path is the second most likely
miss and has its own task line.
