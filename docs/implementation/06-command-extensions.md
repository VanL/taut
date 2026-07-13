# Command Extensions and Lazy Composition

## Purpose and Scope

This document explains how one top-level `taut` verb becomes a command without
turning the core CLI into a plugin framework for arbitrary subsystem behavior.
It covers the version-1 command interface, static and installed discovery,
dispatch ownership, lazy imports, the temporary Summon compatibility bridge,
and the boundary a future rich TUI should use.

The governing contracts are `docs/specs/02-taut-core.md` [TAUT-8.6] and
[TAUT-12.4], plus `docs/specs/04-summon.md` [SUM-13]. Summon's internal
runtime remains documented in `docs/implementation/05-taut-summon-architecture.md`.

## The Core Shape

Every top-level verb has the same two pieces:

1. A lightweight `CommandSpec` says what root help and selection need to know.
2. A factory creates a fresh command adapter only after that verb is selected.

Core verbs and installed verbs use the same `CommandSpec` and `Command`
interfaces. They differ only in where core finds the manifest. Built-ins come
from the static tuple in `taut/commands/_builtins.py`, because core commands
must work from a source checkout without installed distribution metadata.
Extensions publish manifest objects through Python's `taut.commands`
entry-point group. `taut/commands/_registry.py` normalizes both sources into one
immutable process-local `CommandRegistry`.

The distinction is deliberate. Making built-ins self-discover through package
metadata would add failure modes without adding capability. Giving installed
commands a second protocol would make parser, error, stream, and cleanup policy
drift. One interface with two discovery sources is the smaller design.

"Local" does not mean "found by scanning this checkout." Registration follows
the active Python environment:

| Command location | Registration source | Required condition |
|---|---|---|
| Core-owned built-in in `taut/commands/` | Static `BUILTIN_SPECS` | Present in the core source/package |
| First-party extension in this monorepo | Installed `taut.commands` entry point | Extension installed, including editable installs |
| Separately distributed third-party extension | Installed `taut.commands` entry point | Wheel installed into the same interpreter environment as `taut` |

Importability alone is not registration. A sibling source directory that is
not installed contributes no commands. This matters for `pipx`: the extension
must be injected into the same pipx environment as core. It also matters for
tests: setting `PYTHONPATH` is not a valid substitute for installing the wheel
and its generated entry-point metadata.

The integration flow is:

```text
static built-in specs ───────────────┐
installed taut.commands manifests ──┼─> CommandRegistry snapshot
reserved compatibility specs ───────┘        │
                                              ├─> root help/provenance
                                              └─> selected spec
                                                    │
                                                    └─> lazy factory
                                                          │
                                                          └─> adapter -> domain API
```

The registry is the convergence point, not a second domain layer. It decides
which manifest owns a name and records availability/provenance. It does not
run commands, resolve implementation targets, or initialize their subsystems.

## Version-1 Manifest and Adapter Contract

`taut.commands` is the public extension-author import surface. A manifest is a
frozen `CommandSpec` with exactly these fields:

- `command_api_version=1`;
- a canonical lowercase, hyphenated `name`;
- a non-empty one-line `summary` for root help;
- a `frozenset[GlobalOption]` naming root globals accepted after the verb;
- an `implementation` target in `module:attribute` form.

The installed entry point targets the manifest object, not the command
factory. For example, Summon publishes:

```toml
[project.entry-points."taut.commands"]
summon = "taut_summon.command_manifest:summon"
dismiss = "taut_summon.command_manifest:dismiss"
```

Its manifest then points at
`taut_summon.commands.summon:create_command`. The manifest module may import
only lightweight protocol definitions. It must not import the controller,
storage client, driver, provider adapters, PTY code, or start any work.

Each entry-point key must equal `CommandSpec.name`, and each command is one
entry point. The distribution name and version come from installed metadata
and become diagnostic provenance. For reserved first-party names, the
normalized distribution name is also the ownership selector. It is not an
authentication mechanism; installed command code is already trusted in-process.
The manifest and implementation modules must both be included in the built
wheel; a source test that imports them does not prove packaging. A separately
packaged extension must declare a `taut` dependency floor that contains the
command-interface version it uses. Version 1 first ships in Taut 0.6.0.

A minimal extension package therefore contains three connected declarations:

```toml
# pyproject.toml
[project]
dependencies = ["taut>=0.6.0"]

[project.entry-points."taut.commands"]
review = "review_extension.manifest:review"
```

```python
# review_extension/manifest.py: metadata only
from taut.commands import CommandSpec

review = CommandSpec(
    command_api_version=1,
    name="review",
    summary="Review the selected workspace.",
    post_verb_globals=frozenset(),
    implementation="review_extension.command:create_command",
)
```

```python
# review_extension/command.py: imported only after selection
def create_command() -> ReviewCommand:
    return ReviewCommand()
```

The concrete adapter supplies `configure_parser` and `run` as described below.
`tests/fixtures/taut_command_plugin` is the runnable repository example.

The zero-argument factory returns a fresh object implementing two methods:

```python
def configure_parser(parser: CommandArgumentParser) -> None: ...
def run(context: CommandContext, args: argparse.Namespace) -> int: ...
```

`configure_parser` owns command-local syntax. Core owns the parser instance,
usage exit 1, output streams, declared root globals, and final parsing policy.
A command with variable-length positionals around local options may opt into
intermixed parsing through `enable_intermixed_args()`; this is not the default
and cannot be combined with unsupported argparse shapes such as nested
subparsers or `REMAINDER`.

`run` owns adaptation from parsed values to a domain API. It returns only 0,
1, or 2. Expected user-facing failures should raise `CommandError` with exit 1
or 2. Core renders unexpected failures without a traceback and always closes
the context's lazy client. An adapter must write through `context.stdin`,
`stdout`, and `stderr`, not ambient process streams.

`CommandContext` is intentionally not a service locator. It carries root
values, authoritative streams, and one lazy `TautClient`. Extension-specific
operations stay on the extension's public domain interface. Summon adapters,
for example, construct `SummonController`; they do not teach core context about
Summon.

Every root option is accepted before the verb. A manifest's
`post_verb_globals` declares only which exact spellings core may extract after
that verb and show in command help:

| `GlobalOption` | Spellings | Context field | Merge/default |
|---|---|---|---|
| `DB` | `--db PATH`, `--db=PATH` | `db_path` | Later post-verb value wins; default `None` |
| `AS` | `--as NAME`, `--as=NAME` | `as_name` | Later post-verb value wins; default `None` |
| `TOKEN` | `--token TOKEN`, `--token=TOKEN` | `auth_token` | Later post-verb value wins; default `None` |
| `JSON` | `--json` | `json` | Boolean OR; default `False` |
| `TIMESTAMPS` | `-t`, `--timestamps` | `timestamps` | Boolean OR; default `False` |
| `QUIET` | `-q`, `--quiet` | `quiet` | Boolean OR; default `False` |

Do not list a global merely because an extension might inspect the context.
The declaration is part of that verb's grammar. Command-local options remain
the adapter's responsibility and may not reuse a declared root spelling with a
different meaning.

## Selection and Ownership

Built-in names cannot be overridden. Ordinary duplicate installed names make
only that verb unavailable and name both owners; unrelated commands continue.
Registry order is deterministic and does not depend on installation order.

Distribution normalization lowercases the name and collapses every run of
hyphens, underscores, or dots to one hyphen. `taut-summon`, `taut_summon`, and
`TAUT.SUMMON` therefore compare equal. If manifest loading fails, the
entry-point key owns the unavailable record because no valid manifest name
exists. If loading succeeds, the key must equal `CommandSpec.name` exactly.
Root help keeps unavailable verbs visible with the summary `unavailable` and
writes each diagnostic once as a warning. An installed claim for a built-in
becomes a warning and is discarded; the built-in remains usable. For an
ordinary external name, one broken plus one valid claim is still a conflict,
not permission to guess which package the user intended.

`summon` and `dismiss` are exceptional only in ownership, not protocol. They
are reserved first-party slots. A unique valid entry point from the normalized
`taut-summon` distribution owns each slot. Unofficial claims cannot suppress
the first-party path. Broken or duplicate official claims fail loudly and do
not fall back to older code.

Core 0.6.0 retains `taut/commands/_summon_compat.py` only for paired rollout
with Summon 0.5.4. When Summon 0.6.0 is installed, its entry points win and the
bridge does not execute. Remove the bridge only in a later paired release when
0.6.0 is the immediately previous supported Summon, both 0.6.0 entry points
remain present, and artifact policy no longer promises 0.5.4 compatibility.
The bridge must not grow into a generic fallback mechanism.

There are two cached registry paths in CLI dispatch. `taut --version` uses
neither. Direct execution of a known core built-in uses the static snapshot and
does not enumerate installed entry points, so a broken unrelated extension
cannot break ordinary messaging. Root help and reserved/external command
selection use the installed snapshot; construction loads every discovered
manifest to produce the complete sorted inventory and isolated diagnostics.
Both snapshots are immutable for the process. Install/uninstall changes are
observed by starting the next process; version 1 has no hot reload.

## Lazy Imports and Initialization

Lazy loading is enforced at subsystem seams, not by hiding all imports behind
one generic loader:

- `taut --version` uses only constants and does not enumerate entry points.
- A selected static built-in can use the static registry without enumerating
  installed manifests.
- Root help may import installed manifest modules, but not their implementation
  targets.
- Command help may import the selected parser adapter, but not the domain
  runtime that execution needs.
- Actual execution imports only the selected command's domain modules.
- `import taut` and `import taut_summon` expose typed package facades through
  `TYPE_CHECKING` imports and cached `__getattr__` lookup.

Import and discovery must not open storage, start a thread or process, install
a signal handler, or change terminal state. Lazy loading moves an optional
subsystem failure to first use; it does not hide the failure. Diagnostics must
still name the selected distribution, entry point, implementation target, and
original cause where those values are available.

The package facades and command factories solve different problems. Facades
preserve convenient typed Python imports. Factories prevent one CLI verb from
initializing unrelated subsystems. Keep both seams narrow instead of inventing
a general dependency-injection container.

## Command Adapter Versus Domain Interface

A command adapter is presentation glue. It parses, maps root context into a
request, calls a domain API, renders results, and maps typed domain errors to
shell exit classes. It is not the reusable API.

This distinction is load-bearing for richer hosts. Parsing console output
would create a second, text-shaped API and would not expose lifecycle or
terminal ownership safely. Summon's reusable boundary is `SummonController`
plus its typed models and `SummonInteraction`. The standalone
`taut-summon` console and the installed `taut summon`/`taut dismiss` adapters
share parser helpers and controller calls; neither invokes the other.

Core commands may call `context.client()` because `TautClient` is their domain
surface. An extension should call its own public controller. If an operation
cannot be expressed without importing another package's private state, the
missing piece is a domain interface, not another command-context field.

## Rich TUI Boundary

A future first-party TUI may be richer than the command interface. It should
be a composition root that depends directly on `TautClient`, `TautWatcher`,
and public extension controllers. It need not render argparse forms or reduce
all capabilities to generic command manifests.

For Summon, the TUI supplies a `SummonInteraction` that can report terminal
availability and grant a scoped input/output fd lease. Summon still owns PTY
bytes, the attach transition, driver state, and cleanup. The TUI must not read
Summon tables, synthesize control JSON, or duplicate PTY lifecycle.

The current controller's foreground run is blocking. This release does not
choose the TUI's process model, screen suspension, log routing, release
handshake, exit/orphan policy, or the fate of TUI-launched drivers when the TUI
exits. Those are product and process-lifecycle decisions for the TUI's own
specification. Adding them here would be speculative coupling.

## Where to Edit

| Concern | Owner |
|---|---|
| Public protocol types | `taut/commands/_protocol.py` and exports in `taut/commands/__init__.py` |
| Static built-in manifests | `taut/commands/_builtins.py` |
| Installed discovery, conflicts, reserved slots | `taut/commands/_registry.py` |
| Root/global splitting, lazy factory load, cleanup | `taut/commands/_dispatch.py` |
| Built-in command adapters and renderers | `taut/commands/` |
| Temporary Summon 0.5.4 bridge | `taut/commands/_summon_compat.py` |
| Native Summon manifests/adapters | `extensions/taut_summon/taut_summon/command_manifest.py` and `commands/` |
| Reusable Summon operations | `extensions/taut_summon/taut_summon/controller.py`, `models.py`, and `interaction.py` |
| Fresh-wheel compatibility | `bin/check-core-summon-wheel-matrix.py` and `bin/build-and-check-release-wheels.py` |

## Verification and Extension-Author Checklist

Prefer black-box and installed-artifact proofs over mocks of the registry or
domain runtime. `tests/test_command_registry.py` owns protocol, parser,
conflict, cleanup, and real SQLite behavior. `tests/test_lazy_imports.py` and
`tests/test_architecture_boundaries.py` own import floors and dependency
direction. `tests/test_core_summon_wheel_matrix.py` builds and installs real
wheels, verifies exact entry-point ownership, and exercises paired Summon
lifecycle. `tests/fixtures/taut_command_plugin` is the minimal third-party
packaging example.

The principal firing tests are:

| Contract | Firing proof |
|---|---|
| Manifest/key validation and failure isolation | `tests/test_command_registry.py::test_bad_manifest_isolated_as_selected_command_error` |
| Reserved-owner normalization | `tests/test_command_registry.py::test_unique_normalized_official_claim_owns_reserved_slot` |
| Broken-provider root help | `tests/test_command_registry.py::test_root_help_lists_unavailable_commands_and_emits_each_diagnostic_once` |
| Static built-in fast path versus installed discovery | `tests/test_lazy_imports.py::test_installed_core_selection_skips_unrelated_manifest_but_help_and_reserved_do_not` |
| Real wheel install and next-process uninstall visibility | `tests/test_command_registry.py::test_installed_console_discovers_then_loses_uninstalled_command` |
| Exact fresh Summon/core wheel entries and paired lifecycle | `tests/test_core_summon_wheel_matrix.py` metadata and installed-artifact cases |
| Import and initialization floors | `tests/test_lazy_imports.py` and `tests/test_architecture_boundaries.py` |

For a new core built-in:

1. Put domain behavior behind the owning package's typed API.
2. Add its lightweight manifest to `taut/commands/_builtins.py` and write the
   failing source-tree contract test.
3. Add its factory and thin adapter under `taut/commands/`; reuse shared
   renderers and parser helpers.
4. Test real state and subprocess behavior. Mock only metadata enumeration,
   clocks, or a true external host/provider seam.
5. Add import-floor assertions proving root and command help do not initialize
   the domain runtime.
6. Update the governing spec, this implementation guide, repository map, and
   changelog when the public or ownership contract changes.

For a new installed extension command:

1. Put domain behavior behind the extension's typed public API.
2. Declare a compatible `taut` dependency floor, one `taut.commands` entry
   point per verb, and matching lightweight `CommandSpec` objects.
3. Write the failing manifest/package contract, then add zero-argument
   factories and thin adapters. Ensure every target module is included in the
   built wheel.
4. Test real domain state and subprocess behavior. Do not replace broker,
   storage, or CLI execution with mocks.
5. Build and install the wheel into a checkout-free environment. Test
   selection, help, execution, conflict, and uninstall in separate processes.
6. Add import-floor assertions proving manifest and command help discovery do
   not initialize the extension runtime.
7. Update the governing spec, this guide, package README, repository map, and
   changelog for public or ownership changes.

Version 1 is intentionally small: top-level verbs only, no aliases, priority,
hot reload, nested cross-package namespace, or dependency graph. Add one of
those only for a concrete product need with its own compatibility plan.

## Related Plan

- `docs/plans/2026-07-12-lazy-command-extensions-and-rich-tui-composition-plan.md`
  — reviewed specification, implementation sequence, rollout matrix, and
  execution evidence for this design.
