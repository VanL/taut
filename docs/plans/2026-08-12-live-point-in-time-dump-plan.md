# Live Point-in-Time Dump Plan

Status: completed

Class: 5 — persistence and core-configuration specs change. The
concurrency, destructive-load, and configuration boundaries also trigger
mandatory hardening.

Plan type: implementation with spec revision.

## 1. Goal

Replace dump's quiescence-and-movement-abort contract with a live logical
snapshot contract. Writers may remain active. A completed file must be an
internally legal, validated, importable projection, atomically published
owner-only. Workspace advancement alone is not an error.

SimpleBroker 7.3.1 supplies broker-global high-water `H`, bounds each queue
scan to message IDs at or below H, rejects above-H input, and restores H as a
durable allocation floor. Taut adopts that protocol as its message chronology
and copied-cursor ceiling. H is a means, not the product goal.

Taut also adopts SimpleBroker's future-watermark values and behavior through
its existing configuration translation boundary. Public
`TAUT_LOAD_MAX_FUTURE_SKEW_SECONDS` becomes
`BROKER_LOAD_MAX_FUTURE_SKEW_SECONDS` in the resolved SimpleBroker mapping.
The default is 300 seconds. Taut exposes no force bypass. There are no existing
Taut dumps, so no compatibility reader is required.

## 2. Source Documents

- `docs/program-theory.md` [THEORY-1] through [THEORY-5]
- `docs/specs/02-taut-core.md` [TAUT-3.2], [TAUT-7], [TAUT-8.1], [TAUT-8.6]
- `docs/specs/08-persistence-io.md` [PIO-1] through [PIO-11]
- `docs/implementation/10-persistence-io.md`
- `docs/plans/2026-08-07-taut-dump-load-plan.md` (historical implementation
  plan; this plan supersedes only its dump-quiescence decisions)
- SimpleBroker 7.3.1 `CHANGELOG.md`, `docs/specs/13-message-identity.md`
  [SB-ID-*], `docs/specs/15-persistence-io.md` [SB-IO-*], and
  `docs/specs/16-python-library-api.md` [SB-API-11]
- the retired SimpleBroker plan retained in git at
  `d0d2de9:docs/plans/2026-08-12-bounded-live-dump-plan.md`
- repository startup context; writing-plans, hardening-plans,
  testing-patterns, adversarial-acceptance-probes, maintaining-traceability,
  and review-loop runbooks
- TDD skill: `/Users/van/.agents/skills/tdd/SKILL.md`

## 3. Current State and Key Seams

- `taut/persistence/_operations.py::dump_workspace` still contains the old
  before/after broker samples, second core/extension projections, and movement
  failure. An unverified worktree patch has begun removing those checks and
  must be reviewed rather than assumed correct.
- `simplebroker.dump_lines()` now samples H when its iterator first yields,
  emits H in the header, and passes the exclusive bound H+1 to queue scans.
  It is still a bounded logical export, not a frozen claim/delete/move view.
- `_broker_payload()` must drop aliases and contain duplicate IDs from racing
  cross-queue moves. SimpleBroker does not deduplicate across queue scans.
- `taut/state/_sql.py::persistence_records` projects core tables and rejects an
  incomplete rename. Membership `last_seen_ts` is the copied cursor to clamp.
- `taut/persistence/_format.py::_DumpValidator` validates the nested header but
  does not retain H or enforce message/cursor bounds.
- General Taut/SimpleBroker configuration translation and namespace isolation
  are owned by `2026-08-13-simplebroker-config-isolation-plan.md`. This plan
  owns only dump/load use of the resolved future-skew value; Taut must not
  duplicate SimpleBroker parsing or accept fallback behavior after bad Taut
  input.
- SimpleBroker 7.3.1 makes package import safe under invalid recognized broker
  values and raises typed `InvalidConfigError` when configuration is resolved.
  Taut's command execution boundary already renders ordinary exceptions as a
  one-line exit-1 diagnostic; black-box tests must prove the new translated
  setting reaches that boundary before target creation.

Comprehension gate before runtime edits:

1. H bounds message chronology and copied cursors. It does not freeze aliases,
   claims, deletes, moves, queue membership, metadata, extensions, or wall time.
2. SimpleBroker owns `id <= H` selection and load rejection. Taut seeing an
   above-H line is incompatibility and must fail; silently filtering it would
   hide a broken upstream contract.
3. Cross-queue moves can duplicate or omit an ID during traversal. Taut must
   deduplicate first observation for import legality, but must not claim exact
   completeness under concurrent destructive broker operations.
4. Future skew is an availability hazard, not corruption. Any positive skew
   warns. Skew beyond the configured limit rejects load. Taut has no force
   bypass and never lowers H to make writes available.
5. `TAUT_LOAD_MAX_FUTURE_SKEW_SECONDS` is the public input spelling.
   `BROKER_LOAD_MAX_FUTURE_SKEW_SECONDS` is the translated dependency spelling.
   SimpleBroker owns typed parsing and the 300-second default behavior.
6. Taut passes a complete nominal `ResolvedConfig` through
   `load_lines(config=...)`. Lower layers preserve that marker and do not read
   ambient `BROKER_*`. Taut must not mutate `os.environ`; the general isolated
   resolver contract remains owned by the configuration-isolation plan.

## 4. Invariants and Constraints

1. Writers may remain active throughout dump. No writer census, global lock,
   process pause, second-pass equality check, or movement error remains.
2. A published file validates and dry-runs through the same Taut preflight and
   restores into a legal fresh target.
3. Read H once from the first nested header emitted by `dump_lines()`. Do not
   take a separate metadata sample or call it a nanosecond boundary.
4. Preserve the SimpleBroker header and retained message lines byte-for-byte.
   Drop aliases. Reject `id > H`. Retain repeated IDs once across the broker
   component in deterministic first-observation order.
5. Every copied membership cursor is `min(source_cursor, H)`. Never move a live
   source cursor backward. Do not clamp other core or extension timestamps.
6. Claims, deletes, and moves may make the bounded export omit records. This is
   accepted only under the stated logical-projection contract. Final validation
   remains the acceptance fence for an importable legal composite.
7. Core and each extension contributor return one deterministic, individually
   legal projection. No cross-component transaction is claimed.
8. Incomplete rename, active load guard, unknown durable metadata, incompatible
   component, dangling reference, or contributor failure remains fatal.
9. Owner-only staging, fsync, self-validation, temp cleanup, prior-file
   preservation, SQLite alias rejection, and atomic replace remain unchanged.
10. Load remains destructive and operator-quiescent on a fresh target.
11. Restore high-water is at least H. Every successfully generated later ID is
    greater than H and every restored ID. Far-future exact insertion retains
    SimpleBroker's existing possible write stall until wall time catches up.
12. Taut load uses the resolved translated skew setting and never passes
    `force=True`. `TAUT_LOAD_MAX_FUTURE_SKEW_SECONDS` accepts exactly the values
    SimpleBroker accepts for its broker key: a non-negative integer or an
    integer environment string. Default is 300.
13. Ambient `BROKER_LOAD_MAX_FUTURE_SKEW_SECONDS` does not affect Taut.
    `TAUT_LOAD_MAX_FUTURE_SKEW_SECONDS` and its named default supply the
    complete isolated mapping. Invalid Taut input is fatal; no fallback or
    environment mutation hides it.
14. Invalid new-setting input does not break `import taut`. On the first CLI
    operation that resolves broker configuration, it fails before target
    creation with exit 1, empty stdout, one safe stderr line, and no traceback.
    It never falls back to 300. Taut translates an invalid public Taut setting's
    typed upstream `InvalidConfigError` into a Taut-owned `ValueError` whose
    message names `TAUT_LOAD_MAX_FUTURE_SKEW_SECONDS`; invalid ambient broker
    values are not Taut inputs and are neither parsed nor diagnosed.
15. Root help/version retain [TAUT-8.6]'s lazy no-SimpleBroker-import behavior;
    they do not resolve operational broker configuration.
16. Future-skew eligibility is apply-time and host-dependent, not part of file
    preflight. Dry-run neither warns nor rejects it. Apply checks skew only in
    SimpleBroker `load_lines()`, after Taut has committed sidecar state under
    the load guard. Excessive skew therefore leaves a guarded partial target;
    the recovery action is to recreate the destination and retry when clocks or
    configuration are acceptable.
17. Taut v1 is strict because no old dumps exist. Nested `last_ts` and message
    `id` require the canonical exact 19-digit string emitted by the current
    writer. Missing and integer compatibility forms are rejected by Taut
    preflight even though generic SimpleBroker accepts integer v1 input.
18. No SimpleBroker repository edits, private imports, broker-table SQL, new
    dependency, release, tag, or publication are authorized.

Fatal failures are integrity, compatibility, component, validation,
configuration, or I/O failures. Claimed-message counts are observations, not
an atomic-snapshot claim.

## 5. Baselines

- Taut contract baseline: `e80fe0fc9c0b73353b93754c79e93c495ab2667b`
  plus the current worktree diff to `docs/specs/08-persistence-io.md`. This
  change revises that uncommitted promoted contract again before runtime work.
- SimpleBroker release baseline: `50cc8268` (v7.3.1). The relevant behavior
  landed at `d0d2de9`; v7.3.1 is test-only beyond v7.3.0.
- Installed Taut environment: SimpleBroker 7.3.1 and simplebroker-pg 3.8.0.
- After the revised spec-promotion slice, record the Taut base SHA plus exact
  worktree spec diff as the new promotion baseline.
- Revised promotion baseline: `e80fe0fc9c0b73353b93754c79e93c495ab2667b`
  plus the current worktree diffs to `docs/specs/02-taut-core.md` and
  `docs/specs/08-persistence-io.md` after the 2026-08-13 round-2 PASS.

## 6. Proposed Spec Delta

Promotion strategy A: revise active [PIO-*] and [TAUT-*] text before further
runtime implementation.

### [PIO-1]/[PIO-2.4]: live logical dump

> Dump permits active workspace processes. A successful dump is a validated,
> importable logical projection. Racing mutations may appear in this dump or a
> later one. The format does not claim one transaction, one physical instant,
> or complete frozen claim/delete/move state across broker, core, and extension
> components. Load remains destructive and requires quiescence.

### [PIO-3.1]: exit classes

> Exit 1 includes malformed/incompatible state or file, unsafe I/O, incomplete
> transition, unavailable contributor, invalid configuration, excessive future
> skew, backend failure, and failed validation/apply/recovery. Ordinary source
> activity during dump is not an error.

### [PIO-4.3]: SimpleBroker component

> Read H from the first unchanged header emitted by SimpleBroker 7.3.1.
> SimpleBroker owns bounded selection `id <= H`; Taut rejects a violating line,
> preserves retained header/message bytes, drops aliases, and retains a racing
> duplicate ID only at deterministic first observation across the component.
> H is a chronology boundary, not a nanosecond or frozen-membership claim.
>
> Taut v1 requires exact 19-digit string `last_ts` and message `id` fields. Load
> restores allocation state to at least H. Every successful later allocation
> exceeds H and every restored ID.

### [PIO-4.4]: copied cursor clamp

> Each emitted membership `last_seen_ts` is
> `min(live_last_seen_ts, H)`. Only the copied record changes. No other core or
> extension timestamp is clamped merely because it exceeds H.

### [PIO-6.1]: projection and validation

> Dump obtains one core and one per-extension projection, begins the selected
> broker stream and reads H, clamps copied cursors, contains duplicate broker
> IDs, assembles owner-only staging, and validates the complete composite before
> atomic publication. It does not repeat projections to prove immobility.

### [PIO-7]/[PIO-9]/[PIO-11]: restore skew and firing behavior

> Taut load adopts SimpleBroker's future-watermark policy without a force path.
> Any positive physical skew emits `DumpClockSkewWarning`. Skew beyond resolved
> `BROKER_LOAD_MAX_FUTURE_SKEW_SECONDS` rejects load. The Taut public setting is
> `TAUT_LOAD_MAX_FUTURE_SKEW_SECONDS`; default 300. Firing tests cover default,
> override, warning, refusal, guarded failure, no force surface, and real
> SQLite/PostgreSQL restore. Skew is apply-time host eligibility: dry-run does
> not warn or reject; actual refusal occurs after Taut has installed sidecar
> state under its guard and requires recreating the destination.

### [TAUT-3.2]: configuration translation (delegated)

> The complete translation and isolation contract is promoted by
> `2026-08-13-simplebroker-config-isolation-plan.md`. This plan requires only
> that `TAUT_LOAD_MAX_FUTURE_SKEW_SECONDS` resolves to
> `BROKER_LOAD_MAX_FUTURE_SKEW_SECONDS`, SimpleBroker owns type/range parsing,
> invalid Taut input names the Taut key, and dump/load receives the resulting
> ambient-free `ResolvedConfig`.

## 7. Rollout and Rollback

The configuration-isolation plan owns the required additive SimpleBroker
contract and release gate. This dump plan consumes that resolved mapping after
the dependency is available; it does not independently edit or publish the
sibling repository.

Rollback before Taut release reverts the Taut spec, dump/config behavior, and
tests together. No old Taut dump constrains rollback. Once Taut publishes this
strict v1 contract, retain the dependency floor rather than adding fallback
parsing.

## 8. Dependency-Ordered Tasks

1. Fresh-eyes review this revised plan against Taut and released SimpleBroker
   7.3.1. Stop on any false frozen-snapshot claim, duplicate policy owner,
   nonexistent public seam, or lazy-import/config conflict.
2. Promote the revised spec delta into [PIO-*] and [TAUT-3.2]. Record the new
   worktree promotion baseline and rerun document gates.
3. RED/GREEN broker chronology:
   - Through `TautClient.dump`, prove a write after H does not abort and is not
     exported. Make Taut reject, not filter, an injected above-H upstream line.
   - Preserve bytes, drop aliases, and deduplicate IDs across all selected
     queues. Keep real `dump_lines()` and real SQLite queues.
   - Remove before/after samples and second projections.
4. RED/GREEN copied cursors and validation:
   - Clamp copied membership cursors only; prove the live source is unchanged.
   - Retain H in the validator and reject above-H messages/cursors plus
     noncanonical integer/missing nested fields before destination creation.
5. RED/GREEN component concurrency:
   - Prove coherent sidecar/extension mutations can succeed as legal before-or-
     after projections.
   - Keep incomplete transitions, dangling references, contributor failures,
     unknown metadata, and invalid composites fatal.
   - Stop if this grows into a cross-component snapshot API.
6. RED/GREEN configuration and skew:
   - Reuse the configuration-isolation plan's general translation path; do not
     hand-parse values. Invalid public Taut input is re-expressed as a Taut-owned
     `ValueError` naming the public Taut key.
   - Prove ambient broker values, valid or invalid, do not affect Taut dump/load.
     Never mutate the process environment.
   - Pass resolved config to `load_lines()`; never pass force.
   - Prove warning within limit and refusal beyond it through public Taut load.
   - Prove dry-run succeeds without a skew warning, while apply refusal happens
     after the guard/sidecar phase and leaves the target guarded for recreation.
   - Prove invalid negative, bool-like, float-like, and nonnumeric environment
     values are import-safe and fail the first config-consuming CLI operation
     before target creation with no fallback or traceback.
7. Run SQLite and PostgreSQL acceptance, then update CLI help, README,
   CHANGELOG, implementation note, traceability mappings, and dependency-floor
   claims. Run independent completed-work review before completion.

## 9. Testing Plan

Use vertical red-green TDD through public `TautClient.dump/load` and the shipped
CLI. Keep real SimpleBroker dump/load, SQLite/PostgreSQL storage, sidecar SQL,
filesystem staging, and extension records. Phase hooks may coordinate a race;
do not mock the filtering, restore floor, config parser, cursor mutation, final
validator, or atomic publication.

Required firing behavior:

- active append before/after H; exactly-H retained and later write excluded
- header-only and claimed/no-row-at-H restore preserve H
- racing move cannot duplicate an ID in the output
- copied cursor above H becomes H while live source remains unchanged
- above-H message/cursor and noncanonical nested IDs fail preflight
- coherent core/extension movement succeeds; illegal composite still fails
- default 300-second future-skew boundary, positive warning, excessive refusal
- public Taut skew override changes behavior; its invalid-value diagnostic uses
  the Taut spelling
- valid and invalid ambient broker skew do not affect Taut; invalid Taut input
  remains fatal
- no CLI or Python force surface
- invalid Taut skew values are import-safe, one-line CLI failures before target
  creation, and do not fall back
- owner-only atomic publication and prior-file/temp cleanup on genuine failure
- SQLite/PostgreSQL parity

## 10. Verification and Completion Gates

Per slice, run the single new RED test, implement only enough for GREEN, then
run the neighboring persistence/config suite. Final gates include:

```bash
uv run --extra dev pytest -q tests/test_persistence_io.py tests/test_persistence_io_adversarial.py tests/test_constants.py tests/test_cli_probes.py tests/test_command_registry.py tests/test_lazy_imports.py
uv run --project extensions/taut_summon --extra dev pytest -q extensions/taut_summon/tests/test_persistence.py
uv run ./bin/pytest-pg --fast
uv run --extra dev pytest
uv run ruff check taut tests bin extensions/taut_pg/taut_pg extensions/taut_pg/tests extensions/taut_summon/taut_summon extensions/taut_summon/tests
uv run ruff format --check taut tests bin extensions/taut_pg/taut_pg extensions/taut_pg/tests extensions/taut_summon/taut_summon extensions/taut_summon/tests
uv run --extra dev mypy taut tests bin/release.py extensions/taut_pg/taut_pg extensions/taut_pg/tests --config-file pyproject.toml
uv run bin/check-cli-claims
bin/check-plan-status-index
uv run bin/check-doc-paths
uv run bin/coalesce-check
git diff --check
```

Completion requires the published floors, strict format/config firing tests,
concrete SQLite/PostgreSQL restore evidence, zero stale quiescence claims,
independent completed-work review, and no force surface. Work remains
uncommitted unless the owner separately requests a commit.

## 11. Independent Review Log

Reviewer: different-family read-only reviewer from `/Users/van/Developer`,
with this plan, Taut's specs/code/tests, and SimpleBroker 7.3.1's active specs
and implementation. Verdict uses the repository PASS/BLOCKED rubric.

| Round | Finding | Evidence | Disposition | Result |
|---|---|---|---|---|
| 1 | Move dedup is load legality, not cosmetic. | Generic load rejects duplicate IDs. | Accepted: one broker-wide seen-ID set and firing race test. | PASS |
| 1 | Earlier chronology work depended on unpublished upstream behavior. | SimpleBroker 7.1 ignored header H. | Superseded: 7.3.1 is published and installed. | PASS |
| 1 | Derive H from the emitted header rather than a separate sample. | `dump_lines()` emits the sampled global H first. | Accepted. | PASS |
| 2 | Public resolver validates ambient broker config before translated overrides. | SimpleBroker `_constants.py::_resolve_config_input`; direct probe. | Accepted: ambient broker values are an explicit lower-level dependency input; valid Taut input wins only after base validation; no environment mutation. | Round 2 PASS |
| 2 | Skew refusal occurs after Taut sidecar/guard mutation, not file preflight. | Taut load order and SimpleBroker `load_lines()`. | Accepted: dry-run excludes host skew; apply refusal leaves guarded target requiring recreation; firing tests added. | Round 2 PASS |
| 2 | Upstream invalid-config diagnostics name the translated broker key. | `InvalidConfigError.key`. | Accepted: translate only invalid Taut override errors into a Taut-owned `ValueError`; retain upstream ambient errors. | Round 2 PASS |
| 2 | Normative spec edits trigger Class 5. | [DOM-15]. | Accepted in plan and status index. | Round 2 PASS |
| Completed-work 1 | Active doctor wording still implied dump quiescence; CLI help overclaimed one cross-component snapshot boundary. | Active specs/help versus the separate core, H, and extension projection phases. | Accepted: doctor now neither gates nor authorizes live dump; help says live H-bounded logical backup and before-or-after racing changes. | Resolved |
| Completed-work 1 | Required concurrency, cursor, watermark-only restore, default-skew, and fresh-process config proofs were incomplete or synthetic. | Adversarial and public CLI test inspection. | Accepted: replaced duplicate/cursor projections with real SimpleBroker and sidecar storage cases; added claimed/header-only restore, 299/301 default boundary, help/version/config-consuming subprocess, and explicit force rejection. | Resolved |
| Completed-work 2 | Rechecked every completed-work disposition against current code, active specs, and SimpleBroker 7.3.1. | Nine focused disposition cases passed; scoped diff hygiene passed. | No remaining P1/P2 finding. | PASS |

## 12. Out of Scope

- making load safe with active writers
- exact global transaction or frozen claims/deletes/moves
- physical backup, incremental/selective backup, scheduling, compression,
  encryption, remote storage, or retention
- a force flag or force argument
- redesigning the general configuration-isolation contract owned by
  `2026-08-13-simplebroker-config-isolation-plan.md`
- compatibility with Taut dumps created before this contract
- any SimpleBroker repository edit, release, tag, or publication

## 13. Deviation Log

| Spec ref | Planned behavior | Actual behavior | Rationale | Spec proposal |
|---|---|---|---|---|

## 14. Supersession Boundary

This plan supersedes the dump-only quiescence, double-serialization, movement
abort, help copy, and adversarial expectations in
`2026-08-07-taut-dump-load-plan.md`. It does not reopen outer framing,
owner-only publication, fresh-target/load-guard policy, extension discovery,
or destructive load concurrency.

## 15. Fresh-Eyes Gate

Re-check every seam exists; SimpleBroker owns H selection and floor restore;
Taut fails rather than filters an above-H violation; dedup spans the complete
broker component; movement alone cannot fail; illegal composites still can;
strict v1 has no fallback; the public Taut key translates to the broker key;
default 300 and no-force are explicit; invalid input is import-safe and fails
before target creation; bad Taut input names the Taut key; ambient broker input
does not affect Taut; dry-run excludes host skew and apply refusal leaves a
guarded target; root lazy help/version still do not load SimpleBroker.

## 16. Revision Log

| Date | Revision | Evidence / decision |
|---|---|---|
| 2026-08-13 | Rebased onto published SimpleBroker 7.3.1/API v7; assigned bounded selection and floor restore to upstream; made above-H output fatal; added strict no-legacy v1, public Taut-to-broker skew translation, default 300, no-force policy, and invalid-config lifecycle. | Owner direction after read-only release investigation; focused SimpleBroker release proofs passed. |
| 2026-08-13 | Corrected Class 5; acknowledged ambient broker validation before overrides; scoped Taut-key diagnostic translation; defined skew as apply-time eligibility excluded from dry-run and leaving a guarded target on refusal. | Independent revised-plan review round 2 blockers. |
| 2026-08-13 | Delegated general config translation to the SimpleBroker isolation plan; replaced the superseded ambient-broker premise with the complete nominal `ResolvedConfig` contract. | `2026-08-13-simplebroker-config-isolation-plan.md` became the sole owner of namespace isolation. |
| 2026-08-13 | Completed integrated verification for coordinated 0.9.0 preparation. | Core passed 1,957 tests with one platform-specific skip, installed-wheel coverage passed 28 tests, PostgreSQL passed 256 shared plus 36 isolated tests, and the focused persistence/adversarial/doctor gate passed 76 tests. Ruff and all relevant mypy scopes passed. A live-doctor regression found during the gate was fixed by applying the dump high-water membership bound only when a dump header high-water exists. |
