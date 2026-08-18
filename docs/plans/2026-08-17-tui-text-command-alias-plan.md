# TUI Text Command and Quit Alias Plan

Date: 2026-08-17

Status: completed

Owner: Taut maintainers

Class: 4 - this corrects command-line focus ownership, adds two TUI-local text
command aliases, and makes Ctrl-C/Ctrl-D guarded quit chords across every mode
and modal without changing the core CLI grammar

Hardening: required - priority global chords cross text and modal ownership

## Goal

Keep `:` command entry text-first: completion rows may aid discovery and accept
explicit keyboard or pointer activation, but they never own focus while the
user types. Add vi-style `q` and `quit` command-line aliases that use the same
guarded TUI quit path as the existing normal-mode quit action.
Ctrl-C and Ctrl-D request that guarded quit from any mode or modal without
making bare `q` global inside text fields.

## Requested Outcomes

- [x] Typing `:summon grok` continuously keeps the command input visible,
  focused, and editable while passive completions render.
- [x] Tab, Up/Down plus Enter, and one-click completion insertion remain
  available without making the completion list a text-input owner.
- [x] `:q` and `:quit` both exit through `TautApp.action_quit_tui`, including
  its active dump and owned-Summon blockers.
- [x] Ctrl-C and Ctrl-D request the same guarded quit from `NORMAL`, `COMPOSE`,
  `COMMAND`, `SEARCH`, and modal forms; their priority is explicit.
- [x] Bare `q` remains text in compose and command inputs. Existing normal-mode
  `q` and Ctrl-Q behavior remains unchanged.
- [x] The aliases exist only in the TUI command syntax. The core CLI grammar
  and CLI adapter remain unchanged.

## Baseline and Sources

Baseline: `2e2a56f4351ac9282743d59908e09d3bb2bf045a`.

Promotion strategy: **B - atomic**. Exact spec text is reviewed first and then
promoted before dependent implementation resumes. Promotion baseline: commit
`2e2a56f4351ac9282743d59908e09d3bb2bf045a` with reviewed spec-diff SHA-256
`b1f1509c06057cff877d1499f734b4ab806ba865d991bc68e113fd3fd36dff9d`.

Governing sources:

- `docs/specs/10-taut-tui.md` [TUI-4.3], [TUI-7.1], [TUI-8.1], [TUI-8.2],
  [TUI-13.2]
- `docs/specs/02-taut-core.md` [TAUT-8.7]
- `docs/agent-context/runbooks/testing-patterns.md`
- `docs/agent-context/runbooks/hardening-plans.md`
- `docs/implementation/12-taut-tui.md`

## Context and Key Files

- `extensions/taut_tui/taut_tui/screens.py::CommandLineScreen` owns textual
  input and completion insertion. Its `_CommandCompletionList` must be passive.
- `extensions/taut_tui/taut_tui/command_syntax.py` owns TUI-only textual roots;
  `taut/commands/syntax.py::core_command_syntax` remains unchanged.
- `extensions/taut_tui/taut_tui/command_bindings.py` maps `q` and `quit` to
  `ActionId.APPLICATION_QUIT`.
- `extensions/taut_tui/taut_tui/app.py` merges syntax, dispatches aliases,
  owns app-level priority bindings, help text, modal idempotence, and the
  guarded `action_quit_tui` path.
- `extensions/taut_tui/taut_tui/actions.py::NORMAL_GESTURE_PAIRS` owns paging:
  Ctrl-D must be retired from `PAGE_DOWN`; PageDown remains.
- The closed current transient inventory is `NativeFormScreen`,
  `ConfirmationScreen`, `CommandPaletteScreen`, `CommandLineScreen`,
  `SearchScreen`, `SummonStartScreen`, `NamedActionScreen`, and
  `TerminalTooSmallScreen`.
- Firing owners are `test_tui_app.py`, `test_tui_screens.py`,
  `test_tui_command_bindings.py`, `test_tui_actions.py`,
  `test_tui_action_routes.py`, `test_tui_textual_contract.py`, and the existing
  modal/resize tests. The textual-contract file owns retained-floor real-PTY
  control-byte translation proof.
- Durable user guidance is `docs/specs/10-taut-tui.md`,
  `docs/implementation/12-taut-tui.md`, `extensions/taut_tui/README.md`, app
  help text, and `CHANGELOG.md`.

## Ownership and Invariants

- `taut.commands.syntax` remains the core and extension-neutral grammar owner.
  The TUI may merge a narrow local syntax provider for shell-only aliases; it
  must not add `q` or `quit` to `core_command_syntax()`.
- `CommandLineScreen` owns command text. Its completion list is a passive
  presentation/insertion aid and cannot become the focused text owner.
- Alias execution rejoins `ActionId.APPLICATION_QUIT` or
  `action_quit_tui`; it cannot call `App.exit()` directly and bypass active
  operation or Summon ownership checks.
- Ctrl-C/Ctrl-D use a separate priority action that is valid in all modes.
  `quit_tui` remains normal-only so bare `q` cannot escape a text field.
- “Any time” means whenever Textual owns terminal input. During the explicit
  [TUI-11.3] raw-terminal lease, the provider owns bytes and the TUI cannot
  intercept either chord.
- With no blocker, any-mode quit exits from the current surface. A blocking
  diagnostic preserves the underlying mode/modal. Owned-run confirmation may
  layer over that modal once; cancellation restores it, and repeated quit
  requests cannot stack duplicate confirmation screens.
- Existing Tab, keyboard-selection, one-click, parser feedback, draft
  preservation, and exact command dispatch behavior remain firing contracts.
- Tests use real Textual key and pointer events. They do not mock focus,
  parsing, command dispatch, or application exit.

## Exact Proposed Spec Delta

Strategy **B - atomic**.

In [TUI-7.1], replace the command-completion paragraph with:

> Command completions are interactive, passive input aids. The completion list
> cannot own focus; ordinary typing always remains in the command field and
> never inserts or selects a completion. Tab, explicit Up/Down selection plus
> Enter, or a single click on a completion row inserts the selected command
> path followed by an argument-ready space, keeps the command line open, and
> restores focus to the command field. Selecting an action from the separate
> grouped native-action browser continues through its typed action binding and
> opens the existing native form when that action requires arguments.

After that paragraph, insert:

> The TUI adds `q` and `quit` as shell-local textual aliases; they are not core
> CLI commands and do not appear in `core_command_syntax()`. Typing either
> alias remains editable and non-eager until Enter. Enter dispatches
> `application.quit` through the same guarded TUI quit owner as normal-mode
> quit. From `COMPOSE`, an undelimited `:q` or `:quit` follows the ordinary
> promotion rule: the first Enter opens the prefilled command line and the
> second Enter executes it; a whitespace delimiter promotes before submission.

In the [TUI-8.1] gesture table, replace the combined page row and Quit row with:

> | Page up | Ctrl-U | PageUp |
> | Page down | none | PageDown |
> | Quit in `NORMAL` | `q` | Ctrl-Q or palette `Quit` |
> | Guarded quit while the TUI owns input | none | Ctrl-C / Ctrl-D |

After the text-field binding paragraph in [TUI-8.1], insert:

> Ctrl-C and Ctrl-D are priority guarded-quit chords whenever Textual owns
> terminal input: all four modes, every native modal form, and the
> terminal-too-small surface. They dispatch `application.quit` through the guarded
> owner. Bare `q` remains ordinary text outside `NORMAL`, and Ctrl-Q retains its
> existing normal-only behavior. Ctrl-D no longer pages; PageDown remains the
> conventional page-down key and Ctrl-U/PageUp retain page-up. If quitting is
> blocked, the current mode and modal remain intact. An owned-run confirmation
> may layer over the current modal once; repeated quit requests do not stack
> confirmations, and cancel restores the underlying modal.

Append to [TUI-8.2]'s command-completion sentence:

> The completion list never retains focus after pointer handling.

Append to [TUI-11.3]'s raw-terminal lease paragraph:

> While the provider owns the raw terminal lease, Ctrl-C and Ctrl-D are provider
> input and cannot be TUI quit chords. Any-mode TUI quit resumes when Textual
> terminal ownership is restored.

Extend [TUI-13.2]'s gesture/completion firing bullet with:

> continuous typed command input with a non-focusable completion list; non-
> eager `q`/`quit` editing and Enter execution; core-grammar exclusion and
> TUI-local binding ownership for both aliases; Ctrl-D removal from page-down
> while PageDown still pages; Ctrl-C/Ctrl-D guarded quit in `NORMAL`, `COMPOSE`,
> `COMMAND`, `SEARCH`, every current native modal class, and the terminal-too-
> small surface; blocked-modal preservation; and repeated owned-run quit
> requests producing at most one confirmation. Real-PTY probes write `0x03`
> and `0x04` through the shipped Textual entry boundary and prove each byte
> reaches guarded `application.quit` while the TUI owns the terminal; pilot
> tests own the closed mode/modal matrix after that translation boundary.

Add to `docs/specs/10-taut-tui.md` Related Plans:

> - `docs/plans/2026-08-17-tui-text-command-alias-plan.md` — keeps textual
>   command entry focus-owned, adds TUI-local `q`/`quit`, and makes Ctrl-C and
>   Ctrl-D guarded quit chords whenever Textual owns terminal input.

## Deviation Log

| Date | Planned boundary | Observed deviation | Required correction |
|------|------------------|--------------------|---------------------|
| 2026-08-17 | Review and promote exact spec text before implementation | The passive-list tracer and `q`/`quit` alias slices were started while the initial summary-only plan review was still running | Freeze implementation; repair/review this plan, promote the exact delta, record the baseline, then resume from the existing red/green evidence. |

## Dependency-Ordered Work

1. Obtain independent PASS on this exact plan/spec delta.
2. Promote the exact [TUI-7.1], [TUI-8.1], [TUI-8.2], [TUI-11.3], and
   [TUI-13.2] text, add the Related Plans backlink, and record the actual
   worktree diff identifier as the promotion baseline.
3. Add a real-app red test proving continuous `:summon grok` typing keeps the
   input focused while completions render. Add a screen-level assertion that
   the completion list cannot own focus.
4. Make the completion list passive while preserving explicit Tab,
   Up/Down-plus-Enter, and one-click insertion paths.
5. Add red real-app tests for non-eager `:q` and `:quit`, exact Enter execution,
   compose promotion, guarded blocker behavior, and core-grammar exclusion.
6. Add a TUI-local typed syntax provider, merge it in `TautApp._command_syntax`,
   register both aliases, and route them through the guarded quit action.
7. Add the closed-inventory cross-mode/modal red matrix for Ctrl-C/Ctrl-D,
   Ctrl-D-versus-PageDown proof, blocked-modal preservation, owned-run
   confirmation idempotence, and the existing bare-`q` text guard. Add a
   distinct priority any-mode action that rejoins central `application.quit`.
   In `test_tui_textual_contract.py`, retain one shipped-entry-point real-PTY
   probe per chord that writes literal `0x03`/`0x04` and observes guarded quit;
   Pilot-only key injection is not sufficient proof for that translation seam.
8. Update `actions.py`, app help, route/gesture inventories, implementation
   guide, extension README, changelog, plan index, and this execution log.
9. Run focused tests, the full TUI suite, Ruff, formatter, mypy, documentation
   and adversarial input gates, then independent completed-work review.

## Verification

```bash
uv run --project extensions/taut_tui --extra dev pytest \
  extensions/taut_tui/tests/test_tui_app.py \
  extensions/taut_tui/tests/test_tui_screens.py \
  extensions/taut_tui/tests/test_tui_command_bindings.py \
  extensions/taut_tui/tests/test_tui_textual_contract.py -q
uv run --project extensions/taut_tui --extra dev pytest \
  extensions/taut_tui/tests -q
uv run --project extensions/taut_tui --extra dev ruff check \
  extensions/taut_tui/taut_tui extensions/taut_tui/tests
uv run --project extensions/taut_tui --extra dev mypy \
  extensions/taut_tui/taut_tui extensions/taut_tui/tests
bin/check-plan-status-index
uv run pytest tests/test_docs_references.py -q
uv run bin/check-doc-paths
git diff --check
```

## Rollback and Risk

The change is TUI-only, contains no persistence or lifecycle migration, and is
revertible as one source commit. The main risks are accidentally teaching core
CLI syntax about shell-only aliases, bypassing guarded quit, or letting a
priority chord corrupt/dismiss text without taking the quit path. Cross-mode
firing tests and an independent diff review are the stop gates.

## Execution and Review Log

- 2026-08-17: User clarified that CLI-mirror entry must remain text-first and
  requested `:q` and `:quit`.
- 2026-08-17: User added Ctrl-C and Ctrl-D as any-mode quit chords. Bare `q`
  remains mode-sensitive; the chords need a distinct priority action.
- 2026-08-17: Baseline inspection found the completion list remained focusable
  and neither alias existed in core or TUI syntax. The chosen boundary is a
  passive completion list plus a TUI-local syntax contribution routed through
  the existing guarded quit owner.
- 2026-08-17: Independent plan review was BLOCKED first on exact spec/promotion,
  Ctrl-D paging, modal/lease scope, guarded idempotence, syntax proof, and file
  ownership. Round two retained one real-PTY proof blocker plus two record
  corrections. All findings were accepted; round three returned PASS.
- 2026-08-17: The reviewed strategy-B spec delta and reciprocal backlink were
  promoted against baseline `2e2a56f` with spec-diff SHA-256
  `b1f1509c06057cff877d1499f734b4ab806ba865d991bc68e113fd3fd36dff9d`.
- 2026-08-17: The passive-completion real-app test failed because the list was
  focusable, then passed after a non-focusable completion owner preserved Tab,
  Up/Down-plus-Enter, and one-click insertion.
- 2026-08-17: `q` failed first, then `quit` failed independently. Both passed
  after TUI-local syntax/bindings rejoined central guarded
  `application.quit`; non-eager editing, composer promotion, core exclusion,
  and an active-dump blocker also passed.
- 2026-08-17: Ctrl-C and Ctrl-D each failed to reach the guarded owner from
  compose. Both passed after app-level priority bindings rejoined central
  dispatch. The 20-case chord/surface matrix passed, Ctrl-D was removed from
  paging while PageDown retained it, and bare `q` remained compose text.
- 2026-08-17: Repeated any-mode quit initially stacked owned-run confirmation
  screens. The retained regression passed after confirmation ownership became
  single-flight; cancel restored the underlying modal and active-dump refusal
  preserved it.
- 2026-08-17: Real PTY probes wrote literal `0x03` and `0x04` through the
  production launch boundary and observed guarded `application.quit` before a
  clean exit.
- 2026-08-17: Initial completed-work review found one test-proof defect: the
  closed surface matrix displayed command/search screens without proving the
  corresponding interaction modes. The corrected matrix enters the composer,
  command palette, command line, and search through production routes, asserts
  `COMPOSE`, `COMMAND`, and `SEARCH`, and passes all 20 chord/surface cases.
  Round-two independent review returned PASS.
- 2026-08-17: Final local verification passed the full TUI suite (378 tests),
  Ruff, formatting, mypy, documentation/reference tests, `check-doc-paths`
  over 63 sources and 1,319 claims, the plan index, and `git diff --check`.
  The owner directed inclusion in the coordinated 0.9.2 release; this commit
  closes the implementation slice before the release machinery is rerun.
