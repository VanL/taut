# Taut Architecture

## Purpose and Scope

This document explains the v0.1 core implementation: the default `.taut.db`
storage boundary, optional `taut-pg` extension boundary, identity resolution,
message read/write path, watcher, and CLI/API split. The TUI, summon extension,
and non-SQL state mappings remain out of scope.

## Governing Spec References

- `docs/specs/02-taut-core.md` [TAUT-3] storage and project resolution
- `docs/specs/02-taut-core.md` [TAUT-4] threads and membership
- `docs/specs/02-taut-core.md` [TAUT-5] identity and presence
- `docs/specs/02-taut-core.md` [TAUT-6] envelope
- `docs/specs/02-taut-core.md` [TAUT-7] peek-only read model
- `docs/specs/02-taut-core.md` [TAUT-8] CLI, Python API, and watcher
- `docs/specs/02-taut-core.md` [TAUT-10] compound-operation ordering
- `docs/specs/02-taut-core.md` [TAUT-12] forward-compatibility obligations

## Design Rationale

`TautClient` owns target resolution, identity resolution, message writes, and
read cursor semantics. The CLI only parses arguments and renders results. This
keeps one operational path for every verb and prevents CLI behavior from
drifting away from the Python API.

Runtime dependencies are intentionally bounded to `simplebroker` and `psutil`.
SimpleBroker owns the storage and queue substrate; `psutil` is scoped to
cross-platform process metadata for identity capture so taut does not rely on
fragile platform-specific argv parsing for the core recognition path.
`taut-pg` is a separate project under `extensions/taut_pg`; it installs
`simplebroker-pg` beside Taut but does not add a root runtime dependency.

Postgres support intentionally reuses the same core path. `.taut.toml` selects
SimpleBroker's public `postgres` backend plugin, `TautClient` resolves that
`BrokerTarget`, and the existing `Queue.sidecar()` calls in `taut/schema.py`
create the same `taut_*` tables in the configured schema. The extension package
does not own target parsing, queue construction, SQL, identity, CLI rendering,
or watcher behavior.

Release tooling lives in `bin/release.py`. Its boundary is repository hygiene,
not runtime behavior: it verifies that `pyproject.toml` and
`taut/_constants.py` stay in sync, runs the typed/lint/build release gates,
plans root `vX.Y.Z` tag actions and extension `taut_pg/vX.Y.Z` tag actions, and
checks GitHub Release state. It deliberately has no PyPI upload path while the
`taut` package-name request is unresolved.
GitHub Actions mirrors that boundary: `.github/workflows/test.yml` owns normal
push/PR gates and is reusable, `.github/workflows/release-gate.yml` runs on
`v*` tags, reuses the root and PG test workflows, verifies that the tag still
points at the tested commit, and calls `.github/workflows/release.yml` to build
artifacts and create the GitHub Release. `.github/workflows/test-pg-extension.yml`
owns the Docker Postgres gate for `taut-pg`, and
`.github/workflows/release-gate-pg.yml` publishes GitHub artifacts for
`taut_pg/v*` tags through the same reusable release workflow. No workflow
uploads to PyPI.

All taut-owned relational state flows through `taut/schema.py`. It is the only
module with sidecar SQL. That boundary matters because SQL sidecar tables are
the v0.1 state mapping, while [TAUT-12.2] reserves a future non-SQL mapping
behind the same state-access boundary.

Message writes use one path: `Queue.generate_timestamp()` followed by
`Queue.insert_messages([(body, ts)])`. Taut never calls `Queue.write()` because
the caller needs the message id before rendering, cursor advancement, and
sub-thread naming.

`TautWatcher` subclasses a vendored Weft-style `MultiQueueWatcher`, but changes
the peek behavior at the taut boundary: fetch uses
`peek_many(..., after_timestamp=cursor)`, pending checks use
`has_pending(after_timestamp=cursor)`, and cursor advancement happens inside the
taut handler wrapper after the user handler returns. Membership refresh is wired
both to SimpleBroker's data-version callback and to a timer that deliberately
counts as pending work, so an idle watcher still reaches the refresh code on
backends whose native waiters only wake for queue writes.

## Boundaries and Invariants

- Storage: `.taut.db` is the default durable target. SQLite WAL/shm companions
  are SQLite-managed transients. Under `taut-pg`, `.taut.toml` is config and
  durable chat state lives in the configured Postgres schema.
- Project resolution: `TautClient` resolves a target before any queue is opened.
  Only `TautClient.init()` creates a database.
- Backend selection: `--db`, `db_path=`, and `TAUT_DB` remain filesystem path
  selectors. Postgres is selected only through `.taut.toml`.
- SimpleBroker API: taut imports from `simplebroker` and `simplebroker.ext`
  only. No private SimpleBroker modules and no SQL against broker tables.
- Process capture: `psutil` is the primary source for argv, executable, cwd,
  uid, parent, process group/session, and terminal when available. Native
  `/proc` or `ps` evidence remains the start-time token where needed so
  existing `(pid, start_time)` identity matching stays stable.
- Read model: client and CLI paths use peek APIs only. Consuming read/move code
  appears only in the vendored watcher compatibility modes, not in
  `TautWatcher`.
- Cursor writes: `schema.advance_cursor()` is the only cursor update helper and
  is monotonic.
- Identity timestamps: broker timestamps are generated lazily, only once a
  command is known to create or update member state. Guest read-only commands
  must not move the broker timestamp high-water mark.
- Watcher refresh: explicit watch-thread validation is strict at construction.
  During refresh, missing filtered threads are convergence events and are
  dropped rather than treated as fatal errors. The interval refresh must remain
  independent of queue message presence; moving it behind a message-pending gate
  breaks non-SQLite forward compatibility.

## Key Files

| Path | Owner |
|---|---|
| `taut/_constants.py` | Version, config translation, name rules, identity constants |
| `taut/_scripts.py` | Developer helper logic for `bin/pytest-pg` |
| `taut/_exceptions.py` | Public exception hierarchy |
| `taut/envelope.py` | Envelope v1 encode/decode and foreign fallback |
| `taut/schema.py` | Sidecar DDL, version gate, member/thread/membership queries |
| `taut/identity.py` | Process-chain capture, anchor selection, presence |
| `taut/client.py` | Public API and all verb semantics |
| `taut/watcher.py` | Vendored multi-queue watcher and `TautWatcher` |
| `taut/cli.py` | Argparse tree, rendering, exit-code mapping |
| `bin/release.py` | GitHub-only release helper and local release gates |
| `bin/pytest-pg` | Docker-backed Postgres test runner for shared and extension suites |
| `extensions/taut_pg/` | Separate `taut-pg` package, docs, and PG-only tests |
| `.github/workflows/` | GitHub Actions test and GitHub-only release publication gates |
| `tests/` | Contract tests against real SQLite files, shared backend tests, and subprocess CLI |

## Change Guidance

Read `docs/specs/02-taut-core.md` and
`docs/plans/2026-06-12-taut-foundation-plan.md` before changing behavior.
Prefer extending `TautClient` and the schema helpers over adding logic in the
CLI or watcher.

Before completion, run:

```bash
uv run pytest
uv run pytest -m shared
uv run ./bin/pytest-pg --fast
uv run ruff check taut tests bin extensions/taut_pg/taut_pg extensions/taut_pg/tests
uv run ruff format --check taut tests bin extensions/taut_pg/taut_pg extensions/taut_pg/tests
uv run --extra dev mypy taut tests bin/release.py extensions/taut_pg/taut_pg extensions/taut_pg/tests --config-file pyproject.toml
uv build
uv build extensions/taut_pg
```

Then run the grep gates from the foundation plan for private imports,
consuming broker APIs, SQL outside `schema.py`, and `Queue.write()`.

## Related Plans

- `docs/plans/2026-06-12-taut-foundation-plan.md`
- `docs/plans/2026-06-12-taut-0.1.1-hardening-plan.md`
- `docs/plans/2026-06-17-github-release-helper-plan.md`
- `docs/plans/2026-06-17-github-actions-release-workflows-plan.md`
- `docs/plans/2026-06-17-taut-pg-extension-plan.md`
