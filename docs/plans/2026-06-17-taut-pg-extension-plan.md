# Taut Postgres Extension Plan

Date: 2026-06-17
Status: Implemented locally. Author self-review and one independent plan review
were incorporated before implementation. Final verification evidence is listed
in section 13.

Hardening runbook: required. This changes backend compatibility, project
configuration, release tooling, CI, and the test matrix. It crosses a public
CLI/API boundary and adds a cleanup lifecycle for temporary Postgres schemas.

## 1. Goal

Add first-class Postgres support for Taut by following the SimpleBroker
extension pattern: a separate `extensions/taut_pg` project, a root
`bin/pytest-pg` helper, an explicit split between backend-agnostic shared tests
and Postgres-only extension tests, GitHub-only release support, and a clear
plugin boundary. The implementation should make [TAUT-12.1] real without
creating a second Taut storage architecture.

The central design is intentionally small: Taut keeps its core state helpers in
`taut/schema.py`; the SimpleBroker Postgres plugin (`simplebroker-pg`) owns the
actual backend, runner, schema namespace, sidecar SQL execution, and
LISTEN/NOTIFY waiter. `taut-pg` is a Taut extension package and test/release
surface around that existing backend, not a new backend implementation.

## 2. Source Documents

Read these before editing:

- `AGENTS.md` and the required shared context listed there.
- `docs/specs/02-taut-core.md`:
  - [TAUT-3.2] target resolution and creation rules
  - [TAUT-3.3] sidecar schema v1
  - [TAUT-3.4] SimpleBroker interop and public API boundary
  - [TAUT-3.5] timestamp domain and exact-id write path
  - [TAUT-7] peek-only read model
  - [TAUT-8.4] watcher contract and interval backstop
  - [TAUT-9] trust model
  - [TAUT-12.1] Postgres backend roadmap commitment
  - [TAUT-12.2] state-module boundary for future Redis work
- `docs/implementation/04-taut-architecture.md`, especially "Design
  Rationale", "Boundaries and Invariants", and "Change Guidance".
- `docs/agent-context/runbooks/testing-patterns.md`, especially red-green TDD
  and "do not mock the core path".
- `docs/agent-context/runbooks/hardening-plans.md`.
- `docs/agent-context/runbooks/maintaining-traceability.md`.
- SimpleBroker patterns to mirror:
  - `../simplebroker/extensions/simplebroker_pg/pyproject.toml`
  - `../simplebroker/extensions/simplebroker_pg/README.md`
  - `../simplebroker/extensions/simplebroker_pg/tests/conftest.py`
  - `../simplebroker/extensions/simplebroker_pg/tests/test_pg_integration.py`
  - `../simplebroker/bin/pytest-pg`
  - `../simplebroker/simplebroker/_scripts.py::pytest_pg_main`
  - `../simplebroker/tests/conftest.py`
  - `../simplebroker/pyproject.toml`
  - `../simplebroker/.github/workflows/test-pg-extension.yml`
  - `../simplebroker/.github/workflows/release-gate-pg.yml`
  - `../simplebroker/bin/release.py`
- Weft fallback patterns, only when SimpleBroker does not answer the question:
  - `../weft/bin/pytest-pg`
  - `../weft/tests/helpers/test_backend.py`
  - `../weft/tests/system/test_pytest_pg_script.py`
  - `../weft/README.md` "Testing"
- Current Taut release patterns to preserve:
  - `.github/workflows/release.yml`
  - `.github/workflows/release-gate.yml`
  - `bin/release.py`

Pattern precedence:

1. Follow SimpleBroker when it has an answer. This applies to `extensions/`,
   separate project metadata, `bin/pytest-pg`, `shared`/`pg_only` test
   markers, Postgres Docker test setup, namespaced extension tags, and the
   Postgres extension workflow.
2. If SimpleBroker does not answer because Taut's constraint is different,
   inspect Weft and follow the closest existing Weft pattern. Known examples:
   subprocess-group teardown, diagnostic pytest arguments, helper tests for
   `bin/pytest-pg`, and splitting backend-aware test helpers out of
   `tests/conftest.py` if the Taut harness grows too large.
3. If neither SimpleBroker nor Weft has an answer, stop and ask before
   inventing a new project convention.

Release exception: do not use Weft's release workflows as an implementation
reference for Taut. They are PyPI-first. Taut's existing reusable
`.github/workflows/release.yml` is already GitHub-only and accepts a package
directory, so it is the source of truth for publishing both root and extension
artifacts.

## 3. Locked Decisions

These are decisions for this plan. Do not reopen them during implementation
unless a red test or upstream SimpleBroker behavior proves one wrong.

1. `taut-pg` lives at `extensions/taut_pg` as its own Python project.
   - Distribution name: `taut-pg`.
   - Import package: `taut_pg`.
   - It depends on `taut>=<current-version>` and `simplebroker-pg>=2.2.1`.
   - It does not vendor or wrap `simplebroker_pg`.

2. There is no Taut backend registry in this slice.
   - Do not add `taut.plugins`, `taut.backends`, or a Taut plugin entry point.
   - The backend plugin is SimpleBroker's existing `simplebroker.backends`
     entry point from `simplebroker-pg`.
   - `taut_pg` may expose package metadata, but it must not own queue
     creation, target resolution, SQL, identity resolution, CLI command logic,
     or watcher logic.

3. Postgres selection uses `.taut.toml`.
   - Use the same file shape SimpleBroker uses for `.broker.toml`:

     ```toml
     version = 1
     backend = "postgres"
     target = "postgresql://postgres:postgres@127.0.0.1:54329/taut_test"

     [backend_options]
     schema = "taut_project"
     ```

   - Do not reinterpret `TAUT_DB` as a DSN. `TAUT_DB`, `--db`, and
     `db_path=` stay explicit filesystem path selectors.
   - Do not document `BROKER_BACKEND=postgres` as a public Taut API. The
     supported Taut path is `.taut.toml`.

4. Do not add a public `taut[pg]` convenience extra in the first PG slice.
   - SimpleBroker can publish `simplebroker[pg]` because both `simplebroker`
     and `simplebroker-pg` are available from PyPI.
   - Taut does not yet have PyPI name clearance. A root extra that points at
     `taut-pg>=...` would not be installable from normal package indexes.
   - A root extra with a direct GitHub URL would need a separate release
     decision and version-update policy.
   - For now, docs should show installing the core and extension from GitHub
     or GitHub Release artifacts in the same environment.

5. Release remains GitHub-only.
   - No PyPI job, Trusted Publishing environment, `uv publish`, or
     `pypa/gh-action-pypi-publish`.
   - `taut-pg` should get its own GitHub release tag namespace:
     `taut_pg/vX.Y.Z`, matching SimpleBroker's `simplebroker_pg/vX.Y.Z`.
   - The release-gate structure should start from SimpleBroker's
     `release-gate-pg.yml`, then adapt the publishing half to Taut's existing
     GitHub-only `.github/workflows/release.yml`. Copy SimpleBroker's tag and
     test-gate shape, not its PyPI jobs.

## 4. Context And Key Files

### Current Taut structure

- `taut/_constants.py`
  - Owns version, default DB name, project config name, and
    `load_config()`.
  - Today `load_config()` sets:
    - `BROKER_DEFAULT_DB_NAME` from `TAUT_DB` or `.taut.db`
    - `BROKER_PROJECT_SCOPE = True`
    - `BROKER_PROJECT_CONFIG_NAME = .taut.toml`
  - It calls `simplebroker.resolve_config()`, which also reads ambient
    `BROKER_*` env vars. Be careful: when removing SQLite-only rejections,
    ambient `BROKER_BACKEND=postgres` could become an unintended Taut API.
  - The plan resolves this by requiring `load_config()` to pass
    `BROKER_BACKEND = "sqlite"` into `resolve_config()` as Taut's default. This
    blocks env-only backend selection while preserving `.taut.toml`, because
    SimpleBroker project resolution checks the configured project file before
    env-selected backend synthesis.

- `taut/client.py`
  - Owns all public command semantics behind `TautClient`.
  - `TautClient.init()` creates/initializes the target.
  - `TautClient._resolve_target()` resolves a target before any queue opens.
  - Both methods currently reject non-SQLite targets with
    `BackendNotSupportedError`.
  - Explicit `db_path`, `--db`, and `TAUT_DB` paths are checked with
    `Path.exists()` before opening. This is correct for SQLite path targets and
    must stay correct.

- `taut/schema.py`
  - Owns all Taut sidecar SQL.
  - Uses `Queue.sidecar()` and `simplebroker.ext` public types.
  - Uses qmark placeholders (`?`) everywhere. This is required because
    SimpleBroker translates them for Postgres.
  - No other Taut file should gain sidecar SQL in this plan.

- `taut/watcher.py`
  - Uses cursor-aware `peek_many(..., after_timestamp=...)` and
    `has_pending(after_timestamp=...)`.
  - Membership refresh has both a data-version callback path and a timer path.
  - The timer path is the portable guarantee for backends whose native waiters
    only wake for queue writes.

- `taut/cli.py`
  - Is a renderer and argument adapter over `TautClient`.
  - `taut init --json` emits `{"db": ..., "created": ...}`.
  - For Postgres, `db` should be the resolved backend display target and
    `created` should be `false` unless a backend can provide a real creation
    result. Do not guess based on the existence of a local path.

- `tests/conftest.py`
  - Currently provides `clean_env` and a backend-unaware typed `run_cli()`
    helper.
  - The default suite around it is SQLite-only because there are no backend
    markers, PG project config helper, or schema cleanup yet.

- `tests/test_client.py`, `tests/test_cli.py`, `tests/test_schema.py`,
  `tests/test_watcher.py`
  - These currently assume SQLite paths in many places.
  - Shared tests must use project resolution through `cwd` and `.taut.toml`
    where possible.
  - Tests that assert explicit path or filesystem behavior remain
    `sqlite_only`.

- `pyproject.toml`
  - Needs pytest markers for `shared`, `sqlite_only`, and `pg_only`.
  - Needs tool path updates only if the new extension is type/lint checked
    from the root.
  - Do not add core runtime dependencies for Postgres.

- `.github/workflows/`
  - Current workflows test and publish the root package only.
  - New PG extension workflows should mirror SimpleBroker's split while
    preserving Taut's GitHub-only release boundary.

- `bin/release.py`
  - Current helper has one root `taut` release target and `pypi_publish=False`.
  - It needs an extension target model before `taut-pg` can be released.

### SimpleBroker structure to copy conceptually

- `../simplebroker/extensions/simplebroker_pg/pyproject.toml`
  - Separate project.
  - Own package metadata and build include list.
  - Registers `simplebroker.backends` entry point because it implements the
    actual backend.

- `../simplebroker/bin/pytest-pg`
  - Thin script over SimpleBroker's test helper.
  - Starts a temporary Docker Postgres container.
  - Sets `SIMPLEBROKER_PG_TEST_DSN`.
  - Runs root tests marked `shared` and extension tests marked `pg_only`.

- `../simplebroker/tests/conftest.py`
  - Has backend markers and backend-aware CLI helpers.
  - Creates per-test `.broker.toml` files for PG shared tests.
  - Uses one Postgres schema per xdist worker for root shared tests, with
    per-test reset/cleanup for isolation.

- `../simplebroker/.github/workflows/test-pg-extension.yml`
  - Separate extension workflow.
  - Runs `uv run ./bin/pytest-pg`.
  - Lints, formats, and type-checks extension code.

### Files expected to be touched during implementation

Core behavior and test harness:

- `taut/_constants.py`
- `taut/client.py`
- `tests/conftest.py`
- `tests/test_client.py`
- `tests/test_cli.py`
- `tests/test_schema.py`
- `tests/test_watcher.py`
- new `tests/test_project_config.py`
- new `tests/test_dev_scripts.py`

Extension project:

- `extensions/taut_pg/pyproject.toml`
- `extensions/taut_pg/README.md`
- `extensions/taut_pg/LICENSE`
- `extensions/taut_pg/taut_pg/__init__.py`
- `extensions/taut_pg/taut_pg/py.typed`
- `extensions/taut_pg/tests/conftest.py`
- `extensions/taut_pg/tests/test_pg_integration.py`
- `extensions/taut_pg/tests/test_pg_sidecar.py`
- optional focused PG-only test files if one file gets too large

Developer tooling and release:

- `bin/pytest-pg`
- `taut/_scripts.py`
- `bin/release.py`
- `.github/workflows/test-pg-extension.yml`
- `.github/workflows/release-gate-pg.yml`
- existing `.github/workflows/release.yml`
- existing `.github/workflows/release-gate.yml`
- `tests/test_release_script.py`
- `tests/test_github_workflows.py`

Docs:

- `README.md`
- `docs/specs/02-taut-core.md`
- `docs/implementation/02-repository-map.md`
- `docs/implementation/04-taut-architecture.md`
- `docs/plans/README.md` only if plan conventions need a new note
- `docs/lessons.md` only if implementation reveals a reusable correction

### Comprehension questions before editing

The implementing engineer should answer these in their own scratch notes before
touching code:

1. Which module owns all Taut SQL?
   - Answer: `taut/schema.py`. If the plan seems to require SQL elsewhere,
     stop and re-evaluate.

2. Which code currently blocks Postgres?
   - Answer: `TautClient.init()` and `TautClient._resolve_target()` in
     `taut/client.py` reject `BrokerTarget.backend_name != "sqlite"`.

3. Which target selectors must remain path-only?
   - Answer: `--db`, `db_path=`, and `TAUT_DB`. They must not accept a
     Postgres DSN in this slice.

4. Which backend selector is supported for Postgres?
   - Answer: `.taut.toml` discovered through SimpleBroker project resolution.

5. What must stay real in tests?
   - Answer: real `TautClient`, real CLI subprocesses for CLI behavior, real
     `Queue.sidecar()`, real SQLite files, and real Postgres via Docker for PG
     gates. Do not mock SimpleBroker queue operations, sidecar sessions, or
     plugin registration for acceptance tests.

## 5. Invariants And Constraints

These invariants are binding. If implementation pressure makes one hard, stop
and revise the plan rather than locally weakening the invariant.

1. Core default remains SQLite-first and no-config.
   - `taut init` in an empty directory with no `.taut.toml` still creates
     `.taut.db`.
   - Existing SQLite CLI/API tests still pass.
   - The root package does not depend on `simplebroker-pg`, `psycopg`, or
     `psycopg-pool` at runtime.

2. `.taut.toml` is the Postgres door.
   - A project config with `backend = "postgres"` should resolve via
     `simplebroker.resolve_broker_target()`.
   - `.broker.toml` must not affect Taut.
   - `TAUT_DB`, `--db`, and `db_path=` remain path selectors and keep the
     existing explicit-missing-path error behavior.

3. Ambient `BROKER_*` must not silently become Taut's documented API.
   - `taut._constants.load_config()` must pass `BROKER_BACKEND = "sqlite"` in
     its raw config before calling `simplebroker.resolve_config()`. This is the
     concrete fix for env-only `BROKER_BACKEND=postgres`.
   - This pin must not suppress `.taut.toml`: SimpleBroker's public
     `resolve_broker_target()` and `target_for_directory()` check project config
     before `_configured_backend_target()`, and `resolve_project_target()` takes
     `backend` from the TOML file.
   - The implementation may preserve SimpleBroker's supplemental env behavior
     where needed for project-config passwords, but docs must not teach
     env-only Taut backend selection.
   - Add tests that prove `BROKER_BACKEND=postgres` without `.taut.toml` still
     uses Taut's SQLite default, while `.taut.toml` with `backend = "postgres"`
     still wins when the PG plugin is installed.

4. Taut-owned SQL stays in one file.
   - No sidecar SQL outside `taut/schema.py`.
   - No duplicate Postgres DDL in `taut_pg`.
   - No direct SQL against SimpleBroker's own tables.

5. Taut uses public SimpleBroker APIs only.
   - Production code may import from `simplebroker` and `simplebroker.ext`.
   - Production code must not import `simplebroker._*`.
   - Test helpers should also prefer public APIs. If a test uses a
     SimpleBroker private helper, it must explain why no public alternative
     exists and keep that use inside tests.

6. Shared tests are real backend conformance tests.
   - Shared tests should run against SQLite in the default suite and against
     Postgres under `bin/pytest-pg`.
   - Root shared PG tests use one schema per xdist worker. Do not use a unique
     schema per root test unless a red test proves worker-scoped isolation
     cannot work.
   - `bin/pytest-pg` must pass explicit `-n` and `--dist` values, with
     SimpleBroker-style user override extraction, so the worker schema fixtures
     and pytest parallelism stay coordinated.
   - PG-only tests live under `extensions/taut_pg/tests` and validate the
     extension package, PG config, PG schema cleanup, and PG-specific behavior.
     These extension tests may use unique per-test schemas.
   - Do not copy the same scenario into both shared and PG-only tests. Promote
     backend-agnostic behavior to shared tests; reserve PG-only tests for PG
     mechanics and extension packaging.

7. Tests are typed.
   - New test helpers and fixtures must have useful annotations.
   - Keep `mypy taut tests bin/release.py ...` in the gates, and include the
     extension package/tests in the PG gate.

8. Watcher behavior remains portable.
   - Do not make watcher correctness depend on LISTEN/NOTIFY timing.
   - PG tests can assert that live watching works with a real Postgres target,
     but should use bounded polling and should not assert fragile sub-second
     notification timing unless the test is explicitly scoped to the
     SimpleBroker waiter.

9. Release remains GitHub-only until name clearance changes.
   - Root and extension workflows must not publish to PyPI.
   - Release helper targets for both root and PG extension should have
     `pypi_publish=False`.

10. No YAGNI drift.
    - No Redis state mapping.
    - No Taut plugin registry.
    - No connection pooling knobs in Taut.
    - No hosted Postgres provisioning.
    - No auth changes.
    - No schema migration unless a red test proves v1 cannot run on Postgres.

## 6. Rollout, Rollback, And One-Way Doors

There is no intended storage-format one-way door. Taut sidecar schema version
stays `1`. The Postgres backend uses the same `taut_*` tables through
SimpleBroker sidecars.

Rollout order:

1. Add extension project and PG test helper behind no runtime behavior change.
2. Add shared test classification while the default SQLite suite remains green.
3. Add red PG tests that prove `.taut.toml` currently fails because of the
   SQLite-only guards.
4. Relax target resolution and make PG tests pass.
5. Add CI and release support.
6. Update docs after behavior is proven.

Rollback:

- If PG support causes core regressions before release, remove the extension
  project and `bin/pytest-pg`, restore SQLite-only rejection in
  `TautClient.init()` and `_resolve_target()`, and keep any useful
  test-marker cleanup only if the default suite remains simpler and green.
- If the extension release tooling is wrong but core PG support is correct,
  revert only `bin/release.py` extension-target changes and PG release
  workflows. Keep `bin/pytest-pg` and tests.
- If a published `taut_pg/vX.Y.Z` GitHub Release is bad, delete the GitHub
  Release first, then move/delete the tag according to the release helper's
  retag policy. Do not publish PyPI artifacts.

Post-deploy success signals:

- GitHub Actions "Test" remains green for SQLite/default platforms.
- GitHub Actions "Test Postgres Extension" is green.
- A local `uv run ./bin/pytest-pg --fast` run creates a temporary Docker
  Postgres container, runs shared and PG-only tests, and removes the container.
- Installing core and extension into one environment from GitHub artifacts can
  run:

  ```bash
  taut init
  taut join general --as van
  taut say general "hello from postgres"
  taut log general --json
  ```

  from a directory with `.taut.toml` and a reachable Postgres database.

## 7. Dependency-Ordered Tasks

### Task 0. Preflight and inventory

Outcome: confirm the working tree, current gates, and upstream patterns before
editing.

Files to read:

- all source documents in section 2
- `taut/client.py`
- `taut/_constants.py`
- `taut/schema.py`
- `tests/conftest.py`
- `../simplebroker/extensions/simplebroker_pg/pyproject.toml`
- `../simplebroker/bin/pytest-pg`
- `../simplebroker/simplebroker/_scripts.py::pytest_pg_main`
- `../simplebroker/tests/conftest.py`

Actions:

1. Run `git status --short`.
2. Run the default suite once:

   ```bash
   uv run pytest
   uv run ruff check taut tests bin
   uv run ruff format --check taut tests bin
   uv run mypy taut tests bin/release.py --config-file pyproject.toml
   ```

3. Record any pre-existing failures before editing.

Stop and re-evaluate if:

- the default suite is already red for unrelated reasons
- `simplebroker-pg>=2.2.1` is not sufficient for sidecar or watcher behavior
- a local SimpleBroker checkout is required to pass tests but the plan assumes
  the published dependency

Done signal:

- baseline state is known and no unowned work has been overwritten.

### Task 1. Add red tests for Taut Postgres target resolution

Outcome: prove the current SQLite-only guards are the blocker before relaxing
them.

Files to touch:

- `tests/conftest.py`
- new `tests/test_project_config.py` or focused additions to
  `tests/test_client.py`

Read first:

- `docs/specs/02-taut-core.md` [TAUT-3.2], [TAUT-12.1]
- `taut/_constants.py::load_config`
- `taut/client.py::TautClient.init`
- `taut/client.py::TautClient._resolve_target`
- `../simplebroker/extensions/simplebroker_pg/tests/test_pg_integration.py`
  project-config test

Test requirements:

1. Add typed helpers that can write a `.taut.toml` file with a caller-provided
   DSN and schema:

   ```toml
   version = 1
   backend = "postgres"
   target = "<dsn>"

   [backend_options]
   schema = "<schema>"
   ```

2. Add a test that uses a dummy non-SQLite `BrokerTarget` or a PG-marked test
   to prove `TautClient.init()` rejects the resolved Postgres target today.
   This test should fail first if written against the intended final behavior.

3. Add a test that proves explicit missing `db_path=tmp_path / ".taut.db"`
   still raises `NotInitializedError` and does not create a file. This protects
   the path-only selector while target-resolution logic changes.

4. Add a test for `.taut.toml` winning over a sibling `.broker.toml`. Taut must
   continue using `BROKER_PROJECT_CONFIG_NAME = ".taut.toml"`.

Anti-mocking guidance:

- It is acceptable in this task to use a tiny fake or monkeypatch to prove the
  current guard rejects a non-SQLite target without starting Docker.
- Do not use that fake as the final PG acceptance proof. Real PG proof comes
  later through `bin/pytest-pg`.

Stop and re-evaluate if:

- the easiest test requires importing `simplebroker._project_config` from
  production code
- the test starts defining a Taut-specific target parser

Done signal:

- targeted red tests identify the exact SQLite-only rejection and preserve
  explicit path behavior.

### Task 2. Create `extensions/taut_pg` as a separate project

Outcome: add the extension package skeleton without changing core runtime
behavior.

Files to touch:

- `extensions/taut_pg/pyproject.toml`
- `extensions/taut_pg/README.md`
- `extensions/taut_pg/LICENSE`
- `extensions/taut_pg/taut_pg/__init__.py`
- `extensions/taut_pg/taut_pg/py.typed`
- `extensions/taut_pg/tests/conftest.py`
- `extensions/taut_pg/tests/test_pg_integration.py`

Read first:

- `../simplebroker/extensions/simplebroker_pg/pyproject.toml`
- `../simplebroker/extensions/simplebroker_pg/README.md`
- `../simplebroker/extensions/simplebroker_pg/tests/conftest.py`

Implementation guidance:

1. Use `hatchling`, matching the root project and SimpleBroker extension.
2. Set project metadata:
   - `name = "taut-pg"`
   - `requires-python = ">=3.11"`
   - license and author matching the root package
   - dependencies:

     ```toml
     dependencies = [
         "taut>=0.2.0",
         "simplebroker-pg>=2.2.1",
     ]
     ```

     Use the then-current Taut version during implementation.
     `simplebroker-pg>=2.2.1` currently requires `simplebroker>=4.5.0`, which
     is compatible with Taut's existing `simplebroker>=4.7.1` requirement. If
     either bound changes before implementation, re-check compatibility before
     editing package metadata.

3. Add extension dev dependencies needed for its own tests:

   ```toml
   [project.optional-dependencies]
   dev = [
       "pytest>=7.0",
       "pytest-timeout>=2.4.0",
       "pytest-xdist>=3.0",
       "ruff>=0.1.0",
       "mypy>=1.0",
   ]
   ```

4. Add local source mapping for Taut:

   ```toml
   [tool.uv.sources]
   taut = { path = "../..", editable = true }
   ```

   Do not commit a sibling path to `../simplebroker` unless the implementation
   truly requires unreleased SimpleBroker changes.

5. Build include list should include only:
   - `/taut_pg/**/*.py`
   - `/taut_pg/py.typed`
   - `/README.md`
   - `/LICENSE`

6. `taut_pg/__init__.py` should be small. A reasonable first version is:

   ```python
   """Postgres support package for Taut."""

   __all__: list[str] = []
   ```

   Do not add a `plugin.py` unless a Taut plugin registry is explicitly
   designed in a later plan.

7. Extension README must document:
   - GitHub-only installation for now
   - requirement that core `taut` and `taut-pg` be installed in the same
     environment
   - `.taut.toml` config example
   - `bin/pytest-pg` for local tests
   - no PyPI install command until name clearance changes

Tests:

- Add a minimal `pg_only` test that imports `taut_pg`.
- Add a test that imports `simplebroker_pg` and can resolve the SimpleBroker
  `postgres` plugin through the public API:

  ```python
  from simplebroker.ext import get_backend_plugin
  assert get_backend_plugin("postgres").name == "postgres"
  ```

Stop and re-evaluate if:

- implementing `taut_pg` starts duplicating `simplebroker_pg` code
- the extension needs a runtime dependency not named here
- packaging cannot express the GitHub-only install story without a direct URL
  dependency in wheel metadata

Done signal:

- `cd extensions/taut_pg && uv build` builds a wheel and sdist.

### Task 3. Add `bin/pytest-pg`

Outcome: provide one command that runs Taut shared tests and PG-only extension
tests against a real temporary Postgres database.

Files to touch:

- `bin/pytest-pg`
- `taut/_scripts.py`
- `tests/test_dev_scripts.py`
- `pyproject.toml`

Read first:

- `../simplebroker/bin/pytest-pg`
- `../simplebroker/simplebroker/_scripts.py::pytest_pg_main`
- `../weft/bin/pytest-pg`
- `../weft/tests/system/test_pytest_pg_script.py`

Implementation guidance:

1. Follow SimpleBroker's shape:
   - `bin/pytest-pg` is a thin executable wrapper.
   - `taut/_scripts.py` owns the tested helper logic, including
     `pytest_pg_main()`.
   - `tests/test_dev_scripts.py` tests helper routing and preflight behavior.

   Use Weft's self-contained `bin/pytest-pg` only as a fallback reference for
   subprocess-group teardown and diagnostic arguments if the SimpleBroker shape
   leaves a Taut-specific question unanswered. Do not split Docker setup across
   multiple ad hoc scripts.

2. Reuse SimpleBroker env names:
   - `SIMPLEBROKER_PG_TEST_IMAGE`, default `postgres:18`
   - `SIMPLEBROKER_PG_TEST_DB`, default `taut_test`
   - `SIMPLEBROKER_PG_TEST_USER`, default `postgres`
   - `SIMPLEBROKER_PG_TEST_PASSWORD`, default `postgres`
   - `SIMPLEBROKER_PG_TEST_DSN`, set by the helper for pytest

3. The helper should:
   - require `docker` and `uv`
   - start a temporary Postgres container with `--publish-all`
   - wait for `pg_isready`
   - print the DSN with any password redacted
   - run root tests under `BROKER_TEST_BACKEND=postgres`
   - run extension tests without forcing the root shared-test marker
   - remove the container unless `--keep-container` is passed

4. Match SimpleBroker's routing behavior where practical:
   - no explicit pytest target runs both suites
   - a target under `tests/` routes to the shared suite
   - a target under `extensions/taut_pg/tests/` routes to the extension suite
   - `--fast` runs `shared and not slow` for root shared tests
   - extension tests run with marker `pg_only`
   - extract user-supplied `-m`, `-n`, and `--dist` arguments and merge them
     with runner defaults instead of passing duplicate conflicting options
   - default to `-n auto --dist loadgroup`, matching root Taut and
     SimpleBroker, so PG tests are not accidentally serialized unless the user
     explicitly passes `-n 0`

5. The `uv` command should install:

   ```bash
   uv run --extra dev \
     --with-editable . \
     --with-editable ./extensions/taut_pg[dev] \
     pytest ...
   ```

Tests:

- Test argument routing without starting Docker.
- Test marker merging for `-m`.
- Test `-n` and `--dist` override extraction.
- Test missing Docker/uv exits with a clear message, using monkeypatches.
- Test DSN redaction if the helper prints a DSN.

Anti-mocking guidance:

- Unit tests may mock Docker and subprocess calls for helper argument routing.
- The acceptance gate must run the real `bin/pytest-pg` with Docker.

Stop and re-evaluate if:

- the helper starts relying on private `simplebroker._scripts`
- the implementation cannot use an importable `taut._scripts.py` helper; if so,
  inspect Weft and record why the fallback shape is better
- the helper needs platform-specific shell features that break Windows parsing
  unnecessarily
- the helper cannot clean up a failed container reliably
- the helper relies on ambient `pyproject.toml` addopts for xdist behavior
  instead of passing explicit coordinated `-n`/`--dist` options

Done signal:

- `uv run ./bin/pytest-pg --help` works.
- Helper unit tests pass without Docker.

### Task 4. Add backend markers and shared-test harness

Outcome: classify tests honestly and give shared tests a single backend-aware
fixture path.

Files to touch:

- `pyproject.toml`
- `tests/conftest.py`
- existing tests that should be marked or refactored

Read first:

- `../simplebroker/tests/conftest.py` marker logic
- `../weft/tests/helpers/test_backend.py`
- `../weft/README.md` "Testing"
- `docs/agent-context/runbooks/testing-patterns.md`

Implementation guidance:

1. Add pytest markers to root `pyproject.toml`:

   ```toml
   markers = [
       "slow: marks tests as slow (deselect with '-m \"not slow\"')",
       "shared: backend-agnostic tests that should pass on SQLite and Postgres",
       "sqlite_only: tests that validate built-in SQLite/path behavior",
       "pg_only: tests that validate the Postgres extension package",
   ]
   ```

2. Add a typed active-backend helper:

   ```python
   POSTGRES_TEST_BACKEND = "postgres"

   def active_backend(env: Mapping[str, str] | None = None) -> str:
       ...
   ```

   Use `BROKER_TEST_BACKEND=postgres` only as a test-runner control variable.
   It is not a public Taut runtime API.

3. Use this explicit root shared-test ownership model:
   - SQLite shared tests use one temporary project root per test.
   - Postgres shared tests use one schema per xdist worker, derived from
     pytest's `worker_id` fixture. The non-xdist worker name is usually
     `master`; sanitize the final schema name to lowercase letters, digits, and
     underscores.
   - The worker schema name is the only schema source for root shared tests.
     Store it in `SIMPLEBROKER_PG_TEST_SCHEMA` for subprocesses.
   - Extension PG-only tests under `extensions/taut_pg/tests` may use unique
     per-test schemas because they test extension mechanics directly.

4. Add typed worker-scoped PG helpers to `tests/conftest.py`:
   - `pg_test_dsn() -> str | None`
   - `pg_worker_schema(worker_id: str, pg_test_dsn: str | None) -> str | None`
   - `pg_backend_plugin(...)`
   - a session cleanup fixture that drops only the worker schema it created

   Prefer public APIs:

   ```python
   from simplebroker.ext import get_backend_plugin

   get_backend_plugin("postgres").cleanup_target(
       dsn,
       backend_options={"schema": schema},
   )
   ```

   If implementation needs a SimpleBroker private helper for exact TOML parsing
   or a faster table reset, keep that import inside tests, add a short comment
   naming the missing public alternative, and do not use it in production code.

5. Add one typed helper for writing or ensuring `.taut.toml`:

   ```python
   def ensure_taut_project_config(root: Path, *, dsn: str, schema: str) -> Path:
       ...
   ```

   This helper is the only code path that writes `.taut.toml` in root tests.
   It must be idempotent: if a `.taut.toml` already exists at the target root,
   leave it in place and return it.

6. Add a typed `taut_project` fixture for shared API tests:
   - creates a temp project root
   - writes `.taut.toml` through `ensure_taut_project_config()` when active
     backend is Postgres
   - changes cwd to the project root
   - resets the worker PG schema before the test by dropping only that schema,
     then lets the real `TautClient` / `taut init` path recreate broker and
     Taut sidecar state
   - performs session-final cleanup of the worker schema

   Start with public `cleanup_target()` plus real Taut initialization. Do not
   add direct SQL against SimpleBroker tables. If this is too slow or breaks
   runner reuse, stop and propose a focused test-only reset helper instead of
   silently copying SimpleBroker's private TRUNCATE code.

7. Add PG schema-name helper:
   - derive from `worker_id` for root shared tests
   - derive from UUID or `tmp_path` for extension PG-only tests
   - use lowercase letters, digits, and underscores
   - do not use `public`

8. Add cleanup using public APIs:
   - prefer `from simplebroker.ext import get_backend_plugin`
   - call `get_backend_plugin("postgres").cleanup_target(dsn,
     backend_options={"schema": schema})`
   - do not import `simplebroker._project_config` in production code

9. Update `run_cli()`:
   - keep its public shape
   - when active backend is Postgres, derive the config root from `cwd`
     only. Taut's CLI has no `--dir`/`-d` flag; do not copy SimpleBroker's
     `--dir` parsing into this harness.
   - ensure that root has `.taut.toml` by calling
     `ensure_taut_project_config()` with the worker schema
   - pass `SIMPLEBROKER_PG_TEST_DSN` through
   - pass `SIMPLEBROKER_PG_TEST_SCHEMA` through when set
   - do not set `TAUT_DB`
   - do not document or rely on `BROKER_BACKEND=postgres` for runtime behavior

10. Classify tests:
   - `sqlite_only`: explicit `db_path`, `--db`, missing file behavior,
     filesystem permissions, SQLite catalog/file assertions.
   - `shared`: CLI/client behavior that should work against any SQL backend.
   - Prefer explicit `pytestmark = pytest.mark.shared` in modules that are
     fully shared. Use function-level marks for mixed modules.

Tests:

- Add or update tests that prove root collection rejects unmarked tests instead
  of silently assigning backend coverage.
- Add a small test for `.taut.toml` helper output.
- Add a small test that `run_cli()` and `taut_project` use the same schema-name
  source when `BROKER_TEST_BACKEND=postgres`.
- Add a helper test that a user-supplied `.taut.toml` is not overwritten.

Stop and re-evaluate if:

- the harness needs to monkeypatch Taut internals to select Postgres
- shared tests still pass while bypassing `TautClient` or the real CLI
- a test becomes shared but still asserts on `.taut.db` existence
- root shared tests start creating a unique schema per test instead of using
  the worker schema model
- `.taut.toml` writing logic appears in both `taut_project` and `run_cli()`
  instead of one shared helper

Done signal:

- `uv run pytest -m shared` passes on SQLite.
- `uv run pytest -m sqlite_only` passes on SQLite.
- No unknown-marker warnings.

### Task 5. Relax target resolution safely

Outcome: allow `.taut.toml` Postgres targets while preserving all explicit path
rules and default SQLite behavior.

Files to touch:

- `taut/_constants.py`
- `taut/client.py`
- `tests/test_project_config.py`
- `tests/test_client.py`
- `tests/test_cli.py`

Read first:

- `docs/specs/02-taut-core.md` [TAUT-3.2], [TAUT-12.1]
- `../simplebroker/simplebroker/project.py`
- `../simplebroker/simplebroker/_project_config.py`
- `../simplebroker/simplebroker/commands.py::cmd_init`

Implementation guidance:

1. Preserve explicit path behavior:
   - `db_path=`, `--db`, and `TAUT_DB` still become filesystem paths.
   - non-init commands still require those paths to exist before opening.
   - `taut init --db PATH` still creates that SQLite path.
   - Do not treat a string containing `postgresql://` as a DSN in these paths.

2. For project resolution:
   - `resolve_broker_target(Path.cwd(), config=self.config)` may return
     `BrokerTarget(backend_name="postgres", ...)`.
   - Do not reject that target.
   - Do not call `Path(target.target).exists()` for non-SQLite targets.
   - Let `Queue(..., db_path=target, config=config)` and
     `schema.ensure_schema()` validate connection and sidecar support.

3. For `TautClient.init()`:
   - call `target_for_directory(Path.cwd(), config=config)` as today.
   - if target is SQLite, keep current file-created semantics.
   - if target is Postgres, initialize through `Queue(META_QUEUE_NAME,
     db_path=target, config=config)` plus `schema.ensure_schema(queue)`.
   - return `InitResult(db=target.display_target, created=False)` for
     non-SQLite targets unless a public backend API gives a reliable creation
     boolean.

4. For missing plugin errors:
   - allow SimpleBroker's public error to surface with a useful install hint
     when `simplebroker-pg` is not installed.
   - Do not catch it and replace it with generic
     `BackendNotSupportedError`.

5. For ambient `BROKER_BACKEND`:
   - Add `"BROKER_BACKEND": "sqlite"` to the raw dict in
     `taut._constants.load_config()` before calling `resolve_config(raw)`.
   - Do not set or clear `BROKER_BACKEND_TARGET` in Taut; SimpleBroker project
     config resolution already clears ambient target before passing TOML target
     data to non-SQLite plugins.
   - Preserve `.taut.toml` selection. This works because SimpleBroker checks the
     project config before env-selected backend synthesis, and
     `resolve_project_target()` takes the backend name from the TOML file.
   - If this pin breaks `.taut.toml` password supplementation through the
     SimpleBroker plugin, stop and inspect the plugin contract before changing
     Taut's public API.

Tests:

- `taut init` creates `.taut.db` by default.
- `taut init` under `.taut.toml` Postgres succeeds under `bin/pytest-pg`.
- `taut init --json` under PG returns `created: false` and a display-safe
  target.
- non-init commands under `.taut.toml` PG do not try `Path(dsn).exists()`.
- `BROKER_BACKEND=postgres` without `.taut.toml` still uses Taut's SQLite
  default path.
- `.taut.toml` with `backend = "postgres"` still wins even though
  `load_config()` pins ambient `BROKER_BACKEND` to SQLite.
- `--db missing.db list` still exits 1 with the `taut init` hint.
- `.broker.toml` alone does not redirect Taut.
- `.taut.toml` with missing `simplebroker-pg` gives an install-hint failure.

Stop and re-evaluate if:

- the fix requires changing SimpleBroker target resolution
- the fix creates a separate Taut target object
- `TAUT_DB` DSN support looks tempting
- the ambient backend pin suppresses TOML-based Postgres selection

Done signal:

- red tests from Task 1 pass.
- default SQLite tests still pass.

### Task 6. Promote backend-agnostic behavior into shared tests

Outcome: shared tests prove Taut's public behavior through the same paths on
SQLite and Postgres.

Files to touch:

- `tests/test_client.py`
- `tests/test_cli.py`
- `tests/test_schema.py`
- `tests/test_watcher.py`
- possible new `tests/test_shared_contract.py`

Read first:

- current test files listed above
- `docs/specs/02-taut-core.md` [TAUT-3] through [TAUT-8]

Implementation guidance:

1. Refactor shared API tests to use `taut_project` and implicit project
   resolution:

   ```python
   def test_join_starts_at_now(..., taut_project: Path) -> None:
       TautClient.init()
       van = TautClient(as_handle="van")
       ...
   ```

   Keep explicit `db_path` tests separate and `sqlite_only`.

2. Shared client behaviors to cover:
   - init
   - join
   - say
   - log
   - read and cursor advance
   - list unread counts
   - reply and sub-thread creation
   - who/whoami with explicit `--as`
   - rejoin by token
   - guest read-only command does not advance timestamp

3. Shared CLI behaviors to cover:
   - `init --json`
   - `join --json`
   - `say --json`
   - `log --json`
   - human grouped output shape if it is backend-agnostic
   - exit code 2 for empty read
   - token hoisting/rejoin behavior

4. Shared schema behaviors to cover:
   - `schema.ensure_schema()` idempotent through real `Queue.sidecar()`
   - newer schema version refuses
   - cursor advance monotonic
   - uniqueness races resolve by reading the winner where feasible

5. Keep SQLite-only:
   - explicit missing path tests
   - `TAUT_DB` path tests
   - file mode tests if added
   - any assertion that opens `.taut.db` through `sqlite3`

Anti-mocking guidance:

- Do not mock `Queue`, `Queue.sidecar()`, timestamps, or CLI subprocesses for
  shared acceptance tests.
- For identity, use explicit `--as` or injected `identity_capture` where the
  test is about Taut behavior rather than OS process heuristics.

Stop and re-evaluate if:

- shared tests become so abstract that they no longer read like user behavior
- shared tests duplicate large blocks between SQLite and PG
- a shared fixture hides failures by auto-initializing when the user path would
  not

Done signal:

- `uv run pytest -m shared` passes locally against SQLite.
- `uv run ./bin/pytest-pg --fast` runs shared tests against PG.

### Task 7. Add PG-only extension tests

Outcome: prove the extension package, `.taut.toml`, Postgres sidecar behavior,
and cleanup lifecycle with real Postgres.

Files to touch:

- `extensions/taut_pg/tests/conftest.py`
- `extensions/taut_pg/tests/test_pg_integration.py`
- `extensions/taut_pg/tests/test_pg_sidecar.py`
- optional focused files:
  - `test_pg_cli.py`
  - `test_pg_packaging.py`
  - `test_pg_watcher.py`

Read first:

- `../simplebroker/extensions/simplebroker_pg/tests/conftest.py`
- `../simplebroker/extensions/simplebroker_pg/tests/test_pg_sidecar.py`
- `../simplebroker/extensions/simplebroker_pg/tests/test_pg_integration.py`

Test requirements:

1. Extension import and plugin resolution:
   - `import taut_pg`
   - `import simplebroker_pg`
   - `simplebroker.ext.get_backend_plugin("postgres").name == "postgres"`

2. CLI project-config round trip:
   - write `.taut.toml`
   - run `taut init`
   - run `taut join general --as van --json`
   - run `taut say general hello --as van --json`
   - run `taut log general --json`
   - assert message text and member handle from output

3. API project-config round trip:
   - same behavior through `TautClient` from a nested directory
   - proves upward `.taut.toml` discovery

4. Sidecar tables:
   - initialize Taut under PG
   - prove `schema.get_schema_version()` returns `1`
   - prove partial unique indexes work by exercising the real identity/member
     helpers, not by querying catalog tables first
   - optional support assertion with raw psycopg that `taut_meta`,
     `taut_members`, `taut_threads`, and `taut_membership` exist in the
     configured schema

5. Missing plugin message:
   - this can be a unit test with monkeypatching entry-point resolution if
     starting a no-plugin environment is too expensive
   - it must assert an actionable install hint

6. Cleanup:
   - every PG test uses a unique schema
   - cleanup drops only schemas it created
   - cleanup refuses or skips `public`

Anti-mocking guidance:

- Do not mock Postgres for PG-only integration tests.
- Do not inspect only catalog tables as the proof. Catalog inspection is
  supporting evidence; the main proof is real Taut operations succeeding.

Stop and re-evaluate if:

- tests require raw psycopg for normal Taut operations instead of setup/cleanup
- PG-only tests start duplicating shared CLI/client tests wholesale
- a cleanup failure can leave dangerous schema names in the database

Done signal:

- `uv run ./bin/pytest-pg extensions/taut_pg/tests -m pg_only` passes.

### Task 8. Add PG watcher and concurrency coverage

Outcome: prove the behavior most likely to regress across backends: live
watching, cursor advancement, and concurrent writers.

Files to touch:

- `tests/test_watcher.py`
- `extensions/taut_pg/tests/test_pg_watcher.py`

Read first:

- `docs/specs/02-taut-core.md` [TAUT-7], [TAUT-8.4], [TAUT-12.1]
- `taut/watcher.py`
- `tests/test_watcher.py`
- `../simplebroker/extensions/simplebroker_pg/tests/test_pg_notify.py`

Test requirements:

1. Shared watcher subprocess test:
   - start a `TautWatcher` in-process
   - write a message from CLI subprocess
   - wait with bounded polling until the watcher sees it
   - assert watcher remains alive

2. Shared concurrent writer test:
   - two CLI subprocesses write to the same thread
   - log shows both messages
   - message IDs are sorted

3. PG-only watcher smoke:
   - same as shared watcher, but run under PG and marked `pg_only` if it needs
     PG-specific setup
   - do not assert exact LISTEN/NOTIFY latency

4. Cursor invariant:
   - after watcher dispatches a message, membership cursor advances at least to
     that message timestamp
   - repeated drain does not redispatch

Anti-mocking guidance:

- Use real CLI subprocesses and real Postgres.
- Mocking a wake event is not enough; the test must prove a real write becomes
  visible to a real watcher.

Stop and re-evaluate if:

- tests become timing-sensitive and flaky
- the implementation tries to special-case Postgres in `TautWatcher`
- the watcher refresh timer is removed because PG notifications seem enough

Done signal:

- watcher tests pass in default SQLite suite and PG helper suite.

### Task 9. Add CI and release support for the extension

Outcome: make PG support testable and releasable from GitHub without PyPI.

Files to touch:

- `.github/workflows/test-pg-extension.yml`
- `.github/workflows/release-gate-pg.yml`
- existing `.github/workflows/release.yml`
- existing `.github/workflows/release-gate.yml`
- `bin/release.py`
- `tests/test_release_script.py`
- `tests/test_github_workflows.py`

Read first:

- `../simplebroker/.github/workflows/test-pg-extension.yml`
- `../simplebroker/.github/workflows/release-gate-pg.yml`
- `../simplebroker/bin/release.py`
- current Taut `.github/workflows/test.yml`
- current Taut `.github/workflows/release.yml`
- current Taut `.github/workflows/release-gate.yml`
- current Taut `bin/release.py`
- current Taut workflow tests

Implementation guidance:

1. Add `test-pg-extension.yml`:
   - run on push, pull_request, workflow_dispatch, and workflow_call
   - use Ubuntu
   - test Python 3.11, 3.13, 3.14 unless runtime support matrix changes
   - install uv
   - run `uv run ./bin/pytest-pg`
   - lint/format/type-check extension paths:

     ```bash
     uv run --extra dev ruff check extensions/taut_pg/taut_pg extensions/taut_pg/tests bin/pytest-pg
     uv run --extra dev ruff format --check extensions/taut_pg/taut_pg extensions/taut_pg/tests bin/pytest-pg
     uv run --extra dev mypy extensions/taut_pg/taut_pg extensions/taut_pg/tests --config-file pyproject.toml
     ```

     Adjust if helper logic lives in `taut/_scripts.py`.

2. Add `release-gate-pg.yml`:
   - trigger on `taut_pg/v*`
   - follow SimpleBroker's `release-gate-pg.yml` for tag namespace, package
     name, package directory, release-name extraction, and tag-still-current
     checks
   - do not copy SimpleBroker's PyPI or attestation jobs unless the root Taut
     release workflow already has the same GitHub-only behavior
   - call the reusable root Test workflow and the new reusable Test Postgres
     Extension workflow directly, matching Taut's existing release gate style
   - verify tag still points at the tested commit
   - call `.github/workflows/release.yml` with:
     - `package_name: taut-pg`
     - `package_dir: extensions/taut_pg`
     - tag/ref inputs for the extension tag
   - no PyPI jobs

3. Update the existing root `release-gate.yml`:
   - add a reusable workflow job for `test-pg-extension.yml`
   - make tag-current verification and publication depend on both root Test and
     Test Postgres Extension
   - keep GitHub-only publishing
   - verify tag-current checks remain before release publication

4. Inspect `release.yml` before editing:
   - it already accepts `package_dir`, so prefer reuse
   - ensure artifact names are safe for `taut-pg`
   - edit only if the current reusable workflow cannot build and upload a
     subdirectory package

5. Update `bin/release.py`:
   - add `PG_RELEASE_TARGET`
   - package name `taut-pg`
   - package dir `extensions/taut_pg`
   - tag namespace `taut_pg`
   - `github_release=True`
   - `pypi_publish=False`
   - add precheck commands for PG target:
     - default root checks that still matter
     - `uv run ./bin/pytest-pg --fast` for release gate speed, or full
       `uv run ./bin/pytest-pg` if runtime is acceptable
     - extension build
     - extension lint/type checks
   - support `--target pg`, matching SimpleBroker's target-selection style
     when choosing one package target from a multi-target release helper.

6. Add release script tests:
   - tag name for PG target is `taut_pg/v1.2.3`
   - PG target has no PyPI publish
   - PG prechecks include `./bin/pytest-pg`
   - extension build path is `extensions/taut_pg`
   - root release remains `vX.Y.Z`

7. Add workflow tests:
   - PG workflow runs `./bin/pytest-pg`
   - PG workflow exposes `workflow_call`
   - PG release gate has no PyPI text
   - PG release gate verifies tag before publishing
   - root release gate requires the PG workflow before publishing

Stop and re-evaluate if:

- adding PG release support forces PyPI assumptions into root release code
- release helper complexity starts approaching SimpleBroker's multi-backend
  matrix without a local need
- extension tags cannot be published with current reusable workflow inputs
- the plan starts needing Weft's PyPI-first release workflow for any reason

Done signal:

- release helper dry run for root still works.
- release helper dry run for PG target works.
- workflow YAML parses.

### Task 10. Update docs and traceability

Outcome: make the behavior discoverable and keep spec, plan, and implementation
docs aligned.

Files to touch:

- `README.md`
- `docs/specs/02-taut-core.md`
- `docs/implementation/02-repository-map.md`
- `docs/implementation/04-taut-architecture.md`
- this plan's status/evidence sections if implementation is performed under
  this plan

Read first:

- current README "Installation", "Command Reference", "Roadmap", and trust
  model sections
- `docs/agent-context/runbooks/maintaining-traceability.md`

Documentation requirements:

1. README install section:
   - keep GitHub-only install path
   - add a Postgres extension install note, but only with syntax verified by
     an install smoke test during implementation. Preferred documented shape is
     GitHub Release wheels because it avoids direct-URL ambiguity for a
     subdirectory package:

     ```bash
     pipx install "git+https://github.com/VanL/taut.git@vX.Y.Z"
     pipx inject taut ./taut_pg-VERSION-py3-none-any.whl
     ```

     If implementation proves a direct GitHub subdirectory install works
     reliably for the chosen tag shape, it may document that as an additional
     option. Do not publish an untested direct-URL command.

2. README Postgres config:
   - show `.taut.toml`
   - explain database must already exist
   - explain `taut init` initializes the configured schema/tables
   - explain `taut init --json` reports `db` as the resolved display target;
     for Postgres this is a redacted DSN-like target, not a filesystem path
   - explain `created` is `false` for Postgres unless a future public backend
     API can report a reliable creation result
   - explain trust boundary is storage access, not auth

3. README dependency text:
   - root package runtime deps remain `simplebroker` and `psutil`
   - Postgres extension adds `simplebroker-pg` and its Postgres driver deps
   - do not say "one dependency"

4. Spec:
   - update [TAUT-12.1] from roadmap-only to implementation status when code
     lands
   - keep [TAUT-3.2] clear that `TAUT_DB` is path-only
   - update [TAUT-8.2] or the relevant CLI output section so `init --json db`
     is a backend display target, not always a path
   - add or update related-plan backlink

5. Architecture doc:
   - explain `taut-pg` boundary
   - explain root vs extension release boundary
   - update verification commands with PG helper

6. Repository map:
   - add `extensions/taut_pg`
   - add `bin/pytest-pg`
   - add PG workflows

Stop and re-evaluate if:

- docs start describing env-only backend selection
- docs imply Postgres adds auth or untrusted multi-tenant safety
- install docs depend on PyPI names before clearance

Done signal:

- docs describe exactly how to install, configure, test, and release PG support
  from GitHub.

### Task 11. Run review, cleanup, and final verification

Outcome: finish with concrete evidence, no stale docs, and no hidden drift.

Actions:

1. Run the smallest targeted tests for changed behavior.
2. Run full default local gates.
3. Run full PG gates.
4. Run grep gates in section 9.
5. Run independent review from section 10.
6. Incorporate or explicitly answer review findings.
7. Update this plan with observed verification if implementation is done under
   it.

Stop and re-evaluate if:

- review finds the plan implemented a materially different shape
- PG support works only by bypassing public SimpleBroker APIs
- any cleanup task requires dropping unknown schemas

Done signal:

- verification evidence is recorded in the implementation PR/commit message or
  plan update.

## 8. Testing Plan

Testing is the main guardrail for this feature. The implementer should keep
tests real and layered.

### Default SQLite suite

Run on every change:

```bash
uv run pytest
```

This must keep proving no-config SQLite behavior, explicit path behavior,
identity behavior, renderer behavior, and watcher behavior.

### Shared suite

Shared tests are backend-agnostic public behavior tests. Run them on SQLite:

```bash
uv run pytest -m shared
```

Run the same shared tests on Postgres:

```bash
uv run ./bin/pytest-pg --fast
```

Shared tests should prove:

- `taut init`
- `join`, `say`, `reply`, `read`, `log`, `list`
- membership and cursor semantics
- `who`/`whoami` where identity can be deterministic
- CLI JSON output
- watcher sees real writes and advances cursors

### SQLite-only suite

Run:

```bash
uv run pytest -m sqlite_only
```

SQLite-only tests should cover:

- explicit missing path
- `TAUT_DB` as path
- `.taut.db` file creation
- file or sqlite catalog assertions

### PG-only suite

Run:

```bash
uv run ./bin/pytest-pg extensions/taut_pg/tests -m pg_only
```

PG-only tests should cover:

- extension import
- SimpleBroker `postgres` plugin availability
- `.taut.toml` project config
- PG schema setup and cleanup
- PG sidecar table compatibility
- PG-specific missing-plugin/install-hint behavior
- GitHub-only packaging assumptions where practical

### What not to mock

Do not mock:

- `TautClient` in acceptance tests
- `Queue`
- `Queue.sidecar()`
- SimpleBroker timestamp generation
- SimpleBroker backend plugin registration in PG acceptance tests
- CLI subprocesses in CLI behavior tests
- real Postgres in PG acceptance tests

Allowed narrow mocks:

- Docker/subprocess calls inside unit tests for `bin/pytest-pg` argument
  routing and preflight error messages
- entry-point resolution for the missing-plugin error test
- process identity capture where the test is about Taut membership semantics,
  not OS process discovery

## 9. Verification And Gates

Final local gates before claiming implementation complete:

```bash
uv run pytest
uv run pytest -m shared
uv run pytest -m sqlite_only
uv run ./bin/pytest-pg --fast
uv run ./bin/pytest-pg
uv run ruff check taut tests bin extensions/taut_pg/taut_pg extensions/taut_pg/tests
uv run ruff format --check taut tests bin extensions/taut_pg/taut_pg extensions/taut_pg/tests
uv run --extra dev mypy taut tests bin/release.py extensions/taut_pg/taut_pg extensions/taut_pg/tests --config-file pyproject.toml
uv build
cd extensions/taut_pg && uv build
```

If `bin/pytest-pg` helper logic lives in `taut/_scripts.py`, include that file
in the normal `taut` checks automatically. If it is self-contained in `bin/`,
ensure `bin/pytest-pg` is linted and type-checked through the chosen command.

Workflow/YAML gate:

```bash
python - <<'PY'
from pathlib import Path
import yaml

for path in Path(".github/workflows").glob("*.yml"):
    yaml.safe_load(path.read_text())
PY
```

Grep gates:

```bash
rg -n "from simplebroker\\._|import simplebroker\\._" taut extensions/taut_pg
rg -n "sidecar\\(|SELECT |INSERT |UPDATE |DELETE |CREATE TABLE|CREATE INDEX" taut extensions/taut_pg
rg -n "Queue\\.write\\(" taut extensions/taut_pg
rg -n "psycopg|psycopg_pool|simplebroker_pg" taut
rg -n "pypi|trusted-publishing|uv publish|gh-action-pypi-publish" .github bin README.md docs
```

Expected interpretation:

- Private SimpleBroker imports: no production hits.
- SQL hits: production Taut SQL should be in `taut/schema.py`; extension tests
  may have raw PG inspection SQL when justified.
- `Queue.write(`: no hits in Taut production code.
- `psycopg`/`simplebroker_pg` in `taut`: no core runtime hits.
- PyPI grep: only explanatory docs/tests that assert no PyPI publishing, not
  live workflow publish steps.

Packaging smoke:

```bash
python -m venv /tmp/taut-pg-smoke
. /tmp/taut-pg-smoke/bin/activate
python -m pip install dist/taut-*.whl
python -m pip install extensions/taut_pg/dist/taut_pg-*.whl
python - <<'PY'
import taut
import taut_pg
from simplebroker.ext import get_backend_plugin

assert taut
assert taut_pg is not None
assert get_backend_plugin("postgres").name == "postgres"
PY
```

Adjust wheel filenames to actual build output. If installing the extension
wheel alone tries to resolve `taut` from PyPI and fails, install the root wheel
first as shown. That is expected under GitHub-only publishing.

## 10. Independent Review Loop

Before implementation:

Use a different agent family than the authoring agent if available. Give this
prompt:

> Read `docs/plans/2026-06-17-taut-pg-extension-plan.md`, then inspect the
> referenced Taut and SimpleBroker files. Do not implement. Look for errors,
> bad ideas, hidden coupling, missing tests, over-mocking risks, packaging
> mistakes, release-flow mistakes, and places where the plan drifts from
> SimpleBroker's extension pattern. Could you implement this confidently and
> correctly if asked? If not, name the blocker precisely.

Reviewer must read at least:

- this plan
- `taut/client.py`
- `taut/_constants.py`
- `taut/schema.py`
- `tests/conftest.py`
- `pyproject.toml`
- `bin/release.py`
- `../simplebroker/extensions/simplebroker_pg/pyproject.toml`
- `../simplebroker/bin/pytest-pg`
- `../simplebroker/tests/conftest.py`

Author response requirement:

- Update this plan for valid findings.
- Or answer why a finding is intentionally out of scope.
- If the reviewer says they could not implement confidently, treat that as a
  blocker until fixed or explicitly scoped.

During implementation:

- Run another review after Task 5, because target resolution is the riskiest
  core behavior change.
- Run final review after Task 9, because release/CI changes can fail while
  local code works.

## 11. Fresh-Eyes Review

Author pass 1, 2026-06-17:

- Found packaging ambiguity around `taut[pg]`. Fixed by making the first slice
  GitHub-extension install only and deferring root convenience extra until
  PyPI/name semantics are settled.
- Found target-selection ambiguity around ambient `BROKER_BACKEND`. Fixed by
  making `.taut.toml` the supported path and requiring tests/docs not to expose
  env-only backend selection.
- Found `taut init` ambiguity for non-file targets. Fixed by defining
  `InitResult.created=False` for non-SQLite targets unless a reliable public
  backend creation result exists.
- Found over-mocking risk in PG tests. Fixed by requiring real Docker
  Postgres for acceptance and limiting mocks to helper preflight/routing tests.

Author pass 2, 2026-06-17:

- Checked for material drift from the user request. The plan still follows the
  SimpleBroker pattern: `extensions/`, separate project, `bin/pytest-pg`,
  `shared` and `pg_only` tests, extension CI/release, clear plugin boundary.
- The only deliberate deviation is no root `taut[pg]` extra in the first slice.
  Reason: current Taut publishing is GitHub-only and the package name is not
  cleared on PyPI. Adding a PyPI-style extra now would create an install path
  that cannot work reliably from an index.
- Checked for missing file paths. The plan names core, extension, test,
  workflow, release, and docs files.
- Checked for weak phrases like "update the logic". Tasks now name the owner
  function or file and the expected behavior.
- Checked for rollback and cleanup. Rollback is explicit; PG schema cleanup is
  part of the harness.

Author pass 3, 2026-06-17:

- Incorporated the pattern hierarchy explicitly after user clarification:
  SimpleBroker first, Weft only when SimpleBroker has no answer, ask if both
  are silent.
- Removed an implementation choice around `bin/pytest-pg`. SimpleBroker has a
  clear pattern, so the plan now requires a thin bin wrapper over
  `taut/_scripts.py::pytest_pg_main()`.
- Tightened root release gating. Because root Taut owns target resolution, root
  releases must require the PG workflow once PG support lands.
- Removed an unproven direct GitHub subdirectory `pipx inject` command from
  the README task. The plan now requires verified install syntax and prefers
  GitHub Release wheels for the first documented extension install path.

Independent review response, 2026-06-17:

- Resolved the `BROKER_BACKEND` ambiguity. The plan now requires
  `load_config()` to pin ambient `BROKER_BACKEND` to SQLite, and names the
  SimpleBroker precedence rule that keeps `.taut.toml` Postgres selection
  working.
- Reconciled the PG shared-test harness with xdist. Root shared tests now use
  one schema per xdist worker; extension PG-only tests may use unique per-test
  schemas.
- Assigned `.taut.toml` ownership. One shared helper writes or preserves the
  project config; `taut_project` and `run_cli()` both call that helper.
- Removed Weft release workflows as implementation references. Taut's existing
  GitHub-only reusable `release.yml` is the publishing source of truth.
- Added `workflow_call` to the planned PG test workflow and made release gates
  call reusable test workflows directly.
- Added documentation requirements for `taut init --json` under Postgres:
  `db` is a display target, not always a path, and `created` is `false`.

If implementation discovers that the extension package cannot be useful without
a root `taut[pg]` extra or a real Taut plugin registry, stop and ask before
changing direction. That would be materially different from this plan.

## 12. Out Of Scope

- PyPI publication or Trusted Publishing.
- Public `taut[pg]` extra until package-name and GitHub/PyPI dependency
  semantics are decided.
- Redis/Valkey state mapping.
- Taut plugin registry.
- Postgres database provisioning.
- Authentication, authorization, message integrity, or multi-tenant safety.
- Schema version bump or migrations.
- Connection pool tuning in Taut.
- Performance benchmarking beyond smoke-level PG responsiveness.
- TUI or summon work.

## 13. Implementation Evidence

Implemented in this local worktree on 2026-06-17:

- Added `extensions/taut_pg` as a separate `taut-pg` project with package
  metadata, README, typed package marker, and PG-only tests.
- Added `bin/pytest-pg` backed by `taut/_scripts.py::pytest_pg_main()` to run
  root `shared` tests and extension `pg_only` tests against a temporary Docker
  Postgres container.
- Added typed backend-aware root test harness helpers for `.taut.toml`, worker
  schemas, PG cleanup, and subprocess CLI execution.
- Relaxed Taut target resolution so `.taut.toml` can select Postgres while
  `TAUT_DB`, `--db`, and `db_path=` remain filesystem path selectors.
- Pinned ambient `BROKER_BACKEND` to SQLite in Taut config so env-only
  SimpleBroker backend selection does not become Taut's public API.
- Kept all Taut-owned SQL in `taut/schema.py` and changed 64-bit timestamp/id
  columns to `BIGINT` for Postgres compatibility.
- Added GitHub-only PG test and release-gate workflows plus `bin/release.py`
  support for the `taut_pg/vX.Y.Z` extension tag namespace.
- Updated README, spec, architecture docs, repository map, and lessons.

Final local verification:

```bash
uv run pytest tests/test_project_config.py tests/test_release_script.py \
  tests/test_github_workflows.py tests/test_dev_scripts.py -q
# 43 passed

uv run ./bin/pytest-pg --fast -n 0
# root shared: 4 passed, 90 deselected
# extension pg_only: 8 passed

uv run pytest
# 95 passed

uv run pytest -m shared
# 4 passed

uv run pytest -m sqlite_only
# 90 passed

uv run ./bin/pytest-pg --fast
# root shared: 4 passed
# extension pg_only: 8 passed

uv run ./bin/pytest-pg
# root shared: 4 passed
# extension pg_only: 8 passed

uv run ruff check taut tests bin \
  extensions/taut_pg/taut_pg extensions/taut_pg/tests
# All checks passed

uv run ruff format --check taut tests bin \
  extensions/taut_pg/taut_pg extensions/taut_pg/tests
# 34 files already formatted

uv run --extra dev mypy taut tests bin/release.py extensions/taut_pg/taut_pg \
  extensions/taut_pg/tests --config-file pyproject.toml
# Success: no issues found in 32 source files

uv build
# built taut-0.2.0 sdist and wheel

uv build extensions/taut_pg
# built taut_pg-0.2.0 sdist and wheel

uv run --with pyyaml python - <<'PY'
from pathlib import Path
import yaml

for path in Path(".github/workflows").glob("*.yml"):
    yaml.safe_load(path.read_text())
PY
# parsed all workflow YAML files

python bin/release.py --dry-run --skip-checks
# root target dry-run succeeded for v0.2.0

python bin/release.py --target pg --dry-run --skip-checks
# taut-pg target dry-run succeeded with tag taut_pg/v0.2.0
```

Packaging smoke:

```bash
python -m venv /tmp/taut-pg-smoke
. /tmp/taut-pg-smoke/bin/activate
python -m pip install /Users/van/dist/taut-0.2.0-py3-none-any.whl \
  extensions/taut_pg/dist/taut_pg-0.2.0-py3-none-any.whl
python - <<'PY'
import taut
import taut_pg
from simplebroker.ext import get_backend_plugin

assert taut
assert taut_pg is not None
assert get_backend_plugin("postgres").name == "postgres"
PY
# smoke ok
```

Grep gate notes:

- No private SimpleBroker imports in production or extension code.
- No `Queue.write(` use in Taut or `taut-pg`.
- Production sidecar SQL is confined to `taut/schema.py`; PG extension tests
  use raw SQL only for schema-inspection support assertions.
- `psycopg` appears in `taut/_scripts.py` as a lazy import for the developer
  `bin/pytest-pg` DSN readiness probe, not in the core runtime path.
- PyPI-related grep hits are release-helper fields or docs/tests asserting the
  GitHub-only boundary; workflows contain no PyPI publication jobs.
