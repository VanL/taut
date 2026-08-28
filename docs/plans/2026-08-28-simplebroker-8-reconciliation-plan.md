# SimpleBroker 8 Compatibility Reconciliation Plan

Class: 5. The requested dependency floors change the normative compatibility
surface, and SimpleBroker 8 advances the SQL schema and backend API across the
SQLite and PostgreSQL boundaries. The [DOM-5] public-compatibility and storage
format triggers require the hardened rollout, rollback, and review gates below.

Plan type: implementation with spec revision.

Status: completed after implementation verification, independent completed-work
review, and owner-authorized targeted closeout.

## Goal

Raise Taut to `simplebroker>=8.0.0` and `simplebroker-pg>=4.0.0`, refresh every
retained environment, run the existing real SQLite and PostgreSQL contracts,
and make only the compatibility repairs those runs prove necessary. Preserve
Taut's public CLI, Python, JSON, cursor, watcher, persistence, and extension
behavior except for adopting SimpleBroker 8's ascending-public-ID selection
order underneath existing oldest-first Taut surfaces.

## Source Documents

- User request of 2026-08-28: update SimpleBroker/SimpleBroker-PG to
  8.0.0/4.0.0 and isolate and fix compatibility issues.
- User correction of 2026-08-28: do not manufacture a red test merely to make
  the old dependency fail.
- `docs/program-theory.md` [THEORY-1] through [THEORY-4]: the broker substrate
  remains inspectable and SimpleBroker owns durable queue mechanics.
- `docs/specs/02-taut-core.md` [TAUT-3.4], [TAUT-3.5], [TAUT-7.2],
  [TAUT-8.3], [TAUT-8.4], [TAUT-12.1], and [TAUT-12.5].
- `docs/specs/03-identity-addressing-notifications.md` [IAN-8.2].
- `docs/specs/04-summon.md` [SUM-9].
- `docs/specs/08-persistence-io.md` [PIO-4.3], [PIO-7], [PIO-10], and
  [PIO-11].
- `docs/specs/06-search.md` [SRCH-10.1] through [SRCH-10.3]: rotating
  reconciliation owns exact restored IDs below a prior watermark.
- `docs/implementation/04-taut-architecture.md`,
  `docs/implementation/05-taut-summon-architecture.md`, and
  `docs/implementation/10-persistence-io.md`.
- SimpleBroker `v8.0.0` at
  `194dea5bd4841f3c7be36be44f5657e9a20817e1`: `CHANGELOG.md`,
  `docs/specs/13-message-identity.md`,
  `docs/specs/14-timestamp-selection.md`,
  `docs/specs/15-persistence-io.md` [SB-IO-1] through [SB-IO-4],
  `docs/specs/16-python-library-api.md`, and
  `docs/implementation/09-storage-schema-and-claim-lifecycle.md`.
- Repository process consulted before authoring: `AGENTS.md`, the canonical
  startup sequence, program theory, decision hierarchy, principles,
  engineering principles, planning, hardening, testing, review, traceability,
  and adversarial-probe runbooks, the required lessons tier, and the
  diagnosing-bugs and TDD skills.

## Spec Baseline

- Taut baseline: `50eeb947f1530d70ec8ba070c385191e8b4f6336` for the clean
  governing specs named above.
- Upstream baseline:
  `194dea5bd4841f3c7be36be44f5657e9a20817e1` (`v8.0.0`).
- Plan type: implementation with spec revision.
- Promotion strategy: A, in-file text before implementation-link claims. The
  reviewed floor, ordering, and cutover text was intended to precede manifest
  and compatibility work; the timing-only user-directed deviation is recorded
  below. Existing code already cites the stable owning sections; no new code
  citation was added between promotion and reconciliation.
- Promotion baseline: `50eeb947f1530d70ec8ba070c385191e8b4f6336` plus the
  2026-08-28 worktree spec diff recorded in Execution Evidence.

## Current Structure and Key Files

- `pyproject.toml` owns the core runtime floor and root development PG floor.
  `extensions/taut_pg/pyproject.toml` owns the published Taut-PG runtime floor.
- `uv.lock`, `extensions/taut_summon/uv.lock`,
  `extensions/taut_mcp/uv.lock`, and `extensions/taut_tui/uv.lock` are the four
  retained resolved environments. The root manifest is embedded into the
  extension locks, so every retained lock must be refreshed through `uv lock`.
- `README.md`, `CHANGELOG.md`, the governing specs, and implementation notes
  carry current supported-floor or operational-cutover claims. Historical plan
  and released changelog statements remain historical and are not rewritten.
- `taut/client/_messaging.py` uses default `peek_many` and `peek_generator`
  order for unread pages, history, exact-message context, sender-cursor probes,
  and notifications. `taut/client/_searching.py` and `taut/search/_jobs.py`
  advance timestamp cursors through public broker batches. They must continue
  to use public operations, not copy SimpleBroker selection logic.
- `taut/watcher.py` and Summon's reactors rely on SimpleBroker's public watcher,
  stop, retry, activity-waiter, persistent-session, and closeable-iterator
  contracts. These are priority regression surfaces after every floor bump.
- `taut/persistence/_operations.py` passes public `dump_lines()` and
  `load_lines()` streams through a strict Taut composite boundary. The nested
  SimpleBroker dump remains version 1; the SQL schema migration is a target
  migration, not a Taut dump-format change.
- `bin/pytest-pg` is the owner of real PostgreSQL shared and extension proof.
  Do not create a PG lockfile or mock the backend plugin.

Comprehension gates before the spec or manifest edit:

1. What is the v8 ordering change? Expected answer: default bounded and
   generator retrieval is ascending public integer message ID; ordinary
   generated writes remain FIFO-like, while an exact insert, load, or
   ID-preserving move of a lower ID can appear before a row inserted earlier.
2. What is the migration boundary? Expected answer: SQL schema v5 is rebuilt
   or altered transactionally to schema v6 without the private row-order
   surrogate; schema v6 is incompatible with v7 clients and backend API v8
   requires first-party extension major version 4.
3. Who owns migration and selection implementation? Expected answer:
   SimpleBroker and its backend plugin. Taut uses public APIs only, adds no SQL
   against broker-owned tables, and adds no compatibility shim.
4. Does persistence format change? Expected answer: no. SimpleBroker dump v1,
   Taut composite v1, exact string IDs, high-water rules, and Taut sidecar
   records remain unchanged; only the live broker-owned SQL layout migrates.

Execution answers: confirmed from the cited Taut code and SimpleBroker v8
source before plan authoring.

## Invariants and Constraints

- Taut's CLI commands, exit classes, Python types, JSON field shapes, and
  human output do not change.
- Taut keeps one high-water cursor per membership. Existing oldest-unread,
  monotonic advancement, sender catch-up, and no-read-side-fallback rules stay
  intact.
- Existing Taut history/search paths use SimpleBroker's default oldest order.
  Taut does not expose or pass `order="newest"` as part of this upgrade.
- Taut uses only `simplebroker` and `simplebroker.ext` public surfaces and no
  SQL against SimpleBroker-owned objects in production code. The adversarial
  dump race test retains its explicit test-only `simplebroker.db.BrokerDB`
  fault-injection seam while that pinned private surface exists; it is not a
  shipped dependency. A v8 incompatibility is adapted only at an existing
  public production operation or exception boundary.
- SQLite and PostgreSQL stay behaviorally aligned. The real PG plugin and
  database remain live in PG verification; no broker, sidecar, migration,
  dump/load, watcher, or retry behavior is mocked.
- SimpleBroker dump v1 and every Taut persistence component version remain
  unchanged unless an observed incompatibility proves the upstream wire
  contract changed. Such evidence is a stop-and-replan gate, not permission to
  add a permissive reader.
- No new dependency, wrapper layer, retry classifier, dual-version runtime
  path, or speculative refactor is authorized.
- Current-floor prose moves; historical plans, released changelog sections,
  and old-wheel fixtures remain unchanged.
- Fatal evidence: resolver failure, private API requirement, data loss,
  cursor skip under the documented eligible-order contract, migration failure,
  incompatible dump/load, watcher lifecycle regression, or PG/SQLite semantic
  divergence. Existing best-effort notification, debug, and search diagnostics
  retain their current priorities.

## Hidden Couplings, Rollout, Rollback, and One-Way Doors

SimpleBroker 8 removes the SQL row-order surrogate during first current open.
That migration is the one-way operational boundary for an individual target:
v7 clients cannot safely reopen schema v6. Before deployment, stop all v7
Taut, broker, watcher, Summon, and foreign sidecar clients; take a whole-target
backup; install core 8.0.0 with SimpleBroker-PG 4.0.0 wherever PostgreSQL is
used; let one v8 process migrate and verify the target; then restart only v8
clients. PostgreSQL uses its upstream exclusive/advisory migration locks, but
those locks do not turn a mixed-version rolling upgrade into a supported path.

Source rollback before any target is opened is a coordinated revert of specs,
manifests, locks, and current-floor docs. After schema-v6 migration, source
rollback alone is invalid; restore the whole-target pre-upgrade backup before
running v7 code. Taut introduces no downgrade migration. There is no Taut
persistence-format one-way door in this change.

Post-deploy success is positive: clean installs resolve exactly the selected
major pair; existing workspaces open and retain Taut sidecar state; new writes,
bounded reads, log, search, watcher stop, dump/load, and doctor pass; real PG
uses backend API v8 without a handshake or missing-column failure.

## Proposed Spec Delta

### `docs/specs/02-taut-core.md` [TAUT-3.4]

Replace `simplebroker>=7.4.2` as the current load-bearing floor with
`simplebroker>=8.0.0`, retaining the historical capability provenance. Append
this exact text after the 7.4.2 capability sentence:

> Version 8.0.0 makes ascending public message id the uniform default
> retrieval order, removes the private SQL row-order surrogate in schema 6,
> and advances the backend API to v8; `simplebroker-pg>=4.0.0` is the matching
> PostgreSQL line. Ordinary generated writes remain FIFO-like because their ids
> are monotonic. Exact inserts, loads, or id-preserving moves of lower ids are
> selected by public id rather than insertion time. Taut continues to expose
> only oldest selection, now defined as ascending public message id, and uses
> the broker defaults; it does not expose newest-first selection in this
> release.

Append this operational paragraph to the same compatibility item:

> The SQL schema-5 to schema-6 transition is a coordinated downtime cutover,
> not a mixed-version rolling upgrade. Operators stop every v7 client and
> sidecar transaction, take a whole-target backup, install SimpleBroker 8 with
> matching first-party backend major versions, let one v8 process migrate and
> verify the target, and restart only v8 clients. Taut never inspects, migrates,
> or repairs SimpleBroker-owned schema objects itself.

### `docs/specs/02-taut-core.md` [TAUT-7.2]

Replace the sentence `For an explicit thread, the limit bounds the oldest
unread page.` with:

> For an explicit thread, the limit bounds the oldest unread page in ascending
> public message-id order. Among rows eligible above the stored cursor, a lower
> exact id inserted later is selected before a higher id inserted earlier;
> cursor advancement remains the maximum id actually returned.

### `docs/specs/02-taut-core.md` [TAUT-8.3]

Replace the current runtime dependency sentence with:

> Core runtime dependencies: exactly `simplebroker>=8.0.0` and `psutil`. The
> optional `taut-pg` extension adds `simplebroker-pg>=4.0.0` and its driver
> dependencies in the same environment as Taut. Python ≥ 3.11. The CLI uses
> argparse, not a CLI framework.

### `docs/specs/03-identity-addressing-notifications.md` [IAN-8.2]

Replace only the current compatible-pair literals with
`simplebroker>=8.0.0` and `simplebroker-pg>=4.0.0`. Add one sentence after the
existing preserved-capabilities sentence:

> The v8 pair also supplies public-id retrieval order and the coordinated SQL
> schema-6/backend-API-v8 cutover described by [TAUT-3.4]; notification queue
> names, payloads, claim semantics, and fanout remain unchanged.

### `docs/specs/04-summon.md` [SUM-9]

Replace both current repository-wide floor occurrences with
`simplebroker>=8.0.0`, align the paired PG floor to
`simplebroker-pg>=4.0.0`, and append:

> Version 8.0.0 changes default retrieval to ascending public message id and
> advances the SQL/backend compatibility line without changing Summon's fixed
> control topology, read-one command consumption, watcher lifecycle, retry
> ownership, or closeable-iterator cleanup contract.

### Related-plan backlinks

Add this plan to the `## Related Plans` section of the three changed specs.
No [PIO-*] text changes: its nested dump v1 identity and ordering contract is
already the v8 contract and is verified rather than restated.

## Testing Strategy

The existing real integration suite is the feedback loop. The targeted
SQLite command run below passed under the retained 7.4.2 lock before any edit;
after lock refresh, it is rerun against 8.0.0 and is red-capable for actual
public Taut regressions:

```text
uv run --extra dev pytest -q tests/test_client.py tests/test_shared_contract.py tests/test_search_client.py tests/test_persistence_io.py
```

Per the user's explicit correction, do not add an artificial test whose only
purpose is to fail under 7.4.2. For each observed post-upgrade failure: capture
the exact symptom, minimize it with the narrowest existing test, rank and test
falsifiable hypotheses, and add a regression before the code fix only when the
existing failing contract does not pin the incompatibility precisely. The
dependency-only floor and lock edits use the substitute proof of resolver
output plus existing-suite before/after comparison; this exception is explicit
rather than a silent TDD skip.

## Tasks

1. Independently review this plan and exact spec delta.
   - Reviewer reads the upstream v8 tag, Taut specs, current manifests/locks,
     key public call sites, and test commands.
   - Stop on an unaccounted public API, migration, dump-format, or mixed-version
     claim.
   - Done when every finding is reproduced and dispositioned in the Review Log.

2. Promote the reviewed spec delta.
   - Edit only the exact current-floor, eligible-order, cutover, and backlink
     paragraphs in specs 02, 03, and 04.
   - Record the promotion baseline and run focused doc-reference/path gates.
   - Stop if the promoted claim differs from SimpleBroker v8 source.

3. Refresh manifests and all retained locks.
   - Change root runtime/dev and Taut-PG runtime floors.
   - Upgrade both packages at the root and MCP projects; upgrade SimpleBroker
     alone in the Summon and TUI projects, whose graphs do not contain the PG
     package. Do not hand-edit lock package records.
   - Inspect every resolved version and embedded `requires-dist` entry.
   - Stop on unrelated first-party version drift or an incompatible package
     pairing.

4. Run the existing compatibility feedback loops and isolate real failures.
   - Start with the targeted SQLite command above plus
     `tests/test_persistence_io_adversarial.py`, then root non-slow tests,
     extension suites, watcher/reactor-focused tests, and real PG via
     `uv run ./bin/pytest-pg --fast`.
   - Handle each actual failure vertically: reproduce, minimize, hypothesize,
     repair at the existing public boundary, rerun the original scenario.
   - Do not clone upstream ordering, schema, retry, or watcher code into Taut.

5. Reconcile current documentation and traceability.
   - Update README current dependency claims and add the schema-v6 downtime
     cutover where users select PostgreSQL or reuse an existing SQLite target.
   - Reconcile the Unreleased dependency entry rather than preserving 7.4.2 as
     a second current floor.
   - Update implementation docs 04, 05, and 10 with the v8 ownership and
     unchanged dump-format rationale.
   - Scan every retained current-floor literal; classify remaining old values
     as historical or a defect.

6. Run final gates and independent completed-work review.
   - Run the exact commands below from the current worktree.
   - Reconcile every review finding, deviation, task, and evidence line.
   - Mark the status-index row completed only when all in-scope gates are green
     or a precise environment blocker is recorded.

## Verification and Gates

Per-task gates:

- `uv run pytest -q tests/test_docs_references.py`
- `uv run bin/check-doc-paths`
- the targeted SQLite feedback loop above
- `uv run pytest -q tests/test_project_metadata_consistency.py`
- `uv run ./bin/pytest-pg --fast`

Final gates:

- `uv run --extra dev pytest`
- the owned non-slow Summon, MCP, and TUI suites using their retained projects
- the Ruff check/format commands and four mypy owners documented in README
  Development
- `uv run bin/check-cli-claims`
- `uv run bin/check-doc-paths`
- `uv run bin/check-plan-status-index`
- `uv run bin/coalesce-check` (report the separate maintenance trip; do not
  fold it into this product change)
- package metadata inspection proving SimpleBroker 8.0.0 and
  SimpleBroker-PG 4.0.0 in every applicable retained lock
- independent completed-work review against the upstream tag, promoted specs,
  plan, implementation notes, touched files, and current verification output

## Independent Review Loop

Use a separate read-only agent. First existence-check every named path,
version, command, API seam, and upstream migration claim. Then answer PASS or
BLOCKED on whether the plan/work can be implemented confidently without
degrading Taut. Findings are claims: reproduce each before accepting it. Record
every disposition here and use a scoped round two for accepted fixes.

## Out of Scope

- Exposing SimpleBroker's `order="newest"` or CLI `--newest` through Taut.
- Supporting mixed v7/v8 clients, adding a downgrade migration, or inspecting
  broker-owned schema from Taut.
- Redis state support, release publication, package version bumps, or release
  machinery changes.
- The unrelated semantic-compatibility hardening draft and its owner-gated
  spec proposals.
- The separate lessons/plan coalescing maintenance unit.

## Deviation Log

| Spec ref | Planned behavior | Actual behavior | Rationale | Spec proposal |
|----------|------------------|-----------------|-----------|---------------|
| [TAUT-3.4], [TAUT-7.2], [TAUT-8.3], [IAN-8.2], [SUM-9] | Promote the reviewed spec delta before manifest and compatibility edits. | The user explicitly narrowed execution to update and run tests while independent plan review was in flight, so manifest refresh and the two test-proven compatibility repairs preceded spec promotion. The reviewed text was then promoted unchanged before final verification. | Timing only. The implementation did not define a different contract, and review returned PASS before promotion. | Incorporated in the cited spec sections on 2026-08-28. |

## Review Log

- 2026-08-28 independent read-only review: PASS, no blocker.
- P2 accepted: added [SRCH-10.1]–[SRCH-10.3] and upstream [SB-IO-1]–[SB-IO-4]
  as direct source owners.
- P2 accepted: qualified the public-import rule as a production boundary,
  recorded the existing adversarial test's private `BrokerDB` fault seam, and
  added that test to the early persistence run.
- P3 accepted: replaced ambiguous “existing oldest-first behavior” wording
  with “only oldest selection, now defined as ascending public message id.”
- 2026-08-28 independent completed-work review: PASS, no compatibility blocker
  or missing required test.
- P3 accepted: reconciled the stale pending promotion baseline with the
  recorded promotion evidence.
- P3 accepted: documented the SQLite initialization diagnostic boundary in the
  core architecture note.

## Execution Evidence

- Baseline targeted SQLite suite under retained SimpleBroker 7.4.2:
  `uv run --extra dev pytest -q tests/test_client.py
  tests/test_shared_contract.py tests/test_search_client.py
  tests/test_persistence_io.py` passed on 2026-08-28.
- Promotion baseline: `50eeb947f1530d70ec8ba070c385191e8b4f6336` plus the
  2026-08-28 worktree spec diff in [TAUT-3.4], [TAUT-7.2], [TAUT-8.3],
  [IAN-8.2], and [SUM-9]. The promoted text matches the independently reviewed
  proposed delta.
- Resolver and package evidence: root and MCP retain SimpleBroker 8.0.0 plus
  SimpleBroker-PG 4.0.0; Summon and TUI retain SimpleBroker 8.0.0. Installed
  metadata and built core/Taut-PG wheels expose floors 8.0.0/4.0.0. All five
  distributions build successfully, and all four retained `uv lock --check`
  commands pass.
- The post-upgrade targeted SQLite/persistence suite, including
  `tests/test_persistence_io_adversarial.py`, passes. It exposed one invalid
  test fixture: `test_resolved_target_config_handoff_bypasses_ambient_resolution`
  injected SQLite `backend_options` that SimpleBroker 8 correctly rejects.
  Moving the mutation after construction retains the intended snapshot proof
  without relying on unsupported input.
- The full root suite exposed one product regression: corrupt SQLite input lost
  the selected path when SimpleBroker 8 wrapped the database error. Taut now
  restores that path at its public schema-initialization boundary without
  parsing upstream text or changing PostgreSQL errors. The isolated CLI probe
  and targeted client contract pass.
- Final exact root suite: 2,243 passed, 1 skipped, and only
  `tests/test_ruff_policy.py::test_raw_active_rule_inventory_and_registry_are_exact`
  failed. A clean archive of `HEAD` under the same Ruff 0.16.3 reports the
  identical raw counts (BLE001 148 and C901 39 versus stale expected 144 and
  38), proving the sentinel drift predates and is independent of this change.
  Normal Ruff checks and formatting pass; no baseline count was changed.
- Real PostgreSQL proof: `uv run ./bin/pytest-pg --fast` passed 313 shared
  tests and 37 PG-only tests with the real SimpleBroker-PG 4.0.0 plugin.
  Extension proof passed: Summon 684 with 4 expected platform/service skips;
  MCP 289 with 7 expected local-PG skips; TUI 425.
- All four documented mypy owner runs pass. CLI claims, documentation paths
  and references, metadata consistency, plan-status indexing, and normal Ruff
  checks/formatting pass.
- The existing 2026-07-28 lesson about dependency floors changing control flow
  directly covers both observed issues. No distinct durable lesson is owed.
- Session-start `uv run bin/coalesce-check`: all cues resolve; 82 total dated
  lessons, 34 past the 2026-07-14 watermark. This changed from the recorded 33
  and the date-floor reconsideration fired; maintenance remains out of scope.
