# Summon Controlling Terminal and Live Lane Plan

Status: draft — findings verified by live reproduction and code reading;
owner decided the live-lane direction on 2026-09-24; awaiting independent
plan review.

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

- [ ] The POSIX provider's PTY slave is its controlling terminal; when the
  master holder dies, the provider receives `SIGHUP` under the OS's normal
  rules. [SUM-11] states what a driver crash guarantees about the provider.
- [ ] `_spawn_fake` and `DriverProcess.cleanup` reap every process group
  they create on every path, including timeouts and assertion failures.
- [ ] The live-harness lane keeps its local default-on behavior and has no
  false skips: the default run prewires the ledger (the test is the
  acknowledging human), waits deadline-based for behavioral readiness, and
  then passes or fails. A skip is produced only when the lane is disabled
  by `TAUT_SUMMON_LIVE_HARNESS=0`/CI or the provider binary is absent;
  strict mode differs only by failing on an absent binary.
- [ ] A host-PTY scenario lane exists: a test owns a real pseudo-terminal
  as the *host* side, launches the real `taut summon <provider> <thread>`
  CLI inside it (real installed provider by default locally, scripted
  provider in CI), scrapes the screen text, and drives the documented
  human interaction patterns end to end: first-attach acknowledgement,
  provider prompt reached, orientation delivered, a chat message injected
  and answered through the mouth, the `Ctrl-\ Ctrl-\` detach chord in
  both legacy and Kitty-encoded forms with the shell restored afterward,
  `--attach` reattach, and `taut dismiss`. This lane replaces the "physical
  terminal observation pending" step of the active detach plan with an
  automated proof.
- [ ] The two detach-diff follow-ups found in review are recorded for the
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
- Promotion baseline identifier: recorded after the spec-promotion slice.

## Proposed Spec Delta

Promotion strategy: **A — in-file edit, text before link claims**.

| Spec file | Strategy | Sections touched |
|-----------|----------|------------------|
| `docs/specs/04-summon.md` | A | [SUM-7.1] POSIX domain sentence; [SUM-11] "Driver crash" bullet; [SUM-12] one verification bullet; `## Related Plans` |

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
that OS behavior (a provider that ignores `SIGHUP` may survive, and a
resummon then requires the existing `--takeover` evidence path). Taut adds
no watchdog for this case.`

### [SUM-12] — add one bullet under the PTY adapter proofs

> - a real-PTY test kills the master holder with `SIGKILL` while a fixture
>   provider blocks on `/dev/tty` reads and asserts the provider exits
>   within the bounded interval; the same scenario without a controlling
>   terminal is the recorded pre-fix failure

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
  not thread-safe; use an exec trampoline (a tiny `python -c` or a module
  entry that does `fcntl.ioctl(0, termios.TIOCSCTTY, 0)` then
  `os.execvpe`) or `os.login_tty` semantics inside the existing spawn
  helper — read its current structure first.
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
  shared owner; no PTY-only second implementation.
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

Hidden couplings:

- Summon's Ctrl-C forwarding writes `\x03` to the master; with a
  controlling terminal and `ISIG` the line discipline may now also deliver
  `SIGINT` to the foreground group. Read `_TerminalState` raw-mode setup;
  if the slave is in raw mode with `ISIG` cleared, nothing changes; if
  not, task 5 must assert the provider receives exactly one interrupt.
- `test_interaction.py` and `test_driver.py` fixtures spawn through the
  same owner; a behavior change there is a regression, not a fixture
  update.

Failure policy: a failed `TIOCSCTTY` is `AdapterError` at spawn (fatal),
like any other domain setup failure under [SUM-7.1]; a fixture-reap failure
in teardown is reported, not swallowed.

## Rollout, Rollback, and One-Way Doors

- Source revert restores today's no-controlling-terminal spawn.
- No storage or ledger change. No one-way door.
- Post-deploy signal: `kill -9` of a detached driver with a scripted
  provider in a stall scenario leaves zero provider processes within the
  bounded interval; `ps -o stat,tty` for a live provider shows a `s`
  session-leader flag and a real tty.

## Dependency-Ordered Tasks

1. **Owner decision** on the live-lane default (open question 1).
2. **Independent plan review** including the [SUM-7.1]/[SUM-11] delta and
   the E2 interaction.
3. **Spec-promotion slice**; record the promotion baseline.
4. **Red real-PTY test.** `tests/test_pty_posix.py`: spawn `fake_tui.py`
   (or a tiny fixture that opens `/dev/tty`) through the real adapter,
   `SIGKILL` the process that holds the master, assert the child exits
   within 2 s. Must fail at baseline (child survives; the review confirmed
   this with PPID 1, `Ss`, `??`). Add the escape-domain control: the
   scripted `escape_domain` provider still has no controlling terminal.
5. **Implement in the shared spawn owner.** Set the controlling terminal
   in the child before exec for non-escape spawns. Verify the Ctrl-C
   coupling above with a test that counts interrupts the fixture receives.
   Stop if the implementation needs `preexec_fn` or a PTY-only branch.
6. **Fixture reaping.** Give `_spawn_fake` a `request.addfinalizer` (or
   convert it to a fixture) that `killpg`s the recorded pgid if the handle
   is still open; make `DriverProcess.cleanup` signal the provider's group
   through the handle's domain owner, not only the driver PID. Add a test
   that a failing assertion in a stall scenario leaves no child.
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
   costs one model turn per installed provider per run. Stop if passing
   requires synthesizing anything beyond the `wired` acknowledgement the
   strict path already sets.
8. **Host-PTY scenario lane.** Owner motivation (2026-09-24): a bare
   `taut summon claude` exposed a detach-chord bug that no automated test
   reached; the local suite must prove these things really work. Build on
   what exists: `extensions/taut_tui/tests/_terminal_probe.py`
   (`HostTerminal`, `run_terminal_child`) already owns a host-side PTY
   and collects output for the TUI's handoff tests, and
   `extensions/taut_summon/tests/fixtures/terminal_io.py` plus the
   adapter's `output_tail` stripping already reduce escape-laden bytes to
   text. Lift `HostTerminal` into a shared test helper both extensions
   import (do not copy it), then write
   `extensions/taut_summon/tests/test_host_terminal_scenarios.py`:
   - spawn `python -m taut_summon run <provider> general --provider
     <provider>` (no `--detach`) under the host PTY with `TERM` and
     `COLUMNS`/`LINES` set; drive stdin bytes as a human would;
   - scrape with deadline-based waits for text patterns (the first-attach
     acknowledgement prompt, the provider's own prompt, the orientation
     text echoed by the provider, the reply in `taut log`), never sleeps;
   - send `b"\x1c\x1c"` and assert the shell prompt returns, the
     terminal is restored (query `stty -a` through the same PTY and assert
     cooked mode), and `taut-summon status` reports `wired`;
   - run the same detach with the provider first switched into Kitty
     keyboard mode (write the CSI `>1u` push through the provider PTY via
     the scripted provider's control file in CI; on a real provider rely on
     its own negotiation) and send the encoded chord
     `\x1b[92;5u\x1b[92;5u`;
   - `--attach` again, inject one message from another member, assert the
     mouth reply appears in `taut log`, then `taut dismiss` and assert no
     provider process remains (ties to outcome 1).
   Provider selection: the real installed provider by default locally
   (same enable rule as the live lane, prewired the same way); the
   scripted provider always, so CI runs the lane too. Screen scraping is
   stripped-text matching; if a scenario needs a true screen model (cursor
   position, overwrites), stop and propose `pyte` as a dev-only dependency
   under Golden Rule 9 rather than adding it. What stays real: the host
   PTY, the CLI process, the provider PTY, the chord bytes.
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
  `tests/conftest.py`, `tests/test_live_harness.py`.
- Mutation check: remove the `TIOCSCTTY` step and confirm task-4 fails.
- Full extension suite with `TAUT_SUMMON_LIVE_HARNESS=0` and once with
  strict mode on a wired provider if the owner has one.

## Verification and Gates

```bash
cd extensions/taut_summon && TAUT_SUMMON_LIVE_HARNESS=0 uv run --extra dev pytest -n 0 tests/test_pty_posix.py tests/test_pty_adapter.py
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

## Execution Log

(append-only)

- 2026-09-24 — Owner decision: live-harness lane remains default-on
  locally; default runs must prewire and then pass or fail on real
  provider behavior; skips only for a disabled lane or an absent binary.
- 2026-09-24 — Owner direction: a bare `taut summon claude` exposed a
  detach-chord bug that no automated test reached. Add a host-PTY scenario
  lane that launches the real CLI in a real terminal, scrapes the screen,
  and drives the documented interaction patterns (task 8).

## Fresh-Eyes Review

The riskiest guess is the child-side sequence (session leader, then
`TIOCSCTTY`, then exec) and its thread-safety; task 5 forbids
`preexec_fn` and names the alternatives. The Ctrl-C line-discipline
coupling is the hidden interaction most likely to surprise; it has its own
assertion.
