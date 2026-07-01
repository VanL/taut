# Changelog

## 0.4.0 - 2026-07-01

- Added stable member identity, aliases, direct-message routing by current
  name, consumable mention/DM notifications, `inbox`, `set name`, `rejoin`,
  and channel rename support.
- Reworked `taut.client` into a package facade over concern-specific modules
  while keeping `from taut.client import TautClient, Message, ...` as the
  public import surface.
- Replaced the old `schema.py` helper layer with `taut.state` and a SQL dialect
  hook so sidecar ownership is explicit and tested across SQLite and Postgres.
- Changed `TautWatcher` to depend on a `TautWatchRuntime` protocol. The normal
  public API remains `TautClient.watch()`, and direct `TautWatcher(client, ...)`
  construction is deprecated.
- Updated Taut and `taut-pg` tests for the state adapter, public watcher
  surface, and Postgres-visible behavior. Both the core package and `taut-pg`
  are versioned `0.4.0` for this release.
- Cleaned project hygiene: `.envrc` is local-only, stale generated logo assets
  are out of workflow gates, and private test coupling was reduced where the
  public API gives the same proof.

## 0.2.1 - 2026-06-18

- Fixed Postgres project-config and shared backend conformance coverage.
- Documented `read` pagination and tightened bounded `log --limit` behavior.

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
