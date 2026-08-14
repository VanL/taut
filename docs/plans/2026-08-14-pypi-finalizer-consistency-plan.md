# PyPI Finalizer Consistency Plan

Date: 2026-08-14

Class: 5. This revises the normative [TAUT-12.5] publication contract after a
real coordinated release exposed an invalid cross-runner consistency
assumption at the irreversible PyPI/GitHub boundary.

Status: completed.

Plan type: implementation with spec revision.

## Goal

Make each independent GitHub-release finalizer boundedly observe the complete
exact PyPI file set before publishing an immutable GitHub Release. Preserve
immediate failure for unexpected files or digest mismatches and preserve
byte-identical resumability after PyPI has already succeeded.

## Source Documents

- `docs/specs/02-taut-core.md` [TAUT-12.5]
- `docs/implementation/04-taut-architecture.md`
- `docs/implementation/02-repository-map.md`
- `docs/agent-context/runbooks/testing-patterns.md`
- `docs/agent-context/runbooks/hardening-plans.md`
- `docs/lessons.md`

## Spec Baseline

- `24dc2bc073d21adbdeaa24e4bbdc7192b84ea2a4` — [TAUT-12.5] assigns the
  bounded PyPI visibility wait only to the publisher job and requires the
  independent finalizer to perform one exact read.

Promotion baseline: `24dc2bc` plus the current [TAUT-12.5], architecture,
repository-map, and lessons diff. The promoted contract requires an independent
bounded exact observation in each runner.

## Context and Key Files

- `.github/scripts/release_publication.py::verify_pypi` already owns the
  bounded `absent`/matching-`partial` to exact-`complete` convergence loop.
- `finalize_release` deliberately passes `retry_delays=()`, so a fresh runner
  can fail on one CDN `404` even after the publisher job observed completion.
- `tests/test_release_publication.py` owns the pure state-machine and finalizer
  orchestration proofs.
- `.github/workflows/release-finalize.yml` remains a thin caller; do not add a
  shell retry or a second implementation there.

Observed production evidence: TUI release-gate run `31831944421` attempt 1
published both exact `taut-tui==0.9.0` files to PyPI, then its independent
finalizer saw `absent` on one read about nine seconds later and correctly left
the GitHub Release as a draft.

## Invariants and Constraints

- One Python helper remains the sole PyPI filename/digest verifier and retry
  owner.
- Only `absent` and exact matching `partial` states are retryable. Unexpected
  files, mismatched digests, malformed responses, auth failures, and other
  network/API failures remain immediately fatal.
- The finalizer must not publish GitHub until its own observation is complete;
  a prior job's observation is evidence, not shared cache state.
- Retry bounds remain the existing `PYPI_RETRY_DELAYS`; this change does not
  extend them or add sleeps to successful paths.
- Immutable GitHub publication remains the one-way door. It stays strictly
  after this finalizer's own exact PyPI observation and exact draft-asset
  verification.
- Reruns reuse only exact manifest-bound bytes. No rebuild, retag, or
  `skip-existing` weakening is permitted.
- Tests call the real finalizer/verification functions with controlled remote
  observations. Workflow-only string assertions are insufficient.

## Proposed Spec Delta

Revise [TAUT-12.5] so the publisher job and the independent finalizer each run
the bounded exact PyPI convergence check. Explain that successful completion
in one runner does not make a later CDN observation linearizable. Keep the
same retryable states and immediate-fatal mismatch rules.

## Execution Slices

1. Change both finalizer orchestration branches first so draft publication and
   already-public immutable rerun each require the default bounded verifier
   policy; run both red against their independent explicit empty-delay calls.
   Retain the helper's absent-to-partial-to-complete sleep proof and its
   immediate-fatal mismatch coverage.
2. Promote the [TAUT-12.5] delta, align architecture/repository-map text, and
   record the durable lesson that each remote observer must establish its own
   bounded convergence; another runner's success is not transferable cache
   consistency evidence.
3. Remove the empty-delay override from both draft and immutable-rerun paths;
   reuse `verify_pypi` unchanged.
4. Run publication tests, workflow tests, Ruff, format, all five mypy lanes,
   doc paths, plan index, and diff checks.
5. Independently review the state boundary and tests, then commit and push.
6. Record the already-completed 0.9.0 exact-artifact recovery, then verify all
   five GitHub/PyPI releases, hashes, and Sigstore attestations. Do not start a
   third TUI attempt.

## Rollout and Recovery

The 0.9.0 TUI retry executes immutable code at its existing tag and therefore
tests the already-specified resumable path, not this fix. The fix applies to
future tags. If it regresses before another tag, revert the main-branch commit;
published 0.9.0 bytes and tags are unaffected.

The next future package tag gate is the hosted post-deploy signal: every
finalizer must preserve exact mismatch failures while avoiding a false
single-read `absent` failure. Local deterministic branch-exhaustive tests are
the implementation proof until that future tag exists.

## Out of Scope and Stop Gates

- No workflow or shell retry; no retry-constant or job-timeout increase.
- No new retryable error class. Network errors, malformed responses,
  unexpected files, and digest mismatches stay immediately fatal.
- No changed artifact bytes, tags, rebuilds, or `skip-existing` behavior.
- Stop and re-plan if implementation must change `verify_pypi`, workflow
  topology/timeouts, mismatch policy, or any file beyond the two finalizer
  overrides, tests, and aligned documentation.

## Verification

- Red/green: `uv run --no-sync pytest tests/test_release_publication.py -q -n 0`
- Workflow contracts: `uv run --no-sync pytest tests/test_github_workflows.py -q -n 0`
- Quality: repository-wide Ruff format/lint and all five release-owned mypy
  commands.
- Docs: `uv run --no-sync bin/check-doc-paths` and
  `uv run --no-sync bin/check-plan-status-index`.
- Recovery evidence already observed: run `31831944421` attempt 2 completed
  successfully using immutable tag code, exact existing PyPI bytes, and the
  existing draft. This proves resumability only, not the new fix.
- Hosted post-deploy signal: the next future package tag gate, as described in
  Rollout and Recovery.

## Deviation Log

| Spec ref | Planned behavior | Actual behavior | Rationale | Spec proposal |
|----------|------------------|-----------------|-----------|---------------|

## Review Log

- Independent plan review found three blockers: branch-exhaustive finalizer
  tests, stale recovery sequencing, and missing Class-5 hardening/lesson gates.
  All three were adopted before implementation.
- Independent completed-work review found no P1/P2 blocker. It confirmed that
  both branches use the unchanged semantic verifier, both prior empty-delay
  paths have firing tests, and no timeout, retry class, workflow, artifact, tag,
  or mismatch policy changed.

## Execution Log

- Both branch-exhaustive orchestration tests failed red against the two
  explicit empty-delay overrides, observing `()` instead of
  `PYPI_RETRY_DELAYS`.
- Promoted the independently bounded finalizer observation contract to
  [TAUT-12.5] and aligned architecture, repository ownership, and the durable
  cross-runner consistency lesson before changing production code.
- Removed only the two empty-delay finalizer overrides. Publication and workflow
  tests passed 67 cases. Repository-wide Ruff passed across 390 files; the five
  release-owned mypy lanes passed 132, 12, 40, 21, and 31 source files. Doc
  paths passed 63 sources and 1,270 path claims; plan index and diff checks
  passed.
- Recorded 0.9.0 recovery without a third attempt: TUI run `31831944421`
  attempt 2 succeeded against the immutable tag and existing bytes. All five
  remote tags resolve to `24dc2bc073d21adbdeaa24e4bbdc7192b84ea2a4`;
  four exact-SHA producer runs and five tag gates are green. All five GitHub
  Releases are public and immutable. PyPI has exactly the expected two
  non-yanked files per project, all ten hashes match GitHub, and all ten files
  carry exact Sigstore attestations for `VanL/taut`, environment `pypi`, and
  their package release-gate workflow.
- The hosted proof of the changed finalizer remains the next future package tag,
  as required by Rollout and Recovery. This is post-deploy evidence, not a
  reason to mislabel the unchanged 0.9.0 rerun as proof of the fix.
