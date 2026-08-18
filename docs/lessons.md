# Lessons Learned

Startup context is the Golden Rules plus entries after the watermark in
`docs/coalescing.md`; the rest of this ledger is searchable history.

Use this file for durable, project-level lessons that should influence future
sessions.

## Topic Index

This index routes readers into the unchanged incident log below. It does not
reclassify, move, summarize away, or archive any lesson.

- **Universal engineering rules:** [Golden Rules](#golden-rules).
- **Concurrency, reactors, PTYs, and teardown:** search Project Lessons for
  `generation`, `owner`, `shutdown`, `interrupt`, `PTY`, and `control`.
- **SQLite, SimpleBroker, queues, and watcher wakeups:** search for `SQLite`,
  `SimpleBroker`, `handle`, `WAL`, `cursor`, and `waiter`.
- **Testing, CI, subprocesses, and release gates:** search for `CI`, `xdist`,
  `subprocess`, `coverage`, `artifact`, and `release`.
- **Specs, plans, reviews, and documentation:** search for `spec`, `plan`,
  `review`, `traceability`, and `agent`.
- **Identity, membership, and notifications:** search for `identity`, `claim`,
  `membership`, `notification`, and `direct message`.

The outside review's archive/compaction suggestion is intentionally deferred:
there is no measured read-cost baseline or approved retention policy. Any
future redesign needs its own plan and proof.

## When To Add A Lesson

- A correction exposed a repeated failure mode.
- A missing document or runbook caused rework.
- A plan or spec was too ambiguous to execute safely.
- A completed change revealed a stronger general rule than the repo previously
  encoded.

## Golden Rules

Universal principles that inform every change. The dated sections below are the
incident log; these are the durable rules distilled from it. _(2026-06-30)_

1. **Canonicalize once, at the boundary.** Normalize data at ingest/write
   boundaries through one shared helper. Never add runtime dual-case fallback
   readers — they hide contract bugs.
2. **Fix forward, never fall back.** Don't add read-time fallback modes to mask
   drift or corruption. Detect invariant violations and surface them; repair with
   forward migrations.
3. **One canonical contract across all consumers.** Same keys, shapes, and
   vocabulary everywhere. Mixed legacy keys cause cascading mismatches.
4. **Validate at write time, fail fast.** Catch errors at the point of creation,
   not in downstream batch gates or runtime checks.
5. **Update all consumers in the same change.** When renaming keys, tightening
   schemas, or changing contracts, update all producers and consumers together.
   Partial renames pass isolated checks but fail at runtime.
6. **Test what you ship.** Add a regression test with each behavior-changing fix.
   Generate fixtures through production code paths, not synthesis.
7. **Plans fail at boundaries, not in the middle.** For risky work, name what
   must not change, hidden couplings, anti-mocking rules, rollout/rollback
   constraints, and post-deploy success signals before implementation starts.
8. **If a document is human-clear but agent-ambiguous, tighten it immediately.**
   Missing owner, boundary, verification path, or required action makes agents
   guess wrong even when the prose feels obvious to a human.
9. **Agents suggest dependencies; humans add them.** An agent must not introduce
   a new dependency on its own — propose it with justification (purpose, why the
   standard library or an already-vendored dependency won't do, cost of taking it
   on). The human decides whether it enters `pyproject.toml`.
10. **Flag concerns and calibrate uncertainty, even when you did exactly what was
    asked.** Surface risks noticed in passing; distinguish verified from
    unverified claims with precise language ("I have not confirmed X") rather than
    a vague "this should work"; report blockers with precise causes.
11. **Handle the error path, not just the happy path.** A feature whose success
    path works but whose error, empty, or timeout path is silently ignored is
    incomplete. Name the failure cases in the plan and test at least one. Don't
    paper over an unexpected null or empty — find out why first.
12. **Formatting is owned by the project formatters — run them; don't hand-format,
    and don't reformat incidentally.** This repo's style is owned by `ruff format`
    and `ruff check` (line length 88), with typing enforced by `mypy taut tests`;
    let those tools decide style. In a behavior change, keep the diff to the lines
    the task requires and don't let a formatter reflow untouched code. Keep
    formatting-only churn in its own change; if a line changed only because "I was
    in there," revert it.
13. **Enumerable contracts get executable gates.** Any list a document asserts
    — issue codes, exit codes, edge cases, config keys — must be mirrored by a
    machine check that enumerates it (a firing test per element, a no-op
    prevention test per key). Prose binds only what gets checked; agents
    comply uniformly with gates and unevenly with everything else. (See
    engineering-principles §12 and testing-patterns Pattern 6.)
14. **The lessons ledger is itself a reviewable surface**, not a place
    confident text lands unreviewed — an entry can teach a disproved
    protocol as durable guidance hours after drafting. An uncommitted
    entry corrected in place owes no supersession ceremony; the
    ceremony is owed after landing. _(2026-08-07; adopted from the
    agent-theory hub @ `0423923`.)_

## Project Lessons

- 2026-08-14: A package-specific post-tag publication gate is not a substitute
  for pre-tag test evidence. When a separately shipped extension has an owned
  CI suite, give it a distinct push-triggered producer workflow and require
  that workflow's exact-SHA success before creating any coordinated release
  tag. Move the existing suite rather than cloning it, so stronger release
  evidence does not duplicate runner work.

- 2026-08-11: A successful wheel build and internal artifact verification do
  not prove that the pinned publisher can parse the wheel's Core Metadata
  version. Build backends can advance the emitted metadata independently of
  package source, while an older publisher fails before authentication or
  upload. Pin a publisher known to support the emitted metadata, assert that
  pin across every coordinated gate, and treat the failed pre-upload run plus
  untouched PyPI state as recoverable evidence rather than rerunning it.

- 2026-08-08 (revised 2026-08-13): A dependency-floor bump must reconcile
  manifests and maintained documentation, but Python tests should not mirror
  third-party requirement bounds or lock selections. The package manifest owns
  the supported range; the owning retained lock supplies reproducibility; and
  package tooling proves that the selected version satisfies the range. Review
  literal dependency claims as part of the same change, and raise each declared
  minimum to the owning lock's selected version during an approved dependency
  refresh. Add a compatibility lane only when the project deliberately promises
  support beyond the retained lock.

- 2026-08-05: Do not infer a security classification from opacity or identity
  selection. Name the actual authority boundary, emitted and persistent
  surfaces, live-state lifetime, and debug-only retention separately. A
  continuity token can be application data a deployment chooses to handle
  carefully without being a credential or security boundary. Calling it a
  secret can overclaim the product's posture and motivate lower-locality code
  whose only purpose is traceback scrubbing.

- 2026-08-04: A ported policy generator can pass an exhaustive isolated fixture
  suite while still targeting the wrong live document seam. The fixture and the
  implementation may share the same mistaken heading, marker, or path. Add one
  firing integration test against the active spec before promotion. After a
  structural refactor, also rerun repository-wide proof-path sentinels: moving a
  real call site can leave focused product tests green while invalidating the
  coverage contract that proves the path executes.

- 2026-07-13: Release checks must select the optional dependency set they
  claim to validate. A bare `uv run pytest` can inherit a stale package from an
  activated environment even when the repository maps that package to current
  editable source; importable source and installed entry-point metadata can
  then describe different versions. Use `uv run --extra dev pytest` for the
  coordinated release lanes, and keep old-version behavior in isolated wheel
  matrices instead of relying on ambient developer state.

- 2026-07-11: A tight `pytest-timeout` marker under xdist thread mode is a
  worker-kill boundary, not an ordinary failing assertion. On a saturated
  Windows runner, a real queue-handle topology test exceeded its three-second
  marker, killed the worker, and left xdist consuming the outer 20-minute job
  timeout even though the same commit passed every parallel platform lane and
  a failed-job-only rerun. Prefer deterministic call/step bounds for synthetic
  reactor loops; when a wall-clock guard is unavoidable, isolate it from xdist
  worker replacement and size it for the slow supported runner.

- 2026-07-10: A cancellation epoch cannot share the lock held across the I/O it
  must cancel. For fd-backed concurrent writers, publish cancellation under a
  short reentrant lifecycle lock, pin write-side identity with duplicated-fd
  operation leases, recheck state after both successful and failed syscalls,
  and keep interrupt ownership through fallback signaling. Close needs its own
  graceful-write lease and must drain external operations before reap; reader
  EOF ownership may remain independent because duplicates prevent numeric-fd
  reuse from redirecting leased I/O.

- 2026-07-10: Background-worker stop intent needs attempt-local state before
  object publication. A global event cleared for the next generation can lose
  a stop while construction is delayed. Publish a per-attempt stop token, check
  it after object publication but before readiness/run, and make the join fatal
  if the old owner survives so no later generation can overlap it.

- 2026-07-10 (3 entries): compatibility-floor provenance and portable test
  boundaries, verified distilled — the spec separates SimpleBroker's reference
  ownership model from its current accepted floor; wheel fixtures select a
  structural site-packages path; and the scripted-adapter tests fire both
  POSIX `send_signal()` and Windows `terminate()` branches
  (`docs/specs/02-taut-core.md`,
  `docs/implementation/05-taut-summon-architecture.md`,
  `tests/test_core_summon_wheel_matrix.py`, and
  `extensions/taut_summon/tests/test_scripted_adapter.py`).
  (distilled from 3 entries, 2026-07-10..2026-07-10, source 9410b6b)

- 2026-07-10: An integration test should own one load-bearing boundary. If its
  assertions cover event-pump throughput and ledger persistence, cleanup should
  use the product control STOP path rather than add an unrelated POSIX signal-
  delivery dependency. Keep real SIGINT coverage in dedicated lifecycle tests;
  broad incidental signal cleanup multiplies runner-specific flake without
  strengthening the behavior under test.

- 2026-08-17: A flushed readiness record is externally observable before the
  publishing call and its file context have returned. Signal or cancellation
  ownership must therefore be established before publishing readiness and must
  contain the publication call itself. Waiting for the record and then acting
  is event-based, but it is not safe if the child treats return from publication
  as the start of its lifecycle owner.

- 2026-06-12: Type-check tests when they are the executable spec proof.
  A strict source tree with excluded tests leaves a blind spot in fixtures
  and helper contracts; use `mypy taut tests` when test code is part of
  the release gate.

- 2026-06-12: Code-first was accepted for the v0.1 bootstrap uplift and
  promptly demonstrated its cost: the one module that shipped with zero
	  tests (identity capture) is exactly where the release-gating bug lived
	  (macOS `ps` truncates `exe` to 16 chars → the shell-skip walk anchors
	  on the per-command wrapper → a new identity is minted on every
	  invocation). Classification must use untruncated `argv[0]` evidence
	  alongside `comm`/`exe`, and macOS executable-path tests should symlink
	  signed system binaries rather than copying them. TDD is now the
	  codified general rule
  (`docs/agent-context/runbooks/testing-patterns.md`, rule 5); the
  bootstrap exception survives only with its test debt enumerated and
  burned down before release.

- 2026-06-12: Treat watcher construction validation and watcher refresh as
  different phases. Explicit watch filters should fail fast when no initial
  membership exists, but a missing membership during refresh is normal
  convergence and should drop the queue, clear per-thread transient state, and
  keep the watcher alive.

- 2026-06-12 (3 entries): early-foundation corrections, verified
  distilled into the spec tree — read-only identity resolution writes
  nothing (`docs/specs/02-taut-core.md`, guest resolution contract),
  vendor-whole vs contract-copy reuse modes ([TAUT-12.3]), and
  cursor-aware peek discipline for broadcast watchers ([TAUT-8.4], read
  model). (distilled from 3 entries, 2026-06-12..2026-06-12, source
  c09e95e)

- 2026-06-17: cross-backend BIGINT portability, verified distilled —
  sidecar timestamps, process ids, and uid-like values are `BIGINT` in
  documented DDL so Postgres does not truncate what SQLite accepts as
  unbounded integers ([TAUT-12.1] and the schema DDL in
  docs/specs/02-taut-core.md, matching `taut/state/_sql.py`).
  (distilled from 1 entry, 2026-06-17..2026-06-17, source 9410b6b)

- 2026-06-17: Backend-selection tests must prove resolution through the real
  client or CLI path, not just inspect config-file contents or fabricated
  error strings. A test named as precedence or missing-plugin coverage should
  fail when the actual resolver changes; otherwise it creates false confidence
  while backend drift slips through. Shared conformance modules also need an
  explicit marker guard so PG coverage cannot silently collapse to SQLite-only.

- 2026-07-02: Verification-lessons fold synced from agent-guidance
  (2026-07-02 working tree; pinned 2026-07-14: that fold landed as
  agent-guidance `5927481`, and the 2026-07-14 wave adopted by
  `docs/plans/2026-07-14-agent-guidance-propagation-plan.md` is
  agent-guidance `2f7eff6`; original note said: record the commit SHA when agent-guidance
  commits). Landed here as Golden Rule 13, engineering-principles §12/§13
  and the §8 reproduce-claims amendment, testing-patterns Patterns 5–6, the
  adversarial-acceptance-probes runbook, the decision-hierarchy
  baseline/deviation/claims additions, and the writing-plans deviation log.
  Source incident record: the backstitch repo's `docs/lessons.md`.

- 2026-07-06: distilled as engineering-principles §14, Cohesion Over File
  Size — floors, not line counts
  (`docs/agent-context/engineering-principles.md`).
  (distilled from 1 entry, 2026-07-06..2026-07-06, source 9410b6b)

- 2026-07-08: Release gates must prove the oldest supported parser/runtime
  surface when CLI grammar changed. Python 3.14 accepted
  `NAME --provider X THREAD` for a `nargs="*"` positional, while Python 3.11
  rejected the trailing thread; use installed-style smoke tests on the oldest
  supported Python for CLI parser changes, and treat local-vs-CI tool version
  drift as a release-readiness bug.

- 2026-07-08: `pytest-xdist` grouping is co-location, not isolation. A group
  such as `xdist_group("process")` puts those tests on the same worker, but
  unrelated tests still run on other workers at the same time. Real
  multi-process SQLite/PTY tests that show corruption or load-sensitive
  failures need a separate command lane, not only a group marker.

- 2026-07-08 (3 entries): real-process lane topology, verified distilled —
  materially different real-process workloads run as fresh pytest
  invocations; the deterministic summon lane gets a dedicated fresh CI
  matrix job rather than trailing broad suites in one runner; lanes stay
  correctness-first on sync semantics, overlapping independent setup (such
  as local-LLM image/model preparation) instead of weakening storage
  guarantees ([TAUT-12.5] test-lane text in docs/specs/02-taut-core.md,
  docs/implementation/05-taut-summon-architecture.md lane section).
  (distilled from 3 entries, 2026-07-08..2026-07-08, source 9410b6b)

- 2026-07-08: Release-helper lane splits must be mirrored in reusable CI
  workflows. Splitting summon local release gates is insufficient if the GitHub
  process matrix keeps the old broad selector and drives external live harness
  placeholders plus deterministic process tests through one long SQLite-heavy
  worker. Guard the exact CI selector in workflow tests so local release
  readiness and tag-gate readiness do not drift.

- 2026-07-08 (7 entries): shutdown and supervision lifecycle, verified
  distilled — control cleanup is consume-and-close (per-request random reply
  queues, driver-evidence fence, handle close), never delete-all; signal and
  control stop paths publish shutdown and request nonblocking adapter close
  before any join; watcher death is a watcher-rebuild signal over the same
  live provider session, never a silent stall and not an automatic provider
  crash; health separates repeated drain failure (degraded) from programming
  errors (fatal); wake callbacks are hints rechecked against authoritative
  state with no second retry policy; copied Weft primitives stay copied with
  Taut adaptation in `TautWatcher` subclasses (docs/specs/04-summon.md
  control/shutdown/supervision text, docs/specs/02-taut-core.md watcher and
  reactor text, docs/implementation/04-taut-architecture.md and
  05-taut-summon-architecture.md).
  (distilled from 7 entries, 2026-07-08..2026-07-08, source 9410b6b)

- 2026-07-08: Do not pass intentionally large integration-test payloads as
  subprocess argv. Local hosts may tolerate a 200 KB argument, while GitHub
  Linux runners reject it with `E2BIG` once interpreter paths and environment
  size are included. When the production CLI supports stdin, real-process test
  fixtures should use the public stdin path for large bodies and keep argv for
  routing, flags, and small contract tokens.

- 2026-07-08 (2 entries): detached PTY startup, verified distilled — the
  pump starts immediately after spawn, before rejoin and thread setup, so
  terminal queries are answered; the human attach path stays the
  single-reader exception; STOP/SIGINT interrupt pre-watch phases with an
  orientation write interrupted by shutdown classified as clean exit; the
  CI local-LLM lane prewires the synthetic PTY member as already onboarded
  (docs/specs/04-summon.md detached-startup and local-LLM lane text,
  docs/implementation/05-taut-summon-architecture.md).
  (distilled from 2 entries, 2026-07-08..2026-07-08, source 9410b6b)

- 2026-07-08..09 (4 entries): SimpleBroker retry/handle ownership and the
  version-floor correction chain, verified distilled — SimpleBroker owns
  queue-operation retry; Taut layers no retry classifier and never treats
  `malformed`, magic mismatch, disk I/O, or row-decode errors as transient
  by substring; long-lived actors own persistent handles and close/reopen
  them on surfaced faults; one lost control reply is recoverable while
  repeated drain failures degrade control health. The 5.1.x floor
  conclusions were superseded in place: the spec now separates the 5.2.0
  reference ownership model from the first accepted runtime and the current
  floor (docs/specs/02-taut-core.md broker-ownership and floor text,
  docs/specs/04-summon.md control-health text,
  docs/implementation/05-taut-summon-architecture.md). Forensic gist kept:
  thread-local core staleness surfaced as malformed/disk-I/O reads while
  `PRAGMA integrity_check` stayed `ok`.
  (distilled from 4 entries, 2026-07-08..2026-07-09, source 9410b6b)

- 2026-07-10: A bounded thread join is not proof of teardown. A supervisor must
  check that the worker actually stopped before starting the next generation,
  retire a timed-out generation, and fence every external side effect on the
  active generation. Otherwise a stale worker can corrupt session, presence,
  chat, exit-code, and wake state after the next child starts.

- 2026-07-10: Paired-package compatibility must verify fresh, explicitly
  selected build outputs after normal builds and before any irreversible
  release mutation. Reusing persistent `dist/` contents or making the gate a
  skippable precheck can validate the wrong wheels while a release still
  proceeds.

- 2026-07-08: Real process tests can need narrower xdist topology without
  opting out of xdist. When each test starts several subprocesses against a
  shared temporary SQLite file, `xdist_group` co-locates items but does not
  reduce the worker count or maintenance-write pressure. Use a one-worker
  xdist lane and pin test-only SQLite maintenance settings instead of treating
  load-sensitive timeouts as expected slowness.

- 2026-07-08 (5 entries): superseded transient-retry guidance, folded to
  git — these entries prescribed wrapper-shape retries, substring-transient
  classification, malformed-rows-as-"not ready" masking, role-differentiated
  Taut retry budgets with an executable budget-order guard, and per-probe
  reader reopening. All were artifacts of the removed Taut-owned broker
  retry layer; the surviving rule is the inverse and is owned with firing
  no-retry tests (SimpleBroker owns retry; Taut classifies nothing as
  transient by substring; the harness must not hide malformed rows or churn
  fresh clients — docs/specs/02-taut-core.md, docs/specs/04-summon.md,
  docs/implementation/05-taut-summon-architecture.md;
  `taut/_broker_retry.py` is a fail-closed shim).
  (superseded; folded from 5 entries, 2026-07-08..2026-07-08, source
  9410b6b)

- 2026-07-08 (5 entries): summon real-process readiness barriers, verified
  distilled — readiness is downstream of the watcher's first drain and is
  proven by a correlated PING/STATUS control round-trip; session rows,
  provider starts, and logs are diagnostics, not readiness; probe timeouts
  and the overall readiness deadline are bounded separately; harness
  factories without a received-log keep the weaker portable barrier and owe
  their own provider-specific proof before control traffic; readiness
  helpers reuse one reader rather than tight fresh-client polling loops
  (docs/specs/04-summon.md driver-readiness text,
  docs/implementation/05-taut-summon-architecture.md real-process harness
  posture, and the conformance-barrier note in
  `extensions/taut_summon/tests/test_conformance.py`).
  (distilled from 5 entries, 2026-07-08..2026-07-08, source 9410b6b)

- 2026-07-08: Native activity waiters need an arming-point proof before they
  are used as a readiness boundary. If a write can land after a consumer's
  initial drain but before the first native wait is armed, a "ready" signal can
  still precede a missed message. Prefer database-wide data-version polling for
  readiness-sensitive multi-queue watchers unless the native waiter proves that
  pre-wait writes are observed.

- 2026-07-08: identity-claim race recovery, verified distilled —
  read-before-insert collisions reread the unique key and accept only
  same-owner rows; another member stays an ownership collision (the
  member-creation race text in docs/specs/02-taut-core.md, implemented in
  `taut/state/_sql.py`).
  (distilled from 1 entry, 2026-07-08..2026-07-08, source 9410b6b)

- 2026-07-08: Treat SQLite `database disk image is malformed` in real-process
  tests as a handle-lifetime bug until disproven. A summon failure recovered
  `meta.value` rows from the SimpleBroker `messages` table, which pointed away
  from control JSON logic and toward SQLite page/WAL churn. The useful fix was
  to shorten `TautWatcher` queue handles, not to broaden retries or hide the
  lane behind skips.

- 2026-07-08: Do not make cross-platform CI depend on instantaneous
  `psutil.open_files()` handle deltas for ephemeral SQLite queue tests. macOS,
  Windows, Python version, and xdist scheduling can expose temporary handle
  noise even when the queue lifecycle is correct. Assert the owned contract
  instead: the watcher creates ephemeral queues (`conn is None`), calls
  `Queue.close()` when membership churn removes a dynamic queue, and still
  delivers messages after repeated churn.

- 2026-07-08: Single-shot summon session-event writes need a larger bounded
  retry budget than ordinary polling reads. A failed readiness read can simply
  poll again, but a provider `SessionEvent` is the event pump's one chance to
  persist the resume/status session id. Give that write extra retry room, and
  make test helpers that need a token wait for a stable session row instead of
  doing one post-readiness read.

- 2026-07-08: Keep real-process control-test helpers on the same
  transient-aware session-row path as readiness helpers. A direct
  `get_session()` call inside a STATUS/PING helper can still surface the known
  malformed-row transient after the driver is otherwise ready; wait for a
  stable row before attaching driver evidence to control requests.

- 2026-07-08: Random opaque identifiers can legitimately contain human-looking
  substrings. A test that asserts a random id does not include a name such as
  `van` is probabilistic, not a privacy proof. Test opacity by controlling the
  entropy source and checking the stable shape/source contract; test
  name-derived behavior at the call sites that actually receive names.

- 2026-07-08: Do stable summon token lookups at the startup barrier, not inside
  the churn window being tested. Once `wait_for_start()` has proven the durable
  session row, the token is stable; rereading it after flood writes, mid-run
  joins, or blocked injects adds sidecar pressure unrelated to the behavior
  under test and can turn a storage transient into a false timeout.

- 2026-07-08: Once a real-process startup barrier has read a summon session
  row, reuse that row for the bootstrap control PING instead of doing a second
  sidecar read. The PING is proving the control queue, not re-proving session
  persistence; a redundant read can become the flaky surface under CI WAL
  churn.

- 2026-07-08: A PTY fake harness should write its `start` event to the same
  received-log readiness channel as scripted harnesses. A side log can prove
  PTY-specific bytes after the fact, but it cannot drive the shared
  `wait_for_start()` barrier; without that, CI failures collapse into "no
  orientation input" instead of telling whether bootstrap, spawn, or injection
  stalled.

- 2026-07-08: Retry public broker operations, not whole CLI commands. A
  whole-command retry for `taut say` can duplicate a message if the insert
  succeeded and a later cursor or notification step blipped. Put the bounded
  transient retry at the queue/sidecar operation boundary instead.

- 2026-07-08: PTY fake harnesses must model terminal input buffering while
  answering startup queries. Detached summon can inject orientation while a TUI
  is still probing cursor size or OSC colors; a real terminal does not discard
  bytes that arrive before the query reply. Preserve those bytes in the test
  harness so CI catches responder races without inventing a stricter fake than
  production.

- 2026-07-08: PTY "quiet" before first output is not readiness. A cold-start
  PTY child can take long enough on CI that injecting orientation during
  pre-output silence races process startup; wait for first observed output or a
  bounded settle deadline before orientation, then keep the local-LLM settle
  window generous enough to cover image/model cold start side effects.

- 2026-08-17: A terminal reader handoff must classify state by ownership, not
  discard everything observed by the earlier reader. Carry passive facts such
  as output time and input modes across the boundary, including partial control
  sequences. Do not carry active responder state or emit replies while the real
  terminal owns them. Test the full handoff because isolated attach and settle
  tests can both pass while their transition loses state.

- 2026-07-12: Developer-facing path identifiers should be serialized with an
  explicit separator contract. Interpolating `Path` directly makes diagnostics
  and their tests host-dependent; use `as_posix()` when the identifier belongs
  to repository syntax rather than the local filesystem UI.

- 2026-07-12 (1 entry): synchronous signal-context ownership, verified
  distilled — `BaseReactor` handlers publish stop/wake state and unwind;
  resource close, joins, and native waiter teardown stay in ordinary cleanup
  (`docs/implementation/05-taut-summon-architecture.md` and the real
  `BaseReactor` signal probe).
  (distilled from 1 entry, 2026-07-12..2026-07-12, source 9410b6b)

- 2026-07-12: A synthetic PTY peer must consume terminal-reset output before
  joining code that restores termios with `TCSADRAIN`. Joining first can make a
  correctly recognized detach look hung because the test itself withholds the
  drain condition.

- 2026-07-13: One xdist worker was a stabilization measure for Summon's real
  process lane, not a product invariant. Each worker multiplies a complete
  driver/provider/CLI topology, so pressure should be fixed and bounded rather
  than absent or tied to host CPU count: four workers in local release checks
  and two per CI runner. Keep each selected test's resources local, keep broad
  default runs co-located under `loadgroup`, and use `load` only in the isolated
  deterministic lane. External-live and local-LLM lanes retain their separate
  known-safe one-worker boundaries. Matrix jobs on isolated CI hosts do not
  need serialization for SQLite safety.

- 2026-07-13 (2 entries): parser-backstop and cancellation-scope rules,
  verified distilled — global option hoisting preserves the parser's missing-
  value matrix, while expected cancellation leaves its `except` scope before
  cleanup consults `sys.exception()` (`docs/specs/02-taut-core.md`,
  `docs/implementation/05-taut-summon-architecture.md`, parser regression
  tests, and the live driver/PTY/stream cleanup symbols).
  (distilled from 2 entries, 2026-07-13..2026-07-13, source 9410b6b)

- 2026-07-13: A consistency test should verify derived state, not become a
  second source for the same release literal. Put ownership in package
  manifests, make the explicit release workflow reconcile every derived copy
  and commit its exact allowlist before running the gate, then test relations
  such as “README floor equals manifest floor.” Keep human-authored inputs such
  as changelog prose as pre-mutation checks. This turns serial metadata failures
  into one deterministic preparation step without weakening the release fence.

- 2026-07-13: A session-scoped pytest fixture is scoped to one xdist worker,
  not one distributed test run. If that fixture builds wheels or creates a
  costly environment, every worker that receives a consumer repeats the build.
  Derive a marker and xdist group from fixture ownership during collection,
  prove the selector partition as set arithmetic, and give the real installed
  artifact tests one fresh serial owner in CI.

- 2026-07-13: `pytest-timeout` thread mode is a process-kill backstop, not a
  safe assertion boundary under xdist. A test-specific timeout can therefore
  report `node down` and erase the state needed to diagnose the test. Put real
  signal delivery in a probe child, let the pytest worker own the watchdog and
  structured result, and prove a following same-worker sentinel still runs.

- 2026-08-05: A subprocess watchdog must not start a production-behavior clock
  at `Popen`. On saturated Windows CI, interpreter and import startup can spend
  the whole budget before the child reaches the behavior under test. Use a
  structured readiness handshake, start the strict behavior deadline only
  after readiness, keep a separate bounded startup watchdog, and group the
  probe plus watchdog/sentinel tests on one xdist worker. Empty stdout then
  means startup starvation; readiness followed by timeout means a real hang.

- 2026-08-05: A publishing action can mutate its input directory after a
  successful upload, including by adding generated attestation sidecars. Do
  not weaken an exact distribution allowlist to accommodate those files.
  Reconstruct a separate clean postflight directory from the already-verified
  carried bundle, then compare those exact wheel/sdist bytes with the remote
  registry. This preserves both supply-chain attestations and strict byte-set
  verification.

- 2026-07-13: Model discovery proves inventory, not inference readiness. A
  prepared local-model smoke should poll only the cheap model-list boundary,
  then make one completion request and fail on that result. Keep production
  crash recovery enabled, but make the smoke inspect lifecycle evidence and
  reject a success that required a harness restart.

- 2026-07-13: Coverage and release evidence need explicit owners. Collect
  coverage in existing representative matrix lanes and make aggregation
  test-free. For releases, bind a canonical push run by workflow, repository,
  branch, event, SHA, and attempt; bind its artifact by immutable id and both
  outer and inner digests. Tag workflows should observe that evidence, not
  enqueue duplicate matrices or rebuild different bytes.

- 2026-07-13: A full OS/Python Cartesian product is not automatically stronger
  when each case rebuilds the same artifact topology. Make the child use the
  matrix interpreter, then factor-cover every supported Python on one OS and
  every supported OS with one representative. State both dimensions and prove
  the workflow expression so cost cannot fall by silently dropping coverage.

- 2026-07-13: A dedicated live invocation must select the live marker, not the
  whole source file. Live files often contain fast diagnostics already owned by
  the unit lane. Prove the two selectors are a disjoint union of the file, then
  keep the real smoke strict without rerunning its supporting tests.

- 2026-07-14: A test that starts `uv run --project` for another project owns
  that child project's test dependencies. Request its `dev` extra explicitly;
  an existing local `.venv` can otherwise hide a clean-runner failure where the
  child environment correctly lacks `pytest`.

- 2026-07-14: A renderer failure inside a watcher callback can be mistaken for
  poison input and retried or cursor-advanced. Preflight install-owned display
  policy before entering a deferred callback, and keep the fixed bootstrap
  diagnostic outside the failed renderer. Logging formatters need the same
  internal bootstrap handling because `logging.raiseExceptions` can otherwise
  emit its own unsafe traceback.

- 2026-07-14: A helper-thread timeout is a state transition, not just a test
  timeout. If expiry releases a real transaction or lock, scheduler starvation
  can manufacture the behavior the test is meant to reject. Keep the resource
  held until coordinator-owned cleanup releases it, and bound machine-derived
  parallelism so a high-core host cannot turn a pressure test into process and
  database oversubscription.

- 2026-07-14: Release target selection and verification scope are separate
  concerns. If each target conditionally selects its “relevant” suites, a new
  extension can ship without proving its interaction with another extension.
  Plan one repository-wide sequence per release invocation, not one sequence per
  selected package; keep any human override explicit and leave separately owned
  artifact compatibility gates non-skippable.

- 2026-07-14: Live-test enablement and strictness are orthogonal. A strict flag
  can still produce a skipped release gate if the test first sees `CI` or an
  inherited disable and never enters strict setup. Release environments must
  force both the enable flag and strict mode, with an executable test for each.

- 2026-07-14 (8 entries): verified distilled into their existing owners —
  operator configuration and typed human/machine output boundaries in
  [TAUT-3.2]/[TAUT-6.4]; deterministic backend fast-path and cross-backend
  coverage ownership in [TAUT-12] and the architecture trace; portable
  terminal targets and dual lazy-help owners in [TAUT-6.4]/[TAUT-8.2]; routine
  release classification in the writing-plans runbook; and selector-precedence
  race recovery in [IAN-3]. Symbol-liveness and focused parity tests were
  rechecked for every disposition.
  (distilled from 8 entries, 2026-07-14..2026-07-14, source 9410b6b)

- 2026-07-14: A thread event immediately before a blocking call proves only
  that the thread reached that line; it does not prove that the scheduler let
  the call reach the external system. For deterministic database contention
  tests, hold the first real lock, gate the second contender at the same
  recorded boundary, release both together, and assert the committed state.
  Do not poll a timeout-bound negative condition based on an “about to call”
  signal.

- 2026-07-27: A durable pointer can outlive the record that made it
  actionable. Before rendering a follow-up command from a notification or
  index row, revalidate the source through a cursor-neutral exact lookup and
  omit the action when it is gone. Do not reuse a stateful convenience API
  whose read side effects would change the user's position merely to decide
  what hint to print.

- 2026-07-28: Raising a dependency floor can change control-flow semantics
  outside the new API that motivated the bump. After a floor change, run the
  existing integration contracts against the resolved dependency, especially
  watcher stop, retry, and warning paths. Adapt at the public exception or
  operation boundary; do not clone dependency internals to preserve an old
  incidental behavior.

- 2026-08-05: `uv --project` selects the dependency project but does not
  change the command's working directory. Verification commands must still use
  repository-relative paths (or an explicit directory contract). For the
  intentionally lockless PG extension, use the root dev environment plus an
  editable PG install for ordinary collection rather than creating a
  non-canonical lock as a probe side effect.

- 2026-08-05: An exact list comparison for `__all__` silently makes iteration
  order part of the public contract. When only export membership is intended,
  assert set equality and assert cardinality separately so order may be
  normalized without allowing duplicates.

- 2026-08-05: An awaited sleep establishes a minimum suspension, not a maximum
  one. A test must not assert that an intermediate timed state still exists
  after the task resumes. Prove the deadline calculation with a controlled
  clock, then let the real-thread integration test assert eventual output and
  timestamps; runner descheduling can delay observation without violating the
  producer's pacing contract.

- 2026-08-10: Stream write boundaries are not stream read boundaries. A pipe
  or PTY consumer may coalesce two correctly serialized writes into one read,
  or split one write across reads. Serialization tests should control the
  producer-side contest, then compare the reconstructed byte stream and its
  order. They must not require the consumer's event chunks to mirror writes.

- 2026-08-10: Windows `select()` accepts sockets, not anonymous pipe file
  descriptors. Where Python exposes public nonblocking pipe controls, prove a
  pipe is full by writing until `BlockingIOError`, then restore blocking mode.
  A second `select()` check is redundant on POSIX and invalid on Windows. Older
  Python/Windows combinations without those controls need an explicit
  capability skip plus a deterministic blocking-stream behavior owner.

- 2026-08-11: A runner-hosted observer can deadlock the workflows that produce
  its evidence when both share a bounded runner quota. Create producer evidence
  first and observe it from the initiating process; keep later hosted observers
  only where they own artifact selection or publication defense in depth.

- 2026-08-11: Replacing a repeated OS/Python Cartesian suite with factor
  coverage is safe only when collection itself is the executable oracle. Prove
  that every shard is nonempty, shards are pairwise disjoint, and their union
  equals the full selection. Hash the scheduler's complete group identity after
  dynamic markers, not a node ID or one closest marker, or tests that require
  co-location can split.

- 2026-08-13: Hiding a modal widget tree is not an input boundary. A terminal
  UI can keep routing keys to the active screen and focused field even when
  that screen is not displayed. For a recovery-only state such as
  `too-small`, place an opaque focus-owning screen above the whole modal stack,
  test that hidden input cannot change, and test both initial startup and
  nested-modal recovery. Also bound a retained wrapped-row offset to the new
  row height when width grows, or the next message silently becomes the scroll
  anchor.

- 2026-08-13: Catching a cross-thread scheduling call does not contain the
  callback it schedules. Logging, readiness, and operation-result presentation
  need an exception boundary inside the UI-loop callback itself. The same
  liveness token used by the worker owner must be checked when that callback
  executes, not only when it is queued, or a retired run can resurrect visual
  state.

- 2026-08-13: An optional dependency extra is an installation convenience, not
  a package-ownership seam. When a capability is defined as an extension, its
  implementation, framework dependencies, command manifest, tests, lock, and
  release target belong to the extension distribution. A core extra may depend
  on that distribution, but placing the implementation under core creates the
  wrong interface even if ordinary core imports remain lazy.

- 2026-08-14: A PID is not a stable process identity, and `os.kill(pid, 0)` is
  not a portable harmless existence probe. Windows routes non-console signal
  values through `TerminateProcess`, while a completed child's PID may also be
  reused before a later assertion. Capture a process object while the owned
  child is known live, then assert on that retained creation identity.

- 2026-08-14: Reaping a child before releasing its streams does not guarantee
  that another thread blocked in Python-level stream iteration has observed
  EOF. Closing the wrapper can wake that reader with `ValueError`. Normalize
  it as EOF only when the lifecycle owner has already published terminal
  retirement and that exact stream reports closed; otherwise preserve it as a
  fatal read failure.

- 2026-08-14: A path literal that is absolute on the authoring OS is not a
  portable absolute-path fixture. When the behavior under test is native path
  validation, derive both ambient and explicit paths from pytest's `tmp_path`;
  otherwise Windows can correctly reject the fixture while the test calls it
  an application failure.

- 2026-08-14: A UI test must synchronize both the input precondition and the
  asynchronous result boundary. Calling `focus()` does not prove that the
  framework has committed focus before the next key, and a fixed count of
  short event-loop pauses is not proof that a multi-stage worker result was
  applied. Wait for committed focus, then signal from the real result-apply
  callback and retain exact final-state assertions. The timeout remains only a
  deadlock fail-safe, not the success condition.

- 2026-08-14: Remote-observation success is not transferable consistency
  evidence across CI runners. A publisher can observe complete PyPI state while
  a fresh finalizer briefly reaches a CDN node that still reports absence.
  Every independent observer guarding a one-way transition must establish its
  own bounded semantic convergence. Retry only exact pending states; malformed
  responses, unexpected files, and digest mismatches remain immediately fatal.

- 2026-08-14: A timeout stack samples the operation that happened to own the
  thread at the deadline; it does not prove that operation is stuck. In a broad
  integration test, measure each body and each entered/returned phase before
  assigning production ownership. If unrelated fixture setup consumes most of
  the deadlock budget, give that setup a bounded public lifecycle suited to the
  test and move the default-lifecycle contract to its own real-operation test.
  Keep external observers and all product assertions unchanged, and do not
  claim that the refactor excludes a rarer production race.

- 2026-08-14: Automatic subprocess coverage assumes normal process exit. A test
  that deliberately kills a child can race coverage database creation and
  leave a zero-byte shard even though its assertion passes. Do not teach the
  combiner to ignore that evidence. Exclude only modes whose successful
  assertion requires forced termination. Let malformed-but-normally-exiting
  children reap and save coverage before reporting their protocol failure;
  retain coverage on the successful product-path child, and keep raw-shard
  validation fail-closed.

- 2026-08-17: A cross-platform host-routing test must not acquire an
  OS-specific provider transport before reaching the host boundary it owns.
  Use the cross-platform external-provider seam, supply only the capability
  needed to reach that boundary, and make any provider spawn a firing failure
  when the contract is pre-spawn cancellation. Observe the exact foreground
  result as well as the host callback so an early transport failure is reported
  causally instead of becoming a generic polling timeout.

- 2026-08-17: When a complete CI suite makes continuous passing progress but
  exhausts a fixed hosted-runner wall-time cap, reduce aggregate exposure with
  bounded parallelism rather than extending the cap. Choose the scheduler by
  fixture ownership: when all consumers of a session-scoped expensive fixture
  live in one file, `loadfile` keeps them on one worker and avoids duplicate
  fixture construction. A fixed worker count avoids host-dependent pressure.

- 2026-08-18: Textual widget events carry no input-source discrimination: a
  programmatic `TextArea.text` assignment posts the same `Changed` event as
  typing, and assigning `OptionList.highlighted` for scroll restoration
  posts the same `OptionHighlighted` as user navigation. Any handler that
  triggers behavior from such events (promotion, selection tracking) must
  discriminate the source itself — count expected programmatic edits, or
  never route restoration through the state the handler owns. Relatedly,
  capture view state (scroll anchors) when *leaving* a surface, never on
  arrival: a hidden widget's geometry is stale and capture-on-arrival
  destroys the stored truth.

- 2026-08-18: Every direct worker-to-UI apply path needs the same teardown
  attachment guard as the future-watching path, and a UI-loop caller must
  never block on a cleanup future that a worker parked in a UI marshal is
  ahead of — the loop cannot service the marshal while blocked, so the wait
  can only time out. Give session cleanup a `wait=False` shape for loop
  callers and let the non-daemon executor drain at interpreter exit.

## Starter Lessons

- Keep canonical agent guidance in shared repo-owned docs and make root agent
  files point to that context instead of carrying divergent copies.
- Non-trivial plans must be executable by a zero-context engineer: exact
  source references, exact files, invariants, verification commands, and a
  fresh-eyes review are required.
- Specs define intended behavior; implementation docs explain why the current
  design exists. Blending those roles causes drift.
- Documentation maintenance is part of the completion gate. If code changes
  without plan/spec/implementation alignment, the work is incomplete.
- Non-trivial plans should be reviewed by an independent agent, and the
  authoring agent should answer each review point by updating the plan or
  documenting why the current path is still the best choice.
- Prefer symlinks from tool-specific root guidance files such as `CLAUDE.md`
  to `AGENTS.md` when the environment supports them; thin pointer files are the
  fallback.
- Optimize docs for agent usability, not just human readability. If something
  is human-clear but agent-ambiguous, call it out and suggest a specific fix.
  Check for missing owner, boundary, verification, or required action.
