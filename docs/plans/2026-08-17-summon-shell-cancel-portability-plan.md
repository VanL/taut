# Summon Shell Cancellation Portability Plan

Date: 2026-08-17

Class: 4. This is a risky blocking-I/O and thread-cleanup correction inside the
existing [SUM-7.4]/[SUM-13] cancellation contract. No normative behavior is
added or changed.

Plan type: implementation.

Status: active.

## Goal

Make the existing shell pre-attach cancellation decision work on Windows.
Preserve the exact prompt, complete-line blank/nonblank/EOF decision, no-child
pre-spawn result, POSIX behavior, and cancellation responsiveness. Never apply
Windows socket-only `select()` to an ordinary stdin handle.

## Source Documents and Spec Baseline

- `docs/specs/04-summon.md` [SUM-7.4] Pre-attach acknowledgement and [SUM-13]
- `docs/implementation/05-taut-summon-architecture.md`, Host interaction
- `docs/agent-context/runbooks/hardening-plans.md`
- `docs/agent-context/runbooks/testing-patterns.md`
- `extensions/taut_summon/taut_summon/interaction.py`
- `extensions/taut_summon/tests/test_interaction.py`
- `CHANGELOG.md`

Committed spec baseline: `1f9aa6138696b046d6964978903398a9a69918fe`.
The spec already requires host cancellation to be a normal pre-spawn result
and host errors to remain fatal. The Windows implementation violates that
contract; no spec promotion or owner policy choice is needed.

## Evidence, Ownership, and Classification

- Exact-SHA run `32089625236`, Windows Python 3.14 job `95569114612`, passed
  the root suite and compatibility smoke, then failed
  `test_shell_interaction_cancel_event_interrupts_pending_acknowledgement`.
- The interaction owner thread raised `OSError: [WinError 10038]` from
  `select.select([input_fd], ..., 0.1)`. Windows `select()` accepts sockets;
  the authoritative input was a real anonymous pipe.
- This is an application portability defect, not test isolation. The test
  correctly requires a normal `False` decision and no live owner thread.
- `interaction.py` owns shell input/cancellation; `test_interaction.py` owns
  the real-pipe integration proof.

## Invariants and Hidden Couplings

- Keep the public protocol/signatures, authoritative streams, escaped prompt,
  no-cancel `readline()`, blank-Enter confirmation, and EOF/nonblank decline.
- POSIX retains its current fd `select()` path. This correction makes no new
  claim about cancellation after partial noncanonical pipe bytes on POSIX;
  the production shell requests acknowledgement only after stdin reports a
  TTY, whose normal canonical line discipline makes readiness line-oriented.
- Windows uses exactly one non-daemon, method-owned thread whose only blocking
  operation is the authoritative stream's single existing `readline()`. This
  preserves console/pipe/file buffering, encoding, echo, and line semantics.
- A start barrier prevents `readline()` until the reader opens and publishes a
  handle to its own exact native thread id with `THREAD_TERMINATE`. Open failure
  publishes the error, exits without reading, joins, and propagates. The whole
  start/acquisition/return scope has one cleanup owner, so interruption cannot
  strand the barrier reader or lose a transferred handle.
- A lock arbitrates one terminal action. A complete line published first owns
  the line decision. Otherwise cancellation owns the result. The owner issues
  `CancelSynchronousIo` only against that reader, records a successful request
  token for that attempt, and joins the reader before returning.
- `ERROR_NOT_FOUND` means the read-entry race and retries only while that same
  reader is alive. Any other cancel error is recorded as primary, but cleanup
  continues retrying the same cancellation until the reader terminates; after
  join and handle close, the primary error propagates. The method never reports
  success or leaks a reader merely because cancellation itself failed.
- Normalize reader `ERROR_OPERATION_ABORTED` only when cancellation owns the
  terminal action and the exact reader has a successful cancel-request token.
  The same error without that ownership is fatal. No second read is permitted.
- Handle close is mandatory after join. Cleanup errors do not replace an
  earlier reader/cancel error, but are fatal when no earlier error exists.
- The existing 100 ms interval remains event-observation responsiveness, not
  a success timeout. Only line completion or cancellation decides the result.

## Anti-Mocking Floor and TDD

- Retain the real `os.pipe()` threaded cancellation test and run it with
  unhandled-thread warnings as errors. This is the hosted failure boundary.
- Retain exact real blank line, nonblank line, and empty EOF decisions. Add a
  real partial-line then writer-close case to prove the full line remains the
  decision input. Do not add a cross-platform partial-line cancellation claim
  that the unchanged POSIX TTY path does not own.
- Exercise the Windows owner protocol on non-Windows through narrow injected
  Win32 calls while retaining a real blocking reader: line-first;
  cancel-before-read; cancel-during-read; `ERROR_NOT_FOUND` entry race;
  simultaneous line/cancel arbitration; owned aborted-read normalization; the
  same aborted read without ownership; unexpected open/cancel/read/close
  errors; exact join; and no remaining reader or handle on every return.
- Protocol doubles may control Win32 outcomes but must not replace the real
  stream decisions or public real-pipe integration proof.

## Stop Gates, Rollback, and One-Way Door

- No daemon, shared, detached, or unjoined reader. Exactly one method-owned
  Windows reader is in scope. Stop on private Python APIs, a second read,
  timeout extension, platform skip, swallowed error, prompt change, or
  provider lifecycle edit.
- Stop if a successful `CancelSynchronousIo` cannot terminate the real Windows
  anonymous-pipe reader, or if cleanup cannot join it. Do not accept a leaked
  reader fallback.
- Rollback is confined to the reader owner, tests, and owner docs.
- Release tags are the one-way door. No 0.9.2 tag may be pushed until fresh
  exact-SHA root, PG, MCP, and TUI producers pass.

## Tasks

1. Review this implementation plan before editing.
2. Add the real line-decision and Windows owner-protocol firing cases; record
   RED against socket-only `select()` ownership.
3. Implement the narrow synchronous-reader owner and update implementation
   guidance; keep POSIX and provider lifecycle unchanged.
4. Run focused warnings-fatal tests, complete Summon serial/xdist suites,
   repository Ruff/format, Summon mypy, docs/diff, and completed-work review.
5. Commit, push, and require a fresh exact-SHA canonical root producer before
   resuming `bin/release.py`.

## Independent Review

Review must verify exact reader identity, start barrier, terminal arbitration,
cancel token/error ownership, retry cleanup, mandatory join/handle close,
unchanged line/prompt/POSIX semantics, real hosted evidence, and release stop
gates. Any P1/P2 finding blocks implementation or landing.

## Deviation Log

| Spec ref | Planned behavior | Actual behavior | Rationale | Spec proposal |
|----------|------------------|-----------------|-----------|---------------|

## Execution Log

- Plan drafted from run `32089625236`, job `95569114612`. Primary Microsoft
  documentation rejected `PeekNamedPipe` as the cancellation owner because it
  may itself block on synchronous handles; the plan now uses the documented
  dedicated synchronous-reader/`CancelSynchronousIo` pattern.
- Plan review cleared the dedicated-reader design after it gained an explicit
  start/abort barrier, first-wins terminal action, exact cancel token, bounded
  `ERROR_NOT_FOUND` retry cadence, mandatory join-before-handle-close, and
  primary-error containment.
- RED: four initial owner-protocol tests failed because the Windows reader and
  exact-thread Win32 ownership helpers did not exist. GREEN: 19 focused
  real-pipe/protocol cases passed with unhandled thread exceptions promoted to
  errors; the full interaction file passed 60 cases. Review-discovered firing
  probes also prove atomic line/action publication and that wait/join
  interruptions cannot replace the primary failure or skip handle closure.
- Canonical local Summon partitions passed: 329 unit tests (258 deselected),
  and 249 process/load tests under `-n 2 --dist load` in 77.27 seconds.
  Repository Ruff and all format lanes passed; all five mypy lanes passed (138
  root, 12 PG, 41 Summon, 21 MCP, and 34 TUI source files).
- Completed-work review found and drove firing fixes for atomic line/action
  publication, full start/handle lifecycle ownership, and signal-interruptible
  cleanup lock/event/join edges. Final independent review returned CLEAR with
  no P1/P2; real Win32 behavior remains the hosted gate.
- Fresh exact-SHA Windows producer evidence remains pending and blocks release.

## Related Plans

- `docs/plans/2026-08-17-summon-first-attach-handoff-plan.md`
- `docs/plans/2026-08-17-mcp-tools-seed-lifecycle-plan.md`
