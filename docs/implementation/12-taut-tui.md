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
or edits again before the first worker returns. A deletion refresh carries the
already-open reply thread back through the public conversation-open path
because core deletion does not cascade into registered sub-thread deletion.

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

Search results remain public hydrated `SearchHit` values. Opening one calls
`TautClient.history_around()` for exact bounded, cursor-neutral context, then
uses that page as the active transcript and starts the ordinary filtered live
watcher. This avoids both `show_message()` cursor movement and a TUI-owned
second transcript store. The exhaustive handler proof observes both the exact
intent-tokened conversation snapshot and the selected hit's delegated anchor
restore plus following refresh. Snapshot completion alone is not presentation
completion because message rendering defers scroll restoration.

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
and readiness projection contain their own presentation failures; scheduling
alone is not a sufficient exception boundary.

Terminal attachment uses a pre-spawn confirmation followed by the existing
two-event lease handoff. Both the native Summon form and textual `:summon`
route pass the same `TuiSummonInteraction` to the public controller; neither
route guesses whether attachment will occur. When the driver selects an actual
attach, the worker posts one `TerminalAttachConfirmationRequest` while Textual
is still active. The app escapes the typed notice fields and opens the ordinary
native confirmation screen. Cancellation fails closed without suspending or
spawning the provider.

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
idempotent, notifies an `on_resolved` hook so a worker-cancelled
confirmation dismisses its stale modal, and a late modal callback cannot
revive cancelled work. Stale or shutting-down lease requests are refused
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
escape wrappers. A real PTY probe covers initial and updated CSI/OSC-bearing
content because Rich and Textual do not neutralize those bytes by themselves.

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
unchanged.

## Related Plans

- `docs/plans/2026-08-18-tui-deep-review-remediation-plan.md` — display
  escape decoding, the vi-like non-blocking command line and action-browser
  input contract, promotion source discrimination, Summon lease/quit
  lifecycle hardening, teardown-safe worker marshalling, and transcript
  state integrity.
- `docs/plans/2026-08-17-tui-ci-bounded-parallelism-plan.md` — fixed-width,
  file-scoped retained-lock CI execution without timeout or coverage changes.
- `docs/plans/2026-08-17-tui-search-anchor-test-synchronization-plan.md` —
  exact-intent completion proof for deferred search-result anchor restoration.
- `docs/plans/2026-08-17-tui-text-command-alias-plan.md` — passive textual
  completions, TUI-local guarded `q`/`quit`, and any-mode Ctrl-C/Ctrl-D quit
  while Textual owns terminal input.
- `docs/plans/2026-08-17-summon-first-attach-handoff-plan.md` — separates the
  native pre-attach confirmation from the later raw terminal lease for both
  Summon entry routes.
- `docs/plans/2026-08-17-tui-command-entry-correction-plan.md` — leading
  known-command composer promotion, exact originating-draft ownership, and
  argument-ready keyboard/mouse completion activation.
- `docs/plans/2026-08-17-tui-multiline-whitespace-plan.md` — multiline
  composer ownership, exact structural whitespace, and scroll-safe transcript
  spacing.
- `docs/plans/2026-08-17-tui-scroll-anchor-test-synchronization-plan.md` —
  event-based completion proof for the nested viewport-anchor restore refresh.
- `docs/plans/2026-08-17-tui-command-mirror-plan.md` — implements the shared
  command syntax contract, grouped browser, textual `:` mirror, native core
  bindings, and typed `taut-summon` provider/binding boundary.
- `docs/plans/2026-08-14-taut-tui-action-applicability-authority-plan.md` —
  plans one ordered applicability authority in the action-input contracts with
  thin palette, control, and central-dispatch consumers.
- `docs/plans/2026-08-14-taut-tui-action-route-contract-plan.md` — authoritative
  route composition plus exhaustive 54-pair producer and 32-action handler
  firing gates.
- `docs/plans/2026-08-14-taut-tui-display-sink-coverage-plan.md` — structural
  display/toast ownership and enumerable terminal-escape sink proof.
- `docs/plans/2026-08-14-review-findings-remediation-plan.md` — watcher,
  inspector, intent, teardown, pointer, Summon-control, and framework-floor
  remediation after the coordinated 0.9.0 review.
- `docs/plans/2026-08-12-taut-tui-implementation-plan.md` — original TUI
  implementation, contract promotion, and retained visual acceptance record.
