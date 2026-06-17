# Changelog

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

## 0.1.0 - 2026-06-12

- Added the taut v0.1 core package: config translation, schema, identity,
  envelope, client API, watcher, and CLI.
- Added contract tests for config, envelope tolerance, sidecar schema,
  cursor semantics, client messaging, CLI JSON/exit behavior, and watcher
  membership refresh.
- Added implementation documentation for the v0.1 architecture and release
  checklist context.
