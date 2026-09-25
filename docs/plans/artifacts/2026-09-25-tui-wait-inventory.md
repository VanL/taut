# TUI wait inventory and completion seams

Status: baseline inventory with slice-2 conversion evidence appended below.
Neither the baseline counts nor completed individual rows are soak qualification.

Owner: Windows TUI determinism plan implementer. Boundary: TUI test
observations and their existing producer callbacks. Verification: AST inventory
plus direct inspection of product callbacks and retained Textual APIs at
`33205d797814da07071bbe27d2336a057e233b8c`, 2026-09-25.
Required action: convert each liveness row only after its exact completion
observer is installed before the trigger, retain its final assertion, and
record any unconverted/unobservable row. Line references below are this
inventory baseline, not promises about lines after migration.

Related plan:
`docs/plans/2026-09-24-windows-tui-determinism-root-cause-plan.md`.

## Conversion ledger

- 2026-09-25, action handlers/routes: all 33 handler and five route counted
  callers now observe exact named requests and applied phases. Both old helper
  definitions are removed; every final assertion and supported route remains.
  `AppliedRequest` distinguishes source completion from owner application and
  retains synchronous refusal as the original error. Mount, result, retirement
  and focus use separate real lifecycle fences. Main review ACT-R1 corrected
  repeatable focus publication; fresh and retained-refocus regressions both
  fired red before the fix. Main verification: 135 handler/route/viewport/screen
  neighbors pass at two workers with loadfile scheduling; scoped Ruff/mypy pass.
  Remaining three bare pauses are finite framework fences, not liveness
  sampling: post-search geometry, already-requested app exit, and fixture
  composer/layout before input. Each has an inline ownership comment.

## Scope and counts

All Python modules in `extensions/taut_tui/tests` were inventoried, including
source strings used by installed-wheel/native-terminal subprocess tests.
Counts are lexical call sites, not parametrized executions.

| Item | Count | Interpretation |
|---|---:|---|
| Local liveness helpers | 8 | Five elapsed-deadline helpers and three attempt-counted helpers; app's alias is not a ninth implementation. |
| Calls to those helpers | 123 | App 59, action handlers 33, action routes 5, chat 5, Summon 21. |
| Inline counted loops containing pauses/sleeps | 35 | 32 positive liveness loops and three fixed drains used before negative modal assertions. |
| Additional synchronous elapsed polling loops | 4 | Summon waits for a posted request/decision. |
| Other repeated event polling | 1 | `_GateAnswerer.run` alternates lease-state checks with 10 ms stop waits. |
| Finite action loops containing pauses | 2 | Four pane cycles and typing a finite command string; not liveness loops. |
| AST-visible `pilot.pause` calls | 201 | 146 without delay and 55 with explicit delay, including helper/loop bodies. |
| Embedded child `pilot.pause` | 1 | Installed launch child, `test_tui_launch.py:284`. |
| AST-visible `time.sleep` calls | 8 | Seven are polling; chat's post-close inactive-reply sleep is a negative-evidence delay. |
| Embedded child `time.sleep` | 1 | Native exclusive-lease probe, `test_tui_textual_contract.py:615`. |

`rg` alone overcounts loops in test data and overlooks source-string semantics.
The AST scan counted enclosing functions, calls, loop bodies, and explicit
timeouts; direct inspection established the classifications below. Existing
Event/Future/Queue waits are separately listed because they already retain an
outcome. They still need operation/phase deadlines and shared observation
diagnostics where the plan requires them.

## Existing helpers and budget policy

| File:definition | Call sites | Present behavior | Proposed budget and correction |
|---|---:|---|---|
| `test_tui_app.py:27` `_eventually`, alias `_pause_until` at 42 | 59 | 5 s from helper entry; 10 ms pilot pauses; no final expiry observation. | Keep 5 s for behavior; create its deadline at the initiating action/owner handoff. Startup has a separate named cap. |
| `test_tui_action_handlers.py:60` `_eventually` | 33 | 200 attempts, each a 10 ms pilot pause. | No existing elapsed bound. Candidate 5 s matches the current app and existing neighboring owner-event waits; native phase measurements/review must justify adoption. Do not call this an unchanged 2 s deadline. |
| `test_tui_action_routes.py:73` `_pause_until` | 5 | 100 attempts, each a 10 ms pilot pause. | Same ambiguity. Candidate 5 s requires the same explicit review, not a mechanical larger default. |
| `test_tui_chat.py:131` `_wait_until` | 5 | 5 s from helper entry, 10 ms sleep. | Keep 5 s; delivery deadline starts at publish and retirement deadline belongs to cleanup. |
| `test_tui_summon.py:1443` `_pushed_confirmation` | 11 | Normally 2 s; recovery offer callers use 45 s and acknowledgement uses 10 s. Only screen-object existence is observed. | Preserve each explicit cap, split startup from the governed behavior, await actual mount/focus of that request's screen. |
| `test_tui_summon.py:1463` `_settled_decision` | 4 | 200 attempts at 10 ms, then inspect retained decision. | Candidate 2 s for this pure decision phase, pending review; observe exact request resolution and modal retirement separately. |
| `test_tui_summon.py:1833` `_wait_until` | 1 | 30 s from helper entry; reads provider log every 50 ms. | Keep 30 s behavior ceiling at orientation start; observe consumption acknowledgement then read log once. |
| `test_tui_summon.py:1847` `_await_until` | 5 | 45 s per helper entry; declined-return call uses 90 s; 20 ms pilot pauses. | Keep explicit 45/90 s caps; each named phase starts at its actual handoff. Observe exact adapter, provider, readiness, or worker outcome. |

An attempt count times its nominal pause is **not** an elapsed budget.
Retained Textual `Pilot.pause` first invokes `_wait_for_screen(timeout=30)`,
then either `wait_for_idle(0)` or `asyncio.sleep(delay)`, then updates the
screen timer. Each attempt can therefore take far more than the nominal sleep.
No TUI-specific CI timeout scaling seam was found in this test directory,
`tests/helpers`, or the retained workflow. Do not infer one from the 1.9x
whole-suite ratio.

Inline 100/200/400-attempt loops have the same ambiguity. Their proposed
behavior ceiling is the reviewed app 5 s baseline where they test app
application; the source table retains the actual count. Summon request-only
cases should retain 2 s where already explicit. These are proposals, not
measured native acceptance claims. Setup caps must be named independently,
and cleanup retains existing 5/15/20/60 s caps by resource as applicable.

## Owner, phase, identity, and observation map

Each appendix row references one of these groups. The group defines the
completion seam and lifetime; the row identifies the exact test and state
assertion. An observation wrapper always calls the real implementation and
publishes after it returns, including an explicit error outcome. It never
retries the action.

| Group | Actual owner / completion | Request identity and proposed test seam | Start, teardown, and caveat |
|---|---|---|---|
| STARTUP | Textual `TautApp.on_mount` constructs session/domain/system; worker navigation applies later. | Exact app instance; subclass `on_mount` installed before `run_test`, plus separate NAV handle for initial snapshot. | Infrastructure begins before `run_test`; on-mount return alone cannot prove navigation rendered. App context exit owns session cleanup. |
| NAV | Session serialized worker publishes a `NavigationSnapshot`; Textual `_apply_navigation_result` renders it. | Exact refresh Future; before-trigger subclass/wrapper records source snapshot, future error/cancel, apply callback and rendered targets. | Deadline begins at `refresh_navigation` request. Keep observer through apply, detach on disposal. Existing S4 subclass is conforming. |
| CONVERSATION | Session opens/commits snapshot, Textual `_apply_conversation` and exact `_apply_optional_conversation` update target/header/draft. | Conversation intent + snapshot generation + worker Future. Observe real application and retain accept/reject, not merely future.done. | Start at navigation action. A later intent supersedes old handle; app teardown retires session/watcher. |
| DELIVERY | Existing watcher calls session `accept_delivery`; Textual `_apply_delivery(generation,item)` applies real message/notification. Own-send may instead finish at `_apply_send_result`. | Exact watcher generation + message ts (or notification identity); own-send Future and draft revision. Bind observer before publish/send, then assert final rows/domain once. | Start at publish or send. Notification-dependent render may require the exact derived NAV Future and VIEWPORT phase. Do not poll broker/SQLite again. |
| ACTION | Domain worker result is applied through `_apply_action_result`, `_apply_form_action_result`, `_apply_channel_rename_result`, `_apply_send_result`, `_apply_deletion_result`, or `_render_inspector`. | Exact Future captured by before-trigger `_watch_future` wrapper; publish only after its real apply callback. Preserve form/draft/intent identity. | Start at submit/button/dispatcher. Final assertions inspect inspector, persisted state, output file or form once. Nested navigation/refresh is a distinct phase, not generic idle. |
| INPUT | Textual dispatches exact route/input and commits highlight/pointer state. | Exact input/action invocation + widget; wrap `_dispatch_tui_action` / `_dispatch_action_invocation`, `on_taut_option_list_activated`, real pointer handler or highlighted reactive watcher. | Start at real input. A queued callback fence is valid only after the named owner handler; unrelated next message is not completion. |
| MOUNT | Textual mounts pushed screen and its controls. | Exact screen instance + attach request/form; preserve real `push_screen` and observe its returned `AwaitMount`, then requested control's mount/focus. | Register before push. Dismiss/unmount before readiness yields cancellation/supersession; no late press. `isinstance(app.screen,...)` is insufficient. |
| FOCUS | Textual commits screen focus. | Exact target widget/screen; post-handler `on_descendant_focus` or exact focused reactive transition; retain already-completed readiness atomically. | Start at focus/input operation. `widget.focus()` returns before the event. Cleanup detaches the test watcher; no global registry. |
| SEARCH | `SearchScreen._apply_results(generation,future)` applies results; app `_apply_search_context` and subsequent viewport restore apply a chosen hit. | Exact screen + search generation + result Future; jump also uses conversation intent + hit ts. Wrap existing callbacks before submit. | Search start at submit, jump at activation. Closing screen cancels/supersedes pending observation; late worker success is not active-screen success. |
| VIEWPORT | App `_apply_viewport_effect`, `_reapply_tail_effect`, `_settle_transcript_user_viewport`, scroll completion and `_render_latest_resize` own layout application. | Exact effect generation/token, user-intent generation, or resize generation. Observe the last real callback that establishes assertion; scroll APIs already offer `on_complete`. | Start at render/input/resize. First tail application can precede row remeasure; include retained reapply. Do not add a second refresh/poll loop. Existing notification probe is a worked example. |
| DECISION | `TerminalAttachConfirmationRequest.resolve/fail` retains decision/error under its lock. Coordinator owns posted request reservation. | Exact request + logical run token; wrap real resolve/fail or observe retained Event via one-shot source adapter. For coordinator tests add callback to test-owned `_LeaseApp.post_message`. | Start at confirm/decision; join driver thread in finally. `set_on_resolved` has one slot already owned by stale-modal cleanup: never overwrite it with a test observer. |
| LEASE | `TerminalLeaseRequest.hold` publishes acquired then restored; production UI intentionally blocks during suspension. | Exact lease request + scoped run token; observe existing acquired/restored Events/error; headless lease thread publishes retirement after hold returns. | Confirmation precedes acquisition. Cleanup sets release, joins owned lease thread, and checks error. Never require production UI messages while lease is held. |
| ADAPTER | Test-owned `_GateAnswerer` waits on host terminal protocol, publishes finished/failures and retires. | Exact answerer + host-terminal/run; wrap thread run completion or use a one-shot wait adapter, retaining stage/error. | Infrastructure readiness precedes provider behavior. Replace the lease-vs-stop 10 ms poll by one owned stop/acquisition wake or release-on-stop fence. Stop, join under 20 s, then close terminal. |
| PROVIDER | Real provider logs consumed input before `echo:`; live Windows `_observe_output` or POSIX handle terminal-state `observe_output` sees acknowledgement. | Exact foreground run + generation + unique marker; chunk-safe accumulator on the existing callback. POSIX bypasses its similarly named private helper. | Behavior starts at governed orientation, not process setup. Inspect log once after acknowledgement. Stop run, retire pump/reader, then close host terminal. No second reader or file poller. |
| SUMMON-READY | Worker readiness reaches Textual `_apply_summon_ready(run)`. | Exact `OwnedSummonRun.token`; observe after real apply. Test controller's ready Event alone proves only its own stage. | Start at readiness handoff. Dispose observer on return/stop; retain explicit cancellation/supersession. |
| SUMMON-RETURN | Foreground Future completes and Textual `_apply_summon_return(token,future)` removes ownership/presents result. | Exact run token + worker Future; capture final exception and separately real UI apply. | Stop/decline begins behavior; preserve 45/90 s existing cap. Finally join/close resources under cleanup budget. |
| EXIT | Textual `exit` request eventually reaches app shutdown/run-test context exit. | Exact app/run; observe real unmount/run completion, not merely `is_running` sampled false. | Start at quit/fatal lease; teardown is already context-owned. Do not block the same loop waiting for its own exit. |
| CORES | Core watcher completes its initial real drain; session close joins watcher and retires owned cores. | Wrap real `TautClient.watch` in the test and call existing `watcher.notify_ready_after_initial_drain(event)` before returning it to `TuiSession`, hence before `watcher.start()`. Retain Event by exact watcher identity. | Keep 5 s; after the initial-drain Event inspect cores once. After `session.close(wait=True)`, inspect baseline count directly. Never replace producer behavior. |
| STATIC | Synchronous owner method has already returned with the asserted model/display property committed. | Exact call plus input identity; use direct final assertion, without an artificial wait. | No behavior timer required for synchronous proof. Await separate render only when geometry is asserted. |
| DISMISS | Textual delivers the exact modal's result and separately removes its screen. | Wrap the exact result callback for result/application; retain real `App.pop_screen` removal `AwaitComplete` for screen retirement, installed before trigger. Use both if both are asserted. | Keep caller's explicit cap; shield shared removal completion from observer cancellation. Result delivery alone does not fence unmount or retained stack/history assertions. |
| DRAFT | `TautApp.on_text_area_changed` commits text/cursor revision for the exact composer. | Observe after real handler for originating composer, expected text and revision. | Start at text assignment/key/paste; retain final draft and wait only on its owner transition. |
| PALETTE | `CommandPaletteScreen.on_input_changed` calls `_render_results` synchronously for that query. | Exact screen + query value; wrap `_render_results`, retain post-render outcome. | Start at query assignment/key. Activation is a separate INPUT/DISMISS phase. |
| SUBMIT | Screen validates or publishes its typed Submitted message; the host's concrete submission handler commits its own test result. | Exact form/screen + submission. Observe after real `_submit` for inline validation; after host `on_native_form_screen_submitted` or supplied dismiss callback for accepted result. | Input dispatch completion is not domain worker completion; domain assertions separately await ACTION. Duplicate/refused input uses the completed rejecting handler fence. |
| SUGGESTION | Textual `Input._on_suggestion_ready` applies ghost text only for current value; command screen `_cycle_shadow` updates shadow synchronously. | Exact input + submitted value plus expected shadow revision. Wrap real async `_on_suggestion_ready` after await; wrap `_cycle_shadow` for arrow cycling and `action_accept_shadow` for Tab. | Start at corresponding key. Preserve late-value rejection; do not treat worker suggestion return as displayed suggestion. |
| SELECTION | Textual screen commits mouse selection and `TautTranscript.selection_updated` notifies its owner; app selection timer callback owns automatic copy. | Exact transcript + selection bounds/generation; wrap real selection callback after return and queue one framework after-refresh only if geometry is asserted. | Start at mouse input; already captured timer callbacks remain controlled finite stimuli. Assert negative copy history after the exact stale/current timer callback. |
| REFRESH | Existing Textual refresh cycle applies already-requested geometry/render work. | Queue one `call_after_refresh` completion behind the exact owner render, or observe the already-owned viewport/resize callback. | A one-shot finite fence, no repeated schedule. It cannot stand in for future worker/mount completion and does not trigger domain work. |
| RESIZE | `TautApp.on_resize` accepts a size and `_render_latest_resize(generation)` applies it. | Exact generation/size, observe after real current-generation apply; retain rejected old callback outcome. | Start at real resize. Stability assertions follow all captured burst callbacks, not a 0.2 s delay. |

A single shared completion interface does not mean a single callback observes
all progress. Retained handles compose the existing owners. A global hook that
rechecks every arbitrary predicate after every Textual message would not
establish operation identity or committed owner application.

Textual `run_test(message_hook=...)` reports message dispatch, not necessarily
post-handler application. Use it to trace receipt or route a test-owned
observer, not as direct proof that Mount/Focus/worker application completed.
`push_screen` returns `AwaitMount`; `dismiss` returns `AwaitComplete`.
Their exact operation results are preferable to a generic event-drain delay.

## Specific problems and exceptions

- S4 already registers its NAV observer in a subclass before `run_test`,
  preserves future error and rendered targets, then awaits an Event. Preserve
  this proof and extend source/callback/generation evidence; replacing it with
  a weaker generic `future.done` wait is a regression.
- `test_setup_recovery_decline_continues_detached_with_enriched_give_up`
  currently supplies a predicate that appends modal objects while polling.
  Sampling cannot prove no modal appeared. Record actual screen pushes for
  this run, await the worker/UI terminal fence, and assert retained history.
- `test_explicit_reply_open_commits_claimed_history_and_watches_both_surfaces`
  sleeps 0.1 s after switching out of a reply. The preceding completed switch
  already retires the previous watcher; after session close, inspect unread
  state. If an additional race proof is needed, use that retirement boundary,
  not time as evidence of non-consumption.
- Three Summon modal tests use 20 repeated pauses only to assert that no
  acknowledgement/modal remained. Await exact dismissal/unmount after the
  resolved decision and inspect retained screen history.
- `test_search_completion_after_escape_is_ignored`, no-match Enter,
  rapid-resize stability, inactive stale leases, and draft restore contain
  standalone delayed pauses before negative assertions. Replace each with
  the exact rejected callback, render generation, dismissal or dispatch
  terminal fence, then inspect state/history.
- `test_compact_mouse_pane_affordance_reaches_each_logical_surface`'s
  four cycles, `test_programmatic_draft_restore_never_promotes`'s character
  sequence, and the rapid-resize four-size sequence are finite user actions.
  Preserve actions; replace incidental delays only with those actions' actual
  completion fences.
- Message seeding ranges, action registry iteration, option-list scans,
  static AST/package audits, the five successful-confirmation repetitions,
  resize preserved-field iteration and pure viewport/layout/model tests are
  finite computation/coverage, not liveness. Do not rewrite them.
- `test_tui_selection.py`'s 16 pauses follow real render/mouse/key
  operations. Timer tests already capture and invoke exact callbacks; do not
  replace these with real 0.5 s waits. Use transcript selection/render fences
  where asynchronous state is asserted.
- Embedded native exclusive-lease probe deliberately leaves a 0.25 s window
  between LEASE-BEGIN/END and checks there are no Textual bytes. Time alone
  cannot prove exclusion. A stronger test queues identifiable UI output
  before/during lease and verifies it only after restoration, while retaining
  real terminal lease and child watchdog ownership. This remains a native
  qualification seam, not an app polling-helper conversion.
- Native terminal probes also use `set_timer` for finite update/exit actions
  in their child source. These are source-side finite scheduling, not
  liveness polling. Preserve host startup/behavior watchdog ownership.
- Direct Event/Future/barrier waits, native `read_until`, process watchdogs,
  and joins are existing resource-owner seams. Adapt retained outcomes into
  shared diagnostics as appropriate; do not replace them with polling or
  cancel the shared producer on observer timeout.

## Disjoint implementation slices

1. Shared `_completion.py` plus helper-only firing tests. Keep no product
   instrumentation. Establish exact identity, retained success/error/cancel/
   supersede, absolute deadlines, disposal, and producer preservation.
2. App/action/screen observers and migrations: split app navigation/delivery/
   viewport from action handlers/routes/screens to avoid editing one test file
   concurrently. Keep existing S4 and search/notification probes.
3. Summon protocol tests and gate fixture observation: one owner for
   `test_tui_summon.py`, distinct request/run identities, true control mount,
   decision/lease/return retained handles, provider acknowledgement and
   independent run resources.
4. Session/chat tests: use delivery callbacks and existing initial-drain/close
   fences for CORES before replacing its two call sites.
5. Bare-pause and negative-proof sweep across selection/native contracts,
   following Appendix B's concrete fences while retaining finite actions and
   existing watchdogs. Re-scan after all above, then review conversion proof
   and remaining native evidence before qualification.

## Appendix A: every liveness helper caller and inline wait

All paths in this appendix are under `extensions/taut_tui/tests/`.
The helper table supplies existing/proposed budgets. Inline rows retain
their literal attempt count or deadline. Group definitions supply owner,
identity, completing callback and teardown. Long source snippets are clipped
to 400 characters solely for readability; file/line names the full source.

| File:line | Test / local helper | Group | Current observation / loop |
|---|---|---|---|
| `test_tui_action_handlers.py:204` | `_cancel_confirmation` | MOUNT | `_eventually( context.pilot, lambda: bool(context.app.screen.query("#confirmation-cancel")), )` |
| `test_tui_action_handlers.py:215` | `_accept_confirmation` | MOUNT | `_eventually( context.pilot, lambda: bool(context.app.screen.query("#confirmation-confirm")), )` |
| `test_tui_action_handlers.py:263` | `_identity_rejoin` | ACTION | `_eventually( context.pilot, lambda: not isinstance(context.app.screen, NativeFormScreen) )` |
| `test_tui_action_handlers.py:272` | `_identity_show` | ACTION | `_eventually(context.pilot, lambda: "alice" in _inspector(context))` |
| `test_tui_action_handlers.py:278` | `_identity_set_name` | ACTION | `_eventually(context.pilot, lambda: "alice-renamed" in _inspector(context))` |
| `test_tui_action_handlers.py:289` | `_identity_set_persona` | ACTION | `_eventually(context.pilot, lambda: "reviewer" in _inspector(context))` |
| `test_tui_action_handlers.py:303` | `_conversation_open` | CONVERSATION | `_eventually( context.pilot, lambda: context.app.visual_state.active_conversation == "general", )` |
| `test_tui_action_handlers.py:312` | `_channel_join` | ACTION | `_eventually( context.pilot, lambda: not isinstance(context.app.screen, NativeFormScreen) )` |
| `test_tui_action_handlers.py:333` | `_channel_leave` | ACTION | `_eventually(context.pilot, lambda: not _is_joined(context, "general"))` |
| `test_tui_action_handlers.py:339` | `_direct_message_start` | ACTION | `_eventually( context.pilot, lambda: not isinstance(context.app.screen, NativeFormScreen) )` |
| `test_tui_action_handlers.py:364` | `_members_open` | ACTION | `_eventually( context.pilot, lambda: "alice" in _inspector(context) and "bob" in _inspector(context), )` |
| `test_tui_action_handlers.py:373` | `_channel_show_topic` | ACTION | `_eventually(context.pilot, lambda: "Initial topic" in _inspector(context))` |
| `test_tui_action_handlers.py:380` | `_channel_set_topic` | ACTION | `_eventually(context.pilot, lambda: "Changed topic" in _inspector(context))` |
| `test_tui_action_handlers.py:391` | `_channel_clear_topic` | ACTION | `_eventually(context.pilot, lambda: _topic_is(context, None))` |
| `test_tui_action_handlers.py:432` | `_channel_rename` | CONVERSATION | `_eventually( context.pilot, lambda: context.app.visual_state.active_conversation == "renamed-channel", )` |
| `test_tui_action_handlers.py:454` | `_channel_rename` | DELIVERY | `_eventually( context.pilot, lambda: _thread_has_text( context, "renamed-channel", "first line\nsecond line", ), )` |
| `test_tui_action_handlers.py:467` | `_channel_rename` | DELIVERY | `_eventually( context.pilot, lambda: any( row.text == "incoming after rename" for row in context.app._message_rows ), )` |
| `test_tui_action_handlers.py:498` | `_message_send` | FOCUS | `_eventually( context.pilot, lambda: ( composer.has_focus and context.app.visual_state.mode is InteractionMode.COMPOSE ), )` |
| `test_tui_action_handlers.py:509` | `_message_send` | DELIVERY | `_eventually( context.pilot, lambda: _thread_has_text(context, "general", "handler-send"), )` |
| `test_tui_action_handlers.py:519` | `_message_reply` | DELIVERY | `_eventually( context.pilot, lambda: _thread_has_text( context, f"general.{context.message_ts}", "handler reply" ), )` |
| `test_tui_action_handlers.py:531` | `_message_react` | ACTION | `_eventually( context.pilot, lambda: "Reaction ack added" in _inspector(context) )` |
| `test_tui_action_handlers.py:559` | `_message_delete` | ACTION | `_eventually(context.pilot, lambda: "Deleted message" in _inspector(context))` |
| `test_tui_action_handlers.py:678` | `_system_doctor` | ACTION | `_eventually(context.pilot, lambda: "System doctor" in _inspector(context))` |
| `test_tui_action_handlers.py:692` | `_system_dump` | ACTION | `_eventually( context.pilot, lambda: output.read_text(encoding="utf-8") != "sentinel", )` |
| `test_tui_action_handlers.py:796` | `_summon_start` | SUMMON-READY | `_eventually(context.pilot, controller.ready.is_set)` |
| `test_tui_action_handlers.py:808` | `_summon_list` | ACTION | `_eventually( context.pilot, lambda: "actual-summoned" in _inspector(context) )` |
| `test_tui_action_handlers.py:825` | `_summon_status` | ACTION | `_eventually( context.pilot, lambda: "actual-summoned" in _inspector(context) )` |
| `test_tui_action_handlers.py:852` | `_summon_dismiss` | SUMMON-RETURN | `_eventually( context.pilot, lambda: controller.stopped == ["actual-summoned"] )` |
| `test_tui_action_handlers.py:907` | `test_colon_command_line_executes_a_typed_native_core_path.exercise` | STARTUP | `_eventually(pilot, lambda: app._domain is not None)` |
| `test_tui_action_handlers.py:911` | `test_colon_command_line_executes_a_typed_native_core_path.exercise` | ACTION | `_eventually( pilot, lambda: ( app._operation_state == "idle" and "created" in str(app.query_one("#inspector-body").render()).lower() ), )` |
| `test_tui_action_handlers.py:942` | `test_colon_command_line_reports_cli_only_paths_and_options.exercise` | STARTUP | `_eventually(pilot, lambda: app._domain is not None)` |
| `test_tui_action_handlers.py:944` | `test_colon_command_line_reports_cli_only_paths_and_options.exercise` | ACTION | `_eventually( pilot, lambda: "CLI-only" in str(app.query_one("#inspector-body").render()), )` |
| `test_tui_action_handlers.py:1000` | `test_every_action_reaches_a_concrete_handler.exercise` | STARTUP | `_eventually( pilot, lambda: ( app._system is not None and ( action_id is ActionId.WORKSPACE_INITIALIZE or app._domain is not None ) ), )` |
| `test_tui_action_routes.py:120` | `_drive_palette` | MOUNT | `_pause_until(pilot, lambda: bool(app.screen.query("#palette-query")))` |
| `test_tui_action_routes.py:157` | `_drive_context` | MOUNT | `_pause_until(pilot, lambda: bool(app.screen.query("#search-query")))` |
| `test_tui_action_routes.py:163` | `_drive_context` | SEARCH | `_pause_until(pilot, lambda: results.option_count == 1)` |
| `test_tui_action_routes.py:234` | `test_every_declared_route_reaches_the_central_dispatcher_through_its_real_producer.exercise` | STARTUP | `_pause_until(pilot, lambda: app._domain is not None)` |
| `test_tui_action_routes.py:264` | `test_every_declared_route_reaches_the_central_dispatcher_through_its_real_producer.exercise` | INPUT | `_pause_until(pilot, lambda: bool(observations))` |
| `test_tui_app.py:528` | `test_real_transcript_viewport_anchor_survives_width_reflow.exercise` | NAV | `_pause_until( pilot, lambda: _has_option_containing(navigation, "#general"), )` |
| `test_tui_app.py:651` | `test_known_command_prefix_in_composer_promotes_to_argument_input.exercise` | FOCUS | `_pause_until(pilot, lambda: composer.has_focus)` |
| `test_tui_app.py:752` | `test_composer_quit_alias_promotes_before_guarded_execution.exercise` | FOCUS | `_pause_until(pilot, lambda: composer.has_focus)` |
| `test_tui_app.py:980` | `test_enter_delimits_full_command_without_capturing_shorter_root.exercise` | FOCUS | `_pause_until(pilot, lambda: composer.has_focus)` |
| `test_tui_app.py:1006` | `test_unknown_colon_text_stays_message_and_command_cancel_preserves_draft.exercise` | FOCUS | `_pause_until(pilot, lambda: composer.has_focus)` |
| `test_tui_app.py:1051` | `test_text_command_rename_preserves_draft.exercise` | STARTUP | `_pause_until(pilot, lambda: app._domain is not None)` |
| `test_tui_app.py:1058` | `test_text_command_rename_preserves_draft.exercise` | CONVERSATION | `_pause_until( pilot, lambda: app.visual_state.active_conversation == "general", )` |
| `test_tui_app.py:1078` | `test_text_command_rename_preserves_draft.exercise` | CONVERSATION | `_pause_until( pilot, lambda: app.visual_state.active_conversation == "renamed", )` |
| `test_tui_app.py:1086` | `test_text_command_rename_preserves_draft.exercise` | DELIVERY | `_pause_until( pilot, lambda: any(row.text == "source\ndraft" for row in app._message_rows), )` |
| `test_tui_app.py:1236` | `test_successful_promoted_command_clears_unchanged_originating_draft.exercise` | FOCUS | `_pause_until(pilot, lambda: composer.has_focus)` |
| `test_tui_app.py:1260` | `test_promoted_command_does_not_clear_a_newer_originating_draft.exercise` | FOCUS | `_pause_until(pilot, lambda: composer.has_focus)` |
| `test_tui_app.py:1320` | `test_command_palette_mouse_activation_opens_summon_argument_form.exercise` | FOCUS | `_pause_until(pilot, lambda: query.has_focus)` |
| `test_tui_app.py:1331` | `test_command_palette_mouse_activation_opens_summon_argument_form.exercise` | MOUNT | `_pause_until(pilot, lambda: isinstance(app.screen, SummonStartScreen))` |
| `test_tui_app.py:1378` | `test_empty_state_actions_use_the_navigation_route.exercise` | NAV | `_pause_until( pilot, lambda: expected in app._navigation_targets, )` |
| `test_tui_app.py:1415` | `test_explicit_mouse_controls_use_the_typed_action_dispatcher.exercise` | NAV | `_pause_until( pilot, lambda: _has_option_containing(navigation, "#general"), )` |
| `test_tui_app.py:1422` | `test_explicit_mouse_controls_use_the_typed_action_dispatcher.exercise` | DELIVERY | `_pause_until(pilot, lambda: bool(app._message_rows))` |
| `test_tui_app.py:1425` | `test_explicit_mouse_controls_use_the_typed_action_dispatcher.exercise` | STATIC | `_pause_until( pilot, lambda: all( app.query_one(selector).display for selector in ( "#composer-send", "#members-action", "#reply-action", "#react-action", "#delete-action", ) ), )` |
| `test_tui_app.py:1758` | `test_native_and_textual_summon_routes_share_confirmation_before_suspend.exercise` | FOCUS | `_pause_until(pilot, lambda: query.has_focus)` |
| `test_tui_app.py:1763` | `test_native_and_textual_summon_routes_share_confirmation_before_suspend.exercise` | MOUNT | `_pause_until(pilot, lambda: isinstance(app.screen, SummonStartScreen))` |
| `test_tui_app.py:1782` | `test_native_and_textual_summon_routes_share_confirmation_before_suspend.exercise` | FOCUS | `_pause_until(pilot, lambda: composer.has_focus)` |
| `test_tui_app.py:1830` | `test_tui_unmount_cancels_pending_attach_confirmation.exercise` | MOUNT | `_pause_until( pilot, lambda: isinstance(app.screen, ConfirmationScreen) )` |
| `test_tui_app.py:2005` | `test_central_dispatch_enforces_applicability_before_forms_and_mouse_handlers.exercise` | STARTUP | `_pause_until(pilot, lambda: app._domain is not None)` |
| `test_tui_app.py:2060` | `test_conversation_open_evaluates_after_navigation_target_projection.exercise` | STARTUP | `_pause_until(pilot, lambda: app._domain is not None)` |
| `test_tui_app.py:2103` | `test_navigation_single_click_selects_while_enter_and_double_click_activate.exercise` | NAV | `_pause_until( pilot, lambda: app._navigation_targets[:1] == ["general"], )` |
| `test_tui_app.py:2108` | `test_navigation_single_click_selects_while_enter_and_double_click_activate.exercise` | INPUT | `_pause_until(pilot, lambda: navigation.highlighted == 0)` |
| `test_tui_app.py:2113` | `test_navigation_single_click_selects_while_enter_and_double_click_activate.exercise` | CONVERSATION | `for _ in range(100): await pilot.pause(0.01) if app.visual_state.active_conversation == "general": break` |
| `test_tui_app.py:2122` | `test_navigation_single_click_selects_while_enter_and_double_click_activate.exercise` | NAV | `_pause_until( pilot, lambda: second._navigation_targets[:1] == ["general"], )` |
| `test_tui_app.py:2127` | `test_navigation_single_click_selects_while_enter_and_double_click_activate.exercise` | CONVERSATION | `for _ in range(100): await pilot.pause(0.01) if second.visual_state.active_conversation == "general": break` |
| `test_tui_app.py:2152` | `test_navigation_drag_out_does_not_swallow_next_keyboard_enter.exercise` | NAV | `_pause_until( pilot, lambda: app._navigation_targets[:1] == ["general"], )` |
| `test_tui_app.py:2158` | `test_navigation_drag_out_does_not_swallow_next_keyboard_enter.exercise` | FOCUS | `_pause_until(pilot, lambda: navigation.has_focus)` |
| `test_tui_app.py:2162` | `test_navigation_drag_out_does_not_swallow_next_keyboard_enter.exercise` | INPUT | `_pause_until(pilot, lambda: not navigation._pointer_pending)` |
| `test_tui_app.py:2164` | `test_navigation_drag_out_does_not_swallow_next_keyboard_enter.exercise` | CONVERSATION | `_pause_until( pilot, lambda: app.visual_state.active_conversation == "general", )` |
| `test_tui_app.py:2240` | `test_direct_message_header_and_composer_use_actor_scoped_label.exercise` | CONVERSATION | `_pause_until( pilot, lambda: ( app.visual_state.active_conversation == dm_target and "DM with bob" in str(app.query_one("#target-header").render()) and app.query_one("#composer", TautComposer).placeholder == "Message DM with bob" ), )` |
| `test_tui_app.py:2475` | `test_live_reply_notification_refreshes_the_contextual_reply_marker.exercise` | NAV | `_pause_until( pilot, lambda: app._navigation_targets[:1] == ["general"], )` |
| `test_tui_app.py:2482` | `test_live_reply_notification_refreshes_the_contextual_reply_marker.exercise` | DELIVERY | `_pause_until( pilot, lambda: any(message.ts == root.ts for message in app._message_rows), )` |
| `test_tui_app.py:2675` | `test_superseding_navigation_clears_and_rejects_stale_search.exercise` | NAV | `_pause_until( pilot, lambda: _has_option_containing(navigation, "#random"), )` |
| `test_tui_app.py:2682` | `test_superseding_navigation_clears_and_rejects_stale_search.exercise` | CONVERSATION | `_pause_until( pilot, lambda: app.visual_state.active_conversation == "random", )` |
| `test_tui_app.py:2801` | `test_compact_mouse_pane_affordance_reaches_each_logical_surface.exercise` | FINITE-ACTION | `for _ in range(4): for widget_id in ("navigation", "conversation", "inspector"): if app.query_one(f"#{widget_id}").display: seen.add(widget_id) assert await pilot.click("#pane-affordance") is True await pilot.pause()` |
| `test_tui_app.py:2831` | `test_real_app_opens_active_conversation_and_sends_through_public_client.exercise` | NAV | `for _ in range(100): await pilot.pause(0.01) if navigation.option_count and "#general" in str( navigation.get_option_at_index(0).prompt ): break else: pytest.fail("navigation did not load")` |
| `test_tui_app.py:2843` | `test_real_app_opens_active_conversation_and_sends_through_public_client.exercise` | CONVERSATION | `for _ in range(100): await pilot.pause(0.01) if app.visual_state.active_conversation == "general": break else: pytest.fail("conversation did not open")` |
| `test_tui_app.py:2859` | `test_real_app_opens_active_conversation_and_sends_through_public_client.exercise` | ACTION | `for _ in range(100): await pilot.pause(0.01) if app.query_one("#composer", TautComposer).text == "": break else: pytest.fail("send did not complete")` |
| `test_tui_app.py:2890` | `test_command_palette_opens_native_form_and_applies_public_identity_change.exercise` | MOUNT | `for _ in range(100): await pilot.pause(0.01) if list(app.screen.query("#field-persona")): break else: pytest.fail("persona form did not open")` |
| `test_tui_app.py:2899` | `test_command_palette_opens_native_form_and_applies_public_identity_change.exercise` | ACTION | `for _ in range(100): await pilot.pause(0.01) if alice.whoami().persona == "reviewer": break else: pytest.fail("persona action did not complete")` |
| `test_tui_app.py:2934` | `test_native_form_keeps_values_and_renders_domain_error_inline.exercise` | ACTION | `for _ in range(100): await pilot.pause(0.01) error = str(app.screen.query_one("#form-errors").render()) if error and error != "Working…": break` |
| `test_tui_app.py:3005` | `test_open_search_result_anchors_exact_hit_without_advancing_cursor.exercise` | CONVERSATION | `_pause_until( pilot, lambda: ( app.visual_state.active_conversation == "general" and any(message.ts == hit.ts for message in app._message_rows) ), )` |
| `test_tui_app.py:3071` | `test_user_scroll_supersedes_pending_search_anchor_restore.exercise` | VIEWPORT | `_eventually(pilot, viewport_matches_widget)` |
| `test_tui_app.py:3072` | `test_user_scroll_supersedes_pending_search_anchor_restore.exercise` | VIEWPORT | `_eventually( pilot, lambda: int(transcript.scroll_offset.y) == int(transcript.scroll_target_y), )` |
| `test_tui_app.py:3179` | `test_removed_history_anchor_recovers_to_tail.exercise` | VIEWPORT | `_eventually( pilot, lambda: app.visual_state.viewport.tail_pinned and transcript.is_vertical_scroll_end, )` |
| `test_tui_app.py:3466` | `test_overlapping_send_completion_only_clears_its_own_draft.exercise` | NAV | `_pause_until( pilot, lambda: _has_option_containing(navigation, "#general"), )` |
| `test_tui_app.py:3473` | `test_overlapping_send_completion_only_clears_its_own_draft.exercise` | CONVERSATION | `_pause_until( pilot, lambda: app.visual_state.active_conversation == "general", )` |
| `test_tui_app.py:3527` | `test_reply_markers_and_close_restore_conversation_focus.exercise` | NAV | `_pause_until( pilot, lambda: bool(navigation.option_count and app._reply_threads), )` |
| `test_tui_app.py:3534` | `test_reply_markers_and_close_restore_conversation_focus.exercise` | CONVERSATION | `_pause_until( pilot, lambda: app.visual_state.active_conversation == "general", )` |
| `test_tui_app.py:3550` | `test_reply_markers_and_close_restore_conversation_focus.exercise` | CONVERSATION | `_pause_until( pilot, lambda: app.visual_state.open_reply_thread is not None, )` |
| `test_tui_app.py:3557` | `test_reply_markers_and_close_restore_conversation_focus.exercise` | FOCUS | `_pause_until( pilot, lambda: ( app.visual_state.open_reply_thread is None and transcript.has_focus ), )` |
| `test_tui_app.py:3906` | `test_programmatic_draft_restore_never_promotes.open_target` | CONVERSATION | `for _ in range(200): await pilot.pause(0.01) if app.visual_state.active_conversation == target: return` |
| `test_tui_app.py:3915` | `test_programmatic_draft_restore_never_promotes.exercise` | NAV | `for _ in range(200): await pilot.pause(0.01) if app._navigation_targets: break` |
| `test_tui_app.py:3921` | `test_programmatic_draft_restore_never_promotes.exercise` | FINITE-ACTION | `for character in ":summon kimi": await pilot.press("space" if character == " " else character) await pilot.pause(0.005)` |
| `test_tui_app.py:3961` | `test_command_line_open_keeps_live_deliveries_rendering.exercise` | NAV | `for _ in range(200): await pilot.pause(0.01) if app._navigation_targets: break` |
| `test_tui_app.py:3972` | `test_command_line_open_keeps_live_deliveries_rendering.exercise` | CONVERSATION | `for _ in range(200): await pilot.pause(0.01) if app.visual_state.active_conversation == "general": break` |
| `test_tui_app.py:3982` | `test_command_line_open_keeps_live_deliveries_rendering.exercise` | DELIVERY | `for _ in range(400): await pilot.pause(0.01) if transcript.option_count > baseline: break` |
| `test_tui_app.py:4015` | `test_real_rapid_resize_burst_keeps_latest_state_and_live_delivery.exercise` | NAV | `_eventually(pilot, lambda: "general" in app._navigation_targets)` |
| `test_tui_app.py:4019` | `test_real_rapid_resize_burst_keeps_latest_state_and_live_delivery.exercise` | CONVERSATION | `_eventually( pilot, lambda: app.visual_state.active_conversation == "general", )` |
| `test_tui_app.py:4024` | `test_real_rapid_resize_burst_keeps_latest_state_and_live_delivery.exercise` | CONVERSATION | `_eventually(pilot, lambda: transcript.option_count >= 24)` |
| `test_tui_app.py:4026` | `test_real_rapid_resize_burst_keeps_latest_state_and_live_delivery.exercise` | ACTION | `_eventually(pilot, lambda: app.visual_state.inspector is not None)` |
| `test_tui_app.py:4042` | `test_real_rapid_resize_burst_keeps_latest_state_and_live_delivery.exercise.worker_result` | ACTION | `_eventually(pilot, lambda: app._operation_state == "idle")` |
| `test_tui_app.py:4049` | `test_real_rapid_resize_burst_keeps_latest_state_and_live_delivery.exercise` | DELIVERY | `_eventually( pilot, lambda: any( message.text == "delivery during resize burst" for message in app._message_rows ), )` |
| `test_tui_app.py:4056` | `test_real_rapid_resize_burst_keeps_latest_state_and_live_delivery.exercise` | VIEWPORT | `_eventually(pilot, lambda: transcript.is_vertical_scroll_end)` |
| `test_tui_app.py:4098` | `test_tail_pin_survives_own_send_and_watcher_delivery.exercise` | NAV | `_eventually(pilot, lambda: "general" in app._navigation_targets)` |
| `test_tui_app.py:4102` | `test_tail_pin_survives_own_send_and_watcher_delivery.exercise` | DELIVERY | `_eventually(pilot, lambda: len(app._message_rows) >= 24)` |
| `test_tui_app.py:4104` | `test_tail_pin_survives_own_send_and_watcher_delivery.exercise` | VIEWPORT | `_eventually(pilot, lambda: transcript.is_vertical_scroll_end)` |
| `test_tui_app.py:4111` | `test_tail_pin_survives_own_send_and_watcher_delivery.exercise` | DELIVERY | `_eventually( pilot, lambda: any( message.text == "own send keeps tail" for message in app._message_rows ), )` |
| `test_tui_app.py:4117` | `test_tail_pin_survives_own_send_and_watcher_delivery.exercise` | VIEWPORT | `_eventually(pilot, lambda: transcript.is_vertical_scroll_end)` |
| `test_tui_app.py:4121` | `test_tail_pin_survives_own_send_and_watcher_delivery.exercise` | DELIVERY | `_eventually( pilot, lambda: any( message.text == "watcher keeps tail" for message in app._message_rows ), )` |
| `test_tui_app.py:4127` | `test_tail_pin_survives_own_send_and_watcher_delivery.exercise` | VIEWPORT | `_eventually(pilot, lambda: transcript.is_vertical_scroll_end)` |
| `test_tui_app.py:4259` | `test_unselected_composer_draft_carries_into_first_conversation.exercise` | NAV | `for _ in range(200): await pilot.pause(0.01) if app._navigation_targets: break` |
| `test_tui_app.py:4275` | `test_unselected_composer_draft_carries_into_first_conversation.exercise` | CONVERSATION | `for _ in range(200): await pilot.pause(0.01) if app.visual_state.active_conversation == "general": break` |
| `test_tui_chat.py:206` | `test_only_active_conversation_advances_while_inactive_stays_unread` | CONVERSATION | `_wait_until( lambda: any( isinstance(item, Message) and item.text == "active" for item in deliveries ) )` |
| `test_tui_chat.py:259` | `test_latest_switch_wins_and_stops_old_watcher_before_replacement` | DELIVERY | `_wait_until( lambda: any( isinstance(item, Message) and item.text == "new active" for item in deliveries ) )` |
| `test_tui_chat.py:300` | `test_repeated_target_switches_retire_broker_worker_cores` | CORES | `_wait_until( lambda: ( baseline_cores < len(process_session._cores) <= baseline_cores + 2 ) )` |
| `test_tui_chat.py:308` | `test_repeated_target_switches_retire_broker_worker_cores` | CORES | `_wait_until(lambda: len(process_session._cores) == baseline_cores)` |
| `test_tui_chat.py:490` | `test_explicit_reply_open_commits_claimed_history_and_watches_both_surfaces` | DELIVERY | `_wait_until( lambda: {parent_live.ts, reply_live.ts}.issubset( {item.ts for item in deliveries if isinstance(item, Message)} ) )` |
| `test_tui_chat.py:531` | `test_transcript_decodes_literal_escapes_toward_sender_intent.exercise` | NAV | `for _ in range(200): await pilot.pause(0.01) if app._navigation_targets: break` |
| `test_tui_chat.py:544` | `test_transcript_decodes_literal_escapes_toward_sender_intent.exercise` | CONVERSATION | `for _ in range(200): await pilot.pause(0.01) if app.visual_state.active_conversation == "general": break` |
| `test_tui_chat.py:607` | `test_notification_refresh_keeps_scrolled_transcript_position.exercise` | NAV | `for _ in range(200): await pilot.pause(0.01) if app._navigation_targets: break` |
| `test_tui_chat.py:618` | `test_notification_refresh_keeps_scrolled_transcript_position.exercise` | CONVERSATION | `for _ in range(200): await pilot.pause(0.01) if app.visual_state.active_conversation == "general": break` |
| `test_tui_screens.py:431` | `test_search_result_terminal_controls_are_escaped_even_for_fast_completion.exercise` | SEARCH | `for _ in range(100): await pilot.pause(0.01) options = app.screen.query_one("#search-results", OptionList) if options.option_count: break` |
| `test_tui_screens.py:497` | `test_search_results_use_actor_scoped_dm_labels_without_exposing_queue_names.exercise` | SEARCH | `for _ in range(100): await pilot.pause(0.01) options = app.screen.query_one("#search-results", OptionList) if options.option_count == 2: break` |
| `test_tui_summon.py:551` | `test_terminal_attach_confirmation_is_exclusive_and_precedes_lease` | DECISION | `while not app.messages and time.monotonic() < deadline: time.sleep(0.01)` |
| `test_tui_summon.py:616` | `test_terminal_lease_ownership_survives_distinct_driver_phase_threads` | DECISION | `while not decisions and time.monotonic() < deadline: time.sleep(0.01)` |
| `test_tui_summon.py:702` | `test_terminal_attach_confirmation_close_and_post_failure_fail_closed` | DECISION | `while not app.messages and time.monotonic() < deadline: time.sleep(0.01)` |
| `test_tui_summon.py:762` | `test_host_shutdown_requests_the_run_stop_before_refusing` | DECISION | `while not app.messages and time.monotonic() < deadline: time.sleep(0.01)` |
| `test_tui_summon.py:1090` | `test_real_app_lease_suspension_failure_exits_instead_of_lingering.exercise` | LEASE | `for _ in range(100): await pilot.pause(0.01) if request.restored.is_set(): break` |
| `test_tui_summon.py:1095` | `test_real_app_lease_suspension_failure_exits_instead_of_lingering.exercise` | EXIT | `for _ in range(100): await pilot.pause(0.01) if not app.is_running: return` |
| `test_tui_summon.py:1119` | `test_stale_or_shutdown_lease_request_never_suspends_or_exits.exercise` | LEASE | `for _ in range(100): await pilot.pause(0.01) if request.restored.is_set(): break` |
| `test_tui_summon.py:1262` | `test_quit_with_pending_run_offers_cancel_and_quit_dialog.exercise` | EXIT | `for _ in range(100): await pilot.pause(0.01) if not app.is_running: break` |
| `test_tui_summon.py:1292` | `test_cancelled_attach_confirmation_dismisses_stale_dialog.exercise` | MOUNT | `for _ in range(100): await pilot.pause(0.01) if isinstance(app.screen, ConfirmationScreen): break` |
| `test_tui_summon.py:1298` | `test_cancelled_attach_confirmation_dismisses_stale_dialog.exercise` | MOUNT | `for _ in range(100): await pilot.pause(0.01) if not isinstance(app.screen, ConfirmationScreen): break` |
| `test_tui_summon.py:1345` | `test_cancelled_attach_dismiss_failure_cannot_replace_resolution.exercise` | MOUNT | `for _ in range(100): await pilot.pause(0.01) if isinstance(app.screen, FailingOnceConfirmation): break` |
| `test_tui_summon.py:1351` | `test_cancelled_attach_dismiss_failure_cannot_replace_resolution.exercise` | DISMISS | `for _ in range(100): await pilot.pause(0.01) if dismiss_calls == 1: break` |
| `test_tui_summon.py:1418` | `test_attach_resolution_during_push_retries_failed_dismiss_schedule.exercise` | DISMISS | `for _ in range(100): await pilot.pause(0.01) if schedule_attempts >= 2 and not isinstance( app.screen, ConfirmationScreen ): break` |
| `test_tui_summon.py:1496` | `test_setup_recovery_offer_leads_with_member_and_escaped_excerpt.exercise` | MOUNT | `_pushed_confirmation(pilot, app)` |
| `test_tui_summon.py:1508` | `test_setup_recovery_offer_leads_with_member_and_escaped_excerpt.exercise` | MOUNT | `_pushed_confirmation(pilot, app, replacing=offer)` |
| `test_tui_summon.py:1517` | `test_setup_recovery_offer_leads_with_member_and_escaped_excerpt.exercise` | DECISION | `_settled_decision(pilot, request)` |
| `test_tui_summon.py:1546` | `test_setup_recovery_offer_decline_skips_the_acknowledgement_phase.exercise` | MOUNT | `_pushed_confirmation(pilot, app)` |
| `test_tui_summon.py:1550` | `test_setup_recovery_offer_decline_skips_the_acknowledgement_phase.exercise` | DECISION | `_settled_decision(pilot, request)` |
| `test_tui_summon.py:1551` | `test_setup_recovery_offer_decline_skips_the_acknowledgement_phase.exercise` | NEGATIVE-DRAIN | `for _ in range(20): await pilot.pause(0.01)` |
| `test_tui_summon.py:1583` | `test_setup_recovery_acknowledgement_decline_resolves_false.exercise` | MOUNT | `_pushed_confirmation(pilot, app)` |
| `test_tui_summon.py:1585` | `test_setup_recovery_acknowledgement_decline_resolves_false.exercise` | MOUNT | `_pushed_confirmation(pilot, app, replacing=offer)` |
| `test_tui_summon.py:1588` | `test_setup_recovery_acknowledgement_decline_resolves_false.exercise` | DECISION | `_settled_decision(pilot, request)` |
| `test_tui_summon.py:1589` | `test_setup_recovery_acknowledgement_decline_resolves_false.exercise` | NEGATIVE-DRAIN | `for _ in range(20): await pilot.pause(0.01)` |
| `test_tui_summon.py:1621` | `test_worker_resolution_dismisses_the_pending_offer_modal.exercise` | MOUNT | `_pushed_confirmation(pilot, app)` |
| `test_tui_summon.py:1625` | `test_worker_resolution_dismisses_the_pending_offer_modal.exercise` | MOUNT | `for _ in range(100): await pilot.pause(0.01) if not isinstance(app.screen, ConfirmationScreen): break` |
| `test_tui_summon.py:1659` | `test_bootstrap_attach_confirmation_content_is_unchanged.exercise` | MOUNT | `_pushed_confirmation(pilot, app)` |
| `test_tui_summon.py:1666` | `test_bootstrap_attach_confirmation_content_is_unchanged.exercise` | DECISION | `_settled_decision(pilot, request)` |
| `test_tui_summon.py:1667` | `test_bootstrap_attach_confirmation_content_is_unchanged.exercise` | NEGATIVE-DRAIN | `for _ in range(20): await pilot.pause(0.01)` |
| `test_tui_summon.py:1706` | `test_confirm_owner_contention_declines_instead_of_raising` | DECISION | `for _ in range(200): with interaction._lock: if interaction._terminal_owner is not None: break time.sleep(0.01)` |
| `test_tui_summon.py:1909` | `run` | ADAPTER | `while not self._lease_acquired.is_set(): if self._stop_requested.wait(0.01): return` |
| `test_tui_summon.py:1997` | `_wire_gate_member` | PROVIDER | `_wait_until( lambda: any(marker in raw for raw in _gate_inputs(log)), message="wiring-run orientation injection", )` |
| `test_tui_summon.py:2162` | `test_setup_recovery_offer_reaches_a_pending_owned_tui_and_completes.exercise` | MOUNT | `_pushed_confirmation(pilot, app, timeout=45.0)` |
| `test_tui_summon.py:2176` | `test_setup_recovery_offer_reaches_a_pending_owned_tui_and_completes.exercise` | MOUNT | `_pushed_confirmation( pilot, app, replacing=offer, timeout=10.0 )` |
| `test_tui_summon.py:2190` | `test_setup_recovery_offer_reaches_a_pending_owned_tui_and_completes.exercise` | ADAPTER | `_await_until( pilot, answerer.finished.is_set, message="terminal answerer completion", )` |
| `test_tui_summon.py:2205` | `test_setup_recovery_offer_reaches_a_pending_owned_tui_and_completes.exercise` | PROVIDER | `_await_until( pilot, lambda: any(marker in raw for raw in _gate_inputs(log)), message="post-recovery orientation injection", )` |
| `test_tui_summon.py:2216` | `test_setup_recovery_offer_reaches_a_pending_owned_tui_and_completes.exercise` | SUMMON-READY | `_await_until( pilot, lambda: app._operation_state == "summon live", message="post-recovery readiness", )` |
| `test_tui_summon.py:2224` | `test_setup_recovery_offer_reaches_a_pending_owned_tui_and_completes.exercise` | SUMMON-RETURN | `_await_until( pilot, lambda: not app._owned_summon_tokens, message="owned worker return", )` |
| `test_tui_summon.py:2300` | `test_setup_recovery_decline_continues_detached_with_enriched_give_up.exercise` | MOUNT | `_pushed_confirmation(pilot, app, timeout=45.0)` |
| `test_tui_summon.py:2311` | `test_setup_recovery_decline_continues_detached_with_enriched_give_up.exercise` | SUMMON-RETURN | `_await_until( pilot, finished, message="declined run completion", timeout=90.0 )` |
| `test_tui_summon.py:2360` | `test_host_shutdown_during_offer_spawns_nothing_further.exercise` | MOUNT | `_pushed_confirmation(pilot, app, timeout=45.0)` |

## Appendix B: pauses and sleeps outside polling bodies

This table assigns each standalone site a concrete existing owner callback,
returned framework awaitable, or direct synchronous completion. Follow the
listed sequence where a site conflates phases. Sites inside finite typing/pane
loops are shown too. Polling body pauses are already covered by Appendix A and
the helper table. STARTUP sites which assert only synchronous mounted state
need no additional wait: retained Textual `run_test` awaits its app-ready Event
and screen queue fence before yielding.

| File | Test | Sites and literal calls | Owner group / classification |
|---|---|---|---|
| `test_tui_action_handlers.py` | `_select_palette` | `121: context.pilot.pause()`; `125: context.pilot.pause()`; `135: context.pilot.pause()` | 121: MOUNT; 125: PALETTE; 135: INPUT → DISMISS (and MOUNT when dispatcher opens a form) |
| `test_tui_action_handlers.py` | `_submit_form` | `197: context.pilot.pause()` | 197: SUBMIT (ACTION separately awaited by caller) |
| `test_tui_action_handlers.py` | `_cancel_confirmation` | `209: context.pilot.pause()` | 209: DISMISS |
| `test_tui_action_handlers.py` | `_accept_confirmation` | `220: context.pilot.pause()` | 220: DISMISS (ACTION separately awaited by caller) |
| `test_tui_action_handlers.py` | `_channel_rename` | `430: context.pilot.pause()` | 430: MOUNT |
| `test_tui_action_handlers.py` | `_search_open_result` | `648: context.pilot.pause()` | 648: VIEWPORT; existing exact search-anchor/navigation Events already fence this pause |
| `test_tui_action_handlers.py` | `_system_dump` | `690: context.pilot.pause()` | 690: MOUNT |
| `test_tui_action_handlers.py` | `_command_open` | `710: context.pilot.pause()` | 710: MOUNT |
| `test_tui_action_handlers.py` | `_application_quit` | `722: context.pilot.pause()` | 722: EXIT |
| `test_tui_action_handlers.py` | `_summon_dismiss` | `842: context.pilot.pause()`; `850: context.pilot.pause()` | 842: MOUNT; 850: MOUNT |
| `test_tui_action_routes.py` | `_drive_palette` | `124: pilot.pause()` | 124: PALETTE |
| `test_tui_action_routes.py` | `test_every_declared_route_reaches_the_central_dispatcher_through_its_real_producer.exercise` | `254: pilot.pause()` | 254: DRAFT; `_update_context_affordances` itself is STATIC |
| `test_tui_app.py` | `test_real_app_exposes_low_chrome_surfaces_and_mode_status.exercise` | `153: pilot.pause()` | 153: STARTUP; `run_test` entry already awaited framework ready and screen queue fence |
| `test_tui_app.py` | `test_real_empty_search_renders_no_matches_in_the_native_screen.exercise` | `320: pilot.pause()` | 320: MOUNT |
| `test_tui_app.py` | `test_too_small_shields_a_nested_modal_stack_and_restores_exact_focus.exercise` | `468: pilot.pause()`; `473: pilot.pause()` | 468: MOUNT; 473: MOUNT |
| `test_tui_app.py` | `test_real_transcript_viewport_anchor_survives_width_reflow.exercise` | `553: pilot.pause()`; `556: pilot.pause()`; `577: pilot.pause()` | 553: RESIZE; 556: VIEWPORT after exact pane input; 577: VIEWPORT via actual anchor scroll completion |
| `test_tui_app.py` | `test_direct_command_shadow_tab_keeps_argument_input_active.exercise` | `680: pilot.pause()`; `684: pilot.pause()` | 680: MOUNT then SUGGESTION; 684: SUGGESTION via Tab owner |
| `test_tui_app.py` | `test_direct_command_typing_stays_field_owned_without_a_list.exercise` | `707: pilot.pause()` | 707: MOUNT then input handler completion |
| `test_tui_app.py` | `test_text_command_quit_alias_uses_guarded_tui_quit.exercise` | `736: pilot.pause()` | 736: EXIT |
| `test_tui_app.py` | `test_composer_quit_alias_promotes_before_guarded_execution.exercise` | `762: pilot.pause()` | 762: EXIT |
| `test_tui_app.py` | `test_text_quit_alias_preserves_guarded_quit_blocker.exercise` | `786: pilot.pause()` | 786: INPUT after guarded quit handler; retained exit history stays empty |
| `test_tui_app.py` | `test_global_quit_chords_use_guarded_owner_from_compose.exercise` | `825: pilot.pause()` | 825: INPUT after guarded quit handler; retained exit history stays empty |
| `test_tui_app.py` | `test_global_quit_chords_exit_from_every_tui_owned_surface.exercise` | `878: pilot.pause()`; `884: pilot.pause()` | 878: MOUNT; 884: EXIT |
| `test_tui_app.py` | `test_repeated_global_quit_does_not_stack_owned_run_confirmation.exercise` | `914: pilot.pause()`; `917: pilot.pause()`; `923: pilot.pause()`; `928: pilot.pause()` | 914: MOUNT; 917: MOUNT; 923: INPUT after repeated-quit rejection; inspect retained stack; 928: DISMISS |
| `test_tui_app.py` | `test_blocked_global_quit_preserves_active_modal.exercise` | `956: pilot.pause()`; `959: pilot.pause()` | 956: MOUNT; 959: INPUT after guarded-quit refusal |
| `test_tui_app.py` | `test_unknown_colon_text_stays_message_and_command_cancel_preserves_draft.exercise` | `1016: pilot.pause()`; `1026: pilot.pause()` | 1016: DISMISS then FOCUS; 1026: INPUT after unsupported chord dispatch |
| `test_tui_app.py` | `test_text_command_rename_preserves_draft.exercise` | `1075: pilot.pause()` | 1075: MOUNT |
| `test_tui_app.py` | `test_successful_promoted_command_clears_unchanged_originating_draft.exercise` | `1241: pilot.pause()` | 1241: DISMISS then DRAFT/ACTION completion |
| `test_tui_app.py` | `test_promoted_command_does_not_clear_a_newer_originating_draft.exercise` | `1266: pilot.pause()`; `1268: pilot.pause()` | 1266: DRAFT; 1268: DISMISS then DRAFT/ACTION completion |
| `test_tui_app.py` | `test_command_palette_mouse_activation_opens_summon_argument_form.exercise` | `1322: pilot.pause()` | 1322: PALETTE |
| `test_tui_app.py` | `test_command_palette_double_click_dismisses_only_once.exercise` | `1349: pilot.pause()` | 1349: DISMISS; retain duplicate activation count |
| `test_tui_app.py` | `test_resolved_attach_confirmation_never_opens_stale_modal.exercise` | `1866: pilot.pause()` | 1866: DECISION after real confirmation-request handler rejects resolved request |
| `test_tui_app.py` | `test_central_dispatch_enforces_applicability_before_forms_and_mouse_handlers.exercise` | `2029: pilot.pause()` | 2029: INPUT after `_dispatch_action_invocation` rejects applicability |
| `test_tui_app.py` | `test_help_and_errors_open_a_visible_inspector_at_medium_and_compact_sizes.exercise` | `2292: pilot.pause()` | 2292: RESIZE then STATIC `_show_error` |
| `test_tui_app.py` | `test_compose_send_failure_is_visible_and_preserves_the_draft.exercise` | `2355: pilot.pause()`; `2367: pilot.pause()` | 2355: DRAFT then FOCUS; 2367: STATIC `_apply_send_result` returned; REFRESH if placement geometry needed |
| `test_tui_app.py` | `test_superseding_navigation_clears_and_rejects_stale_search.exercise` | `2671: pilot.pause()`; `2690: pilot.pause()` | 2671: STATIC dispatcher already set searching; 2690: SEARCH exact old-generation `_apply_search_context` rejection |
| `test_tui_app.py` | `test_compact_mouse_pane_affordance_reaches_each_logical_surface.exercise` | `2799: pilot.pause()`; `2806: pilot.pause()` | 2799: STATIC `_render_inspector`; REFRESH for pane geometry; 2806: INPUT then REFRESH for finite pane cycle |
| `test_tui_app.py` | `test_native_form_keeps_values_and_renders_domain_error_inline.exercise` | `2930: pilot.pause()` | 2930: MOUNT |
| `test_tui_app.py` | `test_user_scroll_supersedes_pending_search_anchor_restore.exercise` | `3046: pilot.pause()`; `3052: pilot.pause()` | 3046: REFRESH for exact added transcript options; 3052: VIEWPORT exact user-intent settle |
| `test_tui_app.py` | `test_programmatic_scroll_does_not_claim_user_viewport_intent.exercise` | `3125: pilot.pause()` | 3125: VIEWPORT exact programmatic scroll `on_complete` |
| `test_tui_app.py` | `test_completed_search_restore_releases_viewport_ownership.exercise` | `3212: pilot.pause()`; `3216: pilot.pause()` | 3212: VIEWPORT exact search restore completion; 3216: VIEWPORT programmatic scroll `on_complete` |
| `test_tui_app.py` | `test_overlapping_send_completion_only_clears_its_own_draft.exercise` | `3482: pilot.pause()`; `3486: pilot.pause()` | 3482: DRAFT; 3486: DRAFT |
| `test_tui_app.py` | `test_transcript_option_render_keeps_hanging_indent_and_height_in_sync.exercise` | `3727: pilot.pause()` | 3727: REFRESH exact transcript render and row measurement |
| `test_tui_app.py` | `test_programmatic_draft_restore_never_promotes.open_target` | `3904: pilot.pause()` | 3904: INPUT exact highlighted-change owner |
| `test_tui_app.py` | `test_programmatic_draft_restore_never_promotes.exercise` | `3923: pilot.pause(0.005)`; `3924: pilot.pause(0.05)`; `3927: pilot.pause(0.05)`; `3931: pilot.pause(0.05)`; `3933: pilot.pause(0.1)`; `3935: pilot.pause(0.2)` | 3923: INPUT finite typing action (no delay); 3924: MOUNT/SUGGESTION for resulting command screen; 3927: DISMISS; 3931: INPUT after escape mode transition; 3933: CONVERSATION already awaited by `open_target`; no extra delay; 3935: CONVERSATION/DRAFT restore exact handler, then retained promotion history |
| `test_tui_app.py` | `test_command_line_open_keeps_live_deliveries_rendering.exercise` | `3970: pilot.pause()`; `3979: pilot.pause()` | 3970: INPUT exact highlighted-change owner; 3979: MOUNT/SUGGESTION command line ready |
| `test_tui_app.py` | `test_real_rapid_resize_burst_keeps_latest_state_and_live_delivery.exercise` | `4032: pilot.pause()`; `4069: pilot.pause(0.2)` | 4032: DRAFT; 4069: RESIZE all burst generations terminal, then STATIC stability |
| `test_tui_app.py` | `test_action_browser_and_command_line_are_named_distinctly.exercise` | `4144: pilot.pause()`; `4148: pilot.pause()` | 4144: STARTUP; `run_test` entry already fences mount; 4148: INPUT help handler then STATIC inspector assertion |
| `test_tui_app.py` | `test_history_anchor_rerender_preserves_selected_message.exercise` | `4182: pilot.pause(0.1)` | 4182: VIEWPORT current-generation anchor completion |
| `test_tui_app.py` | `test_too_small_shield_clears_even_when_covered_by_a_modal.exercise` | `4196: pilot.pause()`; `4199: pilot.pause()`; `4202: pilot.pause()`; `4205: pilot.pause(0.1)` | 4196: RESIZE then MOUNT shield; 4199: MOUNT; 4202: RESIZE; 4205: DISMISS exact confirmation and covered-shield retirement |
| `test_tui_app.py` | `test_reply_form_with_vanished_selection_stays_recoverable.exercise` | `4226: pilot.pause()`; `4229: pilot.pause()`; `4232: pilot.pause(0.1)`; `4238: pilot.pause()` | 4226: MOUNT; 4229: INPUT field-changed handler; 4232: SUBMIT actual no-selection validation handler (no worker); 4238: DISMISS |
| `test_tui_app.py` | `test_unselected_composer_draft_carries_into_first_conversation.exercise` | `4266: pilot.pause()`; `4273: pilot.pause()` | 4266: DRAFT; 4273: INPUT exact highlighted-change owner |
| `test_tui_app.py` | `test_dump_submission_failure_stays_recoverable.exercise` | `4312: pilot.pause()`; `4314: pilot.pause()` | 4312: STARTUP; already fenced at `run_test` entry; 4314: STATIC `_run_command_dump` catches/rendered synchronous refusal |
| `test_tui_app.py` | `test_delivery_during_teardown_is_rejected_without_raising.exercise` | `4331: pilot.pause()` | 4331: STARTUP; then direct synchronous stale delivery checks |
| `test_tui_app.py` | `test_stale_intent_snapshot_is_not_applied.exercise` | `4363: pilot.pause()` | 4363: STARTUP; then direct synchronous stale snapshot check |
| `test_tui_chat.py` | `test_explicit_reply_open_commits_claimed_history_and_watches_both_surfaces` | `500: time.sleep(0.1)` | 500: CORES/CONVERSATION old watcher retirement is already fenced by completed switch, then close before unread assertion |
| `test_tui_chat.py` | `test_transcript_decodes_literal_escapes_toward_sender_intent.exercise` | `542: pilot.pause()` | 542: INPUT exact highlighted-change owner |
| `test_tui_chat.py` | `test_notification_refresh_keeps_scrolled_transcript_position.exercise` | `616: pilot.pause()` | 616: INPUT exact highlighted-change owner |
| `test_tui_screens.py` | `test_draft_recovery_screen_previews_multiline_and_escape_retains.exercise` | `38: pilot.pause()`; `44: pilot.pause()` | 38: MOUNT then STATIC recovery preview; 44: DISMISS |
| `test_tui_screens.py` | `test_native_form_is_labelled_masked_clickable_and_validates_visually.exercise` | `83: pilot.pause()`; `85: pilot.pause()` | 83: INPUT field-changed handler; 85: SUBMIT host handler then DISMISS |
| `test_tui_screens.py` | `test_native_form_enter_and_tab_follow_field_submit_cancel_order.exercise` | `125: pilot.pause()` | 125: SUBMIT host handler then DISMISS |
| `test_tui_screens.py` | `test_native_form_ignores_duplicate_submit_while_domain_work_is_pending.exercise` | `150: pilot.pause()`; `152: pilot.pause()` | 150: SUBMIT host handler; 152: SUBMIT exact duplicate rejection handler; assert retained submissions |
| `test_tui_screens.py` | `test_native_form_escape_waits_for_pending_domain_work.exercise` | `170: pilot.pause()`; `172: pilot.pause()` | 170: SUBMIT pending transition; 172: INPUT exact cancel refusal while pending |
| `test_tui_screens.py` | `test_command_palette_filters_and_returns_the_same_action_id.exercise` | `213: pilot.pause()` | 213: DISMISS supplied palette result callback |
| `test_tui_screens.py` | `test_command_line_screen_shows_colon_affordance_and_returns_typed_input.exercise` | `237: pilot.pause()` | 237: DISMISS command-line result callback |
| `test_tui_screens.py` | `test_command_line_screen_accepts_summon_provider_syntax.exercise` | `262: pilot.pause()` | 262: DISMISS command-line result callback |
| `test_tui_screens.py` | `test_summon_start_screen_collects_every_typed_request_field.exercise` | `351: pilot.pause()` | 351: DISMISS Summon form result callback |
| `test_tui_screens.py` | `test_summon_start_screen_reports_invalid_rate_inline.exercise` | `386: pilot.pause()` | 386: SUBMIT inline invalid-rate validation |
| `test_tui_screens.py` | `test_search_completion_after_escape_is_ignored.exercise` | `527: pilot.pause()`; `531: pilot.pause(0.1)` | 527: DISMISS exact SearchScreen; 531: SEARCH exact late `_apply_results` generation rejection |
| `test_tui_screens.py` | `test_palette_confirmation_and_form_errors_escape_terminal_controls.exercise` | `571: pilot.pause()`; `578: pilot.pause()`; `591: pilot.pause()` | 571: MOUNT; 578: MOUNT; 591: MOUNT |
| `test_tui_screens.py` | `test_summon_provider_projection_escapes_terminal_controls.exercise` | `612: pilot.pause()` | 612: INPUT real Select value watcher then REFRESH children |
| `test_tui_screens.py` | `test_palette_opens_highlighted_and_updown_select_from_query.exercise` | `648: pilot.pause()`; `654: pilot.pause()` | 648: MOUNT then PALETTE initial render; 654: DISMISS palette result callback |
| `test_tui_screens.py` | `test_palette_no_match_shows_empty_state_and_enter_stays_inert.exercise` | `675: pilot.pause()`; `682: pilot.pause(0.05)`; `686: pilot.pause()` | 675: PALETTE; 682: INPUT exact inert Enter handler, then retained selected history; 686: DISMISS |
| `test_tui_screens.py` | `test_palette_offers_run_as_command_handoff_for_known_root.exercise` | `716: pilot.pause()`; `724: pilot.pause()` | 716: PALETTE; 724: DISMISS command handoff result callback |
| `test_tui_screens.py` | `test_command_line_has_no_completion_list_and_reconciles_on_mount.exercise` | `749: pilot.pause()` | 749: MOUNT then command `on_mount`/FOCUS |
| `test_tui_screens.py` | `test_command_line_shadow_cycles_and_tab_accepts.exercise` | `772: pilot.pause(0.05)`; `777: pilot.pause(0.05)`; `781: pilot.pause()` | 772: SUGGESTION exact `_on_suggestion_ready`; 777: SUGGESTION synchronous `_cycle_shadow`; 781: SUGGESTION `action_accept_shadow` then FOCUS |
| `test_tui_selection.py` | `test_transcript_drag_selects_wrapped_display_lines_without_moving_row.exercise` | `41: pilot.pause()`; `49: pilot.pause()` | 41: INPUT highlighted change then REFRESH; 49: SELECTION |
| `test_tui_selection.py` | `test_transcript_selection_preserves_displayed_trailing_spaces.exercise` | `72: pilot.pause()`; `76: pilot.pause()` | 72: STARTUP/REFRESH initial transcript geometry; 76: SELECTION |
| `test_tui_selection.py` | `test_single_click_selects_row_without_arming_auto_copy.exercise` | `128: pilot.pause()`; `139: pilot.pause()` | 128: VIEWPORT/REFRESH exact transcript render; 139: INPUT real click/highlight handler |
| `test_tui_selection.py` | `test_y_copies_current_selection_through_textual_osc52.exercise` | `174: pilot.pause()`; `179: pilot.pause()` | 174: VIEWPORT/REFRESH exact transcript render; 179: SELECTION |
| `test_tui_selection.py` | `test_transcript_rebuild_cancels_pending_auto_copy.exercise` | `233: pilot.pause()`; `254: pilot.pause()`; `260: pilot.pause()` | 233: VIEWPORT/REFRESH exact transcript render; 254: SELECTION; 260: STATIC `_render_messages` cancels captured timer, then REFRESH if needed |
| `test_tui_selection.py` | `test_copy_failure_is_safe_and_keeps_selection.exercise` | `290: pilot.pause()`; `294: pilot.pause()` | 290: VIEWPORT/REFRESH exact transcript render; 294: SELECTION |
| `test_tui_selection.py` | `test_completed_selection_auto_copy_resets_for_changed_selection.exercise` | `390: pilot.pause()`; `411: pilot.pause()`; `419: pilot.pause()` | 390: VIEWPORT/REFRESH exact transcript render; 411: SELECTION; 419: SELECTION |
| `test_tui_summon.py` | `test_real_app_lease_suspension_failure_exits_instead_of_lingering.exercise` | `1087: pilot.pause()` | 1087: STARTUP |
| `test_tui_summon.py` | `test_stale_or_shutdown_lease_request_never_suspends_or_exits.exercise` | `1115: pilot.pause()`; `1126: pilot.pause(0.05)` | 1115: STARTUP; 1126: LEASE restored Event and real hold return already fence refusal; inspect retained exits |
| `test_tui_summon.py` | `test_quit_with_pending_run_offers_cancel_and_quit_dialog.exercise` | `1256: pilot.pause()`; `1259: pilot.pause()` | 1256: STARTUP; 1259: MOUNT |
| `test_tui_summon.py` | `test_cancelled_attach_confirmation_dismisses_stale_dialog.exercise` | `1289: pilot.pause()` | 1289: STARTUP |
| `test_tui_summon.py` | `test_cancelled_attach_dismiss_failure_cannot_replace_resolution.exercise` | `1342: pilot.pause()`; `1361: pilot.pause()` | 1342: STARTUP; 1361: DISMISS |
| `test_tui_summon.py` | `test_attach_resolution_during_push_retries_failed_dismiss_schedule.exercise` | `1386: pilot.pause()` | 1386: STARTUP |
| `test_tui_summon.py` | `test_setup_recovery_offer_leads_with_member_and_escaped_excerpt.exercise` | `1486: pilot.pause()` | 1486: STARTUP |
| `test_tui_summon.py` | `test_setup_recovery_offer_decline_skips_the_acknowledgement_phase.exercise` | `1536: pilot.pause()` | 1536: STARTUP |
| `test_tui_summon.py` | `test_setup_recovery_acknowledgement_decline_resolves_false.exercise` | `1573: pilot.pause()` | 1573: STARTUP |
| `test_tui_summon.py` | `test_worker_resolution_dismisses_the_pending_offer_modal.exercise` | `1611: pilot.pause()` | 1611: STARTUP |
| `test_tui_summon.py` | `test_bootstrap_attach_confirmation_content_is_unchanged.exercise` | `1650: pilot.pause()` | 1650: STARTUP |
| `test_tui_summon.py` | `test_summon_status_transitions_do_not_clobber_unrelated_operation.exercise` | `1730: pilot.pause()` | 1730: STARTUP |
| `test_tui_summon.py` | `test_setup_recovery_offer_reaches_a_pending_owned_tui_and_completes.exercise` | `2160: pilot.pause()` | 2160: STARTUP |
| `test_tui_summon.py` | `test_setup_recovery_decline_continues_detached_with_enriched_give_up.exercise` | `2297: pilot.pause()` | 2297: STARTUP |
| `test_tui_summon.py` | `test_host_shutdown_during_offer_spawns_nothing_further.exercise` | `2358: pilot.pause()` | 2358: STARTUP |
| `test_tui_textual_contract.py` | `test_owned_display_sinks_escape_initial_and_updated_content.exercise` | `154: pilot.pause()` | 154: STARTUP; ready/mount already retained by `run_test` |
| `test_tui_textual_contract.py` | `test_composer_preserves_multiline_paste.exercise` | `310: pilot.pause()` | 310: DRAFT/TextArea exact Paste handler completion |
| `test_tui_textual_contract.py` | `test_retained_textual_pilot_click_focus_and_resize.exercise` | `396: pilot.pause()` | 396: STARTUP then exact initial `on_resize` receipt |

Embedded exceptions: `test_tui_launch.py:284` has one child startup
`pilot.pause()` (STARTUP). `test_tui_textual_contract.py:615` has the
0.25 s native lease-exclusion window discussed above (LEASE).

## Appendix C: existing retained waits and resource fences

These are already event/future/barrier/join driven, not a second scheduling
loop. Keep their exact producer ownership and current explicit caps. A shared
observer may decorate their outcome and phase diagnostics. The list includes
both outer async wait and its inner Event wait where present; it is a source
inventory, not a count of independent deadlines. Teardown joins must still
assert retirement; final Future completion alone does not prove reader
retirement.

| File:line | Test / helper | Existing wait or fence |
|---|---|---|
| `test_tui_action_handlers.py:168` | `_open_general` | `asyncio.wait_for(conversation_applied.wait(), timeout=5)` |
| `test_tui_action_handlers.py:246` | `_workspace_initialize` | `asyncio.wait_for(action_completed.wait(), timeout=5)` |
| `test_tui_action_handlers.py:267` | `_identity_rejoin` | `context.app._domain.show_identity().result(timeout=5)` |
| `test_tui_action_handlers.py:633` | `_search_open_result` | `asyncio.wait_for(search_context_applied.wait(), timeout=5)` |
| `test_tui_action_handlers.py:634` | `_search_open_result` | `asyncio.wait_for(navigation_refresh_applied.wait(), timeout=5)` |
| `test_tui_action_handlers.py:635` | `_search_open_result` | `asyncio.wait_for(search_anchor_restore_finished.wait(), timeout=5)` |
| `test_tui_action_handlers.py:770` | `run_foreground` | `self.release.wait(5)` |
| `test_tui_action_handlers.py:978` | `test_every_action_reaches_a_concrete_handler.exercise` | `"\n".join( f"post-search-anchor line {index}" for index in range(40) )` |
| `test_tui_app.py:75` | `_await_summon_confirmation` | `asyncio.wait_for(started_futures.get(), timeout=5.0)` |
| `test_tui_app.py:81` | `_await_summon_confirmation` | `asyncio.wait( {confirmation_task, worker_task}, timeout=15.0, return_when=asyncio.FIRST_COMPLETED, )` |
| `test_tui_app.py:103` | `_await_cancelled_summon_run` | `asyncio.wait_for(worker_done.wait(), timeout=15.0)` |
| `test_tui_app.py:263` | `test_token_only_rejoin_form_reaches_the_real_public_client.exercise` | `asyncio.wait_for( result_ready.wait(), timeout=20.0, )` |
| `test_tui_app.py:272` | `test_token_only_rejoin_form_reaches_the_real_public_client.exercise` | `app._domain.show_identity().result(timeout=10)` |
| `test_tui_app.py:325` | `test_real_empty_search_renders_no_matches_in_the_native_screen.exercise` | `asyncio.wait_for( asyncio.wrap_future(search_futures[0]), timeout=20.0, )` |
| `test_tui_app.py:331` | `test_real_empty_search_renders_no_matches_in_the_native_screen.exercise` | `asyncio.wait_for(refreshed.wait(), timeout=5.0)` |
| `test_tui_app.py:535` | `test_real_transcript_viewport_anchor_survives_width_reflow.exercise` | `asyncio.wait_for(transcript_rendered.wait(), timeout=5)` |
| `test_tui_app.py:544` | `test_real_transcript_viewport_anchor_survives_width_reflow.exercise` | `asyncio.wait_for(scroll_applied.wait(), timeout=5)` |
| `test_tui_app.py:605` | `test_real_transcript_viewport_anchor_survives_width_reflow.exercise` | `asyncio.wait_for(restored.wait(), timeout=5)` |
| `test_tui_app.py:1837` | `test_tui_unmount_cancels_pending_attach_confirmation` | `worker.join(timeout=5.0)` |
| `test_tui_app.py:2222` | `test_direct_message_header_and_composer_use_actor_scoped_label.exercise` | `asyncio.wait_for(navigation_applied.wait(), timeout=5)` |
| `test_tui_app.py:2502` | `test_live_reply_notification_refreshes_the_contextual_reply_marker.exercise` | `asyncio.wait_for(reply_navigation_applied.wait(), timeout=5)` |
| `test_tui_app.py:3088` | `test_user_scroll_supersedes_pending_search_anchor_restore.exercise` | `asyncio.wait_for(rendered.wait(), timeout=5)` |
| `test_tui_app.py:3226` | `test_completed_search_restore_releases_viewport_ownership.exercise` | `asyncio.wait_for(rendered.wait(), timeout=5)` |
| `test_tui_app.py:3493` | `test_overlapping_send_completion_only_clears_its_own_draft.exercise` | `asyncio.wait_for(send_results_applied.get(), timeout=5)` |
| `test_tui_app.py:3500` | `test_overlapping_send_completion_only_clears_its_own_draft.exercise` | `asyncio.wait_for(send_results_applied.get(), timeout=5)` |
| `test_tui_chat.py:162` | `test_navigation_uses_public_joined_channels_and_actor_scoped_dms` | `session.refresh_navigation().result(timeout=5)` |
| `test_tui_chat.py:203` | `test_only_active_conversation_advances_while_inactive_stays_unread` | `session.open_conversation("general").result(timeout=5)` |
| `test_tui_chat.py:212` | `test_only_active_conversation_advances_while_inactive_stays_unread` | `session.refresh_navigation().result(timeout=5)` |
| `test_tui_chat.py:255` | `test_latest_switch_wins_and_stops_old_watcher_before_replacement` | `first.result(timeout=5)` |
| `test_tui_chat.py:256` | `test_latest_switch_wins_and_stops_old_watcher_before_replacement` | `second.result(timeout=5)` |
| `test_tui_chat.py:299` | `test_repeated_target_switches_retire_broker_worker_cores` | `session.open_conversation(target).result(timeout=5)` |
| `test_tui_chat.py:335` | `test_shutdown_rejection_does_not_acknowledge_chat_message` | `session.open_conversation("general").result(timeout=5)` |
| `test_tui_chat.py:337` | `test_shutdown_rejection_does_not_acknowledge_chat_message` | `rejected.wait(5)` |
| `test_tui_chat.py:373` | `test_current_delivery_rejection_reports_visible_degradation_owner_event` | `session.open_conversation("general").result(timeout=5)` |
| `test_tui_chat.py:375` | `test_current_delivery_rejection_reports_visible_degradation_owner_event` | `reported.wait(5)` |
| `test_tui_chat.py:481` | `test_explicit_reply_open_commits_claimed_history_and_watches_both_surfaces` | `session.open_conversation( "general", reply_thread=first_reply.thread, ).result(timeout=5)` |
| `test_tui_chat.py:496` | `test_explicit_reply_open_commits_claimed_history_and_watches_both_surfaces` | `session.open_conversation("general").result(timeout=5)` |
| `test_tui_chat.py:623` | `test_notification_refresh_keeps_scrolled_transcript_position.exercise` | `asyncio.wait_for(probe.history_caught_up.wait(), timeout=5)` |
| `test_tui_chat.py:634` | `test_notification_refresh_keeps_scrolled_transcript_position.exercise` | `asyncio.wait_for(scroll_applied.wait(), timeout=5)` |
| `test_tui_chat.py:656` | `test_notification_refresh_keeps_scrolled_transcript_position.exercise` | `asyncio.wait_for( probe.notification_refresh_applied.wait(), timeout=5, )` |
| `test_tui_domain.py:65` | `test_native_identity_channel_message_search_and_context_flow` | `actions.show_identity().result(timeout=5)` |
| `test_tui_domain.py:66` | `test_native_identity_channel_message_search_and_context_flow` | `actions.set_persona("reviewer").result(timeout=5)` |
| `test_tui_domain.py:67` | `test_native_identity_channel_message_search_and_context_flow` | `actions.members("general").result(timeout=5)` |
| `test_tui_domain.py:68` | `test_native_identity_channel_message_search_and_context_flow` | `actions.set_topic("general", "Release coordination").result(timeout=5)` |
| `test_tui_domain.py:70` | `test_native_identity_channel_message_search_and_context_flow` | `actions.show_topic("general").result(timeout=5)` |
| `test_tui_domain.py:72` | `test_native_identity_channel_message_search_and_context_flow` | `actions.send_message("general", "searchable marker").result(timeout=5)` |
| `test_tui_domain.py:73` | `test_native_identity_channel_message_search_and_context_flow` | `actions.search("searchable marker").result(timeout=5)` |
| `test_tui_domain.py:75` | `test_native_identity_channel_message_search_and_context_flow` | `actions.open_search_result(hit, before=1, after=1).result(timeout=5)` |
| `test_tui_domain.py:78` | `test_native_identity_channel_message_search_and_context_flow` | `actions.react_message(sent.ts, "ack").result(timeout=5)` |
| `test_tui_domain.py:80` | `test_native_identity_channel_message_search_and_context_flow` | `actions.delete_message(sent.ts).result(timeout=5)` |
| `test_tui_domain.py:82` | `test_native_identity_channel_message_search_and_context_flow` | `actions.clear_topic("general").result(timeout=5)` |
| `test_tui_domain.py:108` | `test_direct_message_and_reply_flows_keep_core_target_semantics` | `actions.start_direct_message("bob", "hello privately").result( timeout=5 )` |
| `test_tui_domain.py:111` | `test_direct_message_and_reply_flows_keep_core_target_semantics` | `actions.reply_message("general", origin.ts, "reviewed").result( timeout=5 )` |
| `test_tui_domain.py:139` | `test_empty_real_search_returns_the_domain_empty_collection` | `actions.search("nothing-can-match-this").result(timeout=5)` |
| `test_tui_domain.py:173` | `test_empty_read_inbox_log_and_dm_list_return_empty_collections` | `actions.read_messages().result(timeout=10)` |
| `test_tui_domain.py:174` | `test_empty_read_inbox_log_and_dm_list_return_empty_collections` | `actions.inbox().result(timeout=10)` |
| `test_tui_domain.py:175` | `test_empty_read_inbox_log_and_dm_list_return_empty_collections` | `actions.list_threads(direct_messages=True).result(timeout=10)` |
| `test_tui_domain.py:198` | `test_start_direct_message_normalizes_leading_at` | `actions.start_direct_message("@bob", "typed with an at").result( timeout=10 )` |
| `test_tui_domain.py:258` | `test_session_close_without_wait_returns_promptly_despite_parked_commit.blocking_commit` | `release.wait(10)` |
| `test_tui_domain.py:269` | `test_session_close_without_wait_returns_promptly_despite_parked_commit` | `parked.wait(10)` |
| `test_tui_domain.py:300` | `test_rejected_reply_open_does_not_claim_unread_replies` | `session.open_conversation("general", reply_thread=reply_thread).result( timeout=10 )` |
| `test_tui_domain.py:304` | `test_rejected_reply_open_does_not_claim_unread_replies` | `session.submit_client_operation( lambda client: client.read_unread(reply_thread) ).result(timeout=10)` |
| `test_tui_screens.py:613` | `test_summon_provider_projection_escapes_terminal_controls.exercise` | `"\n".join(str(widget.render()) for widget in select.query("*"))` |
| `test_tui_summon.py:74` | `run_foreground` | `self.release.wait(5)` |
| `test_tui_summon.py:84` | `test_owned_run_tracks_exact_ready_handle_and_never_installs_signals` | `controller.started.wait(5)` |
| `test_tui_summon.py:96` | `test_owned_run_tracks_exact_ready_handle_and_never_installs_signals` | `worker.result(timeout=5)` |
| `test_tui_summon.py:118` | `test_pending_owned_run_blocks_quit_until_readiness_or_return.run_foreground` | `ready_gate.wait(5)` |
| `test_tui_summon.py:133` | `test_pending_owned_run_blocks_quit_until_readiness_or_return` | `controller.started.wait(5)` |
| `test_tui_summon.py:135` | `test_pending_owned_run_blocks_quit_until_readiness_or_return` | `worker.result(timeout=5)` |
| `test_tui_summon.py:165` | `test_control_work_is_not_starved_by_eight_blocked_foreground_runs.run_foreground` | `self.release.wait(5)` |
| `test_tui_summon.py:171` | `test_control_work_is_not_starved_by_eight_blocked_foreground_runs` | `controller.all_started.wait(5)` |
| `test_tui_summon.py:172` | `test_control_work_is_not_starved_by_eight_blocked_foreground_runs` | `operations.submit_status("agent").result(timeout=1)` |
| `test_tui_summon.py:176` | `test_control_work_is_not_starved_by_eight_blocked_foreground_runs` | `operations.submit_stop("agent").result(timeout=1)` |
| `test_tui_summon.py:183` | `test_control_work_is_not_starved_by_eight_blocked_foreground_runs` | `worker.result(timeout=5)` |
| `test_tui_summon.py:208` | `test_close_before_readiness_stops_late_handle_without_ready_callback.run_foreground` | `self.publish_readiness.wait(5)` |
| `test_tui_summon.py:210` | `test_close_before_readiness_stops_late_handle_without_ready_callback.run_foreground` | `self.handle.stop_requested.wait(1)` |
| `test_tui_summon.py:220` | `test_close_before_readiness_stops_late_handle_without_ready_callback` | `controller.awaiting_readiness.wait(5)` |
| `test_tui_summon.py:224` | `test_close_before_readiness_stops_late_handle_without_ready_callback` | `worker.result(timeout=5)` |
| `test_tui_summon.py:241` | `test_owned_exit_waits_exact_worker_and_reports_completion` | `controller.started.wait(5)` |
| `test_tui_summon.py:243` | `test_owned_exit_waits_exact_worker_and_reports_completion` | `controller.handle.stop_requested.wait(5)` |
| `test_tui_summon.py:246` | `test_owned_exit_waits_exact_worker_and_reports_completion` | `worker.result(timeout=5)` |
| `test_tui_summon.py:247` | `test_owned_exit_waits_exact_worker_and_reports_completion` | `shutdown.result(timeout=5)` |
| `test_tui_summon.py:271` | `test_pending_owned_exit_is_not_treated_as_stoppable_ready_run.run_foreground` | `ready_gate.wait(5)` |
| `test_tui_summon.py:284` | `test_pending_owned_exit_is_not_treated_as_stoppable_ready_run` | `operations.stop_owned_and_wait(timeout=0.01).result(timeout=5)` |
| `test_tui_summon.py:289` | `test_pending_owned_exit_is_not_treated_as_stoppable_ready_run` | `controller.started.wait(5)` |
| `test_tui_summon.py:291` | `test_pending_owned_exit_is_not_treated_as_stoppable_ready_run` | `worker.result(timeout=5)` |
| `test_tui_summon.py:357` | `test_overlapping_log_bridges_restore_out_of_order_without_stale_owner.hold_scope` | `restore.wait(5)` |
| `test_tui_summon.py:370` | `test_overlapping_log_bridges_restore_out_of_order_without_stale_owner` | `first_installed.wait(5)` |
| `test_tui_summon.py:372` | `test_overlapping_log_bridges_restore_out_of_order_without_stale_owner` | `second_installed.wait(5)` |
| `test_tui_summon.py:375` | `test_overlapping_log_bridges_restore_out_of_order_without_stale_owner` | `first_thread.join(timeout=5)` |
| `test_tui_summon.py:382` | `test_overlapping_log_bridges_restore_out_of_order_without_stale_owner` | `second_thread.join(timeout=5)` |
| `test_tui_summon.py:391` | `test_overlapping_log_bridges_restore_out_of_order_without_stale_owner` | `first_thread.join(timeout=5)` |
| `test_tui_summon.py:393` | `test_overlapping_log_bridges_restore_out_of_order_without_stale_owner` | `second_thread.join(timeout=5)` |
| `test_tui_summon.py:407` | `test_controller_queries_run_off_caller_thread` | `operations.submit_list().result(timeout=5)` |
| `test_tui_summon.py:408` | `test_controller_queries_run_off_caller_thread` | `operations.submit_status("agent").result(timeout=5)` |
| `test_tui_summon.py:412` | `test_controller_queries_run_off_caller_thread` | `operations.submit_stop("agent").result(timeout=5)` |
| `test_tui_summon.py:498` | `join_handler` | `self._handler.join(timeout=5)` |
| `test_tui_summon.py:543` | `test_terminal_attach_confirmation_is_exclusive_and_precedes_lease.run` | `leave_lease.wait(timeout=2.0)` |
| `test_tui_summon.py:570` | `test_terminal_attach_confirmation_is_exclusive_and_precedes_lease` | `lease_granted.wait(timeout=2.0)` |
| `test_tui_summon.py:575` | `test_terminal_attach_confirmation_is_exclusive_and_precedes_lease` | `worker.join(timeout=5.0)` |
| `test_tui_summon.py:608` | `test_terminal_lease_ownership_survives_distinct_driver_phase_threads.confirm_on_first_phase` | `keep_confirmation_thread.wait(timeout=2.0)` |
| `test_tui_summon.py:629` | `test_terminal_lease_ownership_survives_distinct_driver_phase_threads` | `lease.join(timeout=2.0)` |
| `test_tui_summon.py:632` | `test_terminal_lease_ownership_survives_distinct_driver_phase_threads` | `confirmation.join(timeout=2.0)` |
| `test_tui_summon.py:674` | `test_owned_run_uses_and_releases_one_operation_interaction_scope` | `worker.result(timeout=2.0)` |
| `test_tui_summon.py:707` | `test_terminal_attach_confirmation_close_and_post_failure_fail_closed` | `worker.join(timeout=2.0)` |
| `test_tui_summon.py:767` | `test_host_shutdown_requests_the_run_stop_before_refusing` | `thread.join(timeout=5.0)` |
| `test_tui_summon.py:821` | `test_successful_confirmation_leaves_no_cancel_thread.answer` | `entered.wait(2)` |
| `test_tui_summon.py:869` | `test_foreground_return_releases_confirmed_prelease_reservation` | `worker.result(timeout=5.0)` |
| `test_tui_summon.py:1160` | `test_pending_worker_cancelled_before_start_never_runs_controller` | `shutdown.result(timeout=5)` |
| `test_tui_summon.py:1182` | `test_foreground_worker_retains_keyboard_interrupt_on_returned_future` | `worker.result(timeout=5)` |
| `test_tui_summon.py:1695` | `test_confirm_owner_contention_declines_instead_of_raising.first.cancel_soon` | `first_blocked.wait(5)` |
| `test_tui_summon.py:1714` | `test_confirm_owner_contention_declines_instead_of_raising` | `first_done.wait(5)` |
| `test_tui_summon.py:1715` | `test_confirm_owner_contention_declines_instead_of_raising` | `worker.join(timeout=5)` |
| `test_tui_summon.py:1910` | `run` | `self._stop_requested.wait(0.01)` |
| `test_tui_summon.py:2003` | `_wire_gate_member` | `thread.join(timeout=20.0)` |
| `test_tui_summon.py:2232` | `test_setup_recovery_offer_reaches_a_pending_owned_tui_and_completes.exercise` | `answerer.join(timeout=20.0)` |
| `test_tui_summon.py:2234` | `test_setup_recovery_offer_reaches_a_pending_owned_tui_and_completes.exercise` | `lease_thread.join(timeout=20.0)` |
| `test_tui_summon.py:2274` | `test_setup_recovery_decline_continues_detached_with_enriched_give_up.start_after_exit.operation` | `pump.join(15)` |
| `test_tui_summon.py:2368` | `test_host_shutdown_during_offer_spawns_nothing_further` | `future.exception(timeout=60.0)` |
| `test_tui_system.py:28` | `test_doctor_runs_on_background_owner_and_returns_typed_report` | `operations.submit_doctor().result(timeout=10)` |
| `test_tui_system.py:57` | `test_doctor_findings_and_framework_failures_cross_the_background_boundary` | `operations.submit_doctor().result(timeout=5)` |
| `test_tui_system.py:68` | `test_doctor_findings_and_framework_failures_cross_the_background_boundary` | `operations.submit_doctor().result(timeout=5)` |
| `test_tui_system.py:87` | `test_dump_is_single_flight_and_blocks_quit_until_future_finishes.held_dump` | `release.wait(5)` |
| `test_tui_system.py:97` | `test_dump_is_single_flight_and_blocks_quit_until_future_finishes` | `started.wait(5)` |
| `test_tui_system.py:102` | `test_dump_is_single_flight_and_blocks_quit_until_future_finishes` | `future.result(timeout=10)` |
| `test_tui_system.py:128` | `test_existing_dump_path_requires_visual_confirmation_but_domain_replaces` | `operations.submit_dump(output, replace_confirmed=True).result( timeout=10 )` |
| `test_tui_system.py:156` | `test_dump_domain_failure_crosses_the_background_boundary` | `operations.submit_dump(tmp_path / "backup.json").result(timeout=5)` |

The subprocess fixtures in `conftest.py` have independent infrastructure
containment: environment creation 120 s, wheel installation/build commands
180 s where specified, and installed Python invocation 60 s. Native terminal
tests retain `run_terminal_child` and `HostTerminal.read_until` ownership.
Those are not TUI behavior budgets and are not moved into a UI event loop.

## Review questions still open

- CORES is resolved by the existing initial-drain Event publication. Install
  it before watcher start through the real client factory wrapper; do not
  attach an uncoordinated observer after start. Firing conversion tests still
  must verify the actual core-count assertion after that completion.
- Approve explicit elapsed caps for formerly attempt-counted waits after
  native phase data. Preserve all currently explicit 2/5/10/30/45/90 s
  behavior bounds and separate setup/cleanup.
- All previously unclassified local sites now have concrete callback/fence
  mappings in Appendices A/B. Conversion firing tests must confirm those
  selected seams, including error/rejection outcomes. A broad message-driven
  predicate scanner is not an acceptable substitute.
- Native Windows cancellation/ConPTY evidence cannot be generated by these
  source reads. The workflow diagnostic and five-run qualification remain
  separate plan gates. This inventory neither diagnoses historical S4 nor
  waives its unresolved-cause gate.
