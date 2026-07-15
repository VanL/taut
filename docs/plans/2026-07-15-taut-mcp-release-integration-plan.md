# Taut MCP Release Integration Plan

Date: 2026-07-15

Class: 5, risky. This changes the normative release target set, tag-triggered
publication boundary, compatibility evidence, and coverage ownership under
[DOM-5], [DOM-6], and [DOM-15].

Plan type: implementation with spec revision.

## Goal

Make `taut-mcp` the fourth GitHub-only release target in Taut's established
exact-SHA release system. A `taut_mcp/vX.Y.Z` tag must consume canonical green
root, PostgreSQL, and MCP workflow evidence, publish the root workflow's
immutable `taut-mcp` bundle without rebuilding it, and remain available through
the `mcp` and `all` release-helper targets. Add MCP execution to the universal
local release boundary and to the canonical same-run coverage aggregation.

No tag, GitHub Release, PyPI upload, or other publication is performed by this
plan. A later owner-requested invocation of the unchanged completed helper is a
separate release operation.

## Requested Outcomes

- [x] Add `mcp` and `taut_mcp/vX.Y.Z` to `bin/release.py`, including `all`.
- [x] Reconcile the MCP manifest version, core dependency floor, README wheel
  examples, and retained MCP lock through the canonical metadata path.
- [x] Run an explicit local non-`pg_only` MCP suite and package-local MCP mypy
  lane in every ordinary release precheck; never count skipped PG tests as PG
  proof.
- [x] Build, smoke, provenance-wrap, and upload MCP release bytes from the
  canonical root Test workflow.
- [x] Add the MCP tag gate and require exact-SHA root, PostgreSQL, and MCP
  workflow evidence for every package tag.
- [x] Add an MCP coverage producer job to the canonical Test workflow, combine
  its shard in the existing same-run coverage job, and enforce the non-PG
  rate-admission behavior line from `taut_mcp`.
- [x] Update specs, implementation notes, maps, READMEs, changelog, and active
  plans so release and coverage ownership are explicit.
- [x] Preserve GitHub-only publication, immutable artifact selection, and the
  no-rebuild publication workflow.

## Source Documents

Source specs:

- `docs/specs/02-taut-core.md` [TAUT-12.5]
- `docs/specs/05-taut-mcp.md` [MCP-1], [MCP-3], [MCP-12]
- `docs/specs/01-development-documentation-operating-model.md` [DOM-5],
  [DOM-10], [DOM-11], [DOM-15]

Related plans and rationale:

- `docs/plans/2026-07-14-taut-mcp-extension-plan.md`
- `docs/plans/2026-07-14-universal-release-gates-plan.md`
- `docs/plans/2026-07-13-ci-speed-determinism-release-evidence-plan.md`
- `docs/implementation/04-taut-architecture.md`
- `docs/implementation/07-taut-mcp-architecture.md`
- SimpleBroker commit `2a442c9c6391f7b68c84a605ab4ee5f4c801d094`,
  `.github/workflows/test.yml`: separate same-run coverage producers upload
  named shards; one report job downloads every shard by the current run,
  requires them, combines them, and applies the coverage gate.

## Spec Baseline

- Git diff base: `d42686b73063f98e89f7ae07f7eef14303139ef8`.
- Plan-start `docs/specs/02-taut-core.md` worktree blob:
  `559a5d3d0e2378e2cf9f7a3c9b9dc1a5e8a75cae`.
- Plan-start `docs/specs/05-taut-mcp.md` worktree blob:
  `755909b59d061b9bbdd65550334ff0890d4bcabb`.
- The worktree already contains the uncommitted coordinated 0.7.0 MCP feature
  and related core changes. This plan revises that worktree; it must preserve
  unrelated owner changes and uses the two blob ids plus
  `git diff d42686b7 -- docs/specs/02-taut-core.md docs/specs/05-taut-mcp.md`
  as the rerunnable starting identifier.
- Promoted `docs/specs/02-taut-core.md` worktree blob:
  `04b7f37335d6a643a8faf0874ecb3ddde2e6c328`.
- Promoted `docs/specs/05-taut-mcp.md` worktree blob:
  `635a839c64e52d5f52d123aaaaf8324e665faad1`.
- At promotion, the exact two-spec diff from the recorded base was 96
  insertions and 50 deletions: core `+73/-44`, MCP `+23/-6`. This includes the
  pre-existing uncommitted 0.7.0 contract work identified by the plan-start
  blobs, not only this release slice. `git diff --check` passed for both files.

## Context and Key Files

- `bin/release.py` owns release targets, manifest versions, derived metadata,
  the fixed release-file allowlist, universal local prechecks, ordinary package
  builds, release commit/tag planning, and branch/tag fences. It currently has
  exactly three target objects and `all` means PG, Summon, and core.
- `bin/release-artifact.py` binds an immutable wheel/sdist bundle to a package,
  version, commit, and tag family. Its closed tag-prefix map currently lacks
  `taut-mcp`.
- `.github/workflows/test.yml` is the sole release-byte producer. Its packaging
  job creates and uploads three attempt-qualified bundles. Its coverage jobs
  upload named shards and its aggregation job downloads and combines every
  `coverage-data-*` artifact from the same workflow run.
- `.github/workflows/test-mcp-extension.yml` owns three-version MCP behavior,
  a real PostgreSQL service, strict typing, formatting, lint, and an ordinary
  build. It is behavior evidence, not the release-byte owner.
- `.github/workflows/release-gate*.yml` are tag-triggered observers. They wait
  for canonical exact-SHA workflows and pass one immutable root-produced
  artifact id/digest to generic `.github/workflows/release.yml`.
- `bin/require-green-workflows.py` already accepts any enumerated set of
  required workflows while deliberately constraining release bytes to the root
  Test workflow. Reuse it unchanged.
- `extensions/taut_mcp/uv.lock` is retained package-local development state. A
  plain `uv lock` in that project reconciles local root/MCP/PG metadata without
  deliberately upgrading unrelated dependencies.
- `bin/check-required-coverage-paths.py` converts coverage presence into a
  firing contract by requiring behavior-bearing source lines. Extend it rather
  than relying on a permissive report that could omit MCP entirely.
- `target_version_files()` in `bin/release.py` has no production caller; only
  its direct unit test calls it. Under the owner's no-dead-code rule, remove
  the helper and that obsolete test rather than extending either for MCP.

Required comprehension checks before implementation:

1. Which workflow owns publishable bytes? Only root `Test`; the MCP workflow
   supplies required exact-SHA behavior evidence and never owns release bytes.
2. Which proof owns MCP PostgreSQL behavior? The required canonical MCP
   workflow with its real service. The local release command names and runs a
   non-`pg_only` lane and must not describe its four excluded cases as passing.
3. What makes coverage absence fatal? The MCP producer runs from the root
   system environment with root coverage tooling and editable local MCP and PG
   installs. The local PG install satisfies MCP's collection-time `taut_pg`
   import without starting a database. The producer is in the same Test run,
   `coverage` needs that job, the named shard must download, and the required
   marker checker must observe
   `_connection_reactor.py` executing `self._bucket_tokens -= 1.0`.
4. Does adding a tag gate authorize a release? No. Tag creation and publication
   remain a separate explicit owner action through the completed helper.

## Proposed Spec Delta

Promotion strategy: A, in-file requirement text before new implementation-link
claims. Apply after Claude Opus reviews this plan and exact delta. Then record
the two promoted spec blob hashes and exact worktree diff before writing release
code or workflow claims.

### `docs/specs/02-taut-core.md` [TAUT-12.5] release targets

Insert after the `summon` target:

> - `mcp` releases `taut-mcp` from `extensions/taut_mcp` with a
>   `taut_mcp/vX.Y.Z` tag and
>   `.github/workflows/release-gate-mcp.yml`.

Replace the `all` target paragraph with:

> - `all` releases every requested package version that does not already have
>   a GitHub Release. With `--version X.Y.Z`, the helper prepares all four
>   package manifests at that coordinated version. Without `--version`, each
>   package's manifest remains the source for its current version. Package
>   versions are otherwise independent; consistency gates compare derived
>   copies to the manifest that owns them rather than requiring unrelated
>   package versions to match.

### `docs/specs/02-taut-core.md` [TAUT-12.5] helper obligations

Replace three-target wording in the branch and metadata obligations with:

> A publishing release runs from `main` or `master`, the branches that produce
> canonical push-triggered CI evidence. One shared guard rejects a topic branch
> or detached `HEAD` before release metadata mutation for `all`, `core`, `pg`,
> `summon`, and `mcp`. Dry-run and checks-only remain usable from other branches
> because they do not publish.
>
> Prepare deterministic metadata before running release prechecks. Change only
> the selected package versions, but reconcile every manifest-owned derived
> copy on every normal release invocation: root `taut/_constants.py`, README
> tag and wheel examples, all three extension `taut>=...` floors, the root dev
> `taut-summon>=...` and `simplebroker-pg>=...` floors, every exact root README
> SimpleBroker requirement occurrence, and the retained Summon and MCP locks.
> Each package manifest owns its version; the root manifest owns the core
> constant and SimpleBroker requirement; the root version owns every
> first-party extension `taut>=...` floor; the Summon manifest owns the root dev
> `taut-summon>=...` floor; the PG manifest owns the root dev
> `simplebroker-pg>=...` floor; and the MCP manifest owns its MCP SDK range and
> its dev-only `taut-pg` compatibility floor. Refresh the Summon lock
> selectively with `uv lock --upgrade-package simplebroker`; reconcile the MCP
> lock with plain `uv lock` in its project; do not refresh or retain a PG
> lockfile.

Replace the universal-precheck sequence paragraph with:

> Each publishing invocation runs one universal precheck sequence, regardless
> of whether its selected target set contains one package or all packages,
> against its clean local preparation commit and before any branch push, tag
> creation or replacement, tag push, or publication unless `--skip-checks` is
> set. `--checks-only` runs that same single sequence without mutation. The
> sequence is: root pytest partitioned into `not slow and not installed_wheel`
> plus a fresh serial `not slow and installed_wheel` invocation,
> `bin/pytest-pg --fast`, the four isolated Summon lanes, one explicit MCP
> `not pg_only` lane under the MCP project, existing root/PG/Summon Ruff paths,
> package-local MCP Ruff lint/format, and four collision-safe mypy owners
> including an explicit MCP project-local command with its package config. The
> local MCP lane never treats excluded PostgreSQL cases as evidence;
> the required canonical MCP workflow supplies that live-backend proof. Target
> selection controls metadata, ordinary package builds, tags, and publication,
> not the default verification scope. `--skip-checks` remains an explicit
> human override for dry-run and publishing commands.

Replace the selected-build sentence with:

> After metadata preparation and prechecks, build each selected package's
> artifacts. The Summon and MCP locks have already been reconciled during
> preparation. Core/Summon retain their separate paired-wheel compatibility
> proof; selecting MCP adds its ordinary package build without changing that
> paired boundary.

### `docs/specs/02-taut-core.md` [TAUT-12.5] workflow obligations

Replace the canonical workflow/artifact paragraph with:

> Canonical `push` runs of `.github/workflows/test.yml`,
> `.github/workflows/test-pg-extension.yml`, and
> `.github/workflows/test-mcp-extension.yml` are the test evidence for a
> release SHA. On canonical `main`/`master` pushes, the root workflow remains
> the sole release-byte owner: it builds core, Summon, PG, and MCP, runs the
> existing paired and PG wheel checks plus a fresh core/MCP wheel installation
> and `taut-mcp` console smoke, and uploads four separate immutable provenance
> bundles. The PG workflow remains real database evidence for the shared PG
> surface; the MCP workflow runs its complete suite with a real PostgreSQL
> service plus its quality gates. Neither extension workflow produces release
> bytes. Pull-request and manual runs retain ordinary packaging smoke but do not
> produce release evidence.

Replace the tag-gate paragraph with:

> The four tag gates call `bin/require-green-workflows.py`; they do not call the
> test workflows. Every package tag requires successful root Test, PostgreSQL
> Test, and MCP Test evidence for the exact peeled commit. Each gate pins its
> package bundle from the root Test workflow by immutable artifact id and
> GitHub archive digest. `.github/workflows/release.yml` verifies the inner
> manifest against `vX.Y.Z`, `taut_pg/vX.Y.Z`, `taut_summon/vX.Y.Z`, or
> `taut_mcp/vX.Y.Z`, rechecks the remote tag, and uploads those exact files. It
> never rebuilds and never publishes to PyPI.

Insert after the coverage aggregation paragraph:

> The canonical Test workflow also owns MCP coverage. One independent MCP
> coverage job installs the root development environment plus editable local
> MCP and PG projects into the runner's system environment. The PG project is
> required because the MCP suite's root `conftest.py` imports `taut_pg` during
> collection, before marker filtering; installing it does not start or require
> a PostgreSQL service. The job runs the explicit
> `not pg_only` MCP suite under the root coverage tool and configuration on one
> representative Python version, and uploads a named shard from the same
> workflow run. Root coverage configuration includes `taut_mcp` as source.
> The existing coverage report job depends on that producer, downloads and
> combines its shard with root and Summon shards, and requires execution of the
> unique non-PG rate-admission line
> `self._bucket_tokens -= 1.0` in
> `extensions/taut_mcp/taut_mcp/_connection_reactor.py` before generating the
> report. The MCP compatibility workflow remains the sole live-PostgreSQL MCP
> conformance owner and does not become a second coverage owner.

### `docs/specs/05-taut-mcp.md` [MCP-3]

Insert after the package dependency paragraph:

> Repository publication is GitHub-only. `taut-mcp` is the `mcp` release target
> in [TAUT-12.5], uses the `taut_mcp/vX.Y.Z` tag family, and is published only
> by `.github/workflows/release-gate-mcp.yml` from the immutable root-Test
> bundle for the exact green tag commit. The release workflow never rebuilds
> the package and never uploads it to PyPI. Configuring this release path does
> not itself publish a version; a GitHub Release exists only after a later
> explicit tag operation succeeds.

### `docs/specs/05-taut-mcp.md` [MCP-12]

Replace the CI-owner paragraph with:

> `.github/workflows/test-mcp-extension.yml` owns MCP compatibility and
> backend-conformance evidence: its test matrix supplies a real PostgreSQL
> service and runs the complete extension suite without skipping `pg_only`,
> while its quality lane runs Ruff, formatting, strict mypy, and an ordinary
> build. A local no-DSN run may skip PostgreSQL tests for speed, but that run is
> not backend-conformance evidence. For publication, [TAUT-12.5]'s canonical
> root Test workflow separately builds and smokes the exact core/MCP wheels,
> creates the immutable MCP release bundle, and uploads it as the sole
> release-byte owner. The same root workflow owns one MCP `not pg_only`
> coverage producer in its root system environment and combines that named
> shard into the existing same-run report; root coverage source includes
> `taut_mcp`, and the required unique rate-admission marker makes a missing,
> empty, or path-misconfigured shard fatal. Live MCP PostgreSQL behavior remains
> owned by the required canonical MCP compatibility workflow.

Add this plan to both specs' `Related Plans` sections during promotion.

## Invariants and Constraints

- Publication stays GitHub-only. No code path may add `uv publish`, PyPI
  trusted publishing, attestations unrelated to the existing GitHub boundary,
  or a second publisher.
- Root Test is the only release-byte owner. MCP Test proves behavior and may
  build disposable artifacts, but its artifacts are never published.
- Every tag gate observes root, PG, and MCP canonical push workflows for the
  exact peeled commit. Gates never enqueue tests and never rebuild packages.
- `release.yml` stays generic. Only its closed tag-family verifier is extended
  through `bin/release-artifact.py`.
- The local MCP precheck explicitly excludes `pg_only`; the exclusion is named
  in code, tests, and docs. Required canonical MCP evidence supplies live-PG
  proof before any tag gate publishes.
- `mcp` remains target-specific and `all --version` coordinates four manifests.
  Package versions remain independent outside an explicit coordinated batch.
- Root version owns MCP's `taut>=` floor. MCP owns its SDK range and dev-only
  `taut-pg` floor; this plan does not create a new paired PG/MCP version rule.
- Plain MCP `uv lock` reconciliation must preserve unrelated resolved versions.
  If it upgrades unrelated packages, stop and replace it with a narrower
  command rather than accepting lock churn.
- Core/Summon paired-wheel checks remain unchanged. MCP gets a separate exact
  canonical-wheel smoke because it owns a different console boundary.
- Coverage collection has one owner. The root Test MCP producer uses the root
  system environment's coverage installation, installs MCP editable, explicitly
  runs `not pg_only`, and uploads a same-run shard; root coverage source includes
  `taut_mcp`, and the existing aggregator requires the producer plus the unique
  non-PG rate-admission line. Codecov upload remains best-effort only after the
  local combine and marker gates pass.
- Every release target, tag family, workflow, fixed artifact prefix, and
  coverage shard/marker is an enumerable contract with a firing test.
- No new dependency is introduced.
- Preserve all unrelated dirty-worktree changes. Do not reset, discard, or
  rewrite existing MCP work.

## Fatal and Best-Effort Failures

- Fatal: metadata drift, lock reconciliation failure, any local precheck,
  package build/smoke failure, missing provenance bundle, missing exact-SHA
  workflow, missing/empty coverage shard, absent MCP marker, immutable artifact
  mismatch, moved tag, or publication-workflow rebuild.
- Best-effort only after fatal gates pass: Codecov upload, matching the existing
  repository policy.
- A dedicated workflow's ordinary disposable build is not release evidence and
  cannot compensate for a missing root-produced bundle.

## Rollout, Rollback, and One-Way Doors

Rollout order:

1. Review and promote the spec delta.
2. Land release-helper contracts and exact tests without creating tags.
3. Land root artifact/coverage production, the MCP behavior workflow contract,
   and all four observers together.
4. Let a canonical branch push produce all three green workflows, four release
   bundles, and the combined coverage report.
5. Only after that evidence exists may the owner separately request the normal
   coordinated 0.7.0 release helper invocation.

Before a tag is pushed, rollback is an ordinary revert of this release
integration. Existing three-package releases remain usable if the new MCP gate
and target are reverted together. After a public MCP GitHub Release exists,
deleting or moving the tag/release is a one-way public-history correction and
is outside this plan; fix forward with a new version unless the owner explicitly
authorizes the existing retag procedure. This plan performs no one-way action.

Stop and re-plan if implementation requires changing
`bin/require-green-workflows.py`'s root-artifact-owner rule, publishing from the
MCP workflow, adding a dependency, weakening an existing tag gate, counting
skipped PG cases as proof, splitting coverage into cross-workflow artifact
discovery, or changing core/Summon pairing.

## Tasks

1. **Independent review of plan and exact spec delta.**
   - Reviewer: Claude Opus via the repository `call-agent` skill.
   - Read: this plan, [TAUT-12.5], [MCP-3], [MCP-12], release helper,
     artifact verifier, root/MCP workflows, coverage checker, and closest tests.
   - Ask for P1/P2 findings, unnecessary machinery, boundary gaps, and a
     PASS/BLOCKED verdict. Do not implement.
   - Record and disposition every finding here before spec promotion.

2. **Spec-promotion slice.**
   - Apply the exact strategy-A delta to `docs/specs/02-taut-core.md` and
     `docs/specs/05-taut-mcp.md`; add reciprocal plan backlinks.
   - Run `tests/test_docs_references.py`.
   - Record promoted blob hashes and exact diff in this plan.
   - Stop if the promoted contract would require a second artifact owner or
     cross-workflow coverage discovery.

3. **RED: enumerate the fourth target and tag family.**
   - Update tests first in `tests/test_release_script.py` and
     `tests/test_release_artifact.py` for `MCP_TARGET`, `mcp`,
     `taut_mcp/vX.Y.Z`, `all` ordering, GitHub-only flags, and closed tag-family
     validation.
   - Observe targeted failures before editing production code.
   - GREEN by extending existing `ReleaseTarget` and prefix-map paths; do not
     create a parallel MCP release helper.
   - Remove unused `target_version_files()` and its obsolete test rather than
     carrying dead code into the fourth target.

4. **RED: metadata, lock, universal checks, and selected build.**
   - Add failing tests for four-manifest preparation, MCP version/wheel example,
     core floor, retained lock allowlist/reconciliation, stable batch order,
     MCP ordinary build, explicit `not pg_only` test command, full Ruff paths,
     package-local MCP Ruff lint/format, and explicit package-local MCP mypy.
   - Extend `bin/release.py` through existing generic helpers and command-step
     builders for shared behavior. Keep MCP Ruff and mypy as explicit
     `uv run --project extensions/taut_mcp` commands with the MCP config rather
     than forcing them through root-config helpers. Add one plain `uv lock`
     preparation step in the MCP project.
   - Add exact `@vX.Y.Z` and `taut_mcp-X.Y.Z-py3-none-any.whl` tokens to the MCP
     README and the MCP wheel token to the root README. Add the MCP README to
     the root target's core-tag synchronization loop so a later independent
     core-only release cannot leave that token stale. Extend the real
     `sync_readme_version_examples()` branches and metadata-consistency test;
     do not add a zero-match replacement path.
   - Verify a real no-upgrade `uv lock --check`/diff cycle. Stop if unrelated
     package versions change.

5. **RED: canonical bytes and exact-SHA tag gates.**
   - Update `tests/test_github_workflows.py` first: four root-produced bundles,
     exact core/MCP wheel smoke, MCP artifact prefix, four observers, and three
     required exact-SHA workflows for every tag.
   - Add `.github/workflows/release-gate-mcp.yml` by adapting the existing
     extension gate; extend the three existing gates with MCP evidence.
   - Extend root `packaging` to build/smoke/bundle/upload MCP. Keep
     `.github/workflows/release.yml` and `bin/require-green-workflows.py`
     unchanged unless a red test demonstrates a genuine missing generic seam;
     otherwise stop and re-plan.

6. **RED: same-run MCP coverage.**
   - Extend `tests/test_github_workflows.py` and
     `tests/test_required_coverage_paths.py` first for an `mcp-coverage` job,
     root-system coverage environment, editable local MCP and PG installs,
     explicit `not pg_only` invocation, named shard, coverage job
     dependency/download/combine, exact `taut_mcp` source inclusion, and the
     unique required marker `self._bucket_tokens -= 1.0`.
   - The workflow test must fail if the MCP coverage producer omits the local
     `extensions/taut_pg` install. Marker filtering happens after the suite's
     root `conftest.py` imports `taut_pg`, so this is a collection dependency,
     not live-PostgreSQL evidence.
   - The producer has no narrower job-level event condition than the existing
     required coverage producers: it runs for every root Test workflow event
     on which the always-running aggregator can require its shard. Encode that
     trigger parity in the workflow test so pull requests cannot fail solely
     because the MCP shard was configured as push-only.
   - Add the producer to `.github/workflows/test.yml`, extend root coverage
     config, and add the marker to `bin/check-required-coverage-paths.py`.
   - Copy SimpleBroker's producer/shard/report ownership pattern. Do not add a
     PostgreSQL service, second report, `coverage` to an extension's dependency
     metadata, or cross-workflow artifact lookup; the dedicated MCP workflow
     already owns three-version live-PG proof. The explicit editable local PG
     install above is required test collection support, not a coverage owner.

7. **Documentation and traceability reconciliation.**
   - Update `docs/implementation/04-taut-architecture.md`,
     `docs/implementation/07-taut-mcp-architecture.md`,
     `docs/implementation/02-repository-map.md`, root and MCP READMEs,
     changelog, the active MCP plan scope/decision log, and plan index.
   - Describe the configured release path without claiming a GitHub Release
     exists before the tag gate has actually published one.
   - Update release command examples with `mcp` and document
     `pipx inject --include-apps` so the MCP console is exposed.

8. **Verification and completed-work review.**
   - Run targeted red/green suites, root and MCP lint/format/mypy, docs,
     metadata, build/archive, exact-wheel smoke, and the complete relevant test
     lanes below.
   - Run a read-only final Grok review because the prior plan review used
     Claude Opus. Disposition every finding and rerun affected gates.
   - Leave the work uncommitted unless the owner separately requests a commit.

## Testing Plan

- Use real `ReleaseTarget`, metadata writer, command planner, tag validator,
  YAML text, coverage database, package builds, wheels, and console script.
- Mock only network/GitHub state and subprocess execution in existing unit
  seams. Do not mock target enumeration, version-file writes, release allowlist,
  artifact manifest verification, workflow text, or coverage marker lookup.
- Red-green evidence must cover every new closed-set member: target key, package
  name, tag family, gate path, artifact prefix, workflow evidence member,
  package build, README wheel pattern, lock path, coverage shard, and marker.
- Existing exact-SHA observer tests must prove every gate requires root, PG, and
  MCP exactly once and still selects bytes only from root.
- The canonical wheel smoke installs the actual built core and MCP wheels into
  a fresh environment and executes `taut-mcp --version`.
- The local universal MCP command explicitly selects `not pg_only`; a separate
  workflow contract proves the required MCP workflow supplies a real PG service
  and runs the complete suite without that exclusion.
- Coverage tests prove structural ownership. A local representative coverage
  run supplies supporting evidence; the first canonical push remains the
  operational proof that GitHub merges the new shard.

## Verification and Gates

Targeted gates:

```bash
uv run --extra dev pytest -q tests/test_release_script.py tests/test_release_artifact.py tests/test_github_workflows.py tests/test_required_coverage_paths.py -n 0
uv run --extra dev pytest -q tests/test_docs_references.py tests/test_project_metadata_consistency.py tests/test_github_workflows.py -n 0
uv run --project extensions/taut_mcp --extra dev pytest extensions/taut_mcp/tests -m "not pg_only" -n 0
```

Static and packaging gates:

```bash
uv run --extra dev ruff check taut tests bin extensions/taut_pg/taut_pg extensions/taut_pg/tests extensions/taut_summon/taut_summon extensions/taut_summon/tests
uv run --extra dev ruff format --check taut tests bin extensions/taut_pg/taut_pg extensions/taut_pg/tests extensions/taut_summon/taut_summon extensions/taut_summon/tests
uv run --project extensions/taut_mcp --extra dev ruff check extensions/taut_mcp/taut_mcp extensions/taut_mcp/tests
uv run --project extensions/taut_mcp --extra dev ruff format --check extensions/taut_mcp/taut_mcp extensions/taut_mcp/tests
uv run --extra dev mypy taut tests bin/release.py bin/release-artifact.py bin/require-green-workflows.py --config-file pyproject.toml
uv run --project extensions/taut_mcp --extra dev mypy extensions/taut_mcp/taut_mcp extensions/taut_mcp/tests --config-file extensions/taut_mcp/pyproject.toml
uv lock --directory extensions/taut_mcp --check
uv build --project extensions/taut_mcp --out-dir dist/taut_mcp
```

Final regression gates:

```bash
uv run --extra dev pytest -q -n 0
uv run --project extensions/taut_mcp --extra dev pytest -q -n 0
git diff --check
```

The PostgreSQL MCP cases have already passed against a real service in the MCP
implementation closure; this release slice must preserve their dedicated CI
owner. If a live local DSN is available, rerun all MCP tests with it. Otherwise
the missing post-change operational proof is explicitly the first canonical
three-workflow push, not a falsely green skipped local run.

Post-deploy success signals after a later canonical push are: three eligible
exact-SHA workflows on one commit; four immutable release bundles from root
Test; one MCP coverage shard combined into the report; and no tag gate
publication until all three workflow owners are green. After a later release,
the `taut_mcp/vX.Y.Z` GitHub Release must contain exactly one wheel and one
sdist whose inner manifest matches the tag commit.

## Independent Review Loop

Plan review uses Claude Opus with read-only `Read,Grep,Glob` permissions and a
15-minute bound. Final implementation review uses Grok in its OS-enforced
read-only sandbox. Both receive this plan, promoted specs, implementation docs,
release helper/artifact verifier, workflows, and touched tests. Each review must
return explicit P1/P2 findings plus PASS/BLOCKED; every finding is reproduced
and either accepted, rejected with evidence, or marked out of scope here.

## Out of Scope

- Actual tag creation, GitHub Release publication, PyPI publication, or package
  name clearance.
- Changing generic immutable-artifact selection or the generic publication
  workflow beyond the closed MCP tag-family mapping.
- Decoupling optional package failures from universal release availability.
- Expanding `bin/pytest-pg` into an MCP test runner; exact-SHA MCP CI owns live
  PG proof.
- Changing MCP runtime behavior, tool schemas, reactor lifecycle, or SDK range.
- Changing core/Summon paired compatibility policy.
- Adding attestations, signing, deployment, HTTP transport, or a daemon.

## Deviation Log

| Spec ref | Planned behavior | Actual behavior | Rationale | Spec proposal |
|----------|------------------|-----------------|-----------|---------------|

## Review Log

### Claude Opus plan/spec-delta review

Opus inspected the plan, both specs, release helper/artifact/observer code,
workflows, coverage configuration/checker, and closest tests. It returned
`VERDICT: BLOCKED` on the coverage paragraph and four findings:

| Finding | Disposition |
|---------|-------------|
| P1: the draft mandated a fourth full live-PG MCP run under coverage without naming an environment that contains `coverage`; root coverage source omitted `taut_mcp`; the duplicate PG run was unnecessary for the proposed in-process marker. | Accepted. The producer now runs explicit `not pg_only` MCP tests in the root system environment after editable MCP installation, uses root coverage configuration with exact `taut_mcp` source, and leaves live PG to the required canonical MCP workflow. |
| P2: MCP mypy was project-local but Ruff used the root config, diverging from MCP CI; the generic mypy helper hardcodes root config. | Accepted. Universal checks now have explicit package-local MCP Ruff lint/format and mypy commands; shared helpers remain for root/PG/Summon only. |
| P2: README sync had no real MCP tokens or branch, and `_replace_all` fails closed on zero matches. | Accepted. Root and MCP READMEs will receive actual `taut_mcp-X.Y.Z` tokens, MCP README also gets the core tag token, and tests cover the matching sync branches and metadata consistency. |
| P2: the required coverage marker must occur exactly once and execute in the non-PG producer. | Accepted. The marker is the unique, non-PG rate-bucket debit `self._bucket_tokens -= 1.0`, already exercised by connection-reactor tests. |

Opus verified root-only artifact ownership, artifact-prefix separation,
three-workflow observer feasibility, exact-wheel console smoke, dead
`target_version_files()`, and existing MCP floor/lock checks. After the accepted
coverage revision, its stated blocking condition is resolved. A focused Opus
recheck of the revised delta is required before promotion.

### Claude Opus focused recheck 1

The focused recheck returned `VERDICT: BLOCKED` because the revised non-PG
producer still omitted an import-time dependency:

| Finding | Disposition |
|---------|-------------|
| P1: `extensions/taut_mcp/tests/conftest.py` imports `taut_pg` before pytest marker filtering, while neither the root development install nor the MCP runtime install provides it; the proposed coverage lane therefore cannot collect. | Accepted. The plan and proposed spec delta now require editable local MCP and PG installs in the root system environment, explicitly distinguish the PG package import from live-PostgreSQL proof, and require a workflow test that fails if the local PG install is absent. |
| P2: calling `target_version_files()` caller-free was inaccurate because its direct test calls it. | Accepted. The context now says it has no production caller and explicitly removes both helper and obsolete direct test. |

A second focused Opus recheck is required before promotion.

### Claude Opus focused recheck 2

The second focused recheck returned `VERDICT: PASS`. It confirmed the revised
producer can collect, the unique marker executes in the non-PG lane, the
project-local quality commands are executable, the proposed spec delta is
internally consistent, and the documentation set covers the ownership split.
It raised two implementation-level P2 findings:

| Finding | Disposition |
|---------|-------------|
| P2: the MCP README's core-owned `@vX.Y.Z` example would drift on an independent core release unless the root synchronization loop also visits that README. | Accepted. Task 4 now requires adding the MCP README to the root-owned core-tag loop and covering it in metadata consistency tests. |
| P2: the required MCP coverage shard must be produced on every root Test event where the always-running aggregator requires it. | Accepted. Task 6 now forbids a narrower job-level event condition and requires a workflow test for trigger parity. |

The review gate for strategy-A spec promotion is satisfied.

### Grok completed-work review

Grok reviewed the full worktree diff, including the promoted specs, release
plan, helper, workflows, tests, and user-facing documentation. Its first two
headless attempts returned no review because locally discovered plugin tools
consumed the three-turn cap despite `--tools ""`. A third run added explicit
read, write, shell, web, and delegation denials without weakening plan mode; it
returned `VERDICT: BLOCKED` with two P1 and three P2 findings:

| Finding | Disposition |
|---------|-------------|
| P1: `prepare_release_metadata()` does not reconcile MCP's development-only `taut-pg` floor. | Rejected with direct call-graph and firing-test evidence. `prepare_release_metadata()` calls `_sync_root_release_dependencies()`, which calls `sync_mcp_pg_dev_dependency()`. `test_prepare_release_metadata_repairs_all_derived_copies_idempotently` uses real temporary manifests and asserts the repaired `taut-pg>=0.6.2` floor; `test_release_sync_updates_all_first_party_dependency_directions` separately proves the helper is in the shared synchronization path. Both pass. |
| P1: the all-derived-metadata fixture contains duplicate MCP manifest/README writes and a duplicate root README wheel line. | Accepted. Removed the overwritten manifest setup, duplicate README setup, and duplicate wheel fixture. The behavior assertions and red-green coverage remain unchanged. |
| P2: the Class 5 plan did not record implementation, verification, or final-review status. | Accepted. Requested outcomes, execution evidence, review dispositions, and the fresh-eyes checklist are updated in this closure pass. |
| P2: two retained-lock tests still had Summon-only names after MCP lock reconciliation became universal. | Accepted. Renamed them to describe reconciliation of both retained extension locks. |
| P2: static tests do not prove the non-PG producer executes the rate-admission marker. | Accepted as a verification obligation, not a missing unit path. The non-PG `test_connection_token_bucket_uses_continuous_refill_without_refund` forces the debit. A local isolated coverage run executed the non-PG connection-reactor tests, combined the parallel shard, and confirmed `self._bucket_tokens -= 1.0` at line 281 in measured data. The first canonical Test run remains the operational workflow proof. |

After the accepted changes, the review's only blocking call-graph claim is
disproved by production code and two green tests. No unresolved P1 or P2
finding remains.

## Execution Log

- 2026-07-15: Classified Class 5 risky; recorded dirty-worktree spec blobs and
  diff base; audited release helper/workflows and SimpleBroker coverage design;
  drafted exact strategy-A delta. No release code, workflow, tag, or publication
  change has yet been made under this plan.
- 2026-07-15: Claude Opus blocked the first delta on an under-specified and
  duplicate live-PG coverage producer. Revised the plan/spec text to use root
  system coverage, editable MCP, explicit non-PG tests, exact source inclusion,
  one unique reactor marker, project-local MCP Ruff/mypy, and real README sync
  tokens. No spec promotion or implementation has occurred yet.
- 2026-07-15: The first focused Opus recheck found that MCP's root test
  `conftest.py` imports `taut_pg` before `not pg_only` filtering. Revised the
  producer contract to install both local MCP and PG projects and added an
  explicit red workflow-test requirement for the PG collection dependency.
  Also corrected the dead-helper wording. No spec promotion or implementation
  has occurred yet.
- 2026-07-15: The second focused Opus recheck passed the proposed spec delta.
  Accepted its two P2 implementation clarifications: root-owned core-tag sync
  must include the MCP README, and the MCP coverage producer must run on every
  Test event required by the aggregator. Spec promotion is now unblocked.
- 2026-07-15: Promoted the reviewed [TAUT-12.5], [MCP-3], and [MCP-12]
  contracts. Recorded both promoted worktree blobs and the exact two-spec diff
  against the plan base; `git diff --check` passed. No release code or workflow
  claims had been changed before this promotion.
- 2026-07-15: Implemented the fourth release target, four-manifest metadata and
  retained-lock reconciliation, universal non-PG MCP/quality prechecks,
  root-owned MCP build/smoke/provenance bundle, four exact-SHA observers, and
  same-run MCP coverage shard with the unique rate-admission marker. Generic
  publication and workflow-evidence helpers remain unchanged.
- 2026-07-15: Reconciled the shipped specs, architecture notes, repository map,
  root and MCP READMEs, changelog, original MCP plan, and plan index. The
  user-facing examples now name the `mcp` helper target,
  `taut_mcp/vX.Y.Z`, and `pipx inject --include-apps` while distinguishing a
  configured release path from an actual published GitHub Release.
- 2026-07-15: Verification passed: 211 release/workflow/metadata/docs tests
  before the final review additions; 1,083 root non-slow tests with one
  platform skip; the complete serial root suite with the same skip; MCP's 67
  non-PG tests plus four deselections; all 71 MCP tests against a real
  PostgreSQL 18 container; PostgreSQL fast lanes with 195 shared and 14
  extension tests; root and package-local Ruff/format/mypy; MCP lock check;
  exact 0.7.0 core/MCP wheel build, clean-environment console smoke, and
  provenance bundle; YAML parsing; and `git diff --check`.
- 2026-07-15: Grok's final review found real fixture duplication, stale test
  names, incomplete plan status, and an unrecorded marker-execution proof; all
  were corrected or supplied. Its remaining P1 was a call-graph misread and is
  rejected with direct code and two firing tests. No tag, GitHub Release, PyPI
  upload, commit, or push occurred.

## Fresh-Eyes Checklist

- [x] `mcp` is a fourth member of every release closed set, not a side path.
- [x] Root Test alone owns publishable bytes.
- [x] All four gates require root, PG, and MCP exact-SHA evidence.
- [x] Local MCP PG exclusions are explicit and never called passing proof.
- [x] Coverage has one same-run producer and one existing aggregator.
- [x] Missing shard and missing MCP behavior marker both fail.
- [x] Generic publication does not rebuild and remains GitHub-only.
- [x] MCP console exposure is proven from exact built wheels.
- [x] Lock reconciliation does not upgrade unrelated dependencies.
- [x] No tag or release action occurs during implementation.
- [x] Spec, plan, implementation docs, code, tests, and workflow maps close the
  reciprocal traceability chain.
