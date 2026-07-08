# 2026-07-08 Release Helper SimpleBroker Port Plan

## Goal

Port the relevant SimpleBroker release-helper behavior into Taut while keeping
Taut's release boundary GitHub-only.

## Scope

- Extend `bin/release.py` from a single-target helper to a target-aware helper
  with `core`, `pg`, `summon`, and `all`.
- Preserve the older `--target pg` form while adding positional targets.
- Add the `taut-summon` release target and its `taut_summon/vX.Y.Z` tag
  namespace.
- Add batch discovery for current unpublished package versions.
- Track release files across selected targets, including
  `extensions/taut_summon/uv.lock`.
- Sync first-party dependency floors:
  - extension `taut>=...` floors to the current root version
  - root `taut-summon>=...` dev dependency to the local summon extension
    version
- Add the summon GitHub release gate.
- Document the release machinery in the core spec.

## Boundaries

- Do not port SimpleBroker's PyPI publication checks or Trusted Publishing
  behavior. Taut remains GitHub-only until the spec changes.
- Do not add backend API invariant checks. Taut does not own SimpleBroker's
  backend plugin API.
- Do not change package runtime dependencies.

## Invariants

- Root tags remain `vX.Y.Z`.
- `taut-pg` tags remain `taut_pg/vX.Y.Z`.
- `taut-summon` tags are `taut_summon/vX.Y.Z`.
- `all` must not accept `--version`; version files are the source of truth for
  batch releases.
- Release workflows must verify tag stability before publishing artifacts.
- No workflow may upload to PyPI.

## Verification

- `uv run pytest tests/test_release_script.py tests/test_github_workflows.py`
- `uv run pytest tests/test_docs_references.py`
- `uv run --extra dev ruff check bin/release.py tests/test_release_script.py tests/test_github_workflows.py`
- `uv run --extra dev ruff format --check bin/release.py tests/test_release_script.py tests/test_github_workflows.py`
- `uv run --extra dev mypy bin/release.py tests/test_release_script.py tests/test_github_workflows.py --config-file pyproject.toml`
- `uv run python bin/release.py all --dry-run --skip-checks`

## Implementation Log

- 2026-07-08: Release retry exposed intermittent SQLite malformed-page/disk I/O
  failures when deterministic summon process tests, external live harnesses,
  and the local-LLM PTY proof all ran inside one long one-worker xdist
  invocation. The release helper now keeps local LLM preparation backgrounded
  from the start, but splits summon checks into fresh one-worker pytest
  invocations: unit, deterministic process, strict external-live, and local-LLM.
