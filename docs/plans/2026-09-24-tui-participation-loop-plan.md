# TUI Participation Loop Plan

Status: completed — implementation, verification, documentation, and the
independent completed-work review passed on 2026-09-24.

Class: 5 (spec-changing) and risky under [DOM-5]: the change revises the
normative tail-pin rule in [TUI-9.2], states the process exit code in
[TUI-12.1], and extracts a live-state owner (render timing is behavioral
coupling under engineering-principles §14 floor 2). Hardening is required.
Not process-changing.

Plan type: implementation with spec revision.

Owner: implementing engineer.

## Goal

Protect the loop that makes a human a participant rather than a spectator:
follow, notice, reply. Today the transcript stops following the newest
message after the user's own send (6/7 runs) and after a single resize
(5/5): `_apply_delivery` and `on_resize` both call `_capture_scroll_anchor`
on arrival while a `scroll_end` is still pending, and the capture converts
the tail pin into a history anchor. Every row shows the raw 19-digit id
where a person needs a time. The rapid-resize test the completed
implementation plan promised exercises `layout.plan_latest_resize`, which
production never calls. `taut tui` exits 0 after a fatal Textual crash.
Evidence: `docs/plans/artifacts/2026-09-23-deep-dive-review.md` §1 items
8–9, §2, §3 G.

## Requested Outcomes

- [x] A tail-pinned transcript stays pinned across the user's own send, a
  watcher delivery, and any number of resizes. Only explicit user viewport
  intent changes that ownership: scrolling away enters history, reaching the
  tail pins it again, and opening a search hit enters search-owned history.
- [x] The scroll-position logic is one named unit (`TranscriptViewport` or
  the reviewer's preferred name) with its own contract tests.
- [x] Transcript rows show a formatted time; ids remain available through
  the inspector/selection.
- [x] `test_rapid_resize_burst_builds_one_plan_for_latest_size` is replaced
  by a real-app burst test; `plan_latest_resize` and `layout_passes` are
  deleted.
- [x] `taut tui` returns the app's return code after a fatal crash.
- [x] Search results show target labels, not `dm.d_*` queue names.

## Source Documents

Source specs:

- `docs/specs/10-taut-tui.md` [TUI-1], [TUI-5.3] (transcript rows),
  [TUI-6.2] (live delivery), [TUI-9.2] (state preservation), [TUI-9.3]
  (resize processing), [TUI-12.1] (error priority), [TUI-13.2] (required
  matrices)
- `docs/specs/02-taut-core.md` [TAUT-8.2] (human time rendering is owned
  by the CLI renderer today; the public formatter is added under
  [TAUT-8.3] as a presentation helper, one sentence)
- `docs/specs/01-development-documentation-operating-model.md` [DOM-5],
  [DOM-6], [DOM-15]

Supporting context:

- `docs/program-theory.md` [THEORY-1] (humans and agents both first-class),
  [THEORY-3] "Human-first terminal UI" row.
- `docs/agent-context/engineering-principles.md` §14 floor 2 (every state
  machine gets a name and a contract test; the watcher extraction is the
  precedent).
- `docs/lessons.md` 2026-08-18 (capture view state when leaving a surface,
  never on arrival) and 2026-08-14 (fixed-count short pauses are not a
  deadline).
- `2026-08-12-taut-tui-implementation-plan` (retired plan; source `74e1455`) (completed)
  lines ~683–690: the promised app-level burst test and task-count
  diagnostic.
- `docs/plans/2026-09-16-windows-lifecycle-determinism-plan.md` (active):
  S3 "user viewport intent supersedes search restoration" and the reverted
  `620fbe3` protected search anchor (`d7fc067`); S4 DM-navigation blocker.
- `docs/plans/2026-09-15-reported-issues-followup-plan.md` (active): S1/S2
  rename continuity and drafts — untouched here.
- `docs/implementation/12-taut-tui.md`.
- `docs/plans/artifacts/2026-09-23-deep-dive-review.md` §1 items 8–9.

## Spec Baseline

- `c894059` (0.9.9 release SHA) — `docs/specs/10-taut-tui.md` at plan
  authoring time. Since `c0a4616` only the [TUI-11] terminal-lease ownership
  sentence changed (`583038e`), outside every section this plan touches.
- Promotion baseline identifier: `cfd8799` plus the uncommitted worktree
  promotion in `docs/specs/10-taut-tui.md` [TUI-5.3], [TUI-9.2], [TUI-12.1],
  [TUI-13.2] and `docs/specs/02-taut-core.md` [TAUT-8.3]. Other uncommitted
  spec edits in the shared worktree belong to concurrent tasks; the named
  sections are this plan's exact promotion boundary.

## Proposed Spec Delta

Promotion strategy: **A — in-file edit, text before link claims**.

| Spec file | Strategy | Sections touched |
|-----------|----------|------------------|
| `docs/specs/10-taut-tui.md` | A | [TUI-9.2] tail-pin paragraph; [TUI-5.3] time column; [TUI-12.1] exit code; [TUI-13.2] burst matrix row; `## Related Plans` |
| `docs/specs/02-taut-core.md` | A | [TAUT-8.3] one sentence naming the public message-time formatter on `taut.terminal`; `## Related Plans` |

### [TUI-9.2] — replace the sentence `When wrapping changes, a tail-pinned
view remains tail-pinned.`

> Tail pinning is sticky. A view pinned to the live tail remains pinned
> across wrapping changes, resize, the user's own send, watcher delivery, and
> re-render. System-driven arrival, layout, and restoration events never
> capture or change viewport ownership. Explicit user viewport intent does:
> keyboard or mouse movement whose settled position is away from the tail
> enters history at that position; movement whose settled position reaches
> the tail pins it again; and opening a search result enters search-owned
> history at that result. Search-owned restoration is retained across
> system-driven renders until it completes or newer user viewport intent
> supersedes it. When wrapping changes, a history view restores the same
> anchor message instead of jumping to newest content.

### [TUI-5.3] — amend the metadata sentence for transcript rows

Locate the sentence that names the row metadata (sender, timestamp,
reply marker). Replace the timestamp element with:

> a local wall-clock time formatted the same way the CLI's human renderer
> formats message times (`HH:MM`); the exact 19-digit id is available through
> selection and the inspector, never in the row

Append to the actor-scoped-label paragraph:

> Search-result target metadata uses the same actor-scoped direct-message
> label as navigation. If that label is temporarily unavailable, it renders
> `Direct message`; an internal `dm.d_*` queue name never appears in the
> result row.

### [TAUT-8.3] — append one sentence to the presentation helpers

Locate the paragraph in [TAUT-8.3] that describes `taut.terminal`'s public
display transform (grep `terminal` in the section). Append:

> `taut.terminal` also publishes the human message-time formatter the CLI
> renderer uses (`HH:MM` in local time), so first-party surfaces render one
> time for one message.

### [TUI-12.1] — append to the first paragraph

> The `taut tui` process exit code is the application's return code: 0
> after a normal quit, 1 after a fatal error that Textual retained on the
> completed application, and the ordinary core dispatch codes for
> pre-screen failures. Capturing the fatal exception under [TAUT-13] does
> not change that code.

### [TUI-13.2] — add a matrix row

> | Rapid resize burst across 119, 79, 49, 80 columns without an application-level pause between requested sizes, while a watcher delivery and a worker result arrive, with a draft, tail-pinned transcript, selected message, and open inspector | after event-loop quiescence the rendered mode matches 80 columns; preserved state and tail pin remain; later loop turns do not revert to an earlier size, proving no obsolete layout work survives | real `TautApp` under `run_test`, real SQLite, real watcher delivery |

### `## Related Plans` — add

> - `docs/plans/2026-09-24-tui-participation-loop-plan.md` — makes tail
>   pinning sticky under a named viewport owner, shows times instead of
>   ids, replaces the dead rapid-resize test with a real burst test, and
>   makes the process exit code truthful.

## Context and Key Files

Files to modify:

- `extensions/taut_tui/taut_tui/app.py` (3,721 lines) —
  `on_resize` (line ~538–560: calls `_capture_draft_cursor()` then
  `_capture_scroll_anchor()` before computing the transition);
  `_apply_delivery` (line ~3244–3262: `self._capture_scroll_anchor()` then
  `self._render_messages(...)`); `_capture_scroll_anchor` (line ~3342);
  `_on_transcript_user_viewport_intent` (line ~3375); the restore path
  around line ~3314 (`elif anchor.tail_pinned:`); fields
  `_pending_search_anchor`, `_search_anchor_restore_applied`,
  `_transcript_restore_generation`, `visual_state.scroll_anchor`;
  `_message_prompt` (line ~3462–3476: renders `f"  {message.ts}"`). Also
  route `_apply_navigation_result`'s system-driven capture-before-rerender
  through the owner; otherwise reply-marker refresh can still unpin the tail.
- `extensions/taut_tui/taut_tui/widgets.py` — `TautOptionList` currently
  invokes one parameterless `user_viewport_intent` callback before Up, Down,
  Home, End, PageUp/PageDown, click, and mouse-scroll processing. Replace it
  with a two-phase callback: synchronously report `USER_INTENT_STARTED` before
  movement so queued render effects become stale, then schedule a settled
  observation after the user action has changed the public scroll position
  and report whether the list is at the tail plus the history anchor when it
  is not. Programmatic `scroll_end` and `scroll_to` restoration must not emit
  either phase.
- `extensions/taut_tui/taut_tui/models.py` — replace the independently
  mutable `VisualState.scroll_anchor` with `VisualState.viewport`, whose value
  is the pure viewport-owner state. The app and tests inspect that one value;
  no compatibility projection or second copy remains.
- `extensions/taut_tui/taut_tui/layout.py` — `plan_latest_resize` (line
  ~206), `layout_passes` (line ~61), the `__all__` entry (line ~231).
- `extensions/taut_tui/taut_tui/_launch.py` — `return 0` (line ~47) after
  `app.run()` and `_retained_textual_fatal`.
- `extensions/taut_tui/taut_tui/screens.py` — search result rendering
  (line ~880–885) uses `hit.thread` via `getattr` on `list[object]`.
  `TautApp._target_labels` already owns actor-scoped labels; `SearchScreen`
  receives an immutable snapshot when it opens and falls back to `hit.thread`
  only when no public label is known.
- `extensions/taut_tui/tests/test_tui_resize.py` (line ~231 dead test;
  line ~148 pure-model tail-pin test), `tests/test_tui_app.py`,
  `tests/test_tui_launch.py` (line ~403–405 pins `result == 0` with
  `app.return_code == 1`), `tests/test_tui_screens.py`.
- `docs/implementation/12-taut-tui.md`, committed golden SVGs under
  `docs/implementation/artifacts/tui/` (regenerate with
  `bin/render-tui-screens`).
- Core: `taut/commands/_rendering.py` `format_message_time` (line ~852,
  private today) — publish it on `taut.terminal` (the public module that
  already owns display-time text transforms) and have `_rendering.py` call
  the public function so there is one implementation; the TUI imports it
  from `taut.terminal`. Owner decision 2026-09-24: publish, do not
  duplicate.

Read first: [TUI-9.2], [TUI-9.3], [TUI-6.2]; the Windows plan's S3 and the
`620fbe3`/`d7fc067` pair; `app.py` lines 3244–3450 in full; the 2026-08-18
lesson.

Comprehension gate:

1. **Why does capturing on arrival lose the pin?** Expected: at capture
   time the previous `scroll_end` has not been applied, so
   `scroll_y < max_scroll` by a row or two; the capture reads that as
   "not at the tail" and records a history anchor.
2. **Which events may change viewport ownership?** Expected: settled user
   scroll position may move tail → history or history → tail, and explicit
   search-result activation may enter search-owned history. Every other event
   is the system moving content and retains the current owner; `620fbe3`
   tried to protect a search anchor by suppressing later captures rather than
   modeling those user transitions and regressed W4.
3. **Where does the CLI format times, and why must the TUI match it?**
   Expected: `_rendering.format_message_time`; [THEORY-3] gives
   presentation to its owner and the human must see the same time in both
   surfaces.

## Invariants and Constraints

- Boundary discipline stays as verified: no CLI invocation, no imports of
  underscored core modules. Publishing a time formatter means adding it to
  a public core surface (`taut.terminal` or `taut.client`), not importing
  `taut.commands._rendering`.
- Draft, cursor, focus, mode, inspector, and selection preservation
  ([TUI-9.2]) are unchanged and their tests must stay green.
- Search-anchor restoration (Windows plan S3) keeps "newer user viewport
  intent supersedes restoration"; search-result activation itself is user
  intent and legitimately enters search-owned history. The new owner must
  encode both rules as transitions, not a flag pair.
- No resize task per event ([TUI-9.3]); latest-wins.
- [TUI-13.1] real boundaries: contract tests use real `TautApp` under
  `run_test`, real SQLite, real watcher; the viewport owner's own tests
  may be pure.
- Manual visual review of regenerated SVGs is still required by [TUI-13.2].
- Textual privates already in use (`App._exception`, `Input._suggestion`,
  `OptionList._get_visual`) are not multiplied; if the viewport owner needs
  a scroll position, use public `ScrollView` attributes.

Hidden couplings:

- `_apply_conversation` (send result) renders the new row and schedules
  `scroll_end`; the watcher then delivers the same message; both paths
  must feed the same owner with "append" events.
- `_transcript_restore_generation` guards stale restores; the owner
  subsumes it. The generation belongs to every viewport state, not only
  search: a queued tail or history effect can also overwrite newer user input.
- The Windows S4 blocker (DM navigation timeout) is not this plan's
  defect, but the ~80 attempt-counted `_pause_until` loops it implicates
  are; task 8 converts the ones the new tests touch and records the
  pattern for the Windows plan.

Failure policy: a viewport-owner error is a presentation failure
([TUI-12.1]): the domain mutation stays successful, the TUI refreshes from
public state, and the error is reported through the safe notification
path.

## Rollout, Rollback, and One-Way Doors

- Source revert per slice; the viewport extraction is one commit that can
  be reverted independently of the time-column and exit-code changes.
- No storage change. No one-way door.
- Post-deploy signal: send a message from the TUI, then post from the CLI;
  the transcript shows both at the bottom without scrolling; resize twice;
  still at the bottom.

## Dependency-Ordered Tasks

1. **Close the independent plan review.** Append the completed review's full
   findings and verdict, disposition every finding, then run a scoped round-2
   verification over the accepted corrections before spec promotion.
2. **Spec-promotion slice**; record the promotion baseline.
3. **Red real-app tests and deadline helper.** Replace `_pause_until` in the
   touched test module with `_eventually(pilot, predicate, *, timeout)`, using
   `asyncio.get_running_loop().time()` to enforce one elapsed-time deadline
   while `pilot.pause()` yields; do not add an attempt-count parameter. Then
   in `tests/test_tui_app.py`: (a) open a channel,
   send from the TUI, deliver one CLI message through the real watcher,
   assert `visual_state.viewport` is tail-owned and the newest row visible; (b)
   resize 130→100→80 while pinned; (c) the [TUI-13.2] burst row, issuing all
   requested sizes without an application-level pause, then waiting for
   semantic convergence. Assert the latest mode and preserved public visual
   state, deliver the concurrent results, yield further loop turns, and assert
   that no stale layout later replaces the 80-column result. Do not assert a
   single render pass: production handles resize synchronously and the
   contract permits that. All three tests must fail at baseline; record which
   assertion each fails on.
4. **Extract the viewport owner.** New module
   `extensions/taut_tui/taut_tui/viewport.py`: a pure module with no Textual
   import. One frozen `TranscriptViewport` holds a monotonically increasing
   generation in every state plus one of the closed modes `TAIL`,
   `HISTORY(message_id, offset)`, or `SEARCH_OWNED(intent, message_id)`. A
   frozen `ViewportEffect` contains the generation token and exactly one
   effect: `SCROLL_END` or `RESTORE(message_id, offset)`. Its transitions and
   render effects are:

   | Current state | Event | Next state / required render effect |
   |---|---|---|
   | any | `USER_INTENT_STARTED` | retain semantic position, increment generation so every queued effect is stale |
   | any | `USER_VIEWPORT_SETTLED(at_tail=True)` | `TAIL`; invalidate any pending restore |
   | any | `USER_VIEWPORT_SETTLED(at_tail=False, anchor, offset)` | `HISTORY(anchor, offset)`; invalidate any pending restore |
   | `TAIL` or `HISTORY` | `TARGET_CHANGED` | `TAIL`; invalidate pending restore before the new conversation renders |
   | `SEARCH_OWNED` | matching search-context target change | retain search ownership; the authorized context render performs the search restore |
   | `SEARCH_OWNED` | any other target change | `TAIL`; invalidate the superseded search |
   | any | `SEARCH_ARMED(intent, message_id)` | `SEARCH_OWNED(intent, message_id, new_generation)` |
   | `TAIL` | `APPEND`, `RERENDER`, or `RESIZE` | retain `TAIL`; increment generation and emit tokened `SCROLL_END` |
   | `HISTORY` | `APPEND`, `RERENDER`, or `RESIZE` | retain the anchor; increment generation and emit tokened `RESTORE` |
   | `SEARCH_OWNED` | matching authorized render | retain ownership; increment generation and emit tokened `RESTORE` for the search message |
   | any | matching `RESTORE_DONE(effect, settled_offset)` | accept only the current generation; `SEARCH_OWNED` becomes `HISTORY(search_message, settled_offset)`, other modes retain their semantics with any clamped offset |
   | any | stale effect completion | no effect; stale work cannot mutate the current state |

   Contract tests in `tests/test_tui_viewport.py` enumerate each row plus stale
   tail, history, and search effects (Golden Rule 13). The Textual adapter
   derives the settled user observation from public `ScrollView` attributes
   after input processing. It starts intent synchronously, then schedules the
   observation from explicit OptionList action methods, pointer and
   mouse-wheel handlers, and the retained child-scrollbar `on_scroll_to`
   (`ScrollUp`/`ScrollDown` where Textual emits them) boundary. The pinned
   Textual 8.2.8 contract probe proves a child scrollbar gesture emits those
   messages while programmatic `scroll_to()` does not, so this is a user seam,
   not a generic programmatic-scroll trap. This covers the app's vi dispatch,
   conventional keys, wheel, and child scrollbar. The pure owner never reads
   widget geometry. Apply each tokened effect after refresh: check the token,
   then use public
   `scroll_end(..., immediate=True)` or `scroll_to(..., immediate=True)` so
   Textual cannot add an unguarded deferral after the check. A tail effect may
   be applied once more after `OptionList` row remeasurement only under the
   same generation token. Route
   `on_resize`, `_apply_delivery`, `_apply_conversation`, the settled user
   callback, and the search restore path through it; delete
   `_pending_search_anchor`, `_search_anchor_restore_applied`,
   `_transcript_restore_generation`, and `visual_state.scroll_anchor`; store
   the owner itself as `visual_state.viewport`. Stop if the owner needs Textual
   internals, a timer, or a second state field outside the module.
   Emit `TARGET_CHANGED` by comparing the incoming snapshot target with the
   current target in `_apply_conversation`; do not emit it merely because
   `_advance_conversation_intent` ran. Same-target send, watcher, reply-toggle,
   and recovery snapshots retain their current viewport owner.
   Integration tests fire conventional/vi keys, wheel, click, and the real
   child scrollbar as separate user-intent paths, plus programmatic
   `scroll_to(..., immediate=True)` as a non-intent path.
5. **Time column.** Red: a core test that `taut.terminal` exports the
   formatter and that the CLI human renderer and the export agree on a
   fixed id in the same process, with an independent `HH:MM` shape assertion;
   a TUI test that the rendered row contains the export's result and not the
   19-digit id. This slice does not add date-sensitive behavior. Move the
   unchanged implementation to
   `taut.terminal`, re-point `_rendering.py` at it, render it in all three
   metadata layouts, keep the id in the inspector/selection; regenerate the
   golden SVGs; run the manual visual review and record it. Stop if the
   move needs anything from `taut.commands` inside `taut.terminal`; the
   dependency runs the other way.
6. **Dead test and dead code.** Delete `plan_latest_resize`,
   `layout_passes`, the `__all__` entry, and the false test; the burst
   test from task 3 replaces it. Confirm no other caller.
7. **Exit code.** `_launch.py`: `return app.return_code or 0`; rewrite
   `test_tui_launch.py:403-405` to assert the process result equals the
   app return code.
8. **Search labels.** Type `SearchScreen` and its future as `SearchHit`, and
   pass an immutable snapshot of `TautApp._target_labels` when the screen
   opens. Render `labels[hit.thread]` when known; an unknown DM uses the
   non-opaque fallback `Direct message`, while an unknown channel may use its
   public thread name. This keeps the TUI's existing actor-scoped navigation
   label as the owner and never exposes a DM queue name. Test that a labelled
   DM hit contains the human label and does not contain `dm.d_*` in
   `test_tui_screens.py`, plus an unknown-DM case proving the safe fallback.
   Convert the polling loops touched by tasks 3–8 to the deadline helper from
   task 3.
9. **Docs, CHANGELOG, traceability, completed-work review, index flip.**
   Update `docs/implementation/12-taut-tui.md` with the viewport owner and
   the capture-on-leave rule; note in the Windows plan's Execution Log
   (append-only) which polling loops were converted.

## Testing Plan

- Layer: real `TautApp` via Textual `run_test`, real SQLite workspaces
  built through the CLI, real watcher deliveries; pure unit tests for the
  viewport owner.
- Files: `tests/test_tui_viewport.py` (new), `tests/test_tui_app.py`,
  `tests/test_tui_resize.py`, `tests/test_tui_launch.py`,
  `tests/test_tui_screens.py`.
- Do not mock the watcher, the session, or `scroll_end`; do not assert on
  private `app._*` fields in the new tests — assert on `visual_state` and
  rendered rows.
- Mutation check: restore capture-on-arrival in `_apply_delivery` and
  confirm task-3(a) fails.
- Full TUI suite including the retained-lock lane.

## Verification and Gates

```bash
cd extensions/taut_tui && uv run --extra dev pytest -n 0 tests/test_tui_viewport.py tests/test_tui_resize.py tests/test_tui_launch.py
cd extensions/taut_tui && uv run --extra dev pytest
cd extensions/taut_tui && uv run --extra dev ruff check taut_tui tests && uv run --extra dev mypy taut_tui tests --config-file pyproject.toml
bin/render-tui-screens && git diff --stat docs/implementation/artifacts/tui/
bin/check-doc-paths && bin/check-plan-status-index
```

## Independent Review Loop

Reviewer: the different-family reviewer used for the completed first round.
Append that round's full output and dispositions. The scoped round-2 inputs are
this revision, the delta, `app.py` lines 536–560 and 3244–3450, `widgets.py`
`TautOptionList`, `layout.py`, `_launch.py`, `screens.py` `SearchScreen`, the
Windows plan's S3, and the 2026-08-18 lesson. Ask: "Do the accepted corrections
now make search activation, settled user scrolling, synchronous rapid resize,
the unchanged `HH:MM` formatter, and actor-scoped DM labels unambiguous and
implementable without reintroducing `620fbe3`?" Verify only those corrections
and any new defect they introduced.

## Out of Scope

- Rename/draft continuity (reported-issues plan S1/S2).
- The Windows S4 DM-navigation diagnosis (Windows plan); this plan only
  converts the polling loops it touches.
- Help text layout, DM unread counts, navigation label wrapping, startup
  focus (P3 UX items; a follow-up Class 2/3 change).
- Textual upper-bound pin (`<9`) — raise with the owner under the
  2026-08-08 lesson; not decided here.
- Summon terminal handoff.

## Assumptions and Open Questions

1. **Resolved 2026-09-24 (owner): publish the formatter** on
   `taut.terminal`; one presentation owner, no duplicate.
2. **Windows S4 closure (owner direction 2026-09-24): close Windows bugs by
   designing a test that elicits them, then running CI — not by time-box.**
   Facts as of `c894059`: S4's instrumented test has passed in every hosted
   Windows run since `6326905`, including the 0.9.9 release SHA; the
   2026-09-23 red streak on Windows (runs at `3993e20` through `88a2f40`)
   was `test_setup_recovery_offer_reaches_a_pending_owned_tui_and_completes`
   in `test_tui_summon.py`, not S4's test. A green run is not sufficient
   under S4's own gate because the instrumentation *observes* and produces
   evidence only when the failure recurs; it does not *elicit*. What
   closes S4 by the owner's method is one forced-order test per candidate
   cause in S4's classification list, each run on Windows CI:
   - **wait budget:** inject a delay at the real `session.refresh_navigation`
     boundary longer than the old attempt-counted budget; assert the old
     wait shape fails and the deadline-based wait still renders the DM;
   - **stale-result rejection:** deliver a navigation result with a stale
     generation followed by a fresh one; assert the fresh one renders;
   - **missing callback / widget application:** force the future to
     complete after the widget is mounted and after it is unmounted;
     assert the mounted case renders and the unmounted case is rejected
     without a hang.
   **Superseded closure inference (2026-09-25):** the approved successor
   `docs/plans/2026-09-24-windows-tui-determinism-root-cause-plan.md`
   replaces the earlier claim that green candidate tests exonerate every
   product owner and thereby identify the old harness budget as the cause.
   Finite forced schedules rule out only the cases exercised. Navigation
   has no stale-generation guard, so its actual serialized-worker and
   callback-order boundaries are tested rather than inventing one. The
   successor owns these proofs, five-repeat qualification, and S4 disposition:
   causal reproduction and correction, or explicit owner acceptance recorded
   as "cause unresolved; accepted by owner". No such acceptance is inferred.
   This participation plan only converts the polling loops it touches.

## Deviation Log

| Spec ref | Planned behavior | Actual behavior | Rationale | Spec proposal |
|----------|------------------|-----------------|-----------|---------------|
| [DOM-5] ordering | Review → promotion → red/green implementation | The two isolated formatter and launch/search delegates observed RED, then edited production files while the viewport review was still running and before this promotion landed. No viewport production edit began before promotion. | Parallel dispatch crossed the intended promotion barrier. The behavior proofs remain valid, but the timing claim must be explicit rather than rewritten. | None; process deviation only. |
| [TUI-13.2] promotion form | Add a table row | Replaced the existing rapid-resize bullet in the owning enumerable list with the expanded scenario and oracle. | The live section is a bullet matrix, not a Markdown table; preserving its grammar keeps the enumerable contract coherent. | Promoted semantics are unchanged. |
| [TUI-9.2] tail effect application | One checked after-refresh immediate scroll | The adapter repeats the same tokened immediate tail scroll after `OptionList` remeasures its rows. | The real burst test exposed that the first checked callback can precede the new virtual height. The second application is still generation-fenced and creates no resize task or unguarded animation. | None; this is adapter timing below the ownership contract. |

## Review Log

(append-only)

- 2026-09-24 — Owner reported the independent review complete; its full
  record and verdict remain to be appended before spec promotion.
- 2026-09-24 — Fresh-eyes implementability pass found and corrected five plan
  defects: search activation is explicit user viewport intent rather than a
  system event that must retain tail ownership; the widget adapter must report
  settled direction instead of a parameterless pre-motion callback; the
  published formatter retains its actual local `HH:MM` behavior with no
  invented date prefix; the synchronous resize path proves latest-state
  convergence rather than a fictional single render; and `SearchScreen`
  receives the existing actor-scoped label snapshot. The pass also replaced
  the nonexistent `async_eventually` reference with an explicit elapsed-time
  helper contract.
- 2026-09-24 — Viewport scoped round 2: `FAIL`, finding VPR2-01 accepted.
  The first correction overgeneralized Textual scroll messages as
  programmatic and would have deleted the proven child-scrollbar user-intent
  seam. Task 4 now retains two-phase `on_scroll_to`/supported scroll-message
  handling, cites the pinned Textual probe that distinguishes it from
  programmatic `scroll_to()`, and requires firing user tests plus a
  programmatic non-intent test. All other viewport and resize corrections
  passed that review.
- 2026-09-24 — VPR2-01 verification initially found click missing from the
  enumerable firing list; click was added. Final scoped verdict: `PASS`; the
  child-scrollbar seam, synchronous start/settled ordering, programmatic
  non-intent control, and key/vi/wheel/click coverage are implementable with
  no new defect.
- 2026-09-24 — A different-family scoped review was launched against the
  earlier corrected draft and stopped after about eleven minutes without a
  verdict because the viewport reconnaissance had superseded its brief. No
  conclusion is inferred from that stopped run; the owner-reported first
  review and the recorded scoped PASS above are the review evidence used for
  promotion.
- 2026-09-24 — Completed-work independent review: initial verdict `FAIL`.
  Accepted findings were unconditional pane capture, missing-anchor history
  recovery, a rapid-resize scenario that did not match the promoted enumerable
  contract, missing separate vi/real-scrollbar/programmatic-control proofs,
  and incomplete transition enumeration. All five were corrected. Re-review
  verdict: `PASS`; 23 focused tests passed and no actionable finding remained.

## Execution Log

(append-only)

- 2026-09-24 — Owner decision: publish core's message-time formatter on a
  public surface and have the TUI use it; no TUI-owned duplicate.
- 2026-09-24 — Comprehension gate: capture-on-arrival observes geometry before
  the prior deferred `scroll_end` and falsely records history; explicit
  settled user movement and search activation are the only viewport ownership
  changes; the current CLI formatter is `_rendering.format_message_time` and
  moves unchanged to `taut.terminal` so CLI and TUI share one presentation
  owner.
- 2026-09-24 — Spec promotion applied in the named promotion-baseline
  sections before viewport implementation. The rapid-resize contract used the
  owning section's bullet grammar rather than inserting a one-row table; see
  the deviation log.
- 2026-09-24 — RED evidence: the new viewport contract failed import because
  `taut_tui.viewport` did not exist; the formatter test failed because
  `taut.terminal.format_message_time` did not exist; the launch test observed
  process result 0 while `app.return_code` was 1; and the typed search-screen
  tests failed against the old constructor. Each slice then passed its focused
  test before broader integration.
- 2026-09-24 — GREEN implementation: `TranscriptViewport` now owns tail,
  history, search, and generation-fenced effects; capture-on-arrival was
  removed from resize, delivery, and navigation refresh; conventional/vi
  actions, wheel, scrollbar, and click cross the user-intent seam. The final
  real SQLite/watcher/worker resize test matches 119→79→49→80 exactly; the
  complete TUI suite passed: `499 passed in 192.54s`.
- 2026-09-24 — Formatter/launcher/search proof: core CLI/public API tests
  passed (`205 passed, 1 skipped`); scoped core ruff and mypy passed; scoped
  TUI mypy passed across 14 changed source/test files; full TUI ruff passed.
  Full-extension mypy is currently obscured by concurrent worktree edits in
  `taut_tui/domain.py` and the shared terminal-probe package, outside this
  plan's files.
- 2026-09-24 — Documentation gates passed: `check-doc-paths`,
  `check-plan-status-index`, and 15 documentation-reference tests. Golden
  SVGs were regenerated with `uv run --extra dev python
  bin/render-tui-screens`; manual inspection of 130x34, 100x34, and 64x34
  showed the intended local time column with no layout regression. Direct
  `bin/render-tui-screens` lacks the extension import path in this checkout,
  so the documented uv invocation was used.

## Fresh-Eyes Review

The extraction is the largest edit; task 4 now fixes its state, transition,
effect, storage, and adapter contracts so the implementer cannot drift into
another flag pair. Search activation and settled scroll direction are explicit
user transitions; delivery, re-render, and resize retain ownership. The
time-column seam is owner-resolved and preserves the formatter's current
behavior. The real resize oracle matches the synchronous production path, and
the search label source is fixed rather than left as an implementation choice.
