# Ranged Dependency Policy Plan

Status: completed
Class: 5 — spec-changing because [DOM-10.2] and the TUI/MCP dependency
contracts change. Hardening: N/A — no [DOM-5] risky trigger; this is reversible
metadata, test, CI, and documentation reconciliation with no runtime, API,
persistence, lifecycle, or rollout change.

## Goal

Make lockfiles the sole reproducibility mechanism and make project manifests
declare dependency ranges. Exact pins are permitted only when a concrete,
documented need exists; none exists today. On an approved dependency refresh,
each declared minimum advances to the version selected in the retained lock.
Tests must not repeat declared constraints or selected third-party versions.

## Source Documents

- `docs/specs/01-development-documentation-operating-model.md` [DOM-10.2]
- `docs/specs/02-taut-core.md` [TAUT-12.5], release-wheel matrix
- `docs/specs/05-taut-mcp.md` [MCP-3], [MCP-12]
- `docs/specs/10-taut-tui.md` [TUI-3.1], [TUI-13.2]
- `docs/agent-context/runbooks/testing-patterns.md`
- Owner direction in this task: ranges by default; exact pins only for a
  documented necessity; no current dependency needs one; lock-selected
  versions become the next declared minimums; broader old-version support may
  be evaluated later.

Spec baseline: `e80fe0fc9c0b73353b93754c79e93c495ab2667b` plus the existing TUI worktree
delta. Plan type: implementation with spec revision. Promotion strategy A:
promote the policy text first without claiming implementation conformance,
record the promotion baseline, then change manifests, tooling, tests, and CI.

Promotion baseline: `e80fe0fc9c0b73353b93754c79e93c495ab2667b + current worktree spec diff` after the exact delta in this plan was applied; documentation gates and focused independent review are the promotion proof.

## Context and Key Files

- Root and extension `pyproject.toml` files own dependency ranges.
- Root, Summon, MCP, and TUI `uv.lock` files own reproducible selections; PG
  intentionally has no retained lock and therefore takes its current direct
  minimums from the root lock's PG development resolution.
- `tests/test_project_metadata_consistency.py`,
  `tests/test_dependency_floor_claims.py`, and `tests/test_ruff_policy.py`
  currently duplicate third-party constraints or selected versions.
- `.github/workflows/test.yml` and `bin/release.py` currently run a separate
  exact Textual-floor suite in addition to the locked TUI suite.
- `bin/build-and-check-release-wheels.py` and
  `bin/check-core-summon-wheel-matrix.py` duplicate SimpleBroker and
  SimpleBroker-PG floors and run a PG resolution used only for that duplicate
  comparison.
- `tests/test_core_summon_wheel_matrix.py`, `tests/test_release_script.py`,
  `tests/test_github_workflows.py`, and TUI packaging/launch tests cover the
  affected release, CI, and installed behavior surfaces.
- `docs/implementation/04-taut-architecture.md`,
  `docs/implementation/08-complexity-and-suppression-policy.md`, and
  `docs/implementation/12-taut-tui.md` explain those owners. The active TUI
  plan must record the owner correction without rewriting its historical
  execution evidence.
- Release-helper tests using invented versions remain valid test data; they do
  not claim the repository's installed dependency versions.

## Invariants and Constraints

- Preserve all runtime behavior and all first-party coordinated release/version
  relations.
- Preserve `uv lock --check`, `--locked` execution, installed-wheel smoke, and
  behavior suites against retained locks.
- No manifest contains an exact `==` dependency after this change.
- A ceiling remains allowed when it expresses a known incompatibility; it is a
  range boundary, not an exact pin.
- No Python test or CI job owns a current third-party version literal solely to
  mirror a manifest or lock.
- Do not rewrite historical plans, changelog entries, or lessons.
- Preserve unrelated user work in the dirty worktree.

## Proposed Spec Delta

Replace [DOM-10.2]'s first paragraph and its version-change sentence with:

> Taut's development manifests declare Ruff with a lower-bounded range. The
> retained lockfiles, not an exact manifest pin or a test-owned version literal,
> own reproducible tool selection. An approved dependency refresh raises each
> manifest minimum to the version selected by its owning retained lock; the
> lockless PostgreSQL manifest uses the root lock's development resolution.
> Exact dependency pins are permitted only for a separately documented concrete
> need; no current dependency has one. The root and MCP Ruff configurations
> continue to own the reviewed stable-default rule inventory and suppression
> policy.
>
> A Ruff selection change must update manifest ranges and retained locks in one
> reviewed change, regenerate the effective-rule fixture when the selected rule
> inventory changes, and re-run the raw suppression audit before adoption.

Replace the [TAUT-12.5] release-wheel floor paragraphs with:

> Core and `taut-summon` reactor changes ship as a paired release. The release
> helper synchronizes every extension's `taut-chat>=` floor to the exact new
> core version and refreshes every retained lock. Package tooling owns
> third-party constraint satisfaction and lock consistency; release tests do
> not repeat third-party floors or selected versions. Release evidence includes
> an installed-artifact canary built from the current paired wheels.
>
> New core wheel metadata has normalized project name `taut-chat`. New Summon
> metadata contains exactly one unmarked `taut-chat>=<new-core-version>`
> requirement, so the supplied current core wheel is admitted exactly.

In the following [TAUT-12.5] matrix paragraph, replace “exact current package
names and dependency floors” with “exact current first-party package names and
dependency relations.”

Replace [MCP-3]'s dependency sentences with:

> It declares the direct ranges `mcp>=2.0.0,<3` and
> `jsonschema>=4.26.0,<5`; their lower bounds are the versions selected in the
> current retained MCP lock, and the major ceilings record known compatibility
> boundaries. Application-owned tool-input validation uses Draft 2020-12
> validators compiled once from the same fixed schemas returned by `tools/list`.
> Validation completes before rate charging or semantic work. Network `$ref`
> resolution is disabled and the fixed schemas contain no external references.

Replace the pre-[MCP-12] compatibility paragraph with:

> The MCP SDK selected by the retained MCP lock must demonstrate both legacy
> `2025-11-25` and modern `2026-07-28` stdio clients against the same async
> application handlers. The process reactor captures the running loop from
> era-neutral lifespan startup, and no synchronous AnyIO worker owns a protocol
> handler or reactor bridge. Changing a declared major ceiling requires a new
> compatibility review.

Append to [TUI-3.1]:

> The manifest declares `textual>=8.2.8`, the version selected by the current
> retained TUI lock. The retained lock is the supported and tested dependency
> set; Taut does not currently claim or run a separate older-Textual
> compatibility lane.

Replace [TUI-13.2]'s dependency/launch bullet with:

> - absent extension, incomplete/broken extension dependency, non-TTY,
>   help/version lazy-import floors, and source-tree plus paired core/TUI
>   installed-wheel launch against the retained TUI lock; there is no separate
>   exact-floor dependency lane;

## Tasks

1. Promote the exact spec delta, run doc gates, obtain focused review, and
   record the promotion baseline before dependent edits.
2. Convert every exact manifest pin to a range and ensure declared minimums
   match current retained-lock selections after lock reconciliation.
3. Remove duplicate dependency-literal, lock-version, documentation-floor,
   release-wheel-floor, and exact-floor-lane enforcement while retaining
   first-party relationships, artifact identity, and behavioral owners.
4. Remove the exact Textual-floor release/CI command and the PG compile used
   only for a duplicate floor comparison; keep locked TUI and installed-wheel
   suites.
5. Align implementation notes and the active TUI plan, reconcile retained
   locks, run targeted gates, then run an independent
   completed-work review.

## Testing and Verification

No red-green behavior cycle applies because runtime behavior does not change.
Substitute proof is structural inspection plus real package tooling:

```bash
! rg -n '"[A-Za-z0-9_.-]+==' --glob '**/pyproject.toml' .
! rg -n 'jsonschema>=4\.20|textual==3\.0\.0|ruff==0\.16\.3' \
  --glob '!docs/plans/**' --glob '!CHANGELOG.md' --glob '!docs/lessons.md' .
uv lock --check
uv lock --project extensions/taut_summon --check
uv lock --project extensions/taut_mcp --check
uv lock --project extensions/taut_tui --check
uv run --no-sync --extra dev python - <<'PY'
from pathlib import Path
import re
import tomllib

root = Path.cwd()
owners = {
    root / "pyproject.toml": root / "uv.lock",
    root / "extensions/taut_pg/pyproject.toml": root / "uv.lock",
    root / "extensions/taut_summon/pyproject.toml": root / "extensions/taut_summon/uv.lock",
    root / "extensions/taut_mcp/pyproject.toml": root / "extensions/taut_mcp/uv.lock",
    root / "extensions/taut_tui/pyproject.toml": root / "extensions/taut_tui/uv.lock",
}
for manifest_path, lock_path in owners.items():
    manifest = tomllib.loads(manifest_path.read_text("utf-8"))["project"]
    declared = list(manifest["dependencies"])
    for group in manifest.get("optional-dependencies", {}).values():
        declared.extend(group)
    lock = tomllib.loads(lock_path.read_text("utf-8"))
    selected = {item["name"]: item["version"] for item in lock["package"]}
    for requirement in declared:
        match = re.fullmatch(r"([A-Za-z0-9_.-]+)>=(\d+(?:\.\d+)+)(?:,[^;]+)?", requirement)
        if match is None:
            raise SystemExit(f"unsupported ranged dependency: {manifest_path}: {requirement}")
        name, minimum = match.groups()
        normalized = name.lower().replace("_", "-").replace(".", "-")
        actual = selected.get(normalized)
        print(f"{manifest_path.relative_to(root)}: {name}>={minimum} -> {actual}")
        if actual != minimum:
            raise SystemExit(
                f"minimum does not match owning lock: {name}>={minimum}, selected {actual}"
            )
PY
uv run --no-sync --extra dev pytest -q -n 0 \
  tests/test_project_metadata_consistency.py tests/test_ruff_policy.py \
  tests/test_core_summon_wheel_matrix.py tests/test_release_script.py \
  tests/test_github_workflows.py tests/test_docs_references.py \
  tests/test_plan_status_index.py
uv run --project extensions/taut_tui --extra dev --locked pytest \
  extensions/taut_tui/tests -q -n 0
uv run --no-sync --extra dev ruff check bin tests
uv run --no-sync --extra dev mypy \
  bin/build-and-check-release-wheels.py \
  bin/check-core-summon-wheel-matrix.py bin/release.py \
  tests/test_core_summon_wheel_matrix.py tests/test_release_script.py \
  tests/test_project_metadata_consistency.py tests/test_ruff_policy.py \
  tests/test_github_workflows.py --config-file pyproject.toml
bin/check-plan-status-index
bin/check-doc-paths
git diff --check
```

Expected observations: all four lock checks report no drift; the one-time
inspection prints every direct runtime/development dependency and exits zero
only when its lower bound equals its mapped lock selection (PG maps to root);
no manifest exact pin remains; no active source retains the old JSON Schema
floor, exact Textual floor command, or exact Ruff pin; selected tests, lint,
types, documentation, plan index, and whitespace gates pass. This comparison
is migration evidence only and is not retained as a test or standing gate.

## Deviation Log

| Spec ref | Planned behavior | Actual behavior | Rationale | Spec proposal |
|----------|------------------|-----------------|-----------|---------------|

## Review and Completion

- Independent review of this plan and exact spec delta precedes spec promotion.
- Independent fresh-eyes review follows implementation.
- Completion records concrete commands and results here and in the handoff.
- No commit is made without explicit owner authorization.

## Execution Log

| Date | Stage | Evidence | Result |
|------|-------|----------|--------|
| 2026-08-13 | Spec promotion | Promoted [DOM-10.2], [TAUT-12.5], [MCP-3]/[MCP-12], and [TUI-3.1]/[TUI-13.2]; `bin/check-plan-status-index`; `uv run --no-sync bin/check-doc-paths` | Independent focused review passed after the exact policy boundary and TUI insertion were aligned. |
| 2026-08-13 | Manifest and lock reconciliation | Converted every Ruff exact pin to `ruff>=0.16.3`; raised MCP JSON Schema to `jsonschema>=4.26.0,<5`; raised TUI Textual to `textual>=8.2.8`; reconciled four retained locks; ran all four `uv lock --check` commands | Passed; no manifest dependency uses `==`. |
| 2026-08-13 | One-time minimum inspection | Ran the inline TOML inspection in this plan across root, PG (root-owned lock), Summon, MCP, and TUI runtime/optional dependencies | Passed; every declared lower bound equaled the version selected by its owning retained lock. The inspection was not retained as a test. |
| 2026-08-13 | Duplicate enforcement removal | Deleted `tests/test_dependency_floor_claims.py`; removed third-party version assertions from metadata, Ruff, wheel, release, workflow, and TUI launch tests; removed exact-Textual CI/release lane and duplicate wheel-floor probes; retained first-party package/version relationships and behavioral tests | Focused release/metadata/docs suite passed 196 tests; wheel/release checker suite passed 22 tests; Ruff, format, mypy, doc paths, plan index, and `git diff --check` passed. |
| 2026-08-13 | Residual verification | Ran both renamed retained-lock Textual behavioral probes, all four lock checks, focused policy tests, Ruff/format, docs gates, and diff hygiene after fresh-eyes findings | Passed. The full TUI lane remains blocked by unrelated active SimpleBroker configuration work importing `ResolvedConfig` absent from the retained SimpleBroker 7.3.1; full Ruff-policy inventory also sees unrelated dirty TUI files. |
| 2026-08-13 | Integrated completion | Reconciled every retained lock against SimpleBroker 7.3.2 and the current dependency set; ran the coordinated 0.9.0 test matrix, Ruff inventory/format gates, and all five mypy scopes | Passed. The prior TUI blocker is resolved: the retained TUI suite passed 182 tests. Core, installed-wheel, PostgreSQL, Summon live/process/local-LLM, and MCP lanes also passed. |
