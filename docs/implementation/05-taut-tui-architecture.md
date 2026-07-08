# Taut TUI Architecture

Governing specs: `docs/specs/04-taut-tui.md` (all `[TUI-*]` sections),
`docs/specs/02-taut-core.md` [TAUT-8.4], [TAUT-12.4].
Implementing plan: `docs/plans/2026-07-02-taut-tui-implementation-plan.md`
(four review rounds plus per-slice reviews; see its `## Review Log`).
First-join extension:
`docs/plans/2026-07-07-tui-first-join-flow-plan.md` ([TUI-10.9],
[IAN-3.3]).

This doc explains why the TUI is shaped the way it is — the boundaries,
the threading contract, and the tradeoffs. The how lives in the code.

## Ownership and boundary

`taut/tui/` is a **pure consumer** of `TautClient` and `TautClient.watch()`
([TUI-4.2]). It contains no address or identity resolution, no envelope or
SQL work, no cursor advancement, and no notification consumption logic —
those live in the client and watch runtime. When the TUI needed data the
client could not express, the client grew first (plan Task 2: four
read-only accessors — `joined_threads()`, `read_cursor()`,
`channel_threads()`, `history()`), never the UI. The standing grep gates in
`04-taut-architecture.md` §Verification enforce this boundary and must stay
at zero hits.

Textual is quarantined behind the `taut[tui]` extra (INV-5) and imported at
exactly one lazy point: inside `run_tui()` (`taut/tui/__init__.py`).
`taut/tui/_launch.py` and `taut/tui/_bridge.py` import without Textual so
launch decisions and the threading contract are testable without the
framework. A missing `textual` module becomes `MissingTuiExtraError` (never
a plain ImportError catch — a broken-but-installed Textual must surface as
a real error, not an install hint).

## Launch dispatch (`taut/cli.py` + `taut/tui/_launch.py`)

Bare `taut` (or no-verb with only `--db/--as/--token`, either spelling)
launches the TUI when stdin AND stdout are TTYs; anything else prints help
and exits 1, so agents and pipelines never hang ([TUI-5.3]). The decision
(`_launch.decide`) is a pure function over the argparse namespace `main()`
already holds — there is deliberately no second argv parser; equals-form
support comes from argparse via `_hoist_global_options`, proven once.

## The watch bridge (`taut/tui/_bridge.py`)

The riskiest seam. The watch runtime advances a chat cursor immediately
after the handler returns (`taut/watcher.py:642`), which forces the
acknowledgment contract:

- **Messages** hand off synchronously (`App.call_from_thread`) and let
  exceptions propagate — a failed UI update leaves the cursor unmoved and
  the message is redelivered. The app registers its display-dedup key only
  *after* the UI accepts the item; registering earlier swallows the retry
  as a duplicate (Task 4 slice-review finding).
- **Notifications** are consumed by the runtime's READ-mode queue before
  the UI ever sees them; display is best-effort and render failures are
  logged, never raised. The inbox view renders only watch-accumulated
  notifications — calling `client.inbox()` while the watcher runs would be
  a second consumer racing the same queue.
- **Shutdown** sets the watcher stop event *first*, then the `stopping`
  flag, then joins with a bounded timeout from an executor thread (never
  the UI loop a pending hand-off may be waiting on). A message caught in
  the shutdown window raises `ShutdownNonAck` — unacked, redelivered next
  session — and the stop-event-first ordering is what keeps repeated
  raises from reaching the 3-strikes poison advance. Do not reorder.

The bridge holds a strong reference to the thread `run_in_thread()`
returns; the base watcher only keeps a weakref, so `stop(join=...)` can
only join what someone still references.

## Watch-delivered read semantics ([TUI-10.8]) — the load-bearing tradeoff

A running TUI is a watch session: every delivery marks that message seen
for the acting member, including background conversations and the launch
backlog. This was an explicit maintainer decision (2026-07-03, "Option A"
in the plan's round-3 review), consistent with `taut watch`, and it has a
consequence users must know: **unread state does not survive a TUI
session** — after quitting, `taut list` reports everything delivered as
read, even for channels never opened on screen, and cursor advancement is
forward-only so this is not recoverable per-message.

The UI compensates in-session: per-thread cursors are snapshotted once at
mount, strictly before the watcher starts; every `── new messages ──`
separator anchors on that snapshot for the whole session, and unread
badges are session display state (seeded from stored counts, incremented
only for arrivals newer than the mount high-water mark, cleared on view).
This bookkeeping is the one sanctioned exception to "no separate state"
(INV-10) and is never written back as a cursor. The Slack-style
alternative — a delivered-versus-viewed cursor split — is a core-spec
revision and is explicitly out of scope for the first TUI.

## Responsive thresholds ([TUI-9])

wide ≥120 cols; medium 80–119 (presence behind the `m` toggle); narrow
50–79 (navigation rail); too-small below 50 cols or 20 rows. The
structural modes are the contract; the numbers are tunable and live in
`TautApp._compute_mode`. Mode changes reset the members-toggle override;
the thread pane always wins the presence column.

## Recovery model ([TUI-10])

The client is constructed *inside* the App: `TautClient.__init__` raises
`NotInitializedError` before a frame could otherwise exist, so `run_tui`
must not build it eagerly. The uninitialized empty state offers an
Enter-bound init-here action that calls the `TautClient.init` classmethod
(the same path as `taut init`) and then re-bootstraps.

First-join setup ([TUI-10.9]) is the one v1 exception to "setup stays
CLI-first." If the identity read raises the typed
`UnrecognizedCallerError`, or an explicit `--as NAME` read raises
member-not-found, the app opens a modal name/channel form before any
`WatchBridge` exists. The form validates with the same client-owned
validators as the CLI and submits by constructing a one-shot
`TautClient(..., as_name=name).join(channel)`, then discards that client
and re-runs normal bootstrap as the new member. It does not write identity
or membership state directly and does not fabricate optimistic transcript
rows.

The first-join branch is deliberately scoped to `whoami()`. Errors from
`joined_threads()` are not setup triggers, because they can represent
unrelated project or membership failures after identity is known. Other
identity failures, including claim conflicts and token-shaped problems,
leave the form and show CLI-first guidance such as `taut rejoin NAME` or
`taut --as NAME join CHANNEL`. The modal gate blocks normal TUI surfaces
(`c`, `/`, `g`, `i`, `?`, pane toggles) and hides navigation so Tab cannot
leave the form, while keeping Escape and quit live; Escape cleans the form
and returns to the identity-guidance state.

Membership loss surfaces with CLI-first guidance (`taut join …`);
membership loss disables the conversation and keeps history.

## Testing posture

All behavior tests drive the real `App` under Textual's `Pilot` against a
real `.taut.db` seeded through `TautClient`; live tests run a real
`TautWatcher`. The broker, client, and watcher are never mocked; only
failure injection (a raising deliver/widget) and tty predicates are
patched. Import-boundary proofs run in subprocesses because an in-process
`sys.modules` check is order-dependent under xdist. TUI test modules
guard with `pytest.importorskip("textual")`; the release gates run with
`--extra dev` plus explicit TUI test files so a skip can never pass as
green.
