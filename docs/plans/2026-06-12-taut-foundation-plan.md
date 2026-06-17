# Taut v0.1 Foundation Plan

Date: 2026-06-12
Status: Complete for the v0.1 CLI milestone and 0.1.1 hardening slice.
Review rounds 1–5 are recorded in the appendix; implementation,
verification, documentation alignment, and release commit/tag bookkeeping
are complete. PyPI publication remains out of scope pending the package-name
request.

## 1. Goal

Implement the taut v0.1 core defined in `docs/specs/02-taut-core.md`: a
single-file (`.taut.db`) chat substrate over SimpleBroker with process-
fingerprint identity, peek-only reads with per-member cursors, a
`TautClient` Python API, a `TautWatcher` multi-queue follower, and the
`taut` CLI. This plan covers the package through the CLI milestone; the TUI
is explicitly out of scope and gets its own plan.

This is risky work under [DOM-5]: it introduces new persistence (sidecar
schema), background processing (watcher thread), and public contracts
(CLI shape, storage format, envelope). The hardening checklist in
`docs/agent-context/runbooks/hardening-plans.md` applies in full.

## 2. Source Documents

Source specs:

- `docs/specs/02-taut-core.md` — all sections; load-bearing for this plan:
  [TAUT-3.2] config translation, [TAUT-3.3] sidecar schema v1,
  [TAUT-3.4] public-API-only rule, [TAUT-5.2]–[TAUT-5.5] identity,
  [TAUT-6.1] envelope, [TAUT-7.1]–[TAUT-7.4] read model,
  [TAUT-8.1]–[TAUT-8.4] surfaces, [TAUT-11] verification expectations
- `docs/specs/01-development-documentation-operating-model.md` [DOM-5],
  [DOM-8], [DOM-10], [DOM-11]

Reference material (sibling repos, read-only):

- `../simplebroker` — the substrate, v4.7.1
- `../weft` — the embedding reference and the `MultiQueueWatcher` source

## 3. Context and Key Files

### What exists today

This repository contains documentation but no implementation code.
`taut/__init__.py` is empty; `README.md` carries the v0.1 public contract
(written with this plan — do not discount or overwrite it); `pyproject.toml`
declares the dependency floor. There is no prior code to preserve — but
the spec contracts are already written, so the job is conformance, not
invention.

### Files to create (the implementation surface)

| File | Owns |
|---|---|
| `taut/_constants.py` | version, limits, name regexes, shell/wrapper/infra lists ([TAUT-5.2]), `load_config()` translating `TAUT_*` → `BROKER_*` ([TAUT-3.2]) |
| `taut/_exceptions.py` | `TautError` hierarchy (`NotInitializedError`, `ThreadNameError`, `IdentityError`, `SchemaVersionError`, …) |
| `taut/envelope.py` | envelope v1 encode/decode, foreign-body fallback ([TAUT-6]) |
| `taut/schema.py` | sidecar DDL v1, schema-version gate, member/thread/membership queries ([TAUT-3.3]) |
| `taut/identity.py` | chain capture, anchor selection, nearest-wins matching, rejoin hints, presence ([TAUT-5]) |
| `taut/client.py` | `TautClient`: target resolution and every verb's semantics ([TAUT-8.3]) |
| `taut/watcher.py` | vendored `MultiQueueWatcher` (adapted) + `TautWatcher` ([TAUT-8.4]) |
| `taut/cli.py`, `taut/__main__.py` | argparse CLI over `TautClient` ([TAUT-8.1], [TAUT-8.2]) |
| `tests/…` | per-module tests, see Testing Plan |

### Required reading (before any code)

1. `docs/specs/02-taut-core.md` — entire spec.
2. `../weft/weft/core/tasks/multiqueue_watcher.py` — the class to vendor.
   Current structure: `QueueMode` (READ/RESERVE/PEEK), `QueueRuntimeConfig`
   per queue (handler, mode, error_handler, priority), one
   `BaseWatcher`-managed thread; `_fetch_next_message()` dispatches by
   mode (`peek_one(with_timestamps=True)` for PEEK); activity via
   `create_activity_waiter_for_queues` with polling fallback;
   `_update_active_queues()` re-probes with `queue.has_pending()`;
   `add_queue`/`remove_queue` bump `_queue_generation` and rebuild the
   waiter. Weft-specific imports to replace when vendoring:
   `weft._constants` (QUEUE_PRIORITY_NORMAL, discovery interval,
   `load_config`) and `weft.context.resolve_context_broker_target`.
3. `../simplebroker/simplebroker/watcher.py` — `QueueWatcher` peek mode:
   `_last_seen_ts` initialized from `after_timestamp`, fetch via
   `stream_messages(peek=True, after_timestamp=_last_seen_ts)`, cursor
   advanced only after successful dispatch.
4. `../simplebroker/simplebroker/sbqueue.py` — `Queue` surface used here:
   `peek_many(limit, with_timestamps=True, after_timestamp=…)` (note:
   `peek_one` has **no** `after_timestamp` parameter),
   `has_pending(after_timestamp=…)`, `generate_timestamp()`,
   `insert_messages()`, `sidecar(transaction=…)`. Note `write()` returns
   `None` — taut never calls it ([TAUT-3.5] write path).
5. `../simplebroker/simplebroker/project.py` —
   `resolve_broker_target(starting_dir, config=…) -> BrokerTarget | None`:
   the upward-discovery call ([TAUT-3.2]); `None` means "no database →
   taut init hint". Plain `Queue(name, config=…)` does *not* search
   upward and auto-creates files; the client resolves first, opens
   second.
6. `../simplebroker/simplebroker/watcher.py` (second look) —
   `_try_dispatch_message` vs `_dispatch`/`_safe_call_handler`: handler
   exceptions are routed to the error handler and, when it returns
   "continue", dispatch returns normally. Post-dispatch code cannot
   distinguish success from handled failure; this is why cursor advance
   lives in taut's handler wrapper ([TAUT-8.4]).
7. `../simplebroker/README.md` — sections "Sidecar tables (advanced)"
   (note: no queue operations inside a sidecar transaction),
   "Inserting messages with exact IDs", "Embedding SimpleBroker in Your
   Project", "Project Scoping".
8. `../weft/weft/_constants.py` around the `_WEFT_TO_BROKER` mapping
   (~line 1592) — the env-translation pattern taut mirrors.
9. `../weft/weft/core/monitor/store.py` — sidecar table DDL/versioning in
   practice (`weft_monitor_meta` etc.).

Comprehension gate — answer before editing; wrong answers mean re-read:

- Q1: Why does stock `MultiQueueWatcher` PEEK mode re-deliver the same
  message forever on a chat queue, and which two methods must the subclass
  override to fix it? (A: `_fetch_next_message` head-peeks via
  `peek_one()`, and `_queue_has_pending` ignores cursors so the queue
  never goes inactive; override both with cursor-aware variants.)
- Q2: In SimpleBroker's own peek-mode watcher, when does `_last_seen_ts`
  not advance? (A: when handler dispatch fails — failed messages must be
  re-seen; taut mirrors this in [TAUT-8.4].)
- Q3: Which three `BROKER_*` keys does taut set, which *call* performs
  the upward search, and what does `BROKER_PROJECT_CONFIG_NAME=.taut.toml`
  prevent? (A: see [TAUT-3.2]; `resolve_broker_target()` does the search
  and returns `None` for "run taut init"; a stray `.broker.toml` from
  another project must not redirect taut's database resolution.)
- Q4: Where does `joined_ts` come from when no message is written?
  (A: `Queue.generate_timestamp()` — wall clock is never stored,
  [TAUT-3.5].)
- Q5: Why can't taut use `Queue.write()`, and what is the write path?
  (A: `write()` returns `None` and taut always needs the new message's
  id; the single write path is `generate_timestamp()` +
  `insert_messages([(body, ts)])`, [TAUT-3.5].)
- Q6: Why can't cursor advance happen after the base watcher's dispatch
  returns? (A: `_safe_call_handler` routes handler exceptions to the
  error handler and returns normally on "continue", so dispatch
  "success" includes handled failures; advance must happen inside taut's
  handler wrapper after the user handler returns, [TAUT-8.4].)

## 4. Invariants and Constraints

Named before tasks; every task is bounded by these.

- I1 — Single file. No state outside `.taut.db` ([TAUT-3.1]). No config
  files, no `~/.taut`, no lock files.
- I2 — Peek-only. No code path calls `read*`, `move*`, `delete*`, or
  vacuum on broker messages ([TAUT-7.1]). The vendored watcher keeps
  READ/RESERVE modes compilable but `TautWatcher` never configures them.
- I3 — Public API only. Imports from `simplebroker` and `simplebroker.ext`
  exclusively; taut SQL touches `taut_*` tables only ([TAUT-3.4]). No
  `import weft` anywhere — the watcher is vendored, not imported.
- I4 — One path per behavior. Identity resolution, target resolution, and
  every verb live in `TautClient`; `cli.py` parses arguments and renders.
  If the CLI needs logic the client lacks, the client grows it.
- I5 — One timestamp domain, one write path. All stored times come from
  `generate_timestamp()`; every message write is
  `generate_timestamp()` + `insert_messages()` so the writer knows its
  id; `Queue.write()` appears nowhere in taut ([TAUT-3.5]).
- I6 — Cursor monotonicity. `last_seen_ts` writes are
  `max(existing, new)` ([TAUT-7.2]) — concurrent readers in two processes
  must not regress each other.
- I7 — Contracts match the spec verbatim once released: envelope fields
  ([TAUT-6.1]), sidecar DDL ([TAUT-3.3]), `--json` field names and exit
  codes ([TAUT-8.1], [TAUT-8.2]). Pre-release these may change only by
  amending the spec first ([DOM-6]).
- I8 — Bounded dependency set. Runtime deps stay exactly
  `["simplebroker>=4.7.1", "psutil>=6.0"]`; CLI is argparse; Python ≥
  3.11. `psutil` is scoped to cross-platform process metadata for
  identity capture; it must not become a general process-control
  abstraction.
- I9 — Backend forward compatibility ([TAUT-12.1], [TAUT-12.2]). No
  SQLite-specific assumption outside target resolution and the
  documented data-version wake; sidecar SQL is qmark-only; identity is
  host-aware (capture, storage, matching, presence) from the first
  schema version; all state access flows through `schema.py` — the seam
  a future Redis state mapping replaces.

Hidden couplings (call these out in code comments where they bite):

- Watcher membership refresh piggybacks on `PRAGMA data_version` waking
  the poll loop — valid only because sidecar tables share the database
  file (I1). A bounded-interval re-check is the backstop, not the primary.
- Cursors have two writers (a running `watch` plus `read` in another
  process, same member). I6 is what makes that safe; the sidecar UPDATE
  must be written as a monotonic max, not a blind set.
- `say`'s caught-up check then write is a benign race, accepted by
  [TAUT-7.4] — do not "fix" it with locking; note it in a comment.
- Write-path ordering is three steps, not two: authoritative sidecar
  state → message insert → cursor advance last and best-effort
  ([TAUT-10]). Advancing the cursor before the insert can permanently
  skip other writers' messages on crash; the cursor is never part of
  the "sidecar first" state.
- Sidecar writes and message writes cannot share a transaction
  (SimpleBroker forbids queue ops inside a sidecar transaction). Compound
  operations follow the [TAUT-10] ordering rule: authoritative sidecar
  state first (idempotent upserts), notice/message last; crash windows
  leave valid-but-quieter states, never a message in an unregistered
  thread.
- The vendored watcher tracks upstream weft. Record the source repo, file,
  and commit hash in the module docstring so future syncs are diffable.

One-way doors: none during development; the first PyPI release freezes I7
(envelope v1, schema v1, JSON fields, exit codes). The release checklist
in Task 9 is the door's gate. The `SchemaVersionError` refusal path
([TAUT-3.3]) must exist before any release — it is the storage rollback
enabler for every future version.

Rollback: pre-release, each task lands as an independently revertible
slice (git revert restores a coherent earlier state; no task leaves the
repo half-wired). No data migrations exist in v0.1; `taut init` databases
created during development carry `schema_version=1` from day one.

## 5. Tasks

Each task: implement, test, run gates, then stop and re-evaluate against
the named invariants before continuing.

1. Package scaffolding.
   - Files: `pyproject.toml`, `taut/__init__.py`, `taut/py.typed`,
     `LICENSE` (MIT, © Van Lindberg), `.gitignore`, `uv.lock`.
   - Content: name/description/readme; `requires-python = ">=3.11"`;
     `dependencies = ["simplebroker>=4.7.1", "psutil>=6.0"]`;
     `[project.scripts]`
     `taut = "taut.cli:main"`; dev extra (pytest, pytest-xdist, ruff,
     mypy); copy ruff/mypy/pytest tool sections from
     `../simplebroker/pyproject.toml` (same strictness), build backend
     matching weft (hatchling).
   - Done: `uv sync --all-extras` clean; `uv run python -c "import taut"`.
   - Gate: stop if you add any dependency beyond simplebroker and psutil
     (I8).
2. Constants and exceptions.
   - Files: `taut/_constants.py`, `taut/_exceptions.py`,
     `tests/test_constants.py`.
   - `load_config()` mirrors weft's translation pattern: build the three
     `BROKER_*` keys from [TAUT-3.2], pass through
     `simplebroker.resolve_config()`; honor `TAUT_DB`, `TAUT_AS`, and
     `TAUT_TOKEN`. Shell/wrapper/infrastructure lists from [TAUT-5.2]
     live here, as do the handle pools from [TAUT-5.4] (per-basename
     knockoff lists, the shared historical pool) — all lowercase,
     handle-rule-valid, deterministic order.
   - Tests: translation produces exactly the spec'd keys; `TAUT_DB`
     override wins over discovery.
   - Done: tests green; no other module hardcodes a `BROKER_*` key.
3. Envelope.
   - Files: `taut/envelope.py`, `tests/test_envelope.py`.
   - Encode/decode per [TAUT-6.1]; foreign fallback object per
     [TAUT-6.3]; unknown-field tolerance; future-`v` raw rendering.
   - Tests: property-based round-trip (Hypothesis is already a
     simplebroker dev dependency pattern; if adding it violates the dev
     bar, use exhaustive table tests instead — decide once, in this task);
     foreign and future-version inputs.
   - Done: decode never raises on arbitrary str input.
4. Sidecar schema and queries.
   - Files: `taut/schema.py`, `tests/test_schema.py`.
   - DDL strings exactly as [TAUT-3.3] including the two partial unique
     indexes (the schema backstop for anchor and human-uid uniqueness)
     and the `token` (UNIQUE) and `meta` (JSON) member columns;
     `ensure_schema()` idempotent via `sidecar(transaction=True)`;
     `SchemaVersionError` on newer version; query helpers: upsert member
     with lost-race handling (uniqueness violation → re-resolve, never
     error), get-by-anchor/uid/handle, thread registry CRUD, membership
     CRUD, monotonic cursor advance (I6 lives here, in one function).
   - Read first: simplebroker README sidecar rules (qmark placeholders,
     no broker tables, no nested transactions).
   - Tests: real temp db; two-connection cursor race (interleaved
     advances never regress); version-gate refusal.
   - Done: tests green; grep shows no SQL outside `schema.py`.
5. Identity.
   - Files: `taut/identity.py`, `tests/test_identity.py`.
   - Chain capture (`psutil` for cross-platform process metadata; Linux
     `/proc` and macOS/BSD `ps`/`lsof` fallbacks where native start tokens
     or individual fields are still needed), each field degrading to
     `None` ([TAUT-5.1]); host
     identity capture: opaque `host_id` (`/etc/machine-id` on Linux,
     `IOPlatformUUID` via `ioreg` on macOS, hostname fallback) plus
     `host_label` for display — matching always uses `host_id`; anchor
     selection walk ([TAUT-5.2]); nearest-wins match gated on local
     `host_id` ([TAUT-5.3]); similarity hint scoring ([TAUT-5.4]);
     presence check, `remote` for off-host anchors ([TAUT-5.6], I9).
   - Start-time canonicalization ([TAUT-5.1]): store the platform-native
     token exactly as captured and match by byte equality. Never parse
     start times into floats or datetimes for comparison — locale,
     precision, and rounding drift silently break the pid+start-time
     pair.
   - Anti-mock rule: capture *parsers* may be unit-tested against recorded
     `ps` output per platform; anchor selection, nearest-wins, and
     recognition-across-invocations must be proven with real spawned
     process chains (`sh -c`, nested interpreters) per [TAUT-11].
   - Done: real-chain tests pass on the dev platform; CI covers Linux +
     macOS.
   - Gate: stop if capture needs elevated privileges or a dependency
     beyond the I8 set.
6. Client — two reviewable slices sharing `taut/client.py`,
   `taut/__init__.py` exports, and `tests/test_client.py`. Common to
   both: `Queue(name, db_path=target, config=cfg)` per the simplebroker
   embedding pattern, constructed only after target resolution; the
   single internal write function `generate_timestamp()` +
   `insert_messages([(body, ts)])` for messages *and* notices (I4, I5);
   compound ops follow the [TAUT-10] ordering rule (sidecar first,
   message last).

   6a. Resolution, init, and identity lifecycle.
   - `TautClient(db_path=None, identity=None)` (keyword matches
     [TAUT-3.2]): resolve target once — explicit path (must exist, else
     `NotInitializedError`) or `resolve_broker_target(cwd, config=cfg)`
     with `None` → `NotInitializedError`; `init()` classmethod is the
     only creation path (`target_for_directory` + first open + sidecar
     schema). Verbs `whoami/join/leave/rejoin` with exactly the spec
     semantics ([TAUT-4.2]–[TAUT-4.3], [TAUT-5.3]–[TAUT-5.9]): token
     minting at creation and `TAUT_TOKEN` resolution (invalid token =
     loud exit 1, no fall-through), candidate computation with the
     tty-prompt/non-tty-hint split and `join --new`, persona set/show,
     knockoff handle generation; `Member` dataclass; the internal write
     function lands here (join/leave notices need it).
   - Tests: explicit-path-must-exist guard (no auto-create);
     non-SQLite resolved target refused with the version error
     ([TAUT-3.2]); join initializes the cursor at the join/creation
     notice — start-at-now ([TAUT-7.4]); token round-trip (create →
     mint → `TAUT_TOKEN` acts-as from an unrelated process tree) and
     invalid-token error; `rejoin --token`; non-tty candidate hint with
     auto-create, `--new` bypass (tty prompting is excluded from
     automated tests; verify by hand); handle-pool order (`claude` → 
     `claudette` → … → historical pool → numeric backstop); persona
     set at join, updated on re-join, shown in member objects;
     concurrent auto-create race — two processes, one anchor, unique
     index decides, loser re-resolves ([TAUT-3.3]); `--as`
     unanchored-creation on claimed anchor ([TAUT-5.3]); rejoin
     collision refusal ([TAUT-5.5]); guest `whoami`.
   - Done: identity resolution and member lifecycle conform to
     [TAUT-5.3]–[TAUT-5.7] against a real db. **Independent review
     checkpoint here (§8)** — identity semantics are where
     contradictions would surface.

   6b. Messaging.
   - Verbs `say/reply/read/log/list_threads/who` with exactly the spec
     semantics ([TAUT-4], [TAUT-7]); `say`/`reply` return the id; reply
     suffix resolution scans the most recent 1,000 ids via peek APIs
     ([TAUT-8.1]) — no broker-table SQL (I3); dataclasses `Message`,
     `Thread`.
   - Tests: unread/cursor semantics incl. [TAUT-7.4] notice-advance
     rules and advance-only-after-insert ordering ([TAUT-10]);
     membership-gated `read` (non-member → miss + hint; sub-thread
     implicit join with parent membership per [TAUT-4.3]); reply with a
     full id older than the 1,000-message suffix window (exact-peek
     path) and suffix resolution incl. ambiguity error; guest read-only
     commands (`list`/`log`/`who`); `who` on a missing thread → exit-2
     semantics at the client layer.
   - Done: every [TAUT-8.1] behavior except `watch` reachable via one
     client call (`watch` arrives with Task 7, which adds
     `TautClient.watch()` over the new watcher).

   Gate (both slices): stop if a verb needs broker-table SQL (I3) or a
   second write path appears (I4).
7. Watcher.
   - Files: `taut/watcher.py`, `tests/test_watcher.py`.
   - Vendor `MultiQueueWatcher` with weft imports replaced by taut
     constants/target resolution; module docstring records provenance
     (repo, path, commit). Subclass `TautWatcher`: per-queue cursors
     initialized from membership; `_fetch_next_message` override → 
     `peek_many(1, with_timestamps=True, after_timestamp=cursor)`;
     `_queue_has_pending` override → `has_pending(after_timestamp=cursor)`;
     cursor advance + persist **inside the per-queue handler wrapper,
     after the user handler returns** (Q6 — never inferred from dispatch
     returning); per-message failure counter implementing the 3-strikes
     poison rule ([TAUT-8.4]); membership re-check by extending the
     data-version callback (the vendored one only refreshes `last_ts`)
     plus bounded-interval backstop; `add_queue`/`remove_queue` driven by
     membership diffs. Add `TautClient.watch()` returning a configured
     `TautWatcher`.
   - Cursor persistence is per-message by default; batched monotonic
     flushes (every N messages, on idle, on stop) are a permitted
     optimization under [TAUT-8.4] — a crash re-shows messages, never
     skips them. Do not add locking to reduce the write rate; monotonic
     max is the whole concurrency story (I6).
   - Lifecycle edges: the vendored constructor rejects empty
     `queue_configs`, so `TautClient.watch()` with zero memberships
     raises (CLI maps it to exit 2 per [TAUT-8.1]); a *running* watcher
     may drop to zero queues and must keep idling and pick up the next
     join; `leave` convergence is interval-bounded ([TAUT-4.3]) — no
     per-message membership queries.
   - Tests ([TAUT-11]): live watcher vs. concurrent writer subprocesses —
     no loss, no re-dispatch after advance, cursor persisted, mid-watch
     join picked up, idle CPU bounded (assert poll/dispatch counts, not
     timing flakiness); handler-failure test: raising handler → cursor
     unmoved → re-delivery → advances + warns after 3 strikes; mid-watch
     leave stops display within the refresh interval; drop-to-zero then
     rejoin continues.
   - Done: integration tests green under `-n auto`.
   - Gate: stop if the subclass needs to edit vendored internals beyond
     the named overrides + wrapper/cursor plumbing — that means the
     vendored copy drifted; re-evaluate against Q1/Q2/Q6 instead of
     patching deeper.
8. CLI.
   - Files: `taut/cli.py`, `taut/__main__.py`, `tests/test_cli.py`.
   - argparse tree exactly [TAUT-8.1]; global flags incl.
     `-t/--timestamps` (ids in human output; `say -t` prints the new id);
     rendering (stdout content / stderr hints, no prompts when not a
     tty); `--json` ndjson with a defined shape for **every** verb per
     [TAUT-8.2] (writers echo their message object; join/leave echo
     their notice; whoami/rejoin emit member objects; init emits
     `{db, created}`) — foreign bodies emit the same five message
     fields ([TAUT-6.3]); exit codes 0/1/2 incl. `watch` exit 2 on zero
     memberships and `who` exit 2 on a missing thread.
   - Tests: drive the console entry point as a subprocess (simplebroker's
     `run_cli` harness pattern); assert exit codes per verb table and
     JSON field names; `watch` smoke test with timeout.
   - Done: walking the [TAUT-8.1] table against the real CLI matches
     row-for-row.
   - Gate: stop if any verb or flag not in [TAUT-8.1] appears — amend the
     spec first ([DOM-6]) or drop it.
9. Docs, release checklist, and wrap-up.
   - Files: `docs/implementation/04-taut-architecture.md` (rationale,
     boundaries, key files, governing specs per [DOM-7]),
     `docs/implementation/00-implementation-index.md`,
     `docs/implementation/02-repository-map.md`, `CHANGELOG.md`,
     spec `## Related Plans` confirmation, `docs/lessons.md` if earned.
   - Release checklist (the I7 door; releasing is *not* part of this
     plan): spec-conformance pass over envelope/DDL/JSON-fields/exit
     codes, `SchemaVersionError` path proven, README claims audited
     against implemented behavior.
   - Done: [DOM-8] alignment holds; final independent review run.

## 6. Testing Plan

Harness: pytest + pytest-xdist (`uv run pytest`, `-n auto`), one test
module per source module as listed in tasks, plus `tests/conftest.py`
providing tmp-dir database fixtures.

What must stay real (anti-mocking posture, [TAUT-11]):

- SimpleBroker, always. No fake queues, no mocked `Queue`. Tests operate
  on real `.taut.db` files under `tmp_path`.
- Process chains for identity *behavior* (selection, matching, rejoin):
  real spawned subprocesses. Only the per-platform `ps`/`/proc` *parsers*
  may run against recorded fixtures.
- The CLI entry point: subprocess-level (or `run_cli`-equivalent) so
  argparse, rendering, and exit codes are the tested article.
- Watcher concurrency: real threads and real writer subprocesses.

Acceptable mocks/stubs: none in core paths. Recorded `ps` output for
parser units; monkeypatched env (`TAUT_DB`, `TAUT_AS`) in config tests.

Contracts the tests protect: [TAUT-6.1] envelope shape, [TAUT-3.3] DDL,
[TAUT-7.2]/I6 cursor monotonicity, [TAUT-8.1] exit codes, [TAUT-8.2]
JSON fields, [TAUT-5.3] resolution order, [TAUT-8.4] no-redelivery and
no-busy-spin.

## 7. Verification and Gates

Per task: the task's named tests plus
`uv run ruff check taut tests && uv run ruff format --check taut tests`
and `uv run mypy taut tests`.

Final gates before calling the plan complete:

```bash
uv sync --all-extras
uv run pytest                       # full suite, -n auto via config
uv run ruff check taut tests
uv run ruff format --check taut tests
uv run mypy taut tests
uv build                            # packaging smoke
grep -rn "from weft\|import weft" taut/        # must be empty (I3)
grep -rn "simplebroker\._" taut/               # must be empty (I3)
grep -rnE "\.(read|read_one|read_many|read_generator|move|move_one|move_many|delete|delete_many|vacuum)\(" taut/ \
  | grep -v watcher.py                         # I2; watcher.py keeps the
                                               # vendored modes, unused
grep -rn "\.write(" taut/                      # must be empty (I5: the
                                               # write path is
                                               # insert_messages)
```

The grep gates are smoke checks, not the invariant itself: I2/I5 are
enforced by review and by the watcher/client tests; the greps just make
violations loud.

Observable success (post-merge, no deploy in the server sense): the
README Quick Start transcript executes verbatim in a fresh directory;
`taut watch` in one terminal renders a `taut say` from another within the
polling bound; `.taut.db` is the only artifact created.

## 8. Independent Review Loop

- Reviewer: a non-Claude agent family (codex preferred; gemini fallback)
  per [DOM-11] and `docs/implementation/03-agent-inventory.md`.
- Reviewer reads: `docs/specs/02-taut-core.md`, this plan, `README.md`,
  and the four sibling files in Required Reading items 2–4.
- Prompt: "Read the plan at docs/plans/2026-06-12-taut-foundation-plan.md.
  Carefully examine the plan and the associated code. Look for errors, bad
  ideas, and latent ambiguities. Don't do any implementation, but answer
  carefully: Could you implement this confidently and correctly if asked?"
- The authoring agent answers every point in this file (appendix section)
  by changing the plan/spec or recording why not. A reviewer "no" on the
  confidence question is a blocker.
- Round 1 (docs phase) completed 2026-06-12 with codex; all findings
  resolved in the appendix below, confirmation round run on the revised
  docs.
- Repeat after Task 6a (identity-lifecycle slice — the
  contradiction-prone area), optionally after 6b, and before Task 9
  wrap-up ([DOM-11], larger-change cadence).

## 9. Out of Scope

- TUI (`taut[tui]`): named in [TAUT-8.4]/[TAUT-12.4]; separate spec +
  plan.
- Postgres backend enablement and `.taut.toml` documentation
  ([TAUT-12.1]) — this plan only carries its obligations (I9). Redis is
  deferred pending its state-mapping design ([TAUT-12.2]).
- Captive agents / `summon` ([TAUT-12.3]); separate spec + plan.
- Message deletion, editing, retention, archival; `doctor`; member merge.
- Notifications daemon, shell-prompt integration (README pattern only).
- Code-signing fingerprint evidence; any authentication work.
- Publishing to PyPI (release checklist is prepared, not executed).
- No drive-by changes to simplebroker or weft; if either needs a fix,
  file it there, do not work around it with private imports here.

## 10. Fresh-Eyes Review

Re-read performed against the writing-plans checklist before publishing
this plan:

- Every task names exact files, read-first material, reuse, tests, a done
  signal, and a stop gate; invariants precede tasks; hidden couplings and
  the one-way door (first release) are explicit; anti-mocking posture is
  spelled out per surface; rollback story (revertible slices, no
  migrations, version-gate before release) is stated; comprehension
  questions cover the two highest-risk areas (peek-cursor watcher
  mechanics, config translation).
- Known soft spot, recorded deliberately: Hypothesis adoption is decided
  inside Task 3 rather than globally, to keep the dev-dependency decision
  next to its only consumer. If it spreads beyond envelope tests, revisit.
- Reviewer feedback appendix: round 1 and the round 2 confirmation are
  recorded below; the next review rounds run after Task 6 and before
  Task 9 per §8.

## Review Notes (appendix)

### Closed — live review findings, implementation phase (2026-06-12)

Filed by the watching reviewer (Claude). Items 1–2 blocked release per
`testing-patterns.md` rule 5 and are resolved; item 3 is launch-quality
(blocks public demo, not the PyPI name-claim publish).

1. **BLOCKER — identity capture truncation defeats cross-invocation
   recognition on macOS.** Repro (verified repeatedly against current
   code): shell 1 `taut join general` → auto-creates `bi`; shell 2
   `taut whoami` → `unrecognized caller`; shell 2 `taut say` → 
   auto-creates `ada`. Cause: `ps` clips `exe` to 16 chars
   (`/opt/homebrew/bi`), so the [TAUT-5.2] shell-skip never matches
   `bash`, the anchor lands on the per-command wrapper, and the wrapper
   dies with each command. Fix: capture the executable untruncated
   (`ps -ww`), and/or prefer `argv[0]` (captured in full) whenever
   `exe` does not end with `argv[0]`'s basename; have the shell/wrapper
   matcher consult the `argv[0]` basename as backstop. Required
   regression in a new `tests/test_identity.py`: join from one
   `sh -c` invocation, `whoami` from a second against the same db,
   assert the same member resolves ([TAUT-11] identity proofs).
   Status: RESOLVED 2026-06-12 — `basename` now prefers `argv[0]`
   over the clipped `exe`; the shell-skip works, anchors land on
   durable ancestors, and both regressions in `tests/test_identity.py`
   (anchor-location assertions; compound-command wrappers per the
   exec-optimization note baked into the file) are green. Full suite
   green at 29 tests. Residual split out as item 3.
3. **Handle quality — `args=` whitespace-splitting mangles paths with
   spaces.** The anchor now lands on the right process, but its
   `argv[0]` is cut at the first space, so any macOS app-bundle
   process (`/Users/…/Application Support/…`) yields handle
   `application` instead of e.g. `claude`. Recognition is unaffected
   (keyed on pid+start-time); this is a demo/launch-quality defect,
   not a correctness one — it does not block publishing 0.1.0 to
   claim the PyPI name, but should be fixed before any public demo.
   Prescription: reconstruct `argv[0]` by incrementally joining
   `args=` tokens while the joined prefix is an existing executable
   path (Linux `/proc` argv is NUL-separated and unaffected); keep
   `comm=` only as a last-resort fallback. Status: RESOLVED
   2026-06-12 in the 0.1.1 hardening slice — `psutil` is the primary
   capture path; the fallback reconstructs `argv[0]` and uses it before
   truncatable `comm=` evidence. Regression coverage:
   `test_ps_argv_reconstruction_preserves_argv0_paths_with_spaces` and
   `test_ps_fallback_uses_reconstructed_argv0_before_truncated_comm`.
2. **Spec gap — `say` to a non-member thread.** Implementation refuses
   ("X is not a member of THREAD"); [TAUT-8.1]'s say row never defined
   non-member behavior. RESOLVED: spec ratifies the refusal — exit 2
   with a `taut join` hint, mirroring `read` ([TAUT-8.1] say row
   updated 2026-06-12). Implementation should confirm its exit code
   matches.

### Round 5 — codex, 2026-06-12 (0.1.1 implementation review)

Read-only reviewer verdict before fixes: not approved for the 0.1.1
hardening gate. All findings accepted and resolved before final gates:

1. [TAUT-5.1] fallback capture still preferred truncatable `comm=` as
   `exe`. Fixed in `taut/identity.py`; fallback capture now stores
   reconstructed `argv[0]` first, with `comm=` only as last resort.
2. README Quick Start byte-shape diverged from code/tests for `list` and
   `log -t --limit 1`. Fixed in `README.md` to match the grouped renderer
   contract and two-space list count shape.
3. Token proof could be masked by ordinary anchor recognition. Fixed by
   changing the identity test to create an unanchored token-bearing member
   while the live chain resolves a different anchored member; token
   resolution must now beat a concrete conflicting anchor.
4. Poison-message warning was implemented but untested. Fixed by asserting
   the `taut.watcher` warning in the poison-advance regression.
5. Completion trail was inconsistent. Fixed by closing the live handle
   finding here and recording this Round 5 disposition.

Focused read-only codex re-review after these fixes: approved; no
release-blocking mismatch remained in the scoped TAUT-5.1 fallback,
README byte-shape, TAUT-11 token proof, poison-warning test, or ledger
areas. Residual noted by the reviewer: the token proof is a
conflicting-live-anchor proof rather than a literal unrelated-process-tree
fixture, but it proves the load-bearing rule that token resolution beats
anchor recognition.

Grok review for this round was attempted with the local Grok CLI, but the
process hung after environment/plugin warnings and returned no findings
before interruption. Substitute review evidence for this slice is the
completed read-only codex pass above plus the full verification gates.

### Round 1 — codex, 2026-06-12 (docs phase)

Verdict: "could not implement confidently" — treated as a blocker; every
finding verified against source before action. All ten accepted.

1. BLOCKER, target resolution: confirmed — bare `Queue(name, config=…)`
   resolves the cwd (`_default_target_from_config` → 
   `target_for_directory`) and SimpleBroker auto-creates missing SQLite
   files on open. Fix: [TAUT-3.2] rewritten to name
   `resolve_broker_target()` as the discovery call (`None` → init hint),
   require an existence check on explicit paths, and define `taut init`
   as the only creation path; Task 6 and required reading updated.
2. BLOCKER, write ids: confirmed — `Queue.write()` returns `None`. Fix:
   [TAUT-3.5] now mandates the `generate_timestamp()` + 
   `insert_messages()` write path for all messages and notices; I5 and
   Task 6 updated; a `\.write(` grep gate added.
3. BLOCKER, read/unread conflicts: confirmed. Fix: [TAUT-5.4] now states
   `read` requires a resolved member and membership (guests get
   `list`/`log`/`who`/`whoami`); [TAUT-4.3] scopes implicit join to
   sub-threads with parent-room membership; [TAUT-8.1] read row carries
   the miss/hint behavior; README opening and Quick Start rewritten so
   every transcript is reproducible under the spec (agent joins before
   reading; unread counts come from another participant's messages).
4. BLOCKER, watcher failure semantics: confirmed and sharpened —
   `_safe_call_handler` returns normally when the error handler says
   "continue", so post-dispatch advancement would skip failed messages.
   Fix: [TAUT-8.4] now requires advancement inside taut's handler
   wrapper after the user handler returns, adds the 3-strikes poison
   rule, and names the data-version-callback extension for membership
   refresh; Task 7 and Q6 updated; handler-failure test added.
5. BLOCKER, identity collisions: accepted — `--as` semantics and anchor
   uniqueness contradicted. Fix: [TAUT-5.3] now defines acting-as
   (never re-anchors), anchored-vs-unanchored creation under `--as`,
   and the suffix rule for all handle collisions (cross-ref corrected
   to [TAUT-5.4]); [TAUT-5.5] states the rejoin precondition exactly.
6. SHOULD-FIX, sidecar/message atomicity: accepted. Fix: [TAUT-10] adds
   the ordering rule (authoritative sidecar state first, message last;
   notices best-effort; idempotent upserts), mirrored in plan couplings
   and Task 6.
7. SHOULD-FIX, foreign JSON shape: accepted; codex's recommendation
   adopted — output always carries the five [TAUT-8.2] fields, `v` is
   envelope-internal ([TAUT-6.3] updated).
8. SHOULD-FIX, suffix resolution mechanism: accepted. Fix: [TAUT-8.1]
   reply row specifies a bounded public-API scan (most recent 1,000 ids
   via peek), keeping I3 intact; Task 6 updated.
9. SHOULD-FIX, `-t` and grep gates: accepted. Fix: `-t/--timestamps` is
   now a global option in [TAUT-8.1], README, and Task 8; §7 gates
   extended to the full consuming-API set plus `\.write(`, with a note
   that greps are smoke checks, not the invariant.
10. NIT, stale "README is empty": fixed in §3.

### Round 2 — codex, 2026-06-12 (confirmation on revised docs)

All ten round-1 findings confirmed RESOLVED with section-level citations.
Standing question answered **yes** ("I could implement the plan
confidently and correctly"), with one assumption and two residual items,
both fixed:

- `path=` vs `db_path=` constructor keyword mismatch between Task 6 and
  [TAUT-3.2] — plan corrected to `db_path=` (spec authoritative).
- Stale "pending first review round" line in Fresh-Eyes Review —
  corrected.

Timing note: round 2 ran against the pre-roadmap text. The same-day
scope addendum (below) was not part of that round and is queued for the
next scheduled review.

### Round 3 — adversarial, 2026-06-12 (codex + author pass; alternates blocked)

Stance: break the design with concrete failure scenarios, covering the
post-round-2 additions ([TAUT-12], host-aware identity, 6a/6b split,
cursor batching). Reviewer panel: codex (different family from the
author; gemini, qwen, kimi, and grok were attempted and are blocked —
states recorded in `docs/implementation/03-agent-inventory.md`) plus an
independent author-adversarial pass. Codex produced 10 findings (5
BLOCKER, 4 SHOULD-FIX, 1 NIT); the author pass produced 5, of which 3
were subsumed by codex's stronger versions. All accepted and applied:

1. C1/A2/A3 (BLOCKER) — cursor semantics underdefined for notices and
   room creation; README transcripts non-reproducible. Fixed:
   [TAUT-7.4] now covers every written message incl. notices, defines
   creator-advance and join-at-zero; README opening transcript carries
   the creation notice.
2. C2 (BLOCKER) — identity uniqueness had no schema backstop against
   concurrent auto-create. Fixed: two partial unique indexes in
   [TAUT-3.3] + lost-race re-resolve rule; Task 4/6a updated.
3. C3/A1 (BLOCKER) — hostname is not a host identity (macOS renames,
   container collisions). Fixed: `host_id` (machine-id/IOPlatformUUID/
   fallback) + `host_label` split across [TAUT-3.3]/[TAUT-5.1]/
   [TAUT-5.3]; Tasks 4–5 updated.
4. C4 (BLOCKER) — `--json` promised globally, defined partially. Fixed:
   [TAUT-8.2] defines a shape for every verb (writers echo their
   message object; join/leave echo notices; member objects; init).
5. C5 (SHOULD-FIX) — `watch` with zero memberships hits the vendored
   empty-config ValueError. Fixed: exit 2 at start, idle-at-zero while
   running ([TAUT-8.1], Task 7).
6. C6 (SHOULD-FIX) — leave-during-watch displays briefly. Fixed:
   membership "iff" is convergence-bounded for running watchers
   ([TAUT-4.3]); test added.
7. C7 (BLOCKER) — "sidecar first" ordering let a cursor advance precede
   the insert, skipping concurrent messages on crash. Fixed: three-step
   ordering with cursor last/best-effort ([TAUT-10], [TAUT-7.4],
   couplings, Task 6b).
8. C8 (SHOULD-FIX) — full ids must bypass the 1,000-id suffix window.
   Fixed: exact-peek path in [TAUT-8.1]; README states the window.
9. C9 (SHOULD-FIX) — ssh/container chains break recognition silently.
   Fixed: namespace-boundary rule + `TAUT_AS` propagation guidance
   ([TAUT-5.2], [TAUT-10], README).
10. C10 (NIT) — README start-time display implied parsing. Fixed: raw
    token shown verbatim.
11. A4 — `who` exit codes lacked the not-found case. Fixed: exit 2 row.
12. A5 — a stray `.taut.toml` selecting a server backend resolved into
    undefined behavior in v0.1. Fixed: explicit unsupported-backend
    refusal ([TAUT-3.2]).

Held attacks (codex, recorded as design evidence): SimpleBroker API
shapes now match source; the peek-cursor watcher overrides close the
re-delivery spin; handler-failure cursor handling survives the
dispatch-swallowing path.

### Round 4 — grok, 2026-06-12 (adversarial, fresh family, post-addendum-2)

First round from a reviewer that had not shaped the docs (grok,
re-authorized; run from inside the repo — see the agent inventory and
the review-loops runbook for the CLI caveats). Scope: the addendum-2
identity UX (tokens, candidates, personas, join-at-now, name pools),
[TAUT-12.3], and cross-doc consistency; API-vs-source verification was
inherited from round 3 rather than repeated. Six findings, all applied:

1. G1 (BLOCKER) — the leading creation member-object line broke the
   documented `jq .ts` capture idiom on a first-ever write. Fixed:
   [TAUT-8.2] documents the creation line precisely (member fields +
   `token`, no `ts`, primary object follows) and the idiom is now
   field-selective (`select(has("ts"))`).
2. G2 — `--token` was used by resolution but missing from the global
   options surface. Fixed: global flag in [TAUT-8.1] and README; flag
   wins over `TAUT_TOKEN` env.
3. G3 — the candidate prompt gate was tty-only and undefined under
   `--json`/mid-pipe. Fixed: interactive iff stdin is a tty and neither
   `--json` nor `-q`; `--json` always takes the non-interactive path
   ([TAUT-5.4]).
4. G4 — `rejoin --token` was ambiguous between target selector and
   acting identity. Fixed: [TAUT-5.5] defines target selection
   precedence (HANDLE > global `--token`/`--as`), HANDLE+`--token`
   errors, target = acting member for attribution; rejoin row updated
   to `rejoin [HANDLE]`.
5. G5 — persona power and the creation-object shape with `--persona`
   were implicit. Fixed: [TAUT-5.9] states any writer may set any
   persona via `--as` (trust model); creation object includes persona.
6. G6 (NIT) — `whoami` exit-code row lacked the error case. Fixed.

Held attacks (grok): line-by-line transcript trace under join-at-now —
every README transcript reproduces (independently confirming the
author's trace); token/`--as` precedence has no silent-fall-through
hole; the frozen schema additions (token/meta/host_id) carry their
forward-compat rules, no regret vector found.

### Implementation review — Claude, 2026-06-12 (post-build)

Claude reviewed the implemented tree against this plan, the core spec, and
SimpleBroker/Weft source. Findings and disposition:

1. Watcher focus scenario: verified fixed in code — explicit filtered
   threads missing during refresh drop instead of killing the watcher. The
   test gap was real: direct `_refresh_memberships()` coverage was not
   enough. Added live watcher tests for subprocess writers, cursor
   persistence/no re-dispatch, poison advancement, filtered leave, and
   drop-to-zero-then-rejoin.
2. Global `--token` missing from the CLI. Fixed in argparse, option
   hoisting, and `TautClient` construction; added CLI tests before and
   after the command.
3. Invalid `TAUT_TOKEN` on `whoami` exited 2 instead of 1 because
   `TokenError` is an `IdentityError`. Fixed by ordering the exit-code
   mapping and adding a CLI regression.
4. Membership interval refresh only ran from `_drain_queue()`, so an idle
   watcher with a native backend waiter could miss membership changes.
   Fixed by making an expired membership timer count as pending work, and
   documented the invariant in the architecture guide.
5. `TokenError` and `NotFoundError` were missing from the public package
   exports. Fixed and tested.
6. `reply` membership failures and rejoin selector precedence were
   under-documented. Spec rows were aligned; bare `rejoin` now accepts the
   global `--token`/`--as` selector, and handle-plus-token ambiguity is
   rejected for both subcommand and global token forms.
7. The review noted guest bare `list` as a product choice. Left as-is:
   bare `list` means unread joined threads; guests have no joined threads
   and can use `list --all`.

### Scope addendum 2 — 2026-06-12 (user direction, post-round-3): join/rejoin UX

Five identity-flow directions folded into the spec:

1. Continuity tokens ([TAUT-5.8], `token` column): minted at creation,
   shown once, `TAUT_TOKEN` acts-as from any process tree; invalid
   token errors loudly; `rejoin --token`. Continuity, not
   authentication — plaintext on purpose.
2. Candidate presentation ([TAUT-5.4]): unrecognized state-changing
   callers get ranked candidates — interactive prompt on a tty,
   auto-create + candidate hint off-tty (agents never get prompts);
   `join --new` bypasses.
3. Personas ([TAUT-5.9], `meta` JSON column): saved per-member
   prompt/description, set via `join --persona`, surfaced in member
   objects; system-prompt seed for [TAUT-12.3].
4. Join starts at now ([TAUT-7.4]): membership cursor initializes to
   the join notice's timestamp; `log` is the rewind. **Supersedes the
   round-3 C1 resolution's join-at-zero rule**; one carve-out, implicit
   sub-thread join by read starts at 0. README transcripts re-verified
   under the new rule (opening demo now uses `log` for catch-up).
5. Knockoff handle pools ([TAUT-5.4]): `claude` → `claudette`,
   `claudius`, … → historical pool → numeric backstop; deterministic
   first-unused order for reproducible tests.

Schema v1 grew `token` (UNIQUE) and `meta` before the release freeze.
Tasks 2, 4, 6a and [TAUT-11] updated. These deltas are review input for
the post-Task-6a round.

### Scope addendum — 2026-06-12 (user direction, post-round-2)

Planned moves folded into the spec as [TAUT-12]: Postgres backend with
multi-host (obligations live in I9 and Tasks 4–5: host-aware identity,
qmark-only sidecar SQL, no stray SQLite assumptions), Redis deferred
pending a state-structure mapping (sidecar tables are a SQL-backend
mechanism; on Redis, taut state becomes a second connection to the same
instance under `taut:*` keys — [TAUT-12.2]), and captive agents
(`summon`) as a future spec. The [TAUT-12] text and these plan deltas
are review input for the post-Task-6 round.
