# Single Project Configuration Source Spec Plan

Date: 2026-07-14

Status: implemented and verified. Independent review passed. The repository
owner authorized inclusion in 0.6.4 on 2026-07-14.

Plan type: Spec-authoring clarification of shipped behavior

## Goal

Make Taut's project-configuration boundary explicit: default SQLite requires
no config file, `.taut.toml` is the only project file Taut reads as project
configuration, Postgres requires it, and Taut does not inspect or combine Taut
settings from other project files.

## Source Documents

- `docs/specs/02-taut-core.md` [TAUT-2], [TAUT-3.2]
- `README.md` "Features", "Postgres Extension", and "Trust Model"
- `docs/agent-context/runbooks/writing-specs.md`

## Context and Key Files

- `docs/specs/02-taut-core.md` owns the product storage and project-resolution
  contract.
- `taut/_constants.py::load_config` pins SimpleBroker project discovery to
  `.taut.toml`.
- `taut/terminal.py::_find_project_config` reads only `.taut.toml` for
  Taut-owned terminal presentation policy.
- `tests/test_project_config.py` proves SQLite `.taut.toml` selection and that
  `.broker.toml` cannot redirect Taut.

## Invariants and Constraints

- Preserve the zero-config default SQLite path and existing Postgres door.
- Preserve the requirement that a `.taut.toml` used for normal project
  discovery contains `version`, `backend`, and `target`.
- Do not add `pyproject.toml`, arbitrary TOML scanning, or cross-project-file
  settings merging.
- Do not treat a settings-only `.taut.toml` as a valid storage-discovery
  configuration. Preserve its existing presentation-only use under
  [TAUT-6.4], including with an explicit storage selector.
- Do not change explicit `--db`, `TAUT_DB`, or API `db_path=` semantics.
- Preserve unrelated terminal-output-safety edits already present in the
  worktree.
- Add no dependency and make no runtime implementation change.

## Spec Baseline

- Commit `88f1b9a11e8dd183a135c5dce2c4db2582eea561` plus the existing dirty
  worktree. `docs/specs/02-taut-core.md` already contains uncommitted
  terminal-output-safety work and the status correction; this plan changes
  only [TAUT-2], [TAUT-3.2], and the related-plan backlink.
- Promotion baseline: commit
  `88f1b9a11e8dd183a135c5dce2c4db2582eea561` plus the dirty worktree after
  applying the exact [TAUT-2]/[TAUT-3.2] delta and related-plan backlink on
  2026-07-14. The promoted delta is identified by
  `git diff -- docs/specs/02-taut-core.md` and remains uncommitted.

## Proposed Spec Delta

Promotion strategy: spec-authoring in-place edit. The spec is the primary
deliverable; there is no dependent runtime implementation slice.

### [TAUT-2] replacement

Replace the absolute-sounding SQLite `no config file` wording with:

> One file by default. `.taut.db` is a standard SimpleBroker database plus
> taut-owned sidecar tables. No project configuration file is required for the
> default SQLite path. When present, `.taut.toml` is configuration rather than
> durable state. Taut creates no state directory or lock files. SQLite-managed
> `.taut.db-wal` and `.taut.db-shm` companions are transient. Under `taut-pg`,
> `.taut.toml` selects a Postgres target and the same sidecar tables live in
> that configured schema.

### [TAUT-3.2] insertion

Insert after the ordered database-resolution rules:

> `.taut.toml` is the only project file Taut reads as project configuration.
> Default SQLite discovery does not require it; selecting Postgres does. When
> step 3 discovers `.taut.toml`, that file is authoritative for storage and
> must contain `version`, `backend`, and `target`, including when `backend =
> "sqlite"`. It may also contain the Taut-owned `[terminal_text]` settings
> defined by [TAUT-6.4]. Taut does not inspect `pyproject.toml`, `.broker.toml`,
> or any other project file for Taut settings, and does not combine project
> settings from multiple project files. The presentation-only case described
> by [TAUT-6.4] does not make a settings-only `.taut.toml` a valid step-3
> storage configuration.

## Tasks

1. Independently review the exact wording against the current resolver and
   terminal-policy implementation.
2. Apply the two spec edits and add this plan under `## Related Plans`.
3. Add focused firing coverage proving `.broker.toml`, `pyproject.toml`, and an
   arbitrary TOML file cannot redirect default SQLite discovery or contribute
   terminal policy, and that project settings are not merged across files.
4. Add one firing case for each required storage field: `version`, `backend`,
   and `target`.
5. Run targeted project-config and terminal-policy tests, the documentation
   reference gate, and
   `git diff --check`.
6. Inspect the final diff to confirm no unrelated dirty-worktree content was
   rewritten.

Red-green TDD is not applicable because the implementation already ignores
these files. The substitute proof is a focused regression test that would fail
if alternate-manifest scanning were introduced later.

## Verification

- `uv run --extra dev pytest -q tests/test_project_config.py tests/test_terminal_text.py`
- `uv run --extra dev pytest -q tests/test_docs_references.py`
- `git diff --check`
- Inspect `git diff -- docs/specs/02-taut-core.md tests/test_project_config.py tests/test_terminal_text.py`
- Inspect `git diff --no-index -- /dev/null docs/plans/2026-07-14-single-project-config-source-spec-plan.md`
  (exit 1 is the expected "differences found" result).
- Inspect `git diff --no-index -- /dev/null tests/test_terminal_text.py`
  (exit 1 is the expected "differences found" result).

## Independent Review

A fresh reviewer checks that the wording describes existing behavior without
silently adding partial-config, manifest-scanning, merge, or selector-relocation
semantics. Review findings are incorporated or answered before completion.

## Review Disposition

The independent review completed on 2026-07-14. All findings were
incorporated:

- narrowed "configuration source" to "project file" so the spec does not
  overclaim about locator inputs
- named `[terminal_text]` as the current Taut-owned setting instead of
  promising an open-ended settings surface
- distinguished presentation-only `.taut.toml` use from valid step-3 storage
  configuration
- added storage and terminal-policy isolation coverage for `.broker.toml`,
  `pyproject.toml`, and an arbitrary TOML file
- added an explicit no-project-file-merge test and one missing-field test for
  each of `version`, `backend`, and `target`
- added a storage no-merge case where `pyproject.toml` cannot supply a missing
  `.taut.toml` target
- expanded verification to include both configuration readers

The final confirmation review found no remaining actionable issues.

## Out of Scope

- README edits
- support for `pyproject.toml` or any other manifest
- treating a settings-only `.taut.toml` as a valid storage-discovery config
- runtime resolver or presentation-policy refactors

## Deviation Log

| Spec ref | Planned behavior | Actual behavior | Rationale | Spec proposal |
|----------|------------------|-----------------|-----------|---------------|
