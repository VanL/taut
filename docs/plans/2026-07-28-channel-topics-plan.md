# Channel Topics and Command Rehome Plan

Date: 2026-07-28

Status: completed. Independent review approves the topic contract,
channel-command rehome, noun-first MCP normalization, reserved channel-meta
shape, and CLI-claim gate revision. The complete delta is promoted into all
four active specs. Core, CLI, documentation-claim, and MCP behavior are
implemented. Full SQLite, live PostgreSQL, installed-wheel, documentation,
quality, slice-review, and final fresh-eyes-review gates are green. The
owner-authorized targeted landing is recorded by the commit containing this
completed plan.

Plan type: implementation with coordinated core, CLI, Python, and MCP spec
revision.

Class: 5. This adds a reserved public CLI noun, rehomes channel rename beneath
that noun, normalizes related MCP names, adds two public Python methods, a
public value object, persistent channel metadata, and two MCP tools. It also
adds a registry-derived documentation command-claim gate. It changes CLI,
protocol, and development-verification contracts and therefore requires a
dated, hardened plan, spec-first sequencing, real-backend proof, and
independent review under [DOM-5], [DOM-10], [DOM-11], and [DOM-15].

Owner: the implementing engineer owns spec promotion, the single channel
metadata boundary, core and adapter changes, real-backend proof, implementation
documentation, and review evidence. The repository owner owns commit, version
selection, release, and publication.

## 1. Goal

Give each top-level channel one optional, compact topic that tells humans and
agents what the channel is for before they read its history.

The initial CLI surface is a reserved, extensible noun:

```text
taut channel show CHANNEL
taut channel topic CHANNEL TEXT
taut channel topic CHANNEL --clear
taut channel rename OLD NEW
```

`channel show` reads current channel metadata. `channel topic` sets or clears
the topic. `channel rename` is the existing channel-and-subthread rename
operation moved from the top-level `taut rename` route. Topics also appear on
top-level channel records returned by `list`, so orientation does not depend on
knowing a second command exists.

This slice adds no channel lifecycle. `taut channel close CHANNEL` and
`taut channel reopen CHANNEL` are possible future subcommands, but they are not
committed behavior and no closed/open state, write gate, archive filter,
retention rule, or migration is part of this plan.

## 2. Decided Contract

### 2.1 Scope and ownership

- Topics belong only to registered top-level rows whose `kind` is `channel`.
  Direct messages, one-level subthreads, notification queues, and system queues
  cannot have topics.
- `taut_threads` remains the authority for channel existence. The topic is
  stored in that row's existing `meta` JSON. No broker queue alias, chat row,
  new table, new column, or schema-version bump is introduced.
- A channel's `meta` object reserves the sibling keys `topic` and `closed`.
  Version 0.8.0 writes and interprets only `topic`; `closed` remains absent,
  has no defined value type or behavior, and is preserved if encountered.
- A present `topic` value is an object with exactly `text`, `updated_ts`, and
  `updated_by_id`. No topic means the `topic` key is absent. This makes topic
  one field in a small channel-metadata namespace rather than the de facto
  shape of the whole blob.
- Topic mutation replaces the one `topic` object while preserving `closed` and
  every other top-level metadata key. Clearing removes only `topic`. This is
  the compatibility seam for unrelated current metadata and a later channel
  lifecycle contract.
- A topic update or clear writes no chat notice and no notification. The topic
  is canonical state, not a synthetic history message. The stored author and
  timestamp provide freshness evidence without polluting conversation history.

### 2.2 Topic validation and exactness

- The Python mutation input is `str | None`; `None` means clear.
- A string topic is valid only when it is nonblank under [TAUT-6.5]'s existing
  Unicode blank predicate, contains neither carriage return nor line feed, and
  contains at most 500 Unicode code points as measured by Python `len()`.
- An accepted topic is stored exactly. Taut does not trim, normalize, fold, or
  otherwise rewrite it.
- An empty or blank string is invalid. Clearing is explicit through Python
  `None`, CLI `--clear`, or MCP JSON `null`.
- Invalid type, blank input, line breaks, and 501-or-more-code-point input fail
  before identity resolution, activity, membership, timestamp allocation, or
  metadata mutation.

### 2.3 Read and mutation authority

- `TautClient.get_channel(channel)` and `taut channel show CHANNEL` validate a
  top-level channel name, require an existing registered channel, and read only
  Taut sidecar state. They do not resolve an acting member, touch activity,
  inspect a broker queue, create membership, or change a cursor.
- `TautClient.set_channel_topic(channel, topic)` validates the topic first,
  then resolves one existing acting member without creating or healing
  identity. The member must have a current membership in that channel.
- Topic mutation and channel rename-marker creation share one per-channel
  serialization namespace, `taut:channel:<channel-name>`. SQLite's write
  transaction provides that serialization; PostgreSQL acquires a transaction
  advisory lock for the same key. Under that serialization boundary, mutation
  rechecks incomplete rename state, channel kind, membership, and current
  metadata before replacing or removing the `topic` object. It updates member
  activity only when the topic actually changes.
- A same-value set and clearing an already absent topic are successful no-ops:
  they preserve the existing audit fields and do not touch activity. A
  preliminary equal-value read may return before allocating a timestamp. When
  the value looked different before the transaction, core may allocate a
  broker timestamp that becomes unused because a concurrent writer committed
  the requested value first; no unused timestamp is stored and the
  authoritative transaction still returns the unchanged record.
- Concurrent distinct mutations are last-committed-write-wins. Each committed
  record is internally consistent: text, timestamp, and member id come from
  one operation. Concurrent changes to unrelated `meta` keys must not be lost.
- Every channel topic operation applies the existing incomplete-rename gate.
  Rename-marker creation acquires the same old-name serialization key. If
  topic mutation acquires it first, the committed metadata follows the row to
  the new name. If marker creation acquires it first, later old-name mutation
  observes the marker and fails without writing. An operation addressed to a
  name that no longer exists is an ordinary miss. Rename never clears or
  rewrites topic metadata.

### 2.4 Public values and rendering

Add this frozen, slotted public value object:

```python
@dataclass(frozen=True, slots=True)
class Channel:
    name: str
    topic: str | None
    topic_updated_ts: int | None
    topic_updated_by_id: str | None
    topic_updated_by_name: str | None
```

The two public methods are:

```python
TautClient.get_channel(channel: str) -> Channel
TautClient.set_channel_topic(channel: str, topic: str | None) -> Channel
```

`topic_updated_by_name` is the author's current display name when its member
row remains available, otherwise `None`. The stable member id remains the
authority.

Append `topic: str | None = None` to the existing public `Thread` value.
Top-level channel rows populate it. Other thread kinds retain `None`.

Successful `channel show` and `channel topic` JSON records contain exactly:

```json
{
  "channel": "dev",
  "topic": "Current implementation and review coordination",
  "topic_updated_ts": 1837025672140161024,
  "topic_updated_by_id": "m_example",
  "topic_updated_by_name": "Van"
}
```

All four topic fields are `null` when no topic exists. Human `channel show`
prints the channel and either its topic plus update attribution or `(none)`.
Human `list` prints one escaped, indented topic line below a top-level channel
that has a topic. `--quiet` suppresses success output.

Every top-level channel `Thread` record, including `list`, CLI
`channel rename`, and MCP `channel_rename` results, adds required `topic`,
whose value is a string or null. Non-channel thread and DM records omit it,
preserving their current shapes. Taut's human terminal escaping applies to
topic text and current author names; JSON and Python preserve exact topic text.

### 2.5 CLI grammar and failures

- `channel` is a statically registered core noun. Its adapter owns required
  nested `show`, `topic`, and `rename` subparsers, like the existing `message`
  noun.
- `channel topic CHANNEL TEXT` accepts one positional string. Shell quoting is
  required for spaces. Version 1 adds no stdin sentinel or implicit piped
  input.
- `channel topic CHANNEL --clear` is the only CLI clear form. Combining text
  and `--clear`, omitting both, missing the nested operation, extra arguments,
  or unknown options is a usage error and exits 1 before client construction.
- A literal `--` keeps following option-shaped topic text positional. Thus
  `taut channel topic dev -- --clear` sets the literal topic `--clear`.
- `channel rename OLD NEW` preserves the existing `rename_channel()` domain
  behavior, validation, output, exit classes, marker recovery, broker ordering,
  and topic-preservation contract. This is a CLI routing change, not a second
  rename implementation.
- The existing top-level rename parser and dispatch move intact into the
  `channel` adapter. After that move, `taut rename` is no longer registered.
  It is not an alias or deprecation path. Because Taut has not been released
  publicly, this plan adds no compatibility state or retired-name mechanism.
  The freed top-level name follows ordinary installed-command rules.
- Every incomplete-rename recovery diagnostic names
  `taut channel rename OLD NEW`; no user-facing recovery path points to the
  removed route.
- Success exits 0, including idempotent no-ops. Invalid topic or storage errors
  exit 1. Missing/wrong-kind channels, unresolved actors, and absent membership
  use the existing empty/not-found class and exit 2.
- Help must teach the one-line 500-code-point bound, explicit clear, membership
  requirement, observational show behavior, rename syntax and recovery role,
  and 0/1/2 exit classes.

### 2.6 MCP surface

Add two tools to the fixed manifest, increasing it from 18 to 20:

| Tool | Operation | Annotations |
|------|-----------|-------------|
| `channel_show` | Calls `get_channel`; no identity, activity, queue, or cursor effect | read-only true, destructive false, idempotent true, open-world true |
| `channel_topic` | Calls `set_channel_topic`; replaces or clears shared channel state | read-only false, destructive true, idempotent false, open-world true |

Both tools require `workspace` and `channel`. `channel_topic` also requires
`topic`, whose schema is string or null. The string branch has `maxLength: 500`
and `not: { "pattern": "[\\r\\n]" }`, which rejects CR or LF anywhere,
including at the end. Core remains authoritative for Unicode blank
classification and exact runtime type checks.

The exact descriptions are:

- `channel_show`: `Return current metadata for one registered top-level Taut
  channel. Reads only shared registry state and does not resolve identity,
  touch activity, inspect a broker queue, or move a cursor.`
- `channel_topic`: `Set or clear one registered top-level Taut channel's
  topic. Requires the attached member's current channel membership; a changed
  value replaces shared topic state and updates member activity, while an
  identical value is a no-op.`

Both return `record_type: "channel"` with the exact channel record above.
The existing `thread` output schema becomes a closed discriminated `oneOf`:
the `kind: "channel"` branch requires `topic` and forbids `members`; the
`kind: "dm"` branch requires `members` and forbids `topic`; and the
`kind: "subthread"` branch forbids both. Snapshot tests exercise both `list`
and `channel_rename`. Tool handlers call public `TautClient` methods and never
parse CLI output or reach into private state.

The workspace reactor's generic completion path normally refreshes the
notification snapshot after a command. `channel_show` is the narrow exception:
it carries the child-owned cached snapshot in its completion and performs no
post-command `peek_inbox()`. The master still installs that snapshot in the
ordinary completion order. Without this exception the MCP wrapper would
silently violate the tool's actor-free, sidecar-only contract.

The existing flat MCP `rename` tool is rehomed one-for-one as
`channel_rename`, keeping the manifest total at 20 and preserving its input,
output, annotation, dispatch, and domain semantics. The old MCP identifier is
not retained as an alias. The public Python method remains
`rename_channel()`.

The same noun-first rule normalizes the three existing message tool
identifiers one-for-one: `show_message` becomes `message_show`,
`delete_message` becomes `message_delete`, and `react_to_message` becomes
`message_react`. Their schemas, annotations, results, dispatch targets, and
domain behavior do not change. The former identifiers are omitted from
discovery and are not aliases.

MCP outcomes are exact:

- schema-invalid calls, including a missing required field, 501-code-point
  string, CR, or LF, fail protocol/schema validation before child dispatch;
- an in-schema blank/Cf-only topic reaches core validation and returns
  `isError: true`, one concise text content block, and no
  `structuredContent`;
- an absent or wrong-kind channel produces the successful empty result
  `{ "empty": true, "guidance": [], "record_type": "channel",
  "records": [], "warnings": [], "workspace": "<canonical>" }`;
- absent membership and recoverable corrupt-topic or backend/storage
  `TautError` failures return `isError: true`, one concise text content block,
  and no `structuredContent`;
- attachment identity loss returns the existing fixed
  `workspace identity lost; detach and reattach` error and changes that
  workspace status to `identity_lost`; and
- an unexpected non-Taut exception follows the existing terminal reactor-fault
  path, returning the fixed `workspace reactor failed; detach and reattach`
  result with no structured content.

Cancellation after `channel_topic` starts has an uncertain response but a
recoverable outcome. The caller uses `channel_show` before retrying. The MCP
layer adds no retry or optimistic concurrency token.

At the current baseline, core and MCP are both versioned `0.8.0`, MCP requires
`taut>=0.8.0`, and no `v0.8.0` or `taut_mcp/v0.8.0` tag exists. The coordinated
change may use that floor only if it lands before the first 0.8.0 tag. If a tag
appears first, implementation must stop and obtain the repository owner's next
coordinated version decision.

### 2.7 Possible future channel lifecycle

The reserved noun intentionally leaves room for possible future commands:

```text
taut channel close CHANNEL
taut channel reopen CHANNEL
```

That idea is future work, not part of the accepted topic contract. This plan
reserves only the sibling key name `closed`; 0.8.0 assigns it no type, default,
state transition, visibility, write, MCP, TUI, or rendering semantics and does
not write it. Topic code ignores and preserves it. A later feature must define
its authority, value shape, transitions, concurrency, visibility, write
rejection, rollback, MCP, TUI, and compatibility contracts.

### 2.8 Documentation command-claim gate

Add `bin/check-cli-claims` and `tests/test_cli_claims.py` as one grammar with
two entry points, following the existing `check-doc-paths` pattern. The pytest
module owns the claim syntax, maintained-source list, explicit exemption map,
and validator. The bin script imports those definitions rather than restating
them.

The recognized claims are shell-like `taut ...` invocations inside Markdown
inline code or fenced code blocks. The gate validates the top-level verb and,
when the selected core adapter owns required nested subparsers, the nested
operation. It does not pretend to validate every positional value or shell
construct. It accepts optional shell prompts, environment assignments,
pipelines, and dispatcher-owned root globals before locating `taut`.

Validation derives deterministic core command paths from
`CommandRegistry(entry_points=())` and side-effect-free adapter parser
configuration. It does not enumerate ambient installed entry points, construct
a client, resolve a project, or execute a command. Reserved first-party
compatibility verbs remain visible through the registry's existing static
contract.

The source set is exact: `README.md`, `AGENTS.md`, `CLAUDE.md`,
`docs/README.md`, `docs/coalescing.md`, `docs/plans/README.md`,
`extensions/*/README.md`, `docs/agent-context/*.md`,
`docs/agent-context/runbooks/*.md`, `skills/**/*.md`,
`docs/implementation/*.md`, and `docs/specs/*.md`. Explicit historical
exclusions are `CHANGELOG.md`, `docs/lessons.md`, and every individual
`docs/plans/*.md` except the maintained plan index. Intentionally future,
invalid-example, or external-extension claims require a source-scoped exact
exemption with a non-empty reason. An exemption fails once its command path
becomes current, so allowances cannot silently outlive the gap. The known
future `taut channel close` and `taut channel reopen` claims start in that map.

Failures name the source, line, extracted command path, and reason. Exit 0 means
all recognized claims resolve, exit 1 means stale or malformed claims, and
exit 2 means invocation or environment failure. The implementation slice wires
the pytest gate into the normal suite and adds `uv run bin/check-cli-claims` to
documentation and completion commands.

## 3. Source Documents

- `docs/specs/01-development-documentation-operating-model.md`
  [DOM-4]–[DOM-6], [DOM-10]–[DOM-12], [DOM-15]
- `docs/specs/02-taut-core.md`
  [TAUT-3.3], [TAUT-4], [TAUT-6.4], [TAUT-6.5], [TAUT-8],
  [TAUT-10]–[TAUT-12]
- `docs/specs/03-identity-addressing-notifications.md`
  [IAN-6], [IAN-8]
- `docs/specs/05-taut-mcp.md`
  [MCP-5], [MCP-6], [MCP-9]–[MCP-12]
- `docs/implementation/04-taut-architecture.md`
- `docs/implementation/06-command-extensions.md`
- `docs/implementation/07-taut-mcp-architecture.md`
- `docs/agent-context/runbooks/writing-plans.md`
- `docs/agent-context/runbooks/writing-specs.md`
- `docs/agent-context/runbooks/hardening-plans.md`
- `docs/agent-context/runbooks/testing-patterns.md`
- `docs/agent-context/runbooks/adversarial-acceptance-probes.md`
- `docs/agent-context/runbooks/maintaining-traceability.md`

## 4. Context and Key Files

Read before editing:

| File | Current owner or pattern to understand |
|------|----------------------------------------|
| `taut/client/_models.py` | Frozen public `Thread` and other domain values. |
| `taut/client/_threads.py` | Channel registry, membership, list projection, and rename gates. |
| `taut/state/__init__.py` | Backend-neutral state protocol crossed by the client. |
| `taut/state/_sql.py` | SQLite/Postgres-dialect sidecar transactions and JSON decoding. |
| `taut/commands/message.py` | Required nested-subparser pattern for a reserved noun. |
| `taut/commands/rename.py` | Existing adapter behavior to move intact into `channel.py`. |
| `taut/commands/_builtins.py` | Static command reservation and root-help order. |
| `taut/commands/_registry.py` | Deterministic core command inventory used by the new claim gate. |
| `taut/commands/_protocol.py` | Parser and global-option definitions used for nested-path introspection. |
| `taut/client/_base.py` | Incomplete-rename recovery text that must name the nested command. |
| `taut/commands/_rendering.py` | Human escaping and exact JSON record construction. |
| `extensions/taut_mcp/taut_mcp/_commands.py` | Public-client-only MCP dispatch and record encoding. |
| `extensions/taut_mcp/taut_mcp/_tools.py` | Closed tool schemas, record schemas, descriptions, and annotations. |
| `extensions/taut_mcp/taut_mcp/_workspace_reactor.py` | One-command-per-workspace ownership and cancellation boundary. |
| `tests/test_state_contract.py` | Real state, malformed metadata, and unknown-key preservation tests. |
| `tests/test_client.py` | Python behavior, membership, activity, rename, and concurrency tests. |
| `tests/test_cli.py`, `tests/test_command_registry.py`, `tests/test_cli_probes.py` | CLI contract, registry behavior, and hostile-input probes. |
| `tests/test_docs_references.py`, `bin/check-doc-paths` | Existing single-grammar/two-entry-point pattern for maintained documentation claims. |
| `tests/test_shared_contract.py` | Shared SQLite/Postgres state contract. |
| `extensions/taut_mcp/tests/test_tools.py` | Tool schema, dispatch, recovery, and reactor behavior. |
| `extensions/taut_mcp/tests/test_stdio_server.py` | Shipped stdio protocol and exact manifest discovery. |
| `extensions/taut_mcp/tests/test_pg_conformance.py` | Live PostgreSQL protocol conformance. |

Comprehension gate before implementation:

1. Why must metadata merge happen inside the same transaction that rechecks
   channel kind and membership, rather than by `get_thread()` followed by
   `upsert_thread()`?
2. Why can `channel_show` avoid actor resolution and broker queue access while
   `list_threads()` cannot?
3. Where do CLI, Python, and MCP construct their public records, and which
   layer must remain the single owner of topic validation?
4. Why does channel rename preserve `meta` today, and which rename race outcomes
   remain safe without adding a second global lock?

## 5. Invariants and Constraints

- The existing channel name grammar, registry authority, membership rows,
  message history, cursors, notices, DM naming, and rename queue sequence do
  not change.
- Topic validation and domain semantics live once in core. CLI and MCP are
  thin parsing/schema adapters.
- Topic mutation and rename-marker creation use the same per-channel
  transaction serialization key. Every future Taut writer that patches a
  top-level channel's `meta` must join that namespace.
- Topic reads and no-op writes are observational. They do not create or heal
  identity, touch activity, open broker queues, or move cursors.
- A changed topic write requires one existing member and current channel
  membership. This is coordination authority inside Taut's weak trust domain,
  not authentication.
- `taut_threads.meta` remains a forward-compatible JSON object. Every topic
  mutation preserves the reserved `closed` sibling and unknown top-level keys.
- A malformed stored `topic` object is a storage-contract error. A list, show,
  rename, or mutation operation must fail cleanly with no partial output or
  traceback. Rename validates before its marker or broker work; mutation must
  not silently repair or overwrite the object.
- A topic update is all-or-nothing sidecar state. There is no auxiliary chat or
  notification write whose failure can downgrade or partly complete it.
- Rename preserves topic metadata. No implementation may copy topic through a
  second store or derive it from history.
- Human rendering always escapes dynamic topic and author text. JSON and
  Python preserve exact accepted content.
- No new dependency, schema generation, table, queue, broker alias, background
  worker, cleanup lifecycle, TUI implementation, or installed-command nested
  extension point is introduced.
- Stop and re-plan if implementation needs broker SQL, a second metadata store,
  a schema-version bump, a cross-process lock outside sidecar transactions, or
  a change to existing rename ordering.

## 6. Rollout, Rollback, and One-Way Doors

There is no destructive migration or one-way door. Older Taut versions ignore
the new `taut_threads.meta` keys and continue to preserve them because their
rename path changes row names without rebuilding metadata. Newer versions
must preserve all unknown keys on topic mutation.

Rollout is coordinated because the CLI route, Python record shapes, and MCP
manifest change together:

1. Promote the development, core, identity, and MCP specs before code cites
   them.
2. Land state and public Python behavior with backward-readable metadata.
3. Move the existing rename parser and dispatch into the nested CLI adapter,
   cease registering the old route, update recovery diagnostics, and land MCP
   adapters against that public behavior.
4. Run installed-wheel and live PostgreSQL proof before release.
5. Release core before or with MCP at the coordinated version floor.

Rollback is a code/package revert. Existing topic metadata may remain in
`taut_threads.meta`; the prior version ignores it, and reinstalling the feature
restores access. Rollback must not delete the `topic` object, the reserved
`closed` sibling, or unknown keys. If malformed metadata is discovered after
rollout, stop writes and repair through an explicit, reviewed recovery change
rather than teaching readers to guess.

The CLI move is intentionally direct because no public package has been
released. There is no alias or deprecation window. Rolling back restores the
old top-level route; no stored state participates in the route change.

## 7. Spec Baseline

- `061476da16e336cc82f319f8007d562b855de03a`:
  `docs/specs/01-development-documentation-operating-model.md`,
  `docs/specs/02-taut-core.md`,
  `docs/specs/03-identity-addressing-notifications.md`, and
  `docs/specs/05-taut-mcp.md` at plan authoring time.
- Promotion baseline:
  `061476da16e336cc82f319f8007d562b855de03a` plus the reviewed worktree
  spec delta in `docs/specs/01-development-documentation-operating-model.md`,
  `docs/specs/02-taut-core.md`,
  `docs/specs/03-identity-addressing-notifications.md`, and
  `docs/specs/05-taut-mcp.md`. Verification is the rerunnable documentation,
  plan-index, path-claim, and diff gates in §12. Replace this worktree
  identifier with the landed commit SHA when the owner authorizes a commit.

## 8. Proposed Spec Delta

Promotion strategy: **A, in-file text before implementation-link claims**.
Promote the requirements into the existing active specs after independent
review. Do not add code-link claims until the corresponding code and
reciprocal backlinks land.

| Spec file | Strategy | Sections touched |
|-----------|----------|------------------|
| `docs/specs/01-development-documentation-operating-model.md` | A | [DOM-10], new [DOM-10.1] |
| `docs/specs/02-taut-core.md` | A | [TAUT-1], [TAUT-3.3], new [TAUT-4.4], [TAUT-8.1]–[TAUT-8.3], [TAUT-8.6], [TAUT-10], [TAUT-11] |
| `docs/specs/03-identity-addressing-notifications.md` | A | [IAN-8.1], [IAN-9], [IAN-10] |
| `docs/specs/05-taut-mcp.md` | A | [MCP-5], [MCP-6], [MCP-9], [MCP-11], [MCP-12] |

### Development-documentation delta

Add [DOM-10.1]:

> Maintained documentation claims about executable Taut command paths must be
> checked against the deterministic core command registry. The repository
> owns one CLI-claim grammar and source list in its pytest gate; a standalone
> bin entry point imports that contract rather than duplicating it.
>
> Recognized claims are shell-like `taut ...` invocations in Markdown inline
> code or fenced code. Validation covers the top-level verb and any required
> nested operation exposed by a core adapter. It uses
> `CommandRegistry(entry_points=())` plus side-effect-free parser
> configuration, and performs no ambient entry-point discovery, client
> construction, project resolution, database access, or command execution.
>
> The exact source set is `README.md`, `AGENTS.md`, `CLAUDE.md`,
> `docs/README.md`, `docs/coalescing.md`, `docs/plans/README.md`,
> `extensions/*/README.md`, `docs/agent-context/*.md`,
> `docs/agent-context/runbooks/*.md`, `skills/**/*.md`,
> `docs/implementation/*.md`, and `docs/specs/*.md`. `CHANGELOG.md`,
> `docs/lessons.md`, and individual dated plan bodies are explicitly
> historical and excluded. A deliberately future, invalid-example, or
> external-extension command path requires a source-scoped exact exemption
> with a non-empty reason; an exemption that now resolves is itself a failure.
> Failures identify source, line, command path, and reason. The standalone
> checker exits 0 for success, 1 for claim failures, and 2 for invocation or
> environment failure.

### Core delta

Insert this exact subsection after [TAUT-4.3]:

> ### [TAUT-4.4] Channel topics
>
> A registered top-level channel has zero or one current topic. Direct
> messages, subthreads, notification queues, and system queues cannot have
> topics. The authoritative state is the top-level channel's existing
> `taut_threads.meta` object:
>
> - the top-level sibling keys `topic` and `closed` are reserved for channel
>   metadata;
> - no topic means `topic` is absent;
> - a present `topic` is an object with exactly `text`, `updated_ts`, and
>   `updated_by_id`. `text` is a string, `updated_ts` is a non-boolean integer
>   in Taut's timestamp domain, and `updated_by_id` is an [IAN-3.1] member id;
> - `closed` is reserved but has no value shape or behavior in version 0.8.0.
>   Taut does not write or interpret it and preserves it if encountered; and
> - a non-object, partial, extra-key, or wrong-typed `topic` value is corrupt
>   channel-topic metadata. Topic-aware list, show, rename, and mutation paths
>   fail cleanly rather than guessing, repairing, or overwriting it. Rename
>   validates the topic object before marker creation or broker queue mutation.
>
> Topic mutation replaces only the `topic` object and preserves `closed` plus
> every unknown top-level metadata key. Clearing removes only `topic`. It adds
> no table, column, broker alias, queue row, chat notice, notification, cursor
> change, or schema-version bump.
>
> A string topic must be nonblank under [TAUT-6.5], contain neither carriage
> return nor line feed, and contain at most 500 Unicode code points under
> Python `len()`. Accepted text is stored exactly; Taut does not trim,
> normalize, fold, or otherwise rewrite it. `None` is the public clear value.
> Invalid type, blank text, CR/LF, and 501-or-more-code-point text fail before
> identity, activity, membership, timestamp, or metadata work.
>
> `get_channel(channel)` is observational: it validates a top-level name,
> requires a registered `kind == "channel"` row, and reads only sidecar state.
> It does not resolve identity, touch activity, inspect a broker queue, create
> membership, or move a cursor.
>
> `set_channel_topic(channel, topic)` resolves one existing acting member
> without creating or healing identity. The member must currently belong to
> the channel. Topic mutation and channel rename-marker creation share the
> per-channel serialization namespace `taut:channel:<channel-name>`: SQLite
> uses its write transaction and PostgreSQL acquires a transaction advisory
> lock. Under that boundary, mutation rechecks incomplete rename state,
> channel kind, membership, and current metadata before replacing the topic
> object. A changed value stores one internally consistent
> text/timestamp/member-id object and updates member activity in the same
> sidecar transaction. A same-value set or already-absent clear is a successful
> no-op that preserves audit fields and activity. Concurrent different values
> are last-committed-write-wins; cooperative changes to `closed` or unrelated
> metadata keys are preserved.
>
> A preliminary equal-value read may avoid timestamp allocation. A race may
> allocate a broker timestamp that the authoritative transaction does not use
> because another writer committed the requested value first; no unused
> timestamp is stored.
>
> Rename-marker creation acquires the same old-name serialization key. A topic
> mutation that wins commits before the marker and follows the registry row to
> its new name. A marker that wins makes a later old-name mutation fail without
> writing. Rename never clears or rebuilds topic metadata.
>
> Possible future commands include `taut channel close CHANNEL` and
> `taut channel reopen CHANNEL`. They are not required behavior: this section
> defines no lifecycle state, visibility filter, write gate, archive rule,
> retention rule, or `closed` value shape/default. Version 0.8.0 only reserves
> the sibling key name and preserves it.

Add these exact [TAUT-8.1] rows:

> | `channel show CHANNEL` | Return current metadata for one registered top-level channel. Resolves no actor and changes no activity, membership, queue, message, notification, or cursor state. | 0 showed; 1 invalid name, corrupt metadata, or error; 2 no such top-level channel |
> | `channel topic CHANNEL TEXT` / `channel topic CHANNEL --clear` | Set one exact one-line topic or explicitly clear it. Requires an existing acting member and current channel membership. A same-value set and absent clear are successful no-ops. No stdin form. | 0 changed or no-op; 1 usage, invalid topic, corruption, or error; 2 no such channel / unrecognized member / not a member |
> | `channel rename OLD NEW` | Rename a channel and every registered one-level sub-thread under it. Uses SimpleBroker's public queue rename API and sidecar rename markers. Does not rewrite message bodies. | 0; 1 error/collision/invalid name; 2 no such channel |

Move the top-level `rename OLD NEW` row to the nested row above. There is no
compatibility alias.

Add this exact [TAUT-8.2] contract:

> `channel show` and `channel topic` emit a channel object with exactly
> `channel`, `topic`, `topic_updated_ts`, `topic_updated_by_id`, and
> `topic_updated_by_name`. The last four fields are null when no topic exists.
> The author name is the stable author's current display name when available,
> otherwise null. Every top-level channel `Thread` record, including `list`,
> CLI `channel rename`, and MCP `channel_rename`, includes required `topic` as
> string or null. Non-channel thread and DM records omit `topic`. Human list
> output adds one escaped indented topic line only for a channel with a topic.
> Human `channel show` prints the channel and either its topic plus update
> attribution or `(none)`. Human `channel show` and `channel topic` escape
> topic and current author text. Quiet mode emits no success record.

Add to [TAUT-8.1]'s help contract:

> Channel help teaches the one-line 500-code-point topic bound, explicit
> `--clear`, membership requirement, observational `show` behavior, and 0/1/2
> exit classes.

Add this exact [TAUT-8.3] contract:

> `Channel` is a frozen, slotted public value with exact fields
> `name: str`, `topic: str | None`, `topic_updated_ts: int | None`,
> `topic_updated_by_id: str | None`, and
> `topic_updated_by_name: str | None`. It is exported from `taut.client` and
> lazily from `taut`. `TautClient.get_channel(channel: str) -> Channel` and
> `TautClient.set_channel_topic(channel: str, topic: str | None) -> Channel`
> implement [TAUT-4.4]. `Thread` appends
> `topic: str | None = None`; top-level channel projections populate it.

Add this exact [TAUT-8.6] contract:

> `channel` is a reserved core built-in whose selected adapter owns required
> `show`, `topic`, and `rename` nested subparsers. `topic` requires exactly one
> of positional `TEXT` or `--clear`; it has no stdin form. `rename` requires
> exactly `OLD NEW` and delegates to the existing public channel-rename
> behavior. A literal `--` keeps later option-shaped text positional.
> Installed commands cannot override, hide, or extend the built-in's nested
> namespace. The existing rename adapter behavior is rehomed intact; the
> former top-level registration ceases without an alias or retired-name
> mechanism. The top-level name `rename` then follows the ordinary
> installed-command rules; core gives it no special reservation.

Add firing [TAUT-10] and [TAUT-11] bullets for every validation class, metadata
object state, reserved-sibling preservation rule, exit class, activity/no-op
rule, human/JSON branch, serialization race, rename race, and no-side-effect
claim above.

Change the `taut_threads.meta` schema comment to say that channel metadata,
including reserved `topic` and `closed` siblings, plus DM, notification, and
system routing metadata live there and unknown keys must be preserved.

### Rename delta

Add to [IAN-8.1]:

> Rename changes channel and subthread addresses without rebuilding their
> registry rows. Every `taut_threads.meta` key, including [TAUT-4.4] channel
> topic metadata, survives unchanged. Rename validates the source channel's
> topic object before marker creation or broker mutation and refuses corrupt
> metadata. Topic mutation and rename-marker creation acquire the same
> per-channel transaction serialization key. A concurrent topic transaction
> either commits against the old row before marker creation and follows that
> row, or observes the marker and refuses the old-name write; rename never
> drops a committed topic.
>
> The public CLI route is `taut channel rename OLD NEW`. Incomplete-rename
> diagnostics name that exact recovery command. The Python
> `TautClient.rename_channel()` method retains its existing name and semantics.
> The MCP tool moves one-for-one from `rename` to `channel_rename`, with no
> input, output, annotation, dispatch, or domain change and no alias.

Add matching failure and shared-backend verification bullets.

### MCP delta

Add these exact [MCP-5] rows and annotation values:

> | `channel_show` | `taut channel show` | read-only shared channel metadata |
> | `channel_topic` | `taut channel topic` | shared channel-metadata replacement or clear |

Rename the existing MCP `rename` tool to `channel_rename` and change its owning
CLI behavior from `taut rename` to `taut channel rename`. Preserve its exact
input schema, output schema, annotations, dispatch, and semantics. Do not keep
an MCP alias; the fixed manifest remains 20 tools.

Normalize the existing message tools in the same manifest:
`show_message` to `message_show`, `delete_message` to `message_delete`, and
`react_to_message` to `message_react`. Preserve every non-name contract and
omit all former identifiers. Together with `channel_show`, `channel_topic`,
and `channel_rename`, nested CLI concepts use noun-first MCP identifiers.

> `channel_show` description: `Return current metadata for one registered
> top-level Taut channel. Reads only shared registry state and does not resolve
> identity, touch activity, inspect a broker queue, or move a cursor.`
> Its hints are read-only true, destructive false, idempotent true, open-world
> true.
>
> `channel_topic` description: `Set or clear one registered top-level Taut
> channel's topic. Requires the attached member's current channel membership;
> a changed value replaces shared topic state and updates member activity,
> while an identical value is a no-op.`
> Its hints are read-only false, destructive true, idempotent false, open-world
> true.

Add this exact input contract:

> Both tools require `workspace` and `channel`; `channel_topic` also
> requires `topic`. `channel` uses [TAUT-4.1]'s top-level grammar. `topic` is
> one of null or a string with `maxLength: 500` and
> `not: { "pattern": "[\\r\\n]" }`. Core performs the Unicode blank check.
> All input schemas remain closed. The fixed manifest contains exactly 20
> tools.

Add this exact result and error contract:

> Both tools return `record_type: "channel"` and a closed record with required
> `channel`, `topic`, `topic_updated_ts`, `topic_updated_by_id`, and
> `topic_updated_by_name`. The existing thread record becomes a closed
> discriminated `oneOf`: `kind: "channel"` requires `topic` and forbids
> `members`; `kind: "dm"` requires `members` and forbids `topic`; and
> `kind: "subthread"` forbids both.
>
> Schema-invalid calls fail before child dispatch. An in-schema blank topic,
> absent membership, corrupt topic, or recoverable backend/storage `TautError`
> returns `isError: true` with one text block and no structured content.
> Absent or wrong-kind channels return the successful empty channel envelope
> with canonical workspace, no records, warnings, or guidance. Identity loss
> and unexpected reactor failure retain their existing fixed errors and status
> transitions.
>
> A started `channel_topic` whose response is canceled or lost has an
> uncertain outcome. The caller uses `channel_show` before considering a retry;
> the MCP layer adds no retry or optimistic concurrency token.

Update [MCP-9] instructions to prefer topic-bearing list records for
orientation and `channel_show` for current metadata; they must not timer-poll
either tool.

Add firing schema tests for every new property, bound, pattern, required field,
annotation, record field, tool name, and record type. Add started-cancellation
recovery and live PostgreSQL tool-flow proof.

## 9. Deviation Log

| Spec ref | Planned behavior | Actual behavior | Rationale | Spec proposal |
|----------|------------------|-----------------|-----------|---------------|
| [MCP-5], [MCP-8] | Preserve the generic post-command notification refresh unchanged. | `channel_show` carries the existing cached snapshot; every other CLI-shaped command still refreshes after execution. | The generic refresh calls `peek_inbox()`, which resolves attachment identity and inspects the notification queue, contradicting `channel_show`'s exact actor-free, sidecar-only contract. The cached snapshot preserves completion ordering because show has no notification effect. | Promoted the narrow exception and its reactor-level firing test into `docs/specs/05-taut-mcp.md`. |
| §12 verification | Run the shorthand `uv run --extra dev mypy .`. | The command was run and failed because the root environment intentionally lacks MCP-only SDK/stub dependencies. The repository's canonical root/PG, root/Summon, and MCP-project mypy invocations all pass. | `pyproject.toml` already documents split type-check ownership; one root invocation cannot represent all package environments. | Keep the active spec unchanged; record the three canonical commands as authoritative evidence. |
| Completion quality | No adjacent baseline correction anticipated. | Added `meta: dict[str, object]` to the committed DM corruption fixture. | The full canonical mypy gate exposed an existing inference error in `tests/test_direct_messages.py`; the annotation changes no runtime behavior and restores the repository-wide gate. | None. |

## 10. Dependency-Ordered Tasks

1. **Independent contract review and spec promotion.**
   - Review this plan, especially §§2, 5, 6, and 8, against the named code and
     active specs.
   - Resolve every blocker, then apply the delta to all four active specs and
     add reciprocal `## Related Plans` links.
   - Record the promotion baseline identifier.
   - Done signal: reviewer can implement without a new product decision;
     `uv run --extra dev pytest tests/test_docs_references.py -q -n0`,
     `uv run bin/check-doc-paths`, `bin/check-plan-status-index`, and
     `git diff --check` pass.

2. **Red-green state and public-value slice.**
   - Files: `taut/state/__init__.py`, `taut/state/_sql.py`,
     `taut/state/_types.py`, `taut/client/_models.py`,
     `taut/client/__init__.py`, `taut/__init__.py`,
     `tests/test_state_contract.py`, `tests/test_shared_contract.py`.
   - Add failing tests first for valid set/clear, same-value no-op, all
     validation bounds, absent and malformed topic objects, exact nested keys,
     reserved `closed` and unknown-key preservation, atomic audit fields,
     membership recheck, activity rules, two concurrent topic writers, one
     topic writer racing a cooperative unknown-key metadata writer, and topic
     mutation racing rename-marker creation on SQLite and Postgres. The
     cooperative metadata writer must acquire the same namespace; a writer
     that violates the lock contract is not claimed safe.
   - Use real sidecar transactions and both dialect paths. Do not mock the
     state interface, SQL session, or metadata JSON.
   - Stop if a schema bump, table, or out-of-transaction read/modify/write is
     needed.
   - Done signal: targeted state/shared-contract suites pass on both backends.

3. **Red-green client behavior and list projection.**
   - Files: `taut/client/_threads.py`, `tests/test_client.py`.
   - Add `get_channel`, `set_channel_topic`, one shared metadata decoder, and
     `Thread.topic` population. Keep `get_channel` broker-free and actor-free.
   - Prove absent/wrong-kind targets, membership failure, no identity healing,
     no activity on reads/no-ops/failures, rename preservation/races,
     corruption rejection before rename marker or broker work, and list topic
     population without changing DM/subthread shapes.
   - Do not mock Queue to prove `get_channel`; instead assert broker high-water
     and sidecar state remain unchanged around the real call.
   - Done signal: focused client tests pass and a reviewer confirms one
     validation/decoder owner.

4. **Red-green reserved CLI noun and rendering.**
   - Files: new `taut/commands/channel.py`, existing
     `taut/commands/rename.py` as the move source,
     `taut/commands/_builtins.py`, `taut/commands/_rendering.py`,
     `taut/client/_base.py`,
     `tests/test_cli.py`, `tests/test_command_registry.py`,
     `tests/test_cli_probes.py`.
   - Add parser failures before implementation: missing operation, missing
     channel, missing text, text plus `--clear`, extra arguments, unknown
     options, global-option placement, literal `--`, blank/Cf-only text,
     CR/LF, 500/501 code points, absent channel, nonmember, corrupt metadata,
     JSON, quiet, human escaping, and no traceback.
   - Add failing route-move tests before changing the adapter: nested rename
     has byte-equivalent successful human/JSON/quiet output and exit classes;
     interrupted-rename diagnostics name the nested command; core-only root
     help and selection have no top-level rename; an installed top-level
     `rename` manifest receives ordinary extension handling.
   - Move the current rename parser and `rename_channel()` dispatch intact into
     `ChannelCommand`; do not duplicate or rewrite the domain behavior. Delete
     the now-empty top-level adapter module only after import, wheel-content,
     and command-registry tests prove the move.
   - Prove root help reserves `channel`, unrelated broken extensions stay
     isolated, and installed commands cannot override the noun.
   - Do not test through adapter mocks for final acceptance. Run the shipped
     CLI subprocess against a real database.
   - Done signal: CLI/registry/probe suites pass with exact exit classes and
     no partial output on failure.

5. **Red-green documentation command-claim gate.**
   - Files: new `tests/test_cli_claims.py`, new `bin/check-cli-claims`,
     `docs/specs/01-development-documentation-operating-model.md`,
     `docs/agent-context/runbooks/maintaining-traceability.md`, and repository
     task/CI entry points that enumerate documentation gates.
   - Add failing fixtures first for stale top-level and nested commands,
     missing required nested operations, prompt/env/global/pipeline forms,
     inline and fenced claims, prose false positives, future and external
     exemptions, stale exemptions, source/line diagnostics, plans exclusion,
     and exit 0/1/2 behavior.
   - Let the pytest module own extraction, sources, exemptions, and validation.
     The bin entry point imports it. Derive core paths from
     `CommandRegistry(entry_points=())` and adapter parser configuration; do
     not copy command-name lists or discover ambient extensions.
   - The gate validates command paths, not full argument semantics. Stop and
     re-plan if reliable nested-path discovery requires executing adapters,
     creating a client, or importing optional heavy subsystems.
   - Done signal: self-fixtures pass, the checker catches a temporary
     `taut rename OLD NEW` claim in a maintained current-behavior document,
     and the clean tree passes `uv run bin/check-cli-claims`.

6. **Red-green MCP tools and recovery.**
   - Files: `extensions/taut_mcp/taut_mcp/_tools.py`,
     `extensions/taut_mcp/taut_mcp/_commands.py`,
     `extensions/taut_mcp/taut_mcp/_workspace_reactor.py` only if the existing
     generic path cannot carry the new records unchanged,
     `extensions/taut_mcp/tests/test_tools.py`,
     `extensions/taut_mcp/tests/test_stdio_server.py`,
     `extensions/taut_mcp/tests/test_pg_conformance.py`.
   - Add failing exact schema/annotation/20-tool snapshots, including terminal
     CR/LF probes and the closed thread `oneOf`; public dispatch, exact empty
     versus `isError` outcomes, output encoding, no-op behavior, actor
     authority, pre-dispatch invalid input, started-cancellation recovery, and
     SQLite/Postgres end-to-end tests.
   - Rehome existing MCP identifiers one-for-one: `rename` to
     `channel_rename`, `show_message` to `message_show`, `delete_message` to
     `message_delete`, and `react_to_message` to `message_react`. Prove the
     manifest uses noun-first identifiers, omits every former identifier,
     remains exactly 20 tools, and preserves all non-name contracts.
   - Keep the generic reactor and result envelope unchanged. Do not add special
     topic concurrency, retries, or private-state access in MCP.
   - Do not mock `TautClient` for the final stdio and backend proofs.
   - Stop if the new tools require a reactor lifecycle change.
   - Done signal: MCP unit, stdio, installed-wheel, and live PostgreSQL gates
     pass.

7. **Documentation, traceability, and final review.**
   - Files: `README.md`, `docs/README.md` if its surface inventory needs
     adjustment, `docs/implementation/04-taut-architecture.md`,
     `docs/implementation/06-command-extensions.md`,
     `docs/implementation/07-taut-mcp-architecture.md`, active specs, this
     plan, and relevant release/changelog files only when implementation lands.
   - Explain why topics live in registry metadata, why no history notice is
     emitted, the atomic merge boundary, why rename lives under `channel`, and
     why close/reopen remains future work. Update README command examples and
     architecture recovery text from `taut rename` to
     `taut channel rename`.
   - Add implementation mappings and reciprocal backlinks with the code slice,
     reconcile the deviation log, and obtain independent final review.
   - Done signal: full local gates, docs/index/reference gates, packaging
     smoke, installed-wheel proof, live PostgreSQL proof, and fresh-eyes review
     pass; committed landing evidence is recorded only after owner-authorized
     commit.

## 11. Testing Plan

| Layer | Real proof |
|-------|------------|
| Pure validation | Exact type, blank predicate, CR/LF, 500/501 boundary, and exact text preservation. |
| State contract | Real SQLite and PostgreSQL sidecar transactions, absent/valid/malformed topic objects, reserved `closed` and unknown-key preservation, activity/no-op behavior, two topic writers, cooperative unrelated metadata write, and rename-marker race. |
| Python API | Public exports, exact `Channel`/`Thread` values, actor-free show, membership-scoped mutation, rename, and broker/cursor non-effects. |
| CLI | Real parser/dispatcher/database subprocesses for grammar, exit 0/1/2, JSON, quiet, escaping, the mechanical rename rehome, core-only top-level absence, ordinary extension reuse of the freed name, extension conflict, and hostile inputs. |
| Documentation claims | Fixture-driven inline/fence extraction, deterministic registry and nested-parser validation, exact exemptions, stale-exemption rejection, source scoping, diagnostics, and bin exit classes. |
| MCP unit | Exact 20-tool noun-first manifest with no former identifiers, closed schemas, annotations, public dispatch, channel/thread records, and cancellation recovery. |
| MCP stdio | Official SDK discovery and calls against a real SQLite project. |
| Cross-backend | Existing shared-contract and live MCP PostgreSQL harnesses with set/show/list/channel-rename flow. |
| Packaging | Fresh core and MCP wheels installed in clean environments; public imports, CLI help, tool discovery, and one set/show round trip. |

Applicable adversarial probes are mandatory: no traceback, truthful exit
classes, literal grammar mimicry after `--`, malformed stored JSON, missing
target, hostile terminal text, concurrent mutation, self-application, and
every enumerable field/flag/exit/schema element firing at least once.

## 12. Verification and Gates

Per-slice commands:

```bash
uv run --extra dev pytest tests/test_state_contract.py tests/test_shared_contract.py -q -n0
uv run --extra dev pytest tests/test_client.py -q -n0
uv run --extra dev pytest tests/test_cli.py tests/test_command_registry.py tests/test_cli_probes.py -q -n0
uv run --directory extensions/taut_mcp --extra dev pytest tests/test_tools.py tests/test_stdio_server.py -q -n0
```

Final commands must include:

```bash
uv run --extra dev pytest -q
uv run --extra dev ruff check .
uv run --extra dev mypy .
uv run --directory extensions/taut_mcp --extra dev pytest -q
uv run --extra dev pytest tests/test_docs_references.py -q -n0
uv run bin/check-doc-paths
uv run bin/check-cli-claims
bin/check-plan-status-index
git diff --check
```

Run the repository's documented live PostgreSQL, installed-wheel, and
release-grade paired-package gates rather than inventing substitutes. Record
the exact commands and observed counts in this plan during implementation.

### Implementation evidence

| Gate | Observed result |
|------|-----------------|
| `uv run --extra dev pytest -q` | 1,401 tests collected; 1,400 passed and the Windows-only filename contract was skipped on macOS. |
| `uv run --project extensions/taut_mcp --extra dev pytest extensions/taut_mcp/tests -q -n0 -m 'not pg_only' -ra` | 171 non-PostgreSQL MCP tests passed. |
| `uv run ./bin/pytest-pg --fast --keep-container` | 219 shared-contract tests and 14 PostgreSQL-extension tests passed; the temporary container was removed after the run. |
| `uv run --project extensions/taut_mcp --extra dev pytest extensions/taut_mcp/tests -q -n0 -m pg_only` | All 6 live PostgreSQL MCP tests passed. After expanding the topic flow, its focused PostgreSQL test also passed. |
| Live PostgreSQL corrupt-topic rename preflight | The focused state-contract test passed and proved no marker or metadata change on rejection. |
| Canonical Ruff check and format commands from `README.md` | All checks passed; 159 Python files were already formatted after the two changed files were normalized. |
| Canonical split mypy commands from `README.md` | Core/PostgreSQL: 99 files; core/Summon: 130 files; MCP: 17 files. All passed with no issues. |
| `uv run --extra dev pytest tests/test_docs_references.py tests/test_cli_claims.py tests/test_plan_status_index.py -q -n0` | 46 documentation, command-claim, and plan-index tests passed. |
| `uv run bin/check-doc-paths` | 48 maintained sources and 789 path claims checked; OK. |
| `uv run bin/check-cli-claims` | 48 maintained sources and 199 command claims checked; OK. |
| `uv run bin/check-plan-status-index` and `git diff --check` | Both passed. |
| Fresh core/MCP installed-wheel smoke | Clean environment imported `Channel`, set and read a topic, showed all three nested channel operations, and discovered exactly 20 MCP tools. |
| `uv run python bin/build-and-check-release-wheels.py` | All six current/historical core and Summon installed-wheel cases passed. |
| `git tag --list 'v0.8.0' 'taut_mcp/v0.8.0'` | No local release tags exist; core and MCP remain at 0.8.0 and MCP requires `taut>=0.8.0`. |

Post-deploy success signals:

- `taut channel show`, `taut channel topic`, channel-bearing `taut list`, and
  both MCP tools agree on exact topic text and audit fields;
- `taut channel rename OLD NEW` preserves the prior rename behavior and
  recovery path, core registers no top-level rename, and MCP exposes
  `channel_rename` with no `rename` alias;
- no topic operation writes a chat/notification row or moves a cursor;
- topic metadata survives rename and is still ignored safely by the previous
  core version; and
- MCP discovery reports exactly 20 tools with the documented noun-first names,
  annotations, and schemas; and
- the command-claim gate rejects a stale `taut rename OLD NEW` fixture while
  all maintained current command claims pass.

## 13. Independent Review Loop

Plan review:

> Read this plan and its `## Proposed Spec Delta`, the four active specs, and
> the named current code. Look for wrong product choices, missing state or
> concurrency rules, unsafe compatibility assumptions, ambiguous public
> shapes, weak tests, and process that does not buy correctness. Do not
> implement. Could a zero-context engineer implement the promoted delta
> confidently without another product decision?

The author must record each finding and its disposition below. A reviewer who
cannot answer yes blocks spec promotion.

Implementation review:

- Review after the state/Python slice, after the CLI/MCP slice, and once more
  before completion.
- Use a reviewer who did not author the slice. Give the reviewer the promoted
  specs, plan, diff, and targeted test evidence.
- Fix findings or record a reasoned rejection. No unresolved correctness,
  compatibility, confidentiality, metadata-loss, traceback, or contract-test
  finding may remain at completion.

### Review Log

| Date | Reviewer | Scope | Finding | Disposition |
|------|----------|-------|---------|-------------|
| 2026-07-28 | Independent agent | Plan and proposed delta | Anchored negated-class schema accepted terminal LF under the validator. | Accepted. The string branch now uses unanchored `not.pattern` and requires terminal CR/LF probes. |
| 2026-07-28 | Independent agent | State and rename concurrency | A transaction alone did not serialize PostgreSQL metadata merges or close the pre-marker rename race. | Accepted. Topic mutation and marker creation now share an exact per-channel SQLite/PostgreSQL serialization namespace with three required race proofs. |
| 2026-07-28 | Independent agent | MCP errors | Empty versus `isError` behavior was not defined for channel, membership, identity, corruption, and storage failures. | Accepted. §2.6 now gives an exact outcome matrix and preserves the existing terminal fault path. |
| 2026-07-28 | Independent agent | MCP annotations and schemas | Retrying a lost-response setter can overwrite a newer topic; optional topic did not enforce kind-dependent shape. | Accepted. Setter idempotence is false, and the thread record is a closed discriminated union tested through list and rename. |
| 2026-07-28 | Independent agent | Corrected plan and promotion-ready delta | Re-review approved all four corrections and found no remaining product or executability blocker; proposed spec text was promotion-ready. | Accepted. The reviewed delta was promoted into all four active specs before behavior implementation. |
| 2026-07-28 | Independent agent | Active-spec promotion audit | Exact human `(none)` output and detailed nested-help requirements remained only in the plan. | Accepted. Both contracts and their firing tests were promoted into [TAUT-8]. |
| 2026-07-28 | Independent agent | Final active-spec audit | Core, identity, MCP, and plan contracts align after adding corrupt-topic rename preflight; no lifecycle behavior or unresolved product decision remains. One test bullet said “observational read.” | Approved after changing the typo to “observational show.” |
| 2026-07-28 | Independent agent | Rehome, MCP naming, metadata-shape, and claim-gate revision | Product contract and parser-only claim discovery were sound. The schema comment omitted reserved `closed`; claim-gate source scope used an open-ended “including” and did not explicitly exclude historical `CHANGELOG.md`. | Accepted. The schema comment now names both reserved siblings; the plan and [DOM-10.1] enumerate the exact source set and historical exclusions. |
| 2026-07-28 | Independent agent | Final four-spec promotion audit | Plan and all four active specs align; the two revision findings are resolved; no product decision or implementation blocker remains. | Approved. |
| 2026-07-28 | Independent agent | State/client implementation slice | Direct firing tests were missing for corrupt-topic rename preflight and wrong-kind client get/set behavior. | Accepted. Added real-state tests for no marker/metadata mutation, wrong-kind rejection, no activity, and non-channel projection corruption; SQLite and PostgreSQL proofs passed. Re-review approved the slice. |
| 2026-07-28 | Independent agent | CLI/MCP implementation slice | `channel_show` refreshed actor-scoped notifications; MCP firing coverage had gaps; the command-claim parser mishandled literal separators; one tool-count comment was stale. | Accepted. Show now carries the cached snapshot without identity/broker work; schema, fault, and identity tests were added; separator handling and its adversarial tests were corrected; the comment now reports 17 CLI-shaped tools. |
| 2026-07-28 | Independent agent | CLI/MCP re-review | A double literal separator could still hide an invalid nested operation, and recoverable storage `TautError` lacked a reactor-readiness test. | Accepted. Both firing tests and fixes landed; final slice re-review approved with no remaining findings. |
| 2026-07-28 | Independent agent | Final fresh-eyes implementation review | The shipped CLI lacked direct absent-topic and wrong-kind show/topic firing cases required by [TAUT-10]. No production defect was found. | Accepted. Added three real-database cases proving exit 2, empty stdout, no traceback, and unchanged registry/member activity. The full root suite, Ruff, mypy, and diff checks passed after the fix; final re-review approved with no remaining findings. |

### Spec-promotion evidence

| Gate | Observed result |
|------|-----------------|
| `bin/check-plan-status-index` | Plan status index OK. |
| `uv run bin/check-doc-paths` | 48 sources and 769 path claims checked; OK. |
| `uv run --extra dev pytest tests/test_docs_references.py -q -n0` | 10 tests passed. |
| `git diff --check` | Passed with no output. |

These were the documentation-promotion gates at the spec-first checkpoint.
The later implementation evidence in §12 supersedes their counts and records
the full-suite, cross-backend, installed-wheel, and release-grade results.

## 14. Out of Scope

- `channel close`, `channel reopen`, archive/closed list modes, or write
  rejection based on lifecycle state
- TUI implementation or live topic-change observation
- topic history, revision log, notices, mentions, or notifications
- topics on DMs, subthreads, notifications, or system queues
- topic permissions beyond current membership in Taut's existing trust domain
- broker aliases, new tables/columns, schema migrations, indexes, caches, or
  cleanup jobs
- message editing, retention, search ranking, pinning, descriptions, owners,
  ACLs, or moderation
- changing channel rename ordering or adding a general metadata command
- renaming `TautClient.rename_channel()` or the existing message-domain Python
  methods
- retaining top-level CLI or former MCP compatibility aliases

## 15. Fresh-Eyes Review

Before implementation begins, verify that a new engineer can answer:

- which exact row and keys own the topic;
- which reads and no-ops may touch activity;
- who can mutate a topic and where membership is rechecked;
- how clear, corruption, concurrency, and rename behave;
- which rename behavior moves, which Python names stay stable, why MCP nested
  operations use noun-first identifiers, and why no compatibility aliases
  exist;
- what every Python, CLI, JSON, and MCP record contains;
- what stays real in tests;
- how rollback works without deleting metadata; and
- why possible close/reopen behavior is not silently implied by this slice.

If any answer requires inference, revise the plan and promoted spec before
code starts.
