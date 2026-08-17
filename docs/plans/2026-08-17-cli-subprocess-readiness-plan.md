# CLI Subprocess Readiness Plan

Date: 2026-08-17

Class: 5. This changes the cross-platform subprocess-test lifecycle and its
timeout/cleanup boundary after hosted Windows exposed ambiguous child timeouts.

Status: completed at `56e82359119ea1fefea55aeb29e82022127d3b36`.

## Goal

Make real CLI subprocess tests distinguish interpreter/import startup starvation
from application execution failure, without increasing the existing 20-second
application deadline, weakening assertions, reducing parallelism, or replacing
the real CLI/storage path.

## Evidence and Classification

- Release-SHA run `32041378395` timed out two Windows Python 3.11 `join`
  subprocesses after 20 seconds. The same shard showed unrelated in-process
  cases taking 35 to 58 seconds, so runner starvation is plausible, but the old
  helper provides no readiness evidence and cannot distinguish startup from an
  application/SQLite close stall.
- The same run's Windows Python 3.14 Unicode action failure is a test-fixture
  defect: production encoded the documented stdin payload as UTF-8, while the
  Python fixture decoded its pipe using the inherited Windows ANSI encoding.
- Summon and MCP setup failures were GitHub service failures: pinned action
  downloads exhausted retries on HTTP 429/500 before tests ran.

## Source and Ownership

- `tests/conftest.py::run_cli` owns real CLI subprocess invocation.
- `tests/fixtures/cli_ready.py` will be the thin test-only process wrapper.
- `taut/cli.py::main` remains the real application entry point.
- `tests/fixtures/debug_action.py` owns test-side decoding of the UTF-8 action
  stdin contract.
- `docs/lessons.md` already requires readiness before a strict subprocess
  behavior clock on saturated Windows.

Comprehension gate: the current timeout begins at `subprocess.run`, before the
child imports Taut. A timeout therefore proves only failure to exit within 20
seconds, not where the child spent that time. Implementation must preserve the
real `taut.cli.main` call and start the unchanged behavior cap only after import.

## Invariants and Constraints

- Use the real interpreter, CLI parser, Taut client, SimpleBroker, filesystem,
  stdout/stderr, and exit code. Do not mock the command or SQLite path.
- A loopback readiness channel is test-harness control traffic only. It closes
  before `main()` runs and never shares stdout/stderr with application output.
  Loopback TCP availability is an explicit hosted-runner requirement; bind or
  connect failure is fatal and has no polling or direct-invocation fallback.
- Interpreter launch and CLI import have a separate bounded startup watchdog.
  The existing `run_cli(timeout=20)` value remains the post-readiness behavior
  deadline.
- A child that exits before readiness is reaped and reported immediately. A
  child that misses either bound has its complete descendant tree killed and
  verified, is reaped with bounded output collection, and has every pipe/socket
  closed. No cleanup wait is unbounded.
- After readiness, arm a diagnostic traceback before calling the real CLI.
  Derive its delay from the actual behavior deadline, then cancel it on normal
  completion. A real post-readiness timeout remains fatal; its stack is
  evidence, never a success condition.
- Preserve binary stdin, UTF-8 text stdin/output, environment overlays,
  PostgreSQL fixture setup, coverage subprocess wiring, and all existing exact
  output assertions.
- Preserve the `python -m taut` public module contract through an exact direct
  versus wrapped help-output probe and the per-version direct Windows smoke.
- Do not change product behavior, SimpleBroker policy, workflow topology,
  parallelism, source-shard ownership, or any timeout used by production code.

## Rollback and One-Way Door

The harness and fixture changes are independently revertible before tagging.
The release tag and immutable publication remain the one-way door. No 0.9.1 tag
may be created until a fresh exact-SHA root workflow proves the corrected
Windows boundary and every normal producer is green.

## Execution

1. Add real subprocess firing tests for readiness-before-behavior timing,
   pre-readiness exit, post-readiness timeout cleanup/diagnostics, an
   inherited-pipe descendant, binary stdin, and unchanged CLI output.
2. Add the test-only wrapper and refactor `run_cli` to the acknowledged readiness
   protocol. Stop if this requires a production hook or changes CLI argv/output.
3. Decode the action fixture from raw UTF-8 bytes and retain the exact Unicode
   assertion that failed on Windows. Force a non-UTF-8 child text codec in the
   test so the prior fixture fails on every platform.
4. Run focused tests, the full root suite, Ruff, mypy, doc gates, and an
   independent review. Commit and push only after they pass.
5. Run the normal coordinated 0.9.1 helper again. Treat a post-readiness timeout
   as an application failure and use its captured stack; treat a startup-bound
   failure as runner/import evidence. Do not rerun either blindly.

## Verification and Success Signal

- All readiness protocol branches have firing tests with verified reap/cleanup.
- The full root suite and every release-owned extension/static gate pass.
- Fresh exact-SHA Windows 3.11 and 3.14 jobs pass, along with all other producer
  jobs. The release helper then creates all five tags and their release gates
  publish exact artifacts to GitHub and PyPI with valid Sigstore provenance.

## Out of Scope and Stop Gates

- No speculative SimpleBroker or SQLite fix without a post-readiness stack or a
  deterministic reproducer.
- No larger timeout, retry around a test failure, assertion relaxation, skipped
  case, source-shard change, or reduced parallelism.
- Stop before tag mutation on any failed exact-SHA producer or changed release
  state.

## Review Log

| Date | Review | Result | Disposition |
|------|--------|--------|-------------|
| 2026-08-17 | Claude outside-voice review | Two applicable P2 findings: temp-file cleanup did not cover bind/spawn failure and leak assertions observed the wrong path. Several P1/P2 claims described code absent from the supplied diff and were rejected by direct inspection and passing firing tests. | Centralized diagnostic ownership in an outer `finally`; added injected-path cleanup proofs for pre-ready exit, startup timeout, behavior timeout, bind failure, and spawn failure; moved the ready event after traceback arming; added a bounded child connect and direct module-entry parity. A fresh review is required. |
| 2026-08-17 | Claude second review with new files included | Two P2 blockers: direct-child kill plus unbounded collection could hang on a descendant-held pipe, and traceback timing was not derived from non-default behavior deadlines. It also requested practical timing headroom and error-path module parity. | Added bounded full-process-tree termination and a real inherited-pipe descendant proof; derived traceback timing from every behavior timeout; increased the readiness proof's command headroom; added successful post-dump stderr isolation and help/error module parity. A fresh review is required. |
| 2026-08-17 | Claude third review | No P1 and the change was judged landable on correctness. P2 follow-ups requested wider synthetic timing margins and explicit failure if the final bounded reap cannot verify exit. | Made descendant creation/readiness causal, widened deliberate timing probes without changing the 20-second application contract, armed tracebacks at one quarter of each actual deadline, and made failed final reap an explicit fatal cleanup error. Focused tests and static checks passed afterward. |

## Execution Log

- Release SHA `50041d9` local gates passed, then root run `32041378395`
  attempt 1 exposed three independent failures before tags: GitHub action
  downloads failed on HTTP 429/500; Windows 3.14 deterministically exposed the
  locale-decoding fixture defect; Windows 3.11 timed out two pre-readiness-blind
  CLI children while unrelated cases took 35 to 58 seconds.
- Same-SHA attempt 2 made no code change. Summon setup passed, proving the
  download failure transient. Windows 3.11 also passed: the two former timeout
  cases took 4.43 and 2.30 seconds and the source shard fell from 7m37s to
  3m53s. This proves hosted variability, not where attempt 1 spent its time.
  Windows 3.14 retained the deterministic Unicode failure, as expected.
- The complete root source selection passed locally with its normal xdist
  scheduling. The focused CLI/debug/harness selection passed with one documented
  POSIX-only skip. Repository-wide Ruff and all five mypy lanes passed (138,
  12, 41, 21, and 33 source files); doc-path, plan-index, and diff checks passed.
- The normal coordinated helper reran every local release gate at `56e8235`:
  root source `2080 passed, 1 skipped`, installed wheels `28 passed`, real
  PostgreSQL `287 + 37 + 7 passed`, Summon `307 + 244 passed`, eight strict
  external harnesses, the disposable-Ollama smoke, MCP `269 passed`, and TUI
  `322 passed`. Repository-wide Ruff and all five mypy lanes were clean.
- Exact-SHA root run `32045890002` passed on its first attempt, including every
  Windows job and the coverage producer/combiner. PG `32045889985`, MCP
  `32045889952`, and TUI `32045889971` also passed on their first attempts
  before tag mutation.
- All five 0.9.1 tags resolve to `56e8235`. All five GitHub Releases are public
  and immutable, PyPI has exactly each wheel and sdist with matching hashes,
  and all ten files have exact Sigstore workflow/tag/commit provenance. The
  root release gate `32047186181` completed on attempt 2 after attempt 1 hit a
  GitHub artifact-service outage before publication; no bytes were rebuilt.
