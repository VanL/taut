# Taut System Doctor Specification

Date: 2026-08-11

Status: Active

## 1. Purpose and Mental Model [DOCT-1]

`taut system doctor` reports a bounded set of observations about Taut-owned
durable state and operational evidence. It is actor-free: neither the command
nor the Python operation constructs an identity-bearing `TautClient`, resolves
or heals a member, or changes chat state.

Doctor is a sequence of bounded observations, not one global snapshot. Each
check answers one named question at approximately the time that check ran. A
concurrent writer can make the aggregate report mixed or stale immediately.

`healthy=true` means only that every check in [DOCT-4] completed and met its
specified expectation. It does not mean that:

- the workspace is quiescent or no other process or connection exists;
- this process owns the last handle or a destructive operation is safe;
- a lock or timeout would be obtainable or no future write can race;
- search is fully caught up or a physical index is correct;
- every broker message is Taut-authored or decodable; or
- the storage engine, permissions, capacity, backup policy, security posture,
  or retention policy is exhaustively healthy.

Owner: core owns the fixed report and command. Persistence contributors supply
only their already-owned durable state to the fixed `extension_state` check.
Boundary: observable Taut logical state and public broker statistics.
Verification: [DOCT-7]. Required action: treat findings as remediation evidence,
never as a quiescence or dump/load certificate.

## 2. Invariants and Non-Mutation [DOCT-2]

Doctor obeys all of these rules:

1. **Actor-free.** The CLI accepts only the `system` globals `--db`, `--json`,
   and `--quiet`. The Python operation is a class operation. Doctor performs no
   member selection, identity capture, claim healing, activity, cursor, notice,
   inbox, or chat operation.
2. **Report-only.** Doctor never initializes or migrates core, extension, or
   search schema; clears a load guard; resumes a rename; creates a queue;
   reclaims, moves, drains, or rebuilds search work; changes a cursor; or repairs
   an inconsistency.
3. **No census.** Doctor does not use `ps`, `/proc`, PID or anchor liveness,
   SQLite connection enumeration, PostgreSQL activity catalogs, exclusive-lock
   attempts, busy-time heuristics, or last-handle claims.
4. **No dump/load safety claim.** Passing doctor is not a precondition or
   certificate for persistence I/O. [PIO-2.4] and [PIO-7.4] still require the
   operator to stop writers for dump/load.
5. **No fake queue-divergence detection.** SimpleBroker does not durably
   distinguish an empty registered queue from a deleted or never-populated one.
   Doctor reports registered-thread count and observable public statistics but
   never labels an absent statistics row as corruption.
6. **No physical search probe.** The search index is disposable and
   backend-native. Doctor does not import or initialize a provider, inspect an
   FTS/tsvector object, infer freshness, reclaim work, or rebuild.
7. **Portable PostgreSQL contract.** Doctor requires no compiled or optional
   PostgreSQL server extension and contains no backend-specific production SQL.
8. **No secrets or participant bodies.** The report uses a display-safe target,
   counts, stable check names, safe diagnostic details, and bounded identifiers
   only where remediation needs them. It never emits a token, DSN password, raw
   SQL, message body, or notification payload.
9. **Logical non-mutation is the enforceable promise.** Public SimpleBroker
   setup may perform idempotent backend setup. Doctor guarantees no Taut domain
   mutation or repair on an initialized workspace and proves stable logical,
   table, and queue state. It does not promise byte-for-byte storage immutability
   without an upstream read-only connection interface.
10. **Owned handles close.** Every Queue, broker, and sidecar handle Taut opens
    closes on success, findings, framework failure, renderer failure, and broken
    pipe. This is resource hygiene, not evidence about foreign handles.

## 3. Public Surfaces [DOCT-3]

### [DOCT-3.1] CLI and exit classes

The exact command is:

```text
taut system doctor
```

The root `--db TARGET`, `--json`, and `--quiet` options remain accepted before
or after the verb under the existing system-global rules.

`--as`, `--token`, and `--timestamps` are usage errors before or after the
verb. Doctor has no command-local flags in version 1. Missing, extra, or unknown
operations and arguments are usage errors.

Doctor deliberately specializes the project exit convention:

- `0`: the complete fixed report was produced and every check passed;
- `1`: usage, target resolution or access, or inspection-framework failure
  prevented a complete report; and
- `2`: the complete fixed report was produced and at least one check is `fail`
  or dependency `skip`.

Existing commands retain their current exit-2 meanings. A crash or incomplete
report must never use doctor findings exit 2.

A target that cannot be resolved or opened, including a nonexistent SQLite
path, is a framework failure and exits 1 under [TAUT-3.2]. A target that opens
successfully but lacks the required Taut schema completes the report with a
`core_schema` finding and exits 2.

Human output emits one terminal-escaped line per check in [DOCT-4] order,
followed by exactly one summary line: `workspace healthy` or
`workspace has findings`. Human wording in each detail is diagnostic and may
change. `--quiet` suppresses output but preserves diagnostics and exit status.

### [DOCT-3.2] Python values and class operation

The public values are frozen and slotted:

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

The actor-free operation is:

```python
TautClient.doctor(
    *,
    db_path: str | Path | None = None,
) -> DoctorReport
```

It is a class operation like persistence dump/load and does not instantiate an
ordinary client. It returns complete reports containing findings. It raises
when target resolution, access, or the inspection framework cannot produce the
complete fixed report.

Check names, order, status vocabulary, and each check's `data` keys and value
types are stable. Every check retains its exact data keys on `pass`, `fail`, and
`skip`. Values that could not be observed because a check or prerequisite
failed are `null`; valid observed empty counts are `0`, and valid observed empty
collections are empty. `detail` is safe single-line human diagnostic text and
is not a parsing contract.

### [DOCT-3.3] JSON

`--json` emits one aggregate UTF-8 NDJSON object with recursively sorted object
keys under a doctor-specific renderer. Other commands' JSON ordering is
unchanged. The exact top-level fields are:

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

The report contains no message ID. Errors remain concise text diagnostics on
stderr; there is no JSON error envelope.

## 4. Fixed Check Inventory [DOCT-4]

Checks run and appear in this exact order. A failed prerequisite yields `skip`
for a dependent check rather than a fabricated secondary diagnosis. Any
`fail` or `skip` makes `healthy=false`. A check is `fail` when the specified
observation completed and the observed target state violates its expectation.
An access, observation, or framework exception that prevents the complete
fixed report raises from `TautClient.doctor()` and maps to exit 1; it never
becomes a check in a report that could be mistaken for complete.

On `skip`, every value below is `null`. On `fail`, fully observed values remain
present and any value the failed observation could not establish is `null`.

### [DOCT-4.1] `core_schema`

Read `taut_meta`, validate the current core schema version, and issue read-only
projections against every required core table. Do not call `ensure_schema`.
Missing, older, newer, malformed, or unqueryable schema fails.

```json
{"version": 2}
```

`version` is `int | null`; missing or malformed version uses `null`. The
expected value comes from the implementation's core schema constant.

### [DOCT-4.2] `load_guard`

Report whether the core load guard exists. Presence fails with the existing
recreate-target recovery direction and is never cleared. This check skips when
`core_schema` could not read metadata.

```json
{"present": false}
```

`present` is `bool | null`.

### [DOCT-4.3] `core_state`

Project canonical logical core records and run the dump/live-neutral record
and cross-reference validator used by persistence preflight. This covers
members, aliases, identity claims, threads and topics, direct-message pairs,
memberships, dangling references, and rename markers. An incomplete rename
fails and names the existing resume command without applying it. No message
body is scanned. This check skips when `core_schema` failed.

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

All six keys are always present and each value is `int | null`. A valid empty
projection uses zero.

### [DOCT-4.4] `broker_state`

Using public SimpleBroker metadata/statistics only, total pending and claimed
rows for the validated registered thread names. Claims are observable facts and
may be legitimate. Foreign or unregistered queues and aliases are permitted
and are not Taut corruption. This check skips when `core_state` failed.

```json
{
  "claimed": 0,
  "observed_nonempty_queues": 2,
  "pending": 42,
  "registered_threads": 4
}
```

All four values are `int | null`. The check passes when observation succeeds.
It never compares `observed_nonempty_queues` with `registered_threads` as an
integrity rule.

### [DOCT-4.5] `extension_state`

Discover persistence contributors and map their declared schema keys. Ignore
core `schema_version` and `load_guard`. Fail on malformed or duplicate
manifests, unknown durable metadata keys, an active contributor without passive
live-schema inspection, an active contributor whose installed implementation
rejects the stored live schema, read-only export failure, or invalid exported
or cross-referenced records. An installed but unused contributor remains
inactive and uninitialized. This check skips when `core_state` could not
provide authoritative core member IDs.

For each active contributor doctor calls only, in order:
`validate_live_schema(queue)`, `dump_records(queue)`, and
`validate_records(write_version, records, core_member_ids=...)`. It never calls
`ensure_schema`, `is_fresh`, or `load_records`. A missing
`validate_live_schema` or compatibility rejection is a finding with an upgrade
direction, not a framework abort. `load_versions` remains the dump-component
format contract and must not be interpreted as live-schema support.

Compatibility rejection means the contributor raises the internal official-
extension seam's `PersistenceComponentCompatibilityError`. Missing passive
method, invalid records, and that named rejection are contained findings. Any
other contributor exception is an inspection-framework failure: no partial
report is returned and the CLI exits 1.

```json
{
  "active": ["taut-summon"],
  "installed": ["taut-summon"],
  "records": {"taut-summon": 1}
}
```

`installed` and `active` are `list[str] | null`; `records` is
`object[str, int] | null`. Names are Unicode-code-point sorted. A non-null
`records` object has exactly the active names as keys.

### [DOCT-4.6] `search_work`

Read public statistics for exactly `taut.search_index`,
`taut.search_index.claimed`, and `taut.search_index.failed` without creating,
moving, decoding, deleting, or reclaiming records.

```json
{"claimed": 0, "failed": 0, "pending": 0}
```

Each value is `int | null` and, when observed, is `QueueStats.total` for the
corresponding named queue; absence from the public statistics list means zero.
Thus `claimed` means rows in the search claimed-work queue, including any
nested broker claim state in that queue's `total`, not the broker claimed count
of the pending-work queue. Pending and claimed depth are informational and
pass. Nonzero failed depth fails because [SRCH-8.2] and [SRCH-9] quarantine work
there without automatic retry. No count implies expiration, provider health,
index completeness, or freshness.

## 5. Contributor and Search Boundaries [DOCT-5]

Persistence contributor discovery necessarily imports trusted installed
modules and calls their factories, as dump/load already do. That in-process
execution is not a claim that arbitrary imported code is side-effect-free. The
enforceable contract is that doctor invokes no contributor workspace mutation
method.

`validate_live_schema(queue)` is a doctor-selected, read-only method for an
active contributor. The contributor interprets its own schema metadata; core
does not infer extension live-schema meaning from `schema_keys` or
`load_versions`. Adding the method does not change whether an existing
contributor can participate in dump/load. It supplies state to the one fixed
core check and does not create an extension-contributed check registry.

Search is observed only through the three public queue totals in [DOCT-4.6].
Doctor does not load a search provider, call its schema or query interface,
inspect physical index state, or invoke the functional repair surface. The
functional correctness and rebuild path remains `taut search`.

## 6. Limitations, Failure, and Recovery [DOCT-6]

- A report may combine observations from different moments. There is no retry
  loop intended to manufacture a coherent snapshot.
- A missing or inaccessible target, malformed project configuration, backend
  access failure, or internal failure that prevents the fixed report raises and
  maps to exit 1 without partial stdout.
- A specified target-state violation produces a complete report with `fail`
  and exit 2. A dependent check uses `skip`, retains its fixed null data shape,
  and also causes exit 2.
- Doctor performs no recovery. Details point to existing actions such as
  recreating a guarded target, resuming a channel rename, upgrading an
  incompatible extension, or inspecting failed search work.
- A passing report does not authorize dump/load. A failing report does not
  prove that unrelated chat data is corrupt.
- Version 1 has no `status`, `--watch`, `--repair`, `--fix`, `--force`, cleanup,
  migration, or generic diagnostic-extension surface.

## 7. Verification Expectations [DOCT-7]

Tests keep real SimpleBroker queues, sidecar SQL, persistence contributor state,
and PostgreSQL live. They may use tripwires to prove forbidden calls are absent,
but they do not mock broker statistics, core state, contributor export and
validation, search work queues, or PostgreSQL.

At minimum, firing tests cover:

- every stable check name, status, data key, nullable type, and dependency skip;
- all three exit codes, exact aggregate JSON fields, recursively sorted doctor
  keys, one human line per check, fixed summary, quiet mode, and terminal
  escaping;
- globals before and after verbs; actor/timestamp rejection; missing, extra,
  and unknown operations; malformed configuration; unreadable and nonexistent
  targets; broken pipe; interruption; and a forced framework exception that
  exits 1 rather than masquerading as findings;
- current, missing, older, newer, malformed, and unqueryable core schema; load
  guard presence; valid empty state; every core logical record type; malformed
  topic, direct message, reference, and incomplete rename;
- empty registered queues without a false divergence finding; pending and
  claimed broker counts through public statistics;
- no installed contributor, inactive installed Summon, active Summon, unknown
  metadata, malformed or duplicate manifest, missing
  `validate_live_schema`, live-schema rejection, export failure, and invalid
  cross-referenced records; tripwires reject `ensure_schema`, `is_fresh`, and
  `load_records`;
- empty, pending, claimed, and failed search-work queues, with no provider load,
  schema initialization, move, reclaim, decode, or rebuild;
- nonexistent SQLite remains nonexistent; inactive extension and search schemas
  remain absent; and every Taut-owned handle closes under success, findings,
  framework failure, and renderer failure;
- real SQLite and PostgreSQL before/after logical snapshots covering core
  records, metadata, schema-object inventory, pending and claimed message IDs,
  registry and cursors, extension rows, and search work. This is logical-state
  comparison, not bytewise storage or vacuum-volatile physical-row comparison.

Post-release acceptance expects healthy SQLite and PostgreSQL fixtures to
return the exact report and exit 0, seeded findings to return a complete report
and exit 2, and invocation or framework failures to exit 1 with no partial
report or traceback.

## Implementation Mapping

Implementation rationale and the file-level ownership map live in
`docs/implementation/11-system-doctor.md`. The principal owners are
`taut/_doctor.py`, the shared target resolver in `taut/_maintenance.py`, passive
projections in `taut/state/_sql.py`, the shared validator and typed contributor
seams in `taut/persistence/`, public values in `taut/client/_models.py`, and the
`system` command plus renderer in `taut/commands/`.

## Related Plans

- `docs/plans/2026-08-10-system-doctor-plan.md` defines promotion,
  implementation slices, no-repair proof, and independent review.
