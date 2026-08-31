# System Doctor Implementation

The system doctor implements [DOCT-1]–[DOCT-7] as seven ordered passive
observations. It is intentionally narrower than a health framework: a complete
report describes selected Taut-owned logical evidence, while target access or
framework failure raises without returning a partial report.

## Ownership and Flow

`TautClient.doctor()` is the actor-free public entry point. `taut/_doctor.py`
resolves an existing target through `taut/_maintenance.py`, owns the fixed
check order and dependency skips, and closes the metadata queue before the
report reaches the renderer. `taut/commands/system.py` maps a healthy complete
report to exit 0, an incomplete inspection exception to exit 1 through the
ordinary dispatcher, and a complete report with findings to the doctor-specific
exit 2.

The maintenance resolver also owns missing-backend normalization. A PostgreSQL
project without `taut-pg` fails before report construction with the same
actionable install hint as normal client construction; doctor never returns a
partial finding set for that framework failure.

The seven observations use these owners:

1. `taut/state/_sql.py` reads raw metadata and issues portable zero-row
   projections over every required core column. `taut/_doctor.py` decodes that
   stored version through the same state-owned, side-effect-free helper as
   ordinary startup. Neither path calls schema setup. Taut writes canonical
   decimal text but interprets equivalent integer spellings such as `02`
   consistently. Malformed state still has caller-owned surfaces: startup
   raises its existing schema error; doctor records a failed check with
   `version: null`.
2. The same state owner reports the load marker and projects logical records.
3. `taut/persistence/_format.py` validates that live projection with the shared
   dump-neutral core validator, including topics, stable DM names, participant
   memberships, and cross-references.
4. SimpleBroker's public `list_queue_stats()` supplies broker counts for only
   validated registered threads.
5. Persistence discovery supplies installed contributors. Active contributors
   may run only `validate_live_schema`, `dump_records`, and `validate_records`.
6. A later public broker-stat snapshot supplies the three exact search-work
   queue totals. No search provider is loaded.
7. The already-open core state owner reads `debug_capture`. Absent means
   disabled, exact `1` means enabled, and any other value is a finding. When
   enabled, sink is advisory: it is `action` when `TAUT_DEBUG_ACTION` is
   present in the doctor process and `local` otherwise. Doctor never opens
   `taut.debug`, runs the action, or inspects retained event bodies.

This ordering matters. The report is not one database snapshot, so search is
observed after extension state rather than cached earlier and merely rendered
last. Debug status is deliberately last and remains a passive metadata read.

## Findings Versus Framework Failure

Owned state-shape errors are typed at their owner. Missing core tables or
columns become `CoreSchemaInspectionError`; stored row decode problems become
`CoreStateInspectionError`; installed extension metadata errors use
`PersistenceComponentManifestError`; and an active contributor rejects its
live schema with `PersistenceComponentCompatibilityError`. Those specified
conditions can become report findings.

Unexpected database access failures, contributor import/factory failures, and
arbitrary contributor exceptions abort the report. The doctor wraps them with
bounded diagnostics so raw backend or extension text cannot expose a DSN,
password, payload, or SQL. This typed split prevents both false exit-2 reports
and broad exception catches that would hide programming faults [DOCT-6].

## Extension Version Boundary

Live extension schema compatibility is not dump component compatibility.
`PersistenceComponentSpec.load_versions` still names dump formats accepted by
load validation. The doctor-selected `validate_live_schema(queue)` method asks
the contributor whether its installed reader can passively read current live
state [PIO-8.2]. Summon implements it with metadata plus zero-row projections
over both required tables. It performs no DDL or migration.

## Non-Mutation and Resource Boundary

Doctor does not construct an identity-bearing client, call `ensure_schema`,
clear a guard, resume a rename, claim a broker row, load a search provider, or
initialize inactive Summon/search tables. SimpleBroker target setup may still
perform its documented idempotent backend setup, so the enforceable invariant
is unchanged Taut logical state rather than byte-for-byte file identity
[DOCT-2]. Every queue and broker opened by the operation is scoped by `finally`
or a context manager.

SQLite and PostgreSQL share this implementation. Core-owned SQL remains in the
state adapter, and PostgreSQL uses the existing broker target/dialect seams.
The public report stores `BrokerTarget.display_target`, never the raw backend
target, so PostgreSQL credentials remain redacted.

## Verification Map

`tests/test_system_doctor.py` covers the public model, exact CLI/JSON/human
surfaces, all exit classes, dependency shapes, schema and logical corruption,
broker/search totals, contributor containment, forbidden-call tripwires,
non-mutation, missing-PostgreSQL installation guidance, and safe framework
failure. `tests/test_debug_capture.py` adds exact setting-state and advisory
sink coverage. `extensions/taut_summon/tests/
test_persistence.py` covers active, incompatible, and missing-table Summon
state without migration. The shared backend contract in
`tests/test_shared_contract.py` runs healthy and failed-search reports against
real SQLite and PostgreSQL and verifies logical state plus target redaction.

The owning specification is `docs/specs/09-system-doctor.md`; execution and
review records are `docs/plans/2026-08-25-semantic-compatibility-hardening-plan.md`,
`docs/plans/2026-08-10-system-doctor-plan.md`, and
`docs/plans/2026-08-14-review-findings-remediation-plan.md`.
