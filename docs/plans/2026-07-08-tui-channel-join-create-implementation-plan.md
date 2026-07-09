# TUI Channel Join/Create Implementation Plan

Date: 2026-07-08
Owner: maintainer
Status: independently reviewed; review findings folded in; ready for implementation
Branch: `tui/channel-join-create`

## Goal

Implement the normal in-TUI path for `join CHANNEL` after identity resolution.
The surface lets a recognized member press `j`, pick an existing joinable
channel or type a channel name, and submit through `TautClient.join(CHANNEL)`.
The same surface also covers the no-joined-channel and no-channels launch
states from [TUI-10.2a]. It must remain a thin client-owned interaction layer:
no direct state writes, no second channel-creation path, and no optimistic
transcript rows.

## Source Documents

- `docs/specs/04-taut-tui.md` [TUI-3.1], [TUI-4.2], [TUI-6.4a],
  [TUI-8.1], [TUI-8.2], [TUI-10.2a], [TUI-10.4], [TUI-10.7], [TUI-10.9].
- `docs/implementation/05-taut-tui-architecture.md` — TUI ownership boundary,
  Textual structure, focus affordance, and first-join channel chooser context.
- `docs/plans/2026-07-08-tui-first-join-copy-and-existing-channel-plan.md` —
  useful local pattern for a lightweight, non-focusable channel chooser. Reuse
  the lessons; do not merge identity setup and general channel joining.

## Spec Baseline

- `313343fafba53013eae0f8712d883bfd139d24a2` —
  `docs/specs/04-taut-tui.md` at plan authoring time.

Plan type: implementation with review-fold-in clarification. The independent
review fold-in adds `j` to the [TUI-8.2] command table so it matches the
already-promoted [TUI-6.4a] join-surface requirement; it does not change the
join/create behavior. No further proposed spec delta is expected. If
implementation discovers that [TUI-6.4a] or [TUI-10.2a] cannot be implemented
as written, add a row to the deviation log and promote the spec change before
claiming compliance.

## Context and Key Files

Modify:

- `taut/tui/app.py` — owns `TautApp`, key bindings, modal/transient surfaces,
  membership bootstrap, conversation refresh, first-join setup, and the
  existing client-owned TUI reads.
- `tests/test_tui_app.py` — main Textual `Pilot` tests for normal recognized
  member interactions, navigation, composer, watch behavior, focus, and
  non-mutating display state.
- `tests/test_tui_recovery.py` — recovery and setup tests. Use this only for
  launch-state cases that overlap no-joined-channel/no-channels routing or
  first-join interaction.
- `docs/implementation/05-taut-tui-architecture.md` — update after code lands
  to explain the general join surface, its client-owned reads, its confirm
  state, and how it differs from first-join setup.

Read first:

- `taut/tui/app.py` around `BINDINGS`, `KEYBAR_TEXT`, `HELP_TEXT`,
  `_bootstrap`, `_refresh_membership`, `_refresh_conversation`,
  `_show_first_join`, `_existing_channel_names`, and `_submit_first_join`.
- `taut/client/_threads.py`: `join()`, `list_threads(all_threads=True)`, and
  `joined_threads()`.
- `taut/state/_sql.py:add_membership()`: duplicate membership inserts are
  idempotent, but `TautClient.join()` still emits a join notice, so the TUI must
  avoid calling `join()` for already-joined channels.
- Existing tests in `tests/test_tui_app.py` and `tests/test_tui_recovery.py`
  that use `run_test`, `Pilot`, seeded real `.taut.db` projects, and real
  `TautClient` calls. Follow those patterns rather than mocking the client.

Important current behavior:

- The app currently supports first-join identity setup, including a channel
  chooser, but there is no post-identity `j` join/create surface.
- The first-join chooser is non-focusable: rows are `TextStatic`, selection is
  stored in app state, and Up/Down update the channel input. This is a good
  pattern for terminal clarity, but the general join surface should have its own
  state and submit path.
- `list_threads(all_threads=True)` is the client-owned read for all project
  threads and can be filtered to top-level channels. `joined_threads()` is the
  client-owned read for the acting member's memberships.
- The TUI already uses transient surfaces for search/goto/help/inbox and a
  modal first-join state. Preserve those focus and Escape conventions.
- The app-level Enter binding for `init_here` is priority-bound and currently
  neutralized by `check_action()` except in the uninitialized state. Any new
  Enter-driven form must get a regression test proving focused inputs and
  confirmation states receive Enter as intended.

Comprehension checks before editing:

- Can you explain why the join surface must call `TautClient.join()` for both
  existing-channel joins and new-channel creation, and why it must not call
  state helpers directly?
- Can you explain why selecting an already-joined channel must not call
  `TautClient.join()` even though membership insertion itself is idempotent?

## Invariants and Constraints

- Boundary: `taut/tui` remains a pure `TautClient`/watch consumer. No direct SQL,
  state, broker, queue, envelope, or membership writes under `taut/tui`.
- Submit path: every actual join/create goes through
  `self.client.join(channel)` or an equivalent current-member `TautClient`
  instance. Prefer `self.client.join(channel)` once identity is resolved.
- Creation path: the TUI never creates channels separately. A new channel is
  created only by `TautClient.join(CHANNEL)`.
- Already joined: do not call `join()` for a channel the current member already
  belongs to. Switch/select it or show a concise note, then close or keep the
  surface according to the implemented path.
- Listing failure is non-fatal. Manual typed submit stays available and uses
  neutral join/create language until the client result resolves the outcome.
- Validation: use the shared `validate_channel_name()` before offering or
  submitting the action. Invalid or empty input keeps the surface open and shows
  recoverable inline error text.
- Confirmation: unmatched typed names require a keyboard confirmation state
  before the client call. Enter confirms from that state. Escape cancels
  confirmation and returns to editable input without mutation.
- Submit classification: after validation, classify the submitted text in this
  exact order:
  1. exact match for an already-joined channel -> switch/select without
     calling `join()`;
  2. exact match for a known joinable channel -> join immediately with no
     confirmation;
  3. valid unmatched name, or listing unavailable -> enter the confirmation
     state before any client call.
- Transcript: successful join/create notices appear only through normal
  client/watch/history reads. Do not fabricate optimistic rows.
- Navigation: after successful join/create, rebuild membership/navigation from
  client reads and make the joined channel the active target.
- Focus: opening the surface preserves the current conversation until success.
  Escape closes it and restores focus to the opener. `j` must be documented in
  keybar/help for normal TUI states and must not be active or advertised while
  first-join identity setup owns the UI.
- Scope: no fuzzy search, no command palette, no persona/profile management,
  no `join --new`, no identity token/rejoin workflow, no CLI behavior changes.
- No new runtime dependency.

## Deviation Log

| Spec ref | Planned behavior | Actual behavior | Rationale | Spec proposal |
|----------|------------------|-----------------|-----------|---------------|

## Independent Review Notes

An independent review on 2026-07-09 found seven plan-readiness issues. This
revision folds them in before implementation:

- F1: explicit typed-submit classification between existing joinable,
  already-joined, and unmatched names.
- F2: explicit `action_close_transient()` ordering and two-level Escape
  behavior for confirmation.
- F3: Enter priority-binding hazard called out with tests and `check_action()`
  requirements.
- F4: boundary grep gates added to verification.
- F5: no-joined-channel/no-channels launch behavior decided as empty state plus
  primary action, not auto-open modal.
- F6: current first-join compatibility form always joins a channel, so the
  post-first-join zero-membership branch is documented as future-facing until
  the final identity-only form exists.
- F7: normal keybar/help advertise `j`; first-join-owned UI must not advertise
  or activate it, and the spec command table now includes `j`.

## Implementation Tasks

### Task 1 — Tests First: Recognized-Member Surface Opening

Add failing tests in `tests/test_tui_app.py` for [TUI-6.4a] invocation.

Required assertions:

- A recognized member with at least one joined channel can press `j` from the
  main TUI.
- The join surface appears without changing `active_target`, joined membership,
  or transcript contents.
- The keybar/help includes `j` as the join action.
- The [TUI-8.2] command table includes `j`.
- While first-join setup is active, `j` is not advertised by the active keybar
  or accepted by the app.
- Escape closes the surface and returns focus to the pane/control that opened
  it.

Use a real initialized project and real `TautClient` seeds. Do not mock
`TautClient.join()`.

### Task 2 — Add the General Join Surface Skeleton

In `taut/tui/app.py`:

- Add `Binding("j", "open_join_channel", "join", show=False)` and update
  `KEYBAR_TEXT` and `HELP_TEXT` for normal TUI states. If `#keybar` remains
  visible during first-join setup, it must use first-join-specific text that
  does not advertise `j`; hiding it during first-join is also acceptable if the
  first-join hint remains sufficient.
- Add a general join/create container to `compose()`, separate from
  `#firstjoin`.
- Add app state for the surface: active flag, opener focus/pane, channel list,
  selected index, typed value sync guard, listing error, confirm state, and
  pending channel.
- Implement `action_open_join_channel()` with guards:
  - ignored or inline-noted while first-join is active;
  - requires resolved `self.client` and `self.me`;
  - opens from normal main TUI and from no-joined-channel/no-channels states.
- Add `open_join_channel` to the `check_action()` disabled set while
  `_first_join_active` is true. Keep `init_here` disabled outside the
  uninitialized state so the priority Enter binding cannot swallow join-surface
  input submission.
- Hide or disable conflicting transient surfaces while the join surface is
  active, following existing transient/modal conventions.
- Add a join-surface branch to `action_close_transient()` before search/goto/
  help/inbox/thread-pane cleanup. If the join surface is in confirmation state,
  Escape exits only confirmation and returns to editable input with no mutation;
  if it is in editable/list state, Escape closes the surface and restores the
  opener focus.

Keep this slice non-mutating. Tests from Task 1 should pass after this slice.

### Task 3 — Client-Owned Channel Discovery

Add a helper for the general surface, distinct from first-join if needed, e.g.
`_join_surface_channel_state()`.

Required behavior:

- Call `self.client.list_threads(all_threads=True)` and filter to
  `thread.kind == "channel"` for existing project channels.
- Call `self.client.joined_threads()` or use current navigation state to compute
  already-joined channels for the acting member.
- Build three categories:
  - joinable existing channels: top-level channels not already joined;
  - already-joined channels: top-level channels already joined;
  - unavailable/error: listing failed, but manual entry remains active.
- Do not include sub-threads, DMs, notification queues, or system threads.
- Preserve client order for listed channels.
- Surface listing errors as inline non-fatal text and use neutral
  join/create wording for manual typed submit.

Testing:

- Existing unjoined channels are listed.
- Already-joined channels are shown disabled/current for orientation and cannot
  be submitted as duplicate joins.
- Listing failure still leaves manual typed join/create usable.
- Listing failure does not remove the already-joined duplicate guard; the guard
  must use joined membership/navigation state, not only the possibly empty
  project-channel list.

### Task 4 — Selection, Typing, and Validation

Implement interaction semantics:

- Initial selection is the first joinable channel in client order when one
  exists.
- Up/Down move selection within joinable rows and update the channel input.
- Typing clears the selection highlight and treats the input as the literal
  `CHANNEL` argument, not a search query.
- Empty input and invalid names show inline validation errors and do not call
  the client.
- Use `validate_channel_name()` before any join/create action.
- If typed input exactly matches an already-joined channel, do not call
  `join()`: switch/select that channel and close or show a concise note.
- If typed input exactly matches a known joinable channel, route to Task 5's
  direct join path with no confirmation.
- If typed input is valid and unmatched, or if listing failed so the TUI cannot
  prove whether it exists, route to Task 6's confirmation path.

Testing:

- Up/Down selection updates the input and visible highlight.
- Typing a different value clears selection and does not filter the list.
- Invalid uppercase/reserved/bad-character names produce recoverable inline
  errors and leave membership unchanged.
- Already-joined input switches/selects without a new notice.
- Exact typed joinable-channel input joins directly with one Enter and does not
  show confirmation.
- Unmatched typed input enters confirmation and does not call the client on the
  first Enter.

### Task 5 — Existing-Channel Join Submit Path

Implement Enter for known joinable existing channels:

1. Validate input.
2. Call `self.client.join(channel)`.
3. Close the surface.
4. Re-read membership/navigation from client state.
5. Select the joined channel as `active_target`.
6. Let the join notice arrive through normal history/watch/read paths only.

Testing:

- Submitting an existing unjoined channel adds membership for the acting member
  through the real client path.
- Navigation refreshes and selects the channel.
- No optimistic transcript row is mounted before the client/read path returns.
- Recoverable `MembershipError`, `ThreadNameError`, `IdentityError`, and generic
  `TautError` surfaces stay visible and leave the surface open when retrying is
  sensible. Use narrow monkeypatching only for failure injection, not for the
  success path.
- Enter must reach the focused join input for this path despite the app-level
  priority Enter binding for `init_here`.

### Task 6 — New-Channel Create-and-Join Confirmation

Implement the unmatched typed-name path:

- After validation, Enter moves to a confirmation state instead of calling the
  client.
- Confirmation text names the exact channel and action. When channel listing
  succeeded and the name was not found, use create-and-join `#CHANNEL`. When
  listing failed, use neutral join/create `#CHANNEL`.
- The typed value remains visible.
- Enter from confirmation calls `self.client.join(channel)`.
- Escape from confirmation returns to editable input with no mutation.
- On success, close, refresh membership/navigation, and select the new channel.

Testing:

- First Enter on unmatched valid input does not mutate membership.
- Escape from confirmation returns to editable input and leaves membership
  unchanged.
- Second Enter calls the real client path and creates/joins the channel.
- Successful creation notice appears through normal read/watch refresh, not an
  optimistic row.
- Enter must reach the confirmation state despite the app-level priority Enter
  binding for `init_here`.

### Task 7 — Launch-State Routing for No Joined Channels

Bring [TUI-10.2a] launch behavior into alignment:

- Recognized member with joined channels: current normal launch remains.
- Recognized member with no joined channels and project channels exist: open
  the main TUI in a no-joined-channel state. Do not auto-open the join surface;
  show a visible primary action that opens it, and keep `j` available as the
  same action. Do not show first-join identity setup.
- Recognized member with no joined channels and no project channels exist: open
  the main TUI in a no-channels state. Do not auto-open the join surface; show a
  visible primary action that opens the same surface on its create path, and
  keep `j` available as the same action.
- Identity unrecognized: keep current first-join flow first, then route through
  the post-identity channel state.
- Current compatibility note: the shipped [TUI-10.9] first-join form always
  submits `join CHANNEL`, so the post-first-join zero-membership branch is not
  reachable until the final identity-only setup form replaces the compatibility
  name+channel form. Do not write an unreachable test for that branch in this
  slice.

Testing:

- A member that has already joined a channel opens directly to the normal chat
  surface.
- A recognized member with zero memberships sees the correct empty state and
  can press the primary action or `j`.
- The no-channel empty state routes to the same confirmation-backed
  create-and-join path.
- The no-joined-channel/no-channels states do not auto-open a modal at launch.
- Existing first-join tests remain green and continue to submit through the
  first-join compatibility path until [TUI-10.9] final identity-only setup is
  implemented.

### Task 8 — Documentation Alignment

Update `docs/implementation/05-taut-tui-architecture.md`:

- Add this plan to the implementation-plan references.
- Explain the general join surface boundary and why it is separate from
  first-join identity setup.
- Document the client-owned channel discovery reads and the already-joined
  duplicate-notice guard.
- Document the confirmation state for new/unmatched typed names.
- Document listing-failure behavior and neutral join/create language.

Optionally add this plan to `docs/specs/04-taut-tui.md` `## Related Plans`
after implementation or as part of this planning slice.

### Task 9 — Independent Review and Final Gate

Before implementation starts, run an independent plan review focused on:

- Does the plan preserve the client boundary in [TUI-4.2]?
- Are [TUI-6.4a] exact user paths fully covered?
- Are [TUI-10.2a] launch states covered without reintroducing first-join setup
  where identity is already known?
- Are the tests real enough, or do any mock the behavior they claim to prove?

After implementation, run a pre-PR review pass over the branch and resolve or
record findings before claiming ready.

## Verification Commands

Minimum targeted verification:

```bash
uv run --extra dev pytest tests/test_tui_app.py tests/test_tui_recovery.py
uv run --extra dev ruff check taut/tui/app.py tests/test_tui_app.py tests/test_tui_recovery.py
! grep -RIn "Queue(\\|insert_messages\\|sidecar\\|generate_timestamp\\|Envelope\\|encode_envelope" taut/tui/
! grep -RIn "from taut\\.state\\|import taut\\.state\\|open_broker\\|advance_cursor\\|peek_many" taut/tui/
git diff --check
```

Broader confidence gate before pass-off:

```bash
uv run --extra dev pytest tests/test_tui_app.py tests/test_tui_recovery.py tests/test_tui_launch.py tests/test_tui_responsive.py
```

Manual probe before pass-off:

1. In a scratch initialized project, launch `taut` as a recognized member with
   joined channels, press `j`, cancel with Escape, and verify the active
   transcript did not change.
2. Join an existing unjoined channel from the surface and verify navigation
   selects it.
3. Type a new lowercase channel name, verify confirmation appears, cancel once,
   then confirm and verify the new channel is selected.
4. Confirm that an already-joined channel does not emit a duplicate join notice.

## Rollback

Revert the implementation commit(s). This feature should touch only the TUI,
TUI tests, and implementation docs. Core client and CLI semantics should remain
unchanged, so rollback should not require state migration or compatibility
handling.

## Open Questions

- The no-joined-channel/no-channels empty-state copy should be concise and
  work-focused. Exact prose can be finalized during implementation, but it must
  not imply identity is unknown when identity has already resolved.
