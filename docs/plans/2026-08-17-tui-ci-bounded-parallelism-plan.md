# TUI CI Bounded Parallelism Plan

Date: 2026-08-17

Class: 4+P. Multi-process execution is a [DOM-5] risky trigger, and changing a
required recurring verification workflow is [DOM-6]-material to future
verification. Effective Class 5 planning/review requirements apply without a
product-spec change.

Status: active.

## Goal

Run the complete retained-lock TUI suite with two fixed pytest workers and
file-scoped distribution. Preserve all 378 tests, assertions, OS/Python
matrix rows, exact dependency lock, and the ten-minute step cap while reducing
wall time and avoiding duplicate session-scoped wheel construction.

## Source Documents and Baseline

- `docs/specs/10-taut-tui.md` [TUI-13.1], [TUI-13.2]
- `docs/implementation/12-taut-tui.md`, Verification and Related Plans
- `.github/workflows/test-tui-extension.yml`
- `tests/test_github_workflows.py`
- `extensions/taut_tui/tests/conftest.py`

Baseline: `4ca45f2d87c347bfa64e86ed4bd450c0742d90ec`.

Owner ratification: in this session the repository owner explicitly required
faster, more deterministic CI without longer timeouts, skips, weaker
assertions, or reduced parallelism, then instructed continuation of the
release. That ratifies this bounded recurring-verification promotion; agent
review does not substitute for that authorization.

## Proposed Durable-Guidance Delta

Promotion strategy: **B — atomic**. Land the implementation guidance, workflow
command, firing contract test, reciprocal plan link, and lesson together.

Insert in `docs/implementation/12-taut-tui.md`, Verification:

> The canonical retained-lock TUI workflow uses exactly two pytest workers
> with `--dist loadfile`. File-scoped ownership keeps every module indivisible,
> including `test_tui_launch.py` and its session-scoped installed-wheel fixture,
> while independent modules run concurrently. The fixed worker count bounds
> SQLite, Textual, and subprocess pressure; `auto` is not permitted. All five
> OS/Python rows, every collected test, and the existing timeout caps remain
> unchanged.

Add to `docs/lessons.md`:

> When a complete CI suite makes continuous passing progress but exhausts a
> fixed hosted-runner wall-time cap, reduce aggregate exposure with bounded
> parallelism rather than extending the cap. Choose the scheduler by fixture
> ownership: when all consumers of a session-scoped expensive fixture live in
> one file, `loadfile` keeps them on one worker and avoids duplicate fixture
> construction. A fixed worker count avoids host-dependent pressure.

## Evidence, Ownership, and Classification

- Exact-SHA TUI run `32087718902` passed Ubuntu 3.11/3.13/3.14 and macOS.
  Windows job `95563593393` made continuous progress to 280 passing tests, then
  GitHub interrupted pytest at the unchanged ten-minute step cap. No assertion,
  product exception, deadlock stack, or worker crash occurred.
- Prior Windows run `32086814821` completed the same 378-test suite under the
  cap. The new failure is aggregate hosted-runner throughput, not demonstrated
  application or test-logic failure.
- `.github/workflows/test-tui-extension.yml` owns the required pre-tag matrix.
  `tests/test_github_workflows.py` owns its executable command contract. No
  product file changes.

## Invariants and Hidden Couplings

- Keep the exact five matrix rows, retained lock, test root, verbosity,
  traceback mode, ten-minute step cap, and twenty-minute job cap.
- Use exactly two workers. Do not use `auto`; hosted CPU visibility must not
  create unbounded SQLite, subprocess, or Textual pressure.
- Use `--dist loadfile`, not `loadscope`, `loadgroup`, or default scheduling.
  Every test file remains indivisible, so the two installed-wheel tests in
  `test_tui_launch.py` reach one worker and its session-scoped fixture builds
  each wheel only once. Independent files can run concurrently. `loadscope`
  is insufficient durable guidance because xdist may split test classes from
  the same file into separate scope groups.
- Each ordinary TUI test receives its own `tmp_path`-owned ambient database.
  Process-local monkeypatches, loggers, Textual apps, and environment changes
  remain isolated by xdist worker processes. Real PTY subprocess cases retain
  their existing platform skips and cleanup assertions.
- Collection must remain exactly 378 items locally at this baseline. Serial and
  bounded-parallel commands must both pass. A worker crash, collection drift,
  duplicate installed-wheel build, or order-dependent failure blocks rollout.

## Anti-Mocking, Stop Gates, and Out of Scope

- Keep real SQLite, Textual pilots, public clients, installed wheels, Summon
  boundary, PTY processes, and every current assertion. Do not replace slow
  cases with mocks or move them out of the required workflow.
- Do not extend any timeout, skip a test/platform, reduce matrix coverage,
  change pytest failure policy, change the retained dependency lock, or weaken
  parallelism elsewhere.
- Stop and classify any fresh failure by exact stack. If the same test fails
  causally under both serial and parallel execution, treat it as app/test logic,
  not scheduling. If only bounded parallel execution fails, revert and isolate
  shared state before proceeding.
- Out of scope: product behavior, test assertions, workflow artifact ownership,
  release gates, coverage collection, and root/PG/MCP topology.

## Rollback, One-Way Door, and Success Signals

- Rollback is a one-line workflow-command revert plus its exact contract test.
- Tag publication is the one-way door. It remains blocked until the changed-SHA
  TUI matrix and root/PG/MCP producers pass.
- Success requires: exact command-contract RED/GREEN; local 378-test serial and
  `-n 2 --dist loadfile` passes; static/doc gates; independent review; and all
  five fresh hosted TUI jobs green. Record pre/post Windows duration. A faster
  POSIX lane does not substitute for Windows proof.

## Tasks

1. Review this concurrency plan before implementation.
2. Change the workflow-contract test first to require `-n 2 --dist loadfile`;
   require the unchanged 20-minute job cap and 10-minute pytest-step cap in the
   same firing test; record the command failure against the serial workflow.
3. Change only the TUI pytest command. Update the implementation note and
   durable lesson about module-scoped distribution preserving fixture
   ownership.
4. Run focused workflow tests, the serial and bounded-parallel TUI suites,
   repository-wide Ruff, TUI mypy, documentation checks, and diff checks.
5. Obtain completed-work review, commit, push, and require fresh exact-SHA
   producer evidence before resuming `bin/release.py`.

## Independent Review

Review must verify exact collection, module/fixture ownership, fixed concurrency,
unchanged timeouts/matrix/assertions, anti-mocking boundaries, rollback, and the
hosted Windows success signal. Any P1/P2 finding blocks implementation or
landing.

## Deviation Log

| Spec ref | Planned behavior | Actual behavior | Rationale | Spec proposal |
|----------|------------------|-----------------|-----------|---------------|

## Execution Log

- Serial local TUI passed 378 tests in 110.00 seconds at the preceding slice.
- Exploratory bounded runs passed all 378 tests: `-n 2 --dist loadgroup` in
  54.08 seconds, `loadscope` in 53.39 seconds, and the selected `loadfile` in
  53.74 seconds. `loadfile` is selected because it guarantees file ownership
  even if future tests use classes, keeping `test_tui_launch.py` and its
  installed-wheel session fixture on one worker.
- Plan review, contract RED/GREEN, changed-workflow verification, and hosted
  evidence remain pending.
- Independent plan review resolved the classification, xdist scheduling,
  fixture-ownership, timeout-contract, and durable-guidance findings and
  returned CLEAR. Owner ratification is recorded above; implementation may
  begin.
- RED: the workflow contract's new exact `-n 2 --dist loadfile` tokens failed
  against the retained `-n 0` command while its new 20-minute job and
  10-minute pytest-step assertions already passed. GREEN changed only the
  pytest worker/distribution tokens; the full 24-test workflow-contract file
  passed.
- The final exact bounded command passed all 378 TUI tests in 54.20 seconds.
  Repository-wide Ruff and format passed over 415 files; TUI mypy passed 34
  sources; documentation paths, plan index, and diff checks passed. Fresh
  hosted exact-SHA evidence and completed-work review remain pending.

## Related Plans

- `docs/plans/2026-08-17-tui-search-anchor-test-synchronization-plan.md`
- `docs/plans/2026-08-14-tui-pretag-gate-plan.md`
- `docs/plans/2026-08-11-ci-factor-and-release-order-plan.md`
