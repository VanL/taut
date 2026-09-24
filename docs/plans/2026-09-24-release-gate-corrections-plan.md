# Release Gate Corrections Plan

Status: completed — implementation and independent completed-work review are
complete; the targeted completion commit contains only this release-gate unit.

Class: 4 (risky) under [DOM-5]: the change touches the publication path
(`.github/scripts/release_publication.py` post-upload verification) and a
release-gate test; rollback of a publication-path change depends on rollout
order, and release execution is irreversible once PyPI accepts an upload.
Hardening is required. No normative spec text changes: [TAUT-12.5]'s
fail-closed and exact-bytes invariants are unchanged; only budgets, a test
oracle, and help text move. Not process-changing.

Plan type: implementation against existing contracts.

Owner: implementing engineer.

## Goal

Remove three false failures and one misleading help gap from the release path
without weakening any guarantee. First,
`tests/test_release_script.py::test_pg_lockfile_is_not_retained_and_is_ignored`
asserts that a git-ignored file is absent from disk; any `uv run` inside
`extensions/taut_pg` creates it, so the root precheck lane (run under `-x`
after the preparation commit) aborts a local release for a file git already
ignores. The v0.5.2 plan's rule is "must not be committed", which
`.gitignore` enforces. Second, the PyPI post-upload check polls for about
80 seconds; PyPI's CDN lagged past that on 0.9.8 (`taut_mcp` gate run
35166744182 attempt 1 uploaded both files, then failed "last state was
absent") and on 0.9.0, so two of three 0.9.x reruns were caused by the
gate itself, and the 0.9.8 recurrence is unrecorded. Third,
`--skip-checks` silently drops the only lane that proves real provider
CLIs (the external live harness, which CI never runs), and `--help` does
not say so; and `all --version X --dry-run` refuses to preview without a
CHANGELOG heading. Evidence: `docs/plans/artifacts/2026-09-23-deep-dive-review.md`
§2 (Release) and the Release facet section.

## Requested Outcomes

- [ ] The PG lockfile test asserts the git-tracking invariant (`git
  ls-files --error-unmatch` fails) plus the `.gitignore` line, and no
  longer asserts filesystem absence.
- [ ] The PyPI post-upload verification budget is about five minutes with
  the same exact-file-set oracle; the 0.9.8 false failure is recorded in
  the 2026-08-14 finalizer plan's Execution Log (append-only) or in this
  plan.
- [ ] `bin/release.py --help` states that `--skip-checks` also skips the
  external live-harness lane.
- [ ] `--dry-run` for a not-yet-changelogged version warns and continues
  instead of stopping.

## Source Documents

Source specs:

- `docs/specs/02-taut-core.md` [TAUT-12.5] (release machinery; fail-closed
  publication; exact-artifact verification; resumable path)
- `docs/specs/01-development-documentation-operating-model.md` [DOM-5],
  [DOM-15] (routine-release exception boundary — this plan changes
  machinery, so it is outside the exception)

Supporting context:

- `2026-07-11-v0.5.2-coordinated-release-plan` (retired plan; source `06bfc93`) line ~73 (PG
  lock "must not be retained").
- `2026-08-14-pypi-finalizer-consistency-plan` (retired plan; source `73b56a0`) (completed;
  independent-runner PyPI visibility) — the 0.9.0 incident that shaped the
  current check.
- `docs/lessons.md` 2026-08-05 (manual lockfile deletions), 2026-08-11
  (publisher pin), 2026-07-13 (single build of the bytes).
- `docs/agent-context/runbooks/hardening-plans.md` §15 (release plans carry
  stop-gates; immutability attaches at publication).
- `docs/implementation/02-repository-map.md` rows for `bin/release.py`,
  `.github/scripts/release_publication.py`.
- `docs/plans/artifacts/2026-09-23-deep-dive-review.md` §2 (Release).

## Spec Baseline

- `c0a4616e76e954e3f9fbea93fbf487c3ee660cbe` — `docs/specs/02-taut-core.md`
  [TAUT-12.5] at plan authoring time; unchanged through `c894059` and unchanged by this plan.

## Context and Key Files

Files to modify:

- `tests/test_release_script.py` — `test_pg_lockfile_is_not_retained_and_is_ignored`
  (line ~3987–3997): `assert not pg_lock_path.exists()` then the
  `.gitignore` membership assertion.
- `.github/scripts/release_publication.py` — `PYPI_RETRY_DELAYS = (5, 10,
  15, 20, 30)` (line ~24) and `verify_pypi(expected, retry_delays=...)`
  (line ~277–294): polls `plan_pypi(expected)` until `state == "complete"`,
  then raises with `last state was <state>`.
- `tests/test_release_publication.py` — the retry-budget tests that pin
  the delay tuple.
- `bin/release.py` — the `--skip-checks` argparse help (grep
  `skip-checks`); the dry-run CHANGELOG heading check (grep `has no
  heading`).
- `tests/test_release_script.py` — dry-run CHANGELOG test(s).
- `.github/workflows/test.yml` lines ~222–233 (the root lane's
  `not requires_live_harness` marker exclusion) — read only, to word the help
  text truthfully.
- `.github/workflows/release-gate{,-pg,-summon,-mcp,-tui}.yml` and
  `.github/workflows/release-finalize.yml` — the six step-level timeout owners
  for the shared PyPI verifier.
- `tests/test_github_workflows.py` — firing proof for those timeout owners.

Read first: [TAUT-12.5] publication paragraphs; hardening §15;
`verify_pypi` and `plan_pypi`; the finalizer plan's rationale for the
bounded wait.

Comprehension gate:

1. **What does the PG lockfile rule protect, and what enforces it?**
   Expected: the PG extension must not ship or commit a lock (it depends
   on the root lock and Docker lane); `.gitignore` plus the dirty-tree
   check enforce non-commitment; the on-disk file affects no lane.
2. **What guarantee does `verify_pypi` provide and what would weaken it?**
   Expected: that the exact uploaded file set (names and digests) is
   visible before the immutable GitHub finalization; widening the wait
   does not weaken it; removing the digest comparison would.
3. **Why is `--skip-checks` outside the routine-release exception?**
   Expected: [DOM-15] names it as a bypass; it is classified normally and
   the help text must say what evidence it drops.

## Invariants and Constraints

- Fail-closed publication: `verify_pypi` still raises on an incomplete
  file set; only the budget changes.
- Exact-bytes: no change to digest comparison or artifact selection.
- The single-build rule and exact-SHA observer are untouched.
- The release helper's command sequence, tag names, and resumable path are
  unchanged; `tests/test_release_script.py` command-sequence pins stay
  green except the one oracle this plan corrects.
- No workflow YAML restructuring in this plan (the five-gate duplication
  is out of scope; see below). The six verifier step timeouts rise from five
  to ten minutes so the new budget can finish.
- No change to `--skip-checks` behavior, only its help text.

Hidden couplings:

- `PYPI_RETRY_DELAYS` is passed through by name in orchestration tests, but no
  literal tuple pin exists. Add only the behavioral proof that its total sleep
  budget stays between 300 and 360 s (lesson 2026-07-13: do not make a
  consistency test a second source for a literal).
- The shared verifier runs in five post-upload steps and inside the separate
  least-privilege finalizer. Each calling step currently has a five-minute
  timeout. Raise all six to ten minutes: the explicit worst case is 300 s of
  sleep plus nine HTTP calls capped at 30 s each (570 s), while the finalizer's
  15-minute job timeout remains above the step cap.

Failure policy: a PyPI check that still fails after five minutes remains a
hard failure (the immutable GitHub step must not run); the rerun path is
the existing resumable one.

## Rollout, Rollback, and One-Way Doors

- Source revert for all four items. The publication-script change ships
  with the next tag; if it misbehaves, the resumable rerun path applies,
  and no published artifact is affected because the change is before the
  irreversible step, not after.
- One-way door: none. Publication itself is unchanged.
- Post-deploy signal: the next coordinated release's five gate runs
  complete on attempt 1 with no "last state was absent" failure; a local
  `uv run` in `extensions/taut_pg` before a release no longer aborts the
  precheck.

## Dependency-Ordered Tasks

1. **Independent plan review.**
2. **Lockfile test.** Red: with a scratch `extensions/taut_pg/uv.lock`
   present, the current test fails; the new test passes when the file is
   untracked and ignored and fails when it is tracked (simulate by adding
   it in a scratch clone). Implement with `git ls-files --error-unmatch`
   via `subprocess` from `PROJECT_ROOT`, keep the `.gitignore` assertion.
   Stop if the test needs network or a non-git checkout.
3. **PyPI budget and caller timeouts.** Red: a test that
   `300 <= sum(PYPI_RETRY_DELAYS) <= 360`, plus workflow tests proving all five
   post-upload steps and the finalizer step allow ten minutes.
   Change the tuple to a geometric series totaling about 300 s (for
   example `(5, 10, 15, 30, 60, 60, 60, 60)`); raise the six calling
   step-level timeouts from five to ten minutes without changing topology;
   confirm the finalizer workflow's 15-minute job timeout. Record the 0.9.8
   run id and the "last state was absent" text in this plan's Execution Log.
   The retired finalizer plan is immutable in the current tree, so cite its
   source and prior 0.9.0 record here rather than resurrecting it for an
   append-only edit.
4. **Help text.** Red: a test that the `--skip-checks` help mentions the
   external live harness. Implement.
5. **Dry-run CHANGELOG.** Red: `all --version 0.9.99 --dry-run` in a
   scratch clone prints the plan and a warning line when the heading is
   absent. Add a focused single-target dry-run case for the second call site.
   Implement as warn-in-dry-run, fail-in-real-run. Stop if the real-run gate
   order changes.
6. **Docs, CHANGELOG, completed-work review, index flip.** Update
   `docs/implementation/02-repository-map.md` row text if the publication
   script's budget is described there.

## Testing Plan

- Layer: the existing `test_release_script.py` and
  `test_release_publication.py` harnesses (fake API payloads, scratch git
  clones). What stays real: git (`ls-files`), the argparse help, the
  dry-run plan printer.
- Do not mock `subprocess` for the `git ls-files` call. The retained assertion
  runs against `PROJECT_ROOT`; use a scratch repository only for the red or
  mutation proof that a tracked path fails the oracle.
- Mutation check: revert the tuple to the old total and confirm the
  budget test fails.

## Verification and Gates

```bash
uv run --extra dev pytest tests/test_release_script.py tests/test_release_publication.py tests/test_github_workflows.py -n 0
uv run --extra dev pytest -n auto --dist loadgroup
uv run --extra dev ruff check bin tests .github/scripts && uv run --extra dev mypy bin tests
python bin/release.py all --version 0.9.99 --dry-run   # in a scratch clone
bin/check-plan-status-index
```

## Independent Review Loop

Reviewer: a different family. Inputs: this plan, `verify_pypi`, the
finalizer plan, the lockfile test, hardening §15. Ask: "Does widening the
budget change any fail-closed property? Is the tracked-file oracle
sufficient for the v0.5.2 rule?"

## Out of Scope

- Collapsing the five tag-triggered gate workflows into one (the review's
  lighter design; separate Class 4 plan if the owner wants it — loses only
  per-package Actions run lists and requires re-registering four Trusted
  Publishers).
- Reducing `bin/release.py`'s metadata reconciliation.
- Codecov thresholds and branch protection (owner decisions, not machinery
  defects).
- Windows support for running the helper itself.

## Assumptions and Open Questions

1. **Resolved 2026-09-24 (owner): no branch protection on `main`.** It
   gets in the way of the solo fix-forward workflow; release safety comes
   from the exact-SHA gates, not from protection.
2. **Resolved by inspection:** the finalizer job timeout is 15 minutes, but
   each of the six verifier-calling steps is only five minutes. Task 3 raises
   those step caps to ten minutes so the 570-second explicit worst case fits.

## Deviation Log

| Spec ref | Planned behavior | Actual behavior | Rationale | Spec proposal |
|----------|------------------|-----------------|-----------|---------------|

## Review Log

- 2026-09-24, independent Claude plan review at baseline `39179c1`, terminal
  state `success` / `end_turn` / `completed`: **BLOCKED on R1** because all six
  verifier-calling steps had five-minute timeouts around a proposed 300-second
  sleep budget. R1 accepted with ten-minute step caps rather than the suggested
  seven or eight: nine HTTP calls each carry a 30-second explicit ceiling, so
  the plan budgets the 570-second worst case. R2 accepted: no literal retry
  tuple pin exists or should be added; the sum is the behavioral contract.
  R3 accepted: the goal now distinguishes three false failures from the help
  gap. R4 accepted: both the five post-upload callers and finalizer are named.
  R5 accepted: both batch and single-target dry-run call sites receive firing
  coverage. R6 accepted: the retained git assertion runs against the real
  repository; scratch state is only mutation evidence. R7 accepted: the help
  source is described as the root lane's marker exclusion, not a separate
  workflow section. With those dispositions, the blocker is removed and the
  plan is active.

## Execution Log

- 2026-09-24: RED proof ran the new budget, help, dry-run, git-tracking, and
  workflow-timeout tests. The ignored on-disk PG lock passed the new oracle;
  the other ten cases failed against the old 80-second budget, absent warning
  mode/help text, and five-minute step caps. GREEN passed all 11 focused cases,
  then all 238 release-script, publication, and workflow tests.
- 2026-09-24: `PYPI_RETRY_DELAYS` is now `(5, 10, 15, 30, 60, 60, 60, 60)`
  for 300 seconds of bounded sleep across nine exact observations. All five
  post-upload steps and the finalizer step now allow ten minutes; exact file
  names/digests, fatal mismatch classes, and the hard failure after exhaustion
  are unchanged.
- 2026-09-24: recorded the recurrence: taut-mcp release-gate run `35166744182`
  attempt 1 uploaded both 0.9.8 files, then the post-upload verifier failed
  with `last state was absent`. The prior 0.9.0 incident and recovery remain in
  retired finalizer plan source `73b56a0` (run `31831944421`).
- 2026-09-24: the PG lockfile proof now asks real git whether
  `extensions/taut_pg/uv.lock` is tracked and separately retains the ignore
  assertion. Dry-run warning mode fires from both batch and single-target call
  sites; real runs still fail on the same missing heading before mutation.
- 2026-09-24: focused Ruff, format, and mypy checks passed for the five changed
  Python files. `docs/implementation/02-repository-map.md` required no edit:
  its publication row describes the independently bounded exact convergence
  owner without pinning a duration.
- 2026-09-24: independent completed-work review returned **no blocker**. F1
  noted that `returncode != 0` also accepts fatal git errors; disposition:
  tightened to the expected untracked exit 1 so a broken checkout fails the
  test. F2 called the dry-run routing helper optional; disposition: retained
  because it keeps real-run calls on the pre-existing one-argument shape and
  makes the warning-only branch explicit. F3 noted the one-sided minimum could
  admit an accidental 50-minute budget; disposition: accepted with a 300–360 s
  behavioral range, still without a literal tuple pin. F4 noted that wall time
  can reach 570 s under nine maximum-duration HTTP calls; disposition: the
  CHANGELOG now says five-minute retry *sleep budget*, while the plan retains
  the explicit 570-second worst case and ten-minute caller caps.

## Fresh-Eyes Review

Every change is small and reversible; the only place to guess wrong is
whether the budget test pins the tuple or the sum, and task 3 says both,
with the sum as the behavioral pin.
