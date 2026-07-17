# Agent-Guidance Propagation Plan (2026-07-17 delta wave)

Date: 2026-07-17

Status: Active — transplant drafted; orchestrator owns gates, independent
review, landing, and the sweep. Dispositions below are empty pending the
scoped review.

Plan type: guidance propagation with spec revision.

Class: 5+P — normative spec text lands in the taut spec tree (the
[DOM-14] coalescing-trigger bullet), which makes this [DOM-6]-material to
how future taut coalescing is triggered and how reviews are commissioned
and verdicted. Hardening: N/A — no [DOM-5] risky trigger fires (docs and
guidance only; no runtime, storage, or contract surface changes).

Source: agent-guidance @ `b248e1c` (2026-07-17). The wave is the hub
delta since taut's last pins — the 2026-07-14 wave (agent-guidance
`2f7eff6`, landed at taut `c09e95e`) plus the designing-agent-facing-
interfaces runbook adoption (agent-guidance `a4b4345`). Source content
was reviewed in agent-guidance before commit (the six coalescing
amendments were grok-reviewed at `cc7ab30`; the interface-review skill
was grok-reviewed PASS-with-changes at promotion; the review-loops and
call-agent slices are owner-directed). Taut's own review for this plan is
scoped to the **adaptation** — placement, retargets, the reworded
provenance and Status lines, the fold-unit declaration fit — not
re-litigation of the reviewed source content.

## 1. Goal

Adopt the agent-guidance delta between `a4b4345`/`2f7eff6` and `b248e1c`
in taut with SHA-pinned provenance: the [DOM-14] fold-unit trigger
promotion, the six coalescing-skill method refinements, the new
interface-review skill, the plan-lifecycle and planning-standard
additions, the two-question plan-review prompt with the scoped-change
template and unified verdict vocabulary, and the call-agent review-brief
standard — plus the `docs/coalescing.md` fold-unit declaration the
promoted spec text now requires.

## 2. Source Documents

- taut targets: `docs/specs/01-development-documentation-operating-model.md`
  ([DOM-14], §14 coalescing requirements), `skills/coalescing/SKILL.md`,
  `skills/call-agent/SKILL.md`,
  `docs/agent-context/runbooks/writing-plans.md`,
  `docs/agent-context/runbooks/review-loops-and-agent-bootstrap.md`,
  `docs/coalescing.md`, `skills/README.md`, `docs/plans/README.md`.
- agent-guidance @ `b248e1c` payload commits: `30c8b04` ([DOM-14] trigger
  bullet), `cc7ab30` (six coalescing amendments), `763a0e9` (interface-
  review skill), `fafd874` + `b248e1c` (writing-plans bullets), `ea5314b`
  + `cd74fcd` (review-loops §4a/§4/§6), `3ffb807` + `cd74fcd` (call-agent
  step 2). Foreign hub plans quoted by name only, never as taut paths:
  agent-guidance `docs/plans/2026-07-15-coalescing-method-refinements-plan.md`
  (the [DOM-14] promotion and coalescing amendments) and
  `docs/plans/2026-07-15-interface-review-skill-promotion-plan.md` (the
  interface-review promotion).

## 3. Context and Key Files

- Taut carries the DOM spec, the coalescing skill + state file, call-agent,
  writing-plans, and review-loops — every target already exists, so this
  wave amends rather than bootstraps. The single new file is
  `skills/interface-review/SKILL.md`.
- Taut's reference gate (`tests/test_docs_references.py`) checks that every
  backtick path under `docs/`, `taut/`, `tests/`, `bin/`, `extensions/`
  resolves and every bracketed `[FAMILY-N]` citation resolves to a
  registered heading. Every transplanted path and code cite was surveyed
  against taut's tree before landing (see §5).
- Taut's `docs/agent-context/engineering-principles.md` §12 is
  "Enumerable Contracts Get Executable Gates" — the interface-review
  skill's §12 cite resolves natively; the eleven interface principles are
  numbered identically in taut's `designing-agent-facing-interfaces.md`.

## 4. Invariants and Constraints

- **Adapt, never clobber.** Taut's local Status lines, adoption notes,
  and state-file adaptations are preserved; amendments splice into named
  headings, never blanket-replace a localized file.
- **Provenance cites this repo's plan + source SHA `b248e1c`.** Copied
  Status lines cite `docs/plans/2026-07-17-agent-guidance-propagation-plan.md`,
  never a hub plan path. Hub plans appear only as named foreign evidence.
- **No dangling references.** Every path claim resolves in taut's tree;
  no foreign hub path is introduced as a taut path claim.
- **Foreign code scheme decision: keep-local.** Taut uses the canonical
  `[DOM-N]` family natively; all cited codes ([DOM-10], [DOM-14]) resolve
  to taut headings. No dual-cite or name-map needed.
- Orchestrator owns gates, review, and landing; this plan does not assert
  commit or staging state.

## 5. Payload Checklist and Insert Regions

| # | Payload | Target | Insert region | Landed |
|---|---------|--------|---------------|--------|
| 1 | [DOM-14] fold-unit trigger bullet (hub `30c8b04`) | `docs/specs/01-development-documentation-operating-model.md` | §14 requirements list; extends the "coalescing triggers are event-derived" bullet, before "the session-start trigger check is read-only" | yes |
| 2 | Six coalescing method refinements (hub `cc7ab30`) | `skills/coalescing/SKILL.md` | step 1 fold-unit paragraph (before "Lessons past watermark"); step 2.3 three-tier + adjacent-examples (in the distillation bullet); step 2.6 framework-fact expiry (before "Golden rules and safety invariants are exempt"); step 4 catch-all check (before "Presence in the always-read context"); step 6 collision-aware landing (new item 6, before "## Output Standard") | yes |
| 3 | interface-review skill (hub `763a0e9`, b248e1c state) | `skills/interface-review/SKILL.md` (new) | whole file; Status line rewritten to taut provenance form | yes |
| 4a | Planning Standard "plans record evidence" bullet (hub `b248e1c`) | `docs/agent-context/runbooks/writing-plans.md` | after the red-green TDD bullet, before "If a first draft is structurally complete" | yes |
| 4b | Plan Lifecycle "approval attaches to reviewed text" bullet (hub `fafd874`) | `docs/agent-context/runbooks/writing-plans.md` | after the mutability-boundary bullet, before "Completed and superseded plans are harvest candidates" | yes |
| 5a | §4 two-question BLOCKED/CLEAR prompt + trace note (hub `cd74fcd`) | `docs/agent-context/runbooks/review-loops-and-agent-bootstrap.md` | replaces the §4 prompt blockquote; trace note appended before "If the review is for completed work" | yes |
| 5b | §4a scoped-change template + round-2 variant (hub `ea5314b`) | same runbook | new §4a between §4 and §5 | yes |
| 5c | §6 verdict vocabulary (hub `cd74fcd`) | same runbook | appended after "name any residual risk" in §6 | yes |
| 6 | call-agent step-2 brief standard + verdict form (hub `3ffb807` + `cd74fcd`) | `skills/call-agent/SKILL.md` | step 2: verdict-form sentence + brief-required-shape paragraph, before "Write long prompts to a temp file" | yes |
| 7 | Fold-unit declaration required by the promoted spec text | `docs/coalescing.md` | new "## Fold Unit and Progress Model" section before "## Thresholds" | yes |
| — | Register interface-review skill | `skills/README.md` | current-skills sentence | yes |
| — | Register this plan | `docs/plans/README.md` | Active Plans list | yes |

## 6. Adaptations

| Source element | Hub form | Taut adaptation | Reason |
|----------------|----------|-----------------|--------|
| interface-review Status line | cites hub promotion plan + `[DOM-14]` | rewritten to cite `docs/plans/2026-07-17-agent-guidance-propagation-plan.md` @ `b248e1c`; hub citation SHAs kept as promotion evidence | path-claim gate rejects foreign hub plan paths; step-4 provenance rule |
| interface-review "propagate-guidance's scoped-review step" | names the hub-native `propagate-guidance` skill | reworded to "the propagation-guidance scoped-review step" (prose) | taut has no `propagate-guidance` skill (hub-native); naming it as a skill would mislead |
| §4 prompt invariants paragraph | "where this repository keeps a standing-invariants registry" | landed verbatim (conditional clause) | taut has no standing-invariants registry; the clause is already conditional, so it reads correctly as "none registered" |
| `docs/coalescing.md` fold unit | hub spec requires a declaration | declared taut's actual model: repo-wide dated ledger, watermark as examined-through cursor (oldest-first, no theme-cluster-across-dates folding), with the switch conditions noted | taut's `lessons.md` is a single chronological list, not domain-grouped; a bare date cursor is safe only under oldest-first examination, so the declaration states that precondition |
| coalescing skill amendment 1 (progress model) | general text warning date cursors for theme-cluster folding | landed verbatim; taut's specific safe model is declared in `docs/coalescing.md` (payload 7) | skill text is general guidance; the state file owns the repo-local model |
| Verdict vocabulary | two forms by review type — plan reviews `PASS`/`BLOCKED` derived from the two gate questions; scoped-change reviews `no blocker`/`blocker: F<ids>` | landed at the hub `b248e1c` end-state. Correction record: the draft transplant used an intermediate hub commit's `BLOCKED`/`CLEAR` + retirement wording; the orchestrator replaced it with the end-state (`PASS`/`BLOCKED`, no retirement) before review, and the review's F2 caught this table still narrating the intermediate story | end-state fidelity is the transplant contract; intermediate hub commits are never the source |

## 7. Tasks (dependency-ordered)

1. Transplant payloads 1–7 into their named targets with heading-anchored,
   unique-match inserts. (done — see §5)
2. Register the interface-review skill and this plan. (done)
3. Run taut's reference gate and any cheap doc gates; record results. (§8)
4. Orchestrator: scoped independent review (different family), disposition
   into §9, land by explicit file-list staging against the §5 target list,
   then run the first coalescing sweep as the propagation unit's sweep.

## 8. Verification and Gates

- `python -m pytest tests/test_docs_references.py` — the reference gate;
  must stay green (baseline before this wave: 10 passed).
- `python -m pytest tests/test_project_metadata_consistency.py` — metadata
  consistency (does not scan plans; run as a cheap adjacent gate).
- Manual: every §5 insert region is a unique heading-anchored splice; no
  foreign hub path appears as a taut path claim.

## 9. Independent Review and Dispositions

Scope fence (verbatim to the reviewer): source content is already reviewed
upstream; review ONLY the adaptation — placement of each insert, the
reworded provenance/Status lines, the fold-unit declaration's fit to
taut's actual model, the retarget of the `propagate-guidance` mention, and
any performative additions. Verdict form: `no blocker` / `blocker: F<ids>`.

Review run 2026-07-17 (grok, read-only, §4a-form brief). Round-1
verdict: **blocker: F1, F2** — both fixed same pass; fidelity to the
hub `b248e1c` end-state otherwise confirmed (no `BLOCKED`/`CLEAR` or
retirement residue after the orchestrator's pre-review correction; the
[DOM-14] splice, fold-unit declaration, and doc-reference gate all
clean, 10/10 passing).

| ID | Severity | Location | Finding | Suggested disposition | Status |
|----|----------|----------|---------|----------------------|--------|
| F1 | P2 | skills/call-agent step 2 | The §4a template-pointer sentence (part of the hub end-state brief-standard block) was missing | Add the sentence with the full local runbook path | **Fixed** |
| F2 | P3 | this plan's adaptations table | Row narrated the intermediate hub commit's retirement story though the files correctly carry PASS/BLOCKED | Reword to end-state truth with the correction recorded | **Fixed** |
| W1 | P2 (worker defect, orchestrator-caught pre-review) | review-loops §4/§6; call-agent | Draft transplanted `BLOCKED`/`CLEAR` + retirement line from intermediate hub commit `cd74fcd` instead of the `b248e1c` end-state | End-state restored before review; recorded here as the wave's transplant-contract lesson | **Fixed** |
|----|----------|----------|---------|----------------------|--------|

(empty — pending the scoped review)

## 10. Out of Scope

- Re-litigating the source content reviewed in agent-guidance.
- Backfilling taut's plans-tier status index or running a full first sweep
  fold — the sweep runs as the orchestrator's landing unit, not here.
- Any change to taut's runtime, storage, or MCP contract surfaces.

## 11. Fresh-Eyes Review

The scoped review in §9 is the fresh-eyes pass; a round-2 verification is
scoped to accepted findings only (review-loops §4a round-2 variant).
