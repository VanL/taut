# Changelog

## 0.2.0 - 2026-06-17

- Added the separate `taut-pg` extension package for Postgres-backed Taut
  projects through `.taut.toml`.
- Added `bin/pytest-pg` and typed shared/PG-only tests against real Docker
  Postgres.
- Relaxed core target resolution for SimpleBroker project-config targets while
  keeping `TAUT_DB`, `--db`, and `db_path=` as filesystem path selectors.
- Added GitHub-only release gates for `taut-pg` using the `taut_pg/vX.Y.Z` tag
  namespace.
- Updated sidecar DDL to use `BIGINT` for 64-bit timestamp/id portability.

## 0.1.1 - 2026-06-12

- Added `psutil` as a bounded runtime dependency for cross-platform process
  metadata capture, while preserving native start-time tokens where available.
- Fixed identity handle quality for fallback `ps args=` output with spaces in
  `argv[0]`.
- Updated human `read`, `log`, `watch`, and `list` rendering to match the
  README transcript shape, including grouped thread headings, local HH:MM
  display, `-t` id columns, and bounded unread counts.
- Completed the remaining [TAUT-11] proof obligations for concurrent writer
  processes, mid-watch joins, idle peek queues, and continuity-token acts-as.
- Added strict mypy coverage for the test suite (`mypy taut tests`).
- Added a GitHub-only `bin/release.py` helper for version sync, local release
  gates, and `vX.Y.Z` tag management while PyPI name clearance is pending.
- Added GitHub Actions test and release workflows that publish GitHub Releases
  without uploading to PyPI.

## 0.1.0 - 2026-06-12

- Added the taut v0.1 core package: config translation, schema, identity,
  envelope, client API, watcher, and CLI.
- Added contract tests for config, envelope tolerance, sidecar schema,
  cursor semantics, client messaging, CLI JSON/exit behavior, and watcher
  membership refresh.
- Added implementation documentation for the v0.1 architecture and release
  checklist context.
