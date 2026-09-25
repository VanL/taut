# Taut TUI Architecture

## Purpose and Governing Contract

The TUI is Taut's human-first reflection over core and loaded first-party
extensions. It is not a second chat model and does not derive behavior from
the CLI parser. `docs/specs/10-taut-tui.md` [TUI-1] through [TUI-14] governs
the surface; the retired plan 2026-08-12-taut-tui-implementation-plan (source `74e1455`; see the ledger in `docs/plans/README.md`) records
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

The session worker owns and closes the client's BrokerSession. Watch creation
uses independent metadata and reactor scopes: caller-thread construction state
is recycled before handoff, and the watcher drive owner releases its cache and
scopes after its final turn. A timed-out watcher stop therefore cannot make
client cleanup close the watcher's independently owned queues.

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
or edits again before the first worker returns. A deletion refresh carries the
already-open reply thread back through the public conversation-open path
because core deletion does not cascade into registered sub-thread deletion.
Native and textual message deletion share this completion owner, so both remove
the deleted row from the active transcript and session snapshot after storage
confirms the operation.

A current-generation delivery rejected by the UI is handed back to the
serialized session owner. That owner stops and clears the rejected watcher,
then reports a generation-scoped degraded event for the UI status line. It does
not acknowledge the rejected message or start a replacement watcher. Session
shutdown attempts client cleanup even when watcher teardown fails, preserving
the watcher failure as primary; queued UI completions are discarded once the
base screen detaches.

Notifications differ on purpose. Every public watcher already claims the
member notification queue, so the TUI stores those pointers in a bounded
session feed. It does not call `inbox()` behind the watcher or promise replay
after a display failure. A newly claimed notification triggers a cursor-neutral
navigation refresh. That keeps registered reply-thread markers discoverable
when the first reply is created while the parent conversation is already open.
Notification delivery re-renders the inspector only when the notification
inbox owns that surface; message, help, system, and Summon inspectors retain
their content.

## Typed Actions and Native Screens

`actions.py` is the closed semantic vocabulary. Keyboard, arrows, mouse,
navigation rows, inspector actions, and the command palette converge on one
`ActionId` dispatcher. `forms.py` classifies every non-Summon action as a
typed direct action or one of eleven native forms. Visual preflight checks
only required and nonblank fields; public core operations retain domain and
race validation. Exact-target confirmations cover leave, rename, message
delete, dump replacement, and Summon dismissal.

Both the native rename form and the text-command confirmation use one
rename-completion path. It remaps exact channel roots and their dotted reply
targets from the `Thread.name` returned by core, retains target-keyed draft and
view state, and reopens an affected conversation through `TuiSession`. The
session therefore owns the bounded watcher stop and replacement. The captured
conversation-intent token prevents delayed completion from taking over newer
navigation. Core remains the owner of destination-name collisions; a reopen
failure is reported after the completed rename without retrying it.

The rename boundary canonicalizes both channel names before starting the
domain future, so command spellings such as `#general` use the same keys as
visual state. Completion always captures the current composer before remapping
the current immutable state. When a remap collides with a nonempty destination
draft, the source remains at the renamed target and the displaced draft moves
to session-local recovery state. The Recover draft action previews retained
multiline content and loads it explicitly through the ordinary conversation
and composer path. Loading into an occupied target retains that target draft
in turn and assigns a new revision, preserving the send-ack fence.

The ordered context requirements in each non-Summon input contract also own
semantic applicability. `forms.py` evaluates those requirements against one
immutable set of closed visual facts and returns enabled or the first human
reason. This keeps requirement order, channel-only scope, draft preconditions,
and reason text behind the same small interface that tests and consumers use.
Registered Summon actions bypass the non-Summon input table after their package
availability has already been filtered by the action registry.

`TautApp` is the thin state adapter. It projects selected navigation, active
target and channel kind, current-message membership, selected search result,
and the active target's nonblank draft into the pure facts. The palette and
central dispatcher consume the evaluator; dispatch checks after any
route-supplied target projection and before forms, shell actions, or domain
handlers. Existing mouse-control visibility stays presentation policy, while
central dispatch prevents hidden, pointer, keyboard, and programmatic routes
from bypassing the same result. Handler checks remain only as stale-state and
domain-race defense.

Each `ActionSpec.routes` set is authoritative at typed invocation
construction. `ActionInvocation.__post_init__()` rejects an action/route pair
that the registry does not declare, including direct dataclass construction;
`_dispatch_tui_action()` has no default route that could hide a producer's
identity. The five routes name semantic production boundaries, so navigation,
palette, and search-result activation keep those routes regardless of the
physical key or pointer that activated them. `MOUSE` names the explicit
base-screen parity controls.

Route-derived surfaces query the same registry. In particular, the command
palette requests only available specs declaring `PALETTE`; `command.open`
therefore remains on its direct key and Commands control without recursively
listing itself. Tests provide two complementary enumerable gates: every
declared action/route pair fires its real Textual producer into the central
dispatcher, and every `ActionId` continues through one real route to a
concrete UI or public-domain postcondition. Stale route claims are removed
when no such producer exists rather than being treated as aspirational UI.

Mouse parity is explicit rather than inferred from labels. The composer has a
Send control; the inspector exposes Members and selected-message
Reply/React/Delete controls. Those buttons build the same typed action
invocation as keys, navigation activation, and palette selection.
Option lists capture the pointer from press through release so a drag-out can
clear pointer activation without misclassifying the next keyboard Enter.

`TautComposer` is the one TextArea adapter for message drafting. It owns
priority Enter submission, Ctrl-Enter/Shift-Enter/Ctrl-J LF insertion,
Ctrl-Tab literal-tab
insertion, multiline paste, terminal-safe placeholder text, and conversion
between TextArea's row/column cursor and `DraftState`'s framework-neutral
scalar offset. Tab behavior remains focus navigation. The adapter uses public
bindings, document text, and cursor movement rather than overriding Textual's
private key handler. Textual requests the enhanced keyboard protocol, but a
legacy terminal may not distinguish modified Enter or Tab; Ctrl-J, paste, and
the Send control are the declared fallback paths.

Message whitespace is presentation, never a stored-content rewrite. At every
message-body projection (transcript, selected-message inspector, and reply
inspector), the owned adapter first decodes the closed [TUI-5.3] escape
allowlist toward sender intent (`decode_message_escapes`: the short escapes
plus lowercase-hex `\xNN`/`\uNNNN`/`\UNNNNNNNN`, exactly the inverse of the
terminal escape policy's output language; surrogate and beyond-Unicode code
points, uppercase hex, and malformed forms stay literal, and `\\` is not a
suppression sequence), then expands actual tabs to four-column stops, then
applies the terminal escape policy — the decode-before-sink ordering is what
keeps decoded control characters other than LF/TAB from opening an injection
surface, because the unchanged sink re-escapes them. Rationale for decoding
at all: the CLI display dialect renders a real LF as the glyphs `\n` and
never escapes backslashes, so the record's distinction between a real
newline and a typed backslash-n is invisible in every record-stream surface;
the TUI displays the intent instead of preserving a distinction no other
display makes. Names, metadata, and search previews never decode.
Inspector renderers assemble metadata and bodies as separate trusted segments:
names and reply-thread labels keep core control escape notation, so body layout
rules cannot widen their display boundary. Each transcript prompt owns one
trailing structural LF, so Rich, Textual's `OptionList`, and Taut's
scroll-anchor height calculation count the same inter-message row. Separator
options would break the one-option-to-one-message index, and Textual 8.2.8
renders CSS vertical option padding without including it in cached option
heights, so neither mechanism owns spacing.

`screens.py` renders the searchable native palette, labelled forms,
confirmation, cursor-neutral search, and typed Summon controls. Continuity
tokens are masked and cleared when their screen closes. User and extension
text enters Textual as plain `Text` or non-markup option content; no domain
value becomes CLI argv or Rich markup.

Modal work is single-flight. Submission disables submit and cancel paths until
the owner completes or returns an inline domain error; a second Enter cannot
duplicate a mutation. Search generations are invalidated on dismissal, so a
late result never queries an unmounted screen.

### Command mirror boundary

`taut.commands.syntax` is the shared grammar owner for the textual mirror. It
contains typed command paths, nested nodes, positionals, options, quoting,
choices, exclusive groups, root globals, root actions, and provider discovery.
It does not import Textual or command adapters. Installed extensions contribute
syntax through `taut.command_syntax`; the `taut-summon` provider contributes
`summon` and `dismiss` syntax only.

The TUI has two command affordances with deliberately distinct identities
([TUI-7.1] as revised 2026-08-18). `:` opens `CommandLineScreen`, a vi-like
bottom-docked bar: the `:` marker, one editable field, and one feedback line
over a transparent, non-dimming backdrop, so the conversation view stays
visible and keeps rendering live deliveries while the bar owns focus.
Completion is an inline ghost shadow supplied through a
`textual.suggester.Suggester` subclass that computes matches from the live
value (the suggester worker can run before the `Input.Changed` handler, so
screen state is not trusted for it); Up/Down cycle which match the shadow
shows (the refresh pins the private Textual 8.2.8 `Input._suggestion`
reactive — worst-case degradation is a shadow that updates on the next
keystroke), and Tab accepts the shadow with an argument-ready space. There
is no browsable completion list. Ctrl-P and the Actions button open the
grouped native action browser: it opens with the first activatable row
highlighted, priority Up/Down bindings move the highlight from the query
field, Enter activates exactly the highlighted row, a no-match query shows a
disabled empty state naming the `:` line, and a query whose first token is
an exact known command root offers a "Run as command" row that dismisses
into the command line prefilled (`PaletteCommandHandoff`). The palette gains
no parser; root membership is tested against the same `command_nodes` set
the composer promotion uses, independent of the fuzzy action matcher.

The message composer also recognizes a delimited leading root command through
that same merged syntax. It waits for whitespace or Enter before promotion so
`who` cannot capture the still-growing `whoami`; unknown colon-prefixed text
remains a message draft. Promotion evaluates only direct user editing:
programmatic composer restores (conversation switches, send-failure
restores) are counted by `_suppress_promotion_edits` via
`_set_composer_text` and never promote, because a `TextArea.Changed` event
carries no source discrimination. On mount the promoted command line
reconciles against the composer's current draft
(`TautApp._reconcile_promotion`), carrying raced keystrokes into the field
and advancing the originating-draft identity so no raced suffix survives as
a hidden sendable chat draft. Cancel leaves the composer untouched and
restores `COMPOSE`; a parsed submission clears only the still-matching draft
before typed dispatch. Command lines opened from `NORMAL` return to `NORMAL`
instead. The separate native-action browser continues to open its typed
forms for argument-bearing actions.

`command_syntax.py` contributes only the TUI shell aliases `q` and `quit`;
core CLI syntax does not claim them. Both bindings rejoin central
`application.quit`, so active dump and owned-Summon blockers remain in force.
App-level priority Ctrl-C/Ctrl-D bindings rejoin that same owner from every
mode and modal while Textual owns the terminal. Ctrl-D is no longer a paging
gesture; PageDown remains. During a raw Summon terminal lease, the provider
owns those control bytes until Textual resumes.

`command_bindings.py` is the second half of the boundary. A syntax provider
only makes a path recognizable. `TuiCommandBinding` records whether the TUI
has an explicit native owner or must report `CLI-only in TUI`. Native command
dispatch passes typed values to `TuiDomainActions`, `TuiSystemOperations`, or
the existing `TuiSummonOperations`; it never calls the CLI dispatcher, starts
a subprocess, or forwards CLI output. Explicit command targets are never
replaced by the current visual selection. The screen owns text and parse
feedback, while `TautApp` owns applicability, confirmation, worker submission,
and result rendering.

Search results remain public hydrated `SearchHit` values. `SearchScreen`
receives an immutable snapshot of the actor-scoped navigation labels, so DM
hits show the same participant label as navigation; an unknown DM label is
`Direct message`, never an internal queue name. Opening one calls
`TautClient.history_around()` for exact bounded, cursor-neutral context, then
uses that page as the active transcript and starts the ordinary filtered live
watcher. This avoids both `show_message()` cursor movement and a TUI-owned
second transcript store. The exhaustive handler proof observes both the exact
intent-tokened conversation snapshot and the selected hit's delegated anchor
restore plus following refresh. Snapshot completion alone is not presentation
completion because message rendering defers scroll restoration.

## Transcript Selection and Clipboard

`TautTranscript` is the only `OptionList` variant that opts into Textual's
framework text selection. Navigation remains an ordinary `TautOptionList`.
The transcript attaches virtual line offsets to its rendered strips and
extracts selection text from those same policy-filtered lines, including
wrapped message bodies. Selection therefore copies the display form produced
by [TUI-12.2] and [TAUT-6.4], never `Message.text`; an ESC or BEL suppressed by
the display policy cannot reappear as a live control after paste.

Textual owns mouse selection. `TautTranscript.selection_updated()` only tells
the app that the selected region changed, which cancels stale pending work.
The bubbling `TextSelected` event on mouse-up arms the owner-selected trigger
(a): one 500 ms timer for the completed non-empty selection. The timer carries
both a generation and the expected text, and copies only if both still match.
Transcript rebuilds cancel it before replacing rows. This keeps selection
session-only and leaves row selection, cursors, active target, and
`TranscriptViewport` ownership unchanged.

Both `y` and the stable-selection timer call Textual's
`App.copy_to_clipboard()`. That is the sole clipboard boundary: Textual caches
the plain text and writes a base64 OSC 52 payload through its driver. Taut does
not call a platform clipboard program and cannot know whether the terminal
accepted the fire-and-forget sequence. The status line reports the attempted
character count; non-idle operation and error state take priority over that
transient note. macOS Terminal.app and tmux without `set-clipboard on` are
documented as known non-consumers.

## Responsive Presentation

`models.py` stores session-only visual intent: logical focus, selected ids,
target drafts, mode, inspector, pane choice, and the named
`TranscriptViewport` owner. The owner has exactly three semantic modes: sticky
tail, exact-message history with an intra-row offset, and intent-tokened search
history. Every mode carries the generation that fences deferred physical
scroll effects. `layout.py` is pure. It maps the exact 120/80/50-column and 20-row
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
Wide and medium transcript prompts use the pure
`transcript_metadata_layout()` decision and a trusted hanging-text renderer.
Their timestamp is the public core `taut.terminal.format_message_time()`
projection (`HH:MM` in local time); exact ids remain in message inspectors and
selection state. That renderer wraps the message body at the width remaining after time
and author metadata, then prefixes continuation lines with the same display
width. The row-height and anchor-restoration paths measure that exact prompt,
so the visual indent cannot drift from scroll calculations.
An intra-message row offset is bounded to the rewrapped message height when a
wider layout shortens the row; the anchor message therefore cannot drift to
its successor.

Resize work uses a latest-generation render callback. It applies no stale
layout pass after a newer terminal size and restores a hidden compact
conversation only when that surface becomes visible again. The tested
framework floor is Textual 8.2.8, selected by the retained TUI lock. There is
no separate older-Textual compatibility lane. This floor supplies the click
event metadata used for reliable select-versus-activate semantics.

Real viewport tests observe each deferred framework boundary they depend on:
the initial transcript render and following refresh, the explicit scroll's
completion callback, and the exact anchor-restore callback caused by a resize
plus its following refresh. A generic event-loop pause is not completion
evidence because option layout, scrolling, resize rendering, and anchor
restoration occupy distinct deferred callbacks. Observers delegate to
production behavior; their deadlines are only missing-callback caps.

`TranscriptViewport` is the sole authority for tail, history, and search
position. System arrivals never capture widget geometry: resize, send
completion, watcher delivery, navigation refresh, and render retain the current
owner. A render asks the owner for a tokened tail or restore effect; the Textual
adapter applies it after refresh with immediate public scroll operations and
drops it if a newer generation owns the viewport. Tail is applied again after
`OptionList` remeasures its rows, under the same token, which closes the resize
and live-delivery race without adding a resize task.

User movement crosses a two-phase seam. Wheel, scrollbar, conventional and vi
scroll keys, and transcript clicks synchronously advance the generation before
Textual moves, invalidating queued system effects. A later settled observation
uses Textual's public target scroll position, waits until that observation is
stable across refreshes, and records sticky tail or an exact-message history
position. Leaving the compact
conversation surface uses the same settled capture boundary. Programmatic
`scroll_to` and `scroll_end` calls do not impersonate user intent. Search-result
activation enters intent-tokened search ownership before loading context; only
the matching snapshot may schedule its restore. Completion converts it to
ordinary history. A newer user movement, target intent, missing hit, rejected
context, failure, or teardown invalidates it. This prevents arrival capture,
post-search snap-back, and stale deferred scrolling without pausing the watcher
or dropping deliveries. If a history anchor disappears, the failed tokened
restore recovers to tail and schedules a fenced tail effect; it cannot leave a
permanent owner pointing at a missing row.

The rapid-resize acceptance test drives real `TautApp`, SQLite, and its live
watcher while requesting sizes across every breakpoint. It proves the final
accepted size, latest model generation, draft, selection, and tail position,
then waits another loop turn to reject stale reversion. The old
`plan_latest_resize` test helper and its synthetic pass counters do not exist.

Initial navigation tests observe the exact navigation future before inspecting
the rendered target list. Source cancellation/error, a snapshot missing direct
messages, and widget-application failure are distinct immediate failures rather
than one polling timeout. Native quit acceptance retains the shipped launcher
and real PTY/ConPTY path for Ctrl-C and Ctrl-D; the in-process key-binding proof
is supplemental. The command adapter returns `TautApp.return_code`, so a fatal
Textual crash retained for diagnostics exits 1 while an ordinary quit exits 0.
Timeout diagnostics retain whether input was sent plus bounded
platform, Textual, decoded-key, guarded-dispatch, and output evidence.

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

Textual 8.2.8 renders a fatal callback exception, retains it on the app, and
returns from `App.run()` instead of raising it through the command adapter.
`_launch.py` therefore performs one narrow post-return compatibility check for
that retained `Exception` and passes it to core capture as `tui.fatal`. It does
not catch widget callbacks or replace Textual's rich traceback. If `App.run()`
actually raises, the post-return bridge is not reached and the root command
dispatcher is the sole owner. Disabled capture and capture-sink failure leave
Textual's return code and terminal behavior unchanged. The private retained
attribute is a reviewed framework seam pinned by a real failing-app test at the
retained Textual floor.

Summon is discovered only through the public `taut_summon` facade. The native
start screen constructs every `SummonRequest` field and obtains provider names
from the controller. Each foreground run disables Summon's process signal
handlers. Its exact-once readiness callback publishes an immutable
`SummonRunHandle` after the first watcher drain and control-plane open; the TUI
tracks that exact handle instead of diffing mutable names. Pending runs block
exit. Confirmed exit requests stop on every exact owned handle and supervises
the retained workers under the 90-second host budget. External drivers are
listed and may be explicitly dismissed, but normal TUI exit never stops them.
Foreground runs and list/status/stop calls use separate bounded executors, so
eight blocked owned runs cannot starve the control path needed to inspect or
dismiss them.

Ownership uses both the operation-layer record and a UI token set. Closing
before readiness makes the late exact handle stop itself without publishing a
ready event. Worker return retires the UI token before presentation, so a
queued readiness callback cannot resurrect a finished run. Scheduled logging
and readiness projection report ordinary presentation failures through the
existing safe `notify` path; scheduling alone is not a sufficient exception
boundary. Return also settles its own operation state before rendering. If the
error view fails, the notification retains both the primary worker failure and
the presentation error. Renderer control-flow exceptions propagate; a completed
worker's stored control-flow exception still follows the worker-error view.

Terminal attachment uses a pre-spawn confirmation followed by the existing
two-event lease handoff. Both the native Summon form and textual `:summon`
route pass the same `TuiSummonInteraction` to the public controller; neither
route guesses whether attachment will occur. When the driver selects an actual
attach, the worker posts one `TerminalAttachConfirmationRequest` while Textual
is still active. The app escapes the typed notice fields and opens the ordinary
native confirmation screen. Cancellation of a bootstrap first-attach fails
closed without suspending or spawning the provider.

A [SUM-7.4] setup-recovery offer arrives through the same request type when
the notice carries a screen excerpt, at either of two timings: before the
run handle is published (first-generation gate; the TUI is still
pending-owned, so nothing may wait on readiness) or after readiness on a
later-generation gate. The presentation is two sequential
`ConfirmationScreen` pushes on the one worker request — first "Looks like
<member> needs interaction." with the escaped excerpt and the attach
question, then, only on yes, the ordinary acknowledgement facts plus the
plain-language "Enter Ctrl-\ Ctrl-\ (Control-Backslash twice) to return to
Taut." line. Declining or dismissing either phase resolves the request
refused and the run continues detached per [SUM-7.4]; only bootstrap
cancellation ends the run. The two-phase split exists so the person sees
the provider's own pending question before consenting to a raw terminal
takeover — the excerpt is display-only and answers happen inside the
attach, never from Taut chrome.

If a declined pre-readiness continuation loses its provider during
orientation, the terminal outcome remains the readiness-abort diagnostic even
when PTY master closure is observed just before the pump publishes generation
death. This precedence is owned by Summon's typed internal adapter outcome; the
TUI neither waits for pump timing nor rewrites errors.

A confirmed request reserves terminal ownership for that exact worker across
provider startup. Only it may post the later `TerminalLeaseRequest`; the UI
handler then enters and remains inside `App.suspend()` and signals acquisition.
Only then does the worker receive fd 0 and fd 1. Worker release lets the same UI
handler exit suspension, force a redraw, and signal full restoration. One lock
excludes concurrent confirmations and leases; losing the confirmation race
degrades to a graceful decline rather than failing the run. Worker return
releases a confirmed pre-lease reservation, so a provider failure cannot
wedge future Summon runs. App unmount closes the interaction before the
operations pool and wakes an outstanding confirmation; request resolution is
idempotent. Lock-owned `set_on_resolved` registration either installs the
observer or invokes it after an already-latched result, so a worker-cancelled
confirmation dismisses its stale modal without a subscription race and a late
modal callback cannot revive cancelled work. Stale or shutting-down lease requests are refused
without suspending. Exception exit from the suspend scope — including
KeyboardInterrupt in the cooked-mode windows around attach/detach — is a
fatal lease failure that exits the TUI completely through normal teardown
([TUI-11.3]): Textual 8.2.8's `App.suspend` cannot re-enter application
mode after an exception, and exiting cleanly beats a dead screen. Pending
owned runs reach the same cancel-and-quit confirmation as live runs
([TUI-11.2]): pre-start cancellation uses a per-record event consumed
before `run_foreground`, in-bootstrap workers get a bounded wait, and
foreground workers run on daemon threads so a hung provider bootstrap
cannot pin interpreter exit.

The scoped `taut_summon` logging bridge saves and restores the namespace
logger exactly, escapes displayed records, bounds them, and buffers them while
Summon owns the raw terminal. A failed restoration latches the lease boundary
closed for the rest of the app lifetime. Logger scopes share process-level
ownership, so overlapping TUI hosts may restore out of order without leaving a
retired forwarding handler installed.

`TuiSummonOperations` also creates one scoped interaction per foreground run.
Its unique in-memory token crosses Summon's separate confirmation and attach
phase threads and is released in the retained worker's `finally` path. The
shared terminal coordinator compares those tokens by identity. It never uses
numeric thread IDs, which Python may recycle after a phase thread exits.

All core, extension, diagnostic, path, target, and message projections pass
through extension-owned display widgets. Plain strings are escaped when a
widget installs or updates content. Styled content is assembled only through a
protected factory that escapes semantic segments before Rich sees them; raw
Rich `Text` is rejected because Rich may discard controls before the widget
boundary. Option add/set/replace paths, select labels, placeholders, labels,
buttons, checkboxes, and application toasts share that ownership. Summon log
records carry a protected one-pass escaped value from the logging bridge so a
project regex cannot rescan generated escape notation at the widget boundary.

A package-wide structural inventory rejects raw or qualified Textual display
widget imports outside the adapter owner, raw Rich `Text`, and local terminal
escape wrappers. A real PTY/ConPTY probe, selected for the host platform,
covers initial and updated CSI/OSC-bearing content because Rich and Textual do
not neutralize those bytes by themselves.

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

The canonical retained-lock TUI workflow uses exactly two pytest workers with
`--dist loadfile`. File-scoped ownership keeps every module indivisible,
including `test_tui_launch.py` and its session-scoped installed-wheel fixture,
while independent modules run concurrently. The fixed worker count bounds
SQLite, Textual, and subprocess pressure; `auto` is not permitted. All five
OS/Python rows, every collected test, and the existing timeout caps remain
unchanged per repetition. Dispatch alone may request `windows_repeat=1..5`:
Windows starts that many fresh full-suite processes sequentially, stopping at
the first failure. Other platforms and push/PR/reusable calls run once. Each
Windows invocation retains its 20-minute step cap; the job cap is
`15 + 20 * repetitions` minutes. This does not enlarge a behavior deadline.

`bin/record_tui_run.py` owns invocation and retained evidence. It writes start
metadata before pytest, preserves its actual status, and rejects missing final
results, inconsistent SHA/lock/runtime/counts, or malformed phase evidence.
Raw JUnit stays outside the uploaded tree; published XML keeps only test
identity/count/status/duration. Artifacts upload even after failure or timeout.
Five passing Windows repetitions at one immutable SHA are a bounded acceptance
sample, not proof of a historical root cause or zero flake probability.

The opt-in test observer in `extensions/taut_tui/tests/_phase_evidence.py`
records real callback transitions without scheduling work. Exact future/run
objects map to per-test opaque ordinals; source completion and UI application
are distinct. It preserves the production confirmation callback and observes
provider consumption through the existing output reader: the Windows handle
callback or the POSIX handle's terminal-state callback. The fixture logs input
before its matched echo. Sequence is log-write order; captured monotonic times
are the transition evidence. No message body, token, or provider screen is
exported. Required-phase duplicates, conflicting outcomes, impossible causal
times, missing phases, and capacity overflow invalidate evidence. Ordinary
background cancellation/error remains diagnostic. Observer disposal is not
producer cancellation or proof of source-thread retirement.

The completion-wait migration and native qualification are tracked by the
active Windows TUI root-cause plan below; this instrumentation alone does not
resolve S4 or replace its causal gate.

### Test-local completion ownership

`extensions/taut_tui/tests/_completion.py` observes existing source and owner
callbacks; it does not drive domain work. Each test scope retains exact
owner/request identities and named phases. Terminal outcome and monotonic
publication time are stored before waking the existing loop. An absolute
deadline accepts on-time publication even if wake delivery is delayed, but
never accepts a late publication merely because the timeout callback ran late.
Timeout or observing-task cancellation disposes only observation. Product
stop and retirement remain separate test responsibilities.

`_screen_completion.py` observes Textual's already-scheduled `AwaitMount`
and existing removal future. It does not start an extra mount task. Result
callback return, actual removal, and committed focus are different phases.
Textual discovers event handlers on classes, so focus is observed after real
app message dispatch, not by assigning an instance `on_descendant_focus`.
Capture the push lifecycle before dispatch and retain that identity across
an awaited handler; a reused screen object does not authorize a newer push.
The result observer also preserves Textual's prebinding convention:
`invoke(partial(callback, result))`. Calling `invoke(callback, result)` is
not equivalent for bound built-ins such as `list.append`; the observer must
not narrow the callback forms accepted by the real framework.

The helper and real-framework regressions live in `test_tui_determinism.py`
and `test_screen_completion.py`. They cover early/late completion, wrong
identity, duplicate outcomes, cancellation, weak callback lifetime, real
held mount/focus/removal, screen reuse and teardown. Caller migrations and
native qualification remain tracked by the active plan; these tests alone
neither diagnose historical S4 nor close its release gate.

## Related Plans

- `docs/plans/2026-09-24-windows-tui-determinism-root-cause-plan.md` — exact
  owner completion, split budgets, causal elicitation, native diagnostics and
  bounded Windows qualification; inherits unresolved S4.

- `docs/plans/2026-09-24-tui-text-selection-and-clipboard-plan.md` — framework
  transcript selection, explicit and timed OSC 52 copy, and display-form
  clipboard safety.

- retired: 2026-08-18-tui-deep-review-remediation-plan — source `d16a278`; see the ledger in `docs/plans/README.md`.
- retired: 2026-08-17-tui-ci-bounded-parallelism-plan — source `4b88b8d`; see the ledger in `docs/plans/README.md`.
- retired: 2026-08-17-tui-search-anchor-test-synchronization-plan — source `4b88b8d`; see the ledger in `docs/plans/README.md`.
- retired: 2026-08-17-tui-text-command-alias-plan — source `423d6f6`; see the ledger in `docs/plans/README.md`.
- retired: 2026-08-17-summon-first-attach-handoff-plan — source `df54c08`; see the ledger in `docs/plans/README.md`.
- retired: 2026-08-17-tui-command-entry-correction-plan — source `0219d4a`; see the ledger in `docs/plans/README.md`.
- retired: 2026-08-17-tui-multiline-whitespace-plan — source `5ed9292`; see the ledger in `docs/plans/README.md`.
- retired: 2026-08-17-tui-scroll-anchor-test-synchronization-plan — source `2b2fa49`; see the ledger in `docs/plans/README.md`.
- retired: 2026-08-17-tui-command-mirror-plan — source `6aa0f74`; see the ledger in `docs/plans/README.md`.
- retired: 2026-08-14-taut-tui-action-applicability-authority-plan — source `45592f0`; see the ledger in `docs/plans/README.md`.
- retired: 2026-08-14-taut-tui-action-route-contract-plan — source `4ca45f2`; see the ledger in `docs/plans/README.md`.
- retired: 2026-08-14-taut-tui-display-sink-coverage-plan — source `73a3fa9`; see the ledger in `docs/plans/README.md`.
- retired: 2026-08-14-review-findings-remediation-plan — source `76b1ec4`; see the ledger in `docs/plans/README.md`.
- retired: 2026-08-12-taut-tui-implementation-plan — source `74e1455`; see the ledger in `docs/plans/README.md`.


### Reactor restoration audit (2026-09-22)

Under [TUI-4.1]/[TAUT-8.5], `session.py` keeps one public watcher for the active
conversation. Its serialized executor owns ordinary public-client operations;
Textual owns presentation and generation admission. The one-shot
`_monitor_watcher_exit` thread only joins the watcher then publishes its real
retirement to the executor. It performs no broker inspection and remains
necessary evidence distinct from a final callback emitted before thread exit.

`system.py` workers own explicit actor-free operations. `summon.py` supervises
finite invocation/control operations and marshals results to Textual. Its
terminal acquired/release/restored Events protect one exclusive suspension
scope. Attach confirmation samples cancellation on the worker that is
already blocked in the wait. A normal answer resolves the request and leaves
no extra thread; cancellation has no separate owned waiter. Host shutdown
still sets the driver's stop event before the refusal is visible. The sample
is not a broker observer. Existing replacement,
timed-out watcher cleanup, terminal lease and cancellation tests are the
behavioral audit gates. The governing map is
`docs/plans/2026-09-19-reactor-restoration-plan.md` S0-TUI/S5.
