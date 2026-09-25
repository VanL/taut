# Windows TUI Determinism Root-Cause Plan

Status: active — implementation authorized 2026-09-25; slice 1 diagnostic,
model and cap gates passed. Slice 2 implementation is in progress. S4 remains open.

Class: 4 (risky) under [DOM-5]: the work diagnoses and corrects asynchronous
TUI/Summon lifecycle behavior that runs in more than one execution context
(Textual's loop, Summon's phase threads, a real provider process on
ConPTY) and changes the test harness that gates Windows release evidence.
Hardening applies. No normative spec change is planned; if the deep dive
finds one is required, the class escalates to 5 with a declared delta.

Plan type: diagnosis (slice 1), then failing proofs and implementation
(slice 2), then hosted qualification (slice 3), with a spec-revision
escalator. The revision review is recorded below; execution evidence is
appended as each slice runs. Authorization does not claim S4 resolved.

Owner: implementing engineer. Owner direction (2026-09-24): "there should be
two things to happen: 1. a deep dive into root causes and how they can be
fixed, and how things can be made deterministic, and 2. if the current tests
are not enough, design of a test (or tests) that would be enough." Windows
bugs are closed by designing a test that elicits them and then using CI.

## Goal

Explain the Windows failures with causal evidence, then test the failure
orders directly. Write down which owner completes each phase and how that
completion reaches the existing reactor. Queue, PTY, worker, interrupt, and
deadline inputs feed one scheduling/wake owner per context under [TAUT-8.5];
this work introduces no separate domain control loop. Tests observe retained
completion for the exact request and phase. Portable ordering proofs plus
native Windows tests and a bounded soak form the acceptance gate, not a claim
that finite passing runs prove all possible executions deterministic.

## Evidence Register

The register is the input to slice 1. Historical observations, diagnoses,
and hypotheses remain distinct. CI counts and outcomes below are recorded
claims from the named runs; slice 1 retrieves their logs before relying on
them, and records unavailable artifacts explicitly. Current-tree checks do
not independently revalidate the historical hosted runs.

| # | Fact | Source |
|---|------|--------|
| E1 | 0.9.9 preparation commit `3993e20` was red on Windows TUI only; seven fix-forward commits (`d7e056a`…`583038e`) reached the first all-five-job green at `583038e`. The release SHA `c894059` was also green and both tags point there. Initial-to-release run creation spanned 1 h 54 m 41 s, not ~3 h. | runs 35917159249, 35927108722, 35928843388; remote tags `v0.9.9`, `taut_tui/v0.9.9` |
| E2 | The recurring recovery failure initially timed out at post-recovery orientation injection (1 failed/473 passed in 303.64 s); the next run also failed search selection (2 failed/472 passed in 366.99 s). Later failures included gate-menu/lease waits, wiring-run orientation, missing mounted controls, and Ubuntu reply-close focus. They are not one proven cause. | runs 35917159249, 35918083458, 35920877370, 35923841280, 35925072346, 35926016403; verified audit below |
| E3 | Recovery drives the real controller, provider, host PTY, and app. Narrow harness seams include fake `suspend()`, terminal suitability/fds, and a lease-body thread intercepting `TerminalLeaseRequest` so the headless pilot loop remains live. On Windows the provider is ConPTY. | `test_tui_summon.py` `_wire_gate_member`, `_gate_app`, `_configure_gate_pty`, `_prepare_gate_recovery` |
| E4 | Product root cause found in the streak: the TUI used `threading.get_ident()` as the terminal-ownership token across Summon's *distinct* confirmation and attachment phase threads; passing runs depended on numeric thread-id reuse. Fixed by an opaque per-run token (`_ScopedTuiSummonInteraction`, `583038e`; [TUI-11] sentence added). | `git show 583038e`; setup-recovery plan "2026-09-23 Release-hardening correction" |
| E5 | Second product root cause: a stale `OptionList` highlight message from a superseded transcript render could retarget selection after a search jump took ownership (`d7e056a`, `app.py` +7). | `git show d7e056a` |
| E6 | Verified harness corrections with unequal causal evidence: (a) separate host sessions remove a possible cancelled-I/O/reset-output leak, but no historical native trace proves it occurred; (b) deadline origin moved first to recovery generation, then to lease acquisition, without retained phase durations; (c) a headless lease-body thread removes a real pilot-loop blocking mechanism; (d/e) missing controls/OutOfBounds and premature focus are directly observed. The code changes are facts; not every proposed mechanism is a confirmed cause of the historical timeout. | `d7e056a`, `c53ddca`, `d41242a`, `5fcf32c`, `88a2f40`; retrieved logs in the verified audit |
| E7 | Windows retained job: 477 tests in 258 s vs 138 s on Ubuntu 3.13 (1.9×), both at `-n 2 --dist loadfile`. Owner (2026-09-24): Windows process/filesystem cost calls for a separate infrastructure budget, not a larger behavior deadline. Whole-suite duration is not a per-phase scaling measurement. | run 35928843388 job logs; owner statement |
| E8 | Historical inventory: fixed-attempt `_pause_until`, 32 counted loops across the app/Summon test modules, and 82 bare pilot pauses. These are search leads, not a current count or proof that every loop is a wait. Commit `e05c813` replaced the app helper with `_eventually` (5 s elapsed deadline), retaining `_pause_until` as an alias. Re-inventory the implementation SHA; distinguish input actions, causal drains, and liveness polling. | participation-loop commit `e05c813`; `test_tui_app.py`; 2026-08-14 lesson |
| E9 | S4's original run at `3e45409` failed the first DM-entry attempt-counted wait with no source/future/apply evidence. Follow-up `6326905` passed 462 tests on all five jobs; 20/20 local and macOS oversubscription are recorded. No subsequent S4 failure was found in the audited runs. The previously quoted 40 ms/280 ms timings have no located raw source and are withdrawn. Cause remains unresolved. | runs 35145237393, 35162150661; predecessor Execution Log; review artifact §5 (TUI) |
| E10 | The Windows lane runs `-n 2 --dist loadfile`: each file stays on one worker, but different files can run concurrently. Imbalance and contention require measurement; they do not follow merely from two large files. Keep this scheduler fixed during diagnosis and acceptance. | `.github/workflows/test-tui-extension.yml`, retained-suite step |
| E11 | The current S4 test observes the real navigation apply callback, retains the future result/error and rendered targets, then asserts the DM is present. The terminal-owner test holds the confirmation thread alive while a distinct lease thread runs. Both are existing proof to preserve. | `test_direct_message_header_and_composer_use_actor_scoped_label`; `test_terminal_lease_ownership_survives_distinct_driver_phase_threads` |

## Requested Outcomes

- [x] A written determinism model in `docs/implementation/12-taut-tui.md`:
  for every timing-sensitive phase (attach confirmation, terminal lease,
  recovery offer, orientation injection, navigation apply, transcript
  render, search jump, focus transition, resize), the event that completes
  it, who publishes it, and how a test observes it.
- [ ] Every confirmed root-cause class has a firing test and a failing
  mutation of the specific fix. Portable ownership/ordering proofs run on
  all retained platforms; Windows I/O and ConPTY proof runs natively on
  Windows. Unconfirmed hypotheses stay labeled as such.
- [ ] No attempt-counted liveness wait remains in the TUI suite. Tests use
  one TUI completion-observation interface over actual owner events, with
  infrastructure and behavior budgets separated. Legitimate finite action
  sequences and source adapters are classified, not mechanically rewritten.
- [ ] Five consecutive full Windows retained-suite repetitions on one
  immutable SHA, with two workers and `loadfile`, pass the acceptance gate.
  The new dispatch input controls repetitions within one Windows job;
  phase evidence is retained for every repetition.
- [ ] S4 of `docs/plans/2026-09-16-windows-lifecycle-determinism-plan.md`
  is inherited here as an open diagnosis. Close it only by causal
  reproduction and correction, or an explicit owner acceptance of the
  unresolved cause; the latter is not a root-cause claim.

## Source Documents

Source specs:

- `docs/specs/02-taut-core.md` [TAUT-8.5] (one scheduling/wake owner,
  state-before-wake, source adapters, deadlines, and nested contexts)
- `docs/specs/10-taut-tui.md` [TUI-4.1] (process model), [TUI-6.1]–[TUI-6.2]
  (opening and live delivery), [TUI-9.3] (resize processing), [TUI-11.1]–
  [TUI-11.3] (Summon availability, driver ownership, terminal handoff),
  [TUI-12.1], [TUI-12.3], [TUI-13.1]–[TUI-13.2]
- `docs/specs/04-summon.md` [SUM-7.4] (setup-recovery escalation),
  [SUM-13], [SUM-13.1] (foreground readiness for rich hosts)
- `docs/specs/01-development-documentation-operating-model.md` [DOM-5],
  [DOM-10.3] (eventual-evidence helper), [DOM-15]

Supporting context:

- `docs/plans/2026-09-16-windows-lifecycle-determinism-plan.md` (active):
  S4 and its gate; its Execution Log hosted-qualification entries.
- `docs/plans/2026-08-19-tui-setup-recovery-offer-plan.md` (active): the
  2026-09-23 correction section (E4).
- `docs/plans/2026-09-24-tui-participation-loop-plan.md` (completed at
  `e05c813`): owns the viewport extraction and elapsed-deadline app helper;
  this plan preserves its tests and generation ownership.
- `2026-08-11-eventually-test-helper-adoption-plan` (retired plan; source `434db87`)
  (completed): `tests.helpers.eventually` and `async_eventually`; the
  TUI's `_pause_until` predates or bypassed that adoption.
- `docs/program-theory.md` [THEORY-3], [REV-THEORY-002]: one wake path for
  every event kind. None of [THEORY-5]'s rejected alternatives is reopened.
- `docs/lessons.md`: Golden Rules; 2026-08-14 entries on committed UI
  focus/result application and misattributed aggregate timeouts; 2026-08-17
  native host routing; 2026-09-03 narrow clock seams; 2026-09-22 completion
  versus applied owner policy and duplicate observation.
- `docs/agent-context/runbooks/testing-patterns.md` Patterns 4, 7, 8.
- `docs/agent-context/README.md`, `decision-hierarchy.md`, `principles.md`,
  `engineering-principles.md`, `runbooks/writing-plans.md`,
  `runbooks/hardening-plans.md`, `runbooks/review-loops-and-agent-bootstrap.md`;
  `docs/implementation/12-taut-tui.md` and `03-agent-inventory.md`.
- `docs/plans/artifacts/2026-09-23-deep-dive-review.md` §5 (TUI).
- Slice-1 audits: `docs/plans/artifacts/2026-09-25-windows-tui-evidence.md`,
  `docs/plans/artifacts/2026-09-25-tui-completion-seams.md`, and
  `docs/plans/artifacts/2026-09-25-tui-wait-inventory.md`.

## Spec Baseline

- Historical evidence baseline: `c894059` (0.9.9 release SHA).
- Revision baseline: `33205d797814da07071bbe27d2336a057e233b8c` for the
  core, Summon, TUI, and operating-model specs named above. Record the
  implementation start SHA and reconcile intervening changes before slice 1.
- No normative spec change is proposed. A TUI-local completion helper does
  not change [DOM-10.3]'s predicate-polling API. If diagnosis requires a
  product contract change or a repository-wide helper/process revision,
  stop that dependent slice, declare Class 5 (and +P where applicable),
  review an exact delta, and promote it before implementation.

## Context and Key Files

Files to read first (current structure):

- `extensions/taut_tui/taut_tui/summon.py` — `TuiSummonInteraction`,
  `_ScopedTuiSummonInteraction` (E4), `TerminalLeaseRequest`,
  `TerminalAttachConfirmationRequest`; the coordinator that permits exactly
  one acknowledgement or lease.
- `extensions/taut_tui/taut_tui/app.py` — `_apply_delivery`,
  `_apply_navigation_result`, `_watch_future`, transcript selection and
  search restoration. Read `viewport.py` before changing generation handling;
  E5's historical OptionList fix may have a different adapter after later work.
- `extensions/taut_tui/taut_tui/session.py` — `refresh_navigation` and the
  serialized public-client worker (the S4 production path; edit only on
  causal evidence).
- `tests/helpers/terminal_probe.py` — `HostTerminal`,
  `run_terminal_child`; `extensions/taut_summon/tests/fixtures/gate_harness.py`.
- `extensions/taut_tui/tests/test_tui_summon.py` — `_await_until`,
  `_wire_gate_member`, `_gate_app`, `_GateAnswerer`, the recovery test, and
  the existing distinct-phase-thread regression; `test_tui_app.py` —
  `_eventually`/`_pause_until` and the observed DM-navigation apply callback.
- `extensions/taut_summon/taut_summon/_driver.py` — `_after_owner_settle`
  (setup-recovery decision, `awaiting_onboarding`, orientation injection);
  `extensions/taut_summon/taut_summon/_pty_windows.py` — `_AttachSession`,
  chunk queue, cancellation.
- `.github/workflows/test-tui-extension.yml` — matrix and `-n 2 --dist
  loadfile`; it has no `windows_repeat` input yet.
- `tests/helpers/eventually.py` and its [DOM-10.3] contract — read for
  deadline/failure semantics, not as authority to add another polling owner.
- Planned new files: `extensions/taut_tui/tests/_completion.py` (thin
  TUI test completion observer) and `test_tui_determinism.py` beside it.
  The gate fixture's `_chat_loop` already logs each input before emitting
  its `echo:` output. Prefer that acknowledgement via the existing adapter's
  output callback (`WindowsPtyHandle._observe_output`, or the POSIX handle's
  existing terminal-state `observe_output`); account for chunks and bind it to
  the exact run/marker. Extend the fixture only if that existing proof is
  insufficient. Keep the log assertions. No new product event bus is planned.

Comprehension gate (answers in the Execution Log before slice 2):

1. **Which identifier ordering exposes the old ownership bug?** Expected:
   distinct confirmation and lease identities in one logical run. Reuse
   masked the bug. Keep the first thread alive while the second runs; do
   not churn threads hoping to reproduce a platform's reuse schedule.
2. **What is the difference between "the screen object exists" and "the
   control is mounted", and which one may a test press?** Expected:
   Textual creates widget objects before the mount/compose cycle
   completes; input posted before mount is dropped or misrouted; a test
   may act only after the actual mount and required focus are observed.
3. **Why must an infrastructure phase and a behavior phase have separate
   budgets?** Expected: a single aggregate cap
   expiring identifies the work in progress but does not prove that phase
   consumed it; Windows process and ConPTY setup has platform-dependent
   cost, and charging it against the behavior deadline makes a fast
   behavior look slow. Delay after the behavior-start event still consumes
   the behavior budget and must fail when that budget expires.
4. **Does unified event observation allow a second control loop?** Expected:
   no. Source adapters publish results and wake the existing owner; tests
   subscribe to the exact owner's completion. A worker result is not UI
   application, a wake is not completion, and a message type is not a
   request identity. Production Textual intentionally pauses during a lease;
   confirmation completes before acquisition. Only the headless suspension
   body uses the existing test-owned thread seam.

Incorrect answers block implementation until the named contract is reread.

## Invariants and Constraints

- One scheduling owner and one wake arbiter per context under [TAUT-8.5].
  Source adapters publish authoritative state before waking that owner.
  Clock work uses its owned deadline. No timer, test helper, or worker may
  independently poll or advance the same domain state. Textual and the
  broker owner may compose through published completions; neither starts
  another observer of the other's broker state.
- Positive assertions follow exact completion. Negative assertions follow
  a causal/terminal fence and inspect retained state. Elapsed time is a
  containment bound, never evidence of non-occurrence. Tests of the
  deadline helper itself may use a narrow controlled clock.
- One TUI test interface observes completion, as specified below.
  `_pause_until` and `_await_until` liveness adapters are retired after
  their callers are classified. Native reads, cancellation, and joins stay
  with the existing source/resource owner and publish into that interface;
  this is not permission for separate domain control loops.
- Real boundaries stay real ([TUI-13.1]): real `TautApp`, real SQLite, real
  Summon controller, real provider process, real host PTY for acceptance
  flows. The existing headless suspend/thread and fd adapters remain narrow
  harness seams. Pure deadline and completion-record tests need no provider.
  Test observers wrap real callbacks without replacing their implementation.
- Product changes require causal evidence from a test failing without
  them. A missed deadline alone identifies neither product nor harness
  responsibility. Demonstrate where setup was charged or which owner failed
  before selecting a fix; preserve unknowns as unknowns.
- Windows lane parallelism (`-n 2`) and every existing assertion are
  preserved; budgets may be restructured (infrastructure vs behavior) but
  no behavior deadline grows.
- No new dependency.
- The setup-recovery plan's E4 correction and its firing test are not
  reopened; they are the model's first worked example.
- The retained lane remains `-n 2 --dist loadfile`. Scheduler tuning is
  outside this plan so qualification preserves the incident's concurrency.

Hidden couplings:

- Summon's driver phases (`settle`, `orientation`, recovery offer) publish
  to the TUI through `TerminalAttachNotice`/`TerminalLeaseRequest`; the
  test's orientation oracle reads a provider-written log. A file write is
  not automatically a subscribable event. Observe a fixture acknowledgement
  emitted after provider consumption/logging through the existing PTY
  adapter/owner, then inspect the log once. Do not add a filesystem polling
  thread or a second reader of the product's PTY. Slice 1 must identify the
  exact callback and prove that acknowledgement cannot precede consumption.
- `loadfile` distribution makes the two heaviest files each a single
  worker's serial run; per-test budgets are therefore paid under
  contention from the other worker's process spawns.
- The S4 navigation path shares `_watch_future` with every other worker
  result; a fix that changes result application ordering affects the
  tail-pin work in the participation plan.

Failure policy: a confirmed product defect blocks completion. A harness
cause is corrected and recorded without reclassifying it as product behavior.
Timeout diagnostics include the last completed phase and the unfinished
owner, but do not assert that the sampled owner caused the timeout.

## Completion Observation Contract

Owner: `extensions/taut_tui/tests/_completion.py` (new), used by TUI tests.
Boundary: observing real owner transitions, not scheduling product work or
adding a production event bus. Reuse existing result callbacks, Textual
mount/focus/application events, and retained futures. Add a test subclass or
callback observer before adding a production publication. A required product
publication needs a failing causal proof and review first.

The interface accepts a retained completion handle plus an absolute
monotonic deadline and a description. Its identity is the owning operation,
request/generation, and phase. A bare message class cannot identify it.

1. Register observation before triggering the action. Terminal outcomes are
   retained, so completion before the await is not lost. For an existing
   operation, use its retained result or an atomic observe/register seam;
   a non-atomic check-then-subscribe sequence is forbidden.
   The existing DM-navigation test's subclass override, installed before
   `run_test` initiates navigation and observing after the real apply call,
   is a conforming pre-registration pattern. The helper must accept that
   pattern; wrapping a callback after an operation started is not equivalent.
2. Source callbacks publish immutable outcomes through the owning loop's
   thread-safe entry point. Success, failure, cancellation, and supersession
   are explicit terminal outcomes; stale generations cannot satisfy a newer
   request. A wake alone is never success.
3. Observe the phase named by the assertion: navigation after real apply,
   usable controls after mount/focus, provider input after consumption,
   and resource retirement after join/close. Raw worker completion proves
   only the worker phase. Tests still assert final visible/domain state.
4. Await cooperatively on the existing event loop. Use the remaining deadline
   without resetting it on intermediate messages. At expiry inspect the
   retained outcome once before reporting a timeout. Accept only an outcome
   published at or before that deadline in the same monotonic clock domain:
   delayed wake delivery does not erase timely completion, but late publication
   cannot turn expiry into success. Producer exceptions
   and cancellation remain visible rather than becoming timeout failures.
5. Timeout/cancellation detaches the observer and cancels only helper-owned
   waiter tasks, not the shared producer future. Test teardown explicitly
   requests stop and waits for the producer/adapter's own retirement under
   a cleanup cap. Late callbacks after observer disposal do no work.
6. Keep records local to the test/run and release them on teardown. No
   process-global registry or unbounded completion history. The helper does
   not consume broker/PTY records, call `process_once`, retry actions, or
   introduce its own polling schedule.

Firing tests cover completion before/during await, wrong generation,
success/error/cancel/supersede, exact deadline expiry, observer disposal,
and preservation of the producer on observer timeout. Scheduling barriers
and narrow helper-owned clock seams make these deterministic; do not patch
the shared `time` or `threading` modules.

Adapters publish actual transitions once, not every call to an idempotent
producer. Repeated/competing confirmation `resolve`/`fail` calls retain the
first decision while preserving every real call and the production callback.
Test both repeated and competing calls. Screen result delivery and screen
retirement are separate observations: use the result callback for application,
and the real cancellation-shielded removal completion for unmount assertions.

## Budget and Hosted Acceptance Contract

Each inventory row records existing timeout semantics, infrastructure-start
and infrastructure-ready events, behavior-start and behavior-complete events,
and teardown/retirement. Behavior starts at the actual user action or owner
handoff being tested, not when the test happens to await it. A product promise
covering end-to-end startup may not move its start past that startup.

Keep existing explicit behavior limits, including the app helper's 5 s
baseline after `e05c813`. An attempt count was never a fixed elapsed bound;
record that ambiguity and justify the proposed bound in the model before
conversion. Do not silently replace all waits with a larger default.
Infrastructure and cleanup have separately named containment caps. Locate
the applicable repository CI scaling seam; if no TUI factor exists, record
that fact and review explicit measured caps rather than inventing a factor
or using the whole-suite 1.9× ratio. No behavior limit grows in this plan.

For budget proof, hold setup behind a barrier, then release it within its
infrastructure cap and require behavior within its unchanged limit. A paired
case withholds behavior completion after behavior starts and must time out.
Check the deadline arithmetic with a controlled helper clock; integration
barriers control ordering rather than sleeping to manufacture a race.
Measured latency and p95 are diagnostic evidence, not automatic root-cause
classification; retain sample count and raw phase durations.

Qualification uses **N = 5 repetitions in one Windows job on one commit
SHA**. There is no second K multiplier or count of workflow invocations.
The planned `workflow_dispatch` input `windows_repeat` accepts integers 1–5,
defaults to 1, and applies only to Windows; push, pull-request, and
workflow-call behavior remains one run per matrix entry. Each repetition
starts a fresh pytest process with the retained lock, `-n 2 --dist loadfile`,
the full suite, and phase recording. Run repetitions sequentially, preserve
each exit code, and fail the job on any failure, timeout, or missing result.
Do not retry or select a green subset inside the job.

Keep each repetition's existing 20-minute containment cap and bound the job
by `15 + 20 * N` minutes (35 for the ordinary one-run lane). Use five
conditional Windows invocation steps, each with `timeout-minutes: 20`;
steps two through five run only when requested and prior steps succeeded.
The existing first invocation and non-Windows caps remain unchanged. Do not
put all repetitions in one 20-minute step or substitute a pytest-internal
timeout for the Actions-step containment. Propagate native command failures
explicitly on PowerShell and cover invalid inputs, early failure, and timeout
without weakening test deadlines. Collect artifacts in an `always()` step.

Always upload per-repetition results and bounded phase records, including on
failure: SHA, workflow/run attempt, OS/Python/lock identity, ordinal, test
count/skips, exit code, durations, and request/generation/phase outcomes.
No message bodies, credentials, or provider screen content are needed. Define
the phase tripwire in slice 1: missing/duplicate terminal outcome, wrong
generation accepted, or phase ownership/order violation. Normal phase logs
are not tripwire failures. A passing job needs five full successes with no
tripwire violation and no unexplained test/skip reduction, plus green retained
non-Windows jobs at that SHA. A source, fixture, lock, or workflow change
requires a new complete five-run qualification at its new SHA.

This is a finite acceptance sample combined with causal regression proof.
It neither proves zero flake probability nor supplies the missing S4 cause.

## Rollout, Rollback, and One-Way Doors

- Harness changes and product fixes land in separate commits so a product
  fix can be reverted alone. No storage or wire change; no one-way door.
- Post-deploy signal: the fixed-SHA five-repetition qualification above and
  no recurrence in ordinary retained-lane runs. A later recurrence reopens
  the corresponding diagnosis with its retained phase evidence.

## Dependency-Ordered Slices

### Slice 1 — Root-cause deep dive (diagnosis only, no product edits)

1. **Revalidate evidence and inventory waits.** Retrieve the cited CI logs
   and inspect E4–E6's commits. Record the start SHA. Search all TUI test
   modules for `_eventually`, `_pause_until`, `_await_until`, other polling
   helpers, counted loops, and pilot pauses. Inspect their callers, not
   just matching lines. For each liveness wait record test, phase, owner,
   request/generation, completing event, current budget, proposed observation
   hook, and teardown. Classify finite input sequences and intentional causal
   drains separately. Missing historical logs stay an evidence limitation.
2. **Write the determinism model.** Draft `## Determinism model` for
   `docs/implementation/12-taut-tui.md` in this plan's Execution Log.
   Map every requested phase and root-cause class in the matrix below to
   its existing scheduling owner, source adapter, retained completion, and
   test seam. For missing observation, first use a callback observer or
   fixture acknowledgement; propose production publication only if those
   cannot prove the real phase. Class (b) is a headless harness mismatch,
   not a requirement that production process UI messages during suspension.
   No existing event source receives a second polling observer.
3. **Measure native phases.** Add the bounded dispatch input and result
   capture described above. Instrument the recovery and S4 tests at actual
   request, worker, apply, acquisition, consumption, and retirement hooks.
   `--durations=40` supplies test-level context only; it does not measure
   phases. Run a diagnostic Windows repetition with retained concurrency;
   report raw durations and sample count before any percentile. A deadline
   miss stops dependent fixes for causal classification, not automatic
   attribution to product code. Workflow and instrumentation changes get
   focused failure-path checks before dispatch; this slice has no product
   behavior edits.
4. **Review the model.** Every inventory row must have an existing
   completion hook, a concrete fixture/test observation change, or a
   justified proposed product publication with a named failing proof.
   An unobservable phase remains a blocker to its conversion. Independently
   review ownership, budgets, observer lifetime, native proof, and the
   evidence limitations before slice 2.

### Slice 2 — Make things deterministic

5. **Build the observation seam test-first.** Add `_completion.py` and its
   firing cases in `test_tui_determinism.py` under the contract above. Keep
   [DOM-10.3]'s shared polling helper unchanged. Prove early completion,
   stale identity, failure, expiry, and disposal before converting callers.
   Stop if the helper begins driving operations or requires a second loop.
6. **Elicit, then correct, one class at a time.** Use the matrix below.
   Existing fixes receive a narrow mutation proof in a scratch checkout;
   newly discovered defects receive a failing test before their fix.
   Record the exact causal assertion, mutant/fix hunk, platform, and result.
   An import failure or missing symbol after a historical revert is not a
   valid red. Keep production fixes and harness changes independently
   reviewable; run the closest neighboring tests after each slice.
7. **Convert observations and split budgets.** Follow the reviewed inventory
   using exact completion handles. Retain final state assertions and real
   dependencies. Verify setup-delay success and behavior-delay failure,
   independent host terminals/log directories/providers per foreground
   run, and observer/adapter retirement on success, error, cancellation,
   and timeout. Remove retired liveness helpers only after their callers
   are accounted for. Re-scan the inventory and record any remaining loop's
   purpose and owner; absence of a helper name alone is not completion.
8. **Review the implementation.** Review each meaningful class and the
   integrated diff, especially source-adapter ownership and the deliberate
   production suspension versus the headless test seam. Keep two workers
   and `loadfile`; no scheduler comparison is required for closure.

### Required Elicitation Matrix (executed in slice 2)

These are test obligations, not a declaration that every hypothesis is an
observed defect. Reuse an existing firing test when it already proves the row.

| Class / evidence | Forced ordering and observable assertion | Red mutation / platform |
|---|---|---|
| (a) Run ownership, E4 | Preserve the existing test keeping the confirmation thread alive while a different lease thread acts for the same run. Acquisition succeeds; a different run is excluded; release retires the scope. | Replace the scoped run authority with thread-derived authority at the same live seam. The legitimate later phase fails. Portable; never wait for identifier reuse. |
| (b) Headless loop blocking, E6(c) | Confirmation resolves before acquisition. Hold/release the real lease via the existing headless lease-body thread; the pilot can await acquisition, release, and restoration, and the test joins that thread. Native terminal proof retains production's intentional UI pause. | Restore delivery of the blocking headless lease body onto the pilot loop. Run this red case in a child test process with a parent watchdog and owned teardown so the verifier cannot hang. Before entering the blocking state, flush bounded phase records to a test-owned file; the parent reads them even after terminating the child. Portable harness proof. |
| (c) Attempt-counted liveness, E8 | Gate the real result/application order with a barrier while forcing the old observer's finite attempts to exhaust; then publish completion within the explicit behavior limit. The new observer still receives and verifies it. | Restore the old attempt-bound observer; require its specific early failure. Control yields at the test seam, not global time. This proves a harness defect class, not the historical S4 cause. Portable. |
| (d) Wrong deadline origin, E6(b) | Hold process/bootstrap setup before its ready event. After setup release, orientation/navigation completes within the unchanged behavior interval; separately withhold behavior completion after its start and require timeout. | Charge the behavior deadline from setup start, or reset it on progress. Controlled-clock helper tests and real-boundary integration barriers; portable. |
| (e) Mount/focus readiness, E6(d/e) | Delay the actual control mount/focus transition while the screen object already exists. The test input waits for that control's committed readiness, then reaches its real handler. Also close/supersede the screen before readiness and require cancellation with no late input. | Restore object-existence-only readiness; prove input occurs before the held readiness fence or misses the intended handler. Do not invent a product requirement to reject pre-mount worker results. Portable. |
| (f) Cross-run Windows I/O leakage, E6(a) | Wire one provider, leave a tagged reset/output tail pending at detach, await reader cancellation/retirement, then start the recovery run. Assert distinct retained host-terminal objects, log paths, provider creation identities, no old marker in run two, and successful run-two input/output. Do not assert fd/PID integers never recycle. | Reuse the first host-terminal session and require the isolation assertion to fail. Portable fixture-ownership proof; native Windows test must additionally exercise real cancelled I/O and assert the captured bytes/retirement evidence. A structural red alone does not prove the Windows mechanism. |
| (g) Superseded UI event, E5 | Queue a real old-generation selection/highlight event, establish the newer search ownership, then deliver the old event. Assert the exact hit/selection and viewport owner survive. Choose the current transcript adapter, preserving the participation-loop contracts. | Remove the active stale-event guard at that adapter. Portable. If later code eliminated the path, document that removal and its replacement firing proof rather than resurrecting obsolete widgets. |
| (h) ConPTY delivery hypothesis | On native Windows, hold provider readiness, release it, observe the fixture's consumption acknowledgement through the production adapter, then assert the existing log and final readiness. Exercise quiet child exit versus output EOF, detach/cancel, and complete adapter retirement without a second reader. | Existing native lifecycle tests may supply these cases. If a delivery defect is discovered, name and mutate its correction; otherwise record native qualification, no confirmed new cause. POSIX counterpart tests qualify only their own PTY path. |
| S4: source → callback → generation → widget | Keep real SQLite/session/app. Commit the DM before requesting its snapshot; hold worker return and owner application separately; retain source membership, future outcome, callback delivery, stale decision, and rendered DM. Exercise an older request returning after a newer request and verify the latest valid DM is applied. | Mutations at each boundary must produce distinct phase diagnostics and retain final-state assertions. Green candidate probes eliminate only the exercised schedules. A red synthetic mutant is not evidence that the historical incident used that schedule. |

### Slice 3 — Hosted qualification and honest closure

9. **Audit proof coverage.** Every confirmed class has its intended red and
   green on the relevant platform; helper outcomes and all inventory phases
   fire. Unknowns and platform limits are explicit. No native Windows result
   is inferred from a POSIX pass or a fake API test.
10. **Qualify one SHA.** Run `windows_repeat=5` under the acceptance contract.
    Record workflow/run attempt and each repetition's result. A failing
    repetition invalidates that qualification attempt. Fix, review, and run
    a new complete attempt; do not relabel a retry as uninterrupted evidence.
11. **Disposition S4.** Inheritance transfers diagnosis responsibility, not
    a passing verdict. Append the transfer/evidence to the predecessor and
    update its index note without marking it complete by inference. Close
    S4 only after a causal failing regression and correction, or after an
    explicit owner decision accepting the residual risk. In the latter
    case retain the exact words "cause unresolved; accepted by owner", the
    evidence, scope of the waived predecessor gate, and reopen condition.
    Until such evidence or decision exists, S4 and this plan remain open,
    even if the soak passes. Do not request a waiver before presenting the
    completed diagnostic and qualification evidence.
12. **Docs and closure.** Promote the verified determinism model into
    `docs/implementation/12-taut-tui.md`; align CHANGELOG, affected backlinks,
    the predecessor, and plan index. Record only reusable new lessons.
    Run completed-work review and the gates below; mark completed only when
    every outcome, including S4's explicit disposition, is satisfied and the
    implementation is committed under the repository's completion rule.

## Testing Plan

- Layer: real TUI, real Summon controller and provider, real host PTY;
  Textual `run_test` for app-level proofs; scratch copies for red runs that
  need production reverted.
- Files: `extensions/taut_tui/tests/test_tui_summon.py`,
  `test_tui_app.py`, and new `test_tui_determinism.py`/`_completion.py` in
  that directory; `.github/workflows/test-tui-extension.yml`; the existing
  provider fixture and native terminal helper only at identified seams.
- Do not replace real Textual dispatch, worker execution, the driver, broker,
  or PTY for integration proof. Wrap callbacks for observation and use
  barriers to order real operations. Pure helper tests may use retained
  futures and narrow clocks directly. Native tests retain platform markers.
- Mutate only the causal correction in a scratch checkout, keeping the
  current compatible APIs. Portable reds run on retained POSIX and Windows
  environments; native cancellation/ConPTY reds run on Windows. Retain
  subprocess cleanup even when the mutant deliberately deadlocks.
- Planning-only verification: before/after inspection against the six review
  findings and owner clarification, plus documentation gates. No runtime
  implementation or CI qualification is claimed by this plan revision.

## Verification and Gates

Run from the repository root after the new test module/input exists:

```bash
uv run --project extensions/taut_tui --extra dev --locked pytest extensions/taut_tui/tests/test_tui_determinism.py extensions/taut_tui/tests/test_tui_summon.py extensions/taut_tui/tests/test_tui_app.py -n 2 --dist loadfile
uv run --project extensions/taut_tui --extra dev --locked pytest extensions/taut_tui/tests -n 2 --dist loadfile
uv run --project extensions/taut_tui --extra dev --locked ruff check extensions/taut_tui/taut_tui extensions/taut_tui/tests
uv run --project extensions/taut_tui --extra dev --locked mypy extensions/taut_tui/taut_tui extensions/taut_tui/tests --config-file extensions/taut_tui/pyproject.toml
uv run bin/check-doc-paths
uv run bin/check-plan-status-index
uv run pytest tests/test_docs_references.py
git diff --check
```

After committing the implementation and making its ref available to Actions,
dispatch `gh workflow run test-tui-extension.yml --ref REF -f windows_repeat=5`
(replace `REF` with that ref). Verify the resulting run's `headSha` equals
the intended commit before counting it. Record run attempt and all five
repetition artifacts; command exit 0 proves dispatch only. Existing native
Summon tests must also run if their adapter/fixture code changes.

## Independent Review Loop

Reviewer: a different family from the author, for this revised plan, after
slice 1, at meaningful implementation slices, and at completion. Inputs:
this plan, [TAUT-8.5], [TUI-11.3], [DOM-10.3], the implementation note,
inventory/evidence, current app/Summon tests and terminal helper, and streak
commits. Ask: "Does each observation follow the exact real owner without a
second control loop? Could its test pass with the claimed fix removed? Does
any closure statement assert a cause the evidence cannot establish?"
Record every finding and disposition; prefer removing work without causal
value. None of [THEORY-5]'s rejected alternatives is being reconsidered.

## Out of Scope

- The tail-pin viewport extraction (TUI participation plan).
- Summon's own Windows ConPTY lifecycle (Windows PTY lifecycle plan,
  completed) except where a TUI test's oracle depends on it.
- Reducing the Windows matrix or growing any behavior deadline.
- Changing xdist distribution, creating a production event bus, or changing
  the repository-wide eventual-evidence helper/process contract.
- Treating synthetic candidate failures or a passing soak as the historical
  S4 root cause, or silently waiving the predecessor's release gate.

## Assumptions and Open Questions

1. The revision uses the proposed five-run acceptance sample, now defined
   as five repetitions within one fixed-SHA Windows job. It does not change
   product deadlines or claim a statistical reliability guarantee.
2. The user's requested inheritance puts S4's remaining work here. It does
   not authorize labeling S4 fixed or the predecessor completed. Any later
   acceptance of an unresolved cause requires the explicit disposition
   described in slice 3; no such decision is assumed in this revision.
3. Whether native ConPTY delivery or cross-run cancelled-I/O leakage caused
   a historical failure remains unknown. Slice 1 separates code-supported
   mechanisms from directly observed historical failures.

## Deviation Log

| Spec ref | Planned behavior | Actual behavior | Rationale | Spec proposal |
|----------|------------------|-----------------|-----------|---------------|

## Review Log

(append-only)

- 2026-09-24 — Implementability assessment accepted six corrections:
  preserve unresolved S4 causality; force distinct thread identities rather
  than reuse; respect deliberate production suspension; specify retained
  completion observation; cover omitted native I/O classes honestly; and
  make budget/soak semantics precise. The owner's clarification supersedes
  the assessment's overly broad objection to one event-based wait: every
  source feeds the existing reactor, with no separate domain control loop.
  Existing [TAUT-8.5] remains the architectural authority.
- 2026-09-24 — Independent revision review by Claude (`claude-opus-4-6`),
  read-only CLI 2.1.273 with safe/plan mode, matched Read/Grep/Glob tools,
  strict MCP configuration, no session persistence, and closed stdin.
  Invocation used `timeout 540 claude ... --output-format json`; completed
  in 188.156 s, exit 0, `success`, `is_error=false`, `end_turn`,
  `terminal_reason=completed`. Verdict: **no blocker**. The preceding
  120-second-bounded liveness/write-containment probe passed; no probe file
  was created. The skill's invocation and review guidance were evaluated;
  no correction to that guidance was needed.

### Independent review findings (verbatim)

| ID | Severity | Location | Finding | Suggested Disposition |
|----|----------|----------|---------|----------------------|
| F1 | P3 | Plan §Hidden couplings, ¶1 | The plan names `TerminalAttachNotice` as the message type Summon publishes to the TUI. The public type exists in `taut_summon` and is used by the existing distinct-phase-thread test (`test_tui_summon.py:587`). However, the TUI's `summon.py` accepts it through a private `_TerminalAttachNotice` structural protocol (line 58), not via a direct import of the public class. The plan's coupling note is accurate at the domain level; the implementer should be aware that the TUI decouples from the concrete class via a protocol, so fixture acknowledgement wiring must satisfy that protocol, not import the concrete Summon type into product TUI code. | No plan text change needed. Implementation note: the protocol boundary is already correct in the existing test; preserve it. |
| F2 | P3 | Plan §Elicitation Matrix, row (g) | Row (g) instructs: "Choose the current transcript adapter, preserving the participation-loop contracts." The stale-highlight guard is in `app.py` line 780, gated on `self.visual_state.viewport.search_owned`. The plan references E5's `OptionList` fix. Since the participation-loop plan (`e05c813`) changed viewport ownership, the implementer must verify that `search_owned` is still the correct predicate controlling the guard and that `viewport.py`'s current adapter didn't relocate the stale-event path. Current code confirms `search_owned` is still checked at `app.py:780`. | No plan change needed; this is an implementation verification the plan's matrix row (g) already implies. Record the confirmed guard location. |
| F3 | P3 | Plan §Budget and Hosted Acceptance Contract, ¶3 | The formula `15 + 20 * N` yields 115 minutes for N=5 and 35 for N=1, correctly matching the current Windows `job-timeout-minutes: 35`. The plan says "A single unchanged 20-minute step cap cannot contain five full repetitions" — this is accurate since the current `test-timeout-minutes: 20` is the per-step cap. However, the plan does not specify whether the 20-minute per-repetition cap is enforced as a step-level `timeout-minutes` on each iteration inside the loop, or as a process-level `--timeout` to pytest, or both. A process-level pytest timeout alone would not prevent a hung GitHub Actions step from consuming the whole job budget silently. | Author should specify: each repetition runs as a step (or script block) with its own `timeout-minutes` equivalent, not only a pytest-internal timeout. The existing step-level `test-timeout-minutes` mechanism should be preserved per iteration. |
| F4 | P2 | Plan §Completion Observation Contract, item 1 | Item 1 states: "For an existing operation, use its retained result or an atomic observe/register seam; a non-atomic check-then-subscribe sequence is forbidden." The S4 DM navigation test (`test_tui_app.py:2190–2213`) already demonstrates the pattern: it registers an `asyncio.Event` observer via a subclass override of `_apply_navigation_result` *before* `run_test` triggers the navigation. The completion contract must be compatible with this proven pattern. The plan's contract item 1 is correct and the existing test is a valid worked example — but the contract does not explicitly state that subclass callback wrapping (the existing pattern) is an acceptable "atomic observe/register seam." If the new `_completion.py` helper requires a different registration mechanism, it risks invalidating the proven test structure. | The plan should note that subclass callback observation (as in the existing DM navigation test) is a conforming implementation of the atomic registration requirement. The new helper should accept this pattern rather than requiring a replacement mechanism. |
| F5 | P3 | Plan §Elicitation Matrix, row (b) | Row (b) specifies: "Run this red case in a child test process with a parent watchdog, retained phase evidence, and owned teardown so the verifier cannot hang." This is prudent for a test that deliberately deadlocks the pilot loop. However, the plan doesn't specify how phase evidence is communicated from the child process to the parent. Stdout/stderr capture, a temp file, or a pipe would all work, but the choice affects whether the evidence survives a child timeout kill. | Implementation detail; author may leave this to slice 2 design. Suggest noting that the child must write phase evidence to a durable medium (file) before entering the blocking state, so the parent watchdog can read it after kill. |
| F6 | P3 | Plan §Slice 1, step 3 | Step 3 says: "Add the bounded dispatch input and result capture described above." This refers to the `windows_repeat` workflow_dispatch input. Adding a workflow input is a non-reversible CI change (it changes the workflow file's API). The plan correctly places this in slice 1 (diagnosis), which otherwise has "no product behavior edits." The workflow change is not a product edit, but the plan's framing of slice 1 as "diagnosis only, no product edits" could mislead an implementer into thinking no file changes land. The plan does say "Workflow and instrumentation changes get focused failure-path checks before dispatch" which partially addresses this. | No plan change needed; the distinction between product edits and workflow/instrumentation changes is already drawn in the slice 1 text. |

### Dispositions

| ID | Disposition and verification |
|---|---|
| F1 | No change required. Verified the structural protocol in `summon.py`; keep the existing lazy extension boundary. Fixture output observation is not a new attach-notice import. |
| F2 | No change required. Verified `on_option_list_option_highlighted` checks `viewport.search_owned` at the reviewed baseline. Row (g) already requires rechecking the live adapter before mutation. |
| F3 | Accepted. Five conditional Actions invocation steps each retain their own 20-minute outer cap; later repetitions require prior success, and artifact collection runs with `always()`. This bounds a hung pytest process as well as its tests. |
| F4 | Accepted clarification. Item 1 explicitly accepts the existing before-trigger subclass observer, while distinguishing that from attaching an observer to an already-running operation. |
| F5 | Accepted. The child flushes bounded phase evidence to a test-owned file before the deliberately blocking state; the parent can inspect it after termination. |
| F6 | No change required to the already explicit slice boundary. Reject the description of a workflow-input addition as non-reversible: it is a reversible workflow-file edit, with no publication or storage migration. |

### Slice-1 model review attempt

2026-09-25: Claude 2.1.273, unchanged verified safe/plan Read/Grep/Glob
invocation with closed stdin, strict MCP, no session persistence and a
540-second bound, exited 124 with no stdout/stderr or verdict. This is a
reviewer timeout, not approval or a product finding. Invocation artifacts
remain under `/tmp/taut-tui-model-review.xI77ut`; an independent fallback
must supply the model gate. No wait migration started on this attempt.

Grok 1.0.41's fresh read-only liveness/write-containment probes both failed
closed before launch because its sandbox could not resolve the Docker socket
symlink. No bypass was attempted. A fresh same-family separate-role reviewer
was dispatched under the documented fallback; that family limitation is
explicit, not represented as a different-family review.

### Slice-1 CI diagnostic review

Independent same-family reviewer, separate from the workflow/recorder author,
returned the following findings verbatim. Initial verdict: blocker for
diagnostic push, scoped to CI-R1/CI-R2. Native Actions/PowerShell execution
remains a named qualification limit, not a reason to weaken local checks.

| ID | Severity | Location | Finding | Suggested disposition |
|---|---|---|---|---|
| CI-R1 | P2 | `bin/record_tui_run.py:119`, `_required_phases` / `_completed_owners` | Required evidence is reduced to sets of successful phases. This accepts duplicate terminal records and impossible causal timestamps while the summary claims success. Direct probes accepted navigation source at 0.8 s followed by application at 0.2 s for the same request, and lease acquisition at 0.8 s followed by restoration at 0.2 s for the same lease. | Reject duplicate required terminal outcomes and contradictory timestamps at orderable owner boundaries; add firing malformed-evidence tests. Compare captured transition times, not JSON write order. Do not require injection-return before consumption. Preserve legitimate background error records. |
| CI-R2 | P2 | `bin/record_tui_run.py`, `run_repetition` artifact writing | Raw JUnit failure/output/property text enters the uploaded artifact tree. Command arguments are also copied into start/final records, exposing inline source content in the adversarial fixture. The author's newly added privacy tests independently demonstrated both leaks. | Keep raw JUnit outside the upload tree even on interruption; upload a structural summary without failure/output/property text. Record only necessary command metadata. Author is already correcting this. |

Both findings accepted; the scoped correction history follows. Reviewer observed
the new privacy tests fail and independently reproduced CI-R1 with malformed
phase records. Root inspection also required same-identity lease/provider
joins and actual pytest-runtime consistency across repetitions; the author
recorded four semantic reds then greens for these corrections.

Scoped re-review: CI-R2 passed after raw XML moved to an OS temp directory
outside the artifact tree, uploaded XML was structurally sanitized, and argv
was removed from metadata. CI-R1's first correction still accepted conflicting
error/success outcomes on one required identity and omitted confirmation from
the edge-derived phase set. Those remaining cases were reproduced, corrected,
and independently checked: final CI-R1 PASS, 85 recorder/workflow tests passed,
50 additional conflict probes rejected, and the real full-suite artifact set
verified. Unrelated background errors remain valid diagnostics. The writer's
matching tripwire logic gained 42 observed reds and now passes all 65 focused
phase-evidence cases. No native result is inferred from this local review.

### Slice-1 instrumentation review attempt

2026-09-25: a separate scoped Claude review used the saved exact prompt at
`/tmp/taut-tui-phase-review.ikDywR/prompt.txt`, the same read-only containment,
and streamed output. It exited 124 at the 540-second bound with empty stderr.
The stream retained 6,314 events and 36 assistant messages but no terminal
result. This establishes activity, not approval; a fresh separate-role
fallback review was dispatched. No permission or global CLI configuration was
changed. The earlier model review and separate CI review remain distinct.

Fresh separate-role fallback verdict (verbatim): **no blocker**. Finding
table: "None | — | `_phase_evidence.py`, conftest wiring, focused tests | No
verified defect within this review’s boundary. | Accept this diagnostic
slice’s review gate." The reviewer independently checked real callback
delegation, navigation identity, pre-wake timestamps, confirmation callback
preservation, the live platform output paths, disposal/patch lifetime,
retirement and bounded content-free recording; all 65 focused cases passed.
Accepted for the instrumentation gate only. Native validation, wait migration
and S4 closure remain separate. Same-family fallback is explicitly disclosed.

Scoped search-observer correction review: **no blocker**, no actionable
P1–P3 findings. Finding (verbatim): "The observer identifies the accepted
search-owned transition, while retaining the exact `[message_ts]` assertion
and existing final-state checks." Suggested disposition: "Accept the scoped
correction." Accepted after the independent reviewer ran both the original
handler case and forced-order regression: 2 passed. The reviewer verified
both follow-up callbacks finish inside the observation scope and real app
teardown remains intact. This is no claim about S4 or the exact callback
classes present in the original hosted logs.

### Native measurement and conversion-cap review

Independent reviewer recomputed every raw same-owner duration in the evidence
artifact and independently validated all 575 native phase files. The recorded
failing run remains failing qualification. Initial verdict: blocker CAP-1.

| ID | Severity | Location | Finding (verbatim) | Suggested disposition |
|---|---|---|---|---|
| CAP-1 | P2 | Evidence artifact, conversion-cap table | “Keep an existing smaller explicit cap” can replace larger explicit app limits with 5 s, conflicting with the reviewed requirement to preserve existing limits. “30 s orientation” also conflates wiring’s 30 s `_wait_until` with post-recovery orientation’s existing 45 s `_await_until`. The inventory-precedence sentence currently appears only in the infrastructure row. | Make exact existing call-site caps authoritative across the whole table. Apply the new 5 s/2 s defaults only to formerly counted waits. Explicitly distinguish wiring orientation 30 s from recovery orientation 45 s. |

Accepted and corrected: every explicit call-site cap wins globally, neither
grows nor shrinks; 5 s/2 s apply only to formerly counted waits. Wiring and
recovery orientation retain 30 s and 45 s respectively. Scoped re-review:
**PASS**, CAP-1 resolved with no new defect. The reviewer confirmed global
existing-cap precedence, counted-wait-only defaults, and the two distinct
orientation limits. Completion-helper implementation and wait migration
started only after this model/cap gate passed.

### Completion foundation review

Separate-role review inspected the full completion and Textual lifecycle
adapters and their tests against the model, M1 and M3. Initial finding:

| ID | Severity | Location | Finding (verbatim) | Suggested disposition |
|---|---|---|---|---|
| OBS-R1 | P2 | `_screen_completion.py`, `ScreenCompletions._on_message` | Looking up the screen lifecycle only after awaiting real message dispatch can attribute an old in-flight `DescendantFocus` to a newer push of the same installed screen. Holding generation 1’s handler, popping and repushing as generation 2, then releasing only generation 1 completed generation 2’s focus handle with exactly one handler having run. | Capture the exact lifecycle before delegation, and publish afterward only if that same lifecycle is still current and not popped. Add a held-old-focus/reused-screen firing test. |

Accepted and fixed. The reviewer added the real held-handler/reused-screen
regression. A process-local mutation restoring post-dispatch lookup failed
the new generation's pending assertion; the corrected code passes. Final
verdict: **PASS, no residual blocker**. The reviewer independently ran all
82 helper/lifecycle cases plus scoped Ruff, four-file mypy and whitespace
checks. No second loop or cancellation of shared producer work was found.
This review gate covers the foundation, not later caller migrations or S4.

### Action-caller migration review

The main agent independently inspected the delegated action adapter and
handler/route diffs. Finding ACT-R1 (P2): the focus observer published again
for later legitimate focus events while still installed, including after
retained readiness had already succeeded. The completion interface correctly
reported duplicate publication, but the adapter had mistaken a repeatable
source for a once-only producer. Disposition: publish the first matching
committed focus transition once. Both fresh-focus and retained-readiness
cases failed before and passed after the adapter correction; the underlying
duplicate-outcome tripwire is unchanged.

The implementation also added causal held-apply and real synchronous-refusal
proofs: worker completion cannot claim application, and a caught/rendered
producer refusal retains its original exception instead of turning into a
missing-request timeout. Main re-verification of handlers, routes, viewport
and screen neighbors: **135 passed** at `-n 2 --dist loadfile`. Scoped Ruff,
mypy and whitespace gates pass. No blocker remains in this migration slice.

### Summon-caller migration review

Main review found and corrected three observer defects before accepting the
delegated slice: SUM-OBS-1, ready/return could accept an unrelated run or
future; SUM-OBS-2, the separate readiness window was accidentally charged
from the earlier detach boundary; SUM-OBS-3, a source error after confirmed
provider consumption could overwrite/duplicate that consumption outcome.
Exact start request/token/future binding now rejects unrelated callbacks,
including readiness arriving before `start` returns. The first exact ready
handoff is retained without resetting on later progress. The original
post-consumption readiness window stays distinct. Consumption success remains
immutable and a later injection error still propagates through the real
driver and successful observer-context exit.

Forced old-token/wrong-future, early-ready, consumed-then-error, and competing
real confirmation resolution cases pass. M2's actual production callback is
retained and fires once across competing resolve/resolve/fail threads. Main
ran seven focused cases and inspected the source and budget changes. The
preceding 56-case instrumented module run passed at two workers/loadfile;
the one additional M2 case passed afterward. Scoped Ruff/mypy pass. Native
Windows revalidation remains separate from this portable review acceptance.

## Execution Log

- 2026-09-25 — Integrated review found two false-green evidence gaps.
  INT-CI-1: three passing JUnit cases with only two phase files passed both
  capture and verification. Both now require exactly `tests - skipped`
  records under the current mark-only-skip fixture contract, retaining
  available diagnostics and the actual child exit code on failure.
  INT-CI-2: the reader accepted recorded Windows recovery without successful
  `attach.retired`, although the writer required it. Reader validation now
  uses the recorded runtime, not the verifier's host OS. Eight firing reds
  precede the fixes; 71 recorder cases pass, and independent recorder/workflow
  review passes 99 cases (6.39 s). Balanced samples keep the separate
  cross-repetition count-identity guard independently firing. Diagnostic-4
  artifacts still validate as expected: four green lanes, known-red Windows.

- 2026-09-25 — Native-probe generation correction is causal over the real
  recovery driver: the first detached provider is retired before the second
  is spawned; orientation consumption belongs to that exact second handle.
  Reintroducing the one-provider cap raises the original public
  `SummonOperationError` → `DriverError` → `AssertionError`, not an attach
  timeout. Early driver error/cancellation/return are now retained by the
  attach observer. Failure cleanup requests public STOP before closing all
  captured handles and checked joins; regressions cover failure after real
  recovery and a first close failure without skipping the second provider.
  Main retained-lock run: nine portable passed, three native-only skipped
  (60.41 s). Independent combined native/selection review: 21 passed, three
  native skips, exactly 21 complete phase files (60.69 s); Ruff/mypy passed.
  Native cancellation/995 remains unqualified until hosted execution.

- 2026-09-25 — The implementation note now contains the complete owner /
  publication / observation model, including generic worker actions,
  navigation, watcher initial drain, conversation, viewport/search/resize,
  presentation/focus, confirmation, lease, orientation and retirement.
  Independent review corrected the distinction between installing an
  observer before action and binding a Future created by submission, then
  passed the model and budget table. The diagnostic tests' two remaining
  broad pauses now await exact navigation and callback-return completions;
  all 65 diagnostic cases pass, independently repeated (0.81 s), with
  Ruff/mypy clean. This is observation-only migration using the already
  red/green-tested completion interface and unchanged semantic assertions,
  not a newly claimed product fix. Selection/native negative-proof sweep
  remains open before qualification.

- 2026-09-25 — Diagnostic 4 at `e91a435` was red: Windows 686 passed,
  three failed; all four other lanes passed 686 with three native skips.
  Every phase file validates. The first native provider now completes, but
  recovery exposed the probe's false one-provider-per-run assumption; a
  real two-spawn test fires that assertion. Generation-aware observation is
  being corrected and does not change the driver. Separately, real Ctrl-C
  input and exit zero lacked a transient terminal marker. The probe now
  retains closed per-child receipts from the exact decoded-binding and
  guarded-dispatch hooks, read once after real child retirement. Suppressed
  terminal-marker execution passes; removing either receipt is rejected.
  Independent review passed all 19 textual-contract cases (6.25 s), Ruff
  and mypy. This proves the observation correction, not the historical
  native transport cause. Caps, real PTY delivery and quit assertions remain.

- 2026-09-25 — Final app/chat/screen migration review passed after three
  observer corrections: presentation deadlines start at the named producer;
  watcher readiness is timestamped at actual initial-drain publication under
  its separate five-second budget; notification restore requires its exact
  effect and pre-dispatch authority. No extra controller or product loop was
  introduced. Independent review ran 198 neighbors and eight final targeted
  cases. The later rapid-resize failure is now causal: held real initial
  highlight messages overwrite the test's private direct selection before
  resize. Shared setup now uses real widget activation and its exact handler
  completion, then restores the intended tail geometry. Reinstating direct
  selection fires the exact seed-5 versus last-seed assertion. All 150 app
  cases pass (43.42 s), and independent three-case review passes (2.36 s).
  Original resize sizes, real worker/live delivery, selection, inspector,
  draft, tail and latest-size assertions remain. This is a harness ordering
  correction, not a demonstrated product resize defect or S4 cause.

- 2026-09-25 — First full instrumented local integration ran 703 cases:
  698 passed, two failed, three native skips (95.53 s). Complete log and
  phase files: `/tmp/taut-tui-integrated-local.jft0Ia`. The resize failure
  retained a last-seed selection replacing the intended seed-5 selection;
  diagnosis is continuing with held real highlight events, not green retries.
  The other failure is now causal: the launch help test directly evicted
  `taut_tui.app` from `sys.modules`, so the later chat fixture patched a
  different class from the test's local import. The exact ordered pair
  reproduced the missing-observer `AttributeError`. All three lazy-import
  probes now use scoped `monkeypatch.delitem`, restoring exact module
  identities. The ordered pair passes, as do all 46 launch/chat cases.
  A new loaded-module restoration regression and independent three-case
  ordered review pass. No launch behavior or product runtime changes.

- 2026-09-25 — Diagnostic 3 at `d2ffea5` completed: Windows 682 passed,
  one native isolation probe failed before chat-prompt observation; all four
  non-Windows lanes passed 681 with the two declared native-only skips.
  Quiet native exit passed. Every phase file validates, but the full Windows
  result correctly remains red. The prompt observer required unstable
  trailing padding; a portable split-token regression fired before matching
  the established `chat>` token. Independent review found no blocker.
  This is a candidate hosted-failure explanation, not a confirmed native
  product cause. Diagnostic 4 (run 36150401173, one repetition at `e91a435`)
  tests that correction and the real reused-host mutant. It is not the soak.

- 2026-09-25 — Main integration audit found that a per-test scope released
  history on teardown but had no fixed admission bound while repeatable
  focus/highlight events were observed. A 4096-record overflow regression
  fired `DID NOT RAISE` before the correction. Scope admission now fails
  closed under its existing lock, preserves earlier outcomes and leaves the
  producer untouched; teardown clears records but retains the violation.
  Independent review passed and independently ran all 84 foundation/screen
  cases. Main Ruff/mypy pass. This enforces the existing bounded-history
  invariant; no domain scheduler or deadline changed.

- 2026-09-25 — Added the real SQLite ordering probes: older navigation work
  stays serialized; reordered real UI callbacks both retain a DM committed
  before their source reads; older real search results cannot replace the
  newest DM result. Parallel-worker and removed-search-guard scratch mutants
  each fired semantic assertions. Main review moved initial NAV deadlines
  from app construction to the actual refresh submission. Three probes pass
  with scoped Ruff/mypy. Native isolation also gains the explicit reused-host
  mutant, independently reviewed with no P1–P3 finding. Local native cases
  skip honestly; the new mutant still requires Windows execution. Details
  and limitations are in the elicitation-results artifact.

- 2026-09-25 — Integration found SCREEN-R2: the result observer invoked a
  bound built-in differently from Textual's real `ResultCallback.call_next`
  path. Eight/nine screen neighbors exposed `list.append` parameter inspection
  errors. A new real-framework test fired the same `AttributeError` before
  the correction, then passed with `invoke(partial(callback, value))`.
  Main verification: all 11 screen lifecycle cases pass, with scoped Ruff and
  mypy clean. The source callback, its exception, result application and
  independent removal completion remain distinct. This is a test-adapter
  integration correction, not a product or S4 cause.

(append-only)

- 2026-09-24 — Plan opened on owner direction after the 0.9.9 Windows
  streak; evidence register E1–E10 assembled from CI runs and commits.
- 2026-09-24 — The participation-loop implementation replaced
  `test_tui_app.py`'s fixed-attempt `_pause_until` implementation with an
  elapsed event-loop deadline. Existing call sites retain the helper alias
  while the real rapid-resize test calls the deadline owner directly. This
  removes attempt-count timing from the tests touched by that plan; it does not
  close this plan's S4 elicitation and Windows soak gates.
- 2026-09-24 — Plan revision inspected against baseline `33205d7`, the
  governing core/TUI/helper contracts, current recovery and navigation
  tests, and the `583038e` ownership correction. E8/E10 were refreshed,
  completion/budget/soak contracts added, all elicitation classes mapped,
  and S4's causal gate retained. This is planning evidence only; historical
  CI logs and native qualification are slice-1/slice-3 work.
- 2026-09-24 — Revised-plan verification: `uv run bin/check-doc-paths`
  passed (63 sources, 1512 path claims); `uv run bin/check-plan-status-index`
  passed; `uv run pytest tests/test_docs_references.py` passed all 15 tests;
  `git diff --check` passed. Independent review found no blocker; F3–F5's
  clarifications were applied and checked against the existing workflow,
  pre-registered navigation observer, and child-watchdog proof boundary.
- 2026-09-25 — Slice 1 retrieved the historical logs and remote tag targets.
  E1–E3/E6/E9 corrected against retained evidence; the detailed audit records
  each run, failed assertion, matrix count, and evidence limit. Historical
  runs have no uploaded phase artifacts. Initial local firing checks of
  distinct-thread ownership and real initial-DM navigation: 2 passed in
  0.43 s. This is baseline preservation, not a new causal or Windows proof.
- 2026-09-25 — Current wait inventory: 8 helpers with 123 callers, 35
  inline counted wait/drain loops, 4 other elapsed polling loops, and one
  lease/stop polling loop. It separately enumerates 201 AST pilot pauses,
  embedded child delays, finite actions, and retained source waits. The
  old E8 counts are historical only. Concrete source seams are recorded in
  a separate artifact; unresolved row choices are not silently converted.
- 2026-09-25 — Baseline retained suite before instrumentation/migration:
  `uv run --project extensions/taut_tui --extra dev --locked pytest
  extensions/taut_tui/tests -n 2 --dist loadfile --durations=15` passed
  510 tests in 96.18 s on macOS/Python 3.14.4. Recovery offer/decline/host
  shutdown tests took 22.14/30.02/14.94 s respectively. These are whole-test
  durations, not phase budgets or native Windows measurements.
- 2026-09-25 — Slice-1 diagnostic implementation is test/workflow-only.
  Real smoke testing corrected two observation defects: the proposed POSIX
  handle hook was dormant, and separate patch stacks could restore a disposed
  observer after test teardown. The live terminal-state callback and one
  shared pytest patch stack now have firing proofs. Marker-bound consumed
  input, true navigation request entry, retained source/apply identity,
  pre-wake transition timing, and source-owned retirement are recorded.
- 2026-09-25 — The full opt-in recorder passed 524 tests in 96.64 s, then
  575 tests in 95.96 s after additional terminal-conflict cases. The current
  reader verifies the real artifact sets. The final set is retained locally
  at `/tmp/taut-tui-diagnostic-final.lHiEKw`; this working-tree run is local
  proof, not immutable-SHA Windows qualification. Focused recorder/workflow
  tests: 85 passed. Focused phase tests: 65 passed. Documentation tests: 15
  passed. TUI Ruff and all 41-file mypy checks pass after the repair below.
- 2026-09-25 — Incidental Class-1 gate repair committed separately as
  `c1888cd`: unchanged baseline `domain.py:131` promised `Future[Message]`
  while the published core join already returns `Message | None`. Mypy
  reproduced two errors with no production source diff, then passed after
  aligning only the annotation. Real SQLite first-join/rejoin assertions and
  all 9 domain tests pass; runtime behavior and product contracts are unchanged.
  Static red/green is the substitute proof for this annotation-only correction.
- 2026-09-25 — Debugging/TDD guidance exposed real-boundary observation and
  patch-lifetime defects and needed no policy change. The review invocation
  skill's bounded-failure/fallback rules were followed. A contained Claude
  probe passed in 4.583 s; the earlier 540-second review timeout has no proven
  underlying cause. Streamed progress plus saved exact prompts is the proposed
  invocation improvement, with no permission expansion or blind retry.
- 2026-09-25 — Diagnostic checkpoint gates re-run: the final 575-test local
  artifact set passes `record_tui_run.py --verify`; documentation path and
  plan-index checks pass; all 15 documentation tests pass; focused formatter,
  Ruff and whitespace checks pass. This checkpoint supports a one-repetition
  native diagnostic dispatch only. Wait migration, phase-cap approval, causal
  elicitation and the five-run qualification remain pending.
- 2026-09-25 — Diagnostic checkpoint `5b30d80` was pushed to
  `codex/windows-tui-determinism` and dispatched with `windows_repeat=1` as
  run `36143982762`, attempt 1. Its head SHA was verified. Windows failed
  before execution: 514 collected items plus two collection errors produced
  516 errors because the shared terminal helper imported POSIX-only `fcntl`
  unconditionally. The artifact uploaded and the verifier correctly rejected
  it; this run supplies no Windows phase timing or S4 evidence. History pins
  that defect to baseline ancestor `a1a35f09`, not the observer delta.
  Correction `3f0c411` lazily imports `fcntl`, `pty`, and `termios` only at real
  POSIX operations. Three fresh-process unavailable-module cases failed before
  and passed after; two real POSIX ownership/cleanup and four real TUI PTY
  neighbors passed. Native revalidation remains pending.
- 2026-09-25 — The same diagnostic run passed all 575 tests on Ubuntu 3.13.
  Ubuntu 3.11/3.14 and macOS 3.13 each failed the existing search-handler
  observer's exact `[message_ts]` assertion with three copies of the same
  timestamp. The observer tests only post-restore state, so later history or
  rejected stale effects can be counted as another search transition. A
  bounded causal probe is in progress; neither broadening the assertion nor
  changing product behavior is justified by these counts alone.
- 2026-09-25 — Search-observer diagnosis completed with a causal red: after
  the real search restore, force one accepted HISTORY restore to the same
  hit, then replay the stale search effect. The old observer deterministically
  records `[ts, ts, ts]`; its exact `[ts]` assertion fails. Pre-call search
  ownership, matching intent/hit and accepted effect generation distinguish
  the real transition; after adding those checks, both this regression and
  the original handler case pass without weakening final assertions. All 52
  instrumented action-handler/viewport cases pass at `-n 2 --dist loadfile`;
  scoped Ruff/mypy/whitespace checks pass. Only the test oracle changes.
  Historical logs do not show which of these extra callback classes fired.
- 2026-09-25 — The import-only correction was dispatched separately as run
  `36144544513`, attempt 1, `windows_repeat=1`; verified head SHA
  `3f0c4116764a904639d432ec971a2d53360b4067`. This diagnostic may still hit
  the now-proven search oracle defect, which is not in that immutable SHA.
  It is not a qualification attempt or a retry counted as a passing streak.
- 2026-09-25 — The second diagnostic completed with 574 passed, one known
  search-oracle failure, zero skips on Windows in 329.223 s. The import defect
  is absent. All 575 native phase files pass direct validation, including
  source/application, both provider-consumption identities, restoration and
  native attach retirement. Raw phase durations and their one-sample limits
  are in the evidence artifact; S4 source/application took 0.099777/0.002856 s.
  Other matrix jobs failed only the same already-corrected search oracle.
  No deadline miss was observed in this run. This remains a red diagnostic,
  not an acceptance run or causal S4 resolution.
- 2026-09-25 — Full local retained suite after `53ea080`: 576 passed in
  97.57 s. Full TUI Ruff and 41-file mypy gates pass. The one additional case
  is the forced search-observer ordering regression; no tests were removed.
- 2026-09-25 — Slice 1 model/cap re-review passed after CAP-1. Slice 2
  started with the TUI-local retained completion interface. Seventy-two
  foundation cases pass on Python 3.14 and isolated Python 3.11; the main
  agent independently inspected identity, publication/deadline ordering,
  observer disposal, callback lifetime and lock boundaries, then ran the
  foundation and real Textual lifecycle probes together: 81 passed at
  `-n 2 --dist loadfile`. Independent whole-foundation review is in progress.
- 2026-09-25 — Textual mount/result/removal probes hold actual framework
  transitions. In scratch copies, publishing mount at object creation fails
  the held-mount pending assertion; publishing retirement at result delivery
  fails the held-removal pending assertion. Nine green real-framework cases
  include actual input after mount/focus, observer timeout/cancellation
  without source cancellation, pop-before-ready, repeated lifecycle,
  callback failure, and detached focus during teardown. These are causal
  harness proofs for (e)/M3, not native ConPTY or historical S4 evidence.
- 2026-09-25 — Foundation and aligned implementation/lesson notes committed
  as `b194381`; `git log` verified the targeted commit. Action handlers and
  routes now use exact named producer/application, modal lifecycle and focus
  observations. All 33 handler and five route counted-wait callers and both
  polling helpers are removed. Three finite framework fences remain with
  inline rationale: post-search geometry, an already-issued exit event, and
  route fixture layout before input. No test assertions or supported routes
  were removed. New five-second caps apply only to former counted waits;
  existing explicit limits are unchanged. Main review ACT-R1 is resolved.
- 2026-09-25 — Action migration committed as `aef5758`, verified in `git log`.
  Portable elicitation checkpoint is recorded in
  `docs/plans/artifacts/2026-09-25-tui-elicitation-results.md`: actual live
  owner mutation (a), contained headless deadlock (b), counted observer (c),
  split-budget origin/reset (d), framework readiness (e), queued stale UI
  event (g), and distinct S4 source/apply/widget diagnostic mutations. Seven
  new app/lease probes pass; independent review and scoped lint/types pass.
  Native (f)/(h), remaining generation diagnosis and hosted qualification
  are still open. No synthetic mutation is presented as S4's historical cause.
- 2026-09-25 — Portable elicitation checkpoint committed as `2f341fe`, verified
  by `git log`. Summon conversion removes all 21 old helper callers, 14
  counted/drain loops, four elapsed polling loops and the answerer poll.
  Exact confirmation, modal lifecycle, run outcome and provider-consumption
  sources replace them; the headless answerer has one state-before-wake
  acquisition/stop signal. No `pilot.pause`, `time.sleep` or liveness sampling
  remains in that module. Native reads/joins and explicit 2/10/30/45/90-second
  caps stay intact. All drivers retire before successful consumption-observer
  scope exit. Review findings SUM-OBS-1/2/3 are resolved.

## Fresh-Eyes Review

The model must identify an implementable completion seam for every phase,
without manufacturing a second scheduler or mistaking a wake for completion.
The proof matrix separates existing fixes, synthetic hypotheses, and native
platform evidence. Review must reject timeout-based blame, import-only reds,
and a green soak used to invent S4's cause. Missing observation is first a
test/fixture design question, not automatic authority to add product machinery.

## Slice 1 Execution: Determinism Model (draft for review)

Implementation start: `33205d797814da07071bbe27d2336a057e233b8c`.
The existing uncommitted delta was the reviewed plan and reviewer inventory;
no intervening product edits required reconciliation. The owner authorized
implementation on 2026-09-25. The debugging and TDD skills govern causal
proof and vertical red/green slices; the call-agent skill governs independent
review invocation. No product change is justified merely by a timeout.

Comprehension answers: (1) distinct live confirmation/lease thread identities
expose the old token defect; reuse hides it; (2) object creation precedes
mount and focus, so input waits for the actual control's mount plus required
committed focus; (3) setup, behavior, and cleanup are different budget owners,
with behavior charged from its real triggering action, not a later await;
(4) every observation uses the existing reactor. Production suspension stays
blocking; only the existing headless lease-body seam runs on a test thread.

### Model boundary and proposed test interface

The existing Textual loop remains the only scheduler for UI work. The
serialized session worker and native PTY/lease threads retain their own
owners. A test completion is an observation of an owner transition, not a
command queue or a second domain controller. Its key is `(owner object,
request object or generation, phase)`. A test scope retains immutable
success, error, cancellation, or supersession, stores it before wake, and
wakes its asyncio waiter through `call_soon_threadsafe` when needed.

`Completion` is the common awaitable record. Test-owned callback adapters
are installed before the action (or before `run_test` for startup); they
delegate to the original method and then publish its outcome. Existing
retained futures attach through `add_done_callback`, which also handles
already-completed futures. A future's result and the UI application's
outcome are separate records. No generic message hook repeatedly evaluates
arbitrary domain predicates. Observer teardown disables/removes wrappers;
late callbacks do nothing. An observer timeout never cancels its producer.
Synchronous tests may block on the same record's condition with an absolute
monotonic deadline; asynchronous tests register a loop-local waiter and yield.
Neither form periodically rechecks domain state. The synchronous form must
never run on the Textual loop. Native reads and source-owned joins retain
their stronger resource semantics rather than being moved onto that loop.

Each wait accepts an absolute loop-monotonic deadline. It awaits one
helper-owned wake with that remaining budget and checks retained completion
once at expiry. Its completion timestamp must be at or before the deadline
in the same clock domain. Paired tests cover on-time publication with delayed
wake and late publication before the timeout callback is serviced.
Intermediate events cannot restart the clock. The helper's
pure arithmetic tests may inject a narrow clock; integration tests use
barriers on real callbacks. A test-local bounded phase recorder stores only
opaque request ordinals, generation numbers, phase names, outcomes, and
relative monotonic times. It contains no message/provider content or tokens.
Diagnostic recording itself never schedules or advances domain work.

### Owners and completion fences

| Phase | Owner and retained identity | Completing event / test seam |
|---|---|---|
| Navigation source / worker | Serialized `TuiSession`, exact refresh `Future` | After real snapshot future completion, retain source membership and error; this does not prove UI application. |
| Navigation applied (S4) | Textual app, same future | Preinstalled `_apply_navigation_result` wrapper calls real method, then captures rendered targets. Navigation snapshots have **no generation field or existing stale-generation guard**. |
| Conversation / live delivery | Session intent and generation, Textual owner | After real `_apply_conversation` or `_apply_delivery`, retain acceptance and exact intent/generation. |
| Transcript rows | Textual and viewport owner, conversation/viewport effect | After real `_render_messages` for rows; after `_apply_viewport_effect` for restore; after `_reapply_tail_effect` for final measured tail pin. |
| Search results / jump | Search screen generation and app intent | After `_apply_results`; jump finishes at accepted restore effect, not `_apply_search_context` worker return. |
| Resize | Textual, resize generation plus viewport generation | After current `_render_latest_resize` and required viewport effect. Stale generation is superseded; hidden/too-small results are recorded as such. |
| Mounted controls | Textual screen and children, exact screen object | Retain real `push_screen` `AwaitMount` before trigger; reject closed/superseded screens. Framework message hooks run before handlers and are not completion. |
| Committed focus | Textual screen/widget | After real descendant-focus handler, bound to intended widget and still-active screen. `.focus()` alone is not a fence. |
| Recovery offer / confirmation | Exact confirmation request, Textual | Delegate through real `resolve`/`fail`. Never replace the single `set_on_resolved` slot already owned by stale-modal cleanup. |
| Lease acquisition / restoration | Exact `TerminalLeaseRequest`, existing headless lease thread | Publish after real acquired/restored transitions; final retirement requires real hold return and join, not merely a `finally` event. |
| Provider input consumed | Existing PTY adapter, exact run and bounded marker | After Windows `_observe_output` or the POSIX handle's terminal-state `observe_output`, match fixture `echo:` across chunks. Fixture closes its input-log append before emitting echo. Read log once after acknowledgement; no second reader or file poller. |
| Summon ready / return | Textual, exact owned run token | After real `_apply_summon_ready` / `_apply_summon_return`; driver readiness and UI apply are distinct. |
| Retirement | Resource owner, retained run/adapter/thread objects | Stop, await foreground completion, then bounded joins/close; native cancellation needs reader-cleanup evidence, not only child exit or EOF. |

### Evidence and budget refinements

Historical logs were retrieved, not inferred from current green tests. The
register now distinguishes direct failures, verified mechanisms, and
unmeasured hypotheses. The original S4 log contains only attempt exhaustion;
no observation distinguishes source, callback, or rendered-state failure.
Neither a synthetic mutation nor a new green soak establishes that cause.

No TUI-specific CI timeout scaling factor exists in the inspected helpers or
workflow. Existing explicit 5-second app behavior limits stay 5 seconds.
Attempt counts cannot be converted by multiplying by 10 ms: `Pilot.pause`
also contains framework screen/idle fences. Proposed replacement bounds
must be recorded per inventory group before migration. Existing source
timeouts/joins remain source-specific infrastructure/cleanup caps, not new
behavior allowances. Native diagnostic samples will justify setup caps;
whole-suite duration is not that justification.

S4's forced old-after-new schedule needs clarification: the session worker
serializes navigation and its snapshots lack generations. Hold actual future
return and queued application separately, using future identity. Forcing an
old navigation callback after a new one is a diagnostic schedule, not a test
of a guard that already exists. If it demonstrates a reachable product
defect, write its causal regression and review the correction. Conversation
and search already have generation/intent fences and can test them directly.

The recorded tripwire is a violated observer contract: a required phase has
no terminal record at its deadline, duplicate terminal publication, a wrong
request/generation accepted, or a finish before its own start. Normal
supersession/cancellation is an explicit outcome, not a false violation.
Diagnostic wrappers must not declare all background work required at teardown.

Independent model review passed with M1–M3 incorporated below. Native
diagnostic measurement and the justified replacement caps remain pending.

### Independent model review result

2026-09-25: fresh same-family separate-role fallback returned PASS. It read
the full model and all three artifacts, relevant product callbacks, core
watcher readiness, native/shared PTY paths, the gate fixture, and installed
Textual 8.2.8 implementation. No architectural blocker or new production
publication was required. Findings are reproduced verbatim:

| ID | Severity | Location | Finding | Suggested disposition |
|---|---|---|---|---|
| M1 | P2 | Plan, “Model boundary and proposed test interface,” absolute-deadline paragraph; completion-seams artifact, publication paragraph | The final retained-outcome check must distinguish an on-time completion whose wake was delayed from a completion published after the deadline. Presence alone is insufficient under event-loop contention. The outcome already carries completion time, but the acceptance rule is unstated. | State that the final check accepts only an outcome recorded at or before the absolute deadline, using one consistent monotonic clock domain. Add paired firing tests: on-time publication with delayed wake succeeds; post-deadline publication does not turn expiry into success. |
| M2 | P2 | Completion-seams artifact, attach-confirmation wrapper and duplicate-terminal rules; `summon.py`, `TerminalAttachConfirmationRequest.resolve/fail` | `resolve` and `fail` deliberately become no-ops after the first resolution. A wrapper that publishes after every invocation would report legitimate duplicate calls as duplicate terminal transitions. Concurrent resolution attempts make an unsynchronized before/after check insufficient. | Make the adapter publish the first retained decision transition once, while preserving every call to the real method and the production `_on_resolved` callback. Test repeated and competing resolve/fail calls. Keep duplicate-publication tripwires for actual observer-contract violations, not idempotent producer calls. |
| M3 | P2 | Wait-inventory artifact, `DISMISS` row | The row permits the result callback and `AwaitComplete` interchangeably. Textual’s result callback proves result delivery; it does not prove screen removal finished. `Screen.dismiss` schedules the result callback, while `App.pop_screen` returns a separate completion for `_replace_screen` and removal. | Split result-applied and screen-retired observations where the assertion needs both. Use the callback for result/application assertions and the real, cancellation-shielded `AwaitComplete` for unmount/retirement assertions. An observer timeout must not cancel Textual’s shared removal future. |

All three accepted. M1 is explicit in the completion contract/model and owed
paired firing tests. M2 is explicit in the adapter contract and owed repeated/
competing-resolution proof. M3 splits result delivery from screen retirement
in the inventory and seam artifact; removal futures are shielded from observer
timeouts. These are safeguards within the approved scope. The review does not
qualify native measurements, elicitation mutations, or S4's historical cause.
