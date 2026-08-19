# TUI Setup-Recovery Offer Plan

Date: 2026-08-19

Status: draft (see `docs/plans/README.md` status index)

Owner: Taut maintainers

Class: 5 (hardened) — the work revises normative [TUI-11.1]/[TUI-11.3]
lease-timing text and the [SUM-13] typed notice model (spec-changing), and
[DOM-5] risky triggers fire: the public `TerminalAttachNotice` contract and
the TUI host-interaction contract change across the source-atomic
`taut-summon`/`taut-tui` pair, and the change touches the asynchronous
foreground worker's mid-run modal path. Hardening checklist applies;
independent review precedes implementation.

Plan type: implementation with spec revision

Promotion strategy: **A — in-file text before implementation-link claims.**

## Goal

When a TUI-owned summon hits a suspected setup gate, the TUI currently
falls through to the enriched give-up error and a shell instruction
(v1 non-support, deliberate). The owner's first real use (2026-08-19,
Kimi trust gate) showed the missing step plainly: "it never asked."

Make the TUI offer the acknowledged setup attach natively, proxying the
provider's own question through the offer, per the owner's sketch:

```
Looks like Kimi needs interaction. Last screen output:

  Trust this folder?
    Trust this folder   Enable project MCP servers. ...
  > Don't trust         Exit Kimi Code. Asked again next launch.

Attach?  [Y]es / [N]o
```

and, on yes, present the four [SUM-13] facts with the plain-language
detach line: "Enter Ctrl-\ Ctrl-\ (Control-Backslash twice) to return to
Taut." The same screen-excerpt proxying improves the shell offer too.

## Requested Outcomes

- [ ] A TUI `:summon kimi` that parks on a trust gate presents a native
  offer naming the member, showing the sequence-stripped last-screen
  excerpt, and asking to attach — instead of four crash-loop exits and a
  give-up error.
- [ ] Yes → the existing acknowledgement facts (setup-not-chat, setup-only,
  detach chord in plain language, run-continues) are shown, Textual
  suspends, the provider's real screen appears, the human answers it,
  detaches with `Ctrl-\ Ctrl-\`, and the TUI restores with the run
  continuing to readiness.
- [ ] No → exactly today's decline semantics: detached continuation, one
  offer per run, enriched give-up if the gate persists.
- [ ] The shell setup-recovery offer gains the same "Last screen output:"
  excerpt block before its Enter/cancel prompt.
- [ ] Bootstrap first-attach behavior, notice compatibility for hosts that
  ignore the new field, and every v1 fall-through path are unchanged.

## Source Documents

Source specs:

- `docs/specs/04-summon.md` [SUM-7.4] (setup-recovery escalation block,
  as revised through 2026-08-19), [SUM-13] (host interaction, notice)
- `docs/specs/10-taut-tui.md` [TUI-11.1], [TUI-11.2], [TUI-11.3],
  [TUI-11.4], [TUI-13.2], [TUI-14]
- `docs/specs/01-development-documentation-operating-model.md` [DOM-5],
  [DOM-15]

Predecessor plans:

- `docs/plans/2026-08-18-summon-setup-gate-recovery-attach-plan.md`
  (active) — built the driver-side escalation this plan exposes in the
  TUI; its invariants 1–14 are inherited unchanged. Its out-of-scope note
  named this successor.
- `docs/plans/2026-08-17-summon-first-attach-handoff-plan.md` (completed)
  — built the TUI modal + suspend lease machinery this plan reuses.

Consulted startup surfaces: same declaration as the predecessor plan
(2026-08-18), plus a re-read of [TUI-11.2]/[TUI-11.3]/[TUI-11.4] and the
owner's 2026-08-19 session direction (offer wording, plain-language
detach hint).

## Spec Baseline

- `3519c568e91483ef8a982186e6cfbe90867f2b1c` — the predecessor plan is
  completed and landed (`f17612b` plus follow-ups, released as the 0.9.4
  pair); both specs at this SHA carry the [SUM-7.4] escalation block and
  the [TUI-11.1] non-support sentence this plan revises.
- Slice 0's changes (below) sit on top of this baseline; land Slice 0 by
  explicit file-list staging (spec sentence, `_pty.py`, its test, this
  plan, index row) and record that commit SHA here.
- Promotion baseline: _pending_

## Slice 0 — output-tail sequence stripping (completed 2026-08-19)

Implemented immediately on owner feedback ("the shell escapes are
distracting"), before this plan's review, as an atomic strategy-B slice:
the owner's first real TUI give-up showed the byte-level control strip
leaking printable residue (`[38;2;..m` SGR parameters, `]8;;` hyperlink
bodies, `[?2026l` mode sets) into the diagnostic tail.

- Spec: `docs/specs/04-summon.md` [SUM-7.4] output-tail paragraph
  rewritten from "control-stripped" to sequence-stripped semantics —
  well-formed in-window CSI/OSC/DCS/SOS/PM/APC and other ESC- or
  C1-introduced sequences removed with their parameter and string
  bodies; well-formed dangling forms at the buffer end dropped, not
  leaked; window-cap truncation and malformed mid-stream forms
  explicitly qualified; C1 introducers recognized only where they
  cannot be UTF-8 continuation bytes; then the existing control-byte
  strip and length bound.
- Code: `extensions/taut_summon/taut_summon/_pty.py` —
  `_TERMINAL_SEQUENCE` compiled byte-regex applied in `output_tail()`
  before decoding; ordered alternation, dangling-form handling.
- Proof (red first): `extensions/taut_summon/tests/test_pty_adapter.py::
  test_output_tail_is_bounded_control_stripped_text` extended with the
  observed Kimi residue shapes (truecolor SGR, OSC-8 hyperlink with URL
  body, private-mode sets, a CSI split across `_observe_output` chunks);
  failed on residue assertions before the regex, green after; full
  `test_pty_adapter.py` and `test_driver.py` suites, summon setup-gate
  interaction tests, mypy, ruff, doc gates all green 2026-08-19.
- This slice matters to the plan body: the excerpt Task 2 carries into
  the notice is readable because of it.

## Current Structure and Key Files

### Driver side (complete; consume, do not modify except where named)

- `extensions/taut_summon/taut_summon/_driver.py` —
  `_should_offer_setup_recovery` gates the offer on
  `interaction.supports_setup_recovery()`; `_orient_running_generation`
  tears the suspect generation down **before** the acknowledgement, so at
  offer time no provider child exists and no watcher has started (the
  suspect generation never oriented). `_prepare_generation_start`
  requests `confirm_terminal_attach` pre-spawn and maps decline/shutdown.
  The recovery generation runs the existing acknowledged attach order.
  The only driver change in this plan: capture the suspect handle's
  `output_tail()` **before** teardown and carry it into the notice.
- `extensions/taut_summon/taut_summon/_pty.py` — `output_tail()` returns
  sequence-stripped bounded text (revised 2026-08-19; the excerpt is
  already display-clean).
- `extensions/taut_summon/taut_summon/interaction.py` —
  `TerminalAttachNotice(member, provider, detach_hint)` frozen dataclass;
  `ShellSummonInteraction.confirm_terminal_attach` prints the four facts
  and reads Enter/cancel.

### TUI side (the work)

- `extensions/taut_tui/taut_tui/summon.py` — `TuiSummonInteraction`:
  `confirm_terminal_attach` posts `TerminalAttachConfirmationRequest`
  (line ~442) to the Textual loop under a coordinator that excludes
  concurrent owners; `terminal_lease` marshals the suspend handshake;
  `supports_setup_recovery()` currently returns `False` (flip to `True`
  in the final slice, after the modal work is proven).
- The TUI modal/screen that renders `TerminalAttachConfirmationRequest`
  (locate via `TerminalAttachConfirmationRequest` handlers in
  `extensions/taut_tui/taut_tui/` — the handler and screen were built by
  the 2026-08-17 plan; read them before editing; they currently render
  the four facts for the bootstrap case).

### Required comprehension gate

Answers in the execution log before editing; expected answers follow.

1. Q: At the moment a setup-recovery acknowledgement request reaches the
   host, what exists for that member, and is the `SummonRunHandle`
   published?
   Expected: the suspect child and pump are torn down and its watcher
   never started (the suspect generation never oriented); the control
   thread and foreground worker remain live. On a **first-generation**
   gate the escalation `continue`s past `_await_running_generation`, so
   readiness has **not** fired and no `SummonRunHandle` exists — the TUI
   is still pending-owned; asserting or waiting on readiness before the
   offer will hang. On a **later-generation** gate a prior generation
   already reached readiness, so the handle exists and the run is
   owned-live. The modal path must work in both states.
2. Q: Why does [TUI-11.3]'s "before provider spawn" wording remain
   satisfiable for setup-recovery?
   Expected: the acknowledgement precedes the spawn of the generation it
   governs (the recovery generation); what changes is only that the
   request can arrive outside the bootstrap acknowledgement window.
3. Q: What happens today if two acknowledgement requests race in the TUI?
   Expected: the coordinator admits one owner; the loser degrades to the
   graceful decline (returns False) rather than erroring the run.

## Invariants and Constraints

1. **Driver escalation semantics are frozen.** Offer conditions, one
   offer per run, decline-continues, shutdown-ends, teardown-before-ask
   — all inherited from the predecessor plan and its promoted [SUM-7.4]
   text. This plan changes who can say yes, not when the question fires.
2. **Notice compatibility.** `TerminalAttachNotice` gains one optional
   field `screen_excerpt: str | None = None`. Hosts that ignore it render
   exactly today's output. No existing positional construction breaks
   (the field is keyword-defaulted, last).
3. **Excerpt is already sanitized and bounded.** The driver passes
   `output_tail()` text through unchanged; hosts must still escape it
   through their normal dynamic-text policy ([TAUT-6.4] posture) because
   it is Taut-owned human text, not terminal transport. The TUI modal and
   the shell must never write it raw to a terminal outside that policy.
4. **First-attach modal unchanged.** Bootstrap acknowledgements carry
   `screen_excerpt=None` and render exactly as today ([TUI-11.1] native
   flow, acknowledgement-before-suspension, concurrent exclusion).
5. **Suspension rules unchanged.** One coordinator, acknowledgement
   before `App.suspend()`, lease failure fatal-and-exit semantics, log
   buffering during the lease, post-restore redraw — all [TUI-11.3]/
   [TUI-11.4] text stays authoritative; this plan widens only *when* the
   request may arrive.
6. **Detach hint ownership.** Summon still owns the semantic hint string
   (`Ctrl-\ Ctrl-\`); the plain-language phrasing ("Control-Backslash
   twice") is host presentation. Do not change the notice's
   `detach_hint` value.
7. **Guarded quit interplay.** While the offer modal is up, the TUI's
   quit chords keep their existing modal-focused behavior; a host-closed
   modal is a decline, not a run error (matches today's bootstrap modal
   host-close row).
8. **Source-atomic pair.** Notice field, shell rendering, driver capture,
   and TUI modal land together; `supports_setup_recovery() -> True` flips
   only in the slice whose tests prove the whole TUI path; the wheel-pair
   matrix gates the landing.
9. **No new escalation surfaces.** No auto-attach, no screen-text
   parsing, no per-provider wording. The excerpt is display-only.

## Rollback, Rollout, and One-Way Doors

- **Rollback:** one revert. Behavioral kill switches already exist at two
  levels: `TAUT_SUMMON_SETUP_RECOVERY=0` (driver-wide) and flipping
  `TuiSummonInteraction.supports_setup_recovery()` back to `False`
  (TUI-only, one line). No storage or identifier changes; the notice
  field is additive.
- **Rollout:** source-atomic pair, same discipline as the predecessor;
  nothing lands while the installed pair would be incompatible.
- **One-way doors:** none.
- **Post-deploy signal:** the owner's Kimi reproduction in the TUI shows
  the offer with the readable excerpt instead of the give-up error; the
  give-up error still appears when the offer is declined and the gate
  persists.

## Proposed Spec Delta

Promotion strategy table:

| Spec file | Strategy | Sections touched |
|-----------|----------|------------------|
| `docs/specs/04-summon.md` | A | [SUM-13] notice sentence (one edit), [SUM-7.4] one sentence on excerpt capture |
| `docs/specs/10-taut-tui.md` | A | [TUI-11.1] replace non-support sentence, [TUI-11.3] one scoping edit, [TUI-13.2] extend matrix row |

### `docs/specs/04-summon.md` [SUM-13] — extend the notice sentence

Replace:

> The notice owns
> semantic fields, including member, provider, and detach hint; hosts own their
> presentation and must escape dynamic text outside the raw lease.

with:

> The notice owns semantic fields, including member, provider, detach
> hint, and — for setup-recovery offers — an optional bounded,
> sequence-stripped excerpt of the suspect generation's final screen
> output; hosts own their presentation, may omit an absent excerpt, and
> must escape dynamic text, the excerpt included, outside the raw lease.

### `docs/specs/04-summon.md` [SUM-7.4] — append one sentence to the escalation block

Append after "...The teardown always precedes the acknowledgement
request, so a person is never deciding while a suspect harness runs.":

> Before that teardown the driver captures the suspect handle's bounded
> output tail and offers it to the host through the acknowledgement
> notice, so the offer can show the provider's own pending question.

### `docs/specs/10-taut-tui.md` [TUI-11.1] — replace the non-support sentence

Replace the sentence block added 2026-08-18 (beginning
"`TuiSummonInteraction` declares no setup-recovery support in version 1"
and ending "...instead of a mid-chat lease.") with:

> `TuiSummonInteraction` declares setup-recovery support
> (`supports_setup_recovery()` is `True`): a [SUM-7.4] setup-recovery
> acknowledgement may reach the TUI outside the bootstrap window, at
> either of two timings. On a first-generation gate — the common case —
> the offer arrives after the suspect generation's teardown but before
> the run handle is published: readiness has not fired and the TUI is
> still pending-owned. On a later-generation gate, the offer arrives
> after readiness on an owned live run. In both timings the request is
> pre-spawn for the generation it governs — the suspect child and pump
> are already gone and its watcher never started — and it uses the same
> native confirmation, coordinator exclusion, and suspension rules as
> the bootstrap acknowledgement. The offer presentation names the
> member, renders the notice's screen excerpt when present (escaped as
> ordinary dynamic text), asks whether to attach, and on proceed — for
> setup-recovery offers only — presents the four required facts with a
> plain-language detach line before suspension (for example "Enter
> Ctrl-\ Ctrl-\ — Control-Backslash twice — to return to Taut").
> Declining or closing the offer is the normal [SUM-7.4] decline: the
> run continues detached and the enriched [SUM-11] give-up remains the
> terminal diagnostic. Host shutdown while the offer is pending takes
> the [SUM-7.4] shutdown class, not the decline class.

### `docs/specs/10-taut-tui.md` [TUI-11.3] — scope the posting sentence

Replace:

> When Summon resolves that an attach will actually occur, the foreground
> worker posts a typed acknowledgement request to the active Textual loop
> before provider spawn.

with:

> When Summon resolves that an attach will actually occur — at bootstrap
> for a first attach, or mid-run for a [SUM-7.4] setup-recovery offer —
> the foreground worker posts a typed acknowledgement request to the
> active Textual loop before the governed generation's provider spawn.

### `docs/specs/10-taut-tui.md` [TUI-11.3] — scope the decision-outcome sentences

Replace:

> The prompt explains provider-only setup, the Summon-supplied detach hint, and
> that Textual resumes and continues owning the run after detach. Confirmation
> resolves the worker request; cancellation ends that foreground run without a
> provider child or terminal lease. Host shutdown resolves any pending prompt
> as cancelled so the foreground worker cannot remain stranded waiting for the
> decision.

with:

> The prompt explains provider-only setup, the Summon-supplied detach
> hint, and that Textual resumes and continues owning the run after
> detach; a setup-recovery offer additionally leads with the member name
> and screen excerpt per [TUI-11.1]. Confirmation resolves the worker
> request. Cancellation follows the decision's [SUM-7.4] class: a
> cancelled bootstrap first-attach ends that foreground run without a
> provider child or terminal lease, while a declined or dismissed
> setup-recovery offer continues the run detached. Host shutdown first
> requests the run's stop so the driver's shutdown event is set, then
> resolves any pending prompt as refused — the foreground worker cannot
> remain stranded, and a shutdown-produced refusal takes the [SUM-7.4]
> shutdown class rather than ending as a decline or a cancel.

### `docs/specs/10-taut-tui.md` [TUI-13.2] — extend the matrix row

Replace the setup-recovery clause (added 2026-08-18, as qualified
2026-08-19) with:

> , and setup-recovery offer handling (mid-run acknowledgement
> confirm/decline/host-close/concurrent exclusion with excerpt
> rendering, suspension and restoration equivalence with the bootstrap
> lease, and the Summon-level proof that a non-supporting host receives
> no mid-run request); and

### Related Plans additions

Both specs: add `docs/plans/2026-08-19-tui-setup-recovery-offer-plan.md`.

## Dependency-Ordered Tasks

### Task 0 — Commit Slice 0, then promote

- Outcome: Slice 0 (worktree) committed with this plan file and its
  index row; then, after independent review, this delta applied per
  strategy A; Related Plans updated; promotion identifier recorded.
- Verify: `uv run --extra dev bin/check-doc-paths`,
  `uv run --extra dev pytest tests/test_docs_references.py -q`,
  anchor-verbatim grep for each replaced sentence.

### Task 1 — Notice field and shell excerpt rendering

- Outcome: `TerminalAttachNotice` gains keyword-defaulted
  `screen_excerpt: str | None = None`;
  `ShellSummonInteraction.confirm_terminal_attach` prints, when the
  excerpt is present, a `Looks like '<member>' needs interaction. Last
  screen output:` block (escaped via the existing
  `escape_terminal_text`, indented, before the existing four facts).
- Files: `extensions/taut_summon/taut_summon/interaction.py`; tests
  `extensions/taut_summon/tests/test_interaction.py` (shape test at
  `test_public_interaction_models_have_exact_stable_shape` gains the
  field; new rendering red test asserting excerpt block order, escaping,
  and absence when `None`).
- Red first: shape assertion and rendering test fail before the field
  exists.
- Verify: `uv run --project extensions/taut_summon --extra dev --locked
  pytest -q extensions/taut_summon/tests/test_interaction.py`.

### Task 2 — Driver: capture the excerpt before teardown

- Outcome: in `_orient_running_generation`'s escalation branch, capture
  `tail = handle.output_tail()` (best-effort, empty on failure) before
  `_teardown_generation`; store on the driver; `_confirm_terminal_attach`
  builds the notice with `screen_excerpt=tail or None` for setup-recovery
  and `None` for first-attach; clear the stored excerpt once consumed.
- Files: `extensions/taut_summon/taut_summon/_driver.py`; tests
  `extensions/taut_summon/tests/test_interaction.py` — extend the
  existing proceed test (`test_setup_gate_offers_single_recovery_attach_
  and_completes_setup`) to assert
  `confirmation_notices[0].screen_excerpt` contains "Trust this
  folder?". For the first-attach `screen_excerpt is None` proof, have
  `_wire_member_through_pretrusted_first_attach` return its interaction
  (it currently constructs and discards a local one) so the caller can
  assert on run 1's recorded notice.
- Stop gate: if excerpt capture wants to move teardown or touch the
  reader, stop — capture is one read of an in-memory buffer.
- Verify: same command as Task 1.

### Task 3 — TUI offer modal and plain-language detach line

- Outcome: the `TerminalAttachConfirmationRequest` handler renders, when
  `notice.screen_excerpt` is present, the owner-sketch offer as a
  two-phase presentation: first `Looks like <member> needs
  interaction.`, the escaped excerpt block, and the attach question;
  then, on yes — for setup-recovery offers only — the existing
  four-facts presentation plus the plain-language line "Enter Ctrl-\
  Ctrl-\ (Control-Backslash twice) to return to Taut." before the
  worker request resolves (presentation only — the notice's
  `detach_hint` value is unchanged, invariant 6). Bootstrap notices
  (`screen_excerpt is None`) render exactly as today.
- Files: `extensions/taut_tui/taut_tui/app.py` (the
  `TerminalAttachConfirmationRequest` handler, ~line 777) and
  `extensions/taut_tui/taut_tui/screens.py` (`ConfirmationScreen`,
  ~line 254); tests `extensions/taut_tui/tests/test_tui_summon.py` and
  the screen tests where the bootstrap modal is already proven.
- Implementation shape (reviewer guidance, accepted): no new screen
  class, coordinator, or lease path — one worker request presented as
  two sequential `ConfirmationScreen` pushes before `resolve`.
- Red first: modal-content test with an excerpt-bearing notice fails
  before rendering exists; bootstrap-notice (no excerpt) content test
  asserts byte-identical rendering to today (invariant 4).
- Stop gate: any new suspension, coordinator, or lease code path — the
  lease machinery must be reused untouched (invariant 5).

### Task 4 — Flip support and prove the full TUI path

- Outcome: `TuiSummonInteraction.supports_setup_recovery()` returns
  `True`; the 2026-08-18 declaration tests updated; full-path proof per
  the promoted [TUI-13.2] row: a real Textual-pilot run against the
  `gate_harness.py` fixture reaches the offer while the run is still
  pending-owned (no readiness wait — comprehension Q1), with no
  injection into the menu; confirm → suspend → gate answered → detach →
  restore → run readiness; decline → detached continuation and enriched
  give-up; modal dismiss / host-close of the *screen* → decline
  semantics; TUI/app shutdown while the offer is pending → the handler
  first requests the run's stop (setting the driver's shutdown event —
  the cancel event already passed to `confirm_terminal_attach`) and
  then resolves refused, so the driver takes the shutdown class and
  spawns nothing (a bare `resolve(False)` without the stop request
  would wrongly continue detached on the daemon worker); concurrent-
  owner exclusion. The later-generation (post-readiness) timing is
  covered at the Summon level by the driver matrix; the TUI proof adds
  one modal-arrival case on an owned-live run only if the pilot harness
  can re-gate the fixture cheaply (gate_harness state-file re-gate), and
  otherwise records the gap explicitly in the execution log.
- Files: `extensions/taut_tui/taut_tui/summon.py`;
  `extensions/taut_tui/tests/test_tui_summon.py` (and the existing fake
  terminal lease boundary helpers per [TUI-13.1] — real controller, real
  scripted/PTY child, no mocking of the lease state machine).
- Red first: flip the declaration last; the full-path test is written
  against `True` and fails while `False` short-circuits the offer.
- Verify: `uv run --project extensions/taut_tui --extra dev --locked
  pytest -q extensions/taut_tui/tests`.

### Task 5 — Traceability reconciliation

- Outcome: implementation-link claims and backlinks; implementation-doc
  update (`docs/implementation/05-taut-summon-architecture.md` setup-gate
  block gains the offer-presentation sentence; `docs/implementation/
  12-taut-tui.md` summon section updated); predecessor plan's
  out-of-scope note annotated as superseded-by-successor for the TUI
  item; status index; full final gate block (same command set as the
  predecessor plan's, both packages).

## Testing Plan

- Harness: the Summon-level machinery reuses
  `extensions/taut_summon/tests/fixtures/gate_harness.py` and the
  `_PtyHostInteraction` family; the TUI level uses the real Textual
  pilot, real controller, real child per [TUI-13.1].
- Must stay real: the lease state machine, coordinator, controller
  status/stop, PTY child, driver threads, `output_tail` capture.
- Narrow fakes permitted: pilot input, clocks via existing knobs, the
  fake terminal modeling the public lease boundary (existing helper).
- Contract proofs by invariant: 2 → shape test; 3 → escaping test with a
  hostile excerpt (embedded sequence text must render escaped); 4 →
  bootstrap-notice byte-identical rendering; 5 → suspension-equivalence
  rows in Task 4; 7 → host-close row; 8 → wheel matrix.

## Verification and Gates

Per-task commands above; final gates are the predecessor plan's full
block (both packages' suites, both statics, wheel matrix, plan index,
doc gates, `git diff --check`) plus manual observation: the owner's Kimi
trust-gate reproduction through the TUI shows the offer, the excerpt,
the attach flow, and the detach line.

## Independent Review Loop

Per the review-loops runbook and the 2026-08-19 session evidence: Grok
first (`grok --cwd ... --sandbox read-only --always-approve
--disable-web-search --output-format json --prompt-file`, restored by
the owner 2026-08-19 after a balance top-up), then Kimi headless
(`kimi -p`, `timeout 1140`, read-only by instruction, post-run tree
check) — Codex is out of quota (owner-reported 2026-08-19). Review
before Task 0's promotion; reviewer existence-checks anchors first.
Disposition loop as in the predecessor plan.

## Review Log

### Round 1 — Grok (different family), 2026-08-19

Command: `timeout 1140 grok --cwd <repo> --sandbox read-only
--always-approve --disable-web-search --output-format json
--prompt-file <prompt>` (grok 1.0.5, restored after balance top-up;
Codex out of quota, owner-reported). Outcome: completed,
`stopReason: end_turn`. Verdict: **blocker: F1, F2**.

| ID | Severity | Finding | Disposition |
|----|----------|---------|-------------|
| F1 | blocker | Promoting only the [TUI-11.3] posting sentence leaves the surviving cancellation/prompt sentences contradicting decline-continues and the two-phase offer | Accepted. Delta gains a second [TUI-11.3] edit scoping decision outcomes by [SUM-7.4] class (bootstrap cancel ends; setup-recovery decline continues; shutdown-produced refusal is shutdown-class) and pointing the offer shape at [TUI-11.1]. |
| F2 | blocker | Plan's readiness model was wrong: a first-generation gate offers **before** handle publication (escalation skips `_await_running_generation`), so "the `SummonRunHandle` remains" was false and an implementer could hang waiting for readiness | Accepted with a correction to the reviewer's own fix: a *later-generation* gate offers after readiness, so both timings are real. [TUI-11.1] delta and comprehension Q1 rewritten to name both states (pending-owned vs owned-live); Task 4 asserts the pending-owned timing. |
| F3 | P2 | Modal dismiss and app teardown both resolve `False` without setting the driver's shutdown event — setup-recovery would wrongly continue detached on the daemon worker during TUI shutdown | Accepted. Task 4 wires host shutdown to request the run's stop before resolving refused, plus a firing row; the second [TUI-11.3] delta edit makes it normative. |
| F4 | P2 | Task 2's `screen_excerpt is None` proof site never sees run 1's notice (helper discards its interaction) | Accepted. Helper returns its interaction; assertions named concretely. |
| F5 | P2 | Slice 0 regex holes: no dangling DCS/SOS/PM/APC form (generic ESC alt leaks string bodies), C1 byte introducers corrupt UTF-8 text (`ś` is C5 9B), window-cap left-edge residue, dangling `ESC (` leaks `(` | Accepted and fixed in Slice 0 immediately (red-first): dangling DCS/SOS/PM/APC and dangling-generic alternates added; C1 introducers guarded by a not-after-UTF-8-lead/continuation lookbehind; spec sentence qualified for window-cap truncation and malformed mid-stream forms; new tests for `ś`/`żółć` text, unterminated DCS, dangling `ESC (`. |
| F6 | P2 | "Adds the plain-language line" readable as changing the bootstrap presentation, violating invariant 4 | Accepted. Scoped to setup-recovery proceeds only, in Task 3 and the [TUI-11.1] delta. |
| F7 | P3 | Handler location should be named; "qualified 2026-08-19" claimed absent from tree | Accepted for naming: `app.py` handler (~777) and `screens.py` `ConfirmationScreen` (~254) now named in Task 3. Rejected on the tree claim: the qualified [TUI-13.2] composition wording is committed at `docs/specs/10-taut-tui.md:942-945` (verified by grep at review time). |
| F8 | nit | Transient "applied to the worktree / uncommitted" prose would freeze false | Accepted. Baseline and Slice 0 prose rewritten as completed-work statements plus a landing instruction. |
| F9 | nit | A second widget/coordinator would be ceremony | Accepted as guidance: Task 3 states one worker request, two sequential `ConfirmationScreen` pushes, no new screen class or lease path. |

Round-2 re-review of the revised delta sections is required before Task
0's promotion (class 4/5 review-before-implementation gate).

### Round 2 — Grok (different family), 2026-08-19

Same invocation form, targeted at the F1/F2/F5 revisions. Outcome:
completed, `stopReason: end_turn`. Verdict: **no blocker**, with an
explicit yes to "could you implement Tasks 1–4 confidently and correctly
against the delta as promoted." Confirmed byte-identical anchors for
both [TUI-11.3] replace-from blocks; confirmed the decision-class
alignment across [TUI-11.1]/[TUI-11.3]/[SUM-7.4]; independently traced
the two offer timings in `_driver.py` (escalation `continue` skips
`_await_running_generation`; readiness publishes only via
`_watch_until_wake`), matching the revised Q1; and probed the revised
`_TERMINAL_SEQUENCE` against the round-1 F5 cases through the production
`output_tail()` (UTF-8 text preserved, unterminated DCS dropped,
dangling `ESC (` not leaked), accepting the window-cap qualification as
the spec's stated remainder.

Review-loop status: all nine round-1 findings dispositioned (eight
accepted and applied, F7's tree claim rejected with grep evidence);
round 2 clean. The review-before-implementation gate is satisfied;
Task 0 may proceed once the owner lands Slice 0.

## Deviation Log

| Spec ref | Planned behavior | Actual behavior | Rationale | Spec proposal |
|----------|------------------|-----------------|-----------|---------------|

## Execution Log

Comprehension-gate answers (recorded before implementation, 2026-08-19):

1. Suspect child and pump are torn down; its watcher never started; the
   control thread and foreground worker remain live. First-generation
   gate: escalation `continue`s past `_await_running_generation`, so
   readiness has not fired, no `SummonRunHandle` exists, and the TUI is
   pending-owned — waiting on readiness before the offer hangs.
   Later-generation gate: a prior generation reached readiness, the
   handle exists, the run is owned-live. Both states must work.
2. The acknowledgement precedes the spawn of the generation it governs
   (the recovery generation); only the arrival window changes.
3. The coordinator admits one owner; the loser degrades to the graceful
   decline (`False`), not a run error.

## Out of Scope

- Auto-attach without acknowledgement (permanently out — [SUM-7.4]
  offer-not-bridge invariant).
- Answering gate questions from the modal itself (proxying *input* — the
  "Trust MCP server? Y/N" the offer displays is answered inside the
  attach, not from Taut chrome). A future keystroke-proxy is its own
  spec conversation.
- Detach-chord changes or configurability (still deliberately unbundled).
- Screen-text parsing, per-provider wording, provider-specific flags.
- Changes to the driver escalation conditions, crash ladder, or wired
  semantics.

## Fresh-Eyes and Hardening Checklist

Invariants before tasks; hidden couplings named (notice compatibility,
coordinator reuse, excerpt escaping, pair atomicity); wrapper-vs-core
(presentation in hosts, semantics in the notice); stop gates per task;
out-of-scope explicit; anti-mocking named; fatal-vs-best-effort (excerpt
capture best-effort, presentation failure fatal as today); post-deploy
signal named; current-structure context with comprehension gate;
rollback/kill-switches before tasks; no one-way doors. Author fresh-eyes
pass: anchors quoted from the current worktree spec text (which includes
the 2026-08-18/19 promotions); Task 3 deliberately defers exact modal
file naming to the comprehension gate because the handler location is
owned by the 2026-08-17 plan's implementation — the implementer must
read it, not guess it.
