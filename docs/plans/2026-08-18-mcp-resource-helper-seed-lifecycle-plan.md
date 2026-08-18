# MCP Resource Helper Seed Lifecycle Plan

Date: 2026-08-18

Class: 4. This changes test-owned SimpleBroker session ownership after a
hosted Windows SQLite commit consumed an MCP resource test's existing
deadlock cap during fixture setup. It does not change a normative product
contract.

Status: active.

## Goal

Keep every MCP resource assertion, real SQLite operation, external-client
boundary, 15-second deadlock valve, and CI topology while giving the selected
identity's setup-only `TautClient` bounded persistent ownership. Close that
seed before the helper constructs its other client. Preserve the existing
explicit `other_persistent=True` path for the high-volume resource seed case;
default callers still receive an ephemeral external actor. Do not treat a
green result as proof that the lower-layer Windows SQLite stall cannot recur.

## Source, Evidence, and Ownership

- `docs/specs/05-taut-mcp.md` [MCP-7]/[MCP-8] own resource and delivery
  behavior. No product requirement changes.
- `docs/implementation/07-taut-mcp-architecture.md` owns the existing split:
  setup-only clients may reuse a runner under bounded ownership, while clients
  that act during the scenario remain default-ephemeral.
- `extensions/taut_mcp/tests/test_resource.py::_workspace` owns the fixture.
- Exact-SHA run `32197935073`, Windows Python 3.13, exhausted
  `test_backstop_detects_external_consumption_without_touching_identity`'s
  unchanged 15-second cap inside `_workspace() -> selected.join() ->
  sqlite3.Connection.commit()`. The `ProcessReactor` and the behavior under
  test had not started.

Classification: test setup lifecycle amplification at the observed boundary,
not an MCP assertion failure. The stack is a sample at the deadline, so it
does not prove that one commit was blocked for the full 15 seconds. A rare
SimpleBroker, CPython, or Windows SQLite defect remains possible.

## Spec Baseline

- `fda81460c9a7639eab30dcea47b8f1017706ae04`:
  `docs/specs/05-taut-mcp.md` [MCP-7]/[MCP-8] at plan authoring time. This plan
  does not revise the spec.

## Required Reading and Comprehension Gate

Read `docs/agent-context/runbooks/testing-patterns.md`,
`docs/agent-context/runbooks/hardening-plans.md`, the MCP architecture's test
lifecycle section, the complete `_workspace()` helper, and every helper caller
before editing.

1. When must the selected persistent seed close? Expected answer: on success,
   before constructing the other client or returning; on a failed join, before
   the exact exception propagates.
2. Which existing other-client lifecycle must remain? Expected answer: default
   callers receive a default-ephemeral external actor used during their MCP
   scenario; only the two high-volume setup calls retain their explicit
   `other_persistent=True` ownership inside the calling test's `ExitStack`.

An incorrect or missing answer blocks implementation until the cited owner
text is reread.

## Invariants and Hidden Couplings

- Use real SQLite and public `TautClient.init/join/close`; do not mock broker,
  queue, transaction, or MCP work.
- Set `persistent=True` on the selected setup client. Register its close owner
  immediately after construction and close it before constructing the other
  client.
- Preserve the `other_persistent` parameter exactly. Default callers keep an
  ephemeral external actor because it performs independent actions during the
  MCP scenario. The two existing `other_persistent=True` calls remain bounded
  by their caller's `ExitStack` during the 102-message setup. Keep every
  message, identity, token, notification, resource, timing, and state assertion
  unchanged.
- Keep the 15-second valve, serial Windows MCP topology, and complete matrix.
- Root
  `tests/test_client.py::test_default_ephemeral_client_operation_releases_owned_runner`
  remains the real default-ephemeral lifecycle proof.

## TDD Substitute, Stop Gates, and Anti-Mocking Floor

The native Windows stall is not deterministic locally. The explicit TDD
substitute is a firing constructor/cleanup observer that delegates to the real
client and requires the selected seed to be persistent, closed before helper
continues, and closed on join failure. It must prove both other-client modes:
default callers remain ephemeral and the explicit high-volume opt-in remains
persistent. The exact failed node, complete non-PG MCP suite, and a fresh
changed-SHA canonical Windows job retain real integration proof.

Stop before product changes, timeout changes, retries, skipped tests, weaker
assertions, private SimpleBroker APIs, persistent external observers, or
workflow changes. If fresh Windows reaches the same setup stall, reject this
classification and reopen the lower-layer diagnosis.

## Rollback, One-Way Door, and Success Signals

- Rollback is confined to the helper, its lifecycle tests, and owner docs.
- Release tag publication is the one-way door. No 0.9.3 tag is pushed until
  all exact-SHA root, PG, MCP, and TUI producer workflows pass.
- Success requires focused and full MCP tests, repository Ruff/format, MCP
  mypy, documentation checks, independent review, and a fresh uninstrumented
  Windows MCP pass. An unchanged failed-attempt rerun is not acceptance
  evidence.

## Tasks

1. Add the transparent selected-seed ownership and exceptional-cleanup tests;
   record the intended red result.
2. Give the selected setup client new bounded persistent ownership, preserve
   the existing other-client opt-in, and rerun the focused failed node plus the
   full MCP suite.
3. Align implementation guidance; run static/doc gates and independent review.
4. Commit, push, and resume the unchanged normal release helper. Require its
   fresh exact-SHA producer fence before tag creation.

## Independent Review

Review must verify immediate cleanup ownership, close-before-return, real
backend work, default external-client ephemerality plus explicit opt-in
preservation, unchanged assertions/timeouts/topology, the default-ephemeral
root proof, and the stated lower-layer risk.
Any P1/P2 finding blocks landing.

## Deviation Log

| Spec ref | Planned behavior | Actual behavior | Rationale | Spec proposal |
|----------|------------------|-----------------|-----------|---------------|

## Execution Log

- Plan drafted from run `32197935073` before implementation.
- Comprehension gate: (1) selected seed cleanup precedes other construction on
  success and precedes propagation on join failure; (2) default external actors
  remain ephemeral while the two existing high-volume calls keep their bounded
  `other_persistent=True` opt-in.
- RED: all three lifecycle nodes failed because the real selected constructor
  received `persistent=False`. GREEN: both default/opt-in ownership nodes and
  the exceptional-cleanup node passed, together with the exact previously
  failed backstop node.
- The complete non-PG MCP suite passed 276 selected tests with 7 PG-only tests
  deselected in the release-equivalent editable environment. The real root
  default-ephemeral close proof, repository Ruff, relevant format gates, and
  MCP mypy over 21 source files also passed. A first full-suite invocation
  without the release helper's editable overlays found stale installed 0.9.2
  metadata; rerunning with the canonical overlays was green and changed no
  code.

## Related Plans

- `docs/plans/2026-08-17-mcp-tools-seed-lifecycle-plan.md`
- `docs/plans/2026-08-17-mcp-resource-seed-lifecycle-plan.md`
- `docs/plans/2026-08-14-windows-postrelease-ci-determinism-plan.md`
