# Identity, Addressing, and Notifications Specification

Status: Active

This spec defines Taut's member identity model, mutable names, addressing
syntax, special queue namespaces, direct-message queues, notification queues,
and channel rename semantics. It describes the intended model directly. Current
implementation details belong in plans, not in this spec as compatibility
rules.

## 1. Purpose and Scope [IAN-1]

In scope:

- stable member identity and deterministic identity evidence
- mutable member names and reserved routeable-alias storage
- `@name` direct-message addressing, plus alias routing where an alias already
  exists
- channel, sub-thread, direct-message, notification, and system queue naming
- mention and direct-message notifications
- channel rename semantics across channel queues, sub-thread queues, and
  sidecar state
- the DM, sub-thread, and notification consequences of core
  exact-message deletion
- verification expectations for the identity, addressing, and notification
  contracts

Out of scope:

- authentication, authorization, signing, encryption, or proof of identity
- per-device notification fanout
- private channel permissions beyond the existing storage-access trust model
- message editing, retention, archival, bulk deletion, or history rewrite
  beyond the exact core deletion contract in [TAUT-7.6]
- opaque channel ids for normal channels
- nested sub-threads beyond one level

## 2. Mental Model [IAN-2]

### [IAN-2.1] Members have stable opaque ids

A member is the logical participant that sends messages, owns read cursors, can
be mentioned, can receive a direct message, and can receive notifications. A
member has a stable opaque `member_id`.

`member_id` is the identity used inside Taut. It is not a display name, not a
route alias, and not a channel name. A member may change names without changing
`member_id`.

### [IAN-2.2] Names are current values

Names are mutable current-value lookup data. They are used to route new
commands such as `taut say @claude "..."` or `taut rejoin claude`; they are not
the durable identity. Alias storage follows the same model, but public alias
management is not part of the current command surface.

Messages keep the sender name that was current when the message was written.
Taut does not rewrite old messages when a member changes name.

### [IAN-2.3] Identity evidence is separate from member identity

Process-chain evidence, human session evidence, and continuity-token evidence
produce deterministic identity claim hashes. A claim hash is evidence that a
session probably belongs to a member. It is not, by itself, the durable member
identity.

Rejoin associates a new claim hash with an existing `member_id`. This is what
lets a restarted agent keep its old cursors, memberships, direct-message
queues, and notification inbox even though the process evidence changed.

### [IAN-2.4] Normal channels stay human-named

Normal channels are unprefixed human slugs such as `general` and `ops`. They do
not use opaque ids. This keeps the common command surface simple and avoids
turning every channel operation into an indirection lookup.

Direct messages and notification queues do use opaque member-derived names
because their routing identity must survive mutable names.

### [IAN-2.5] Chat history and notifications have different consumption rules

Channel, sub-thread, and direct-message queues are chat history. Taut reads them
with peek-family broker APIs and advances member cursors in sidecar state.

Notification queues are inbox pointers. They are claimed when read so the
notification goes away. This is intentionally per member, not per device.

## 3. Member Identity [IAN-3]

### [IAN-3.1] Member id format

`member_id` values are opaque strings matching:

```text
^m_[a-z0-9]{26,52}$
```

The prefix makes member ids distinguishable from channel names and message ids.
The suffix is lowercase, URL-safe, and has no dots.

Taut mints `member_id` as an opaque value when a member is created. It must not
derive `member_id` from a display name or alias, and it must not recompute
`member_id` from the current process evidence on later commands.

The deterministic value tied to local identity evidence is the claim hash in
[IAN-3.2]. A claim hash maps to a member id; it is not the durable member id
itself.

### [IAN-3.2] Identity claim hashes

Taut captures best-effort local evidence when it is needed to infer or create a
member, to associate the current process claim through `rejoin`, or to render
current evidence through `whoami --explain`. Either a resolved explicit name or
alias, or a valid continuity token when no explicit `as` is supplied, is
sufficient to select the acting member for an ordinary operation and does not
require process/session capture. Whenever local evidence is captured, Taut
canonicalizes it into an identity claim. Canonicalization computes the claim
hash in memory; it does not by itself insert or refresh
`taut_identity_claims`. Persistence follows [IAN-3.3], member creation, or
`rejoin` only. The claim hash format is:

```text
^ic_[a-z0-9]{52}$
```

The hash input is canonical JSON with sorted keys and no insignificant
whitespace. It includes `claim_kind` and only the evidence that belongs to that
kind.

Supported claim kinds:

| Claim kind | Evidence |
|---|---|
| `agent_process` | host id, anchor pid, anchor start token, executable path, argv, cwd, uid, process group, session id, tty |
| `human_session` | host id, uid, login name, tty when available, session id when available |
| `continuity_token` | token id or token hash, not the token display string |

The exact evidence may be null field-by-field when the platform cannot provide
it. Missing optional fields must not fail identity capture.

### [IAN-3.3] Claim association

`taut_identity_claims` maps claim hashes to `member_id` values. A claim hash can
belong to only one member. A member can have many claim hashes.

Resolution order:

1. Explicit `--as NAME_OR_ALIAS` / `TAUT_AS`, if present, is authoritative for
   the ordinary operation and remains ahead of token and inferred evidence.
   Taut validates and resolves the current name or alias before capturing local
   evidence. An existing member is selected without writing the current process
   claim or changing its anchor or fingerprint. If no member exists and the
   operation may create one, Taut captures local evidence once, creates the
   member with that name, and associates the current claim when it is unclaimed.
   An operation that cannot create a member fails or remains a guest according
   to its existing contract without probing identity or creating a throwaway
   member.
2. A continuity token, when no explicit `as` selector is present, resolves to
   its member without capturing local process/session evidence. A state-changing
   resolution records or refreshes the `continuity_token` claim and activity
   exactly as before; it does not write the current process claim or change the
   member anchor or fingerprint. An invalid token fails without falling back to
   inferred identity.
3. When neither deterministic selector is supplied, Taut captures local
   evidence. A captured claim-hash match resolves to the associated member.
4. Agent anchor match: when no claim hash matches and the capture is an
   agent capture, resolution may match a stored member anchor by the stable
   triple (`host_id`, `anchor_pid`, `anchor_start_time`) against the
   captured ancestor chain. This recovers continuity when a live anchor
   process changed mutable claim inputs (working directory, tty, process
   group) without restarting. On a match, the resolver records the current
   claim hash for that member so subsequent commands resolve at step 3.
   Anchor match never applies under `join --new`, never overrides steps
   1–3, and never matches across hosts.
5. Human fallback resolves by local host id plus uid when an existing human
   member has that claim history.
6. Otherwise the caller is unrecognized. Read-only commands may operate as
   guests where the core spec allows that. State-changing commands create a new
   member only when the command can still succeed after creating that member.
   Membership-gated writes, such as channel `say` and `reply`, must not create
   throwaway members before failing membership or missing-target validation.

Acting-member selection and process-claim association are separate operations.
For an existing member, `as` and token selectors affect the current operation
but do not teach future selector-free resolution a new process claim.
Selector-free resolution may still resolve through claim-hash continuity under
item 3 and record process claims through anchor healing and human fallback under
items 4–5. `rejoin` is the sole explicit command that associates the current
process claim with a caller-chosen existing member, including when its target is
selected by token. Taut performs no deferred or background identity verification
or claim association. A process may therefore act as different members through
explicit selectors without the first selection becoming a silent durable
binding.

No resolution path silently changes a member name. Name changes are explicit
through [IAN-4.4].

`join --new` creates a fresh member and bypasses rejoin suggestions. If the
current claim hash is unclaimed, Taut may associate it with the fresh member. If
the current claim hash already belongs to another member, `join --new` must not
steal it; the fresh member is reachable by its name or continuity token until a
future explicit rejoin from suitable evidence.

`join(..., new=True)` means create a fresh member and never adopt an existing
route. When an explicit `as_name` is already a member name or alias, the call
raises the existing identity-collision error before activity, claim,
membership, cursor, persona, or notice mutation. The CLI `join --new` has the
same fail-not-adopt behavior.

### [IAN-3.4] Rejoin

`taut rejoin NAME_OR_ALIAS` means "associate the current process claim with the
member selected by this name or alias." The target may instead be selected by a
continuity token or by the global `--as` selector. Supplying both a name/alias
and a token, or otherwise leaving more than one selector active, fails as an
ambiguous request. Rejoin does not merge message history, does not rename the
member, and does not rewrite old messages.

If the current claim is already associated with a different member, `rejoin`
fails and names the conflicting current member. There is no implicit merge.

## 4. Names and Aliases [IAN-4]

### [IAN-4.1] Name roles

Taut stores:

- `member_id`: stable opaque identity
- `display_name`: current human-readable name shown in member lists and used as
  the message sender snapshot for new messages
- `name_key`: normalized unique key for `display_name`
- aliases: normalized route keys that also point to a `member_id`

The term "name" in the CLI refers to `display_name`, with `name_key` computed
from it for routing.

### [IAN-4.2] Name validation

Names are case-preserving but route-normalized. A name must match:

```text
^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$
```

The route key is lowercase ASCII. `VanL`, `vanl`, and `VANL` conflict.

Automatically generated human and agent display names use the same display
casing rule: normalize the login or process seed, then scan left-to-right,
uppercase the first lowercase ASCII letter `[a-z]`, and leave all remaining
characters unchanged. A digit-leading seed such as `2agent` therefore becomes
`2Agent`; a seed with no ASCII letter is unchanged. Curated fallback candidates
carry their intended display casing. Explicit names supplied through `--as`,
`TAUT_AS`, the Python API, or `set name` are case-preserving and are never
recased automatically. All forms still route through the lowercase `name_key`.

Free-form display profiles, names with spaces, and non-ASCII route aliases are
out of scope until a later spec defines unambiguous shell and JSON behavior.

### [IAN-4.3] Alias validation

Aliases use the same validation and normalization rules as names. An alias is
route-only; old messages never display an alias unless that alias was also the
member's `display_name` at write time.

All active name keys and alias keys share one uniqueness namespace. If `claude`
is a member name, another member cannot claim `claude` as an alias.

The name/alias route-key namespace remains unique under concurrent writes on
every supported backend. Before checking either route table and inserting or
renaming a route, a server-backed SQL implementation serializes the normalized
route key for the current transaction. Per-table UNIQUE constraints remain the
final same-table backstop; they are not sufficient for cross-table uniqueness
by themselves.

The current public CLI does not define an alias-management command. Alias
storage and lookup are reserved for schema/API use and future command work.
Any future public alias command must specify ownership, collision behavior,
rendering, and tests before exposing aliases to users.

### [IAN-4.4] Name changes

`taut set name NAME` updates the acting member's `display_name` and `name_key`.
The old name stops routing to the member unless it is retained explicitly as an
alias by a future alias-management command. Taut does not keep stale route
aliases by default.

An explicit name change fails if the normalized name is already owned by another
member as either a current name or alias. Automatic name generation may append
or choose a deterministic fallback to avoid collisions, but explicit `set name`
must not silently choose a different name.

Automatic candidate order is the normalized seed, a curated per-agent pool
when one exists, the shared historical-name pool, then a numeric suffix. The Pi
family begins `Pi`, `Tau`, `Phi`.

### [IAN-4.5] Message sender snapshot

Every Taut-written chat message records both:

- `from_id`: sender `member_id`
- `from`: sender `display_name` at write time

Renderers show `from`. Machine consumers should use `from_id` when they need
stable identity across name changes.

## 5. Addressing [IAN-5]

### [IAN-5.1] Command address classes

Taut conversation arguments use these shapes:

| Input shape | Meaning |
|---|---|
| `general` | channel `general` |
| `#general` | channel `general`, accepted for familiarity but usually needs shell quoting |
| `general.<message_id>` | sub-thread under channel `general` |
| `@claude` | direct message with the member currently named `claude`, or aliased `claude` if a Taut member alias exists |
| `dm.d_<26-lowercase-base32-chars>` | one existing stable direct-message conversation, subject to actor access checks in [IAN-5.3] |

Not every command accepts every class. `say` accepts channels, subthreads, and
`@name-or-alias`; it does not accept a stable `dm.d_*` handle. `read`, `log`,
and `watch` accept their existing channel/subthread forms plus both DM selector
forms. `join`, `leave`, `reply`, `channel rename`, and `who THREAD` retain
their existing narrower contracts.

Documentation should prefer bare channel names in shell commands because an
unquoted leading `#` can be interpreted as a shell comment. Human rendering may
show channels as `#general`.

### [IAN-5.2] Mention parsing

Taut parses mentions from Taut-written message text after the message has been
accepted for write. A mention is a token of the form `@name` or `@alias` where
the route key matches [IAN-4.2] / [IAN-4.3] and resolves at write time.

Rules:

- A message can mention multiple members.
- Multiple mentions of the same member in one message produce at most one
  notification.
- The sender does not receive a mention notification for mentioning themself.
- Mentions inside foreign broker bodies are not parsed by Taut.
- Mention routing uses the current name/alias route table at write time; later
  name changes do not retarget the old mention.
- Mentions written into a direct-message queue notify only the two DM
  participants. Mentioning any other member in a DM produces no
  notification for them: a DM must not leak its existence, queue name, or
  activity to non-participants. Exact-message delete may scan registered DMs
  to find the acting author's own row, but an ineligible lookup must expose no
  body, participant, thread, or existence detail ([TAUT-7.6]).

### [IAN-5.3] Direct-message conversation selection

A DM route selector is `@` plus a valid current member name or Taut member
alias. It resolves once at invocation time relative to the acting member, then
derives [IAN-6.4]'s deterministic queue from the two stable member ids. A
running watch stays on that canonical queue after either member renames.
Later invocations follow the then-current route owner. Old names do not remain
routes unless retained through the Taut member-alias model in [IAN-4].

A stable DM selector matches exactly `^dm\.d_[a-z2-7]{26}$`. The selector is
authority only when the registered row is a DM with exactly two distinct valid
member ids, its name equals [IAN-6.4]'s derivation for that pair, the actor is
one participant, both member rows exist, and both participant memberships
exist. Missing, malformed, mismatched, self, nonparticipant, or inaccessible
selection returns one content-free not-found/empty result without exposing
another participant, registry metadata, queue contents, member-route
existence, or whether another pair owns the supplied handle. Malformed selector
syntax remains a validation error.

Navigation never creates or heals a member, identity claim, route, queue,
thread, membership, notification, or DM. A valid current route with no
existing DM is not found. SimpleBroker queue aliases do not participate in DM
selection because their namespace is global rather than actor-relative.

## 6. Queue Namespace [IAN-6]

### [IAN-6.1] Queue classes

Taut-owned queues have one of these classes:

| Queue class | Queue name shape | Consumption rule |
|---|---|---|
| channel | `<channel>` | peek history |
| sub-thread | `<channel>.<message_id>` | peek history |
| direct message | `dm.<dm_id>` | peek history |
| notification | `notify.<member_id>` | claim inbox pointers |
| system | `sys.<name>` or `taut.<name>` | class-specific |

All Taut-visible queues must have a sidecar registry row that records their
class. Unknown broker queues remain invisible to Taut commands.

Queues under the reserved `sys` prefix are extension-internal control
queues; their derivation and bodies are defined by the extension spec
that owns them (summon: [SUM-9]). They are deliberately **not
registered**: the registry requirement above applies to queues core
lists and routes, and `sys.*` extension queues remain invisible broker
queues to every core command — exactly the treatment unknown broker
queues already get. Core never routes chat to `sys.*`; only the owning
extension reads or writes them.

Core-owned unregistered system queues use the reserved `taut.*` namespace.
Search owns `taut.search_index`, `taut.search_index.claimed`, and
`taut.search_index.failed` under [SRCH-8]. They are invisible to every chat
route and listing surface; only the owning core subsystem consumes them.

### [IAN-6.2] Channel names

Channel names match:

```text
^[a-z0-9][a-z0-9_-]{0,63}$
```

Dots are forbidden. Dot is structural namespace syntax. This means
`general.1837025672140161024` can only mean a sub-thread, never a top-level
channel.

The exact channel names `dm`, `notify`, `sys`, and `taut` are reserved. Dotted
queue names whose first segment is one of those reserved words are reserved for
special queues.

### [IAN-6.3] Sub-thread queues

A sub-thread queue name is:

```text
<channel>.<origin_message_id>
```

`origin_message_id` is the 19-digit SimpleBroker timestamp of the parent
message. Sub-threads of sub-threads are not supported. The registry relation
survives physical deletion of that origin message. The resulting child is a
permanent, addressable orphan: existing members may continue to post with
`say <child-thread>`, while a new root-based `reply` fails because the parent
row no longer resolves. Taut neither cascades the deletion nor repairs or
removes the child.

### [IAN-6.4] Direct-message queues

A direct-message queue name is:

```text
dm.<dm_id>
```

`dm_id` is deterministic from the unordered pair of member ids:

```text
dm_id = "d_" + base32_lower(sha256("taut-dm\0" + min(member_id_a, member_id_b) + "\0" + max(member_id_a, member_id_b)))[0:26]
```

Both participants map to the same queue regardless of who starts the
conversation or what either member is named later.

Physical deletion of the first, newest, or only direct-message row does not
remove the deterministic thread registry or either membership. An empty
registered DM remains a valid conversation and appears under list-all with no
surviving `last_ts`. Later contact reuses the same queue and does not emit a
second `dm_started` notification.

Actor-scoped human renderers label a valid direct-message conversation
`DM with <other current display name>`. Human `read`, `log`, and `watch`
message headings, bare joined `list`, and `list --dms` use that label. JSON,
Python, and MCP message surfaces keep the internal `dm.<dm_id>` queue name in
`thread`; list/thread metadata also exposes participant member ids under
[TAUT-8.2].

The pre-existing global `list --all` diagnostic view retains its current
membership-independent rendering: a valid DM may show all current participant
names, and missing or malformed participant metadata renders
`DM <internal-thread> (participants unavailable)`. It invents no identity or
extra warning. Actor-scoped `list --dms` excludes malformed or inaccessible
rows.

Human notification actions are type-specific. A channel or subthread mention
renders `taut log <source-thread>`; a direct-message mention renders
`taut log <stable-dm-thread>`. A mention includes the shortest unique
source-message suffix usable with `taut reply` only when the source is a
top-level channel and the recipient is a member (full id on ambiguity). A
reply pointer renders `taut log <child-thread>`; `dm_started` renders
`taut read <stable-dm-thread>`, and no invented reply id. Choosing and
constructing a DM action uses the pointer's stable source thread and performs
no identity, list, registry, or source-queue lookup. Existing channel mention
reply-suffix eligibility and uniqueness probes are unchanged. `log` remains
membership-independent for channels/subthreads but is participant-scoped for
DMs under [IAN-5.3]. All render local `HH:MM`. JSON timestamps and names do not
change.

Self-DM is rejected unless a later spec explicitly gives it a use.

### [IAN-6.5] Notification queues

A member's notification queue name is:

```text
notify.<member_id>
```

There is exactly one notification queue per member. Taut does not create
per-device queues. In a multi-host backend, whichever session claims a
notification consumes it for that member.

## 7. Notifications [IAN-7]

### [IAN-7.1] Notification purpose

A notification is a small durable pointer telling a member that a relevant
chat event occurred elsewhere. It is not the source of truth or a copy of the
source body. The source initially exists in the channel, sub-thread, or
direct-message queue, but its author may later physically delete it under
[TAUT-7.6]. The notification row survives unchanged and `message_ts` then
becomes a stale pointer.

A reaction notification is one such pointer. It records a configured
lightweight response to an ordinary message. It is not maintained message
state, an aggregate, or a reaction count. Each intended current member inbox
receives an independent row; a missing implicit inbox is established by that
row. Consuming one member's row affects no other member.

### [IAN-7.2] Notification payload

Notification queue bodies are JSON objects:

```json
{
  "type": "mention",
  "to_id": "m_abcd1234abcd1234abcd1234ab",
  "actor_id": "m_wxyz1234wxyz1234wxyz1234wx",
  "actor_name": "claude",
  "thread": "general",
  "message_ts": 1837025672140161024,
  "matched": "@van"
}
```

Fields by notification type:

| Field | Meaning |
|---|---|
| `type` | `mention`, `dm_started`, `reply`, or `reaction` |
| `to_id` | recipient member id; omitted from a stored reaction body and decoded as null |
| `actor_id` | member id that caused the notification |
| `actor_name` | actor display-name snapshot at event time |
| `thread` | source chat queue |
| `message_ts` | source message timestamp |

`matched` is required for `mention` and omitted for `dm_started`, `reply`, and
`reaction`. A reaction instead requires `reaction`, a lowercase ASCII slug
matching `^[a-z0-9][a-z0-9_-]{0,31}$`. The receiving client validates that
grammar, not its local outbound reaction allowlist. A missing, non-string, or
syntactically invalid value is malformed/foreign under the existing tolerant
notification contract. Unknown fields remain ignored.

Reaction bodies contain the common actor snapshot, `thread`, `message_ts`, and
required `reaction`, but omit recipient-specific `to_id`. The identical body
is broadcast to exact inbox names, whose queues supply the routing. Public
`Notification.to_id` is therefore null for reactions; public notification
records add `reaction` only for `type == "reaction"`.

A `reply` notification points the author of a parent message to activity in
that message's child thread. Taut emits one for each reply while the parent
author is not a member of the child thread, except when the author wrote the
reply or the parent is a foreign message without a stable `from_id`. Once the
author joins the child, ordinary unread/watch delivery replaces the pointer. If
the same reply mentions the parent author, Taut emits only the reply
notification, not a duplicate mention pointer. The payload uses `type:
"reply"` and the existing actor/thread/message fields; `thread` is the child
queue.

Membership is observed after the reply commits and immediately before
notification dispatch. A concurrent join may therefore leave one stale
disposable pointer; it never duplicates the reply, and later replies use the
new membership state. The reply may later be author-deleted while the pointer
survives. After a later leave, reply pointers resume.

Notification payloads may add fields later. Consumers must ignore unknown
fields and must not depend on notification text formatting.

### [IAN-7.3] Notification write ordering

A blank attempt filtered under [TAUT-6.5] never becomes a source message and
never enters mention, reply, or `dm_started` notification dispatch.

For a mention, Taut writes the source chat message first. Notification writes
come after the source message succeeds.

If notification emission fails after the source message succeeds, the chat
write remains successful. The implementation should surface a warning when the
CLI can do so without corrupting JSON output. It must not roll back the source
message or rewrite history.

Reaction fanout follows [TAUT-7.7]. After target lookup, a nonempty
current-audience snapshot, and actor cursor advancement, Taut calls public
SimpleBroker exact-name broadcast once with `create_missing=True`.
SimpleBroker atomically writes the identical body to every distinct requested
inbox name, including a name with no retained row, or writes none. A raised
call may be outcome-ambiguous and warns, but the `audience_count` operation
receipt makes no delivery claim. Taut neither retries nor rewinds the actor
cursor. A later membership change, source claim, or source deletion does not
rewrite an already emitted pointer.

### [IAN-7.4] Notification reads

Notification reads use claim/read broker APIs. Reading a notification removes
it from the recipient's notification inbox. A failed notification renderer may
lose that notification. The source chat message normally remains available
through history, but may already be absent because its author deleted it,
another consumer claimed it, or broker/registry state diverged.

This tradeoff is intentional. Notifications are wakeups and pointers, not
durable chat history.

Reaction pointers are claimed, peeked, and watched like other notifications.
Those recipient operations never move a source chat cursor. Human reaction
rendering always advertises `message show`; it does not preflight the source.
A stale action returns that command's ordinary content-free empty result. This
deliberately differs from mention reply-action preflight: `reply` mutates and
has a confusing dead-source failure, while `message show` is a safe read with
an established empty result.

A read-only notification peek may expose current pending notification
pointers without claiming them. Peek is observational and does not advance a
notification or chat cursor, create or heal identity, touch activity, or
acknowledge delivery. A later consuming read may therefore return the same
notifications, while another consumer may remove them before the next peek.

Notification rendering treats `message_ts` as a fallible pointer. A mention
may advertise the shortest usable `taut reply` action only after a
cursor-neutral public exact `peek_one()` confirms that the top-level source
still exists and the recipient remains a member. The renderer must not call
`show_message()`, because showing the source would advance the recipient's
chat high-water cursor. If the source is absent, the pointer remains
renderable and consumable, but the dead reply action is omitted. Reply and
`dm_started` pointer rendering retains its type-specific thread/read action;
source deletion never rewrites the notification row. MCP notification
snapshots remain notification-derived and receive no resource update merely
because a source message was deleted.

## 8. Channel Rename [IAN-8]

### [IAN-8.1] Rename semantics

Renaming a channel changes the channel slug and all one-level sub-thread queue
names under it.

Example:

```text
general -> ops
general.1837025672140161024 -> ops.1837025672140161024
```

The rename must update:

- the channel queue name
- every registered sub-thread queue name under that channel
- `taut_threads.name`
- `taut_threads.parent`
- `taut_membership.thread`
- any notification payloads still pending that point at the old queue name, if
  the backend exposes a safe public way to update them

It must not rewrite existing chat message bodies. Existing message `from` values
and text remain unchanged.

Rename changes channel and subthread addresses without rebuilding their
registry metadata. Every `taut_threads.meta` key, including [TAUT-4.4] channel
topic metadata, survives unchanged. Rename validates the source channel's topic
object before marker creation or broker mutation and refuses corrupt metadata.
Topic mutation and rename-marker creation acquire the same per-channel
transaction serialization key. A concurrent topic transaction either commits
against the old row before marker creation and follows that row, or observes
the marker and refuses the old-name write; rename never drops a committed
topic.

The public CLI route is `taut channel rename OLD NEW`. Its parser, dispatch,
output, exit classes, and recovery semantics are the existing rename behavior
rehomed under the reserved `channel` noun. Incomplete-rename diagnostics name
that exact command. The Python `TautClient.rename_channel()` method and MCP
`channel_rename` tool retain their domain semantics; the MCP identifier is
normalized from `rename` without an alias.

### [IAN-8.2] Rename dependency on SimpleBroker

Taut must use a public SimpleBroker queue-rename API for broker queue renames.
Taut must not update SimpleBroker-owned message tables directly.

Taut requires `simplebroker>=6.0.1` and `taut-pg` requires
`simplebroker-pg>=3.5.0`. This compatible pair preserves the atomic write ids,
rename-capable backend handshake, persistent-reactor ownership, live
activity-waiter replacement, interruptible watcher bootstrap, corrected
runner cleanup, and timestamp-conflict metrics on which rename relies. The
6.0.0 command-layer binding change does not affect rename because Taut uses
`simplebroker.open_broker(...).rename_queue(...)`, not
`simplebroker.commands`. The implementation must use
`simplebroker.open_broker(...).rename_queue(...)` against Taut's resolved
broker target; it must not assume `Queue.rename()` or a module-level
`simplebroker.rename_queue()` exists.

### [IAN-8.3] Rename failure handling

Rename is rejected before mutation if:

- the source channel does not exist
- the target channel already exists
- the source or target is a special queue name
- the target name is invalid under [IAN-6.2]

Because broker queue renames and sidecar updates may not share one transaction,
the implementation plan must define recovery for partial rename. At minimum,
the operation needs a sidecar marker that records old name, new name, affected
queue names, current phase, and completion state so a later command can finish
or report the interrupted rename. The recovery command is
`taut channel rename OLD NEW`.

## 9. Failure Modes and Edge Cases [IAN-9]

- Name collision: explicit `set name` and schema-level alias creation fail.
  Automatic member creation may choose a deterministic fallback.
- Claim collision: if the same claim hash is already mapped to another member,
  resolution uses that member. `rejoin` to a different member fails loudly.
- Explicit-selector and process-claim disagreement: the explicit `as` member or
  token member wins for the current operation. The existing process claim
  remains owned by its current member; ordinary selection neither steals nor
  rewrites it.
- Missing deterministic selector target: a supplied explicit name with no
  matching member on a non-creating operation fails or remains a guest under
  the operation's existing `allow_guest` contract, without local identity
  inference or member creation. An invalid token fails with the existing token
  error. Neither case falls back to a different claim-derived member.
- Name change after mention: pending and historical notifications keep the
  actor and matched route-token snapshots from event time.
- Name change after direct message: the direct-message queue stays the same
  because it is derived from member ids.
- Foreign writes into chat queues: Taut renders them as foreign bodies and does
  not parse mentions.
- Foreign writes into notification queues: Taut drops or reports malformed
  notification bodies after claiming them. It must not crash the inbox reader.
- Notification claimed but not displayed: allowed. Notifications are
  best-effort pointers; source history is usually available but may have been
  author-deleted.
- Notification source deleted: the mention, reply, or `dm_started` pointer
  remains byte-for-byte consumable. Human mention rendering omits a reply
  action when its cursor-neutral exact source peek misses.
- Reaction receiver configuration differs: a structurally valid reaction
  still decodes when the receiver's local emission list omits that value.
- Reaction inbox absent at broadcast selection: `create_missing=True`
  establishes it with the reaction row. A member who joins after the audience
  snapshot misses the event, while one who leaves after the snapshot may
  receive a stale pointer.
- Repeated reaction or retry after an uncertain result: duplicate independent
  notification rows are valid.
- Corrupt channel-topic metadata: rename fails before creating its marker or
  mutating broker queues; it does not guess, repair, or overwrite the topic
  object.
- Reply origin deleted: the registered child thread and its history survive;
  direct child addressing works and new root-based reply creation fails.
- Sole direct-message row deleted: the deterministic registry and both
  memberships survive; later contact reuses them without another
  `dm_started`.
- `@name-or-alias` DM navigation resolves relative to the actor and creates no
  conversation; valid stable handles survive rename, while later route reuse
  follows the new owner.
- Stable handles are rejected before queue access for nonparticipants,
  malformed registry metadata, pair/name mismatch, missing members, or missing
  participant memberships, with absent and inaccessible adapter output
  indistinguishable.
- Actor-scoped DM directory results include read and empty valid DMs, exclude
  malformed/inaccessible rows, and sort by newest surviving row with empty
  conversations last.
- Channel with dot: rejected. Dots are structural.
- Channel named `dm`, `notify`, `sys`, or `taut`: rejected.
- Partial channel rename: must be recoverable or loudly reportable; silent
  split-brain is not acceptable. Diagnostics name
  `taut channel rename OLD NEW`.
- Topic mutation racing channel rename: the shared old-name serialization
  boundary chooses one safe order. Metadata committed before the marker follows
  the row; mutation after the marker is refused. No committed topic or unknown
  metadata key may be dropped.

## 10. Verification Expectations [IAN-10]

Tests for this spec must use real Taut client, CLI, broker, and sidecar paths.
Do not mock the broker, schema helpers, identity resolver, or queue naming
logic for contract tests.

Required proofs:

- changing a member name does not change `member_id`
- automatic human and agent names use the [IAN-4.2] display casing rule while
  explicit names preserve caller casing
- automatic availability includes both current names and aliases in the
  lowercase route namespace
- the Pi automatic sequence begins `Pi`, `Tau`, `Phi`
- messages written before a name change keep the old `from` snapshot and the
  same `from_id`
- messages written after a name change use the new `from` snapshot and the
  same `from_id`
- `taut rejoin NAME_OR_ALIAS` and `taut rejoin --token TOKEN` each associate a
  new process claim hash with the same `member_id`
- each deterministic selector class independently selects the acting member for
  an ordinary state-changing operation without requesting local process/session
  capture: either an existing explicit name or alias, or a valid token when no
  explicit `as` is supplied
- existing explicit and token selection do not change process-claim ownership,
  anchor, or fingerprint; token selection retains its declared
  `continuity_token` claim/activity effects
- a supplied explicit name with no matching member captures exactly once when a
  creation-capable operation creates it, but a non-creating or
  membership-gated operation creates no throwaway member and does not probe
  identity
- selector-free resolution still captures and exercises claim-hash, anchor,
  human, and allowed-creation behavior
- `rejoin` captures and associates the current process claim, while
  `whoami --explain` captures current evidence without silently associating it
- ordinary selector resolution performs no deferred or background identity
  verification or claim association
- `@name` direct messages route to the member id currently owning the name
- alias-route direct messages route to the member id currently owning the alias
  when an alias exists; public alias-management tests belong with the future
  alias command
- a direct-message queue is stable across both participants changing names
- mentions write exactly one notification per mentioned member per message,
  scoped to the DM participants when the source queue is a direct-message
  queue
- notification reads claim notifications and do not affect chat history
- read-only notification peek preserves pointer count/order and all member,
  identity, activity, cursor, and acknowledgement state; consuming read still
  claims the same pointers under the existing contract
- a second session for the same member can drain notifications; no per-device
  state exists
- deleting a mention, reply, or first-DM source leaves its notification
  pointer byte-for-byte intact and consumable; a deleted mention source emits
  no dead reply action, and the renderer's exact source check advances no chat
  cursor
- deleting an origin message preserves the registered child, its membership,
  history, rendering, and direct-child `say` behavior while new root-based
  `reply` fails
- deleting the first or only direct-message row preserves its deterministic
  registry and both memberships, list-all renders the empty DM, and later
  contact emits no second `dm_started`
- channels cannot contain dots or use reserved special names
- unregistered broker queues remain invisible
- reaction fanout reaches each current exact-thread recipient inbox except the
  actor, stays exact to child membership, intersects direct-message membership
  with registry metadata, reports `audience_count` from that final
  post-intersection set, and establishes never-used and post-vacuum inboxes
- the operation receipt reports only the intended `audience_count`; an
  outcome-ambiguous broadcast exception warns and causes no Taut retry
- reactions are consumed independently per recipient; receiver allowlists do
  not reject valid inbound values; malformed values become foreign; stale
  `message show` actions return empty without renderer preflight
- channel rename, when enabled by a public SimpleBroker rename API, renames the
  channel and every registered sub-thread and updates sidecar references
- the CLI rename parser, dispatch, output, exits, and interrupted-rename
  recovery operate through `taut channel rename OLD NEW`; core registers no
  top-level rename alias
- shared real SQLite and PostgreSQL rename/topic races use deterministic
  barriers to prove the topic-before-marker and marker-before-topic outcomes,
  complete audit objects, and preservation of reserved `closed` plus unrelated
  channel metadata
- rename rejection on a corrupt source topic object occurs before marker
  creation or broker queue mutation

## Related Plans

- `docs/plans/2026-08-06-taut-search-plan.md` — search internal queues,
  actor-scoped DM visibility, and cursor-neutral candidate hydration.
- `docs/plans/2026-07-31-simplebroker-6-reconciliation-plan.md` —
  SimpleBroker 6.0.0 and SimpleBroker-PG 3.5.0 compatibility reconciliation.
- `docs/plans/2026-07-28-channel-topics-plan.md` — per-channel topic and
  rename-marker serialization, metadata preservation, and cross-backend race
  proof.
- `docs/plans/2026-07-28-direct-message-navigation-plan.md` — actor-scoped
  current-route and stable-handle DM navigation, durable DM directory, and
  fail-closed registry/membership validation.
- `docs/plans/2026-07-28-message-react-plan.md` — reaction notification
  payloads, full-audience exact fanout, non-delivery receipts, and stale
  pointer behavior.
- `docs/plans/2026-07-27-message-show-delete-plan.md` — author-owned physical
  deletion, orphaned subthreads, stable empty DMs, stale notification pointers,
  and cursor-neutral notification rendering.
- `docs/plans/2026-07-14-taut-mcp-extension-plan.md` — read-only notification
  peek plus the optional MCP resource and consuming-inbox split.
- `docs/plans/2026-07-14-blank-message-no-op-plan.md` — ensures filtered
  blank attempts never become notification sources.
- `docs/plans/2026-07-14-trusted-identity-selector-fast-path-plan.md` — trust
  existing `as`/token selectors without process capture, preserve
  creation-gated first-contact claims, and keep `rejoin` as explicit process
  claim association.
- `docs/plans/2026-07-12-automatic-display-name-capitalization-plan.md` —
  automatic human/agent display casing, route-aware candidate selection, and
  the Pi/Tau/Phi family.
- `docs/plans/2026-07-11-multi-factor-review-remediation-plan.md` — reviewed
  identity, route concurrency, reply notification, human rendering, and trust
  remediation program for v0.5.3.
- `docs/plans/2026-07-10-taut-dynamic-native-waiter-replacement-plan.md` —
  active SimpleBroker floor and live native-waiter replacement follow-on.
- `docs/plans/2026-07-10-taut-summon-quality-remediation-plan.md` — approved
  SimpleBroker floor and persona-only embedding-seam remediation.
- `docs/plans/2026-06-18-member-identity-addressing-plan.md` - implemented
  migration from the current development implementation to this model.
- `docs/plans/2026-07-06-evaluation-findings-remediation-plan.md` —
  implemented [IAN-3.3] anchor-match resolution, [IAN-8.3] channel-rename
  resume, first-contact naming retry, and direct-message mention
  participant scoping.
