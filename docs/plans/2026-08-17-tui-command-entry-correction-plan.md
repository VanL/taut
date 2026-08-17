# TUI Command Entry Correction Plan

Date: 2026-08-17

Status: completed; implementation, verification, independent review, and
owner-authorized close-out passed

Owner: Taut maintainers

Class: 5 - the user changed the public TUI input contract so a leading
recognized command in the composer enters command input; the work also repairs
the command-completion selection path

Plan type: implementation with spec revision

Hardening: required - the public input contract changes and state crosses the
base composer, modal command screen, and native action dispatcher

## Goal

Make command entry behave as one vi-like TUI flow. A composer draft beginning
at column zero with `:` followed by a delimited exact known root command
transitions to the textual command line instead of being sent as chat. The command line keeps
an editable argument field, and keyboard or mouse activation of a displayed
completion fills the command path and returns focus to that field so the user
can type required arguments. Native action-palette selection continues to open
the existing typed form for actions such as Summon start.

## Requested Outcomes

- [x] Typing `:summon grok` from an empty composer transitions into command
  input and never sends the literal text to chat.
- [x] A leading colon remains ordinary message text when the following token is
  not an exact known root command.
- [x] Escape then `:` opens a visibly labelled command input whose buffer is
  editable and accepts arguments.
- [x] Tab, keyboard selection, and mouse activation of a command completion
  insert the selected command plus an argument-ready separator without closing
  the command line.
- [x] Choosing a native action through the Commands browser still opens its
  existing typed form when input is required.

## Source Documents

Source specs:

- `docs/specs/10-taut-tui.md` [TUI-4.3], [TUI-6.3], [TUI-7.1], [TUI-7.2],
  [TUI-8.1], [TUI-8.2], [TUI-11.1], [TUI-13.2]
- `docs/specs/02-taut-core.md` [TAUT-8.7], [TAUT-12.4]
- `docs/specs/01-development-documentation-operating-model.md` [DOM-5],
  [DOM-6], [DOM-10], [DOM-11], [DOM-15]

Canonical context and runbooks consulted:

- `docs/program-theory.md`
- `docs/agent-context/decision-hierarchy.md`
- `docs/agent-context/principles.md`
- `docs/agent-context/engineering-principles.md`
- `docs/agent-context/runbooks/testing-patterns.md`
- `docs/agent-context/runbooks/writing-plans.md`
- `docs/agent-context/runbooks/hardening-plans.md`
- `docs/agent-context/runbooks/writing-specs.md`
- `docs/agent-context/runbooks/maintaining-traceability.md`
- `docs/agent-context/runbooks/review-loops-and-agent-bootstrap.md`
- `docs/lessons.md`, Golden Rules and post-watermark entries

Existing implementation records:

- `docs/plans/2026-08-17-tui-command-mirror-plan.md`
- `docs/plans/2026-08-17-tui-multiline-whitespace-plan.md`
- `docs/implementation/12-taut-tui.md`
- `extensions/taut_tui/README.md`

## Spec Baseline

- `5ed9292d1b3fbbce6643cfb9e50e1d70dc1b461a` -
  `docs/specs/10-taut-tui.md` and `docs/specs/02-taut-core.md` at plan
  authoring time. This plan revises [TUI-7.1], [TUI-8.1], and [TUI-13.2].

Promotion strategy: **B - atomic**. The delta is small and directly changes
existing linked paragraphs. Promote the spec text, tests, code, reciprocal
implementation note, and backlinks in one reviewed worktree change so the
active spec never claims behavior that the implementation does not provide.

Promotion baseline identifier: `5ed9292d1b3fbbce6643cfb9e50e1d70dc1b461a`
plus the current worktree diff in `docs/specs/10-taut-tui.md`, applied after the
2026-08-17 Claude Sonnet round-two PASS. Implementation compliance is measured
against that promoted worktree text until the slice is committed.

## Current Structure and Key Files

- `extensions/taut_tui/taut_tui/widgets.py::TautComposer` owns multiline
  message editing and posts `Submitted`; it must remain the only message
  composer adapter.
- `extensions/taut_tui/taut_tui/app.py::on_text_area_changed` currently writes
  every composer edit into `DraftState`. `on_key` deliberately resolves `:`
  only in `NORMAL`, and `action_open_command_line` currently starts an empty
  `CommandLineScreen`. This is why a colon typed in `COMPOSE` remains chat.
- `extensions/taut_tui/taut_tui/screens.py::CommandLineScreen` owns command
  text and parse feedback. Its completion `OptionList` is presentation-only:
  Tab copies the first string without an argument separator; keyboard or mouse
  activation has no completion handler. The screen must remain the sole owner
  of command-line editing.
- `extensions/taut_tui/taut_tui/screens.py::CommandPaletteScreen` returns an
  `ActionId`; `TautApp._complete_palette` dispatches it through the central
  action path, which already opens `SummonStartScreen` for `summon.start`.
- `taut.commands.syntax` remains the sole command-language and installed
  provider owner. TUI code may query its typed nodes but must not add a second
  command inventory or invoke CLI parsing/adapters.

### Required Comprehension Gate

Before editing code, record the answers in the execution log. A wrong answer
blocks implementation until the cited owner is reread.

1. Why must composer detection use the merged `RootCommandSyntax`, rather than
   `ActionId` labels or a hard-coded command set?
   Expected answer: the shared syntax tree owns released core paths and
   installed extension syntax; native actions are a different semantic
   inventory and syntax discovery alone does not grant execution permission.
2. Which state owns text before and after promotion into command input?
   Expected answer: `TautComposer`/`DraftState` retain the original message
   draft until successful command submission; `CommandLineScreen` exclusively
   owns the transient command buffer. Cancel leaves the original draft intact,
   while successful parse clears only the originating draft before central
   typed command dispatch.

### Execution Log

- 2026-08-17: Comprehension answer 1 confirmed from `taut.commands.syntax`,
  `TautApp._command_syntax`, and `command_bindings.py`: syntax recognition and
  native execution ownership are separate registries.
- 2026-08-17: Comprehension answer 2 confirmed from
  `TautApp.on_text_area_changed`, `CommandLineScreen`, and
  `_complete_command_line`: the base draft and modal command buffer have
  separate owners; promotion must explicitly reconcile them only on success.
- 2026-08-17: Independent Claude Sonnet plan/delta review returned BLOCKED on
  the `who`/`whoami` prefix collision plus three plan precision gaps. All four
  findings were accepted; the scoped round-two review returned PASS.
- 2026-08-17: The reviewed strategy-B delta was promoted against baseline
  `5ed9292` as the current `docs/specs/10-taut-tui.md` worktree diff before
  dependent behavior was implemented.
- 2026-08-17: Red evidence was observed independently for composer promotion,
  Enter delimitation, exact-draft clearing, Tab completion, keyboard selection,
  and pointer activation. The named focused tests then passed after their
  respective minimal implementation slices.
- 2026-08-17: `test_tui_app.py` plus `test_tui_screens.py`, then
  `test_tui_action_handlers.py` plus `test_tui_action_routes.py`, passed. The
  full package-local TUI suite passed. Ruff, mypy, formatter, plan-index,
  docs-reference, and project-environment doc-path gates passed.
- 2026-08-17: Two different-family completed-work review attempts timed out
  without a verdict. The repository-authorized same-family fallback review
  then returned BLOCKED on a real callback-order defect: command cancellation
  restored composer focus but overwrote its mode to `NORMAL`. A real Pilot test
  was strengthened first, reproduced the failure, and then passed after modal
  completion began restoring `COMPOSE` for composer-originated commands and
  `NORMAL` for direct command entry.
- 2026-08-17: The fallback review's round two returned PASS after reproducing
  composer cancel, composer success, and direct-normal success. No blocker
  remains in the reviewed behavior; commit/landing remains intentionally
  pending because the user did not request a commit.
- 2026-08-17: After the accepted correction, the full package-local TUI suite
  passed at 100%. Ruff, mypy, formatter, plan-index, docs-reference, doc-path,
  and diff-whitespace gates also passed.
- 2026-08-17: The owner explicitly requested close-out and commit. The plan was
  moved to completed after the accepted-review rerun and all close-out gates
  passed; the resulting commit is the final landing record.

## Invariants and Constraints

- Exact known-root detection uses the merged typed syntax. Do not hard-code
  `summon`, inspect CLI adapters, or infer commands from palette labels.
- Detection applies only at composer offset zero and only after the token after
  `:` exactly equals a known root path segment and is delimited by whitespace
  or Enter. A still-growing token is never promoted: `:whoami` must not promote
  at its shorter known prefix `:who`. `:summonship` and ordinary mid-message
  colons remain chat text.
- Opening from the composer must not parse or execute until the user submits
  the command line. Cancel is non-mutating and must preserve the original
  composer draft and cursor. Dismissal restores `COMPOSE` for a
  composer-originated command and `NORMAL` for a direct command line, so mode
  and restored focus cannot diverge.
- Successful command submission clears only the exact originating draft. It
  must not clear a newer edit or a draft for another target.
- The command screen owns completion selection and editing. Completion
  activation fills text and stays open; it never dispatches an incomplete
  command or opens a CLI subprocess.
- Native palette actions continue through `ActionInvocation` and the central
  dispatcher. Summon command execution remains owned by `TuiSummonOperations`
  and the public controller boundary.
- Textual's real event routing, focus, and screen stack are the proof boundary.
  Do not mock `TautComposer`, `CommandLineScreen`, completion activation, or
  central dispatch.
- Parse errors and incomplete commands remain inline and non-mutating.
  Presentation failure remains secondary; no successful command may be
  downgraded by a later inspector/toast failure.
- No new dependency, command grammar, action id, subprocess path, persistence,
  background worker, or terminal lease behavior is introduced.

## Rollback, Rollout, and One-Way Doors

This is a source-compatible TUI-only behavior change with no data migration or
one-way door. It ships atomically because the active spec text and behavior
must agree. Rollback is one commit revert of the spec, app/screen behavior,
tests, implementation note, plan, and index row. Existing CLI, syntax-provider,
and Summon controller versions remain compatible because their contracts do
not change.

Post-deploy success is direct: in a released TUI, entering `:summon grok` from
an empty composer visibly moves to the command line and starts the typed Summon
flow only after Enter; selecting `summon` from completions leaves an editable
argument cursor. Failure signals are a literal `:summon ...` chat message, a
completion click that closes the screen, or loss of the original draft after
Escape.

## Proposed Spec Delta

Promotion strategy: **B - atomic**.

| Spec file | Strategy | Sections touched |
|-----------|----------|------------------|
| `docs/specs/10-taut-tui.md` | B - atomic | [TUI-7.1], [TUI-8.1], [TUI-13.2], Related Plans |

### [TUI-7.1] Replace the command-line entry paragraph

Replace the paragraph beginning ``The command line is opened with `:`...``
with:

> The command line is opened with `:` in `NORMAL`. In `COMPOSE`, a draft whose
> first character is `:` transitions to the command line when the token after
> the colon exactly matches a root command in the merged shared syntax and is
> followed by whitespace or Enter. Matching never occurs against a
> still-growing prefix, so a shorter command such as `who` does not capture
> `whoami`. The recognized command text prepopulates the command field and
> subsequent input supplies its arguments. Unknown leading-colon tokens and
> colons after the first character remain message text. The command line mirrors the Taut
> command language after the `taut` executable name. It accepts command paths,
> nested paths, positionals, options, quoted values, and literal `--` according
> to the shared syntax contract. `:` is an entry affordance and is not part of
> the command. Cancel preserves an originating composer draft; successful
> command submission clears only that unchanged originating draft.

Insert after that paragraph:

> Command completions are interactive, not display-only. Tab, keyboard
> selection, or mouse activation inserts the selected command path followed by
> an argument-ready space, keeps the command line open, and focuses the command
> field. Selecting an action from the separate grouped native-action browser
> continues through its typed action binding and opens the existing native form
> when that action requires arguments.

### [TUI-8.1] Replace the text-entry exception paragraph

Replace the paragraph beginning ``Bindings that would insert text are
disabled...`` with:

> Bindings that would insert text are disabled outside `NORMAL`; for example,
> typing `q`, `i`, or `/` in a text field edits text rather than invoking a
> global action. The narrow exception is a composer draft beginning at offset
> zero with `:` plus a whitespace- or Enter-delimited exact known root command,
> which promotes that prefix to the command line under [TUI-7.1]. Unknown and
> still-growing leading-colon tokens and all other colons remain text. Escape
> has priority for leaving `COMPOSE`, `COMMAND`, `SEARCH`, or a modal.

### [TUI-13.2] Extend the keyboard and mouse matrix bullet

In the gesture/mouse bullet, add:

> leading known-command composer promotion versus unknown-colon message
> retention; originating-draft preservation on command cancel and exact-draft
> clearing on submission; and command completion through Tab, keyboard
> selection, and mouse activation retaining editable argument focus.

## Dependency-Ordered Tasks

1. Review the plan and exact proposed delta before implementation.
   - Reviewer: a different agent family where available, read-only.
   - Inputs: this plan, [TUI-7.1]/[TUI-8.1]/[TUI-13.2], the prior command
     mirror plan, `app.py`, `screens.py`, `widgets.py`, and closest tests.
   - Stop if the composer-cancel ownership or exact-root rule is ambiguous.
   - Done when every finding is dispositioned and the plan is marked active.
2. Run the first red-green slice for composer promotion.
   - Files: `extensions/taut_tui/tests/test_tui_app.py`, then
     `extensions/taut_tui/taut_tui/app.py` and the small public initial-value
     seam in `extensions/taut_tui/taut_tui/screens.py`.
   - Add one real Textual pilot test proving `:summon grok` leaves the composer,
     enters a prefilled `CommandLineScreen`, and does not call message send.
   - Add the unknown-token/cancel preservation case and the `:who` versus
     `:whoami` prefix-collision case only after the tracer bullet is green.
   - Reuse merged syntax and existing draft helpers. Stop if implementation
     requires a second parser, a hard-coded root list, or private Textual hooks.
3. Run the second red-green slice for interactive completions.
   - Files: `extensions/taut_tui/tests/test_tui_screens.py`, then
     `extensions/taut_tui/taut_tui/screens.py`.
   - Prove Tab, explicit keyboard selection plus Enter, and real pointer
     activation each insert an argument-ready command path, keep the modal
     open, and leave the command input focused.
   - Stop if completion handling begins dispatching actions or duplicating
     command grammar.
4. Prove the native action browser still opens argument collection.
   - Files: closest existing route/handler test only if the current enumerable
     route matrix does not already fire this exact outcome.
   - Use the real palette producer and central dispatcher; the Summon controller
     may remain a narrow existing fake only beyond the form-opening boundary.
5. Promote the reviewed spec delta atomically and reconcile durable docs.
   - Files: `docs/specs/10-taut-tui.md`, `docs/implementation/12-taut-tui.md`,
     this plan, and `docs/plans/README.md`.
   - Record the promotion baseline identifier. Add reciprocal related-plan
     links and explain composer-to-command draft ownership in the implementation
     note.
6. Run focused and package-wide verification, then independent completed-work
   review.
   - Focused commands are listed below. Review the complete diff against the
     promoted spec and rerun accepted-finding tests after any correction.
   - Stop rather than claiming completion if a firing route is skipped, the
     docs graph is not clean, or a test only passes with mocked input routing.

## Testing Plan and Verification

Red-capable loop for the reported regression:

```bash
uv run --project extensions/taut_tui --extra dev pytest \
  extensions/taut_tui/tests/test_tui_app.py \
  extensions/taut_tui/tests/test_tui_screens.py -q
```

The first new test must be observed failing because the literal composer text
remains chat input or no command modal opens. The completion test must fail
because activation currently has no handler and Tab omits the argument-ready
separator. Each test is implemented and turned green before the next behavior
is added.

Final verification:

```bash
uv run --project extensions/taut_tui --extra dev pytest \
  extensions/taut_tui/tests/test_tui_app.py \
  extensions/taut_tui/tests/test_tui_screens.py \
  extensions/taut_tui/tests/test_tui_action_handlers.py \
  extensions/taut_tui/tests/test_tui_action_routes.py -q
uv run --project extensions/taut_tui --extra dev pytest extensions/taut_tui/tests -q
uv run --project extensions/taut_tui --extra dev ruff check \
  extensions/taut_tui/taut_tui extensions/taut_tui/tests
uv run --project extensions/taut_tui --extra dev mypy \
  extensions/taut_tui/taut_tui extensions/taut_tui/tests
bin/check-plan-status-index
uv run pytest tests/test_docs_references.py -q
uv run bin/check-doc-paths
```

No broker, client write, command parser, Textual event routing, or central
dispatcher is mocked. Existing narrow Summon controller fakes are allowed only
after the test has proved the native form or typed invocation boundary.

## Independent Review Loop

Plan and delta review happens before the atomic implementation slice. Completed
work receives a second read-only review against the promoted spec, plan,
implementation note, complete diff, and observed red/green evidence. Findings
are appended below and each is accepted, rejected with evidence, or marked out
of scope with reasoning. A `BLOCKED` plan verdict or completed-work blocker
halts implementation/completion respectively.

## Review Log

| Date | Review | Verdict | Finding | Disposition |
|------|--------|---------|---------|-------------|
| 2026-08-17 | Claude Sonnet plan/delta review | BLOCKED | P1: `who`/`whoami` prefix collision under per-keystroke exact matching | Accepted. Promotion now requires whitespace or Enter delimitation; Task 2 names the firing collision test. |
| 2026-08-17 | Claude Sonnet plan/delta review | BLOCKED | P1: required Fresh-Eyes Review section missing | Accepted. Added below. |
| 2026-08-17 | Claude Sonnet plan/delta review | BLOCKED | P2: Task 2 omitted the `CommandLineScreen` initial-value owner | Accepted. Task 2 now names the narrow `screens.py` seam. |
| 2026-08-17 | Claude Sonnet plan/delta review | BLOCKED | P2: native-browser wording was ambiguous beside completion behavior | Accepted. Proposed text now names the separate native-action browser. |
| 2026-08-17 | Claude Sonnet round-two review | PASS | Verified the four accepted corrections; no new defect introduced | Closed. Plan and proposed delta approved for promotion and implementation. |
| 2026-08-17 | Claude completed-work review | No verdict | Timed out before returning review output | Review retried with another family under the same read-only scope. |
| 2026-08-17 | Grok completed-work review | No verdict | Timed out before returning a verdict | After two different-family failures, used the repository-authorized same-family fallback review. |
| 2026-08-17 | Same-family fallback completed-work review | BLOCKED | P1: cancel restored composer focus, then `_complete_command_line` overwrote mode to `NORMAL`, allowing normal-only bindings such as Ctrl-Q | Accepted. Added a real Pilot mode/focus/Ctrl-Q assertion, observed it fail, then made modal completion restore mode from command origin. |
| 2026-08-17 | Same-family fallback round-two review | PASS | Reproduced composer cancel, composer success, and direct-normal success with coherent focus, mode, and draft state | Closed. Focused correction tests passed and no new blocker was found. |

## Deviation Log

| Spec ref | Planned behavior | Actual behavior | Rationale | Spec proposal |
|----------|------------------|-----------------|-----------|---------------|

## Out of Scope

- Redesigning the shared command grammar or TUI binding inventory.
- Adding shell expansion, CLI subprocess execution, or generic argparse forms.
- Changing CLI command syntax, Summon lifecycle/terminal ownership, persistence,
  or background execution.
- Adding insert-mode escape syntax for literal known commands unless observed
  use shows the exact-root rule needs an explicit literal escape.
- Refactoring unrelated composer, resize, transcript, or action-route code.

## Fresh-Eyes Review

- Every named source, test path, class, callback, and spec reference exists at
  baseline `5ed9292`.
- The plan preserves the shared grammar/native-binding split and does not add a
  second parser or execution path.
- Composer promotion owns an explicit token boundary, draft-cancel invariant,
  and exact-draft success rule; `who`/`whoami` proves prefix collisions.
- Command prepopulation remains owned by `CommandLineScreen`; completion
  activation remains inside that screen; palette dispatch remains separate.
- Verification uses real Textual input, focus, and modal behavior. No named
  task depends on mocked core behavior or an unstated file.
