# Summon Unified PTY and Cross-Platform Test Plan

Date: 2026-09-03

Status: Active; final-tip review corrections in progress

Class: 5. This changes the public Summon CLI and typed API, removes a shipped
adapter and persistence fields, replaces Windows process ownership, and changes
asynchronous child-process
cleanup. The full plan-hardening checklist applies.

Plan type: implementation with spec revision.

## Goal

Remove the Claude-specific structured adapter and make the interactive PTY
adapter the only production harness path. Add a Windows ConPTY implementation
behind that same adapter, port the real scripted test harness to interactive
terminal I/O, and run the complete non-live Summon suite on every supported
operating system. Tests may be platform-specific only when they prove a POSIX
or Windows adapter primitive.

The design deliberately does not add a configurable structured-event mapping
language or a provider-profile framework. The existing `PtySpec` launch shape
is enough for every current named provider. A new abstraction requires a
second concrete production need, not a prediction that harnesses may diverge.

## Source Documents

Source specs:

- `docs/specs/04-summon.md` [SUM-1], [SUM-2], [SUM-3], [SUM-6], [SUM-7.1],
  [SUM-7.2], [SUM-7.3], [SUM-7.4], [SUM-8], [SUM-11], [SUM-12], [SUM-13]
- `docs/specs/08-persistence-io.md` [PIO-5.3]
- `docs/specs/01-development-documentation-operating-model.md` [DOM-5],
  [DOM-10], [DOM-10.2], [DOM-11], [DOM-15]

Current implementation account:

- `docs/implementation/05-taut-summon-architecture.md`

Prior plans that define behavior this plan removes or preserves:

- `docs/plans/2026-07-06-taut-summon-plan.md`
- `docs/plans/2026-07-07-taut-summon-pty-harness-adapter-plan.md`
- `docs/plans/2026-07-28-summon-terminal-retirement-plan.md`
- `docs/plans/2026-08-14-summon-stream-close-race-plan.md`
- `docs/plans/2026-08-17-scripted-provider-ready-signal-plan.md`
- `docs/plans/2026-08-18-summon-setup-gate-recovery-attach-plan.md`
- `docs/plans/2026-08-24-extension-seams-process-containment-coverage-plan.md`
- `docs/plans/2026-08-25-semantic-compatibility-hardening-plan.md`

Required runbooks:

- `docs/agent-context/runbooks/writing-plans.md`
- `docs/agent-context/runbooks/hardening-plans.md`
- `docs/agent-context/runbooks/testing-patterns.md`
- `docs/agent-context/runbooks/adversarial-acceptance-probes.md`
- `docs/agent-context/runbooks/review-loops-and-agent-bootstrap.md`
- `docs/agent-context/runbooks/maintaining-traceability.md`

Pinned external source for the Windows implementation:

- Microsoft's ConPTY lifecycle contract. Input and output require independent
  service threads; closing the pseudoconsole terminates attached console
  clients and can emit final output that must be drained:
  <https://learn.microsoft.com/en-us/windows/console/creating-a-pseudoconsole-session>

No new runtime dependency is proposed. Fresh-eyes review rejected `pywinpty`
because its public v3.0.5 high-level close signals and polls the leader but does
not expose the `ClosePseudoConsole` capability required by Summon's descendant-
retirement contract. The Windows backend therefore uses the same narrow
standard-library `ctypes` boundary already used by current `_win32_job.py` and
`interaction.py`, but targets the documented ConPTY API directly. It must not
grow bindings beyond the functions exercised by a current Summon CLI/API path.

## Spec Baseline

- Repository baseline: `174236a5b5b632d88e74e4caa9b0ba35b9489753`.
- `docs/specs/04-summon.md` blob:
  `cde770b23eac7909293a8905b8c1a20c20f29b84`.
- `docs/specs/08-persistence-io.md` blob:
  `5dd7160708e12b4a973a85b7b2ed61247a1fcb50`.
- `docs/implementation/05-taut-summon-architecture.md` blob:
  `5772c922883a22c6c6e7bb68048870afc521ace3`.
- Promotion baseline: `32ec8594bb3122073d9d84f1aebbc726dd23fa2d`.
  This promoted the reviewed unified-PTY contract after the disposable ConPTY
  qualification passed and before production code depended on that contract.

## Context and Key Files

### Current ownership

- `extensions/taut_summon/taut_summon/_adapter.py` owns the adapter protocols,
  event union, lazy registry, PTY environment parsing, and named-provider
  factories. All named providers except `claude-stream` already resolve to the
  PTY adapter.
- `extensions/taut_summon/taut_summon/_pty.py` owns the interactive PTY path.
  Its module-level `fcntl`, `pty`, `termios`, and `tty` imports make it POSIX
  only. It also owns provider-neutral terminal state, output-tail sanitation,
  write serialization, attach, readiness observation, and lifecycle logic.
- `extensions/taut_summon/taut_summon/_process_domain.py` owns POSIX process
  groups and delegates Windows process creation to `_win32_job.py`.
  `_darwin_wait.py` remains the Darwin-specific non-reaping observation helper
  imported by the renamed `_process_domain_posix.py`; it is neither moved nor
  generalized by this plan.
- `extensions/taut_summon/taut_summon/_claude.py` translates Claude
  `stream-json`; `_stream.py` owns its pipe lifecycle; `_win32_pipe.py` adapts
  cancellable Windows pipe writes. This is the vendor-specific path to delete.
- `extensions/taut_summon/taut_summon/_scripted.py` is a second structured
  adapter over the same stream plumbing. `scripted_provider.py` is the real
  child used by driver and conformance tests.
- `extensions/taut_summon/taut_summon/_driver.py` consumes assistant, session,
  activity, and exit events; terminal mode and provider-session resume are
  structured-only branches.
- `extensions/taut_summon/taut_summon/_control.py`, `controller.py`,
  `models.py`, `cli.py`, and `commands/summon.py` expose provider session and
  terminal-mode state through the public CLI and typed API.
- `extensions/taut_summon/taut_summon/_state.py` stores
  `provider_session_id`. `persistence.py` exports and restores it.
- `.github/workflows/test.yml` runs the full ordinary Summon unit selection on
  Windows but allowlists only three process-test files there. The default PTY
  driver path is therefore not collected on Windows.

### Required reading and comprehension gate

Before editing, the implementer records answers in the execution log:

1. Why does the Windows backend own `ClosePseudoConsole` directly rather than
   wrapping `PtyProcess.close(force=True)`? Expected answer: the reviewed
   `pywinpty` v3.0.5 high-level method signals and polls the leader but does not
   expose deterministic pseudoconsole close. The repository contract is about
   the terminal domain, including attached descendants.
2. Which code may interpret terminal output as assistant speech after this
   change? Expected answer: none. Terminal output remains activity,
   terminal-query input, attach bytes, and bounded diagnostics only. Agent
   speech remains an explicit `taut say`/`taut reply` action.
3. What test may be skipped on Windows or POSIX? Expected answer: only a test
   whose subject is a named platform primitive in `_pty_posix.py`,
   `_process_domain_posix.py`, or `_pty_windows.py`. Driver, controller, CLI,
   persistence, conformance, and shared terminal-behavior tests do not acquire
   platform skips.
4. Why is the physical `provider_session_id` column retained? Expected answer:
   dropping a nullable column creates a destructive sidecar migration without
   improving the remaining PTY behavior. The public model and new dumps remove
   the field; the loader accepts and discards it only because a real old dump
   can contain it.

An incorrect answer blocks implementation until the cited owner text and
source are reread.

### Windows native API and ownership ledger

Slice 1 must qualify this complete set before promotion. Adding another native
call later is a plan deviation and stop condition.

| API | Current Summon use | Ownership and cleanup |
|---|---|---|
| `CreatePipe` | Create non-inherited parent input-write/output-read ends plus ConPTY input-read/output-write ends | Pass NULL security attributes and `bInheritHandles=False`; retain the two ConPTY-facing handles through child creation, then close them immediately after successful `CreateProcessW`; retain and close the two parent ends in the Windows handle owner; close every created handle on partial setup |
| `CreatePseudoConsole`, `ClosePseudoConsole` | Create and deterministically retire the terminal domain | One owned `HPCON`; exactly one lifecycle owner calls `ClosePseudoConsole` while the output reader remains active. No resize API is bound because Summon exposes no resize trigger. |
| `InitializeProcThreadAttributeList`, `UpdateProcThreadAttribute`, `DeleteProcThreadAttributeList` | Put the `HPCON` into `STARTUPINFOEX` | One caller-allocated attribute-list buffer; delete the initialized list on every post-init exit, then release the buffer |
| `CreateProcessW`, `ResumeThread`, `TerminateProcess` | Create the hosted CLI suspended, publish all ownership, then resume; terminate only an unresumable partial-spawn leader during failed setup | Use `STARTF_USESTDHANDLES` with null standard handles and `bInheritHandles=False` so a redirected parent cannot bypass ConPTY through duplicated standard handles; retain the process handle through final exit inspection; close the primary thread handle after successful resume; close both on setup failure; `TerminateProcess` is pre-publication cleanup only, never normal terminal-domain close |
| `ReadFile`, `WriteFile` | Drain ConPTY output, write serialized ConPTY input, read attach input, and write attach output | Each blocking call has one identifiable thread owner; input writes share the adapter serializer; a dedicated attach-output writer consumes chunks enqueued by the sole non-blocking ConPTY observer; no second ConPTY output reader exists |
| `GetConsoleMode`, `SetConsoleMode`, `GetConsoleCP`, `SetConsoleCP`, `GetConsoleOutputCP`, `SetConsoleOutputCP` | Snapshot, enter raw/VT input and VT/UTF-8 output, and restore a real console lease | Input and output modes and both code pages belong to the borrowed host console; restore every exact snapshot before releasing duplicated attach handles, including on cancellation and partial setup |
| `GetCurrentProcess`, `DuplicateHandle` plus `msvcrt.get_osfhandle` | Turn borrowed CRT lease fds into lifetime-bounded Win32 handles | The lease's original fd/handle stays borrowed and is never closed; attach owns and closes only duplicates |
| `OpenThread`, `CancelSynchronousIo` | Cancel a dedicated blocked attach-input reader, attach-output writer, ConPTY-output reader, or active ConPTY-input writer during detach, teardown, or reusable interrupt | Close each opened thread handle after cancellation/observation; cancellation races are normalized only for the exact retiring or interrupted owner; retirement invalidates the write epoch before cancellation, releases queued writers, and reusable interrupt creates a fresh epoch only after the old writer has observed cancellation |
| `WaitForSingleObject`, `GetExitCodeProcess`, `CloseHandle` | Bounded wait, exit event, and deterministic native cleanup | The handle that created or duplicated a native object closes it exactly once; wait timeout is fatal unless an earlier primary failure already owns the outcome |

The adapter-owned ConPTY output reader is created at spawn and remains the sole
reader through detached and attached phases. It always feeds terminal state,
activity, query detection, and the bounded diagnostic tail. It never calls a
possibly blocking host-sink `WriteFile`. Attach registers a generation-tagged
duplicated output handle and dedicated writer owner under a routing lock; the
reader only enqueues chunks for that generation. Detach unregisters the same
generation, cancels the exact writer if it is blocked, waits boundedly for it
to observe cancellation and discard queued chunks, then closes the duplicate.
Cancellation observation and writer join are preconditions for closing or
reusing that handle. If the bounded wait expires, return the existing fatal
attach/adapter failure, permanently retire routing for that handle, and
quarantine the duplicate until the writer exits, then close it. Normal adapter
or terminal teardown may not close it before writer exit; if the process exits
first, only operating-system process teardown releases it. No later attach
generation may reuse it.
Attach never opens a second ConPTY reader, and an old sink generation cannot
write to a reused handle. Query replies and attach input use the existing
serialized ConPTY input writer. No queue-overflow policy or guard is added
without a constructible host-backpressure result from the hosted probe.

### Files to add

- `extensions/taut_summon/taut_summon/_pty_posix.py`: POSIX-only PTY handle,
  fd attach, signal, and process-group implementation moved from `_pty.py`.
- `extensions/taut_summon/taut_summon/_pty_windows.py`: Windows-only native
  ConPTY handle using the documented kernel API through `ctypes`.
- `extensions/taut_summon/taut_summon/_win32_io.py`: the narrow shared owner
  for synchronous Win32 handle reads, cancellation, console-mode snapshot and
  restoration, and writes used by shell acknowledgement and PTY attach.
- `extensions/taut_summon/taut_summon/_process_domain_posix.py`: renamed,
  POSIX-only process-domain owner.
- `extensions/taut_summon/tests/test_pty_posix.py`: POSIX primitive tests.
- `extensions/taut_summon/tests/test_pty_windows.py`: Windows primitive and
  real ConPTY process-domain tests.

### Files to modify

- `extensions/taut_summon/taut_summon/_adapter.py`
- `extensions/taut_summon/taut_summon/_pty.py`
- `extensions/taut_summon/taut_summon/_driver.py`
- `extensions/taut_summon/taut_summon/_control.py`
- `extensions/taut_summon/taut_summon/interaction.py`
- `extensions/taut_summon/taut_summon/_state.py`
- `extensions/taut_summon/taut_summon/models.py`
- `extensions/taut_summon/taut_summon/controller.py`
- `extensions/taut_summon/taut_summon/cli.py`
- `extensions/taut_summon/taut_summon/commands/summon.py`
- `extensions/taut_summon/taut_summon/command_syntax.py`
- `extensions/taut_summon/taut_summon/__init__.py`
- `extensions/taut_summon/taut_summon/persistence.py`
- `extensions/taut_summon/taut_summon/persistence_manifest.py`
- `extensions/taut_summon/taut_summon/scripted_provider.py`
- `extensions/taut_summon/tests/conftest.py`
- `extensions/taut_summon/tests/test_conformance.py`
- `extensions/taut_summon/tests/test_control.py`
- `extensions/taut_summon/tests/test_controller.py`
- `extensions/taut_summon/tests/test_driver.py`
- `extensions/taut_summon/tests/test_interaction.py`
- `extensions/taut_summon/tests/test_persistence.py`
- `extensions/taut_summon/tests/test_pty_adapter.py`
- `extensions/taut_summon/tests/test_state.py`
- `extensions/taut_summon/tests/test_summon_cli.py`
- `extensions/taut_summon/tests/test_live_harness.py`
- `extensions/taut_summon/tests/test_live_local_llm.py`
- `extensions/taut_tui/tests/test_tui_action_handlers.py`
- `extensions/taut_tui/tests/test_tui_app.py`
- `extensions/taut_tui/tests/test_tui_summon.py`
- `extensions/taut_tui/taut_tui/app.py`
- `.github/workflows/test.yml`
- `tests/test_github_workflows.py`
- `tests/test_core_summon_wheel_matrix.py`
- `docs/specs/04-summon.md`
- `docs/specs/08-persistence-io.md`
- `docs/specs/01-development-documentation-operating-model.md`
- `docs/implementation/05-taut-summon-architecture.md`
- `extensions/taut_summon/README.md`
- `README.md`
- `CHANGELOG.md`
- `docs/plans/README.md`

`tests/test_core_summon_wheel_matrix.py` is listed because persistence-manifest
and public export changes must be checked against built wheels. The TUI tests are
listed because they construct the typed Summon request/status models.

## Invariants and Constraints

1. **One production adapter path.** Every registered production provider uses
   `PtyAdapter`. Platform selection happens below `PtyAdapter.spawn()`, not in
   the provider registry and not in the driver.
2. **No vendor protocol in Summon.** No Claude event types, Claude headless
   flags, structured reply parser, provider session resume path, or public
   `claude-stream` registration remains.
3. **No speculative profile language.** Keep `PtySpec` to the launch and timing
   values used by current CLI/API entry points. Do not add prompt regexes,
   config inheritance, exit-chord tables, or a schema for future harnesses in
   this plan. Add a field only with a named current provider and a firing test
   that needs it.
4. **Speech stays explicit.** PTY screen output is never posted to chat.
   Removing terminal mode must not create screen scraping or implicit routing.
5. **Public surface removal is deliberate.** Remove `--terminal`,
   `SummonRequest.terminal`, `provider_session_id` from result/status models,
   `AssistantTextEvent`, `SessionEvent`, `supports_terminal_mode`,
   `emits_session_events`, and `AdapterHandle.session_id`. Do not retain
   deprecation aliases that keep the second protocol alive.
6. **Storage is logically cleaned without destructive theater.** Keep the
   nullable physical `provider_session_id` column in schema version 3. New
   writes set it to NULL. Persistence component version 2 omits it; the exact
   version-1 loader still accepts and discards the released field. Do not bump
   the sidecar schema or rebuild the table solely to remove this column.
7. **Real legacy recovery.** A stored session whose provider is
   `claude-stream` is reachable through re-summon after upgrading. That start
   must fail with a handled diagnostic that names the recovery sequence: stop
   the old summoned driver if it is live, then summon the same member with
   explicit `--provider claude`. That exact explicit replacement is authorized
   as a one-time compare-and-set only when the stored provider is
   `claude-stream` and driver evidence is either absent or an exact complete
   pid/start-time pair proven dead immediately before the predicated write.
   Live or partial/indeterminate evidence refuses replacement. All other provider
   changes retain the current refusal. This guard exists only for that real
   durable-state path and has a fixture-driven CLI test. Status may report the
   stored legacy provider as data; the registry does not advertise or
   instantiate a compatibility alias.
8. **Process ownership remains terminal-domain ownership.** POSIX keeps the
   existing unreaped-leader/process-group ladder. Windows owns the ConPTY and
   proves termination of a real attached descendant. Leader-only termination
   is not an acceptable green.
9. **One reader, serialized writers.** Both platform handles continuously
   drain output, serialize injection/query replies/attach input, unblock active
   and queued writes on retirement, and emit one `ExitEvent`. On Windows,
   interrupt or `request_close()` invalidates the current write epoch, cancels
   its active `WriteFile` owner, and releases queued writers; reusable interrupt
   rearms a fresh epoch only after the prior owner observes cancellation.
   The sole output-drain thread never performs blocking attach-sink writes;
   ConPTY close must not run on it.
10. **Readiness is evidence, not a provider contract.** Preserve the current
    quiet-settle and bracketed-paste observation behavior. Do not claim that
    bracketed paste is universal readiness. Onboarding recovery continues to
    use it only as observed input-prompt evidence. Changing readiness or idle
    gating needs a separate provider-backed plan.
11. **Cross-platform by default.** The full non-live Summon suite runs on
    Linux, macOS, and Windows. A module-wide `importorskip` or workflow file
    allowlist is forbidden outside the two platform primitive test modules.
12. **Anti-mocking seam stays real.** The scripted child is a real subprocess
    under the same PTY adapter as production providers. Driver/conformance
    tests use a real SQLite broker and real CLI peers. Platform backend tests
    use real PTYs/ConPTY and real descendants. Mocks may cover only injected
    clock/error boundaries already allowed by the current spec.
13. **No unreachable armor.** Every new user-facing guard or recovery branch
    must have a reachability row naming a current public CLI or typed API call,
    the constructible input/state that reaches it, and a firing test through
    that path. If no such path exists, remove the guard. Internal assertions
    may document programmer invariants, but they are not user recovery logic
    and must not add a public error branch.
14. **Failure priority is unchanged.** Spawn, injection, domain retirement,
    reader termination, and child reap failures remain fatal `AdapterError`s.
    Output-tail/status-field collection stays best effort and may only add a
    cleanup note under an existing primary failure.
15. **No fail-open Windows fallback.** An unsupported Windows version, ConPTY
    setup failure, host-console lease failure, or inability to prove owned
    close is a handled adapter failure. Never fall back to plain pipes,
    leader-only termination, or a destructor while claiming PTY behavior.
16. **Narrow native boundary.** `_pty_windows.py` and `_win32_io.py` bind only
    the documented functions used by spawn, I/O, close, console-mode
    setup/restoration, and cancellation. No general Win32 wrapper library,
    guessed retry ladder, or unused error classification is added.
17. **Overlap boundary.** Before editing `_state.py`, its tests, or
    `_win32_job.py`, recheck the active semantic-compatibility and process-
    containment plans. Preserve their landed historical v2 fixture and any
    concurrent worktree changes. This plan deletes `_win32_job.py` only after
    Windows ConPTY proof supersedes it.

## Guard Reachability Register

This table is normative for implementation and review. No other public guard
may be added without first adding a row here.

| Guard or failure branch | Real entry point | Constructible cause | Required firing test |
|---|---|---|---|
| Unknown provider | `taut summon NAME --provider VALUE` and `SummonController.run_foreground()` | `VALUE` is absent from `adapter_names()`; `claude-stream` is absent after removal | CLI and typed API assert handled error, known names, no traceback |
| Legacy stored `claude-stream` session | `taut summon NAME` and `SummonController.run_foreground()` against a pre-change sidecar/dump | Durable v3 row names `claude-stream`; replacement is omitted, names another provider, has live or partial driver evidence, or explicitly selects `claude` after driver evidence is absent or a complete pid/start-time pair is proven dead | Real SQLite fixtures exercise absent-evidence and proven-dead compare-and-set replacement, plus omitted, other-provider, live, both partial-evidence, and predicate-loss refusals through console and controller |
| Removed terminal flag | `taut summon ... --terminal` and `taut-summon run ... --terminal` | User invokes a removed public option | Both parsers reject with their existing usage-error exit 1 and no traceback; no custom compatibility guard |
| Malformed PTY environment values | `taut summon NAME --provider pty` and `SummonController.run_foreground()` with `TAUT_SUMMON_PTY_*` environment | Existing public environment variable is invalid | CLI and typed API firing tests assert the handled error; private `get_adapter("pty")` tests are supporting evidence only |
| PTY executable missing | Either public console or controller selecting a registered provider whose executable is absent | PATH has no requested binary | Cross-platform public-path test asserts handled spawn failure, retention of the already-published durable member/session required by token-before-spawn ordering, and release of transient name and driver claims |
| Windows PTY runtime unavailable | Public console/controller on Windows | Required ConPTY function is absent or `CreatePseudoConsole` fails | Windows backend boundary injection plus one public CLI test; diagnostic names Windows PTY initialization, never Claude |
| Windows ConPTY read/write/close failure | Public console/controller on Windows | Real child closes a channel, blocks a write, exits first, or leaves a descendant | Real ConPTY lifecycle tests plus driver STOP tests assert bounded exit and original-error priority |
| POSIX PTY fd/signal failure | Public console/controller on POSIX | Real child closes master, exits first, or survives graceful signal | Existing real PTY/process-group probes moved to explicit POSIX modules |
| Legacy dump field | `taut load FILE` / persistence component API | Version-1 released dump contains `provider_session_id` | Exact version-1 record is accepted and discarded; a version-2 re-dump omits the field |

Not proposed because no current firing path justifies them: provider-profile
schema validation, prompt-regex compilation, per-provider exit-chord fallback,
unknown structured-event tolerance, structured stream EOF normalization, and a
`claude-stream` compatibility adapter.

## Proposed Spec Delta

Promotion strategy: A, in-file text before link claims. Apply the following
exact replacements to the active specs before dependent production edits.

| Spec file | Strategy | Sections touched |
|---|---|---|
| `docs/specs/04-summon.md` | A | [SUM-1], [SUM-2], [SUM-3], [SUM-6], [SUM-7.1], [SUM-7.2], [SUM-7.3], [SUM-7.4], [SUM-8], [SUM-9], [SUM-11], [SUM-12], [SUM-13], [SUM-13.1], Related Plans |
| `docs/specs/08-persistence-io.md` | A | [PIO-5.3] Summon record shape |
| `docs/specs/01-development-documentation-operating-model.md` | A | [DOM-10.2] suppression rationale and generated index |

### `docs/specs/04-summon.md` [SUM-1] purpose replacement

Replace the first sentence of [SUM-1] with:

> `taut summon` hosts any interactive agent CLI as an ordinary member of a
> taut workspace. Summon does not build an agent loop, a task runtime, a
> provider protocol adapter, or a sandbox; the harness already owns tool
> dispatch, session state, interruption, and permissions.

### `docs/specs/04-summon.md` [SUM-2] ears, mouth, and captivity replacement

Replace the two paragraphs that distinguish structured and PTY output with:

> **Ears and mouth.** The summoned member's *ears* are an injected stream: the
> summon driver watches every thread the member has joined plus its
> notification inbox and pushes each message into the harness's live terminal.
> The ordinary member *mouth and hands* are the taut CLI itself. The agent
> speaks by running `taut say`, `taut reply`, or another explicit Taut command,
> selected as its member by its continuity token. Summon never interprets or
> routes terminal output as speech.
>
> **Captive process, free agent.** The harness child is a captive process: the
> driver spawns it on an operating-system pseudoterminal, owns its terminal
> I/O, signals it, anchors presence to it, and retires its terminal domain.
> The terminal output is read only for coarse activity, bounded terminal-query
> replies, attach display, and diagnostics. Conversation state belongs to the
> harness and is not parsed or persisted by Summon.

Replace the Windows lifecycle paragraph with:

> Lifecycle captivity includes the provider leader and descendants that remain
> attached to its terminal domain. POSIX retains the process-group guarantee
> defined in [SUM-7.4]. Windows owns one ConPTY session and closes that session
> while its output remains drained; the real-process acceptance test must show
> that an attached descendant is absent afterward. Neither mechanism is a
> sandbox and neither chases a process that deliberately escapes its platform
> terminal domain.

### `docs/specs/04-summon.md` [SUM-3] packaging replacement

Keep the existing sole `taut-chat` runtime dependency claim. Add:

> Summon's Windows ConPTY support uses the operating-system API through a
> narrow standard-library boundary and adds no runtime package.

Remove `--terminal` from every command synopsis and option list in [SUM-3].

### `docs/specs/04-summon.md` [SUM-6] replacement

Replace [SUM-6] from “stdout is diagnostics” through the terminal-mode rules
with:

> **Terminal output is diagnostics, not speech.** The driver never posts
> harness terminal output to chat and never parses a provider reply envelope.
> Output may update coarse activity, answer a finite set of terminal queries,
> feed an explicit human attach, and contribute a bounded control-stripped
> diagnostic tail. The agent's only mouth is an explicit Taut command. A human
> watches a hosted agent through attach, not through output mirroring.

### `docs/specs/04-summon.md` [SUM-7.1] interface replacement

Replace the protocol block and event-union paragraphs with:

> The provider adapter surface is deliberately terminal-shaped:
>
> ```python
> class ProviderAdapter(Protocol):
>     supports_attach: bool
>     orientation_via_inject: bool
>
>     def spawn(self, *, system_prompt: str,
>               env: Mapping[str, str]) -> AdapterHandle: ...
>     # AdapterHandle:
>     def inject(self, text: str) -> None: ...
>     def events(self) -> Iterator[ActivityEvent | ExitEvent]: ...
>     def interrupt(self) -> None: ...
>     def request_close(self) -> None: ...
>     def close(self) -> None: ...
> ```
>
> Summon defines no provider event protocol. All production providers use the
> interactive PTY adapter. The adapter emits coarse `ActivityEvent` values and
> exactly one terminal `ExitEvent`; it emits no assistant-text or provider-
> session event. `inject()` is flushed at the child terminal boundary.

Replace the platform process-domain and structured-stream paragraphs with:

> `PtyAdapter.spawn()` selects a POSIX PTY or Windows ConPTY implementation.
> The registry and driver do not branch by platform. POSIX process groups and
> Windows ConPTY sessions are platform-specific owned capabilities. Both
> implementations preserve reusable interrupt, one terminal close request,
> bounded finalization, serialized writes, continuous output drain, and one
> exit event. Windows may not fall back to plain pipes or direct-child-only
> cleanup when ConPTY setup fails.

Remove `supports_terminal_mode`, `emits_session_events`, the handle
`session_id`, every structured-stream EOF rule, and every assistant/session
event rule from [SUM-7.1]. Keep the existing detailed interrupt,
`request_close()`, `close()`, activity, attach, output-tail, and failure-
priority contracts where they do not mention the deleted stream path.

### `docs/specs/04-summon.md` [SUM-7.2] replacement

Replace [SUM-7.2] with:

> ### [SUM-7.2] Adapters shipped
>
> - `pty` is the sole production adapter. It hosts every named provider
>   (`claude`, `codex`, `coder`, `grok`, `qwen`, `kimi`, `opencode`, `pi`, and
>   future interactive CLIs) through the same terminal path. Provider entries
>   contain only the executable argv and values already represented by
>   `PtySpec`; they are not protocol adapters.
> - `scripted` is a packaged test registration for the same PTY adapter. Its
>   real interactive child publishes terminal readiness, accepts terminal
>   input, records received turns, and exercises explicit Taut commands. It is
>   the anti-mocking seam for downstream conformance and contains no second
>   adapter or wire protocol.

### `docs/specs/04-summon.md` [SUM-7.4] platform addition

Replace the POSIX-only spawn opening with:

> **Spawn.** `PtyAdapter` validates one `PtySpec`, then selects a platform
> implementation below the adapter boundary. On POSIX, `pty.openpty()` and the
> shared POSIX process-domain owner retain the current fd and process-group
> behavior. On Windows, the adapter calls the documented CreatePseudoConsole
> and ClosePseudoConsole APIs through `ctypes`, passes the
> pseudoconsole in `STARTUPINFOEX`, and owns the input/output pipe handles.
> ConPTY input and output are serviced on independent threads. Output remains
> drained through close, and `ClosePseudoConsole` owns the terminal session
> rather than only the leader PID. The registry, driver, readiness policy,
> terminal-query responder, injection framing, diagnostics, and adapter event
> contract remain platform-neutral.

Add after the configuration-validation paragraph:

> Validation exists only for values constructible through `PtySpec` or the
> documented `TAUT_SUMMON_PTY_*` environment variables. Platform setup errors
> are normalized to `AdapterError` at `PtyAdapter.spawn()`. The adapter does not
> validate speculative provider profiles or unreachable internal states.

Add to the attach contract:

> On Windows, attach converts the lease's input/output fds to owned Win32
> handles. A console input handle is switched from line/echo processing to
> virtual-terminal input after its exact mode is saved; restoration occurs on
> every exit. A dedicated blocking `ReadFile` owner scans the existing detach
> chord and is cancelled with `CancelSynchronousIo` during detach or shutdown.
> Non-console handles supplied by a rich host skip console-mode mutation but use
> the same owned read/cancel path. Output uses the lease's output handle. A
> failed mode change, cancellation, restoration, or write follows the existing
> attach failure-priority rules; there is no fallback to cooked `input()`.

### `docs/specs/04-summon.md` [SUM-7.3] replacement

Replace [SUM-7.3] with:

> ### [SUM-7.3] Session continuity
>
> Session persistence belongs entirely to the harness. Summon neither receives
> nor stores a provider session id. Every provider-generation restart starts a
> fresh interactive process and replays unread chat through the existing
> cursor contract. Chat history is the durable conversation; provider-local
> state is outside Summon's recovery guarantee.

### `docs/specs/04-summon.md` [SUM-8] durable session replacement

Replace the `taut_summon_sessions` and persistence-I/O field lists with:

> `taut_summon_sessions` durably stores member id, continuity token, provider,
> driver pid/start-time evidence, PTY onboarding `wired`, and updated timestamp.
> The historical nullable `provider_session_id` SQL column remains physical
> compatibility ballast in schema version 3 but is not part of the typed model,
> status output, or persistence component version 2; new writes leave it NULL.
> The exact version-1 persistence reader accepts and discards its required
> string-or-null `provider_session_id`; version 2 rejects that field. A stored
> provider value of `claude-stream` is not silently rewritten. Public start
> without an explicit replacement returns a handled diagnostic. If driver
> evidence is absent, or a complete pid/start-time pair is proven dead, an
> explicit `--provider claude` start performs one transactionally predicated
> rewrite from exactly `claude-stream` to `claude`. The predicate includes the
> exact classified driver evidence, clears stale evidence, and fails if the row
> changes concurrently. Live evidence, either partial-evidence orientation, and
> every other stored-provider mismatch remain errors. Status may display the
> stored legacy provider value before replacement.

### `docs/specs/04-summon.md` [SUM-9] status replacement

Replace `session_id` in the fixed STATUS snapshot fields and reserved-key list
with no field. Remove provider-session update methods from the control-loop
contract. The snapshot continues to expose `provider`, driver/control health,
rate fields, thread/cursor state, and adapter detail fields.

### `docs/specs/04-summon.md` [SUM-11] crash replacement

Replace “attempts one resume (session id, then cursor replay)” with:

> attempts one fresh interactive spawn and resumes delivery from durable chat
> cursors

Replace “pump exit or injection failure remains the harness-resume path” with:

> reader exit or injection failure remains the fresh-generation recovery path

Remove `session` and `terminal-mode chat` from stale-generation side effects;
retain activity, driver fields, durable ledger, control state, presence, and
wake-state fencing.

### `docs/specs/04-summon.md` [SUM-12] verification replacement

Replace the structured-adapter and platform test paragraphs with:

> The provider seam is the packaged `scripted` registration over the production
> PTY adapter and a real interactive child. Broker, sidecar, CLI, child process,
> and PTY/ConPTY are not mocked. Driver, controller, CLI, persistence,
> conformance, and shared terminal-behavior tests collect and run on Linux,
> macOS, and Windows. Only tests whose subject is a POSIX fd/process-group
> primitive or a Windows ConPTY primitive carry a platform marker or skip.
>
> CI runs the same complete non-live Summon selection on each operating system;
> it does not use a Windows file allowlist. POSIX primitive tests prove the
> unreaped-leader process-group ladder. Windows primitive tests prove real
> ConPTY spawn, input, output drain, reusable interrupt, bounded close, and
> attached-descendant retirement. Common adapter conformance is parameterized
> over the platform implementation selected by production code.
>
> Every new guard includes a firing proof through a current CLI or public typed
> API path. A guard with no constructible production input/state is removed
> rather than preserved as defensive ceremony.

Delete terminal-mode, stream-json, provider-session resume, Windows Job Object,
and Windows pipe-specific verification bullets from [SUM-12]. Retain all
platform-neutral lifecycle, control, broker, stale-generation, and release
proofs.

### `docs/specs/08-persistence-io.md` [PIO-5.3] replacement

Replace the Summon record field list with:

> Summon exports `member_id`, `token`, `provider`, `wired`, and `updated_ts`.
> Persistence component version 2 exports `member_id`, `token`, `provider`,
> `wired`, and `updated_ts`. Its reader requires exactly that shape. The exact
> component-version-1 reader continues to require the released
> `provider_session_id` field, validates it as string or null, and discards it.
> The manifest writes version 2 and loads versions 1 and 2. This one-way read
> compatibility does not preserve a provider-session runtime API. This changes
> the component record `write_version` and `load_versions`; the persistence
> protocol's `component_api_version` remains 1.

### `docs/specs/04-summon.md` [SUM-13] and [SUM-13.1] replacements

In `SummonRunHandle`, replace the member description with:

> The `SummonRunHandle` contains the actual `SummonedMember`: member id,
> collision-resolved current name, and provider. It exposes that value as
> immutable field `member: SummonedMember` plus `request_stop()`.

In the controller model paragraph, replace the request and result field lists
with:

> The request model contains `name`, `threads`, `persona`,
> `system_prompt_file`, `rate_limit`, `attach`, `detach`, `provider_flag`, and
> `takeover`. A live summary contains member id, current name, and provider.
> Status contains those identity/provider values plus driver, thread count,
> cursor lag, and defensive copies of remaining validated JSON-primitive
> detail fields.

Replace “all three shipped adapter families” in [SUM-13] verification with
“the single PTY adapter on each supported platform.” Replace provider-session
precedence and crash-resume verification with exact member/provider delivery
and once-only callback delivery across a fresh-generation restart.

### `docs/specs/01-development-documentation-operating-model.md` [DOM-10.2]

Update the authoritative Ruff suppression registry and generated index in the
same slice as symbol moves/deletions. Remove entries for deleted structured
tests and `_win32_job.py`; rename retained `_pty.py` locations to their actual
new owner only when the suppression remains necessary. Recount every affected
group and run the repository suppression checker. Do not preserve a
suppression for a deleted symbol and do not create replacement suppressions
until Ruff produces a concrete diagnostic on the new code.

## Deletion Ledger

Delete these production files after their replacement proofs are green:

| Delete | Replacement or reason |
|---|---|
| `taut_summon/_claude.py` | No provider-specific protocol adapter remains |
| `taut_summon/_stream.py` | No structured pipe event path remains |
| `taut_summon/_scripted.py` | `scripted` becomes a `PtyAdapter` registration |
| `taut_summon/_win32_pipe.py` | Structured pipe cancellation disappears |
| `taut_summon/_win32_job.py` | Windows terminal domain is owned by ConPTY after descendant proof |
| `taut_summon/_process_domain.py` | Replaced by explicitly POSIX `_process_domain_posix.py` |

Delete these tests rather than mechanically porting obsolete contracts:

| Delete | Why |
|---|---|
| `tests/test_claude_adapter.py` | Tests deleted Claude stream translation and flags |
| `tests/test_scripted_adapter.py` | Tests the deleted stream handle and stream-json shapes |
| `tests/test_win32_pipe.py` | Tests deleted structured pipe cancellation |
| `tests/test_win32_job.py` | Tests deleted Job Object owner; ConPTY tests replace the user contract |
| `tests/test_process_domain.py` | Split: retain only real POSIX guarantees in `test_pty_posix.py`; common lifecycle moves to adapter conformance |
| `tests/fixtures/claude_stream_sample.jsonl` | Fixture has no consumer after Claude stream translation tests are deleted |

Within retained tests, delete cases for terminal-mode posting, blank assistant
events, session event waits, session resume IDs, unknown structured events,
stream EOF normalization, Claude headless flags, and registry capability flags.
Do not preserve these as unit tests against dead helpers.

Delete documentation claims for `claude-stream`, terminal mode, parsed replies,
structured adapters, Job Objects, cancellable structured pipes, and provider
session IDs from the active spec, implementation note, READMEs, and current
changelog entry. Historical completed plans and old changelog entries remain
historical records; do not rewrite them.

## Test Portability Matrix

| Test owner | Linux | macOS | Windows | Rule |
|---|---:|---:|---:|---|
| Driver, controller, CLI, control, interaction, state, persistence | run | run | run | No platform marker, skip, or import guard |
| Provider conformance and scripted real-process flows | run | run | run | Same `scripted` registry and child path as production PTY |
| Shared terminal parsing, query response, paste framing, readiness, output tail | run | run | run | Pure helpers or selected production backend; no POSIX imports |
| Live named-provider tests | opt-in/installed | opt-in/installed | opt-in/installed | Existing explicit live markers only |
| POSIX fd, termios, signals, process groups, raw host attach | run | run | skip | `posix_only` on the individual native test; process-domain tests live in `test_pty_posix.py` |
| Windows ConPTY creation, channel cancellation, terminal-domain close | skip | skip | run | `windows_only` marker in `test_pty_windows.py` only |

Add `posix_only` and `windows_only` marker declarations. The workflow invokes
the full non-live Summon test tree on each OS and selects `not windows_only` on
POSIX or `not posix_only` on Windows. It may keep separate ordinary/process
shards for time and xdist topology, but both shards select by markers rather
than filenames. `tests/test_github_workflows.py` must fail if a Windows Summon
step names individual test files or omits the driver/conformance selection.

## Tasks

### Slice 0: Review and baseline

1. Run the required fresh-eyes review and separate model-family review against
   this draft, the spec baseline, implementation note, code owners, deletion
   ledger, portability matrix, and guard register.
2. Disposition every finding in the Review Log. Revise the plan and repeat a
   scoped review for accepted blockers.
3. Recheck worktree overlap and record blobs for every active spec touched.
4. Run `uv run bin/check-plan-status-index`, `uv run bin/check-doc-paths`, and
   `uv run --extra dev pytest tests/test_docs_references.py -v`.

Stop if a reviewer cannot identify a public firing path for a proposed guard,
or if the deletion ledger misses an import/export/test owner.

### Slice 1: Qualify native ConPTY before changing the contract

1. On hosted Windows, run a bounded throwaway probe against every function and
   ownership transition in the complete Windows native API ledger above. The
   probe is review evidence, not shipped code.
2. The real probe child creates an attached descendant, publishes a ready
   token, echoes injected UTF-8 text, emits observable VT output, accepts the
   Ctrl-C terminal input sequence, survives one reusable interrupt, and
   then remains alive until pseudoconsole close. Separate read and write owners
   keep output drained. Force the ConPTY input `WriteFile` owner to block;
   prove reusable interrupt invalidates its epoch, cancels that exact writer,
   releases queued writers, and rearms only after cancellation is observed.
   Repeat under `request_close()` and prove no rearm. The probe records leader
   and descendant identities and proves both absent after bounded close.
3. Allocate or open a real test console in a separate probe process. Save exact
   input and output modes plus input and output code pages; enter raw/VT input,
   VT processed output, and UTF-8 code pages; exercise non-ASCII input/output;
   cancel a blocked `ReadFile`; and prove exact restoration of all four values.
   A pipe-backed rich-host lease separately proves detach-chord scanning while
   `GetConsoleMode` classifies it as non-console and no mode mutation occurs.
4. Record the HRESULT returned by `CreatePseudoConsole`. For every other
   retained Win32 call, capture `GetLastError` immediately only when its
   documented failure sentinel occurs: FALSE, NULL/`INVALID_HANDLE_VALUE`,
   `WAIT_FAILED`, `DWORD(-1)`, or zero code page. Treat the first
   `InitializeProcThreadAttributeList(NULL, ...)` FALSE plus
   `ERROR_INSUFFICIENT_BUFFER` as the expected sizing protocol, not a forced
   failure. Do not read `GetLastError` after success or void/pseudo-handle
   calls; record `msvcrt.get_osfhandle` as its Python/OSError result. Record
   timing, cancellation order, whether final bytes appeared after close entry
   without requiring them, output EOF/broken-pipe observation, and cleanup
   order in this plan's execution log. Delete the throwaway probe after the
   evidence is captured.

Stop and revise the plan before spec promotion if any required operation needs
an undocumented API, destructor timing, leader-only kill, polling without a
bounded wait object, or a guard that cannot be fired through the planned
console/typed API path.

### Slice 2: Promote the contract deletion

1. Apply the exact spec delta to [SUM] and [PIO]. Add this plan to [SUM]'s
   Related Plans.
2. Update the implementation note only enough to describe the target owner
   boundaries and mark the structured path as pending deletion. Do not claim
   code completion.
3. Record the promotion baseline and run spec/reference/CLI-claim checks. The
   [DOM-10.2] normative rule is promoted here, but its exact location index is
   not changed until each owning symbol moves or is deleted.

Stop if active normative text still requires a structured adapter, terminal
mode, provider-session resume, Job Object, or Windows pipe path.

### Slice 3: Red tests for one interactive adapter and public deletions

1. Add failing registry tests: every production name resolves to `PtyAdapter`;
   `claude-stream` is unknown and not advertised; `scripted` also resolves to
   `PtyAdapter`.
2. Add failing CLI and typed API tests for removal of `--terminal`, terminal
   request/model fields, provider-session result/status fields, and the
   assistant/session adapter events and capabilities.
3. Add the real SQLite legacy-provider and exact component-version-1 dump
   firing probes from the guard register. Prove the one-time `claude-stream`
   to `claude` compare-and-set for both absent driver evidence and a complete
   pid/start-time pair proven dead. Prove predicate-loss, live evidence, both
   partial-evidence orientations, omitted replacement, and every other provider
   mismatch are refused.
4. Rewrite the scripted child contract tests as interactive PTY tests before
   deleting the old stream tests. The child must publish terminal readiness,
   receive bracketed/plain terminal input, write a received-log, run real Taut
   CLI speech, model a stalled turn, and expose bounded signal/close evidence.

Stop if a proposed compatibility branch is reachable only by importing a
private helper or manually constructing an invalid internal object.

### Slice 4: Implement Windows ConPTY behind the existing adapter boundary

1. Implement `_win32_io.py` as the narrow shared native boundary: exact-width
   handles/errors, fd-to-handle duplication, raw read/write, exact-thread
   cancellation, and console mode/code-page snapshot and restoration. Reuse
   the ownership pattern from `interaction.py`; keep its TextIO `readline()`
   arbitration there rather than generalizing it into a Win32 framework.
2. Implement `_pty_windows.py` with explicit handle ownership for the two
   ConPTY pipes, pseudoconsole, attribute list, child process/thread, reader,
   write serialization, and close state. Create the child through
   `STARTUPINFOEX`; continuously drain output on its own thread; close the
   pseudoconsole from the lifecycle owner; join the reader; then inspect/reap
   the child and release handles.
3. Implement attach with the Slice 1 console/pipe behavior: duplicate but never
   close borrowed lease handles; exact input/output mode and code-page
   save/configure/restore; blocking `ReadFile` on a dedicated input owner; the
   sole ConPTY reader plus generation-tagged attach-output writer above;
   `CancelSynchronousIo` on detach/shutdown; and shared detach-chord scanning.
   Test each failure through an actual `run_foreground()` host interaction
   where constructible.
4. Wire `PtyAdapter.spawn()` to select the Windows handle, but leave the old
   structured adapter available until all real Windows driver/conformance
   proofs pass.

Stop if the implementation needs general Win32 wrappers, retries not justified
by an observed API result, private third-party state, or a second driver path.

### Slice 5: Remove structured runtime and public surface

1. Reduce `_adapter.py` to activity/exit events and terminal capabilities.
   Register `scripted` via `PtyAdapter(PtySpec(...scripted_provider...))`.
2. Remove terminal-mode and provider-session branches from driver, control,
   controller, CLI, command syntax, typed models, and exports.
3. Keep the physical sidecar column. Set it NULL on new writes and remove it
   from typed models. Promote persistence component version 2 and split
   `persistence.py` validation into exact v1 and v2 field sets. Make
   `_state.persistence_records()` and the component's `dump_records()` omit
   `provider_session_id`; make `_state.load_persistence_records()` write SQL
   NULL for every v2 record instead of indexing the omitted key. Retain a
   distinct exact version-1 normalization path that validates and discards
   `provider_session_id` before calling the state loader. Add firing tests that
   a fresh v2 dump lacks the key and a v2 record loads without `KeyError`, plus
   the released v1 load/re-dump probe. Update `persistence_manifest.py` to
   write 2 and load `{1, 2}` while leaving `component_api_version=1`.
4. In `_driver.py`'s existing re-summon provider-mismatch branch (currently the
   `_bootstrap()` refusal before `_require_adapter()`), intercept only the
   stored `claude-stream` plus explicitly requested `claude` pair. Apply the
   targeted exact-evidence compare-and-set there, not in a second bootstrap
   path. Permit it only when evidence is absent or the complete pid/start-time
   pair is proven dead; clear stale evidence in the same transaction. Refuse
   live, partial, changed, and arbitrary-provider cases. Do not add a hidden
   registry alias.
5. Delete `_claude.py`, `_stream.py`, `_scripted.py`, `_win32_pipe.py`, and
   their obsolete tests. Run `rg` for each deleted symbol/flag/name and
   disposition every remaining hit as active, compatibility, or history.
6. In this same deletion slice, remove or recount [DOM-10.2] suppression groups
   whose structured symbols/tests disappeared, regenerate the index, and run
   `uv run --no-sync --extra dev python bin/ruff_suppression_index.py --check`.

Stop if removing provider-session fields would require rebuilding the sidecar
table, or if any screen-output-to-chat behavior appears.

### Slice 6: Split PTY platform mechanics without changing POSIX behavior

1. Move POSIX-only imports, spawn, fd attach, termios, signals, and process-
   group ownership into `_pty_posix.py` and `_process_domain_posix.py`.
2. Leave `PtySpec`, validation, platform selection, terminal state/query
   parsing, paste framing, diagnostic-tail rules, and registry construction in
   `_pty.py` unless a real platform implementation requires a smaller pure
   helper. Do not create a general backend class hierarchy.
3. Move only POSIX primitive tests into `test_pty_posix.py`. Run every retained
   common PTY behavior test unchanged on POSIX.
4. In this same move slice, rename only still-live [DOM-10.2] suppression
   locations, remove any suppression that Ruff no longer emits, regenerate the
   index, and run the suppression checker.

Stop if common code begins importing a POSIX module at import time, if the
driver branches on `os.name`, or if the split changes existing POSIX terminal
bytes/lifecycle behavior before Windows code exists.

### Slice 7: Make common Summon tests truly cross-platform

1. Remove module-wide `pytest.importorskip("taut_summon._pty")`, broad
   `sys.platform` skips, and Windows test-file allowlists from all common test
   owners.
2. Port `test_pty_adapter.py`, driver, controller, CLI, control, interaction,
   persistence, TUI, and
   conformance fixtures to the interactive scripted PTY child. Preserve real
   broker, real process, peer CLI, backpressure, stale generation, control,
   readiness, attach, and cleanup assertions.
3. For every existing `importorskip("pty")`, `importorskip("termios")`,
   `sys.platform`, and `os.name` hit in Summon and TUI tests, record exactly one
   disposition: rewrite against the selected production backend, move a true
   POSIX primitive to `test_pty_posix.py`, move a true Windows primitive to
   `test_pty_windows.py`, or delete it because its contract was removed.
4. Parameterize shared adapter contract tests over the production-selected
   platform handle. Keep POSIX and Windows implementation details in their two
   explicit primitive modules.
5. Change CI process shards to marker selection over the full test tree. Add
   workflow-structure tests that reject a future Windows filename allowlist.
6. Run collection-only gates on all OSes and compare test IDs. Differences are
   allowed only for `posix_only`, `windows_only`, and existing live-provider
   markers.

Stop if portability is achieved by weakening assertions, replacing real
processes with mocks, or marking a driver/control/conformance test platform-
specific.

### Slice 8: Documentation, deletion audit, and release evidence

1. Rewrite the implementation note and Summon README around one interactive
   adapter with POSIX and Windows mechanics. Remove current docs for terminal
   mode and `claude-stream`.
2. Update root README provider and Windows claims, current changelog entry,
   public export/API tables, `taut_tui/app.py`, and persistence manifest
   documentation.
3. Run an exhaustive deletion audit with `rg` for all removed files, symbols,
   flags, events, capabilities, and persistence fields. Historical plans and
   released changelog entries are the only allowed historical references.
4. Build wheel and sdist; inspect contents to prove deleted modules are absent,
   the interactive scripted child remains packaged, and the component-version
   manifest is correct.
5. Run final fresh-eyes and different-family completed-work review. Reproduce
   findings before changes and disposition all of them.

Stop if docs advertise a capability not exercised through a public CLI/API
acceptance test, or if an obsolete structured module ships in either artifact.

## Testing Plan

Red-green TDD is mandatory for Slices 3 through 7. Each slice lands its failing
contract proof before production changes, then turns only that proof green.

Minimum local gates:

```text
uv run bin/check-plan-status-index
uv run bin/check-doc-paths
uv run bin/check-cli-claims
uv run --no-sync --extra dev python bin/ruff_suppression_index.py --check
uv run --extra dev pytest tests/test_docs_references.py -v
uv run --extra dev pytest tests/test_github_workflows.py tests/test_core_summon_wheel_matrix.py -v
cd extensions/taut_summon && uv run --extra dev pytest tests -m "not requires_live_harness and not requires_local_llm" -v
cd extensions/taut_summon && uv run --extra dev mypy taut_summon
cd extensions/taut_summon && uv run --extra dev ruff check taut_summon tests
cd extensions/taut_summon && uv run --extra dev python -m build
```

Hosted gates:

- Linux and macOS: full non-live Summon ordinary and process shards excluding
  only `windows_only` and explicit live markers.
- Windows `windows-latest` x64 lane: the same full non-live Summon shards
  excluding only `posix_only` and explicit live markers. No arm64 execution
  claim is made because the repository has no Windows arm64 runner.
- Collection audit: compare collected common test IDs across Linux, macOS, and
  Windows. Explain every difference in the portability matrix.
- Existing local-LLM and installed live-provider lanes remain required for the
  providers they cover. Add Windows live harness execution only where CI has
  an installed/authenticated provider; do not fake credentials.

Acceptance probes through public surfaces:

- `taut summon scripted general`, peer `taut say`, `taut-summon status
  scripted`, and `taut dismiss scripted` complete with a real PTY/ConPTY child
  on every OS.
- `taut summon reviewer --provider claude` reaches a handled missing-binary or
  live-harness result on Windows, never a raw `fcntl` import traceback.
- `taut summon reviewer --provider claude-stream` fails as an unknown adapter
  and does not list it among known adapters.
- both console surfaces reject `--terminal` with their existing normal usage
  output and exit 1, not a custom runtime branch.
- a released-shape dump containing `provider_session_id` loads and re-dumps
  without that field.
- a pre-change sidecar naming `claude-stream` reaches the exact recovery
  diagnostic through start and remains non-mutated until an explicit-provider
  replacement start.
- Windows STOP closes the ConPTY while continuously draining output and removes
  an attached descendant; POSIX STOP retains current process-group behavior.

## Verification and Evidence Gates

The implementation is not ready to land until the execution log records:

- changed and deleted file lists matched against this plan;
- each guard-register row with the exact test ID and observed result;
- per-OS collection counts and the explicit platform-only differences;
- Linux, macOS, and Windows full non-live Summon results;
- Windows real ConPTY leader-and-descendant identity evidence;
- POSIX real process-group evidence;
- wheel/sdist content and metadata inspection, including persistence manifest
  write version 2 / load versions 1 and 2;
- `rg` deletion audit results;
- exact commands, exit codes, and residual risks;
- independent completed-work findings and dispositions;
- commit SHA verified by `git log` only if the owner later authorizes landing.

Post-release success is observable when a clean Windows install can run the
scripted public flow and a named provider no longer raises `ModuleNotFoundError`
for POSIX modules. A failure in ConPTY spawn/close is a release blocker, not a
warning. No telemetry system is introduced for this change.

## Rollout, Rollback, and One-Way Doors

Rollout order is strict: reviewed plan, throwaway native ConPTY qualification,
spec promotion, Windows backend behind the existing boundary, public/stream
deletion, POSIX split, old Windows owner deletion, cross-platform CI expansion,
docs/artifacts, final review. Do not promote the Windows contract or delete the
Job Object path before hosted ConPTY descendant proof.

The public removal of `claude-stream`, `--terminal`, typed fields, and
persistence component version 1 as the write format is a breaking release
boundary and must be called out in release notes. Existing databases remain
schema version 3, so code rollback to the prior release remains possible. New
versions leave the old nullable session-id column intact. A prior release
cannot load a version-2 dump; that is an explicit format-version boundary, not
an accidental compatibility claim. The new release must continue to load exact
version-1 dumps.

Deleting the five custom Windows/stream modules is reversible in source. A
published breaking release is not. Do not publish until Windows hosted proof,
built-artifact inspection, and final review pass.

## Independent Review

Two plan reviews are required and serve different purposes:

1. **Fresh eyes:** a read-only reviewer with repository access checks every
   named file/flag/seam, deletion completeness, task order, cross-platform test
   classification, and guard reachability. It is specifically asked to remove
   work that has no current code path or contract value.
2. **Cross-model:** a review-eligible agent family different from the author
   receives the full plan text, spec baseline, proposed delta, implementation
   note, key code/tests, accepted risks, and the same anti-over-armor question.
   It returns PASS or BLOCKED using the repository review gate.

Both reviews must answer:

- Could this be implemented correctly without inventing a missing behavior?
- Would it degrade lifecycle correctness or Windows support?
- Does every proposed guard have a real CLI/API firing path and firing test?
- Does any retained compatibility layer cost more than the real recovery path
  justifies?
- Are any common tests still excluded on Windows for implementation
  convenience rather than platform semantics?

Findings are claims. Reproduce them against code before changing the plan.
Every finding receives an accepted, rejected, or out-of-scope disposition. A
round-2 review covers only accepted blocker fixes and defects introduced by
those fixes.

## Review Log

| Review | Reviewer / invocation | Verdict | Findings | Disposition |
|---|---|---|---|---|
| Fresh eyes | repository subagent, read-only, rounds 1–4, 2026-09-03 | PASS | Initial F1–F8: incomplete spec/suppression delta, unqualified pywinpty lifecycle and ordering, unreachable legacy recovery, unspecified Windows attach, persistence-version misuse, wrong public API/exit evidence, incomplete file/skip census, and nonexistent arm64 lane. Follow-up N1: blocked ConPTY input writer lacked a cancellable owner. | All accepted and reproduced. The plan now ties suppression edits to symbol moves/deletion; uses a pre-spec native ConPTY qualification gate; defines exact legacy CAS states; specifies one-reader attach routing and handle ownership; promotes persistence v2 with an exact v1 reader; corrects public firing paths; completes the deletion/test census; limits hosted execution to available x64; and assigns blocked input writes to an epoch-controlled cancellable owner. Round 4 passed with no scoped blocker. |
| Cross-model | Claude Opus 2.1.207, read-only plan mode with `Read,Grep,Glob`, 2026-09-03 | PASS | P2-1 make the v2 state-loader field drop explicit; P2-2 define separate persistence v1/v2 field sets and fresh-dump proof; P2-3 place legacy CAS in the existing re-summon refusal branch. Observations: state `_darwin_wait.py` disposition and distinguish component record version from component API version. | All reproduced and accepted. Slice 5 now names the exact dump/load functions, v1/v2 normalization boundary, v2 load and fresh-dump firing tests, unchanged `component_api_version=1`, and the existing `_driver._bootstrap()` mismatch branch as the sole CAS site. Current ownership now states that `_darwin_wait.py` remains the Darwin helper under the renamed POSIX process-domain owner. No new guard or scope was added. |
| Slice 1 preflight | repository subagents, read-only code/API audit plus scoped fresh-eyes rounds, 2026-09-03 | PASS after correction | `ResizePseudoConsole` and `SetHandleInformation` had no public firing path; direct attach-sink writes could block the sole ConPTY drain; pipe-handle cleanup preceded child creation; classic-console output/UTF-8 restoration was incomplete; HRESULT/error-sentinel evidence was conflated; attach-writer timeout ownership was ambiguous. | All accepted. The two unreachable bindings were deleted from the plan. Pipe ends now survive through child creation. Attach output has a separate generation-tagged cancellable writer. Input/output modes and code pages restore exactly. Error evidence follows each documented return domain. A timed-out sink handle is quarantined until writer exit and cannot be reused. The final scoped review passed. |
| Completed-work fresh eyes | repository subagent, read-only implementation review with portability follow-up, 2026-09-03 | PASS after correction | Three public backpressure tests and shared query/parser behavior were still hidden behind POSIX markers; one status probe used a platform-recognized terminal query. | All reproduced and accepted. Backpressure now uses a public-valid payload and runs as common behavior; parser/state tests are common; only the real POSIX transport query remains platform-specific; the status probe uses a genuinely unknown sequence. Follow-up found no blocker. |
| Completed-work cross-model | GPT-5.5, read-only implementation review with portability follow-up, 2026-09-03 | PASS after correction | Independently identified the same unjustified common-test exclusions and requested proof that the replacement paths remained public and portable. | The corrected tests use public controller/driver routes and directory-wide collection. Follow-up passed with no scoped blocker. |
| Windows attach and writer slices | two independent repository subagents, read-only focused reviews, 2026-09-03 | PASS after correction | Eager output drain could consume the startup prompt before attach; a 64 MiB ConPTY blocking assumption was not contractual; writer validation could misclassify an old-epoch interrupt. | Drain startup is lazy and idempotent; attach publishes its sink before draining; the renderer-size assumption was deleted; real unread Win32 pipes fire active and queued writer interruption/close; validation now gives epoch retirement the required precedence. Both focused follow-ups passed. |

Cross-model findings, preserved verbatim:

- **[P2-1] Make the v2 loader field-drop explicit.** `_state.load_persistence_records` indexes `record["provider_session_id"]` (`_state.py:649`); v2 records omit that key, so it will `KeyError` unless it writes NULL unconditionally. Slice 5.3 doesn't name this edit — add it plus a firing test that a v2 record loads.
- **[P2-2] Split the persistence field-set, don't half-migrate.** `_state.persistence_records` still projects the field (`_state.py:611-621`) and `persistence.py:_FIELDS` (17-25) requires it. State that `dump_records` drops it on the v2 path and validation carries two field sets, with a test asserting a fresh dump lacks the key.
- **[P2-3] Point the CAS at the existing refusal branch.** The `claude-stream`→`claude` compare-and-set must intercept *before* the current "refusing to switch" `DriverError` (`_driver.py:516-524`) for exactly that stored/requested pair, still refusing all other cases. Name `_driver.py:511-546` as the edit site so it isn't a second code path.

Cross-model observations, preserved verbatim and dispositioned as clarifications:

- `_darwin_wait.py` is an existing platform module absent from add/modify/delete lists; state whether it stays or moves with `_process_domain_posix.py`.
- "Persistence component version 2" = manifest `write_version`/`load_versions`, distinct from `component_api_version=1` (untouched); a one-line clarification prevents bumping the wrong field.
- `conftest.py:513` (`os.name=="nt"` STOP branch) and the `interaction.py` Windows read owner are legitimate platform branches, not the module-wide skip/allowlist Invariant 11 forbids.

## Deviation Log

| Spec ref | Planned behavior | Actual behavior | Rationale | Spec proposal |
|---|---|---|---|---|
| [SUM-12] | Put every POSIX primitive in `test_pty_posix.py`. | Process-domain primitives moved; 45 PTY fd/signal/attach cases remain individually marked in `test_pty_adapter.py`. | Those cases share the real scripted-child and adapter harness with common tests. A physical move would duplicate or expose test-only helpers without changing Windows collection. Individual marker selection is exact and the full-directory CI gate proves the required boundary. | Keep the behavioral rule; do not require filename confinement. |

## Execution Log

Slice 1 hosted-Windows evidence was recorded before contract promotion. The
disposable CI probe recorded the branch commit SHA, Actions run and job IDs,
Windows runner/Python identity, its single `TAUT_CONPTY_PROBE` JSON record, and
the exact target test result. No spec promotion or production deletion began
until that record satisfied the native API/ownership ledger and all Slice 1
stop gates.

First hosted attempt: branch commit `19d60c48522c4950c2b1f0b96f1be24e7b8472bf`,
Actions run `33801891208`, job `100803133629`, Windows Python 3.11.9. ConPTY
creation, the deliberate pre-resume rollback, reader startup, and attached
leader/descendant creation succeeded, but the child `READY` lines were copied
to the coordinator's redirected stdout instead of ConPTY; the ConPTY reader
saw only its initialization VT bytes. This is a real redirected-parent spawn
path. The accepted correction is the documented node-pty pattern:
`STARTF_USESTDHANDLES` with all three standard handles null and
`bInheritHandles=False`. Rerun required; no later Slice 1 claim was reached.

Second hosted attempt: branch commit `877a791e442ce8b442fcc287910f32b966be989c`,
Actions run `33802096546`, job `100803801113`, Windows Python 3.11.9. The
standard-handle correction worked: `READY`, the descendant marker, and child
output arrived through ConPTY. The probe then incorrectly expected ANSI input
sequences to survive as literal echoed text; ConPTY correctly interpreted and
removed those terminal controls. The probe now tests exact UTF-8 text echo,
observable SGR output, and Ctrl-C input separately. Rerun required; the failure
does not change the production design.

Third hosted attempt: branch commit `11f823e5f3ae7e493ce8b258e8ea19489c616df4`,
Actions run `33802570688`, job `100805335819`, Windows Python 3.11.9. Exact
UTF-8 text echo passed. The probe expected a contiguous ANSI SGR/reset byte
string, but ConPTY emitted terminal screen-update output with the colored text,
a rendered newline, and a normalized reset (`ESC[m`) as separate updates. The
probe now checks the meaningful invariant after the send offset: colored marker
and later reset are both present, without assuming a terminal renderer's frame
layout. Rerun required; later ownership cases were not reached.

Fourth hosted attempt: branch commit `7ba0015eb84492bf044cc2f337026556bcf6b7c9`,
Actions run `33802771030`, job `100805973787`, Windows Python 3.11.9. ConPTY
again preserved the SGR color prefix and marker, but deferred or elided the
reset frame during the probe's wait. Reset timing is not a Summon contract and
requiring it is renderer-specific armor. The probe now requires only the
post-send SGR-prefixed marker, which proves observable VT output without a
screen-frame timing assumption. Rerun required; later ownership cases were not
reached.

Fifth hosted attempt: branch commit `c23a50a0216b418fd9d75d9e4308185b973e3af1`,
Actions run `33802969328`, job `100806619157`, Windows Python 3.11.9. The
pre-resume rollback, sole-reader attach routing, blocked attach-output
cancellation, generation isolation, UTF-8 echo, and observable VT output all
passed. Writing the documented Ctrl-C input byte did not invoke Python's
`signal.SIGINT` handler in the ConPTY client. That expectation was stronger
than [SUM-7.4], which promises a PTY Ctrl-C, and stronger than Microsoft's own
ConPTY sample, which implements Ctrl-C by writing `"\x3"` to the input pipe.
`GenerateConsoleCtrlEvent` is not added: its documented target is a process
group sharing the caller's console, which is not the Summon host/ConPTY
topology, and targeted `CTRL_C_EVENT` cannot be limited to the requested
group. The probe client now observes the Ctrl-C terminal input sequence as an
interactive raw-input harness would. Provider-specific cancellation remains
the live-harness proof. Rerun required; the failure does not add a production
native API or guard.

The follow-up contract audit also removed two probe-only recovery branches
around the privileged close write. No public caller may invoke that internal
operation before retirement or invoke it twice: the winning public
`request_close()` owns it and later terminal actions must no-op. Those states
are programmer assertions, while the retained public firing proof is repeated
`request_close()` producing exactly one Ctrl-C. The production conformance
test must compose epoch cancellation and the Ctrl-C attempt in the public
`interrupt()` operation; the probe qualifies those native primitives
separately because its forced full-pipe condition requires an out-of-band
release.

Sixth hosted attempt: branch commit `d56f8c9bfdc2a584c0a7bcf56078c818f2e83d0c`,
Actions run `33803682993`, job `100808928115`, Windows Python 3.11.9. Both
reusable Ctrl-C gestures reached the active raw key reader as ETX and the
client survived and accepted later input. During terminal `request_close()`,
the fixture had deliberately paused key reads to fill the ConPTY pipe; that
Ctrl-C was translated into a Windows control signal and Python's default
handler exited the client before the expected marker. This is valid provider
behavior and does not justify a production delivery branch. The fixture now
has one observer for both raw ETX and control-signal delivery so it can survive
the graceful terminal gesture and continue to qualify pseudoconsole/domain
close. The run's separate lint job also found two `RUF012` suppressions that
Ruff 0.16.6 considers unused; they were removed and checked against the CI
version. Rerun required; descendant close and console-lease cases were not
reached.

Seventh hosted attempt: branch commit `e1e1ae6` (full SHA recorded by the
Actions run), Actions run `33804006033`, job `100809997417`, Windows Python
3.11.9. The Windows process selection completed with `6 passed, 17 skipped in
6.28s`; the native ConPTY qualification passed every assertion in the API and
ownership ledger, including pre-resume rollback, sole-reader attach routing,
blocked writer cancellation and epoch rearm/retirement, two raw-ETX reusable
interrupts, one graceful close interrupt, UTF-8 and VT I/O, exact console
mode/code-page restoration, pipe-backed attach classification, reader-close
ordering, and leader plus descendant absence after close. Pytest captured the
coordinator's JSON on success, so the disposable outer test now republishes
that already-validated single record for durable Actions evidence. One
evidence-only rerun is required; no probe behavior or production design
changed.

Eighth hosted attempt: branch commit `0dd031416ab7c4f76e77bcda269b235a4bea4cfe`,
Actions run `33804256714`, Windows process job `100810817917`, Windows Python
3.11.9. The target selection completed with `6 passed, 17 skipped`; its
republished `TAUT_CONPTY_PROBE` record covered the full native API and ownership
ledger. Unrelated jobs failed because the disposable qualification commit
intentionally contained only the probe slice. The probe was then deleted, as
planned, before production integration.

Slices 2 through 7 replaced the structured runtime and provider-session API,
split the portable terminal state from POSIX and Windows mechanics, wired
ConPTY through the public `PtyAdapter`, removed the Job Object and pipe-only
owners, and changed CI from a Windows filename allowlist to full-directory
collection with platform markers. A fresh implementation review found two
reachable Windows defects: natural exit could make the later close gesture
report a broken pipe, and quiet settling returned before an unsupported query
could reach its stall threshold. Clean pipe-end writes are now accepted during
close, pending unknown queries settle through `stall_s`, and public hosted
tests fire both paths. One stream-era `close_stdin` fixture/test was deleted:
keeping the terminal process alive also keeps the pseudoterminal input owner
alive, so its claimed broken-write path was not reproducible through the PTY
API on either platform.

The first full Windows integration runs exposed and corrected two test-design
mistakes rather than adding production branches. An eager ConPTY drain lost
startup bytes before attach; lazy drain ownership fixed the reachable attach
path. A later attempt forced the scripted byte-oriented child to use wide
console character reads solely to preserve one supplementary-plane emoji.
That changed bracketed-paste framing and split real multiline injections into
separate turns. The wide-input specialization and emoji assertion were
deleted. The fixture again reads the PTY byte stream used by the production
adapter, retains UTF-8/BMP coverage, and leaves a real harness free to select
its own Windows console API. This is the accepted anti-over-armor disposition.

Final hosted verification: branch commit
`1c5f4c83cf0945a1f7a557b0271c78c50ae7ec9b`, Actions run
`33831244048`, 2026-09-04, completed successfully across every job. The
Windows Summon process job `100894509870` ran the complete process selection
with `214 passed`. Windows root/unit jobs passed on Python 3.11, 3.12, 3.13,
and 3.14 (`100894510068`, `100894510006`, `100894510034`, and
`100894509944`). Lint job `100894509901` and packaging job `100894509852`
also passed. Collection contains 517 common tests, 72 POSIX primitive tests,
and 12 Windows primitive tests; the workflow selects the whole Summon test
directory and filters only by those semantic markers.

Final local verification ran the complete non-Windows Summon selection with no
failures. Four expected skips remained: one unavailable local Ollama model,
two direct Darwin fallback cases, and one Linux zombie process-group
regression. Ruff, formatting, production mypy, documentation/CLI claim gates,
workflow architecture tests, wheel build and contents, persistence manifest
v1/v2 compatibility, and the relevant core/TUI tests also passed during the
recorded slices. PyYAML was already available through the development
environment and no new direct dependency was necessary.

## Out of Scope

- A generic structured-event adapter or mapping language.
- Provider-profile configuration in `.taut.toml`.
- Provider-specific prompt regexes, idle menus, or exit chords without a
  current failing provider path.
- Parsed screen replies or automatic routing of model output.
- Provider conversation-session persistence or resume.
- A general Win32 or terminal library beyond the exact ConPTY and host-console
  functions qualified in Slice 1.
- Process containment as a security sandbox or reclamation of processes that
  deliberately escape the terminal domain.
- Installing/authenticating live agent CLIs in CI solely for this refactor.
- Rewriting historical completed plans or released changelog entries.

## Fresh-Eyes Checklist

- [x] Every named path, flag, symbol, marker, workflow step, and spec anchor
  exists at the recorded baseline.
- [x] The deletion ledger covers imports, public exports, tests, docs,
  persistence, build artifacts, and Windows helpers.
- [x] Each guard-register cause is constructible through the named current CLI
  or API path; unreachable guards were removed.
- [x] No common test gained a platform skip and the CI plan has no filename
  allowlist.
- [x] The scripted seam uses the production PTY adapter and real subprocess.
- [x] Windows proof observes an attached descendant, not only the leader.
- [x] Native `ClosePseudoConsole` and host-console cancellation/restoration are
  qualified before the spec or deletion slices proceed.
- [x] The physical schema decision avoids an unnecessary destructive migration
  while preserving a real old-dump path.
- [x] Failure priority, rollback, stop gates, and native-boundary limits are clear.
- [x] Proposed spec text deletes the second protocol before code depends on the
  new contract.
