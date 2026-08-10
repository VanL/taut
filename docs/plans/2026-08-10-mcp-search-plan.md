# MCP Search Plan

Date: 2026-08-10

Status: completed after implementation, verification, and independent review

Class: 5 — changes the fixed public MCP manifest, schemas, result contract, and
agent-facing guidance. No storage migration is introduced.

Baseline: `50a67eb9e541` (`Adopt SimpleBroker 7 JSON message ID boundaries`).

## Goal

Expose Taut's existing full-text search through one explicit MCP `search` tool
so MCP-only agents can discover workspace history without knowing a thread in
advance. The adapter must preserve the core search query, visibility, result,
index-repair, and backend-quality contracts. It must not reflect CLI commands
automatically, invent a second search language, move cursors, consume inboxes,
or imply identical ranking across SQLite and PostgreSQL.

## Source Documents

- `README.md`, especially the human-and-agent product claim and Search section
- `docs/program-theory.md` (THEORY-2, THEORY-3, THEORY-4, THEORY-6)
- `docs/specs/product-section-registry.md` (MCP and Search ownership rows)
- `docs/specs/02-taut-core.md` [TAUT-6.5], [TAUT-8.1], [TAUT-8.2], [TAUT-9]
- `docs/specs/05-taut-mcp.md` [MCP-3]–[MCP-6], [MCP-9]–[MCP-12]
- `docs/specs/06-search.md` [SRCH-1]–[SRCH-12]
- `docs/implementation/07-taut-mcp-architecture.md`
- `docs/implementation/09-search-architecture.md`
- `docs/agent-context/runbooks/writing-plans.md`
- `docs/agent-context/runbooks/hardening-plans.md`
- `docs/agent-context/runbooks/testing-patterns.md`
- `docs/agent-context/runbooks/adversarial-acceptance-probes.md`
- `docs/agent-context/runbooks/designing-agent-facing-interfaces.md`

## Current Structure and Key Files

- `taut/client/_searching.py` owns `TautClient.search`; it is the sole domain
  operation the new handler may invoke.
- `taut/client/_models.py` owns `SearchHit`.
- `taut/commands/_rendering.py` owns the CLI projection, including the external
  19-digit string `ts`. MCP must share the value semantics, not import terminal
  rendering.
- `extensions/taut_mcp/taut_mcp/_tools.py` owns the explicit fixed tool
  definitions, exact JSON Schemas, annotations, and structured result schemas.
- `extensions/taut_mcp/taut_mcp/_commands.py` owns the explicit domain-command
  allowlist, public-record projection, and one-operation dispatch.
- `extensions/taut_mcp/taut_mcp/_process_reactor.py` freezes validated tool
  arguments before crossing into the workspace child. Its current
  `CommandScalar` transport cannot carry selector arrays.
- `extensions/taut_mcp/taut_mcp/server.py` and the process reactor own framing,
  workspace admission, cancellation, and recovery. Search adds no new reactor
  lane or lifecycle.
- `extensions/taut_mcp/tests/test_tools.py` and
  `extensions/taut_mcp/tests/test_stdio_server.py` own manifest/schema and real
  MCP framing proof. `extensions/taut_mcp/tests/test_pg_conformance.py` owns
  PostgreSQL parity at the extension boundary.

Every named path exists at the baseline. Implementation must stop and amend
this plan if ownership has moved.

## Invariants and Constraints

1. **Core owns search semantics.** MCP validates and transports arguments, then
   calls `TautClient.search` exactly once. It does not tokenize, rank, filter,
   hydrate, rebuild, or retry on its own.
2. **Backend equality is API equality, not result equality.** SQLite FTS and
   PostgreSQL text search may differ in Unicode tokenization, ranking, and
   matching quality as [SRCH-11] permits. The MCP shape and visibility rules are
   identical.
3. **Cursor-neutral does not mean physically read-only.** Ordinary search does
   not move chat cursors, claim notifications, or touch member activity, but it
   may reconcile disposable index state. `reindex=true` explicitly rebuilds
   derived state. The manifest must not advertise `readOnlyHint=true`.
4. **No automatic tool reflection.** The manifest remains an explicit allowlist.
   Adding a future CLI verb does not add an MCP tool.
5. **IDs stay strings at JSON boundaries.** Search-hit `ts` is the canonical
   19-digit decimal string required by the SimpleBroker 7 compatibility
   boundary. No numeric compatibility alias is added.
6. **Lists become immutable before process transfer.** Validated JSON arrays are
   copied to tuples of strings in the parent. No mutable SDK-owned object crosses
   the reactor boundary.
7. **No new auth or identity mode.** The tool requires the same `workspace` and
   continuity `token` as every CLI-shaped MCP tool and uses the existing shared
   ensure lifecycle.
8. **No new wake or subscription semantics.** A search call creates no chat
   message and publishes no search-result-specific resource update. It retains
   the existing post-command observational notification refresh, which may
   publish an independently changed inbox snapshot.
9. **Errors remain content-free where required.** Search validation and provider
   errors use the existing typed MCP error envelope. They do not expose tokens,
   backend credentials, SQL, rejected participant content, or tracebacks.
10. **Real integration seams stay real.** Acceptance tests may not mock
    `TautClient.search`, the search provider, broker queues, sidecars, index
    reconciliation, hydration, MCP framing, or PostgreSQL. One focused
    error-path test may inject failure at the auxiliary search-invalidation
    enqueue boundary only after proving the source write committed through the
    real broker; that test owns warning priority and is not backend-conformance
    evidence.

## Spec Baseline

- [SRCH-1] currently defers an MCP search tool to a later MCP spec revision.
- [SRCH-5.2] already defines the complete Python query and `SearchHit` model.
- [SRCH-5.3] defines external JSON facets and canonical string timestamps.
- [MCP-5] fixes exactly 20 tools, 17 of them CLI-shaped, and omits search.
- [MCP-5] transports only scalar command arguments today.
- [MCP-6] has no `search_hit` record family.
- [MCP-12] freezes every manifest property and requires a firing case per tool.

Those statements are internally consistent at the baseline. Promotion is a
deliberate public-contract change, not documentation repair.

## Proposed Spec Delta

Promote this delta atomically before implementation. If review changes any
enumerable field below, update this plan before editing code.

### D1 — Search scope and public surfaces

In [SRCH-1], replace the MCP-search out-of-scope sentence with:

> The optional `taut-mcp` extension exposes the same operation as its explicit
> `search` tool under [MCP-5]. That adapter delegates one `TautClient.search`
> call and inherits this specification's query, visibility, hydration,
> reconciliation, result, and backend-quality contracts. It adds no search
> language, ranking rule, or retry.

Add [SRCH-5.4] **MCP surface**:

> MCP accepts the [SRCH-5.2] arguments as named fields. JSON arrays are copied
> to immutable string tuples before process transfer. A successful call returns
> zero or more `search_hit` records whose fields are exactly [SRCH-5.3]'s JSON
> fields. `ts` is a canonical 19-digit decimal string. Empty search is ordinary
> success with no records. Search is cursor-, notification-, and member-activity
> neutral, but it may reconcile disposable index state and `reindex=true`
> rebuilds that state.

### D2 — Fixed manifest and exact tool contract

Amend [MCP-5] from exactly 20 tools / 17 CLI-shaped tools to exactly 21 tools /
18 CLI-shaped tools everywhere those counts are normative. Add this exact row:

| Tool | Exact description | `readOnlyHint` | `destructiveHint` | `idempotentHint` | `openWorldHint` |
|------|-------------------|----------------|-------------------|------------------|-----------------|
| `search` | Search actor-visible Taut history without moving chat cursors, claiming notifications, or touching member activity. The call may reconcile disposable derived index state; `reindex=true` rebuilds it. Backend tokenization and ranking may differ. | false | false | true | true |

`idempotentHint=true` is intentional. Repeated calls converge the same
disposable projection for the then-current source state and do not compound an
authoritative effect. As with other read hints, concurrent source changes may
change the returned records.

Add these property rows or exact equivalents to [MCP-5]:

| Property | Contract |
|----------|----------|
| `query` | Required nonblank Unicode search query; core [SRCH-3] remains authoritative for normalization, length, and token rules. |
| `channels` | Optional array of channel names; default `[]`; each element uses the canonical channel pattern. |
| `direct_messages` | Optional array of `@name-or-alias` routes or stable `dm.d_*` handles; default `[]`; each element uses the exact chat-DM selector grammar needed by [SRCH-4.1]. |
| `all_direct_messages` | Optional boolean, default `false`; it may coexist with explicit DM selectors, whose union collapses by canonical thread under [SRCH-4.1]. |
| `from_member` | Optional member name or alias string, or null; default null. |
| `kinds` | Optional array whose unique elements are drawn from `message`, `notice`, `foreign`; default `[]`. |
| `before` | Optional canonical 19-digit decimal string, or null; default null. Numeric JSON values are invalid. |
| `limit` | Optional integer from 1 through 1,000; default 50. |
| `reindex` | Optional boolean, default `false`. |

The tool row is:

> `search` requires `workspace`, `token`, and `query`; lazily ensures the
> workspace; freezes every selector array to a tuple; and calls
> `TautClient.search(query, channels=..., direct_messages=...,
> all_direct_messages=..., from_member=..., kinds=..., before=..., limit=...,
> reindex=...)` once. It adds no retry or post-filter.

The JSON Schema is a closed Draft 2020-12 object. It declares arrays directly
and enforces the enumerated kind values. It does not use `uniqueItems`, invent
selector-count caps, or reject duplicates: core accepts repeated values and
collapses them. It adds no cross-field exclusivity absent from [SRCH-4.1].

### D3 — Result family and error behavior

Add `search_hit` to [MCP-6]. The common envelope has
`record_type: "search_hit"`. Each object inside `records` has exactly the ten
[SRCH-5.3] fields:

```text
thread: string
ts: canonical 19-digit decimal string
from_id: string or null
from: string
kind: "message" | "notice" | "foreign"
text: string
thread_kind: "channel" | "subthread" | "dm"
channel: string or null
parent: channel name string or null
members: [string, string] or null
```

No record contains an inline `record_type`; that discriminator belongs only to
the [MCP-6] envelope, as for every sibling record family. `parent` is the
top-level channel name for a subthread, not a message ID.
`members` is present only for direct-message hits and preserves core ordering.
The output schema is a closed discriminated `oneOf`: channel hits require
`channel` plus null `parent`/`members`; subthread hits require string `channel`
and `parent` plus null `members`; DM hits require null `channel`/`parent` and an
exact two-string `members` array.
The common MCP success envelope uses `record_type: "search_hit"`, `records: []`,
and `guidance: []` for no matches. A provider failure is an ordinary sanitized
tool error, not an empty result. Because the core provider boundary
intentionally surfaces backend-native non-domain exceptions, the MCP command
adapter re-raises existing `TautError`, `TypeError`, `ValueError`,
`EmptyResultError`, and `TokenError` unchanged, but converts any other
exception raised by its single `TautClient.search` call to the exact
content-free `TautError` message `search provider or index unavailable; fix
the workspace search provider or index and retry`. This search-only mapping
does not weaken the existing unexpected-exception reactor-fault rule for any
other command. A re-raised `EmptyResultError` flows through the existing MCP
empty-result handler to the ordinary empty `search_hit` success envelope; it
does not become a tool error.

### D4 — Verification and ownership

Amend [MCP-9] to teach default and explicit scope, backend-native lexical
differences, exact string-ID reuse, and the potentially expensive `reindex`
path. Amend [MCP-10] so search consumes one ordinary tool-bucket charge, with no
weighted class. Amend [MCP-12] to require 21 discovery entries, 18 CLI-shaped
schemas, one real firing case for `search`, immutable list transfer, empty-
result shape, no cursor/activity/inbox change, `reindex` effects, exact
19-digit `ts`, exact facet discrimination, malformed rejection before dispatch,
and real SQLite plus PostgreSQL proof. Amend [SRCH-12] to name the MCP adapter
conformance.

Amend [MCP-6]'s warning rule so the child clears and returns both notification
and search warnings for every domain call in deterministic notification-then-
search order, with no cross-call leakage. A search warning may accompany an
otherwise empty success.

No product-section-registry row changes ownership. The existing MCP and Search
rows remain canonical; run the two-way promise audit and update their cited
section lists only if [SRCH-5.4] or another new code must be named explicitly.

## Promotion Strategy

Use strategy A: edit active specs in place. This is an additive, reviewed
change to two already-canonical families; no draft spec or registry state is
needed. Land D1–D4 and the plan revision from independent review before runtime
implementation. The spec-promotion commit must contain no production code.

## Dependency-Ordered Tasks

### S0 — Baseline and contract promotion

1. Reconfirm HEAD, clean/dirty state, package floors, and all paths above.
2. Run existing focused MCP and search tests to establish the baseline.
3. Apply D1–D4, the README/MCP README restatement, and any product-section
   registry citation-only alignment.
4. Run docs references, CLI claims, spec-link, and plan-index gates.

Done signal: the active specs define exactly one MCP search tool with no code
claiming it exists yet, and the promotion commit is independently reviewed.

### S1 — RED manifest, schema, and transport tests

Write failing tests that require:

- exact 21-name discovery on both protocol eras;
- the exact description, annotations, property descriptions, defaults,
  patterns, bounds, enum, required list, and `additionalProperties: false`;
- list values frozen to tuples before process transfer;
- malformed IDs/selectors, non-string array elements, unknown fields, empty
  query, and out-of-range limit rejected before domain dispatch, while
  duplicate selectors/kinds and combined all-DM/explicit-DM scope are accepted;
- `search_hit` schema with string `ts`/`parent` and exact fields.

RED proof must fail for absence of the tool/transport/result, not for fixture or
import mistakes.

### S2 — Manifest and immutable command transport

1. Add the explicit tool/schema/result definitions in `_tools.py`.
2. Extend the command argument type to admit immutable string tuples only.
3. Freeze validated list inputs in the parent before enqueuing the command.
4. Clear and aggregate both client warning channels around each domain command
   in deterministic order.
5. Keep lifecycle, bucket charge, cancellation, and workspace admission paths
   unchanged.

Done signal: manifest/transport tests pass while the domain firing test remains
RED.

### S3 — One-operation domain adapter

1. Add `search` to `RECORD_TYPE_BY_TOOL`, the explicit command branch, and the
   public record union/projection.
2. Decode only the already-validated immutable values.
3. Call `TautClient.search` once and project each `SearchHit` with external
   message-ID formatting.
4. Return the ordinary empty typed result for no hits.

Done signal: real SQLite MCP calls match direct `TautClient.search` facets and
effects for the same query.

### S4 — Backend and process-boundary conformance

Add real stdio and real PostgreSQL cases covering search, filters, stable DM
scope, Unicode without asserting backend-identical ranking, empty results,
reindex, and no cursor/activity/inbox movement. Verify process cancellation
does not cause a retry.

Done signal: SQLite and PostgreSQL each satisfy the same API assertions while
backend-native result quality remains permitted to differ.

### S5 — Documentation and traceability closure

Update:

- `README.md` MCP/search restatements and tool counts;
- `extensions/taut_mcp/README.md` counts, tool notes, and examples;
- `extensions/taut_mcp/pyproject.toml` core floor, raised to the first released
  `taut-chat` version that contains `TautClient.search` and `SearchHit`;
- `docs/implementation/07-taut-mcp-architecture.md` transport/result mapping;
- `docs/implementation/09-search-architecture.md` adapter boundary;
- implementation mapping and Related Plans in specs;
- `CHANGELOG.md` under the current unreleased section.

Run the two-way promise audit for both registered concern families. Record any
runtime deviation in this plan and amend the active spec before proceeding.

## Testing Plan

Use red-green TDD per slice. Required firing matrix:

| Contract | SQLite | PostgreSQL | MCP stdio | Pure/schema |
|----------|--------|------------|-----------|-------------|
| discovery count/name/description/hints |  |  | both protocol eras | exact snapshot |
| every argument/default/filter | real index | real native index | representative full call | every invalid branch |
| stable and routed DM visibility | real two-member DM | real two-member DM | yes | malformed/inaccessible |
| external `ts` and `parent` strings | yes | yes | yes | exact schema |
| empty typed result | yes | yes | yes | exact envelope |
| cursor/activity/inbox neutrality | inspect real sidecar/queues | inspect real sidecar/queues | yes |  |
| reconciliation and `reindex` | real disposable index | real disposable index | one end-to-end call | annotations frozen |
| cancellation/transport failure |  |  | no automatic retry | reactor unit seam |

The warning matrix also fires one mutating tool such as `say` whose successful
source write produces a best-effort search-enqueue warning, proves that MCP
returns it, then proves a following `read`, `log`, or `who` does not inherit it.
The only permitted fault injection replaces that auxiliary enqueue attempt
after a real source commit. It must not replace the source queue, search call,
provider, hydration, sidecar, reactor, or MCP framing, and all acceptance rows
above retain real storage.

Do not compare SQLite and PostgreSQL hit order or Unicode match sets except for
an ASCII floor that both specifications require.

## Verification and Gates

Focused commands are confirmed during implementation from current project
scripts, then recorded with observed results. Expected gates include:

```bash
uv run --project extensions/taut_mcp --extra dev \
  --with-editable ./extensions/taut_pg pytest \
  extensions/taut_mcp/tests/test_tools.py \
  extensions/taut_mcp/tests/test_process_reactor.py \
  extensions/taut_mcp/tests/test_stdio_server.py -n 0
uv run ./bin/pytest-pg extensions/taut_mcp/tests/test_pg_conformance.py \
  -n 1 --dist loadgroup
uv run pytest tests/test_search.py tests/test_search_cli.py -n 0
uv run ruff check .
uv run ruff format --check .
uv run --extra dev mypy taut tests bin/release.py \
  extensions/taut_pg/taut_pg extensions/taut_pg/tests \
  --config-file pyproject.toml
uv run --project extensions/taut_mcp --extra dev mypy \
  extensions/taut_mcp/taut_mcp extensions/taut_mcp/tests \
  --config-file extensions/taut_mcp/pyproject.toml
uv run pytest -n auto
bin/check-plan-status-index
```

Also run the adversarial parser floor against the new schema: omitted versus
null, empty arrays, wrong scalar/array types, duplicate and unknown keys,
boundary IDs, limit 0/1/1000/1001, malformed UTF-8 framing where applicable,
and broken-pipe/no-traceback behavior through stdio.

## Rollout, Rollback, and Success Signals

This is an additive MCP discovery change with no durable migration. Publish the
compatible core release before the MCP release and raise the MCP dependency
floor; do not duck-type around an older core. Old clients ignore the new tool.
New clients must feature-detect `search`; they must not
assume it against older servers. Rollback removes the tool and restores the
20/17 counts; it does not require data repair because search index state is
already disposable core-owned state. A client that has begun depending on the
tool will receive ordinary unknown-tool failure after rollback.

Post-release signals:

- discovery reports exactly 21 tools on both supported protocol eras;
- an ASCII query returns the expected visible record on SQLite and PostgreSQL;
- repeated search leaves cursors, inbox claims, and activity unchanged;
- provider errors are sanitized and are not reported as empty success;
- notification/search warnings are returned in fixed order and do not leak;
- no increase in reactor restarts, stuck workspace slots, or automatic retries.

## Independent Review Loop

Before spec promotion, run a read-only independent Opus review over this whole
plan plus [MCP-5]–[MCP-12], [SRCH-3]–[SRCH-12], the MCP architecture, and the
named implementation surfaces. Ask for `PASS` or `BLOCKED` with P1/P2 findings,
and specifically challenge schema exactness, annotation truthfulness, mutable
cross-process values, JSON ID boundaries, backend parity claims, and missing
firing tests. Record every finding and disposition below. Repeat after material
revision. Larger implementation slices receive a separate review after S3 and
again before completion.

## Out of Scope

- semantic/vector search, snippets, highlighting, facets beyond `SearchHit`,
  saved searches, pagination tokens, subscriptions, and search-result wakeups;
- automatic reflection of CLI or extension verbs;
- backend-identical ranking/tokenization;
- a new MCP resource, prompt, identity mode, or server lifecycle;
- changes to core search storage, job queues, or provider algorithms except a
  defect independently proven while implementing this adapter.

## Deviation Log

- The MCP dependency floor was already `taut-chat>=0.8.2`, the first current
  release containing `TautClient.search` and `SearchHit`; no metadata edit was
  needed.
- `bin/pytest-pg` did not classify explicit `extensions/taut_mcp/tests` paths
  and therefore omitted the MCP dependency overlay. The runner now routes MCP
  tests through its `pg_only` extension lane and installs both extension
  overlays. Routing and command construction have firing tests.
- The authoring-time shorthand `uv run mypy` has no target in this repository.
  The gate above now records the two canonical root and MCP invocations from
  the repository README.
- The fixed search-provider error boundary requires one intentional `BLE001`
  suppression because provider implementations do not share an enumerable
  exception vocabulary. [RUFF-SUP-083] now owns its exact one-directive
  cardinality, no-detail invariant, real proof, and rejected alternatives.

No public field, annotation, count, error class, or backend promise deviated
from the promoted specification.

## Review Record

| Date | Reviewer | Verdict/finding | Disposition |
|------|----------|-----------------|-------------|
| 2026-08-10 | Claude Opus, focused read-only plan review | **BLOCKED**, P2: D3 listed `record_type` as both an envelope discriminator and an inline field, contradicting [SRCH-5.3], [MCP-6], and every existing record serializer. Advisory: fire a mutating-tool search-warning/no-leakage case. | Accepted. D3 now fixes `record_type` at the envelope only and makes each record exactly the ten [SRCH-5.3] fields. The warning matrix now fires `say` followed by a nonmutating command. Focused closure review pending. |
| 2026-08-10 | Claude Opus, focused closure review | **PASS**, no unresolved P1/P2. Verified envelope-only `record_type`, the exact ten-field hit record, facet discrimination, and the warning/no-leakage firing case. | Closed. The plan is ready for spec promotion; implementation review gates remain. |
| 2026-08-10 | Implementation preflight | Core search provider/index failures intentionally include backend-native exceptions outside `TautError`; the existing MCP child would classify them as terminal reactor faults. The no-resource-update wording also overclaimed against the existing post-command inbox refresh. | D3 now defines one exact search-only sanitized translation while preserving domain/identity exceptions; invariant 8 now forbids only search-result-specific wakes and retains ordinary observational refresh. Independent promotion-diff review required before runtime work. |
| 2026-08-10 | Test-seam preflight | The plan required a deterministic successful-source/search-enqueue-warning case while banning every queue fault injection. The shared target has no supported way to fail only the auxiliary enqueue without destabilizing the authoritative source write. | Invariant 10 and the warning matrix now permit one narrowly scoped auxiliary enqueue fault after a real source commit. It is warning-priority proof only, never backend or acceptance evidence; all core search and storage seams remain real elsewhere. |
| 2026-08-10 | Claude Opus, promotion-diff review attempt 1 | **NO VERDICT**. The bounded CLI process ended after producing output too large for the review harness to retain; the session could not be resumed. | Treat as failed review evidence. No approval inferred. Retry with the same baseline, a narrower prompt, and a strict response limit. |
| 2026-08-10 | Claude Opus, promotion-diff review attempt 2 | **PASS**, no P1. P2: the shared `limit` teaching row omitted `search=50`; the unchanged `EmptyResultError` rule could be misread as a tool error despite the empty-success contract. | Accepted both. [MCP-5] now teaches the search default in the shared property row. [MCP-6] and D3 now state that the existing empty-result handler returns an empty `search_hit` success envelope. Runtime work may begin after recording the promotion baseline. |
| 2026-08-10 | Claude Opus, implementation review after the first complete runtime slice | **BLOCKED**, P1: `test_channel_tools.py` retained a 20-tool assertion. P2: optional search defaults were covered only indirectly, not at the command call boundary. | Accepted both. The off-topic count assertion was removed from the naming test; a CLI-capability/MCP parity test plus the central manifest and both era-discovery tests own completeness. A direct spy test now fires the exact eight omitted defaults while proving one call. Focused closure review pending. |
| 2026-08-10 | Claude Opus, focused implementation closure review | **PASS**, no unresolved P1/P2. Confirmed the structural CLI-capability partition and nested-operation discovery map one-to-one onto all 18 CLI-shaped tools; both protocol eras independently pin all 21 tools. Confirmed one search call receives all eight exact omitted defaults. | Closed. The stronger parity proof replaces the rejected global count assertion. Documentation closure and final broad verification remain. |
| 2026-08-10 | Claude Opus, final fresh-eyes implementation review | **PASS**, no unresolved P1/P2. Independently verified the one-call boundary, string IDs, immutable tuple transport, exact ten-field projection and three facets, provider-error classification, warning order, real SQLite/stdio/PostgreSQL proof, cancellation, and the production-derived CLI/MCP bijection. | Closed. Reviewer reported no blocking contract or correctness defect; the owner-authorized targeted close-out commit satisfies the remaining history gate. |

## Verification Evidence

- `uv run ruff check .`: passed.
- `uv run ruff format --check` on every changed Python file: passed. The
  repository-wide formatter check still reports three unchanged historical
  plan files that were already outside this change.
- Canonical root and MCP `mypy` commands: passed, covering 134 and 18 source
  files respectively.
- Full non-PostgreSQL MCP suite with the PostgreSQL overlay: passed.
- Real PostgreSQL MCP conformance through `bin/pytest-pg`: all seven tests
  passed against a disposable PostgreSQL 18 container.
- Core search, search-client, search-CLI, and PostgreSQL runner tests: passed.
- Ruff suppression-index write/check and every policy test owned by this
  change: passed. The new structural parity/default tests also pass under Ruff
  and mypy.
- Documentation paths, CLI claims, plan index, and `git diff --check`: passed.
- The broad root suite completed with three failures unrelated to this diff:
  two README install-command assertions whose required strings are absent from
  `HEAD:README.md`, and a root-`uv.lock` absence assertion even though
  `HEAD:uv.lock` exists. No owned failure remains.
- The plan, implementation, and verification evidence are included in the
  owner-authorized targeted close-out commit. Unrelated worktree plans and
  their index rows remain outside that commit.

Promotion baseline: repository `HEAD`
`50a67eb9e5412e330475608f3d515b4096a0c994` plus the reviewed uncommitted
`docs/specs/05-taut-mcp.md` and `docs/specs/06-search.md` diff with SHA-256
`88e9de545c488e1a1f363449a561f69461ecdadfbdf8c63fbc2d28bace6d3710`.
The focused documentation-reference, CLI-claim, and plan-index tests passed on
this baseline.

## Fresh-Eyes Review

Before declaring implementation complete, a reviewer who did not author the
last slice must verify from scratch that: the MCP tool is discoverable and
useful without CLI knowledge; descriptions teach all state effects; one core
call owns semantics; all JSON IDs survive a JavaScript-number-sensitive path;
both real backends fire; no mutable arrays cross the process boundary; empty,
invalid, inaccessible, provider-failure, cancellation, and reindex cases are
distinct; docs and counts agree; and git history contains the reviewed spec,
implementation, and verification evidence.
