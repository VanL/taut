# Taut TUI Cross-Reference Correction Plan

Class: 5 — the requested correction edits normative text in the active core
spec; [DOM-15] therefore requires a spec-authoring plan even though intended
behavior is unchanged. Hardening: N/A — no [DOM-5] risky trigger fires.

Plan type: spec-authoring clarification.

## Goal

Correct the stale TUI cross-reference in [TAUT-1] so it points to the actual
rich-TUI roadmap contract in [TAUT-12.4], not the watcher contract in
[TAUT-8.4].

## Source Documents

- `docs/specs/02-taut-core.md` [TAUT-1], [TAUT-8.4], [TAUT-12.4]
- `docs/agent-context/runbooks/writing-specs.md`
- `docs/agent-context/runbooks/writing-plans.md`
- `docs/agent-context/runbooks/maintaining-traceability.md`
- `docs/implementation/04-taut-architecture.md`

## Context and Key Files

- Modify `docs/specs/02-taut-core.md`: [TAUT-1] currently says the TUI is
  named in [TAUT-8.4], but [TAUT-8.4] governs the watcher and [TAUT-12.4]
  governs the future rich first-party TUI.
- Modify `docs/plans/README.md`: record this class-5 plan while the work is
  uncommitted.
- This plan is the only new file owned by this correction. No implementation
  or runtime contract is changing, and
  `docs/implementation/04-taut-architecture.md` already keeps the TUI outside
  its core-runtime scope.

## Invariants and Constraints

- The correction changes only citation accuracy; no product behavior,
  roadmap commitment, status, implementation mapping, or code changes.
- [TAUT-8.4] remains the watcher contract.
- [TAUT-12.4] remains the rich first-party TUI roadmap contract and still
  requires a separate product spec before implementation.
- Do not add a new dependency, test fixture, or parallel documentation path.
- Keep the existing [TAUT-1] deferred-scope wording except for the stale
  reference.

## Spec Baseline

- `682cc4488959ddb06472c020c27f07fe425eac32` —
  `docs/specs/02-taut-core.md` at plan authoring time; the initial
  `git status --short` was empty.
- Concurrent worktree context before promotion: a separate
  `2026-07-14-trusted-identity-selector-fast-path-plan.md` task added a
  `docs/specs/02-taut-core.md` Related Plans row and a
  `docs/plans/README.md` Active Plans row after this plan was drafted. Those
  hunks are preserved and remain outside this plan's ownership.
- Promotion baseline: `682cc4488959ddb06472c020c27f07fe425eac32` plus the
  uncommitted worktree after strategy-D promotion. This plan owns only the
  [TAUT-1] TUI-bullet correction and its Related Plans backlink in
  `docs/specs/02-taut-core.md`; the concurrent trusted-identity backlink is
  not part of this delta.

## Proposed Spec Delta

Promotion strategy: D — spec-authoring / clarification only. The active spec
text changes in place; no code or implementation-link claim changes.

| Spec file | Strategy | Section touched |
|-----------|----------|-----------------|
| `docs/specs/02-taut-core.md` | D | [TAUT-1] deferred-scope TUI bullet; `## Related Plans` backlink |

Replace:

> - the TUI (named as a surface in [TAUT-8.4]; it gets its own spec before
>   implementation)

With:

> - the TUI (governed by the roadmap commitment in [TAUT-12.4]; it gets its
>   own spec before implementation)

Add under `## Related Plans`:

> - `docs/plans/2026-07-14-taut-tui-cross-reference-correction-plan.md` —
>   corrects the stale [TAUT-1] TUI citation from watcher section [TAUT-8.4]
>   to the rich-TUI roadmap contract in [TAUT-12.4].

## Deviation Log

| Spec ref | Planned behavior | Actual behavior | Rationale | Spec proposal |
|----------|------------------|-----------------|-----------|---------------|

## Tasks

1. Review this plan and its exact strategy-D delta independently.
   - Reviewer reads this plan and `docs/specs/02-taut-core.md` [TAUT-1],
     [TAUT-8.4], and [TAUT-12.4].
   - Done signal: every finding has an explicit disposition below.
2. Apply the reviewed cross-reference correction and add the plan backlink.
   - File: `docs/specs/02-taut-core.md`.
   - Preserve every adjacent scope statement.
   - Done signal: the stale phrase is absent and the replacement resolves to
     [TAUT-12.4].
3. Reconcile traceability and run the documentation gates.
   - Files: `docs/plans/README.md`, `docs/specs/02-taut-core.md`, and this
     plan.
   - Replace the pending promotion baseline with the post-edit identifier:
     baseline commit plus the named uncommitted spec diff.
   - Done signal: the plan/spec links resolve, no promotion-baseline field is
     pending, and the targeted gates pass.
4. Run an independent completed-work review.
   - Give the reviewer the governing spec, this plan, the complete diff, and
     current verification evidence.
   - Done signal: the reviewer confirms this plan's two spec hunks equal the
     reviewed delta, distinguishes concurrent user-owned hunks, and every
     finding has an explicit disposition below.

## Testing Plan

This is docs-only. The observed red proof is the pre-edit `rg` result showing
`the TUI (named as a surface in [TAUT-8.4]` at line 45. The green proof is a
grep assertion that the stale phrase is absent and the [TAUT-12.4] replacement
is present. Run the repository's real documentation reference test afterward;
no mocks or runtime suite are relevant.

## Verification and Gates

- `! rg -n -F 'the TUI (named as a surface in [TAUT-8.4]' docs/specs/02-taut-core.md`
  must exit 0 because the inner `rg` finds no match.
- `rg -n -F 'the TUI (governed by the roadmap commitment in [TAUT-12.4]' docs/specs/02-taut-core.md`
  must return exactly one match.
- `uv run --extra dev pytest tests/test_docs_references.py` must pass.
- Inspect `git diff --check` and the focused documentation diff.

## Independent Review Loop

Use the repository's `skills/call-agent/SKILL.md` read-only Claude invocation,
which is a different family from the author. Before editing, the reviewer
receives this plan, the exact proposed delta, and the governing spec sections.
After the edit and gates, the reviewer receives the same inputs plus the
complete diff and current verification evidence. Both rounds look for errors,
ambiguity, or needless ceremony. Record every finding and disposition below.

## Review Findings and Dispositions

Review round 1 returned `BLOCKED` on the missing completed-work review and
three P2 execution ambiguities. After amendment, review round 2 returned
`PASS`; it verified all four corrections and raised two further P2s caused by
the concurrent trusted-identity worktree changes. Both were reproduced and
accepted below. The completed-work review then returned `PASS` with no
findings; it reproduced the grep and diff-hygiene gates, confirmed this plan's
owned hunks match the reviewed delta, and confirmed the concurrent hunks remain
intact.

| Finding | Disposition |
|---------|-------------|
| [P1] The draft scheduled independent plan/delta review but omitted the class-5 completed-work review required through [DOM-15]'s cumulative class-3 review floor. | Accepted. Task 4 and the review-loop text now require independent post-edit review of the full diff and current gates. |
| [P2] The exact delta omitted the `## Related Plans` backlink that Task 2 would add. | Accepted. The delta table and exact proposed text now declare the backlink. |
| [P2] No task replaced the pending promotion baseline after the spec-authoring edit. | Accepted. Task 3 now requires the post-edit identifier and forbids a pending closeout field. |
| [P2] Bare `rg` returns status 1 on the intended no-match result. | Accepted. The gate now uses `! rg` and states the expected outer exit status. |
| [P2] Concurrent trusted-identity hunks made the current worktree broader than the original clean-HEAD baseline and made whole-diff equality ambiguous. | Accepted after reproducing the mid-review worktree change. The baseline now names the concurrent hunks, and Task 4 compares only this plan's owned spec hunks. |
| [P2] Task 2 listed this plan as a touched file without naming a Task-2 plan edit. | Accepted. Task 2 now lists only the spec file; plan closeout remains in Task 3. |

## Execution Evidence

- Red observation before the edit: `rg` found the stale [TAUT-8.4] TUI phrase
  at `docs/specs/02-taut-core.md:45`.
- Green stale-reference gate: the negated fixed-string `rg` exited 0 with no
  match.
- Green replacement gate: fixed-string `rg` found exactly one replacement at
  `docs/specs/02-taut-core.md:45`.
- Documentation gate: `uv run --extra dev pytest tests/test_docs_references.py`
  reported `10 passed` on both the pre-review and post-review reruns.
- Diff hygiene: `git diff --check` exited 0 with no output.
- Completed-work independent review: `PASS` with no findings. Residual risk is
  commit-time hunk partitioning because this correction shares the worktree
  with the concurrent trusted-identity task; no commit is authorized here.

## Out of Scope

- Defining or implementing the TUI.
- Revising [TAUT-8.4] or [TAUT-12.4].
- Auditing unrelated cross-references.
- Runtime code, tests, dependencies, release metadata, or implementation docs.

## Fresh-Eyes Review

The change owner will re-read the final diff against [TAUT-1], [TAUT-8.4],
and [TAUT-12.4], confirm the plan contains no unresolved deviation or review
row, and report that the work remains uncommitted unless the user separately
authorizes a commit.
