# Message React Plan

Date: 2026-07-28

Status: **implemented and verified locally; awaiting repository-owner
commit**. SimpleBroker 5.6.1 provides the required public full-requested-set
exact-name broadcast. Core, CLI, MCP, watcher, SQLite, and PostgreSQL contracts
pass. Completed-work bare `claude -p` review found no behavior or layer
defect; its two firing-test gaps and one format-gate finding were fixed and
reverified. The historical 5.6.0 blocker remains in section 16 for audit.

Plan type: implementation using the released SimpleBroker
all-requested-name broadcast, with coordinated Taut core,
identity/notification, and MCP changes.

Class: 5. The change adds a public configured vocabulary, a Python method, a
CLI subcommand, and an MCP tool; advances seen state; and fans one logical
reaction into multiple independently consumable notification rows. It changes
the public notification payload and fixed MCP manifest. The queued fanout,
cross-store cursor work, public dependency contract, and compatibility
sequencing fire [DOM-5]'s risky triggers, so the hardening checklist is
required.

Owner: the implementing engineer owns spec promotion, configuration loading,
core policy, fanout, Python/CLI/MCP adapters, real-backend tests,
documentation, and review evidence. The repository owner owns version
selection, commit, release, deployment order, and publication.

Resolved prerequisite: SimpleBroker 5.6.0's existing-queue selector was not
sufficient for Taut's membership-defined audience because registration and
join do not establish a broker inbox row, and vacuum removes an emptied inbox.
SimpleBroker 5.6.1 resolves that mismatch with
`broadcast(..., queue_names=..., create_missing=True)`, which provisions every
requested exact queue inside the broadcast transaction. Taut can therefore
use current membership as its audience without preflight, sentinels,
per-recipient writes, delivery accounting, or private broker access.

## 1. Goal

Add a lightweight response operation across all supported surfaces:

- `taut message react MSG_ID REACTION`
- `TautClient.react_to_message(msg_id, reaction)`
- MCP `react_to_message`

A reaction is not a chat message, maintained annotation, counter, or mutable
piece of message state. It is one logical operation that writes one consumable
notification pointer to each current member of the source message's exact
thread, excluding the reacting member. Its allowed outbound values are loaded
from packaged defaults and may be replaced by the resolved project's
`.taut.toml`.

Reacting requires current visibility of an exact ordinary message and proves
that the actor observed it, so it monotonically advances the actor's existing
thread cursor through the target before notification fanout. One public
SimpleBroker exact-name broadcast writes the same pointer body to every
requested notification queue, including a name with no retained row. Its
transaction commits the full requested set or none. Taut treats a raised call
as best-effort and outcome-ambiguous, without retries, per-recipient loops,
rollback, or delivery accounting.
Recipient reads claim their individual rows and do not move any chat cursor.

## 2. Target Contract

This is the implementation contract. The superseded existing-inbox candidate
remains recorded in sections 14 and 16 for audit only.

### 2.1 Vocabulary and configuration

The packaged defaults add:

```toml
[reactions]
values = ["ack", "blocked"]
```

A storage-authoritative `.taut.toml` may replace the whole ordered list:

```toml
version = 1
backend = "sqlite"
target = ".taut.db"

[reactions]
values = ["ack", "done", "blocked"]
```

The exact configuration rules are:

- Missing `[reactions]` or missing `values` uses the packaged list.
- A present `values` list replaces rather than merges with packaged values.
- `values = []` deliberately disables outbound reactions for that project.
- Every value is a unique lowercase ASCII slug matching
  `^[a-z0-9][a-z0-9_-]{0,31}$`. Configured order is preserved for diagnostics.
  Taut does not lowercase, trim, sort, or silently deduplicate.
- Unknown keys remain ignored under [TAUT-3.2].
- This is a validated configured string vocabulary, not a Python `Enum`.
  A static enum would make project extension impossible.
- Invalid packaged defaults fail with the fixed
  `reaction configuration is unavailable`. Invalid local shape, item type,
  duplicate, or slug fails client construction with a concise diagnostic
  naming `.taut.toml` and `[reactions].values` but not echoing the invalid
  value.
- A `TautClient` snapshots the vocabulary once after resolving its target.
  Existing clients retain that tuple after a file edit; new clients see the
  edit. An MCP child therefore freezes it from workspace attachment until
  detach and reattach.
- A project-resolved `BrokerTarget` reads only its own `config_path`.
  `db_path=` and `TAUT_DB` are path-only selectors and use packaged reaction
  defaults; they do not inherit an unrelated current-directory
  `.taut.toml`. This deliberately differs from the CWD-relative,
  presentation-only `[terminal_text]` policy.
- `taut/_constants.py::load_config()` remains the SimpleBroker translation
  boundary. Reaction configuration belongs in a new private
  `taut/_reactions.py`; do not put Taut domain values into the broker mapping
  or reuse `taut.terminal`'s different discovery/cache contract.
- The local list is an **emission allowlist only**. An inbound structurally
  valid reaction is decoded and rendered even when the receiving client's
  current allowlist does not contain it. This is required for PostgreSQL peers
  and long-lived attachments with different configuration snapshots.

The first release has no separate vocabulary-discovery command or MCP tool.
Static CLI/MCP help cannot truthfully enumerate per-workspace dynamic values.
Packaged defaults are documented, and a syntactically valid disabled value
fails with `reaction must be one of: VALUE, ...` in configured order. An empty
list fails with `message reactions are disabled by project configuration`.
Adding proactive discovery through a future `message info` operation remains
an explicit product follow-up, not a hidden addition to this change.

### 2.2 Target and audience

- `msg_id` uses [TAUT-7.6]'s exact full 19-digit string validation. Suffixes,
  numbers, signs, whitespace, out-of-range values, and non-strings retain the
  same type/shape errors and validation-first side-effect floor.
- `reaction` must be a string. Non-string input raises
  `TypeError("reaction must be a string")`; a string outside the stable slug
  grammar raises
  `ValueError("reaction must match ^[a-z0-9][a-z0-9_-]{0,31}$")`; a valid slug
  outside the client's snapshot uses the configured-list or disabled error in
  section 2.1.
- Validation order is exact ID, reaction type/shape/allowlist, incomplete
  rename preflight, existing-member resolution, current-membership lookup,
  target policy, audience snapshot, cursor, fanout. Invalid ID or reaction
  performs no identity/activity, thread enumeration, queue peek, cursor, or
  notification write.
- Target lookup reuses the current pending-only exact locator and the same
  candidate set as `show_message`: the actor's current registered channel,
  subthread, and DM memberships. It does not rejoin a channel, implicitly join
  a child, inspect an unrelated DM, or search departed memberships.
- Only a decoded `kind == "message"` row with a stable `from_id` is reactable.
  Structural notices, foreign rows, absent or claimed rows, inaccessible
  threads, and unrelated DMs use the uniform
  `NotFoundError("message not found or not reactable: MSG_ID")`. No source
  body, author, participant, thread, or existence distinction reaches an
  adapter.
- Reacting to one's own ordinary message is allowed. The actor is still
  excluded from delivery.
- After target lookup, Taut snapshots
  `TautState.list_thread_members(target.thread)` once. This existing query
  defines the current exact-thread audience. The actor is removed.
- Channel recipients are current channel memberships.
- Subthread recipients are current child-thread memberships only. Parent-only
  members are not subscribers. A parent member becomes eligible only after an
  explicit read has created the existing implicit child membership; leaving
  the child removes eligibility.
- DM recipients are the intersection of current DM memberships and the two
  member IDs in validated DM registry metadata, minus the actor. Missing,
  malformed, non-distinct, or wrong-cardinality DM metadata fails closed with
  `NotFoundError("message not found or not reactable: MSG_ID")` and writes
  nothing. This preserves [IAN-5.2]'s confidentiality boundary if sidecar
  membership is corrupt.
- A nonempty snapshot is invocation-scoped. A recipient who leaves after the
  snapshot may receive one stale pointer; a join after the snapshot misses
  this event; later reactions use the later state. No send-time audience
  snapshot exists in Taut, and this change adds none.
- If exclusion leaves no recipient, raise
  `EmptyResultError("no reaction recipients")` before cursor advancement or
  notification writes. CLI exits 2 silently; MCP returns an empty typed
  reaction result with the content-free guidance defined below.

### 2.3 SimpleBroker dependency and layer boundary

SimpleBroker 5.6.1 exposes:

```python
broker.broadcast(
    message: str,
    *,
    pattern: str | None = None,
    queue_names: Sequence[str] | None = None,
    create_missing: bool = False,
) -> int
```

`pattern` and `queue_names` are mutually exclusive. `create_missing=True` is
valid only with `queue_names` and must be a strict boolean. The broker
materializes, validates, and deduplicates the requested names before mutation,
then atomically writes one identical ordinary message to every distinct name,
including a queue with no retained row, or writes none. Empty input returns
`0`; a successful call returns the distinct requested target count. The
default `create_missing=False` keeps the 5.6.0 existing-only behavior for
compatibility. Taut requires `simplebroker>=5.6.1` and
`simplebroker-pg>=3.3.1` where the PostgreSQL extra is installed.

Broadcasting to `notify.*` would over-deliver and leak direct-message or
subthread activity. Calling `Queue.write()` per member would lose the one-call
atomic selected-subset contract. Reaching into `BrokerCore`, runners, SQL, or
exact-ID import APIs remains a layer violation.

### 2.4 Seen state and best-effort broadcast

- A valid, nonempty-audience reaction proves actor observation. Taut calls the
  existing monotonic
  `advance_cursor(thread=..., member_id=..., seen_ts=message.ts)` before the
  first notification write.
- High-water semantics are identical to `message show`: reacting to a newer
  target marks it and every earlier/intervening row in the thread seen.
  Reacting at or below the cursor never regresses it.
- Cursor failure is fatal and emits no reaction row or success receipt.
- A concurrent actor leave after target/audience snapshot may make the cursor
  update affect zero rows while the already-authorized fanout still proceeds.
  This retains `show_message`'s accepted invocation-snapshot race and does not
  add a row-count contract to `advance_cursor`.
- Taut converts the audience snapshot to exact
  `notify.<member_id>` names and calls
  `open_broker(...).broadcast(
  body, queue_names=queue_names, create_missing=True)` once (or the released
  equivalent exact-name public operation). It never loops over `Queue.write()`,
  calls private broker internals, synthesizes IDs, or opens a sidecar
  transaction around broker work.
- SimpleBroker atomically commits the full requested inbox set or none,
  including names with no prior row.
- The broadcast is auxiliary and best-effort, matching Taut's existing
  notification posture. If it raises, Taut appends one
  `reaction notification broadcast failed: ERROR` warning and still returns
  the reaction operation receipt. Commit may have occurred before confirmation
  was lost, but the receipt makes no delivery claim. Taut does not retry above
  SimpleBroker, rewind the actor cursor, or downgrade the command to an error.
- The warning uses the existing notification-warning channel and the same
  exception-text behavior as other notification writes; this feature adds no
  recipient IDs or separate error-detail machinery. `--quiet` suppresses it;
  MCP returns it in the ordinary `warnings` array.
- Repeated successful calls are independent events and intentionally create
  duplicate consumable rows. There is no idempotency key, aggregate, count,
  toggle, replacement, deduplication, or undo.
- A target deleted or foreign-claimed after lookup may still produce a stale
  pointer. A notification already fetched by a reader may still render after
  source deletion. Neither race rolls back delivery.

### 2.5 Public value and notification payloads

Add frozen, slotted `MessageReaction`:

```python
@dataclass(frozen=True, slots=True)
class MessageReaction:
    thread: str
    message_ts: int
    reaction: str
    audience_count: int
```

`TautClient.react_to_message(msg_id: str, reaction: str) -> MessageReaction`
returns that operation receipt after the one best-effort broadcast attempt.
`audience_count` is the exact final recipient-set size after actor exclusion
and, for a DM, registry intersection. It equals `len(queue_names)`. It is not a
delivery, consumption, or read receipt. Recipient IDs are intentionally
absent.

Every recipient receives the same row body:

```json
{
  "type": "reaction",
  "actor_id": "m_wxyz1234wxyz1234wxyz1234wx",
  "actor_name": "claude",
  "thread": "general",
  "message_ts": 1837025672140161024,
  "reaction": "ack"
}
```

`reaction` is required for `type == "reaction"` and absent for mention,
`dm_started`, and reply. `matched` remains mention-only. Because one atomic
broadcast writes an identical body, reaction payloads omit recipient-specific
`to_id`; the receiving queue already supplies that routing. Public
`Notification.to_id` is `None` for reactions, and the existing JSON/MCP
notification field remains present as `null`. `Notification` gains
`reaction: str | None`; all notification JSON/MCP encoders include it only
when non-null.

The decoder validates an inbound reaction against the stable slug grammar, not
the receiver's emission list. Missing, non-string, or syntactically invalid
`reaction` makes the row `foreign` under the existing malformed-notification
contract. Extra fields remain ignored. The queue-row timestamp stays internal;
the public pointer continues to expose `message_ts`.

`peek_inbox()` remains observational. `inbox()` and watcher delivery claim one
recipient's row. Neither recipient path advances the source chat cursor.
Deleting the source leaves the reaction pointer byte-for-byte pending and
consumable.

Human notification rendering is:

```text
HH:MM ACTOR reacted REACTION to message MSG_ID in THREAD; inspect: taut message show MSG_ID
```

The renderer does not preflight the source. It always renders the pointer and
inspect action. If the source became stale or inaccessible, the later
`message show` command returns its ordinary content-free empty result. This
avoids a presentation-layer lookup that would still race with deletion and
would not improve correctness. Using a live action advances seen state by
design. This deliberately differs from mention reply-action preflight: `reply`
is a mutating operation whose dead-source failure is confusing, while
`message show` is a safe read with an established content-free empty result.

### 2.6 CLI and MCP surface

| Surface | Contract |
|---|---|
| CLI | `taut message react MSG_ID REACTION` |
| Python | `react_to_message(msg_id: str, reaction: str) -> MessageReaction` |
| MCP | `react_to_message(workspace, msg_id, reaction)` |
| Success record | new `reaction` receipt |
| Empty audience | CLI 2 / Python `EmptyResultError` / MCP typed empty reaction |
| Missing or ineligible target | CLI 2 / Python `NotFoundError` / MCP typed empty reaction |
| Invalid ID/reaction | CLI 1 / Python type or value error / MCP schema or core error |
| Broadcast failure | normal receipt plus one best-effort warning; cursor remains advanced |

CLI human success is:

```text
reacted REACTION to message MSG_ID in THREAD (AUDIENCE current recipients)
```

JSON emits exactly:

```json
{"thread":"general","message_ts":1837025672140161024,"reaction":"ack","audience_count":3}
```

`--quiet` suppresses the receipt and delivery warnings. `-t` has no special
effect because the receipt identifies its source. Root and subcommand
help describe the cursor effect, consumable fanout, duplicate-on-repeat risk,
and configured vocabulary without dynamically constructing a client during
help.

MCP adds `react_to_message`, bringing the fixed manifest from 17 to 18 tools.
Its input schema uses the exact-message string pattern and the stable reaction
slug pattern, not an `enum`, because one process may attach workspaces with
different snapshots. Core enforces the workspace allowlist.

Exact MCP description:

> Send one configured reaction to the current audience of an exact ordinary
> message, excluding this member. Validates against the workspace's
> attachment-time reaction vocabulary, advances this member's high-water
> cursor through the target, then attempts one atomic best-effort notification
> broadcast to every requested current-recipient inbox. Repeating may deliver
> duplicates.

Annotations are `readOnlyHint=false`, `destructiveHint=true`,
`idempotentHint=false`, and `openWorldHint=true`. The destructive hint names
the non-additive cursor change; the operation does not delete chat history.

The closed `reaction` result schema has exactly `thread`, `message_ts`,
`reaction`, and `audience_count`. The count describes the current non-actor
authorized recipient set after DM registry intersection and makes no delivery
claim. An empty result has this content-free guidance:

```json
{
  "action": "Verify the full 19-digit message id, current membership, and that another current thread member exists before retrying.",
  "code": "message_reaction_not_sent",
  "message": "No reactable message with a current recipient was found."
}
```

The wording deliberately merges absent, inaccessible, ineligible, and
zero-audience cases at the MCP edge. The Python exceptions remain distinct so
embedders can distinguish a visible valid target with no recipient.

Server instructions must say that reactions move the actor cursor, are
best-effort consumable pointers rather than maintained state, atomically reach
all requested inboxes or none at the broker boundary, and may duplicate after
an uncertain retry. `message_ts` must be preserved as decimal text before
reuse by JavaScript consumers.

No new MCP resource is added. Recipient child reactors observe the existing
notification queues and recompute `taut://notifications/current`; the sender's
post-command snapshot does not contain its outgoing reactions because self is
excluded.

## 3. Source Documents

Source specs:

- `docs/specs/01-development-documentation-operating-model.md` [DOM-5],
  [DOM-6], [DOM-10], [DOM-11], [DOM-15]
- `docs/specs/02-taut-core.md` [TAUT-3.2], [TAUT-4.3], [TAUT-6],
  [TAUT-7.1]–[TAUT-7.6], [TAUT-8.1]–[TAUT-8.3], [TAUT-8.6], [TAUT-9],
  [TAUT-10], [TAUT-11], [TAUT-12.1]
- `docs/specs/03-identity-addressing-notifications.md` [IAN-2.5],
  [IAN-5.2], [IAN-6.3]–[IAN-6.5], [IAN-7], [IAN-9], [IAN-10]
- `docs/specs/05-taut-mcp.md` [MCP-3], [MCP-5]–[MCP-7], [MCP-9]–[MCP-12]

Implementation context:

- `taut/defaults.toml`
- `pyproject.toml`
- new `taut/_reactions.py`
- `taut/client/_base.py`
- `taut/client/_messaging.py`
- `taut/client/_notifications.py`
- `taut/client/_codec.py`
- `taut/client/_models.py`, `taut/client/__init__.py`, `taut/__init__.py`
- `taut/state/__init__.py`, `taut/state/_sql.py`
- `taut/commands/message.py`, `taut/commands/_builtins.py`,
  `taut/commands/_rendering.py`
- `extensions/taut_mcp/taut_mcp/_tools.py`
- `extensions/taut_mcp/taut_mcp/_commands.py`
- `extensions/taut_mcp/taut_mcp/_workspace_reactor.py`
- `extensions/taut_mcp/taut_mcp/_connection_reactor.py`
- `extensions/taut_mcp/taut_mcp/server.py`
- `tests/test_project_config.py`, `tests/test_client.py`,
  `tests/test_shared_contract.py`, `tests/test_cli.py`,
  `tests/test_command_registry.py`, `tests/test_public_api.py`,
  `tests/test_lazy_imports.py`, `tests/test_architecture_boundaries.py`,
  `tests/test_watcher.py`
- `extensions/taut_mcp/tests/test_tools.py`
- `extensions/taut_mcp/tests/test_resource.py`
- `extensions/taut_mcp/tests/test_stdio_server.py`
- `extensions/taut_mcp/tests/test_pg_conformance.py`
- `docs/implementation/02-repository-map.md`
- `docs/implementation/04-taut-architecture.md`
- `docs/implementation/06-command-extensions.md`
- `docs/implementation/07-taut-mcp-architecture.md`
- `README.md`, `extensions/taut_mcp/README.md`, `CHANGELOG.md`

SimpleBroker released-contract context:

- `../simplebroker/AGENTS.md`
- `../simplebroker/README.md` broadcast and public cross-queue API sections
- `../simplebroker/simplebroker/__init__.py`
- `../simplebroker/simplebroker/_backend_plugins.py::BrokerConnection`
- `../simplebroker/simplebroker/db.py::open_broker`
- `../simplebroker/simplebroker/db.py::BrokerCore.broadcast`
- `../simplebroker/extensions/simplebroker_pg/`
- `../simplebroker/extensions/simplebroker_redis/simplebroker_redis/core.py`
- SQLite, PostgreSQL, Redis, public-surface, activity-wake, size, and atomicity
  broadcast tests

Process guidance:

- `AGENTS.md`
- `docs/agent-context/decision-hierarchy.md`
- `docs/agent-context/runbooks/writing-plans.md`
- `docs/agent-context/runbooks/writing-specs.md`
- `docs/agent-context/runbooks/hardening-plans.md`
- `docs/agent-context/runbooks/testing-patterns.md`
- `docs/agent-context/runbooks/adversarial-acceptance-probes.md`
- `docs/agent-context/runbooks/designing-agent-facing-interfaces.md`
- `docs/agent-context/runbooks/maintaining-traceability.md`
- `docs/agent-context/runbooks/review-loops-and-agent-bootstrap.md`

## 4. Spec Baseline and Promotion Strategy

- Spec baseline: commit `8509dc47efa5ab7e353169f4df1e92ef98ee329d`.
- The active specs are canonical. Their uncommitted reaction delta now encodes
  the released 5.6.1 full-requested-set contract and is the authority for
  implementation after the final review gate.
- Promotion strategy: **A, in-file requirement text before link claims**.
  The exact delta below is promoted into the three active specs, with Related
  Plans backlinks. Documentation gates and a stable diff digest are recorded
  before production-code edits. Implementation backlinks and mapping claims
  land with their corresponding code slice.
- Released SimpleBroker 5.6.1 supplies public
  `broadcast(message, queue_names=..., create_missing=True)`. It validates and
  deduplicates the exact requested set, provisions missing implicit queues,
  and atomically writes the full set or none.
- No Taut storage migration, new queue class, or sidecar table is required.
  Existing exact peek, current membership query, monotonic cursor, and
  notification queues remain sufficient.
- Dependency metadata is reconciled to `simplebroker>=5.6.1` and
  `simplebroker-pg>=3.3.1`. No editable-path or private-API coupling is
  permitted.
- If MCP ships in a separately versioned release, its minimum `taut`
  dependency must name the first core version exporting `MessageReaction`,
  `Notification.reaction`, and `react_to_message`.
- Promotion baseline: base commit
  `8509dc47efa5ab7e353169f4df1e92ef98ee329d` plus the three-spec diff whose
  SHA-256 is
  `bfcdea52ec1be4841f871132ff54668fc1f29320ae4e7a320064d78e4dd26759`.

## 5. Current Structure and Hidden Couplings

### 5.1 Exact lookup and cursor

`MessagingMixin.show_message()` already supplies the required target
visibility model and first-operation exact-ID validator.
`_locate_exact_message()` carries the located queue and decoded message.
`TautState.advance_cursor()` is monotonic and intentionally returns no affected
row count. Reuse these seams; do not fork another exact lookup or introduce a
per-message seen table.

Comprehension check: why must reaction lookup use current memberships like
show, while deletion scans all registered threads? Answer: reaction is a
response by a current viewer and broadcasts to current scope; deletion is an
author-owned cleanup operation explicitly allowed after leave.

### 5.2 Audience authority

`TautState.list_thread_members(thread)` is one ordered membership snapshot.
Subthread membership is exact: reply joins the replier; explicit
`read(child)` may implicitly join a parent member; parent membership alone is
not child subscription. DM registry `meta.members` is the independent
confidentiality guard and must intersect the membership result.

Comprehension check: why is a parent-channel member excluded from a child
reaction? Answer: the existing child membership row is Taut's subscriber
contract; broadening to the parent would invent a second, implicit subthread
scope and leak activity to users who never entered the child.

### 5.3 Cross-queue write ownership

`NotificationsMixin._write_notification()` is intentionally one-recipient
best-effort `Queue.write()`. It remains correct for mention, reply, and
`dm_started`, but it is the wrong layer for reaction fanout. A loop around it
would create partial delivery and duplicate SimpleBroker's cross-queue owner.

Reaction adds one narrowly named Taut helper that opens the public
backend-agnostic broker handle and calls the released all-requested-name
broadcast mode once. It may catch that one exception only to preserve Taut's
existing best-effort notification semantics and warning channel. It must not
inspect `BrokerConnection` internals, runners, SQL, backend names, or
timestamps.

### 5.4 Verified SimpleBroker boundary

Public SimpleBroker 5.6.1 exact broadcast with `create_missing=True` writes to
every requested name without preflight and owns queue establishment plus
atomicity. Taut passes one exact set derived from sidecar membership and does
not infer delivery from the return count. Real SimpleBroker tests own that
cross-backend contract; Taut tests own intended-audience-to-requested-name
mapping, cursor ordering, best-effort exception handling, and non-delivery
receipt semantics.

### 5.5 Configuration ownership

`_constants.load_config()` returns SimpleBroker settings after filtering and
translation. `terminal.py` independently finds CWD presentation policy and
caches by file stat. Reaction vocabulary instead belongs to the resolved
storage project and must be frozen per client. `BrokerTarget.config_path`
provides the exact project file for discovered and handed-off clients;
explicit string paths have no project config owner.

Opening `.taut.toml` for broker resolution and then for reaction parsing is not
an atomic filesystem snapshot. A concurrent edit may make target selection and
reaction values come from adjacent file versions. Taut freezes whatever valid
reaction document it reads at construction and makes no cross-read atomicity
claim.

### 5.6 MCP compatibility

The MCP manifest and output schemas are static, while configured vocabulary is
workspace-specific. Therefore the schema can enforce only stable slug syntax;
the child-owned client enforces the frozen allowlist.

Old core versions decode `type: "reaction"` as foreign. Old MCP encoders then
omit the useful raw content from their closed notification record. New
receivers must be deployed before operators rely on reactions in mixed-version
multi-host projects. The plan cannot make old software understand a new type.

MCP resource records omit the notification queue-row timestamp. Two identical
reactions pending together remain two array elements, but a consume-and-replace
race can produce byte-identical aggregate snapshots and suppress an update
hint. Resource hints are already coalescible and non-authoritative; the 0.5s
backstop and explicit resource reads remain the recovery. Adding
`notification_ts` to every notification schema is out of scope.

## 6. Promoted Spec Delta

Promotion strategy A has been applied to the governing 5.6.1 contract:

| Spec file | Sections touched | Governing delta |
|---|---|---|
| `docs/specs/02-taut-core.md` | [TAUT-3.2], [TAUT-3.4], new [TAUT-7.7], [TAUT-8.1]–[TAUT-8.3], [TAUT-10], [TAUT-11] | configured vocabulary, released SimpleBroker 5.6.1 call, full requested-set semantics, `audience_count`, warnings, CLI/Python contract, proof |
| `docs/specs/03-identity-addressing-notifications.md` | [IAN-7.1]–[IAN-7.4], [IAN-9], [IAN-10] | reaction payload, recipient-independent body, absent-inbox provisioning, independent consumption, edge cases |
| `docs/specs/05-taut-mcp.md` | [MCP-3], [MCP-5]–[MCP-7], [MCP-9]–[MCP-12] | frozen workspace config, tool 18, audience receipt, resource behavior, uncertain outcome, verification |

The cross-file contract is:

1. Taut derives one nonempty membership audience, advances the actor cursor,
   and makes one public atomic call with every exact non-actor inbox name.
2. SimpleBroker writes the identical body to every requested name, including a
   name with no retained row, or commits none.
3. `MessageReaction.audience_count` reports the final authorized recipient-set
   size after actor exclusion and DM registry intersection. It equals the
   number of exact requested queue names and never claims delivery. Taut does
   not expose the broker return count.
4. A raised broadcast remains best-effort and warning-producing. Taut does not
   retry, rewind, or add nullable/partial delivery state.
5. Recipient bodies remain identical, omit `to_id`, and are independently
   consumed from their own queues.
6. Human rendering does not preflight source existence. A stale advertised
   `message show` action may cleanly return empty. Mention preflight remains
   because its advertised `reply` action mutates.

## 7. Invariants and Constraints

### 7.1 Must change

- Add the configured outbound vocabulary and frozen client snapshot.
- Add exact-message reaction policy, actor cursor movement, and current-audience
  targeted broadcast.
- Add `MessageReaction` and `Notification.reaction`.
- Require SimpleBroker 5.6.1, which writes to all requested exact names when
  `create_missing=True`.
- Extend nested CLI, fixed MCP manifest, schemas, instructions, resource
  encoding, tests, and docs.
- Raise the fixed MCP tool count from 17 to 18 everywhere it is enumerable.

### 7.2 Must not change

- No chat row is written for a reaction.
- No message envelope, sidecar schema, thread registry, membership model, DM
  naming, notification queue naming, or broker storage format changes.
- No stored message body is edited and no reaction count is maintained.
- No recipient ID appears in the sender receipt or broadcast warning.
- No current parent membership is promoted into child membership.
- No DM audience trusts sidecar membership without registry intersection.
- No notification claim advances a chat cursor.
- No receiver allowlist rejects another peer's structurally valid reaction.
- Existing mention, reply, and `dm_started` best-effort behavior stays intact.
- Existing `message show` and `message delete` behavior, errors, outputs, and
  lookup scopes stay intact.
- No dynamic CLI plugin command or MCP tool reflection is introduced.
- No new package dependency is added. Only the existing SimpleBroker floor
  changes.

### 7.3 Anti-mocking rules

- Core contract tests use real `TautClient`, `SqlSidecarTautState`,
  SimpleBroker queues, exact lookup, cursor SQL, and per-member notification
  queues.
- SQLite and PostgreSQL run the same shared behavior contract.
- DM tests use real registry metadata and memberships.
- Taut fault injection may replace only the one public
  all-requested-name broadcast call to prove its best-effort exception path.
  It must
  not fake audience selection, cursor state, decoding, or receipt construction.
- Atomic target-set proof belongs to SimpleBroker's real SQLite, PostgreSQL,
  and Redis backend suites. A Taut mock that simulates per-recipient outcomes
  cannot prove that contract.
- CLI tests run the real parser/dispatcher and renderers.
- MCP tests run the fixed manifest, child command path, canonical encoders, and
  real attached-workspace/resource path. A schema snapshot alone is not
  delivery proof.
- Concurrency tests use barriers around the real membership/source boundary;
  sleeps are not proof.

## 8. Dependency-Ordered Implementation Tasks

The upstream dependency and spec-promotion prerequisites are complete.
Production implementation may begin after the final plan review has no
unresolved blocker.

### Upstream prerequisite: exact-name broadcast semantics (completed 2026-07-28)

Owner: SimpleBroker maintainer under that repository's Class 4+ plan and
release rules.

Boundary: additive public broadcast selection, first-party backend protocol,
SQLite/PostgreSQL/Redis implementations, tests, README/CHANGELOG, and release.
No Taut membership policy belongs in SimpleBroker.

Released public operation:

```python
broker.broadcast(
    message,
    queue_names=queue_names,
    create_missing=True,
)
```

`create_missing=False` preserves the released 5.6.0 selector. In 5.6.1 the
strict boolean keyword is valid only with `queue_names`. When true, the broker
validates and deduplicates the requested names before mutation, then
atomically writes one copy to every requested name; the message itself
establishes a previously absent implicit queue. It returns the full distinct
target count.

Actions:

1. SimpleBroker planned and reviewed the additive contract, including its
   direct-backend compatibility/version handshake.
2. Its real SQLite, PostgreSQL, and Redis suites prove all requested names,
   including absent names, receive one row atomically.
3. Its contract tests cover duplicate/empty/invalid names, transaction
   rollback, activity wake, retry snapshot, and concurrent queue deletion.
4. Coordinated core 5.6.1 and PostgreSQL/Redis backend 3.3.1 releases exist.
5. Taut's core/PostgreSQL floors are raised and the installed public signature
   and absent-queue behavior are probed.
6. Keep Taut on one public call. Reject private `BrokerCore`, exact-ID import
   APIs, broad `notify.*` patterns, sentinels, existence preflight, and
   per-recipient write loops.

Minimum downstream acceptance probe after release:

```bash
uv run python -c 'import inspect, tempfile; from pathlib import Path; from simplebroker import open_broker; d=tempfile.TemporaryDirectory(); cm=open_broker(Path(d.name)/"probe.db"); b=cm.__enter__(); assert "create_missing" in inspect.signature(b.broadcast).parameters; cm.__exit__(None, None, None); d.cleanup()'
uv run --extra dev pytest tests/test_client.py tests/test_shared_contract.py -q
```

The probe must inspect the returned broker surface, not the `open_broker()`
factory signature. The observed results are in section 17.

### Spec-promotion slice: make one governing contract (completed 2026-07-28)

Owner: spec/core implementer.

Boundary: plan and spec files only.

Actions:

1. Apply section 6 to the three active specs.
2. Add Related Plans backlinks and keep this plan in the active index.
3. Update spec summaries/indexes only where existing text becomes false.
4. Run docs references and `git diff --check`.
5. Record the promotion baseline identifier before code cites the new sections.

Verification:

```bash
uv run --extra dev pytest tests/test_docs_references.py -q -n0
git diff --check
```

Stop gate: do not start code if review leaves audience, best-effort broadcast
failure, config ownership, receiver compatibility, or MCP empty-result wording
ambiguous.

### Slice 1: Add receive-side compatibility first

Owner: notification/core and MCP adapter implementer.

Boundary: public notification model/decoder/renderers/resource encoders and
their tests; no reaction emission yet.

Actions:

1. Add optional `Notification.reaction` and inbound `type: "reaction"`
   structural decoding.
2. Add CLI human/JSON and watcher rendering without source preflight; prove a
   stale pointer renders safely and its later `message show` action returns
   empty.
3. Extend both MCP notification encoders and the closed notification schema.
4. Prove configured-list independence with a structurally valid value that is
   not in the receiver's defaults.
5. Prove malformed reaction fields fall back to foreign without crashing.

Verification:

```bash
uv run --extra dev pytest tests/test_client.py tests/test_cli.py tests/test_watcher.py -q
uv run --directory extensions/taut_mcp --extra dev pytest \
  tests/test_tools.py tests/test_resource.py -q
```

Review gate: confirm no receive path imports or consults outbound configuration
and no renderer moves a recipient cursor merely to build an action.

### Slice 2: Add and freeze reaction configuration

Owner: core configuration implementer.

Boundary: `taut/defaults.toml`, new `taut/_reactions.py`,
`taut/client/_base.py`, focused config/public tests.

Actions:

1. Load and validate packaged values with the fixed packaged-failure message.
2. Resolve a local override only through copied `BrokerTarget.config_path`.
3. Snapshot an immutable ordered tuple after target resolution.
4. Preserve path-only explicit target behavior and unknown-key tolerance.
5. Add tests for missing/replace/empty/invalid/duplicate/unknown/frozen cases,
   handed-off targets, explicit paths, ignored alternate config files, and
   packaged artifact presence.
6. Map invalid MCP workspace config to the fixed configuration-unavailable
   attachment error.

Verification:

```bash
uv run --extra dev pytest tests/test_project_config.py tests/test_public_api.py \
  tests/test_lazy_imports.py tests/test_architecture_boundaries.py -q
uv run --directory extensions/taut_mcp --extra dev pytest \
  tests/test_resource.py tests/test_stdio_server.py -q
```

Stop gate: if resolving the correct config requires duplicating backend target
search or makes explicit `db_path` inherit CWD policy, stop and revise the
boundary rather than adding fallback discovery.

### Slice 3: Add red core contracts and implement reaction emission

Owner: core messaging implementer.

Boundary: public receipt/export, message method, one public SimpleBroker
targeted-broadcast call, notification warning reporting, and shared Taut
backend tests; no CLI/MCP tool yet.

Actions:

1. Add failing tests for every input, audience, cursor, broadcast, receipt,
   error, race, and stale-pointer branch in section 9.
2. Add frozen slotted `MessageReaction` and public lazy exports.
3. Implement `react_to_message` by reusing exact validation/locator and current
   membership candidates.
4. Snapshot `list_thread_members`, exclude actor, and apply the DM metadata
   intersection.
5. Advance the actor cursor before broadcast.
6. Encode one recipient-independent reaction body, convert the snapshot to
   distinct exact `notify.<member_id>` names, and call the public
   all-requested-name broadcast mode once.
7. Own that call with one invocation-scoped
   `with open_broker(self.target, config=self.config) as broker:` context,
   matching the existing cross-queue pattern in `taut/client/_threads.py`.
   Exiting the context releases only that broker handle; do not cache it on the
   client or close the client's existing queue handles.
8. Return `audience_count = len(queue_names)` from the final authorized
   recipient set after actor exclusion and DM registry intersection; ignore
   the broker count. On exception, append one ordinary failure warning and
   return the same receipt. Do not retry, rewind, preflight queue existence,
   or add per-recipient result state.
9. Preserve existing one-recipient notification behavior unchanged and run
   shared Taut contracts on SQLite and PostgreSQL.

Verification:

```bash
uv run --extra dev pytest tests/test_client.py tests/test_shared_contract.py \
  tests/test_public_api.py -q
bin/pytest-pg tests/test_shared_contract.py
```

Review gate: inspect real state to confirm no chat row, annotation, membership,
or new table exists; verify actor exclusion, child exactness, DM fail-closed
scope, validation ordering, one public broadcast call, and best-effort
exception handling. Reject private SimpleBroker access, per-recipient write
loops, retry/rollback logic, or any delivery-accounting surface.

### Slice 4: Extend the nested CLI noun

Owner: CLI implementer.

Boundary: `taut/commands/message.py`, `_builtins.py`, `_rendering.py`, CLI and
command-registry tests.

Actions:

1. Add required `react MSG_ID REACTION` parsing without dynamic argparse
   choices or eager client construction during help.
2. Add receipt human/JSON rendering and shared notification warning output.
3. Map invalid/error/empty outcomes to 1/2 exactly and keep `--quiet`/`-t`
   behavior.
4. Update root and nested help while preserving show/delete grammar and lazy
   ownership of the `message` namespace.
5. Apply CLI adversarial option/arity probes.

Verification:

```bash
uv run --extra dev pytest tests/test_cli.py tests/test_command_registry.py \
  tests/test_architecture_boundaries.py -q
```

Review gate: check both help owners, stdout/stderr separation, no dynamic config
read on help, exact JSON shape, and no regression to show/delete.

### Slice 5: Add the fixed MCP tool

Owner: MCP implementer.

Boundary: fixed manifest, command adapter, result/notification schemas,
workspace config mapping, server instructions, extension tests/docs.

Actions:

1. Add `react_to_message` as tool 18 with exact description and annotations.
2. Add stable input patterns, direct public-client dispatch, `MessageReaction`
   command union support, both record-type maps, and the closed result schema.
3. Merge not-found/not-reactable/no-recipient into the exact typed empty
   guidance; preserve invalid input as `isError`; return a broadcast exception
   as the normal `audience_count` success record plus warning.
4. Extend resource records and canonical text/structured parity.
5. Update cancellation/uncertain-retry teaching and exact tool-count tests.
6. Prove two attached workspaces keep independent frozen vocabularies.
7. Update the extension's minimum core dependency only when the repository
   owner selects the first shipping version; otherwise record it as release
   preparation debt without inventing a version.

Verification:

```bash
uv run --directory extensions/taut_mcp --extra dev pytest -q
```

Review gate: inspect the actual child path and recipient resource, not only
schema builders. Confirm no enum, no recipient IDs, correct cursor annotation,
config-unavailable mapping, and no automatic retry.

### Slice 6: Reconcile docs, traceability, and full evidence

Owner: implementing engineer; completed-work review by a different model
family.

Boundary: public/implementation docs, changelog, mapping backlinks, plan
evidence, full gates.

Actions:

1. Update repository map and core, command, and MCP implementation docs with
   why/boundary/tradeoffs rather than code narration.
2. Add CLI, Python, config, notification, and MCP examples to README files.
3. Add an Unreleased changelog entry without choosing a version or releasing.
4. Reconcile spec implementation links and reciprocal code/doc references.
5. Run adversarial probes and full core/PG/MCP/type/lint/doc gates.
6. Run independent completed-work review on the full diff and evidence.
7. Update plan status, deviation log, hardening evidence, review dispositions,
   and promotion baseline.
8. Evaluate whether implementation exposed a reusable lesson; add one only if
   it generalizes beyond reactions.

Minimum final commands:

```bash
uv run --extra dev pytest -q
bin/pytest-pg
uv run --directory extensions/taut_mcp --extra dev pytest -q
uv run --extra dev ruff check .
uv run --extra dev ruff format --check .
uv run --extra dev mypy taut tests
uv run --directory extensions/taut_mcp --extra dev mypy taut_mcp tests
uv run --extra dev pytest tests/test_docs_references.py -q -n0
git diff --check
```

Use newer canonical aggregate commands if repository guidance changes before
implementation, and record the exact command plus observed result.

## 9. Test Diagram and Adversarial Acceptance Probes

| Flow or branch | Required firing proof |
|---|---|
| ID validation | valid full string proceeds; suffix, letters, signs, spaces, 18/20 digits, int64 overflow, `int`, `bool`, and `None` fail before identity/activity/peek/cursor/write |
| Reaction input | string type, stable grammar, allowed, disabled list, and ordered allowed-list error each fire; invalid input has no domain side effect |
| Config source | packaged default; missing table/key; replacement; empty; wrong table/list/item; duplicate; invalid slug; unknown key; ignored alternate files |
| Config lifetime | current client remains frozen after edit; new client sees edit; MCP detach/reattach refreshes; two workspaces remain independent |
| Config target | project/handoff reads exact `BrokerTarget.config_path`; explicit DB ignores unrelated CWD config |
| Target kinds | ordinary message succeeds; notice, foreign, claimed-before-lookup, absent, inaccessible, and unrelated DM share uniform not-reactable output |
| Current visibility | joined channel/child/DM succeeds; departed/unjoined target fails with no implicit membership |
| Channel audience | every current member except actor receives one row; outsider and actor receive none; self-authored source remains allowed |
| Dynamic audience | join after source but before reaction receives; leave before reaction does not; join/leave after snapshot affects only later reactions |
| Subthread audience | current child members only; parent-only member excluded; explicit child read makes eligible; later child leave removes eligibility |
| DM audience | only current validated counterpart receives; outsider/corrupt extra membership excluded; `audience_count` equals the post-intersection requested-name count; missing/malformed/duplicate/wrong-cardinality metadata emits nothing |
| Empty audience | typed empty before cursor and writes |
| Cursor relations | below/equal does not regress; ahead advances through target and marks intervening rows seen; chat row remains pending |
| Cursor failure | deterministic sidecar failure emits no reaction or success |
| Actor-leave race | leave after snapshot may allow already-authorized fanout with zero-row cursor update |
| Public primitive | exact unique queue names and one identical body reach the public broker handle in one call; actor is absent; Taut uses no private/import API or per-recipient write loop |
| Selector safety | the one broadcast call always supplies keyword-only `queue_names`, the released all-requested-name mode, and never `pattern`; a probe fails if selector/mode omission could broadcast broadly or skip absent inboxes |
| Exact-name full broadcast | real broker paths prove one call with unique requested names; never-used, post-vacuum, and existing inboxes all receive the identical body atomically |
| No delivery accounting | receipt contains the intended `audience_count`; broker count is not exposed; there is no normal-shortfall warning or nullable delivery state |
| Best-effort broadcast failure | a forced pre-commit public-call exception leaves the cursor advanced, returns the normal `audience_count` receipt, writes no rows, emits one warning, and causes no Taut retry; an outcome-ambiguous stub proves Taut still does not retry |
| Repeats | two calls produce two independently consumable rows; no dedup/toggle/count |
| Target race | deterministic delete/claim after lookup may leave a stale reaction pointer; no rollback |
| Codec | valid/default and valid-not-locally-configured values decode; missing/non-string/invalid slug becomes foreign; extra fields ignored |
| Inbox/peek/watch | peek repeats without claim/activity/cursor; inbox/watch claims once for one member; other members' rows remain |
| Stale action | source deletion leaves the byte-identical consumable pointer and human rendering unchanged; the later `message show` action cleanly returns empty |
| CLI parsing | nested help, missing/extra args, literal `--`, option-looking reaction, root globals before/after noun, human/JSON `audience_count`, quiet warnings, exit 0/1/2 |
| Python surface | exact signature, frozen/slotted receipt, lazy public exports, no eager optional imports |
| MCP manifest | exactly 18 tools; stable patterns not enum; exact description/annotations; both maps/union/schemas agree |
| MCP execution | direct public method call; typed success/empty/error; best-effort warning remains success; canonical parity; cursor and recipient rows verified |
| MCP resource | recipient wake shows reaction; sender snapshot does not; inbox consumes; duplicates remain ordered; different receiver vocabulary decodes |
| MCP cancellation | pre-start prevents every side effect; post-start lost result may leave the cursor and either all or no recipient rows; no auto-retry |
| Backends | shared channel/subthread/DM, cursor, per-member claim, stale pointer, and config snapshot proof on real SQLite and PostgreSQL |

Every enumerable config rule, output field, error class, notification type
branch, audience class, cursor relation, annotation, and listed race requires a
firing test. Table-driven tests are preferred when failures stay legible.

## 10. Failure Modes and Recovery Registry

| Failure | Observable result | State after failure | Recovery |
|---|---|---|---|
| Invalid packaged config | fixed startup error | no client/domain work | repair package; do not fall back |
| Invalid project reaction config | concise startup/attachment configuration error | no ready client | repair `.taut.toml`; construct or reattach |
| Disabled or unknown outbound value | value error / CLI 1 / MCP `isError` | no identity/activity/lookup/cursor/write | choose a listed configured value or edit config and restart |
| Malformed exact ID or slug | validation/schema error | no dispatch-side domain effect | supply exact ID and stable slug |
| Missing/ineligible target | not found / CLI 2 / MCP typed empty | ordinary member resolution may refresh activity; no cursor/fanout | verify ID and current membership |
| Empty audience | empty result / CLI 2 / MCP typed empty | no cursor/fanout | wait for another current member or use another thread |
| Cursor write fails | error | no reaction row; source unchanged | repair sidecar/backend and retry |
| Targeted broadcast raises | normal `audience_count` receipt plus one warning | cursor advanced; all recipient rows may be absent or may have committed before confirmation was lost | do not blind-retry; inspect state or accept possible duplicate |
| Response/cancellation lost after start | outcome unknown | cursor advanced or unchanged; all requested recipient rows are present or all absent at the broker boundary | inspect inbox/state; do not assume retry safety |
| Recipient leaves after snapshot | may receive one stale pointer | no membership restoration | consume/ignore; later fanout uses new scope |
| Recipient joins after snapshot | misses current event | no backfill | later reactions include them |
| Source deleted/claimed after lookup | stale pointer may exist | notification remains consumable | render normally; later `message show` may return empty |
| Receiver config omits value | normal decoded reaction | no local allowlist mutation | consume normally |
| Old receiver version | degrades to foreign; old MCP may lose useful payload | row may be consumed without reaction UX | upgrade receivers before enabling use |
| Identical MCP consume/replace snapshot | update edge may coalesce | resource read/backstop remains authoritative | reread resource or consume inbox |

## 11. Hardening Checklist

Plan-design checks:

- [x] Public contracts, exact defaults, and non-goals are explicit.
- [x] The actor, target, exact-thread audience, DM confidentiality guard, and
  recipient exclusion are explicit.
- [x] Broker/sidecar/config/MCP boundaries and accepted races are explicit.
- [x] Validation/cursor failures, empty results, and best-effort broadcast
  failures are distinct.
- [x] Cursor high-water effects and ordering precede fanout.
- [x] One notification queue per recipient prevents claim stealing.
- [x] Anti-mocking rules require real SQLite and PostgreSQL.
- [x] No storage migration or new package dependency is required; the existing
  SimpleBroker floor must rise.
- [x] Receiver compatibility is sequenced before emission.
- [x] Dynamic-vocabulary discoverability is named as a first-release limit.
- [x] Stop-and-re-evaluate gates exist for config ownership, DM scope, fanout
  truth, and MCP behavior.
- [x] The public SimpleBroker 5.6.1 operation covers every requested
  membership-derived inbox, including a never-used or post-vacuum inbox.
- [x] Post-deploy signals are defined below.

Rollback and rollout:

- Roll out decoder/model/rendering/resource support before operators begin
  sending reactions. In a coordinated single release, upgrade receiving
  clients and MCP servers before enabling agent workflows that invoke react.
- Old receivers fail soft as foreign notifications, but old MCP adapters may
  omit the useful payload. This is degraded delivery, not a crash or storage
  corruption, and is not acceptable as the intended steady state.
- Rollback requires no schema downgrade. Reverting code/spec/config stops new
  emission, but pending reaction rows remain. New receivers can consume them;
  old receivers treat them as foreign. Reinstalling a compatible decoder is
  the only way to recover their typed meaning.
- A config rollback may set `values = []` for newly constructed clients.
  Existing clients and MCP attachments retain their snapshot until restart or
  detach, so operational rollback must recycle them.
- Consumed notification rows cannot be restored. Cursor advancement cannot be
  selectively rewound without making later seen history unread. A committed
  targeted broadcast cannot be recalled. These are the one-way doors.
- Release/tag/publication is outside this plan. Version and dependency-floor
  changes occur only with repository-owner direction.

Post-deploy success signals:

- reaction success receipts have `audience_count >= 1` and make no delivery
  claim;
- broadcast-failure warnings remain rare and contain no Taut-added recipient
  data;
- SimpleBroker atomicity probes observe no partial commit across the full
  requested set, including initially absent names;
- no reaction recipient is outside current exact-thread/validated-DM scope;
- actor cursors never regress and recipient cursors do not move on inbox;
- reaction notifications are claimed once per member and source rows remain;
- MCP resource updates or backstop reads expose typed reaction fields;
- malformed/foreign notification rates do not rise after receiver-first
  rollout;
- no notification warning or attachment error exposes recipient IDs, tokens,
  paths, DSNs, or message bodies.

Implementation evidence gates remain unchecked until execution:

- [x] Promoted spec baseline recorded and reviewed.
- [x] Red-green evidence recorded for every slice.
- [x] Every config rule and error/output field has a firing test.
- [x] Real SQLite and PostgreSQL shared contracts pass.
- [x] Deterministic audience/source/broadcast-failure races pass.
- [x] CLI and MCP exact surface snapshots pass.
- [x] Full typing, lint, docs, and package gates pass.
- [x] Independent completed-work review has no unresolved blocker.

## 12. Out of Scope

- Reaction counts, aggregation, annotation storage, message-body mutation, or
  a new message kind.
- Toggle, remove, edit, undo, recall, deduplication, or idempotency keys.
- Emoji or arbitrary Unicode reaction values in the first contract.
- Per-device notification fanout or acknowledgements.
- Historical send-time audience storage or backfill to later members.
- Broadening child scope to parent-channel membership.
- Reacting to notices, foreign rows, or deleted/claimed messages discovered
  before lookup.
- Admin/moderator policy or a stronger authorization boundary.
- New notification queue names, state tables, migrations, broker APIs, or
  sentinel rows to force empty inbox existence.
- A new MCP resource or notification queue timestamp in public records.
- A proactive vocabulary-discovery tool. A future `message info` design may
  expose it explicitly.
- Dynamic argparse or MCP schema enums.
- Release, deployment, tag, or publication work.

## 13. Independent Review Loop

### Plan review

- Reviewer: a different model family invoked read-only with bare `claude -p`,
  per repository-owner direction. Allow up to 15 minutes.
- Reviewer reads this plan, its `## Promoted Spec Delta`, cited spec sections,
  current message/config/state/notification code, CLI noun, fixed MCP
  manifest/result/resource code, and test ownership.
- Required challenge areas: configured-vocabulary ownership and discovery,
  current versus historical audience, exact child scope, DM confidentiality,
  cursor/broadcast ordering, atomicity versus best effort, duplicate semantics,
  receiver config independence, old-version rollout, MCP annotations/schema,
  enumerable test completeness, layer violations, and machinery that does not
  materially improve correctness or usability. It must specifically verify
  that all three specs use the 5.6.1 full-requested-set primitive and do not
  retain the superseded nullable delivery-accounting surface.
- Verdict vocabulary: `APPROVED`, `APPROVED WITH CONDITIONS`, or `BLOCKED`.
- Every finding is incorporated or answered in section 16 before the plan is
  ready for spec promotion.

### Slice and completed-work review

- Run independent review after spec promotion, receive/config compatibility,
  core fanout, adapter completion, and the final diff.
- Each reviewer receives the current plan, promoted spec, complete slice diff,
  red/green commands, and observed results.
- Review both tests and production code. Schema-only or unit-double-only review
  cannot approve a delivery slice.
- Completion requires no unresolved blocker on enumerable contracts,
  real-backend proof, docs alignment, rollout/rollback, or unrelated edits.

## 14. Deviation Log

| Spec ref | Planned behavior | Actual behavior | Rationale | Spec proposal |
|---|---|---|---|---|
| [TAUT-3.4], [TAUT-7.7], [IAN-7.3], [MCP-6] | Proposed sibling `broadcast_to_queues()` created every requested inbox and returned the full target count. | Released SimpleBroker 5.6 uses `broadcast(..., queue_names=...)`, selects only existing queues, ignores missing names, and returns the committed selected count. | Align Taut with the published dependency rather than a superseded proposed API. Silent partial delivery would make the old `audience_count` misleading. | Promoted existing-subset atomicity, integer-or-null `delivered_count`, count-only shortfall warning, and no inbox creation into the three active specs. |
| [TAUT-3.4], [TAUT-7.7], [IAN-7.3], [MCP-6] re-review | Accept the promoted existing-inbox subset and expose its shortfall. | A current Taut member commonly has no broker inbox row; vacuum also removes the existence marker. | Existing-only reach contradicts membership-defined audience and makes delivery depend on unrelated retention. The accounting surface is compensating complexity. | Block implementation; add a public all-requested-name atomic mode upstream, then restore `audience_count` and remove normal-shortfall/null-delivery surface branches before repromotion. |
| [TAUT-3.4], [TAUT-7.7], [IAN-7.3], [MCP-6] resolution | Wait for a public full-requested-set primitive rather than emulate it in Taut. | SimpleBroker 5.6.1 adds `broadcast(..., queue_names=..., create_missing=True)` and backend API v5; PostgreSQL and Redis extensions 3.3.1 implement the same contract. | The primitive restores membership-defined reach without sentinels, preflight, per-recipient loops, delivery accounting, or private access. | Reconciled the three active specs to `audience_count`, one exception warning, and one full-requested-set public call. |

## 15. Fresh-Eyes Review

A zero-context implementer should be able to answer:

1. Which config file controls outbound values, and when does an edit take
   effect?
2. Why does a receiver accept a valid value absent from its local list?
3. Which exact members receive a channel, child, or DM reaction?
4. Which high-water state moves, and what extra messages become seen?
5. What happens for an empty audience, a missing requested inbox, a committed
   selected-subset broadcast, and a broadcast exception?
6. Why is a reaction receipt not a notification or maintained annotation?
7. Which source and membership races are accepted?
8. Why must receiver support precede emitter use in a mixed-version project?
9. Which tests must use real SQLite/PostgreSQL paths?
10. How do CLI, Python, MCP result, and recipient notification shapes differ?

Fresh-eyes reviewers must flag any requirement without an owner, boundary,
verification path, or required action, plus any test that could pass while
using a shared queue, parent scope, or receiver-side allowlist.

## 16. Review Findings and Dispositions

Bare `claude -p` read-only review completed 2026-07-28 with verdict
`APPROVED WITH CONDITIONS`. It verified the released SimpleBroker 5.6
signature, existing-only selection, missing-name behavior, return count, and
selected-subset atomicity directly against the sibling source.

Dispositions:

1. MCP empty-result guidance differed between plan and spec. Fixed both to the
   exact full-19-digit/current-thread-member wording in [MCP-6].
2. The plan and [MCP-5] descriptions differed on attachment-time vocabulary
   validation. Fixed [MCP-5] to the plan's exact description.
3. Section 2.3 abbreviated the signature. Added `pattern` so the mutually
   exclusive released form is explicit.
4. Human output did not enumerate `delivered_count=None`. Added exact
   `delivery unknown` rendering, preserved confirmed zero as
   `0 existing inboxes`, and added a firing-test row.
5. Selector-free broadcast could target every existing queue. Added a named
   selector-safety invariant and probe requiring keyword-only `queue_names`
   and forbidding `pattern`.

That review's conditions were incorporated, but its readiness verdict is
superseded by the new API/application-boundary re-review below.

### 2026-07-28 SimpleBroker 5.6 application-boundary re-review

Verdict: **BLOCKED**.

1. **P1: the selected broker set is not the Taut audience.** Taut registers a
   notification thread only in sidecar state
   (`taut/client/_identity.py::_ensure_notification_thread`); it writes no
   SimpleBroker row. SimpleBroker states that queues are implicit, exist only
   while a row remains, and disappear when vacuum removes claimed rows
   (`../simplebroker/README.md`, Queue Metadata). Its 5.6 exact selector
   explicitly ignores missing names ([BCAST-1]). Therefore a current Taut
   member with a never-used or clean inbox is omitted. The smallest correction
   is the additive upstream mode in section 8.
2. **P1: the blocked spec contradicts the stated audience contract.** Section
   1 promises one pointer to each current exact-thread member minus the actor,
   while the promoted [TAUT-7.7]/[IAN-7.3] text accepts a maintenance-dependent
   subset. “Best effort” does not repair this mismatch: it permits a failed
   attempt, not a deterministic eligibility rule based on stale broker rows.
3. **P2: delivery accounting is compensating complexity.** Nullable
   `delivered_count`, N-of-M warnings, distinct human strings, MCP union
   handling, cancellation text, and the associated test matrix exist only
   because the primitive skips ordinary recipients. They do not improve the
   intended reaction model. With a full requested-name atomic call, restore a
   simple non-delivery receipt (`audience_count`), retain one exception warning,
   and remove the normal-shortfall branches.
4. **P1: no Taut-side workaround is acceptable.** Existence preflight races
   with vacuum/deletion; sentinel rows invent maintained state; broad
   `notify.*` broadcast leaks scope; per-recipient writes lose the requested
   transaction; private/import APIs violate [TAUT-3.4]. The fix belongs in the
   SimpleBroker public multi-queue owner.
5. **P2: source preflight in the renderer is needless and still racy.** The
   blocked spec required a cursor-neutral lookup before advertising
   `message show`. Deletion can occur immediately after that check, and the
   command already has a safe content-free empty result. The corrected target
   contract always renders the pointer/action and lets a stale invocation fail
   normally, avoiding a presentation-to-domain lookup seam.

Concrete probes:

- A newly joined Taut member had a real `general` membership and
  `inbox.exists() == False`.
- SimpleBroker 5.6 returned `0` for a never-used exact inbox, `1` while an
  inbox row existed, and `0` again after the rows were claimed and vacuumed.
- Focused SimpleBroker exact-broadcast suites passed on SQLite, PostgreSQL, and
  Redis. This confirms that the implementation matches its own existing-only
  contract; the blocker is downstream semantic fit, not an atomicity defect.

The first bare `claude -p` re-review hit its usage limit before returning a
verdict. The required retry completed after reset with
`APPROVED WITH CONDITIONS`, meaning the blocked analysis and upstream stop gate
are correct, not that Taut implementation may begin.

Cross-model conditions and dispositions:

1. **P2: the downstream probe inspected the `open_broker` factory rather than
   the returned broadcast surface. Accepted.** Section 8 now asserts the
   released operation's signature on a real temporary handle and names the
   separately-named-method alternative.
2. **P3: the worktree already contains 5.6/3.3 dependency floors while the plan
   says to wait for the corrected release. Accepted.** Section 4 records these
   as inert intermediate reconciliation, requires the final floors to rise,
   and explicitly requires replacement of [TAUT-3.4]'s existing-only rationale.
3. **P3: removing only reaction preflight lacked a rationale against mention
   precedent. Accepted.** Sections 2.5 and 6 distinguish safe, empty-returning
   `message show` from the mutating mention `reply` action and name the exact
   reaction-preflight sentence to remove.
4. **P3: the broker-handle lifecycle was not pinned. Accepted.** Slice 3 now
   requires one invocation-scoped public context manager, no client cache, and
   no closure of existing queue handles.

The reviewer independently confirmed the 5.6 existing-only implementation,
Taut's sidecar-only notification registration, the membership/audience
contradiction, the inconsistency with first-time mention/reply/DM notification
creation, the upstream layer ownership, DM/subthread scope, cursor order,
configuration boundary, and removal of compensating delivery/preflight
machinery.

### 2026-07-28 SimpleBroker 5.6.1 resolution re-review

The upstream blocker is resolved:

1. SimpleBroker commit `ddb18f3` adds exact broadcast queue provisioning, and
   `30e1489` promotes the delivery contract to its canonical spec. The checked
   out sibling head is tagged `v5.6.1`, `simplebroker_pg/v3.3.1`, and
   `simplebroker_redis/v3.3.1`.
2. The returned public broker surface has exact signature
   `broadcast(message, *, pattern=None, queue_names=None,
   create_missing=False) -> int`.
3. A direct Taut-environment probe called it with one absent exact name and
   `create_missing=True`; it returned `1` and `peek_many()` observed the
   ordinary reaction body in the newly established queue.
4. The three active specs and dependency floors now require that public mode.
   They expose `audience_count`, not broker delivery accounting, and retain
   only the best-effort exception warning.
5. Taut still owns visibility, membership/DM audience policy, cursor ordering,
   reaction encoding, and adapter behavior. SimpleBroker owns queue-name
   validation, missing-queue provisioning, full-set atomicity, and backend
   transaction mechanics. This is the layer boundary implementation review
   must preserve.

Final bare `claude -p` review returned `APPROVED WITH CONDITIONS`.

Required condition and disposition:

1. **`audience_count` was ambiguous for a DM with corrupt extra sidecar
   membership. Accepted.** The plan and [TAUT-7.7], [TAUT-8.2], [IAN-10],
   [MCP-6], and [MCP-12] now define it as the final authorized recipient-set
   size after actor exclusion and DM registry intersection. It equals
   `len(queue_names)`, not the raw sidecar membership size or broker return
   count. The test matrix now requires a corrupt-extra-member DM case that
   proves both recipient exclusion and the post-intersection count.

Optional observations, not added to scope:

- Project-configurable values are the largest piece of v1 machinery, but they
  are an explicit product decision and the emission-only allowlist is needed
  for cross-peer compatibility.
- An empty audience intentionally returns before cursor advancement. This is
  already explicit and should not be silently changed during implementation.

The reviewer found no other required change, no layer violation, and no stale
active delivery-accounting contract. With the required condition
dispositioned, it judged the plan ready to implement.

## 17. Verification Record

2026-07-28 spec-reconciliation slice:

- Direct SimpleBroker 5.6 source and runtime probes established the public
  signature, existing-only target selection, missing-name non-creation,
  selected-subset atomicity, and exact returned count.
- Bare `claude -p` independent review returned
  `APPROVED WITH CONDITIONS`; all five conditions/minor findings are
  dispositioned in section 16.
- `uv run --extra dev pytest tests/test_docs_references.py -q -n0`:
  10 passed.
- `python3 bin/check-dom15-fixtures`: fixture contract OK.
- `git diff --check` and
  `git diff --no-index --check /dev/null
  docs/plans/2026-07-28-message-react-plan.md`: no whitespace errors.
- The earlier stale-contract grep applied to the now-blocked existing-inbox
  candidate and is superseded by the API re-review.

Production code and behavior tests remain pending. This record closes only the
spec-promotion/reconciliation slice, not the implementation plan.

2026-07-28 API re-review evidence:

- `uv run pytest tests/test_broadcast_api.py tests/test_broadcast.py -q` in
  `../simplebroker`: 34 passed.
- `uv run ./bin/pytest-pg -q
  extensions/simplebroker_pg/tests/test_pg_broadcast_semantics.py
  tests/test_broadcast_api.py`: shared exact-target suite passed with one
  SQLite-only skip; PostgreSQL semantics 2 passed.
- `uv run ./bin/pytest-redis -q
  extensions/simplebroker_redis/tests/test_redis_integration.py
  extensions/simplebroker_redis/tests/test_redis_atomicity.py -k broadcast`:
  31 passed.
- Direct SimpleBroker lifecycle probe: `never_used 0`,
  `before_consume 1`, `after_vacuum 0`.
- Direct Taut registration probe: `member_in_sidecar True`,
  `inbox_exists_in_broker False`.
- Bare `claude -p` cross-model retry: `APPROVED WITH CONDITIONS`; all four
  conditions are accepted and dispositioned in section 16. The verdict
  approves the blocker analysis, not Taut implementation.
- `git diff --check`: passed before this disposition.

2026-07-28 SimpleBroker 5.6.1 resolution evidence:

- Sibling tags at head: `v5.6.1`, `simplebroker_pg/v3.3.1`, and
  `simplebroker_redis/v3.3.1`.
- Installed Taut environment: `simplebroker v5.6.1` and
  `simplebroker-pg v3.3.1`.
- Returned broker signature probe:
  `(message: str, *, pattern: str | None = None,
  queue_names: Sequence[str] | None = None,
  create_missing: bool = False) -> int`.
- Direct absent-inbox probe: requested target count `1`;
  `peek_many("notify.absent") == ["reaction"]`.
- `uv run pytest tests/test_broadcast_api.py tests/test_broadcast.py -q` in
  `../simplebroker`: 42 passed.
- `uv run ./bin/pytest-pg -q
  extensions/simplebroker_pg/tests/test_pg_broadcast_semantics.py
  tests/test_broadcast_api.py`: shared exact suite passed with one SQLite-only
  skip; PostgreSQL semantics 3 passed.
- `uv run ./bin/pytest-redis -q
  extensions/simplebroker_redis/tests/test_redis_integration.py
  extensions/simplebroker_redis/tests/test_redis_atomicity.py -k broadcast`:
  38 passed.
- Three-spec diff SHA-256:
  `bfcdea52ec1be4841f871132ff54668fc1f29320ae4e7a320064d78e4dd26759`.
- `uv run --extra dev pytest tests/test_docs_references.py -q -n0`: 10 passed.
- `python3 bin/check-dom15-fixtures`: fixture contract OK.
- `git diff --check` and the standalone new-plan whitespace check: passed.
- Final bare `claude -p` cross-model review: `APPROVED WITH CONDITIONS`; its
  one required `audience_count` clarification is dispositioned in section 16.

2026-07-28 implementation evidence:

- Receive/config RED: the initial reaction decoder and renderer cases returned
  `foreign`; configuration coverage produced 15 focused failures before the
  packaged/default/replacement loader existed. GREEN: 32 project-config tests
  and the combined config/lazy/architecture set (78 tests) passed.
- Core RED: `react_to_message` was absent; malformed boolean timestamps and
  recipient-specific reaction fields violated the promoted model. GREEN:
  reaction input, exact-id, channel, self-authored, sub-thread, DM,
  empty-audience, high-water, duplicate, peek/claim, stale-source, one-call
  broadcast-failure, cursor-failure, and deterministic membership/source-race
  contracts pass.
- CLI RED: the nested parser rejected `react`; the new exit-2 firing test
  exposed an unwanted empty-audience diagnostic. GREEN: exact human/JSON,
  warning/quiet, help, option/arity, exit 0/1/2, and not-found diagnostic
  contracts pass.
- MCP RED: 19 focused manifest, schema, dispatch, encoding, and resource cases
  failed before tool 18. GREEN: the full extension suite passed 113 tests on
  SQLite; all 5 live PostgreSQL conformance tests then passed against a
  disposable Postgres 18 container.
- Root `uv run --extra dev pytest -q -n0`: passed with one Windows-only
  filename probe skipped on macOS. Summon extension suite: passed.
- `uv run ./bin/pytest-pg --fast`: 198 shared contracts and 14 Taut-PG
  contracts passed. This includes the shared message-reaction contract against
  PostgreSQL.
- Both canonical root mypy partitions and the MCP mypy partition passed.
  Repository-wide Ruff check and format check, lock checks, DOM-15 fixture
  check, docs/metadata/CLI-probe/architecture tests, and `git diff --check`
  passed.
- Completed-work bare `claude -p` review found no correctness,
  confidentiality, best-effort, compatibility, overengineering, or layer
  defect. It requested a distinguishing synchronous `StopWatching` test and a
  CLI exit-2 firing test; both were added. Its final disposition confirmed
  those logic fixes and found one Ruff-format failure in the architecture
  inventory, which was formatted and rechecked cleanly.

Implementation deviations and adjacent compatibility:

- Raising the SimpleBroker floor exposed its current `StopWatching` terminal
  control-flow behavior. Taut's reactor now treats that exception as a normal
  stop even before its own stop flag is visible; a synchronous firing test
  distinguishes this from the prior unhandled exception.
- No Taut-side fanout primitive, retry, delivery counter, maintained reaction
  table, dynamic CLI/MCP enum, or private SimpleBroker access was added.
- Release version selection, commit, tag, and publication remain outside this
  implementation. The working tree is intentionally left uncommitted for the
  repository owner.
