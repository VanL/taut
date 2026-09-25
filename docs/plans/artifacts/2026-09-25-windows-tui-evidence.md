# Windows TUI Historical Evidence Audit

Date: 2026-09-25
Implementation baseline: `33205d797814da07071bbe27d2336a057e233b8c`.
Owner: implementing engineer for
`docs/plans/2026-09-24-windows-tui-determinism-root-cause-plan.md`, slice 1.
Boundary: read-only retrieval of historical Actions logs and metadata, remote
tag checks, and inspection of local commits and supporting records. This
artifact neither dispatches CI nor claims a new reproduction or qualification.

## Method and availability

Retrieved the cited runs with `gh run view --repo VanL/taut`, using JSON
metadata and full or failed-step logs. Enumerated the TUI workflow history for
2026-09-16 through 2026-09-24; inspected failure logs throughout the 0.9.9
streak. Inspected the correction commits with `git show`, the current test
seams, the predecessor plan, and the deep-dive review artifact. Verified the
two release tags against the remote with `git ls-remote origin`.

The Actions API reports zero uploaded artifacts for runs `35917159249`,
`35918083458`, `35928843388`, and `35162150661`. Their textual logs remain
available. No per-phase timing, native cancellation record, or captured-byte
artifact was recovered from those runs. Absence of those records limits
causal attribution; it does not make the textual failure logs unavailable.

## Revalidated evidence register

| Plan evidence | Verified observation and qualification | Source |
|---|---|---|
| E1 | Initial preparation SHA `3993e206e9ed4938496d85f10376081df873a8cf` failed only the Windows TUI matrix entry. Seven TUI fix-forward commits span `d7e056a` through `583038e`. The first all-five-entry green was `583038e`; the final release SHA was `c8940596d93bbc3ba16e86e08f962ffc32966723`. Both remote tags, `v0.9.9` and `taut_tui/v0.9.9`, point to that final SHA. The interval between initial and final run creation was 1 h 54 m 41 s (20:37:07 to 22:31:48 UTC), not approximately three hours. The tag targets were checked; the release helper's internal execution was not separately audited. | [Initial run](https://github.com/VanL/taut/actions/runs/35917159249), [first green](https://github.com/VanL/taut/actions/runs/35927108722), [release green](https://github.com/VanL/taut/actions/runs/35928843388), remote tag refs. |
| E2 | The two cited early runs both failed recovery at `test_tui_summon.py:2017`, helper `:1749`, with `timed out waiting for post-recovery orientation injection`. The second also failed the exact search selected-message assertion. Later streak failures changed phase and included additional tests, listed below. These timeout traces alone identify the unmet oracle, not its cause. | [Run 35917159249](https://github.com/VanL/taut/actions/runs/35917159249), [run 35918083458](https://github.com/VanL/taut/actions/runs/35918083458). |
| E3 | Real controller, provider process, host terminal, and app boundaries are present. The statement that only `suspend()` is faked is stale: `_gate_app` also intercepts `TerminalLeaseRequest` and invokes its real `hold()` method on a checked harness thread. Terminal suitability/fds are adapted, and the real provider fixture receives explicit settle settings. These are harness seams, not replacement broker/controller implementations. | `extensions/taut_tui/tests/test_tui_summon.py`: `_configure_gate_pty`, `_gate_app`, `_prepare_gate_recovery`; [5fcf32c](https://github.com/VanL/taut/commit/5fcf32c). |
| E4 | `583038e` replaces numeric thread authority with a per-operation opaque token. Its new test holds the confirmation thread alive while a distinct lease thread acts. The code and regression provide structural evidence for the ownership defect. The historical failing log itself does not record thread identities, so its exact interleaving remains inferred. | [583038e](https://github.com/VanL/taut/commit/583038e), setup-recovery plan's release-hardening correction. |
| E5 | `d7e056a` adds the stale-highlight guard while a pending search anchor owns selection. The preceding run contains the exact wrong selected-message assertion. This supports the defect class; a forced event-delivery test and narrow mutation provide the plan's required causal regression proof. | [d7e056a](https://github.com/VanL/taut/commit/d7e056a), [run 35918083458](https://github.com/VanL/taut/actions/runs/35918083458). |
| E6 | The named corrections exist, but their evidence has different strength. Missing mounted controls and premature focus assertions are directly observed. Cross-run cancelled-I/O leakage and wrong deadline origin are supported by the code changes and contemporaneous explanations, without retained native/phase measurements establishing that they caused the historical failures. The headless-loop mismatch is present in the code; historical traces do not prove every earlier timeout reached that mechanism. | Correction audit and streak observations below. |
| E7 | At `c894059`, all five entries ran 477 tests with `-n 2 --dist loadfile`. Windows 3.13 took 258.51 s; Ubuntu 3.13 took 137.63 s, a ratio of approximately 1.878. No skips were reported. These are suite durations, not a measured infrastructure or behavior phase factor. | [Run 35928843388](https://github.com/VanL/taut/actions/runs/35928843388); full matrix below. |
| E9 | Original W5 run `35145237393` at `3e454094a76d434fe7e44cb2c2117f3003606839` failed the first DM-entry wait at `test_tui_app.py:2162`, helper `:37`, with `condition did not become true`. The failure includes no source membership, snapshot, future outcome, generation, or application record. | [Original W5 run](https://github.com/VanL/taut/actions/runs/35145237393), original test source at `3e45409`. |
| E9 follow-up | `6326905` passed 462 tests in all five TUI matrix entries. The predecessor records 20/20 local exact-event passes and explicitly keeps S4 unresolved. The enumerated hosted history through 2026-09-24 has no later S4 failure. Passing observations do not establish the original cause. | [Run 35162150661](https://github.com/VanL/taut/actions/runs/35162150661), `docs/plans/2026-09-16-windows-lifecycle-determinism-plan.md` Execution Log. |

## 0.9.9 streak observations

Times below are pytest suite durations reported by the affected job, not
per-test or phase timings. All failures listed are Windows 3.13 unless the
row says otherwise. A diagnostic field names what the observer saw; it is
not automatically the failing owner.

| Run | SHA | Observed failures / result |
|---|---|---|
| [35917159249](https://github.com/VanL/taut/actions/runs/35917159249) | `3993e206e9ed4938496d85f10376081df873a8cf` | Recovery orientation oracle timeout. 1 failed, 473 passed in 303.64 s. Other four matrix entries green. |
| [35918083458](https://github.com/VanL/taut/actions/runs/35918083458) | `15e3fd1227d27f1c13fd8ab296d13d0683109d9e` | Same recovery timeout; `test_every_action_reaches_a_concrete_handler[search.open-result]` found the wrong `selected_message_id` at `test_tui_action_handlers.py:650`. 2 failed, 472 passed in 366.99 s. Other four matrix entries green. |
| [35919709613](https://github.com/VanL/taut/actions/runs/35919709613) | `d7e056a49bf0462800687f293097c6e8269549f7` | Recovery orientation timeout remained after host-terminal isolation and search guard changes. 1 failed, 474 passed in 333.88 s. |
| [35920877370](https://github.com/VanL/taut/actions/runs/35920877370) | `ea483951a1ec5cf866fe66ac8f7a1dc8c4c1705f` | Windows recovery reported that the gate menu never reached the leased terminal: 1 failed, 474 passed in 240.23 s. Ubuntu 3.11 separately failed `test_reply_markers_and_close_restore_conversation_focus` because `transcript.has_focus` was false: 1 failed, 474 passed in 176.14 s. |
| [35922875491](https://github.com/VanL/taut/actions/runs/35922875491) | `c53ddcaacedeaad0910a577438428fa4a6377752` | After the generation-based deadline change, recovery still reported no gate-menu output (`b''`). 1 failed, 474 passed in 272.64 s. |
| [35923841280](https://github.com/VanL/taut/actions/runs/35923841280) | `d41242ae0da984d522c3a57f016a880975a31d99` | Recovery timed out on terminal-answerer completion; answerer stage was `waiting for terminal lease`, with no answerer failures. Provider log had two start/menu pairs. `test_host_shutdown_during_offer_spawns_nothing_further` also timed out on wiring-run orientation injection. 2 failed, 473 passed in 275.82 s. |
| [35925072346](https://github.com/VanL/taut/actions/runs/35925072346) | `5fcf32c9fc11d6b5dda3d0a0007eb7bad1efa77d` | Recovery failed with `textual.pilot.OutOfBounds`. `test_every_action_reaches_a_concrete_handler[system.dump]` failed because `#confirmation-cancel` did not exist on the confirmation screen. 2 failed, 473 passed in 320.62 s. |
| [35926016403](https://github.com/VanL/taut/actions/runs/35926016403) | `88a2f40e43a7b3fef750423fbaa591dd506ad1fe` | Recovery again timed out on terminal-answerer completion while `waiting for terminal lease`; no answerer failures; two provider start/menu pairs. 1 failed, 474 passed in 237.32 s. |
| [35927108722](https://github.com/VanL/taut/actions/runs/35927108722) | `583038ee17bf79420470f94dec66e5f66e5b50fb` | First subsequent all-five-entry green, after per-run terminal ownership. |
| [35928223960](https://github.com/VanL/taut/actions/runs/35928223960) | `1ad4630585f3e5b58e68f17709766d02d7a007fc` | Workflow green after Ruff inventory refresh. |
| [35928843388](https://github.com/VanL/taut/actions/runs/35928843388) | `c8940596d93bbc3ba16e86e08f962ffc32966723` | All five entries green at the release-tag SHA; counts and durations below. |

The seven TUI fix-forward commits are `d7e056a`, `ea48395`, `c53ddca`,
`d41242a`, `5fcf32c`, `88a2f40`, and `583038e`. The intervening `15e3fd1`
changed MCP test paths; subsequent `1ad4630` refreshed the Ruff suppression
inventory and `c894059` synchronized PostgreSQL MCP owner retirement.

## Correction audit: what each commit establishes

- [d7e056a](https://github.com/VanL/taut/commit/d7e056a) gives wiring and
  recovery distinct host-terminal sessions and documents cancelled-I/O/reset
  leakage as the rationale. Its Windows recovery test remains red. There is
  no retained native cancellation or old-byte record proving that specific
  leakage mechanism. Preserve the isolation and execute the planned native
  proof before treating the mechanism as reproduced.
- [c53ddca](https://github.com/VanL/taut/commit/c53ddca) starts the answerer's
  provider-output wait after the recovery generation appears and includes
  committed focus in the reply-close test's predicate. The old deadline
  origin is visible in code; the hosted logs do not measure setup duration
  separately from behavior. The focus failure is directly observed on
  Ubuntu, rather than being Windows-specific.
- [d41242a](https://github.com/VanL/taut/commit/d41242a) changes that deadline
  origin again, from generation start to **terminal lease acquisition**.
  E6(b)'s generation wording describes an intermediate state, not the final
  correction. The subsequent timeout waits for the lease itself, supporting
  the need for separate phase diagnostics without choosing its cause.
- [5fcf32c](https://github.com/VanL/taut/commit/5fcf32c) intercepts only the
  unsupported headless lease body, runs it on a checked harness thread, and
  joins that thread. Production deliberately blocks Textual during the
  terminal lease. The code change repairs a harness mismatch; it does not
  imply production should process confirmation messages while suspended.
- [88a2f40](https://github.com/VanL/taut/commit/88a2f40) waits for mounted
  confirmation controls in action-handler tests. In the recovery test it
  reverts pilot clicks to the screen's `action_confirm()` rather than adding
  the same control-mount wait. The immediately preceding missing-node and
  out-of-bounds failures are direct evidence for readiness defects.
- [583038e](https://github.com/VanL/taut/commit/583038e) scopes terminal
  authority to a logical run. Keeping the first phase thread alive makes
  the regression force distinct thread identities; thread-ID reuse had
  masked the old bug. This is the first all-five-job green in the streak.
  The plan's narrow mutation should preserve that forced ordering.

## Retained matrix results

Both runs below invoke the full TUI suite with the retained lock and
`-n 2 --dist loadfile`. Every row reports all tests passed and no skips.

| Platform / Python | Release `c894059`, run 35928843388 | S4 follow-up `6326905`, run 35162150661 |
|---|---|---|
| Windows / 3.13 | 477 passed, 258.51 s | 462 passed, 232.45 s |
| Ubuntu / 3.11 | 477 passed, 135.18 s | 462 passed, 114.48 s |
| Ubuntu / 3.13 | 477 passed, 137.63 s | 462 passed, 112.36 s |
| Ubuntu / 3.14 | 477 passed, 133.80 s | 462 passed, 126.39 s |
| macOS / 3.13 | 477 passed, 136.25 s | 462 passed, 107.06 s |

Run links: [release matrix](https://github.com/VanL/taut/actions/runs/35928843388),
[S4 follow-up matrix](https://github.com/VanL/taut/actions/runs/35162150661).
The full follow-up SHA is `63269053dc2e482bddddb2d137e0e2d8981344f4`.

## S4 disposition and remaining evidence limits

**Cause unresolved.** The original
[run 35145237393](https://github.com/VanL/taut/actions/runs/35145237393)
at `3e454094a76d434fe7e44cb2c2117f3003606839` recorded 3 failed and
454 passed in 486.36 s on Windows. Besides the DM-entry wait, the failures
were native Ctrl-D's missing `GUARDED-QUIT` and the search scroll-anchor
assertion. No phase evidence joins those failures into one cause.

The original DM test commits the DM before constructing the real app and
then waits for a non-general string in `_navigation_targets`. The old helper
performs 100 `pilot.pause(0.01)` attempts and fails without retaining the
navigation snapshot, worker outcome, callback delivery, or widget-apply
decision. This proves an unmet first-navigation oracle and a finite-attempt
harness shape. It does not prove whether the historical fault was in source
membership, worker completion, callback delivery, stale-generation policy,
widget application, or observation timing.

The predecessor's Execution Log records 20/20 local passes after exact-event
instrumentation and explicitly declines to select a production owner. The
hosted follow-up at `6326905` is green. Workflow enumeration from that run
through 2026-09-24 returns 13 runs: the two September 16 greens (`35162150661`
and `35163175582`) and the 11 September 23 runs above. The available failure
logs show no S4 recurrence in that interval. This bounds observed history,
not all later or future executions.

The deep-dive review artifact
`docs/plans/artifacts/2026-09-23-deep-dive-review.md` says macOS at 6×
oversubscription did not reproduce S4 and calls attempt-count polling a
likely cause. It does **not** contain the plan's asserted 40 ms median or
280 ms maximum. A search of tracked docs found those numbers only in this
plan. They are not independently recoverable measurements and must be
removed from the verified evidence or labeled as an unverified historical
claim until the original samples are supplied.

No soak or synthetic boundary mutant in this audit establishes the historical
S4 cause. Its causal-reproduction gate remains open under the inherited plan.

## Native diagnostic measurement, before wait migration

[Run 36144544513](https://github.com/VanL/taut/actions/runs/36144544513),
attempt 1, dispatched with one repetition at immutable SHA
`3f0c4116764a904639d432ec971a2d53360b4067`, retained `-n 2 --dist loadfile`.
Windows Server 2025 / Python 3.13.15 completed 575 cases: 574 passed, one
failed, zero skips, 329.223 s. The failure is the separately reproduced
search-observer false positive, corrected afterward at `53ea080`; this run
is not green qualification. All other matrix jobs failed that same oracle.

The [Windows artifact](https://github.com/VanL/taut/actions/runs/36144544513/artifacts/10868588919)
contains all 575 phase files. Direct invocation of the recorder's
`phase_evidence` validator accepts them, including same-owner source/apply,
two provider consumption/close identities, lease restoration, and native
attach retirement. The full repetition verifier correctly remains red for
the failing test. Local artifact copy:
`/tmp/taut-tui-native-measurement.sl0VEA`.

Raw same-owner durations below are in seconds; each cell is the complete
sample, **n = 1** for each named flow. No percentile or reliability inference
is warranted. The navigation row is the S4 DM test, not aggregate app latency.

| Phase | Windows 3.13 | Ubuntu 3.11 | Ubuntu 3.13 | Ubuntu 3.14 | macOS 3.13 |
|---|---:|---:|---:|---:|---:|
| S4 navigation request → source | 0.099777 | 0.075002 | 0.075734 | 0.070454 | 0.039570 |
| S4 source → application | 0.002856 | 0.001452 | 0.001675 | 0.001522 | 0.001043 |
| Recovery navigation request → source | 0.088571 | 0.077448 | 0.079769 | 0.087321 | 0.038673 |
| Recovery source → application | 0.002602 | 0.001583 | 0.001537 | 0.002303 | 0.055969 |
| Confirmation request → resolution | 0.093899 | 0.081771 | 0.103723 | 0.081408 | 0.335962 |
| Lease request → acquired | 0.000725 | 0.000285 | 0.000443 | 0.000310 | 0.000435 |
| Lease acquired → restored | 0.046080 | 0.048652 | 0.027320 | 0.025266 | 0.177700 |
| Lease restored → hold returned | 0.000569 | 0.004999 | 0.000184 | 0.000081 | 0.000465 |

Windows wiring/recovery provider `inject()`-return-to-consumption differences
are 0.001668 / 0.000689 s (two distinct providers, one observation each).
These are **not orientation durations**: consumption may precede injection
return (the macOS wiring sample is −0.000155 s). The acknowledgement proves
consumption after fixture logging; no timestamp is backdated to an unobserved
orientation start. Actual behavior deadlines must start at that owner handoff
in the migration adapters, not at the late await or injection return.

The Windows recovery test lasted 18.090601 s. Its wiring provider/host closed
at relative 6.492895/6.623543 s; recovery confirmation was requested at
12.530803 s, readiness applied at 12.940399 s, final provider close occurred
at 17.972054 s, and foreground return applied at 18.072655 s. Native attach
cleanup returned at 1.308376 and 12.857025 s. These are raw transition times,
not isolated process-bootstrap or close-call costs. They cannot justify
charging bootstrap/cleanup against a UI application deadline.

### Proposed conversion caps for model review

No TUI CI scaling seam exists and this sample supplies no reason to invent
one. Every existing explicit call-site cap wins, whether smaller or larger
than a proposed default; no existing explicit behavior cap changes.
Infrastructure and cleanup
remain source-specific rather than receiving a blanket Windows multiplier.

| Inventory group | Deadline owner and cap | Rationale / containment boundary |
|---|---|---|
| App navigation, conversation, delivery, action, render, focus, search, resize | Preserve each explicit call-site limit from its initiating action/request. Use 5 s only for formerly counted waits with no explicit elapsed limit. | Preserve the app's explicit 5 s baseline. For formerly counted action/routes/inline waits this is a newly explicit limit, not a claimed conversion of attempts × pause. The measured real navigation/application samples are far below it; action-specific firing and hosted tests still qualify other phases. |
| Pure confirmation decision formerly 200 attempts | 2 s from resolve/decision handoff | Makes the previously ambiguous count explicit at the neighboring confirmation protocol's existing 2 s limit; native request/resolution sample is 0.093899 s. No provider startup is charged here. |
| Existing Summon confirmation/offer/acknowledgement | Preserve 2 / 45 / 10 s at each existing call site, from its real initiating action | The recovery offer's 45 s remains end-to-end from owned-run start, including its setup. Do not move its start to the offer or add a second 45 s allowance. |
| Existing provider/orientation and foreground outcomes | Preserve wiring orientation's 30 s; recovery orientation and normal outcomes' 45 s; declined return's 90 s, at their actual phase handoffs | Await consumption rather than file polling; preserve driver-ready versus app-ready identity. Injection return is not a valid new deadline origin. |
| Framework app/control readiness | Retain real `run_test` / `AwaitMount` ownership and the existing Pilot screen fence (30 s), separately from worker/application handles | `run_test` waits for its startup callback before yielding. That initial framework wait has no separate timeout; the unchanged Actions step remains outer containment. Do not claim the 30 s screen fence bounds earlier startup, or cancel shared framework futures to impose a new cap. Control operations with explicit 2/5/10 s limits retain those. |
| Native/process infrastructure and retirement | Preserve each existing source cap: terminal reads 15 s, provider/worker futures 5/30/60 s as currently named, joins 2/5/15/20 s as currently named | These are resource-owner containment limits, not behavior allowances. The exact inventory call site wins over this summary. Stop first, then await/join the actual owner. Each Windows repetition retains the 20-minute outer Actions cap. |

The model's budget firing pair must still show delayed setup followed by
timely behavior succeeds, while late behavior fails at the unchanged deadline.
The sample neither proves these caps sufficient under every schedule nor
closes S4. Conversion may proceed only after scoped model/cap review.

## Diagnostic 3: foundation, action/Summon migration and native probes

[Run 36149242970](https://github.com/VanL/taut/actions/runs/36149242970),
attempt 1 at `d2ffea525c5c93a41004ba4a3c0ba6324a01be45`, ran one repetition,
not the five-run qualification. All four non-Windows jobs passed 681 tests
with two declared native-only skips. Their JUnit durations were 143.807 s
(Ubuntu 3.11), 141.496 s (Ubuntu 3.13), 142.785 s (Ubuntu 3.14), and
149.792 s (macOS 3.13).

Windows passed 682 and failed one of 683 tests in 306.678 s, with zero skips.
The quiet native process-exit probe passed. The new cross-run isolation
probe timed out at `host.chat` on its first provider, before cancellation or
recovery. It therefore supplies no cancelled-I/O or isolation qualification.
This timeout alone does not classify a product defect.

The probe required a trailing blank after `chat>`, unlike the established
native harness reader's stable `chat>` token. A portable split-chunk prompt
without padding fires the same observer timeout and passes after matching
the stable token. This corrects an overly strict test observer; it remains
a candidate explanation for the hosted failure because raw host bytes were
not retained. The next run adds content-free byte-count/token/retirement
diagnostics and must reach actual cancellation before claiming that proof.

All phase files validate directly: 683 Windows and 681 in each other lane.
The full repetition verifier correctly rejects Windows for the failing test.
[Windows artifact](https://github.com/VanL/taut/actions/runs/36149242970/artifacts/10870697765).
Local copy: `/tmp/taut-tui-native-diagnostic3.iK5xYU`.
