# SimpleBroker Configuration Isolation Plan

Class: 5 — [TAUT-3.2] and SimpleBroker's public configuration contract change.
The cross-repository compatibility boundary also triggers mandatory hardening.

Plan type: implementation with spec revision.

Status: completed 2026-08-13 after published-artifact verification and
independent completed-work review.

## 1. Goal

Make Taut and standalone SimpleBroker configuration symmetric and isolated:
ambient `BROKER_*` values do not affect Taut, and ambient `TAUT_*` values do
not affect standalone SimpleBroker. Taut compiles its own complete `TAUT_*`
configuration, mechanically renames every supported key to `BROKER_*`, asks
SimpleBroker to normalize that complete mapping, and passes the resulting
self-contained configuration through every lower-layer broker call.

The few defaults that encode Taut product policy stay together at the top of
`taut/_constants.py`. The remaining named defaults are deliberately mundane:
they mirror SimpleBroker defaults only so every broker field has an explicit
Taut-side value and ambient `BROKER_*` cannot fill a hole. Their presence does
not make cache sizes, retry timing, vacuum cadence, or backend connection-part
defaults part of Taut's product theory.

## 2. Source Documents

- `docs/program-theory.md` [THEORY-1] through [THEORY-5]
- `docs/specs/02-taut-core.md` [TAUT-3.2], [TAUT-8.3], [TAUT-8.6], [TAUT-12.1]
- `docs/implementation/04-taut-architecture.md`
- SimpleBroker `docs/specs/16-python-library-api.md` [SB-API-2], [SB-API-9]
- SimpleBroker `simplebroker/_constants.py`, `simplebroker/project.py`,
  `simplebroker/_project_config.py`, `simplebroker/sbqueue.py`, and
  `simplebroker/db.py`
- Weft `weft/_constants.py::SIMPLEBROKER_ENV_MAPPING`,
  `_translate_weft_config_vars`, `apply_weft_simplebroker_defaults`, and
  `_resolve_weft_broker_config` as the mapping reference, not as proof of full
  isolation
- `docs/agent-context/runbooks/writing-plans.md`, `hardening-plans.md`,
  `testing-patterns.md`, and `maintaining-traceability.md`

## 3. Current State and Key Seams

- `taut/_constants.py::load_config()` currently supplies only five broker
  overrides. Valid ambient `BROKER_*` fills every omitted field; invalid
  ambient broker input fails before an override is applied. Its skew-specific
  `InvalidConfigError` translation is a one-key special case.
- `simplebroker.resolve_config(mapping)` currently begins with a fresh strict
  ambient environment read, even when `mapping` contains every canonical
  broker field. Lower layers call the resolver again when a config mapping is
  handed to `Queue`, `open_broker`, or project-resolution helpers. Taut cannot
  close that boundary by constructing a complete plain dictionary alone.
- Weft has the right declarative rename shape, but its input mapping is partial.
  A missing `WEFT_*` value can therefore still inherit ambient `BROKER_*` under
  the current resolver contract. Do not copy that gap.
- The public SimpleBroker config currently contains 32 canonical `BROKER_*`
  fields. All have defaults. Taut needs one Taut-spelled input and one named raw
  default for each field. SimpleBroker remains the only parser and validator.
- `TAUT_DB` remains the Taut path selector. When present it overwrites the
  mechanically compiled `TAUT_DEFAULT_DB_LOCATION` and
  `TAUT_DEFAULT_DB_NAME` pair: an absolute path is split into directory and
  basename; a relative path clears the location and remains relative to the
  selected directory. This preserves `TAUT_DB` parity with `--db` and prevents
  a lower-level location value from rebasing it.
- Project TOML is a later target-resolution input. By default a discovered
  `.taut.toml` owns its backend and target. This change deliberately makes the
  mechanically corresponding `TAUT_PROJECT_CONFIG_PATH`,
  `TAUT_PROJECT_CONFIG_NAME`, and `TAUT_BACKEND*` settings public Taut inputs,
  so [TAUT-3.2]'s earlier fixed-filename and TOML-only backend-selection text
  must change in the same spec-promotion slice rather than survive as a
  contradiction.
- Internal callers currently pass broker-spelled overrides to the private
  `load_config()` helper, including `taut_mcp._workspace_reactor` and tests.
  They must move to Taut spellings so no internal bypass becomes an accidental
  second configuration surface.
- `taut/client/_base.py`, `taut/client/_watching.py`, and `taut/watcher.py`
  currently turn supplied configuration into an ordinary `dict`. That is a
  hidden marker-loss boundary under the revised design. Each must freeze or
  recreate a `ResolvedConfig` through the public ambient-free helper before it
  passes configuration to Queue, watcher, broker, project, or persistence
  layers.

### Comprehension gate before edits

The implementer records these answers in this plan's `## 15. Execution Log`.
A wrong answer blocks implementation until the cited owner text is reread.

1. Why is a complete Taut mapping insufficient against SimpleBroker 7.3.1?
   Expected: `resolve_config(mapping)` and downstream config consumers first
   parse ambient `BROKER_*`; an invalid ambient value can still fail, and a
   valid value fills any omitted field.
2. Which defaults encode Taut policy?
   Expected: storage location/name and `TAUT_DB` path semantics, project search
   and `.taut.toml` isolation, the default SQLite backend, and Taut's load-skew
   policy. The other named values exist to make the mapping complete and
   isolated, not to restate Taut product behavior.
3. Who parses values?
   Expected: SimpleBroker. Taut selects Taut-spelled raw values, renames keys,
   and translates typed diagnostics back to the public Taut spelling; it does
   not copy SimpleBroker normalizers.

## 4. Invariants and Constraints

1. For any process environment, changing, adding, or invalidating any
   canonical `BROKER_*` variable produces no change and no failure in
   `taut._constants.load_config()` or a real Taut client/CLI operation.
2. Changing a `TAUT_*` variable cannot change `simplebroker.resolve_config()`
   or a standalone SimpleBroker queue opened without Taut.
3. Every canonical SimpleBroker config field has exactly one Taut-spelled key,
   one named Taut raw default, and one mechanical rename. The mapping is
   bijective; no duplicate targets, missing targets, or unconsumed defaults.
4. The Taut-important defaults are visually and semantically grouped first.
   A nearby code comment and [TAUT-3.2] both state that the remaining defaults
   are isolation scaffolding, not Taut product policy.
5. SimpleBroker owns coercion, range checks, fallback normalization, path
   validation, and sensitive-value redaction. Taut imports no private
   SimpleBroker module and duplicates no parser.
6. When SimpleBroker rejects a public `TAUT_*` broker setting with
   `InvalidConfigError`, Taut's configuration boundary names the Taut key and
   preserves the upstream safe value display and expected-form metadata.
   SimpleBroker's documented normalizations and fallbacks remain unchanged;
   Taut does not invent stricter grammar. Password/target values remain
   redacted under SimpleBroker's existing rules.
7. `TAUT_DB` keeps [TAUT-3.2]'s explicit-selector precedence and cannot be
   rebased by `TAUT_DEFAULT_DB_LOCATION` or ambient
   `BROKER_DEFAULT_DB_LOCATION`. `--db` and `db_path=` remain path-only and
   higher-level selectors; they are not added to the mechanical map.
8. The default project file remains `.taut.toml`; when the public Taut project
   path/name settings select another file, only that Taut-selected file
   participates. A discovered project file remains authoritative for its
   storage target and backend. Direct Taut backend settings are the explicit
   no-project-file selection door. Reaction ownership follows the selected
   storage project file. Terminal-text ownership does not change: [TAUT-6.4]
   retains its separate current-directory `.taut.toml` policy.
9. Package import and lazy root help/version do not import or resolve
   SimpleBroker configuration.
10. `broker_target`/`broker_config` handoff stays a frozen complete
    SimpleBroker mapping; later caller mutation and ambient environment changes
    cannot alter the attachment.
11. No temporary `os.environ` mutation, private `_CONFIG_FIELDS` import,
    reflection over underscore modules, copied normalizer, compatibility
    fallback, or second resolver path is allowed.
12. Existing broker behavior under Taut's effective defaults remains the same
    except for the intentional removal of ambient `BROKER_*` influence.

Configuration errors are fatal. There is no best-effort fallback. Documentation
or diagnostic reverse-translation failure is also a programming defect, not a
reason to expose a misleading broker-spelled public key.

## 5. Baselines and Cross-Plan Ownership

- Taut repository base: `e80fe0fc9c0b73353b93754c79e93c495ab2667b`.
- [TAUT-3.2] authoring baseline: that base plus the worktree file
  `docs/specs/02-taut-core.md` with SHA-256
  `e6ae9f56452b21a2c2b5958a5a776122a18d8830b536c05eb8a9ac7ccc6648f4`.
  This plan revises the already-promoted skew paragraph rather than treating
  the base copy as current.
- SimpleBroker source baseline:
  `50cc8268d3718edac36bdc5cfe76cb7dd61deaef` (7.3.1).
- Weft comparison baseline:
  `410aaeacf77dc550fbb6c0dc65658361475a787e`.
- Plan type: implementation with spec revision. Promotion strategy A applies
  [TAUT-3.2] text before Taut runtime code. Record the promotion baseline as
  the Taut base plus exact worktree spec diff after promotion.
- This plan is the sole owner of general Taut/SimpleBroker configuration
  isolation. Other work may consume the ambient-free resolved skew value, but
  it does not share ownership of the translation contract.

## 6. Proposed Spec Delta

Promotion strategy A: replace [TAUT-3.2]'s numbered resolution step 3, current
resolution/configuration paragraphs, translation table, and following
ambient/config paragraphs before runtime implementation. Do not leave the
earlier `.taut.toml`-only and backend-selection claims intact. Do not add
implementation-link claims until the reciprocal code and architecture-note
slice.

### [TAUT-3.2] — replace numbered resolution step 3

> 3. Otherwise Taut asks SimpleBroker to resolve from the current directory
>    using the Taut-resolved project config path/name and default SQLite
>    database name, and uses the resolved target. Relative project settings use
>    upward discovery; an absolute project-config path selects its one configured
>    location. The defaults are `.taut.toml` and `.taut.db`.

### [TAUT-3.2] — replace the fixed project-file and backend-selection paragraphs

> `.taut.toml` is Taut's default project configuration file; selecting Postgres
> normally uses it. The translated `TAUT_PROJECT_CONFIG_PATH` and
> `TAUT_PROJECT_CONFIG_NAME` settings may explicitly select a different Taut
> project configuration location/name. Taut searches only that configured
> project file and the configured default SQLite database name. It never falls
> back to ambient SimpleBroker project settings or merges multiple project
> files. A user may deliberately set the Taut project filename to a name also
> used by another application; after that explicit Taut setting, the file is a
> Taut input rather than an ambient SimpleBroker fallback.
>
> A discovered Taut project file is authoritative for its `backend`, `target`,
> and `backend_options`. The translated `TAUT_BACKEND` and
> `TAUT_BACKEND_*` settings are the explicit no-project-file backend-selection
> door. The default remains SQLite. An explicit path selector (`--db`,
> `db_path=`, or `TAUT_DB`) remains path-only, takes precedence over project and
> backend settings, and requires an existing SQLite file except for `taut init`.
> The optional Taut-owned `[reactions]` table is read only from the selected
> storage project file under its existing contract. `[terminal_text]` remains
> the separate current-directory `.taut.toml` presentation policy defined by
> [TAUT-6.4]; storage selectors do not relocate it.

### [TAUT-3.2] — replace the configuration translation contract

> Taut and standalone SimpleBroker have symmetric configuration namespaces.
> Taut reads `TAUT_*`; SimpleBroker reads `BROKER_*`. Ambient `BROKER_*` values,
> whether valid or invalid, do not affect Taut. Ambient `TAUT_*` values do not
> affect standalone SimpleBroker. Taut never obtains isolation by temporarily
> editing the process environment.
>
> `load_config()` compiles one complete Taut-owned input mapping, mechanically
> renames every supported `TAUT_NAME` to `BROKER_NAME`, and passes the complete
> mapping through SimpleBroker's public `resolve_isolated_config()` helper.
> That helper returns a nominal public `ResolvedConfig` mapping. Broker lower
> layers recognize and revalidate that type without consulting ambient
> `BROKER_*`; converting it to an ordinary dictionary discards the isolation
> guarantee and is not permitted on the Taut-to-broker handoff. SimpleBroker
> owns value coercion, validation, safe rejected-value display, and the
> resulting typed broker mapping. Taut owns only input selection, key
> translation, Taut-specific defaults, and translation of a typed invalid-key
> diagnostic back to its public Taut spelling.
>
> The named defaults have two different roles. These Taut-important values are
> grouped first in code because they encode Taut behavior: default storage is
> `.taut.db` in the selected directory; project search is enabled; project
> configuration is isolated to `.taut.toml`; the default backend is SQLite;
> and maximum load watermark future skew defaults to 300 seconds. `TAUT_DB`
> remains the higher-precedence Taut path selector and replaces the compiled
> default location/name pair.
>
> The Taut-policy defaults are these raw pre-normalization values:
>
> | Taut key | Raw default | Why Taut owns it |
> |---|---:|---|
> | `TAUT_DEFAULT_DB_LOCATION` | `""` | selected directory |
> | `TAUT_DEFAULT_DB_NAME` | `.taut.db` | Taut storage filename |
> | `TAUT_PROJECT_CONFIG_PATH` | `""` | project-root search |
> | `TAUT_PROJECT_CONFIG_NAME` | `.taut.toml` | isolated default project filename |
> | `TAUT_PROJECT_SCOPE` | `1` | upward project discovery |
> | `TAUT_BACKEND` | `sqlite` | zero-config backend |
> | `TAUT_LOAD_MAX_FUTURE_SKEW_SECONDS` | `300` | Taut load eligibility |
>
> Every other named default exists to make the broker mapping complete so an
> ambient `BROKER_*` value can never fill a missing field. Almost all of these
> values have no independent Taut meaning: they mirror the supported
> SimpleBroker default for cache, durability, batching, vacuum, polling,
> logging, and backend connection-part settings. Naming them in Taut is an
> isolation mechanism, not a claim that they are Taut product policy.
>
> The isolation-only named defaults are these raw pre-normalization values:
>
> | Taut key | Raw default | Taut key | Raw default |
> |---|---:|---|---:|
> | `TAUT_BUSY_TIMEOUT` | `5000` | `TAUT_CACHE_MB` | `10` |
> | `TAUT_SYNC_MODE` | `FULL` | `TAUT_WAL_AUTOCHECKPOINT` | `1000` |
> | `TAUT_MAX_MESSAGE_SIZE` | `10485760` | `TAUT_READ_COMMIT_INTERVAL` | `1` |
> | `TAUT_GENERATOR_BATCH_SIZE` | `100` | `TAUT_AUTO_VACUUM` | `1` |
> | `TAUT_AUTO_VACUUM_INTERVAL` | `100` | `TAUT_VACUUM_THRESHOLD` | `10` |
> | `TAUT_VACUUM_BATCH_SIZE` | `1000` | `TAUT_SKIP_IDLE_CHECK` | `0` |
> | `TAUT_JITTER_FACTOR` | `0.15` | `TAUT_INITIAL_CHECKS` | `100` |
> | `TAUT_MAX_INTERVAL` | `0.1` | `TAUT_BURST_SLEEP` | `0.00001` |
> | `TAUT_DEBUG` | `""` | `TAUT_LOGGING_ENABLED` | `0` |
> | `TAUT_BACKEND_HOST` | `localhost` | `TAUT_BACKEND_PORT` | `5432` |
> | `TAUT_BACKEND_USER` | `postgres` | `TAUT_BACKEND_PASSWORD` | `""` |
> | `TAUT_BACKEND_DATABASE` | `simplebroker` | `TAUT_BACKEND_SCHEMA` | `simplebroker_pg_v1` |
> | `TAUT_BACKEND_TARGET` | `""` |  |  |
>
> These two tables are the closed 32-field translation inventory. The values
> are raw strings so the public SimpleBroker field schema remains the sole
> normalizer; the resolved values may differ, such as vacuum threshold `10`
> becoming ratio `0.1`.
>
> The mapping is exhaustive and bijective over SimpleBroker's public resolved
> config keys. Except for the separate `TAUT_DB` path selector, each broker
> setting uses mechanical prefix substitution: `TAUT_<suffix>` becomes
> `BROKER_<suffix>`. Explicit private `load_config()` overrides use Taut
> spellings, then ambient `TAUT_*`, then the named Taut default. Unknown
> override keys fail rather than pass through. A dependency upgrade that adds,
> removes, or renames a canonical broker key fails the mapping-parity gate
> until Taut assigns the corresponding named default and verifies its role.
>
> When SimpleBroker rejects translated Taut input with
> `simplebroker.ext.InvalidConfigError`, Taut converts it into a safe
> `ValueError` that names the corresponding `TAUT_*` key and preserves the
> upstream expected-form and redacted value display. SimpleBroker's documented
> total and fallback normalizations remain authoritative. Ambient `BROKER_*`
> input is neither parsed nor diagnosed on a Taut path.
>
> The Taut input precedence within `load_config()` is: explicit private
> Taut-spelled override, then `TAUT_DB` for the default location/name pair,
> then the corresponding ambient `TAUT_*` value, then the named Taut default.
> An explicit location/name override therefore suppresses ambient `TAUT_DB`;
> this is required by multi-workspace embedders resolving an explicit project
> directory. An absolute `TAUT_DB` splits into location and basename. A relative
> `TAUT_DB` clears the location and remains relative. Unknown explicit override
> keys fail rather than pass through.
>
> Unknown selected-project TOML keys retain SimpleBroker's forward-compatible
> ignore behavior. Taut does not merge settings from any second project file.
>
> Verification enumerates every mapped key and fires both directions of the
> isolation contract: each ordinary `TAUT_*` input changes only its translated
> field in Taut's resolved mapping; selector precedence is fired separately;
> every valid, invalid, and sensitive ambient `BROKER_*` field leaves Taut
> unchanged; and representative `TAUT_*` values leave standalone SimpleBroker
> unchanged. Diagnostic firing cases cover each field whose SimpleBroker
> grammar can reject a value; fields with total or fallback normalization are
> checked against that behavior rather than assigned an invented invalid form.
> Real target resolution and queue construction prove that isolation survives
> lower-layer re-resolution rather than existing only in the first returned
> mapping.

### [TAUT-3.2] — replace the public environment-knob sentence

> `TAUT_AS` and `TAUT_TOKEN` remain identity inputs outside broker translation.
> `TAUT_DB` remains the explicit database selector. The broker-operation
> settings use the exhaustive Taut-prefixed translation contract above. Taut
> does not recognize `BROKER_*` as a fallback spelling.

## 7. Upstream Prerequisite and Rollout

SimpleBroker 7.3.1 cannot carry a self-contained complete mapping through its
lower layers because `resolve_config(mapping)` always starts from ambient
environment and returns an ordinary dictionary. Implement and review this
additive upstream surface:

- `simplebroker.resolve_isolated_config(overrides: Mapping[str, Any]) ->
  ResolvedConfig` starts from canonical SimpleBroker defaults, never reads
  ambient `BROKER_*`, applies and validates the supplied mapping with the same
  field schema, rejects every unknown input key, and returns exactly the
  canonical complete nominal mapping. This strict unknown-key rule is specific
  to the new isolated helper; ordinary `resolve_config()` retains its existing
  pass-through compatibility.
- `simplebroker.ResolvedConfig` is the public marker carried through Queue,
  watcher, broker, runner, project-resolution, and dump/load config parameters.
  Each lower layer recognizes it and revalidates/copies it without reading the
  environment. Taut must preserve the marker when it freezes configuration.
- Ordinary mappings and `resolve_config()` retain 7.3.1's environment-base
  behavior for compatibility. No implicit inference from key-set completeness
  is permitted.
- `ResolvedConfig` must not allow unchecked mutation to launder an invalid
  value. The upstream plan chooses and proves either immutability or
  ambient-free revalidation on every lower-layer receipt; Taut treats the
  resulting public mapping as read-only in either case.
- The resolved result itself is the public parity seam. Taut compares its
  translated input key set with the returned canonical key set. If a future
  dependency adds, removes, or renames a field, Taut fails closed with a fixed
  compatibility error before constructing a target or handle. It never falls
  back to a partial/environment-based path.
- Add real Queue, project-resolution, `open_broker`, watcher, and dump/load
  tests with invalid ambient broker values plus a `ResolvedConfig`. Do not prove
  only the first resolver call.

This requires an upstream SimpleBroker spec, implementation, tests, changelog,
independent review, and owner-controlled release. The Taut implementation must
not raise its dependency floor or claim completion until that public behavior
exists in a published SimpleBroker version. Record that exact version during
execution and reconcile the root manifest, retained locks, README restatements,
spec floor, architecture note, and dependency-floor gates through the existing
release-metadata machinery. Publication itself is not authorized by this plan.

Rollout order is strict: upstream contract and tests; upstream release by the
owner; Taut dependency-floor/spec promotion; Taut red/green implementation;
cross-backend and installed-wheel verification. Rollback before a Taut release
reverts the Taut mapping, spec, dependency floor, and docs together. After a
Taut release, retaining the higher SimpleBroker floor is safer than restoring
ambient leakage. There is no storage migration, one-way data change, or mixed
database format.

## 8. Dependency-Ordered Tasks

1. **Review the upstream contract and establish ownership.**
   - Files: this plan and the upstream SimpleBroker plan/spec selected under
     that repository's process.
   - Stop if the upstream owner rejects nominal resolved-config isolation or requires
     a different public representation; revise this plan and proposed delta
     before any Taut code.
   - Done: one configuration owner, reviewed upstream API shape, no contradictory
     active instruction.

2. **Implement and release the SimpleBroker prerequisite through its own
   repository process.**
   - Files there: governing [SB-API-2]/[SB-API-9] spec, `_constants.py`, focused
     config/lifecycle tests, lower-layer real integration tests, implementation
     note, changelog, manifest/release surfaces selected by its plan.
   - RED first: the proposed isolated resolver/marker does not exist under
     7.3.1, and an ordinary complete mapping plus invalid ambient input fails
     at resolver, Queue, project-resolution, and broker-open seams.
   - GREEN: `ResolvedConfig` mappings are self-contained across every named
     lower layer; ordinary mappings preserve compatibility.
   - Do not mock `os.environ`, resolver calls, Queue, project resolution, or
     broker open beyond pytest's real environment isolation and temporary
     filesystem fixtures.
   - Stop before publication. The human owner controls version selection and
     release authorization.
   - Done: independently reviewed upstream change and, after separate owner
     authorization, a published version with installed-artifact proof.

3. **Promote the Taut spec delta and record its baseline.**
   - Files: `docs/specs/02-taut-core.md`, its Related Plans section, and this
     plan.
   - Apply strategy A text before Taut code. Run documentation and
     traceability gates. Record the base plus exact worktree diff.
   - Stop if the final upstream contract differs from the proposed
     complete-mapping rule; revise and re-review the delta first.
   - Done: one canonical active TAUT-3.2 contract and no stale ambient-broker
     exception.

4. **RED: enumerate translation and isolation failures.**
   - Files: `tests/test_constants.py`, `tests/test_project_config.py`,
     `tests/test_client.py`, `tests/test_shared_contract.py`, and the smallest
     installed/subprocess test seam already used for config lifecycle.
   - Add a table-driven firing case for all 32 canonical fields: default exists,
     Taut spelling maps once, and a representative value changes the expected
     broker field. Add reverse-diagnostic cases for every field with rejecting
     grammar. Preserve upstream fallback/total normalization for the rest.
     Sensitive redaction is tested through upstream-supported safe-display
     cases, not by inventing invalid password or target grammar.
   - Add exhaustive ambient-broker invariance with valid and invalid values,
     plus standalone-SimpleBroker invariance under representative Taut values.
   - Add real lower-layer cases for target discovery, Queue/client creation,
     handed-off config, relative and absolute `TAUT_DB`, explicit overrides
     suppressing ambient `TAUT_DB`, alternate Taut project filename/path, and
     direct/project-file Postgres selection where the existing shared harness
     supports it.
   - Fix `tests.conftest.clean_env` so it removes the full canonical Taut and
     broker config namespaces used by a test, while preserving test-harness
     selectors such as `BROKER_TEST_BACKEND` and `SIMPLEBROKER_PG_TEST_DSN`.
   - Done: tests fail for the observed ambient cache/location leak and invalid
     ambient lifecycle before production edits.

5. **GREEN: build the complete mechanical Taut mapping.**
   - File: `taut/_constants.py`.
   - Keep a compact Taut-policy block first. Directly below it, add the required
     comment: the rest are named SimpleBroker-mirroring defaults present for
     namespace isolation and are mostly unrelated to Taut product policy.
   - Define one ordered Taut-default mapping and one mechanical/reviewable key
     translator. Reject unknown explicit override keys. Compile ambient
     `TAUT_*` over named defaults, apply `TAUT_DB` to the location/name pair,
     then apply explicit Taut overrides last. Call
     `resolve_isolated_config()`, compare translated and returned canonical key
     sets, and retain the `ResolvedConfig` marker.
   - Replace skew-only error handling with generic reverse-key diagnostic
     translation. Preserve safe upstream value display and expected metadata.
   - Do not add one constant per field outside the table, a copied parser, an
     environment-mutation context manager, or a second broker config builder.
   - Done: task-4 tests pass and the 32-key mapping/default/returned canonical
     key sets are equal with no duplicates; simulated upstream addition,
     removal, and rename cases all fail closed before target resolution.

6. **Update every Taut consumer and durable rationale.**
   - Files: `taut/client/_base.py`, `taut/client/_watching.py`,
     `taut/watcher.py`, `taut_mcp._workspace_reactor`, affected core/Summon
     fixtures and tests, `docs/implementation/04-taut-architecture.md`,
     dependency metadata and locks, README/config catalog if it enumerates
     public settings.
   - Convert private `load_config()` overrides and Taut-owned test environment
     inputs from broker spellings to Taut spellings. Do not change the
     `broker_config` handoff payload's broker spellings; do preserve or recreate
     its public `ResolvedConfig` marker through an ambient-free call. MCP's
     explicit-directory path overrides both default location and name so
     ambient `TAUT_DB` cannot redirect it.
   - The architecture note must preserve the same policy-vs-isolation-default
     distinction and explain why both a complete mapping and its nominal
     `ResolvedConfig` marker are required across repeated lower-layer
     resolution.
   - Reconcile the published SimpleBroker floor only after task 2's release.
   - Done: no Taut-owned configuration input uses `BROKER_*`; broker-spelled
     keys remain only in the compiled lower-layer mapping, assertions about that
     mapping, backend test-harness controls, and explicit standalone-broker
     isolation probes.

7. **Cross-backend, installed-artifact, and completed-work review.**
   - Run focused SQLite tests first, then shared SQLite/PostgreSQL config and
     target-resolution cases, lazy import/help tests, installed-wheel tests, and
     the full repository gates.
   - Review the final diff against both promoted specs and the exact upstream
     released artifact. Reproduce every finding before changing code.
   - Close traceability, deviation logs, plan index status, and any durable
     lesson exposed during implementation. Do not claim completion or commit on
     the user's behalf.

## 9. Testing and Verification

Anti-mocking rule: SimpleBroker normalization, process environment, target
resolution, Queue/client construction, SQLite filesystem behavior, and the
shared PostgreSQL path stay real. Parameter tables may synthesize raw field
values; they may not replace the resolver or assert only call arguments.

Per-slice commands are selected from:

```bash
uv run --extra dev pytest tests/test_constants.py tests/test_project_config.py tests/test_client.py tests/test_shared_contract.py -q
uv run --extra dev pytest tests/test_lazy_imports.py tests/test_architecture_boundaries.py -q
uv run --extra dev pytest extensions/taut_pg/tests -q
uv run --extra dev pytest
uv run --extra dev ruff check taut tests extensions
uv run --extra dev ruff format --check taut tests extensions
uv run --extra dev mypy taut tests extensions/taut_pg/taut_pg extensions/taut_pg/tests --config-file pyproject.toml
uv run pytest tests/test_docs_references.py -q
bin/check-plan-status-index
uv run bin/check-doc-paths
git diff --check
```

The upstream plan must add its own focused and full commands under
`../simplebroker`; Taut does not substitute source-path imports for a published
installed-artifact gate.

Post-release success signal: in a clean environment containing the released
Taut and required SimpleBroker versions, an invalid
`BROKER_BUSY_TIMEOUT` plus valid `TAUT_BUSY_TIMEOUT` still permits Taut init and
queue use with the Taut value, while standalone SimpleBroker fails on its own
invalid broker value. Conversely, invalid `TAUT_BUSY_TIMEOUT` fails Taut with
the Taut key and leaves standalone SimpleBroker behavior unchanged.

## 10. Independent Review Loop

Before spec promotion, use a different-family read-only reviewer. The reviewer
reads this plan including `## Proposed Spec Delta`, current [TAUT-3.2], the
Taut `_constants.py` and tests, SimpleBroker [SB-API-2]/[SB-API-9] and
resolver/lower-layer code, and Weft's mapping.

Review stance: verify that the nominal `ResolvedConfig` truly survives every
lower-layer re-resolution; look for a hidden ambient read, duplicated parser, incomplete
key inventory, public-surface expansion without a firing test, unsafe
diagnostic echo, `TAUT_DB` precedence regression, or unnecessary abstraction.
Answer whether a zero-context engineer could implement the plan correctly.

The author records each finding below and either changes the plan, rejects it
with file/line evidence, or marks it out of scope with a reason. Any uncertainty
about upstream feasibility, key completeness, or target precedence is BLOCKED.
Repeat review after each coherent upstream/spec/Taut slice and once on the
completed work.

### Review log

| Round | Finding | Evidence | Disposition | Result |
|---|---|---|---|---|
| 1 attempt | Different-family Claude review produced no output before the bounded timeout. | Read-only `claude` invocation from `/Users/van/Developer` with `Read,Grep,Glob`; 540-second timeout; exit 124; repository unchanged. | No verdict inferred. Fall back to a separate same-family read-only reviewer role per the review runbook; retain this limitation in the plan. | Failed attempt |
| 1 F1 (P1) | Implicit completeness fails open after an upstream field addition. | SimpleBroker 7.3.1 resolves ordinary mappings from ambient state; a 32-key Taut dictionary becomes partial against a future 33-key schema. | Accepted: replace implicit completeness with public `resolve_isolated_config()` plus nominal `ResolvedConfig`; compare returned keys and fail closed before use. | Fixed for round 2 |
| 1 F2 (P1) | A full public Taut mapping contradicts retained fixed `.taut.toml` and TOML-only backend rules. | Current [TAUT-3.2] lines 121–145 and 184–195 versus mapped project/backend keys. | Accepted: the proposed delta now replaces those earlier paragraphs and explicitly makes Taut project/backend keys the deliberate configuration doors. | Fixed for round 2 |
| 1 F3 (P1) | Applying `TAUT_DB` after explicit overrides breaks MCP explicit-directory resolution. | `taut_mcp._workspace_reactor::_resolve_workspace` intentionally overrides the default database name. | Accepted: explicit Taut overrides apply last; MCP overrides both location and name; add a firing ambient-TAUT_DB attachment test. | Fixed for round 2 |
| 1 F4 (P2) | Inventory says 31 but pinned SimpleBroker has 32 fields; no public private-schema parity seam exists. | Pinned `_CONFIG_FIELDS` and public resolved output. | Accepted: count corrected to 32; `resolve_isolated_config()` returned keys are the public runtime parity seam. | Fixed for round 2 |
| 1 F5 (P2) | Per-field invalid diagnostics and “never falls back” contradict SimpleBroker total/fallback normalization. | `SYNC_MODE`, project scope, debug, default DB location, and unrestricted strings. | Accepted: preserve upstream normalization; diagnostic matrix covers rejecting grammars only; sensitive display uses supported rejection evidence. | Fixed for round 2 |
| 1 F6 (P2) | Worktree spec hash was stale. | Fresh SHA-256 inspection. | Accepted: baseline refreshed to `e6ae9f...`; recheck immediately before promotion because the shared spec is active. | Fixed for round 2 |
| 2 F7 | Removed/renamed upstream fields can evade parity if isolated resolution passes unknown keys through. | Current `resolve_config()` preserves unknown mapping keys; input and returned sets can remain equal after an upstream removal. | Accepted: isolated helper rejects unknown keys and returns canonical keys only; addition/removal/rename simulations are required. | Fixed for round 3 |
| 2 F8 | The proposed delta omitted numbered resolution step 3's literal `.taut.toml`/`.taut.db` wording. | Current [TAUT-3.2] step 3 would survive beside the generalized project/default names. | Accepted: exact replacement step now names Taut-resolved path/name/default DB and states only their defaults literally. | Fixed for round 3 |
| 3 F9 | Revised step 3 falsely said every configured project path searches upward. | SimpleBroker absolute project-config paths resolve one configured location. | Accepted: step 3 now delegates general resolution and distinguishes relative upward discovery from an absolute configured location. | Fixed for round 4 |
| 4 | Scoped verification of F9 found no new defect. | Revised step 3 matches relative/empty upward discovery and absolute single-location resolution while leaving legacy database discovery and no-target handling to the surrounding order. | No further change. Same-family fallback limitation remains disclosed after the different-family timeout. | PASS |

## 11. Out of Scope

- changing queue, retry, vacuum, polling, cache, logging, or backend semantics
  beyond selecting their existing SimpleBroker values through `TAUT_*`
- copying or redesigning SimpleBroker parsers and validators
- reading `.broker.toml` or merging multiple project config files
- changing identity, reaction, terminal-text, persistence format, or dump/load
  chronology
- environment mutation, private SimpleBroker imports, or a compatibility
  fallback for SimpleBroker versions below the new required floor
- releasing or publishing SimpleBroker or Taut without separate owner
  authorization
- changing Weft; its partial-mapping isolation gap is evidence and a possible
  separate follow-up, not part of this implementation

## 12. Deviation Log

| Spec ref | Planned behavior | Actual behavior | Rationale | Spec proposal |
|---|---|---|---|---|

## 13. Fresh-Eyes and Hardening Gate

Before calling the plan review-ready, recheck: all 32 current broker fields are
covered; policy defaults precede isolation defaults; both the spec and code
comment explain why the mundane defaults exist; `ResolvedConfig` skips ambient
at every lower-layer resolution; ordinary SimpleBroker mappings preserve their
published compatibility contract; key-set drift fails closed; Taut errors use
Taut keys and preserve redaction where upstream rejects; relative `TAUT_DB`
clears location; explicit overrides outrank it; configured project/backend
doors are stated without contradicting default `.taut.toml` behavior; root lazy
imports survive; upstream publication is a human gate; rollback has no storage
consequence; and no active plan still asserts that ambient `BROKER_*` is a Taut
dependency input.

One-way doors: none in persisted data. Compatibility risk is the new public
Taut environment surface and the higher SimpleBroker floor. Stop and re-plan if
the implementation needs environment mutation, a private upstream field list,
parser duplication, a second config builder, loss of the nominal resolved
marker, or a change to ordinary-mapping SimpleBroker semantics.

## 14. Revision Log

| Date | Revision | Evidence / decision |
|---|---|---|
| 2026-08-13 | Initial plan: complete Taut-prefixed mapping, upstream complete-config isolation prerequisite, exhaustive bidirectional firing tests, and explicit policy-default versus isolation-default grouping. | Owner direction after comparing Taut and Weft embedding; direct probes showed valid ambient cache/location leakage and invalid ambient validation before overrides. |
| 2026-08-13 | Replaced implicit complete-dictionary inference with nominal public `ResolvedConfig`; corrected the 32-field inventory; made project/backend expansion and selector precedence explicit; preserved upstream fallback normalization; refreshed the worktree spec baseline. | Same-family fallback review F1–F6 after the bounded different-family attempt timed out. |

## 15. Execution Log

### 2026-08-13: comprehension and spec promotion

1. A complete ordinary dictionary is insufficient against SimpleBroker 7.3.1
   because its resolver and repeated lower-layer consumers begin from ambient
   `BROKER_*`; invalid ambient input can fail before overrides and omitted
   fields inherit ambient values.
2. Taut policy is limited to storage location/name and `TAUT_DB`, project
   discovery and default `.taut.toml`, default SQLite selection, and load-skew
   policy. The other named defaults close the mapping for isolation.
3. SimpleBroker parses and validates values. Taut selects raw `TAUT_*` input,
   mechanically renames keys, enforces parity, and reverses typed diagnostics.

Promotion strategy A was applied before runtime edits. Baseline is Taut base
`e80fe0fc9c0b73353b93754c79e93c495ab2667b` plus the exact promoted
`docs/specs/02-taut-core.md` worktree diff with SHA-256
`95cb229830fc5f28ae2be8c47a4821509e2c7d1de23ce62580d3e0f3ef0a518f`.

### 2026-08-13: red/green slices

- RED: the 32-field table, marker type, ambient-broker invariance, selector
  precedence, unknown-key rejection, and lifecycle probes failed against the
  old partial `load_config()` implementation.
- GREEN: `tests/test_constants.py` passed 70 cases against the sibling
  SimpleBroker source; the focused constants/project/client/shared suite passed
  385 cases. Real alternate-project, direct-backend, invalid-ambient client,
  watcher, and MCP attachment paths also passed.
- Taut ownership boundaries now recreate `ResolvedConfig`; source-linked mypy
  passes after the upstream public config parameters were widened to
  `Mapping[str, Any]`.

The owner published SimpleBroker 7.3.2 after its full upstream workflow passed.
The canonical PyPI JSON identifies wheel SHA-256
`a9f59fe8d4e407b9c04ea65e057091114b347564db9657c5f750578f8bcdad0f`,
uploaded 2026-08-14T00:37:38Z. Taut's floor and retained locks move to
`simplebroker>=7.3.2`; installed-wheel verification uses that artifact.

### 2026-08-13: completed-work review and artifact verification

Independent review found one fail-closed defect: upstream removal/rename
rejection was initially translated as ordinary invalid Taut input. Both
`load_config()` and `freeze_broker_config()` now recognize SimpleBroker's typed
unknown-canonical-key diagnostic and raise the fixed compatibility error.
Removal and rename tests exercise that strict rejection path rather than only
mocking a returned key set.

The same review added full invalid ambient numeric/path enumeration, real
relative-upward and absolute-single-location project-path cases, and successful
direct Postgres selection in the shared PG harness. Re-review passed with no
remaining P1/P2 finding.

Published-artifact evidence: a clean isolated install of SimpleBroker 7.3.2
imports both public APIs and returns a 32-key `ResolvedConfig`. The focused
installed Taut suite passed 573 tests; the broader config/client/project/shared/
watcher suite passed 514 tests; MCP attachment, Ruff, format, mypy, metadata,
release-helper, plan-index, doc-path, docs-reference, and diff-hygiene gates
passed. A repository-wide run during development passed 1,981 tests and had one
declared Windows skip; three failures were outside this plan's paths and were
not used as completion evidence.

### 2026-08-13: owner-authorized closeout

The owner authorized a targeted closeout commit after SimpleBroker 7.3.2 was
published. A locked sync selected the published package from Taut's virtual
environment rather than the sibling source tree. The installed distribution
reported version 7.3.2, exported `ResolvedConfig` and
`resolve_isolated_config`, and returned the expected 32-key resolved marker.
The focused installed-artifact compatibility suite, metadata and release-tool
tests, all retained lock checks, and diff hygiene passed before staging. The
exact staged tree then passed the focused core/config/watcher suite, the MCP
ambient-`TAUT_DB` attachment subprocess, root and MCP mypy, scoped Ruff, plan
index and documentation-reference gates, and the dependency-floor claims.
