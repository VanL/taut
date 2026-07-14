# CI Speed, Determinism, and Release Evidence Plan

Status: Implemented and locally verified. Plan and implementation reviews are
dispositioned below, and the corrected requirements are promoted into the
governing specs. The worktree remains uncommitted and prepared-CI acceptance is
still required.

Plan type: Implementation with spec revision.

## Goal

Make CI faster and less flaky without reducing the test surface: collect
coverage during existing Ubuntu executions, keep expensive installed-wheel
tests on one worker and one fresh lane, isolate signal probes from xdist worker
death, keep the real local-LLM smoke strict, and let release tags consume one
canonical exact-SHA test result and its immutable artifacts instead of running
the same matrices again.

## Requested Outcomes

- No test node is rerun only to collect coverage.
- Every supported OS/Python cell still runs the full source root and Summon
  contracts. Installed-artifact coverage includes every Python version once on
  Ubuntu and every OS at least once.
- Installed-wheel tests still use real built wheels and the active matrix
  interpreter, but one worker owns the wheel build in each selected cell. CI
  runs six factor-covering cells rather than all ten OS/Python combinations.
- A reactor/SIGINT watchdog can fail only its probe child, never an xdist
  worker.
- The prepared Ollama job still performs a real model completion through the
  PTY child and a real `taut say`; prepared-CI failures never become skips or
  silent greens. Production [SUM-11] harness recovery remains intact, but the
  smoke fails if that recovery path was needed before the sentinel landed.
- Release tags wait for canonical successful Test and PG Test runs at the exact
  release SHA, then publish the distributions produced by those runs. A tag
  gate does not enqueue another copy of either test workflow.
- Artifact identity is fail-closed: workflow path, event, SHA, package,
  version, file set, and SHA-256 digests are checked before publication.

## Source Documents

- `docs/specs/02-taut-core.md` [TAUT-11], [TAUT-12.5].
- `docs/specs/04-summon.md` [SUM-12].
- `docs/implementation/05-taut-summon-architecture.md`.
- `docs/implementation/06-command-extensions.md`.
- `docs/plans/2026-07-13-bounded-summon-process-test-parallelism-plan.md`.
- `docs/plans/2026-07-10-ci-failure-remediation-plan.md`.
- The current user direction: test fully, improve speed and determinism, do not
  solve failures by extending timeouts or skipping tests, and retain a strict
  live local-LLM CI smoke.

## Spec Baseline

- Commit `e325ef6543a621716ec0958195c25fac41109188`.
- The worktree was clean at plan start.
- Governing files at that commit:
  `docs/specs/02-taut-core.md` and `docs/specs/04-summon.md`.
- Promotion baseline: strategy A applied 2026-07-13 and refreshed after final
  implementation review. Promoted worktree blob ids are
  `7332a9b0900835299685db9cbca2dbe709fe7985` for
  `docs/specs/02-taut-core.md` and
  `84051bd144e83e942ef2d82eb7986c74672a139e` for
  `docs/specs/04-summon.md`.

## Context and Key Files

- `.github/workflows/test.yml` owns ten root OS/Python cells, six isolated
  Summon process cells, the prepared local-LLM job, packaging, and a coverage
  job that currently reruns root, Summon unit, process, and placeholder live
  selectors. One invocation therefore runs the 787-node root suite eleven
  times rather than ten.
- `.github/workflows/test-pg-extension.yml` owns three PG cells but does not
  currently build a release artifact.
- `.github/workflows/release-gate*.yml` each call reusable test workflows.
  `release.py all` pushes three tags, so the same SHA currently causes four
  Test workflow calls and three PG workflow calls when the branch push is
  included.
- `tests/conftest.py::installed_command_fixture` is session-scoped, but an
  xdist worker is a pytest session. Every participating worker therefore
  builds core, fixture-plugin, and Summon wheels and creates a base venv.
- `tests/test_watcher.py` contains two three-second `pytest-timeout` markers.
  Thread-mode timeout exits the worker process. The analogous Weft SIGINT
  proof runs the real signal in an isolated child and gives the parent a
  watchdog.
- `extensions/taut_summon/tests/test_live_local_llm.py` already requires a real
  loopback completion and sentinel post when `TAUT_SUMMON_LOCAL_LLM=1`, but its
  early-exit diagnostic omits the TUI event log and the workflow readiness
  check proves only that the model is listed, not that it can complete.
- `bin/build-and-check-release-wheels.py` currently always rebuilds core and
  Summon even when the packaging job just built them. It should retain its
  build-owning default for local release use while accepting explicit fresh
  artifacts from CI.
- `bin/release.py` pushes the current branch before tags. Exact-SHA workflow
  reuse requires the branch to trigger the canonical push workflows; release
  mutation must therefore fail before preparation when the current branch is
  not `main` or `master`.

Comprehension gates:

1. Why is a coverage aggregator still allowed? It downloads and combines data;
   it executes zero tests. Coverage must come from the root, process, and real
   local-LLM jobs that already own those boundaries.
2. Why can a tag gate trust a prior run? Only a successful `push` run of the
   expected workflow file at the exact SHA, canonical branch, source
   repository, and latest completed attempt is eligible. Publication pins the
   expected non-expired distribution artifact by immutable artifact id and
   GitHub archive digest, then verifies the inner package/version/file hashes.
   A run name, `path@ref` string, cache, or mutable artifact name is not
   evidence.
3. Why is installed-wheel grouping not a skip? Dynamic collection marks every
   consumer of `installed_command_fixture`; the broad lane deselects that
   group only because a fresh serial command in a selected factor-covering cell
   owns it. The six selected cells cover all Python versions and all operating
   systems. A collection guard prevents a fixture consumer from falling out of
   the serial lane.

## Invariants and Constraints

- Preserve all [TAUT-11] and [SUM-12] real-boundary proof: real temp databases,
  real subprocesses, real PTYs, real local model endpoint, and real CLI posts.
- Do not raise an existing test, subprocess, readiness, or test-job timeout to
  mask a failure in this change. New parent watchdogs and workflow-evidence
  waits must be explicit bounded failure mechanisms, not extra execution time
  for a failing test. The existing 900-second job-level thread timeout remains
  a last-resort hang backstop; the reactor probe's parent watchdog must fire
  well inside it and turn the child hang into an ordinary assertion.
- Do not add a retry that can turn a failed model completion, signal probe,
  workflow run, artifact check, or tag check green. Bounded polling may observe
  model listing, GitHub workflow state, or artifact visibility; it must not
  rerun a failed proof. Preserve the production [SUM-11] harness retries.
- Preserve the deterministic Summon process selector and `-n 2 --dist load`
  CI topology. Coverage from that lane must use the same topology.
- Preserve one-worker external-live and local-LLM boundaries.
- Coverage collection may add instrumentation overhead to one representative
  Ubuntu cell per existing execution boundary; it must not create a second
  execution of the selected tests.
- Every non-slow installed-wheel fixture consumer is selected exactly once
  across `not slow and not installed_wheel` and
  `not slow and installed_wheel`; the selectors' union equals the prior
  `not slow` collection and their intersection is empty. A default unfiltered
  local invocation still selects each test once.
  The marker is derived from the fixture at collection time so new consumers
  cannot silently miss the lane.
- Installed-artifact CI uses the active matrix interpreter and factor-covers
  all four supported Python versions on Ubuntu plus one macOS and one Windows
  representative. Source tests still run in all ten root matrix cells.
- The release artifact must be produced at the tested SHA by the eligible
  canonical workflow attempt. A cache hit, mutable branch artifact,
  workflow-name-only match, artifact-name-only match, or locally rebuilt tag
  artifact is not acceptable release evidence.
- Tag-current checks remain immediately before publication. Exact-SHA test
  reuse does not replace the TOCTOU fence.
- Core and Summon paired compatibility still runs on freshly built explicit
  wheel paths before either distribution can be published.
- No new third-party dependency. Use the standard library and existing pinned
  GitHub actions.
- Do not alter production watcher, broker, PTY, driver, or retry behavior based
  only on these CI symptoms.

## Hidden Couplings and Failure Priorities

- `pytest-timeout --timeout-method=thread` calls `os._exit(1)` after a timeout;
  under xdist this appears as `node down`, not as an ordinary assertion.
- `xdist_group` co-locates marked tests only under `loadgroup`. The dedicated
  installed-artifact command uses `-n 0`; the group protects normal local
  `pytest` runs, while the `installed_wheel` marker partitions CI and release
  commands.
- Coverage subprocess patching relies on `COVERAGE_PROCESS_START` and distinct
  `COVERAGE_FILE` prefixes. Shard upload must include hidden parallel data
  files even after a test step fails so diagnostics are not lost.
- A matrix job cannot collect coverage from a separate process job. Root/unit,
  deterministic process, and actual local-LLM jobs each upload their own
  shard; the aggregator combines them and runs required-path checks.
- GitHub reusable workflow callers do not memoize results or share artifacts.
  Deduplication therefore happens by querying canonical exact-SHA runs and
  downloading their immutable artifacts, not by adding reusable outputs to
  three independent tag runs.
- GitHub's workflow-run API may return a workflow `path` suffixed with `@ref`,
  and a rerun keeps its run id while incrementing `run_attempt`. Resolve the
  expected workflow by file or id, then bind repository, head repository,
  canonical branch, event, SHA, conclusion, and latest attempt. Artifact names
  include the successful attempt; failed-jobs-only reruns cannot borrow a
  package artifact from an older attempt.
- A successful test run with a missing or mismatched current-attempt artifact
  is fatal after the two-minute visibility window. Seeing only an older-attempt
  artifact during that window is pollable API lag, not permission to reuse it.
  Codecov upload remains best-effort and must not affect test truth.
- The three coordinated tag gates make one repository-wide workflow-run list
  request per poll and filter the required workflow files locally. A
  rate-limit-signature 403 or 429 respects `Retry-After`/rate-limit reset within
  the overall observation bound; 401 and non-rate-limit 403 remain fatal.
- Tag workflows peel lightweight or annotated refs to a commit before querying
  evidence. Bundle verification binds package, version, and tag family so the
  wrong tag namespace cannot publish otherwise valid bytes.
- The live model smoke owns transport and integration, not model instruction
  following. Any valid completion body is enough because the deterministic
  child, not model text, posts the sentinel. Endpoint errors, malformed JSON,
  PTY failures, or `taut say` failures remain fatal.

## Rollout and Rollback

This change has no data migration and no one-way product door. Land the test
topology, artifact producer, exact-SHA gate, and consumer together so a release
gate never expects an artifact that the canonical workflow does not produce.
The local release helper remains a pre-push proof and keeps its default fresh
paired build. Rollback is source-only but must be atomic by slice:

- Coverage rollback restores the test-running coverage job and removes shard
  conditionals together; never leave partial coverage that silently omits the
  process or local-LLM lane.
- Installed-wheel rollback restores the single broad command and collection
  behavior together; do not retain deselection without the serial owner.
- Release rollback restores tag-owned test workflow calls and publication
  builds together; do not reuse a prior run without verified artifacts.
- Signal-probe rollback restores the original in-process test only if the
  worker-killing timeout marker is not restored.

Observe CI wall time, exact test counts, coverage required-path checks, xdist
worker deaths, local-LLM event logs, and release-gate job counts. If artifact
promotion fails, no GitHub Release should exist. A failed canonical workflow is
not eligible. A missing or expired artifact requires rerunning all jobs in the
canonical push workflow while the SHA remains eligible, or creating and
testing a new SHA before retagging; a tag-only or failed-jobs-only rerun cannot
regenerate acceptable evidence. Rerunning a tag-gate workflow is permitted when
the observer itself timed out or hit a transient API limit: the gate runs no
tests, changes no evidence, and merely re-observes the canonical workflow. It
must still reject a failed test conclusion or an ineligible artifact attempt.

## Proposed Spec Delta

Promotion strategy: A, in-file requirement text before implementation-link
claims. Applied after both independent reviews and before code or workflow
changes.

### `docs/specs/02-taut-core.md` [TAUT-11]

Append to the verification expectations:

> Installed-wheel tests remain real cross-platform installed-artifact proofs,
> but wheel construction has one owner per selected cell and uses that cell's
> active Python interpreter. Every consumer of the installed-wheel fixture is
> collection-marked into one group; normal xdist runs co-locate it, while CI
> factor-covers every Python on Ubuntu and every OS at least once in fresh
> serial invocations after the broad root lane deselects the group.
>
> No per-test timeout marker may terminate an xdist worker for a reactor or
> signal test. Real process-signal semantics run in an isolated probe child;
> the parent pytest worker owns a bounded watchdog, well inside the retained
> job-level hang backstop, and asserts the child's structured final state. This
> isolation is not permission to retry or ignore probe failure.

### `docs/specs/02-taut-core.md` [TAUT-12.5] helper obligations

Append after the clean-commit/fresh-fence obligations:

> A publishing release runs from `main` or `master`, the branches that produce
> canonical push-triggered CI evidence. The helper rejects any other branch
> before release metadata mutation. Dry-run and checks-only remain usable from
> other branches because they do not publish.

### `docs/specs/02-taut-core.md` [TAUT-12.5] CI and coverage obligation

Replace the sentence that requires the coverage invocation to rerun the
deterministic selector, and append the coverage ownership rule:

> The representative Ubuntu root/unit cell and Ubuntu deterministic-process
> cell collect and upload coverage while running their existing selectors; the
> prepared local-LLM job does the same for the real smoke. The process shard
> retains `-n 2 --dist load`. A final coverage aggregation job downloads and
> combines shards, enforces required paths, and uploads the report, but runs no
> tests. Placeholder live files that skip without prepared credentials or a
> model are not invoked merely to inflate coverage.

### `docs/specs/02-taut-core.md` [TAUT-12.5] workflow obligations

Replace the three bullets that say each release gate calls reusable test
workflows with:

> - Canonical `push` runs of `.github/workflows/test.yml` and
>   `.github/workflows/test-pg-extension.yml` are the test evidence for a
>   release SHA. On canonical `main`/`master` pushes, the root workflow performs
>   the release-grade paired core/Summon wheel check against the distributions
>   it built, builds the PG distribution, and runs a fresh-environment PG wheel
>   smoke with the paired core wheel before uploading separate core, Summon,
>   and PG artifact bundles. The PG workflow remains the real database test
>   evidence and need not duplicate package construction. Pull-request and
>   manual runs retain their ordinary packaging smoke but do not produce
>   release evidence. Each release bundle carries the exact commit, package
>   name/version, file allowlist, and SHA-256 digests, and its name identifies
>   the workflow attempt that produced it.
> - Each tag gate waits for the required canonical workflow file(s) to complete
>   successfully for the exact commit peeled from the tag, canonical branch,
>   source/head
>   repository, latest attempt, and `push` event. It resolves the workflow by
>   file or id and normalizes API `path@ref` responses; display-name or path
>   string equality alone is insufficient. Core requires root plus PG evidence;
>   PG requires root plus PG evidence; Summon requires root evidence. Tag gates
>   do not invoke the test workflows.
> - `.github/workflows/release.yml` downloads the one expected, non-expired
>   package artifact for the eligible workflow attempt by immutable artifact id,
>   with repository, run id, and GitHub archive SHA-256 digest verified from
>   REST metadata. It then verifies the embedded commit/package/version/file
>   hashes against the checked-out peeled tag commit, binds the package/version
>   to its exact release-tag family, rechecks that the remote tag is current,
>   and publishes those exact files. It does not rebuild distributions and is
>   the only artifact publisher. It must not contain PyPI upload or Trusted
>   Publishing steps.

Replace the conditional paired-verification input obligation with:

> The canonical-branch root Test workflow runs release-grade paired
> verification once on its freshly built explicit core and Summon wheel paths,
> and proves the PG wheel installs, imports `taut_pg`, and is discoverable with
> the paired core wheel in a fresh environment. Pull-request and manual
> workflow calls retain ordinary packaging smoke. The local release helper
> retains its build-owning paired check before remote mutation. Tag gates reuse
> the successful canonical Test run and its verified artifacts; they do not
> repeat paired or installed-wheel verification.

### `docs/specs/04-summon.md` [SUM-12]

Replace the local-LLM bullet with:

> - A CI-safe local LLM lane uses a real PTY child and a loopback
>   OpenAI-compatible model endpoint. Prepared CI first proves readiness with a
>   bounded model-list wait followed by exactly one real chat completion, not
>   completion retries. The child must receive the summon orientation,
>   complete one request through the counting
>   proxy, and post a sentinel through real `taut say`. The model's prose does
>   not control the sentinel post; this is a deterministic transport and
>   PTY/mouth proof, not an instruction-following benchmark. With
>   `TAUT_SUMMON_LOCAL_LLM=1`, missing models, endpoint/completion errors,
>   malformed responses, failed sentinel posts, and any harness exit/restart
>   observed before success are hard failures and never skips or silent greens.
>   Production [SUM-11] crash recovery remains enabled; the smoke inspects its
>   lifecycle evidence and fails if recovery was needed. Failure evidence
>   includes driver stderr, TUI events, request count, and provider/container
>   diagnostics. The lane prewires the synthetic PTY member as already
>   onboarded and does not replace the real-harness, local-only smoke matrix.

## Tasks

1. Independently review and promote this spec delta.
   - Completed 2026-07-13 with the review dispositions below and the promoted
     blob ids recorded in Spec Baseline.
   - Reviewer reads this plan, all proposed text, current specs, workflows,
     release helper, fixture ownership, and live-LLM test.
   - Apply accepted changes to both specs, add Related Plans backlinks, and
     record the promotion worktree identifier here.
   - Stop if artifact promotion cannot preserve exact-SHA and tag-current
     evidence, or if a proposed split drops a test selector.

2. Red-green installed-wheel ownership and fresh-lane selection.
   - Update collection/config tests first to require an `installed_wheel`
     marker on every `installed_command_fixture` consumer and one
     `xdist_group("installed-wheel")` owner.
   - Add the collection hook and marker registration.
   - Change CI and `bin/release.py` root commands to run broad
     `not slow and not installed_wheel` then fresh
     `not slow and installed_wheel -n 0`; add exact command guards and prove
     that the two collections are disjoint and their union equals the current
     `not slow` collection.
   - Prove one fixture root/build under a multi-worker default run.
   - Use `sys.executable` inside the wheel environment. In CI, run the serial
     installed selector for Python 3.11-3.14 on Ubuntu, macOS 3.13, and Windows
     3.11, preserving every Python and OS factor without the ten-cell product.

3. Red-green signal-probe isolation.
   - Change the watcher regression to launch a dedicated helper module and
     assert structured final state; observe the missing-helper red result.
   - Port only the necessary real `BaseReactor` scenario into
     `tests/helpers/base_reactor_sigint_probe.py`.
   - Remove both three-second worker-killing markers. Keep deterministic
     synchronous bounds in the callback test by making the fake raise on a
     third wait call; no timeout increase.
   - Prove the parent reports a killed/hung child as an ordinary test failure
     under a parent-owned watchdog, xdist retains its worker, and a following
     same-worker sentinel test still runs.

4. Red-green strict local-LLM readiness and diagnostics.
   - Add firing tests for HTTP and URL failure, timeout, invalid JSON, wrong
     top-level type, non-list and empty choices, missing message/content,
     driver early exit, and sentinel timeout. Each child failure is concise,
     nonzero, and traceback free, while the parent diagnostic includes all
     retained evidence.
   - Keep the bounded model-list readiness wait, then make exactly one real
     chat-completion request with the configured model. Do not poll completion.
   - Include TUI events and proxy request count in every early driver-exit
     failure. Record all URL/HTTP/JSON errors in the child before nonzero exit.
   - Preserve production [SUM-11] harness recovery, but make the smoke fail if
     its lifecycle log shows any harness exit/resume before the sentinel.
   - Run non-live unit tests locally; the prepared CI job remains the real
     acceptance environment.

5. Red-green release artifact provenance and explicit-wheel reuse.
   - Add standard-library tests for manifest creation/verification: exact SHA,
     normalized package name, manifest version, expected version, exact file
     allowlist, digest mismatch, extra file, and missing file all fire.
   - Implement one small `bin/release-artifact.py` producer/verifier.
   - Extend `build-and-check-release-wheels.py` to accept both explicit wheel
     paths as a pair while retaining build-owning default behavior. Test that
     explicit mode performs zero current core/Summon wrapper `uv build` calls
     and still runs all metadata, resolution, and wheel-matrix checks. The four
     deliberate historical compatibility-wheel builds remain real.

6. Move coverage and artifact production into canonical workflows.
   - Update workflow tests first. They must assert that only representative
     Ubuntu cells wrap existing commands with coverage; root/unit, process, and
     real local-LLM shards upload; aggregation executes no pytest command.
   - On canonical branch pushes, make root packaging build core and Summon once
     into clean explicit dirs, run paired verification on those wheels, build
     PG once, and smoke the PG wheel with that core wheel in a fresh venv by
     importing `taut_pg` and confirming plugin discovery. Create
     attempt-qualified manifests and upload three separate artifacts from this
     one producer. The PG workflow keeps real database coverage without a
     second package build. Pull-request/manual runs keep ordinary packaging
     smoke and do not upload release evidence.
   - Keep all source matrix selectors unchanged. Reduce installed-artifact
     execution from ten cells to the six-cell Python/OS factor cover, and make
     dedicated live commands select only their live markers.

7. Red-green exact-SHA canonical workflow gating and artifact publication.
   - Add unit tests for workflow-run and artifact selection before the gate
     script: workflow file/id and normalized `path@ref`, `push` event, head SHA,
     canonical branch, source/head repository, latest run attempt, completion,
     success, wrong branch/repository, duplicate artifact, expired artifact,
     wrong attempt, digest mismatch, timeout, missing, and failed states.
   - Implement `bin/require-green-workflows.py` with standard-library HTTP and
     `GITHUB_OUTPUT` export of workflow run id/attempt plus immutable artifact
     id/digest. Include it and `bin/release-artifact.py` in ruff and mypy. Add
     adversarial CLI firing tests for absent env, 401, non-rate-limit 403,
     rate-limited 403, 429, 5xx exhaustion, malformed JSON, and concise nonzero
     failure without traceback.
   - Use one repository-wide runs-list request per 60-second poll, filtering
     both workflow files locally. Bound observation at 95 minutes: the root
     Test DAG has a 45-minute critical path (a 30-minute prerequisite followed
     by the dependent 15-minute coverage job), followed by 45 minutes of
     explicit runner-queue margin and five minutes of API/listing margin. Give
     the enclosing gate job 110 minutes for checkout/setup, observation, and
     overhead. A
     completed non-success conclusion, 401, non-rate-limit 403, or malformed
     response fails immediately. Rate-limited 403/429 respects
     `Retry-After`/reset headers; transient 5xx and not-yet-listed runs remain
     bounded by the same total. Give artifact visibility at most two minutes
     after a green run.
   - Document that rerunning a tag-gate observer after its own timeout or API
     limit is allowed because it reruns no proof and cannot change test truth;
     canonical workflow failure is fatal. Stale-only artifact listings are
     pollable for two minutes after the eligible run, then fatal.
   - Replace release-gate reusable test calls with the gate script and pass the
     eligible run id/attempt and artifact id/digest to `release.yml`.
   - Peel the tag ref to its commit before evidence lookup so lightweight and
     annotated tags share one exact-SHA path. Bind the package/version to the
     required tag family during inner bundle verification.
   - Change `release.yml` from builder to verified artifact consumer. Retain
     checkout, SHA verification, pre-publish tag-current check, and GitHub-only
     publication.
   - Put one shared release-helper guard before every preparation mutation. It
     permits publishing `all`, `core`, `pg`, and `summon` only from `main` or
     `master`, rejects topic and detached HEAD, and leaves dry-run/checks-only
     usable and non-mutating. Tests must prove rejection occurs before any
     preparation command.

8. Reconcile docs, verify, and independently review each meaningful slice.
   - Update implementation docs, workflow/release ownership notes, plan index,
     and durable lessons.
   - Run focused tests after each slice, then full root/Summon/PG/static gates.
   - Run an independent final review over specs, plan, changed files, and
     current evidence. Disposition every finding here.

## Testing Plan

Tests remain real at the important seams. The broker, SQLite files, CLI,
watcher, signals, xdist, PTY child, Ollama completion, wheel builds, and
installed artifacts are not mocked. Narrow unit tests may fake GitHub API JSON,
HTTP failures, clocks, and subprocess command recording because those are the
external orchestration boundaries. Configuration changes use red-green exact
workflow/release tests plus collection-count checks. Artifact provenance uses
both focused adversarial unit cases and one real built-wheel end-to-end check.

The key anti-regression counts are:

- root collection remains 787 node ids at the baseline (unless tests added by
  this plan increase it); node ids stay unique;
- `not slow and not installed_wheel` plus
  `not slow and installed_wheel` partition the prior `not slow` collection
  exactly, with an empty intersection;
- Summon unit/process/live selectors are disjoint and complete for the dedicated
  live files; the live lanes select only their required markers;
- a canonical Test workflow has ten source root cells, six installed-artifact
  factor-cover cells, six process cells, one real local-LLM cell, and zero
  test-running coverage-only cells;
- coordinated release tags enqueue zero additional Test or PG Test workflows.

## Verification and Gates

Per-slice commands will be recorded with observed results. Final minimum:

```bash
uv run --extra dev pytest tests/test_github_workflows.py tests/test_release_script.py -n 0 -q
uv run --extra dev pytest tests/test_release_artifact.py tests/test_require_green_workflows.py -n 0 -q
uv run --extra dev pytest tests/test_watcher.py -k 'rebinds_callback_topology or defers_reentrant_sigint' -n 2 --dist load -q
uv run --extra dev pytest tests/test_watcher.py -k 'sigint_probe_watchdog' -n 2 --dist loadgroup -q
uv run --extra dev pytest --collect-only -q
uv run --extra dev pytest -m 'not slow' --collect-only -q
uv run --extra dev pytest -m 'not slow and not installed_wheel' --collect-only -q
uv run --extra dev pytest -m 'not slow and installed_wheel' --collect-only -q
uv run --extra dev pytest -m 'not slow and installed_wheel' -n 0 -q
uv run --project extensions/taut_summon pytest extensions/taut_summon/tests/test_live_local_llm.py -m 'not requires_local_llm' -n 0 -q
uv run --extra dev pytest
uv run --project extensions/taut_summon pytest extensions/taut_summon/tests -m 'not xdist_group' -q
uv run --project extensions/taut_summon pytest extensions/taut_summon/tests -m 'xdist_group and not requires_live_harness and not requires_local_llm' -n 2 --dist load -q
uv run --extra dev ./bin/pytest-pg --fast
uv run --extra dev ruff check taut tests bin extensions/taut_summon/taut_summon extensions/taut_summon/tests
uv run --extra dev ruff format --check taut tests bin extensions/taut_summon/taut_summon extensions/taut_summon/tests
uv run --extra dev mypy taut tests bin/release.py bin/release-artifact.py bin/require-green-workflows.py --config-file pyproject.toml
uv run --extra dev mypy extensions/taut_summon/taut_summon extensions/taut_summon/tests --config-file pyproject.toml
uv run --extra dev pytest tests/test_docs_references.py -n 0 -q
git diff --check
```

Observed locally on macOS/Python 3.14.4 on 2026-07-13:

- The full root suite passed after final review fixes: 883 tests in 18.10
  seconds. Collection remained unique and the 883 non-slow nodes partitioned
  exactly into 857 broad
  plus 26 installed-wheel nodes. The 26 real installed-artifact cases passed
  once under `-n 0`.
- The isolated signal watchdog and its following same-worker sentinel both ran
  on `gw0` under `-n 2 --dist loadgroup` and passed after the hung child was
  killed without losing the worker.
- Summon selected 245 unit nodes, 224 deterministic process nodes, and 18
  non-live local-LLM diagnostic nodes; all three fresh invocations passed. The
  prepared Ollama job remains the real local-LLM acceptance environment.
- Docker Postgres passed 140 shared contract tests and 13 PG-only tests.
- The 171 workflow/release/evidence focused tests passed. Ruff check and format,
  root and Summon mypy, documentation references, YAML parsing, and
  `git diff --check` passed.
- Real package evidence passed separately: core/Summon/PG wheels and sdists
  built; one manifest-bound bundle verified and copied exact publish bytes; a
  fresh venv imported `taut_pg` and discovered the Postgres plugin; explicit
  current core/Summon wheels still ran the four historical builds and all six
  installed compatibility cases.

Post-rollout success means lower Test workflow wall time and compute, no
coverage-only test run, no `node down` from the two reactor tests, strict
local-LLM failures with complete event evidence, and one Test plus one PG Test
run per release SHA regardless of tag count. Do not use a failed-job rerun as
evidence that the original failure was harmless.

## Independent Review Loop

- Plan review: independent read-only reviewer, preferably Claude, reviews the
  proposed spec delta and current cross-repo precedents before promotion.
- Slice reviews: review after coverage/wheel/signal changes and after release
  evidence/artifact changes.
- Final review: fresh reviewer reads both promoted specs, this plan,
  implementation docs, all touched files, and current verification output.
- Review stance: find dropped selectors, green-by-skip/retry behavior, weak
  workflow identity, mutable artifact trust, TOCTOU gaps, xdist worker-kill
  paths, and release cases that can publish untested bytes.

## Review Findings and Dispositions

First independent review (Sagan, repository subagent), 2026-07-13:

| Priority | Finding | Disposition |
|----------|---------|-------------|
| P1 | A no-retry live-smoke rule conflicted with [SUM-11] production harness crash recovery. | Accepted. Production retries remain. Readiness performs one completion after model-list polling, and the smoke fails if lifecycle evidence shows any harness exit/resume before success. |
| P1 | Exact-SHA workflow selection did not bind canonical branch/repository/latest attempt or pin immutable artifact identity. | Accepted. The gate resolves workflow file/id, normalizes `path@ref`, binds source/head repository, branch, event, SHA, conclusion, and latest attempt, then exports verified artifact id and archive digest. Wrong-identity, duplicate, expired, and rerun cases get firing tests. |
| P1 | Bare installed-wheel selectors would fail to preserve the current release/CI selector contract if slow tests are added. | Accepted. Both new selectors compose defensively with `not slow`; collection tests prove their disjoint union equals the old `not slow` set. Today no root test is slow-marked, so `not slow` equals the full baseline collection. |
| P1 | “Zero `uv build` calls” would wrongly suppress four deliberate historical compatibility builds. | Accepted. Only current core/Summon wrapper builds are forbidden in explicit mode; historical builds remain real. |
| P2 | LLM malformed-response and error classes were not enumerable. | Accepted. URL, timeout, invalid JSON, wrong top type, empty choices, missing message/content, early exit, and sentinel timeout each get a concise nonzero firing test with retained diagnostics. |
| P2 | A script under `.github/scripts` would fall outside current mypy ownership and its failure contract was vague. | Accepted. Both new Python CLIs live in `bin/`, enter ruff/mypy gates, and get env/auth/5xx/malformed-response/no-traceback probes. |
| P2 | Release-grade paired artifact production on every PR/manual run would add cost without producing eligible evidence. | Accepted. Only canonical branch pushes create release evidence; PR/manual runs retain ordinary packaging smoke. |
| P2 | Signal isolation lacked deterministic callback and post-crash worker-survival proofs. | Accepted. The fake raises on a third wait; the parent watchdog converts a killed/hung probe to ordinary failure, followed by a same-worker sentinel. |
| P2 | The release branch guard covered no explicit command matrix or mutation boundary. | Accepted. One pre-mutation guard covers `all`, `core`, `pg`, and `summon`; topic/detached rejects and dry-run/checks-only allowances get firing tests. |
| P2 | Workflow wait, API error, artifact lag, and expired-evidence recovery policy were unspecified. | Accepted, then superseded by the implementation critical-path review below. The current contract is a 95-minute observer, one repository-wide query per 60-second poll, at most two minutes of artifact visibility within that same total, fail-fast permanent errors, bounded transient errors, and rerun-all/new-SHA recovery. |

Different-family read-only review (Claude), 2026-07-13:

| Priority | Finding | Disposition |
|----------|---------|-------------|
| P1 | Three coordinated gates polling every 15 seconds could consume the shared API budget, then treat rate-limit 403 as permanent; 429 was absent. | Accepted. Each gate makes one repository-runs query per 60-second poll and filters workflow paths locally. Rate-limit 403/429 respects reset headers within the same bound; 401 and non-rate-limit 403 fail fast. All cases get firing tests. |
| P2 | The proposed watchdog invariant contradicted the retained global 900-second thread timeout. | Accepted. The spec now prohibits worker-killing per-test markers for these probes, puts the child watchdog well inside the retained job-level last-resort backstop, and requires ordinary assertion failure plus worker survival. |
| P2 | PG provenance alone did not prove that the published PG wheel installs or exposes its plugin. | Accepted with a less duplicative design. The canonical root packaging owner builds all three packages once, then installs PG with the exact core wheel in a fresh venv, imports `taut_pg`, and checks plugin discovery. The PG workflow remains separate database evidence and does not rebuild packages. |
| P2 | A bare 60-minute gate wait had little queue margin over the PG job's 40-minute ceiling, and rerunning an observer was ambiguous. | Accepted, then superseded by the implementation critical-path review below. Rerunning only the no-test gate observer is explicitly allowed; it cannot change test truth. |
| P3 | The first review's slow-test wording implied a currently nonempty slow set. | Accepted. The plan now says `not slow` composition is defensive; today it equals the full root collection. |

Claude's conditional conclusion was that dispositioning its first four findings
makes the plan safe to promote. All four are now incorporated in the proposed
spec text, tasks, invariants, rollout, and firing-test matrix.

Implementation final review (Sagan, repository subagent), 2026-07-13:

| Priority | Finding | Disposition |
|----------|---------|-------------|
| P1 | A valid bundle could be published under a tag whose family or version did not match the package. | Accepted. `release-artifact.py verify` now requires the tag and binds `taut` to `vX.Y.Z`, PG to `taut_pg/vX.Y.Z`, and Summon to `taut_summon/vX.Y.Z`; malformed, wrong-family, and wrong-version tags have firing tests. |
| P2 | The installed-wheel lane repeated its three-wheel environment in all ten root cells while hard-coding a Python 3.11 child. | Accepted with stronger factor coverage. The child uses `sys.executable`; Ubuntu covers Python 3.11-3.14, with macOS 3.13 and Windows 3.11 covering the remaining OS factors. This reduces ten lanes to six without dropping a Python or OS boundary. |
| P2 | Dedicated live commands selected whole files, rerunning 10 external-harness and 16 local-LLM diagnostics already owned by the unit lane. | Accepted. The commands now select only `requires_live_harness` or `requires_local_llm`. A real collection proof asserts disjoint, complete unit/live ownership; the local diagnostic count is now 18 after adding two missing error cases. |
| P2 | Seeing only a stale-attempt artifact failed immediately, bypassing the intended visibility allowance after rerun-all. | Accepted. Stale-only listings raise the pollable absence class for two minutes; the current attempt succeeds when it appears, while stale-only evidence times out fatally and is never reused. |
| P2 | The 90-minute observer treated the Test workflow as a 40-minute flat job, but coverage is a dependent 15-minute job after 30-minute prerequisites. | Accepted. The observer is 95 minutes: 45-minute DAG critical path, 45-minute queue margin, and five-minute API margin. Gate jobs are 110 minutes to include checkout, setup, tag peeling, and overhead. |

Different-family implementation final review (Claude), 2026-07-13:

| Priority | Finding | Disposition |
|----------|---------|-------------|
| P1 | Local release prechecks omitted the two new gate scripts from mypy even though CI checks them. | Accepted. `ROOT_MYPY_PATHS` and its exact command test include `bin/release-artifact.py` and `bin/require-green-workflows.py`. |
| P2 | The isolated real-SIGINT regression could silently skip on an `unsupported` child status. | Accepted. The unsupported branch and parent skip hatch are removed; any probe defect is a hard failure. |
| P2 | Structured local-LLM `http_error` and `missing_choices` results lacked firing tests. | Accepted. A real HTTP 500 stub and a non-list `choices` payload now exercise both branches. |
| P2 | Gate lookup used the raw tag-event SHA, which can be an annotated tag object rather than its commit. | Accepted. Every gate peels `GITHUB_REF^{commit}`, validates the 40-character commit, uses it for evidence lookup, and passes it through checkout and bundle verification. |
| P2 | Review dispositions and promoted text omitted current tag binding and retained stale observer numbers. | Accepted. The spec and this plan now state tag-family/version binding and mark the earlier 90-minute reasoning as superseded. |
| P2 | Failure-aware step conditions could create misleading installed-lane or missing-coverage follow-on failures after setup failed. | Accepted. Installed lanes require successful dependency installation, while coverage uploads run after a started coverage step even on test failure and skip when coverage never started. |

Claude's statement that stale-attempt artifacts were immediately fatal described
an earlier worktree state. The Sagan finding and current firing tests establish
the final policy: stale-only listings are pollable for two minutes and fatal
afterward.

Final follow-up review (Sagan, repository subagent), 2026-07-13:

| Priority | Finding | Disposition |
|----------|---------|-------------|
| P2 | The isolated SIGINT child watchdog was widened from the removed three-second marker to ten seconds, contrary to the no-timeout-extension rule. | Accepted. The parent-owned watchdog is three seconds again; both the hung-child failure and same-worker sentinel pin that budget and pass under xdist. |
| P3 | One exhausted-total-window diagnostic still said 90 minutes after behavior moved to 95. | Accepted. The diagnostic says 95 minutes, and a CLI firing test proves the workflow phase cannot consume the artifact phase's total budget. |

The follow-up reviewer reran the signal, workflow-evidence, release, selector,
and installed-wheel checks after these fixes and reported no remaining
actionable issues.

## Deviation Log

| Spec ref | Planned behavior | Actual behavior | Rationale | Spec proposal |
|----------|------------------|-----------------|-----------|---------------|
| [TAUT-11] | Run the serial installed selector in every root matrix cell. | Run it in six factor-covering cells using the active matrix interpreter. | Covers every supported Python and OS while removing four redundant three-wheel environments. | Promoted into [TAUT-11] and implementation docs. |
| [TAUT-12.5] | Observe for 90 minutes using a 40-minute flat-job estimate. | Observe for 95 minutes inside a 110-minute gate job. | The actual Test DAG has a 45-minute critical path because coverage depends on the 30-minute test jobs. | Promoted into [TAUT-12.5]. |

## Out of Scope

- Production watcher or Summon behavior changes without a reproduced product
  defect.
- Reducing supported OS/Python matrices or replacing real tests with mocks.
- Removing the live local-LLM CI smoke or treating it as advisory.
- Increasing timeout budgets, adding flaky-test reruns, or quarantining tests.
- PyPI publication or Trusted Publishing.
- Account-wide GitHub Actions quota/concurrency policy.
- Retrofitting sibling repositories.

## Fresh-Eyes Review

Two fresh-eyes reviews found and corrected the identity, selector,
recovery-contract, historical-build, rate-limit, watchdog-scope, PG-wheel, and
observer-wait holes recorded above. Before promotion, recheck that the artifact
producer and consumer land atomically, the exact-SHA query cannot select a
manual or reusable call by display name or `path@ref`, the installed marker is
assigned from fixture ownership before `-m` deselection, and every current
coverage selector has an existing execution owner.
