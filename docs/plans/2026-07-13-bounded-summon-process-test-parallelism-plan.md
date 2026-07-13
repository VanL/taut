# Bounded Summon Process Test Parallelism Plan

Status: Implemented and verified locally; remote CI observation pending.

Plan type: Implementation with spec revision.

## Goal

Replace the deterministic taut-summon process lane's exact-one-worker policy
with fixed, bounded concurrency: four xdist workers for local release checks
and two workers per CI runner. Preserve the fresh-invocation boundaries and
keep the external-live and local-LLM lanes at one worker.

## Requested Outcomes

- Local release prechecks run the deterministic process selector with
  `-n 4 --dist load`.
- CI process and coverage invocations run that selector with
  `-n 2 --dist load`.
- The CI process matrix no longer uses `max-parallel: 1` because matrix jobs
  run on isolated hosts.
- Broad default extension runs retain `xdist_group("process")` and
  `--dist loadgroup`, so only the isolated deterministic lane opts into
  concurrent process topologies.
- Strict external-live and local-LLM invocations remain at
  `-n 1 --dist loadgroup` as their existing known-safe boundaries.
- Spec, implementation guidance, the active verification plan, tests, and
  durable lessons agree with the new policy.

## Source Documents

- `docs/specs/02-taut-core.md` [TAUT-12.5], release-helper and reusable-CI
  obligations.
- `docs/implementation/05-taut-summon-architecture.md`, Change Guidance.
- `docs/plans/2026-07-12-lazy-command-extensions-and-rich-tui-composition-plan.md`,
  full repository and extension gates.
- `docs/lessons.md`, 2026-07-08 process-lane isolation lessons.
- User decision in this task: local `-n 4`, CI `-n 2`, with xdist pressure as
  part of the proof rather than speed alone.

## Spec Baseline

- Commit: `b03709452cf4d5962b0d7204b0dab78b9bafd524`.
- Plan start includes a pre-existing dirty worktree owned by the user.
- `docs/specs/02-taut-core.md` worktree blob before this plan's edits:
  `89833ecc1cb00141766c7a94e455355bd5d793ce`.
- Other overlapping worktree blobs at plan start:
  `.github/workflows/test.yml`
  `6382f813aadb318b1261157b66863c807a652cbf`, `bin/release.py`
  `4aff0908dcf2403ac1615c6f5e797065bf6f6cef`,
  `tests/test_github_workflows.py`
  `7339527023f51e36f922d01414fa7b6cadd93e42`, and
  `tests/test_release_script.py`
  `0f1e15b8228cbdf1a10853bcdcf2e715549f80ca`.

## Context and Key Files

- `bin/release.py` owns the local release precheck command tuples. Its
  `SUMMON_PROCESS_TEST_COMMAND` currently fixes the deterministic selector at
  one loadgroup worker; the live and local-LLM tuples are separate.
- `.github/workflows/test.yml` owns a dedicated deterministic process matrix
  job and a separate coverage invocation of the same selector. The job
  currently caps the whole matrix at one concurrent job and each invocation at
  one loadgroup worker.
- `extensions/taut_summon/tests/conftest.py` adds
  `xdist_group("process")` to real-driver tests. Module markers use that same
  group. The broad default suite therefore remains serialized under
  `--dist loadgroup`; the isolated lane must select those tests but override
  scheduling with `--dist load` to exercise more than one topology. Its
  process-pressure comments and the marker description in
  `extensions/taut_summon/pyproject.toml` are rationale owners and must describe
  this dual role accurately.
- `tests/test_release_script.py` and `tests/test_github_workflows.py` are the
  executable configuration contracts. They must fail before production
  config changes and then pass with exact worker and scheduler values.
- `docs/specs/02-taut-core.md`,
  `docs/implementation/05-taut-summon-architecture.md`, and the active
  2026-07-12 plan currently prescribe one worker and must be reconciled.

Comprehension gates:

1. Why does changing `-n 1` to `-n 4` while retaining `--dist loadgroup` not
   create deterministic-lane pressure? All selected items share the same
   `process` group, so loadgroup assigns them to one worker.
2. Which workloads remain serial? External-live and local-LLM lanes, because
   their parameterized external-provider and prepared-model topologies retain
   their existing known-safe boundaries; this change affects only the
   deterministic scripted-provider process selector.

## Invariants and Constraints

- Do not alter production summon process topology, provider behavior, SQLite
  sync mode, broker maintenance settings, readiness deadlines, or retry policy.
- Keep deterministic, external-live, and local-LLM workloads in fresh pytest
  invocations; do not collapse them into one worker lifetime.
- Keep process group markers so broad default extension runs do not acquire
  unbounded `-n auto` process fan-out.
- Every test selected into the deterministic process lane must own test-local
  databases, paths, file descriptors, and subprocesses. Under `--dist load`,
  the process marker selects the isolated lane; it does not serialize items or
  protect a shared resource.
- Use fixed worker counts. Do not use `-n auto`; pressure must have the same
  meaning on hosts with different CPU counts.
- Local and CI values intentionally differ. Tests and docs must name both
  values rather than asserting vague parallelism.
- CI coverage must mirror the CI deterministic process topology. Otherwise
  coverage can pass under a weaker execution mode than the main CI lane.
- The coverage job's `PYTEST_ADDOPTS` supplies `-n auto --dist loadgroup`, but
  the explicit process command follows it and must override both values. The
  verification log must show two workers under the load scheduler, not infer
  the override from text alone.
- Matrix jobs may run concurrently because GitHub-hosted jobs have isolated
  runner filesystems and process tables. Reintroduce `max-parallel` only for a
  separately documented account quota or cost constraint, not SQLite safety.
- Preserve all pre-existing user changes in overlapping files. No incidental
  formatting or unrelated cleanup.
- No new dependency, process wrapper, marker vocabulary, or test helper.

## Hidden Couplings and Failure Priorities

- `xdist_group` is both a selection marker and a scheduling group. The isolated
  lane still selects it with `-m`, but `--dist load` is required to bypass its
  co-location effect.
- The local release helper and reusable CI workflow intentionally use different
  worker counts. Exact command guards are the drift gate.
- A failure in the bounded parallel process lane is a release/CI failure, not a
  best-effort stress signal and not a candidate for an automatic serial retry.
  A manual `-n 1` rerun may classify a failure but must not erase the original
  failure.
- External-live and local-LLM execution topology is unchanged; widening those
  parameterized external-provider or prepared-model lanes would be a separate
  plan and needs its own evidence.

## Rollout and Rollback

Roll out spec and configuration in one worktree change after plan review. The
change has no product data or compatibility migration and no one-way door.
Observe the existing CI OS/Python matrix for timeouts, worker crashes, and
SQLite/control failures. If two workers are unstable on the slowest runner,
the CI rollback unit is the [TAUT-12.5] text, workflow and coverage commands,
and their exact guard tests together; restore those to
`-n 1 --dist loadgroup`. The local rollback unit is the spec text, release
tuple, and release guard together. Keep the fresh job boundary and do not
weaken SQLite sync or skip tests. Local and CI widths remain independently
revertible.

## Proposed Spec Delta

Promotion strategy: A, in-file text first. Promote the two [TAUT-12.5]
release-helper paragraphs after independent plan review, before changing tests
or command configuration. Add this plan to `## Related Plans` in the same
promotion slice.

### `docs/specs/02-taut-core.md` [TAUT-12.5] local helper obligation

Replace exactly this sentence span, leaving the preceding root/PG/ruff/mypy
gate enumeration intact:

> The process/live/LLM lanes are isolated from unrelated summon tests because
> they drive multiple real processes against shared SQLite files; xdist still
> schedules each lane with `-n 1 --dist loadgroup`, but the lanes run as fresh
> pytest invocations rather than one long worker.

Replacement text:

> The process/live/LLM lanes are isolated from unrelated summon tests because
> they drive multiple real processes against shared SQLite files. The
> deterministic process lane is a fixed-width pressure proof: local release
> checks run it with `-n 4 --dist load`. Its `xdist_group("process")` marker
> selects and co-locates the lane in broad default runs, but every selected test
> owns test-local resources because the isolated release invocation uses
> `--dist load` and intentionally ignores group co-location. Strict
> external-live and local-LLM lanes retain their existing known-safe
> `-n 1 --dist loadgroup` boundaries. All three run as fresh pytest invocations
> rather than one long worker.

### `docs/specs/02-taut-core.md` [TAUT-12.5] CI obligation

Replace exactly this full bullet:

> - In `.github/workflows/test.yml`, keep summon's deterministic process lane
>   aligned with the release helper selector:
>   `xdist_group and not requires_live_harness and not requires_local_llm`. Run
>   that lane as a dedicated fresh matrix job, still under `-n 1 --dist
>   loadgroup`, so it is not preceded by the broad root and summon unit suites in
>   the same runner environment. The local-LLM lane runs in its own CI job with a
>   prepared loopback Ollama model. External-provider live harnesses are a strict
>   local release gate unless CI grows explicit credentials/tooling for those
>   provider CLIs.

Replacement bullet:

> - In `.github/workflows/test.yml`, keep summon's deterministic process lane
>   aligned with the release helper selector:
>   `xdist_group and not requires_live_harness and not requires_local_llm`. Run
>   that lane as a dedicated fresh matrix job under `-n 2 --dist load`, so it is
>   not preceded by the broad root and summon unit suites in the same runner
>   environment. The coverage invocation of the same deterministic selector
>   uses the same two-worker topology. Do not serialize the matrix itself for
>   SQLite safety; matrix jobs run on isolated hosts. The local-LLM lane runs in
>   its own CI job with a prepared loopback Ollama model. External-provider live
>   harnesses are a strict local release gate unless CI grows explicit
>   credentials/tooling for those provider CLIs.

## Promotion Baseline

- Commit baseline `b03709452cf4d5962b0d7204b0dab78b9bafd524` plus the
  pre-existing dirty worktree and promoted `docs/specs/02-taut-core.md`
  worktree blob `e208120deb5d87d4fae5e840fe9865199b897cde`.
- Strategy A promotion applied after both read-only reviews and before command
  or guard changes. `git diff --check` passed for the promoted spec, this plan,
  and the plan index.

## Tasks

1. Review and promote the spec delta.
   - Review this plan, its exact delta, current command owners, and config
     guard tests with a read-only independent Claude pass.
   - Apply the reviewed text to `docs/specs/02-taut-core.md`; add the reciprocal
     Related Plans link; record the promoted worktree blob here.
   - Stop if review finds that matrix jobs share a host/resource or that a live
     lane is included in the deterministic selector.
   - Done signal: review findings are dispositioned and the promoted spec is
     the single governing contract.

2. Red-green the local release command.
   - First change only `tests/test_release_script.py` to require
     `-n 4 --dist load` and to pin the retained live and local-LLM tuples at
     `-n 1 --dist loadgroup`; run its focused test and observe failure.
   - Change only `SUMMON_PROCESS_TEST_COMMAND` in `bin/release.py`; retain the
     live and local-LLM tuples at one loadgroup worker.
   - Stop if the command builder rewrites or normalizes the tuple elsewhere;
     update the existing path rather than add a second command.
   - Done signal: the focused release test passes.

3. Red-green the CI workflow policy.
   - First update `tests/test_github_workflows.py` to require no
     `max-parallel:` key, exact `-n 2 --dist load` in the process job, and the
     same topology in the deterministic coverage invocation. Retain exact
     one-worker assertions for live and local-LLM commands.
   - Run the focused workflow tests and observe failure.
   - Update `.github/workflows/test.yml` minimally to satisfy those contracts.
   - Done signal: the focused workflow tests pass.

4. Reconcile durable guidance.
   - Update `docs/implementation/05-taut-summon-architecture.md` with the fixed
     local/CI concurrency split and retained one-worker live lanes. Add
     [TAUT-12.5] to its governing references and this plan to its Related Plans.
   - Update the bounded-pressure rationale in
     `extensions/taut_summon/tests/conftest.py` and the `xdist_group` marker
     description in `extensions/taut_summon/pyproject.toml`. State that
     deterministic-lane items must own test-local resources and that
     `--dist load` makes the marker selection-only in the isolated lane.
   - Update the active 2026-07-12 plan's current full-gate command to local
     `-n 4 --dist load`; do not rewrite historical evidence tables.
   - Append a 2026-07-13 correction to `docs/lessons.md`; preserve the
     2026-07-08 incident record.
   - Add this plan to `docs/plans/README.md`.
   - Done signal: grep finds no live contract that still prescribes one worker
     for the deterministic selector.

5. Verify and independently review the completed slice.
   - Run the exact configuration guards, docs-reference gate, and formatting
     checks.
   - Run the real deterministic selector at local `-n 4 --dist load` and at
     CI-equivalent `-n 2 --dist load`; broker, SQLite, subprocesses, and PTYs
     stay real.
   - Repeat the two-worker command with the coverage job's `PYTEST_ADDOPTS` and
     inspect the xdist header for two workers under `load`, proving command-line
     override rather than assuming it.
   - Give the final focused diff and evidence to an independent Claude
     reviewer. Disposition every finding in this plan.
   - Done signal: all named gates pass or residual risk is explicit.

## Testing Plan

TDD uses two vertical slices: the release-command contract, then the workflow
contract. Configuration files are the public artifact under test; assertions
use exact literal commands from the reviewed spec. No product process, broker,
SQLite database, subprocess, PTY, or workflow text is mocked. The real process
selector is then executed with both fixed widths as an integration proof. The
release guard also pins the unchanged one-worker suffixes for both
single-resource lanes; the workflow guard rejects every undocumented
`max-parallel:` cap, not only the former value of one.

## Verification and Gates

```bash
uv run pytest tests/test_release_script.py::test_summon_precheck_commands_include_extension_gate -n 0 -q
uv run pytest tests/test_github_workflows.py::test_test_workflow_is_reusable_and_runs_release_gates tests/test_github_workflows.py::test_coverage_measures_core_and_summon_in_isolated_process_lanes -n 0 -q
uv run pytest tests/test_release_script.py tests/test_github_workflows.py -n 0 -q
uv run pytest tests/test_docs_references.py -n 0 -q
uv run pytest extensions/taut_summon/tests -m "xdist_group and not requires_live_harness and not requires_local_llm" -n 4 --dist load -q
uv run pytest extensions/taut_summon/tests -m "xdist_group and not requires_live_harness and not requires_local_llm" -n 2 --dist load -q
PYTEST_ADDOPTS='-ra -q --strict-markers -n auto --dist loadgroup' \
  uv run pytest extensions/taut_summon/tests \
  -m "xdist_group and not requires_live_harness and not requires_local_llm" \
  -n 2 --dist load -vv
uv run --extra dev ruff check bin/release.py tests/test_release_script.py tests/test_github_workflows.py
uv run --extra dev ruff format --check bin/release.py tests/test_release_script.py tests/test_github_workflows.py
git diff --check
```

Observed post-rollout success is a green `taut-summon process` matrix without
worker crashes, control/readiness timeouts, or SQLite corruption diagnostics.
The main residual risk is slow-runner flake that cannot be reproduced on the
local host; the existing matrix is the acceptance environment for that risk.

## Independent Review Loop

- Plan review: fresh read-only Claude review of this plan, the exact proposed
  delta, and current command/test owners before promotion.
- Final review: fresh read-only Claude review of the focused diff and current
  verification evidence.
- Review stance: find wrong selectors, accidental live-lane widening, hidden
  loadgroup serialization, stale one-worker contracts, and weak verification.
- Every finding is accepted and fixed, rejected with reasoning, or marked out
  of scope below.

## Review Findings and Dispositions

Independent Claude plan review completed 2026-07-13.

| Finding | Disposition |
|---------|-------------|
| [P1] “Replace the paragraph” could delete the same bullet's binding root/PG/ruff/mypy gates. | Accepted. The delta now quotes the exact old sentence span and explicitly preserves the preceding gate enumeration. |
| [P2] Coverage topology depended on command-line options overriding `PYTEST_ADDOPTS` without an observed proof. | Accepted. The plan names the coupling and adds an exact-env run whose xdist header must report two workers under `load`. |
| [P2] Release guards did not pin retained one-worker live and local-LLM tuples. | Accepted. Task 2 and the testing contract now require exact suffix assertions for both. |
| [P2] Conftest rationale and marker description would remain stale; `--dist load` changes the marker to selection-only in the isolated lane. | Accepted. The plan adds both rationale owners and the test-local-resource invariant. |
| [P2] Rollback was narrower than the promoted spec and exact guards. | Accepted. Rollback units now include spec, configuration, and guards together. |
| [P2] The workflow guard should reject every undocumented `max-parallel:` value and history should confirm the old setting's origin. | Accepted. Task 3 rejects the key entirely. History inspection found `max-parallel: 1` introduced in commit `62815750` (“Isolate summon process CI lane”) with SQLite/process-lane isolation docs and no quota or cost rationale. |
| [P2] “Single external harness” overstated an eight-provider parameterized lane. | Accepted. The delta now preserves the existing known-safe boundary without inventing a single-resource rationale. |
| [P2] Implementation traceability did not require [TAUT-12.5] or a Related Plans backlink. | Accepted. Task 4 now requires both links. |
| [P2] The final review found that the one-line marker metadata did not itself state test-local ownership or selection-only behavior under isolated `load`. | Accepted. Extended the marker description to state both points; the detailed rationale remains in `conftest.py` and the implementation guide. |

Claude and a second read-only reviewer confirmed the selector excludes both
live classes, all current explicit groups use `process`, default addopts retain
loadgroup co-location, and implementation is safe after these revisions. The
second reviewer independently reproduced the blocking replacement-span issue
and the retained-lane guard, rollback, and conftest-rationale gaps; those were
already addressed above.

## Deviation Log

| Spec ref | Planned behavior | Actual behavior | Rationale | Spec proposal |
|----------|------------------|-----------------|-----------|---------------|

## Out of Scope

- Production summon concurrency or subprocess counts.
- External-live or local-LLM worker fan-out.
- `-n auto`, dynamic worker selection, CI cost controls, or account-wide
  GitHub Actions concurrency policy.
- SQLite, SimpleBroker, retry, timeout, readiness, or PTY lifecycle changes.
- Rewriting historical plans or incident evidence that accurately records the
  former one-worker policy.
- Committing, staging, or reverting any existing worktree changes.

## Execution Log

- 2026-07-13 preflight: before edits, the current deterministic selector
  passed locally under `-n 2 --dist load` in 70.07s, `-n 4 --dist load` in
  39.34s, and `-n 8 --dist load` in 27.38s. These single-host passes disprove
  an exact-one-worker design invariant but do not replace the CI acceptance
  matrix.
- 2026-07-13 plan review: independent Claude review found one blocking spec
  replacement ambiguity and five advisory proof/rationale gaps. All were
  accepted into the plan before spec promotion.
- 2026-07-13 spec promotion: [TAUT-12.5] now owns local four-worker and CI
  two-worker deterministic pressure, retained serial live/LLM lanes, test-local
  resource ownership, coverage parity, and matrix-host isolation. Promotion
  blob: `e208120deb5d87d4fae5e840fe9865199b897cde`.
- 2026-07-13 local release red-green: the existing release-command contract
  first failed on the old `-n 1 --dist loadgroup` tuple, then passed after
  `SUMMON_PROCESS_TEST_COMMAND` moved to `-n 4 --dist load`. The same existing
  test now pins both unchanged live commands at one loadgroup worker.
- 2026-07-13 CI configuration: the two existing workflow contract tests failed
  on the old matrix cap and one-worker deterministic commands, then passed after
  the process job and coverage mirror moved to `-n 2 --dist load` and the matrix
  cap was removed. Per user direction, no separate regression test was added
  merely to reject the old policy; the existing command-contract assertions
  were updated in place.
- 2026-07-13 focused gates: `tests/test_release_script.py` plus
  `tests/test_github_workflows.py` passed 60 tests; docs references passed 10;
  Ruff check passed; Ruff format reported four files already formatted; and
  `git diff --check` passed.
- 2026-07-13 real pressure gates: the deterministic selector passed all 223
  items under local `-n 4 --dist load` in 43.34s. With the coverage job's
  `PYTEST_ADDOPTS='-ra -q --strict-markers -n auto --dist loadgroup'`, the
  explicit CI command reported `created: 2/2 workers`, collected 223 items, and
  passed under `-n 2 --dist load` in 98.80s.
- 2026-07-13 final review: independent Claude review found no P1 issue, hidden
  serialization, or live-lane widening. Its one P2 marker-description gap was
  accepted and fixed. Remote GitHub-hosted runners remain the acceptance
  environment for slow-runner behavior.

## Fresh-Eyes Review

The final independent review found no P1 issues, no hidden `loadgroup` use in
the isolated deterministic lane, and no widening of the live or local-LLM
lanes. Its one P2 wording issue was fixed in the marker metadata. The remaining
acceptance risk is the first run on GitHub-hosted macOS and Python-version
matrix workers; local checks prove the exact scheduler overrides, but cannot
reproduce those hosts.
