# Summon Rich-Host Global-State Isolation Plan

Date: 2026-08-01

Class: 5. The change revises the normative [SUM-13] public embedding contract,
changes the public `SummonController.run_foreground` signature and default
signal policy, and crosses process-global environment, signal, thread, CLI,
and cleanup boundaries.

Plan type: implementation with spec revision.

Hardening: required. The same foreground driver runs behind short-lived CLI
adapters and inside long-lived hosts, and the correction changes a public
compatibility surface plus process-global cleanup ownership.

## Goal

Make `SummonController.run_foreground()` safe for a long-lived in-process host:
Summon-owned clients must ignore ambient `TAUT_AS` and `TAUT_TOKEN` without
mutating `os.environ`, and the public controller must preserve host signal
dispositions unless the caller explicitly grants temporary signal ownership.
Keep standalone and installed CLI SIGINT/SIGTERM shutdown behavior unchanged.

## Requested Outcomes

- A foreground controller run never adds, removes, or rewrites the host's
  `TAUT_AS` or `TAUT_TOKEN`, including while the run is active and on every
  success or failure path.
- Every `TautClient` owned by the driver or its control loop uses explicit
  identity inputs only and sets `inherit_environment_identity=False`.
- The harness child still receives the summoned member's explicit
  `TAUT_TOKEN` and backend projection. Each adapter removes inherited
  `TAUT_AS` and `TAUT_TOKEN` from its copied child environment before applying
  the explicit driver overlay, so host ambient identity never replaces or
  combines with that child identity.
- `SummonController.run_foreground(..., *, install_signal_handlers=False)` is
  safe by default: it does not inspect or replace `SIGINT` or `SIGTERM`.
- The installed `taut summon` and standalone `taut-summon run` adapters opt in
  to driver signal handling explicitly, preserving their current graceful
  stop behavior.
- An opted-in main-thread run restores the exact prior callable, `SIG_DFL`, or
  `SIG_IGN` disposition for each successfully installed signal on clean return
  and on every exception path.
- Opt-in from a non-main thread fails before the driver lifecycle starts with
  a typed `SummonOperationError`; it does not silently skip the requested
  policy or change process state.
- The public-boundary regression tests use real `os.environ` and real signal
  APIs. The real rich-host integration keeps SQLite, the controller, driver,
  provider process, control loop, and concurrent host identity behavior real.
- [SUM-6], [SUM-13], both Summon implementation notes, tests, and code retain
  a closed traceability chain.

## Source Documents

Source specs:

- `docs/specs/04-summon.md` [SUM-13], public controller, blocking foreground
  lifecycle, rich-host composition, and host interaction ownership.
- `docs/specs/04-summon.md` [SUM-3], provider/name resolution that must not be
  changed while identity isolation is corrected.
- `docs/specs/04-summon.md` [SUM-6], explicit child `TAUT_TOKEN` propagation.
- `docs/specs/04-summon.md` [SUM-9], driver SIGINT/STOP cleanup and release
  behavior that the CLI must retain.
- `docs/specs/02-taut-core.md` [TAUT-8.3], the existing
  `inherit_environment_identity=False` contract for long-lived embedders.
- `docs/specs/01-development-documentation-operating-model.md` [DOM-5],
  [DOM-6], [DOM-10], [DOM-11], and [DOM-15].

Implementation and historical context:

- `docs/implementation/05-taut-summon-architecture.md`, driver/control
  ownership, child environment, CLI logging boundary, and [SUM-13] mapping.
- `docs/implementation/06-command-extensions.md`, command adapter versus
  domain interface and rich-TUI composition boundary.
- `docs/plans/2026-07-12-lazy-command-extensions-and-rich-tui-composition-plan.md`,
  the design that introduced the public controller and called it the real
  future-rich-host seam.
- `docs/plans/2026-07-28-summon-terminal-retirement-plan.md`, current
  driver-signal and foreground-finalization ownership.
- `docs/agent-context/runbooks/writing-plans.md`.
- `docs/agent-context/runbooks/hardening-plans.md`.
- `docs/agent-context/runbooks/writing-specs.md`.
- `docs/agent-context/runbooks/testing-patterns.md`.
- `docs/agent-context/runbooks/maintaining-traceability.md`.

Investigation evidence:

- A process-isolated public-controller probe returned cleanly with both host
  identity variables absent and both handlers still bound to the completed
  driver. The same result reproduced three times.
- `uv run --extra dev pytest extensions/taut_summon/tests/test_interaction.py
  -n 0 -q` passed all 14 tests despite the defect.
- The gap exists because the shared driver helper disables signal installation,
  the public rich-host test runs in a worker thread where signal installation
  returns early, and the extension autouse fixture clears ambient Taut identity.

## Spec Baseline

- Baseline commit: `40a1306c8716af8befb04dea2bdaf4e138080aa0`.
- Governing specs at baseline: `docs/specs/04-summon.md` [SUM-13] and
  `docs/specs/02-taut-core.md` [TAUT-8.3].
- Plan type: implementation with spec revision.
- `docs/specs/02-taut-core.md` is cited but not revised: [TAUT-8.3] already
  defines the object-local identity seam required here.
- Promotion baseline: committed baseline `40a1306c8716af8befb04dea2bdaf4e138080aa0`
  plus the 2026-08-04 worktree diff to `docs/specs/04-summon.md`. That diff
  promotes the reviewed [SUM-6]/[SUM-13] text and Related Plans backlink before
  dependent tests or code cite the revised contract.

## Current Structure and Key Files

### Public controller and CLI ownership

- `extensions/taut_summon/taut_summon/controller.py::SummonController.run_foreground`
  exposes exactly `(request, interaction)`, then delegates to private
  `run_driver()` without a signal-policy distinction.
- `extensions/taut_summon/taut_summon/_driver.py::run_driver` always constructs
  `SummonDriver` with its default `install_signal_handlers=True`.
- `extensions/taut_summon/taut_summon/commands/summon.py::SummonCommand.run`
  is the shared native command adapter used by installed root dispatch and the
  standalone console factory. It is the one place that should opt into CLI
  signal ownership; do not make either console import `_driver.py` directly.
- `extensions/taut_summon/tests/test_interaction.py` owns the public controller
  and real rich-host PTY seam. Its current worker-thread helper is load-bearing
  for host concurrency but makes signal installation a silent no-op.
- `extensions/taut_summon/tests/test_summon_cli.py` owns command-adapter policy
  and real native/standalone parity.

### Environment identity ownership

- `extensions/taut_summon/taut_summon/_driver.py::SummonDriver.run` currently
  removes `TAUT_AS` and `TAUT_TOKEN` before its `try` block. That process-global
  mutation protects driver clients from ambient selectors but cannot be made
  safe for concurrent host work by restoring values later.
- `taut/client/_base.py::TautClient.__init__` already provides the correct
  object-local seam: `inherit_environment_identity=False` ignores both
  ambient identity selectors while preserving explicit `as_name=` and
  `token=` arguments.
- Driver-owned client constructors currently live at these boundaries and
  must all be audited rather than assuming the first client is representative:
  `_driver.py::_persistent_client`, new-member creation, re-summon persona,
  generation setup, event-pump mouth, rejoin, and watcher ownership; plus
  `_control.py::ControlLoop._make_broker_handles` and its reopen path.
- `extensions/taut_summon/taut_summon/_driver.py::_harness_environment` builds
  a new child environment carrying the
  minted continuity token. This explicit child projection must remain; the fix
  concerns the host process environment, driver client selection, and the
  adapter merge that turns the explicit projection into a provider child
  environment.
- `extensions/taut_summon/taut_summon/_scripted.py::ScriptedAdapter.spawn`
  and `_claude.py::ClaudeAdapter.spawn`, plus `_pty.py::PtyAdapter.spawn`,
  currently
  copy all of `os.environ` and then overlay `_harness_environment`. Once the
  driver stops deleting host identity, those copies would inherit `TAUT_AS`
  beside the minted `TAUT_TOKEN` unless all three shipped adapter owners
  explicitly neutralize inherited identity first.

### Signal ownership and cleanup

- `SummonDriver._install_signals` currently installs `self._on_signal` for
  `SIGINT` and `SIGTERM` only on the main thread. It records no previous
  disposition, silently ignores install errors, and has no paired release.
- `SummonDriver.run` installs signals before the `try` that wraps `_run`, so
  neither normal error translation nor `_run` cleanup can restore host state.
- `taut/watcher.py::TautWatcher.run_forever` is the local restoration pattern:
  it snapshots a prior handler on the main thread and restores it in `finally`.
  Reuse the ownership shape, not the watcher API.
- Signal dispositions are process-global, while Python permits
  `signal.signal()` only on the main thread. The public default must therefore
  avoid signal ownership. Explicit opt-in is an execution-context contract,
  not something inferred from `SummonInteraction` type or terminal availability.

## Required Reading and Comprehension Gates

Before editing, read the current versions of:

1. `docs/specs/04-summon.md` [SUM-3], [SUM-6], [SUM-9], and [SUM-13], plus
   `docs/specs/02-taut-core.md` [TAUT-8.3].
2. `controller.py`, `_driver.py` from public entry through every `TautClient`
   construction and signal helper, `_control.py::ControlLoop`, and
   `commands/summon.py::SummonCommand.run`.
3. `test_interaction.py`, the constructor/helper area and real process-signal
   cases in `test_driver.py`, `test_control.py` reopen coverage, and
   `test_summon_cli.py` native/standalone lifecycle cases.
4. `docs/implementation/05-taut-summon-architecture.md` and
   `docs/implementation/06-command-extensions.md` at their rich-host sections.

Comprehension questions:

1. Why is saving and restoring `TAUT_AS`/`TAUT_TOKEN` insufficient? Because
   other host threads observe the deletion during the blocking run, and an
   unconditional restore can overwrite a legitimate concurrent host update.
2. Why must every driver/control `TautClient` opt out of ambient identity even
   when it passes an explicit token? `TautClient` resolves the two selector
   fields independently; an ambient `TAUT_AS` can combine with an explicit
   token and change precedence or violate exactly-one-selector assumptions.
3. Why must the child-launch merge also change? Adapter `spawn()` starts from a
   copy of the host environment, while the driver overlay contains a token but
   no `TAUT_AS` deletion marker. Object-local client policy cannot affect the
   provider subprocess.
4. Which layer may opt into signal ownership? The command adapter, through the
   public controller keyword. The controller default and rich-host calls do
   not infer permission from being on the main thread or using a shell-shaped
   interaction.
5. Why must signal installation and restoration surround the entire driver
   `try`? Installation can partially succeed, and `_run` can return cleanly or
   raise through several translated and untranslated paths; every acquired
   process-global disposition needs a paired release.
6. Why is a source-only constructor check not enough? It prevents a missed
   keyword but does not prove the public host environment remains visible
   during a real controller/provider/control lifecycle.

## Decisions, Rejected Alternatives, and Open Questions

Decisions:

- Use `inherit_environment_identity=False` at each Summon driver/control client
  construction. Do not add another identity-resolution algorithm.
- At each shipped adapter's child-launch boundary, copy the host environment,
  delete inherited `TAUT_AS` and `TAUT_TOKEN` from that copy, then apply the
  explicit driver overlay. Do not mutate the host mapping and do not change
  unrelated inherited variables or the existing conditional `TAUT_DB` policy.
- Add one keyword-only public policy:
  `install_signal_handlers: bool = False`. The safe embedding behavior is the
  default; command adapters opt in with `True`.
- Treat non-main-thread opt-in as a typed pre-lifecycle error. Silent fallback
  would make an explicit safety request untrue.
- Preserve exact prior signal values and restore only signals whose
  installation succeeded. A partial installation failure restores earlier
  acquisitions before surfacing the typed failure.
- Preserve the existing primary-error priority if restoration itself fails
  during an already-failing lifecycle: emit a precise package log for the
  secondary restoration failure and propagate the primary. A restoration
  failure after an otherwise clean run is a `SummonOperationError`.

Rejected alternatives:

- Snapshot and restore the host identity environment: rejected because it is
  unsafe during the run and can clobber concurrent changes.
- Infer signal ownership from `ShellSummonInteraction`: rejected because
  terminal I/O policy and process-signal authority are distinct contracts.
- Disable driver signal handling everywhere: rejected because native CLI
  SIGINT/SIGTERM cleanup is a shipped [SUM-9] behavior.
- Move signal handling into the CLI by having it call private driver state or
  guess the final summoned name: rejected because it breaks the public
  controller boundary and cannot safely reach the active driver.
- Add a child supervisor, daemon, background controller, or new cancellation
  handle: rejected as unrelated process-model work already reserved for a
  future TUI specification.

Open questions: none at plan review. Reopen the design only under the explicit
stop conditions below.

## Proposed Spec Delta

Promotion strategy: **A, in-file edit with text before implementation-link
claims**. In the spec-promotion slice, update [SUM-6] and [SUM-13] and add this
plan under `## Related Plans`. Do not update implementation mapping prose until
code, tests, and implementation notes land together. The active
`docs/specs/04-summon.md` file remains active; do not reclassify it.

### [SUM-6] Child identity environment

Replace the first bullet under `## 6. Mouth — the CLI Contract [SUM-6]` with:

> - The adapter constructs the provider child environment from a copy of the
>   host environment, removes inherited `TAUT_AS` and `TAUT_TOKEN` from that
>   copy, then applies the driver's explicit child overlay. The resulting
>   child carries exactly the summoned member's `TAUT_TOKEN` (continuity,
>   **not** authentication, per [TAUT-5]/[TAUT-9]: it selects the member within
>   the storage trust boundary and proves nothing) and, when the backend is
>   path-addressed, `TAUT_DB`. The adapter does not mutate the host environment
>   or change unrelated inherited variables. The agent speaks with ordinary
>   CLI calls; replies route wherever the agent says (`taut say dev ...`,
>   `taut reply`, `taut say @van ...`).

### [SUM-13] Public controller signature

Replace the sentence beginning `` `run_foreground(request, interaction)`
remains blocking`` with:

> `run_foreground(request, interaction, *, install_signal_handlers=False)`
> remains blocking and owns exactly one foreground driver lifecycle; it never
> silently daemonizes or detaches. The default is the rich-host boundary: it
> does not inspect, install, or replace process signal handlers. Command
> adapters that own a short-lived foreground process pass
> `install_signal_handlers=True` explicitly. Opt-in is valid only on the
> Python main thread; an invalid opt-in fails before the driver lifecycle
> starts with `SummonOperationError`.

Insert after that replacement paragraph:

> A controller foreground run never mutates the host process's `TAUT_AS` or
> `TAUT_TOKEN`. Every driver-owned and control-loop-owned core client disables
> ambient identity inheritance and uses only its explicit name, token, or
> capture inputs ([TAUT-8.3]); the provider child receives only the summoned
> member's explicit identity overlay after adapter-side removal of inherited
> host identity as required by [SUM-6]. This non-mutation
> invariant applies while the run is active and after every success or failure,
> so concurrent host work retains its own process environment.
>
> When signal handling is explicitly enabled, Summon temporarily installs its
> driver handler for `SIGINT` and `SIGTERM` and restores the exact prior
> disposition for each successfully installed signal on every exit. Partial
> installation rolls back earlier installations before the lifecycle begins.
> The temporary opt-in does not grant ownership of unrelated signals, logging,
> terminal policy, or host environment.

### [SUM-13] Public method inventory

Replace the phrase `a blocking foreground run that returns no value on clean
completion` with:

> a blocking foreground run with keyword-only
> `install_signal_handlers: bool = False` that returns no value on clean
> completion

### [SUM-13] Verification requirement

Insert before `## Implementation Mapping`:

> [SUM-13] verification crosses the public controller boundary with real
> process environment and signal APIs. It proves environment non-mutation
> during and after a real rich-host lifecycle; default signal non-ownership;
> exact opt-in restoration on clean and failing exits; invalid worker-thread
> opt-in; exact child `TAUT_TOKEN` with absent child `TAUT_AS` through all three
> shipped adapter families; and unchanged CLI SIGINT/STOP release. Tests that
> clear ambient
> identity, disable signal installation, or run only off the main thread do
> not satisfy this boundary by themselves.

### Related Plans backlink

Add under `docs/specs/04-summon.md` `## Related Plans`:

> - `docs/plans/2026-08-01-summon-rich-host-global-state-plan.md` — makes
>   driver identity object-local, prevents inherited host identity in provider
>   children, and separates safe rich-host signal defaults from explicit
>   temporary CLI signal ownership.

## Invariants and Constraints

1. **No host environment write:** Summon code must not call `pop`, assignment,
   `setdefault`, or deletion on `TAUT_AS` or `TAUT_TOKEN`. The invariant holds
   throughout the active run, not only at return.
2. **One identity algorithm:** reuse core [TAUT-8.3]. Do not add a Summon-local
   environment parser, save/restore context, fallback selector, or compatibility
   shim.
3. **Complete identity-boundary coverage:** bootstrap, creator, re-summon, setup,
   mouth, rejoin, watcher, control-loop initial open, and control-loop reopen
   all ignore ambient identity. All three shipped adapters remove inherited identity
   from their copied child environments before overlaying the explicit minted
   token; unrelated child inheritance and conditional `TAUT_DB` behavior stay
   unchanged.
4. **Safe public default:** a caller that omits the new keyword grants no
   signal authority, even on the main thread.
5. **CLI parity:** both installed and standalone foreground commands opt in to
   the same controller path. SIGINT/SIGTERM still request graceful driver stop,
   and ledger/control/provider cleanup ordering remains [SUM-9]-compliant.
6. **Exact scoped release:** opt-in changes only `SIGINT` and `SIGTERM`, records
   exact prior values before replacement, and releases every successful
   acquisition once. No completed driver remains reachable through a handler.
7. **No silent opt-in degradation:** a worker-thread `True` or failed install
   does not proceed as though signal support existed. Partial acquisition rolls
   back before any provider, watcher, control thread, or database lifecycle
   begins.
8. **Primary error priority:** existing driver, adapter, broker, terminal, and
   `BaseException` cleanup semantics remain authoritative. Secondary restoration
   failure is visible but does not hide an active primary failure.
9. **No second driver path:** `SummonController -> run_driver -> SummonDriver`
   remains the only foreground lifecycle. The boolean is threaded through that
   path; CLI code does not import or reconstruct private driver behavior.
10. **No unrelated contract drift:** request fields, provider selection,
    session rows, control protocol, PTY lease, shutdown ordering, logging,
    output, exit codes, storage, and supported OS/Python versions do not change.
11. **No new dependency or module split:** use `signal`, existing core client
    policy, and current owners. File size is not a reason to extract a helper.
12. **Documentation-first promotion:** implementation does not cite the new
    [SUM-13] behavior until the reviewed delta is promoted and its baseline is
    recorded.

## Hidden Couplings and Failure Priorities

- `os.environ` is a live process-wide mapping. A worker-thread rich-host test
  is the strongest environment concurrency seam, not merely a reason signal
  installation is skipped.
- Core resolves `as_name` and `token` fallbacks independently. Explicit token
  construction alone is not proof against an ambient `TAUT_AS`; every owned
  client needs the false inheritance policy.
- `ControlLoop` reopens its broker handles after faults. Correcting only the
  initial driver client leaves a delayed ambient-identity regression on reopen.
- All three adapters clone `os.environ` at spawn. Correcting only in-process clients
  moves the selector collision into the provider child; the child merge must
  prove exact token presence and `TAUT_AS` absence for scripted, claude-stream,
  and PTY paths.
- Signal handlers hold a bound method and therefore a strong reference to the
  driver. Exact restoration is also a stale-object lifetime requirement.
- CLI and rich hosts share one controller. The new keyword must reach every
  command factory without making the controller infer caller type.
- Signal installation happens before `_run`; partial install rollback and
  cleanup must be established before moving this boundary under a `try`.
- Fatal before lifecycle: invalid execution context for explicit signal opt-in,
  or inability to install the requested handler after rolling back partial
  acquisition.
- Fatal after otherwise clean lifecycle: inability to restore an acquired
  signal disposition.
- Secondary during an existing failure: restoration failure is logged with
  signal identity and prior disposition while the original exception remains
  primary, following the existing terminal-lease cleanup precedence.
- Best effort remains unchanged only where the existing driver contract already
  says so; environment isolation and signal release are not best-effort policy.

## Rollout, Rollback, and One-Way Doors

- Rollout is one coordinated code/spec/test change. There is no schema,
  migration, state conversion, protocol version, or mixed-service ordering.
- CLI behavior stays compatible because the command adapter explicitly passes
  `True`. The intentional public change is that direct controller callers no
  longer receive implicit signal takeover; callers that genuinely want it can
  opt in on the main thread.
- Land the [SUM-6]/[SUM-13] promotion before dependent code in the same development
  sequence. Do not land a code-only fix that leaves the advertised boundary
  ambiguous.
- Roll back by reverting the complete implementation/spec/docs/test change.
  No persisted data needs repair. Do not restore only the old environment pops
  as a partial rollback; that recreates the concurrent-host defect.
- There is no one-way door. The higher bar comes from process-global state and
  public compatibility, not irreversibility.
- Post-release observation: native CLI SIGINT/STOP lanes remain green across
  supported OS/Python CI; an embedding smoke probe can run the controller twice
  in one process and observe unchanged identity and handlers after both runs;
  no report should show a completed `SummonDriver._on_signal` still installed.
- If the repository has no active Unreleased changelog section at execution
  time, do not rewrite a published release entry. Record the behavior in the
  implementation docs and leave release-note/version work to release planning.

## Tasks

1. **Spec-promotion slice: promote the reviewed [SUM-6]/[SUM-13] contract.**
   - Files to touch: `docs/specs/04-summon.md` and this plan's promotion
     baseline line.
   - Apply the exact Proposed Spec Delta with strategy A and add the Related
     Plans backlink. Do not add implementation-link claims yet.
   - Record the promotion baseline as a commit SHA or baseline
     `40a1306c...` plus the exact spec worktree diff.
   - Verify stable references and documentation paths before code begins.
   - Stop if review changes the public keyword, default, environment
     non-mutation rule, or error semantics; revise the delta and review the
     changed text before promotion.
   - Done signal: the spec tree is the single governing contract, the plan
     backlink resolves, and docs reference gates pass.

2. **Write public-boundary RED tests before implementation.**
   - Files to touch: `extensions/taut_summon/tests/test_interaction.py`,
     `extensions/taut_summon/tests/test_summon_cli.py`, and only if a focused
     lifecycle helper belongs there, `extensions/taut_summon/tests/test_driver.py`.
   - Add a fast main-thread controller probe that substitutes only `_run` with
     a finite clean/failing body while keeping the public controller,
     `run_driver`, `SummonDriver.run`, real `os.environ`, and real
     `signal.getsignal/signal.signal` path.
   - RED cases: current default mutates both environment keys and replaces both
     handlers; the new public keyword is absent; a clean opted-in return and a
     typed failure fail to restore callable/`SIG_DFL`/`SIG_IGN`; worker-thread
     opt-in silently continues; command adapter calls omit explicit opt-in; and
     direct real subprocess launches through all three adapters inherit host
     `TAUT_AS` beside the supplied token. These adapter REDs call each real
     `spawn()` boundary directly; they do not suppress driver behavior or mock
     the child environment.
   - Ensure every test restores its own process signals in an outer test
     `finally`, even while production is red, so pytest is never poisoned.
   - Do not fake `os.environ`, `signal.getsignal`, or successful main-thread
     `signal.signal`. Narrow fault injection is allowed only for partial
     install/restore failures after the real success cases exist.
   - Capture the exact failing assertions in the execution log.
   - Stop if a red can pass while a stale driver handler remains installed or
     if a test depends on order with another test.
   - Done signal: deterministic, seconds-fast REDs fail on the exact reported
     post-return and active-host symptoms.

3. **Replace process-global identity mutation with object-local client and child policy.**
   - Files to touch: `extensions/taut_summon/taut_summon/_driver.py`,
     `extensions/taut_summon/taut_summon/_control.py`,
     `extensions/taut_summon/taut_summon/_scripted.py`,
     `extensions/taut_summon/taut_summon/_claude.py`,
     `extensions/taut_summon/taut_summon/_pty.py`,
     `extensions/taut_summon/taut_summon/scripted_provider.py`,
     `extensions/taut_summon/tests/fixtures/fake_tui.py`,
     `extensions/taut_summon/tests/test_claude_adapter.py`, and the focused
     driver/scripted/PTY/interaction tests.
   - Remove the two host-environment `pop` calls. Do not replace them with a
     context manager or restoration helper.
   - Pass `inherit_environment_identity=False` to every driver/control-loop
     `TautClient`, including delayed control reopen and all explicit-token
     constructors. Preserve explicit `as_name`, `token`, capture, persistence,
     db/backend, and close ownership exactly.
   - Add an enumerable architecture assertion over production
     `TautClient(...)` calls in `_driver.py` and `ControlLoop` that reports each
     missing false keyword by file and line. Keep this as supporting
     completeness evidence, not the primary runtime proof.
   - In all three shipped adapter `spawn()` implementations, remove `TAUT_AS` and
     `TAUT_TOKEN` from the local copied child mapping before
     `child_env.update(env)`. Do not delete from `os.environ`, change other
     inherited variables, or special-case one provider family.
   - Extend the shipped scripted-provider and fake-PTY child ledgers so their
     start records expose child `TAUT_AS` and `TAUT_TOKEN`. For
     `ClaudeAdapter.spawn`, point `_CLAUDE_BIN` at a temporary executable wrapper
     that `exec`s the shipped scripted provider without forwarding Claude flags;
     this crosses the real adapter `Popen` and stream handle without requiring
     an external Claude account. Assert the exact minted token and absent
     `TAUT_AS` in every real child; a mocked `Popen(env=...)` assertion alone is
     insufficient.
   - Verify bootstrap, resummon/persona, event pump, watcher, rejoin, control
     initial-open, and reopen tests. Add a targeted reopen assertion if the
     existing fault test does not fire the identity policy.
   - Stop if any client genuinely needs ambient identity. That contradicts
     [SUM-13] and requires a named deviation/spec proposal rather than a local
     exception.
   - Done signal: source enumeration is complete, targeted client lifecycle
     tests pass, no production Summon code writes either host identity key, and
     all three real adapter children receive exact token-only identity.

4. **Separate safe controller defaults from explicit CLI signal ownership.**
   - Files to touch: `controller.py`, `_driver.py`, `commands/summon.py`,
     `test_interaction.py`, `test_driver.py`, and `test_summon_cli.py`.
   - Add keyword-only `install_signal_handlers: bool = False` to
     `SummonController.run_foreground` and thread it through `run_driver` to
     `SummonDriver` without adding another entry point.
   - Make `SummonCommand.run` pass `True`; verify both installed and standalone
     factories reach that same adapter.
   - Default false must bypass signal reads and writes entirely.
   - For true: validate the main-thread precondition before `_run`; snapshot
     exact prior dispositions; install in a deterministic order; on partial
     failure restore successful acquisitions before raising; and restore in
     `finally` on every clean, translated-error, ordinary exception, and
     `BaseException` exit.
   - Use the current `SummonOperationError` public hierarchy. Do not expose
     private driver exceptions or add a new public error class.
   - Preserve primary-error precedence as specified above and make restoration
     failure diagnostics signal-specific.
   - Stop if CLI opt-in requires private-driver imports, or if the keyword
     becomes positional or is inferred from interaction type.
   - Done signal: every Task 2 RED is green; a completed driver is not retained
     by `SIGINT`/`SIGTERM`; public signature/type checks and CLI parity pass.

5. **Prove the real concurrent rich-host and CLI boundaries.**
   - Files to touch: primarily `test_interaction.py` and
     `test_claude_adapter.py`; extend existing real process/controller helpers
     rather than adding a second driver harness.
   - In a real worker-thread controller lifecycle with SQLite and the shipped
     deterministic provider, create a valid host identity, set both ambient
     selectors to that same identity, and prove while the summoned provider is
     active that: the exact environment strings remain present; an ordinary
     host `TautClient` still resolves the host identity; the summoned member is
     distinct and controlled by its minted token; and stop/release completes.
   - Inspect the real scripted child start record and require its minted
     `TAUT_TOKEN` plus `TAUT_AS is None`. Exercise `ClaudeAdapter.spawn` through
     the temporary real-child wrapper described in Task 3, and the existing real
     PTY/fake-TUI lifecycle, under the same ambient host identity. Require the
     same child assertions so all three enumerable shipped adapter families fire.
   - After return, prove exact environment preservation and no leaked driver
     resources. The test must fail if production merely restores at return.
   - Keep existing real direct-driver SIGINT and correlated STOP tests as the
     CLI signal-effect proof; add or tighten a native command assertion that
     the adapter opts in rather than relying only on a mock call count.
   - Do not mock SQLite, controller, provider process, control loop, client
     identity resolution, child environment, or stop/release evidence.
   - Stop if the proof needs arbitrary sleeps; use provider readiness, control
     status, or existing bounded events.
   - Done signal: the real concurrent host proof and native/standalone process
     lanes pass deterministically.

6. **Reconcile durable documentation and traceability.**
   - Files to touch: `docs/implementation/05-taut-summon-architecture.md`,
     `docs/implementation/06-command-extensions.md`,
     `docs/specs/04-summon.md` implementation mapping if needed, this plan,
     and `docs/plans/README.md` at closure.
   - Explain why environment restoration was rejected, how [TAUT-8.3] is reused,
     why adapter child copies neutralize inherited identity, which layer owns
     signal opt-in, and the exact default/CLI distinction.
   - Add reciprocal plan/spec/implementation/code-test mapping without
     narrating transient worktree state.
   - Update the repository map only if ownership or files move; this plan
     expects neither. Do not add a durable lesson unless implementation reveals
     a reusable correction beyond existing Golden Rules 5-7.
   - Evaluate whether `skills/brainstorming-to-plan` or the planning runbooks
     missed a reusable boundary step; record no change when they did not.
   - Stop if documentation begins specifying a future TUI process model or a
     new cancellation API.
   - Done signal: the traceability chain closes and documentation gates pass.

7. **Run slice review, final verification, and completed-work review.**
   - After Tasks 3-5 form a coherent implementation slice, run a read-only
     independent review against the promoted [SUM-6]/[SUM-13], plan, code, and
     focused evidence. Reproduce every claimed defect before changing code.
   - Run the targeted, full extension, root integration, formatting, typing,
     docs, plan-index, and diff gates below.
   - Run a final different-agent-family completed-work review when available.
   - Update the execution, revision, deviation, and review-disposition tables
     with durable evidence. Do not claim ready-to-land unless the user requests
     landing and `git log` verifies the resulting commit.
   - Stop on any unexplained signal mutation, environment write, identity
     crossover, resource leak, CLI regression, warning/error in required docs
     gates, or unclosed review finding.
   - Done signal: all local gates and independent reviews pass with residual
     platform/external evidence stated precisely.

## Testing Plan

### RED/GREEN contract matrix

| Contract | RED on baseline | GREEN requirement |
|----------|-----------------|-------------------|
| Host identity after return | Public finite controller call observes both keys absent | Exact present values remain; initially absent keys remain absent |
| Host identity during run | Real worker-thread lifecycle observes missing keys/host identity | Exact values and ordinary host identity remain usable while provider/control loop run |
| Driver identity isolation | Conflicting ambient selector can enter driver-owned clients unless globally popped | Every owned constructor ignores ambient selectors; source enumeration and real lifecycle agree |
| Provider-child identity | Removing global pops makes all three adapters copy host `TAUT_AS` beside the minted token | Real scripted, claude-stream, and PTY children record exact minted `TAUT_TOKEN` and absent `TAUT_AS` |
| Default signal policy | Main-thread controller replaces SIGINT/SIGTERM | Default call performs no signal read/write and preserves exact dispositions |
| Opt-in clean release | Completed driver remains installed | Callable, `SIG_DFL`, and `SIG_IGN` values restore exactly; no stale driver reference |
| Opt-in failure release | `_run` error leaves driver installed | Translated error and `BaseException` paths restore exact dispositions |
| Partial install | First successful replacement can survive second failure | Earlier acquisition rolls back; no lifecycle begins; typed error surfaces |
| Worker opt-in | True silently skips installation | Typed pre-lifecycle error; environment/signals/resources unchanged |
| CLI behavior | New safe default would remove CLI signal handling without adapter change | Native and standalone adapters explicitly opt in; real SIGINT/STOP cleanup remains green |

### Anti-mocking posture

- Real: public `SummonController`, `run_driver`, `SummonDriver.run`, process
  environment, main-thread signal APIs, SQLite/SimpleBroker, provider child,
  all three adapter child-environment merges, control loop/reopen, identity
  resolution, and stop/release evidence.
- Allowed narrow substitution: replace only `_run` with a finite clean or
  failing body for seconds-fast process-global acquisition/release tests; inject
  one `signal.signal` failure only after real handler preservation tests exist.
- Supporting only: constructor/source enumeration and command call argument
  assertions. They cannot replace the real active-host or OS-signal proofs.
- Forbidden as primary proof: fake environment mappings, fake signal registry,
  fake controller, fake broker, mock-only provider, sleeps, or assertions that
  only inspect `install_signal_handlers` without observing behavior.

### Failure and edge coverage

- Environment values present, absent, and changed only by the host before call.
- Callable, `SIG_DFL`, and `SIG_IGN` prior dispositions.
- Clean return, typed driver error, ordinary exception, and `KeyboardInterrupt`
  or equivalent `BaseException` cleanup.
- First install failure and second install failure after one acquisition.
- Restoration failure with no primary and with an active primary.
- Main-thread default false and worker-thread explicit true.
- Control-loop handle reopen under conflicting ambient selectors.
- Scripted and PTY child launch under conflicting ambient host selectors.
- Two sequential foreground controller calls in one process.

## Verification and Gates

Per-task focused commands:

```bash
uv run --extra dev pytest extensions/taut_summon/tests/test_interaction.py -n 0 -q
uv run --extra dev pytest extensions/taut_summon/tests/test_driver.py -n 0 -q
uv run --extra dev pytest extensions/taut_summon/tests/test_control.py -n 0 -q
uv run --extra dev pytest extensions/taut_summon/tests/test_summon_cli.py -n 0 -q
```

Final behavior gates:

```bash
uv run --extra dev pytest extensions/taut_summon/tests -n 0 -q
uv run --extra dev pytest extensions/taut_summon/tests -n 2 -q
uv run --extra dev pytest tests/test_architecture_boundaries.py tests/test_command_registry.py -n 0 -q
```

Static, typing, documentation, and plan gates:

```bash
uv run ruff format --check extensions/taut_summon/taut_summon extensions/taut_summon/tests
uv run ruff check extensions/taut_summon/taut_summon extensions/taut_summon/tests
uv run mypy extensions/taut_summon/taut_summon extensions/taut_summon/tests
uv run pytest tests/test_docs_references.py -n 0 -q
bin/check-plan-status-index
bin/check-dom15-fixtures
git diff --check
```

Required static inspection:

```bash
rg -n 'TAUT_AS|TAUT_TOKEN|TautClient\(|signal\.signal|signal\.getsignal|install_signal_handlers' extensions/taut_summon/taut_summon extensions/taut_summon/tests
```

Success means:

- no production Summon write to host `TAUT_AS`/`TAUT_TOKEN`
- every driver/control-loop client has explicit false ambient inheritance
- all three shipped child processes receive the minted `TAUT_TOKEN` with no
  inherited `TAUT_AS`
- default public controller behavior performs no signal takeover
- opt-in has exact paired acquisition/release on every tested exit
- CLI signal behavior and release evidence are unchanged
- both serialized and two-worker extension lanes pass
- spec/plan/implementation links resolve and the status index is valid
- no unreviewed deviation or pending spec proposal remains

Post-deploy/CI evidence:

- supported OS/Python Summon lanes pass, especially Windows behavior where
  POSIX signal cases are inapplicable and must remain correctly skipped rather
  than simulated
- existing real-process SIGINT/STOP signal-count and release cases remain green
- no flaky process-group or xdist worker behavior is introduced
- a release-time embedding smoke probe can execute two finite controller runs
  in one process with exact before/during/after host-global assertions

## Independent Review Loop

Plan and proposed-delta review:

- Reviewer: an independent read-only subagent, preferably a different agent
  family from the author when available.
- Inputs: baseline `40a1306c...`, this complete plan including Proposed Spec
  Delta, `docs/specs/02-taut-core.md` [TAUT-8.3],
  `docs/specs/04-summon.md` [SUM-6]/[SUM-13], both implementation notes,
  `controller.py`, `_driver.py`, `_control.py`, `commands/summon.py`, and the
  closest tests.
- Required stance: look for incorrect signal semantics, incomplete client
  enumeration, public compatibility hazards, weak/mocked proof, missing
  failure priority, and performative abstraction. Answer PASS or BLOCKED based
  on whether the plan is confidently implementable and would preserve or
  improve robustness.
- Every finding is recorded below and accepted, rejected with evidence, or
  marked out of scope with reasoning. A BLOCKED verdict prevents promotion.

Implementation slice review:

- Review after object-local identity and signal ownership are both implemented;
  reviewing only one side can miss the shared public boundary.
- Reviewer receives the promotion baseline, focused RED/GREEN evidence, changed
  files, and exact diff. Round two is limited to accepted findings and their
  corrections.

Completed-work review:

- Prefer a different agent family. Review the complete spec/plan/docs/code/test
  chain and current gate output before any ready-to-land claim.
- Findings are claims; reproduce them. Record full dispositions in this plan.

## Out of Scope

- A nonblocking controller, background driver manager, daemon, child supervisor,
  or future TUI process model.
- A new public cancellation handle, callback, signal enum, interaction method,
  or controller subclass.
- Changes to provider process signals, PTY Ctrl-C delivery, STOP/control
  protocol, rate-limit interruption, watcher semantics, or terminal leases.
- Changes to core [TAUT-8.3], ordinary `TautClient` default identity behavior,
  CLI global selector precedence, or MCP identity policy.
- Changing `TAUT_DB`, unrelated provider-child environment inheritance, storage
  schemas, session records, evidence predicates, or cleanup timeouts.
- Logging redesign, exception hierarchy expansion, module splitting, generic
  lifecycle abstractions, or a new dependency.
- Package version selection, release execution, tagging, publication, or
  rewriting an already published changelog section.
- Coalescing the already-tripped completed-plan backlog; this plan only adds
  and maintains its own required index row.

## Stop and Re-Plan Conditions

Stop and revise the plan/spec delta if:

- any driver/control client has a justified need to inherit host identity
- `install_signal_handlers=False` cannot be the safe public default without an
  undiscovered shipped caller contract
- native and standalone CLI paths do not share `SummonCommand.run`
- reliable CLI signal handling requires the command layer to import private
  driver state or guess provider/member lifecycle state
- real active-host proof cannot be built without replacing the controller,
  broker, provider, or identity boundary with mocks
- signal restoration cannot preserve exact dispositions on every supported
  main-thread path without changing the public exception model materially
- partial installation can start the provider lifecycle before rollback
- implementation needs a second driver path, new thread, dependency, storage
  change, or TUI process-policy decision
- the code change requires normative edits outside [SUM-6]/[SUM-13] or
  [TAUT-8.3] itself must change
- rollout cannot remain one coordinated reversible code/spec/docs/test change

## Deviation Log

| Spec ref | Planned behavior | Actual behavior | Rationale | Spec proposal |
|----------|------------------|-----------------|-----------|---------------|

## Execution Log

| Date | Slice | Evidence | Result |
|------|-------|----------|--------|
| 2026-08-01 | Plan and exact spec-delta review | Claude Opus read-only review against baseline, specs, implementation notes, code, and tests | Initial `BLOCKED`: child environment would inherit host `TAUT_AS`; accepted and revised. |
| 2026-08-01 | Accepted-findings review | Claude Opus two scoped verification rounds over OPUS-1/OPUS-2 and the constructor-enumeration nit | First round found the omitted third adapter; final round returned `PASS` after all three clone owners and real child seams were enumerated. |
| 2026-08-04 | Spec promotion | `git diff 40a1306c -- docs/specs/04-summon.md`; documentation reference gate | Reviewed [SUM-6]/[SUM-13] behavior and plan backlink promoted before tests/code; promotion baseline recorded above. |
| 2026-08-04 | Host identity RED/GREEN | Public finite run failed with missing `TAUT_AS`; real concurrent lifecycle failed rejoin with two selectors. Focused rerun: 4 passed. | Removed host environment mutation; all eight driver/control constructors now disable ambient identity, including watcher and control reopen owners. |
| 2026-08-04 | Provider-child identity RED/GREEN | Three direct real-child cases failed because scripted, claude-stream, and PTY children recorded host `TAUT_AS`; focused rerun: 3 passed. | Every adapter removes inherited selectors from its copied mapping before applying the explicit summoned-token overlay; the host mapping remains exact. |
| 2026-08-04 | Signal ownership RED/GREEN | Initial controller matrix: 6 failed on missing keyword/default/restore behavior. Expanded focused suite: `test_interaction.py` 37 passed. | Default performs no signal access; explicit main-thread opt-in restores callable, `SIG_DFL`, and `SIG_IGN` dispositions across clean, translated, ordinary, and `BaseException` exits; first/second install failure and restoration precedence fire. |
| 2026-08-04 | Implementation-slice review | Independent Rawls review of spec/plan/docs/code/tests | Initial `BLOCKED` on enumerable signal cases, prior-disposition diagnostics, and command-extension documentation; all accepted and corrected. Scoped round two returned `PASS`. |
| 2026-08-04 | Full behavior and integration gates | Full extension serialized lane passed with one external local-LLM skip; two-worker lane passed with the same skip; architecture-boundary and command-registry tests passed. | No local regression. The skip is an unavailable optional Ollama model, not a changed behavior path. |
| 2026-08-04 | Static, docs, and plan gates | Ruff format/check, mypy (36 source files), docs references (10 passed), plan-status index, DOM-15 fixtures, required source inspection, and `git diff --check` | All passed; source inspection found no production Summon write to host identity variables and enumerated the eight owned client constructors. |
| 2026-08-04 | Documentation/release/skill reconciliation | Implementation notes 05/06, repository map, spec mapping, and plan evidence inspected; root changelog has no active Unreleased section. TDD skill and hardening/testing runbooks evaluated. | Durable ownership rationale aligned; no published changelog rewrite and no reusable skill/runbook correction required. |
| 2026-08-04 | Completed-work review | Independent Rawls full-diff review after final serialized/two-worker/integration/static evidence; no different-family subagent was available in the current roster | `PASS`: implementation complete with no actionable defect; plan closure and ready-to-land status remain pending user-authorized commit/history evidence. |
| 2026-08-04 | Closure authorization | Repository owner requested a targeted commit after receiving the implementation, verification, residual-risk, and uncommitted-state report. | Plan status changed to `completed`; the targeted commit containing this row is the closure artifact, to be verified immediately afterward with `git log`. |

## Revision Log

| Date | Baseline | Revision | Reason | Review required |
|------|----------|----------|--------|-----------------|
| 2026-08-01 | `40a1306c` | Initial Class 5 plan and exact [SUM-13] delta | Confirmed public rich-host environment and signal leakage; selected object-local identity plus explicit signal authority | Independent plan and proposed-delta review |
| 2026-08-01 | `40a1306c` | Added [SUM-6] child-environment neutralization and real scripted/PTY child assertions | Accepted OPUS-1: removing host pops otherwise moves ambient `TAUT_AS` into each child beside the minted token | Accepted-findings round two |
| 2026-08-01 | `40a1306c` | Expanded the child boundary from two adapters to all three, including a real `ClaudeAdapter.spawn` subprocess seam | Round two found that `claude-stream` has the same host-environment clone | Final accepted-findings verification |
| 2026-08-04 | `40a1306c` plus promoted spec worktree | Implemented object-local identity, all-three child sanitization, safe signal default, exact opt-in restoration, CLI opt-in, and real boundary tests | Fulfill the promoted [SUM-6]/[SUM-13] production boundary | Independent implementation and completed-work review |

## Review Findings and Dispositions

| Review | Finding | Disposition | Plan change or rationale |
|--------|---------|-------------|--------------------------|
| Claude Opus plan/delta review (`BLOCKED`) | OPUS-1/P1: both initially identified adapters copy host `TAUT_AS`; removing global pops without changing child merge gives the provider both `TAUT_AS` and minted `TAUT_TOKEN` | accepted; final verification passed | Added exact [SUM-6] delta, every adapter owner/test seam, child token-only invariant, and revised scope/tasks/gates. |
| Claude Opus plan/delta review (`BLOCKED`) | OPUS-2/P2: the planned real test did not inspect the spawned child's environment | accepted; final verification passed | Task 3/5 and the matrix require real start-ledger assertions for scripted, claude-stream, and PTY children. |
| Claude Opus plan/delta review (`BLOCKED`) | P3 observation: finite controller operations still inherit ambient identity | out of scope | This plan corrects `run_foreground`; the reviewer confirmed the finite operations are pre-existing and not worsened. |
| Claude Opus plan/delta review (`BLOCKED`) | Nit: constructor enumeration must inspect `_persistent_client`'s constructor, not only wrapper call sites | accepted; round two passed | Task 3 enumerates production `TautClient(...)` constructors; fresh-eyes review calls out wrapper ownership explicitly. |
| Claude Opus accepted-findings round two (`FAIL`) | OPUS-1 remained open because `ClaudeAdapter.spawn` is a third host-environment clone; OPUS-2 and the constructor nit otherwise passed | accepted; final verification passed | Added `_claude.py`, `test_claude_adapter.py`, a real temporary executable wrapper over the shipped scripted provider, and all-three enumeration throughout the plan. |
| Claude Opus final accepted-findings verification (`PASS`) | All three clone owners, exact files, remove-before-overlay ordering, real child assertions, and the account-free Claude wrapper are complete and mutually consistent | resolved | No further plan change required. |
| Rawls implementation-slice review (`BLOCKED`) | Signal proof omitted `SIG_DFL`/`SIG_IGN`, translated error, first-install failure, and continued restoration evidence; restoration diagnostics omitted prior disposition; implementation note 06 was not reconciled | accepted; scoped round two passed | Expanded the real/fault-injected matrix, included prior disposition in public/logged restoration diagnostics, and documented controller-default versus shared command-adapter ownership with a plan backlink. |
| Rawls scoped round two (`PASS`) | All three accepted findings are closed; focused tests and static/docs gates pass | resolved | No remaining scoped finding. Residual supported-platform and external-provider evidence remains CI/release work. |
| Rawls completed-work review (`PASS`) | Complete spec/plan/implementation/code/test chain and final local gates are aligned; no actionable defect remains | resolved | Implementation is complete; the subsequent owner-authorized targeted commit permits plan closure once repository history verifies it. |

## Fresh-Eyes Review

The implementation and completed-work reviews confirmed:

- the spec says what is true during the run, not only after return
- every owned client and delayed reopen path is enumerated
- `_persistent_client` is checked at its internal `TautClient` constructor,
  while its call sites remain behavior coverage rather than duplicate keyword sites
- all three adapter child copies remove ambient identity before explicit
  overlay, and all three real child paths prove token-only identity
- the public default is safe and CLI ownership is explicit
- terminal interaction does not imply signal authority
- partial signal acquisition cannot leak or start lifecycle work
- success, typed failure, and `BaseException` all release acquired handlers
- primary-error precedence and restoration failure visibility are specified
- real environment, signal, identity, provider, control, and release seams stay
  real where each contract depends on them
- no task invents a TUI process model or a second driver path
- rollout, rollback, post-deploy evidence, traceability, and review gates are
  executable without guessing
