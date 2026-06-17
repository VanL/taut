# GitHub Actions Release Workflows Plan

Date: 2026-06-17
Status: Complete.

## 1. Goal

Add GitHub Actions workflows for taut that match the SimpleBroker/Weft release
discipline while preserving taut's current publishing boundary: GitHub Releases
only, no PyPI upload until the package-name request is cleared.

## 2. Source Documents

- `../simplebroker/.github/workflows/test.yml`
- `../simplebroker/.github/workflows/release-gate.yml`
- `../weft/.github/workflows/test.yml`
- `../weft/.github/workflows/release-gate.yml`
- `../weft/.github/workflows/release.yml`
- `docs/plans/2026-06-17-github-release-helper-plan.md`
- `docs/implementation/04-taut-architecture.md`

## 3. Current State

- The repository has GitHub Actions workflows for test, release gate, and
  GitHub Release publication.
- `bin/release.py` pushes `vX.Y.Z` tags, checks for an existing GitHub Release,
  and keeps dry-run detached tag testing separate from real release rejection.
- `v0.1.1` points at the tested release commit and has a published GitHub
  Release.
- PyPI is still unavailable for taut, so release automation must not contain a
  PyPI publish job, Trusted Publishing environment, or package-index upload
  step.
- The Windows test matrix exposed portability gaps in identity discovery,
  terminal fallback handling, CLI stdout encoding, and POSIX-only tests. Those
  were fixed as part of this release workflow slice.

## 4. Invariants

- Release publishing means creating a GitHub Release and uploading built
  artifacts; it does not mean PyPI.
- A release tag must still point at the tested commit immediately before
  publication.
- The same test workflow must be usable from normal push/PR events and from
  the tag release gate.
- CI gates must include pytest, ruff check, ruff format check, mypy, and build.
- Runtime/package code must remain installable on Windows if Windows is in the
  test matrix.

## 5. Tasks

1. Add reusable CI workflow.
   - File: `.github/workflows/test.yml`.
   - Run test matrix across Python 3.11-3.14 on Linux, macOS, and Windows.
   - Run lint, format, mypy, and packaging smoke on Ubuntu.
   - Expose `workflow_call` so the release gate can call the exact same gates.

2. Add release workflows.
   - Files: `.github/workflows/release-gate.yml`,
     `.github/workflows/release.yml`.
   - `release-gate.yml` runs on `v*` tags, calls the reusable test workflow,
     verifies the tag did not move, then calls `release.yml`.
   - `release.yml` builds artifacts from the tagged commit, verifies the tag,
     and creates a GitHub Release with the sdist and wheel.
   - No PyPI jobs.

3. Fix Windows import portability exposed by the matrix.
   - Files: `taut/identity.py`, `tests/test_identity.py`.
   - Make `pwd` optional and prove the fallback path.

4. Update docs.
   - Files: README, repository map, architecture docs, related plans.
   - Clarify that tag pushes now publish GitHub Releases through Actions.

## 6. Verification

Planned local gates:

```bash
uv run pytest
uv run ruff check taut tests bin assets/gen_taut_logo.py generate_knot.py
uv run ruff format --check taut tests bin assets/gen_taut_logo.py generate_knot.py
uv run mypy taut tests bin/release.py
uv build
python -m py_compile taut/identity.py tests/test_identity.py
```

Workflow gates:

```bash
python - <<'PY'
from pathlib import Path
import yaml
for path in Path('.github/workflows').glob('*.yml'):
    yaml.safe_load(path.read_text())
PY
```

If pushed in this turn, observe the Test workflow and any tag-triggered release
gate with `gh run list`.

Observed local evidence:

```bash
uv run pytest
# 69 passed

uv run ruff check taut tests bin assets/gen_taut_logo.py generate_knot.py
# passed

uv run ruff format --check taut tests bin assets/gen_taut_logo.py generate_knot.py
# 25 files already formatted

uv run mypy taut tests bin/release.py --config-file pyproject.toml
# Success: no issues found in 23 source files

uv build
# Built taut-0.1.1.tar.gz and taut-0.1.1-py3-none-any.whl

uv run python bin/release.py --retag
# Re-ran local release gates, pushed main, force-updated v0.1.1 to the tested
# commit, and triggered the tag release gate. PyPI remained disabled.
```

Observed hosted evidence:

- Test workflow run `27700415360`: success across lint, packaging, Ubuntu
  Python 3.11-3.14, Windows Python 3.11-3.14, and macOS Python 3.13-3.14.
- Release Gate workflow run `27700556933`: success. It called the reusable test
  workflow, verified the tag, built release artifacts, verified the tag again,
  and uploaded the artifacts to a GitHub Release.
- GitHub Release:
  `https://github.com/VanL/taut/releases/tag/v0.1.1`
  - `taut-0.1.1-py3-none-any.whl`
  - `taut-0.1.1.tar.gz`

Hosted failures before the final green run were useful gates rather than
ignored noise: they caught detached-head release dry-run behavior, Windows
`psutil` terminal fallback handling, legacy stdout encoding, POSIX-only test
assumptions, and timing-sensitive concurrent writer tests.

Post-release follow-up:

- Test workflow run `27700821362` was cancelled after two runners wedged in the
  `Install uv` setup action before taut code ran. The workflows already had job
  timeouts, but they were too coarse for this failure mode. Setup, build,
  verification, and publish steps now have explicit step-level timeouts.

## 7. Rollback

Remove the new `.github/workflows/*.yml` files and revert the small optional
`pwd` import fallback if the workflow surface misbehaves. If a release tag
publishes an incorrect GitHub Release, delete the GitHub Release first, then
move or delete the tag according to the release-helper retag policy.

## 8. Out of Scope

- PyPI upload, Trusted Publishing, or name-clearance automation.
- Dependabot, CodeQL, Scorecard, or Codecov.
- Changing the release helper's CLI shape beyond documentation text needed to
  acknowledge the workflow.
