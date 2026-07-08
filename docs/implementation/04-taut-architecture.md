# Taut Architecture

## Purpose and Scope

This document explains the core implementation boundary: the default `.taut.db`
storage boundary, optional `taut-pg` extension boundary, identity resolution,
message read/write path, watcher, and CLI/API split. The TUI, summon extension,
and non-SQL state mappings remain out of scope.

Implementation status: the current code implements the member-id,
mutable-name, direct-message, notification, and channel-rename model specified
in `docs/specs/03-identity-addressing-notifications.md`.

## Governing Spec References

- `docs/specs/02-taut-core.md` [TAUT-3] storage and project resolution
- `docs/specs/02-taut-core.md` [TAUT-4] threads and membership
- `docs/specs/02-taut-core.md` [TAUT-5] identity and presence
- `docs/specs/02-taut-core.md` [TAUT-6] envelope
- `docs/specs/02-taut-core.md` [TAUT-7] chat-history read model
- `docs/specs/02-taut-core.md` [TAUT-8] CLI, Python API, and watcher
- `docs/specs/02-taut-core.md` [TAUT-10] compound-operation ordering
- `docs/specs/02-taut-core.md` [TAUT-12] forward-compatibility obligations
- `docs/specs/03-identity-addressing-notifications.md` [IAN-3] member ids and
  identity claims
- `docs/specs/03-identity-addressing-notifications.md` [IAN-4] mutable names
  and aliases
- `docs/specs/03-identity-addressing-notifications.md` [IAN-5] addressing
- `docs/specs/03-identity-addressing-notifications.md` [IAN-6] queue namespace
- `docs/specs/03-identity-addressing-notifications.md` [IAN-7] notifications
- `docs/specs/03-identity-addressing-notifications.md` [IAN-8] channel rename

## Design Rationale

`TautClient` owns target resolution, identity resolution, address resolution,
message writes, notification writes, and read cursor semantics. The CLI only
parses arguments and renders results. This keeps one operational path for every
verb and prevents CLI behavior from drifting away from the Python API.

Runtime dependencies are intentionally bounded to `simplebroker>=5.1.0` and
`psutil`. SimpleBroker owns the storage and queue substrate; `psutil` is scoped to
cross-platform process metadata for identity capture so taut does not rely on
fragile platform-specific argv parsing for the core recognition path.
`taut-pg` is a separate project under `extensions/taut_pg`; it installs
`simplebroker-pg` beside Taut but does not add a root runtime dependency.

Postgres support intentionally reuses the same core path. `.taut.toml` selects
SimpleBroker's public `postgres` backend plugin, `TautClient` resolves that
`BrokerTarget`, and `taut/state/_sql.py` uses `Queue.sidecar()` to create the
same `taut_*` tables in the configured schema. The extension package does not
own target parsing, queue construction, SQL, identity, CLI rendering, or
watcher behavior.

Release tooling lives in `bin/release.py`. Its boundary is repository hygiene,
not runtime behavior: it verifies that `pyproject.toml` and
`taut/_constants.py` stay in sync, runs the typed/lint/build release gates,
plans root `vX.Y.Z` tag actions plus extension `taut_pg/vX.Y.Z` and
`taut_summon/vX.Y.Z` tag actions, syncs first-party dependency floors, and
checks GitHub Release state. It accepts `core`/`pg`/`summon` targets plus `all`
for current unpublished versions. It deliberately has no PyPI upload path while
the `taut` package-name request is unresolved. For core or summon releases, it
also starts summon local-LLM preparation before the precheck sequence: reuse a
configured loopback endpoint if it already serves the model; otherwise start a
disposable loopback Ollama container and build the bounded served model while
root and PG gates run. The release helper waits on that endpoint at the
dedicated local-LLM lane and runs it with `TAUT_SUMMON_LOCAL_LLM=1`, so a
missing local model is a release failure rather than a hidden skip. External
live harnesses run in a separate strict one-worker lane from the local-LLM lane
to keep each SQLite process workload in a fresh pytest invocation.
GitHub Actions mirrors that boundary: `.github/workflows/test.yml` owns normal
push/PR gates and is reusable, `.github/workflows/release-gate.yml` runs on
`v*` tags, reuses the root and PG test workflows, verifies that the tag still
points at the tested commit, and calls `.github/workflows/release.yml` to build
artifacts and create the GitHub Release. `.github/workflows/test-pg-extension.yml`
owns the Docker Postgres gate for `taut-pg`, and
`.github/workflows/release-gate-pg.yml` publishes GitHub artifacts for
`taut_pg/v*` tags through the same reusable release workflow.
`.github/workflows/release-gate-summon.yml` publishes GitHub artifacts for
`taut_summon/v*` tags after the reusable root test workflow, which includes the
summon extension and local-LLM lane. No workflow uploads to PyPI.

All production taut-owned relational state flows through `taut/state/`.
`taut/state/__init__.py` exposes the internal `TautState` interface,
`taut/state/_dialect.py` holds the minimal SQL dialect marker, and
`taut/state/_sql.py` is the only production module with sidecar SQL. The
historical schema compatibility shim has been retired
(`docs/plans/2026-07-01-schema-shim-retirement-plan.md`); all callers,
including tests, go through `taut/state/`. That boundary matters because SQL
sidecar tables are the current state mapping, while [TAUT-12.2] reserves a
future non-SQL mapping behind the same state-access boundary.

Message writes use one path: `Queue.generate_timestamp()` followed by
`Queue.insert_messages([(body, ts)])`. Taut never calls `Queue.write()` because
the caller needs the message id before rendering, cursor advancement, and
sub-thread naming.

List metadata asks SimpleBroker for the newest pending timestamp with
`Queue.latest_pending_timestamp()`. That keeps `taut list` from walking full
thread history for `last_ts` while preserving the public SimpleBroker API
boundary and avoiding a Taut-owned cache or sidecar denormalization.

Channel rename uses `simplebroker.open_broker(...).rename_queue(...)` against
the resolved Taut target. Taut records a sidecar rename marker before broker
queue renames, applies broker renames in deterministic channel-then-subthread
order, and then updates `taut_threads` plus `taut_membership`. The code must not
repair this by editing SimpleBroker-owned message tables.

The rename marker is also the recovery contract ([IAN-8.3]). It is written
before the first broker rename, carries the authoritative affected-queue
list, and is cleared only by the sidecar apply step, so an interruption
anywhere in the window leaves a marker naming exactly what was in flight.
Recovery deliberately rides the same `taut rename OLD NEW` invocation
instead of a repair verb: the marker already names the one legal operation,
every other command refuses with that exact command line, and [TAUT-10]
reserves general registry/queue divergence for a future `doctor` verb —
resume must not grow into a divergence reporter. Resume decides each
affected item from which of its two queue names currently exist rather than
rerunning the fresh path's global target precheck, because resume's own
partial progress legitimately produces already-renamed targets the precheck
would refuse. Both names absent is the normal broker state for an empty
queue and is skipped silently — the same posture as the fresh path's
`queue_exists(old)` guard — while both names present means a foreign queue
occupies the target and aborts loudly before any mutation.

Identity resolution orders its evidence from explicit to inferred: explicit
selection (`--as`), continuity token, claim-hash match, agent anchor match,
then human host/uid fallback ([IAN-3.3]). The anchor-match step exists
because the claim hash deliberately includes mutable process facts (working
directory, tty, process group): a live agent that calls `chdir()`
invalidates its own hash without restarting. The stable
(`host_id`, `anchor_pid`, `anchor_start_time`) triple recovers that
continuity — but only below claim-hash precedence, never under `join --new`,
and never across hosts. An anchor match immediately records the current
claim hash for the member ("healing"), which keeps the fallback
self-limiting: the very next command resolves at the cheaper claim-hash
step, and a healing race against a concurrent process is settled in favor
of the claim-hash owner because step-3 semantics outrank the fallback.

First contact retries auto-chosen names because `choose_name` is
deterministic from the anchor basename seed — simultaneous first contacts
collide by construction, not by accident. Each bounded retry re-mints all
three unique values (name, member id, token) inside the loop body so a
stale candidate can never be reused across attempts. Explicit `--as` names
get exactly one attempt and fail loudly: a collision on a chosen name is a
user decision to surface, not noise to retry through.

`TautWatcher` subclasses a vendored Weft-style `MultiQueueWatcher`, but changes
the peek behavior at the taut boundary for chat queues: fetch uses
`peek_many(..., after_timestamp=cursor)`, pending checks use
`has_pending(after_timestamp=cursor)`, and cursor advancement happens inside the
taut handler wrapper after the user handler returns. Notification queues are a
separate consumable inbox path and must not be forced through chat-history cursor
semantics. The vendored multi-queue watcher installs its fan-in activity waiter
through SimpleBroker's watcher lifecycle hook rather than cloning the base retry
loop. Membership refresh is wired both to SimpleBroker's data-version callback
and to a timer that deliberately counts as pending work, so an idle watcher still
reaches the refresh code on backends whose native waiters only wake for queue
writes. The data-version callback is a wake hint, not a fatal boundary: known
transient SQLite sidecar read failures mark the watcher for a full pending scan
on the next drain, while unrelated exceptions still raise.

`TautClient.watch()` builds a client-owned `TautWatchRuntime` adapter before it
constructs `TautWatcher`. The watcher owns live-follow mechanics and local
in-memory cursors; the runtime adapter owns the translation from `TautState`
membership rows to watched-thread values, message/notification decoding, and
cursor persistence. Direct `TautWatcher(client, ...)` construction is preserved
only as a deprecated constructor compatibility path and is converted immediately
to the same runtime.

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
  `/proc` or `ps` evidence remains the start-time token where needed for
  process identity claims.
- Read model: chat client and CLI paths use peek APIs only. Notification inbox
  paths intentionally claim/read notification messages.
- Cursor writes: `TautState.advance_cursor()` is the only production cursor
  update helper and is monotonic for chat queues.
- Identity timestamps: broker timestamps are generated lazily, only once a
  command is known to create or update member state. Guest read-only commands
  must not move the broker timestamp high-water mark.
- Identity claims: claim recording is idempotent under the read/insert race.
  If another process inserts the same deterministic claim before this process
  does, core rereads the row, refreshes `last_seen_ts` for the same member, and
  still rejects claims owned by a different member.
- Watcher refresh: explicit watch-thread validation is strict at construction.
  During refresh, missing filtered threads are convergence events and are
  dropped rather than treated as fatal errors. The interval refresh must remain
  independent of queue message presence; moving it behind a message-pending gate
  breaks non-SQLite forward compatibility.

## Key Files

| Path | Owner |
|---|---|
| `taut/_constants.py` | Version, config translation, name rules, identity constants |
| `taut/addressing.py` | Target parsing, channel/sub-thread validation, and internal queue naming |
| `taut/_scripts.py` | Developer helper logic for `bin/pytest-pg` |
| `taut/_exceptions.py` | Public exception hierarchy |
| `taut/_watch_runtime.py` | Internal watcher runtime protocol and watched-thread value object |
| `taut/envelope.py` | Envelope encode/decode, `from_id`/`from` snapshot handling, and foreign fallback |
| `taut/state/` | Internal state interface, row types, dialect marker, sidecar DDL, version gate, member, claim, alias, thread, membership, cursor, and rename-state queries |
| `taut/identity.py` | Process-chain capture, claim hashing, identity resolution evidence, presence |
| `taut/client/` | Public API facade, shared base, value models, verb mixins, shared codecs, and watcher runtime adapter |
| `taut/watcher.py` | Vendored multi-queue watcher, chat cursor watching, notification inbox integration |
| `taut/cli.py` | Argparse tree, rendering, exit-code mapping |
| `bin/release.py` | GitHub-only release helper, target/tag planning, dependency sync, and local release gates |
| `bin/pytest-pg` | Docker-backed Postgres test runner for shared and extension suites |
| `extensions/taut_pg/` | Separate `taut-pg` package, docs, and PG-only tests |
| `extensions/taut_summon/` | Separate `taut-summon` package, summon driver/adapters, docs, and real-process tests |
| `.github/workflows/` | GitHub Actions test and GitHub-only release publication gates |
| `tests/` | Contract tests against real SQLite files, shared backend tests, and subprocess CLI |

## Spec-Code Trace

Normative specs intentionally describe behavior instead of current file
layout. This table is the code-to-spec map agents should use when changing a
requirement or auditing implementation coverage.

| Spec area | Primary code owners | Contract tests |
|---|---|---|
| [TAUT-3.2], project resolution and config | `taut/_constants.py::load_config`, `taut/client/_base.py::_ClientBase._resolve_target`, `taut/client/__init__.py::TautClient.init` | `tests/test_project_config.py`, `tests/test_cli.py::test_init_uses_project_config_postgres_backend` |
| [TAUT-3.3], [TAUT-3.4], sidecar schema and version gate | `taut/state/_sql.py::SqlSidecarTautState.ensure_schema`, `taut/state/__init__.py::TautState` | `tests/test_state_contract.py`, `tests/test_shared_contract.py` |
| [TAUT-4], channels, membership, replies, reads, logs, and listing | `taut/client/_threads.py::ThreadsMixin.join`, `leave`, `list_threads`; `taut/client/_messaging.py::MessagingMixin.say`, `reply`, `read_unread`, `log`; `taut/client/_identity.py::IdentityMixin.who` | `tests/test_client.py`, `tests/test_cli.py`, `tests/test_shared_contract.py` |
| [TAUT-5], [IAN-3], identity claims, recognition, rejoin, and name changes | `taut/identity.py`, `taut/client/_identity.py::IdentityMixin._resolve_member`, `_create_member`, `rejoin`, `set_name` | `tests/test_identity.py`, `tests/test_client.py`, `tests/test_cli.py::test_rejoin_*` |
| [TAUT-6], message envelopes and sender snapshots | `taut/envelope.py`, `taut/client/_codec.py::message_from_body`, `message_from_decoded`, `taut/client/_messaging.py::MessagingMixin._insert_message` | `tests/test_envelope.py`, `tests/test_client.py::test_set_name_changes_current_name_without_changing_member_id` |
| [TAUT-7], read cursors and chat-history peek discipline | `taut/client/_messaging.py::MessagingMixin.read_unread`, `_implicit_subthread_membership`, `taut/state/_sql.py` membership and cursor helpers | `tests/test_client.py`, `tests/test_state_contract.py`, `tests/test_shared_contract.py` |
| [TAUT-8.1], [TAUT-8.2], CLI behavior, rendering, JSON, and exit codes | `taut/cli.py` | `tests/test_cli.py`, `tests/test_public_api.py` |
| [TAUT-8.3], Python API objects and verb semantics | `taut/client/__init__.py::TautClient`, `taut/client/_models.py`, and the client mixins | `tests/test_public_api.py`, `tests/test_client.py` |
| [TAUT-8.4], watcher behavior | `taut/watcher.py`, `taut/_watch_runtime.py`, `taut/client/_watching.py`, `taut/client/__init__.py::TautClient.watch` | `tests/test_watcher.py`, `tests/test_shared_contract.py::test_project_watcher_receives_cli_write` |
| [IAN-4], alias/name route namespace | `taut/state/_sql.py` member and alias helpers, `taut/_constants.py::route_key`, `validate_member_name` | `tests/test_state_contract.py`, `tests/test_client.py::test_set_name_changes_current_name_without_changing_member_id` |
| [IAN-5], [IAN-6], addressing and special queue names | `taut/addressing.py`, `taut/client/_messaging.py::MessagingMixin.say`, `_say_dm`; `taut/client/_threads.py::_thread_from_row` | `tests/test_addressing.py`, `tests/test_client.py::test_direct_message_queue_is_stable_across_name_change`, `test_channel_names_reject_dots_and_reserved_words` |
| [IAN-7], notification payloads and claiming | `taut/client/_messaging.py::_write_mention_notifications`; `taut/client/_codec.py::notification_from_body`; `taut/client/_notifications.py::_write_notification`, `inbox`; `taut/watcher.py` notification path | `tests/test_client.py::test_mention_notification_is_claimed_without_touching_chat_history`, `tests/test_watcher.py` |
| [IAN-8], channel rename and partial-rename reporting | `taut/client/_threads.py::ThreadsMixin.rename_channel`, `taut/client/_base.py::_ClientBase._ensure_no_incomplete_channel_rename`; `taut/state/_sql.py` rename helpers | `tests/test_client.py::test_rename_channel_moves_messages_and_subthreads`, `test_incomplete_channel_rename_blocks_chat_history_operations`, `tests/test_state_contract.py`, shared rename tests |
| [TAUT-12.1], Postgres extension boundary | `extensions/taut_pg/`, `taut/_scripts.py`, `bin/pytest-pg` | `extensions/taut_pg/tests/`, `tests/test_shared_contract.py` under `bin/pytest-pg` |

## Change Guidance

Read `docs/specs/02-taut-core.md`,
`docs/specs/03-identity-addressing-notifications.md`, and the active plan for
the behavior before editing. Prefer extending `TautClient` and `taut/state/`
over adding logic in the CLI or watcher.

Before completion, run:

```bash
uv run pytest
uv run pytest -m shared
uv run ./bin/pytest-pg --fast
uv run pytest extensions/taut_summon/tests
uv run ruff check taut tests bin extensions/taut_pg/taut_pg extensions/taut_pg/tests extensions/taut_summon/taut_summon extensions/taut_summon/tests
uv run ruff format --check taut tests bin extensions/taut_pg/taut_pg extensions/taut_pg/tests extensions/taut_summon/taut_summon extensions/taut_summon/tests
uv run --extra dev mypy taut tests bin/release.py extensions/taut_pg/taut_pg extensions/taut_pg/tests --config-file pyproject.toml
uv run --extra dev mypy extensions/taut_summon/taut_summon extensions/taut_summon/tests --config-file pyproject.toml
uv build
uv build extensions/taut_pg
uv build extensions/taut_summon
```

Then run the grep gates from the active plan for private imports, unexpected
consuming broker APIs, SQL outside `taut/state/_sql.py`, and `Queue.write()`.
Expected exceptions: `taut/watcher.py` consumes notification queues during
watch, `taut/client/_notifications.py::NotificationsMixin.inbox` claims notification pointers, and
`taut/_scripts.py` may use `SELECT 1` only to validate a Postgres test DSN.

## Related Plans

- `docs/plans/2026-06-18-member-identity-addressing-plan.md`
- `docs/plans/2026-06-12-taut-foundation-plan.md`
- `docs/plans/2026-06-12-taut-0.1.1-hardening-plan.md`
- `docs/plans/2026-06-17-github-release-helper-plan.md`
- `docs/plans/2026-06-17-github-actions-release-workflows-plan.md`
- `docs/plans/2026-06-17-taut-pg-extension-plan.md`
- `docs/plans/2026-06-17-implementation-review-followups-plan.md`
- `docs/plans/2026-06-18-simplebroker-latest-timestamp-plan.md`
- `docs/plans/2026-07-01-schema-shim-retirement-plan.md`
- `docs/plans/2026-07-01-taut-state-sql-dialect-plan.md`
- `docs/plans/2026-07-01-taut-watch-runtime-plan.md`
- `docs/plans/2026-07-06-evaluation-findings-remediation-plan.md`
