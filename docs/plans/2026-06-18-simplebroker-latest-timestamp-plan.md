# SimpleBroker Latest Timestamp Plan

Date: 2026-06-18
Status: Implemented locally. Independent review was completed with a bounded
read-only snippet review; verification evidence is recorded in section 11.

Hardening runbook: required as a checklist. The code change is small, but the
same `TautClient.list_threads()` path must keep working across SQLite and
Postgres, preserve the public `list` output contract, and stay inside
SimpleBroker's public API boundary.

## 1. Goal

Address issue #3 by replacing Taut's full-history `last_ts` scan in
`list_threads()` with SimpleBroker 4.8.0's public
`Queue.latest_pending_timestamp()` API. The fix should remove the O(history)
walk from `taut list` without adding a Taut cache, sidecar column, schema
migration, CLI shape change, or backend-specific SQL.

## 2. Source Documents

Source specs:

- `docs/specs/02-taut-core.md` [TAUT-3.1], [TAUT-3.4], [TAUT-3.5],
  [TAUT-7.1], [TAUT-7.2], [TAUT-7.3], [TAUT-8.1], [TAUT-8.2],
  [TAUT-11], [TAUT-12.1]

Implementation docs and related plans:

- `docs/implementation/04-taut-architecture.md`
- `docs/plans/2026-06-17-taut-pg-extension-plan.md`
- `docs/plans/2026-06-17-implementation-review-followups-plan.md`

Runbooks:

- `docs/agent-context/runbooks/writing-plans.md`
- `docs/agent-context/runbooks/hardening-plans.md`
- `docs/agent-context/runbooks/testing-patterns.md`
- `docs/agent-context/runbooks/maintaining-traceability.md`

Upstream SimpleBroker context to read before implementation:

- `../simplebroker/simplebroker/sbqueue.py`
  - `Queue.latest_pending_timestamp()` is the public queue API added in
    SimpleBroker 4.8.0.
- `../simplebroker/simplebroker/db.py`
  - backend-level `latest_pending_timestamp()` delegates to
    `GET_LATEST_PENDING_TIMESTAMP`.
- `../simplebroker/simplebroker/_sql/sqlite.py`
  - SQLite query and `idx_messages_pending_queue_ts` partial index.
- `../simplebroker/tests/test_latest_pending_timestamp.py`
  - shared API semantics: empty queue, newest pending row, claimed rows, queue
    scoping, and non-mutating lookup.
- `../simplebroker/tests/test_sqlite_schema.py`
  - SQLite query-plan proof that the lookup uses the pending queue/timestamp
    index.
- `../simplebroker/extensions/simplebroker_pg/simplebroker_pg/_sql.py`
  - Postgres query.
- `../simplebroker/extensions/simplebroker_pg/simplebroker_pg/schema.py`
  - Postgres pending queue/timestamp index.
- `../simplebroker/extensions/simplebroker_pg/tests/test_pg_latest_pending_timestamp.py`
  - Postgres semantics and schema-index coverage.

## 3. Context and Key Files

- `pyproject.toml`
  - Must keep `simplebroker>=4.8.0`. This is the minimum version that exposes
    `Queue.latest_pending_timestamp()`.
  - The dev dependency on `simplebroker-pg>=2.3.0` is the corresponding PG
    release that carries the same backend API and index.

- `extensions/taut_pg/pyproject.toml`
  - Must keep `simplebroker-pg>=2.3.0` so the extension cannot install with a
    PG backend that lacks the new API.

- `taut/client.py`
  - `TautClient.list_threads()` resolves memberships, calls
    `_thread_from_row()`, and returns `Thread` objects.
  - `_thread_from_row()` currently calculates `last_ts` through
    `_last_message_ts(queue)`.
  - `_last_message_ts()` currently walks `queue.peek_generator()`, retaining
    only the final timestamp. This is the O(history) behavior being fixed.
  - `_unread_count()` already uses bounded `peek_many(..., cap=1000)` for
    display-only unread counts. This plan does not change it.
  - `_resolve_message_id()` still performs a bounded suffix scan over recent
    message ids. That is a separate API behavior from `list` and must remain
    unchanged.

- `taut/cli.py`
  - Renders list output from `Thread.last_ts` and `Thread.unread_count`.
  - The CLI output shape must not change. JSON list objects remain `thread`,
    `parent`, `unread`, and `last_ts`.

- `tests/test_shared_contract.py`
  - Module-marked `shared`, so it runs against SQLite in the default suite and
    against Postgres through `bin/pytest-pg`.
  - This is the right place for backend-agnostic `list` behavior coverage.

- `docs/specs/02-taut-core.md`
  - Should clarify that `list` reports the newest visible pending broker
    timestamp and that this is obtained through SimpleBroker's public API, not
    through a Taut cache.

- `docs/implementation/04-taut-architecture.md`
  - Should record the rationale: `list` uses SimpleBroker's indexed latest
    pending timestamp API to preserve the no-private-SQL and no-cache
    boundaries.

Comprehension checks before editing:

1. Why does pending-only latest timestamp preserve current Taut behavior?
   Answer: current `_last_message_ts()` uses `peek_generator()`, which also
   sees only pending rows. Taut itself never claims messages; claimed rows mean
   a foreign broker consumer removed them from Taut history per [TAUT-7.1].
2. Why is a Taut-side cache the wrong fix here?
   Answer: [TAUT-3.1] says Taut must not add extra durable state or caches, and
   [TAUT-7.3] says unread state asks the broker rather than maintaining
   invalidation-prone counters.
3. Which public output changes?
   Answer: none. The value of `last_ts` should match the previous pending-row
   semantics; only the lookup cost changes.

## 4. Invariants and Constraints

- Preserve the `list` CLI and Python API contract. No new JSON fields, removed
  fields, exit-code changes, or human-output shape changes.
- Preserve the peek-only read model. No Taut path may consume, claim, move, or
  delete broker messages.
- Use only SimpleBroker public APIs. Do not import SimpleBroker underscore
  modules from Taut and do not query SimpleBroker's own `messages` table from
  Taut.
- Do not add a Taut cache, sidecar `last_ts` column, migration, trigger, or
  denormalized metadata table.
- Preserve backend portability. The same `TautClient` code path must work on
  SQLite and Postgres; do not add backend branches.
- Keep `_unread_count()` bounded-display behavior as-is. This plan fixes the
  last-message timestamp scan only.
- Keep `_resolve_message_id()` suffix resolution as-is. It is a user-facing
  bounded lookup described in [TAUT-8.1], not the issue #3 list scan.
- Dependency floors are load-bearing. If `simplebroker>=4.8.0` or
  `simplebroker-pg>=2.3.0` is not present in project metadata, stop and update
  metadata before using the new API.
- Rollback is source-only: revert the client/test/doc edits together. There is
  no data migration and no rollout ordering requirement beyond shipping with
  the dependency floors above.
- One-way doors: none. This change does not alter persisted data or public
  contracts.

## 5. Tasks

1. Add a real shared behavior test for `list` `last_ts`.
   - Files to touch: `tests/test_shared_contract.py`.
   - Read first: current `test_project_list_reports_unread_contract()` and
     nearby shared client tests.
   - Use the real `TautClient` and `taut_project` fixture. Do not mock
     `Queue`, SimpleBroker, or `TautClient`.
   - Cover a joined thread with multiple messages and assert that
     `list_threads(all_threads=True)` reports the timestamp of the newest
     message.
   - Also assert that reading the thread does not change `last_ts`, because
     Taut reads are cursor moves, not broker consumes.
   - Add and run the test before implementation. It may already pass because
     the current bug is cost, not returned value. That is acceptable only
     because the algorithm-selection gate below proves the O(history) scan was
     removed.
   - Stop and re-evaluate if the test needs to inspect SQLite files directly
     or cannot run through the shared PG harness.
   - Done when the test proves the public result with real SQLite and is ready
     for PG execution.

2. Replace the full-history scan with SimpleBroker's public API.
   - Files to touch: `taut/client.py`.
   - Read first: `TautClient._thread_from_row()`, `_last_message_ts()`,
     `_unread_count()`, and `_resolve_message_id()`.
   - Required change:

     ```python
     def _last_message_ts(self, queue: Queue) -> int | None:
         return queue.latest_pending_timestamp()
     ```

   - Do not inline SQL, branch on backend type, add a cache, or reuse
     `refresh_last_ts()`. `refresh_last_ts()` is database-high-water-mark
     oriented and not queue-scoped pending-message state.
   - Keep `_last_message_ts()` as a small helper unless removing it clearly
     reduces local complexity without obscuring the boundary. The helper name
     is useful for review because it isolates the issue #3 behavior.
   - Stop and re-evaluate if the type checker says the installed SimpleBroker
     stubs or runtime package lack `latest_pending_timestamp()`. That means
     the dependency floor is not actually effective.
   - Done when `list_threads()` uses the new API and no `list` code path walks
     `peek_generator()` to compute `last_ts`.

3. Update source-of-truth documentation.
   - Files to touch: `docs/specs/02-taut-core.md` and
     `docs/implementation/04-taut-architecture.md`.
   - Spec update: add a concise note near [TAUT-8.2] or [TAUT-7.3] that
     `last_ts` is the newest pending broker timestamp for the registered
     thread, obtained through SimpleBroker's public indexed lookup. Keep this
     as behavior plus boundary, not an implementation tutorial.
   - Implementation update: record that `TautClient` uses
     `Queue.latest_pending_timestamp()` for list metadata to avoid a
     full-history scan while preserving the no-private-SQL and no-cache
     boundaries.
   - Do not add a changelog entry unless the implementation owner decides this
     should be user-facing release text. It is a performance fix under the
     existing 0.2.1 bug-fix scope.
   - Done when spec and architecture doc both point to the plan and explain why
     no Taut data-model change is needed.

4. Add an algorithm-selection gate.
   - Files to touch: none required, unless adding a small grep helper is cleaner
     than documenting a manual gate.
   - Behavior tests alone cannot prove the O(history) scan is gone, because
     the old implementation returned the same `last_ts`.
   - Use a source inspection gate after implementation:

     ```bash
     rg -n "def _last_message_ts|latest_pending_timestamp|peek_generator" taut/client.py
     ```

   - Expected result: `_last_message_ts()` calls
     `latest_pending_timestamp()`. The only remaining `peek_generator()` uses
     in `taut/client.py` are `log()` history iteration and
     `_resolve_message_id()` bounded suffix resolution, not `list` metadata.
   - Do not satisfy this gate by mocking broker calls or timing a large local
     database. Mocking violates [TAUT-11], and wall-clock performance tests are
     too noisy for this narrow proof.
   - Done when the source gate and code review show no list-time full-history
     walk remains.

5. Run targeted and shared verification.
   - Files to touch: none unless tests reveal a real issue.
   - Run the targeted SQLite shared test first, then the PG shared harness.
   - If PG fails because Docker or Postgres is unavailable, record that as a
     residual verification gap; do not treat a skipped PG run as equivalent to
     passing.
   - Stop and re-evaluate if SQLite and PG disagree on `last_ts`; the likely
     causes are dependency mismatch, PG index/schema version drift, or a
     misunderstanding of pending-row semantics.
   - Done when verification evidence is recorded in the plan or the final
     implementation summary.

6. Run independent review before implementation is considered complete.
   - Files for reviewer: this plan, `taut/client.py`,
     `tests/test_shared_contract.py`, `docs/specs/02-taut-core.md`,
     `docs/implementation/04-taut-architecture.md`, and the SimpleBroker files
     listed in section 2.
   - Preferred reviewer: a different agent family than the implementer.
   - Review stance: look for hidden contract changes, weak tests, accidental
     backend branching, misuse of SimpleBroker internals, and missed doc
     traceability.
   - Done when each review point is answered by updating the plan/code/docs,
     marking it out of scope with reasoning, or recording accepted residual
     risk.

## 6. Testing Plan

Red-green exception: public `list` behavior should not change, so a real
behavior test may pass before implementation. A failing performance test would
need either broker mocking or wall-clock timing, both weaker than the proof this
change needs. Add the real-backend characterization test in
`tests/test_shared_contract.py` before changing `taut/client.py`, then use the
source inspection gate as the substitute proof that the O(history) path was
removed.

What must stay real:

- Real SimpleBroker queues.
- Real `.taut.db` SQLite files through the `taut_project` fixture.
- Real Postgres backend through `bin/pytest-pg` for shared tests.
- Real `TautClient` public methods.

What may be inspected instead of mocked:

- Source text for the algorithm-selection gate. This is acceptable because the
  performance regression is the choice of API call, while behavior is already
  covered through real broker tests.

What must not be mocked:

- `Queue`, `Queue.peek_generator()`, `Queue.latest_pending_timestamp()`,
  `TautClient`, or broker storage behavior in the shared test.

Targeted test behavior:

- Create or join a thread through `TautClient`.
- Write multiple messages through `say()`.
- Assert `list_threads(all_threads=True)` reports `last_ts` equal to the
  newest message timestamp.
- Read the thread.
- Assert `list_threads(all_threads=True)` still reports the same `last_ts`.

## 7. Verification and Gates

Per-task commands:

```bash
uv run pytest tests/test_shared_contract.py -k list
uv run ./bin/pytest-pg --fast tests/test_shared_contract.py -k list
rg -n "def _last_message_ts|latest_pending_timestamp|peek_generator" taut/client.py
```

Final gates:

```bash
uv run pytest -m shared
uv run ./bin/pytest-pg --fast
uv run ruff check taut tests bin extensions/taut_pg/taut_pg extensions/taut_pg/tests
uv run ruff format --check taut tests bin extensions/taut_pg/taut_pg extensions/taut_pg/tests
uv run --extra dev mypy taut tests bin/release.py extensions/taut_pg/taut_pg extensions/taut_pg/tests --config-file pyproject.toml
```

Run the broader default suite if the targeted/shared gates pass and time is not
the limiting factor:

```bash
uv run pytest
```

Success looks like:

- The shared list test passes under SQLite and Postgres.
- Source inspection shows `last_ts` list metadata no longer uses
  `peek_generator()`.
- Static checks pass.
- No private SimpleBroker imports or broker-table SQL appear in Taut.

Post-release signal:

- `taut list` latency should no longer grow linearly with per-thread history
  for the `last_ts` part of the operation. Unread count display can still do a
  bounded peek up to 1,000 rows by design.

Rollback:

- Revert the `taut/client.py` change and its tests/docs. No persisted data,
  dependency lockstep, or schema migration is involved.

## 8. Independent Review Loop

Before implementation:

> Read `docs/plans/2026-06-18-simplebroker-latest-timestamp-plan.md`,
> `taut/client.py`, `tests/test_shared_contract.py`,
> `docs/specs/02-taut-core.md`, and
> `docs/implementation/04-taut-architecture.md`. Also inspect the
> SimpleBroker 4.8.0 and simplebroker-pg 2.3.0 latest pending timestamp API
> files named in the plan. Do not implement. Review whether the plan is
> specific enough to implement correctly, whether the testing proof is strong
> enough, and whether any contract or backend-boundary risk is missing.

After review, the implementation owner must respond to every finding in this
plan or in the implementation summary. A "could not implement confidently"
review is a blocker until the ambiguity is resolved or explicitly accepted.

## 9. Out of Scope

- No Taut cache or `taut_threads.last_ts` column.
- No schema migration.
- No changes to `read`, `log`, `watch`, `reply` suffix lookup, or unread-count
  display.
- No backend-specific Taut code.
- No new SimpleBroker API request.
- No change to CLI JSON/human output shape.
- No PyPI, release workflow, or version-bump work.

## 10. Fresh-Eyes Review

Before implementation starts, re-read this plan as if you have no project
context and verify:

- The exact file paths and edit points are named.
- The public contract that must not change is explicit.
- The no-cache and no-private-SQL boundaries are explicit.
- The behavior proof and algorithm-selection proof are separate.
- The shared SQLite and Postgres verification path is concrete.
- The rollback story does not depend on data migration or rollout order.

## 11. Implementation Notes and Verification Evidence

Implemented changes:

- `taut/client.py`: `_last_message_ts()` now delegates to
  `Queue.latest_pending_timestamp()` instead of walking
  `queue.peek_generator()`.
- `tests/test_shared_contract.py`: added shared list metadata coverage for:
  newest pending timestamp, read-does-not-claim behavior, newest claimed
  foreign row ignored, and all-claimed queue returning `last_ts is None`.
- `docs/specs/02-taut-core.md`: documented `last_ts` as the newest pending
  broker timestamp for the registered thread.
- `docs/implementation/04-taut-architecture.md`: recorded the rationale for
  using SimpleBroker's indexed public API instead of a Taut cache or sidecar
  denormalization.

Independent review:

- External agent-runner attempts with Claude, Gemini, Qwen, and Codex were
  unavailable or failed before returning review findings.
- A local Claude print-mode review was completed against read-only
  implementation snippets and verification output. It reported no blockers.
  Its one actionable gap was the lack of Taut-level coverage for claimed
  foreign rows and empty/all-claimed `last_ts`; that gap was closed by
  `test_project_list_ignores_foreign_claimed_messages_contract()`.
- Residual review limitation: the successful review was snippet-bounded rather
  than full-tree tool-assisted. The final source gate and full local/PG test
  gates below were run after incorporating the review feedback.

Verification evidence:

```bash
uv run pytest tests/test_shared_contract.py -k list
# 3 passed

uv run ./bin/pytest-pg --fast tests/test_shared_contract.py -k list
# 3 passed against Docker Postgres

rg -n "def _last_message_ts|latest_pending_timestamp|peek_generator" taut/client.py
# _last_message_ts calls latest_pending_timestamp(); remaining peek_generator
# uses are log history iteration and bounded message-id suffix resolution.

uv run pytest -m shared
# 11 passed

uv run ./bin/pytest-pg --fast
# root shared: 11 passed; extension pg_only: 8 passed

uv run ruff check taut tests bin extensions/taut_pg/taut_pg extensions/taut_pg/tests
# All checks passed

uv run ruff format --check taut tests bin extensions/taut_pg/taut_pg extensions/taut_pg/tests
# 32 files already formatted

uv run --extra dev mypy taut tests bin/release.py extensions/taut_pg/taut_pg extensions/taut_pg/tests --config-file pyproject.toml
# Success: no issues found in 32 source files

uv run pytest
# 106 passed
```
