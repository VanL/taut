# Actor-Free System Doctor Plan

Date: 2026-08-10

Status: completed after implementation, cross-backend verification,
independent final review, and owner-authorized close-out

Class: 5 — adds a public actor-free maintenance command, Python API, report
schema, JSON contract, exit semantics, and a new canonical specification. It
adds no durable schema and performs no repair.

Baseline: `50a67eb9e541` (`Adopt SimpleBroker 7 JSON message ID boundaries`).
Execution rebase: `68222d2` (`Record stable DM review evidence`). The relevant
doctor implementation seams are unchanged from the authoring baseline; current
spec text also includes the later stable-DM and MCP-search contracts and is the
promotion edit base.

## Goal

Add one bounded `taut system doctor` operation that reports Taut-owned durable
state and operational evidence without constructing an identity-bearing client
or changing chat state. It must help a human or agent distinguish an observable
workspace finding from an invocation/tool failure. It must never imply that the
workspace is quiescent, that no other process is attached, that dump/load is
safe, or that the storage engine is exhaustively healthy.

The first version is deliberately one command. A separate `status` command,
repair mode, process census, or generic diagnostics extension point requires a
later contract based on demonstrated need.

## Source Documents

- `README.md`, especially Maintenance, product boundaries, and agent use
- `docs/program-theory.md`, especially THEORY-2, THEORY-3, THEORY-5 A6, and
  THEORY-6
- `docs/specs/product-section-registry.md`
- `docs/specs/00-specs-index.md`
- `docs/specs/01-development-documentation-operating-model.md` [DOM-5],
  [DOM-10], [DOM-15]
- `docs/specs/02-taut-core.md` [TAUT-2], [TAUT-3.1]–[TAUT-3.4], [TAUT-8.1]–
  [TAUT-8.3], [TAUT-8.6], [TAUT-9]–[TAUT-12]
- `docs/specs/06-search.md` [SRCH-6]–[SRCH-12]
- `docs/specs/08-persistence-io.md` [PIO-1]–[PIO-3], [PIO-5], [PIO-7],
  [PIO-8], [PIO-10], [PIO-11]
- `docs/implementation/04-taut-architecture.md`
- `docs/implementation/09-search-architecture.md`
- `docs/implementation/10-persistence-io.md`
- `docs/agent-context/runbooks/writing-plans.md`
- `docs/agent-context/runbooks/hardening-plans.md`
- `docs/agent-context/runbooks/testing-patterns.md`
- `docs/agent-context/runbooks/adversarial-acceptance-probes.md`

## Current Structure and Key Files

- `taut/commands/system.py` owns the reserved nested maintenance grammar. It
  rejects `--as`, `--token`, and `--timestamps`, then calls actor-free
  `TautClient.dump`/`load` class operations without `context.client()`.
- `taut/persistence/_operations.py:_resolve_source` already resolves an existing
  SQLite or configured backend target without creating a missing SQLite file.
  Doctor should reuse a small shared extraction, not import persistence-private
  orchestration or invent another config parser.
- `taut/client/_base.py` is forbidden for doctor orchestration: constructing an
  ordinary `TautClient` calls `ensure_schema`, may write activity, and violates
  the passive diagnostic boundary.
- `taut/state/_sql.py` is the sole owner of production core sidecar SQL. It has
  read-only projections and schema-version access, but most state objects assume
  the schema already exists. Doctor needs a read-only inspection seam that turns
  missing/malformed/newer state into report checks without `ensure_schema`.
- `taut/persistence/_format.py` and `_operations.py` already validate logical
  core records and extension contributor records during dump/load preflight.
  Extract the live/dump-neutral validator rather than fork structural rules.
- `taut/persistence/_components.py` owns persistence contributor discovery and
  manifest/schema-key ownership. Doctor may call read-only export and validation
  on active contributors. The existing `load_versions` manifest field describes
  dump-component format versions, not live schema versions, so it must not be
  reused for live compatibility. Add one doctor-selected read-only contributor
  method, `validate_live_schema(queue)`, without changing dump/load discovery or
  compatibility. An active installed contributor that lacks this method is an
  `extension_state` finding with an upgrade direction. Doctor may never call
  contributor `ensure_schema`, `is_fresh`, or `load_records`.
- `taut/search/_jobs.py` owns the three durable work-queue names. Doctor may
  inspect their public queue depths. It may not load a search provider, ensure
  search schema, inspect a physical FTS/tsvector index, reclaim work, or rebuild.
- `taut/client/_models.py`, the public client/root export modules, command
  rendering, and public API tests own new report values.
- `extensions/taut_pg` needs real acceptance tests but no backend-specific doctor
  code and no PostgreSQL server extension.

Every named path exists at the baseline. If portable passive observation cannot
be expressed through current public broker/sidecar seams, stop and revise the
boundary. Do not put SQLite or PostgreSQL SQL in command/orchestration code.

## Mental Model

Doctor is a sequence of bounded observations, not one global snapshot. Each
check answers a named narrow question at approximately the time it ran. A
concurrent writer can make the combined report mixed or stale immediately.

`healthy=true` means only: every specified observation completed and met its
specified expectation. It does not mean:

- no writer, watcher, Summon driver, raw DB client, or other process exists;
- every handle is closed, this is the last connection, or a destructive
  operation is safe;
- a lock/timeout would be obtainable, or no future write can race;
- search is fully caught up or every physical index row is correct;
- every broker message is Taut-authored or decodable;
- SQLite/PostgreSQL physical integrity, permissions, capacity, backup policy,
  security, or retention is exhaustively valid.

This is the direct application of program-theory alternative A6. Taut must not
repeat the cross-process correctness argument for a destructive operation by
inventing a weak connection census, PID scan, lock probe, or timeout heuristic.

## Invariants and Constraints

1. **Actor-free.** CLI accepts only the `system` globals `--db`, `--json`, and
   `--quiet`. The Python surface is a class operation. No member selection,
   identity capture, claim healing, activity, cursor, notice, inbox, or chat
   operation occurs.
2. **Report-only.** Doctor never initializes or migrates core/extension/search
   schema, clears a load guard, resumes a rename, creates a queue, reclaims work,
   drains or rebuilds search, changes a cursor, or repairs any inconsistency.
3. **No process or connection census.** Do not use `ps`, `/proc`, PID/anchor
   liveness, SQLite connection enumeration, PG activity catalogs, exclusive
   lock attempts, busy-time heuristics, or “last handle” claims.
4. **No dump/load safety claim.** A passing report is not a precondition or
   certificate for persistence I/O. The operator still follows [PIO-7]'s stop-
   writers requirement.
5. **No fake queue-divergence detection.** SimpleBroker does not durably
   distinguish an empty registered queue from a deleted or never-populated one.
   Doctor may report registered thread count and observable stats, but must not
   label a missing stat row as corruption.
6. **No physical search probe.** The index is disposable and backend-native.
   Provider import/ensure or index parity checks would mutate state or create
   asymmetric false confidence. The functional check and repair path remains
   `taut search`.
7. **Optional PG optimization stays optional.** No compiled or non-built-in
   PostgreSQL server extension becomes required. Doctor reports only Taut's
   portable contract.
8. **No secrets or participant bodies.** The target uses the broker's display-
   safe form. Reports contain counts, stable check codes, safe summaries, and
   bounded identifiers only where needed for remediation. They never emit a
   token, DSN password, raw SQL, message body, or notification payload.
9. **Logical non-mutation is the enforceable promise.** Public broker setup may
   perform idempotent backend setup. Doctor guarantees no Taut domain mutation
   or repair on an initialized workspace and proves stable logical/table/queue
   state. It does not promise byte-for-byte storage immutability absent an
   upstream read-only connection API.
10. **All Taut-opened handles close.** Every path uses scoped/finally ownership,
    including check failure and renderer/broken-pipe failure. This is resource
    hygiene, not proof that no other process has a handle.
11. **Real seams stay real.** Acceptance must not mock SimpleBroker, sidecar
    SQL, persistence contributor state, search work queues, or PostgreSQL.
    Tripwires may prove forbidden identity/provider/process calls are absent.

## Proposed Public Contract

### CLI

```text
taut [--db TARGET] [--json] [--quiet] system doctor
```

`--as`, `--token`, and `--timestamps` are usage errors before or after the verb.
The command has no flags in v1. Human output emits one terminal-escaped line per
check in fixed order, then `workspace healthy` or `workspace has findings`.
`--quiet` suppresses output but preserves the exit status.

Exit codes deliberately specialize the project convention:

- `0`: a complete report and every check passed;
- `1`: usage, target resolution/access, or inspection-framework failure that
  prevented a complete report;
- `2`: a complete report contains at least one `fail` or dependency `skip`.

This exception is required by the adversarial-probe rule that “findings exist”
and “the invocation/tool failed” must be distinct. It is scoped to `doctor` and
must be named in root and system help; existing commands keep exit 2 as their
empty/not-found class.

### Python values

Add frozen, slotted public values:

```python
DoctorCheck(
    name: str,
    status: Literal["pass", "fail", "skip"],
    detail: str,
    data: dict[str, object],
)

DoctorReport(
    db: str,
    healthy: bool,
    checks: tuple[DoctorCheck, ...],
)
```

And the actor-free operation:

```python
TautClient.doctor(*, db_path: str | Path | None = None) -> DoctorReport
```

`detail` is safe human diagnostic text, not a parsing contract. Check names,
order, status vocabulary, and each check's `data` keys/types are stable. The
method returns reports with findings. It raises only when target resolution,
access, or the inspection framework cannot produce the complete fixed report.
Every check keeps its exact data keys on `pass`, `fail`, and `skip`. A value
that could not be observed because the check or its prerequisite failed is
`null`; a valid observed empty count remains integer zero and a valid observed
empty collection remains empty. This prevents dependency skips from looking
like healthy empty state.

### JSON

Exact top-level shape:

```json
{
  "checks": [
    {
      "data": {"version": 2},
      "detail": "current core schema is readable",
      "name": "core_schema",
      "status": "pass"
    }
  ],
  "db": "/workspace/.taut.db",
  "healthy": true,
  "type": "system_doctor"
}
```

JSON uses UTF-8 NDJSON with one aggregate object, sorted keys under existing
rendering policy, and no integer message IDs.

## Fixed Check Inventory

Checks run in this exact order. A failed prerequisite yields `skip` for a
dependent check rather than a fabricated secondary diagnosis. Any `fail` or
`skip` sets `healthy=false` and CLI exit 2.

### 1. `core_schema`

Read `taut_meta`, validate the current core schema version, and issue read-only
projections against every required core table. Do not call `ensure_schema`.
Missing, older, newer, malformed, or unqueryable schema fails.

Stable data keys:

```json
{"version": 2}
```

On missing/malformed version, `version` is null. The literal expected version
is taken from the implementation constant and spec at promotion time rather
than hard-coded from this example if the baseline changes.

### 2. `load_guard`

Report whether the core load guard exists. Presence fails with the existing
recreate-target recovery direction and is never cleared.

```json
{"present": false}
```

This check skips only if `core_schema` could not read metadata.

### 3. `core_state`

Project canonical logical core records and run the same dump-neutral record and
cross-reference validator used by persistence preflight. This covers malformed
members, aliases, claims, threads/topics/DM pairs, memberships, dangling
references, and rename markers. An incomplete rename fails and names the
existing resume command without applying it. No message body scan occurs.

```json
{
  "aliases": 0,
  "completed_renames": 0,
  "identity_claims": 2,
  "members": 3,
  "memberships": 5,
  "threads": 4
}
```

All six integer keys are always present, using zero when a valid projection has
none. The validator is extracted into a shared internal helper; doctor does not
emit dump-file line-number language for live state.

### 4. `broker_state`

Using public SimpleBroker metadata/stats only, total pending and claimed rows
for the validated registered thread names. Claims are observable facts and may
be legitimate. Foreign/unregistered queues and aliases are permitted and are
not reported as Taut corruption.

```json
{
  "claimed": 0,
  "observed_nonempty_queues": 2,
  "pending": 42,
  "registered_threads": 4
}
```

The check passes when observation succeeds. It never compares
`observed_nonempty_queues` with `registered_threads` as an integrity rule.

### 5. `extension_state`

Discover persistence contributors and map their declared schema keys. Ignore
core `schema_version` and `load_guard`. Fail on malformed/duplicate manifests,
unknown durable metadata keys, an active contributor whose installed reader
does not support the stored version, read-only export failure, or invalid
exported/cross-referenced records. An installed but unused contributor remains
inactive and uninitialized.

For active contributors call only current read-only `validate_live_schema`,
`dump_records`, and `validate_records`; never call `ensure_schema`, `is_fresh`,
or `load_records`. A missing `validate_live_schema` method or a compatibility
rejection from it is an `extension_state` `fail` with an upgrade direction, not
an inspection-framework exception that aborts the fixed report. Contributor
discovery necessarily imports installed trusted modules and calls their
factories, as dump/load already do. That in-process import is not a claim of
arbitrary-code side-effect freedom; the contract is that doctor invokes no
contributor workspace mutation method.

```json
{
  "active": ["taut-summon"],
  "installed": ["taut-summon"],
  "records": {"taut-summon": 1}
}
```

Names are Unicode-code-point sorted. `records` has exactly the active names as
keys. An absent Summon schema remains absent after doctor.

### 6. `search_work`

Read public stats for the exact `taut.search_index`,
`taut.search_index.claimed`, and `taut.search_index.failed` queues without
creating, moving, decoding, deleting, or reclaiming records.

```json
{"claimed": 0, "failed": 0, "pending": 0}
```

Each value is the public `QueueStats.total` for the correspondingly named queue
(missing from the stats list means zero). Thus `claimed` means durable rows in
the search claimed-work queue, not SimpleBroker's internal claimed count for
the pending queue; nested broker claim state is included in that queue's total.
Pending and claimed depth are informational and pass. A nonzero failed depth is
an actionable finding and fails this check because [SRCH-8.2]/[SRCH-9]
quarantine work
there without automatic retry. The report does not infer expiration, index
completeness, or provider availability from these counts.

## Spec Baseline

- Authoring baseline: `50a67eb9e541`.
- Execution/promotion diff base: `68222d2`. The worktree already contains the
  uncommitted plan, its active status-index row, and unrelated Summon/MCP lockfile
  changes. Promotion verification and the recorded promotion identifier must use
  this diff base plus the explicit spec-file diff; no lockfile belongs to this
  unit.
- Promoted worktree contract identifier: SHA-256
  `8d271e0f580f4bd81472ea9d636e460dff342ab907f4dfac46e7398da6967b73`
  over the tracked README/spec/gate diff from `68222d2` plus the complete new
  `docs/specs/09-system-doctor.md`. Promotion gates: 26 docs-reference and CLI-
  claim tests passed on 2026-08-11.

- [TAUT-8.1] says `system` requires `dump` or `load` and explicitly implements
  no `status` or `doctor`.
- [TAUT-10] says a future doctor may report registry/queue divergence, but the
  current public broker model cannot distinguish a valid empty registered
  thread from a missing queue.
- [PIO-1] reserves `system` for actor-free maintenance while intentionally
  defining only dump/load.
- [PIO-7.4] already rejects process counting, last-connection proof, and weak
  lock/census substitutes for quiescence.
- [SRCH-9] defines pending/claimed/failed work and quarantine, but no diagnostic
  surface.
- No canonical concern row owns system diagnostics today.

## Proposed Spec Delta

### D1 — New canonical specification

Create `docs/specs/09-system-doctor.md` with:

- [DOCT-1] purpose, actor-free owner model, and bounded-observation mental model;
- [DOCT-2] non-mutation, no repair, no census, no quiescence/dump-safety claim,
  logical-versus-physical write boundary, handle ownership, and secret policy;
- [DOCT-3] exact CLI, public values/API, JSON, human/quiet rendering, and 0/1/2
  exit contract above;
- [DOCT-4] exact ordered checks, statuses, data fields, dependency skips, and
  `healthy` derivation above;
- [DOCT-5] persistence contributor and search/provider boundaries;
- [DOCT-6] limitations and failure/recovery semantics;
- [DOCT-7] real SQLite/PostgreSQL, extension, no-repair, closure, CLI, and
  adversarial verification requirements;
- implementation mapping and related plan.

[DOCT-4] must state that a check's observed target state may yield `fail`, while
an access/observation/framework exception that prevents completion of the fixed
report raises and maps to exit 1. Such an exception never becomes a `fail` or
`skip` record in a report that could be mistaken for complete.

### D2 — Core and namespace integration

Amend [TAUT-8.1] to require `dump`, `load`, or `doctor`, list the exact doctor
grammar, and name its scoped exit-2 findings meaning. Amend [TAUT-8.2]/[TAUT-8.3]
for the report JSON and public class operation. Amend [TAUT-8.6] to keep
`system` core-owned and non-extensible while contributors remain persistence-
state inputs only.

Replace [TAUT-10]'s broad future divergence sentence with the truthful rule:

> Doctor may validate Taut registry structure and report observable broker
> counts. It cannot distinguish an intentionally empty registered queue from a
> deleted or never-populated broker queue and does not claim general
> registry/queue divergence detection.

### D3 — Persistence and search cross-references

Amend [PIO-1]/[PIO-3] so dump/load remain governed by spec 08 and doctor is
governed by [DOCT-*]. Reuse of contributor discovery/export/validation is
read-only and never invokes contributor schema initialization. Amend [PIO-8.2]
to define `validate_live_schema(queue)` as a doctor-selected, read-only
compatibility check for an active contributor. It is separate from
`load_versions`, which remains the dump-component format contract; it does not
change dump/load compatibility or create extension-contributed diagnostic
checks. A contributor without the passive method remains usable for dump/load
but produces an `extension_state` finding when doctor observes its active schema.
[PIO-7.4]'s quiescence refusal applies unchanged; doctor is not a substitute.

Add a [SRCH-12] doctor paragraph: it reports the three work-queue depths only;
failed depth is a finding; it does not load a provider, inspect or initialize a
physical index, infer caught-up state, reclaim, or rebuild.

### D4 — Documentation authority

Add spec 09 to `docs/specs/00-specs-index.md`. Add a `System diagnostics`
`canonical-spec` row in `docs/specs/product-section-registry.md` owned by
[DOCT-1]–[DOCT-7]. Run the two-way README promise audit, then update README
Maintenance/CLI/API restatements. Program theory needs no change because A6
already owns the rejected alternatives.

## Promotion Strategy

Use strategy C: create a new active spec because system diagnostics is a new
non-overlapping concern family, then make the companion amendments and registry
row atomically. The spec-promotion commit contains no production code. It must
pass independent semantic review before implementation starts.

## Dependency-Ordered Tasks

### S0 — Baseline and RED public contract

1. Reconfirm target-resolution, passive SQL, contributor, queue-stat, renderer,
   public-export, and PG harness surfaces.
2. Run existing system dump/load, persistence, search-job, extension, CLI, and
   PG focused tests.
3. Add failing public-model/API/CLI/schema tests for the exact six-check healthy
   report, JSON, globals, quiet mode, and exit classes.
4. Promote D1–D4 after independent review.

### S1 — Shared passive target and core inspection

1. Extract existing-source resolution from persistence into a small internal
   maintenance helper with behavior-pinning tests. Missing SQLite must not
   create a file; server targets use display-safe labels.
2. Add sidecar-owner read-only schema/meta/table projections in
   `taut/state/_sql.py`. Do not call `ensure_schema`.
3. Extract persistence's logical core validator into a dump/live-neutral helper.
4. Implement `core_schema`, `load_guard`, and `core_state`, including skip
   dependency behavior.

Done signal: healthy/current and every missing/old/new/malformed/guard/core-
corruption fixture produces the exact report while logical state is unchanged.

### S2 — Broker, extension, and search observations

1. Implement `broker_state` through public broker stats only and pin the empty-
   queue non-inference.
2. Implement `extension_state` with discovery, passive live-schema compatibility,
   and read-only export/validation; add tripwires against every mutating
   contributor method. Update the current Summon contributor with
   `validate_live_schema(queue)`; do not reinterpret `load_versions`.
3. Implement `search_work` with public stats for the fixed queues and no
   provider import/ensure.
4. Aggregate fixed-order checks and map fail/skip to `healthy=false`.

Done signal: active and inactive Summon, an active contributor missing passive
live-schema inspection, unknown metadata, normal search backlog, failed work,
and empty registered threads all report truthfully without mutation.

### S3 — Public API, CLI, and rendering

1. Add frozen/slotted values and exact public exports.
2. Add `TautClient.doctor` as a class operation that delegates to the actor-free
   orchestrator without constructing a client instance.
3. Add the `doctor` system subparser, option rejection, JSON/human/quiet
   rendering, and exit mapping.
4. Ensure terminal escaping, broken-pipe behavior, and handle closure on every
   render/error path.

### S4 — Real backend and no-repair proof

Run the full six checks on real SQLite and PostgreSQL. Seed load guards, unknown
extension metadata, active Summon records, failed search work, incomplete
rename, malformed core references, and empty threads. Compare canonical core
records, metadata, schema-object inventory, pending/claimed message identities,
registry/cursors, extension rows, and search work before/after. This is a
logical-state comparison, not a bytewise database/file or vacuum-volatile
physical-row assertion. No `taut_pg` production code or PostgreSQL server
extension may be added.

### S5 — Documentation and traceability closure

Create `docs/implementation/11-system-doctor.md` explaining the bounded
observation model, shared validator, non-mutation seams, provider refusal,
resource ownership, and traceability. Update repository/implementation indexes,
README, CHANGELOG, help snapshots, public API inventory, and Related Plans. Run
the two-way promise audit and record all deviations below before final review.

## Testing Plan

Required firing matrix:

| Check/surface | Healthy | Fail | Skip/dependency | No mutation |
|---------------|---------|------|-----------------|-------------|
| `core_schema` | current | missing/old/new/malformed/unqueryable | n/a | no schema creation/migration |
| `load_guard` | absent | present | unreadable meta | never clear |
| `core_state` | canonical rows | malformed topic/DM/reference/incomplete rename | schema fail | never repair/resume |
| `broker_state` | stats readable | observable invalid target state, if any is added by spec | core projection fail | access/framework failure aborts the report with exit 1; no queue create/claim |
| `extension_state` | none + active Summon | malformed/duplicate/unknown/unsupported/missing passive schema method/invalid export | core IDs unavailable | no ensure/fresh/load |
| `search_work` | empty/pending/claimed | failed depth | n/a | broker access/framework failure aborts the report with exit 1; no provider/move/reclaim |
| CLI/API | exact report | target/invocation exit 1 | findings exit 2 | no identity client |

Every stable name, status, data key, exit code, and prohibited global receives a
firing test. Real corruption fixtures must inspect post-state, not merely the
returned wording. A nonexistent SQLite target must remain nonexistent.

## Verification and Gates

Expected commands, reconfirmed at implementation time:

```bash
uv run pytest tests/test_system_doctor.py tests/test_persistence_io.py \
  tests/test_persistence_io_adversarial.py tests/test_search_jobs.py \
  tests/test_cli.py tests/test_command_registry.py tests/test_public_api.py -n 0
uv run pytest extensions/taut_summon/tests -n 0
uv run ./bin/pytest-pg --fast
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest -n auto
bin/check-plan-status-index
```

Apply the adversarial CLI floor: globals before/after verbs, actor/timestamp
rejection, missing/extra/unknown operations, unreadable/nonexistent target,
malformed config, JSON/quiet, terminal controls in safe details, stdout/stderr
closure, broken pipe, interruption, and a forced mid-check exception that exits
1 rather than masquerading as a findings report.

## Rollout, Rollback, and Success Signals

This is additive and schema-free. There is no dump-format, provider-interface,
or durable migration. Rollback removes the command, report types, orchestrator,
spec row, and docs; stored workspaces remain unchanged. Once released, removing
the command is an API break, so fix forward is preferred.

Post-release signals:

- healthy SQLite and PostgreSQL fixtures return the exact report and exit 0;
- seeded findings return a complete structured report and exit 2;
- invocation/framework failures exit 1 and never look like health findings;
- before/after logical snapshots and schema inventories match;
- inactive Summon/search schemas are not created;
- no output claims quiescence, process count, last connection, dump safety, or
  general empty-queue divergence detection;
- every Taut-owned handle closes under success, check failure, and render
  failure, without claiming anything about foreign handles.

## Independent Review Loop

Before promotion, run a read-only Opus review over this whole plan, program-
theory A6, [TAUT-8]/[TAUT-10], [PIO-7], [SRCH-8]–[SRCH-12], persistence
contributor code, state SQL, search jobs, and `system.py`. Require `PASS` or
`BLOCKED` with P1/P2 findings. Ask the reviewer to challenge every health claim,
exit-code distinction, dependency skip, data-field stability, secret/body leak,
mutation path, extension initializer, provider probe, empty-queue inference,
backend-specific branch, and handle-closure path. Repeat after material edits,
after S2, and before completion.

## Out of Scope

- `status`, `--watch`, `--repair`, `--fix`, `--force`, cleanup, migration,
  automatic recovery, or placeholders for future system operations;
- process/connection census, PID/lease checks, quiescence certification, locks,
  timeouts, dump/load preflight, or backup safety;
- SQLite `PRAGMA integrity_check`, PostgreSQL catalogs/activity, backend capacity,
  credentials, permissions, security posture, retention, or policy audit;
- message-history/body scans, foreign queue policing, alias policing, general
  broker administration, or exact empty-queue divergence detection;
- physical search-index inspection/parity, provider capability probing, caught-
  up claims, reclaim, retry, or rebuild;
- a generic diagnostics plugin API or extension-contributed check registry;
- any required compiled PostgreSQL extension.

## Counterarguments and Decisions

**Why not process/connection detection?** SQLite and the OS can expose some
local process or file-handle evidence, and PostgreSQL can expose sessions, but
none proves that all writers are stopped across namespaces, containers, remote
hosts, raw clients, or the next instant. That evidence would be especially
misleading before destructive load. Taut closes its own handles and states the
operator precondition; doctor does not counterfeit a stronger guarantee.

**Why not call all backlog unhealthy?** Search pending and claimed work are
normal in an opportunistic derived-index design. Quarantined failed work is the
actionable exception because it has no automatic retry. Broker claims in chat or
notification queues can also be legitimate, so broker depth is evidence, not a
failure rule.

**Why a new spec?** The command crosses core state, broker state, extensions,
search, CLI, Python, JSON, and operational safety. Folding its exact report into
persistence I/O would make dump/load appear to own diagnostics and obscure the
central epistemic boundary. A small dedicated [DOCT-*] contract is the tighter
long-term owner.

## Deviation Log

| Spec ref | Planned behavior | Actual behavior | Rationale | Spec proposal |
|----------|------------------|-----------------|-----------|---------------|
| [DOCT-5], [PIO-8.2] | Infer active contributor live-schema support through the existing read-only dump/export validation surface. | Add a doctor-selected read-only `validate_live_schema(queue)` contributor method; keep `load_versions` scoped to dump-component formats and leave dump/load compatibility unchanged. | Current Summon stores live schema version 3 while its component format is version 1. Reusing `load_versions={1}` would falsely fail every healthy active Summon workspace, while `dump_records` does not validate the metadata version. | D3 and [DOCT-5] promotion text; current Summon contributor implementation. |
| [DOM-10.1] | Strategy-C spec promotion precedes the production parser while executable documentation claims remain gated. | Add one exact, source-scoped `taut system doctor` exemption for active spec 09 during promotion; remove it in the CLI implementation slice. README promotion uses non-executable wording until the parser lands. | The claim gate intentionally rejects active command syntax before dispatch exists; a narrow expiring exemption preserves both promotion order and mechanical honesty. | Remove the exemption when `system doctor` becomes a registered parser path. |

A new durable table, repair behavior, process
or provider probe, backend-specific production implementation, changed check
inventory/data key, or weakened exit distinction requires re-planning and spec
review before implementation continues.

## Review Record

| Date | Reviewer | Verdict/findings | Disposition |
|------|----------|------------------|-------------|
| 2026-08-10 | Claude Opus, focused read-only plan review | **PASS**, no P1/P2. Ratified passive public queue stats, scoped exit 2 for complete findings, new spec 09, A6 census/quiescence refusal, failed-search finding semantics, contributor method boundary, and logical rather than physical non-mutation. P3s: distinguish observation failure from target finding in the matrix; make S4 comparison explicitly logical; disclose trusted contributor import/factory execution; cite [SRCH-8.2]. | Applied all four P3s. Plan is ready for spec promotion; implementation review gates remain. |
| 2026-08-11 | Claude Opus, different-family scoped revision review | **BLOCKED: F1** because the fixed check inventory still allowed only `dump_records`/`validate_records`; P3 F2 left compatibility-rejection mapping unspecified; P3 F3 omitted the missing-method firing case; nit F4 favored the method over a manifest field because the contributor should interpret its own metadata. | Accepted F1–F3: reconciled the three-method allowlist, mapped missing/rejected passive compatibility to `extension_state` fail rather than framework abort, and added the missing-method done signal/firing matrix case. F4 noted; no change. Round-two verification required before promotion. |
| 2026-08-11 | Claude Opus, scoped round-two verification | **PASS** on accepted findings F1–F3; verified the exact three-method allowlist, finding-versus-framework mapping, S2 done signal, and firing-matrix branch. No new defect introduced. | Revision review closed; spec promotion may proceed after the public RED tracer. |
| 2026-08-11 | Claude Opus, independent spec-promotion review | **BLOCKED: P2** because README called the unimplemented doctor “Shipped.” P3s asked for a precise unresolved-target versus opened-schemaless split, removal of a nonexistent `search_work` skip, and an exact contained contributor exception. | Accepted all: roadmap now says doctor is in progress; [DOCT-3.1] distinguishes exit 1 target failure from exit 2 schema finding; the matrix has no search skip; `PersistenceComponentCompatibilityError` is the only contained compatibility rejection. Round-two verification required. |
| 2026-08-11 | Claude Opus, spec-promotion round-two verification | **PASS**, no P1/P2. Verified the roadmap status, target-failure/schema-finding split, absence of a search dependency skip, and exact contained contributor exception across specs 08 and 09. | Promotion review closed. Production implementation may start from the recorded worktree contract identifier. |
| 2026-08-11 | Two independent read-only implementation reviews | **BLOCKED** on false-healthy topic/DM validation, load-guard dependency, column-shape probing, stored JSON classification, unknown-extension null shape, Summon table readability, database/contributor framework containment, search observation order, and stale [PIO-8.1] wording. | Accepted every finding. Shared validation now covers topics and exact DM pairs; metadata and column probes are separate and typed; stored corruption, manifest, compatibility, and runtime failures have distinct containment; search is observed after extensions; Summon probes both required tables; specs and firing tests were aligned. |
| 2026-08-11 | Claude Opus, fresh-eyes final implementation review | **BLOCKED: P2** because the README example accessed nonexistent `DoctorCheck.summary`; otherwise found no P1/P2 across the six checks, exit split, passivity, closure, validator, extension-version boundary, PostgreSQL portability, and public surfaces. | Corrected the example to `check.detail`; retained the intentional duplicate terminal-sink inventory entries while fixing their indentation. Round-two verification required. |
| 2026-08-11 | Claude Opus, final round-two verification | **PASS**, no P1/P2. Verified the public example against the exact frozen value shape and the reviewed terminal-sink call-count inventory. | Independent implementation review closed; the owner subsequently authorized close-out and commit. |

## Implementation Evidence

- Focused core, CLI, adversarial CLI, search, persistence, public API, and
  shared doctor contract: 536 passed, one expected Windows filename skip.
- Full Summon suite: 530 passed, one environmental local-LLM/Ollama skip.
- Real PostgreSQL fast gate: 266 shared root tests and 34 `taut-pg` tests
  passed. The shared doctor test fired healthy and failed-search reports,
  logical before/after equality, and credential-redacted target display.
- Documentation reference/CLI claims plus public/inventory follow-up: 38
  passed. Ruff and mypy passed on the changed core, doctor tests, and Summon
  implementation.
- `git diff --check` passed. The owner-authorized close-out commit contains the
  doctor plan, spec, implementation doc, source, and tests. Unrelated extension
  lockfile and eventual-test plan changes remain preserved outside this unit.

## Fresh-Eyes Review

Before implementation is declared complete, an uninvolved reviewer must run
healthy and seeded-failure workspaces on both backends, compare full logical
before/after state, inspect inactive extension/search schema absence, force a
framework error, and read every human/JSON sentence as a skeptical operator.
They must confirm the report is useful but cannot be mistaken for quiescence,
process census, exhaustive integrity, or dump/load authorization; all docs and
registry owners agree; and the reviewed evidence is committed in git history.
