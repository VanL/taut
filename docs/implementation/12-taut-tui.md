# Taut TUI Architecture

## Purpose and Governing Contract

The TUI is Taut's human-first reflection over core and loaded first-party
extensions. It is not a second chat model and does not derive behavior from
the CLI parser. `docs/specs/10-taut-tui.md` [TUI-1] through [TUI-14] governs
the surface; `docs/plans/2026-08-12-taut-tui-implementation-plan.md` records
the staged implementation and verification decisions.

The separately distributed extension lives in
`extensions/taut_tui/taut_tui/`. Its installed `taut.commands` manifest
declares ambient stdio ownership and imports the TUI only after rejecting
incompatible globals and proving that process stdin and stdout are terminals.
Core contains no TUI implementation or command adapter. Importing `taut`,
asking for root help, or asking for `taut tui --help` does not import Textual.
Without `taut-tui` installed, `tui` is an ordinary unknown command.

## Ownership Model

The Textual thread owns widgets and `VisualState`. It never performs storage,
search, doctor, dump, controller, or child-process work. `TuiSession` owns one
persistent identity-bearing `TautClient` on one serialized worker. The active
`TautWatcher` retains its independent owner thread. `TuiSystemOperations`
uses one actor-free worker; `TuiSummonOperations` retains one foreground
worker per TUI-started Summon run plus one bounded exit supervisor.

Conversation selection uses monotonically increasing generations. A switch
stops and joins the old filtered watcher, loads bounded public history,
commits only the current generation, then starts a watcher filtered to the
active conversation and explicit reply surface. The synchronous watcher
callback commits a message to the UI model before returning. If shutdown or a
newer selection rejects the commit, it raises public `WatcherRejected`; core
translates that at the broker boundary so the rejected message does not
advance the cursor or accumulate poison retries.

The same intent token crosses search-context and deletion-refresh work, so a
late worker cannot commit after a newer target selection. Sends use independent
tokens rather than one global pending slot; each completion may clear only the
same target draft revision it submitted. This matters when a user sends twice
or edits again before the first worker returns.

Notifications differ on purpose. Every public watcher already claims the
member notification queue, so the TUI stores those pointers in a bounded
session feed. It does not call `inbox()` behind the watcher or promise replay
after a display failure. A newly claimed notification triggers a cursor-neutral
navigation refresh. That keeps registered reply-thread markers discoverable
when the first reply is created while the parent conversation is already open.

## Typed Actions and Native Screens

`actions.py` is the closed semantic vocabulary. Keyboard, arrows, mouse,
navigation rows, inspector actions, and the command palette converge on one
`ActionId` dispatcher. `forms.py` classifies every non-Summon action as a
typed direct action or one of eleven native forms. Visual preflight checks
only required and nonblank fields; public core operations retain domain and
race validation. Exact-target confirmations cover leave, rename, message
delete, dump replacement, and Summon dismissal.

Mouse parity is explicit rather than inferred from labels. The composer has a
Send control; the inspector exposes Members and selected-message
Reply/React/Delete controls. Those buttons build the same typed action
invocation as keys, navigation activation, and palette selection.

`screens.py` renders the searchable native palette, labelled forms,
confirmation, cursor-neutral search, and typed Summon controls. Continuity
tokens are masked and cleared when their screen closes. User and extension
text enters Textual as plain `Text` or non-markup option content; no domain
value becomes CLI argv or Rich markup.

Modal work is single-flight. Submission disables submit and cancel paths until
the owner completes or returns an inline domain error; a second Enter cannot
duplicate a mutation. Search generations are invalidated on dismissal, so a
late result never queries an unmounted screen.

Search results remain public hydrated `SearchHit` values. Opening one calls
`TautClient.history_around()` for exact bounded, cursor-neutral context, then
uses that page as the active transcript and starts the ordinary filtered live
watcher. This avoids both `show_message()` cursor movement and a TUI-owned
second transcript store.

## Responsive Presentation

`models.py` stores session-only visual intent: logical focus, selected ids,
target drafts, mode, inspector, pane choice, and tail or exact-message scroll
anchor. `layout.py` is pure. It maps the exact 120/80/50-column and 20-row
boundaries to wide, medium, compact, and too-small placements. Resize performs
one synchronous latest-state transition and one widget placement batch. It
does not fetch history, restart a watcher, consume a pointer, or create a
resize worker.

Wide mode shows navigation, conversation, and inspector. Medium shows the
conversation plus the selected side surface. Compact shows one logical
surface and stacks transcript metadata. Too-small hides all content and the
footer. An opaque top-screen focus shield owns input while the terminal is too
small; hiding a widget alone is insufficient because Textual can still route
keys to the active modal. Popping that shield restores the exact underlying
modal stack and focus when space returns. Target drafts and message anchors
live outside the widget arrangement, so reflow does not recreate domain state.
An intra-message row offset is bounded to the rewrapped message height when a
wider layout shortens the row; the anchor message therefore cannot drift to
its successor.

Resize work uses a latest-generation render callback. It applies no stale
layout pass after a newer terminal size and restores a hidden compact
conversation only when that surface becomes visible again. The tested
framework floor is Textual 3.0.0: 1.0 exposed the named public APIs but its
click event metadata could not implement reliable select-versus-activate
semantics.

The checked visual fixtures are:

- `docs/implementation/artifacts/tui/taut-tui-130x34.svg`
- `docs/implementation/artifacts/tui/taut-tui-100x34.svg`
- `docs/implementation/artifacts/tui/taut-tui-64x34.svg`
- `docs/implementation/artifacts/tui/taut-tui-40x15.svg`

Regenerate them with `uv run --extra dev python bin/render-tui-screens`. The
script uses fixed public message values. Golden review is a visual gate, not a
substitute for the layout and pilot assertions.

## System and Summon Boundaries

Doctor and dump call actor-free public class operations. Dump is single-flight
and blocks normal quit while active. Its snapshot/watermark behavior comes
only from the active persistence contract; no quiescence or point-in-time
algorithm lives in the TUI extension. Load stays CLI-only. The native help form
quotes the selected paths into an exact command but never invokes load or a
subprocess.

Summon is discovered only through the public `taut_summon` facade. The native
start screen constructs every `SummonRequest` field and obtains provider names
from the controller. Each foreground run disables Summon's process signal
handlers. Its exact-once readiness callback publishes an immutable
`SummonRunHandle` after the first watcher drain and control-plane open; the TUI
tracks that exact handle instead of diffing mutable names. Pending runs block
exit. Confirmed exit requests stop on every exact owned handle and supervises
the retained workers under the 90-second host budget. External drivers are
listed and may be explicitly dismissed, but normal TUI exit never stops them.

Ownership uses both the operation-layer record and a UI token set. Closing
before readiness makes the late exact handle stop itself without publishing a
ready event. Worker return retires the UI token before presentation, so a
queued readiness callback cannot resurrect a finished run. Scheduled logging
and readiness projection contain their own presentation failures; scheduling
alone is not a sufficient exception boundary.

Terminal attachment uses a two-event owner split. A Summon worker posts one
`TerminalLeaseRequest`; the UI handler enters and remains inside
`App.suspend()`, then signals acquisition. Only then does the worker receive
fd 0 and fd 1. Worker release lets the same UI handler exit suspension, force
a redraw, and signal full restoration. One lock excludes concurrent leases.
The scoped `taut_summon` logging bridge saves and restores the namespace
logger exactly, escapes displayed records, bounds them, and buffers them while
Summon owns the raw terminal. A failed restoration latches the lease boundary
closed for the rest of the app lifetime. Logger scopes share process-level
ownership, so overlapping TUI hosts may restore out of order without leaving a
retired forwarding handler installed.

All core, extension, diagnostic, path, target, and message projections pass
through the same terminal-control escaping boundary. A real PTY probe covers
CSI and OSC payloads because Rich `Text` does not neutralize those bytes by
itself.

## Where to Change and How to Verify

- Installed command discovery and launch behavior:
  `extensions/taut_tui/taut_tui/command_manifest.py`, `command.py`, and
  `_launch.py`.
- Action identity, form metadata, and input parity: `actions.py`, `forms.py`,
  and `screens.py`.
- Chat ownership and cursor behavior: `session.py`; change core first when a
  required semantic seam is missing.
- Layout and retained visual state: `layout.py` and `models.py`; keep them free
  of domain I/O.
- Actor-free system work: `system.py`.
- Optional rich-host behavior: `summon.py` plus public `taut_summon` contracts.

The focused local gate is
`uv run --project extensions/taut_tui --extra dev --locked pytest
extensions/taut_tui/tests/test_tui_*.py` plus Ruff and mypy over the extension
package and tests. The retained TUI lock is the supported framework set; there
is no separate older-framework lane. SQLite client/watcher tests stay real;
PostgreSQL uses the shared contract and focused TUI smoke; installed-wheel
probes prove plain core omits the command and paired core-plus-TUI wheels expose
it without eager Textual import.
