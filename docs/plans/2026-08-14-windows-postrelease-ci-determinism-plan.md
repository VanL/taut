# Windows Post-Release CI Determinism Plan

Date: 2026-08-14

Class: 5. This work crosses the TUI callback boundary and an MCP child-thread /
SQLite transaction boundary after hosted Windows exposed two independent
failures. Async and storage lifecycle hardening require a dated hardened plan.

Status: active.

Plan type: diagnosis and implementation. No product-spec revision is authorized
until a deterministic MCP reproduction identifies a contract mismatch.

## Goal

Make the two Windows failures deterministic and robust without increasing a
timeout, removing coverage, weakening an assertion, reducing parallelism, or
blindly rerunning unchanged code.

## Source Documents

- `docs/program-theory.md` [THEORY-2] and [THEORY-3]
- `docs/specs/10-taut-tui.md` [TUI-6], [TUI-7], and [TUI-10]
- `docs/specs/07-taut-mcp.md` [MCP-4], [MCP-5], and [MCP-8]
- `docs/implementation/07-taut-mcp-architecture.md`
- `docs/implementation/12-taut-tui.md`
- `docs/agent-context/runbooks/testing-patterns.md`
- `docs/agent-context/runbooks/hardening-plans.md`
- `docs/lessons.md`

## Baseline and Production Evidence

Baseline: `73b56a0d5242f5a0353ecbf8f409d4013b155088`.

- TUI run `31832783361`, Windows Python 3.13, failed only
  `workspace.initialize`. Its concrete-handler proof polled for file and
  inspector state and timed out while the exact background result callback was
  not causally observed. The other 31 handler cases and all four non-Windows
  TUI jobs passed. This is provisionally a harness synchronization defect, not
  yet a proven test-only failure: a fresh exact-callback probe must distinguish
  missed observation from application callback-delivery failure.
- MCP run `31832783363`, Windows Python 3.13, timed out the 15-second
  `test_explicit_dm_read_log_and_directory_use_public_core_contract`. The main
  thread was in a transactional SimpleBroker sidecar commit while the workspace
  owner was idle on its wake event. The same exact-SHA test passed in the prior
  release run in 3.24 seconds and 100 focused macOS repetitions pass, so Windows
  hosted execution is currently the only red feedback loop.
- Root run `31832783433` and PostgreSQL run `31832783439` passed at the
  baseline. No changed release-finalizer code is on either failing runtime path.
- MCP installed registry `simplebroker==7.3.2` from
  `extensions/taut_mcp/uv.lock`, wheel SHA-256
  `a9f59fe8d4e407b9c04ea65e057091114b347564db9657c5f750578f8bcdad0f`.
  The clean sibling `../simplebroker` is matching tag `v7.3.2`, commit
  `284059c1`; ownership may be assigned upstream only against that exact source.

## Invariants and Constraints

- The TUI observer captures the next exact `_apply_action_result` completion
  after dispatch, delegates to the real method, and sets its event regardless
  of success. It then immediately asserts an exception-free future returning
  exactly `InitResult(db=str(context.db_path), created=True)`, followed by the
  existing file and rendered inspector assertions.
- Time is only a bounded missing-callback cap for the TUI event. Wrong and
  failed results wake immediately and fail their assertions; the cap is not a
  success condition and will not be extended.
- MCP command completion must continue to mean that the owner-thread command
  and its post-command snapshot have settled before the master future resolves.
- Keep real SQLite, real `TautClient`, and the real child-thread reactor in the
  MCP reproduction. Do not mock the broker/transaction path or replace the
  external observer with reactor-owned reads.
- Do not classify the MCP failure as a test timeout until transaction and lock
  ownership prove that production work has settled. Do not classify it as an
  app bug merely from a stack sampled during a timeout.
- Preserve the full OS/Python matrices, serial MCP Windows execution, all
  assertions, and every currently exercised command.
- No timeout, busy-timeout, retry-count, or sleep increase. No automatic CI
  rerun and no ignored failure.

## Rollback, Rollout, and One-Way Doors

There is no data migration or irreversible product change. Each correction is
revertible as one commit. Hosted Windows is the rollout signal. The published
0.9.0 artifacts are immutable and are not rebuilt or retagged.

If MCP diagnosis points to SimpleBroker rather than Taut, stop before editing
the sibling repository. Record the minimal red-capable reproducer and make the
upstream ownership boundary explicit. The reproducer and report belong in the
matching `../simplebroker` checkout at tag `v7.3.2` / commit `284059c1`, but
editing or publishing that repository requires a separately authorized task.
A Taut workaround that hides an upstream transaction leak is out of scope.

## Execution Slices

1. Replace only the TUI initialization polling success condition with an exact
   callback-completion event that fires for success or failure. Assert the exact
   successful `InitResult`, then keep the final file and inspector assertions.
   If fresh Windows does not deliver the exact callback, reclassify this as an
   application failure and stop before calling the test fixed.
2. Build a red-capable MCP feedback loop. Add flushed, uniquely tagged phase
   markers around each real reactor await and external-observer operation in
   the failing test. Commit that diagnostic-only change on an intermediate
   branch, push the exact ref, and run a fresh `workflow_dispatch` or PR MCP
   workflow against it. This is changed diagnostic code, not an unchanged
   failed-attempt rerun. Use the last phase plus the real timeout stacks to
   minimize to an event-controlled real SQLite / real reactor case. Remove all
   tagged instrumentation before the final commit.
3. Generate three to five falsifiable MCP hypotheses only after the loop is
   red. Distinguish an owner-thread open transaction, observer cleanup/close,
   command-future premature settlement, and upstream SQLite retry/lock behavior.
4. Add the narrow regression first, apply the owner-correct fix, and rerun the
   original hosted scenario. Stop and revise this plan before any normative
   product-spec change.
5. Run full TUI and MCP suites, repository-wide Ruff, all five mypy lanes, doc
   checks, and diff checks. Obtain independent implementation review, commit,
   push, and require fresh Windows success without rerunning a failed attempt.

## Stop Gates and Out of Scope

- Stop if the exact TUI callback is absent on fresh Windows or production needs
  changes; reclassify the provisional test-race diagnosis as an app failure.
- Stop if the MCP loop cannot reproduce the exact sidecar-commit / idle-owner
  state. A nearby synthetic lock failure is not a substitute.
- Stop before changing SimpleBroker, SQLite pragmas, Taut public semantics,
  reactor command ordering, or dependency floors; each requires an explicit
  ownership decision and likely a spec delta.
- Do not split a broad integration assertion merely to reset its timeout budget.
- Do not delete cross-client concurrency from the MCP test. That is supported
  product behavior and part of the contract being exercised.

## Verification

- TUI focused handler case plus the full 32-case concrete-handler registry.
- MCP exact minimized regression, original focused test, full `test_tools.py`,
  and the complete MCP suite.
- Fresh hosted Windows TUI and MCP runs at the new exact SHA. Failed-attempt
  reruns are recovery evidence only and are not accepted as proof of a fix.
- Repository-wide Ruff and the five release-owned mypy lanes; doc paths, plan
  index, and `git diff --check`.

## Review Log

- Independent plan review found four P2 blockers: premature TUI classification,
  a success-only event, no executable hosted diagnostic sequence, and an
  unpinned SimpleBroker baseline. All four were adopted before implementation.
- Independent slice review found no TUI blocker and confirmed the exact-callback
  test plus five-job hosted evidence. It also confirmed the MCP stop gate: the
  new failure precedes MCP startup and lands in SimpleBroker connection cleanup.
  The stack assigns the live failure boundary, not the still-unproved internal
  root cause; a minimal upstream reproducer remains required.

## Execution Log

- Provisionally classified the TUI failure as test synchronization: the generic
  polling helper was not causally tied to the initialization future. Fresh
  hosted exact-callback evidence remains the discriminator.
- Kept the MCP classification open between application lifecycle and test
  budget because current evidence cannot distinguish them. One focused local
  run passed in 0.38 seconds; 100 repetitions passed. No unchanged CI rerun was
  initiated.
- Replaced the TUI initialization polling condition with exact callback
  completion. The observer delegates to production, wakes for success or
  failure, and asserts the exact `InitResult`, file, and rendered result. The
  focused test passed in 0.44 seconds; fresh workflow-dispatch run
  `31834126569` passed all five jobs, including Windows. This confirms the
  original TUI failure was test synchronization, not application callback
  delivery.
- Pushed diagnostic-only commit `e46185e` and dispatched the canonical MCP
  workflow as run `31834124498`. Windows reproduced the failure class in a
  different test before its MCP subprocess started: ordinary
  `TautClient.say()` blocked while SimpleBroker 7.3.2 closed an ephemeral
  SQLite connection at `_runner.py:761`. Together with the earlier sidecar
  commit timeout, this removes MCP command ordering and the individual test
  budget from ownership. The live failure boundary is the pinned SimpleBroker
  SQLite close lifecycle; its internal root cause still needs a minimal
  upstream reproduction. Per the stop gate, all diagnostic markers are
  excluded from the landing change and no Taut workaround or sibling-repository
  edit was made.
- The complete retained-lock TUI suite passed locally. Repository-wide Ruff and
  format checks passed across 391 files; the suppression registry reconciled.
  The five release-owned mypy lanes passed across 132 root, 12 PostgreSQL, 40
  Summon, 21 MCP, and 31 TUI source files. Documentation path checks covered 63
  sources and 1,270 claims; the plan index and `git diff --check` also passed.
  This closes the TUI slice. The plan remains active at the explicit upstream
  MCP stop gate.
