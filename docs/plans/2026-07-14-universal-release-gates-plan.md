# Universal Release Gates Plan

Date: 2026-07-14

Plan type: implementation with spec revision.

## Goal

Make every `release.py` target (`core`, `pg`, `summon`, and `all`) use the same
repository-wide test boundary by default before publication: core, PostgreSQL,
and Summon, including strict external-provider and local-LLM smoke tests. Keep
`--skip-checks` as an explicit human override. Make every tag observer require
both canonical exact-SHA GitHub workflows without reenqueuing either workflow.

## Sources and Current Boundary

- `docs/specs/02-taut-core.md` [TAUT-12.1], [TAUT-12.5]
- `bin/release.py::build_precheck_commands_for_targets`
- `.github/workflows/release-gate*.yml`
- `tests/test_release_script.py`, `tests/test_github_workflows.py`
- `docs/implementation/04-taut-architecture.md`
- `docs/implementation/02-repository-map.md`
- `docs/implementation/05-taut-summon-architecture.md`

Today core releases run all local suites and require both canonical workflows.
PG releases omit local Summon gates. Summon releases omit local PG and its tag
observer requires only the root workflow. Canonical CI already creates both
workflow results on a branch push, so the remote change adds a required
evidence edge rather than another matrix.

## Spec Baseline

- Commit `d12adcf961bffdabc96b32f2416b9a4c3f7c940c`.
- Governing file at plan authoring time:
  `docs/specs/02-taut-core.md` [TAUT-12.5].
- The worktree initially differed from that commit only by this plan and its
  active-plan index entry.
- Promotion baseline: strategy A applied against
  `d12adcf961bffdabc96b32f2416b9a4c3f7c940c` in a dirty worktree containing
  only `docs/specs/02-taut-core.md`, `docs/plans/README.md`, and this untracked
  plan. The promoted spec blob is
  `e8a3d330a489b0f7520e1ca449790b231dd7b719`; the rerunnable exact promotion
  diff is
  `git diff d12adcf961bffdabc96b32f2416b9a4c3f7c940c -- docs/specs/02-taut-core.md`.

## Proposed Spec Delta

Promotion strategy: A, in-file requirement text before implementation-link
claims. Apply after independent review and before tests or implementation.

### `docs/specs/02-taut-core.md` [TAUT-12.5] helper obligations

Replace the local-gate bullet beginning “Run the relevant local gates” with:

> Each publishing invocation runs one universal precheck sequence, regardless
> of whether its selected target set contains one package or all packages,
> against its clean local preparation commit and before any branch push, tag
> creation or replacement, tag push, or publication unless `--skip-checks` is
> set. `--checks-only` runs that same single sequence without mutation. The
> sequence is:
> root pytest partitioned into `not slow and not installed_wheel` plus a fresh
> serial `not slow and installed_wheel` invocation, `bin/pytest-pg --fast`, the
> `extensions/taut_summon/tests` suite split into non-process, deterministic
> `xdist_group` process, strict external-live, and local-LLM lanes, ruff over
> root and both extension paths, and split mypy lanes so extension
> `conftest.py` modules do not collide. Target selection controls metadata,
> ordinary package builds, tags, and publication, not the default verification
> scope. `--skip-checks` remains an explicit human override for dry-run and
> publishing commands.
>
> The process/live/LLM lanes are isolated from unrelated summon tests because
> they drive multiple real processes against shared SQLite files. The
> deterministic process lane is a fixed-width pressure proof: local release
> checks run it with `-n 4 --dist load`. Its `xdist_group("process")` marker
> selects and co-locates the lane in broad default runs, but every selected test
> owns test-local resources because the isolated release invocation uses
> `--dist load` and intentionally ignores group co-location. Strict
> external-live and local-LLM lanes retain their existing known-safe
> `-n 1 --dist loadgroup` boundaries and select only
> `requires_live_harness` or `requires_local_llm`, respectively. Non-live
> diagnostics in those files remain owned by the unit lane. All three run as
> fresh pytest invocations rather than one long worker.

Replace the local-LLM and external-live bullet beginning “For core or summon
releases” with:

> For every target whose prechecks run, require the summon local-LLM lane
> locally. The helper starts one local-LLM preparation at the beginning of
> prechecks so Docker image/model setup can overlap root and PostgreSQL checks,
> waits immediately before the local-LLM selector, passes the prepared endpoint
> and model, and closes preparation after success or failure. It uses an
> existing loopback endpoint when the configured model is already listed;
> otherwise it starts a disposable loopback Ollama container with the same
> bounded model shape as CI, waits for the served model only when the dedicated
> local-LLM lane is reached, and runs that lane with
> `TAUT_SUMMON_LOCAL_LLM=1`. A separate external-live lane runs installed
> external harnesses in strict prewired mode and explicitly sets both
> `TAUT_SUMMON_LIVE_HARNESS=1` and
> `TAUT_SUMMON_LIVE_HARNESS_STRICT=1`; inherited `CI` or a disabled live env
> cannot turn an enabled precheck into skips. Missing, unready, or failing
> external providers and local models are fatal when prechecks run.

### `docs/specs/02-taut-core.md` [TAUT-12.5] workflow obligations

Replace “Core and PG tags require root plus PG evidence; Summon requires root
evidence” with:

> Every package tag requires successful root Test and PostgreSQL Test evidence
> for the exact peeled tag commit. The three tag gates observe those canonical
> workflows and never invoke them.

## Invariants and Hidden Couplings

- Every target plans and, unless a human explicitly passes `--skip-checks`, runs
  the same precheck command sequence. Target selection may still control
  metadata, package builds, tags, and publication artifacts.
- Strict external Summon harnesses and the local Ollama smoke remain hard
  failures whenever prechecks run. Universal gating must not introduce
  implicit skips, retries, or advisory conclusions.
- Every tag observer requires successful latest-attempt canonical `push`
  evidence from both `.github/workflows/test.yml` and
  `.github/workflows/test-pg-extension.yml` for the peeled tag commit.
- Tag workflows remain observers. They must not call reusable test workflows
  or rebuild packages.
- Artifact ownership stays with the root Test packaging job; each tag consumes
  only its package-specific immutable bundle.
- The local model preparation starts once and overlaps the earlier universal
  gates for every target whose prechecks run. It waits immediately before the
  local-LLM selector, supplies the prepared endpoint/model, and closes after
  success or failure.
- The external-live command forcibly enables live execution and strictness;
  inherited `CI` or `TAUT_SUMMON_LIVE_HARNESS=0` cannot skip it.
- `--skip-checks` remains a deliberate human override for all four public
  targets. It skips ordinary prechecks, but it does not suppress separately
  non-skippable build and paired-wheel compatibility gates.
- No package-version synchronization rule changes. A single-target release may
  still version, tag, and publish only that target. Existing paired
  core/Summon canary builds remain unchanged even when they build an
  unselected companion wheel for compatibility proof.

Hidden coupling: an unchanged branch push may not create a new workflow run.
Observers therefore continue to accept existing eligible exact-SHA canonical
evidence under the current latest-attempt and artifact rules. Requiring PG for
Summon is safe only because the observer keys by commit, not by tag time.

## Spec-Promotion and TDD Slices

1. Promote the reviewed exact delta into [TAUT-12.5], add this plan to the
   spec's Related Plans, and record base commit `d12adcf...`, the dirty-worktree
   state, the exact spec diff, and the promoted spec blob hash as the uncommitted
   strategy-A promotion baseline.
2. Characterize that `--skip-checks` remains accepted for `all`, `core`, `pg`,
   and `summon`; RED→GREEN the CLI help requirement that labels it an explicit
   human override. Preserve the existing non-skippable artifact-build and
   paired-wheel gates.
3. RED→GREEN: parameterize `core`, `pg`, `summon`, and the canonical combined
   target tuple; assert their precheck tuples are exactly equal to one literal
   universal order. The literal includes both root selectors, PG, all four
   Summon selectors, one full-path ruff command, one format command, and each
   mypy owner exactly once. Normalize command planning without changing builds.
4. RED→GREEN: prove every single target starts local model preparation exactly
   once, overlaps earlier gates, waits immediately before local LLM, supplies
   endpoint/model, and closes in `finally` after success and an earlier-gate
   failure. Remove target-dependent preparation selection.
5. RED→GREEN: extend the split live/LLM environment test to require literal
   `TAUT_SUMMON_LIVE_HARNESS=1` plus strictness, then force enablement in the
   live command environment.
6. RED→GREEN: remove the workflow test's root-only alternative so all three
   real observer files must contain exactly one root and one PG workflow
   argument. Add the PG argument to the Summon observer; do not add workflow
   calls.
7. Reconcile implementation docs, repository map, Summon architecture,
   lessons, traceability backlinks, review findings, and the deviation log.
8. Add the `CHANGELOG.md` heading for 0.6.3, complete final review, commit the
   implementation slice, and push it on the clean canonical branch. Once its
   canonical Test and PostgreSQL Test workflows are green, run
   `uv run python bin/release.py all --version 0.6.3`. Capture the release
   preparation commit SHA, then use `gh run list`, `gh run view`,
   `gh release view`, and `git rev-parse <tag>^{commit}` to prove exactly one
   canonical Test push run, one canonical PG push run, three successful tag
   observers, three GitHub Releases, matching peeled tag commits, and immutable
   package assets for that SHA. Confirm no Test or PG workflow was triggered by
   a tag.

Stop and re-evaluate if the implementation needs a new workflow, duplicates a
test run, changes package build selection, or weakens strict live gates.

## Verification

```bash
uv run --extra dev pytest tests/test_release_script.py -n 0 -q
uv run --extra dev pytest tests/test_github_workflows.py -n 0 -q
uv run --extra dev pytest tests/test_docs_references.py -n 0 -q
uv run --extra dev ruff check bin/release.py tests/test_release_script.py tests/test_github_workflows.py
uv run --extra dev ruff format --check bin/release.py tests/test_release_script.py tests/test_github_workflows.py
uv run --extra dev mypy bin/release.py tests/test_release_script.py tests/test_github_workflows.py --config-file pyproject.toml
uv run --extra dev python -c 'import pathlib, yaml; [yaml.safe_load(path.read_text()) for path in pathlib.Path(".github/workflows").glob("*.yml")]'
git diff --check
uv run python bin/release.py all --checks-only
```

After push, query runs by the exact release SHA. Require exactly one canonical
push Test run, one canonical PG run, three successful tag observers, three
GitHub Releases bound to that SHA, and no test workflow dispatched by a tag.
Use these exact post-release probes:

```bash
export RELEASE_SHA="$(git rev-parse HEAD)"
test "$(gh run list -R VanL/taut --commit "$RELEASE_SHA" --event push --workflow test.yml --limit 10 --json databaseId --jq 'length')" -eq 1
test "$(gh run list -R VanL/taut --commit "$RELEASE_SHA" --event push --workflow test-pg-extension.yml --limit 10 --json databaseId --jq 'length')" -eq 1
ROOT_RUN_ID="$(gh run list -R VanL/taut --commit "$RELEASE_SHA" --event push --workflow test.yml --limit 10 --json databaseId --jq '.[0].databaseId')"
PG_RUN_ID="$(gh run list -R VanL/taut --commit "$RELEASE_SHA" --event push --workflow test-pg-extension.yml --limit 10 --json databaseId --jq '.[0].databaseId')"
gh run view -R VanL/taut "$ROOT_RUN_ID" --exit-status
gh run view -R VanL/taut "$PG_RUN_ID" --exit-status
test "$(gh run view -R VanL/taut "$ROOT_RUN_ID" --json headBranch,headSha,event --jq '.headSha == env.RELEASE_SHA and .event == "push" and (.headBranch == "main" or .headBranch == "master")')" = true
test "$(gh run view -R VanL/taut "$PG_RUN_ID" --json headBranch,headSha,event --jq '.headSha == env.RELEASE_SHA and .event == "push" and (.headBranch == "main" or .headBranch == "master")')" = true
for WORKFLOW in release-gate.yml release-gate-pg.yml release-gate-summon.yml; do test "$(gh run list -R VanL/taut --commit "$RELEASE_SHA" --event push --workflow "$WORKFLOW" --limit 10 --json databaseId --jq 'length')" -eq 1; OBSERVER_RUN_ID="$(gh run list -R VanL/taut --commit "$RELEASE_SHA" --event push --workflow "$WORKFLOW" --limit 10 --json databaseId --jq '.[0].databaseId')"; gh run view -R VanL/taut "$OBSERVER_RUN_ID" --exit-status; done
test "$(git rev-parse 'v0.6.3^{commit}')" = "$RELEASE_SHA"
test "$(git rev-parse 'taut_pg/v0.6.3^{commit}')" = "$RELEASE_SHA"
test "$(git rev-parse 'taut_summon/v0.6.3^{commit}')" = "$RELEASE_SHA"
test "$(gh release view v0.6.3 -R VanL/taut --json tagName,isDraft,isPrerelease,assets --jq '.tagName == "v0.6.3" and (.isDraft | not) and (.isPrerelease | not) and ([.assets[].name] | sort == ["taut-0.6.3-py3-none-any.whl", "taut-0.6.3.tar.gz"]) and (all(.assets[]; .state == "uploaded" and (.digest | startswith("sha256:"))))')" = true
test "$(gh release view taut_pg/v0.6.3 -R VanL/taut --json tagName,isDraft,isPrerelease,assets --jq '.tagName == "taut_pg/v0.6.3" and (.isDraft | not) and (.isPrerelease | not) and ([.assets[].name] | sort == ["taut_pg-0.6.3-py3-none-any.whl", "taut_pg-0.6.3.tar.gz"]) and (all(.assets[]; .state == "uploaded" and (.digest | startswith("sha256:"))))')" = true
test "$(gh release view taut_summon/v0.6.3 -R VanL/taut --json tagName,isDraft,isPrerelease,assets --jq '.tagName == "taut_summon/v0.6.3" and (.isDraft | not) and (.isPrerelease | not) and ([.assets[].name] | sort == ["taut_summon-0.6.3-py3-none-any.whl", "taut_summon-0.6.3.tar.gz"]) and (all(.assets[]; .state == "uploaded" and (.digest | startswith("sha256:"))))')" = true
```

The exactly-one canonical workflow counts plus canonical `headBranch` checks
are the executable proof that no tag push dispatched Test or PostgreSQL Test.

Tests may replace subprocess execution when checking the release helper's
command plan, but must inspect the real workflow files. Final acceptance uses
real GitHub workflow evidence, real Docker PostgreSQL, real external provider
CLIs, and real Ollama.

### Local verification evidence

`uv run python bin/release.py all --checks-only` passed from the reconciled
worktree on 2026-07-14. It ran 873 broad root tests, 26 fresh serial
installed-wheel tests, 140 shared PostgreSQL tests, 13 PG-only tests, 245
Summon unit tests, 224 fixed-width process tests, eight strict external-provider
smokes, and one real local-Ollama PTY smoke. Full ruff and format checks passed,
as did all three mypy owners (84 root, six PG, and 37 Summon source files).
The focused release/workflow/docs suite passed 120 tests before this full gate.

## Rollout, Rollback, and Success Signals

Land the helper, observer, tests, spec, and implementation documentation in one
commit. Push the canonical branch before tags. Publish only after both exact-SHA
workflows are green. Success is three release observers completing with no
additional Test or PG workflow runs.

Rollback before publication is a normal revert. After publication, do not move
release tags; correct any defect in the next patch release. The change adds
gates and has no storage, package-runtime, or consumer compatibility effect.

## Independent Review

An independent reviewer checks for target asymmetry, duplicate workflow calls,
artifact-owner drift, hidden skips, and documentation mismatch after meaningful
behavioral slices and again before release. The first reviews blocked
implementation until the spec workflow, model lifecycle, strict enablement,
human `--skip-checks` override, retained topology requirements, promotion
identity, and executable patch-release slice were explicit. The revised plan
and exact spec delta then passed the required review before promotion.

The final pre-promotion review found no blockers. The implementation-slice
review found no defects after 110 focused release/workflow tests passed; it
confirmed one sequence per invocation, target symmetry, model cleanup on
success and failure, forced live enablement plus strictness, preservation of
the human override, and observer-only PG evidence for the Summon tag.
The final pre-commit review found no findings after the full local release gate
and documentation reconciliation. Its only residual risk was the intentionally
external exact-SHA CI, tag-observer, and GitHub-asset proof below.

## Deviation Log

| Spec ref | Planned behavior | Actual behavior | Rationale | Spec proposal |
|----------|------------------|-----------------|-----------|---------------|

## Out of Scope

- Consolidating the three waiting observer jobs into one coordinator.
- Changing CI matrices, timeout budgets, package versions, or dependency
  floors except through the normal patch-release preparation.
- Adding PyPI publication.

## Fresh-Eyes Questions

- Other than the explicit human `--skip-checks` override for local prechecks,
  can any target silently bypass a required gate?
- Can any target publish without both exact-SHA workflows succeeding?
- Does any tag push enqueue a test workflow?
- Do single-target releases still mutate, tag, and publish only the selected
  package while retaining mandated paired canary builds?
- Are strict external and local-LLM failures still fatal?
