# CI Failure Remediation Plan

Status: Complete; `v0.5.1` published successfully from
`1ad3e346e04579cf1c3772ec54d791e05c5ebfa9`

## Goal

Correct the four failure families exposed by the v0.5.1 GitHub Actions runs:
PTY interrupt starvation, Windows installed-artifact fixture misplacement,
wall-clock-sensitive waiter-rebind proof, and the immediate-crash watcher
startup/stop race. Preserve the existing public contracts and paired-release
shape.

## Requested Outcomes

- [x] `PtyHandle.interrupt()` publishes cancellation without waiting behind an
  active normal writer, and active plus queued old-epoch writes fail.
- [x] Windows artifact fixtures place synthetic distributions in the actual
  `site-packages` directory.
- [x] The topology-rebind test proves ordering without depending on 100 ms of
  runner wall time.
- [x] A harness that dies before watcher publication cannot strand the watcher
  thread or spend one 30-second join per crash generation.
- [x] Documentation and reusable CI evidence match the corrected behavior.

## Source Documents

- `docs/specs/04-summon.md` [SUM-7.1], [SUM-7.4], [SUM-11], [SUM-12]
- `docs/specs/02-taut-core.md` [TAUT-8.5]
- `docs/implementation/05-taut-summon-architecture.md`
- `docs/implementation/04-taut-architecture.md`
- `docs/plans/2026-07-10-taut-summon-quality-remediation-plan.md`
- `docs/plans/2026-07-09-taut-reactor-safety-plan.md`
- GitHub Actions runs `29129548532`, `29129550627`, `29129549937`, and
  `29129549215`

## Spec Baseline

- `22ed4c17a4a1d04b90dd498ce25300eadda43fa9` — committed
  `docs/specs/02-taut-core.md` and `docs/specs/04-summon.md` at plan authoring.
- Plan type: implementation with spec revision. The externally observable
  adapter and driver behavior is unchanged, but [SUM-7.4]'s current statement
  that each syscall itself remains under the lifecycle lock is incompatible
  with non-starving interruption. The exact ownership mechanism is revised
  below.
- Promotion baseline: `22ed4c17a4a1d04b90dd498ce25300eadda43fa9`
  plus the current uncommitted worktree diff for `docs/specs/02-taut-core.md`
  and `docs/specs/04-summon.md`. Strategy B was applied atomically with code,
  reciprocal implementation documentation, and firing tests.

## Proposed Spec Delta

Promotion strategy: **B — atomic**. The spec text, reciprocal implementation
documentation, code, and firing tests land in one worktree slice after this
delta is independently reviewed. The promotion baseline will be the baseline
SHA plus the final worktree diff because the user requested implementation,
not an intermediate commit.

### `docs/specs/04-summon.md` [SUM-7.4] — replace the normal-write paragraph

> The PTY master is configured nonblocking once before concurrent publication,
> preserving unrelated flags. No writer calls `F_SETFL` afterward. Injection,
> terminal-query replies, and attach-forwarded human input serialize through
> one normal-writer primitive. Every normal-write call snapshots the current
> epoch at method entry, before waiting for serialization. Before fd I/O, it
> validates the epoch, child, and handle state under the lifecycle lock,
> registers a unique active-operation token, and duplicates the canonical
> master fd. The duplicated fd pins the same nonblocking open file description, so
> `os.write` and readiness wait run outside the lifecycle lock without risking
> numeric-fd reuse. The operation closes its duplicate in `finally`, then
> rechecks the epoch and retires its token as one lifecycle-lock action. It
> rechecks the epoch after every syscall; a published epoch mismatch outranks
> concurrent reader close and stale lower-level fd diagnostics. An attempt
> already authorized when interruption is published may transfer its current
> chunk, but cancellation published before token retirement makes the call
> report interruption and no later chunk begins. Once the token is retired,
> later cancellation applies only to later calls.
>
> Interrupt is the sole out-of-band writer. It never acquires the normal-writer
> lock: under the reentrant lifecycle lock it first registers an operation
> token, advances the epoch, and attempts to duplicate the master fd, then
> attempts Ctrl-C outside the lock when duplication succeeded. The token exists
> even when duplication fails and remains active through any SIGTERM fallback,
> so close cannot reap the child between the failed duplication or Ctrl-C
> attempt and fallback signal. Calls
> entering afterward capture the new epoch and remain valid. Close publishes
> retirement and advances the epoch atomically with acquiring its own
> close-owned duplicated-fd token. Outside the lock, the winning closer writes
> graceful Ctrl-C through that duplicate, closes it, and retires its own token.
> If close cannot duplicate the master, retirement and the epoch advance still
> commit; close registers no self-token (or retires it immediately), drains
> external tokens, and proceeds directly to escalation and reap rather than
> leaving the handle open or stuck in `closing`.
> It then waits for all other pre-retirement write/interrupt tokens to drain
> before escalation and reap; it never waits on its own token. The reader's
> existing canonical `select`/`read` and EOF-close ownership is unchanged. A
> reader-side canonical close and numeric-fd reuse cannot redirect leased
> write-side syscalls because their duplicates pin the original open file
> description. Query replies retain best-effort error reporting but use the
> same serializer, epoch checks, and operation leases.

### `docs/specs/04-summon.md` [SUM-11] — append after watcher-crash behavior

> Each watcher attempt owns a fresh stop token and captures the immutable
> harness-generation death event it serves. Foreground teardown publishes the
> attempt stop before inspecting the watcher object. After constructing and
> publishing its watcher, the owner thread checks that attempt token,
> generation death, global shutdown, and fatal control state before readiness
> registration or `run()`. A pre-publication stop therefore closes on the
> owner without entering the drive loop. Every watcher-attempt join is checked;
> a live thread after the bounded join is a fatal driver error and prevents a
> watcher rebuild or harness generation N+1.

### `docs/specs/04-summon.md` [SUM-12] — extend the firing list

> Firing tests also cover PTY same-thread signal reentry, fd-operation lease
> drain and numeric-fd reuse, deterministic queued old-epoch capture,
> cancellation priority over concurrent reader close, cancellation at final
> write-token retirement, watcher pre-publication stop, and fatal
> watcher-attempt join timeout.

## Context and Key Files

- `extensions/taut_summon/taut_summon/_pty.py`: `PtyHandle` owns PTY normal
  writer serialization, write epochs, interrupt, close, and master-fd lifetime.
  Current code holds `_lifecycle_lock` across `os.write()` and requires the
  same lock before interrupt advances `_write_epoch`, so cancellation can be
  starved by the operation it must cancel.
- `extensions/taut_summon/tests/test_pty_adapter.py`: real PTY and subprocess
  contract tests. The active-plus-queued test currently permits interrupt to
  wait behind the controlled active write, contradicting [SUM-7.4].
- `extensions/taut_summon/taut_summon/_driver.py`: `_watch_until_wake()` starts
  the watcher thread and may observe harness death before `_run_watcher()` has
  published `self._watcher`. Teardown then has no object to signal and can
  spend the 30-second join budget before the late watcher is stopped.
- `extensions/taut_summon/tests/test_driver.py`: unit lifecycle tests plus the
  real scripted-provider crash loop.
- `tests/test_reactor_artifact_compat.py`: `_make_venv()` selects
  `site.getsitepackages()[0]`; Windows returns the venv prefix before
  `Lib\\site-packages`.
- `tests/test_watcher.py`: the callback-topology test uses a real 100 ms
  deadline even though its contract is ordering, not throughput.
- `.github/workflows/test.yml` and release workflows: reuse the same matrix,
  which multiplied the same failures across tag gates. Selectors must remain
  unchanged.

Comprehension gates before implementation:

1. Why can interrupt publish a new write epoch independently of the normal
   writer while master-fd close still needs one ordered ownership path?
2. What stop signal remains observable if harness death wins the race before
   the watcher object is assigned?
3. Why does the waiter-rebind test need deterministic deadline control rather
   than a larger timeout?

## Invariants and Constraints

- Public adapter and driver interfaces do not change.
- All normal PTY writers still serialize through one path. Interrupt remains
  the only out-of-band writer.
- A normal write may finish the syscall already in progress, but it must detect
  the new epoch before another chunk or before a queued call begins.
- Interrupt and close must not write through a retired or reused fd. Fd close,
  retirement, and interrupt must have one explicit lock order with no cycle.
- A write-side syscall never uses the canonical master fd after lifecycle-lock
  validation. It uses a registered duplicated-fd lease instead. Reader-side
  canonical `select`/`read` and EOF-close ownership remain unchanged; close
  does not complete reap while pre-retirement write/interrupt tokens remain.
- Interrupt remains signal-reentry-safe and cannot wait on the normal writer.
- Later new-epoch injections remain valid while the child remains alive.
- Watcher stop intent must survive the interval before the watcher object is
  published. The owner thread still creates, drives, stops, and closes its
  persistent handles.
- Harness crash backoff, watcher rebuild budgets, control ownership, queue
  semantics, workflow selectors, and release dependency floors do not change.
- The Windows correction must strengthen fixture placement, not weaken the
  verifier's isolation guard.
- No new dependencies and no drive-by refactor.

Fatal versus best-effort:

- Failure to cancel a stale PTY write or stop a watcher generation is fatal to
  the relevant operation.
- Terminal reply writes remain best-effort, but use the same cancellation and
  fd-safety path.
- Artifact isolation mismatch remains fatal; fixture discovery failure must be
  explicit rather than falling back to the venv root.

## Hidden Couplings

- `_lifecycle_lock` currently pins master-fd identity across normal writes and
  close. Moving epoch publication must preserve reused-fd safety without
  moving normal writes outside that ownership rule.
- `_write_epoch` is sampled before `_normal_writer_lock`; this is what lets a
  queued old-epoch caller be rejected after serialization becomes available.
- `_halt_ack` is driver-global and cleared between attempts, so it remains only
  the current in-handler injection acknowledgment. A fresh per-attempt stop
  token is the durable pre-publication signal; the attempt's checked join
  prevents that token from overlapping a later attempt.
- The immediate-crash test creates three generations; a single lost startup
  stop can therefore turn into three 30-second waits and hit the 90-second
  process deadline.
- `site.getsitepackages()` ordering is platform-specific; membership in a
  `site-packages`/`dist-packages` directory is the invariant, not list index.

## Rollback and Rollout

- Each slice is independently revertible. No schema, CLI, persistence, or
  package metadata changes are involved.
- Roll back PTY synchronization and its tests together; never retain a test
  that permits interrupt starvation.
- Roll back watcher stop-intent propagation and its regression test together.
- CI rollout is the existing test and release-gate matrix. Success is the
  disappearance of the named PTY, Windows artifact, waiter-rebind, and
  crash-backoff failures on a fresh run at one commit.
- There are no one-way doors. The main operational risk is a synchronization
  regression, so focused real-process tests precede broad suites.

## Deviation Log

| Spec ref | Planned behavior | Actual behavior | Rationale | Spec proposal |
|----------|------------------|-----------------|-----------|---------------|

## Tasks

1. **RED→GREEN: publish PTY cancellation independently of normal writes.**
   - Touch `_pty.py` and `test_pty_adapter.py` only.
   - First make the controlled active-plus-queued test require `interrupt()`
     to return before the active write is released; observe RED on current
     code.
   - Replace the contradictory test that requires interrupt to wait between an
     epoch check and `os.write`. Require interrupt completion before the
     controlled syscall is released, then prove the active call reports
     interruption after its authorized chunk and the queued old-epoch call
     never writes.
   - Add lifecycle-owned duplicated-fd operation leases. The lifecycle lock is
     reentrant and guards epoch, retirement, the canonical fd, and a set of
     unique operation tokens; syscalls use duplicated fds outside the lock.
     `_normal_writer_lock` remains the sole normal serializer. Interrupt and
     close never take it.
   - Register an interrupt operation token before attempting `os.dup` and keep
     it active through Ctrl-C and SIGTERM fallback, including dup failure.
   - The winning close transition atomically acquires a close-owned duplicate,
     publishes retirement, and advances the epoch. Close writes Ctrl-C through
     that duplicate outside the lock, retires its own token, drains all other
     pre-retirement write/interrupt tokens, then escalates and reaps. It never
     waits on its own token. Dup failure still commits retirement, drains
     external tokens, and proceeds to escalation/reap. Preserve the reader's
     existing canonical fd ownership; lease rules apply to write-side
     operations.
   - Make queued old-epoch capture deterministic at the real serializer
     acquisition point; do not use sleep as proof. Make the full-queue proof
     observe real `BlockingIOError`/EAGAIN before interrupting.
   - Verify full-queue unblock, active-plus-queued cancellation, post-interrupt
     reuse, close lease drain, same-thread signal reentry, concurrent close,
     close-dup failure, and reused-fd tests.
   - Stop and re-plan if interrupt must acquire `_normal_writer_lock`, if a
     write-side syscall uses the canonical fd after lifecycle validation, if
     close reaps before external operation tokens drain, if reader ownership
     changes, or if public interfaces change.

2. **RED→GREEN: preserve watcher stop intent across pre-publication startup.**
   - Touch `_driver.py` and `test_driver.py` only.
   - Add a deterministic `_watch_until_wake()` test that blocks watcher
     construction, publishes generation death and a fresh attempt stop before
     the watcher is assigned, then releases construction. Observe RED on
     current code.
   - Give each attempt a fresh stop `Event` plus its captured generation-local
     harness-death event. After construction, publish `self._watcher`, then
     check attempt stop, captured death, shutdown, and control failure before
     readiness registration or `run()`.
   - Foreground teardown sets the attempt token before requesting stop on a
     published watcher. Check the bounded join; a still-live thread is fatal
     and prevents rebuild or generation N+1.
   - Assert the pre-publication case never registers readiness or calls
     `run()`, does not report watcher failure, and closes watcher/client on the
     owner thread. Add a checked-join-timeout firing test.
   - Re-run the immediate repeated-crash real-process test.
   - Stop and re-plan if the fix needs a second watcher supervisor, changes
     crash budgets, or moves handle close off the owner thread.

3. **RED→GREEN: make Windows site-packages selection structural.**
   - Touch `tests/test_reactor_artifact_compat.py` only.
   - First extract the current first-entry selector unchanged. Add a
     platform-independent regression where the venv prefix is first and
     `Lib/site-packages` is second; observe it return the wrong prefix, then
     GREEN by selecting the structural package directory.
   - Use the selected actual package directory in `_make_venv()` and fail
     explicitly when none exists. Do not relax `_ISOLATION_PROBE`.

4. **Remove wall-clock sensitivity from the topology-rebind proof.**
   - Touch `tests/test_watcher.py` only.
   - Keep the same ordering assertions, but replace the `taut.watcher` module's
     `time` binding with a tiny fake object whose `monotonic()` is constant.
     Do not patch `time.monotonic` on the shared stdlib module.
   - Substitute proof for RED: run the focused test repeatedly; this is a
     test-harness correction, not production behavior.

5. **Traceability, broad verification, and independent review.**
   - Update both implementation docs, spec plan backlinks, `docs/plans/README.md`,
     and `docs/lessons.md` if the final mechanism yields a reusable lesson.
   - Run focused tests after each slice, then formatting, lint, typing, core
     watcher tests, Summon process tests, artifact tests, and workflow tests.
   - Run independent review after the PTY and watcher-lifecycle slices and
     again on the complete diff. Reproduce every finding before changing code.

## Testing Plan

- Real PTY/subprocess behavior stays real in `test_pty_adapter.py`; do not mock
  PTY backpressure, fd close, or child lifecycle.
- The watcher startup regression may control construction timing, but must run
  the real thread and observable stop/exit path.
- The repeated-crash acceptance proof uses the real driver subprocess,
  scripted provider, SQLite broker, watcher, and ledger.
- The artifact fixture selector test is pure; installed-artifact and workflow
  tests remain the neighboring integration proof.
- The waiter-rebind test may control the clock only. Strategy callback,
  topology mutation, replacement, and second wait remain real in-process.

Targeted commands:

```text
uv run --no-sync pytest extensions/taut_summon/tests/test_pty_adapter.py -n 1 --dist loadgroup
uv run --no-sync pytest extensions/taut_summon/tests/test_driver.py::test_repeated_crashes_back_off_and_exit_with_reason -n 1 --dist loadgroup
uv run --no-sync pytest tests/test_reactor_artifact_compat.py tests/test_watcher.py -n 1 --dist loadgroup
```

## Verification and Gates

Final gates:

```text
uv run ruff format --check taut tests extensions/taut_summon
uv run ruff check taut tests extensions/taut_summon
uv run mypy taut tests extensions/taut_summon/taut_summon extensions/taut_summon/tests
uv run --no-sync pytest -m "not slow" -n auto --dist loadgroup
uv run --no-sync pytest extensions/taut_summon/tests -m "xdist_group and not requires_live_harness and not requires_local_llm" -n 1 --dist loadgroup
uv run --no-sync pytest tests/test_github_workflows.py tests/test_reactor_artifact_compat.py -n 1 --dist loadgroup
```

Success means all commands exit zero, no orphan process is reported, the
working-tree diff matches this plan, and fresh GitHub Actions runs no longer
show the four failure families. Any platform lane not reproducible locally is
an explicit residual risk until Actions runs.

## Independent Review Loop

- Plan review: a separate agent reads this plan, both governing specs, the
  current PTY/driver implementations, and the named tests. It challenges lock
  ordering, fd reuse, pre-publication stop, and proof determinism.
- Slice review: separate agents inspect PTY synchronization and watcher
  lifecycle without implementing.
- Final review: findings-first review of the complete diff plus verification
  evidence. Each finding is accepted, rejected with evidence, or marked out of
  scope with reasoning in `## Review Log`.

## Out of Scope

- New adapters, provider behavior, control verbs, database changes, dependency
  changes, workflow matrix changes, timeout increases, or release publication.
- General watcher architecture redesign or replacement of the existing
  `BaseReactor`/`TautWatcher` seam.
- Weakening isolation checks or treating CI-only concurrency failures as
  expected flakes.

## Review Log

| Stage | Reviewer | Finding | Resolution |
|-------|----------|---------|------------|
| Initial plan | independent overall and PTY reviewers | PTY cancellation and fd lifetime were incompatible without an explicit pinning mechanism; one existing test required the buggy wait; queued capture and full-queue setup were probabilistic; same-thread reentry and SIGTERM fallback ownership were missing. | Accepted. Proposed [SUM-7.4]/[SUM-12] delta uses duplicated-fd operation tokens, deterministic gates, fallback coverage, lease drain, and reentry/reuse tests. |
| Initial plan | independent watcher reviewer | Global `_halt_ack` and rebound `_harness_dead` are unsafe before watcher publication; joins were unchecked; direct `time.monotonic` patching would mutate the shared module. | Accepted. [SUM-11]/[SUM-12] delta adds per-attempt stop/captured death and fatal checked join; the test replaces only `taut.watcher.time`. |
| Initial plan | independent overall reviewer | Windows RED only proved a missing helper, not the bad first-entry behavior. | Accepted. Extract current selection first, observe the wrong result, then correct it structurally. |
| Revised delta | independent overall and PTY reviewers | The lease rule accidentally included reader I/O; close-owned graceful Ctrl-C and interrupt dup-failure token lifetime were underspecified. | Accepted. The delta now preserves reader ownership, registers interrupt before dup, and defines close-owned dup, self-token retirement, external-token drain, escalation, and reap ordering. |
| Revised delta, final | independent PTY reviewer | Close-owned dup failure could leave retirement/cleanup ambiguous. | Accepted. Dup failure commits retirement, creates no lasting self-token, drains external tokens, and continues to escalation/reap; a firing test is required. |
| Revised delta clearance | independent overall, PTY, and watcher reviewers | Re-review after exact delta revisions. | CLEAR. No implementation blocker remained. |
| PTY implementation slice | independent PTY reviewer | Error-returning and zero-byte syscalls could report stale fd errors before newer cancellation; dup-failure fallback, live numeric-fd reuse, signal reentry, and deterministic gates needed stronger firing proof. | Accepted red-first. State is revalidated after every syscall outcome; token lifetime, live reuse, reentry, zero-return, old-epoch, and lease-drain tests were added. Follow-up CLEAR after 50/50 PTY tests. |
| Watcher/clock implementation slice | independent overall reviewer | Frozen time needed a timeout; owner-thread cleanup, single construction, and final watcher clearing were not fully pinned. | Accepted. Added a 3-second timeout and explicit owner/construction/clear assertions. Follow-up CLEAR. |
| Final whole-diff review | independent final reviewer | Concurrent reader close could outrank an already-published cancellation, and cancellation published after the last syscall check but before token retirement could be missed. | Accepted red-first. Epoch mismatch now has priority over closed state; final epoch validation and token retirement are one lifecycle-lock action. Added deterministic firing tests for both boundaries. |
| Final whole-diff clearance | independent final reviewer | Re-review after both PTY boundary corrections and aligned docs. | CLEAR for code, tests, specs, and implementation docs. Fresh cross-platform Actions remain the post-push verification gate. |
| First release resubmission | GitHub Actions Windows 3.11-3.14 matrix | Structured-adapter lifecycle fakes implemented POSIX `send_signal()` but not the Windows `Popen.terminate()` path; the real second-SIGINT probe also assumed POSIX signal semantics. | Accepted red-first. Added an isolated Windows-branch firing test, completed the Popen fake contract, and scoped the real signal probe to POSIX. |
| Windows correction review | independent reviewer | The new dispatch proof observed only a shared signal counter and would not distinguish `terminate()` from an incorrect direct `send_signal()` call. | Accepted red-first. Added a separate terminate-call oracle; follow-up targeted pytest, Ruff, and mypy passed. |
| Second release resubmission | GitHub Actions macOS 3.13 process lane | The flood/ledger test completed its owned assertions, then its generic cleanup added an unrelated POSIX SIGINT delivery boundary and timed out once; macOS 3.14 and every Ubuntu process lane passed. | Accepted as a test-boundary correction. The flood test now uses product control STOP and still waits for clean driver exit; more than two dozen other process tests retain real SIGINT cleanup coverage. Independent follow-up review: CLEAR. |
| Third release resubmission | GitHub Actions full release matrix | Re-run after the Windows fake-contract and flood-test ownership corrections. | CLEAR. Release Gate `29136154853`, main Test `29136154502`, and main PG `29136154501` all passed; `v0.5.1` was published with wheel and source artifacts. |

## Verification Record

- `uv run --no-sync pytest extensions/taut_summon/tests/test_pty_adapter.py -n 1 --dist loadgroup -q --tb=short` — 52 passed after final-review fixes.
- `uv run --no-sync pytest extensions/taut_summon/tests/test_driver.py -n 1 --dist loadgroup -q --tb=short` — exit 0, all items passed.
- `uv run --no-sync pytest tests/test_reactor_artifact_compat.py tests/test_watcher.py -n 1 --dist loadgroup -q --tb=short` — exit 0, all 102 items passed.
- Exact Actions process selector — 169 passed in 113.24 seconds after
  final-review fixes.
- Actions extension unit selector (`not xdist_group`) — exit 0, all items passed.
- Root `not slow` suite with `-n auto --dist loadgroup` — exit 0, all selected items passed.
- Focused workflow plus artifact suite — 49 passed.
- CI-equivalent Ruff format/check — passed; 77 files already formatted.
- CI-equivalent mypy — core 47 files and Summon 28 files passed.
- `gh run list --commit 22ed4c17a4a1d04b90dd498ce25300eadda43fa9`
  reports the four original failed workflows. Fresh Actions on the replacement
  tag remain required cross-platform proof.
- Release Gate run `29134863827` passed packaging, paired artifacts, local LLM,
  lint, PG, coverage, and non-Windows unit lanes but exposed the incomplete
  Windows Popen fake contract in the Summon unit step.
- `uv run --no-sync pytest extensions/taut_summon/tests/test_scripted_adapter.py -n 1 --dist loadgroup -q --tb=short` — 22 passed after the Windows boundary correction.
- Release Gate run `29135319846` passed every Windows version, all Ubuntu
  process lanes, and macOS 3.14; only the macOS 3.13 flood test's unrelated
  signal-cleanup step timed out after its owned assertions passed.
- Updated flood test through product control STOP — 20 consecutive integrated
  runs passed; independent review confirmed the shared teardown remains covered
  and dedicated POSIX signal coverage is retained elsewhere.
- Release Gate `29136154853` — success across packaging, paired-artifact
  verification, local LLM, lint, coverage, PG 3.11/3.13/3.14, unit tests on
  Ubuntu/macOS/Windows, and the 169-test process selector on Ubuntu 3.11-3.14
  plus macOS 3.13-3.14. Both tag-stability checks and GitHub Release upload
  passed.
- Main Test `29136154502` and Test Postgres Extension `29136154501` — success.
- GitHub Release `v0.5.1` — public at
  `https://github.com/VanL/taut/releases/tag/v0.5.1`; uploaded
  `taut-0.5.1-py3-none-any.whl` and `taut-0.5.1.tar.gz`.

The TDD and hardening runbooks exposed the missing completion-boundary firing
case during final review. Their current guidance was sufficient; no reusable
skill or runbook correction is needed from this slice.

## Fresh-Eyes Review

- [x] Current owners and edit points are named.
- [x] Lock, fd, epoch, watcher-start, and deadline invariants are explicit.
- [x] Real versus controlled test seams are explicit.
- [x] Rollback, rollout, stop gates, and residual platform risk are explicit.
- [x] The public contract is preserved; the internal fd-ownership spec delta
  is exact, atomic, and independently reviewed before implementation.
