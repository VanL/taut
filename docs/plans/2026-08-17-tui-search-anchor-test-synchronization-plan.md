# TUI Search-Anchor Test Synchronization Plan

Date: 2026-08-17

Class: 4. This changes an async test-observation lifecycle across Textual's
deferred transcript-anchor restore and refresh boundary.

Status: completed at `99995cc49249996c208646ee972d940c48383119`.

## Goal

Make the exhaustive `search.open-result` handler proof observe the exact
intent-tokened conversation apply and the anchor restore scheduled by that
same apply. Time remains only a missing-callback cap. No product behavior,
timeout, existing assertion removal or weakening, matrix, or parallelism
changes.

## Source Documents and Baseline

- `docs/specs/10-taut-tui.md` [TUI-9.2], [TUI-13.1], [TUI-13.2]
- `docs/implementation/12-taut-tui.md`, Ownership Model, command/search
  boundary, and Responsive Presentation
- `docs/plans/2026-08-14-taut-tui-action-route-contract-plan.md`

Baseline: `2b2fa49a86597972af398f3b4d9ebb39fc3f6852`. This plan does not revise
the product contract.

## Context, Ownership, and Classification

- Ubuntu Python 3.14 job `95560962858` in pre-tag run `32086814821` completed
  the exact expected `ConversationSnapshot`, but the test asserted the logical
  search anchor before `_render_messages()` executed its deferred
  `_restore_transcript_anchor()` callback. Ubuntu 3.11/3.13, macOS, and Windows
  passed at the same SHA.
- `extensions/taut_tui/tests/test_tui_action_handlers.py` owns the exhaustive
  real-handler proof. Production `app.py` remains unchanged.
- The failure is provisionally a test-observation defect. If the exact restore
  scheduled by the expected intent completes and the anchor is still wrong,
  stop and reclassify it as an application race.

## Invariants, Hidden Couplings, and Anti-Mocking Floor

- Retain the real Textual pilot, SQLite, public search/history operation,
  intent token, `ConversationSnapshot`, production apply method, transcript
  render, restore method, and every final snapshot/row/target/anchor assertion.
- Bind the restore observer to the exact `expected_intent`, not merely the
  message id. Install it only while delegating that intent's real
  `_apply_optional_conversation()` call, then restore the instance method
  immediately. Textual's scheduled callback retains the exact wrapper.
- The wrapper delegates to the real restore first, matches the selected hit,
  and signals only after the following refresh. A stale intent, unrelated
  restore, exception, wrong hit, or missing callback cannot pass.
- Five seconds is only a missing-event/deadlock cap. Elapsed time never proves
  success.
- Do not mock broker reads/writes, search hydration, cursor behavior, the
  conversation apply, rendering, or scroll restoration.

## Stop Gates, Rollback, and Success Signals

- Stop before product edits if the exact expected-intent restore has not been
  observed. If it is observed with wrong state, reopen as an app failure and
  harden production under a revised plan.
- Do not increase timeouts, poll state, reduce assertions, skip a platform,
  change the retained Textual lock, or weaken parallelism.
- The test-only observer is independently reversible. Release tag publication
  is the one-way door and remains blocked until a fresh exact-SHA five-job TUI
  matrix and the root/PG/MCP producer workflows pass.
- Success is repeated focused proof, the full handler and TUI suites, static
  and documentation gates, independent review, and fresh hosted Ubuntu 3.14
  plus all other TUI lanes.

## Tasks and Verification

1. Record the hosted red evidence and causal boundary in this plan.
2. Install the expected-intent-scoped delegated restore observer and retain all
   exact assertions.
3. Run the focused case repeatedly, the 37-case handler matrix, the full TUI
   suite, Ruff, format, TUI mypy, documentation gates, and `git diff --check`.
4. Obtain independent completed-work review, commit, push, and require fresh
   exact-SHA hosted producer evidence before resuming `bin/release.py`.

## Independent Review

Review must verify exact-intent identity, temporary observer scope, delegation,
post-refresh signaling, stale-callback rejection, retained and strengthened
assertions, and the test-versus-app stop gate. Any P1/P2 finding blocks commit.

## Out of Scope

- Search semantics, history bounds, cursor policy, watcher lifecycle, product
  scroll logic, action routes, Textual version, CI topology, and release
  machinery.

## Execution Log

- Red: run `32086814821`, job `95560962858`, failed with a successful exact
  snapshot but `ScrollAnchor.tail()` at the premature final assertion.
- First correction matched only the hit id. Independent review rejected it
  because a stale restore for the same message could satisfy the event.
- Current correction scopes the wrapper to delegation of `expected_intent`,
  restores the live method immediately, delegates the captured callback, and
  signals after its refresh. The focused case passed 20 consecutive runs; the
  complete handler file passed 37 tests; the full TUI suite passed all 378
  tests. Static and documentation gates passed. Independent completed-work
  review found no P1/P2 blocker.
- Fresh hosted exact-SHA evidence remains pending.
- Run `32093200521`, Windows job `95579370572`, exposed a fixture-isolation
  defect rather than the provisional product race. The searched hit was the
  newest message in a transcript shorter than the viewport, so the required
  hit anchor and legitimate tail-pinned geometry were physically
  indistinguishable. The exact restore ran, then an independent watcher render
  correctly recaptured the same physical position as tail before the final
  assertion. The case now seeds substantial later content only for
  `search.open-result`, asserts that later content is in the exact snapshot,
  asserts the hit anchor inside the delegated exact restore, and retains the
  post-refresh final anchor assertion. No product code, timeout, assertion,
  removal or weakening, matrix, or parallelism changed. The exact case passed
  20 consecutive runs; all 37 handler cases and the full 378-case two-worker
  `loadfile` suite passed locally. Independent review returned CLEAR with no
  P1/P2.
- Final TUI run `32094496894` passed all five jobs at exact completion SHA
  `99995cc49249996c208646ee972d940c48383119`; the Windows lane passed the
  corrected non-tail fixture under the retained two-worker schedule. Root
  `32094496836`, PG `32094496899`, and MCP `32094496909` also passed at that
  SHA.

## Related Plans

- `docs/plans/2026-08-17-tui-scroll-anchor-test-synchronization-plan.md`
- `docs/plans/2026-08-14-taut-tui-action-route-contract-plan.md`
