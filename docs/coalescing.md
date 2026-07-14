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
| Lessons | (none — first sweep pending) | — |
| Plans | (none — first sweep pending; the plans README's Active Plans list is the status source) | — |
| Promotion | (none — first derivation pending) | — |

## Deferral State

A trip is only news when it is new: unchanged counts against this table
do not re-nag; a changed count or a fired reconsideration condition
does.

| Tier | Checked through (date, SHA) | Counts at check | Reason deferred | Reconsider when |
|------|------------------------------|-----------------|-----------------|-----------------|
| Lessons | 2026-07-14, adoption | 85 past (no) watermark — tripped at adoption | First sweep is taut's own authorized unit of work; dedup against taut's Golden Rules is mandatory | User authorizes taut's first sweep |
| Plans | 2026-07-14, adoption | not derived | Derive at first sweep from the Active Plans list and plan contents | First sweep runs |
| Promotion | 2026-07-14, adoption | not derived | Derive at first sweep | First sweep runs |

## Run Log

One line per run, newest first. Each line is a claim; it must survive a
spot-check against the diff. `checked-deferred` lines are valid runs.

| Date | Tier(s) | Source SHA | Claim |
|------|---------|------------|-------|
| 2026-07-14 | — | — | Layer adopted from agent-guidance `2f7eff6`. Lessons derived count 85 past (no) watermark — tripped, deferred to an authorized first sweep. No fold performed. |
