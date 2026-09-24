# TUI Participation Loop Plan

Status: draft — findings verified by headless reproduction; awaiting
independent plan review.

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

- [ ] A tail-pinned transcript stays pinned across the user's own send, a
  watcher delivery, and any number of resizes; only user scroll intent
  un-pins it.
- [ ] The scroll-position logic is one named unit (`TranscriptViewport` or
  the reviewer's preferred name) with its own contract tests.
- [ ] Transcript rows show a formatted time; ids remain available through
  the inspector/selection.
- [ ] `test_rapid_resize_burst_builds_one_plan_for_latest_size` is replaced
  by a real-app burst test; `plan_latest_resize` and `layout_passes` are
  deleted.
- [ ] `taut tui` returns the app's return code after a fatal crash.
- [ ] Search results show target labels, not `dm.d_*` queue names.

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
- Promotion baseline identifier: recorded after the spec-promotion slice.

## Proposed Spec Delta

Promotion strategy: **A — in-file edit, text before link claims**.

| Spec file | Strategy | Sections touched |
|-----------|----------|------------------|
| `docs/specs/10-taut-tui.md` | A | [TUI-9.2] tail-pin paragraph; [TUI-5.3] time column; [TUI-12.1] exit code; [TUI-13.2] burst matrix row; `## Related Plans` |
| `docs/specs/02-taut-core.md` | A | [TAUT-8.3] one sentence naming the public message-time formatter on `taut.terminal`; `## Related Plans` |

### [TUI-9.2] — replace the sentence `When wrapping changes, a tail-pinned
view remains tail-pinned.`

> Tail pinning is sticky. A view pinned to the live tail remains pinned
> across wrapping changes, resize, the user's own send, watcher delivery,
> re-render, and search-anchor restoration. Exactly one event un-pins it:
> user scroll intent (keyboard or mouse movement away from the tail).
> Arrival of new content never captures the viewport; the viewport owner
> captures state only when the user leaves the tail. When wrapping changes
> a history view restores the same anchor message instead of jumping to
> newest content.

### [TUI-5.3] — amend the metadata sentence for transcript rows

Locate the sentence that names the row metadata (sender, timestamp,
reply marker). Replace the timestamp element with:

> a local wall-clock time formatted the same way the CLI's human renderer
> formats message times (`HH:MM`, with the date prefix the CLI adds when
> the day differs); the exact 19-digit id is available through selection
> and the inspector, never in the row

### [TAUT-8.3] — append one sentence to the presentation helpers

Locate the paragraph in [TAUT-8.3] that describes `taut.terminal`'s public
display transform (grep `terminal` in the section). Append:

> `taut.terminal` also publishes the human message-time formatter the CLI
> renderer uses (`HH:MM`, with a date prefix when the day differs), so
> first-party surfaces render one time for one message.

### [TUI-12.1] — append to the first paragraph

> The `taut tui` process exit code is the application's return code: 0
> after a normal quit, 1 after a fatal error that Textual retained on the
> completed application, and the ordinary core dispatch codes for
> pre-screen failures. Capturing the fatal exception under [TAUT-13] does
> not change that code.

### [TUI-13.2] — add a matrix row

> | Rapid resize burst across 119, 79, 49, 80 columns while a watcher delivery and a worker result arrive, with a draft, tail-pinned transcript, selected message, and open inspector | one final render at the latest size; tail still pinned; no obsolete layout task | real `TautApp` under `run_test`, real SQLite, real watcher delivery |

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
  `_message_prompt` (line ~3462–3476: renders `f"  {message.ts}"`).
- `extensions/taut_tui/taut_tui/layout.py` — `plan_latest_resize` (line
  ~206), `layout_passes` (line ~61), the `__all__` entry (line ~231).
- `extensions/taut_tui/taut_tui/_launch.py` — `return 0` (line ~47) after
  `app.run()` and `_retained_textual_fatal`.
- `extensions/taut_tui/taut_tui/screens.py` — search result rendering
  (line ~880–885) uses `hit.thread` via `getattr` on `list[object]`.
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
2. **Why is user intent the only legitimate un-pin?** Expected: every
   other event is the system moving content, and [TUI-9.2] says the view
   follows content unless the user chose otherwise; `620fbe3` tried to
   protect a search anchor by capturing on arrival and regressed W4.
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
- Search-anchor restoration (Windows plan S3) keeps "user viewport intent
  supersedes restoration"; the new owner must encode that as a transition,
  not a flag pair.
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
  subsumes it.
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

1. **Independent plan review** including the delta.
2. **Spec-promotion slice**; record the promotion baseline.
3. **Red real-app tests.** `tests/test_tui_app.py`: (a) open a channel,
   send from the TUI, deliver one CLI message through the real watcher,
   assert `scroll_anchor.tail_pinned` and the newest row visible; (b)
   resize 130→100→80 while pinned; (c) the [TUI-13.2] burst row. Use
   deadline-based waits (`async_eventually`), not attempt counts. All must
   fail at baseline; record which assertion each fails on.
4. **Extract the viewport owner.** New module
   `extensions/taut_tui/taut_tui/viewport.py`: states tail / history
   (anchor, offset) / search-owned (intent, msg); events user-scroll,
   append, rerender, resize, search-armed, restore-done, superseded; pure
   functions over a small dataclass, no Textual import. Contract tests in
   `tests/test_tui_viewport.py` enumerate every state × event (Golden Rule
   13). Then route `on_resize`, `_apply_delivery`, `_apply_conversation`,
   `_on_transcript_user_viewport_intent`, and the search restore path
   through it and delete the four scattered fields. Stop if the owner
   needs Textual internals or a timer.
5. **Time column.** Red: a core test that `taut.terminal` exports the
   formatter and that the CLI human renderer and the export agree on a
   fixed id (same day and different day); a TUI test that a rendered row
   contains `HH:MM` and not the 19-digit id. Move the implementation to
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
8. **Search labels.** Type the search screen on `SearchHit` (or pass the
   label map) so DM hits render the actor-scoped label; test in
   `test_tui_screens.py`. Convert the polling loops touched by tasks 3–8
   to deadline-based waits.
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

Reviewer: a different family. Inputs: this plan, the delta, `app.py`
lines 536–560 and 3244–3450, `layout.py`, `_launch.py`, the Windows
plan's S3, the 2026-08-18 lesson. Ask: "Does the proposed owner's
transition table cover the search-anchor restoration case without
reintroducing `620fbe3`? Is publishing the core time formatter the right
seam?"

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
   If every candidate passes forced-order on Windows, every product owner
   is exonerated by construction and the remaining cause is the harness
   budget the rewrite already replaced; S4 then closes with that
   classification recorded, which satisfies its "classify from positive
   evidence" rule. If one fails, that is the causal reproduction the plan
   asked for. Those tests, and S4's closure, are owned by
   `docs/plans/2026-09-24-windows-tui-determinism-root-cause-plan.md`;
   this plan only converts the polling loops it touches.

## Deviation Log

| Spec ref | Planned behavior | Actual behavior | Rationale | Spec proposal |
|----------|------------------|-----------------|-----------|---------------|

## Review Log

(append-only)

## Execution Log

(append-only)

- 2026-09-24 — Owner decision: publish core's message-time formatter on a
  public surface and have the TUI use it; no TUI-owned duplicate.

## Fresh-Eyes Review

The extraction is the largest edit; task 4 fixes its interface (pure,
no Textual import, enumerated transitions) so the implementer cannot drift
into another flag pair. The time-column seam is the one cross-package
decision and is called out as an open question rather than assumed.
