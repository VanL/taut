# Coalescing State

Status: Active — governed by [DOM-14] in
`docs/specs/01-development-documentation-operating-model.md` (adopted
from agent-guidance @ `2f7eff6` via
`docs/plans/2026-07-14-agent-guidance-propagation-plan.md`).

Owner: any agent that observes a tripped threshold at session start.
Boundary: lessons, plans, and skill/runbook promotion in this
repository. Specs and implementation docs are living documents and are
never coalesced. Verification: the run log below plus this repository's
documentation gates (`tests/test_docs_references.py`). Required action:
the session-start check is **read-only** — derive the counts, compare
against the deferral state, and report a new trip to the user in one
sentence. All writes happen only inside an authorized maintenance task
(`skills/coalescing/SKILL.md`); destructive steps additionally require
landing authorization.

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
| Plans | (none — first sweep pending; the plans README's Active Plans list is the status source) | — |
| Promotion | (none — first derivation pending) | — |

## Deferral State

A trip is only news when it is new: unchanged counts against this table
do not re-nag; a changed count or a fired reconsideration condition
does.

| Tier | Checked through (date, SHA) | Counts at check | Reason deferred | Reconsider when |
|------|------------------------------|-----------------|-----------------|-----------------|
| Lessons | 2026-07-14, first sweep executed | 79 past watermark — above threshold 20, but every one is within the 30-day age floor | Checked-deferred: nothing foldable until entries age | The 2026-07-08 block (43 entries) crosses the age floor on 2026-08-07 |
| Plans | 2026-07-14, adoption | not derived | Derive at first sweep from the Active Plans list and plan contents | First sweep runs |
| Promotion | 2026-07-14, adoption | not derived | Derive at first sweep | First sweep runs |

## Run Log

One line per run, newest first. Each line is a claim; it must survive a
spot-check against the diff. `checked-deferred` lines are valid runs.

| Date | Tier(s) | Source SHA | Claim |
|------|---------|------------|-------|
| 2026-07-17 | — (propagation; nothing folded) | source agent-guidance @ `b248e1c`; landed `9221cbd` | Delta wave per `docs/plans/2026-07-17-agent-guidance-propagation-plan.md`: [DOM-14] fold-unit trigger bullet promoted (this file's Fold Unit and Progress Model section is the required declaration); six coalescing-skill refinements; interface-review skill; writing-plans and review-loops wave content; call-agent brief standard. Scoped review round 1 blocker (missing template-pointer sentence; stale adaptation narration) fixed same pass; the draft's intermediate-commit transplant (BLOCKED/CLEAR) corrected to the b248e1c end-state pre-review. No thresholds, watermarks, or folds touched. |
| 2026-07-14 | Lessons | `c09e95e` | First sweep (user-authorized): six cold entries (2026-06-12) examined; three folded into a pointer line — each verified distilled into the spec tree (read-only resolution contract, [TAUT-12.3] reuse modes, [TAUT-8.4] cursor discipline); three kept verbatim because their claimed or expected distillation homes could not be verified (type-check-tests rule, identity argv classification, watcher construction-vs-refresh phases) — flagged as future runbook/spec candidates. Watermark advanced to 2026-06-14. Remaining 79 entries all within age floor → checked-deferred. Doc gates green. |
| 2026-07-14 | — | — | Layer adopted from agent-guidance `2f7eff6`. Lessons derived count 85 past (no) watermark — tripped, deferred to an authorized first sweep. No fold performed. |
| 2026-07-14 | mini-wave + sweep check | agent-guidance `a4b4345` | Adopted `runbooks/designing-agent-facing-interfaces.md` (first [DOM-14] fold-up, distilled from mm's agent API) via `docs/plans/2026-07-14-agent-interfaces-runbook-adoption-plan.md`; principle citations land verbatim (this repo's numbering matches canonical). Sweep-after-propagation check: lessons count since 2026-06-14 watermark unchanged from the first sweep's deferral (all within age floor) — no new trip, nothing folded, no watermark advanced. First intended citation target: the MCP extension plan's tool surface. |
