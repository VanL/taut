# Release CI Test Determinism Plan

Date: 2026-09-01

Class: 4. The correction crosses root, Summon, and TUI test boundaries. The
TUI decline failure requires a concurrency-safe production correction to
restore existing [TUI-13.2] diagnostic precedence, and hosted follow-up exposed
a search-anchor ownership race against live refresh under [TUI-6.4]. No
intended behavior or release gate changes.

Status: completed.

## Goal

Repair the exact-SHA CI failures blocking the coordinated 0.9.6 release by
making each test enter the state it claims to test through causal events or
platform-correct selection. Preserve every behavior assertion, required
platform, timeout budget, and release gate. Replace Summon's historical fixed
worker counts with `-n auto --dist load` after owner review identified those
caps as an isolation blind spot rather than a product constraint.

## Source Documents and Baseline

- `AGENTS.md` and the canonical startup sequence in
  `docs/agent-context/README.md`
- `docs/specs/01-development-documentation-operating-model.md` [DOM-5],
  [DOM-10], [DOM-15]
- `docs/specs/02-taut-core.md` [TAUT-12.5]
- `docs/specs/04-summon.md` [SUM-7.1], [SUM-7.4], [SUM-12]
- `docs/specs/10-taut-tui.md` [TUI-6.4], [TUI-13.2]
- `docs/agent-context/runbooks/testing-patterns.md`
- `docs/implementation/05-taut-summon-architecture.md`
- `docs/implementation/12-taut-tui.md`
- `docs/plans/2026-08-17-tui-search-anchor-test-synchronization-plan.md`, whose
  stop gate requires an exact-intent wrong-anchor observation to be treated as
  an application race
- `docs/plans/2026-07-13-bounded-summon-process-test-parallelism-plan.md`, the
  fixed-width policy superseded by the owner decision in this task
- exact-SHA CI runs for `1eec6803a123f28de9b4e16a1d0852bb6181fd06`

Baseline failures: root run `33547281507` and TUI run `33547281505`.

## Invariants and Constraints

- Do not extend a timeout, remove or skip meaningful platform coverage, retry
  failed assertions, or weaken expected diagnostics.
- Every Summon release lane must pass under explicit `-n auto --dist load`.
  CI must use the same topology for Summon unit, process, process-coverage, and
  prepared local-LLM execution, with no matrix `max-parallel` cap. External
  live providers remain a local release gate but receive the same topology.
- The prepared Ollama service and each external provider executable are real.
  Tests own separate databases, members, paths, processes, and control state;
  provider-side inference queuing is allowed, test-side shared mutable state is
  not. The one current local-LLM smoke does not by itself prove concurrent
  requests, but the lane topology must not suppress future pressure.
- External provider CLIs still share host auth/config/cache stores and provider
  account quotas. Those are residual prerequisites, not test-owned resources.
  A failure caused by concurrent access to them must be classified and fixed at
  the provider adapter or fixture boundary; it is not grounds for a serial
  fallback.
- Keep real subprocess, PTY, Textual, SQLite, and stdio protocol boundaries.
- A PID publication is not a lifetime fence. A later-stage timeout test must
  causally establish completion of all earlier protocol stages.
- POSIX rejection is asserted only against the POSIX implementation branch;
  the real Windows success path remains covered on Windows.
- No tag or publication occurs until all exact-SHA pre-tag workflows pass.
- A search intent owns its programmatic message anchor as the exact
  `(intent token, message id)` pair until the restore scheduled by that
  intent-tokened `ConversationSnapshot` commits the physical viewport on the
  following refresh, the intent is superseded, the search context fails or is
  rejected, or teardown begins. A stale or unrelated render naming the same
  message may neither release ownership nor scroll a newer view. Live delivery
  and navigation refresh may update content during that window but may not
  recapture the stale physical viewport over the owned logical anchor.

## Hardening: Concurrency Boundary and Rollback

- Hidden coupling: `PtyHandle` can close its master on the pump thread before
  `_finish_generation()` publishes `harness_dead`; the supervisor's concurrent
  orientation write must still classify that terminal adapter state as a
  pre-readiness generation exit.
- Primary-error order remains: control failure, explicit shutdown, pending
  readiness abort, then ordinary orientation failure. Post-readiness write
  failures retain their current diagnostic.

  ```text
  terminal adapter outcome
          |
          +-- control failed ------> control failure
          +-- shutdown requested --> shutdown result
          +-- readiness pending ---> readiness-abort diagnostic
          `-- readiness published -> ordinary orientation diagnostic
  ```
- Keep the real PTY, pump thread, supervisor, setup gate, and Textual owner in
  acceptance proof. A fake handle is permitted only for the deterministic unit
  proof of the exact pre-publication ordering.
- Rollback is the production typed-outcome change plus its focused tests. There
  is no storage, wire, package, or public API migration and no one-way door
  before tag publication.
- Stop if the typed outcome leaks into the public adapter API, changes ordinary
  post-readiness orientation errors, changes shutdown/control precedence, or
  requires waiting for the pump thread in the error classifier.
- Success signals: deterministic unit proof of master-close-before-death
  publication, the unchanged real TUI setup-decline assertion, full Summon and
  TUI suites, and green exact-SHA hosted lanes.
- Search-anchor rollback is the internal pending-anchor latch plus its
  deterministic interleaving test. It changes no public API, storage, search,
  history, watcher, or cursor contract. Stop if the correction quiesces the
  watcher, drops a delivery, substitutes polling, or accepts a different
  message anchor.

## Tasks and Verification

1. Reproduce or stress each CI symptom with its narrowest runnable test.
2. Correct platform selection for the Windows pipe constructor test.
3. Hold provider-leader exit behind a bounded release file after descendant
   publication. Start the real pump, capture PID and creation identity while
   that hold is active, then release leader exit. Keep this deliberately
   stubborn test descendant alive after PTY output closure until `close()`
   retires the domain, preserving the post-`ExitEvent` liveness assertion.
4. Separate MCP process-start readiness from the intentionally tiny
   later-stage behavior timeout so each timeout case reaches its named stage.
5. Synchronize empty-search rendering with the real search `Future` and a
   post-refresh event. Add an internal, non-exported typed terminal-adapter
   outcome so a PTY master closure observed before pump death publication still
   maps to the specified pending-readiness abort. Fire the full precedence
   matrix: control failure remains primary; shutdown returns shutdown; pending
   readiness produces the exact readiness-abort diagnostic; published
   readiness retains the ordinary orientation diagnostic; and an ordinary
   `AdapterError` while readiness is pending remains an ordinary orientation
   failure. Each error path must retire the generation exactly once and keep
   cleanup failure subordinate. Retain the unchanged real PTY/TUI acceptance
   proof.
6. Run each focused test repeatedly, then the affected root, Summon, and TUI
   suites under their CI worker topology; run Ruff, formatting, mypy, and doc
   gates.
7. Obtain independent completed-work review, commit, push, and require fresh
   exact-SHA CI. Then rerun unchanged `python3 bin/release.py all --version
   0.9.6` and verify all five GitHub and PyPI publications.
8. If fresh hosted CI exposes another release blocker, classify it from the
   exact failing assertion and preserve its contract. For a time-boundary
   assertion, hold the validation clock fixed rather than adding timing margin.
9. Supersede the fixed-width Summon policy in [TAUT-12.5]. Red-green the exact
   release-helper and workflow guards, then run every isolated Summon lane with
   `-n auto --dist load`. Keep fresh invocation and environment boundaries;
   do not combine lanes merely to obtain concurrency. Reconcile the live
   guidance owners in the Summon implementation note and test conftest, the
   current gate block in the 2026-07-12 plan, and the related-plan text. Mark
   the 2026-07-13 bounded-parallelism plan superseded and append a dated
   correction to the lessons ledger; preserve historical evidence rather than
   rewriting it as though it used the new topology.
10. Reopen the prior search-anchor stop gate as a production race. Add a
    deterministic real-Textual regression that invokes viewport capture after
    the exact search render schedules restoration but before that restoration
    runs. Atomically arm an internal `(intent token, message id)` owner with
    the search anchor. Pass restore ownership only from the exact
    intent-tokened `ConversationSnapshot`; delivery and navigation renders do
    not inherit it. Preserve ownership until the exact restore's following
    refresh commits the viewport. A stale or same-message unrelated restore
    must not release or scroll. Superseding intent, missing-hit snapshot,
    second-stage exception/`None`/apply rejection, and teardown clear ownership
    and invalidate deferred callbacks. Add a firing test for every branch.
    Keep live delivery active and retain every exact snapshot, later-content,
    row, target, and final-anchor assertion. Update the TUI implementation note
    with this ownership and finalization boundary.

## Independent Review

Review must check app-versus-test classification, exact causal fences, cleanup
on every failure path, unchanged assertions/timeouts/parallelism, and that each
regression test remains capable of detecting the original defect.

## Out of Scope

Unrelated product behavior changes, workflow topology changes, release
bypasses, manual publication, timeout increases, and unrelated cleanup.

## Fresh-Eyes Review and Execution Log

- Independent plan review found one blocking ambiguity: the existing atomic PID
  file is only a child-to-test acknowledgement and cannot prevent leader exit
  from closing the PTY before identity capture. Task 3 now requires the inverse
  test-to-provider release fence and post-output-close descendant lifetime.
  Review approved the amended plan; the Windows branch-forcing approach must
  not become a platform skip.
- Class 4 review found the production task named the precedence invariant but
  did not require a firing test for every branch. Task 5 now enumerates the
  five-case typed-outcome matrix, exact teardown ownership, and the internal
  non-exported boundary. The amended production approach is approved.
- RED: the forced pending-readiness terminal outcome produced `cannot orient
  the harness: provider exited during orientation` before the driver mapping.
  The coverage-instrumented MCP setup reproduced wrong-stage initialization
  failure 7/50 before stage-local timeout arming; the macOS busy-PTY fixture
  lost the published child before identity capture at iteration 35/50.
- GREEN stress: busy PTY 30/30, real setup-decline 10/10, MCP request/shutdown
  target timeouts 30/30, and native empty search 30/30.
- GREEN suites: root compatibility file 70 passed; Summon 694 passed with four
  expected OS/live-environment skips under one `loadgroup` worker; TUI 425
  passed under two `loadfile` workers. Repository-wide Ruff, format,
  suppression-index, all five mypy surfaces, doc paths, plan index, and focused
  doc tests passed.
- Independent completed-work review found the post-readiness unit fixture had
  removed `_on_ready` rather than retaining it with callback publication
  complete. That would not fire if the production readiness guard regressed.
  The fixture now varies only `_ready_callback_invoked`. The same review led to
  module-local Windows `os` isolation and pre-spawn release-fence validation
  with kill/reap on timeout. Re-review found no remaining release blocker.
- Fresh exact-SHA CI passed every PG, MCP, and TUI lane and 21/22 root jobs.
  Windows Python 3.14 exposed a separate test-clock race in
  `test_default_future_skew_boundary_is_300_seconds`: the test encoded a
  timestamp 301 seconds ahead but validated it against a later wall-clock
  sample. The 4.92-second test duration and the observed acceptance show that
  enough time elapsed for the sample to age within the 300-second boundary.
  The boundary proof now fixes SimpleBroker's validation clock at the same
  instant used to encode both 299- and 301-second cases. This preserves the
  exact boundary and removes filesystem/process speed from the assertion.
- Owner review rejected the historical fixed-width Summon policy. RED: exact
  release-helper and workflow guards fail while commands remain at unit
  `-n 0`, process `-n 4`/`-n 2`, and live `-n 1 --dist loadgroup`. Before any
  command change, the existing deterministic process selector passed locally
  with 16 auto-selected workers under `--dist load`: 303 passed and three
  expected platform skips in 49.50 seconds.
- Independent concurrency review required all live guidance owners to be
  reconciled and provider auth/config/cache plus account quotas to remain named
  residual shared prerequisites. After those amendments it approved the
  auto-width implementation. GREEN: the unit selector passed 383 tests on 16
  workers in 16.02 seconds; all eight strict external-provider live cases
  passed concurrently on 16 workers in 12.85 seconds; and the complete
  release/workflow guard files passed 188 tests on 16 workers. The ordinary CI
  unit step was already effectively auto-width through project addopts; making
  it explicit improves drift detection but is not counted as a speedup.
- Auto-width coverage then exposed a parser-fixture lifecycle race: a replay
  child could print one malformed Claude event, the expected parser error could
  win, and `close()` could terminate the child while its automatic coverage
  finalizer was writing. Four of five stress runs produced one or two zero-byte
  shards, correctly rejected by the fail-closed combiner. The parser-only
  helper now observes natural child exit before parsing the buffered line. Ten
  subsequent 16-worker coverage runs produced 88 readable shards each and all
  passed the repository combiner; the protocol-error assertion is unchanged.
- Failure-path review required that the parser helper also close the replay
  handle if its bounded natural-exit assertion fails. After that correction,
  five more auto-width coverage runs produced 88 non-empty shards each and all
  passed the fail-closed combiner. The prepared disposable-Ollama gate also
  passed its live inference case with `-n auto --dist load` (50 local workers,
  18.37 seconds).
- Independent closure review approved the completed slice with no blockers. It
  verified failure-path replay cleanup, explicit owned-versus-residual resource
  boundaries, exact auto/load topology and guards, unchanged selectors and
  assertions, and no matrix cap or serial fallback.
- Fresh exact-SHA TUI run `33558275375` reached the exact expected-intent
  search restore with the target hit arguments but found the logical anchor
  overwritten by an earlier notice. This fires the prior plan's application
  race stop gate. The proven ordering is search-anchor commit, deferred
  physical restore, live-delivery or navigation viewport capture, then the
  exact restore. Increasing the event cap cannot change that ordering.
- Fresh exact-SHA root run `33558275396` exposed a separate probabilistic test
  oracle: a valid random Base32 member id contained the display-name fragment
  `van`. The test now injects one fixed valid generated id and asserts exact
  stable return, while the dedicated random-id test continues to own entropy
  and shape coverage. No production restriction was added.
- RED TUI proof scheduled a real navigation refresh after the exact owned
  physical restore but before its finalizer. Textual reset the physical
  viewport to the first row while the logical anchor still named the search
  hit. GREEN adds an authorized-restore phase: a later content render
  invalidates the old finalizer and re-establishes the exact physical scroll
  before ownership is released. The full retained-lock TUI suite passed 434
  tests under its two-worker `loadfile` topology; focused lifecycle/error tests
  passed 10/10, Ruff and mypy are clean, and the exact handler passed 40/40
  under eight-worker review stress.
- Independent re-review approved the search-anchor correction with no P1/P2
  blockers. It verified the physical viewport assertion, generation-bound
  stale-callback no-ops, synchronous and asynchronous failure cleanup,
  supersession, and teardown without pausing or dropping live delivery.
- Fresh exact-SHA root run `33561588262` exposed a Windows filesystem
  publication race in the process-domain test harness. The descendant had
  atomically replaced its complete PID payload, but the redundant reader saw a
  transient `PermissionError` after target visibility; the exact Windows or
  filesystem-filter cause is unobserved. The Windows Job proof now waits for
  an exact `descendant-ready` provider event that can only follow successful
  child spawn and PID
  publication, then captures the sole direct child from the already-known
  provider process. The redundant second file reader is gone from this path.
  The five-second containment cap and every process/job assertion are
  unchanged.
- Exact-SHA hosted evidence is green: root `33562480441` (23 jobs), PG
  `33562480448`, MCP `33562480513`, and TUI `33562480535` (five retained-lock
  jobs). The corrected Windows 3.11 process proof and the local-LLM smoke both
  passed. The root workflow completed in 12m35s wall time including runner
  allocation; no job failed.
- The unchanged coordinated release helper passed 2,233 root tests, 28 wheel
  tests, 314 shared Postgres tests, 40 PG extension tests, seven MCP/PG tests,
  383 Summon unit tests in 15.70s at auto width, 301 Summon process tests in
  46.01s at auto width, eight live harness tests in 11.61s, the local-LLM
  smoke in 18.09s at auto width, 289 MCP tests, and 435 TUI tests. All Ruff,
  formatting, suppression, and five mypy gates passed. Compared with the
  reported 38.00s four-attempt local-LLM failure, the final smoke completed on
  its first attempt in under half that wall time; this is observed release
  evidence, not a controlled performance benchmark.
- Release-gate runs `33564360352`, `33564351484`, `33564354442`,
  `33564363904`, and `33564357967` all passed. All five `0.9.6` GitHub Releases
  and PyPI projects contain exactly one wheel and one source archive with
  matching SHA-256 digests. PyPI integrity provenance contains a Sigstore
  certificate and transparency entry for all ten files, tied to the exact
  package release-gate workflow. GitHub Release assets expose matching SHA-256
  digests but no GitHub artifact attestation; `gh attestation verify` returns
  404 for the core wheel. That provenance-surface gap is explicit and was not
  silently treated as publication failure because the current release contract
  requires inner bundle provenance plus exact-byte postflight, not a GitHub
  artifact attestation.

## Deviation Log

| Planned behavior | Actual behavior | Rationale |
|------------------|-----------------|-----------|
