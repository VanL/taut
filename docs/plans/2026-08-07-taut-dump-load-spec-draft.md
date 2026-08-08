# Taut Persistence I/O: Proposed Spec Draft

Date: 2026-08-07

Status: draft. This file is the review target for
`docs/plans/2026-08-07-taut-dump-load-plan.md`. The spec-promotion slice copies
the accepted text to `docs/specs/07-persistence-io.md` with `Status: Active`
and applies the companion deltas in section 12. Until that slice, the governing
contract remains the spec tree at
`847516f04ec9d2d8da7d3b17dd4008af9e07dcaf`.

## 1. Purpose and Scope [PIO-1]

Taut persistence I/O exports one workspace to a portable logical file and
restores it into a fresh Taut target. A complete export includes the registered
SimpleBroker queues that Taut owns, Taut's authoritative core sidecar state,
and durable state contributed by installed Taut extensions. It deliberately
excludes disposable indexes, work queues, process leases, configuration, and
foreign broker queues.

The command surface is:

```text
taut system dump --output FILE
taut system load --input FILE --dry-run
taut system load --input FILE
```

`system` is the core-owned namespace for actor-free workspace maintenance.
Version 1 implements only `dump` and `load`. Future commands such as `status`
or `doctor` may live there, but this spec does not reserve their behavior or add
placeholder parsers.

This spec governs the composite file format, dump selection, sidecar logical
records, extension contribution, consistency limits, load preflight, recovery,
CLI and Python surfaces, and cross-backend verification.

Out of scope for version 1:

- merge, replace, selective-component, incremental, resume, or in-place repair
  loads
- dumping to stdout or loading from stdin
- encryption, signing, compression, remote storage, retention, or scheduling
- a point-in-time live backup claim while writers remain active
- raw SQL table dumps or physical SQLite/PostgreSQL backup formats
- exporting unknown SimpleBroker queues or SimpleBroker aliases
- a portable Weft Monitor store format; Weft's operational JSONL and reports
  do not reconstruct its physical monitor state and are not a Taut format

## 2. Mental Model and Invariants [PIO-2]

### [PIO-2.1] One Taut format, composed from logical components

The outer format is versioned UTF-8 NDJSON named `taut-dump`. It is not a file
that claims to be `simplebroker-dump` while appending private record types.
Instead, one delimited component contains a valid SimpleBroker dump stream and
other delimited components contain logical Taut records.

Core passes every retained SimpleBroker header or message line from public
`simplebroker.dump_lines()` through unchanged. On load, core extracts that
component and passes its lines to public `simplebroker.load_lines()`. Taut owns
the outer framing, queue selection, sidecar components, validation, and recovery
policy. It does not copy SimpleBroker's format implementation or access private
broker tables.

### [PIO-2.2] Authority and derivation

The dump contains state needed to restore Taut behavior:

- pending rows from registered Taut thread queues, with exact message ids
- core member, alias, identity-claim, thread, membership, cursor, topic, DM,
  notification, and completed channel-rename state
- durable logical records from recognized installed extensions

The dump does not contain state that can be rebuilt or that represents a live
process:

- `taut_search_*` tables and `taut.search_index*` queues
- transient extension claims or work/control queues
- live member anchors or extension driver leases
- project configuration, backend credentials, terminal policy, or environment

Search remains a disposable view under [SRCH-2.1]. The first later search uses
the existing absent-watermark reconciliation path; load does not synchronously
index restored history.

### [PIO-2.3] Exact identifiers, logical schema

Message ids, member ids, continuity tokens, claim hashes, thread names,
membership cursors, timestamps, and extension continuity ids are restored
exactly. Exact message ids are load-bearing because cursors, sub-thread origins,
notifications, reactions, and extension state may refer to them.

Physical table layouts and schema-version rows are not dump contracts. Core and
each extension initialize their current schema, then translate logical records
into it. A `taut-dump` format version and a component format version therefore
do not equal a database schema version.

### [PIO-2.4] Maintenance requires quiescence

Dump and load are maintenance operations. The operator must stop Taut writers,
watchers, Summon drivers, foreign SimpleBroker consumers, and other processes
that can mutate the selected broker or sidecar state for the operation's full
duration.

SimpleBroker dump is a logical export, not a point-in-time snapshot under
concurrent writers [SB-IO-2]. The current public broker and sidecar APIs do not
offer one transaction spanning both stores. Taut samples broker metadata and
compares independently serialized sidecar components before and after broker
export. It refuses activity it observes, but a successful check is not proof
that no invisible race occurred. Exact cross-component state requires actual
quiescence. Taut does not add a global workspace lock that other clients do not
honor.

### [PIO-2.5] No identity or chat side effects

`system dump`, `system load --dry-run`, and the read/validation phases of
`system load` do not resolve or create an actor, capture identity evidence,
touch activity, change membership, advance a cursor, claim a notification, or
enqueue search work. A successful load writes only the state represented by the
dump plus temporary load-guard state. It does not emit chat notices.

## 3. Public Surfaces [PIO-3]

### [PIO-3.1] CLI grammar and namespace

The built-in `system` command owns required nested subparsers:

```text
taut system dump --output FILE
taut system load --input FILE [--dry-run]
```

`--output` and `--input` are required file paths. Relative paths resolve from
the current working directory. Dump atomically replaces an existing output only
after the new file is complete and durable enough for the current platform.
Load never reads stdin and dump never writes the dump body to stdout.

The `system` manifest accepts only the root `--db`, `--json`, and `--quiet`
options after the verb. Supplying actor selectors or `--timestamps` before or
after `system` is a usage error. The command never prompts.

The exit classes are:

- 0: dump completed; dry-run preflight found a valid internally consistent file
  while leaving destination eligibility unchecked; or load completed and
  cleared its guard
- 1: usage, malformed or incompatible dump, digest mismatch, output or input
  I/O error other than a missing input, observed source activity, incomplete
  channel rename, unrecognized durable extension state, unavailable component
  importer, non-fresh destination, backend error, or any failed apply/recovery
- 2: the named input file is absent

An uninitialized source follows [TAUT-3.2]'s existing no-database contract:
exit 1 with the `taut init` hint.

An unknown `system` operation and a missing nested operation use the normal
usage-on-stderr exit 1 contract. There are no top-level `taut dump` or
`taut load` aliases.

### [PIO-3.2] Python API

The actor-free embedding surface is:

```python
TautClient.dump(
    *,
    output: str | Path,
    db_path: str | Path | None = None,
) -> DumpReport

TautClient.load(
    *,
    input_path: str | Path,
    db_path: str | Path | None = None,
    dry_run: bool = False,
) -> LoadReport
```

Both are class methods like `TautClient.init()`. They do not instantiate an
identity-bearing client. `DumpReport`, `LoadReport`, and
`PersistenceComponentReport` are frozen, slotted public values exported from
`taut.client` and lazily from `taut`.

`PersistenceComponentReport` has exact fields:

```python
name: str
version: int
records: int
```

`DumpReport` has exact fields:

```python
path: str
format: str
version: int
components: tuple[PersistenceComponentReport, ...]
queues: int
messages: int
omitted_claimed_messages: int
```

`LoadReport` has the same `format`, `version`, `components`, `queues`, and
`messages` fields plus:

```python
path: str
dry_run: bool
destination_checked: bool
applied: bool
```

`applied` is false exactly for a successful dry-run and true exactly after the
guard has been cleared on a completed load. `destination_checked` is false for
dry-run and true for a completed actual load. The field prevents an agent from
mistaking file validation for a promise that the target is still fresh.

### [PIO-3.3] Output

Human success output is one concise summary naming the path, component count,
queue count, message count, and claimed-message omission count when nonzero.
Dry-run says explicitly that it wrote nothing. Quiet mode emits no success
record but preserves exit status and diagnostics.

`--json` emits exactly one NDJSON object. Dump uses:

```json
{"components":[{"name":"simplebroker","records":43,"version":1},{"name":"taut-core","records":17,"version":1}],"format":"taut-dump","messages":42,"omitted_claimed_messages":0,"path":"/work/backup.jsonl","queues":3,"type":"system_dump","version":1}
```

Load uses:

```json
{"applied":false,"components":[{"name":"simplebroker","records":43,"version":1},{"name":"taut-core","records":17,"version":1}],"destination_checked":false,"dry_run":true,"format":"taut-dump","messages":42,"path":"/work/backup.jsonl","queues":3,"type":"system_load","version":1}
```

The field sets are exact. Errors remain concise text on stderr under
[TAUT-8.2]; there is no JSON error envelope.

## 4. Composite File Contract [PIO-4]

### [PIO-4.1] Encoding and canonical Taut records

The file is strict UTF-8 NDJSON with one JSON object per nonempty line and one
LF after every line, including the final line. Blank lines, a byte-order mark,
non-object JSON values, invalid UTF-8, and trailing bytes are invalid.

Taut-owned lines use `ensure_ascii=False`, sorted keys, compact separators, and
literal UTF-8. Strings therefore retain Unicode rather than being reduced to
ASCII escapes. SimpleBroker payload lines retain the exact strings returned by
`dump_lines()`.

Unknown outer record types, unknown fields on a version-1 framing record,
duplicate fields, duplicate components, and records outside a component are
errors. Component payload field policy belongs to that component version.

### [PIO-4.2] Framing and digests

The first line is the outer header:

```json
{"components":[{"name":"simplebroker","version":1},{"name":"taut-core","version":1}],"format":"taut-dump","type":"header","version":1}
```

Components appear in the header order. `simplebroker` is first, `taut-core` is
second, and extension components follow in lexical name order. Each component
is framed by:

```json
{"name":"simplebroker","type":"component_start","version":1}
... payload lines ...
{"name":"simplebroker","records":43,"sha256":"<64 lowercase hex>","type":"component_end"}
```

The component digest covers the exact UTF-8 payload bytes including each LF,
but excludes start and end records. The final line is:

```json
{"components":2,"records":60,"sha256":"<64 lowercase hex>","type":"end"}
```

The final digest covers every prior byte in the file, including framing LFs.
`records` counts payload records, not framing records. Digests detect truncation
and accidental corruption. They provide no authenticity or protection from a
malicious party able to rewrite the file and recompute hashes.

### [PIO-4.3] SimpleBroker component

The SimpleBroker payload is itself a valid `simplebroker-dump` v1 stream:

1. one unchanged SimpleBroker header line
2. zero or more unchanged message lines
3. no alias lines

Messages are ordered as SimpleBroker emits them: queue name ascending, then
message id ascending. The outer validator requires the nested header format and
version, rejects alias and unknown nested record types, and verifies every
message queue is present in the Taut core thread component. It supplies the
retained lines unchanged to `load_lines()`.

### [PIO-4.4] Taut core component

The `taut-core` component version is 1. Payload records appear in this order,
then by the listed stable sort key:

| Record `type` | Logical fields | Sort key |
|---|---|---|
| `member` | `member_id`, `display_name`, `kind`, `uid`, `host_id`, `host_label`, `token`, `meta`, `created_ts`, `last_active_ts` | `member_id` |
| `member_alias` | `alias_key`, `member_id`, `created_ts` | `alias_key` |
| `identity_claim` | `claim_hash`, `member_id`, `claim_kind`, `host_id`, `host_label`, `evidence`, `first_seen_ts`, `last_seen_ts` | `claim_hash` |
| `thread` | `name`, `kind`, `parent`, `origin_ts`, `created_by`, `meta`, `created_ts` | `name` |
| `membership` | `thread`, `member_id`, `joined_ts`, `last_seen_ts` | `(thread, member_id)` |
| `channel_rename` | `old_name`, `new_name`, `state`, `affected`, `started_ts`, `updated_ts` | `old_name` |

`meta` and `evidence` are parsed JSON values, not double-encoded SQL strings;
the current core validators govern their required shapes while preserving
allowed unknown keys. `name_key` is recomputed from `display_name` and is not a
wire field. Member `anchor_pid`, `anchor_start_time`, and `fingerprint` are
current process-recognition evidence, not portable identity authority. They are
omitted and load as null. Durable identity claims and continuity tokens remain.

Only completed channel-rename rows are legal. Dump refuses while any rename is
incomplete, using the existing recovery diagnostic and command. Load rejects a
non-completed rename record.

Core schema-version rows and operational load-guard rows are never payload
records. The destination writes its current core schema version.

## 5. Selection and Extension State [PIO-5]

### [PIO-5.1] Registered broker queues only

Core reads the authoritative `taut_threads` registry and gives its exact queue
names to `simplebroker.dump_lines()` as the include set. It retains the nested
header and message records, drops all SimpleBroker alias records, and rejects a
message for any other queue.

This includes pending chat, notification, and registered system queue rows. It
includes empty threads through the core registry even though SimpleBroker emits
no record for an empty queue. Claimed rows are omitted according to [SB-IO-2]
because they are already consumed/deletion-pending, not restorable pending
stock. The success report states their count for selected queues.

Foreign queues, unregistered `sys.*` control queues, search work queues,
extension runtime queues, and SimpleBroker aliases are excluded even when they
exist in the same backend.

SimpleBroker `include` values are fnmatch globs [SB-IO-3], not exact-name
selectors. Taut's registered queue grammars exclude the glob metacharacters
`*`, `?`, `[`, and `]`, so passing canonical registered names is exact. Adding
one of those characters to a future queue grammar requires this selection rule
and its tests to change first.

The claimed omission total covers all selected queues. Claimed chat rows often
indicate a foreign consumer; claimed notification rows may be ordinary already-
consumed inbox pointers. The count reports pending stock that will not be
restored. It does not by itself diagnose data loss.

### [PIO-5.2] Derived and transient state

The following are always excluded:

- every `taut_search_*` object and every search pending, claimed, or failed job
- `taut_summon_claims`
- Summon `sys.ctl_*` and `sys.rsp_*` queues
- member live-anchor fields and Summon driver pid/start-time fields
- any temporary dump file, load snapshot, or load-guard value

Exclusion is semantic, not prefix-only. An extension contributor must classify
each owned state family as durable or transient in its component contract.

### [PIO-5.3] Summon component

When installed Summon state exists, `taut-summon` contributes component
`taut-summon` version 1. It exports one `session` record per
`taut_summon_sessions` row with:

```text
member_id, token, provider, provider_session_id, wired, updated_ts
```

It does not export `taut_summon_claims`, `driver_pid`, or
`driver_start_time`. Load initializes the current Summon schema, verifies every
session member exists in `taut-core`, inserts the logical session, and leaves
driver evidence null. Provider-session continuity and the durable wired flag
survive; no restored row claims that an old process is live.

### [PIO-5.4] Unknown durable extension state fails closed

Every extension-owned durable sidecar schema that participates in Taut backup
must own a version key in `taut_meta` and register one persistence component.
Core reads every `taut_meta` key. It recognizes its own schema and load-guard
keys and requires every other key to be claimed by exactly one installed
component manifest. An unclaimed key, a duplicate claim, an unavailable
component, or a component that cannot read its stored schema fails dump before
the final output is replaced.

This rule prevents a successful-looking backup from silently omitting durable
state left by an uninstalled or incompatible extension. Search uses its own
disposable metadata table and is not a persistence component.

## 6. Dump Operation [PIO-6]

### [PIO-6.1] Preflight and stable-view check

Dump resolves the target without identity, verifies the current core schema,
refuses an active load guard, refuses an incomplete channel rename, discovers
component manifests, and validates all `taut_meta` key ownership before writing
the destination.

It then:

1. serializes each sidecar component to deterministic logical records
2. samples public broker queue metadata for the registered queue set
3. streams the selected SimpleBroker component to staging
4. samples the same broker metadata again
5. serializes every sidecar component again and compares digests
6. refuses and removes staging if either broker metadata or sidecar digests
   changed
7. assembles those records in one owner-only staged composite and verifies it

These checks catch observed movement. They do not weaken [PIO-2.4]'s quiescence
requirement or turn the result into a database snapshot claim.

### [PIO-6.2] File lifecycle and permissions

All staging files are created owner-only. The completed dump is mode `0600` on
POSIX. Core writes in the destination directory, flushes and fsyncs the file
where supported, verifies its own final digest, then atomically replaces the
named output. Failure before replacement leaves any older output untouched and
removes temporary artifacts best-effort. No partially written dump appears at
the final path.

For SQLite, preflight rejects an output path that resolves to or is the same
file as the source database or its `-wal`/`-shm` companions. Resolution covers
relative paths and symlinks; existing-file identity checks cover hard links.
Dump must never replace storage it is exporting.

The dump contains chat text, member continuity tokens, identity evidence that
may include host and process details, and extension continuity tokens. It is a
secret-bearing backup. Taut does not offer a redacted mode because redaction
would not restore the same workspace.

Project `.taut.toml`, `.broker.toml`, backend connection strings, environment
variables, and external provider credentials are never read into the dump.

## 7. Load Operation [PIO-7]

### [PIO-7.1] Full preflight before writes

Load makes no destination writes until it has read the full file and validated:

- strict UTF-8, framing, order, counts, component and final digests
- outer, nested SimpleBroker, core, and extension versions
- exact field sets, types, identifier grammar, timestamp bounds, uniqueness,
  and current logical JSON shapes
- core foreign-key and structural relations, without inventing a requirement
  that deleted historical messages still exist
- every broker message queue against the core thread registry
- every extension's cross-component references
- installed importer availability for every file component

The implementation may scan the input more than once and retain bounded
indexes or section offsets. It must not require all message bodies to fit in
memory. `--dry-run` executes this same file and component preflight, but does
not open or initialize the destination to inspect broker or sidecar state. The
current public SimpleBroker connection path initializes backend schema, so
claiming a zero-write PostgreSQL eligibility check would be false. A successful
dry-run therefore returns `destination_checked: false`; actual load repeats the
file preflight and checks [PIO-7.2] immediately before guard acquisition.

Dry-run does reject an input path that resolves to or is the same existing file
as a selected SQLite destination or its `-wal`/`-shm` companions. It does not
open that destination to do so.

### [PIO-7.2] Fresh destination only

Version 1 loads only into a nonexistent SQLite target or a fresh/empty resolved
target. An initialized target is eligible when it contains the current empty
core schema and no broker aliases, pending or claimed messages, core domain
rows, active load guard, or extension-owned durable or transient rows. Empty
disposable search
schema objects do not make a target non-fresh; any pending or claimed search or
runtime queue row is a broker message and does.

There is no merge, replace, force, or selective-component escape hatch. A
nonempty or previously failed target exits 1 before applying the file. The
operator must choose a fresh target or recreate the failed one.

### [PIO-7.3] Load guard and apply order

Actual load requires quiescence, then:

1. creates or validates the current core schema and required extension schemas
2. checks destination eligibility, then atomically inserts a unique `taut_meta`
   load-guard record after rechecking destination emptiness; concurrent loads
   cannot both acquire it
3. loads core and extension logical records in dependency order in one sidecar
   transaction
4. passes the unchanged nested SimpleBroker lines to `load_lines()` so exact
   message ids are restored
5. deletes the guard in one final sidecar transaction

`load_lines()` delegates exact-id insertion to SimpleBroker's public
`insert_messages()` path, which advances the broker timestamp counter beyond
the largest restored id. The first later broker write must therefore receive an
id greater than every restored id. Load must not emulate or separately mutate
that clock.

All ordinary current-version Taut client construction, `init`, dump, search,
and extension commands must fail closed with an actionable
"load incomplete; recreate the target" diagnostic while the guard exists.
The guard is not a general cross-version lock. Quiescence remains required,
and an older Taut process must not be used during the maintenance window.

Authoritative sidecar state commits before broker history, matching
[TAUT-10]'s authority-first ordering. The guard makes the intermediate state
unusable. Search state stays absent and is rebuilt later through [SRCH-10].

### [PIO-7.4] Failure and recovery

For file-backed SQLite, load snapshots the database plus existing `-wal` and
`-shm` companions before marker acquisition. Any caught failure after writes
begin first closes every Queue, broker connection, and sidecar handle for the
target, then restores that snapshot and removes newly created companions.
Restoring while a target connection remains open is forbidden because a later
WAL checkpoint could overwrite the restored files. Snapshot restore failure is
reported as an unsafe target. An abrupt process or host failure may leave the
guard and requires target recreation; Taut makes no automatic orphan-snapshot
recovery claim.

For PostgreSQL, the public SimpleBroker load path may commit message batches
independently of the sidecar transaction, so Taut must not claim atomic
rollback. Any failure after guard acquisition leaves the guard in place and
the target unusable. The operator recreates the fresh destination and reruns
the already preflightable dump. Core does not add PostgreSQL-specific SQL or a
compiled server extension to simulate atomicity.

A failure clearing the final guard is a failed load even when every logical
record was written. The target remains fail-closed and must be recreated. Taut
does not guess that the preceding writes were complete.

## 8. Extension Component Boundary [PIO-8]

### [PIO-8.1] Manifest discovery

Installed durable-state contributors use entry-point group
`taut.persistence_components`. Entry-point keys and manifest names match and
are unique. Root help and unrelated commands do not enumerate this group; only
selected `system dump` or `system load` code loads it.

The lightweight manifest shape is:

```python
PersistenceComponentSpec(
    component_api_version=1,
    name="taut-summon",
    write_version=1,
    load_versions=frozenset({1}),
    schema_keys=frozenset({"summon_schema_version"}),
    implementation="taut_summon.persistence:create_component",
)
```

Names match `^[a-z][a-z0-9-]{0,31}$`. Missing, malformed, duplicate, or
incompatible manifests fail only the selected system operation with the
distribution and entry-point identity; they do not break root help or chat.

### [PIO-8.2] Contributor ownership

A contributor owns:

- classification of its sidecar rows as durable or transient
- current-schema initialization through the core-supplied queue
- deterministic logical record production for its write version
- exact validation for every supported load version
- insertion into its tables through a core-supplied sidecar session
- cross-component validation through a read-only core summary

Core owns framing, file and temp lifecycle, digests, target resolution,
quiescence policy, marker lifecycle, apply order, reporting, and error
containment. Contributors must not construct queues, open independent database
connections, touch broker-private tables, emit configuration or credentials,
or create their own dump files. Core supplies a fresh replayable iterator for
validation and load rather than requiring contributors to retain all records.

The component API is an internal official-extension seam, not a general public
plugin SDK. One contributor failure is fatal to dump or preflight because a
partial backup must not look complete.

## 9. Failure Modes and Edge Cases [PIO-9]

- A malformed line reports its 1-based file line and component when known. No
  parser, extension, backend, or restore failure exposes a traceback.
- Duplicate ids, route keys, claims, component names, records, or destination
  rows fail before writes when discoverable in preflight.
- A file with valid JSON but a wrong digest, count, order, nested header, or
  footer is corrupt and rejected.
- A newer outer or component version is rejected with the installed supported
  versions. No best-effort downgrade or unknown-component skip occurs.
- Claimed selected rows are omitted and counted. Dump does not resurrect them.
- A sidecar component that changes during the dump causes failure even when
  broker metadata is stable. Broker movement causes failure even when sidecar
  state is stable.
- Output-parent errors and atomic-replace errors leave the prior destination
  file unchanged when the platform operation permits that guarantee.
- Provider or extension state that cannot be represented without credentials
  is not durable Taut state; the contributor must fail rather than embed those
  credentials.
- Empty workspaces round-trip: the dump still contains SimpleBroker and core
  headers/components, with zero payload messages and domain records.

## 10. Backend and Dependency Contract [PIO-10]

SQLite and PostgreSQL use the same outer format, logical component records,
public API, CLI, selection rules, reports, and preflight. A dump from either
backend is intended to load into the other when all represented component
implementations are installed.

All core sidecar SQL remains qmark-parameterized Taut SQL executed through
`Queue.sidecar()`. PostgreSQL target resolution still requires the existing
`taut-pg` package, but persistence I/O adds no PostgreSQL implementation to
`taut-pg`, no PostgreSQL branch in core domain semantics, and no required
non-built-in PostgreSQL server extension. The backend-specific difference is
only the recovery guarantee in [PIO-7.4].

Raw `simplebroker-dump` files remain usable through SimpleBroker's own load
surface, but they are not accepted by `taut system load` because they cannot
restore Taut sidecar authority.

## 11. Verification Expectations [PIO-11]

### [PIO-11.1] Real-boundary proof

Tests must keep real SimpleBroker queues, `dump_lines()`, `load_lines()`,
sidecar sessions, SQLite files, and PostgreSQL integration live. They may use
fault barriers around named phase boundaries, but must not mock the broker or
sidecar behavior whose crash result is under test.

Required round trips include SQLite to SQLite, SQLite to PostgreSQL,
PostgreSQL to SQLite, and PostgreSQL to PostgreSQL. Each proves exact message
ids, member ids, tokens, aliases, claims, thread metadata, memberships,
cursors, completed rename rows, notification rows, and supported extension
state. They also prove member anchors and Summon driver leases are cleared.

### [PIO-11.2] Firing matrix

At minimum, firing tests cover:

- every core logical record type and every fixed report field
- exact registered-queue inclusion; empty registry threads; foreign queue,
  SimpleBroker alias, search, control, claim, and derived-table exclusion
- claimed-row omission and count
- UTF-8 content, malformed/non-UTF-8/truncated input, duplicate JSON keys,
  wrong count/hash/order, unknown version/component/field, and huge streaming
  input without full message-body retention
- owner-only output, atomic replacement, unwritable output, temp cleanup, and
  no configuration or credential bytes
- incomplete rename, source load guard, changing sidecar, changing broker
  metadata, unknown `taut_meta` key, and missing component importer
- dry-run byte-for-byte destination non-mutation, `destination_checked: false`,
  and file/component report equality with apply preflight
- output/input SQLite database, WAL, SHM, symlink, and hard-link identity
  rejection before any target mutation
- nonexistent/fresh/nonempty/failed destinations and two concurrent loaders
- fault after marker, during sidecar load, after a partial broker batch, and
  during final marker clear, with SQLite restore and PostgreSQL fail-closed
  evidence; SQLite proof closes all handles before restore and reopens the
  target to observe the original empty state
- on every backend, the first ordinary `Queue.write()` after a successful load
  returns an id greater than the maximum restored message id
- no actor capture, activity, cursor, membership, notice, notification claim,
  search job, or synchronous index mutation
- public CLI help, globals, paths beginning with `-` via attached option values
  such as `--input=-backup.jsonl`, JSON,
  quiet mode, 0/1/2 exits, and no traceback

Cross-backend logical results must match. Recovery guarantees are deliberately
different and must be asserted as specified rather than normalized by mocks.

### [PIO-11.3] Operational acceptance

Before release, run one manual or scripted restore of a realistic secret-free
fixture on each backend. Record dump size, dump and load duration, component
counts, message count, omitted claims, first-search rebuild behavior, and
absence of a load guard after success. A remaining guard, digest mismatch,
unexpected component omission, changed exact id, or ordinary operation that can
run through a guard blocks release.

## 12. Proposed Companion Spec Deltas

These changes promote with `docs/specs/07-persistence-io.md`.

### [PIO-D1] `docs/specs/02-taut-core.md` [TAUT-1] and [TAUT-3.3]

Add persistence I/O to the governed core surface and point its full contract to
`docs/specs/07-persistence-io.md` [PIO-1] through [PIO-11].

Append to [TAUT-3.3]:

> `taut_meta` may also hold the core-owned transient load guard defined by
> [PIO-7.3] and extension schema-version keys governed by [PIO-5.4]. Neither is
> exported as a raw meta row. While the load guard exists, every ordinary Taut
> operation fails closed; only persistence-load recovery inspection may read
> the target.

### [PIO-D2] `docs/specs/02-taut-core.md` [TAUT-8.1]

Add this verb row:

> | `system dump --output FILE` / `system load --input FILE [--dry-run]` |
> Actor-free full-workspace maintenance under spec 07. Dump writes an
> owner-only composite logical backup; load preflights or restores it into a
> fresh target. | 0 success; 1 usage/validation/conflict/I/O/backend/apply
> error; 2 missing input |

An uninitialized dump source retains [TAUT-3.2]'s exit 1 plus `taut init` hint.

State that `system` requires one nested operation, is core-owned, accepts only
`--db`, `--json`, and `--quiet`, and currently implements no `status` or
`doctor` operation.

### [PIO-D3] `docs/specs/02-taut-core.md` [TAUT-8.2]

Add the exact one-record `system_dump` and `system_load` JSON shapes from
[PIO-3.3]. State that the dump body never uses stdout and that dry-run emits a
normal success record with `dry_run: true`, `destination_checked: false`, and
`applied: false`.

### [PIO-D4] `docs/specs/02-taut-core.md` [TAUT-8.3]

Add `DumpReport`, `LoadReport`, and `PersistenceComponentReport` to public
exports and add the exact `TautClient.dump()` and `TautClient.load()` class
method signatures from [PIO-3.2]. State that these methods bypass identity-
bearing client construction.

### [PIO-D5] `docs/specs/02-taut-core.md` [TAUT-8.6] and [TAUT-10]

Add `system` as a core nested-command adapter like `message` and `channel`, but
with actor-free maintenance policy. Add `taut.persistence_components` as a
lazy selected-command-only manifest group. Installed extensions may contribute
logical state but may not add or override `system` operations.

Append to [TAUT-10]:

> Persistence load writes authoritative sidecar state before broker history
> and keeps a fail-closed load guard across that boundary [PIO-7.3]. No
> ordinary operation may observe or repair the intermediate target.

### [PIO-D6] `docs/specs/04-summon.md` [SUM-8]

Append:

> Summon participates in Taut persistence I/O through the `taut-summon`
> component [PIO-5.3]. Durable session continuity (`member_id`, token,
> provider, provider session id, wired, updated timestamp) is exported.
> Bootstrap claims and driver pid/start-time evidence are transient and are
> never exported; restored driver evidence is null.

### [PIO-D7] `docs/specs/06-search.md` [SRCH-2.1], [SRCH-8.1], and [SRCH-10.3]

Append:

> Taut persistence dumps exclude every search table and work queue. A restored
> workspace starts with no search generation or jobs; the existing absent-
> watermark reconciliation or explicit `--reindex` rebuilds from canonical
> broker history and registry state. Load never gates on indexing.

### [PIO-D8] Spec and documentation indexes

Add `07-persistence-io.md` to `docs/specs/00-specs-index.md` and the thin specs
README; add the implementation architecture note created by the plan to the
implementation index; update docs-reference and CLI-claim firing gates for the
new spec family and maintained commands.

## Related Plans

- `docs/plans/2026-08-07-taut-dump-load-plan.md` (draft) defines promotion,
  implementation slices, hardening gates, and independent review.
