# TUI Pre-PR Review Fixes

Date: 2026-07-06
Branch: main (ahead of origin/main by the TUI series)
Owner: maintainer
Source: pre-PR review of the taut TUI series (6 reviewer passes + 2 Codex passes)

## Context

The Textual TUI series (`taut/tui/`, client accessors, watch bridge) passed a
multi-reviewer pre-PR review. The review found one merge-blocker plus a cluster
of correctness, error-handling, and cleanup issues. This plan applies the
confirmed, non-design-call subset and records the deferrals.

## Fixes applied

### F1 — Rich markup crash-loop / injection (BLOCKER)

`taut/tui/widgets/_shared.py`: `TextStatic` extends Textual `Static`, whose
`markup=True` default parses every remote-controlled string as console markup.
A message body of `[/]` raises `MarkupError` at render; because history
re-renders on launch, the TUI crash-loops for that conversation. Well-formed
markup also spoofs separators/notices/links.

Fix: render with `markup=False`, and normalize untrusted text through a single
control-character strip (drop C0 except `\n`/`\t`, C1, DEL) at the widget
boundary. Owner: `TextStatic`. Verification: regression test mounts `[/]` and
`[bold]x[/]` and asserts no crash + literal display.

### F2 — Unhandled read errors crash the app ([TUI-10.4])

`taut/tui/app.py`: `_refresh_conversation` calls `history()`/`who()`/
`channel_threads()` with no guard; a DB-locked `OperationalError` (the
multi-writer scenario taut exists for) or a concurrent-rename `TautError`
crashes the app via `watch_active_target`. `action_init_here` runs
`TautClient.init()` unguarded — the one recovery screen can crash. After a
successful init on an empty project, the stale "no .taut.db here" fatal stays
on screen.

Fix: wrap the conversation read section → banner and early-return; guard
`action_init_here` → `_show_fatal`; on successful bootstrap with no default
channel, show a neutral empty transcript.

### F3 — Own sent messages inflate unread badges

`taut/tui/app.py:_apply_watch_item`: increments `_unread_counts` for any
non-active arrival, including the sender's own echoed message. Fix: skip when
`item.from_id == self.me.member_id`.

### F4 — Sub-thread nav rows never show unread badge

`taut/tui/app.py:_row_label`: the subthread branch returns before the unread
suffix. Fix: append the suffix.

### F5 — `goto inbox` dead + stale member cache on new DMs

`_goto` builds candidates only from `_threads` (spec lists inbox as a goto
target); `_refresh_membership` refreshes threads but not `_members`, so a DM
from a member created after mount renders `unknown` and replying is blocked.
Fix: include inbox in goto; refresh `who()` on membership change.

### F6 — `history()` DM reads not participant-scoped

`taut/client/_messaging.py:history()` does no membership check, so any caller
can read any `dm.*` thread — broader than the prior contract (`log()` rejects
DMs, `read_unread` is membership-scoped). Fix: gate DM reads on membership
(raises `NotFoundError`, matching the unknown-thread path, avoiding existence
leak). TUI reads its own joined DMs, so legit use is unaffected.

### F7 — Cleanups

- Bridge docstring: correct the "at-least-once" overclaim (watcher
  poison-advances after 3 failures) and replace stale `watcher.py:NNN` line
  refs with symbol references.
- Dedup the install hint (single constant shared by `cli.py` and the TUI).
- Move `_format_message_time` to `taut/_format.py`; import from there in
  `cli.py` and the widgets (removes the widget→CLI layering inversion).
- Clear `#status-banner` on successful send and on conversation switch.
- Name responsive thresholds + nav widths as constants; build the too-small
  hint from them.
- Decouple the TUI membership poll from the watcher's 0.5s constant and
  lengthen it (fallback timer; primary trigger is unknown-thread delivery).
- Bound `session_notifications` (session display state only).
- Replace user-reachable `assert self.client is not None` with real guards.

## Deferred (design calls — recorded, not fixed here)

- Per-conversation interleaving lock (backfill vs. watch delivery across
  `await` points). Needs a lock/coalescing design + tests.
- Worker-thread offload of client reads (freeze under slow/large reads).
- `history(limit=N)` tail-read + `_total_count` COUNT storage primitives
  (full-scan today).
- `_seen` set / transcript widget pruning (unbounded over a long session).
- z/t always target the first inline sub-thread (acknowledged v1 stub).
- Unify BINDINGS / keybar / help from one keymap (informational; test-fragile).
- Extract the duplicated sub-thread reply logic into one helper: the two call
  sites (composer banner vs. thread-pane label) diverge on error surface, so a
  safe unify is more involved than the informational finding's value.

## Verification

- `pytest tests/test_tui_app.py tests/test_tui_launch.py tests/test_tui_recovery.py tests/test_tui_responsive.py tests/test_client.py`
- New regression tests for F1–F6.
- `ruff check` + `mypy` on changed files.
