# 2026-07-13 Release Metadata Preparation Plan

Plan type: implementation with spec revision.

Status: implemented and verified; independent completed-work review passed;
worktree intentionally uncommitted for owner review.

## Goal

Make `bin/release.py` own deterministic release-metadata preparation so a
maintainer does not discover and repair version, dependency-floor, README, and
retained-lock copies through serial test failures. Keep the consistency tests
as gates, but make each package manifest the source for its own version and the
root manifest the source for its SimpleBroker requirement.

## Requested Outcomes

- [x] A normal release invocation prepares deterministic metadata before the
  test gate that verifies it.
- [x] `all --version X.Y.Z` can set one coordinated version across core, PG,
  and Summon without manual manifest edits.
- [x] A target-specific release still supports an independent package version;
  metadata tests compare each derived copy to the manifest that owns it rather
  than forcing unrelated package versions to match. The selected version may
  change; unselected manifest versions stay fixed while their derived copies
  are still repaired.
- [x] First-party `taut>=...`, `taut-summon>=...`, and root dev
  `simplebroker-pg>=...` floors, README examples, the core version constant,
  and the retained Summon lock are generated or refreshed by the helper.
- [x] The changelog entry stays human-authored and is checked before generated
  files are changed.
- [x] The helper stages and commits the prepared release files locally before
  checking them, so a failed check leaves a clean rerunnable commit rather than
  a dirty half-prepared tree.
- [x] No branch push, tag mutation, tag push, or publication occurs before the
  committed metadata, tests, builds, and paired wheel check pass.

## Source Documents

- `docs/specs/02-taut-core.md` [TAUT-3.4], [TAUT-8.3], [TAUT-12.5]
- `docs/specs/03-identity-addressing-notifications.md` [IAN-8.2]
- `docs/specs/04-summon.md` [SUM-9]
- `docs/implementation/04-taut-architecture.md`
- `docs/implementation/05-taut-summon-architecture.md`
- `docs/plans/2026-07-08-release-helper-simplebroker-port-plan.md`
- `docs/plans/2026-07-11-multi-factor-review-remediation-plan.md`, Task 11
- `docs/agent-context/runbooks/testing-patterns.md`
- `docs/agent-context/runbooks/adversarial-acceptance-probes.md`

## Spec Baseline

- `2c7d9dc3` (`Sync uv.lock`) for `docs/specs/02-taut-core.md` and
  `docs/specs/03-identity-addressing-notifications.md` at plan authoring time.
- This plan revises the release CLI contract and reconciles the already-edited
  root manifest's `simplebroker>=5.3.2` floor with the governing spec.
- Promotion baseline: `2c7d9dc3 + worktree diff`; the plan was reviewed before
  the spec-promotion slice because the user did not request a planning commit.

## Current Behavior and Reproduction

`tests/test_project_metadata_consistency.py` currently treats one root version
as the expected value for all three packages, hardcodes the exact SimpleBroker
floor in the test, and checks derived files one assertion at a time.
`bin/release.py` already has writers for versions, README examples, and
first-party dependency floors, plus a Summon `uv lock` step. The normal release
path calls the complete pytest precheck before those writers and the lock step.
The batch path rejects `all --version` entirely.

The tight current-state feedback loop is:

```text
uv run --extra dev pytest -q tests/test_project_metadata_consistency.py
```

Observed on 2026-07-13 at `2c7d9dc3`: one pass and one failure. The failure is
`test_readme_install_examples_match_current_manifests`, because the manifest
version is `0.6.1` while the helper-owned README examples still say `0.6.0`.
The command is deterministic, agent-runnable, and exercises the exact serial
metadata failure the maintainer reported.

Recent commits show the same chain: the SimpleBroker manifest change was
followed by separate manual commits for package versions, changelog, the
test's hardcoded floor, the root Summon dev floor, and the retained lock. The
README gate remains red.

## Context and Key Files

- `bin/release.py`
  - Add a manifest-only version reader for planning. The existing
    `read_current_version()` compares the root manifest to the derived core
    constant and therefore cannot repair a stale constant.
  - `write_version_files()` owns one target manifest, the core constant, and
    target-specific README replacements.
  - Add one explicit README SimpleBroker-requirement synchronizer. No existing
    helper updates that derived copy from the root manifest.
  - `sync_root_summon_dev_dependency()` and
    `sync_summon_core_dependency()` own the two first-party floor directions.
  - `build_postupdate_steps_for_targets()` currently mixes the retained lock
    refresh with artifact builds and paired-wheel verification.
  - `main()` and `_run_batch_release()` run prechecks before those mutations.
  - A target-specific invocation must reconcile all manifest-owned copies,
    because the root precheck suite verifies repository-wide metadata. Its
    release-file allowlist therefore includes only the complete derived-
    metadata set, never unrelated paths.
- `tests/test_release_script.py` owns CLI parsing, mutation order, dry-run,
  checks-only, retained-lock, artifact, and irreversible-action guards.
- `tests/test_project_metadata_consistency.py` owns cross-file consistency.
  It should compare derived values to their manifest owner, not become another
  editable source of the same literal.
- `extensions/taut_summon/uv.lock` is retained release state. The PG lock is
  intentionally ignored and must remain so.
- `README.md` and extension READMEs contain tag and wheel examples generated by
  the existing replacement helpers.
- `CHANGELOG.md` contains human release notes. The helper verifies a heading but
  must not synthesize prose.

Comprehension gates before editing:

1. Which operations are local preparation, and which cross the remote one-way
   door? File writes, `uv lock`, staging, and a local commit are preparation;
   branch pushes, tag creation/replacement tied to a remote release, tag pushes,
   and GitHub publication are later boundaries.
2. Which value owns each copy? Each package manifest owns its package version;
   the root manifest owns the core constant and SimpleBroker requirement; the
   root version owns both extension `taut>=...` floors; the Summon manifest owns
   the root dev `taut-summon>=...` floor; the PG manifest owns the root dev
   `simplebroker-pg>=...` floor; manifests own README and retained-lock
   comparisons.

## Invariants and Constraints

- GitHub-only publication, tag namespaces, target aliases, retag rules, and
  paired core/Summon wheel verification do not change.
- `--checks-only` remains strictly non-mutating. It reports drift and never
  repairs files. `--dry-run` prints the real order without changing files.
- Changelog verification and publication-state checks happen before generated
  file writes. A missing heading or already-published target leaves the tree
  untouched.
- Metadata preparation and its exact-path local commit happen before pytest, so
  the test suite verifies one named commit containing the state the helper
  intends to release.
- `uv lock` for Summon is preparation. Artifact builds and paired-wheel checks
  remain after prechecks and before every branch/tag push action.
- The release invocation is explicit authority to write, stage, and locally
  commit the exact release-file allowlist. It is not authority to stage
  unrelated worktree paths or add agent attribution.
- A writer or lock failure before the preparation commit may leave only
  helper-generated working-tree changes. Do not use `git reset`, checkout, or
  hidden rollback. A precheck or artifact failure after the preparation commit
  must leave the branch clean at that local commit. In both cases, the
  diagnostic must say that no remote release action ran.
- After the preparation commit, any new tracked release-file change is a hard
  stop. Do not silently amend or create a second unchecked metadata commit
  after prechecks.
- Do not add a new version file, dependency, generic templating system, or
  second release script.
- Do not retain or begin checking `extensions/taut_pg/uv.lock`.
- The SimpleBroker 5.3.2 floor is load-bearing for interruptible watcher
  bootstrap under locked PhaseLock/SQLite setup. Do not weaken it to the
  artifact checker's general 5.3.0 compatibility floor.
- Version parsing remains strict `X.Y.Z`. Explicit batch versions apply to all
  three package manifests. Existing target-specific `--version` remains valid.
- When an explicit batch version names a GitHub Release that already exists for
  one target, preserve the current batch resume behavior: exclude that target's
  publication action while still preparing local manifest-derived consistency
  for the requested version. Never backdate a manifest below its current
  version.
- Summon lock refresh uses
  `uv lock --upgrade-package simplebroker`, not a broad refresh. A historical
  dry run at `9671d1f1` proved that this updates only `simplebroker` plus the
  local editable `taut` and `taut-summon` versions; it preserves unrelated
  `mypy`, Ruff, and other registry pins. The command shape gets a firing test.
- Before remote action, require the current branch and `HEAD` to match the
  preparation commit, the index and worktree to be clean, and a fresh
  publication/tag-state inspection to remain compatible with the planned
  action. Every branch/tag refspec and local tag command names the preparation
  commit explicitly; remote tag deletion uses an exact force-with-lease from
  the fresh state. State drift or a failed lease fails closed and requires a
  rerun.

## Rollout and Rollback

This is a local developer-tool change. Rollout is the next invocation of
`bin/release.py`; no runtime or stored-data migration exists. The first real
release should use `all --dry-run --version X.Y.Z` to inspect ordering, then the
normal command from a clean branch after human changelog text is committed. The
normal command prepares and locally commits release metadata, checks that exact
commit, and pushes only after every local proof passes.

Rollback is a normal revert of this change before any release command is run.
After a writer/lock failure before commit, the helper leaves generated edits
visible for explicit inspection. After a test or artifact failure, the local
preparation commit remains clean and unpushed; the maintainer can fix forward,
amend/revert explicitly, or rerun after another local commit. The helper never
resets the branch automatically. After a tag push, existing retag and GitHub
release rules govern; this plan adds no new automatic rollback across that
one-way door.

Post-release success is: the selected tag workflows publish the expected
artifacts, package metadata reports the manifest versions/floors, and rerunning
the metadata test plus `--checks-only` stays green without hand edits.

## Proposed Spec Delta

Promotion strategy: A, in-file requirement text before code/link claims. The
spec-promotion slice will edit existing paragraphs in
`docs/specs/02-taut-core.md`, add this plan under `## Related Plans`, and record
the worktree diff baseline before code changes.

| Spec file | Strategy | Sections touched |
|-----------|----------|------------------|
| `docs/specs/02-taut-core.md` | A | [TAUT-3.4], [TAUT-8.3], [TAUT-12.5] |
| `docs/specs/03-identity-addressing-notifications.md` | A | [IAN-8.2] |
| `docs/specs/04-summon.md` | A | [SUM-9] |

### [TAUT-3.4] replacement floor paragraph

> The `simplebroker>=5.3.2` floor is load-bearing. Version 5.2.0 supplies the
> reference ownership model, 5.2.2 first passed Taut's persistent-owner
> process/control proof, 5.3.0 supplies the public live activity-waiter
> replacement contract, 5.3.1 makes `Queue.write()` return the exact committed
> message id, and 5.3.2 makes watcher bootstrap cancellation interrupt locked
> PhaseLock and SQLite connection setup. Persistent Queue handles for one
> resolved target share a process-local broker session; each driving thread
> receives its own thread-local backend core. Releasing an ordinary operation
> ends only its active-operation lease; it does not recycle the owning thread's
> cached core or end the Queue lease. `Queue.cleanup_connections()` explicitly
> recycles active handles while retaining the Queue lease, and `Queue.close()`
> ends the owned persistent lifetime. Taut follows the 5.2.0 reference-reactor
> rule: after drive begins, only the reactor owner performs normal Queue and
> sidecar work. Taut does not recreate SimpleBroker connection release or retry
> policy.

### [TAUT-8.3] dependency sentence replacement

> Core runtime dependencies: exactly `simplebroker>=5.3.2` and `psutil`. The
> optional `taut-pg` extension adds `simplebroker-pg` and its driver dependencies
> in the same environment as Taut. Python >= 3.11. The CLI uses argparse, not a
> CLI framework.

### [IAN-8.2] dependency paragraph replacement

> Taut requires `simplebroker>=5.3.2` and `taut-pg` requires
> `simplebroker-pg>=3.2.1`. This compatible pair supplies atomic write ids, the
> rename-capable backend handshake, safe persistent-reactor ownership, public
> live activity-waiter replacement, and interruptible watcher bootstrap during
> locked PhaseLock and SQLite connection setup. The implementation must use
> `simplebroker.open_broker(...).rename_queue(...)` against Taut's resolved
> broker target; it must not assume `Queue.rename()` or a module-level
> `simplebroker.rename_queue()` exists.

### [SUM-9] reactor-floor sentence replacement

> The control reactor follows SimpleBroker 5.2.0's reference
> persistent-session and thread-local-core ownership model, with SimpleBroker
> 5.3.2 or newer required for the supported reactor lane. Version 5.2.2 first
> proved persistent process visibility; 5.3.2 makes cancellation interrupt
> watcher bootstrap while PhaseLock or SQLite connection setup is blocked.
> Operation release ends only the active lease; the owner thread retains its
> core until explicit cleanup or close.

### [TAUT-12.5] batch and helper obligation replacements

> - `all` releases every requested package version that does not already have a
>   GitHub Release. With `--version X.Y.Z`, the helper prepares all three package
>   manifests at that coordinated version. Without `--version`, each package's
>   manifest remains the source for its current version. Package versions are
>   otherwise independent; consistency gates compare derived copies to the
>   manifest that owns them rather than requiring unrelated package versions to
>   match.

> - Before release, reject dirty worktrees unless `--dry-run` is set, reject or
>   exclude already-published GitHub Releases according to the existing single
>   target and resumable batch rules, and plan local/remote tag actions without
>   force-pushing tags. Validate the human-authored changelog heading before
>   generated metadata changes.
> - Prepare deterministic metadata before running release prechecks. Change
>   only selected package versions, but reconcile every manifest-owned derived
>   copy: the core constant, README tags and wheel names, both extension core
>   floors, root dev Summon and SimpleBroker PG floors, every exact root README
>   SimpleBroker requirement, and the retained Summon lock. Stage only the
>   release-file allowlist and create the local release-preparation commit
>   before prechecks. The prechecks verify that exact commit. `--checks-only`
>   remains non-mutating and reports drift; `--dry-run` prints the same prepare,
>   commit, verify, and remote-action order without writing.
> - Keep branch pushes, tag creation or replacement, tag pushes, and publication
>   after prechecks, normal artifact builds, and the paired core/Summon wheel
>   check. A writer or lock failure may leave only helper-generated working-tree
>   changes. A later proof failure leaves the local preparation commit unpushed
>   and the branch clean. The helper never resets or silently rolls back files.
>   Any `HEAD`, branch, index, or worktree drift after the preparation commit
>   stops the release before remote mutation.

Replace the existing local-gate obligation beginning “Run the relevant local
gates before mutation” with:

> - Run the relevant local gates against the clean local preparation commit and
>   before any branch push, tag creation or replacement, tag push, or
>   publication unless `--skip-checks` is set: root pytest,
>   `bin/pytest-pg --fast` for core or PG releases, the
>   `extensions/taut_summon/tests` suite for core or summon releases split into
>   non-process, deterministic `xdist_group` process, strict external-live, and
>   local-LLM lanes, Ruff over root plus touched extension paths, and split mypy
>   lanes so extension `conftest.py` modules do not collide. The existing lane
>   topology and local-LLM preparation rules remain unchanged.

The existing post-update obligation becomes:

> - After metadata preparation and prechecks, build the selected package
>   artifacts. The Summon lock has already been refreshed during preparation;
>   do not refresh or retain a PG lockfile.

Replace the paired-wheel ordering sentence in [TAUT-12.5] with:

> Every non-dry-run `core`, `summon`, or matching `all` release builds both
> wheels from the same clean preparation commit into a fresh temporary artifact
> root and runs the core/Summon wheel-matrix checker with their explicit paths
> after both builds and before any branch push, tag creation or replacement,
> tag push, or publication. The gate still runs under `--skip-checks`; dry-run
> prints the ordered build and verification commands. PG-only releases do not
> run it. Immediately before remote action, the helper verifies that the branch
> and `HEAD` still name the preparation commit, the index and worktree are
> clean, and fresh GitHub Release plus tag state remains compatible with the
> action. Branch and tag commands name the preparation commit explicitly;
> remote tag replacement deletes only the freshly inspected tag under an exact
> force-with-lease before pushing that explicit commit.

## Task Breakdown

1. Independent plan and spec-delta review.
   - Reviewer: Claude in read-only mode from `/Users/van/Developer` so the
     reviewer can inspect both Taut and sibling SimpleBroker 5.3.2 evidence.
   - Read: this plan, [TAUT-3.4]/[TAUT-8.3]/[TAUT-12.5], `bin/release.py`, both
     metadata/release test files, and SimpleBroker 5.3.2 changelog/tests.
   - Stop if version ownership, batch resume behavior, or failure residue is
     ambiguous.
   - Done: every finding is accepted, rejected with evidence, or marked out of
     scope, and the reviewer says the plan is implementable confidently.

2. Spec-promotion slice.
   - Files: `docs/specs/02-taut-core.md`,
     `docs/specs/03-identity-addressing-notifications.md`,
     `docs/specs/04-summon.md`, this plan.
   - Apply the reviewed exact delta and add the related-plan backlink.
   - Record promotion baseline as `2c7d9dc3 + worktree diff` unless a commit is
     explicitly requested.
   - Verify: `uv run --extra dev pytest -q tests/test_docs_references.py` and
     `git diff --check`.

3. Red tests for metadata ownership and preparation order.
   - Files: `tests/test_project_metadata_consistency.py`,
     `tests/test_release_script.py`.
   - Change fixture expectations first so each package version and the
     SimpleBroker README copy derive from the owning manifest.
   - Add a batch `--version` test that fails while the parser rejects it.
   - Add an event-order test proving version/README/floor writers, Summon lock,
     exact-path `git add`, and the local release commit run before prechecks,
     while builds run after prechecks and branch/tag pushes stay last.
   - Add a temporary-repository regression starting with a stale core constant,
   three stale version README copies, every stale SimpleBroker README copy,
   stale first-party floors, and a stale Summon
     lock. One normal invocation must repair and commit all derived state before
     invoking one precheck; a second invocation after a simulated proof failure
     must reuse that commit.
   - Add checks-only/dry-run and preparation-failure assertions. Do not mock the
     orchestration under test; mock only network state and external commands at
     the existing `run_command` seam.
   - Add mixed published/unpublished batch resume, all-published no-op,
     pre-write backdating refusal, and post-commit failed-check rerun cases.
     Preparation targets and publication candidates are separate: explicit
     `all --version` prepares all manifests when at least one target remains,
     while only unpublished candidates receive release actions.
   - Red command:
     `uv run --extra dev pytest -q tests/test_release_script.py tests/test_project_metadata_consistency.py`.

4. Implement one metadata preparation path.
   - File: `bin/release.py`.
   - Reuse `write_version_files()`, `sync_readme_version_examples()`, and the
     existing dependency sync path. Add the missing PG-floor wrapper over the
     same extension-floor writer; do not add parallel version/README writers.
   - Add `read_manifest_version()` for pre-repair planning and keep
     `read_current_version()` as the strict post-repair verifier. Add
     `sync_readme_simplebroker_requirement()` to read the one exact unmarked
     root manifest requirement and replace every exact requirement occurrence
     in the root README. Fail if no exact occurrence exists.
   - Split Summon `uv lock` from artifact build/check steps so it can run before
     the preparation commit exactly once for every normal target. Use
     `uv lock --upgrade-package simplebroker` so unrelated locked tools retain
     their existing pins.
   - Extend batch candidate resolution for optional explicit coordinated
     versions, with no backdating and resumable published-target handling.
   - Route normal single-target and batch releases through preparation plus one
     exact-path local commit before prechecks. Keep checks-only non-mutating and
     dry-run ordered.
   - After prechecks and artifact proof, require the current branch/HEAD to
     remain the clean preparation commit and freshly inspect GitHub Release plus
     local/remote tag state before planning or performing remote actions.
   - Stop if the change needs hidden git rollback, a second release entry point,
     or changes tag/publish semantics beyond the promoted delta.

5. Reconcile current metadata and durable documentation.
   - Files: `tests/test_project_metadata_consistency.py`, README files as
     generated by the helper path, `docs/implementation/04-taut-architecture.md`,
     `docs/implementation/02-repository-map.md` only if its ownership summary
     changes, `docs/lessons.md`, this plan.
   - Update SimpleBroker 5.3.2 rationale and describe preparation-before-gates.
   - Record the durable lesson: a consistency test should verify derived state,
     while the owning workflow generates it before invoking the gate.
   - Evaluate the diagnosing-bugs skill and release runbooks for a reusable gap;
     update only if the omission is broader than this repository.

6. Verification and completed-work review.
   - Run focused tests, release dry-run probes, docs references, Ruff, mypy, and
     `git diff --check`.
   - Run the current metadata test against the prepared worktree and show it
     green.
   - Run a read-only independent completed-work review with spec, plan, diff,
     and command evidence. Reproduce findings before changing code.
   - Do not invoke a non-dry release, create commits, create tags, or push.

## Testing Plan

The contract seam is `release.main()` with existing command/network boundaries
replaced, plus a real temporary filesystem for writer helpers. Tests must prove:

- `all --version 0.6.2` is accepted and prepares core, PG, and Summon versions;
- target-specific versions remain independent and their README/lock copies use
  the correct manifest owner;
- every target reconciles all derived copies without changing unselected
  manifest versions;
- the core constant follows only the core manifest;
- both first-party dependency directions are prepared before pytest;
- every exact root README SimpleBroker requirement follows the root manifest,
  and no stale SimpleBroker floor remains, rather than treating any literal in
  the test as the source;
- Summon `uv lock` precedes pytest and runs once;
- the exact-path local preparation commit precedes pytest;
- builds and paired-wheel verification follow pytest and do not change tracked
  release files;
- changelog/publication/dirty-state failures occur before writes;
- checks-only writes nothing; dry-run prints but writes nothing;
- a writer/lock failure runs no commit or remote action;
- a precheck/artifact failure leaves the local commit but runs no branch push,
  tag mutation, tag push, or publication;
- unrelated dirty files are never included in the preparation commit;
- a stale core constant is repaired from the root manifest instead of blocking
  planning;
- selective lock refresh updates SimpleBroker and local editable versions but
  does not upgrade unrelated locked tools;
- mixed published/unpublished batch resume prepares all requested manifests but
  acts remotely only on unpublished candidates;
- backdating and all-published explicit batches perform no writes;
- rerunning after a post-commit proof failure reuses the clean preparation
  commit rather than creating an empty or duplicate commit;
- branch, `HEAD`, index/worktree, GitHub Release state, and local/remote tag
  state are revalidated after the long checks and before remote action.

Do not run real GitHub calls, tag pushes, or local-LLM setup in unit tests. Do
use real TOML/README/lock-shaped temp files for pure writers. The final dry-run
probe uses the shipped CLI entry point.

## Verification Gates

Focused:

```text
uv run --extra dev pytest -q tests/test_release_script.py tests/test_project_metadata_consistency.py
uv run --extra dev pytest -q tests/test_docs_references.py tests/test_github_workflows.py
uv run --extra dev ruff check bin/release.py tests/test_release_script.py tests/test_project_metadata_consistency.py
uv run --extra dev ruff format --check bin/release.py tests/test_release_script.py tests/test_project_metadata_consistency.py
uv run --extra dev mypy bin/release.py tests/test_release_script.py tests/test_project_metadata_consistency.py --config-file pyproject.toml
git diff --check
```

Black-box and self-application probes:

```text
uv run --extra dev python bin/release.py all --version 0.6.1 --dry-run --skip-checks
uv run --extra dev python bin/release.py all --checks-only
```

The first must show preparation, lock, exact-path local commit, prechecks when
not skipped, builds, paired check, then branch/tag push previews with no
traceback or mutation. The
second is intentionally run only after the current worktree has been prepared;
it must execute real checks and remain non-mutating. If the full checks-only
gate is too long for this slice, report it as unrun rather than treating a
dry-run as proof.

Final broader gate, proportional to the release boundary:

```text
uv run --extra dev pytest -q tests/test_release_script.py tests/test_project_metadata_consistency.py tests/test_core_summon_wheel_matrix.py tests/test_github_workflows.py tests/test_docs_references.py
```

## Independent Review Loop

Plan review prompt:

> Read `taut/docs/plans/2026-07-13-release-metadata-preparation-plan.md`, its
> Proposed Spec Delta and promotion strategy, the named Taut spec/code/tests,
> and sibling SimpleBroker 5.3.2 evidence. Look for errors, bad ideas, hidden
> coupling, destructive failure behavior, and tests that would pass without
> proving the reported serial-failure problem. Do not implement. Could you
> implement this confidently and correctly after the delta is promoted?

Completed-work review uses the same stance plus the final diff and verification
evidence. Findings and dispositions are recorded below.

## Out of Scope

- Inventing changelog prose, deriving release notes from commits, or changing
  changelog format.
- Publishing, tagging, pushing, or committing the current 0.6.1 work.
- PyPI support, tag namespace changes, workflow publication redesign, or
  immutable release policy changes.
- Replacing TOML regex writers with a new dependency or general template
  engine.
- Retaining the PG lockfile or broad dependency upgrades beyond the already
  selected SimpleBroker 5.3.2 floor.
- Weakening artifact compatibility floors or removing paired wheel tests.

## Deviation Log

| Spec ref | Planned behavior | Actual behavior | Rationale | Spec proposal |
|----------|------------------|-----------------|-----------|---------------|

## Review Findings and Dispositions

Plan review used a same-family independent read-only reviewer after two Claude
review invocations passed a short read probe but hung without findings. This is
the fallback allowed by
`docs/agent-context/runbooks/review-loops-and-agent-bootstrap.md`.

| Finding | Disposition |
|---------|-------------|
| P1: proposed [TAUT-12.5] text left existing “before mutation” and “before any release commit” clauses contradictory | Accepted. Added exact replacement text distinguishing the local preparation commit from remote mutation; Task 5 also updates the implementation note. |
| P1: planning uses `read_current_version()` and would reject a stale derived core constant before repair; no README SimpleBroker writer was named | Accepted. Added manifest-only planning, strict post-repair verification, and an explicit manifest-to-README requirement writer with firing tests. |
| P1: release-file drift alone does not fence the tested SHA or refreshed remote state | Accepted. Added branch/HEAD, full clean-tree, GitHub Release, and local/remote tag-state revalidation immediately before remote action. |
| P2: plain `uv lock` silently upgraded unrelated tools in `2c7d9dc3` | Accepted. Historical `uv lock --dry-run --upgrade-package simplebroker` at `9671d1f1` resolved only `simplebroker 5.3.1 -> 5.3.2`, local `taut 0.6.0 -> 0.6.1`, and local `taut-summon 0.6.0 -> 0.6.1`; the plan now requires that selective command and a command-shape test. |
| P2: missing resume/backdating/all-published and multi-stale-copy proof | Accepted. Added those cases and separated preparation targets from publication candidates. |
| P2: SimpleBroker README synchronization did not require replacing every exact occurrence | Accepted. The writer now owns every exact root README requirement occurrence, fails when none exists, and the regression proves no stale floor remains. |
| Research audit recommended a separate prepare-only mode to avoid mutation authority and dirty failure residue | Rejected after explicit user direction. Invoking the release command authorizes deterministic writes and a local exact-path commit. The revised flow commits preparation before checks, so later proof failure leaves a clean rerunnable local commit while remote actions remain fenced. |
| Completed-work P2: mixed published/unpublished batch resume was tested only through candidate discovery, so the test would not fire if `main()` stopped preparing the already-published target's manifest | Accepted. Replaced the helper-only assertion with a public `main(["all", "--version", "0.6.0", "--skip-checks"])` orchestration test. It executes the real reconciler with observed writers, proves all three manifests are prepared, and proves only unpublished candidates reach builds and tag actions. |
| Completed-work rereview | No findings. The reviewer reran the focused regression, all 70 release-script tests, Ruff, mypy, and `git diff --check`; the prior P2 is closed and the verdict is implementation-ready. |

## Execution Evidence

| Slice | Command | Observed result | Residual risk |
|-------|---------|-----------------|---------------|
| Reproduction | `uv run --extra dev pytest -q tests/test_project_metadata_consistency.py` | `1 passed, 1 failed`; README still pins `0.6.0` while the root manifest is `0.6.1` | Earlier serial failures reconstructed from committed diffs rather than retained pytest output |
| Selective lock probe | Historical checkout `9671d1f1`: `uv lock --dry-run --upgrade-package simplebroker --directory <temp>/extensions/taut_summon` | Updated only SimpleBroker `5.3.1 -> 5.3.2` and local editable Taut/Summon `0.6.0 -> 0.6.1`; no unrelated tool upgrades | `uv` resolver behavior remains an external tool contract, pinned by the release command-shape test and lock diff review |
| Spec promotion | `uv run --extra dev pytest -q tests/test_docs_references.py && git diff --check` | `10 passed`; diff whitespace check passed | Promotion is an uncommitted worktree diff by user choice, so baseline is `2c7d9dc3 + worktree diff` |
| Focused release behavior | `uv run --extra dev ruff format --check bin/release.py tests/test_release_script.py tests/test_project_metadata_consistency.py && uv run --extra dev ruff check bin/release.py tests/test_release_script.py tests/test_project_metadata_consistency.py && uv run --extra dev mypy bin/release.py tests/test_release_script.py tests/test_project_metadata_consistency.py --config-file pyproject.toml && uv run --extra dev pytest -q tests/test_release_script.py tests/test_project_metadata_consistency.py` | Formatting, lint, and types passed; `72 passed` | Unit seams fake external publication and build commands, but the orchestration regression uses a real temporary Git repository, real writers, and real exact-path add/commit |
| Mixed published/unpublished batch firing proof | Focused Ruff, mypy, and `uv run --extra dev pytest -q tests/test_release_script.py tests/test_project_metadata_consistency.py` after completed-work review | Public `main()` proof passed within the `72` focused tests; all manifests were observed at `0.6.0`, while published PG received no build or tag action | External GitHub state is represented by deterministic `ReleaseState` fixtures; fresh-state reinspection is still exercised |
| Broader release and documentation regression | `uv run --extra dev pytest -q tests/test_release_script.py tests/test_project_metadata_consistency.py tests/test_core_summon_wheel_matrix.py tests/test_github_workflows.py tests/test_docs_references.py && git diff --check` | `157 passed`; diff whitespace check passed | None observed |
| Full root test gate | `uv run --extra dev pytest -q` | Full root suite passed | Provider-backed and local-model checks remain environment-specific and are not part of this default pytest lane |
| Full lint and type lanes | Root `ruff check`, root `ruff format --check`, root `mypy`, PG `mypy`, and Summon `mypy` commands from the release gate | All passed; Ruff reported `123 files already formatted`, and mypy checked 77 root, 6 PG, and 37 Summon source files | None observed |
| Non-mutating release plan | `uv run --extra dev python bin/release.py all --version 0.6.1 --dry-run --skip-checks` | Printed reconcile, selective lock, exact eight-path add/commit, builds, paired-wheel proof, fresh-state fence, and explicit tested-SHA branch/tag operations in order; made no writes | Dry-run cannot prove external registry or GitHub behavior |
| Remote tag lease syntax | Temporary bare Git remote with a lightweight tag; `git push --force-with-lease=refs/tags/v1:<old-oid> origin :refs/tags/v1` | Command succeeded and the remote tag was absent afterward | Git hosting policy may still reject tag deletion; failure is safe because the lease prevents deleting an unexpected tag |
| Full `all --checks-only` | Not run | The path is covered by firing non-mutation tests; equivalent default pytest, lint, type, docs, and dry-run gates passed independently | The aggregate command also invokes strict environment-dependent provider/local-model checks, so this work does not claim a live external integration run |

## Fresh-Eyes Checklist

- [x] Current owners and helper functions are named.
- [x] Spec baseline, exact delta, promotion strategy, and promotion gate exist.
- [x] Authorized local preparation/commit is separated from remote branch/tag
  push and publication boundaries.
- [x] Pre-commit failure residue, clean post-commit proof failure, and rollback
  are explicit.
- [x] Tests keep the real orchestration seam and mock only external boundaries.
- [x] Changelog ownership and retained/ignored lock boundaries are explicit.
- [x] No dependency, second release path, or speculative template system is
  introduced.
