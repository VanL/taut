# Windows Lifecycle and Test Determinism

Date: 2026-09-16
Status: active — independently reviewed; implementation in progress.
Class: 4. Async native-I/O cancellation, deferred viewport ownership, and
cross-process test coordination trigger risky-work hardening under [DOM-5]
and [DOM-15]. No intended product behavior or normative spec text changes.
Plan type: diagnosis and implementation against existing contracts.

## Goal

Correct the Windows failures blocking coordinated 0.9.8 qualification, including
the regression and lost native coverage introduced while addressing them.
Prove each correction with forced event orderings and the real Windows path;
retain parallelism, assertions, and existing timeout bounds.

## Source Documents and Spec Baseline

Baseline: `620fbe37c89844bd62ccec5353bc6c6345896c46` for code and specs.

- `docs/specs/04-summon.md`: [SUM-4], [SUM-7.1], [SUM-8], [SUM-9], [SUM-12].
- `docs/specs/10-taut-tui.md`: [TUI-6.1], [TUI-6.4], [TUI-9.2].
- `docs/specs/01-development-documentation-operating-model.md`: [DOM-5],
  [DOM-10], [DOM-11], [DOM-15].
- `docs/program-theory.md`; `docs/agent-context/decision-hierarchy.md`;
  `docs/agent-context/principles.md`; `docs/agent-context/engineering-principles.md`.
- `docs/agent-context/runbooks/writing-plans.md`,
  `docs/agent-context/runbooks/hardening-plans.md`,
  `docs/agent-context/runbooks/testing-patterns.md`,
  `docs/agent-context/runbooks/review-loops-and-agent-bootstrap.md`.
- `docs/lessons.md` Golden Rules; `docs/implementation/03-agent-inventory.md`;
  `skills/call-agent/SKILL.md`.
- `docs/implementation/05-taut-summon-architecture.md`;
  `docs/implementation/12-taut-tui.md`.
- `docs/plans/2026-09-15-windows-pty-lifecycle-fixes-plan.md`;
  `docs/plans/2026-09-15-reported-issues-followup-plan.md`;
  `docs/plans/2026-08-14-windows-postrelease-ci-determinism-plan.md`.
- Native API contract: <https://learn.microsoft.com/en-us/windows/win32/api/ioapiset/nf-ioapiset-cancelsynchronousio>.
  ERROR_NOT_FOUND means no pending request was cancelled; success is not an
  operation-completion acknowledgement.

## Evidence and Investigation Dispositions

| Finding | Evidence and certainty | Owner |
|---|---|---|
| W1 wrong STOP identity | Root CI run 35146699199: fallback stop returns 1; concurrent stop waits 90 s. Real helper with process/CLI doubles reproduces both. Session publication precedes the log used for name resolution; historical exact interleaving is inferred because diagnostics were discarded. | S1 |
| W2 stale close assertion | Same run fails test_pty_windows.py:701 after close, not the earlier interrupt phase. Actual writer with controlled API produces closed error, consistent with terminal precedence. | S2 |
| W3 lost cancellation | Controlled API pauses after active publication and before pending I/O; one cancellation returns false, then write blocks and interrupt times out. Native reproduction remains required. | S2 |
| W4 viewport ownership | TUI run 35145237393 had wrong search anchor. Latest protection reproduces a new regression in real run_test: scroll y=38 to y=0, refresh returns y=38. | S3 |
| W5 DM navigation missing | Same TUI run failed first navigation-entry wait at baseline test_tui_app.py:2162. Later-wait edit does not address it. Cause unresolved. | S4 diagnosis gate |
| W6 native Ctrl-D | Same TUI run exited without GUARDED-QUIT. Baseline replaces Windows native path with Pilot dispatch. EOF explanation unproven; lost native coverage confirmed. | S5 diagnosis gate |

Principle-level diagnosis: readiness evidence was mistaken for later completion;
logical state publication was mistaken for native I/O entry; selection was
mistaken for viewport intent. Apply named lifecycle ownership and tests of the
actual handoff, as required by engineering principles 4, 8, 10, and 14.
No-action register: no evidence assigns these failures to SimpleBroker, xdist,
or insufficient timeout bounds. Do not modify those on this evidence.

## Context and Key Files

| Files | Existing owner and permitted work |
|---|---|
| `extensions/taut_summon/tests/conftest.py`, `extensions/taut_summon/tests/test_driver.py` | DriverProcess owns child identity/readiness/cleanup. Reuse session helpers and correlated control PING; repair STOP resolution and diagnostics. |
| `extensions/taut_summon/taut_summon/_driver.py`, `extensions/taut_summon/taut_summon/_state.py` | Read startup order and PID/start evidence. Production changes only if a deterministic reproduction proves an additional defect; amend scope first. |
| `extensions/taut_summon/taut_summon/_pty_windows.py`, `extensions/taut_summon/taut_summon/_win32_io.py`, `extensions/taut_summon/tests/test_pty_windows.py` | _EpochWriter owns serialization, epochs, active-operation handle lifetime; NativeApi owns cancellation result. Keep these owners and existing cleanup aggregation. |
| `extensions/taut_tui/taut_tui/app.py`, `extensions/taut_tui/taut_tui/widgets.py` | TautApp owns search intent/generation and viewport restore; widgets provide actual user-input events. Correct ownership locally, not a package split. |
| `extensions/taut_tui/taut_tui/session.py` | Read navigation production path for S4; edit only after causal evidence identifies this owner. |
| `extensions/taut_tui/tests/test_tui_app.py`, `extensions/taut_tui/tests/test_tui_action_handlers.py`, `extensions/taut_tui/tests/test_tui_textual_contract.py` | Real Textual harness, exact-result observers, and shipped terminal probe. Preserve their integration boundaries. |
| `tests/helpers/terminal_probe.py` | Shared `run_terminal_child` owns native child transport and cleanup; S5 may correct encoding here after diagnosis. |
| `.github/workflows/test.yml`, `.github/workflows/test-tui-extension.yml` | Existing native qualification owners. Temporary focused branch diagnostics may narrow commands; final workflows retain existing selectors/matrices. |
| `docs/implementation/05-taut-summon-architecture.md`, `docs/implementation/12-taut-tui.md`, `CHANGELOG.md`, `docs/plans/README.md` | Update rationale, release note and plan status with evidence. |

Before editing, record answers in Execution Log: (1) Does a session row prove
control readiness? Expected: no, it precedes provider/control/watch setup.
(2) Does _active prove pending kernel I/O? Expected: no, publication precedes
WriteFile. (3) Does selected_message_id identify the first visible row?
Expected: no, scrolling can leave selection unchanged. Wrong answers block the
relevant slice until its owner code and spec are reread.

## Invariants and Constraints

- I1: STOP reaches only the owned child session. Never guess identity from a
  mutable requested name, reuse bare PID identity across process lifetimes,
  or count forced termination as graceful success.
- I2: request_close remains nonblocking and terminal. Interrupt remains reusable;
  close/exit supersedes cancellation; genuine transport errors remain fatal.
  Preserve serialized writes, Ctrl-C ordering, bounded finalization, continuous
  drain and exactly one exit event. Never cancel using a released thread handle.
- I3: Stale restores cannot overwrite newer conversation or user viewport intent.
  Preserve selection independently of first-visible-row anchor and tail pinning.
- I4: Keep native Ctrl-D input-to-guarded-quit-to-clean-exit proof. A simulated key
  is supplementary, never its substitute. No assertions, test cases, OS matrix
  entries, or concurrency settings removed to obtain green.
- I5: Events acknowledge an exact request and its applied outcome, including
  errors and stale rejection. Calling a callback that returns early is not proof
  of successful completion. Keep real errors visible, never poll them away.
- I6: No timeout extensions, sleeps as proof, dependency changes, schema changes,
  broad exception swallowing, new retry budgets, or suppression additions.
  A bounded cancellation reconciliation loop is operation-lifecycle work, not
  a test retry or repeated user operation.

## Rollback and Rollout

No migration or public API change is planned. Keep coherent code/test fixes in
separate commits per slice; revert a slice as a unit if qualification regresses.
Do not retain the known permanent search pin or weakened Ctrl-D proof as a
fallback. No tags or publication until all completion gates pass. Publication
is irreversible; afterward corrections use a new version, not moved tags.
The already requested release resumes through unchanged `bin/release.py all`
as a separate routine release action after this work qualifies.

## Tasks and Deterministic Acceptance

### S1 — Exact driver identity and readiness

- [x] Reproduce both wrong-target STOP outcomes before the fix. Resolve the owned
  session using child PID plus available process-start evidence, retain member
  ID, and PING that member through the existing correlated control helper.
  If CLI STOP requires a name, derive its current name from that exact member;
  never fall back on lookup failure. Prefer the existing member-targeted control
  helper where it avoids a mutable-name race, retaining separate real CLI tests.
- [x] Separate graceful stop from cleanup fallback; failure diagnostics include
  target member/session, child PID/start/exit, STOP reply and child stderr.
  Bound diagnostics and redact continuity tokens; diagnostic failure must not
  replace the primary error. Cleanup still owns child reap on every failure.
- [x] Force early shutdown while name-allocation competitors are active. Use
  real drivers, real SQLite and real control requests; gate the later readiness
  boundary with a test-only injected synchronization seam (no shipped sleep or
  environment backdoor). Exercise the CLI/control stop strategy on POSIX too.
  Assert unrelated member and competing driver remain alive and responsive,
  intended child exits 0, and all children are reaped in finally.
- [x] Done: forced schedules fail before/pass after, existing identity/process
  tests pass with -n auto, independent slice review passes. Replan if this needs
  a new public selector, persistence field or core ownership change.

### S2 — Write retirement and cancellation handoff

- [x] Separate typed reusable-interrupt outcomes from terminal-close outcomes in
  the native test; keep active and queued writers covered in both phases.
- [x] Add deterministic fake-native tests pausing before syscall entry, while
  pending, after normal completion, and during concurrent close. Use the real
  _EpochWriter; fake only native calls and their legal outcomes.
- [x] Extend cancellation reconciliation until the specific active operation
  retires: under the state lock validate operation identity and handle validity,
  attempt cancellation, then release the lock while waiting on the condition.
  Reattempt on a short bounded wait when that SAME operation remains active,
  including ERROR_NOT_FOUND and cancellation-requested-but-not-completed cases.
  Use the existing monotonic operation deadline; no busy spin or timeout growth.
  Never hold the serializer or state lock while waiting for native completion.
  Completion/epoch checks prevent a later writer from inheriting cancellation.
- [x] Force the post-active-clear/pre-handle-close ordering, then handle release
  and potential numeric reuse. Assert every cancel attempt validates the exact
  operation under _state and no attempt reaches a retired/released handle.
- [x] Retain native blocked-pipe proof. A test drainer must not release the large
  write before both cancelled callers have returned; afterward drain the single
  Ctrl-C and allow interrupt completion. If caller publication waits for Ctrl-C,
  acknowledge native write retirement separately before draining, then assert
  caller outcomes after interrupt completion. Always release/reap test threads
  and handles on assertion failure. Active publication alone is not readiness.
- [x] Done: all forced schedules, transport-error propagation, handle lifetime,
  queued writes, repeated interrupt and close precedence pass; native Windows
  proof passes. Replan if synchronous reconciliation cannot meet the existing
  contract; overlapped-I/O conversion is not implicitly authorized by this plan.

### S3 — User viewport intent supersedes search restoration

- [x] Before production edits, use a disposable run_test probe to establish which
  pinned Textual wheel, scrollbar and keyboard events distinguish user scrolling
  from programmatic scroll_to. TautOptionList does not yet expose a unified
  user-scroll seam. Record the chosen event boundary and probe evidence in the
  Execution Log; stop and revise S3 if those events cannot support the invariant.
- [x] Lock down the baseline scroll-snap regression with real run_test and actual
  scroll input on a transcript taller than the viewport. Assert rendered offset,
  first visible row/intra-row offset and unchanged selected message.
- [x] Replace _protected_search_anchor with finite restore ownership using the
  existing intent/generation machinery. Programmatic restore may preserve its
  logical anchor while pending; actual user scroll invalidates that ownership.
  Distinguish user input from programmatic scroll changes at the widget/event
  boundary. Cover mouse wheel, scrollbar and keyboard scroll paths supported by
  the widget. Successful restoration releases protection; later capture reads
  the real viewport. Selection remains independent.
- [x] Force refresh before/after restore, user scroll before/after restore,
  stale generation, target switch, resize/wrapping and tail pinning. Observe
  applied outcomes, not merely callback invocation. Keep real Textual layout
  and refresh; controlled future delivery is allowed.
- [x] Done: original search jump and user-scroll regression pass with real UI;
  stale callbacks do nothing; independent review passes. Replan if reliable user
  intent cannot be identified without changing the public interaction contract.

### S4 — Diagnose initial DM navigation before selecting a fix

- [x] Instrument the exact initial navigation request/result/application sequence
  for test_direct_message_header_and_composer_use_actor_scoped_label. Record
  request ID, future error or DM targets, generation/stale decision and rendered
  navigation. Keep real TautClient/SQLite/session and navigation worker.
- [ ] Reproduce on focused Windows CI with concurrent suite pressure retained.
  Classify missing source DM, missing callback, stale result rejection or widget
  application failure from positive phase evidence. A timeout stack alone and
  a subsequent green run do not choose a cause.
- [ ] Add the forced-order failing regression at the identified boundary, fix
  that owner, and preserve actor-scoped labels and unrelated navigation entries.
  Record the concrete implementation choice and independent review before its
  code change. If no causal reproduction emerges, this slice and release stay
  blocked; do not modify the later wait and call it resolved.

### S5 — Restore and diagnose native Ctrl-D

- [x] Restore the Windows native branch in the existing terminal test, retaining
  Pilot binding proof separately if useful. Read its imported _terminal_probe
  helper and the Windows Textual input decoder before editing.
- [x] Trace positive readiness, injected representation, decoded event, guarded
  APPLICATION_QUIT and child exit. No fixed sleeps. Distinguish a raw control
  byte from a physical key/negotiated terminal encoding using the actual pinned
  terminal protocol. Record OS build and Textual version with failures.
- [x] No corrective branch was required: the existing raw `0x04` ConPTY input
  decoded as `ctrl+d` and reached guarded quit. The terminal helper now retains
  bounded readiness, input, decode, guarded-action and child-exit evidence on
  failure, while cleanup still reaps the process and handles. The shipped
  launcher, real ConPTY and exit status remain under test.
- [x] Done: Ctrl-C and Ctrl-D both reach guarded quit and exit 0 on native Windows;
  POSIX proof also passes. Unproven EOF explanations, dependency replacement or
  inability to inject valid native input block this slice and require revision.

### S6 — Qualification and documentation

- [x] Update the two implementation notes and 0.9.8 CHANGELOG with actual causes
  and proof. Add this plan's backlinks to the relevant specs' Related Plans
  without changing normative requirements. Record a factual lesson on mistaken
  completion evidence; evaluate existing runbooks/skill for improvement, but no
  new process rule is needed where current rules already cover the failure.
- [ ] Run exact commands below and independent final diff review. Record SHA,
  OS/Python, test counts, elapsed time and failures per qualification run. Compare
  focused/full job times to baseline runs only under matching configurations;
  do not claim speedup from fewer tests or reduced concurrency.
- [ ] Close only after W1–W6 have concrete dispositions and no unresolved native
  qualification. Mark the plan/index complete only after verification and commit.

## Verification Commands and Gates

Per-slice selection uses the existing test files, adding exact new node IDs to
Execution Log when authored. Run changed tests before broad suites.

```sh
uv run --project extensions/taut_summon --extra dev pytest extensions/taut_summon/tests/test_driver.py extensions/taut_summon/tests/test_pty_windows.py -n auto --dist load --tb=short
uv run --project extensions/taut_tui --extra dev --locked pytest extensions/taut_tui/tests -n 2 --dist loadfile --tb=short
uv run ruff check .
uv run ruff format --check .
uv run mypy taut tests
uv run --extra dev mypy extensions/taut_summon/taut_summon extensions/taut_summon/tests extensions/taut_summon/tests/conftest.py --config-file pyproject.toml
uv run --project extensions/taut_tui --extra dev mypy extensions/taut_tui/taut_tui extensions/taut_tui/tests --config-file extensions/taut_tui/pyproject.toml
uv run python bin/check-doc-paths
uv run python bin/check-plan-status-index
uv run pytest tests/test_docs_references.py -q
git diff --check
```

Existing root and every extension's normal CI/static gates remain required;
commands here do not substitute for the full release machinery. Monitor with
`gh run list --commit <sha>` and `gh run view <run-id> --log-failed`.
Use temporary focused diagnostics only on a branch via existing dispatchable
workflows. Restore their full commands before landing. No automatic retry-until-
green: every failure is retained, classified, and dispositioned. Final root and
TUI workflows must be green at the exact release candidate SHA, including native
Windows process tests. The normal release script additionally gates all other
extensions and live local-LLM smoke. Post-publication verification of all five
packages on GitHub and PyPI remains part of the separately authorized release.

## Independent Review Loop

Prefer Claude via skills/call-agent after read-only probe verification. Review
this plan against its baseline, source specs, implementation notes and named
tests. Existence-check paths/seams/commands first. Ask PASS/BLOCKED on confident
implementability and whether execution would degrade robustness. Findings need
IDs, severity, evidence and suggested disposition. Prefer removing unnecessary
work; unrelated baseline concerns are observations unless worsened. No accepted
coverage weakening or timeout/parallelism tradeoffs. Review every meaningful
slice and final diff; scope follow-ups to accepted findings and new regressions.

## Out of Scope and Stop Gates

No new dependency, public CLI/schema, backwards-compatibility layer, canary,
general watcher rewrite, SimpleBroker change, release bypass, wheel rebuild
policy change, or global CI scheduling redesign. A required intended-behavior
change escalates to Class 5: exact spec delta, promotion strategy and independent
review precede implementation. S4/S5 are bounded diagnostic gates, not permission
to guess. The current request produces the plan only, not runtime edits/release.

## Deviation Log

| Spec ref | Planned behavior | Actual behavior | Rationale | Spec proposal |
|---|---|---|---|---|

## Review Log

2026-09-16: Claude 2.1.273, default claude-opus-4-8[1m], read-only via
skills/call-agent; 900-second bound, 290-second completion, exit 0,
success/end_turn, terminal_reason=completed, is_error=false. Verdict PASS.
The review checked owner code, specs, tests and commands. Its summary phrase
"six diagnoses ... verified defect" is interpreted narrowly: W5 and native
W6 causation remain unresolved; only their failing seam/coverage gap is verified.

Verbatim findings and explicit dispositions:

| ID | Severity | Reviewer finding | Disposition |
|---|---|---|---|
| F1 | P2 | The slice's core seam — distinguish user input from programmatic scroll "at the widget/event boundary" across wheel/scrollbar/keyboard — **does not exist yet**. `TautOptionList` has only `on_mouse_down/up/click`, no scroll handling. The cited "existing intent/generation machinery" covers the *restore* side, not user-scroll *detection*; `scroll_to` (`app.py:3519`) is the programmatic path to separate. Least de-risked slice. | Accepted. S3 now requires a disposable real Textual event probe and recorded boundary before production edits; failure triggers revision. |
| F2 | P3 | Ordering window: `_active` is cleared under `_state` (`:173-179`) but `close_handle(thread_handle)` runs *outside* the lock (`:180-181`). A reconciliation loop that only cancels while `self._active is <op>` under `_state` is safe, but I2's "never cancel a released handle" must be asserted, not assumed. | Accepted. S2 explicitly tests post-clear/pre-close and released/reused-handle orderings with identity checked under the state lock. |
| F3 | P3 | Local dev is darwin; native red-before/green-after for W2/W3/W6 is only obtainable on Windows CI. Fake-native (S2) and Pilot tests run locally; the native completion gate depends on CI turnaround. | Acknowledged; existing native completion gates retained. No substitute local pass claimed. |
| F4 | P3 | W1 is a **test-helper** defect (`conftest.stop`), yet the table lists `_driver.py`/`_state.py` under S1 — scope-creep risk into production for a test-only bug. | Existing restriction retained: production driver/state edits require a reproduced additional defect and scope amendment. |

Non-actionable reviewer observations: historical W1 ordering is inferred;
native coverage and concurrency remain mandatory; no normative spec delta is
needed; comprehension questions match owner code. No unrelated expansion added.

Round 2, scoped to accepted F1/F2 only: same read-only invocation, 540-second
bound, 89-second completion, exit 0, success/end_turn, completed. Verdict PASS.
Reviewer: "New-defect check: None." Both added gates were verified against the
owner code; no declined findings were reopened.

TUI slice review found three proof defects before completion: direct observer
invocation did not prove scrollbar movement/preservation; navigation observation
could turn widget-application failure into another timeout; terminal timeout
details were discarded. All were accepted. Tests now post the real scrollbar
message and assert offset/anchor after refresh, navigation application signals
in `finally` while preserving the exception, and the native probe retains its
bounded output evidence. Focused and full TUI gates passed after correction.

The first hosted run at `d7fc067` exposed one remaining proof race in the
action-handler integration test. A navigation refresh could invalidate the
first deferred search-anchor finalizer and schedule its replacement, as the
production generation contract requires. The observer signaled completion when
that stale finalizer was merely invoked, so slower Windows, macOS, and Ubuntu
lanes asserted before the replacement restore completed. The observer now
signals only after the owned state transition has actually cleared the pending
anchor with the requested logical anchor intact. This is a test synchronization
fix, not a timeout or a production serialization change.

The next Windows run at `3e59c87` proved that transition occurred, then exposed
an invalid postcondition in the same test. After ownership release, normal
capture ran before the waiting coroutine resumed. Windows viewport geometry had
clamped the searched row near the bottom, so the real top-visible row was an
earlier message. Requiring the logical search target to remain the anchor after
release would recreate permanent pinning. The integration test now records the
exact successful owner transition, separately proves that the searched row is
visible, and derives the post-release anchor from the rendered viewport.

Summon completed-work review attempt 1: Claude 2.1.273 with read-only
Read/Grep/Glob/Bash access reached its 900-second bound without output or
verdict. The timeout is recorded as reviewer failure, not approval or a product
finding. Per the review fallback, a fresh independent reviewer was dispatched
against the same S1/S2 unit before CI publication.

Fresh S1/S2 review verdict: blocked by S1-B1 and S1-B2; no S2 code blocker.
S1-B1 found that `stop()` wrapped the raw control exception, which already
contained unredacted stderr, before appending its sanitized diagnostic. S1-B2
found that the collision test waited for the final summoned identity log and
therefore did not force the original pre-log race. Both findings were accepted:
sanitize the complete primary error with a real stderr secret fixture, and gate
STOP after session/control readiness but before identity-log publication. The
review also noted the owned-session lookup must receive the remaining aggregate
deadline. Native S2 Windows qualification remains required.

Round 2 scoped to S1-B1/S1-B2 and the aggregate deadline: PASS. The complete
primary exception and assembled diagnostic are sanitized; the regression puts
a distinctive token in real child stderr and proves both it and the session
token absent. The fallback child blocks at the exact pre-identity-log boundary
after control readiness, STOP runs while log identity is unavailable, and the
competitor answers PING before and after only the fallback exits. One monotonic
deadline now supplies remaining budgets throughout. No new blocker found.

## Execution Log

- 2026-09-16: Planning only. CI logs and controlled reproductions from diagnosis
  underpin W1–W6; native Windows qualification is explicitly outstanding.
- 2026-09-16 pre-edit comprehension gate: (1) no, the session row precedes
  provider/control/watch readiness; (2) no, `_active` is published before
  native `WriteFile`; (3) no, scrolling can leave message selection unchanged
  while the first visible row moves. All three match the plan's expected answers.
- Planning verification: check-doc-paths passed (1,417 claims),
  check-plan-status-index passed, tests/test_docs_references.py passed (12 tests),
  git diff --check passed, and all 36 literal plan file paths exist. These are
  documentation checks, not runtime qualification. Existing testing/review
  guidance already covers the exposed errors; no skill/runbook change proposed.
- S1 RED: the exact-owner regression failed because `DriverProcess` lacked an
  owned-member seam. GREEN: both new forced-order tests passed; full
  `test_driver.py` passed 144 tests under `-n auto --dist load`. The harness now
  binds PID/start evidence to one session, PING-fences readiness, targets STOP
  by member id, leaves failed graceful stops to cleanup, and redacts diagnostics.
- S2 RED: both pre-native-I/O handoff cases left the writer live before the
  reconciliation change. GREEN: platform-neutral Windows PTY tests passed 33
  with 6 native skips. Exact-operation cancellation now spans ERROR_NOT_FOUND,
  successful-but-incomplete cancellation, active retirement, and handle reuse
  under the original deadline. Native Windows qualification remains open.
- S3 probe on retained Textual 8.2.8: programmatic `scroll_to(y=10)` invoked only
  the method; wheel reached `on_mouse_scroll_down`, PageDown the key path, and a
  real child-scrollbar `ScrollTo` reached `on_scroll_to`. GREEN: actual viewport
  offset/anchor and refresh preservation pass for all three input paths. The
  permanent protected anchor was removed.
- S4 exact-event diagnosis passed 20/20 locally: the navigation future returned
  a snapshot containing the DM and application rendered it. No causal product
  defect reproduced, so production navigation code was not changed. Windows
  qualification with the phase evidence remains open.
- S5 restored the shipped native Ctrl-D path and retained the Pilot binding
  proof. Pinned Textual parsed raw `0x04` as `ctrl+d` locally; native POSIX
  Ctrl-C/Ctrl-D pass. Windows ConPTY qualification remains open.
- Integrated local gates: Summon driver plus Windows PTY tests passed 177 with
  6 native skips in 21.98 seconds under `-n auto`; retained TUI passed 462 in
  123.32 seconds under `-n 2 --dist loadfile`; Ruff and format were clean;
  Summon and TUI mypy gates passed. These do not substitute for hosted Windows.
- Hosted qualification at `63269053dc2e482bddddb2d137e0e2d8981344f4`:
  root Test run 35162150704 passed all 23 jobs. Its native Windows 3.11 Summon
  process lane passed 246 tests in 205.22 seconds, and Windows 3.11/3.12/3.13/
  3.14 unit lanes each passed all 310 Summon tests. TUI run 35162150661 passed
  all five retained-lock jobs with two workers: Windows 3.13 passed 462 tests
  in 232.45 seconds; Ubuntu 3.11/3.13/3.14 passed 462 in 114.48/112.36/126.39
  seconds; macOS 3.13 passed 462 in 107.06 seconds. MCP run 35162150683 and
  PostgreSQL run 35162150649 also passed. This qualifies S2 and S5 without
  timeout growth, reduced parallelism, skipped assertions or ignored failures.
- S4 remains deliberately open. Its exact navigation future/snapshot/application
  instrumentation passed locally and in the concurrent Windows TUI lane, so the
  earlier missing-DM failure did not recur with phase evidence and no production
  owner can honestly be selected. Per the S4 gate, this is an unresolved causal
  diagnosis, not permission to call a longer/event-based wait the fix.
- Comprehension answers, red/green commands, slice reviews and final SHA evidence
  are required here during implementation; no implementation completion claimed.
- 2026-09-25: S4 diagnosis ownership transfers to
  `docs/plans/2026-09-24-windows-tui-determinism-root-cause-plan.md` on the
  owner's implementation direction. The successor retrieved the original
  W5 failure and confirmed that it contains only attempt-count exhaustion,
  not source/future/application phase evidence. S4 and this predecessor
  remain open. Transfer does not waive the causal closure/release gate;
  neither a replacement wait nor a passing soak supplies the missing cause.

## Fresh-Eyes Check

Owner boundaries, cancellation-before-I/O, user-scroll supersession, cleanup on
failed probes, diagnostic redaction, and unresolved-cause gates are explicit.
Planning verification uses doc/path/status checks; runtime gates belong to the
implementation phase. No spec delta is proposed because the fixes restore the
existing contracts.
