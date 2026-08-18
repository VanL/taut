# Summon First-Attach Handoff Plan

Date: 2026-08-17

Status: completed; implementation, verification, final review, and
owner-authorized closeout passed

Owner: Taut maintainers

Class: 5 (hardened) — the work revises the public Summon host-interaction and
first-attach contracts in [SUM-7.4]/[SUM-13], crosses the shell and TUI host
contexts, and changes asynchronous foreground/terminal handoff behavior; the
[DOM-5] public-contract, multiple-execution-context, and background-work risky
triggers require the hardening checklist

Plan type: implementation with spec revision

Promotion strategy: **A — in-file text before implementation-link claims**.
Promote the reviewed [SUM-7.4]/[SUM-13]/[TUI-11]/[TUI-13] requirement text
before code. Add implementation mappings and reciprocal code/doc links with
the implementation slices, not with the text-only promotion.

## Goal

Repair the first interactive `taut summon grok` handoff in two implementation
stages. First, make the shell CLI explain and obtain acknowledgement before it
spawns the provider, preserve terminal state observed during attach, and return
promptly to a truthful foreground-readiness display after detach. Second,
adapt and prove the existing TUI interaction so both its native form and
`:summon grok` route present the same required facts while Textual is active,
suspend only for the raw provider lease, restore and redraw afterward, and
continue owning the foreground Summon run.

The two stages are review boundaries, not independently releasable package
states. Do not land or publish the CLI stage while the installed TUI is
incompatible with the promoted public interaction contract.

## Requested Outcomes

- [x] On an attach-capable run that will actually attach, the shell explains
  before provider spawn that the provider screen is setup rather than Taut
  chat, names `Ctrl-\ Ctrl-\`, says the foreground process remains running
  after detach, and requires explicit acknowledgement.
- [x] The provider is not spawned and no terminal lease begins before that
  acknowledgement; cancellation or input failure follows an explicit,
  test-covered outcome and leaves the durable row unwired.
- [x] The raw attach bridge remains byte-transparent and single-reader, but
  passively carries provider-output evidence and terminal input modes across
  the attach-to-pump ownership transfer without issuing duplicate terminal
  replies.
- [x] A provider that rendered its prompt only during attach does not spend the
  ten-second no-output fallback after detach, and its first multiline
  orientation retains bracketed-paste framing when the attached output enabled
  that mode.
- [x] After detach the shell reports that setup ended and listener startup is
  in progress; the existing `summoned ...` line remains the readiness marker,
  and the user has already been told to keep this command running and use
  another terminal for chat.
- [x] The TUI presents the acknowledgement through a native modal while
  Textual is active for both the native Summon form and the textual
  `:summon grok` route, suspends only for the byte-transparent PTY lease, then
  restores/redraws and keeps the run in its existing owned-run registry.
- [x] TUI cancellation, shutdown, concurrent-prompt, lease-acquisition, and
  restoration failures are bounded and preserve the existing foreground-run,
  logging, terminal, and exact-run cleanup priorities.
- [x] Shell-focused red/green proof lands before TUI adaptation; full
  cross-package verification and independent completed-work review gate any
  integration-ready claim.

## Source Documents

Source specs:

- `docs/specs/04-summon.md` [SUM-2], [SUM-5.1], [SUM-7.1], [SUM-7.4],
  [SUM-8], [SUM-11], [SUM-13], [SUM-13.1]
- `docs/specs/10-taut-tui.md` [TUI-2.1], [TUI-4.1], [TUI-7.1], [TUI-11.1],
  [TUI-11.2], [TUI-11.3], [TUI-11.4], [TUI-12.1], [TUI-12.3], [TUI-13.1],
  [TUI-13.2]
- `docs/specs/01-development-documentation-operating-model.md` [DOM-5],
  [DOM-6], [DOM-8], [DOM-10], [DOM-11], [DOM-15]

Canonical context and required runbooks consulted:

- `AGENTS.md`
- `docs/program-theory.md`
- `docs/agent-context/decision-hierarchy.md`
- `docs/agent-context/principles.md`
- `docs/agent-context/engineering-principles.md`
- `docs/agent-context/runbooks/testing-patterns.md`
- `docs/agent-context/runbooks/adversarial-acceptance-probes.md`
- `docs/agent-context/runbooks/writing-plans.md`
- `docs/agent-context/runbooks/hardening-plans.md`
- `docs/agent-context/runbooks/writing-specs.md`
- `docs/agent-context/runbooks/maintaining-traceability.md`
- `docs/agent-context/runbooks/review-loops-and-agent-bootstrap.md`
- `docs/agent-context/lessons.md`
- `docs/lessons.md`, Golden Rules and post-watermark entries
- `docs/implementation/03-agent-inventory.md`
- `skills/call-agent/SKILL.md`

Current implementation records and nearby plans:

- `docs/implementation/05-taut-summon-architecture.md`
- `docs/implementation/12-taut-tui.md`
- `extensions/taut_summon/README.md`
- `extensions/taut_tui/README.md`
- `docs/plans/2026-07-07-taut-summon-pty-harness-adapter-plan.md`
- `docs/plans/2026-08-01-summon-rich-host-global-state-plan.md`
- `docs/plans/2026-08-12-taut-tui-implementation-plan.md`
- `docs/plans/2026-08-17-tui-command-mirror-plan.md`
- `docs/plans/2026-08-17-tui-command-entry-correction-plan.md`

## Spec Baseline

- `5ed929273e9e65992104b3142c2515adee43cffb` — committed
  `docs/specs/04-summon.md` at plan authoring time; that file has no local
  diff.
- `0219d4a3dd947d78af369d0b03b3c581215b5e28` — the concurrent
  `docs/plans/2026-08-17-tui-command-entry-correction-plan.md` landed while
  this plan was active. Its command-entry matrix is now the committed
  `docs/specs/10-taut-tui.md` baseline for the TUI slice.

Before spec promotion, re-read both spec files from the then-current tree. If
the concurrent TUI plan has landed, replace the worktree identifier above with
its containing commit in the execution log. If [TUI-11] or the Summon attach
paragraph changed materially, stop and revise/re-review this delta rather than
applying it by context guess.

Promotion baseline identifier: Summon base
`5ed929273e9e65992104b3142c2515adee43cffb`; promoted
`docs/specs/04-summon.md` unstaged diff SHA-256
`050cfabcbabffc70a435556e081a78a89c14c66d556e2bd3d34aa885eeed9020`;
TUI base `0219d4a3dd947d78af369d0b03b3c581215b5e28`; promoted
`docs/specs/10-taut-tui.md` unstaged diff SHA-256
`8cc701e78236412e0fe3aedd0efc1de816698d9de96a885984e2f3aef0dc7dde`.
The latter is only this plan's additive [TUI-11]/[TUI-13.2] promotion over the
landed command-entry work. The shared workspace currently has no staged files.

## Current Structure and Key Files

### Summon-owned core path

- `extensions/taut_summon/taut_summon/interaction.py` owns the public
  `SummonInteraction` protocol, `TerminalAvailability`, and `TerminalLease`.
  At plan authoring it had only availability and lease phases;
  `ShellSummonInteraction` could not present a pre-spawn acknowledgement
  through that contract.
- `extensions/taut_summon/taut_summon/_driver.py::SummonDriver._supervise`
  resolves the adapter and terminal availability once. `_start_live_generation`
  currently spawns before `_prepare_generation_attach` reads `wired` and
  decides whether to lease/attach. The first stage must compute the same
  first-generation attach decision once before spawn, obtain host
  acknowledgement, and pass that decision forward without inventing a second
  policy path or rereading mutable state inconsistently.
- `extensions/taut_summon/taut_summon/_pty.py::PtyHandle.attach` is the sole
  reader during attach and forwards provider bytes unchanged. `_event_stream`
  becomes the sole reader afterward and is the only current owner that updates
  `_seen_output`, `_last_output_ts`, the terminal responder, and
  `_bracketed_paste`. That ownership handoff loses state observed during attach.
- `extensions/taut_summon/taut_summon/commands/summon.py` owns root-command
  logging and construction of `ShellSummonInteraction`; `cli.py` shares the
  same parser/controller behavior for the standalone console. Do not create a
  second driver or provider path in either adapter.
- `extensions/taut_summon/taut_summon/_persona.py` owns the multiline
  orientation. Its text and semantics do not change; only the PTY framing and
  time at which the existing orientation is delivered are repaired.

### TUI-owned rich-host path

- `extensions/taut_tui/taut_tui/summon.py::TuiSummonInteraction` is the only
  TUI implementation of the public interaction protocol. `TerminalLeaseRequest`
  marshals from a foreground worker to the Textual loop, whose handler enters
  `App.suspend()` and remains there until worker release. `SummonLogBridge`
  buffers logs while raw terminal ownership is leased.
- `extensions/taut_tui/taut_tui/app.py` owns both Summon entry routes. The
  native action opens `SummonStartScreen`; `_dispatch_summon_command` executes
  textual `:summon ...` directly. Therefore instructions placed only in the
  native form do not satisfy the TUI contract. A worker-originated pre-attach
  request must reach one native confirmation owner before suspension.
- `extensions/taut_tui/taut_tui/screens.py::ConfirmationScreen` is the
  existing yes/cancel visual owner. Reuse it; do not add a second modal style.
- `TuiSummonOperations` records a run as pending before the foreground worker
  starts and replaces it only through the exact `SummonRunHandle` readiness
  callback. A cancelled pre-attach acknowledgement ends through the existing
  worker-return path; it must not fabricate readiness or an owned handle.
- `TautApp.on_unmount`, confirmed-exit supervision, and the interaction's
  lease lock are the cleanup owners. Any new pending acknowledgement must be
  released on host close and must not strand the non-daemon foreground worker.

### Required comprehension gate

Before editing code, record both answers in this plan's execution log. A wrong
answer blocks implementation until the cited owners are reread.

1. **Where may acknowledgement occur without starving provider terminal
   queries, and who decides that attach will actually occur?**
   Expected answer: the driver decides once from request, adapter capability,
   cached host availability, first-generation state, and durable `wired`
   state. The host acknowledgement occurs after that decision but before
   provider spawn; prompting after spawn can leave the provider blocked on an
   unanswered startup query.
2. **Why can the attach bridge observe provider bytes but not run the active
   responder?**
   Expected answer: during attach the real host terminal owns query replies.
   Summon may passively retain output-seen time and input-mode state, but
   generating or retaining active query replies would duplicate the real
   terminal or create false post-detach `awaiting_query` state. After detach,
   the pump becomes the sole active responder.
3. **How must the TUI collect acknowledgement without breaking suspension?**
   Expected answer: while Textual is active, the worker posts a native prompt
   request and waits on that request's result; the UI handler returns after
   opening the existing confirmation screen. Only a confirmed request proceeds
   to the separate lease request whose UI handler enters synchronous
   `App.suspend()` and remains there until raw attach releases it.

## Invariants and Constraints

- Summon owns the attach decision. Shell and TUI are presentation adapters;
  neither may infer `wired`, inspect the ledger, identify a provider screen, or
  auto-detach from rendered output.
- The first-generation attach decision is computed once and threaded through
  spawn/attach. Do not add a second `_should_attach` formula or allow the
  acknowledgement result and later lease decision to disagree.
- A provider child does not exist while a person is deciding whether to enter
  setup. This prevents startup-query timeouts and makes cancellation genuinely
  pre-spawn.
- A cancelled acknowledgement is a normal foreground end: no provider child,
  terminal lease, `wired=True`, readiness callback, or watcher may appear. The
  already-bootstrapped member/session remains unwired, matching today's
  interrupted-first-attach recovery model; do not add destructive member or
  session rollback.
- Failure to present or collect acknowledgement is fatal to that foreground
  run and uses normal driver cleanup. Presentation failure must never fall
  through into an unacknowledged raw attach.
- The PTY master has exactly one reader at a time. Attach remains
  byte-transparent. Passive observation may update bounded state but emits no
  bytes, consumes no host replies, and creates no outstanding-query diagnostic.
- Output-seen time and bracketed-paste mode cross the attach-to-pump boundary.
  Cursor/query-response state crosses only if it can be proven passive and
  reply-free; otherwise keep it pump-owned. Do not broaden the parser merely to
  capture screen contents.
- Detached cold start still waits for first provider output or the existing
  aggregate maximum. The fix narrows only the case where attach already
  observed provider output; it must not weaken the slow-start protection added
  by `c8e61f4b`.
- `wired=True` remains downstream of a complete detach chord and successful
  terminal restoration. A prompt acknowledgement, visible provider screen, or
  provider readiness text never marks the row wired.
- Orientation remains before watcher readiness and chat injection. The
  `summoned ...` log remains downstream of watcher initial drain and is still
  the only shell readiness marker.
- Shell dynamic text uses the existing terminal-escape policy. Raw provider
  bytes remain the explicit policy exemption. Do not interpolate unescaped
  member/provider names into terminal instructions.
- TUI acknowledgement occurs before `App.suspend()`. While suspended, Textual
  processes no prompt, log, or render work. Logging remains buffered until the
  lease has restored and redraw completed.
- Both native-form and textual-command TUI routes use the same
  `TuiSummonInteraction`; neither route duplicates the prompt or bypasses it.
- TUI ownership remains exact-run based. Cancellation produces no fake handle;
  readiness and worker-return races retain their existing token fences.
- Concurrent acknowledgement or lease attempts fail closed under one
  TUI-owned coordinator. They must not stack modals or allow two workers to
  believe they own fd 0/1.
- No new dependency, provider-specific Grok branch, screen parser, CLI flag,
  storage column, daemon, detached ownership transfer, or alternate TUI
  Summon implementation is introduced.

## Rollback, Rollout, and One-Way Doors

There is no storage migration or destructive one-way door. The existing
`wired` row and provider sessions remain readable by old code. Rollout is
source-atomic across `taut-summon` and `taut-tui`: the public interaction
contract, shell implementation, driver, TUI implementation, tests, specs, and
implementation notes ship together. The shell-first stage is a development
and review boundary only.

Rollback is one coordinated revert of the spec delta and both extension
implementations. Because no schema or request field changes, old and new
databases remain compatible. Do not retain a permanent runtime fallback for a
host lacking the acknowledgement method. A short-lived compatibility check is
allowed only inside an unlanded shell-first worktree slice and must be removed
before the TUI compatibility slice is declared complete or any artifact is
built.

Post-deploy success signals:

- first shell attach shows an acknowledged explanation before any provider
  alternate-screen bytes;
- detach-to-orientation no longer spends the no-output maximum when attach saw
  output, and multiline orientation remains framed;
- the final shell readiness line appears only after listener readiness and the
  foreground command stays live until dismiss/interrupt;
- native and textual TUI starts show one native confirmation, suspend only
  after confirmation, return to the same TUI state after detach, and show the
  existing exact-run readiness state;
- cancellation and TUI exit leave no provider child or stuck foreground worker.

Rollback signals are terminal corruption, duplicate query replies, lost TUI
focus/draft state, a second terminal owner, readiness before watcher drain, or
any provider spawn before acknowledgement. Stop rollout and revert rather than
adding provider-specific exceptions.

## Proposed Spec Delta

Promotion strategy: **A — in-file text before implementation-link claims**.

| Spec file | Strategy | Sections touched |
|-----------|----------|------------------|
| `docs/specs/04-summon.md` | A | [SUM-7.4], [SUM-13], verification list, Related Plans |
| `docs/specs/10-taut-tui.md` | A | [TUI-11.1], [TUI-11.3], [TUI-11.4], [TUI-13.2], Related Plans |

### `docs/specs/04-summon.md` [SUM-7.4] — insert before “Attach is first-generation only”

> **Pre-attach acknowledgement.** After resolving that the first provider
> generation will actually attach, but before spawning that generation, Summon
> asks the host interaction to present a typed terminal-attach notice and
> return an explicit proceed/cancel decision. The notice identifies the member
> and provider and supplies the Summon-owned detach hint. Every host must make
> four facts clear: this screen is provider setup rather than Taut chat; the
> user should complete only trust, login, model, or equivalent setup; the user
> returns with `Ctrl-\ Ctrl-\`; and the foreground Summon run continues after
> detach. The shell requires an Enter acknowledgement. A rich host may use a
> native confirmation that was opened by this exact attach decision.
>
> Cancellation is a normal pre-spawn end. It starts no provider child, terminal
> lease, event pump, control loop, watcher, or readiness callback and never
> marks the session wired. The already-bootstrapped member and durable unwired
> session remain available for a later summon, as they do after an interrupted
> first attach; Summon performs no destructive identity rollback. A host error
> while presenting or collecting the decision is fatal to this foreground run
> and follows normal ownership-checked cleanup. Forced detach, a wired
> automatic run, unsupported attach, and later crash generations never request
> acknowledgement.

### `docs/specs/04-summon.md` [SUM-7.4] — replace the attach/pump startup-order paragraph

Replace the paragraph beginning “Startup order per generation is fixed...”
with:

> Startup order per generation is fixed around PTY master ownership. When
> policy rules out attach before bootstrap (`--detach`, `NESTED_HOST`, or
> generic `UNAVAILABLE`), the driver starts the pump immediately after spawn,
> before `rejoin` and `ensure_threads`, so the terminal-query responder is live
> while bootstrap work runs:
> `spawn → pump.start → rejoin → ensure_threads → settle → inject orientation →
> watcher`. For a first-generation attach, the driver first computes one attach
> decision from request, adapter capability, cached host availability, and
> durable `wired` state, then obtains host acknowledgement before provider
> spawn. After acknowledgement, the human bridge owns the PTY master until
> detach:
> `acknowledge → spawn → rejoin → ensure_threads → attach → detach →
> set_wired(True) → pump.start → settle → inject orientation → watcher`.
> `--attach` follows that path when the terminal is available. `NO_TTY` and
> `AVAILABLE` preserve their reason-specific detached or acknowledged-attach
> outcomes. The same cached availability is reused after a provider crash; no
> later generation reacquires a host lease or requests acknowledgement.
> `rejoin` still anchors the member to the child before raw onboarding or
> detached operation, and the watcher starts only after orientation is
> injected. Early-pump refusal paths remain required because TUIs may emit DSR,
> XTVERSION, or kitty queries immediately after spawn and time out while the
> driver is doing SQLite or thread bootstrap work.

### `docs/specs/04-summon.md` [SUM-7.4] — replace both orientation-settle paragraphs

Replace the paragraphs beginning “Settling must not treat...” and “Before the
first injected chat turn...” at their respective current locations with the
two paragraphs below. Delete both originals; do not append or duplicate either
replacement:

> Settling must not treat genuine pre-output silence as readiness. In a
> detached cold start, when the PTY reader has started but no Summon owner has
> observed provider output, the driver waits for first output or the bounded
> settle deadline. During human attach, the byte-transparent bridge may
> passively retain that provider output was observed, its latest timestamp, and
> input-mode state such as bracketed paste. Passive observation emits no
> terminal replies and retains no attach-era unanswered-query diagnostic,
> because the real host terminal owns query responses until detach. The pump
> inherits that bounded state when it becomes the sole reader. Output consumed
> during attach therefore satisfies the first-output condition, while a
> provider that emitted nothing still receives the existing cold-start bound.
>
> Before the first injected chat turn, the current PTY reader publishes
> `last_output_ts`; settle waits until observed output has been quiet for
> `quiet_ms` (default 500ms) or spends one aggregate `max_settle_s` deadline
> (default 10s). Starting the pump after attach does not erase prior observed
> output or terminal input modes. Settle never reads the master and is not a
> readiness signal. Orientation remains an explicit driver step gated by
> `orientation_via_inject`; PTY sets it true, while structured adapters set it
> false and receive the persona at spawn.

### `docs/specs/04-summon.md` [SUM-13] — replace the host-interaction paragraph

Replace the paragraph beginning “A host interaction reports terminal
availability...” with:

> A host interaction reports terminal availability, presents one typed
> pre-spawn acknowledgement only when the driver has resolved an actual attach,
> and grants a later scoped lease containing input/output fds. The notice owns
> semantic fields, including member, provider, and detach hint; hosts own their
> presentation and must escape dynamic text outside the raw lease. A cancelled
> decision is a normal pre-spawn result. A presentation failure is fatal and
> never falls through to attach. Summon owns the attach decision, provider PTY
> bytes, bridge invocation, finite detach result, and lifecycle. Shell and rich
> TUI adapters present different host-appropriate wording while preserving the
> same transition; neither inspects Summon persistence or provider screens.
> A rich TUI host that wants a nonblocking managed driver must define process
> supervision, terminal-release handshake, log routing, exit policy, and
> rollback in its own spec; Taut's first such host is governed by
> `docs/specs/10-taut-tui.md` [TUI-11] rather than by guessed Summon behavior.

### `docs/specs/04-summon.md` verification list — extend command/embedding verification

Append to the command/embedding verification paragraph:

> The shell-first attach matrix additionally proves acknowledgement precedes
> provider spawn, cancel and prompt failure spawn no child or lease, attach
> output survives the reader handoff without duplicate terminal replies,
> bracketed-paste framing survives detach, and listener readiness follows the
> retained quiet interval rather than the no-output maximum.

### `docs/specs/10-taut-tui.md` [TUI-11.1] — append to native-flow paragraph

> Both the native start form and textual `:summon` binding pass the same
> `TuiSummonInteraction`. If the driver resolves an actual terminal attach,
> that interaction requests one native acknowledgement; neither entry route
> precomputes `wired`, bypasses the acknowledgement, or owns terminal bytes.

### `docs/specs/10-taut-tui.md` [TUI-11.3] — replace the terminal-handoff section

Replace the body of [TUI-11.3] with:

> The TUI supplies one cooperative `SummonInteraction`. It reports terminal
> availability without changing terminal state and returns `AVAILABLE` only
> when both standard streams are suitable, no acknowledgement or lease owner
> conflicts, and the framework can suspend safely.
>
> When Summon resolves that an attach will actually occur, the foreground
> worker posts a typed acknowledgement request to the active Textual loop
> before provider spawn. The UI handler opens the existing native confirmation
> screen and returns; it never blocks the event loop waiting for the person.
> The prompt explains provider-only setup, the Summon-supplied detach hint, and
> that Textual resumes and continues owning the run after detach. Confirmation
> resolves the worker request; cancellation ends that foreground run without a
> provider child or terminal lease. Host shutdown resolves any pending prompt
> as cancelled so a non-daemon worker cannot be stranded. One coordinator
> excludes concurrent acknowledgement and lease owners.
>
> Only after confirmation and provider bootstrap does the interaction marshal
> a separate lease handshake to the UI loop. One handler enters Textual's
> supported synchronous `App.suspend()` context and remains inside it while
> waiting on a thread-safe release event. The Textual event loop is
> intentionally paused for the lease; it does not process prompts, logging, or
> rendering while suspended. After suspension succeeds, the handler signals
> acquisition to the Summon worker, which receives only input fd 0 and output
> fd 1 and owns byte-transparent PTY attachment. Worker release lets the same
> UI handler exit `App.suspend()`, restore the terminal, force a complete
> redraw, restore logical focus/mode/draft state, and signal restoration
> complete. Prompt-post, lease-acquisition, or restoration failure is fatal to
> that foreground run and visible through the existing safe presentation path;
> none falls through to concurrent terminal ownership.

### `docs/specs/10-taut-tui.md` [TUI-11.4] — append to log-routing paragraph

> The pre-attach confirmation runs before the raw lease and may render normally.
> Once the lease begins, Summon logs remain buffered until terminal restoration
> and redraw complete. The post-detach setup-complete diagnostic and eventual
> readiness projection therefore appear only on the restored TUI.

### `docs/specs/10-taut-tui.md` [TUI-13.2] — extend the Summon matrix bullet

Replace the final “Summon absent/present...” bullet with:

> - Summon absent/present, native-form and textual-command start, status/dismiss,
>   external versus owned exit, pending startup, actual-name readiness after
>   auto-rename, one readiness over provider resume, post-readiness rename,
>   readiness/worker return races, run-scoped stop, failed stop/return,
>   pre-spawn attach acknowledgement confirm/cancel/host-close/concurrent
>   exclusion, acknowledgement-before-suspension, terminal
>   availability/lease/restore, buffered post-detach logging, logging
>   restoration, and host signal non-ownership; and

### Related Plans additions

Add this plan to `## Related Plans` in both touched specs, describing the
shell-first attach repair and the subsequent TUI compatibility slice.

## Dependency-Ordered Tasks

1. **Independent plan and exact-delta review.**
   - Reviewer: Claude Sonnet, a different review-eligible family, invoked
     read-only through `skills/call-agent/SKILL.md`.
   - Inputs: this plan including the complete proposed delta, both baseline
     specs, both implementation notes, `interaction.py`, `_driver.py`,
     `_pty.py`, TUI `summon.py`/`app.py`/`screens.py`, and the named tests.
   - Review stance: existence-check first; then attack public-contract shape,
     pre-spawn ordering, cancellation cleanup, passive parser design, TUI
     event-loop ownership, cross-package rollout, and unnecessary ceremony.
   - Stop on `BLOCKED`. Disposition every finding in the Review Log and run a
     scoped round two for accepted fixes.
   - Done when the delta and sequencing have a recorded PASS.

2. **Spec-promotion slice (strategy A).**
   - Files: `docs/specs/04-summon.md`, `docs/specs/10-taut-tui.md`, this plan,
     and `docs/plans/README.md` only.
   - Reconcile the concurrent TUI spec work first; apply the exact reviewed
     requirement text without new implementation-link claims.
   - Add Related Plans backlinks and record the promotion baseline identifier.
   - Verify docs references and plan index before code cites the new behavior.
   - Stop if promotion would overwrite the active command-entry delta, require
     reclassifying either active spec, or change the reviewed ownership model.

3. **Stage 1 red: capture the shell-first failures through the real PTY path.**
   - Files to test first:
     `extensions/taut_summon/tests/test_driver.py`,
     `extensions/taut_summon/tests/test_interaction.py`, and
     `extensions/taut_summon/tests/test_pty_adapter.py`.
   - Extend the existing first-run real-PTY driver harness. Provider startup
     must be held behind an observed acknowledgement; then emit alternate-screen
     and bracketed-paste enable bytes only during attach, accept the split
     detach chord, remain quiet afterward, and record the first injected
     orientation.
   - Observe RED for: provider spawning before acknowledgement; cancellation
     still spawning or leasing; attach output not setting retained observation
     state; multiline orientation flattened after attach; and the full
     no-output settle budget being required.
   - Use events and recorded provider input as causal evidence. Wall-clock
     timeouts are deadlock fail-safes, not the success condition.
   - Stop if the test mocks the driver, PTY, fd bridge, provider subprocess, or
     durable `wired` transition it claims to prove.

4. **Stage 1 green: implement the public acknowledgement and shell host.**
   - Files:
     `extensions/taut_summon/taut_summon/interaction.py`,
     `extensions/taut_summon/taut_summon/_driver.py`,
     `extensions/taut_summon/taut_summon/commands/summon.py` only if command
     context streams are needed, `extensions/taut_summon/taut_summon/cli.py`
     only for shared standalone construction, and public exports in
     `extensions/taut_summon/taut_summon/__init__.py`.
   - Add one frozen typed notice and one explicit acknowledgement method to the
     existing interaction contract. Dynamic text is data; host implementations
     own presentation. Do not add a CLI flag or provider-specific adapter.
   - Refactor the existing attach decision into one named value computed before
     first spawn and consumed later by attach. Prompt only for that resolved
     path. Cancellation returns through normal driver cleanup with no child.
   - `ShellSummonInteraction` renders the fixed explanation safely and consumes
     one explicit Enter acknowledgement. EOF/cancel and stream errors follow
     the reviewed outcomes.
   - Emit one fixed post-detach progress diagnostic after terminal restoration;
     do not move or weaken the existing watcher-drain readiness log.
   - Stop if implementation requires duplicate `wired` reads/formulas, member
     deletion on cancel, parsing provider UI, or a permanent optional-method
     fallback.
   - Done when the new shell/interaction/driver tests and the neighboring
     Summon suite pass. Record an independent review of this meaningful slice
     before TUI adaptation.

5. **Stage 1 green: preserve passive PTY state across attach.**
   - Files: `extensions/taut_summon/taut_summon/_pty.py` and
     `extensions/taut_summon/tests/test_pty_adapter.py` plus the real driver
     regression from task 3.
   - Extract the smallest passive observation seam shared by attach and the
     active event reader. It updates output evidence and bounded terminal input
     modes, but only the active reader emits replies or owns outstanding-query
     health.
   - Preserve attach observation when `_event_stream` starts. A never-output
     detached provider still spends the original aggregate deadline.
   - Prove split escape sequences, bracketed-paste enable/disable, no duplicate
     replies, no false `awaiting_query`, immediate shutdown wake, and exact
     multiline orientation before chat.
   - Stop if passive tracking becomes screen parsing, introduces another PTY
     reader, copies the full responder, or weakens fd retirement/serialization.

6. **Stage 2 red: exercise TUI confirmation from both routes before suspend.**
   - Files to test first:
     `extensions/taut_tui/tests/test_tui_summon.py`,
     `extensions/taut_tui/tests/test_tui_app.py`, and, only if the existing
     confirmation screen lacks the required projection seam,
     `extensions/taut_tui/tests/test_tui_screens.py`.
   - With Textual's real pilot, prove the native form route and textual
     `:summon grok` route each reach one native attach confirmation through the
     same interaction. Assert the app is not suspended while the modal is
     actionable.
   - Observe RED for cancellation starting a provider/lease, confirmation not
     reaching the worker, a second prompt stacking, and host close leaving the
     wait live.
   - Keep the real Textual message and screen stack. A narrow fake may stand in
     for the provider only beyond the public interaction call; do not mock the
     acknowledgement message routing or lease state machine under test.

7. **Stage 2 green: adapt the TUI interaction and preserve rich-host ownership.**
   - Files: `extensions/taut_tui/taut_tui/summon.py`,
     `extensions/taut_tui/taut_tui/app.py`, and
     `extensions/taut_tui/taut_tui/screens.py` only if the existing
     `ConfirmationScreen` cannot render the typed notice safely.
   - Add a pre-lease request object whose UI handler opens the existing
     confirmation screen and returns immediately. Its callback resolves the
     worker decision. Keep `TerminalLeaseRequest.hold` as the separate
     synchronous suspension owner.
   - Extend the existing interaction lock/coordinator across pending prompt and
     lease states. Host close resolves a pending decision as cancel before
     executor shutdown. Prompt/post failure is visible and fail-closed.
   - Preserve log buffering, redraw, focus/mode/draft restoration, exact-run
     readiness, owned-run shutdown, and external-run exclusion.
   - Stop if the TUI reads Summon state, duplicates the attach decision,
     spawns a CLI subprocess, prompts from the suspended handler, or creates a
     second Summon operation owner.

8. **Cross-host real-boundary integration and documentation reconciliation.**
   - Tests: extend the public-controller real-PTY rich-host test in
     `extensions/taut_summon/tests/test_interaction.py`; run the full Summon and
     TUI suites. The controller, provider child, PTY, SQLite ledger, `wired`
     transition, and lease ordering stay real. Host UI presentation may use
     the TUI pilot/fake-fd boundary already sanctioned by [TUI-13.1].
   - Docs:
     `docs/implementation/05-taut-summon-architecture.md`,
     `docs/implementation/12-taut-tui.md`,
     `extensions/taut_summon/README.md`,
     `extensions/taut_tui/README.md`, both spec implementation/plan link
     sections, this plan, and the plan index.
   - Explain why acknowledgement is pre-spawn, why attach observation is
     passive, and why TUI prompt and terminal lease are distinct UI-loop
     transitions. Update maintained first-use instructions for shell and TUI.
   - Evaluate whether the investigation yields a durable lesson only after the
     implementation proves the rule. Do not add a lesson that merely narrates
     this incident.

9. **Final verification, independent completed-work review, and closeout.**
   - Run every command below from the final tree. Inspect skips; a skipped live
     provider lane is not evidence for the deterministic fake-provider path.
   - Give the reviewer the promotion baseline, plan, complete diff, both specs,
     both implementation notes, and red/green transcripts. Disposition every
     finding and rerun affected gates.
   - Reconcile traceability, close the deviation log, update plan status to
     `completed`, and commit only if the user separately authorizes landing.
   - Stop before completion if the TUI-compatible stage, cross-host proof, or
     zero-warning documentation gates are incomplete.

## Testing Plan

### Red-capable shell loop

The first failing proof extends the shipped real-PTY first-run test rather than
adding a mock-only unit:

```bash
uv run --project extensions/taut_summon --extra dev --locked pytest -q \
  extensions/taut_summon/tests/test_interaction.py \
  extensions/taut_summon/tests/test_pty_adapter.py \
  extensions/taut_summon/tests/test_driver.py::test_pty_first_run_attaches_until_chord_and_sets_wired
```

The minimized test must fail before implementation because provider startup is
currently observable before any acknowledgement and attach-consumed output
does not set `_seen_output` or bracketed-paste state. It turns green only when
the same real subprocess/PTY path proves pre-spawn acknowledgement, passive
state handoff, detach, orientation, watcher readiness, and foreground
liveness.

### Red-capable TUI loop

```bash
uv run --project extensions/taut_tui --extra dev --locked pytest -q \
  extensions/taut_tui/tests/test_tui_summon.py \
  extensions/taut_tui/tests/test_tui_app.py
```

At least one real-pilot test must fail before the TUI adaptation because the
current interaction has no acknowledgement phase. It must drive both native
and textual Summon producers to the same modal/interaction boundary.

### Anti-mocking boundary

- Keep real: public `SummonController.run_foreground`, driver bootstrap,
  provider subprocess, PTY/fd bridge, SQLite ledger, `wired` transition,
  orientation input, watcher readiness, Textual prompt routing, suspension
  state machine, and exact-run worker return.
- Narrow fakes allowed: controlled clock/wake for pure settle arithmetic,
  external Grok model/network behavior, OS fd suitability in TUI unit tests,
  and provider behavior behind the existing fake PTY executable.
- Do not require a live paid Grok request for correctness. A manual Grok smoke
  is post-change observational evidence, not the regression owner.

## Verification and Gates

Per-stage focused gates are named in the tasks. Final local verification:

```bash
uv run --project extensions/taut_summon --extra dev --locked pytest -q \
  extensions/taut_summon/tests/test_interaction.py \
  extensions/taut_summon/tests/test_pty_adapter.py \
  extensions/taut_summon/tests/test_driver.py \
  extensions/taut_summon/tests/test_controller.py \
  extensions/taut_summon/tests/test_summon_cli.py
uv run --project extensions/taut_summon --extra dev --locked pytest -q \
  extensions/taut_summon/tests
uv run --project extensions/taut_tui --extra dev --locked pytest -q \
  extensions/taut_tui/tests/test_tui_summon.py \
  extensions/taut_tui/tests/test_tui_app.py \
  extensions/taut_tui/tests/test_tui_screens.py
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
uv run --extra dev bin/check-cli-claims
git diff --check
```

Success means every command exits zero, no relevant acceptance test is skipped,
the installed-pair wheel matrix still exposes both extensions compatibly, and
the final diff contains no temporary optional-method fallback.

Manual post-change observation, after deterministic gates:

1. In a disposable initialized workspace, run `taut summon grok` from a real
   shell TTY. Confirm the explanation precedes Grok output, detach is
   discoverable, listener startup is prompt, the readiness line is truthful,
   and Ctrl-C dismisses cleanly.
2. In `taut tui`, run both the native Summon action and `:summon grok` against
   disposable member names. Confirm the native prompt appears before Textual
   suspension, Grok owns the raw terminal only after confirmation, detach
   restores the same TUI, and the owned run remains live until explicit
   dismiss/TUI-exit confirmation.

Do not record paid-model output, credentials, continuity tokens, or raw terminal
captures containing sensitive provider state in the repository.

## Independent Review Loop

Plan/delta review occurs before spec promotion. A different-family Claude
review receives the baseline identifiers, complete proposed delta, current
code/test owners, concurrent TUI-plan warning, and hardening invariants. It
must answer PASS or BLOCKED against confident implementability and no material
degradation. Findings are claims; reproduce each before accepting it.

Run another independent review after the shell-first meaningful slice, scoped
to the new interaction contract, pre-spawn ordering, PTY state transfer, and
shell tests. Run a final independent review after TUI compatibility and all
verification. Intermediate review does not authorize landing a package pair
with an incompatible TUI.

## Review Log

| Date | Reviewer | Verdict/finding | Disposition |
|------|----------|-----------------|-------------|
| 2026-08-17 | Claude Sonnet, round 1 | **BLOCKED, F1.** The exact [SUM-13] replacement dropped the existing sentence that makes [TUI-11] authoritative for rich-host supervision, terminal release, logging, exit, and rollback. | Accepted. Restored that sentence verbatim in the proposed [SUM-13] replacement. Scoped round-two review required. |
| 2026-08-17 | Claude Sonnet, round 1 | **N1.** The startup-order replacement dropped the existing rationale that early terminal queries can time out during SQLite or thread bootstrap. | Accepted. Restored the rationale verbatim. |
| 2026-08-17 | Claude Sonnet, round 1 | **N2.** The settle edit names two non-adjacent paragraphs but did not expressly say to delete both originals, risking duplicated text during promotion. | Accepted. The edit instruction now identifies the two locations and forbids append/duplication. |
| 2026-08-17 | Claude Sonnet, round 1 | **N3.** Reusing the complete active terminal responder during attach would contaminate outstanding-query state; passive bracketed-paste/output tracking should be a narrow tracker. | Accepted as confirmation of task 5's existing invariant and stop condition; no scope change. |
| 2026-08-17 | Claude Sonnet, round 2 | **PASS.** Scoped re-review found F1, N1, and N2 resolved without contradiction or new material degradation. | Plan and proposed delta may proceed to the spec-promotion slice. |
| 2026-08-17 | Claude Sonnet, Stage 1 | **PASS.** The shell/PTY slice has one pre-spawn decision, bounded cancel/error cleanup, authoritative streams, a byte-transparent single-reader attach, passive split-mode tracking without query replies, and retained settle state, with real controller/PTY proof. | Stage 1 accepted; proceed to TUI compatibility. The first broader review command timed out silently, so the successful review was rerun read-only against a narrower file boundary without test execution. |
| 2026-08-17 | Einstein, final round 1 | **NOT PASS.** The TUI route test called private dispatch methods with fake operations; [TUI-13.2] overclaimed buffered post-detach-log coverage; the Summon architecture still called the now lazily core-dependent interaction module stdlib-only. | Accepted. Replaced the shortcut with real pilot routes over real TUI operations/public controller/driver and a fake executable only at the provider boundary; narrowed the unsupported firing-matrix claim; corrected both architecture references. |
| 2026-08-17 | Einstein, final round 2 | **PASS.** Both real routes reach the driver-owned native confirmation before suspension, cancel without provider spawn, and retire the exact run; the spec and architecture claims now match their firing evidence and dependency boundary. | Final review accepted with no remaining finding. |

## Deviation Log

| Spec ref | Planned behavior | Actual behavior | Rationale | Spec proposal |
|----------|------------------|-----------------|-----------|---------------|
| [TUI-13.2] | Enumerate buffered post-detach logging as a firing-test element. | Retained the existing generic lease-buffering and logger-restoration tests, but removed that new enumerable claim. | The new setup-ended diagnostic is emitted after the lease restores, so calling it buffered was false; no dedicated end-to-end firing test owns that exact combined phrase. | Incorporated in the promoted spec. |

## Execution Log

- 2026-08-17: Live read-only reproduction with Taut 0.9.1 and Grok 1.0.4
  confirmed the detach instruction is hidden by Grok's alternate screen; the
  attached screen does not distinguish provider setup from Taut chat; detach
  is followed by the no-output settle delay; and the foreground command remains
  occupied without explaining that another terminal is required.
- 2026-08-17: Source inspection confirmed attach consumes provider bytes
  without updating output-seen or bracketed-paste state, while existing tests
  cover attach, settle, and orientation separately but not the complete
  attach-to-ready transition.
- 2026-08-17: Independent round-one review reproduced the ownership and
  ordering claims but blocked on one omitted [SUM-13] governance sentence.
  The sentence and two fidelity clarifications were restored; scoped round two
  returned PASS.
- 2026-08-17: Comprehension gate passed. The driver resolves one attach
  decision from request, adapter support, cached availability,
  first-generation state, and durable `wired` before spawn. Attach may
  passively observe output and input modes but cannot run the active query
  responder while the real terminal owns replies. The TUI must resolve its
  native confirmation while Textual is active, then use a separate synchronous
  suspension for the terminal lease.
- 2026-08-17: Promoted the independently reviewed [SUM-7.4]/[SUM-13] and
  [TUI-11]/[TUI-13.2] text before implementation-link claims. Recorded the
  exact diff baseline above and preserved the concurrent TUI command-entry
  delta.
- 2026-08-17: Stage 1 RED proved the public notice/export was absent, the real
  provider spawned before confirmation, and attach-consumed output did not set
  retained state. GREEN added the typed host acknowledgement, cancellation and
  prompt-failure pre-spawn exits, authoritative shell streams, one threaded
  attach decision, post-detach progress, and passive output/bracketed-paste
  handoff. The focused interaction/PTY/driver/CLI suite, Ruff, format, mypy,
  and diff check passed; independent Stage 1 review returned PASS.
- 2026-08-17: The concurrent TUI command-entry correction landed as
  `0219d4a3dd947d78af369d0b03b3c581215b5e28`. Rebased this plan's recorded
  TUI promotion baseline onto that commit without changing its command-entry
  behavior.
- 2026-08-17: Stage 2 RED proved the TUI had no confirmation-request owner.
  GREEN routes both native and textual starts through one native confirmation
  while Textual remains active, reserves the terminal for the confirming
  worker, suspends only for its later lease, releases pre-lease failures, wakes
  pending confirmation on unmount, and rejects late resolved requests without
  opening a stale modal. The focused TUI interaction/app suite passed.
- 2026-08-17: Final review round one rejected the shortcut route test and two
  overclaims. The amended real pilot drives palette → native Summon form and
  typed `:summon grok` through real `TuiSummonOperations` and the public
  controller/driver, with only a PATH-injected fake provider executable. Both
  prompts precede suspension, cancellation retires the exact run, and the
  provider never starts. The unsupported buffered-post-detach firing claim was
  removed and the lazy core escape dependency documented. Round two returned
  PASS.
- 2026-08-17: Final deterministic gates passed: the complete Summon suite
  passed with only the expected absent-Kimi and absent-local-LLM skips; the
  complete TUI suite passed; focused cross-host tests, the installed wheel
  matrix, Ruff, format, mypy, plan index, docs references/paths, CLI claims,
  and `git diff --check` all passed. The worktree remains intentionally
  uncommitted pending owner authorization, so this plan remains active.
- 2026-08-17: The owner explicitly authorized closeout and commit. Promoted
  the plan and index to completed before the final closeout gates and atomic
  coordinated commit.
- 2026-08-17: The 0.9.2 pre-tag Windows lane exposed that the route proof's
  PATH-injected `grok` executable still selected the POSIX-only PTY adapter and
  failed on `fcntl` before acknowledgement. The test now keeps both exact
  `grok` route inputs while its Grok factory uses the existing cross-platform
  scripted-provider seam with attach capability supplied; provider spawn is a
  firing failure. Both real TUI routes, the public
  controller/driver, real SQLite, exact prompt/suspension assertions, and exact
  cancellation cleanup remain unchanged. The event-based foreground observer
  surfaced the transport error directly rather than collapsing it into a
  polling timeout.

## Out of Scope

- Changing the detach chord or making it configurable.
- Provider-specific Grok flags, screen scraping, prompt detection, or model API
  integration.
- Auto-detach based on trust/login/model UI text.
- Returning the shell while leaving Summon daemonized, transferring ownership,
  or adding a service lifecycle.
- Changing the default orientation/persona content, rate limits, watcher
  semantics, `wired` schema, identity bootstrap, collision rules, or session
  persistence.
- Making PTY output speech or adding PTY terminal mode.
- Redesigning the TUI Summon form, command grammar, action registry, general
  confirmation UI, or exit policy beyond the new acknowledgement lifecycle.
- Solving unrelated concurrent TUI command-entry work in this plan.
- Releasing packages or changing coordinated release machinery.

## Fresh-Eyes and Hardening Checklist

Before implementation and again before completion, verify:

- every named file, method, flag, route, and test exists in the current tree;
- acknowledgement is pre-spawn and attach-decision-owned, not a shell-only
  guess or post-spawn prompt;
- cancellation and host-close cleanup are explicit and bounded;
- passive PTY observation cannot write replies or fabricate query health;
- detached cold-start protection remains intact;
- TUI prompt and terminal suspension are two distinct state transitions;
- both native and textual TUI routes fire;
- the shell-first stage is not described as independently releasable;
- no new dependency, storage migration, second parser, or second terminal owner
  appears;
- red evidence, per-slice review, rollback, post-deploy signals, and final
  traceability gates are all recorded.

If any answer is no, stop and revise the plan rather than implementing around
the gap.
