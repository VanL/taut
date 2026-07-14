# Agent-Guidance Propagation Plan (2026-07-14 wave)

Status: Active
Class: 5+P — normative spec sections land in the taut spec tree
([DOM-14], [DOM-15]) and the change is [DOM-6]-material to how future
taut work is planned, reviewed, and verified. Hardening: N/A — no
[DOM-5] risky trigger fires (docs and guidance only).
Source: agent-guidance @ `2f7eff6` (2026-07-14). Source-content review
history: seven independent review rounds across four plans in
agent-guidance today (coalescing §8a ×2; external-skill-suites §7a
codex; task-class-matrix §8a–§8e codex ×4 + one outside review;
call-agent §7 grok ×2). Taut's own review for this plan is scoped to
the **adaptation** (numbering fit, local conflicts, calibration), not
re-litigation of the reviewed content.

## 1. Goal

Adopt the 2026-07-14 agent-guidance wave in taut with SHA-pinned
provenance: the coalescing layer ([DOM-14] + skill + state file), task
classification ([DOM-15] + fixture checker), the
performative-overengineering review lens, the external-skill-suites
crosswalk, and four skills (coalescing, debugging,
brainstorming-to-plan, call-agent) — and close taut's outstanding
provenance debt ("record the commit SHA when agent-guidance commits").

## 2. Source Documents

- taut: `docs/specs/01-development-documentation-operating-model.md`
  (sections 1–13 at plan time — [DOM-14]/[DOM-15] slot cleanly),
  `docs/agent-context/engineering-principles.md` (§1–14),
  `docs/lessons.md` (provenance note, 2026-07-02 entry).
- agent-guidance @ `2f7eff6`: the promoted [DOM-14]/[DOM-15] text,
  §15 and the §10 amendment, plan lifecycle and retirement, the
  retired-citation form, the [DOM-11] lens amendment, the crosswalk,
  the four skills, `bin/check-dom15-fixtures`.

## 3. Invariants and Constraints

- **Adapt, never clobber.** Taut's locally extended guidance (its
  testing-patterns additions, its richer agent inventory, its plans
  README shape) is kept; deltas insert at verified anchors only.
- **Dirty-tree discipline:** taut has unrelated WIP (CHANGELOG,
  README, `bin/check-core-summon-wheel-matrix.py`,
  `docs/implementation/02-repository-map.md`, `04-taut-architecture.md`)
  — this plan touches none of those files; repository-map rows for the
  new files are deferred to a follow-up to avoid mixing changes.
- **Copied skills cite taut-resolvable paths.** Status lines reference
  this plan and the source SHA, never agent-guidance plan paths (the
  doc-reference test enforces path claims).
- **Per-repo calibration:** taut's ledger has 85 dated entries;
  coalescing thresholds are set higher (lessons 20) and watermarks
  start unset — the first taut sweep is taut's own decision.
- Taut's own gates govern: `tests/test_docs_references.py` and the
  full docs checks must pass before this plan is landed.

## 4. Deviation Log

| Spec ref | Planned behavior | Actual behavior | Rationale | Spec proposal |
|----------|------------------|-----------------|-----------|---------------|
| agent-guidance coalescing plan task 6/7 | Propagation blocked on a two-sweep pilot gate | Propagated after one sweep | Explicit user instruction (tier 1) on 2026-07-14 | none — gate remains for other repos' sweeps |

## 5. Tasks

1. Close the provenance debt: pin the 2026-07-02 fold note in
   `docs/lessons.md` to `5927481`, and record this wave's source as
   `2f7eff6`.
2. Spec deltas: [DOM-14] and [DOM-15] appended to the DOM spec
   (verbatim from source, with taut's `## Related Plans` gaining this
   plan); [DOM-5] routing amendment; [DOM-11] lens amendment.
3. Guidance deltas: engineering-principles §15 + §10 amendment;
   writing-plans (lifecycle section, class boundary in File Placement,
   prompt lens); review-loops (surface line, prompt lens, call-agent
   pointer); maintaining-traceability (retired-citation form);
   decision-hierarchy (classify-before-preflight); AGENTS.md
   convention bullet; agent-context README (runbook list, hot-lessons
   read order, coalescing maintenance rule); context.index.yaml
   entries; lessons.md startup-scope note.
4. New files: `docs/coalescing.md` (taut-calibrated),
   `docs/agent-context/runbooks/external-skill-suites.md`,
   `skills/{coalescing,debugging,brainstorming-to-plan,call-agent}/SKILL.md`
   (status lines adapted), `bin/check-dom15-fixtures`.
5. Plans README: add this plan to Active Plans; add the Retired Plans
   ledger section (empty).
6. Gates: `./.venv/bin/python -m pytest tests/test_docs_references.py`
   (and neighboring docs tests) green; `python3
   bin/check-dom15-fixtures` exit 0; grep gates for [DOM-14]/[DOM-15].
7. Scoped adaptation review (different family, via call-agent) —
   dispositions recorded here — then land.

## 5a. Review Findings and Dispositions (grok, scoped adaptation review, 2026-07-14)

Verdict: PASS — no placement, calibration, foreign-path, or
local-clobber failures. Five advisory findings, all addressed:

| # | Finding | Disposition |
|---|---|---|
| A1 | debugging/brainstorming status lines omitted this plan | Fixed — both cite it |
| A2 | call-agent Read First path not repo-root-resolvable | Fixed here and backported to agent-guidance |
| A3 | call-agent's verified table vs the 2026-07-13 inventory: two truths, no review-eligible rung | Reconciled by pointer: the inventory now states probe mechanics and the eligibility rung are owned by the skill and that its statuses predate it; actual re-probing is a per-machine task for a taut session |
| A4 | skills/README still claimed an intentionally empty directory | Fixed — lists the four skills |
| A5 | taut's local Rule 5 docs-inspection exit looser than the amended §10 | Tightened: inspection only when no reproducible check exists |

Also found during landing (gate-driven, fixed before review): the
initial spec transplant matched an inline mention of "## Related Plans"
inside a DOM-6 bullet instead of the heading, splicing [DOM-14]/[DOM-15]
mid-section — caught by `test_cited_spec_codes_resolve_to_spec_headings`,
reverted, and redone with line-anchored unique-match inserts; the
crosswalk's external-suite path examples and the [DOM-15] `XYZ-3`
placeholder read as path/citation claims to taut's scanner — reworded in
both repos.

## 6. Out of Scope

- Repository-map updates (deferred: file is dirty with unrelated WIP)
- Running taut's first coalescing sweep or populating a full plan
  status index (the sweep's job, on taut's own trigger)
- The other sibling repos (each gets its own propagation plan)
