# Persistence I/O Architecture

## Purpose and Scope

This note explains why Taut persistence I/O is a composite logical format and
where its owners live. The normative behavior is in
`docs/specs/08-persistence-io.md` [PIO-1] through [PIO-11]. The delivery record
is `docs/plans/2026-08-07-taut-dump-load-plan.md`.

The implementation owns full-workspace dump/load only. It does not turn Taut
into a backup scheduler, add merge or replace modes, or make live multi-store
snapshot claims.

## Design Rationale

### One outer format, existing component owners

SimpleBroker already owns exact message serialization and exact-id restore.
`taut/persistence/_operations.py` therefore gives registered Taut queue names
to public `dump_lines()`, retains its header and pending-message strings, and
feeds those same strings to public `load_lines()`. Taut adds outer framing and
logical sidecar components because a raw broker dump cannot reconstruct member,
thread, membership, cursor, identity, or extension authority.

The outer parser in `_format.py` is deliberately strict. It validates the full
file before opening a load target, retains byte offsets rather than message
bodies, and replays the nested broker section from disk. Framing records are
canonical UTF-8 JSON; SimpleBroker payload lines remain owned by SimpleBroker.
Taut still validates the exact nested version-1 header and message field sets.
That is an intentional compatibility pin to the `simplebroker>=7.1.0` format
contract: a future nested field requires an explicit version decision when the
dependency floor moves, rather than permissive acceptance and silent loss.
Version 1 permits canonical strings or exact JSON integer tokens for nested
`last_ts` and `id`. The validator normalizes only for bounds, ordering, and
duplicate checks, then replays the original lines unchanged to SimpleBroker.

### Logical authority, not physical tables

All core persistence SQL remains in `taut/state/_sql.py`. Its projection omits
schema rows, route-key derivations, and live process anchors, then reconstructs
the current schema from logical version-1 records. Search tables and work queues
are disposable and absent from the format. The first later search uses normal
reconciliation rather than making load depend on synchronous indexing.

Official extensions contribute through the lazy
`taut.persistence_components` entry-point group. The public manifest value is
lightweight; `_components.py` performs strict discovery only for a selected
system operation. Core owns files, framing, targets, guards, and ordering.
Contributors own their schema, logical record validation, freshness, and writes
through a supplied Queue or SidecarSession. Dump never initializes an unused
extension schema.

Summon's contributor exports durable session continuity but excludes transient
name claims and driver pid/start evidence. Its SQL stays in
`extensions/taut_summon/taut_summon/_state.py`; the component adapter only
translates and validates logical records.

Taut-owned component writers explicitly project timestamp fields through the
public formatter. Core includes its fixed per-record field inventory and the
owned nested `thread.meta.topic.updated_ts`; Summon includes only
`session.updated_ts`. Readers accept canonical strings or exact Python-parsed
JSON integer tokens and normalize before every sidecar load. This corrects the
unreleased version-1 contract in place. It adds neither a version-2 format nor
a legacy component loader, and it never rewrites opaque metadata or stored
broker bodies.

### Destructive maintenance boundary

Dump and load require operator quiescence. Public broker and sidecar APIs do not
offer one transaction across both stores. Dump samples broker state and repeats
sidecar projections to catch observed movement, but those checks are not proof
that no race happened.

Load admits only a nonexistent or fresh target. It commits authoritative
sidecar state before broker history and keeps a `taut_meta` load guard across
that gap. Ordinary current-version operations reject the guard. Any failure
after guard acquisition leaves the target guarded and disposable; the operator
recreates it and retries. This is the same destructive-operation posture as
SimpleBroker maintenance: Taut closes every handle it owns, but does not count
other processes, prove last-connection status, snapshot SQLite, or claim
rollback across independently committing stores.

Guard acquisition atomically rechecks core sidecar emptiness and allowed meta
keys. Broker and extension-owned row freshness use their public owner APIs
before that transaction; they cannot share its atomic boundary. Quiescence is
what closes that gap. If an overlapping writer violates it and a later insert
fails, the already acquired guard remains and the target is discarded.

## Boundaries and Invariants

- `_operations.py` may use only public SimpleBroker persistence and metadata
  APIs. Private broker SQL, timestamp writes, and backend-specific core branches
  are defects.
- `_format.py` must finish file and cross-component validation before actual
  load resolves or opens a destination. Broker message bodies stay on disk.
- `taut/state/_sql.py` is the sole production owner of core sidecar SQL.
  Extension SQL stays in that extension's existing state module.
- The load guard is a fail-closed recovery marker, not a distributed lock.
  Quiescence remains the operator's responsibility.
- A failed dump cannot replace an older output. A failed post-guard load is not
  repaired or rolled back in place.
- Persistence commands are actor-free. They must not construct an
  identity-bearing client, move cursors, post notices, claim notifications, or
  rebuild search synchronously.
- PostgreSQL needs the existing `taut-pg` target package but no persistence
  provider, catalog query, or compiled server extension.

## Key Files and Verification

| Path | Owner |
|---|---|
| `taut/persistence/_format.py` | Composite framing, strict streaming preflight, replay offsets, core logical validation |
| `taut/persistence/_operations.py` | Target/file lifecycle, stable-view checks, component assembly, freshness, guarded apply |
| `taut/persistence/_components.py` | Lazy official-contributor discovery and manifest validation |
| `taut/state/_sql.py` | Core logical projection/import, freshness recheck, load-guard lifecycle |
| `taut/commands/system.py` | Actor-free nested CLI grammar and report dispatch |
| `extensions/taut_summon/taut_summon/persistence.py` | Summon logical component adapter |
| `extensions/taut_summon/taut_summon/_state.py` | Summon persistence SQL and lease-clearing import |

Real SQLite format, selection, corruption, file-lifecycle, guard, failure, and
round-trip proofs live in `tests/test_persistence_io.py` and
`tests/test_persistence_io_adversarial.py`. Summon continuity proof lives in
`extensions/taut_summon/tests/test_persistence.py`. Real PostgreSQL native and
both-direction cross-backend proofs live in
`extensions/taut_pg/tests/test_persistence_io.py`.

## Change Guidance

Read [PIO-2], [PIO-4], [PIO-7], and [PIO-8] before changing the format or apply
order. A new component or logical record version needs a spec revision and
backward-load tests. Do not solve an observed maintenance race by adding a lock
that ordinary clients do not honor. If stronger live-backup semantics become a
product goal, treat that as a new cross-store protocol rather than extending
the version-1 guard.

## Related Plans

- `docs/plans/2026-08-07-taut-dump-load-plan.md`
- `docs/plans/2026-08-06-taut-search-plan.md`
