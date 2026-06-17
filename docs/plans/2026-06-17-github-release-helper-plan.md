# GitHub Release Helper Plan

Date: 2026-06-17
Status: Complete.

## 1. Goal

Add a repo-local release helper for taut that mirrors the SimpleBroker/Weft
release-helper discipline while keeping taut's current distribution boundary:
GitHub Releases only until the PyPI `taut` name is cleared. The helper should
make the release flow repeatable, testable, and hard to misuse.

## 2. Source Documents

Source spec: None — repository tooling change.

Source references:

- `../simplebroker/bin/release.py` — multi-target release-helper pattern.
- `../weft/bin/release.py` — single-root release-helper pattern with GitHub
  release gate.
- `README.md` — current distribution status and PyPI-name blocker.
- `docs/implementation/04-taut-architecture.md` — release/verification gates.

## 3. Context and Key Files

Files to add or update:

- `bin/release.py` — new repo-local helper.
- `tests/test_release_script.py` — typed unit tests for release-helper logic.
- `docs/implementation/02-repository-map.md` — mention the new helper.
- `docs/implementation/04-taut-architecture.md` — mention release helper and
  GitHub-only publication boundary.
- `README.md` — fix any stale dependency/publication wording surfaced while
  adding the helper.
- `pyproject.toml` — include `bin` in ruff/mypy scope if needed.

Current state:

- taut has `pyproject.toml` version and `taut/_constants.py` version; they
  must match.
- The local tag has been normalized to the sibling convention `v0.1.1`; origin
  has no tags.
- PyPI publication is blocked by the existing `taut` placeholder package. The
  helper must not upload to PyPI or treat PyPI publication as the expected path.

## 4. Invariants and Constraints

- No PyPI upload path in this helper. `--publish` may exist only as a
  compatibility no-op that explains GitHub-only release.
- Tags use `vX.Y.Z`; do not introduce a second tag naming convention.
- The helper must refuse dirty release files. It may coexist with unrelated
  dirty files, but a real release should require a clean worktree unless the
  dirty files are explicitly ignored by design.
- Version changes must update `pyproject.toml` and `taut/_constants.py`
  together.
- Prechecks must match the local release gate: pytest, ruff check, ruff format
  check, mypy over `taut`, `tests`, and `bin/release.py`, and `uv build`.
- Tests for the helper should mock network/git boundaries but exercise the real
  helper functions.

## 5. Tasks

1. Add the release helper.
   - Files: `bin/release.py`.
   - Reuse the Weft shape where it fits: version parsing, `ReleaseState`,
     GitHub API release lookup, local/remote tag inspection, tag-action
     planning, dry-run output, command runner.
   - Keep only taut's single package target and GitHub-only publication note.
   - Done: `python bin/release.py --help` works and dry-run prints the planned
     `vX.Y.Z` tag action.

2. Add release-helper tests.
   - Files: `tests/test_release_script.py`.
   - Cover version validation, version sync mismatch, version file updates, tag
     names, tag-action decisions, GitHub slug parsing, and `--publish` no-op
     behavior.
   - Done: focused test file passes and is included in mypy.

3. Update docs and release metadata.
   - Files: `README.md`, implementation docs, repository map, this plan.
   - Fix stale "one-dependency" roadmap wording if still present.
   - Clarify GitHub-only release helper boundary.
   - Done: docs mention `bin/release.py` and do not imply PyPI is clear.

4. Normalize the local release tag.
   - Replace local `0.1.1` with `v0.1.1` only after tests prove the helper
     expects `vX.Y.Z` tags. Origin currently has no tags.
   - Done: `git tag --points-at HEAD` shows `v0.1.1`, not `0.1.1`.

## 6. Testing Plan

- Unit-test helper logic in `tests/test_release_script.py`.
- Keep git/network calls mocked at the helper-function boundary; do not run
  real tag pushes in tests.
- Runtime proof:
  - `python bin/release.py --help`
  - `python bin/release.py --dry-run`
  - `uv run pytest tests/test_release_script.py -q -n 0`
  - full suite and static gates.

## 7. Verification and Gates

Final gates:

```bash
uv run pytest
uv run ruff check taut tests bin
uv run ruff format --check taut tests bin
uv run mypy taut tests bin/release.py
uv build
python bin/release.py --dry-run
```

## 8. Independent Review Loop

Run a focused read-only review after implementation if available:

> Review the new taut GitHub-only release helper against
> `docs/plans/2026-06-17-github-release-helper-plan.md`,
> `../simplebroker/bin/release.py`, and `../weft/bin/release.py`. Look for
> release-footguns, PyPI leakage, weak tests, and tag-state mistakes. Do not
> edit files.

Review result: subagent delegation was unavailable under the active tool policy
without an explicit user request. A focused read-only review found one real
release-footgun: a failed `git ls-remote` was treated as a missing remote tag.
That now fails early, with a typed regression test.

## 10. Completion Evidence

- Added `bin/release.py` with a single taut target, `vX.Y.Z` tag planning,
  GitHub Release state lookup, typed/lint/build gates, dry-run output, and a
  `--publish` compatibility no-op that states PyPI is disabled.
- Added `tests/test_release_script.py` with typed tests for version parsing,
  version sync, annotated `__version__` updates, GitHub-only release state,
  tag-action decisions, remote inspection failure, GitHub slug parsing, release
  gates, and `--publish` behavior.
- Updated README, changelog, repository map, architecture docs, and spec
  backlinks for the GitHub-only release boundary.
- Verification:
  - `uv run pytest` -> 61 passed.
  - `uv run ruff check taut tests bin` -> passed.
  - `uv run ruff format --check taut tests bin` -> passed.
  - `uv run mypy taut tests bin/release.py` -> passed.
  - `uv build` -> built `taut-0.1.1.tar.gz` and `taut-0.1.1-py3-none-any.whl`.
  - `python bin/release.py --dry-run` -> planned `v0.1.1` GitHub tag flow and
    printed PyPI disabled note.

## 9. Out of Scope

- PyPI upload, Trusted Publishing, or name-clearance automation.
- GitHub Actions workflow implementation. The helper may name a future
  `.github/workflows/release-gate.yml`, but this plan does not add CI.
- Package rename or transfer decision.
