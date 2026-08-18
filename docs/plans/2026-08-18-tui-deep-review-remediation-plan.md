# TUI Deep-Review Remediation Plan

Date: 2026-08-18

Status: active — independent review (Kimi, 2026-08-18) completed and
dispositioned; owner decisions recorded; strategy-A spec promotion applied
to the worktree spec tree. Code slices 2–7 may proceed against the
promoted text.

Owner: Taut maintainers

Class: 5 — the work revises several public TUI contracts (transcript
display decoding, command-palette input semantics, composer promotion,
compose keys, Summon pending-run quit) and repairs verified async,
terminal-ownership, and teardown defects across `taut_tui` and its Summon
integration. Trigger reasoning per [DOM-15]: public contract changes plus
risky lifecycle work; hardening is mandatory under both runbook trigger
lists (async/background work, contract changes, terminal one-way doors).

Plan type: implementation with spec revision.

Hardening: required — this plan applies
`docs/agent-context/runbooks/hardening-plans.md` throughout.

## Goal

Remediate every verified finding from the 2026-08-18 deep review of the
`taut_tui` extension: make transcript display decode sender-intent escape
sequences under a closed allowlist, repair the command palette's input
contract, stop spontaneous command-line promotion from programmatic draft
restores, fix the verified Summon terminal-lease and quit-lifecycle
defects, repair async/teardown correctness in session/system/domain
plumbing, and fix transcript state-integrity bugs (scroll anchor, selected
message, too-small shield, form deadlock). Land the already-implemented
Shift-Enter newline alias under this plan's authority.

## Finding Register and Decisions

IDs are stable for this plan. "Verified" means reproduced headlessly with
Textual Pilot against the real app, or traced through exact code paths with
the installed Textual 8.2.8 source during the 2026-08-18 review.

| ID | Finding (verified) | Disposition | Required outcome |
|----|--------------------|-------------|------------------|
| D1 | Messages containing literal `\n`/`\t` (agents typing escapes in shell-quoted `taut say` arguments; 9 such messages in the reference workspace, all agent-sent) render as raw text; the CLI display dialect already renders real LF as the glyphs `\n`, so both variants are indistinguishable in CLI surfaces | fix (owner-directed 2026-08-18: decode a closed allowlist; display the intent) | TUI message bodies decode the exact inverse of the terminal escape policy's output language before sink escaping; record and CLI unchanged |
| D2 | The [SUM-10] persona briefing shows only `taut say <thread> "..."` examples; agents have no multiline guidance, producing D1's data | fix | Briefing states literal `\n` in a quoted argument is not a newline and names stdin (`taut say <thread> -`) as the multiline path |
| K1 | Shift-Enter (the common chat-composer newline convention) was not a composer newline key | fix — already implemented and verified in the worktree under this plan's authority | `shift+enter` inserts LF alongside `ctrl+enter`/`ctrl+j`; spec, help, README, changelog aligned; land with Slice 3 |
| P1 | Palette: Up/Down do nothing while the query input has focus, contradicting the on-screen "Up/Down select" instruction | fix | Up/Down move the result highlight from the query input, matching `CommandLineScreen`'s pattern |
| P2 | Palette: Enter always activates the first enabled filtered entry with no visible highlight; with an empty query this silently executed "Initialize workspace" | fix | Enter activates only the visibly highlighted enabled entry; the browser opens with the first enabled row highlighted |
| P3 | Palette: a query with arguments ("summon kimi") matches nothing; Enter is a silent no-op; arguments are impossible | fix | Explicit no-match empty state naming the `:` command line; when the first token is an exact known root command, offer a handoff row that opens the command line prefilled |
| P4 | Help text and the status-bar button conflate the action browser and the `:` command line ("`: / Ctrl-P` commands") | fix | Distinct naming in help and affordance labels |
| L1 | Cancelling a promoted command line preserves the `:` draft (spec'd); merely reopening that conversation then re-promotes with zero keystrokes, because `_apply_conversation`'s programmatic `composer.text` assignment is indistinguishable from typing (reproduced) | fix | Only direct user composer editing promotes; programmatic restores never promote |
| L2 | Keystrokes between promotion and the modal taking focus land in the composer; the draft revision bumps, the originating-draft clear is skipped, and a stale `:command` draft survives (send-as-chat hazard) | fix | On mount the command line reconciles the composer's current draft; the stale suffix cannot be silently sent as chat |
| L3 | The command line presents a browsable completion list inside a centered dimming modal, which reads as a second action browser and blurs the two-surface design (owner direction 2026-08-18: the `:` surface is vi-like minimal — a bottom line that owns focus but does not block or obscure the live view; Esc quits; Tab completion with a "shadow" of what is available; it never engages the browser) | fix | The command line becomes a bottom-docked single-line surface: it owns keyboard focus while open, the conversation view stays fully visible and keeps rendering live updates behind it, and completion is inline ghost-shadow (dimmed shadow shows one matching command path, Up/Down change which match the shadow shows, Tab accepts it with an argument-ready space, feedback names other matches compactly) |
| S1 | Ctrl-C while the UI thread waits inside `App.suspend()` for a Summon lease raises KeyboardInterrupt out of the `with`, Textual never resumes application mode, and `hold()` swallows the exception: the app keeps running with a dead screen (high; violates [TUI-11.3] "restoration failure is fatal … and visible") | fix (owner-directed 2026-08-18: exit completely) | Exception exit from the suspend context records the lease failure and exits the TUI through normal teardown, leaving a restored terminal; the TUI never continues outside application mode |
| S2 | Pending owned runs (started, provider not yet ready) block every quit route with an error and no dialog, per current [TUI-11.2] text; a provider hung in bootstrap makes the TUI unquittable, and `TuiSummonOperations.close()` joins non-daemon workers so even process exit hangs | owner decision plus fix | [TUI-11.2] revision: pending-run quit offers a cancel-and-quit decision through a cooperative pre-ready cancellation seam; see Slice 2 stop-gate for the seam investigation |
| S3 | Worker-side cancel of an attach confirmation (e.g. the member is dismissed while the dialog is up) resolves the request but never dismisses the pushed `ConfirmationScreen`; the stale modal lies (Confirm is a latched no-op) | fix | The handler retains the screen reference and dismisses it when the request resolves without the user |
| S4 | `on_terminal_lease_request` runs `begin_lease` + `App.suspend()` even when the worker already timed out or the app is shutting down (its sibling handler checks both) | fix | Stale/shutdown lease requests are refused without suspending |
| S5 | Two concurrent summon starts can both observe `AVAILABLE`, and the loser of the confirm race dies with `RuntimeError` (DriverError aborts the run) instead of the graceful unavailable decline | fix | Owner contention at confirm degrades to the same decline path as unavailability |
| S6 | `_apply_summon_ready`/`_apply_summon_return` clobber `_operation_state` across concurrent runs/actions (status-line misreport only) | fix (fold into S-slice) | Summon status transitions do not overwrite an unrelated in-flight operation state |
| A1 | `submit_dump` raises `OperationAlreadyRunning` (and `ReplacementConfirmationRequired` via TOCTOU) synchronously; no caller catches it; the exception escapes the Textual handler and the TUI panics (violates [TUI-12.1] recoverable-failure priority) | fix | Overlapping/racing dump requests render as attached recoverable errors |
| A2 | Teardown race: a worker parked in no-timeout `call_from_thread` while `session.close()` blocks the UI loop in `future.result(timeout=7.0)` → guaranteed 7s quit stall plus a spurious "TUI cleanup failed: TimeoutError" toast | fix | Worker→UI marshalling cannot deadlock against teardown; quit does not stall or report false cleanup failure |
| A3 | Empty `read`/`inbox`/`log`/`list --dms` results raise `EmptyResultError` uncaught in `domain.py` and render as bold-red errors; `domain.search` already catches it | fix | Empty results use the existing "No results" presentation |
| A4 | `_commit_conversation_from_worker` checks the intent token on the worker thread only; `_apply_conversation` never re-checks on the loop, so a superseded open can flash stale state | fix | Loop-side re-check mirroring `_apply_optional_conversation` |
| A5 | `commit_returned_message` returns the live snapshot when the returned message matches neither target nor reply thread, triggering a full unnecessary re-render/composer reset | fix | Non-matching returns yield `None` |
| A6 | `_open_reply_owned` claims reply unread cursors before the commit/intent gates; a rejected open marks messages read that were never shown | fix | Unread claim happens only for an accepted open |
| A7 | `start_direct_message` sends `@{member}` unconditionally; typing `@alice` produces `@@alice` and a raw addressing error | fix | Normalize a single leading `@` |
| T1 | History-anchor re-render overwrites the transcript highlight with the anchor row, which rewrites `selected_message_id`; an open Reply form then submits against the wrong message | fix | Re-render preserves the selected message; anchor restoration must not mutate selection |
| T2 | Scroll anchor is captured only on resize and message deliveries; a notification-driven navigation refresh re-renders with the stored (usually tail) anchor and yanks the transcript to the bottom | fix | Anchor capture precedes every transcript re-render path |
| T3 | Leaving TOO_SMALL pops the shield only when it is the top screen; a modal pushed above it (e.g. Summon attach confirmation) strands the shield forever | fix | Shield removal is stack-aware |
| T4 | `NativeFormScreen` disables both buttons on submit; the reply/react/rename error paths that fire when context vanished route errors under the modal and never re-enable it — the form becomes unclosable | fix | Those error paths route through `show_domain_error`/`resume` like the session-starting path |
| T5 | Composer text typed with no active conversation drafts under `"__unselected__"` and is unrecoverable after opening any conversation | fix | The unselected draft is restored or explicitly surfaced, not silently dropped |
| T6 | A retained Textual fatal exits the process with status 0 (codified in [TUI-12.1] and `test_tui_launch.py`) | owner decision — default no action | Revisit only with an explicit [TUI-12.1] revision; out of scope here |

Any new evidence that changes a disposition must be recorded in the
Deviation Log before implementation continues.

## Source Documents

Source specs:

- `docs/specs/10-taut-tui.md` [TUI-2.2], [TUI-4.3], [TUI-5.3], [TUI-6.1],
  [TUI-6.2], [TUI-6.3], [TUI-7.1], [TUI-7.2], [TUI-8.1], [TUI-9.2],
  [TUI-10.2], [TUI-11.2], [TUI-11.3], [TUI-11.4], [TUI-12.1], [TUI-13.1],
  [TUI-13.2]
- `docs/specs/04-summon.md` [SUM-6], [SUM-7], [SUM-10]
- `docs/specs/02-taut-core.md` [TAUT-6.4] (terminal escape policy)
- `docs/specs/01-development-documentation-operating-model.md` [DOM-5],
  [DOM-10], [DOM-11], [DOM-15]

Canonical context consulted for this plan (read-order declaration): root
`AGENTS.md`/`CLAUDE.md`, `docs/agent-context/README.md`,
`docs/program-theory.md` (placement table, [THEORY-4]),
`docs/agent-context/runbooks/writing-plans.md`,
`docs/agent-context/runbooks/hardening-plans.md`, spec 10 in full for the
sections above, the completed plans
`2026-08-17-tui-command-entry-correction-plan.md`,
`2026-08-17-tui-multiline-whitespace-plan.md`, and the exemplar umbrella
`2026-08-14-review-findings-remediation-plan.md`. Review evidence:
headless Pilot reproductions for L1, P1–P3, K1, and the quit-route matrix;
DB byte inspection for D1; installed-wheel comparison for the version
timeline; three delegated verification passes over
session/domain/system, summon, and forms/layout/models.

## Spec Baseline

- `4b88b8d` — docs/specs/10-taut-tui.md, docs/specs/04-summon.md at plan
  authoring time. The K1 compose-key delta (Shift-Enter) exists in the
  authoring worktree as applied text over this baseline — spec text,
  binding, help/README/changelog, and passing tests together. It is
  restated in §Proposed Spec Delta so this plan's independent review
  covers it as reviewed text, and it lands atomically with Slice 3
  (strategy B). Slice 1's strategy-A promotion touches disjoint spec
  sentences, so promotion diffs remain unambiguous against this
  baseline; do not revert or partially stage the K1 delta.

After the spec-promotion slice, record the promotion baseline identifier
here:

- Promotion baseline: `588dc44` — the Slice 1 landing commit carrying the
  strategy-A deltas to `docs/specs/10-taut-tui.md` ([TUI-5.3],
  [TUI-7.1] ×3, [TUI-11.2], [TUI-11.3]) and `docs/specs/04-summon.md`
  ([SUM-10] bullet) with Related Plans backlinks. The K1 strategy-B
  Shift-Enter slice (spec text in [TUI-6.3]/[TUI-8.1]/[TUI-13.2] plus
  binding, help, README, changelog, tests) landed in the same commit
  because it shares the spec file and the baseline forbade partial
  staging; Slice 3 task 1 is thereby complete at `588dc44`.

## Proposed Spec Delta

Promotion strategy per file:

| Spec file | Strategy | Sections touched |
|-----------|----------|------------------|
| docs/specs/10-taut-tui.md | A — in-file text in the promotion slice; link claims land with each code slice | [TUI-5.3], [TUI-7.1], [TUI-11.2], [TUI-11.3] |
| docs/specs/10-taut-tui.md | B — atomic with Slice 3 (text already applied in worktree with its code and tests) | [TUI-8.1], [TUI-6.3], [TUI-13.2] (Shift-Enter) |
| docs/specs/04-summon.md | A | [SUM-10] |

### [TUI-5.3] — replace the sentence "Literal backslash sequences remain literal message content and are never decoded as layout."

> Message bodies additionally pass through a closed display-decode
> allowlist before sink escaping: the exact escape forms `\a`, `\b`, `\t`,
> `\n`, `\v`, `\f`, `\r`, `\xNN`, `\uNNNN`, and `\UNNNNNNNN` — the closed
> inverse of the terminal escape policy's output language under
> [TAUT-6.4], plus the numeric `\xNN`/`\uNNNN`/`\UNNNNNNNN` forms for the
> code points the policy writes as short escapes, so the short form and
> the numeric form of the same code point decode identically — decode to
> the characters they denote. Hex digits are lowercase (`0-9`, `a-f`),
> matching the policy's output exactly; a sequence containing uppercase
> hex remains literal text. Decoding runs before
> the terminal-escape sink, so any decoded control character other than LF
> and TAB is immediately re-escaped by the unchanged display policy; the
> decode introduces no new terminal injection surface. Decoded LF is an
> actual line break, decoded TAB is tab-stop whitespace, and decoded
> printable characters (including code points above U+FFFF) display as
> themselves. Sequences outside the allowlist, malformed hex or Unicode
> forms, and a trailing lone backslash remain literal text; `\\` is not in
> the allowlist and is not decoded, so no sequence exists for suppressing
> the decode. This decode is TUI-message-body display only: the stored
> record, search-hit previews, inline metadata such as author names, and
> every CLI surface keep exact stored bytes. Rationale: the CLI display
> dialect renders a real LF as the glyphs `\n` and never escapes
> backslashes, so the two variants are already indistinguishable in every
> record-stream surface; the TUI decodes toward the sender's intent
> instead of preserving a distinction no other display surface makes.

### [TUI-7.1] — browser paragraph: replace "The browser lists currently available native actions by stable human-facing groups, shows disabled reasons, and has visible selection and activation instructions."

> The browser lists currently available native actions by stable
> human-facing groups, shows disabled reasons, and has visible selection
> and activation instructions. It opens with the first enabled action row
> visibly highlighted. While the query field owns focus, Up and Down move
> the result highlight without moving text focus, and Enter activates
> exactly the highlighted enabled action — never an implicit first match.
> A query matching no actions shows an explicit empty state that names the
> `:` command line for commands taking arguments, and Enter with no
> highlighted action does nothing. When the query's first
> whitespace-delimited token exactly matches a root command in the merged
> shared syntax, the browser offers one "Run as command" row; activating
> it closes the browser and opens the command line prefilled with the
> query.

### [TUI-7.1] — promotion paragraph: append after "Matching never occurs against a still-growing prefix, so a shorter command such as `who` does not capture `whoami`."

> Promotion evaluates only direct user editing of the composer.
> Programmatic draft restoration — conversation switches, send-failure
> restores, and resize reflow — never promotes, regardless of draft
> content. When promotion opens the command line, on mount the command
> line reads the composer's current text — not the promotion-time
> snapshot — replaces its field with that text (colon stripped), and
> advances the originating draft identity, so keystrokes that raced into
> the composer after the promotion boundary are carried into the command
> field and no part of that text can survive as a hidden sendable chat
> draft.

### [TUI-7.1] — replace the paragraph beginning "Command completions are interactive, passive input aids." through "…restores focus to the command field."

> The command line is a vi-like, deliberately minimal surface: the `:`
> marker, one editable command field, and one feedback line, docked at
> the bottom of the screen. It owns keyboard focus while open, but it
> does not block the interface: the conversation view stays fully
> visible and continues rendering live deliveries behind it, and Escape
> closes it. It never presents a browsable completion list and never
> engages the grouped action browser. Command completions are inline,
> passive input aids: a dimmed shadow after the caret shows one
> available completion of the current input to a command path; Up and
> Down change which matching path the shadow shows; Tab accepts the
> shadow, inserting the completed command path followed by an
> argument-ready space with focus kept in the command field. When more
> than one path matches, the feedback line compactly names the available
> matches alongside the existing readiness and syntax feedback. Ordinary
> typing always edits the command field and never inserts or selects a
> completion. Selecting an action from the separate grouped
> native-action browser continues through its typed action binding and
> opens the existing native form when that action requires arguments.

### [TUI-11.2] — replace the sentence "Normal exit remains blocked while a worker is pending because an auto-renamed live member does not yet have an exact run handle."

> While a worker is pending, normal exit requires a decision rather than a
> silent block: the owned-run exit confirmation names the pending members
> and offers cancel-and-quit. Confirmed exit cancels every pending worker
> that has not yet entered the foreground controller run, and for workers
> already inside provider bootstrap waits a bounded interval for worker
> return exactly as for live owned runs; a worker that still does not
> return keeps the TUI open with the exact members and public errors
> visible. Cancellation targets the pending worker, never a member name,
> because an auto-renamed live member does not yet have an exact run
> handle. Cooperative in-bootstrap cancellation is a Summon contract
> enhancement ([SUM-7]) that this section adopts if and when Summon
> provides it; until then the bounded wait is the contract.

### [TUI-11.3] — append to the lease paragraph ending "none falls through to concurrent terminal ownership."

> If the suspend context exits by exception — including a
> KeyboardInterrupt delivered while the terminal is in cooked mode around
> attach or detach — the interruption is a fatal lease failure: the same
> UI handler records it, releases the worker, and exits the TUI through
> normal teardown without re-entering application mode and without the
> guarded-quit confirmation. The terminal is left restored for the shell.
> The TUI never continues running outside application mode.

### [SUM-10] — add to the "must state, at minimum" bullet list

> - **multiline sends**: a literal `\n` inside a quoted shell argument is
>   not a newline; multiline messages use stdin (`taut say <thread> -`)
>   or real newlines in the argument.

### [TUI-8.1] / [TUI-6.3] / [TUI-13.2] — Shift-Enter (strategy B, text as already applied in the authoring worktree)

[TUI-6.3]: "Plain Enter sends through `message.send`. Ctrl-Enter or
Shift-Enter inserts LF without sending; Ctrl-J is the legacy-terminal
newline fallback." [TUI-8.1]: "…Ctrl-Enter, Shift-Enter, or Ctrl-J inserts
a newline… Ctrl-Enter, Shift-Enter, and Ctrl-Tab require a terminal that
reports modified Enter/Tab distinctly; Ctrl-J and multiline paste are the
portable newline path…" [TUI-13.2]: the compose matrix row adds
Shift-Enter to the insertion enumeration.

### Related-plan backlink

Add this plan to `docs/specs/10-taut-tui.md` `## Related Plans` and to
`docs/specs/04-summon.md`'s related-plans list in the promotion slice.

## Context and Key Files

All paths relative to the repository root. Line references are at baseline
`4b88b8d`.

- `extensions/taut_tui/taut_tui/widgets.py` — display sinks.
  `escape_display_text` splits on LF and escapes each line via
  `escape_terminal_text`; `escape_message_body` (line 60) expands tabs then
  escapes; `TautComposer.BINDINGS` (line 171) owns Enter-submit and the
  newline/tab insertions. D1 and K1 edit here. The decode must be a new
  pure function applied only inside `escape_message_body`, before
  `expandtabs`, so decoded `\t` and literal TAB share the same tab-stop
  path and decoded controls hit the unchanged sink escaping.
- `taut/terminal.py` — `_write_escaped` (line 240) defines the encode
  language whose exact inverse D1 decodes. Read before writing the
  decoder; do not import private helpers from here — reimplement the
  closed inverse in `taut_tui` (the language is spec-frozen in the
  [TUI-5.3] delta).
- `extensions/taut_tui/taut_tui/app.py` (3,047 lines) — composition root.
  Relevant owners: `on_text_area_changed` (554) fires for both user and
  programmatic composer changes and drives promotion via
  `_composer_command_text` (841) → `action_open_command_line` (815);
  `_apply_conversation` (2721) assigns `composer.text` (2754) on every
  snapshot commit; `_render_messages` (2788) rebuilds the transcript and
  applies the scroll anchor; `_capture_scroll_anchor` (2825) is called
  only from `on_resize` (511) and `_apply_delivery` (2782);
  `_apply_navigation_result` (2551) re-renders the transcript at 2609;
  `on_resize` pops the too-small shield only when top-of-stack (533–536);
  `action_quit_tui` (893) is the single guarded quit owner;
  `on_terminal_lease_request` (729) and
  `on_terminal_attach_confirmation_request` (732) are the Summon
  marshalling handlers; `_run_command_dump` (1420) and
  `_complete_system_form` (2044) call `domain.dump` bare;
  `_watch_future` (2169) is the only sanctioned future→UI bridge.
- `extensions/taut_tui/taut_tui/screens.py` — `CommandPaletteScreen`
  (282): query `Input` + `TautOptionList`, no up/down bindings,
  `on_input_submitted` (317) activates the first enabled rendered entry;
  `CommandLineScreen` (418) already implements the correct pattern:
  priority `down`/`up` bindings (424–437), passive non-focusable
  completion list, explicit `_completion_selection_active` state. P1–P3
  copy this pattern, not a new one.
- `extensions/taut_tui/taut_tui/session.py` — single-worker executor plus
  watcher. `close()` blocks the calling thread in
  `future.result(timeout=7.0)` (184); `commit_returned_message` (114)
  returns the live snapshot on non-matching threads; `_open_reply_owned`
  (~255–309) claims reply unread before commit gates; worker→UI
  marshalling uses `call_from_thread` via the app callbacks (A2).
- `extensions/taut_tui/taut_tui/domain.py` — `read_messages`, `inbox`,
  `log_messages`, `list_threads` (200–228) lack the `EmptyResultError`
  handling that `search` (248) has; `start_direct_message` (135) formats
  `@{member}`.
- `extensions/taut_tui/taut_tui/system.py` — `submit_dump` (70) raises
  `OperationAlreadyRunning` synchronously on the UI thread.
- `extensions/taut_tui/taut_tui/summon.py` — `TerminalLeaseRequest.hold`
  (377–393) wraps `App.suspend()` and currently swallows `BaseException`
  into `request.error`; `quit_block_reason` (276), `has_pending_owned`
  (289), `stop_owned_and_wait` (292), `close` (341, `shutdown(wait=False)`
  over non-daemon threads); the confirmation coordinator and availability
  check around 469–505. Textual 8.2.8 `App.suspend` has no try/finally —
  `resume_application_mode()` runs only on clean exit; that fact shapes
  S1.
- `extensions/taut_summon/taut_summon/_persona.py` — briefing template
  (`taut say` examples at 84–85). D2 edits here; `taut_summon` controller
  files are read-only for this plan except the S2 cancellation seam
  decided in Slice 2.
- Tests to extend: `extensions/taut_tui/tests/test_tui_screens.py`,
  `test_tui_app.py`, `test_tui_chat.py`, `test_tui_summon.py`,
  `test_tui_textual_contract.py`, `test_tui_domain.py`,
  `test_tui_system.py`, `test_tui_launch.py` (read-only; T6 out of
  scope), and `extensions/taut_summon/tests/test_persona.py`.

Comprehension questions (write the answers in the execution log before
editing; a wrong answer blocks implementation until the owner text is
reread):

1. Q: Why must the D1 decode run before the existing sink escaping rather
   than after? Expected: decoded control characters other than LF/TAB must
   be re-escaped by the unchanged policy so the decode cannot open a
   terminal injection surface; running after would emit raw controls.
2. Q: Why does L1 happen even though `_clear_originating_command_draft`
   exists? Expected: the reopen is not driven by the originating-draft
   path at all — `_apply_conversation` programmatically assigns
   `composer.text`, TextArea posts `Changed`, and `on_text_area_changed`
   cannot distinguish that from typing, so `_composer_command_text`
   promotes again.
3. Q: Why can `stop_owned_and_wait` not cancel a pending run today?
   Expected: pending records hold no `SummonRunHandle` — `on_ready` fires
   only after the first live generation — and [TUI-11.2] forbids stopping
   by name because of auto-rename; there is no worker-targeted
   cancellation seam yet.
4. Q: Why is Enter-submit on the composer unaffected by the K1/D1 work?
   Expected: `TautComposer` binds `enter` to `action_submit` with
   `priority=True`, which Textual checks before the TextArea's own key
   handling; the newline aliases extend the separate `insert_newline`
   binding only.

## Invariants and Constraints

- The stored record is immutable input: no slice rewrites message bytes,
  normalizes at `say`/store time, or migrates historical data.
- The terminal-escape sink boundary is unchanged: every message body still
  passes through `escape_terminal_text`-backed sink escaping exactly once,
  after any decode. `EscapedDisplayText` provenance rules in `widgets.py`
  stay intact.
- The decode allowlist is closed and spec-frozen: exactly the inverse of
  `_write_escaped`'s output language. No locale-, config-, or
  markdown-style extensions.
- CLI rendering, search-hit previews, and inline metadata (author names,
  thread labels) do not decode.
- One quit owner: every quit route continues to funnel through
  `action_quit_tui`; the S2 change adds a decision path inside that owner,
  never a second quit path. The verified quit-route matrix (q, Ctrl-Q,
  Ctrl-C, Ctrl-D from normal and compose, `:q`, `:quit`, palette Quit)
  must still pass after every S-slice task.
- Terminal ownership invariant ([TUI-11.3]): at every exit from the lease
  handler — normal, timeout, or exception — either Textual owns the
  terminal in application mode or the app is exiting. No path may leave
  the process running in cooked mode.
- The palette remains an action browser: P3's handoff row opens the
  existing command line; the palette itself never parses or dispatches
  command syntax.
- Draft preservation rules ([TUI-9.2], [TUI-6.3]) hold: no fix may drop a
  user-typed draft except the explicitly spec'd originating-command-draft
  clear.
- `_watch_future` remains the only future→UI bridge for domain results;
  A1's fix must convert synchronous submission failures into the same
  presentation path, not add a parallel bridge.
- Auxiliary-failure priority ([TUI-12.1]): fixes must not let a
  presentation repair downgrade a successful domain mutation.
- No new dependencies; no Textual version change; no drive-by refactors of
  files this plan does not name.

## Rollout and Rollback

- Everything ships inside the `taut_tui` (and one `taut_summon` template
  string + optional cancellation seam) wheels; no storage format, DB, or
  wire change. Rollback for any landed slice is `git revert` of that
  slice; no slice depends on another slice's revert staying un-reverted,
  except that code slices depend on the promotion slice (reverting
  promotion requires reverting dependents first).
- D1 is display-only and independently revertible; reverting restores
  literal rendering with zero data impact.
- S2 changes quit behavior only when pending runs exist; the dialog path
  degrades to the current block if the cancellation seam is reverted.
- One-way doors: none. The only irreversible surface would be a release;
  releasing is out of scope for this plan.
- Post-deploy success signals: agent-authored multiline messages in a real
  workspace render as paragraphs in the TUI while `taut read` output is
  unchanged; the palette empty state appears for argumentful queries; no
  recurrence of the spontaneous command-line modal during conversation
  switching; Ctrl-C during a provider attach either cancels into a visible
  lease failure or exits, never a dead screen.

## Dependency-Ordered Implementation Slices

Slices land in order; within a slice, tasks are ordered. Every task is
red-green unless it names its substitute proof. Stop-and-re-evaluate gates
are binding.

### Slice 1: independent review and spec promotion

1. Independent review of this plan and every delta above (see
   §Independent Review Loop). Record findings and dispositions in the
   review log.
2. Owner decisions to confirm explicitly: S2 (pending-run cancel-and-quit
   plus the Summon cancellation seam) and the P3 handoff row. D1 is
   already owner-directed (2026-08-18). If a decision is declined, revise
   the register and deltas before promotion.
3. Apply the strategy-A deltas ([TUI-5.3], both [TUI-7.1] paragraphs,
   [TUI-11.2], [TUI-11.3], [SUM-10]) with no implementation-link claims,
   plus the Related Plans backlinks. Do not apply the strategy-B
   Shift-Enter text here; it lands with Slice 3.
4. Add this plan to the `docs/plans/README.md` status index (status
   `active` once promotion lands). Gates: `bin/check-doc-paths`,
   `bin/check-plan-status-index`. Record the promotion baseline
   identifier in §Spec Baseline.

### Slice 2: Summon terminal-ownership and quit lifecycle (S1–S6)

Read first: [TUI-11.2], [TUI-11.3], `summon.py` in full, Textual 8.2.8
`App.suspend`/`_driver` resume paths, and `taut_summon`
`controller.py`/`_driver.py` bootstrap phases (for the S2 seam).

1. S1 (owner-directed 2026-08-18: exit completely): make
   `TerminalLeaseRequest.hold` exception-safe by treating any exception
   escaping the suspend body — KeyboardInterrupt included — as a fatal
   lease failure: record it on the request, release the worker, end the
   lease bookkeeping, and call `app.exit()` so the TUI shuts down
   through normal teardown without re-entering application mode and
   without the guarded-quit confirmation. Do not attempt to resume
   application mode (no private Textual API is used). Verify the
   process leaves a restored, usable terminal: exiting from the
   suspended state must not re-enter application mode on the way down.
   Tests: extend `test_tui_summon.py` with a fake lease whose wait
   raises; assert the app exits (run_test context completes with
   `app.return_code` set / `is_running` false), the failure is recorded
   on the request, and no summon worker is left unreleased. Do not mock
   `App.suspend` itself — drive the real context manager in `run_test`.
   Stop-gate: if exiting from inside the suspended handler leaves
   Textual attempting to re-enter application mode during teardown
   (garbling the terminal), stop and record the constraint before
   choosing a workaround.
2. S2: pending-run quit. The promoted [TUI-11.2] text (as revised after
   independent review) makes the bounded-wait fallback the contract:
   confirmed cancel-and-quit (a) cancels workers that have not yet
   entered `run_foreground` via a per-record cancel event consumed in
   the `run()` wrapper in `taut_tui/summon.py`, and (b) waits a bounded
   interval for workers already inside bootstrap, keeping the TUI open
   (members and errors visible) when a worker does not return.
   Investigate `taut_summon/controller.py` for an in-bootstrap
   cancellation seam anyway; if one exists, use it and record that in
   the implementation log — the spec text already covers both shapes.
   If none exists, record the [SUM-7] enhancement pointer in the
   deviation log's Spec proposal column. Change `close()` to a bounded
   join with explicit abandonment reporting rather than an unbounded
   interpreter-exit hang.
   Tests: `test_tui_summon.py` — quit during pending offers the dialog;
   confirmed cancel-and-quit exits when the worker returns (pre-start
   cancel path); worker non-return keeps the TUI open with visible
   members (bounded-wait path).
   Stop-gate: if the bounded wait would abandon a live provider child
   holding the terminal lease, stop — that is a [SUM-7] contract
   conversation, not a local decision.
3. S3: retain the pushed attach `ConfirmationScreen` and dismiss it when
   the request resolves without the user. S4: guard
   `on_terminal_lease_request` with the same `_shutting_down`/staleness
   checks as the confirmation handler (refuse without suspending). S5: at
   confirm-time owner contention, resolve as unavailable-decline instead
   of raising. S6: make summon status transitions set `_operation_state`
   only when they own the current state (guard on the value they set).
   Tests: worker-cancelled confirmation dismisses the modal; stale lease
   request never suspends; contention declines without DriverError.
4. Gate: full `test_tui_summon.py` plus the quit-route matrix
   (`test_tui_app.py -k quit`). Stop if any task introduces a second quit
   path or touches Summon signal handling.

### Slice 3: compose keys and display decode (K1, D1, D2)

1. K1 (already implemented in the authoring worktree; land it here,
   strategy B): binding `ctrl+enter,shift+enter,ctrl+j` in
   `widgets.py`; help text in `app.py`; README; [TUI-6.3]/[TUI-8.1]/
   [TUI-13.2] text; changelog entry; extended
   `test_tui_textual_contract.py::test_composer_modified_keys_insert_structure_without_submitting`
   and the help assertion in `test_tui_app.py`. Evidence at authoring:
   RED reproduced (shift+enter inserted nothing), GREEN after the
   binding; contract suite 12/12; help/multiline/compose selection of
   `test_tui_app.py` 14/14. Land by explicit file-list staging; rerun
   both suites at landing.
2. D1: implement `decode_message_escapes` (new pure function in
   `widgets.py`) as the exact closed inverse of
   `taut/terminal.py::_write_escaped`'s language; apply it only in
   `escape_message_body`, before `expandtabs`. Malformed forms and `\\`
   pass through untouched. Red-green in
   `test_tui_textual_contract.py`: unit rows for each allowlisted form,
   malformed forms, trailing backslash, `\x1b` round-tripping back to the
   escaped glyphs through the sink, astral-plane `\U0001F600` displaying
   as the emoji; transcript-level proof in `test_tui_chat.py` that a
   stored literal `\n\n` body renders as a paragraph break while the
   search screen preview for the same message keeps the literal glyphs.
   Do not mock the escape policy — drive the real
   `escape_terminal_text` path.
   Stop-gate: if implementing the decoder tempts you to import private
   helpers from `taut/terminal.py` or to extend the allowlist beyond the
   spec-frozen inverse, stop.
3. D2: add the multiline-sends sentence to the `_persona.py` briefing
   (matching the promoted [SUM-10] bullet); extend
   `extensions/taut_summon/tests/test_persona.py` to assert it.
4. Gate: `test_tui_textual_contract.py`, `test_tui_chat.py`,
   `test_persona.py` green; `bin/check-doc-paths`.

### Slice 4: command surfaces (P1–P4, L1, L2)

Read first: [TUI-7.1] as promoted; `CommandLineScreen`'s
priority-binding/selection pattern (`screens.py:418–530`) — P1/P2 copy
this pattern into `CommandPaletteScreen`.

1. P1+P2: priority Up/Down bindings on `CommandPaletteScreen` moving the
   highlight across enabled rows (skip disabled and group-header rows);
   open with the first enabled row highlighted; `on_input_submitted`
   activates exactly the highlighted entry and does nothing when none is
   highlighted. Fix the existing
   `test_command_palette_filters_and_returns_the_same_action_id` so its
   `down`+`enter` actually exercises the new path (today it passes for
   the wrong reason), and add: empty-query bare Enter is a no-op
   (regression for the "Initialize workspace" hazard); Down/Down/Enter
   from the query input activates the second enabled entry.
2. P3: no-match empty state row (disabled, names the `:` command line);
   "Run as command" handoff row when the first query token is an exact
   known root in the merged syntax — activation dismisses the palette
   and calls `action_open_command_line(initial_text=<query>)`. The
   palette gains no parser: the handoff decision tests exact root-token
   membership against the same `command_nodes` set the composer
   promotion uses, evaluated independently of (and before) the fuzzy
   action matcher, which continues to govern only which action rows are
   listed.
3. P4: rename the status-bar affordance and help wording so the browser
   ("Actions"/"Commands browser") and the `:` command line are named
   distinctly; keep gesture pairs intact. Update the help assertion
   test.
4. L1: distinguish programmatic composer writes from user edits (e.g. a
   guard flag set around the `composer.text` assignments in
   `_apply_conversation` and `_clear_originating_command_draft`, checked
   in `on_text_area_changed` before promotion; draft bookkeeping still
   runs). Red-green: reproduce the recorded scenario — promote, Escape,
   Escape, switch conversation, switch back — and assert no
   `CommandLineScreen` appears while the draft text is restored intact.
5. L2: on `CommandLineScreen` mount from promotion, read the composer's
   current text (not the promotion-time snapshot), replace the command
   field with it (colon stripped), and advance the originating-draft
   identity so the racing suffix cannot survive as a sendable chat
   draft. Test: simulate the race by mutating the composer between
   `action_open_command_line` and mount.
6. L3 (owner-directed two-surface contract): rebuild `CommandLineScreen`
   as the vi-like bottom line the promoted [TUI-7.1] text describes.
   Presentation: bottom-docked single-line surface (keep the
   `ModalScreen` mechanism for focus ownership if convenient, but with
   bottom alignment and a fully transparent, non-dimming backdrop so
   the conversation view stays visible); live deliveries must keep
   rendering behind it — the existing `_query_base` base-screen path
   already updates base widgets under a modal, so assert it rather than
   rebuild it. Completion: delete `_CommandCompletionList` and its
   rows; implement the ghost shadow with Textual's `Input`
   `suggester` API (`textual.suggester.Suggester` subclass over
   `_command_completions`, which stays); rebind Up/Down from
   list-selection to shadow-match cycling; Tab accepts the shown shadow
   (replacing `action_complete`'s first-match insert); feedback line
   compactly names remaining matches. Tests: rewrite
   `test_command_line_tab_completion_keeps_argument_input_active` and
   `test_command_line_keyboard_selection_keeps_argument_input_active`
   against shadow semantics; retire
   `test_command_line_mouse_activation_keeps_argument_input_active`
   (no rows to click — record in the implementation log); add a
   liveness test: with the command line open, a delivered message
   appears in the transcript behind it.
   Stop-gate: if the `suggester` API cannot render the shadow while a
   custom feedback line is present, stop and choose between a manual
   ghost-render or keeping a single-line hint — do not reintroduce a
   completion list.
6. Gate: `test_tui_screens.py`, `test_tui_app.py` green. Stop if the
   palette starts parsing command syntax or the promotion guard grows
   beyond one flag plus its two write sites.

### Slice 5: transcript state integrity (T1–T5)

1. T1: in `_render_messages`, restore the history anchor without routing
   through `highlighted` mutation of selection — preserve
   `selected_message_id` across re-renders (set the highlight to the
   selected row when present; scroll restoration must not rewrite
   selection). Red-green: scroll up, select a non-anchor message, deliver
   a new message, assert selection unchanged and reply targets the
   selected message.
2. T2: call `_capture_scroll_anchor` at the top of every transcript
   re-render path that does not already capture (`_apply_navigation_result`
   before its re-render; `_move_surface`/`_cycle_surface` refreshes).
   Test: scrolled-up transcript plus a notification delivery keeps the
   scroll position.
3. T3: make too-small shield removal stack-aware: track the pushed shield
   instance and remove it from the screen stack wherever it sits when
   leaving TOO_SMALL; never push a second shield while one is tracked.
   Test: shield + covering modal + grow terminal → shield gone after the
   modal resolves.
4. T4: route the vanished-context error paths reachable from an open
   `NativeFormScreen` (`MESSAGE_REPLY`/`MESSAGE_REACT` selection loss,
   rename target loss) through `screen.show_domain_error`/`resume`
   instead of `_show_error`. Test: submit a reply form after clearing the
   selection state; the form re-enables and shows the error inline.
5. T5: on opening a conversation while an `"__unselected__"` draft holds
   nonblank text, carry that draft into the newly opened conversation's
   composer (and drop the placeholder key). Test: type with no target,
   open a conversation, text survives.
6. Gate: `test_tui_app.py`, `test_tui_chat.py`, `test_tui_resize.py`
   green.

### Slice 6: async, session, and domain correctness (A1–A7)

1. A1: wrap the synchronous submission window for dumps: both
   `_run_command_dump` and `_complete_system_form` route
   `OperationAlreadyRunning`/`ReplacementConfirmationRequired` into the
   attached recoverable-error presentation (form path re-enables the
   form). Test in `test_tui_system.py`/`test_tui_app.py`: overlapping
   dump requests never escape a handler.
2. A2: make the worker→UI marshalling teardown-safe: bound the
   `call_from_thread` waits (timeout with shutdown re-check) or gate them
   on a teardown event so `session.close()` cannot deadlock against a
   parked worker; eliminate the spurious "TUI cleanup failed:
   TimeoutError" on quit. Test: simulated parked commit during close
   completes without the 7s stall (event-driven, no sleeps — follow the
   repo's event-based test pattern from the 2026-08-17 anchor plans).
   Stop-gate: if the fix requires changing Textual's `call_from_thread`
   semantics rather than our wait discipline, stop and re-plan.
3. A3: catch `EmptyResultError` in `read_messages`, `inbox`,
   `log_messages`, and `list_threads(direct_messages=True)` exactly as
   `domain.search` does, returning the empty projection the renderer
   already presents as "No results". Tests in `test_tui_domain.py`.
4. A4: re-check the intent token inside `_apply_conversation` (mirror
   `_apply_optional_conversation`). A5: return `None` from
   `commit_returned_message` for non-matching threads and make both
   `_apply_*_action_result` callers tolerate it (they already branch on
   `None`). A6: move the reply-thread unread claim after commit
   acceptance in `_open_reply_owned`. A7: normalize a single leading `@`
   in `start_direct_message`. Each with a focused red-green test in
   `test_tui_domain.py`/`test_tui_chat.py`.
5. Gate: full `extensions/taut_tui/tests` sqlite lane green.

### Slice 7: traceability reconciliation and closeout

1. Add the implementation-link claims for the promoted sections and
   reciprocal code citations (strategy A completion); update
   `docs/implementation/12-taut-tui.md` (display decode, palette
   semantics, promotion guard, lease exception safety, pending-quit) and
   the spec's implementation snapshot notes.
2. Close the deviation log (no `pending` rows), record lessons in
   `docs/lessons.md` if any slice exposed a durable correction, update
   the status index row to `completed`, and rerun `bin/check-doc-paths`,
   `bin/check-plan-status-index`, `bin/coalesce-check`.
3. Final independent review of the completed work (see §Independent
   Review Loop).

## Testing Plan

- Harness: real `TautApp.run_test` Pilot flows against real SQLite
  workspaces (`TautClient.init` + real `say`/`join`), per [TUI-13.1]. The
  existing suites named per slice are the homes; no new test files unless
  a slice's home file exceeds review size.
- What must stay real: the terminal-escape policy and display sinks
  (D1), the Textual screen stack and focus system (P/L/T slices), the
  session executor and watcher threads (A2, A4–A6), `App.suspend`'s real
  context manager (S1), and the SQLite-backed client. The only sanctioned
  fakes are the existing summon controller/lease fakes in
  `test_tui_summon.py` and simulated worker timing for race tests.
- Contract bias: every fix lands with a test that fails at baseline and
  asserts externally visible behavior (rendered transcript text, screen
  stack contents, selection identity, quit outcome, message bytes on the
  wire), not internal flags.
- The quit-route matrix and the [TUI-13.2] compose matrix are regression
  floors: rerun after Slices 2–4.

## Verification Commands

Per-slice: the suites named in each slice via
`.venv/bin/python -m pytest extensions/taut_tui/tests/<file> -q` (and
`extensions/taut_summon/tests/test_persona.py` for D2).

Final gates before completion claim:

```bash
.venv/bin/python -m pytest extensions/taut_tui/tests -q
.venv/bin/python -m pytest extensions/taut_summon/tests -q
ruff check extensions/taut_tui extensions/taut_summon
bin/check-doc-paths
bin/check-plan-status-index
bin/coalesce-check
```

plus the hosted TUI CI lanes on the landing branch (the repo's existing
`test-tui-extension.yml` matrix) before any completion claim, per the
2026-08-17 precedents.

## Out of Scope

- T6 (fatal exit status 0) — codified [TUI-12.1] decision; revisit only
  by explicit owner direction with its own spec delta.
- Any decode outside TUI message bodies: CLI rendering, search previews,
  metadata, markdown or styling of message content.
- Write-side normalization of message text in core or `taut say`.
- Redesigning the palette into a command executor, merging it with the
  command line, or removing either surface.
- `taut_summon` controller/driver refactors beyond the S2 cancellation
  seam decision and the D2 template sentence.
- Releasing (0.9.3) — a follow-on routine release per [DOM-15] once this
  plan completes.
- The A2 executor architecture (single-worker model) — only the wait
  discipline changes.

## Deviation Log

| Spec ref | Planned behavior | Actual behavior | Rationale | Spec proposal |
|----------|------------------|-----------------|-----------|---------------|
| [TUI-11.2] / [SUM-7] | Slice 2 investigates an in-bootstrap cancellation seam and uses it if present | Seam confirmed absent (`taut_summon/controller.py:189` `run_foreground` → `run_driver`, no cancel parameter); implemented pre-start cancel event plus bounded wait only | No Summon-side seam exists; the promoted [TUI-11.2] text already conditions adoption on Summon providing one | Closed — no spec edit required now; the [SUM-7] cooperative pre-ready cancellation enhancement is future work under its own plan |

## Independent Review Log

Reviewer instructions: review this plan and its `## Proposed Spec Delta`
before promotion (Slice 1) and again over the completed diff (Slice 7).
Prefer a different agent family from the authoring agent (Claude authored
this plan; Codex or Grok CLI are available in the owner's environment) —
if unavailable, use a fresh Claude session with no shared context. Read:
this plan, [TUI-5.3]/[TUI-7.1]/[TUI-8.1]/[TUI-11.2]/[TUI-11.3]/[SUM-10]
at the baseline, `widgets.py`, `screens.py`, `summon.py`, and the app.py
regions named in §Context. Stance: look for errors, bad ideas, latent
ambiguities, and performative overengineering — recommending removal is as
valuable as recommending additions; answer explicitly whether you could
implement each slice confidently and correctly against the promoted
delta. Findings and dispositions are recorded here; an "could not
implement confidently" answer is a blocker.

### 2026-08-18 — plan review, Kimi (kimi-code/k3, read-only consult)

Reviewer: Kimi Code CLI 0.36.1, non-Claude family, no shared context;
prompted with the reviewer instructions above. Grok was attempted first
and is blocked (402, usage balance exhausted). Verdicts: slices 1, 3–7
implementable confidently; slice 2 "No" pending two blockers. Author
dispositions:

| # | Severity | Finding | Disposition |
|---|----------|---------|-------------|
| 1 | P1 | [TUI-11.2] delta assumed a pre-ready cancellation seam `taut_summon` does not have | Accepted — delta rewritten to make pre-start cancel + bounded wait the contract, with in-bootstrap cooperative cancellation adopted if/when [SUM-7] provides it; Slice 2 task 2 aligned |
| 2 | P1 | S1 recovery relies on private `App._driver.resume_application_mode()` with no stated fallback | Superseded (2026-08-18, historical — not implementation authority): the owner directed that Ctrl-C during a lease exits the TUI completely, which removes the resume path and the private-API dependency altogether; see the decision record below |
| 3 | P2 | [TUI-5.3] hex case unspecified | Accepted — lowercase-only rule added to the delta |
| 4 | P2 | "precisely the inverse" inaccurate (`\x07` decodes but is never emitted) | Accepted — reworded to "closed inverse plus numeric forms; short and numeric forms decode identically" |
| 5 | P2 | L2 reconciliation ambiguous (snapshot vs current text) | Accepted — delta and Slice 4 task 5 now say: composer's current text at mount, colon stripped, draft identity advanced |
| 6 | P2 | K1 exists in the worktree ahead of promotion; baseline confusing | Accepted — §Spec Baseline clarified (reviewed-as-part-of-this-plan, disjoint from strategy-A sentences, do not revert/partially stage) |
| 7 | P2 | P3 handoff must test exact root membership independent of the fuzzy matcher | Accepted — Slice 4 task 2 wording tightened |

Slice 2's "No" is resolved by dispositions 1–2; re-review of Slice 2 is
not required by the reviewer's own framing (the blockers were the two
assumptions, both now removed from the promoted text).

### 2026-08-18 — owner decisions (recorded)

1. **S2 — approved as proposed.** The revised [TUI-11.2] cancel-and-quit
   contract (pre-start cancel + bounded wait; cooperative in-bootstrap
   cancellation adopted if/when [SUM-7] provides it) is the contract.
2. **S1 — decided differently: Ctrl-C exits completely.** Exception exit
   from the suspend context is a fatal lease failure and exits the TUI
   through normal teardown; no application-mode resume, no private
   Textual API. [TUI-11.3] delta and Slice 2 task 1 rewritten
   accordingly; review finding 2 is thereby superseded.
3. **P3 — approved, within a two-surface direction.** The owner's
   articulated contract: two independent command-entry surfaces. (a) A
   vi-like `:` line — bottom-docked, owns focus without blocking the
   live view, Esc quits, Tab completion with a ghost "shadow" of the
   available command, never engaging the browser (new register row L3;
   new [TUI-7.1] completions-paragraph delta; Slice 4 task 6). (b) The
   mouse/Tab action browser — filtering stays, plus the "Run as
   command" handoff for typed full commands (P3) and the existing typed
   forms as the argument-entry interface for selected actions.

## Implementation Log

### Slice 1 — 2026-08-18

Landed at `588dc44` (promotion + plan + index + K1 strategy-B slice; see
§Spec Baseline for why K1 rode along). Gates: check-plan-status-index,
check-doc-paths, K1 test suites green.

### Slice 2 — 2026-08-18 — comprehension answers (pre-edit gate)

1. Decode-before-sink: decoded control characters other than LF/TAB must
   be re-escaped by the unchanged sink policy so the decode cannot open a
   terminal injection surface; decoding after the sink would emit raw
   controls to the terminal. (Matches expected answer.)
2. L1 reopen: `_apply_conversation` assigns `composer.text`
   programmatically; TextArea posts `Changed`; `on_text_area_changed`
   cannot distinguish that from typing and re-promotes — the
   originating-draft clear path is not involved. (Matches.)
3. Pending runs cannot be stopped: pending records carry no
   `SummonRunHandle` (`on_ready` fires only after the first live
   generation), and [TUI-11.2] forbids stopping by name because of
   auto-rename; before this slice there is no worker-targeted
   cancellation seam. (Matches.)
4. Enter-submit unaffected: `TautComposer` binds `enter` to
   `action_submit` with `priority=True`, checked before TextArea key
   handling; the newline aliases extend only the separate
   `insert_newline` binding. (Matches.)

### Slice 2 — 2026-08-18 — evidence

- S1: `TerminalLeaseRequest.hold` exits the app on any exception from
  the suspend scope (`suppress`-guarded `app.exit()`); no
  application-mode resume, no private Textual API. The app-level proof
  drives the real `App.suspend` in `run_test`, where the headless
  driver raises `SuspendNotSupported` through the same `BaseException`
  branch a KeyboardInterrupt takes; the unit proof injects a raising
  release-wait through the file's established `_LeaseApp` fake. (The
  plan sentence "drive the real context manager" is satisfied by the
  app-level test; real suspension cannot occur headless.)
- S2: pending-run quit — `action_quit_tui` no longer dead-ends on
  `has_pending_owned`; the owned-exit confirmation covers pending runs;
  `_OwnedRecord.cancel` + `_run_owned` pre-start check implement the
  pre-start cancel; `stop_owned_and_wait` cancels handle-less records
  and bounded-waits the rest; foreground workers moved from the
  non-daemon `ThreadPoolExecutor` to daemon threads with manual Future
  semantics (`_submit_foreground`) so a hung bootstrap cannot pin
  interpreter exit; `close()` also sets cancel events. Seam
  investigation recorded in the Deviation Log.
- S3: attach-confirmation requests carry an `on_resolved` callback; the
  app handler retains the screen and dismisses it via
  `call_later` when the worker resolves the request without the user
  (dismissal when the stale screen is current; a buried screen's later
  dismissal flows through its normal callback, which is latched-no-op).
- S4: `on_terminal_lease_request` refuses stale (`release` already set)
  or shutting-down requests without suspending.
- S5: confirm-time owner contention returns a graceful decline instead
  of raising; the exclusivity test updated to the promoted contract.
- S6: `_apply_summon_ready`/`_apply_summon_return` mutate
  `_operation_state` only when it holds an idle or summon-owned value.
- Tests: 8 new tests in `test_tui_summon.py` (7 red at baseline; the
  stale-lease guard test pins post-S1 behavior); suite 27/27; quit-route
  matrix `test_tui_app.py -k quit` 30/30; full `test_tui_app.py` 97/97;
  ruff clean (C901 resolved by extracting `_run_owned`). Landed at
  `0261a62`.

### Slice 3 — 2026-08-18 — evidence

- K1 landed with Slice 1 at `588dc44` (recorded there).
- D1: `decode_message_escapes` in `widgets.py` — regex over exactly the
  [TUI-5.3] language (short escapes + lowercase-hex numeric forms;
  surrogate and >U+10FFFF code points treated as malformed literals);
  applied only in `escape_message_body`, before `expandtabs`, so decoded
  controls re-escape through the unchanged sink. Red-green: allowlist
  unit matrix + non-decoding boundary proof in
  `test_tui_textual_contract.py`; transcript-level proof in
  `test_tui_chat.py` (stored literal `\n\n` renders as a paragraph
  break beside a real-newline message). One prior-contract assertion
  (`test_message_body_tabs_expand_before_escape_notation`, written
  against the superseded [TUI-5.3] sentence) updated to the promoted
  contract with a dated comment.
- D2: multiline-sends guidance added to the mouth section of the
  `_persona.py` briefing (stdin path named; literal backslash-n called
  out); `REQUIRED_PERSONA_CONCEPTS` extended red-green in
  `test_persona.py`; module docstring aligned with the promoted
  [SUM-10] bullet.
- Gates: contract + chat + persona suites green; ruff clean;
  check-doc-paths OK; changelog entry added. Landed at `1537fb6`.

### Slice 4 — 2026-08-18 — evidence

- P1+P2: `CommandPaletteScreen` gains priority Up/Down bindings cycling
  the highlight across activatable rows, opens (and re-renders) with the
  first activatable row highlighted, and Enter activates exactly the
  highlighted row (inert when none). The prior filter test now
  exercises the real path.
- P3: no-match disabled empty-state row naming the `:` command line;
  "Run as command" handoff row when the first query token is an exact
  member of the app-supplied `command_roots` (evaluated independently
  of the fuzzy action matcher); dismissal result type extended with
  `PaletteCommandHandoff`, completed by `_complete_palette` into
  `action_open_command_line(initial_text=query)`.
- P4: browser titled "Actions", status-bar affordance relabeled, help
  text names the command line and action browser distinctly.
- L1: `_suppress_promotion_edits` counter with `_set_composer_text`
  wrapping all three programmatic composer restores; reproduced
  spontaneous-reopen scenario now proven inert at the app level.
- L2: `CommandLineScreen(reconcile=...)` reads the composer's current
  draft at mount via `TautApp._reconcile_promotion`, which also
  advances `_pending_command_origin` so the raced draft clears on
  successful submission.
- L3: `CommandLineScreen` rebuilt as a bottom-docked, transparent,
  non-dimming bar (no title/instructions/completion list; `:` marker +
  field + one feedback line). Inline ghost shadow via a
  `textual.suggester.Suggester` subclass computing matches from the
  live value; Up/Down cycle the match (ghost refresh pins the private
  `Input._suggestion` reactive, documented, degradation = stale ghost
  until next keystroke); Tab accepts with an argument-ready space;
  feedback line compactly names multiple matches. Liveness proven:
  deliveries keep rendering behind the open command line.
- Old-contract tests updated with dated comments: keyboard-selection →
  shadow cycle + Tab; clickable-completion and passive-list app tests →
  shadow/no-list equivalents; mouse row-click screen test retired (no
  rows — recorded here); transcript literal-`\n\t` row expectation
  moved to the promoted decode contract; help handler assertion updated
  to the new wording.
- Gates: `test_tui_screens` 21/21, `test_tui_app` full green,
  `test_tui_action_handlers` 37/37, action routes + command bindings
  green, ruff clean. Landed at `51704c5`.

### Slice 5 — 2026-08-18 — evidence

- T1: `_render_messages` no longer rewrites the highlight to the anchor
  row; scroll restoration is position-only, so re-renders preserve
  `selected_message_id`. Companion: search-result open now sets
  `selected_message_id = hit.ts` explicitly (the jumped-to hit is the
  selection), keeping the 2026-08-17 search-anchor highlight contract.
- T2: `_capture_scroll_anchor` runs before the navigation-refresh
  re-render and at the top of `_move_surface`/`_cycle_surface`
  (leaving-capture, guarded to run only while the conversation surface
  is visible). Task-detail deviation recorded: the plan sketched
  capture at the surface-switch re-render site (arrival), but arrival
  capture reads the hidden transcript's stale geometry and destroyed
  the anchor (caught by the 2026-08-17 width-reflow test); departure
  capture is the correct timing. Behavior proof: a mention-driven
  navigation refresh no longer yanks a scrolled-up transcript (test
  measures watcher-delivery quiescence, since deduped catch-up
  redeliveries re-render without changing the row count).
- T3: the too-small shield is tracked; leaving TOO_SMALL dismisses it
  when top-of-stack, and a shield resumed under a stale state dismisses
  itself (`on_screen_resume`), so a covering modal can no longer strand
  it; double-push prevented.
- T4: vanished-context error paths reachable from an open
  `NativeFormScreen` (reply/react selection loss, set-topic/rename
  target loss) route through `screen.show_domain_error`, keeping the
  form submittable and cancellable.
- T5: a nonblank `__unselected__` composer draft carries into the first
  opened conversation instead of being silently dropped.
- Observed during this slice and deferred to Slice 6 (A2 family):
  watcher deliveries still in flight during app teardown can fail
  `#transcript` queries three times and poison-advance a message; the
  teardown guard lands with A2.
- Gates: ruff clean; `test_tui_resize` + `test_tui_chat` +
  `test_tui_app` 129/129. Landed at `84cc74e`.

### Slice 6 — 2026-08-18 — evidence

- A1: `_submit_dump` wraps the synchronous submission window for both
  the command and form dump paths; `OperationAlreadyRunning` and the
  TOCTOU `ReplacementConfirmationRequired` render as attached
  recoverable errors (form path re-enables the form) instead of
  escaping the Textual handler.
- A2: `TuiSession.close(wait=False)` for UI-loop callers — on_unmount
  no longer blocks the loop a parked worker needs, eliminating the 7s
  quit stall and the spurious "TUI cleanup failed: TimeoutError" toast;
  cleanup still runs on the executor thread, which drains before
  interpreter exit (a parked marshal unblocks with RuntimeError once
  the loop exits and is swallowed by the existing worker guards).
  Companion teardown guard `_presentation_ready` (mirroring
  `_watch_future`'s attachment probe) now gates `_apply_delivery` and
  `_apply_conversation`, closing the Slice 5-observed
  poison-on-teardown path (three NoMatches failures advancing past a
  live message).
- A3: `read`, `inbox`, `log`, and `list --dms` convert
  `EmptyResultError` into empty collections via `_empty_ok`, taking the
  renderer's existing "No results" path.
- A4: `_apply_conversation` re-checks the intent token on the loop
  side; a superseded snapshot returns False without flashing stale
  state.
- A5: `commit_returned_message` returns `None` for threads unrelated to
  the open conversation, ending the needless full re-render/composer
  reset.
- A6: reply-thread unread is claimed only after the open's first commit
  is accepted, then merged and re-committed; a rejected (superseded)
  open no longer silently marks never-displayed replies read.
- A7: `start_direct_message` normalizes a single leading `@`.
- Tests: eight new red-green tests (five in `test_tui_domain.py`, three
  in `test_tui_app.py`; the teardown-guard test also pins
  `_apply_conversation` against a detached screen). One prior stub
  updated to the new `close(wait=...)` contract.
- Gates: ruff clean; full `extensions/taut_tui/tests` lane (minus the
  wheel-building packaging suite, exercised in CI) green. Landed at
  `8b76352`.

### Slice 7 — 2026-08-18 — traceability closeout and final review

- `docs/implementation/12-taut-tui.md` updated: display decode ordering
  and rationale, the two-surface command contract (vi bottom line +
  action browser), promotion source discrimination and mount
  reconciliation, lease exception exit, pending-run cancel-and-quit,
  and the confirmation/lease guard changes; Related Plans backlink
  added. Two durable lessons recorded in `docs/lessons.md` (Textual
  events carry no input-source discrimination / capture-on-departure;
  teardown attachment guards and `close(wait=False)` for loop callers).
- Deviation Log closed (single row, resolved — no `pending`).
- Final independent review: Kimi (kimi-code/k3), completed-work pass
  over `588dc44..8b76352` plus this closeout. Verdict: implementation
  faithful to the promoted deltas; tests pin the promoted contracts; no
  escaping, lifecycle, or teardown regressions found. Findings and
  dispositions: (P1) completion claim must land with the status-index
  flip and a Slice 7 log entry — this entry and the closeout commit are
  that disposition; the index flips to `completed` only when the hosted
  TUI lanes pass, per the Completion Gate. (P2) palette instruction
  said "Click run" while rows activate on double-click per [TUI-8.2] —
  accepted, instruction now reads "Double-click run".
- Local final gates: full `extensions/taut_tui/tests` 409 passed (Kimi
  rerun, includes persona suite), ruff clean, `check-doc-paths`,
  `check-plan-status-index`, `coalesce-check` all OK.
- Outstanding for the completion claim: hosted TUI CI lanes on the
  landing branch. Land instruction: push main, let
  `test-tui-extension.yml` run, then flip the status-index row and this
  header to `completed` in the same change as the claim.
- Release-precheck correction (2026-08-18): the repository-wide raw Ruff
  inventory exposed six Slice 2/6 `BLE001` directives that focused lint had
  accepted but the exact registry had not reconciled. Independent suppression
  review rejected score-only extraction, removed a main-thread test catch and
  a redundant nested callback catch, and retained four narrow ownership
  boundaries. The same review exposed the direct attach-resolution observer
  assignment race; lock-owned `set_on_resolved` registration now handles both
  register-before-resolve and resolve-before-register orderings. New firing
  proofs cover arbitrary dump-submission failure, callback and deferred-dismiss
  failure, and a real daemon worker retaining `KeyboardInterrupt` on its
  returned Future. [TUI-11.2] was corrected from its stale non-daemon wording.

## Completion Gate

This plan is complete only when: every register row's required outcome has
a passing test or recorded owner decision; the deviation log has no
`pending` rows; the final verification commands and hosted TUI lanes are
green from the landing identifier; `docs/implementation/12-taut-tui.md`
and the spec implementation notes reflect the changes; the status index
row reads `completed` in the same change as the claim; and the final
independent review's findings are incorporated or explicitly answered.
