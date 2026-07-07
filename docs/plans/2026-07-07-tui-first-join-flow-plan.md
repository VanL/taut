# TUI First-Join Setup Flow Implementation Plan

Date: 2026-07-07
Owner: maintainer
Spec: `docs/specs/04-taut-tui.md` [TUI-10.9] (revision slice, 2026-07-07);
typed-error contract in `docs/specs/03-identity-addressing-notifications.md`
[IAN-3.3].
Status: awaiting independent plan review, then implementation.

## Context

An unrecognized caller in an initialized project currently dead-ends at a
fatal message (`"… — join with: taut join CHANNEL · q quits"`, `_bootstrap` in
`taut/tui/app.py`) and must exit the TUI to run `taut join`. [TUI-10.9] adds a
first-join setup state: collect display name + channel, run the client-owned
equivalent of `taut --as NAME join CHANNEL`, re-bootstrap. Setup stays
client-owned ([TUI-4.2]); rejoin/tokens/`--new`/persona/renames stay CLI-first
([TUI-15]).

Verified code facts this plan builds on:

- `"unrecognized caller"` is raised at exactly two sites, both for the same
  [IAN-3.3] step-6 condition: `taut/client/_identity.py:23` (`whoami`) and
  `taut/client/_base.py:160` (`_require_member`).
- With `--as NAME` unknown, read-only resolution raises
  `NotFoundError("member not found: NAME")` (`_resolve_member`, explicit
  branch) — a different, already-typed error. This is the prefill trigger.
- `taut/cli.py:_exit_code_for_exception` currently string-matches
  `str(exc) == "unrecognized caller"` → exit 2. The typed error replaces this
  wart with an isinstance check; exit codes must not change
  (`test_cli_set_name_unrecognized_exits_2`, and the `--as` case pins
  `member not found` → 2 via the `NotFoundError` branch).
- `validate_member_name` / `validate_channel_name` raise `ValueError`
  (`taut/_constants.py:163`), and thread-shape errors are `ThreadNameError` —
  so "simple validation → inline" vs "identity conflict → CLI guidance" is a
  clean typed split with no message parsing anywhere.
- `join()` resolves with `create=True`, creates absent channels, and applies
  normal identity-capture rules — sufficient for a brand-new project directly
  after [TUI-10.1] init-here.

## Task 1 — Typed unrecognized-caller error (client, red-green)

1. `taut/_exceptions.py`: add

   ```python
   class UnrecognizedCallerError(IdentityError):
       """No member resolves for the current caller ([IAN-3.3] step 6)."""
   ```

2. Raise it (same message, `"unrecognized caller"`) at both sites:
   `taut/client/_identity.py:23` and `taut/client/_base.py:160`.
3. `taut/cli.py:_exit_code_for_exception`: replace the string-match line with
   `isinstance(exc, UnrecognizedCallerError)` → 2. Ordering note: place the
   check BEFORE the generic `IdentityError` fall-through to 1 (TokenError
   stays first; TokenError is not affected — it is a sibling subclass).

Tests (write first, red → green):

- `tests/test_client.py`: fresh initialized project, no `--as` →
  `whoami()` raises `UnrecognizedCallerError`; assert
  `isinstance(exc, IdentityError)` (compat pin).
- Pin the companion trigger: `--as unknown` + `whoami()` raises
  `NotFoundError` (now load-bearing for the TUI; the assertion exists
  implicitly in CLI tests — add the explicit client-level pin).
- Pin the distinction: a conflict-shaped identity error is NOT the subclass.
  Use the `set_name` IntegrityError path or a rejoin conflict — whichever is
  cheapest to construct; the assertion is
  `not isinstance(exc, UnrecognizedCallerError)`.
- Existing CLI tests must stay green unmodified
  (`test_cli_set_name_unrecognized_exits_2` proves exit-code stability).

Invariant: additive contract change only. Every existing
`except IdentityError` / `except TautError` handler keeps working; JSON
shapes and exit codes unchanged. Rollback: revert the commit; no persistent
state involved.

## Task 2 — First-join state in the TUI

All in `taut/tui/app.py` unless noted. Follow the existing hidden-transient
pattern (`#search-input`, `#goto-input`).

1. **Compose:** add a hidden first-join container in the center column:
   a guidance `TextStatic` (`#firstjoin-hint`), `Input#firstjoin-name`,
   `Input#firstjoin-channel`, and an inline-error `TextStatic`
   (`#firstjoin-error`). CSS `display: none` defaults, matching the other
   transients.
2. **Trigger wiring in `_bootstrap`:** split the current combined
   `whoami()`/`joined_threads()` try so the identity read is caught
   separately:
   - `except UnrecognizedCallerError` → `self._show_first_join(prefill=None)`
   - `except NotFoundError` (only reachable here when `self._as_name` was
     given, per Task 1 pins) →
     `self._show_first_join(prefill=self._as_name)`
   - `except TautError as exc` → existing CLI-first fatal guidance,
     unchanged. Conflict-shaped `IdentityError`s land here by construction —
     no list of conflict messages exists anywhere in the TUI.
3. **`_show_first_join(prefill)`:** show the container, set the hint text
   ("first time here — pick a name and a channel · esc back · q quits"),
   prefill the name input, focus name (or channel when prefilled).
4. **Submit flow** (`on_input_submitted` branches):
   - Enter on `#firstjoin-name` → focus `#firstjoin-channel`.
   - Enter on `#firstjoin-channel` → `_submit_first_join()`.
   - `_submit_first_join()`:
     a. Read+strip both values; empty → inline error, stay.
     b. Pre-validate with the client-owned validators
        (`validate_member_name`, `validate_channel_name` — imported from
        `taut._constants`, no TUI-local rules); `ValueError` → inline error,
        form stays.
     c. `TautClient(db_path=self._db_path, as_name=name,
        token=self._token).join(channel)` —
        the exact CLI-equivalent path.
        - `except (ThreadNameError, MembershipError, ValueError)` → inline
          error, form stays (simple validation/membership per spec).
        - `except IdentityError as exc` → hide form, CLI-first guidance
          fatal: the error text plus
          `use: taut rejoin NAME  or: taut --as NAME join CHANNEL`.
        - `except TautError` → inline error, form stays (recoverable,
          [TUI-10.4]).
     d. Success: `self._as_name = name`, hide the form, clear inline error,
        `await self._bootstrap()`. No optimistic transcript ([TUI-10.7]);
        bootstrap re-reads and starts the watcher normally. Note the
        one-shot client used for `join()` is discarded; the bootstrap client
        is the session client (mirrors `action_init_here` symmetry).
5. **Escape:** `action_close_transient` gets a first-join branch (before the
   inbox/thread-pane branches): hide the form and re-show the identity
   guidance fatal (the state it replaced). `q` continues to quit via the
   existing binding.
6. **Enter-binding hazard:** no `check_action` change is needed —
   `init_here` is gated on `_uninitialized`, which is False in this state —
   but the spec requires a pin test (Task 3, test 9), because a future
   priority binding on Enter would silently eat form submission.

Boundary invariants (unchanged, enforced by existing grep gates + tests):
no SQL/queue/envelope/cursor/membership mutation in `taut/tui`; no changes
to `taut/tui/_launch.py` (non-tty behavior untouched); Textual imports stay
inside `taut/tui` below the lazy import point.

## Task 3 — Tests (`tests/test_tui_recovery.py` unless noted)

Seed for the trigger: `TautClient.init(db_path=db)` with NO member created,
launch `TautApp(db_path=str(db), as_name=None)`.

1. Unrecognized caller in an initialized project → first-join form visible,
   name input focused, no fatal banner.
2. Submit name+channel → lands in normal TUI: nav shows the channel,
   composer label targets it, titlebar set. (Bounded-poll, real client.)
3. CLI equivalence: after (2), a CLI-style client
   `TautClient(db_path=db, as_name=name)` resolves the same `member_id`
   that `whoami()` reports in-app, and `joined_threads()` shows the channel
   — i.e. the member and join match `taut --as NAME join CHANNEL`.
4. Prefill: `TautApp(db_path=db, as_name="newname")` → form opens with
   `newname` prefilled.
5. Invalid channel shape (e.g. `UPPER`) → inline error shown, form still
   open, app alive; then a corrected submit succeeds (recovery, not just
   rejection).
6. Conflict-shaped identity error → CLI-first guidance, NOT the form:
   monkeypatch `whoami` to raise
   `IdentityError("current identity claim already belongs to x")` and
   assert fatal guidance text (contains `taut rejoin`), no form, no crash.
7. Escape from the form returns to the guidance state; `q` still quits.
8. Update `test_empty_state_offers_init_here_and_quit`: after init-here on a
   fresh project the flow now lands in the first-join form (was: fatal
   `taut join` guidance). Chain assertion: init-here → form → submit →
   working TUI — the full journey that motivated the spec.
9. Enter-binding pin: with the form focused, pressing Enter submits the
   form (`Input.Submitted` reached) — guards against priority-binding
   regressions.
10. Non-tty launch tests: existing `test_tui_launch.py` suite unchanged and
    green (bare non-tty still help+exit, never prompts).

Client/CLI tests are in Task 1. Every enumerable element of [TUI-10.9]
(trigger types, prefill, both failure classes, escape/quit, no-optimism)
has a firing test above — DoD requirement.

## Task 4 — Docs and traceability

- `docs/implementation/05-taut-tui-architecture.md`: add a first-join
  section (state, trigger types, why the typed error exists, boundary
  rationale).
- `docs/specs/04-taut-tui.md` Related Plans: backlink this plan.
- README: extend the TUI usage note with one line (first run asks for name
  + channel; everything else stays CLI-first).
- `docs/lessons.md` candidate (post-implementation): UI trigger contracts
  must be typed errors, never message-text matches — the CLI's own exit-code
  string-match was the same latent wart.

## Sequencing and gates

1. Task 1 (red-green) → commit.
2. Task 2 + Task 3 interleaved red-green → commit per coherent slice.
3. Task 4 docs → commit.
4. Gates before calling it done: full `pytest tests/`, `ruff check`, `mypy`
   on changed files, TUI grep gates (INV-5..8 equivalents in the test
   suite), and an independent review pass on the result.

Plan review: per repo convention (DOM-5/DOM-11), this plan gets an
independent review from a different agent family before implementation;
findings are folded in or answered inline here.

## Risks / hardening notes

- **Contract change** is additive (new subclass, same message/exit codes);
  the only behavioral edit outside the TUI is the exit-code isinstance swap,
  pinned by existing CLI tests.
- **Hidden coupling:** the `NotFoundError` trigger is only unambiguous
  because `_bootstrap` catches it around the *identity read specifically* —
  keep the catch scoped to `whoami()`, never around `joined_threads()`
  (which could surface unrelated not-found conditions).
- **No new persistence:** the form holds transient input only; abandoning it
  (escape/quit) leaves zero state behind.
- **Anti-mocking:** all happy-path tests run the real client against a real
  `.taut.db`; monkeypatching appears only in test 6, where constructing a
  genuine claim conflict is disproportionate.
- **Rollback:** each slice is a clean revert; no migration, no stored state.
