# Summon Controlling Terminal and Live Lane Plan

Status: completed — spec and implementation slices completed and independently
reviewed on 2026-09-24. Deterministic gates are green; the explicitly selected
real-provider host smoke was not run. The targeted closing commit records the
completed work.

Class: 5 (spec-changing) and risky under [DOM-5]: the change adds a
normative provider-survival statement to [SUM-11], changes the POSIX spawn
lifecycle owned by [SUM-7.1]/[SUM-7.4] (process containment; cleanup
lifecycle), and changes a test lane's outcome rules. Hardening is required.
Not process-changing (the live-lane rules are a test-suite convention, not
a planning/review rule).

Plan type: implementation with spec revision.

Owner: implementing engineer. The repository owner decided on 2026-09-24
that the live lane stays on by default and must produce real outcomes.

## Goal

Close two gaps between what Summon promises and what the process domain
does, and stop the default local test run from spending model quota to
prove nothing. First, the POSIX harness PTY is never the child's
controlling terminal: `_pty_posix.py` opens the slave before
`spawn_process`, the shared process-domain owner starts a new session
(`start_new_session=True`), and nothing calls `TIOCSCTTY`. Inside the
child, `/dev/tty` fails with `ENXIO`, and when the driver dies (`kill -9`)
no `SIGHUP` reaches the provider: it survives with PPID 1, `taut-summon
status` says "nothing summoned", and a resummon needs no `--takeover`, so
two processes can hold one `TAUT_TOKEN`. The same missing controlling
terminal is why a `fake_tui.py` fixture from
`tests/test_pty_adapter.py::test_interrupt_unblocks_full_pty_input_queue`
has been orphaned on the owner's machine since 2026-09-16 (PID 70100).
Second, `tests/test_live_harness.py` runs by default on any non-CI
machine but cannot pass there: only strict mode calls
`_prewire_live_harness`, which sets the ledger's `wired` flag before
spawning; the default mode leaves the fresh database unwired, so the
driver's readiness condition (`input_prompt_observed and wired`,
`_driver.py:1223`) is unsatisfiable, `awaiting_onboarding` is always
reported, and every default run ends in a skip after spending a real
orientation turn. The owner's direction: the lane exists to make sure
things work, so a default run must pass or fail on the provider's real
behavior; the quota cost is accepted.
Evidence: `docs/plans/artifacts/2026-09-23-deep-dive-review.md` §1 item 7
and §2.

## Requested Outcomes

- [x] The POSIX provider's PTY slave is its controlling terminal; when the
  master holder dies, the provider receives `SIGHUP` under the OS's normal
  rules. [SUM-11] states what a driver crash guarantees about the provider.
- [x] `_spawn_fake` and `DriverProcess.cleanup` reap every process group
  they create on every path, including timeouts and assertion failures.
- [x] The live-harness lane keeps its local default-on behavior and has no
  false skips: the default run prewires the ledger (the test is the
  acknowledging human), waits deadline-based for behavioral readiness, and
  then passes or fails. A skip is produced only when the lane is disabled
  by `TAUT_SUMMON_LIVE_HARNESS=0`/CI or the provider binary is absent;
  strict mode differs only by failing on an absent binary.
- [x] A host-PTY scenario lane exists: a test owns a real pseudo-terminal
  as the *host* side and launches the real root
  `taut summon <provider> <thread>` CLI inside a shell whose controlling
  terminal and foreground process group are test-owned. The scripted lane
  always drives first-attach acknowledgement, provider prompt, legacy and
  Kitty detach chords, direct termios restoration evidence, orientation
  receipt, a chat message answered through the mouth, out-of-band status and
  dismiss, shell-prompt return after dismiss, a fresh `--attach` run after
  the first driver exits, and final provider retirement. A real installed
  provider runs locally under the same default-on rule after explicit provider
  selection, with provider-specific prompt/readiness matching and enhanced-key
  assertions only when that provider actually negotiates the protocol. It
  never silently chooses a binary from `PATH`. This lane replaces the
  "physical terminal observation pending" step of the active detach plan
  with an automated proof; it does not invent live-driver reattachment.
- [x] The two detach-diff follow-ups found in review are recorded for the
  active detach plan, not implemented here.

## Source Documents

Source specs:

- `docs/specs/04-summon.md` [SUM-2], [SUM-7.1] (adapter process-domain
  lifecycle), [SUM-7.4] (PTY shell adapter; domain ownership),
  [SUM-8] (single-driver guard), [SUM-11] (failure modes), [SUM-12]
- `docs/specs/01-development-documentation-operating-model.md` [DOM-5],
  [DOM-6], [DOM-15]

Supporting context:

- `docs/plans/2026-08-24-extension-seams-process-containment-coverage-plan.md`
  (active): E2 promoted [SUM-7.1]'s "one owned process domain" text and
  [SUM-7.4]'s spawn sentence ("the shared POSIX process-domain spawn owner
  … in a new session/process group"). This plan extends that owner; it
  does not add a second spawn path. Its comprehension question 5 ("why is
  E2 containment not full captivity?") still holds: a controlling terminal
  is lifecycle plumbing, not sealing.
- `docs/plans/2026-09-23-summon-enhanced-keyboard-detach-plan.md`
  (active; code landed at `bd8ff4e`, shipped in 0.9.9): inherits the two follow-ups in "Deferred to
  the active detach plan" below.
- `docs/implementation/05-taut-summon-architecture.md` "PTY adapter".
- `extensions/taut_summon/README.md` lines ~133–141 (live-harness
  documentation).
- `docs/agent-context/runbooks/testing-patterns.md` Rule 3, Pattern 7.
- `docs/plans/artifacts/2026-09-23-deep-dive-review.md` §1 item 7, §2,
  §5 (Summon).

## Spec Baseline

- `bd8ff4e` (`Support enhanced keyboard detach protocols`, which promoted
  the detach plan's [SUM-7.4] delta) — `docs/specs/04-summon.md` at plan
  authoring time; unchanged through `c894059` (the 0.9.9 release SHA). The
  [SUM-7.1] and [SUM-11] paragraphs this plan touches are unchanged since
  `c0a4616`.
- Promotion baseline identifier: `cfd8799` (current pre-promotion HEAD; its
  post-0.9.9 changes only retire historical plan links in this spec).

## Proposed Spec Delta

Promotion strategy: **A — in-file edit, text before link claims**.

| Spec file | Strategy | Sections touched |
|-----------|----------|------------------|
| `docs/specs/04-summon.md` | A | [SUM-7.1] POSIX domain sentence; [SUM-11] "Driver crash" bullet; [SUM-12] controlling-terminal, live-lane, and host-PTY verification bullets; `## Related Plans` |

### [SUM-7.1] — amend the POSIX sentence of the process-domain paragraph

Current: `On POSIX the provider is the leader of a new session/process
group, and the domain owner is the only code allowed to reap it.`

Proposed: `On POSIX the provider is the leader of a new session/process
group whose controlling terminal is the adapter's PTY slave, established
in the child before `exec` (`TIOCSCTTY` or `os.login_tty`) by the shared
spawn owner; the domain owner is the only code allowed to reap it. A
provider that deliberately escapes the domain (`escape_domain`) is not
given a controlling terminal.`

### [SUM-11] — replace the "Driver crash" bullet

Current: `- Driver crash: cursors and ledger make restart safe
(at-least-once injection); the stale ledger claim is reclaimable by
evidence.`

Proposed: `- Driver crash: cursors and ledger make restart safe
(at-least-once injection); the stale ledger claim is reclaimable by
evidence. Because the PTY slave is the provider's controlling terminal,
closing the master on driver death delivers the operating system's
`SIGHUP` to the provider's foreground group; Taut promises nothing beyond
that OS behavior (a provider that ignores `SIGHUP` may survive even though
ordinary dead-driver evidence permits a new claim, so Taut cannot prevent
duplicate providers in that case). Taut adds no provider census or watchdog
for this residual risk.`

### [SUM-12] — add three bullets under the PTY adapter proofs

> - a real-PTY test kills the master holder with `SIGKILL` while a fixture
>   provider and foreground descendant use the controlling terminal and
>   asserts the group exits within the bounded interval; the same scenario
>   without a controlling terminal is the recorded pre-fix failure; a
>   setup-failure companion proves no child remains, no fd leaks, and no
>   `SpawnedProcess` or adapter handle is published
> - every enabled live-harness run prewires the temporary session and skips
>   only for explicit disablement or an absent provider binary; strict mode
>   differs only by failing on an absent binary
> - a POSIX host-PTY scenario drives the real root CLI through first attach,
>   legacy and negotiated Kitty detach, direct termios restoration,
>   out-of-band control, shell return after dismiss, fresh attach after the
>   old driver exits, mouth output, and final provider retirement

### `## Related Plans` — add

> - `docs/plans/2026-09-24-summon-controlling-terminal-and-live-lane-plan.md`
>   — gives the POSIX provider a controlling terminal through the shared
>   spawn owner, states the driver-crash guarantee, reaps fixture process
>   groups on every test path, and removes the live-harness lane's false
>   skips so its default run passes or fails on real provider behavior.

## Context and Key Files

Files to modify:

- `extensions/taut_summon/taut_summon/_process_domain_posix.py` — the
  shared spawn owner (line ~76: `start_new_session=True`). The controlling
  terminal must be set here, in the child, before `exec`. `preexec_fn` is
  not thread-safe; use an exec trampoline owned by this module (a tiny
  `python -c` or a private module entry) that does
  `fcntl.ioctl(0, termios.TIOCSCTTY, 0)` then `os.execvpe`. The shared owner
  must pair the trampoline with a close-on-exec status pipe: the trampoline
  reports setup or target-exec failure, successful target exec closes the
  pipe, and `SpawnedProcess` is not published until the parent observes that
  success EOF. Read the current atomic publication boundary first.
- `extensions/taut_summon/taut_summon/_pty_posix.py` —
  `spawn_posix_pty()` (line ~44–62): `pty.openpty()`, `_set_winsize`,
  `_set_nonblocking`, then `spawn_process(argv, stdin=slave, stdout=slave,
  stderr=slave, env, close_fds=True)`.
- `extensions/taut_summon/taut_summon/scripted_provider.py` (line ~469:
  `start_new_session=bool(raw_spec.get("escape_domain", False))`) — the
  escape case that must not get a controlling terminal.
- `extensions/taut_summon/tests/test_pty_adapter.py` — `_spawn_fake`
  (line ~658–688): no finalizer; `test_interrupt_unblocks_full_pty_input_queue`
  (line ~2190–2240): disables `_signal_process_group` and closes only on
  the happy path.
- `extensions/taut_summon/tests/conftest.py` — `DriverProcess.cleanup`
  (line ~685): `SIGKILL`s only the driver.
- `extensions/taut_summon/tests/test_live_harness.py` —
  `_live_harness_enabled()` (line ~55–59: default is `not CI`),
  `_not_ready_reason` (line ~70–77).
- `extensions/taut_summon/taut_summon/_driver.py` (line ~1223–1226): marks
  `awaiting_onboarding` and still injects orientation — read only, to
  confirm the skip-before-spawn option.
- `extensions/taut_summon/README.md` live-harness paragraph.
- `tests/helpers/terminal_probe.py` (new shared test helper, lifted from the
  former TUI-local helper) — owns a POSIX host shell
  through `forkpty`/equivalent controlling-terminal setup, deadline-based
  transcript reads, foreground-child cleanup, and direct termios snapshots.
  Both extension suites import it; do not ship it in either extension wheel.
- `extensions/taut_summon/tests/test_host_terminal_scenarios.py` (new) —
  drives the root CLI through the host shell and uses separate control-plane
  subprocesses while the foreground Summon command remains live.

Read first: [SUM-7.1] and [SUM-7.4] as promoted by E2; the E2 plan's task
6 ("shared POSIX process domain"); `_process_domain_posix.py` in full.

Comprehension gate:

1. **Why does `start_new_session=True` plus a pre-opened slave leave the
   child without a controlling terminal?** Expected: `setsid()` creates a
   session with no controlling terminal; a terminal becomes controlling
   only when the session leader opens it without `O_NOCTTY` or issues
   `TIOCSCTTY`; the slave was opened by the parent, so neither happens.
2. **Why must the ioctl run in the child, and why not `preexec_fn`?**
   Expected: only the session leader can acquire the terminal;
   `preexec_fn` runs between fork and exec while other threads may hold
   locks (the driver is three-threaded), so an exec trampoline or the
   spawn owner's own child-side sequence is required.
3. **What does the escape-domain provider expect?** Expected: no session
   or terminal ownership from Taut; it must remain exactly as today.

## Invariants and Constraints

- One spawn owner ([SUM-7.1]): the controlling-terminal step lives in the
  shared owner; no PTY-local fork/exec implementation. `spawn_process`
  exposes an explicit controlling-terminal request used by the POSIX PTY
  caller; stream callers retain today's no-terminal behavior.
- Atomic publication is preserved: a requested controlling terminal and the
  final provider exec must both succeed before the owner returns a
  `SpawnedProcess`. Setup failure retires and reaps the unpublished child and
  closes every partial fd before raising `AdapterError`.
- The close ladder (observe leader exit without reaping → group signal
  ladder → reap → release) is unchanged; `SIGHUP` on master close is an
  OS effect the ladder tolerates, not a new step.
- Windows path (`_pty_windows.py`, Job Object) is untouched.
- `escape_domain` providers keep no controlling terminal.
- The scripted provider and `fake_tui.py` must keep working: they read the
  PTY through stdin, not `/dev/tty`, so acquiring a controlling terminal
  must not change their input path.
- No new dependency. No watchdog, census, or "is the provider still alive"
  poll ([THEORY-5.A6]-adjacent: the precondition is the OS contract, not an
  adversary).
- The live lane's strict mode keeps its current meaning.
- Detach releases the terminal bridge but does not exit the foreground Summon
  command. Host-terminal tests inspect termios directly after detach and use a
  separate CLI process for status, chat, and dismiss.
- `--attach` never bypasses [SUM-8]'s single-driver guard. A host scenario may
  start a fresh `--attach` only after out-of-band dismiss has stopped the prior
  driver and the first foreground CLI has returned to its shell.
- The host scenario exercises the root `taut summon` command, not only the
  standalone `taut_summon run` console.

Hidden couplings:

- Summon's Ctrl-C forwarding writes `\x03` to the master; with a
  controlling terminal and `ISIG` the line discipline may now also deliver
  `SIGINT` to the foreground group. Read `_TerminalState` raw-mode setup;
  if the slave is in raw mode with `ISIG` cleared, nothing changes; if
  not, task 5 must assert the provider receives exactly one interrupt.
- `test_interaction.py` and `test_driver.py` fixtures spawn through the
  same owner; a behavior change there is a regression, not a fixture
  update.

Failure policy: a failed `TIOCSCTTY` or final target exec is reported through
the trampoline status pipe as `AdapterError` at spawn (fatal), like any other
domain setup failure under [SUM-7.1]. The parent retires the unpublished
child before returning the error. Fixture cleanup first asks the live driver
to run its owned close path; any direct PGID signal is an identity-checked,
best-effort last resort and is not described as reaping through a capability
the fixture does not own. Teardown attempts cleanup for every created fixture
and reports aggregated failures rather than abandoning later cleanup.

## Rollout, Rollback, and One-Way Doors

- Source revert restores today's no-controlling-terminal spawn.
- No storage or ledger change. No one-way door.
- Post-deploy signal: `kill -9` of a detached driver with a scripted
  provider in a stall scenario leaves zero provider processes within the
  bounded interval; `ps -o stat,tty` for a live provider shows a `s`
  session-leader flag and a real tty.

## Dependency-Ordered Tasks

1. **Owner decision complete** on the live-lane default (open question 1).
2. **Independent plan review complete**, including the [SUM-7.1]/[SUM-11]
   delta and the E2 interaction. The review's feasibility amendments are
   incorporated in tasks 4–8 and recorded in the Review Log.
3. **Spec-promotion slice**; record the promotion baseline.
4. **Red real-PTY and spawn-publication tests.** In `tests/test_pty_posix.py`,
   run a tiny `/dev/tty` fixture through the real adapter under a helper
   process that owns the master; `SIGKILL` that master holder and assert the
   provider leader and one foreground descendant receive the terminal hangup
   and exit within 2 s. This must fail at baseline (the leader survives with
   PPID 1, `Ss`, `??`). Add the escape-domain control: an `escape_domain`
   descendant still has no controlling terminal. Add a forced setup-failure
   case (non-tty fd or injected trampoline failure) proving `spawn_process`
   raises before publishing a handle and leaves no child or fd behind.
5. **Implement in the shared spawn owner.** Add an explicit
   `controlling_terminal` request to `spawn_process`; the POSIX PTY caller
   sets it and stream callers do not. For that request, launch the child-side
   exec trampoline with a close-on-exec status pipe, acquire fd 0 with
   `TIOCSCTTY`, and exec the target. Publish only after success EOF; on a
   structured failure, run unpublished-child cleanup and raise `AdapterError`.
   Verify the Ctrl-C coupling with a canonical/`ISIG` fixture that counts the
   interrupts it receives. Stop if implementation needs `preexec_fn`, a
   PTY-local spawn path, or publishes before final exec success.
6. **Fixture reaping.** Convert `_spawn_fake` to a fixture or give it a
   `request.addfinalizer` that calls idempotent `handle.close()`, preserving
   the production domain owner's ladder and one reap. `DriverProcess.cleanup`
   first uses its existing STOP path (or the installed driver signal handler)
   while the driver is alive so driver-owned teardown closes the provider
   domain; only after bounded cooperative failure may it identity-check the
   recorded provider PID/PGID and apply a best-effort hard signal before
   killing/reaping the driver. The `driver_factory` finalizer attempts every
   cleanup and raises one aggregated teardown failure afterward. Prove the
   assertion-failure path with a subprocess/meta-test whose outer test can
   inspect that the deliberately failing inner case left no live provider.
7. **Live lane: no false skips.** Red: with a provider installed and
   authed, the default (non-strict) run currently skips; assert it passes.
   Implement: call `_prewire_live_harness` in every enabled run, not only
   strict; turn every mid-run skip in `_wait_for_live_ready` and
   `_reject_unready_harness` into `pytest.fail` with the existing
   diagnostic (detached session exited, terminal query gap, no ready
   prompt within the deadline); keep `pytest.skip` only for a disabled
   lane and an absent binary (strict: absent binary fails). Wait with the
   existing deadline, not attempt counts. Update the README paragraph to
   say the lane runs by default, proves real-provider reachability, and
   consumes real provider input for orientation and the injected probe (at
   least two provider inputs; do not describe it as one model turn without a
   measured provider-specific accounting result). Stop if passing
   requires synthesizing anything beyond the `wired` acknowledgement the
   strict path already sets.
8. **Host-PTY scenario lane.** Owner motivation (2026-09-24): a bare
   `taut summon claude` exposed a detach-chord bug that no automated test
   reached; the local suite must prove these things really work. Lift the
   reusable fd/transcript pieces from
   former TUI-local terminal probe into `tests/helpers/terminal_probe.py`,
   then extend the shared helper with a
   POSIX host-session owner that launches a shell under `forkpty` (or an
   equivalent session-leader + `TIOCSCTTY` sequence), retains a cumulative
   stripped transcript, snapshots termios, and retires the shell's complete
   foreground process group on every path. The existing helper does not yet
   provide those shell/session semantics. Also reuse
   `extensions/taut_summon/tests/fixtures/terminal_io.py` plus the
   adapter's `output_tail` stripping to reduce escape-laden bytes to text.
   Write
   `extensions/taut_summon/tests/test_host_terminal_scenarios.py`:
   - start from a fresh **unwired** database and, through the host shell, run
     `python -m taut --db <db> summon <name> general --provider <provider>`
     (no `--detach`); drive the first-attach acknowledgement and provider
     input as a human would;
   - scrape only host-visible text with monotonic-deadline waits: the
     acknowledgement, provider prompt, and detach/reset output. Prove
     orientation delivery through the scripted provider's received log,
     because orientation begins after detach when provider output is no
     longer mirrored to the host terminal;
   - send legacy `b"\x1c\x1c"`, wait for `wired` through an out-of-band
     status subprocess, and compare `termios.tcgetattr()` on the host slave
     with the saved cooked baseline. Do **not** expect a shell prompt yet:
     the foreground Summon command intentionally remains live;
   - inject a chat message from another member through an out-of-band root
     CLI, configure the scripted provider to answer through a real
     `python -m taut say`, and assert the reply in `taut log`;
   - run `taut dismiss <name>` out of band, assert the first foreground CLI
     exits, then wait for the host shell prompt and run `stty -a` as a second
     restoration proof;
   - start a **new driver** with `taut summon --attach <name>` through the
     same host shell, acknowledge it, detach again, dismiss out of band, and
     assert the recorded scripted-provider PID/process group is gone. This
     is reattach after driver retirement, never concurrent live-driver
     attachment;
   - in the scripted lane, configure provider output to push Kitty mode and
     repeat the detach with `\x1b[92;5u\x1b[92;5u`; both legacy and Kitty
     cases are mandatory in CI. In the real-provider lane, require the
     legacy chord; exercise the encoded chord only after the transcript
     shows that provider negotiated an enhanced keyboard protocol.

   State machine (the shell and the control plane are deliberately separate):

   ```text
   host shell:  prompt -> summon/attach -> detach -> driver keeps running
                   ^                              |
                   |                              v
                prompt <- CLI exits <- out-of-band dismiss
                   |
                   +-> fresh `summon --attach` -> detach -> dismiss -> prompt

   control:                   status/chat/log --------^-----------^
   ```

   Provider selection: the scripted provider always runs so CI owns a
   deterministic proof. A local real-provider case uses an explicit
   environment-selected provider or the existing parameterized provider
   matrix; never silently choose the first binary on `PATH`. It follows the
   live lane's enable/absent-binary rules but does not prewire the first-attach
   database. Provider-specific prompt patterns and mouth instructions live
   with that provider's case. Screen scraping remains stripped-text matching;
   if cursor position or overwrite semantics become necessary, stop and
   propose `pyte` as a dev-only dependency under Golden Rule 9. The scenario
   is POSIX-only because its contract includes `forkpty`, `termios`, and
   `stty`; Windows ConPTY remains out of scope. What stays real: the host PTY,
   root CLI process, provider PTY, control-plane subprocesses, and chord bytes.
9. **Traceability, CHANGELOG, completed-work review, index flip.** Record
   in the Execution Log whether PID 70100 was terminated by the owner, and
   record in the active detach plan's Execution Log (append-only) that
   the physical-terminal observation is superseded by the scenario lane.

## Deferred to the active detach plan

Recorded here so they are not lost; they belong to
`docs/plans/2026-09-23-summon-enhanced-keyboard-detach-plan.md` and are
not implemented by this plan:

- A lone legacy `ESC` is now held up to 100 ms and coalesced with the next
  key (`ESC`,`x` → `b"\x1bx"`, which TUIs parse as Alt+x). Either document
  the trade-off in [SUM-7.4] and the architecture note, or forward a
  trailing lone `ESC` immediately and hold only from `ESC [`.
- Surviving mutant: keeping `_pending_deadline` set after an atom completes
  passes all 62 tests. Add: first enhanced atom, advance the injected clock
  0.5 s, `expire()`, feed the second atom, expect a detach.
- `test_posix_attach_routes_ambiguity_deadline_through_select` patches
  `os.read`, `os.write`, and `select.select` process-wide (the 2026-09-03
  lesson's hazard); scope the patches to the adapter module.

## Testing Plan

- Layer: real `pty.openpty`, real fixture children, real signals; the
  Windows fake API is not involved. Do not mock `spawn_process`, the
  process-domain owner, or the PTY.
- Files: `tests/test_pty_posix.py`, `tests/test_pty_adapter.py`,
  `tests/conftest.py`, `tests/test_live_harness.py`, and
  `tests/test_host_terminal_scenarios.py`.
- Mutation check: remove the `TIOCSCTTY` step and confirm task-4 fails.
- Mutation check: publish before the trampoline success EOF and confirm the
  setup-failure test catches the escaped child/handle.
- Host lane: the deterministic scripted scenario runs in CI; the real-provider
  scenario follows the local live-lane gate. Both use the root CLI. The host
  transcript is not evidence for post-detach provider output; received logs,
  Taut log records, status, process identity, and termios own those assertions.
- Full extension suite with `TAUT_SUMMON_LIVE_HARNESS=0` and once with
  strict mode on a wired provider if the owner has one.

## Verification and Gates

```bash
cd extensions/taut_summon && TAUT_SUMMON_LIVE_HARNESS=0 uv run --extra dev pytest -n 0 tests/test_pty_posix.py tests/test_pty_adapter.py
cd extensions/taut_summon && TAUT_SUMMON_LIVE_HARNESS=0 uv run --extra dev pytest -n 0 tests/test_host_terminal_scenarios.py
cd extensions/taut_summon && TAUT_SUMMON_LIVE_HARNESS=0 uv run --extra dev pytest
cd extensions/taut_summon && uv run --extra dev ruff check taut_summon tests && uv run --extra dev mypy taut_summon tests --config-file pyproject.toml
bin/check-doc-paths && bin/check-plan-status-index
```

## Independent Review Loop

Reviewer: a different family. Inputs: this plan, the delta, E2's [SUM-7.1]
text, `_process_domain_posix.py`, `_pty_posix.py`, `_spawn_fake`. Ask:
"Does acquiring a controlling terminal change any signal the provider
receives during normal attach, Ctrl-C forwarding, or close? Is the
escape-domain control sufficient?"

## Out of Scope

- Windows ConPTY lifecycle (Job Object path).
- Any watchdog or liveness poll for providers.
- Concurrent attachment to a live driver or a change to Summon's foreground
  lifecycle; reattach in the scenario occurs only after dismiss/release.
- A cross-platform host-shell scenario. The new lane is POSIX-only; existing
  Windows ConPTY tests retain their current ownership boundary.
- The detach-diff follow-ups (deferred above).
- The `_owner_phase` `Literal` typing and transition test (P3 in the
  review; separate small plan or Class 2 change).

## Assumptions and Open Questions

1. **Resolved 2026-09-24 (owner): lane stays on by default; remove the
   false skips.** The owner bears the quota cost and judges a few turns
   insignificant; the point of the tests is to make sure things work.
   Opt-in and skip-before-spawn were rejected because both keep a lane
   that reports skips as if they were coverage.
2. **Assumption:** `fake_tui.py` and the scripted provider read stdin, not
   `/dev/tty`; task 4's fixture may need a `/dev/tty` reader variant to
   prove `SIGHUP` delivery.

## Deviation Log

| Spec ref | Planned behavior | Actual behavior | Rationale | Spec proposal |
|----------|------------------|-----------------|-----------|---------------|

## Review Log

(append-only)

- 2026-09-24 — Owner reports the independent review complete. Feasibility
  re-review found the direction sound but required three amendments before
  execution: preserve spawn-time failure and atomic publication with a
  trampoline status pipe; route fixture cleanup through the live driver's
  owned teardown before any best-effort hard fallback; and rewrite the
  host-PTY scenario around Summon's foreground lifecycle and single-driver
  guard. Tasks 4–8 now carry those requirements.

## Execution Log

(append-only)

- 2026-09-24 — Owner decision: live-harness lane remains default-on
  locally; default runs must prewire and then pass or fail on real
  provider behavior; skips only for a disabled lane or an absent binary.
- 2026-09-24 — Owner direction: a bare `taut summon claude` exposed a
  detach-chord bug that no automated test reached. Add a host-PTY scenario
  lane that launches the real CLI in a real terminal, scrapes the screen,
  and drives the documented interaction patterns (task 8).
- 2026-09-24 — Spec promotion completed against `cfd8799`. Independent review
  corrected the residual SIGHUP contract: ordinary dead-driver evidence can
  permit a new claim while a SIGHUP-ignoring orphan survives, so duplicate
  prevention is not promised and no `--takeover` claim was invented.
- 2026-09-24 — Controlling-terminal slice completed red-green. The shared
  POSIX spawn owner now uses an isolated `-I -S` exec trampoline, a
  close-on-exec READY/error status protocol, `TIOCSCTTY`, and unpublished-child
  retirement. Proofs cover unchanged stream spawning, terminal ownership,
  pre-READY exit, setup and target-exec failure, master-holder death across a
  foreground tree, escaped-session isolation, and exactly one canonical
  `SIGINT`. Independent re-review returned CLEAR.
- 2026-09-24 — Fixture cleanup completed red-green. `_spawn_fake` registers
  idempotent `handle.close`; driver fixtures try STOP and installed signal
  teardown before an identity-checked hard fallback; the failure path proves
  provider retirement precedes driver kill; cleanup-all aggregates ordinary
  exceptions; and an inner failing pytest case proves its provider is gone
  while the outer pytest host remains alive. Independent re-review returned
  CLEAR.
- 2026-09-24 — Live lane completed red-green. Every enabled provider is
  prewired before spawn and any subsequent readiness/status/query/catch-up
  gap fails. Explicit disablement and an absent binary remain the only skips;
  strict mode differs only for the absent binary.
- 2026-09-24 — Host-PTY lane completed red-green. The shared root test helper
  owns a POSIX shell session and identity-checked cleanup. Deterministic legacy
  and Kitty cases drive the root CLI through first attach, detach, direct
  termios proof, out-of-band status/chat/log/dismiss, shell return, fresh
  attach, and final provider retirement. An explicitly selected real-provider
  case carries the same lifecycle and uses encoded detach only after a complete
  nonzero Kitty enable sequence. It was not externally executed in this run.
  Independent re-review returned CLEAR.
- 2026-09-24 — Verification: full Summon suite with external harnesses disabled
  passed `716 passed, 18 skipped` in 463.92 seconds before final host-helper
  hardening; the affected host file then passed `10 passed, 1 expected skip`.
  Summon Ruff check and format passed; strict mypy passed 55 files. The
  controlling-terminal file passed `22 passed, 1 platform skip`; the full PTY
  adapter file passed `177 passed, 1 expected inner-probe skip`; documentation
  paths, plan index, and `git diff --check` passed. PID 70100 was absent when
  checked; whether the owner terminated it cannot be established from current
  process evidence. The targeted closing commit records the completed work.

## Fresh-Eyes Review

The riskiest spawn boundary is no longer only the child-side sequence
(session leader, then `TIOCSCTTY`, then exec): it is preserving synchronous
failure and atomic publication across the trampoline. Task 5 therefore
requires a close-on-exec status pipe and forbids `preexec_fn`, a PTY-local
spawn path, or early publication. The Ctrl-C line-discipline coupling remains
the hidden signal interaction most likely to surprise and has its own
canonical/`ISIG` assertion. The host-lane risk is lifecycle confusion:
detach restores the terminal bridge but intentionally does not return the
shell, so task 8 gives terminal observation, control commands, dismiss, shell
return, and fresh reattach distinct owners and phases.
