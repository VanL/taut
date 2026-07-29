# Coalescing State

Status: Active — governed by [DOM-14] in
`docs/specs/01-development-documentation-operating-model.md` (adopted
from agent-guidance @ `2f7eff6` via
`docs/plans/2026-07-14-agent-guidance-propagation-plan.md`).

Owner: any agent that observes a tripped threshold at session start.
Boundary: lessons, plans, skill/runbook promotion, retrieval cues and
watermarks, and the gates that make those surfaces accurate and
derivable. Product behavior and unrelated cleanup remain outside the
sweep. Specs and implementation docs are living documents and are never
coalesced. Verification: the run log below, this repository's
documentation gates (`tests/test_docs_references.py` and
`bin/check-doc-paths`), and every executable coalescing metadata gate
(`bin/check-plan-status-index` for the plan tier, `bin/coalesce-check`
for SHA claims, retrieval cues, and the lessons-tier counts). Required
action: the session-start check is **read-only** — derive the counts,
compare against the deferral state, and report a new trip to the user in
one sentence. Inside an authorized sweep, repair reversible,
evidence-backed in-boundary defects before folding. Destructive steps
additionally require landing authorization.

Counts are always derived from watermarks and the current tree — never
stored, never trusted from memory.

## Fold Unit and Progress Model

Per [DOM-14], each tier's trigger count is denominated in this repo's
fold unit and counts only cold, unfolded material:

- **Lessons.** The fold unit is the **repo-wide dated ledger entry**:
  `docs/lessons.md` is a single chronological bullet list, not a
  domain-grouped set of sections, so the count is repo-wide (not
  per-section) over entries past the lessons watermark that are also past
  the age floor. The progress model is the **lessons watermark used as an
  examined-through date cursor**: taut folds oldest-first and advances the
  watermark only past entries it has examined and dispositioned (folded,
  summarized, or kept-verbatim as a named future candidate), so no
  unexamined material hides behind the cursor. If the ledger ever splits
  into domain sections, switch to per-section watermarks; if folding ever
  becomes theme-cluster-across-dates rather than oldest-first, switch to a
  fold-records index — a bare date cursor would then falsely claim older
  unfolded material behind it was folded.
- **Plans.** The fold unit is the individual plan; progress is tracked by
  the retired-plans ledger in `docs/plans/README.md`, not a cursor —
  completed/superseded plans with no retired-ledger line are the eligible
  count.
- **Promotion.** The fold unit is the workflow theme; progress is the
  promotion watermark over distinct citations since it.

## Thresholds

Calibrated for taut's volume (85 dated ledger entries at adoption);
tune with a run-log note, not ad hoc.

| Tier | Trigger (derived count) | Threshold | Age floor |
|------|------------------------|-----------|-----------|
| Lessons | dated ledger entries after the lessons watermark | 20 | 30 days, and never entries cited by an active plan or in a still-accumulating theme |
| Plans | plans with status completed/superseded, not `exemplar`, and no retired-ledger line | 8 | none — the harvest gate and two-step retirement are the guards |
| Promotion | distinct citations of the same workflow theme (judgment-clustered) since the promotion watermark | 3 | n/a |

## Watermarks

| Tier | Distilled through | Source SHA |
|------|-------------------|------------|
| Lessons | 2026-06-14 | `c09e95e` |
| Plans | (none — first derivation and status-index repair recorded; no retirement checkpoint) | — |
| Promotion | (none — first derivation recorded; no promotion checkpoint in the additive-only wave) | — |

## Deferral State

A trip is only news when it is new: unchanged counts against this table
do not re-nag; a changed count or a fired reconsideration condition
does.

| Tier | Checked through (date, SHA) | Counts at check | Reason deferred | Reconsider when |
|------|------------------------------|-----------------|-----------------|-----------------|
| Lessons | 2026-07-28, `788cdd38` | 87 past watermark: 2 cold and unfolded, 85 inside the age floor; below threshold 20 | Checked-deferred: the two 2026-06-17 cross-backend portability entries form a two-entry candidate and remain verbatim; no lesson or watermark changed | The 2026-07-08 block crosses the age floor on 2026-08-07, or 18 additional cold eligible entries accrue first |
| Plans | 2026-07-28, base `788cdd38`, index SHA-256 `61ad88e66fc8d4307183fcc38f74e9eabca5457cba195c3117efad0c64c34ad6` | 49 indexed plans: 47 completed, 2 superseded, 1 exemplar, 0 retired; 48 completed/superseded non-exemplars are eligible against threshold 8 | Checked-deferred after maintenance repaired the incomplete, free-form status source and added its executable gate. The retirement trigger is tripped, but no soft retirement, backlink conversion, watermark change, or deletion is authorized in this wave | A landing-authorized retirement pass begins with the four-plan harvested batch, or the status index or retired ledger changes |
| Promotion | 2026-07-28, `788cdd38` | 3 coherent themes crossed threshold: 2 already owned, 1 missing runbook amendment, 0 missing skills | First derivation complete. The xdist worker-kill containment pattern belongs in `testing-patterns.md`, but that material process edit requires its own Class 3+P unit; no promotion watermark advanced | A Class 3+P runbook-amendment unit is authorized, or a new unowned workflow theme reaches 3 independent citations |

## Run Log

One line per run, newest first. Each line is a claim; it must survive a
spot-check against the diff. `checked-deferred` lines are valid runs.

| Date | Tier(s) | Source SHA | Claim |
|------|---------|------------|-------|
| 2026-07-28 | — (upstream rename; nothing folded) | — | The guidance hub was renamed `agent-guidance` → `agent-theory` (it names a discipline — theory-building for agent-assisted development — not an artifact of instructions). `bin/coalesce-check`'s sibling list was repointed so hub SHA claims resolve again. Existing provenance lines, run-log rows, and plan filenames naming `agent-guidance` refer to that same upstream repository under its former name and are left as written; git commit messages likewise retain it. |
| 2026-07-28 | — (propagation; nothing folded) | source agent-guidance @ `cec5666`; landed `7afcb14` | Delta wave per `docs/plans/2026-07-28-agent-guidance-delta-wave-plan.md`: cue-portability paragraph, harness scoping sentence, both executable gates (check-doc-paths imports this repo's test grammar + covers this file and the plans index; coalesce-check watermark-denominated, cross-checked 87 against the deferral table). Two items EMPTY — this repo is the fold-up source; hub credits taut `3706d73` as first lineage. First run: local-only pins `788cdd38`, `9221cbd`. Scoped review no blocker. No thresholds, watermarks, or folds touched. |
| 2026-07-28 | Promotion | `788cdd38` | First derivation: three coherent workflow themes crossed the citation threshold. Summon readiness barriers and real-process lane ownership are already owned by product specs and implementation notes; xdist worker-kill containment is a genuine `testing-patterns.md` amendment candidate. No new skill is justified, no process file changed, and no promotion watermark advanced. Candidate evidence is in `docs/plans/2026-07-28-coalescing-wave-plan.md`. Doc references: 10 passed; DOM-15 fixtures and diff check green. |
| 2026-07-28 | Plans + maintenance | base `788cdd38`, index SHA-256 `61ad88e66fc8d4307183fcc38f74e9eabca5457cba195c3117efad0c64c34ad6` | Repaired the non-derivable plan status source: replaced 27 mixed prose rows and 22 omissions with one checked row for each of 49 plan files, using a closed status vocabulary and literal exemplar field. Final derivation: 47 completed, 2 superseded, and 1 exemplar; 48 completed/superseded non-exemplars remain unretired against threshold 8. Added `bin/check-plan-status-index`, 21 contract tests, and coalescing process guidance. No soft retirement, backlink conversion, watermark change, or deletion occurred; the user authorized a targeted commit after final verification. |
| 2026-07-28 | Lessons | `788cdd38` | Checked-deferred: 87 dated entries past the 2026-06-14 watermark, but only the two 2026-06-17 entries are cold; threshold 20 is not tripped. Both remain verbatim, no distillation was drafted, and the watermark did not advance. Reconsider on 2026-08-07. Doc references: 10 passed; DOM-15 fixtures, source-entry check, and diff check green. |
| 2026-07-17 | — (propagation; nothing folded) | source agent-guidance @ `b248e1c`; landed `9221cbd` | Delta wave per `docs/plans/2026-07-17-agent-guidance-propagation-plan.md`: [DOM-14] fold-unit trigger bullet promoted (this file's Fold Unit and Progress Model section is the required declaration); six coalescing-skill refinements; interface-review skill; writing-plans and review-loops wave content; call-agent brief standard. Scoped review round 1 blocker (missing template-pointer sentence; stale adaptation narration) fixed same pass; the draft's intermediate-commit transplant (BLOCKED/CLEAR) corrected to the b248e1c end-state pre-review. No thresholds, watermarks, or folds touched. |
| 2026-07-14 | Lessons | `c09e95e` | First sweep (user-authorized): six cold entries (2026-06-12) examined; three folded into a pointer line — each verified distilled into the spec tree (read-only resolution contract, [TAUT-12.3] reuse modes, [TAUT-8.4] cursor discipline); three kept verbatim because their claimed or expected distillation homes could not be verified (type-check-tests rule, identity argv classification, watcher construction-vs-refresh phases) — flagged as future runbook/spec candidates. Watermark advanced to 2026-06-14. Remaining 79 entries all within age floor → checked-deferred. Doc gates green. |
| 2026-07-14 | — | — | Layer adopted from agent-guidance `2f7eff6`. Lessons derived count 85 past (no) watermark — tripped, deferred to an authorized first sweep. No fold performed. |
| 2026-07-14 | mini-wave + sweep check | agent-guidance `a4b4345` | Adopted `runbooks/designing-agent-facing-interfaces.md` (first [DOM-14] fold-up, distilled from mm's agent API) via `docs/plans/2026-07-14-agent-interfaces-runbook-adoption-plan.md`; principle citations land verbatim (this repo's numbering matches canonical). Sweep-after-propagation check: lessons count since 2026-06-14 watermark unchanged from the first sweep's deferral (all within age floor) — no new trip, nothing folded, no watermark advanced. First intended citation target: the MCP extension plan's tool surface. |
