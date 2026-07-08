# TUI First-Join Copy and Channel Chooser Refinement Plan

Date: 2026-07-08
Owner: maintainer
Spec: `docs/specs/04-taut-tui.md` [TUI-10.9]
Status: draft implementation plan

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
  resolves.
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

If existing channels are available:

- show the channel names in a lightweight chooser inside the first-join surface;
- set the initial selected channel to the first channel in client order;
- keep `#firstjoin-channel` as the submit source, setting its value to the
  selected channel as the user moves the selection;
- Up/Down moves the selection while focus is on the channel field or channel
  chooser;
- typing in `#firstjoin-channel` replaces the selected value with arbitrary
  user input, allowing a new channel name;
- hint should say no identity is recognized and that the user can pick an
  existing channel or type a new one.

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
   - existing first-join success/failure tests remain green.

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
