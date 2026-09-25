# TUI determinism elicitation results

Status: slice-2 proof register; five-run qualification and S4 closure remain
open. Native diagnostic execution is recorded below. Owner: Windows TUI
determinism plan implementer. Boundary:
source-owned test observations over real app/session/framework/lease work.
Required action: finish current-tree integration, then run the unchanged full
retained suite five times on one Windows job/SHA.

## Portable proof register

| Class | Real boundary and forced ordering | Observed red | Current green / limitation |
|---|---|---|---|
| (a), run ownership | Existing `test_terminal_lease_ownership_survives_distinct_driver_phase_threads` retains the confirmation thread while another real thread leases under the same operation. | In a copied product package, replace operation-token authority in confirmation/lease with `threading.current_thread()`. The later lease raises “not acknowledged by this worker”; `leased.is_set()` fails. | Original scoped authority passes. No thread-id reuse is awaited or assumed. |
| (b), headless loop blocking | `_lease_probe_child.py` uses the real recovery app fixture and real `TuiSummonInteraction`. Confirmation precedes lease acquisition. | Select the mutant that posts the blocking body onto Textual instead of the existing headless lease thread. Flushed file contains exactly `confirmed`, `acquired`; pilot release never runs. Parent watchdog terminates and reaps that exact child. | Correct fixture additionally records pilot release, restoration and retirement; all lease/foreground owners join. Two parent cases pass. Production's intentional UI suspension is unchanged. |
| (c), counted liveness | Hold real SQLite navigation worker return, then hold real owner application. Run the retired 200-attempt `Pilot.pause(0.01)` observer with only this Pilot's yield seam controlled. | Its original “condition did not become true” failure occurs while the same five-second absolute deadline is still live. | Release real application and await its pre-registered completion under that same deadline; committed DM and real option label render. This proves a harness class, not historical S4. |
| (d), deadline origin/reset | Real serialized client bootstrap and navigation read are held at separate barriers; only the observer clock advances. | Charging behavior from setup origin fails at `navigation.read`; resetting the deadline after progress lets late behavior through and fails the required timeout assertion. | Timely behavior after slow setup passes; late behavior fails without cancelling its real future. Actual session cleanup still retires the worker. |
| (e), mount/focus | Real Textual mount and focus policy handlers are held while the screen/widget already exists. | Publishing mount at object creation fails the pending-mount assertion. Looking up lifecycle after an old held focus handler wrongly completes a repushed screen's new generation. | Ten framework tests cover actual input after readiness, pop-before-ready, generation reuse, errors, and cleanup. Separate result/removal mutation fails the held-retirement assertion (M3). |
| (g), stale UI event | Queue a real old `OptionHighlighted`, arm search ownership before yielding, then let the actual Textual dispatcher deliver it. | Originally, removing the `viewport.search_owned` guard changed selected message from hit 2 to 3. Class (i) replaces that narrow guard with source invalidation; the retained `search-input-invalidation` mutant now removes invalidation at search arming and produces the same semantic failure. | The current source owner preserves selected hit, viewport anchor and search owner. No obsolete renderer path is reintroduced merely to keep the old hunk mutant. |
| (i), render/input selection ownership | Release a held real resize after actual activation is posted; drive Home and single-click. Hold real key application across newer input and an intervening render. Admit queued message input before holding application across shifted, removed and other-thread rows. | Original render feedback overwrites the clicked row. The first reconciliation fix lost a third Down action (SEL-1). Current scratch mutants re-enable actual render input admission, discard pending source projection, use row index or omit thread identity, or overwrite an absent search hit with a default. | Real input and rendering remain on Textual. Nineteen portable semantic mutants include these five new corrections and the replaced (g) mutation. Activation commands still execute; default and empty rendering have explicit tests. |
| (j), requested-open readiness | Hold the real optional-conversation callback while startup renders the same rows. The exact requested completion remains pending despite the generic render event. | Releasing that real callback after viewport capture makes the original full equality fail only on generation (6 versus 5). The twentieth scratch mutant removes the exact conversation wait and fails `requested conversation must finish before capture`, with passing setup/teardown. | Ordinary and delayed-open reflow cases pass after exact conversation, initial resize and viewport completion share one five-second deadline before capture. Full viewport equality and actual reflow geometry assertions remain unchanged. This matches the hosted symptom without claiming its unrecorded callback identity. |
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
The two-run case retains actual host terminals, log paths and provider
creation identities, leaves first-run echo/reset bytes unread, and checks
second-run input/output isolation after both attach readers retire.
The recovery run itself has two provider generations: initial detached and
subsequent attached. Its observer now retains both actual handles, requires
the first to retire before replacement, and binds attachment by exact owner.
Portable real-driver baseline, one-provider-cap mutant and failure-after-
recovery scenarios exercise this same observer. The mutant must retain the
original source exception chain; it cannot pass via a startup timeout.
Cleanup STOPs pending driver work before closing every captured provider and
joining, including when the first close raises after real retirement.

The isolation case now has an explicit reused-host fixture mutant. It runs
both real runs and requires actual cancellation evidence before checking
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

The portable mutants are now committed-source pytest gates in
`extensions/taut_tui/tests/test_tui_mutation_gates.py` and
`extensions/taut_tui/tests/_mutation_probe_child.py`, so every retained
platform executes the same twenty semantic reds. Each child copies the
current selected tests/helpers and product package into scratch space, applies
exactly matched source edits, and runs one declared node. The parent accepts
only exit 1, that exact node, passing setup/teardown, and the expected call
exception plus semantic marker. Collection/internal failures, wrong markers,
extra tests, missing reports, and timeouts fail the gate. Child output is
discarded; the retained report contains phase/outcome/marker booleans only.
The 45-second child containment starts before process creation; expiry kills
and reaps the exact child and is never accepted as a causal red. The separate
timeout probe proves containment/reaping, not arrival at its injected body.

The serialization mutant uses an actual second-worker entry handshake, not
a scheduler race. The portable host-reuse mutant writes tagged bytes to real
`HostTerminal` instances and reads through their existing source-owned reader;
it proves unread-output ownership, not native cancelled-I/O behavior. Negative
children cannot emit parent phase artifacts. At the initial fourteen-mutant
checkpoint, all 24 parent cases passed, with
exactly 24 instrumented phase files; all eleven unique isolated targets also
pass unmutated. Independent review reran the 24 gates (14.22 s) and found no
blocker. Hosted execution and the native probe remain separate requirements.

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

Current selection-slice verification: all 29 parent cases pass, including the
five new mutants and replaced search invalidation case. An independent
review reran all six new/rebound cases successfully. The pending-projection
probe releases its held app handler even when the next key is wrong, so its
mutant fails the exact lost-input assertion with successful teardown, not a
masked cleanup timeout. All fifteen unique isolated targets also pass with
mutation disabled. Full current-tree retained verification and the new
immutable-SHA hosted attempt are recorded in the active plan.

## Diagnostic 5 update (2026-09-25)

The native-pending statements above describe their checkpoint, not the latest
execution. Run `36153148123` at `5d495db` passed all 741 Windows cases with
741 validated phase files, including real successful cancellation followed by
matching `ERROR_OPERATION_ABORTED`, reader retirement, the reused-host semantic
failure, and quiet ConPTY exit publication before output drain. This supplies
native evidence for the exercised (f)/(h) schedules. See the exact identities,
timings and proof limits in
`docs/plans/artifacts/2026-09-25-windows-tui-evidence.md`.

It was one diagnostic repetition, not the five-run acceptance gate. All three
Linux lanes passed; macOS exposed the transcript render/input race now recorded
as class (i) in the active plan. That correction needs its own causal mutants
and a new immutable-SHA qualification. Historical S4 remains unresolved.
