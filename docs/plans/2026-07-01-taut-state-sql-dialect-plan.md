# Plan: Introduce `TautState` and `SqlDialect`

Date: 2026-07-01
Status: Implemented
Risk: Moderate-high. This is intended to preserve behavior, but it crosses the
state-access boundary used by every client and watcher command.
Companion runbook: `docs/agent-context/runbooks/hardening-plans.md` (required
input because this changes storage ownership and the internal state contract).

## 1. Goal

Introduce a private `TautState` module interface and a narrow `SqlDialect`
implementation seam so Taut state access no longer leaks SQL, sidecar sessions,
or backend-specific SQL details into `TautClient` and `TautWatcher`. Keep the
current SQLite and Postgres behavior unchanged. The first adapter remains a
SimpleBroker sidecar SQL adapter; Redis/Valkey state mapping and public backend
plugins remain future work.

## 2. Source Documents

Source specs:

- `docs/specs/02-taut-core.md` [TAUT-3.1] - all durable Taut state lives in the
  resolved SimpleBroker target; no extra caches or state directories.
- `docs/specs/02-taut-core.md` [TAUT-3.3] - sidecar schema, version checks,
  identity/member/thread/membership tables, and schema evolution rules.
- `docs/specs/02-taut-core.md` [TAUT-3.4] - Taut uses only public SimpleBroker
  APIs and never writes SQL against SimpleBroker-owned tables.
- `docs/specs/02-taut-core.md` [TAUT-3.5] - one SimpleBroker timestamp domain and
  one message write path.
- `docs/specs/02-taut-core.md` [TAUT-7.2], [TAUT-7.4] - cursor monotonicity and
  sender cursor ordering.
- `docs/specs/02-taut-core.md` [TAUT-8.3], [TAUT-8.4] - `TautClient` API and
  watcher cursor/membership behavior.
- `docs/specs/02-taut-core.md` [TAUT-10] - compound-operation ordering and
  failure windows.
- `docs/specs/02-taut-core.md` [TAUT-11] - anti-mocking proof obligations.
- `docs/specs/02-taut-core.md` [TAUT-12.1] - Postgres extension boundary,
  qmark-placeholder sidecar SQL, and shared SQLite/Postgres test expectations.
- `docs/specs/02-taut-core.md` [TAUT-12.2] - every Taut state read and write must
  flow through one state module before a future Redis state mapping can exist.
- `docs/specs/03-identity-addressing-notifications.md` [IAN-3], [IAN-4],
  [IAN-7], [IAN-8] - identity claims, mutable names, notification ordering, and
  channel rename state.

Supporting context:

- `docs/implementation/04-taut-architecture.md` currently says all Taut-owned
  relational state flows through `taut/schema.py`; this plan replaces that file
  as the production seam with `taut/state/`.
- `../simplebroker/simplebroker/_backend_plugins.py` proves the real
  SimpleBroker backend seam: SQLite, Postgres, and Redis adapters satisfy one
  backend plugin contract. Taut should borrow the "one resolved backend target,
  one adapter slot" discipline, not copy SimpleBroker's public plugin machinery.
- `../simplebroker/extensions/simplebroker_redis/tests/test_redis_sidecar.py`
  proves Redis has no SQL sidecar. That validates [TAUT-12.2], but Redis remains
  out of scope for this refactor.

## 3. Context and Key Files

### Current structure

`taut/schema.py` is both the sidecar SQL implementation and the state-access
interface. It defines row `TypedDict`s, DDL strings, schema-version checks,
member/claim/thread/membership/cursor/rename helpers, JSON conversion, SQL row
conversion, and route-key collision enforcement.

The current client surface (`taut/client/` if the split has landed, otherwise
`taut/client.py`) imports `taut.schema` directly and references it throughout
command orchestration and type annotations. The client also owns message writes,
identity capture, envelope conversion, notification rendering, queue
construction, and CLI-visible semantics. This means storage mechanics are mixed
into the public behavior owner.

`taut/watcher.py` also imports `taut.schema` directly for membership refresh and
cursor advancement. This gives the watcher its own storage path instead of
crossing the same state seam as the client.

Tests currently use `taut.schema` directly, especially `tests/test_schema.py`.
Postgres-specific sidecar checks live in
`extensions/taut_pg/tests/test_pg_sidecar.py`. Shared backend behavior is
exercised through `tests/test_shared_contract.py` and `bin/pytest-pg`.

### New target structure

Introduce a new private package:

```text
taut/state/
  __init__.py       # internal exports: TautState, SqlSidecarTautState, row types
  _types.py         # row TypedDicts and small state-owned value types
  _dialect.py       # minimal SqlDialect marker and Taut-target dialect selection
  _sql.py           # SqlSidecarTautState and all Taut-owned SQL
```

`taut/schema.py` should stay during this refactor as a compatibility forwarding
module for existing internal tests and any unpublished local imports. Production
code must move off it. Removing or deprecating `taut/schema.py` is a later,
separate cleanup after direct production imports are gone.

Compatibility warning: `taut/schema.py` wrappers receive only a `Queue`. They
must **not** infer dialect from `Queue.db_target`; a bare string target can be a
SQLite path in the `TautClient` path or a backend target/DSN in other
SimpleBroker construction paths. During this refactor the wrappers may rely only
on SQL that is deliberately portable across supported SQL sidecar backends. If a
real SQLite/Postgres SQL divergence is introduced before the wrappers are
removed, the plan must be revised so wrapper callers pass an explicit dialect or
stop using the wrappers.

### Required reading before implementation

- `taut/schema.py` in full. Understand which helpers are pure row lookup, which
  open sidecar transactions, and which enforce cross-table invariants.
- The current client surface in full. If the client-module split has landed,
  read `taut/client/`; otherwise read `taut/client.py`. Identify every current
  `schema.*` reference, including type annotations, and whether it is part of
  command orchestration, identity resolution, message write ordering,
  notification write ordering, or rendering.
- `taut/watcher.py:527-710`. Understand why membership refresh and cursor
  advancement are coupled to watcher liveness.
- `tests/test_schema.py`, `tests/test_client.py`, `tests/test_shared_contract.py`,
  and `extensions/taut_pg/tests/test_pg_sidecar.py`. These are the current proof
  surface for SQL state behavior.
- `../simplebroker/simplebroker/_sidecar.py`. Confirm that sidecar SQL must use
  qmark placeholders and that `SidecarSession` is scoped to its `with` block.

Comprehension checks:

1. Which state writes must happen before a broker message write, and which cursor
   writes must happen after a broker message write? Answer this from [TAUT-10]
   before moving any call.
2. Which failures are fatal and which are best-effort? In particular,
   notification write failure must not roll back a successful source chat write,
   and sender cursor advance is best-effort after insert.
3. Which SimpleBroker APIs are public and allowed here? The implementation may
   use `Queue.sidecar()`, `SidecarSession.run()`, `open_broker()`, and resolved
   broker targets. It must not import SimpleBroker underscore modules.
4. Does a proposed `TautState` method expose SQL, `Queue`, `SidecarSession`, raw
   JSON columns, or backend names to callers? If yes, the seam is too shallow.
5. Where does dialect information come from? The only safe production answer in
   this refactor is the already resolved Taut target held by `TautClient`, not a
   bare `Queue`.

## 4. Invariants and Constraints

Behavior and contracts:

- Public CLI behavior, Python method signatures, dataclass fields, JSON shapes,
  exit codes, and exception types do not change.
- The on-disk/on-server schema version does not change in this refactor. No
  migration, new table, or data rewrite is planned.
- Taut state still lives in the resolved SimpleBroker target. SQLite uses
  `.taut.db`; Postgres uses the configured `.taut.toml` target/schema.
- Message queues remain SimpleBroker-owned. Taut state code must not read or
  write SimpleBroker message/meta/alias tables directly.
- Message writes stay in `TautClient`, through
  `Queue.generate_timestamp()` plus `Queue.insert_messages([(body, ts)])`.
  `TautState` owns sidecar state only.
- Sidecar SQL continues to use qmark placeholders. SimpleBroker translates them
  for Postgres.
- `BIGINT` stays the documented storage type for timestamps, process ids, and
  uid-like values so Postgres does not truncate values SQLite accepts.
- Cursor advancement remains monotonic. A refactor must never create a path that
  can move `last_seen_ts` backwards.
- Compound operation ordering from [TAUT-10] stays intact. Do not combine broker
  queue writes and sidecar writes into one invented transaction; SimpleBroker
  explicitly does not support that.
- Watcher membership refresh must continue to work through both backend wake
  signals and the interval backstop. Moving membership reads behind message
  presence checks is a regression.

Boundaries:

- `TautState` is an internal module interface, not a public extension contract.
  Do not add entry points, plugin loading, Redis code, or a user-facing backend
  API.
- `SqlDialect` is an internal helper for SQL syntax and DDL details that vary
  between SQLite-like and Postgres-like sidecars. It must not become a second
  storage interface. In the first slice it is deliberately a minimal SQL-shape
  marker (`portable`, `sqlite`, or `postgres`) plus a documented extension point;
  do not add SQL fragment methods until a concrete SQLite/Postgres difference
  and a failing shared test require one. `portable` is allowed only for
  `taut/schema.py` compatibility wrappers while the SQL text remains identical
  across supported SQL sidecar backends; production client/watcher state access
  must use `sqlite` or `postgres`.
- Prefer one `SqlSidecarTautState` adapter with a dialect helper until concrete
  SQL divergence proves separate SQLite/Postgres adapters are deeper.
- Use the already resolved Taut broker target to select dialect. Do not inspect
  SimpleBroker private attributes or import `simplebroker._targets`. Do not use
  `Queue.db_target` in compatibility wrappers as a generic dialect source.
- Keep `taut/schema.py` as a compatibility layer for this slice. Production code
  should no longer import it; tests may keep using it temporarily only where they
  are explicitly testing compatibility.

Design constraints:

- Do not create a one-method-per-`schema.py` wrapper and call it done. The
  adapter may keep private helper methods internally, but the `TautState`
  interface should be shaped around Taut state operations.
- Do not move command semantics into the state adapter. For example, the adapter
  may create or fetch membership rows, but it should not decide CLI exit codes,
  render messages, parse addresses, or write chat envelopes.
- Do not introduce a new runtime dependency. If a dependency seems necessary,
  stop and propose it to the human per `docs/lessons.md`.
- Do not edit unrelated dirty files. The current worktree may contain other
  changes; work with them and keep this refactor's diff scoped.

Rollback and rollout:

- Rollback is code-only: revert the refactor commit(s). Because the schema
  version and stored data shape do not change, no data rollback is needed.
- Rollout is ordinary release gating: land only after SQLite, shared Postgres,
  lint, format, type, and build gates pass.
- Post-deploy success signal is absence of SQLite/PG divergence in CI and no
  user-visible change in CLI/API behavior.

## 5. Tasks

1. **Add failing state contract tests for the new seam.**
   - Files to touch: add `tests/test_state_contract.py`; optionally update
     `extensions/taut_pg/tests/test_pg_sidecar.py` only if the same contract
     cannot run through the root shared harness.
   - Read first: `tests/conftest.py` backend marker rules, `tests/test_schema.py`,
     and `tests/test_shared_contract.py`.
   - Required shape: mark portable state contract tests with
     `@pytest.mark.shared` so they run under both default SQLite and
     `bin/pytest-pg`.
   - Prove at least these state invariants through the planned interface:
     schema initialization/version read, member name/alias uniqueness, claim hash
     mapping, membership lookup/listing, monotonic cursor advance, and channel
     rename sidecar state.
   - Tests must use real `Queue`/`TautClient`/sidecar state. Do not mock the
     broker, sidecar session, SQL runner, or identity rows.
   - Red-green expectation: tests initially fail because `taut.state` and the
     new state factory/interface do not exist.
   - Stop and re-evaluate if the tests need backend-specific assertions beyond
     fixture setup; that likely means the interface is leaking SQL dialect.
   - Done signal: the new tests fail for the missing interface or missing method,
     not because of unrelated setup errors.

2. **Create the state package and move row types.**
   - Files to touch: `taut/state/__init__.py`, `taut/state/_types.py`,
     `taut/schema.py`.
   - Move `MemberRow`, `IdentityClaimRow`, `ThreadRow`, `MembershipRow`,
     `ChannelRenameRow`, and `ThreadKind` into `taut/state/_types.py`.
   - Re-export those types from `taut/state/__init__.py`.
   - Update `taut/schema.py` to import/re-export the same names so existing tests
     and local callers still type-check.
   - Do not move SQL or behavior yet.
   - Verify: `uv run pytest tests/test_schema.py -q` and `uv run mypy taut tests
     bin/release.py`.
   - Done signal: row types have one owner, `taut.schema.MemberRow` still works,
     and no production behavior changed.

3. **Introduce `SqlDialect` and dialect selection.**
   - Files to touch: `taut/state/_dialect.py`, `taut/state/__init__.py`, tests
     from Task 1.
   - Define a small `SqlDialect` type. Initial responsibility is SQL-shape
     identity only: `portable`, `sqlite`, or `postgres`. It should have a
     docstring that says it is the designated home for future backend-specific
     SQL, but the first refactor must not invent SQL fragment methods without a
     concrete divergence.
   - Define explicit constants such as `PORTABLE_SQL_DIALECT`,
     `SQLITE_SQL_DIALECT`, and `POSTGRES_SQL_DIALECT`. `PORTABLE_SQL_DIALECT` is
     only for old `taut/schema.py` wrappers and means "use only SQL known to be
     valid on every supported SQL sidecar backend." It is not a backend identity
     and must not be returned by production dialect selection.
   - Define `dialect_for_taut_target(target: BrokerTarget | str) -> SqlDialect`,
     using the resolved target object already held by `TautClient`. This function
     is only valid for Taut-resolved targets: plain strings mean explicit SQLite
     filesystem paths because `TautClient._resolve_target()` enforces that
     contract. A resolved target with `backend_name == "postgres"` means
     Postgres. Unknown SQL sidecar backends should fail clearly instead of
     guessing.
   - Add a docstring or comment warning that `dialect_for_taut_target()` must not
     be used on arbitrary `Queue.db_target` values. A bare string there may be a
     backend DSN, not a SQLite path.
   - If an implementer wants to add a `SqlDialect` method that emits SQL or DDL,
     stop unless they can name the concrete SQLite/Postgres difference and the
     shared SQLite/PG test that fails without it.
   - Keep qmark placeholders in every statement, including Postgres.
   - Do not import SimpleBroker private modules. If a needed backend fact is not
     available from the public resolved target, stop and re-plan.
   - Verify: targeted dialect unit tests plus `uv run mypy taut tests
     bin/release.py`.
   - Done signal: dialect selection is public-API clean and has not changed any
     schema behavior.

4. **Implement `SqlSidecarTautState` behind `TautState`.**
   - Files to touch: `taut/state/_sql.py`, `taut/state/__init__.py`,
     `taut/schema.py`.
   - Define a `TautState` `Protocol` in `taut/state/__init__.py` or a small
     adjacent module. It is internal, but it should still be typed.
   - Implement `SqlSidecarTautState(queue: Queue, dialect: SqlDialect)`.
   - Move DDL, JSON conversion, row conversion, and SQL helpers from
     `taut/schema.py` into `taut/state/_sql.py`.
   - Keep all `Queue.sidecar()` usage inside `_sql.py`.
   - Convert `taut/schema.py` functions into forwarding wrappers that construct
     or use `SqlSidecarTautState(queue, PORTABLE_SQL_DIALECT)` and preserve old
     names for this slice. These wrappers must not infer dialect from
     `Queue.db_target`. They are temporary compatibility for the current
     dialect-neutral SQL only. If `_sql.py` gains dialect-sensitive SQL before
     wrappers are retired, revise the plan so old wrapper callers pass an
     explicit dialect or move to `taut.state`.
   - Interface guidance: expose Taut state operations, not `SidecarSession` or
     raw SQL. It is acceptable for the SQL adapter to have private one-for-one
     helper methods internally, but the interface crossed by the client
     package/module and `watcher.py` should not mirror every old helper blindly.
   - Suggested operation clusters:
     - schema: `ensure_schema()`, `get_schema_version()`
     - members/identity: create/read/update member rows, claims, aliases, names,
       and route lookups
     - threads/membership: create/read/list threads, add/remove/list membership,
       monotonic cursor advance
     - rename: begin, update, list incomplete, and apply sidecar rename state
   - Stop and re-evaluate if `_sql.py` starts importing `taut.client`,
     `taut.watcher`, `taut.cli`, or envelope/address rendering modules. That
     means command semantics are moving into storage.
   - Verify: `uv run pytest tests/test_schema.py tests/test_state_contract.py -q`
     and mypy.
   - Done signal: new state contract tests pass on SQLite; `taut/schema.py`
     remains a compatibility wrapper.

5. **Move `TautClient` to the new state seam.**
   - Files to touch: `taut/client/` if the client split has landed; otherwise
     `taut/client.py`. Possibly tests that intentionally inspect internal state.
   - Add `self._state = SqlSidecarTautState(self._meta_queue,
     dialect_for_taut_target(self.target))` after `_meta_queue` is created. Use
     `self._state.ensure_schema()` instead of `schema.ensure_schema()`.
   - Update `TautClient.init()` to construct the state adapter for the init queue
     and call `ensure_schema()` through the adapter.
   - Replace production `schema.*` calls with `self._state.*` calls. This means
     both runtime calls and type annotations: import row types from `taut.state`
     (`MemberRow`, `MembershipRow`, `ThreadRow`, etc.), drop `schema.` prefixes,
     and remove now-unused `import taut.schema as schema` imports so ruff cannot
     hide a leftover dependency.
   - Keep message writes, address parsing, envelope conversion, notification
     warning handling, CLI-visible error decisions, and identity capture in
     `TautClient`.
   - Preserve ordering exactly. For each command with both sidecar state and
     broker writes (`join`, `leave`, `say`, `reply`, `rename`, notifications),
     compare before/after ordering against [TAUT-10] before marking the task done.
   - Stop and re-evaluate if a replacement changes a public method signature,
     exception type, JSON shape, or message/cursor ordering.
   - Verify: `uv run pytest tests/test_client.py tests/test_cli.py
     tests/test_shared_contract.py -q` and mypy.
   - Done signal: `rg -n "schema\\." taut/client` returns no matches if the
     client is a package, or `rg -n "schema\\." taut/client.py` returns no
     matches if it is still a module. The targeted client/CLI tests pass.

6. **Move `TautWatcher` to the same state seam.**
   - Files to touch: `taut/watcher.py`, possibly `tests/test_watcher.py`.
   - Replace direct `schema.list_memberships()` and `schema.advance_cursor()` with
     the `TautClient` state adapter, for example `self.client._state`.
   - Replace schema-qualified row annotations too. Import `MembershipRow` from
     `taut.state` and remove `import taut.schema as schema` when no runtime calls
     remain.
   - Preserve `TautWatcher`'s current startup validation: explicit thread filters
     fail strictly at construction when there is no membership, while refresh
     treats missing rows as convergence.
   - Preserve the interval refresh path. State reads must not be moved behind
     pending-message checks.
   - Stop and re-evaluate if this pushes the watcher toward constructing its own
     independent state adapter. The watcher should share the client's resolved
     target/state seam.
   - Verify: `uv run pytest tests/test_watcher.py tests/test_shared_contract.py -q`
     and mypy.
   - Done signal: `rg -n "schema\\." taut/watcher.py` returns no matches and
     watcher tests pass.

7. **Tighten direct SQL and sidecar ownership.**
   - Files to touch: `taut/state/_sql.py`, `taut/schema.py`, tests as needed.
   - Run ownership grep gates and fix any production leaks:
     - `rg -n "sidecar\\(" taut --glob '*.py'`
     - `rg -n "SELECT|INSERT|UPDATE|DELETE|CREATE TABLE" taut --glob '*.py'`
     - `rg -n "import taut\\.schema|from taut import schema|schema\\." taut --glob
       '*.py'`
   - Expected production result: sidecar calls and SQL statements live only in
     `taut/state/_sql.py` and the compatibility wrappers in `taut/schema.py`.
     Production client modules and `watcher.py` do not import or call `schema`.
   - Keep tests that intentionally exercise the compatibility wrapper, but prefer
     new contract tests against `taut.state`.
   - Stop and re-evaluate if the grep shows SQL moving into CLI, watcher, or
     client rendering code.
   - Done signal: the ownership grep output matches the expected exceptions and
     is recorded in the implementation notes or final change summary.

8. **Run SQLite and Postgres contract gates.**
   - Files to touch: none unless failures expose real refactor defects.
   - Commands:
     - `uv run pytest`
     - `uv run pytest -m shared`
     - `uv run ./bin/pytest-pg --fast`
     - `uv run ruff check taut tests bin extensions/taut_pg/taut_pg extensions/taut_pg/tests`
     - `uv run ruff format --check taut tests bin extensions/taut_pg/taut_pg extensions/taut_pg/tests`
     - `uv run --extra dev mypy taut tests bin/release.py extensions/taut_pg/taut_pg extensions/taut_pg/tests --config-file pyproject.toml`
   - If Postgres fails because dialect behavior differs, prefer fixing
     `SqlDialect` or `SqlSidecarTautState`; do not add backend-specific branches
     in `TautClient` or `TautWatcher`.
   - Done signal: all gates pass or each residual risk is explicitly tied to a
     known blocker.

9. **Update documentation and traceability.**
   - Files to touch:
     - `docs/implementation/02-repository-map.md`
     - `docs/implementation/04-taut-architecture.md`
     - `docs/specs/02-taut-core.md`
     - this plan, if implementation changes the sequence
   - Update repository and architecture docs so `taut/state/` is the state owner,
     `taut/schema.py` is described as compatibility or legacy forwarding, and
     `TautClient`/`TautWatcher` no longer directly own SQL access.
   - Add or keep a backlink to this plan under `docs/specs/02-taut-core.md`
     `## Related Plans`.
   - Do not change normative behavior in the spec unless implementation discovers
     that the current spec is wrong. If that happens, stop and re-plan before
     quietly changing both spec and code.
   - Done signal: the traceability chain is explicit:
     [TAUT-3], [TAUT-7], [TAUT-8], [TAUT-10], [TAUT-12.1], [TAUT-12.2] <->
     this plan <-> architecture doc <-> `taut/state/` code.

## 6. Testing Plan

Red-green posture:

- Task 1 should add failing tests for the new state seam before implementation.
  The expected first failure is missing `taut.state` interface or missing method.
- The rest of the work is behavior-preserving. Existing public behavior tests are
  the regression oracle, but they are not enough by themselves; the new state
  contract tests are the proof that the seam works across SQLite and Postgres.

Harness and files:

- Add `tests/test_state_contract.py` as the main contract suite for `TautState`.
  Mark portable cases `@pytest.mark.shared` so `bin/pytest-pg` runs them under
  Postgres.
- Keep `tests/test_schema.py` initially to prove compatibility wrappers and
  low-level SQLite behavior. Do not expand it as the main proof for new code.
- Keep `extensions/taut_pg/tests/test_pg_sidecar.py` focused on extension
  packaging and PG-only sidecar facts. Avoid duplicating the root shared state
  contract there unless the root harness cannot express the assertion.
- Run `tests/test_client.py`, `tests/test_cli.py`, `tests/test_shared_contract.py`,
  and `tests/test_watcher.py` after moving callers.

What must stay real:

- Real SimpleBroker queues.
- Real sidecar sessions.
- Real SQLite temp databases.
- Real Docker Postgres via `bin/pytest-pg` for shared backend acceptance.
- Real identity resolution where client/CLI behavior is under test.

Acceptable mocking:

- None on the state/broker path. Unit-style tests may use simple in-memory values
  for pure helper functions such as dialect selection from an already-resolved
  target, but not for `TautState` behavior.

Regression names:

- "SQL sidecar behavior differs between SQLite and Postgres."
- "`TautClient` bypasses the state module and directly couples to SQL helpers."
- "`TautWatcher` advances cursors through a separate storage path."
- "A cursor can move backwards or advance before the message write success point."
- "Postgres-visible integer values stay stored as `BIGINT`; this is a guard
  against future DDL drift, not a refactor-specific SQL-text change."

## 7. Verification and Gates

Per-task gates are listed in §5. Final gates before completion:

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

Ownership grep gates:

```bash
rg -n "schema\\." taut/client taut/watcher.py
rg -n "sidecar\\(" taut/client taut/watcher.py taut/cli.py
rg -n "SELECT|INSERT|UPDATE|DELETE|CREATE TABLE" taut/client taut/watcher.py taut/cli.py
rg -n "from simplebroker\\._|import simplebroker\\._" taut extensions tests
rg -n "Queue\\.write\\(" taut tests extensions
```

Expected results:

- No `schema.*` references from the client package/module or `taut/watcher.py`,
  including annotations.
- No sidecar calls or SQL strings in client, watcher, or CLI.
- No private SimpleBroker imports.
- No `Queue.write()` calls.
- Full SQLite and Postgres gates green.

Post-change success signal:

- CI remains green for both root and `taut-pg` workflows.
- No user-visible CLI/API diffs.
- Future SQL dialect changes have one code owner: `taut/state/_dialect.py` plus
  `taut/state/_sql.py`.

## 8. Independent Review Loop

Reviewer: a different agent family than the implementation author, per
`docs/specs/01-development-documentation-operating-model.md` [DOM-11].

Review timing:

- First review after Tasks 1-4, before moving `TautClient`. This reviews the
  load-bearing interface shape.
- Second review after Tasks 5-7, before final docs and release gates.

Files and docs for reviewer:

- This plan.
- `docs/specs/02-taut-core.md` [TAUT-3], [TAUT-7], [TAUT-8], [TAUT-10],
  [TAUT-11], [TAUT-12.1], [TAUT-12.2].
- `docs/specs/03-identity-addressing-notifications.md` [IAN-3], [IAN-4],
  [IAN-7], [IAN-8].
- `taut/state/`, `taut/schema.py`, the current client package/module
  (`taut/client/` or `taut/client.py`), and `taut/watcher.py`.
- `tests/test_state_contract.py`, `tests/test_schema.py`,
  `tests/test_shared_contract.py`, `extensions/taut_pg/tests/test_pg_sidecar.py`.

Review prompt:

> Read the plan at
> `docs/plans/2026-07-01-taut-state-sql-dialect-plan.md` and the associated
> code. Look for errors, shallow seams, hidden behavior changes, backend-specific
> leakage, weak tests, and ordering regressions. Do not implement anything. Could
> you implement or continue this refactor confidently and correctly from the
> plan?

Feedback handling:

- The authoring agent must answer each review point explicitly.
- If the reviewer identifies an ambiguity that would make implementation unsafe,
  update this plan before continuing.
- If the reviewer asks for a broader plugin system, Redis adapter, or schema
  migration, mark that out of scope unless a current spec requires it.

Implementation review response on 2026-07-01:

- Review found one remaining production type-annotation import from
  `taut.schema` in `taut/identity.py`. Fixed by importing `MemberRow` from
  `taut.state`.
- Review found the dialect selection seam under-tested. Fixed by adding shared
  tests for plain Taut SQLite paths, resolved SQLite targets, resolved Postgres
  targets, unknown resolved backends, and the rule that production dialect
  selection never returns `PORTABLE_SQL_DIALECT`.
- Review raised an existing behavior concern: explicit `--as` flows can create a
  claimless member when the captured identity claim already belongs to another
  member. This is not introduced by the `TautState` refactor and is out of scope
  for this behavior-preserving storage-seam change. Fixing it needs a separate
  identity semantics plan because it may change [IAN-3] command behavior and the
  trust model around explicit names.

## 9. Out of Scope

- Redis/Valkey state mapping, Redis Lua/WATCH logic, or `taut:*` key design.
- Public Taut backend plugins or entry points.
- Replacing SimpleBroker's backend plugin contract or adding a Taut-specific
  resolver.
- Schema version bump, migrations, new tables, or stored-data rewrites.
- Renaming public CLI verbs, changing Python API method signatures, or changing
  JSON field names.
- Moving message writes into `TautState`.
- Repairing or redesigning channel rename recovery beyond preserving the current
  marker/report behavior.
- Further client package restructuring beyond the current client split.

## 10. Fresh-Eyes Review

- The plan names the governing spec sections and the current state owner.
- The plan says what must not change before it says what to build.
- The highest-risk ordering rule is explicit: authoritative sidecar state before
  message writes where required, sender cursor after successful insert, and no
  invented broker/sidecar transaction.
- The plan avoids the weak version of the seam: it forbids a blind one-for-one
  wrapper while still allowing private SQL helper reuse inside the adapter.
- The plan gives a rollback path that does not depend on data migration.
- The plan has concrete grep gates to prove production SQL ownership moved.
- The plan keeps Redis and public plugin loading out of scope.
- The plan requires shared SQLite/Postgres state contract tests, not only
  SQLite-only helper tests.
