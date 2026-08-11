# Test Quality Remediation Plan

Date: 2026-08-10

Class: 4. This is a repository-wide, cross-component test refactor with
subprocess, signal, PTY, concurrency, persistence, PostgreSQL, release, and CI
proof boundaries. It does not change intended product behavior or a public
contract, but the concurrency and process-harness slices meet [DOM-5]'s risky
trigger.

Plan type: implementation without spec revision.

Hardening: required. The plan changes tests that own async and subprocess
lifecycle guarantees. It must preserve the real broker, database, process,
PTY, protocol, and release-workflow seams named below.

Process modifier: not +P. This plan applies the existing [DOM-10], [TAUT-11],
[SUM-12], [MCP-12], [SRCH-12.2], [PIO-11], and testing-pattern rules. It does
not change the repository's standing planning or verification policy. If
implementation proposes a new permanent CI gate or changes those rules,
reclassify and independently review that delta before proceeding.

## Goal

Replace false-green, tautological, count-only, scheduler-sensitive, and
implementation-locking tests with independent behavioral proof. Delete tests
only when another named test already owns the same contract. Preserve the
suite's production-code coverage while improving the strength of its oracles:
test count may fall, but contract coverage and meaningful line coverage must
not.

## Requested Outcomes

- Bare totals and subset checks no longer stand in for enumerable contracts.
  Exact identities, exact mappings, or required semantic subsets own those
  boundaries.
- Tests that claim to cover every dynamic field use field-distinct sentinels.
- Negative claims fail when their observation path breaks; missing members,
  swallowed exceptions, empty parity results, and absent leak sentinels cannot
  turn failures into success.
- Concurrency tests prove both actors reached the contested boundary before
  release. Sleeps and short negative timer windows are not evidence of
  concurrency, blocking, serialization, or non-occurrence.
- Shipped defaults remain live in tests that claim to cover buffering,
  closed-pipe, CLI, subprocess, broker, database, protocol, and PTY behavior.
- Exact prose, layout, timeout literals, private cache state, coroutine local
  names, and historical tombstones remain asserted only when a governing spec
  makes them contractual.
- Every deleted test or assertion has one named surviving owner. Replacements
  land and pass before deletions.
- Aggregate statement coverage does not decline by more than 0.10 percentage
  point from the implementation-start baseline; no configured package declines
  by more than 0.25 percentage point; no required coverage marker is lost; and
  every production line that becomes uncovered receives an explicit restore or
  reviewed disposition.
- No production behavior is changed merely to make a test convenient. A newly
  strong test that exposes a product defect remains strong; the product defect
  is handled as a separately reviewed deviation or follow-up.

## Source Documents

Governing process and testing rules:

- `docs/specs/01-development-documentation-operating-model.md` [DOM-5],
  [DOM-10], [DOM-11], and [DOM-15].
- `docs/agent-context/runbooks/testing-patterns.md`, especially rules 1, 5,
  and 6 and Patterns 6-8.
- `docs/agent-context/runbooks/writing-plans.md`.
- `docs/agent-context/runbooks/hardening-plans.md`.
- `docs/agent-context/runbooks/adversarial-acceptance-probes.md`.

Existing behavior contracts whose proof is being repaired:

- `docs/specs/02-taut-core.md` [TAUT-3.2], [TAUT-8.2], [TAUT-8.4],
  [TAUT-8.5], and [TAUT-11].
- `docs/specs/03-identity-addressing-notifications.md` [IAN-2] through
  [IAN-4], [IAN-7], and [IAN-10].
- `docs/specs/04-summon.md` [SUM-3], [SUM-7.4], [SUM-8] through [SUM-13].
- `docs/specs/05-taut-mcp.md` [MCP-5] through [MCP-8], [MCP-10], and
  [MCP-12].
- `docs/specs/06-search.md` [SRCH-5], [SRCH-11], and [SRCH-12.2].
- `docs/specs/08-persistence-io.md` [PIO-3.2] and [PIO-11].

Implementation context:

- `docs/implementation/04-taut-architecture.md`.
- `docs/implementation/05-taut-summon-architecture.md`.
- `docs/implementation/07-taut-mcp-architecture.md`.
- `docs/implementation/10-persistence-io.md`.
- `docs/implementation/09-search-architecture.md`.
- `.github/workflows/test.yml`, `.github/workflows/test-pg-extension.yml`, and
  `.github/workflows/test-mcp-extension.yml` for canonical lane ownership.

Task evidence:

- The 2026-08-10 audit inspected 77 test modules, 1,734 `test_*` functions,
  shared fixtures, and extension artifacts in the root, MCP, PostgreSQL, and
  Summon suites.
- The audit classified each suspect as delete, merge, replace, strengthen, or
  keep. A fresh-eyes pass rejected several tempting deletions where exact
  structure is itself a specified architecture boundary.

## Spec Baseline

- Baseline commit: `50a67eb9e5412e330475608f3d515b4096a0c994`.
- No normative spec delta is planned. The implementation target is the current
  active text of the cited sections when each slice begins.
- If a stronger test disagrees with the active spec, stop. Do not change the
  oracle or spec inside this plan. Record the discrepancy in the deviation log
  and reclassify the product or spec change.

## Current Structure and Key Files

### Core and shared contracts

- `tests/conftest.py::build_cli_env` currently forces
  `PYTHONUNBUFFERED=1`, which neutralizes the default-buffering condition in
  the live-flush and closed-pipe tests in `tests/test_cli.py`.
- `tests/test_cli.py` owns core human and JSON rendering, CLI process behavior,
  DM directory projection, and several public subprocess boundaries.
- `tests/test_project_config.py` currently observes private reaction vocabulary
  state instead of proving `TautClient.react_to_message` behavior.
- `tests/test_search.py` owns the SQLite no-raw-body invariant but enumerates
  today's known tables rather than every search-owned ordinary table.
- `tests/test_addressing.py`, `tests/test_identity.py`,
  `tests/test_public_api.py`, `tests/test_state_contract.py`,
  `tests/test_terminal_text.py`, and `tests/test_watcher.py` own the remaining
  core replacements and de-brittling work.

### MCP and PostgreSQL contracts

- `extensions/taut_mcp/tests/test_dual_era_contract.py` owns the exact
  CLI-capability-to-MCP-tool mapping. Count-only and noun-first subset checks in
  other files must defer to it.
- `extensions/taut_mcp/tests/test_resource.py`, `test_tools.py`, and
  `test_stdio_server.py` own exact resource pages, tool pages, public records,
  and real protocol exchanges. Several cases currently assert only totals.
- `extensions/taut_mcp/tests/test_process_reactor.py` uses CPython coroutine
  local names as a disposal oracle. Replace that with observable cancellation,
  readiness, command admission, and sensitive-state disposal evidence.
- `extensions/taut_pg/tests/test_pg_integration.py`, `test_pg_sidecar.py`,
  `test_persistence_io.py`, and the MCP PostgreSQL conformance suite own cleanup,
  schema convergence, partial-batch, and backend-result proof.

### Release, workflow, and static contracts

- `tests/test_github_workflows.py` owns YAML topology. Counts of commands or
  selector strings are insufficient when named steps and packages have distinct
  roles.
- `tests/test_release_artifact.py`, `test_release_publication.py`,
  `test_release_script.py`, `test_core_summon_wheel_matrix.py`, and
  `test_dev_scripts.py` own tag families, remote verification, security,
  repository settings, package roles, and PostgreSQL lane construction.
- `tests/test_architecture_boundaries.py` contains both legitimate exact
  architecture gates and one formatting-sensitive source scanner. Preserve the
  former; replace the latter with syntax-aware proof.

### Summon contracts

- `extensions/taut_summon/tests/test_persona.py` imports the production-owned
  mandatory-section inventory, making the inventory test self-confirming.
- `test_conformance.py` owns portable provider behavior. Its no-double-speak
  observer currently converts member lookup and log failures into an empty
  result.
- `test_pty_adapter.py` and `test_scripted_adapter.py` contain timing-window
  tests for serialization, blocking, activity coalescing, concurrent close,
  and repeated signal handling. Existing locks, conditions, fake clocks,
  subprocess pipes, and provider wait boundaries are the preferred seams.
- `test_live_local_llm.py` currently recognizes harness recovery by parsing
  human wording rather than structured lifecycle evidence.
- `test_control.py`, `test_driver.py`, `test_interaction.py`,
  `test_persistence.py`, `test_state.py`, and `test_summon_cli.py` own the
  remaining duplicate, formatting, CLI-forwarding, state, and public-value
  changes.

### Coverage ownership

- `[tool.coverage.run]` in `pyproject.toml` measures `taut`, `taut_summon`, and
  `taut_mcp`; tests are excluded.
- `.github/workflows/test.yml` owns root, installed-wheel, Summon unit,
  Summon process, MCP, local-LLM, and aggregate coverage lanes.
- `bin/combine-coverage.py` rejects missing, zero-byte, unreadable, skipped, or
  warning-producing raw shards.
- `bin/check-required-coverage-paths.py` owns exact cross-process path markers.
  Its source-marker tests are valid and are not cleanup targets.

## Required Reading and Comprehension Gates

Before editing a slice, read its cited spec sections, the current test owner,
the implementation owner it exercises, and `testing-patterns.md`. Record the
answers below in the plan's execution log. A wrong answer blocks editing until
the owner text is reread.

1. **When is an exact set appropriate?** Expected answer: when the contract is
   finite and enumerable, such as public exports, MCP tools, tag families, or
   required query types. A bare cardinality or subset is not equivalent because
   one member can replace another.
2. **What is the replacement-before-deletion rule?** Expected answer: the new
   owner must first fail against the named defect, then pass against current
   behavior. Only then may the weaker or duplicate owner be removed.
3. **What proves concurrency?** Expected answer: both actors have crossed an
   observable arrival boundary and one is blocked on the intended owner before
   release. Sleeping and observing that nothing happened yet is insufficient.
4. **What must remain real?** Expected answer: the broker, sidecar, SQLite or
   PostgreSQL database, public CLI/protocol entry point, real subprocess, PTY,
   or release-workflow structure named by the governing spec. Fakes may control
   time, external network/process results, or a narrow fault/arrival seam; they
   may not replace the behavior being claimed.
5. **How is coverage preservation measured?** Expected answer: same baseline
   and final lane selection; aggregate and per-package statement deltas; exact
   required marker preservation; explicit review of every newly uncovered
   production line; and a contract-owner ledger for every deletion. Test count
   is not the metric.
6. **What happens when a stronger test finds a product bug?** Expected answer:
   keep the strong oracle, preserve the red evidence, and stop for a reviewed
   plan deviation or separate product fix. Do not weaken the test to keep this
   plan green.

## Invariants and Constraints

1. **No intended product change.** Public output, storage, CLI, protocol,
   lifecycle, release, and compatibility contracts remain unchanged.
2. **Coverage is dual.** Statement coverage is a backstop, not a substitute for
   behavioral ownership. Both quantitative coverage and contract coverage must
   pass.
3. **No count substitution.** For finite contracts, assert exact identities or
   mappings. For extensible contracts, assert a named required subset plus
   semantic success for each required member.
4. **No shared-sentinel inventory proof.** Each field gets a distinct value so
   omission and duplication cannot cancel out.
5. **No fail-open observation.** Observation errors are test failures unless the
   contract explicitly makes them best-effort.
6. **No time-window concurrency proof.** Timeouts remain only as deadlock
   guards after deterministic barriers establish state.
7. **No test-induced defaults.** Tests for buffering, signal, retry, path,
   environment, and process behavior use shipped defaults unless the altered
   dimension is named and paired with a default-path test.
8. **No production-only test API.** Prefer wrapping existing locks, conditions,
   clocks, subprocess handles, and injected dependencies in the harness. If a
   deterministic proof requires a new production hook or state object, stop and
   amend this plan with the narrow production refactor and an independent
   review.
9. **Architecture gates remain when the architecture is normative.** Do not
   remove exact lifecycle-template inheritance, watcher retry/wait ownership,
   fixed SQL projection, one-terminal-owner, one-reap, or similar white-box
   gates merely because they inspect internals.
10. **Failure priority remains unchanged.** Test observation or cleanup failure
    fails the test; it does not alter production's fatal versus best-effort
    behavior.
11. **No new dependency or mutation framework.** Use focused reversible defect
    injections and existing pytest facilities.
12. **No coverage gaming.** Do not add calls whose only purpose is executing
    lines, widen tests to unrelated behavior, lower a coverage threshold, omit
    a lane, or preserve redundant tests solely for percentage points.
13. **No drive-by production or documentation refactor.** Durable lessons may
    be recorded, but product code, specs, workflow topology, and implementation
    architecture change only through an explicit deviation and review.

## Coverage Preservation Contract

### Authoritative baseline capture

Before changing any test, identify a successful `.github/workflows/test.yml`
run for the exact implementation-start commit and download all four raw
coverage artifacts: `coverage-data-root-unit`,
`coverage-data-summon-process`, `coverage-data-mcp`, and
`coverage-data-local-llm`. The local-LLM artifact is mandatory because TQ-19
changes its lifecycle proof. If the exact commit has no retained artifacts,
implementation is blocked until the workflow is run on an owner-authorized ref
for that commit. Do not substitute a non-live local selection for that lane.

Use the existing workflow and artifact owner rather than recreating the Ollama
setup in this plan:

```bash
gh run list --workflow test.yml --commit IMPLEMENTATION_START_SHA \
  --status success --limit 20 --json databaseId,headSha,conclusion
TAUT_TQ_HOSTED_DIR="$(mktemp -d)"
gh run download EXACT_RUN_ID --pattern 'coverage-data-*' \
  --dir "$TAUT_TQ_HOSTED_DIR/shards"
uv run --no-sync --extra dev python bin/combine-coverage.py \
  "$TAUT_TQ_HOSTED_DIR/shards" --output "$TAUT_TQ_HOSTED_DIR/.coverage"
uv run --no-sync --extra dev python bin/check-required-coverage-paths.py \
  --data-file "$TAUT_TQ_HOSTED_DIR/.coverage"

# Hosted data records /home/runner paths. Re-combine the same validated raw
# shards through one explicit local-root mapping before generating reports.
uv run --no-sync --extra dev python - \
  "$TAUT_TQ_HOSTED_DIR/coverage-remap.toml" <<'PY'
from __future__ import annotations

import json
import sys
from pathlib import Path

destination = Path(sys.argv[1])
destination.write_text(
    "[tool.coverage.paths]\nsource = [\n"
    f"    {json.dumps(str(Path.cwd()))},\n"
    '    "/home/runner/work/taut/taut",\n'
    "]\n",
    encoding="utf-8",
)
PY
mkdir -p "$TAUT_TQ_HOSTED_DIR/normalized"
uv run --no-sync --extra dev python -m coverage combine --keep \
  --data-file="$TAUT_TQ_HOSTED_DIR/normalized/.coverage" \
  --rcfile="$TAUT_TQ_HOSTED_DIR/coverage-remap.toml" \
  "$TAUT_TQ_HOSTED_DIR"/shards/coverage-data-*
TAUT_TQ_REPORT_DATA="$TAUT_TQ_HOSTED_DIR/normalized/.coverage"
```

Record in the execution log:

- the implementation-start commit identifier;
- Coverage version and Python version;
- aggregate `num_statements`, `covered_lines`, `missing_lines`, and
  `percent_covered`;
- the same values for `taut`, `taut_summon`, and `taut_mcp`;
- the output of `bin/check-required-coverage-paths.py`;
- the baseline workflow run ID, exact head SHA, artifact names, and any
  explicit skips.

Generate aggregate and configured-package reports from the combined data:

```bash
COVERAGE_FILE="$TAUT_TQ_REPORT_DATA" \
  uv run --no-sync --extra dev python -m coverage json \
  -o "$TAUT_TQ_HOSTED_DIR/coverage.json"
COVERAGE_FILE="$TAUT_TQ_REPORT_DATA" \
  uv run --no-sync --extra dev python -m coverage json --include='taut/*' \
  -o "$TAUT_TQ_HOSTED_DIR/coverage-taut.json"
COVERAGE_FILE="$TAUT_TQ_REPORT_DATA" \
  uv run --no-sync --extra dev python -m coverage json \
  --include='*/taut_summon/*' \
  -o "$TAUT_TQ_HOSTED_DIR/coverage-taut-summon.json"
COVERAGE_FILE="$TAUT_TQ_REPORT_DATA" \
  uv run --no-sync --extra dev python -m coverage json \
  --include='*/taut_mcp/*' \
  -o "$TAUT_TQ_HOSTED_DIR/coverage-taut-mcp.json"
```

The same commands and artifact set are required for the final hosted run. This
hosted comparison is the authoritative total-coverage gate.

### Preliminary local coverage capture

The following task-specific local capture gives fast feedback for the root,
installed-wheel, Summon unit/process, and MCP non-PG lanes. It does not replace
the authoritative hosted comparison because it omits the prepared local-LLM
producer. The lane commands must be identical between local baseline and local
final capture:

```bash
TAUT_TQ_COV_DIR="$(mktemp -d)"
TAUT_TQ_COVERAGE_CONFIG="$PWD/pyproject.toml"

COVERAGE_PROCESS_START="$TAUT_TQ_COVERAGE_CONFIG" \
  COVERAGE_FILE="$TAUT_TQ_COV_DIR/.coverage.root" \
  uv run --no-sync --extra dev python -m coverage run --parallel-mode \
  -m pytest -v --tb=short -m "not slow and not installed_wheel" -n 0

COVERAGE_PROCESS_START="$TAUT_TQ_COVERAGE_CONFIG" \
  COVERAGE_FILE="$TAUT_TQ_COV_DIR/.coverage.wheel" \
  uv run --no-sync --extra dev python -m coverage run --parallel-mode \
  -m pytest -v --tb=short -m "not slow and installed_wheel" -n 0

COVERAGE_PROCESS_START="$TAUT_TQ_COVERAGE_CONFIG" \
  COVERAGE_FILE="$TAUT_TQ_COV_DIR/.coverage.summon-unit" \
  uv run --no-sync --extra dev python -m coverage run --parallel-mode \
  -m pytest extensions/taut_summon/tests -v --tb=short \
  -m "not xdist_group" -n 0

COVERAGE_PROCESS_START="$TAUT_TQ_COVERAGE_CONFIG" \
  COVERAGE_FILE="$TAUT_TQ_COV_DIR/.coverage.summon-process" \
  uv run --no-sync --extra dev python -m coverage run --parallel-mode \
  -m pytest extensions/taut_summon/tests -v --tb=short \
  -m "xdist_group and not requires_live_harness and not requires_local_llm" \
  -n 2 --dist load

COVERAGE_PROCESS_START="$TAUT_TQ_COVERAGE_CONFIG" \
  COVERAGE_FILE="$TAUT_TQ_COV_DIR/.coverage.mcp" \
  uv run --project extensions/taut_mcp --extra dev python -m coverage run \
  --parallel-mode -m pytest extensions/taut_mcp/tests -v --tb=short \
  -m "not pg_only" -n 0

uv run --no-sync --extra dev python bin/combine-coverage.py \
  "$TAUT_TQ_COV_DIR" --output "$TAUT_TQ_COV_DIR/.coverage"
uv run --no-sync --extra dev python bin/check-required-coverage-paths.py \
  --data-file "$TAUT_TQ_COV_DIR/.coverage"
COVERAGE_FILE="$TAUT_TQ_COV_DIR/.coverage" \
  uv run --no-sync --extra dev python -m coverage json \
  -o "$TAUT_TQ_COV_DIR/coverage.json"
COVERAGE_FILE="$TAUT_TQ_COV_DIR/.coverage" \
  uv run --no-sync --extra dev python -m coverage report --show-missing
```

If the local lane selection differs from the corresponding current workflow
jobs, stop and update the commands before taking a baseline. Do not compare
unlike selections.

### Final coverage gates

The final hosted capture repeats the authoritative baseline protocol and
compares the four pairs of Coverage JSON files. Use this exact comparator,
passing the baseline and final report directories; it emits newly uncovered
production lines and fails the percentage thresholds:

```bash
uv run --no-sync --extra dev python - BASELINE_REPORT_DIR FINAL_REPORT_DIR <<'PY'
from __future__ import annotations

import json
import sys
from pathlib import Path

baseline = Path(sys.argv[1])
final = Path(sys.argv[2])
reports = {
    "aggregate": ("coverage.json", 0.10),
    "taut": ("coverage-taut.json", 0.25),
    "taut_summon": ("coverage-taut-summon.json", 0.25),
    "taut_mcp": ("coverage-taut-mcp.json", 0.25),
}
failed = False
for name, (filename, limit) in reports.items():
    before = json.loads((baseline / filename).read_text(encoding="utf-8"))
    after = json.loads((final / filename).read_text(encoding="utf-8"))
    before_pct = float(before["totals"]["percent_covered"])
    after_pct = float(after["totals"]["percent_covered"])
    decline = before_pct - after_pct
    print(
        f"{name}\t{before_pct:.6f}\t{after_pct:.6f}\t{decline:.6f}"
    )
    if decline > limit:
        failed = True
    if name != "aggregate":
        continue
    before_files = before["files"]
    after_files = after["files"]
    for path, payload in sorted(before_files.items()):
        old_lines = set(payload["executed_lines"])
        new_lines = set(after_files.get(path, {}).get("executed_lines", []))
        for line in sorted(old_lines - new_lines):
            print(f"LOST\t{path}\t{line}")
if failed:
    raise SystemExit(1)
PY
```

- Aggregate coverage may decline by at most **0.10 percentage point**.
- No configured package may decline by more than **0.25 percentage point**.
- `bin/check-required-coverage-paths.py` must remain green.
- The comparator's `LOST` rows are copied into the seeded
  `docs/plans/artifacts/2026-08-10-test-quality-coverage-line-delta.tsv` with
  baseline file/line, prior test owner, final owner, restored/dispositioned
  state, and rationale. Unexplained lost lines block completion even when
  percentage gates pass.
- A coverage increase does not excuse a missing contract owner.
- A test-count decrease is expected for duplicate deletion and is not itself a
  failure.

The seeded audit artifact
`docs/plans/artifacts/2026-08-10-test-quality-coverage-ledger.tsv` records one
row per removed or materially rewritten test: audit ID, action, exact old node
or assertion owner, contract, replacement or surviving owner, real seam, red
defect injection, and targeted green command. The separate seeded line-delta
artifact above records baseline/final production-line reconciliation. Both
contain summaries, not raw Coverage databases or credentials.

## Remediation Inventory

This table is the scope boundary. A row may be split for review, but no row may
be silently dropped.

| ID | Area and current owners | Required disposition |
|----|-------------------------|----------------------|
| TQ-01 | `tests/conftest.py`, `tests/test_cli.py` live flush and closed pipe | Remove forced unbuffering for these probes; use small records and shipped-default buffering. |
| TQ-02 | Core and Summon human renderer inventory tests | Replace shared occurrence totals with field-distinct sentinels; retain structural-control rejection. |
| TQ-03 | Core human CLI rendering and diagnostics | Preserve semantic content/order/escaping; remove unstable alignment, time, dash-count, and whole-sentence pins. |
| TQ-04 | `tests/test_project_config.py` reaction vocabulary cases | Replace private tuple inspection with public reaction acceptance, rejection, disablement, handoff, and snapshot behavior. |
| TQ-05 | `tests/test_search.py` no-raw-body proof | Enumerate every search-owned ordinary table dynamically and scan its values; treat FTS virtual/shadow tables separately. |
| TQ-06 | Addressing, identity, DM directory, public API, persistence reports | Complete reserved-prefix and exact-ID matrices; remove vacuous/unrelated assertions; prove required frozen/slotted behavior where specified. |
| TQ-07 | Core state, watcher, terminal-text, and identity timeouts | Keep meaningful ownership/merge tests; add lost-update proof; replace private flags and exact timeout literals with behavior/boundedness; delete constants-only assertions. |
| TQ-08 | MCP tool inventory and channel tests | Let the exact dual-era mapping own inventory; delete count/subset duplicates and merge channel dispatch into the generic proxy matrix. |
| TQ-09 | MCP resource, pagination, latest-state, DM, and `who` records | Assert exact identities, order, pages, member IDs, and isolation rather than lengths. |
| TQ-10 | MCP malformed-frame and reactor cancellation tests | Add a real sensitive sentinel. Preserve raw-token/digest clearing with a sanctioned coroutine-frame value scan that rejects those values under any local name, plus observable disposal and admission outcomes; do not depend on `f_locals["token"]` or delete the [MCP-4]/[MCP-10] proof. |
| TQ-11 | PostgreSQL cleanup, conformance, schema, and persistence tests | Add unrelated-schema sentinel, known-answer search oracle, exact schema identity or real behavior, and batch-boundary semantics; delete the fixture-string reread. |
| TQ-12 | Release publication and artifact family tests | Make `verify-tag` observable and mismatch-firing; behaviorally reject `--token`; add the four-family accept/reject matrix. |
| TQ-13 | Release scripts, wheel matrix, PG runner, and repository settings | Assert semantic command roles and exact issue labels; remove private tombstones and order pins unrelated to behavior. |
| TQ-14 | Workflow and coverage topology tests | Assert each named lane/package tuple; use non-empty disjoint full partition instead of fixed collected counts; remove redundant finalizer/release-gate copies. |
| TQ-15 | Architecture, Ruff, metadata, docs, and registry assertions | Use AST-aware boundary scanning; remove stale total counts, duplicated floor checks, historical phrases, non-`None` tautologies, and full-prose locks while preserving exact normative inventories. |
| TQ-23 | Ruff lock ownership assertion contradicts the retained root lock | Replace root-lock absence with exact Ruff-pin agreement across root, Summon, and MCP locks; retain the PostgreSQL no-lock boundary and align implementation notes. |
| TQ-24 | Required-coverage checker checkout-root coupling | Match required files by one unambiguous repository-relative suffix so hosted coverage can be checked from another checkout; fail closed on duplicate suffix matches. |
| TQ-25 | Persistence dump mode assertion on Windows | Keep dump/preflight behavior on every platform; assert POSIX `0600` mode only where POSIX mode bits carry that meaning. |
| TQ-26 | PostgreSQL paging setup crosses unrelated write paths 250 times | Seed valid public envelopes through the real PostgreSQL broker queue; retain the exact 100/100/50 MCP paging oracle and the existing watchdog. |
| TQ-27 | MCP started-command cancellation waits a fixed 0.5 seconds before asserting the committed effect | Replace the sleep with bounded public busy-to-success acknowledgement; retain client-cancellation and committed-effect oracles within the unchanged test deadline, with the adjacent raw-stdio owner retaining wire-level no-result coverage. |
| TQ-28 | Core pagination and unread-limit tests seed 2,251 records through work unrelated to their read/cursor contracts | Batch-seed explicit monotonic timestamps through the public broker envelope seam; use a minimal fixture only for the one-advance owner. Retain exact 100/100/50 and 1/1000 pages, timestamps, cursor updates, and boundary cardinality. |
| TQ-16 | Summon persona and no-double-speak conformance | Use an independent required-concept inventory; make member/log observation fail closed and close clients. |
| TQ-17 | Summon PTY serialization, quiet/activity, attach chord, and concurrent close | Replace timer windows with barriers, controlled clocks, actual byte-flow proof, and one-owner outcomes. |
| TQ-18 | Summon scripted blocked injection, concurrent close, and second SIGINT | Prove the pipe/wait/close boundary is entered, synchronize both callers/signals, join helpers, then assert unblock and retirement. |
| TQ-19 | Summon local-LLM recovery and client/queue lifetime | Replace human-log parsing with structured lifecycle evidence; close or safely reuse every one-shot handle. |
| TQ-20 | Summon query inventory, CLI `--db`, schema refusal, and persistence component selection | Assert named query successes, real selected-database side effects, fail-before-mutation state, and component-by-name results. |
| TQ-21 | Summon duplicate goldens, probes, PING, function identity, fixture self-test, parser cases | Merge canonical owners; delete weaker copies and representation-only/meta-tests; rename or combine parser-shape tests. |
| TQ-22 | Summon STOP prose, public value layout, and redundant assertions | Keep structured fields, causal fragments, frozen behavior, and exact public fields; remove undocumented storage-layout and logically implied assertions. |

## Rollback and Sequencing

- There are no data migrations, compatibility transitions, or one-way doors.
- Implement replacement tests before deleting old owners. Each workstream is
  independently revertible and should remain a coherent review/landing slice.
- Do not batch all deletions into an unreviewable final diff. The cleanup slice
  removes only entries whose replacement or surviving owner is already green
  and recorded in the coverage ledger.
- If a slice raises runtime materially or makes a lane flaky, revert that slice
  rather than increasing timeouts or weakening assertions. Diagnose the seam
  before reattempting.
- If a corrected test exposes a production defect, stop that slice. Preserve
  the red proof and amend this plan only if the fix is reversible, conforms to
  an existing spec, and receives the required classification and review.
  Otherwise open a separate product plan.
- Landing is test-only plus plan/evidence documentation. No deployment rollout
  is required. Hosted CI across supported Python/OS lanes is the post-landing
  success signal.

## Dependency-Ordered Tasks

### S0: Baseline, ledger, and red-proof protocol

Outcome: establish the quantitative and behavioral baseline before test edits.

- Files to update/create:
  the seeded `docs/plans/artifacts/2026-08-10-test-quality-coverage-ledger.tsv`,
  seeded `docs/plans/artifacts/2026-08-10-test-quality-coverage-line-delta.tsv`,
  and this plan's append-only execution log.
- Run the baseline coverage protocol and targeted current tests.
- Existence-check every seeded ledger node id and fill any assertion-level
  location that moved before editing. No audit disposition may rely on the
  conversation as its only source.
- For each high-risk false green, record a focused reversible defect injection
  that the old test misses and the intended replacement must catch. Minimum
  mutations: remove explicit flush, return the wrong capped notification page,
  create a pagination gap, make a no-speech observer raise, omit one rendered
  field, bypass the second SIGINT, and allow a concurrent test to run
  sequentially.
- Do not commit defect injections. Revert each explicit file immediately after
  capturing the red/false-green result and verify the diff contains no mutation.

Stop and re-evaluate if the baseline coverage lane is already red, required
markers are missing, or current workflow selection differs from the command
block.

Done signal: baseline evidence and a complete ownership ledger exist; each
planned deletion names its replacement or surviving owner.

### S1a: Core CLI buffering and rendering oracles

Outcome: complete TQ-01 through TQ-03 as one reviewable CLI slice.

- Files to update: `tests/conftest.py`, `tests/test_cli.py`, and
  `extensions/taut_summon/tests/test_summon_cli.py`. Inspect
  `tests/test_cli_probes.py`, but retain TQ-03c unchanged because [TAUT-6.4]
  makes its exact one-line diagnostic normative.
- Run live-flush and closed-pipe subprocesses without inherited
  `PYTHONUNBUFFERED`; use sub-buffer records and prove the child remains live or
  cursor-neutral as required.
- Give every dynamic renderer field a unique unsafe sentinel. Preserve exact
  machine-readable JSON while relaxing only human alignment, time, dash-count,
  and punctuation that [TAUT-8.2] declares unstable. Do not relax wording that
  another active contract specifies exactly.
- Keep message IDs, grouping, order, unread meaning, ASCII encodability,
  terminal escaping, exit classes, and no-traceback behavior.

Targeted verification:

```bash
uv run --no-sync --extra dev pytest -q -n 0 \
  tests/test_cli.py::test_cli_watch_json_flushes_records_while_live \
  tests/test_cli.py::test_cli_watch_closed_pipe_exits_0_without_advancing_cursor \
  tests/test_cli.py::test_core_human_renderer_inventory_escapes_every_dynamic_model_field \
  tests/test_cli.py::test_cli_human_glyphs_fall_back_for_legacy_stdout_encoding \
  tests/test_cli.py::test_cli_human_log_groups_messages_by_thread \
  tests/test_cli.py::test_cli_human_log_timestamps_prepend_message_ids \
  tests/test_cli.py::test_cli_human_read_uses_grouped_readme_shape \
  tests/test_cli.py::test_cli_human_list_shows_unread_counts
```

Stop if default buffering cannot be exercised without changing production or
using an oversized payload. Re-plan the subprocess harness rather than forcing
unbuffering.

Done signal: the no-flush defect injection fails both repaired owners, every
field omission is detected independently, and the focused CLI tests pass.

### S1b: Core public configuration, addressing, identity, and API proof

Outcome: complete TQ-04 and TQ-06.

- Files to update: `tests/test_addressing.py`, `tests/test_cli.py`,
  `tests/test_client.py`, `tests/test_identity.py`,
  `tests/test_project_config.py`, and `tests/test_public_api.py`.
- Use public `TautClient`, CLI, complete target equality, exact DM participant
  IDs, and explicit configured reaction acceptance/rejection.
- Keep exact public export inventories and `SearchHit` facade introspection;
  remove only redundant membership/name, lazy-cache, and unrelated assertions.
- Instantiate persistence reports and prove the frozen/slotted behavior that
  [PIO-3.2] actually specifies.
- Replace exact identity probe timeout literals with bounded fallback behavior;
  vary genuinely display-only evidence in the claim-hash test.

Targeted verification:

```bash
uv run --no-sync --extra dev pytest -q -n 0 \
  tests/test_addressing.py tests/test_cli.py tests/test_client.py \
  tests/test_identity.py tests/test_project_config.py tests/test_public_api.py
```

Stop if a test needs private `_reaction_values`, `vars(taut)` cache placement,
or a cardinality where exact identities exist.

Done signal: every configuration key changes public behavior, enumerable
addressing/DM contracts are complete, and removed assertions have named owners.

### S1c: Core search, state, watcher, and lifecycle proof

Outcome: complete TQ-05 and TQ-07.

- Files to update: `tests/test_search.py`, `tests/test_state_contract.py`,
  `tests/test_state_sqlite.py`, `tests/test_terminal_text.py`, and
  `tests/test_watcher.py`.
- Dynamically enumerate every search-owned ordinary table from real SQLite;
  inspect all columns/values and handle FTS virtual/shadow tables separately.
- Keep `MultiQueueWatcher`'s negative retry/wait-authority gate and the persona
  metadata-preservation test. Add the distinct missing behavior proofs instead
  of deleting those owners.
- For state lost-update proof, let a cooperative unknown-key writer hold a real
  `sidecar(transaction=True)` write transaction before commit. Start persona
  mutation in a spawned worker through a thin queue proxy that reports each
  real sidecar attempt and completion. If an implementation first performs a
  nontransactional read, keep the writer uncommitted until that stale read has
  completed; if it first attempts a transaction, release at that attempt
  boundary. Then assert both the returned row and persisted row preserve the
  committed unknown key plus the persona. Separate interpreter-start readiness
  from the short database-progress watchdog and bound terminate/kill cleanup.
  The proxy controls orchestration only; every read, write, lock, commit, and
  returned row stays real. Do not patch `_one`, return fabricated SQL rows, or
  use sleeps.
- Replace private persistent flags and exact watchdog/stop literals with handle
  reuse, close, start-rejection, transient operation, and bounded behavior.

Targeted verification:

```bash
uv run --no-sync --extra dev pytest -q -n 0 \
  tests/test_search.py tests/test_state_contract.py tests/test_state_sqlite.py \
  tests/test_terminal_text.py tests/test_watcher.py
```

Stop if a new public behavior test fails current production. Preserve the red
oracle and follow the product-defect rule.

Done signal: storage and concurrency gaps are fired through real SQLite,
watcher ownership remains protected, and constants/private-state-only evidence
is gone.

### S2a: MCP exact-contract and lifecycle proof

Outcome: complete TQ-08 through TQ-10.

- Files to update:
  `extensions/taut_mcp/tests/test_channel_tools.py`,
  `test_dual_era_contract.py`, `test_process_reactor.py`, `test_resource.py`,
  `test_stdio_server.py`, and `test_tools.py`.
- Keep the real SDK framing, workspace reactor, and SQLite provider. Fakes may
  control cancellation or fault timing but not domain results.
- Assert exact page contents and identities. For extensible startup queries or
  schema capabilities, assert a named required semantic set, not a total.
- Remove the channel inventory subset/count only after the dual-era exact
  mapping and every firing case are green.
- A same-provider parity assertion must include an independent known-answer
  oracle so empty/empty cannot pass.
- For raw-token and transient-digest clearing, keep the narrow CPython frame
  access because live master-coroutine state is the specified boundary and no
  public seam exposes it. Scan `frame.f_locals.values()` for the exact raw token
  string and digest bytes instead of naming local variables, then retain the
  observable cancellation, no-command-admission, publication, and cleanup
  assertions. If another interpreter cannot expose a frame, skip only that
  white-box sub-assertion with an explicit interpreter reason; do not remove
  the surrounding behavior test.

Targeted verification:

```bash
uv run --project extensions/taut_mcp --extra dev pytest \
  extensions/taut_mcp/tests -q -n 0
```

Stop if a raw-token clearing assertion is removed without the replacement
value scan and observable lifecycle outcomes.

Done signal: the stale-count mutation family fails, real SQLite MCP proofs pass,
and no current MCP tool or lifecycle contract loses an owner.

### S2b: PostgreSQL cleanup, persistence, and MCP conformance proof

Outcome: complete TQ-11.

- Files to update: `extensions/taut_pg/tests/test_pg_integration.py`,
  `test_pg_sidecar.py`, `test_persistence_io.py`, and
  `extensions/taut_mcp/tests/test_pg_conformance.py`.
- Keep the real PostgreSQL database, schemas, roles, persistence batches,
  search provider, MCP adapter, and client state.
- Cleanup proof creates an unrelated sentinel schema/table/row and proves it
  survives target cleanup.
- Concurrent schema proof asserts exact required identities or exercises real
  representative Taut operations after convergence; it does not replace one
  count with another.
- Partial-batch proof asserts a nonempty exact committed prefix and guarded
  failure state without pinning an upstream batch size.
- MCP/direct parity includes an independent known-answer Unicode result so
  empty/empty cannot pass. Preserve spec-permitted backend lexical differences.

Targeted verification:

```bash
uv run ./bin/pytest-pg --fast
uv run ./bin/pytest-pg --fast \
  extensions/taut_mcp/tests/test_pg_conformance.py
```

Stop if a PostgreSQL expectation assumes SQLite tokenization/ranking or mocks
the provider/database boundary.

Done signal: sentinel cleanup, schema convergence, partial-batch, and exact
known-answer conformance proofs pass on real PostgreSQL.

### S3: Release, workflow, metadata, and architecture proof

Outcome: complete TQ-12 through TQ-15 and TQ-23.

- Files to update: `tests/test_architecture_boundaries.py`,
  `tests/test_cli_probes.py`, `tests/test_command_registry.py`,
  `tests/test_core_summon_wheel_matrix.py`, `tests/test_dev_scripts.py`,
  `tests/test_github_workflows.py`, `tests/test_project_metadata_consistency.py`,
  `tests/test_release_artifact.py`, `tests/test_release_publication.py`,
  `tests/test_release_script.py`, and `tests/test_ruff_policy.py`; align
  `docs/implementation/04-taut-architecture.md` and
  `docs/implementation/08-complexity-and-suppression-policy.md` with the
  retained root-lock contract.
- Parse YAML and command arguments by named owner and semantic role. Do not
  replace one raw substring/count with another.
- The SimpleBroker boundary scanner must parse imports and attribute access,
  including aliases and multiline imports, while ignoring comments and string
  literals.
- Test `--token` rejection through the real parser/help surface. Test remote tag
  mismatch through the public publication CLI boundary.
- Preserve exact inventories when they are normative: built-in command names,
  release tag families, package/version floors, Ruff debt groups, and explicit
  terminal sinks.

Targeted verification:

```bash
uv run --no-sync --extra dev pytest -q -n 0 \
  tests/test_architecture_boundaries.py tests/test_cli_probes.py \
  tests/test_command_registry.py tests/test_core_summon_wheel_matrix.py \
  tests/test_dev_scripts.py tests/test_github_workflows.py \
  tests/test_project_metadata_consistency.py tests/test_release_artifact.py \
  tests/test_release_publication.py tests/test_release_script.py \
  tests/test_ruff_policy.py
```

Stop if stronger workflow parsing starts duplicating production release logic.
The test should extract and compare declared roles, not become a second release
planner.

Done signal: package/lane substitution mutations fail and harmless prose or
private representation changes no longer break unrelated tests.

### S4a: Summon persona, conformance, CLI, and state proof

Outcome: complete TQ-16, TQ-20, TQ-21, and TQ-22 without the live-LLM or PTY
concurrency changes.

- Files to update: `extensions/taut_summon/tests/test_conformance.py`,
  `test_control.py`, `test_driver.py`, `test_interaction.py`,
  `test_persistence.py`, `test_persona.py`, `test_state.py`, and
  `test_summon_cli.py`.
- Keep the real broker, state, CLI subprocess, scripted-provider subprocess,
  and component registry. Make no-double-speak observation fail closed.
- Replace `--db` error-string evidence with side effects isolated to the
  selected database.
- Prove old-schema refusal leaves version and relevant schema/index state
  unchanged.
- Keep one canonical owner for injection formatting, CLI error probes, and
  cross-process PING. Preserve distinct hostile-input and native-wake tests.
- Use an independent persona concept inventory and distinct renderer sentinels.
  Retain structured STOP fields, causal fragments, exact specified public
  fields, and frozen behavior while removing undocumented layout pins.

Targeted verification:

```bash
uv run --no-sync --extra dev pytest -q -n 0 \
  extensions/taut_summon/tests/test_conformance.py \
  extensions/taut_summon/tests/test_control.py \
  extensions/taut_summon/tests/test_driver.py \
  extensions/taut_summon/tests/test_interaction.py \
  extensions/taut_summon/tests/test_persistence.py \
  extensions/taut_summon/tests/test_persona.py \
  extensions/taut_summon/tests/test_state.py \
  extensions/taut_summon/tests/test_summon_cli.py \
  -m "not xdist_group and not requires_live_harness and not requires_local_llm"
uv run --no-sync --extra dev pytest -q -n 0 \
  extensions/taut_summon/tests/test_conformance.py::test_clean_shutdown_releases_and_no_double_speak
```

The direct conformance node is mandatory because its driver fixture marks it
`xdist_group`; the filtered unit command alone deselects it.

Stop if a replacement weakens a named [SUM-12] conformance item or mistakes
the canonical conformance owner for a duplicate.

Done signal: semantic replacements pass through real boundaries and every
duplicate candidate names the stronger surviving owner.

### S4b: Summon local-LLM evidence and handle lifetime

Outcome: complete TQ-19 as a separate hosted-boundary slice.

- Files to update: `extensions/taut_summon/tests/conftest.py`,
  `test_conformance.py`, `test_driver.py`, `test_live_harness.py`, and
  `test_live_local_llm.py`.
- Replace recovery detection based on human log strings with the existing
  append-only TUI event log.
  `extensions/taut_summon/tests/fixtures/local_llm_tui.py::main` emits a
  structured `{"event": "start", "pid": ...}` before readiness for every
  spawned harness process after its Python entry point begins. At sentinel
  success, assert exactly one observed `start`, one orientation, one
  `llm_response`, and one successful `taut_say`, exactly one proxy request, and
  a still-live driver. This proves one complete post-start generation and no
  post-start recovery. It cannot observe a process that exits before executing
  the fixture entry point; record that residual limit instead of claiming the
  child-owned log proves all spawn attempts. Do not parse driver stderr for
  recovery wording.
- Close every one-shot `TautClient` and `Queue` in `finally`; polling may reuse
  one owned client when safe or open/close each attempt.
- Keep the real PTY child, loopback OpenAI-compatible endpoint, model request,
  broker, driver, and `taut say` path.

Targeted verification:

```bash
uv run --no-sync --extra dev pytest -q -n 0 \
  extensions/taut_summon/tests/test_live_local_llm.py \
  -m "not requires_local_llm"
```

The prepared `requires_local_llm` case must then pass in the exact hosted job
that produces `coverage-data-local-llm`; a local skip is not completion.

Stop if structured recovery evidence would require changing the public Summon
protocol or fixture event shape. Human wording remains unacceptable.

Done signal: non-live diagnostics pass locally, the prepared hosted smoke is
green, its coverage artifact is nonempty, and handle-lifetime inspection is
clean.

### S5: Summon deterministic concurrency and process proof

Outcome: complete TQ-17 and TQ-18.

- Files to update:
  `extensions/taut_summon/tests/test_pty_adapter.py` and
  `test_scripted_adapter.py`; touch `test_driver.py` or fixtures only when they
  own the public boundary.
- Reuse existing synchronization objects, fake monotonic clocks, process wait
  fakes, PTY writer serialization, and stream backpressure seams. A narrow
  test-owned fake/responder hook may acknowledge that an activity event was
  consumed before the coalescing decision; do not add a production callback
  solely for the test.
- For every concurrent test, record: actor A arrival, actor B arrival,
  contested owner, observed blocked state, release action, final order, and
  exactly-once terminal/reap/close outcome.
- Timeouts remain generous deadlock guards and may not be asserted as proof of
  intermediate state.
- The second-SIGINT sender must wait for the close/wait boundary, record signal
  delivery, and be joined.
- Blocked-inject tests must fill the real pipe to `BlockingIOError`, restore
  blocking mode, prove it remains non-writable, and synchronize the injecting
  actor at its write-attempt boundary before requesting interrupt/close. Pair
  that real-pipe smoke with a deterministic stream whose `write` publishes an
  acknowledgement after entry and can be released only by the process's
  terminal signal. The platform exposes no portable acknowledgement inside
  the kernel writable wait, so the real-pipe owner must not claim to observe
  that narrower internal state.

Targeted verification:

```bash
uv run --no-sync --extra dev pytest -q -n 0 \
  extensions/taut_summon/tests/test_pty_adapter.py \
  extensions/taut_summon/tests/test_scripted_adapter.py
uv run --no-sync --extra dev pytest extensions/taut_summon/tests -q \
  -m "xdist_group and not requires_live_harness and not requires_local_llm" \
  -n 2 --dist load
```

Repeat each changed concurrency test at least 20 times under ordinary local
load. A repeated run is a flake probe after deterministic synchronization, not
a substitute for it.

Stop if the proof needs a new production-only callback, a longer sleep, or a
larger timeout. Re-plan the seam instead.

Done signal: every concurrency defect injection fails deterministically, the
targeted process lane passes, and independent slice review finds no scheduler-
only oracle.

### S6: Delete and merge superseded owners

Outcome: remove only tests and assertions made redundant by S1 through S5.

- Delete the MCP noun-first subset/count owner, PG config fixture reread,
  watcher constants-only test, release private-helper tombstone, duplicate core
  release gate, duplicate Summon PING, standalone function-identity test,
  fixture-environment self-test, duplicate basic format goldens, duplicate CLI
  probes, and unrelated lazy-import assertion.
- Merge the channel dispatch case, finalizer privilege proof, parser/request
  shape cases, and repeated semantic assertions into their canonical owners.
- Remove redundant total counts and logically implied assertions only after the
  exact owner is recorded.
- Run each deleted node id's replacement directly and update the ledger.

Stop if a candidate lacks a single named surviving owner or its removal loses
unique production coverage. Restore it until the replacement is complete.

Done signal: the ownership ledger has no blank replacement/survivor fields and
all targeted suites remain green.

### S7: Full verification, coverage reconciliation, and documentation closure

Outcome: prove improved test quality without meaningful coverage loss.

- Run the final coverage protocol and compare it with S0.
- Restore or explicitly disposition every newly uncovered production line.
- Run all final gates below, including full PostgreSQL and hosted CI lanes.
- Update this plan's execution, deviation, and review logs.
- Update `docs/lessons.md` only for a genuinely new durable lesson not already
  covered by `testing-patterns.md`. Do not duplicate Pattern 6 or Pattern 7.
- Evaluate whether any heavily used runbook needs correction. A no-change
  conclusion is acceptable and should be recorded.
- Update the plan index to `completed` only after the work is committed with
  owner authorization and `git log` verifies the completion commit.

Done signal: every coverage gate passes, all reviews are resolved, hosted CI is
green, and the plan/status index accurately records completion.

## Testing Plan

### Red proof for test changes

For replacements, the relevant red state is not necessarily broken production
at baseline. Use a focused defect injection that recreates the false-green
class and prove:

1. the old test passes or cannot distinguish the defect;
2. the replacement fails for the intended reason;
3. the defect injection is removed;
4. the replacement passes against current production.

For deletions, the red substitute is a surviving-owner proof: make the named
contract defect and show the canonical test fails. Do not invent a duplicate
replacement merely to delete a duplicate test.

### Anti-mocking rules

- Core client, CLI, addressing, config, search, and watcher proof uses real
  SQLite broker/state. Shared contract cases use real PostgreSQL through
  `bin/pytest-pg`.
- MCP firing and stdio proof uses the real SDK framing and reactor boundary.
- Summon lifecycle proof uses real subprocesses and the real fake-TUI PTY seam.
- Release/workflow tests may fake network, Git, Docker, clock, and process
  execution, but must parse the real command/YAML structures they claim.
- Fakes may expose deterministic arrival or fault boundaries. They may not
  return the expected answer from the same implementation being tested.

### Coverage is not a proxy for oracle quality

- Preserve execution coverage, but reject tests that merely call code and
  assert `is not None`, a count, or a production-derived expectation.
- Parameterization should enumerate named contract elements, not reproduce a
  production registry and compare it to itself.
- Exact strings remain only for protocols, machine-readable records, explicit
  stable diagnostics, or documented golden text. Human layout and prose use
  semantic fragments and structure.

## Verification and Gates

Per-slice commands are listed above. Final local gates:

```bash
uv run --no-sync --extra dev pytest -q -m "not slow"
uv run --project extensions/taut_mcp --extra dev pytest \
  extensions/taut_mcp/tests -q -n 0
uv run --no-sync --extra dev pytest extensions/taut_summon/tests -q \
  -m "not xdist_group and not requires_live_harness and not requires_local_llm" \
  -n 0
uv run --no-sync --extra dev pytest extensions/taut_summon/tests -q \
  -m "xdist_group and not requires_live_harness and not requires_local_llm" \
  -n 2 --dist load
uv run ./bin/pytest-pg
uv run ./bin/pytest-pg \
  extensions/taut_mcp/tests/test_pg_conformance.py
uv run --no-sync --extra dev ruff check .
uv run --no-sync --extra dev ruff format --check .
uv run --no-sync --extra dev mypy taut extensions/taut_mcp/taut_mcp \
  extensions/taut_pg/taut_pg extensions/taut_summon/taut_summon
bin/check-plan-status-index
bin/check-doc-paths
uv run --no-sync --extra dev pytest -q -n 0 \
  tests/test_docs_references.py tests/test_plan_status_index.py
```

Additional final gates:

- repeat the coverage protocol and satisfy every quantitative and line-level
  comparison;
- run changed concurrency node ids 20 times without a failure or timing-only
  assertion;
- run the prepared hosted local-LLM lane if its recovery/lifecycle proof
  changed;
- obtain green supported OS/Python GitHub Actions evidence for root, Summon,
  MCP, and PostgreSQL workflows;
- run an independent completed-work review against the audit inventory,
  coverage ledger, specs, and final diff;
- verify committed completion with `git log` before changing plan status to
  `completed`.

No post-deploy product metric applies because this changes tests only. The
operational success signal is stable green CI without increased flake rate,
plus failure of each recorded defect injection under the repaired owner.

## Independent Review Loop

### Plan review

Before implementation, an independent reviewer reads this plan,
`testing-patterns.md`, the cited verification sections, the current tests, and
the coverage protocol. Review stance:

> Could a zero-context engineer implement every audit disposition without
> deleting unique contract coverage, weakening real-boundary proof, gaming line
> coverage, or replacing scheduler-sensitive tests with different timing
> assumptions? Identify missing audit rows, nonexistent seams, overbroad tasks,
> weak coverage thresholds, and any legitimate white-box test the plan would
> wrongly remove.

The plan author records each finding in the review log and either revises the
plan or records a reasoned rejection. Any missing owner, missing real seam, or
coverage-preservation ambiguity blocks implementation.

### Slice reviews

- S1a, S1b, S1c, S2a, S2b, S3, S4a, and S4b each receive fresh-eyes review
  after their targeted gates.
- S5 receives a dedicated concurrency review before S6 deletes any prior
  owner. The reviewer checks barrier arrival, ownership, release order,
  deadlock guards, and absence of proof-by-sleep.
- S6 receives an ownership-ledger review focused on accidental coverage loss.
- S7 receives an independent completed-work review against all TQ rows and the
  baseline/final coverage comparison.

## Out of Scope

- Product behavior, new public APIs, new MCP tools, new CLI commands, storage
  migrations, release workflow redesign, or new dependencies.
- Raising a global coverage threshold or adding a permanent coverage-delta
  tool. This plan proves its own non-regression without changing standing CI
  policy.
- Maximizing test count or line coverage. The goal is stronger independent
  evidence with no meaningful coverage loss.
- Rewriting every test into an integration test. Pure parsers, serializers,
  protocol schemas, explicit architecture gates, and deterministic state
  machines keep focused unit tests where that is the correct boundary.
- Removing legitimate exact-set, exact-mapping, fixed-SQL, lifecycle-template,
  signal/reap ownership, or source-artifact tests.
- Fixing product bugs uncovered by stronger tests without explicit
  classification, plan amendment, and review.

## Deviation Log

| Spec ref | Planned behavior | Actual behavior | Rationale | Spec proposal |
|----------|------------------|-----------------|-----------|---------------|
| TQ-15d / S0 | Capture a successful exact-SHA hosted baseline before changing any audited test. | The first exact-SHA run failed because TQ-15d still required obsolete separate extension-install commands after README ownership moved to one combined command. | Repair TQ-15d first, then capture the hosted baseline before any production-behavior test changes. The repaired test reads documentation only and executes no production lines, so it cannot alter the production coverage baseline. | None. This is a sequencing correction inside the approved remediation scope. |
| TQ-23 / S0 | Capture the hosted baseline after the TQ-15d prerequisite. | The next local baseline probe found a Ruff test and two implementation notes still claiming the root lock was absent, while committed dependency work deliberately retains and validates it. | Repair the test and notes before retrying hosted CI. This policy test executes no production lines, so it cannot alter the production coverage baseline. | None. The retained root lock is already established by the dependency plan and project metadata tests. |
| TQ-24 / S0 | Validate downloaded hosted coverage with the required-path checker. | Coverage data stores the runner's absolute checkout root, so the local checker reported all six required files missing even though suffix inspection proved every marker was executed. | Match a unique repository-relative file suffix and reject ambiguity. This changes coverage evidence validation only and executes no production source. | None. |
| TQ-25 / S0 | Use a successful whole-workflow exact-SHA baseline. | Run `31433434641` produced all four valid coverage artifacts, but every Windows matrix job failed only on a pre-existing `st_mode & 0o777 == 0o600` assertion after 1,700 tests passed. Windows does not expose POSIX permission semantics through those bits. | Accept the complete Ubuntu-hosted coverage snapshot as the production baseline, retain the cross-platform dump/preflight assertions, and restrict the mode-bit oracle to POSIX before the final whole-workflow run. The conditional changes no Linux baseline production coverage. | None. [PIO-7.1] requires owner-only files where supported; it does not redefine Windows ACLs as POSIX bits. |
| TQ-26 / S7 | Run the real MCP PostgreSQL paging proof through 250 public `say` calls. | Isolated runs took 29.9 to 53.9 seconds and the slower run produced 14,571 database commits; the failure blocked in PostgreSQL `WalSync` during setup, before paging. Each `say` needlessly crossed membership, sender-cursor, search-job, and notification analysis paths for this contract. | Seed 250 valid envelopes with the public codec through the real PostgreSQL channel queue, then retain the same MCP child, exact pages, content order, and 60-second deadlock guard. | None. [MCP-12] requires real broker/client/state pagination on PostgreSQL, not repeated end-to-end send behavior already owned elsewhere. |
| TQ-24 / S7 | Re-run the documented `--include='*/taut/*'` core-package coverage filter after mapping hosted paths to the local checkout. | Because the repository directory itself is named `taut`, the leading wildcard matched all 100 measured files and made the core report equal the aggregate report. The saved baseline core report was correctly scoped, but the documented command was not reproducible on an absolute local path. | Use the repository-relative `--include='taut/*'` filter for both baseline and final data; it selects the same 68 core files and 7,130 statements in each capture. | None. This repairs evidence selection only and changes no measured execution. |
| Invariant 11 / S7 | Add no dependency while repairing tests. | Commit `d0549d0` added the dev-only `types-PyYAML` stub package after the exact hosted mypy command exposed untyped `yaml` imports in the audited test surface. | Retain the type stub and root lock update. It changes no runtime or production dependency, avoids a broad `ignore_missing_imports` escape hatch, and lets the hosted checker validate the new typed AST/workflow helpers. | None. This is a narrow verification-tool dependency required by the existing hosted type gate, not a product or test-runtime seam. |

## Execution Log

Append implementation evidence here. Do not record transient worktree state.

| Date | Slice | Evidence | Result |
|------|-------|----------|--------|
| 2026-08-10 | S0 prerequisite / TQ-15d | Exact-SHA Test run `31432504218` and local targeted runs failed on obsolete separate PG and MCP root-README injection assertions. | Red proof captured from the real maintained documentation surface; replacement asserts the combined root command, extension-owned commands, release command, and tag family while removing historical prose and duplicate dependency-floor pins. |
| 2026-08-10 | S0 prerequisite / TQ-23 | Local baseline probe failed because `test_existing_extension_locks_resolve_the_exact_ruff_pin` asserted that committed `uv.lock` did not exist. | Red proof captured from the real retained lock; replacement checks the exact Ruff pin across root, Summon, and MCP locks and preserves the PostgreSQL no-lock boundary. |
| 2026-08-10 | S0 baseline | Exact SHA `7d2cf288070bdf97d6bc274086f1008d360cc53f`, Test run `31433434641`; artifacts `coverage-data-root-unit` (3,762,532 bytes), `coverage-data-summon-process` (2,339,731), `coverage-data-mcp` (128,889), and `coverage-data-local-llm` (35,012); Coverage.py 7.15.3. | Combined 100 measured files. Required-marker result: `Every required child-process and critical Summon path was executed.` Aggregate: 11,629/12,483 lines, 854 missing, 93.158696%; `taut`: 6,717/7,130, 413 missing, 94.207574%; Summon: 3,494/3,827, 333 missing, 91.298667%; MCP: 1,418/1,526, 108 missing, 92.922674%. Coverage-producing jobs passed; whole run was red only for TQ-25 in the four Windows jobs. |
| 2026-08-10 | S0 evidence / TQ-24 | Foreign-root coverage fixture first reported all six markers missing; a duplicate-root fixture then showed that first-match suffix logic could hide ambiguity. | Replacement accepts one exact component suffix across checkout roots and returns an explicit ambiguity failure for multiple matches; six focused tests and Ruff pass. |
| 2026-08-10 | S0 portability / TQ-25 | All four Windows jobs in run `31433434641` failed `test_dump_writes_an_owner_only_empty_composite_that_preflights` on `33206 & 0o777 != 0o600`; the same jobs passed 1,700 tests and failed no other node. | Renamed owner keeps dump and dry-run preflight checks on every OS and checks `0600` only on POSIX; focused Linux behavior test and Ruff pass. |
| 2026-08-10 | S1 / TQ-01–TQ-07 | Focused S1a, S1b, and S1c gates passed; temporary defects for buffering, renderer fields, semantic fallbacks, reaction policy, raw search storage, addressing/DM identity, state merge, watcher ownership, persistent flags, and bounded waits each failed their intended owner. | Replacements assert observable records, exact identities, persistence outcomes, and bounded lifecycle behavior; weaker counts, shared production expectations, private flags, and layout pins were removed. |
| 2026-08-10 | S1 concurrency / TQ-07a | A temporary stale-read-before-write implementation lost `custom_flag` and failed `tests/test_state_sqlite.py`; the restored implementation passed. Shared-marker collection deselects the node and sqlite-only collection selects it exactly; the final node passed 20/20 serial repetitions. | Spawned worker plus adaptive real-sidecar barrier forces a stale read to complete when present; exact returned and persisted metadata own the outcome, with bounded terminate/kill cleanup. |
| 2026-08-10 | S2 / TQ-08–TQ-11 | Full non-PG MCP process-reactor file passed 24 nodes; real PostgreSQL shared suite passed 248 and PG-only extension suite passed 34. Temporary reservation-retention and non-prefix restore defects failed public retry and exact-prefix owners. | Exact mappings, known-answer records, public lifecycle recovery, real schema isolation, and committed-prefix behavior replace counts, mirror oracles, private counters, fixture rereads, and upstream batch-size coupling. |
| 2026-08-10 | S3 / TQ-12–TQ-15 | Selected release/workflow/metadata/architecture suite passed 100%; the complete root `not slow` selection passed after review corrections. | Public command outcomes, exact semantic families/roles/labels, AST-aware import boundaries, order-independent registries, and nonempty disjoint workflow partitions replace prose, order, duplicate, and implementation pins. |
| 2026-08-10 | S4–S5 / TQ-16–TQ-22 | S4a passed 201 nodes plus the directly selected conformance node; PTY/scripted lane passed 88, process lane 233, local helper lane 26, and ten changed concurrency owners passed 20 repetitions each (200 executions). | Independent persona concepts, fail-closed observers, structured local-LLM evidence, real selected-DB effects, deterministic barriers/clocks/byte flow, and one-owner close/reap outcomes replace counts, swallowed errors, sleeps, prose, duplicate probes, and private representation checks. |
| 2026-08-10 | S5 review repair | First-byte detach and missing post-entry terminal-signal mutations failed the corrected PTY/stream owners. The revised state owner and five revised Summon concurrency cases then passed 20/20 loop iterations with the original deadlock guards. | Split-chord proof acknowledges the real matcher result; already-entered-write proof uses a deterministic signal-released stream; real full-pipe tests claim only the observable retirement boundary. |
| 2026-08-10 | S7 local integration | Root `not slow`, full non-PG MCP, both Summon marker partitions, real PostgreSQL shared/extension suites, docs references, plan index, doc paths, Ruff suppression index, changed-file formatting, and per-project mypy all passed. | Local gates are green; hosted exact-SHA coverage comparison and final completed-work review remain. |
| 2026-08-10 | S7 integration / TQ-26 | The real MCP PostgreSQL paging node passed alone in 29.9 seconds, later passed alone in 53.9 seconds, and timed out under the unchanged 60-second guard in the full conformance lane. PostgreSQL inspection showed `COMMIT` waiting on `IO/WalSync`; the 53.9-second isolated run recorded 14,571 commits for 250 setup sends. | Root cause was transaction-amplifying setup across unrelated behaviors. Public-envelope/real-queue seeding retained the same 250 rows, MCP child, and exact 100/100/50 page/content oracle while reducing the isolated node to 4.43 seconds and 1,572 commits; the four-worker file then passed 7/7 in 6.07 seconds with the original 60-second guard. |
| 2026-08-10 | S7 hosted type-check parity | Exact-SHA run `31439360477` reached the hosted lint job and failed mypy because the workflow checks the root test surface that the earlier project-scoped local commands omitted. It required precise annotations in the new concurrency helpers and stubs for existing `yaml` imports. | Added the annotations plus dev-only `types-PyYAML` and updated the root lock in `d0549d0`; exact root and Summon mypy commands passed locally, and the next hosted lint job passed. No production source or runtime dependency changed. |
| 2026-08-10 | S7 hosted portability | Exact-SHA run `31439636701` failed only `test_attach_forwarding_serializes_with_injection` on macOS 3.13: the fake TUI observed `human\ragent\r` in one PTY read instead of two input events. | The writer contest and exact byte order were correct; the oracle had pinned consumer read chunks to producer writes. The replacement reconstructs and compares the exact pre-detach byte stream, passed 20/20 local repetitions, and retains every original deadline. |
| 2026-08-10 | S7 coverage reconciliation | Exact-SHA run `31440063336` passed the required-path gate. Against the baseline, aggregate coverage declined 0.016 percentage point, Summon 0.052, and core/MCP were unchanged; the comparator identified `_driver.py:768,956` and `watcher.py:963` as the only lost lines. Baseline coverage carried no dynamic test contexts, so their prior exact owners could not be recovered. | Restored the watcher line with a deterministic public manual-turn cleanup owner; removing deferred finalization fails it. A proposed driver no-respawn owner false-greened when both short-circuits were deleted because a replacement can close before publishing evidence, so it was deleted and the two internal lines were explicitly dispositioned. Final exact-SHA comparison remains required. |
| 2026-08-10 | S7 hosted pipe portability | Exact-SHA run `31440063336` filled the real scripted-provider stdin pipe to `BlockingIOError`, then both full-pipe tests failed on Windows 3.12–3.14 when the helper passed that anonymous pipe descriptor to `select()`; Windows 3.11 lacks `os.get_blocking` for the setup. | Removed the redundant socket-only readiness query and capability-skip only runtimes without public nonblocking pipe controls. The deterministic entered-write terminal-action owner remains cross-platform; the real child/full-pipe smoke still runs on POSIX and supported Windows versions with its original join deadlines. |
| 2026-08-10 | S7 final hosted gate | Exact SHA `3e334d171d9d31a5dcb4d6905ba22994206a4e57`, Test run `31441715026`; all 21 jobs passed, including the final coverage job. Artifacts: root/unit 3,751,414 bytes, Summon process 2,335,301, MCP 128,896, local LLM 35,016. The required-path checker passed. Windows 3.12–3.14 ran the real full-pipe proof; Windows 3.11 skipped only its two instances because the runtime lacks public nonblocking pipe controls, while the deterministic entered-write owner ran. | Aggregate: 11,628/12,483, 855 missing, 93.150685% (down 0.008011 point); core: 6,716/7,130, 414 missing, 94.193548% (down 0.014025); Summon: 3,494/3,827, 333 missing, 91.298667% (unchanged); MCP: 1,418/1,526, 108 missing, 92.922674% (unchanged). The only final `LOST` rows were `watcher.py:538–540`, private terminal-stop scheduling cleanup with no supported post-stop observation; all three are dispositioned in the line ledger. Every threshold passed. |
| 2026-08-10 | S7 user-review follow-up / TQ-13a | Temporarily changing `PG_TEST_DEFAULT_WORKERS` from `"4"` to `"auto"` passed the production-derived oracle. Replacing the expected value with the independent literal `"4"` then failed on both real runner command roles; restoring production passed. | The exact command `Counter` now owns shared and PG-only routing, one invocation each, the fixed four-worker default, and `loadgroup`. Focused pytest, Ruff, formatting, docs references, plan status, doc paths, and diff checks passed. |
| 2026-08-10 | S7 follow-up hosted gate | Docs-only run `31443287350` made steady progress to 91% on Windows 3.12 before the job-level 20-minute cap interrupted 1,581 passing tests. Two high-volume unread tests took about 119 seconds each versus 62 seconds in the green run, and another large pagination test had not completed; no individual test failed or hit its own guard. No timeout was changed. Exact SHA `2d87653abd9e9225903185e27bd7565a5917e44a`, run `31444700253`, then passed all 21 jobs, including Windows 3.12 in about 15 minutes. Its four artifacts were root/unit 3,751,493 bytes, Summon process 2,335,367, MCP 128,896, and local LLM 35,013; required paths passed. | The evidence is consistent with host/broker I/O throughput variance in high-volume tests, not a hidden deadlock or reason to enlarge a deadline; no host-level I/O trace was available to prove that inference directly. The current exact comparison is identical to the approved gate: aggregate 11,628/12,483, 93.150685% (down 0.008011 point); core 6,716/7,130, 94.193548% (down 0.014025); Summon 3,494/3,827 and MCP 1,418/1,526 unchanged. `watcher.py:538–540` remain the only `LOST` rows and are already dispositioned. |
| 2026-08-10 | S7 hosted cancellation follow-up / TQ-27 | The MCP non-PG job in run `31446231744` failed only `test_stdio_started_command_cancellation_sends_no_result_and_commits`: after the child committed, the test's fixed 0.5-second sleep expired before the master processed the workspace outcome, so the next public command correctly returned `workspace busy; retry after backoff`. Increasing the fixture delay from 0.3 to 0.8 seconds reproduced the failure locally. | Renamed the owner to match its observable claim and replaced both sleeps with repeated public calls that accept only the exact busy response until success, using a 5-second settle budget within the unchanged 15-second test deadline. The adjacent raw-stdio cancellation owner retains the no-result-on-wire contract. The 0.8-second mutation then passed, the restored test passed 20/20 repetitions, and the complete local non-PG MCP selection passed 245 tests with 7 deselected. No timeout changed. |
| 2026-08-10 | S7 hosted throughput follow-up / TQ-28 | In exact-SHA run `31447098776`, Windows 3.11 and 3.13 reached 1,587 and 1,717 passing tests with no test failures before the unchanged 20-minute action cap interrupted pytest. Windows 3.13 recorded shared paging at 101.55 seconds and the two 1,000-record unread owners at 75.26/75.21 seconds; Windows 3.11 recorded the unread owners at 96.53/95.86 seconds, while shared paging had not completed when the action was canceled. The prior green run showed the same owners in the slow tail at lower host-dependent durations. | Removed unrelated setup amplification: shared paging and the exact 1,000-row limit page now batch-seed public envelopes with one broker timestamp allocation plus explicit monotonic offsets; the one-advance owner uses the minimum multiple records needed to fire its behavior. Exact 100/100/50 and 1/1000 page cardinality, timestamps, one cursor advance, and both numeric boundaries remain. The focused local loop fell from 4.94 to 0.72 seconds. No timeout changed. |

## Review Log

Append plan, slice, and completed-work review dispositions here.

| Date | Scope | Reviewer | Finding | Disposition |
|------|-------|----------|---------|-------------|
| 2026-08-10 | Plan | Independent plan review | Required-path checker ignored `COVERAGE_FILE`. | Adopted: both local and hosted commands pass explicit `--data-file`. |
| 2026-08-10 | Plan | Independent plan review | Coverage baseline omitted the hosted local-LLM producer changed by TQ-19. | Adopted: exact hosted four-artifact capture is authoritative; missing baseline artifact blocks implementation. |
| 2026-08-10 | Plan | Independent plan review | MCP PostgreSQL conformance was not selected by `pytest-pg` defaults. | Adopted: explicit MCP PG conformance commands added to S2b and final gates. |
| 2026-08-10 | Plan | Independent plan review | Audit dispositions had no durable exact node-id ledger. | Adopted: seeded a complete ID-keyed audit ledger with exact owners, contracts, seams, defect injections, and gates. |
| 2026-08-10 | Plan | Independent plan review | Coroutine-local cleanup is a legitimate [MCP-4]/[MCP-10] white-box contract with no public seam. | Adopted with edit: retain sanctioned frame access, scan values rather than local names, and pair it with observable lifecycle outcomes. |
| 2026-08-10 | Plan | Independent plan review | Per-package and lost-line coverage claims lacked executable measurement. | Adopted: exact filtered JSON commands, comparator, thresholds, and seeded line-delta artifact added. |
| 2026-08-10 | Plan | Independent plan review | Core and Summon semantic slices were too broad for safe review. | Adopted: split into S1a-S1c, S2a-S2b, and S4a-S4b with separate gates. |
| 2026-08-10 | Plan | Independent plan review | State lost-update task named no real transaction seam. | Adopted: real held writer transaction plus arrival-only queue proxy specified; SQL and locking remain real. |
| 2026-08-10 | Plan re-review | Independent plan review | S4b named nonexistent generation/restart evidence. | Adopted: use the fixture's existing append-only `start` event with PID; exactly one start plus one complete sentinel chain and a live driver proves no successful recovery generation. |
| 2026-08-10 | Plan final review | Independent plan review | Conditional approval after correcting the S4b fixture path. | Corrected to `extensions/taut_summon/tests/fixtures/local_llm_tui.py::main`; no implementation blocker remains. |
| 2026-08-10 | Core implementation preflight | Independent core review | TQ-03c is an exact [TAUT-6.4] diagnostic; TQ-01/TQ-06 citations and TQ-07c owners were incomplete. | Adopted: retain TQ-03c, correct contract citations, add the omitted private-flag assertions, and include the Summon renderer owner in S1a. |
| 2026-08-10 | MCP/PG implementation preflight | Independent MCP/PG review | TQ-11d used a batch-size change as a red defect even though batch-size independence is desired. | Adopted: red checks now clear the guard, lose the committed prefix, or restore a non-prefix record; batch-size changes must remain green. |
| 2026-08-10 | Summon implementation preflight | Independent Summon review | Activity-consumption, kernel writable-wait entry, and pre-fixture-start process generations were not observable as claimed; the S4a marker filter also deselected TQ-16b. | Adopted: use a test-owned activity acknowledgement, real pipe-full/write-boundary proof, explicitly scope local-LLM evidence to observed post-start generations, and run TQ-16b directly. |
| 2026-08-10 | S1 core slice | Independent Summon reviewer | SQLite-only lost-update owner inherited `shared`; its thread-pool timeout could hang during executor shutdown; DM sets hid duplicates; raw-body scan missed bytes; fallback presence and one test name were incomplete. | Adopted: moved the owner to a sqlite-only module, used a bounded spawned process with adaptive stale-read completion, compared exact sequences, scanned byte-like values, asserted separate fallback positions, and renamed the public API owner. Re-review approved all six fixes; five focused nodes, five concurrency repetitions, Ruff, format, and diff checks passed. |
| 2026-08-10 | S2 MCP/PG slice | Independent core reviewer | Restore fault used private upstream batch size; non-CPython frame absence silently passed; new candidate/counter assertions pinned private representation. | Adopted: observe a real committed prefix from a separate PostgreSQL connection, report an interpreter-scoped skip only after lifecycle assertions, and prove cleanup through public reattachment and tool use. Focused red defects and green gates passed. |
| 2026-08-10 | S3 release/workflow slice | Independent MCP/PG reviewer | Several replacements could still pass on pre-command token injection, missing family versions, duplicate runner/workflow roles, aliased `Queue` imports, unresolved public exports, or stale Ruff-debt totals. | Adopted: test both CLI option positions, complete the four-family wrong-version matrix, use exact multisets and robust option parsing, resolve AST aliases, require every export to resolve, and reconcile the suppression registry. The selected suite passed 100%. |
| 2026-08-10 | S7 pre-landing review | Independent completed-work reviewer | Found pre-call blocked-write and pre-matcher chord snapshots; scope-leaky/incomplete AST flow; missing canonical workflow predicates and release permission owner; raw-segment and contentless-FTS gaps; conflated process startup/DB watchdog; dropped persona backstop concepts; and stale ledger/plan owners. | Adopted all findings. Each replacement received a firing mutation or adversarial fixture; startup and behavior watchdogs are separate; ledger maps all 33 deleted nodes; unrelated user plan files remain excluded. |
| 2026-08-10 | S7 pre-landing re-review | Independent completed-work reviewer | No remaining blocker or major false-green in the 79-row remediation; residual risk is limited to intentionally lightweight static flow analysis for exotic Python aliasing. | Implementation approved. Landing remains gated only by the committed exact-SHA hosted four-artifact coverage comparison and lost-line reconciliation. |
| 2026-08-10 | S7 final evidence review | Independent completed-work reviewer | Verified exact SHA, 21/21 successful jobs, four artifact sizes, required-path output, normalized package totals, exact comparator result, and all final line dispositions; no false coverage claim or missing gate remains. | Approved. The reviewer confirmed `watcher.py:538–540` have no supported post-stop oracle, the candidate driver dispositions should remain, the completed status is justified, and only the test-quality README hunk may be staged. |
| 2026-08-10 | S7 user-review follow-up | User review plus independent completed-work reviewer | The bounded-xdist owner still mirrored the production worker constant; the Invariant 11 type-stub deviation was unlogged; TQ-13a did not name the corrected owner or mutation. | Adopted all findings. The literal oracle has a verified `4 -> auto` red proof; the deviation and hosted mypy evidence are logged; TQ-13a names both the fixed worker/loadgroup contract and defect injection. Independent re-review approved with no remaining blocker. |
| 2026-08-10 | S7 cancellation follow-up / TQ-27 | Independent completed-work reviewer | The fixed sleep was a false synchronization oracle; the first revision overclaimed wire-level no-result behavior, misstated the 15-second deadline, and described an in-progress workflow as complete. | Adopted all findings. Public busy-to-success acknowledgement now owns reservation retirement and exact committed effects; the node name and ledger claim only observable client cancellation, while the adjacent raw-stdio owner retains no-result coverage. Deadlines are unchanged, 20/20 repetitions and the full local MCP lane passed, and independent re-review approved. |
| 2026-08-10 | S7 throughput follow-up / TQ-28 | Independent completed-work reviewer | The first minimization let a `1000 -> 999` clamp pass, conflated the two Windows duration reports, and omitted one ledger path prefix. | Adopted all findings. The exact 1000-row page is restored with one public timestamp allocation plus monotonic offsets; shared 100/100/50 paging uses the same batch seam on real SQLite and PostgreSQL; the one-advance owner uses three records. Evidence wording and all old node IDs are exact. Independent re-review approved with no timeout change. |

## Fresh-Eyes Review Checklist

- [x] Every TQ inventory row maps to an exact task and file owner.
- [x] Every deletion names a green replacement or surviving owner.
- [x] Baseline and final coverage commands use identical selections.
- [x] Aggregate, per-package, required-marker, and lost-line gates are explicit.
- [x] Concurrency tasks name arrival, contested owner, release, and final state.
- [x] No task depends on a sleep, exact incidental timeout, or human prose.
- [x] Real broker, database, process, PTY, protocol, and release seams are named.
- [x] Product defects discovered by stronger tests cannot be hidden by weakening
      the oracle.
- [x] Rollback and stop conditions are executable.
- [x] Independent plan, slice, and final reviews are assigned.
