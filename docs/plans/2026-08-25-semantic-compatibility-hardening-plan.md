# Semantic Compatibility Hardening Plan

Status: active. Rebased on `28376fe9bfb39210b570e4c91dca40abece0027d`
after the SimpleBroker 8 and E2 landings. Fresh independent review found no
blocker. The owner ratified the plan for implementation on 2026-08-28, and the
exact spec delta is promoted in the working tree.

Class: 5. This plan changes normative configuration, schema, identity,
diagnostic, and first-party provider-discovery contracts. Hardening is required
because it touches persisted state, a ranged dependency, Windows identity
continuity, and separately released search providers.

Plan type: implementation with spec revision and one durable lesson.

Promotion strategy: A. Ratify and promote the exact spec text below before
behavior tests or production code change.

## Goal

Make compatibility checks enforce facts needed for correct behavior, not
incidental physical order or whole-inventory equality.

Address eight concrete findings:

1. allow additional resolver-owned SimpleBroker output keys without weakening
   Taut-owned input isolation;
2. read existing search schema versions before current-shape insert or provider
   DDL on SQLite and PostgreSQL;
3. state an executable rule for future columns on installed core tables;
4. classify Windows executable spellings into their existing process families
   without changing raw identity evidence;
5. replace target-shaped Summon v2 migration fixtures with one historical v2
   fixture;
6. replace PostgreSQL ordinal and closed-table assertions with named semantic
   assertions;
7. make doctor use the same schema-version interpretation as ordinary startup;
   and
8. filter search-provider ownership before counting ambiguous claims.

This is not a general leniency project. Newer unsupported versions, missing or
renamed Taut-owned config inputs, missing required columns or constraints,
unknown durable extension state, duplicate official providers, persistence
field order, and digests remain strict for correctness reasons.

## Finding Register

| ID | Current problem | Planned correction | Contract owner |
|---|---|---|---|
| SC-1 | `load_config()` and `freeze_broker_config()` require exact equality between Taut's translated inputs and the resolver's outputs. A compatible SimpleBroker canonical-key addition can abort every config path. The same boundary identifies an unknown upstream key by exact matching of human-readable `InvalidConfigError.expected` text. | Keep the Taut input translation closed and strict; require every translated key to survive; retain additional canonical output from the strict ambient-free resolver. Use a public strict-default containment probe, not diagnostic wording, to detect removed keys. Do not enforce whole-output inventory equality at runtime or in CI. | [TAUT-3.2] |
| SC-2 | Both search providers run a current-shape metadata insert before reading stored schema and projection versions. | On an existing metadata table, read and classify the stable version fields before current-shape insert or other provider DDL. | [SRCH-6.2] |
| SC-3 | [TAUT-3.3] permits a nullable column addition, but rerunning `CREATE TABLE IF NOT EXISTS` cannot alter an installed table. | Any future column on an installed table must ship an explicit idempotent reconciliation or a versioned migration with proof from state made by the actual predecessor producer. Editing current create DDL alone is invalid. | [TAUT-3.3] |
| SC-4 | `cmd.exe`, `powershell.exe`, `pwsh.exe`, and shell names with `.exe` are selected as agent anchors. | Normalize executable suffixes for classification only and add Windows shell families. Preserve raw evidence and claim inputs. | [IAN-3.2], [IAN-3.3] |
| SC-5 | Summon migration tests create v3, drop the v3 index, and rewrite the marker to 2. | Install one checked-in historical v2 fixture directly. | [SUM-8], [SUM-12] |
| SC-6 | PostgreSQL tests assert ordinal column order and closed `taut_%` / `taut_search_%` table lists. | Assert required table and required name-to-type subsets, logical constraints, owned indexes, and behavior. | [TAUT-3.3], [SRCH-6.2] |
| SC-7 | Doctor rejects `02` while ordinary startup accepts it as schema version 2. | Share the existing integer interpretation. Keep canonical writes; do not introduce a stricter storage grammar in this plan. | [TAUT-3.3], [DOCT-4.1] |
| SC-8 | Search discovery counts foreign and official same-name claims together before checking ownership. | Filter normalized `taut-pg` ownership first; require exactly one official claim and never load foreign claims. | [SRCH-7] |

## Sources and Baseline

Normative sources:

- `docs/specs/02-taut-core.md` [TAUT-3.2], [TAUT-3.3]
- `docs/specs/03-identity-addressing-notifications.md` [IAN-3.2],
  [IAN-3.3], [IAN-10]
- `docs/specs/04-summon.md` [SUM-8], [SUM-12]
- `docs/specs/06-search.md` [SRCH-6.2], [SRCH-7]
- `docs/specs/09-system-doctor.md` [DOCT-4.1]

Implementation context:

- `docs/implementation/04-taut-architecture.md`
- `docs/implementation/05-taut-summon-architecture.md`
- `docs/implementation/09-search-architecture.md`
- `docs/implementation/11-system-doctor.md`
- `docs/plans/2026-08-24-concurrency-and-schema-contract-alignment-plan.md`
- `docs/plans/2026-08-13-simplebroker-config-isolation-plan.md`
- `docs/plans/2026-08-13-ranged-dependency-policy-plan.md`
- `docs/plans/2026-08-28-simplebroker-8-reconciliation-plan.md`
- SimpleBroker `v8.0.0` at
  `194dea5bd4841f3c7be36be44f5657e9a20817e1`, especially
  `docs/specs/16-python-library-api.md` [SB-API-2].

Canonical agent context consulted for this rebase: `AGENTS.md`,
`docs/program-theory.md`, `docs/agent-context/decision-hierarchy.md`,
`docs/agent-context/principles.md`,
`docs/agent-context/engineering-principles.md`,
`docs/agent-context/runbooks/writing-plans.md`,
`docs/agent-context/runbooks/hardening-plans.md`,
`docs/agent-context/runbooks/testing-patterns.md`,
`docs/agent-context/runbooks/review-loops-and-agent-bootstrap.md`,
`docs/agent-context/lessons.md`, the required Golden Rules and current dated
entries in `docs/lessons.md`, and `docs/implementation/03-agent-inventory.md`
for independent-review routing.

Repository baseline: `28376fe9bfb39210b570e4c91dca40abece0027d`.
The prior reviewed draft is identified by Git blob
`fa82fea42cc42f764742a6f16d7e757a1cc9fe34`; this plan was untracked, so no
commit contains that reviewed text. The owning spec blobs at the repository
baseline are:

| Spec | Baseline blob |
|---|---|
| `docs/specs/02-taut-core.md` | `f3e41012815b1ba090ba3a3d929d41ec45a0b8d9` |
| `docs/specs/03-identity-addressing-notifications.md` | `41b4fd3ba3e4228f563f760bd93010f22e42a992` |
| `docs/specs/04-summon.md` | `fca8abb367f38d0ebb199cf02546de9ad822b0b8` |
| `docs/specs/06-search.md` | `a48b5ff589955a3697a899d80eb393535809be9a` |
| `docs/specs/09-system-doctor.md` | `b23ca14fa3c097e6aa599fcb9e73a388de4485e8` |

E2 process containment landed at
`50eeb947f1530d70ec8ba070c385191e8b4f6336`; SimpleBroker 8 reconciliation
landed at the repository baseline. The prior Summon/workflow overlap warning
is therefore retired. The current worktree instead contains unrelated Task 7A
Ruff cleanup in
`docs/plans/2026-08-24-extension-seams-process-containment-coverage-plan.md`,
`docs/specs/01-development-documentation-operating-model.md`,
`extensions/taut_summon/taut_summon/_win32_job.py`, its test, and
`tests/test_ruff_policy.py`. None is an implementation target here. Preserve
those overlays. `docs/plans/README.md` is shared only because it already holds
this draft's index row; edit that row without disturbing its other changes.

All five owning specs and all production, test, and implementation-doc targets
listed below are clean at this rebase. Re-read target paragraphs by stable
reference and anchor text before promotion; never apply replacements by line
number. The Windows proof remains in `tests/test_identity.py` and is collected
by the existing Windows shards. This plan does not edit workflows.

## Current Owners and Edit Points

Production:

- `taut/_constants.py`: `_TAUT_BROKER_DEFAULTS`, `load_config()`,
  `freeze_broker_config()`, and the configured process-family basename sets.
- `taut/identity.py`: `ProcessInfo.classification_basenames` and
  `select_anchor()`.
- `taut/state/_sql.py`: core schema version read and shared decoder owner.
- `taut/_doctor.py`: passive core-version interpretation.
- `taut/search/_sqlite.py::SQLiteSearchProvider.ensure_schema()`.
- `extensions/taut_pg/taut_pg/_search.py::PostgresSearchProvider.ensure_schema()`.
- `taut/search/_discovery.py::load_search_provider()`.
- `extensions/taut_summon/taut_summon/_state.py`: real v2 to v3 migration.

Tests:

- `tests/test_constants.py`
- `tests/test_identity.py`
- `tests/test_state_contract.py`
- `tests/test_system_doctor.py`
- `tests/test_search.py`
- `tests/test_search_discovery.py`
- `tests/test_shared_contract.py`
- `extensions/taut_pg/tests/test_pg_search_provider.py`
- `extensions/taut_pg/tests/test_pg_sidecar.py`
- `extensions/taut_summon/tests/test_state.py`
- new shared fixture:
  `extensions/taut_summon/tests/fixtures/summon-schema-v2.json`

Documentation:

- the five specs listed above;
- implementation docs 04, 05, 09, and 11;
- `docs/lessons.md`;
- this plan and `docs/plans/README.md`.

## Invariants and Constraints

1. **No ambient config fallback.** Every Taut-owned translated key remains
   required. Both initial resolution and handoff re-freezing use
   SimpleBroker's strict ambient-free resolver. `ResolvedConfig` stays nominal
   and immutable. Unknown Taut overrides and arbitrary unknown broker keys
   remain errors; this plan does not enable `preserve_unknown=True`.
2. **Only resolver-owned additions pass.** A copied handoff must contain every
   Taut-translated key before re-resolution, so a missing Taut value cannot be
   silently replaced by a broker default. A new key is retained only when the
   installed strict resolver recognizes it as canonical and supplies or
   accepts it. A removed or renamed Taut-translated input remains a
   compatibility error before target construction. Key-shape acceptance does
   not replace dependency behavior tests.
3. **Diagnostics are not type tags.** Human-readable `InvalidConfigError`
   fields remain display material. Compatibility classification uses required
   membership in a public strict isolated default snapshot; it never branches
   on exact `expected` wording.
4. **No target-shaped preflight before version classification.** The existing
   metadata `CREATE TABLE IF NOT EXISTS` may run first because it creates a
   missing table and is a no-op on an existing one. On an existing row, the
   version read comes before current-shape insert and document/segment DDL.
5. **Fresh remains distinct.** No metadata row initializes current state. An
   older, newer, or unreadable stored version does not silently become fresh.
6. **No speculative migration framework.** Do not add empty core or search
   dispatchers. The first real column or supported migration brings its own
   mechanism and predecessor-produced proof.
7. **Physical order and global prefix closure are not APIs.** Production SQL
   continues to name columns. Tests require owned names and semantics as
   subsets unless an explicit positional or closed-inventory consumer is
   documented.
8. **No runtime catalog validator.** This plan does not add general schema diff
   or repair machinery. Required constraints remain covered by focused schema
   and behavior tests.
9. **Identity evidence remains deterministic.** Classification normalization
   cannot alter stored process evidence or claim hashes for an unchanged
   selected agent.
10. **Foreign provider code never loads.** Discovery may read inert distribution
   metadata, but it must not import or call a foreign same-name entry point.
11. **Duplicate official claims remain fatal.** Do not choose by enumeration
    order.
12. **Historical proof is historical.** The Summon v2 fixture comes from the
    actual v2 producer at the pinned commit. It is not generated by the v3
    installer or edited to satisfy the current migration.
13. **No unrelated cleanup.** Preserve public APIs, schema/projection versions,
    persistence formats, dependency floors, and command behavior.

## Hidden Couplings and Rollout

- `freeze_broker_config()` is used by client handoff and watcher paths. Test
  both direct config load and frozen handoff. A plain handoff mapping does not
  carry provenance, so arbitrary extras cannot be distinguished safely from
  typos; strict resolver recognition, not mapping membership alone, is the
  eligibility test.
- Search schema and projection versions are separate gates. Both providers keep
  their existing transaction owner; PostgreSQL also keeps its advisory lock.
- Skipping a Windows shell may select a different parent or human fallback. A
  live legacy shell anchor may heal only through existing ancestor matching
  when the new capture is still an agent. Otherwise continuity token or
  explicit `rejoin` is the recovery. Do not add basename-only adoption.
- `taut_%` is shared by core and first-party extensions, so a core test cannot
  own the global prefix as a closed set.
- SimpleBroker 8 [SB-API-2] guarantees that strict isolated resolution fills
  canonical defaults without ambient reads and rejects unknown inputs. Taut
  must use that public contract, not inspect SimpleBroker's private field
  registry or duplicate its normalizers.
- SC-1 deliberately stops using configuration inventory as a surrogate
  dependency-version gate. Taut trusts the declared dependency range and the
  dependency's public compatibility contract, then runs real behavior suites
  at lock refresh and release. If a future version proves incompatible, the
  manifest may gain a separately justified range ceiling; exact config-key
  equality is not a sound substitute.
- The current Summon v2 producer at
  `c7266dd97d65d96a66b03c152ac2ad3b53b363c7` stores schema version 2 and owns
  the metadata table, two extension tables, and version-row insert. That
  source, not current test helpers, defines the fixture.

No data-format or version change is planned, and there is no new one-way door.
Complete and verify both search providers before closing their slice; commit
shape is not a correctness contract. Source rollback needs no schema rollback
because current-version DDL is unchanged and refusal paths stay transactional.
The meaningful residual is Windows identity selection: the first capture after
the change may select a different ancestor or human fallback and may create a
new durable member. Reverting code does not merge that member. Existing
continuity-token or explicit `rejoin` flow is the safe recovery; do not add
basename-only adoption or automatic member merging.

## Proposed Spec Delta

The following is exact proposal text for owner ratification.

### [TAUT-3.2]: replace symmetry and exact-output inventory claims

Replace the paragraph beginning “Taut and standalone SimpleBroker have
symmetric configuration namespaces” with:

> Taut and standalone SimpleBroker have isolated configuration namespaces.
> Taut reads only its documented `TAUT_*` inputs and SimpleBroker reads
> `BROKER_*`; neither ambient namespace fills the other. The Taut translation
> inventory is the closed set of broker settings Taut currently exposes, not a
> promise that every future resolver output immediately gains a Taut spelling.
> A newly recognized broker setting uses the strict isolated resolver's
> canonical default until Taut deliberately assigns it a public input and
> product meaning. Taut never obtains isolation by temporarily editing the
> process environment.

Replace the paragraph beginning “`load_config()` compiles one complete” and
ending “public Taut spelling” with:

> `load_config()` compiles the closed Taut-owned input mapping, mechanically
> renames each supported `TAUT_NAME` to its documented `BROKER_NAME`, and
> passes only those inputs through SimpleBroker's public strict
> `resolve_isolated_config()` helper. The helper returns a nominal immutable
> `ResolvedConfig` without reading ambient `BROKER_*`. Broker lower layers
> retain that no-ambient marker; converting it to an ordinary dictionary is
> not a broker handoff. A copied embedder mapping is re-frozen before Taut
> passes it to broker lower layers. SimpleBroker owns canonical defaults,
> normalization, validation, safe rejected-value display, and the resulting
> typed mapping. Taut owns input selection, key translation, Taut-specific
> defaults, required-input survival, and translation of typed invalid-key
> diagnostics back to public Taut spellings.

Replace the paragraph beginning “Every other named default exists” with:

> Every other named Taut default mirrors a broker setting that Taut currently
> exposes. Supplying all documented Taut translations explicitly prevents
> ambient `BROKER_*` values from affecting them. Most have no independent Taut
> meaning; naming them is an isolation and public-configuration choice, not a
> claim that the table is the resolver's permanent output inventory.

Replace only the first two sentences after the configuration tables, beginning
“These two tables are the closed 32-field,” with:

> These two tables are the closed current Taut-to-broker input translation
> inventory. Their values are raw strings so SimpleBroker's public field
> schema remains the sole normalizer; resolved values may differ, such as
> vacuum threshold `10` becoming ratio `0.1`.

Replace only the next paragraph's opening sentence, beginning “The mapping is
exhaustive and bijective,” with:

> Each documented Taut broker setting maps to exactly one canonical broker key;
> the Taut input inventory need not equal the strict resolver's whole returned
> key set.

Retain that paragraph's existing mechanical-prefix, precedence,
multi-workspace, path-splitting, and unknown-override sentences verbatim.

Replace the paragraph beginning “The isolated resolver rejects unknown keys”
with:

> The strict isolated resolver rejects broker input keys it does not recognize
> and returns a nominal ambient-free snapshot containing every canonical key
> it owns. Taut requires every translated Taut input key to be present after
> resolution. A copied client or watcher handoff must also contain every
> translated Taut key before strict re-resolution, so a missing Taut-owned
> value is not replaced by a broker default. Taut preserves any additional
> canonical keys returned by that resolver through the handoff. A missing,
> removed, or renamed Taut input fails before target or handle construction.
> Taut detects removed keys by requiring its input keys to be a subset of a
> public strict isolated default snapshot; it does not parse human-readable
> `InvalidConfigError` wording as a type tag. Taut does not enable permissive
> unknown-key preservation, expose additional outputs as Taut inputs, inspect
> SimpleBroker's private field registry, or impose whole-output key equality at
> runtime or in CI. Dependency upgrades still require behavior verification;
> key-shape compatibility alone is not an endorsement of changed broker
> semantics.

### [TAUT-3.3]: replace the additive-column sentence and clarify comparison

Replace only the sentence beginning “Schema evolution is additive” with:

> New tables and indexes may evolve additively within the current schema
> generation through idempotent DDL. Adding a column to an installed table is
> not accomplished by editing `CREATE TABLE IF NOT EXISTS`: the change must
> supply an explicit idempotent reconciliation step or a versioned migration
> and a firing upgrade proof whose source state was produced by the actual
> supported predecessor. That proof may run the predecessor producer or use a
> provenance-pinned fixture; no generic fixture or migration framework is
> required. Backend proof follows the column's actual compatibility boundary.

Append after the existing schema-evolution and migration paragraphs:

> Migration and schema-conformance checks require named columns and logical
> constraint semantics as owned subsets. Physical column ordinal,
> engine-generated constraint names, unrelated tables sharing a prefix, table
> creation order, and unowned additional columns are not invariants unless an
> explicit consumer says otherwise.

Retain the existing ordered-rung and unsupported schema-1 rules.

### [IAN-3.2]: insert after optional evidence handling

> Process selection classifies executable basenames independently from the raw
> evidence used for identity. For classification only, one terminal `.exe`
> suffix is case-insensitive and does not distinguish configured shell,
> wrapper, or infrastructure families. `cmd`, `powershell`, and `pwsh` are
> shell families. Classification does not rewrite executable path, argv,
> selected-anchor evidence, fingerprint, automatic-name evidence, or
> claim-hash input. A shell is not an `agent_process` anchor merely because its
> platform spelling carries an executable suffix.

Add this [IAN-10] verification bullet:

> - process-family classification treats one case-insensitive terminal `.exe`
>   suffix identically to the configured unsuffixed shell, wrapper, and
>   infrastructure names; synthetic chains cover `cmd`, `powershell`, `pwsh`,
>   an existing shell, one wrapper, one infrastructure process, and a
>   selectable control agent, while a real Windows subprocess probe proves it
>   observed PowerShell in the ancestry and did not select that shell as the
>   agent anchor; raw executable path, argv, fingerprint input, and claim input
>   remain unchanged

### [SUM-8] and [SUM-12]: historical migration fixture

Append to [SUM-8]:

> Migration compatibility is defined by the predecessor's named semantic
> schema, not physical column order. The v2 to v3 proof starts from a checked-in
> fixture copied from the actual v2 release. Running the v3 installer and
> rewriting its version marker is not a v2 fixture.

Replace the current [SUM-12] schema-test bullet with:

> Schema tests install the historical version-2 fixture directly and prove
> successful normalization plus fail-before-mutation handling for colliding
> case variants on real SQLite and PostgreSQL sidecars.

Fixture provenance belongs beside the test fixture and in implementation docs,
not in the product spec. Use tag `taut_summon/v0.5.3`, commit
`c7266dd97d65d96a66b03c152ac2ad3b53b363c7`.

### [SRCH-6.2]: append to schema initialization

> Each provider may create the metadata table if absent, because that statement
> is a no-op for an existing table. It then reads the singleton's stored schema
> and projection versions before any insert, update, or provider-object DDL
> that assumes the current shape. No singleton row is the fresh-initialization
> case. An existing row whose stable version fields cannot be read is not
> fresh; it fails without being rewritten. Older or newer versions follow
> their declared refusal or transition path. Provider schema checks require
> owned names, types, constraints, and indexes as semantic subsets. Physical
> column order, unrelated additional objects, and unowned additional columns
> are not provider invariants.

### [SRCH-7]: replace only the first two discovery-ambiguity sentences

Replace the sentences beginning `Zero claims` through `Discovery rejects
ambiguity before choosing a claim` with:

> Discovery normalizes distribution ownership and filters eligible `taut-pg`
> claims before counting ambiguity. Exactly one eligible official `postgres`
> claim may load even when foreign distributions publish the same key; foreign
> claims are never loaded. Zero or duplicate eligible official claims and the
> existing manifest, load, or provider validation failures fail only search
> with the actionable `taut-pg` diagnostic. Core never chooses among multiple
> official claims by enumeration order.

Retain verbatim the following two sentences that prohibit core from importing
`taut_pg`, depending on `simplebroker-pg`, containing PostgreSQL SQL, or
treating the seam as a public plugin/root export.

### [DOCT-4.1]: append to schema-version handling

> Doctor and ordinary core startup use the same side-effect-free stored-version
> decoder and therefore accept or reject the same representations. Their error
> projections remain different: ordinary startup raises its existing schema
> error, while doctor reports malformed data as `version: null` in a failed
> check. Taut continues to write canonical decimal text, but this change does
> not invent a stricter stored-text grammar. Sharing the decoder does not permit
> doctor to call `ensure_schema`, mutate metadata, or repair it.

### Related Plans

Add a specific backlink to this plan in specs 02, 03, 04, 06, and 09 during
promotion.

## Durable Lesson

Add one concise entry to `docs/lessons.md` at closeout:

> - 2026-08-28: Compatibility gates must name the semantics they protect.
>   Read source versions before target-shape work; classify ownership before
>   ambiguity; and do not make physical column order, ineligible foreign
>   inventory, or strict-resolver-owned canonical output additions into runtime
>   failures. Missing required inputs, unknown config inputs, newer unsupported
>   state, unknown durable data, and multiple eligible owners remain
>   fail-closed. Historical migration proof starts from the historical
>   producer, not the target installer with a rewritten marker.

This lesson is the negative-knowledge record for this change. Do not add a
second program-theory record unless the owner later decides the rule needs a
product-level reconsideration policy.

## Required Reading and Comprehension

Before spec promotion or implementation, record these answers in the
Execution Log. A wrong or source-unsupported answer blocks the relevant slice.

1. **What makes an added broker key eligible?** Expected: the installed strict
   `resolve_isolated_config()` recognizes it as canonical and returns it from
   an ambient-free resolution. Taut does not accept arbitrary extras, enable
   `preserve_unknown=True`, inspect a private registry, or infer compatibility
   from key shape alone. Removed-key classification uses required containment
   in a public strict default snapshot, not diagnostic prose.
2. **What may run before search version classification?** Expected: only the
   transaction/advisory-lock setup and metadata-table creation needed to reach
   the stable version row. A current-shape insert, update, or provider-object
   DDL waits until no-row fresh classification or current-version acceptance.
3. **Which identity value is normalized?** Expected: a derived basename used
   only to classify shell, wrapper, and infrastructure families. Raw process
   evidence, selected anchor, fingerprint input, and claim input are not
   rewritten.
4. **What defines Summon v2?** Expected: the source DDL and version metadata in
   `_state.py` at commit
   `c7266dd97d65d96a66b03c152ac2ad3b53b363c7`, not the current installer or a
   test helper that downgrades current state.

## Dependency-Ordered Slices

### Slice 0: review and spec promotion

1. Complete a fresh independent review of this rebased plan, its exact spec
   delta, and the public SimpleBroker 8 [SB-API-2] contract. Approval of the
   prior blob does not attach to this revision.
2. Owner-ratify the reviewed proposal paragraphs above.
3. Re-read the current target paragraphs and protected worktree overlays.
4. Promote the ratified text and Related Plans backlinks using strategy A.
5. Record the promotion baseline as a commit or as repository baseline plus
   exact spec diff, then run plan-index and documentation-reference gates.

No production edit starts before promotion.

### Slice 1: config compatibility, doctor parity, and provider ownership

Red first:

- replace the current three-way addition/removal/rename schema-drift test with
  semantic cases: a future-resolver wrapper that delegates all current
  normalization to the real strict resolver, recognizes one additional
  canonical key, and returns a nominal `ResolvedConfig` must succeed through
  `load_config()`, a plain copied handoff, and `freeze_broker_config()`;
- retain removal/rename failure and ambient `BROKER_*` isolation tests;
- delete one required Taut key from a copied resolved handoff and prove
  `freeze_broker_config()` fails before strict resolution can refill the broker
  default;
- add one arbitrary unknown broker key to a complete copied handoff and prove
  the real strict resolver rejects it rather than preserving it;
- remove `_UNKNOWN_BROKER_KEY_EXPECTED` and the production branch that compares
  `InvalidConfigError.expected`; existing real-resolver invalid-value tests
  continue to prove that upstream expected-form text is preserved for display,
  not used as a type tag;
- retain the current Taut translation registry/table equality proof, but
  remove numeric field-count and whole-resolver-output equality assertions;
- prove ordinary startup and doctor both interpret `02` as version 2 and both
  reject the same non-integer token through one shared decoder, while doctor
  remains passive and keeps its nullable report shape;
- prove one official plus one foreign search claim loads only the official
  provider, foreign-only fails, and duplicate official claims fail without
  loading either.

Then:

- replace equality with required-key containment before and after handoff
  re-resolution, after initial resolution, and against one strict isolated
  default snapshot used only as the public supported-key capability check.
  Retain strict resolver calls at both boundaries; do not use permissive
  unknown-key mode, diagnostic-string classification, or SimpleBroker private
  registries;
- move the core version conversion to one side-effect-free state helper reused
  by startup, `get_schema_version()`, and doctor, preserving current startup
  acceptance, canonical writes, and each caller's existing error projection;
  and
- filter normalized official ownership before search-claim cardinality.

Do not add a new schema token grammar, config capability framework, warning
channel, or public plugin API.

### Slice 2: version-first search initialization and semantic PG assertions

For each provider, add one real-database adversarial source-shape test. This is
not a claimed historical fixture: search has no released predecessor schema.
Create only the existing metadata table and singleton with the stable schema
and projection version fields, and omit at least one column used by the current
insert. Parameterize the probe over exactly two independent gate cases:
unsupported schema with current projection, then current schema with
unsupported projection. In both cases `ensure_schema()` must report the stored
version refusal rather than an insert/DDL shape error and must leave the table
and row unchanged. Existing newer-version cases keep their coverage; use the
smallest unsupported sentinel needed to isolate each gate. Add one bounded
companion case where either stable version field itself is absent; the shared
two-column read must fail without inserting or rewriting metadata. These are
ordering probes, not an exhaustive malformed-schema matrix.

Keep the existing fresh, current, newer-schema, and newer-projection tests.
Inside each provider's existing transaction/lock:

1. run metadata `CREATE TABLE IF NOT EXISTS`;
2. read the stable version row;
3. if no row exists, insert current metadata and continue fresh setup;
4. otherwise classify schema and projection versions; and
5. only after current-version acceptance run current provider-object DDL.

Do not add a general migration dispatcher, catalog validator, corruption
matrix, or schema repair.

Update the PostgreSQL conformance tests:

- required core/search tables are subsets of discovered names;
- required `taut_search_segments` name-to-type entries are a subset of
  discovered columns;
- existing logical constraint, owned-index, concurrent-init, and usable-search
  assertions remain.

No dynamic scan framework or synthetic reordered schema is added.

### Slice 3: Windows classification

Add table-driven synthetic chains covering the semantic classes, not an
exhaustive Windows executable inventory: new Windows shells (`cmd.exe`,
`powershell.exe`, mixed-case `PWSH.EXE`), one existing shell (`bash.exe`), one
wrapper (`uv.exe`), one infrastructure process (`tmux.exe`), and one control
agent (`codex.exe`). The non-control entries follow their existing family
behavior after classification normalization; the control agent remains
selectable. Raw-evidence and claim-contract tests must prove the original
exe/argv, fingerprint inputs, and claim inputs are unchanged;
strengthen or add the missing exact-field assertions rather than inferring
that proof from hash equality.

Implement one classification-only basename helper. Do not change
`ProcessInfo.basename` or stored evidence.

Add one Windows-only subprocess proof in `tests/test_identity.py`. The test
launches a child Python identity probe from PowerShell so PowerShell is in the
child's real ancestry. The probe must first prove that it observed the
PowerShell process, then prove it did not report a shell executable as an
agent anchor; otherwise it is a false green. Assert no fixed ancestor above the
shell or fixed generated member name. Existing root Windows shards collect the
test; do not edit the workflow.

### Slice 4: historical Summon fixture

Copy only the portable v2 metadata-table DDL, the two extension-table DDL
statements, and the version-row insert
from `extensions/taut_summon/taut_summon/_state.py` at
`c7266dd97d65d96a66b03c152ac2ad3b53b363c7`
(`taut_summon/v0.5.3`) into one standard JSON fixture with `source_path`,
`source_commit`, `schema_version`, and a fixed `steps` array. Each step is
`{"sql": string, "params": array}` so the historical parameterized version
insert remains the source statement plus
`["summon_schema_version", "2"]`, not a hand-substituted SQL variant. Root
shared-contract and Summon extension migration tests parse JSON and run each
step through the real sidecar. Do not execute a dialect-dependent
multi-statement string, split SQL text, or add a generic fixture loader. Remove
target-installer downgrade helpers.

Run the existing successful normalization and collision fail-before-mutation
cases on SQLite and PostgreSQL. If the historical shape differs from the
migration's assumptions, stop and revise the migration plan. Do not modify the
fixture to fit current code.

Update only the migration rationale in implementation doc 05. E2's process
containment sections are baseline content and are not reopened by this plan.

### Slice 5: documentation, verification, and completed-work review

Update implementation docs 04, 05, 09, and 11 with the rationale and exact
owners. Add the durable lesson. Update this plan's logs and plan-index status.

Run focused tests, then the canonical Development block in `README.md`.
Record the hosted Windows result at the reviewed commit. Run an independent
completed-work review with this question first: did the change introduce any
new exactness, fixture, parser, or process that is not needed for correctness?

## Testing and Verification

### Anti-mocking floor

- Use the real SimpleBroker isolated resolver and real nominal
  `ResolvedConfig`. The only resolver substitution may be a small
  future-schema wrapper that delegates current fields to the real strict
  resolver and models one newly canonical key at both initial and re-freeze
  boundaries. It must not replace normalization, validation, or ambient
  isolation.
- Use real SQLite and Docker PostgreSQL sidecars for search and Summon schema
  proof.
- Use synthetic process chains for classification plus one real hosted Windows
  PowerShell test.
- Entry-point fixtures may provide inert metadata, but foreign `load()` methods
  must be firing failures in the mixed-owner success case.
- Do not mock `ensure_schema`, doctor projections, or migration helpers in
  contract tests.

### Focused commands

```bash
uv run --extra dev pytest tests/test_constants.py tests/test_state_contract.py tests/test_system_doctor.py tests/test_search_discovery.py
uv run --extra dev pytest tests/test_identity.py tests/test_search.py
uv run --extra dev pytest tests/test_shared_contract.py
uv run --extra dev pytest extensions/taut_summon/tests/test_state.py
uv run ./bin/pytest-pg --fast
uv run bin/check-plan-status-index
uv run bin/check-doc-paths
```

Per slice, record changed files, the red failure, the green result, the real
boundary exercised, and residual risk. Final completion also requires the full
Development block, exact-commit hosted Windows evidence, independent diff
review, and owner-authorized landing verified by `git log`. If the owner asks
for uncommitted review, report the uncommitted state instead of calling it
ready to land.

Post-deploy or post-install success is positive: Taut config still ignores
ambient `BROKER_*`; both search backends open current state and refuse the
adversarial version before mutation; doctor and startup agree on stored-version
interpretation; a Windows PowerShell-launched probe does not create a shell
agent anchor; Summon migrates an authentic v2 source on both sidecars; and the official
Postgres provider loads even with an inert foreign same-name claim. Absence of
exceptions alone is not sufficient evidence.

## Outside Review and Fresh-Eyes Gate

The first independent reviews improved correctness but also caused the draft to
grow into new schema grammars, corruption matrices, fixture frameworks, release
metadata rewriting, and duplicate governance. A separate outside simplicity
review rejected that direction. This revision incorporates its lean target:

- keep the five direct runtime fixes and two test corrections;
- keep the future core-column rule as a spec obligation, not a framework;
- keep one real Summon historical fixture;
- use one focused adversarial search source-shape test per backend without
  claiming historical provenance; and
- keep one short lesson instead of duplicating program theory.

Before promotion, a fresh reviewer must answer:

1. Does each planned check protect a named correctness invariant?
2. Can any task be removed without reopening SC-1 through SC-8?
3. Does any new test freeze physical layout, wording, or inventory that the
   specs do not own?
4. Does the implementation add machinery for a migration or corruption state
   that does not exist?
5. Does SC-1 preserve strict unknown-input rejection and ambient isolation
   while avoiding any whole-output inventory check?

Any “yes” to questions 2 through 4, or “no” to questions 1 or 5, requires
simplification or correction before promotion.

## Out of Scope and Deferred Findings

- a generic schema diff, validation, repair, or migration framework;
- a core historical fixture before a real core column/migration change exists;
- exhaustive malformed search-metadata matrices;
- synthetic reordered-schema variants;
- a dynamic scan of arbitrary future search tables;
- a stricter schema-version text grammar;
- permissive SimpleBroker unknown-key preservation, private config-field
  reflection, diagnostic-string classification, or a frozen resolver-output
  inventory fixture;
- release-tool TOML rewriting, PEP 508 normalization, and optional-dependency
  ordering cleanup (valid lower-severity findings, deferred to a small release
  tooling change with its own mutation boundary);
- a new program-theory record duplicating the lesson;
- public plugin APIs, dependency caps, schema-version bumps, or persistence
  format changes; and
- committing, releasing, or publishing without separate owner authorization.

## Stop Conditions

Stop and revise if:

- an extra resolved key can consult ambient state or change a Taut invariant
  under a supposedly compatible SimpleBroker release;
- accepting additions requires permissive unknown-key mode, private
  SimpleBroker registry access, diagnostic-string classification, or
  duplicated value normalization;
- an existing search metadata row cannot expose stable version fields before
  current-shape work;
- Windows classification requires changing raw claim evidence;
- provider ownership cannot be determined from inert metadata;
- the historical Summon fixture differs from the migration's assumed source;
  or
- a current worktree overlay appears in an implementation target and cannot be
  preserved without changing this plan's boundary.

## Deviation Log

| Date | Spec reference | Planned behavior | Actual behavior and rationale | Spec proposal or disposition |
|---|---|---|---|---|

No deviations are recorded.

## Revision Log

- 2026-08-28: rebased prior reviewed draft blob
  `fa82fea42cc42f764742a6f16d7e757a1cc9fe34` from repository baseline
  `8f908f2b32c22d8aeb23cf75791011224db43722` to
  `28376fe9bfb39210b570e4c91dca40abece0027d`. The revision consumes landed E2
  and SimpleBroker 8 work, replaces the stale overlap gate, and records clean
  target-spec blobs plus current unrelated worktree boundaries.
- 2026-08-28: materially revised SC-1 against released SimpleBroker 8
  [SB-API-2]. Removed runtime and CI whole-output inventory equality; retained
  strict resolver recognition, closed Taut inputs, required-input survival,
  nominal handoff, ambient isolation, and dependency behavior tests. Also
  replaced claimed historical search fixtures with adversarial source-shape
  probes, made PostgreSQL maps explicit subsets, made the Windows proof
  ancestry-based, and allowed predecessor-produced proof without mandating a
  fixture framework. These changes require fresh review before ratification.
- 2026-08-28: reintroduced four bounded source-comprehension questions because
  the rebase adds new strict-resolver, version-first, identity-evidence, and
  historical-provenance boundaries that block implementation when
  misunderstood. The prior review removed a redundant written-comprehension
  summary from the old draft; this gate now asks only source-verifiable answers
  required by the repository's hardened-plan runbook and records them once in
  the Execution Log.
- 2026-08-28: implementation exploration corrected two non-semantic omissions:
  Slice 3 also owns the configured basename sets in `taut/_constants.py`, and
  exact raw exe/argv evidence needs a strengthened firing assertion rather
  than relying on existing hash-shape tests. Added `test_state_contract.py` to
  the Slice 1 focused command because the shared decoder is state-owned.

## Review Log

- 2026-08-25: three correctness reviews found missing boundaries in the first
  draft. Their valid safety points were incorporated.
- 2026-08-25: an outside simplicity review found that the resulting draft had
  become over-broad and ceremonial. It directed removal of SC-9/SC-10 release
  work, the strict version grammar, speculative core fixture, corruption
  matrices, derived reordered fixtures, dynamic introspection, duplicate
  negative knowledge, and redundant gates. This revision follows that cut
  list.
- 2026-08-25: the outside reviewer re-read the lean revision, requested one
  factual count correction and removal of the redundant written-comprehension
  gate, and then found the plan proportionate and ready for owner ratification.
- 2026-08-28: prior approval is retained as history but does not approve the
  materially revised blob. Fresh scoped review is pending.
- 2026-08-28: fresh scoped review of plan blob
  `e055f7e977d4fc3f5ce38c4ef1ddbe8e0966d50e` found no blocker after eight
  findings were resolved. The revision added firing missing-owned-key and
  arbitrary-unknown-key cases, exact [IAN-10] text, independent schema and
  projection ordering probes, authentic diagnostic proof, a bounded [SRCH-7]
  edit that retains core boundaries, parameter-preserving Summon fixture
  steps, and explicit gate and source provenance. No scope expansion was
  recommended. Owner ratification remains the promotion gate.
- 2026-08-28: independent Slice 0/1 implementation review found no blocker
  after removing a CPython-specific `int()` error-message assertion and adding
  the required per-slice evidence log. It verified 173 focused tests, Ruff,
  full `mypy taut tests`, documentation gates, and the public SimpleBroker 8
  contract.
- 2026-08-28: independent Slice 2 review found no blocker or actionable
  finding. It verified real-database ordering probes, fresh/no-row behavior,
  SQLite `BEGIN IMMEDIATE` and PostgreSQL advisory-lock race ownership,
  semantic subset assertions, owned GIN catalog facts, and rollback-resistant
  statement/state evidence.
- 2026-08-28: independent Slice 3 review found no remaining finding after it
  requested a `bash.exe.exe` control that proves exactly one terminal suffix is
  removed. It verified family coverage, unchanged raw/fingerprint/claim/name
  semantics, and the hosted proof's observation-before-exclusion structure.
- 2026-08-28: independent Slice 4 review found no actionable finding. It
  compared every fixture SQL string and parameter with the released v2
  producer, ran the SQLite and PostgreSQL migration paths through real
  sidecars, and confirmed there is no target-shaped downgrade, SQL splitter,
  multi-statement executor, or generic fixture loader. The reviewer accepted
  exact four-step closure as historical provenance rather than a current-schema
  inventory.
- 2026-08-28: independent completed-work review first found two precision
  issues, both resolved before its final pass. Implementation doc 11 now names
  the doctor as the caller of the state-owned decoder. The SQLite ordering
  probe now recognizes exact identifier tokens and semantic operation order
  without pinning one whole SQL spelling or exactly one read. The final review
  found no blocker or remaining finding and judged the fixed historical
  fixture and hosted Windows subprocess to be the minimum correctness proofs,
  not new runtime frameworks.

## Execution Log

- 2026-08-25: plan authored and revised only. No product, spec, implementation
  doc, lesson, workflow, or test behavior changed. Unrelated active Summon work
  remains untouched.
- 2026-08-28: plan and status-index row rebased and revised only. No product,
  spec, implementation doc, lesson, workflow, or test behavior changed. E2 and
  SimpleBroker 8 are now baseline facts; unrelated Task 7A overlays remain
  untouched.
- 2026-08-28: the owner's instruction to implement per plan ratified the exact
  proposed spec delta. Promoted it by stable anchor and added backlinks in all
  five owning specs. Against repository baseline `28376fe9b`, the promoted
  working-tree blobs are `75770edc` (spec 02), `8bce76e5` (spec 03),
  `ce0e0119` (spec 04), `c0dafd41` (spec 06), and `89a9d25f` (spec 09).
  Documentation path, reference, status-index, and whitespace gates passed.
- 2026-08-28: required-reading answers recorded before production edits:
  (1) an added broker key is eligible only when the installed strict
  ambient-free resolver recognizes and returns it; required Taut inputs remain
  closed and diagnostic prose is not classification; (2) before search version
  classification only transaction/lock setup and metadata-table creation may
  run; (3) only a derived basename is normalized for process-family
  classification, never raw evidence or claim inputs; and (4) Summon v2 is the
  DDL and metadata at `c7266dd9`, not a downgraded current installer.
- 2026-08-28: Slice 1 red evidence fired at each changed interface. A future
  canonical resolver key failed the old whole-output equality; missing strict
  capability checks left removal/rename probes green and the diagnostic-string
  branch misclassified an arbitrary unknown handoff; doctor rejected stored
  `02` that startup accepted; and one official plus one foreign provider failed
  as ambiguous before ownership filtering. Green: 173 focused config, state,
  doctor, and discovery tests passed, followed by focused Ruff format/lint and
  full `mypy taut tests`. The proof crosses the real SimpleBroker 8 strict
  resolver and nominal `ResolvedConfig`, ordinary Taut startup plus passive
  doctor, and inert entry-point metadata with a foreign-load tripwire. Residual:
  the added-key dependency shape is necessarily simulated by a thin wrapper
  over the released resolver; all current-key normalization, validation, and
  ambient isolation remain real.
- 2026-08-28: Slice 2 red evidence on both providers failed at the old
  current-shape metadata insert with missing `current_generation`, before the
  stable version read. Green: 31 SQLite search tests passed; the PostgreSQL
  fast gate passed 314 shared tests plus 40 extension tests; focused Ruff,
  format, mypy, and whitespace checks passed. The two independent schema and
  projection cases plus the missing-stable-field companion use real SQLite and
  Docker PostgreSQL, recording delegates, and pre/post source snapshots, so a
  transaction rollback cannot conceal insert/update/provider-DDL work before
  refusal. Residual: these are deliberately adversarial source shapes, not
  historical search schemas; no migration or concurrency mechanism changed.
- 2026-08-28: Slice 3 red evidence fired for `cmd.exe`, `powershell.exe`,
  mixed-case `PWSH.EXE`, `bash.exe`, `uv.exe`, and `tmux.exe`; unsuffixed-family
  classification selected each as an agent before the change. Green: the
  eight-case semantic table, exact raw exe/argv fingerprint and claim proof,
  and the full identity suite passed (52 passed, one hosted-Windows skip), with
  Ruff, format, and mypy clean. Classification removes one terminal `.exe`
  only in the derived family name; `bash.exe.exe` and `codex.exe` remain
  selectable. Residual: the PowerShell child probe is implemented and cannot
  false-green without observing PowerShell, but its exact-commit hosted Windows
  result remains required before closeout.
- 2026-08-28: Slice 4 red evidence was the fixed fixture path missing before
  fixture creation. The fixture now reproduces exactly the metadata DDL, v2
  claim and session DDL, and parameterized version insert from released source
  `c7266dd9`. Green: 43 Summon state tests and both shared migration tests
  passed on SQLite; both shared migration tests passed on PostgreSQL 18; the
  wider PostgreSQL fast gate remained 314 shared plus 40 extension tests.
  Collision refusal snapshots the version and all five claim fields before and
  after failure. Residual: the fixture is intentionally a fixed four-step
  historical artifact, not a reusable schema-fixture framework.
- 2026-08-28: Slice 5 aligned implementation docs 04, 05, 09, and 11 with the
  strict-resolver subset, shared decoder, derived Windows classifier,
  ownership-first provider discovery, version-first search initialization,
  and authentic Summon fixture owners. The single planned durable lesson was
  added. Documentation path, reference, status-index, and whitespace gates
  passed. Canonical full verification and completed-work review remain open.
- 2026-08-28: completed-work review closed after correcting one documentation
  owner sentence and one overly exact SQLite SQL matcher. Its final verdict was
  no blocker and no remaining finding; it found no fixture, parser, process, or
  exactness beyond the named correctness proofs. The post-correction core suite
  passed 2,261 tests with two platform skips; CLI claims, PostgreSQL (314 shared
  plus 40 extension), MCP (289 passed, seven PG-environment skips), TUI (425),
  Ruff, format, all four mypy lanes, five package builds, and all documentation
  gates passed. The canonical Summon suite had one unrelated process-lifecycle
  failure after 687 passes and four skips:
  `test_pty_observes_leader_exit_while_descendant_continuously_writes` observed
  a published descendant PID that had exited before `psutil` could establish
  its start time. An isolated rerun failed at the same setup boundary. None of
  this plan's files touch that PTY/process-domain path, so this plan does not
  absorb the fix. Residual closeout gates remain: resolve or separately
  disposition that baseline failure, record exact-commit hosted Windows proof,
  and obtain owner-authorized landing verified by `git log`.
