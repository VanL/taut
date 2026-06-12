# Taut Architecture

## Purpose and Scope

This document explains the v0.1 core implementation: the `.taut.db` storage
boundary, identity resolution, message read/write path, watcher, and CLI/API
split. The TUI, summon extension, and non-SQLite state mappings remain out of
scope.

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

- Storage: `.taut.db` is the only durable file. SQLite WAL/shm companions are
  SQLite-managed transients.
- Project resolution: `TautClient` resolves a target before any queue is opened.
  Only `TautClient.init()` creates a database.
- SimpleBroker API: taut imports from `simplebroker` and `simplebroker.ext`
  only. No private SimpleBroker modules and no SQL against broker tables.
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
| `taut/_exceptions.py` | Public exception hierarchy |
| `taut/envelope.py` | Envelope v1 encode/decode and foreign fallback |
| `taut/schema.py` | Sidecar DDL, version gate, member/thread/membership queries |
| `taut/identity.py` | Process-chain capture, anchor selection, presence |
| `taut/client.py` | Public API and all verb semantics |
| `taut/watcher.py` | Vendored multi-queue watcher and `TautWatcher` |
| `taut/cli.py` | Argparse tree, rendering, exit-code mapping |
| `tests/` | Contract tests against real `.taut.db` files and subprocess CLI |

## Change Guidance

Read `docs/specs/02-taut-core.md` and
`docs/plans/2026-06-12-taut-foundation-plan.md` before changing behavior.
Prefer extending `TautClient` and the schema helpers over adding logic in the
CLI or watcher.

Before completion, run:

```bash
uv run pytest
uv run ruff check taut tests
uv run ruff format --check taut tests
uv run mypy taut
uv build
```

Then run the grep gates from the foundation plan for private imports,
consuming broker APIs, SQL outside `schema.py`, and `Queue.write()`.

## Related Plans

- `docs/plans/2026-06-12-taut-foundation-plan.md`
