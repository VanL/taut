# Reported issues follow-up

Status: Active
Class: 5 — proposed terminal/TUI/Summon contract additions; async rename completion and cancellation cross ownership and lifecycle boundaries. Hardening applies.
Plan type: Implementation with spec revision, plus a bounded measurement slice.
Owner: Implementing engineer; independent reviewer owns the plan and slice review verdicts.
Requested outcome: Implement the reviewed plan. Commits, release, and publication remain separate steps.

## Goal

Repair TUI rename continuity and draft loss, preserve already-known command errors when project terminal policy fails, and distinguish reusable Summon write cancellation from adapter death. Measure deletion-heavy search maintenance before proposing optimization. Leave the schema fast path unchanged by explicit owner decision.

## Source Documents and Spec Baseline

Baseline: `a880011a8a6431f0d6173b1886e39998c33591b0`.
Promotion baseline: working tree from `a880011a8a6431f0d6173b1886e39998c33591b0`; the exact proposed text is promoted in `docs/specs/10-taut-tui.md`, `docs/specs/02-taut-core.md`, and `docs/specs/04-summon.md` before dependent implementation.

Consulted: `AGENTS.md`, `docs/program-theory.md`, canonical startup hub, decision hierarchy, principles, engineering principles, review runbook, lessons and agent inventory. Planning uses `docs/agent-context/runbooks/writing-plans.md`, `docs/agent-context/runbooks/hardening-plans.md`, and `skills/call-agent/SKILL.md`. Implementers also read testing-patterns and adversarial-acceptance-probes before writing tests.

Governing documents:

- `docs/specs/10-taut-tui.md` [TUI-6.3], [TUI-7.1]; `docs/implementation/12-taut-tui.md`: rename view ownership, drafts, and send revision fences.
- `docs/specs/02-taut-core.md` [TAUT-6.4], [TAUT-8.4], [TAUT-8.6]; `docs/implementation/04-taut-architecture.md`: safe diagnostics, watcher cursor and dispatch ownership.
- `docs/specs/04-summon.md` [SUM-5.4], [SUM-7.1], [SUM-10], [SUM-11]; `docs/implementation/05-taut-summon-architecture.md`: cancellation, generation and watcher supervision.
- `docs/specs/06-search.md`; `docs/implementation/09-search-architecture.md`; `docs/plans/2026-09-14-audit-remediation-plan.md` source-identity lookup slice: a stale hint requires current searchable-queue lookup; rename markers are not permanent redirects.
- `docs/plans/2026-09-15-windows-pty-lifecycle-fixes-plan.md`: completed Windows writer/interrupt ownership work; preserve its fixes.
- `docs/specs/01-development-documentation-operating-model.md` [DOM-5], [DOM-10], [DOM-11], [DOM-15].

## Findings and Dispositions

| ID | Evidence and scope | Disposition |
|----|--------------------|-------------|
| F1 | Raw `#general` survives command parsing; core normalizes, TUI callback does not. Real Textual probe left active view/draft on general after successful rename. | S1: canonicalize both input names once for TUI dispatch and completion. |
| F2 | Model overwrites a destination draft. Core rejects live destination channel, but an external rename can leave a stale draft under a now-free name. Full multiclient test still required. | S2: reproduce then retain conflicting drafts with explicit recovery. |
| F3 | Usage/load/parser diagnostic writers bypass execution fallback. Invalid regex probes lose diagnostics. Human missing-argument example stops earlier in parser construction. | S3: extend known-error rendering only; retain human preflight. |
| F4 | Interrupted injection raises AdapterError, sets harness-dead and enters respawn accounting. Handler probe confirmed classification, not full real-process race. Current contract is ambiguous about cancellation versus failure. | S4: explicit cancellation outcome, same-generation watcher restart, real platform proof. |
| F5 | A deleted message caused five exact peeks across five channels; persistent queues remained cached. No latency evidence yet. Existing plan explicitly accepts the scan for correctness. | S5: benchmark and report; no optimization authorized by this plan. |
| F6 | Core DDL unchanged across examined v0.5.x–v0.9.7 tags and baseline. Hypothetical same-version addition is skipped on existing DB; no demonstrated ordinary released upgrade break. | No change by owner decision. Reopen with an actual schema evolution. |

## Context and Key Files

| Slice | Files and existing ownership |
|-------|------------------------------|
| S1/S2 | `extensions/taut_tui/taut_tui/app.py`: `_submit_channel_rename`, `_apply_channel_rename_result`, composer capture and intent ownership. `models.py` in that package: immutable VisualState/DraftState and `remap_channel_target`; one active draft per public target today. `actions.py` and `screens.py`: palette registry/routing and modal UI. `taut/addressing.py`: reuse `validate_chat_thread_name(..., allow_subthread=False)`, as core rename does. |
| S3 | `taut/commands/_dispatch.py`: all dispatch error exits, parser construction/preflight and execution fallback. `taut/commands/_protocol.py`: CommandArgumentParser.error/exit. `taut/commands/_rendering.py`: project-policy writer and packaged-policy writer. |
| S4 | `extensions/taut_summon/taut_summon/_adapter.py`: AdapterError and AdapterExitedError. `_pty_posix.py` and `_pty_windows.py` in same package: epoch invalidation, serialized writes, reusable interrupt and permanent retirement. `_driver.py`: `_on_item`, `_halt_and_raise`, watcher-attempt supervision and readiness. `_control.py`: rate nudge and `_hard_breach`. `taut/watcher.py`: terminal exceptions preserve cursors; ordinary handler errors have a three-strike poison budget. |
| S5 | `taut/client/_searching.py`: per-job source lookup. `taut/client/__init__.py`: queue cache lifetime. `tests/test_search.py`, `tests/test_shared_contract.py`: search correctness fixtures. |

S1/S2 tests: `extensions/taut_tui/tests/test_tui_app.py`, `test_tui_chat.py`, `test_tui_screens.py`, `test_tui_actions.py`, `test_tui_action_routes.py` in that test directory. Add model tests there only if the existing files cannot hold the contract naturally.
S3 tests: `tests/test_command_registry.py`, `tests/test_terminal_text.py`.
S4 tests: `extensions/taut_summon/tests/test_driver.py`, `test_pty_adapter.py`, `test_pty_windows.py` in that directory; real child helper `extensions/taut_summon/taut_summon/scripted_provider.py` only if needed for deterministic terminal behavior.
All slices update the relevant implementation note and `CHANGELOG.md`; repository maps change only for genuinely new owned surfaces.

Before edits, implementer records answers in Execution Log. Wrong answers block edits pending reread:

1. Does successful rename authorize completion to change whatever view is now open? Expected: no; existing conversation-intent fence owns navigation, while current draft state must still be remapped without losing later edits.
2. May a cancelled handler return success or retry as a generic exception repeatedly? Expected: neither; success advances the cursor, repeated ordinary failure can poison-advance. Stop the attempt without advancing, then let its owner join and restart it against the same surviving generation.
3. Can completed rename records replace exact source lookup? Expected: no; old-name reuse replaces records. They are recovery bookkeeping, not a location index.

## Invariants, Hidden Couplings, and Rollback

- No core rename semantics, database schema/version markers, search job formats, new dependencies, or provider protocol changes. TUI validation calls core's existing canonical helper; it does not duplicate normalization.
- Rename failure changes no drafts. Successful rename transforms current state, not a dispatch-time snapshot. Newer navigation wins. Source and destination text, cursor and content remain recoverable; whitespace is content. Never silently concatenate, discard, or send recovered text.
- A recovered draft loaded into a target receives a fresh target revision so an older send acknowledgement cannot clear it. Recovery records are session-local, like ordinary drafts; no durability promise on app exit.
- Diagnostics use project policy normally and packaged policy only for a known failure's diagnostic. No raw dynamic fallback, no bypass of successful-output filtering, no command execution after failed human preflight. Preserve quiet, stdio, error exit and NDJSON ownership.
- Cancellation means a reusable write was superseded by a completed interrupt; it is not evidence of provider exit. Real exit/I/O failure still uses existing fatal recovery. STOP/close/control failure wins over cancellation, and lifecycle owners retain close/join responsibility.
- No same-generation retry before interrupt completion. Interrupted terminal input can be partial; retain at-least-once semantics, not an invented exactly-once claim. No new durable retry queue, no cursor writes in driver, no spin loop or hidden crash-budget consumption.
- Keep watcher attempt stop, checked join, wake and generation death distinct. Initial-drain cancellation must not convert into a false readiness failure or reset the original readiness deadline. Chat messages use durable cursor replay. Notification pointers are consumed by the existing inbox claim path and remain best-effort: cancellation may lose that pointer, with no new replay promise or re-enqueue mechanism. Both handler routes must stop terminally without poison accounting.
- Search measurement must not alter production cache or registry behavior. Full source hydration and name-reuse correctness remain authoritative.

Rollout: S1 and S3 are independently reversible; S2 model/UI changes land together; S4 exception, both adapters and driver land together within Summon. No storage migration or distributed rollout ordering. Roll back each code slice with its associated spec text/tests, preserving other slices and the completed Windows fixes. Do not selectively revert cancellation classification while retaining retry handling. Publication is outside this plan. A binary rollback does not persist or transfer unsent session drafts; normal app-exit limitations remain explicit.

## Proposed Spec Delta

Promotion strategy A for all rows: in-file normative text before code/link claims. Promote each slice's paragraph immediately before its implementation, after independent review. Update Related Plans backlinks and record the promotion identifier. No spec edits are part of the current plan-only request.

### [TUI-6.3] — append to rename continuity requirements (S1/S2)

> Rename continuity uses canonical channel names on both sides, including when command input includes a leading `#`. Completion preserves current drafts and respects a newer conversation intent. If remapping would replace another nonempty draft, the displaced draft is retained in session-local recovery state with its original target and cursor. The TUI exposes a Recover draft action while recovery records exist. Loading a recovery never sends text; it preserves an occupied destination draft in recovery and assigns a fresh destination revision. Dismissing recovery retains its records. Recovery does not add persistence beyond the TUI session.

### [TAUT-6.4] — append to fixed policy diagnostic rules (S3)

> When a core CLI diagnostic for an already-detected usage, command-load, parser, or execution failure cannot be rendered with the project terminal policy, render that diagnostic with the packaged policy, then the fixed policy-failure diagnostic, and exit 1. This does not bypass ordinary human-output preflight or successful-output policy checks. If preflight fails before an underlying command error is detected, only the policy diagnostic is required. A packaged-policy failure retains the fixed printable-ASCII bootstrap diagnostic; never emit unescaped dynamic text. Existing quiet and raw-stdio ownership remains unchanged.

### [SUM-7.1] — append to reusable interrupt requirements (S4)

> A write aborted by reusable interrupt is distinguishable from terminal retirement, provider exit, and transport failure. The cancellation outcome is not published to an injection caller until that interrupt has completed, so a same-generation retry cannot overtake its Ctrl-C delivery. Terminal retirement or provider exit observed concurrently takes precedence over reusable cancellation. An interrupted write may have delivered a partial event; successful retry remains at-least-once at the terminal boundary.

### [SUM-5.4] / [SUM-11] — qualify injection-failure recovery statements (S4)

> Reusable write cancellation is not harness death or watcher failure. The driver stops and joins the current watcher attempt without advancing a cancelled chat-message delivery's cursor, then rebuilds it over the same surviving handle. Notification pointers retain their existing consumable, best-effort semantics: a pointer already claimed when injection is cancelled may be lost, and this path adds no notification replay or re-enqueue mechanism. It consumes neither harness-crash nor watcher-failure budget. Initial-drain cancellation preserves the pending readiness barrier until a replacement attempt completes its initial drain, subject to the original readiness deadline. Cancellation restarts neither that deadline nor its timeout budget; expiry follows the existing startup failure/shutdown path. Shutdown, control failure, provider exit, and genuine adapter failure retain their existing terminal or fatal recovery paths. A cancellation must never be retried through the ordinary poison-message budget.

### [SUM-10] — append to normal hard-breach interrupt paragraph (S4)

> A hard-breach interrupt that cancels an in-flight injection does not itself retire a surviving generation. Delivery resumes through the cancellation path in [SUM-5.4]. An actual provider exit, including exit caused by failed interrupt delivery, remains eligible for normal generation recovery.

## Tasks and Per-Slice Acceptance

### 0. Plan review and spec promotion

- [x] Review this plan and exact deltas independently; resolve findings before implementation.
- [x] Record comprehension answers, baseline drift and per-slice spec promotion. Existing authority remains baseline until promotion.
- [x] Read testing-patterns/adversarial-acceptance-probes and map every enumerated requirement below to a firing test; do not replace native qualification with a status assertion.

### S1. Canonical rename continuity

- [ ] Red: extend `test_text_command_rename_preserves_draft` through real Textual/session/core flow for `#general -> #ops`; assert core result, active channel, reply target, navigation, exact draft/cursor and successful next send to ops. Include plain-name control and newer-navigation completion fence.
- [x] Validate both names in the shared `_submit_channel_rename` boundary, route validation failures through existing form/command error handling, and carry canonical old name into completion. Native form and text command use the same boundary.
- [x] Green: all TUI rename tests, invalid input/no mutation, renamed reply descendant, and delayed success/failure. Review coherent slice independently.
- Stop if this requires changing the core rename return type or duplicating addressing rules.

### S2. Preserve colliding drafts

- [ ] Red through two real clients: draft in ops, external rename ops away, source draft in general, TUI rename general to now-free ops. Demonstrate loss, then make both texts recoverable.
- [x] Add immutable RecoveredDraft records (proposed new type) to VisualState: stable recovery ID, original DraftState, intended target, reason. On collision, mapped source remains target draft; displaced nonempty destination becomes a recovery record. Existing recoveries survive later renames. Do not deduplicate equal texts or drop whitespace.
- [x] Completion captures the current composer before transforming current VisualState; intent guard still prevents navigation theft. Test edits during the future, root/reply collisions and failures.
- [x] Add Recover draft palette action, enabled only with records. Reuse existing modal styling for selection and full multiline read-only preview, not NativeFormScreen's single-line Input. Display original/intended targets. Load into composer is explicit; select/open the intended target through the normal intent path, never infer external rename destinations. If target no longer exists, report that and retain the record. Escape retains records. On successful open, capture current destination draft, retain it if nonempty, install selected recovery with a new target revision, then remove only that recovery. No implicit send or clipboard dependency.
- [ ] Acceptance: both texts/cursors, late edits, newer navigation, failed reopen, whitespace/multiline/equal text, occupied destination swap, Escape, multiple recoveries, and old send acknowledgement after recovery load. Test palette enable/dispatch and accessible keyboard/mouse controls.
- Done: user can access all displaced text without inventing a channel or losing a newer edit; independent review passes.
- Stop if persistence, general draft history, or arbitrary channel reassignment is needed; those need a separate design.

### S3. Diagnostic fallback coverage

- [ ] Red matrix through real dispatch with temporary invalid regex config: unknown command, manifest failure, implementation import failure, parser exit with error, unexpected parsing SystemExit, execution failure; human/JSON variants where reachable. Use `--json say` for missing TARGET. Human `say` must still stop at preflight with only its policy diagnostic.
- [x] Factor the existing execution fallback into one shared diagnostic writer in `_rendering.py`, used from `_dispatch.py` and `_protocol.py`; no dispatcher import cycle. Return/propagate policy-failed status so exit becomes 1, including an original exit 2. Route all known-error sites through it. Status-0 parser help and normal stdout are not diagnostic fallback paths.
- [x] Format the complete error/hint group before writing, so a later-line policy failure does not duplicate earlier error records. Parser `error()` may already have emitted its structural usage text through `print_usage`; that existing ordering is retained, and fallback must not re-emit usage. The shared writer owns error/hint records, not parser usage/help rendering. Preserve each error/hint as a separate escaped record. Reuse packaged writer and existing static bootstrap distinction for malformed project files.
- [ ] Test hostile escape/newline error strings, project-only failure, packaged-policy failure, quiet behavior, and unchanged valid-policy output/exit status. For import/parse errors assert execute was never called. Test unknown/preflight/load/parser cases with the applicable adversarial input floors from the runbook; no new parser grammar.
- Done: original known error plus one policy diagnostic, safely escaped and correctly routed; existing execution test remains green; independent review passes.

### S4. Reusable cancellation without respawn

- [ ] Red: use existing interrupted-write adapter tests and production driver path to show a rate interrupt during injection currently classifies as death. Build a causal real-child probe: entered write/backpressure, interrupt completion, same child alive, complete retried line observed, then clean STOP. Use events/pipe acknowledgements, not sleeps as proof.
- [x] Add a distinct AdapterWriteCancelled subtype in `_adapter.py` (proposed name). Audit every epoch/retirement raise on both platforms: reusable interrupt maps to cancellation; close, exit and real I/O failure keep terminal semantics. Cancellation publication must wait for interrupt completion without holding a lock needed by interrupt/close. Preserve Windows operation-token and POSIX lease ownership, overlapping interrupts and close precedence.
- [x] Add an explicit attempt-local cancellation signal/outcome in driver supervision. Catch cancellation before AdapterError, request watcher stop, raise a terminal watcher exception that bypasses poison accounting (reuse the current public WatcherRejected/StopWatching semantics after verifying error-handler routing), and wake supervisor. Never set harness-dead for this case. Existing attempt owner performs checked join before replacement. Add cancellation to wake/readiness decisions and restart it without incrementing either failure counter; check shutdown/control/exit first. `_run_watcher_attempt` must inspect the attempt-local cancellation outcome in both its exception handler and its finally branch before setting `_watcher_failed`. Keep one readiness deadline across cancellation restarts; do not create a fresh 30-second allowance per attempt. Genuine startup timeout follows the existing bounded failure path. Do not call adapter close from watcher or control threads.
- [ ] Audit all inject consumers, including orientation and rate soft nudge. Orientation interrupted by shutdown remains clean shutdown; unexpected pre-ready reusable cancellation must obey the readiness barrier. A cancelled soft nudge is best-effort, never harness death; rate audit and hard-breach state must still advance as intended. Do not broaden genuine error catches.
- [ ] Acceptance matrix: in-flight message and notification cancellation; repeated cancellations beyond both old budgets; unchanged chat cursor until successful message replay; notification claim retains its current consumable semantics with no re-enqueue, while its terminal exception stops without poison processing; no poison advance; unchanged generation/PID/spawn count, live pump/control and preserved rate counters; initial-drain cancellation with successful replacement before the original deadline and bounded timeout after repeated cancellation without deadline reset; concurrent STOP; provider exits on Ctrl-C; real transport error; overlapping interrupts; queued writers; close supersedes cancellation; no unbounded waiting. Replay must demonstrate complete terminal input after partial-prefix cancellation, not just a fake exception result.
- [ ] Run real POSIX and Windows ConPTY proofs in their native lanes. Portable fake native-API tests validate race precedence, but do not replace actual child/terminal proof. Native unavailable means qualification remains open, not a pass. A review before implementation and after this slice is mandatory.
- Stop if same-generation replay cannot be shown safe under the existing PTY framing contract, if new core watcher semantics are required, or if cancellation needs a new durable retry protocol. Replan rather than swallowing errors or claiming exactly-once delivery.

### S5. Search measurement, no production optimization

- [x] Use production clients/providers with fresh temporary workspaces; record baseline SHA, platform, versions, workload and exact reproducible method in this plan's Execution Log. No new benchmark framework or permanent observability subsystem.
- [ ] Measure 10/100/1000 searchable threads and 1/10/100 deletions, persistent and ephemeral clients. The 10/100 matrix completed; 1000 threads exceeded the bounded local run and remains unavailable.
- [x] Separate registry enumeration, exact peeks and connection setup cost where instrumentation permits without replacing their production implementations. Confirm linear work counts; do not assert a universal latency SLO or introduce timing-sensitive CI gates.
- [x] Report whether cost is material for the owner's actual workload, with measured evidence. If workload relevance is unknown, request it with the results. Any optimization is a separate proposed change with concurrency proof; snapshots must account for renames during drain and rename records may only be hints. A delete miss still requires source-absence resolution under the accepted contract.
- Done: reproducible measurements and an explicit retain/propose disposition, even if no optimization follows. This slice does not block independently verified fixes.

### S6. Reconcile and close

- [x] Update implementation notes, spec backlinks, changelog, plan index and any genuinely affected ownership map. Evaluate skill/runbook improvements; record a durable lesson only for a new reusable correction, not to repeat existing rules.
- [x] Review each coherent code slice and all final changes independently; disposition every finding. Run final gates from the candidate revision, record commands/results and residual native-platform qualification.
- [ ] Stage by explicit file list only if the owner requests commits. A slice is not called finished/ready to land without verifying its commit in git log; if review is requested without commits, report changed files and uncommitted state explicitly. No release or publication in this plan.

## Verification Commands

Planning gates (current task):

```sh
.venv/bin/python -m pytest tests/test_docs_references.py tests/test_plan_status_index.py -n 0 -q
.venv/bin/python bin/check-plan-status-index
git diff --check
```

Implementation focused commands, after adding the tests to named existing files:

```sh
.venv/bin/python -m pytest tests/test_command_registry.py tests/test_terminal_text.py -n 0 -q
uv run --no-sync --project extensions/taut_tui --extra dev --with-editable . --with-editable extensions/taut_tui pytest extensions/taut_tui/tests -n 0
.venv/bin/python -m pytest extensions/taut_summon/tests/test_pty_adapter.py extensions/taut_summon/tests/test_pty_windows.py -n 0 -q
.venv/bin/python -m pytest extensions/taut_summon/tests/test_driver.py -k 'interrupt or cancel or rate or watcher' -n 0 -q
```

Broader final verification uses the existing ROOT_TEST_COMMANDS, SUMMON_UNIT_TEST_COMMAND and SUMMON_PROCESS_TEST_COMMAND definitions in `bin/release.py` as separate invocations, plus TUI_TEST_COMMAND. Run the changed surface's Ruff and type-check paths from that file, including tests; no blanket release invocation or publishing to get test coverage. Use native Windows/POSIX CI jobs for platform-only proofs and record skips explicitly. Search uses existing search/shared conformance tests for its measurement harness; no production search code change. The plan's new contract enumeration is the test checklist, not a request for tests mirroring implementation.

Post-deploy signals, when separately released: # prefixed rename immediately targets the new channel; recovery action exposes displaced drafts; diagnostic reproduction shows known error then policy error; rate interruption keeps the same surviving generation and resumes complete input without crash-backoff logs. Existing genuine exit and STOP remain observable and bounded.

## Out of Scope and No-Action Register

DDL fast path/repair/migration changes are excluded by owner decision; reopen only with actual schema evolution. Search optimization is excluded pending measurement. No general draft persistence/history, automatic text merging, provider redesign, watcher framework rewrite, new dependency, schema or config key, release or deployment. Preserve the already-completed Windows lifecycle changes.

## Deviation Log

| Spec ref | Planned behavior | Actual behavior | Rationale | Spec proposal |
|----------|------------------|-----------------|-----------|---------------|
| [TUI-6.3] | Recovery selector may retain inline failure state. | Selector closes before async open; failures appear in the main inspector and the record remains recoverable. | Keeps async navigation and errors on the existing app-owned path without losing data. | None; observable retention contract is unchanged. |

No implementation deviations recorded. Proposed spec deltas above are explicit changes, not existing behavior claims.

## Review Log

Round 1: Claude 2.1.207, default reviewer `claude-opus-4-8[1m]`, read-only safe/plan mode, matched Read/Grep/Glob tools, strict MCP config, closed stdin, no session persistence and 540-second timeout. Completed with exit 0, success/end_turn and terminal_reason=completed. Verdict PASS, with four refinements accepted below. The combined liveness/write-containment probe also passed (120-second bound); no probe file appeared. Round 2 checks only these accepted findings and defects introduced by their corrections.

| Finding | Disposition | Correction |
|---------|-------------|------------|
| P2-1 | Accepted | Restrict cursor/replay guarantee to chat. Notifications remain consumable best-effort pointers; cancellation may lose an already claimed pointer. Test terminal routing without inventing notification replay. |
| P2-2 | Accepted | Preserve original readiness deadline across cancellation restarts; test both successful recovery and original-deadline expiry. |
| P3-1 | Accepted | Cancellation outcome must fence both `_run_watcher_attempt` exception and finally branches before watcher-failure publication. |
| P3-2 | Accepted | Shared diagnostic writer owns error/hints. Preserve already-emitted parser usage and never duplicate it during fallback. |

### Round 1 findings (verbatim)

## Findings

**P2-1 (S4, notification replay semantics).** The invariants treat message and notification injection cancellation uniformly ("unchanged cursor until successful replay"; [SUM-5.4] "without advancing the cancelled delivery's cursor"). But notifications are **not** PEEK/cursor-based — they route through the base fetch (`watcher.py:1428-1446`), and `_make_notification_handler` (`1379-1385`) has neither the terminal-exception wrapper nor `_advance` that `_make_taut_handler` has. So "unchanged cursor" is inapplicable to notifications, and a cancelled notification injection risks being consumed-and-lost. *Correction:* state the actual notification cancellation semantics (replay mechanism, or explicitly best-effort/lossy) and require the acceptance test to confirm StopWatching/WatcherRejected raised from the notification handler routes terminally without poison.

**P2-2 (S4, readiness deadline under repeated pre-ready cancellation).** The 30s readiness barrier (`_driver.py:1841`) conflicts with "initial-drain cancellation preserves the pending readiness barrier" + "no unbounded waiting" unless disambiguated. *Correction:* specify that the original readiness deadline **persists** across cancellation-triggered attempt restarts (a cancellation is neither a readiness failure nor a deadline reset), so both invariants hold.

**P3-1 (S4, cancellation signal must reach `_run_watcher_attempt`).** Its `except Exception` (`2212-2220`) and `finally` (`2234-2242`) set `_watcher_failed` for any non-stop/non-halt exit, which would increment `watcher_failures`. The new attempt-local cancellation signal must be consulted in **both** branches alongside `attempt_stop`/`_halt_ack`, not only in `_watch_until_wake`/`_await_wake`. Name this explicitly.

**P3-2 (S3, parser usage-line ordering).** `CommandArgumentParser.error()` writes `print_usage` unescaped before the escaped message (`_protocol.py:78-80`), so "format the complete group before writing" cannot fully cover the parser path. Confirm the shared writer owns only the error/hint record(s), and the already-written usage line is acceptable and not re-emitted by the packaged fallback.




### Round 2 verification

Claude returned PASS on all four accepted corrections, with no new defect or blocking finding. Same restricted invocation as round 1, 360-second bound; exit 0, success/end_turn, terminal_reason=completed. This is review of the plan only, not implementation acceptance.

I'm unable to write the plan file (Write tool is not enabled in this review context), so I'll deliver the verdict directly.

## Round-2 Verification — Verdict: **PASS**

Baseline `a880011`. Scope limited to accepted findings P2-1, P2-2, P3-1, P3-2 and any new defects their corrections introduce. Each correction verified against baseline code; unchanged design not re-audited.

**P2-1 (notification best-effort; chat-only cursor/replay) — PASS.** `taut/watcher.py`: `_make_notification_handler` (1379–1385) calls the user handler with no try/except, no poison accounting, no `_advance`; only `_make_taut_handler` (1387–1416) has the StopWatching/WatcherRejected terminal re-raise and durable-cursor `_advance`. Notifications defer to the base fetch (`_fetch_next_message` 1428–1433), so cursor/replay never applied to them. The revised invariant and [SUM-5.4]/[SUM-11] delta now scope replay to chat and mark notification pointers consumable/best-effort/lossy-on-cancel with no re-enqueue — matches code.

**P2-2 (original readiness deadline) — PASS.** `_driver.py:1841` creates `deadline = now + 30.0` inside the supervisor `while` (1824), so today each rebuilt attempt gets a fresh 30s — exactly the ambiguity flagged. The correction ("keep one readiness deadline across cancellation restarts… restarts neither that deadline nor its timeout budget") targets this correctly and reconciles "preserve pending barrier" with "no unbounded waiting." Both success-before-deadline and original-deadline-expiry tests are required.

**P3-1 (fence both `_run_watcher_attempt` branches) — PASS.** The `except` branch sets `_watcher_failed` at 2219 and the `finally` branch at 2240, each guarded only by `_watcher_stop_requested`/`_halt_ack` (2213–2216, 2234–2237). The correction requires the attempt-local cancellation outcome to be consulted in *both* before watcher-failure publication — precisely these two sites; no harness-dead set.

**P3-2 (parser usage not re-emitted) — PASS.** `_protocol.py:78–80`: `error()` emits static `print_usage(stderr)` before `exit()` renders the message via `write_human_line` (82–90). The correction scopes the shared `_rendering.py` writer to error/hint records only, retains the already-emitted usage line, forbids fallback re-emission. `_protocol` already imports `write_human_line` lazily from `_rendering`, so no `_dispatch` import cycle; usage is static so the "no unescaped dynamic text" invariant is untouched.

**New-defect check (corrections only).** No code changed (plan-only). No internal contradictions found: "both handler routes stop terminally without poison" holds (taut re-raises terminally; notification route has no poison budget to consume); P3-1's distinct cancellation outcome strengthens rather than conflicts with the existing `attempt_stop` fence; P2-2 reconciles bounded-wait with original deadline via the existing startup-failure path. All Round-1 line citations match baseline. Accepted risks respected; no correction worsens a pre-existing issue.

No blocking findings. The four accepted corrections are faithfully reflected in the revised plan and consistent with the code.

Since this was a review task (verdict delivered above) rather than an implementation to plan, there is no implementation plan to approve.

## Execution Log

Plan authoring: inspection and probes from the preceding read-only evaluation support F1–F6, with proof limits retained above. No implementation is claimed. Planning verification and review results will be appended below.

Planning verification: 35 documentation/reference and plan-index tests passed; standalone plan-index gate passed; all 31 explicitly quoted full paths existed; `git diff --check` passed. No production code or governing spec changed during plan authoring.

Maintenance check (read-only): coalesce-check reports 90 dated lessons, 42 after the watermark, and all cues resolve; 25 are age candidates before active-plan exclusions. The plan index has 98 completed/superseded non-exemplars. Checked-deferred: harvesting is a separate maintenance unit and is not folded into this requested plan. Skill evaluation: call-agent's current restrictive Claude invocation worked; no skill change justified.

Final planning gate: documentation/reference and plan-index tests rerun after review incorporation (35 passed), standalone index check and diff whitespace check passed. Independent review is complete; implementation checkboxes remain open.

Implementation comprehension: rename completion may remap only the view owned by
its original intent while transforming current draft state; reusable write
cancellation stops and joins one watcher attempt without cursor advance or
failure accounting; rename records remain lookup hints rather than a source
index. Specs 02, 04, and 10 were promoted before their dependent code changes.

S5 measurement used baseline `a880011a8a6431f0d6173b1886e39998c33591b0`
on macOS 26.6.2 arm64, Python 3.14.4, SimpleBroker 8.2.2, and SQLite. Fresh
production `TautClient`/`SQLiteSearchProvider` workspaces were seeded and
indexed before timed database clones. Instrumentation wrapped, then delegated
to, production `SqlSidecarTautState.list_threads` and `Queue.peek_one`; five
runs were made per completed cell. Each delete and drain phase made `D`
listings and `D × N` exact peeks. No-delete controls made zero calls. At 100
threads/100 deletions, ephemeral median drain was 10.271 s (runs 10.465,
10.271, 9.972, 10.126, 10.488) and median delete was 10.021 s (9.939, 10.051,
10.068, 10.021, 9.942). Persistent median drain was 0.413 s (0.410, 0.405,
0.437, 0.413, 0.472) and median delete was 0.281 s (0.287, 0.287, 0.275,
0.281, 0.278). Persistent caches grew from 1 to `N + 2`, then returned to zero
after close; a supported live-connection census is unavailable. Name reuse
passed: the stale `general` job found its original message under `ops`, did not
attribute it to reused `general`, and indexed new `general` content correctly.
The 1000-thread matrix exceeded ten minutes and buffered no recoverable partial
results. Disposition: retain the correctness scan; deletion-heavy ephemeral
cost is material at 100 × 100, but workload relevance is unknown and any
optimization needs a separate concurrency proof.

Independent implementation review found and resolved three races: draft
revision reuse could let an old destination send acknowledgement clear moved
text; repeated pre-ready cancellations could evade the original readiness
deadline; and Windows could report cancellation after its monitor had already
recorded provider exit. Fresh revisions now exceed current, recovered, and
pending revisions; the cancellation branch enforces the retained deadline;
Windows rechecks monitor state at the handle boundary. The review found no
diagnostic fallback defect. Native Windows ConPTY qualification remains open.

Final local verification: root broad suite 2171 passed/4 platform skips;
installed-wheel partition 28 passed; Summon unit lane 308 passed; Summon process
lane 303 passed/9 platform skips; focused driver/adapter suites and the full TUI
suite passed. Root and Summon mypy checked 141 and 46 source files; TUI mypy
checked 36. Repository and TUI Ruff checks, suppression registry, 45
documentation/architecture/policy tests, plan-index gate, and `git diff --check`
passed. Full-repository Ruff formatting still reports one pre-existing
unmodified historical plan (`2026-09-15-mcp-result-simplification-plan.md`);
all changed Python paths pass formatting. No commit, release, or publication was
requested or performed. The plan remains Active because the 1000-thread search
cell and native Windows ConPTY qualification are explicitly open.
