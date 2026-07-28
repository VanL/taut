# Agent-Guidance Delta Wave (2026-07-28)

Status: Active — transplants applied, local gates run; independent review
and landing authorization outstanding.

Class: 3+P — guidance propagation that adds two executable gates and edits
the coalescing skill, the root entry point, and the documentation inventory.
No spec text changes (the wave's spec-shaped payload is already present and
richer locally), so Class 5 does not fire.

Hardening: N/A — no [DOM-5] risky trigger fires. The wave adds two read-only
checkers and additive documentation text. It deletes nothing, advances no
watermark, retires no plan, and changes no product behavior.

## Goal

Land the genuinely-new-to-taut portion of the agent-guidance wave since
taut's `b248e1c` pin: the coalescing skill's cue-portability rule, the root
entry point's harness-scoping sentence, and two new executable gates
(`bin/check-doc-paths`, `bin/coalesce-check`) adapted to taut's layout and
ledger format — without transplanting back the two items the hub folded
*up* from taut, whose local versions are canonical.

## Source Documents

Source repository: agent-guidance, pin `cec5666` ("coalesce-check: include
agent-guidance in the sibling resolution list"). The wave was extracted at
`51626db` ("Land the guidance gates: the corpus checks its own claims") and
re-verified against `cec5666` when the hub advanced mid-session; see
§Source-State Note.

Consumer's prior pin: `b248e1c`, adopted in
`docs/plans/2026-07-17-agent-guidance-propagation-plan.md`.

Extraction rule: every payload was read from the pinned end state
(`git show 51626db:<path>`), never from an intermediate commit's diff.

Source specs:

- `docs/specs/01-development-documentation-operating-model.md` [DOM-12],
  [DOM-14], [DOM-15]

Operational sources (targets):

- `AGENTS.md`
- `skills/coalescing/SKILL.md`
- `docs/coalescing.md`
- `docs/implementation/02-repository-map.md`
- `docs/plans/README.md`
- `bin/check-doc-paths` (new)
- `bin/coalesce-check` (new)

## Source-State Note

At extraction time the hub's `HEAD` was `51626db` and its working tree
carried four uncommitted files (`docs/agent-context/runbooks/writing-plans.md`,
`docs/coalescing.md`, `docs/lessons.md`, `skills/coalescing/SKILL.md`)
holding the fold-up of taut's own 2026-07-28 inventions. Those edits are
**not** transplant sources for this wave: they originate here. Every payload
item was extracted from the committed pin `51626db`.

The hub then advanced during this session, committing exactly that material
as `e42762c` ("Fold up taut's repair-in-sweep doctrine and status-index
contract") plus `cec5666`. Every payload item was re-verified against the
new end state (`git diff 51626db..cec5666`):

- `AGENTS.md` and `bin/check-doc-paths`: byte-identical at both pins.
- `skills/coalescing/SKILL.md`: changed only by the fold-up; the
  cue-portability paragraph transplanted here is unchanged.
- `bin/coalesce-check`: one change, `SIBLINGS` gaining `agent-guidance`.
  This wave's adaptation A4 had made the same correction independently
  before the hub commit existed; the hub's back-port note names the mm
  wave-2 landing as its trigger. Convergent, not conflicting.
- `docs/agent-context/runbooks/writing-plans.md`, `docs/coalescing.md`, and
  `docs/lessons.md`: changed only by the fold-up — taut-sourced material,
  excluded per §Payload Checklist items 2, 3, and 9. The hub's new
  `docs/lessons.md` entry is the hub's own record of accepting taut's
  inventions (with lineage counts); it is not consumer payload.

Net effect of the hub advancing: no payload changed, and no re-extraction
was required. The plan is pinned at `cec5666`.

## Payload Checklist

One line per wave item, with its disposition. Every non-empty line is
grep-verified in §Verification and Gates.

| # | Item | Source (`51626db` unless noted) | Disposition |

Scoped review (grok, read-only, 2026-07-28, §4a-form): **no blocker**.
Verified: end-state fidelity at `cec5666` for the landed items; the two
EMPTY dispositions (Purpose; vocabulary bullet — this repo is the
fold-up's source and its local versions are richer) confirmed by diff;
the check-doc-paths import-of-local-grammar approach sound with its two
extra surfaces real; coalesce-check's 87-past-watermark count
cross-checks the deferral table exactly; the maintenance-note
correction accurate; shared-dirty touches held to single localized
inserts. All gates green (docs-references, plan-status-index, both new
tools, dom15).
|---|------|--------------------------------|-------------|
| 1 | Coalescing skill: cue-portability paragraph (published-mirror rule, `local-only pin` marker) | `skills/coalescing/SKILL.md` (identical at `51626db` and `cec5666`) | **Applied** — inserted at taut's equivalent point (lessons-tier source-pinning paragraph), adapted to name the now-installed `bin/coalesce-check` |
| 2 | Coalescing skill: Purpose-line "repair … accurate" wording | hub fold-up, since committed as `e42762c` | **Empty** — taut's Purpose already reads "repair defects in the memory surfaces … small, accurate, and hot". This wording was folded *up* from taut; transplanting it back would be a no-op duplicate. Diffed, not assumed |
| 3 | `writing-plans.md`: closed status-vocabulary bullet | hub fold-up, since committed as `e42762c` | **Empty** — taut's `## Plan Lifecycle and Retirement` already declares the closed vocabulary, the exemplar field, the `status-review` quarantine, and the executable gate (`bin/check-plan-status-index`), in richer form. The hub's bullet explicitly credits taut as first lineage ("Folded up 2026-07-28 from taut's status-index contract (its commit `3706d73`)"); mm's independently-invented free-text quarantine is the second lineage |
| 4 | `AGENTS.md`: harness-scoping sentence after the two overrides | `AGENTS.md` | **Applied** — verbatim, inserted after the self-attribution bullet |
| 5 | New gate `bin/check-doc-paths` | `bin/check-doc-paths` | **Applied, adapted** — see §Adaptations A1–A3 |
| 6 | New gate `bin/coalesce-check` | `bin/coalesce-check` | **Applied, adapted** — see §Adaptations A4–A6 |
| 7 | Registration of both gates in taut's documentation inventory | n/a (local requirement) | **Applied** — `docs/implementation/02-repository-map.md` Root Entry Points; `docs/coalescing.md` Verification clause; `skills/coalescing/SKILL.md` Read First |
| 8 | Coalescing skill maintenance note describing a future `coalesce-check` | `skills/coalescing/SKILL.md` (taut-local text) | **Applied, corrected** — see §Adaptations A7 |
| 9 | Hub payload deliberately *not* transplanted: repair-in-sweep doctrine; structured status-index contract; the hub's fold-up lessons entry | hub `e42762c` | **Excluded by direction** — taut is the source (its commit `3706d73`); local versions are canonical and richer (own tool, own renumbered steps) |
| 10 | Hub payload out of scope for taut | `bin/bootstrap-agent-guidance`, `LICENSE`, hub `docs/plans/*`, hub `docs/implementation/02-repository-map.md`, hub `skills/propagate-guidance/SKILL.md` | **Empty** — hub-native. The bootstrap script and the propagate-guidance skill are explicitly hub-only; the hub relicense and hub plan/index edits are hub-internal records |

## Context and Key Files

taut renumbered its coalescing skill relative to the hub: taut's step 1 is
"Inspect and repair the coalescing surfaces" (the doctrine the hub folded up
from here), so taut's derivation step is 2 and its lessons tier is **step 3**.
The hub's cue-portability paragraph lives in the hub's lessons tier
immediately after the `source_sha` pinning paragraph; taut's equivalent
point is inside step 3, between the source-pinning paragraph ending
"…(or the sweep stays additive-only)." and the line "For each tripped or
requested fold:".

taut already owns a path-claim gate: `tests/test_docs_references.py`
(`test_documented_paths_exist`). Its claim grammar covers five prefixes
(`docs`, `taut`, `tests`, `bin`, `extensions`) against 46 maintained
markdown sources — strictly broader than the hub checker's three-prefix
grammar. Its source list, however, does **not** include `docs/coalescing.md`,
which the hub checker scans by name. That gap is the new gate's real
contribution here.

## Invariants and Constraints

- Do not transplant the two fold-up items back into taut. Their local
  versions are canonical.
- Additive only. No existing taut sentence is rewritten except the one
  stale maintenance note (§Adaptations A7) whose precondition this wave
  makes true.
- No git writes in this unit: no `add`, `commit`, `stage`, `reset`, or
  branch operation. The wave is delivered as a verified working tree with
  an explicit changed-file list.
- No subagents.
- Provenance in copied text cites **this** repository's plan path and the
  source SHA — never a hub plan path. Hub plans are cited by quoted name
  only.
- Two path-claim checkers must not diverge into two definitions of "a path
  claim". `bin/check-doc-paths` imports taut's grammar rather than
  restating it.
- The status vocabulary and its checker stay owned by
  `bin/check-plan-status-index` and `tests/test_plan_status_index.py`.
  Nothing in this wave duplicates that mechanism.

## Adaptations

| # | Hub form | taut form | Why |
|---|----------|-----------|-----|
| A1 | `check-doc-paths` restates its own claim regex (`(?:docs\|skills\|bin)/…`) and its own scan list | Imports `LINK_PATH_RE`, `BACKTICK_PATH_RE`, `ALLOWLIST`, `_prose_lines`, and `_markdown_path_sources` from `tests/test_docs_references.py` | taut already owns a broader claim grammar. Two regexes for one invariant is a divergence hazard; one definition, two entry points is not |
| A2 | Scans `docs/agent-context`, `docs/specs`, `skills`, plus `AGENTS.md`, `docs/README.md`, `docs/coalescing.md` | Scans taut's 46 maintained markdown sources **plus** `docs/coalescing.md` (and `docs/plans/README.md`, the status index, which is a maintained routing surface the test's plans exclusion also skips) | Matches taut's actual layout; the added files are exactly the gap in the existing gate |
| A3 | `--scaffold` mode bootstraps via `bin/bootstrap-agent-guidance` | Mode removed | taut has no bootstrap script. The hub's fresh-install path is hub-native |
| A4 | `SIBLINGS` at `51626db` omitted `agent-guidance` and listed `taut` | `SIBLINGS = ["agent-guidance", "mm", "weft", "backstitch", "engram", "simplebroker"]` | `taut` is self here; `agent-guidance` is mandatory — taut's run log pins hub SHAs (`2f7eff6`, `b248e1c`, `a4b4345`) that resolve nowhere else. The hub reached the same conclusion independently in `cec5666`, so only the self-entry removal remains a local adaptation |
| A5 | Lessons regex `^- 20[0-9]{2}-[0-9]{2}-[0-9]{2}` | `^- 20[0-9]{2}-[0-9]{2}-[0-9]{2}:` (trailing colon) | Matches taut's **declared** derivation command in `skills/coalescing/SKILL.md` step 2 exactly. The colon changes the count here (90 vs 91): one ledger line begins with a date and no colon, and the declared command is the contract |
| A6 | Reports a bare dated-entry count | Also reports the count past the lessons watermark parsed from `docs/coalescing.md` | taut's threshold is denominated in entries *past the watermark*; a bare total cannot be compared to it |
| A7 | (taut-local) maintenance note: "When an executable `coalesce-check` script exists, replace step 2's manual derivation with it" | Rewritten to state what the installed tool actually does: verify SHA claims and retrieval cues, report the lessons counts; the plans tier stays with `bin/check-plan-status-index`; the manual commands remain the fallback | The note's precondition is now true. Left as written it would instruct a future sweep to replace a derivation the tool does not fully perform — a false instruction |
| A8 | Hub skill's cue paragraph says "where a coalesce-check tool is installed" | Names `bin/coalesce-check` directly | The tool is installed here; a conditional would read as speculative |

## Tasks

1. Insert the harness-scoping bullet in `AGENTS.md` after the
   self-attribution override. — done
2. Insert the cue-portability paragraph in `skills/coalescing/SKILL.md`
   step 3, before "For each tripped or requested fold:". — done
3. Add `bin/coalesce-check` to the skill's Read First list; correct the
   stale maintenance note (A7). — done
4. Add adapted `bin/check-doc-paths`. — done
5. Add adapted `bin/coalesce-check`. — done
6. Register both gates in `docs/implementation/02-repository-map.md` and in
   the `docs/coalescing.md` Verification clause. — done
7. Add this plan's row to the Plan Status Index; run
   `bin/check-plan-status-index`. — done
8. Run both new gates and `tests/test_docs_references.py`. — done
9. Independent review scoped to adaptation only; then landing
   authorization. — outstanding

## Testing Plan

These are read-only checkers over repository text; their proof is
execution against the real tree, not fixtures.

- `bin/check-doc-paths` must exit 0 on the current tree and must report a
  scan surface that includes `docs/coalescing.md` (the file the existing
  pytest gate does not cover).
- `bin/coalesce-check` must exit 0, resolve every SHA claim in
  `docs/coalescing.md` either locally or in a named sibling, and report
  `local-only pin` for claims absent from `origin/main`.
- `tests/test_docs_references.py` must stay green after the new backticked
  path claims are added to the repository map and the coalescing state file.
- `bin/check-plan-status-index` must exit 0 after this plan's index row.

## Verification and Gates

Payload completeness greps (one per applied checklist line) and gate
outputs are recorded in the handoff report for this wave. Gate commands:

```bash
bin/check-doc-paths
bin/coalesce-check
bin/check-plan-status-index
uv run python -m pytest tests/test_docs_references.py -q
```

## Independent Review Loop

Scope fence for the reviewer, verbatim: *the source content is already
reviewed in agent-guidance at `51626db`; review ONLY the adaptation* —
insert placement, the empty dispositions in §Payload Checklist, the
single-grammar decision in A1, the scan-surface delta in A2, the colon
regex in A5, the corrected maintenance note in A7, and whether any added
text is performative rather than load-bearing.

Preferred: a different agent family from the author. Not yet run.

## Out of Scope

- Committing, staging, or otherwise writing git state.
- Retiring plans, advancing watermarks, or any destructive coalescing step.
- Backfilling the repository map's other missing inventory rows
  (`docs/coalescing.md`, `skills/coalescing/SKILL.md`, and
  `bin/check-dom15-fixtures` have no rows). That is coalescing maintenance
  for taut's next authorized sweep, not propagation work. Recorded here so
  it is not lost. `bin/check-plan-status-index` **was** added in this wave,
  as a deliberate exception: the two new gates are listed beside it and a
  reader finding two of three sibling gates would draw the wrong
  conclusion about which gates exist.
- Widening `tests/test_docs_references.py`'s own source list to include
  `docs/coalescing.md`. The new CLI closes the gap without changing an
  existing gate's contract mid-propagation; merging the two surfaces is a
  separate, reviewable decision.

## Fresh-Eyes Review

A zero-context engineer should be able to answer: which four hub items
landed, which six were deliberately empty and why, and which two came from
taut in the first place. The §Payload Checklist table is the single place
that answers all three.
