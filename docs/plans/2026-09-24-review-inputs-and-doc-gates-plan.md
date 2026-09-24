# Review Inputs and Documentation Gates Plan

Status: draft — gate blind spots verified by scratch mutation; awaiting
owner ratification of the process changes and independent plan review.

Class: 3+P (effective 5). The work materially changes how future reviews
are briefed (`skills/call-agent/SKILL.md`, the review-loops runbook) and
what the documentation gates enforce; that is [DOM-6]-material to how work
is reviewed and verified. No product behavior changes. `hardening: N/A —
no [DOM-5] risky trigger`.

Plan type: process change with executable gates; spec-authoring for the
[DOM-15] fixture sentence.

Owner: implementing engineer; durable-guidance promotions gate on the
human owner ([DOM-15] rules).

## Goal

Close the gaps the 2026-09-23 review found in the process itself. The
program theory's adopted alternatives (A1–A6) demonstrably stop
re-litigation inside plans, but independent reviewers never receive them:
neither `skills/call-agent/SKILL.md` nor
`docs/agent-context/runbooks/review-loops-and-agent-bootstrap.md` mentions
program theory, and both documented re-litigations (A2 via reviewer
finding F1; the 2026-08-24 R2 "tokens are secrets") came from reviewers.
Three gates have verified blind spots: `CITATION_RE` accepts only one- or
two-level codes, so `[DOM-10.2.1]` on 210 `noqa` lines is unchecked; the
retired-plan ledger's source SHAs are not resolved by any gate (a
`deadbee` SHA passes); and the DOM-15 fixture checker's negative-trigger
check is a substring match. The lessons ledger keeps three contradictory
xdist rules live. The plan tier of coalescing cannot converge (eligible
backlog 48→99 against a threshold of 8). Two "completed" items rested on
proofs that could not fail (the reactor restoration's SIGINT safety trace;
the TUI rapid-resize test), and one true rationale was undone by code
(MCP say-miss) — the system prevents wrong changes better than it catches
wrong proofs. Evidence: `docs/plans/artifacts/2026-09-23-deep-dive-review.md`
§4 and the Theory facet.

## Requested Outcomes

- [ ] Every review brief carries a "rejected alternatives in force" bracket
  quoting each [THEORY-5] A-record whose area the delta touches, together
  with the instruction that a reviewer who believes circumstances have
  changed so that a rejected path should be reconsidered raises it for
  evaluation by the human owner, citing the record's reconsider-when
  clause, rather than filing it as a finding or dropping it (owner
  decision 2026-09-24).
- [ ] `CITATION_RE` accepts codes of any depth; a test proves
  `[DOM-10.2.1]` is checked.
- [ ] `bin/coalesce-check` resolves every retired-ledger source SHA and
  verifies the plan exists at that SHA.
- [ ] `bin/check-dom15-fixtures` rejects a class-1/2 fixture whose stated
  facts name a firing trigger (structural, not substring).
- [ ] The three xdist lessons carry supersession markers.
- [ ] The plan tier converges. Diagnosis (2026-09-24, from both run logs):
  taut's sweeps retire "the next four oldest" per run, a batch size no
  document mandates — the 2026-08-08 first batch was four and later sweeps
  copied it as a norm — while SimpleBroker's sweeps harvest every eligible
  candidate that passes the gate, in bulk (67, 21, 11, 14, 5, 6 plans per
  sweep) with parallel independent audits, roughly weekly. With inflow of
  about nine plans a week, four per sweep cannot converge at any cadence.
  Fix: `docs/coalescing.md` and `skills/coalescing/SKILL.md` state that a
  plan-tier sweep audits every eligible candidate and retires each that
  passes the harvest gate, deferring a candidate only with a per-plan
  reason; oldest-first is the lessons tier's cursor rule and does not
  apply to plans. One owner-authorized catch-up sweep clears the current
  backlog the way SimpleBroker's 2026-08-04 sweep did. Retire-at-
  completion remains available as a second lever if bulk sweeps still lag.
- [ ] A mutation-check line is required in the completion evidence of any
  P1-class fix (break the production line, confirm the test fails).
- [ ] [DOM-15] gains the README-typo and dependency-floor fixtures.

## Source Documents

Source specs:

- `docs/specs/01-development-documentation-operating-model.md` [DOM-5],
  [DOM-10], [DOM-10.1], [DOM-11], [DOM-14], [DOM-15]
- `docs/program-theory.md` [THEORY-5] (A1–A6), [THEORY-8]

Supporting context:

- `skills/call-agent/SKILL.md` lines ~67–90 (the required-shape brief).
- `docs/agent-context/runbooks/review-loops-and-agent-bootstrap.md` §3,
  §4, §4a (fill-every-bracket template), §6.
- `docs/agent-context/engineering-principles.md` §8 (findings are claims),
  §12 (gates do not gate gates), §13.
- `docs/coalescing.md` (thresholds, run log, fold unit).
- `docs/lessons.md` entries 2026-07-08 (line ~403), 2026-07-13 (~546),
  2026-09-01 (xdist rules); Golden Rule 14.
- `tests/test_docs_references.py` line ~66 (`CITATION_RE`);
  `bin/coalesce-check` docstring lines ~20–30 ("covers the lessons tier
  and the cue contract only"); `bin/check-dom15-fixtures`;
  `bin/check-plan-status-index`.
- `docs/plans/README.md` retired-plans ledger.
- `docs/plans/artifacts/2026-09-23-deep-dive-review.md` §4.

## Spec Baseline

- `c894059` (0.9.9 release SHA) —
  `docs/specs/01-development-documentation-operating-model.md` and
  `docs/program-theory.md` at plan authoring time. Since `c0a4616` only one
  [RUFF-SUP-088] registry row changed (`1ad4630`), outside every section
  this plan touches.
- Promotion baseline identifier: recorded after the spec-authoring slice.

## Proposed Spec Delta

Promotion strategy: **D — spec-authoring / clarification** for [DOM-15]
fixtures and [DOM-10.1]; the theory revision (A-record ids) is a
[THEORY-8] revision that gates on the owner.

| Spec file | Strategy | Sections touched |
|-----------|----------|------------------|
| `docs/specs/01-development-documentation-operating-model.md` | D | [DOM-15] fixture table (two rows); [DOM-10.1] citation depth sentence; [DOM-11] review-brief requirement |
| `docs/program-theory.md` | owner-gated [THEORY-8] revision | [THEORY-5] preamble (reconsideration routing); record count and ids |

### [DOM-15] — add two fixture rows

> | Fix a spelling error inside a README-owned promise — the claim's meaning is unchanged; the README counts as normative text only for README-owned promises and only for their meaning | 1 |
> | Raise a runtime dependency floor stated in normative spec text — the floor is a compatibility surface ([DOM-5] risky) and the spec sentence changes | 5, with hardening |

### [DOM-10.1] — append one sentence to the citation paragraph

> Reference codes may nest to any depth (`[ABC-1]`, `[ABC-1.2]`,
> `[ABC-1.2.3]`); the gate resolves every depth against the owning spec.

### [DOM-11] — append to the independent-review requirements

> The review brief for any plan or completed work quotes each
> `docs/program-theory.md` [THEORY-5] adopted alternative whose area the
> unit touches, under "rejected alternatives in force". A rejected path is
> not re-argued as a finding. If the reviewer believes circumstances have
> changed so that a rejected path should be reconsidered — its
> reconsider-when condition appears to have fired, or new evidence bears
> on it — the reviewer raises that explicitly for evaluation by the human
> owner, in a separately labeled "reconsideration requested" note that
> names the record, the condition, and the evidence. The author does not
> disposition such a note; only the owner does, and the outcome is recorded
> as a [THEORY-8] revision or an explicit decline. Completion evidence for
> any P1-class defect includes one mutation line: the production change
> reverted or broken, the named test observed failing, the change
> restored.

### [THEORY-5] — owner-gated revision (proposed text for [THEORY-8])

> `[REV-THEORY-003]` Current account: the adopted alternatives are six,
> listed as A1–A6 in numeric order, and are cited as `[THEORY-5.A<n>]` so
> the citation gate resolves them and plan-local finding ids (`A6` in a
> TUI plan) cannot collide. Supersedes: "Five records" and the A4, A6, A5
> ordering. Pressure: the 2026-09-23 review found the miscount, the
> ordering, and a collision with a TUI plan's finding A6.

## Context and Key Files

Files to modify:

- `skills/call-agent/SKILL.md` — the required-shape list (items 1–6); add
  item 7 "rejected alternatives in force" and the reconsideration-request
  rule (raise to the human owner; never a finding; never dropped).
- `docs/program-theory.md` [THEORY-5] preamble — one sentence stating that
  a reconsideration request from any reviewer or author is routed to the
  owner and answered by a [THEORY-8] revision or a recorded decline, so
  the records stay live rather than fossilized.
- `docs/agent-context/runbooks/review-loops-and-agent-bootstrap.md` — §3
  (what to give the reviewer) and the §4a template: add the bracket.
- `tests/test_docs_references.py` — `CITATION_RE = re.compile(r"\[([A-Z][A-Z0-9]*)-(\d+(?:\.\d+)?)\]")`
  (line ~66) and `_citation_codes`; the resolver that maps codes to spec
  headings must accept the deeper form (check how `[DOM-10.2.1]` is
  headed in the spec: `### [DOM-10.1]`-style headings exist; confirm the
  third-level heading form before widening).
- `bin/coalesce-check` — extend the cue scan to the retired-plans table in
  `docs/plans/README.md`: for each row, `git cat-file -e <sha>` and `git
  show <sha>:docs/plans/<name>.md | head -1`; report unreachable or
  missing. Update the docstring's "plans tier stays with
  check-plan-status-index" sentence.
- `bin/check-dom15-fixtures` — the negative-trigger check; replace the
  substring test with a structural one (a class-1/2 row must contain a
  negation phrase from a fixed list applied to "trigger", and must not
  contain "fires" without a preceding negation).
- `docs/lessons.md` — three xdist entries gain `_(superseded by
  2026-09-01 …)_` markers; the Topic Index line for `xdist` points at the
  current rule.
- `docs/coalescing.md` — convergence expectation for the plan tier and,
  if adopted, the retire-at-completion rule.
- `docs/specs/01-development-documentation-operating-model.md` and
  `docs/program-theory.md` per the delta.
- `tests/test_coalesce_check.py`, `tests/test_plan_status_index.py`, the
  DOM-15 fixture tests (grep `dom15`).

Read first: [DOM-14], [DOM-15] in full; the §4a template; Golden Rule 14;
`bin/coalesce-check` in full.

Comprehension gate:

1. **Why hand reviewers the A-records rather than expecting them to read
   the theory?** Expected: the brief is the reviewer's frame by contract
   ("a reviewer is only as good as the frame it receives"); the theory is
   in the startup order for authors, not in the review invocation, and the
   two recorded re-litigations came from reviewers.
2. **Why is "gates do not gate gates" not violated by the retired-ledger
   check?** Expected: the check resolves archive pointers, a declared
   contract in [DOM-14]; it does not verify another gate's correctness.
3. **What does a mutation line prove that a green test does not?**
   Expected: that the test can fail for the defect it names; three
   completed items in this repository had green tests that could not.

## Invariants and Constraints

- No product code changes.
- Gate changes are additive: every currently passing citation, ledger
  row, and fixture must still pass after the change (run each gate before
  and after on the unchanged tree).
- The review-brief bracket is required-shape, not optional: a brief
  missing it is malformed per the skill's existing rule.
- Durable-guidance promotion (the [DOM-11] sentence, the theory revision,
  retire-at-completion) requires owner ratification before landing; agent
  review supports, does not substitute.
- The lessons ledger is append-plus-marker: superseded entries are marked
  in place, never deleted (Golden Rule 14; [DOM-14]).
- `bin/coalesce-check` remains read-only.

Hidden couplings:

- `_citation_codes` feeds both the local-code check and the external-family
  check; widening the regex must not make external citations
  (`[SB-API-2]`-style) fail.
- The DOM-15 fixture checker is itself cited as [DOM-15]'s executable gate;
  its tests are the failing-first proof (engineering-principles §12).

## Rollout, Rollback, and One-Way Doors

- Docs and gate scripts: source revert. No one-way door.
- Retire-at-completion, if adopted, changes the plan lifecycle from the
  next completed plan onward; existing backlog is drained by ordinary
  sweeps.

## Dependency-Ordered Tasks

1. **Owner ratification** of: the [DOM-11] brief bracket and mutation
   line; the theory revision; retire-at-completion (or an explicit
   decline with the convergence expectation stated).
2. **Independent plan review** (different family), including the [DOM-15]
   fixture rows.
3. **Citation depth.** Red: a test that `_citation_codes("[DOM-10.2.1]")`
   returns the code and that an unknown `[TAUT-99.9.9]` is flagged. Widen
   the regex to `(\d+(?:\.\d+)*)`; confirm the heading resolver handles
   three levels; run the gate on the tree.
4. **Retired-ledger SHAs.** Red: a scratch copy of `docs/plans/README.md`
   with one `deadbee` SHA makes `bin/coalesce-check` exit 1. Implement the
   ledger scan; run on the tree (all current SHAs resolve — the review
   checked eight by hand).
5. **DOM-15 fixture negatives.** Red: a class-1 fixture reading "…a
   [DOM-5] risky trigger fires" fails the checker. Implement the
   structural check; keep every existing fixture passing.
6. **Review-brief bracket and reconsideration route.** Edit the skill's
   required-shape list and the §4a template to add the bracket and the
   "reconsideration requested" note format; add the routing sentence to
   the [THEORY-5] preamble (owner-gated); add a fixture brief under
   `docs/agent-context/runbooks/` examples if one exists; existence-check
   every path named. Add to the review-output standard (§6 of the
   review-loops runbook) that a reconsideration note is neither a finding
   nor an observation: it is a third, owner-addressed section.
7. **[DOM-11] and [DOM-15] spec-authoring slice**; record the promotion
   identifier.
8. **Lessons supersession markers** and Topic Index pointer.
9. **Coalescing policy.** Replace the implicit four-per-sweep practice with
   the all-eligible rule in `docs/coalescing.md` (plans tier row and the
   deferral-table reason) and `skills/coalescing/SKILL.md` (the plans step:
   audit every candidate, parallel independent audits permitted, per-plan
   deferral reasons required); record the diagnosis in the run log. Then
   run one authorized catch-up sweep over the current 99 candidates using
   SimpleBroker's parallel-audit shape, in soft-retire and delete steps as
   today. Adopt retire-at-completion only if a later sweep still finds more
   than the threshold after a full harvest.
10. **Theory revision** landed only after owner ratification, with the
    citation form updated in the plans that cite A-records by bare id
    (grep `A[1-6]\b` in `docs/plans/*.md` and judge each).
11. **Completed-work review, index flip.**

## Testing Plan

- Layer: the gate scripts' own pytest suites (`tests/test_coalesce_check.py`,
  `tests/test_docs_references.py`, DOM-15 fixture tests) plus running each
  `bin/` gate on the tree before and after.
- What stays real: the git repository (scratch clones for the negative
  cases), the actual spec files.
- Mutation check for each gate change: revert the script change and
  confirm its new red test fails.

## Verification and Gates

```bash
uv run --extra dev pytest tests/test_docs_references.py tests/test_coalesce_check.py tests/test_plan_status_index.py -n 0
bin/coalesce-check && bin/check-plan-status-index && bin/check-doc-paths && bin/check-cli-claims && bin/check-dom15-fixtures
uv run --extra dev pytest -n auto --dist loadgroup
```

## Independent Review Loop

Reviewer: a different family from the author; because this is +P, the
pre-landing review is also a different family. Inputs: this plan, the
spec delta, the skill and runbook diffs, the three gate scripts. Ask: "Do
the widened gates reject exactly the verified blind spots without
rejecting any current citation, ledger row, or fixture?"

## Out of Scope

- Reworking the Ruff suppression registry's approval batching (recorded in
  the review as ceremony; owner decision).
- Moving [TAUT-12.5]'s release procedure out of the core spec.
- The `interface-review` skill's retirement (owner decision under the
  skills lifecycle).
- Any product code.

## Assumptions and Open Questions

1. **Owner:** confirm the diagnosis and the all-eligible sweep rule, and
   authorize the catch-up sweep. Retire-at-completion is now the fallback,
   not the recommendation, because SimpleBroker's record shows bulk sweeps
   keep up with the same inflow while preserving the independent audit.
2. **Resolved 2026-09-24 (owner):** hand reviewers the records, and add
   the instruction that a reviewer who believes circumstances have changed
   raises the rejected path for evaluation by the human. Blind review is
   not the intended mode.
3. **Owner:** the theory revision's citation form `[THEORY-5.A<n>]` — or
   keep bare ids and accept the collision risk?

## Deviation Log

| Spec ref | Planned behavior | Actual behavior | Rationale | Spec proposal |
|----------|------------------|-----------------|-----------|---------------|

## Review Log

(append-only)

## Execution Log

(append-only)

- 2026-09-24 — Owner decision: reviewers receive the [THEORY-5] records
  in every brief; a changed-circumstances case is raised to the human
  owner for evaluation, never re-argued as a finding and never dropped.
- 2026-09-24 — Owner question: why is coalescing not retiring plans when
  it works in SimpleBroker? Diagnosis from both run logs: taut sweeps
  throttle to four oldest per run (unwritten norm from the first batch)
  and ran four times in six weeks with a month-long gap; SimpleBroker
  sweeps harvest all eligible candidates with parallel audits about
  weekly. Recommendation changed from retire-at-completion to the
  all-eligible sweep rule plus one catch-up sweep.

## Fresh-Eyes Review

Three of the eight outcomes are owner decisions and are separated into
task 1 so the mechanical gate work (tasks 3–5) can proceed and be reviewed
without them. Each gate change has a named red case drawn from the
review's actual mutation, not an invented one.
