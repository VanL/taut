# SimpleBroker 8.2 Config Migration Plan

Status: completed. SimpleBroker 8.2.2 and simplebroker-pg 4.2.1 are published;
implementation and independent review passed. Class: 5. This changes Taut's public embedding
config type, its
dependency floor, environment resolution, and cross-package handoff contract.
The code and normative spec must land atomically.

Owner: implementing engineer. The repository owner owns the public decision to
replace copied-mapping handoff with SimpleBroker's nominal `Config`.

## Goal

Adopt SimpleBroker 8.2's declaration-driven `Config` API and remove Taut's
parallel configuration system. Taut should declare only the defaults it changes
and the Taut-only values that belong in storage resolution, then pass the
resolved `Config` directly to SimpleBroker.

The migration must remove the 32-entry mirrored default table, `TAUT_*` to
`BROKER_*` translation, required-key inventory, schema-drift guards,
`ResolvedConfig` reconstruction, and tests that freeze those mechanisms. It
must preserve Taut's storage-selection, identity, project discovery, diagnostic,
and backend behavior.

## Evidence and upstream contract

An isolated install of `simplebroker==8.2.0` reproduces the current wheel
failure: Taut imports the removed package-root `ResolvedConfig`. Versions 8.0
and 8.1 exported that type. Version 8.2 replaces it with:

```python
ConfigField(default, description, validator=None, sensitive=False)
Config(values, *, prefix="BROKER", defaults=DEFAULT_CONFIG)
resolve_config(
    prefix=None,
    *,
    defaults=None,
    toml=None,
    env=None,
    override=None,
    config=None,
) -> Config
```

Resolved keys are uppercase and unprefixed. The prefix applies only while
reading TOML, environment, and overrides. Resolution order is defaults, TOML,
environment, then overrides. Environment input is explicit. Passing an
existing `Config` returns that object unchanged unless an override derives a
new snapshot. SimpleBroker target, queue, watcher, and backend APIs consume the
nominal `Config` directly.

SimpleBroker 8.2.2 and simplebroker-pg 4.2.1 are published as a coordinated
patch release and independently installable. Set the lower bounds to
`simplebroker>=8.2.2` and `simplebroker-pg>=4.2.1`. Do not add an upper bound or
an adapter for the removed 8.1 API.

## Decisions

### One declaration table

Build `TAUT_CONFIG_DEFAULTS` by copying public `DEFAULT_CONFIG` and replacing
only these declarations:

- `DEFAULT_DB_NAME`: `.taut.db`;
- `PROJECT_CONFIG_NAME`: `.taut.toml`;
- `PROJECT_SCOPE`: true;
- `DB`: a Taut-only path selector, default `""`, validated with `str`;
- `AS`: a Taut-only identity selector, default `""`, validated with `str`; and
- `TOKEN`: a sensitive Taut-only identity selector, default `""`, validated
  with `str`.

All broker tuning, backend, logging, and path defaults remain owned by
SimpleBroker. Do not restate them in Taut. If implementation inspection shows a
fourth changed default, add it only with a behavior citation. A whole-map
equality assertion is not such evidence.

Construct `TAUT_CONFIG_DEFAULTS` once at module import and reuse that exact
declaration object for every resolution. SimpleBroker includes declaration
identity in process-session identity; rebuilding equivalent `ConfigField`
records per call would prevent equivalent Taut clients from sharing a
persistent backend session.

The client reads `AS` and `TOKEN` directly from the resolved snapshot when
environment identity inheritance is enabled. Explicit constructor values still
win. Empty `DB`, `AS`, and `TOKEN` values mean unset. For `DB`, this resolves
the current inconsistency where config compilation treated an empty `TAUT_DB`
as present while client target selection treated it as absent. Empty `TAUT_DB`
therefore retains ordinary `.taut.db` and project discovery.

`TAUT_DEBUG_ACTION`, `TAUT_DEBUG_ACTION_ACTIVE`, and other well-formed custom
`TAUT_*` values may remain undeclared. SimpleBroker intentionally retains them
as unvalidated custom Config values. Debug action execution continues to sample
the live environment at each failure because that is its existing lifetime;
its retained Config value is context, not a replacement action source. Do not
add a second filter or reserved-name table. The accepted cost is that a
well-formed typo in an undeclared `TAUT_*` name remains as inert custom context
rather than receiving declared-field typo diagnostics.

### Explicit environment boundary

Call `resolve_config("TAUT", defaults=TAUT_CONFIG_DEFAULTS, env=os.environ,
override=overrides)`. SimpleBroker selects the `TAUT_` namespace, validates
declared fields, and preserves well-formed custom fields. Other prefixes and
bare environment names remain ignored. Let `InvalidConfigError` provide
validation metadata; its key already uses the public `TAUT_*` spelling, so do
not parse or rewrite human-readable text. If a rejected value survives source
precedence, suppress the duplicate application warning and retain the typed
exception as Taut's established one-line CLI diagnostic. Re-emit warnings when
resolution succeeds so overridden invalid values remain visible.

### `TAUT_DB` precedence

Resolve `DB` with the other fields and read it directly at Taut's database
selection boundaries. A nonempty value remains the same path-only selector as
before; an empty value falls through to project and default discovery. Do not
copy it into SimpleBroker's stricter `DEFAULT_DB_LOCATION` or
`DEFAULT_DB_NAME` fields. `db_path=` and CLI `--db` remain direct path-only
selectors and still outrank the resolved config.

### Direct nominal handoff

Change public `broker_config` and config parameters from `Mapping[str, Any]` to
SimpleBroker `Config`, including `TautClient`, `MultiQueueWatcher`, and
`resolve_context_broker_target`. Pass the same object through clients, watchers,
maintenance, persistence, MCP, Summon, and backend construction. Delete
`freeze_broker_config`; do not replace it with a nominal-type wrapper.

This intentionally removes copied-dictionary handoff at each of those public
surfaces. A caller that needs a
derived snapshot uses `resolve_config(config=cfg, override=...)`; a caller that
needs a content copy can call `dict(cfg)` for inspection but cannot pass that
copy back as resolved configuration. The capability loss is limited to an old
representation workaround. Project attachment, ambient isolation, derivation,
and immutable handoff remain available through the upstream public type.

### Concrete upstream behavior changes

SimpleBroker 8.2 reports resolved `VACUUM_THRESHOLD` in percentage units rather
than the old ratio representation. Taut's public environment/TOML input was and
remains a percentage, so existing values keep their meaning. Update tests that
inspect the resolved mapping from `0.25` to `25.0`; do not add conversion or a
user-config migration.

Do not pass `.taut.toml` as generic `resolve_config(toml=...)` input. Taut uses
that file as SimpleBroker's project-target document plus its own reactions and
presentation tables. `resolve_broker_target(..., config=cfg)` discovers the
configured file and `resolve_project_target` applies its backend target while
retaining the supplied Config for supplemental backend values. This remains
separate from generic namespaced setting-TOML resolution.

SimpleBroker 8.2 also validates terminal SQLite filenames more narrowly during
default and project resolution. Before implementation is declared ready, run a
real matrix for explicit paths, `TAUT_DB`, default discovery, and project TOML
on POSIX and the existing Windows contract. If a path accepted by [TAUT-3.2]
now fails, stop and choose one explicit contract change or an upstream fix. Do
not recreate SimpleBroker path resolution inside Taut.

## Atomic implementation slice

Suggested commit: `refactor: adopt SimpleBroker config declarations`.

This is one atomic slice because upgrading the dependency removes imported
symbols used by core and every extension. Intermediate compatibility shims
would exist only to make artificial commits green and would add the exact
dual-stack complexity this migration removes.

Production edits:

- In `taut/_config.py`, replace `_TAUT_BROKER_DEFAULTS`, prefix helpers,
  required-key checks, `freeze_broker_config`, manual environment merging, and
  `resolve_isolated_config` with the small declaration table and one
  `load_config` call to `resolve_config`.
- Migrate config annotations and reads to `Config` and unprefixed keys in
  `taut/client/_base.py`, `taut/client/__init__.py`,
  `taut/client/_watching.py`, `taut/watcher.py`, `taut/_maintenance.py`,
  `taut/persistence/_operations.py`, and `taut/debug.py`.
- Make the same type/key migration in
  `extensions/taut_mcp/taut_mcp/_workspace_reactor.py` and
  `extensions/taut_summon/taut_summon/_control.py`. Update PostgreSQL callers
  only where the nominal config or unprefixed keys require it.
- Raise dependency floors in root
  and extension manifests to 8.2.2 and 4.2.1 and refresh `uv.lock`. Do not
  constrain future compatible releases.

Normative and implementation edits:

- Replace [TAUT-3.2]'s translation, mirrored inventory, reconstruction, and
  copied-mapping handoff text with declaration, explicit-source, unprefixed-key,
  and direct-`Config` rules.
- Supersede only SC-1 in
  `docs/plans/2026-08-25-semantic-compatibility-hardening-plan.md`; SC-2 through
  SC-8 remain active and unchanged.
- Align `README.md`; specs 03 and 04; implementation docs 04, 05, 07, and 10;
  and the MCP, Summon, and persistence package documentation. Refresh the root,
  PostgreSQL, MCP, and TUI lockfiles. Record the new dependency floors and the
  reason for the public handoff change.

## Behavioral proof

Rewrite `tests/test_constants.py` around outcomes rather than implementation
shape:

1. Defaults discover `.taut.db` and `.taut.toml` through real target
   resolution.
2. A small `TAUT_MAX_MESSAGE_SIZE` causes a real oversized write rejection;
   the same ambient `BROKER_MAX_MESSAGE_SIZE` does not change a Taut client.
3. `TAUT_DB`, `db_path=`, and project config retain their documented precedence
   for relative and absolute paths; empty `TAUT_DB` behaves as unset.
4. Declared identity values and an undeclared custom value survive in `Config`
   through a real Queue without closed-set validation or backend exposure;
   explicit identity arguments still win, disabled environment inheritance
   ignores `TAUT_AS` and `TAUT_TOKEN`, and debug action still samples its live
   environment at failure time.
5. A real invalid ordinary setting reports the public Taut key through upstream
   `InvalidConfigError` metadata. Retain Taut's existing token and debug payload
   redaction proofs; do not invent an invalid sensitive-string case.
6. `Config` handoff remains attached to the selected project after cwd and
   environment mutation. Derivation uses upstream `resolve_config` and does not
   mutate the source snapshot.
7. The percentage-unit and SQLite path cases exercise the published 8.2.2
   behavior. SimpleBroker may validate the database name Taut asks it to create,
   but must preserve pre-existing parent-directory spelling, including spaces.
8. Keep one module-level declaration object so upstream can preserve its
   process-session identity contract. That internal sharing guarantee belongs
   to SimpleBroker's tests; Taut must not assert private Queue connection state.

Retain or adapt the real SQLite/PostgreSQL shared contract, MCP workspace
attachment, persistent watcher, dump/load, debug capture, and installed-wheel
tests. The installed core, TUI, and core/Summon wheel tests are the release
proof that dependency resolution and package imports work together.

Delete tests for the 32-field mirror, whole-map equality, future-key
monkeypatches, removed-key monkeypatches, key-renaming simulations,
`ResolvedConfig` reconstruction, and copied-dict mutation. Those tests prove a
retired defensive process and would pressure the new code back toward it.

## Gates

Run:

```bash
.venv/bin/python -m pytest -q -n 0 tests/test_constants.py tests/test_client.py \
  tests/test_project_config.py tests/test_shared_contract.py
.venv/bin/python -m pytest -q -n 0 -m installed_wheel
.venv/bin/python -m pytest -q -n 0 extensions/taut_tui/tests/test_tui_launch.py
TAUT_PG_UV_NO_SYNC=1 .venv/bin/python bin/pytest-pg --fast \
  tests/test_shared_contract.py extensions/taut_pg/tests -n 2 --dist loadgroup
.venv/bin/python -m mypy taut tests extensions/taut_mcp extensions/taut_summon \
  extensions/taut_tui --config-file pyproject.toml
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/python bin/check-doc-paths
.venv/bin/python bin/check-plan-status-index
```

Verification must include ordinary isolated resolution installing
SimpleBroker 8.2.2 with simplebroker-pg 4.2.1 from the published indexes. Then
run the normal root and extension suites. Any temporary test environment must
resolve those patch releases rather than inheriting the checkout's 8.0 lock.

## Review gates

Before implementation, obtain a fresh-eyes review and an external-model review
of this plan. Both reviewers must check correctness, completeness, public
capability loss, and whether any step reintroduces armor for hypothetical
schema drift. They must specifically challenge:

- whether more than the three changed defaults plus `DB`, `AS`, and `TOKEN` are
  declared;
- whether a compatibility wrapper or copied-mapping adapter is justified;
- whether tests assert behavior rather than declaration inventory;
- whether splitting the migration into multiple commits would require a
  temporary dual API;
- whether any environment allowlist or custom-field registry duplicates the
  upstream namespace owner; and
- whether the SQLite filename rule causes a real capability regression.

After implementation, repeat independent review on the complete diff. Treat
suggestions for inventories, unknown-future-key guards, compatibility shims, or
new path resolvers as suspect unless tied to a reproduced failure.

## Rollback and success signals

Rollback is one commit because the migration is atomic. It restores the prior
dependency floor and config implementation together. Do not publish artifacts
from a partially reverted tree.

Success means fresh wheel installs import and run against SimpleBroker 8.2.2
and simplebroker-pg 4.2.1;
SQLite and PostgreSQL target resolution retain documented precedence; ambient
broker variables cannot alter a client; declared and custom Taut values survive
in the one Config; Config handoff stays stable across environment changes; and
Taut owns no mirrored broker-default or resolved-key inventory.

## Plan review record

Fresh-eyes review checked the plan against Taut's public client and watcher
surfaces plus SimpleBroker's current source, guide, and session-identity tests.
It required explicit coverage of every mapping handoff, empty `TAUT_DB`, one
module-level declaration object, exact documentation/lockfile owners, a
deterministic max-message-size behavior proof, and deletion of a synthetic
sensitive-validator test. Those corrections are incorporated.

An external-model review explicitly assessed over-armoring and complexity
against locality. It found the atomic commit justified and no compatibility
shim, allowlist, inventory, or path resolver warranted. Its concrete findings
were incorporated: project TOML remains in target resolution rather than the
generic config-TOML source; DB derivation uses exact namespaced override keys;
vacuum percentages preserve public input meaning; custom Taut fields receive a
real Queue handoff proof; and the cost of silent well-formed custom-name typos
is explicit. It agreed that the SQLite filename matrix is a real implementation
stop gate, not a paper assumption.

The owner clarified that SimpleBroker's custom-field behavior was designed with
Taut in mind. Earlier draft language proposing an environment allowlist and a
custom-field registry was withdrawn. The final plan passes `os.environ` to the
TAUT-prefixed resolver and relies on upstream custom-field retention.
