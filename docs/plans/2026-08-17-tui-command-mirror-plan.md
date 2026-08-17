# TUI Textual Command Mirror Plan

Date: 2026-08-17

Status: active; implementation authorized by the owner on 2026-08-17 after
independent review and approval of the spec-promotion gate

Owner: Taut maintainers

Class: 5 - the change adds a normative command-input contract and changes the
TUI and extension command boundaries

Plan type: implementation with spec revision

Hardening: required - this crosses the CLI/TUI/extension boundary, adds a new
deferred command execution path, and includes terminal-owning Summon behavior

## Goal

Make TUI `COMMAND` mode a textual mirror of the Taut command language after
the `taut` executable name. `:summon grok` must be recognized as the command
`summon grok` and dispatched through the TUI's native typed handler. The TUI
must not invoke the CLI executable, spawn a CLI subprocess, or treat the text
as an opaque argument vector. The existing grouped action browser remains the
discoverable visual view over the native action registry.

The mirror is a language and affordance contract. It is not a second CLI
process and it is not a generic form generator over `argparse`.

## Requested outcomes

- `:` opens a visibly labeled command-line state inside `COMMAND` mode.
- Text after `:` accepts the same command paths, nested commands, positionals,
  options, quoting, and `--` separator semantics as the supported CLI grammar,
  without the leading `taut` token.
- Enter parses and executes a complete command through a native TUI binding.
- `:summon grok` reaches the public Summon controller through the existing TUI
  Summon owner and terminal-interaction boundary.
- The Commands affordance and `Ctrl-P` retain a grouped action browser with
  visible activation instructions.
- Injected first-party command syntax can register through a typed extension
  provider. Unknown or unsupported commands produce a clear inline result;
  they never disappear silently.
- CLI behavior, exit codes, output, extension discovery, and lazy loading stay
  unchanged outside the new TUI mirror contract.

## Source documents

Source specs:

- `docs/specs/02-taut-core.md` [TAUT-8.1], [TAUT-8.3], [TAUT-8.6], [TAUT-12.4]
- `docs/specs/04-summon.md` [SUM-6], [SUM-7.1], [SUM-13], [SUM-13.1]
- `docs/specs/10-taut-tui.md` [TUI-2.1], [TUI-2.2], [TUI-4.3], [TUI-7.1],
  [TUI-7.2], [TUI-10.3], [TUI-11.1], [TUI-11.3], [TUI-13]
- `docs/specs/01-development-documentation-operating-model.md` [DOM-5],
  [DOM-6], [DOM-10], [DOM-11], [DOM-15]

Canonical context and runbooks consulted:

- `docs/program-theory.md`
- `docs/agent-context/decision-hierarchy.md`
- `docs/agent-context/principles.md`
- `docs/agent-context/engineering-principles.md`
- `docs/agent-context/runbooks/writing-plans.md`
- `docs/agent-context/runbooks/hardening-plans.md`
- `docs/agent-context/runbooks/review-loops-and-agent-bootstrap.md`
- `docs/agent-context/runbooks/testing-patterns.md`
- `docs/lessons.md`

Existing implementation and planning records:

- `docs/implementation/12-taut-tui.md`
- `docs/plans/2026-08-12-taut-tui-implementation-plan.md`
- `docs/plans/2026-08-14-cross-surface-command-capability-plan.md` - related
  but explicitly deferred. This plan does not revive its proposed universal
  semantic capability inventory.
- `extensions/taut_tui/README.md`
- `extensions/taut_summon/README.md`

## Classification and baselines

This is Class 5 because the current TUI contract explicitly says that
`COMMAND` mode accepts no arbitrary command-line text and does not parse CLI
text. The requested behavior changes that contract. It is also risky because
command execution crosses asynchronous TUI ownership, extension discovery,
output rendering, and the Summon terminal handoff.

The spec baseline is commit
`38579a467d1b1a76544426a94b46766fdad225ee` (2026-08-15), with a clean
worktree at plan start. The governing files at that baseline are:

- `docs/specs/02-taut-core.md`
- `docs/specs/04-summon.md`
- `docs/specs/10-taut-tui.md`

No code may cite the new requirement identifiers until the spec-promotion
slice has landed. The promotion baseline is commit
`9888b38ceb4de509fad153c1b2970d4ca2832bb3` (2026-08-17). Runtime code may
now cite [TAUT-8.7], [TUI-7.1], and the related extension requirements.

## Current state and key files

The current TUI command path is an action palette, not a command line:

- `extensions/taut_tui/taut_tui/app.py:725-731` changes the visual mode to
  `COMMAND` and pushes `CommandPaletteScreen`.
- `extensions/taut_tui/taut_tui/screens.py:267-341` filters human labels and
  internal action ids. Enter selects the first enabled result; the screen has
  no command parser, command syntax preview, or activation hint.
- `extensions/taut_tui/taut_tui/app.py:1312-1354` creates palette entries from
  the native action registry and dispatches an `ActionId`.
- `extensions/taut_tui/taut_tui/actions.py:87-130` defines `ActionSpec`; the
  tuple at `:139-314` currently provides tuple order and internal family names,
  but no stable display-group or display-order metadata.
- `extensions/taut_tui/taut_tui/forms.py` owns native form contracts and
  explicitly does not parse command lines.
- `extensions/taut_tui/taut_tui/domain.py`, `system.py`, and `summon.py` own
  public typed TUI operations and must remain the execution owners.

The CLI command inventory and grammar are split today:

- `taut/commands/_protocol.py:32-42` defines `CommandSpec`, which has root
  name, summary, post-verb globals, implementation target, and raw-stdio
  metadata. It does not describe nested grammar or TUI behavior.
- `taut/commands/_registry.py:55-103` builds the immutable installed command
  registry and reserves `summon` and `dismiss` for `taut-summon`.
- `taut/commands/_builtins.py:33-60` declares the 20 first-party root
  commands and their manifest-level global options.
- Each command adapter's `configure_parser()` owns its nested argparse grammar;
  `taut/commands/_dispatch.py` owns root parsing and selected-adapter dispatch.
- `docs/specs/02-taut-core.md` [TAUT-8.1] is the user-facing command grammar
  and must remain the compatibility reference.

Summon already has a native TUI boundary:

- `extensions/taut_summon/taut_summon/command_manifest.py` publishes the
  `summon` and `dismiss` command manifests.
- `extensions/taut_tui/taut_tui/summon.py` owns TUI-started Summon workers,
  run handles, readiness, shutdown, and terminal interaction.
- `extensions/taut_summon/taut_summon/controller.py` is the public typed
  controller. The TUI must continue to use it rather than the CLI adapter or
  `ShellSummonInteraction`.

### Required comprehension questions for implementers

Record answers in the execution log before editing code:

1. Why is `CommandSpec` insufficient as the mirror grammar, and where does
   nested command syntax live today?

   Expected answer: `CommandSpec` contains only root manifest metadata;
   nested syntax lives in selected adapters' `configure_parser()` methods.

2. Which owner must receive a TUI `summon` invocation, and which two paths are
   forbidden?

   Expected answer: `TuiSummonOperations` must build and run the public
   `SummonController` operation; invoking the root CLI dispatcher or
   `ShellSummonInteraction` is forbidden.

### Execution log

- 2026-08-17: The `CommandSpec` insufficiency was confirmed by inspection of
  `taut/commands/_protocol.py`; nested grammar is still distributed across
  adapter `configure_parser()` methods. The promoted [TAUT-8.7] contract now
  gives those forms one surface-neutral syntax owner.
- 2026-08-17: The TUI Summon owner was confirmed as
  `extensions/taut_tui/taut_tui/summon.py`, which calls the public
  `SummonController` boundary. CLI dispatch and `ShellSummonInteraction`
  remain forbidden paths.
- 2026-08-17: The shared typed syntax tree, parser, provider discovery, and
  TUI command-line screen were implemented. Core paths are mirror-recognized;
  native execution is selected by the explicit TUI binding matrix. The grouped
  browser remains on `Ctrl-P`, while `:` opens the textual mirror.
- 2026-08-17: `taut-summon` now publishes a `taut.command_syntax` provider.
  The TUI fallback-loads that provider only when the existing Summon owner is
  available, then dispatches through `TuiSummonOperations` and the public
  controller boundary.

## Product and interaction contract

### Two views over one command vocabulary

`COMMAND` mode has two entry states:

1. `:` opens the textual command line. The screen shows a leading `:` marker,
   an editable single-line command field, completion/help feedback, and the
   instruction `Enter run · Tab complete · Esc close`. The colon is the TUI
   mode opener and is not sent to the command parser.
2. `Ctrl-P` and the Commands button open the grouped action browser. The
   browser shows headings such as `Workspace & identity`, `Conversations`,
   `Channels`, `Messages`, `Search`, `System`, and `Summon`. It shows
   `Type to filter · Up/Down select · Enter run · Click run · Esc close`.

Both states resolve to the same native action or typed command owner. The
   browser does not need to display a CLI spelling beside every action. Its
   grouping and labels must make the relationship understandable without that
   mapping.

### Textual mirror behavior

- `:summon grok` parses as the command path `("summon",)` with the typed
  provider-or-name value `"grok"`.
- Root globals and command-local options follow [TAUT-8.1] placement and
  separator rules. The mirror accepts quoted values and reports malformed
  quoting before execution.
- No shell expansion, pipes, redirection, environment interpolation, or
  command substitution is added. The mirror reflects Taut's command language,
  not a shell.
- The CLI's omitted-text and `-` stdin forms for `say` and `reply` are
  syntax-recognized but are CLI-only in the TUI. The TUI has no process-stdin
  command source; users enter explicit text in the command line or composer.
- Empty input shows command-root completion and grouped help. A partial root
  or nested path shows matching commands and syntax. A complete command shows
  its parsed values and an enabled/disabled execution state.
- Enter executes only a complete, supported command. An incomplete or invalid
  command stays open and shows an inline error with the relevant syntax.
- Escape cancels without mutation. A second Enter cannot duplicate a command
  while its owner is pending.
- Output is rendered into a native inspector/result surface. It does not write
  through ambient stdout or move the Textual terminal cursor.
- A syntactically known command with no safe native TUI binding is still
  recognized and reports `CLI-only in TUI: <command path>` with its syntax.
  It is not silently omitted. `system load` remains in this category unless a
  later plan changes the explicit [TUI-10.3] maintenance boundary.

The scope guarantee is therefore precise: every core CLI command path and its
released syntax, plus every installed extension syntax provider, are
mirror-recognized; native execution is guaranteed only for paths with an
explicit TUI binding. The first implementation must publish
the complete disposition matrix below. It must not claim that every CLI
output/global-option mode has an equivalent TUI behavior.

### Root-global policy in the TUI

The shared parser recognizes the released global spellings, but execution is
surface-specific:

| Global | TUI behavior |
|--------|--------------|
| `--help` / command help | Render typed syntax and help in the command screen; no mutation. |
| `--version` | Render the TUI/core version receipt; no mutation. |
| `--db PATH` | Accept only when `PATH` resolves to the active TUI database; otherwise report that the session target is fixed until restart. |
| `--as NAME`, `--token TOKEN` | Parse, then report that TUI identity is fixed for this session; use the native identity/rejoin flow instead. |
| `--json`, `-t/--timestamps`, `-q/--quiet` | Parse, then report that CLI output modes are not execution modes in the TUI. Results use the native inspector. |

This keeps the command language mirrored without pretending that a full-screen
host has CLI stdout, exit-status, or process-global identity semantics.

### Injected commands

The mirror adds a narrow typed syntax-provider contract for command extensions.
It is not a generic rich-view or widget plugin protocol.

- Core publishes syntax for its built-in commands.
- `taut-summon` publishes syntax for `summon` and `dismiss` through the new
  versioned provider contract.
- The TUI separately registers a native binding for a provider command. Syntax
  discovery alone never creates a handler, form, or subprocess path.
- An installed provider that has syntax but no TUI binding is visible as
  unsupported in the command line and does not enter the action browser.
- If the optional `taut-summon` syntax provider is absent, `summon` and
  `dismiss` are reported as extension syntax unavailable/CLI-only rather than
  treated as core commands. A loaded provider with a registration error gets a
  visible diagnostic.
- Provider load and registration errors are isolated and shown as diagnostics;
  they cannot terminate the Textual event loop or hide core commands.

## Invariants and constraints

1. The mirror is textual input plus native dispatch. It never invokes the
   `taut` executable, calls the root CLI dispatcher, passes text to a
   subprocess, or forwards ambient stdout/stderr.
2. The shared syntax contract is the only source of command spelling,
   nesting, option placement, quoting, and separator behavior. The CLI and
   TUI may render and execute differently, but they cannot maintain divergent
   grammars.
3. `CommandSpec` version 1 remains a compatible manifest contract. Syntax
   metadata is adjacent typed contract data, not an undocumented field added
   to the existing manifest.
4. TUI action applicability remains owned by the existing ordered input
   contracts. A textual command cannot bypass a disabled action, confirmation,
   stale-state defense, or domain validation.
5. Native forms remain native forms. Command text may prefill a form only when
   the command is incomplete or the action deliberately requires confirmation;
   the TUI must not generate forms from argparse metadata.
6. Core operations remain behind `TautClient`, `TautWatcher`, public value
   objects, and actor-free operation owners. The TUI command dispatcher does
   not inspect sidecar tables or private extension state.
7. Summon keeps one TUI-owned worker and one public run handle per foreground
   run. `summon --attach` and terminal takeover use the existing terminal lease
   and cannot run concurrently with Textual terminal ownership.
8. Command completion, parsing, and display are synchronous and bounded. Domain
   work, search, doctor, dump, watcher changes, and Summon work remain on their
   existing workers.
9. A successful domain operation cannot be downgraded by result rendering,
   toast, focus, or completion callback failure. Presentation failures are
   contained at the existing TUI boundary.
10. Existing direct keys, mouse routes, palette routes, forms, CLI behavior,
    installed command discovery, and lazy import guarantees remain intact.
11. The action-browser fix for single-flight dismissal remains intact. A
    command result may close its own screen at most once.
12. Command bindings receive typed command values and explicit command context.
    They do not silently substitute the current visual selection for an
    explicit command target. Existing applicability and confirmation rules
    remain in force, with command-specific target validation added where the
    palette has no target.
13. TUI command input has no process-stdin form. `say TARGET -`, `reply THREAD
    MSG_ID -`, and equivalent omitted-text stdin forms are syntax-recognized but
    report CLI-only in the TUI. Users enter explicit text or use the composer.

## Deviation Log

Empty at plan start. Any departure from the promoted spec must add one row here
before implementation continues.

| Spec ref | Planned behavior | Actual behavior | Rationale | Spec proposal |
|----------|------------------|-----------------|-----------|---------------|
| TAUT-8.7 / task 3 | Migrate every CLI `configure_parser()` grammar to the shared AST in this slice. | The typed AST is complete for the released core mirror grammar, but existing argparse adapters remain the CLI compatibility owner. | Preserves exact CLI help, usage errors, exit classes, and lazy adapter loading while the new TUI contract lands. | Follow-up migration should add an AST-to-argparse compatibility builder and compare the released CLI matrix before removing adapter-owned parser declarations. |
| TUI-7.1 / task 7 | Treat `watch` as a native live-view binding. | `watch` is syntax-recognized and explicitly CLI-only in this slice. Search filter options are likewise explicit CLI-only; basic query and limit are native. | The TUI does not approximate watcher lifecycle, filter, or search-scope semantics with a one-shot dispatch. | Revisit only with a separate watcher/search binding plan and lifecycle tests. |

## Spec baseline and proposed delta

### Promotion strategy

Use strategy A from `writing-plans.md`: promote exact requirement text into the
existing specs without implementation-link claims, then add reciprocal links
with the implementation slice after the delta is accepted. The independent
review must cover this delta before promotion. The spec-promotion slice must
update the `## Related Plans` sections and record the post-promotion baseline
SHA here.

### Core delta: `docs/specs/02-taut-core.md`

Insert after [TAUT-8.6]:

> ### [TAUT-8.7] Shared command syntax for surface mirrors
>
> Taut command syntax is a typed, surface-neutral contract adjacent to the
> version-1 `CommandSpec` manifest. It describes canonical command paths,
> nested subcommands, positional values, options, value kinds, quoting,
> literal `--` separator behavior, and deterministic completion metadata. It
> does not describe a surface's renderer, form layout, gesture, lifecycle, or
> output transport.
>
> The CLI parser and an approved textual command mirror consume this contract.
> A mirror may dispatch to a surface-native typed owner, but it must not invoke
> the `taut` executable, call the root CLI dispatcher, or treat the syntax as a
> shell command. The existing version-1 command manifest remains unchanged;
> syntax providers are separately versioned and discovered through the typed
> command-syntax provider interface.
>
> Core owns syntax for every built-in command. An extension may publish syntax
> for its own command through the provider interface. Syntax discovery does not
> grant any surface permission to execute the command or reflect its
> implementation target. A surface must register a native binding before it
> executes a mirrored command. A rich host may recognize an extension command
> without executing it when no native binding has been installed for that host.
> The root syntax wrapper owns pre-verb global options, post-verb declarations,
> root actions such as `--help` and `--version`, and the released precedence
> rules. These are part of the shared grammar rather than ad hoc surface logic.

### Summon delta: `docs/specs/04-summon.md`

Insert in [SUM-13], after the existing public-controller host boundary:

> A rich host may publish a typed command-syntax provider for the extension's
> CLI command paths and a separate native host binding. The provider may parse
> `summon` and `dismiss` mirror input into typed request values, but it never
> invokes the CLI adapter or owns the host terminal. A TUI host continues to
> call the public controller and to supply the [SUM-13] interaction adapter.
> Provider absence, malformed input, unavailable provider, and terminal-lease
> failure remain distinct user-visible outcomes.

### TUI delta: `docs/specs/10-taut-tui.md`

Amend [TUI-2.1] as follows:

> The TUI may consume the public typed command-syntax contract for its textual
> mirror. It must not invoke the CLI executable or root CLI dispatcher, inspect
> command implementation targets, run command adapters for their CLI output, or
> generate native forms from parser metadata. Native command bindings remain
> TUI-owned adapters over public typed interfaces.

Replace [TUI-7.1] with the following requirement:

> ### [TUI-7.1] Native command surfaces
>
> `COMMAND` mode contains a grouped native-action browser and a textual command
> line. The browser lists currently available native actions by stable
> human-facing groups, shows disabled reasons, and has visible selection and
> activation instructions. The command line is opened with `:` and mirrors the
> Taut command language after the `taut` executable name. It accepts command
> paths, nested paths, positionals, options, quoted values, and literal `--`
> according to the shared syntax contract. `:` is not part of the command.
>
> Enter executes a complete command only through a registered native TUI
> binding. The binding may invoke an existing action, open a deliberately
> chosen native form, or schedule a typed public operation and render its
> typed result in a native inspector. It never starts the CLI, passes input to
> a subprocess, forwards CLI output, or generates an argparse form. A known
> command without a native binding remains typeable and reports an explicit
> CLI-only result. Escape cancels without mutation; pending execution is
> single-flight; parse and domain errors remain inline and actionable.
>
> The mirror recognizes the released global option spellings. `--help` and
> command help render native syntax; `--version` renders a native version
> receipt; `--db` must resolve to the active session target; `--as` and `--token`
> report that TUI identity is fixed for the session; and `--json`, `-t`,
> `--timestamps`, and `-q` report that CLI output modes are unavailable in the
> native result surface. These options are not silently ignored.

Add to [TUI-11.1]:

> When `taut-summon` is available, the TUI registers native textual mirror
> bindings for `summon` and `dismiss` through the public controller boundary.
> `:summon grok` is a typed request, not a CLI invocation. The existing
> foreground ownership, readiness, terminal lease, logging, and shutdown
> rules remain authoritative.

Leave [TUI-14]'s generic-renderer and rich-view-plugin prohibitions in place.
The blanket prohibition on command text is removed from [TUI-7.1] by the
replacement above; [TUI-14] needs no unrelated change.

## Architecture and API shape

### Shared syntax contract

Add a public `taut.commands.syntax` module. The exact names may change during
review, but the contract must contain equivalent typed shapes:

```python
CommandPath = tuple[str, ...]

@dataclass(frozen=True, slots=True)
class CommandSyntax:
    path: CommandPath
    summary: str
    positionals: tuple[PositionalSyntax, ...]
    options: tuple[OptionSyntax, ...]
    children: tuple[CommandSyntax, ...]
    exclusive_groups: tuple[ExclusiveGroupSyntax, ...]
    intermixed: bool = False
    accepts_remainder: bool = False

@dataclass(frozen=True, slots=True)
class RootCommandSyntax:
    globals: tuple[GlobalOptionSyntax, ...]
    commands: tuple[CommandSyntax, ...]
    root_actions: tuple[str, ...]

@dataclass(frozen=True, slots=True)
class CommandInput:
    text: str

@dataclass(frozen=True, slots=True)
class CommandInvocation:
    path: CommandPath
    values: Mapping[str, object]
    source: CommandInput
```

`PositionalSyntax`, `OptionSyntax`, and `ExclusiveGroupSyntax` must cover the
currently released grammar: required and optional values, repeated values,
choices, string/int/path value kinds, short and long spellings, defaults,
mutually exclusive groups, `REMAINDER`-style tails, intermixed parsing opt-ins,
the `--` separator, and the command's completion/help text. The AST is the
canonical grammar source. `RootCommandSyntax` additionally owns pre-verb
globals, per-command post-verb global declarations, root actions, and
precedence. The CLI adapter builds its existing `CommandArgumentParser`
behavior from this AST, while the TUI uses the same AST with its own lexer and
typed result path. Parsing returns a typed invocation or a span-aware user
error. It does not return or expose an `argv` object.

Core built-ins publish a deterministic syntax registry. The CLI adapter uses
that registry to preserve current behavior. The TUI uses the same registry for
tokenization, parsing, help, and completion. Existing command execution
adapters remain responsible for domain semantics and CLI rendering.

### Extension provider contract

Add a versioned `taut.command_syntax` entry-point group. A provider returns
syntax only for its owned command paths and declares a stable provider name
and version. It must not expose an implementation target as a UI schema.

`taut-summon` publishes `summon` and `dismiss` syntax through this group. The
TUI's Summon adapter separately binds those paths to `TuiSummonOperations`.
Provider loading is isolated, deterministic, and lazy with respect to command
execution. Unknown or broken providers remain diagnostics.

### TUI native binding

The TUI adds a command mirror registry separate from `ACTION_REGISTRY`:

```python
@dataclass(frozen=True, slots=True)
class TuiCommandBinding:
    path: CommandPath
    action_id: ActionId | None
    validate: Callable[[CommandInvocation, TuiCommandFacts], CommandApplicability]
    confirmation: ConfirmationPolicy
    execute: Callable[[CommandInvocation, TuiCommandHost], CommandOutcome]
```

`CommandOutcome` must distinguish: completed typed result, open native form,
pending typed operation, unsupported-in-TUI, and user-facing error. A binding
with an `action_id` derives its browser label, group, and order from
`ActionSpec`; a binding without one supplies an explicit native result owner.
This prevents a second label/group registry from drifting away from the action
registry. `validate` receives explicit command values plus closed TUI facts. It
must not replace an explicit target with the current selection. It returns the
same enabled/disabled reason shape used by the action applicability evaluator,
and `confirmation` routes destructive values through the existing exact-target
confirmation screen. Bindings may call the existing central action dispatcher
only when the action handler accepts the command's typed values. Otherwise they
call the existing public domain/system/Summon owner directly. The registry does
not manufacture handlers from syntax metadata.

### Screen model

Replace the single-purpose `CommandPaletteScreen` contract with a command
screen that supports browser and text entry states. Keep the existing screen
callback single-flight guard. The screen owns only text, selection, parse
feedback, and completion rows. The app owns execution, applicability, worker
submission, and result presentation.

Add display-group and deterministic display-order metadata to `ActionSpec`, or
to a TUI-owned companion descriptor if review rejects changing the current
dataclass. Do not sort by internal action id. Group headings are presentation
metadata, not CLI namespaces.

## Command binding disposition matrix

This matrix is a required implementation artifact. Every nested path must be
listed in the final version with the exact owner, result sink, and status. The
initial disposition is:

| Command path | Initial TUI disposition | Native owner or explicit boundary |
|--------------|-------------------------|-----------------------------------|
| `init` | native action | `ActionId.WORKSPACE_INITIALIZE` and `TuiDomainActions` |
| `join` | native form | `ActionId.CHANNEL_JOIN` and native form contract |
| `leave` | native action with confirmation | `ActionId.CHANNEL_LEAVE` and `TuiDomainActions` |
| `set name` | native form | `ActionId.IDENTITY_SET_NAME` and identity owner |
| `say` | native typed send for explicit text; stdin forms CLI-only | `TuiSession`/domain send owner with explicit target and text values |
| `reply` | native typed send for explicit text; stdin forms CLI-only | reply-thread owner with explicit thread and message values |
| `message show` | native typed report | public client read owner and inspector result sink |
| `message delete` | native typed confirmation | public client delete owner; command value is the exact message id |
| `message react` | native typed operation | public client reaction owner and inspector result sink |
| `channel show` | native typed report | public client channel metadata owner |
| `channel topic` | native form or typed operation | channel-topic owner and existing confirmation/validation policy |
| `channel rename` | native typed confirmation | public channel-rename owner |
| `read` | native typed read | session/client cursor owner and transcript/inspector sink |
| `inbox` | native typed claim/report | notification owner and inspector sink |
| `log` | native cursor-neutral report | public history owner and inspector sink |
| `search` | native typed query; unsupported filters are explicit CLI-only | existing search owner for query and limit; filter options are not silently ignored |
| `system doctor` | native typed report | `TuiSystemOperations` and system inspector |
| `system dump` | native form/worker | `TuiSystemOperations` and existing dump flow |
| `system debug enable/disable` | native typed operation | actor-free public debug owner and status sink |
| `system load` | explicit CLI-only | current [TUI-10.3] maintenance boundary |
| `list` | native typed report | public list owner and inspector sink |
| `watch` | explicit CLI-only in this slice | the TUI watcher lifecycle and filter semantics are not approximated by a one-shot command dispatch |
| `who` | native typed report | public member/presence owner and inspector sink |
| `whoami` | native typed report | public identity owner and inspector sink |
| `rejoin` | native typed identity flow | public rejoin owner and navigation refresh |
| `summon` | extension-owned native binding | `TuiSummonOperations` and public `SummonController` |
| `dismiss` | extension-owned native binding | existing Summon stop owner and confirmation |

The implementation may narrow a row only by changing this matrix, the
acceptance criteria, and the promoted spec before coding that slice. `watch`
is a deliberate stop gate because the CLI's filter and lifecycle semantics must
not be approximated by a label or a one-shot refresh.

## Dependency-ordered implementation tasks

### 1. Independent review of this plan and delta

- Files: this plan and the cited core, Summon, and TUI specs.
- Reviewer reads the current command registry, command adapters, TUI action
  registry, forms, app dispatcher, Summon controller, and existing related
  deferred plan.
- Review question: can an implementer build the mirror without importing
  implementation targets, duplicating grammar, or changing CLI behavior?
- Done when every finding is either incorporated, answered in the plan, or
  marked as a deliberate owner decision. A reviewer who cannot implement this
  confidently is a blocker.

### 2. Spec-promotion slice

- Files: `docs/specs/02-taut-core.md`, `docs/specs/04-summon.md`,
  `docs/specs/10-taut-tui.md`, and their `## Related Plans` sections.
- Apply the reviewed exact delta using strategy A.
- Run `bin/check-plan-status-index` and the repository spec/reference checks.
- Record the promotion commit SHA here before any code cites the new sections.
- Stop and re-plan if review rejects a shared syntax source, if the extension
  entry-point shape cannot remain lazy, or if the owner wants literal support
  for a currently CLI-only destructive maintenance command.

### 3. Build the shared syntax vocabulary

- Files: `taut/commands/syntax.py` or the reviewed public module location,
  `taut/commands/__init__.py`, `taut/commands/_builtins.py`,
  `taut/commands/_dispatch.py`, command adapter modules, and core command
  tests.
- Extract the released root and nested grammar into typed syntax definitions.
- Make the syntax AST the canonical grammar owner. Migrate every current
  `configure_parser()` grammar, including nested subparsers, mutually exclusive
  groups, intermixed parsing, `REMAINDER` tails, root-global placement, and
  root actions into that AST. Retain
  adapter `run()` methods and an argparse-compatible namespace bridge only as
  a CLI execution compatibility layer.
- Preserve the current CLI parser's root-global precedence, command-local
  option behavior, intermixed parsing opt-ins, `--` literal behavior, usage
  errors, and exit classes.
- Add a compatibility gate that parses a fixed matrix of existing CLI examples
  through the shared syntax parser and the CLI compatibility layer and asserts
  the same command path and typed values. Include `channel topic TEXT/--clear`,
  `system debug enable/disable`, `system load --dry-run`, and `summon` option
  combinations. Keep actual CLI execution tests real.
- Do not make the TUI import private command modules or implementation targets.
- Done when all current built-in roots and nested paths have syntax coverage,
  the AST can represent every released parser feature, existing CLI tests pass
  unchanged, and a syntax registry can be imported without importing Textual
  or command execution modules.

### 4. Add extension syntax discovery

- Files: core packaging/entry-point metadata, public syntax provider protocol,
  `extensions/taut_summon/taut_summon/command_manifest.py`, a new public
  Summon syntax provider module, and `tests/test_command_registry.py` or a
  focused provider test file.
- Add the versioned `taut.command_syntax` group without changing the existing
  `taut.commands` manifest contract.
- Make provider ordering, duplicate paths, malformed syntax, and provider
  failures deterministic and diagnosable.
- Prove that core import and CLI help stay lazy and that installing Summon
  exposes its syntax only through the installed provider path.
- Done when `summon` and `dismiss` are discoverable as syntax but no handler is
  inferred from syntax alone.

### 5. Rework action-browser information architecture

- Files: `extensions/taut_tui/taut_tui/actions.py`, `screens.py`, `app.py`,
  styles, `tests/test_tui_actions.py`, `test_tui_screens.py`, and
  `test_tui_app.py`.
- Add stable human-facing groups and explicit order to native actions.
- Render headings, disabled reasons, current selection, and the activation
  hint. Auto-highlight the first enabled row.
- Preserve the existing central `ActionId` dispatcher and route declarations.
- Keep single-click selection versus activation behavior explicit and retain
  the single-flight dismissal regression coverage.
- Done when the browser is understandable without internal family names and
  every existing palette action still reaches the same handler.

### 6. Add textual command-line state

- Files: `extensions/taut_tui/taut_tui/screens.py`, `models.py`, `actions.py`,
  `app.py`, and focused TUI tests.
- Bind `:` in normal mode to the command-line state. Preserve `Ctrl-P` and the
  Commands button as browser entry points.
- Add bounded completion for root and nested command paths, syntax preview,
  parse errors, quoted values, and literal `--` behavior.
- Enter submits only a complete parsed `CommandInvocation`. Escape cancels.
  Disable duplicate submission while the owner is pending.
- Keep the parser synchronous and domain-free. Do not run a worker from the
  screen or write directly to Textual from a parser callback.
- Done when pilot tests prove typing, navigation, completion, invalid input,
  cancellation, resize restoration, and exact single submission.

### 7. Bind core commands to native TUI owners

- Files: new TUI command-binding module, `app.py`, `domain.py`, `system.py`,
  existing native forms/screens, and focused tests.
- Build an explicit coverage matrix for every first-party root and nested path:
  `init`, `join`, `leave`, `set`, `say`, `reply`, `message`, `channel`, `read`,
  `inbox`, `log`, `search`, `system`, `list`, `watch`, `who`, `whoami`,
  `rejoin`, `summon`, and `dismiss`.
- Implement the disposition matrix in this plan as an executable registry/test,
  with one owner and one result sink per nested path. A root name alone is not
  coverage.
- Map action-shaped commands to existing `ActionId` and form contracts. Map
  read-only/report commands to typed inspector result rendering. Map
  long-running watcher commands to the existing watcher owner, with explicit
  cancellation and mode transitions.
- Treat parsed command values as explicit inputs to a command owner. Do not
  reuse an `ActionId` whose current handler reads only visual selection unless
  that handler is extended with a typed command binding and retains the same
  applicability, confirmation, and stale-state rules.
- Apply the root-global policy in [TUI-7.1] and add firing tests for each global
  option disposition. No global may be silently ignored.
- Reject or explicitly classify stdin-dependent forms. `say` and `reply` with
  omitted text or `-` remain CLI-only; explicit text follows the native typed
  binding.
- Keep `system load` explicit as CLI-only under [TUI-10.3] unless the owner
  approves a separate maintenance-boundary revision.
- Preserve confirmation and applicability semantics. A command cannot bypass
  a disabled action because it came from text.
- Done when the coverage matrix has no unclassified path: native binding,
  deliberate CLI-only status, or an approved extension-owned binding.

### 8. Add the Summon native mirror binding

- Files: `extensions/taut_tui/taut_tui/summon.py`, `app.py`, the new command
  binding adapter, `extensions/taut_summon/taut_summon` public provider files,
  and `extensions/taut_tui/tests/test_tui_summon.py`.
- Parse `summon` text into the typed request fields used by the existing native
  start path. `:summon grok` must select `grok` as the provider-or-name value
  and execute through the public controller boundary.
- Use `TuiSummonOperations`, `SummonRequest`, `SummonController`, existing
  readiness handles, and `SummonInteraction`. Do not use the CLI command
  adapter, root dispatcher, or `ShellSummonInteraction`.
- Preserve foreground worker ownership, attach/takeover terminal lease,
  logging bridge, shutdown, and external-driver distinction.
- Done when a real TUI harness proves a typed Summon request reaches the public
  controller and failures remain inline without terminating Textual. Provider
  binary behavior stays in the existing Summon conformance/live harness.

### 9. Result rendering, diagnostics, and unsupported commands

- Files: TUI command result model, inspector/result screen, app error boundary,
  command provider diagnostics, and tests.
- Render typed success receipts, multi-line reports, usage errors, domain
  errors, provider errors, and CLI-only notices with stable labels.
- Escape all command and provider text through the existing display sinks.
- Keep parse errors local to the command screen; keep domain/worker errors at
  the existing TUI operation boundary; keep provider load failures isolated.
- Done when every result class has one owner and no failure path falls through
  to the Textual fatal callback.

### 10. Documentation and traceability closeout

- Files: `docs/implementation/12-taut-tui.md`, relevant README/help text,
  `docs/specs/*` backlinks, this plan, and `docs/lessons.md` if a reusable
  correction was found.
- Document why command syntax is shared, why execution remains native, how
  extension providers are loaded, and which commands remain CLI-only.
- Add reciprocal implementation links only after the code and tests satisfy
  the promoted sections.
- Update the plan status index only when status changes, then run its checker.
- Done when the spec, plan, implementation note, and code form a closed
  traceability chain.

## Testing plan

| Layer | Proof | Expected coverage |
|-------|-------|-------------------|
| Syntax unit | Real shared parser over root, nested, quoted, repeated, typed, option, and `--` cases | Every first-party root and every nested path in [TAUT-8.1] |
| CLI compatibility | Existing `tests/test_cli.py`, `test_cli_probes.py`, and command help/usage tests | No changed CLI output, exit code, lazy import, or precedence behavior |
| Registry/provider | `tests/test_command_registry.py` plus syntax-provider fixtures | Deterministic discovery, duplicate paths, broken providers, absent Summon |
| Action browser | `extensions/taut_tui/tests/test_tui_actions.py`, `test_tui_screens.py`, `test_tui_action_routes.py` | Group headings, order, disabled reasons, selection, click/Enter, route parity |
| Text mode | New focused tests beside `test_tui_app.py` and `test_tui_screens.py` | `:summon grok`, root/nested completion, quoting, separator, invalid input, cancel, resize, single-flight |
| Native core bindings | Real SQLite TUI harness and existing public operation tests | Typed domain mutation, report rendering, confirmation, applicability, worker/error ownership |
| Summon binding | Existing TUI Summon fixtures plus `test_tui_summon.py` and focused public-controller tests | Request conversion, provider availability, readiness, terminal lease, shutdown, inline errors |
| Packaging | `test_tui_packaging.py`, installed-wheel matrix, and core lazy-import tests | Syntax provider entry point and no eager Textual or Summon import |
| Structural boundary | Architecture/grep checks and required coverage paths | No CLI subprocess, root dispatcher call, implementation-target reflection, or raw stdout path |
| Visual acceptance | Existing fixed-size TUI render fixtures plus command-screen fixtures | Browser headings, command-line marker, hint, completion, disabled/error/result states |

Anti-mocking rules:

- Keep SQLite `TautClient`, watcher, parser, and command registry behavior
  real in contract tests.
- Use a controlled public Summon controller or the existing fake provider at
  the provider/process boundary only. Do not mock away readiness, terminal
  lease, cleanup, or the TUI worker ownership state machine.
- Do not test command completion by asserting only private list contents. Drive
  the real Textual pilot and assert visible result plus native postcondition.
- Do not use a fake CLI process as proof. The absence of a subprocess is itself
  a structural and runtime assertion.

## Verification and gates

Per-slice gates:

```bash
uv run pytest tests/test_command_registry.py tests/test_cli.py tests/test_cli_probes.py
uv run --project extensions/taut_tui --extra dev --locked pytest \
  extensions/taut_tui/tests/test_tui_actions.py \
  extensions/taut_tui/tests/test_tui_screens.py \
  extensions/taut_tui/tests/test_tui_app.py \
  extensions/taut_tui/tests/test_tui_action_routes.py \
  extensions/taut_tui/tests/test_tui_summon.py
uv run --project extensions/taut_tui --extra dev --locked ruff check \
  extensions/taut_tui/taut_tui extensions/taut_tui/tests
uv run --project extensions/taut_tui --extra dev --locked mypy \
  extensions/taut_tui/taut_tui
```

Final gates:

- Run the full core command/CLI suite and the full retained TUI suite, not only
  the new tests.
- Run the full `extensions/taut_summon/tests` suite with its documented live
  harness settings for the available local lanes.
- Run package build/install probes for core, TUI, and Summon syntax provider
  discovery.
- Run `bin/check-plan-status-index`, documentation/reference checks, Ruff,
  mypy, and the repository required-coverage gate.
- Regenerate and inspect the command-screen visual fixtures at the retained
  terminal sizes. Visual inspection is supplementary to pilot assertions.
- Verify from the current worktree that no code path imports or calls the root
  CLI dispatcher from TUI command execution and that no command result writes
  to ambient stdout.
- Record each changed file, command, observed result, and residual risk in the
  execution log and this plan's review/verification appendix.

### Rollout and rollback

Promote the syntax contract before code. Land the shared syntax and provider
contract in a backward-compatible form first. Then land TUI support behind the
existing optional `taut-tui` distribution. A TUI release without a syntax
provider remains usable with the grouped native action browser; a missing or
broken optional provider affects only that provider's mirror entries.

Rollback is a package-level revert in reverse dependency order: remove TUI
bindings, then remove extension provider registration, then remove shared
syntax only after CLI adapters are restored to their prior parser path. Do not
remove a syntax contract while an installed CLI adapter still advertises it.
If the command screen proves unsafe, the first safe fallback is to disable the
text-entry route and retain the grouped action browser; this must not alter
native action handlers or CLI behavior.

Operational success signals after release:

- `:` opens the command screen without Textual fatal errors.
- A successful typed command produces its native result or visible state
  change, with no subprocess and no terminal corruption.
- `summon` failures are reported inline and all TUI-owned workers and terminal
  leases retire normally.
- Unsupported command diagnostics identify the exact path and do not reduce
  the available core action inventory.

## Independent review loop

Before implementation, request a read-only review from a different agent family
than the author, preferably Claude Opus or Grok if the repository inventory
shows them review-eligible. The reviewer must read:

- this plan, especially `## Proposed Spec Delta`,
- [TAUT-8.1], [TAUT-8.6], [TAUT-12.4], [SUM-13], and [TUI-2.1], [TUI-7.1],
  [TUI-10.3], [TUI-11],
- `taut/commands/_protocol.py`, `_registry.py`, `_dispatch.py`,
- `extensions/taut_tui/taut_tui/actions.py`, `screens.py`, `app.py`, `domain.py`,
  `summon.py`,
- `extensions/taut_summon/taut_summon/command_manifest.py`, `controller.py`,
  and the deferred cross-surface plan.

Review prompt:

> Review this plan and its proposed spec delta as an implementation handoff.
> The requirement is a textual mirror of the Taut command language, not CLI
> invocation or raw argv execution. Look for grammar drift, wrong ownership,
> accidental generic argparse-form generation, incomplete command coverage,
> extension loading hazards, Summon terminal lifecycle gaps, and performative
> abstractions. Check whether the plan preserves current CLI and TUI behavior
> while making `:summon grok` executable through native typed ownership. Return
> concrete findings with priority and exact file/spec references. Do not edit.

The author must answer every finding in this plan before the spec-promotion
slice. A finding that the shared syntax source or native binding boundary is
not implementable blocks code work until the architecture is revised and
reviewed again.

## Out of scope

- Calling `taut`, `taut-summon`, or any CLI executable from inside the TUI.
- Shell features such as pipes, redirects, command substitution, or environment
  expansion.
- A generic renderer that turns argparse or installed command manifests into
  TUI forms.
- A universal semantic capability inventory across CLI, MCP, and TUI. The
  deferred `2026-08-14-cross-surface-command-capability-plan.md` remains
  deferred.
- A third-party rich-view/widget plugin protocol.
- Changing CLI command names, parser behavior, output, exit codes, or manifest
  version 1.
- Executing `system load` inside the TUI without a separate maintenance-boundary
  plan and spec review.
- Replacing the existing TUI action registry or native form contracts.
- Changing Summon driver, PTY, control-plane, persistence, or signal ownership.

## Fresh-eyes review checklist

Before marking this plan review-ready, re-read it as a new implementer and
verify:

- every new type has an owning package and a named file boundary;
- the plan never confuses command text with `argv` or CLI process execution;
- the core syntax source cannot drift from the released CLI grammar;
- every command path has a native, CLI-only, or extension-owned disposition;
- `summon` uses the public controller and existing terminal lease;
- parsing is synchronous, execution is owned by existing workers, and results
  have a native sink;
- the spec promotion, independent review, rollback, and traceability gates are
  ordered before implementation claims;
- the plan index and implementation note are updated at the correct closeout
  slice.

## Review and verification record

Independent review on 2026-08-17 returned `BLOCKED` with eight findings. The
plan author incorporated the findings as follows:

| Finding | Disposition |
|---------|-------------|
| Shared grammar source was underspecified | Resolved in the architecture and task 3: a complete AST is canonical, including exclusive groups, intermixed parsing, and remainder tails; CLI and TUI consume it through separate surface adapters. |
| Parsed arguments could not reach native TUI handlers | Resolved in `TuiCommandBinding` and task 7: command values are explicit inputs, and an `ActionId` is reused only when its handler accepts those typed values. |
| Command coverage was asserted rather than designed | Resolved by the command binding disposition matrix and the executable coverage-matrix requirement in task 7. |
| “Anything CLI” had no explicit scope boundary | Resolved by separating full syntax recognition from native execution coverage and adding the root-global policy. `system load` remains an explicit [TUI-10.3] exception. |
| Injected syntax had no execution disposition | Resolved by stating that syntax providers make commands recognizable, while native execution requires a host binding; `taut-summon` supplies the first-party binding. Unknown providers remain syntax-only/CLI-only. |
| Root-global semantics were missing | Resolved by the root-global policy and the matching [TUI-7.1] delta. |
| Duplicate registries could drift | Resolved by deriving action-linked binding labels, groups, and order from `ActionSpec`; only non-action bindings carry their own presentation metadata. |
| The proposed TUI-14 edit targeted the wrong prohibition | Resolved: [TUI-7.1] changes; [TUI-14] remains unchanged except for its existing generic-renderer boundary. |

The review found the plan not implementable before these corrections. A
follow-up read-only review of the corrected plan is required before the
spec-promotion slice. The follow-up returned `PASS WITH RESIDUALS` and found no
architectural blocker. Its residuals are now explicit in the plan:

- `RootCommandSyntax` owns root globals, pre/post-verb placement, precedence,
  and root actions such as `--help` and `--version`.
- `say` and `reply` stdin/omitted-text forms are syntax-recognized but CLI-only
  in the TUI; explicit text is native.
- The TUI command dispatcher receives typed values and applies closed session
  policy before dispatch, so explicit targets do not silently fall back to
  visual selection; confirmation remains exact-target and owner-specific.
- The full syntax-recognition guarantee covers core commands and installed
  syntax providers. Missing optional Summon syntax is reported as unavailable,
  not treated as a core command.

## Implementation verification appendix

Implementation evidence for the 2026-08-17 slice:

- `uv run pytest -q -n 0 extensions/taut_tui/tests` — passed.
- `uv run pytest -q -n 0 extensions/taut_summon/tests` — passed; two documented
  live lanes skipped because the local `kimi` binary and Ollama model were not
  available.
- `uv run pytest -q -n 0 tests/test_command_syntax.py tests/test_cli.py tests/test_cli_probes.py` — passed; the documented Windows filename case was skipped.
- `uv run pytest -q -n 0 tests/test_architecture_boundaries.py tests/test_command_registry.py tests/test_ruff_policy.py` — passed.
- `uv run ruff check taut extensions/taut_tui/taut_tui extensions/taut_tui/tests extensions/taut_summon/taut_summon extensions/taut_summon/tests tests/test_command_syntax.py` — passed.
- `uv run mypy extensions/taut_tui/taut_tui` and
  `uv run mypy extensions/taut_summon/taut_summon` — passed.
- `uv build --project extensions/taut_summon --out-dir /tmp/taut-summon-build-check` — passed; the wheel contains the `taut.command_syntax` entry point.
- `bin/check-plan-status-index`, `uv run bin/check-doc-paths`, and
  `uv run bin/check-cli-claims` — passed.

The repository-wide `uv run pytest -q -n 0 tests` run has one unrelated
environment-sensitive failure: the release test intentionally refuses the
publishing path on `codex/windows-ci-diagnostics` and requires `main` or
`master`. The full run also caught three expected-contract updates for the new
syntax public surface and grouped headings; those were corrected and their
targeted suites pass.

The remaining architectural residual is deliberate: existing CLI
`configure_parser()` adapters remain the compatibility owner for exact CLI help,
usage errors, and exit behavior. The shared AST/parser is the mirror grammar
owner in this slice. An AST-to-argparse migration needs its own compatibility
matrix and should land separately.

The plan was approved by the owner on 2026-08-17. The promotion SHA is
`9888b38ceb4de509fad153c1b2970d4ca2832bb3`. The implementation slice is
complete and committed, with the CLI-adapter migration residual recorded in
the deviation log and verification appendix below.
