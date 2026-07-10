# Taut Summon quality-remediation plan

Date: 2026-07-10

Status: implemented and verified in the working tree; independently cleared.
Changes remain uncommitted, so this plan does not claim ready-to-land status.

Plan type: implementation with spec revision.

Promotion strategy: **A — in-file edits, requirement text before link claims**.

Owner: the implementation agent owns the complete remediation. Write scopes may
be delegated by module, but the owner integrates every slice, reruns the real
gates, and answers independent review findings before completion.

## Goal

Resolve the confirmed Taut Summon state, lifecycle, control, CLI, release-gate,
test-coverage, and documentation defects without weakening the existing
single-driver, at-least-once injection, STOP ordering, no-traceback, or
installed-artifact contracts.

## Requested Outcomes

- A driver claim returns success only when the stored evidence is the caller's.
- Every final bootstrap name has a successful live claim covering it.
- Stream and PTY interruption stay bounded, reentrant-signal-safe, and do not
  corrupt shared file-descriptor or terminal-input state.
- One provider generation cannot publish lifecycle or session state into a
  later generation.
- PTY adapters do not wait for session events they cannot emit.
- Re-summon `--persona` updates persona without resetting a chat cursor.
- Explicit unsupported attach refuses loudly.
- STATUS programming failures are fatal, STOP release-error replies fire in
  tests, and rate audit uses message age rather than detection time.
- Every confirmed CLI branch has a firing test and no known failure emits a
  traceback.
- SimpleBroker 5.2.2 is the supported runtime minimum everywhere the current
  specs, plans, implementation notes, manifests, and artifact probes state or
  enforce that floor.
- The installed-artifact verifier accepts a later valid SimpleBroker minimum,
  preserves the exact Summon-to-core floor, runs in release automation, and
  the current lint/release gates pass.
- Specs, active plans, implementation notes, and code describe the same state.

## Source Documents

Source specs:

- `docs/specs/02-taut-core.md` [TAUT-3.4], [TAUT-3.5], [TAUT-8.3],
  [TAUT-11], [TAUT-12.5]
- `docs/specs/03-identity-addressing-notifications.md` [IAN-8.2]
- `docs/specs/04-summon.md` [SUM-4], [SUM-5.3], [SUM-5.4], [SUM-7.1],
  [SUM-7.4], [SUM-8], [SUM-9], [SUM-10], [SUM-11], [SUM-12]
- `docs/specs/01-development-documentation-operating-model.md` [DOM-4],
  [DOM-5], [DOM-8], [DOM-10], [DOM-11]

Related plans and implementation notes:

- `docs/plans/2026-07-06-taut-summon-plan.md`
- `docs/plans/2026-07-07-taut-summon-pty-harness-adapter-plan.md`
- `docs/plans/2026-07-08-taut-sqlite-contention-hardening-plan.md`
- `docs/plans/2026-07-09-taut-reactor-safety-plan.md`
- `docs/implementation/04-taut-architecture.md`
- `docs/implementation/05-taut-summon-architecture.md`

Required process guidance:

- `AGENTS.md`
- `docs/agent-context/decision-hierarchy.md`
- `docs/agent-context/engineering-principles.md`
- `docs/agent-context/runbooks/testing-patterns.md`
- `docs/agent-context/runbooks/adversarial-acceptance-probes.md`
- `docs/agent-context/runbooks/writing-plans.md`
- `docs/agent-context/runbooks/hardening-plans.md`
- `docs/agent-context/runbooks/maintaining-traceability.md`

## Spec Baseline

- Repository baseline: `766e3aaf84f75046a57ef769b9c802148b42e71a`.
- This plan begins against that commit plus the existing dirty worktree. The
  user asked to preserve and extend those changes, not reset them.
- Relevant dirty-worktree content identifiers before plan creation:
  - `docs/specs/02-taut-core.md`:
    `14f4500d98150f75efc34b2272914a0471abfe0ddc86dae1566932ef82af5b2d`
  - `docs/specs/03-identity-addressing-notifications.md`:
    `45306fc33539c1617de3dd66a05164ba474cea489ddce605bcf1042dd223ef45`
  - `docs/specs/04-summon.md`:
    `d1f45ce8f60d281cca722f10bd3aefb0ac9f03e3880db5d784f6f56ad54a375a`
  - `docs/implementation/04-taut-architecture.md`:
    `3a6e7151a1827beb1b21d48eb9ff3928dfa5b51b9e17eae32304e02f893248dd`
  - `docs/implementation/05-taut-summon-architecture.md`:
    `86b27bc74ceb3bc9dd6855401fa0ab888f255f6afafaedd081fce9b37fa63018`
  - `docs/plans/2026-07-08-taut-sqlite-contention-hardening-plan.md`:
    `732e9e88b55182697aa53457a323f1e1d445ded13dd6ee61f356a93fc3074518`
  - `docs/plans/2026-07-09-taut-reactor-safety-plan.md`:
    `effaeb244d429d8ba1a21c0cc5c1ad073fa445e1218f68cfae809e8d5a581f2a`
- Promotion baseline after approved text and reciprocal plan links, before code
  edits:
  - `docs/specs/02-taut-core.md`:
    `b83074eecd787cea4b230314966acf832a9fa5afc5329f053870db857ceb4a7f`
  - `docs/specs/03-identity-addressing-notifications.md`:
    `cf1a056160fdb495cba03d3a1075464db979ea5965aa33a05439ec6ee0ecd129`
  - `docs/specs/04-summon.md`:
    `1d24a6b91e388b38af7f8c36a82318f85396b13e11acf74bc952c40622c8095e`
  - `uv run --no-sync pytest tests/test_docs_references.py -q -n0`: 2 passed.
  - `git diff --check` on the promoted specs, plan index, and this plan: passed.

## Current Context and Key Files

### State and bootstrap

- `extensions/taut_summon/taut_summon/_state.py::claim_driver` performs a
  predicated write but accepts any existing readback. Partial-null evidence
  misses SQL `= NULL` predicates and currently returns false success.
- `extensions/taut_summon/taut_summon/_driver.py::_first_summon` retries
  `set_name(target)` after a fallback `claim_name(target)` conflict.
- Re-summon has no safe public persona-update path. Calling `join()` would
  rewrite membership/cursor state, so `taut/client/_identity.py` and the state
  owner must expose a narrow, atomic `set_persona()` interface.

### Adapter and generation lifecycle

- `_stream.py::close` holds a non-reentrant lock across process waits, making a
  second main-thread SIGINT self-deadlock.
- `_pty.py` lets responder and injection writers race file status and input
  bytes; close snapshots reader ownership before reaping; spawn can close the
  same slave fd twice; interrupt permanently poisons later writes; and final
  SIGKILL timeout can return without a reaped child.
- `_driver.py` reuses generation events. A late pump can mutate the next
  generation, and pump joins are not checked before resume.

### Control and release

- `_control.py::_status_fields` turns reserved-key programming errors into an
  `ok` STATUS with `status unavailable`.
- Rate audit timestamps backlog rows at observation time, creating false
  current-window floods after recovery. SimpleBroker exposes no public hybrid
  timestamp decoder; the fix compares stored hybrid timestamps directly with
  a cutoff derived from a fresh public `Queue.generate_timestamp()` value,
  using their documented nanosecond-magnitude ordering and no private import.
- `bin/verify-reactor-artifact-compat.py` requires the literal floor
  `simplebroker>=5.2.0`, while the supported package line requires at least
  5.2.2 (and may declare a stronger compatible floor); release automation does
  not invoke the paired-artifact verifier.

### Comprehension gate

1. Why may re-summon not use `join(..., persona=...)` to update persona? It
   would rewrite membership timing/cursor state and can skip replay.
2. Why must PTY interrupt use a write epoch rather than a permanent event or a
   write lock? It must abort every normal-write call that entered before the
   interrupt without blocking behind one, while calls entering afterward use a
   new epoch and remain valid on a still-live harness.
3. Why must pump state be generation-scoped even if close normally ends the
   pump? Bounded join can expire; a late daemon thread must not mutate current
   session, exit, or wake state.
4. Why is 5.2.2 the supported floor rather than merely an accepted stronger
   floor? The real process/control proof failed under 5.2.0 and passed under
   5.2.2. The verifier may accept a later SimpleBroker `>=X` floor, but the
   Summon `taut>=...` floor must still match and admit the paired core wheel.

## Invariants and Constraints

- No new dependency and no SimpleBroker private import.
- No SQL against broker-owned tables and no Taut retry classifier.
- Claim writes are atomic and return only caller-owned evidence.
- A partial driver-evidence pair is indeterminate, never cleanly live or dead.
- Persona resolution uses the session token, updates activity and persona in
  one state transaction, accepts `None` as clear, and does not create or move
  membership, notices, or cursors. Re-summon performs it only after winning
  the driver claim and before spawning; failure follows the normal protected
  release path.
- `interrupt()` aborts an in-flight write, remains safe from a signal handler,
  and permits a later write if the child remains live.
- Injection, terminal replies, and attach-forwarded input use one serialized
  PTY normal-write path. Each call snapshots the epoch before waiting for that
  serializer; interrupt advances it without the writer lock, so active and
  queued old-epoch calls abort and later calls remain valid. Ctrl-C is the only
  out-of-band writer.
- The PTY master becomes nonblocking once before concurrent publication;
  writers never call `F_SETFL` afterward or discard unrelated descriptor
  flags.
- Reader/master ownership is reread at the close point; close cannot act on a
  stale fd snapshot.
- `interrupt()` may re-enter the main thread at any point in stream or PTY
  close without waiting on a non-reentrant lock owned by the interrupted
  frame. Exactly one concurrent closer performs escalation, reap, and stream
  or fd retirement; other closers observe the same terminal result.
- A failed reap retires the handle, unblocks readers/writers, releases the
  master once through the terminal ownership path, and raises a loud adapter
  error only after best-effort cleanup. Cleanup errors never replace an
  existing primary exception; interrupt after retirement cannot touch a reused
  fd.
- Old-generation pumps cannot perform any current/shared/external side effect,
  including durable ledger writes, control-session changes, presence updates,
  terminal-mode posts, driver fields, or wake state. A pump that misses its
  bounded join prevents generation N+1. A join timeout is primary during
  normal stop/resume; during cleanup it is secondary and cannot mask the
  original failure.
- STOP acknowledges success only after clean shutdown and confirmation that
  the driver claim is absent or replaced. Cleanup/release exceptions or
  indeterminate confirmation reply with error. STATUS/PING correlation,
  generation fences, and at-most-once command consumption do not change.
- Data-integrity and configuration errors are one-line exit-1 diagnostics.
- Rate audit compares each message's hybrid timestamp to one inclusive cutoff
  computed as a fresh public broker timestamp minus the window in nanoseconds.
  Future timestamps count as current; older rows do not acquire a new
  observation timestamp.
- Per-thread input filters are removed from the current contract rather than
  implemented speculatively.
- SimpleBroker metadata accepts only one unmarked `simplebroker>=X.Y.Z`
  requirement and requires `X.Y.Z >= 5.2.2`. Summon's unmarked
  `taut>=X.Y.Z` requirement must equal and admit the supplied core version;
  stronger-but-excluding Taut floors remain invalid.
- Every `core`, `summon`, or matching `all` release builds both wheels from the
  same checkout into fresh isolated output directories and verifies explicit
  wheel paths after build but before commit, tag, or push. This mandatory gate
  still runs under `--skip-checks`; dry-run prints it. PG-only release does not
  run it.
- Release CI enables the same paired gate only for core and Summon release
  callers, after both fresh builds and before publication. Ordinary push/PR and
  PG-only callers remain unchanged.
- Existing dirty work unrelated to these defects is preserved.

### Fatal versus best-effort

- Fatal: claim postcondition failure, bootstrap claim lapse, unreaped child,
  pump join timeout, adapter protocol/configuration error, STATUS programming
  error, installed-artifact incompatibility.
- Recoverable: current-turn PTY Ctrl-C when the child stays alive, one lost
  idempotent STATUS/PING reply, old messages outside the audit window.
- Best effort: duplicate close logging and cleanup diagnostics after a primary
  failure; they must not hide the primary exception.

### Stop-and-re-evaluate gates

Stop and revise this plan if any fix requires:

- a new dependency or a SimpleBroker private timestamp decoder;
- a second driver/state/PTY lifecycle path;
- `join()` or private core state access for persona updates;
- changing control verbs, queue names, consumption mode, or message envelope;
- weakening installed-artifact isolation;
- swallowing a data-integrity/programming error to keep a process alive.

## Rollback and Rollout

Rollback is code-and-spec atomic by slice. There is no schema migration or
one-way storage change. `TautClient.set_persona()` and its atomic state method
are additive and may remain during rollback; Summon does not require them until
the paired core/Summon release ships. Revert Summon use before reverting the
core method.

Release core and Summon as one paired batch. Run the artifact verifier after
both wheels are built and before either package is announced. Canary signals:
bounded double-SIGINT shutdown; PTY injection after a cancel; one successful
driver claim under racing takeover; PING/STATUS/STOP success; no traceback; and
no stale-pump generation wake. One-way doors: none.

## Proposed Spec Delta

Promotion strategy: **A — in-file edits, text before implementation links**.

| Spec file | Strategy | Sections touched |
|---|---|---|
| `docs/specs/02-taut-core.md` | A | [TAUT-3.4], [TAUT-3.5], [TAUT-8.3], [TAUT-11], [TAUT-12.5], Related Plans |
| `docs/specs/03-identity-addressing-notifications.md` | A | [IAN-8.2], Related Plans |
| `docs/specs/04-summon.md` | A | [SUM-4], [SUM-5.3], [SUM-7.1], [SUM-7.4], [SUM-8], [SUM-9], [SUM-10], [SUM-11], [SUM-12], Related Plans |

### `docs/specs/02-taut-core.md` [TAUT-3.4] — replace the floor sentence

> The `simplebroker>=5.2.2` floor is load-bearing. Version 5.2.0 supplies the
> reference ownership model, but 5.2.2 is the first supported release that
> passes Taut's persistent-owner process/control proof.

### `docs/specs/02-taut-core.md` [TAUT-3.5] — append

> The supported SimpleBroker hybrid encoding preserves the nanosecond magnitude
> of `time.time_ns()` while reserving low bits for logical ordering. A Taut
> time-window policy may therefore derive one raw inclusive cutoff as
> `Queue.generate_timestamp() - window_nanoseconds` and compare stored hybrid
> timestamps directly. It must not import a private decoder or convert stored
> timestamps into a second persisted clock domain.

### `docs/specs/02-taut-core.md` [TAUT-8.3] — append to the Python API paragraph

> `TautClient.set_persona(persona: str | None) -> Member` resolves the client's
> selected identity, raises `IdentityError` when none resolves, and atomically
> updates activity plus the exact persona value (`None` clears it). It does not
> create, join, or leave a thread; write a notice; or alter membership/cursor
> state. This is the public embedding seam for persona-only updates such as
> Summon re-summon.

Replace the dependency sentence with:

> Core runtime dependencies: exactly `simplebroker>=5.2.2` and `psutil`.

### `docs/specs/02-taut-core.md` [TAUT-11] — append

> - Persona-only update tests prove the member field changes while memberships
>   and cursors remain byte-for-byte unchanged; `None` clears it; unresolved
>   identity fails; and no notice is written.

### `docs/specs/02-taut-core.md` [TAUT-12.5] — append

> New core wheel metadata must contain one unmarked
> `simplebroker>=X.Y.Z` requirement with `X.Y.Z >= 5.2.2`; other operators,
> compound specifiers, markers, and weaker floors fail closed. New Summon
> metadata must retain one unmarked `taut>=<new-core-version>` requirement, so
> the supplied core wheel is admitted exactly rather than excluded by a
> superficially stronger floor.
>
> Every non-dry-run `core`, `summon`, or matching `all` release builds both
> wheels from the same checkout into a fresh temporary artifact root and runs
> the paired installed-artifact verifier with their explicit paths after both
> builds and before any release commit, tag, or push. The gate still runs under
> `--skip-checks`; dry-run prints the ordered build and verification commands.
> PG-only releases do not run it. The reusable test workflow exposes a default-
> false paired-verification input enabled by the core and Summon release gates;
> it verifies after both fresh builds and before either publication job can run.

### `docs/specs/03-identity-addressing-notifications.md` [IAN-8.2] — replace the floor

> Taut requires `simplebroker>=5.2.2` and `taut-pg` requires
> `simplebroker-pg>=3.1.0`.

### `docs/specs/04-summon.md` [SUM-4] — append to re-summon behavior

> When re-summon receives `--persona`, it updates the existing member through
> a token-selected `TautClient.set_persona()` after the driver claim succeeds
> and inside the release-protected bootstrap path, before spawning. The
> returned member id must match the claimed session member. Claim loss never
> mutates persona; update failure spawns no child and releases normally. The
> update must not re-join a thread, write a notice, or move a cursor.

### `docs/specs/04-summon.md` [SUM-5.3] — replace the final sentence

> Per-thread input filters are not part of the current `run` surface. Adding
> them requires a future spec and CLI revision; the present driver injects the
> complete non-self stream.

### `docs/specs/04-summon.md` [SUM-7.1] — extend adapter capabilities

> `ProviderAdapter.emits_session_events` declares whether startup may wait for
> a `SessionEvent`; adapters that declare false never pay that wait.
> `interrupt()` aborts any adapter write already in flight. If the harness
> remains live, later `inject()` calls remain valid; interruption is not a
> permanent poison latch. Close remains the operation that retires a handle.
> For stream and PTY handles, `interrupt()` may re-enter the main thread at any
> point in `close()` and must not wait on a non-reentrant lock owned by the
> interrupted frame. Exactly one closer performs escalation, reap, and stream
> release; concurrent closers observe the same terminal result.

### `docs/specs/04-summon.md` [SUM-7.4] — append to PTY write/fd ownership

> The PTY master is configured nonblocking once before concurrent publication,
> preserving unrelated flags. No writer calls `F_SETFL` afterward. Injection,
> terminal-query replies, and attach-forwarded human input serialize through
> one normal-writer primitive. Every normal-write call snapshots the current
> epoch at method entry, before waiting for serialization, and checks it plus
> handle retirement before every `os.write`; active and queued calls from the
> old epoch abort. Interrupt is the sole out-of-band writer: it advances the
> epoch without acquiring the normal-writer lock and writes Ctrl-C
> nonblocking. Calls entering afterward capture the new epoch and remain valid.
> Query replies retain best-effort error reporting but use the same serializer
> and epoch checks.
>
> Close re-reads reader ownership after each reap outcome and makes the fd
> ownership decision atomically under the lifecycle lock. Spawn closes each fd
> once. Failure to reap after SIGKILL permanently retires the handle, unblocks
> readers and writers, releases the master exactly once through the terminal
> ownership path, and raises `AdapterError` after best-effort cleanup. Cleanup
> errors do not replace an existing primary exception; interrupt after
> retirement is a no-op and cannot touch a reused fd.

### `docs/specs/04-summon.md` [SUM-8] — append to the single-driver guard

> A claim succeeds only when a same-transaction readback carries the caller's
> exact pid/start-time evidence. Predicated writes use null-safe expected
> evidence, so partial-null corruption can be replaced only by explicit
> takeover and can never return false success. Partial evidence is classified
> indeterminate by readers.
> `record_session` accepts driver evidence only when both values are null or
> both are non-null. Ordinary renewal requires both stored values to null-safely
> match both expected values; takeover is the only path that may replace a
> partial-null legacy row.

### `docs/specs/04-summon.md` [SUM-9] — append

> Adapter STATUS-key collisions and other programming errors are fatal control
> failures, not `status=ok` degradation. STOP replies success only after clean
> shutdown and confirmation that the driver claim is absent or replaced;
> cleanup/release exceptions and indeterminate confirmation reply
> `status=error`. Rate audit computes one inclusive raw cutoff for the pass as a
> fresh public `Queue.generate_timestamp()` value minus the configured window
> in nanoseconds, then compares each message's hybrid timestamp directly. This
> relies on [TAUT-3.5]'s supported hybrid format rather than a private decoder.
> Future timestamps count as current; old recovery backlog never receives a
> new observation timestamp.

### `docs/specs/04-summon.md` [SUM-10] — append

> A PTY hard breach cancels the current harness turn. It does not lazily poison
> the handle or force a generation restart unless the child exits or later
> adapter I/O fails independently.

### `docs/specs/04-summon.md` [SUM-11] — append

> Every spawn owns an immutable generation context containing its token,
> completion, exit, readiness, and wake state. The pump mutates only that local
> context and, immediately before every shared or external side effect, proves
> that its token is still active. A stale pump may not update driver fields,
> durable ledger state, control session, presence, terminal-mode chat, or wake
> state for any adapter event. The token is retired before a generation is
> abandoned. One checked-join helper owns every pump join; timeout prevents
> generation N+1. During normal STOP/resume it is the primary fatal error and
> makes STOP reply error; during cleanup it is secondary and never masks the
> original failure.

### `docs/specs/04-summon.md` [SUM-12] — append

> Firing tests cover invalid partial record evidence, indeterminate takeover,
> both partial-null takeover orientations, claim write postconditions,
> mid-bootstrap fallback-claim collision, double SIGINT, PTY reply/inject
> serialization, attach-writer serialization, active-plus-queued write cancel,
> reader-start-during-close, concurrent close, post-interrupt reuse, unreaped
> child cleanup/primary-error precedence, stale-pump fencing for every event,
> STOP cleanup/release error, fatal STATUS-key collision supervision,
> old-backlog rate audit, bare status success, dead-driver stop, unknown-verb
> reply, persona re-summon, unsupported attach, malformed ledger/configuration
> diagnostics, registry-wide session-event capability, the 5.2.2 floor, and
> ordered release invocation with fresh built artifacts.

## Deviation Log

| Spec ref | Planned behavior | Actual behavior | Rationale | Spec proposal |
|---|---|---|---|---|
| [SUM-7.4], [SUM-11], [SUM-12] | The promoted delta covered PTY epochs, fd/reap ownership, stale-generation effects, and checked joins. | Implementation review exposed four unenumerated boundaries: inject after close starts, invalid PTY configuration/pre-publication cleanup, readiness-wait failure during close, and event-pump broker failure transfer. | These are direct consequences of the promoted lifecycle and storage-failure invariants, but the original firing list did not make them executable. Each received a failing test before production changes. | Applied in place: exact PTY validation, foreground pump failure transfer, and the expanded [SUM-12] firing list. |

## Tasks

1. **Independent plan/spec-delta review, then spec promotion.**
   - Review this plan, current specs, implementation notes, and touched code.
   - Apply the exact delta with strategy A; add reciprocal Related Plans rows.
   - Record worktree promotion hashes before code edits.
   - Stop if reviewer cannot implement confidently or finds a contract conflict.

2. **RED→GREEN state and persona contracts.**
   - Files: `taut/client/_identity.py`, `taut/state/__init__.py`,
     `taut/state/_sql.py`, `tests/test_client.py`,
     `extensions/taut_summon/taut_summon/_state.py`,
     `extensions/taut_summon/tests/test_state.py`, and the existing PG
     sidecar/conformance lane.
   - One cycle each: atomic persona set/clear with activity; unresolved
     identity; byte-identical cursor/membership and no notice; invalid partial
     record evidence; indeterminate liveness; both partial-null takeover
     orientations; zero-row postcondition; racing claim ownership.
   - Real sidecar/SQLite and Postgres stay real; only liveness capture may fake.

3. **RED→GREEN bootstrap and CLI contracts.**
   - Files: `_driver.py`, `cli.py`, `test_driver.py`, `test_summon_cli.py`.
   - One cycle each: fallback claim conflict; losing duplicate does not mutate
     persona; token-selected persona set occurs inside the driver-release guard
     before spawn; broker-error diagnostic; bare status success; dead stop exit
     2; unknown reply body; unsupported attach; and removal of
     dead/pass-through helpers.
   - Run the first independent implementation review before task 4.

4. **RED→GREEN stream lifecycle.**
   - Files: `_stream.py`, `test_claude_adapter.py`, and
     `test_scripted_adapter.py`.
   - Prove signal reentry while the lifecycle transition lock is owned and
     during `wait()`; two concurrent closes have one escalation/stream closer;
     and post-kill timeout is one terminal `AdapterError` with no traceback or
     primary-error masking.

5. **RED→GREEN PTY lifecycle and serialization.**
   - Files: `_pty.py`, `test_pty_adapter.py`, and the fake TUI fixture. Task 5
     does not edit `_adapter.py` or `_driver.py`.
   - One cycle each: reply/inject partial-write serialization; attach forwarding
     uses the same primitive; one pre-publication `F_SETFL` preserving unrelated
     flags; active-plus-queued old-epoch cancellation; post-interrupt new-epoch
     reuse; reader-start close race; spawn fd ownership; concurrent close;
     interrupt-after-close reused-fd safety; and final reap failure with and
     without a reader plus primary-error precedence.

6. **RED→GREEN driver generation and adapter capabilities.**
   - Files: `_adapter.py`, adapters, `_driver.py`, `test_driver.py`.
   - Add a required session-event capability to every registered adapter and a
     registry-wide firing test. Add immutable generation contexts and one
     checked-join helper. Fence `SessionEvent`, `ActivityEvent`,
     `AssistantTextEvent`, and `ExitEvent` before driver-field, ledger,
     control-session, presence, post, and wake side effects. Prove join timeout
     exits 1, produces STOP error when applicable, and spawns no next
     generation. Add explicit attach refusal. No fourth driver lane.
   - Run the second independent implementation review before task 7.

7. **RED→GREEN control behavior.**
   - Files: `_control.py`, `test_control.py`, process conformance tests.
   - One cycle each: STATUS collision reaches fatal driver supervision; STOP
     cleanup/release exception and indeterminate confirmation acknowledge
     error; real driver release failure propagates; old backlog is excluded by
     one inclusive raw hybrid cutoff derived from a public broker timestamp;
     exact-boundary/future rows count; and a current-window breach remains
     enforced.

8. **RED→GREEN artifact and release gates.**
   - Files: `bin/verify-reactor-artifact-compat.py`, a narrow fresh-build
     orchestration helper under `bin/`, `tests/test_reactor_artifact_compat.py`,
     `bin/release.py`, `tests/test_release_script.py`, `.github/workflows/test.yml`,
     and the core/Summon release-gate workflows.
   - Accept only unmarked `simplebroker>=X.Y.Z` with `X.Y.Z >= 5.2.2`; reject
     weak or unsupported grammar; keep exact `taut>=<built-core-version>`.
     Build into fresh explicit directories and verify the pair for every core,
     Summon, or matching batch release after build and before commit/tag/push,
     including `--skip-checks`; PG-only skips and dry-run prints the sequence.
   - Firing tests prove fresh wheel selection; build/build/verify/order;
     verifier failure prevents commit/tag/push; single-target and batch paths;
     `--skip-checks`; dry-run; workflow default false; core/Summon opt-in; and
     verification before publish. Run the third independent implementation
     review before task 9.

9. **Traceability reconciliation and full verification.**
   - Update [TAUT-3.4], [TAUT-3.5], [TAUT-8.3], [TAUT-11], [TAUT-12.5],
     [IAN-8.2], and the listed Summon refs; fix [SUM-8]'s stale projection
     symbol names.
   - Reconcile `docs/plans/2026-07-08-taut-sqlite-contention-hardening-plan.md`
     and `docs/plans/2026-07-09-taut-reactor-safety-plan.md`: record 5.2.2 as
     the proven floor, remove the stale control blocker, and replace the false
     “implementation has not started” execution/verdict text with current
     evidence. Preserve historical reference-version statements where they
     describe provenance rather than the supported floor.
   - Update implementation docs 04/05: supported floor, paired artifact owner
     and boundary, removed filter promise, exact public Taut-module seams, and
     current process-lane evidence. Update repository map, plan index, and
     lessons only where a new durable rule emerged.
   - Run all final gates below and an independent completed-work review.

## Testing Plan

Use vertical red-green cycles: one failing behavioral test, minimal production
change, targeted green, then the next behavior. Never write the whole test
batch first.

Do not mock broker, sidecar, CLI subprocess, PTY, process signals, control
dispatch, artifact installation, or cursor state in acceptance proofs. Fakes
may control clocks, process liveness evidence, non-reaping process behavior,
and deterministic scheduling around a real interface.

`bin/verify-reactor-release-artifacts.py` is the single orchestration owner for
fresh paired builds. It creates a temporary artifact root, invokes explicit
core and Summon wheel-only builds into separate empty directories, requires
exactly one wheel in each, and invokes
`bin/verify-reactor-artifact-compat.py` with those paths and the immutable prior
refs. `bin/release.py` and release CI call this owner rather than duplicating
wheel discovery. It returns before its temporary directory is removed and
never reads persistent `dist/` output.

## Verification and Gates

Per-slice: exact new regression node, then nearest test file.

Final gates:

```bash
uv run --no-sync pytest tests/test_client.py tests/test_watcher.py -q -n0
uv run --no-sync pytest extensions/taut_summon/tests/test_state.py \
  extensions/taut_summon/tests/test_control.py \
  extensions/taut_summon/tests/test_summon_cli.py -q -n0
uv run --no-sync pytest extensions/taut_summon/tests \
  -m 'not xdist_group and not requires_live_harness and not requires_local_llm' -q
uv run --no-sync pytest extensions/taut_summon/tests \
  -m 'xdist_group and not requires_live_harness and not requires_local_llm' \
  -q -n 1 --dist loadgroup
uv run --no-sync ./bin/pytest-pg --fast
uv run --no-sync pytest tests/test_reactor_artifact_compat.py \
  tests/test_release_script.py tests/test_docs_references.py \
  tests/test_architecture_boundaries.py -q -n0
uv run ruff check taut tests bin extensions/taut_summon/taut_summon \
  extensions/taut_summon/tests
uv run ruff format --check taut tests bin extensions/taut_summon/taut_summon \
  extensions/taut_summon/tests
uv run --extra dev mypy taut tests --config-file pyproject.toml
uv run --extra dev mypy extensions/taut_summon/taut_summon \
  extensions/taut_summon/tests --config-file pyproject.toml
uv lock --directory extensions/taut_summon --check
python -m compileall -q taut extensions/taut_summon/taut_summon
uv run --no-sync python bin/verify-reactor-release-artifacts.py
git diff --check
```

The paired command is mandatory and exercises fresh builds plus installed
artifacts without committing, tagging, or pushing. It also compiles the PG
manifest in its temporary directory and rejects a resolved
`simplebroker-pg<3.1.0`; this repository retains no PG lockfile, so a persistent
PG `uv lock --check` is not a gate. External provider-live and local-LLM lanes
run if touched adapter behavior affects their contract; otherwise they remain
explicit release verification.

## Independent Review Loop

Plan review: a read-only reviewer receives this plan, its Proposed Spec Delta,
the governing specs, implementation notes, and current dirty diff. Required
question: “Could you implement every slice confidently without weakening
claim, cursor, PTY, control, or artifact invariants?”

Implementation review runs after state/bootstrap, after lifecycle/driver, after
control/release, and once more before completion. Each finding is accepted and
fixed, rejected with evidence, or marked out of scope with reason in the review
record below.

## Review Record

| Stage | Reviewer | Finding | Disposition | Evidence |
|---|---|---|---|---|
| Plan, state/control | independent state/control reviewer | Persona targeting/order, claim input integrity, PTY/pump error priority, timestamp conversion, STOP propagation, release lifecycle, and hot-file overlap were underspecified. | Accepted except the proposed new SimpleBroker decoder. Persona is token-selected/atomic and claim-protected; partial record evidence fails; lifecycle priority and STOP error are explicit; hot files are sequential. Rate audit instead compares the public hybrid value directly to an inclusive epoch-nanosecond cutoff because the encoding preserves physical magnitude, avoiding both a private decoder and a new upstream dependency. | Proposed Spec Delta and tasks 2–8. |
| Plan, lifecycle | independent lifecycle reviewer | Epoch start, attach serialization, lock-state signal reentry, terminal fd cleanup, and every stale-pump side effect lacked firing definitions. | Accepted. Old-epoch queued calls cancel; all normal writers share one path; signal/close and terminal ownership are explicit; all event side effects are fenced. | [SUM-7.1], [SUM-7.4], [SUM-11], [SUM-12] delta. |
| Plan, release/docs | independent release/docs reviewer | 5.2.2 must be the actual floor; stronger-floor logic cannot weaken the exact Taut pair; prechecks run too early; single-target and workflow owners, firing tests, and reconciliation files were missing. | Accepted. Every core/Summon release verifies fresh paired builds post-build and pre-mutation, even with `--skip-checks`; PG-only and default workflow callers stay unchanged. | [TAUT-3.4], [IAN-8.2], [TAUT-12.5], task 8, explicit final command. |
| Plan, corrected delta | independent state/control, lifecycle, and release/docs reviewers | All three reviewers answered the required confidence question affirmatively; no P1 remained. The state/control reviewer explicitly accepted the raw hybrid cutoff under promoted [TAUT-3.5]. | Cleared for spec promotion. | State/control: high confidence; lifecycle: 9/10; release/docs: clear. |
| Implementation, tasks 2–3 | independent state/control reviewer | First-summon record readback and bootstrap failures could escape release; driver release ignored an unconfirmed conditional clear. | Fixed with same-transaction record readback/rollback; name-claim cleanup across thread setup, creator close, and record failure; a bootstrap-wide driver release guard; explicit absent/null/replaced confirmation; and zero-row/partial rejection. Follow-up: clear. | 119 state/control/CLI tests; 8 focused driver tests; real SQLite trigger and Postgres race proofs. |
| Implementation, tasks 2–3 cleanup | independent release/docs reviewer | Removed status pass-through left stale tests; incompatible schema was mapped to “nothing summoned”; first-summon name claim leaked before record. | Removed the helper/tests in favor of the real ControlClient boundary; schema mismatch is one-line exit 1 for status/stop; all named bootstrap failure points release. Follow-up: clear. | Full `test_control.py`: 60 passed after the subsequent control slice; schema and three failure-point firing tests pass. |
| Implementation, tasks 7–8 | independent control/release reviewer | Per-thread audit append order made head-only pruning unsafe; release-confirmation exceptions skipped STOP error replies; a version-changing core-only release left Summon's exact core floor stale; retained/plugin resolution floors and helper spawn errors lacked gates. | Fixed red-first. Pruning filters the full deque; STOP converts confirmation exceptions to correlated errors; a core bump syncs and stages Summon's manifest and retained lock before paired verification; the helper validates the retained Summon resolution and an ephemeral PG compile, and wraps command-start failures. | 62 control tests; 89 release/artifact/workflow tests; real four-case installed-artifact helper passed with SimpleBroker 5.3.0 and simplebroker-pg 3.2.0. |
| Implementation, tasks 4–6 | independent lifecycle/driver reviewer | PTY epoch validation and most close/reap/join paths were sound, but inject-after-close, empty/unsafe PTY config, select-after-close translation, and pump `BrokerError` transfer lacked tests and failed at runtime. Follow-up found huge timing integers could overflow after child spawn. | Fixed red-first. Close state fences stream injection twice; PTY validation and broad pre-publication cleanup fail closed before `openpty`; select failures normalize to `AdapterError`; pump storage failures transfer through generation-local state to the foreground and prevent N+1. The handle protocol now carries attach/settle/onboarding directly. Follow-up: clear. | 96 adapter/conformance tests; 83 driver tests; 27 overflow/config cases; focused real BrokerError proof; Ruff and mypy pass. |
| Final completed-work review | independent fresh-eyes reviewer | Join timeout was demoted behind close cleanup; stop CLI discarded the STOP reply and used evidence semantics that treated partial rows as clear and replacement as held; active reactor gates still named 5.2.0. | Fixed red-first for runtime behavior. Join timeout now outranks cleanup absent an inherited primary; STOP requires correlated ACK and evidence-relative confirmation; active gates use 5.2.2+. Final follow-up: CLEAR, no P1/P2. | 84 driver tests; 32 CLI tests; docs references, Ruff, mypy, full suites, and final artifact helper pass. |

## Out of Scope

- New provider adapters, per-thread input-filter feature work, new control
  verbs, schema migrations, a fourth runtime lane, a new retry engine, or a new
  dependency.
- Redesigning core identity, watcher scheduling, provider protocols, or release
  versioning beyond the confirmed defects.
- Unrelated cleanup in the existing dirty worktree.

## Fresh-Eyes Review

The first independent pass rejected the draft as underspecified. Its state,
lifecycle, release, and documentation findings are incorporated above. Three
read-only reviewers then approved the corrected delta with no open P1. Owners,
interfaces, rollback, anti-mocking posture, exact tests, error priority, and
release ordering are sufficient for a zero-context implementer.

## Execution Record

2026-07-10: plan review passed after one correction round. The approved delta
was promoted with strategy A and the hashes in Spec Baseline before runtime
code edits.

2026-07-10: tasks 2–3 completed two independent correction rounds. Atomic
persona/state, claim/readback/release, bootstrap name ownership, explicit
attach, no-traceback diagnostics, schema failure, and missing CLI branch proofs
are green. The slice is independently cleared. Tasks 4–5 and task 8 now run in
parallel because their file owners are disjoint; control task 7 completed in
the foreground with 60 tests passing.

2026-07-10: the first tasks 7–8 implementation review rejected the initial
green result with four P1 gaps and one P2 diagnostic gap. Each received a
firing red test before its fix. Control now has 62 passing tests; the paired
release slice has 89 passing tests plus a successful real installed-artifact
run. The repository retains only the Summon lock; PG resolution is verified in
the helper's temporary directory rather than adopting the existing untracked
PG lock as release state.

2026-07-10: the tasks 4–6 implementation review found four additional
lifecycle/storage boundaries after the initial adapter and generation suites
were green. Red evidence covered 14 focused lifecycle failures plus a real
SimpleBroker pump failure with an unhandled-thread warning. The corrected
slices pass 90 adapter/conformance tests and 83 driver tests; the exact new
requirements were added to [SUM-7.4], [SUM-11], and [SUM-12].

2026-07-10: lifecycle follow-up found one final pre-publication overflow path
for enormous timing integers. Direct and CLI tests failed before the fix; all
27 validation cases pass now. The independent reviewer rechecked all prior
findings and returned CLEAR.

2026-07-10: final completed-work review found teardown error-priority, STOP
client ACK/evidence, and active-plan floor gaps. The runtime gaps received
failing tests before correction. Final follow-up returned CLEAR with no open
P1/P2. All requested code and documentation are verified in the worktree but
remain uncommitted, so the repository's commit-based ready-to-land gate has not
been claimed.
