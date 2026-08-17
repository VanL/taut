# TUI Scroll-Anchor Test Synchronization Plan

Date: 2026-08-17

Class: 4. This changes an async test-observation lifecycle at the deferred
Textual refresh boundary after a hosted release gate exposed a false failure.

Status: active.

## Goal

Make the real viewport-reflow test observe completion of the exact anchor
restore caused by the final resize. Time remains only a missing-callback cap;
the test keeps every message-id and offset assertion and does not change TUI
production behavior.

## Source Documents and Spec Baseline

Source specs:

- `docs/specs/10-taut-tui.md` [TUI-9.2], [TUI-9.3]
- `docs/implementation/12-taut-tui.md`, Responsive Presentation

Baseline:

- `9447ce7b24276e1e13b4ff2e6fc8a9beae4cac9f` — the source spec and
  implementation note above at plan authoring time. This plan does not revise
  the product contract.

## Context, Ownership, and Classification

- `TautApp.on_resize()` records the logical anchor, applies the latest layout,
  and schedules `_render_latest_resize()` after refresh.
- `_render_messages()` then schedules `_restore_transcript_anchor()` after a
  further refresh. The hosted macOS failure captured scroll state after one
  generic `pilot.pause()`, before that exact nested callback had completed.
- The failed assertion observed the successor message, while all other TUI
  platforms passed. This is provisionally a test synchronization defect. If an
  exact callback observer completes and the anchor still differs, stop and
  reopen the classification as an application failure.
- `extensions/taut_tui/tests/test_tui_app.py` owns the real-app proof. No
  production file should change.

## Required Reading and Comprehension Gate

Read [TUI-9.2], [TUI-9.3], the architecture's Responsive Presentation section,
`on_resize()`, `_render_messages()`, `_restore_transcript_anchor()`, and the
complete failing test.

1. What completes the behavior under test? Expected answer: the final resize's
   exact `_restore_transcript_anchor()` call plus the following Textual refresh,
   not an arbitrary event-loop turn.
2. What may time control? Expected answer: only a bounded failure when the exact
   callback never completes; elapsed time may never establish success.

Incorrect or missing answers block implementation until the owner text is
reread.

## Invariants, Hidden Couplings, and Stop Gates

- Keep real Textual, real SQLite, 30 real messages, both resize directions,
  compact-pane interaction, deep intra-row offset, and exact message-id/offset
  assertions.
- Install the observer before the final resize. Delegate to the real restore
  method, match the expected anchor message, and signal only after the next
  refresh. A stale or unrelated callback cannot satisfy the event.
- The five-second wait is only a missing-callback/deadlock cap. An exception,
  wrong anchor, or wrong offset remains an immediate failure.
- Do not change production code, timeout policy, message count, assertions,
  matrix coverage, parallelism, or retained Textual lock.
- Stop if the exact callback fires but state is wrong, or if success requires
  polling, sleeps, private event-loop timing, or a production hook.
- The observer must not replace the real method or mock layout/scroll behavior.

## Rollback, One-Way Door, and Success Signal

- The test-only observer is independently reversible; no persistent or public
  state changes.
- Release tag publication is the only one-way door. Require a fresh exact-SHA
  full TUI matrix, including macOS, before tagging.
- Success is the focused real test passing repeatedly locally and the complete
  canonical hosted TUI matrix passing unchanged at the landing SHA.

## Verification

1. Run the focused real viewport test repeatedly and the full TUI suite.
2. Run repository-wide Ruff, TUI mypy, documentation checks, and diff checks.
3. Obtain an independent completed-work review.
4. Commit and push a fresh SHA; require root, PG, MCP, and TUI producer success
   before the normal release helper may push tags.

## Deviation Log

| Spec ref | Planned behavior | Actual behavior | Rationale | Spec proposal |
|----------|------------------|-----------------|-----------|---------------|

## Execution Log

- Pre-edit comprehension: (1) the exact final anchor-restore callback and its
  following refresh complete the behavior; (2) time is only the missing-event
  cap and never the success condition.
- Release-SHA run `32044233342`, macOS Python 3.13, failed after one generic
  pause captured the successor message. The other four TUI matrix jobs passed.
- The event-based real-app test passed 10 consecutive focused runs, then the
  complete retained-lock TUI suite passed all 322 tests locally.

## Related Plans

- `docs/plans/2026-08-17-tui-command-mirror-plan.md`
- `docs/plans/2026-08-14-windows-postrelease-ci-determinism-plan.md`
