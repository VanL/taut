# Automatic Display-Name Capitalization Plan

Plan type: implementation with spec revision

## 1. Goal

Capitalize the first ASCII letter of every automatically generated human or
agent display name, including implied-provider Summon names; preserve explicit
user-supplied casing; and extend the Pi agent collision family to `Pi`, `Tau`,
then `Phi`. Routing remains case-insensitive through lowercase `name_key`
values.

## 2. Source Documents

Source specs:

- `docs/specs/03-identity-addressing-notifications.md` [IAN-3.3], [IAN-4.1],
  [IAN-4.2], [IAN-4.4]
- `docs/specs/02-taut-core.md` [TAUT-5]
- `docs/specs/04-summon.md` [SUM-3], [SUM-4]

Supporting implementation context:

- `docs/implementation/04-taut-architecture.md`, identity-resolution and
  first-contact naming rationale
- User decision in the 2026-07-12 task: automatic human and agent display
  names use the same capitalization rule; Pi collisions use Tau then Phi.

## 3. Context and Key Files

- `taut/_constants.py` owns name validation, lowercase route normalization,
  normalized seed generation, and curated per-agent candidate pools.
- `taut/identity.py::choose_name` owns deterministic automatic candidate
  selection. It must canonicalize every supplied taken display name, alias, or
  route key through `route_key` before availability checks.
- `taut/client/_identity.py::_create_member` is the one creation boundary. It
  sends automatic seeds through `choose_name`; explicit `--as`/`TAUT_AS` names
  bypass that helper and must remain byte-for-byte case-preserved.
- `taut/state/_sql.py::member_names_in_use` currently omits aliases even though
  aliases share the route namespace. Replace that misleading internal method
  with `route_keys_in_use`, returning member `name_key` and `alias_key` values
  through one portable SQL query; update the `TautState` protocol and race-test
  monkeypatches together.
- `extensions/taut_summon/taut_summon/_driver.py::_fallback_name` is the second
  production `choose_name` consumer. An implied provider such as
  `taut summon pi` is an automatic name and must become `Pi`; a chosen name such
  as `taut summon reviewer --provider pi` is explicit and remains `reviewer`.
  Summon must normalize display names, aliases, and attempted candidates through
  the same `choose_name` boundary.
- `tests/test_client.py` can prove the behavior through the public
  `TautClient(identity_capture=...)` seam with real SQLite state.
- `tests/test_identity.py` contains the narrow deterministic candidate-order
  checks and must align with the display-name return contract.
- `README.md` and `docs/implementation/04-taut-architecture.md` describe the
  visible naming behavior and rationale.

Comprehension gates before editing:

1. Why must availability compare `route_key(candidate)` to `taken`, rather
   than compare the cased display candidate directly?
2. Why must explicit names bypass automatic capitalization even though their
   route keys are lowercase?
3. Why is `taut summon pi` automatic while
   `taut summon reviewer --provider pi` is explicit?

## 4. Invariants and Constraints

- `member_id`, identity claims, recognition order, and persistence schema do
  not change.
- Existing stored member names and historical message sender snapshots are not
  migrated or rewritten.
- Only automatically generated names are recased. Explicit `--as`, `TAUT_AS`,
  `TautClient(as_name=...)`, and `set name` input preserves caller casing.
- Automatic display casing is deliberately simple: scan left-to-right,
  uppercase the first lowercase ASCII letter `[a-z]`, and leave all other
  characters unchanged. Thus `2agent` becomes `2Agent`, `123` stays `123`, and
  `new-agent` becomes `New-agent`. Do not infer human names, split words, or
  title-case suffixes.
- Name validation remains ASCII and route uniqueness remains lowercase.
- Curated candidate constants carry their intended display casing. Candidate
  lookup keys remain normalized lowercase process basenames.
- The available-route snapshot contains both member name keys and alias keys.
  A taken alias must advance automatic selection instead of causing the same
  candidate to fail repeatedly at insertion.
- The selection order stays seed, per-basename pool, shared historical pool,
  then numeric suffix. Pi's exact first three candidates are `Pi`, `Tau`,
  `Phi`.
- Real client/state behavior must not be mocked. Synthetic process capture is
  allowed only through the existing public constructor seam.
- No new dependency, alias command, or alternate creation path. Summon schema
  version 2 requires one bounded forward migration of its transient claim keys;
  the version-3 expression index and normalized query are the single canonical
  route identity and keep an already-running version-2 writer safe during
  rollout. There are no durable session or core schema changes.
- Summon's provider lookup remains lowercase and independent of its capitalized
  member display name. Resummon continues to resolve the current route and use
  the stored provider.

Stop and re-plan if implementation requires a schema change beyond the approved
transient-claim v2-to-v3 migration, recases durable member/message rows, changes
public route matching, or introduces a second automatic-name path.

## Rollout and Rollback

Summon schema version 3 atomically lowercases version-2 transient claim keys and
creates a unique `(LOWER(name), provider)` index. Index construction serializes
with old claim inserts; normalized v3 lookup keeps any later v2 mixed-case claim
visible. Migration refuses a legacy or racing case-variant collision before
commit, leaving version 2 intact for operator resolution and retry. The success
and fail-before-mutation proofs run on SQLite and PostgreSQL. Durable sessions, core state, existing
members, and message snapshots are not migrated. New automatic members use the
new display casing immediately. Core and Summon are
separately packaged, so release order is mandatory: publish the new core first,
then publish the paired Summon version with its `taut>=X.Y.Z` floor set to that
core version by `bin/release.py`. Do not publish this Summon behavior against an
older core floor. This feature change does not guess or bump the next release
number; the release slice owns coordinated manifests, README pins, changelog,
and tags, with `tests/test_project_metadata_consistency.py` as the floor gate.

A forward fix is the preferred rollback after schema version 3. To reinstall
the paired v2 core/Summon artifacts: block new Summon invocations; stop every
driver; verify `SELECT COUNT(*) FROM taut_summon_claims` is zero; transactionally
set `taut_meta.value` to `2` for `summon_schema_version`; install both older
packages; then unblock summons. The expression index may remain because it only
strengthens v2 uniqueness. Never downgrade the version key with a claim in
flight or roll back only one of the paired packages. Existing capitalized names
and message snapshots are not rewritten; names remain mutable through
`set name`.

Post-release success is observable by creating fresh core captures and an
implied-provider Summon, then checking `whoami`: route lookup remains
case-insensitive while returned automatic names are capitalized.

## Spec Baseline

- `c7266dd` — `docs/specs/03-identity-addressing-notifications.md`,
  `docs/specs/02-taut-core.md`, and `docs/specs/04-summon.md` at plan authoring
  time.
- Worktree note: the user-directed `Pi -> Tau` precursor is already present as
  an uncommitted change in `taut/_constants.py` and `tests/test_client.py`.
- Promotion baseline: `c7266dd` plus the uncommitted worktree diff in
  `docs/specs/03-identity-addressing-notifications.md` and
  `docs/specs/04-summon.md`; promotion applied after independent review. The
  rerunnable reference gate is `pytest -q tests/test_docs_references.py`.

## Proposed Spec Delta

Promotion strategy: **A — in-file, text before link claims**. Promote the
reviewed requirement text and plan backlinks before changing code. Add the
implementation/test mapping claims only after the core and Summon slices pass.

### `docs/specs/03-identity-addressing-notifications.md` [IAN-4.2]

Insert after the route-key paragraph:

> Automatically generated human and agent display names use the same display
> casing rule: normalize the login or process seed, then scan left-to-right,
> uppercase the first lowercase ASCII letter `[a-z]`, and leave all remaining
> characters unchanged. A digit-leading seed such as `2agent` therefore becomes
> `2Agent`; a seed with no ASCII letter is unchanged. Curated
> fallback candidates carry their intended display casing. Explicit names
> supplied through `--as`, `TAUT_AS`, the Python API, or `set name` are
> case-preserving and are never recased automatically. All forms still route
> through the lowercase `name_key`.

### `docs/specs/03-identity-addressing-notifications.md` [IAN-4.4]

Insert after the automatic-generation paragraph:

> Automatic candidate order is the normalized seed, a curated per-agent pool
> when one exists, the shared historical-name pool, then a numeric suffix. The
> Pi family begins `Pi`, `Tau`, `Phi`.

### `docs/specs/04-summon.md` [SUM-3]

Insert after the implied-name/chosen-name distinction:

> An implied provider name is an automatically generated display name under
> [IAN-4.2]. `taut summon pi` therefore starts with member name `Pi`, while
> `taut summon reviewer --provider pi` preserves the explicitly chosen
> `reviewer`. Provider registry keys remain lowercase and do not change when
> the member display name is capitalized.

Replace the existing lowercase result examples in [SUM-3]:

> the convenience form (`taut summon claude`, name implied by the provider)
> falls back through the [IAN-9] pool — a second Claude becomes `Claudette` or
> `Claude-2`, with a console note

### `docs/specs/03-identity-addressing-notifications.md` [IAN-10]

Add required proofs:

> - automatic human and agent names use the [IAN-4.2] display casing rule while
>   explicit names preserve caller casing
> - automatic availability includes both current names and aliases in the
>   lowercase route namespace
> - the Pi automatic sequence begins `Pi`, `Tau`, `Phi`

### `docs/specs/04-summon.md` [SUM-4]

Replace the implied-name example and clarify the post-claim race:

> (`summoned as 'Claudette' — 'claude' is taken`).

> A chosen name bypasses automatic selection at initial resolution and refuses
> an already-visible collision. If a route collision appears only after its
> transient claim was acquired, the existing [SUM-4] recovery rule releases the
> claim and chooses a fallback; that fallback is automatic and therefore uses
> [IAN-4.2] display casing for both implied and initially chosen requests.

## Deviation Log

| Spec ref | Planned behavior | Actual behavior | Rationale | Spec proposal |
|----------|------------------|-----------------|-----------|---------------|
| [SUM-4], [SUM-8] transient claims | Capitalize implied Summon display names while preserving existing claim serialization | A real collision test showed `scripted` and `Scripted` occupied distinct transient claim slots | Claim identity was exact display text even though visible routes are case-insensitive; capitalization exposed the hidden mismatch | Promoted [SUM-4]/[SUM-8] clarification: claim boundaries store the lowercase route key |
| [SUM-8] stored version-2 claims | Treat claim rows as transient and normalize new accesses only | Final review showed a mixed-case pre-upgrade row would become invisible and could coexist with a new lowercase row | Transient does not mean absent at upgrade; stored serialization changes need a forward transition | Promoted schema-v3 migration: normalize atomically, fail before mutation on case-variant collapse |

## 5. Tasks

1. Independently review this plan and exact spec delta.
   - Reviewer reads the governing spec, current constants, `choose_name`,
     creation boundary, and current tests.
   - Done signal: all findings are incorporated or answered before code work.

2. Promote the reviewed naming contract before implementation.
   - Files: `docs/specs/03-identity-addressing-notifications.md`,
     `docs/specs/04-summon.md`, and their Related Plans sections.
   - Record the promotion baseline as `c7266dd` plus the exact spec diff and
     the rerunnable `pytest -q tests/test_docs_references.py` gate.

3. Prove automatic capitalization through the public client boundary.
   - Extend `tests/test_client.py` one red-green behavior at a time: an
     automatic agent seed displays as `Codex`; a human login displays as `Van`;
     three distinct Pi captures display as `Pi`, `Tau`, `Phi`; lowercase route
     selectors still resolve the cased names; explicit lowercase input remains
     lowercase; an alias occupying an automatic candidate advances selection.
   - Keep real SQLite state and the public `TautClient` path.
   - Mirror the alias-owned candidate proof in `tests/test_shared_contract.py`
     so `bin/pytest-pg --fast` executes the new portable SQL query on Postgres.

4. Implement the canonical core candidate and route-snapshot paths.
   - Files: `taut/_constants.py`, `taut/identity.py`, `taut/state/__init__.py`,
     `taut/state/_sql.py`, `taut/client/_identity.py`, and affected race tests.
   - Store curated candidates with display casing, compare their lowercase
     route keys with `taken`, and return cased seed/history/numeric candidates.
   - Reuse `route_key`; do not add a second normalization rule.

5. Apply the same contract to implied Summon names.
   - Files: `extensions/taut_summon/taut_summon/_driver.py`,
     `extensions/taut_summon/tests/test_driver.py`, and any existing exact-name
     tests exposed by the focused Summon run.
   - Implied names call `choose_name` even for the first available candidate.
     Chosen names bypass it initially; a post-claim route race retains the
     existing automatic fallback and therefore uses cased candidates. Provider
     resolution remains lowercase.

6. Align narrow tests and durable documentation.
   - Files: `tests/test_identity.py`, `README.md`,
     `docs/implementation/04-taut-architecture.md`, and
     `docs/implementation/05-taut-summon-architecture.md`.
   - Explain that OS login/process basename is evidence or a seed, not the
     returned Taut display name.
   - Update `tests/test_identity.py::_expected_name_from_anchor` and map existing
     explicit-case proofs: `TautClient(as_name=...)`, CLI `--as`, `TAUT_AS`, and
     `set name`.

7. Run verification, traceability reconciliation, and independent final review.
   - Address every review finding or record why no change is warranted.
   - Do not claim landing readiness while changes remain uncommitted.
   - Record the release boundary: core first, then paired Summon with the floor
     synchronized to the chosen release version. Do not mutate versions in this
     feature slice.

## 6. Testing Plan

Use public `TautClient` tests with real SQLite for externally visible creation,
routing, and explicit-name preservation. Use the existing pure
`choose_name` test only to pin fallback order and suffix spelling. Do not mock
the state layer, identity resolver, or route normalization.

Required observable proofs:

- automatic agent: `codex` seed returns `Codex`
- automatic human: `van` login returns `Van`
- Pi collisions return `Pi`, `Tau`, `Phi` in order
- digit-leading `2agent` becomes `2Agent`; digit-only `123` stays `123`
- lowercase selectors resolve capitalized display names
- explicit lowercase names stay lowercase
- an alias occupying a candidate advances automatic selection
- implied `taut summon pi` uses `Pi`; chosen
  `taut summon reviewer --provider pi` remains `reviewer`
- Summon schema v2 mixed-case claims migrate to lowercase route keys; colliding
  legacy case variants fail before mutation
- shared historical fallback and numeric suffixes are capitalized

## 7. Verification and Gates

Per-slice:

```bash
pytest -q tests/test_client.py::test_automatic_agent_name_capitalizes_first_ascii_letter
pytest -q tests/test_client.py::test_automatic_human_name_capitalizes_first_ascii_letter
pytest -q tests/test_client.py::test_repeated_pi_agents_use_capitalized_curated_names
pytest -q tests/test_client.py::test_automatic_name_skips_alias_owned_route
pytest -q tests/test_identity.py::test_choose_name_uses_seed_pool_history_then_numeric_suffix
pytest -q extensions/taut_summon/tests/test_driver.py -k 'name or fallback or implied'
```

Final:

```bash
pytest -q tests/test_identity.py tests/test_client.py tests/test_cli.py tests/test_shared_contract.py
pytest -q extensions/taut_summon/tests/test_driver.py
uv run ./bin/pytest-pg --fast
ruff format --check taut tests bin extensions/taut_pg/taut_pg extensions/taut_pg/tests extensions/taut_summon/taut_summon extensions/taut_summon/tests
ruff check taut tests bin extensions/taut_pg/taut_pg extensions/taut_pg/tests extensions/taut_summon/taut_summon extensions/taut_summon/tests
mypy taut tests bin/release.py extensions/taut_pg/taut_pg extensions/taut_pg/tests --config-file pyproject.toml
mypy taut tests extensions/taut_summon/taut_summon extensions/taut_summon/tests --config-file pyproject.toml
pytest -q tests/test_project_metadata_consistency.py
pytest -q tests/test_docs_references.py
git diff --check
```

Success means every named proof passes, the spec/plan/implementation/code chain
is reciprocal, and the independent reviewer finds no unresolved correctness
issue. Residual risk: existing members keep their old casing by design.

## 8. Independent Review Loop

Use an isolated review agent with no implementation authority. It reads this
plan, the proposed delta, [IAN-4], `taut/_constants.py`, `taut/identity.py`,
`taut/client/_identity.py`, the state route snapshot, Summon's fallback path,
and the named tests. It should challenge route-key collisions, explicit-name
preservation, core/Summon consistency, migration assumptions, and proof
coverage. The author incorporates or explicitly answers every finding. The
same reviewer may perform the final diff review after tests pass; note if only
the same agent family is available.

Initial review disposition:

- Accepted: add Summon as a production `choose_name` consumer and specify
  implied versus chosen names.
- Accepted: replace the name-only snapshot with an all-route-key snapshot and
  add an alias regression.
- Accepted: define digit-leading behavior as scanning for the first `[a-z]`.
- Accepted: correct the Python surface to `TautClient(as_name=...)`, map each
  explicit path to tests, and update `_expected_name_from_anchor`.
- Accepted: add [IAN-10] proofs, exact promotion evidence, implementation-doc
  backlinks, and Summon verification.
- Accepted on second review: replace every lowercase normative Summon result,
  retain cased automatic fallback after a chosen-name post-claim race, require
  core-first paired release/floor sequencing without guessing the next version,
  include spec 04 in the baseline, use the canonical static gates, and run the
  alias-route proof through the shared Postgres contract lane.
- Final implementation review: initial findings required the schema-v3
  claim-key migration and exact Pi bootstrap proof; follow-up required the
  cross-backend route expression index, PostgreSQL migration proofs, and an
  executable rollback. After those changes and reruns, the reviewer returned
  `CLEAR`.

## 9. Out of Scope

- Inferring legal or full human names from login data
- Unicode or free-form display names
- Recasing existing members or historical messages
- New providers beyond the requested Pi candidate extension
- Reordering existing non-Pi curated pools
- Alias-management changes

## 10. Fresh-Eyes Review

Before completion, verify that a new implementer can identify the one automatic
selection path, the lowercase collision boundary, the explicit-name bypass,
the public tests, rollback behavior, and the exact spec text without inference.

## Execution Evidence

| Slice | Red evidence | Green evidence |
|---|---|---|
| Automatic core display casing | `test_automatic_agent_name_capitalizes_first_ascii_letter` returned `codex` instead of `Codex` | Focused agent and human public-client tests passed |
| Pi family and fallback casing | Pi client test returned lowercase `tau`; narrow fallback test returned lowercase `new-agent` | `Pi`, `Tau`, `Phi`, `New-agent`, `Ada`, and `Agent-2` proofs passed; every curated candidate is reachable in declared order |
| Alias-aware availability | Public client retried alias-owned `Codex` five times and raised `IdentityError` | SQLite public-client and shared PostgreSQL contract select `Codette` |
| Implied Summon casing | Real driver created `scripted` instead of `Scripted` | Real driver, persona, terminal-post, mouth, collision, and complete Summon suite passed with cased names |
| Transient claim route identity | `Scripted` and `scripted` occupied separate claim rows | State and real driver collision tests prove one lowercase route-key slot |
| Version-2 claim migration | Mixed-case version-2 fixture remained at schema 2 and was invisible through normalized lookup | Schema 3 atomically lowercases non-conflicting claims and refuses colliding case variants before mutation |
| Exact Pi Summon boundary | Final review found only generic implied-name Summon coverage | Bootstrap-boundary test proves implied `pi` becomes `Pi` and chosen `reviewer --provider pi` stays `reviewer` without spawning the external harness |

Final reruns from the current worktree:

- `pytest -q`: exit 0
- `pytest -q extensions/taut_summon/tests`: exit 0; eight configured live-provider onboarding skips
- `uv run ./bin/pytest-pg --fast`: 86 shared and 13 PG-only passed
- canonical Ruff format/check: 85 files clean
- canonical mypy lanes: 53 and 75 source files clean
- docs-reference plus metadata gates: 12 passed
- `git diff --check`: exit 0

Release boundary remains explicit: this uncommitted feature work does not choose
or mutate a version. A future release must publish core first and synchronize
the paired Summon dependency floor to that version before publishing Summon.
