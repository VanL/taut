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
are archive maintenance when every removal has a verified pre-fold
source cue reachable from a retained ref; such a routine authorized
sweep is plan-exempt and needs no separate landing authorization, and
worktree-only material remains ineligible for removal
([DOM-5]/[DOM-14] archive rule, adopted from agent-theory @ `0423923`;
durable-guidance promotion still escalates and gates on the human
owner).

Counts are always derived from watermarks and the current tree — never
stored, never trusted from memory.
The derivation recipe declared in this file and mirrored in
`skills/coalescing/SKILL.md` step 1 is authoritative; `bin/coalesce-check`
is an **evidence trail, not a second recipe** — read-only, never writes
counts back, and when the tool and this file disagree, this file wins
and the script is the defect.

**Report when (one sentence to the user):** harvest candidates ≥ the
plans threshold, or the index gate finds an unindexed plan file (any
positive is reportable; `bin/check-plan-status-index` natively gates
every-file-indexed here), or a reconsideration condition in the
deferral table has fired and counts changed since checked-through.
Unchanged counts against an unchanged deferral row: do not re-nag.

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
| Unindexed | plan files missing from the Status Index | 0 (any positive is reportable; natively gated — `bin/check-plan-status-index` requires every plan file to appear exactly once) | none |
| Promotion | distinct citations of the same workflow theme (judgment-clustered) since the promotion watermark | 3 | n/a |

## Reporting Cues (non-gating)

Derived counts worth reporting alongside the threshold check when cheap to
compute. They inform judgment and are never gates:

- **Apparatus share** — the fraction of active (non-retired) plan files
  whose subject is the process corpus itself (plans, docs, lessons,
  coalescing, skills). A sustained rise is evidence for the process-tower
  falsifier in the agent-theory hub's program theory; evaluate by
  judgment, not by budget.

## Watermarks

| Tier | Distilled through | Source SHA |
|------|-------------------|------------|
| Lessons | 2026-07-14 | `9410b6b` |
| Plans | (progress is the Retired Plans ledger, not a cursor — two four-plan soft-retirement batches recorded through 2026-08-14) | per-plan, see ledger |
| Promotion | (none — three derivations recorded; no promotion checkpoint) | — |

## Deferral State

A trip is only news when it is new: unchanged counts against this table
do not re-nag; a changed count or a fired reconsideration condition
does.

| Tier | Checked through (date, SHA) | Counts at check | Reason deferred | Reconsider when |
|------|------------------------------|-----------------|-----------------|-----------------|
| Lessons | 2026-08-14, source `9410b6b` | 65 dated entries: 17 past the 2026-07-14 watermark, all inside the 30-day age floor; 0 cold eligible against threshold 20 | Checked-deferred after all 37 entries in the 2026-07-10..2026-07-14 block were examined: 14 folded into source-cued summaries and 23 kept verbatim as named hot or promotion candidates | Recount when the 2026-07-27 entry reaches the 30-day age floor on 2026-08-26, or sooner if 20 new cold eligible entries accumulate |
| Plans | 2026-08-14, base `f1b5be6` (local-only pin) plus concurrent active-plan row | 75 indexed plans in the current tree: 63 completed, 4 superseded, 4 retired-pending, 4 active; 66 completed/superseded non-exemplars remain eligible against threshold 8 | Checked-deferred after the second four-plan soft-retirement batch: retirement remains volume-limited, with no blocker class found in the audited oldest-first batch | The next authorized sweep or completion boundary gates the next batch; the four newly retired-pending plans require a dedicated physical-deletion follow-up with fresh harvest-gate and source-cue verification |
| Promotion | 2026-08-14, source `9410b6b` | 3 candidate themes: xdist worker-kill containment; summon harness readiness/token discipline; and causal synchronization/resource ownership in tests (4 independent July entries) | The two testing-patterns amendments require their own Class 3+P units; the harness-discipline cluster remains a summon-architecture-note candidate; all gate on the durable-guidance ceiling (human owner) | A Class 3+P runbook/implementation-note amendment unit is authorized, or a new unowned workflow theme reaches 3 independent citations |

## Run Log

One line per run, newest first. Each line is a claim; it must survive a
spot-check against the diff. `checked-deferred` lines are valid runs.

| Date | Tier(s) | Source SHA | Claim |
|------|---------|------------|-------|
| 2026-08-14 | Lessons | `9410b6b` | Examined and dispositioned all 37 age-floor candidates dated 2026-07-10..2026-07-14. Folded 14 already-owned entries into four source-cued summaries after text-fidelity, symbol-liveness, and focused behavioral-parity checks: compatibility-floor/test portability ×3, signal-context ownership ×1, parser/cancellation scope ×2, and eight separately owned configuration/performance/backend/presentation/help/release/identity rules. Kept 23 verbatim: 4 causal-synchronization promotion candidates; 4 lifecycle/renderer entries in the concurrent active remediation domain; 2 xdist worker-kill entries still accumulating through the active publication plan; and 13 release/CI entries cited by that active plan. Repaired the misplaced renderer entry by moving it unchanged under Project Lessons. Watermark 2026-07-09 → 2026-07-14. The published source contains all removed raw entries. Project-environment doc-reference, path, coalescing, and diff gates rerun green. |
| 2026-08-14 | Promotion | `9410b6b` | No skill or durable guidance promoted. Existing xdist worker-kill and summon harness-discipline candidates remain; newly named causal synchronization/resource ownership in tests from four independent entries. The release/CI cluster remains product-owned and hot, not a skill candidate. All durable-guidance amendments remain separately classed and owner-gated; no promotion watermark advanced. |
| 2026-08-14 | Plans (soft retirement) | `f1259c0`, `33e13ee`, `dadd324` | Soft-retired the next four oldest eligible non-exemplar plans after an independent current-tree harvest audit: foundation, 0.1.1 hardening, initial GitHub Actions release workflows, and initial release helper. All deviation/spec-proposal debt is closed; durable rationale is absorbed into [TAUT-*] and the architecture notes; applicable lessons are present or explicitly not owed; all four spec backlinks and the maintained repository-map/architecture paths now use retained-cue citations. The old GitHub-only/no-PyPI boundaries were judged transitional rather than durable. Repaired one stale transient repository-map claim that a 2026-07-11 completed plan's worktree was still uncommitted. Source blobs are byte-identical and reachable from `origin/main`. Remaining eligible: 66. Apparatus-share cue: 0 of 4 live plans is process-subject. Project-environment plan-index, path, docs-reference, and coalescing gates rerun green. |
| 2026-08-14 | Plans (physical deletion) | `b03709452`, `db67b94b`, `281f04fa`, `4a129e94` | Dedicated second-step deletion of the four plans soft-retired 2026-08-08. An independent agent re-verified each four-part harvest gate from the current tree; each retained source is reachable from `origin/main` and contains a byte-identical plan; maintained specs and implementation notes contain only retired citations. Removed the four status-index rows and plan files, retained all four Retired Plans ledger rows, and left historical plan-to-plan paths in immutable plan sources outside the live traceability surface. Project-environment plan-index, path, docs-reference, and coalescing gates passed before deletion and are rerun below from the resulting tree. |
| 2026-08-08 | Lessons | `9410b6b` (local-only pin) | First large fold, owner-authorized sweep: all 48 cold entries (dated ≤ 2026-07-09) examined and dispositioned. Folded 29: 24 verified distilled into owning spec/implementation text (summon readiness barriers ×5, shutdown/supervision lifecycle ×7, SimpleBroker retry/handle ownership + version-floor chain ×4, real-process lane topology ×3, detached PTY startup ×2, identity-claim race ×1, cross-backend BIGINT ×1, cohesion→engineering-principles §14 ×1) and 5 superseded transient-retry entries whose inverse rule is owned with firing no-retry tests. Kept 19 verbatim as named candidates (unowned harness readiness/token rules, psutil-handle prohibition, E2BIG/stdin, opacity testing, oldest-parser gate generalization, backend marker guard, 2026-06-17 backend-selection entry, 2026-07-02 fold record). Verification: three independent read-only agents produced file:line evidence both directions plus symbol-liveness and code-parity checks; orchestrator spot-checked. Watermark 2026-06-14 → 2026-07-09. Correction recorded: the 2026-07-28 promotion claim "readiness theme fully owned by [SUM-5.1]" was false as a blanket — the owning text is the summon architecture note's harness posture, and four sub-rules were unowned (kept verbatim). Out-of-boundary defect detected, not repaired here: simplebroker floor drift (specs say >=6.0.1, pyproject/README say >=6.0.2) — owner-flagged as a follow-up task. Doc gates rerun green (see plans line). |
| 2026-08-08 | Plans | batch pins `b03709452`, `db67b94b`, `281f04fa`, `4a129e94` | Soft-retired the four-plan first batch (ci-failure-remediation, single-project-config-source-spec, terminal-output-safety, per-call-read-limit) after an independent agent re-verified the four-part harvest gate from the current tree: deviation logs closed, rationale absorbed, lessons extracted, all 8 spec/implementation backlinks converted to the retired citation form; each source SHA verified to contain the plan file with an empty diff against HEAD. The 2026-08-07 handoff's per-call-read-limit blocker ("routed durable record unlanded") did not reproduce — [TAUT-7.2] carries the request-policy limit and both rejected alternatives, mirrored in 04-taut-architecture. No file deleted (two-step rule); physical deletion is a dedicated follow-up. Remaining 58 eligible plans checked-deferred (volume-limited, no blocker class found). check-plan-status-index green after the flips. |
| 2026-08-08 | Promotion | `9410b6b` | Re-derivation: no new skill justified. The xdist worker-kill containment amendment to `testing-patterns.md` remains owed and gained one citation (2026-08-05 subprocess-watchdog entry); newly named candidate: summon harness readiness/token discipline (the kept unowned 2026-07-08 rules) as a future summon-architecture-note amendment. Both gate on the durable-guidance ceiling; nothing promoted, no watermark advanced. Cross-repo fold-up candidate proposed upward for the owner to carry to the agent-theory hub: "co-location is not isolation" (grouping/marker mechanisms that co-locate work do not serialize the rest of the system) — taut evidence is the folded lane-topology cluster; hub acceptance needs an independent second lineage. Apparatus-share cue: 1 of 3 live (active/draft) plans is process-subject (information-architecture). |
| 2026-08-07 | — (propagation + checked-deferred sweep) | source agent-theory @ `0423923`; landed `4e3f12f` (wave) after `c541b48` (program theory) | Agent-theory delta wave per plan 2026-08-07-agent-theory-delta-wave-plan (25 payload items; scoped review F1-F9 applied; round-2 waived with mechanical verification disclosed). Program theory crystallized and ratified Active the same day (plan 2026-08-07-program-theory-crystallization-plan). First-sweep-after-propagation standing rule discharged as an honest checked-deferred: lessons 97 total/94 past the 2026-06-14 watermark (threshold 20 — tripped; reconsideration condition of the 2026-07-28 deferral fired 2026-08-07) and plans 48 completed/superseded non-exemplars (threshold 8 — tripped; zero retired). Both tiers are their own authorized maintenance unit, reported to the owner this session; folding under wave pressure destroys evidence. Reconsider when: the owner authorizes the harvest sweep, or either count changes. No thresholds, watermarks, or folds touched. |
| 2026-07-28 | — (gate correction; nothing folded) | — | **`coalesce-check` no longer probes the filesystem for sibling repositories** (corrected upstream in agent-theory and propagated). The old `SIBLING_ROOT = REPO_ROOT.parent` hardcoded a checkout layout no document declared, and reported SHAs resolvable only in a neighbouring working copy as *verified* — laundering a local-only claim into a green check, defeating the cue-portability rule the tool enforces. Now: own SHAs verified locally and against this repo's published remote; unresolvable SHAs reported as **foreign claims** naming the repository they cite (informational, never a verdict); an unresolvable SHA naming no repository is a genuine failure. `COALESCE_SIBLING_ROOT` is opt-in local convenience, off by default. |
| 2026-07-28 | — (upstream rename; nothing folded) | — | The guidance hub was renamed `agent-guidance` → `agent-theory` (it names a discipline — theory-building for agent-assisted development — not an artifact of instructions). `bin/coalesce-check`'s sibling list was repointed so hub SHA claims resolve again. Existing provenance lines, run-log rows, and plan filenames naming `agent-guidance` refer to that same upstream repository under its former name and are left as written; git commit messages likewise retain it. |
| 2026-07-28 | — (propagation; nothing folded) | source agent-guidance @ `cec5666`; landed `7afcb14` | Delta wave per `docs/plans/2026-07-28-agent-guidance-delta-wave-plan.md`: cue-portability paragraph, harness scoping sentence, both executable gates (check-doc-paths imports this repo's test grammar + covers this file and the plans index; coalesce-check watermark-denominated, cross-checked 87 against the deferral table). Two items EMPTY — this repo is the fold-up source; hub credits taut `3706d73` as first lineage. First run: local-only pins `788cdd38`, `9221cbd`. Scoped review no blocker. No thresholds, watermarks, or folds touched. |
| 2026-07-28 | Promotion | `788cdd38` | First derivation: three coherent workflow themes crossed the citation threshold. Summon readiness barriers and real-process lane ownership are already owned by product specs and implementation notes; xdist worker-kill containment is a genuine `testing-patterns.md` amendment candidate. No new skill is justified, no process file changed, and no promotion watermark advanced. Candidate evidence is in `docs/plans/2026-07-28-coalescing-wave-plan.md`. Doc references: 10 passed; DOM-15 fixtures and diff check green. |
| 2026-07-28 | Plans + maintenance | base `788cdd38`, index SHA-256 `61ad88e66fc8d4307183fcc38f74e9eabca5457cba195c3117efad0c64c34ad6` | Repaired the non-derivable plan status source: replaced 27 mixed prose rows and 22 omissions with one checked row for each of 49 plan files, using a closed status vocabulary and literal exemplar field. Final derivation: 47 completed, 2 superseded, and 1 exemplar; 48 completed/superseded non-exemplars remain unretired against threshold 8. Added `bin/check-plan-status-index`, 21 contract tests, and coalescing process guidance. No soft retirement, backlink conversion, watermark change, or deletion occurred; the user authorized a targeted commit after final verification. |
| 2026-07-28 | Lessons | `788cdd38` | Checked-deferred: 87 dated entries past the 2026-06-14 watermark, but only the two 2026-06-17 entries are cold; threshold 20 is not tripped. Both remain verbatim, no distillation was drafted, and the watermark did not advance. Reconsider on 2026-08-07. Doc references: 10 passed; DOM-15 fixtures, source-entry check, and diff check green. |
| 2026-07-17 | — (propagation; nothing folded) | source agent-guidance @ `b248e1c`; landed `9221cbd` | Delta wave per `docs/plans/2026-07-17-agent-guidance-propagation-plan.md`: [DOM-14] fold-unit trigger bullet promoted (this file's Fold Unit and Progress Model section is the required declaration); six coalescing-skill refinements; interface-review skill; writing-plans and review-loops wave content; call-agent brief standard. Scoped review round 1 blocker (missing template-pointer sentence; stale adaptation narration) fixed same pass; the draft's intermediate-commit transplant (BLOCKED/CLEAR) corrected to the b248e1c end-state pre-review. No thresholds, watermarks, or folds touched. |
| 2026-07-14 | Lessons | `c09e95e` | First sweep (user-authorized): six cold entries (2026-06-12) examined; three folded into a pointer line — each verified distilled into the spec tree (read-only resolution contract, [TAUT-12.3] reuse modes, [TAUT-8.4] cursor discipline); three kept verbatim because their claimed or expected distillation homes could not be verified (type-check-tests rule, identity argv classification, watcher construction-vs-refresh phases) — flagged as future runbook/spec candidates. Watermark advanced to 2026-06-14. Remaining 79 entries all within age floor → checked-deferred. Doc gates green. |
| 2026-07-14 | — | — | Layer adopted from agent-guidance `2f7eff6`. Lessons derived count 85 past (no) watermark — tripped, deferred to an authorized first sweep. No fold performed. |
| 2026-07-14 | mini-wave + sweep check | agent-guidance `a4b4345` | Adopted `runbooks/designing-agent-facing-interfaces.md` (first [DOM-14] fold-up, distilled from mm's agent API) via `docs/plans/2026-07-14-agent-interfaces-runbook-adoption-plan.md`; principle citations land verbatim (this repo's numbering matches canonical). Sweep-after-propagation check: lessons count since 2026-06-14 watermark unchanged from the first sweep's deferral (all within age floor) — no new trip, nothing folded, no watermark advanced. First intended citation target: the MCP extension plan's tool surface. |
