# 0.9.0 Review Findings Remediation Plan

Status: completed. Implementation, local verification, independent completed-
work review, and the owner-authorized landing are recorded below.

Class: 5+P. The work changes two product contracts, repairs several async and
cleanup lifecycles, and widens the standing release helper's PostgreSQL proof.

Plan type: implementation with spec revision.

## Goal

Resolve every actionable issue verified from
`2026-08-14-review-bug-report.md`, without carrying forward its two stale
conclusions or turning defensive hardening into an overstated vulnerability
claim. The implementation should restore the existing core, MCP, TUI, Summon,
search, persistence, and release contracts; add exact firing tests for each
enumerated finding; and leave one auditable release gate for the coordinated
0.9.0 candidate.

The endpoint is a verified implementation ready for an owner-authorized
landing. Publishing or tagging 0.9.0 is outside this plan.

## Finding Register and Decisions

| Finding | Disposition | Required outcome |
|---------|-------------|------------------|
| C1, C2 | fix | Rejoining cannot skip unread messages; a configured SQLite directory receives Taut's initialization hint. |
| C3 | defensive hardening | Score a synthetic stored session id of zero. Do not describe zero as reachable on normal supported process capture without new evidence. |
| M1-M4 | fix | Stop degraded reactor spin, close the shutdown admission race, retrieve abandoned attach failures, and align every exact teaching row with [MCP-5]. |
| T1-T3, T5, T7-T11 | fix | Repair the verified form, empty-result, help, inspector, watcher, intent-state, teardown, pointer, and executor defects. |
| T4 | docs-only correction | Align three stale prose surfaces with the already-correct Textual floor. Do not revise the canonical contract. |
| T6 | owner decision plus fix | Proposed decision: preserve the open reply surface when its registered thread survives deletion. Promote the exact [TUI-6.3] delta before code. |
| TUI untracked | no action | Refuted at baseline: the TUI is committed in `74e1455`. |
| S1-S4, S6 | fix | Restore terminal-operation cancellation, teardown primacy, one-budget settle, Claude no-wait startup, and final confirmation polling. |
| S5 | owner decision plus hardening | Strip C1 controls and narrow the proof to the supported Unicode-to-UTF-8 path. Do not label exploitability verified. |
| P1 | fix | Give actor-free doctor/dump/load the same missing-PostgreSQL install hint as normal client construction. |
| P2 | proof completion | Add the missing public-client SQLite/PostgreSQL parity and pinned adversarial PostgreSQL matrix. Retain the real PG tests that already exist. |
| P3 | narrower process fix | Keep standing MCP PG CI; add MCP PG conformance to the local release helper's PG gate. |
| bare `taut list` | test only | Pin the already-correct exit 2, empty stdout, and `no unread threads` stderr contract. No registry or behavior change. |

Any new evidence that changes a disposition must be recorded in the Deviation
Log before implementation continues.

## Source Documents

Product and process sources:

- `docs/program-theory.md`
- `docs/agent-context/decision-hierarchy.md`
- `docs/agent-context/principles.md`
- `docs/agent-context/engineering-principles.md`
- `docs/agent-context/runbooks/writing-plans.md`
- `docs/agent-context/runbooks/hardening-plans.md`
- `docs/agent-context/runbooks/testing-patterns.md`
- `docs/agent-context/runbooks/adversarial-acceptance-probes.md`
- `docs/agent-context/runbooks/review-loops-and-agent-bootstrap.md`
- `docs/agent-context/lessons.md`
- `docs/lessons.md` (Golden Rules and entries after the watermark)
- `docs/specs/02-taut-core.md` [TAUT-3.2], [TAUT-7.2], [TAUT-7.4], [TAUT-8.1],
  [TAUT-8.5], [TAUT-12.5]
- `docs/specs/04-summon.md` [SUM-7.1], [SUM-7.4], [SUM-11]
- `docs/specs/05-taut-mcp.md` [MCP-5], [MCP-10], [MCP-12]
- `docs/specs/06-search.md` [SRCH-12.2]
- `docs/specs/08-persistence-io.md` [PIO-9]
- `docs/specs/09-system-doctor.md` [DOCT-5]
- `docs/specs/10-taut-tui.md` [TUI-3.2], [TUI-6.2]-[TUI-6.4],
  [TUI-8], [TUI-9.2], [TUI-10], [TUI-11], [TUI-13.3]
- `docs/implementation/04-taut-architecture.md`
- `docs/implementation/05-taut-summon.md`
- `docs/implementation/09-taut-mcp.md`
- `docs/implementation/11-search.md`
- `docs/implementation/12-taut-tui.md`
- `2026-08-14-review-bug-report.md` (claim source, not governing contract)

Review inputs also include the code and test owners named below, the history at
`74e1455`, and the independent verification evidence recorded in this plan.

## Spec Baseline

- `74e145537c961a24d54dcae5710f530c2728ed6e` is the implementation and
  active-spec baseline for this plan.
- Promotion baseline: `74e145537c961a24d54dcae5710f530c2728ed6e` plus the
  worktree diff for `docs/specs/02-taut-core.md`,
  `docs/specs/04-summon.md`, and `docs/specs/10-taut-tui.md`;
  documentation gates recorded below.

## Proposed Spec Delta

Promotion strategy: A. Apply both small reviewed deltas to the active spec
files and add reciprocal `## Related Plans` links in the same spec-promotion
slice. The code and tests that depend on them must not land first.

| Spec file | Strategy | Sections touched |
|-----------|----------|------------------|
| `docs/specs/02-taut-core.md` | A | [TAUT-12.5], `## Related Plans` |
| `docs/specs/10-taut-tui.md` | A | [TUI-6.3], `## Related Plans` |
| `docs/specs/04-summon.md` | A | [SUM-7.4], `## Related Plans` |

### [TAUT-12.5] MCP PostgreSQL release precheck

Implementation-discovered correction: in [TAUT-12.5]'s universal precheck
sequence, replace the text from `` `bin/pytest-pg --fast` `` through “live-
backend proof” with:

> `bin/pytest-pg --fast`, a second PostgreSQL-harness invocation selecting
> `extensions/taut_mcp/tests/test_pg_conformance.py`, the four isolated Summon
> lanes, one explicit MCP `not pg_only` lane under the MCP project, the complete
> package-local TUI lane against its retained lock, existing root/PG/Summon Ruff
> paths, package-local MCP and TUI Ruff lint/format, and five collision-safe
> mypy owners including explicit MCP and TUI project-local commands with their
> package configs. The local non-PostgreSQL MCP lane never treats excluded
> PostgreSQL cases as evidence; the selected MCP PostgreSQL invocation and the
> required canonical MCP workflow both supply live-backend proof.

### [TUI-6.3] deletion refresh

Insert after the paragraph ending “authorization rule”:

> After successful message deletion, refresh preserves the currently open
> reply surface when its registered sub-thread still exists. Physical message
> deletion does not itself cascade into sub-thread deletion or close an
> otherwise valid reply surface.

### [SUM-7.4] injected-text sanitizer

Replace the sanitizer paragraph beginning “In detached driver mode” with:

> **Ears and orientation.** In detached driver mode, `inject(text)` writes to
> the master under an inject lock. Payloads are canonicalized and sanitized
> before submission: CRLF/lone CR become LF; `ESC`, `DEL`, all C0 controls
> except LF, and all C1 controls (`U+0080` through `U+009F`) are stripped;
> `TAB` becomes a space. If the harness has enabled bracketed paste
> (`ESC[?2004h` observed in output), the sanitized text is framed as
> `ESC[200~...ESC[201~` plus `\r`, preserving LF. Otherwise remaining LFs
> collapse to spaces and exactly one turn is submitted with trailing `\r`.
> Embedded 7-bit or Unicode C1 paste delimiters cannot survive this
> Unicode-to-terminal encoding path because `ESC` and C1 controls are removed.

### Related-plan backlink

Add to each touched spec:

> - `docs/plans/2026-08-14-review-findings-remediation-plan.md` — review-driven
>   lifecycle, contract-proof, diagnostic, and release-gate remediation for
>   the coordinated 0.9.0 candidate.

## Context and Key Files

| Area | Current owner and defect | Files to change or verify first |
|------|--------------------------|---------------------------------|
| Core membership/config/identity | `TautClient.join()` supplies a fresh timestamp even when SQL preserves the existing membership row; explicit SQLite paths use `exists()`; identity scoring drops stored zero. | `taut/client/_threads.py`, `taut/client/_messaging.py`, `taut/client/_base.py`, `taut/state/_sql.py`, `taut/identity.py`, `tests/test_client.py`, `tests/test_project_config.py`, `tests/test_identity.py` |
| MCP workspace/process reactors | Degraded mode re-enters an overdue deadline; `detach_workspace()` can admit after close begins; a canceled shield waiter can leave a failed future unretrieved. | `extensions/taut_mcp/taut_mcp/_workspace_reactor.py`, `extensions/taut_mcp/taut_mcp/_process_reactor.py`, `extensions/taut_mcp/tests/test_resource.py`, `extensions/taut_mcp/tests/test_process_reactor.py` |
| MCP teaching contract | `_tools.py` owns exact descriptions, but both tool-specific and generic fragments have drifted from [MCP-5]; the manifest hash only compares code with itself. | `extensions/taut_mcp/taut_mcp/_tools.py`, `docs/specs/05-taut-mcp.md`, `extensions/taut_mcp/tests/test_tools.py` |
| TUI domain/forms/rendering | The form adapter normalizes blank name incorrectly; empty unread is rendered as an error; help omits notification consumption; notification refresh overwrites unrelated inspector state; deletion refresh drops reply state. | `extensions/taut_tui/taut_tui/app.py`, `domain.py`, `screens.py`, `session.py`, `widgets.py`, `summon.py`; corresponding `test_tui_forms.py`, `test_tui_domain.py`, `test_tui_screens.py`, `test_tui_app.py`, `test_tui_chat.py`, `test_tui_summon.py` |
| TUI lifecycle and intent state | Watcher failures can become invisible; superseded search leaves `searching`; unmount can skip client close; pointer-down state survives drag-out; foreground Summon work can starve control work. | The same TUI owners plus `test_tui_actions.py`, `test_tui_system.py`, and `test_tui_textual_contract.py` |
| Summon stream/driver/PTY | Stream injection uses blocking `TextIO`; control failure may escape before teardown; PTY settle spends two budgets and ignores retirement; Claude incorrectly claims session events; the sanitizer retains C1; final confirmation omits a last read. | `extensions/taut_summon/taut_summon/_stream.py`, `_driver.py`, `_pty.py`, `_claude.py`, `controller.py`; `test_conformance.py`, `test_driver.py`, `test_pty_adapter.py`, `test_claude_adapter.py`, `test_controller.py` |
| Persistence/search/release | Actor-free PostgreSQL errors bypass the install hint; [SRCH-12.2]'s cross-backend public proof is incomplete; the release helper's PG command omits MCP PG conformance. | `taut/_maintenance.py`, `taut/persistence/_operations.py`, `taut/client/_base.py`, `tests/test_system_doctor.py`, `tests/test_persistence_io.py`, `tests/test_shared_contract.py`, `extensions/taut_pg/tests/test_pg_search_provider.py`, `extensions/taut_mcp/tests/test_pg_conformance.py`, `bin/release.py`, `tests/test_release_script.py` |
| Documentation | Three TUI prose surfaces still claim Textual 3.0 while the manifest and active spec require 8.2.8. | `README.md`, `extensions/taut_tui/README.md`, `docs/implementation/12-taut-tui.md`, `tests/test_project_metadata_consistency.py` |

Before editing, the implementer records answers to these gates in the
Implementation Log:

1. Why must C1 read membership before writing it? Expected answer: SQL conflict
   preserves the old cursor, so a new timestamp used as `prior_cursor` can skip
   already-unread messages; existing reply and DM-send paths demonstrate the
   stored-cursor pattern.
2. Which Summon terminal actions are terminal? Expected answer: `close()` and
   `request_close()` retire the generation; reusable `interrupt()` must unblock
   in-flight inject without making the handle permanently unusable.
3. Which MCP failure remains primary when teardown also fails? Expected answer:
   the fatal control `DriverError`; teardown is mandatory and cleanup failures
   become notes on that primary error.
4. What must remain real in search proof? Expected answer: public `TautClient`
   calls and real SQLite/PostgreSQL backends. Provider-only or MCP-to-itself
   mirrors cannot prove cross-backend parity.
5. What does T6 preserve? Expected answer: only an already-open registered reply
   surface that survives deletion, not deleted message selection, authorization,
   cursor movement, or a new cascade policy.

An incorrect or missing answer blocks implementation until the cited owner is
reread.

## Invariants and Constraints

- Rejoin never advances an existing member's stored cursor or skips older
  unread messages. The existing duplicate-join notice policy is not changed in
  this plan.
- Public CLI exit codes, stdout/stderr separation, and install hints remain
  stable except where this plan restores the documented shape.
- MCP degraded mode performs no database work and no hot loop. Close admits no
  new process-reactor work after `_closing` publishes.
- Async cleanup always runs. A primary operation/control failure remains
  primary; cleanup diagnostics are attached without replacing it.
- TUI owner-thread rules remain intact. Watcher callbacks do not mutate Textual
  state directly, and a failed watcher cannot be silently replaced while an
  old generation remains live or degraded.
- Notification refresh may update notification-owned state, but it may not
  replace a message, help, members, search, or Summon inspector selection.
- Search/result callbacks commit state only for the current intent generation.
- Summon control operations remain responsive even when every foreground run is
  blocked. Separate capacity, not a larger shared pool, owns that guarantee.
- Stream `interrupt()` remains reusable and nonterminal. `request_close()` and
  `close()` are terminal and must bound an in-flight write even when the child
  ignores SIGINT and never drains stdin.
- PTY settle has one total deadline across reader startup and quiet polling and
  observes synchronized retirement. Attached byte forwarding remains
  byte-transparent; only detached injected text is sanitized.
- No test may mock away the seam it claims to prove: real SQLite for C1/C2/T2,
  a real blocked subprocess for S1, real Textual pilot events for T10, real
  public clients and both databases for P2, and the real release command
  assembly for P3.
- No new runtime dependency, persistence field, thread pool shared by control
  and foreground work, second watcher implementation, or alternative search
  engine is authorized.
- There are no one-way data migrations. Every code slice is independently
  revertible with its tests; the two spec-backed behaviors must revert with
  their spec text and backlink.

## Rollout and Rollback

Apply the reviewed spec delta first. Then land coherent, independently tested
slices in this order: core, MCP, TUI, Summon, persistence/search/release,
traceability. Do not mix release tagging or version changes into the series.

Rollback is file-local by slice. Revert tests and implementation together. For
T6 or S5, revert the active spec paragraph and Related Plans backlink in the
same rollback as behavior. If the S1 implementation cannot provide bounded
cross-platform cancellation without changing the public handle contract, stop
and return to design review; do not ship an unconditional kill in
`interrupt()` or a capability-blind Windows claim.

Post-landing success signals are absence of the reproduced hot-loop and
unretrieved-future diagnostics, bounded STOP/status latency under saturation,
and a green full release precheck including MCP PG conformance. No new telemetry
surface is required.

## Dependency-Ordered Implementation Slices

Every behavior slice starts red, makes the smallest owner-local fix, runs its
focused gate, updates the Implementation Log, and receives an independent
review before another subsystem depends on it. Stop if a fix changes an
unlisted public contract, adds a dependency, creates a second lifecycle owner,
or cannot make its named proof fail before the implementation edit.

### Slice 1: review and spec promotion

1. Independently review this plan, exact deltas, all named paths, and the
   release-gate claim. Record every finding and disposition below.
2. Obtain owner acceptance of the T6 and S5 decisions. If either is declined,
   revise the finding disposition and plan before code.
3. Apply the exact [TUI-6.3] and [SUM-7.4] text and Related Plans backlinks.
4. Run documentation, path, plan-index, and whitespace gates. Record the
   promotion baseline identifier.

### Slice 2: core cursor and validation correctness (C1-C3, bare list)

1. Add a real-SQLite C1 regression: join, receive unread content, rejoin, then
   read the same unread content. Cover the stored cursor rather than merely the
   membership row. Read `state.get_membership()` before
   `state.add_membership()` and pass the existing membership's
   stored `last_seen_ts` as the pre-write cursor, following the existing reply
   and DM-send patterns around `state.get_membership()` and
   `state.add_membership()`.
2. Add public-construction tests for both `db_path` and `TAUT_DB` pointing at a
   directory. Replace the explicit-path `exists()` check with `is_file()` and
   assert Taut's initialization hint with no dependency traceback.
3. Add a synthetic identity-score test with session id zero; replace the
   truthiness gate with an explicit `is not None` check.
4. Add the exact bare `taut list` all-read CLI regression: exit 2, empty stdout,
   stderr `no unread threads`. Do not change dispatch or the spec.

Gate: focused core tests plus the existing unread, join, identity, project
config, and CLI suites. Stop if C1 requires changing SQL conflict semantics or
duplicate notice policy.

### Slice 3: MCP lifecycle and teaching contract (M1-M4)

1. Add a deterministic degraded-reactor test proving no iteration/CPU spin
   after deadline and prompt wake on stop/detach. In degraded mode, wait on the
   existing wake primitive before rechecking state; perform no DB work.
2. Add a deterministic close/detach interleaving. Gate
   `detach_workspace()` at method entry on `_closing`; do not add a second
   cancellation registry.
3. Add a cancellation-then-validation-failure test with a loop exception
   handler. Centralize retrieval/ownership of a failed attach future so no
   “Future exception was never retrieved” diagnostic occurs and fixed payload
   content remains opaque.
4. Enumerate every exact [MCP-5] teaching row, including generic selector
   fragments. Align `_tools.py` literals with the spec, then add direct
   spec-owned literal assertions. Refresh the manifest hash only after semantic
   assertions pass.

Gate: `test_resource.py`, `test_process_reactor.py`, `test_tools.py`, and MCP
stdio tests. Stop if the fix introduces polling, DB access in degraded mode,
new admission after `_closing`, or imports the spec file at runtime.

### Slice 4: TUI public behavior and state ownership (T1-T11)

1. T1: drive the real summon form-to-client path with token-only input and
   normalize blank name/alias to `None` before construction.
2. T2: catch only `EmptyResultError` at the domain empty-unread boundary and
   return an empty collection. Prove real SQLite empty state renders normally;
   other failures must still surface.
3. T3/T4: add the notification-pointer consumption warning to help and pin it;
   update the three stale Textual-floor prose surfaces to 8.2.8. Add one
   relational metadata-consistency assertion rather than duplicating a new
   independent version owner.
4. T5: preserve the active non-notification inspector across notification
   refresh. Add cases for message, help, and Summon status inspectors; update
   only notification model/feed state unless the notification inbox owns the
   surface.
5. T6: after the spec promotion, preserve `open_reply_thread` through deletion
   refresh when the registered thread survives. Prove deleted selection clears
   while the reply surface and cursor semantics remain stable.
6. T7: make watcher exit/failure an owner-thread event with a visible degraded
   state. Clear lifecycle ownership only through the session owner; do not
   acknowledge rejected messages or start a replacement watcher until the
   prior one has stopped within budget.
7. T8: make operation state intent-scoped, or clear superseded search state
   when the conversation intent generation advances. Prove a stale completion
   cannot leave `searching` visible or overwrite the newer view.
8. T9: structure session close so client close is attempted even if watcher
   stop fails, preserving the watcher error as primary. Contain and visibly
   report unmount cleanup failure without a Textual traceback.
9. T10: clear pointer activation on mouse-up/capture loss and prove a real
   press-drag-release outside does not fire the action. Preserve keyboard
   activation.
10. T11: give foreground Summon runs and control/status/stop separate bounded
    executors. Saturate all foreground workers with eight blocked runs and
    prove status and stop complete within their control budget.

Gate: the full TUI extension suite, including real Textual pilot tests. Stop if
the design mutates UI state from watcher threads, automatically advances a
cursor on failure, or merely increases a shared executor's worker count.

### Slice 5: Summon cancellation and supervision (S1-S6)

1. S1: add a real subprocess that ignores SIGINT and does not drain stdin;
   fill the pipe, block an inject, then prove `request_close()` retires and
   releases it within the shutdown budget. Replace blocking buffered writes
   with a cancellation-aware raw-pipe write loop using a generation/retirement
   epoch. Use short nonblocking writes and periodic epoch checks; keep one
   serialized writer. Add a separate cooperative-child proof that
   `interrupt()` releases the current inject while the handle remains reusable.
   Capability-check platform pipe support and retain the standing Windows
   capability skip where the runtime cannot provide honest nonblocking pipes.
2. S2: force fatal control failure to race an adapter failure. Always tear down
   the generation; re-raise the control `DriverError` as primary and attach any
   cleanup failures as notes.
3. S3: use one deadline across reader-start and quiet polling. Observe terminal
   retirement/master closure through a synchronized event or condition, and
   prove STOP interrupts settle promptly without spending a second budget.
4. S4: set the Claude stream adapter's session-event declaration false. Add an
   adapter-specific call-path/timing test proving the driver does not pay the
   five-second session wait.
5. S5: after spec promotion, strip `U+0080..U+009F` in detached injected text
   and add exact `U+009B` coverage. Do not alter attached raw PTY forwarding.
6. S6: bound each confirmation sleep by remaining time and perform one final
   evidence read after the last sleep. Use a controlled clock to place release
   in the final slice.

Gate: focused adapter/controller tests, all Summon conformance tests, and the
real-process lane. Stop if S1 kills the child for reusable `interrupt()`, relies
on unsynchronized retirement reads, or claims unsupported Windows behavior.

### Slice 6: diagnostics, search proof, and release gate (P1-P3)

1. P1: move missing-PostgreSQL backend error normalization into a low-level,
   actor-free helper. Reuse it from client construction, maintenance, and
   persistence loading; do not import a private client helper into maintenance.
   Test doctor, dump, and load with the PG extension unavailable.
2. P2: add a backend-parametric public-client matrix in
   `tests/test_shared_contract.py` for portable ASCII terms, punctuation/space
   tokenization, newest-first order, and state neutrality. Add PG public-client
   cases for Unicode/diacritic behavior and the lexeme-limit boundary alongside
   the existing PG search tests. Pin expected results; do not compare two calls
   to the same backend as parity.
3. P3: preserve `.github/workflows/test-mcp-extension.yml`. Add a distinct MCP
   PG conformance command to `bin/release.py` after the normal PG command and
   assert its exact selection and order in `tests/test_release_script.py`.
   Reuse the standing PG DSN and fail closed when it is absent.

Gate: actor-free doctor/persistence tests; real SQLite plus real PostgreSQL
shared-search tests; `extensions/taut_mcp/tests/test_pg_conformance.py`; release
command assembly tests. Stop if the proof becomes provider-only, silently
skips PostgreSQL, or duplicates the full MCP suite unnecessarily.

### Slice 7: traceability, integration, and closeout

1. Update the four relevant implementation notes with rationale and proof
   boundaries, not a narration of code. Record the narrower P3 conclusion and
   S5 threat classification.
2. Reconcile all spec/plan/implementation backlinks and the finding register.
   Every actionable ID must map to at least one firing test; refuted IDs must
   remain no-action entries.
3. Run focused gates, each extension suite, real PostgreSQL lanes, static
   checks, documentation checks, and the unchanged release helper precheck with
   its new MCP PG step.
4. Run independent completed-work review. Reproduce and disposition every
   finding; rerun affected gates after accepted changes.
5. Record stable evidence and landed commit identifiers only after the owner
   authorizes landing. Do not publish or tag.

## Verification Commands

Focused commands may be narrowed during red-green work, but the completion
floor is:

```bash
uv run --extra dev pytest -q \
  tests/test_client.py tests/test_project_config.py tests/test_identity.py \
  tests/test_cli.py tests/test_system_doctor.py tests/test_persistence_io.py \
  tests/test_shared_contract.py tests/test_release_script.py
uv run --extra dev pytest -q extensions/taut_mcp/tests
uv run --extra dev pytest -q extensions/taut_tui/tests
uv run --extra dev pytest -q extensions/taut_summon/tests
uv run ./bin/pytest-pg --fast
test -n "${SIMPLEBROKER_PG_TEST_DSN:-}"
uv run --extra dev pytest -q extensions/taut_mcp/tests/test_pg_conformance.py
uv run ruff check taut tests extensions bin/release.py
uv run --extra dev mypy taut tests bin/release.py bin/release-artifact.py \
  bin/require-green-workflows.py --config-file pyproject.toml
uv run --extra dev mypy taut/_scripts.py extensions/taut_pg/taut_pg \
  extensions/taut_pg/tests extensions/taut_pg/tests/conftest.py \
  --config-file pyproject.toml
uv run --extra dev mypy extensions/taut_summon/taut_summon \
  extensions/taut_summon/tests extensions/taut_summon/tests/conftest.py \
  --config-file pyproject.toml
uv run --project extensions/taut_mcp --extra dev mypy \
  extensions/taut_mcp/taut_mcp extensions/taut_mcp/tests \
  --config-file extensions/taut_mcp/pyproject.toml
uv run --project extensions/taut_tui --extra dev mypy \
  extensions/taut_tui/taut_tui extensions/taut_tui/tests \
  --config-file extensions/taut_tui/pyproject.toml
uv run --extra dev pytest -q tests/test_docs_references.py \
  tests/test_project_metadata_consistency.py tests/test_plan_status_index.py
uv run bin/check-doc-paths
uv run bin/check-plan-status-index
git diff --check
```

Before closeout, execute `bin/release.py` only in its non-publishing precheck
mode supported by the current helper. Do not invent a flag; existence-check the
exact invocation at implementation time.

## Anti-Mocking and Adversarial Proof Matrix

| Boundary | Must stay real | Allowed control seam |
|----------|----------------|----------------------|
| C1/C2/T2 | SQLite file, `TautClient`, public/domain call path | Clock or identity fixture only |
| M1/M3/M4 | Actual asyncio futures/events and reactor lifecycle | Deterministic barriers; no wall-clock sleeps |
| T9/T10 | Textual app/session lifecycle and pilot mouse events | Injected failing watcher/client owner |
| T11 | Real executor queues and blocked foreground futures | Events to release workers after assertions |
| S1 | Real child process, OS pipe, blocking payload | Scripted child behavior; platform capability marker |
| S2/S3 | Real generation teardown and synchronization | Deterministic events and controlled monotonic clock |
| P2/P3 | Public client, real SQLite/PostgreSQL, real release command list | Stable fixtures and command runner capture |

Apply the CLI/parser adversarial floor to C2, bare list, P1, and the release
helper: malformed/missing configuration, closed output, dependency failure,
correct exit class, no traceback, and no partial success claim.

## Out of Scope

- Publishing, tagging, version bumps, changelog release notes, or pushing 0.9.0.
- Changing duplicate-join notice semantics, unread definitions, notification
  delivery guarantees, message-deletion cascade rules, or search semantics.
- Redesigning MCP teaching text, TUI navigation, Summon provider protocols, or
  persistence formats.
- Claiming U+009B exploitability beyond the supported Unicode/C1 parser model.
- Removing or replacing standing MCP PostgreSQL CI.
- Refactoring adjacent executors, watchers, or reactor abstractions without a
  finding-specific need.

## Deviation Log

| Spec ref | Planned behavior | Actual behavior | Rationale | Spec proposal |
|----------|------------------|-----------------|-----------|---------------|
| [TAUT-12.5] | Add MCP PG conformance to the release helper, but the initial Proposed Spec Delta omitted the enumerable precheck sequence. | A second `bin/pytest-pg` invocation selects the MCP PG conformance file immediately after the ordinary PG gate. | [TAUT-12.5] owns the exact universal sequence, so changing code alone would create contract drift. | Promoted to `docs/specs/02-taut-core.md` during Slice 6 before further release work; requires independent revision review. |
| [TUI-3.2], [TUI-6.2]-[TUI-13.3] | Each TUI behavior test should have been observed failing before its implementation edit. | The delegated TUI slice implemented code before running the new tests as RED; the tests are green and map one-for-one to T1-T11. | This violates the plan's TDD order. Substitute proof is the prior independent code/live reproduction for each defect, the report's differential evidence, and the final real-boundary firing matrix. It does not establish a compliant red-green sequence and must remain disclosed. | No product-spec change; process deviation closed by explicit record and independent completed-work review. |
| [SUM-7.1], [SUM-7.4], [SUM-11] | Each Summon regression should have a clean standalone RED command before implementation. | The delegated Summon slice wrote the regressions after the verified evaluation; its first focused run was then blocked at collection by a concurrent shared-tree import error. All S1-S6 tests and real-process proofs are green, but the slice lacks a clean test-first RED transcript. | This violates the plan's TDD evidence order. Substitute proof is the evaluation's live S1/S3 reproductions, exact code-path evidence for S2/S4-S6, and the final real-process/firing matrix. The limitation remains disclosed. | No product-spec change; process deviation closed by explicit record and independent completed-work review. |

## Independent Review Log

| Date | Reviewer and baseline | Verdict/findings | Disposition |
|------|-----------------------|------------------|-------------|
| 2026-08-14 | Claude Opus read-only plan review at `74e1455` | PASS; R1 corrected a nonexistent `add_thread_member()` name; R2 added the governing [TAUT-7.4] citation; R3 required the direct MCP PG command to be treated as DSN-backed smoke rather than standalone proof; R4 accepted [TUI-6.3] as the better deletion-refresh home. No P1/P2 findings. | R1-R3 accepted and applied. R4 accepted as no textual change because [TUI-6.3] owns the action and the plan already preserves [TUI-9.2] state. |
| 2026-08-14 | Claude Opus read-only round-two review | PASS; verified only the accepted R1-R3 corrections against real symbols, [TAUT-7.4], and the actual `SIMPLEBROKER_PG_TEST_DSN` owner; no new defect found. | Review loop closed. |
| 2026-08-14 | Claude Opus read-only completed-work review of the integrated worktree | PASS; no P1/P2/P3 defects. The review accepted the added [TAUT-12.5] release sequence and found one pre-existing, out-of-scope observation: actor-free explicit maintenance paths still distinguish an invalid directory only after backend construction. Its declared spot-check did not line-review M2, T3-T11, or S3-S6. | No implementation change. Kept the maintenance-directory observation out of scope because C2 governs explicit client selectors and P1 governs missing-backend diagnostics. Requested the supplemental review below rather than treating partial coverage as completion. |
| 2026-08-14 | Claude Opus supplemental read-only review of M2, T3-T11, and S3-S6 | PASS; verified each mechanism and firing regression against the baseline. Non-blocking observations: tool-level MCP descriptions outside the [MCP-5] property table remain protected mainly by the manifest hash; the Textual-floor test need not also ban every stale version string; adjacent live-session tests, rather than the T5 kind-guard test itself, provide T5's live boundary. | No implementation change. Each observation is outside the verified finding or is already covered by an adjacent real-boundary test; the completed-work review loop is closed. |

## Implementation Log

| Date/slice | Evidence | Result |
|------------|----------|--------|
| Plan authoring | Independent verification reproduced C1, M1, S1, S3, C2, and the bare-list behavior; code/spec/test/history inspection classified every report claim. | Plan starts from 21 confirmed, 6 partly confirmed, and 2 refuted/stale claims; the register narrows each partial claim. |
| 2026-08-14, spec promotion | Owner authorization accepted both reviewed deltas. Applied [TUI-6.3], [SUM-7.4], and reciprocal Related Plans links; `check-plan-status-index`, `check-doc-paths`, reference tests, and `git diff --check` passed. | Active implementation now targets the promoted worktree baseline above. |
| 2026-08-14, Slice 2 | C1-C3 regressions observed RED then GREEN; the bare-list proof passed first run because behavior was already correct. Full `test_client.py`, `test_identity.py`, and `test_cli.py` gate passed with one Windows-only skip. | Rejoin preserves the stored cursor; directory selectors fail with Taut's hint; synthetic session zero scores; bare-list exit/stderr is pinned. Duplicate notices did not change. |
| 2026-08-14, Slice 3 | M1-M4 firing tests observed RED then GREEN. Full non-PG MCP suite passed; Ruff and package-local mypy passed. | Degraded work waits for lifecycle wake, teardown closes admission, canceled shield futures are retrieved without canceling reactor work, and every [MCP-5] teaching row has a direct semantic assertion before the refreshed hash. |
| 2026-08-14, Slice 4 | Full retained-lock TUI suite passed 196 tests; metadata consistency passed 4 tests; Ruff and 29-file mypy passed. | T1-T11 are implemented through real SQLite/Textual/public-client boundaries. The missing pre-fix test transcript is disclosed in the Deviation Log; prior reproductions plus the firing matrix are the substitute proof. |
| 2026-08-14, Slice 5 | Focused S1-S6 and changed-owner tests passed; serial broad Summon unit and required four-worker process selections passed; Ruff and 40-file mypy passed. | Stream writes are epoch-cancelable on capable real pipes, control error remains primary through teardown, PTY settle uses one wakeable budget, Claude skips session wait, C1 is stripped only from detached injection, and confirmation performs the final read. One auto-xdist run hung after all dots during gateway teardown; the identical serial selection and isolated process lane passed. |
| 2026-08-14, Slice 6 | Missing-PG doctor/dump/load/client tests passed; portable ASCII search passed on real SQLite and PostgreSQL; PG Unicode/diacritic/oversized-lexeme test passed; distinct MCP PG harness passed 7 tests. `test_release_script.py` passed with exact command order. | P1-P3 are closed. Implementation exposed the omitted [TAUT-12.5] delta; it was promoted and recorded before further release work. |
| 2026-08-14, integrated verification | Focused core/persistence/release set and full non-PG MCP suite exited 0; TUI 196 passed; Summon serial unit and four-worker process lanes exited 0; `bin/pytest-pg --fast` passed 257 shared plus 37 PG-only tests; explicit MCP PG passed 7. Ruff passed and 235 files were formatted. Five mypy owners passed 132, 12, 40, 21, and 29 files. Doc paths, references, plan index, metadata consistency, and diff checks passed. | Local completion floor is green. External live-harness/local-LLM release lanes and hosted CI are not claimed here; no release was requested. |
| 2026-08-14, owner-authorized landing | `b2405c2b2107aae88a983be0a0fede22278c8ed1` (`Fix verified 0.9.0 review findings`) recorded by `git log`. | The verified implementation, promoted contracts, tests, implementation notes, and review evidence are committed. The original untracked bug-report input remains outside the commit. |

## Completion Gate

This plan may become `active` only after independent plan review is closed and
the owner accepts or revises both proposed spec deltas. It may become
`completed` only when every actionable register row has a firing test, every
slice gate and the full verification floor pass, implementation and contract
docs agree, the Deviation Log has no pending proposal, independent completed-
work review is closed, and the owner-authorized landing is verified by `git
log`. An uncommitted implementation can be reviewed, but it is not complete.
