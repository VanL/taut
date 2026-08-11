# Eventual-Evidence Test Helper and Adoption Plan

Date: 2026-08-11

Class: 5+P. The implementation is test-only, but it adds a normative
verification rule under [DOM-10] and changes the standing repository testing
process, which triggers [DOM-6] and the `+P` modifier under [DOM-15]. The same
deadline contract must work in synchronous and asyncio contexts, and adoption
crosses thread, subprocess, broker, and PostgreSQL-backed tests, so the
hardening runbook is mandatory. Product behavior and public runtime contracts
must not change.

Plan type: implementation with spec revision.

Hardening: required.

Status: completed; implementation, runtime gates, final review, and owner-authorized close-out passed.

## Goal

Add one repository-only helper for the common test operation “observe a
side-effect-free predicate until positive evidence appears or one aggregate
deadline expires.” Provide synchronous and asyncio wrappers with the same
deadline, final-recheck, failure, and diagnostic contract. Then audit the eight
near-identical polling loops already copied across core, PostgreSQL, Summon,
and MCP tests, replacing the eligible copies while retaining domain-specific
coordination loops whose semantics are not generic polling. Seven generic
copies are adopted. Summon's shared adapter remains specialized because its
public predicate surface mixes observation with control request/reply and
identity-touching operations.

This plan deliberately does not port Weft's full `drive_until` interface.
Taut's duplicated loops observe work owned by background threads or reactors;
they do not share a safe `step`, worker-result drain, or progress-ledger seam.
The canonical names are therefore `eventually` and `async_eventually`, not
`drive_until`.

## Requested Outcomes

- One tested implementation owns monotonic aggregate deadlines, wait capping,
  the exact-deadline final predicate check, and timeout diagnostics.
- Sync and asyncio callers have thin context-specific wrappers over one private
  deadline/diagnostic core. The asyncio wrapper yields without blocking its
  event loop and propagates cancellation.
- Existing suite-specific timeout budgets and polling intervals remain
  explicit. Adoption must not silently lengthen or shorten a test's budget.
- Timeout failures identify the awaited evidence and can include a
  best-effort live snapshot without letting snapshot failure mask the timeout.
- Core, PostgreSQL, and MCP tests consume the same repository-only helper
  without shipping it in any product wheel. Summon's mixed-domain suite
  adapter remains specialized after transitive-caller audit.
- Consumptive reads, reactor-driving loops, condition/event/barrier ownership,
  PTY or pipe reads, and subprocess watchdogs remain with their domain
  harnesses.
- Time is used only as a liveness bound. A negative safety claim waits for a
  causal or terminal fence and then inspects retained history or state; the
  helper is never presented as proof that an event cannot occur.
- No static policy gate bans local polling loops in this change. Semantic loop
  classification is not mechanically reliable. Recurrence after adoption is
  evidence for a separate reviewed enforcement proposal.

## Source Documents

Governing process and testing rules:

- `docs/specs/01-development-documentation-operating-model.md` [DOM-5],
  [DOM-6], [DOM-10], [DOM-11], and [DOM-15].
- `docs/agent-context/runbooks/writing-plans.md`.
- `docs/agent-context/runbooks/hardening-plans.md`.
- `docs/agent-context/runbooks/testing-patterns.md`, especially the general
  rules, Pattern 8, and the proposed eventual-evidence guidance below.
- `docs/agent-context/runbooks/review-loops-and-agent-bootstrap.md`.
- `docs/agent-context/runbooks/maintaining-traceability.md`.
- `docs/lessons.md`, especially the 2026-07-11 short-timeout lesson, the
  2026-07-13 timeout scaling lesson, the 2026-08-05 startup-versus-behavior
  watchdog lesson, and the 2026-08-10 await-versus-sleep lesson.

Relevant product contracts and implementation context:

- `docs/specs/02-taut-core.md` [TAUT-3.5] and [TAUT-8.5].
- `docs/specs/04-summon.md` [SUM-12].
- `docs/specs/05-taut-mcp.md` [MCP-12].
- `docs/implementation/02-repository-map.md`.
- `docs/implementation/04-taut-architecture.md`.
- `docs/implementation/05-taut-summon-architecture.md`, especially the
  correlated-PING readiness boundary.
- `docs/implementation/07-taut-mcp-architecture.md`.
- `docs/plans/2026-08-10-test-quality-remediation-plan.md`. This plan narrows
  one repeated synchronization issue found during that wider audit; it does
  not reopen or replace that plan's full remediation inventory.

## Spec Baseline

- Baseline commit: `68222d2bb9df149e7f85a8cddd004bd1d8c0e99a`.
- Governing spec at baseline:
  `docs/specs/01-development-documentation-operating-model.md`.
- Process guidance at baseline:
  `docs/agent-context/runbooks/testing-patterns.md`.
- This plan revises both surfaces. The first implementation slice promotes the
  reviewed text atomically with the helper paths and firing tests that the
  repository path gate requires. Adopting tests may cite [DOM-10.3] only after
  that atomic slice is green.
- After promotion, record a rerunnable promotion baseline in the execution
  log. Prefer a commit SHA. For an owner-requested uncommitted review, record
  the baseline SHA plus the exact spec and runbook diffs instead.
- If implementation evidence disagrees with the promoted rule, stop and use
  the deviation process. Do not silently reinterpret the plan appendix.

## Proposed Spec Delta

Promotion strategy: **B, atomic**. The initial strategy-A attempt exposed that
the exact normative text names `tests/helpers/eventually.py` and
`tests/test_eventually.py`; Taut's executable path gate rejects those claims
until the files exist. Promote the normative rule, helper, firing tests,
repository-map entry, and reciprocal citations as one green slice. No adopting
test may depend on [DOM-10.3] before that slice passes.

| Spec file | Strategy | Sections touched |
|-----------|----------|------------------|
| `docs/specs/01-development-documentation-operating-model.md` | B | New [DOM-10.3] after [DOM-10.2.1]; `## Related Plans` backlink; atomic helper/test paths |

### [DOM-10.3] Eventual-evidence test synchronization

Insert the following exact text after [DOM-10.2.1] and before [DOM-11]:

> ### [DOM-10.3] Eventual-evidence test synchronization
>
> The canonical seam for repository tests that repeatedly observe a
> side-effect-free predicate for positive evidence is the repository-only
> `tests.helpers.eventually` module:
> `eventually` for synchronous owners and `async_eventually` when the asyncio
> event loop must yield between observations. Both use one monotonic aggregate
> deadline, cap each wait to the remaining budget, check the predicate once
> more at expiry, propagate predicate and cancellation failures, and raise one
> `AssertionError` with the evidence description, poll count, timeout and
> elapsed values, plus an optional best-effort snapshot. Snapshot collection or
> rendering failure is diagnostic only and may not replace the primary timeout.
>
> Owner: `tests/helpers/eventually.py`. Boundary: repository test code in a
> source checkout, not installed `taut-chat` or extension packages and not
> product runtime. Verification: `tests/test_eventually.py` fires each public
> interface and deadline edge under controlled time, while adopting suites
> retain their real broker, backend, thread, process, and protocol boundaries.
> Required action: use the helper only for positive observational liveness
> where repeated polling is already the synchronization seam; keep each
> caller's timeout budget explicit.
>
> The helper does not drive production state and does not reset time from
> arbitrary progress. Fixed-turn reactor tests, blocking event, condition, or
> barrier coordination, PTY, pipe, or `select` reads, consumptive queue reads,
> subprocess startup-versus-behavior watchdogs, and domain loops with distinct
> failure classification remain with their owning harness. Time cannot prove
> absence: a negative safety assertion must follow a causal or terminal fence
> and then inspect retained state or history. No policy gate bans local loops;
> recurrence after adoption is evidence for a separate reviewed gate.

Add this exact `## Related Plans` entry:

> - `docs/plans/2026-08-11-eventually-test-helper-adoption-plan.md`: adds
>   [DOM-10.3], a repository-only sync/async eventual-evidence helper, and
>   staged adoption across core and extension tests.

## Proposed Runbook Delta

Add the following exact section to
`docs/agent-context/runbooks/testing-patterns.md` after Pattern 4 and before the
current Pattern 5. Renumbering existing patterns is not required.

> ### Canonical eventual-evidence helper
>
> Use `tests.helpers.eventually.eventually` when a synchronous test already
> polls a side-effect-free predicate for positive evidence. Use
> `async_eventually` when the asyncio event loop must yield between checks.
> Pass an explicit timeout and a concrete description at every call site; add a
> cheap, side-effect-free snapshot when it materially improves timeout triage.
> Keep suite-specific defaults in a thin domain adapter only after enumerating
> every transitive caller and proving every predicate is observation-only. A
> shared `Callable[[], bool]` surface can hide control requests, consumptive
> reads, or identity-touching calls; Summon's mixed-domain adapter therefore
> remains with its owning harness.
>
> A legal predicate observes current state and may be called once more at the
> deadline. It does not consume a broker or pipe record, call `process_once`,
> mutate the system under test, or translate a domain failure into `False`.
> Predicate exceptions remain failures. Snapshot collection runs only after a
> timeout and is best-effort; it must not become a second test action.
>
> Do not use elapsed time to prove non-occurrence. First wait for evidence that
> causally follows the interval under test, then assert the negative invariant
> over retained history or state. Keep blocking primitives, fixed-turn loops,
> protocol reads, and startup-versus-behavior watchdogs in their owning harness
> when they carry stronger semantics than polling.

## Current Structure and Measured Evidence

At baseline, eight local helpers implement the same positive-observation loop
with inconsistent subsets of the desired behavior:

| Owner | Current seam | Baseline use |
|-------|--------------|--------------|
| `tests/test_watcher.py` | `_wait_until`, 3-second default | 48 calls |
| `tests/test_shared_contract.py` | `_wait_until`, 3-second default | 2 calls |
| `extensions/taut_pg/tests/test_reactor.py` | `_wait_until`, 5-second default | 11 calls |
| `extensions/taut_mcp/tests/test_process_reactor.py` | async `_wait_until`, 5-second default | 7 calls |
| `extensions/taut_mcp/tests/test_resource.py` | async `_wait_until`, 5-second default | 8 calls |
| `extensions/taut_mcp/tests/test_tools.py` | async `_wait_until`, 5-second default | 5 calls |
| `extensions/taut_mcp/tests/test_claude_channel.py` | async `_wait_until`, 5-second default | 4 calls |
| `extensions/taut_summon/tests/conftest.py` | `wait_until`, `_DEADLINE` default | about 60 suite calls through one fixture helper |

The first seven helpers account for 85 direct call sites and delegate to the
canonical helper after migration. Summon's suite adapter remains specialized:
its roughly 60 transitive callers mix observation with control request/reply
and identity-touching operations. The current tree also contains deadline
loops across about 20 test files. Most are intentionally different: subprocess result collection,
barriers, PTY reads, consumptive broker reads, live-harness readiness, or
fixed-turn reactor proofs. Their mere syntactic resemblance is not an adoption
criterion.

Current topology supports a repository-only seam:

- `tests/helpers/__init__.py` already establishes a test-support package.
- Root and extension development environments install the repository source
  checkout editably. Authoring-time `python -c` probes resolved `tests` to this
  repository, but that does not prove pytest collection uses the same path;
  S0 therefore requires exact project collection probes before migration.
- Root Hatch configuration excludes `/tests` from built artifacts, so the
  helper does not become product API.
- Root Ruff and mypy commands already cover `tests/`; no new package or
  dependency is needed.

This import topology is a hidden coupling, not an assumption to preserve at
all costs. The exact extension environments must prove resolution before
migration. If an environment resolves another top-level `tests` package,
requires `pythonpath` changes, or needs product packaging to see the helper,
stop and select another repository-only test-support path under a reviewed
deviation.

Taut does not have Weft's universal ledger premise. [TAUT-3.5] makes broker
timestamps comparable within one resolved broker, but chat rows may be deleted,
notifications may be consumed, and Summon's session ledger represents current
state. Summon readiness is a correlated PING round trip after watcher drain;
ledger rows are diagnostics, not the readiness proof. These facts block a
generic `assert_order(events, ...)` abstraction in this plan.

## Required Reading and Comprehension Gates

Before implementation, the implementer reads [DOM-10.3] after promotion, the
runbook delta, the helper call sites in the table above, and the relevant suite
architecture note. Record answers in the execution log. A wrong answer blocks
editing until the named owner text is reread.

1. **Why can this helper not replace Summon bootstrap readiness?** Expected:
   readiness is the correlated PING after watcher drain; session or message rows
   are diagnostic and cannot substitute for that causal round trip.
2. **Which predicates are legal?** Expected: repeatable, side-effect-free
   observations. Exceptions are fatal. A predicate must not consume records,
   drive a reactor, hide a domain error as `False`, or depend on being called an
   exact number of times.
3. **Why must the helper remain under `tests/`?** Expected: it is repository
   test infrastructure, excluded from wheels and public API. Extension tests
   may use the editable source checkout, but extension or core runtime packages
   must not import or ship it.
4. **What differs between sync and async wrappers?** Expected: only the wait
   mechanism needed to yield in the owning context. Deadline, final recheck,
   validation, poll counting, error priority, and diagnostics are one contract;
   asyncio cancellation propagates unchanged.
5. **How is absence proved?** Expected: establish a causal or terminal fence,
   then assert against retained state or history. A finite sleep or an
   `eventually(lambda: not condition)` call proves only one observation.

## Interface and Behavior Contract

Create these public test-only callables in
`tests/helpers/eventually.py`:

```python
def eventually(
    predicate: Callable[[], bool],
    *,
    timeout: float,
    description: str,
    interval: float = 0.01,
    snapshot: Callable[[], object] | None = None,
) -> None: ...


async def async_eventually(
    predicate: Callable[[], bool],
    *,
    timeout: float,
    description: str,
    interval: float = 0.01,
    snapshot: Callable[[], object] | None = None,
) -> None: ...
```

The contract is exact:

1. `timeout` and `interval` are positive, finite seconds. Zero, negative,
   infinite, and NaN values raise `ValueError` before the predicate runs.
2. `description` is non-empty after trimming; an empty description raises
   `ValueError` before the predicate runs.
3. The helper records one `time.monotonic()` aggregate deadline. It never
   resets that deadline when state changes.
4. It checks the predicate immediately. Immediate success performs no sleep.
5. Every wait is capped to the remaining aggregate budget.
6. Once the deadline is observed as expired, it performs exactly one final
   predicate check before failure. This closes the “evidence became visible at
   the deadline” race. There is no extra reactor step or drain.
7. Truthy predicate results return `None`. Predicate exceptions propagate
   unchanged, including on the final check. The async wrapper also propagates
   `asyncio.CancelledError` unchanged.
8. Timeout raises `AssertionError`. Its stable semantic fields are the
   description, configured timeout, elapsed time, and predicate-call count.
   Tests assert these fields by label or substring, not whole prose.
9. `snapshot`, when supplied, is called only after final predicate failure.
   Its `repr` is appended to the timeout diagnostic. Invocation or rendering
   failure is caught and represented as a secondary snapshot error containing
   the exception type; it never replaces the timeout.
10. The async predicate remains synchronous and observational. Supporting an
    awaitable predicate, progress-based deadline reset, jitter, backoff,
    callbacks, `step`, or `drains` requires a new reviewed need.

Use one private polling-state or deadline core for validation, aggregate-time
decisions, poll accounting, and timeout rendering. Keep `time.sleep` and
`asyncio.sleep` in thin wrappers. Do not expose clock or sleep injection in the
public interface. Use module-private aliases for monotonic time and synchronous
and asynchronous sleep; `tests/test_eventually.py` may monkeypatch those aliases
so unit proof does not wait on wall time.

## Invariants and Constraints

1. **No product change.** No file under `taut/`, `taut_mcp/`, `taut_pg/`, or
   `taut_summon/` imports the helper or changes behavior for the sake of it.
2. **No artifact expansion.** Built core and extension wheels remain free of
   `tests.helpers.eventually` and do not gain a test-support dependency.
3. **One aggregate deadline.** No per-turn or per-progress deadline reset is
   added. Existing caller budgets remain explicit at migrated sites.
4. **Observation only.** Predicates are idempotent observations. The helper
   cannot own production progress, broker consumption, process I/O, or cleanup.
5. **Failure priority.** Predicate and cancellation failures are fatal and
   propagate. Snapshot failure is best-effort and subordinate to timeout.
6. **Real boundaries remain real.** Adoption retains actual SQLite and
   PostgreSQL brokers, watcher threads, subprocesses, MCP reactors, and Summon
   readiness protocol. Unit tests may fake time, not the integration boundary.
7. **No global mutable state.** The helper must be safe under pytest-xdist and
   concurrent callers. Each call owns its deadline and diagnostics.
8. **No time-based absence proof.** Migration does not rewrite negative claims
   into negative polling. It either identifies a real causal fence or leaves
   the domain test unchanged with a documented disposition.
9. **No count-driven mass rewrite.** A call migrates because its predicate is
   observational and the local loop has the same liveness contract, not merely
   because `rg` found `monotonic` or `sleep` nearby.
10. **No policy gate yet.** Review guidance and deleted duplicate helpers are
    the enforcement floor for this slice. A source scanner cannot distinguish
    valid PTY/watchdog loops from generic polling without brittle heuristics.

## Hidden Couplings and Failure Modes

- The four test projects have separate dependency and invocation contexts.
  Editable root-source resolution makes the shared helper available today, but
  generic top-level package name `tests` can be shadowed. Import probes and
  selected collection must run in each exact project environment.
- Existing budgets are domain choices: core uses 3 seconds, PG and MCP use 5
  seconds, and Summon uses its CI-scaled `_DEADLINE` with a 0.05-second interval.
  A helper default must not flatten these choices.
- Async callers currently use the running loop's time while sync callers use
  `time.monotonic`. The new contract deliberately standardizes on monotonic
  wall time; parity tests must prove wrappers make the same deadline decisions.
- Predicates frequently inspect shared lists, thread liveness, private reactor
  state, or database-derived state. Snapshot collection must not race by
  iterating a mutable object unsafely; callers should return small immutable
  summaries or lock-protected snapshots.
- Some tests wrap domain errors in predicate functions so a background failure
  surfaces promptly. Migration must preserve that fast-fail behavior instead
  of converting the error to a timeout.
- `pytest-timeout`, `Thread.join`, `Process.communicate`, PTY/select deadlines,
  and Summon startup-versus-behavior watchdogs own broader deadlock or cleanup
  failure classes. The helper does not replace them.
- The exact-deadline recheck means a predicate may run once after expiry. Any
  predicate whose correctness depends on a strict call count is ineligible.
- Snapshot rendering can execute user-defined `repr`; it must be isolated from
  the primary timeout just like snapshot collection.

## Rollout, Rollback, and One-Way Doors

This is a repository test-process rollout, not a production deployment. It has
no persistence, compatibility, data migration, or one-way door.

Roll out in this order: land spec and runbook text atomically with red-then-green
helper proof; verify helper import and artifact exclusion; migrate core and PG;
migrate MCP; audit Summon's existing fixture helper and retain it if any
transitive caller is not observation-only (as occurred); then close traceability
and run full gates. Each consumer slice must pass before the next starts. Remove
a local loop only in the same slice that migrates its last caller.

Rollback in reverse dependency order: restore the affected suite's local
adapter first; remove its canonical-helper import; repeat until no consumer
remains; then remove the helper, implementation-map entry, and [DOM-10.3]
guidance. A failed extension import proof rolls back only that extension slice.
Do not solve it by adding the repo root to `pythonpath`, adding a runtime
dependency, or shipping `tests/`.

Observable success is green root, PostgreSQL, MCP, and Summon CI evidence with
unchanged integration boundaries, plus timeout reports that name the awaited
evidence. During the next normal CI observation window, any failure from a
migrated site should contain the canonical diagnostic fields. A higher flake
rate, changed timeout duration, event-loop blocking, import shadowing, or lost
domain error is a rollback signal.

## Dependency-Ordered Tasks

### S0: Reconfirm baseline and promotion readiness

- Read the required sections and answer all comprehension gates in the
  execution log.
- Re-run the measured-helper inventory and exact project import probes. Record
  drift rather than forcing the old counts.
- Confirm every named path, test selector, flag, and command still exists.
- Capture the starting diff for the operating-model spec and testing-patterns
  runbook. Preserve unrelated owner changes.
- Stop if the shared import depends on adding product packaging, a new
  dependency, or a test `pythonpath` override. Record a deviation and select a
  different repository-only seam before proceeding.
- Done when the current baseline and import/artifact boundaries are recorded
  and no unresolved deviation affects the interface.

### S1: Begin the atomic spec-promotion and helper slice

- Files to touch:
  `docs/specs/01-development-documentation-operating-model.md`,
  `docs/agent-context/runbooks/testing-patterns.md`, this plan's execution and
  deviation logs, and `docs/plans/README.md` only if its note needs correction.
- Apply the exact [DOM-10.3], runbook, and Related Plans text above. Keep this
  worktree slice open through S2 because its two path claims cannot pass before
  the helper and firing-test files exist.
- Run the plan-index and CLI-claim gates now. Run the documentation path and
  reference gates after S2 creates both claimed paths. Inspect the diff to prove
  only intended human-owned text moved.
- Record the promotion baseline identifier only after S2 makes the complete
  atomic slice green.
- Stop if review requires a behavioral expansion beyond observational
  liveness, if the active spec has acquired a conflicting [DOM-10] rule, or if
  strategy A would create warning-class traceability debt.
- Done together with S2 when active guidance, helper, firing tests, and all
  documentation gates pass as one atomic slice.

### S2: Complete the atomic slice with the red-then-green helper core

- Files to add or update:
  `tests/helpers/eventually.py`, `tests/test_eventually.py`, and, only if useful
  for stable imports, `tests/helpers/__init__.py`.
- Write the contract tests first and capture the expected missing-helper or
  missing-behavior failure. Then implement the smallest helper satisfying the
  interface above.
- Unit tests must use controlled time and scripted predicate outcomes. Do not
  make the suite sleep through real multi-second deadlines.
- Add direct proof for every numbered contract element: immediate success;
  eventual success; aggregate deadline; capped final sleep; exact-deadline
  final success; timeout fields and call count; snapshot only on timeout;
  snapshot invocation and `repr` failures; predicate exception propagation;
  invalid timeout, interval, and description; async parity; and async
  cancellation.
- Add artifact-boundary proof using existing wheel inspection conventions or a
  focused archive assertion that `tests/helpers/eventually.py` is absent from
  built core and extension artifacts. Do not build a second generic packaging
  framework.
- Update `docs/implementation/02-repository-map.md` with the helper's owner,
  repository-only boundary, and firing-test owner. Add reciprocal [DOM-10.3]
  references in the helper and test module in the repository's existing
  citation style. At this point, add any implementation link claim needed by
  the spec.
- Stop if sync and async need separate semantic cores, if public clock/sleep
  injection appears necessary, if the helper grows domain callbacks, or if
  timeout wording becomes a public product contract.
- Done when targeted helper tests, type checks, lint, import probes, and
  artifact exclusion pass, followed by a fresh independent slice review.

### S3: Core and PostgreSQL adoption

- Files to update:
  `tests/test_watcher.py`, `tests/test_shared_contract.py`, and
  `extensions/taut_pg/tests/test_reactor.py`.
- Delete each local `_wait_until` only after all callers in that file use
  `eventually` with the same explicit budget and interval. Supply a concrete
  description to every call. Add a small immutable snapshot where it exposes
  thread liveness, watcher stop state, queue membership, seen-event counts, or
  preserved background errors.
- Preserve any predicate wrapper that raises a captured background-thread
  error. The helper must propagate it; do not wait for timeout.
- Keep the real SQLite and PostgreSQL brokers, native waiter, watcher threads,
  and xdist serialization. No mock may replace them.
- Review `tests/test_command_registry.py`'s nested boolean `wait_until` as a
  secondary candidate. Migrate it only if changing its `assert wait_until(...)`
  call to assertion-raising `eventually(...)` preserves the surrounding broken
  pipe and cursor proof without weakening `Condition.wait_for` ownership.
- Leave `tests/test_identity.py`'s multiprocess barrier loop in its owner unless
  a separate review proves that helper adoption retains process exit-state and
  cleanup diagnostics. Its shared-state predicate alone is not enough reason
  to migrate it.
- For the duration-based negative assertion in
  `extensions/taut_pg/tests/test_reactor.py`, either identify and prove a real
  later causal fence before changing it, or record it as unchanged. Never
  replace it with negative polling.
- Stop if a call consumes state, requires driving `process_once`, changes its
  budget, or loses domain diagnostics. Keep that call specialized and record
  the disposition.
- Done when the three duplicate helpers are gone, targeted SQLite and real PG
  suites pass, and preserved specialized-loop dispositions are logged.

### S4: MCP asyncio adoption

- Files to update:
  `extensions/taut_mcp/tests/test_process_reactor.py`,
  `extensions/taut_mcp/tests/test_resource.py`,
  `extensions/taut_mcp/tests/test_tools.py`, and
  `extensions/taut_mcp/tests/test_claude_channel.py`.
- Replace the four local async helpers and their 24 callers with
  `async_eventually`. Preserve each explicit 0.3-, 0.6-, 1.5-, or 5-second
  budget and the current 0.01-second yield interval.
- Give each wait an evidence description. Favor snapshots of immutable counts,
  workspace records, candidate IDs, owner-thread liveness, and captured
  warnings. Do not dump tokens, fingerprints, or request payloads into timeout
  text.
- Preserve real workspace-owner threads, broker-backed resources, task
  cancellation, and stdio protocol behavior. No production reactor is mocked
  merely to exercise the helper.
- Leave bespoke loops in `test_stdio_server.py`, PostgreSQL conformance, and
  maintenance-interval tests unchanged unless their owner review proves exact
  contract equivalence. Duration-based absence cases need causal fences, not
  `async_eventually`.
- Stop on event-loop blocking, cancellation translation, sensitive diagnostic
  leakage, or a predicate that awaits or consumes an event.
- Done when all four duplicate async helpers are gone, MCP's selected tests and
  project-local static gates pass, and a fresh slice review finds no lifecycle
  regression.

### S5: Summon domain-adapter audit and disposition

- File to update: `extensions/taut_summon/tests/conftest.py`.
- Keep the public fixture helper name and current call shape to avoid a broad,
  low-value rewrite. Audit every caller before converting its body. Adopt only
  if all predicates are observation-only; otherwise retain the mixed-domain
  loop and record the concrete stateful callers.
- Do not replace `DriverProcess.wait_for_start`, `wait_for_message`, correlated
  control request helpers, live-harness readiness, PTY readers, event pumps, or
  consumptive broker loops. They own protocol, process, cleanup, or I/O failure
  classes beyond generic polling.
- Run representative unit and real-process tests whose predicates observe
  driver state, control state, and message visibility. Preserve Summon's
  process xdist group and CI timing factor.
- Stop if adapter compatibility would require changing approximately 60 call
  sites, if `_DEADLINE` scaling is lost, or if correlated readiness is reduced
  to ledger observation.
- Done when the adapter surface is audited, its adoption or specialized
  retention is recorded, and both unit and real-process evidence pass without
  readiness-contract drift.

### S6: Traceability, full verification, and closure

- Re-run the inventory. The eight baseline duplicate loop bodies must be
  removed or have a documented, independently reviewed reason to remain.
- Reinspect all remaining deadline loops touched or considered by this plan.
  Record domain ownership for each non-obvious retained case. Do not set a
  repository-wide zero-loop target.
- Reconcile [DOM-10.3], the runbook, plan, helper/test citations, and
  `docs/implementation/02-repository-map.md`. Run the documentation reference
  gate with zero new errors.
- Run targeted, neighboring, extension, PostgreSQL, and full gates below.
  Capture exact command, exit status, and observed result in the execution log.
- Run completed-work review and a different-family pre-landing review against
  the promoted spec. Dispose every finding in the review log.
- Evaluate `skills/call-agent/SKILL.md` and the planning/testing runbooks for a
  concrete omission exposed by implementation. Update only for a reusable
  correction. Add a durable lesson only if the work uncovers a new rule not
  already captured in [DOM-10.3].
- Do not mark complete without an owner-authorized commit verified by
  `git log`. If the owner requests uncommitted review, report changed files and
  verification evidence and leave status active.

## Testing Plan

### Red-green protocol

- S2 is normal red-green TDD: add public-contract tests first; capture the
  missing-helper or missing-behavior failure; then implement.
- Adoption slices are behavior-preserving test refactors. Their substitute
  proof is before/after execution of the exact selected tests, plus deliberate
  timeout probes showing the new diagnostic path. Do not introduce a product
  defect merely to make migrated integration tests red.
- For each suite, run the existing selected file before editing when practical,
  then run it after migration with identical environment, selectors, and
  timing budget.

### Helper firing-test matrix

| Contract | Required proof |
|----------|----------------|
| Immediate evidence | Predicate called once; neither sleep nor snapshot runs |
| Eventual evidence | Scripted false-to-true sequence returns within one aggregate budget |
| Deadline | Controlled monotonic clock proves no reset and capped remaining sleep |
| Deadline race | Evidence appearing on the final recheck succeeds |
| Timeout | `AssertionError` includes semantic fields and exact predicate-call count |
| Predicate failure | Original exception object/type propagates; snapshot does not run |
| Snapshot | Runs only on timeout; value rendered; call and `repr` failures remain secondary |
| Validation | Non-positive/non-finite timing and blank description fail before observation |
| Async parity | Same scripted schedule reaches the same result and diagnostic fields |
| Cancellation | `CancelledError` escapes and no timeout conversion occurs |
| Packaging | Core and extension wheels do not contain the helper |

### Anti-mocking rules

- Fake monotonic time and sleep only in `tests/test_eventually.py` to make the
  deadline contract exact and fast.
- Do not mock the broker, PostgreSQL waiter, watcher owner thread, MCP workspace
  reactor, Summon driver process, correlated-PING readiness, PTY, or stdio seam
  in integration adoption tests.
- A snapshot may summarize those real objects; it must not replace them as the
  behavioral oracle.
- Existing narrow fault injectors and recording wrappers remain valid when the
  current test already uses them to expose a specified boundary.

## Verification Commands and Gates

Existence-check command shape against current `pyproject.toml`, extension
manifests, and CI workflows before execution. Use `-n 0` for deterministic
targeted diagnosis; retain canonical parallel/full commands for final proof.

### Plan and documentation gates

```bash
bin/check-plan-status-index
uv run --no-sync --extra dev bin/check-doc-paths
uv run --no-sync --extra dev pytest tests/test_docs_references.py tests/test_cli_claims.py -n 0
git diff --check
```

### Helper and import-boundary gates

```bash
uv run --no-sync --extra dev pytest tests/test_eventually.py -n 0
uv run --no-sync python -c "from tests.helpers.eventually import eventually, async_eventually"
uv run --project extensions/taut_mcp --extra dev python -c "from tests.helpers.eventually import eventually, async_eventually"
uv run --project extensions/taut_mcp --extra dev pytest --collect-only extensions/taut_mcp/tests/test_resource.py
uv run --no-sync --extra dev python -c "from tests.helpers.eventually import eventually, async_eventually"
```

The two identical root/Summon-looking commands require an execution-log note
identifying their project context. If they resolve the same environment, keep
one and prove Summon through its exact pytest invocation instead of recording
duplicate evidence.

### Targeted adoption gates

```bash
uv run --no-sync --extra dev pytest tests/test_watcher.py tests/test_shared_contract.py -n 0
uv run --no-sync --extra dev pytest tests/test_command_registry.py -n 0
uv run ./bin/pytest-pg extensions/taut_pg/tests/test_reactor.py -n 0
uv run --project extensions/taut_mcp --extra dev pytest \
  extensions/taut_mcp/tests/test_process_reactor.py \
  extensions/taut_mcp/tests/test_resource.py \
  extensions/taut_mcp/tests/test_tools.py \
  extensions/taut_mcp/tests/test_claude_channel.py -n 0
uv run --no-sync --extra dev pytest \
  extensions/taut_summon/tests/test_control.py \
  extensions/taut_summon/tests/test_driver.py \
  extensions/taut_summon/tests/test_interaction.py -n 0
```

If a selected Summon module belongs to a slower canonical process lane or
requires an existing selector, use the exact CI-owned command from
`.github/workflows/test.yml` and record the substitution. Do not weaken or skip
the real-process boundary to shorten the gate. PostgreSQL evidence requires the
configured real backend and Docker; an unavailable backend is an explicit
blocker, not a SQLite substitute.

### Static and full gates

```bash
uv run --no-sync --extra dev ruff check .
uv run --no-sync --extra dev ruff format --check taut tests bin extensions/taut_summon/taut_summon extensions/taut_summon/tests
uv run --no-sync --extra dev mypy taut tests bin/release.py bin/release-artifact.py bin/require-green-workflows.py --config-file pyproject.toml
uv run --no-sync --extra dev mypy extensions/taut_summon/taut_summon extensions/taut_summon/tests --config-file pyproject.toml
uv run --project extensions/taut_mcp --extra dev ruff check extensions/taut_mcp/taut_mcp extensions/taut_mcp/tests
uv run --project extensions/taut_mcp --extra dev ruff format --check extensions/taut_mcp/taut_mcp extensions/taut_mcp/tests
uv run --project extensions/taut_mcp --extra dev mypy extensions/taut_mcp/taut_mcp extensions/taut_mcp/tests --config-file extensions/taut_mcp/pyproject.toml
uv run --extra dev ruff check extensions/taut_pg/taut_pg extensions/taut_pg/tests bin/pytest-pg
uv run --extra dev ruff format --check extensions/taut_pg/taut_pg extensions/taut_pg/tests bin/pytest-pg
uv run --extra dev mypy taut/_scripts.py extensions/taut_pg/taut_pg extensions/taut_pg/tests --config-file pyproject.toml
uv run --no-sync --extra dev pytest
uv run ./bin/pytest-pg
```

Also run the exact Summon and MCP canonical CI commands from
`.github/workflows/test.yml` and `.github/workflows/test-mcp-extension.yml`.
Do not guess them into the plan if they drift; copy the current commands into
the execution log after existence-checking their flags and environment.

### Required failure probes

- Force one migrated sync predicate never to succeed and confirm the failure
  reports description, timing, poll count, and a safe snapshot.
- Force one migrated async predicate never to succeed and confirm the same
  semantic fields without event-loop blocking.
- Make a predicate raise a sentinel exception and prove both wrappers surface
  it immediately.
- Make snapshot collection and snapshot `repr` fail and prove the primary
  timeout remains visible.
- Cancel an `async_eventually` task during its yield and prove cancellation is
  not converted to timeout.
- Inspect built archives and prove no product artifact contains
  `tests/helpers/eventually.py`.

## Independent Review Loop

### Plan and proposed-delta review

- Before implementation, a different-family reviewer receives this entire
  plan, baseline [DOM-10], the proposed [DOM-10.3] and runbook text,
  `docs/implementation/02-repository-map.md`, the eight existing helper bodies,
  relevant packaging configuration, and `skills/call-agent/SKILL.md`.
- The reviewer first existence-checks every named path, command, flag, and
  call-site count. Then it challenges the abstraction boundary, exact deadline
  semantics, import topology, artifact exclusion, adoption scope, negative
  assertion guidance, anti-mocking rules, rollback order, and whether a
  zero-context engineer can implement the plan without inventing policy.
- A passing verdict requires no blocker and no unresolved material ambiguity.
  Every finding receives an adopted, modified, deferred-with-owner, or rejected
  disposition in the review log.

### Implementation slice reviews

- After S2, review the core interface, controlled-time firing tests, async
  cancellation, snapshot error priority, and artifact proof before adoption.
- After S3, review core/PG predicates for hidden consumption, altered budgets,
  and lost background errors.
- After S4, review event-loop yielding, cancellation, and sensitive diagnostic
  content.
- After S5, review that Summon's adapter retains `_DEADLINE`, the 0.05 interval,
  and correlated readiness ownership.
- After S6, run completed-work review and a fresh different-family pre-landing
  review against the promoted spec and actual diff. Larger merged slices do not
  waive these gates.

## Out of Scope

- Product-level `taut.testing` or a published test-support package.
- Weft-compatible `step`, `drains`, progress callbacks, stall-timeout reset,
  backoff, jitter, or worker-result inspection.
- A universal event ledger or `assert_order` assertion DSL.
- A static AST/text policy that bans local polling loops.
- Rewriting blocking `Event`, `Condition`, or `Barrier` coordination; fixed-turn
  reactor tests; subprocess communicate/join watchdogs; PTY, pipe, or select
  readers; consumptive broker reads; or live-harness readiness protocols.
- Proving absence with elapsed time or negative polling.
- Changing product timeouts, CI timeout scaling, xdist grouping, backend
  selection, or test parallelism.
- Broad cleanup from the test-quality remediation plan unrelated to this
  helper's liveness contract.

## Stop-and-Re-Evaluate Gates

Stop and record a deviation before continuing if any of these occurs:

- a production package must import or ship the helper;
- a new dependency, `pythonpath` override, or packaging inclusion is proposed;
- a predicate needs to mutate state, consume an event, await I/O, drive a
  reactor turn, or swallow a domain error;
- sync and async behavior cannot share one deadline/diagnostic contract;
- an existing timeout budget or CI timing factor would change;
- negative correctness still depends on a sleep with no causal fence;
- timeout diagnostics would expose tokens, fingerprints, message bodies, or
  other sensitive request data;
- exact extension import resolution differs from the baseline assumption;
- real PostgreSQL, process, broker, protocol, or PTY proof is replaced by a
  mock;
- the active [DOM-10] text or another in-flight plan conflicts with [DOM-10.3].

## Deviation Log

| Date | Slice | Deviation | Decision and owner | Verification impact |
|------|-------|-----------|--------------------|---------------------|
| 2026-08-11 | S1 | Strategy A could not pass `bin/check-doc-paths` or `test_documented_paths_exist` because [DOM-10.3] names the not-yet-created helper and firing-test files. | Switch to strategy B. Keep spec, runbook, helper, tests, repository-map entry, and reciprocal citations in one uncommitted atomic slice; independent Claude Opus deviation review passed before helper implementation. | The failed promotion gate is expected evidence, not an accepted warning. Both path gates must pass after S2 before any adoption. |
| 2026-08-11 | S2 | The required best-effort snapshot boundary introduces one broad `Exception` catch, and the raw-Ruff gate rejected an ordinary local `noqa` by increasing `BLE001` from 91 to 92. | Apply existing [DOM-10.2.1]: add narrow `[RUFF-SUP-084]`, its exact cardinality and rationale, a source pointer, updated global inventory, and generated location evidence. | Snapshot invocation and `repr` failure tests are the real proof. The suppression-index check, raw inventory, Ruff, and independent S2 review must pass before adoption. |
| 2026-08-11 | S3 | The PostgreSQL removed-queue test has a `0.2`-second negative assertion but no causal notification-channel acknowledgment that can distinguish an invalid removed-room wake from the later valid home wake. | Leave the assertion unchanged. A deterministic replacement requires new channel-classifying instrumentation outside S3; negative polling would only restate the scheduling bet. | Record as residual risk. Preserve the later positive home-delivery proof and real PostgreSQL waiter test. |
| 2026-08-11 | S5 | The shared Summon `wait_until` adapter accepts mixed-domain predicates. Several issue `_control_request()` request/reply round trips; unread predicates call identity-touching `list_threads()`. `eventually` would add a final post-deadline domain action. | Revert the adapter conversion and retain the existing specialized loop. A safe future change would first split observation-only waits from correlated control and identity-touching operations; changing roughly 60 callers is outside this helper adoption. | Summon unit and real-process selectors must pass after the revert. Count this as one audited retained loop, not an eighth migrated helper. |
| 2026-08-11 | S6 | A separate authorized worktree task committed the passive system doctor during this implementation, advancing `main` from the starting `68222d2` baseline to `6ef344f`. | Preserve that commit and keep this unit uncommitted on top. No intentional helper file conflicted; final diff, tests, and reviews use the resulting current tree. | Final handoff names `6ef344f` as current HEAD and distinguishes the two pre-existing lockfile edits from this unit. |

## Execution Log

| Date | Slice | Evidence | Result |
|------|-------|----------|--------|
| 2026-08-11 | Plan | Baseline `68222d2bb9df149e7f85a8cddd004bd1d8c0e99a`; eight duplicate helpers; 85 direct core/PG/MCP callers; about 60 Summon adapter callers; deadline-loop candidates in about 20 files | Planning inventory established; implementation not started. |
| 2026-08-11 | Plan gates | `bin/check-plan-status-index`; `uv run --no-sync --extra dev bin/check-doc-paths`; `git diff --check`; docs-reference, CLI-claim, and plan-index pytest owners | All passed from the current tree; 47 pytest cases passed in 1.06 seconds. |
| 2026-08-11 | S0 | Root and MCP Python resolved `/Users/van/Developer/taut/tests/__init__.py`; MCP collected 7 resource tests; Summon collected 65 control tests; Docker-backed PG collected 2 reactor tests. | Shared source-checkout import and collection boundaries passed before migration. |
| 2026-08-11 | S1 strategy-A probe | `bin/check-doc-paths`; `tests/test_docs_references.py::test_documented_paths_exist` | Failed only on the two future [DOM-10.3] paths, proving strategy A cannot keep the repository path graph green. Deviation recorded; strategy-B review passed before implementation. |
| 2026-08-11 | S1 strategy-B review | Claude Opus reviewed the exact deviation, gate implementations, spec/runbook promotion rules, and current path/citation graph. | **PASS**, no findings. Strategy B is the smallest green sequence because spec path claims and helper/test reciprocal citations form a real cycle. |
| 2026-08-11 | S1/S2 atomic promotion | Promotion baseline: `68222d2bb9df149e7f85a8cddd004bd1d8c0e99a` plus the worktree diff for [DOM-10.3], the testing-pattern section, `[RUFF-SUP-084]`, `tests/helpers/eventually.py`, `tests/test_eventually.py`, and repository-map rows. Gates: plan index, path/citation/CLI claims, suppression reconciliation, Ruff, format, mypy, root/MCP import and collection, real wheel inspection. | 75 targeted tests passed; all static/docs/import gates passed; four real wheels excluded both test paths. Atomic slice independently reviewed **PASS** with no findings. |
| 2026-08-11 | S3 core/PostgreSQL adoption | Removed three local `_wait_until` helpers and migrated 48 core watcher, 2 shared-contract, and 13 PostgreSQL waits. Non-observational `list_threads()` cursor polls were refactored to SELECT-only persisted-membership checks. Ruff, format, and mypy passed; root SQLite/shared tests passed `131`; Docker-backed `postgres:18` reactor tests passed `2`. | Independent Claude Opus review **PASS**, no findings. Every predicate is observational; the PG health adapter retains background-error priority. The unchanged PG negative sleep is the recorded residual above. |
| 2026-08-11 | S4 MCP adoption | Removed four async `_wait_until` helpers and migrated exactly 24 calls: process reactor `7`, resource `8`, tools `5`, Claude channel `4`. Preserved all `0.3`/`0.6`/`1.5`/`5.0` budgets and `0.01` intervals. Replaced one adjacent `0.05` absence sleep with synchronous Claude-task state proof. MCP Ruff, format, mypy, and the four-module pytest run passed. | Independent Claude Opus review **PASS**, no findings. All predicates are synchronous/observational, cancellation remains unchanged, diagnostics exclude sensitive values, and the Claude warning callback supplies a valid causal completion fence. |
| 2026-08-11 | S5 Summon adapter audit | An initial thin-adapter conversion passed `65` control, `37` interaction, and `138` real-process driver tests, but completed-work audit found stateful control and identity-touching predicates. The conversion was reverted. | Retained as a specialized mixed-domain loop under the S5 stop gate. Post-revert CI selectors passed `289` unit and `233` two-worker process tests. The initial green tests did not exercise timeout-path extra actions. |
| 2026-08-11 | S6 full verification | Plan/docs/path/suppression/import/collection/diff gates passed. Full root passed `1845` with `1` platform skip; full Docker PG passed `266` shared and `34` extension tests; MCP passed `252` non-PG and `7` live-PG tests; Summon passed `289` unit and `233` process tests. Full root, MCP, Summon, and PG Ruff/mypy gates passed for the implementation. | Root format check remains non-green only for four pre-existing files outside this unit (`taut/_doctor.py`, `taut/state/_sql.py`, `tests/test_system_doctor.py`, and `extensions/taut_summon/tests/test_persistence.py`). Intentional files format clean. Completed-work audits and final Claude Opus review passed after the Summon revert. |
| 2026-08-11 | S6 guidance evaluation | The Summon finding proved that a shared `Callable[[], bool]` adapter can hide stateful transitive callers even when its body looks like generic polling. | Added the transitive-caller audit rule to [DOM-10.3] and the testing runbook. `skills/call-agent` needed no invocation change. The generic gstack review skill short-circuits on an uncommitted base-branch worktree, so the repository review loop remained the applicable final gate. |
| 2026-08-11 | S2-S6 summary | Required red/failure probes, targeted/full commands, residual-risk dispositions, and independent slice/final reviews are recorded above. | Owner authorized the targeted close-out commit. The final handoff verifies commit evidence from `git log`. |

## Review Log

| Date | Reviewer | Scope and verdict | Findings | Disposition |
|------|----------|-------------------|----------|-------------|
| 2026-08-11 | Claude Opus CLI | Plan, proposed [DOM-10.3], runbook delta, interface, adoption, hardening, commands, paths, and measured counts; **PASS** with four minor findings | F1 bare import did not prove pytest collection; F2 suggested `Class 4+P (effective 5)`; F3 opening sentence could read as universal; F4 private fake-time mechanism unnamed. | F1 adopted: added exact MCP collect-only gate. F2 rejected: editing normative spec text independently fires base Class 5 under [DOM-15], while `+P` records the material verification-process change. F3 adopted: opening now names the canonical seam without an unqualified imperative. F4 adopted: module-private time/sleep aliases and test monkeypatch boundary are explicit. No blocker or major ambiguity remained; no second round required. |
| 2026-08-11 | Claude Opus CLI | Strategy-B deviation after executable path gates rejected strategy A; **PASS** | None. Reviewer verified the two-way spec-path/citation dependency, TDD red validity, and absence of a simpler separately green sequence. | Proceed with S2 as the second half of one atomic slice; no adoption or promotion-baseline claim before all gates pass. |
| 2026-08-11 | Claude Opus CLI | Completed S1/S2 atomic spec/helper slice; **PASS** | None. Reviewer re-traced validation, deadline capping, final recheck, exception/cancellation priority, snapshot failure isolation, private time seams, [RUFF-SUP-084], docs, and repository-map alignment. | Begin S3. Non-blocking observations: wheel absence is real-build evidence rather than a standing per-file test; `sqlite_only` is the repository-required marker floor; exact-deadline fake time can report one more poll than an overshooting real clock without changing behavior. |
| 2026-08-11 | Claude Opus CLI | S3 core/shared/PostgreSQL adoption at baseline `68222d2`; **PASS** | None. The reviewer traced every predicate to read-only state, verified the durable cursor SELECT, preserved budgets, safe snapshots, real backend boundaries, and immediate PG background-error priority. | Begin S4. Keep the PG `0.2`-second negative assertion as a named residual until notification-channel acknowledgment exists. |
| 2026-08-11 | Claude Opus CLI | S4 MCP async adoption at baseline `68222d2`; **PASS** | None. The reviewer verified all 24 callers, budgets, yield intervals, snapshot contents, synchronous observational predicates, unchanged cancellation, and the direct Claude-task causal fence. | Begin S5. Preserve the resource maintenance-interval sleep and other domain-owned loops. |
| 2026-08-11 | Claude Opus CLI | Initial S5 thin-adapter review at baseline `68222d2`; **superseded by completed-work audit** | F1 [P2] noted invalid-config `ValueError`, but the sampled review incorrectly classified the public predicate surface as observation-only. | Do not rely on this PASS. Final audit found stateful predicates and the adapter conversion was reverted. The invalid-config observation no longer applies to Summon's retained loop. |
| 2026-08-11 | Codex fresh-eyes audit | Completed MCP/Summon worktree review; MCP **PASS**, Summon **BLOCKED** before disposition | F1 [P1]: Summon predicates issue `_control_request()` round trips and identity-touching `list_threads()` calls; helper final recheck could perform another action after deadline. F2 [P2]: stale closing blocker text. | **F1 adopted:** reverted Summon adapter adoption and recorded the specialized-loop owner. **F2 adopted:** closing status now names only final review and owner-authorized commit. Re-run Summon/static gates and final review. |
| 2026-08-11 | Codex fresh-eyes audit | Completed helper/core/shared/PostgreSQL worktree review; **PASS after one P2** | F1 [P2]: stale plan statements contradicted the executed seven-adopted/one-retained outcome. No code, race, predicate, diagnostic, suppression, or spec/runbook findings. | **Adopted:** aligned the goal, target state, proposed runbook, current structure, rollout, and closing gate. Final narrow alignment recheck **PASS**. Independent audit passed `164` scoped tests, `2` real PG tests, and scoped static/docs gates. |
| 2026-08-11 | Claude Opus CLI | Complete corrected worktree against promoted [DOM-10.3]; **PASS** | None. The reviewer traced deadline/poll accounting, final recheck, exception/cancellation priority, snapshot subordination, validation, all adopted predicates, budgets, suppression inventory, packaging, and the Summon retained-loop disposition. | Final review gate passed. Non-actionable observations: some timeout-only snapshots rely on best-effort catch for concurrent mutation; async invalid-config proof is transitive through the shared core; pre-existing format drift remains outside the unit. |

## Fresh-Eyes Review Checklist

- Does the plan solve an observed duplication, or merely add another helper?
- Is `eventually` semantically honest for observation-only callers, with
  reactor-driving and consumptive loops excluded?
- Can a zero-context engineer implement exact deadline and snapshot-error
  priority without guessing?
- Do all enumerable interface and error branches have firing tests?
- Are sync and asyncio wrappers thin and behaviorally identical except for
  yielding?
- Does the import and wheel boundary work in each real project environment?
- Are existing suite budgets, CI scaling, xdist groups, and domain failures
  preserved?
- Are negative claims separated from liveness and tied to real causal fences?
- Does every adoption slice keep its broker, backend, process, thread, or
  protocol boundary real?
- Is rollback dependency-ordered and free of packaging or product changes?
- Are every named path, flag, selector, and command still real at execution
  time?
- Has each review finding received an explicit disposition, with no generic
  “addressed” row?

Implementation, final S6 review, and post-revert gates passed. The owner
authorized the targeted close-out commit; `git log` verification in the final
handoff is the authoritative commit evidence.
