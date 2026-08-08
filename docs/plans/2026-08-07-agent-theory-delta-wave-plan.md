# Agent-Theory Delta Wave Plan (2026-08-07)

Status: completed — wave landed (see Execution Log); scoped review
blocker F1-F9, all nine applied; round-2 waived with mechanical
verification disclosed
Class: 5+P — normative spec text lands ([DOM-2], [DOM-5], [DOM-14],
[DOM-15]; new reference spec), and runbooks, skills, and gate scripts
are materially changed. Effective requirements: class 5 plus
pre-landing different-family review, scoped per the hub's
propagate-guidance skill step 6 (source content is hub-reviewed;
review covers adaptation only).
Hardening: N/A — no [DOM-5] risky trigger fires (docs and doc-gate
scripts only; the one scaffold contract change — coalesce-check
shallow behavior — is declared and reversible).

## Goal

Land the agent-theory delta wave: hub source pin `0423923`; this
repo's last pin agent-guidance @ `cec5666` (2026-07-28, landed
`7afcb14`). The delta spans both 2026-08 hub waves and the
program-theory document class. This repo's own program theory was
crystallized and ratified separately (plan
`2026-08-07-program-theory-crystallization-plan.md`, commit
`c541b48`), so the theory-scaffold items land as reference and
tooling, not as a stub.

## Source Documents

- `docs/specs/01-development-documentation-operating-model.md`
  [DOM-2], [DOM-5], [DOM-14], [DOM-15]
- Hub source, pinned: agent-theory @ `0423923` — extract with
  `git -C ../agent-theory show 0423923:<path>`. New references to the
  hub say "agent-theory"; existing "agent-guidance" provenance stays
  per this repo's rename policy (run-log row of 2026-07-28).

## Payload checklist (verified absent at HEAD `c541b48` before
transplant; grep-verified present at completion)

2026-08-06 hub wave:
1. writing-specs authoring-time enumeration-gate rule + anti-pattern.
2. engineering-principles §12 recursion floor (gates do not gate
   gates).
3. testing-patterns Pattern 7 (hostile-default neutralization —
   lands under its canonical number; this repo ends at Pattern 6).
4. review-loops bounded/timed/recorded different-family attempts.
5. agent-context README read-order declared-claim floor.
6. coalescing.md apparatus-share reporting cue.

Program-theory document class:
7. Definitional primer → `docs/specs/07-agent-theory-and-program-theory.md`
   (07: the hub's 02 slot is this repo's core product spec) + specs
   index entry.
8. `skills/crystallize-program-theory/` (hub end-state, incl. the
   citation tests; status line cites this plan + source SHA).
9. [DOM-2] module-theory paragraph (MODULE-THEORY.md convention,
   entry-time loading).

2026-08-07 hub backport wave + owner decisions:
10. [DOM-5] git-backed coalescing carve-out; [DOM-14] archive-rule
    bullets replacing landing-authorization text; [DOM-15] +2 sweep
    fixture rows; reconciliation of every landing-authorization
    clause in `skills/coalescing/SKILL.md` and `docs/coalescing.md`.
11. [DOM-15] Rules: ordinary-maintenance-is-Class-2 +
    promotions-gate-on-the-human-owner (hub owner decisions
    2026-08-07); [DOM-14] promotion-gate sentence; skill ceiling.
12. writing-plans Plan Lifecycle: status-index completion binding;
    supersession same-change flip; retirement-is-routine; source-SHA
    ref-reachability; second-agent-verification optional with
    current-tree re-check semantics; demotion-in-place.
13. Existence-check-first duties (writing-plans author-side;
    review-loops reviewer-side) with promotion provenance.
14. writing-specs gate-wiring rule — adapted: this repo's doc gates
    reach CI through the pytest modules inside `test.yml`
    (`tests/test_docs_references.py` etc.); the `bin/` entry points
    are sweep/propagation tools run by hand, stated as such.
15. Comprehension-gate teeth (writing-plans §3 normative;
    hardening-plans §14 pointer).
16. hardening-plans §15 release stop-gates — concrete to this repo:
    `bin/release.py`, four tag families, `require-green-workflows.py`,
    immutable releases.
17. review-loops: guidance-reviewable-and-blockable + deferred-units
    register; §5a audit-response protocol (conditional); timeout
    calibration.
18. maintaining-traceability: chain terminus `code/test evidence`;
    closure task-diff rule.
19. testing-patterns Pattern 8 (multiprocess aggregate deadlines +
    serialization-group rule).
20. writing-implementation-docs non-goal anti-duplication rule.
21. brainstorming-to-plan admission test (cites this repo's program
    theory adopted-alternatives admission test).
22. coalescing skill + state file: durable-guidance ceiling;
    evidence-trail posture (state-file recipe authoritative);
    additive watermark rule; report-when list. Unindexed tier:
    **natively gated here** by `bin/check-plan-status-index`
    (every plan file must appear exactly once), so the tier lands as
    a threshold row + skill note crediting the native gate, not new
    machinery.
23. Gate scripts: `bin/coalesce-check` shallow loud-skip with
    cue-syntax inventory (scaffold contract change, declared) +
    origin/main-limitation comment; `bin/check-dom15-fixtures`
    rigorous fence parser + expanded probes through the real path.
    `bin/check-doc-paths` is this repo's own pytest-grammar design —
    hub comments N/A, untouched.
24. decision-hierarchy Trusted Base for Normative Guidance section.
25. lessons.md Golden Rule 14: the lessons ledger is itself a
    reviewable surface (next free number verified: 13 exists).

## Divergences and adaptations

- Foreign names quoted with repo attribution, never backticked paths.
- Section citations by name where portable; principle numbering here
  matches canonical (verified by survey).
- The judgment paragraph's home is this repo's canonical startup
  order (landed with the theory commit `c541b48`), not AGENTS.md —
  AGENTS.md delegates by design.
- Owner WIP in the tree (dump-load plan rows and files): shared-dirty
  `docs/plans/README.md` lands via synthetic HEAD+mine blob; WIP
  files never staged.
- Provenance-check before transplant: coalescing repair-in-sweep
  doctrine originated here (hub credits taut `3706d73`) — the hub
  end-state of that paragraph is compared, not blindly re-landed.

## Deviation Log

| Spec ref | Planned behavior | Actual behavior | Rationale | Spec proposal |
|----------|------------------|-----------------|-----------|---------------|

## Tasks

1. Transplant payload 1–25 per adaptations; heading-anchored inserts
   with unique-match assertions against this repo's text.
2. Gates: `./bin/check-plan-status-index`, `./bin/check-dom15-fixtures`
   (+ `--self-test`), `python3 bin/coalesce-check`,
   `uv run --no-sync bin/check-doc-paths`,
   `uv run --no-sync bin/check-cli-claims`, targeted pytest
   (`tests/test_docs_references.py tests/test_plan_status_index.py
   tests/test_coalesce_check.py`).
3. Scoped independent review (different family): adaptation only.
4. Land by explicit file-list staging with the synthetic-blob
   protocol for the shared plans README; wave commit, then pin
   run-log row.
5. Coalescing sweep record: derive counts; honest checked-deferred —
   the 94-past-watermark lessons tier and ~58-candidate plans tier
   are their own authorized maintenance unit, already reported to the
   owner this session.

## Out of Scope

- Any product behavior; the dump-load WIP; the information-
  architecture/registry unit; the big harvest sweep.

## Review Log

| Date | Stage | Reviewer / result | Findings and disposition |
|------|-------|-------------------|--------------------------|
| 2026-08-07 | Scoped adaptation review, attempt 1 | codex CLI (900 s bound, completed in bound). Reviewer disclosure recorded: its different-family claude sub-pass failed (ConnectionRefused); three independent same-family read-only sweeps reproduced every finding locally — **blocker: F1–F9** | All nine accepted and applied: F1 ruff complexity/format — fence probes extracted to a helper, both scripts formatted with the repo's pinned Ruff, `ruff check`/`format --check`/mypy clean; F2 specs-index item 7 moved after item 6's continuation; F3 primer hub-relative wording named as foreign with Taut routed to its Active theory; F4 crystallize-skill internals retargeted ([AT-REF-*]/section names; hub meta-theory cited as foreign); F5 [DOM-14] archival-transitions bullet and the Plans deferral condition reconciled to the archive rule; F6 Unindexed zero-threshold row + skill step-1 note crediting the native `check-plan-status-index` gate; F7 shallow branch reports lessons counts and a firing test covers loud-skip/cue-count/lesson-count/exit 0; F8 release stop-gates rescoped — immutability attaches at publication, leased `--retag` recovery for unpublished tags preserved, local prechecks vs tag-triggered gates distinguished; F9 gate-wiring wording: execution path stated, CI where wired, explicit manual otherwise. Round-2 waived per the hub propagate-guidance skill step 6 (disclosed): every fix mechanically verified — 35/35 doc tests, all five gates, ruff, mypy. |

## Execution Log

(append-only)

- 2026-08-07: 25-item payload transplanted (heading-anchored,
  unique-match asserted; taut's native repair-in-sweep origin
  provenance-checked, not re-landed). Taut's own gates caught two
  adaptation defects mid-flight (primer path in the crystallize
  skill via test_docs_references; index row demand via
  check-plan-status-index) before review. Scoped review round 1:
  blocker F1–F9, all applied. Final battery: check-plan-status-index
  0, check-dom15-fixtures 0 (+self-test), coalesce-check 0 (0423923
  reported foreign @ agent-theory, correct), check-doc-paths 0,
  check-cli-claims 0, pytest doc modules 35/35, ruff check + format
  clean, mypy clean. Owner WIP (dump-load rows and files)
  byte-untouched; landed via the synthetic-blob protocol.
