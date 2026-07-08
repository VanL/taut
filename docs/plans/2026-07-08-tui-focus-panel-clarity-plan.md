# TUI Focus Panel Clarity Plan

Date: 2026-07-08
Owner: maintainer
Spec: `docs/specs/04-taut-tui.md` [TUI-8.1], [TUI-8.4]
Status: implemented

## Context

The TUI has deterministic keyboard focus, but the visible focus treatment is
inconsistent. Grey panels can show a subtle background shade difference, black
panes do not, and the composer input gets a control-level outline while the
other focusable panes do not get an equally obvious pane marker.

The spec requires exactly one focused pane at a time, that the focused pane is
visually obvious, and that focused controls/selected rows are distinguishable
without relying on color alone.

## Design Intent

Focus should be a quiet operational affordance, not decorative chrome. A user
should be able to scan the layout and immediately see which pane will receive
keyboard actions.

Use one consistent structural marker for pane focus:

- navigation, transcript, presence, inbox, composer, and thread pane should use
  the same pane-level focus treatment;
- text inputs may keep their native cursor/control styling, but composer focus
  must also mark the containing composer pane;
- the marker must work on both grey and black panels;
- pane text must sit inside the marker, not visually outside a tight outline;
- the marker must not change focus order, active target, command semantics, or
  persisted state.

## Implementation Plan

1. Add CSS focus rules in `taut/tui/app.py` for focusable pane surfaces:
   `#navigation`, `#transcript`, `#presence`, `#inbox-view`, `#composer`, and
   `#thread-pane`.
2. Use a structural non-color-only left focus rail. The unfocused state must
   reserve the same left border column and padding so focus changes do not shift
   layout and text remains inside the pane marker.
3. Use `:focus` for directly focusable panes and `:focus-within` for panes
   whose child input owns focus (`#composer`, `#thread-pane`).
4. Add regression tests in `tests/test_tui_app.py` that tab/focus movement gives
   the focused pane a non-default structural rail, including transcript and
   composer, and that unfocused panes retain the reserved rail/padding.
5. Keep Escape/unfocus behavior out of scope for this slice.

## Verification

Run:

```bash
uv run --extra dev pytest tests/test_tui_app.py tests/test_tui_responsive.py
uv run --extra dev ruff check taut/tui/app.py tests/test_tui_app.py
git diff --check
```

## Rollback

Revert the implementation commit. This changes only TUI presentation and tests.
