# Summon Setup-Gate Detection and Recovery-Attach Plan

Date: 2026-08-18

Status: completed at `f17612b` (see `docs/plans/README.md` status index)

Owner: Taut maintainers

Class: 5 (hardened) — the work edits normative [SUM-7.4], [SUM-11], and
[SUM-13] text and one [TUI-11] compatibility sentence (spec-changing), and
[DOM-5] risky triggers fire independently: the change alters asynchronous
foreground supervision behavior (crash-resume ladder, orientation timing),
revises the public `SummonInteraction` contract across two execution
contexts (shell CLI and TUI host), and its rollout depends on the
source-atomic `taut-summon`/`taut-tui` pairing. Hardening checklist applies;
independent review precedes implementation.

Plan type: implementation with spec revision

Promotion strategy: **A — in-file text before implementation-link claims.**
Promote the reviewed [SUM-7.4]/[SUM-11]/[SUM-13]/[TUI-11.1] requirement text
before code. Implementation mappings and reciprocal code/doc links land with
the implementation slices, not with the text-only promotion.

## Goal

Stop the silent crash loop that occurs when a PTY provider parks on an
interactive setup gate (trust dialog, login, model chooser) instead of a chat
prompt. Motivating incident (2026-08-18): Kimi Code 0.37.2 introduced a
"Trust this folder?" dialog whose default answer, "Don't trust", exits 0.
A wired re-summon skipped the first-attach handoff, orientation injection
pressed Enter into the dialog four times, and the driver gave up with
`harness for 'Kimi' exited 4 times in a row (last exit code 0); giving up` —
a message that made the cause undiagnosable without a manual PTY
reproduction.

Three coordinated changes:

1. **Input-prompt confirmation.** Settle passively publishes whether the
   harness has enabled bracketed paste since spawn. A quiescent screen
   without a confirmed input prompt is treated as a suspected setup gate,
   not as readiness.
2. **Setup-recovery escalation.** When a generation's orientation target is
   a suspected setup gate and an acknowledged human terminal is available,
   the driver offers one acknowledged setup attach — the existing
   first-attach machinery — instead of blindly injecting and spending the
   crash budget. Declining continues today's detached behavior.
3. **Diagnosable give-up.** The crash-ladder give-up error carries a
   bounded, sanitized tail of the harness's final screen output and, for
   attach-capable providers, the exact `taut summon --attach <name>`
   recovery command. (Absorbs the previously chip-tracked "surface harness
   screen on summon give-up" task.)

## Requested Outcomes

- [x] A wired `taut summon kimi` whose harness sits at a trust dialog offers
  the acknowledged setup attach within one settle deadline instead of
  crash-looping four times; completing setup during the attach and detaching
  resumes the normal detached flow and reaches `summoned ...`.
- [x] Declining the offer, running `--detach`, or running without an
  available terminal preserves today's behavior (inject after settle,
  ordinary crash ladder), plus an `awaiting_onboarding`-style STATUS surface
  while the suspected gate is on screen.
- [x] The give-up error names the member, attempt count, last exit code, a
  sanitized bounded tail of the final screen, and the `--attach` recovery
  command when the adapter supports attach.
- [x] Providers that reach a real chat prompt (bracketed paste observed) see
  zero new prompts, zero timing changes, and an unchanged crash ladder.
- [x] The TUI keeps working against the revised `SummonInteraction` contract
  by declaring no setup-recovery support in version 1; its users get the
  enriched give-up message and the CLI `--attach` instruction.

## Source Documents

Source specs:

- `docs/specs/04-summon.md` [SUM-2], [SUM-7.1], [SUM-7.4], [SUM-11],
  [SUM-12], [SUM-13]
- `docs/specs/10-taut-tui.md` [TUI-11.1], [TUI-11.3], [TUI-13.2], [TUI-14]
- `docs/specs/01-development-documentation-operating-model.md` [DOM-5],
  [DOM-10], [DOM-11], [DOM-15]

Predecessor plan (inherited invariants, rollout constraint, spec seams):

- `docs/plans/2026-08-17-summon-first-attach-handoff-plan.md` (completed)

Consulted startup surfaces (read-order declaration per
`docs/agent-context/README.md`): `AGENTS.md`, `docs/program-theory.md`
(A4 no-daemon, A6 precondition-as-contract), 
`docs/agent-context/decision-hierarchy.md`, `docs/agent-context/principles.md`,
`docs/agent-context/engineering-principles.md` (§4, §5, §8, §9, §10, §12),
`docs/agent-context/runbooks/writing-plans.md`,
`docs/agent-context/runbooks/hardening-plans.md`,
`docs/agent-context/runbooks/review-loops-and-agent-bootstrap.md`,
`docs/agent-context/runbooks/testing-patterns.md` (rule 5),
`docs/agent-context/lessons.md`, `docs/lessons.md` (Golden Rules plus dated
entries after the 2026-07-14 watermark in `docs/coalescing.md`),
`docs/implementation/05-taut-summon-architecture.md`,
`docs/implementation/03-agent-inventory.md`.

Load-bearing lessons applied:

- `docs/lessons.md` 2026-08-17 reader-handoff entry: carry passive facts
  (output timestamps, input modes) across reader boundaries; test the full
  handoff, not the endpoints.
- `docs/lessons.md` PTY-settle entry: "quiet before first output is not
  readiness"; this plan extends that to "quiet without an input prompt is
  not injection readiness" without weakening the first-output bound.
- Golden Rule 5 / engineering principle §11: the `SummonInteraction`
  protocol change updates every producer and consumer in one source-atomic
  change; no optional-method fallback survives into the final diff
  (predecessor precedent).

## Spec Baseline

- `7930b2538d212fbcb3a550c56051a1134b3feab8` — `docs/specs/04-summon.md`,
  `docs/specs/10-taut-tui.md`,
  `docs/specs/01-development-documentation-operating-model.md` at plan
  authoring time.

This plan revises the spec (`Plan type: implementation with spec revision`).
After the spec-promotion slice lands, record the promotion baseline
identifier here:

- Promotion baseline: diff base `7930b2538d212fbcb3a550c56051a1134b3feab8`
  plus worktree state at 2026-08-18 with the full delta applied to
  `docs/specs/04-summon.md` (seven [SUM-7.4] edits, one [SUM-11] edit, two
  [SUM-13] edits) and `docs/specs/10-taut-tui.md` ([TUI-11.1] append,
  [TUI-13.2] extension), verified by `bin/check-doc-paths` and
  `tests/test_docs_references.py`; landed at `f17612b`.

## Current Structure and Key Files

### Summon-owned core path (all under `extensions/taut_summon/taut_summon/`)

- `_driver.py` — foreground supervision. Load-bearing today:
  - `_supervise` (~line 746): the generation loop. Resolves availability
    once (`_terminal_availability`, PREFERRED intent unless `--attach`),
    computes one attach decision per generation
    (`_prepare_generation_start` → `_resolve_generation_attach`, ~1520–1567;
    `should_attach` requires `first_generation` and either `request.attach`
    or not-wired + `AVAILABLE`), spawns via `_start_live_generation`
    (~824–871), orients via `_orient_running_generation` (~940, which calls
    `_settle_for_orientation` → `handle.wait_until_quiet()` then
    `handle.inject(system_prompt)`), then waits in
    `_await_running_generation`.
  - `_resume_after_harness_exit` (~1002–1031): the crash ladder. A run
    shorter than `_HEALTHY_RUN_SECONDS = 60.0` increments
    `consecutive_crashes`; more crashes than `len(self._backoff)`
    (default `(1.0, 2.0, 4.0)`, env `TAUT_SUMMON_RESUME_BACKOFF`) raises
    `DriverError("harness for '<name>' exited N times in a row (last exit
    code C); giving up")`.
  - `_prepare_generation_attach` (~910–938): runs the bridge on
    `should_attach`, marks `set_wired(True)` on `"detached"`, calls
    `handle.mark_awaiting_onboarding()` when still unwired.
  - `_confirm_terminal_attach` (~1569): builds `TerminalAttachNotice`
    (member, provider, detach hint `Ctrl-\ Ctrl-\`) and calls
    `interaction.confirm_terminal_attach(notice, cancel=self._shutdown)`.
  - Today, a cancelled acknowledgement ends the run
    (`_prepare_generation_start` returns `None` → `_supervise` returns 0).
    That semantics stays true for the first-attach decision and is
    deliberately different for setup recovery (see delta).
- `_pty.py` — PTY adapter and handle. Load-bearing today:
  - `_TerminalInputModeTracker` (~144): parses `CSI ?2004 h/l`, maintains
    `bracketed_paste`; fed from `PtyHandle._observe_output` (~545) which
    also stamps `_last_output_ts`.
  - `PtyHandle.wait_until_quiet` (~261): the settle wait (quiet `quiet_ms`
    default 500 ms, aggregate `max_settle_s` default 10 s), which also
    waits for first observed output per the cold-start bound.
  - `PtyHandle.inject` (~370): sanitizes, frames with bracketed paste when
    `_bracketed_paste` is set, appends `\r`.
  - `PtyHandle.status_fields` / `mark_awaiting_onboarding` (~250): the
    existing STATUS surface for onboarding.
  - There is **no** retained output tail today; output bytes flow through
    `_observe_output` to the responder and tracker and are dropped.
- `_adapter.py` — `ProviderAdapter` protocol (name, `supports_attach`,
  `orientation_via_inject`, `spawn`) and `AdapterHandle` usage. The
  `AdapterHandle` protocol (defined here) is what `_driver.py` types
  against; any new handle member must be added to the protocol and to every
  shipped handle (PTY, scripted, claude-stream).
- `interaction.py` — `SummonInteraction` protocol
  (`terminal_availability`, `confirm_terminal_attach`, `terminal_lease`),
  `TerminalAttachNotice` (member, provider, detach_hint),
  `ShellSummonInteraction` (fd-0-tty availability rules, Enter-to-proceed
  acknowledgement with cancel-event select loop and Windows branch, no-op
  lease over fds 0/1).

### TUI-owned rich-host path

- `extensions/taut_tui/taut_tui/summon.py` — `TuiSummonInteraction`
  (~494): implements the same protocol; acknowledgement marshals a native
  modal to the Textual loop before provider spawn; the lease suspends the
  app ([TUI-11.3] is normatively bootstrap-scoped: acknowledgement "before
  provider spawn", lease "only after confirmation and provider bootstrap").
  This plan adds only a `supports_setup_recovery()` returning `False`.

### Kimi reproduction evidence (2026-08-18, this session)

- `~/.kimi-code/workspace-trust/` held no entry for the working directory;
  Kimi 0.37.2 (self-updated 2026-08-18 17:33 local) renders a full-screen
  trust menu, ignores typed text, default-selects "Don't trust", exits on
  Enter with code 0, and does **not** enable bracketed paste while the menu
  is up. Kimi's rollout log recorded the four driver launches ~3–6 s apart,
  matching the default backoff ladder.

### Required comprehension gate

The implementer answers these in the execution log before editing; expected
answers follow each question. A wrong answer blocks implementation until the
cited owner text is reread.

1. Q: In today's `_supervise`, what are the two ways a generation can end
   without spending the crash budget, and which one does a cancelled
   first-attach acknowledgement take?
   Expected: shutdown paths (`_shutdown` checks) and the
   `attach_decision is None` cancel path; a cancelled first-attach
   acknowledgement returns `None` from `_prepare_generation_start` and
   `_supervise` returns 0 — the run ends cleanly, nothing is spawned.
2. Q: Why does the settle step (`wait_until_quiet`) not read the PTY
   master, and which component is the sole master reader during a detached
   generation?
   Expected: [SUM-7.4] requires exactly one master reader at a time; during
   detached operation the pump's event stream owns the master, so settle
   only observes `last_output_ts` published by that reader.
3. Q: When the driver injects orientation and the harness has not enabled
   bracketed paste, what exactly does `PtyHandle.inject` submit?
   Expected: sanitized text with LFs collapsed to spaces and exactly one
   trailing `\r` — a single Enter-terminated turn (this is the keystroke
   that answered Kimi's trust dialog).
4. Q: After a provider crash, may the driver call
   `interaction.terminal_availability` again under the promoted delta?
   Expected: no — cached availability is still resolved exactly once per
   foreground run; setup recovery reuses the cached value and only adds an
   acknowledgement plus lease within the existing interaction contract.

## Invariants and Constraints

Named before tasks; each maps to a firing test or an inspection gate in the
testing plan.

1. **No silent bridge.** Every terminal bridge is preceded by an explicit
   host acknowledgement. Screen-readiness heuristics may cause Summon to
   *offer* an attach; they never start one. (Revision of the [SUM-7.4]
   "never by screen-readiness heuristics" sentence is scoped to exactly
   this: heuristics gain offer power, not bridge power.)
2. **Single master reader.** Unchanged: the bridge during attach, the
   pump's reader otherwise. The escalation path never bridges a generation
   whose pump reader is live — it tears the suspect generation down and
   runs a fresh generation through the existing acknowledged attach order.
   No new pump-pause or reader-handoff machinery.
3. **Availability is resolved once per foreground run.** Setup recovery
   reuses the cached `AVAILABLE`; it never calls
   `terminal_availability` again and never re-derives host state.
4. **At most one setup-recovery attempt per foreground run**, and it is
   consumed whether the human proceeds or declines. Declining is a normal
   mid-run result: the driver continues the detached path (inject after
   settle, ordinary crash ladder). It does not end the run and does not
   re-prompt.
5. **Confirmed-prompt generations are untouched.** When bracketed paste has
   been observed since spawn, orientation timing, injection framing, crash
   ladder, and give-up behavior are byte-for-byte today's behavior.
6. **Compatibility for paste-less providers.** A provider that never
   enables bracketed paste still receives orientation after the existing
   settle bound whenever no escalation offer is possible (headless,
   `--detach`, nested host, unsupported host, kill-switch, declined, or
   already consumed). Inject-anyway remains the terminal fallback in every
   branch.
7. **First-attach semantics unchanged.** The not-wired first-generation
   decision, its acknowledgement, its cancel-ends-run semantics, and
   `wired=True` staying downstream of a complete detach are untouched.
   Setup recovery is a distinct, additional decision with its own spec
   text — not a second computation of the first-attach decision.
8. **Slow-start protection unchanged.** The detached cold start still waits
   for first observed output or the aggregate settle maximum (predecessor
   invariant, commit `c8e61f4b` protection). Input-prompt confirmation adds
   a fact to settle's outcome; it does not shorten or lengthen either
   bound.
9. **Foreground-only.** No daemonization, ownership transfer, or detached
   service creeps in (program theory A4, [TUI-14]).
10. **Error-path priorities.** Failing to capture or sanitize the output
    tail is best-effort and never masks or replaces the give-up
    `DriverError`; acknowledgement presentation failure remains fatal to
    the foreground run (unchanged [SUM-13]); teardown failures keep their
    existing fatal semantics.
11. **Sanitized human text.** The output tail embedded in the give-up error
    is control-stripped printable text (ESC, C0 except LF, C1, DEL removed)
    and bounded before it reaches any log, stderr, or host surface
    ([TAUT-6.4] posture: the error is Taut-owned human text, not terminal
    transport).
12. **Protocol changes are source-atomic.** `SummonInteraction` gains
    `supports_setup_recovery()` in the same change across shell and TUI
    implementations; no `getattr` optional-method fallback survives into
    the final diff. Rollout is a coordinated `taut-summon`/`taut-tui` pair
    (wheel-matrix gated), exactly like the predecessor plan.
13. **STATUS keys are additive and collision-checked.** Any new
    adapter STATUS field obeys the existing key-collision test.
14. **No provider-specific screen parsing.** Detection uses only the
    passively tracked bracketed-paste input mode. No matching on dialog
    text, provider names, or screen content (predecessor out-of-scope item
    stays out).

## Rollback, Rollout, and One-Way Doors

Written before the task list, per the hardening runbook.

- **Rollback unit.** One revert of the code+spec change restores today's
  behavior; there are no storage, schema, ledger, or identifier changes
  (the `wired` flag and session ledger are reused as-is). No data
  migration; no one-way doors.
- **Behavioral kill-switch without release.** Env knob
  `TAUT_SUMMON_SETUP_RECOVERY=0` disables the escalation offer (branch 6 of
  invariant 6 applies; give-up enrichment remains). Pattern and naming
  follow the existing `TAUT_SUMMON_RESUME_BACKOFF` test/ops knob, documented
  in the same `_driver.py` module docstring block.
- **Rollout sequencing.** Source-atomic across `taut-summon` and
  `taut-tui`: the protocol method, its shell implementation, and the TUI
  `False` implementation land together; the wheel-pair matrix
  (`uv run --extra dev pytest tests/test_core_summon_wheel_matrix.py -q`)
  is the compatibility gate. Development may stage the driver work in a
  worktree slice before the TUI method exists, but nothing is landed or
  built while the pair is incompatible (predecessor constraint, verbatim).
- **Post-deploy observability.** Success signals: (a) the exact incident
  reproduction — wired Kimi with a revoked trust entry — reaches the
  acknowledgement offer instead of the give-up error; (b) give-up errors in
  the field now carry a screen tail (grep-able marker `last screen
  output:`); (c) no change in summon startup timing for paste-confirmed
  providers (existing conformance timing tests stay green).

## Proposed Spec Delta

Promotion strategy table:

| Spec file | Strategy | Sections touched |
|-----------|----------|------------------|
| `docs/specs/04-summon.md` | A — in-file, text before link claims | [SUM-7.4] seven edits (five replacements, one insertion, one append), [SUM-11] one edit, [SUM-13] two edits |
| `docs/specs/10-taut-tui.md` | A — in-file, text before link claims | [TUI-11.1] one appended sentence, [TUI-13.2] one extended bullet |

Every edit below names its anchor by quoting the exact current sentence(s)
it replaces or abuts. The promotion slice applies these without
implementation-link claims; reciprocal links land with the code slices.

### `docs/specs/04-summon.md` [SUM-7.4] — replace the bridging-decision sentence

Replace:

> Whether a human is bridged is decided by the durable `wired` flag plus a
> [SUM-13] host-interaction adapter, never by screen-readiness heuristics.

with:

> Whether a human is bridged is decided by the durable `wired` flag, the
> single setup-recovery escalation defined below, and a [SUM-13]
> host-interaction adapter. Screen-readiness observations may cause Summon
> to offer an acknowledged attach; they never start a bridge, and no bridge
> ever begins without an explicit host acknowledgement.

### `docs/specs/04-summon.md` [SUM-7.4] — replace the first-generation-only paragraph

Replace:

> Attach is first-generation only. A post-crash resume does not re-grab
> the terminal. During attach the driver starts no event pump and no
> watcher; there is exactly one master reader at a time: the bridge during
> attach, then the driver's reader after detach. Chat that arrives during
> attach is not injected until the watcher starts after detach.

with:

> Attach occurs in exactly two cases: the first-generation attach decision
> (unchanged below) and at most one setup-recovery attach per foreground
> run (defined below). An ordinary post-crash resume does not re-grab the
> terminal. During any attach the driver starts no event pump and no
> watcher; there is exactly one master reader at a time: the bridge during
> attach, then the driver's reader after detach. Chat that arrives during
> attach is not injected until the watcher starts after detach.

### `docs/specs/04-summon.md` [SUM-7.4] — revise the acknowledgement-exclusions sentence

Replace:

> Forced detach, a wired automatic run, unsupported attach, and later crash
> generations never request acknowledgement.

with:

> Forced detach, a wired automatic run, and unsupported attach never
> request acknowledgement. Later generations request acknowledgement only
> for the single setup-recovery escalation defined below; ordinary crash
> resumes never do.

### `docs/specs/04-summon.md` [SUM-7.4] — scope the cancellation paragraph to the first-generation decision

In the "Pre-attach acknowledgement." region, replace:

> Cancellation is a normal pre-spawn end. It starts no provider child,
> terminal lease, event pump, control loop, watcher, or readiness callback
> and never marks the session wired.

with:

> For the first-generation attach decision, cancellation is a normal
> pre-spawn end. It starts no provider child, terminal lease, event pump,
> control loop, watcher, or readiness callback and never marks the session
> wired. A declined setup-recovery acknowledgement is governed by the
> escalation block below: it never ends the run and its suspect generation
> was already torn down before the decision was requested.

### `docs/specs/04-summon.md` [SUM-7.4] — replace the cached-availability sentence

Replace:

> The same cached availability is reused after a provider crash; no later
> generation reacquires a host lease or requests acknowledgement.

with:

> The same cached availability is reused after a provider crash. No
> generation ever reacquires availability; the setup-recovery escalation
> reuses the cached value and is the only later-generation path that may
> request acknowledgement and a scoped lease.

### `docs/specs/04-summon.md` [SUM-7.4] — insert setup-recovery escalation block

Insert a new bold-led paragraph block immediately after the
"Pre-attach acknowledgement." paragraph (after the sentence ending
"...never request acknowledgement." as revised above):

> **Setup-recovery escalation.** Settle publishes one additional passively
> observed fact per generation: whether the harness has enabled bracketed
> paste since spawn (the input prompt is *confirmed*). A generation that
> reaches its settle outcome without a confirmed input prompt is a
> suspected interactive setup gate — trust, login, or model onboarding —
> because injecting orientation would submit an Enter keystroke into an
> unknown full-screen dialog. When every escalation condition holds —
> the adapter supports attach and orients via injection, the run is not
> `--detach`, cached availability is `AVAILABLE`, the host interaction
> declares setup-recovery support, `TAUT_SUMMON_SETUP_RECOVERY` is not
> `0`, and no setup-recovery attempt has been consumed in this foreground
> run — the driver does not inject. It tears the suspect generation down
> through the ordinary generation teardown, requests the same typed
> pre-spawn acknowledgement, and on proceed runs one fresh generation
> through the acknowledged attach order (`acknowledge → spawn → rejoin →
> ensure_threads → attach → detach → set_wired(True) → pump.start →
> settle → inject orientation → watcher`). The teardown always precedes
> the acknowledgement request, so a person is never deciding while a
> suspect harness runs. Declining consumes the single attempt and is a
> normal mid-run result: the driver starts the next generation detached
> and injects orientation after that generation's settle exactly as
> today; the run does not end and no second offer is made. A `False`
> acknowledgement produced by driver shutdown rather than a human decline
> follows the ordinary shutdown path — nothing further is spawned and
> nothing is injected. When any escalation
> condition fails, the driver injects after the settle bound exactly as
> today — providers that never enable bracketed paste retain today's
> behavior — and, while unconfirmed, surfaces the suspected gate through
> the existing `awaiting_onboarding` log-plus-STATUS surface. The
> escalation consumes no harness crash budget; the input-prompt fact is
> passive, per-generation, and never read from the master by settle
> itself.

### `docs/specs/04-summon.md` [SUM-7.4] — append output-tail diagnostic to the ears/orientation block

Append to the paragraph ending "Terminal mode is unsupported for PTY.":

> The PTY handle additionally retains a bounded tail of raw harness output
> (final bytes only, fixed cap) for diagnostics. The tail is exposed as
> control-stripped printable text: ESC, DEL, all C0 controls except LF,
> and all C1 controls are removed and the result is length-bounded before
> it reaches any log, error, or host surface. Tail capture is best-effort
> and read-only; it never emits terminal replies, never blocks the reader,
> and its failure never changes a driver outcome.

### `docs/specs/04-summon.md` [SUM-11] — extend the harness-crash bullet

Replace the first bullet's text:

> - Harness crash: driver observes `exit`, marks ledger, attempts one
>   resume (session id, then cursor replay); repeated crashes back off and
>   exit with the reason on ctrl_out and stderr. Never auto-posts to chat
>   as the member.

with:

> - Harness crash: driver observes `exit`, marks ledger, attempts one
>   resume (session id, then cursor replay); repeated crashes back off and
>   exit with the reason on ctrl_out and stderr. Never auto-posts to chat
>   as the member. A suspected setup gate escalates before injection per
>   [SUM-7.4] setup-recovery instead of spending crash budget. The
>   give-up error names the member, the consecutive-exit count, the last
>   exit code, the bounded sanitized tail of the final screen output when
>   the adapter retains one, and — when the adapter supports attach — the
>   exact `taut summon --attach <name>` recovery command.

### `docs/specs/04-summon.md` [SUM-13] — extend the host-interaction paragraph

In the paragraph beginning "A host interaction reports terminal
availability, presents one typed pre-spawn acknowledgement only when the
driver has resolved an actual attach, and grants a later scoped lease
containing input/output fds.", replace that opening sentence with:

> A host interaction reports terminal availability, declares through
> `supports_setup_recovery()` whether it can present acknowledgements and
> grant leases after its host has left bootstrap, presents one typed
> pre-spawn acknowledgement only when the driver has resolved an actual
> attach — first-generation or [SUM-7.4] setup-recovery — and grants a
> later scoped lease containing input/output fds.

and append to the same paragraph, immediately before the existing sentence
"A rich TUI host that wants a nonblocking managed driver must define
process supervision, terminal-release handshake, log routing, exit policy,
and rollback in its own spec; Taut's first such host is governed by
`docs/specs/10-taut-tui.md` [TUI-11] rather than by guessed Summon
behavior." (that sentence is preserved verbatim):

> The shell interaction declares setup-recovery support; a host that
> declares no support never receives a mid-run acknowledgement request.
> For a setup-recovery acknowledgement, an explicit human decline is a
> normal mid-run result that continues the detached path rather than
> ending the run; a refusal produced by driver shutdown follows the
> ordinary shutdown outcome and spawns nothing; a presentation failure
> remains fatal and never falls through to attach.

### `docs/specs/04-summon.md` [SUM-13] — extend the shell-first attach matrix sentence

Replace:

> The shell-first attach matrix additionally proves acknowledgement
> precedes provider spawn, cancel and prompt failure spawn no child or
> lease, attach output survives the reader handoff without duplicate
> terminal replies, bracketed-paste framing survives detach, and listener
> readiness follows the retained quiet interval rather than the no-output
> maximum.

with:

> The shell-first attach matrix additionally proves acknowledgement
> precedes provider spawn, cancel and prompt failure spawn no child or
> lease, attach output survives the reader handoff without duplicate
> terminal replies, bracketed-paste framing survives detach, and listener
> readiness follows the retained quiet interval rather than the no-output
> maximum. The setup-recovery matrix proves: an unconfirmed input prompt
> with a supporting host offers exactly one acknowledged recovery attach
> and injects nothing beforehand; proceed tears down the suspect
> generation, completes setup through the bridge, and reaches watcher
> readiness; decline, `--detach`, kill-switch, non-`AVAILABLE`
> availability, and a non-supporting host each fall through to today's
> inject-after-settle behavior with at most one offer per run; a
> confirmed input prompt changes nothing; and the give-up error carries
> the bounded sanitized tail plus the `--attach` instruction.

### `docs/specs/10-taut-tui.md` [TUI-11.1] — append one sentence

Append to the [TUI-11.1] paragraph:

> `TuiSummonInteraction` declares no setup-recovery support in version 1
> (`supports_setup_recovery()` is `False`): the TUI presents
> acknowledgements only during Summon bootstrap per [TUI-11.3], and a
> suspected setup gate on a TUI-owned run surfaces through the enriched
> [SUM-11] give-up diagnostics and the shell `taut summon --attach <name>`
> instruction instead of a mid-chat lease.

### `docs/specs/10-taut-tui.md` [TUI-13.2] — extend the Summon matrix bullet

Append to the [TUI-13.2] Summon firing-matrix bullet (the one enumerating
"pre-spawn attach acknowledgement confirm/cancel/host-close/concurrent
exclusion, ..."):

> , and setup-recovery non-support (the TUI interaction reports
> `supports_setup_recovery()` false and receives no mid-run
> acknowledgement request across a suspected-gate run)

### Related Plans additions

- `docs/specs/04-summon.md` `## Related Plans`: add
  `docs/plans/2026-08-18-summon-setup-gate-recovery-attach-plan.md`.
- `docs/specs/10-taut-tui.md` related-plans block: add the same entry.

## Dependency-Ordered Tasks

Each task is a review boundary with red-green discipline (engineering
principle §10; any exception names its testing-patterns rule 5 substitute
inline). Stop-and-re-evaluate gates are embedded per task.

### Task 0 — Spec-promotion slice (strategy A)

- Outcome: every delta section above applied to
  `docs/specs/04-summon.md` and `docs/specs/10-taut-tui.md`, with no
  implementation-link claims; `## Related Plans` updated in both specs;
  promotion baseline identifier recorded in this plan.
- Files: `docs/specs/04-summon.md`, `docs/specs/10-taut-tui.md`, this plan.
- Verify: `uv run --extra dev pytest tests/test_docs_references.py -q`,
  `bin/check-doc-paths`, `git diff --check`; inspection that each replaced
  sentence was found verbatim (a failed anchor match is a stop gate — the
  spec moved under the plan; re-baseline before editing).
- Proof style: docs-only; verification by inspection plus the doc gates
  (rule 5 substitute: the promotion diff itself is the reviewable artifact;
  pre-change failure is not observable for prose).
- Blocked by: independent review of this plan and delta (see review loop).

### Task 1 — PTY handle: input-prompt fact and bounded output tail

- Outcome: `PtyHandle` exposes `input_prompt_observed: bool` (True iff
  `CSI ?2004h` observed since spawn, latched — a later `?2004l` does not
  unconfirm) and `output_tail() -> str` (control-stripped printable text
  from a fixed-cap raw ring buffer fed in `_observe_output`; cap 4096 raw
  bytes, rendered tail bounded to 1024 characters).
- Files: `extensions/taut_summon/taut_summon/_pty.py`;
  tests `extensions/taut_summon/tests/test_pty_adapter.py`.
- Read first: `_observe_output`, `_TerminalInputModeTracker`, the existing
  sanitizer `_sanitize_for_pty` (reuse its control-stripping discipline;
  write a byte-oriented sibling rather than round-tripping through it).
- Red first: feed a fake harness that (a) draws a menu without paste mode —
  assert `input_prompt_observed` is False and `output_tail()` contains the
  menu text with controls stripped; (b) enables paste mode — assert
  latched True; (c) emits > 4096 bytes — assert only the tail survives and
  the rendered form is ≤ 1024 chars; (d) emits invalid UTF-8 — assert
  replacement, no exception.
- Invariants protected: 8, 10, 11. Tail capture must not add reads,
  replies, or blocking to the reader path (inspection gate: the diff
  touches `_observe_output` only additively).
- Stop gate: if the tail requires touching the responder or reply path in
  any way, stop — the design is drifting into invariant 2 territory.
- Verify: `uv run --project extensions/taut_summon --extra dev --locked
  pytest -q extensions/taut_summon/tests/test_pty_adapter.py`.

### Task 2 — Adapter handle protocol: extend every producer together

- Outcome: `AdapterHandle` protocol gains `input_prompt_observed`
  (property) and `output_tail()`; the structured-adapter implementation
  lands once on `StreamJsonHandle` in `_stream.py` — the shared base that
  `ScriptedHandle` (`_scripted.py`) and `ClaudeHandle` (`_claude.py`)
  inherit — returning the vacuous values (`True`, `""`) with a one-line
  docstring noting [SUM-7.1] orientation gating means the driver only
  consults them on `orientation_via_inject` adapters.
- Files: `extensions/taut_summon/taut_summon/_adapter.py`,
  `_stream.py`; tests
  `extensions/taut_summon/tests/test_scripted_adapter.py`,
  `test_claude_adapter.py` (conformance assertions that the members exist
  and return the vacuous values on both concrete handles). Any
  handle-shaped structural test double found by
  `grep -rn "def wait_until_quiet\|def inject" extensions/taut_summon/tests`
  gains the members in the same change.
- Red first: mypy fails on the protocol addition until every handle
  implements it; add the conformance assertions before the
  implementations.
- Invariant protected: 12 (all producers in one change).
- Verify: `uv run --extra dev mypy extensions/taut_summon/taut_summon
  extensions/taut_summon/tests` plus the two test files.

### Task 3 — Interaction contract: `supports_setup_recovery()`

- Outcome: `SummonInteraction` protocol gains
  `supports_setup_recovery() -> bool`; `ShellSummonInteraction` returns
  True; `TuiSummonInteraction` returns False; every structural test
  interaction gains the method in the same change — at minimum
  `_PtyHostInteraction`, `_GatedPtyHostInteraction`, and
  `_GatedAttachDecisionInteraction` in
  `extensions/taut_summon/tests/test_interaction.py`, plus every
  `confirm_terminal_attach`-bearing double surfaced by
  `grep -rln "def confirm_terminal_attach" extensions/taut_summon/tests
  extensions/taut_tui/tests`.
- Files: `extensions/taut_summon/taut_summon/interaction.py`,
  `extensions/taut_tui/taut_tui/summon.py`; tests
  `extensions/taut_summon/tests/test_interaction.py`,
  `extensions/taut_summon/tests/test_driver.py`,
  `extensions/taut_tui/tests/test_tui_summon.py`.
- Red first: protocol-conformance test asserting both shipped
  implementations expose the method with the specified values fails before
  the implementations land.
- Invariant protected: 12. Stop gate: if any call site wants
  `getattr(..., default)`, stop — that is the forbidden optional-method
  fallback; fix the type instead.
- Verify: the two test files plus both mypy invocations from the final
  gate block.

### Task 4 — Driver: escalation branch, decline path, kill-switch

- Outcome: after `_settle_for_orientation`, on `orientation_via_inject`
  adapters the driver consults `handle.input_prompt_observed`, then takes
  exactly one of three transitions, expressed as a single typed
  result carried through `_supervise` (no ad-hoc flags):
  1. **Confirmed, or any escalation condition failed** → inject into the
     *current* generation as today; while unconfirmed, call
     `mark_awaiting_onboarding()`. No teardown, no offer.
  2. **Offer made** → tear down the suspect generation via the existing
     teardown helper *before* requesting acknowledgement (a person never
     decides while a suspect harness runs), then request
     `confirm_terminal_attach`. The offer is consumed now, regardless of
     outcome. Proceed → one recovery generation through the existing
     acknowledged attach path (`_resolve_generation_attach` gains an
     explicit setup-recovery input rather than a second decision
     computation — invariant 7). Explicit human decline → start the next
     generation detached; that generation takes transition 1 (the consumed
     attempt fails the conditions), so it injects after its own settle and
     surfaces `awaiting_onboarding` while unconfirmed.
  3. **Acknowledgement returned `False` because of driver shutdown**
     (`self._shutdown.is_set()`) → the ordinary shutdown outcome; nothing
     further is spawned and nothing is injected. Only an explicit human
     decline continues the run.
  `TAUT_SUMMON_SETUP_RECOVERY=0` short-circuits the offer (transition 1);
  document the knob beside `TAUT_SUMMON_RESUME_BACKOFF` in the module
  docstring.
- Files: `extensions/taut_summon/taut_summon/_driver.py`; tests
  `extensions/taut_summon/tests/test_driver.py` plus a gate-harness
  fixture under `extensions/taut_summon/tests/fixtures/` (see testing
  plan).
- Read first: `_supervise`, `_orient_running_generation`,
  `_prepare_generation_start`, `_prepare_generation_attach`,
  `_teardown_generation`; the comprehension gate answers must be recorded
  before this task.
- Red first, in order: (a) suspected gate + supporting shell interaction →
  acknowledgement text appears before any injection and no `\r` reaches
  the fixture child pre-acknowledgement, and the suspect child is reaped
  before the acknowledgement text appears; (b) proceed → fixture completes
  setup during bridge, detach reaches watcher readiness (`summoned` path);
  (c) decline → exactly one offer, a fresh detached generation,
  inject-anyway, fixture exits, ladder runs, run ends with the give-up
  error; (d) confirmed-prompt fixture → zero offers, unchanged flow;
  (e) kill-switch env → zero offers; (f) `--detach` and non-`AVAILABLE`
  availability → zero offers; (g) once-per-run across a
  later-generation second gate; (h) shutdown signalled while the
  acknowledgement is pending → clean shutdown outcome, no further spawn,
  no injection.
- Stop gates: any need to pause or hand off a live pump reader (invariant
  2); any second computation of the first-attach decision (invariant 7);
  any new call to `terminal_availability` (invariant 3); orientation-path
  changes observable in case (d)'s confirmed-prompt timing assertions
  (invariant 5).
- Verify: `uv run --project extensions/taut_summon --extra dev --locked
  pytest -q extensions/taut_summon/tests/test_driver.py`.

### Task 5 — Give-up diagnostics

- Outcome: the `DriverError` raised at ladder exhaustion appends, when
  available: `last screen output:` plus the bounded sanitized
  `output_tail()`, and, when `adapter.supports_attach`,
  `provider may be waiting on interactive setup; run: taut summon
  --attach <member>`. Tail retrieval failures are swallowed (best-effort,
  invariant 10) — the original message always survives.
- Files: `extensions/taut_summon/taut_summon/_driver.py`
  (`_resume_after_harness_exit`); tests
  `extensions/taut_summon/tests/test_driver.py`.
- Red first: ladder-exhaustion test asserts the marker, the tail content
  from the fixture's final screen, the `--attach` line, and — with a
  handle whose `output_tail` raises — the unmodified base message.
- Verify: same command as Task 4.

### Task 6 — Traceability reconciliation and docs

- Outcome: implementation-link claims and reciprocal backlinks for every
  promoted section; `docs/implementation/05-taut-summon-architecture.md`
  gains a short "setup-gate detection and recovery attach" subsection
  (why: gates are indistinguishable from crashes without an input-prompt
  fact; boundary: offer-not-bridge, once per run; tradeoff: paste-less
  providers keep legacy behavior); `docs/lessons.md` entry recording the
  Kimi 0.37.2 default-flip lesson ("wired once is not wired forever;
  provider updates can re-gate a member — detect gates behaviorally, not
  by screen text"); plan index row flipped per lifecycle; deviation log
  closed.
- Files: both specs (link claims), 
  `docs/implementation/05-taut-summon-architecture.md`, `docs/lessons.md`,
  `docs/plans/README.md`, this plan.
- Verify: full final gate block below, including
  `bin/check-plan-status-index`, `uv run --extra dev pytest
  tests/test_docs_references.py -q`, `bin/check-doc-paths`.

## Testing Plan

### Gate-harness fixture (the red-capable core)

Add `extensions/taut_summon/tests/fixtures/gate_harness.py`: a small
stdin/tty Python program that (1) draws a full-screen menu ("Trust this
folder?" analogue) without enabling bracketed paste, (2) exits 0 on Enter
while the menu is up (modeling Kimi's default), (3) on a distinct setup
keystroke (e.g. `t`) switches to a chat-prompt screen that enables
bracketed paste (`CSI ?2004h`) and echoes injected turns, and (4) never
requires the network. Generate all driver-level proofs through this real
child on a real PTY — Golden Rule 6: fixtures through production code
paths, not synthesis. A paste-confirmed variant flag makes case (d)
red-capable.

### What must stay real (anti-mocking boundary)

- Real PTY spawn, real `PtyHandle`, real reader/pump threads, real settle
  timing (shrink via the existing `PtySpec` timing knobs, not by mocking
  `wait_until_quiet`).
- Driver-level lease-bearing proofs use the existing custom-fd structural
  interaction `_PtyHostInteraction` (and its gated variants) from
  `test_interaction.py` — `ShellSummonInteraction.terminal_lease()`
  hardcodes fds 0/1 and cannot be pointed at test-owned fds.
  `ShellSummonInteraction` proofs are scoped to what it actually owns:
  availability rules, acknowledgement presentation, and the Enter /
  decline / cancel-event readline paths over test-owned streams; its
  fixed-fd lease keeps its existing coverage.
- Real SQLite ledger and driver bootstrap (existing test_driver harness
  patterns).
- Permitted narrow fakes: the provider child (the gate-harness fixture is
  the sanctioned external-provider seam), clocks only via the existing
  timing knobs, and a recording interaction stub *only* for the
  TUI-non-support proof (asserting no mid-run acknowledgement request is
  delivered to a `supports_setup_recovery() == False` host).
- Forbidden: mocking `_TerminalInputModeTracker`, `input_prompt_observed`,
  `wait_until_quiet`, the crash ladder, or `confirm_terminal_attach` in
  any proceed/decline driver proof.

### Contract tests by invariant

| Invariant | Firing proof |
|-----------|--------------|
| 1, 4 | Task 4 cases (a)(c)(g) |
| 2 | Task 4 (b) plus inspection gate on the diff (no reader handoff) |
| 3 | Recording interaction asserts one `terminal_availability` call per run across escalation |
| 5 | Task 4 (d) with timing assertions reused from existing conformance tests |
| 6 | Task 4 (c)(e)(f) |
| 7 | Existing first-attach matrix stays green untouched |
| 10, 11 | Task 1 (d), Task 5 raising-tail case |
| 12 | Task 3 conformance test + wheel-pair matrix |
| 13 | Existing STATUS key-collision test extended if any new key ships |

### Live harness spot-check (manual, not CI)

`extensions/taut_summon/tests/test_live_harness.py` gains no mandatory
case; manual observation instead (below), because real provider gates
(Kimi trust) depend on mutable machine state (`~/.kimi-code/`) that CI
must not depend on. This is the named rule 5 substitute for the
end-to-end Kimi proof: post-change demonstration is the manual observation;
the pre-change failure is the recorded 2026-08-18 incident.

## Verification and Gates

Per-task gates are named in the tasks. Final local verification (matches
the predecessor block plus this plan's files):

```bash
uv run --project extensions/taut_summon --extra dev --locked pytest -q \
  extensions/taut_summon/tests/test_pty_adapter.py \
  extensions/taut_summon/tests/test_scripted_adapter.py \
  extensions/taut_summon/tests/test_claude_adapter.py \
  extensions/taut_summon/tests/test_interaction.py \
  extensions/taut_summon/tests/test_driver.py \
  extensions/taut_summon/tests/test_controller.py \
  extensions/taut_summon/tests/test_summon_cli.py
uv run --project extensions/taut_summon --extra dev --locked pytest -q \
  extensions/taut_summon/tests
uv run --project extensions/taut_tui --extra dev --locked pytest -q \
  extensions/taut_tui/tests/test_tui_summon.py
uv run --project extensions/taut_tui --extra dev --locked pytest -q \
  extensions/taut_tui/tests
uv run --extra dev ruff check \
  extensions/taut_summon/taut_summon extensions/taut_summon/tests \
  extensions/taut_tui/taut_tui extensions/taut_tui/tests
uv run --extra dev ruff format --check \
  extensions/taut_summon/taut_summon extensions/taut_summon/tests \
  extensions/taut_tui/taut_tui extensions/taut_tui/tests
uv run --extra dev mypy \
  extensions/taut_summon/taut_summon extensions/taut_summon/tests
uv run --project extensions/taut_tui --extra dev --locked mypy \
  extensions/taut_tui/taut_tui extensions/taut_tui/tests
uv run --extra dev pytest tests/test_core_summon_wheel_matrix.py -q
bin/check-plan-status-index
uv run --extra dev pytest tests/test_docs_references.py -q
bin/check-doc-paths
git diff --check
```

Success: every command exits zero, no relevant acceptance test is skipped,
and the final diff contains no optional-method fallback and no reader
handoff outside the existing attach bridge.

Manual post-change observation:

1. Remove (or rename) the Kimi trust entry for a disposable workspace
   directory, then `taut summon kimi` from a real shell TTY. Confirm: no
   Enter reaches the trust dialog; the setup acknowledgement appears within
   the settle bound; proceed → trust dialog answered by hand → detach →
   `summoned ...`; a second summon runs straight through detached.
2. Repeat and decline: confirm one offer, detached continuation, ladder,
   and a give-up error showing the trust-menu tail and the `--attach`
   line.
3. `taut tui`, `:summon kimi` with the gate present: confirm no mid-chat
   modal, and the surfaced error carries the tail plus the `--attach`
   instruction.

Do not record provider credentials, continuity tokens, or raw terminal
captures containing sensitive provider state in the repository.

## Independent Review Loop

Per `docs/agent-context/runbooks/review-loops-and-agent-bootstrap.md`:
different-family review first (two evidenced attempts), then same-family
separate-role, then fresh-eyes with the limitation recorded.

- Preferred reviewer: Codex —
  `codex exec -s read-only -C "$(git rev-parse --show-toplevel)"
  "$PROMPT" --json -c 'model_reasoning_effort="high"'`, wrapped in
  `timeout` (~540 s). Second attempt / alternate family: Grok per
  `skills/call-agent/SKILL.md` (gate on `stopReason`). Kimi, Qwen, and
  Gemini are not review-eligible per the runbook and
  `docs/implementation/03-agent-inventory.md`.
- Reviewer inputs: this plan (including the full `## Proposed Spec Delta`
  and promotion strategy), `docs/specs/04-summon.md` at the spec baseline,
  `docs/specs/10-taut-tui.md` [TUI-11]/[TUI-13], the predecessor plan's
  invariants section, and the four code files named in Context.
- Review stance: the runbook §4 plan-review prompt, plus these targeted
  questions: does the delta preserve every [SUM-7.4] sentence it does not
  name (especially the single-reader and slow-start text)? Is the
  decline-continues semantics unambiguous against the first-attach
  cancel-ends-run semantics? Could you implement Task 4 confidently
  without inventing a second attach decision path? Existence-check every
  named symbol, path, and command first.
- Disposition: every finding is accepted (plan updated), rejected (with
  reasoning recorded in the Review Log), or explicitly out of scope. A
  "could not implement confidently" verdict blocks implementation.
- Timing: review completes before Task 0 (spec promotion) begins —
  class 4/5 review-before-implementation applies.

## Review Log

### Round 1 — Codex (different family), 2026-08-18

Command: `timeout 560 codex exec -s read-only -C <repo root> "<runbook §4
prompt + targeted questions>" -c 'model_reasoning_effort="high"'`
(codex-cli 0.144.3). Outcome: completed; existence audit passed for every
named path, flag, symbol, test seam, and quoted spec anchor. Verdict:
**blocker: F1, F2** ("could not implement confidently" until resolved).

| ID | Severity | Finding | Disposition |
|----|----------|---------|-------------|
| F1 | blocker | Delta tears the suspect generation down before acknowledgement; Task 4 said teardown-on-proceed and inject-on-decline into a generation that no longer exists. | Accepted. Task 4 rewritten as three explicit transitions carried through `_supervise` as one typed result: condition-failed injects the current generation; an offer tears down first and is consumed regardless of outcome; decline starts a fresh detached generation that takes the condition-failed transition. Delta strengthened with "teardown always precedes the acknowledgement request." |
| F2 | blocker | `confirm_terminal_attach` returns bare `bool`; shutdown-cancel and human decline were conflated, and they must diverge for setup recovery (decline continues, shutdown ends). | Accepted. Delta ([SUM-7.4] block and [SUM-13] paragraph) now distinguishes explicit human decline (continues detached) from shutdown-produced refusal (ordinary shutdown outcome, nothing spawned or injected); Task 4 gains transition 3 and red case (h). |
| F3 | major | Structured handles share `StreamJsonHandle` in `_stream.py`; Task 2 named `_scripted.py`/`_claude.py` as the implementation seam and omitted structural test doubles. | Accepted. Task 2 re-seamed on `_stream.py` with conformance assertions on both concrete handles; Task 3 now enumerates `_PtyHostInteraction`, `_GatedPtyHostInteraction`, `_GatedAttachDecisionInteraction` and adds a grep sweep for `confirm_terminal_attach`-bearing doubles. |
| F4 | medium | Promotion table said five [SUM-7.4] edits; the delta contains six. | Accepted. Count corrected (four replacements, one insertion, one append). |
| F5 | medium | `ShellSummonInteraction.terminal_lease()` hardcodes fds 0/1; the anti-mocking plan wanted it over test-owned fds. | Accepted. Driver lease proofs use the existing custom-fd `_PtyHostInteraction` family; `ShellSummonInteraction` proofs scoped to availability, acknowledgement presentation, and readline paths. |

Codex also confirmed: the delta preserves the unnamed [SUM-7.4]
single-reader and slow-start sentences, and the abbreviated startup order
matches the code's relative attach/pump order. Round-2 re-review of the
revised sections is required before Task 0 (spec promotion) begins, per
the class 4/5 review-before-implementation gate.

### Round 2 — Codex (different family), 2026-08-18

Same invocation form as round 1. Outcome: **F1–F5 confirmed resolved**;
two new blockers raised against the revised text.

| ID | Severity | Finding | Disposition |
|----|----------|---------|-------------|
| F6 | blocker | The surviving [SUM-7.4] sentence "Cancellation is a normal pre-spawn end..." contradicts setup-recovery decline (a child existed; decline continues the run). | Accepted. Added a seventh [SUM-7.4] edit scoping that paragraph to the first-generation decision and pointing decline at the escalation block; promotion table count corrected to seven. |
| F7 | blocker | Plan used `taut summon <name> --attach`; the repo's documented and implemented form is `taut summon --attach <name>` ([SUM-7.4] responder text, `_warn_unwired_without_attach`, live-harness tests). | Accepted. Every new occurrence normalized to `taut summon --attach <name>`, including the [SUM-11] give-up text and Task 5 message. |

### Round 3 — author verification after bounded reviewer stall, 2026-08-18

Two evidenced Codex attempts at the targeted F6/F7 confirmation stalled
(`timeout 400` then `timeout 560`, both SIGTERM exit 143; round-2 output had
already shown codex-cli cache-TTL errors). Per the review-loops runbook,
after bounded attempts the fallback is recorded with its limitation:
round 3's scope was three mechanical checks, verified deterministically by
the author instead —

1. The F6 anchor sentence exists verbatim in `docs/specs/04-summon.md`
   (whitespace-normalized match, scripted check).
2. `grep` finds no remaining wrong-order `taut summon <name> --attach`
   form anywhere in the plan.
3. The promotion table's "seven edits" matches the seven
   `### docs/specs/04-summon.md [SUM-7.4]` delta sections.

Limitation: the round-3 confirmation is author-verified, not
independent; the substantive independent verdicts remain Codex round 1
(existence audit, F1–F5) and round 2 (F1–F5 resolved). The F6 replacement
text itself has not had independent eyes; the round-1/round-2 reviewer
should re-check it if a further round runs before the spec-promotion
slice, and the promotion-slice reviewer inherits it either way.

Review-loop status: all seven findings dispositioned (all accepted and
applied). No open blockers from completed independent rounds; one
author-verified confirmation carries the disclosed limitation above.

### Completed-work review — 2026-08-19

Two-pass review after implementation, user-directed reviewer fallback
order Codex → Grok → Kimi.

**Attempts (evidenced):** Codex single-pass `timeout 560` stalled (exit
143); split into two passes. Pass 2 (tests/scope/docs, Codex,
`timeout 540`, medium effort) completed. Pass 1 (code-vs-spec, Codex)
stalled twice (`timeout 560` high, `timeout 540` medium, both exit 143).
Grok attempt failed hard (`402 Payment Required` — Grok Build balance
exhausted). Kimi 0.37.2 headless (`kimi -p`, output-format text) stalled
at `timeout 540`, probe confirmed headless works, relaunch at
`timeout 1140` completed. Kimi ran without a containment sandbox (none
exists for `-p`); it was instructed read-only and `git status` after the
run showed no new modifications beyond the author's own edits.

**Pass 2 (Codex, tests/scope/docs): blocker F1–F4, all accepted and
fixed:**

| ID | Finding | Disposition |
|----|---------|-------------|
| F1 | Proceed test proved orientation injection but not watcher readiness, despite the promoted [SUM-13] sentence | Accepted. Proceed test now posts chat as a second member (`TautClient` "Witness") and asserts the watcher delivers it to the gate child. |
| F2 | `--detach`, kill-switch, non-`AVAILABLE`, and non-supporting-host fall-throughs were proven only via the synthetic condition matrix | Accepted. New parametrized real-driver test `test_setup_gate_fall_through_variants_inject_after_settle` proves all four variants end-to-end: zero offers, zero leases, injection reaches the menu, enriched give-up raised. |
| F3 | Availability-sampled-once (invariant 3) had no firing assertion | Accepted. Proceed test asserts `availability_calls == [PREFERRED]` across the whole escalation run. |
| F4 | [TUI-13.2] implied a TUI-harness mid-run-request proof that does not exist | Accepted as qualification: [TUI-13.2] row rewritten to name the real composition (TUI unit proof of `False` + Summon-level non-supporting-host run); deviation row added. |

Pass 2 also confirmed by inspection: gate fixture models a real gate,
forbidden seams unmocked, `modes:True` flip justified, deviation rows
accurate, no drive-by changes, `git diff --check` clean.

**Pass 1 (Kimi, code-vs-spec conformance): no blocker.** All ten
normative items verified with matching code behavior. Findings:

| ID | Finding | Disposition |
|----|---------|-------------|
| F1 (low) | `orientation_via_inject` condition enforced only at the call site, not inside `_should_offer_setup_recovery` | Accepted. Guard co-located in the eligibility check; `_AttachCapableAdapter` test double gained the attribute. |
| F2 (low) | Wired members can receive the offer; spec did not say whether that is intended | Guard rejected — wired eligibility is the point of the feature (the motivating incident was a wired member re-gated by a provider update). Clarification accepted: [SUM-7.4] escalation block now states wired members are deliberately eligible. |
| F3 (info) | Escalation flags stay set if teardown raises mid-offer | Reviewer's own disposition: no action needed (run ends; consumed-flag semantics remain correct). Accepted as-is. |

Limitation: pass 1 ran on Kimi, which `docs/implementation/03-agent-inventory.md`
lists as present-only (write-attempt probe pending) — it was directed to
this reviewer by the owner after Codex stalled three times on this scope
and Grok failed with an exhausted balance. Its transcript shows a full
read of the promoted sections and all six code files.

## Deviation Log

| Spec ref | Planned behavior | Actual behavior | Rationale | Spec proposal |
|----------|------------------|-----------------|-----------|---------------|
| [SUM-7.4] | Escalation conditions did not exclude a generation that itself completed an acknowledged attach | Added condition: a just-attached generation never escalates (`attached_this_generation`) | Without it, a paste-less provider re-prompts the human immediately after they deliberately detached from first-attach setup — discovered when the promoted conditions broke the predecessor's wired-resume proof | Promoted in the same slice: the escalation block now names the condition (edit applied 2026-08-18, this plan) |
| [SUM-13] | Task 5's test asserted the raw `DriverError` type | Public boundary proof asserts `SummonOperationError` (the controller wrap) carrying the enriched message | [SUM-13] already requires typed public errors; asserting the wrapped type tests the real contract | none needed — behavior already matches promoted [SUM-13] text |
| [TUI-13.2] | Promoted row implied a TUI-harness proof that a suspected-gate run sends the TUI no mid-run request | Proof is a composition: TUI unit test proves `supports_setup_recovery()` is `False`; the Summon-level fall-through matrix proves a non-supporting host receives no mid-run request across a real suspected-gate run | A full Textual-pilot gate run duplicates the Summon-level proof at much higher cost; completed-work review F4 asked for the proof or an honest qualification | Promoted in the same slice: [TUI-13.2] row rewritten to name the composition (edit applied 2026-08-19, this plan) |

## Execution Log

Comprehension-gate answers (recorded before driver edits, 2026-08-18):

1. Shutdown paths (`_shutdown` checks throughout `_supervise`) and the
   `attach_decision is None` cancel path from `_prepare_generation_start`;
   a cancelled first-attach acknowledgement takes the second — `_supervise`
   returns 0 with nothing spawned.
2. [SUM-7.4] permits exactly one master reader at a time; during detached
   operation the pump's event stream owns the master, so settle only
   observes the reader-published `last_output_ts`.
3. Sanitized text with LFs collapsed to spaces and exactly one trailing
   `\r` — a single Enter-terminated turn.
4. No — availability is resolved once per foreground run; setup recovery
   reuses the cached value and only adds acknowledgement plus lease.

Task 0 (spec promotion): applied all ten delta edits across
`docs/specs/04-summon.md` and `docs/specs/10-taut-tui.md` plus both
Related Plans entries; `bin/check-doc-paths` and
`tests/test_docs_references.py` green; anchors matched verbatim at their
wrapped line positions.

Task 1 (PTY facts): red — four new tests failed with `AttributeError`
(`input_prompt_observed`, `output_tail`); green after adding the latched
`paste_enable_seen` tracker fact, the 4096-byte raw tail ring, and the
1024-char control-stripped renderer to `_pty.py`.

Task 2 (protocol): red — scripted defaults test failed on the missing
members; green after `AdapterHandle` protocol members plus one vacuous
implementation on `StreamJsonHandle` (`_stream.py`, F3 seam); mypy clean.

Task 3 (interaction): red on both new declaration tests; green after
protocol method + shell `True` + TUI `False` + `_PtyHostInteraction`
family + `_RecordingInteraction` (settable) in the same change.

Tasks 4-5 (driver): red — full-run gate tests via the new
`tests/fixtures/gate_harness.py` timed out awaiting the offer; green after
`_should_offer_setup_recovery`, the three-transition
`_orient_running_generation` rework, the pending-recovery attach decision
input, decline-continues/shutdown-ends handling in
`_prepare_generation_start`, and the enriched give-up in
`_resume_after_harness_exit`. Full-run proofs: offer/proceed/bridge/detach
/orient, decline + ladder + give-up (tail with the trust menu and the
`taut summon --attach <name>` line), shutdown-during-offer clean end,
confirmed-prompt no-offer, plus a ten-case condition matrix in
`test_driver.py`. Two harness lessons: the bridge's TCSADRAIN restore
requires the test to drain the user PTY after the detach chord, and the
gate fixture's setup key must be a byte sanitized injection cannot emit
(Ctrl-T), or injected orientation text drives the menu. The shared
`_configure_fake_pty` fake now enables paste mode (a confirmed prompt) so
predecessor wired-resume proofs keep their flow under the promoted spec.
Mid-implementation deviation (just-attached generations never escalate)
recorded in the Deviation Log and promoted to [SUM-7.4] in the same slice.

Task 6 (traceability): implementation-doc subsection added
(`docs/implementation/05-taut-summon-architecture.md` attach-decision
paragraph updated plus new setup-gate rationale block), lessons entry
added (`docs/lessons.md` 2026-08-18 wired-once entry), status index row
`draft` → `active`.

Final gates (2026-08-18, worktree state, all exit zero): full
`extensions/taut_summon/tests` (one environmental skip: local-LLM lane,
pre-existing); full `extensions/taut_tui/tests`; `ruff check` and
`ruff format --check` over both packages (three files reformatted by the
formatter before the check); both mypy invocations (41 + 34 files clean);
`tests/test_core_summon_wheel_matrix.py`; `bin/check-plan-status-index`;
`tests/test_docs_references.py`; `bin/check-doc-paths`;
`bin/check-cli-claims`; `git diff --check`. Manual post-change
observation (plan §Verification items 1-3, Kimi trust-entry removal) is
still owed by the owner on a real terminal; the recorded 2026-08-18
incident is the pre-change half of that proof.

Completed-work review fixes (2026-08-19, all gates rerun green): watcher
readiness and availability-count assertions added to the proceed test;
`test_setup_gate_fall_through_variants_inject_after_settle` (four real
fall-through variants); [TUI-13.2] qualified to the proof composition
(deviation row three); `orientation_via_inject` guard co-located in
`_should_offer_setup_recovery`; wired-eligibility clarification sentence
added to the [SUM-7.4] escalation block. Post-review gates: full summon
suite (one pre-existing environmental skip), `test_tui_summon.py`, wheel
matrix, both statics, plan index, doc references, doc paths,
`git diff --check` — all exit zero. Working tree after the uncontained
Kimi reviewer run contains only the plan's own 18 expected paths.

Owner closure (2026-08-19): the owner declared the reviewed plan complete
subject to fresh Ruff, mypy, and tests, then directed release of the current
tree as-is. Full Summon and TUI suites, repository Ruff lint/format, both
package mypy lanes, the 47-case wheel-pair matrix, doc references, doc paths,
CLI claims, plan index, and diff check all passed immediately before landing
at `f17612b`; the Summon suite retained only its expected unavailable local
Ollama smoke skip.

Release-gate correction (2026-08-19): the first 0.9.4 release attempt stopped
before branch or tag publication when the raw Ruff inventory detected the new
give-up diagnostic catch. Independent refactor review found that the one-call
`output_tail()` boundary is already the narrowest coherent owner: narrowing
the exception type would guess an unconstrained adapter contract, while moving
containment into handles would split primary-error ownership. A firing test now
makes `output_tail()` raise an arbitrary `RuntimeError` and proves the original
member/count/exit-code error and attach recovery instruction survive, no tail
block is appended, and the diagnostic is called exactly once. The approved
site is therefore registered under existing `[RUFF-SUP-067]` (8→9; global raw
`BLE001` 141→142) rather than hidden behind a refactor or broader boundary.

Hosted pre-tag correction (2026-08-19): exact-SHA root run `32275050123`
failed only the macOS/Python 3.14 forced-detach fall-through row after the
real gate logged `declined_default`. The child exited between a successful
orientation write and the PTY's post-write liveness check, so the fixture
observed an immediate orientation error instead of the asserted crash-ladder
give-up. The test now uses a byte-level fixture handshake: the real gate waits
after consuming the complete orientation line, and a transparent wrapper sends
the release byte only after the real `PtyHandle.inject()` returns. This keeps
the real PTY/process path and every exact give-up, tail, and attach assertion;
it removes the child-exit observation race rather than accepting two outcomes
or rerunning for luck. PG, MCP, and TUI producers were green; the release
helper stopped before every tag as required.

## Out of Scope

- Any TUI mid-chat terminal lease, acknowledgement, or [TUI-11.3] timing
  change beyond the one-sentence non-support declaration. A TUI-native
  setup-recovery lease is a successor plan against [TUI-11]; it inherits
  invariant 1 and the once-per-run rule from the promoted [SUM-7.4] text.
- Detach-chord changes or configurability (`Ctrl-\ Ctrl-\` stands;
  separately discussed 2026-08-18, deliberately not bundled here).
- Provider-specific screen scraping, dialog-text matching, or per-provider
  flags; auto-detach heuristics during attach.
- Changes to orientation/persona content, watcher semantics, `wired`
  schema, session persistence, rate limits, identity bootstrap, or the
  crash-ladder lengths/backoff values.
- Daemonization, driver ownership transfer, or any detached service
  (program theory A4, [TUI-14]).
- Release machinery; releasing the coordinated pair is ordinary [TAUT-12.5]
  work after completion.

## Fresh-Eyes and Hardening Checklist

Hardening checklist positions (runbook order): invariants before tasks
(§Invariants); hidden couplings named (settle/tracker/pump coupling in
Context, availability cache in invariant 3, wheel-pair coupling in
invariant 12); wrapper-vs-core separation (escalation reuses the existing
attach core; only the decision input is new); stop gates per task;
out-of-scope explicit; anti-mocking named; contract-focused tests
(invariant table); fatal-vs-best-effort explicit (invariant 10); post-deploy
observability (Rollout section); current-file descriptions (Context);
rollout sequencing and rollback written before tasks; no one-way doors;
comprehension questions with expected answers and an execution-log gate.

Fresh-eyes pass (author): file paths existence-checked against the tree at
the spec baseline; every quoted anchor sentence grepped verbatim in the
specs; commands copied from the predecessor's verified block with only
file-list changes; remaining known risks — (a) a provider that enables
bracketed paste *on its gate screen* would defeat detection and fall back
to today's behavior (accepted; no worse than status quo), (b) a paste-less
provider on an available shell TTY gains one decline-able prompt per run
(accepted; recorded in the implementation doc), (c) the latched
input-prompt fact deliberately ignores `?2004l` so alt-screen toggles
cannot flap the classification.
