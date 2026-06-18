# Implementation Review Follow-ups Plan

Date: 2026-06-17
Status: Implemented locally. Verification evidence is recorded in section 9.

Hardening runbook: required. This follow-up touches public error behavior,
backend conformance coverage, project-resolution tests, and the root test
harness. It must preserve the single TautClient path across SQLite and
Postgres.

## 1. Goal

Address the implementation-review findings from the Postgres extension slice:
make the missing Postgres backend hint resilient and rooted in `TautError`,
restore bounded `log --limit` memory behavior, remove dead copied harness
logic, and strengthen backend-shared tests for reply, leave/rejoin, and unread
thread listing.

## 2. Source Documents

Source specs:

- `docs/specs/02-taut-core.md` [TAUT-3.2], [TAUT-3.3], [TAUT-7], [TAUT-8],
  [TAUT-10], [TAUT-11], [TAUT-12.1]

Related implementation docs and plans:

- `docs/implementation/04-taut-architecture.md`
- `docs/plans/2026-06-17-taut-pg-extension-plan.md`

Runbooks:

- `docs/agent-context/runbooks/testing-patterns.md`
- `docs/agent-context/runbooks/hardening-plans.md`
- `docs/agent-context/runbooks/maintaining-traceability.md`

## 3. Context and Key Files

- `taut/client.py` owns target resolution, queue construction, command
  semantics, and user-visible API errors. `_raise_with_backend_install_hint()`
  currently depends on one exact SimpleBroker error string and raises
  `RuntimeError`; `log()` currently loads all messages before slicing.
- `taut/_exceptions.py` owns the public exception hierarchy rooted at
  `TautError`.
- `tests/conftest.py` owns backend markers and PG config injection for root
  shared tests. `_config_root_from_args()` is copied from SimpleBroker but
  Taut has no `--dir` flag.
- `tests/test_project_config.py` owns project-resolution and missing-plugin
  coverage.
- `tests/test_shared_contract.py` is module-marked `shared` and is the right
  home for backend-agnostic client/CLI behavior that must run under SQLite and
  Postgres.

Comprehension checks before editing:

1. Public CLI/API errors should stay catchable through `TautError`.
2. Backend-shared tests must use real `TautClient` or real CLI subprocesses.
3. PG shared tests must be driven by `.taut.toml`; `TAUT_DB` and `--db` stay
   path-only selectors.

## 4. Invariants and Constraints

- Do not add Taut-owned backend plumbing. Postgres selection remains
  SimpleBroker project config plus the `taut-pg` package.
- Do not add SQL outside `taut/schema.py`.
- Do not mock broker behavior in shared conformance tests.
- `log --limit N` must return the most recent N messages after `--since`, in
  chronological order, without retaining every decoded message when a limit is
  supplied.
- Unmarked root tests may still default to SQLite-only, but the explicit shared
  contract module must not silently run as SQLite-only.
- Keep changes local. The duplicate root/extension CLI subprocess helpers are
  accepted out of scope for this slice.

## 5. Tasks

1. Fix client behavior.
   - Files: `taut/client.py`, `taut/_exceptions.py` only if a new exception is
     truly needed.
   - Reuse the existing exception hierarchy; prefer `TautError` over a raw
     runtime exception for the install hint.
   - Restore bounded-memory `log(limit=...)` using a `deque(maxlen=limit)`.
   - Done when focused tests prove error matching survives extra context and
     log limit still returns the newest messages in order.

2. Clean the root test harness.
   - Files: `tests/conftest.py`, `tests/test_harness.py`.
   - Collapse the copied `--dir` parsing path because Taut has no such CLI
     option.
   - Add a guard that the shared contract module stays marked `shared`.
   - Done when harness tests cover PG config placement and shared-marker guard.

3. Strengthen project config tests.
   - File: `tests/test_project_config.py`.
   - Replace file-content-only precedence proof with actual Taut resolution
     through `TautClient.init()` and `TautClient`.
   - Keep the missing-plugin proof resilient to SimpleBroker context appended
     to the unknown-backend message.
   - Done when the test would fail if `.broker.toml` controlled Taut resolution.

4. Broaden shared backend contract coverage.
   - File: `tests/test_shared_contract.py`.
   - Add shared tests for reply/sub-thread creation, leave plus membership
     deletion, rejoin anchor update, and unread list behavior.
   - Use real client/CLI calls and the `taut_project` fixture.
   - Done when the new tests run under the default SQLite suite and the PG
     shared runner.

5. Update plan status and docs only where the code changes alter durable
   guidance.
   - File: this plan; `docs/lessons.md` only if a reusable lesson emerges.
   - Done when verification evidence and residual risk are recorded here.

## 6. Testing Plan

Use red-green where practical by adding or changing focused tests before the
implementation edit. The substitute proof for small mechanical cleanup is
targeted harness tests plus static checks.

Do not mock the broker in shared conformance tests. Limited monkeypatching is
acceptable for the missing-plugin helper and harness subprocess boundary.

Targeted commands:

```bash
uv run pytest tests/test_project_config.py tests/test_harness.py tests/test_shared_contract.py
uv run ./bin/pytest-pg --fast tests/test_shared_contract.py
uv run ruff check taut tests
uv run ruff format --check taut tests
uv run --extra dev mypy taut tests --config-file pyproject.toml
```

Final broader command if targeted gates pass:

```bash
uv run pytest
```

## 7. Verification and Gates

Per-task gates:

- If a fix needs private SimpleBroker imports, stop and re-plan.
- If a test mocks `Queue` or `TautClient` for shared behavior, stop and rewrite
  it against the real path.
- If `log(limit=...)` cannot stay chronological without full retention, stop
  and document why before accepting the tradeoff.

Rollback: all changes are source/test/doc only and can be reverted together.
There is no schema or data migration.

Post-release signal: `bin/pytest-pg --fast` continues to exercise the expanded
shared contract suite against a real Docker Postgres backend.

## 8. Independent Review Loop

The user-provided implementation review is the independent review input for
this follow-up. Before completion, re-check each finding against the diff and
record which findings were fixed or intentionally left as residual risk.

## 9. Review Findings Response

Implemented responses:

- Brittle error coupling: fixed in `taut/client.py`. Missing Postgres backend
  wrapping now accepts the raw SimpleBroker unknown-plugin text with appended
  context and SimpleBroker's newer backend-unavailable text. The raised error
  is rooted at `TautError`.
- `log()` dead line and bounded retention: fixed in `taut/client.py`. Limited
  logs now retain a `deque(maxlen=limit)` while scanning and return the bounded
  result in chronological order. The no-op `list()` conversion is gone.
- Dead copied harness path: fixed in `tests/conftest.py`. PG subprocess config
  is created at the actual `cwd`, matching Taut's CLI surface.
- Weak project-config tests: fixed in `tests/test_project_config.py`. The
  missing-plugin test now exercises `TautClient.init()` through a real
  `.taut.toml` project config and appended SimpleBroker error context. The
  `.taut.toml` precedence test now initializes and uses the resolved Taut DB,
  proving `.broker.toml` is ignored.
- Thin shared conformance: broadened in `tests/test_shared_contract.py`.
  Shared tests now cover reply/sub-thread creation, leave membership removal,
  rejoin anchor update, unread list behavior, and `log(limit=...)` ordering.
- Silent shared-marker loss: fixed in `tests/conftest.py`. Root test
  collection now rejects any collected test without an explicit `shared`,
  `sqlite_only`, or `pg_only` marker; `test_shared*` modules still receive a
  dedicated error if they omit `@pytest.mark.shared`.

Accepted residuals:

- Root `run_cli()` and extension `taut_cli()` still duplicate subprocess
  setup. The review called this acceptable, and merging them would widen this
  slice without improving the concrete defects.
- No heap benchmark was added for `log(limit=...)`; the implementation-level
  bounded-retention change plus shared behavior coverage is the right proof for
  this small regression.

Verification evidence:

```bash
uv run pytest tests/test_project_config.py tests/test_harness.py tests/test_shared_contract.py
# 18 passed

uv run ./bin/pytest-pg --fast tests/test_shared_contract.py
# 9 passed against Docker Postgres

uv run ruff check taut tests
# All checks passed

uv run ruff format --check taut tests
# 27 files already formatted

uv run --extra dev mypy taut tests --config-file pyproject.toml
# Success: no issues found in 27 source files

uv run pytest
# 101 passed

uv run ./bin/pytest-pg --fast
# shared: 9 passed; extension PG-only: 8 passed
```
