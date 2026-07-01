# Plan: Remove `generate_knot.py` / stale `assets/` references

Date: 2026-06-30
Status: Implemented 2026-07-01 (see Implementation Record at end)
Risk: Low (tooling + docs; one mild destructive edge — deleting tracked assets)

## 1. Goal

The CI `lint` job runs `ruff … assets/gen_taut_logo.py generate_knot.py`. Neither
path exists: `generate_knot.py` was removed from the repository, and
`assets/gen_taut_logo.py` (plus `assets/taut-logo.svg`, `assets/taut-logo.svg.png`)
are already deleted in the working tree but still tracked. `ruff check` exits `1`
on a missing path, so the lint job is red on every push, and
`tests/test_github_workflows.py` asserts the broken command string verbatim, which
pins the bug in place. This change makes the lint command reference only files that
exist, finalizes the intentional asset deletions, and scrubs the now-spurious
references (including in historical plan docs, per owner decision).

## 2. Source Documents

Source spec: None — CI bug fix / tooling + docs cleanup.

Supporting context:
- Local architecture review artifact (2026-06-30), "Deepen the verification command
  module" — flagged this exact stale command and the string-matching test that
  preserves it.
- `docs/lessons.md` (lines ~53–54): repo style is owned by `ruff format` /
  `ruff check` (line length 88); the canonical lint target elsewhere is
  `taut tests bin` (see `README.md:449-450`).

## 3. Context and Key Files

Canonical lint target after this change is **`taut tests bin`** — matching
`README.md:449-450`. Files to touch:

Live surfaces (the actual bug):
- `.github/workflows/test.yml` — lines 98 and 103 run
  `ruff check taut tests bin assets/gen_taut_logo.py generate_knot.py` and the
  `ruff format --check` equivalent. This is the failing CI step.
- `tests/test_github_workflows.py` — lines 23 and 26 assert those exact broken
  strings are present in `test.yml` (`test_test_workflow_is_reusable_and_runs_release_gates`).

Working-tree asset state (finalize the intentional deletions):
- Tracked but deleted on disk (confirm with `git status --porcelain assets/` →
  ` D` for each): `assets/gen_taut_logo.py`, `assets/taut-logo.svg`,
  `assets/taut-logo.svg.png`.
- **Keep**: `assets/taut-knot.webp` (still on disk, still tracked).

Historical plan docs that still name the removed files (scrub per owner decision):
- `docs/plans/2026-06-17-github-actions-release-workflows-plan.md` — lines 80, 81,
  107, 110.
- `docs/plans/2026-06-17-taut-pg-extension-plan.md` — lines 484, 485, 1565, 1566,
  and the multi-line block at 1802–1807.

Read first:
- `.github/workflows/test.yml` §`lint:` (around lines 92–110) to see both ruff steps.
- `tests/test_github_workflows.py` (whole file, 104 lines) to see that every
  assertion is a substring check against workflow text, not an execution.
- `README.md:444-452` (the Development block) for the canonical `taut tests bin`
  target.

Comprehension checks before editing:
1. Why does the full test suite pass locally today while CI's lint step fails?
   (Answer: the workflow test only substring-matches the command in the YAML; it
   never runs `ruff`, so the missing-file failure is invisible to pytest.)
2. After removing both `assets/gen_taut_logo.py` and `generate_knot.py` from the
   command, does any *other* repo reference point at a missing `assets/` file?
   (Answer: no — `git grep 'assets/'` shows `assets/gen_taut_logo.py` is the only
   referenced asset path anywhere, and no doc/README references the logo images.)

## 4. Invariants and Constraints

- After the change, `ruff check taut tests bin` and `ruff format --check taut tests bin`
  must each exit `0`. That is the whole point — verify by running them, not by
  reading the YAML.
- The workflow test must guard against the dead-path regression, not merely
  substring-match. `"ruff check taut tests bin"` is a substring of the **broken**
  command too, so a positive substring assertion alone passes while the stale paths
  remain. The test must therefore also assert the dead tokens are absent
  (`"generate_knot.py"` and `"gen_taut_logo"` not in the workflow). Scope note: this
  guards against *these* dead tokens returning — it does not prove the ruff line is
  *exactly* `ruff check taut tests bin` (an implementer could append a different bad
  path and still pass). Fully asserting the exact command is the verification-catalog
  work in §9; here we close the specific regression. Do not delete the assertions;
  strengthen them. (Improving the test to *execute* ruff is also out of scope, §9.)
- Do not touch the PG workflow lint (`test-pg-extension.yml`, `extensions/…`) — it
  is a separate, correct command surface.
- Keep `assets/taut-knot.webp`. Only `gen_taut_logo.py`, `taut-logo.svg`, and
  `taut-logo.svg.png` are removed.
- No change to any `taut/` runtime code, package behavior, or public contract.
- Mild one-way door: deleting tracked brand assets. It is reversible from git
  history, but confirm the deletions are the intended three before staging.

## 5. Tasks

1. **Confirm the working-tree asset state.**
   - Run `git status --porcelain assets/` and confirm exactly three ` D` entries:
     `gen_taut_logo.py`, `taut-logo.svg`, `taut-logo.svg.png`; and that
     `assets/taut-knot.webp` is present and unmodified.
   - Stop-and-re-evaluate gate: if any *other* asset is deleted/modified, or the
     webp is gone, stop and report — the scope assumption is wrong.
   - Done signal: the three-and-only-three deletion set is confirmed.

2. **Stage the intentional asset deletions.**
   - Files: `assets/gen_taut_logo.py`, `assets/taut-logo.svg`,
     `assets/taut-logo.svg.png`.
   - Run `git rm assets/gen_taut_logo.py assets/taut-logo.svg assets/taut-logo.svg.png`
     (records the already-on-disk deletions in the index; do not delete
     `taut-knot.webp`).
   - Done signal: `git status --porcelain assets/` shows the three as staged
     deletions (`D ` in the first column) and no webp change.

3. **Fix the live lint command in the workflow.**
   - File: `.github/workflows/test.yml`.
   - Line 98: `ruff check taut tests bin assets/gen_taut_logo.py generate_knot.py`
     → `ruff check taut tests bin`.
   - Line 103: `ruff format --check taut tests bin assets/gen_taut_logo.py generate_knot.py`
     → `ruff format --check taut tests bin`.
   - Do not change surrounding steps (pytest, mypy, uv build) or indentation.
   - Done signal: `git grep -n 'gen_taut_logo\|generate_knot' .github/` → no matches.

4. **Update the workflow test to *pin* the corrected command.**
   - File: `tests/test_github_workflows.py`, `test_test_workflow_is_reusable_and_runs_release_gates`.
   - Replace the two ruff assertions (lines 22–28) with four:
     - `assert "ruff check taut tests bin" in workflow`
     - `assert "ruff format --check taut tests bin" in workflow`
     - `assert "generate_knot.py" not in workflow`
     - `assert "gen_taut_logo" not in workflow`
   - Why: the positive substring is present in the *broken* command too, so the two
     negative assertions are what stop this specific drift from recurring. (They
     guard against these dead tokens, not against every possible bad path — full
     exact-command assertion is deferred to the verification-catalog work, §9.)
   - Done signal: `pytest tests/test_github_workflows.py -q` passes; as a sanity
     check, temporarily re-adding `generate_knot.py` to `test.yml` makes it **fail**.

5. **Scrub the two historical plan docs (owner decision: scrub all references).**
   - File `docs/plans/2026-06-17-github-actions-release-workflows-plan.md`, lines
     80, 81, 107, 110: replace `... bin assets/gen_taut_logo.py generate_knot.py`
     with `... bin` in each command snippet.
   - File `docs/plans/2026-06-17-taut-pg-extension-plan.md`:
     - Lines 484, 485: `... bin assets/gen_taut_logo.py generate_knot.py` → `... bin`.
     - Lines 1565, 1566: `... bin assets/gen_taut_logo.py generate_knot.py extensions/taut_pg/taut_pg extensions/taut_pg/tests`
       → `... bin extensions/taut_pg/taut_pg extensions/taut_pg/tests`.
     - Lines 1802–1807 (multi-line block): drop the `assets/gen_taut_logo.py` and
       `generate_knot.py` tokens, preserving the remaining paths and the line
       continuation.
   - These are frozen-history docs; the only edit is removing the two dead path
     tokens from command snippets. Do not otherwise rewrite the plans.
   - Done signal (scoped to exclude *this* plan, which names both tokens as its
     subject):
     `git grep -n 'gen_taut_logo\|generate_knot' -- ':!docs/plans/2026-06-30-assets-reference-cleanup-plan.md'`
     → **no matches.** (`git grep` searches tracked files only, so if this plan is
     staged/committed the exclusion is what keeps the gate honest; the other two plan
     docs must show clean.)

## 6. Testing Plan

This is a tooling + docs change; verification is by running the real commands and
the existing workflow test — no new behavioral tests, nothing to mock.

- Layer/harness: local shell + the existing `tests/test_github_workflows.py`
  (reads real workflow files).
- Commands that prove the fix (all must be run, not reasoned about):
  - `uv run ruff check taut tests bin` → exit 0.
  - `uv run ruff format --check taut tests bin` → exit 0.
  - `uv run pytest tests/test_github_workflows.py -q` → pass.
  - `uv run pytest -q` → full suite still green.
- Observable proof: the corrected lint command exits 0 (previously 1), the workflow
  test asserts a command that actually succeeds, and `git grep` finds zero
  references to either removed path.
- Anti-mock: n/a — the workflow test reads real YAML; no dependency is mocked.

## 7. Verification and Gates

Per-task verification is listed inline in §5. Final gates before claiming
completion:

- `uv run ruff check taut tests bin` → 0
- `uv run ruff format --check taut tests bin` → 0
- `uv run pytest -q` → all pass
- `git grep -n 'gen_taut_logo\|generate_knot' -- ':!docs/plans/2026-06-30-assets-reference-cleanup-plan.md'`
  → no output (this plan is excluded because it names both tokens as its subject)
- `git status --porcelain assets/` → three staged deletions; `taut-knot.webp` intact
- (Optional, if `actionlint` is available) `actionlint .github/workflows/test.yml`
  → no new errors.

Post-merge success signal: the GitHub Actions `lint` job goes green on the next
push (it is currently red). No rollout sequencing needed.

Rollback: revert the workflow/test/doc edits; restore the three assets by name
(`git checkout HEAD -- assets/gen_taut_logo.py assets/taut-logo.svg assets/taut-logo.svg.png`)
— named explicitly, not `git checkout -- assets/`, so any unrelated asset edits are
not swept up. Fully reversible; no data or migration involved.

## 8. Independent Review Loop

- Reviewer: a different agent family than the author (per `CLAUDE.md` /
  [DOM-11]).
- Files to read: `.github/workflows/test.yml` (`lint:` job),
  `tests/test_github_workflows.py`, `README.md:444-452`, and this plan.
- Review prompt: "Read the plan at
  `docs/plans/2026-06-30-assets-reference-cleanup-plan.md`. Confirm the corrected
  lint target `taut tests bin` is complete (no other missing paths), that no live
  reference to a deleted asset remains, and that leaving `test.yml`'s test as a
  string assertion is acceptable for this scope. Could you implement this
  confidently and correctly?"
- Feedback handling: the author addresses each point by updating the plan,
  justifying the current choice, or marking it out of scope with reasoning.

## 9. Out of Scope

- **Unifying the verification-command catalog** (the review's "Strong"
  recommendation): the lint/format/mypy commands are duplicated across `test.yml`,
  `bin/release.py`, `docs/implementation/04`, and `test_github_workflows.py`, and
  they drift. Fixing that duplication is a separate change.
- Changing `test_github_workflows.py` from substring assertions to *executing*
  ruff/mypy — a real improvement, but not required to fix this bug.
- The PG extension workflow lint command (`extensions/…`) — already correct.
- Any `taut/` source change, and the `client.py` split (separate plan:
  `docs/plans/2026-06-30-client-module-split-plan.md`).

## 10. Fresh-Eyes Review

- Every touched file and line number is named in §3/§5; no "update the workflow"
  hand-waving.
- The canonical target `taut tests bin` is stated once and reused, matching an
  existing surface (README), so the implementer does not invent a new target.
- The one hazard — assuming which assets were deleted — is gated by Task 1's
  confirmation step before anything is staged.
- The proof is a command that must be *run* (ruff exit 0), not a YAML re-read,
  directly addressing why the bug survived CI-green-locally in the first place.

## Implementation Record (2026-07-01)

Executed per plan. Changes (working tree, not committed):

- **Task 1** — confirmed exactly three ` D` assets (`gen_taut_logo.py`,
  `taut-logo.svg`, `taut-logo.svg.png`); `taut-knot.webp` present. Gate passed.
- **Task 2** — `git rm` staged the three deletions.
- **Task 3** — `.github/workflows/test.yml:98,103` → `ruff check taut tests bin` /
  `ruff format --check taut tests bin`.
- **Task 4** — `tests/test_github_workflows.py`: two positive assertions +
  `"generate_knot.py" not in workflow` + `"gen_taut_logo" not in workflow`.
- **Task 5** — scrubbed `docs/plans/2026-06-17-github-actions-release-workflows-plan.md`
  and `docs/plans/2026-06-17-taut-pg-extension-plan.md`. Note: a bulk token-removal
  pass missed three snippet lines carrying an `extensions/…` suffix or a `\`
  continuation; the grep gate caught them and they were fixed directly. The gate did
  its job.

Verification (all green):

- `uv run ruff check taut tests bin` → exit 0 ("All checks passed!")
- `uv run ruff format --check taut tests bin` → exit 0 (30 files formatted)
- `uv run pytest` → 159 passed
- All workflow YAML parses.
- `git grep 'gen_taut_logo\|generate_knot' -- ':!docs/plans/2026-06-30-assets-reference-cleanup-plan.md'`
  returns only the two intended `not in` guard assertions in
  `tests/test_github_workflows.py` — no stale command references remain.
- `git status assets/` → three staged deletions; `taut-knot.webp` intact.

Gate-wording refinement for future reference: the §5/§7 grep gate should also
exclude `tests/test_github_workflows.py` (its negative-guard assertions necessarily
name the tokens), or read "no matches outside the cleanup plan and the test's `not
in` guards."

Not done here (left to the owner): committing. The working tree carries unrelated
pre-existing changes, so a commit should stage only the Plan 1 files
(`.github/workflows/test.yml`, `tests/test_github_workflows.py`, the two 2026-06-17
plan docs, the three asset deletions, and this plan).
