# MCP Windows Resource Timeout Budget Plan

Date: 2026-08-18

Class: 4. This changes platform-specific test deadlock budgets after a Windows
resource test timed out during setup. It changes no product contract or
behavioral assertion.

Status: completed at `72cd6f3`.

## Goal

Scale only the outer MCP resource-test deadlock cap by 3x on Windows, where
process initialization and filesystem work are routinely 2x–3x slower. Keep
every event-based and domain-specific behavior deadline unchanged so Windows
setup overhead cannot create a false failure and a real MCP behavior mismatch
still fails on the same evidence.

## Source, Evidence, and Ownership

- Owner intent: the repository owner explicitly accepted Windows setup-budget
  scaling on 2026-08-18 because setup overhead is not the behavior under test.
- Baseline: `d16a278` after the coordinated 0.9.3 release evidence record.
- `extensions/taut_mcp/tests/test_resource.py` owns six real-SQLite integration
  deadlock markers: five 15-second cases and one 60-second bulk seed case.
- Exact-SHA MCP run `32197935073` sampled the fourth resource test in
  `_workspace() -> selected.join() -> sqlite3.Connection.commit()` when its
  15-second whole-test marker expired. The MCP reactor had not started.

Classification: test budget/isolation defect. The outer marker is a missing-
progress containment cap, not a behavior assertion. The existing exact
`async_eventually` deadlines, pacing checks, result/state assertions, and
reactor semantics own the behavior under test.

## Invariants and Hidden Couplings

- Use one pure platform-budget helper: Windows is exactly 3x; every other
  platform remains exactly 1x.
- Apply it to all six resource integration deadlock markers: 15 becomes 45 on
  Windows and remains 15 elsewhere; 60 becomes 180 on Windows and remains 60
  elsewhere.
- Do not change any `async_eventually` timeout or interval, pacing threshold,
  message count, SQLite/client lifecycle, assertion, skip, xdist topology, or
  workflow/job timeout.
- The platform cap changes failure latency only. It never converts a failed
  result/state assertion into success and remains far below the canonical
  900-second MCP step backstop.
- Keep the recent bounded persistent selected-seed optimization. Budget
  correctness must not depend on that optimization making Windows fast enough.

## TDD, Stop Gates, and Anti-Mocking Floor

Add a pure firing test for Windows and non-Windows factor values, plus an
enumerable marker audit covering all six test names and both base budgets.
Record RED against the unscaled marker set before changing it. Run the exact
previously failed node and the complete real-SQLite MCP suite; do not mock
SQLite, Taut clients, reactor work, or pytest marker inspection.

Stop if implementation needs product code, changes a behavioral deadline,
adds retries/skips, removes assertions, changes parallelism/workflows, or
scales platforms other than Windows. A fresh hosted Windows failure inside the
MCP scenario after setup completes is an application/test-behavior failure and
must not be relabeled as setup overhead.

## Rollback, One-Way Doors, and Signals

- Rollback is the helper, marker replacements, tests, and owner docs.
- There is no publication in this slice. A future release tag is the only
  one-way door and remains outside this work.
- Success requires deterministic factor/marker tests, the exact resource node,
  full MCP tests, repository Ruff/format, MCP mypy, docs checks, independent
  completed-work review, and a fresh canonical Windows MCP lane at the landing
  SHA. A rerun of unchanged code is not hosted acceptance evidence.

## Required Reading and Comprehension Gate

Read `docs/agent-context/runbooks/testing-patterns.md`,
`docs/agent-context/runbooks/hardening-plans.md`, every timeout-marked resource
test, and the MCP architecture's test-lifecycle section.

1. What gets scaled? Expected answer: only each test's outer deadlock cap on
   Windows, by exactly 3x.
2. What stays exact? Expected answer: every behavioral/event deadline,
   assertion, workload, lifecycle, and CI topology.
3. What does a post-setup timeout mean? Expected answer: it remains a real
   behavior/deadlock failure; the platform setup explanation cannot excuse it.

Incorrect answers block implementation.

## Tasks

1. Add the pure factor and complete marker-audit tests; record RED.
2. Add the test-local factor helper and replace all six literal markers.
3. Update MCP implementation guidance and the durable timeout-budget lesson.
4. Run focused/full/static/doc gates and independent completed-work review.
5. Commit and push; require a fresh exact-SHA canonical Windows MCP pass before
   marking the plan complete.

## Independent Review

Review must verify all six markers, exact platform factors, unchanged inner
deadlines/assertions/workload/topology, no product change, and honest hosted
evidence. Any P1/P2 blocks landing or completion.

## Deviation Log

| Spec ref | Planned behavior | Actual behavior | Rationale | Spec proposal |
|----------|------------------|-----------------|-----------|---------------|

## Execution Log

- Owner acceptance and the three comprehension answers were recorded before
  implementation: only Windows outer caps scale 3x; inner behavior remains
  exact; any post-setup behavior failure remains fatal.
- RED: the pure platform rule produced two expected failures because `win32`
  still returned the unscaled 15- and 60-second values; Linux and macOS cases
  passed unchanged.
- GREEN: one pure helper now owns the exact 3x Windows factor and all six
  resource integration markers cite it. The enumerable marker audit and the
  previously failed backstop node passed together (11 tests).
- The complete non-PostgreSQL MCP suite passed serially with real SQLite.
  Repository-wide Ruff lint and format, MCP source/test mypy, plan-index,
  doc-path (63 sources and 1,332 claims), and `git diff --check` also passed.
- Independent completed-work review returned CLEAR: all six outer markers use
  the exact factor helper; no inner deadline, assertion, workload, lifecycle,
  xdist setting, or workflow changed. Fresh exact-SHA Windows evidence was the
  remaining completion gate.
- Fresh exact-SHA MCP run `32207169859` passed at
  `72cd6f3be48a74064e5c19a51452d696052039fc`. Windows job `95932530496`
  passed 286 tests with 7 deselected in 275.43 seconds; the formerly failing
  resource backstop completed in 2.93 seconds. macOS, Ubuntu 3.11/3.13/3.14
  SQLite/PostgreSQL, lint, mypy, and package build were also green.

## Related Plans

- `docs/plans/2026-08-18-mcp-resource-helper-seed-lifecycle-plan.md`
- `docs/plans/2026-08-17-mcp-tools-seed-lifecycle-plan.md`
- `docs/plans/2026-08-14-windows-postrelease-ci-determinism-plan.md`
