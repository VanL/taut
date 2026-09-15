# Windows PTY Lifecycle Fixes

Status: completed (implementation, local verification, and independent review
complete; owner deferred hosted Windows qualification to the next push)
Class: 5 (spec-changing clarification); [DOM-5] risky triggers also fire:
background cancellation and native-handle cleanup ownership. Hardening applies.
Plan type: implementation with spec revision, strategy A.
Owner: implementing engineer; independent reviewer checks the plan and each
coherent implementation slice. Product owner decides changes beyond this scope.

## Goal

Finish the Windows PTY lifecycle corrections following `a24778e`: keep the
exit monitor's process handle valid, make completing-write cancellation safe,
give providers their graceful shutdown interval, and prove these changes in
the existing CI lanes. Preserve the cleanup-error aggregation already landed.
The implementation and spec promotion are present in the worktree. Native
ConPTY evidence remains gated on the existing hosted Windows process lane.

Requested outcomes:

- [x] Monitor owns a separate handle through wait, exit-code read, and cleanup.
- [x] Reusable interrupt cannot target a closed thread handle or poison later writes.
- [x] Close-request cancellation failures are reported and cleanup continues.
- [x] Windows close waits for graceful leader exit before closing ConPTY.
- [x] Platform-neutral regression tests actually run in non-Windows CI.
- [x] Spec, implementation rationale, and tests agree; native Windows evidence
  is explicitly deferred to the next push.

## Spec Baseline

Baseline: `a3cb49a5a4182c4faefa8dcf0eddfef1f29e1f66` for
`docs/specs/04-summon.md` [SUM-2], [SUM-7.1], [SUM-7.4], [SUM-9],
[SUM-11], [SUM-12], and the code inspected for this plan.
Promotion baseline: record after the spec-promotion slice, before dependent
implementation. Use its commit SHA, or base SHA plus the exact spec diff when
reviewing without a commit. Plan appendix text is not the governing contract.

Promotion baseline: base `a3cb49a5a4182c4faefa8dcf0eddfef1f29e1f66`
plus the worktree diff for `docs/specs/04-summon.md` produced by this plan's
spec-promotion slice on 2026-09-15. The exact spec delta and related-plan
backlink were promoted before code edits.

## Source Documents

Consulted: `AGENTS.md`; `docs/program-theory.md` [THEORY-2], [THEORY-3];
`docs/agent-context/README.md`, `decision-hierarchy.md`, `principles.md`,
`engineering-principles.md`, and `lessons.md`;
`docs/agent-context/runbooks/writing-plans.md`, `writing-specs.md`,
`hardening-plans.md`, `testing-patterns.md`, `adversarial-acceptance-probes.md`,
and `review-loops-and-agent-bootstrap.md`;
`docs/lessons.md` Golden Rules and post-watermark entries (especially
2026-09-15 cleanup errors, 2026-08-17 readiness ownership, 2026-08-05 separate
startup watchdogs); `docs/coalescing.md`;
`docs/specs/01-development-documentation-operating-model.md` [DOM-5],
[DOM-6], [DOM-10], [DOM-11], [DOM-15];
`docs/implementation/05-taut-summon-architecture.md` owned process domains;
`docs/implementation/03-agent-inventory.md`;
`docs/plans/2026-09-03-summon-unified-pty-cross-platform-plan.md` (completed
predecessor, not a second active owner);
`skills/brainstorming-to-plan/SKILL.md` and `skills/call-agent/SKILL.md`.

Native contracts checked against Microsoft documentation on 2026-09-15:

- [WaitForSingleObject](https://learn.microsoft.com/en-us/windows/win32/api/synchapi/nf-synchapi-waitforsingleobject): closing a handle during its pending wait is undefined.
- [HandlerRoutine](https://learn.microsoft.com/en-us/windows/console/handlerroutine): returning TRUE from CTRL_CLOSE_EVENT still terminates the process.
- [ClosePseudoConsole](https://learn.microsoft.com/en-us/windows/console/closepseudoconsole): immediate return starts with Windows 11 24H2 build 26100; older implementations can block. Output must remain drained.
- [CancelSynchronousIo](https://learn.microsoft.com/en-us/windows/win32/api/ioapiset/nf-ioapiset-cancelsynchronousio): cancellation requests do not wait for pending operations to complete; synchronize the targeted operation's lifetime.

## Context and Key Files

| File | Ownership and planned edits |
|------|----------------------------|
| `extensions/taut_summon/taut_summon/_pty_windows.py` | `_EpochWriter` owns serialized input and epochs; `WindowsPtyHandle` owns lifecycle and process monitor; `spawn_windows_pty` transfers suspended-child resources. Change these paths locally; retain `_record_cleanup`, `_CLEANUP_ERRORS`, and `_aggregate_failures`. |
| `extensions/taut_summon/taut_summon/_win32_io.py` | `NativeApi` owns Win32 bindings. Extract the existing native duplication body from `duplicate_fd_handle` into a small `duplicate_handle` helper, then reuse it. This helper is new, not a currently available API. |
| `extensions/taut_summon/tests/test_pty_windows.py` | Existing fake handle/attach APIs and real ConPTY tests. Extend them, and narrow the module-level Windows marker to individual native tests. |
| `extensions/taut_summon/tests/test_driver.py` | Existing real driver STOP and scripted cleanup probes; reuse their harness if a Windows end-to-end assertion is missing. |
| `docs/specs/04-summon.md` | Promote the exact delta below and backlink this plan. |
| `docs/implementation/05-taut-summon-architecture.md` | Document resource ownership, timing, and residual failure behavior; backlink the plan. |
| `docs/plans/README.md`, this plan, `CHANGELOG.md`, `docs/lessons.md` | Status, execution evidence, user-facing fixes, and concise durable corrections at implementation closeout. |

Read-only dependencies: `_driver.py` generation teardown and `_join_pump`;
`_process_domain_posix.py` (`graceful_timeout=5.0`); `scripted_provider.py`
(`sigint_cleanup_seconds`, received-log cleanup evidence);
`extensions/taut_summon/tests/conftest.py` real-process harness;
`.github/workflows/test.yml` unit/process selectors and static gates.
All unqualified Python filenames in this paragraph live under
`extensions/taut_summon/taut_summon/`.

Current defects and limits:

1. `_monitor_process_exit` waits indefinitely on the same process handle that
   `_close_owned_domain` closes after a timeout. The fake wait ignores handle
   validity and therefore accepts an unsafe native lifetime.
2. `_cancel_active` receives a snapshot whose thread handle can already be
   closed. `interrupt` lacks exception-safe state restoration. The landed
   cleanup fix already records close-worker AdapterError; do not describe that
   old silent-failure bug as still present.
3. `finish_close_request` joins the Ctrl-C writer, not the provider. ConPTY
   closes immediately afterward. [SUM-7.1] requires the graceful interval.
4. Module-level `windows_only` excludes even the fake tests from the normal
   Linux/macOS CI selectors. A direct local pytest invocation bypasses that
   exclusion and is not evidence of cross-platform CI coverage.

Before editing code, the implementer records answers in the execution log:
Who closes the monitor duplicate after timeout? Expected: only the monitor,
after its wait and exit-code read finish; caller closes only its original.
Does writing Ctrl-C prove child cleanup finished? Expected: no; wait for
leader-exit evidence while draining output. Wrong answers block editing until
the cited code/spec is reread.

## Invariants and Constraints

| ID | Required invariant | Proof |
|----|--------------------|-------|
| W1 | Every acquired handle has one cleanup owner; no wait/query/cancel uses a closed or reused handle. | Handle-validity fake, constructor failures, real Windows smoke. |
| W2 | Interrupt remains nonterminal; an older interrupt cannot clear a newer interrupt's state or undo retirement. | Barrier-controlled completion, failure, and interrupt/close races. |
| W3 | One terminal request owns at most one Ctrl-C attempt; request remains nonblocking and repeatable. | Existing tests plus delayed close-worker completion race. |
| W4 | Foreground close grants up to five seconds after successful graceful-write completion for leader exit, returning early on exit; it still closes ConPTY if the leader already exited. | Wait-order tests, real cleanup record, existing descendant test. |
| W5 | Cleanup keeps the landed error aggregation and `closed`/notify `finally`; later close reports the same recorded failure promptly. | Existing timeout/attach regressions and concurrent closer test. |
| W6 | Only a real return code produces ExitEvent, at most once. No synthetic exit, force-kill after publication, PID scans, or driver policy change. | Normal, delayed-exit, and timeout monitor tests; driver lane. |
| W7 | Windows native tests stay native; deterministic lifecycle tests run under both platform selectors. | Exact collection manifests and hosted process job. |

Hidden couplings: the constructor starts reply/drain ownership before the child
is resumed; if constructor work fails, outer spawn still owns the originals.
A successful constructor transfers those originals only on return. Monitor
completion must include releasing its duplicate before `_exit_monitor_done`
is set. A late monitor may publish a real exit after `closed`; it must never
clear the recorded close failure. `_exit_ready` can mean output ended, so it is
not proof of leader exit. Do not wait on it for the graceful stage.

Keep changes in existing owners. No dependency, CLI, storage, provider protocol,
POSIX lifecycle, or workflow infrastructure changes. No broad exception
swallowing or treating ERROR_INVALID_HANDLE as a benign cancellation result.

## Proposed Spec Delta

Strategy A: edit text in the existing active spec first, without new
implementation-link claims or classification changes. Review this delta before
promotion. Existing [SUM-2]/[SUM-12] acceptance-test scope stays intact.

### [SUM-7.1] replace the Windows sentences in the close paragraph

Replace the prose from "On Windows" through "adapter-specific order."
(baseline lines 426-430; the sentence wraps across lines) with:

> On Windows, after the graceful Ctrl-C write completes successfully, the
> closer allows up to five seconds for leader exit, returning from that wait
> early when exit is observed. It then closes the owned ConPTY session while
> output remains drained, including when the leader exited first. Runtime
> retirement uses the retained ConPTY capability and observes the leader's
> real exit status; the attached-descendant absence proof is the real-process
> acceptance test in [SUM-12], not a runtime ancestry scan. Finalization then
> releases streams, fds, and native terminal handles in adapter-specific order.
> Direct provider exit does not bypass either platform's descendant-retirement step.
> A background wait retains its own valid process handle until the wait and
> exit-code query have finished, even if foreground finalization times out.

Replace "Any other failed group signal, leader reap, ConPTY operation, or
Windows attached-descendant check is terminal `AdapterError`;" with:

> Any other failed group signal, leader reap, ConPTY operation, or Windows
> leader-exit observation is terminal `AdapterError`;

### [SUM-7.1] insert after the close/error paragraph

> If Windows finalization times out without a leader return code, it records
> a terminal cleanup failure and unblocks concurrent and later closers. It
> does not fabricate an ExitEvent. The monitor retains its private process
> handle until the child exits or the native observation fails, then releases
> that handle. A later observed return code may publish the one real exit
> event; it does not erase the recorded cleanup failure. The driver's checked
> pump join remains the failure bound if no exit event arrives. Application
> wait deadlines do not bound ClosePseudoConsole itself on older Windows
> implementations where that native call waits for pseudoconsole shutdown.

This explicitly qualifies the section's normal-success "one exit event" and
bounded-finalization wording. It does not promise a new terminal failure event
or expand the supported platform contract.

## Tasks and Gates

### 1. Review and spec promotion

- [x] Complete independent plan/delta review and disposition every finding.
- [x] On implementation authorization, promote the exact delta, add the
  related-plan backlink, and record the promotion baseline. Run doc gates.
- [x] Record the comprehension answers above before code edits.

### 2. Monitor ownership and CI selection (complete locally)

- [x] First strengthen `_HandleApi`: distinct original/duplicate identities,
  active-wait tracking, invalid-handle rejection on wait/query/close, and a
  child-exit barrier. The existing timeout test must fail on the original
  code because the waited handle closes while its wait is pending.
- [x] Add `NativeApi.duplicate_handle` by reusing the current DuplicateHandle
  binding (same access, non-inheritable, current process), with
  `duplicate_fd_handle` delegating after fd conversion.
- [x] Duplicate before monitor start. Transfer the duplicate to the monitor
  only when start succeeds. On duplication/start failure, close any duplicate
  locally; let the existing spawn rollback own originals and terminate only
  the unpublished child. Put the failure guard inside `WindowsPtyHandle.__init__`,
  covering reply-worker construction through monitor start: if a reply worker
  was successfully created, call its `request_close()` and `finish()` there.
  Record auxiliary cleanup failures on the original constructor exception.
  Neither method closes outer-owned handles; spawn cannot do this half-built
  object cleanup because its `backend` assignment never completed.
- [x] Monitor waits and queries through its duplicate and closes it in
  `finally`, before publishing completion. Preserve primary monitor failures
  if duplicate close also fails. Foreground close retains its original-handle
  cleanup path. A timed-out daemon monitor is intentionally retained until
  actual exit; this fix does not claim all threads ended at timeout.
- [x] Test normal exit, timeout then later exit, wait/query failure, duplicate
  failure, monitor-start failure, and duplicate-close failure. Assert release
  exactly once, real exit at most once, and prompt repeat/concurrent close.
  Test cleanup releases the exit barrier and joins every test-owned thread.
- [x] Remove module-wide `windows_only`; put it on each actual Windows-native
  test, retaining its skip guard and the module's process/sqlite grouping.
  Verify ABI assumptions against the existing x64 matrix. Collect with both
  CI filters and prove the named fake regressions appear in both selections.

Done signal: targeted tests pass; old-code red reason and both collection
manifests recorded. Independent slice review before proceeding.

### 3. Completing-write cancellation and reusable interrupt (complete locally)

- [x] Add barrier tests for interrupt and close request when a write completes
  before cancellation, and while cancellation is in progress. Fail on the
  old code through invalid-handle use or poisoned subsequent write, not sleeps.
- [x] In `_cancel_active`, under `_state`, confirm the exact `_ActiveWrite`
  object is still current, then call CancelSynchronousIo while holding that
  short lock. `write`'s finally cannot clear/close the active handle until the
  call returns. A stale snapshot is a no-op. Never hold the lock across
  WriteFile, thread joins, or `_wait_inactive`; cancellation only requests
  cancellation and does not wait for I/O completion.
- [x] Capture the interrupt's epoch and restore transient interrupt state in
  `finally` only if that epoch still owns it and retirement has not won. Before
  sending its Ctrl-C, verify it is still the current nonterminal interrupt.
  Carry that same captured epoch through the existing serialized write path,
  including its pre-WriteFile and post-WriteFile validations. Factor the shared
  private write body if needed; public `write(payload)` still captures a fresh
  epoch, but interrupt must NOT call it in a way that recaptures a newer epoch.
  A pre-send check followed by a fresh-epoch write leaves the race open.
  Test supersession after that check but before write publication. Do not let
  an older failure clear a newer operation's gate.
- [x] Keep unexpected cancellation errors visible. Add forced native
  cancellation-error and inactivity-timeout cases; after releasing the old
  write, subsequent nonretired writes must work. For close-request errors,
  assert `finish_close_request` raises and finalization still runs; no silent
  threading.excepthook-only failure.
- [x] Cover interrupt versus close request and overlapping interrupts with
  controlled barriers. Retired handles reject injection and emit no extra
  graceful signal. If the short-lock design cannot meet signal reentry or
  epoch ownership, stop and revise this slice rather than add an ad-hoc second
  lock or swallow errors.

Done signal: deterministic race matrix and existing real blocked-write test
pass; independent slice review checks locking and cancellation ownership.

### 4. Graceful interval and real Windows proof (implementation complete;
hosted native run pending)

- [x] Write order tests showing successful Ctrl-C completion precedes a
  five-second leader-completion wait, which precedes ClosePseudoConsole.
  Introduce a separate private graceful-timeout constant (5.0); keep existing
  I/O/monitor cleanup timeout meaning unchanged. Test zero/full-expiry and
  early-exit paths through a controlled wait boundary, not wall-clock sleeps.
- [x] In the foreground close owner, start the output drain before waiting,
  including when no events consumer was started. Then finish the Ctrl-C write,
  wait on leader-monitor completion only if the write succeeded, finish the
  reply writer, and close the owned domain. Split the uniform cleanup loop to
  express this conditional stage; retain `_record_cleanup`, failure precedence,
  and the outer `finally`. Record write failure and continue teardown. Do not
  move any wait into `request_close`, and never bypass ConPTY retirement on
  natural leader exit. Include a close-before-events-consumption order test
  requiring the drain to start before the graceful wait. Update test fakes to release or shorten grace explicitly
  where timeout is intentional.
- [x] Add a real `windows_only` ConPTY graceful-cleanup test in the existing
  test module. Reuse `scripted_provider.py` and its received-log scenario with
  `sigint_cleanup_seconds` below five seconds. Wait for actual provider
  readiness, then call public request/close. Require first-signal-entered,
  cleanup-release with source watchdog, one signal, one real successful exit,
  and no surviving provider. Keep production five-second grace in this proof.
  Set the scenario/received-log environment through the existing provider
  interface and wait for its `provider-ready` record. The provider's raw-byte
  parser calls `interrupts.interrupt()` when it reads Ctrl-C, so this proof
  does not require native delivery of Python SIGINT.
  Extend `test_control_stop_sends_one_graceful_signal_to_provider` in
  `test_driver.py` to run on Windows by removing its `posix_only` marker and
  strengthening cleanup-release to require source watchdog. That test already
  uses the public STOP CLI and `driver.wait()`, not `send_signal`. Keep the
  separate direct-driver-SIGINT test POSIX-only. No duplicate STOP harness.
- [x] Keep real process creation, ConPTY, drain, Ctrl-C, and monitor native.
  Test watchdog cleanup owns creation identity and kills only its own child
  on failure, then joins test workers. Startup gets a separate bounded budget;
  time alone is not readiness. Inspect cleanup records after child termination.
- [ ] Run the existing descendant-retirement and native blocked-write tests
  along with the new native proof on the Windows CI process job.

Do not add the proposed "return TRUE to ignore CTRL_CLOSE_EVENT" test. It
cannot establish that premise. The fake timeout proves resource ownership;
native graceful cleanup and existing native shutdown tests prove integration.
If native Windows cannot meet the intended proof, capture the exact OS build,
test failure and traces; fix or replan, never weaken assertions or auto-retry.

### 5. Reconcile and verify

- [x] Update implementation rationale, changelog, and concise lessons about
  pending-wait handle ownership and CI marker exclusion. Evaluate heavily used
  skills/runbooks for improvement; propose durable process changes separately.
- [x] Reconcile spec/plan/implementation links and all W1-W7 proofs. Every
  accepted review finding must have a disposition and evidence.
- [x] Run final local gates below and independent completed-work review. The
  owner deferred exact-SHA hosted Windows results to the next push.
- [x] Commit only with owner authorization using explicit file-list staging.
  Verify the commit with `git log`; otherwise report the changed files as
  uncommitted and do not claim the implementation is finished or ready to land.

## Testing Plan and Verification Commands

Run from repository root using the configured project environment. Slice tests
run first; dependent edits and gates are sequential. Independent read-only
searches can run together. Do not run competing process-heavy suites together.
New behavior tests are red-green; record the pre-fix failing assertion and
post-fix result. Plan-only verification uses inspection and reproducible docs
checks; it makes no runtime proof claim.

```bash
.venv/bin/python -m pytest extensions/taut_summon/tests/test_pty_windows.py -q -n 0
.venv/bin/python -m pytest extensions/taut_summon/tests/test_pty_windows.py --collect-only -q -n 0 -m 'xdist_group and not windows_only'
.venv/bin/python -m pytest extensions/taut_summon/tests/test_pty_windows.py --collect-only -q -n 0 -m 'xdist_group and not posix_only'
.venv/bin/python -m pytest extensions/taut_summon/tests -v --tb=short -m 'not xdist_group and not windows_only' -n auto --dist load
.venv/bin/python -m pytest extensions/taut_summon/tests -v --tb=short -m 'xdist_group and not requires_live_harness and not requires_local_llm and not windows_only' -n auto --dist load
.venv/bin/ruff check .
.venv/bin/ruff format --check taut tests bin extensions/taut_summon/taut_summon extensions/taut_summon/tests
.venv/bin/mypy extensions/taut_summon/taut_summon extensions/taut_summon/tests --config-file pyproject.toml
.venv/bin/python bin/ruff_suppression_index.py --check
.venv/bin/python bin/check-plan-status-index
.venv/bin/python bin/check-doc-paths
.venv/bin/python bin/check-dom15-fixtures
.venv/bin/python -m pytest tests/test_docs_references.py -q -n 0
git diff --check
```

CI runs the existing `.github/workflows/test.yml` `summon-process` Windows
matrix with `not posix_only` in place of `not windows_only`, using its installed
Python environment. No workflow changes or new infrastructure are needed.
On an implementation branch, require the exact commit's existing hosted jobs;
do not push an untested implementation straight to main or claim local skips
as Windows evidence. Publishing a branch/PR follows the owner's authorization.

Acceptance floors: default startup/STOP through the existing real harness;
errors keep AdapterError/DriverError containment with no user traceback;
concurrent close and canceled injection get explicit tests. Encoding/grammar,
configuration, and batch-scanning probes are not touched by this lifecycle fix.

## Rollout, Rollback, and Residual Risks

No migration, new persisted state, dependencies, or release change. Implement
the three fixes as coherent review slices on a branch; existing platform matrix
is the deployment evidence. A revert restores earlier defects, so prefer a
forward fix; if reverting, revert the corresponding tests/spec/rationale
together and document which known defect returns. Never remove the landed
AdapterError cleanup fix as incidental rollback.

Post-merge signals: Windows STOP permits the cleanup record, one graceful
signal, normal provider/descendant absence, and no invalid-handle diagnostics;
native natural exit still publishes once. Monitor the existing CI job rather
than introduce a daemon or a new telemetry system.

Residuals retained deliberately: a truly surviving child can retain a daemon
monitor and its private handle until exit; the event pump may time out without
a real exit code. No synthetic exit or force-kill policy is introduced. Older
ClosePseudoConsole can block inside the OS; this plan records that boundary
instead of promising a new cancellable native close. Reopen only with concrete
failure evidence requiring a broader ownership redesign and owner review.

## Assumptions and Open Questions

Implementer owns checking the native Windows job's OS build and fixture
readiness. This resolves platform behavior uncertainty; it is not permission
to change the product timeout. The review must verify that constructor rollback
can retire any already-started reply worker without acquiring outer-owned
handles. If it cannot, revise slice 2 before implementation.

Checked-deferred maintenance: planning-time `coalesce-check` reported 88 dated
entries, 40 after the 2026-07-14 watermark, all cues resolved. No ledger fold is
part of this product repair plan; maintenance remains a separate unit under
[DOM-14]. The index has 95 completed/superseded non-exemplar rows; a plain dated
entry scan finds 25 post-watermark entries at least 30 days old. Thresholds are
tripped; defer the independent harvest unit rather than mix it into this plan.
Do not silently amend unrelated active plans or inventory changes.

## Out of Scope

Published-child force killing, synthetic exit events, redesigning the driver's
event stream, OS-level cancellation of ClosePseudoConsole, other PTY subsystem
refactors, and changes to unrelated plans or product features. Any new failure
introduced by this plan remains in scope for correction before completion.

## Deviation Log

| Spec ref | Planned behavior | Actual behavior | Rationale | Spec proposal |
|----------|------------------|-----------------|-----------|---------------|

## Independent Review and Fresh-Eyes Gate

Use the review-eligible Claude CLI via `skills/call-agent/SKILL.md`, with
Read/Grep/Glob only, no subagents, a bounded 540-second review, captured output,
and plan-mode containment. Give it this full plan, pinned spec, implementation
note, and named source/tests. Demand existence checks first, then PASS/BLOCKED
on implementability and degradation. Prefer removing needless work. Findings
outside this delta are observations, not expansion mandates. Review each code
slice and final work independently during execution.

Author fresh-eyes checklist: actual file paths and selectors checked; new
helper identified as new; failure ownership, timeout clock, early exit, rollback,
and native-versus-fake proof boundaries explicit. Review dispositions and
verification evidence belong below; no success inferred from a prior report.

## Review Log

2026-09-15 independent Claude plan review: PASS, exit 0, `success`,
`end_turn`, terminal reason `completed`, elapsed 364.3 seconds under a
540-second bound. Invocation: `claude --safe-mode -p <full-plan-and-brief>
--permission-mode plan --tools Read,Grep,Glob --allowedTools Read,Grep,Glob
--strict-mcp-config --no-session-persistence --output-format json`, stdin
closed. No model override. Full plan embedded in the brief; source existence
checks and review of the exact proposed delta completed. Fresh liveness probe
returned `PROBE-OK # Taut Summon Specification`; inventory records the probe.

Reviewer finding text (verbatim) and author dispositions:

| ID | Severity | Reviewer finding | Disposition |
|----|----------|------------------|-------------|
| F1 | P2 | On constructor failure `backend` is None, so spawn rollback can't reach the half-built handle to retire the already-started reply worker. Plan says include this cleanup but not *where*. | Accepted: slice 2 names the constructor-local guard, resource boundary, and exception precedence. |
| F2 | P2 | Terminal `write(b"\x03")` runs outside the `_interrupting` reset and `write` reads `epoch` fresh, so a superseding interrupt could still emit an extra Ctrl-C (narrow TOCTOU). | Accepted: carry the original epoch through the actual shared write path; a separate pre-send check is insufficient. Explicit supersession test added. |
| F3 | P2 | Grace wait must be conditional on `finish_close_request` success and precede ClosePseudoConsole, but the uniform `_record_cleanup` tuple loop can't express that branch. | Accepted: split the conditional stage, retain reply-writer finish, failure aggregation, and the final state transition. Author also required drain start before the wait when events were never consumed. |
| F4 | P3 | Reusing scripted_provider's SIGINT-handler cleanup makes the proof depend on ConPTY Ctrl-C delivering a real Python SIGINT; the existing native proof deliberately avoids this via a raw-byte `msvcrt.getwch()` child. Genuine feasibility risk. | Rejected after source check: `scripted_provider.main` passes terminal bytes through `_TerminalInputParser.feed` and calls `interrupts.interrupt()` for each returned interrupt. No Python SIGINT delivery is required and no weaker fallback is allowed. |
| F5 | P3 | Replace-from anchor "On Windows it closes the owned ConPTY session" spans the L426/427 wrap; not a literal contiguous substring. | Accepted: named prose range and baseline lines explicitly. |
| F6 | P3 observation | Reusable STOP proofs are `posix_only` + `send_signal`, won't select on Windows; plan already calls for a Windows STOP case without send_signal. | Partly accepted: existing STOP proof is POSIX-marked, but unlike the adjacent SIGINT proof it uses CLI STOP and wait. Extend that exact test across platforms rather than add a duplicate. |
| F7 | P3 | `test_win32_process_structures_match_x64_abi` has no skipif and is platform-neutral; after module-wide `windows_only` removal it runs cross-platform (desirable). | Accepted confirmation: retain cross-platform ABI test; only native tests receive Windows markers. |

2026-09-15 scoped round 2: PASS on F1, F2, F3, F5, and the accepted part of F6;
exit 0, `end_turn`, terminal reason `completed`, elapsed 287.2 seconds under
the same 540-second bound and restricted invocation. The reviewer verified
constructor cleanup does not close outer-owned handles, original-epoch writes
close the supersession race, and the exact control STOP test is portable.
F4/F7 were closed by disposition and not reopened.

One round-2 finding (verbatim): "the named range also contains the
*cross-platform* sentence at `:428` — \"Direct provider exit does not bypass
either platform's descendant-retirement step.\" The replacement text re-expresses
only the Windows side". Accepted: restored that baseline sentence verbatim in
the exact delta, preserving both platforms' requirement. This is a restoration
of existing text, not a new contract. No open review findings remain.

## Execution Log

- 2026-09-15: Plan authored from current source and the cleanup commit; no
  implementation or spec promotion performed. The plan-index gate first failed
  for the missing new row, then passed after indexing. `check-doc-paths`,
  `check-dom15-fixtures`, `tests/test_docs_references.py` (12 tests), and
  `git diff --check` passed. Current non-Windows CI selector collected zero tests
  from `test_pty_windows.py` (pytest exit 5), confirming the selection defect.
- 2026-09-15: Two independent review rounds passed; dispositions above capture
  every finding. Fresh-eyes check preserved the POSIX direct-exit contract in
  the exact delta. Planning/call-agent skills were evaluated: no skill or
  runbook amendment is needed for this task; source-first disposition handled
  the reviewer's mistaken SIGINT premise. Final doc gates are rerun after this
  review record. No runtime or spec-promotion evidence is claimed.
- 2026-09-15: Implemented the promoted contract in the worktree. The exit
  monitor owns a duplicated process handle; cancellation keeps the active
  thread handle valid and carries the owning epoch through Ctrl-C publication;
  close starts drainage, observes the five-second graceful interval, and
  continues every cleanup stage after failures. Portable fake tests are no
  longer hidden by a module-wide Windows marker. The public STOP regression is
  cross-platform, and a native ConPTY graceful-cleanup proof is selected only
  on Windows.
- 2026-09-15: Final local evidence: focused Windows PTY module `28 passed, 6
  skipped`; non-Windows collection selected 29 tests from that module; public
  STOP regression passed; unit lane `308 passed`; process lane `300 passed, 3
  skipped`; Ruff check and format, mypy (45 files), suppression index, plan
  index, doc paths, DOM-15 fixtures, 12 documentation-reference tests, and
  `git diff --check` passed. Three scoped implementation review rounds ended
  PASS after constructor rollback, drain-start failure continuation, native
  provider-absence, epoch-race, and graceful-boundary coverage were tightened.
  Hosted Windows evidence remained pending until the owner explicitly deferred
  it to the next push.
- 2026-09-15: Owner authorized closure and commit with hosted Windows
  qualification deferred to the next push. The native process-lane task above
  remains unchecked as an explicit post-commit verification item, not an
  unreported local success claim.
