# Taut Persistence I/O Implementation Plan

Date: 2026-08-07

Class: 5, spec-changing and risky. [DOM-6] requires a new normative
persistence-I/O contract. [DOM-5] risky triggers also fire because the change
adds a public CLI and Python API, a portable storage format, secret-bearing
temporary files, extension discovery, cross-store apply ordering, destructive
failure edges, and fail-closed recovery.

Status: completed. The owner accepted the reviewed plan, requested
implementation on 2026-08-08, and authorized close-out and commit after the
implementation, cross-backend verification, and final Opus review passed.

Plan type: implementation with spec revision.

## 1. Goal

Add `taut system dump` and `taut system load` as actor-free, full-workspace
maintenance commands. Reuse SimpleBroker's public dump/load stream unchanged
inside a versioned Taut composite file, represent authoritative sidecar state
as logical records, include recognized durable extension state, exclude
derived/runtime state, and restore exact identifiers across SQLite and
PostgreSQL without requiring a new server extension.

The result should fit Taut's product shape: one explicit file, no daemon, no
configuration surface, no merge modes, no hidden identity work, and no claim
that several independently committed stores form a live point-in-time snapshot.

## 2. Source Documents

Governing specs at the plan baseline:

- `docs/specs/01-development-documentation-operating-model.md` [DOM-5],
  [DOM-6], [DOM-10], [DOM-11], [DOM-15]
- `docs/specs/02-taut-core.md` [TAUT-1], [TAUT-3.1], [TAUT-3.3],
  [TAUT-3.4], [TAUT-8.1], [TAUT-8.2], [TAUT-8.3], [TAUT-8.6], [TAUT-10],
  [TAUT-12.1], [TAUT-12.2]
- `docs/specs/03-identity-addressing-notifications.md` [IAN-3], [IAN-4],
  [IAN-5], [IAN-6], [IAN-7], [IAN-8]
- `docs/specs/04-summon.md` [SUM-8], [SUM-9], [SUM-11]
- `docs/specs/06-search.md` [SRCH-2.1], [SRCH-8], [SRCH-10.3], [SRCH-11]

Proposed full contract:

- `docs/plans/2026-08-07-taut-dump-load-spec-draft.md` [PIO-1] through
  [PIO-11], plus companion deltas [PIO-D1] through [PIO-D8]

Upstream and comparative references:

- `/Users/van/Developer/simplebroker/docs/specs/15-persistence-io.md`
  [SB-IO-1] through [SB-IO-5]
- `/Users/van/Developer/weft/weft/commands/_dump_support.py`
- `/Users/van/Developer/weft/weft/commands/_load_support.py`
- `/Users/van/Developer/weft/weft/commands/system.py`

Process and architecture guidance:

- `docs/agent-context/runbooks/writing-plans.md`
- `docs/agent-context/runbooks/writing-specs.md`
- `docs/agent-context/runbooks/hardening-plans.md`
- `docs/agent-context/runbooks/testing-patterns.md`
- `docs/agent-context/runbooks/adversarial-acceptance-probes.md`
- `docs/agent-context/runbooks/review-loops-and-agent-bootstrap.md`
- `docs/agent-context/runbooks/maintaining-traceability.md`
- `docs/implementation/04-taut-architecture.md`
- `docs/implementation/05-taut-summon-architecture.md`
- `docs/implementation/06-command-extensions.md`
- `docs/implementation/09-search-architecture.md`

The product source is the 2026-08-06 and 2026-08-07 discussion that selected a
Taut-specific composite dump, reuse of SimpleBroker's dump/load mechanics,
logical export of sidecar authority, exclusion of derived/runtime state, and a
core-owned `taut system` namespace that can later hold maintenance commands
such as status or doctor.

## 3. Spec Baseline and Proposed Delta

### 3.1 Spec baseline

- Baseline: `847516f04ec9d2d8da7d3b17dd4008af9e07dcaf`.
- Governed files at baseline: `docs/specs/02-taut-core.md`,
  `docs/specs/03-identity-addressing-notifications.md`,
  `docs/specs/04-summon.md`, and `docs/specs/06-search.md`.
- No active Taut persistence-I/O spec exists. SimpleBroker defines only broker
  messages and aliases; it cannot restore Taut sidecar authority.
- This repository has no machine in-flight spec classification. Prose status
  and the document-reference gates are the available mechanisms.

### 3.2 Proposed spec delta

The exact review target is
`docs/plans/2026-08-07-taut-dump-load-spec-draft.md`.

| Target | Proposed sections | Promotion strategy |
|---|---|---|
| new `docs/specs/08-persistence-io.md` | [PIO-1] through [PIO-11] | A: active requirement text first, no premature implementation mapping |
| `docs/specs/02-taut-core.md` | [PIO-D1] through [PIO-D5] | A: exact companion text in the promotion slice |
| `docs/specs/04-summon.md` | [PIO-D6] | A: exact durable/transient persistence rule |
| `docs/specs/06-search.md` | [PIO-D7] | A: exact exclusion and rebuild rule |
| spec and implementation indexes plus docs tests | [PIO-D8] | promotion and firing gates |

Promotion strategy A is deliberate. The new active text lands before runtime
code cites it, without implementation-link claims that would create false
reciprocity. The implementation mapping and reciprocal code citations land
with the relevant code slices. After promotion, the active spec tree is
canonical and the draft remains only historical review material.

### 3.3 Spec-promotion slice

After owner acceptance and independent review:

1. Copy the accepted draft to `docs/specs/08-persistence-io.md` and change its
   status to Active.
2. Apply [PIO-D1] through [PIO-D8] exactly, adjusting only surrounding prose
   needed to avoid duplicate statements.
3. Add the active spec to `docs/specs/00-specs-index.md`, `docs/specs/README.md`,
   and the document reference tests.
4. Add the plan backlink under every materially touched active spec.
5. Record a promotion baseline identifier in this section. Use a commit SHA if
   committed, otherwise record the baseline SHA plus a manifest digest over all
   promotion files.
6. Run the document, CLI-claim, and plan-index gates before runtime work.

Do not begin a runtime slice against the draft. If review changes component
authority, load recovery, the system namespace, included state, or the format,
revise and re-review before promotion.

Promotion baseline: base `11935af`; SHA-256
`7f403a1fe402ec12227350de2844440603aaa4ae551adc81e7fb0dd01151f768` in
the 2026-08-08 worktree. The digest is the output of `shasum -a 256` over each
of these ordered files, piped to a final `shasum -a 256`:
`docs/specs/08-persistence-io.md`, `docs/specs/02-taut-core.md`,
`docs/specs/04-summon.md`, `docs/specs/06-search.md`,
`docs/specs/00-specs-index.md`, `docs/specs/README.md`,
`docs/plans/README.md`, `tests/test_docs_references.py`, and
`tests/test_cli_claims.py`. Runtime work is measured against this explicit
active-spec promotion manifest.

## 4. Verified Current Structure and Key Files

### 4.1 Current state

| Path | Current responsibility | Persistence-I/O consequence |
|---|---|---|
| `taut/commands/_builtins.py` | lightweight built-in manifests | add one lazy `system` manifest with a reduced post-verb global set |
| `taut/commands/channel.py` | existing required nested-subparser pattern | copy parser ownership style, not channel domain logic |
| `taut/commands/_protocol.py` | command protocol, root-global vocabulary, lazy client context | reject identity/timestamp globals for actor-free system work and never call `context.client()` |
| `taut/client/__init__.py::TautClient.init` | actor-free classmethod target resolution and schema init; it bypasses `_ClientBase.__init__` | reuse target-resolution posture for new class methods, add its own load-guard check, and do not construct an identity-bearing client |
| `taut/client/_base.py::_ClientBase.__init__` | normal target, queue, and core state construction | add the ordinary-operation load-guard gate after schema validation |
| `taut/state/_sql.py` | all core-owned sidecar SQL and schema validation | own deterministic logical projections, empty-target checks, guard operations, and ordered imports |
| `taut/state/_types.py` | typed core sidecar rows | add only reusable logical/report types that genuinely belong here |
| `taut/search/` | disposable search tables and work queues | no dump component; first-search reconciliation remains the rebuild path |
| `extensions/taut_summon/taut_summon/_state.py` | transient claims and durable session ledger | add extension-owned logical session export/import while preserving SQL ownership |
| `extensions/taut_summon/pyproject.toml` | installed Summon entry points | register the official `taut-summon` persistence manifest |
| `extensions/taut_pg/` | PostgreSQL target package and search provider | add integration tests only; no persistence implementation or server extension |
| `tests/test_command_registry.py` | manifest, lazy-load, global-option, and nested-parser contracts | prove `system` remains lazy and root help survives broken contributors |
| `tests/test_cli_probes.py` | black-box adversarial CLI floors | add malformed input, output lifecycle, exit, and no-traceback probes |
| `tests/test_docs_references.py` | stable spec/code family and path assertions | admit and require [PIO-*] paths and backlinks after promotion |

SimpleBroker's public `dump_lines()` emits one v1 header, aliases, then pending
messages sorted by queue and id. `load_lines()` validates the nested stream and
preserves exact ids. Claimed rows are omitted, and concurrent dump is explicitly
not a snapshot. These facts are load-bearing. Do not duplicate its parser,
message serializer, insertion batching, id handling, or private schema.

Weft is a useful policy example, not a wire-format template. Its system dump is
a pure `simplebroker-dump`, excludes runtime queues, writes owner-only output,
supports dry-run load, and snapshots file-backed SQLite before apply. It does
not include a portable sidecar or Monitor-state format. Taut must therefore own
a true outer composite format rather than label custom records as SimpleBroker.

### 4.2 Required reading and comprehension gate

Before editing runtime code, the implementer must read the files above plus:

- `taut/client/_identity.py` and `taut/identity.py`: distinguish durable claim
  authority from current process anchor/presence evidence
- `taut/search/_jobs.py` and `taut/search/_worker.py`: identify every search
  queue/table that must remain derived and excluded
- `extensions/taut_summon/taut_summon/_state.py`: distinguish claims, durable
  sessions, continuity fields, and driver lease evidence
- the public exports for `dump_lines`, `load_lines`, sidecar sessions, queue
  stats, and exact target resolution in the installed SimpleBroker floor

Answer these before the first red test:

1. Which state can rebuild from registered broker history, and which state is
   the only authority for identity, names, membership, and cursors?
2. Which exact fields can falsely claim a live process after restore, and what
   durable continuity remains after those fields are cleared?
3. Which public SimpleBroker lines can be passed through unchanged, and why do
   aliases and unregistered queues still need Taut filtering?
4. Where can PostgreSQL commit partial load work despite a successful sidecar
   transaction, and which observable guard prevents normal use afterward?

If any answer depends on private broker SQL, a backend-specific catalog query
in core, or assumptions about Weft Monitor state, stop and revise the design.

## 5. Invariants, Hidden Couplings, and Constraints

1. **SimpleBroker remains the message-format owner.** Retained nested lines are
   unchanged `dump_lines()` output and are restored by `load_lines()`. No
   private import and no broker-table SQL enters Taut.

2. **Taut registry state selects broker content.** Only exact registered
   `taut_threads` queue names are eligible. Notification and registered system
   queues count; foreign, search, Summon control, and other unregistered queues
   do not. Empty registered threads survive through sidecar records.
   SimpleBroker accepts fnmatch include globs, but every current registered
   queue grammar excludes `*`, `?`, `[`, and `]`; expanding that grammar is a
   required re-review of dump selection.

3. **Exact ids survive.** Never rewrite message, member, claim, thread,
   cursor, token, provider-session, or timestamp identifiers. A backend that
   cannot preserve SimpleBroker ids fails before apply.

4. **Physical schemas are not the format.** Never serialize raw SQL rows,
   table DDL, `taut_meta` schema versions, backend names as behavior, or search
   provider pages. Decode JSON columns into logical JSON values and initialize
   the destination's current schemas.

5. **Live leases do not survive.** Core member anchor pid/start/fingerprint,
   Summon bootstrap claims, and Summon driver pid/start are absent or null after
   load. Durable identity claims, continuity tokens, provider session ids, and
   wired state remain.

6. **No partial backup looks complete.** Unknown `taut_meta` schema keys,
   missing extension contributors, contributor failures, source movement,
   digest failures, or incomplete renames fail before atomic output replacement.

7. **No partial load looks usable.** The load guard spans authoritative
   sidecar commit, broker load, and finalization. Every ordinary current-version
   operation fails closed while it exists. Clearing it is part of success.

8. **Quiescence is a precondition, not a heuristic result.** Double reads and
   metadata comparisons detect some races only. Help, docs, and reports must
   not call a successful dump a point-in-time snapshot.

9. **Dry-run shares file/component preflight and writes nothing.** It parses the
   same file, loads the same manifests, and validates the same cross-references,
   but reports `destination_checked: false`. The public SimpleBroker open path
   initializes schema, so actual load alone checks target eligibility before
   guard acquisition. Dry-run never creates a target, schema, marker,
   temp file beside the target, queue, or sidecar row.

10. **Core stays backend-neutral.** No PostgreSQL SQL, catalog inspection,
    optional server extension, or new `taut-pg` runtime code. Both backends
    fail closed; PostgreSQL can expose independently committed broker batches.

11. **Files are secret-bearing.** Output and staging are owner-only; old output
    survives a failed replacement; config and credentials never enter the
    logical records. Hashes detect corruption, not malicious rewriting. SQLite
    path-identity checks prevent dump output or load input from aliasing the
    database, WAL, or SHM through relative paths, symlinks, or hard links.

12. **The namespace remains small.** Add only `taut system dump/load`. Do not
    implement empty `doctor` or `status`, top-level aliases, component filters,
    stdin/stdout streaming, merge, force, replace, or resume.

13. **Extension contributors stay narrow.** Core owns framing and lifecycle;
    contributors own only their logical records and sidecar schema. They get a
    core-constructed queue/session and cannot open another connection or file.

14. **Errors are fatal by integrity class.** Data-format, digest, component,
    target-eligibility, guard, schema, exact-id, and apply failures are fatal.
    Cleanup after an already determined failure is best-effort, but cleanup
    failure must be added to the diagnostic when it changes recovery safety.

15. **No drive-by framework.** The component seam serves installed Taut
    extensions with durable sidecar state. It is not a generalized database
    migration, arbitrary table export, or third-party backup SDK.

### 5.1 One-way doors and destructive edges

- Actual load mutates a fresh destination and can commit a partial PostgreSQL
  broker stream. There is no `--force`; a guarded failed target is discarded.
- Dump atomically replaces the explicitly named output after success. Failure
  before replace must retain the previous file.
- A future component version, merge mode, or live-snapshot protocol changes the
  compatibility surface. It requires a new spec revision, not an inferred
  extension of version 1.

### 5.2 Stop-and-replan triggers

Stop and return to spec review if implementation needs any of these:

- private SimpleBroker modules, SQL, or timestamp mutation
- a second broker/body serializer or a raw sidecar-table record
- a core PostgreSQL branch or required compiled server extension
- a workspace lock presented as protecting clients that do not honor it
- preserving a pid/start-time lease to make a round trip test pass
- skipping unknown extension state, a component, a corrupt record, or a guard
- accepting a nonempty destination or adding a force/replace path
- buffering the full broker message body set in memory
- synchronous search rebuild as a load completion condition
- an identity-bearing `TautClient` instance in system command execution

## 6. Rollout and Rollback Before Implementation

### 6.1 Rollout order

1. Promote the reviewed spec without implementation claims.
2. Land format/parser/report types and red public acceptance tests.
3. Land core sidecar projection, extension discovery, and load-guard checks.
   Guard checks must exist before any usable apply path.
4. Land dump, then load preflight, then guarded apply and recovery.
5. Land the Summon contributor and cross-backend tests before advertising full
   installed-extension coverage.
6. Add CLI/API docs, implementation mapping, and first-search recovery proof.
7. Run completed-work Opus review and all release gates.

Do not allow mixed older Taut clients during `system load`. The guard is a
current-version recovery fence, not a cross-version distributed lock. The
maintenance command and docs require quiescence for every version.

### 6.2 Rollback

Before any release creates a dump in the field, runtime code can be reverted
independently because it adds no required schema column or background process.
Existing databases retain only additive code paths and no marker unless a load
was started.

After release:

- removing the command does not invalidate existing Taut targets or broker
  history
- a completed `taut-dump` remains data that can be loaded by the release that
  wrote it; do not promise older releases can read it
- a failed target is never repaired in place on either backend; recreate it and
  rerun the same preflighted dump
- SQLite load closes its own handles but does not snapshot, checkpoint, count
  attached processes, or claim a cross-process rollback guarantee
- if a release defect can clear a guard prematurely or write wrong ids, disable
  load immediately; dump may remain enabled only if independent round-trip
  verification shows its bytes are correct

The old output path is not a rollback store for load. It is only the dump
artifact. No task may delete the source target as part of load.

## 7. Dependency-Ordered Tasks

### 1. Review and promote the contract

- Files: this plan, the adjacent spec draft, then the active spec and companion
  files named in section 3.
- Run an independent Claude Opus plan/spec review in a read-only posture. Give
  it up to 15 minutes. Require PASS/BLOCKED against implementability and system
  degradation, plus direct review of the format, quiescence limit, extension
  seam, marker lifecycle, and SQLite/PostgreSQL recovery split.
- Apply every accepted finding or record a reasoned rejection in section 11.
- Promote with strategy A and record the promotion baseline.
- Red document proof: make the docs-reference expectation require the new
  active spec before adding it, observe the focused failure, then add the spec
  and observe green.
- Stop if review changes any authority or blast-radius choice. Re-review the
  revised delta rather than treating old approval as attached to the filename.
- Done: active [PIO-*] text exists, companion deltas are applied, docs gates are
  green, and no runtime mapping is claimed prematurely.

### 2. Establish red format, report, API, and CLI acceptance tests

- Files: new `tests/test_persistence_io.py`, updates to
  `tests/test_public_api.py`, `tests/test_command_registry.py`,
  `tests/test_cli.py` or the current focused CLI home, and
  `tests/test_cli_probes.py`.
- Add failing tests for the exact classmethod signatures, frozen report fields,
  `system` nested grammar, reduced globals, help, JSON, quiet, output/input path
  rules, 0/1/2 exits, and no actor construction.
- Add format fixtures that pin literal UTF-8 canonical Taut records, raw nested
  SimpleBroker lines, component order, counts, hashes, and final LF.
- Add adversarial red cases from [PIO-11.2], including duplicate JSON keys and
  well-formed corrupt framing, before parser code.
- Keep the real CLI dispatcher. A command test may inject an operation function
  only to isolate rendering; at least one subprocess path must use real storage.
- Stop if the CLI needs separate semantics or an identity-bearing client.
- Done: focused tests fail only because the new public surface and parser are
  absent, not because fixtures contradict the promoted spec.

### 3. Implement the composite format and bounded streaming preflight

- Files: new `taut/persistence/__init__.py`,
  `taut/persistence/_format.py`, and focused
  tests from task 2.
- Implement strict UTF-8 line reading, duplicate-key rejection, framing state,
  exact outer fields, component replay offsets or equivalent bounded indexes,
  per-component/final digests, canonical Taut serialization, and report
  derivation.
- Preserve nested SimpleBroker lines byte-for-byte. Do not normalize and
  reserialize them before `load_lines()`.
- Use a two-pass or replayable-file design so preflight validates the full file
  without retaining all message bodies. Pin this with a large fixture and an
  observable bounded-memory substitute proof if stable RSS assertion is not
  portable.
- Stop if parsing accepts unknown outer fields/types or needs a second message
  model.
- Done: format tests and hostile-input probes pass with 1-based line/component
  diagnostics and no traceback.

### 4. Implement core sidecar projection, guard, and component discovery

- Files: `taut/state/_sql.py`, new `taut/persistence/_components.py`,
  `taut/client/_base.py`, `taut/client/__init__.py`, `taut/client/_models.py`,
  `taut/__init__.py`, and tests.
- Add explicit fixed SQL projections for every core logical record. Decode and
  validate JSON through existing domain helpers. Recompute route keys on load.
  Never use `SELECT *` or runtime-built SQL column lists.
- Add portable empty-target checks, exact ordered inserts, load-guard acquire,
  inspect, reject, and clear operations. Guard acquisition must recheck
  emptiness in the same sidecar transaction and serialize two loaders.
- Gate ordinary client construction and `init` on the guard with the exact
  recovery diagnostic. Persistence load uses a narrow bypass that cannot leak
  to chat APIs.
- Implement lightweight `taut.persistence_components` manifests with lazy
  implementation loading, exact schema-key ownership, and replayable record
  iterators. Use command/search discovery conventions only where they fit; do
  not generalize a shared plugin framework in this slice.
- Red/green unknown/duplicate meta-key and component cases.
- Stop if core needs backend catalogs, extension table names, independent
  connections, or raw schema versions in the file.
- Done: real SQLite sidecar tests round-trip all core records, clear live anchor
  evidence, reject incomplete renames and unknown durable state, and fail every
  ordinary operation through a guard.

### 5. Implement owner-only, stable-view dump

- Files: new `taut/persistence/_operations.py` or a smaller clearly named
  orchestrator, client classmethod wiring, and dump tests.
- Resolve the target using the same actor-free configuration/error posture as
  `TautClient.init()`. Consider extracting one small target-resolution helper
  only if it removes literal duplication without changing existing behavior.
- Reject an SQLite output path that resolves to or is the same file as the
  source database, WAL, or SHM; cover relative paths, symlinks, and hard links.
- Snapshot core/extension logical components as deterministic records, sample
  public queue metadata, stream `dump_lines()` with the exact registry include
  set, filter alias lines, count claimed selected rows, repeat sidecar exports,
  and reject observed movement.
- Assemble, self-verify, fsync where supported, and atomically replace output.
  On every fault barrier, assert old output survival and staging cleanup.
- Use real registered chat, DM, notification, empty, search, control, foreign,
  aliased, pending, and claimed queues. Do not mock `dump_lines()` or queue
  stats in the contract tests.
- Stop if an exact-view claim requires a lock other clients do not honor or if
  any selected broker line is reconstructed by Taut.
- Done: dump selection, omission reporting, stable-view refusal, permissions,
  atomic replacement, secrets boundary, and empty-workspace cases pass.

### 6. Implement two-pass load, guard lifecycle, and recovery

- Files: persistence orchestrator, state operations, client classmethod wiring,
  focused load/fault tests, and any small platform file helper.
- Make dry-run and apply share one file/component preflight implementation.
  Verify no writes with nonexistent SQLite, existing empty SQLite, and
  PostgreSQL targets. Dry-run returns `destination_checked: false` and does not
  claim target eligibility because opening the public broker path initializes
  schema.
- Before writes, verify current component importers, logical references, exact
  nested SimpleBroker stream, and SQLite input/target path non-aliasing. Actual
  load then initializes the backend, verifies destination emptiness and exact-id
  support, and acquires the guard before domain records.
- For actual load: initialize schemas; acquire the guard; import all sidecar
  components in one transaction; feed a replayed raw
  nested iterator to `load_lines()`; clear guard only after success.
- Add deterministic fault barriers before guard, during sidecar import, after a
  partial broker batch, and at final guard clear. Both backends retain the guard
  and require recreation; SQLite must close every Taut-owned handle before the
  failure returns.
- Pin SimpleBroker's exact-id clock contract: on every backend, the first real
  `Queue.write()` after load must return an id greater than the largest restored
  id. Do not add a Taut clock write or canary message.
- Add two real concurrent loader attempts. Exactly one may acquire; neither may
  expose an unguarded partial target.
- No fixed sleeps. Use barriers, process joins, or bounded polling.
- Stop if cleanup tries to infer and repair partial PostgreSQL content, if a
  guard can clear on an uncertain result, or if dry-run creates storage.
- Done: exact-id round trip, dry-run non-mutation, fresh-only policy, recovery,
  guard, and concurrent-load tests pass on real SQLite.

### 7. Add the system adapter, reports, and user documentation

- Files: new `taut/commands/system.py`, `taut/commands/_builtins.py`,
  `taut/commands/_rendering.py`, `README.md`, `CHANGELOG.md`, CLI-claim tests,
  and public API docs in active specs.
- Implement only parsing and report rendering in the command adapter. It calls
  the actor-free classmethods and never `context.client()`.
- Reject `--as`, `--token`, and `--timestamps` regardless of root-option
  placement. Teach quiescence, secret-bearing output, fresh-target load,
  dry-run, claimed omission, and backend recovery in help without promising
  status/doctor behavior.
- Add exact JSON records and human summaries. Keep errors text-only.
- Update maintained CLI claims in the same slice and run `bin/check-cli-claims`.
- Stop if docs add top-level aliases, prompts, default paths, or unsupported
  flags.
- Done: subprocess CLI probes pass and README/CHANGELOG/spec claims match the
  shipped grammar exactly.

### 8. Add the Summon persistence contributor

- Files: `extensions/taut_summon/taut_summon/_state.py`, new
  `extensions/taut_summon/taut_summon/persistence.py` and lightweight manifest,
  `extensions/taut_summon/pyproject.toml`, extension tests, and Summon docs.
- Export deterministic durable session records only. Exclude claims and driver
  evidence. On load, require a core member, initialize the current schema, and
  write sessions through the core-supplied sidecar session with null leases.
- Test absent schema, empty initialized schema, current rows, unsupported newer
  schema, missing installed contributor, and provider-session/wired continuity.
- Keep real core/Summon sidecar and CLI integration. Only provider harness
  execution itself may be absent; no driver process needs to start for ledger
  round trip.
- Stop if the contributor needs control queues, provider credentials, an
  independent connection, or core knowledge of Summon tables.
- Done: core plus Summon round trips with claims/leases excluded and all
  durable session fields preserved.

### 9. Prove cross-backend portability and reconcile traceability

- Files: `extensions/taut_pg/tests/` integration tests only, new
  `docs/implementation/10-persistence-io.md`, implementation and
  spec indexes, repository map if package ownership changed, plan review and
  deviation logs.
- Add real SQLite to PostgreSQL, PostgreSQL to SQLite, and PostgreSQL to
  PostgreSQL round trips. Verify the same logical report and records, exact ids,
  no search state, and the backend-specific failure recovery in [PIO-7.4].
- Prove no new PostgreSQL server extension or persistence runtime module exists
  in `taut-pg`.
- Run first-search rebuilding on a loaded fixture without load-time index work.
- Add reciprocal implementation mapping only now, when code exists. Reconcile
  every spec/plan/implementation/code/test link and update the promotion
  baseline if the active spec moved.
- Run a final independent Opus completed-work review and disposition every
  finding before completion.
- Done: the full gate set is green, traceability is closed, and the plan can be
  marked completed only after the owner asks to land and `git log` verifies the
  commit.

## 8. Testing Plan

Red-green TDD is required for runtime slices. The docs-only authoring work in
this request uses reproducible document/index gates as its substitute proof;
runtime work has no TDD exception.

| Layer | Real proof | Core contracts |
|---|---|---|
| Unit | strict framing, canonical record encoding, duplicate-key parser, digest/count/order state machine, report values | [PIO-3], [PIO-4], [PIO-9] |
| Core integration | real SQLite Queue, sidecar, dump/load, registered/foreign/internal queues, exact ids, and guard | [PIO-2], [PIO-5] through [PIO-7] |
| Extension integration | real Summon schema and core member rows | [PIO-5.3], [PIO-8] |
| Cross-backend | real PostgreSQL through existing `taut-pg` target support and SimpleBroker-PG | [PIO-7.4], [PIO-10], [PIO-11] |
| CLI acceptance | installed or repository console subprocess, real files/storage, malformed and hostile inputs | [PIO-3], [PIO-6.2], [PIO-9], [PIO-11.2] |
| Operational | realistic secret-free fixture dump/load and first search on each backend | [PIO-11.3] |

Anti-mocking rules:

- never mock `dump_lines()`, `load_lines()`, exact-id insertion, queue
  selection, sidecar transactions, the SQLite file set, or PostgreSQL partial
  apply in the proof that claims those behaviors
- fault injection may wrap a named phase boundary, but the storage on either
  side stays real
- manifest unit tests may fake entry-point enumeration; at least one installed
  wheel or editable-distribution test must discover the real Summon manifest
- CLI rendering tests may substitute a report, but end-to-end CLI tests must
  exercise the actual classmethod and filesystem
- timing assertions do not prove quiescence; concurrency uses barriers and
  bounded polling, never sleep-only correctness

Enumerable firing gates must map every outer record type, component type,
report field, CLI exit class, fixed logical record type, destination state, and
listed corruption/fault phase to at least one test.

## 9. Verification and Completion Gates

Per-slice commands should use the narrowest test files first. The final runtime
gate is expected to include at least:

```bash
uv run --extra dev pytest tests/test_persistence_io.py tests/test_public_api.py tests/test_command_registry.py tests/test_cli_probes.py
uv run --project extensions/taut_summon --extra dev pytest extensions/taut_summon/tests
uv run ./bin/pytest-pg --fast
uv run --extra dev pytest
uv run ruff check taut tests bin extensions/taut_pg/taut_pg extensions/taut_pg/tests extensions/taut_summon/taut_summon extensions/taut_summon/tests extensions/taut_mcp/taut_mcp extensions/taut_mcp/tests
uv run ruff format --check taut tests bin extensions/taut_pg/taut_pg extensions/taut_pg/tests extensions/taut_summon/taut_summon extensions/taut_summon/tests extensions/taut_mcp/taut_mcp extensions/taut_mcp/tests
uv run --extra dev mypy taut tests bin/release.py extensions/taut_pg/taut_pg extensions/taut_pg/tests --config-file pyproject.toml
uv run bin/check-cli-claims
bin/check-plan-status-index
uv run bin/check-doc-paths
uv run bin/coalesce-check
git diff --check
```

The exact selectors may change only when files move; record replacements in the
plan. Success requires zero failing tests, lint/format/type errors, stale CLI
claims, malformed plan rows, dead doc paths, or unanswered review findings.

Post-release signals:

- successful dumps report the expected registered queue/message/component
  counts and no unexplained extension omission
- successful loads have no guard and preserve exact ids and cursors
- dry-run reports `destination_checked: false`; it does not initialize or
  certify a PostgreSQL destination
- failed loads retain a guard and require target recreation on both backends
- first search after load rebuilds through existing reconciliation and no load
  latency is spent indexing
- no ordinary operation, old output corruption, partial final file, traceback,
  or group-readable dump is observed

A missing component, remaining guard after claimed success, exact-id drift,
ordinary operation through a guard, or cross-component state mismatch is a
release blocker. Performance has no fixed v1 SLA, but memory must not scale with
the total message-body bytes during load preflight.

## 10. Out of Scope

- live point-in-time snapshot coordination across broker and sidecar
- backup encryption/signing/compression/upload/scheduling/retention
- dump or load filters, component selection, merge, replace, force, resume, or
  automated repair of a partially loaded PostgreSQL target
- stdin/stdout dump streaming or direct shell piping
- raw SimpleBroker dump acceptance by Taut, raw sidecar table export, or
  SimpleBroker alias preservation
- search index or job preservation and synchronous reindex on load
- Summon claims, control queues, driver leases, provider credentials, or
  starting a driver during restore
- implementation of `taut system status`, `doctor`, `tidy`, or other future
  maintenance commands
- a generic third-party persistence SDK or core knowledge of extension tables
- Weft Monitor store backup or changes in sibling repositories

## 11. Independent Review Log and Dispositions

Review path: Claude Opus, a different model family from the Codex author. Run
read-only from `/Users/van/Developer` so the reviewer can inspect Taut,
SimpleBroker, and Weft. Do not allow edits or implementation. Allow up to 15
minutes.

Required prompt stance:

> Read the Taut plan and its full proposed [PIO-*] spec draft, the active core,
> Summon, and search specs, the current Taut sidecar/command code, SimpleBroker
> [SB-IO-*], and Weft's dump/load implementation. Look for errors, bad ideas,
> latent ambiguity, silent data loss, false atomicity or snapshot claims,
> security mistakes, and performative overengineering. Prefer removing
> machinery when it does not close a real risk. Do not implement. Answer PASS
> or BLOCKED based on: (1) could you implement this confidently and correctly;
> and (2) would it materially degrade Taut's correctness, security, portability,
> or small/no-daemon character?

Every finding must be reproduced here and receive one disposition: accepted
and fixed, rejected with evidence, or out of scope with rationale. A BLOCKED
answer to either gate question blocks promotion.

| Round | Finding | Evidence | Disposition | Result |
|---|---|---|---|---|
| 1 | F1 (medium): uninitialized dump source was assigned exit 2 despite [TAUT-3.2] and dispatcher exit 1 | `NotInitializedError` is a plain `TautError`; current core specs and `_exit_code_for_exception` map no database to exit 1 | accepted: [PIO-3.1], [PIO-D2], and CLI task now retain exit 1; exit 2 is only missing input | PASS |
| 1 | F2 (medium): SQLite snapshot restore did not require closing target connections first | Weft exits its broker context before file restore; an open WAL connection can later checkpoint over restored files | accepted: [PIO-7.4], [PIO-11.2], task 6, and tests require complete handle teardown before restore plus reopen proof | PASS |
| 1 | F3 (medium): exact restored ids did not explicitly pin advancement of the destination broker clock | SimpleBroker `load_lines()` uses `insert_messages()`, whose public implementation advances `last_ts` beyond the largest inserted id | accepted: [PIO-7.3], [PIO-11.2], task 6, and every backend round trip require the first later write id to exceed the restored maximum; Taut adds no clock mutation | PASS |
| 1 | F4 (low): current-structure table could imply `_ClientBase` guard coverage includes `TautClient.init()` | `TautClient.init()` constructs a bare Queue and never calls `_ClientBase.__init__` | accepted: section 4.1 now names an independent `init` guard check; task 4 already required it | PASS |
| 1 | F5 (low): exact queue selection relies on SimpleBroker fnmatch includes plus Taut's no-glob queue grammar | [SB-IO-3] uses globs; current channel and reserved queue grammars exclude `*`, `?`, `[`, and `]` | accepted: [PIO-5.1] and invariant 2 now state the coupling and require re-review if grammar expands | PASS |
| 2 | Focused verification of accepted F1-F5 edits | Opus re-read the revised plan/spec and checked each fix against current dispatcher, client, SimpleBroker clock, SQLite WAL, and queue-grammar behavior | all five dispositions closed; no defect introduced by the fixes | PASS |
| 3 | Scoped review of zero-write dry-run, destination report field, path-alias rejection, and empty search schema | Opus confirmed the underlying SimpleBroker initialization constraint and four revised contracts, but found [PIO-3.1]'s exit-0 text still said dry-run proved target eligibility | accepted: exit 0 now says dry-run proves an internally consistent file while leaving destination eligibility unchecked | FAIL; focused recheck required |
| 4 | Focused recheck of the round-3 exit-0 correction | Opus compared [PIO-3.1] with the report fields and [PIO-7.1]'s no-open dry-run rule | false freshness promise removed; no contradiction introduced | PASS |
| 5 | B1 (blocking): channel topic could be lost because it was not visibly projected or asserted | Topic text, author, and timestamp are encoded in the exported thread `meta` JSON, but no persistence test proved that public `Channel` reconstruction survived | accepted as a proof gap, not a projection defect: SQLite and every PostgreSQL/cross-backend round trip now set a Unicode topic and assert it after load; immediate re-dump also compares the exact core payload | PASS |
| 5 | B2 (blocking): PostgreSQL had no real interrupted-load/partial-batch recovery proof | The prior PG guard test installed a marker directly and never exercised independently committed `load_lines()` batches | accepted: the real PG test now faults replay after header plus 1,000 messages, observes exactly 1,000 committed broker rows and `load_guard=1`, and proves ordinary Taut use fails closed | PASS |
| 5 | B3 (blocking): membership cursor/read state was projected but never asserted | No prior round trip left one member exactly one peer message behind and checked the restored unread result | accepted: SQLite and all PG/cross-backend fixtures now prove the exact cursor through `(unread=True, unread_count=1)` and exact unread message id | PASS |
| 5 | N1: strict nested-field validation makes Taut compatibility depend on SimpleBroker dump version 1 | `_format.py` intentionally rejects added fields even though SimpleBroker owns nested serialization | accepted: code and implementation docs now call this an explicit `simplebroker>=6.0.2` format pin that must be reviewed with any dependency-floor move | PASS |
| 5 | N2: extension freshness rows are checked outside the core guard transaction | Public broker and contributor APIs cannot join the core sidecar transaction; only core emptiness, allowed meta keys, and guard uniqueness are atomically rechecked | accepted: [PIO-7.3], the implementation note, and the deviation log now state the exact boundary and reliance on quiescence | PASS |
| 5 | N3: `queues` can be misread as nonempty queues | Reports count every registered Taut queue, including empty notification or system queues | accepted: both nested operation help pages now say receipts count every registered queue, including empty ones | PASS |
| 5 | N4: the superseded draft retains slot-07 history | The promoted active spec is slot 08 and [PIO-D8] records why; rewriting the historical draft would erase the reviewed proposal | rejected with evidence: the draft remains explicitly superseded and the active spec/index links are slot 08 | PASS |
| 6 | Focused completed-work recheck of B1-B3 and the current full patch | Opus verified exact public topic reconstruction, real PostgreSQL 1,000-row partial commit plus surviving guard, exact cursor/unread behavior, handle teardown, dump atomicity, concurrency, and bounded body-memory behavior | all three blockers closed; no new blocking correctness, data-loss, portability, or resource-lifetime defect | PASS |
| 6 | Non-blocking: an empty installed extension schema not represented by the input is rejected by its schema-version meta key | The behavior is conservative and fail-closed, but [PIO-7.2] could be read as permitting any empty extension schema | accepted: [PIO-7.2] now states that an unrepresented extension schema key is owner authority and therefore non-fresh; a Summon firing test covers the empty-table case | PASS |
| 6 | Non-blocking: message-id and message-queue validation sets scale with message count | The parser retains ids and queue names for duplicate/reference validation but never retains message bodies | no change: this is the stated bounded-index contract in [PIO-7.1], not a hidden body-memory cost | PASS |

Round-1 observations are non-blocking. O1 asked to verify the [SRCH-8.1]
citation; that exact subsection exists in the active search spec, so no edit is
needed. O2 asked that public text preserve the draft's honest no-snapshot
language; retained. O3 noted that claimed notification rows can reflect normal
inbox consumption; [PIO-5.1] now prevents reading the aggregate omission count
as a diagnosis by itself. O4 found no persistence machinery that should be
removed.

The required completed-work Opus review is recorded in rounds 5 and 6 above;
the focused recheck returned PASS after every blocking finding was closed.

## 12. Deviation Log

| Spec ref | Planned behavior | Actual behavior | Rationale | Spec proposal |
|---|---|---|---|---|
| [PIO-D8] | Promote as `docs/specs/07-persistence-io.md` | Promoted as `docs/specs/08-persistence-io.md` | The independently landed program-theory spec now owns numbered slot 07. Duplicate slot numbers would make canonical read order ambiguous. This changes only the document path, not the [PIO-*] contract. | Active spec and every maintained reference use slot 08. |
| [PIO-7.4] | Snapshot and restore a fresh SQLite target after caught load failure; PostgreSQL remains guarded | Both backends remain guarded and require target recreation; SQLite closes only its own handles and performs no snapshot, checkpoint, connection census, or rollback | SimpleBroker's revision-5 destructive-cleanup reasoning applies: a fresh-target load has no preexisting workspace authority worth preserving, cross-process quiescence cannot be proved portably, and stronger recovery machinery would overclaim undefined overlap semantics. Owner direction on 2026-08-08 explicitly rejected repeating that work. | Active [PIO-7.4], [PIO-10], and [PIO-11.2] revised before load implementation. |
| [PIO-6.1] | Stage each logical sidecar component in a separate owner-only artifact before assembly | Retain the non-message logical sidecar records and use one owner-only staged composite file | A second family of secret-bearing temporary files adds cleanup and disclosure surface without improving the only required memory bound, which is independence from broker message-body bytes. The composite is still double-serialized and self-verified before atomic replacement. | Active [PIO-6.1] now specifies deterministic logical records and one staged composite. |
| [PIO-7.2] | Freshness text named extension durable rows only | Contributor freshness rejects all extension-owned durable and transient rows | A stale Summon claim is not a load-eligible empty target. Rejecting both table families is safer and matches fresh-target semantics. | Active [PIO-7.2] clarified before completion. |
| [PIO-11.2] | Test dash-prefixed option paths using a bare `--` separator | Use argparse's attached-value form, such as `--input=-backup.jsonl` | `--input` owns a required option value; bare `--` terminates option parsing and cannot supply that value. Attached values are the unambiguous standard grammar. | Active firing text and CLI probes use the shipped grammar. |
| [PIO-7.3] | Wording could be read as atomically rechecking every broker, core, and extension freshness condition with guard insertion | Guard acquisition atomically rechecks core sidecar emptiness and allowed meta keys; public broker and contributor freshness checks occur immediately before it under the quiescence precondition | SimpleBroker and contributor APIs cannot participate in the core sidecar transaction. Claiming a wider atomic boundary would be false. A later conflict leaves the target guarded. | Active [PIO-7.3] and the implementation note state the exact boundary. |
| Implementation layout | Separate persistence `_models.py` and `_core.py` modules | Keep replay spans with the strict format parser and keep every core projection/import statement in `taut/state/_sql.py` | The types are private to one deep parser module, while a `_core.py` adapter would either contain no authority or violate the repository's single core-SQL owner. | `docs/implementation/10-persistence-io.md` maps the final ownership. |

## 13. Fresh-Eyes Review

Before promotion and before implementation completion, re-read the plan as a
zero-context engineer and check:

- every included and excluded state family has one named owner
- every secret, temp, marker, and output file has a lifecycle
- every success claim states its transaction boundary and does not overclaim
  live snapshot or PostgreSQL rollback
- the extension seam can restore Summon without core table knowledge
- all fixed records, fields, exits, and fault phases have firing tests
- dry-run cannot create a destination while trying to inspect it
- guard checks land before apply and cannot be bypassed by ordinary APIs
- exact ids remain SimpleBroker-owned, and nested lines stay unchanged
- no task asks `taut-pg` to add persistence code or a server extension
- no future `system` command is implemented by accident

Fix any gap and repeat the read. If tightening the text changes authority,
format compatibility, included state, or recovery blast radius, re-enter
classification and independent review rather than silently editing an approved
plan.
