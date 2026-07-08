# TUI First-Join Setup Flow Implementation Plan

Date: 2026-07-07
Owner: maintainer
Spec: `docs/specs/04-taut-tui.md` [TUI-10.9];
typed-error contract in `docs/specs/03-identity-addressing-notifications.md`
[IAN-3.3].
Status: independently reviewed (see Review Log); ready for implementation.

## Spec Baseline

- `docs/specs/04-taut-tui.md` as of commit `f740be6` — [TUI-10.9] present,
  including the two-trigger contract (unrecognized-caller type; member-not-found
  from an explicit `--as` identity read).
- `docs/specs/03-identity-addressing-notifications.md` as of `cb8316b` —
  [IAN-3.3] typed unrecognized-caller error contract
  (`UnrecognizedCallerError`).

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
- With `--as NAME` **invalid** (fails `MEMBER_NAME_RE`), `_resolve_member`
  raises `ValueError` from `validate_member_name` — NOT a `TautError` — so
  today it would escape `_bootstrap`'s catch and crash the app
  (review finding R-4).
- `taut/cli.py:_exit_code_for_exception` currently string-matches
  `str(exc) == "unrecognized caller"` → exit 2. The typed error replaces this
  wart with an isinstance check; exit codes must not change
  (`test_cli_set_name_unrecognized_exits_2`, and the `--as` case pins
  `member not found` → 2 via the `NotFoundError` branch).
- `validate_member_name` (`taut/_constants.py:163`) and
  `validate_channel_name` (`taut/_constants.py:170`) raise `ValueError`, and
  thread-shape errors are `ThreadNameError` — so "simple validation → inline"
  vs "identity conflict → CLI guidance" is a clean typed split with no
  message parsing anywhere.
- `join()` resolves with `create=True`, creates absent channels, and applies
  normal identity-capture rules — sufficient for a brand-new project directly
  after [TUI-10.1] init-here.
- `WatchBridge` starts only at the end of a successful `_bootstrap`
  (`app.py`), so no watcher exists in the first-join state; this plan makes
  that invariant executable (review finding R-3).

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
  `NotFoundError` (now load-bearing for the TUI).
- Pin the crash-shaped input: `--as` with an invalid name raises `ValueError`
  from the identity read (load-bearing for the bootstrap catch, R-4).
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
pattern (`#search-input`, `#goto-input`) plus the inbox pattern for surface
swapping.

1. **State flag:** `self._first_join_active: bool = False`. It is the gate
   for everything below and is cleared on success AND on escape.
2. **Compose:** add a hidden first-join container in the center column:
   a guidance `TextStatic` (`#firstjoin-hint`), `Input#firstjoin-name`,
   `Input#firstjoin-channel`, and an inline-error `TextStatic`
   (`#firstjoin-error`). CSS `display: none` defaults.
3. **Trigger wiring in `_bootstrap`:** split the current combined
   `whoami()`/`joined_threads()` try so the identity read is caught
   separately — the catch must be scoped to `whoami()` only, never around
   `joined_threads()`:
   - `except UnrecognizedCallerError` → `self._show_first_join(prefill=None)`
   - `except NotFoundError` (only reachable here when `self._as_name` was
     given, per Task 1 pins) →
     `self._show_first_join(prefill=self._as_name)`
   - `except ValueError as exc` → CLI-first fatal guidance (invalid `--as`
     name; NOT a first-join trigger — the user asked for a specific, invalid
     name; guidance names the constraint) (R-4).
   - `except TautError as exc` → existing CLI-first fatal guidance,
     unchanged. Conflict-shaped `IdentityError`s land here by construction —
     no list of conflict messages exists anywhere in the TUI.
4. **`_show_first_join(prefill)`** (R-5):
   - set `_first_join_active = True`;
   - hide the normal center surfaces the way `_open_inbox` does: transcript
     hidden, composer hidden, inbox hidden; presence/thread-pane hidden;
   - show the container, set the hint text ("first time here — pick a name
     and a channel · esc back · q quits"), clear `#firstjoin-error`,
     prefill the name input, focus name (or channel when prefilled).
5. **Key/binding gate** (R-1): first-join is a modal setup state. In
   `check_action`, when `_first_join_active` is true, return False for every
   surface action that would steal focus or open another transient —
   `toggle_fold`, `toggle_thread_pane`, `focus_composer`, `toggle_members`,
   `open_search`, `open_goto`, `open_inbox`, `open_help` — leaving only
   `quit_app` and `close_transient` live. (`init_here` is already gated by
   `_uninitialized`, which is False here.) `action_close_transient` gets a
   first-join branch FIRST, before the search/goto/help/inbox branches, so
   Escape cannot close a stale transient underneath the form.
6. **Submit flow** (`on_input_submitted` branches):
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
        - `except IdentityError as exc` → leave the form via
          `_exit_first_join()`, then CLI-first guidance fatal: the error
          text plus `use: taut rejoin NAME  or: taut --as NAME join CHANNEL`.
        - `except TautError` → inline error, form stays (recoverable,
          [TUI-10.4]).
     d. Success: `self._as_name = name`, `_exit_first_join()`,
        `await self._bootstrap()`. No optimistic transcript ([TUI-10.7]);
        bootstrap re-reads and starts the watcher normally. The one-shot
        client used for `join()` is discarded; the bootstrap client is the
        session client (mirrors `action_init_here` symmetry).
7. **`_exit_first_join()`** (R-6): single cleanup path used by success,
   escape, and the identity-conflict branch — clear both input values and
   the inline error, hide the container, restore transcript+composer
   display, set `_first_join_active = False`. Escape additionally re-shows
   the identity-guidance fatal (the state the form replaced). Abandoning the
   form leaves zero state behind — enforced by this single exit path.
8. **Watcher invariant** (R-3): no `WatchBridge` may exist while
   `_first_join_active` is true — the form appears strictly before the
   bootstrap success path that starts the bridge. Made executable in Task 3
   (tests 1, 6, 8 assert `app._bridge is None`).

Boundary invariants (unchanged, enforced by existing grep gates + tests):
no SQL/queue/envelope/cursor/membership mutation in `taut/tui`; no changes
to `taut/tui/_launch.py` (non-tty behavior untouched); Textual imports stay
inside `taut/tui` below the lazy import point.

## Task 3 — Tests (`tests/test_tui_recovery.py` unless noted)

Seed for the trigger: `TautClient.init(db_path=db)` with NO member created,
launch `TautApp(db_path=str(db), as_name=None)`.

1. Unrecognized caller in an initialized project → first-join form visible,
   name input focused, no fatal banner, transcript/composer hidden, and
   `app._bridge is None` (R-3).
2. Submit name+channel → lands in normal TUI: nav shows the channel,
   composer label targets it, titlebar set, bridge running.
   (Bounded-poll, real client.)
3. CLI equivalence: after (2), a CLI-style client
   `TautClient(db_path=db, as_name=name)` resolves the same `member_id`
   that `whoami()` reports in-app, and `joined_threads()` shows the channel
   — i.e. the member and join match `taut --as NAME join CHANNEL`.
4. Prefill: `TautApp(db_path=db, as_name="newname")` → form opens with
   `newname` prefilled, channel input focused.
5. Invalid `--as` name at launch (e.g. `"bad name"`) → CLI-first fatal
   guidance, no form, no crash (R-4).
6. Pre-validation inline error: invalid channel shape (e.g. `UPPER`) →
   inline error shown, form still open, app alive, `_bridge is None`; then a
   corrected submit succeeds (recovery, not just rejection).
7. Submit-time error classes at the `join()` call (R-2) — monkeypatch
   `TautClient.join` where constructing the genuine condition is
   disproportionate; the catch branches are the contract under test:
   a. `ThreadNameError` → inline error, form stays.
   b. `MembershipError` → inline error, form stays.
   c. `IdentityError("current identity claim already belongs to x")` →
      form exits, CLI-first guidance fatal (contains `taut rejoin`),
      no crash.
   d. Generic recoverable `TautError` → inline error, form stays.
8. Escape from the form returns to the guidance state, clears input/error
   state, `_bridge is None`; re-entering the form (fresh trigger) shows a
   clean form, not stale values (R-6). `q` still quits from the form.
9. Modal gate (R-1): with the form open, pressing `c`, `/`, `g`, `i`, `?`
   does not move focus off the form inputs and opens no other surface;
   Enter still submits (`Input.Submitted` reached — also the
   priority-binding pin required by [TUI-10.9]).
10. Bootstrap-time conflict (kept from spec expectations): monkeypatch
    `whoami` to raise a conflict-shaped plain `IdentityError` → CLI-first
    guidance, NOT the form.
11. Update `test_empty_state_offers_init_here_and_quit`: after init-here on
    a fresh project the flow now lands in the first-join form (was: fatal
    `taut join` guidance). Chain assertion: init-here → form → submit →
    working TUI — the full journey that motivated the spec.
12. Non-tty launch tests: existing `test_tui_launch.py` suite unchanged and
    green (bare non-tty still help+exit, never prompts).

Client/CLI tests are in Task 1. Every enumerable element of [TUI-10.9] —
both trigger types, prefill, both submit-time failure classes plus the
bootstrap-time classes, modal keyboard behavior, escape/quit, state
cleanup, watcher absence, no-optimism — has a firing test above (DoD).

## Task 4 — Docs and traceability

- `docs/specs/04-taut-tui.md` Related Plans: backlink added at plan time
  (commit alongside this revision), not deferred to implementation (R-7).
- `docs/implementation/05-taut-tui-architecture.md`: add a first-join
  section (state, trigger types, why the typed error exists, modal gate
  rationale, boundary rationale).
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

## Deviation Log

(Empty at plan time. Record any implementation deviation from this plan or
from [TUI-10.9] here, with rationale, as the TUI implementation plan did.)

## Review Log

- 2026-07-07 — Independent plan review (Codex, high reasoning, read-only,
  cross-family per DOM-11). Verdict: "revise then proceed." Findings and
  resolutions, all folded into this revision:
  - R-1 (P1) live global bindings steal focus from the form → Task 2 step 5
    modal gate via `check_action` + escape-ordering; test 9.
  - R-2 (P1) submit-time error classes had no firing tests (prior tests
    fired pre-validation or at bootstrap) → test 7a–d at the `join()` catch.
  - R-3 (P1) watcher-absence invariant not executable → asserted in tests
    1, 6, 8; stated in Task 2 step 8.
  - R-4 (P2) invalid `--as` name raises `ValueError` through bootstrap →
    explicit `except ValueError` branch; client pin in Task 1; test 5.
  - R-5 (P2) normal surfaces (transcript/composer) left visible under the
    form → Task 2 step 4 hides them; test 1 asserts.
  - R-6 (P2) no state cleanup on escape → single `_exit_first_join()`
    cleanup path; test 8.
  - R-7 (P2) missing Spec Baseline / Deviation Log / Related Plans backlink
    → all three added in this revision.
  - R-8 (P3) `validate_channel_name` line cite corrected (163 → 170).
- 2026-07-07 — Independent completed-work review (Codex subagent, read-only).
  Findings folded into the implementation before final gates:
  - first-join success restored normal wide-mode presence visibility after
    leaving the modal form;
  - Escape from a prefilled `--as NAME` form now returns to member-not-found
    guidance that names the selected member;
  - modal-gate tests now exercise every enumerated blocked binding
    (`c`, `/`, `g`, `i`, `?`, `z`, `t`, `m`) and verify resize cannot reveal
    presence while first-join is active.
- 2026-07-07 — Second pre-PR review (Claude, cross-family): verdict
  ship-ready; four P3 cleanups applied afterward:
  - stray out-of-scope `_bridge.py` docstring word-swap reverted;
  - navigation hidden while the modal form is up (Tab could previously move
    focus to the empty nav list) and restored on exit — pinned by tests
    incl. resize-cannot-reveal and Tab-stays-on-form;
  - `_bootstrap`'s `except ValueError` documented as scoped to the invalid
    `--as` name source in `_resolve_member`;
  - unreachable duplicate of the escape-guidance default in `__init__`
    replaced with an empty sentinel plus an invariant comment.

## Risks / hardening notes

- **Contract change** is additive (new subclass, same message/exit codes);
  the only behavioral edit outside the TUI is the exit-code isinstance swap,
  pinned by existing CLI tests.
- **Hidden coupling:** the `NotFoundError` trigger is only unambiguous
  because `_bootstrap` catches it around the *identity read specifically* —
  keep the catch scoped to `whoami()`, never around `joined_threads()`
  (which could surface unrelated not-found conditions).
- **Modal state:** `_first_join_active` is the single source of truth for
  the gate; it is set in exactly one place and cleared in exactly one place
  (`_exit_first_join`). No new persistent state; abandoning the form
  (escape/quit) leaves zero state behind.
- **Anti-mocking:** happy-path and pre-validation tests run the real client
  against a real `.taut.db`; monkeypatching appears only where constructing
  the genuine condition is disproportionate (test 7's join-time classes,
  test 10's bootstrap conflict), and what is under test there is the TUI's
  catch contract, not client behavior.
- **Rollback:** each slice is a clean revert; no migration, no stored state.
