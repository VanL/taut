# Taut TUI Spec

Status: Design specification for the first Textual-based TUI.

## Purpose and Scope [TUI-1]

This spec defines the intended behavior, layout model, interaction model, and
verification expectations for Taut's terminal user interface.

The TUI is the primary interactive human surface for reading, writing, and
watching Taut conversations in a console. It complements the existing CLI. It
must not replace or weaken the CLI verbs, JSON contracts, non-interactive
safety, or script-friendly behavior in `docs/specs/02-taut-core.md` [TAUT-8.1]
and [TAUT-8.2].

This spec is binding for product behavior and implementation boundaries. Exact
Textual widget class names, internal CSS organization, and pixel-identical
colors are implementation details unless this spec explicitly names a behavior
that depends on them.

The first TUI intentionally does not specify summon/provider lifecycle screens,
message editing/deletion, archival, retention, or a notification daemon. Those
surfaces need their own specs before they become TUI obligations.

## Source Signals [TUI-2]

The governing upstream spec signals are:

- `docs/specs/02-taut-core.md` [TAUT-8.4] and [TAUT-12.4]: the TUI is a
  consumer of `TautClient` and `TautWatcher`, ships as `taut[tui]`, and adds no
  new runtime dependency to the core package.
- `README.md` roadmap: the TUI provides panes for threads and live presence.
- Van's design note: use Textual for the TUI; appearance should broadly borrow
  from Slack, adapted for a console; launching `taut` with no arguments should
  launch the TUI, while invocations with arguments continue to act like the CLI.
- TUI wireframes supplied on 2026-07-02: default layout is navigation |
  transcript with inline threads | presence; thread side-pane is a toggle;
  narrow modes collapse to tabs or an icon rail; recovery states are explicit.

## Product Model [TUI-3]

The TUI is "Slack in a terminal" for a local Taut project:

- a navigation surface shows channels, direct messages, thread shortcuts, the
  notification inbox, unread state, and presence hints
- a transcript surface shows the active conversation with notices, timestamps,
  authors, message text, unread separators, and thread affordances
- a composer sends a new message or reply to the active target
- a presence surface shows active-context members, selected identity detail, and
  the current acting member
- live updates arrive through the same watch semantics as `taut watch`

The implementation should favor density, keyboard flow, terminal readability,
and predictable focus over decorative fidelity to Slack.

### [TUI-3.1] Existing Design Leverage

Taut has no separate `DESIGN.md` at this spec baseline. The first TUI therefore
uses these existing product design anchors:

- README positioning: private, no-config chat for humans and agents in a
  terminal
- core spec semantics: channels, direct messages, one-level threads, notices,
  membership, presence, unread cursors, and notification inboxes
- wireframe visual language: dark terminal surface, compact monospace layout,
  sectioned left navigation, central reading surface, anchored composer,
  right-side context, active focus outline, muted low-chrome separators, and a
  bottom key bar
- CLI/API boundary: visible UI actions map to existing client-owned operations
  wherever those operations exist

New visual patterns should extend those anchors rather than inventing a
marketing-style interface or a decorative dashboard.

## Architecture Boundary [TUI-4]

### [TUI-4.1] Optional Extra

The TUI ships behind `taut[tui]`. Textual and any TUI-only dependencies belong
to that optional extra. They must not be added to core `project.dependencies`.

The core install remains sufficient for the current CLI and Python API.

### [TUI-4.2] No Parallel Semantics

The TUI must use `TautClient` for command semantics and `TautClient.watch()` or
`TautWatcher` for live updates. It must not duplicate:

- target or address resolution
- identity resolution
- message envelope construction
- sidecar SQL
- notification claiming
- cursor advancement
- membership convergence

If the TUI needs behavior the client cannot express, the client/API surface
should grow first or in the same change, with CLI/API compatibility reviewed.

### [TUI-4.3] Import Boundary

Normal CLI commands must not import Textual at module import time. Missing
Textual or a missing `tui` extra must not break `taut --help`, `taut --version`,
or existing CLI verbs.

## Launch Behavior [TUI-5]

### [TUI-5.1] Bare Interactive Launch

When `taut` is launched with no arguments from an interactive terminal, it
starts the TUI.

If `taut[tui]` is not installed, the command exits cleanly with a clear message:

- state that the TUI extra is not installed
- give a concrete install hint such as `pipx inject taut "taut[tui]"`
- remind the user that CLI commands such as `taut list` and `taut watch` still
  work
- exit with code 1

### [TUI-5.2] Existing CLI Behavior

Invocations with CLI verbs continue to act as the CLI. `taut --help` and
`taut --version` remain CLI operations.

No TUI launch path may change existing CLI output contracts, JSON shapes, or
exit-code meanings unless `docs/specs/02-taut-core.md` is intentionally revised.

### [TUI-5.3] Non-Interactive Safety

The TUI must not launch in non-interactive contexts where it could hang an
agent, script, or pipeline. If stdin or stdout is not a terminal, bare `taut`
must choose deterministic non-interactive behavior: print help or a clear error
and exit non-zero.

This preserves [TAUT-8.2]: agents must never hang on a question or interactive
prompt.

### [TUI-5.4] Global Options Without a Verb

No-verb invocations that contain only global options, such as `taut --db PATH`,
should launch the TUI configured with those options when the terminal is
interactive. `--help` and `--version` are exceptions and remain CLI operations.

The implementation must document and test exactly which global options are
accepted for TUI launch.

## Default Layout [TUI-6]

### [TUI-6.1] Wide Layout

At wide terminal sizes, approximately 120 columns and above, the default layout
is:

```text
navigation | transcript and composer | presence
```

The title bar identifies Taut and the current project path. The bottom key bar
shows the current command surface.

### [TUI-6.2] Navigation Pane

The navigation pane is ordered by sections:

1. Channels
2. Direct
3. Threads, when useful thread shortcuts exist
4. Inbox

Navigation rows show a stable target label and, when available, unread counts.
Direct-message rows also show presence hints. The selected row is visibly
distinct from unread styling.

Unread counts and unread separators follow the watch-delivered read semantics
in [TUI-10.8]: while the TUI runs they are session display state, and they do
not persist across TUI sessions.

The inbox appears as a navigation row in the first TUI. It should not become a
dedicated pane unless notification traffic or design review shows that the row
is insufficient.

### [TUI-6.3] Transcript Pane

The transcript pane shows the active conversation. It includes:

- a header with the conversation name and useful context such as member count
  or presence summary
- notice events, such as channel creation or joins
- message timestamps
- author names
- wrapped message text
- inline thread summaries or expanded inline replies
- unread separators for newly arrived messages

Human rendering is intentionally not a stable API. Tests should verify
structure and behavior, not exact glyphs, colors, spacing, or decorative rules.

### [TUI-6.4] Composer

The composer is anchored below the transcript. Its label names the active
message target, for example `message #general` or `reply in parser`.

Sending from the composer uses the same client-owned write path as `taut say`
or `taut reply`, according to the active target.

### [TUI-6.4a] Channel Join and Creation Surface

The TUI must provide a normal interactive path to the client-owned
`join CHANNEL` operation. Joining and channel creation are one client
operation in Taut: `TautClient.join(CHANNEL)` joins an existing channel or
creates the channel if it does not exist. The TUI must not invent a second
channel-creation path or write channel/membership state directly.

The join surface is available from the main TUI, including when the current
member already has joined channels. It may be opened from the navigation pane,
help/command surface, or a dedicated key binding, but the user path must be
discoverable from keyboard help.

Required user path for joining an existing channel:

1. Open the join-channel surface.
2. See existing project channels that the current member has not joined, using
   a client-owned read-only listing path.
3. Move through channels with the keyboard and/or type a channel name.
4. Submit the selected existing channel.
5. The TUI calls `TautClient.join(CHANNEL)`, rebuilds membership/navigation from
   client reads, and makes the joined channel reachable without fabricating
   optimistic transcript rows.

Required user path for creating a new channel:

1. Open the same join-channel surface.
2. Type a valid new channel name.
3. The TUI makes clear that submitting this unmatched name will create and join
   `#CHANNEL` through normal `join` semantics.
4. Submit/confirm.
5. The TUI calls `TautClient.join(CHANNEL)`, then rebuilds membership/navigation
   from client reads.

The join surface must handle these states:

- existing joinable channels are present: list them and allow typing a new
  channel name;
- no existing project channels are present: show an empty state whose primary
  action is typing a new channel name;
- the member already has joined channels: keep the current conversation open
  unless the user successfully joins/creates another channel, then switch to
  the joined channel or otherwise make the result obvious;
- the member has no joined channels: present the join/create surface as the
  primary next action after launch or first-join identity setup.

`join --persona` and `join --new` are not part of this surface. They are
identity/profile operations layered onto `join`, not normal channel membership
selection, and remain governed by [TUI-10.9]'s identity-management deferral
until a dedicated identity/profile design exists.

### [TUI-6.5] Presence Pane

The presence pane shows active-context members and at least:

- display name
- presence state, such as here or away
- selected identity detail when a member is selected
- the current acting member

At widths where the presence pane cannot fit, it collapses behind the members
toggle and may be summarized in the transcript header.

### [TUI-6.6] Visual Language

The TUI is app UI, not a landing page. Its visual system should stay calm,
compact, and work-focused:

- use one primary accent for active focus, unread counts, and selected targets
- use presence color only for presence state, not general decoration
- keep chrome minimal: thin separators, subdued title bars, no decorative cards
  or ornamental gradients
- prefer readable monospace alignment for transcript rows and command surfaces
- make selected, focused, unread, and disabled states visually distinct from one
  another
- preserve enough contrast for long reading sessions in dark terminals

The screenshots are directional for hierarchy and density. Exact hex values,
glyphs, and border treatment may change during implementation if the structural
roles above remain clear.

## Threads [TUI-7]

### [TUI-7.1] Default Inline Threads

One-level sub-threads render inline under their parent message by default. An
expanded inline thread shows a thread label, reply count, and the recent replies
indented below the parent.

Inline threads must preserve Taut's one-level thread model. The UI must not
imply recursive nested threads.

### [TUI-7.2] Folding

An inline thread can be folded to a one-line summary containing the thread label
and reply count. Folding affects only display state. It must not change read
cursors, membership, message history, or notification state.

### [TUI-7.3] Thread Side Pane

The user can open the active thread in a right-side thread pane for longer
exchanges. In this mode:

- the main transcript remains visible
- the thread pane shows the parent context and replies
- the thread pane owns its own reply composer
- Escape closes the thread pane
- the pane may replace or borrow the presence column

The thread side pane uses the same thread membership and reply semantics as the
CLI `reply` command.

## Focus and Keyboard [TUI-8]

### [TUI-8.1] Focus Model

Exactly one pane is focused at a time. The focused pane must be visually
obvious. Focus can move among navigation, transcript, composer, presence, and
the thread side pane when present.

Tab and Shift-Tab cycle focus. Text entry from a non-modal state should move to
the composer unless a command palette, search box, or similar text-capture mode
is active.

### [TUI-8.2] Baseline Commands

The initial command surface is:

| Key | Behavior |
|---|---|
| Arrow keys | Move selection within the focused pane |
| Enter | Open selected conversation or thread |
| `c` | Focus composer |
| `z` | Fold or unfold the active inline thread |
| `t` | Toggle thread side pane |
| `m` | Toggle members/presence |
| `/` | Search or find |
| `g` | Go to conversation |
| `i` | Open inbox |
| `?` | Open help |
| `q` | Quit |
| Escape | Close transient pane, modal, or search state |

The bottom key bar should show the relevant commands for the current mode. It
may omit unavailable commands at narrow widths, but help must expose the full
active command set.

### [TUI-8.3] Search, Goto, and Help

`/` opens search for the active conversation. The first implementation should
search visible transcript content and loaded active-conversation history; it
does not need to search every joined conversation at once.

`g` opens a goto overlay for switching among known channels, direct messages,
thread shortcuts, and inbox. This is not a full command palette in the first
version.

`?` opens help for the active mode, including commands hidden from the narrow
key bar. Help must be closable with Escape without changing the active target.

### [TUI-8.4] Accessibility and Terminal Ergonomics

The TUI must be fully operable from the keyboard. Any pointer/mouse support is
an enhancement, not the primary path.

Accessibility requirements for the first implementation:

- focus order is deterministic and matches the pane model
- focused controls and selected rows are distinguishable without relying on
  color alone
- body text and command labels meet practical terminal contrast expectations
  for dark themes
- status and error messages use text, not only color or symbols
- composer labels stay visible when the composer has content
- narrow modes preserve the same command reachability as wide mode through
  help, goto, tabs, or toggles
- screen-reader compatibility is best-effort within Textual's terminal
  constraints, but semantic labels and visible text must not be sacrificed for
  glyph-only UI

## Responsive Layout [TUI-9]

### [TUI-9.1] Wide Mode

At about 120 columns and wider, show navigation, transcript/composer, and
presence together.

### [TUI-9.2] Medium Mode

At about 80 to 119 columns, collapse to a tabbed or two-pane layout. The
transcript remains the primary reachable surface. Presence is available through
the members toggle.

### [TUI-9.3] Narrow Mode

At about 50 to 79 columns, collapse navigation to a compact rail or equivalent
selector. Author metadata may stack above wrapped text. The composer remains
reachable.

### [TUI-9.4] Too Small

Below the minimum usable width or height, show a clear terminal-too-small hint
rather than rendering an unusable interface.

Exact thresholds may be tuned during Textual implementation, but the structural
modes above are required.

## State and Recovery [TUI-10]

### [TUI-10.1] Uninitialized Project

When no Taut database or configured backend exists for the current project, the
TUI shows an empty state explaining that the directory is not a Taut project.
The first version should provide an explicit "run taut init" or "init here"
action and a quit path.

Initialization must call the same client-owned initialization path as `taut
init`.

### [TUI-10.2] Unknown Identity

Identity errors surface from the same client rules as CLI commands. The TUI
must not invent alternate member selection or alias rules.

One identity condition gets a dedicated setup state instead of a fatal
message: an unrecognized caller in an initialized project ([TUI-10.9]). Every
other identity condition — conflicts, token mismatches, rejoin-shaped cases —
remains CLI-first and surfaces as guidance naming a concrete next command.

### [TUI-10.2a] Post-Identity Channel State

After launch identity resolution succeeds, or after a first-join identity setup
creates/resolves a member, the TUI decides the initial channel state from
client-owned membership and thread reads.

Required behavior:

| Condition | TUI behavior |
|---|---|
| recognized member has one or more joined channels | Open the main TUI directly. Build navigation from joined threads, select a deterministic default joined channel, and show the transcript/composer for that target. No setup or join prompt appears. |
| recognized member has joined channels with unread messages | Same as above, with unread badges and unread separators seeded from the session snapshot under [TUI-10.8]. The presence of unread messages must not change launch routing. |
| recognized member has no joined channels, and project channels exist | Open the main TUI in a no-joined-channel state. The primary next action is the channel join surface from [TUI-6.4a], listing joinable existing channels and allowing a new channel name. |
| recognized member has no joined channels, and no project channels exist | Open the main TUI in a no-channels state. The primary next action is the channel creation path from [TUI-6.4a]. |
| identity is unrecognized | Enter first-join identity setup ([TUI-10.9]) before applying the no-joined-channel/no-channel routing above. |

This table is the launch contract for a user who has already joined a channel
before opening the TUI: they are taken straight to the normal chat surface.
Channel joining is available as an explicit action, not as a blocking setup
step.

### [TUI-10.3] Lost Membership

If the active member loses membership in a conversation while the TUI is
running, the watcher membership-convergence rules apply. The UI removes or
disables the affected conversation and surfaces a recoverable status or error
message. Message history is not deleted.

### [TUI-10.4] Runtime Errors

Recoverable runtime errors surface as inline, non-blocking banners or status
messages where possible. They must not corrupt cursors, claim notifications
incorrectly, or silently skip messages outside the watcher contract.

### [TUI-10.5] Watcher Liveness

The TUI inherits watcher liveness rules from [TAUT-8.4]. Handler or display
failures must not create a second cursor policy. At-least-once display,
poison-message handling, and membership convergence remain owned by the watch
runtime.

### [TUI-10.6] Interaction State Matrix

The first implementation must define visible states for each major surface:

| Surface | Loading | Empty | Error | Success | Partial |
|---|---|---|---|---|---|
| TUI launch | Starting app and resolving project/member | No project state with init/quit actions | Missing extra, invalid db, identity failure | Main layout opens on selected/default target | TUI opens with some targets unavailable |
| Navigation | Resolving joined targets and unread state | No joined conversations; offer join/init guidance as appropriate | Target list unavailable | Targets grouped with unread counts | Some targets disabled after membership loss |
| Transcript | Loading recent active history | No messages yet; show target context and composer | Active target cannot be read | Messages and notices render; unread separator appears when needed | History window loaded but older messages remain unloaded |
| Composer | Sending message/reply | Empty input with visible target label | Send failed with retry/recoverable message | Sent message appears through client/watch path | Source write succeeded but auxiliary notification warning surfaces |
| Presence | Loading members | No other members known | Presence unavailable | Member list and selected identity render | Presence summary shown when pane collapsed |
| Inbox | Loading pending notifications | No pending notifications | Claim/read failed | Notifications shown and claimed per client semantics | Some notifications shown while source context is unavailable |
| Thread pane | Loading parent/replies | Thread has no replies yet | Parent or thread target unavailable | Replies render and reply composer targets thread | Parent context shown but older replies remain unloaded |
| First-join setup ([TUI-10.9]) | Joining as the entered name | Form with name/channel inputs and quit path | Inline validation error keeps form; identity conflict shows CLI-first guidance | Normal bootstrap as the new member | — |

Each visible state should say what the user can do next. Empty and error states
are part of the UI, not fallback exceptions.

### [TUI-10.7] Success and Progress Feedback

Successful sends, replies, joins triggered from an init/setup path, and
notification claims should be reflected in-place through the same client/watch
state that would update the transcript or inbox. The TUI should avoid separate
optimistic state that can disagree with the client result.

Long-running or retrying work should surface unobtrusive progress/status text
without blocking unrelated navigation.

### [TUI-10.8] Watch-Delivered Read Semantics

A running TUI is a watch session. Live updates inherit the watch runtime's
delivered-equals-seen contract from [TAUT-8.4]: when the watcher hands a chat
message to the TUI and the hand-off succeeds, the acting member's stored read
cursor for that thread advances. This applies to every joined conversation —
including conversations not currently displayed — and to the backlog drained
when the watcher starts.

The first implementation must therefore treat unread presentation as session
state:

- Unread badges and unread separators are seeded from stored cursors captured
  once at app start, before the watcher starts, and are maintained from watch
  deliveries afterward. They are display bookkeeping over client/watch state,
  never a second stored read cursor ([TUI-10.5]).
- Unread state does not persist across TUI sessions for the acting member.
  After a TUI session, `taut list` reports previously delivered messages as
  read, including in conversations never opened on screen. This matches
  leaving `taut watch` running, and it intentionally differs from Slack-style
  persistent unread.
- Cursor advancement is forward-only, so consumed unread state cannot be
  restored per-message. A delivered-versus-viewed cursor split that would
  provide Slack-style persistence is a core-spec change ([TAUT-7.2],
  [TAUT-8.4]) and is explicitly out of scope for the first TUI.

This tradeoff is intentional (maintainer decision, 2026-07-03). User-facing
documentation — at minimum the README usage note — and the TUI implementation
doc must state it plainly.

### [TUI-10.9] First-Join Setup Flow

Revision slice added 2026-07-07; copy/channel affordance refined 2026-07-08.
This narrows the v1 "setup beyond `init` stays CLI-first" scoping (the Task 8
decision recorded in [TUI-13] and [TUI-15]) for exactly one flow: an
interactive caller in an initialized project where the client does not
recognize the caller's identity. Everything else in [TUI-15]'s
identity-management deferral stays deferred.

**Design intent.** The TUI may help an unrecognized interactive caller become
usable, but it must not become a parallel identity-management system. The TUI
only collects minimal input and calls existing `TautClient` operations with
the same semantics as the CLI ([TUI-4.2]). Only the client decides what
identity or member exists. The setup state should tell the user that no
identity is recognized for this terminal/caller, then collect only the minimum
information needed to reach a normal TUI channel state.

**Trigger.** When bare interactive `taut` launches the TUI in an initialized
project, client construction succeeds, and identity resolution reports the
caller as *unrecognized* ([IAN-3.3] resolution step 6), the TUI shows a
first-join setup state instead of a fatal message.

The trigger is the typed unrecognized-caller error contract in [IAN-3.3] —
the TUI branches on the error type, never on message text. One companion
condition also opens this state: when `--as NAME` was given and read-only
resolution reports that member as not found ([IAN-3.3] resolution step 1,
surfaced as the member-not-found error from the identity read), the form
opens with the name prefilled — the same "no identity exists here" situation
entered through an explicit selector. Identity errors that are neither of
those types (claim conflicts, token mismatches, rejoin-shaped conditions)
must not open this state; they surface as CLI-first guidance naming a
concrete next command, for example `taut rejoin NAME` or
`taut --as NAME join CHANNEL`.

**The form.** The identity setup state asks for a display name, prefilled from
`--as NAME` when it was given but unrecognized. Channel choice belongs to the
normal join/create surface in [TUI-6.4a] once that surface exists.

Compatibility note for the narrow first implementation: while the TUI lacks a
standalone main-surface join/create action, this setup state may ask for both
display name and channel name so it can submit through the existing
client-owned equivalent of `taut --as NAME join CHANNEL`. That compatibility
shape is not the final product model; it is an implementation bridge.

When the compatibility form includes a channel control and existing channel
rows are visible through a client-owned read-only path, it should include a
lightweight channel chooser: list existing channels and allow arrow-key
selection, while also allowing the user to type a new channel name. If no
channel exists, the channel control is simply an empty field for a new channel
name. Picking an existing channel and typing a new channel are both just ways
to choose the `CHANNEL` argument for the same client-owned submit action.

Submitting the compatibility form performs the client-owned equivalent of
`taut --as NAME join CHANNEL`. Joining a channel that does not exist yet
creates it — existing client semantics, sufficient for a brand-new project
straight after [TUI-10.1] init-here. After success the TUI re-runs its normal
bootstrap as that member; it must not fabricate an optimistic transcript
([TUI-10.7]).

When the final identity-only setup form is used, submitting the display name
must create/resolve identity through client-owned semantics, then route through
[TUI-10.2a]. If the resulting member has no joined channels, the TUI shows the
normal join/create surface from [TUI-6.4a] rather than keeping channel choice
inside identity setup.

**Failure rules.** A simple validation or membership error from `join()`
shows an inline error and keeps the form open. Any other identity condition
shows the CLI-first guidance above; the TUI must not invent recovery logic.

**Interaction rules.**

- This state appears only in an already initialized project; uninitialized
  behavior remains [TUI-10.1].
- Non-tty bare `taut` still prints help and exits ([TUI-5.3]); it never
  prompts. `--json`, `--timestamps`, `--quiet`, `--help`, `--version`, and
  all explicit verbs keep CLI behavior ([TUI-5.2], [TUI-5.4]).
- The form is keyboard-complete ([TUI-8.1]). Enter submits the focused form
  input and must not be swallowed by app-level priority bindings (the
  [TUI-10.1] init-here binding is the known hazard; pinned by test).
- In the compatibility form, when existing channels are listed, Up/Down moves
  among them without leaving the setup state; typing in the channel field may
  replace the selected channel with a new channel name. This is an affordance
  only, not a separate command path.
- While a text input is focused, printable keys belong to that input. The form
  hint must not advertise bare `q` as an active quit shortcut in this state.
  Escape returns to the identity-guidance state; from there `q` quits. A
  concise hint such as "esc then q quits" is acceptable.

**Non-goals.** The first implementation must not add in-TUI support for:
rejoin, continuity tokens, `join --new`, persona selection, rename/name
changes, resolving name collisions beyond surfacing the client error,
choosing between identity candidates, or any TUI-only identity, membership,
cursor, or presence semantics. Where one of those is needed, the TUI shows
the concrete CLI command instead.

**Invariants.** No direct SQL, queue, envelope, cursor, or membership
mutation in `taut/tui` ([TUI-11]). No TUI-specific identity rules. No new
persistent setup state. Existing CLI output, JSON shapes, and exit codes do
not change.

## Invariants [TUI-11]

- Textual and TUI-only dependencies stay in `taut[tui]`.
- CLI, Python API, and TUI share client-owned command semantics.
- Live display uses the exported watch path; no watcher fork.
- Unread badges and separators are session display state under [TUI-10.8];
  the TUI stores no second read cursor.
- Bare `taut` is safe for scripts and agents in non-tty contexts.
- Existing CLI JSON and exit-code contracts do not drift.
- Visual styling is not a public machine contract.
- Thread UI never implies more than one level of sub-threading.
- Empty, error, and partial states remain visible and actionable.
- Keyboard operation is complete; mouse operation is optional.

## Verification Expectations [TUI-12]

The first implementation plan must include these proof points:

- CLI launch tests proving bare interactive launch dispatches to the TUI path,
  while `--help`, `--version`, and existing verbs keep current behavior.
- Global-option launch tests for accepted no-verb TUI options such as `--db`.
- Non-interactive tests proving bare `taut` does not launch or hang when stdin
  or stdout is not a terminal.
- Packaging tests or inspection gates proving Textual is only in the optional
  `tui` extra and normal CLI imports do not require it.
- TUI behavior tests for conversation selection, message send, inline thread
  folding, thread-pane toggling, presence toggling, inbox opening, and error
  reporting.
- Search/goto/help tests proving active-conversation search, target switching,
  and help dismissal do not corrupt focus or active target.
- At least one real `TautClient`/watcher-backed proof for live updates; do not
  mock the core message/watch path being proven.
- Terminal-size tests or inspection gates proving wide, medium, narrow, and
  too-small modes choose the expected structure without incoherent overlap in
  representative fixtures.
- Recovery tests for missing optional extra, uninitialized project, lost
  membership, and recoverable runtime errors.
- First-join setup tests ([TUI-10.9]): an unrecognized caller in an
  initialized project opens the setup state; submitting name/channel goes
  through the real client path and lands in the normal TUI; the created
  member and join match `taut --as NAME join CHANNEL` semantics; a
  conflict-shaped identity error shows CLI-first guidance instead of the
  form and does not crash; Enter reaches the focused form input despite
  app-level priority bindings; existing-channel projects surface those
  channels in a lightweight chooser and allow arrow-key selection; typing a
  new channel still submits the same client-owned join path; the form hint
  does not claim bare `q` quits while text input is focused; non-tty bare
  `taut` still never prompts; and existing launch, missing-extra, and CLI verb
  tests are unchanged.
- Accessibility inspection gates for keyboard-only operation, visible labels,
  non-color-only status, and contrast-sensitive dark terminal readability.

## Open Questions [TUI-13]

These questions should be resolved before implementation planning, or carried
into that plan with an explicit decision owner:

- What exact width and height thresholds should Textual use for the four
  responsive modes?
- Should `join` and identity-management flows exist in-app in the first
  version, or should setup beyond `init` remain CLI-first?
  **Resolved in two steps:** v1 shipped CLI-first (Task 8 decision,
  implementation plan). Revised 2026-07-07: the narrow first-join flow
  (name + channel for an unrecognized caller) is now in-app per
  [TUI-10.9]; all other identity management stays CLI-first per [TUI-15].

## User Journey [TUI-14]

The first TUI should support this core journey:

| Step | User does | User should feel | Spec support |
|---|---|---|---|
| 1 | Runs `taut` in a project | Oriented, not dropped into help text | Bare interactive launch opens TUI; title bar names project |
| 2 | Scans navigation | Able to see where attention is needed | Sections, unread counts, presence hints, inbox row |
| 3 | Opens a conversation | Grounded in context | Header, transcript, notices, unread separator |
| 4 | Reads/replies | Fast and low-friction | Anchored composer, command key bar, client-owned send path |
| 5 | Encounters a thread | Still in the channel, not lost | Inline threads by default; side pane for deeper exchange |
| 6 | Checks people/context | Confident who is present and who they are acting as | Presence pane, selected identity, current member |
| 7 | Handles trouble | Recoverable, not stranded | Missing-extra, init, lost-membership, and runtime banners |

The design should optimize the five-second impression around orientation and
the five-minute experience around uninterrupted reading/replying. The
five-year value is trust: Taut should feel like a dependable local tool that
does not surprise scripts, lose state, or hide what happened.

## Explicit Deferrals [TUI-15]

These design decisions are intentionally deferred from the first TUI:

- Full command palette: first version has `g` goto, `/` active search, and `?`
  help.
- Cross-conversation search: first version searches the active conversation.
- Dedicated inbox pane: first version keeps inbox in navigation unless traffic
  proves the row insufficient.
- Full in-app identity management: first version may initialize a project, but
  join/rejoin/name/persona management can remain CLI-first unless the
  implementation plan explicitly pulls it in. **Narrowed 2026-07-07:** the
  first-join flow for an unrecognized caller (name + channel) is now
  specified in [TUI-10.9]. Rejoin, continuity tokens, `join --new`, persona
  selection, and rename management remain deferred and CLI-first.
- Mouse-first interaction: keyboard remains primary.
- Recursive/nested thread UI: Taut supports one-level sub-threads only.

## Related Plans

- `docs/plans/2026-07-02-taut-tui-implementation-plan.md` — first Textual-based
  TUI implementation plan: bare-`taut` interactive launch dispatch ([TUI-5]),
  the three-pane layout of wireframe frame 2a ([TUI-6]), inline foldable threads
  and side pane ([TUI-7]), watch-backed live updates ([TUI-8.4]/[TUI-10.5]),
  responsive modes ([TUI-9]), and recovery states ([TUI-10]) — all as a pure
  `TautClient` + `TautWatcher` consumer behind the `taut[tui]` extra.
- `docs/plans/2026-07-07-tui-first-join-flow-plan.md` — first-join setup flow
  ([TUI-10.9]): the typed unrecognized-caller error ([IAN-3.3]), the modal
  name+channel form, and the client-owned `--as NAME join CHANNEL` submit
  path.
- `docs/plans/2026-07-08-tui-first-join-copy-and-existing-channel-plan.md` —
  follow-up refinement for [TUI-10.9]: unknown-identity wording, lightweight
  existing-channel chooser, typing a new channel, and accurate text-input
  shortcut hints.
