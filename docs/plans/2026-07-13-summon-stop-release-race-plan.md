# Summon STOP Release Race Plan

Status: Root fix implemented and verified; intentionally uncommitted pending
user review.

Plan type: Implementation against the existing lifecycle contract. If the
diagnosis requires a new durable generation field or control-envelope field,
stop and revise this plan as implementation with spec revision before changing
the spec, schema, or protocol.

## Goal

Eliminate the CI-observed race in which the second same-process rich-host PTY
generation receives a correlated STOP error saying that driver-slot release
could not be confirmed. Preserve bounded xdist `--dist load` pressure and make
the lifecycle result deterministic through ownership and ordering, not longer
timeouts, whole-command retries, or serialized scheduling.

## Requested Outcomes

- The real rich-host PTY test deterministically starts, stops, resumes while
  wired, and stops again without a false STOP error.
- STOP acknowledges only after the active generation has completed teardown
  and released its claim. A real cleanup failure remains fatal and reports its
  actual plane instead of being mislabeled as a ledger-release failure.
- No prior foreground, pump, watcher, or control owner can mutate or answer for
  a successor generation.
- The deterministic process lane remains `-n 4 --dist load` locally and
  `-n 2 --dist load` in CI and coverage.
- No timeout is lengthened. No new retry loop, dependency, scheduler fallback,
  or mock of broker, sidecar, control dispatch, subprocess, or PTY is added.

## Source Documents

- `docs/specs/04-summon.md` [SUM-7.4], PTY attach/detach and fd ownership.
- `docs/specs/04-summon.md` [SUM-8], session ledger and driver evidence.
- `docs/specs/04-summon.md` [SUM-9], release-before-ACK STOP ordering and
  evidence-relative confirmation.
- `docs/specs/04-summon.md` [SUM-11], checked generation teardown and stale
  owner fencing.
- `docs/specs/04-summon.md` [SUM-12], real PTY/control verification floors.
- `docs/specs/04-summon.md` [SUM-13], blocking foreground ownership for rich
  hosts.
- `docs/implementation/05-taut-summon-architecture.md`, terminal interaction,
  control, ledger, and change guidance.
- `docs/plans/2026-07-12-lazy-command-extensions-and-rich-tui-composition-plan.md`,
  Tasks 8 and 9.
- `docs/plans/2026-07-13-bounded-summon-process-test-parallelism-plan.md`, the
  fixed-width load rollout whose first remote macOS/Python 3.13 observation
  exposed this failure.
- User direction in this task: keep xdist load, solve the root race, do not
  lengthen timeouts, rank at least four hypotheses, and distinguish them with
  targeted tests.

## Spec Baseline

- Commit `0a7e5fa2436f88cd63c51b2d446028d6414fb488`.
- Governing file: `docs/specs/04-summon.md` at that commit.
- The worktree was clean before this plan and plan-index entry were added.
- This plan initially claims conformance repair, not a spec delta. A durable
  generation token or changed public/control shape is a stop condition that
  requires a `## Proposed Spec Delta`, independent review, and promotion before
  dependent implementation.

## Context and Key Files

- `extensions/taut_summon/tests/test_interaction.py` owns the failing real PTY
  scenario. Its second run waits only for `terminal_availability()`. That call
  occurs after the ledger claim but before spawn, pump, and control startup, so
  the subsequent STOP may already be queued when the control owner opens.
- `extensions/taut_summon/taut_summon/_driver.py::_run` owns final release,
  `shutdown_complete` publication, and the control-thread join.
  `_control_release_confirmed()` currently collapses two facts into one bool:
  ledger release and absence of `_shutdown_error`.
- `_driver.py::_shutdown_current_generation` and `_teardown_generation` own the
  duplicate interrupt, PTY close, checked pump join, and shutdown error.
- `_driver.py::_start_control_thread` passes process evidence plus callbacks to
  the control owner. The final `_run` join is bounded but does not currently
  reject a still-live control thread.
- `extensions/taut_summon/taut_summon/_control.py::ControlLoop.run` waits for
  `shutdown_complete`, calls the combined confirmation callback, and emits the
  same release-error text for either a false ledger result or teardown error.
- `extensions/taut_summon/taut_summon/_state.py::claim_driver` and
  `release_driver` use `(driver_pid, driver_start_time)` as ownership evidence.
  Two embedded foreground drivers in one process therefore have identical
  evidence.
- `extensions/taut_summon/taut_summon/_pty.py::PtyHandle` owns concurrent
  interrupt/close/write leases and child reap. The reported path uses a real
  fake-TUI subprocess and real PTY.

Comprehension gates:

1. Why does the reported message not prove `release_driver()` returned false?
   Because `_control_release_confirmed()` also returns false when
   `_shutdown_error` is non-null, and `ControlLoop` maps both cases to the same
   release diagnostic.
2. Why is process evidence not necessarily driver-generation evidence in this
   test? Both blocking controller runs execute on threads in one host process,
   so PID and process start time are identical across the two lifecycles.

## Ranked Hypotheses and Decision Probes

The initial ranking over-weighted command queue time. The plan review and owner
code show that a command queued during `terminal_availability()` cannot call
`request_stop()` until the control consumer exists, after spawn, rejoin, wired
handling, pump start, and initial-session handling. The revised ranking below
separates command arrival from dispatch and separates release false from release
exception.

1. **Driver-level PTY/watcher shutdown ordering records a teardown error
   (35%).** STOP may be dispatched at the post-control, orientation, watcher
   publication, or live-watcher boundary. The exact path can call PTY interrupt
   from `request_stop()`, then interrupt and close from watcher shutdown, then
   interrupt and close again from `_shutdown_current_generation()`.
   - Support: an explicit phase barrier makes the real driver sequence produce
     a teardown error and the reported public failure while ledger release is
     confirmed.
   - Refute: every pinned phase completes with a null teardown error, one
     finalized release success, dead watcher/pump owners, and a STOP ACK.
2. **Ledger release raises under shutdown-time SQLite handle contention
   (25%).** `_release()` catches every exception, logs it, and reduces it to the
   same false confirmation seen by the client.
   - Support: the structured outcome records a release exception on the real
     failing path; a deterministic lock-order probe reproduces that exception
     using production writers and queue handles.
   - Refute: both lock orders serialize and complete, and phase-pinned STOP
     outcomes never contain a release exception.
3. **Queued STOP dispatch timing crosses an incompletely ordered driver phase
   (20%).** The test treats availability as readiness. The durable command is
   safe before control startup only if every later dispatch boundary has a
   single shutdown owner and a complete teardown path.
   - Support: pinning the same queued command to one exact post-control,
     orientation, or watcher transition reproduces the public error and one
     classified internal failure.
   - Refute: the command remains durable and all explicit dispatch boundaries
     converge on the same clean shutdown result.
4. **Real SQLite release returns false after a production-writer interleaving
   (10%).** A concurrent session or wired update makes the evidence-predicated
   release affect zero rows or leaves indeterminate evidence.
   - Support: a real sidecar concurrency test makes `release_driver()` return
     false without a test-only trigger or malformed row.
   - Refute: `BEGIN IMMEDIATE` serializes both lock orders and release always
     clears or confirms complete replacement. Code inspection already makes
     this less likely than a release exception.
5. **Process evidence fails to fence a stale same-process lifecycle (6%).** Two
   embedded drivers share PID/start evidence. This explains the sequential CI
   failure only if an old owner or stale command demonstrably survives the
   first foreground join and acts on the successor.
   - Support: a deterministic stale-owner chain reproduces the second STOP
     error after the first foreground owner appears finished.
   - Refute for this incident: no old lane survives the first join and no stale
     command acts on generation two. Simultaneous same-process claim aliasing
     alone is a separate [SUM-8]/[SUM-9] defect, not causal proof.
6. **Unchecked control-owner join permits lifecycle escape (4%).** `_run`
   returns after a bounded control-thread join without checking liveness.
   - Support for this incident: an escaped first control owner survives while
     the first foreground thread satisfies the test's join, then consumes or
     affects the second STOP.
   - Refute for this incident: the first foreground cannot finish within its
   ten-second join while a control owner is blocked behind the thirty-second
   join. A confirmed unchecked-join defect remains separate hardening unless
   a causal chain is shown.

### Diagnostic Verdict

- Hypothesis 1 is confirmed, narrowed to the pre-watch orientation write. A
  real PTY write barrier held the foreground inside `_write_all`; the real
  control STOP completed `PtyHandle.interrupt()`, retiring the write epoch.
  The resumed write raised the expected `AdapterError("PTY write interrupted")`.
  Because shutdown called `_shutdown_current_generation()` from inside that
  handler, `_teardown_generation()` read the active error via `sys.exception()`
  and stored it as `_shutdown_error`.
- Hypothesis 3 is confirmed as the trigger shape, not a separate queue defect.
  Availability let the command be queued; the deterministic failure occurred
  only when dispatch interrupted the exact orientation operation.
- Hypotheses 2 and 4 are refuted for the reproduced incident. The finalized
  outcome showed teardown error with release confirmed and no release
  exception. The same real SQLite release path ACKed after the exception-scope
  fix. `BEGIN IMMEDIATE` still makes a pure production-writer false result the
  least likely ledger explanation.
- Hypotheses 5 and 6 are refuted as causal explanations for this sequential
  test. The first foreground thread, which owns the bounded control join,
  completed and was asserted dead before generation two was constructed. No
  stale owner was required to reproduce the failure.

## Invariants and Constraints

- Preserve the [SUM-9] truth rule: ACK means clean teardown plus confirmed
  release. Never turn a real cleanup or release failure into success.
- Preserve one active pump, watcher, control owner, and provider generation.
  A stale owner has no authority to mutate state, answer control, or clear a
  successor's claim.
- Keep the existing PTY writer operation-lease and reader-close ownership.
  Do not add another reader, signal path, or cleanup thread.
- Keep SimpleBroker ownership thin. Do not add substring retry, SQLite cleanup,
  or a Taut transaction layer around sidecar operations.
- Keep control STOP non-retrying and correlated through its existing
  per-request reply queue.
- Keep the real anti-mocking boundary: real SQLite, control queues, subprocess,
  and PTY for the integration regression. Narrow in-memory probes may control
  a barrier or thread exit, but may not stand in for the final proof.
- Error classification must preserve primary cause. A teardown failure and a
  ledger-release failure are distinct fatal facts even if both block ACK.
- No new dependency. No timeout changes. No `-n` or `--dist` changes.
- Preserve unrelated user work. Keep changes local to the diagnosed owner and
  its tests/docs.

## Hidden Couplings and Failure Priorities

- `terminal_availability()` is both a host-policy result and an observable
  pre-spawn barrier. Treating it as readiness is wrong.
- `_shutdown_complete` publishes results from the foreground owner to the
  control owner. Every field read after the event must be final for that
  lifecycle.
- A control reply can reach the client before the control thread finishes its
  own handle cleanup. Foreground completion must still prove that owner is dead
  before a same-process successor can be admitted.
- PID/start evidence proves process liveness across processes. It does not
  identify two driver lifecycles inside one process. If that distinction is
  load-bearing, it is a storage/control contract change, not a local test fix.
- PTY teardown errors outrank release success for STOP ACK, but the error plane
  must remain inspectable so diagnosis is deterministic.

## Rollout and Rollback

This is a code-and-doc rollback with no one-way door unless diagnosis requires
a schema field. Without a schema change, revert the driver/control/state slice
and its tests together. Observe the existing macOS/Python 3.13 two-worker CI
lane for disappearance of the exact STOP error, plus no new pump/control join
or PTY cleanup diagnostics. Do not roll back by serializing xdist or expanding
timeouts.

If a durable generation field is required, stop before implementation. Define
schema-version migration, mixed-version behavior, control-envelope rollout,
rollback compatibility, and post-deploy signals in a reviewed spec delta. Do
not make that one-way contract change under this baseline plan.

## Tasks

1. Make the shutdown result exact before probing the race.
   - Touch first: the nearest control/driver unit tests, then `_driver.py` and
     `_control.py`.
   - Red-test one immutable result published before `_shutdown_complete` that
     distinguishes teardown error, release false, and release exception.
     Preserve the current ACK truth table; improve only internal classification
     and the error detail returned on failure.
   - Keep control-thread close/join results separate because the STOP reply is
     produced by that owner before it can close itself.
   - Done: every non-ACK path has one exact firing test and the real integration
     test can record which plane fired.
2. Pin queued STOP dispatch at real driver phase boundaries.
   - Touch first: `extensions/taut_summon/tests/test_interaction.py` and the
     nearest driver lifecycle test.
   - Probe post-control startup, orientation, watcher publication, and
     live-watcher supervision in likelihood order with explicit events. Stop
     phase expansion when one boundary reproduces both the public error and an
     exact internal failure plane; do not add non-causal barriers after root
     selection. An availability barrier may prove the command was written
     early, but is not itself a phase verdict.
   - Keep the real database, controller, control dispatch, PTY, and child in the
     final probe. Failure cleanup must release every event and issue a final
     stop so no child or owner escapes an assertion.
   - Done: the orientation boundary reproduced the exact public and internal
     failure. Later watcher boundaries were therefore not added or claimed.
3. Prove or refute release exception and false-return paths.
   - If the finalized outcome selects the release plane, touch
     `extensions/taut_summon/tests/test_state.py` and exercise both lock orders
     with production writers over real SQLite. Record raised errors as distinct
     from false results; do not use an ignore trigger or malformed partial row.
   - Done for this incident: the exact reproduction selected teardown with
     release confirmed and no release exception. Existing `test_state.py`
     release tests passed; no new lock-order test is claimed or needed for the
     selected root.
4. Test stale-owner theories only as causal chains.
   - Touch first: the nearest driver/control ownership tests.
   - For same-process identity, require an old lifecycle to survive the first
     foreground join and affect generation two. For the unchecked join, prove
     the same chain rather than only showing a generic checked-join omission.
   - Record independently confirmed adjacent defects for follow-up, but do not
     select them as this fix unless they reproduce the original second-STOP
     failure.
   - Stop and revise/promote the spec if a per-run durable/control token is
     necessary for the selected causal fix.
   - Done: hypotheses 5 and 6 are causal, refuted for this incident, or tracked
     without being bundled.
5. Implement the smallest root fix red-green.
   - Choose exactly the owner selected by tasks 1-4. Extend the current path;
   do not combine speculative fixes.
   - Preserve exact failure priorities and add the integration regression that
     would fail on the original implementation.
   - Stop if the fix needs schema/protocol/public-shape change; revise the plan,
     add exact spec delta, review, and promote first.
   - Done: the selected deterministic red is green; the other probes remain
     green and continue to reject their disproved failure modes.
6. Reconcile docs, run gates, and review.
   - Update `docs/implementation/05-taut-summon-architecture.md` with the root
     ownership rule; update `docs/specs/04-summon.md` only through an explicit
     promoted spec-revision slice if intended behavior changes.
   - Record a durable lesson if the root exposes a reusable lifecycle rule.
   - Run focused, neighboring, full process-load, lint, format, mypy, docs, and
     diff gates. Then run an independent completed-work review.
   - Done: every finding is dispositioned and evidence is recorded below.

## Testing Plan

Start with deterministic barrier tests, not repeated load. Each hypothesis gets
one variable and one verdict. The final regression must cross the real public
controller, SQLite sidecar, correlated control request, driver thread, PTY,
and fake-TUI subprocess. Narrow unit tests may provide exact internal cause
classification, but cannot replace that integration proof.

Required command ladder after the red is selected:

```bash
uv run --extra dev pytest extensions/taut_summon/tests/test_interaction.py -n 0 -q
uv run --extra dev pytest extensions/taut_summon/tests/test_state.py extensions/taut_summon/tests/test_control.py extensions/taut_summon/tests/test_driver.py -n 0 -q
uv run --extra dev pytest extensions/taut_summon/tests -m "not xdist_group" -q
uv run --extra dev pytest extensions/taut_summon/tests -m "xdist_group and not requires_live_harness and not requires_local_llm" -n 4 --dist load -q
uv run --extra dev pytest extensions/taut_summon/tests -m "xdist_group and not requires_live_harness and not requires_local_llm" -n 2 --dist load -q
uv run --extra dev ruff check extensions/taut_summon/taut_summon extensions/taut_summon/tests
uv run --extra dev ruff format --check extensions/taut_summon/taut_summon extensions/taut_summon/tests
uv run --extra dev mypy extensions/taut_summon/taut_summon extensions/taut_summon/tests --config-file pyproject.toml
uv run --extra dev pytest tests/test_docs_references.py -n 0 -q
git diff --check
```

Python 3.13 is included for the selected focused regression because the remote
failure occurred there. Worker load is an acceptance gate after deterministic
proof, not the diagnostic mechanism.

## Verification Evidence Log

| Slice | Red evidence | Green evidence | Review | Status |
|-------|--------------|----------------|--------|--------|
| Exact shutdown classification | `test_control.py` initially failed collection because `StopShutdownOutcome` did not exist; driver release/teardown outcome tests then failed on the missing finalizer. | `test_control.py` passed; focused driver outcome tests passed. | Plan review required this slice before race probes. | Complete |
| Real PTY orientation/STOP race | The pinned original test failed in 2.85s with `STOP failed: driver teardown failed: PTY write interrupted`. | The identical barrier test passed after teardown left the expected cancellation handler; full `test_interaction.py` passed all 14 tests. | Final review found the root fix correct; barrier specificity and failure cleanup advisories were fixed and re-reviewed. | Complete |
| Neighboring control/driver regression | Not applicable after selected red. | `test_control.py` plus `test_driver.py` passed serially; final outcome truth-table cases passed after review. | No blocker. | Complete |
| Python-version match | Not applicable after selected red. | The pinned regression passed on macOS Python 3.13.13 before and after review edits. | No blocker. | Complete |
| State and scheduler gates | Not applicable after selected red. | `test_state.py` passed 43 tests; the 224-test process selector passed unchanged at both `-n 4 --dist load` and `-n 2 --dist load`, including final post-review reruns; the non-process extension selector passed under its default loadgroup topology. | No blocker. | Complete |
| Repository gates | Not applicable after selected red. | Core `tests/` passed; docs references passed 10 tests; ruff, format, mypy, and `git diff --check` passed; `uv build extensions/taut_summon` built both sdist and wheel. | No blocker. | Complete |

## Independent Review Loop

- Plan review: a different-family Claude review was attempted first, but the
  installed CLI had no detected authentication. An isolated read-only reviewer
  then reviewed this plan, the governing spec baseline, implementation note,
  failing test, and exact owner code before tests were edited.
- Meaningful-slice review: review after hypothesis selection if the fix crosses
  driver/control/state ownership.
- Final review: review the completed diff and current verification evidence.
- Every finding is accepted and fixed, rejected with reasoning, or marked out
  of scope below.

## Review Findings and Dispositions

| Finding | Disposition |
|---------|-------------|
| [P1] Availability only pins command arrival, not STOP dispatch or teardown phase. | Accepted. The exact orientation boundary reproduced both the public failure and internal plane. Later non-causal phase probes were not added. |
| [P1] Exact release/teardown classification must precede every race probe. | Accepted. Task 1 now creates a finalized structured outcome without changing ACK truth. |
| [P1] Same-process evidence and unchecked join probes could select adjacent defects without explaining this sequential failure. | Accepted. Both now require a concrete stale-owner chain and otherwise remain separately tracked hardening. |
| [P1] The ranking omitted release exceptions and the actual repeated PTY interrupt/close sequence. | Accepted. Both are now explicit higher-ranked hypotheses with firing probes. |
| [P2] Real SQLite lock tests must cover both orders if the release plane is selected, and barrier cleanup must be failure-safe. | Partly activated. The finalized reproduction selected teardown with release confirmed, so no new lock-order test is claimed. Cleanup releases every gate, signals captured drivers, then joins owners. |
| [P2] Teardown plus an unconfirmed release lost the second fact in the new error truth table. | Accepted. The combined branch now reports both facts and has a firing test. |
| [P2] Assertion-failure cleanup joined the STOP client before signaling the driver. | Accepted. Cleanup now releases gates and signals every captured driver before joining client and foreground owners. |
| [P2] Completed plan text overstated unrun phase and SQLite probes. | Accepted. Tasks, dispositions, and fresh-eyes text now state the conditional stop rule and the exact probes actually run. |
| Final re-review | All prior findings resolved; no P1 or new blocker. Residual: cleanup joins are bounded and do not assert liveness after an already-failed test. This does not affect the successful-path regression or production fix. |

## Deviation Log

| Spec ref | Planned behavior | Actual behavior | Rationale | Spec proposal |
|----------|------------------|-----------------|-----------|---------------|

## Out of Scope

- Serializing or reducing xdist pressure.
- Lengthening STOP, pump-join, control-join, or readiness timeouts.
- Whole-command retry, duplicate STOP, or substring broker retry.
- Provider behavior, terminal-query responder expansion, visual TUI design, or
  nonblocking driver supervision.
- Unrelated SQLite maintenance, SimpleBroker policy, or release tooling.
- Committing, staging, tagging, pushing, or releasing on the user's behalf.

## Fresh-Eyes Review

Completed by an isolated read-only reviewer before test edits after the
different-family path was blocked by missing local authentication. Initial result:
revise before implementation. The review found that availability pins command
arrival rather than dispatch, mandatory outcome classification was missing,
and two proposed probes could prove adjacent defects without explaining the
sequential CI failure. All findings are dispositioned above. Outcome
classification selected the exact orientation boundary; conditional later
phase and SQLite lock-order probes were not run and are not claimed.

Completed-diff review found no P1. Three P2 findings covered the combined
shutdown truth table, assertion-failure cleanup order, and plan accuracy; a
barrier-specificity residual was also addressed with a unique prompt payload.
The re-review confirmed every finding resolved and found no new blocker.
