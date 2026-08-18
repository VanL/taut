# Scripted Provider Readiness-Signal Ownership Plan

Date: 2026-08-17

Class: 4. This corrects a subprocess signal-cleanup ownership boundary in the
real scripted-provider acceptance harness.

Status: completed at `99995cc49249996c208646ee972d940c48383119`.

## Goal

Make `provider-ready` a truthful signal-lifecycle boundary. Once the parent can
observe readiness, bounded SIGINT cleanup must already be owned by the
provider's normal control-exception handler. Keep physical signals, the real
child process, the two-signal reentrant contract, and all existing deadlines.

## Source Documents and Baseline

- `docs/specs/04-summon.md` [SUM-7.1]
- `docs/implementation/05-taut-summon-architecture.md`
- `docs/agent-context/runbooks/testing-patterns.md`

Baseline: `4955eede3434cf22942780bf571cf3f7b76bae5e`. This plan repairs the
existing test-provider lifecycle and does not revise the product contract.

## Evidence, Ownership, and Classification

- Root run `32093818874`, macOS Python 3.13 job `95581170323`, failed
  `test_scripted_provider_records_reentrant_sigint_cleanup`.
- `_record({"event": "provider-ready"})` flushed the JSONL line before its file
  context finished. The parent observed the line and sent SIGINT while that
  call was still returning. `_SignalCleanupComplete` then escaped because its
  owner began only after readiness publication.
- The shipped scripted provider and its tests own this acceptance boundary.
  No Summon driver, provider adapter, production signal, or timeout behavior is
  implicated. This is a deterministic harness lifecycle race.

## Invariants and Anti-Mocking Floor

- Install the real signal handler before readiness, as today.
- Own `_SignalCleanupComplete` across start/readiness publication, optional
  session announcement, startup steps, and the input loop.
- Keep JSONL flush semantics, signal counts, watchdog/reentrant release source,
  exit codes, and the real `Popen.send_signal(SIGINT)` tests unchanged.
- Add a deterministic boundary test that raises the exact cleanup control
  exception from readiness publication. It supplements, and does not replace,
  the real subprocess signal proofs.
- Time remains only a deadlock cap. Do not add sleeps, extend deadlines, rerun
  until green, serialize xdist, or weaken process assertions.

## Stop Gates, Rollback, and Success Signals

- Stop on product driver/adapter changes, broader exception swallowing, signal
  masking, changed exit codes, or timeout changes.
- The narrow rollback is the provider ownership scope plus its firing test and
  docs. Release tags remain the one-way door.
- Require focused deterministic and physical-signal tests, the full Summon
  process partition, Ruff/format, Summon mypy, docs/diff, independent review,
  and fresh exact-SHA root plus PG/MCP/TUI producers before release.

## Tasks and Execution Log

1. RED: the injected readiness-boundary cleanup exception escaped `main()`.
2. GREEN: move existing startup/readiness work inside the existing
   `_SignalCleanupComplete` owner; the injected case and both physical-signal
   cases pass.
3. Run the broader gates and independent review, then commit and require fresh
   hosted exact-SHA evidence.

Local GREEN: the deterministic boundary case and both physical-SIGINT cases
passed; the reentrant subprocess case passed 20 consecutive runs; all 259
selected process-partition cases completed with only the two declared live
environment skips. Repository Ruff/format, Summon mypy (25 source files),
documentation paths, plan index, and diff checks passed. Independent review
returned CLEAR with no P1/P2. Fresh root run `32094496836` passed all jobs at
the exact completion SHA, including the corrected macOS Python 3.13 and 3.14
physical-SIGINT process lanes. PG `32094496899`, MCP `32094496909`, and all five
TUI jobs in `32094496894` also passed at that SHA.

## Independent Review

Review must verify the exact publication/ownership race, unchanged physical
signal behavior and deadlines, no broader catch, and retained cleanup evidence.
Any P1/P2 blocks landing.

## Related Plans

- `docs/plans/2026-08-17-summon-shell-cancel-portability-plan.md`
