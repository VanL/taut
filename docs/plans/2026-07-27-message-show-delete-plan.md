# Message Show and Delete Plan

Date: 2026-07-27

Status: implemented, verified on SQLite and PostgreSQL, and independently
approved. The worktree is intentionally uncommitted for repository-owner
review.

Plan type: implementation with coordinated core, CLI, and MCP spec revision.

Class: 5. This adds two public Python methods, one core CLI noun with two
subcommands, and two MCP tools. It deliberately changes the append-only chat
history contract and adds a new cursor-mutating exact-read path. The delete
verb is irreversible, the show verb crosses broker and sidecar state, and both
verbs depend on lookup across registered chat queues. [DOM-5] hardening is
required.

Owner: the implementing engineer owns spec promotion, the shared exact-message
locator, core policy, CLI and MCP adapters, real-backend tests, documentation,
and review evidence. The repository owner owns commit, version selection,
release, and publication.

## 1. Goal

Add exact-message inspection and author-only hard deletion across all supported
surfaces:

- `taut message show MSG_ID`
- `taut message delete MSG_ID`
- `TautClient.show_message(msg_id)`
- `TautClient.delete_message(msg_id)`
- MCP `show_message`
- MCP `delete_message`

`show` performs a non-claiming SimpleBroker exact peek and then monotonically
advances the acting member's existing `taut_membership.last_seen_ts` cursor for
the located thread. `delete` physically removes one eligible message through
SimpleBroker's public queue-scoped delete API. It does not cascade into
notifications, reply subthreads, memberships, cursors, member rows, or thread
registry rows.

## 2. Decided Contract

### 2.1 Shared message-ID and lookup contract

- Both verbs require one exact 19-digit native message ID. They do not accept
  the suffix form supported by `reply`.
- Python signatures accept `str` only. A non-string, including `bool` or
  `int`, raises `TypeError("msg_id must be a string")`. A string that does not
  match `MESSAGE_ID_RE` or does not pass the public
  `TimestampGenerator.validate(msg_id, exact=True)` range check raises
  `ValueError("msg_id must be a full 19-digit message id")`.
- Validation is the first domain operation. Invalid input performs no member
  resolution, thread enumeration, queue peek, cursor write, or delete.
- A private exact-message locator accepts an explicit iterable of candidate
  chat threads. For each candidate it calls the public
  `Queue.peek_one(exact_timestamp=..., with_timestamps=True)`. Notification
  queues and unregistered broker queues are outside the search.
- Show supplies only the acting member's current registered `channel`,
  `subthread`, and `dm` memberships. It must not peek another member's DM or an
  unjoined thread and check membership afterward.
- Delete supplies all registered `channel`, `subthread`, and `dm` rows from
  `TautState.list_threads()` so an author can remove their own message after
  leaving. This broader scan may decode the target row even when it belongs to
  a DM between two other members. No decoded body, participant, thread, or
  existence detail from an ineligible row may reach the receipt, error text,
  warning, log, or MCP guidance.
- The locator stops at the first match because SimpleBroker message
  timestamps are globally unique within a broker. It does not query private
  broker tables, add a cache, or add a Taut message-index sidecar.
- The locator uses the default pending-only peek. A row already claimed by a
  foreign SimpleBroker consumer at lookup time is absent from Taut history and
  is not found. If it becomes claimed after lookup but before delete,
  SimpleBroker's delete may still physically remove it and return success;
  claimed and unclaimed rows are both eligible once queue and ID are known.
- The private locator returns an internal miss. Show maps it to
  `NotFoundError("message not found: MSG_ID")`. Delete maps a miss, ineligible
  row, or broker `False` to
  `NotFoundError("message not found or not deletable: MSG_ID")`. The delete
  wording and class stay identical for absent, foreign, notice,
  other-author, and nonparticipant-DM targets.
- Both verbs run the existing incomplete-channel-rename preflight before
  enumeration. They fail with the existing resume guidance rather than
  scanning a registry whose queue names may be in transition.
- Show lookup is O(number of current memberships); delete lookup is O(number
  of registered chat threads). Do not add an index until measurements show
  these bounded interactive paths need one. If they do, prefer a public
  SimpleBroker global locator over a Taut cache.

### 2.2 `message show`

- `TautClient.show_message(msg_id: str) -> Message` resolves an existing
  acting member; it never creates a member. Ordinary identity resolution may
  refresh existing activity/claim evidence just as `read` does.
- The located row may be a Taut `message`, a structural `notice`, or a
  tolerant `foreign` row. It is decoded through the same `message_from_body`
  path as `read` and `log`.
- Only current memberships are searched. Show does not rejoin a departed
  channel, implicitly join an unjoined subthread, or inspect a nonparticipant
  DM. Departed-thread, unjoined-child, unrelated-DM, and absent IDs share the
  same not-found result.
- Membership rows whose registry row is absent or whose registered kind is
  `notification` are skipped, matching `read_unread()`.
- After successful decode and membership resolution, show calls
  `TautState.advance_cursor(thread=..., member_id=..., seen_ts=message.ts)`.
  The existing monotonic SQL update is the only seen-state write. This plan
  does not add a per-message seen table.
- The cursor is a high-water mark. Showing a message newer than the stored
  cursor marks that message and every earlier timestamp in the thread as seen,
  including intervening rows that were not returned by this call. Showing a
  message at or below the cursor returns it without regressing or otherwise
  changing the cursor.
- Cursor advancement occurs before the `Message` is returned to the adapter.
  If the sidecar update fails, the call fails and emits no successful record.
- A concurrent leave after the membership snapshot can delete the membership
  before `advance_cursor()`. The existing update then affects zero rows and
  show may still return the fetched message. This invocation-snapshot race is
  accepted; the plan does not claim linearizable membership or add a row-count
  return to the state API.
- The broker peek and sidecar cursor update cannot form one cross-store
  transaction. A concurrent delete after the peek may still allow show to
  return the already-fetched message and advance to its now-missing ID. This is
  the same safe high-water race accepted for `read` and watcher delivery.
- `show` is not a claim and does not remove or reserve the broker row.
- Human and JSON CLI output reuse the ordinary one-message rendering contract.
  MCP returns `record_type="message"` and the existing message record shape.
- The `show` name is retained by owner direction even though the operation
  moves seen state. Every help and tool description must state the cursor
  effect in its first sentence and point to known-thread `log` for
  cursor-neutral inspection.

### 2.3 `message delete`

- `TautClient.delete_message(msg_id: str) -> MessageDeletion` resolves an
  existing acting member; it never creates a member or membership. Ordinary
  identity resolution may refresh existing activity/claim evidence.
- Only a decoded row with `kind == "message"` and
  `from_id == acting_member.member_id` is eligible. Structural notices,
  foreign rows, and another member's messages use the same
  `NotFoundError("message not found or not deletable: MSG_ID")` result as a
  missing ID. This uniform class and wording avoid a nonparticipant-DM
  existence oracle while remaining honest for a visible but ineligible row.
- Author ownership is an accident-prevention rule, not an authorization
  boundary. Taut's `--as`, token selection, and storage-access trust model
  remain unchanged.
- Prior or current thread membership is not required for deletion. An author
  may delete their own ordinary message after leaving its channel or
  subthread. The asymmetry is deliberate: a departed author may be unable to
  use `show` to inspect the row first, and DM history has no cursor-neutral
  `log` path. User-facing docs must warn that post-departure deletion can be
  blind and irreversible.
- After lookup and policy checks, delete calls exactly
  `queue.delete(message_id=message.ts)`. It must never call `delete()` with
  `None`, because SimpleBroker interprets that as a whole-queue purge.
- A `False` result from the broker, including a concurrent winner or repeated
  delete, maps to the same `NotFoundError` path. There is no tombstone and no
  attempt to distinguish never-existed, already-deleted, wrong-queue, or lost
  prior success.
- Success returns immutable
  `MessageDeletion(thread: str, ts: int, deleted: bool = True)`. It does not
  echo deleted body text, author identity, or other source content.
- The CLI human form is
  `deleted message MSG_ID from THREAD`. JSON and MCP use a dedicated
  `record_type="deletion"` record with exactly
  `{"thread": THREAD, "ts": MSG_ID_AS_INTEGER, "deleted": true}` plus the
  adapter's ordinary result envelope. `ts` remains a JSON integer to match the
  existing message record, even though native IDs exceed JavaScript's exact
  integer range. MCP input remains a string; tool descriptions tell
  JavaScript consumers to preserve returned IDs as decimal text before reuse.
- Delete does not move or rewind any member cursor. Numerical cursors may
  continue to point at the deleted ID, and future reads skip the gap.
- Delete does not cascade to notification pointers, DM registry state,
  memberships, member metadata, thread registry rows, reply subthreads,
  watcher state, or Summon audit state.
- Deleting a reply root is allowed even when a registered child subthread
  exists. The child remains addressable and existing members may continue
  using `say CHILD`. A new `reply PARENT DELETED_ID` fails because the parent
  lookup no longer resolves. This is the explicit no-cascade policy, not an
  accidental invariant.
- Deleting the first or only DM message leaves the deterministic DM registry
  and both membership rows intact. A later DM reuses the same queue and does
  not emit a second `dm_started` notification.
- Delete is not recall. A reader or watcher that fetched the row before the
  delete committed may still display it once.
- A row located while pending may become foreign-claimed before
  `Queue.delete()`. Delete still removes it and returns the normal receipt;
  this does not claim or cascade any other row.

### 2.4 Notification and renderer consequences

- Existing mention, reply, and `dm_started` notification rows survive source
  deletion unchanged. Their `message_ts` becomes a potentially stale pointer.
- Update [IAN-7] language that currently promises durable source history.
  Notifications are durable pointers; the source may later be deleted.
- Human mention rendering must not advertise a `taut reply` action when the
  source row no longer exists. Its check must use a read-only exact
  `peek_one()` against `notification.thread`; it must not call
  `show_message()`, because rendering an inbox must not advance a chat cursor.
- MCP notification-resource snapshots remain notification-derived. Deleting a
  source message does not itself create a resource update because no
  notification row changed.

### 2.5 CLI, Python, and MCP matrix

| Surface | Show | Delete |
|---|---|---|
| CLI | `taut message show MSG_ID` | `taut message delete MSG_ID` |
| Python | `show_message(msg_id: str) -> Message` | `delete_message(msg_id: str) -> MessageDeletion` |
| MCP | `show_message(workspace, msg_id)` | `delete_message(workspace, msg_id)` |
| Success record | existing `message` | new `deletion` |
| Well-formed miss | CLI exit 2 / Python `NotFoundError` / MCP empty message result | CLI exit 2 / Python `NotFoundError` / MCP empty deletion result |
| Malformed ID | CLI exit 1 / Python `TypeError` or `ValueError` / MCP schema rejection or domain error | same |
| MCP hints | read-only false; destructive true; idempotent false; open-world true | read-only false; destructive true; idempotent false; open-world true |

Both tools use `idempotentHint=false`: ordinary member resolution refreshes
activity evidence on every successful dispatch, and the first call also
changes a cursor or message row. Storage deletion itself converges on repeat,
but the complete Taut operation is not state-idempotent. This matches existing
member-resolving MCP tools such as `read`, `list`, `who`, and `whoami`; the
cursor-neutral, member-neutral `log` tool remains idempotent.

The new core noun reserves the normalized top-level command name `message`.
Core built-ins retain precedence over an installed third-party command with the
same normalized name. Add a compatibility test and document this namespace
claim.

## 3. Source Documents

Source specs:

- `docs/specs/01-development-documentation-operating-model.md` [DOM-5],
  [DOM-6], [DOM-10], [DOM-11], [DOM-15]
- `docs/specs/02-taut-core.md` [TAUT-1], [TAUT-3.3], [TAUT-3.4],
  [TAUT-4.1]–[TAUT-4.3], [TAUT-6], [TAUT-7.1]–[TAUT-7.3], [TAUT-8.1]–[TAUT-8.3],
  [TAUT-8.6], [TAUT-9], [TAUT-10], [TAUT-11]
- `docs/specs/03-identity-addressing-notifications.md` [IAN-5.2],
  [IAN-6.4], [IAN-7]
- `docs/specs/05-taut-mcp.md` [MCP-5], [MCP-6], [MCP-9], [MCP-10],
  [MCP-11], [MCP-12]

Implementation context:

- `taut/client/_messaging.py`
- `taut/client/_models.py`, `taut/client/__init__.py`, `taut/__init__.py`
- `taut/state/__init__.py`, `taut/state/_sql.py`
- `taut/commands/set.py`, `taut/commands/_builtins.py`,
  `taut/commands/_rendering.py`, `taut/commands/_dispatch.py`
- `extensions/taut_mcp/taut_mcp/_tools.py`
- `extensions/taut_mcp/taut_mcp/_commands.py`
- `extensions/taut_mcp/taut_mcp/_workspace_reactor.py`
- `docs/implementation/02-repository-map.md`
- `docs/implementation/04-taut-architecture.md`
- `docs/implementation/06-command-extensions.md`
- `docs/implementation/07-taut-mcp-architecture.md`
- `README.md`, `extensions/taut_mcp/README.md`, `CHANGELOG.md`

Dependency implementation:

- `../simplebroker/simplebroker/sbqueue.py::Queue.peek_one`
- `../simplebroker/simplebroker/sbqueue.py::Queue.delete`
- `../simplebroker/simplebroker/_message_id.py`
- SQLite and PostgreSQL delete implementations and shared delete contract tests

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

## 4. Baseline and Promotion Strategy

- Baseline commit: `e807454d51afa35e05497a1a668ef45f0d2c73c6`.
- The worktree was clean before this plan and its index entry were created.
- Taut already requires SimpleBroker versions that contain exact 19-digit
  string validation and physical delete on SQLite and PostgreSQL. No
  SimpleBroker dependency-floor change is required for the core primitive.
- The active specs remain canonical until promotion.
- Promotion strategy: **A, exact in-file requirement text before behavior
  implementation**. Amend the active core, identity/notification, and MCP
  specs; add Related Plans backlinks; run the documentation gate; and record
  the promotion baseline before production-code edits.
- This plan must not silently preserve the old append-only claims. [TAUT-1],
  [TAUT-7.1], and [IAN-7] require direct revision.
- Implementation may choose the next unpublished coordinated core/MCP version
  only with repository-owner direction. If MCP ships these tools, its declared
  core dependency floor and lockfile must name the first core version that
  exports both methods and `MessageDeletion`. Release and publication remain
  out of scope.
- Promotion baseline: uncommitted worktree based on
  `e807454d51afa35e05497a1a668ef45f0d2c73c6`. The three active specs were
  promoted before behavior code changed. Post-promotion SHA-256 values:
  - `docs/specs/02-taut-core.md`:
    `b192b2d199c139876c11673d9884282a4c583d94b3b4898ab0755227eb050ccf`
  - `docs/specs/03-identity-addressing-notifications.md`:
    `15e09ceb905ccdf60f88d1caff0bd61fde8ce18ecd4a949c6f7921a66679f923`
  - `docs/specs/05-taut-mcp.md`:
    `04899ea9d4c82e0ad7a03b179d5ae43d8e8ac3d6122ee5eb6b01ef810269deda`
  Verification: `tests/test_docs_references.py` passed 10 tests and
  `git diff --check` passed. Bare `claude -p` returned
  `APPROVED WITH CONDITIONS`; the two blocking residual durable-source claims
  in [TAUT-7.4]/[TAUT-8.4] were corrected, the [TAUT-6] notice/foreign
  ineligibility cross-references were added, and the nonblocking scope/help
  wording findings were reconciled. No Slice 0 blocker remains.

## 5. Current Structure and Hidden Couplings

### 5.1 Exact lookup

`MessagingMixin._resolve_message_id(thread, msg_id)` already performs an exact
`peek_one()` when given a full ID, but it requires the caller to know the
thread and also owns reply-only suffix resolution. Do not overload it with
global lookup or destructive policy. Extract or add a narrowly named
full-ID validator and a candidate-scoped exact locator that both new methods
share, while keeping reply suffix behavior unchanged.

SimpleBroker IDs are global, but `Queue.delete()` remains queue-scoped. The
located queue must travel with the decoded `Message`; rediscovering it after
authorization adds a second scan and a larger race window.

### 5.2 Seen metadata

There is no per-message seen table. The current seen state is
`taut_membership.last_seen_ts`, updated by
`TautState.advance_cursor()`. The SQL update is monotonic and does not verify
that a broker row still exists. This is the correct primitive for show.

The high-water model means an exact read is not equivalent to a per-row read
receipt. Showing message N consumes unread status for all timestamps at or
below N in that thread. CLI help, Python docs, and MCP descriptions must say
this plainly so an agent does not use show for harmless inspection when it
needs cursor-neutral history. `log` remains the cursor-neutral tool when the
thread is known.

### 5.3 Membership and visibility

`read_unread()` requires membership and may implicitly join a subthread only
when the caller names that child thread explicitly. `log()` is cursor-neutral
and does not resolve an acting member. MID-only `show_message()` searches the
caller's current memberships and creates none: it cannot safely discover an
unjoined child by peeking every registered queue.

Delete authorization derives from the stored `from_id`, not current
membership. Requiring current membership would strand an author's content
after leave and would not improve the weak-trust security boundary. The cost
is that delete must inspect the exact target in all registered chat queues,
including a possible nonparticipant DM, and a departed DM author may have no
public way to re-inspect content before deleting. Uniform errors and
content-free receipts prevent that inspection from becoming an output leak.

### 5.4 Compound state and races

Broker message storage and the Taut sidecar are separate transactional
domains:

- Show peeks broker state, then updates the sidecar cursor.
- Delete reads and authorizes the broker row, then deletes it.
- A concurrent leave after show's membership snapshot can make the cursor
  update affect zero rows while the already-fetched message still returns.
- A row pending during delete lookup can become foreign-claimed before
  physical delete; SimpleBroker still deletes that exact claimed row.
- Thread rename state may change queue addresses, so both verbs use the
  existing incomplete-rename guard.
- No transaction can retract a message already fetched by another process.
- The no-cascade parent policy allows orphaned subthreads by contract, so a
  concurrent reply/delete race does not need a false cross-store atomicity
  guarantee.

### 5.5 Adapter shape

`taut set name` is the existing nested-parser precedent. Add one lightweight
`message` builtin manifest and one lazy `taut/commands/message.py` adapter with
required `show` and `delete` subparsers. Do not add two top-level verbs.

MCP has a fixed manifest independent of CLI discovery. It currently defines 15
tools and a closed record-schema set. This change raises the tool count to 17,
maps `show_message` to the existing message schema, and adds a deletion schema
and renderer path. `_tools.py` and `_commands.py` own separate
`RECORD_TYPE_BY_TOOL` maps; both must change. `_commands.py` also needs its
stale tool-count docstring updated, and `CommandRecord`/`record_object` must
accept `MessageDeletion`.

### 5.6 Comprehension gate

Before editing production code, the implementer must answer:

1. Why can Taut not call `Queue.delete(message_id=msg_id)` without first
   locating the registered queue?
2. Why must malformed IDs fail before enumeration, and why must `None` never
   reach `Queue.delete()`?
3. Why does showing one newer row mark unseen intervening rows as seen?
4. Why does show require membership while delete uses author identity
   independent of membership?
5. Why may a successful peek still return a row concurrently deleted before
   cursor advancement?
6. Which functions may inspect source existence without advancing the cursor,
   and why must notification rendering not call `show_message()`?
7. What remains after deleting the only DM message or a reply root?
8. Why is `idempotentHint=false` even though repeated broker deletion has no
   further message-storage effect?

Stop and revise the plan if message IDs are no longer globally unique, if
`Queue.peek_one(exact_timestamp=...)` claims rows, if `Queue.delete()` changes
to accept a global ID without a queue, or if Taut replaces its one-cursor
high-water model with per-message seen state.

## 6. Proposed Spec Delta

Promotion strategy: **A**.

| Spec | Required sections |
|---|---|
| `docs/specs/02-taut-core.md` | revise [TAUT-1] and [TAUT-7.1]; extend [TAUT-4], [TAUT-6], [TAUT-7.2], [TAUT-8.1]–[TAUT-8.3], [TAUT-8.6], [TAUT-9], [TAUT-10], [TAUT-11], Related Plans |
| `docs/specs/03-identity-addressing-notifications.md` | subthread and DM consequences in [IAN-5]/[IAN-6]; stale-source notification contract in [IAN-7]; Related Plans |
| `docs/specs/05-taut-mcp.md` | 17-tool manifest and descriptions in [MCP-5]; deletion schema in [MCP-6]; instructions in [MCP-9]; trust/failure/proof updates in [MCP-10]–[MCP-12]; Related Plans |

The promoted text must enumerate, not merely imply:

- exact full-ID-and-range input and validation ordering;
- candidate-scoped pending-only lookup;
- show current-membership policy and absence of implicit join;
- show's monotonic high-water cursor effect;
- author-only ordinary-message deletion;
- uniform absent-or-not-deletable errors with no DM-content leak;
- delete-after-leave behavior;
- blind post-departure deletion warning;
- no cascade and allowed orphaned subthreads;
- stable DM registry and no repeated `dm_started`;
- stale notification pointers and corrected reply-action rendering;
- already-fetched delivery and cross-store race semantics;
- concurrent leave and locate-then-claim race semantics;
- Python value objects, CLI exit classes, MCP record types and annotations;
- integer deletion `ts` output and JavaScript precision guidance;
- show O(memberships), delete O(threads), and the absence of a cache/index;
- real SQLite/PostgreSQL and adapter proof obligations.

## 7. Invariants and Constraints

### 7.1 Must change

- Full-ID messages become globally addressable through a registered-chat
  locator.
- Show returns one decoded message and advances only the acting member's
  located-thread cursor monotonically.
- Delete physically removes one eligible author-owned ordinary message.
- CLI, Python, and MCP expose both capabilities with aligned names and result
  semantics.
- Notification rendering stops presenting an unusable reply action for a
  deleted source.

### 7.2 Must not change

- Reply suffix resolution and its most-recent-1,000 ambiguity rules.
- `read`, `log`, inbox, watch, say, reply, join, leave, rename, and list
  behavior except for their documented interaction with deleted gaps.
- Message-envelope tolerance for notices and foreign rows.
- Existing cursor monotonicity and one-high-water-per-membership model.
- DM deterministic naming, membership, and first-contact lifecycle.
- Notification pointer consumption and MCP notification-resource derivation.
- Taut's weak-trust boundary.
- SimpleBroker schema, private tables, queue aliases, or dependency floors.
- Root and command-help lazy-import guarantees.

### 7.3 Anti-mocking rules

- Storage semantics must run against real SQLite and real PostgreSQL through
  the shared public client contract. Do not mock `Queue.peek_one`,
  `Queue.delete`, `list_threads`, membership state, or cursor SQL for the
  integration proof.
- Focused unit doubles are allowed only to prove call ordering, invalid-input
  no-side-effect behavior, or an injected failure between broker peek and
  sidecar update. They do not substitute for backend tests.
- CLI tests must execute the real parser/dispatcher and client, not call the
  adapter method directly.
- MCP tests must exercise the real fixed manifest and workspace-reactor
  command path. A schema-only assertion does not prove cursor or delete
  behavior.
- Concurrency tests need deterministic barriers around fetch/delete or
  delete/delete. Do not rely on sleeps.

## 8. Dependency-Ordered Implementation Tasks

### Slice 0: Promote and verify the contract

Owner: core/spec implementer.

Boundary: documentation only.

Actions:

1. Amend the three active specs with the complete contract in section 6.
2. Add Related Plans backlinks and this plan to `docs/plans/README.md`.
3. Update spec indexes only if their summaries become false.
4. Run the docs-reference suite and `git diff --check`.
5. Record the promoted-spec baseline and independent review disposition here
   before behavior code starts.

Verification:

```bash
uv run --extra dev pytest tests/test_docs_references.py -q -n0
git diff --check
```

Review gate: independent reviewer checks that old append-only and durable-source
claims were removed everywhere, not papered over by additive text.

### Slice 1: Add red core contracts and the shared locator

Owner: core implementer.

Boundary: core tests and private lookup helpers; no CLI or MCP changes.

Actions:

1. Add firing tests for input validation, candidate-scoped exact lookup,
   member/membership policy, cursor effects, author policy, and receipts.
2. Add one private validated exact-ID representation or helper using the
   public exact `TimestampGenerator` validator for both shape and signed-int64
   range. Keep reply suffix behavior isolated.
3. Add one private located-message structure carrying thread, queue, decoded
   message, and exact timestamp/body evidence needed by both verbs.
4. Implement pending-only enumeration using public state and queue APIs;
   show passes current memberships and delete passes registered chat threads.
5. Prove incomplete-rename refusal and no cache/private SQL.

Verification: focused red tests fail because the public methods and locator do
not exist, then pass after the smallest core implementation.

Review gate: independent slice review checks validation-first ordering,
candidate visibility, O(thread) bounds, global-uniqueness reliance, and queue
ownership.

### Slice 2: Implement show, delete, and public values

Owner: core implementer.

Boundary: `taut/client`, public exports, core tests, and shared backend tests.

Actions:

1. Add frozen slotted `MessageDeletion`.
2. Add `show_message()` with member resolution, current-membership-only
   candidate selection, tolerant decode, and pre-return monotonic cursor
   advance.
3. Add `delete_message()` with author/kind filtering and exact
   `Queue.delete(message_id=...)`.
4. Preserve `NotFoundError` as the well-formed empty class, with the distinct
   show and delete wording decided in section 2.
5. Prove a nonparticipant DM delete target emits no body, participant, thread,
   or existence detail.
6. Add deterministic concurrency and compound-failure tests, including
   show/leave and locate/claim/delete.
7. Run the same shared contracts on SQLite and PostgreSQL.

Verification:

```bash
uv run --extra dev pytest tests/test_client.py tests/test_state_contract.py tests/test_shared_contract.py -q
bin/pytest-pg tests/test_shared_contract.py
```

The exact command may be narrowed during red/green work, but final proof must
include the ordinary SQLite shared suite and repository PostgreSQL wrapper.

Review gate: independent slice review checks that show cannot claim, delete
cannot purge a queue, author filtering cannot be bypassed through notices, and
cursor advancement matches the returned timestamp.

### Slice 3: Add the nested CLI noun

Owner: CLI implementer.

Boundary: builtin manifest, lazy command module, shared rendering, CLI tests.

Actions:

1. Register the lightweight top-level `message` builtin.
2. Add required `show` and `delete` subparsers with `MSG_ID`.
3. Reuse ordinary message rendering for show.
4. Add deletion human/JSON rendering without source text.
5. Preserve global option placement and root/command help behavior.
6. Test installed-command collision ownership for the new reserved core name.
7. Extend public/lazy-import/architecture assertions for the new command.

Verification:

```bash
uv run --extra dev pytest tests/test_cli.py tests/test_command_registry.py tests/test_public_api.py tests/test_architecture_boundaries.py -q
```

Review gate: CLI review checks stdout/stderr/exit behavior, exact help wording,
JSON records, namespace conflict handling, and no eager messaging/MCP import.

### Slice 4: Add fixed MCP tools

Owner: MCP implementer.

Boundary: MCP manifest, command adapter, record schemas, server instructions,
tests, and MCP docs.

Actions:

1. Add `show_message` and `delete_message` to the fixed 17-tool manifest with
   exact `msg_id` string patterns and decided annotations.
2. Route both through public client methods in `_commands.py`.
3. Map show to `record_type="message"` and add
   `record_type="deletion"` plus its closed schema.
4. Update both `RECORD_TYPE_BY_TOOL` maps, the `CommandRecord` union,
   `record_object`, and the stale CLI-shaped-tool count docstring.
5. Preserve empty-result mapping: a missing show/delete is successful MCP
   completion with `empty=true`, the tool's record type, and no records.
6. Give an empty delete result content-free guidance that says no matching
   deletable own message was found, without distinguishing absence,
   ineligibility, or unrelated DM.
7. Update server instructions to distinguish `show_message` from cursor-neutral
   `log`, warn that show may mark intervening history seen, and preserve
   19-digit output IDs as decimal text in JavaScript consumers.
8. Prove workspace isolation, busy handling, rate limiting, and error
   sanitization still cover all 17 tools.
9. Update exact tool-count and record-type matrices.

Verification:

```bash
uv run --directory extensions/taut_mcp --extra dev pytest -q
```

Review gate: MCP review checks annotations against actual state effects, the
decided integer `ts` schema and precision guidance, output schema closure, both
record-type maps, and no accidental exposure through dynamic CLI discovery.

### Slice 5: Reconcile stale-pointer UX and implementation docs

Owner: documentation and integration implementer.

Boundary: notification rendering, public docs, architecture docs, changelog,
and cross-reference tests.

Actions:

1. Change mention reply-action detection to a cursor-neutral exact source
   peek; omit the action when absent.
2. Document stale pointers, orphaned child threads, empty DM persistence,
   already-fetched delivery, cursor gaps, post-departure blind deletion, and
   non-recall semantics.
3. Update repository map, core architecture, command-extension architecture,
   and MCP architecture.
4. Add copy-paste CLI, Python, and MCP examples.
5. Add an Unreleased changelog entry. Do not claim a version or release.
6. Evaluate whether the implemented lookup or review process exposed a durable
   lesson; update `docs/lessons.md` only if the lesson generalizes.

Verification:

```bash
uv run --extra dev pytest tests/test_docs_references.py tests/test_cli.py -q -n0
git diff --check
```

Review gate: documentation review checks that each public surface says show
moves seen state and delete is physical, author-only, no-cascade, and not
recall.

### Slice 6: Full verification and completed-work review

Owner: implementing engineer; review by a different agent family.

Actions:

1. Run focused core, shared-backend, CLI, MCP, docs, typing, lint, and package
   metadata gates.
2. Apply the adversarial acceptance probes in section 9.
3. Run an independent completed-work review with the full diff and evidence.
4. Incorporate or explicitly answer every finding.
5. Update this plan's status, evidence table, and review record.
6. Leave commit and release actions to the repository owner.

Minimum final commands:

```bash
uv run --extra dev pytest -q
bin/pytest-pg
uv run --directory extensions/taut_mcp --extra dev pytest -q
uv run --extra dev ruff check .
uv run --extra dev mypy taut
git diff --check
```

Use the repository's current canonical aggregate gates if they supersede these
commands at implementation time. Record exact commands and observed results,
not intentions.

## 9. Test Diagram and Adversarial Acceptance Probes

| Flow or branch | Required firing proof |
|---|---|
| ID type/shape/range | in-range 19-digit string succeeds; short suffix, letters, whitespace, sign, 18/20 digits, 19-digit signed-int64 overflow, `int`, `bool`, and `None` fail before identity/activity, lookup, or state mutation |
| Candidate-scoped locator | show searches current registered chat memberships only; delete searches all registered chat threads; both skip notification, dangling, and unregistered rows; miss scans each candidate once; first match stops |
| Claimed row | row claimed before lookup is not found; deterministic claim after lookup but before delete is physically deleted with the ordinary receipt |
| Incomplete rename | both verbs refuse before enumeration and preserve resume guidance |
| Show decode | ordinary, notice, and foreign chat bodies return the existing `Message` shape |
| Show membership | joined channel succeeds; left/nonmember channel fails; DM participant succeeds; nonparticipant fails; unjoined child is not searched; dangling/notification memberships are skipped; no membership is created |
| Show cursor below/equal | message returns; cursor does not regress |
| Show cursor ahead | cursor becomes target ID and intervening rows become read by high-water semantics |
| Show failure | injected cursor-write failure emits no success; real broker row remains |
| Show/delete race | deterministic delete after peek may still return fetched show record and advance safely; later reads continue |
| Show/leave race | deterministic leave after membership snapshot may let the fetched message return while the zero-row cursor update leaves no membership |
| Delete ownership | own ordinary message deletes; another author's message, notice, and foreign body receive the uniform absent-or-not-deletable result and remain |
| Delete unrelated DM | exact target in another pair's DM receives byte-identical absent-or-not-deletable output; row and DM state remain; no body, participant, or thread detail reaches output, warning, or log |
| Delete after leave | author may delete own row without recreating membership; docs warn that pre-delete inspection may be unavailable, especially for DMs |
| Delete repeat/concurrency | first winner gets one receipt; repeats/concurrent losers get not found; no queue purge |
| Cursor gap | delete below, at, above, newest, oldest, and only row; stored cursor unchanged; later writes remain readable |
| Unread/list | unread and `last_ts` recompute from surviving rows; accepted one-call concurrent staleness converges on next call |
| DM lifecycle | delete first/only DM; registry and memberships identical; list-all shows empty; later DM reuses thread; no second `dm_started` |
| Subthread lifecycle | delete root with child; child registry/history/membership survive; list/thread rendering remains well-formed; direct child say works; new root-based reply fails |
| Notifications | mention/reply/DM pointers remain byte-for-byte; source body is absent; mention renderer emits no dead reply action |
| Watcher | delete before fetch skips; delete after fetch may display once; cursor remains safe; stale failure-key cleanup is optional hygiene, not a correctness gate |
| CLI parsing | nested help, required subcommand/ID, global options before/after noun, human/JSON/quiet output, exit 0/1/2, stdin irrelevance |
| CLI registry | root help lists `message`; core owns normalized collision; unrelated installed commands remain available |
| Python exports | both methods and `MessageDeletion` are reachable through documented facades without eager optional imports |
| MCP schemas | exactly 17 tools; exact input patterns plus core range rejection; show message schema; deletion closed schema with integer `ts`; both record-type maps and command union align; every tool has all four annotations |
| MCP execution | real attached workspace shows and advances cursor; deletes and returns receipt; misses return typed empty; isolation/busy/rate-limit paths remain |
| Backends | shared show/delete semantics fire on real SQLite and PostgreSQL |

Enumerable contract rule: every error class, output field, annotation, thread
kind, message kind, cursor relation, and listed race above needs a firing test.
Table-driven tests are preferred where they keep failures legible.

## 10. Failure Modes and Recovery Registry

| Failure | Observable result | State after failure | Recovery |
|---|---|---|---|
| Malformed or out-of-range ID | validation error / CLI 1 / MCP schema or domain validation error | no identity/activity, lookup, or state side effect | supply an in-range full 19-digit native ID |
| Well-formed miss or inaccessible show target | `NotFoundError` / CLI 2 / MCP typed empty | no cursor movement; ordinary existing-member activity resolution may have refreshed evidence | join the thread or use known-thread `log` if policy permits |
| Show cursor write fails | error, no success record | broker and cursor unchanged; ordinary member activity may already be refreshed | repair sidecar/backend and retry |
| Concurrent leave during show | fetched message may return | membership is gone; cursor update affects zero rows | accepted invocation-snapshot race; rejoin for later seen tracking |
| Delete loses race | not found / typed empty | winner's delete persists | treat repeat as converged |
| Row claimed after delete lookup | ordinary success receipt | exact claimed row is physically gone | no recovery; foreign consumer already treated it as deletion-pending |
| Delete response lost | retry returns absent-or-not-deletable; success cannot be distinguished from prior absence | row may already be gone | no reliable inspection exists after departure; no tombstone is added |
| Parent deleted | root lookup fails | child registry and queue survive | address child directly; no automatic repair |
| Notification source deleted | pointer still renders, without reply action when source absent | notification remains consumable | consume/dismiss normally |
| DM sole row deleted | DM queue may vanish from broker queue listing | Taut registry/memberships persist | later DM recreates broker-visible queue under same name |
| Concurrent list/delete | one list result may be stale | next list converges | rerun list |
| Already-fetched delivery | reader/watcher may display once | cursor may advance to deleted numeric ID | no recovery needed; this is not recall |
| Partial/incomplete rename | explicit refusal | no new show/delete work | resume rename, then retry |

## 11. Hardening Checklist

Plan-design checks:

- [x] Public contracts and non-goals are explicit.
- [x] Destructive target is one validated full ID in one located queue.
- [x] Owner, boundary, required action, and verification are stated per slice.
- [x] Broker/sidecar transaction boundary and accepted partial states are
  explicit.
- [x] Cursor high-water implication is explicit.
- [x] DM, subthread, notification, watcher, list, and foreign-row couplings are
  explicit.
- [x] Anti-mocking guidance requires real SQLite and PostgreSQL.
- [x] Rollout is additive at the parser/API level but reserves one core command
  namespace and changes history invariants.
- [x] Rollback is code/spec rollback before release. After users physically
  delete rows, rollback cannot restore those rows; backups are the only data
  recovery path.
- [x] No migration is required. The existing sidecar schema remains unchanged.
- [x] No feature flag or dual-write period is required because the verbs are
  explicit opt-in operations.
- [x] Post-release success signals are: successful exact show/delete calls,
  expected typed misses, no queue-purge incidents, no cursor regressions, and
  stable MCP error/busy rates.
- [x] Rollout order is core contract and methods first, CLI second, MCP adapter
  after its minimum core floor is available, then release only under the
  repository's coordinated release process.

Implementation-evidence gates:

- [x] Whole-queue `None` hazard has a firing no-purge test.
- [x] Input range validation is proved before identity/activity work.
- [x] Unrelated-DM delete lookup is proved content-free at every adapter.
- [x] Deterministic show/leave and locate/claim/delete races pass.
- [x] The promoted spec baseline is recorded.
- [x] Red/green evidence is recorded for every slice.
- [x] Real SQLite and PostgreSQL shared contracts pass.
- [x] CLI and MCP adapter suites pass with exact schema/help snapshots.
- [x] Independent completed-work review has no unresolved blocker.

Implementation hardening remains incomplete until every evidence gate above is
checked with an exact command and observed result.

## 12. Out of Scope

- Cascading deletion of notifications, child threads, memberships, or audit
  records.
- Tombstones, undo, trash, retention windows, purge jobs, or content recovery.
- Admin/moderator deletion or a stronger authorization model.
- Bulk deletion or delete-by-filter.
- Message editing.
- Per-message read receipts or a new seen table.
- Cursor-neutral global exact lookup as a separate public verb. `show` is
  intentionally cursor-mutating; known-thread `log` remains cursor-neutral.
- A persistent message-ID-to-thread index or cache.
- Delete event broadcast, remote recall, or watcher retraction.
- SimpleBroker schema/API changes.
- Release, tag, or publication work.

## 13. Independent Review Loop

### Plan review

- Reviewer: a different model family from the author, invoked read-only with
  bare `claude -p` as requested by the repository owner.
- Time allowance: up to 15 minutes.
- Reviewer reads this plan, the cited spec sections, core messaging/state code,
  SimpleBroker public peek/delete paths, CLI command registry, and MCP
  manifest/result code.
- Required challenge areas: high-water seen semantics, membership visibility,
  delete authorization, `None` purge prevention, no-cascade parent/DM effects,
  cross-store races, MCP annotations/schema, exact test coverage, and rollout.
- Verdict vocabulary: `APPROVED`, `APPROVED WITH CONDITIONS`, or `BLOCKED`.
- Every finding is incorporated or answered in section 15 before this plan is
  considered reviewed.

### Slice and completed-work review

- Run an independent review after spec promotion, after the core slice, after
  the adapter slice, and on the complete diff.
- A reviewer receives the current plan, relevant spec delta, complete slice
  diff, red/green commands, and observed output.
- Do not accept a review that inspects only tests or only production code.
- Completion requires the final reviewer to verify enumerable contract
  coverage, real-backend evidence, docs alignment, and absence of unrelated
  edits.

## 14. Fresh-Eyes Review

Before implementation starts, a fresh reader should be able to answer:

1. What exact row can each verb touch?
2. Which state does show mutate, and what extra history becomes seen?
3. Why can delete work after leave but show cannot?
4. What survives deletion of a DM row or reply root?
5. What does a stale notification do?
6. What happens when a response is lost or another process wins the race?
7. Which tests are real-backend tests and which may use a fault-injection
   double?
8. How are all six public surfaces kept semantically aligned?

Fresh-eyes reviewers must flag any requirement that lacks an owner, boundary,
verification step, or required action.

## 15. Review Findings and Dispositions

Bare `claude -p` reviewed the plan read-only on 2026-07-27 and returned
`APPROVED WITH CONDITIONS`. All five promotion-blocking conditions and five
lower-severity findings were incorporated:

| ID | Severity | Disposition |
|---|---|---|
| MSD-R1 | High | Incorporated. Taut validates both the 19-digit shape and public `TimestampGenerator` signed-int64 range before identity/activity or lookup; the overflow case is a firing probe. |
| MSD-R2 | High | Incorporated. Delete's all-thread scan explicitly admits possible nonparticipant-DM decode, forbids every output/log leak, and adds a byte-identical absent-target probe. |
| MSD-R3 | Medium | Incorporated. The plan now distinguishes claimed-at-lookup from locate-then-claim and accepts SimpleBroker's exact claimed-row deletion in the latter race. |
| MSD-R4 | Medium | Incorporated. Deletion `ts` is explicitly an integer matching existing message records; MCP docs carry JavaScript precision guidance while input stays a string. |
| MSD-R5 | Medium | Incorporated. Delete keeps uniform `NotFoundError` for privacy but uses honest `message not found or not deletable` wording and content-free MCP guidance. |
| MSD-R6 | Low | Incorporated. Concurrent leave may make show's cursor update affect zero rows while the fetched message returns; the plan no longer claims linearizability. |
| MSD-R7 | Low | Incorporated. Show skips dangling and notification-kind membership rows and tests both branches. |
| MSD-R8 | Low | Incorporated. Slice 4 names both MCP record-type maps, `CommandRecord`, `record_object`, and the stale count docstring. |
| MSD-R9 | Low | Incorporated. The plan and public-doc task disclose blind irreversible deletion after departure, especially for DMs. |
| MSD-R10 | Informational | Incorporated. Plan-design checks remain checked; all test-dependent hardening gates are now visibly pending. |

Review answers retained as explicit decisions:

- Current-membership-only show lookup is correct. A MID does not express intent
  to join an unknown child thread or inspect an unrelated DM.
- Ineligible delete keeps the not-found class to avoid a DM existence oracle;
  uniform wording states both absence and ineligibility honestly.
- Both MCP tools remain non-idempotent because existing-member resolution
  refreshes activity evidence on each dispatch.
- No-cascade parent deletion is honest only with permanent orphan-child,
  rendering, reply-failure, and claimed-row race tests.
- No schema migration is required.

The bare `claude -p` confirmation review verified MSD-R1 through MSD-R10
against current Taut and SimpleBroker code. It found one new low-severity
verification-path typo:

| ID | Severity | Disposition |
|---|---|---|
| MSD-C1 | Low | Incorporated. Slice 3 now invokes the existing `tests/test_architecture_boundaries.py`, verified present, instead of nonexistent `tests/test_architecture.py`. |

Confirmation verdict: `APPROVED WITH CONDITIONS`; the sole condition was
MSD-C1, now corrected. The reviewer explicitly authorized Slice 0 spec
promotion. No unresolved plan-review finding remains.

Bare `claude -p` then reviewed the completed diff on 2026-07-27. Its initial
verdict was `NOT APPROVED` because evidence and copy remained incomplete; it
found no production-code correctness defect. The implementation changed during
that review, so every finding was rechecked against the later quiescent tree:

| ID | Severity | Disposition |
|---|---|---|
| MSD-I1 | Medium | Incorporated. Status, implementation gates, exact commands, and observed results are recorded here. |
| MSD-I2 | Medium | Incorporated. `taut inbox` help now says a pointer may outlive an explicitly deleted source. |
| MSD-I3 | Medium | Incorporated. Core, CLI, and MCP each prove unrelated-DM deletion is content-free and indistinguishable from absence. |
| MSD-I4 | Medium | Incorporated. A DM participant now has a firing show-success and cursor-advance test. |
| MSD-I5 | Medium | Incorporated. MCP execution now fires the in-pattern signed-int64 overflow through both tools. |
| MSD-I6 | Medium | Answered with observed evidence. The implementing session ran the Docker wrapper: 197 shared PostgreSQL tests and 14 `taut-pg` tests passed; all five live MCP PostgreSQL tests also passed. |
| MSD-I7 | Low | Incorporated. The reviewer observed a test file while it was being edited. Two consecutive full-suite runs on the quiescent final tree passed with only the existing Windows-only skip. |
| MSD-I8 | Low | Incorporated. Missing-id, human show rendering, and stdin-irrelevance CLI probes now fire. |
| MSD-I9 | Low | Incorporated. Focused doubles prove candidate lookup stops after one exact match and delete passes one non-null exact id. |
| MSD-I10 | Low | Incorporated. Subthread post-leave deletion, empty-DM list state, concurrent list/delete convergence, and cursor-neutral stale-pointer rendering now fire. DM has no public leave operation. |
| MSD-I11 | Low | Incorporated. Public method docstrings state the effects, and README calls post-departure deletion blind and irreversible. |

The bare `claude -p` confirmation review returned `VERDICT: APPROVED`. It
verified MSD-I1 through MSD-I11 against the quiescent tree and found no
remaining blocker. Its residual risks are the accepted races, non-recall,
stale-pointer, precision-guidance, blind-deletion, and no-tombstone properties
already recorded in this plan and the promoted specs.

## 16. Verification Record

Plan-authoring and implementation evidence are recorded here.

| Gate | Result |
|---|---|
| Baseline | `e807454d51afa35e05497a1a668ef45f0d2c73c6` |
| Prior exploratory SQLite probes | DM, cursor, notification, subthread, and later-write behavior confirmed; no production files changed |
| Prior SimpleBroker focused proof | 18 targeted SQLite deletion tests passed |
| Independent design review | no blocker; conditions incorporated into this plan |
| Bare `claude -p` plan review | initial MSD-R1–R10 incorporated; confirmation verified all dispositions and authorized Slice 0; MSD-C1 corrected; no unresolved finding |
| Documentation references | `uv run --extra dev pytest tests/test_docs_references.py -q -n0`: 10 passed after final review disposition |
| Diff whitespace | `git diff --check`: passed after final review disposition |
| Core red/green | show tracer failed on absent method, then passed; delete tracer failed on absent public receipt, then passed; stale-pointer CLI tracer reproduced a dead reply action, then passed after cursor-neutral exact revalidation |
| CLI red/green | first exact-show tracer failed with `unknown command: message`; delete tracer failed while only show existed; focused message, registry, lazy-import, help, rendering, and exit tests passed after implementation |
| MCP red/green | focused tests first failed on missing registration, dispatch, schemas, encoding, and owner-thread execution; the complete package suite then passed with five expected no-DSN skips |
| Final root suite | `uv run --extra dev pytest -q`: passed twice consecutively on the quiescent tree; one existing Windows-only filename test skipped on macOS |
| PostgreSQL root/extension | `uv run --extra dev bin/pytest-pg --fast`: 197 shared tests passed; 14 `taut-pg` tests passed |
| PostgreSQL MCP | live Docker PostgreSQL run of `extensions/taut_mcp/tests -m pg_only -q -n0`: 5 passed |
| MCP package | `uv run --directory extensions/taut_mcp --extra dev pytest -q`: passed; five PostgreSQL tests skipped in the no-DSN run and passed in the live run |
| Quality | root and MCP Ruff check/format passed; `mypy taut` passed for 51 source files; MCP mypy passed for 16 source files |
| Completed-work review | bare `claude -p` initial MSD-I1–I11 findings incorporated or answered; confirmation verdict `APPROVED` with no open finding |
