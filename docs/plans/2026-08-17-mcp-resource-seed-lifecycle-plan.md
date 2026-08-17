# MCP Resource Seed Lifecycle Plan

Date: 2026-08-17

Class: 4. This changes test-owned SimpleBroker session lifecycles after a hosted
Windows native SQLite close stalled during a release gate. It does not change a
normative product contract.

Status: active.

## Goal

Keep the exact MCP resource ordering, 100-pointer bound, truncation, claim, and
cross-workspace assertions while removing irrelevant per-message runner
construction and teardown from the 102-message setup phase.

## Source, Contract, and Ownership

- Product baseline: `docs/specs/05-taut-mcp.md` [MCP-7] owns resource ordering,
  notification bounds, truncation, and claim behavior. None changes here.
- Implementation baseline: `docs/implementation/07-taut-mcp-architecture.md`
  owns the seed-client test-lifecycle split and real-backend verification.
- Test owner: `extensions/taut_mcp/tests/test_resource.py` owns both the fixture
  clients and the exact resource assertions. One `ExitStack` owns every seed
  client immediately after construction and closes before reactor startup.

## Spec Baseline

- `9447ce7b24276e1e13b4ff2e6fc8a9beae4cac9f` —
  `docs/specs/05-taut-mcp.md` [MCP-7] at plan authoring time. This plan does not
  revise the spec.

## Required Reading and Comprehension Gate

Read `docs/agent-context/runbooks/testing-patterns.md`,
`docs/agent-context/runbooks/hardening-plans.md`, the MCP architecture's test
lifecycle section, `_workspace()`, and the complete resource test before
editing.

1. What behavior owns the 60-second valve? Expected answer: the real MCP
   resource ordering/bounding/claim scenario, not repeated setup-only runner
   creation and teardown.
2. When must persistent seed ownership end? Expected answer: on every setup
   path and before `ProcessReactor` construction; each client must be registered
   with the same `ExitStack` immediately after construction.

An incorrect or missing answer blocks implementation until the cited owner
text is reread.

## Evidence and Classification

- Exact-SHA MCP run `32044233327`, Windows Python 3.13, timed out the existing
  60-second test deadline in `sqlite3.Connection.close()` while the test was
  writing one of 101 later-workspace mention pointers through a default-
  ephemeral seed client.
- MCP logic and the reactor had not started. The failure boundary was test seed
  setup through SimpleBroker's owned runner cleanup. This is a test-lifecycle
  defect, not evidence of an MCP application failure. It does not rule out a
  rare lower-layer SQLite close defect.
- The macOS job in the same run failed before checkout after HTTP 429, 429, and
  503 responses while GitHub downloaded the pinned `setup-uv` action. That is
  separate hosted infrastructure evidence.

## Invariants and Boundaries

- Use real SQLite and public `TautClient` behavior. Do not mock broker, queue,
  transaction, notification, or reactor work.
- Keep all 102 seed messages, their exact payloads, both workspaces, distinct
  clients, sorted-workspace assertions, the 100-pointer bound, truncation
  assertions, inbox claim, and refreshed-resource assertions.
- Keep the existing 60-second deadline and serial Windows MCP topology.
- Only the two setup actors may use public persistent ownership. Close them on
  every setup outcome and before the reactor starts. Reactor clients retain
  their existing independent ownership.
- Default-ephemeral product behavior remains unchanged and separately covered
  by the root real-operation cleanup test.
- Stop if the correction requires production code, a timeout change, fewer
  messages, weaker assertions, reduced CI parallelism, or private broker APIs.

## Hidden Couplings and Hardening

- `persistent=True` retains a SimpleBroker session and runner until client
  close. Construction order therefore cannot be cleanup order; immediate
  `ExitStack` registration is required so a later constructor or seed write
  cannot leak an earlier client.
- Closing before reactor construction is part of the proof. Leaving the seed
  actors open would conflate setup ownership with the reactor's independent
  workspace ownership.
- The lower-layer Windows stall remains unresolved. A green optimized test
  proves removal of irrelevant lifecycle churn, not absence of a SimpleBroker,
  CPython, or Windows SQLite defect.

## Rollback, One-Way Doors, and Signals

- The code change is test-only and reversible by returning the two actor calls
  to default-ephemeral ownership. No storage, package, API, or workflow state is
  migrated.
- The only one-way door is release tag publication. All local and exact-SHA
  hosted gates therefore run before any 0.9.1 tag is pushed.
- Success means the exact resource test and full canonical Windows/macOS MCP
  lanes pass at the landing SHA with all original assertions. A repeat native
  close stall, leaked client, or post-seed reactor failure blocks publication.

## Verification and Rollout

1. Make the resource fixture's actor persistence explicit and opt-in; use it
   only for this high-volume seed setup.
2. Run the exact resource test, complete MCP non-PG suite, repository-wide
   Ruff, all five mypy lanes, documentation checks, and release dry run.
3. Independently review the lifecycle and assertion boundaries.
4. Commit and push a fresh SHA. Require the complete canonical MCP workflow,
   including Windows and macOS SQLite lanes, before any release tag.
5. Complete the coordinated 0.9.1 release only after all root, PG, Summon/MCP,
   and TUI producer workflows are green at the same SHA. Verify all five GitHub
   Releases, PyPI file hashes, and Sigstore provenance.

## Deviation Log

| Spec ref | Planned behavior | Actual behavior | Rationale | Spec proposal |
|----------|------------------|-----------------|-----------|---------------|

## Execution Log

- Pre-edit comprehension: (1) the valve owns the real resource contract, not
  setup-only runner churn; (2) all persistent seed clients require immediate
  common-`ExitStack` ownership and the stack must exit before reactor creation.
- Independent review found manual cleanup gaps and an overclassification. The
  correction now uses one immediately registered `ExitStack`, is Class 4, and
  records the required hardening, baseline, and deviation surfaces.
- Local proof: the exact 102-message resource case passed in 0.48 seconds; the
  complete non-PG MCP suite passed 269 tests with 7 PG-only cases deselected.
  Repository-wide Ruff and all five mypy lanes passed before review.

## Related Plans

- `docs/plans/2026-08-14-windows-postrelease-ci-determinism-plan.md`
- `docs/plans/2026-08-17-cli-subprocess-readiness-plan.md`
