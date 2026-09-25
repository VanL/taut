# TUI Completion Observation Seams

Date: 2026-09-25
Status: slice-1 read-only source audit and implementation proposal; no product
change or native Windows qualification is claimed.
Owner: implementing engineer for
`docs/plans/2026-09-24-windows-tui-determinism-root-cause-plan.md`.
Boundary: TUI-local test observation over existing owner callbacks, futures,
and source adapters. This artifact does not introduce a product event bus or
another polling/control loop.
Verification: inspected the current app/session/Summon implementation,
relevant real-boundary tests, gate fixture, terminal helper, and installed
Textual **8.2.8** source. Proposed seams still need firing implementation
tests, mutation proof where required by the plan, and independent model review.
Required action: preserve the real callback and its return/error semantics at
each seam; allocate retained observation before the initiating action.

## Governing surfaces consulted

- `docs/program-theory.md`, `docs/agent-context/decision-hierarchy.md`,
  `principles.md`, `engineering-principles.md`, testing and hardening runbooks,
  the lessons Golden Rules, and `docs/implementation/03-agent-inventory.md`.
- `docs/specs/02-taut-core.md` [TAUT-8.5]: one scheduling/wake owner per
  context, state before wake, distinct source-result and retirement evidence.
- `docs/specs/01-development-documentation-operating-model.md` [DOM-10.3]:
  the existing shared predicate helper and the stronger source-owned seams
  this TUI-local helper must preserve.
- `docs/specs/10-taut-tui.md` [TUI-11.2]–[TUI-11.3], the active root-cause
  plan, and `docs/implementation/12-taut-tui.md`.

## Minimal observer design

Use one per-test completion scope in the planned
`extensions/taut_tui/tests/_completion.py`. It owns a finite set of retained
handles and cleanup for their observers. It does not own product progression.

The conceptual interface is:

```python
key = CompletionKey(owner, request, phase)
handle = scope.expect(key)  # before initiating the action
# An installed wrapper invokes the real callback, then:
handle.publish(outcome)
# The test awaits the exact already-registered handle:
outcome = await handle.wait(deadline=absolute_deadline, description=description)
```

`owner` and `request` retain actual object/token identity during the test;
diagnostic labels must not turn recyclable numeric ids into authority.
`phase` names a specific transition, not a message class. Use a request's
existing generation where one exists, and its exact retained future where it
does not. Render and resize phases carry their existing effect/generation
fences. No process-global registry or unbounded event history is needed.

Terminal outcomes are success, producer error, producer cancellation, or
supersession. An immutable outcome contains the identity, phase, completion
time, and bounded phase-specific evidence. Preserve the original exception
for propagation within the test. Export only safe structured diagnostics,
such as exception type and phase, not provider screen/message content.

Publication retains the outcome under synchronization **before** notifying
the waiting loop through `loop.call_soon_threadsafe`. This makes completion
before await safe and permits one final retained-outcome check at expiry
even if its scheduled wake has not run. Await cooperatively with the remaining
absolute deadline. Accept only outcomes published at or before the deadline
using that same monotonic clock: a delayed wake preserves on-time success,
but post-deadline publication is not success. Test both orders explicitly.
There is no repeated predicate evaluation, timer-driven
domain observation, retry, or deadline reset on progress. A loop timeout is
containment, not a diagnosis of the unfinished owner.

Wrappers must invoke the real callback exactly as before. Afterward they
capture its result and applied state. They also retain the input future's
failure/cancellation: several app callbacks deliberately render a failure
and return normally, so callback return alone cannot mean operation success.
For a stale generation, preserve the real no-op and publish supersession for
that old handle. It cannot complete a newer handle. Repeated legitimate
events need distinct phase/request keys; an unexpected duplicate terminal
publication is a tripwire, not a second successful completion.
Producer methods may be idempotent: repeated or competing confirmation
resolve/fail calls must publish the first retained decision transition once,
not one outcome per invocation. Preserve all real calls and the production
callback. An unsynchronized check before the call is not an atomic first-win
observer. Test competing resolution as well as sequential repeats.

Timeout or observer-task cancellation disposes only observation and
helper-owned waiter tasks. It must not cancel the shared producer future.
`concurrent.futures.Future` has no `remove_done_callback`; its small wrapper
therefore needs an inactive/weak-reference guard so a late callback becomes
inert and retains no live observer scope. Remove callbacks where the source
supports it. Scope teardown releases local records. Product teardown remains
explicit: request stop, then await the existing owner's retirement with a
separate cleanup cap. Observer disposal is not producer cancellation.

For operations already underway, use an existing retained future or an atomic
registration seam. An app subclass installed before `run_test` initiates
navigation is pre-registration. Installing a wrapper after the operation
started and hoping its callback has not fired is not.

## Owner and completion map

All app symbols below are in `extensions/taut_tui/taut_tui/app.py`, session
symbols in its sibling `session.py`, and TUI Summon symbols in `summon.py`.
All observations run after the real handler unless the row explicitly names
a source-ready event. Each observer publishes to the same TUI test interface;
none drives the product or separately observes broker state.

| Phase | Owner and completing event | Retained identity | Test seam and completion boundary |
|---|---|---|---|
| Initial navigation snapshot | Serialized `TuiSession` worker completes `refresh_navigation()` | Exact returned `Future[NavigationSnapshot]` | Its retained done callback proves worker completion only. Preserve result/error and source membership evidence. |
| Navigation application | Textual invokes `_apply_navigation_result` through `_watch_future` | The same navigation future | Install a subclass override before `run_test`, invoke the real method, then retain input outcome and rendered targets. The current DM test already does this. |
| Conversation application | Textual `_apply_conversation(snapshot)` or `_apply_optional_conversation(intent, future)` | Snapshot generation, intent token, and exact future where applicable | Observe the real acceptance return and resulting active target. The synchronous worker-to-UI commit is distinct from worker completion. |
| Transcript row application | Textual `_render_messages(messages, restore_owner_intent=...)` | Conversation/request plus viewport generation | After the real method, retain rows and selected id. This proves rows exist, not that deferred viewport effects finished. Empty/hidden cases need their own explicit applied/no-effect outcome. |
| Search results | `SearchScreen._apply_results(generation, future)` in `screens.py` | Exact screen, search generation, and future | Observe after real apply. Preserve raw future failure; mark mismatched generations superseded. Assert final rendered hits. |
| Search jump | `_apply_search_context(intent, future)` starts history application, followed by conversation commit | Conversation intent and hit id | Observe this as a handoff, not final jump completion. Final completion requires the corresponding conversation and anchor effect. |
| Search/history anchor | Textual `_apply_viewport_effect(effect, messages)` completes accepted RESTORE | Exact `ViewportEffect` generation and anchored message id | Observe after real accepted restore. Missing-anchor recovery creates another effect; follow that effect instead of claiming the failed restore completed the requested anchor. |
| Tail pin | Textual `_reapply_tail_effect(effect)` | The same accepted tail effect generation | Observe after this second after-refresh application. The first `_apply_viewport_effect` precedes final OptionList row remeasurement. |
| Resize | `on_resize` schedules `_render_latest_resize(generation)` on Textual | Exact resize generation, then any resulting viewport effect | Old callbacks are superseded. Current hidden/too-small callbacks can finish without rendering. Visible geometry assertions also await the resulting final viewport effect. |
| Focus policy | Textual `on_descendant_focus(event)` | Actual widget plus action/request identity | Wrap after the real handler so app mode/focus policy is committed. Calling `.focus()` or observing screen object creation is earlier. |
| Modal mount/readiness | Textual `App.push_screen()` returns its actual `AwaitMount` | Exact screen and its retained mount awaitable | Install the push wrapper before the action. Retain and await the real returned mount awaitable, preserving the original return. Mount covers screen/children; observe required focus separately. Dismissal/replacement before readiness cancels/supersedes the exact screen. |
| Recovery offer | Existing attach-confirmation handler pushes the offer screen | Exact confirmation request and offer screen | Observe actual mounted offer through the preceding seam. Offer creation does not prove input readiness, and accepting the offer starts the distinct acknowledgement phase. |
| Attach confirmation | `TerminalAttachConfirmationRequest.resolve/fail` | Exact request object | Use a delegating test wrapper registered before posting, preserving the real resolution and its production callback. Retain decision/error after resolution. Do not overwrite `set_on_resolved`. |
| Lease acquired | Existing `TerminalLeaseRequest.hold` owns suspension and sets `acquired` | Exact lease request and logical foreground run | Publish from the existing headless suspension thread's real acquisition seam, preserving `hold()` and its errors. Production Textual deliberately pauses during the lease. Confirmation must already have completed. |
| Lease restored | Real `hold()` exits suspension and sets `restored` | Same request/run | Observe its real completion/error. A headless lease-thread exit is a later retirement phase, not implied by acquisition. |
| Provider consumption | Existing PTY output owner invokes Windows `_observe_output` or POSIX terminal-state `observe_output` | Exact adapter object, run/generation, and unique input marker | Wrap the live callback, invoke it first, preserve query arguments/replies, then match bounded, chunk-spanning fixture `echo:`. POSIX attach/event-stream paths bypass its similarly named private helper. Read the log once after this completion. |
| Summon readiness applied | Textual `_apply_summon_ready(run)` | Exact owned-run token | Observe after real policy application and assert ownership/status. Driver `on_ready` and registry publication are distinct earlier phases. |
| Foreground worker return applied | Textual `_apply_summon_return(token, future)` | Exact owned-run token and future | Preserve worker result/error and observe after real retirement of UI ownership. Await actual worker completion separately where no app callback was registered. |
| Source/resource retirement | Existing foreground worker, answerer/lease threads, and native attach cleanup | Retained thread/adapter/session objects | Use their real close/join boundaries. A thread's `finished.set()` in its `finally` is not proof of thread exit. Windows `_AttachSession._cleanup()` return proves its joins/retirement only when no cleanup error escaped. |

## Framework facts that constrain the design

The installed lock resolves Textual 8.2.8. Direct inspection established:

- `App.run_test(message_hook=...)` supports a hook, but
  `MessagePump._dispatch_message` invokes it **before** handlers. The hook
  itself is arrival, not completion. A post-handler queued observation must
  be attached to the correct receiver; a broad message hook is not a
  substitute for the explicit applied-owner seams above.
- `App.push_screen` returns `AwaitMount` when not waiting for dismissal.
  This public awaitable waits on retained mount events for the actual screen
  and children. Preserve it instead of testing that `app.screen` has a type.
- Result delivery does not prove removal: observe a screen's result callback
  for applied results and retain the actual `App.pop_screen` removal
  `AwaitComplete` for unmount/retirement. Shield the shared removal future
  from observer timeout/cancellation; use both fences when both are asserted.
- `Widget.focus()` queues a `set_focus` callback. `Screen.set_focus` updates
  focused-widget identity and posts `Focus`; the widget handler sets
  `has_focus` and posts `DescendantFocus`. App policy therefore follows
  another real event and must be observed at that phase when asserted.
- `Pilot.pause()` combines a queue fence, CPU-idle or timed wait, and timer
  update. A finite causal drain may remain classified as such, but repeatedly
  calling it to test a state is not exact completion observation.

## Plan/code mismatches and slice-2 resolutions

### Navigation does not currently have a generation guard

`TuiSession.refresh_navigation` submits to one serialized executor.
`NavigationSnapshot` and `_apply_navigation_result` carry no navigation
generation. Conversation/search snapshots and viewport effects do carry
generations/intents. The S4 matrix must not describe a navigation
stale-decision guard as existing code.

Slice 2 can preserve the current product and meet the diagnostic intent by
retaining exact navigation future identities, holding worker-return and
application boundaries separately, and recording source membership, future
outcome, callback delivery, and rendered DM. Exercise older/newer ordering at
the conversation/search boundaries that actually own generations. If forcing
navigation callback reordering reveals a stale overwrite, that is a new
causal finding: write its failing proof and record the proposed correction
before a product edit. A synthetic reordered schedule still does not prove
that S4 historically followed that schedule.

### Confirmation has a single auxiliary callback

`TerminalAttachConfirmationRequest.set_on_resolved` stores one callback.
`_present_attach_confirmation` installs production stale-modal dismissal
there. Installing a test callback through the same setter would replace
production behavior. Slice 2 should wrap `resolve/fail` before posting or
compose the callback while preserving the original exactly. No new product
publication is needed.

`test_tui_summon.py::_pushed_confirmation` currently checks only screen
identity/type. Replace its callers with pre-registered actual mount/focus
observation. Input must not target a dismissed/superseded screen after its
late mount completion.

### Provider consumption is already observable without fixture changes

In `extensions/taut_summon/tests/fixtures/gate_harness.py`, `_chat_loop`
calls `_log("input", ...)`, whose file context closes, **before** emitting
`echo:` for that input. The existing output source therefore gives a causal
acknowledgement after logging/consumption. The adapter seams are
The POSIX handle's existing terminal-state `observe_output(data,
answer_queries=...)` callback in `_pty_posix.py` and
`WindowsPtyHandle._observe_output(data, *, answer_queries=True)` in
`_pty_windows.py`. Preserve the Windows keyword argument and call the real
method before observing.

Accumulate only a bounded chunk-spanning frame sufficient to identify an
`echo:` and the unique expected marker. Bind it to the exact adapter/run,
not a process-global marker or recycled PID/fd. Wiring and recovery use
separate markers/identities. The existing provider log remains the final
assertion. Do not create a filesystem poller or a second reader of the
product PTY.

### Negative assertions need retained event history

The decline test passes a `finished()` predicate to `_await_until` that also
collects modal appearances. It is not observation-only and cannot be
mechanically converted into another predicate wait. Register actual screen
push observation before declining, retain bounded screen identities, await
the real foreground terminal fence, then inspect the retained history.
Likewise, a quiet elapsed interval cannot prove that no stale event fired.

### Native proof remains a separate qualification obligation

`extensions/taut_summon/tests/test_pty_windows.py` already contains native
natural-exit, close-before-output-consumption, full ConPTY domain retirement,
and real blocked-write cancellation cases. Reuse those qualified paths for
their stated mechanisms. They do not alone prove that cancelled host-input
I/O or pending reset output cannot cross between two TUI foreground attaches.
The cross-run test still needs distinct retained `HostTerminal` objects,
actual attach-reader cleanup evidence, run-specific markers, and native
Windows execution. A structural host-object assertion is a useful portable
red but not evidence of the Windows cancellation mechanism.

## Review boundary

No product publication is currently necessary for the mapped phases.
Pre-installed test subclasses/callback wrappers, retained futures,
`AwaitMount`, and the existing PTY source callback provide sufficient seams.
This conclusion is a source-level design proposal, not completed runtime
proof. Missing phase, cleanup, generation, or mutation evidence must stay
open during conversion. Historical S4 causality and hosted soak acceptance
remain governed by the active plan's explicit closure rules.
