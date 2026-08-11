# CI Factor Coverage and Release Ordering Plan

Date: 2026-08-11

Class: 4. This changes the canonical OS/Python test topology and the ordering of
remote release actions. The work crosses subprocess, hosted-runner, exact-SHA
evidence, tag, and publication boundaries. Hardening is required.

Plan type: implementation with spec revision.

## Goal

Make canonical CI finish reliably without weakening test coverage, and prevent
release evidence observers from starving the workflows that produce their
evidence. Replace the redundant Windows Cartesian source-suite runs with a
complete, disjoint four-version factor partition plus one small public CLI smoke
on every version. Push the canonical branch and wait locally for exact-SHA root,
PostgreSQL, and MCP evidence before creating or replacing remote release tags.

## Incident Evidence

- Release candidate `09f9fd878c6b0a5b848728f43700939f32733cfd`, Test run
  `31520887779`, failed Ubuntu Python 3.11 because a test stored `id(queue)`
  after the queue lifetime. CPython reused the address. The weak-reference fix
  passed 25 focused repetitions, the full Summon unit suite, and replacement
  Ubuntu Python 3.11 job `93880959305` at candidate
  `76f5d27626f0098d072bc40a62872f5eb59db84a`.
- On the replacement SHA, the four release-evidence jobs occupied all four
  available hosted runners while root and MCP producer workflows remained
  queued. Cancelling only the four observer attempts allowed both producers to
  start. The observer design can therefore deadlock under the repository's
  observed runner quota.
- Replacement Test run `31521973543` then failed Windows Python 3.14 job
  `93880959403`. A CLI subprocess exceeded its unchanged 20-second command
  watchdog, unrelated client tests took 50 to 96 seconds, and the workflow step
  reached its unchanged 20-minute cap after only 35% of the 1,818-item source
  selection. The other 19 root jobs, PostgreSQL run `31521973490`, MCP run
  `31521973587`, the local strict harness, and the local LLM smoke passed.
- A prior green Windows matrix repeated the same complete source selection four
  times and took 14 to 18.5 minutes per cell. The narrow margin and duplicated
  work make host-load variance release-blocking.

## Source Documents

- `docs/specs/02-taut-core.md` [TAUT-12.5].
- `docs/agent-context/runbooks/testing-patterns.md`, especially the xdist and
  subprocess-watchdog rules.
- `docs/agent-context/runbooks/hardening-plans.md`.
- `docs/plans/2026-07-13-ci-speed-determinism-release-evidence-plan.md`.
- `docs/plans/2026-08-10-test-quality-remediation-plan.md`, especially the
  hosted coverage and Windows evidence.

## Spec Baseline

- `76f5d27626f0098d072bc40a62872f5eb59db84a` for
  `docs/specs/02-taut-core.md` [TAUT-12.5].

Promotion baseline: `76f5d27626f0098d072bc40a62872f5eb59db84a` plus the
2026-08-11 worktree diff in `docs/specs/02-taut-core.md` replacing Cartesian
Windows source repetition and inserting producer-first release ordering.

## Context and Key Files

- `.github/workflows/test.yml` owns the canonical root OS/Python matrix. It
  currently runs the full 1,818-item source selection in every cell. The
  representative Ubuntu 3.13 cell runs that selection serially under coverage;
  other cells inherit `-n auto --dist loadgroup` and Windows creates two workers.
- `tests/conftest.py` already collection-marks installed-wheel consumers into
  one xdist group. It is the existing collection owner and is the narrow place
  to add an opt-in source-factor selector without a dependency or mirror list.
  xdist 3.8 computes an effective loadgroup identity from every inherited and
  direct `xdist_group` marker, accepting positional and `name=` values, then
  stringifying, deduplicating, sorting, and joining them. Sharding must use that
  complete identity after dynamic markers are installed, not
  `get_closest_marker()` or one marker argument.
- `tests/test_github_workflows.py` parses workflow roles and already runs real
  collection probes. It owns exact workflow topology and set-partition proof.
- `bin/release.py::_run_batch_release` and `_run_single_release` currently
  prepare tags (including leased remote-tag deletion for `--retag`), push the
  canonical branch, and then push tags without waiting for producer CI.
- `bin/require-green-workflows.py` already owns exact-SHA canonical workflow
  selection, repository/branch/event checks, polling, rate-limit handling, and
  fail-closed conclusions. Extend that owner for a workflow-only local wait;
  do not clone its selection logic in `release.py`.
- `tests/test_release_script.py`, `tests/test_require_green_workflows.py`, and
  `tests/test_github_workflows.py` own release order, observer behavior, and
  workflow contract tests.
- `docs/implementation/04-taut-architecture.md` describes release flow and
  exact-artifact ownership. `docs/implementation/02-repository-map.md` assigns
  release/workflow file ownership. Both need the new producer-first boundary;
  `docs/lessons.md` needs the runner-consuming observer deadlock and factor-
  coverage lesson.

Comprehension gates before editing:

1. Why must the shard key use xdist's complete effective group identity when
   any `xdist_group` marker is present? Expected answer: hashing raw node IDs or
   only the closest marker could split tests whose correctness depends on
   co-location; the sorted union of every inherited/direct positional or
   keyword group value is the scheduling ownership boundary.
2. Why must remote tags remain untouched until the local exact-SHA wait passes?
   Expected answer: tag creation starts runner-consuming publication observers,
   and leased retag preparation currently deletes the old remote tag. Both are
   externally visible actions that must follow producer success.
3. Why is a failed canonical workflow fatal rather than retryable inside the
   release helper? Expected answer: a retry would replace failure evidence and
   could publish from an uncorrected SHA. Recovery requires a corrected commit
   and a new normal helper invocation.

Implementation records the answers in the execution log before code changes.

## Invariants and Constraints

- No test, supported OS, supported Python version, extension suite, strict
  harness, local LLM smoke, coverage requirement, artifact check, or quality
  gate is skipped.
- The Windows factor union equals the complete source selection exactly. Shards
  are pairwise disjoint and nonempty. A deliberately small compatibility smoke
  is the only intentional duplicate and runs on every Windows Python version.
- Static or dynamic `xdist_group` members remain in one factor shard. The shard
  key matches xdist's complete effective group identity: all inherited and
  direct positional or `name=` values are stringified, deduplicated, sorted,
  and joined, with explicit domain separation from ungrouped node IDs. Shard
  selection runs after every dynamic group marker is installed. Installed-wheel
  tests retain their separate serial owner and existing factor matrix.
- Sharding is opt-in. Local default pytest, release prechecks, Ubuntu, macOS,
  PostgreSQL, MCP, and Summon selectors retain their current semantics.
- Do not increase the 20-second CLI watchdog, the 20-minute source-step limit,
  the 30-minute matrix-job limit, or any product retry/lock timeout.
- Use real pytest collection and the real workflow parser in acceptance tests.
  Do not mock collection, GitHub workflow documents, git command order, or the
  exact-SHA observer. API payload fakes remain acceptable in the observer's unit
  tests, where network transport is not the contract.
- The branch push is allowed before canonical evidence because it creates that
  evidence. Remote tag creation, replacement, deletion, and publication remain
  forbidden until all three exact-SHA workflows pass.
- Obtain release-observer credentials before the branch push so missing local
  auth cannot leave a pushed commit with no observer. A supplied
  `GITHUB_TOKEN` takes precedence and avoids `gh`; otherwise capture
  `gh auth token`. Never put the token in argv, output, or a persistent file.
- After the local wait, rerun repository settings and the full fresh release
  fence before touching tags:
  immutable Releases remain enabled; exact `pypi` tag policies remain present;
  branch and HEAD still identify the prepared commit, the tree is clean, the
  version remains absent from GitHub Releases and PyPI, and local/remote tag
  state still matches the leased plan.
- `--skip-checks` remains a human override for local prechecks only. It does not
  bypass canonical CI evidence. Dry-run must print the new order without API
  polling or mutation. Checks-only remains remote-free.
- Authentication comes from `GITHUB_TOKEN` when supplied, otherwise from a
  captured `gh auth token`. Missing `gh`, command failure, or blank output is
  fatal before branch push. Pass the secret only in the observer child's
  environment and scrub it from diagnostics.
- Existing tag-gate observers stay in place as defense in depth and immutable
  artifact selectors. The local wait does not produce publication inputs.
- A branch-push failure starts no observer and performs no tag action. A
  successful wait followed by settings, publication, local-tag, remote-tag, or
  lease drift is fatal before tag mutation.
- Batch tag pushes remain non-atomic. If a later tag push fails, the existing
  unpublished leased recovery applies to tags not yet published; never imply
  that coordinated publication is one atomic remote action.
- No new dependency, product-code change, persistence change, or public CLI
  change is in scope.

## Rollout and Rollback

Roll out in one commit before retrying 0.8.5. The helper first pushes the new
commit, waits for canonical producer evidence, re-fences, then retags. If the
producer workflows fail, the helper stops with no new tag event and no
publication. The branch commit and failed workflow remain evidence for the next
fix. Rollback is a normal revert before publication. After immutable releases
exist, do not retag or replace 0.8.5; any correction requires a new patch
version. There is no data migration or one-way product change.

## Proposed Spec Delta

Promotion strategy: A, in-file replacement in [TAUT-12.5].

| Spec file | Strategy | Sections touched |
|-----------|----------|------------------|
| `docs/specs/02-taut-core.md` | A | canonical Test factor coverage and pre-tag release ordering in [TAUT-12.5] |

Replace the sentence beginning “Every root OS/Python cell still runs the source
contract” with:

> Root source tests use explicit factor coverage rather than a full
> OS-by-Python Cartesian repetition. The representative Ubuntu coverage cell
> retains the complete source selection. Each macOS cell retains the complete
> source selection. The four Windows Python cells run a deterministic,
> pairwise-disjoint, nonempty partition whose union is exactly the complete
> source selection. Partitioning uses xdist's effective group identity after
> dynamic marker assignment: all inherited and direct positional or `name=`
> group values form one indivisible scheduling unit, with ungrouped node IDs in
> a separate hash domain.
> One small public CLI compatibility smoke runs on every Windows Python version
> and is the only intentional source-test duplicate. The workflow has an
> executable collection oracle for completeness, disjointness, group integrity,
> and the exact four shard identities. Installed-wheel factor coverage remains
> all four supported Python versions on Ubuntu plus one macOS and one Windows
> representative, using the active matrix interpreter.

Insert before “Each tag gate waits for the required canonical workflow”:

> For a publishing invocation, the local helper pushes the prepared canonical
> branch commit before creating, deleting, replacing, or pushing any release
> tag. It then uses the shared exact-SHA workflow selector to wait for successful
> canonical root Test, PostgreSQL Test, and MCP Test runs. A completed
> non-success conclusion is fatal and is never retried by the helper. After
> success, the helper rechecks immutable-release and exact PyPI environment
> settings, then reruns its clean-tree, branch/HEAD, remote publication, and
> leased tag-state fence before tag actions. Observer credentials are resolved
> before branch push, passed only through the child environment, and never
> logged. Dry-run reports this order without credential lookup or polling.
> Tag-gate observers retain the same checks as defense in depth and bind
> publication to the package-specific immutable artifact.

## Task Breakdown

### Slice 1: Plan and independent review

- Review the exact incident logs, current workflow matrix, observer owner, and
  remote action order.
- Independently review this plan for coverage holes, shard/group breakage,
  authentication leakage, TOCTOU gaps, and release-recovery behavior.
- Stop if review finds that factor coverage removes an OS or version contract,
  or that local observation would become the publication artifact authority.

### Slice 2: Spec promotion

- Apply the exact [TAUT-12.5] delta and add this plan to Related Plans.
- Run documentation paths, plan-index, and diff checks. Record the
  promotion baseline identifier.

### Slice 3: Failing source-factor contracts

- Add failing tests for `index/count` validation, fixed stable assignment
  vectors across child processes with different `PYTHONHASHSEED` values, group
  indivisibility, four nonempty shards, pairwise disjointness, exact-union
  completeness, and opt-in-only behavior.
- Real collection cases cover positional, keyword `name=`, inherited plus
  function-level multiple markers, and the dynamically added installed-wheel
  marker. Every effective xdist loadgroup unit must occur in exactly one shard.
- Add failing workflow tests requiring exact Windows shard identities and one
  named compatibility smoke on all four Windows versions.
- Defect injections: force every item into shard zero; hash node IDs despite an
  xdist group; omit one Windows shard. Each must fail its named owner.

### Slice 4: Implement Windows factor coverage

- Add the smallest collection selector to `tests/conftest.py`, reusing the
  existing installed-wheel grouping hook and a stable cryptographic hash.
- Make the Windows matrix pass exactly one of `0/4`, `1/4`, `2/4`, `3/4` to the
  complete source selection. Run `test_cli_json_join_say_log` as the bounded
  compatibility smoke on every Windows version outside the factor selection.
- Preserve all existing Ubuntu/macOS, coverage, installed-wheel, Summon, MCP,
  lint, and packaging commands.

### Slice 5: Failing pre-tag-order contracts

- Add observer CLI tests for workflow-only wait success, incomplete polling,
  immediate completed-failure rejection, malformed/auth failures, no
  `GITHUB_OUTPUT` read/write, and no artifact endpoint request.
- Add release tests proving branch push precedes the wait, the wait precedes any
  tag deletion/preparation/push, a failed wait performs no tag action, and a
  second settings-plus-fresh fence runs after the wait. Inject GitHub Release,
  PyPI, local-tag, remote-tag, lease, and repository-settings drift separately.
- Add credential tests: supplied `GITHUB_TOKEN` avoids `gh`; absent token uses
  captured `gh auth token`; missing `gh`, command failure, and blank output fail
  before branch push; the token appears only in child env and never argv or
  captured output.
- Add batch and single-target tests proving `--skip-checks` still resolves auth,
  pushes the branch, waits for exact-SHA root/PG/MCP, re-fences, and only then
  tags; wait failure leaves every tag untouched. Add checks-only and dry-run
  proofs of no token lookup, API poll, branch push, or tag mutation.
- Add branch-push failure proof: no observer or tag action follows.

### Slice 6: Implement producer-first release order

- Extend `bin/require-green-workflows.py` with a workflow-only wait path that
  reuses `wait_for_required_workflows` and emits concise run evidence.
- Add a release-owned wrapper that supplies exact repository/SHA, obtains a
  token without logging it, and invokes that shared owner.
- Reorder both batch and single release flows: resolve auth, first fresh fence,
  branch push, exact-SHA wait, recheck repository settings, second fresh
  fence/replan, then prepare and push tags.
- Keep tag gates unchanged except for spec/test assertions needed to retain
  their defense-in-depth role.

### Slice 7: Durable documentation

- Update `docs/implementation/04-taut-architecture.md` with the split between
  local workflow-only observation and tag-gate artifact selection.
- Update `docs/implementation/02-repository-map.md` with selector and release-
  order ownership.
- Record in `docs/lessons.md` that runner-hosted observers can deadlock their
  producers under a bounded quota, and that factor coverage removes redundant
  Cartesian repetition only with an executable exact-union/group oracle.

### Slice 8: Verification and release recovery

- Run focused source-factor, workflow, observer, and release-helper tests with
  mutation probes; Ruff, mypy, docs paths, plan index, and diff checks.
- Run the universal local release prechecks through normal `release.py`.
- Commit the coherent slice, rerun `release.py all --version 0.8.5 --retag`, and
  monitor exact-SHA workflows with `gh`. Do not manually rerun a failed producer
  workflow. Fix a real failure on a new commit and repeat the normal recovery.
- Verify all four immutable GitHub Releases, wheel/sdist asset allowlists,
  Sigstore attestations, PyPI versions/files/digests, exact tag SHAs, and a clean
  worktree. Record elapsed local, canonical CI, queue, and publication times.
- Run an independent completed-work review before closing the plan.

## Verification Commands

Exact commands may be narrowed while red, but the final gate includes:

```text
uv run --no-sync pytest tests/test_github_workflows.py tests/test_require_green_workflows.py tests/test_release_script.py tests/test_harness.py -n 0
uv run --no-sync ruff check tests/conftest.py tests/test_github_workflows.py tests/test_require_green_workflows.py tests/test_release_script.py bin/release.py bin/require-green-workflows.py
uv run --no-sync ruff format --check tests/conftest.py tests/test_github_workflows.py tests/test_require_green_workflows.py tests/test_release_script.py bin/release.py bin/require-green-workflows.py
uv run --no-sync mypy tests bin/release.py bin/require-green-workflows.py --config-file pyproject.toml
uv run --no-sync bin/check-doc-paths
bin/check-plan-status-index
git diff --check
uv run --no-sync --extra dev python bin/release.py all --version 0.8.5 --retag
```

Hosted success requires the exact replacement SHA's root, PostgreSQL, and MCP
workflows plus all four publication gates to complete successfully without
manual producer reruns.

## Deviation Log

| Spec ref | Planned behavior | Actual behavior | Rationale | Spec proposal |
|----------|------------------|-----------------|-----------|---------------|

## Review Log

| Date | Scope | Result | Disposition |
|------|-------|--------|-------------|
| 2026-08-11 | Independent plan review | Five blockers: effective xdist identity, second settings fence, credential non-leakage tests, override-mode firing tests, and durable docs; five tightening suggestions. | Adopted all blockers and suggestions. The plan now matches all-marker xdist semantics, resolves auth before branch push, refences settings and all drift classes, covers override modes and workflow-only boundaries, updates durable docs, and records non-atomic batch-tag risk. |
| 2026-08-11 | Independent plan re-review | All substantive blockers and suggestions resolved; requested removal of one duplicated quote fragment and use of the project environment for `check-doc-paths`. | Both textual corrections applied; plan approved for implementation. |
| 2026-08-11 | Independent completed-work review | One blocker: the first implementation passed the shard through a step environment variable, so nested pytest probes inherited and reapplied it. One strengthening request: prove two distinct tests with the same composite xdist identity remain together. | Replaced the environment selector with process-local `--taut-source-shard`, added a sharded-parent/nested-child regression, and added the shared composite-identity case. The reviewer's exact failing module and all four complete shards then passed. |
| 2026-08-11 | Independent correction re-review | No remaining implementation blocker. The reviewer independently reran 34 harness/workflow tests, the prior failing shard boundary, Ruff, format, and diff checks; release ordering and documentation remained aligned. | Approved for the hosted exact-SHA and publication completion gate. |
| 2026-08-11 | Independent hosted-failure correction review | No blocker. Reusing `sys.executable` is the correct dependency-complete, cross-platform interpreter boundary and preserves process-local shard behavior. The reviewer independently reran 21 workflow tests, Ruff, format, focused mypy, and diff checks. | Approved for a new normal release attempt. |

## Execution Log

| Date | Slice | Evidence | Result |
|------|-------|----------|--------|
| 2026-08-11 | S1 comprehension gates | Read xdist 3.8 group construction, current dynamic installed-wheel marker, release remote-action order, repository settings preflight, and exact-SHA observer. | The shard owner must hash the complete sorted effective group after dynamic marking; observers select but never create evidence; completed failures require a corrected commit; settings and all release state must be refenced after the wait. |
| 2026-08-11 | S2 spec promotion | Applied the reviewed exact delta to `docs/specs/02-taut-core.md` [TAUT-12.5] and added the related-plan link; `uv run --no-sync bin/check-doc-paths`, plan-index, and diff checks passed. | The spec tree now owns factor coverage and producer-first release ordering before implementation begins. |
| 2026-08-11 | S3-S4 source factor implementation | Added the opt-in SHA-256 collection shard after dynamic xdist marking, explicit Windows factor rows, and the per-version CLI smoke. Real root collection plus positional, keyword, inherited, multiple, and dynamic group cases prove stable vectors, cross-hash-seed identity, nonempty shards, pairwise disjointness, exact union, and group indivisibility. | The four Windows versions now own the complete source suite once in aggregate; Ubuntu, macOS, installed-wheel, extension, coverage, and local defaults are unchanged. |
| 2026-08-11 | S5 observer mode | Added `wait-workflows` by reusing the canonical exact-SHA evaluator and transport. The full observer suite proves exact workflow success/failure behavior, no artifact request, and no `GITHUB_OUTPUT` dependency. | Local observation can wait on producer evidence without becoming a publication-artifact owner. |
| 2026-08-11 | S6 producer-first release order | Both single and batch paths now first fence, resolve auth, push the exact branch commit, wait for root/PG/MCP, recheck repository settings, repeat the full fresh fence and tag plan, then touch tags. Firing tests cover environment/`gh` auth, missing/failed/blank auth, secret non-leakage, branch-push failure, observer failure, settings drift, `--skip-checks`, checks-only, and dry-run. | Failed or unavailable producer evidence cannot create, delete, replace, or push a tag. The human override remains limited to local prechecks. |
| 2026-08-11 | S7 durable docs | Updated the architecture, repository map, and lessons with factor-coverage ownership, workflow-only observation versus tag-gate artifact selection, repeated settings/fresh-state fences, and runner-quota deadlock recovery. | Spec, implementation rationale, ownership map, and durable lessons are aligned. |
| 2026-08-11 | Focused verification | `pytest` over workflow, observer, release, and harness owners passed; Ruff passed; mypy passed over 62 source files; `check-doc-paths` passed 60 sources/1,174 claims; plan index and `git diff --check` passed. | The implementation slice is locally coherent; universal release gates and hosted replacement evidence remain before completion. |
| 2026-08-11 | S3-S4 execution correction | Ran the nested-pytest regression, the prior failing installed-wheel collection module under its owning shard, and every complete `not slow and not installed_wheel` shard with real xdist execution. | All four shards passed under parallel load in 29.79s, 32.64s, 32.76s, and 37.51s; the only skip was the expected non-Windows filename-contract case. No selector reached nested pytest. |
| 2026-08-11 | First hosted replacement attempt | Normal release preparation produced `c5f87c8` after the selective Summon lock advanced SimpleBroker 7.0.1 to 7.1.0. All universal local gates passed, including 1,836 root tests, every extension suite, strict harness, real local LLM, quality checks, fresh empty-dist builds, and the wheel matrix. Producer-first ordering pushed only the branch and started no tag gate. PG was green in 2m57s. Root macOS 3.13 then failed after 1,835 source passes because the real-collection oracle launched `uv run --no-sync` on a fresh runner; uv created an empty `.venv`, so the nested process lacked pytest. | Stopped the local observer with every tag untouched. Changed the oracle to use `sys.executable`, the dependency-complete interpreter already running the canonical test. This is a test-infrastructure ownership bug, not a product or timeout failure. |
| 2026-08-11 | Second hosted replacement and publication attempt | Exact SHA `319131f` passed root Test `31527821820`, PG `31527821847`, and MCP `31527821780`. All four Windows source factors passed in 4m41s to 6m13s. The four tag gates selected and staged the verified artifacts, then failed before authentication or upload because pinned `gh-action-pypi-publish` v1.14.1 rejected the build backend's Core Metadata 2.5 wheels. PyPI remained untouched and all GitHub Releases remained drafts. | Added a four-gate firing assertion and advanced the immutable publisher pin to v1.14.2, whose upstream purpose is Twine 7/Core Metadata 2.5 support. A new normal helper invocation is required; the failed gates will not be rerun. |
