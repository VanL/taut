# Taut dynamic native-waiter replacement plan

Date: 2026-07-10

Status: implemented and verified in the current uncommitted worktree.

Plan type: narrow reactor correction with spec and implementation-doc revision.

## Goal

Correct Taut's already-specified owner-thread dynamic-topology behavior to use
SimpleBroker 5.3.0's public
`PollingStrategy.replace_activity_waiter(ActivityWaiter | None)` interface.
`BaseReactor` must call `PollingStrategy.start()` exactly once for initial
strategy setup. When the drive owner later changes `TautWatcher` membership,
the next owner wait builds a waiter for the complete committed queue set,
replaces the live optional waiter without restarting strategy lifecycle state,
and closes the returned displaced waiter exactly once.

Taut mirrors Weft at the SimpleBroker ownership seam, not by copying Weft's
foreign-thread mutation request state machine. Taut's public contract already
allows dynamic mutation only on the drive owner after drive begins. That
different workload removes the need for a request deque, manual-wait owner, or
cross-thread topology commit protocol.

## Governing sources and baseline

- `docs/specs/02-taut-core.md` [TAUT-8.4], [TAUT-8.5], [TAUT-11], [TAUT-12.1],
  [TAUT-12.5]
- `docs/implementation/04-taut-architecture.md`
- `docs/plans/2026-07-09-taut-reactor-safety-plan.md` task 9 and its accepted
  CORE-R8 resolution
- SimpleBroker 5.3.0 public strategy replacement interface
- Weft's completed owner/replacement example in
  `../weft/weft/core/tasks/multiqueue_watcher.py`, used as design evidence only

Repository baseline: `766e3aaf84f75046a57ef769b9c802148b42e71a` plus the current dirty worktree.
The dirty tree belongs to the owner and must be preserved.

Worktree blob baselines:

- `taut/watcher.py`: `fe6eaf57c8d16166cf860a96f07eeab013a56692`
- `tests/test_watcher.py`: `31300c3df1980091a265784d20b207a24f82e577`
- `extensions/taut_pg/tests/test_reactor.py`:
  `968190ce84b30589aa4c17a171b87daa8be6fe69`
- `extensions/taut_pg/pyproject.toml`:
  `9487141752f385273a50508a2f09455ad2bac642`
- `docs/specs/02-taut-core.md`:
  `1ecca05b9621a93aba6e9fb980f025cbbd717300`
- `docs/implementation/04-taut-architecture.md`:
  `7473c6b61c8621abf5a5085644458c5c7ae24385`

## Proven defect

`BaseReactor._ensure_polling_strategy_started()` currently calls
`_start_strategy()` whenever `_queue_generation` changes. The TautWatcher
override then calls `PollingStrategy.start(...)` again. This happens on the
correct owner thread, but it is still the wrong interface: `start()` is
strategy lifecycle initialization, not live waiter replacement. It resets
strategy data-version state and makes the strategy itself close the old waiter
inside a second startup.

The current unit test observes only waiter creation and close. It cannot tell a
live replacement from a strategy restart. The current PostgreSQL test observes
eventual delivery under a three-second wall-clock bound. It does not prove that
the `{notification, home, new-room}` native waiter returned `True`, nor that the
post-remove waiter excludes `new-room`.

## Invariants

- The drive owner remains the only thread that mutates live topology, creates a
  replacement waiter, calls the strategy replacement interface, or closes a
  displaced waiter.
- `PollingStrategy` remains the sole background wait and current-waiter owner.
- Initial startup still installs data-version provider and callback exactly
  once through `start()`.
- A generation change uses `replace_activity_waiter()` only. It must not call
  `start()` again or rebuild an unchanged generation.
- The one-waiter rule is per `PollingStrategy` / reactor instance, not
  process-global. One `TautWatcher` and one fixed Summon control reactor may
  each own their own optional native waiter; neither owns two current waiters.
- Candidate creation failure or `None` commits polling fallback without
  changing message/cursor delivery semantics. A later generation may restore
  native waiting.
- The replacement interface is exception-atomic. Until it returns, a distinct
  candidate is caller-owned. After it returns, Taut owns only the displaced
  waiter and closes it once.
- If replacement raises, restore the prior Taut waiter cache/generation
  metadata and close only a distinct unpublished candidate. Do not inspect or
  mutate SimpleBroker private fields.
- If a changed-signature factory returns the exact prior waiter object, treat
  the strategy replacement as the released same-object no-op. The object is
  pre-existing strategy-owned state: do not close it as a candidate or a
  displaced waiter. This supports a backend that internally updates/reuses its
  waiter without inventing a Taut identity restriction.
- Synchronous main-thread SIGINT cannot interrupt the ownership transfer after
  the strategy accepts a candidate but before Taut publishes cache/generation
  metadata and closes the displaced waiter. A narrow replacement-critical flag
  coalesces SIGINT, sets stop/wake state without taking `_topology_lock`, and
  defers `KeyboardInterrupt` until replacement success or rollback plus
  ownership-required close is complete.
- Removed membership Queue lifetime stays Taut-owned and separate from waiter
  lifetime: `_remove_thread_queue()` closes the removed Queue after topology
  removal on the drive owner.
- Cursor, poison-message, notification-inbox, membership timer, Summon fixed
  topology, and SimpleBroker retry behavior do not change.

## Spec-promotion slice

Before production code cites the new release interface:

1. Update [TAUT-3.4], [TAUT-8.3], and [TAUT-12.5] dependency floors from
   `simplebroker>=5.2.2` / `simplebroker-pg>=3.1.0` to the already-declared root
   floors `simplebroker>=5.3.0` / `simplebroker-pg>=3.2.0`. Preserve 5.2.0 as
   historical reference-reactor provenance where that is the subject.
2. In [TAUT-8.5], replace the ambiguous "startup/reconfiguration seam" claim
   with the exact public `PollingStrategy.replace_activity_waiter(...)`
   ownership contract. State that `start()` runs once and live generations do
   not reset callbacks or local activity state.
3. Update `docs/implementation/04-taut-architecture.md` with the same current
   dependency floor and the owner-only start-once/replace-later rationale.
4. Synchronize the paired release contract in
   `docs/specs/03-identity-addressing-notifications.md` [IAN-8.2],
   `docs/specs/04-summon.md`, and
   `docs/implementation/05-taut-summon-architecture.md`. Historical 5.2.0
   reference provenance remains; current minimum-runtime claims become 5.3.0.
5. Add this plan to the touched spec and implementation document Related Plans
   lists.

No new public Taut interface is introduced.

## Red-green implementation tasks

### 1. RED: distinguish replacement from restart

File: `tests/test_watcher.py`.

Strengthen `test_base_reactor_rebinds_waiter_after_topology_change` with an
injected real `PollingStrategy` subclass that counts `start()` and
`replace_activity_waiter()` calls. Drive through public
`wait_for_activity()`, `add_queue()`, and a second wait. The current code must
fail because it starts twice and never calls replacement. Assert:

- initial topology calls `start()` once;
- changed topology calls replacement once with the second candidate;
- `start()` remains at one;
- the displaced waiter closes once on the owner;
- unchanged later waits create/replace nothing.

Use protocol waiters only at the external backend-waiter seam. Do not mock the
reactor loop, Queue, or membership policy.

### 2. GREEN: add the private owner replacement path

File: `taut/watcher.py`.

- Split `_ensure_polling_strategy_started()` into first-start and
  generation-replacement branches.
- Keep `_start_strategy()` as initial lifecycle setup.
- Add one private replacement helper in `BaseReactor`; do not expose another
  public method or generic topology abstraction.
- Refactor the existing waiter factory logic into a pure private candidate
  builder that returns `(candidate, signature)` without mutating
  `_multi_activity_waiter` or its generation/signature. Initial startup may
  publish the builder result through `_ensure_multi_activity_waiter()`;
  generation replacement must not publish it before strategy acceptance.
- Snapshot prior cache metadata, build the candidate through that pure helper
  under outer rollback cleanup, then set the SIGINT-critical flag immediately
  before calling the released strategy replacement interface.
- On success, close the returned displaced waiter once outside SimpleBroker.
- On replacement failure, restore the prior cache metadata and close only a
  distinct candidate; re-raise the primary exception.
- If SIGINT or another `BaseException` lands after candidate creation but
  before the critical flag, outer cleanup closes the assigned distinct
  caller-owned candidate. Keep the critical flag set from immediately before
  replacement through cache/generation publication and displaced/candidate
  ownership cleanup.
- Update `_strategy_generation` only after successful start or replacement.
- Use a defensive one-shot close helper. Log ordinary close errors and never
  retry a partially completed close.
- A data-version callback may refresh membership while
  `_strategy.wait_for_activity()` is on-stack. After every strategy wait
  returns, call the generation check before any second strategy wait. Never
  replace from inside the callback. Add a firing strategy test whose callback
  changes topology and whose second wait fails unless replacement already ran.
- Add a narrow `_sigint_handler` override for the replacement commit window
  only. Outside that window, preserve inherited SimpleBroker behavior. During
  the window, record one pending interrupt, set stop/local/strategy wake state,
  and return without calling inherited `stop()` or raising. After cache
  publication or exception-atomic rollback and waiter cleanup, clear the
  critical flag and deliver `KeyboardInterrupt`; repeated signals coalesce.

Return the focused test to green before adding more cases.

### 3. RED→GREEN: fallback and unchanged-generation edges

File: `tests/test_watcher.py`.

Add one test at a time for:

- native waiter to `None` fallback closes the displaced native waiter and
  preserves strategy startup count;
- a later successful generation replaces `None` with native waiting;
- an unchanged generation does not call the factory or replacement again;
- replacement failure preserves the old installed/cache generation and closes
  the distinct unpublished candidate once.
- a main-thread SIGINT raised by a `PollingStrategy` test subclass immediately
  after `super().replace_activity_waiter(...)` does not interrupt the commit:
  metadata matches the installed waiter, displaced and final waiters each close
  once, and `KeyboardInterrupt` remains observable from synchronous `run()`.

Tests may inject the strategy and waiter factory because those are the two
external seams. Keep real Queue construction and public reactor drive methods.

### 4. Replace the PostgreSQL timing proxy with native-wake evidence

File: `extensions/taut_pg/tests/test_reactor.py`.

Wrap, but do not replace, the real
`create_activity_waiter_for_queues(...)` result. The proxy delegates real
`wait()` and `close()` while recording its queue-name set, each `True` wake,
and close count.

Drive one real `TautWatcher`:

1. Initial membership is `home` plus the member notification queue.
2. Add `new-room` through Taut membership and trigger the real owner refresh.
3. Write only to `new-room`; its handler must observe that the waiter whose set
   includes `new-room` returned `True` before handler entry.
4. Remove `new-room` and trigger owner refresh.
5. Wait for an explicit rebind barrier: the proxy for the complete remaining
   set is installed and the displaced add-generation proxy is closed.
6. Write only to `new-room`; during a short bounded quiet window, the current
   waiter must record no new `True` wake and no handler may run.
7. Write to `home`; the current waiter must return `True` and dispatch.
8. Stop/join in `finally`; every displaced/current proxy closes once and no
   drive thread exception is lost.

Do not fake Queue, PostgreSQL runner, LISTEN/NOTIFY, or elapsed latency as the
positive proof.

### 5. Dependency and documentation closure

Files:

- `extensions/taut_pg/pyproject.toml`
- `bin/verify-reactor-artifact-compat.py`
- `bin/verify-reactor-release-artifacts.py`
- `tests/test_reactor_artifact_compat.py`
- `docs/specs/02-taut-core.md`
- `docs/specs/03-identity-addressing-notifications.md`
- `docs/specs/04-summon.md`
- `docs/implementation/04-taut-architecture.md`
- `docs/implementation/05-taut-summon-architecture.md`
- `docs/plans/README.md`
- this plan

Keep the root's existing `simplebroker>=5.3.0` and
`simplebroker-pg>=3.2.0` declarations. Raise the taut-pg project floor to
`taut>=0.5.1` and `simplebroker-pg>=3.2.0`, so the extension cannot resolve an
older core lacking the fix. Updating the taut-pg distribution version is
release-owned and outside this implementation slice. Do not retain or regenerate
`extensions/taut_pg/uv.lock`: repository architecture says taut-pg has no
retained lock, and the current untracked file belongs to the owner.

Raise the executable artifact-verifier floors to SimpleBroker 5.3.0 and
simplebroker-pg 3.2.0 and update every enumerated test case/error string. This
is required release compatibility, not optional metadata cleanup.

## Verification

Run focused gates first, then expand:

```bash
uv run pytest tests/test_watcher.py -n 0 -q
uv run ./bin/pytest-pg extensions/taut_pg/tests/test_reactor.py
uv run pytest
uv run pytest -m shared
uv run ./bin/pytest-pg --fast
uv run ruff check taut tests extensions/taut_pg/taut_pg extensions/taut_pg/tests
uv run ruff format --check taut tests extensions/taut_pg/taut_pg extensions/taut_pg/tests
uv run --extra dev mypy taut tests extensions/taut_pg/taut_pg \
  extensions/taut_pg/tests --config-file pyproject.toml
uv build
uv build extensions/taut_pg
git diff --check
```

Also run the plan/spec/docs gates named by the repository if present. Record
current-tree results, not prior plan claims.

## Rollback and operational observation

Rollback is one code path and one dependency floor: revert the private
replacement helper and floor together. Do not keep a runtime version branch or
fallback to repeated `start()`. Post-release, successful behavior is one PG
listener per watcher, exact membership after churn, and no stale-waiter wake on
removed rooms. Repeated strategy startup, listener growth, or missing added-room
wakes are rollback signals.

## Out of scope

- Allowing foreign threads to add/remove TautWatcher queues.
- Copying Weft's mutation request deque or manual wait ownership state.
- Making Summon control topology dynamic.
- Mutating `PostgresMultiQueueActivityWaiter` membership in place.
- Backend-specific listener calls or registry inspection in Taut.
- Any SQLite WAL or connection-lifetime change.
- Batching/coalescing membership generations.

## Independent review

Before implementation, review this plan against [TAUT-8.4]/[TAUT-8.5], current
`taut/watcher.py`, the released SimpleBroker interface, and Weft's completed
example. After implementation, independently review waiter ownership,
start-once behavior, fallback, exception atomicity, the real PostgreSQL proof,
and dirty-tree scope. Record every finding and its disposition below.

## Review and execution record

- Pre-implementation review: READY after six corrections. The review required
  callback-time post-wait rebinding, paired artifact-floor owners, a real PG
  post-remove barrier, per-reactor one-waiter policy, same-object ownership,
  SIGINT deferral across replacement, and a pure unpublished-candidate builder.
  Zero architectural blockers remain.
- Post-implementation review, first pass: five findings. Initial-start failure
  could strand an unpublished waiter; replacement-critical SIGINT used a
  non-reentrant stop lock; a current-waiter close error could skip remaining
  resource cleanup; the PG positive proof lacked a pre-write wake baseline; and
  release verification checked the resolved plugin but not both declared
  taut-pg floors. Each received a firing test and a narrow fix at its existing
  ownership boundary. An additional firing test proves that a `BaseException`
  from unpublished-candidate close cannot cause a retry.
- Post-implementation review, second pass: CLEAR. The reviewer confirmed all
  five findings closed, exact one-shot candidate cleanup, and no new blocker.
- Current-tree verification on 2026-07-10:
  - focused watcher, artifact-floor, and docs-reference suites passed;
  - the full root pytest suite passed;
  - `./bin/pytest-pg --fast` passed 65 shared tests and 10 taut-pg tests against
    Dockerized PostgreSQL 18;
  - the focused real PostgreSQL reactor proof passed after its final wake-floor
    correction;
  - Ruff check/format, Mypy, `git diff --check`, core build, and taut-pg build
    passed;
  - the fresh paired installed-artifact verifier passed all four isolated wheel
    cases on its latest run. Two immediately prior retries reached the paired
    SQLite control smoke and reported the independently tracked intermittent
    unhandled traceback; no WAL workaround is part of this plan.
- The untracked `extensions/taut_pg/uv.lock` remained untouched as required.
  No commit was created on the owner's behalf.
