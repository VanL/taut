# Agent-Theory Delta Wave Plan (2026-10-14)

Status: completed — landed after Tier-1 codex scoped adaptation review (APPROVE)
Class: 5+P — normative spec text lands ([DOM-2], [DOM-5], [DOM-10], [DOM-11],
[DOM-14], [AT-REF-1]–[AT-REF-5]), and shared agent context, runbooks, skills,
and gate scripts are materially changed. Effective requirements: Class 5 plus
pre-landing different-family review, scoped per the hub's propagate-guidance
skill step 6 (source content is hub-reviewed; review covers adaptation only).
Hardening: N/A — no [DOM-5] product risky trigger fires (docs and doc-gate
scripts only; gate-script enhancements are additive and verified via
`--self-test` and existing pytest suites).

## Goal

Propagate the `agent-theory` delta wave from hub pin `8f41a9d` into Taut
(previous hub pin `0423923`, landed at `4e3f12f` on 2026-08-07). The delta
spans two hub clusters:

1. **Empirical review discipline, migration/coalescing hardening, and gate
   upgrades (`0423923..93ef65c`):**
   - [DOM-2], [DOM-5], [DOM-10], [DOM-11], and [DOM-14] refinements:
     canonical review-tier hierarchy (Tier 1 cross-family, Tier 2 native
     subagent fallback after two bounded logged Tier-1 attempts, Tier 3 raw
     HTTP forbidden), plan revision tracking (`Reviewed baseline:` header and
     `## Revision Log`), verification gate floor (empirical premise check,
     mutated-or-unimplemented RED test failure, full CI root scope,
     migration/import fixture lineage, and command-verified counts), and
     noncontiguous lesson fold records plus discipline-vs-product fold-up
     routing.
   - Shared context updates across `AGENTS.md`, `docs/agent-context/README.md`,
     `docs/agent-context/context.index.yaml`,
     `docs/agent-context/decision-hierarchy.md`,
     `docs/agent-context/principles.md`, and
     `docs/agent-context/engineering-principles.md` (§2 config threading, §3
     startup order, §4 contention stop-condition and module-owned seams, §8
     Tier-1/Tier-2 review hierarchy and empirical checks, §10 migration
     fixture lineage, §11 full-repo search before negative lifecycle labels,
     §12 command-verified counts, §14 governed static complexity suppression
     registry, and Warning Signs).
   - Runbook updates across `review-loops-and-agent-bootstrap.md`,
     `writing-plans.md`, `testing-patterns.md` (Rules 7–10, Pattern 9),
     `hardening-plans.md` (§1 standing invariants, §13 owning cleanup
     contract, §15 stale-remote guard and failure-path verification),
     `writing-specs.md` (§9 `_Traceability:` directives, clause-by-clause
     hazard audit), and `maintaining-traceability.md`.
   - Skill updates across `skills/call-agent/SKILL.md`,
     `skills/coalescing/SKILL.md`, `skills/debugging/SKILL.md`, and
     `skills/crystallize-program-theory/SKILL.md` (Step 7 9-item product-apex
     owner checklist).
   - Gate script upgrades in `bin/check-doc-paths`
     (`DECLARED_FUTURE_ARTIFACTS`, stale/unused allowlist checks, symlink
     awareness, and `--self-test`), `bin/check-dom15-fixtures`
     (`CLAUSE_SPLIT_RE`, `has_negative_fact`, clause-scoped
     `states_firing_trigger`, and expanded mutation probes), and
     `bin/coalesce-check` (`FOREIGN_MARKER_RE` word-boundary nearest-preceding
     attribution and `resolve_remote_ref()`).
2. **STE100 readability pass (`93ef65c..8f41a9d`):**
   - Tightened sentence length, active voice, and bullet structure across
     `docs/README.md` and `docs/specs/07-agent-theory-and-program-theory.md`
     while preserving every `[AT-REF-*]` heading code, Taut's layered product
     ownership sections, and Taut's Active `docs/program-theory.md` routing.

## Source Documents

- `docs/specs/01-development-documentation-operating-model.md`
  ([DOM-2], [DOM-5], [DOM-10], [DOM-11], [DOM-14], [DOM-15])
- `docs/specs/07-agent-theory-and-program-theory.md`
  ([AT-REF-1]–[AT-REF-5])
- Hub source, pinned: `agent-theory` @ `8f41a9d` — extracted from committed
  hub history via `git -C /Users/van/Developer/agent-theory show 8f41a9d:<path>`.

## Invariants and Adaptations

1. **Preserve Taut-local spec extensions:**
   - Keep `[DOM-10.1]`, `[DOM-10.2]`, `[DOM-10.2.1]`, and `[DOM-10.3]` in
     `docs/specs/01-development-documentation-operating-model.md`.
   - Keep Taut's `[DOM-14]` bounded-maintenance and status-index gate bullets
     and `[DOM-15]` routine-release exception (`bin/release.py`) and
     classification fixtures.
   - Keep Taut's reference primer at
     `docs/specs/07-agent-theory-and-program-theory.md` (`02-` in Taut is
     `docs/specs/02-taut-core.md`) and retarget hub references from `02-` to
     `07-`.
2. **Preserve Taut-local documentation ownership and tool commands:**
   - Keep `docs/README.md` layered product ownership (`## Layers and Ownership`
     and `### Known documentation gaps`) and single canonical startup order
     delegation.
   - Keep Taut's Ruff complexity and governed suppression registry contract
     (`bin/ruff_suppression_index.py --check`, `[DOM-10.2.1]`,
     `tests/test_ruff_suppression_index.py`) and Taut's root static check list
     (`taut bin tests extensions`).
   - Keep Taut's release-helper specifics (`bin/release.py`, four release tag
     families, `require-green-workflows.py`) in
     `docs/agent-context/runbooks/hardening-plans.md` §15 alongside the hub's
     stale-remote guard and failure-path verification rules.
3. **Preserve Taut-local gate architecture:**
   - `bin/check-doc-paths` continues to import Taut's single path-claim grammar
     from `tests/test_docs_references.py` while adding
     `DECLARED_FUTURE_ARTIFACTS`, stale/unused allowlist checks, symlink
     support, and `--self-test`.
   - `bin/check-dom15-fixtures` continues to use `bin.markdown_fences.prose_lines`
     and Taut's `ROUTINE_RELEASE_FIXTURE_MARKER` while adopting the hub's
     clause-split negative/firing trigger checks and mutation self-tests.
   - `bin/coalesce-check` continues to expose `ClaimClassification`,
     `classify_claims`, `retired_plan_claims`, `retired_plan_problems`, and
     `lessons_counts` for `tests/test_coalesce_check.py` while adopting
     `FOREIGN_MARKER_RE` and `resolve_remote_ref()`.
   - Never write backticked foreign plan paths in scanned surfaces; quote
     foreign plan names with repository attribution instead.

## Deviation Log

| Spec ref | Planned behavior | Actual behavior | Rationale | Spec proposal |
|----------|------------------|-----------------|-----------|---------------|

## Tasks

1. Update `docs/specs/01-development-documentation-operating-model.md` and
   `docs/specs/07-agent-theory-and-program-theory.md` with the `8f41a9d`
   normative and STE100 deltas while preserving Taut-local sections and
   `07-` numbering.
2. Update `AGENTS.md`, `docs/README.md`, and `docs/agent-context/`
   (`README.md`, `context.index.yaml`, `decision-hierarchy.md`,
   `principles.md`, `engineering-principles.md`, and six runbooks).
3. Update `skills/call-agent/SKILL.md`, `skills/coalescing/SKILL.md`,
   `skills/debugging/SKILL.md`, and
   `skills/crystallize-program-theory/SKILL.md`.
4. Upgrade `bin/check-doc-paths`, `bin/check-dom15-fixtures`, and
   `bin/coalesce-check` while keeping cyclomatic complexity within Taut's
   `C901 <= 10` policy and preserving governed `# noqa` suppressions.
5. Register this plan as `active` in `docs/plans/README.md` and run all
   verification gates (`bin/check-dom15-fixtures`, `bin/check-doc-paths`,
   `bin/check-plan-status-index`, `bin/coalesce-check`, targeted pytest
   modules, Ruff check/format, and `git diff --check`).
6. Run scoped cross-family adaptation review and close the plan upon landing.

## Out of Scope

- Product runtime changes in `taut/` or `extensions/`.
- Executing a full coalescing harvest sweep in this change.

## Review Log

| Date | Stage | Reviewer / result | Findings and disposition |
|------|-------|-------------------|--------------------------|
| 2026-10-14 | Scoped adaptation review | `codex` (Tier-1 CLI) / `APPROVE` | 1. (Non-blocking, line 89) Replace nonexistent `taut/ruff_suppression_inventory.toml` reference with `[DOM-10.2.1]` — fixed. 2. (Non-blocking, line 151) Update `"22-file"` count to `"24-file"` (23 tracked files + new plan) — fixed. |

## Execution Log

(append-only)

- 2026-10-14: Prepared the 24-file `agent-theory` @ `8f41a9d` delta wave in
  the working tree (specs, `AGENTS.md`, `docs/README.md`, `docs/agent-context/`,
  `skills/`, `bin/` gates, and plan index) and verified all doc, fixture,
  coalescing, Ruff, and pytest gates.
- 2026-10-14: Tier-1 `codex` scoped adaptation review returned `APPROVE`;
  applied both non-blocking plan notes and closed the plan as `completed`.
