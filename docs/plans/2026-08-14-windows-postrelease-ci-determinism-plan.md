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
- The bounded upstream investigation is complete at SimpleBroker main
  `4f0860e8`. Changed-code Windows runs `31839280773` and `31839980458`
  completed 2,000 real transaction/read/close cycles both alone and with an
  event-confirmed idle same-file connection on a distinct runner. Every exact
  commit and close returned. These greens do not exclude a rare race, but no
  SimpleBroker-only state reproduced the downstream timeout and no upstream
  code or release was justified.

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
- A pytest timeout stack is a sample of current work, not proof that the sampled
  commit or close is stuck. The next discriminator must measure the exact Taut
  operation sequence and its phase progress against the existing 15-second
  observation point before assigning production ownership.
- Preserve the full OS/Python matrices, serial MCP Windows execution, all
  assertions, and every currently exercised command.
- No timeout, busy-timeout, retry-count, or sleep increase. No automatic CI
  rerun and no ignored failure.

## Rollback, Rollout, and One-Way Doors

There is no data migration or irreversible product change. Each correction is
revertible as one commit. Hosted Windows is the rollout signal. The published
0.9.0 artifacts are immutable and are not rebuilt or retagged.

The authorized SimpleBroker investigation reached its stop gate without a
SimpleBroker-only red. Its diagnostic instrumentation remains off upstream
main, and no patch release was made. A Taut workaround that hides an upstream
transaction leak remains out of scope, but test-owned setup may use a public
persistent client when the test does not claim default-ephemeral lifecycle and
separate root tests retain that contract.

## Execution Slices

1. Replace only the TUI initialization polling success condition with an exact
   callback-completion event that fires for success or failure. Assert the exact
   successful `InitResult`, then keep the final file and inspector assertions.
   If fresh Windows does not deliver the exact callback, reclassify this as an
   application failure and stop before calling the test fixed.
2. Build a red-capable MCP feedback loop by temporarily narrowing the already
   default-branch-registered `.github/workflows/test-mcp-extension.yml` on the
   diagnostic branch. GitHub does not register a new dispatch-only workflow
   that exists only on a non-default branch. The temporary branch version
   contains one Windows 3.13 job and no producer, lint, coverage, artifact, or
   release jobs; it is restored exactly before landing. Its two exact commands run
   `test_windows_aggregate_diagnostic.py::test_exact_mcp_body_budget_lane` and
   `test_windows_aggregate_diagnostic.py::test_exact_mcp_body_phase_lane` with
   `-n 0`; the branch workflow is `workflow_dispatch` only, and the second
   command also fires the Windows process-tree cleanup contract test. A
   dedicated child process
   calls each exact test body directly with a fresh temporary path, so the
   retained pytest `@timeout(15)` marker is not changed. The child acknowledges
   readiness after import/instrumentation and before test work. Every protocol
   record has unique body, iteration, operation, and sequence IDs.

   The budget lane adds only acknowledged body-entered, MCP-grandchild PID
   ownership, and terminal records. The PID control record exists solely so a
   failed probe can verify process-tree cleanup; it is excluded from timing.
   Inner macro phases append child-local monotonic entered/returned/error times
   without IPC; SQLite wrappers are not installed. A body is evidence of
   aggregate pressure only if that one body is still active at its own
   15-second observation point, later reports exact inner progress after that
   point, and completes with every original assertion. Completed earlier
   repetitions cannot satisfy that predicate. Record the minimally instrumented
   per-body timing distribution; never use detailed ACK overhead to authorize
   a lifecycle change.

   The separate phase lane installs transparent SQLite observers in the
   diagnostic driver and publishes synchronous acknowledged
   entered/returned/error records for every driver-process SQLite
   begin/commit/close plus macro phases covering every seed
   `init`/client construction/`join`/`say`/`close`, external observer
   operation/close, and reactor or subprocess await in both exact nodes. The
   stdio server remains an unmodified grandchild: its await boundary and PID
   ownership are observed, while its stdout remains exclusively MCP framing.
   This
   lane may repeat fresh bodies to amplify a rare missing transition, but its
   elapsed time is location evidence only. In both lanes, assertion or product
   exceptions produce an acknowledged terminal error with traceback and are
   re-raised immediately by the parent; success requires an acknowledged final
   complete record. Unexpected EOF, nonzero child exit, and protocol errors are
   immediately fatal. Fifteen seconds records per-body state but neither passes
   nor kills; a separate 60-second missing-progress cap resets on every
   acknowledged record, and a distinct absolute diagnostic cap prevents an
   indefinitely progressing loop.

   The parent initializes cleanup state before launch and closes every endpoint
   on every path. The child is launched in a dedicated process tree. Normal
   completion uses an event-driven cleanup handshake; failure or a missing
   transition uses Windows `taskkill /T /F` (and a POSIX process-group kill in
   local verification), then waits for and verifies child and MCP-grandchild
   reaping. No timed-out stdio server may survive the probe. Commit this
   diagnostic-only change on an intermediate branch and dispatch that exact
   ref. Capture run ID, job ID, and full head SHA. This is changed diagnostic
   code, not an unchanged failed-attempt rerun. Remove the temporary workflow
   and all tagged instrumentation before the final commit.
3. Generate three to five falsifiable MCP hypotheses only after the loop is
   red. Distinguish an owner-thread open transaction, observer cleanup/close,
   command-future premature settlement, and upstream SQLite retry/lock behavior.
4. Add the narrow regression first, apply the owner-correct fix, and rerun the
   original hosted scenario. Stop and revise this plan before any normative
   product-spec change.
5. Run full TUI and MCP suites, repository-wide Ruff, all five mypy lanes, doc
   checks, and diff checks. Obtain independent implementation review, commit,
   push, and require fresh Windows success without rerunning a failed attempt.
6. If exact phase evidence shows continuing aggregate progress rather than a
   missing transition, optimize only test-owned database setup. This test-only
   change has no deterministic local red and changes no product behavior, so
   its explicit red-green substitute is: unchanged exact result/state
   assertions, diagnostic pre/post counts of ephemeral runner creation and
   terminal cycles removed, a repeatable local timing sample, and one fresh
   changed-SHA hosted Windows run. The two failed MCP cases do not claim
   `TautClient`'s default ephemeral lifecycle. In the stdio node, convert seed
   `selected`/`other` and the parent-process `observer` to public
   `persistent=True`; the MCP server is a separate process, so the observer
   remains process-independent. In the tools node, convert only seed
   `selected`/`other`/`third`; keep `observer`, `other_observer`, and
   `third_observer` ephemeral because they intentionally prove operations
   outside the in-process reactor's shared session. Put every persistent client
   under `try/finally` or `ExitStack`, including setup-failure paths. Keep every
   MCP result/state assertion and cite separate root coverage of default
   ephemeral clients at
   `tests/test_client.py::test_client_default_queue_handles_are_transient`.
   Add the real operation/close proof
   `tests/test_client.py::test_default_ephemeral_client_operation_releases_owned_runner`:
   it transparently observes the real SimpleBroker close while a default Taut
   client performs a real queue operation, rather than mocking the operation.
   Do not claim a production race fixed. This is not permission to change
   product defaults, remove the 15-second deadlock valve, or make reactor-owned
   reads replace external observer assertions.

## Stop Gates and Out of Scope

- Stop if the exact TUI callback is absent on fresh Windows or production needs
  changes; reclassify the provisional test-race diagnosis as an app failure.
- Stop if the exact-body loop shows neither a missing entered/returned
  transition nor acknowledged aggregate progress beyond 15 seconds. A terminal
  stack sampled at 15 seconds or a nearby synthetic lock failure is not a
  substitute for either discriminator.
- Stop before changing SimpleBroker, SQLite pragmas, Taut public semantics,
  reactor command ordering, or dependency floors; each requires an explicit
  ownership decision and likely a spec delta.
- Do not split a broad integration assertion merely to reset its timeout budget.
- Do not delete cross-client concurrency from the MCP test. That is supported
  product behavior and part of the contract being exercised.
- Do not add synthetic same-runner contention after the upstream reductions:
  the sampled Taut calls use sequential ephemeral runners, so that state would
  not be a faithful minimization.

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
- Independent review of the downstream MCP discriminator rejected a batch-time
  proxy and an incomplete child protocol. The adopted design now requires one
  minimally instrumented body to cross its own observation point and later
  complete with child-local post-threshold progress; detailed ACK timing is
  location evidence only. The protocol also fails immediately on assertion,
  product, EOF, exit, or transport errors and verifies diagnostic child plus
  MCP-grandchild cleanup. Re-review found no remaining implementation blocker.
- Independent implementation review found and closed three pre-push defects:
  branch-only workflow registration, untested aggregate acceptance, and an
  exited-driver PID reuse window in forced cleanup. The diagnostic now narrows
  the already registered MCP workflow, fires all four acceptance/rejection
  cases, and excludes an exited driver from taskkill targets. Final re-review
  found no remaining blocker before hosted dispatch.

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
  commit timeout, this removes MCP command ordering from that sample, but it
  does not remove the individual test's aggregate 15-second budget from
  ownership: both stacks can be ordinary progress sampled at the deadline.
  Per the stop gate, all diagnostic markers were excluded from the landing
  change and no Taut workaround was made.
- The separately authorized SimpleBroker investigation used real SQLite,
  public Queue sidecars, acknowledged readiness and entered/returned phases,
  and spawned-child hard-cap isolation. Exact Windows job `94892438787`
  completed 16,020 records; job `94894527760` completed 16,024 records with a
  same-file idle peer. Neither reproduced a missing terminal return. The
  general-workflow dispatch also demonstrated why platform diagnostics need a
  dedicated job: unrelated producers were enqueued and the combiner correctly
  rejected an intentionally absent Windows coverage artifact. No upstream
  production change or release occurred. The remaining classification is
  between rare unobserved lifecycle failure and aggregate Taut test progress.
- The complete retained-lock TUI suite passed locally. Repository-wide Ruff and
  format checks passed across 391 files; the suppression registry reconciled.
  The five release-owned mypy lanes passed across 132 root, 12 PostgreSQL, 40
  Summon, 21 MCP, and 31 TUI source files. Documentation path checks covered 63
  sources and 1,270 claims; the plan index and `git diff --check` also passed.
  This closes the TUI slice. The plan remains active at the explicit upstream
  MCP stop gate.
- The temporary exact-body driver passed both original targets and both probe
  lanes locally. One-iteration budget timings were 0.27 seconds for tools and
  0.83 seconds for stdio; the detailed lane observed 51/51 tool commits and
  33/33 stdio-driver commits returning, plus exact MCP grandchild create/stop.
  Predicate and cleanup fault tests passed; MCP Ruff and mypy are clean. The
  canonical MCP workflow contract test is intentionally red only on this
  disposable diagnostic branch because its registered workflow is temporarily
  narrowed; exact restoration is required before any landing commit.
