# TUI Multiline Composition and Whitespace Plan

Date: 2026-08-17

Class: 5. The requested multiline composer, modified-key behavior, transcript
spacing, and structural tab presentation revise [TUI-4.3], [TUI-5.3],
[TUI-6.3], [TUI-8.1], [TUI-12.2], [TUI-13.2], and [TUI-14]. The keyboard
compatibility surface also fires the [DOM-5] risky trigger, so the hardening
checklist applies and independent review must pass before implementation.

Status: completed 2026-08-17 after implementation, local and real-PTY
verification, independent review, and owner-authorized close-out.

## Goal

Add one terminal-row gap between transcript messages; replace the single-line
composer with a target-labelled multiline editor where Enter sends,
Ctrl-Enter inserts LF, Ctrl-J is the legacy-terminal newline fallback, and
Ctrl-Tab inserts a literal tab while Tab and Shift-Tab retain focus navigation.
Preserve actual newlines, blank lines, ordinary whitespace, and literal
backslash sequences distinctly; render stored tabs as four-column tab-stop
whitespace rather than visible `\t` notation.

## Source Documents and Spec Baseline

Plan type: implementation with spec revision.

Source specs and context consulted in the canonical startup order:

- `AGENTS.md`
- `docs/program-theory.md` [THEORY-1] through [THEORY-5]
- `docs/agent-context/decision-hierarchy.md`
- `docs/agent-context/principles.md`
- `docs/agent-context/engineering-principles.md`
- `docs/agent-context/runbooks/testing-patterns.md`
- `docs/agent-context/runbooks/writing-plans.md`
- `docs/agent-context/runbooks/hardening-plans.md`
- `docs/agent-context/runbooks/maintaining-traceability.md`
- `docs/agent-context/runbooks/review-loops-and-agent-bootstrap.md`
- `docs/agent-context/lessons.md` and the required portion of
  `docs/lessons.md`
- `docs/specs/01-development-documentation-operating-model.md` [DOM-5],
  [DOM-6], [DOM-10], [DOM-11], [DOM-15]
- `docs/specs/02-taut-core.md` [TAUT-6.4], [TAUT-6.5]
- `docs/specs/10-taut-tui.md` [TUI-4.2], [TUI-4.3], [TUI-5.3], [TUI-6.3],
  [TUI-8.1], [TUI-9.2], [TUI-12.2], [TUI-13], [TUI-14]
- `docs/implementation/12-taut-tui.md`
- `docs/plans/2026-08-12-taut-tui-implementation-plan.md`

Spec baseline:

- `6aa0f741f71cc99092e28d899acf31de8ac450da` — the source specs and
  implementation note above at plan authoring time.

Promotion strategy: A — put the reviewed behavior text into the existing
active spec before production code; add reciprocal implementation evidence
and the final traceability links with the implementation slice.

Promotion baseline: `6aa0f741f71cc99092e28d899acf31de8ac450da` plus the
worktree delta to `docs/specs/10-taut-tui.md` and its reciprocal plan backlink,
verified by the plan-index, document-path, reference, and diff gates before
production edits.

## Current Structure, Ownership, and Reproduction

- `extensions/taut_tui/taut_tui/widgets.py` owns every Textual display/input
  sink. `TautInput` is a single-line Textual `Input`; `escape_display_text()`
  preserves LF by escaping each line separately but sends TAB through core's
  default C0 policy, which renders it as printable `\t`.
- `extensions/taut_tui/taut_tui/app.py` mounts `TautInput` as `#composer`,
  dispatches `message.send` from `Input.Submitted`, stores scalar draft cursor
  offsets, creates one `OptionList` option per message, and derives scroll
  height from the same Rich prompt it displays.
- `extensions/taut_tui/taut_tui/models.py` correctly keeps target-keyed draft
  text and a scalar code-point cursor offset outside the responsive widget
  tree, but its docstring incorrectly narrows that state to one line.
- Textual 8.2.8 `Input` discards all but the first pasted line. Its `TextArea`
  keeps multiline paste, uses `(row, column)` cursor locations, supports
  `tab_behavior="focus"`, and inserts LF on plain Enter unless an owned
  priority binding intercepts the key first.
- Textual's parser distinguishes Kitty CSI-u Ctrl-Enter and Ctrl-Tab and its
  Linux driver requests the enhanced keyboard protocol. Legacy terminals may
  collapse Ctrl-Enter into Enter and Ctrl-Tab into Tab. Ctrl-J remains
  distinguishable as LF and is the newline fallback; pasted tabs remain the
  literal-tab fallback.
- Actual stored LF already survives envelope storage and reaches the transcript
  as structural LF. Literal two-character `\n` remains literal. The renderer
  must never decode slash escapes because that would corrupt code, regexes,
  JSON, and shell text.
- Adding CSS bottom padding to an `OptionList` option is unsafe: Textual 8.2.8
  renders the padding but omits it from cached option heights and virtual size.
  A prompt-owned trailing LF is counted by both Rich wrapping and Taut's
  `_message_row_height()` and therefore preserves scroll accounting and the
  one-option-to-one-message index invariant.

Tight red-capable feedback loop, already run at the baseline:

```text
uv run --project extensions/taut_tui --extra dev --locked python - <<'PY'
# real TautApp.run_test probe asserting TextArea composer, Ctrl-Enter LF,
# structural LF, one-row message gap, and structural TAB presentation
PY
```

Observed result:

```text
{'multiline_widget': False, 'ctrl_enter_newline': False,
 'structural_newlines': True, 'message_gap': False,
 'tab_whitespace': False}
AssertionError
```

The reproduction is deterministic, sub-second, and exercises the real Textual
widget and transcript prompt path. The first committed regression test will
replace the inline probe as the canonical loop.

## Required Reading and Comprehension Gate

Read the current `TautInput`, `escape_display_text()`, composer event/capture/
restore/send paths, `_render_messages()`, `_message_prompt()`,
`_message_row_height()`, `DraftState`, the nearby composer/resize/anchor tests,
and Textual 8.2.8 `TextArea._on_key()` before editing.

1. What must a newline key binding do before `TextArea._on_key()`? Expected
   answer: an Enter-to-submit binding must be priority-owned so plain Enter
   cannot insert LF; Ctrl-Enter/Ctrl-J explicitly insert LF and do not submit.
2. Why may the transcript not add separator options or CSS vertical padding?
   Expected answer: option indices are message indices, and Textual's cached
   option height excludes component vertical padding. A prompt-owned structural
   LF keeps selection and scroll math on the real rendered height.
3. Should visible `\n` be decoded? Expected answer: no. Actual LF is already
   structural; a literal slash-n sequence is message content and remains exact.

The implementer records these answers in the Execution Log. Any different
answer blocks production edits until the owner text and probes are reread.

## Invariants, Hidden Couplings, and Constraints

- Storage, Python objects, and JSON retain exact accepted text. Presentation
  expansion of tabs never mutates the draft sent to core or the stored message.
- Actual LF, consecutive blank lines, leading/trailing spaces, repeated spaces,
  actual TAB, and literal slash sequences remain distinguishable. Do not trim
  or decode. In particular, actual LF differs from literal `\n`, and actual
  TAB differs from literal `\t`.
- Core blank-message behavior remains unchanged: `.strip()` may decide whether
  send is enabled/no-op, but the untrimmed nonblank draft is sent.
- Enter still dispatches the existing typed `message.send` keyboard route.
  Modified insertion keys do not dispatch a domain action or clear the draft.
- Tab and Shift-Tab remain forward/reverse focus movement. Ctrl-Tab alone
  inserts TAB. Ctrl-J is an additive newline fallback, not a send alias.
- The composer adapter owns TextArea-specific `.text`, change, paste, cursor,
  submission, and key details. `TautApp` consumes its narrow scalar-offset
  interface; TextArea tuple locations must not leak into `DraftState`.
- Draft preservation across target switches, resize, too-small mode, failed
  sends, and stale successful sends remains exact for multiline text and cursor.
- One transcript option continues to map to one `_message_rows` entry. Message
  selection, reply lookup, search anchoring, and scroll restoration must not
  gain separator indices or guessed heights.
- A one-row prompt gap may follow the final message as harmless transcript tail
  breathing room; adjacent messages must always have exactly one empty row
  beyond body-owned blank lines.
- Tabs expand in every TUI message-body projection at four-column stops
  relative to each body line. They never reach the terminal as raw C0 bytes,
  so terminal escape safety remains owned at the display sink. All other
  dynamic fields and selected controls retain the configured core escape
  policy.
- Recoverable domain/presentation failures preserve draft state. A successful
  domain send remains successful even if transcript redraw fails, per [TUI-12].
- No new dependency, storage field, command, action id, mode, or configuration
  key is introduced.

## Rollback, Rollout, and Success Signals

The change is code/spec-only and introduces no persistence migration or one-way
door. Rollback is a coordinated revert of the TUI spec delta, composer adapter,
transcript presentation, tests, and implementation note; stored multiline
messages remain valid core content before and after rollback. Ship all pieces
in one TUI release so a spec promising multiline input cannot accompany the
old single-line widget.

Post-deploy success is observable when a real enhanced-protocol terminal can
compose `one<Ctrl-Enter>two<Ctrl-Tab>three`, Enter sends one exact message, a
second client reads `"one\ntwo\tthree"`, and the transcript shows the blank
line/tab spacing without visible escape notation. On a legacy terminal,
Ctrl-J and paste supply newline/tab input; the Send control remains the
submission fallback. A failure to distinguish modified keys is a declared
terminal limitation, not a data-loss fallback to submission.

## Proposed Spec Delta

### `docs/specs/10-taut-tui.md` [TUI-4.3]

Replace:

> - `COMPOSE`: edit the single-line, target-labelled message composer;

with:

> - `COMPOSE`: edit the multiline, target-labelled message composer;

### [TUI-5.3] — append

> One empty terminal row separates adjacent transcript messages. Message bodies
> preserve actual LF as line breaks, including consecutive blank lines, and
> render horizontal tabs as four-column tab-stop whitespace. Literal backslash
> sequences remain literal message content and are never decoded as layout.

### [TUI-6.3] — append after the first paragraph

> The composer accepts multiline paste. Terminal and Textual paste handling may
> normalize recognized line boundaries to LF and remove NUL; apart from that
> boundary normalization, the composer preserves the pasted nonblank text.
> Plain Enter sends through `message.send`. Ctrl-Enter inserts LF without
> sending; Ctrl-J is the legacy-terminal newline fallback. Ctrl-Tab inserts a
> literal horizontal tab while Tab and Shift-Tab retain focus navigation. The
> inserted LF and tab remain exact message content through the public send path.

### [TUI-8.1] — append after the gesture table

> In `COMPOSE`, Enter dispatches `message.send`, Ctrl-Enter or Ctrl-J inserts a
> newline, and Ctrl-Tab inserts a literal tab. Tab and Shift-Tab continue to move
> among focusable visible surfaces. Ctrl-Enter and Ctrl-Tab require a terminal
> that reports modified Enter/Tab distinctly; Ctrl-J and multiline paste are
> the portable newline path, and paste is the portable literal-tab path.

Replace:

> Tab and Shift-Tab always move among focusable visible surfaces or form fields.

with:

> Tab and Shift-Tab always move among focusable visible surfaces or form fields;
> only the explicit Ctrl-Tab compose gesture inserts a tab.

### [TUI-12.2] — append

> TUI message-body display sinks treat LF and horizontal tab as structural
> layout: LF remains a line boundary and horizontal tab expands to spaces at
> four-column stops before rendering. This applies consistently to transcript,
> selected-message, and reply-inspector bodies. These two TUI presentation
> exceptions do not decode printable escape notation and do not change stored
> content. Every other selected terminal control still passes through the
> configured public escape policy.

### [TUI-13.2] — add a required matrix bullet

> - multiline compose typing and paste; Enter send; Ctrl-Enter, Ctrl-J, and
>   Ctrl-Tab insertion; Tab/Shift-Tab focus movement; exact send/failure/resize/
>   target-switch draft preservation; actual LF versus literal `\n` and actual
>   TAB versus literal `\t`; consecutive blank lines, leading/trailing/repeated
>   spaces, four-column tab expansion before escape-notation generation;
>   consistent transcript/selected-message/reply-inspector bodies; one-row
>   inter-message spacing; sender names and reply-thread labels retaining the
>   configured control-escape policy beside structural bodies; and scroll-anchor
>   preservation across those variable-height rows;

### [TUI-14] — remove

> - multiline message composition;

## Dependency-Ordered Tasks

1. **Independent plan and delta review; spec promotion.**
   - Review this plan, exact proposed text, baseline spec, implementation note,
     current widgets/app/model paths, and Textual floor behavior.
   - Resolve every finding in the Review Log. A non-PASS verdict blocks code.
   - Apply strategy A to `docs/specs/10-taut-tui.md`, add its Related Plans
     backlink, run plan/doc/diff gates, and record the worktree promotion
     baseline.

2. **RED→GREEN composer adapter tracer bullet.**
   - Files: `extensions/taut_tui/taut_tui/widgets.py` and
     `extensions/taut_tui/tests/test_tui_textual_contract.py`.
   - Add one failing real-Pilot test for Enter submit, Ctrl-Enter/Ctrl-J LF,
     Ctrl-Tab TAB, Tab/Shift-Tab focus, and multiline paste. Then add one owned
     `TautComposer(TextArea)` with priority bindings, protected placeholder,
     an owned submitted message, and scalar cursor-offset conversion.
   - Keep real Textual. Do not mock `_on_key`, the document, bindings, or paste.
   - Stop if this requires overriding a private framework method instead of
     public bindings/actions/document APIs.

3. **RED→GREEN real application multiline send.**
   - Files: `app.py`, `models.py`, `test_tui_app.py`,
     `test_tui_action_routes.py`, and `test_tui_action_handlers.py`.
   - First prove Ctrl-Enter does not dispatch, Enter fires the existing typed
     keyboard route, exact multiline/tab content crosses real SQLite/client
     send/read, and success/failure/target-switch/resize draft rules hold.
   - Migrate every composer consumer from Input vocabulary to the owned adapter;
     update the draft docstring without changing its scalar state contract.
   - Stop if a second send path/action id appears or if any test must mock core
     storage/routing to pass.

4. **RED→GREEN transcript spacing and whitespace.**
   - Files: `widgets.py`, `app.py`, `test_tui_textual_contract.py`, and
     `test_tui_app.py`.
   - First add cases for actual LF versus literal slash-n, actual TAB versus
     literal slash-t, consecutive blank lines, leading/trailing/repeated spaces,
     tab-stop alignment, transcript/selected-message/reply-inspector
     consistency, two-message spacing, and selected-option/message index
     identity. Add a structural trailing LF to the existing message prompt and
     safe four-column tab expansion on raw bodies before escape notation is
     generated at each TUI message-body display boundary.
   - In the selected-message and reply-inspector cases, pair body LF/TAB with
     actual LF/TAB in `from_name` and `reply_thread`; body whitespace must be
     structural while metadata remains printable core escape notation. Do not
     pass a concatenated metadata/body string through the message-body adapter.
   - Extend the real viewport-anchor test with multiline/tab/gap height.
   - Stop if CSS padding, separator options, raw terminal TAB, or guessed row
     heights are introduced.

5. **Traceability, visual acceptance, and final review.**
   - Update `docs/implementation/12-taut-tui.md` with composer ownership,
     modified-key compatibility, tab presentation, and prompt-owned gap/scroll
     rationale. Update Related Plans and this plan's logs/index state.
   - Regenerate representative screen artifacts only if the stable transcript
     fixture makes the spacing delta reviewable; otherwise inspect a real
     deterministic screenshot and state why committed goldens are unchanged.
   - Run focused, full TUI, static, docs, and diff gates. Obtain an independent
     completed-work review against every task and invariant.

## Testing and Verification

Vertical red-green order is mandatory: composer widget, real send/draft, then
transcript presentation/anchor. Each new test must be observed failing for its
named symptom before the production edit that makes it pass.

Focused gates:

```bash
uv run --project extensions/taut_tui --extra dev --locked pytest -q \
  extensions/taut_tui/tests/test_tui_textual_contract.py \
  extensions/taut_tui/tests/test_tui_app.py \
  extensions/taut_tui/tests/test_tui_action_routes.py \
  extensions/taut_tui/tests/test_tui_action_handlers.py \
  -k 'composer or whitespace or message_gap or transcript_viewport_anchor'
```

Final gates:

```bash
uv run --project extensions/taut_tui --extra dev --locked pytest -q \
  extensions/taut_tui/tests -n 0
uv run --project extensions/taut_tui --extra dev --locked ruff check \
  extensions/taut_tui/taut_tui extensions/taut_tui/tests
uv run --project extensions/taut_tui --extra dev --locked mypy \
  extensions/taut_tui/taut_tui extensions/taut_tui/tests
bin/check-plan-status-index
uv run --no-sync bin/check-doc-paths
uv run --extra dev pytest -q tests/test_docs_references.py -n 0
git diff --check
```

Manual acceptance must use one real terminal with enhanced key reporting and
one legacy-path probe for Ctrl-J/paste. The black-box payload is
`one\n\n  two\tthree  ` plus literal `\n\n` and `\t`; verify exact data from
a second client and visibly distinct transcript output.

## Independent Review Loop

Use an independent agent that did not author the plan. Review stance:

> Read this plan, its Proposed Spec Delta, the baseline TUI/core specs, the TUI
> implementation note, current widget/app/model code, and pinned Textual 8.2.8
> behavior. Check every named file/symbol. Challenge terminal compatibility,
> exact-content preservation, TextArea cursor/paste migration, display safety,
> OptionList height/index coupling, TDD seams, rollback, and performative
> complexity. Do not implement. Return PASS or BLOCKED with source-backed
> findings and say whether a zero-context engineer can implement confidently.

After implementation, a different independent pass compares every planned
task and invariant with the diff and current test evidence. Every finding is
accepted and fixed or explicitly rebutted in the Review Log; BLOCKED prevents
completion.

## Out of Scope

- Durable drafts, key remapping/configuration, editor syntax highlighting,
  markdown rendering, automatic slash-sequence decoding, or content rewriting.
- Changing core storage, `say()`/`reply()` semantics, message size limits,
  blank-message rules, terminal policy for CLI/MCP/Summon, or form inputs.
- Fractional-line spacing, separator options, or a transcript widget rewrite.
- A universal promise that legacy terminal protocols can distinguish modified
  Enter/Tab; the documented fallbacks are the compatibility boundary.

## Deviation Log

| Spec ref | Planned behavior | Actual behavior | Rationale | Spec proposal |
|----------|------------------|-----------------|-----------|---------------|
| [TUI-12.2], [TUI-13.2] | The reviewed delta expanded LF/TAB only in the transcript sink. | Apply the same message-body adapter to transcript, selected-message, and reply-inspector bodies. | Regenerated visual evidence showed the selected-message inspector rendering visible `\t` beside the corrected transcript. The user's request covers message rendering, and inconsistent views are a visible defect. Names, logs, diagnostics, and other dynamic fields keep the core policy. | Promoted as a focused [TUI-12.2]/[TUI-13.2] worktree amendment before the dependent code edit; scoped review pending. |

## Review Log

| Date / baseline | Reviewer | Verdict and findings | Disposition |
|-----------------|----------|----------------------|-------------|
| 2026-08-17, `6aa0f74` plus draft plan | Claude Fable 5, read-only | PASS. P2: exact paste preservation overclaimed framework normalization of line boundaries and NUL. P2: actual TAB versus literal `\t` was absent from the exact-content matrix. All framework, key-protocol, prompt-height, path, and replacement-location claims verified. | Both accepted before promotion: narrowed paste exactness to the terminal/Textual normalization boundary; added TAB/literal-slash-t separation and required expansion before escape-notation generation. Non-actionable observations remain out of scope. |
| 2026-08-17, focused message-body sink widening | Independent Codex read-only review | BLOCKED. P2: the widened boundary lacked a firing test proving sender names and reply-thread labels keep core LF/TAB escape notation beside structurally rendered message bodies; reply-inspector concatenation made accidental widening plausible. | Accepted. Added the negative boundary to [TUI-13.2], task 4, and the invariant matrix. Round-two review required before dependent code. |
| 2026-08-17, focused message-body sink widening round two | Independent Codex read-only review | PASS. No P1 or P2 findings. | The negative metadata boundary and paired firing-test requirement are implementation-ready. |
| 2026-08-17, completed-work review | Independent Codex read-only review | BLOCKED. P2: Ctrl-J lacked a direct firing test; failed/stale sends asserted text but not exact cursor state; required real-PTY acceptance evidence was absent. No implementation defect was found in spacing, display, storage, index, or scroll behavior. | Accepted all three. Added direct Ctrl-J input, full `DraftState` plus composer-cursor assertions for failure/stale completion, and an enhanced-protocol/legacy-path PTY probe with exact second-client readback. Round-two review required. |
| 2026-08-17, completed-work review round two | Independent Codex read-only review | PASS. All three accepted P2s are resolved; the focused tests pass; no new P1 or P2 finding. | Final review gate passed. |

## Execution Log

- 2026-08-17 pre-edit exploration: the real-app feedback loop reproduced four
  requested failures; actual LF/blank-line presentation was already green and
  literal slash-n remained distinct. A Textual 8.2.8 spike proved public
  priority bindings can implement Enter submit, Ctrl-Enter/Ctrl-J LF, and
  Ctrl-Tab TAB without overriding `_on_key()`.
- 2026-08-17 comprehension gate: plain Enter must be priority-owned before
  `TextArea._on_key()` while the modified bindings insert structure only;
  separator options break the message/index invariant and CSS padding is absent
  from Textual's cached height, so the prompt owns one trailing LF; printable
  slash-n is exact content and must never be decoded.
- 2026-08-17 RED→GREEN: the composer key contract first failed on the absent
  `TautComposer`; the real SQLite multiline/tab send flow then failed on the
  old `Input` query; tab-stop and prompt-gap cases failed on visible `\t` and
  absent trailing rows. The owned TextArea adapter, scalar cursor bridge,
  four-column message-body projection, and prompt-owned row made each case
  green without changing stored content.
- 2026-08-17 visual/deviation gate: regenerated 100×34 evidence exposed visible
  `\t` in the selected-message inspector. The reviewed spec amendment widened
  only message-body projections. A paired metadata/body test went red for the
  old concatenated/structural behavior, then green after segmented transcript,
  selected-message, and reply-inspector rendering. Sender names and reply
  labels retain core control notation.
- 2026-08-17 verification: all 328 extension tests passed; Ruff check and format
  check passed; mypy passed for all 16 extension source files; 11 documentation
  reference tests, documentation-path claims, plan-index status, deterministic
  screen generation, and `git diff --check` passed. The 100×34 artifact was
  inspected and shows whole-row message gaps, multiline/tab-stop bodies, and a
  multiline composer. Final independent implementation review passed after its
  three proof gaps were resolved.
- 2026-08-17 terminal acceptance: a real 80×10 PTY running Textual's Linux
  driver with `TERM=xterm-kitty` delivered CSI-u Ctrl-Enter and Ctrl-Tab plus
  legacy Ctrl-J to `TautComposer`; unmodified CSI-u Enter submitted through a
  real `TautClient`. A second client read back exactly
  `one\n\n  two\tthree  \nfour literal\\n\\n literal\\t  `, preserving structural
  whitespace, trailing spaces, and literal slash sequences distinctly.

## Fresh-Eyes Review

Independent review rechecked the named TextArea document/cursor APIs, exact
spec replacement locations, test selection expression, and framework height
couplings. The author re-read the revised delta after disposition; no missing
path, unresolved invariant, or scope-expanding ambiguity remains.
