# Taut TUI Specification

Date: 2026-08-12

Status: Active — owner-authorized for implementation 2026-08-13.

## 1. Purpose and Mental Model [TUI-1]

The Taut TUI is the human-first extension over the same workspace that core
and loaded extensions expose to other surfaces. `taut-mcp` is the corresponding
agent-first extension. Neither surface owns a second chat model.

The TUI is a reflection over public domain capabilities, not a graphical
wrapper around command-line arguments. Core owns chat, identity, cursor,
notification, search, and maintenance semantics. A loaded extension owns its
domain semantics. The TUI owns composition, layout, focus, gestures, forms,
and other visual affordances.

When a requested experience needs new meaning rather than a new presentation,
that meaning moves to its domain owner first. In particular:

- a layout breakpoint, focus rail, modal, or target label belongs in the TUI;
- a new meaning of read, unread, presence, thread membership, message target,
  or notification delivery belongs in core and must become available to other
  relevant surfaces, including MCP;
- a new meaning of Summon liveness, ownership, status, or terminal attachment
  belongs in `taut-summon` and its public controller;
- dump snapshot and cursor semantics belong in the persistence contract, not
  in the TUI.

Owner: the separately distributed `taut-tui` extension owns the first-party
TUI composition root and visual interaction contract. Core and each other
extension retain their domain contracts. Boundary: human presentation and host
lifecycle only. Verification: [TUI-13]. Required action: do not implement a
TUI-local substitute when a public domain seam is missing; stop that slice and
add the seam to its owner.

## 2. Composition and Capability Reflection [TUI-2]

### [TUI-2.1] Typed public boundaries

The TUI calls `TautClient`, `TautWatcher`, public value objects, and public
addressing helpers for core work. It calls actor-free `TautClient` class
operations for system work. It calls `SummonController`, `SummonRequest`,
`SummonStatus`, and `SummonInteraction` for Summon work.

It must not:

- import private modules from core or an extension;
- read or write sidecar tables, queues, cursor rows, Summon ledgers, control
  messages, driver state, or provider adapters directly;
- derive direct-message queue names or reconstruct access from member ids;
- invoke a Taut CLI subprocess, parse CLI output, or generate an argparse form;
- inspect command implementation targets or treat command manifests as a
  generic UI schema; or
- duplicate terminal, PTY, dump, doctor, search-provider, or backend logic.

Direct-message discovery uses `TautClient.list_direct_messages()`. Existing
conversation handles remain opaque model values even when diagnostic views can
copy them. Sub-thread origin parsing, when needed for an inline affordance,
uses core's public addressing parser rather than TUI string rules.

### [TUI-2.2] Native action registry

The TUI has one internal registry of semantic actions. Keyboard, conventional
keyboard, mouse, command-palette, and contextual-menu gestures dispatch the
same action objects. One operation must not acquire separate behavior because
it was reached through a different gesture.

Core actions are always registered when their public operation is available.
A first-party extension adds native actions only through a TUI-owned adapter
over that extension's public typed surface. PostgreSQL and search providers
remain transparent substitutions behind core. MCP has no TUI panel merely
because its package is installed. Summon adds native actions because it has a
human-operable public controller.

Version 1 defines no third-party rich-view or TUI-plugin protocol. Unknown
installed `taut.commands` manifests may remain visible in CLI help, but the TUI
does not run them or manufacture generic forms. A general contribution
protocol requires at least two concrete extension cases and a later spec.

### [TUI-2.3] Required version-1 actions

The version-1 action registry contains the following user-visible actions.
Names below are stable test identifiers, not required display labels.

| Action family | Required actions |
|---|---|
| Workspace and identity | `workspace.initialize`, `identity.rejoin`, `identity.show`, `identity.set-name`, `identity.set-persona` |
| Navigation | `conversation.open`, `channel.join`, `channel.leave`, `direct-message.start`, `notifications.open`, `members.open` |
| Channel context | `channel.show-topic`, `channel.set-topic`, `channel.clear-topic`, `channel.rename` |
| Messages | `compose.enter`, `message.send`, `message.reply`, `message.react`, `message.delete` |
| Retrieval | `search.open`, `search.open-result` |
| System | `system.doctor`, `system.dump`, `system.load-help` |
| Application | `command.open`, `help.open`, `application.quit` |
| Summon, when `taut-summon` is importable | `summon.start`, `summon.list`, `summon.status`, `summon.dismiss` |

The selected message is already a native show view; version 1 does not call
`show_message()` merely to reconstruct data already in the transcript model.
Destructive actions require a native confirmation that names the exact target.
The action inventory is executable contract data: a test enumerates every id,
proves it has at least one reachable gesture, and proves every destructive id
has a confirmation path.

## 3. Packaging and Launch [TUI-3]

### [TUI-3.1] Extension distribution boundary

The TUI implementation ships in the separate first-party distribution
`taut-tui`, import package `taut_tui`. Textual is its required terminal
framework and is not a core `taut-chat` runtime dependency. The convenience
extras `taut-chat[tui]` and `taut-chat[all]` install `taut-tui`; they do not
move its implementation or dependency ownership into core.

Normal imports, `taut --version`, root help, ordinary commands, and
`taut tui --help` do not import Textual or initialize TUI state. Only actual
TUI execution loads the framework. Without the extension, `tui` is an ordinary
unknown command and root help does not list it. An incomplete `taut-tui`
installation missing Textual produces one actionable reinstall diagnostic and
no traceback. A broken installed Textual dependency is reported as the actual
import failure, not mislabelled as a missing dependency.

The manifest declares `textual>=8.2.8`, the version selected by the current
retained TUI lock. The retained lock is the supported and tested dependency set;
Taut does not currently claim or run a separate older-Textual compatibility
lane.

### [TUI-3.2] Explicit command

The only version-1 launch is:

```text
taut tui
```

Bare `taut` retains normal command help. There is no implicit TTY dispatch and
no standalone `taut-tui` script.

The TUI accepts the existing `--db`, `--as`, and `--token` root selections
before or after `tui`. It rejects `--json`, `--timestamps`, and `--quiet` as
usage errors because they have no honest meaning for an interactive screen.
Post-verb rejection comes from omitting those options from the TUI manifest;
pre-verb values reach the selected adapter in its command context and are
rejected there before the Textual import.
The installed `taut.commands` manifest owned by `taut-tui` declares ambient
stdio ownership through core's legacy-named `raw_stdio_transport` field.
Terminal preflight therefore checks the process `sys.stdin` and `sys.stdout`
that Textual will own, not injected command-context streams.
Execution requires an interactive input and output terminal. A non-TTY launch
fails before changing terminal mode, opening storage, or starting background
work.

### [TUI-3.3] Startup and bootstrap

On an initialized workspace, startup resolves the acting identity through the
ordinary public client and enters the last session's in-memory default only;
version 1 writes no TUI preference file. On an absent local workspace, the
empty state offers `workspace.initialize` for the resolved local target. On an
unrecognized identity, it offers native join or rejoin flows. Backend,
configuration, permission, and malformed-target failures do not masquerade as
an uninitialized local workspace.

Public empty-result exceptions from channel, DM, notification, or search
queries are ordinary empty views, not application failures. They render their
specific empty state and preserve the current mode.

Secrets such as continuity tokens use masked fields, never appear in status,
logs, screenshots, or diagnostics, and are cleared from the form after the
operation completes or is cancelled.

## 4. Runtime and Session State [TUI-4]

### [TUI-4.1] Process model

The Textual event loop owns widgets, focus, rendering, and the session model.
It performs no broker, sidecar, search, doctor, dump, control-plane, or process
operation directly.

One serialized session worker owns each identity-bearing `TautClient` it
constructs. Watchers own their public independent runtime. Actor-free system
operations use bounded background workers. Each TUI-started Summon driver has
one explicitly supervised blocking worker under [TUI-11]. Worker results are
marshalled into the UI loop with generation ids so a stale completion cannot
replace newer selection or search state.

No TUI worker is a user-managed daemon. Normal shutdown stops and joins owned
watchers, restores any logging and terminal state, and resolves every active
TUI-owned operation according to this spec. Abrupt process or OS termination
follows the underlying operation's existing crash and atomic-file contracts;
the TUI makes no stronger promise.

### [TUI-4.2] Session-only visual state

Focus, open overlays, pane choice, selections, scroll anchors, folded display
groups, search/command input, bounded notification presentation, and drafts are
session-only visual state. They are not chat semantics and are not persisted in
version 1. Drafts are keyed by public conversation target and remain intact
across focus changes, conversation switches, resize, and recoverable errors.

The TUI maintains no second durable or session-only read cursor and no shadow
definition of unread. It displays the `Thread` unread fields and lets public
read/watcher operations move core cursors. Resize, reflow, focus, selection,
history backfill, and search never move a cursor.

### [TUI-4.3] Modes

Exactly four interaction modes are visible in the status line:

- `NORMAL`: navigate, select, open, and invoke actions;
- `COMPOSE`: edit the single-line, target-labelled message composer;
- `COMMAND`: search the native action registry;
- `SEARCH`: search visible Taut history through `TautClient.search()`.

Modal forms are owned transient surfaces layered on these modes. A mode change
must not silently submit, clear a draft, consume a notification, or advance a
cursor.

## 5. Information Architecture and Visual Direction [TUI-5]

### [TUI-5.1] Three logical surfaces

The stable logical structure is:

1. **Navigation:** joined channels, direct messages, unread state, inbox, and
   entry points to join/start flows.
2. **Conversation:** target header, transcript, selected-message affordances,
   and target-labelled composer.
3. **Inspector:** context for the current selection, such as a reply thread,
   members/presence, message actions, system report, or Summon status.

These are logical surfaces, not a promise that three columns are always
visible. [TUI-9] governs their physical placement.

### [TUI-5.2] Terminal-native visual language

The default view is transcript-first and low-chrome. It uses terminal
background and primary text, one muted text role, one restrained accent, and
distinct warning/error roles. Color is never the only carrier of focus,
selection, unread, status, or error.

Focus is shown with one structural rail or equivalent one-cell marker. Panels
do not use dense boxes or filled dashboard cards. The TUI defines its own
semantic Textual theme and component styles; the framework's default theme is
not the product design system.

The footer contains mode, active target, background-operation state, and only
the small set of actions relevant to the current focus. It is not an exhaustive
permanent keybar. `help.open` owns the complete discoverable gesture list.

### [TUI-5.3] Transcript rows

At wide and medium widths, ordinary messages use aligned timestamp and author
metadata with a hanging body indent. At compact widths, metadata stacks above
the body. Notices, warnings, unread boundaries, selected messages, and thread
origins remain structurally distinct without relying on color.

Direct messages use actor-scoped human labels. Internal queue names never
replace those labels in ordinary navigation. The composer always shows the
exact public target label so a send cannot be mistaken for a different channel,
DM, or reply thread.

## 6. Conversation, Read, and Live Semantics [TUI-6]

### [TUI-6.1] Opening a conversation

Navigation is assembled from public joined thread names, public thread
projections, and `list_direct_messages()`. Opening a top-level conversation:

1. stops and boundedly joins the previous filtered watcher before making the
   previous target inactive;
2. obtains cursor-neutral bounded history with `log()` and commits it to the
   session model;
3. starts one `TautWatcher` filtered to the active conversation and any reply
   thread currently open in the inspector; and
4. accepts watcher messages synchronously into the UI model before the handler
   returns, preserving the watcher's core cursor ordering.

The active-filter rule is deliberate: inactive conversations remain unread.
A target switch does not create an all-joined watcher. An explicit sub-thread
open may use core's public read operation to perform the existing implicit
membership/read transition before adding that target to the filtered watcher.

Switches are serialized and latest-selection-wins. A stale history, watcher,
presence, or search completion cannot replace the current target. A watcher
that cannot stop within its bounded shutdown budget is a visible degraded
state and blocks creation of a second watcher for the same session.

### [TUI-6.2] Live delivery and notifications

Live chat delivery uses the public watcher and inherits its handler-before-
cursor-advance rule, retry bound, dynamic membership checks, and stop behavior.
The TUI does not acknowledge a message that it rejected during shutdown or
could not commit to its model.

Every public Taut watcher also claims the acting member's notification queue.
The TUI therefore shows claimed notifications in an inbox surface and a
bounded session feed. It states in help that notification pointers are
consumable and shared by sessions, while chat history remains durable. A
notification render failure is best-effort after claim and never fabricates a
re-delivery guarantee.

### [TUI-6.3] Compose and message actions

`message.send` calls `say()` with the labelled public target. `message.reply`
calls `reply()` with the selected message's full id and parent conversation.
The draft clears only after a successful returned message is committed to the
model. A blank draft is a no-op under core's blank-message contract.

Starting a new direct message selects a public member and sends the first
message through the public `@route` target; existing DMs reopen through their
stable public handle. Message reaction and deletion use the selected full
message id. Deletion and channel leave/rename require exact-target
confirmation. The TUI never guesses a reply suffix, DM queue name, reaction
vocabulary, or authorization rule.

### [TUI-6.4] Search, presence, and reply threads

Search is cursor-neutral and uses the public search result contract. Opening a
result selects its public conversation and calls core's cursor-neutral
`history_around()` seam to anchor the matching message with bounded context,
without turning search into a second transcript store.

The members inspector uses `who()` and displays the returned chat presence as
chat presence. Summoned-driver status is separate and labelled as live
controller status; neither value substitutes for the other.

Registered sub-threads appear as contextual markers at their origin message.
Their replies are not silently expanded with cursor-neutral `log()` in the
main channel. Opening one makes it an explicit reading surface in the
inspector. Adding or removing that surface stops and joins the current watcher,
then creates a replacement with the complete new explicit filter. The TUI does
not mutate a live watcher's private or inherited queue topology. Closing the
reply surface changes no cursor by itself.

## 7. Native Command and Form Behavior [TUI-7]

### [TUI-7.1] Command palette

`COMMAND` mode is a fuzzy/searchable palette over currently applicable native
actions. Results show a human label, target or scope where relevant, and the
conventional and vi-like gesture when one exists. Disabled actions state the
reason. Selecting an action either performs it or opens its native form.

The palette is not a shell, accepts no arbitrary argv, does not interpolate
text into a command line, and never invokes `taut` as a subprocess.

### [TUI-7.2] Forms and validation

Forms use labelled fields, explicit submit/cancel actions, core validation,
and inline domain errors. Mouse click, Tab, and Shift-Tab can focus every
field. Enter activates the focused button or single-line field action; Escape
cancels without mutation.

The TUI may preflight display-only conditions such as an empty required field
or an existing dump output path. Domain validation and race decisions remain
with the public operation. A successful domain result is never downgraded by a
later toast, notification, focus, or animation failure.

## 8. Keyboard and Mouse Interaction [TUI-8]

### [TUI-8.1] Vi-like, not vi-only

In `NORMAL` mode the following pairs dispatch the same semantic actions:

| Semantic action | Vi-like gesture | Conventional equivalent |
|---|---|---|
| Previous/next item or line | `k` / `j` | Up / Down |
| Previous/next visible surface | `h` / `l` | Left / Right |
| First/last item | `gg` / `G` | Home / End |
| Page up/down | Ctrl-U / Ctrl-D | PageUp / PageDown |
| Enter compose | `i` | Tab or click to composer; palette `Compose` |
| Activate/open | Enter | Enter |
| Leave transient mode | Escape | Escape |
| Open command palette | `:` | Ctrl-P or clickable command affordance |
| Search history | `/` | Ctrl-F or clickable search affordance |
| Open help | `?` | F1 or clickable help affordance |
| Quit | `q` | Ctrl-Q or palette `Quit` |

Tab and Shift-Tab always move among focusable visible surfaces or form fields.
Bindings that would insert text are disabled outside `NORMAL`; for example,
typing `q`, `i`, `:`, or `/` in a text field edits text rather than invoking a
global action. Escape has priority for leaving `COMPOSE`, `COMMAND`, `SEARCH`,
or a modal.

Inbox is not bound to bare `i`; it is available from navigation, the command
palette, and the optional `g i` normal-mode sequence. Mode and focus are always
visible, so a key does not depend on invisible state.

### [TUI-8.2] Mouse

Mouse use is optional and never the sole route to an action. A single click
focuses a pane or field and selects the clicked row/message. A double click or
single click on an explicit action control activates where Textual can report
it reliably. The scroll wheel scrolls the surface under the pointer. Clicking
the composer focuses it and positions the editing cursor when the terminal and
framework expose a position.

There is no hover-only information or action. Help documents the terminal's
modified-drag escape for native text selection (commonly Shift-drag), and the
TUI must not deliberately disable that terminal escape. Mouse and keyboard
parity tests exercise the same action ids and resulting model changes.

## 9. Reflow and Terminal Resize [TUI-9]

### [TUI-9.1] Exact layout modes

Version 1 uses these tested thresholds:

| Mode | Terminal size | Physical arrangement |
|---|---|---|
| `wide` | width at least 120 and height at least 20 | navigation, conversation, and inspector visible |
| `medium` | width 80–119 and height at least 20 | conversation plus one side surface; navigation is default and inspector replaces it when opened |
| `compact` | width 50–79 and height at least 20 | one logical surface at a time; conversation is default |
| `too-small` | width below 50 or height below 20 | clear resize hint; content surfaces hidden but session state retained |

Compact mode never compresses navigation labels into a glyph strip or a
fixed eight-column pane. A header/tab/goto affordance changes the one visible
surface. No supported intermediate size may overlap panes, render labels one
character per line, hide the active target, or make the composer unreachable.

### [TUI-9.2] State preservation

Reflow preserves:

- active conversation and open reply thread;
- selected navigation row and selected message;
- per-target drafts and cursor position;
- command/search input and current mode when that mode remains operable;
- inspector kind and its selected item;
- whether the transcript was pinned to the live tail; and
- otherwise, the first visible message id and its intra-row offset as the
  scroll anchor.

When wrapping changes, a tail-pinned view remains tail-pinned. A history view
restores the same anchor message instead of jumping to newest content. If a
wider layout makes the retained intra-row offset longer than that message's
new wrapped height, the offset clamps to its last rendered row so the next
message cannot replace the anchor.

If the focused widget remains visible, it keeps focus. If reflow hides it,
focus moves deterministically to the same logical surface in its new physical
location; if that surface is unavailable in `too-small`, focus moves to the
resize hint and returns to the prior logical surface when space recovers.

### [TUI-9.3] Resize processing

Resize handling is pure presentation over current view models. It does not
open storage, fetch history, restart a watcher, consume a notification, send a
message, move a cursor, or create one task per resize event.

Rapid resize is coalesced or processed synchronously as latest-wins. After a
burst, the rendered mode matches the latest terminal size and no obsolete
layout task remains. Live watcher and operation results continue to enter the
session model while `too-small`; they become visible when a usable size
returns.

Tests drive transitions in both directions across every exact boundary,
including a rapid burst, while a draft, non-tail scroll anchor, selected
message, open inspector, and live delivery exist.

## 10. System Operations [TUI-10]

### [TUI-10.1] Doctor

`system.doctor` runs the public actor-free doctor operation in a background
worker and renders the fixed typed checks as a native report. It does not
construct a chat actor, parse CLI text, repair state, or describe a passing
report as a quiescence or dump-safety certificate. Rerun is an explicit action.

### [TUI-10.2] Dump

`system.dump` opens a native output-path form, confirms replacement when the
selected path currently exists, and runs `TautClient.dump()` in a background
worker. It shows indeterminate activity rather than a fabricated percentage,
then renders the typed receipt.

This spec does not define dump watermark, snapshot, cursor, or concurrent
writer semantics. Those come entirely from the active persistence contract.
The TUI dump slice must not ship until the separately owned point-in-time dump
contract is active. The TUI does not add a quiescence proof or process census.

A normal quit request while a dump is running leaves the application open and
explains that the operation must finish. The underlying atomic replacement
contract owns abrupt-termination file safety.

### [TUI-10.3] Load stays CLI-only

The TUI never executes `TautClient.load()` and never invokes `taut system load`.
`system.load-help` is informational: it explains that restore is a deliberate
CLI maintenance operation and shows the exact command shape for the selected
workspace and user-supplied input path. It does not preflight, inspect, or
modify the destination.

## 11. Summon Integration [TUI-11]

### [TUI-11.1] Availability and native flows

When the public `taut_summon` facade imports successfully, the TUI registers
native start, list, status, and dismiss actions. When it is absent, those
actions are absent from ordinary results; optional-extension help may show one
install hint without importing private modules.

The start form obtains provider names from `provider_names()` and constructs a
typed `SummonRequest`. It exposes name, conversations, provider, persona,
system-prompt file, rate limit, terminal, attach/detach, and takeover without
reusing the CLI parser; the selected provider populates `provider_flag`.
Status calls the controller and displays correlated live status. Dismiss calls
confirmed `stop()`. Chat member presence and live
driver status are separate labelled observations.

### [TUI-11.2] Driver ownership and shutdown

Each TUI-started foreground run executes
`SummonController.run_foreground(..., install_signal_handlers=False,
on_ready=...)` on one supervised non-daemon worker. The optional public
readiness callback is owned by the coordinated proposed Summon rich-host
contract delta in this spec's implementation plan. It reports a run-scoped
`SummonRunHandle` only after the first live generation's control plane can
accept public status and stop operations from another thread. The handle
contains the actual `SummonedMember` and an idempotent nonblocking stop request
bound to that exact run. The TUI never infers ownership by diffing `list_live()`
or by matching a requested or remembered name.

The TUI records the worker as pending-owned before it starts. The readiness
callback synchronously replaces that pending record with the exact run handle
in a thread-safe registry keyed by a unique worker token, before posting any
display update. Worker return atomically retires either form. A late display
message for an already retired token is a no-op. Normal exit remains blocked
while a worker is pending because an auto-renamed live member does not yet have
an exact run handle. Callback and worker-return races cannot resurrect a stale
ownership record.

Summon retains driver, control, PTY, child, and release ownership. The TUI does
not install Summon's process signal handlers.

An externally started live driver is observable and dismissible but is not
TUI-owned. Normal TUI exit never stops such a driver automatically.

Normal exit with TUI-owned live drivers requires a decision. Cancel keeps the
TUI open. Confirmed exit calls `request_stop()` on each owned run handle and
waits for each retained foreground worker to return after its normal teardown
and evidence-owned release. If any worker remains live or returns an error,
exit is cancelled and the exact members and public errors remain visible.
Externally started drivers have no TUI-owned run handle and are never included.
Version 1 has no “leave TUI-owned driver running” choice because the blocking
controller has no detached ownership transfer.

### [TUI-11.3] Terminal handoff

The TUI supplies a cooperative `SummonInteraction`. It reports terminal
availability without changing terminal state. It reports `AVAILABLE` only
when both standard streams are suitable, no other lease is active, and the
framework can suspend safely.

For one terminal lease, the interaction marshals a handshake to the UI loop,
where one handler enters Textual's supported synchronous `App.suspend()`
context and remains inside it while waiting on a thread-safe release event. The
Textual event loop is intentionally paused for the lease; it does not keep
processing or rendering a suspended app. After suspension succeeds, the
handler signals acquisition to the Summon worker, which receives only input fd
0 and output fd 1 and owns byte-transparent PTY attachment. The worker signals
release in its context-manager `finally`; the same UI handler exits
`App.suspend()`, restores the terminal, forces a complete redraw, restores
logical focus/mode/draft state, and signals restoration complete. Lease
acquisition or restoration failure is fatal to that foreground run and visible
after safe restoration; it never falls through to concurrent terminal
ownership.

### [TUI-11.4] Log routing

While Summon support is loaded, the TUI installs one scoped logging handler for
records in the `taut_summon` logger namespace. The handler escapes Taut-owned
display text, places bounded diagnostics in the TUI, does not write through
the active full-screen terminal, and buffers display updates during a terminal
lease. It does not modify the root logger. The TUI saves and restores the
namespace logger's prior handlers, level, and propagation state on every exit,
including startup and Summon failures.

## 12. Failure, Safety, and Cleanup [TUI-12]

### [TUI-12.1] Error priority

Usage, missing-extra, non-TTY, startup, domain, worker, and controller failures
produce concise TUI or pre-screen diagnostics with no traceback. Once the
screen is active, recoverable failures stay attached to their action or target
and preserve drafts and selection.

A primary domain failure wins over cleanup, toast, focus, logging, or redraw
failure. A successful domain mutation remains successful even if an auxiliary
presentation update fails; the TUI refreshes from public state and reports the
presentation failure separately.

### [TUI-12.2] Terminal text and untrusted content

Message bodies, names, topics, personas, diagnostics, extension logs, paths,
and foreign envelopes are untrusted terminal text. Widgets render them as text
or through core's public escape policy and never as markup. Raw bytes exist
only inside the scoped Summon terminal lease.

### [TUI-12.3] Cleanup order

Normal shutdown stops accepting new actions, resolves active dump and owned
Summon exit gates, stops watchers before closing their session owners, joins
owned workers within named budgets, restores Summon logging, restores terminal
state, and then exits. Cleanup is idempotent. A cleanup error is reported but
does not replace a prior primary error.

## 13. Verification Expectations [TUI-13]

### [TUI-13.1] Real boundaries

Acceptance tests use Textual's real test application/pilot, real SQLite
storage, real `TautClient`, and real `TautWatcher`. PostgreSQL receives a
focused real-backend smoke for navigation, send, search, and system report.
Summon lifecycle proof uses the public controller with a real scripted child,
real control exchange, real worker ownership, and a fake terminal that models
the public lease boundary. Tests must not mock broker reads/writes, cursor
advancement, client routing, watcher acknowledgment, controller status/stop,
or the terminal lease state machine under test.

Pure layout calculations, clocks, terminal size events, Textual pilot input,
external provider behavior, and OS fd adapters may use narrow fakes.

### [TUI-13.2] Required matrices

The following enumerable matrices have firing tests:

- all action ids in [TUI-2.3], including destructive confirmation;
- every gesture/equivalent row in [TUI-8.1] and mouse parity in [TUI-8.2];
- width boundaries 49/50, 79/80, 119/120 and height boundaries 19/20;
- wide to medium to compact to too-small and reverse reflow with the preserved
  state named in [TUI-9.2];
- rapid resize plus concurrent live delivery and stale worker completion;
- absent extension, incomplete/broken extension dependency, non-TTY,
  help/version lazy-import floors, and source-tree plus paired core/TUI
  installed-wheel launch against the retained TUI lock; there is no separate
  exact-floor dependency lane;
- active-only cursor advancement, inactive unread retention, watcher switch
  ordering, notification claim presentation, and shutdown non-acknowledgment;
- doctor pass/findings/framework error, dump success/replacement/failure/quit
  gate, and load-help non-execution;
- Summon absent/present, start/status/dismiss, external versus owned exit,
  pending startup, actual-name readiness after auto-rename, one readiness over
  provider resume, post-readiness rename, readiness/worker return races,
  run-scoped stop, failed stop/return, terminal availability/lease/restore,
  logging restoration, and host signal non-ownership; and
- terminal-control payloads in every user/extension text-bearing widget.

Representative wide, medium, compact, and too-small screens receive a manual
visual review against [TUI-5] in addition to structural tests. Any committed
golden artifact has a documented regeneration command and is reviewed as a
behavior delta, not as a substitute for semantic assertions.

### [TUI-13.3] Adversarial acceptance floor

The shipped `taut tui` entry point is probed for missing/broken dependencies,
missing and malformed targets, non-TTY streams, terminal setup failure,
unwritable dump output, malformed child/log text, closed output, and worker
failure. Each applicable case has an honest error class, no traceback, no
terminal-state leak, and no partial domain result invented by the TUI.

## 14. Explicitly Out of Scope [TUI-14]

Version 1 does not include:

- dump semantic changes or persistence load execution;
- a generic renderer for argparse or installed command manifests;
- a public third-party TUI widget/plugin protocol;
- a PostgreSQL, MCP, search-provider, or persistence-component inventory
  dashboard;
- a daemon, detached TUI service, background tray process, or driver ownership
  transfer;
- durable drafts, layout preferences, key remapping, themes, or per-device
  notification state;
- multiline message composition;
- a new definition of read/unread, viewport-seen cursors, presence, or
  notification delivery; or
- a direct port of the historical PR implementation.

## Related Plans

- `docs/plans/2026-08-12-taut-tui-implementation-plan.md`: staged
  implementation, hardening, verification, and review plan.

## Implementation

- `docs/implementation/12-taut-tui.md`: runtime ownership, native action and
  form composition, responsive state, system boundary, and Summon terminal
  handoff rationale.

## Non-Normative Design Provenance

The historical TUI at commit `b1a599a565882a2122b57b3c362e69aecd6c5b80`
is an archaeological input only. Its transcript-first three-surface direction,
target label, focus rail, and restrained terminal palette informed [TUI-5].
Its old API bridge, all-thread watch behavior, permanent keybar, compressed
narrow navigation, and version-specific state model are not implementation
baselines.
