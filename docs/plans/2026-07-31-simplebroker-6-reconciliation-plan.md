# SimpleBroker 6.0 Reconciliation Plan

Class: 5 — the user-selected dependency floor changes a supported compatibility
surface and the normative dependency text must change with it. The [DOM-5]
risky compatibility trigger fires, so this plan applies the hardening checklist.

Plan type: implementation with spec revision.

## Goal

Reconcile Taut with the user-selected `simplebroker>=6.0.0` and
`simplebroker-pg>=3.5.0` floors. Verify every SimpleBroker 6.0 breaking or moved
surface against Taut's real consumers, update only consumers that exist, refresh
retained locks and dependency-owned documentation, and preserve all Taut runtime
behavior.

## Source Documents

- User requirement in the 2026-07-31 session: investigate SimpleBroker 6.0.0
  and update Taut, with special attention to `cmd_read` keyword-only arguments
  and newly exported `simplebroker.ext` surfaces.
- `../simplebroker/CHANGELOG.md`, version 6.0.0.
- `../simplebroker/docs/specs/16-python-library-api.md` [SB-API-1], [SB-API-10],
  [SB-API-11].
- `docs/specs/02-taut-core.md` [TAUT-3.4], [TAUT-8.3], [TAUT-12.1],
  [TAUT-12.5].
- `docs/specs/03-identity-addressing-notifications.md` [IAN-8.2].
- `docs/specs/04-summon.md` [SUM-9] control-reactor dependency floor.
- `docs/implementation/04-taut-architecture.md` and
  `docs/implementation/05-taut-summon-architecture.md`.

## Context and Key Files

- `pyproject.toml` owns the core SimpleBroker floor and the development
  SimpleBroker-PG floor. The user already selected 6.0.0 and 3.5.0 there.
- `extensions/taut_pg/pyproject.toml` owns the Taut-PG runtime floor. The user
  already selected 3.5.0 there.
- `extensions/taut_summon/uv.lock` and `extensions/taut_mcp/uv.lock` are the
  retained locks derived from those manifests. The initial root test run
  refreshed the Summon lock; MCP remains stale until explicitly reconciled.
- `README.md`, `docs/specs/02-taut-core.md`,
  `docs/specs/03-identity-addressing-notifications.md`,
  `docs/specs/04-summon.md`,
  `docs/implementation/04-taut-architecture.md`, and
  `docs/implementation/05-taut-summon-architecture.md` still name the prior
  floors.
- `tests/test_project_metadata_consistency.py` is the existing red-capable
  dependency-documentation gate. It currently fails because the README says
  5.6.1 while `pyproject.toml` says 6.0.0.
- A repository-wide source scan found no import or call of
  `simplebroker.commands`, including `cmd_read`. It also found no Taut import of
  `find_project_config`, `project_config_path_for_directory`, or
  `resolve_project_target` from an older SimpleBroker module. Existing Taut
  exception, sidecar, timestamp, watcher-base, and backend-plugin imports
  already use `simplebroker.ext`.

Required comprehension before implementation:

1. Does Taut invoke any command-layer function whose optional arguments became
   keyword-only? The answer must remain evidence-backed by a full source scan;
   do not create a call merely to exercise the new signature.
2. Which file owns each version string: manifest, retained lock, human README,
   normative spec, or durable implementation rationale? Update derived copies
   without turning historical changelog entries or tests of rejected old wheel
   metadata into current-floor claims.

## Invariants and Constraints

- Taut's CLI, Python API, queue operations, storage schema, retry ownership,
  reactor lifecycle, and output remain unchanged.
- Production code continues to use only `simplebroker` and
  `simplebroker.ext`; no private SimpleBroker module becomes a dependency.
- Do not add a `simplebroker.commands` integration. Taut owns its CLI through
  `TautClient`, so the command-layer signature change is non-applicable unless
  an actual caller is found.
- Do not replace Taut's `.taut.toml` terminal-policy discovery with
  SimpleBroker's project-config helpers. The file names and policy semantics
  differ.
- Historical version statements remain historical. Only current supported-floor
  claims and manifest-derived metadata move.
- SimpleBroker remains real in compatibility tests. Do not mock its signatures,
  imports, queue behavior, or backend plugin resolution.
- No new dependency, compatibility shim, second runtime path, or speculative
  refactor is authorized.

## Hidden Couplings and Error Priorities

- `simplebroker-pg>=3.5.0` itself requires `simplebroker>=6.0.0`; the two floors
  and both retained locks must resolve as a compatible pair.
- Root metadata is embedded into each retained extension lock, so changing only
  the resolved package record leaves stale `requires-dist` claims.
- README dependency strings are checked against the root manifest. Specs and
  implementation notes are living owners even where the metadata test does not
  enumerate them.
- Resolver or import failure is fatal evidence and stops the change. A missing
  applicable `cmd_read` or moved-helper consumer is not a failure and must not
  be "fixed" by adding code.

## Rollout, Rollback, and One-Way Doors

Rollout is one coordinated source change: manifests, locks, current docs, and
tests must agree before release. The post-deploy signal is successful clean
installation/resolution of core plus Taut-PG and ordinary root/extension test
execution with SimpleBroker 6.0.0.

Rollback is a coordinated revert of the floor, derived locks, and current-floor
documentation. There is no data migration, storage-format change, cleanup, or
other one-way door. Do not publish or tag as part of this plan.

## Spec Baseline

- `1d91141270cb031b1f1d464c1b3dc3bec77377b5` —
  `docs/specs/02-taut-core.md` and
  `docs/specs/03-identity-addressing-notifications.md`, and
  `docs/specs/04-summon.md` at plan authoring time.
- The worktree already contains the user's manifest-floor edits; those do not
  alter the committed spec baseline.
- Promotion baseline: `1d91141270cb031b1f1d464c1b3dc3bec77377b5` plus
  worktree changes to `docs/specs/02-taut-core.md`,
  `docs/specs/03-identity-addressing-notifications.md`, and
  `docs/specs/04-summon.md`; 10 doc-reference tests and `uv run
  bin/check-doc-paths` passed immediately after promotion.

## Proposed Spec Delta

Promotion strategy: A — edit the existing active spec paragraphs first, then
reconcile the implementation notes, README, locks, and plan backlinks. No code
will cite new behavior between slices.

### `docs/specs/02-taut-core.md` [TAUT-3.4]

Replace exactly:

> The `simplebroker>=5.6.1` floor is load-bearing.

with:

> The `simplebroker>=6.0.0` floor is load-bearing.

Keep the existing detailed 5.2.0 through 5.6.1 provenance text unchanged.
Insert this exact text inline in the same list-item paragraph, immediately after
the sentence ending `or access private broker state.` and immediately before
the sentence beginning `Persistent Queue handles for one resolved target`:

> Version 6.0.0 is the supported compatibility boundary: its command-layer
> options are keyword-only, its project-config discovery helpers are public
> through `simplebroker.ext`, and `simplebroker-pg>=3.5.0` requires that core
> line. Taut uses neither the SimpleBroker command layer nor the newly
> re-exported project-config helpers; it continues to use the root queue/target
> API and the existing `simplebroker.ext` embedder surfaces.

### `docs/specs/02-taut-core.md` [TAUT-8.3]

Replace the runtime dependency sentence with:

> Core runtime dependencies: exactly `simplebroker>=6.0.0` and `psutil`. The
> optional `taut-pg` extension adds `simplebroker-pg>=3.5.0` and its driver
> dependencies in the same environment as Taut. Python ≥ 3.11. The CLI uses
> argparse, not a CLI framework.

### `docs/specs/03-identity-addressing-notifications.md` [IAN-8.2]

Replace exactly:

> Taut requires `simplebroker>=5.6.1` and `taut-pg` requires
> `simplebroker-pg>=3.3.1`. This compatible pair supplies atomic write ids, the
> rename-capable backend handshake, safe persistent-reactor ownership, public
> live activity-waiter replacement, and interruptible watcher bootstrap during
> locked PhaseLock and SQLite connection setup. It also includes corrected
> runner cleanup and initialized timestamp-conflict metrics for concurrent first
> writes. The implementation must use
> `simplebroker.open_broker(...).rename_queue(...)` against Taut's resolved
> broker target; it must not assume `Queue.rename()` or a module-level
> `simplebroker.rename_queue()` exists.

with:

> Taut requires `simplebroker>=6.0.0` and `taut-pg` requires
> `simplebroker-pg>=3.5.0`. This compatible pair preserves the atomic write ids,
> rename-capable backend handshake, persistent-reactor ownership, live
> activity-waiter replacement, interruptible watcher bootstrap, corrected
> runner cleanup, and timestamp-conflict metrics on which rename relies. The
> 6.0.0 command-layer binding change does not affect rename because Taut uses
> `simplebroker.open_broker(...).rename_queue(...)`, not
> `simplebroker.commands`. The implementation must use
> `simplebroker.open_broker(...).rename_queue(...)` against Taut's resolved
> broker target; it must not assume `Queue.rename()` or a module-level
> `simplebroker.rename_queue()` exists.

### `docs/specs/04-summon.md` [SUM-9]

Replace exactly:

> SimpleBroker 5.6.1 or newer required for the supported reactor lane.

with:

> SimpleBroker 6.0.0 or newer required for the supported reactor lane.

Replace exactly:

> Version 5.6.1 is the repository-wide floor that also supplies core reaction
> fanout's full-requested-set exact-name broadcast.

with:

> Version 5.6.1 supplies core reaction fanout's full-requested-set exact-name
> broadcast; 6.0.0 is the repository-wide supported floor, aligned with
> `simplebroker-pg>=3.5.0`. Summon does not call the SimpleBroker command layer,
> so 6.0.0's keyword-only command-option binding does not alter the control
> reactor path.

### Related-plan backlinks

Add this plan under `## Related Plans` in all three touched specs, describing it as
the SimpleBroker 6.0.0 / SimpleBroker-PG 3.5.0 compatibility reconciliation.

## Tasks

1. Review this plan and exact spec delta independently.
   - Reviewer reads this plan, all three governing spec sections, the SimpleBroker
     6.0.0 changelog/API spec, current imports/call scan, and existing metadata
     test.
   - Stop if a reviewer identifies an unsearched consumer or disputes that the
     dependency floor is the only runtime compatibility change.
   - Done when every finding is reproduced and dispositioned in the review log.

2. Promote the reviewed spec delta.
   - Files: `docs/specs/02-taut-core.md`,
     `docs/specs/03-identity-addressing-notifications.md`, and
     `docs/specs/04-summon.md`.
   - Preserve historical provenance and add reciprocal plan backlinks.
   - Record a worktree promotion baseline and run the doc-reference tests.
   - Stop if the exact SimpleBroker API inspection contradicts any promoted
     claim.

3. Reconcile current metadata, retained locks, and durable documentation.
   - Preserve the user's edits in `pyproject.toml` and
     `extensions/taut_pg/pyproject.toml`.
   - Refresh `extensions/taut_summon/uv.lock` and
     `extensions/taut_mcp/uv.lock` through `uv lock`, not manual lock editing.
   - Update current floor claims in `README.md`, and add a new Unreleased floor
     entry to `CHANGELOG.md`. Update durable rationale in
     `docs/implementation/04-taut-architecture.md` and
     `docs/implementation/05-taut-summon-architecture.md`.
   - Do not change historical changelog entries or old-wheel rejection
     fixtures.
   - Stop if resolution selects a SimpleBroker or SimpleBroker-PG version below
     the selected floors or changes unrelated first-party package versions.

4. Verify the compatibility boundary and reconcile traceability.
   - Re-run the exact source scan for command-layer calls, old project-helper
     imports, private imports, and every `5.6.1` / `3.3.1` occurrence. Classify
     each remaining occurrence explicitly as historical, a rejected-old-wheel
     fixture, or a defect before completion.
   - Run the focused metadata test, root and retained-extension tests, Ruff,
     mypy, plan-status, doc-reference, and CLI-claim gates listed below.
   - Perform independent completed-work review and author fresh-eyes review.
   - Update this plan's promotion baseline, evidence, review log, and deviation
     log; then mark its status completed only if all required work is done.

## Testing Plan

The existing failing test is the red-green proof:

```bash
uv run pytest -q tests/test_project_metadata_consistency.py::test_readme_install_examples_use_public_distribution_names
```

It failed with README `{5.6.1}` versus manifest `{6.0.0}`. No new runtime
regression test is planned because Taut has no consumer of the changed
SimpleBroker command signatures or newly exported project helpers. Adding a
mocked or synthetic caller would test invented behavior. The substitute proof
for non-applicability is an exact repository-wide import/call scan plus the real
installed dependency in the full suites.

Do not mock SimpleBroker. Root and extension tests must import and exercise the
resolved 6.0.0 package and 3.5.0 PostgreSQL extension where their existing
harnesses select it.

## Verification and Gates

Per-task:

```bash
uv run pytest -q tests/test_project_metadata_consistency.py::test_readme_install_examples_use_public_distribution_names
uv run pytest -q tests/test_architecture_boundaries.py
uv run pytest -q tests/test_docs_references.py
bin/check-plan-status-index
```

Final:

```bash
uv run --extra dev pytest -q
uv run --project extensions/taut_mcp --extra dev pytest -q
uv run ruff check taut tests extensions
uv run ruff format --check taut tests extensions
uv run mypy taut tests
bin/check-doc-paths
bin/check-cli-claims
bin/check-plan-status-index
bin/check-dom15-fixtures
```

If a Docker PostgreSQL service is available, also run `bin/pytest-pg`; otherwise
report that live backend gate as residual risk rather than claiming it passed.

## Independent Review Loop

Use `skills/call-agent/SKILL.md` with a review-eligible non-Codex family. The
reviewer receives this plan verbatim, the exact unit/baseline, accepted risk
(the user has selected the major-version floor), the pre-existing-rule fence,
the required [P1]/[P2] and PASS/BLOCKED format, and a non-actionable
observations outlet. Review findings are reproduced before acceptance. Accepted
findings modify the plan before spec promotion; declined or out-of-scope
findings receive a written rationale.

Run the same scoped review posture over the completed diff before closure.

## Out of Scope

- Weft's parallel reconciliation; it is neither evidence nor an example for
  this work.
- New use of `simplebroker.commands` or the added project-config helper exports.
- Taut behavior, schema, CLI, public Python API, retry policy, or watcher
  architecture changes.
- Publication, tagging, or release execution.
- Historical test fixtures that intentionally model older package metadata.

## Deviation Log

| Spec ref | Planned behavior | Actual behavior | Rationale | Spec proposal |
|----------|------------------|-----------------|-----------|---------------|

## Review Log

| Round | Reviewer | Verdict | Findings and dispositions |
|-------|----------|---------|---------------------------|
| 1 | Claude Opus | BLOCKED | Accepted P1: added the missed normative `docs/specs/04-summon.md` floor and backlink. Accepted P2: made CHANGELOG work an explicit new Unreleased entry. Accepted P2: changed [TAUT-3.4] to exact anchored replacements and removed redundant provenance summary. |
| 2 | Claude Opus | BLOCKED | Accepted P2: replaced the nonexistent paragraph anchors with exact sentence anchors and specified inline insertion. Also tightened the reviewer's non-blocking [IAN-8.2] observation into an exact whole-paragraph replacement so the same ambiguity cannot recur there. |
| 3 | Claude Opus | PASS | No findings. Verified the [TAUT-3.4] anchors are unique and adjacent and the inline structure is explicit; verified the exact [IAN-8.2] replacement preserves every normative rename requirement. |
| Completed work | Claude Opus | PASS | Accepted non-blocking P2: the product delta was correct, but the investigation record explicitly dispositioned only the breaking command signatures and added ext exports. Added evidence for alias canonicalization, reserved exact-insert ID zero, exact-ID decimal validation, and Unicode timestamp digit folding; no product change followed. |

## Evidence

- Upstream inspection: SimpleBroker `v6.0.0` changelog, public API spec, and
  `v5.6.1..v6.0.0` source diff confirm keyword-only options on `cmd_read`,
  `cmd_peek`, `cmd_move`, `cmd_watch`, and `cmd_list`; the only added
  `simplebroker.ext` exports are `find_project_config`,
  `project_config_path_for_directory`, and `resolve_project_target`.
- Remaining 6.0.0 changelog dispositions: Taut never calls
  `canonicalize_queue`, creates no SimpleBroker aliases, and passes
  `retarget_aliases=False`, so the corrected alias-sigil rule needs no local
  adaptation. Taut has no SimpleBroker dump/load or exact-insert path, so
  reserving ID `0` for new exact insertion does not apply; upstream retains
  legacy-zero selection. Taut's exact-message boundary rejects non-ASCII input
  through `MESSAGE_ID_RE` before `TimestampGenerator.validate(..., exact=True)`,
  so the `isdecimal()` error fix does not alter Taut's exact-ID contract. Taut's
  `log(..., since=...)` intentionally delegates to `TimestampGenerator.validate`,
  so it inherits corrected non-ASCII timestamp-digit folding without a local
  signature or policy change.
- Applicability scan: no Taut production/test import or call of
  `simplebroker.commands`; no SimpleBroker project-helper import; no production
  private-module import. Same-named `_find_project_config` hits are Taut's own
  `.taut.toml` terminal-policy helper.
- Red-green proof: the initial full suite failed only
  `test_readme_install_examples_use_public_distribution_names` with README
  `{5.6.1}` versus manifest `{6.0.0}`. After reconciliation, the focused
  metadata plus architecture/doc boundary command passed 45 tests.
- Locks: `uv lock --upgrade-package simplebroker --upgrade-package
  simplebroker-pg` in `extensions/taut_summon` and plain `uv lock` in
  `extensions/taut_mcp` resolved 6.0.0/3.5.0; MCP reported both exact upgrades.
- Runtime suites: `uv run --extra dev pytest -q` passed with one expected
  Windows-only skip; the MCP project suite passed with six expected DSN-gated
  PostgreSQL skips.
- Live backend: `uv run bin/pytest-pg` passed 214 shared PostgreSQL tests and
  14 PG-only tests against Docker PostgreSQL 18.
- Static and documentation gates: Ruff check passed; Ruff format reported 159
  files already formatted; mypy reported no issues in 96 source files;
  `check-doc-paths` checked 48 sources/823 claims; `check-cli-claims` checked 48
  sources/200 claims; plan-status and DOM-15 fixture gates passed.
- Completed-work independent review: Claude Opus returned PASS. Its one
  non-blocking P2 documentation-rigor finding was accepted and produced the
  four remaining changelog dispositions above.
- No residual compatibility risk was identified by the completed-work review.
  Publication and tagging remain governed separately by [TAUT-12.5].
