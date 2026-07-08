# TUI First-Join Copy and Channel Chooser Refinement Plan

Date: 2026-07-08
Owner: maintainer
Spec: `docs/specs/04-taut-tui.md` [TUI-10.9]
Status: independently reviewed (see Review Log); ready for implementation

## Context

The first-join setup flow works, but the current form copy says
`first time here — pick a name and a channel · esc back · q quits`. Two UX
problems surfaced during manual use:

- The project may already have channels. The user is not "first time here" in
  the project; only this terminal/caller identity is unrecognized.
- While a Textual `Input` owns focus, `q` is printable text, not an app-level
  quit action. The hint is misleading; the real quit path is Escape back to the
  identity-guidance state, then `q`.
- If channels already exist, a lightweight chooser is acceptable and useful:
  list the channels, let the user pick with arrow keys, and still allow typing a
  new channel name.

This is a copy/affordance refinement, not an identity-management expansion.
The TUI remains a pure `TautClient` consumer and still submits through the
client-owned `TautClient(as_name=NAME).join(CHANNEL)` path.

## Design Intent

The setup state should orient the user without implying project emptiness or
inventing new semantics. It should say what is actually true:

- no identity is recognized for this terminal/caller;
- the user can enter a display name and join a channel;
- if channels already exist, they can pick one with arrow keys;
- if no channels exist, or if they prefer a new one, they can type a channel
  name;
- printable keys in text fields type text, so quitting is `esc` then `q`.

## Scope

In scope:

- Update [TUI-10.9] copy in the form hint.
- Discover existing channel rows through a client-owned read-only path.
- Render a lightweight existing-channel chooser when channels are available.
- Allow the user to type a new channel name even when existing channels are
  listed.
- Keep the form lightweight: no command palette, no fuzzy channel search, no
  multi-select.
- Add regression tests for existing-channel chooser behavior and shortcut-hint
  accuracy.

Out of scope:

- rejoin, tokens, `join --new`, persona, rename, identity candidates;
- changing `TautClient.join()` semantics;
- direct state/SQL reads from `taut/tui`;
- persistent setup state.

## Implementation Plan

### Task 1 — Existing-channel discovery helper

Owner: `taut/tui/app.py`.

Add a small helper, e.g. `_existing_channel_names() -> list[str]`, called only
after `self.client` exists and before/inside `_show_first_join()`.

Required behavior:

- Use `self.client.list_threads(all_threads=True)` and filter `kind ==
  "channel"`. This is client-owned and already guest-safe when no member row
  resolves (verified: it resolves with `allow_guest=True`, which also covers
  the `--as NAME` prefill case — the explicit branch returns a guest
  resolution instead of raising `NotFoundError`; and the
  `EmptyResultError("no unread threads")` raise fires only when
  `not all_threads`, so an empty project returns `[]`). Guest resolution has
  no side effects — no member creation, no activity write.
- Catch `TautError`/`ValueError` and return `[]` plus a non-fatal inline setup
  note if useful. Failure to list existing channels must not prevent the user
  from manually entering a channel.
- Preserve client ordering for the deterministic list order and initial
  selection.

Do not use `joined_threads()` here: an unrecognized caller has joined nothing,
so it cannot answer "what channels exist in this project?"

### Task 2 — Copy and channel chooser

Owner: `taut/tui/app.py:_show_first_join` and small local helpers/widgets as
needed.

Change the hint text from the current "first time here" string to
identity-oriented copy.

**Chooser focus contract (review finding, 2026-07-08).** The chooser is
NON-focusable: render it as plain `TextStatic` rows with a selection
highlight, never a `ListView` or other focusable widget. The shipped modal
contract pins `app.focused in (name_input, channel_input)` after every key
and Tab-cannot-leave-the-form (`test_modal_gate_keeps_focus_on_form`); a
focusable chooser would break those tests or silently weaken the modal
gate — the same bug class review round R-1 caught. Up/Down are handled by a
key handler on the first-join container: Textual `Input` does not consume
Up/Down, so they bubble to the container cleanly while printable keys stay
with the focused input. The shipped focus-pin tests must remain green
unmodified.

If existing channels are available:

- show the channel names in a lightweight chooser inside the first-join surface;
- set the initial selected channel to the first channel in client order;
- keep `#firstjoin-channel` as the submit source, setting its value to the
  selected channel as the user moves the selection;
- Up/Down moves the selection while focus is on either form input (via the
  container key handler above);
- typing in `#firstjoin-channel` replaces the selected value with arbitrary
  user input, allowing a new channel name; the chooser highlight follows only
  Up/Down, never the typed text (no fuzzy matching — out of scope);
- hint should say no identity is recognized and that the user can pick an
  existing channel or type a new one.

Prefill × chooser (review finding, 2026-07-08): with `--as NAME` unknown AND
existing channels, both affordances apply simultaneously — name input
prefilled with NAME, channel input pre-set to the first existing channel,
focus on the channel input (the shipped prefill focus). Shipped prefill
tests seed empty projects, so they stay green; the combined state gets its
own test (Task 3 item 7).

If no channels are available:

- show no chooser;
- leave `#firstjoin-channel` blank;
- hint may say the entered channel will be joined/created by the normal join
  path.

Shortcut copy:

- The form hint must not say bare `q quits` while an input is focused.
- Use "esc then q quits" or "esc back · q quits from guidance" so the displayed
  affordance matches Textual input behavior.

### Task 3 — Tests

Owner: `tests/test_tui_recovery.py`.

Add/adjust tests:

1. Existing channel project:
   - seed an initialized project with an existing channel and no recognized
     caller for the app;
   - first-join form opens;
   - hint mentions identity/unrecognized terminal;
   - existing channel names are visible in the setup surface;
   - channel input is set to the initially selected existing channel.

2. Empty initialized project:
   - first-join form opens;
   - channel input is blank;
   - no channel chooser is shown;
   - hint indicates the user can type a channel name.

3. Shortcut hint:
   - with the form open and an input focused, hint does not contain bare
     `q quits`;
   - hint contains an Escape-mediated quit path (`esc then q` or equivalent).

4. Channel selection:
   - with multiple existing channels, Down/Up changes the selected channel and
     the channel input value;
   - submitting a selected existing channel goes through the real client join
     path.

5. Typing a new channel:
   - with existing channels visible, typing a different channel name into the
     channel input submits that typed value through the same real client join
     path and creates/joins that channel according to `TautClient.join`.

6. Existing launch tests remain green:
   - non-tty launch tests remain unchanged;
   - existing first-join success/failure tests remain green;
   - the shipped modal focus-pin tests (`test_modal_gate_keeps_focus_on_form`
     asserting `app.focused in (name_input, channel_input)`) remain green
     UNMODIFIED — this is the executable form of the non-focusable-chooser
     contract in Task 2.

7. Prefill × chooser combined state:
   - seed a project with existing channels, launch with `--as newname`;
   - name input prefilled with `newname`, channel input pre-set to the first
     existing channel, focus on the channel input;
   - submitting immediately joins that channel as that name through the real
     client path.

## Task 4 — Docs alignment

Owner: `docs/implementation/05-taut-tui-architecture.md`.

Update the first-join paragraphs: unrecognized-identity wording, the
non-focusable channel chooser and its container-level Up/Down handling, the
guest-safe `list_threads(all_threads=True)` discovery path (and why
`joined_threads()` cannot answer it), and the corrected `esc then q` quit
affordance. Doc alignment is part of the definition of done.

## Risks and Constraints

- `list_threads(all_threads=True)` can surface non-channel threads too; filter
  to channels only.
- Listing all threads is acceptable for setup scale, but this must not become a
  full channel browser or command palette in this slice.
- Arrow-key handling must not steal printable input from the channel field.
- Do not let channel-discovery failure block the join form; the user can type
  a channel manually.
- Keep launch and CLI behavior unchanged: no prompt in non-tty contexts, no
  change to verbs, JSON, or exit codes.

## Verification

Run:

```bash
uv run --extra dev pytest tests/test_tui_recovery.py tests/test_tui_launch.py
uv run --extra dev pytest tests/test_tui_app.py tests/test_tui_responsive.py tests/test_client.py
uv run --extra dev ruff check taut/tui/app.py tests/test_tui_recovery.py
git diff --check
```

If implementation touches shared client behavior, broaden to full `uv run
--extra dev pytest`.

## Rollback

Revert the implementation commit. This slice only changes TUI display/default
selection and tests; it adds no persistent state and changes no client
semantics.

## Review Log

- 2026-07-08 — Independent plan review (Claude, cross-family; the spec/plan
  refinement was authored by another agent). Verified against the code before
  findings:
  - `list_threads(all_threads=True)` guest-safety CONFIRMED, including the
    `--as` prefill case and empty-project no-raise behavior (folded into
    Task 1).
  - The `q`-hint premise CONFIRMED as a real shipped bug: the `q` binding is
    non-priority and a focused Input consumes printable keys; the shipped
    test only asserted `check_action("quit_app")`, never the key path.
  - Finding 1 (must fix): chooser focus contract unspecified — a focusable
    chooser would break the shipped modal focus-pin tests
    (`test_modal_gate_keeps_focus_on_form`). Resolved: non-focusable
    `TextStatic` chooser + container-level Up/Down handling; shipped focus
    tests must stay green unmodified (Task 2 + Task 3 item 6).
  - Finding 2: prefill × chooser combined initial state undefined.
    Resolved: name prefilled, first channel pre-set, focus on channel;
    new Task 3 item 7.
  - Finding 3: no docs task. Resolved: Task 4 added
    (`docs/implementation/05-taut-tui-architecture.md`).
