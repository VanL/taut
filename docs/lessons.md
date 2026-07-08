# Lessons Learned

Use this file for durable, project-level lessons that should influence future
sessions.

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

## Project Lessons

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

- 2026-06-12: Allocate broker timestamps only after a command is known to
  mutate taut state. A timestamp generated for convenience still updates the
  broker's high-water mark; doing that during guest read-only identity
  resolution violates the "nothing is written" contract and can distort
  thread metadata if later code reads database-wide timestamp hints.

- 2026-06-12: Treat watcher construction validation and watcher refresh as
  different phases. Explicit watch filters should fail fast when no initial
  membership exists, but a missing membership during refresh is normal
  convergence and should drop the queue, clear per-thread transient state, and
  keep the watcher alive.

- 2026-06-12: Two different reuse modes, chosen by the shape of the
  source. Vendor whole-and-faithfully when the source is one stable
  class (taut's multi-queue watcher: copied entire, provenance recorded,
  diffable against upstream). For an evolving multi-part subsystem
  (Weft's agent task), partial vendoring is reimplementation in denial —
  the extraction cuts exactly the interactions where bugs live and the
  copy drifts. There, copy the *contract* (verbs, queue shapes,
  semantics, with divergences documented) and transfer findings as a
  portable executable conformance suite both projects run, not as prose
  lessons. See `docs/specs/02-taut-core.md` [TAUT-12.3].

- 2026-06-12: Consume-oriented watcher primitives do not transfer to
  broadcast/history semantics unmodified. Weft's `MultiQueueWatcher` PEEK
  mode head-peeks (`peek_one()`), so without a per-queue cursor it
  re-delivers the head message and never lets the queue go inactive. Any
  peek-based consumer needs cursor-aware fetch *and* cursor-aware pending
  checks (`peek_many(after_timestamp=…)` + `has_pending(after_timestamp=…)`).
  See `docs/specs/02-taut-core.md` [TAUT-8.4] and comprehension Q1/Q2 in
  `docs/plans/2026-06-12-taut-foundation-plan.md`.

- 2026-06-17: Treat cross-backend integer types as an executable portability
  invariant, not a naming convention. SQLite accepts SimpleBroker's 64-bit
  hybrid timestamps in `INTEGER` columns, but Postgres `integer` overflows.
  Sidecar columns that store timestamps, process ids, or uid-like values must
  be documented and implemented as `BIGINT` before PG acceptance tests can be
  trusted.

- 2026-06-17: Backend-selection tests must prove resolution through the real
  client or CLI path, not just inspect config-file contents or fabricated
  error strings. A test named as precedence or missing-plugin coverage should
  fail when the actual resolver changes; otherwise it creates false confidence
  while backend drift slips through. Shared conformance modules also need an
  explicit marker guard so PG coverage cannot silently collapse to SQLite-only.

- 2026-07-02: Verification-lessons fold synced from agent-guidance
  (2026-07-02 working tree; record the commit SHA when agent-guidance
  commits). Landed here as Golden Rule 13, engineering-principles §12/§13
  and the §8 reproduce-claims amendment, testing-patterns Patterns 5–6, the
  adversarial-acceptance-probes runbook, the decision-hierarchy
  baseline/deviation/claims additions, and the writing-plans deviation log.
  Source incident record: the backstitch repo's `docs/lessons.md`.

- 2026-07-06: Cohesion beats file size; floors beat line counts. Do not
  propose or perform a file split on size grounds alone, and do not treat
  file size by itself as a review finding — a large cohesive module like
  `taut/state/_sql.py` is a deliberate pre-joined index for grep-navigating
  agents, not neglected debt. What is a finding, at any size: an implicit
  coupling with no explicit marker at the edit point, or a live-state machine
  (queue activity, cursors, stop ordering — e.g. `MultiQueueWatcher` in
  `taut/watcher.py`) without a name and a firing contract test. Codified as
  engineering-principles §14
  (`docs/agent-context/engineering-principles.md`).

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

- 2026-07-08: Do not pass intentionally large integration-test payloads as
  subprocess argv. Local hosts may tolerate a 200 KB argument, while GitHub
  Linux runners reject it with `E2BIG` once interpreter paths and environment
  size are included. When the production CLI supports stdin, real-process test
  fixtures should use the public stdin path for large bodies and keep argv for
  routing, flags, and small contract tokens.

- 2026-07-08: Signal-driven shutdown must close blocked adapters before waiting
  behind unrelated joins. A SIGINT handler that only sets an event is not enough
  when another path is in a restartable syscall or a PTY child is waiting on a
  terminal query; shutdown ordering should interrupt/close the adapter first,
  then drain watchers and pumps. Idempotent control probes (STATUS/PING) should
  retry with the same reply route so one transient lost reply does not turn a
  healthy driver into a false timeout.

- 2026-07-08: Long-lived process supervisors must propagate owned-thread death
  as a first-class state transition. A child process can be healthy while its
  watcher thread has exhausted broker retries or exited; if the supervisor waits
  only on child death or explicit shutdown, the member becomes live-but-deaf and
  tests fail as slow timeouts. Wrap watcher threads so unexpected exit wakes the
  supervisor and drives the same replay/resume path as child failure.

- 2026-07-08: Real process tests can need narrower xdist topology without
  opting out of xdist. When each test starts several subprocesses against a
  shared temporary SQLite file, `xdist_group` co-locates items but does not
  reduce the worker count or maintenance-write pressure. Use a one-worker
  xdist lane and pin test-only SQLite maintenance settings instead of treating
  load-sensitive timeouts as expected slowness.

- 2026-07-08: Retry policies must cover the public wrapper shape of a transient,
  not only the low-level exception. SimpleBroker can turn a transient SQLite
  malformed-page read during connection setup into
  `RuntimeError("Failed to get database connection: ...")`; a narrowly marked
  wrapper retry is safer than broad RuntimeError retrying and prevents real
  process gates from failing on a known WAL checkpoint blip.

- 2026-07-08: Real-process readiness barriers must wait for the consumer, not
  just the child process, ledger row, or thread start. A summon provider can be
  spawned and its session row recorded before the chat watcher has entered its
  first drain; tests that speak during that gap create legitimate "message was
  before join" misses. Make any readiness log downstream of an explicit
  consumer-ready event, then wait on that log or event before asserting live
  message delivery.

- 2026-07-08: Native activity waiters need an arming-point proof before they
  are used as a readiness boundary. If a write can land after a consumer's
  initial drain but before the first native wait is armed, a "ready" signal can
  still precede a missed message. Prefer database-wide data-version polling for
  readiness-sensitive multi-queue watchers unless the native waiter proves that
  pre-wait writes are observed.

- 2026-07-08: Health flags should distinguish non-recoverable control-path
  failure from recoverable long-lived-handle failure and adjacent safety-audit
  failure. A real STOP/STATUS drain fault can make the system uncontrollable
  and should degrade immediately; a recoverable broker-handle read blip under
  heavy SQLite process churn should close/reopen the handles, let clients retry,
  and degrade only if it repeats. Otherwise a live process gets permanently
  marked unhealthy for one skipped pass.

- 2026-07-08: Read-before-insert uniqueness checks need an idempotent collision
  path. Deterministic identity claims can be recorded by two processes at the
  same time; if the insert loses the race, reread the unique key and accept it
  only when it belongs to the same owner. Treating the primary-key collision as
  fatal turns normal concurrent recognition into driver crashes.

- 2026-07-08: Real-process test readiness should prove every plane the test
  will use. A driver can have a provider child, a session row, presence, and a
  watcher-ready log while its control consumer is still recovering from SQLite
  sidecar contention. If a test will send PING/STATUS or rely on later control
  health, include a bounded control round-trip in the readiness barrier and keep
  the failure diagnostic tied to the driver stderr tail.

- 2026-07-08: Watcher wake callbacks are hints, not delivery guarantees. If a
  backend data-version callback hits a known transient SQLite sidecar read
  failure, convert it into "poll soon" and keep the watcher alive; delivery
  correctness belongs to the subsequent pending scan and cursor checks.
  Letting the callback exception escape can strand a live watcher as silent
  while the provider process remains healthy.

- 2026-07-08: Do not trade SQLite sync semantics for speed in real-process
  correctness lanes. Disabling test-only maintenance writes can reduce
  irrelevant churn, but `BROKER_SYNC_MODE=NORMAL` made CI more likely to observe
  false malformed-page reads under summon driver/provider/CLI WAL load. Keep the
  slow lane correctness-first and overlap independent setup work, such as the
  local LLM image/model preparation, instead of weakening storage guarantees.

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
