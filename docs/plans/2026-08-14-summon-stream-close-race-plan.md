# Summon Stream Close Race Plan

Date: 2026-08-14

Class: 5. The fix revises normative [SUM-7.1] behavior and changes an
asynchronous child-stream cleanup boundary after a release gate exposed an
unhandled pump-thread exception.

Status: active.

Plan type: implementation with spec revision.

## Goal

Make an owned stream-json close end its blocked event reader as normal EOF,
without hiding a spontaneous read failure while the handle is open.

## Source Documents

- `docs/specs/04-summon.md` [SUM-7.1]
- `docs/implementation/05-taut-summon-architecture.md`
- `docs/agent-context/runbooks/hardening-plans.md`

## Context and Key Files

- `extensions/taut_summon/taut_summon/_stream.py`: `StreamJsonHandle.close()`
  owns child reap and stream release; `_event_stream()` owns the concurrent
  stdout iterator.
- `extensions/taut_summon/tests/test_scripted_adapter.py`: real handle tests and
  deterministic `Popen`-shaped lifecycle race seams.
- `extensions/taut_summon/tests/test_controller.py`: real scripted-child proof
  for foreground callback-failure cleanup.
- `docs/specs/04-summon.md` [SUM-7.1] and
  `docs/implementation/05-taut-summon-architecture.md`: normative and durable
  ownership/order descriptions.

Comprehension gates, answered before implementation:

1. Which owner may close stdout? `StreamJsonHandle.close()` after bounded child
   wait/escalation/reap; the event pump must not close it first.
2. Which read failure is nonfatal? Only a closed-stream `ValueError` observed
   after terminal retirement is published and the same stream reports closed.
   A read failure while open remains fatal. A wrong answer blocks editing until
   [SUM-7.1] and `_stream.py` are reread.

## Invariants and Constraints

- Keep close-before-pump-join ordering. Joining first can deadlock on a live
  provider with undrained stdout.
- Normalize only the exact owned-close condition: lifecycle is no longer
  `open` and the same stdout object is closed.
- Preserve malformed protocol, I/O, parser, and open-stream failures as fatal.
- Preserve one `ExitEvent` after the child has been reaped.
- Do not change timeouts, process parallelism, restart policy, or public API.
- The deterministic stream double may control the race, but the production
  `StreamJsonHandle` and the real controller/scripted-child regression remain
  unmocked.
- No new dependency, execution path, persistence, or one-way door is allowed.
  If the fix needs any of those, stop and re-plan.

Rollback is a single commit revert. Rollout is the normal coordinated release;
the exact-SHA hosted suite must show no pump-thread warning before tags. There
is no irreversible state change in this fix.

## Spec Baseline

- `05626d187003e118d7a56cc5e79cbc292f7ef66a` —
  `docs/specs/04-summon.md` [SUM-7.1] at plan authoring time.

Promotion baseline: pending the dedicated spec-promotion commit; implementation
must not be committed before this is replaced with that commit SHA.

## Proposed Spec Delta

Promotion strategy: A, in-file before implementation.

### [SUM-7.1] — insert after the shutdown-order paragraph

> When blocking `close()` releases a structured stdout stream while its event
> pump is blocked in iteration, the resulting closed-stream read is normal EOF
> only after terminal retirement is published and that same stream reports
> closed. Read, framing, or translation failures observed while the stream is
> open remain fatal. The normal owned-close path still emits one final `exit`
> event after child reap.

## Deviation Log

| Spec ref | Planned behavior | Actual behavior | Rationale | Spec proposal |
|----------|------------------|-----------------|-----------|---------------|

## Tasks

1. Promote the [SUM-7.1] delta and align the implementation note. Stop if the
   text would make arbitrary `ValueError` best-effort.
2. Add a deterministic barrier-controlled regression that is red on the exact
   close/read race, plus a guard proving an open-stream `ValueError` propagates.
3. Implement the narrow lifecycle-and-stream-state check in `_event_stream()`.
4. Run focused tests, the full Summon unit/process gates, Ruff, formatting,
   mypy, doc paths, plan index, and diff checks.
5. Obtain an independent review, commit, then restart the unskipped release
   process. Hosted Windows and warning-free exact-SHA evidence are required.

## Testing and Verification

- Red proof already observed:
  `uv run --no-sync --extra dev pytest extensions/taut_summon/tests/test_scripted_adapter.py::test_owned_close_ends_a_blocked_event_reader_without_thread_failure extensions/taut_summon/tests/test_scripted_adapter.py::test_open_event_stream_value_error_remains_fatal -n 0 -v --tb=short`
  produced one failure with `ValueError: I/O operation on closed file`; the
  open-stream guard passed.
- Green gates use the same command, the full two affected test files, and the
  repository's normal Summon release slices.
- Post-change success is no `PytestUnhandledThreadExceptionWarning` in the
  original controller scenario and green Windows 3.11 through 3.14 cells.

## Independent Review

Review must challenge the exception boundary, preservation of one final
`ExitEvent`, and whether the regression controls the real close/reader order.
Any broad swallow or join-before-close proposal is blocking.

## Out of Scope

- Redesigning stream ownership or the driver generation state machine.
- Changing provider shutdown budgets or retry policy.
- Cleaning up unrelated tests or warnings.

## Execution Log

- 2026-08-14: The normal release gate exposed one unhandled close-induced
  `ValueError` in `taut-summon-pump`. The release was stopped before push.
- 2026-08-14: A two-test, subsecond feedback loop deterministically reproduced
  the race and proved the open-stream guard was already fatal.
- 2026-08-14: Independent review blocked the first implementation because its
  `try` region also covered translation. Added a third red-first guard proving
  a closed stream's translator `ValueError` remains fatal, then narrowed the
  normalization boundary to `next(lines)` alone. All three boundary tests and
  both affected full test files pass with unhandled-thread warnings promoted
  to errors.
