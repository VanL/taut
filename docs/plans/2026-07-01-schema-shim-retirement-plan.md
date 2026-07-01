# Plan: Retire the `taut/schema.py` compatibility shim

Date: 2026-07-01
Status: Implemented 2026-07-01 (see Implementation Record at end)
Risk: Low (test-only migration + deletion of a delegating shim; no production
importers; behavior cannot change).

## 1. Goal

`taut/schema.py` is a 361-line compatibility shim whose functions each delegate to
`SqlSidecarTautState` (`taut.state`). After the `TautState` refactor, **no production
code imports it** — only tests do. Retire the shim: migrate the ~13 remaining
`schema.*` call sites in three test files to `taut.state`, backfill the two focused
assertions unique to `tests/test_schema.py` into `tests/test_state_contract.py`, then
delete `taut/schema.py` and `tests/test_schema.py`. The result removes 361 lines of
production-import-dead code and stops the suite from partly exercising a compatibility
facade instead of the real state seam.

## 2. Source Documents

Source spec: `docs/specs/02-taut-core.md` [TAUT-3.3] (sidecar schema), [TAUT-12.2]
(single state module / swappable seam). No behavior change to either — this only
removes a transitional wrapper the spec never required.

Supporting context:
- `docs/plans/2026-07-01-taut-state-sql-dialect-plan.md` — the refactor that
  introduced `taut.state` and left `schema.py` as a labeled shim
  ("Production code should use `taut.state` … while the state seam lands",
  `taut/schema.py:1-5`). This plan is the "lands" step.

## 3. Context and Key Files

### What is being deleted

- `taut/schema.py` — thin function-per-method delegating shim. Each
  `schema.fn(queue, …)` constructs `SqlSidecarTautState(queue, PORTABLE_SQL_DIALECT)`
  and calls `.fn(…)` (see its private `_state()` helper at `taut/schema.py:27-28`).
- `tests/test_schema.py` — the shim's dedicated test suite.

### The state surface to migrate onto (public)

- `taut/state/__init__.py` exports `SqlSidecarTautState`, the `TautState` Protocol,
  the dialect markers (`PORTABLE_SQL_DIALECT`, `SQLITE_SQL_DIALECT`,
  `POSTGRES_SQL_DIALECT`, `dialect_for_taut_target`), and the row types.
- `SqlSidecarTautState(queue, dialect)` exposes the same method names the shim
  wrapped, as **bound methods** (no leading `queue` argument).

### Call sites to migrate (exact inventory)

Confirmed via `grep -oE 'schema\.[a-z_]+'`:

- `tests/test_client.py` (import `from taut import schema`, line 10): 6 calls —
  `list_members` (×3), `get_thread` (×2), `start_channel_rename` (×1). A `TautClient`
  instance is in scope in these tests.
- `tests/test_watcher.py` (import `import taut.schema as schema`, line 13): 4 calls —
  `get_membership` (×4).
- `extensions/taut_pg/tests/test_pg_sidecar.py` (import `from taut import schema`,
  line 11): `get_schema_version` (line 29), `insert_member` (72, 87),
  `add_member_alias` (103). **pg-only** — runs under `bin/pytest-pg`.

`tests/test_schema.py` (import line 10) is the shim's own suite and is deleted, not
migrated (see coverage note below).

### Coverage note (what must be preserved before deleting `test_schema.py`)

`tests/test_state_contract.py` already drives `SqlSidecarTautState` through
`ensure_schema`, `get_schema_version` (asserts `== 2`), `insert_member`,
`add_member_alias`, `add_identity_claim`, `get_member_by_claim_hash`, `upsert_thread`,
`add_membership`, `advance_cursor`, `get_membership`, `start_channel_rename`,
`incomplete_channel_renames`, `apply_channel_rename_sidecar`. The only two methods
`test_schema.py` exercises that `test_state_contract.py` does **not** are
`get_member_by_route_key` and `update_member_name`. Those two must be added to
`test_state_contract.py` before `test_schema.py` is deleted, so no focused coverage is
lost. (Both are also integration-tested via `set_name` and DM/mention routing in
`test_cli`/`test_shared_contract`, but the state-contract suite is the intended unit
home.)

### Comprehension checks

1. Why is this migration behavior-preserving by construction? (Answer:
   `schema.fn(q, …)` is literally `SqlSidecarTautState(q, PORTABLE_SQL_DIALECT).fn(…)`;
   the transform inlines the shim. Using the same queue `q` and the same
   `PORTABLE_SQL_DIALECT` reproduces identical SQL.)
2. Why keep `PORTABLE_SQL_DIALECT` rather than switch to
   `dialect_for_taut_target(...)`? (Answer: the shim always used PORTABLE, including
   for the pg-backed test; the dialect is currently cosmetic — `SqlDialect` carries
   only `name` and all SQL is portable qmark — so PORTABLE matches today's behavior
   exactly and avoids any incidental change.)

## 4. Invariants and Constraints

- **No production behavior change.** `taut/schema.py` has zero production importers
  (verified: the only `taut.schema` hits in `taut/` are f-string text in
  `state/_sql.py`). This is a test refactor + dead-shim deletion.
- **Mechanical 1:1 transform.** `schema.fn(q, …)` → `SqlSidecarTautState(q,
  PORTABLE_SQL_DIALECT).fn(…)` (or `client._state.fn(…)` only when `q` is exactly
  `client._meta_queue` — see Task 2). Do not change which queue an operation targets,
  its arguments, or its assertions.
- **No net coverage loss.** `test_schema.py` may only be deleted after
  `get_member_by_route_key` and `update_member_name` are asserted in
  `test_state_contract.py`.
- **Import surface:** migrate onto the public `taut.state` exports only. Do not import
  from `taut.state._sql` / `taut.state._types` directly.
- **Out of the client package:** no `taut/client/*` or `taut/watcher.py` change — they
  already use `taut.state`. This plan touches tests + deletes two files.
- **pg slice isolation:** the `test_pg_sidecar.py` change is only verifiable under
  Docker Postgres (`bin/pytest-pg`); do not claim it verified from the SQLite suite.

## 5. Tasks

1. **Backfill the two unique assertions into `tests/test_state_contract.py`.**
   - In `test_state_contract_preserves_identity_membership_cursor_and_rename` (or a new
     small sibling test), after a member is inserted, assert:
     `state.get_member_by_route_key(<route key of the display name>)` returns that
     member; and `state.update_member_name(member_id, "renamed")` then
     `state.get_member(member_id)["display_name"] == "renamed"` and the new route key
     resolves while the old one does not.
   - Reuse: `route_key` from `taut._constants`; the existing `state` fixture pattern in
     the file.
   - Verify: `uv run pytest tests/test_state_contract.py -q` green.
   - Done signal: both methods have a direct state-contract assertion.

2. **Migrate `tests/test_client.py` and `tests/test_watcher.py`.**
   - Replace the `schema` import with `from taut.state import SqlSidecarTautState,
     PORTABLE_SQL_DIALECT` (drop the `schema` import).
   - Transform each call: `schema.fn(Q, …)` → `SqlSidecarTautState(Q,
     PORTABLE_SQL_DIALECT).fn(…)`, keeping the identical `Q` and args. Optional
     cleanup: where `Q` is exactly `client._meta_queue`, `client._state.fn(…)` is
     equivalent and cleaner — use it only when the queue identity matches.
   - Files/sites: `test_client.py` (`list_members`×3, `get_thread`×2,
     `start_channel_rename`×1); `test_watcher.py` (`get_membership`×4).
   - Stop-and-re-evaluate gate: if any call passed a queue that is **not** the one the
     `SqlSidecarTautState` would bind, stop — the transform assumption is wrong for
     that site.
   - Verify: `uv run pytest tests/test_client.py tests/test_watcher.py -q` green.

3. **Migrate `extensions/taut_pg/tests/test_pg_sidecar.py`.**
   - Same transform for `get_schema_version`, `insert_member` (×2), `add_member_alias`,
     using `SqlSidecarTautState(queue, PORTABLE_SQL_DIALECT)` (mirrors what the shim
     did for this pg test today). Leave the `information_schema.tables` SQL query
     untouched — it is a raw DB assertion, not a `schema.*` call.
   - Verify: `uv run ./bin/pytest-pg --fast` green (requires Docker Postgres).

4. **Delete the shim and its test.**
   - `git rm taut/schema.py tests/test_schema.py`.
   - Grep gate: `git grep -n 'taut\.schema\|from taut import schema\|import taut.schema'`
     returns nothing (the `state/_sql.py` "taut schema version" f-strings are text, not
     imports — confirm they are the only remaining literal hits and they are not
     imports).
   - Verify: full suite green.

## 6. Testing Plan

- Harness: existing pytest suite (real `.taut.db`, broker never mocked — unchanged
  posture) for Tasks 1–2 and 4; `bin/pytest-pg` for Task 3.
- What proves it: the migrated call sites exercise `SqlSidecarTautState` directly and
  still pass; `test_state_contract.py` now asserts `get_member_by_route_key` and
  `update_member_name`; and the full suite is green with `schema.py` gone.
- Anti-mocking: unchanged — no new mocks; the state adapter and broker stay real.
- Do not add a re-export or "deprecation" stub for `schema` — the point is deletion.

## 7. Verification and Gates

Per-task verification is inline in §5. Final gates:

- `uv run pytest` → all green (expect the current count minus `test_schema.py`'s cases
  plus the two backfilled assertions).
- `uv run ./bin/pytest-pg --fast` → green (Task 3; Docker Postgres required — if
  unavailable, record it as unverified rather than claiming pass).
- `uv run mypy taut tests bin/release.py --config-file pyproject.toml` → clean (fewer
  source files once `schema.py` is gone).
- `uv run ruff check taut tests bin` and `ruff format --check` → clean.
- `git grep -n 'from taut import schema\|import taut.schema\|taut\.schema'` → no import
  matches anywhere.

Rollback: `git checkout HEAD -- taut/schema.py tests/test_schema.py` and revert the
test edits. Fully reversible; no data, no migration, no runtime path involved.

## 8. Independent Review Loop

- Reviewer: a different agent family than the author (per `CLAUDE.md` / [DOM-11]).
- Files to read: this plan, `taut/schema.py`, `taut/state/__init__.py`,
  `tests/test_state_contract.py`, and the three migrated test files.
- Review prompt: "Read `docs/plans/2026-07-01-schema-shim-retirement-plan.md` and the
  code. Is the `schema.fn(q, …)` → `SqlSidecarTautState(q, PORTABLE_SQL_DIALECT).fn(…)`
  transform truly behavior-preserving at every listed site? Is any coverage lost by
  deleting `test_schema.py`? Could you implement this confidently and correctly?"
- Feedback handling: update the plan, defend the choice, or mark out of scope with
  reasoning.

## 9. Out of Scope

- The duplicated free function `membership_threads` (exists in both `taut/schema.py`
  and `taut/state/_sql.py:1038`). Nothing imports `schema.membership_threads`, so it
  disappears with the shim; whether the `state/_sql.py` copy is itself used is a
  **separate** dead-code check, not this plan.
- Any change to `taut/state/*`, `taut/client/*`, or `taut/watcher.py`.
- The watcher's `client._state` layering debt (tracked separately).
- Committing/branching strategy for the larger uncommitted refactor tree.

## 10. Fresh-Eyes Review

- Every call site is enumerated with counts and files; the transform is a single
  mechanical rule, so there is no "migrate the tests" ambiguity.
- The one real risk — deleting `test_schema.py` and silently losing the two
  unique-method assertions — is closed by making Task 1 a prerequisite of Task 4.
- The pg slice is explicitly fenced to `bin/pytest-pg` so it is not falsely reported
  as verified from the SQLite run.
- `PORTABLE_SQL_DIALECT` is specified (not `dialect_for_taut_target`) precisely so the
  migration reproduces the shim's current behavior rather than a plausible-looking
  variant.

## Implementation Record (2026-07-01)

Executed per plan. Scope was smaller than drafted: **Task 2 was already done** in the
working tree — `tests/test_client.py` and `tests/test_watcher.py` no longer reference
`schema` (test_client uses `SqlSidecarTautState(queue, SQLITE_SQL_DIALECT)`), so no
migration was needed there.

Changes:

- **Task 1** — `tests/test_state_contract.py`: added the two unique assertions
  (`get_member_by_route_key` before/after rename; `update_member_name` moves the route
  key and rewrites `display_name`), using the file's assign-then-assert-not-None
  pattern for strict mypy.
- **Task 3** — `extensions/taut_pg/tests/test_pg_sidecar.py`: migrated
  `get_schema_version`, `insert_member` (×2), `add_member_alias` to
  `SqlSidecarTautState(queue, PORTABLE_SQL_DIALECT)` (mirrors the retired shim's
  `_state()`); left the `information_schema.tables` raw SQL query untouched.
- **Task 4** — `git rm -f taut/schema.py tests/test_schema.py` (both had uncommitted
  working-tree content from the state refactor; `-f` was required and intended).

Verification (all green):

- `uv run pytest` → **155 passed** (162 − 7 from `test_schema.py`'s removed cases; the
  two backfilled assertions folded into an existing state-contract test, adding no test
  count).
- `uv run ./bin/pytest-pg --fast` → **shared 18 passed, pg_only 8 passed** (the migrated
  `test_pg_sidecar.py` runs under real Docker Postgres).
- `uv run mypy taut tests bin/release.py --config-file pyproject.toml` → clean, 42
  source files.
- `uv run ruff check taut tests bin` / `ruff format --check` → clean.
- `grep -rn 'from taut import schema\|import taut.schema'` → none. Only remaining
  `schema` text is the "taut schema version" f-strings in `taut/state/_sql.py`
  (messages, not imports).

Not done here (left to the owner): committing. The staged deletions
(`taut/schema.py`, `tests/test_schema.py`), the pg test edit, and the
`test_state_contract.py` addition should be committed together as the shim-retirement
change, separate from the surrounding uncommitted refactor blob.
