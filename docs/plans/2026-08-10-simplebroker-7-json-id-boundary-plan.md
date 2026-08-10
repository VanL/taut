# SimpleBroker 7 JSON Message-ID Boundary Plan

Status: completed. Implementation, verification, and independent review are
recorded in the Execution Log and Review Log.

Class: 5. This changes Taut's public JSON and persistence-component contracts,
raises a load-bearing dependency floor across multiple distributions, and
therefore requires normative spec revision, a hardened rollout/rollback plan,
red-green proof, and independent review.

Plan type: implementation with spec revision.

## Goal

Raise Taut's supported floor to `simplebroker>=7.0.0` and
`simplebroker-pg>=3.5.2`, then make every Taut-owned external JSON
representation of a SimpleBroker-domain timestamp or message id an exact
19-digit ASCII decimal string. Python values, sidecar columns, broker metadata,
stored broker-message bodies, search work bodies, and internal IPC remain
integers. Reuse the public package-root `simplebroker.format_message_id` helper
at each owned output field.

## Source Documents

- `docs/program-theory.md` [THEORY-1]–[THEORY-4]: Taut is inspectable
  SimpleBroker plumbing and `--json` is a first-class agent surface.
- `docs/specs/02-taut-core.md` [TAUT-3.4], [TAUT-3.5], [TAUT-8.2],
  [TAUT-8.3], [TAUT-12.4]: dependency ownership, one timestamp domain, JSON
  shapes, integer Python API, and release metadata.
- `docs/specs/03-identity-addressing-notifications.md` [IAN-7.2], [IAN-8.2]:
  stored notification bodies and the paired SimpleBroker floor.
- `docs/specs/04-summon.md` [SUM-4], [SUM-8]: Summon runtime floor and durable
  persistence component.
- `docs/specs/05-taut-mcp.md` [MCP-6]: MCP structured output and schemas.
- `docs/specs/06-search.md` [SRCH-5.3], [SRCH-8.2]: public search JSON and
  internal durable search work bodies.
- `docs/specs/08-persistence-io.md` [PIO-4.3], [PIO-4.4], [PIO-5.3],
  [PIO-7.1], [PIO-11]: composite JSON representation and load compatibility.
- `docs/implementation/04-taut-architecture.md`,
  `docs/implementation/05-taut-summon-architecture.md`, and
  `docs/implementation/10-persistence-io.md`: current dependency, rendering,
  extension, and dump/load ownership.
- SimpleBroker source tag `v7.0.0` at
  `b58ef6619927812adfb6d03d2d1838ab421449f1`: `CHANGELOG.md`,
  `docs/guides/python.md`, `docs/implementation/11-json-message-id-boundary.md`,
  `docs/specs/13-message-identity.md`, `docs/specs/16-python-library-api.md`,
  `simplebroker/_message_id.py`, and
  `extensions/simplebroker_pg/pyproject.toml`.
- Repository process consulted before authoring: `AGENTS.md`,
  `docs/agent-context/README.md`, `docs/program-theory.md`,
  `docs/agent-context/decision-hierarchy.md`,
  `docs/agent-context/principles.md`,
  `docs/agent-context/engineering-principles.md`, the planning, hardening,
  testing, review, traceability, and adversarial-probe runbooks,
  `docs/lessons.md` required startup tier, the repository TDD skill, and
  `skills/call-agent/SKILL.md`.

## Spec Baseline

- `6d19465acf805c3562daf54d45318ea6dddafd0c` for every Taut spec named above.
- Upstream contract baseline:
  `b58ef6619927812adfb6d03d2d1838ab421449f1` (`v7.0.0`).
- Promotion strategy: B (atomic). Apply the reviewed requirement text,
  backlinks, implementation, and reciprocal code/test evidence in one
  worktree change so the repository never presents linked external-string
  requirements with integer-producing implementation.
- Promotion baseline identifier:
  `6d19465acf805c3562daf54d45318ea6dddafd0c + reviewed worktree delta
  2026-08-10`. The spec delta and implementation were reviewed as one
  uncommitted worktree change because the user requested review before any
  commit.

## Context and Key Files

- `taut/commands/_rendering.py` constructs every core CLI success JSON record.
  It currently copies integer domain fields directly.
- `extensions/taut_mcp/taut_mcp/_commands.py` constructs command-result records;
  `_process_reactor.py` separately constructs notification-resource records;
  `_tools.py` owns the closed output schemas. All three must move together.
  `_tools.py` and `_commands.py` also own the `log.since` JSON input boundary;
  it must preserve the existing ISO-8601/Unix/native-id string grammar, reject
  bare JSON integers above `2**53 - 1`, and rely on the existing core resolver
  to normalize accepted values to an internal integer.
- `taut/persistence/_operations.py` writes component versions and payloads;
  `_format.py` validates the nested SimpleBroker dump and Taut core records.
  The validator currently rejects SimpleBroker 7 string `id`/`last_ts` fields.
- `taut/state/_sql.py::persistence_records()` and
  `taut_summon._state.persistence_records()` return integer logical values.
  They remain internal. Formatting belongs in the persistence output adapters,
  not these storage owners.
- The core dump adapter must project fields explicitly by record type. The
  owned channel-topic value at `thread.meta.topic.updated_ts` is also external
  in a dump and therefore needs an explicit nested projection and reciprocal
  normalization. Other metadata and broker-body JSON remain opaque.
- `extensions/taut_summon/taut_summon/persistence_manifest.py` owns the Summon
  component write/load versions; `persistence.py` owns external record
  validation and load normalization.
- `pyproject.toml`, `extensions/taut_pg/pyproject.toml`, the root/Summon/MCP
  lockfiles, README requirement copies, specs, and implementation notes carry
  the version floor. `tests/test_dependency_floor_claims.py` gates maintained
  literal restatements against manifests.
- `tests/test_cli.py`, `tests/test_search_cli.py`, MCP tool/resource/schema
  tests, and persistence SQLite/PostgreSQL tests own the closest observable
  contracts.

Comprehension checks before implementation:

1. Where does string conversion belong? Expected answer: at explicit external
   JSON field construction only; never in domain objects, DB rows, broker
   bodies, internal worker/control JSON, or a generic encoder.
2. What must load do with an external string timestamp? Expected answer:
   validate the component-version representation, normalize it to an integer,
   and pass only integers to sidecar/backend writers.
3. Which Taut JSON values are in scope? Expected answer: fields backed by
   Taut's one SimpleBroker timestamp domain (`ts`, `message_ts`, `last_ts`,
   `last_active_ts`, `topic_updated_ts`, and persistence-only `*_ts` fields),
   not counts, versions, PIDs, Unix nanoseconds, or opaque JSON payloads.
4. How is an external JSON timestamp input handled? Expected answer: exact
   message-id inputs use canonical strings; the flexible MCP `log.since`
   boundary retains its ISO-8601/Unix/native-id string grammar and safe JSON
   integers but rejects integer tokens above `2**53 - 1`; its existing core
   resolver normalizes the accepted value to `int`. Dump readers additionally
   accept any exact JSON integer token because Python parses the original token
   without loss.

Execution log answer: all four expected answers above were confirmed from the
cited code and upstream v7 implementation before the first edit.

## Invariants and Constraints

- Public Python dataclasses and queue/sidecar APIs remain integer-valued.
- Sidecar SQL, broker storage, notification bodies, search jobs, Summon control
  bodies, and MCP parent/child IPC remain integer-valued. JSON syntax alone
  does not make an internal stored or transported value an external contract.
- Every non-null external Taut timestamp is exactly 19 ASCII decimal digits,
  produced by `simplebroker.format_message_id`; nullable fields stay JSON null.
- Exact public JSON message-id inputs use the same canonical string and are
  normalized to `int`. `log.since` is a pre-existing flexible cursor grammar,
  not a pure message-id field: keep ISO-8601, Unix-time, and native-id strings,
  plus JSON integer tokens no greater than `2**53 - 1`, and let the existing
  core resolver normalize them. Dump loading is separately tolerant of
  canonical strings and any exact direct JSON integer token. Floats, exponent
  notation, booleans, malformed strings, and out-of-range values are rejected.
- Conversion is explicit beside each owned field. Do not add a recursive walk,
  key-name heuristic, custom JSON encoder, private SimpleBroker import, or
  duplicate formatter.
- Counts, booleans, schema versions, PIDs, `claimed_unix_ns`, and unrelated
  numeric data remain JSON numbers.
- Dump/load has not been released, so the existing version-1 Taut core and
  Summon component numbers define the initial public contract. Writers emit
  canonical strings. Loaders accept either canonical strings or JSON integer
  tokens, since Python's JSON loader preserves integer values exactly, and
  normalize them immediately to Python integers. There is no version-2 bump or
  legacy component-version branch.
- The nested SimpleBroker component stays upstream dump version 1. Taut applies
  the same tolerant-reader rule to `id`/`last_ts` and passes the nested lines
  byte-for-byte unchanged. Floating-point tokens, exponent notation, booleans,
  malformed strings, and out-of-range values are rejected.
- Core dump projection is explicit by record type: `member.created_ts` and
  `last_active_ts`; `member_alias.created_ts`; `identity_claim.first_seen_ts`
  and `last_seen_ts`; nullable `thread.origin_ts`, `thread.created_ts`, and the
  owned nested `thread.meta.topic.updated_ts`; `membership.joined_ts` and
  `last_seen_ts`; and `channel_rename.started_ts` and `updated_ts`. Summon owns
  only `session.updated_ts`. No other nested JSON is traversed or rewritten.
- No dependency is added. This is a floor update of an existing dependency.
- Existing human output, CLI exit classes, field names, ordering, cursor
  semantics, storage values, and PostgreSQL behavior do not change.
- Do not mock SimpleBroker formatting, real CLI serialization, MCP schema
  validation, dump/load, or sidecar writes in the contract proofs.

Fatal errors: malformed or noncanonical external timestamp strings, an
unsupported component version, or a resolved dependency below the requested
floor. Best-effort behavior remains limited to existing notification/search
warnings and is not changed by this migration.

Stop and re-plan if implementation requires a private upstream import, changes
a Python dataclass timestamp type, changes a stored body, introduces a generic
JSON rewrite, adds a legacy component-version branch, or reveals an external
timestamp field with no owning spec.

## Rollout, Rollback, and Observable Success

Roll out the core `simplebroker>=7.0.0` and PG `simplebroker-pg>=3.5.2` floors
together; the PG patch itself requires core 7. Dump/load is unreleased, so the
version-1 component schemas are corrected in place before their first public
release. No operator migration or legacy component-version support is needed.

Before publication, rollback is a single revert of specs, manifests, locks,
formatters, schemas, and validators. After publication, the canonical writer
contract remains string-only. The tolerant reader is not a promise that an
older pre-release build can read newly written dumps.

Success signals after deployment:

- adjacent unsafe IDs above `2**53` remain distinct after CLI/MCP JSON parsing;
- public Python objects and backend rows still contain integers;
- a new composite dump contains string timestamps and round-trips to integer
  storage on SQLite and PostgreSQL;
- integer-token input loads without numeric change when Taut parses the
  original JSON directly, while float and exponent forms are rejected;
- `uv lock` resolves SimpleBroker 7.0.0 and SimpleBroker-PG 3.5.2 in every
  retained environment.

## Proposed Spec Delta

### [TAUT-3.4] / [TAUT-12.4] / [IAN-8.2] / [SUM-4] — dependency floor

Replace maintained active requirements with `simplebroker>=7.0.0` and
`simplebroker-pg>=3.5.2`. Record that 7.0.0 adds the public package-root
`format_message_id` helper and changes SimpleBroker-owned JSON IDs/high-water
values to exact strings while leaving Python and backend values integer. Taut
uses the formatter only at its own external JSON fields.

### [TAUT-3.5] and [TAUT-8.2] — external timestamp representation

Add this normative rule:

> Taut keeps the one SimpleBroker timestamp domain as integers in Python,
> sidecar/backend storage, broker message bodies, and internal process or work
> protocols. At an external JSON boundary, every non-null field representing a
> value from that domain is an exact 19-digit ASCII decimal string produced by
> the public `simplebroker.format_message_id` helper. This includes `ts`,
> `message_ts`, `last_ts`, `last_active_ts`, `topic_updated_ts`, and the
> timestamp fields in Taut-owned persistence components. Null stays null.
> Counts, versions, PIDs, Unix-clock measurements, and opaque payload JSON stay
> in their owned types. Formatting is explicit per owned field; Taut does not
> install a generic encoder or rewrite mappings by key name.

Retain [TAUT-8.3]'s integer Python dataclass fields unchanged. Amend each
[TAUT-8.2] shape description so its in-scope timestamp fields cite the rule.

### [IAN-7.2] and [SRCH-8.2] — stored JSON is internal

Add that notification payload `message_ts` and search message-job
`message_ts` remain integer values because those JSON objects are stored
internal broker bodies, not public output. Decode contracts remain strict and
unchanged.

### [SRCH-5.3] — search JSON

Replace the example hit's numeric `ts` with a quoted 19-digit string and state
that `SearchHit.ts` remains an integer in Python while external search NDJSON
uses [TAUT-8.2]'s canonical string.

### [MCP-6] — MCP records and schemas

Change `ts` and `message_ts` output schemas from integer to a 19-digit ASCII
decimal string pattern. Change nullable `last_ts` to string-or-null. Also apply
[TAUT-8.2] to `last_active_ts` and nullable `topic_updated_ts`. Remove the
instruction telling JavaScript clients to preserve an already-returned integer;
the server now returns exact strings. `audience_count` remains integer.
Retain `log.since`'s ISO-8601, Unix seconds/milliseconds/nanoseconds, and native
19-digit-id string grammar. Keep integer-or-null input only with a JSON Schema
maximum of `2**53 - 1`, and add the same runtime guard in `_commands.py` so
non-schema callers cannot bypass it. Pass accepted strings through to
`TautClient.log`, whose existing timestamp resolver normalizes them to Python
integers. Do not duplicate that resolver or force arbitrary strings through
`format_message_id`.

### [PIO-4.3], [PIO-4.4], [PIO-5.3], and [PIO-7.1] — dump representation

State:

> SimpleBroker dump version 1 may contain JSON integer tokens or canonical
> strings for `id`/`last_ts`. Taut validates both, orders by normalized integer
> identity, and passes the original lines unchanged to `load_lines()`.
>
> `taut-core` component version 1 emits every `*_ts` field and non-null
> `origin_ts` as [TAUT-8.2] canonical strings. It accepts either those strings
> or JSON integer tokens and normalizes both to integers before sidecar
> insertion.
>
> `taut-summon` component version 1 emits `updated_ts` as a canonical string.
> It accepts either that string or a JSON integer token and normalizes both to
> integer before sidecar insertion.

These version-1 schemas are the initial public dump/load contract. Tolerant
field parsing does not introduce a legacy component-version loader. Taut parses
the original JSON with Python; it cannot detect corruption introduced before
the bytes reach it.

For `taut-core`, the timestamp inventory is explicit by record type as listed
in this plan's invariants. The nested `thread.meta.topic.updated_ts` is
Taut-owned metadata, not opaque user JSON, so it is formatted and normalized
explicitly. Broker message bodies and all other metadata remain byte-for-byte
or value-for-value in their owned representation.

Update [PIO-11] to require raw token-type assertions above `2**53`, adjacent-ID
stability, version-1 round trips through both accepted input token types,
rejection of float/exponent and boolean values, and integer storage after load.

## Tasks

1. Independent plan and proposed-delta review.
   - Reviewer: Grok or Claude, read-only, using `skills/call-agent/SKILL.md`.
   - Inputs: this plan, all cited specs/implementation notes, upstream v7 tag,
     current renderers/schemas/persistence code.
   - Done: every finding dispositioned in the Review Log and a corrective PASS
     verifies the accepted fixes.

2. RED→GREEN: establish the SimpleBroker 7 runtime floor before importing its
   formatter.
   - First strengthen dependency and release-gate tests to require exactly the
     supported floors `simplebroker>=7.0.0` and `simplebroker-pg>=3.5.2`, and
     observe them fail against the current manifests and release scripts.
   - Raise root and PG manifests; update `bin/build-and-check-release-wheels.py`,
     `bin/check-core-summon-wheel-matrix.py`, their firing tests, and metadata
     consistency tests; update every maintained active floor claim in the same
     slice; then regenerate root/Summon/MCP retained locks.
   - Inspect exact resolutions. The MCP lock reconciliation is mandatory
     because it is already behind the current root floor. Do not create a PG
     lockfile or accept unrelated major dependency drift.

3. Promote the reviewed spec delta atomically with the core CLI tracer bullet.
   - Files: the six cited product specs and their `## Related Plans` sections,
     manifests/floor claims established in task 2, and
     `taut/commands/_rendering.py`.
   - Add this plan's reciprocal backlinks and record the promotion baseline
     identifier.
   - Tests: `tests/test_cli.py`, `tests/test_search_cli.py`; use fixed adjacent
     IDs above `2**53` and nullable metadata cases. Observe RED after adding the
     output assertions, then apply explicit package-root formatter calls.
   - Prove CLI JSON strings and unchanged integer domain objects. Human output
     stays unchanged. Stop if the delta expands beyond external representation
     or version-floor compatibility.

4. RED→GREEN: MCP JSON input, command/resource output, and closed schemas.
   - Tests: every MCP suite that asserts record or schema timestamp types,
     including `test_tools.py`, `test_channel_tools.py`, `test_resource.py`,
     `test_process_reactor.py`, `test_stdio_server.py`, and
     `test_pg_conformance.py`. Use fixed adjacent IDs above `2**53` for
     `log.since` and output records. Closed-schema assertions live in those
     tests; there is no separate snapshot file.
   - Code: `_commands.py`, `_process_reactor.py`, `_tools.py`.
   - Prove `log.since` retains ISO-8601, Unix-time, and native-id strings plus
     safe JSON integers; rejects bare integers above `2**53 - 1` in both schema
     and dispatch; and reaches integer comparison only through the existing
     core resolver. Also prove structured content and canonical text agree,
     resource notifications use the same strings, schemas reject numeric
     public output IDs, and counts stay numeric.

5. RED→GREEN: SimpleBroker 7 nested dump and Taut persistence boundaries.
   - Tests: core and adversarial persistence tests plus Summon and PostgreSQL
     round trips. Use real `dump_lines()`, `load_lines()`, queues, and sidecars.
   - Code: `taut/persistence/_format.py`, `_operations.py`, Summon persistence
     adapter/manifest, and the narrow load normalization paths. Core output is
     an explicit per-record-type projection in `_operations.py`; core input is
     normalized both for `_CoreValidator` and again in
     `ParsedDump.core_records()` before insertion. Summon formats only
     `updated_ts` in `dump_records()` and normalizes it in `load_records()`.
     `_accept_simplebroker` and the nested header normalize identity for
     ordering/dedup while preserving original lines for `load_lines()`.
   - Prove nested v7 strings are accepted byte-for-byte, exact integer-token
     input is accepted, core/Summon v1 emits strings, both accepted input forms
     load, float/exponent and boolean forms fail, and restored DB values are
     integers.

6. Align durable implementation docs, README examples/warnings, and complete
   traceability.
   - Files: architecture, Summon, persistence I/O notes, repository map if the
     new plan requires its established plan inventory entry; root/MCP READMEs;
     MCP server instructions; and this plan's execution/review logs.
   - Update `docs/plans/README.md`; do not mark completed without a commit.
   - Evaluate the TDD and call-agent skills for omissions; change no process
     guidance unless separately authorized and classified.

7. Final independent scoped-change review.
   - Review the exact worktree delta against the promoted specs and upstream
     tag. Reproduce every finding before accepting it; disposition every item.

## Testing Plan

Vertical tracer bullets are tasks 3 through 5. For each, add one public
behavior test, observe the integer-output or rejection failure against the
current code, apply the narrow production change, and rerun to green before
adding the next boundary. Expected values are fixed 19-digit literals, not
computed with the production formatter.

Do not mock formatter behavior, CLI JSON, MCP validation, nested dump/load, or
sidecar insertion. Mocks remain acceptable only for existing discovery/fault
injection seams outside the serialization behavior.

Targeted gates, refined after test discovery:

```text
uv run --extra dev pytest tests/test_cli.py tests/test_search_cli.py -q -n0
uv run --project extensions/taut_mcp --extra dev pytest \
  extensions/taut_mcp/tests -q -n0
uv run --extra dev pytest tests/test_persistence_io.py \
  tests/test_persistence_io_adversarial.py \
  extensions/taut_summon/tests/test_persistence.py -q -n0
uv run --extra dev pytest extensions/taut_pg/tests/test_persistence_io.py -q -n0
```

## Verification and Gates

- `uv run --extra dev pytest` (full default repository suite)
- repository Postgres lane required by existing markers/configuration
- `uv run --extra dev mypy taut tests bin/release.py extensions/taut_pg/taut_pg
  extensions/taut_pg/tests --config-file pyproject.toml`
- `uv run --extra dev mypy taut tests extensions/taut_summon/taut_summon
  extensions/taut_summon/tests --config-file pyproject.toml`
- `uv run --project extensions/taut_mcp --extra dev mypy
  extensions/taut_mcp/taut_mcp extensions/taut_mcp/tests --config-file
  extensions/taut_mcp/pyproject.toml`
- `uv run ruff check .` and `uv run ruff format --check .`
- `uv run pytest tests/test_dependency_floor_claims.py
  tests/test_project_metadata_consistency.py -q -n0`
- `bin/check-plan-status-index`, `bin/check-doc-paths`, and
  `uv run bin/check-cli-claims`
- inspect every retained lock for exact SimpleBroker 7.0.0 and PG 3.5.2
- inspect `git diff --check` and `git status --short`

Residual risk must name any unrun PostgreSQL, hosted CI, or release-artifact
lane. Local green SQLite tests do not substitute for a PG compatibility run.

## Independent Review Loop

Plan review uses a different-family read-only reviewer and the PASS/BLOCKED
stance from the review runbook. Completed-work review uses the scoped-change
template: external string representation is the unit; unchanged integer
internal/storage representation is a standing constraint; pre-existing
concerns are observations unless this delta worsens them. Findings are claims
and enter the append-only Review Log with accepted/rejected/out-of-scope
dispositions and evidence.

## Out of Scope

- changing public Python timestamp/id types
- changing notification, search-job, Summon control, or MCP IPC stored bodies
- migrating sidecar schemas or backend columns
- generic JSON-safe-integer conversion for unrelated application numbers
- changing human output or exact-message input grammar
- adding Redis support or upgrading Taut package versions
- publishing packages, tags, commits, or pull requests

## Deviation Log

| Spec ref | Planned behavior | Actual behavior | Rationale | Spec proposal |
|----------|------------------|-----------------|-----------|---------------|

## Review Log

Round 1 used Grok 0.2.101 under the OS-enforced read-only sandbox with a 540 s
bound. The response supplied a full explicit `BLOCKED` verdict, but the CLI
completion field was `end_turn` rather than the skill's documented `EndTurn`.
No sandbox fail-open warning or repository write occurred. The findings are
retained and dispositioned below. Claude Opus then completed two corrective
passes: round 2 found one remaining `log.since` defect, and round 3 verified
that focused correction with a final `PASS`.

| ID | Finding | Disposition | Evidence |
|----|---------|-------------|----------|
| R1 [P1] | “Task order cannot reach green against the stated helper.” | Accepted. The dependency/release floor is now the first RED→GREEN slice, before any formatter import. | Task 2 now raises/tests floors and locks; Task 3 starts formatting. |
| R2 [P1] | “Named Summon persistence test path does not exist.” | Accepted. | The plan now names `extensions/taut_summon/tests/test_persistence.py`, which exists. |
| R3 [P1] | “Core dump emit ownership is underspecified relative to ‘no key walker’.” | Accepted. | Invariants and Task 5 now enumerate an explicit per-record projection plus both validate-time and insert-time normalization seams. |
| R4 [P2] | “Nested `meta.topic.updated_ts` is an unowned external boundary.” | Accepted with the full-boundary option. This is Taut-owned topic metadata, not opaque user JSON. | The exact nested path is now included in invariants, spec delta, output projection, and reciprocal normalization. |
| R5 [P2] | “MCP test inventory under-names real contract owners.” | Accepted. | Task 4 names all six existing MCP suites with integer/schema expectations and removes nonexistent snapshot wording. |
| R6 [P2] | “SimpleBroker nested identity tracking must normalize before compare/dedup.” | Accepted. | Task 5 names `_accept_simplebroker`, the nested header, ordering/dedup normalization, and byte-preserving replay. |
| R7 [P3] | “Spec floor promotion must move with manifests or the floor gate fails mid-worktree.” | Accepted. | Task 2 moves every maintained active floor claim with manifests, release gates, and locks. |
| R8 [P3] | “Extension typing commands defined in the project configuration is vague.” | Accepted. | Verification now lists the three collision-safe canonical mypy invocations from `README.md`. |
| R9 [nit] | “MCP lock is already behind root floor.” | Accepted as a mandatory reconciliation note. | Task 2 explicitly makes MCP lock reconciliation mandatory. |
| R10 [nit] | “Comprehension / preflight claims are fine; driver still wrong.” | Addressed by R1; no separate action. | Task order now makes the formatter available before implementation. |
| A1 [audit] | MCP `log.since` was omitted even though it is an external JSON input and can be corrupted before Python receives it. | Accepted. | Context, invariants, [MCP-6], Task 4, and tests now require canonical string input and immediate integer normalization. |
| A2 [audit] | Release gates still encode old minimums and must make 7.0.0/3.5.2 the actual supported floor. | Accepted. | Task 2 names both release scripts, their firing tests, metadata consistency, manifests, floor claims, and all retained locks. |
| R2-A1 [round 2 FAIL] | The first A1 disposition misclassified flexible `log.since` as a pure message-id field, dropping ISO-8601/Unix string forms and duplicating core normalization. | Accepted; supersedes the earlier A1 remedy without deleting its audit history. Preserve the full string grammar and safe integers, reject only bare JSON integers above `2**53 - 1`, and use the existing core resolver. | Context, comprehension check 4, invariants, [MCP-6], and Task 4 now state the narrowed schema/runtime guard and preserve cursor semantics. |
| R2-R1–R9/A2 | All other round-1 fixes verified against executable owners. | Closed. | Claude Opus round 2 verified every named seam, test path, release gate, lock, and mypy command; only A1 failed. |
| R3-A1 [round 3 PASS] | The focused correction preserves the full string cursor grammar, bounds only bare JSON integers, and reuses the core resolver. | Closed. Implementation may proceed. | Claude Opus verified the plan against `_tools.py`, `_commands.py`, and `_messaging.py`; final verdict `PASS`. The schema description wording remains an implementation task under [MCP-6]. |
| F0 [review harness] | The first completed-work Claude Opus invocation reached its 540 s bound without a verdict. | Closed as an unsuccessful review attempt, not treated as approval. | A second read-only invocation used streamed output and completed with an explicit no-blocker result. |
| F1 [P3] | `_CORE_TIMESTAMP_FIELDS` was duplicated between the persistence writer and reader, so their explicit inventories could drift. | Accepted. | `_format.py` is now the single definition; `_operations.py` imports and uses it. |
| F2 [nit] | The nullable formatter adapter is duplicated between CLI and MCP modules. | Rejected as cosmetic within this change. | The two copies sit beside distinct boundary owners, contain one null check plus one public-helper call, and there is no third shared policy to justify a new cross-package abstraction. |
| A3 [audit] | Upstream's formatter accepts whitespace and non-ASCII decimal digits before canonicalizing, which is wider than Taut's exact 19-digit ASCII loader contract. | Accepted. | Core, nested SimpleBroker, and Summon string loaders now require the input string to equal the formatter result. Six new RED probes for whitespace/non-ASCII strings became green; JSON integer tokens remain accepted. |
| F3 [focused corrective PASS] | Re-review F1 consolidation and A3 exact-string guards for new defects. | Closed. | Claude Opus verified both fixes, every normalization call path, byte-preserving nested replay, canonical record checks, and relevant tests; final verdict `PASS`. |

## Execution Log

| Slice | Status | Evidence |
|-------|--------|----------|
| Preflight | complete | Clean worktree; baseline `6d19465`; upstream tag `b58ef66`; external/internal boundary confirmed by owner. |
| Plan review | complete | Grok round 1 `BLOCKED`; Claude Opus round 2 isolated one defect; focused round 3 returned `PASS` after correction. |
| Dependency floor | complete | Seven intended RED failures; then 25 release/matrix cases, four dependency/metadata gates, two floor-claim cases, and all three retained `uv lock --check` gates passed. Root/MCP resolve SimpleBroker 7.0.0 and PG 3.5.2; Summon resolves SimpleBroker 7.0.0. |
| CLI boundary tracer | complete | Six intended RED probes became green after explicit package-root formatter calls; fixed adjacent IDs stay distinct, nullable values stay null, and dataclass values remain integers. |
| MCP boundary tracer | complete | Unsafe bare `log.since` integer, record encoding, duplicated notification resource, and closed-schema probes were RED, then 11 focused cases passed after the schema/runtime changes. |
| Persistence boundary tracer | complete | Initial writer/reader probes failed against numeric output and int-only nested validation, then passed with explicit projections and integer normalization. A later canonicality audit added six RED whitespace/non-ASCII cases; the equality guards made them green. The final core, adversarial, and Summon persistence set reached 100% (76 cases), and nested SimpleBroker lines remained byte-for-byte inputs to `load_lines()`. |
| Documentation and traceability | complete | Six product specs, four implementation notes, root/MCP README text, server instructions, plan index, and reciprocal related-plan links now state the same external-string/internal-integer boundary. `check-plan-status-index`, `check-doc-paths` (58 sources, 1105 claims), and `check-cli-claims` (58 sources, 240 claims) pass. |
| Final verification | complete | Full root suite reached 100% with one Windows-only skip after deselecting three confirmed baseline assertions. Full MCP reached 100% with six PG cases skipped locally; those same PG cases had already passed against a temporary PostgreSQL container. The repository `pytest-pg --fast` lane passed 247 shared plus 35 extension cases. All three canonical mypy invocations passed (134, 163, and 18 files). Ruff check, scoped 207-file format check, dependency floors, lock checks, and `git diff --check` pass. Hosted CI and release-wheel builds were not run. Global format check still reports only three pre-existing historical Markdown plans. |
| Final review | complete | The successful completed-work review returned no blocker. F1 was fixed, F2 was rejected with evidence, A3 was found and fixed during local audit, and the focused corrective review returned `PASS`. The TDD runbook exposed A3 before handoff. The call-agent streaming path avoided another silent timeout; the agent inventory records the observed completion-field drift. No skill change is needed. |
