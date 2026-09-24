# Windows TUI Determinism Root-Cause Plan

Status: draft — evidence register assembled from the 2026-09-23 Windows
streak and the 0.9.9 release; awaiting independent plan review.

Class: 4 (risky) under [DOM-5]: the work diagnoses and corrects asynchronous
TUI/Summon lifecycle behavior that runs in more than one execution context
(Textual's loop, Summon's phase threads, a real provider process on
ConPTY) and changes the test harness that gates Windows release evidence.
Hardening applies. No normative spec change is planned; if the deep dive
finds one is required, the class escalates to 5 with a declared delta.

Plan type: diagnosis (slice 1) then implementation against existing
contracts (slices 2–3), with a spec-revision escalator.

Owner: implementing engineer. Owner direction (2026-09-24): "there should be
two things to happen: 1. a deep dive into root causes and how they can be
fixed, and how things can be made deterministic, and 2. if the current tests
are not enough, design of a test (or tests) that would be enough." Windows
bugs are closed by designing a test that elicits them and then using CI.

## Goal

Stop closing Windows TUI failures by iterating on CI. Produce a written
determinism model for the TUI's timing-sensitive paths (what event completes
each phase, and how a test observes that event instead of polling), fix the
product and harness causes the model exposes, and replace attempt-counted
waits with tests that either subscribe to the completing event or force the
failure order deterministically. Define, and then meet, a sufficiency
criterion for "the Windows TUI lane is deterministic".

## Evidence Register

The register is the input to slice 1; every row is a fact with a source.

| # | Fact | Source |
|---|------|--------|
| E1 | 0.9.9 preparation commit `3993e20` was red on Windows TUI only; seven fix-forward commits over ~3 h (`d7e056a`…`583038e`) made `c894059` green on all five retained jobs; the release helper tagged the green SHA. | `gh run list --workflow test-tui-extension.yml`; tags `v0.9.9`, `taut_tui/v0.9.9` → `c894059` |
| E2 | The failing test throughout was `test_tui_summon.py::test_setup_recovery_offer_reaches_a_pending_owned_tui_and_completes`, timing out at `_await_until(... "post-recovery orientation injection")` (`test_tui_summon.py:2017`, helper at `:1749`); once also `test_tui_action_handlers.py::test_every_action_reaches_a_concrete_handler[search.open-result]`. | run 35917159249 and 35918083458 failed-step logs |
| E3 | That test drives the real `SummonController.run_foreground` in a thread, a real gate-harness provider (`tests/fixtures/gate_harness.py`) on a real host PTY (`HostTerminal.open()`, `_terminal_probe.py`), and the real `TautApp` with only `suspend()` faked. On Windows the provider side is ConPTY. | `test_tui_summon.py` `_wire_gate_member`, `_gate_app` |
| E4 | Product root cause found in the streak: the TUI used `threading.get_ident()` as the terminal-ownership token across Summon's *distinct* confirmation and attachment phase threads; passing runs depended on numeric thread-id reuse. Fixed by an opaque per-run token (`_ScopedTuiSummonInteraction`, `583038e`; [TUI-11] sentence added). | `git show 583038e`; setup-recovery plan "2026-09-23 Release-hardening correction" |
| E5 | Second product root cause: a stale `OptionList` highlight message from a superseded transcript render could retarget selection after a search jump took ownership (`d7e056a`, `app.py` +7). | `git show d7e056a` |
| E6 | Harness causes found in the streak: (a) one host-terminal session shared across independent foreground attaches leaked cancelled Windows pipe I/O and unread reset output between runs; (b) provider-output deadlines were charged from process setup and TUI confirmation, not from the recovery generation; (c) the headless harness blocked the same asyncio loop that drives Textual's pilot during the suspension body; (d) confirmation helpers treated screen-object creation as UI readiness instead of waiting for controls to mount; (e) focus tests observed the framework event cycle early. | CHANGELOG entries at `d7e056a`, `c53ddca`, `5fcf32c`, `88a2f40` |
| E7 | Windows retained job: 477 tests in 258 s vs 138 s on Ubuntu 3.13 (1.9×), both at `-n 2 --dist loadfile`. Owner (2026-09-24): the slowness is endemic to Windows process and filesystem handling, not a defect to fix; it is the reason infrastructure phases need their own scaled budget (slice 2, step 6), never a reason to grow a behavior deadline. | run 35928843388 job logs; owner statement |
| E8 | Wait shapes in the TUI suite: `_pause_until` is `for _ in range(100): await pilot.pause(0.01)` (attempt-counted, ~1 s nominal, elastic under load); 32 `for _ in range(N)` loops across `test_tui_app.py` (16) and `test_tui_summon.py` (16); 82 bare `pilot.pause()` calls; `_await_until` in `test_tui_summon.py`. The 2026-08-14 lesson rejects fixed-count short pauses as deadlines. | grep; `docs/lessons.md` 2026-08-14 |
| E9 | S4 (initial DM navigation missing on Windows, W5) never reproduced with phase evidence: 20/20 locally, green in every hosted Windows run since `6326905`; the original wait was an attempt-counted loop at the then `test_tui_app.py:2162`; macOS oversubscription runs measured navigation apply at 40 ms median, 280 ms max. | Windows plan Execution Log; review artifact §5 (TUI) |
| E10 | The Windows lane runs `-n 2 --dist loadfile`: tests in one file share a worker, so the two largest, most timing-sensitive files serialize behind each other while the other worker idles or contends. | `.github/workflows/test-tui-extension.yml:72` |

## Requested Outcomes

- [ ] A written determinism model in `docs/implementation/12-taut-tui.md`:
  for every timing-sensitive phase (attach confirmation, terminal lease,
  recovery offer, orientation injection, navigation apply, transcript
  render, search jump, focus transition, resize), the event that completes
  it, who publishes it, and how a test observes it.
- [ ] Every root cause in E4–E6 and any new one found in slice 1 has a
  forced-order elicitation test that fails deterministically without its
  fix, on every platform, and passes with it.
- [ ] No attempt-counted wait remains in the TUI suite; waits subscribe to
  the completing event under one deadline helper, with infrastructure
  phases (process spawn, ConPTY setup) budgeted separately from the
  behavior under test.
- [ ] A stated sufficiency criterion for the Windows lane, met on hosted CI:
  the elicitation tests plus `K` consecutive green Windows runs of the
  retained lane (owner sets `K`; proposed 5) with the phase tripwire
  retained, and a `workflow_dispatch` input that repeats the Windows lane
  `N` times for soak.
- [ ] S4 of `docs/plans/2026-09-16-windows-lifecycle-determinism-plan.md`
  is inherited here and closed by elicitation, not by recurrence.

## Source Documents

Source specs:

- `docs/specs/10-taut-tui.md` [TUI-4.1] (process model), [TUI-6.1]–[TUI-6.2]
  (opening and live delivery), [TUI-9.3] (resize processing), [TUI-11.1]–
  [TUI-11.3] (Summon availability, driver ownership, terminal handoff),
  [TUI-12.1], [TUI-12.3], [TUI-13.1]–[TUI-13.2]
- `docs/specs/04-summon.md` [SUM-7.4] (setup-recovery escalation),
  [SUM-13], [SUM-13.1] (foreground readiness for rich hosts)
- `docs/specs/01-development-documentation-operating-model.md` [DOM-5],
  [DOM-10.3] (eventual-evidence helper), [DOM-15]

Supporting context:

- `docs/plans/2026-09-16-windows-lifecycle-determinism-plan.md` (active):
  S4 and its gate; its Execution Log hosted-qualification entries.
- `docs/plans/2026-08-19-tui-setup-recovery-offer-plan.md` (active): the
  2026-09-23 correction section (E4).
- `docs/plans/2026-09-24-tui-participation-loop-plan.md` (draft): owns the
  tail-pin viewport extraction; cites this plan for S4 elicitation.
- `docs/plans/2026-08-11-eventually-test-helper-adoption-plan.md`
  (completed): `tests.helpers.eventually` and `async_eventually`; the
  TUI's `_pause_until` predates or bypassed that adoption.
- `docs/lessons.md`: 2026-08-14 (fixed-count pauses are not deadlines),
  2026-08-18 (one outer timeout must not be both infrastructure budget and
  behavior oracle; scale only the containment cap), 2026-09-16 (published
  state is not completion evidence for the next phase; tests wait for the
  exact owner and outcome), 2026-09-15 (platform markers and native
  surfaces).
- `docs/agent-context/runbooks/testing-patterns.md` Patterns 4, 7, 8.
- `docs/plans/artifacts/2026-09-23-deep-dive-review.md` §5 (TUI).

## Spec Baseline

- `c894059` (0.9.9 release SHA) — `docs/specs/10-taut-tui.md` and
  `docs/specs/04-summon.md` at plan authoring time. No delta is proposed;
  if slice 1 finds a contract gap, add `## Proposed Spec Delta` and
  re-classify to 5 before slice 2.

## Context and Key Files

Files to read first (current structure):

- `extensions/taut_tui/taut_tui/summon.py` — `TuiSummonInteraction`,
  `_ScopedTuiSummonInteraction` (E4), `TerminalLeaseRequest`,
  `TerminalAttachConfirmationRequest`; the coordinator that permits exactly
  one acknowledgement or lease.
- `extensions/taut_tui/taut_tui/app.py` — `_apply_delivery`,
  `_apply_navigation_result`, `_watch_future`, the OptionList highlight
  handler changed in E5, `_declare_user_viewport_intent`.
- `extensions/taut_tui/taut_tui/session.py` — `refresh_navigation` and the
  serialized public-client worker (the S4 production path; edit only on
  causal evidence).
- `extensions/taut_tui/tests/_terminal_probe.py` — `HostTerminal`,
  `run_terminal_child`; `extensions/taut_summon/tests/fixtures/gate_harness.py`.
- `extensions/taut_tui/tests/test_tui_summon.py` — `_await_until`,
  `_wire_gate_member`, `_gate_app`, the recovery test; `tests/test_tui_app.py`
  — `_pause_until` (line ~27), the DM-navigation test.
- `extensions/taut_summon/taut_summon/_driver.py` — `_after_owner_settle`
  (setup-recovery decision, `awaiting_onboarding`, orientation injection);
  `extensions/taut_summon/taut_summon/_pty_windows.py` — `_AttachSession`,
  chunk queue, cancellation.
- `.github/workflows/test-tui-extension.yml` — matrix and `-n 2 --dist
  loadfile`.

Comprehension gate (answers in the Execution Log before slice 2):

1. **Why did thread-id reuse only fail on Windows?** Expected: numeric
   thread identifiers are recycled by the OS/interpreter; Summon's
   confirmation and attachment phases run on distinct threads whose
   lifetimes and reuse patterns differ by platform scheduler, so equality
   of `get_ident()` across phases was a coincidence that held on POSIX
   runners and not on Windows.
2. **What is the difference between "the screen object exists" and "the
   control is mounted", and which one may a test press?** Expected:
   Textual creates widget objects before the mount/compose cycle
   completes; input posted before mount is dropped or misrouted; a test
   may act only after the mount message the control itself emits.
3. **Why must an infrastructure phase and a behavior phase have separate
   budgets?** Expected: 2026-08-18 lesson — a single aggregate cap
   expiring identifies the work in progress but does not prove that phase
   consumed it; Windows process and ConPTY setup is slower by a known
   factor, and charging it against the behavior deadline makes a fast
   behavior look slow.

## Invariants and Constraints

- No test asserts timing by elapsed time; non-occurrence is proven by
  waiting for the causally later event, then asserting over retained state
  (Pattern 4).
- One wait helper: extend `tests.helpers.eventually.async_eventually` (or a
  thin TUI adapter over it, per the adoption plan's rules) with an
  event-subscription form (a Textual message or a future) plus a deadline;
  `_pause_until` and `_await_until` are retired, not duplicated.
- Real boundaries stay real ([TUI-13.1]): real `TautApp`, real SQLite, real
  Summon controller, real provider process, real host PTY. The only fake
  is Textual's headless-unsupported `suspend()`.
- Product changes are made only on causal evidence from an elicitation
  test that fails without them; "the wait was too short" is a harness
  cause and is fixed in the harness.
- Windows lane parallelism (`-n 2`) and every existing assertion are
  preserved; budgets may be restructured (infrastructure vs behavior) but
  no behavior deadline grows.
- No new dependency.
- The setup-recovery plan's E4 correction and its firing test are not
  reopened; they are the model's first worked example.

Hidden couplings:

- Summon's driver phases (`settle`, `orientation`, recovery offer) publish
  to the TUI through `TerminalAttachNotice`/`TerminalLeaseRequest`; the
  test's "orientation injection" oracle reads the gate harness log, which
  is a file the provider writes, so its readiness is a filesystem event on
  a ConPTY-hosted process, not a Textual message.
- `loadfile` distribution makes the two heaviest files each a single
  worker's serial run; per-test budgets are therefore paid under
  contention from the other worker's process spawns.
- The S4 navigation path shares `_watch_future` with every other worker
  result; a fix that changes result application ordering affects the
  tail-pin work in the participation plan.

Failure policy: a determinism defect found in product code is a P1 for
this plan and blocks its completion; a harness-only cause is fixed and
recorded but does not change product contracts.

## Rollout, Rollback, and One-Way Doors

- Harness changes and product fixes land in separate commits so a product
  fix can be reverted alone. No storage or wire change; no one-way door.
- Post-deploy signal: `K` consecutive green hosted Windows runs with the
  soak input at `N ≥ 3`, and no tripwire output in any of them.

## Dependency-Ordered Slices

### Slice 1 — Root-cause deep dive (diagnosis only, no product edits)

1. **Inventory every timing-sensitive wait.** Script over
   `extensions/taut_tui/tests/*.py`: list each `_pause_until`,
   `_await_until`, `for _ in range(N)` loop, and bare `pilot.pause()` that
   precedes an assertion; for each record the predicate, the phase it
   awaits, and the event that actually completes that phase (Textual
   message, worker future, driver notice, PTY byte, file write). Output: a
   table in this plan's Execution Log and a `## Determinism model` section
   drafted for `docs/implementation/12-taut-tui.md`.
2. **Classify the streak.** For E4–E6 and S4, state the hypothesis class:
   (a) ownership keyed by a recyclable identifier; (b) production handler
   blocking the loop that drives the pilot; (c) attempt-counted wait under
   a 1.9× slower runner; (d) deadline charged from the wrong start; (e)
   readiness inferred from object creation rather than mount; (f)
   cross-run leakage of cancelled Windows overlapped I/O; (g) framework
   message ordering after supersession; (h) ConPTY-specific delivery. Each
   class gets one sentence on how it is made deterministic (event
   subscription, opaque tokens, per-run resources, split budgets) and
   which existing lesson already names it.
3. **Measure on Windows CI once, with instrumentation, not sleeps.** Add a
   `workflow_dispatch` input to the TUI workflow that runs the Windows
   retained lane with `--durations=40` and the phase tripwire enabled, and
   repeats it `N` times. Record per-phase timings for the recovery test and
   the DM-navigation test; compute the infrastructure/behavior split.
   Stop gate: if any phase's p95 on Windows exceeds its behavior budget
   even with setup excluded, that phase is a product finding, not a
   harness one.
4. **Deliverable check.** The deep dive is complete when every wait in the
   inventory has a named completing event or an explicit "no event exists;
   production must publish one" row. Independent review of the model
   before slice 2.

### Slice 2 — Make things deterministic

5. **One event-based wait.** Extend the [DOM-10.3] helper with
   `await_event(message_type | future, *, deadline, description)` (or the
   adopter's thin TUI adapter) and convert every inventory row to it; where
   the row says "no event exists", add the publication in production (a
   Textual message posted after mount/apply, or a future resolved after
   the phase's owner finishes) — that is a product change and needs its
   own elicitation test (slice 3) first.
6. **Split budgets.** Infrastructure phases (process spawn, ConPTY
   attach, gate-harness startup) get a containment cap scaled by the
   repository's CI factor; behavior phases keep unscaled deadlines
   (2026-08-18 lesson). Record both per test.
7. **Per-run resources.** Verify structurally (a fixture assertion, not a
   comment) that each foreground attach in a test owns its own
   `HostTerminal`, log directory, and gate-harness process, and that the
   headless suspension body runs on its own checked thread.
8. **Distribution.** Evaluate `--dist loadgroup` with `xdist_group`
   markers for the process-spawning tests instead of `loadfile`, keeping
   `-n 2`; adopt only if the soak in slice 3 shows lower p95 with no new
   failures.

### Slice 3 — Tests that would be enough

9. **Elicitation test per root-cause class**, each failing deterministically
   on every platform without its fix:
   - (a) ownership by recyclable id: run the confirmation phase on a thread
     that exits, start the attachment phase on a new thread, and force
     `get_ident()` collision by draining thread creation until an ident is
     reused (or monkeypatch the identity source in a scratch copy for the
     red run); assert the scoped token still admits exactly one owner.
   - (b) loop blocking: hold the pilot's loop in the suspension body and
     assert the confirmation message still completes on its own owner.
   - (c)/(d) budgets: inject a delay at the real navigation and orientation
     boundaries longer than the old attempt budget; assert the behavior
     deadline still passes because setup is excluded.
   - (e) readiness vs mount: complete the worker future before and after
     the control mounts; assert the pre-mount case is rejected without a
     hang and the post-mount case renders.
   - (g) stale highlight: post a superseded render's highlight after a
     search jump; assert selection is retained.
   - S4 candidates (from the Windows plan's classification list): missing
     source DM, missing callback, stale-result rejection, widget
     application — one forced-order test each; if all pass forced-order,
     S4 closes with the cause classified as the harness budget the rewrite
     replaced; if one fails, that is S4's causal reproduction.
10. **Soak as the gate.** Run the Windows retained lane `N = 5` times via
    the dispatch input from step 3 with the tripwire on; the sufficiency
    criterion is `K = 5` consecutive green runs with no tripwire output.
    Record run ids in the Execution Log.
11. **Close S4.** Append the outcome to the Windows plan's Execution Log
    (append-only) and its index row; this plan inherits and closes S4.
12. **Docs, CHANGELOG, completed-work review, index flip.** Promote the
    determinism model into `docs/implementation/12-taut-tui.md`; add a
    lesson only if slice 1 finds a class not already in the ledger.

## Testing Plan

- Layer: real TUI, real Summon controller and provider, real host PTY;
  Textual `run_test` for app-level proofs; scratch copies for red runs that
  need production reverted.
- Files: `tests/test_tui_summon.py`, `tests/test_tui_app.py`, a new
  `tests/test_tui_determinism.py` for the elicitation tests, `tests/helpers`
  for the event-wait helper, `.github/workflows/test-tui-extension.yml`.
- Do not mock Textual messages, worker futures, the driver, or the PTY;
  only inject delays and thread scheduling at real boundaries.
- Mutation check per elicitation test: revert its fix in a scratch copy
  and confirm the test fails on macOS and Linux, not only on Windows.

## Verification and Gates

```bash
cd extensions/taut_tui && uv run --extra dev pytest -n 2 --dist loadfile tests/test_tui_determinism.py tests/test_tui_summon.py tests/test_tui_app.py
cd extensions/taut_tui && uv run --extra dev pytest
cd extensions/taut_tui && uv run --extra dev ruff check taut_tui tests && uv run --extra dev mypy taut_tui tests --config-file pyproject.toml
gh workflow run test-tui-extension.yml -f windows_repeat=5     # soak; record run ids
bin/check-plan-status-index
```

## Independent Review Loop

Reviewer: a different family from the author, after slice 1 (the model)
and again at completion. Inputs: this plan, the evidence register, the
inventory table, `summon.py`, `app.py`, `_terminal_probe.py`, the streak
commits. Ask: "Does every wait in the inventory have a real completing
event? Which elicitation test could pass without its fix?"

## Out of Scope

- The tail-pin viewport extraction (TUI participation plan).
- Summon's own Windows ConPTY lifecycle (Windows PTY lifecycle plan,
  completed) except where a TUI test's oracle depends on it.
- Reducing the Windows matrix or growing any behavior deadline.

## Assumptions and Open Questions

1. **Owner:** `K` (consecutive green soak runs) — proposed 5.
2. **Owner:** may the Windows plan's S4 be marked inherited by this plan
   so the predecessor can complete on S1–S3/S5? Recommended yes.

## Deviation Log

| Spec ref | Planned behavior | Actual behavior | Rationale | Spec proposal |
|----------|------------------|-----------------|-----------|---------------|

## Review Log

(append-only)

## Execution Log

(append-only)

- 2026-09-24 — Plan opened on owner direction after the 0.9.9 Windows
  streak; evidence register E1–E10 assembled from CI runs and commits.

## Fresh-Eyes Review

The plan's risk is that slice 1 becomes a report with no teeth; the
deliverable check in step 4 (every wait has a named event or a "production
must publish one" row) is the falsifiable exit. The second risk is fixing
waits without elicitation; the invariant that product changes need a
failing elicitation test first guards it.
