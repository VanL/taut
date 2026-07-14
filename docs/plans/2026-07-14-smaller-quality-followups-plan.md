# Smaller Quality Follow-ups Plan

Date: 2026-07-14

Status: implemented and verified. Independent plan, slice, documentation, and
final whole-slice reviews passed. The repository owner authorized inclusion in
0.6.4 on 2026-07-14; the ordinary exact-tree release gates remain the
publication boundary.

Plan type: implementation and conformance coverage with no intended spec
behavior change.

Owner: the implementing engineer owns the documentation corrections, the
real-backend tests, the bounded client state machine, the unread-list
measurement and optimization, traceability, and final independent review.

## 1. Goal

Close the useful smaller findings from the 2026-07-14 audit without turning
them into a broad rewrite. Add credential hygiene to the PostgreSQL examples,
backfill the thin 0.6.1 changelog entry, prove the watcher polling fallback on
real PostgreSQL, add one focused model-based client test, and remove avoidable
bounded queue reads when `taut list` examines a caught-up membership.

The PostgreSQL and Hypothesis work adds missing evidence for behavior that
already exists. The unread-list slice changes only the query selection for a
caught-up thread; returned `Thread` values and the bounded `999+` presentation
contract remain unchanged.

## 2. Requested Outcomes

- README PostgreSQL examples say plainly that their embedded password is a
  disposable local-test credential, that a real DSN is secret-bearing, and
  that downstream projects should ignore and permission-protect `.taut.toml`.
  Do not promise environment interpolation or a secret-manager integration
  that Taut does not implement.
- The 0.6.1 changelog entry records the actual release work: the Summon
  stop/release race correction, deterministic release-metadata preparation,
  and the dependency/floor updates. The text must be reconstructed from the
  committed diff and plans, not memory.
- One `pg_only` test forces the optional native activity waiter to be absent
  while retaining the real PostgreSQL backend, Queue objects, watcher loop,
  membership refresh, message delivery, cursor persistence, and shutdown.
- One bounded Hypothesis `RuleBasedStateMachine` exercises join, leave,
  membership rejoin, say, read, log, unread counts, and cursor rules through
  real public clients and isolated SQLite storage.
- `taut list` obtains the latest pending timestamp once per row and skips
  `peek_many(1000, ...)` when that timestamp proves the membership is caught
  up. Unread threads keep the existing bounded peek and exact saturation
  behavior.
- A manual, non-CI benchmark records the current and optimized SQLite list
  costs across thread width, unread depth, and one large-payload sensitivity
  case. Timing is evidence, not a flaky threshold.
- Specs, implementation notes, plan index, and verification evidence remain
  aligned. No release, tag, push, or commit is authorized.

## 3. Source Documents

Source specs:

- `docs/specs/02-taut-core.md` [TAUT-3.2], [TAUT-3.4], [TAUT-3.5], [TAUT-4.3], [TAUT-7.2],
  [TAUT-7.3], [TAUT-8.3], [TAUT-8.4], [TAUT-8.5], [TAUT-11], [TAUT-12.1]
- `docs/specs/01-development-documentation-operating-model.md` [DOM-4],
  [DOM-5], [DOM-6], [DOM-8], [DOM-10], [DOM-11]

Historical evidence:

- `docs/plans/2026-07-13-summon-stop-release-race-plan.md`
- `docs/plans/2026-07-13-release-metadata-preparation-plan.md`
- `CHANGELOG.md`, especially 0.6.1
- `git diff v0.6.0..v0.6.1` and its commits

Implementation and testing context:

- `taut/client/_threads.py`
- `taut/client/_messaging.py`
- `taut/watcher.py`
- `tests/test_client.py`
- `tests/test_shared_contract.py`
- `tests/test_envelope.py`
- `extensions/taut_pg/tests/test_reactor.py`
- sibling `../simplebroker/tests/test_property_queue_model.py` as the local
  state-machine style reference only
- `README.md` and `extensions/taut_pg/README.md`
- `docs/implementation/04-taut-architecture.md`

Required process guidance:

- `AGENTS.md`
- `docs/agent-context/README.md` and its required startup sequence
- `docs/agent-context/runbooks/writing-plans.md`
- `docs/agent-context/runbooks/testing-patterns.md`
- `docs/agent-context/runbooks/adversarial-acceptance-probes.md`
- `docs/agent-context/runbooks/review-loops-and-agent-bootstrap.md`
- `docs/agent-context/runbooks/maintaining-traceability.md`
- `docs/lessons.md`

## 4. Spec Baseline

- `88f1b9a1` is the committed source, spec, and test baseline.
- Plan authoring occurs on top of the existing uncommitted terminal-output
  safety slice and MultiQueueWatcher provenance comment. The pre-existing
  `docs/specs/02-taut-core.md` worktree diff is part of the effective baseline
  for this plan and must not be overwritten or reclassified.
- This plan does not revise intended behavior. It adds conformance evidence,
  user guidance, historical release notes, and an implementation optimization
  that preserves the [TAUT-7.3] result contract.
- Add only a related-plan backlink and implementation mapping during the
  traceability slice. If implementation reveals a behavior decision not
  already covered by the cited specs, stop and add an explicit proposed spec
  delta before coding that decision.

## 5. Current Evidence and Finding Disposition

### 5.1 Hypothesis coverage

The audit is correct that Hypothesis currently appears only in
`tests/test_envelope.py`, with two properties. That observation does not by
itself justify copying SimpleBroker's full queue model. Taut's highest-value
stateful seam is the client membership/read-cursor protocol, where operation
order matters and a small reference model can catch regressions that isolated
examples miss.

The initial model stays `sqlite_only`. Its rules are backend-neutral, but the
current PostgreSQL fixture does not provide cheap, isolated storage for every
generated example. Marking it `shared` now would either accumulate state across
examples or repeatedly recreate the PostgreSQL schema, harming shrinking and
the release lane. Existing deterministic shared tests cover the same primitive
operations on PostgreSQL. Promotion to a shared state-machine harness requires
a separate measured isolation design.

### 5.2 PostgreSQL polling coverage

The audit's broad claim that watcher, identity, and CLI suites are SQLite-only
is stale. `tests/test_shared_contract.py` already runs identity, CLI, list, and
ordinary watcher contracts through `bin/pytest-pg`; the PG extension also has
a real LISTEN/NOTIFY topology-rebind test.

The narrower gap is valid: there is no real-PostgreSQL firing test that removes
the optional native waiter and proves the portable polling path still refreshes
memberships, delivers a later write, persists the cursor, and stops. The test
belongs in the PG reactor suite because it intentionally manipulates a
PostgreSQL capability seam.

### 5.3 Credential example hygiene

Both public README paths show an inline `postgres:postgres` DSN without saying
that it is disposable test data or that real `.taut.toml` files can contain
secrets. The repository's own `.gitignore` already ignores `.taut.toml`, but
downstream repositories do not inherit that rule. The fix is explicit local
credential and file-hygiene guidance. Do not suggest `${ENV}` syntax because
Taut does not currently interpolate it.

### 5.4 Changelog 0.6.1

The audit is correct that the entry is materially thinner than adjacent
releases. `v0.6.0..v0.6.1` includes the Summon stop/release race correction,
release metadata preparation, and dependency/floor/lock reconciliation. The
backfill must stay concise and historical. It must not claim behavior that the
tagged diff or dated plans do not support.

### 5.5 Unread-list cost

`ThreadsMixin._thread_from_row()` currently calls `_unread_count()` before
`_last_message_ts()`. Every membership therefore materializes up to 1000
post-cursor rows even when a public latest-timestamp query can prove there are
none. This makes the common all-read list path do avoidable work.

There is no public SimpleBroker cursor-relative count API. `Queue.stats()` is
whole-queue state and cannot answer this query. Private SQL, backend branches,
or a Taut count cache would violate the current ownership boundary. The
smallest sound change is a caught-up fast path that retains the existing
bounded peek for unread queues.

PostgreSQL `Queue.get_data_version()` returns `None`; the fallback test must not
claim a data-version wake. The portable reactor proof is repeated bounded
waiting followed by the authoritative cursor-aware pending check, with
membership convergence supplied by the refresh interval.

## 6. Context and Key Files

Files to modify:

- `README.md`
- `extensions/taut_pg/README.md`
- `CHANGELOG.md`
- `extensions/taut_pg/tests/test_reactor.py`
- `tests/test_client_stateful.py` (new)
- `tests/test_client.py` or a narrowly named new non-slow test module for the
  unread algorithm and boundary characterizations
- `tests/test_unread_performance.py` (new, manual `slow` benchmark)
- `taut/client/_threads.py`
- `docs/implementation/04-taut-architecture.md`
- `docs/specs/02-taut-core.md` related-plan backlink only
- `docs/plans/README.md`
- this plan

Current owners and load-bearing behavior:

- `ThreadsMixin._thread_from_row()` opens the Queue, derives unread state and
  the latest timestamp, and constructs the public `Thread` model.
- `ThreadsMixin._unread_count()` returns zero without membership; otherwise it
  calls public `Queue.peek_many()` with a cap of 1000 and the membership cursor.
  The renderer maps a returned value of 1000 to `999+`.
- `TautWatcher` delegates waiting policy to `BaseReactor`. A backend may return
  a native activity waiter; `None` selects the portable polling strategy.
  Cursor advancement happens only after handler success.
- `tests/test_shared_contract.py` already proves ordinary watcher delivery on
  both backends. `extensions/taut_pg/tests/test_reactor.py` owns PG-specific
  native-waiter behavior and is the right place for the forced fallback.
- Root pytest requires every test module to carry exactly the relevant
  `shared`, `sqlite_only`, or `pg_only` marker. `slow` is additive and excluded
  from the default lane.

Comprehension gate before editing:

1. Why can latest timestamp prove a membership has no unread rows, while a
   positive comparison still requires the bounded peek for the presentation
   count?
2. Why may two fields from one non-transactional `list_threads()` call reflect
   nearby points in time, and why must the optimization not claim a snapshot?
3. Why does returning `None` from the activity-waiter factory prove the
   supported fallback more directly than raising an unrelated constructor
   exception?
4. Which state-machine actions append notices, which actions move cursors, and
   why does a sender with older unread messages not skip them when posting?
5. Which 0.6.1 claims are directly supported by the tagged diff and plans?

If any answer is uncertain, stop and re-read the cited source and tests before
writing a test.

## 7. Invariants and Constraints

- No public API, CLI shape, storage schema, message encoding, identity rule, or
  thread-list result changes.
- `Thread.last_ts` and unread fields remain derived from public Queue APIs. No
  private SimpleBroker SQL, internal backend import, cache, or new dependency.
- Unread counts remain exact from 0 through 999. A backlog of 1000 or more
  returns 1000 to the Python model and renders as `999+`.
- A missing membership always reports zero unread. An empty queue always
  reports zero unread.
- The fast path must obtain `last_ts` once and reuse that captured value in the
  returned `Thread`; do not add a second latest-timestamp probe.
- Listing remains a non-transactional observation. A concurrent write may
  appear on the next call. The operation must never advance a membership
  cursor, and the next call must converge to the new unread state.
- The PG fallback test patches only
  `taut.watcher.create_activity_waiter_for_queues` to return `None`. Queue,
  PostgreSQL, polling, membership refresh, pending checks, cursor writes, and
  the watcher thread stay real.
- The fallback test writes from a second client only after the watcher reports
  the newly joined queue. This prevents pre-existing queued data from masking
  whether polling detected a post-refresh write.
- Watcher startup uses `notify_ready_after_initial_drain`; thread liveness alone
  is not readiness. Shutdown always calls `stop()`, joins with a bound, closes
  both clients, and asserts the thread exited.
- The state machine uses public Taut operations and real SQLite. It does not
  mock the client, state store, Queue, timestamps, or cursor updates.
- Generated examples are bounded: one channel, two actors, small ASCII text,
  12 examples, 12 steps, and no concurrency. The initial 25-by-16 target took
  about 49 seconds even with persistent clients; deterministic examples retain
  the critical branch guarantees while the smaller machine keeps useful
  sequence composition in the normal test budget. The model must close both
  clients before its temporary directory is removed.
- Documentation must not imply that `.gitignore` or POSIX file modes are an
  authentication boundary. They are secret-hygiene controls. Avoid a
  platform-unqualified `chmod` instruction; label it POSIX where used.
- The changelog backfill describes already released behavior only. It does not
  alter version numbers or release artifacts.
- Wall-clock benchmark numbers do not gate CI. The deterministic call-through
  test, semantic boundary tests, and backend conformance tests are the gates.
- No drive-by refactor of `BaseReactor`, `MultiQueueWatcher`, identity, or
  SimpleBroker is in scope.

### 7.1 Hidden coupling and anti-mocking guidance

The unread optimization relies on `latest_pending_timestamp()` and
`peek_many(after_timestamp=...)` using the same monotonically ordered queue
timestamps. The semantic tests therefore use real Queue writes or inserts and
assert public list results first. A call-through counter around
`Queue.peek_many` is allowed only as secondary evidence that caught-up rows do
not select the expensive operation.

The watcher fallback relies on the reactor's authoritative post-wait pending
check. Mocking `_has_pending_messages`, `PollingStrategy`, or cursor state would
allow the test to pass without proving the portable path. Do not do so.

The Hypothesis model owns only expected domain state. It may not call private
state helpers to decide what should happen. Public timestamps returned by
operations can be recorded as identifiers, but production state cannot become
the oracle for membership or cursor rules.

## 8. Detailed Test and Implementation Design

### 8.1 Credential and changelog documentation

Add prose next to both PostgreSQL snippets:

- the shown credentials are disposable local-test credentials;
- a real DSN may contain a password and should be treated as a secret;
- add `.taut.toml` to the downstream repository's `.gitignore` when it contains
  a secret and restrict the file to the owner on POSIX systems, for example
  `chmod 600 .taut.toml`;
- do not commit production credentials.

Do not add an environment-placeholder example until Taut has and tests that
feature.

Replace the one-line 0.6.1 entry with three to five factual bullets derived
from `v0.6.0..v0.6.1`. At minimum cover the Summon stop/restart race fix,
deterministic release-metadata ownership/preparation, and dependency floors or
retained lock reconciliation. Preserve the existing release date and heading.

Verification substitute for docs-only edits: inspect both rendered README
contexts, compare each changelog claim to the tagged diff/dated plan, run docs
reference tests, and run `git diff --check`.

### 8.2 Real PostgreSQL polling fallback

Add
`test_taut_watcher_polls_and_refreshes_membership_without_native_waiter` to
`extensions/taut_pg/tests/test_reactor.py`:

1. Use `taut_pg_project`, change into it, initialize Taut, and create real
   `van` and `bob` clients.
2. Join both to `home`; drain Van's initial history.
3. Patch only the activity-waiter factory. Set an observation event and return
   `None`.
4. Create a real `TautWatcher` with a 0.05 second membership refresh interval,
   attach a ready event through `notify_ready_after_initial_drain`, and start.
5. Wait for readiness and factory observation. The forced `None` return is the
   supporting evidence that this instance has no native waiter; do not inspect
   private strategy state.
6. Join both clients to `new-room`; wait until the watcher queue inventory
   includes it.
7. Write `polled delivery` from Bob after that barrier and wait for the handler
   to record its thread, text, and exact timestamp.
8. Through `van.list_threads(all_threads=True)`, wait until `new-room` is not
   unread; then prove `van.read("new-room")` raises `EmptyResultError`. This is
   durable cursor evidence, not just handler-memory evidence.
9. Stop, join, close, and assert the watcher thread is dead.

Capture drive-thread exceptions with the existing `threading.excepthook`
pattern in this test file. Assert the error list stays empty so an early crash
is reported directly rather than surfacing only as a later timeout.

This is test-only conformance work expected to pass on the current production
code. Red-green is not fabricated. The firing failures are loss of timed
membership refresh, loss of fallback/authoritative pending delivery broadly,
loss of cursor advance, or broken bounded shutdown. Dedicated reactor tests,
not this integration case, own the exact pre-wait/post-wait timing and stop-wake
mechanisms.

### 8.3 Bounded client state machine

Add `tests/test_client_stateful.py`, marked `sqlite_only`, using
`RuleBasedStateMachine` and a fresh temporary `.taut.db` per machine instance.
Use two named clients, Alice and Bob, and one channel, `general`. Deterministic
initialization creates Alice and joins her to `general`; Bob starts unknown.
This removes the ambiguous no-thread initial state from generated operations.

Reference model:

- append-only records `(ts, from_name, kind, text)`;
- whether each identity has ever been created;
- current membership for each actor;
- cursor index for each current member.

Rules and guards:

- `bob_join`: enabled only while Bob is absent. His first join creates the
  identity; a later join is membership rejoin. Join appends the expected join
  notice and sets Bob's new cursor to the tail, so rejoin does not expose old
  history.
- `bob_leave`: enabled only while Bob is a member. Leave removes Bob's
  membership and cursor before appending the leave notice for Alice.
- `post(actor, text)`: joined actors call `say`. If the sender was caught up
  before the write, advance its model cursor to the new tail. If older unread
  rows existed, keep the cursor so the post does not skip them. When Bob is
  unknown, `say` expects `NotFoundError`; when he is known but left, it expects
  `MembershipError`. Alice remains a member for the generated run.
- `read(actor)`: joined actors with pending model rows receive exactly those
  rows and advance to the tail. Caught-up actors get `EmptyResultError`.
  Unknown Bob expects `NotFoundError`; known-left Bob expects
  `MembershipError`.
- `inspect_log`: Alice compares complete append-only history and the later
  invariant proves that logging did not move her cursor. Do not call Bob's log
  path while he is unknown or absent; its exception cases add no cursor-model
  coverage beyond the explicit `say` and `read` rejection rules.

After every step, public invariants verify joined thread names, list unread
count and boolean, last timestamp, full history ordering, and strictly
increasing timestamps. Alice's `joined_thread_names()` is always
`("general",)`; Bob's is `("general",)` while joined, raises `NotFoundError`
while unknown, and is empty while known-left. `list_threads(all_threads=True)`
is valid for all three Bob states and reports zero unread for a non-member.
Keep payloads small and printable so this model stays focused on
membership/cursor semantics.

Do not assert in teardown that every generated example hit rejoin or the
sender-with-older-unread branch. Such an assertion fights valid shorter
examples and shrinking. Retain
`tests/test_client.py::test_say_does_not_advance_cursor_when_sender_has_unread`
as the deterministic firing gate for the sender branch. Add one deterministic
join, leave, intervening-history, rejoin case beside the state machine if no
existing test proves that old history stays behind the new join cursor. The
state machine adds sequence-composition coverage; it does not replace those
branch-specific examples.

This is additional coverage for established behavior, so it may begin green.
Its value is generated operation ordering and shrinkable counterexamples, not
an artificial production change.

### 8.4 Unread fast path and semantic boundaries

Write the deterministic red test before production code:

- Alice joins three queues: two caught up and one intended to be unread. Bob
  joins the unread queue, Alice drains Bob's join notice, and Bob posts one
  message. Using a second writer is load-bearing because a self-write by Alice
  could advance her cursor and invalidate the proof.
- After setup, wrap `Queue.peek_many` with a typed call-through counter.
- Assert public thread counts are `0`, `1`, `0`, and the bounded peek is called
  only for the unread queue. Record queue name and `after_timestamp`, not only a
  total call count.
- Current code should return correct values but call `peek_many` for all three,
  making the algorithm-selection assertion red.

Add real-state boundary characterizations:

- 999 unread valid envelopes produce `Thread.unread_count == 999`;
- after crossing 1000, the returned value saturates at 1000 and the renderer
  reports `999+`;
- a guarded call-through wrapper around Alice's queue
  `latest_pending_timestamp()` has Bob write immediately after the prior latest
  value is captured. The first result may reflect that prior view, but the
  second list must see Bob's exact timestamp and Alice's stored membership
  cursor must remain unchanged throughout. Do not use Alice as the writer.

Then change `taut/client/_threads.py`:

1. In `_thread_from_row`, call `_last_message_ts(queue)` once before unread
   counting.
2. Pass that value to `_unread_count` as required `latest_pending_ts` data.
3. Return zero without `peek_many` when membership is absent, latest is `None`,
   or latest is less than or equal to `membership["last_seen_ts"]`.
4. Otherwise retain the current `peek_many(cap, with_timestamps=True,
   after_timestamp=...)` and `len(rows)` behavior.
5. Reuse the captured timestamp as `Thread.last_ts`.

Run the red test before and after the change and record both observations.

### 8.5 Manual unread benchmark

Add `tests/test_unread_performance.py`, marked both `sqlite_only` and `slow`.
It is a manual measurement probe, excluded by the default pytest marker. Keep
it under tests rather than creating a new benchmark CLI contract.

Use a fresh real SQLite database for each scenario. Bulk-seed valid envelopes
outside the timed region with public `Queue.insert_messages`; do not loop over
individual public writes. Close all Queue and client resources before removing
each temporary directory. Use roughly 256-byte envelopes, three warmups,
eleven timed samples, and report median plus interquartile range. Time only
`list_threads(all_threads=True)`. Measure widths 1, 10, and 50 across unread
depths 0, 1, 100, and 1000. Add one single-queue 1000-row, 16 KiB payload
sensitivity case because the row cap does not cap transferred bytes. Report
total benchmark runtime as well as per-scenario statistics. Run serially:

```text
uv run --extra dev pytest tests/test_unread_performance.py -m slow -n 0 -s
```

Record before and after results in this plan. Do not assert a time ratio or
absolute threshold. The benchmark answers whether the caught-up fast path is
material and exposes the remaining unread-body cost. Only if realistic
unread-heavy cases remain material should a later SimpleBroker plan propose a
public capped `count_pending(after_timestamp=..., limit=...)` contract across
all supported backends and a Taut dependency-floor change.

## 9. Task Breakdown

1. Independent plan review.
   - Reviewer reads this plan, cited spec sections, `_threads.py`, the watcher
     strategy path, PG reactor tests, and sibling state-machine example.
   - Reviewer challenges the algorithm proof, concurrency claim, real-PG seam,
     model oracle, test cost, and documentation promises.
   - Stop until every finding is accepted or rejected with evidence and the
     reviewer says the plan can be implemented confidently.

2. Documentation corrections.
   - Edit both README credential examples and the 0.6.1 changelog entry.
   - Inspect historical evidence and rendered context; run docs references and
     `git diff --check`.

3. PostgreSQL fallback conformance slice.
   - Add the real PG test exactly at the optional waiter seam.
   - Run the one test serially, then the complete PG reactor file.
   - Independent slice review must confirm that only the capability factory is
     patched and the post-barrier write/cursor proof is real.

4. Stateful client-model slice.
   - Add the bounded SQLite machine and public invariants.
   - Run with Hypothesis statistics and save any failing replay blob in the
     test output, not in a hardcoded example unless it is a useful permanent
     regression.
   - Time the focused test. Reduce examples only if it exceeds the normal test
     budget while preserving sequence diversity.

5. Unread red test, benchmark baseline, and fast path.
   - Add and run the deterministic call-through test; record the expected red.
   - Add boundary/concurrency characterizations and run them green before the
     optimization.
   - Run the manual benchmark and record the baseline.
   - Implement the timestamp-based skip, run focused tests green, then rerun
     the benchmark and record results.
   - Stop if the optimization needs private SQL, a cache, a backend branch, or
     a new broker API.

6. Traceability and broader verification.
   - Update the architecture mapping and related-plan backlink without
     rewriting the current terminal-output safety worktree edits.
   - Run focused root and PG tests, docs tests, Ruff, mypy, the default root
     suite, and the fast PG lane.
   - Reconcile the plan execution evidence and deviation log.

7. Independent completed-work review.
   - Reviewer receives the spec, plan, full diff, red/green observations,
     benchmark output, and verification commands.
   - Reproduce every actionable finding before editing. Record dispositions
     and rerun affected gates.
   - Leave the work uncommitted for owner review. Report every changed file and
     residual risk; do not call the slice ready to land because the Definition
     of Done commit gate is intentionally unsatisfied.

## 10. Verification Gates

Focused root behavior:

```text
uv run --extra dev pytest -q tests/test_client.py tests/test_client_stateful.py -n 0
uv run --extra dev pytest tests/test_unread_performance.py -m slow -n 0 -s
```

Focused PostgreSQL behavior:

```text
uv run ./bin/pytest-pg extensions/taut_pg/tests/test_reactor.py::test_taut_watcher_polls_and_refreshes_membership_without_native_waiter -n 0
uv run ./bin/pytest-pg extensions/taut_pg/tests/test_reactor.py -n 0
```

Static and documentation gates:

```text
uv run --extra dev pytest -q tests/test_docs_references.py
uv run --extra dev ruff check taut/client/_threads.py tests/test_client.py tests/test_client_stateful.py tests/test_unread_performance.py extensions/taut_pg/tests/test_reactor.py
uv run --extra dev ruff format --check taut/client/_threads.py tests/test_client.py tests/test_client_stateful.py tests/test_unread_performance.py extensions/taut_pg/tests/test_reactor.py
uv run --extra dev mypy taut/client/_threads.py tests/test_client.py tests/test_client_stateful.py tests/test_unread_performance.py --config-file pyproject.toml
uv run --extra dev mypy taut/_scripts.py extensions/taut_pg/taut_pg extensions/taut_pg/tests extensions/taut_pg/tests/conftest.py --config-file pyproject.toml
git diff --check
```

Broader regression:

```text
uv run --extra dev pytest -q
uv run ./bin/pytest-pg --fast
```

Apply the repository's adversarial acceptance probes to the changed test
helpers and benchmark input setup. There is no new parser or CLI in this plan,
so parser-specific floors do not apply.

## 11. Rollout, Rollback, and Success Signals

There is no schema, stored-data, or one-way migration. The documentation and
test slices are independently revertible. Reverting the `_threads.py` fast
path restores the prior algorithm without changing persisted state or public
results. The new boundary tests should continue to pass after such a revert;
only the deterministic call-count expectation would need to revert with it.

Post-change success is:

- default root and PostgreSQL lanes stay green;
- the forced PG fallback delivers and persists a post-refresh write;
- the state machine completes within the normal test budget and yields
  replayable shrinks if it finds a fault;
- caught-up rows make no bounded peek, while unread caps remain exact;
- the manual benchmark shows the expected caught-up reduction without a
  regression large enough to question the extra latest-timestamp ordering;
- README guidance makes the limits of credential hygiene explicit.

No deployment monitor is needed for a local library optimization. A later
SimpleBroker count API is explicitly not implied by completion of this plan.

## 12. Out of Scope

- A full SimpleBroker-grade Taut model suite, concurrency model, or shared
  PostgreSQL Hypothesis harness.
- A new SimpleBroker counting API, Taut-side SQL, cache, or dependency-floor
  bump.
- Refactoring BaseReactor, PollingStrategy, or MultiQueueWatcher.
- Changing watcher refresh intervals or native LISTEN/NOTIFY behavior.
- Environment-variable interpolation, credential providers, encryption, or a
  secrets subsystem for `.taut.toml`.
- Editing the 0.6.1 tag, release artifacts, or published release notes.
- A CI wall-clock performance threshold.
- Coverage percentage gates, branch coverage, or the separate coverage-policy
  finding.

## 13. Deviation Log

| Spec ref | Planned behavior | Actual behavior | Rationale | Spec proposal |
|----------|------------------|-----------------|-----------|---------------|

## 14. Review Findings and Dispositions

| Finding | Disposition |
|---------|-------------|
| P1: unread red and race cases did not require a second writer, so a self-write could advance the listing client's cursor and invalidate the intended proof | Accepted. Both designs now require Bob to write, install instrumentation after setup, and assert queue/cursor-specific evidence. |
| P2: the state machine left the pre-thread and unknown/left exception policy ambiguous and could imply that random runs must hit every critical branch | Accepted. Alice now deterministically creates and stays in the thread; Bob has guarded join/leave rules and explicit unknown/left outcomes. Deterministic tests remain the firing gates for rejoin history and sender-with-unread behavior. |
| P2: benchmark seeding, isolation, large-payload width, and cleanup were underspecified | Accepted. Each scenario now uses a fresh DB, bulk inserts outside timing, one queue for the 16 KiB case, explicit cleanup, and total-runtime reporting. |
| P2: the fast path depends on [TAUT-3.4]/[TAUT-3.5], while the cited IAN refs did not govern this work | Accepted. Added the timestamp/API ownership refs and removed the unused identity refs. |
| P2: “non-native strategy state” named an unnecessary private assertion and watcher-thread crashes could appear only as timeouts | Accepted. Factory observation is supporting evidence; public delivery/cursor/shutdown are primary. The test now captures and asserts drive-thread exceptions. |
| Credential and changelog scope | Reviewer confirmed the credential advice is appropriately limited and the planned 0.6.1 claims are supported by the tagged diff and dated plans. |
| Plan rereview | Passed with no remaining blocker. Reviewer confirmed the plan is zero-context implementable; queue-name mappings, not result order, should key unread assertions. |
| PG slice P2: the plan overclaimed that this integration test isolates the post-wait pending check and a distinct polling stop wake | Accepted. Narrowed the firing claims to fallback delivery, membership refresh, cursor persistence, and bounded shutdown. Existing focused reactor tests own internal wait timing. The code slice was approved without findings. |
| Documentation slice P2: the first 0.6.1 bullet assigned the root STOP race fix to outcome separation instead of leaving the caught adapter-error scope before teardown | Accepted. The changelog now names the STOP-interrupted PTY orientation write misclassification as the race and outcome separation as the accompanying exact reporting. The dependency bullet now names each floor precisely. README credential guidance was approved. |
| Stateful slice P2: the implementation reduced the measured 25-by-16 state-machine budget to 12-by-12, but the plan invariant still named the original target | Accepted. Recorded the roughly 49-second initial run, the 12-by-12 budget, and deterministic branch-specific gates. Independent code review approved the model and cleanup. |
| Unread slice review | Approved. Reviewer ran a negative control with the prior algorithm and observed the deterministic call-selection failure, then approved the public-API fast path, race and saturation cases, benchmark isolation, cleanup, typing, and cost. |
| Documentation closure review | Approved. Reviewer confirmed corrected 0.6.1 causality, credential limits, non-snapshot unread wording, broad fallback claims, spec mappings, backlinks, and lessons. |
| Final completed-work review | No blocking findings. Reviewer approved the complete slice for owner review while explicitly uncommitted and confirmed it is not ready to land under the commit gate. Residuals are the SQLite-only state machine and its runtime, unread-body materialization, and Docker PG18 rather than a managed service. |

## 15. Execution Evidence

| Slice | Command or inspection | Observed result | Residual risk |
|-------|-----------------------|-----------------|---------------|
| Baseline inventory | `rg` over Hypothesis use, README DSNs, shared/PG watcher tests, and unread helpers | Two existing Hypothesis properties; both README paths embed local PG credentials; shared tests already cover PG identity/CLI/watcher primitives; no forced real-PG polling fallback; every joined row currently calls bounded `peek_many` | Inventory is source inspection until firing tests and benchmark run |
| Plan docs gate | `uv run --extra dev pytest -q tests/test_docs_references.py -n 0 && git diff --check` | `10 passed`; diff whitespace check passed | None observed |
| Independent plan rereview | Read-only review of clarified plan against specs, source, and tests | No remaining blocker; reviewer approved implementation | Completed-work review remains required |
| README and changelog inspection | `git diff v0.6.0..v0.6.1`, both dated 0.6.1 plans, rendered diff, docs reference test | README credential text approved; reviewer corrected the causal STOP-race wording and confirmed the remaining historical claims | Corrected changelog wording awaits final whole-diff review |
| Real PG polling fallback | Focused new node, full PG reactor file, PG mypy lane, Ruff, and diff check | `1 passed in 1.41s`; reactor file `2 passed in 3.62s`; static gates passed; independent slice review approved the code | Test proves fallback behavior broadly, not a particular pre/post-wait internal timing |
| Stateful client model | 25-by-16 timing probe, then `uv run --extra dev pytest tests/test_client_stateful.py -n 0 --hypothesis-show-statistics` at 12-by-12; Ruff and mypy | Initial persistent-client machine took 48.96s; final file `2 passed in 22.44s` during implementation and about 13s on independent review; static gates passed; code review approved | SQLite-only by design; deterministic shared tests retain PostgreSQL primitive coverage |
| Unread red/green behavior | Focused call-selection, 999/1000, and race nodes before/after `_threads.py` change; full `tests/test_client.py`; independent negative control | Prior algorithm returned correct counts but peeked all three queues, failing the queue-specific assertion; optimized code passed all three nodes and the full client file; reviewer reproduced the intended negative-control failure | Listing remains a non-transactional observation and may expose the prior view once |
| Unread benchmark | Manual `slow` benchmark before and after, serial, with no timing threshold | Total runtime fell from 10.263s to 9.394s; caught-up medians for 1/10/50 threads changed 8.534→7.476, 24.600→15.515, and 98.809→55.268 ms; unread-heavy cases stayed within roughly six percent; independent rerun passed in 9.07s | Unread rows still materialize message bodies; row cap does not cap transferred bytes |
| Focused combined root gate | `uv run --extra dev pytest -q tests/test_client.py tests/test_client_stateful.py -n 0` | Completed at 100% with exit code 0 | Manual slow benchmark remains separately selected by design |
| Focused static gate | Ruff check/format over five touched code/test files; root mypy over `_threads.py` and three root test files; PG mypy lane | All passed; root mypy reported no issues in four files and PG mypy no issues in six files | Static checks cover the changed code paths; existing terminal-output slice had already passed its broader static lanes |
| Full root regression | `uv run --extra dev pytest -q` | Completed at 100% with exit code 0 | Default marker excludes the manual slow benchmark and environment-specific live-provider lanes |
| Fast PostgreSQL regression | `uv run ./bin/pytest-pg --fast` | Shared lane `190 passed in 15.47s`; PG-only lane `14 passed in 25.83s`; exit code 0 | Dockerized PostgreSQL 18; no external managed database tested |
| Final docs/diff gate | `uv run --extra dev pytest -q tests/test_docs_references.py -n 0 && git diff --check` | `10 passed`; diff whitespace check passed | None observed |
| Final whole-slice review | Independent read-only review of the complete plan-scoped diff plus focused test and benchmark reproduction | No P0/P1/P2 findings; acceptable for owner review while uncommitted | Commit gate intentionally unsatisfied; no ready-to-land claim |

### 15.1 Unread benchmark results

Times are milliseconds. Brackets contain inclusive Q1 and Q3 from eleven
timed samples after three warmups.

| Threads | Unread depth | Payload bytes | Before median [Q1, Q3] | After median [Q1, Q3] |
|---------|--------------|---------------|-------------------------|------------------------|
| 1 | 0 | 256 | 8.534 [7.863, 8.606] | 7.476 [6.943, 8.027] |
| 1 | 1 | 256 | 5.709 [5.459, 5.885] | 5.562 [5.407, 5.896] |
| 1 | 100 | 256 | 5.864 [5.593, 6.332] | 5.862 [5.543, 6.144] |
| 1 | 1000 | 256 | 6.477 [6.032, 6.595] | 6.037 [5.894, 6.184] |
| 10 | 0 | 256 | 24.600 [24.215, 25.118] | 15.515 [15.271, 15.695] |
| 10 | 1 | 256 | 17.685 [17.449, 18.175] | 17.320 [16.809, 18.285] |
| 10 | 100 | 256 | 17.820 [17.712, 18.454] | 18.384 [18.025, 18.843] |
| 10 | 1000 | 256 | 22.424 [22.170, 22.767] | 23.793 [22.743, 24.418] |
| 50 | 0 | 256 | 98.809 [98.182, 100.108] | 55.268 [51.927, 58.958] |
| 50 | 1 | 256 | 72.092 [71.161, 73.342] | 68.523 [66.773, 71.142] |
| 50 | 100 | 256 | 75.926 [74.346, 76.576] | 71.193 [69.859, 71.496] |
| 50 | 1000 | 256 | 96.083 [95.489, 97.584] | 94.217 [93.479, 98.237] |
| 1 | 1000 | 16384 | 29.594 [28.761, 31.918] | 27.700 [26.885, 29.387] |

Total measured runtime was 10.263 seconds before and 9.394 seconds after.

## 16. Fresh-Eyes Checklist

- [x] Independent reviewer says the plan is implementable without guessing.
- [x] Current owners, test seams, and backend markers are explicit.
- [x] Existing PG coverage is distinguished from the narrower valid gap.
- [x] Every behavior change has a red test or an explicit test-only/docs-only
  exception.
- [x] Real storage remains the primary proof; instrumentation is secondary.
- [x] Concurrency non-snapshot behavior and cursor invariants are explicit.
- [x] Rollback has no schema or persistence coupling.
- [x] No unsupported credential feature or new broker API is promised.
