# Coordinated 0.9.8 Preparation Plan

Class: 5+P — coordinated release preparation exposed stale dependency-floor and
versioning language in active normative specs, and the release gate needed a
process correction for isolated extension test environments. [DOM-15] therefore
requires a spec-authoring plan plus process evidence. Hardening: N/A — no
[DOM-5] risky trigger fires.

Plan type: release preparation with spec-authoring clarification.

## Goal

Prepare one synchronized 0.9.8 patch release for core and every extension,
reconcile maintained documentation with the already-selected SimpleBroker
8.3.1 / simplebroker-pg 4.3.1 pair, and update PostgreSQL lifecycle tests to
assert Taut's public session-close obligations rather than dependency-private
checkout or core-cache implementations.

## Source Documents

- `docs/specs/02-taut-core.md` [TAUT-3.4], [TAUT-12.5]
- `docs/specs/03-identity-addressing-notifications.md` [IAN-8.2]
- `docs/specs/04-summon.md` [SUM-7.2]
- `docs/implementation/04-taut-architecture.md`
- `docs/implementation/05-taut-summon-architecture.md`
- `docs/plans/2026-09-15-mcp-result-simplification-plan.md`
- `docs/plans/2026-09-15-numeric-start-time-token-plan.md`
- `../simplebroker/CHANGELOG.md` 8.3.1 and
  `../simplebroker/extensions/simplebroker_pg/simplebroker_pg/runner.py`

## Context and Key Files

- `bin/release.py` remains the sole release-preparation owner. Its existing
  metadata helpers set all five manifests, core constants, first-party pins,
  README, and retained locks to one version.
- `extensions/taut_pg/tests/test_pg_sidecar.py`,
  `extensions/taut_pg/tests/test_reactor.py`, and
  `extensions/taut_mcp/tests/test_pg_conformance.py` inspected a private
  PostgreSQL lease-depth counter. SimpleBroker-PG 4.3.1 intentionally changed
  cached session cores to borrow checkouts per active operation, so an idle
  worker no longer owns a checkout. Its implementation note still contains a
  stale paragraph describing the prior cached-core lease and is not treated as
  authoritative evidence for this preparation.
- The durable Taut requirement is session ownership and closure. The corrected
  tests wrap public `BrokerSession.close()` and `recycle_thread()` while
  delegating to their real implementations, assert calls on the owning thread,
  and preserve real PostgreSQL plus same-target peer proof.
- Existing edits in `docs/agent-kernel.md` and
  `docs/implementation/03-agent-inventory.md` predate this preparation. They
  are preserved and included because the owner requested the current tree be
  gathered into the next patch commit.
- `bin/release.py` is also in scope because the MCP and TUI release test
  commands previously used project environments that could retain stale
  installed metadata. The release gate must exercise isolated extension
  dependency resolution while still testing the prepared editable sources.

## Invariants and Constraints

- Core, `taut-pg`, `taut-summon`, `taut-mcp`, and `taut-tui` use exactly
  version 0.9.8; first-party pins and retained locks agree.
- The MCP result-envelope change is non-breaking within this pre-1.0 internal
  beta and ships in the coordinated patch. No shim, canary, old-version repair,
  or minor-version split is added.
- Every normal release check remains enabled. Do not reduce xdist parallelism,
  extend behavior deadlines, skip tests, or weaken assertions.
- PostgreSQL tests assert calls at Taut's public dependency boundary, not the
  number or timing of dependency-owned pool checkouts or cached cores. Real
  PostgreSQL and same-target peer behavior stay in the proof.
- Historical completed plans remain evidence. New owner decisions are appended
  as explicit supersession notes rather than rewriting their prior execution
  record silently.
- No tag, push, or publication occurs in this preparation task.

## Spec Baseline

- `710f217c34d5f4d76d2e81cd12afce2438fd3ad2` — active specs and maintained
  implementation notes at plan authoring time, plus the existing worktree
  listed above.
- Promotion baseline: `710f217c34d5f4d76d2e81cd12afce2438fd3ad2`
  plus the strategy-D worktree diff in `docs/specs/02-taut-core.md`,
  `docs/specs/03-identity-addressing-notifications.md`, and
  `docs/specs/04-summon.md`, independently reviewed before promotion.

## Proposed Spec Delta

Promotion strategy: D — clarification and dependency-floor reconciliation.
Runtime behavior is already selected by the manifests and dependency release;
the active specs change in place before release preparation is declared ready.

| Spec file | Strategy | Exact delta |
|-----------|----------|-------------|
| `docs/specs/02-taut-core.md` | D | Replace each current supported floor `simplebroker>=8.3.0` with `simplebroker>=8.3.1`, and the matching `simplebroker-pg>=4.3.0` with `simplebroker-pg>=4.3.1`. Retain the historical sentence identifying what 8.3.0 introduced. Add this plan under `## Related Plans`. |
| `docs/specs/03-identity-addressing-notifications.md` | D | In [IAN-8.2], replace the two supported floors with 8.3.1 and 4.3.1. Add this plan under `## Related Plans`. |
| `docs/specs/04-summon.md` | D | Replace the repository-supported SimpleBroker and PostgreSQL floors with 8.3.1 and 4.3.1 while retaining historical version references. Add this plan under `## Related Plans`. |

Maintained implementation docs receive the same current-floor substitutions.
`docs/implementation/04-taut-architecture.md` also replaces “target-specific
versions remain independent” with the current synchronized-version rule:
`all --version X.Y.Z` is the only version-preparation path; target selection
still controls builds, tags, and publication.

Append an owner-decision note dated 2026-09-16 to each affected completed
plan: the MCP envelope is classified non-breaking and ships in coordinated
0.9.8; the numeric-token core-only rollout wording is superseded by that same
coordinated release. Earlier review and implementation evidence remains intact.

## Deviation Log

| Spec ref | Planned behavior | Actual behavior | Rationale | Spec proposal |
|----------|------------------|-----------------|-----------|---------------|

## Tasks

1. Independently review this plan and exact strategy-D delta.
2. Promote the reviewed spec delta and reconcile implementation and completed-
   plan guidance. Record the promotion baseline.
3. Verify the PostgreSQL lifecycle test correction with real PostgreSQL,
   parallel test execution, Ruff, and mypy.
4. Run the unchanged coordinated release check:
   `uv run python bin/release.py all --version 0.9.8 --checks-only`.
5. Run documentation, metadata, diff-hygiene, and artifact-build gates; then
   obtain independent completed-work review.
6. Commit the complete requested tree as `Prepare coordinated 0.9.8 release`.

## Testing and Verification

- Red evidence: the 4.3.1 PG-only sidecar test expected one persistent private
  checkout and deterministically observed zero; the dependency contract now
  requires operation-scoped checkout ownership.
- Green targeted proof: all three corrected lifecycle tests pass against real
  PostgreSQL and prove public session close/recycle invocation on the owning
  thread plus same-target peer usability.
- `uv run python bin/release.py all --version 0.9.8 --checks-only`
- `uv run --extra dev pytest tests/test_docs_references.py -n auto --dist load`
- `uv run python bin/check-doc-paths`
- `uv run python bin/check-plan-status-index`
- `uv run --extra dev pytest tests/test_project_metadata_consistency.py -n auto --dist load`
- build all five wheels from empty package-local `dist/` directories and run
  the repository wheel compatibility checker
- `git diff --check`

## Independent Review Loop

A read-only independent reviewer receives this plan, the active spec sections,
the sibling SimpleBroker 8.3.1 contract, and the focused test diff before
promotion. After all gates, a separate completed-work review receives the full
diff and current evidence. Every finding is accepted, rejected with rationale,
or marked out of scope below.

## Review Findings and Dispositions

The first independent review returned BLOCKED with three P1 findings and one
P2. All are accepted and incorporated before spec promotion.

| Finding | Disposition |
|---------|-------------|
| F1 — named metadata command does not exist | Accepted. Replaced it with the existing metadata-consistency pytest gate. |
| F2 — corrected tests still inspected SimpleBroker-private session/core state | Accepted. Tests now record real public `BrokerSession.close()` / `recycle_thread()` calls at Taut's boundary, delegate to the real implementation, and retain real PostgreSQL and peer-usability proof. |
| F3 — proposed Taut spec text froze dependency-private checkout strategy | Accepted. The normative delta now changes supported floors only; checkout rationale remains attributed context in this plan. |
| F4 — sibling implementation note contradicts current 8.3.1 behavior | Accepted. The plan records the defect and bases the dependency observation on the 8.3.1 changelog and implementation. Correcting the sibling repository is separate work. |
| Round 2 N1 — green evidence still claimed exact core retirement | Accepted. The evidence now states only the observed public session close/recycle calls, owner thread, and peer usability. |

The coordinated check then found one stale assertion in
`test_interrupt_unblocks_full_pty_input_queue`: the test allowed cancellation
but required the child-exit message. The fake child intentionally remains
blocked after the interrupt, so this was a test bug. The assertion now requires
the exact `AdapterWriteCancelled("PTY write interrupted")` outcome and verifies
the child is still alive before explicit cleanup.

The next coordinated check found stale installed metadata in the MCP project
environment (`taut-chat==0.9.7`, `taut-mcp==0.9.7`) despite current editable
sources. The MCP and TUI extension test commands now use uv's `--isolated`
environment, so subprocess metadata probes resolve the prepared source
distributions rather than an ambient project environment. Exact command-shape
tests were updated with this isolation boundary. The MCP command also names
the `taut-pg` editable explicitly because its conftest registers that backend
even in the non-PG selection. Behavioral assertions remain unchanged.

The isolated MCP run also exposed a second stale checkout/core-count oracle in
`test_broker_session_owner_retirement_orders_waiter_before_scope_close`.
That test now waits for the Taut-owned candidate to be reaped and keeps its
existing public waiter-before-session-close ordering and same-target peer
assertions; it no longer infers lifecycle completion from SimpleBroker's
private core set.

The artifact-build proof then found a stale MCP result-envelope oracle in the
installed-wheel checker: after `detach_workspace`, `list_workspaces` correctly
returned `{"records": []}`, but the checker still required the removed
`empty: true` marker. The checker and its scripted lifecycle fixture now assert
the current MCP contract directly: an empty workspace list is represented by an
empty `records` array. The completed-work review then found the checker should
also reject the retired marker if it appears alongside `records`; accepted. The
checker now requires exact `{"records": []}`, and the scripted fixture includes
a failing `legacy-empty-envelope` case. Focused re-review returned PASS.

## Execution Evidence

- Focused release-script command-shape test:
  `uv run --no-sync --extra dev pytest tests/test_release_script.py -q` —
  165 passed.
- Direct isolated MCP non-PG proof:
  `uv run --isolated --project extensions/taut_mcp --extra dev --with-editable . --with-editable extensions/taut_mcp --with-editable ./extensions/taut_pg python -m pytest extensions/taut_mcp/tests -m 'not pg_only' -n 0 -q` —
  310 passed.
- First full coordinated check reached every test suite and then failed only on
  Ruff formatting in `tests/test_release_script.py`; the test failure was fixed
  by formatting that file.
- Final clean full coordinated check after the release helper fixes:
  `uv run python bin/release.py all --version 0.9.8 --checks-only` —
  passed. Observed sub-results included core `2191 passed, 4 skipped`;
  installed-wheel `28 passed`; shared PostgreSQL `275 passed`;
  `taut-pg` PostgreSQL `44 passed`; MCP PostgreSQL `8 passed`;
  `taut-summon` unit `310 passed`; grouped `taut-summon`
  `303 passed, 9 skipped`; live harness `8 passed`; local LLM smoke
  `1 passed`; isolated MCP `310 passed, 8 deselected`; isolated TUI
  `457 passed`; Ruff, Ruff format, suppression index, and all mypy slices
  passed.
- Wheel-matrix checker regression:
  `.venv/bin/python bin/build-and-check-release-wheels.py` initially failed
  with `list_workspaces retained state after detach` because the checker still
  expected the old `empty: true` marker. After updating the probe to the current
  MCP result contract, `uv run --no-sync --extra dev pytest
  tests/test_core_summon_wheel_matrix.py -q` passed with 65 tests and
  `.venv/bin/python bin/build-and-check-release-wheels.py` passed all four
  synchronized installed-wheel cases.
- Release artifact proof:
  `uv run python -c "from bin import release; release.run_postupdate_steps_for_targets((release.ROOT_TARGET, release.PG_TARGET, release.SUMMON_TARGET, release.MCP_TARGET, release.TUI_TARGET), dry_run=False)"` —
  emptied `dist`, `extensions/taut_pg/dist`, `extensions/taut_summon/dist`,
  `extensions/taut_mcp/dist`, and `extensions/taut_tui/dist`; built all five
  0.9.8 sdists/wheels; and passed all four synchronized installed-wheel cases.
- Documentation and hygiene gates:
  `uv run python bin/check-doc-paths` passed;
  `uv run python bin/check-plan-status-index` passed;
  `uv run --extra dev pytest tests/test_docs_references.py tests/test_project_metadata_consistency.py -n auto --dist load -q`
  passed with 15 tests; `git diff --check` passed.

## Out of Scope

- Publishing, tagging, or pushing 0.9.8.
- Backward-compatibility machinery or support for previous internal beta
  releases.
- Changing SimpleBroker's operation-scoped PostgreSQL checkout policy.
