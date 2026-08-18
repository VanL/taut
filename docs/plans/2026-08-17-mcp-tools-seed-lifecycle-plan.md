# MCP Tools Seed Lifecycle Plan

Date: 2026-08-17

Class: 4. This changes test-owned SimpleBroker session lifecycles after a
hosted Windows native SQLite close stalled during MCP fixture setup. It does
not change a normative product contract.

Status: active.

## Goal

Keep the complete MCP tools suite and every application assertion while
making `_workspace_with_two_members()` own its two setup clients as bounded
persistent seeds. Close both clients before returning the workspace to the
test body. Keep time only as the existing per-test deadlock cap.

## Source, Evidence, and Ownership

- `docs/specs/05-taut-mcp.md` [MCP-11] owns reactor failure behavior. No
  product requirement changes.
- `docs/implementation/07-taut-mcp-architecture.md` owns the existing rule
  that seed-only integration clients may be persistent when bounded by an
  `ExitStack` and closed before the asserted reactor scenario.
- `extensions/taut_mcp/tests/test_tools.py` owns the helper and all of its
  consumers.
- Exact-SHA run `32088946497`, Windows job `95567174984`, made continuous
  passing progress through 57 percent and into `test_tools.py` before
  `test_post_command_snapshot_crash_marks_workspace_failed` exhausted its
  unchanged 15-second cap in `sqlite3.Connection.close()`.
  The stack was inside `_workspace_with_two_members() -> other.join()` through
  SimpleBroker ephemeral-runner cleanup. `ProcessReactor` had not been
  constructed and the product behavior under test had not begun.

Classification: test setup lifecycle defect. The helper is used repeatedly to
seed identities and one message; it does not assert default-ephemeral client
ownership. The sampled lower-layer close stall remains a possible rare
SimpleBroker, CPython, or Windows SQLite defect. This correction reduces
irrelevant setup exposure and does not claim to fix or disprove that defect.

## Invariants and Hidden Couplings

- Use real SQLite, public `TautClient.init/join/say/close`, exact member tokens,
  and the same seeded message. Do not mock broker or database work.
- Construct exactly two `persistent=True` seed clients. Register each client
  with one `ExitStack` immediately after construction, before its first
  fallible operation. The stack must close before the helper returns.
- Keep every helper consumer, test assertion, 15-second per-test cap, MCP
  matrix row, and serial Windows topology unchanged.
- The helper's returned workspace and token must remain usable only after both
  seed clients have closed. Reactor and observer clients keep their existing
  independent ownership.
- Root
  `tests/test_client.py::test_default_ephemeral_client_operation_releases_owned_runner`
  remains the real default-ephemeral lifecycle proof.

## TDD Substitute, Stop Gates, and Anti-Mocking Floor

The native Windows stall is not deterministic locally, so there is no honest
local red for the timeout. The substitute proof is: a firing helper test that
transparently observes the two real client constructions and requires
`persistent=True`; the unchanged exact failing test; the complete non-PG MCP
suite; and a fresh canonical Windows job at the changed SHA. The construction
observer delegates to the real client and does not replace any operation.

Stop before product changes, timeout changes, skipped tests, weaker assertions,
private SimpleBroker APIs, or workflow changes. If the changed helper reaches
the same close stall in fresh Windows CI, reopen the lower-layer diagnosis
rather than adding retry or more time.

## Rollback, One-Way Door, and Success Signals

- Rollback is confined to the helper and its lifecycle firing test.
- Release tag publication is the one-way door. No 0.9.2 tag may be pushed
  until root, PG, MCP, and TUI exact-SHA producers pass.
- Success requires focused and full MCP tests, repository-wide Ruff, MCP mypy,
  documentation checks, independent review, and a fresh uninstrumented
  Windows MCP pass. A rerun of unchanged code is diagnostic evidence only.

## Tasks

1. Add the transparent construction-observer test and record its red result.
2. Bound the two persistent seeds with one `ExitStack`; retain all operations.
3. Run focused/full/static/documentation gates and obtain completed-work review.
4. Commit, push, and require a fresh exact-SHA canonical MCP workflow before
   resuming `bin/release.py`.

## Independent Review

Review must verify immediate stack ownership, close-before-return, real backend
work, unchanged assertions/timeouts/topology, the default-ephemeral proof, and
the lower-layer residual. Any P1/P2 finding blocks landing.

## Deviation Log

| Spec ref | Planned behavior | Actual behavior | Rationale | Spec proposal |
|----------|------------------|-----------------|-----------|---------------|

## Execution Log

- Plan drafted from run `32088946497`, job `95567174984`.
- RED: the transparent constructor observer saw `[False, False]` from the two
  real seed clients. GREEN requires `[True, True]` and proves both real clients
  close in reverse construction order before the helper returns.
- Independent review found that the happy-path proof would not catch either
  cleanup callback moving after its client's first fallible `join()`. Two
  parameterized fault probes now fail the first and second seed joins, require
  the exact exception, and prove every successfully constructed client closes
  in reverse order. The real success probe still owns SQLite/join/say coverage.
- The exact previously sampled test and all three lifecycle cases (four pytest
  nodes) passed together. The complete non-PG MCP suite passed after adding the
  fault probes; the preceding timed run passed 271 tests with 7 PG-only tests
  deselected in 41.22 seconds before those two nodes were added. Repository-wide
  Ruff and format passed over 416 files; MCP mypy passed 20 sources;
  documentation paths (63 sources, 1,322 claims), plan index, and diff checks
  passed. Final independent re-review found no P1/P2 blocker. Fresh changed-SHA
  Windows evidence remains pending.

## Related Plans

- `docs/plans/2026-08-17-mcp-resource-seed-lifecycle-plan.md`
- `docs/plans/2026-08-14-windows-postrelease-ci-determinism-plan.md`
