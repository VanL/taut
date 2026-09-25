# TUI determinism elicitation results

Status: slice-2 portable proof checkpoint; native qualification and S4 closure
remain open. Owner: Windows TUI determinism plan implementer. Boundary:
source-owned test observations over real app/session/framework/lease work.
Required action: complete native execution and integration review,
then run the unchanged full retained suite five times on one Windows job/SHA.

## Portable proof register

| Class | Real boundary and forced ordering | Observed red | Current green / limitation |
|---|---|---|---|
| (a), run ownership | Existing `test_terminal_lease_ownership_survives_distinct_driver_phase_threads` retains the confirmation thread while another real thread leases under the same operation. | In a copied product package, replace operation-token authority in confirmation/lease with `threading.current_thread()`. The later lease raises “not acknowledged by this worker”; `leased.is_set()` fails. | Original scoped authority passes. No thread-id reuse is awaited or assumed. |
| (b), headless loop blocking | `_lease_probe_child.py` uses the real recovery app fixture and real `TuiSummonInteraction`. Confirmation precedes lease acquisition. | Select the mutant that posts the blocking body onto Textual instead of the existing headless lease thread. Flushed file contains exactly `confirmed`, `acquired`; pilot release never runs. Parent watchdog terminates and reaps that exact child. | Correct fixture additionally records pilot release, restoration and retirement; all lease/foreground owners join. Two parent cases pass. Production's intentional UI suspension is unchanged. |
| (c), counted liveness | Hold real SQLite navigation worker return, then hold real owner application. Run the retired 200-attempt `Pilot.pause(0.01)` observer with only this Pilot's yield seam controlled. | Its original “condition did not become true” failure occurs while the same five-second absolute deadline is still live. | Release real application and await its pre-registered completion under that same deadline; committed DM and real option label render. This proves a harness class, not historical S4. |
| (d), deadline origin/reset | Real serialized client bootstrap and navigation read are held at separate barriers; only the observer clock advances. | Charging behavior from setup origin fails at `navigation.read`; resetting the deadline after progress lets late behavior through and fails the required timeout assertion. | Timely behavior after slow setup passes; late behavior fails without cancelling its real future. Actual session cleanup still retires the worker. |
| (e), mount/focus | Real Textual mount and focus policy handlers are held while the screen/widget already exists. | Publishing mount at object creation fails the pending-mount assertion. Looking up lifecycle after an old held focus handler wrongly completes a repushed screen's new generation. | Ten framework tests cover actual input after readiness, pop-before-ready, generation reuse, errors, and cleanup. Separate result/removal mutation fails the held-retirement assertion (M3). |
| (g), stale UI event | Queue a real old `OptionHighlighted`, arm search ownership before yielding, then let the actual Textual dispatcher deliver it. | Remove the current `viewport.search_owned` guard in a copied product package: selected message becomes 3 instead of exact hit 2. | Current guard preserves selected hit, viewport anchor and search owner. |
| S4 boundary diagnostics | DM is committed using real `TautClient` before the real session snapshot. Source read, future return, queued callback, owner application and actual widget option are separately observed. | Drop source membership: “source missing committed DM”. Raise after real read: original `ValueError` from the source future. Drop owner application: `navigation.applied` timeout. Clear actual options after apply: “rendered DM row missing”. | Two held-order variants pass. Navigation has no generation field or rejection guard; conversation/search own those contracts. These mutations distinguish diagnostic boundaries but do not establish S4's historical schedule or cause. |
| S4 ordering / real generation boundary | Hold the real older SQLite navigation worker, then submit a newer read. Separately hold older/newer real navigation UI callbacks and apply newer first. Commit the DM before both reads. At the actual search generation boundary, hold two real SQLite search callbacks and deliver old after new. | Increasing the actual session executor to two workers breaks the assertion that the newer request cannot run while the older worker is held. Removing the real search-generation guard replaces the newest DM result with the old channel hit. | Three real-source tests pass in `test_tui_navigation_ordering.py`. Navigation workers are serialized and navigation callbacks have no generation guard: both snapshots contain the committed DM, which survives both callback orders. Actual search generation rejection preserves the newest DM and its rendered label. These exercised schedules do not identify historical S4. |

The portable probe files are
`extensions/taut_tui/tests/test_tui_determinism_probes.py`,
`extensions/taut_tui/tests/test_tui_lease_probe.py`, and
`extensions/taut_tui/tests/_lease_probe_child.py`. A separate-role reviewer
ran all seven cases and found no new P1–P3 blocker, then rechecked the (c)
correction against the unchanged retired observer body. Scoped Ruff and mypy
pass. The foundation's independent review and 82-case verification are in
the main plan.

## Native probe checkpoint (not native qualification)

`extensions/taut_tui/tests/test_tui_native_determinism.py` covers three
Windows-only executions. Quiet natural exit must publish status 7 after real monitor retirement
and before the output drain starts; only then may the one event consumer run.
The two-provider case retains actual host terminals, log paths and provider
creation identities, leaves first-run echo/reset bytes unread, and checks
second-run input/output isolation after both attach readers retire.

The isolation case now has an explicit reused-host fixture mutant. It runs
both real providers and requires actual cancellation evidence before checking
the expected semantic failure: the first run's unread tagged bytes appear in
the second run's host output. Only that exact isolation assertion is caught;
source errors, missing cancellation and teardown failures remain failures.
Local checks report three Windows skips with this parametrization. The hosted
diagnostic at `d2ffea5` predates it and exercises only the two positive cases.

The cancelled-read probe records the exact session, duplicated input handle
and retained reader object. It holds cleanup until the reader reaches its
next read after detach, but does not treat entry as pending I/O. Qualification
requires both a real successful cancellation and matching
`ERROR_OPERATION_ABORTED`, plus reader retirement. A clean retirement without
those events is explicitly “native cancellation proof not established”, not
a diagnosed product defect. There is no OS polling or repeated cancellation.

Main source review checked real read/write/cancel delegation, single-reader
ownership, bounded records and teardown. An independent separate-role review
of the reused-host addition found no P1–P3 issue and confirmed that the exact
cancellation and retirement checks remain outside the expected-failure block.
Local Ruff/mypy pass. Exercises with the existing fake Win32 API
validate callback wiring through real monitor/attach owner code only. A
deferred-publication mutant failed the pre-drain exit-publication assertion
there, but actual ConPTY qualification and the native reused-host mutation
remain open. No new quiet-exit defect is diagnosed, so row (h) requires
native lifecycle qualification rather than inventing a new causal correction.
The next hosted dispatch is a one-repetition diagnostic, not the five-run
acceptance attempt.

## Mutation reproduction notes

Scratch copies, not the working product, were modified. At this checkpoint
the local evidence directories are `/tmp/taut-screen-mutations.QcT2L2` and
`/tmp/taut-owner-mutations.kMoxCS`. They are temporary convenience, not the
durable authority. Reproduce from the named tests by making the single
boundary changes in the table. Run with the extension's locked environment;
the mutation must fail the named semantic assertion, not import or collection.
The source/application/widget variants each fired on both navigation variants.
The wrong-origin mutant failed both budget variants; the reset mutant wrongly
passed late work and failed its `pytest.raises(CompletionTimeout)` assertion.

No production behavior correction is justified by these synthetic S4
mutations. Native cancelled-I/O/ConPTY evidence and the complete five-run
acceptance attempt are still required. A green soak cannot manufacture the
missing cause or owner acceptance.
