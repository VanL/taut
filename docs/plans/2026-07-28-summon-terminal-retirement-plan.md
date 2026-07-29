# Summon Terminal Retirement and Coverage Integrity Plan

Date: 2026-07-28

Class: 5+P. The change revises normative Summon lifecycle behavior and the
public `AdapterHandle` protocol, crosses signal, thread, subprocess, PTY, and
cleanup boundaries, and changes the canonical coverage aggregation gate.

Plan type: implementation with spec revision and verification-gate change.

Hardening: required. The work changes a public compatibility surface and a
background-process cleanup lifecycle.

## Goal

Give Summon one explicit terminal-retirement operation so a STOP or driver
signal sends exactly one graceful stop to a provider before bounded
escalation. Preserve reusable, nonterminal `interrupt()` semantics. Make the
canonical coverage owner reject every zero-byte or unreadable input shard
instead of silently combining an incomplete report.

## Requested Outcomes

- `AdapterHandle` distinguishes reusable turn cancellation from permanent
  handle retirement.
- One terminal retirement sends at most one graceful SIGINT or PTY Ctrl-C.
  Later bounded SIGTERM/SIGKILL escalation remains valid.
- Repeated STOP, repeated driver SIGINT, control failure, watcher unwind, and
  blocking foreground teardown cannot send another graceful stop after
  retirement has been published.
- A surviving provider remains injectable after a standalone `interrupt()`;
  no time window, successful-write heuristic, or global one-shot latch changes
  that contract.
- STOP remains responsive while injection is blocked. The signal and control
  paths request retirement without waiting or reaping; the foreground owner
  performs final close and checked joins.
- A STOP published while a provider is being spawned cannot miss the newly
  published handle.
- Stream and PTY adapters use their existing lifecycle locks and write
  cancellation machinery. No second shutdown path, cleanup thread, or new
  dependency is introduced.
- Canonical coverage aggregation fails if any downloaded shard is absent,
  zero-byte, unreadable through Coverage's public API, or skipped with a
  `CoverageWarning`.
- The spec, implementation note, repository map, changelog, tests, workflow,
  and public protocol remain aligned.

## Source Documents

Source specs:

- `docs/specs/04-summon.md` [SUM-7.1], adapter interruption, retirement,
  reentry, and close ownership.
- `docs/specs/04-summon.md` [SUM-7.4], PTY write epochs, operation leases,
  Ctrl-C delivery, escalation, reap, and master-fd ownership.
- `docs/specs/04-summon.md` [SUM-9], STOP/SIGINT responsiveness,
  release-before-ACK ordering, and fatal control failure.
- `docs/specs/04-summon.md` [SUM-10], the reusable rate-backstop interrupt.
- `docs/specs/04-summon.md` [SUM-11], generation teardown and checked pump
  ownership.
- `docs/specs/04-summon.md` [SUM-12], adapter, real-process, CI, and coverage
  verification.
- `docs/specs/01-development-documentation-operating-model.md` [DOM-5],
  [DOM-6], [DOM-10], [DOM-11], and [DOM-15].

Implementation and historical context:

- `docs/implementation/05-taut-summon-architecture.md`, especially the driver
  lane model, shutdown ordering, PTY adapter, control lifecycle, change
  guidance, verification topology, and related plans.
- `docs/implementation/02-repository-map.md`, coverage-tool ownership.
- `docs/plans/2026-07-10-taut-summon-quality-remediation-plan.md`, the adapter
  interrupt/close contract and reentry proof.
- `docs/plans/2026-07-13-summon-stop-release-race-plan.md`, the previous STOP
  ordering diagnosis and the duplicate interrupt/close observation.
- `docs/plans/2026-07-15-taut-0.7.1-portability-and-coverage-plan.md`, existing
  same-run coverage ownership and the earlier decision not to act on an
  unproven empty child shard.
- `docs/agent-context/runbooks/writing-plans.md`.
- `docs/agent-context/runbooks/hardening-plans.md`.
- `docs/agent-context/runbooks/testing-patterns.md`.
- `docs/agent-context/runbooks/maintaining-traceability.md`.

Task evidence:

- The investigation in this task traced one live-watcher STOP through
  `SummonDriver.request_stop()`, `_watch_until_wake()`, and adapter `close()`.
  A structured child can receive three graceful signals before shutdown
  completes; repeated driver SIGINT can add more while close waits.
- Repeated-signal probes produced zero-byte Coverage databases on every run.
  A signal forced during Coverage schema initialization produced the observed
  nonzero but schema-incomplete database. A one-signal control produced valid
  databases.
- Coverage 7.15.2 records subprocess data from `atexit`; a later SIGINT can
  interrupt `save()`. `coverage combine` warns and skips some unreadable files
  while still returning success, and a zero-byte input can be opened or
  deduplicated without a warning.

## Spec Baseline

- Baseline commit: `061476da16e336cc82f319f8007d562b855de03a`.
- Implementation-start commit: `3a1ae8e6acac228305ace41edfa98072fd82a873`.
  The intervening channel-topic commit changed none of this plan's Summon,
  workflow, coverage, or implementation-note inputs.
- Governing spec at baseline: `docs/specs/04-summon.md`.
- Plan type: implementation with spec revision.
- Promotion baseline: `3a1ae8e6acac228305ace41edfa98072fd82a873` plus
  the 2026-07-28 worktree diff to `docs/specs/04-summon.md`. The diff promotes
  [SUM-7.1], [SUM-7.4], [SUM-9], [SUM-12], and the reciprocal plan link before
  implementation code cites the revised lifecycle text.

## Current Structure and Key Files

### Public adapter contract

- `extensions/taut_summon/taut_summon/_adapter.py::AdapterHandle` is publicly
  re-exported by `taut_summon.__init__`. It currently exposes `interrupt()` as
  graceful cancellation and `close()` as bounded stop, reap, and resource
  release.
- There is no third-party adapter registry. The shipped registry is fixed, but
  the protocol remains a public compatibility surface. Update it forward;
  do not add `getattr()` fallback behavior for older handles.
- `extensions/taut_summon/taut_summon/_stream.py::StreamJsonHandle` owns the
  common lifecycle for `ScriptedHandle` and `ClaudeHandle`. Its current
  `interrupt()` sends SIGINT while any state other than `closed` is visible.
  Its current `close()` changes `open` to `closing` and sends SIGINT again
  before waiting and escalating.
- `extensions/taut_summon/taut_summon/_pty.py::PtyHandle` owns an independent
  close machine because PTY cancellation uses a write epoch, duplicated-fd
  operation leases, Ctrl-C, process-group escalation, and split reader/master
  ownership. `interrupt()` leaves the handle reusable; `close()` publishes
  retirement and sends another Ctrl-C.

### Driver ownership

- `extensions/taut_summon/taut_summon/_driver.py::request_stop()` publishes
  `_shutdown`, interrupts the current handle, and wakes the foreground.
- `_watch_until_wake()` stops the watcher, then interrupts and closes the
  adapter during shutdown.
- `_shutdown_current_generation()` interrupts again and delegates to
  `_teardown_generation()`.
- `_teardown_generation()` is already the cohesive foreground finalizer. It
  retires the generation, closes the adapter, checked-joins the pump, and
  preserves primary-error precedence.
- `_report_control_failure()` is terminal but currently uses `interrupt()`.
- `_control.py`'s rate hard breach is different: it uses `interrupt()` as a
  recoverable circuit-breaker action and must not retire the handle.
- Handle publication is one assignment after spawn. STOP publishes its event
  before reading the handle. A post-publication event recheck is enough to
  close the race; a new driver lock is not required.

### Proof boundaries

- `extensions/taut_summon/tests/test_scripted_adapter.py` has stream lifecycle
  tests. `test_interrupt_can_reenter_close_during_process_wait` currently
  expects two physical signal calls and therefore encodes the defect.
- `extensions/taut_summon/tests/test_pty_adapter.py` owns PTY write epoch,
  operation lease, fd reuse, reentry, close, and escalation proof.
- `extensions/taut_summon/tests/test_driver.py::_CountingHandle` counts method
  calls but does not model that real `close()` sends a signal. Method-count
  tests cannot be the regression's primary proof.
- `extensions/taut_summon/taut_summon/scripted_provider.py` is the shipped,
  real-subprocess anti-mocking seam. Its scenario and received-log support are
  the correct place for a deterministic slow-SIGINT-cleanup probe used through
  the real driver.
- `extensions/taut_summon/tests/conftest.py::DriverProcess` drives the real
  provider and direct driver SIGINT on POSIX. Existing control helpers drive
  correlated STOP through the real broker.

### Coverage owner

- `.github/workflows/test.yml` owns raw coverage download and aggregation.
  It currently calls `python -m coverage combine coverage-data`, which does
  not require every input shard to be usable.
- `bin/check-required-coverage-paths.py` runs after combine and verifies named
  executed lines in the aggregate. It cannot recover or detect every discarded
  raw shard.
- `tests/test_github_workflows.py` owns the workflow topology and coverage
  command contract.
- A new `bin/combine-coverage.py` should own only raw-shard integrity and the
  public Coverage combine call. Keep `check-required-coverage-paths.py`
  unchanged as the post-combine execution-path gate.

## Required Reading and Comprehension Gates

Before editing, read the current versions of:

1. `docs/specs/04-summon.md` [SUM-7.1], [SUM-7.4], [SUM-9], [SUM-10],
   [SUM-11], and [SUM-12].
2. `extensions/taut_summon/taut_summon/_adapter.py`,
   `_stream.py`, `_pty.py`, `_driver.py`, and `_control.py`.
3. `extensions/taut_summon/tests/test_scripted_adapter.py`,
   `test_pty_adapter.py`, `test_driver.py`, and `conftest.py`.
4. `.github/workflows/test.yml`, `tests/test_github_workflows.py`,
   `bin/check-required-coverage-paths.py`, and
   `tests/test_required_coverage_paths.py`.

Comprehension questions:

1. Why can `interrupt()` not become a one-shot latch until another successful
   injection? Because [SUM-7.1] makes it reusable and the [SUM-10] rate
   backstop can interrupt a provider without permanently retiring it. A later
   terminal STOP is a different lifecycle event even if no write intervenes.
2. Why must terminal state be published before the graceful signal is sent?
   A Python signal handler can reenter while the first signal or close path is
   active. Publishing retirement first makes every reentrant terminal request
   and `interrupt()` a no-op.
3. Why can the foreground not wait for pump exit before calling `close()`?
   A PTY provider may remain alive after Ctrl-C. `close()` must drive bounded
   escalation while the pump drains, then the driver checked-joins the pump.
4. Why is a driver lock unnecessary around handle publication? If publish
   happens first, a later stopper reads the handle. If stop publishes first,
   the post-publication event check sees it. Both sides call an idempotent
   nonblocking terminal request.
5. Why is aggregate line coverage not proof that every shard was saved?
   Coverage combine can skip an unreadable shard and still produce a plausible
   report from the remaining inputs.

## Proposed Spec Delta

Promotion strategy: **A, in-file text before link claims**. Promote the
normative lifecycle text and the plan backlink in
`docs/specs/04-summon.md` before implementation. Do not add implementation
mapping claims until the code, tests, and implementation note land together.

### [SUM-7.1] Adapter interface

Replace the `AdapterHandle` portion of the interface example with:

> ```python
> # AdapterHandle:
> def inject(self, text: str) -> None          # one flushed user-role event
> def events(self) -> Iterator[AdapterEvent]   # typed output stream
> def interrupt(self) -> None                  # reusable nonterminal cancel
> def request_close(self) -> None              # nonblocking terminal retirement
> def close(self) -> None                      # bounded finalize/reap/release
> # .session_id property: provider session for resume
> ```

Replace the paragraph beginning `Contract requirements on every adapter` with:

> Contract requirements on every adapter: `inject()` returns only after a
> flushed write and surfaces failures synchronously ([SUM-5.4]);
> `interrupt()`, `request_close()`, and `close()` are thread-safe and unblock
> any in-flight `inject()` ([SUM-9] depends on this to stop a stalled
> harness); `events()` must be **drained continuously by the driver**. The
> driver owns a dedicated event-pump thread for the life of the child.
> Shutdown ordering is: stop injection → request terminal close → foreground
> close drives bounded wait/escalation/reap while the pump drains → checked
> pump join → ownership-checked release. An undrained stream is a child-stdout
> deadlock; waiting for pump exit before close is not valid because a provider
> may remain alive after its graceful interrupt.

Replace the paragraph beginning `` `emits_session_events` declares`` with:

> `emits_session_events` declares whether startup may wait for a
> `SessionEvent`; adapters that declare false never pay that wait.
> `interrupt()` is a reusable, nonterminal cancellation operation. It aborts
> adapter writes already in flight but leaves the handle open; if the provider
> survives, later `inject()` and later `interrupt()` calls remain valid.
>
> `request_close()` is the nonblocking terminal-retirement operation. Under
> the handle's reentrant lifecycle lock it atomically changes `open` to
> `close_requested`, permanently rejects or cancels injection, and owns the
> retirement's one graceful SIGINT or PTY Ctrl-C. It does not wait, escalate,
> reap, join, or release streams. After `close_requested` is visible,
> `interrupt()` and repeated `request_close()` calls are no-ops and cannot
> deliver another graceful signal.
>
> `close()` is the blocking finalizer. A direct close first performs the same
> terminal request when the handle is still open. Exactly one closer changes
> `close_requested` to `closing`, waits within the existing bounds, escalates
> when required, reaps the child, and releases streams or fds. It does not send
> another graceful signal after a terminal request. Concurrent closers wait
> for and observe the same terminal result. `interrupt()` and
> `request_close()` may reenter from a Python signal handler at any point in
> close and must not wait on a non-reentrant lock owned by the interrupted
> frame.

### [SUM-7.4] PTY terminal retirement

Replace the `Master fd ownership` paragraph with:

> **Master fd ownership.** `request_close()` publishes retirement and attempts
> the one graceful Ctrl-C; `close()` then drives the existing bounded
> SIGTERM/SIGKILL escalation, reaps the child, and closes the master iff no
> reader has started. If a reader has started, the reader closes the master on
> EOF/EIO. The reader sets `_reader_started` under the lifecycle lock as its
> first action and checks `_master_closed` before its first read. Any `OSError`
> on master read is end-of-stream, so a close-before-first-read `EBADF`
> produces the normal single `ExitEvent`. Direct `handle.close()` first
> requests retirement, so exceptions in the universal
> `spawn → pump-started` span cannot leak a master fd or zombie.

Replace the paragraphs beginning `Interrupt is the sole out-of-band writer`
and `Close publishes retirement` with:

> Interrupt and terminal-close request are the two out-of-band writers.
> Neither acquires the normal-writer lock. `interrupt()` registers an
> operation token, advances the write epoch, duplicates the master fd, and
> attempts Ctrl-C outside the lifecycle lock. Failed duplication or Ctrl-C may
> use the existing SIGTERM fallback while the operation token remains live.
> The handle stays open, so calls entering afterward capture the new epoch and
> remain valid.
>
> `request_close()` changes `open` to `close_requested`, publishes `_retired`,
> advances the epoch, and acquires its close-request duplicated-fd operation
> token as one lifecycle-lock transition. The winning request attempts the
> one graceful Ctrl-C outside the lock, closes the duplicate, and retires its
> token. Failed duplication still commits retirement and may use the existing
> signal fallback; no later close request or interrupt sends another graceful
> Ctrl-C.
>
> `close()` first ensures retirement was requested, then the winning closer
> changes `close_requested` to `closing`, drains every external operation,
> performs bounded escalation and reap, and publishes the terminal result.
> It never waits on its own close-request token and never repeats the graceful
> Ctrl-C. The reader's canonical select/read and EOF-close ownership remains
> unchanged. Concurrent close, reader-side close, and numeric-fd reuse cannot
> redirect leased write-side syscalls because their duplicates pin the
> original open file description.

### [SUM-9] Control and signal ownership

Replace the blocked-injection paragraph in the control-plane introduction
with:

> Control must stay responsive while injection is blocked on a stalled
> harness. STOP's signal/control path calls nonblocking
> `AdapterHandle.request_close()`, which publishes permanent retirement and
> unblocks any in-flight `inject()` under [SUM-7.1]. The foreground generation
> owner alone calls blocking `close()`, checked-joins the event pump, and
> publishes teardown before release. A stuck harness can therefore always be
> stopped without making a signal handler or control thread own reap or join.

Replace the unexpected-control-loop and STOP paragraphs with:

> Unexpected control-loop exit is a first-class driver failure. The control
> thread reports the failure to the foreground supervisor, requests terminal
> close on the current adapter, stops the chat watcher, releases the driver
> claim after foreground teardown, and exits nonzero. It must never leave a
> live harness without STOP/STATUS/PING, and it must not spend watcher-rebuild
> or harness-crash retry budgets. Expected STOP and driver shutdown remain
> clean exits and preserve release-before-ACK ordering.
>
> `taut-summon stop NAME` writes STOP. The driver first publishes shutdown,
> requests terminal close on the currently published adapter, and wakes the
> foreground. Watcher coordination only stops and joins the watcher; it does
> not finalize the adapter. Foreground generation teardown calls `close()`,
> checked-joins the pump, posts nothing on the member's behalf, updates the
> ledger, and exits 0. SIGINT to the driver uses the same path. If shutdown or
> fatal control failure was published while spawn was returning, handle
> publication rechecks those events and requests close on that exact handle.

### [SUM-12] Verification

Add the following verification paragraph after the adapter lifecycle firing
tests:

> Terminal-retirement conformance observes the child boundary, not only handle
> method counts. Stream and PTY tests prove `request_close()` is nonblocking,
> publishes retirement before signaling, cancels active and queued writes,
> refuses later injection, is idempotent under repeated requests and
> signal-handler reentry, and composes with direct and concurrent `close()`
> while delivering one graceful SIGINT or Ctrl-C for that retirement.
> Separate tests preserve reusable `interrupt()` and inject-after-interrupt.
> Real scripted-provider process tests make the first SIGINT enter an
> observable, bounded cleanup gate and record every reentrant signal;
> correlated control STOP and direct driver SIGINT each record one graceful
> signal and exit cleanly. The assertion counts signals after cleanup rather
> than waiting for a target count.
>
> Canonical coverage aggregation validates every downloaded raw shard before
> combine. No shard may be missing, zero-byte, or unreadable through Coverage's
> public data API, and any `CoverageWarning` during combine is fatal.
> Aggregation does not delete or filter invalid evidence, require every valid
> shard to contain project lines, depend on Coverage's private schema, or
> replace the existing required-execution-path gate.

### Related Plans

Add:

> - `docs/plans/2026-07-28-summon-terminal-retirement-plan.md`:
>   separates reusable adapter interruption from one-signal terminal
>   retirement and makes invalid raw coverage shards fatal.

## Invariants and Constraints

- `interrupt()` remains reusable and nonterminal while the handle is open.
  Do not debounce it by time, suppress it until a later successful injection,
  or make it a permanent poison latch.
- One terminal retirement owns one graceful SIGINT or Ctrl-C. Bounded
  SIGTERM/SIGKILL escalation after the grace period is not a duplicate
  graceful signal.
- Publish `close_requested` and permanent write retirement before attempting
  the graceful signal. Signal-handler reentry must observe the new state.
- `request_close()` may duplicate an fd, perform one nonblocking write, or
  signal a process, but it must not wait for a child, drain operations, join a
  thread, reap, or release shared streams.
- A direct `close()` on an open handle remains sufficient cleanup. It invokes
  the terminal-request phase internally before finalization.
- One close owner performs wait, escalation, reap, and resource release.
  Concurrent close callers observe the same final error.
- Stream and PTY lifecycle machines remain separate. Reuse their existing
  locks and resource rules; do not introduce a generic lifecycle base class.
- PTY retirement changes `_close_state`, `_retired`, and `_write_epoch`
  together under the existing reentrant condition lock. Do not create another
  unsynchronized retirement flag.
- Stream retirement uses the existing condition/RLock and inject-open checks.
  Do not take the injection serialization lock on the terminal path.
- Signal/control owners request close only. The foreground driver owns
  blocking finalization. The watcher owns only watcher stop/join. The pump owns
  only event drain.
- `_teardown_generation()` stays the single driver finalization seam and
  retains primary-exception precedence, shutdown-error publication, generation
  retirement, and checked pump join.
- STOP-before-handle-publication uses the event/publication handshake. Do not
  add a driver lock or call adapter signaling while holding the generation
  lock unless a reproduced race proves the handshake insufficient.
- Fatal control failure is terminal and uses `request_close()`. The [SUM-10]
  hard rate breach remains recoverable and uses `interrupt()`.
- Release-before-ACK, cursor lag, generation fencing, crash/resume budgets,
  control correlation, and ledger ownership do not change.
- Invalid raw coverage evidence is fatal. Do not delete, ignore, hash-filter,
  or silently replace a bad shard.
- A valid Coverage database with no measured project lines remains valid.
  Required line execution remains the separate
  `check-required-coverage-paths.py` contract.
- Use Coverage's public API and `CoverageWarning`. Do not inspect private table
  names, database sizes beyond the zero-byte check, host-specific filename
  suffixes, or pin Coverage to its current implementation.
- No new dependency, timeout increase, scheduler change, xdist worker-count
  change, release action, storage/schema change, or unrelated refactor.
- Preserve unrelated work already present in the worktree. Stage and commit by
  explicit file list only when the user authorizes landing.

## Hidden Couplings and Failure Priorities

- The same external action reaches multiple driver checkpoints. Idempotence
  belongs to the handle's terminal state, but duplicate driver ownership
  should still be removed so ownership remains intelligible.
- `request_stop()` runs from Python signal context and the control thread. It
  cannot call blocking close or wait for a helper thread.
- Stream `close()` currently sends its graceful signal while changing state.
  Splitting that code must retain same-thread RLock reentry and one terminal
  result for concurrent closers. Keep structured-stream signal dispatch inside
  the reentrant lifecycle-lock transition so a concurrent finalizer cannot
  overtake the graceful request.
- PTY close owns a duplicated-fd token so canonical-fd closure or numeric reuse
  cannot redirect Ctrl-C. The new request phase must retain that lease until
  graceful delivery or fallback completes; foreground close must drain it
  before reap.
- The pump can terminate only after the child exits. PTY Ctrl-C can leave the
  child alive, so close and pump drain proceed concurrently; checked pump join
  follows close.
- A handle can be spawned after stop intent but before publication. The
  publish-then-recheck handshake and stop-set-then-read ordering are a pair;
  changing either side requires a new race proof.
- `scripted_provider.py` is shipped because downstream conformance users rely
  on its real process boundary. Its slow-SIGINT scenario must be opt-in,
  deterministic, and inert in all existing scenarios.
- Coverage subprocess patching runs `atexit` in provider and CLI children.
  A clean provider exit is part of coverage correctness, but tests must assert
  physical signal count directly rather than rely on Coverage timing.
- Coverage combine can mutate or remove inputs. The integrity owner must
  enumerate and validate all candidates before combine and keep inputs when a
  failure occurs so diagnostics name the offending path.

Failure priority:

1. Retirement state publication and write cancellation must commit even if
   graceful signal delivery races an already-exited child.
2. Expected process-exit signal races remain best-effort and do not mask
   teardown.
3. Failure to reap or release resources remains a fatal `AdapterError`, keeps
   primary-error precedence, and blocks STOP ACK.
4. Watcher diagnostics and cleanup notes remain secondary to the foreground
   teardown result.
5. Any invalid coverage shard or combine warning is a fatal CI evidence
   failure even when the remaining aggregate would meet coverage expectations.

## Rollout, Rollback, and One-Way Doors

Rollout order:

1. Review this plan and exact spec delta.
2. Promote the spec text with strategy A and record the promotion baseline.
3. Add the deterministic real-process red regression and adapter state-machine
   red tests.
4. Implement the public protocol and both shipped adapter families.
5. Reassign driver terminal ownership and prove publication races.
6. Add the coverage integrity owner and workflow wiring.
7. Align implementation docs, repository map, changelog, and traceability.
8. Run slice review, full gates, completed-work review, and the +P pre-landing
   review.

Land the product fix and coverage gate together. Landing only the gate can
turn the already-known lifecycle defect into intermittent main-branch CI
failure; landing only the product fix leaves aggregate evidence able to hide a
future recurrence.

Rollback before release is one coordinated revert of the spec, protocol,
adapters, driver, tests, workflow, tooling, and docs. There is no storage
migration or durable data rollback.

The public `AdapterHandle.request_close()` method is a one-way compatibility
door once published. This plan does not perform a release or version bump. Do
not publish a package until all shipped adapters, protocol-shaped test fakes,
installed-wheel proof, and documentation agree. After publication, do not
remove the method as a rollback shortcut; retain the public surface and issue a
follow-up patch if implementation correction is required.

Post-deploy success signals:

- The next canonical `Test` workflow has no zero-byte or unreadable raw shard
  and no Coverage warning.
- The aggregate job reports that every input shard validated before combine
  and the existing required-path gate still passes.
- Summon process lanes complete control STOP and driver SIGINT cases without a
  second provider signal or invalid coverage artifact.
- No increase appears in STOP timeout, unreaped-child, pump-join, or
  release-before-ACK failures.

## Tasks

1. **Complete independent plan and spec-delta review.**
   - Reviewer: Claude Opus through the repository's read-only `claude -p`
     procedure.
   - Inputs: this plan, the baseline spec, implementation note, adapter
     protocol, stream/PTY implementations, driver call sites, relevant tests,
     workflow, and coverage checker.
   - Review stance: errors, bad ideas, lifecycle gaps, weak proof,
     compatibility risks, and performative overengineering.
   - Done signal: PASS and a disposition row for every finding.
   - Stop gate: do not promote the spec or write code while the reviewer says a
     zero-context implementer could not implement the state machine safely.

2. **Promote the reviewed spec delta.**
   - Files: `docs/specs/04-summon.md`,
     `docs/plans/2026-07-28-summon-terminal-retirement-plan.md`.
   - Apply strategy A text without premature implementation mapping claims.
   - Add the Related Plans backlink.
   - Record the promotion baseline identifier in this plan.
   - Verify the spec codes and links with the documentation reference gates.
   - Done signal: the active spec is the single lifecycle contract before code
     cites the revised sections.
   - Stop gate: if review changes whether interruption is reusable, who owns
     reap, or whether terminal retirement is public, revise and re-review the
     delta before promotion.

3. **Build the deterministic red proof at the child boundary.**
   - Files:
     `extensions/taut_summon/taut_summon/scripted_provider.py`,
     `extensions/taut_summon/tests/test_driver.py`,
     `extensions/taut_summon/tests/test_conformance.py` only if the shared
     conformance contract is the narrower owner.
   - Extend the scripted scenario with an opt-in SIGINT cleanup mode. The
     provider records `provider-ready`, then records every SIGINT as
     `signal=SIGINT,count=N`. The first handler publishes
     `first-signal-entered` and waits on one cleanup-release event with a
     configured upper bound. A reentrant handler records its count and
     releases that event; a watchdog releases the same event at the bound when
     no reentrant signal arrives. The provider then exits normally. The
     handler must not call `sleep()`, wait for a target count in the test
     process, or use repeated polling as the assertion.
   - First prove the test fixture itself records one and two signals when
     driven directly.
   - Through the real provider, real driver, real SQLite control queue, and
     received log, add separate cases for correlated control STOP and POSIX
     driver SIGINT. Each requires one signal, clean provider cleanup, driver
     exit 0, and released ledger evidence.
   - Observe both regressions fail on the baseline because the completed
     received log contains `count > 1`. Do not assert an exact baseline count:
     the current paths can race between two and four graceful-signal attempts.
     GREEN requires `count == 1`, prompt normal provider cleanup, driver exit
     0, and released ledger evidence. Keep the red output and elapsed bound in
     the execution log before implementation.
   - Do not use sleep repetition as the proof. Use `provider-ready`,
     `first-signal-entered`, and `cleanup-release` evidence. Run a bounded
     repeat only as robustness evidence after the single-run state proof
     passes; repetition is not the proof.
   - Done signal: deterministic RED through the production driver/provider
     boundary.
   - Stop gate: if the failure appears only under Coverage timing or repeated
     stress, the barrier is wrong; stop and repair the proof before coding.

4. **Specify the terminal state machine with adapter unit tests, then update
   the public protocol and structured stream handle.**
   - Files:
     `extensions/taut_summon/taut_summon/_adapter.py`,
     `extensions/taut_summon/taut_summon/_stream.py`,
     `extensions/taut_summon/tests/test_scripted_adapter.py`,
     `extensions/taut_summon/tests/test_claude_adapter.py` only where inherited
     behavior needs an explicit registry proof, and protocol-shaped fakes found
     by repository-wide `AdapterHandle`/`interrupt`/`close` search.
   - Add `request_close()` to `AdapterHandle`; do not add a compatibility
     fallback or overload `interrupt()` with terminal semantics.
   - Extend the existing stream lifecycle state to
     `open → close_requested → closing → closed`.
   - `request_close()` publishes `close_requested` before the one signal and
     sends under the existing reentrant lifecycle lock so close cannot
     overtake it. It returns without process wait or stream release.
   - `interrupt()` sends only while state is `open`.
   - `close()` invokes the request phase when open, claims finalization once,
     and never signals from `close_requested` or `closing`.
   - Add firing tests for direct close, request then close, repeated request,
     interrupt reentry during request/close, concurrent close, signal-delivery
     exit race, final-error sharing, inject refusal after request, active and
     queued inject cancellation, Windows terminate once, and post-interrupt
     injection reuse.
   - Change the existing reentry test that expects two signals to assert one
     terminal signal without weakening its no-deadlock proof.
   - Run mypy over production and test code so every structural fake is
     updated. The gate is repository-wide search plus a clean mypy result for
     the full `AdapterHandle` protocol and every protocol-shaped fake; missing
     `request_close()` implementations are failures, not optional cleanup.
   - Done signal: focused stream tests GREEN while the real driver regression
     remains RED until driver ownership changes.
   - Stop gate: if the implementation needs an interrupt epoch or time-based
     debounce, stop. That indicates terminal and reusable cancellation are
     being conflated.

5. **Implement the PTY terminal request using existing fd leases.**
   - Files:
     `extensions/taut_summon/taut_summon/_pty.py`,
     `extensions/taut_summon/tests/test_pty_adapter.py`.
   - Split the current close-owned graceful-write phase into
     `request_close()`. Under the existing condition/RLock, commit
     `close_requested`, `_retired`, epoch advance, and the close-request
     operation lease before fd I/O.
   - Outside the lock, attempt one Ctrl-C on the duplicated fd, preserve the
     current SIGTERM fallback on immediate write/dup failure, close the
     duplicate, and retire the operation token.
   - Make `close()` ensure a request exists, claim finalization, drain external
     operations including an in-progress request, then use the existing reap
     and master ownership paths.
   - Add tests for one Ctrl-C across repeated request/interrupt/close reentry,
     active plus queued old-epoch cancellation, request/close dup failure,
     canonical-fd close and numeric reuse, direct close, concurrent close,
     SIGTERM/SIGKILL escalation, reader-first and close-first master ownership,
     and inject-after-standalone-interrupt reuse.
   - Done signal: the existing PTY matrix plus new state tests are GREEN.
   - Stop gate: do not weaken operation-lease drain, add a blocking write, or
     merge PTY and stream close code to reduce duplication.

6. **Give terminal lifecycle actions one driver owner each.**
   - Files:
     `extensions/taut_summon/taut_summon/_driver.py`,
     `extensions/taut_summon/tests/test_driver.py`,
     `extensions/taut_summon/tests/test_interaction.py` where existing attach
     STOP assertions need the new fake surface.
   - `request_stop()`: set `_shutdown`, snapshot the published handle, call
     `request_close()` best-effort, then wake.
   - After `self._handle = handle`, recheck `_shutdown` and `_control_failed`;
     request close on that handle if either is already set. Do not add a new
     driver lock for this handshake.
   - `_report_control_failure()`: use `request_close()`.
   - `_watch_until_wake()`: publish watcher halt, request watcher stop, and
     checked-join the watcher. Remove adapter interrupt and close calls.
   - `_shutdown_current_generation()`: remove its explicit interrupt and
     delegate to `_teardown_generation()`.
   - `_teardown_generation()`: remain the only blocking finalizer through
     `handle.close()` and checked pump join.
   - Keep `_control.py`'s rate hard-breach call on `interrupt()`.
   - Update driver fakes to model `request_close()` explicitly. Use call counts
     only for ownership-unit tests; the real provider log remains the physical
     signal proof.
   - Add deterministic tests for stop before handle publication, stop after
     publication, repeated request_stop during close, fatal control failure,
     live watcher shutdown, pre-watch orientation STOP, attach STOP, blocked
     inject, and close/pump failure precedence.
   - Done signal: both real driver signal-count regressions turn GREEN; STOP
     ACK, cursor lag, and teardown failure tests remain GREEN.
   - Stop gate: if watcher code still blocks in `handle.close()` or any signal
     path joins/reaps, stop and restore foreground ownership.

7. **Make every raw coverage shard required evidence.**
   - Files:
     `bin/combine-coverage.py` (new),
     `tests/test_combine_coverage.py` (new),
     `.github/workflows/test.yml`,
     `tests/test_github_workflows.py`,
     `docs/implementation/02-repository-map.md`.
   - Give the script a small CLI: input directory and optional output data-file
     path. CI uses `coverage-data` as input and repository `.coverage` as
     output.
   - Before Coverage opens any input, recursively enumerate the directory's
     regular files. Fail with path-specific diagnostics if the set is empty or
     any file is zero-byte.
   - Read each candidate through public `CoverageData`; a valid data file with
     no project lines passes. Any unreadable file fails before combine.
   - Run public `Coverage.combine(..., strict=True, keep=True)` with
     `CoverageWarning` promoted to an error, then save the requested aggregate.
     Do not reproduce Coverage's merge logic.
   - Replace only the workflow's direct combine command. Keep artifact
     producers, names, selectors, worker counts, reports, Codecov behavior,
     and `check-required-coverage-paths.py`.
   - Red-first tests: zero-byte shard, unreadable nonzero shard, no shards, and
     a forced `CoverageWarning` all fail. Public-API-generated valid shards,
     including a valid empty shard, combine successfully and emit zero
     promoted `CoverageWarning`s. A workflow test requires the checked
     combiner and forbids the unchecked direct command.
   - Done signal: focused checker/workflow tests GREEN and the observed invalid
     shard shapes fail before aggregate reporting.
   - Stop gate: if the checker needs private Coverage tables, suffix parsing,
     a minimum measurement count, or deletion of a bad file, stop and redesign
     around the public API.

8. **Align durable documentation and traceability.**
   - Files:
     `docs/implementation/05-taut-summon-architecture.md`,
     `docs/implementation/02-repository-map.md`,
     `CHANGELOG.md`,
     `docs/specs/04-summon.md`,
     this plan, and `docs/plans/README.md`.
   - Replace the old `interrupt → pump drains → close` architecture wording
     with the terminal-request/finalizer ownership and state machine.
   - Update PTY and stream close guidance, driver lane ownership, testing
     boundary, and coverage owner. Do not narrate line-by-line code.
   - Add reciprocal implementation mapping/backlinks now that code and tests
     exist.
   - Add an unreleased changelog entry only if the repository has opened the
     next release section. Do not rewrite or append to an already-published
     version heading and do not choose a release version in this plan.
   - Add a dated lesson only if implementation reveals a reusable rule not
     already covered by the 2026-07-12 signal-handler lesson and the
     2026-07-10 cancellation-epoch lesson.
   - Evaluate the planning, hardening, testing, and call-agent guidance for a
     concrete omission; record no change when they already covered the work.
   - Done signal: zero-error documentation references, correct plan index, and
     closed spec-plan-implementation-code chain.
   - Stop gate: if documentation would claim release or version state not
     created by this work, omit that claim.

9. **Run slice and completion reviews.**
   - After Tasks 3-6 form one coherent product slice, use Grok read-only to
     review the promoted spec, adapter states, driver ownership, real signal
     proof, and regressions.
   - After Tasks 7-8 and all gates, use Claude Opus read-only for completed-work
     review and the Class +P pre-landing review.
   - Reproduce every finding before changing work. Record accepted, rejected,
     and out-of-scope dispositions below. Round two reviews only accepted
     finding IDs and their fixes.
   - Done signal: no unresolved blocker and no undispositioned finding.

10. **Run final verification from the current state.**
    - Run the focused red/green commands first, then the full Summon unit and
      two-worker process selectors, static checks, documentation gates, and
      local coverage-shard proof.
    - Record command, result, changed files, observed behavior, rollback
      validity, post-deploy pending state, and residual risk.
    - Inspect `git diff` for unrelated files and stage only the plan-owned file
      list if the user later authorizes a commit.
    - Done signal: every requested outcome has current rerun evidence and the
      completed work is independently reviewed.

## Testing Plan

### Required red evidence

- A real structured provider records a second SIGINT during first-signal
  cleanup on the baseline driver. The test asserts `count > 1`, not an exact
  duplicate count. The provider-ready, first-signal-entered, and bounded
  cleanup-release events make the failure deterministic; repetition is only a
  later robustness check.
- Proposed `request_close()` stream and PTY contract tests fail before the
  method and state exist.
- The coverage combiner tests prove the current unchecked path accepts at
  least one invalid-input shape before the checked owner is installed.
- Record the exact failing assertion and baseline commit in the execution log.

### Product contract tests

- Stream lifecycle:
  `extensions/taut_summon/tests/test_scripted_adapter.py`.
- PTY lifecycle:
  `extensions/taut_summon/tests/test_pty_adapter.py`.
- Driver ownership, publication, control failure, blocked injection, and real
  process:
  `extensions/taut_summon/tests/test_driver.py`,
  `test_conformance.py`, and `test_interaction.py`.
- Registry/inheritance:
  the existing adapter registry and Claude structured-handle tests.

The primary regression must keep the following real:

- provider subprocess
- OS signal delivery on POSIX
- structured pipes
- SQLite and SimpleBroker control queue for correlated STOP
- driver foreground, control, watcher, and pump threads
- received-log process boundary

Mocks/fakes are allowed only for:

- deterministic Popen error and Windows branch coverage
- a controlled Coverage API warning
- driver method-ownership units after the real physical-signal test exists
- clock-free barriers and events that expose a state transition

Do not mock adapter `close()` in the only test claimed to prove signal count.

### Coverage gate tests

- `tests/test_combine_coverage.py` invokes the new public script surface.
- Valid shards are generated through Coverage's public data API.
- The valid-empty-shard case asserts successful combine and zero promoted
  `CoverageWarning`s.
- Zero and arbitrary unreadable bytes are permitted only as negative fixtures.
- One unit test may substitute the external `Coverage.combine` call solely to
  emit `CoverageWarning`; it must not substitute shard enumeration or
  validation.
- `tests/test_github_workflows.py` proves the canonical aggregate uses the
  checked owner without adding tests to the aggregation job.
- `tests/test_required_coverage_paths.py` remains the post-combine marker proof.

## Verification and Gates

Per-task focused commands:

```bash
uv run --project extensions/taut_summon --extra dev pytest \
  extensions/taut_summon/tests/test_scripted_adapter.py -n 0
uv run --project extensions/taut_summon --extra dev pytest \
  extensions/taut_summon/tests/test_pty_adapter.py -n 0
uv run --project extensions/taut_summon --extra dev pytest \
  extensions/taut_summon/tests/test_driver.py \
  extensions/taut_summon/tests/test_conformance.py \
  extensions/taut_summon/tests/test_interaction.py \
  -k "terminal_close or signal_cleanup or blocked_inject or control_failure or attach" \
  -n 0
uv run --extra dev pytest \
  tests/test_combine_coverage.py tests/test_github_workflows.py \
  tests/test_required_coverage_paths.py -n 0
```

Static and documentation gates:

```bash
uv run --extra dev ruff check \
  extensions/taut_summon/taut_summon \
  extensions/taut_summon/tests \
  bin tests/test_combine_coverage.py tests/test_github_workflows.py
uv run --extra dev ruff format --check \
  extensions/taut_summon/taut_summon \
  extensions/taut_summon/tests \
  bin tests/test_combine_coverage.py tests/test_github_workflows.py
uv run --extra dev mypy \
  extensions/taut_summon/taut_summon \
  extensions/taut_summon/tests \
  bin/combine-coverage.py tests/test_combine_coverage.py \
  --config-file pyproject.toml
uv run --extra dev pytest tests/test_docs_references.py -n 0
uv run --extra dev bin/check-doc-paths
bin/check-plan-status-index
bin/check-dom15-fixtures
git diff --check
```

Neighboring and final behavior gates:

```bash
uv run --project extensions/taut_summon --extra dev pytest \
  extensions/taut_summon/tests -m "not xdist_group" -n 0
uv run --project extensions/taut_summon --extra dev pytest \
  extensions/taut_summon/tests \
  -m "xdist_group and not requires_live_harness and not requires_local_llm" \
  -n 2 --dist load
uv run --extra dev pytest -m "not slow" -n 0
```

Local subprocess coverage proof:

```bash
coverage_dir="$(mktemp -d)"
COVERAGE_FILE="$coverage_dir/.coverage.summon-process" \
  uv run --extra dev python -m coverage run --parallel-mode -m pytest \
  extensions/taut_summon/tests -v --tb=short \
  -m "xdist_group and not requires_live_harness and not requires_local_llm" \
  -n 2 --dist load
uv run --extra dev python bin/combine-coverage.py \
  "$coverage_dir" --output "$coverage_dir/.coverage"
```

Success means:

- both real shutdown initiators record one graceful provider signal
- all adapter lifecycle, blocked-inject, attach, STOP ACK, pump join, and
  release tests pass
- every protocol-shaped fake type-checks with `request_close()`
- the two-worker process lane produces only readable nonzero raw shards
- the checked combiner emits no warning and the required-path gate still passes
- documentation and plan indexes report zero error

Final CI evidence after landing:

- canonical `Test` workflow all green
- raw coverage integrity step green with every downloaded input validated
- aggregate report and Codecov upload complete
- no `Couldn't use data file`, schema, or zero-byte diagnostic

## Independent Review Loop

Plan review:

- Reviewer: Claude Opus, read-only.
- Gate questions:
  1. Could a zero-context engineer implement this plan and exact delta
     confidently and correctly?
  2. Would implementation as written impair adapter reuse, signal safety,
     shutdown responsiveness, cleanup truth, compatibility, or coverage
     evidence?
- A BLOCKED verdict must trace to one of those questions.

Implementation reviews:

- Grok reviews the completed adapter/driver slice.
- Claude Opus reviews completed work and performs the +P pre-landing review.
- Each reviewer receives the promoted spec identifier, this plan, relevant
  implementation note, touched files, tests, and current verification output.
- Reviews are read-only. Findings are claims and must be reproduced.
- Round two is restricted to accepted finding IDs and their fixes.

## Out of Scope

- Redesigning the provider registry or adding third-party adapter discovery.
- A generic lifecycle base class shared by stream and PTY adapters.
- Debouncing signals by time or inferred injection episodes.
- Changing rate-backstop policy or making its interrupt terminal.
- Changing STOP protocol, ACK shape, control queues, ledger schema, cursor
  semantics, provider crash recovery, or release evidence.
- Changing timeout values, retry budgets, xdist topology, or supported OS and
  Python matrices.
- Pinning Coverage, parsing its private SQLite schema, requiring a coverage
  percentage, or requiring every shard to measure project code.
- Filtering, deleting, repairing, or fabricating coverage shards.
- Releasing packages, choosing the next version, moving tags, or publishing
  artifacts.
- Refactoring unrelated Summon, workflow, documentation, or user work.

## Stop and Re-Plan Conditions

Stop and revise this plan and proposed delta if:

- a shipped adapter cannot implement nonblocking terminal request without a
  second worker or a changed public error contract
- post-publication event recheck does not close the spawn race under a
  deterministic proof
- `request_close()` needs a time window or successful-inject rearm rule
- the PTY request phase cannot retain its fd operation lease until fallback
  signaling completes
- foreground finalization cannot remain in `_teardown_generation()`
- the real regression requires mocked process, broker, or driver boundaries
- valid Coverage data cannot be distinguished from the observed invalid forms
  through public API without private schema assumptions
- rollout requires the product fix and integrity gate to land separately
- implementation changes CLI, storage, control envelopes, or release scope

## Deviation Log

| Spec ref | Planned behavior | Actual behavior | Rationale | Spec proposal |
|----------|------------------|-----------------|-----------|---------------|

## Execution Log

| Date | Slice | Evidence | Result |
|------|-------|----------|--------|
| 2026-07-28 | Spec promotion | `git diff 061476da..3a1ae8e6 --` over every Summon/workflow/coverage input named by this plan | No affected input changed between the reviewed baseline and implementation start. |
| 2026-07-28 | Spec promotion | Worktree diff to `docs/specs/04-summon.md`; documentation reference and path gates | [SUM-7.1], [SUM-7.4], [SUM-9], [SUM-12], and Related Plans promoted before code. |
| 2026-07-28 | Scripted child boundary RED/GREEN | Direct cleanup-mode provider test first returned 130; real-driver SIGINT probe recorded signal-count entries `[1, 3, 2]` on the baseline path | The bounded handler now exits cleanly, and direct driver SIGINT plus correlated STOP each record exactly one physical graceful signal. |
| 2026-07-28 | Stream and PTY terminal retirement | The first PTY contract test failed with missing `request_close()`; focused stream and PTY suites then passed 26 and 60 tests | Both handle families now separate reusable interruption, nonblocking terminal request, and blocking finalization, including PTY fd-operation leases and fallback. |
| 2026-07-28 | Driver lifecycle | Full `test_driver.py`; focused conformance and interaction suite, 45 passed | Shutdown publication precedes close request, handle-publication races recheck terminal state, watcher shutdown owns no adapter finalization, and the foreground closes once. |
| 2026-07-28 | Coverage evidence RED/GREEN | New combiner and workflow contract tests failed while the owner script was absent and CI called Coverage directly; focused coverage/workflow/required-path suite then passed 28 tests | The canonical owner validates every raw file, promotes combine warnings, preserves inputs, and leaves required-path policy separate. |
| 2026-07-28 | Adapter/driver slice review | Grok `grok-4.5-build`, read-only review and accepted-finding round two | No blocker. GROK-1 found stale driver module wording; the wording was corrected and round two returned `RESOLVED`. |
| 2026-07-28 | Full local verification | 257-test Summon unit partition; 237-test two-worker process partition; two 1,407-test root non-slow runs with one platform skip each; Ruff, format, mypy, docs, plan, path, build gates | All completed gates passed; live external-provider and post-landing CI evidence remain rollout checks. |
| 2026-07-28 | Local raw-shard proof | Two-worker process lane under `coverage run --parallel-mode`, checked combiner, preserved raw-file inspection, driver report | 237 tests passed; every enumerated shard was nonzero and publicly readable; combine emitted no combine-phase warning; driver coverage was 91%. |
| 2026-07-28 | Completed-work and +P review | Claude Opus `claude-opus-4-8`, read-only, full plan/spec/diff/evidence | `PASS`, no findings. N1 through N3 were non-blocking observations and require no implementation change. |
| 2026-07-28 | Release-note boundary | Inspected `CHANGELOG.md` before closeout | The top section is the already released 0.8.0 record and there is no Unreleased section, so this work does not append to a published release. |
| 2026-07-28 | Targeted landing authorization | Owner requested a targeted commit after reviewing the completed implementation report | Stage only the implementation's enumerated files; post-landing CI remains the rollout evidence gate. |

## Revision Log

| Date | Baseline | Revision | Reason | Review required |
|------|----------|----------|--------|-----------------|
| 2026-07-28 | `061476da` | Initial Class 5+P plan and exact spec delta | Root-cause investigation found terminal cancellation and terminal retirement conflated, plus a false-green coverage aggregate | Claude Opus plan/delta review |
| 2026-07-28 | `061476da` | Pinned real-child cleanup synchronization, relative RED/GREEN signal counts, protocol-fake gate, and warning-free valid-empty coverage proof | Accepted OPUS-1 through OPUS-4 from the independent plan review | Claude Opus accepted-findings round two |
| 2026-07-28 | `3a1ae8e6` | Rebased implementation start and promoted the reviewed spec delta in the worktree | The intervening commit changed no plan-owned Summon or coverage input | No new review; reviewed delta is unchanged |
| 2026-07-28 | `3a1ae8e6` plus worktree spec | Implemented adapter terminal retirement, foreground-only finalization, physical-signal regression proof, and checked coverage aggregation | The RED paths reproduced both the duplicate graceful signal and the missing integrity owner | Grok adapter/driver slice review; Claude Opus completed-work review pending |
| 2026-07-28 | `3a1ae8e6` plus completed worktree | Recorded full verification and independent completed-work disposition; no code change was required by final review | Claude Opus confirmed every required review dimension and returned PASS | No round two required because the review reported no finding |

## Review Findings and Dispositions

| Review | Finding | Disposition | Plan change or rationale |
|--------|---------|-------------|--------------------------|
| Claude Opus plan/delta review (`claude-opus-4-8`, PASS) | OPUS-1: real-child RED synchronization was under-specified | accepted; round two resolved | Task 3 now names provider-ready, first-signal-entered, one bounded cleanup-release event, reentrant release, watchdog release, post-cleanup counting, and required elapsed-bound evidence. |
| Claude Opus plan/delta review (`claude-opus-4-8`, PASS) | OPUS-2: an exact baseline signal count would be brittle | accepted; round two resolved | Tasks 3 and 6 plus the testing plan require baseline `count > 1` and GREEN `count == 1`; no exact RED multiplicity is contractual. |
| Claude Opus plan/delta review (`claude-opus-4-8`, PASS) | OPUS-3: the illustrative spec protocol omits existing members, so fake completeness needs a real gate | accepted; round two resolved | Task 4 makes repository-wide structural search and clean full-surface mypy results mandatory. |
| Claude Opus plan/delta review (`claude-opus-4-8`, PASS) | OPUS-4: fatal warnings could reject healthy combines | accepted; round two resolved | Task 7 and the coverage tests require a valid empty shard to combine with zero promoted `CoverageWarning`s. |
| Claude Opus accepted-findings round two (`claude-opus-4-8`, RESOLVED) | OPUS-1 through OPUS-4 | resolved | The narrow second round found no remaining defect in any accepted ID and did not reopen plan scope. |
| Grok adapter/driver slice review (`grok-4.5-build`, no blocker) | GROK-1: `_driver.py` module header retained the old interrupt-driven shutdown order | accepted; round two resolved | The header now names request-close publication, watcher join, foreground finalization, and signal/control nonblocking limits. |
| Grok accepted-finding round two (`grok-4.5-build`, `RESOLVED`) | GROK-1 | resolved | The narrow second round found no residual defect in the accepted finding. |
| Claude Opus completed-work and +P review (`claude-opus-4-8`, PASS) | none | no action | The reviewer confirmed the state machine, signal/control boundary, publication handshake, physical signal count, PTY fd leases, reusable interrupt, public-API coverage integrity, workflow ownership, and real-process proof. |

### Claude Opus Plan and Spec-Delta Findings (Verbatim)

Verdict: `PASS`. Reviewer model: `claude-opus-4-8`. Baseline:
`061476da`.

> **OPUS-1 — RED-proof determinism is under-specified — MEDIUM.**
> `scripted_provider.py` has no signal handler today, and the "bounded
> barrier" is not concretely designed. A single external stimulus (one
> STOP/one SIGINT) is internally multiplied by the driver into ≥2 graceful
> signals on baseline yet exactly one on the fixed path. The provider must
> stay alive across the baseline cascade without tripping `close()`'s 5s
> SIGKILL, and must exit promptly on the fixed path where no second signal
> ever arrives — so a "wait for signal #2" barrier hangs on green, and a raw
> sleep is exactly what the stop-gate disclaims, yet no channel carries
> "teardown complete" back to the provider. *Why it matters:* this is the
> plan's primary anti-mocking proof of exactly-once retirement and the gate
> for Task 6; if it flakes or degrades to a 5s-per-test delay, the regression
> is untrustworthy. *Disposition (smallest):* before Task 3, pin the
> synchronization — provider records each SIGINT to the received-log and
> holds a bounded cleanup window keyed to observable state (provider-ready +
> first-signal-entered), the assertion **counts recorded signals** rather
> than waiting for a target, and both RED (>1) and GREEN (==1, prompt clean
> exit, driver exit 0) are shown timing-robust with the barrier *released*,
> not slept.
>
> **OPUS-2 — Assert relative signal count, not the exact baseline "three" —
> LOW.** The traced path yields up to *four* interrupt-sending calls (`372`,
> `1536`, `1537`, `1286`) depending on how fast the child exits and how far
> `_close_state` advanced. A `== 3` assertion is brittle against that racy
> multiplicity. *Disposition:* assert `== 1` on GREEN and `> 1` on RED;
> never pin the baseline number.
>
> **OPUS-3 — Protocol-edit completeness vs. illustrative spec example —
> LOW.** The `[SUM-7.1]` delta comment omits real members (`pid`,
> `status_fields`, `wait_until_quiet`, `mark_awaiting_onboarding`, `attach`).
> Fine as an illustration (matches baseline style), but the actual
> `_adapter.py` edit must add `request_close()` to the *full* surface and
> every protocol-shaped fake (`_CountingHandle:175`, plus any structural
> double) must gain it. *Disposition:* no spec change; treat the Task 4 mypy
> sweep as the explicit **gate** for fake completeness, not a nicety.
>
> **OPUS-4 — Confirm no benign CoverageWarning on a healthy combine — LOW.**
> Promoting `CoverageWarning` to fatal is right for the combine phase, but a
> benign warning on valid data would false-positive CI. *Disposition:* the
> Task 7 "valid empty shard combines successfully" green test should assert
> **zero** promoted warnings, catching a false-positive in unit tests before
> main.

### Claude Opus Accepted-Findings Round Two

Verbatim verdict: `RESOLVED (all four accepted findings)`.

- `OPUS-1`: `RESOLVED`
- `OPUS-2`: `RESOLVED`
- `OPUS-3`: `RESOLVED`
- `OPUS-4`: `RESOLVED`

The reviewer reported no remaining defect within the accepted-ID scope.

### Grok Adapter/Driver Slice Review

Verdict: `NO BLOCKER`. Reviewer model: `grok-4.5-build`.

> **GROK-1 — LOW.** `_driver.py`'s module header still describes shutdown as
> “adapter interrupt → pump drain → release” while the code now requests
> close and leaves blocking `close()` to the foreground. The stale wording
> could lead a later change to restore the duplicate-signal path. Refresh the
> paragraph to match the implemented ownership boundary.

Accepted-finding round-two verdict: `RESOLVED`. The reviewer found no residual
defect in GROK-1 and did not reopen the slice.

### Claude Opus Completed-Work and +P Review

Verdict: `PASS`. Reviewer model: `claude-opus-4-8`. No finding and no
accepted-finding round two.

The reviewer confirmed all nine requested dimensions: both adapter state
machines; signal/control nonblocking behavior; the two-order publication
handshake; exactly one physical graceful provider signal; PTY operation-token
and duplicated-fd safety; reusable `interrupt()` behavior; public Coverage API
validation; unchanged workflow ownership outside combine; and real
subprocess/broker/SQLite proof.

Non-blocking observations:

- `N1`: recursive validation sees every regular file while Coverage combine
  selects canonical `.coverage.*` names. Canonical CI artifacts use that
  naming, so the sets align without adding a filename policy.
- `N2`: an aggregate made only of valid empty data would fail strict combine.
  Canonical CI always has real exercised data, and the contract requires a
  valid empty shard to coexist with populated data, not to fabricate an empty
  report.
- `N3`: the scripted provider records from a SIGINT handler. That is acceptable
  only in this deterministic child-process test seam; the reentry test proves
  the intended behavior.

## Fresh-Eyes Review

Before implementation begins, confirm:

- every new state and transition has one named owner
- the proposed spec says both what `interrupt()` retains and what
  `request_close()` permanently changes
- a direct `close()` remains sufficient
- the plan never asks signal/control context to wait
- watcher and pump ownership are not conflated
- the publication handshake covers both event/assignment orders
- physical signal proof stays real
- PTY fd leases and stream pipe behavior are not forced through one abstraction
- invalid-shard policy uses public Coverage behavior
- the coverage gate does not become a percentage or per-shard-content policy
- rollout, rollback, review, traceability, and post-deploy evidence are named
- no task requires inference about files, tests, or stop conditions
