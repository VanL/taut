# Lazy Command Extensions and Rich TUI Composition Plan

Date: 2026-07-12

Status: implementation and Task 13 verification were performed as uncommitted
work on 2026-07-13. The promoted specs, code, packaging, release gates, and current
documentation are aligned. This work is not called ready to land because the
user has not authorized the commit required by the repository completion gate;
no release, tag, push, or publication is authorized by this plan.

Plan type: implementation with spec revision.

Owner: the implementing engineer owns the spec-promotion slice, command
registry, built-in command migration, Summon embedding extraction, verification,
and documentation reconciliation. A separate future TUI plan owns product UX,
screen layout, framework selection, and managed-driver survival policy.

## 1. Goal

Replace Taut's hard-coded top-level CLI registration and Summon-specific
delegation with one versioned command-module interface. Built-in commands use
static registration; separately installed packages use standard Python entry
points. Discovery and help remain lightweight, and only the selected command
imports its implementation and initializes its subsystems.

At the same time, extract a public, typed Summon controller and host-interaction
interface so the CLI and a future rich first-party TUI can share Summon's real
behavior without the TUI parsing CLI output or reaching into Summon's private
ledger, control queues, driver, or PTY machinery. The TUI is deliberately a
composition root that may understand first-party capability models. It is not a
generic renderer over command metadata.

## 2. Requested Outcomes

- One public command interface governs every top-level `taut` verb.
- Core commands and installed extension commands have the same descriptor and
  adapter shape, while packaging remains independent from code organization.
- Built-ins are registered statically and cannot disappear because distribution
  metadata is absent in a source checkout.
- Installed commands are discovered through the standard-library
  `importlib.metadata` `taut.commands` entry-point group.
- Installing a compatible package makes its command visible to the next `taut`
  process without editing core.
- `taut summon` and `taut dismiss` are supplied by `taut-summon` entry points;
  core contains no permanent Summon dispatcher.
- The existing `taut-summon run|stop|status` executable remains supported and
  calls the same public Summon controller as the `taut` adapters.
- `taut --version` loads constants only. `taut --help` loads registry metadata
  and lightweight command manifests, not command implementations, storage,
  watchers, Summon drivers, provider adapters, PTY code, or a TUI.
- `taut COMMAND --help` may load that command's parser adapter but not its
  client/controller/driver/provider runtime.
- `taut say` loads the messaging/client/state path but not watcher, Summon, PTY,
  or TUI modules. Other commands load only the subsystems they use.
- `import taut` and `import taut_summon` do not eagerly import their heavy public
  exports. Accessing a public export loads its owning module on demand without
  changing the typed public surface.
- A public Summon controller owns `run_foreground`, `list_live`, `status`, and
  `stop` semantics. Command adapters render results; the controller does not
  print or return CLI exit codes.
- Summon receives terminal/onboarding behavior through a public interaction
  interface. The shell adapter preserves today's attach/detach behavior. A
  future TUI adapter may suspend/redraw its terminal around the same interface.
- The future first-party TUI may depend directly on public core and Summon
  interfaces and provide rich capability-specific screens. It must not depend on
  private modules or treat argparse metadata as a universal UI schema.
- Existing CLI grammar, output, exit classes, identity semantics, message
  semantics, watcher behavior, Summon lifecycle, storage schemas, and control
  protocol remain unchanged unless the exact proposed spec delta below says
  otherwise.

## 3. Source Documents

Source specs:

- `docs/specs/02-taut-core.md` [TAUT-8.1], [TAUT-8.2], [TAUT-8.3],
  [TAUT-8.4], [TAUT-8.5], [TAUT-12.3], [TAUT-12.4], [TAUT-12.5]
- `docs/specs/04-summon.md` [SUM-2], [SUM-3], [SUM-4], [SUM-6], [SUM-7.1],
  [SUM-7.4], [SUM-8], [SUM-9], [SUM-11], [SUM-12]
- `docs/specs/01-development-documentation-operating-model.md` [DOM-4],
  [DOM-5], [DOM-6], [DOM-8], [DOM-10], [DOM-11]

Implementation rationale and repository context:

- `docs/implementation/02-repository-map.md`
- `docs/implementation/04-taut-architecture.md`
- `docs/implementation/05-taut-summon-architecture.md`
- `docs/plans/2026-07-06-taut-summon-plan.md`
- `docs/plans/2026-07-10-taut-summon-quality-remediation-plan.md`
- `docs/plans/2026-07-11-multi-factor-review-remediation-plan.md`
- `docs/plans/2026-07-12-automatic-display-name-capitalization-plan.md`

Required process guidance:

- `AGENTS.md`
- `docs/agent-context/decision-hierarchy.md`
- `docs/agent-context/engineering-principles.md`, especially sections 1, 6,
  7, 10, 11, 12, 13, and 14
- `docs/agent-context/runbooks/writing-plans.md`
- `docs/agent-context/runbooks/hardening-plans.md`
- `docs/agent-context/runbooks/testing-patterns.md`
- `docs/agent-context/runbooks/adversarial-acceptance-probes.md`
- `docs/agent-context/runbooks/maintaining-traceability.md`
- `docs/lessons.md`

No external dependency is approved by this plan. `argparse`,
`importlib`, and `importlib.metadata` are in Python 3.11's standard library.

## 4. Spec Baseline

- `b03709452cf4d5962b0d7204b0dab78b9bafd524` is the committed baseline for
  `docs/specs/02-taut-core.md`, `docs/specs/04-summon.md`, the implementation
  notes, manifests, code, and tests when this plan was authored.
- The worktree was clean at plan start (`main...origin/main`).
- This plan revises intended behavior. The baseline specs govern until the
  spec-promotion slice applies the reviewed delta.
- Promotion strategy: **A, active requirement text before implementation-link
  claims**. The first implementation slice edits the existing active spec files
  and adds their Related Plans backlinks, but does not claim code mappings that
  do not yet exist. Later code slices add reciprocal mappings together. Do not
  reclassify either active spec file.
- Promotion baseline: committed baseline `b0370945` plus the uncommitted
  2026-07-13 Task 1 diff limited to `docs/specs/02-taut-core.md` and
  `docs/specs/04-summon.md`, inspectable with
  `git diff b0370945 -- docs/specs/02-taut-core.md docs/specs/04-summon.md`.

## 5. Scope Decision

This plan does **not** build a TUI. There is no accepted TUI product spec,
framework choice, screen model, driver-survival policy, or terminal/process
handoff protocol in the repository. Inventing those here would move materially
away from the command-extension and code-organization decision.

This plan does make the approved preparation:

1. record in [TAUT-12.4] that a future first-party TUI is a rich composition
   root, not a generic command renderer;
2. keep command discovery usable by a future `taut-tui` distribution;
3. extract public Summon models and a controller for non-CLI callers;
4. inject terminal/onboarding interaction so a future TUI can provide terminal
   suspension and restoration without Summon importing TUI code; and
5. document that `run_foreground` remains blocking and process-owning. A future
   TUI plan must choose and prove managed child-process ownership before it can
   start a long-lived driver without blocking its render loop.

Stop and return to the user if implementation cannot deliver these preparation
steps without defining TUI product behavior or adding a background/daemon
lifecycle. Do not quietly add `taut-tui`, a TUI framework, an ATTACH control
verb, fd-passing IPC, or driver orphaning to make a demo work.

## 6. Current Context and Key Files

### 6.1 Core command path today

- `taut/cli.py` is a 1,000-line argparse tree plus every CLI handler, shared
  renderer, exit-code mapping, global-option hoister, and the special
  `_DELEGATED_VERBS` path for `summon`/`dismiss`.
- `taut/cli.py::main` finds a command before parsing. Summon/dismiss split raw
  argv before argparse so extension-looking options and literal `--` survive
  verbatim. Every other command uses `_hoist_global_options`.
- `taut/cli.py::_client` creates `TautClient`. Command semantics belong to
  `taut.client.TautClient`; adapters must not reimplement them.
- `taut/__init__.py` eagerly imports `TautClient`, `TautWatcher`, models, and
  exceptions. Because Python executes package `__init__` before
  `taut.cli:main`, even `taut --version` currently imports client, watcher, and
  SimpleBroker.
- `pyproject.toml` registers only the `taut` console script. It has no Taut
  command entry-point group yet.

### 6.2 Core client and rendering ownership

- `taut/client/` is the public domain interface. The concern files are mixins
  over one cohesive client, not independently swappable modules.
- `taut/cli.py` owns shared output helpers for messages, members, threads,
  notifications, JSON, human formatting, stdin, and error classification.
  Extract those helpers once into a shared command-rendering module. Do not
  copy them into every command adapter.
- `taut/watcher.py` is intentionally imported lazily by
  `TautClient.watch()`. Preserve that behavior; ordinary commands must not
  import watcher merely because `TautWatcher` is a root export.

### 6.3 Summon command and runtime path today

- `taut/cli.py::_delegate_to_summon` imports `taut_summon.cli:main` in-process
  and maps `summon -> run`, `dismiss -> stop`.
- `extensions/taut_summon/taut_summon/cli.py` owns both argparse and domain
  orchestration for run/status/stop. It reaches `_state`, `ControlClient`, and
  `run_driver` directly and prints results itself. `ControlClient` and the
  `_state` symbols are eager module-top imports; the `_driver` import inside
  `_cmd_run` is already lazy, so the lazy-import work targets the control/state
  imports, not the driver import.
- `RunRequest` currently lives in `taut_summon.cli`, while `_driver.py` imports
  it only for typing. Move request/result models out of the CLI layer before
  adding a public controller; do not create a controller/CLI import cycle.
- `extensions/taut_summon/taut_summon/_driver.py::SummonDriver` is the cohesive
  live state machine for bootstrap, generations, event pump, watcher, control
  thread, and release. Keep it cohesive. The controller wraps it; it does not
  split the generation machine by file size.
- `_driver.py::_attach_if_needed` currently reads `sys.stdin.isatty()` and
  `TAUT_HOST_TUI` directly, then calls `AdapterHandle.attach` with implicit
  fd 0/1. Move host-policy decisions behind an injected interaction adapter,
  but keep the PTY bridge and fd lifecycle in `_pty.py`.
- `taut_summon/__init__.py` eagerly imports adapter types and
  `ScriptedAdapter`. Make public exports lazy without changing `__all__` or
  typing.
- `extensions/taut_summon/pyproject.toml` registers only the
  `taut-summon` console script. Add `taut.commands` entries here.

### 6.4 Extension and release coupling

- `taut-pg` extends SimpleBroker below Taut and is not a Taut command provider.
  Do not route backend discovery through the new command registry.
- Core and Summon form a paired release boundary because Summon subclasses
  core `BaseReactor`. The command interface adds another compatibility
  contract but does not remove reactor coupling.
- `bin/build-and-check-release-wheels.py` and
  `bin/check-core-summon-wheel-matrix.py` own installed-wheel compatibility.
  Extend those proofs rather than adding a second wheel-matrix checker.
- `bin/release.py` owns root/Summon test, lint, type, build, lock, and paired
  artifact gates. Update its path/compatibility assertions only when the new
  files require it; do not invent a second release path.

### 6.5 Required reading comprehension gate

Before editing, the implementer must answer these in the plan execution log:

1. Why can root help use a command manifest but not import a command
   implementation? What modules must remain absent after `taut --help`?
2. Why must built-ins use static registration even though installed commands
   use entry points?
3. How does current raw-tail parsing preserve `taut summon ... -- --token`,
   and how will the replacement preserve it without a Summon-specific branch
   in `taut.cli.main`?
4. Why is `rejoin --token` command-local after the verb while `--token rejoin`
   is a root selector, and what test proves both?
5. Why must the TUI call a public Summon controller rather than invoke
   `taut-summon status` and parse stdout?
6. Which module owns PTY fd epochs, write leases, attach/detach, and terminal
   reset? Why must the controller and interaction adapter not duplicate it?
7. Why is `SummonController.run_foreground` explicitly blocking, and which
   future decision is still required before a TUI may launch it without
   blocking?

If any answer is uncertain, read the cited code and tests before writing a
failing test. Do not infer from filenames.

## 7. Proposed Module Interfaces

These shapes are plan constraints, not copy-paste mandates. Names may change
only if the deviation log explains why the resulting interface is smaller or
clearer without changing the contract.

### 7.1 Lightweight command manifest

Public location: `taut.commands`.

```python
@dataclass(frozen=True, slots=True)
class CommandSpec:
    command_api_version: int
    name: str
    summary: str
    post_verb_globals: frozenset[GlobalOption]
    implementation: str
```

Rules:

- `name` matches `[a-z][a-z0-9-]*` and equals the entry-point name.
- `summary` is non-empty root-help text.
- `implementation` is an import string loaded only after selecting the verb.
  It has `module.path:attribute` form and resolves to a zero-argument factory
  returning one fresh `Command`. It is never a class guessed and instantiated
  by convention, and never a shared command singleton.
- `command_api_version` is exactly `1` for this plan.
- `post_verb_globals` uses a closed enum owned by core: `DB`, `AS`, `TOKEN`,
  `JSON`, `TIMESTAMPS`, and `QUIET`. It says which root-global spellings the
  dispatcher may consume after this verb; pre-verb root options remain accepted
  exactly as today and are available on `CommandContext`. Every enum member has
  a firing test and changes parsing or rendering; do not add speculative flags.
- Each enum member covers every spelling the current hoister accepts
  (`taut/cli.py::_hoist_global_options`), not only the long space-separated
  form: `DB` covers `--db PATH` and `--db=PATH`; `AS` covers `--as NAME` and
  `--as=NAME`; `TOKEN` covers `--token TOKEN` and `--token=TOKEN`;
  `TIMESTAMPS` covers `-t` and `--timestamps`; `QUIET` covers `-q` and
  `--quiet`; `JSON` covers `--json`. A declared member consumes all of its
  spellings post-verb; an undeclared member consumes none of them. Firing
  tests must exercise the `=`-joined and short spellings, not only the long
  forms.
- Built-ins declare the current hoisting set. In particular, `rejoin` omits
  `TOKEN` so `rejoin --token` stays command-local. `summon` and `dismiss` declare
  only `DB`; other option-like tail tokens remain extension arguments verbatim.
- Manifests contain no callable that imports client, state, watcher, driver,
  provider, PTY, or TUI modules at construction time.
- An entry point's loaded attribute is the `CommandSpec` object itself, not a
  manifest factory. Loading that object may execute its lightweight manifest
  module but must not resolve `implementation`.

### 7.2 Command adapter

```python
class Command(Protocol):
    def configure_parser(self, parser: CommandArgumentParser) -> None: ...
    def run(self, context: CommandContext,
            args: argparse.Namespace) -> int: ...

CommandFactory = Callable[[], Command]
```

Rules:

- Core constructs one fresh public `CommandArgumentParser` with
  `prog="taut <name>"`, exit-1 usage errors, help, and only the manifest's
  declared post-verb globals. `configure_parser()` adds command-local
  positionals/options and may set description/epilog. It must not replace the
  parser, its `error()` behavior, or its global option actions.
- A command that owns nested syntax, currently only `set`, uses the same public
  `CommandArgumentParser` as its `parser_class`. Extension code never imports a
  private core parser.
- `configure_parser()` is side-effect free with respect to storage, processes,
  threads, signals, terminal modes, and network access.
- Command adapter modules are approved lazy subsystem seams: keep domain types
  under `TYPE_CHECKING`, use `CommandContext.client()` for core behavior, and
  import an extension controller inside `run()` when selection reaches actual
  execution. Do not copy local imports deeper into domain functions.
- `run()` is invoked exactly once after successful parsing.
- Return values are restricted to `0`, `1`, or `2`. An invalid value is a
  command programming error rendered as exit 1 with no traceback.
- Domain exceptions travel through the existing core error classifier.
  Extension adapters translate extension-specific errors into a public
  `CommandError(message, exit_code)` rather than printing inside domain code.
  `exit_code` is restricted to 1 or 2; an error cannot claim success.
- `CommandContext` owns root option values and streams. Its `client()` method
  lazily creates one core-owned `TautClient` and the dispatcher closes it.
  Commands with special long-lived ownership, including Summon, may ignore
  `client()` and use their owning public controller.
- `CommandContext` fields are exactly `db_path`, `as_name`, `auth_token`,
  `json`, `timestamps`, `quiet`, `stdin`, `stdout`, and `stderr`. The dispatcher
  merges pre/post-verb global values before construction; adapters read globals
  only from the context, not accidental argparse namespace attributes.
- Context streams are authoritative, not placeholders. Extracted stdin and
  rendering helpers read/write only through `context.stdin`, `context.stdout`,
  and `context.stderr`; command modules do not call `input()`, `print()`, or
  `sys.stdin`/`sys.stdout`/`sys.stderr` directly. The dispatcher supplies the
  process streams by default and routes root/command help, usage errors,
  registry diagnostics, and cleanup diagnostics through the same injected
  streams before a command context exists.
- The dispatcher extracts global destinations from the parsed namespace before
  `run()`, so the remaining namespace contains command-local fields only.

### 7.3 Registry and dispatch

The registry implementation is internal to core. Its observable contract is:

1. enumerate static built-in `CommandSpec` objects;
2. enumerate `importlib.metadata.entry_points(group="taut.commands")` without
   loading command implementations;
3. validate names, provenance, manifest version, and conflicts;
4. sort independently of metadata/install order, then build one immutable
   process-local snapshot: core verbs retain the [TAUT-8.1] table order,
   reserved first-party slots retain their table positions, and other external
   names sort by canonical command name then normalized distribution name;
5. locate the verb as the first token not consumed by a recognized root option,
   rejecting an unknown option before it; if literal `--` occurs first, the
   next token is still the verb positional but root option parsing/hoisting is
   disabled for every later token; preserve a separator in the tail handed to
   the command parser so every later token remains positional rather than
   resuming command-option parsing;
6. parse the pre-verb root options;
7. resolve the selected implementation target, call its zero-argument factory
   once, and have that command configure one core-created parser;
8. hoist only the selected manifest's `post_verb_globals`, then let the
   selected standalone parser parse the untouched remaining command tail; and
9. merge options deterministically: a value option after the verb wins over
   the same root option before the verb, matching textual order. Boolean flags
   combine as logical OR: a flag set pre-verb remains set even when the
   post-verb parse never sees it. Because the pre-verb and post-verb tokens now
   pass through two separate parses, the implementation must distinguish
   "explicitly set" from "parser default" (for example via `argparse.SUPPRESS`
   or sentinel defaults); a post-verb parser default must never overwrite an
   explicit pre-verb value. Each of these merge behaviors has a named firing
   test.

Version 1 supports top-level commands only. Nested subcommands such as
`set name` remain entirely owned by their top-level command. Do not add aliases,
priority, cross-package namespace merging, dependency graphs, capability
negotiation, hot reload, or command override policy.

Conflict/error rules:

- Built-in names are reserved. An external claim on a built-in name is
  unavailable and cannot replace the built-in.
- `summon` and `dismiss` are not built-ins. They are two explicit first-party
  extension slots reserved to the normalized distribution name `taut-summon`.
  A unique compatible entry point from that distribution owns the slot. If it
  is absent, core supplies the narrow 0.5.4 compatibility/install-hint adapter.
  A claimant from any other distribution is ignored with an unavailable-owner
  warning and cannot suppress the official provider or compatibility adapter.
  Two official claims, or one broken/incompatible official claim, make the slot
  unavailable; the registry must not fall back to legacy code and hide the bad
  new installation.
- Two external distributions claiming one name make only that name
  unavailable. Invoking it exits 1 and names both distributions and entry
  points. Unrelated built-ins continue working.
- A selected manifest or implementation import failure exits 1 with package,
  entry-point, and import-target context and no traceback.
- Root help lists unavailable external commands with a concise warning but
  still exits 0. A broken unrelated extension never bricks root help or a
  built-in invocation.
- No install-order or last-wins behavior is permitted.
- Discovery executes trusted installed Python manifest code. This is an
  extensibility seam, not a sandbox or authorization boundary.

### 7.4 Summon embedding interface

Public location: `taut_summon`, implemented in concern-specific public modules
without exposing private state helpers.

```python
class SummonController:
    def __init__(self, *, db_path: str | Path | None = None) -> None: ...
    def provider_names(self) -> tuple[str, ...]: ...
    def list_live(self) -> tuple[SummonedMember, ...]: ...
    def status(self, name: str) -> SummonStatus: ...
    def stop(self, name: str) -> StopResult: ...
    def run_foreground(self, request: SummonRequest,
                       interaction: SummonInteraction) -> None: ...
```

Rules:

- The controller is bound to one optional database path. Each finite operation
  opens and closes its own core client. `run_foreground` transfers the same
  path into the one driver lifecycle; the controller does not retain a mutable
  client between calls. The path is keyword-only and accepts `pathlib.Path`,
  matching `TautClient` and preventing an unlabeled constructor string.
- `SummonRequest` is the current immutable `RunRequest` minus `db_path`: `name`,
  `threads`, `terminal`, `persona`, `system_prompt_file`, `rate_limit`,
  `attach`, `detach`, `provider_flag`, and `takeover`, with the same defaults
  and collision meaning.
- `provider_names()` returns the sorted registered names without constructing
  provider adapters. It is intentionally not a capability registry.
- The controller owns name/session resolution, control client calls, and
  translation from private rows/replies into typed public results.
- `SummonedMember` has exactly `member_id`, `name`, `provider`, and
  `provider_session_id`. `list_live()` returns only rows whose existing
  evidence classifier is not dead; no database or no live rows returns `()`.
  The CLI supplies the literal `live` label and maps that empty tuple to exit 2.
- `SummonStatus` has exactly `member_id`, `name`, `driver`, `provider`,
  `provider_session_id`, `thread_count`, `cursor_lag`, and `details`.
  `cursor_lag` is a new mapping of thread name to integer lag. `details` is a
  new mapping of remaining validated JSON primitive status fields, including
  health/rate/provider-specific fields; reserved fields cannot be repeated
  there. Both mappings are defensive copies with no shared driver/control
  state. Do not add deep-freezing machinery merely to make a frozen dataclass's
  nested values physically immutable.
- `StopResult` has exactly `member_id` and `name`. It is returned only after
  the existing ACK plus evidence-relative release confirmation.
- Public results contain domain values, not rendered columns or CLI exit
  codes. They must not expose `Queue`, `SidecarSession`, table rows, control
  queue names, control request/reply dictionaries, or mutable driver internals.
- Public errors are a small typed hierarchy with `NothingSummoned`,
  `DriverUnresponsive`, and `SummonOperationError`. These are domain classes,
  not embedded exit codes. CLI adapters map `NothingSummoned` to 2 and the
  other two to 1 while preserving the current messages.
- `run_foreground` is blocking and owns one driver process lifecycle exactly as
  today's `taut-summon run`. Clean completion returns `None`; failure raises a
  typed Summon error. It does not create a daemon or silently detach.
- `status` keeps the current live-control truth rule. A ledger row alone is not
  live STATUS. `stop` succeeds only after correlated ACK and evidence-relative
  release confirmation.
- The CLI and future TUI are adapters over this controller. Neither reimplements
  session resolution, evidence classification, or control correlation.

### 7.5 Summon host interaction

```python
class TerminalIntent(Enum):
    REQUIRED = "required"
    PREFERRED = "preferred"

class TerminalAvailability(Enum):
    AVAILABLE = "available"
    NO_TTY = "no-tty"
    NESTED_HOST = "nested-host"
    UNAVAILABLE = "unavailable"

@dataclass(frozen=True, slots=True)
class TerminalLease:
    input_fd: int
    output_fd: int

class SummonInteraction(Protocol):
    def terminal_availability(
        self, intent: TerminalIntent
    ) -> TerminalAvailability: ...
    def terminal_lease(self) -> ContextManager[TerminalLease]: ...
```

This two-phase shape is deliberate. Availability is resolved and cached before
the driver decides whether an early event pump is needed; the lease is entered
only at the actual attach transition, so a TUI is not suspended through provider
bootstrap. Do not merge the methods unless the replacement preserves both
timing properties and is recorded in the deviation log.

Ownership rules:

- `ShellSummonInteraction` owns stdin tty detection and the fd 0/1 grant. It
  maps a missing stdin tty to `NO_TTY` before considering the nested marker,
  maps `TAUT_HOST_TUI=1` to `NESTED_HOST` only when stdin is a tty, permits
  redirected stdout as the current shell path does, and supplies a no-op lease
  over fds 0/1 only for `AVAILABLE`.
- A future TUI interaction owns pausing rendering, restoring its terminal,
  granting terminal fds, resuming its input mode, and redraw when its lease
  exits.
- `_pty.py` continues to own harness PTY bytes, query replies, detach chord,
  harness-master fd/write leases, reset blast, child signals, and reap. The
  interaction lease covers only the host's human input/output fds.
- The driver owns eligibility (`first_generation`, `wired`, provider attach
  support, `--attach`, and `--detach`), when attach occurs relative to
  spawn/rejoin/pump/watcher, and the single cached availability result. For an
  attach-capable provider, it samples availability once before the early-pump
  decision unless `--detach` bypasses interaction entirely. `AVAILABLE` defers
  the pump until bootstrap decides whether attach is eligible. Preserve the
  baseline early-pump matrix: forced detach and `NESTED_HOST` start it early;
  `NO_TTY` follows today's delayed path. Treat the new generic `UNAVAILABLE`
  like a host refusal and start it early. Later, unavailable
  `REQUIRED` maps to the current reason-specific error; unavailable `PREFERRED`
  maps to the current reason-specific detached warning. The lease is entered
  only when first-generation/wired policy actually selects attach.
- Generic `UNAVAILABLE` required attach raises `--attach requires an available
  terminal`. Its preferred warning says the provider is not wired because the
  host terminal is unavailable and includes the member-specific follow-up
  `taut summon --attach` instruction.
- The driver, not the interaction, calls `AdapterHandle.attach` with lease fds,
  wake, and shutdown. The interaction never receives or closes the provider
  handle and cannot read or write Summon state.
- `AdapterHandle.attach` returns the existing finite result set (`detached`,
  `eof`, or `shutdown`). Replace its internal magic-string type with an enum if
  needed for safe driver branching, but do not export that internal result
  through the interaction interface. The driver alone applies it to `wired`
  and shutdown state.
- Failure to acquire or restore a granted terminal lease is fatal. There is no
  generic progress/event callback in v1; add one only for a concrete second
  consumer and its failure policy.

## 8. Invariants and Constraints

### 8.1 Command and CLI invariants

- Every current [TAUT-8.1] grammar and exit code remains unchanged.
- Root options remain valid before every verb and after a verb only where its
  `post_verb_globals` declares that spelling, matching current built-in,
  `rejoin`, Summon, and dismiss behavior. A literal `--` after the verb stops
  hoisting and makes every later token command-local/positional. A literal `--`
  before the verb still allows the next positional to select the verb, matching
  argparse today, but disables global interpretation for the complete command
  tail. The dispatcher preserves the separator for the command parser in both
  positions; later tokens remain positional and do not resume command-option
  parsing. With no token after it, root help goes to stderr with exit 1.
- `rejoin --token` remains command-local; a pre-verb `--token` remains global.
- Summon/dismiss command tails keep option-looking tokens and `--` behavior.
- Successful JSON shapes and human/stdout/stderr separation remain unchanged.
- No command adapter contains domain persistence, identity, message, watcher,
  or Summon lifecycle logic.
- Shared rendering and stdin helpers have one owner. Do not duplicate them per
  command to make the directory look symmetrical.
- Do not split cohesive client mixins, watcher, driver, control, state, stream,
  or PTY implementations by verb or file size.

### 8.2 Lazy import and initialization invariants

- Lazy loading is allowed only at package/subsystem seams. Do not scatter
  function-local imports through cohesive implementation modules merely to
  reduce `sys.modules` counts.
- `taut --version` must not enumerate external entry points.
- `taut --help` may load lightweight external manifest modules but no command
  implementation target.
- `taut COMMAND --help` may load/configure its command target but must not load
  that command's client/controller/driver/provider runtime.
- `taut-summon --help` and each standalone subcommand help path obey the same
  rule; the standalone parser cannot remain an eager control/state importer.
- Importing an unavailable optional command does not occur during unrelated
  commands.
- Lazy root exports preserve `from taut import TautClient`,
  `from taut import TautWatcher`, `from taut_summon import ScriptedAdapter`,
  `__all__`, `py.typed`, mypy behavior, and unknown-attribute `AttributeError`.
- Import failure moves to first use and must retain the original exception as
  cause while producing an actionable public diagnostic at CLI surfaces.
- No subsystem starts a process, thread, database connection, watcher, signal
  handler, or terminal mode at import or manifest-discovery time.

### 8.3 Summon invariants

- No storage schema, claim key, session row, control command, reply shape,
  generation fence, provider protocol, injection format, cursor behavior, or
  rate audit changes in this plan.
- The controller is a relocation of orchestration and translation, not a
  second state/control implementation.
- Broker, sidecar, control, driver, and PTY behavior remain real in integration
  tests. Do not replace them with mocks to make controller tests easy.
- `SummonDriver` remains the owner of live generation and shutdown state.
- `BaseReactor` coupling and paired release verification remain unchanged.
- Shell attach/no-tty/`TAUT_HOST_TUI` behavior stays byte- and exit-compatible.
- The future TUI may know Summon domain models, but it may not import modules
  whose names begin with `_`, inspect tables, or synthesize control JSON.

### 8.4 Dependency and YAGNI constraints

- No new third-party runtime or development dependency.
- Do not add pluggy, click, typer, importlib-metadata backport, a DI container,
  a service locator, or a universal extension manifest.
- Do not add a provider-adapter entry-point group in this plan. That is a real
  separate seam but needs its own spec and compatibility work.
- Do not add dynamic methods to `TautClient`.
- Do not make argparse a TUI form schema.
- Do not build a TUI contribution registry until a second rich UI contribution
  exists.
- Do not implement cross-package nested commands, command aliases, overrides,
  priorities, dependency solving, hot reload, or remote plugins.

### 8.5 Code style and edit discipline

- Python 3.11 is the syntax floor. Do not use newer parser/runtime features.
- Use existing dataclass, Protocol, typed-dict/result-model, and exception
  styles. Every public function and method is fully typed.
- Use absolute imports as the codebase does. Keep `from __future__ import
  annotations` at module tops.
- Formatter/linter authority is Ruff, line length 88. Do not hand-reflow
  unrelated code or perform formatting-only cleanup in behavior slices.
- TDD is red-green. Every behavior task begins with the named failing test,
  records the red failure, then makes the smallest implementation pass.
- DRY means reuse the existing client, renderers, error classifier, controller,
  driver, and PTY paths. It does not mean inventing a generic abstraction before
  two real behaviors vary.
- Preserve user work in a dirty tree. Stop if intended files have overlapping
  unexplained edits.

### 8.6 Fatal versus best-effort failures

Fatal, exit 1 at the selected command surface:

- selected command manifest/implementation missing or incompatible;
- invoked-name conflict;
- invalid command return value;
- parser usage error;
- failure to construct/restore a required terminal interaction;
- existing domain/storage/controller fatal errors.

Best-effort or isolated:

- an unrelated external command fails to load;
- root help cannot obtain one external summary;
- optional provenance display is unavailable.

Best-effort failures must remain visible as warnings or unavailable-command
records. They must never silently change command selection.

## 9. Rollout, Compatibility, and Rollback

Write and preserve compatibility before removing the hard-coded path.

### 9.1 Supported artifact combinations

The installed-artifact proof must cover:

1. new core 0.6.0 alone: built-ins work; `taut summon` gives the current install hint;
2. new core + immediately previous published Summon 0.5.4: legacy Summon
   delegation still works through a registry-owned compatibility adapter
   without eager import;
3. core 0.6.0 + Summon 0.6.0: entry-point commands win; no legacy path executes;
4. immediately previous core 0.5.4 + release-version new Summon: dependency
   resolution rejects the combination after the release operator synchronizes
   the new Summon `taut>=<new-core-version>` floor;
5. new core + synthetic third-party command wheel: install makes the verb
   available, uninstall removes it on the next process;
6. duplicate/broken/incompatible synthetic command wheels: affected verb fails
   cleanly while built-ins remain usable.

The existing wheel-matrix checker intentionally retains a separate older reactor
compatibility floor (`v0.5.0` at this plan's baseline). Do not silently replace
that case. Add the 0.5.4 command-rollout case beside it, or update the retained
floor only through the release policy that owns that decision.

The legacy Summon adapter is explicitly temporary and registry-owned. It may
recognize only `summon` and `dismiss`, may not become a generic fallback reader,
and must carry a removal condition in code and this plan's execution record:
remove it only after the immediately previous published Summon release already
contains `taut.commands` entry points and the installed-artifact compatibility
policy no longer promises 0.5.4 support. Do not remove it in this plan.

### 9.2 Release order

- Core and Summon remain a paired release.
- Publish/install the new core first; its legacy adapter keeps Summon 0.5.4
  working.
- Publish/install the new Summon second with its `taut>=<new-version>` floor.
- The new Summon entry points then replace the compatibility adapter.
- A future `taut-tui` release is out of scope and requires its own spec/plan.

### 9.3 Rollback

- No storage migration or destructive operation exists, so rollback is package
  rollback.
- Before the new Summon is installed, rolling core back restores the original
  hard-coded delegation.
- After both are installed, roll Summon back first (the new core legacy adapter
  supports it), then roll core back. Do not roll core back while leaving a new
  Summon whose dependency floor rejects it.
- If lazy root exports break an embedding import, revert the lazy-facade slice
  independently; command registry entry points do not depend on root facade
  laziness.
- If the public controller extraction regresses runtime behavior, revert its
  adapters to the prior CLI/driver path before release. Do not add dual writes,
  fallback state reads, or duplicated control clients as rollback machinery.

### 9.4 One-way doors

Publishing command interface version 1 is the only one-way compatibility door.
Hold it behind installed-wheel tests and independent review. Keep v1 minimal so
future requirements can add optional interfaces rather than break it.

## 10. Proposed Spec Delta

Promotion strategy: A, active in-file requirement text before implementation
link claims. Apply this exact text in Task 1 after independent plan review.

### 10.1 `docs/specs/02-taut-core.md` [TAUT-8.1]

Replace the sentence `Global options may appear before or after the subcommand,
but never after --.` with:

> Root globals may appear before every verb. After a verb, the dispatcher
> consumes only the root-global spellings that verb's manifest declares; this
> preserves command-local lookalikes such as `rejoin --token` and opaque
> extension tails. A literal `--` stops root option interpretation. Before a
> verb, the next positional still selects that verb but its entire tail is
> command-local; after a verb, every later token is command-local. `--version`
> is a root action before the verb. `COMMAND --help` is command help.

Replace the two `summon`/`dismiss` table rows and the delegation paragraph with:

> | `summon PROVIDER_OR_NAME [THREAD ...]` | Provided by the separately installed `taut-summon` command package through [TAUT-8.6]. Without a compatible provider, exit 1 with a one-line install hint. Behavior lives in spec 04. | per spec 04 |
> | `dismiss NAME` | Provided by the same package and command interface; maps to Summon's stop operation. | per spec 04 |
>
> Top-level verbs are command modules under [TAUT-8.6]. Core verbs and installed
> extension verbs share one interface and dispatch policy. A command adapter
> translates argv and output only; domain behavior remains on its typed owning
> interface. Installing a package may add a top-level verb, but no package may
> override a built-in or win a conflict by installation order.

Append after the help-text paragraph:

> Root help is registry-backed. It must remain usable when an unrelated
> installed command is broken or incompatible. A selected unavailable command
> exits 1 with its distribution, entry point, and compatibility failure; it
> never produces a traceback. Literal `--`, global-option placement, usage exit
> 1, and the 0/1/2 exit classes apply equally to built-in and extension command
> adapters.

### 10.2 `docs/specs/02-taut-core.md` [TAUT-8.3]

Append:

> `taut.commands` is the typed extension-author surface for command manifests,
> adapters, the command parser, command context, and command errors
> ([TAUT-8.6]). It does not dynamically add methods to `TautClient`;
> extension-specific Python behavior remains on the extension package's typed
> interface.
>
> Root package exports are lazy at subsystem seams. `import taut` does not load
> SimpleBroker, client/state, watcher, Summon, PTY, or TUI implementations.
> Accessing a documented public export loads its owner on first use while
> preserving `__all__`, `py.typed`, static typing, and ordinary
> `AttributeError` for unknown names.

### 10.3 Add `docs/specs/02-taut-core.md` [TAUT-8.6]

Insert after [TAUT-8.5]:

> ### [TAUT-8.6] Command modules, discovery, and lazy loading
>
> Every top-level `taut` verb is represented by a versioned command manifest
> and a command adapter. Built-ins are registered statically from the core
> distribution. Installed extensions register the same manifest shape through
> the standard Python entry-point group `taut.commands`; discovery uses
> `importlib.metadata` and adds no runtime dependency.
>
> A manifest contains exactly the command-interface version, canonical
> lowercase-hyphenated name, non-empty root-help summary, closed set of root
> global options that may be consumed after the verb (each option's documented
> long, `=`-joined, and short spellings travel together as one declaration),
> and a lazy implementation import target in `module:attribute` form. The
> installed entry point loads the manifest object itself. The implementation
> target resolves only after selection to a zero-argument factory returning a
> fresh command adapter. Core creates the usage-error parser; the adapter
> configures it but
> cannot replace its policy. Pre-verb root globals remain accepted for all
> commands. Interface version 1 supports top-level verbs only. Nested parsing
> remains owned by the selected top-level adapter. Version 1 has no aliases,
> override priority, cross-package nested namespace, dependency graph, or hot
> reload.
>
> Discovery produces one immutable process-local registry snapshot. Built-in
> names are reserved. Duplicate external names make only that name unavailable;
> invoking it fails with both owners named, while unrelated built-ins continue.
> Selection and root-help ordering never depend on installation order. Core and
> reserved first-party verbs retain their CLI table order; other installed
> names sort canonically. Installed command code is trusted in-process Python
> and is not a sandbox or authentication boundary.
>
> `summon` and `dismiss` are reserved first-party extension slots owned by the
> normalized `taut-summon` distribution name, not ordinary built-ins. A unique
> compatible official entry point owns each slot. When absent, core may supply
> only the previous-release compatibility/install-hint adapter required by
> [SUM-3]. An unofficial claimant cannot suppress that path. A broken,
> incompatible, or duplicate official claim is an error and never falls back to
> legacy code.
>
> Dispatch locates the verb as the first token not consumed by a recognized
> root option; an unknown option before it is a root usage error. A literal
> `--` before a verb still leaves the next positional as the verb, but disables
> root-global interpretation for its complete tail; after a verb it likewise
> stops root-global hoisting and leaves all later tokens to the command.
> Dispatch parses pre-verb globals, then loads only the selected
> command implementation and gives its standalone parser the unconsumed tail. A
> declared value option after the verb wins over the same option before the
> verb, matching textual order; a declared boolean flag combines as logical OR
> across both positions. `rejoin --token` remains command-local while a
> pre-verb `--token` remains global. The selected adapter runs exactly once and
> returns only exit class 0, 1, or 2.
>
> The execution context contains the resolved database path, acting name,
> continuity token, JSON/timestamp/quiet flags, and stdin/stdout/stderr streams.
> Its `client()` method creates at most one core `TautClient` lazily, and the
> dispatcher closes that client in `finally` without replacing a primary
> command failure. Context streams are authoritative for command input/output;
> adapters and shared renderers do not use ambient process streams directly.
> Root/command help, usage, and registry diagnostics use the same dispatcher
> streams. Extension-specific domain APIs remain on their owning package; the
> context is not a service locator.
>
> Imports and initialization are lazy by subsystem. `taut --version` does not
> enumerate entry points. `taut --help` may load lightweight manifests but no
> command implementation. `taut COMMAND --help` may load its parser adapter but
> not its client/controller/driver/provider runtime. Actual execution imports
> only the domain modules that command uses;
> import or manifest discovery never opens storage, starts a thread/process or
> watcher, installs a signal handler, or changes terminal mode. Failures move to
> first use with actionable diagnostics and preserved causes.
>
> Verification must include source-tree and installed-wheel invocation,
> built-in parity, entry-point install/uninstall, duplicate/broken/incompatible
> providers, literal/global grammar on Python 3.11, exit classes, traceback
> absence, and isolated `sys.modules` import floors for version, help, ordinary
> messaging, watcher, and extension commands.

### 10.4 Replace `docs/specs/02-taut-core.md` [TAUT-12.4]

> ### [TAUT-12.4] Rich first-party TUI
>
> The future TUI has its own product spec and ships as an optional installed
> command provider under [TAUT-8.6]. It is a first-party composition root, not a
> generic renderer over argparse or command manifests. It may present rich
> capability-specific flows and depend directly on public typed interfaces from
> core and first-party extensions such as Summon.
>
> The TUI consumes `TautClient` and `TautWatcher` for chat. For Summon it consumes
> the public [SUM-13] controller and supplies a host-interaction adapter for
> terminal suspension/restoration. It must not import private modules, inspect
> extension tables, synthesize control JSON, or duplicate driver/PTY lifecycle.
> Its own spec must choose screen behavior, framework/dependencies, managed
> child-process ownership, terminal handoff, and what happens to TUI-launched
> drivers when the TUI exits. None of those choices are implied by the command
> registry.

### 10.5 `docs/specs/04-summon.md` [SUM-3]

Make these exact bullet edits:

1. Leave the first bullet beginning `Ships as the separate extension package`
   unchanged.
2. Replace the complete second bullet beginning `Surface: core gains two`
   (including its command fence and `Core's implementation is a thin hand-off`
   continuation) with:

> - Surface: the separately installed `taut-summon` distribution registers two
>   first-party command slots through the core `taut.commands` entry-point
>   interface ([TAUT-8.6]):
>
> ```text
> taut summon PROVIDER_OR_NAME [THREAD ...] [flags]   # default thread: general
> taut dismiss NAME
> ```
>
>   Core supplies only a temporary previous-release compatibility adapter and
>   the absent-package install hint; it contains no Summon domain logic. The
>   compatibility adapter is removed after the immediately previous supported
>   Summon release supplies entry points.

3. In the third bullet beginning `The extension installs the console script`,
   replace only its opening through the phrase `so both surfaces share one
   resolution contract:` with:

> - The extension also installs `taut-summon run|stop|status`. Both console
>   surfaces are adapters over the public [SUM-13] controller. They share
>   request models, provider/name resolution, results, error semantics, and
>   tests; neither console surface invokes the other's `main()` or parses the
>   other's output. `taut summon X ...` remains behaviorally equivalent to
>   `taut-summon run X ...`, and `taut dismiss X` remains equivalent to
>   `taut-summon stop X`. Both surfaces share one resolution contract:

   Leave the remainder of that bullet, beginning `run NAME_OR_PROVIDER`,
   unchanged, including all provider-resolution, collision, capitalization,
   and default-thread rules.
4. Delete the final bullet beginning ``stop`/`status` are thin clients`; its
   guarantees are now owned by the replacement text and [SUM-13].

### 10.6 `docs/specs/04-summon.md` [SUM-7.4]

Make three exact edits. This avoids accidentally deleting the detach matcher or
startup rules that share the current paragraphs:

1. Replace only the paragraph whose bold lead is `Attach / detach.` with the
   first paragraph below.
2. Leave the current `Attach is first-generation only` paragraph unchanged.
3. In the current detach-chord paragraph, replace only its final sentence that
   begins `A single-terminal host TUI` with the second paragraph below. Append
   the third paragraph immediately after that detach-chord paragraph. Leave the
   reset blast, STOP-during-attach, fd ownership, and startup-order paragraphs
   byte-for-byte unchanged except for necessary reference links.

> **Attach / detach and host interaction.** Whether a human is bridged is
> decided by the durable `wired` flag plus a [SUM-13] host-interaction adapter,
> never by screen-readiness heuristics. On a first-ever summon of a not-wired
> member, the shell interaction reports an ordinary real tty as available and
> Summon bridges it in raw mode to the PTY master. The human answers
> trust/login/model prompts and explicitly detaches with the configured
> non-`ESC` chord, defaulting to `Ctrl-\ Ctrl-\`; only then does Summon mark the
> row wired. Summon never auto-detaches on a first run. Subsequent wired summons
> go straight to detached driver mode. No-tty runs go detached with the current
> notice and may surface `awaiting_onboarding` through log plus STATUS.
> `--attach` requires terminal availability; `--detach` forces detached mode.
>
> An uncooperative nested shell-out marked `TAUT_HOST_TUI=1` refuses attach so
> two full-screen applications never share the terminal. A cooperative future
> TUI supplies a [SUM-13] interaction adapter instead of setting that fallback
> marker for the in-process call.
>
> The interaction has a pure availability phase and a scoped terminal-lease
> phase. A cooperative TUI may report availability during bootstrap, then pause
> rendering and grant explicit input/output fds only when the lease is entered.
> Summon calls the provider attach bridge itself and owns when attach occurs,
> the harness PTY, detach result, reset bytes, driver lifecycle, and the rule
> that chat is not injected until the watcher starts after detach. The
> interaction never receives the provider handle, reads Summon state, or writes
> control messages.

### 10.7 Add `docs/specs/04-summon.md` [SUM-13]

Insert before `## Related Plans`:

> ## 13. Embedding and Rich Hosts [SUM-13]
>
> `taut_summon` exports a typed `SummonController` with provider-name discovery,
> session listing, live status, confirmed stop, and foreground-run operations,
> plus typed request/result/status models and a host-interaction interface. The
> standalone CLI, core command adapters, and future rich TUI use this controller
> rather than private ledger/control/driver modules.
>
> The controller hides extension table rows, queue handles and names, control
> JSON, evidence predicates, adapter handles, and driver mutable state. `status`
> proves a live correlated control response; a session row alone is not live
> status. `stop` succeeds only after correlated ACK and evidence-relative
> release confirmation. `run_foreground` remains blocking and owns exactly one
> foreground driver lifecycle; it never silently daemonizes or detaches.
>
> A host interaction reports terminal availability and grants a scoped lease
> containing input/output fds. Summon owns provider PTY bytes, calls the attach
> bridge itself, interprets its finite result, and owns lifecycle. Shell and
> future TUI adapters may present different experiences while using the same
> attach transition. A
> future TUI that wants a nonblocking managed driver must define process
> supervision, terminal-release handshake, log routing, exit policy, and
> rollback in its own spec; [SUM-13] does not guess those behaviors.
>
> `SummonController` is bound to one optional database path. It exposes sorted
> provider names through `provider_names()` without constructing adapters; live
> session summaries through `list_live()`; one correlated live status; one
> confirmed stop result; and a blocking foreground run that returns no value on
> clean completion. The request model contains `name`, `threads`, `terminal`,
> `persona`, `system_prompt_file`, `rate_limit`, `attach`, `detach`,
> `provider_flag`, and `takeover`; the database path belongs to the controller.
> A live summary contains member id, current name, provider, and optional
> provider session id. A stop result contains member id and current name. Status
> contains those identity/provider values plus driver, thread count, cursor lag,
> and defensive copies of remaining validated JSON-primitive detail fields;
> it never exposes a raw reply.
>
> Public controller operations return typed domain results and raise typed
> `NothingSummoned`, `DriverUnresponsive`, or `SummonOperationError`. They do
> not print, return CLI exit codes, or require callers to parse human or JSON
> output. Command adapters own rendering and map `NothingSummoned` to exit 2 and
> the other public operation errors to exit 1.

### 10.8 `docs/specs/04-summon.md` [SUM-12]

Append:

> Command/embedding verification additionally proves: both console surfaces use
> one controller; source and installed-wheel command discovery; previous-Summon
> compatibility; controller list/status/stop truth through real SQLite and real
> control queues; shell interaction parity through a real PTY child; a
> deterministic host adapter that grants explicit terminal fds and observes the
> attach transition; no private state/control access by adapters; and lazy import
> floors showing core and standalone command help do not import
> client/controller/driver/provider/PTY implementations until execution. Mocks
> may replace only metadata enumeration, clocks, or the
> external host adapter response in narrow unit tests. Broker, sidecar, CLI
> subprocess, control dispatch, driver process, and PTY remain real for contract
> proof.

### 10.9 Related Plans backlinks

Add this plan to `## Related Plans` in both touched specs. During final
traceability reconciliation, add implementation-note and code mappings only for
modules that actually exist.

## 11. Deviation Log

| Spec ref | Planned behavior | Actual behavior | Rationale | Spec proposal |
|----------|------------------|-----------------|-----------|---------------|
| [TAUT-8.5] | Add [TAUT-8.6] after the reactor section and replace [TAUT-12.4] | Also remove [TAUT-8.5]'s stale sentence that says the future TUI ships as the `taut[tui]` extra | The sentence conflicts with the promoted [TAUT-12.4] contract that the optional TUI ships as a command-provider distribution; retaining both would leave two packaging contracts | Keep TUI packaging and composition ownership solely in [TAUT-12.4] |
| [TAUT-8.6] | Make the Task 4 `say` adapter import-floor test green before Task 6 | Task 4 proves the adapter's static import ownership; Task 6 owns the clean-process `sys.modules` floor for `say` | Importing any `taut.commands` module first executes the current eager `taut.__init__`, so the runtime floor cannot pass honestly until the facade is made lazy | Keep the same final import floor, but place its executable runtime proof at the slice that removes the eager package import |
| [TAUT-8.3], [TAUT-8.6] | Task 6 touches the listed facades and accidentally eager command modules | Task 6 also touches `taut/_constants.py` | `_constants.py` imports `simplebroker.resolve_config` at module scope, so an eagerly available `__version__` would still violate the root import/version floor | Move the resolver import inside `load_config()`; keep version constants lightweight |
| [SUM-13] | The proposed sketch accepted positional `str | None` in `SummonController.__init__` | The constructor makes `db_path` keyword-only and accepts `str | pathlib.Path | None` | This matches the public `TautClient` database selector, avoids an unlabeled constructor string, and does not broaden persistence or lifecycle ownership | Promote the keyword-only path shape in section 7.4; no new controller behavior follows from accepting `Path` |
| [SUM-13] | Section 7.4 shows the final `run_foreground(request, interaction)` signature | Task 8 temporarily exposes `run_foreground(request)`; Task 9 adds the required interaction argument and shell adapter before release | Task 9 exclusively owns the interaction protocol and its driver ordering tests. A placeholder object or optional untyped parameter in Task 8 would fabricate the seam before its contract exists | Treat the one-argument signature as an unshipped intermediate state; Task 9 must replace it with the final required signature |
| [SUM-7.4], [SUM-13] | The sketch said shell stdin/stdout detection without defining overlap precedence | The shell adapter preserves the old stdin-only eligibility rule, permits redirected stdout, and reports `NO_TTY` before `NESTED_HOST` when both conditions apply | Requiring stdout to be a tty changes working redirected-output runs. Marker-first diagnostics also change the existing `--attach requires a tty` and no-tty warning. The single availability enum cannot preserve both the old combined-case diagnostic and its old early-pump timing; the user-visible diagnostic wins, so that rare combined case now follows the `NO_TTY` delayed path | Promote the exact shell precedence in [SUM-7.4]; keep all non-overlap early-pump cases unchanged |
| [SUM-7.4] | The retained startup paragraph said every detached/no-tty/no-attach path starts the pump early, while section 7.5 preserved the shipped delayed `NO_TTY` path | The active spec and implementation note now enumerate the actual matrix: forced detach, `NESTED_HOST`, and `UNAVAILABLE` are early; `AVAILABLE` and `NO_TTY` are delayed | The old paragraph already contradicted the baseline driver. Task 9 did not introduce that timing. Preserving it verbatim would leave the governing spec, reviewed plan, tests, and implementation irreconcilable | Promote the enumerable matrix and keep a firing test for every availability/flag case |
| [SUM-7.4], [SUM-13] | The plan treated `--attach` and `--detach` independently but did not define their overlap | CLI parsing rejects the pair as a usage error, and the internal driver constructor rejects programmatic requests with typed `SummonOperationError` before probing the host | Letting detach start the pump and attach enter the bridge creates two readers on one PTY master. Silent precedence would hide caller error and make the two surfaces disagree | Specify mutual exclusion at both syntax and driver safety boundaries |
| [SUM-12] | Add command/embedding installed-wheel verification without changing the existing four reactor combinations | The promoted spec now distinguishes those four combinations from two additional command-rollout cases, matching the checker's six separately reported cases | The naming-cleanup review found that an unqualified "four combinations" beside a six-case checker was agent-ambiguous even though the command paragraph required the extra coverage | Keep the 0.5.0 reactor floor and 0.5.4 command floor separate and enumerate both additional cases |
| Process tooling | Keep the reactor-only artifact and generic coverage-evidence entry-point names while widening their contracts | Rename `verify-reactor-artifact-compat.py` / `verify-reactor-release-artifacts.py` / `test_reactor_artifact_compat.py` to `check-core-summon-wheel-matrix.py` / `build-and-check-release-wheels.py` / `test_core_summon_wheel_matrix.py`; rename `verify-coverage-evidence.py` / `test_coverage_evidence.py` to `check-required-coverage-paths.py` / `test_required_coverage_paths.py` | The old names hid the 0.5.4 command-rollout cases and described required path execution as generic evidence. The rename updates every live workflow, release helper, maintained doc, and test together; historical plans retain the names that existed when their evidence ran | No product-spec change. Treat this row and the tooling execution slice as the exact old-to-new mapping for later agents |

The implementer appends one row before deviating. `pending` is not allowed at
completion.

## 12. Dependency-Ordered Tasks

Each task is a reviewable slice. Begin every behavior task by writing the named
failing test and recording why it fails. Implement only enough to make it pass,
then run the neighboring proof. Do not batch all red tests or all code before
checking behavior.

### Task 1: Promote the reviewed spec delta

Outcome: the spec tree, not this appendix, becomes the single implementation
contract.

Files to touch:

- `docs/specs/02-taut-core.md`
- `docs/specs/04-summon.md`
- this plan (promotion baseline and execution log only)

Actions:

1. Apply sections 10.1-10.9 exactly, adjusting only surrounding grammar.
2. Add Related Plans backlinks.
3. Do not add implementation mappings or claim completion.
4. Record the promotion baseline identifier in section 4.
5. Run `uv run pytest tests/test_docs_references.py -n 0`.

Stop gate: if the existing reference checker requires reciprocal code links at
promotion time, stop and switch this plan to strategy B. Do not weaken the
checker or leave main with warning/error debt.

Done signal: exact delta present, references resolve, promotion identifier
recorded, docs test green.

### Task 2: Establish the registry test harness and first red contract

Outcome: one bounded red checkpoint proves the registry protocol is missing;
Task 3 owns making every case in this checkpoint green. Do not add future
command-migration, lazy-facade, Summon-controller, or interaction reds here.

Files to add/touch:

- add `tests/test_command_registry.py`
- add `tests/fixtures/taut_command_plugin/pyproject.toml`
- add `tests/fixtures/taut_command_plugin/taut_command_plugin/__init__.py`
- add fixture manifest/command modules under that package
- update `tests/conftest.py` only for reusable installed-wheel helpers
- update `tests/test_cli.py` only where an existing parity case is the right
  owner

Required red cases:

- static built-in discovery without installed metadata;
- real wheel entry-point discovery through the registry/dispatcher in an
  isolated venv (the shipped-console install/uninstall case belongs to Task
  5D);
- built-in collision, external/external collision, broken manifest, broken
  implementation, invalid name, wrong manifest name, unsupported interface
  version, invalid command return value, and shuffled metadata enumeration with
  byte-identical help/conflict output;
- a broken unrelated fixture does not break direct dispatch of a healthy
  fixture;
- exact pre-verb globals, fixture-declared `post_verb_globals` in every
  supported spelling (`--db=PATH`, `-t`, and `-q` included), duplicate value
  precedence, a pre-verb boolean flag surviving a post-verb parse that does
  not repeat it, and literal `--` before/after the fixture verb;
- no process/thread/db/signal/terminal side effect during manifest discovery,
  proven with stdlib mechanisms: compare `threading.enumerate()` and
  `signal.getsignal` snapshots across discovery, assert no file is created in
  the fixture-scoped temporary project directory, and assert the `sys.modules`
  floor; the fixture manifest module records any import-time action it takes
  so the test fails loudly if discovery executes more than manifest
  construction.

Anti-mocking rule: the isolated-venv test must build and install the fixture
wheel and run the real registry/dispatcher against installed metadata. Task 5D
then executes the real `taut` console script and proves install/uninstall in new
processes. Unit tests may inject a fixed entry-point list only to exhaust pure
validation/conflict branches.

Stop gate: if tests need a new subprocess tracing dependency, stop. Use the
stdlib and existing build/venv helpers.

Checkpoint signal: pytest collection succeeds because imports of the missing
surface occur inside test bodies, and a separate fixture-build smoke proves the
synthetic wheel is well formed. One public-surface test fails with the expected
`ImportError` for `taut.commands`. The remaining behavior tests may initially
stop at that same import, so do not claim their contract assertions fired yet.
Task 3 first adds only the public protocol skeleton, reruns the suite, and
records each now-reachable behavior red before implementing registry behavior.
This is an intentional red WIP checkpoint, not a completed/committable slice;
proceed directly to Task 3.

### Task 3: Implement the minimal public command protocol and internal registry

Outcome: one deep registry hides discovery, validation, selection, parsing,
resource ownership, and error isolation.

Files to add:

- `taut/commands/__init__.py` — typed public command-author surface only
- `taut/commands/_protocol.py` — `GlobalOption`, `CommandSpec`, `Command`,
  `CommandFactory`, `CommandArgumentParser`, `CommandContext`, `CommandError`
- `taut/commands/_registry.py` — static/entry-point discovery and validation
- `taut/commands/_dispatch.py` — argv split, selected load, context lifecycle
- `taut/commands/_builtins.py` — static lightweight manifest tuple

Files to touch:

- tests from Task 2

Implementation constraints:

- First add only `taut/commands/__init__.py` and `_protocol.py` with the reviewed
  public types. Rerun Task 2 so collection and imports are green and the
  discovery/dispatch assertions fail for their own named reasons. Record those
  reds before adding `_registry.py`, `_dispatch.py`, or `_builtins.py` behavior.
- Cache one immutable snapshot per process; expose a test-only explicit reset
  helper only if necessary, private and documented.
- Attribute entry points to their distribution/version using public metadata.
- Normalize distribution ownership with the PEP 503 rule implemented locally
  as lowercase plus collapse of each `[-_.]+` run to `-`; do not add
  `packaging` for this one comparison. Missing distribution metadata cannot own
  a reserved first-party slot and is diagnosed as unavailable provenance.
- Import targets use one shared resolver; do not duplicate import-string logic
  between manifests and implementations.
- Validate that entry points load `CommandSpec` objects and implementation
  targets are zero-argument factories returning an object with the command
  protocol. Factory exceptions, invalid signatures, invalid return objects, and
  parser-configuration failures are selected-command errors with provenance and
  no traceback.
- Keep manifest loading separate from implementation loading.
- Selected resource cleanup belongs to dispatcher `finally`.
- Dispatcher unit tests may inject one minimal disposable client factory only
  to prove same-instance reuse, close-on-success, close-on-command-failure, and
  primary-error precedence when cleanup also fails. Built-in parity tests use a
  real `TautClient` and storage; the fake is not evidence for domain behavior.
- Use `io.StringIO` stream injection to prove parser help/errors and one command
  success/failure path avoid ambient process streams. Do not mock `print()` or
  patch global `sys.std*` as the primary proof.
- Preserve exception causes; render concise messages at the CLI edge.
- Do not wire `taut.cli.main` to the registry in this task. The registry and
  dispatcher are exercised directly as an internal shadow path until every
  built-in adapter passes parity in Tasks 4 and 5. Production retains exactly
  the current path until the atomic cutover in Task 5D.

Stop gate: if the registry interface gains aliases, priorities, capability
graphs, nested routes, or a generic dependency injector, stop and delete that
work. It is beyond v1.

Done signal: every Task 2 registry/dispatch test, including generic installed
fixture discovery, is green while the unchanged production CLI parity suite
remains green. No known red test is carried into Task 4.

### Task 4: Prove the command adapter shape with `say`

Outcome: one real built-in crosses the new seam without duplicating messaging
or rendering.

Files to add/touch:

- add `taut/commands/say.py`
- add `taut/commands/_rendering.py` or `_io.py` only for helpers moved from
  `taut/cli.py` and needed by multiple adapters
- update `taut/commands/_builtins.py`
- extract any shared `taut/cli.py` rendering/parser helper without changing
  `main` registration
- update `tests/test_cli.py`, `tests/test_cli_probes.py`,
  `tests/test_command_registry.py`

Red tests first:

- text, stdin `-`, piped omitted text, empty text, arbitrary UTF-8;
- channel/subthread/DM routing via real `TautClient` and SQLite;
- JSON and human output parity, timestamps, quiet, creation prelude;
- notification-warning stderr rendering for `say` without contaminating
  successful stdout/NDJSON;
- globals before/after (including `=`-joined and short spellings), duplicate
  precedence, pre-verb boolean survival across the split parse, literal `--`
  option-like text;
- injected context stdin/stdout/stderr with ambient streams untouched;
- `say` import floor excludes watcher and all Summon modules.

Implementation rule: `say.py` parses/translates/renders only and calls
`context.client().say`. Move a shared helper rather than copy it. Do not change
`MessagingMixin`.

Stop gate: if `say.py` starts owning target parsing, identity resolution,
notification writes, or envelope construction, stop; domain behavior leaked
through the seam.

Done signal: registry-dispatched `say` parity and import-floor tests are green.
The production `_cmd_say` remains temporarily because `main` has not cut over;
it must call the same extracted domain/rendering helpers and is deleted in
Task 5D. No released or test-selected surface has two competing dispatchers.

### Task 5: Migrate the remaining built-ins in cohesive groups

Outcome: every top-level verb uses the same command interface; shared domain
and rendering code stays shared.

Perform these sub-slices in order. For each, add parity tests before writing the
adapter and exercise it through the shadow registry dispatcher. The current
production handlers remain active until Task 5D; they share extracted helpers
where needed and are never selected by the registry. Do not wire a partial
registry into `main` and do not add runtime fallback between old/new handlers.

#### Task 5A: Identity and membership commands

Files:

- add `taut/commands/join.py`, `taut/commands/leave.py`,
  `taut/commands/who.py`, `taut/commands/whoami.py`,
  `taut/commands/rejoin.py`, and `taut/commands/set.py`
- update `taut/commands/_builtins.py`, `taut/commands/_rendering.py`,
  `taut/cli.py`, `tests/test_cli.py`, and `tests/test_command_registry.py`

Preserve identity creation prelude, persona, `--new`, `set name` nesting,
rejoin selector exclusivity, token shadowing, presence, aliases, and exit 2.

#### Task 5B: Read and thread commands

Files:

- add `taut/commands/reply.py`, `taut/commands/read.py`,
  `taut/commands/inbox.py`, `taut/commands/log.py`,
  `taut/commands/list.py`, and `taut/commands/rename.py`
- update `taut/commands/_builtins.py`, `taut/commands/_rendering.py`,
  `taut/cli.py`, `tests/test_cli.py`, `tests/test_command_registry.py`, and
  `tests/test_architecture_boundaries.py` for the shared renderer's explicit
  lightweight exception import

Preserve reply id/suffix resolution, implicit sub-thread creation, stdin text,
reply-specific usage-hint augmentation for missing/ambiguous message ids,
notification-warning stderr rendering, cursor advancement, notification
consumption, `--since`, `--limit`, list metadata, rename recovery diagnostics,
and empty exit 2.

#### Task 5C: Long-running watch

Files:

- add `taut/commands/watch.py`
- update `taut/commands/_builtins.py`, `taut/commands/_rendering.py`,
  `taut/cli.py`, `tests/test_cli.py`, `tests/test_command_registry.py`, and
  `tests/test_watcher.py`; update `tests/test_architecture_boundaries.py` only
  for the new import ownership rule

Use the existing `TautClient.watch` and `StopWatching` behavior. Preserve flush
before handler success, closed-pipe stop, SIGINT cleanup, dynamic memberships,
and no eager watcher import for other commands.

#### Task 5D: Initialization and remaining root behavior

Files:

- add `taut/commands/init.py`
- add `taut/commands/_summon_compat.py`: relocate the current
  `_delegate_to_summon` verbatim-tail delegation behind the command protocol
  as the registry-supplied provider for the two reserved `summon`/`dismiss`
  slots, preserving the lazy `taut_summon` import, the existing verb mapping,
  and the existing absent-package install hint. This is a relocation, not a
  redesign; the registry needs only the minimal two-entry reserved-name table
  here (both slots route to the relocated adapter or the install hint), and
  Task 7 adds the full slot-ownership policy around it
- update `taut/commands/_registry.py` and `taut/commands/_dispatch.py` for the
  minimal reserved-slot selection and compatibility adapter lifecycle
- update `taut/commands/_builtins.py`, `taut/commands/_rendering.py`,
  `taut/cli.py`, `tests/test_cli.py`, `tests/test_cli_probes.py`, and
  `tests/test_command_registry.py` for root help/version/no-command behavior
- replace `taut.cli.main` registration with the registry dispatcher in one
  atomic edit, then delete all old `_cmd_*` handlers, old hard-coded subparser
  registration, the old `main`-owned Summon delegation branch (its behavior
  now lives in the relocated adapter), and transitional shared wrappers that
  have no remaining caller

Red tests before the cutover:

- root help remains usable and deterministic with a broken unrelated command,
  while every registry diagnostic (including a rejected built-in override or
  invalid installed name) is rendered once as a concise warning on the
  injected stderr stream rather than being silently stored;
- current unambiguous pre-verb long-option abbreviations accepted by argparse,
  including `taut --timest ...`, remain accepted; root `-h` still prints help
  and exits 0; and an unknown root option remains a usage error. This is
  compatibility proof for existing grammar, not permission to add aliases to
  `CommandSpec`;
- post-verb declared globals participate only through their exact documented
  spellings. Preserve command-local argparse abbreviation behavior: in
  particular, `taut rejoin --t TOKEN` continues to select rejoin's local
  `--token`, while `taut join NAME --tok TOKEN` remains an unrecognized-option
  error rather than becoming a new global alias. Repeated exact global
  spellings retain textual last-value-wins ordering. This rule also prevents
  an abbreviated spelling from being merged out of textual order with an exact
  spelling;
- root `--version`, unknown verb, unknown root option, missing global values,
  a bare separator, no command, and `COMMAND --help` fire their specified exit
  class and stdout/stderr route with no traceback.
- after the atomic `main` edit, the existing real-process watch test must send
  SIGINT through the registry-backed entry point and observe exit 0, while its
  real message plus notification records flush before process exit. The closed-
  pipe subprocess case must also run unchanged and leave the terminal chat
  record unread. Controlled shadow tests before cutover are not a substitute
  for this production-entry transfer gate.

Preserve backend discovery, filesystem diagnostics, idempotence, JSON, and
creation output.

Cutover gate: before editing `main`, all built-in adapters must pass direct
registry parity, the relocated legacy adapter must already serve the two
reserved slots so the existing `summon`/`dismiss` delegation tests pass
unchanged, and a test must enumerate the [TAUT-8.1] verb table against the
static built-in manifest tuple plus the two reserved first-party slots in the
table's exact order, not merely compare set membership.
`taut summon` must never regress to an unknown verb between slices.
Immediately after the edit, run the full CLI
subprocess suite. If it fails, revert only the cutover edit and repair the
shadow adapter; do not add a production fallback to the old dispatcher.

Add the real installed-console fixture cases here: build/install the synthetic
wheel, execute `taut <fixture-verb>`, uninstall it, and prove it disappears in
a new process. Also make unknown-root-option versus unknown-verb, missing root
option value, `taut -- say`, `taut -- summon`, no-command, root help, and
version behavior green through `taut.cli.main` and the shipped console script.

Per-slice stop gate: if two adapters need the same nontrivial behavior, move it
to one shared renderer/policy helper or keep it on `TautClient`. Do not create a
generic base class merely because functions share three lines.

Done signal: `taut/cli.py` is a thin entry point and common policy owner; no
domain verb handler or hard-coded built-in-name set remains there. Static
`CommandSpec` registration and the explicitly documented two-name reserved-slot
table remain in their owning registry modules by design.

### Task 6: Make core package and CLI imports lazy

Outcome: package import and command selection initialize only required
subsystems.

Files to touch:

- `taut/__init__.py`
- `taut/cli.py`
- `taut/commands/_builtins.py`
- command modules whose imports are accidentally eager
- `tests/test_public_api.py`, `tests/test_lazy_imports.py`,
  `tests/test_architecture_boundaries.py`

Implementation pattern:

- Keep light constants/exceptions eager if they do not pull domain/runtime
  dependencies.
- Under `TYPE_CHECKING`, import public types for static analysis.
- At runtime, use one explicit name-to-`(module, attribute)` table and module
  `__getattr__`; cache resolved values in `globals()`.
- Keep `__all__` exactly aligned and make unknown names raise `AttributeError`.

Red tests must prove public imports and type checking still work before
asserting reduced `sys.modules` sets. Add `tests/test_lazy_imports.py` here and
make root import/version/help plus core `say --help` and `watch --help`
subprocess floors green. Task 8 separately adds the `taut_summon` facade and
standalone-help floors; Task 10 adds installed `summon --help`.

The Task 5D registry snapshot intentionally loads every installed manifest
before selecting a verb. Task 6 must remove that cost for statically known core
verbs: a built-in selection such as `say` uses the static manifests without
loading unrelated third-party manifest modules, while root help and external
verb selection still use the complete immutable registry. Do not apply this
shortcut to the reserved `summon`/`dismiss` slots because Task 7's official
owner selection requires installed metadata. Add an installed synthetic
manifest whose import is observable and prove ordinary built-in dispatch does
not import it.

Stop gate: if lazy import logic is copied into more than the two package
facades, centralize it or revert. Lazy loading is a subsystem-seam tool, not a
general coding style.

Done signal: core public API tests, mypy, version/root/core-command-help import
floors, and ordinary command isolation are green; only the explicitly
later-owned Summon floors remain unimplemented and unclaimed until their tasks
add a red test and make it green.

### Task 7: Add reserved Summon rollout slots and artifact compatibility

Outcome: the already-generic registry applies the exact first-party ownership
policy around the legacy adapter relocated in Task 5D: official entry-point
precedence, unofficial-claimant diagnostics, duplicate/broken official
handling, and the paired-rollout artifact policy for `summon` and `dismiss`;
old Summon remains usable during paired rollout.

Files to touch:

- `taut/commands/_registry.py`
- `taut/commands/_dispatch.py`
- `taut/commands/_builtins.py`
- `taut/commands/_summon_compat.py` relocated in Task 5D (ownership policy
  wiring only; no delegation redesign)
- `tests/test_command_registry.py`
- `tests/test_core_summon_wheel_matrix.py`
- `bin/check-core-summon-wheel-matrix.py`
- `bin/build-and-check-release-wheels.py` only if artifact selection needs
  new assertions

The legacy adapter relocated in Task 5D already uses lazy import and the
existing verbatim mapping; this task must not change its delegation behavior.
Extend Task 5D's minimal two-entry reserved-name table into the full
reserved-slot policy mapping `summon` and `dismiss` to normalized distribution
`taut-summon`; do not generalize this into an extension-ownership framework.
The adapter is selected only when no official `taut.commands` entry point owns
the name and the old `taut_summon` package is importable. The same slot renders
the install hint when the package is absent.
It must not mask a broken or duplicate new official entry point. An unofficial
claimant is diagnosed but cannot suppress the official/compatibility path.
The previously published `taut_summon.cli.main` must continue accepting
`run`/`stop` argv for one full paired-release compatibility cycle. Task 7 must
recognize the normalized `taut-summon` distribution as the sole official owner
rather than reuse Task 5D's blanket reserved-claim rejection. Record the exact
core and Summon versions that permit removal before deleting the bridge.

Add red installed-artifact cases only for core-only, old-Summon, unofficial,
official-plus-unofficial, duplicate-official, and broken-official-with-legacy-
code states, then make all of them green in this task. Tasks 10 and 11 add their
own new-Summon success and version-rejection reds when those artifacts exist;
do not check in future tests as expected failures or fabricate a package early.

Stop gate: if compatibility requires importing old Summon during root help or
accepting multiple manifest shapes indefinitely, stop and re-plan. The
compatibility path is one release-specific adapter, not a fallback protocol.

Done signal: every Task-7-owned artifact case is green, the removal condition is
recorded, and no known red test is carried into Task 8. The complete section
9.1 matrix is not claimed until Task 11 adds and passes its remaining cases.

### Task 8: Extract typed Summon models and controller with no behavior change

Outcome: CLI-independent callers can use Summon without private imports or
output parsing.

Files to add:

- `extensions/taut_summon/taut_summon/models.py`
- `extensions/taut_summon/taut_summon/controller.py`
- add `extensions/taut_summon/tests/test_controller.py`

Files to touch:

- `extensions/taut_summon/taut_summon/cli.py`
- `extensions/taut_summon/taut_summon/_driver.py`
- `extensions/taut_summon/taut_summon/_members.py`
- `extensions/taut_summon/taut_summon/_control.py` only to return/consume typed
  values, not redesign the protocol
- `extensions/taut_summon/taut_summon/__init__.py`
- `extensions/taut_summon/tests/test_summon_cli.py`
- `extensions/taut_summon/tests/test_driver.py`
- `extensions/taut_summon/tests/test_control.py`

Sub-slices:

1. Move `RunRequest` to `SummonRequest` in `models.py`; update driver typing.
2. Add the exact `SummonedMember`, `SummonStatus`, `StopResult`, and public error
   shapes from section 7.4 around existing state/control paths.
3. Make CLI render controller results and translate errors to current exits.
4. Change the foreground driver boundary to return `None` on clean completion
   and raise typed errors; remove printing from controller/driver domain paths.
5. Export models/controller lazily from `taut_summon`.
6. Keep `taut_summon.cli` parser construction lightweight; import the
   controller only after successful parse when executing a verb.

Red tests must compare the controller and standalone CLI through real SQLite
and real control queues. Pin structured fields exactly and message substrings
only. Task 10 adds the core command surface and the three-way parity proof.

Anti-mocking rule: do not mock `_state`, `Queue`, `ControlClient`, or
`SummonDriver` in controller contract tests. Narrow unit tests may fake an
external adapter handle or clock where the existing suite already does.

Stop gate: if controller methods expose private rows/replies, accept argv, print,
or return exit codes, stop. The module is becoming a shallow CLI relocation.

Done signal: public controller tests and all pre-existing Summon CLI/driver
tests green with one orchestration path; `import taut_summon` and standalone
root/subcommand help floors are green.

### Task 9: Inject the Summon host-interaction interface

Outcome: shell attach behavior becomes one adapter and driver ordering remains
authoritative; future rich hosts have a real seam.

Files to add:

- `extensions/taut_summon/taut_summon/interaction.py` — `TerminalIntent`,
  `TerminalAvailability`, `TerminalLease`, public protocol, and shell adapter
- `extensions/taut_summon/tests/test_interaction.py`

Files to touch:

- `extensions/taut_summon/taut_summon/cli.py`
- `extensions/taut_summon/taut_summon/controller.py`
- `extensions/taut_summon/taut_summon/_driver.py`
- `extensions/taut_summon/taut_summon/_pty.py` only if explicit fd parameters
  must be threaded through existing `attach`
- `extensions/taut_summon/taut_summon/__init__.py`
- `extensions/taut_summon/tests/test_controller.py`
- `extensions/taut_summon/tests/test_driver.py`
- `extensions/taut_summon/tests/test_pty_adapter.py`
- `extensions/taut_summon/tests/test_persona.py` only for affected contracts
- `extensions/taut_summon/tests/test_summon_cli.py` only for affected shell
  diagnostics
- `tests/test_architecture_boundaries.py`

Red tests:

- shell tty/no-tty/forced attach/forced detach/nested marker parity;
- `--attach --detach` rejected before host probing at both CLI and programmatic
  driver boundaries;
- explicit non-default terminal fds through a real PTY peer;
- exactly one cached `terminal_availability` call before the early-pump
  decision for each attach-capable, non-forced-detach foreground run, including
  a later-discovered wired resume; one lease only when attach actually occurs;
- attach result controls `wired` exactly once;
- STOP during attach remains observable;
- bridge remains the sole master reader before detach;
- terminal reset and termios restoration still occur on success/error/stop;
- `NO_TTY`, `NESTED_HOST`, and generic `UNAVAILABLE` preferred terminals take
  their reason-specific detached warning paths; required unavailability and
  lease acquire/restore failures are fatal;
- interaction never receives the provider handle, closes it, or touches state.
- raw host-fd/termios failures become typed public Summon errors without a
  traceback, while lease restoration still runs.

Use the existing fake TUI subprocess and PTY fixtures. The "future TUI" test
adapter is a deterministic host that owns explicit fds; it is not a mocked PTY
and does not claim to prove a real visual TUI.

Stop gate: if the adapter needs ledger/control access, generation state, or PTY
write leases, or if `AdapterHandle` enters the public interaction signature, the
seam is wrong. Move that behavior back to driver/PTY.

Done signal: interaction tests plus full PTY/driver process lane green.

### Task 10: Register Summon commands and unify console adapters

Outcome: installing `taut-summon` supplies `taut summon`/`dismiss`; both console
surfaces use the controller.

Files to add:

- `extensions/taut_summon/taut_summon/command_manifest.py` — lightweight specs
  only
- `extensions/taut_summon/taut_summon/commands/__init__.py`
- `extensions/taut_summon/taut_summon/commands/summon.py`
- `extensions/taut_summon/taut_summon/commands/dismiss.py`

Files to touch:

- `extensions/taut_summon/pyproject.toml`
- `extensions/taut_summon/taut_summon/cli.py`
- `extensions/taut_summon/taut_summon/__main__.py`
- `extensions/taut_summon/taut_summon/__init__.py`
- `tests/test_cli.py`, `tests/test_command_registry.py`
- `extensions/taut_summon/tests/test_summon_cli.py`
- `extensions/taut_summon/tests/test_controller.py`
- `extensions/taut_summon/README.md`, root `README.md`

Manifest entry points:

```toml
[project.entry-points."taut.commands"]
summon = "taut_summon.command_manifest:summon"
dismiss = "taut_summon.command_manifest:dismiss"
```

The manifest module and package facade must not import controller, driver,
control, adapters, scripted provider, or PTY. Command implementations load
the controller only inside `run()`, not during factory creation or parser
configuration.

Red tests must prove `taut summon`/`dismiss` parity, absent-package hint,
standalone parity, entry-point provenance, help, import floors, and installed
wheel behavior on Python 3.11.

Stop gate: if one console calls the other's `main()` or parses rendered output,
stop and return to the shared controller.

Done signal: new entry points own commands; new-core/new-Summon path never runs
legacy adapter; standalone surface remains green.

### Task 11: Update release, metadata, and cross-package gates

Outcome: paired artifacts prove command compatibility before irreversible
release actions.

Files to inspect/touch only as evidence requires:

- `pyproject.toml`
- `extensions/taut_summon/pyproject.toml`
- `extensions/taut_summon/uv.lock`
- `bin/release.py`
- `bin/check-core-summon-wheel-matrix.py`
- `bin/build-and-check-release-wheels.py`
- `tests/test_project_metadata_consistency.py`
- `tests/test_core_summon_wheel_matrix.py`
- `tests/test_release_script.py`
- `.github/workflows/test.yml`
- `.github/workflows/release-gate.yml` and
  `.github/workflows/release-gate-summon.yml` only if selectors/path coverage
  must change; do not touch PG-only or publication workflows for command
  discovery

The user selected 0.6.0 on 2026-07-13 for core and every extension. Task 11
therefore synchronizes all package versions and cross-package floors to 0.6.0
without publishing, tagging, pushing, or committing. Preserve
core-first/Summon-second dependency floors and fresh artifact selection.

Red tests must prove new command entry points are present in the built Summon
wheel and absent from core-only environment, and that release checks run the
expanded wheel-matrix checker before commit/tag/push/publish even under
`--skip-checks`. Note: `bin/release.py` already runs the release-wheel check as
an unconditional postupdate step (`--skip-checks` skips only the pytest, ruff,
and mypy prechecks), so the skip-checks case may be born green for the
existing checker path; record it as a regression guard whose new coverage is
the expanded matrix, not as a fabricated red. Before synchronizing package
metadata, use synthetic 0.6.0 wheel metadata to fire the old-core rejection
branch; do not weaken the real package floor or temporarily edit committed
versions inside a test.

Release-only subgate: with the selected 0.6.0 paired release version, the
release helper must synchronize core, every extension, the extension `taut>=`
floors, and locks, then run the same matrix with the actual fresh wheels. The
new-core + old-Summon case uses `taut_summon/v0.5.4`; the old-core + new-Summon rejection
uses `v0.5.4`. Keep the older `v0.5.0` reactor-compatibility cases as separate
proofs.

Stop gate: if a workflow change is needed for reasons other than including new
files/tests, open a separate remediation plan.

Implementation done signal: verifier/unit/fixture metadata tests are green and
pre-sync fresh wheels pass every applicable case without pretending they are
0.6.0 artifacts. Release-ready signal: after version sync,
actual fresh wheels pass all of section 9.1. Do not use the first signal to
claim the second.

### Task 12: Documentation and traceability reconciliation

Outcome: the promoted specs, plan, implementation rationale, repository map,
code, and tests form one navigable chain.

Files to touch:

- add `docs/implementation/06-command-extensions.md`
- `docs/implementation/04-taut-architecture.md`
- `docs/implementation/05-taut-summon-architecture.md`
- `docs/implementation/02-repository-map.md`
- `docs/implementation/00-implementation-index.md`
- `README.md`
- `extensions/taut_summon/README.md`
- `docs/specs/02-taut-core.md`, `docs/specs/04-summon.md` mapping/backlinks
- `docs/plans/README.md`
- `tests/test_docs_references.py`
- `CHANGELOG.md`
- this plan's execution/review/deviation records

Required rationale:

- same command interface, different static vs installed discovery sources;
- lazy subsystem imports and why they stop at facades/command targets;
- command adapter versus domain interface;
- temporary old-Summon compatibility adapter and removal condition;
- Summon controller ownership;
- rich TUI as composition root, not generic parser UI;
- TUI product/process lifecycle explicitly deferred.
- a dated `0.6.0 - 2026-07-13` changelog entry covering the complete release,
  not an undated or partial unreleased note.

The new command-extension guide is the canonical author path. It must contain:

- the five `CommandSpec` fields and all validation rules;
- a minimal `pyproject.toml` `[project.entry-points."taut.commands"]` example;
- separate lightweight manifest and execution-adapter modules;
- the zero-argument factory and `configure_parser`/`run` protocol;
- exact pre/post-verb global and literal-`--` behavior;
- error/exit/resource ownership and the trusted-code, non-sandbox warning;
- an installed-wheel smoke recipe that builds, installs in an isolated venv,
  checks root/command help import floors, runs the verb, uninstalls it, and
  proves disappearance in a new process;
- the statement that Python domain APIs remain typed package interfaces and
  are not dynamically attached to `TautClient`.

Evaluate `docs/lessons.md`: add a lesson only if implementation or review
exposes a reusable correction not already covered by engineering principles.

Done signal: docs references green; no stale claim says core changes are only
two Summon delegation verbs; all new modules have spec pointers where ownership
would otherwise be ambiguous.

### Task 13: Final adversarial acceptance and fresh-eyes review

Outcome: current-state evidence supports integration-ready claims. Release-ready
requires the separate versioned artifact subgate in Task 11.

Actions:

1. Run targeted red/green suites after each slice.
2. Run the full gates in section 14 from a clean process environment.
3. Run installed-wheel probes on the oldest supported Python 3.11.
4. Inspect `git diff --check`, `git status`, and changed-file scope.
5. Run an independent completed-work review with specs, plan, implementation
   notes, changed files, and evidence.
6. Reproduce every accepted finding before changing code.
7. Reconcile the deviation log and promotion baseline.
8. Commit only when the user asks to land the work; otherwise report all
   uncommitted files and do not call the slice complete.

Stop gate: any traceback, wrong exit class, eager heavy import, command conflict
ambiguity, private TUI/Summon reach, controller/CLI behavior drift, or artifact
combination failure blocks release readiness.

## 13. Testing Plan

### 13.1 Red-green discipline

For every behavior task:

1. add the narrowest public-contract test;
2. run it and record the expected red failure;
3. implement the smallest path that passes;
4. rerun the targeted test;
5. run the nearest neighboring suite;
6. refactor only while green.

No behavior slice receives a TDD exception. Documentation promotion is verified
by inspection/reference tests. Lock regeneration and manifest-only edits use
metadata/build tests as substitute proof.

### 13.2 What must remain real

- Real `argparse` parsers and `main` dispatch.
- Real `importlib.metadata` discovery in at least one installed-wheel venv.
- Real console scripts from built wheels.
- Real SQLite files, SimpleBroker queues, sidecar tables, and TautClient paths.
- Real Summon driver/scripted-provider processes for run/control parity.
- Real control request/reply queues for status/stop.
- Real PTY fds and fake interactive child for attach/interaction tests.
- Real Python 3.11 interpreter for parser/install smoke.

Mocks/fakes are limited to:

- fixed entry-point objects for exhaustive pure registry validation;
- clock/signal/error injection at existing narrow seams;
- the external model/provider through the real scripted subprocess;
- a deterministic host-interaction adapter that owns real PTY fds.

Do not mock broker, state, command dispatch, control queues, driver process, or
PTY in the contract tests that claim integration readiness.

### 13.3 Enumerable contract matrix

Every element must have a firing test:

- command manifest fields and validation errors;
- every `GlobalOption` enum member in both a declared and undeclared
  post-verb position, in every supported spelling (long, `=`-joined value,
  and short forms), plus pre-verb boolean survival across the split parse;
- exit 0/1/2 and help/version exits;
- all current top-level verbs;
- built-in/external/conflicting/broken/incompatible/uninstalled command states;
- source/static and installed/entry-point registration sources;
- lazy import floors for import/version/root help/command help and actual
  say/watch/summon/status execution;
- Summon controller operations and typed result variants;
- shell attach decision variants, availability reasons, and finite attach
  outcomes;
- supported artifact combinations in section 9.1.

### 13.4 Adversarial CLI probes

Apply the repository probe runbook through shipped entry points:

- unknown verb and unknown flag: usage exit 1, no traceback;
- missing/broken/incompatible command package: exit 1 with provenance;
- missing Summon package: existing install hint;
- duplicate provider names: deterministic conflict, no last-wins;
- literal option-like positional after `--`;
- non-UTF-8/closed stdin and closed stdout where applicable;
- invalid command return value;
- malformed manifest object and wrong top-level type;
- help with an unrelated broken extension;
- command implementation raising before/after lazy client creation;
- cleanup does not replace the primary exception.

## 14. Verification and Gates

### 14.1 Per-task targeted commands

```bash
uv run --extra dev pytest tests/test_command_registry.py tests/test_lazy_imports.py -n 0
uv run --extra dev pytest tests/test_cli.py tests/test_cli_probes.py -n 0
uv run --extra dev pytest tests/test_public_api.py tests/test_architecture_boundaries.py -n 0
uv run --extra dev pytest extensions/taut_summon/tests/test_controller.py \
  extensions/taut_summon/tests/test_interaction.py \
  extensions/taut_summon/tests/test_summon_cli.py -n 0
uv run --extra dev pytest extensions/taut_summon/tests/test_driver.py \
  extensions/taut_summon/tests/test_control.py \
  extensions/taut_summon/tests/test_pty_adapter.py -n 0
uv run --extra dev pytest tests/test_core_summon_wheel_matrix.py \
  tests/test_project_metadata_consistency.py tests/test_release_script.py -n 0
uv run --extra dev pytest tests/test_docs_references.py -n 0
```

New test files do not exist at plan authoring time; commands become valid in
their owning task.

### 14.2 Full repository and extension gates

```bash
uv run --extra dev pytest
uv run ./bin/pytest-pg --fast
uv run --extra dev pytest extensions/taut_summon/tests -m "not xdist_group"
uv run --extra dev pytest extensions/taut_summon/tests \
  -m "xdist_group and not requires_live_harness and not requires_local_llm" \
  -n 4 --dist load
TAUT_SUMMON_LIVE_HARNESS_STRICT=1 uv run --extra dev pytest \
  extensions/taut_summon/tests/test_live_harness.py -n 1 --dist loadgroup
TAUT_SUMMON_LOCAL_LLM=1 uv run --extra dev pytest \
  extensions/taut_summon/tests/test_live_local_llm.py -n 1 --dist loadgroup
uv run --extra dev ruff check taut tests bin \
  extensions/taut_summon/taut_summon extensions/taut_summon/tests
uv run --extra dev ruff format --check taut tests bin \
  extensions/taut_summon/taut_summon extensions/taut_summon/tests
uv run --extra dev mypy taut tests bin/release.py --config-file pyproject.toml
uv run --extra dev mypy extensions/taut_summon/taut_summon \
  extensions/taut_summon/tests \
  extensions/taut_summon/tests/conftest.py --config-file pyproject.toml
uv build
uv build extensions/taut_summon
uv run python bin/build-and-check-release-wheels.py
git diff --check
```

Do not weaken SQLite sync, merge real-process lanes, or replace strict external
and local-LLM release gates with skips.

### 14.3 Release-version-only gate

After synchronizing every package and cross-package floor to the user-selected
0.6.0 version:

```bash
uv run python bin/build-and-check-release-wheels.py
uv run python bin/release.py all --dry-run
```

Inspect the verifier output to prove both separate historical floors ran:
reactor compatibility against the retained 0.5.0 refs and command rollout
against core/Summon 0.5.4. Then the release operator runs the applicable
non-dry-run release target, whose pre-mutation gate rebuilds both wheels and
reruns the verifier. This plan does not authorize that release action.

### 14.4 Observed success signals after release

- Core-only install: built-ins and help work; optional commands show install
  hints or ordinary unknown-command diagnostics.
- Core + Summon install: root help lists Summon commands; invoking them loads
  Summon only then; standalone CLI stays equivalent.
- `taut --version` and unrelated built-ins have no Summon/provider/PTY import or
  startup failures.
- Broken third-party command installation cannot prevent core chat use.
- Existing summoned members resume, report status, stop, and attach exactly as
  before; no schema or control migration occurs.
- No new traceback signatures, command-conflict ambiguity, PTY terminal
  corruption, or driver-release residue appears in release smoke logs.

## 15. Independent Review Loop

Plan reviewer: Claude Code CLI in read-only consult mode, then an author
fresh-eyes pass. The reviewer receives:

- this entire plan, especially `## 10. Proposed Spec Delta`;
- baseline specs `docs/specs/02-taut-core.md` and `04-summon.md`;
- implementation notes `04-taut-architecture.md` and
  `05-taut-summon-architecture.md`;
- `taut/cli.py`, `taut/__init__.py`, `taut/client/__init__.py`;
- Summon `cli.py`, `_driver.py`, `_control.py`, `_state.py`, `_pty.py`, and
  `__init__.py`;
- manifests, release-wheel checker, and relevant tests.

Exact adversarial prompt:

> Read `docs/plans/2026-07-12-lazy-command-extensions-and-rich-tui-composition-plan.md`
> and its `## Proposed Spec Delta`, including promotion strategy A. Inspect the
> cited specs, implementation notes, code, manifests, release-wheel checker, and
> tests. Look for latent ambiguities, errors, bad decisions, incorrect current-
> code claims, compatibility gaps, weak or mock-heavy tests, missing failure
> paths, and performative overengineering. Pay special attention to lazy import
> guarantees, argparse/global/`--` behavior, installed entry-point conflict and
> failure isolation, old/new core-Summon rollout, controller depth, PTY/terminal
> ownership, and the explicit decision not to build the TUI in this plan. Do not
> implement or edit. Answer specifically: **If requested, could you implement
> this plan as written confidently and correctly?** If not, name every blocker
> and the exact plan section that must change.

The author records every finding below and either edits the plan or rejects the
finding with concrete code/spec evidence. Review is blocking until Claude says
the plan is implementable confidently and correctly or every remaining
limitation is an explicit user-approved scope decision.

## 16. Out of Scope

- Building `taut-tui`, selecting a TUI framework, or defining screens/keymaps.
- Managed/background Summon driver launch from a TUI, terminal-release IPC,
  process orphaning, or survival after TUI exit.
- New Summon control verbs such as ATTACH or fd passing to a live remote driver.
- Dynamic `TautClient` methods or a universal extension/service registry.
- Provider-adapter plugins.
- Taut backend/state plugin changes, Redis mapping, or `taut-pg` redesign.
- Summon storage schema, control JSON, queue naming, injection format, persona,
  provider behavior, or rate policy changes.
- Command aliases, override priority, nested cross-package namespaces,
  dependency solving, hot reload, remote plugins, or plugin sandboxing.
- A new CLI framework or dependency.
- Unrelated plan-index cleanup, stale historical status edits, file-size-driven
  splits, or formatting churn.

## 17. Fresh-Eyes Review Checklist

Before marking the plan review-ready, the author must re-read it from an empty
context and confirm:

- every new type has one owner and does not duplicate a domain path;
- every task names exact files, red tests, real dependencies, stop gates, and
  done signals;
- exact spec text distinguishes decided behavior from deferred TUI product
  choices;
- command v1 does not contain speculative extension-system features;
- global/`--`/rejoin/Summon grammar is implementable without guessing;
- lazy import floors name exact modules and execution surfaces;
- previous-Summon compatibility and release order are executable;
- controller results are domain models rather than CLI-shaped dictionaries;
- PTY, driver, host, and future TUI ownership cannot be confused;
- full gates match current `bin/release.py` lane separation;
- no task silently introduces a dependency, storage migration, daemon, or TUI;
- deviation, promotion, review, and execution records are present.

Repeat the review after every material correction from Claude.

## 18. Review Record

### Author fresh-eyes pass 1

Completed against baseline code/specs and the current parser/release scripts.
Corrections made before independent review:

- replaced an interaction callback that exposed `AdapterHandle` with a
  two-phase availability/terminal-lease seam; restored distinct no-tty/nested
  diagnostics and pinned early-pump timing;
- specified controller constructors, request/result/error fields, defensive
  copying, and blocking behavior instead of leaving model policy to taste;
- changed partial production migration to a shadow-adapter build followed by
  one atomic `taut.cli.main` cutover with no fallback path;
- probed the real parser and corrected pre-verb literal `--` behavior;
- renamed vague supported globals to exact `post_verb_globals` and assigned all
  enum members/precedence tests;
- defined manifest-object, zero-argument factory, core-owned parser, context,
  cleanup, deterministic ordering, and PEP 503 ownership contracts;
- added reserved first-party `summon`/`dismiss` slots so official entry points,
  old-package compatibility, and unofficial claims have deterministic policy;
- restored the omitted `reply` migration and made the [TAUT-8.1] table a firing
  manifest inventory test;
- separated retained 0.5.0 reactor compatibility, 0.5.4 command rollout, and
  the release-version-only dependency rejection gate;
- removed cross-task duplicate ownership and future red tests that would have
  remained failing across slices; and
- expanded shorthand file paths and added one canonical extension-author guide.

Inspection evidence: `uv run pytest tests/test_docs_references.py -n 0` passed
10 tests; `git diff --check` was clean. Independent review was still blocking
at the end of this first pass and was completed below.

### Claude adversarial review

Completed in a fresh read-only Claude Code consult session after one prior CLI
invocation idled for ten minutes with empty response/error files and was
stopped. The completed review inspected the plan and targeted code/spec/release
evidence. It answered the required question yes and ended:

> Recommendation: IMPLEMENTABLE

Claude found no blocker and three non-blocking ambiguities. All three were
accepted and corrected below. A focused same-session confirmation re-read the
revised sections, found no new contradiction or scope drift, answered the
required implementability question yes, and again ended:

> Recommendation: IMPLEMENTABLE

### Author fresh-eyes pass 2

Completed after the Claude corrections and same-session confirmation. The pass
checked the three edited boundaries against adjacent tasks and the baseline
files, confirmed that no future red test is carried across a green slice, and
confirmed that implementation-ready is not conflated with the release-version
subgate. Final inspection repeated the docs reference suite (10 passed),
`git diff --check`, an explicit trailing-whitespace scan of the untracked plan,
and changed-file scope inspection. No implementation has started.

### Finding dispositions

| Finding | Disposition | Plan change or evidence |
|---------|-------------|-------------------------|
| `CommandContext` streams had no adoption rule | Accepted | Sections 7.2, 10.3, Tasks 3-4 now make injected streams authoritative for parser, diagnostics, stdin, and renderers, with `StringIO` firing tests. |
| Task 5B omitted reply usage hints and notification warnings | Accepted | Task 4 fires notification-warning stderr behavior; Task 5B preserves/tests reply message-id hint augmentation and warning rendering. |
| [SUM-3] edit boundary was under-specified | Accepted | Section 10.5 now names the exact four bullet operations and the exact preserved provider-resolution suffix. |

### Claude adversarial review 2 (2026-07-13)

A second independent adversarial review verified the plan's current-code claims
against source with parallel verification passes (core CLI grammar and
hoisting; Summon cli/driver/control/state; release and test infrastructure).
All roughly twenty-five checked claims were accurate, including the `rejoin`
token hoisting conditional, the pre-verb literal `--` behavior, the
`AdapterHandle.attach` result strings, the v0.5.0 compat floor, and the
review-record test counts. The review found one sequencing error and five
smaller items; all were accepted and corrected in place.

### Finding dispositions 2

| Finding | Disposition | Plan change or evidence |
|---------|-------------|-------------------------|
| Task 5D deleted the Summon delegation before Task 7 supplied its replacement, so `taut summon` regressed to an unknown verb between slices, contradicting invariant 8.1 and 5D's own full-suite cutover gate | Accepted | Task 5D now relocates the legacy delegation adapter into the two reserved slots before the atomic cutover, with a minimal reserved-name table; Task 7 adds ownership policy only. The cutover gate requires delegation tests to pass unchanged and forbids the between-slice regression. |
| `GlobalOption` never enumerated the short (`-t`, `-q`) and `=`-joined spellings the current hoister accepts (`taut/cli.py::_hoist_global_options`), so a long-form-only dispatcher could pass the enumerated matrix | Accepted | Sections 7.1 and 10.3 now bind every spelling to its enum member; section 13.3, Task 2, and Task 4 require firing tests for the alternate spellings. |
| Split-parse boolean merge semantics were implicit in "existing argparse behavior" | Accepted | Section 7.3 step 9 and 10.3 now state logical-OR combination and explicit-versus-default detection; Tasks 2 and 4 name the survival tests. |
| The discovery side-effect-absence red case named no proof mechanism | Accepted | Task 2 now names the stdlib snapshot, marker-file, and instrumented-fixture mechanisms. |
| The Task 11 `--skip-checks` case is born green: `bin/release.py` postupdate artifact verification is already unconditional | Accepted | Task 11 now records it as a regression guard over the expanded verifier rather than a red. |
| The Task 2 red checkpoint fails uniformly at collection with one `ImportError` | Accepted | Task 2 now keeps collection green, proves the fixture wheel separately, and records one missing-public-surface red. Task 3 first adds only the protocol skeleton, then records the now-reachable behavior-specific reds before implementing the registry. |
| Section 6.3 context: `_cmd_run`'s `_driver` import is already lazy; only control/state imports are eager | Accepted | Section 6.3 now states which imports the lazy-import work targets. |

### Author fresh-eyes pass 3 (2026-07-13 minor amendments)

Completed after re-reading the amended plan end to end. The second independent
review's changes preserve the agreed architecture and scope. This pass found
two local implementation ambiguities and corrected them without changing the
design: Task 5D now names the exact compatibility-adapter module and every
registry file it touches, and Task 2 now has a valid staged red-green sequence
instead of conflating pytest collection failure with firing contract tests.
The pass also reconciled the affected done signal and review record. No
implementation has started.

### Finding dispositions 3

| Finding | Disposition | Plan change or evidence |
|---------|-------------|-------------------------|
| Task 5D required a private legacy Summon adapter but did not assign it an exact file owner, while its done signal appeared to forbid the reserved-name table it introduced | Accepted | Task 5D now assigns compatibility behavior to `taut/commands/_summon_compat.py`, names `_registry.py` and `_dispatch.py` as touched owners, and limits the prohibition to hard-coded built-in names in `taut.cli`; the explicit two-name registry table remains by design. |
| Task 2 said every named test ran while most tests failed during collection, so the claimed contract assertions could not fire | Accepted | Imports now occur inside test bodies, fixture construction has its own smoke proof, one missing-surface red is recorded in Task 2, and Task 3 exposes and records each behavior-specific red before implementing it. |

### Claude implementation-slice review: Tasks 1-3 (2026-07-13)

A fresh read-only Claude Code review inspected the promoted specs, all five
command modules, the complete registry suite, the installed-wheel fixture, and
the current production hoister. It found no registry design rework and judged
the slice safe for Task 4 after three localized corrections. Those corrections
were reproduced with failing tests before implementation. The reviewer also
identified lower-risk gaps and future-slice obligations; none were silently
dropped.

### Finding dispositions 4

| Finding | Disposition | Plan/code change or evidence |
|---------|-------------|------------------------------|
| Parse-phase `SystemExit` with a string code raised `ValueError`, while a bare `SystemExit()` returned success | Accepted and fixed red-green | `test_parse_system_exit_is_contained_as_exit_one` fires both cases; dispatch now accepts only exact integer parser exits 0/1 and renders all other codes as exit 1 without traceback. |
| Parser-seen declared globals used private `_root_*` destinations that were never merged or removed | Accepted and fixed red-green | `test_parser_seen_global_is_merged_and_removed_from_command_namespace` proves the value reaches `CommandContext` and the adapter namespace contains command fields only. The merge preserves existing argparse abbreviation behavior instead of globally disabling command-option abbreviations. |
| Generic dispatch contained speculative `reply` message-text matching before the Task 5B adapter existed | Accepted and fixed red-green | The branch was deleted; `test_generic_dispatcher_does_not_add_command_specific_error_hints` pins generic rendering. Task 5B remains the sole owner of the reply hint. |
| Registry diagnostics were stored but not rendered | Accepted, assigned to Task 5D | Task 5D now requires a red stream-routing test and one concise warning per diagnostic during registry-backed root help. Production is not cut over before that slice. |
| Reserved `summon`/`dismiss` ownership is absent from the shadow registry | Accepted, already assigned to Tasks 5D and 7 | No permissive behavior is pinned. Task 5D installs compatibility slots before cutover; Task 7 applies official ownership/conflict policy. |
| An arbitrary custom `BaseException` reached an assertion traceback | Accepted and fixed red-green | `test_arbitrary_base_exception_is_contained_as_exit_one` now fires the clean exit-1 boundary while `KeyboardInterrupt` remains the explicit re-raised exception. |
| Current pre-verb argparse abbreviations would regress at cutover | Accepted, assigned to Task 5D | Task 5D now names `--timest` compatibility proof. Unknown options remain loud errors. |
| Literal pre-verb `--` could be read as merely disabling root hoisting rather than forcing the later tail positional | Accepted clarification | Sections 7.3 and 8.1 plus promoted [TAUT-8.6] now say the separator is preserved for command parsing in both positions. The existing firing test already pins this behavior. |
| Boolean invalid returns and `CommandError` exit/quiet behavior had no firing test | Accepted and covered | The Task 3 suite now fires boolean rejection, exit class 2, invalid `CommandError` construction, and quiet suppression. Remaining root behavior listed by the reviewer is explicitly Task 5D-owned above. |
| `_builtins.py` omitted the module annotation future import | Accepted | The standard module header was added. |

### Claude implementation-slice review: Task 4 (2026-07-13)

A fresh read-only Claude Code review inspected the complete `say` adapter,
shared renderer, temporary production wrappers, real-state tests, and static
import proof. It found no adapter-seam rework and answered that Task 4 is safe
to build Task 5 on. Its only P1 was the repository completion/commit gate. The
overall multi-task implementation remains explicit uncommitted WIP, so this is
not a claim that Task 4 is ready to land and no commit was created merely to
satisfy the gate. The evidence gap was fixed below.

### Finding dispositions 5

| Finding | Disposition | Plan/code change or evidence |
|---------|-------------|------------------------------|
| Task 4 had no execution-log row and the plan still said production implementation had not started | Accepted | The execution status and Task 4 row below now record red, green, independent review, and the uncommitted WIP boundary. |
| Quiet JSON identity preludes and quiet candidate notes were characterized but not checked against the pre-refactor baseline | Accepted | `git show b0370945:taut/cli.py` confirms both legacy branches. The JSON case already fires through registry dispatch; `test_shared_creation_renderer_preserves_quiet_candidate_note` now fires the candidate-note branch through the shared renderer and a real client. |
| Registry command help exposes declared globals while legacy command help did not | Accepted as required new-interface behavior | Section 7.2 requires the core-created parser to carry declared globals. A red help test exposed that their descriptions were blank; `_add_declared_globals` now supplies agent-usable help and the test proves help does not create a client. |
| The production and shadow error classifiers are duplicated during migration | Accepted transitional risk | Do not make the legacy CLI import the shadow dispatcher merely for a private helper. Tasks 5A-5C must keep both CLI and direct-registry parity gates green; Task 5D deletes the legacy copy atomically. Any classifier change before then must edit both and add a firing parity test. |
| The static import proof omitted `_protocol.py` and the public command facade | Accepted | Both modules are now in the exact runtime-import allowlist test, closing the complete `say` leaf set until Task 6 supplies the fresh-process proof. |
| Root `-h` compatibility was not named for cutover | Accepted | Task 5D's root red list now names exit-0 `-h` alongside long-option abbreviation compatibility. |
| Unimplemented built-in manifests fail if selected on the shadow path | Accepted intentional WIP | The production CLI is not cut over and no fallback exists. Each Task 5 sub-slice supplies the named adapter before Task 5D's atomic cutover gate. |
| Task 4 did not modify `tests/test_cli.py` or `tests/test_cli_probes.py` | Accepted test-placement adjustment | New seam behavior belongs in `tests/test_command_registry.py`; the unchanged black-box suites are the production refactor-parity oracle and were rerun in full. No production behavior contract was removed. |

### Claude implementation-slice review: Task 5A (2026-07-13)

A fresh read-only Claude Code review inspected the six identity and membership
adapters, their real-state tests, the dispatcher changes they exercise, shared
rendering, and the migration boundary. It found no adapter-seam rework and
judged the slice safe for Task 5B after one parser correction. The correction
was reproduced across every separated-value global spelling before production
code changed. Concrete coverage and formatting gaps were also closed. The one
cutover-only compatibility issue is assigned below to Task 5D rather than
changing the agreed architecture during this slice.

### Finding dispositions 6

| Finding | Disposition | Plan/code change or evidence |
|---------|-------------|------------------------------|
| A separated global such as `--db --json` or `--token --` consumed the following option or separator as its value | Accepted and fixed red-green | A twelve-case matrix now fires `--db`, `--as`, and `--token` before and after the verb with either a following declared flag or `--`. `_consume_global` rejects those missing values while retaining negative-number values, literal `-`, and joined option-looking values such as `--db=--path`. |
| Task 5A had no execution row and the plan status still stopped at Task 4 | Accepted | The status and Task 5A execution row below now record red, green, review, and uncommitted-WIP evidence. |
| Ruff formatting was not clean | Accepted | The project formatter was run over the touched command, CLI, registry-test, and architecture-test files; the slice gates below rerun format checking rather than relying on manual layout. |
| Human-rendering branches, token absence, repeated leave, and set-name collision did not all fire through the registry | Accepted and covered | Focused real-client tests now exercise human join/whoami output without leaking the token, an already-left member, and a rename collision. No client or domain method is mocked. |
| Hoisting declared post-verb abbreviations would change legacy command-local argparse behavior (`rejoin --t`) and accept new spellings (`join --tok`) | Accepted, assigned to Task 5D | Task 5D now requires exact-only matching for declared post-verb globals while preserving command-local argparse abbreviations. Its red list names both examples and textual last-value-wins behavior. No new alias enters `CommandSpec`. |
| Task 5A did not mechanically touch `_builtins.py` or `tests/test_cli.py` | Accepted scope adjustment | The static manifest already named all six adapter imports, so editing it would be performative. New shadow-path behavior belongs in `tests/test_command_registry.py`; the unchanged CLI/probe suites remain the production parity oracle until cutover. |

### Claude implementation-slice review: Task 5B (2026-07-13)

A fresh read-only Claude Code consult ran to completion after roughly seven
minutes. It inspected the six read/thread adapters, client error paths, shared
rendering, legacy callers and tests, registry tests, import allowlist, and the
Task 5B plan contract. It found no adapter-seam rework, explicitly answered
that Task 5C can proceed confidently from this slice, and ended
`Recommendation: PROCEED`. Its evidence finding and every concrete P2 were
fixed before the slice gate below.

### Finding dispositions 7

| Finding | Disposition | Plan/code change or evidence |
|---------|-------------|------------------------------|
| Task 5B had no execution row and the implementation status stopped at Task 5A | Accepted | The status and Task 5B row below now record the named red, final gates, independent review, and uncommitted-WIP boundary. |
| Static built-ins followed legacy parser-registration order rather than the promoted [TAUT-8.1] table order required by [TAUT-8.6] | Accepted and fixed red-green | The exact-order registry test was changed first and failed at `set`; `BUILTIN_SPECS` now follows the table (`init`, `join`, `leave`, `set`, `say`, `reply`, `read`, `inbox`, `log`, `list`, `watch`, `rename`, `who`, `whoami`, `rejoin`). Task 5D's enumeration gate now says order, not membership. |
| Direct registry tests omitted two `message not found` reply-hint branches, reply warning rendering, and grouped human read/log output | Accepted and covered | Real-state adapter tests now fire exact-id miss, bounded-suffix miss, human grouping, and the shared reply warning path. The warning test performs the real reply and adds only a narrow post-write warning fault through a `TautClient` subclass; it does not replace domain behavior. |
| `_thread_object` and `_notification_object` remained as dead legacy wrappers | Accepted | Both wrappers and their imports were deleted. Live compatibility wrappers imported by `tests/test_cli.py` remain until Task 5D's atomic sweep. |
| `tests/test_cli.py` was listed but unchanged, while the renderer import boundary required an architecture-test edit | Accepted test-placement correction | New shadow behavior stays in `tests/test_command_registry.py`; the unchanged 73-test CLI suite is the black-box parity oracle over the now-shared renderer. `tests/test_architecture_boundaries.py` was added to Task 5B's file list because the renderer deliberately imports only lightweight `taut._exceptions` at runtime. |

### Independent implementation-slice reviews: Task 5C (2026-07-13)

A read-only subagent first mapped the watcher ownership and existing firing
tests. It identified two precise corrections that were incorporated: message
versus notification routing now has one shared renderer owner, and the EPIPE
integration test fails the terminal record's `flush()` after its write rather
than failing the write itself. A fresh read-only Claude Code consult then ran
to completion after roughly six minutes. Claude inspected the adapter,
renderer, legacy path, client/watcher lifecycle, registry tests, static import
proof, and unchanged watcher/CLI suites. It found no seam rework, confirmed
Task 6 is the correct owner for the fresh-process facade floor, answered that
Task 5D can proceed confidently, and ended `Recommendation: PROCEED`.

### Finding dispositions 8

| Finding | Disposition | Plan/code change or evidence |
|---------|-------------|------------------------------|
| Task 5C had no execution row and status stopped at Task 5B | Accepted | The status and Task 5C row below now record red, green, both independent reviews, and the uncommitted-WIP boundary. |
| Watch item routing was duplicated between the new adapter and legacy CLI | Accepted | `_rendering.emit_watch_item` now owns only Message-versus-Notification selection and delegates to the existing renderers. Both watch paths retain flush, EPIPE, signal, and watcher lifecycle policy locally. Its `taut.client` type import is function-local. |
| The first EPIPE test failed during `write`, which did not fire flush-before-handler-success | Accepted and corrected | The terminal NDJSON record is now written completely, arms the stream, and raises `BrokenPipeError` only from its following `flush()`. The real watcher exits 0 and the record remains unread, proving the cursor did not advance. |
| A filtered unjoined thread had no registry-path exit-class proof | Accepted and covered | A real SQLite/TautClient case now dispatches `watch missing` and fires `MembershipError` as exit 2 with no watcher double. |
| Real notification plus SIGINT cross only the legacy production entry point before cutover | Accepted, assigned to Task 5D | Task 5D's red/cutover list now explicitly requires the unchanged real-process watch test to exercise both records and SIGINT through registry-backed `main`; the closed-pipe subprocess also transfers unchanged. The controlled shadow test remains a narrow infinite-driver/lifecycle proof, not a claimed signal integration test. |
| Task 5C did not edit `_builtins.py`, `tests/test_cli.py`, or `tests/test_watcher.py` | Accepted scope adjustment | The watch manifest already existed in its now-spec-ordered tuple. The unchanged CLI and 70-test watcher suites are stronger parity/domain oracles than performative edits and were run in the final gate. New adapter behavior and import ownership belong in registry and architecture tests. |
| A fresh-process `sys.modules` proof would currently fail because importing any `taut` submodule executes the eager public facade | Accepted planned boundary | Task 6 already owns `taut/__init__.py`, the lazy public exports, and the fresh-process import floor. Task 5C pins exact module-level and function-local import sets, including no direct `taut.watcher` import. |
| Broken-pipe watch closes the injected stdout stream | Accepted compatibility behavior to document | This matches the legacy process contract and prevents interpreter-shutdown EPIPE noise. Task 12 must call out that an embedding host which supplies a stream to long-running watch transfers terminal-sink ownership for that watch lifetime. |

### Independent implementation-slice reviews: Task 5D (2026-07-13)

A read-only subagent first mapped the cutover sequence, parser traps, reserved
compatibility lifecycle, and installed-console gate. After implementation, the
first tool-less Claude review reported that the supplied diff was too large to
review reliably. The same Claude session was therefore resumed with only
read-only `Read`, `Grep`, and `Glob` access and allowed to run to completion for
roughly six minutes. It inspected the actual implementation, tests, packaging,
and plan. Its first substantive pass found no blocker and ended
`Recommendation: PROCEED`; every concrete advisory was fixed or assigned to
its exact later owner. A second read-only pass verified those changes, found
only the residual `-qh`/`-th` compatibility edge, and again answered that the
remaining plan is implementable confidently with `Recommendation: PROCEED`.
That final edge then received its own red-green fix.

### Finding dispositions 9

| Finding | Disposition | Plan/code change or evidence |
|---------|-------------|------------------------------|
| Released pre-verb argparse bundles such as `-tq`, `-qt`, `-qh`, and `-th` regressed under the manual root splitter | Accepted and fixed red-green | Direct root tests failed first. `_consume_root_short_bundle` now preserves only the existing `t`/`q`/`h` bundle vocabulary before the verb; unknown characters still fail loudly. Help bundles exit 0 through the same root-help path. |
| The opaque Summon adapter depended on argparse preserving a synthetic `--`, with no Python 3.11 proof or firing failure branch | Accepted and covered | Separator validation now precedes package discovery, the missing-sentinel branch fires directly, and the installed Python 3.11 console proves `summon --help` and `-- summon` reach the absence adapter only when the sentinel survives. The development suite separately proves real-extension opaque tails, help `SystemExit(0)`, DB placement, and dismiss mapping. |
| Parser-declared global actions appeared to be a second live value path even though exact globals are extracted first | Accepted and simplified | Dead `_merge_parsed_globals` plumbing was deleted. `_add_declared_globals` now documents that its actions own help visibility and near-miss rejection only; an exact-global namespace test proves no `_root_*` field leaks to adapters. |
| Built-in dispatch still loads every installed manifest | Accepted Task 6 boundary | Task 5D's immutable snapshot is semantically correct. Task 6 now explicitly requires static-only registry selection for known core verbs plus an observable installed-manifest import floor, while retaining complete discovery for root help, external verbs, and reserved slots. |
| The shipped console test covered fixture discovery but not the full root grammar gate | Accepted and covered | The real wheel's Python 3.11 `taut` executable now fires no-command, help, short help, version, unknown root, unknown verb, missing value, `-- say`, `-- summon`, and Summon sentinel behavior with stream and traceback assertions. |
| Root option vocabulary was repeated without a consistency gate | Accepted proportionate guard | A firing test ties `_ROOT_LONG_OPTIONS` exactly to `GlobalOption` plus help/version and requires every spelling in root help. Existing parametrized tests separately execute every documented post-verb spelling. A generic option framework remains deliberately out of scope. |
| A parser red could touch the checkout database and left `.taut.db.lock` unignored | Accepted | The `join --tok` red now supplies a temp DB. `.taut.db.lock` is ignored and the generated artifact was removed. |
| The temporary reserved-slot rejection could be reused accidentally for the official owner, and the old CLI bridge lifetime was implicit | Accepted Task 7 boundary | Task 7 now names normalized `taut-summon` as the sole official owner, forbids reuse of the blanket Task 5D rejection, and requires old `run`/`stop` CLI compatibility for one full paired-release cycle before bridge removal. |

### Independent implementation-slice review: Task 6 (2026-07-13)

After the author red-green pass, a fresh read-only Claude review inspected the
actual facade, dispatcher, registry shortcut, architecture tests, installed
Python 3.11 artifact probes, specs, and this plan. The review was allowed to run
to completion for several minutes with only `Read`, `Grep`, and `Glob` access.
It found no seam rework, verified that built-ins alone use the static registry
while root help, external commands, and reserved slots retain full discovery,
and confirmed that runtime `say` and `watch` isolation is tested beyond help
parsing. It explicitly found `__dir__` to be justified compatibility for the
previous eager facade, answered that Task 7 can be implemented confidently and
correctly, and ended `Recommendation: PROCEED`.

### Finding dispositions 10

| Finding | Disposition | Plan/code change or evidence |
|---------|-------------|------------------------------|
| A runtime module `__getattr__(name) -> Any` caused mypy to accept misspelled public exports | Accepted and fixed red-green | A subprocess mypy probe first accepted `taut.TautCleint`. The runtime `__getattr__`/`__dir__` definitions now live under `if not TYPE_CHECKING`, so the explicit type-checking imports own static lookup. The same probe now rejects the typo, while runtime caching, unknown-name `AttributeError`, `__all__`, and pre-load `dir(taut)` tests remain green. |
| Task 6 had no execution-evidence row | Accepted | The Task 6 row below records its named red floors, final 376-test gate, static-analysis gates, independent review, and uncommitted-WIP boundary. |
| Registry cache initialization is unsynchronized for threaded embedders | Accepted as a documented non-goal | `_default_registry` and `_static_registry` now state their process-local, single-threaded CLI contract. A threaded embedder can only build equivalent immutable snapshots redundantly; the last assignment wins. No synchronization framework is added without an embedding requirement. |

### Independent implementation-slice review: Task 7 (2026-07-13)

A read-only reconnaissance agent first mapped the exact reserved-slot policy,
artifact states, verifier split, and removal ambiguity without editing files.
After implementation, a fresh Claude review ran for roughly nine minutes with
only `Read`, `Grep`, and `Glob` access. It inspected the actual registry,
dispatcher, compatibility bridge, isolated-wheel fixtures, both artifact
verifiers, specs, repository refs, and this plan. It confirmed normalized
ownership, per-slot independence, fail-closed official errors, deterministic
ordering, real installed-wheel policy states, and the separate immutable 0.5.0
reactor and 0.5.4 command-rollout floors. It found no premature Task 10/11
implementation, answered that Task 8 can be implemented confidently and
correctly, and ended `Recommendation: PROCEED`.

### Finding dispositions 11

| Finding | Disposition | Plan/code change or evidence |
|---------|-------------|------------------------------|
| Task 7 had no execution row or plan-recorded bridge removal condition | Accepted | The Task 7 row below records named reds, gates, review, scope adjustment, and uncommitted status. The exact boundary is: retain the bridge in 0.6.0 for Summon 0.5.4; remove it only in a later paired release where 0.6.0 is the immediately previous supported Summon, contains both entry points, and 0.5.4 support has ended. |
| Distribution metadata/version access occurred outside the per-entry-point failure guard | Accepted and fixed red-green | New metadata- and version-fault cases first escaped registry construction with tracebacks. Provenance now starts at explicit unknown values and resolves inside the same guarded block as manifest loading. Root help lists the affected command unavailable, emits the preserved cause once, and remains exit 0. |
| The immutable Summon 0.5.4 rollout probe exercised only `run`/`stop` help | Accepted and strengthened red-green | The verifier probe still proves root help does not import Summon and both help surfaces map correctly, then executes real `taut dismiss nobody --db PATH` through the old `stop` path. It requires exit 2, the legacy diagnostic plus forwarded DB path, no stdout, and no database creation. |
| Repository map still described a four-case verifier | Accepted | The map now describes the six retained-reactor/control/resolver and command-rollout artifact cases. Task 12 remains responsible for the wider architecture narrative. |
| `tests/conftest.py` was not in Task 7's predicted file list | Accepted scope adjustment | The shared installed-command fixture now builds but does not preinstall the actual Summon 0.5.4 wheel and can install additional wheels into disposable Python 3.11 environments. That is the narrow reusable infrastructure needed for the six required Task 7 artifact states. |

### Independent implementation-slice review: Task 8 (2026-07-13)

A read-only reconnaissance agent first mapped the existing CLI, driver,
ledger, control, public-facade, and real-process test boundaries without
editing files. After implementation, a fresh Claude consult ran for roughly
nine minutes with only `Read`, `Grep`, and `Glob` access. It inspected the
actual controller/models/facade, thin CLI, driver boundary, control/state
paths, tests, [SUM-13], implementation notes, and this plan. It confirmed one
controller orchestration path, typed results and errors, ACK-plus-release STOP,
validated defensive STATUS copies, lazy help/facade floors, and real anti-mock
proof. It found no seam rework, answered that Task 9 can be implemented
confidently and correctly, and ended `Recommendation: PROCEED`.

### Finding dispositions 12

| Finding | Disposition | Plan/code change or evidence |
|---------|-------------|------------------------------|
| The controller had no firing test that refused a correlated `status=error` STOP reply before release polling | Accepted and covered with real queues | A real SQLite test now starts a responder over the actual `sys.ctl_*` request queue, writes a correlated error reply to the request's real per-request queue, and requires the controller to raise the base `SummonOperationError` with the driver's error. The live evidence remains present; a wrong implementation would poll and raise `DriverUnresponsive` instead. No state, queue, control client, or driver is mocked. |
| Task 8 had no execution row or deviation record | Accepted | The two deliberate intermediate/interface-shape differences are recorded in section 11, and the Task 8 row below records red evidence, final gates, independent review, and the uncommitted-WIP boundary. |
| `_with_status_fault_plane` became dead code and resolve-stage classifications were unreachable | Accepted and fixed | The dead helper and its self-test were deleted. Controller member/session resolution now carries `resolve_member` or `resolve_session` on public operation errors. A real incompatible-schema CLI subprocess with the opt-in environment variable proves the resolve-session diagnostic, normal error, exit 1, and no traceback. The control fault attribute constant is imported from its one internal owner rather than duplicated. |
| `list_live()` raised `NothingSummoned` for an ordinary empty result, forcing polling hosts to use exceptions for an empty panel | Accepted API correction | `list_live()` now returns `()` for no database or no non-dead rows. The standalone CLI alone maps that empty result to its historical nothing-summoned message and exit 2. [SUM-13], section 7.4, tests, and implementation guidance state this boundary. |
| `fault_plane` is an undocumented public attribute and `_driver.py` still named the CLI as error owner | Partly accepted | The stale driver comment now names the controller, and the internal control attribute string has one owner. `fault_plane` remains a small opt-in diagnostic carried on the public base error because CLI rendering must not inspect private exception causes; it is not a domain result or control-reply leak. |
| The defensive `result != 0` driver branch is unreachable under current private return contracts | Retained as bounded defense | Private `_run` remains integer-returning in Task 8 to avoid a broad internal state-machine rewrite. The branch prevents a future accidental nonzero return from becoming typed success; it is not claimed as separately covered public behavior. |

### Independent implementation-slice review: Task 9 (2026-07-13)

A read-only reconnaissance agent mapped the old shell decision order, driver
pump/attach sites, PTY fd ownership, and missing real-host proofs before the
slice closed. A fresh Claude consult then ran for roughly seven minutes with
only `Read`, `Grep`, and `Glob`. It inspected the actual public protocol,
controller/CLI propagation, driver ordering, PTY bridge, specs, implementation
notes, and tests. It returned `Recommendation: FIX FIRST` for one pre-existing
startup-order documentation contradiction plus two public-boundary faults. All
three reproduced as named reds. After correction, a same-session review ran to
completion, verified each fix at its firing site, found no remaining P1/P2,
confirmed Task 10 is implementable as written, and returned
`Recommendation: PROCEED`.

### Finding dispositions 13

| Finding | Disposition | Plan/code change or evidence |
|---------|-------------|------------------------------|
| The retained [SUM-7.4] startup paragraph said every detached/no-tty path pumped early, contradicting the baseline driver, section 7.5, its matrix test, and a second implementation paragraph | Accepted as a governing-document correction | [SUM-7.4], the implementation note, section 7.5, and the deviation log now enumerate one matrix: forced detach, `NESTED_HOST`, and `UNAVAILABLE` early; `AVAILABLE` and `NO_TTY` delayed. The nine-case driver test fires every branch, and the real wired-resume proof pins one cached probe with no later lease. |
| `attach=True` plus `detach=True` started the pump under detach policy, then could enter a host lease and create two PTY-master readers | Accepted and fixed red-green | The real CLI now rejects the pair as usage exit 1 through one argparse mutual-exclusion group. The driver constructor independently raises typed `SummonOperationError` before any host probe, covering programmatic controller calls. CLI, driver, and public-controller tests fire. |
| Raw `OSError`, `ValueError`, or `termios.error` from `AdapterHandle.attach` escaped the typed public controller contract | Accepted and fixed red-green | The driver restores the lease first, preserves `AdapterError`, `DriverError`, and non-`Exception` base exceptions, and wraps other attach failures as `DriverError` with cause. A real PTY controller test grants invalid fds and requires public `SummonOperationError`, lease exit, released driver evidence, and `wired=False`. A separate test proves a restore failure cannot replace a primary attach failure. |
| `PtyHandle.attach` has no defensive `_reader_started` check | Not added | The driver is the policy owner, the overlap is now rejected at syntax and driver boundaries, and real ordering tests prove one reader. Adding a second state policy inside `_pty.py` would duplicate the owner without a remaining executable route. |
| `_cmd_run` retains a currently unreachable `NothingSummoned` mapping | Retained as harmless adapter symmetry | All public operation errors remain mapped in one CLI adapter pattern. Removing one subtype branch has no behavior or import benefit and is not required by [SUM-13]; no test or caller depends on its reachability. |

### Independent implementation-slice review: Task 10 (2026-07-13)

A fresh read-only Claude Code consult ran to completion for roughly fifteen
minutes with only `Read`, `Grep`, and `Glob` access. It inspected the plan,
governing specs, manifests, shared command adapters, both console surfaces,
parser protocol, installed Python 3.11 proofs, architecture boundaries, and
real driver lifecycle test. It found no code blocker, answered the required
question "If requested, could you implement this plan as written confidently
and correctly?" with **Yes**, confirmed Task 11 can proceed safely, and ended
`Recommendation: PROCEED`. Its required evidence correction and concrete DRY
and test-ownership observations were incorporated before this slice closed.

### Finding dispositions 14

| Finding | Disposition | Plan/code change or evidence |
|---------|-------------|------------------------------|
| Task 10 had no execution-evidence row or independent-review close-out | Accepted | The status and Task 10 row below now record the named reds, complete gates, review outcome, and uncommitted-WIP boundary. |
| Source-tree root Summon tests could select native adapters or the compatibility bridge depending on installed editable metadata, while comments claimed one path | Accepted and clarified | The comments now state that these semantic parity cases are deliberately owner-agnostic. Path-specific ownership remains proved in disposable Python 3.11 environments: core-only selects the hint bridge, current Summon selects both native entry points, and duplicate/broken official metadata never falls back. |
| Fault-plane vocabulary had a literal type, a set in shared command helpers, and an inline CLI set | Accepted and fixed DRY | `taut_summon.commands` now owns `StatusFaultPlane` and `STATUS_FAULT_PLANES`; native adapters and standalone status rendering consume those definitions. Existing real resolution/control fault tests fire the vocabulary. |
| A second literal `--` inside the already-literal thread tail can be normalized differently by Python 3.11 intermixed parsing and the standalone manual boundary parser | Not generalized | A thread literally named `--` is outside Taut's valid thread-name grammar. The parity matrix fires the meaningful leading and mid-tail separator forms, including option-shaped names and threads. Adding a bespoke multi-separator normalization policy would broaden argparse emulation for an invalid operand. |
| CLI logging uses process-global `logging.basicConfig`, which is a no-op after a host configures logging | Accepted released CLI behavior; documented boundary | The implementation guide now states that console logging configuration is best-effort and process-global. Rich embedding hosts call `SummonController` directly and own logging policy; no controller method mutates logging. |
| Missing-value wording for a dispatcher-hoisted `--db` differs from the old argparse wording | Accepted generic command-protocol behavior | Exit 1, stderr routing, and traceback absence are unchanged. The generic dispatcher owns this exact missing-global-value contract, already fired before and after verbs; Summon adapters must not reproduce a second parser merely to retain one noun. |
| The installed import-floor probe covered only `summon --help` | Accepted and covered | The real Python 3.11 installed-wheel import-floor test is now parameterized over both `summon --help` and `dismiss --help`; both configure their command module without importing controller, driver, control, state, adapter, PTY, SimpleBroker, or core client/state runtime. |

### Independent implementation-slice review: Task 11 (2026-07-13)

A read-only subagent audited the artifact verifier before and after the release
slice. The first pass found the stale paired probe's removed private CLI
imports, the missing distinct `v0.5.4` core input, hard-coded 0.5.0 resolver
diagnostics, and the need to validate exact entry points in the fresh wheels.
After those fixes, the real 0.6.0 six-case wheel matrix passed. The closure pass
then withheld approval for stale README pins and a compile test that did not
prove native root invocation. Both gaps were fixed, the exact focused gate
passed 13 tests, and the final review returned **PROCEED** with no unresolved
Task 11 finding.

### Finding dispositions 15

| Finding | Disposition | Plan/code change or evidence |
|---------|-------------|------------------------------|
| The paired artifact probe imported removed private `taut_summon.cli` state helpers | Accepted and fixed | The probe now starts `python -m taut ... summon`, observes readiness and STATUS through public `SummonController`, stops through `python -m taut ... dismiss`, and proves release. Its source test forbids the private/standalone path and pins two native root invocations. |
| The old-core rejection reused `v0.5.0`, contrary to the command-rollout matrix | Accepted and fixed without replacing older proof | A separate immutable `--previous-command-core-ref v0.5.4` is resolved, archived, built, and used for new-Summon rejection. The existing core/Summon 0.5.0 refs and new-core/old-Summon reactor case remain intact. |
| Fresh artifacts were not themselves checked for command entry-point placement | Accepted and fixed | Wheel metadata parsing now requires no `taut.commands` entries in core and exact `summon`/`dismiss` entries and targets in Summon before any installed case runs; the paired installed probe independently confirms `taut-summon` ownership. |
| Resolver diagnostics were hard-coded to core 0.5.0 | Accepted and fixed | The resolver case takes the prior core version explicitly. Release proof uses 0.5.4; focused grammar tests retain independent older-version coverage. |
| Metadata sync had no retained-lock assertion | Accepted and fixed | The package consistency test requires exactly one locked `taut` and `taut-summon` record at the coordinated version; `uv lock --check` passes. |
| README pins made the coordinated metadata gate fail after the version bump | Accepted as Task 11/12 boundary sequencing | Task 12's first documentation edit moved all root, PG, and Summon examples to 0.6.0, after which the complete metadata test passed. |

### Independent implementation-slice review: Task 12 (2026-07-13)

A fresh read-only agent was asked to reconstruct the registry and
local/static-versus-installed extension integration from documentation alone.
Its first pass found that the design intent was clear but cache timing,
entry-point identity, distribution normalization, package dependency floors,
unavailable-help behavior, root-global merging, and the distinct built-in and
extension author workflows still required inference. The spec, implementation
guide, runnable wheel fixture, index, repository map, and firing-test map were
corrected. The same agent reread the current files, returned **PROCEED**, and
confirmed a zero-context agent can now identify the owners, integration flow,
packaging contract, lazy boundary, edit locations, and acceptance gates. Its
only non-blocking wording nit about installed versus static snapshots was also
removed.

### Finding dispositions 16

| Finding | Disposition | Plan/code change or evidence |
|---------|-------------|------------------------------|
| Repository locality could be mistaken for command registration | Accepted and specified | [TAUT-8.6] and `docs/implementation/06-command-extensions.md` now state that discovery follows installed metadata in the active interpreter, never filesystem scanning; monorepo editable installs and published wheels use the same entry-point path. |
| Registry cache creation and install/uninstall visibility were implicit | Accepted and specified | The docs name the no-registry version path, static built-in snapshot, installed snapshot used by help/reserved/external selection, process immutability, and next-process visibility. Named lazy/import and install/uninstall tests fire the contract. |
| Entry-point key/name, owner normalization, and broken-help selection required code reading | Accepted and specified | The key must equal `CommandSpec.name`; failed loads remain owned by the key; package normalization is lowercase plus collapsed `[-_.]+`; unavailable rows and warnings, built-in immunity, and valid-plus-broken conflicts are explicit with named firing tests. |
| The runnable fixture did not require a core containing command API version 1 | Accepted and fixed | The fixture now requires `taut>=0.6.0`; a focused metadata test pins the API-introduction floor. |
| One checklist conflated core built-ins and installed extensions | Accepted and split | The guide now gives separate file, packaging, artifact, lazy-import, and documentation actions for each ownership path, plus a complete root-global spelling/merge table. |

### Independent tooling-name review (2026-07-13)

A read-only same-family pass checked the five file moves and every live
consumer. It found two remaining P3 labels: one temporary-directory prefix and
one release-test name. Both now use wheel-matrix or release-wheel language. A
fresh Claude review then checked the release helper, reusable workflows,
historical refs, case count, ordering, and maintained documentation. It found
no rename wiring or behavior defect. It did identify the pre-existing [SUM-12]
ambiguity between four reactor combinations and six reported cases.

### Finding dispositions 17

| Finding | Disposition | Plan/code change or evidence |
|---------|-------------|------------------------------|
| The matrix checker still used `taut-reactor-artifact-` as its temporary root and one release test still said `verifies_fresh_paired_artifacts` | Accepted and fixed | The temporary root is `taut-wheel-matrix-`; the test names the fresh paired release-wheel check. |
| [SUM-12] said four installed-artifact combinations while the checker reported six cases | Accepted as a pre-existing traceability gap and fixed | [SUM-12] now distinguishes the four reactor combinations from two additional command-rollout cases and keeps the immutable 0.5.0 and 0.5.4 floors separate. |
| The full networked six-case matrix was not rerun for this naming-only slice | Accepted at slice time; resolved by Task 13 | Wiring, focused tests, static checks, help surfaces, and the ordered dry run were the naming-slice proof. Task 13 subsequently rebuilt current 0.6.0 wheels, fetched both 0.5.0 and 0.5.4 historical ref families, and passed all six installed cases through the renamed entry points. |

### Claude final completed-work review (2026-07-13)

A fresh read-only Claude session spent about ten and a half minutes inspecting
the full plan, promoted specs, implementation docs, core and Summon code,
package metadata, release tooling, workflows, and firing tests. It found no
implementation defect, eager-import leak, core/extension boundary violation,
private-module reach, over-mocked contract proof, or speculative plugin
machinery. It returned `Recommendation: PROCEED` and answered the required
question, "If requested, could you implement this plan as written confidently
and correctly?", with **Yes**.

The review found one P2 evidence gap and two P3 traceability/hygiene gaps. The
same Claude session receives the corrected current files and final gate record
for closure before handoff.

### Finding dispositions 18

| Finding | Disposition | Plan/code change or evidence |
|---------|-------------|------------------------------|
| Task 13 had no current-state full-gate row after the documentation and tooling-name slices | Accepted and fixed | Every section 14.2 behavior/static/build gate was rerun, the explicit Python 3.11 installed-wheel probe passed 21 cases, the networked renamed six-case matrix passed, and the Task 13 row below records exact results. |
| Task 7/11 evidence still named removed artifact files, and the five-file tooling rename lacked a single old-to-new owner mapping | Accepted and fixed | The historical rows now use the current executable test/checker names. The deviation log explicitly maps all five old names to their replacements, assigns the rename to process tooling, and explains why historical plans retain their original names. |
| `.context/` Claude session scratch could be swept into a broad commit | Accepted and fixed without widening `.gitignore` | The final prompt and session-id files are deleted after the same-session closure review. No repository behavior depends on `.context/`, and the final status gate proves it is absent. |

## 19. Execution Evidence Log

Tasks 1-13 are implemented and verified as uncommitted work. Task 1 promoted
the reviewed spec delta and production dispatch uses the registry-backed
command protocol through the thin `taut.cli` entry point. No commit, tag, push,
or publication was made; under the repository completion rule this is a
verified handoff, not a claim that the work is ready to land.

### Required-reading comprehension answers

1. Root help needs only names, summaries, order, provenance, and availability,
   all supplied by lightweight manifests. It must not resolve implementation
   targets. After `taut --help`, client/state, watcher, Summon controller and
   driver, provider adapters, PTY, and TUI modules must remain absent.
2. Built-ins use static registration because a source checkout need not expose
   installed distribution metadata. Core verbs are part of the core contract
   and cannot disappear merely because entry points are unavailable.
3. The current dispatcher removes the selected `summon`/`dismiss` token before
   argparse and passes every remaining token to `taut_summon.cli` after only the
   verb mapping. The replacement gives those reserved manifests only the `DB`
   post-verb global, honors literal `--` as the end of root interpretation, and
   passes the untouched remaining tail to the selected standalone parser.
4. `rejoin` omits `GlobalOption.TOKEN`, so `rejoin --token TOKEN` belongs to
   the command parser. A token before `rejoin` remains a root selector. The
   grammar matrix must fire both forms, their precedence, and the existing
   name-plus-token exclusivity error.
5. A TUI needs typed domain results and errors that survive rendering changes.
   Calling a console command would make human/NDJSON text a second interface
   and still would not safely expose foreground ownership or terminal leasing.
6. `taut_summon._pty` and its adapter handle own PTY fd epochs, operation/write
   leases, the attach bridge and detach result, terminal-reset bytes, and fd
   cleanup. The controller chooses the lifecycle operation; a host interaction
   reports availability and leases terminal fds but never duplicates PTY state.
7. `SummonController.run_foreground` is blocking because it owns exactly one
   complete foreground driver lifecycle and its cleanup. A future TUI must
   separately specify process supervision, the terminal-release handshake, log
   routing, exit/orphan policy, and rollback before it may manage that work
   without blocking its render loop.

| Slice | Red evidence | Green evidence | Review | Commit/baseline |
|-------|--------------|----------------|--------|-----------------|
| Task 1 spec promotion | Docs-only TDD exception; reviewed delta and reference checker are the substitute proof | `uv run pytest tests/test_docs_references.py -n 0`: 10 passed | Two independent plan reviews plus author pass 3; implementation-slice review still required | `b0370945` plus the exact uncommitted two-spec diff recorded in section 4 |
| Tasks 2-3 command protocol/registry | Public-surface test failed with `ModuleNotFoundError: taut.commands`; static registry test then failed with `ModuleNotFoundError: taut.commands._registry`; installed selection failed until `_dispatch.py`; conflict and literal-before-verb tests each failed at their named policy. Review follow-up separately reproduced parse `SystemExit`, parser-global leakage, speculative reply rendering, and arbitrary-`BaseException` failures before fixing them. | `uv run pytest tests/test_command_registry.py -n 0`: 49 passed, including a real current-core + fixture-wheel install in Python 3.11; focused review corrections are green. Final static and unchanged-CLI gates are rerun after this documentation reconciliation. | Independent Claude implementation-slice review completed; all blocking findings fixed and lower-risk findings assigned to their exact future owners. | Uncommitted worktree against promotion baseline |
| Task 4 `say` adapter and shared renderer | First direct real-state test returned exit 1 because `taut.commands.say` did not exist. After the adapter tracer, a real DM observability assertion failed because public `log()` correctly rejects internal DM queue names; the test was corrected to use Bob's public unread surface rather than weakening production. Claude follow-up help text failed before declared-global descriptions were added. | `uv run pytest tests/test_cli.py tests/test_cli_probes.py tests/test_command_registry.py tests/test_architecture_boundaries.py -n 0 -q`: 165 passed after review follow-ups. The Task 4 matrix uses real SQLite/TautClient for persistence, routing, notification, and cleanup behavior; only pure stream/parser ports use narrow test doubles. Ruff and mypy over the slice passed; `git diff --check` was clean. | Independent Claude Task 4 review found no seam rework; all evidence and concrete P2 findings were incorporated or explicitly bounded above. | Uncommitted WIP; not declared ready to land and not committed on the user's behalf. |
| Task 5A identity and membership adapters | All six adapter help cases first failed because their modules did not exist. The real lifecycle case then exposed a test assumption that `join --as` created an alias; the baseline correctly treats it as identity selection, so the test was repaired rather than production. Claude follow-up reproduced twelve missing-global-value failures before `_consume_global` changed. | `uv run pytest tests/test_command_registry.py tests/test_architecture_boundaries.py tests/test_cli.py tests/test_cli_probes.py -n 0 -q`: 207 passed (110 registry, 14 architecture, 73 CLI, 10 probes). The matrix uses real SQLite/TautClient for identity and membership behavior; formatter, Ruff, and mypy passed over all touched Python files; docs references passed 10 tests; `git diff --check` was clean. | Independent Claude Task 5A review found no seam rework. Its parser defect and concrete test/format gaps are fixed; its abbreviation concern is an explicit Task 5D cutover gate. | Uncommitted WIP; not declared ready to land and not committed on the user's behalf. |
| Task 5B read/thread adapters | Six help cases first failed with missing adapter modules; after parser-only tracers made help green, eight real-state behavior tests failed on the named not-implemented adapters. The promoted table-order test separately failed at `set` before the manifest moved. | `uv run pytest tests/test_command_registry.py tests/test_architecture_boundaries.py tests/test_cli.py tests/test_cli_probes.py -n 0 -q`: 229 passed (126 registry, 20 architecture, 73 CLI, 10 probes). The registry cases use real SQLite/TautClient for reply resolution, cursor movement, log filtering, list/DM metadata, notification consumption, sub-thread rename, and rename recovery; only a post-write warning fault is injected. Formatter, Ruff, and mypy passed over 23 touched Python files; docs references passed 10 tests; `git diff --check` was clean. | Independent Claude Task 5B review found no seam rework and answered that 5C can proceed confidently. All P1/P2 findings were incorporated before this row. | Uncommitted WIP; not declared ready to land and not committed on the user's behalf. |
| Task 5C long-running watch adapter | Adding `watch` to command help first failed because `taut.commands.watch` did not exist. After a parser-only tracer made help green, the controlled lifecycle and real watcher tests both failed on the named not-implemented adapter. The real test initially failed at write by construction; review tightened the proof to fail on flush after the terminal record was written, without changing production behavior. | `uv run pytest tests/test_command_registry.py tests/test_architecture_boundaries.py tests/test_cli.py tests/test_cli_probes.py tests/test_watcher.py -n 0 -q`: 304 passed (130 registry, 21 architecture, 73 CLI, 10 probes, 70 watcher). Real SQLite/TautClient proves live flush, dynamic membership, EPIPE exit 0, and unread cursor preservation; the narrow controlled driver proves both item shapes, per-item flush, SIGINT cleanup, and exact stop/client-close ordering. Formatter, Ruff, and mypy passed over 24 touched Python files; docs references passed 10 tests; `git diff --check` was clean. | Read-only subagent and independent Claude reviews found no seam rework. Every concrete finding is fixed, covered, or assigned to the exact Task 5D/6/12 gate above. | Uncommitted WIP; not declared ready to land and not committed on the user's behalf. |
| Task 5D init, reserved compatibility slots, root grammar, and atomic CLI cutover | `init` help/execution first failed because its adapter module did not exist. Exact table-order tests then failed on absent `summon`/`dismiss`; post-verb `--quie`, pre-verb abbreviations, bundled short flags, diagnostic rendering, the isolated console lifecycle method, and the old production unknown-root wording each failed at their named red before implementation. | `uv run pytest tests/test_command_registry.py tests/test_architecture_boundaries.py tests/test_cli.py tests/test_cli_probes.py tests/test_watcher.py -n 0 -q`: 359 passed (176 registry, 23 architecture, 80 CLI, 10 probes, 70 watcher). The unchanged real-process watch tests now cross registry-backed `main` for notification plus SIGINT and terminal EPIPE cursor preservation. A real Python 3.11 wheel console proves root grammar, entry-point install/uninstall, and Summon sentinel behavior. Ruff passed; mypy passed over 28 files; docs references passed 10 tests; `git diff --check` was clean. | Read-only subagent plus two substantive Claude passes found no blocker and twice returned `Recommendation: PROCEED`. Every concrete P2 was fixed red-green or assigned to the exact Task 6/7/12 owner; the last follow-up bundle edge was fixed after review. | Uncommitted WIP; not declared ready to land and not committed on the user's behalf. |
| Task 6 lazy facades and built-in registry shortcut | The five fresh-process import floors initially failed because the public facade and constants were eager. Real `say` loaded watcher internals, and an installed core verb imported an unrelated synthetic manifest. A separate introspection red showed lazy names missing from `dir(taut)`. Review then added a firing mypy red in which `taut.TautCleint` was incorrectly accepted. | `uv run pytest tests/test_public_api.py tests/test_lazy_imports.py tests/test_command_registry.py tests/test_architecture_boundaries.py tests/test_cli.py tests/test_cli_probes.py tests/test_watcher.py -n 0 -q`: 376 passed (5 public API, 9 lazy imports, 176 registry, 26 architecture, 80 CLI, 10 probes, 70 watcher). Fresh subprocesses pin exact import floors; a real Python 3.11 wheel proves core dispatch skips an observable installed manifest while root help and reserved slots discover it. Ruff passed over `taut` and `tests`; mypy passed 77 source files; docs references passed 10 tests; `git diff --check` was clean. | Independent Claude review checked every Task 6 seam, found no blocker, and returned `Recommendation: PROCEED`. All three P2 findings are fixed or explicitly bounded above. | Uncommitted WIP; not declared ready to land and not committed on the user's behalf. |
| Task 7 reserved Summon ownership and artifact compatibility | Seven focused registry cases first failed because every installed reserved claim was rejected in favor of compatibility. Four verifier/ref-propagation tests then failed on the absent 0.5.4 input; the multi-commit archive, command-only verifier cases, and historical-wheel builder each failed at their named missing seam. Review added two provenance faults that escaped with tracebacks and a legacy non-help execution assertion that was absent from the immutable probe. | `uv run pytest tests/test_command_registry.py tests/test_core_summon_wheel_matrix.py -n 0 -q`: 240 passed (187 registry, 53 artifact). Six disposable Python 3.11 installed-wheel states prove core-only hint, actual Summon 0.5.4 bridge, unofficial claim, official-plus-unofficial precedence, duplicate official failure, and broken official failure with loud legacy code present. The neighboring CLI/lazy/watcher integration gate passed 435 tests after review fixes; Ruff formatting/check, mypy over 77 files, docs references, and `git diff --check` passed. The release verifier retains immutable 0.5.0 reactor refs and adds the separately pinned `taut_summon/v0.5.4` bridge probe; Task 11 owns the actual post-version-sync full verifier run. | Read-only reconnaissance plus independent Claude review found no seam rework. Claude returned `Recommendation: PROCEED` and confirmed Task 8 is implementable; every P2 is fixed above. | Uncommitted WIP; bridge retained in 0.6.0 and removable only under the exact later-release condition in Finding dispositions 11. |
| Task 8 typed Summon controller and lazy public facade | The first four controller tests failed on missing exports; real status failed on the absent method; four help floors loaded SimpleBroker/client/control/state/driver modules; three driver-boundary tests still printed and returned 1; and twenty PTY conformance probes exposed an uncaught adapter-construction error after the CLI cutover. Review then made empty-list semantics fail red before the controller returned `()`. | Public model/facade, real list, real driver STATUS/STOP, real-queue timeout/error-ACK, validation/copy, mypy typo, and help-floor tests pass. The ordinary extension lane, full driver suite, and serialized deterministic process lane pass. The combined controller/CLI/control/driver plus core architecture/lazy/registry/CLI gate reached 100%. Ruff reports 111 files formatted and all checks passed; core mypy passed 77 files; extension mypy passed 31; docs references passed 10; `git diff --check` is clean. | Read-only reconnaissance, a fresh nine-minute Claude review, and a same-session closure review found no seam rework. The follow-up verified every prior finding against the corrected code, found no new P1/P2, returned `Recommendation: PROCEED`, and confirmed Task 9 is implementable. Every concrete P2 is fixed, covered, or explicitly bounded in Finding dispositions 12. | Uncommitted WIP; Task 9 replaced the temporary foreground signature with the required explicit interaction. |
| Task 9 Summon host interaction | Ten public/facade cases first failed because the interaction module and exports did not exist. Thirteen driver-policy cases then failed on the missing injected interaction, availability sample, and early-pump matrix; the CLI architecture gate failed on the new unrecorded local import. Three exact termios comparisons exposed macOS's kernel-managed `PENDIN` bit and were corrected to compare every host-controlled field. Claude review added four firing reds: the attach/detach pair reached execution, the driver constructor accepted it, raw attach I/O escaped, and a real invalid-fd controller run leaked `ValueError`. | Exact public shapes, shell precedence, required controller signature, every availability/flag branch, reason-specific errors/warnings, finite attach results, acquire/restore and primary-error precedence, and lazy import boundaries pass. Real PTY/controller tests prove non-default fds, one lease on first attach, no lease on wired resume, STOP during attach, reset/termios restoration, typed invalid-fd failure, released evidence, and `wired=False`. Ordinary and serialized process lanes reached 100%; the combined interaction/driver/PTY/architecture gate reached 100%. Ruff reports 34 files formatted and all checks passed; extension mypy passed 32 files; docs references passed 10; `git diff --check` is clean. | Read-only reconnaissance identified the shell-precedence ambiguity and missing real-fd/order proofs. A fresh seven-minute Claude review returned `FIX FIRST` with one spec contradiction and two boundary bugs. All three failed red before correction. Its same-session closure review verified the fixes, found no remaining P1/P2, confirmed Task 10 is implementable, and returned `Recommendation: PROCEED`. | Uncommitted WIP; no TUI product, daemon lifecycle, control ATTACH verb, or provider plugin surface was added. |
| Task 10 native Summon commands | Four focused contract tests first failed because the manifest module, entry-point metadata, and shared command factories did not exist. The installed Python 3.11 parity matrix then failed when ordinary root argparse rejected a thread after `--provider`, and failed again when intermixed parsing lost a leading literal `--`; both failures preceded the opt-in parser policy and its leading-separator carve-out. The architecture allowlist failed on each newly visible lightweight import. | Exact manifests and provenance, native help, absent-package hint, both standalone factories, root/standalone error parity, interspersed threads, leading and mid-tail literal separators, and both installed help import floors pass in disposable Python 3.11 environments. A real SQLite and real scripted-provider process proves native `taut summon` startup and `taut dismiss` STOP/release success. The complete affected CLI/registry/artifact/architecture/lazy/public/Summon controller and CLI gate passed all 436 collected tests; Ruff format/check, 10 docs-reference tests, mypy over 112 files, and `git diff --check` pass. | A fresh roughly fifteen-minute Claude review found no blocker, explicitly answered that the plan is implementable confidently, confirmed Task 11 can proceed, and returned `Recommendation: PROCEED`. Its evidence P1 and concrete DRY/test-ownership findings are fixed or dispositioned in Finding dispositions 14. | Uncommitted WIP; the 0.5.4 bridge remains for paired rollout, and versions/changelog remain Task 11/12-owned. |
| Task 11 release metadata and artifact gates | Seven focused tests failed on the absent separate 0.5.4 core input/builder, missing exact wheel entry-point validation, and stale private-CLI paired probe. The selected 0.6.0 value itself was treated as release metadata rather than forced through a performative literal red; existing synthetic 0.6.0 rejection remained a regression guard. | Core, PG, and Summon metadata/floors plus the retained Summon lock are coordinated at 0.6.0. `uv run python bin/build-and-check-release-wheels.py` built fresh wheels and passed all six installed cases: retained 0.5.0 reactor evidence, new-new native root lifecycle and public STATUS, 0.5.4 old-core rejection, core-only hint, and 0.5.4 bridge. The focused artifact/release/metadata gate passed 118 tests; closure docs/metadata/probe gate passed 13; `uv lock --check`, Ruff, and `git diff --check` pass. | A read-only subagent performed initial, closure, and final closure passes. It blocked twice on concrete evidence gaps, verified their fixes, then returned **PROCEED** with no unresolved finding. | Uncommitted WIP; no build artifact, commit, tag, push, or publication was retained or performed. |
| Task 12 documentation and traceability | Documentation-only TDD exception: the substitute proof was a zero-context agent reconstruction audit plus maintained-reference, metadata, and release dry-run gates. Its first pass returned BLOCK because several edge rules still required implementation reading. | Added `docs/implementation/06-command-extensions.md`; aligned both specs, architecture docs, index, map, READMEs, the runnable extension fixture, changelog, and this execution log. Root, PG, and Summon install examples and manifests are 0.6.0. The exact registry-handoff focused tests passed 13 cases; docs references passed 10; `uv run python bin/release.py all --dry-run --skip-checks` reported all three unpublished 0.6.0 targets and printed the paired verifier with both historical ref families. | The same zero-context agent reread the corrected documentation and returned **PROCEED**. Every blocking ambiguity was specified and linked to a firing test; its final wording nit was also fixed. | Uncommitted WIP; Task 13 owns the final complete suite and independent adversarial review. |
| Tooling entry-point naming cleanup | Naming/docs-only TDD exception: existing workflow, release-order, coverage-data, and matrix tests were the substitute proof; no gate behavior was added. | Live entry points are now `check-required-coverage-paths.py`, `build-and-check-release-wheels.py`, and `check-core-summon-wheel-matrix.py`; matching test files, workflow input, release-helper symbol, maintained docs, and active commands agree. The 138-test focused gate passed; Ruff and format checks passed over eight files; mypy passed over eight files; `git diff --check`, live-old-reference grep, all three help surfaces, and the ordered dry run passed. | A same-family review found two stale labels, both fixed. A fresh Claude review found no rename wiring or behavior defect and identified the [SUM-12] case-count ambiguity, now clarified. | Uncommitted WIP. Task 13 later reran the renamed networked six-case matrix successfully. |
| Task 13 final adversarial acceptance | Acceptance/evidence task: no product behavior red was required. Claude's final P2 reproduced the missing current-state acceptance row after the Task 12 and tooling-name edits. | Current-state gates: root 768 passed; real Postgres 138 shared plus 13 PG passed; Summon ordinary 228, serialized real-process 223, strict live-harness 18, and strict local-LLM 6 passed. Twenty-one explicit Python 3.11 installed-wheel cases passed. Ruff passed and 117 files were formatted; mypy passed 77 root, 37 Summon, and 6 PG files; all three 0.6.0 sdists/wheels built; `uv lock --check` passed; and `bin/build-and-check-release-wheels.py` fetched both historical ref families and passed all six installed cases. The post-edit documentation/metadata/workflow/release/coverage gate passed 74 tests; final docs references and `git diff --check` passed. | Fresh Claude completed-work review found no implementation defect, answered the required implementability question **Yes**, and returned `Recommendation: PROCEED`. Same-session closure found no remaining P1, P2, or P3, confirmed the registry/extension docs require no implementation inference, answered **Yes** again, and returned `Recommendation: PROCEED`. | Uncommitted verified handoff. No commit, release, tag, push, or publication was performed. |

Task 3 process note: selected implementation-failure and cleanup-precedence
tests added after the first dispatcher tracer bullet were born green because
that bullet already implemented the common selected-load/error/finally edge.
They are retained as regression guards and are not claimed as red evidence.
No behavior exemption is inferred for later slices; subsequent work returns to
one named red before its implementation.
