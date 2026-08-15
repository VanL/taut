# Cross-Surface Command Capability Plan

Date: 2026-08-14

Status: deferred by owner decision; indexed as `status-review` because the
closed [DOM-14] lifecycle vocabulary has no `deferred` value; no implementation
authority

Owner: Taut maintainers

Class: 5 — the change adds a normative cross-surface command contract and
changes the typed registration interfaces consumed by core, MCP, and TUI

Plan type: implementation with spec revision

Hardening: required — this changes a public compatibility surface and must keep
one semantic inventory coherent across three independently packaged execution
contexts

## Goal

Make the core command specification the canonical inventory of executable Taut
command capabilities, then require the CLI, MCP, and TUI to declare how each
capability is exposed or why it is intentionally absent. Keep each surface's
native grammar, validation, rendering, and interaction flow independent. The
shared contract supplies semantic identity and coverage only; it does not
generate argparse parsers, MCP schemas, or TUI forms.

This replaces the MCP-local `CLI_CAPABILITY_TO_MCP_TOOL` inventory with one
core-owned capability vocabulary and extends the same conformance discipline to
the TUI. Surface-local operations remain legal, but they must be classified as
such instead of looking like unmapped core commands.

## Deferral Decision

Owner decision (2026-08-14): defer this entire initiative. The deferral covers
both the locked cross-surface design below and the narrower MCP-only alternative
identified by review. Do not revise the specs, add capability metadata, create
the MCP mapping, or open a replacement implementation plan before the
reconsideration condition fires.

Checked through 2026-08-14 at
`45592f0f09356d0818a74a8c8bb5fbaebc1976ed`: the production first-party root
registry contains 20 verbs. Eighteen come from `BUILTIN_SPECS`; `summon` and
`dismiss` are the two reserved first-party compatibility verbs. The baseline
set is:

```text
init join leave set say reply message channel read inbox log search system
list watch who whoami rejoin summon dismiss
```

Reconsider only when the production first-party root registry contains at least
25 distinct verbs. That is the fifth additional root verb beyond this baseline,
which satisfies the owner's "more than four more" threshold. Nested command
paths such as `message delete`, aliases, and third-party extension verbs do not
count. A rename with no added operation family does not count as growth.

Crossing the threshold authorizes evaluation, not implementation. The new
evaluation must inspect the then-current duplication and failure history before
choosing among no change, the narrow CLI-to-MCP parity design, or a domain-
operation inventory with typed surface relations. It must not assume that the
locked design below has become advisable merely because the count increased.

## Review Outcome and Author Recommendation

Do not implement the locked design below. Both requested independent reviewers
returned `BLOCKED`, and their central finding reproduces in the current tree:
command paths are exact CLI grammar, not the complete cross-surface semantic
seam. `TautClient.set_persona()` is a core identity mutation used directly by
the TUI, but no `taut set persona` command exists; `join --persona` has different
semantics. The TUI also presents `list` results and composes `log`, filtered
watching, notification claims, and cursor-neutral search context outside a
one-command-per-action model. Mapping those cases to actions would overclaim;
calling them TUI-local would misclassify core domain behavior.

The author accepts the reviewers' shared P1 conclusion. Tasks 2 through 8 are
blocked and remain below only as the reviewed proposal. No agent should promote
the spec delta or implement the locked design without an owner-directed
revision and another independent review.

The review's preferred alternative was a smaller MCP-only plan that derives
exact CLI paths from production built-ins and nested parsers, makes production
`ToolDefinition`s the tool-to-path mapping, and retains one explicit MCP
omission policy. The owner has deferred that alternative under the same trigger
above. If a later evaluation instead finds that a true cross-surface inventory
is justified, it should design around public domain operations and distinguish
`performs`, `side-effect`, `presents`, and `absent`; it should not reuse command
paths as semantic identities by assertion.

## Source Documents

- `docs/program-theory.md` [THEORY-1], [THEORY-2], and [THEORY-4]
- `docs/agent-context/decision-hierarchy.md`
- `docs/agent-context/principles.md`
- `docs/agent-context/engineering-principles.md` sections 1, 5, 8, 9, 10, 11,
  12, and 13
- `docs/agent-context/runbooks/writing-plans.md`
- `docs/agent-context/runbooks/hardening-plans.md`
- `docs/agent-context/runbooks/review-loops-and-agent-bootstrap.md`
- `docs/agent-context/runbooks/testing-patterns.md`
- `docs/agent-context/runbooks/maintaining-traceability.md`
- `docs/lessons.md` Golden Rules 3, 5, 6, 7, 10, and 13, plus all entries
  after the current lessons watermark
- `docs/specs/01-development-documentation-operating-model.md` [DOM-5],
  [DOM-6], [DOM-10], [DOM-11], and [DOM-15]
- `docs/specs/02-taut-core.md` [TAUT-8.1], [TAUT-8.3], [TAUT-8.6], and
  [TAUT-12.4]
- `docs/specs/05-taut-mcp.md` [MCP-5], [MCP-6], and [MCP-12]
- `docs/specs/10-taut-tui.md` [TUI-1], [TUI-2.1], [TUI-2.2], [TUI-2.3],
  [TUI-13], and [TUI-14]
- `docs/implementation/04-taut-architecture.md`
- `docs/implementation/06-command-extensions.md`
- `docs/implementation/07-taut-mcp-architecture.md`
- `docs/implementation/12-taut-tui.md`
- `skills/call-agent/SKILL.md`

## Classification and Promotion

This is Class 5 under [DOM-15] because it adds normative capability identity,
exposure defaults, exception rules, and firing obligations to three active
specifications. It is also Class 4-risky under [DOM-5]: `taut.commands` is a
public versioned extension interface, the MCP and TUI ship separately, and
rollback depends on the core version each extension imports.

Use promotion strategy A. Review this plan and its exact proposed deltas first.
Then promote requirement text into the active core, MCP, and TUI specs without
claiming implementation links. Record the promotion baseline before production
code cites the new sections. Add reciprocal implementation links only in the
traceability slice after the firing gates pass.

## Spec Baseline

The pre-promotion baseline is commit
`45592f0f09356d0818a74a8c8bb5fbaebc1976ed` for:

- `docs/specs/02-taut-core.md`
- `docs/specs/05-taut-mcp.md`
- `docs/specs/10-taut-tui.md`

Before promotion, compare those files against this identifier. If [TAUT-8.6],
[MCP-5], or [TUI-2.1] has changed in a way that conflicts with this plan, stop
and revise the plan. After promotion, record the new commit SHA or the exact
diff base plus worktree-state identifier here. Mid-implementation compliance is
against that promotion baseline, not this appendix.

Promotion baseline: pending

## Proposed Spec Delta

### Promotion table

| Spec file | Strategy | Sections touched |
|---|---|---|
| `docs/specs/02-taut-core.md` | A — in-file text before implementation links | new [TAUT-8.7] after [TAUT-8.6] |
| `docs/specs/05-taut-mcp.md` | A — in-file text before implementation links | [MCP-5], [MCP-12] |
| `docs/specs/10-taut-tui.md` | A — in-file text before implementation links | [TUI-2.1], [TUI-2.2], [TUI-13.2], [TUI-14] |

### New core section [TAUT-8.7] — Command capability identity and exposure

Insert after [TAUT-8.6]:

> A core command capability is one stable executable operation identified by
> its canonical command path, such as `say`, `message.delete`, or
> `channel.topic`. The core-owned capability inventory is part of
> `taut.commands` and groups each capability under exactly one built-in
> top-level `CommandSpec`. It is the semantic exposure inventory for the
> first-party CLI, MCP, and TUI; it does not prescribe any surface's argument
> grammar, transport schema, rendering, form, gesture, or lifecycle.
>
> Every core command capability is expected to have a declared CLI, MCP, and
> TUI exposure. An exposure may be direct or composed: one surface operation
> may expose several core capabilities, and several surface operations may
> expose one capability. An intentionally absent exposure is valid only when
> the capability specification names the surface and carries a non-empty
> rationale. Absence is never inferred from a missing registration.
>
> Every first-party surface registration identifies the core command
> capabilities it exposes. A registration that exposes no core capability must
> instead carry one closed surface-local role. Surface-local operations include
> host/session lifecycle, navigation, presentation, and application control;
> they do not enter the core capability inventory merely to satisfy parity.
> First-party extension domain operations remain owned by their extension and
> require a separately specified capability vocabulary before they can claim
> cross-surface parity.
>
> `CommandSpec` version 1 remains the exact public top-level CLI extension
> manifest defined by [TAUT-8.6]. Capability identity is adjacent typed contract
> data, not a new optional field silently added to the version-1 manifest.
> Installed third-party command manifests are not automatically MCP or TUI
> capabilities, and no surface reflects command implementation targets.
>
> Executable conformance gates derive the current CLI grammar, MCP tool
> definitions, and TUI action registrations and compare them with the one
> core-owned inventory. The gates reject unknown capability ids, missing
> expected exposures, unused exceptions, blank exception reasons, unclassified
> surface-local registrations, and duplicate direct bindings where a surface
> requires uniqueness.

### MCP amendments [MCP-5] and [MCP-12]

Append to [MCP-5] after the paragraph that distinguishes lifecycle tools:

> Each CLI-shaped `ToolDefinition` declares the [TAUT-8.7] core command
> capability it exposes. `attach_workspace`, `detach_workspace`, and
> `list_workspaces` declare the closed surface-local role `session-management`
> and no core capability. The declaration is identity and conformance metadata;
> it does not generate the tool name, JSON Schema, annotations, dispatcher, or
> serializer. MCP-only bounds and transport semantics remain owned here.

Add to [MCP-12]:

> A structural cross-surface gate proves that every non-excepted MCP exposure
> in the core capability inventory is backed by at least one current
> `ToolDefinition`, every CLI-shaped tool names a known capability, each
> process-lifecycle tool is explicitly surface-local, and every declared MCP
> exception remains both necessary and nonblank. The gate derives tool names
> from the production manifest and does not maintain a second expected tool
> list.

### TUI amendments [TUI-2.1], [TUI-2.2], [TUI-13.2], and [TUI-14]

Append to [TUI-2.1]'s prohibition list clarification:

> Importing the lightweight [TAUT-8.7] capability identifiers for conformance
> does not make command manifests a TUI schema. The TUI still does not inspect
> `CommandSpec`, command factories, argparse parsers, or implementation targets
> at runtime.

Append to [TUI-2.2]:

> Each native `ActionSpec` declares zero or more [TAUT-8.7] core command
> capabilities that the action directly or compositionally exposes. An action
> with no core capability declares one closed TUI-local role, such as
> navigation, presentation, composition, or application lifecycle. Capability
> associations do not select handlers, infer applicability, generate forms, or
> widen the action registry. Loaded first-party extension actions continue to
> use their extension-owned typed interface and do not claim a core capability.

Add to [TUI-13.2]:

> - every non-excepted TUI exposure in the core capability inventory backed by
>   at least one current action declaration; every core capability referenced by
>   an action known to the inventory; every core-empty action carrying one
>   closed TUI-local role; and every declared TUI exception necessary and
>   nonblank, with the expected set derived from production registries rather
>   than copied into a test fixture;

Add to [TUI-14]:

> - generation of TUI actions, forms, applicability, routes, or handlers from
>   core command capability metadata;

## Context and Key Files

Read these files before implementation:

- `taut/commands/_protocol.py`: owns the public version-1 `CommandSpec`. Its
  current exact field set is a compatibility boundary and must not be widened
  by this plan.
- `taut/commands/_builtins.py`: owns the static built-in command list. Add the
  core capability inventory beside this list or in one tightly owned sibling
  module, while keeping each capability grouped under exactly one built-in.
- `taut/commands/_registry.py`: owns top-level CLI discovery and conflicts. It
  must not become a cross-surface runtime registry.
- `taut/commands/channel.py`, `message.py`, `set.py`, and `system.py`: own the
  nested CLI grammar that capability ids must match.
- `tests/test_command_registry.py` and `tests/test_cli.py`: own manifest and
  parser behavior. Extend the narrowest production-derived inventory test;
  do not snapshot a duplicate table.
- `extensions/taut_mcp/taut_mcp/_tools.py`: owns production
  `ToolDefinition`s and the fixed MCP manifest. Add capability or local-role
  metadata here, not in the dispatcher or serializer.
- `extensions/taut_mcp/tests/test_dual_era_contract.py`: currently owns
  `CLI_CAPABILITY_TO_MCP_TOOL` and `INTENTIONALLY_UNEXPOSED_CLI_COMMANDS`.
  Those are the duplication this plan removes after red tests prove the new
  core inventory can replace them.
- `extensions/taut_tui/taut_tui/actions.py`: owns `ActionSpec` and the closed
  action registry. Add capability or local-role metadata here without changing
  route or confirmation semantics.
- `extensions/taut_tui/taut_tui/forms.py`: owns input kind and applicability.
  It consumes action identity only; capability metadata must not become a
  second applicability authority.
- `extensions/taut_tui/tests/test_tui_actions.py`, `test_tui_action_routes.py`,
  and `test_tui_action_handlers.py`: preserve existing action, route, and
  handler completeness while adding cross-surface conformance.
- `docs/implementation/06-command-extensions.md`,
  `07-taut-mcp-architecture.md`, and `12-taut-tui.md`: update rationale and
  edit guidance after the contract is implemented.

The current MCP parity test already proves the design pressure but owns the
wrong authority: it parses selected CLI adapters and compares them with an
MCP-local mapping plus an MCP-local omission set. The TUI has no equivalent
mapping. The target state keeps production surface registries native while
moving capability identity, expected coverage, and exceptions to core.

## Required Comprehension Checks

Before editing code, the implementer records answers in the Implementation Log:

1. Why is `CommandSpec` not itself the semantic operation inventory today?
   Expected: it is a public version-1 top-level CLI manifest; nested grammar is
   adapter-owned, and extension launch verbs such as `mcp` and `tui` are not
   domain operations.
2. Why must capability ids include nested paths?
   Expected: family-only coverage would let `message.react` or
   `channel.topic` disappear while `message` or `channel` still looked covered.
3. Why can a TUI action expose zero, one, or several capabilities?
   Expected: some actions are local presentation/navigation; others directly
   invoke one operation; a conversation flow may compose read, log, and watch
   semantics without becoming a CLI wrapper.
4. Why are MCP workspace tools not core commands?
   Expected: they own MCP process/session lifecycle and do not invoke one core
   domain operation.
5. What remains native to each surface?
   Expected: names, arguments, schemas, validation, rendering, forms, gestures,
   applicability, dispatch, and lifecycle. Shared metadata is identity and
   coverage only.

Wrong, uncertain, or unrecorded answers block implementation until the cited
spec and implementation sections are reread.

## Locked Design

The initial implementation target is deliberately narrower than adding fields
to `CommandSpec`:

```python
class CommandCapability(StrEnum):
    SAY = "say"
    MESSAGE_SHOW = "message.show"
    MESSAGE_DELETE = "message.delete"
    MESSAGE_REACT = "message.react"
    CHANNEL_SHOW = "channel.show"
    CHANNEL_TOPIC = "channel.topic"
    CHANNEL_RENAME = "channel.rename"
    # Every remaining built-in command path follows the same rule.


class Surface(StrEnum):
    CLI = "cli"
    MCP = "mcp"
    TUI = "tui"


@dataclass(frozen=True, slots=True)
class ExposureException:
    surface: Surface
    reason: str


@dataclass(frozen=True, slots=True)
class CommandCapabilitySpec:
    capability: CommandCapability
    command_name: str
    exceptions: tuple[ExposureException, ...] = ()
```

The production inventory is one immutable tuple grouped by built-in command.
It either lives in `_builtins.py` or one sibling such as `_capabilities.py` if
keeping it in `_builtins.py` would force the public manifest module to import
surface-only types. The deletion test decides: removing the chosen module must
make capability identity and exception policy reappear in multiple surfaces;
otherwise it is a pass-through and should be folded back into `_builtins.py`.

`CommandSpec` retains its exact v1 fields. `CommandCapability`, `Surface`,
`ExposureException`, `CommandCapabilitySpec`, and read-only query helpers are
exported from `taut.commands` only if MCP and TUI need a supported cross-package
import. No private core import is permitted.

MCP `ToolDefinition` gains mutually exclusive metadata:

```python
capabilities: frozenset[CommandCapability] = frozenset()
surface_role: McpSurfaceRole | None = None
```

TUI `ActionSpec` gains the same capability set plus a TUI-owned local role.
Each constructor rejects both-set and neither-set states. Extension-owned
Summon actions use a TUI-local `EXTENSION_OPERATION` role in this slice; a
future extension capability vocabulary requires its own spec and concrete
second consumer.

CLI exposure is checked against the real adapters. Simple command paths derive
from the built-in name. Nested paths derive from production argparse choices
for the currently nested built-ins. Parser introspection remains a test-only
oracle and does not become runtime discovery.

The conformance helper computes expected capabilities for a surface by removing
that surface's explicit exceptions from the core inventory. It compares those
with capability ids derived from the production registry. Tests may format the
diff, but must not carry another expected capability or exception set.

Before coding, enumerate the complete current mapping in the red test and
classify every difficult case. Stop and return to design review if any of these
occur:

- more than one capability id can plausibly name the same core operation;
- a TUI association would falsely claim that invoking the action performs the
  capability rather than composing or presenting it;
- exceptions become the normal case for either MCP or TUI;
- the mapping needs domain methods that no command path represents; or
- extension commands require core to know extension-owned semantics.

Those signals mean command paths are the wrong semantic seam. The fallback is
an explicitly reviewed domain-operation vocabulary, not more exception rows.

## Invariants and Constraints

- `CommandSpec` version 1, installed entry-point loading, lazy imports, root
  help, conflict policy, and extension compatibility remain byte-for-byte
  behaviorally unchanged.
- The canonical capability id for a core operation is its exact stable command
  path. No aliases or renderer names enter the vocabulary.
- Every capability belongs to exactly one core built-in command.
- Missing exposure fails unless the core inventory carries one explicit,
  nonblank exception for that surface.
- An exception that is no longer needed fails the gate. Exceptions cannot
  become a stale waiver list.
- Surface-local registrations are explicit and closed. `None` without a role is
  invalid; a core capability plus a local role is invalid.
- Many-to-many composition is allowed, but it must not overclaim behavior. A
  mapping means the surface actually makes that capability available through
  the named operation.
- MCP schemas, annotations, tool names, dispatch, output shapes, admission,
  cancellation, and workspace lifecycle remain MCP-owned.
- TUI action ids, routes, confirmations, forms, applicability, handlers,
  layout, and lifecycle remain TUI-owned.
- The TUI does not inspect command manifests or argparse at runtime.
- No command, MCP, or TUI operation is generated from the shared inventory.
- No persistence, wire-format, exit-code, dependency, or user-visible command
  syntax changes.
- No new dependency is introduced.

## Hidden Couplings and Failure Modes

- `CommandSpec` is public and versioned. Adding an optional field while leaving
  `command_api_version=1` would silently change the exact v1 interface.
- Built-in command names are top-level families, while parity needs nested
  operations. Family-only checks are too weak.
- The TUI exposes some domain behavior compositionally through navigation and
  long-lived session ownership, not as one action per CLI command. False
  one-to-one mappings would make the gate green while lying about behavior.
- `system load` is deliberately CLI-only; the TUI shows help but never loads.
  The exception must describe absence, not map help display to execution.
- MCP has session-management tools with no CLI/TUI equivalent. Treating them as
  core capabilities would move process semantics into core.
- Summon is extension-owned. Core must not acquire a fake `summon.*` vocabulary
  merely because CLI and TUI both expose it.
- Importing capability ids from a heavy command module could violate root-help
  and extension lazy-import floors. Keep the shared type module standard-library
  only and preserve import-boundary tests.
- Exact set equality can hide duplicate bindings. Cardinality and duplicate
  policy need separate assertions where uniqueness is required.

## Rollout, Rollback, and One-Way Doors

Ship this as one coordinated core/MCP/TUI compatibility change after all three
retained environments pass. Core must land before or atomically with extension
code because the extensions import the new public capability types. There is no
mixed-version promise beyond each extension's declared `taut-chat` dependency
floor; update those floors only if required by the first released core version
containing the interface.

Rollback is code and documentation only: revert the coordinated change and the
spec delta together. No stored state, protocol payload, or user data changes.
Do not leave adapters accepting both old MCP-local and new core-owned mappings;
dual authority is the defect being removed.

There is no data one-way door. Publishing packages with mismatched dependency
floors would be an operational one-way edge, so coordinated release follows the
existing release plan and exact-wheel gates. This plan does not itself publish.

Post-deploy success means fresh paired installations of core plus MCP and core
plus TUI import and launch successfully, the full surface suites pass, and the
cross-surface gate reports no missing exposure, stale exception, unknown id, or
unclassified local operation.

## Dependency-Ordered Tasks

### Task 1: Finish independent design review and accept the semantic seam

Read the source documents, proposed deltas, current registries, and nearest
tests. Obtain independent reviews from Grok and Claude Fable 5. Each reviewer
may inspect repository files and run focused read-only tests. Ask whether the
change is advisable, whether command-path identity is the right seam, whether
leaving `CommandSpec` v1 unchanged is correct, and whether a smaller or deeper
design exists.

Record every finding and disposition in the Review Log. A reviewer inability to
implement confidently, a demonstrated false mapping, or a better design that
reduces authority duplication blocks promotion until the plan is revised and
re-reviewed.

Done signal: both reviews have terminal results; every finding is accepted,
rejected with source-backed reasoning, or explicitly raised for owner decision.

### Task 2: Promote the reviewed spec delta

Files:

- `docs/specs/02-taut-core.md`
- `docs/specs/05-taut-mcp.md`
- `docs/specs/10-taut-tui.md`

Apply the accepted text using strategy A, add the plan backlinks, run document
reference gates, and record the promotion baseline. Do not add code backlinks
or implementation claims yet.

Stop gate: any unresolved disagreement about command-path identity, extension
scope, composed TUI exposure, or v1 manifest compatibility blocks promotion.

### Task 3: Add red core-inventory and conformance tests

Files:

- `tests/test_command_registry.py`
- `extensions/taut_mcp/tests/test_dual_era_contract.py`
- `extensions/taut_tui/tests/test_tui_actions.py`

Add failing tests that require the new typed inventory, prove exact nested CLI
path coverage through production parsers, reject duplicate ids and malformed
exceptions, and require every MCP tool and TUI action to be either capability-
mapped or locally classified. Delete no old mapping until the new tests fail for
the intended missing production interface.

Red gate: run the three focused test files and record failures caused by absent
capability metadata. If they pass on the baseline, strengthen the tests.

### Task 4: Implement the core capability inventory

Files:

- `taut/commands/_builtins.py`
- either `taut/commands/_protocol.py` or one lightweight sibling capability
  module selected by the deletion test
- `taut/commands/__init__.py`
- `tests/test_command_registry.py`
- `tests/test_public_api.py`
- `tests/test_lazy_imports.py`

Add the closed types, immutable inventory, validation/query helper, complete
built-in capability declarations, public exports needed by first-party
extensions, and import-floor proof. Keep `CommandSpec` unchanged.

Stop gate: if implementation needs the registry to import MCP/TUI, parse
surface files, or load command factories at runtime, the seam is wrong.

### Task 5: Replace MCP-local capability authority

Files:

- `extensions/taut_mcp/taut_mcp/_tools.py`
- `extensions/taut_mcp/tests/test_dual_era_contract.py`
- package typing/import tests if the new core floor requires them

Add typed capability/local-role metadata to `ToolDefinition`, derive parity
from `TOOL_DEFINITIONS`, and remove `CLI_CAPABILITY_TO_MCP_TOOL` plus
`INTENTIONALLY_UNEXPOSED_CLI_COMMANDS`. Preserve the exact 21-tool manifest,
schemas, annotations, and serialization snapshots.

Stop gate: a generated tool or schema, a second tool-name mapping, or an MCP
runtime dependency on CLI parser construction is out of design.

### Task 6: Add TUI capability classification

Files:

- `extensions/taut_tui/taut_tui/actions.py`
- `extensions/taut_tui/tests/test_tui_actions.py`
- `extensions/taut_tui/tests/test_tui_action_routes.py`
- `extensions/taut_tui/tests/test_tui_action_handlers.py`

Add capability/local-role metadata to `ActionSpec`, classify every current
action, and prove TUI coverage against the core inventory. Preserve all current
action ids, routes, confirmations, applicability tuples, forms, and concrete
handler outcomes.

Stop gate: if an action mapping changes dispatch or if a test must pretend that
help/navigation performs a destructive command, record an exception or return
to the semantic-seam decision. Do not falsify exposure to satisfy parity.

### Task 7: Reconcile docs, packaging, and traceability

Files:

- `docs/implementation/04-taut-architecture.md`
- `docs/implementation/06-command-extensions.md`
- `docs/implementation/07-taut-mcp-architecture.md`
- `docs/implementation/12-taut-tui.md`
- `docs/specs/02-taut-core.md`
- `docs/specs/05-taut-mcp.md`
- `docs/specs/10-taut-tui.md`
- `docs/plans/README.md`
- affected extension `pyproject.toml` files only if a released core floor is
  required

Add reciprocal links, explain why capability identity is shared while surface
grammar remains native, and update dependency floors only from the retained
release version selected by the owner. Run traceability and CLI-claim gates.

### Task 8: Run final verification and independent completed-work review

Run the focused and full gates below from the same final tree. Then give a
different-family reviewer the promoted specs, this plan, implementation notes,
diff, and observed command output. Resolve every finding before marking the
plan completed or requesting a commit.

## Testing Plan

Use red-green TDD. The pre-change failure is the absence of a core-owned typed
capability inventory and the continued need for MCP-local mapping/omission
sets. The post-change correction is a production-derived conformance gate over
all three surfaces.

Keep real:

- static built-in manifests and actual nested argparse adapters;
- production MCP `TOOL_DEFINITIONS` and generated `types.Tool` manifest;
- production TUI `ACTION_SPECS`, action constructors, route inventory, and
  handler completeness;
- fresh core/MCP and core/TUI package imports where dependency floors change.

May be mocked:

- installed third-party entry-point enumeration in existing registry-isolation
  tests;
- no domain storage or network behavior is needed for pure inventory checks.

Required firing cases:

- every canonical capability id appears exactly once in the core inventory;
- every id's top-level owner is one current built-in `CommandSpec`;
- every simple and nested CLI path is discovered from production grammar;
- every expected MCP capability is declared by a production tool;
- every MCP-local tool carries exactly one closed local role;
- every expected TUI capability is declared by a production action or carries
  an explicit exception;
- every TUI action is capability-mapped or carries exactly one local role;
- unknown ids, duplicate ids, duplicate exceptions, blank reasons, stale
  exceptions, both-set metadata, and neither-set metadata all fail;
- `CommandSpec` v1 construction, repr/equality assumptions, installed fixture
  loading, root help, and lazy import floors remain unchanged;
- MCP's exact 21 tools and TUI's exact action/route/handler inventories remain
  unchanged unless separately specified.

## Verification and Gates

Focused red/green commands:

```bash
uv run --extra dev pytest -p no:cacheprovider tests/test_command_registry.py tests/test_public_api.py tests/test_lazy_imports.py
uv run --project extensions/taut_mcp --extra dev pytest -p no:cacheprovider extensions/taut_mcp/tests/test_dual_era_contract.py
uv run --project extensions/taut_tui --extra dev --locked pytest -p no:cacheprovider extensions/taut_tui/tests/test_tui_actions.py extensions/taut_tui/tests/test_tui_action_routes.py extensions/taut_tui/tests/test_tui_action_handlers.py
```

Static and full neighboring gates:

```bash
uv run --extra dev ruff check taut tests extensions/taut_mcp extensions/taut_tui
uv run --extra dev mypy taut tests
uv run --project extensions/taut_mcp --extra dev mypy taut_mcp tests
uv run --project extensions/taut_tui --extra dev --locked mypy taut_tui tests
uv run --extra dev pytest
uv run --project extensions/taut_mcp --extra dev pytest
uv run --project extensions/taut_tui --extra dev --locked pytest
uv run bin/check-cli-claims
uv run bin/check-doc-paths
uv run --extra dev pytest tests/test_docs_references.py
bin/check-plan-status-index
git diff --check
```

If PostgreSQL behavior or package dependency floors change unexpectedly, stop;
this metadata-only design should not require backend conformance. If a full gate
is unavailable, report the exact residual and do not call the work complete.

## Independent Review Loop

Plan review uses Grok and Claude Fable 5, both read-only with repository access.
They are asked to inspect code and specs, run focused tests if useful, and
answer:

1. Is a core-owned cross-surface capability contract advisable here?
2. Is command-path identity the correct semantic seam, or is a domain-operation
   inventory, generated contract, or no new abstraction better?
3. Does keeping `CommandSpec` v1 unchanged while adding adjacent typed data
   avoid the right compatibility risks?
4. Are composed TUI exposure and surface-local roles precise enough to prevent
   false parity?
5. Could they implement the plan confidently, and would it degrade the system?

Each returns `PASS` or `BLOCKED`, explicit P1/P2 findings, suggested
dispositions, and a separate non-actionable observations section. The plan
author verifies each claim against source or tests before accepting it.

Completed-work review repeats with the promoted spec and final diff. Reviewers
do not implement or edit repository files.

## Out of Scope

- Generating CLI parsers, MCP schemas, serializers, TUI forms, applicability,
  routes, handlers, or UI from shared metadata.
- A generic third-party MCP or TUI plugin protocol.
- Automatic exposure of installed `taut.commands` extensions.
- Moving domain behavior into command adapters or parsing CLI output.
- Renaming current commands, MCP tools, or TUI action ids.
- Changing domain semantics, persistence, cursor behavior, lifecycle, or
  terminal ownership.
- Defining cross-surface capability vocabularies for Summon or future
  extensions without a separate reviewed contract.
- Publishing or releasing packages.

## Deviation Log

| Spec ref | Planned behavior | Actual behavior | Rationale | Spec proposal |
|---|---|---|---|---|

## Review Log

Review findings are append-only. Full reviewer output and each source-backed
disposition belong here before spec promotion.

| Review | Finding | Disposition | Plan change |
|---|---|---|---|
| Grok CAP-1 (P1) | Command paths omit public core operations including `set_persona`, `history_around`, `joined_thread_names`, `list_direct_messages`, and `peek_inbox`; the plan's own seam-falsifier fires. | Accepted. Verified `set_persona` and the TUI call directly; the other methods also exist and are used outside command-path actions. | Added the blocking outcome and rejected command paths as the universal semantic seam. |
| Grok CAP-2 (P1) | Default CLI/MCP/TUI exposure is false for the TUI; `read`, `inbox`, `log`, `watch`, `list`, `message.show`, and `system.load` have absent, filtered, side-effect, presentation, or composed relations that an action-level mapping cannot state honestly. | Accepted. Verified `list_threads`, `list_direct_messages`, `read_unread`, `log`, filtered `watch`, and notification-feed paths in the TUI session/domain code. | Recommended an MCP-only correction; any future domain inventory must use typed relation kinds. |
| Grok CAP-3 (P1) | `CommandCapability` plus `CommandCapabilitySpec` is a second catalog over existing manifests, parsers, and `TautClient`; Task 2 would promote it before Task 3 discovers the known counterexamples. | Accepted. | Blocked spec promotion and implementation. |
| Grok CAP-4 (P2) | The delta is internally inconsistent: singular MCP capability versus a set; unreconciled future-verb policy; no [TAUT-11] gate; open-ended “closed” TUI roles; unspecified duplicate policy. | Accepted as defects in the reviewed design. | No piecemeal repair because the owning seam is rejected. Any successor plan must resolve them explicitly. |
| Grok CAP-5 (P2) | Keeping `CommandSpec` v1 exact is correct; widening `taut.commands` into the cross-surface semantic authority is not. | Accepted. | Preserved v1 as an invariant and recommended no new cross-surface exports. |
| Claude Fable 5 F1 (P1) | `identity.set-persona` cannot map truthfully to a command path or a surface-local role; Task 2 precedes the seam-falsifying enumeration. | Accepted and independently reproduced. | Same blocking outcome as Grok CAP-1/CAP-3. |
| Claude Fable 5 F2 (P2) | TUI `list` exposure is presented by navigation rather than an action. | Accepted and reproduced in `session.py`/`domain.py`. | Future domain design must represent non-action presentation; current design is blocked. |
| Claude Fable 5 F3 (P2) | The proposed requirement that every first-party surface registration carry capability/local-role metadata is impossible for unchanged CLI extension manifests. | Accepted. | No spec promotion; any successor scopes local-role metadata to the actual owning surface. |
| Claude Fable 5 F4 (P2) | Declared composed TUI exposure is not behaviorally verified merely by comparing declaration sets. | Accepted. | Future composed claims require typed relations plus named firing proof, or an honest review-only residual. |
| Claude Fable 5 F5 (P3) | `CommandCapabilitySpec.command_name` duplicates the first path segment. | Accepted if the rejected structure is ever reconsidered. | Record only; no implementation. |
| Claude Fable 5 F6 (P3) | MCP/TUI dependency-floor bumps would be mandatory, not conditional, if they imported new core exports. | Accepted. | Moot for the recommended MCP-owned design; mandatory in any future core-export design. |
| Claude Fable 5 F7 (P3) | CLI exceptions are impossible when capability identity is definitionally an exact CLI path. | Accepted. | Another reason not to present symmetric three-surface exception policy. |

### Grok final review (2026-08-14)

Verdict: `BLOCKED` after an OS-sandboxed read-only review with terminal
`stopReason=end_turn`. Grok existence-checked the named surfaces, confirmed the
baseline, enumerated 24 core command paths, and reported focused passing checks
for the public command surface/built-ins, MCP CLI-path parity, and TUI action
inventory. It judged the MCP-local duplication real but the proposed
three-surface deepening harmful. Its preferred design is an MCP-only authority
move: derive CLI paths from production parsers, make production tool
definitions the mapping, retain an explicit omission policy, and add no TUI
capability fields. If a later cross-surface catalog is justified, Grok recommends
public `TautClient` operations with explicit `performs`, `side-effect`,
`presents`, and `absent` relations.

### Claude Fable 5 final review (2026-08-14)

Verdict: `BLOCKED` after a read-only Claude Code review using exact model
`claude-fable-5`, with terminal reason `completed`. Claude existence-checked all
named files and sections and independently enumerated the same 24 command
paths. Its environment could not run the `uv` commands without violating the
review's no-resolver rule, so it used production parser discovery directly.
Claude considered the overall core-owned coverage direction potentially
advisable, but required the complete mapping to be reviewed before promotion
and identified `set_persona` plus non-action `list` presentation as baseline
counterexamples. Its preferred repair was either a narrowly pathless domain
operation id or a preceding `taut set persona` feature. The author rejects both
for this plan: the former abandons strict command-path identity, while the
latter changes product syntax merely to satisfy an inventory abstraction.

## Implementation Log

- Plan authored against baseline
  `45592f0f09356d0818a74a8c8bb5fbaebc1976ed`.
- Promotion, red/green evidence, implementation commits, and final verification
  are pending. This plan authoring task does not authorize implementation.

## Fresh-Eyes Review

Before promotion, reread this plan from a zero-context implementer's position
and verify:

- every named path, type, test file, and command exists;
- capability identity is not conflated with `CommandSpec` v1 or domain API
  generation;
- every exception is core-owned and executable rather than prose-only;
- TUI composed exposure cannot be satisfied by a misleading label;
- extension-owned operations remain outside core;
- rollout order and dependency-floor implications are explicit; and
- both external review verdicts and every disposition are recorded.

Any change to capability identity, default exposure policy, extension scope,
or `CommandSpec` compatibility after review changes the reviewed architecture
and requires another review round before spec promotion.
