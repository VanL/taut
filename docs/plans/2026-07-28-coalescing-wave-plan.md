# Coalescing Wave

Status: Completed and landed by targeted commit after the user-approved
maintenance amendment, forward-use validation, final gates, and independent
review all passed.

Class: 5+P — revising normative [DOM-14] independently fires Class 5, and the
bounded-maintenance rule materially changes how future sweeps are planned,
executed, and verified. The change also revises the coalescing skill,
plan-status workflow, and executable gate.

Hardening: N/A — no [DOM-5] risky trigger fires. This phase repairs
documentation and adds a read-only checker; it does not delete lessons,
advance watermarks, soft-retire or delete plans, or create commits.

## Goal

Derive and maintain the current coalescing state: repair reversible,
evidence-backed defects that prevent accurate memory derivation, harvest
completed-plan and workflow promotion candidates, preserve cold lesson
evidence, and retain separate authority for destructive retirement.

## Source Documents

Source specs:

- `docs/specs/01-development-documentation-operating-model.md` [DOM-14],
  [DOM-15]

Operational sources:

- `docs/coalescing.md`
- `skills/coalescing/SKILL.md`
- `docs/lessons.md`
- `docs/plans/README.md`
- `docs/agent-context/runbooks/writing-plans.md`
- `docs/agent-context/runbooks/maintaining-traceability.md`
- `docs/agent-context/runbooks/skills-lifecycle.md`
- `docs/agent-context/runbooks/testing-patterns.md`
- `tests/test_plan_status_index.py`
- `bin/check-plan-status-index`

## Spec Baseline

Spec baseline: commit `8509dc47efa5ab7e353169f4df1e92ef98ee329d`.
The governing [DOM-14] text is clean relative to that commit. During the plan
review, a concurrent session landed the product work as commit
`788cdd3884c29a68753e8ba9e244907d4e1a4455`; [DOM-14],
`docs/coalescing.md`, and `skills/coalescing/SKILL.md` did not change. That
commit contains the new 2026-07-28 lesson and, because the files were shared,
the coalescing plan's status-index row, but not this plan file. The wave uses
`788cdd3884c29a68753e8ba9e244907d4e1a4455` as its execution source
checkpoint and must leave the index reference resolvable before closeout.

Promotion strategy: A — promote the reviewed [DOM-14] maintenance text into
the active spec before changing the dependent coalescing skill, status-index
runbook, checker, or index. Promotion baseline will be recorded as
`788cdd3884c29a68753e8ba9e244907d4e1a4455` plus the post-review worktree
spec file SHA-256
`241270d6163d8c0bfa6b6214593a69fc5f56c7908a96ca7e39fbba6de56127d8`
(strategy-A promotion applied; uncommitted worktree).

## Proposed Spec Delta

In [DOM-14], keep every current trigger, checkpoint, age-floor, fold-cue,
importance-floor, and retirement rule. Add these requirements after the
session-start authorization rule:

> An authorized coalescing sweep is both memory compaction and bounded
> maintenance. Before distillation or retirement, inspect the coalescing
> surfaces for defects that make memory inaccurate, non-derivable,
> unreachable, or unverifiable. Repair an observed defect in the same wave
> when the repair is inside the declared coalescing boundary, reversible, and
> supported by current-tree or source-SHA evidence. Merely logging such a
> repairable defect is not a valid completed sweep.
>
> Bounded maintenance is not general cleanup. It covers the lesson ledger,
> plan status index and retirement ledger, fold cues and watermarks,
> traceability needed to retrieve folded material, promotion ownership, and
> the coalescing gates themselves. Product behavior, unrelated documentation,
> and speculative redesign remain outside the sweep.
>
> Ambiguous repairs, destructive actions, and changes that require new
> authority are deferred explicitly with the evidence gap, owner, and
> reconsideration condition. Existing landing authorization remains mandatory
> for deletion, watermark advancement, plan soft-retirement, and other
> destructive or archival transitions.
>
> Enumerable coalescing metadata uses an executable gate. In this repository,
> every plan file appears exactly once in a structured status index with an
> allowed lifecycle status and explicit exemplar marker. The closed status
> vocabulary is `draft`, `active`, `status-review`, `completed`, `superseded`,
> and `retired-pending`; `status-review` is a conservative maintenance
> quarantine, not a completion state. The exemplar field is exactly `yes` or
> `no`. Missing rows, duplicate rows, nonexistent-path rows, unknown statuses,
> unknown exemplar values, and malformed status tables fail the gate. A sweep
> repairs gate failures before trusting the affected trigger count.

Extend the run-log requirement:

> Each run-log entry records both folds and maintenance repairs. If a detected
> defect is deferred, the log names why it was unsafe or unauthorized to
> repair rather than presenting diagnosis alone as maintenance.

Replace [DOM-14]'s closing operating-metadata paragraph with:

> Owner: whoever the sweep check nags — any agent that observes a tripped
> threshold at session start. Boundary: lessons, plans, runbook and skill
> promotion, retrieval cues and watermarks, and the gates that make those
> coalescing surfaces accurate and derivable; product behavior and unrelated
> cleanup remain outside the sweep. Verification: the run log, the repository
> traceability gate, and every executable coalescing metadata gate (in this
> repository, `bin/check-plan-status-index`). Required action: report a
> session-start trip; inside an authorized sweep, repair reversible,
> evidence-backed in-boundary defects before folding, and explicitly defer
> only ambiguous, destructive, or unauthorized repairs with their owner and
> reconsideration condition.

## Context and Key Files

- `docs/coalescing.md` owns thresholds, watermarks, deferral state, and the run
  log. This wave may append a run-log claim and update deferral state, but may
  not advance a watermark.
- `docs/lessons.md` is a repo-wide dated ledger. The lessons fold unit is one
  dated entry; the 30-day age floor and active-theme exclusions apply before
  the threshold comparison.
- `docs/plans/README.md` is the checked status source and owns the
  retired-plans ledger. The maintenance amendment replaced its incomplete
  Active Plans prose with one structured row per plan file.
- `bin/check-plan-status-index` owns the deterministic index grammar,
  completeness, status vocabulary, exemplar field, and truthful exit codes.
- `tests/test_plan_status_index.py` fires every allowed status and every
  declared index defect.
- `docs/plans/*.md` provide fallback evidence for omitted or ambiguous status
  rows. A status word alone does not pass the four-part harvest gate.
- `skills/` and the agent-context runbooks are promotion destinations only
  when three independent citations identify the same workflow, failure
  surface, and fix shape and no current owner already covers it.

## Invariants and Constraints

- Preserve all pre-existing worktree changes. Use localized inserts and do not
  reflow contested files.
- Derive counts from watermarks and current files; do not copy the prior
  hot-inclusive count.
- Do not fold a lesson that is young, cited by an active plan, or in a theme
  that is still accumulating.
- Do not infer plan completion from age or filename. Distinguish completed,
  ambiguous, and active status evidence.
- Do not soft-retire a plan until its deviation log, durable-rationale,
  lesson-extraction, and backlink gates all pass.
- Do not delete raw material, advance a watermark, soft-retire a plan, or
  commit without explicit landing authorization and a source SHA that contains
  the material.
- Do not create a skill for a theme already owned by an existing skill or
  runbook.
- A run-log line is a claim and must match the derived artifacts and current
  verification result.
- Coalescing maintenance repairs only defects that affect memory accuracy,
  derivability, retrieval, traceability, or the coalescing machinery. It does
  not authorize generic cleanup.
- Unknown plan outcomes remain `status-review`; do not infer completion from
  age, filename, or implementation-shaped prose.
- The closed statuses are `draft`, `active`, `status-review`, `completed`,
  `superseded`, and `retired-pending`; exemplar values are `yes` and `no`.
  Each value gets a firing test. Missing, duplicate, nonexistent-path,
  unknown-status, unknown-exemplar, and malformed-table defects each get a
  rejection test.

## Execution Plan

1. Derive tier counts and pin evidence.
   - Count cold lesson entries after the 2026-06-14 watermark and through the
     2026-06-28 age cutoff for this 2026-07-28 wave.
   - Reconcile Active Plans rows with `Status:` headers and the empty retired
     ledger. Record exact completed, ambiguous, active, exemplar, and omitted
     sets.
   - Gather explicit workflow citations and cluster only semantically identical
     themes.
2. Run the lessons disposition.
   - Check each cold entry for active-plan citations and existing
     distillation.
   - Because this is additive-only, keep every raw entry and the watermark
     unchanged even if a future fold candidate is found.
3. Run the plan harvest gate.
   - Produce a reviewable candidate ledger with each gate result and blocker.
   - Do not convert backlinks or add retired-ledger rows in this wave.
4. Run the promotion disposition.
   - Record already-owned themes separately from genuinely missing workflow
     owners.
   - Escalate classification and obtain process review before any material
     skill or runbook edit.
5. Close the run.
   - Update `docs/coalescing.md` with derived counts, checked-through state,
     blockers, reconsideration conditions, and the additive-only boundary.
   - Update `docs/plans/README.md` only as needed to make the wave itself
     discoverable; leave retirement changes for a landing-authorized pass.
   - Report every wave-owned insert by file, subsection, and approximate line
     so a landing agent can stage and reconcile it independently from the
     concurrent product work.
   - Run the current documentation reference gates.
6. Promote and implement the user-approved maintenance amendment.
   - Obtain independent review of the exact Proposed Spec Delta.
   - Promote [DOM-14] with strategy A and record the promotion baseline.
   - Add red checker tests for every allowed status and defect class.
   - Implement `bin/check-plan-status-index` and make the tests green.
   - Replace the incomplete prose list with a structured, exhaustive index.
     Use `status-review` wherever completion is not evidence-backed.
   - Update `writing-plans.md` and `skills/coalescing/SKILL.md` so maintenance
     precedes distillation and retirement.
   - Re-run the checker, docs gates, skill validation or the repository's
     local equivalent, and independent completed-work review.

## Testing Plan

- `git diff --check`
- `python -m pytest tests/test_docs_references.py`
- `bin/check-dom15-fixtures`
- `python -m pytest tests/test_plan_status_index.py`
- `bin/check-plan-status-index --self-test`
- `bin/check-plan-status-index`
- targeted scripts or read-only checks recorded beside each derived count
- independent plan review before tier edits
- independent completed-work review after the documentation diff exists

## Verification

Rule 5 substitute proof: this is a documentation-maintenance wave with no
product behavior change. The additive derivation used the reproducible
pre-change failure in the non-derivable status index. The process amendment
does have an executable red-green boundary: checker tests must fail because
`bin/check-plan-status-index` and the structured index contract do not yet
exist, then pass after implementation.

Observed 2026-07-28:

- `git diff --check` — exit 0.
- `python -m pytest tests/test_docs_references.py -q` — 10 passed.
- `bin/check-dom15-fixtures` — fixture contract OK.
- canonical lessons derivation —
  `TOTAL_DATED=90 POST_WATERMARK=87 COLD_BY_DATE=2`.
- plan corpus derivation — 48 files at `788cdd38`, plus this wave = 49
  working-tree files; the pre-maintenance source had 27 indexed, 22 omitted,
  and 0 retired.
- `git cat-file -e <source-sha>:<plan-path>` — all four first-batch source
  cues resolve.
- checker TDD red — 20 expected failures while
  `bin/check-plan-status-index` did not exist.
- checker/index boundary red — 19 passed and 1 failed after checker
  implementation exposed the live malformed prose index.
- checker/index green — 20 passed after the index repair; the final malformed
  separator probe raised the maintained suite to 21 passed;
  `bin/check-plan-status-index --self-test` and
  `bin/check-plan-status-index` both exit 0.
- normalized plan derivation — 49 indexed files: 47 `completed`, 2
  `superseded`, 1 exemplar, and 0 retired. The closeout trigger count is 48
  completed/superseded non-exemplars.
- final gate bundle — `git diff --check` exit 0; 31 focused tests passed
  (`tests/test_docs_references.py` plus `tests/test_plan_status_index.py`);
  DOM-15 fixtures passed; checker self-test and live-index check passed;
  checker byte-compilation passed; index SHA-256 matched
  `61ad88e66fc8d4307183fcc38f74e9eabca5457cba195c3117efad0c64c34ad6`.

## Review Path

Use the repository `call-agent` skill with a review-eligible different-family
agent.

- Plan review inputs: [DOM-14], this plan, `docs/coalescing.md`,
  `skills/coalescing/SKILL.md`, `docs/plans/README.md`, and the declared
  baseline. This pass occurs before any tier-state edit.
- Completed-work review inputs: the same governing files plus the wave-owned
  diff, derived-count evidence, candidate artifact, and verification results.

Every finding is reproduced and dispositioned here before execution or
completion.

## Out of Scope

- product behavior, code, release, or dependency changes
- physical plan deletion
- destructive lesson folding
- threshold or fold-unit changes
- generic repository cleanup outside coalescing accuracy and retrieval
- cross-repository propagation

## Deviation Log

| Spec ref | Planned behavior | Actual behavior | Rationale | Spec proposal |
|----------|------------------|-----------------|-----------|---------------|
| [DOM-14] baseline `8509dc47` | Preserve concurrent dirty hunks and use a later source checkpoint | Concurrent session landed the reaction slice as `788cdd38`, including the wave's README row but excluding this untracked plan; raw-material evidence was re-pinned to `788cdd38` | Shared-worktree commit occurred during the read-only plan review on 2026-07-28 | None; [DOM-14] was unchanged |
| [DOM-14] additive-only boundary | Diagnose defects and defer repairs outside the additive boundary | Reopen the wave as Class 5+P, repair evidence-backed defects, and add the durable maintenance process and gate | Explicit user correction on 2026-07-28: coalescing is maintenance as well as memory management | Exact Proposed Spec Delta above |
| [DOM-14] closing operating metadata | Replace the closing paragraph with the reviewed bounded-maintenance wording | Promoted the reviewed maintenance contract while retaining the pre-existing guidance-repository cross-repo fold-up boundary and the rule that specs and implementation docs are maintained, not coalesced | A literal replacement would have silently removed two orthogonal, already-approved boundaries; preserving them avoids a normative regression | None; the merged active-spec text is the intended contract |

## Plan Review

Different-family review: Claude Sonnet, read-only repository tools,
2026-07-28. Verdict: PASS.

| Finding | Disposition |
|---------|-------------|
| P2: required Fresh-Eyes Review section was absent | Accepted; the section and completion gate were added below. |
| P2: concurrent-session insert-region reporting was not an execution step | Accepted; closeout now requires file, subsection, and approximate-line reporting. |
| P2: plan-review and completed-work-review inputs were conflated | Accepted; Review Path now names separate input sets. |
| P3: canonical `Testing Plan` and `Spec Baseline` headings were absent | Accepted; the content now has the canonical headings. |
| P3: Out of Scope did not explicitly bar skill/runbook creation | Accepted; the exclusion is now explicit. |

Reviewer observations confirmed that the Active Plans index is incomplete,
free-form plan statuses require an ambiguous bucket, the baseline is exact,
and the named documentation gates exist. None changed the execution boundary.

### Maintenance amendment review

Different-family review round 1: Claude Sonnet, read-only repository tools,
2026-07-28. Verdict: BLOCKED.

| Finding | Disposition |
|---------|-------------|
| P1: the plan required exhaustive status tests without enumerating the allowed statuses | Accepted; the Proposed Spec Delta and invariants now close the vocabulary over six statuses and two exemplar values. |
| P2: [DOM-14]'s closing owner/boundary/verification/action paragraph would remain stale | Accepted; the delta now replaces it and names the coalescing gate and bounded maintenance action. |
| P3: Deviation Log columns were non-canonical | Accepted; the table now uses the writing-plans schema. |
| P3: Class 3+P under-cited the direct Class 5 spec-edit trigger | Accepted; classification is now Class 5+P. |

Round 2: FAIL. F1, F2, and F4 passed. F3 exposed a new mismatch: the first
fix retained a non-canonical `Date` column. The table now uses the exact
five-column schema from `writing-plans.md` §4a, with dates preserved in the
rationale text. Round 3, scoped to F3 only: PASS.

## Initial Additive-Wave Fresh-Eyes Review

Author fresh-eyes pass, 2026-07-28:

- reproduced the lesson and plan corpus counts from the current tree;
- verified `788cdd38` contains both cold lesson entries and all 33 provisional
  implementation-shaped plan candidates;
- verified all four first-batch source cues at their plan-specific SHAs;
- confirmed no raw lesson, plan status, backlink, retired-ledger row,
  watermark, skill, or runbook changed;
- confirmed the wave-owned diff is limited to `docs/coalescing.md` and this
  new plan. The plan's Active Plans row was already committed by the
  concurrent reaction landing.

This was the pre-amendment state. The maintenance pass subsequently resolved
all 14 plan-status ambiguities from source-SHA and repository-history evidence,
added the literal exemplar marker, and made the index executable.

## Execution Record

### Lessons tier

The canonical dated-bullet command finds 90 lesson entries at source checkpoint
`788cdd38`: 87 after the 2026-06-14 watermark. The broader loose-date count is
91 because it also includes the already-folded 2026-06-12 summary bullet; that
summary is not a fold unit. Applying the 30-day age floor through 2026-06-28
leaves exactly two cold entries, both dated 2026-06-17:

- cross-backend integer widths as executable portability constraints;
- backend selection through the real resolution path.

They form a coherent two-entry portability candidate, below both the
three-entry distillation floor and the lessons threshold of 20. They remain
verbatim. No lesson text or watermark changed. Reconsider on 2026-08-07, when
the large 2026-07-08 block crosses the age floor.

Evidence:

- dated-entry derivation: `TOTAL_DATED=90`, `POST_WATERMARK=87`,
  `COLD_BY_DATE=2`;
- `git show 788cdd38:docs/lessons.md` contains both cold entries;
- repository searches found no explicit active-plan citation to either raw
  lesson.

### Plans tier

The initial additive-only diagnosis found:

Corpus reconciliation:

- 48 plan files at source checkpoint `788cdd38`, plus this wave = 49
  working-tree plan files;
- 27 Active Plans index rows;
- 22 files omitted from the index;
- 0 retired-ledger rows;
- formal completed count not derivable from the pre-maintenance status source;
- 33 provisional implementation-shaped non-exemplar candidates from full
  status-header and history inspection;
- 14 ambiguous or conflicting statuses;
- 1 active plan (this wave);
- 1 semantic exemplar
  (`2026-07-14-agent-interfaces-runbook-adoption-plan.md`), whose index row
  says it is retained for review dispositions but lacks the literal
  `exemplar` marker. A strict header scan would therefore include it as a 34th
  implementation-shaped candidate; neither number is a valid completed count
  until the primary index is normalized.

Provisional implementation-shaped candidates (not a completed count):

- `2026-06-12-taut-0.1.1-hardening-plan.md`
- `2026-06-12-taut-foundation-plan.md`
- `2026-06-17-github-actions-release-workflows-plan.md`
- `2026-06-17-github-release-helper-plan.md`
- `2026-06-17-implementation-review-followups-plan.md`
- `2026-06-17-taut-pg-extension-plan.md`
- `2026-06-18-member-identity-addressing-plan.md`
- `2026-06-18-simplebroker-latest-timestamp-plan.md`
- `2026-06-30-assets-reference-cleanup-plan.md`
- `2026-06-30-client-module-split-plan.md`
- `2026-07-01-schema-shim-retirement-plan.md`
- `2026-07-01-taut-state-sql-dialect-plan.md`
- `2026-07-01-taut-watch-runtime-plan.md`
- `2026-07-06-taut-summon-plan.md`
- `2026-07-09-taut-reactor-safety-plan.md`
- `2026-07-10-ci-failure-remediation-plan.md`
- `2026-07-10-taut-dynamic-native-waiter-replacement-plan.md`
- `2026-07-10-taut-summon-quality-remediation-plan.md`
- `2026-07-11-multi-factor-review-remediation-plan.md`
- `2026-07-11-v0.5.2-coordinated-release-plan.md`
- `2026-07-12-lazy-command-extensions-and-rich-tui-composition-plan.md`
- `2026-07-13-bounded-summon-process-test-parallelism-plan.md`
- `2026-07-13-ci-speed-determinism-release-evidence-plan.md`
- `2026-07-13-release-metadata-preparation-plan.md`
- `2026-07-13-summon-stop-release-race-plan.md`
- `2026-07-14-blank-message-no-op-plan.md`
- `2026-07-14-single-project-config-source-spec-plan.md`
- `2026-07-14-smaller-quality-followups-plan.md`
- `2026-07-14-terminal-output-safety-plan.md`
- `2026-07-15-per-call-read-limit-plan.md`
- `2026-07-15-taut-0.7.1-portability-and-coverage-plan.md`
- `2026-07-27-message-show-delete-plan.md`
- `2026-07-28-message-react-plan.md`

Ambiguous or conflicted status candidates:

- `2026-07-06-evaluation-findings-remediation-plan.md`
- `2026-07-06-taut-summon-spec-draft.md`
- `2026-07-07-taut-summon-pty-harness-adapter-plan.md`
- `2026-07-08-release-helper-simplebroker-port-plan.md`
- `2026-07-08-taut-sqlite-contention-hardening-plan.md`
- `2026-07-12-automatic-display-name-capitalization-plan.md`
- `2026-07-14-agent-guidance-propagation-plan.md`
- `2026-07-14-routine-release-classification-plan.md`
- `2026-07-14-taut-mcp-extension-plan.md`
- `2026-07-14-taut-tui-cross-reference-correction-plan.md`
- `2026-07-14-trusted-identity-selector-fast-path-plan.md`
- `2026-07-14-universal-release-gates-plan.md`
- `2026-07-15-taut-mcp-release-integration-plan.md`
- `2026-07-17-agent-guidance-propagation-plan.md`

All 33 provisional candidates exist at source checkpoint `788cdd38`. Of those,
16 lack canonical deviation logs, 13 need an explicit lessons-applicability
judgment, and 3 need an explicit durable-rationale or no-durable-rationale
judgment. Thirty have 49 convertible spec backlinks. The missing reciprocal
backlink on `2026-07-13-summon-stop-release-race-plan.md` is a real blocker.
More importantly, the pre-maintenance `docs/plans/README.md` was not a
machine-usable primary status source: its 27 rows mixed active, completed, and
transient descriptions without
a status field while omitting 22 files. The formal [DOM-14] completed count is
therefore blocked at that stage. The lists above are retained as the
diagnostic evidence that motivated the repair, not as the current derivation
or retirement authorization.

Independent traceability inspection found this first soft-retirement batch
had complete content-harvest evidence. At that stage, each row still needed
explicit status normalization in the primary index plus landing authorization:

| Plan | Source SHA | Backlinks | Harvest disposition |
|------|------------|-----------|---------------------|
| `2026-07-10-ci-failure-remediation-plan` | `b03709452` | core and Summon specs | deviation log closed; rationale absorbed; related lessons exist |
| `2026-07-14-single-project-config-source-spec-plan` | `db67b94b` | core spec | deviation log closed; governing spec is the durable rationale; no separate lesson needed |
| `2026-07-14-terminal-output-safety-plan` | `281f04fa` | core and Summon specs | deviations resolved; rationale absorbed; terminal-safety lessons extracted |
| `2026-07-15-per-call-read-limit-plan` | `4a129e94` | core spec | no behavior deviation; rationale absorbed; no separate lesson needed |

The initial additive-only pass changed no plan status, backlink, ledger row, or
file. The user-approved maintenance amendment below then repaired the status
index without performing retirement.

Maintenance reconciliation resolved every provisional and ambiguous row using
plan-local evidence plus source-SHA or repository-history checks. The canonical
index now derives:

- 49 plan files and exactly 49 index rows;
- 47 `completed` and 2 `superseded`;
- 1 literal exemplar (`yes`) and 48 non-exemplars (`no`);
- 0 retired-ledger rows;
- 48 completed/superseded non-exemplars eligible against threshold 8.

The maintenance repair changes the conclusion, not the authority boundary:
the plan tier is tripped, but soft retirement and backlink conversion still
require a landing-authorized pass. The four previously harvested plans remain
the first reviewable batch.

### Promotion tier

Three coherent themes crossed the three-citation threshold:

| Theme | Citations | Disposition |
|-------|-----------|-------------|
| Real-process xdist lane isolation and resource ownership | 10 | Exact behavior is owned by [TAUT-12.5], Summon implementation guidance, release machinery, and tests; no new skill |
| xdist worker-kill timeout containment | 7 | Genuine future amendment to `docs/agent-context/runbooks/testing-patterns.md`: risky signal/reactor behavior belongs in a probe child while the parent worker owns watchdog and structured assertions |
| Summon consumer/control readiness barrier | 8 | Fully owned by [SUM-5.1] and the Summon architecture note; no new skill |

The promotion tier is tripped, but it yields zero new skills and one material
runbook-amendment candidate. The initial additive wave remained Class 3 because
it recorded but did not implement that separate Class 3+P process change. The
maintenance amendment raised this plan to Class 5+P for the [DOM-14] change,
but did not implement the unrelated testing-patterns candidate. No promotion
watermark advanced.

### Wave-owned insert regions

- `docs/coalescing.md`, `Watermarks`, `Deferral State`, and the first three
  `Run Log` rows (approximately lines 58–95).
- `docs/plans/README.md`, `Plan Status Index`.
- `docs/plans/2026-07-28-coalescing-wave-plan.md`, entire new plan. Its
  original Active Plans row was committed by the concurrent reaction landing
  at `788cdd38`.
- `docs/specs/01-development-documentation-operating-model.md`, [DOM-14].
- `docs/agent-context/runbooks/writing-plans.md`, lifecycle/status-index rules.
- `skills/coalescing/SKILL.md`, purpose, prerequisites, maintenance phase,
  plan derivation, and run-log/output requirements.
- `bin/check-plan-status-index`, entire new checker.
- `tests/test_plan_status_index.py`, entire new contract suite.

### Maintenance amendment

Implemented:

- independently reviewed and promoted the [DOM-14] bounded-maintenance
  contract while preserving two pre-existing orthogonal boundaries, as
  declared in the deviation log;
- added red-green contract coverage for all six statuses, both exemplar
  values, all six declared defect classes, current-repository acceptance, and
  invocation-error behavior;
- added `bin/check-plan-status-index` with truthful 0/1/2 exit semantics and a
  built-in self-test;
- replaced the incomplete prose registry with an exhaustive structured index;
- updated `writing-plans.md` and the coalescing skill so inspection and repair
  precede derivation, distillation, and retirement;
- updated `docs/coalescing.md` with the repaired count and explicit retirement
  deferral.

No plan was soft-retired or deleted. No backlink was converted and no watermark
advanced. The user authorized a targeted commit after the final review.

### Forward-use skill validation

A fresh agent used only the revised skill and repository sources, read-only.
It independently derived 49 plans, 46 completed, 2 superseded, 1 active, 1
exemplar, 0 retired, and 47 trigger-eligible plans. The checker, self-test, and
all 20 contract tests present during that forward test passed; the final
malformed-separator probe later raised the maintained suite to 21.

The forward test found one instruction defect: `plus current wave` was not a
content-addressed checkpoint, so a later session could reproduce the count but
could not prove whether the status-index reconsideration condition had fired.
Accepted and repaired: the skill now requires content hashes for dirty
derivation sources. The forward test used index SHA-256
`3fe2e50b5603a4fdea6373eedf6a0ffc2a85b6d434aec697e53545510aab9b0e`;
the completion transition produced the final closeout hash recorded above.

## Initial Additive-Wave Completed-Work Review

Different-family review round 1: Claude Sonnet, read-only repository tools,
2026-07-28. Verdict: BLOCKED.

| Finding | Reproduction and disposition |
|---------|------------------------------|
| P1: the 33-candidate set was presented as a completed count even though the primary Active Plans index conflicts with plan headers | Accepted. The core defect reproduces: the index is incomplete and mixes status meanings, so a formal completed count is not derivable. The stronger fix marks the tier blocked and relabels 33 as a provisional implementation-shaped set. One reviewer subclaim did not reproduce: all four first-batch plans are in the Active Plans index, not absent from it. They remain content-harvest candidates only until their index statuses are explicit. |
| P3: total lesson count was 91 rather than the canonical command's 90 | Accepted. The loose pattern counted the already-folded 2026-06-12 summary bullet. All evidence now uses the canonical total 90; post-watermark 87 and cold 2 were unchanged. |

Different-family review round 2, scoped to those two accepted fixes: PASS.
The reviewer reproduced the 33-item provisional and 14-item ambiguous lists,
confirmed the four first-batch plans are indexed and explicitly gated on
status normalization, independently reproduced lesson counts 90/87/2, and
found no defect introduced by the fixes.

## Maintenance-Amendment Completed-Work Review

Different-family review round 1: Claude Sonnet, read-only repository tools,
2026-07-28. Verdict: BLOCKED.

| Finding | Reproduction and disposition |
|---------|------------------------------|
| P2: the active [DOM-14] closing paragraph preserved two pre-existing clauses that were absent from the literal reviewed replacement, while the plan claimed an exact promotion and logged no deviation | Accepted. Preserving the guidance-repository fold-up boundary and the rule that specs and implementation docs are maintained rather than coalesced prevents a normative regression. The Deviation Log now declares that merge and the execution record no longer calls it a literal exact replacement. No active-spec change was needed. |

The reviewer independently reproduced the plan counts, status breakdown,
eligible trigger count, source-SHA evidence, authorization boundaries, checker
semantics, firing coverage, and spec/skill/runbook alignment. Its only blocker
was the undeclared merge above.

Round 2 scoped F1 plus post-review deltas D1 and D3: PASS. The reviewer confirmed
the deviation row closes F1; the dirty-source content-hash rule is reproducible;
the current index hash and 49-row status breakdown derive exactly; and the
stricter Markdown separator grammar has a passing rejection test. No new
finding was reported.
