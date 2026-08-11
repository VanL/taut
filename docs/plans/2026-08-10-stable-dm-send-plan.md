# Stable Direct-Message Send Plan

Date: 2026-08-10

Status: active after independent plan review

Class: 5 — expands the public `say` address contract across Python, CLI, JSON,
and MCP. It changes no durable schema or queue format.

Plan type: implementation with spec revision

Baseline: `50a67eb9e541` (`Adopt SimpleBroker 7 JSON message ID boundaries`).

## Goal

Allow a valid actor-accessible stable direct-message handle (`dm.d_*`) to be a
`say` target for that existing conversation. Keep `say @name TEXT` as the only
direct-message creation route. A stable handle must never create or heal a
member, route, claim, thread registration, membership, notification queue, or
conversation. This makes opaque handles returned by Taut directly reusable by
humans and agents without changing their meaning after member rename or route
reassignment.

## Source Documents

- `README.md`, especially Direct Messages, Addressing, CLI, and MCP claims
- `docs/program-theory.md` (THEORY-2, THEORY-3, THEORY-4, THEORY-6)
- `docs/specs/product-section-registry.md` (CLI, Direct messages, MCP rows)
- `docs/specs/02-taut-core.md` [TAUT-4], [TAUT-6.1], [TAUT-6.5], [TAUT-7.1],
  [TAUT-7.8], [TAUT-8.1]–[TAUT-8.3], [TAUT-9], [TAUT-10], [TAUT-11]
- `docs/specs/03-identity-addressing-notifications.md` [IAN-3]–[IAN-7],
  [IAN-9]
- `docs/specs/05-taut-mcp.md` [MCP-5], [MCP-6], [MCP-9]–[MCP-12]
- `docs/implementation/04-taut-architecture.md`
- `docs/implementation/07-taut-mcp-architecture.md`
- `docs/plans/2026-07-28-direct-message-navigation-plan.md` (historical
  rationale; not an active contract)
- `docs/agent-context/runbooks/writing-plans.md`
- `docs/agent-context/runbooks/hardening-plans.md`
- `docs/agent-context/runbooks/testing-patterns.md`
- `docs/agent-context/runbooks/adversarial-acceptance-probes.md`

## Current Structure and Key Files

- `taut/addressing.py` has two intentionally different parsers:
  `parse_target` accepts channel/subthread/`@route` for writes, while
  `parse_dm_selector` accepts both `@route` and stable handles for existing-DM
  navigation. The change must make this distinction explicit rather than let a
  dotted stable handle fall accidentally into subthread parsing.
- `taut/client/_messaging.py:TautClient.say` owns blank filtering, rename guard,
  target dispatch, and message publication. Its `_say_dm` route path may create
  the deterministic DM and memberships. `_say_chat_thread` writes only to an
  existing registered membership, but it also has subthread-specific implicit
  membership behavior. Stable DM send should use a dedicated existing-DM helper
  taking the already validated context rather than either general writer.
- `taut/client/_base.py:_resolve_direct_message` and
  `_direct_message_context_for_state` own content-free existing-DM validation:
  registered DM kind, exact deterministic participant pair/name, actor
  participation, both current member rows, and both memberships.
- `taut/state/_sql.py` remains the sole production sidecar SQL owner. This
  feature should need no new SQL.
- `taut/commands/say.py`, `taut/commands/_builtins.py`, and rendering own the CLI
  adapter and JSON receipt.
- The existing MCP `say` tool delegates core behavior. It needs description and
  schema-teaching alignment, not a second tool.
- `tests/test_direct_messages.py`, `tests/test_shared_contract.py`,
  `tests/test_cli.py`, `tests/test_command_registry.py`, and MCP SQLite/PG suites
  are the primary proof homes.

Every named path exists at the baseline. Stop and revise this plan if the
resolver or write ownership changes before implementation.

## Comprehension Gate

Before editing the spec or runtime, answer both questions from the current
tree. A wrong answer blocks implementation until the named owners are reread.

1. Which path may create or repair a DM registry row or participant
   membership? Expected answer: only the person-addressed `_say_dm` path after
   `say @route`; stable-handle selection must use `_resolve_direct_message`
   and a dedicated writer over its validated `_DirectMessageContext`.
2. What may a failed well-formed stable send change? Expected answer: no DM,
   identity, claim, route, registry, membership, queue, cursor, notification,
   or message state; ordinary noncreating/nonhealing resolution may update the
   already existing actor's activity timestamp.

Execution answers (2026-08-11): both answers above match the current
`taut/client/_messaging.py`, `taut/client/_base.py`, and
`taut/client/_identity.py` ownership paths. Runtime work remains blocked until
the D1–D4 spec-promotion slice is committed.

## Invariants and Constraints

1. **Handles identify conversations, not people.** `dm.d_*` always selects the
   exact deterministic pair encoded by registered state. It never follows a
   display name, alias, route, or later reassignment.
2. **Creation remains person-addressed.** Only `say @name TEXT` may create a
   direct-message thread and its two memberships or emit `dm_started`.
3. **Stable send is existing-only.** Before source publication, the same full
   structural and actor-access validation used by stable `read`/`log` must
   succeed. There is no partial or best-effort repair.
4. **No DM creation on a miss.** A well-formed absent, dangling, wrong-kind,
   malformed-state, deterministic-name-mismatch, missing-member,
   missing-membership, or nonparticipant handle creates no member, alias,
   claim, route, thread, queue, membership, cursor, notification queue, or
   message. Resolving an already existing actor for this attempted write may
   update that actor's ordinary activity timestamp, matching other `say`
   attempts; it must use `create=False` and `_heal_claim=False`.
5. **Errors do not become an oracle.** Invalid grammar is an ordinary validation
   error. Every well-formed inaccessible or structurally invalid stable handle
   returns the same content-free not-found class with no participant, route, or
   existence detail.
6. **Successful writes retain ordinary effects.** Once validated, the source
   message, sender cursor, member activity, unread state, and ordinary mention
   notification behavior follow the existing message path. No `dm_started`
   pointer is emitted for an existing stable conversation.
7. **No outside-DM audience.** Mention scanning may notify only the other valid
   participant under the existing DM audience rule. A named third party in the
   text receives nothing.
8. **Blank remains a universal no-op.** Existing blank/Cf-only filtering runs
   before target parsing, identity resolution, guards, or state access.
9. **No false concurrency guarantee.** Validation and publication use existing
   backend transaction/order boundaries. Taut does not lock out direct storage
   peers or promise that a concurrent root-level mutation cannot race between
   observations.
10. **No new stable handle issuance.** Handles continue to come from current DM
    list/read/log/message results. This change only accepts a returned handle at
    one more existing public input.
11. **Real seams stay real.** Acceptance tests may not mock target parsing,
    identity selection, deterministic DM validation, broker publication,
    sidecar membership state, notification delivery, CLI dispatch, MCP dispatch,
    or PostgreSQL.

## Spec Baseline

- Promotion baseline: `e22109ae26e4b899a46d9538115cefe2309b389e`
  (`Promote stable direct-message send contract`). Runtime implementation must
  preserve this reviewed D1–D4 boundary.
- [IAN-5.1] classifies `dm.d_*` as a stable existing-DM selector but explicitly
  excludes it from `say`.
- [IAN-5.3] defines the full actor-accessible stable-DM validation and uniform
  miss behavior. Navigation never creates or heals.
- [TAUT-7.8] applies the existing-DM resolver to read/log navigation.
- [TAUT-8.1] documents `say TARGET TEXT` as channel/subthread/`@route`.
- [MCP-5] teaches `say.target` as channel/subthread/`@name` only.
- The product-section registry records a README-owned promise that `say @name`
  is the sole DM creator. This feature preserves and should promote that exact
  promise rather than erase it.

## Proposed Spec Delta

Promote D1–D4 together before runtime code.

### D1 — Address classes and creation boundary

Replace the `say` exclusion in [IAN-5.1] with:

> `say` accepts either a person-addressed `@name-or-alias` route or an exact
> stable `dm.d_*` handle. The forms are intentionally asymmetric. `@route`
> selects a person at invocation time and remains the sole operation that may
> create a deterministic DM and its memberships. A stable handle selects only
> an already registered, fully valid, actor-accessible conversation under
> [IAN-5.3]; it never creates, adopts, redirects, or heals DM or identity state.

Move the README-owned “`say @name` is the sole DM creator” promise into this
canonical section and remove it from the registry's README-owned exception
list in the same promotion.

### D2 — Existing-DM validation and effects

Add to [IAN-5.3]:

> Stable-handle send uses the same complete validation as stable-handle
> navigation before publishing its source message. A well-formed absent,
> inaccessible, or structurally invalid handle returns the same content-free
> not-found result and performs no identity, claim, route, registry,
> membership, queue, cursor, notification, or message creation or repair.
> Noncreating, nonhealing actor resolution may update the already existing
> actor's ordinary activity timestamp, as for other attempted sends. On a
> valid conversation, publication follows the ordinary existing-thread write
> contract: it updates the sender's ordinary activity/cursor state and may emit
> ordinary mention pointers only to the other participant. It never emits
> `dm_started`.

Clarify that this is an operation-level precondition, not a storage-exclusion
or quiescence guarantee against direct backend writers.

### D3 — Python and CLI surface

Amend [TAUT-8.1]'s `say` row and [TAUT-8.3]'s Python mapping to retain every
existing [IAN-5.1] channel/subthread form, including `#channel`, and add exact
`dm.d_<26-lowercase-base32-chars>` beside `@name-or-alias`.

The exact behavior text is:

> `@route` may create the deterministic conversation. `dm.d_*` requires an
> existing fully valid actor-accessible conversation and never creates or heals
> one. For a nonblank attempt, malformed syntax exits 1. A well-formed
> inaccessible or invalid existing handle exits 2 without content. A successful
> send exits 0 and returns the stable DM thread plus the canonical string
> message ID in JSON; the Python `Message.ts` remains an integer.

Do not change the blank-message rule or human output. Do not add a flag.

### D4 — MCP teaching and verification

Amend [MCP-5]'s `say` description and target property to state:

> Post a new Taut message to a channel, sub-thread, person-addressed direct
> message, or an existing direct-message conversation. `@name-or-alias` may
> create a DM; exact `dm.d_*` requires an existing actor-accessible conversation
> and never creates or heals one.

The MCP schema must accept the existing `say` channel/subthread grammar,
`@route`, and exact stable-handle grammar without narrowing any current quoted
or core-validated channel form. If one regular expression cannot represent the
complete current core grammar truthfully, use `oneOf` branches or retain a
shape-only string schema and let core own semantic parsing. Do not reuse
`CHAT_OR_DM_PATTERN` blindly if it rejects a currently accepted `say` input.
Apply the teaching text consistently to [MCP-5]'s tool row, shared target-
property row, tool input row, `_tools.py` tool description, and `_tools.py`
target description; exact manifest snapshots must cover all five sites.

Amend [IAN-9] with the failure/effect cases and amend [IAN-10], [TAUT-11], and
[MCP-12] to require the creation/miss/effect matrix on real SQLite and
PostgreSQL, plus CLI and MCP firing cases.

The existing product-section rows retain ownership. Only the README-owned
exception list changes because D1 absorbs the promise.

## Promotion Strategy

Use strategy A: amend active specs 02, 03, and 05 plus the registry exception
list in one reviewed spec-promotion commit. The contract is additive at the
input boundary but changes security- and persistence-relevant negative
behavior, so code must not precede the reviewed spec.

## Dependency-Ordered Tasks

### S0 — Baseline and spec promotion

1. Reconfirm current `say`, parsers, resolver, writer, notification audience,
   MCP schema, and backend shared-test wiring.
2. Run current DM, CLI, and MCP focused tests.
3. Promote D1–D4, update README restatements, and run the two-way promise audit.
4. Commit the independently reviewed spec change before implementation.

### S1 — RED domain matrix

Add failing real-SQLite tests for:

- a valid stable-handle send returning the same thread and appending one source
  message;
- rename and alias reassignment not retargeting the stable handle;
- `@route` still creating first contact and emitting exactly one `dm_started`;
- stable send never emitting `dm_started`;
- malformed grammar versus well-formed missing/inaccessible exit classes;
- wrong kind, bad participant count/id/name, actor absent, other member absent,
  either membership absent, and nonparticipant actor;
- exact before/after state proof that every miss creates or heals nothing;
- the only permitted miss-side difference is an existing actor activity update;
- ordinary sender activity/cursor/unread effects and DM mention audience;
- blank stable-target input performing no state access.

RED must fail because `say` rejects the stable handle, while all unchanged
`@route` controls remain green.

### S2 — Parser and core dispatch

1. Add an explicit stable-DM write target class or branch. Do not infer it as a
   subthread and do not weaken channel/subthread validation.
2. In `TautClient.say`, preserve blank filtering and rename guard order.
3. For the stable branch, resolve the actor with `create=False` and
   `_heal_claim=False`, then call the existing full direct-message resolver.
4. Add a narrow existing-DM writer that accepts the validated
   `_DirectMessageContext`, writes through `_write_message`, and advances the
   sender from the context's prior cursor. It must not call `_say_dm` or the
   implicit-subthread membership path.
5. Keep `_say_dm` as the only route that may create the pair or `dm_started`.
6. Add no new SQL or persistent flags.

Done signal: the entire domain matrix passes on SQLite and unchanged DM tests
prove person-addressed creation still works.

### S3 — CLI and JSON acceptance

Add subprocess/registry tests for the exact grammar, `--` handling, blank stdin,
quiet/human/JSON modes, canonical string `ts`, stable `thread`, content-free
exit 2, validation exit 1, no traceback, and broken-pipe behavior. Do not add a
new command or global option.

### S4 — MCP and PostgreSQL conformance

1. Update exact MCP description/schema snapshots.
2. Fire valid and inaccessible stable sends through real MCP dispatch.
3. Run the shared contract and extension PG harness against a real PostgreSQL
   workspace, inspecting state after each negative case.
4. Prove both backends restrict mention notifications to the other participant
   and never emit `dm_started` for stable send.

### S5 — Documentation and closure

Update README examples, MCP README/tool notes, core and MCP implementation
architecture, implementation mappings, Related Plans, and `CHANGELOG.md`.
Raise `extensions/taut_mcp/pyproject.toml`'s core floor to the first released
`taut-chat` version with this behavior; do not promise stable send while
permitting installation with a core that rejects it.
Record any implementation deviation in this plan and amend active specs before
continuing. Run final docs/reference/claim gates and independent review.

## Testing Plan

The minimum enumerable matrix is:

| Target/state | Expected result | State effect |
|--------------|-----------------|--------------|
| malformed stable grammar | exit/error 1 | none before actor resolution |
| well-formed absent handle | content-free exit/empty 2 | no creation/repair; existing actor activity may update |
| registered wrong kind | content-free 2 | no creation/repair; existing actor activity may update |
| invalid participant set/name | content-free 2 | no creation/repair; existing actor activity may update |
| actor not participant | content-free 2 | no creation/repair; existing actor activity may update |
| either member row absent | content-free 2 | no creation/repair; existing actor activity may update |
| either membership absent | content-free 2 | no creation/repair; existing actor activity may update |
| valid existing pair | success | one ordinary source write; normal sender effects |
| valid existing pair with mention of peer | success | peer may receive ordinary mention |
| valid existing pair with mention of third party | success | third party receives nothing |
| first-contact `@route` | success | existing creation + one `dm_started` contract |
| blank text for any target | silent empty-result exit 2 | no state access |

Run each structural case through the public Python API on SQLite and
PostgreSQL using the shared backend contract suite. Keep backend-specific
SQLite proofs for branch ordering, identity non-healing, and durable
before/after snapshots where their instrumentation requires it. Fire grammar
and receipts through CLI and MCP. Avoid mocking durable state or publication.

## Verification and Gates

Expected commands, reconfirmed at implementation time:

```bash
uv run pytest tests/test_direct_messages.py tests/test_shared_contract.py \
  tests/test_cli.py tests/test_command_registry.py -n 0
uv run --project extensions/taut_mcp --extra dev pytest \
  extensions/taut_mcp/tests/test_tools.py \
  extensions/taut_mcp/tests/test_stdio_server.py -n 0
uv run ./bin/pytest-pg tests/test_shared_contract.py \
  extensions/taut_mcp/tests/test_pg_conformance.py -n 1 --dist loadgroup
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest -n auto
bin/check-plan-status-index
uv run bin/check-cli-claims
uv run pytest tests/test_docs_references.py tests/test_cli_claims.py -n 0
```

Apply adversarial CLI probes to empty input, stdin, `--`, malformed Unicode,
unknown options, missing workspace, read-only storage, interruption, and broken
pipe. Inspect real rows/queues before and after negative cases rather than
asserting only the returned error.

## Rollout, Rollback, and Success Signals

This is an additive accepted target with no migration. Existing scripts keep
their behavior. New scripts should feature-detect the installed Taut version
before feeding a returned stable handle to `say`. Before publication, rollback
is a direct code/spec revert. After an immutable release, fix forward is
preferred; removing the accepted target would break agents that compose
`list --dms` or message results into `say`.

Publish the core release before the MCP release that teaches the new target.
Post-release signals:

- a stable handle returned by Taut can be sent to without name lookup;
- the message lands in that exact history on SQLite and PostgreSQL;
- member rename/alias reassignment does not redirect the handle;
- negative sends leave registry, membership, identity, broker, and notification
  state unchanged;
- first-contact creation volume and `dm_started` behavior remain confined to
  `@route`.

## Independent Review Loop

Before promotion, run a read-only Opus review over this plan, [IAN-5]–[IAN-7],
[TAUT-7.8], the `say` CLI/Python rows, [MCP-5]/[MCP-12], and the named resolver
and writer code. Require `PASS` or `BLOCKED` with P1/P2 findings. Ask the
reviewer to attack target ambiguity, creation/healing side effects, content
oracles, rename/reassignment behavior, notification audience, blank ordering,
MCP regex narrowing, and race overclaims. Repeat after material edits, after
the core slice, and before completion.

## Out of Scope

- creating a DM by stable handle; group DMs; third-party forwarding; public
  participant lookup from the opaque handle; handle aliases; handle revocation;
- making `@route` stable across rename/reassignment;
- new transactions, locks, process census, quiescence checks, or direct-storage
  conflict prevention;
- changing DM history/read/list semantics, notification durability, or MCP
  attachment identity;
- exposing the deterministic-handle derivation as a public addressing API.

## Counterargument and Decision

Person-addressed `@name` is the friendlier human send form and should remain the
documented default. The stable form is still valuable because Taut already
returns an opaque conversation address to agents, and a valid address that can
be read but not written is needlessly non-composable. The risk is accidental
orphan creation. The existing-only precondition removes that risk without
turning handles into person routes.

## Deviation Log

This plan intentionally reverses the 2026-07-28 navigation slice's rejection of
stable-handle `say`. That earlier choice was slice-local, not canonical theory.
The rationale is machine-output round-tripping and exact-conversation safety;
the existing-only precondition prevents the orphan-creation failure that
motivated the narrower slice. Any creation/healing on stable send, distinct
inaccessible error, changed mention audience, or widened handle meaning is a
blocking implementation deviation.

## Review Record

| Date | Reviewer | Verdict/findings | Disposition |
|------|----------|------------------|-------------|
| 2026-08-10 | Claude Opus, focused read-only plan review | **PASS**, no P1/P2. Ratified the asymmetric creator boundary, historical decision reversal, ordinary actor-activity update on misses, content-free errors, dedicated existing-DM writer, mention audience, MCP shape-only/`oneOf` schema choice, core-before-MCP release order, and real-backend proof. P3: blank matrix said success/no-op; enumerate repeated MCP teaching sites. | Applied both P3s: blank is now silent exit 2, and D4 names the five teaching/snapshot sites. Plan is ready for spec promotion; implementation review gates remain. |
| 2026-08-11 | Independent source/spec audit | **BLOCKED** on five promotion defects: D3 narrowed accepted `#channel` syntax, malformed-target wording ignored blank-first ordering, proof ownership omitted [IAN-9]/[IAN-10], a pattern could narrow MCP input, and Python ids were described as strings. | Corrected all five before review; also aligned the full structural matrix across both real backends and added maintained-example gates. |
| 2026-08-11 | Claude Opus, read-only promotion review | **PASS**. Two P2 follow-ups: make MCP's stable-only empty-message result explicit without changing `@route`, and require the blank stable-target proof in normative matrices. | Applied both before promotion: [MCP-5] now pins the exact scoped [MCP-6] envelope, and [IAN-10]/[TAUT-11] require blank-before-parse proof. |

## Fresh-Eyes Review

Before completion, an uninvolved reviewer must take a handle only from public
Taut output and demonstrate valid send, rename stability, content-free misses,
and absence of negative-case state creation on both real backends. They must
also confirm `@route` remains the sole creator, MCP and CLI teach the asymmetry,
all external IDs remain strings, docs and registry ownership agree, and the
reviewed work is present in git history.
