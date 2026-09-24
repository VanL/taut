# TUI Text Selection and Clipboard Plan

Status: draft — owner-requested enhancement (2026-09-24); mechanism verified
against Textual 8.2.8; owner chose copy trigger (a) on 2026-09-24; awaiting
independent plan review.

Class: 5 (spec-changing) and risky under [DOM-5]: the change revises the
normative mouse contract in [TUI-8.2], adds a key to [TUI-8.1], and writes to
the host clipboard through a terminal escape, which is a new outbound
terminal-protocol surface governed by [TUI-12.2]. Hardening applies. Not
process-changing.

Plan type: implementation with spec revision.

Owner: implementing engineer. Owner direction (2026-09-24): "we should also
make the text selectable. Right now it highlights but that blocks selection.
We should be able to copy the text for pasting — in fact, highlighting and
leaving something highlighted for more than half a second or so should
perhaps trigger a write to the clipboard."

## Goal

Let a human select transcript text with the mouse and get it onto the
clipboard, without losing single-click row selection. Today a drag in the
transcript moves the row highlight and never selects text, because the
transcript is a `TautOptionList` and Textual's `OptionList` disables the
framework's text selection (`ALLOW_SELECT = False`). The README's only
answer is the terminal's modified drag (Shift-drag), which bypasses the TUI
entirely. Textual already provides the pieces: screen-level text selection
across widgets that allow it, `Screen.get_selected_text()`, and
`App.copy_to_clipboard()` which emits OSC 52.

## Requested Outcomes

- [ ] A plain mouse drag in the transcript selects text across rows; a
  single click still focuses and selects the row ([TUI-8.2] preserved).
- [ ] The selected text is what the user sees: the display-policy-filtered
  rendering under [TUI-12.2]/[TAUT-6.4], never raw message bytes, so a
  paste cannot relay control sequences the display suppressed.
- [ ] Copy: an explicit `y` (yank) key copies the current selection; and,
  per owner direction, a selection that is complete and unchanged for 500
  ms is copied automatically (trigger (a), owner decision 2026-09-24). A transient status line reports what was copied.
- [ ] The clipboard write uses Textual's OSC 52 path; unsupported
  terminals are documented (Terminal.app; tmux without `set-clipboard on`).
- [ ] [TUI-8.1], [TUI-8.2], [TUI-12.2], the TUI README, and the root README
  sentence about modified-drag are updated; help text names `y` and the
  auto-copy behavior.

## Source Documents

Source specs:

- `docs/specs/10-taut-tui.md` [TUI-5.3] (transcript rows), [TUI-8.1]
  (vi-like keys), [TUI-8.2] (mouse), [TUI-12.2] (terminal text and
  untrusted content), [TUI-13.2] (required matrices)
- `docs/specs/02-taut-core.md` [TAUT-6.4] (terminal escape policy: display-
  time safety control against accidental relay)
- `docs/specs/01-development-documentation-operating-model.md` [DOM-5],
  [DOM-6], [DOM-15]

Supporting context:

- `docs/program-theory.md` [THEORY-3] "Terminal escape policy" row and
  [THEORY-4] principle 4 (presentation filtering prevents accidental relay).
- Textual 8.2.8 in the retained lock: `App.ALLOW_SELECT` (`app.py:403`),
  `Widget.ALLOW_SELECT` (`widget.py:328`), `Widget.get_selection`
  (`widget.py:4213`), `Screen.get_selected_text` (`screen.py:963`),
  `Screen.text_selection_started_signal` (`screen.py:321`),
  `App.copy_to_clipboard` (`app.py:1770`, OSC 52, documented as not working
  on macOS Terminal.app), `OptionList.ALLOW_SELECT = False`
  (`widgets/_option_list.py:111`), `OptionList._on_click` (`:721`) and
  `_on_mouse_move` (`:740`).
- `docs/plans/2026-09-24-tui-participation-loop-plan.md` (draft): owns the
  viewport/scroll-anchor extraction; this plan must not touch scroll
  anchoring.
- `README.md` line ~221 and `extensions/taut_tui/README.md`: the modified-
  drag sentence.

## Spec Baseline

- `c894059` (0.9.9 release SHA) — `docs/specs/10-taut-tui.md` and
  `docs/specs/02-taut-core.md` at plan authoring time.
- Promotion baseline identifier: recorded after the spec-promotion slice.

## Proposed Spec Delta

Promotion strategy: **A — in-file edit, text before link claims**.

| Spec file | Strategy | Sections touched |
|-----------|----------|------------------|
| `docs/specs/10-taut-tui.md` | A | [TUI-8.1] key table (`y`); [TUI-8.2] drag and copy paragraph; [TUI-12.2] copied-text rule; [TUI-13.2] matrix row; `## Related Plans` |

### [TUI-8.2] — replace the modified-drag paragraph

Current text:

> There is no hover-only information or action. Help documents the terminal's
> modified-drag escape for native text selection (commonly Shift-drag), and the
> TUI must not deliberately disable that terminal escape. Mouse and keyboard
> parity tests exercise the same action ids and resulting model changes.

Proposed text:

> There is no hover-only information or action. A plain drag in the
> transcript selects text across one or more rows using the framework's
> text selection; a single click without drag still selects the row. The
> selection is presentation state ([TUI-4.2]) and never moves a cursor,
> claims a pointer, or changes the selected message. `y` copies the current
> selection to the clipboard; a selection that is complete and unchanged
> for 500 ms is copied automatically. Copying writes the host clipboard
> through the terminal's OSC 52 sequence and reports the copied length in
> the status line; terminals that do not honor OSC 52 (macOS Terminal.app;
> tmux without `set-clipboard on`) receive the sequence and ignore it, and
> help names them. Help still documents the terminal's modified-drag
> escape (commonly Shift-drag), and the TUI must not deliberately disable
> it. Mouse and keyboard parity tests exercise the same action ids and
> resulting model changes.

### [TUI-8.1] — add to the key table

> | `y` | copy the current text selection to the clipboard | transcript |

### [TUI-12.2] — append one rule

> Copied text is the rendered, policy-filtered display text of the selected
> region, exactly as the escape policy ([TAUT-6.4]) presented it, never the
> stored message bytes. A paste therefore cannot relay a control sequence
> the display suppressed. The OSC 52 payload is base64 and carries no
> terminal-interpreted bytes from message content.

### [TUI-13.2] — add a matrix row

> | Mouse drag across three transcript rows, one containing an escaped control sequence; `y`; then a 500 ms stable selection | `get_selected_text()` equals the rendered rows; the driver receives exactly one OSC 52 write per copy whose payload decodes to that text; the escaped sequence appears as its display form; row selection unchanged | real `TautApp` under `run_test`, real SQLite, driver write captured at the driver seam |

### `## Related Plans` — add

> - `docs/plans/2026-09-24-tui-text-selection-and-clipboard-plan.md` —
>   enables framework text selection in the transcript, adds `y` and timed
>   auto-copy through OSC 52, and pins copied text to the policy-filtered
>   display form.

## Context and Key Files

Files to modify:

- `extensions/taut_tui/taut_tui/widgets.py` — `TautOptionList(OptionList)`
  (line ~367): inherits `ALLOW_SELECT = False`; override to `True` for the
  transcript instance only (the navigation list keeps row semantics) and
  implement `get_selection(selection)` if the inherited `Widget` default
  does not produce text for `OptionList` strips — verify in task 3 before
  assuming either way.
- `extensions/taut_tui/taut_tui/app.py` — the transcript is composed at
  line ~421 (`TautOptionList(id="transcript")`); bindings at ~310–330 (`y`
  is unbound; `ctrl+c` is quit with priority and stays so); the status line
  writer; the [TUI-12.2] display escaping already applied when rows are
  rendered (`escape_message_body`, `escape_inline_text` in
  `_message_prompt`, ~3462), which is what makes "copy the display text"
  free.
- `extensions/taut_tui/tests/test_tui_app.py`, a new
  `tests/test_tui_selection.py`, `tests/test_tui_textual_contract.py` (add
  the OptionList `ALLOW_SELECT` default and the OSC 52 write shape to the
  Textual-boundary contract so a Textual upgrade that changes either is
  caught).
- `extensions/taut_tui/README.md`, `README.md` (~221), help text.

Read first: [TUI-8.2], [TUI-12.2], [TUI-4.2]; Textual's `Screen`
selection handling (`screen.py` around 1737–1900: mouse capture, auto-
scroll, `allow_select` gate at ~1895) and `OptionList._on_click`; the
participation plan's viewport section so drag auto-scroll does not fight
the tail pin.

Comprehension gate (answers in the Execution Log before editing):

1. **Why does a drag currently move the row highlight?** Expected:
   `OptionList` opts out of framework selection, so the screen never
   captures the drag as text selection; the widget's own mouse handlers
   treat the pointer as row navigation.
2. **Why copy the rendered text rather than `message.text`?** Expected:
   the display already applied the [TAUT-6.4] escape policy; copying the
   stored bytes would re-create the accidental-relay hazard on paste.
3. **What can the TUI know about whether the clipboard write succeeded?**
   Expected: nothing; OSC 52 is fire-and-forget, so the status line reports
   the attempt and help names known-unsupported terminals.

## Invariants and Constraints

- Single click behavior in [TUI-8.2] is unchanged: focus plus row
  selection; a drag that ends where it started is a click.
- Text selection is session-only presentation state ([TUI-4.2]); it never
  moves a cursor, claims a pointer, or changes the selected message or the
  active target.
- Copied text is the rendered display form (rule above); the raw message
  never reaches the clipboard path.
- `ctrl+c` remains quit; copy is `y` plus the timed trigger.
- Textual's selection auto-scroll must not un-pin the tail or fight the
  viewport owner from the participation plan; if a drag at the bottom
  scrolls, it counts as user viewport intent (the same rule the viewport
  owner already applies to keyboard and wheel).
- No new dependency; no pyperclip or platform clipboard tool.
- The OSC 52 write goes through Textual's driver seam only (`app.py:1770`);
  the TUI never writes escape bytes itself.
- Navigation list, inspector, and forms keep their current selection
  semantics; only the transcript gains text selection in this plan.

Hidden couplings:

- `OptionList._on_mouse_move` (`:740`) may change the highlighted row on
  hover-drag; with selection enabled the screen captures the mouse first
  (`screen.py:~1895` gate), so verify the row highlight does not follow
  the drag.
- The transcript is rebuilt on delivery (`_render_messages`); a rebuild
  during an active selection clears it. Acceptable (selection is
  ephemeral), but the auto-copy timer must be cancelled on rebuild so a
  half-selected region is not copied.
- The status line is shared with operation state; the "copied" note is a
  transient toast-class message that must not overwrite an error.

Failure policy: a driver write failure while copying is a presentation
failure ([TUI-12.1]): report through the safe notification path, keep the
selection, change nothing else.

## Rollout, Rollback, and One-Way Doors

- Source revert. No storage or wire change. No one-way door.
- Post-deploy signal: in Ghostty, iTerm2, kitty, or WezTerm, drag three
  rows, wait, paste elsewhere; the pasted text equals the rows as shown.

## Dependency-Ordered Tasks

1. **Independent plan review** including the delta.
3. **Verify the seam before coding.** In a scratch script under
   `run_test`, set `ALLOW_SELECT = True` on the transcript, drive a drag
   with the pilot, and print `screen.get_selected_text()`. Record whether
   `OptionList` yields text through the inherited `get_selection` or needs
   an override, and whether the row highlight moved. Stop and revise the
   plan if the framework cannot select across `OptionList` strips at all;
   the fallback design is a `Static`-per-row transcript, which is a larger
   change and needs its own review.
4. **Spec-promotion slice**; record the promotion baseline.
5. **Red tests** (`tests/test_tui_selection.py`): (a) drag across three
   rows yields the rendered text and leaves the selected message and
   cursors unchanged; (b) `y` produces exactly one driver write matching
   `\x1b]52;c;<base64>\a` whose payload decodes to the selection; (c) with
   the timed trigger enabled, a selection held unchanged for 500 ms
   produces one write and a changed selection resets the timer (use a
   controlled clock or the app's timer seam, not sleeps); (d) a row with an
   escaped control sequence copies its display form; (e) a transcript
   rebuild during selection cancels the pending copy. All must fail at
   baseline because no text is selectable.
6. **Implement.** Enable selection on the transcript instance, add the
   `get_selection` override if task 3 showed it is needed, bind `y`,
   implement the timed copy as a Textual timer started on
   `text_selection_started_signal` and reset on selection change, cancelled
   on rebuild; route the write through `App.copy_to_clipboard`; add the
   status note. Stop if the implementation needs to intercept raw mouse
   events in the widget; the screen's selection machinery must own the
   drag.
7. **Contract tests.** Add the `OptionList.ALLOW_SELECT` default and the
   OSC 52 shape to `test_tui_textual_contract.py` so a Textual bump that
   changes either fails loudly.
8. **Docs.** README (root and extension), help text, [TUI-13.2] row,
   `docs/implementation/12-taut-tui.md` (why copied text is the display
   form; why OSC 52 and not a clipboard tool); CHANGELOG.
9. **Manual observation** in at least two real terminals (one OSC 52
   capable, one not) recorded in the Execution Log; completed-work review;
   index flip.

## Testing Plan

- Layer: real `TautApp` under Textual `run_test` with pilot mouse events;
  the driver write captured at Textual's driver seam (the same seam the
  handoff tests use), not by mocking `copy_to_clipboard`.
- Do not mock the screen's selection machinery or the transcript widget.
- Timer proof uses a controlled clock; no `sleep`.
- Mutation check: revert `ALLOW_SELECT` and confirm test (a) fails; remove
  the rebuild cancellation and confirm (e) fails.

## Verification and Gates

```bash
cd extensions/taut_tui && uv run --extra dev pytest -n 0 tests/test_tui_selection.py tests/test_tui_textual_contract.py
cd extensions/taut_tui && uv run --extra dev pytest
cd extensions/taut_tui && uv run --extra dev ruff check taut_tui tests && uv run --extra dev mypy taut_tui tests --config-file pyproject.toml
bin/check-doc-paths && bin/check-cli-claims && bin/check-plan-status-index
```

## Independent Review Loop

Reviewer: a different family. Inputs: this plan, the delta, `widgets.py`
`TautOptionList`, Textual's `screen.py` selection section and
`_option_list.py`, the task-3 scratch result. Ask: "Can the framework
select across OptionList strips without intercepting mouse events in the
widget? Is copying the display form the right answer to [TUI-12.2]?"

## Out of Scope

- Text selection in the navigation list, inspector, forms, or search
  results.
- Any clipboard mechanism other than OSC 52 (no subprocess to `pbcopy`,
  `xclip`, or `clip.exe`).
- Paste into the composer (bracketed paste already works through Textual).
- Scroll-anchor behavior during drag beyond declaring it user intent
  (participation plan).

## Assumptions and Open Questions

1. **Resolved 2026-09-24 (owner): trigger (a)** — copy when the selection
   is complete (button released) and unchanged for 500 ms, plus `y`.
   Rejected: (b) copy while held, (c) `y` only. Help states that any
   completed selection replaces the clipboard.
2. **Assumption:** the retained Textual lock (8.2.8) keeps
   `OptionList.ALLOW_SELECT = False` and the OSC 52 write shape; the
   contract test in task 7 turns that into a gate.

## Deviation Log

| Spec ref | Planned behavior | Actual behavior | Rationale | Spec proposal |
|----------|------------------|-----------------|-----------|---------------|

## Review Log

(append-only)

## Execution Log

(append-only)

- 2026-09-24 — Plan opened on owner request; mechanism verified: Textual
  8.2.8 selection is disabled by `OptionList.ALLOW_SELECT = False` on the
  transcript widget; `copy_to_clipboard` emits OSC 52.
- 2026-09-24 — Owner decision: auto-copy trigger (a), "we will try the
  suggested auto-selection criteria now".

## Fresh-Eyes Review

The one unknown that could change the design is whether `OptionList` can
yield selected text through the framework at all; task 3 answers it with a
scratch run before the spec is promoted, and names the fallback. The
[TUI-12.2] copied-text rule is the safety decision and is stated as an
invariant, not left to the implementer.
