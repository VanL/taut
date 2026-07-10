# Taut SQLite contention hardening plan

Date: 2026-07-08

Status: implementation in progress. This revision supersedes the earlier
same-day retry-classification draft. The accepted direction is to align Taut
with Weft and SimpleBroker connection ownership: Taut remains a thin semantic
layer over SimpleBroker, not a second broker retry implementation.

Superseded mechanism note (2026-07-09): this plan's 5.1.1 per-operation
core-release conclusion and sibling-checkout verification direction were
invalidated by the 5.1.1 bug. The proven supported runtime floor is
SimpleBroker 5.2.2, and long-lived ownership follows the 5.2.0 executable
reference reactor as specified
and implemented by `2026-07-09-taut-reactor-safety-plan.md`. The rest of this
plan remains historical context for removing Taut-owned retry layers.

## Goal

Make Taut and `taut-summon` robust under real multi-process SQLite load without
hiding corruption-shaped errors or rebuilding SimpleBroker policy inside Taut.

The governing rule:

- SimpleBroker owns queue mechanics, connection setup, and lock/busy retry.
- Taut owns identity, chat semantics, summon ledger state, control correlation,
  adapter events, live STATUS fields, and handle lifetime.
- Long-lived actors use persistent owned handles and close them at owner
  shutdown. Transient CLI/request paths use non-persistent handles.
- If a surfaced broker fault hits a long-lived owner, Taut records health
  detail, closes/reopens owned handles, and lets the next tick or idempotent
  correlated request proceed.
- Taut does not retry `malformed`, magic mismatch, disk I/O, timestamp
  row-shape, or taut-authored row-decode errors by substring.

## Source Lessons

Weft:

- `BaseTask` owns long-lived queue/control handles and closes every cached queue
  on task exit.
- STATUS/PING answers are live current-state observations, not sidecar reads or
  lifecycle mutations.
- Monitor tables are derived operational evidence only. They are never lifecycle
  truth, result authority, or control authority.
- Keyed control replies belong to the prober that issued the request id.
- Worker/adapters return typed local events; broker effects are committed by
  named owner paths.

SimpleBroker:

- Public `Queue` and `Queue.sidecar()` are the boundary. Taut must not import
  private SimpleBroker modules or wrap broker operations with its own retry
  engine.
- Static SQL templates with qmark parameters are the normal shape for fixed
  sidecar operations.
- Corruption-shaped SQLite failures are release blockers unless an integrity
  proof shows the database remains sound and the code path is otherwise correct.
- SimpleBroker must distinguish queue/session lifetime from owner-thread core
  lifetime. The corrected proof requires `simplebroker>=5.2.2`: one
  process-local persistent session selects a thread-local core for the reactor
  owner, following the 5.2.0 reference reactor. The earlier per-operation
  5.1.1 mechanism is superseded and must not be used.

## Implementation Slices

1. Remove the Taut retry layer.
   Delete `taut/_queue.py`, `taut/_broker_retry.py`,
   `extensions/taut_summon/taut_summon/_broker_retry.py`, and
   `extensions/taut_summon/taut_summon/_retry.py`. Replace imports and tests
   with direct `simplebroker.Queue` operations.

2. Make `TautClient.queue(...)` return plain `Queue`.
   Preserve `persistent=False` for transient client/CLI paths and
   `persistent=True` cached owned handles until `TautClient.close()`.

3. Keep long-lived actors persistent.
   `TautWatcher`, summon `ControlLoop`, the driver ledger client, watcher
   client, and terminal-mode mouth client use persistent owned handles. Removed
   membership handles and owner shutdown call `Queue.close()` or
   `TautClient.close()`.

4. Keep transient paths transient.
   Ordinary `taut say`, summon CLI invocations, per-request reply queues, and
   short support reads outside loops use non-persistent handles.

5. Refactor summon state SQL.
   `extensions/taut_summon/taut_summon/_state.py` uses module-level static SQL
   template strings, qmark parameters, and one canonical session projection.
   There is no runtime-built projection, joined column list, or `SELECT *`.

6. Reduce lock hold time.
   Process-liveness checks for claims and driver ownership happen outside write
   transactions. Writes are short predicate-guarded transactions that recheck
   ownership enough to preserve race safety.

7. Refactor summon control.
   Control drain, reply, client request, and rate audit call `Queue` methods
   directly. The only retry Taut owns is semantic no-reply resend for
   idempotent STATUS/PING using the same correlated request body and reply route.

8. Keep STATUS live.
   Primary STATUS/PING fields come from driver-owned memory and adapter status.
   The session ledger remains durable resume and generation authority, but
   answering a live correlated request must not read the ledger just to rebuild
   fields the driver already owns.

9. Harden readiness.
   Process readiness is a correlated PING/STATUS reply from expected driver
   evidence. Session rows and logs are diagnostics. The harness must not swallow
   `malformed summon session row` as "not ready" and must not run tight
   fresh-client polling loops.

10. Port the useful Weft spec discipline.
    Specs and tests should capture: SimpleBroker public-surface boundary,
    current-state STATUS/PING semantics, derived-evidence-only monitor posture,
    keyed reply ownership, and no private SimpleBroker reaches. Do not port
    Weft's task model, reserved queues, manager election, or task-monitor cleanup
    machinery into Taut.

## Verification

For the paired reactor hardening, local verification uses SimpleBroker 5.2.2 or
newer. The ownership design itself was ported from the 5.2.0 reference:

```bash
PYTHONPATH=/Users/van/Developer/simplebroker uv run --no-sync ...
```

Focused gates:

- `PYTHONPATH=/Users/van/Developer/simplebroker uv run --no-sync pytest tests/test_client.py tests/test_watcher.py extensions/taut_summon/tests/test_state.py extensions/taut_summon/tests/test_control.py -q -n0`
- `PYTHONPATH=/Users/van/Developer/simplebroker uv run --no-sync pytest tests/test_architecture_boundaries.py -q -n0`
- `python -m compileall -q taut extensions/taut_summon/taut_summon`

Process proof:

- Run the summon SQLite integrity stress test. It must prove
  `PRAGMA integrity_check == ok` before and after high-churn STATUS/PING/STOP
  or restart activity.

Dependency proof:

- In `../simplebroker`, run
  `uv run pytest tests/test_process_broker_session.py -q -n0`.

Release-level gates after focused tests pass:

- format/lint/type checks
- main suite
- extension suites
- local live tests
- local LLM tests
- release helper
- CI, including the local LLM lane

## Rollback

If removing the Taut retry layer exposes a real lock/busy retry gap, stop and
fix or upgrade SimpleBroker. Do not restore a Taut retry wrapper around broker
operations. If persistent long-lived handles expose a separate setup or
coordination bug, fix handle ownership or setup coordination directly.
