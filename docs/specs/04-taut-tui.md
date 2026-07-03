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

Each visible state should say what the user can do next. Empty and error states
are part of the UI, not fallback exceptions.

### [TUI-10.7] Success and Progress Feedback

Successful sends, replies, joins triggered from an init/setup path, and
notification claims should be reflected in-place through the same client/watch
state that would update the transcript or inbox. The TUI should avoid separate
optimistic state that can disagree with the client result.

Long-running or retrying work should surface unobtrusive progress/status text
without blocking unrelated navigation.

## Invariants [TUI-11]

- Textual and TUI-only dependencies stay in `taut[tui]`.
- CLI, Python API, and TUI share client-owned command semantics.
- Live display uses the exported watch path; no watcher fork.
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
- Accessibility inspection gates for keyboard-only operation, visible labels,
  non-color-only status, and contrast-sensitive dark terminal readability.

## Open Questions [TUI-13]

These questions should be resolved before implementation planning, or carried
into that plan with an explicit decision owner:

- What exact width and height thresholds should Textual use for the four
  responsive modes?
- Should `join` and identity-management flows exist in-app in the first
  version, or should setup beyond `init` remain CLI-first?

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
  implementation plan explicitly pulls it in.
- Mouse-first interaction: keyboard remains primary.
- Recursive/nested thread UI: Taut supports one-level sub-threads only.

## Related Plans

None yet. The implementation plan should cite this spec after design review.
