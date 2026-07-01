# Member Identity, Addressing, and Notifications Plan

Status: Implemented
Created: 2026-06-18
Implemented: 2026-06-18

This plan may use `v1` and `v2` as shorthand:

- `v1` means the current development implementation: member handles are the
  durable identity in schema, membership, envelopes, and JSON output.
- `v2` means the intended model in the specs: stable opaque `member_id`,
  deterministic identity claim hashes, mutable names and aliases, `from_id`
  plus sender-name snapshots, `@alias` direct messages, and consumable
  per-member notifications.

The public specs do not need to define `v1` or preserve compatibility with it.
This plan uses those labels only so the implementing engineer can reason about
the migration.

## 1. Goal

Update the codebase from handle-as-identity to stable member ids with mutable
names, direct-message addressing, mention notifications, and notification
inboxes. Keep the implementation small and direct: one schema boundary, one
client semantics path, no long-lived compatibility readers, no extra
dependencies, and no speculative UI or permission system.

## 2. Source Documents

Source specs:

- `docs/specs/02-taut-core.md` [TAUT-3], [TAUT-4], [TAUT-5], [TAUT-6],
  [TAUT-7], [TAUT-8], [TAUT-10], [TAUT-11]
- `docs/specs/03-identity-addressing-notifications.md` [IAN-2] through
  [IAN-10]
- `docs/specs/01-development-documentation-operating-model.md` [DOM-5],
  [DOM-6], [DOM-8], [DOM-10], [DOM-11]

Required runbooks:

- `docs/agent-context/runbooks/writing-plans.md`
- `docs/agent-context/runbooks/hardening-plans.md`
- `docs/agent-context/runbooks/testing-patterns.md`
- `docs/agent-context/runbooks/maintaining-traceability.md`

Related implementation note:

- `docs/implementation/04-taut-architecture.md`

Related prior plans:

- `docs/plans/2026-06-12-taut-foundation-plan.md`
- `docs/plans/2026-06-18-simplebroker-latest-timestamp-plan.md`

## 3. Context and Key Files

Read these files before editing:

| File | Why it matters |
|---|---|
| `taut/_constants.py` | Version, schema version, thread/name validation, reserved names, identity constants |
| `taut/schema.py` | Only allowed sidecar SQL boundary; all `taut_*` DDL and state helpers belong here |
| `taut/identity.py` | Process-chain capture, anchor selection, token minting, candidate ranking |
| `taut/envelope.py` | Taut-written message body encode/decode and foreign fallback |
| `taut/client.py` | Single source of command semantics for CLI and Python API |
| `taut/cli.py` | Argparse command tree, JSON rendering, human rendering, exit codes |
| `taut/watcher.py` | Chat-history watcher and cursor advancement behavior |
| `tests/test_schema.py` | Current schema/version/cursor proof |
| `tests/test_identity.py` | Identity capture, recognition, token, and rejoin tests |
| `tests/test_envelope.py` | Envelope property tests and foreign fallback |
| `tests/test_client.py` | Local SQLite client behavior |
| `tests/test_cli.py` | CLI JSON and human contract tests through `run_cli` |
| `tests/test_shared_contract.py` | Cross-backend contract tests; must cover SQLite and Postgres |
| `extensions/taut_pg/tests/` | PG-only extension behavior, plugin availability, sidecar compatibility |

Current important shapes:

- `taut/schema.py` currently defines `taut_members.handle` as primary key,
  `taut_membership.member`, `taut_threads.created_by`, and helpers that take
  `handle`.
- `taut/client.py` currently stores `Member.handle`, `Message.from_handle`, and
  writes envelopes with `encode_envelope(from_handle=...)`.
- `taut/cli.py` currently emits message JSON with `from`, member JSON with
  `handle`, and has no `set name` or `inbox` command.
- `taut/envelope.py` currently treats messages without `{"v":1,...}` as
  foreign. The target model has no old-envelope compatibility requirement.
- `taut/watcher.py` must keep chat queues peek/cursor based. Notification queues
  are a separate claim/read path.
- SimpleBroker 4.9.0 exposes queue rename through
  `simplebroker.open_broker(...).rename_queue(...)`. It does not expose
  `Queue.rename()` or a module-level `simplebroker.rename_queue()`, so do not
  plan around those names.

Comprehension checks before editing:

1. Which module is allowed to contain sidecar SQL? Answer must be
   `taut/schema.py`.
2. Which layer owns CLI behavior semantics? Answer must be `TautClient`; the CLI
   parses and renders only.
3. Which broker queues are peek history and which are claim inboxes? Answer:
   channels, sub-threads, and DMs are peek history; notifications are claimed.
4. Which value survives name changes? Answer: `member_id`, not `display_name`,
   `name_key`, or alias.

## 4. Invariants and Constraints

- No long-lived compatibility layer. Convert the implementation to the new
  model. Do not keep dual envelope readers or dual schema semantics unless the
  user explicitly asks for old database compatibility.
- No release notes are required for this migration.
- `member_id` is the stable identity. Do not use current name, alias, process
  pid, process start time, or current claim hash as durable identity.
- Identity claim hashes are deterministic evidence. They map to `member_id`;
  they are not themselves the member id after rejoin.
- Old messages keep their old `from` name snapshot. Name changes affect only
  future messages and current routing.
- Normal channels are human slugs and remain unprefixed. Do not introduce
  opaque channel ids.
- Channel names cannot contain dots. Dots are structural. Exact names `dm`,
  `notify`, `sys`, and `taut` are reserved.
- Direct-message and notification queues use special prefixes and sidecar
  annotations. Do not infer user-visible state from arbitrary unregistered
  broker queues.
- Chat queues are never consumed by Taut. Notification queues are intentionally
  consumed.
- There is one notification queue per member, not per device or session.
- The broker is never mocked in contract tests. Sidecar schema helpers are not
  mocked in client/CLI/shared tests.
- Use SimpleBroker public APIs only. No SQL against SimpleBroker-owned tables,
  no underscore imports, and no local cache of broker message metadata.
- No new runtime dependency. Use stdlib `hashlib`, `base64`, `json`, and
  existing `psutil`/`simplebroker`.
- `Queue.write()` remains forbidden in Taut message writes. Use
  `Queue.generate_timestamp()` plus `Queue.insert_messages([(body, ts)])`.
- Channel rename must use SimpleBroker's public
  `open_broker(...).rename_queue(...)` API. Do not implement it with private
  SQL or by editing SimpleBroker-owned message tables.
- Red-green TDD is required for behavior changes. Each task below names the
  failing tests to add first.

## 5. Rollback and Rollout Position

This is a development-stage breaking migration. The plan intentionally does not
preserve old field names or old schema behavior.

Rollback is a code revert plus database recreation from scratch. Do not promise
that a database opened by the new schema can be used by old code.

Implementation rule:

- Bump `SCHEMA_VERSION` and create the new schema for fresh databases.
- If an existing database has an older schema version, fail with a clear error
  that says the current development schema is unsupported and the database must
  be recreated. Do not silently update the `taut_meta` version over incompatible
  tables.
- If the user later wants old database migration, write a separate plan. Do not
  smuggle that work into this implementation.

## 6. Bite-Sized Tasks

### Task 1: Add schema tests for member ids, names, aliases, and claims

Outcome: failing tests describe the new sidecar contract before DDL changes.

Files to touch first:

- `tests/test_schema.py`
- `tests/test_shared_contract.py` only if a behavior must be proven across
  SQLite and Postgres

Read first:

- `docs/specs/02-taut-core.md` [TAUT-3.3]
- `docs/specs/03-identity-addressing-notifications.md` [IAN-3], [IAN-4],
  [IAN-6]
- Current `taut/schema.py`

Tests to add first:

- `test_schema_creates_member_identity_tables`
- `test_schema_refuses_older_incompatible_schema`
- `test_member_name_key_is_unique_case_insensitive`
- `test_alias_key_conflicts_with_member_name_key`
- `test_claim_hash_maps_to_one_member`
- `test_membership_uses_member_id_not_name`

Implementation files:

- `taut/_constants.py`
- `taut/schema.py`

Implementation guidance:

- Set `SCHEMA_VERSION = 2`.
- Add constants for member id, claim hash, name, channel, and reserved special
  queue validation. Keep regexes centralized in `_constants.py`.
- Replace `taut_members.handle` primary key with `member_id`.
- Add `display_name`, `name_key`, `taut_member_aliases`, and
  `taut_identity_claims`.
- Add `kind` and `meta` to `taut_threads`.
- Change `taut_membership.member` to `member_id`.
- Add `taut_channel_renames` DDL, but do not implement channel rename command
  yet.
- Update schema helpers to use member ids in function names and parameters.
  Keep wrappers thin; do not duplicate SQL in `client.py`.

Stop and re-evaluate if:

- You need SQL outside `taut/schema.py`.
- You start writing a schema-1 to schema-2 migration.
- You need a new package dependency.

Done signal:

- New schema tests fail before implementation and pass after implementation.
- `rg -n "handle" taut/schema.py` only finds comments naming old code in a
  temporary plan context or no matches.

### Task 2: Add deterministic identity claim hashing

Outcome: identity evidence can produce deterministic claim hashes, and member
ids are minted opaque values without using names.

Files to touch first:

- `tests/test_identity.py`
- `taut/identity.py`

Read first:

- `docs/specs/03-identity-addressing-notifications.md` [IAN-3.1],
  [IAN-3.2], [IAN-3.3]
- Current `taut/identity.py`

Tests to add first:

- same process evidence produces the same `agent_process` claim hash
- changing display name input does not change claim hash
- different process start token changes the claim hash
- human session claim includes host id and uid
- minted member ids match the `^m_[a-z0-9]{26,52}$` contract and do not include
  display-name material

Implementation guidance:

- Add small helpers in `identity.py`:
  - `claim_for_capture(capture) -> IdentityClaim`
  - `claim_hash(payload) -> str`
  - `random_member_id() -> str`
- Use canonical JSON: sorted keys, compact separators, UTF-8 bytes.
- Use stdlib hashing and base32/base64 encoding. Normalize to lowercase and
  strip padding.
- Do not put display name or alias into claim payloads.
- Do not derive durable `member_id` from the current claim hash.

Stop and re-evaluate if:

- Claim hashing needs current database state.
- A helper starts importing `TautClient`.

Done signal:

- Identity tests pass and no production code outside `identity.py` constructs
  claim hashes by hand.

### Task 3: Change envelopes and message objects to `from_id` plus `from`

Outcome: Taut-written messages carry stable sender id and sender-name snapshot.

Files to touch first:

- `tests/test_envelope.py`
- `tests/test_client.py`
- `tests/test_cli.py`
- `taut/envelope.py`
- `taut/client.py`
- `taut/cli.py`

Read first:

- `docs/specs/02-taut-core.md` [TAUT-6], [TAUT-8.2]
- `docs/specs/03-identity-addressing-notifications.md` [IAN-4.5]

Tests to add first:

- envelope round-trip includes `from_id`, `from`, `kind`, and `text`
- envelope without required `from_id` decodes as foreign
- foreign text still never raises
- JSON message output includes `from_id` and `from`
- Python `Message` exposes `from_id` and `from_name`

Implementation guidance:

- Replace `from_handle` terms in `DecodedEnvelope`, `Message`, and encode paths.
- Do not retain special old-envelope decode logic. This project is still in
  development and does not need compatibility.
- Keep foreign fallback simple: malformed body becomes `from_id=None`,
  `from_name="?"`, `kind="foreign"`, `text=raw`.
- Update CLI JSON and human rendering in one pass.

Stop and re-evaluate if:

- You are adding `v1`/`v2` branches.
- You are rewriting old broker messages.

Done signal:

- Envelope, client, and CLI tests pass for the new fields.
- `rg -n "from_handle|Envelope v1|\"v\":1|v1 envelope" taut tests docs/specs README.md`
  has no active-code or active-spec hits.

### Task 4: Convert member resolution and memberships to `member_id`

Outcome: all member-owned state routes through stable ids while names remain
mutable current values.

Files to touch first:

- `tests/test_client.py`
- `tests/test_shared_contract.py`
- `tests/test_cli.py`
- `taut/client.py`
- `taut/schema.py`
- `taut/identity.py`

Read first:

- `docs/specs/03-identity-addressing-notifications.md` [IAN-2], [IAN-3],
  [IAN-4]
- Current `_resolve_member`, `_create_member`, and `_member_from_row` in
  `taut/client.py`

Tests to add first:

- creating a member returns `member_id`, `name`, and one-time `token`
- joining and reading uses membership keyed by `member_id`
- `set name` changes current name without changing `member_id`
- messages before a name change keep old `from`; messages after use new `from`
- `--as oldname` no longer resolves after `set name newname`
- `--as newname` resolves to the same `member_id`
- `rejoin NAME_OR_ALIAS` adds the current claim to the existing `member_id`
- token resolution acts as the same `member_id`
- `join --new` does not steal an existing claim from another member

Implementation guidance:

- Add `TautClient.set_name(name: str) -> Member`.
- Update `Member` dataclass to `member_id`, `name`, `aliases`, `kind`,
  `presence`, `last_active_ts`, `persona`, `token`, `explain`.
- Keep creation and resolution in `_resolve_member`; do not add CLI-side member
  creation.
- Store and compare normalized `name_key`/alias keys in schema helpers.
- Use `member_id` in all membership, cursor, thread-created-by, and message
  write paths.
- Continue to update `last_active_ts` lazily only after a command is known to
  need member state.

Stop and re-evaluate if:

- A name or alias is used as a foreign key.
- You need to query members by display name from outside schema helpers.
- You are tempted to preserve old `handle` JSON fields.

Done signal:

- Targeted client and shared tests pass.
- `rg -n "from_handle|Member\\.handle|Message\\.from_handle|taut_members\\.handle|\\\"handle\\\"" taut tests`
  is empty after implementation.

### Task 5: Add address parsing and queue namespace helpers

Outcome: channel, hash-channel, sub-thread, direct-message, notification, and
reserved special queue names have one parser and one validator.

Files to touch first:

- `tests/test_constants.py`
- `tests/test_client.py`
- new `tests/test_addressing.py` if the parser grows beyond constants tests
- `taut/_constants.py`
- new `taut/addressing.py` only if it removes real duplication
- `taut/client.py`

Read first:

- `docs/specs/03-identity-addressing-notifications.md` [IAN-5], [IAN-6]
- Existing `_validate_thread_name` in `taut/client.py`

Tests to add first:

- `general` parses as channel
- `#general` parses as channel after stripping `#`
- `@claude` parses as direct-message target
- `general.<19-digit-id>` parses as sub-thread
- `general.foo` is rejected
- `general.extra.123` is rejected
- channels named `dm`, `notify`, `sys`, and `taut` are rejected
- unregistered broker queues are invisible to `list`

Implementation guidance:

- Keep channel names lowercase as today.
- Accept `#channel` for command args, but continue to document bare channel
  names as the shell-safe path.
- Put direct-message queue id generation in one helper:
  `dm_queue_name(member_id_a, member_id_b)`.
- Put notification queue name generation in one helper:
  `notification_queue_name(member_id)`.
- Do not add opaque ids for normal channels.

Stop and re-evaluate if:

- There is more than one parser for command target syntax.
- Channel names with dots become possible.

Done signal:

- Parser and validation tests pass.
- `TautClient` uses the shared parser rather than local string branching.

### Task 6: Implement direct-message queues

Outcome: `taut say @name ...` opens a stable member-pair chat queue.

Files to touch first:

- `tests/test_shared_contract.py`
- `tests/test_client.py`
- `tests/test_cli.py`
- `taut/client.py`
- `taut/schema.py`
- `taut/cli.py`
- `taut/addressing.py` if created in Task 5

Read first:

- `docs/specs/03-identity-addressing-notifications.md` [IAN-5.1],
  [IAN-6.4]
- Current `TautClient.say`

Tests to add first:

- Alice can `say @bob "hi"` after Bob exists.
- The DM queue name is the same when Bob later says `@alice`.
- The DM queue name remains the same after either member changes name.
- Both participants have membership rows for the DM queue.
- Sender cursor behavior matches channel `say`: caught-up sender does not see
  own message as unread.
- `list --all --json` exposes `kind="dm"` and `members`.
- Self-DM is rejected.
- Unknown `@alias` returns exit 2 in CLI.

Implementation guidance:

- Use `taut_threads.kind = "dm"` and store participant member ids in
  `taut_threads.meta`.
- Add both participants as members of the DM thread when the first message is
  sent.
- Use the same `_write_message` / `_insert_message` path as channels.
- For human rendering, label a two-person DM by the other participant's current
  name when practical. JSON should keep the internal `dm.<id>` in `thread`.
- Keep `reply` scoped to channel/sub-thread roots unless the specs are expanded
  to define threaded DMs.

Stop and re-evaluate if:

- DM queue names include display names or aliases.
- You add a second message-write path.
- You add DM-specific cursor logic instead of reusing membership cursors.

Done signal:

- Shared SQLite and Postgres contract tests prove DM behavior.

### Task 7: Implement mention detection and notification inbox reads

Outcome: mentions create consumable per-member notification pointers without
changing chat-history semantics.

Files to touch first:

- `tests/test_shared_contract.py`
- `tests/test_client.py`
- `tests/test_cli.py`
- `taut/client.py`
- `taut/schema.py`
- `taut/cli.py`
- new `taut/notifications.py` only if it centralizes payload encode/decode and
  mention parsing

Read first:

- `docs/specs/03-identity-addressing-notifications.md` [IAN-5.2], [IAN-7],
  [IAN-9], [IAN-10]
- Current `TautClient.say`, `TautClient.reply`, and `_insert_message`

Tests to add first:

- mentioning `@bob` in a channel writes one notification to Bob's
  `notify.<member_id>` queue
- two mentions of `@bob` in one message produce one notification
- sender does not notify themself
- mention resolution uses alias/name at write time
- changing actor name after sending does not alter pending notification
  `actor_name`
- `taut inbox --json` claims and emits notification objects
- a second `taut inbox --json` returns exit 2 after the first drained the
  inbox
- source chat message remains visible through `log` after notification drain
- malformed foreign notification bodies do not crash inbox reading

Implementation guidance:

- Add a `Notification` dataclass in `client.py` or a small notifications module.
  Do not put JSON payload construction in `cli.py`.
- Mention detection happens after the source message insert succeeds.
- Notification write failure is best-effort after source success. Warn to
  stderr for human output. For `--json`, do not corrupt ndjson; either emit a
  warning on stderr or expose a structured warning object only if the spec is
  updated first.
- Notification reads use broker claim/read APIs, not peek plus cursor.
- Do not add per-device state.

Stop and re-evaluate if:

- Notification state appears in `taut_membership`.
- You need a cursor for notifications.
- Notification failure rolls back a source chat message.

Done signal:

- Notification tests pass in SQLite and shared Postgres gates.

### Task 8: Integrate notifications into `watch`

Outcome: `taut watch` can surface notifications and consume them without
breaking chat cursor behavior.

Files to touch first:

- `tests/test_watcher.py`
- `tests/test_shared_contract.py` only for backend-level behavior that can be
  proven without timing flake
- `taut/watcher.py`
- `taut/client.py`

Read first:

- `docs/specs/02-taut-core.md` [TAUT-8.4]
- `docs/specs/03-identity-addressing-notifications.md` [IAN-7.4]
- Current `TautWatcher` cursor wrapper

Tests to add first:

- watch sees a chat message and advances chat cursor as before
- watch sees a mention notification and claims it
- after watch claims a notification, `inbox` returns nothing
- chat history remains available after watch claims a notification
- watch with no joined chat threads still stays alive for the member's
  notification inbox
- a failing chat handler leaves chat cursor in place
- a failing notification renderer may lose the notification but must not skip
  source chat history

Implementation guidance:

- Keep chat queue watching on the existing cursor-aware peek path.
- Add notification polling/claiming as a separate path in `TautWatcher`; do not
  shoehorn notification queues into `taut_membership.last_seen_ts`.
- If the existing watcher architecture makes this awkward, add a thin wrapper
  method on `TautClient` for draining notifications and have `TautWatcher` call
  it on the refresh interval. Keep it small.

Stop and re-evaluate if:

- The base watcher starts claiming chat messages.
- Notification handling requires modifying vendored watcher internals in a way
  that would make future Weft diffs hard to reason about.

Done signal:

- Watcher tests pass without sleeps longer than the existing bounded wait style.

### Task 9: CLI and Python API finalization

Outcome: public surfaces match [TAUT-8.2] and [IAN] docs.

Files to touch first:

- `tests/test_public_api.py`
- `tests/test_cli.py`
- `taut/__init__.py`
- `taut/cli.py`
- `taut/client.py`

Read first:

- `docs/specs/02-taut-core.md` [TAUT-8]
- README command reference

Tests to add first:

- `taut set name` human and JSON output
- `taut say @name` human and JSON output
- `taut inbox` human and JSON output
- member JSON objects include `member_id`, `name`, `aliases`, `kind`,
  `presence`, `last_active_ts`, and `persona`
- message JSON objects include `thread`, `ts`, `from_id`, `from`, `kind`,
  `text`
- list JSON objects include `thread`, `kind`, `parent`, `unread`, `last_ts`,
  and `members` for DMs
- public exports still include `TautClient`, `TautWatcher`, `Message`,
  `Thread`, `Member`, `TautError`, and `__version__`

Implementation guidance:

- `cli.py` should stay a renderer. If a branch needs to know business rules,
  move that logic into `TautClient`.
- Do not include old `handle` JSON fields.
- Keep exit code behavior aligned with SimpleBroker: 0 success, 1 error, 2
  empty/not found/not a member.

Stop and re-evaluate if:

- CLI grows business logic that tests cannot reach through `TautClient`.
- JSON output starts depending on human display labels.

Done signal:

- CLI and public API tests pass.

### Task 10: Channel rename support

Outcome: channel rename moves the channel queue, registered sub-thread queues,
sidecar thread names, membership rows, and rename recovery marker without
private broker access.

Files to touch:

- `taut/client.py`
- `taut/schema.py`
- `taut/cli.py`
- `tests/test_client.py`
- `tests/test_cli.py`
- `tests/test_shared_contract.py`
- `extensions/taut_pg/tests/` if PG shared coverage needs backend-specific
  fixtures
- `README.md`
- `docs/specs/03-identity-addressing-notifications.md`
- `docs/implementation/04-taut-architecture.md`

Read first:

- `docs/specs/03-identity-addressing-notifications.md` [IAN-8]
- SimpleBroker 4.9.0 `open_broker` and `BrokerConnection.rename_queue`
- The queue-name namespace rules in [IAN-6]

Preflight command:

```bash
uv run python - <<'PY'
import inspect
import simplebroker
print(getattr(simplebroker, "__version__", "unknown"))
with simplebroker.open_broker(".taut-rename-preflight.db") as broker:
    print("broker.rename_queue", hasattr(broker, "rename_queue"))
    print(inspect.signature(broker.rename_queue))
PY
rm -f .taut-rename-preflight.db .taut-rename-preflight.lock
```

Red tests first:

- Add a client/shared test that renames a channel with pending messages and
  verifies old channel reads fail, new channel reads show the same messages,
  membership moved, and `list_threads()` reports only the new channel name.
- Add a client/shared test that renames a channel with a registered sub-thread
  and verifies `<old>,<mid>` becomes `<new>,<mid>` in broker queues and sidecar
  rows.
- Add collision tests for existing target channel, target special queue,
  source special queue, invalid target name, and missing source. Assert no
  sidecar rows or broker queues moved after failure.
- Add an interrupted-rename recovery test around `taut_channel_renames`. Use a
  small injectable failpoint in `TautClient` or schema helpers if needed; do not
  monkeypatch SimpleBroker internals or inspect SimpleBroker private tables.
- Add CLI tests for success, human error text, and JSON error output.

Implementation guidance:

- Resolve Taut's broker target once, then open a broker connection with
  `simplebroker.open_broker(resolved_target, config=cfg)`.
- Use `broker.rename_queue(old, new, retarget_aliases=False)` for each Taut
  queue. Taut should own alias/member routing in sidecar tables, not
  SimpleBroker queue aliases.
- Record the rename marker before the first broker rename. Include old name,
  new name, affected queue names, phase, and completion state.
- Apply broker queue renames and sidecar updates in a deterministic order:
  channel queue first, then registered sub-thread queues sorted by name, then
  sidecar thread/membership rows. On startup or before another rename, resume or
  report an incomplete marker rather than starting a second overlapping rename.
- Keep historical message bodies unchanged. Only current lookup and future
  routing move.
- The broker is a real dependency in tests. Do not mock `open_broker()` unless
  the specific test is the failpoint/recovery test and the mock is at the Taut
  boundary, not the SimpleBroker internals.

Done signal:

- `taut rename old new` exists only after client and shared contract tests pass.
- No production code imports `simplebroker._*` or updates SimpleBroker-owned
  tables.
- Rename works on SQLite and the shared test suite passes against Postgres.

### Task 11: Documentation alignment

Outcome: docs match the implemented behavior and do not describe old shapes as
compatibility promises.

Files to touch:

- `README.md`
- `docs/specs/02-taut-core.md`
- `docs/specs/03-identity-addressing-notifications.md`
- `docs/specs/00-specs-index.md`
- `docs/implementation/04-taut-architecture.md`
- this plan

Read first:

- `docs/agent-context/runbooks/maintaining-traceability.md`

Required updates:

- Replace any remaining active `handle` identity wording with member id/name
  wording.
- Keep `v1`/`v2` labels out of specs and README.
- Keep this plan updated if implementation discovers a narrower or blocked
  scope.
- If channel rename remains blocked by SimpleBroker API absence, keep that
  explicitly documented.

Done signal:

- Grep gates below pass.

## 7. Testing Plan

Do not mock:

- SimpleBroker queues
- `Queue.sidecar()`
- `TautClient`
- CLI entrypoint behavior
- identity resolution in contract tests
- notification queue consumption

Limited mocks or synthetic values are acceptable for:

- pure identity canonicalization tests
- platform-specific process capture edge cases
- generated timestamp values only when testing a pure helper, not client
  behavior

Test layers:

| Layer | Files | Required proof |
|---|---|---|
| Pure helper | `tests/test_identity.py`, `tests/test_envelope.py`, `tests/test_constants.py`, optional `tests/test_addressing.py` | claim hashes, id formats, envelope decode, parser validation |
| Schema | `tests/test_schema.py` | DDL, uniqueness, version refusal, helper behavior through real sidecar |
| Client | `tests/test_client.py` | member id stability, name changes, DM creation, notification writes, inbox drain |
| CLI | `tests/test_cli.py` | command parsing, JSON shapes, human output basics, exit codes |
| Shared backend | `tests/test_shared_contract.py` | SQLite/Postgres contract for member ids, DMs, notifications, list metadata |
| Watcher | `tests/test_watcher.py` | chat cursor behavior remains peek-based; notifications claim once |
| Extension | `extensions/taut_pg/tests/` | PG plugin and sidecar compatibility still hold |

Red-green sequence:

1. Add the narrow failing test for the task.
2. Run only that test or file to confirm it fails for the expected reason.
3. Implement the smallest code change.
4. Run the targeted test again.
5. Run the neighboring test file.
6. Move to the next task only after the slice is green.

## 8. Verification and Gates

Targeted gates during implementation:

```bash
uv run pytest tests/test_schema.py
uv run pytest tests/test_identity.py
uv run pytest tests/test_envelope.py
uv run pytest tests/test_client.py
uv run pytest tests/test_cli.py
uv run pytest tests/test_watcher.py
uv run pytest tests/test_public_api.py
uv run pytest -m shared tests/test_shared_contract.py
uv run ./bin/pytest-pg --fast tests/test_shared_contract.py
```

Final gates:

```bash
uv run pytest
uv run pytest -m shared
uv run ./bin/pytest-pg --fast
uv run ruff check taut tests bin extensions/taut_pg/taut_pg extensions/taut_pg/tests
uv run ruff format --check taut tests bin extensions/taut_pg/taut_pg extensions/taut_pg/tests
uv run --extra dev mypy taut tests bin/release.py extensions/taut_pg/taut_pg extensions/taut_pg/tests --config-file pyproject.toml
uv build
uv build extensions/taut_pg
```

Grep gates:

```bash
rg -n "Queue\\.write\\(" taut tests
rg -n "simplebroker\\._|from simplebroker\\._" taut tests
rg -n "SELECT|INSERT|UPDATE|DELETE" taut | rg -v "taut/schema.py"
rg -n "from_handle|Member\\.handle|Message\\.from_handle|taut_members\\.handle|\\\"handle\\\"|Envelope v1|v1 envelope|\\\"v\\\":1" taut tests README.md docs/specs
rg -n "Queue\\.rename|simplebroker\\.rename_queue" taut tests
```

Expected grep results:

- `Queue.write(`: no matches.
- private SimpleBroker imports: no matches.
- SQL outside `taut/schema.py`: no matches.
- old handle/envelope API and schema terms: no matches in active code/spec docs.
  Historical plan mentions are acceptable only when clearly labeled as
  historical.
- unsupported rename APIs: no matches. Runtime code may call
  `broker.rename_queue(...)` on a connection returned by
  `simplebroker.open_broker(...)`.

Post-implementation observation:

- In a temp project, create two members, change one name, send old and new
  messages, send a DM, mention the other member, drain inbox, and verify:
  old message shows old `from`, new message shows new `from`, `from_id` is
  stable, DM queue is stable, notification is gone after inbox, source history
  remains.

## 9. Independent Review Loop

Before implementation starts, ask a reviewer from a different agent family when
available:

> Read `docs/plans/2026-06-18-member-identity-addressing-plan.md`,
> `docs/specs/02-taut-core.md`, `docs/specs/03-identity-addressing-notifications.md`,
> `docs/implementation/04-taut-architecture.md`, and the key files listed in
> the plan. Do not implement. Look for errors, bad ideas, missing files,
> ambiguous instructions, weak tests, and anything that would make a
> zero-context engineer implement this incorrectly. Could you implement it
> confidently and correctly from the plan?

The author must answer each review point by updating this plan, recording why
the current path remains correct, or marking the point out of scope. If the
reviewer says the plan is not implementable, treat that as a blocker.

## 10. Out of Scope

- Release notes.
- Old database compatibility or automatic schema-1 to schema-2 migration.
- Auth, signing, encryption, permissions, or trust-boundary hardening.
- Per-device notifications.
- Opaque ids for normal channels.
- Redis/Valkey state mapping.
- Summon/captive-agent implementation.
- TUI polish.
- Message delete/edit/history rewrite.
- Free-form display names with spaces or non-ASCII aliases.

## 11. Fresh-Eyes Review

Author self-review checklist applied to this plan:

- File paths are explicit for every task.
- The plan states that `schema.py` is the only sidecar SQL boundary.
- The plan states that `TautClient` owns semantics and `cli.py` renders.
- The plan names the real tests to write first.
- The plan forbids broker/schema over-mocking at the important seams.
- The plan names the breaking-schema choice and refuses old schema instead of
  quietly preserving compatibility.
- The plan requires SimpleBroker's public queue rename API for channel rename.
- The plan keeps normal channels human-named and unprefixed.
- The plan separates chat-history peek behavior from notification claim
  behavior.

Issues found and fixed during review:

- Ambiguity: DM list output would otherwise expose only `dm.<id>`.
  Fix: specs now require list metadata to include `kind` and DM participant
  member ids, and human renderers should label two-person DMs by the other
  participant's current name.
- Ambiguity: old schema migration could pull the implementation into a
  compatibility project. Fix: rollback/rollout section explicitly refuses old
  schema and requires a separate plan for migration.
- Error: deriving `member_id` from the first claim hash would make forced new
  identities and process-claim churn awkward. Fix: [IAN-3.1] now makes the
  claim hash the deterministic evidence value and keeps `member_id` as a minted
  opaque id.
- Ambiguity: channel rename could tempt private broker-table edits. Fix: Task
  10 requires `simplebroker.open_broker(...).rename_queue(...)` and forbids
  private SimpleBroker table edits.

Re-review result: this plan remains aligned with the discussed direction. It is
large, but the slices are separable and each has a red-green proof. The largest
risk is Task 8 (`watch` plus notification claiming), because it crosses the
vendored watcher boundary. The stop gates there are intentional: if that slice
starts mutating chat watch semantics, pause and re-plan the watcher integration.
