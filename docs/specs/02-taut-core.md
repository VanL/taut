# Taut Core Specification

Status: Proposed

Taut is private, no-config chat for the processes that already share your
machine: you, your agents, and anything else that can run a CLI. It is built
on SimpleBroker and stores everything — messages, threads, members, read
state — in one SQLite file, `.taut.db`, by default. With the `taut-pg`
extension installed, the same state lives in a project-configured Postgres
schema.

This spec defines intended behavior for the core storage model, thread model,
message contract, read model, and CLI, Python API, and watcher surfaces.
Stable member identity, mutable names, reserved alias storage, direct messages,
notifications, and special queue namespaces are governed by
`docs/specs/03-identity-addressing-notifications.md`.

## 1. Purpose and Scope [TAUT-1]

In scope:

- the default `.taut.db` storage model and project resolution rules
- thread and channel semantics over SimpleBroker queues
- the core sidecar state model
- the message envelope contract
- the read model: cursors, unread state, chat-history peek discipline, and
  notification-inbox claim discipline
- the CLI surface, the `TautClient` Python API, and the `TautWatcher`
- the trust model and its limits

Delegated to `03-identity-addressing-notifications.md`:

- stable member ids, identity claim hashes, process evidence, recognition, and
  rejoin
- mutable names, reserved alias storage, and `taut set name`
- `@name` direct messages and mention routing
- notification queue payloads and consumption semantics
- special queue namespaces and channel rename

Out of scope for core but committed on the roadmap, with compatibility
obligations defined in [TAUT-12]:

- non-SQL state mappings beyond the SQL sidecar path (`taut-pg` remains SQL)
- captive agents (`summon`): hosting an agent process as a thread member
- the TUI (named as a surface in [TAUT-8.4]; it gets its own spec before
  implementation)

Out of scope as non-goals (not deferred ambiguity):

- authentication or message integrity guarantees (see [TAUT-9])
- message deletion, editing, retention, or archival verbs
- taut-owned networking; remote reach only ever comes from the broker
  backend, never from taut growing a protocol
- code-signing identity as identity-claim evidence (recorded as a possible
  future macOS evidence field; not captured by the current spec)

## 2. Mental Model [TAUT-2]

- One file by default. `.taut.db` is a standard SimpleBroker database plus
  taut-owned sidecar tables. There is no other durable state in the SQLite
  path: no config file, no state directory, no lock files. (SQLite WAL
  companions `.taut.db-wal` and `.taut.db-shm` are transient and managed by
  SQLite.) Under `taut-pg`, `.taut.toml` selects a Postgres target and the same
  sidecar tables live in that configured schema.
- A thread is a queue. A **channel** is a top-level thread (`general`). A
  **sub-thread** hangs off one message in a channel and is itself a queue
  (`general.1837025672140161024`, named by the origin message id).
- Chat messages are never consumed. Channel, sub-thread, and direct-message
  readers peek; the queue is the conversation history. "Read" on a chat
  surface means "move my bookmark", never "remove". Notification queues are the
  exception: they are per-member inbox pointers and are claimed when read
  ([IAN-7.4]).
- Who you are is a stable opaque member id plus current evidence. Process
  fingerprints, human session evidence, and continuity tokens produce identity
  claim hashes that map to a `member_id`; names are mutable current-value data
  ([IAN-2], [IAN-3]).
- Per-member state is relational. Members, identity claims, names, thread
  registry, membership, and read cursors live in `taut_*` sidecar tables in the
  same file, written through SimpleBroker's sidecar API.
- Identification, not authentication. Anyone with storage access can be
  anyone. Taut makes coordination inside one trust domain frictionless;
  it is not a security boundary ([TAUT-9]).

## 3. Storage and Project Resolution [TAUT-3]

### [TAUT-3.1] Single-file state

All durable taut state lives in the resolved SimpleBroker target: by default
`.taut.db`, containing SimpleBroker's own tables (messages, meta, aliases) and
the `taut_*` sidecar tables. Under `taut-pg`, `.taut.toml` is configuration,
not message state; the durable chat state lives in the configured Postgres
schema. Taut must not create extra caches or state directories. Violation of
this rule is a spec bug, not an implementation choice.

### [TAUT-3.2] Resolution and configuration translation

Taut resolves its database the way git resolves a repository:

1. `--db PATH` (CLI) or `db_path=` (API), if given, is used as-is — but
   the file must already exist (see the creation rule below).
2. `TAUT_DB`, if set, behaves exactly like `--db`.
3. Otherwise taut searches upward from the current directory for `.taut.toml`
   or `.taut.db` through SimpleBroker project resolution, and uses the first
   resolved target.
4. If nothing is found, commands fail with exit code 1 and the message
   `No taut database found. Run 'taut init' to create one.` Only
   `taut init` creates a database.

Implementation contract: taut owns no search logic of its own. The upward
search is one call: `simplebroker.resolve_broker_target(cwd, config=cfg)`,
which returns the discovered target or `None` (→ the `taut init` error).
Plain `Queue(name, config=cfg)` does **not** search upward — it resolves
the current directory and would auto-create a database there, so the
client always resolves a target first and only then constructs queues
against it. The creation rule is enforced by taut, because SimpleBroker
auto-creates missing SQLite files on open: for explicit `--db`/`TAUT_DB`/
`db_path=` targets, taut requires the file to exist before opening it
(exit 1 with the `taut init` hint otherwise). These selectors are path-only;
Taut never interprets them as DSNs. `taut init` itself resolves the current
directory explicitly (`target_for_directory`), creates the SQLite database or
initializes the configured non-SQLite target by opening it, and installs the
sidecar schema ([TAUT-3.3]).

v0.2.0 supports SQLite in the core package and Postgres through the separate
`taut-pg` extension. Postgres selection uses `.taut.toml` with SimpleBroker's
project-config shape:

```toml
version = 1
backend = "postgres"
target = "postgresql://postgres:postgres@127.0.0.1:54329/taut_test"

[backend_options]
schema = "taut_project"
```

The configuration handed to SimpleBroker goes through `resolve_config()`
with these keys:

| Taut intent | SimpleBroker config key | Value |
|---|---|---|
| database filename | `BROKER_DEFAULT_DB_NAME` | `.taut.db` |
| upward search | `BROKER_PROJECT_SCOPE` | `true` |
| config-file isolation | `BROKER_PROJECT_CONFIG_NAME` | `.taut.toml` |
| ambient backend pin | `BROKER_BACKEND` | `sqlite` |

`BROKER_PROJECT_CONFIG_NAME=.taut.toml` exists so a stray `.broker.toml`
belonging to a standalone SimpleBroker or Weft project can never redirect
taut. It is also the Postgres backend-selection door ([TAUT-12.1]) using the
same project-config format SimpleBroker and Weft already use, which is why
backend support costs taut no new resolution machinery. `BROKER_BACKEND` is
pinned to SQLite in Taut's resolved config so ambient `BROKER_*` variables do
not silently become Taut's public backend API. `.taut.toml` still wins through
SimpleBroker project resolution. `TAUT_DB`, `TAUT_AS`, and `TAUT_TOKEN` are the
only public environment knobs in the core CLI.

Unknown keys in `.taut.toml` are ignored, not rejected — the same
forward-compatibility posture SimpleBroker's project-config loader applies
and that notification consumers apply to unknown payload fields
([IAN-7.2]). A malformed file (invalid TOML) is a loud error naming the
file; an unrecognized key is not. Tools must not depend on unknown keys
being diagnosed.

### [TAUT-3.3] Sidecar schema

Taut-owned tables are created through `Queue.sidecar(transaction=True)`
with idempotent DDL at `taut init` time and verified (created if missing)
on first write access. All tables are prefixed `taut_`.

```sql
CREATE TABLE IF NOT EXISTS taut_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);  -- holds schema_version

CREATE TABLE IF NOT EXISTS taut_members (
    member_id         TEXT PRIMARY KEY,
    display_name      TEXT NOT NULL,
    name_key          TEXT NOT NULL UNIQUE,
    kind              TEXT NOT NULL CHECK (kind IN ('human', 'agent')),
    uid               BIGINT NOT NULL,
    host_id           TEXT NOT NULL,
    host_label        TEXT,
    anchor_pid        BIGINT,
    anchor_start_time TEXT,
    fingerprint       TEXT,
    token             TEXT UNIQUE,
    meta              TEXT,
    created_ts        BIGINT NOT NULL,
    last_active_ts    BIGINT NOT NULL
);  -- member_id is the stable opaque identity from [IAN-3.1].
    -- display_name is mutable and captured into new message envelopes.
    -- name_key is the normalized route key from [IAN-4.2].
    -- uid/host/anchor/fingerprint columns are current recognition evidence
    -- and presence diagnostics; taut_identity_claims is the durable claim map.
    -- token is continuity, not authentication ([IAN-3.3]).
    -- meta is a JSON object. Defined key so far: "persona".
    -- Unknown keys are preserved.

CREATE TABLE IF NOT EXISTS taut_member_aliases (
    alias_key   TEXT PRIMARY KEY,
    member_id   TEXT NOT NULL REFERENCES taut_members(member_id),
    created_ts  BIGINT NOT NULL
);  -- aliases share the same normalized uniqueness namespace as name_key.

CREATE TABLE IF NOT EXISTS taut_identity_claims (
    claim_hash     TEXT PRIMARY KEY,
    member_id      TEXT NOT NULL REFERENCES taut_members(member_id),
    claim_kind     TEXT NOT NULL,
    host_id        TEXT,
    host_label     TEXT,
    evidence_json  TEXT NOT NULL,
    first_seen_ts  BIGINT NOT NULL,
    last_seen_ts   BIGINT NOT NULL
);  -- claim_hash is deterministic evidence from [IAN-3.2].
    -- A member may have many claims; a claim belongs to only one member.

CREATE TABLE IF NOT EXISTS taut_threads (
    name       TEXT PRIMARY KEY,
    kind       TEXT NOT NULL CHECK (
        kind IN ('channel', 'subthread', 'dm', 'notification', 'system')
    ),
    parent     TEXT,
    origin_ts  BIGINT,
    created_by TEXT NOT NULL,
    meta       TEXT,
    created_ts BIGINT NOT NULL
);  -- parent/origin_ts are set for sub-threads.
    -- dm/notification/system metadata is stored in meta as JSON and must
    -- duplicate only routing data that is needed to render or recover.

CREATE TABLE IF NOT EXISTS taut_membership (
    thread       TEXT NOT NULL,
    member_id    TEXT NOT NULL REFERENCES taut_members(member_id),
    joined_ts    BIGINT NOT NULL,
    last_seen_ts BIGINT NOT NULL DEFAULT 0,
    PRIMARY KEY (thread, member_id)
);

CREATE TABLE IF NOT EXISTS taut_channel_renames (
    old_name      TEXT PRIMARY KEY,
    new_name      TEXT NOT NULL,
    state         TEXT NOT NULL,
    affected_json TEXT NOT NULL,
    started_ts    BIGINT NOT NULL,
    updated_ts    BIGINT NOT NULL
);
```

The schema backs the identity invariants from [IAN-3] and [IAN-4]:
one member id is the durable identity, each normalized current name or alias
routes to at most one member, and each identity claim hash maps to at most one
member. Member-creation paths must treat uniqueness violations as lost races,
not ordinary user-facing errors: re-resolve and use the member the other
process created when the conflict represents the same claim. Claim recording
has the same race boundary: if the deterministic `claim_hash` appears between
the pre-insert read and the insert, reread it; refresh `last_seen_ts` and
return it when it belongs to the same member, but keep treating another member
as an ownership collision.

Schema evolution is additive within the current schema generation when possible
(new tables, new nullable columns). Breaking changes bump `schema_version` and
require an explicit migration plan. Older taut versions encountering a newer
`schema_version` must refuse with a clear error rather than guess.

### [TAUT-3.4] SimpleBroker interop

`.taut.db` is a standard SimpleBroker database. `broker -f .taut.db list`,
`peek`, `dump`, and friends work on it, and that interop is a feature, not
an accident. Two consequences are binding:

- Taut uses only SimpleBroker's public API (`simplebroker` and
  `simplebroker.ext` exports). No underscore-module imports, and no SQL
  against SimpleBroker's own tables — taut's SQL touches `taut_*` tables
  only.
- Core `TautClient` queue access goes through Taut's public-API
  `RetryingQueue` wrapper. The wrapper does not change storage shape or reach
  into SimpleBroker internals; it applies a bounded retry policy around known
  transient SQLite/WAL open, page-read, and timestamp-parse shapes on queue
  operations and sidecar SQL statements. Non-transient errors still surface.
- Taut must tolerate foreign writes: bodies that are not taut envelopes
  render as raw text ([TAUT-6.3]), and queues with no `taut_threads` row
  are invisible to `taut list` but must not break any command.

### [TAUT-3.5] One timestamp domain

Every taut timestamp (message ids, `created_ts`, `joined_ts`,
`last_seen_ts`, `last_active_ts`) is a SimpleBroker 64-bit hybrid
timestamp generated via `Queue.generate_timestamp()`. Taut never stores
wall-clock times. This keeps every ordering question in one
monotonic-per-database domain and makes any message id directly
comparable to any cursor.

Write path: `Queue.write()` returns `None`, but taut always needs the id
of the message it just wrote (cursor advance [TAUT-7.4], sub-thread
naming [TAUT-4.1], `-t` output). Every taut message write therefore
preallocates its id and inserts it exactly — SimpleBroker's sanctioned
pattern for live protocols that need the id up front:

```python
ts = queue.generate_timestamp()
queue.insert_messages([(envelope_json, ts)])
```

This is the single write path (invariant: there is no `Queue.write()`
call anywhere in taut).

## 4. Threads and Channels [TAUT-4]

### [TAUT-4.1] Naming

- Channel names match `^[a-z0-9][a-z0-9_-]{0,63}$`. No dots: dot is
  structural namespace syntax. Uppercase is rejected, not folded.
- The exact channel names `dm`, `notify`, `sys`, and `taut` are reserved.
  Dotted queue names whose first segment is one of those reserved words are
  special queues, not channels ([IAN-6.2]).
- A sub-thread's queue name is `<channel>.<origin_ts>` where `origin_ts` is
  the message id it branched from. Sub-threads of sub-threads are not
  supported (one level, like Slack).
- Direct-message, notification, and system queues are special queues governed
  by [IAN-6].
- These names are valid SimpleBroker queue names by construction; taut
  performs its own validation before SimpleBroker sees the name.

### [TAUT-4.2] Creation and registry

- `join` on a nonexistent channel creates it: a `taut_threads` row plus a
  membership row, and a `notice` envelope ([TAUT-6.2]) is written to the
  new queue so creation is visible in history.
- `reply` to a message creates the sub-thread on first use: registry row
  (`parent`, `origin_ts` set), creator membership, then the reply itself.
- The `taut_threads` registry is the authority for what threads exist and
  how they relate. Queue rows are storage; an empty queue with a registry
  row is still a thread.

### [TAUT-4.3] Membership

- Members see and are notified about a thread iff they have a
  `taut_membership` row. `leave` deletes the membership row and writes a
  `notice`; it never touches messages or the registry. For a *running*
  watcher the iff is convergence-bounded: membership changes apply
  within the [TAUT-8.4] refresh interval, so a just-left thread may
  display briefly before the watcher drops it. One-shot commands
  (`read`, `list`) check membership at invocation and are exact.
- Joining a channel does not auto-join its sub-threads. Replying to a
  sub-thread, or explicitly reading one (`read channel.<ts>`), joins it
  implicitly — provided the caller is a member of the parent channel
  (Slack's "you're in the thread now"). Channels are never joined implicitly;
  `read` on a channel you have not joined is a miss ([TAUT-8.1]).

## 5. Identity and Recognition [TAUT-5]

Identity, names, reserved alias storage, direct-message addressing,
notifications, and special queue namespaces are governed by
`docs/specs/03-identity-addressing-notifications.md`.

Core obligations:

- Taut surfaces resolve an acting member to a stable `member_id` before any
  state-changing command writes sidecar state or chat history.
- Process evidence, human session evidence, and continuity tokens are identity
  claims that map to a `member_id`; they are not display names.
- Names are mutable current values. The CLI may accept a name, and may resolve
  an existing alias where the schema contains one, but core state, cursors,
  memberships, direct messages, and notifications use `member_id`.
- `taut rejoin NAME_OR_ALIAS` associates the current identity claim with the
  selected member. It does not rename the member or rewrite history.
- `taut set name NAME` updates the acting member's current display name and
  route key. It does not alter old message envelopes.
- `--as NAME_OR_ALIAS` and `TAUT_AS` select by current name, or by an alias if
  one exists. If used to create a member, the new member still receives a stable
  opaque `member_id`.
- `TAUT_TOKEN` remains continuity, not authentication. It is another way to
  resolve a member inside the weak trust model from [TAUT-9].

## 6. Message Envelope [TAUT-6]

### [TAUT-6.1] Envelope

Every message taut writes is one JSON object, UTF-8, no newlines required:

```json
{"from_id": "m_abcd1234abcd1234abcd1234ab", "from": "claude", "kind": "message", "text": "parser is green"}
```

- `from_id` (string, required): sender `member_id` at write time.
- `from` (string, required): sender display-name snapshot at write time.
- `kind` (string, required): `"message"` or `"notice"`.
- `text` (string, required): the content.

The broker timestamp is the message id and time; the envelope never
duplicates it. Readers must ignore unknown fields. Writers must not emit fields
outside this spec unless the governing spec is updated first.

### [TAUT-6.2] Notices

System events are ordinary messages with `kind: "notice"` and
human-readable `text` (`"van created #general"`, `"claude joined"`,
`"claude left"`). Notices come from the member that caused them — there is
no system member. Renderers display them dimmed/inline; `--json` consumers
filter on `kind`.

### [TAUT-6.3] Foreign bodies

A body that does not parse as a Taut envelope (raw `broker write`, other
tools) renders with sender `?` and the raw body as text. In `--json` output it
is an ordinary [TAUT-8.2] message object with `"from_id": null`, `"from": "?"`,
and `"kind": "foreign"`. `foreign` is an output-only kind: taut never writes it
to a queue. Foreign bodies must never crash or stall any taut surface.

### [TAUT-6.4] Limits

Body size and content limits are SimpleBroker's (10 MB default). Taut adds
no limit of its own; `text` is arbitrary UTF-8 including newlines and
terminal control characters — escaping at render time is the renderer's
job, and `--json` output is the safe path for machine consumers.

## 7. Read Model [TAUT-7]

### [TAUT-7.1] Chat-history peek invariant

No chat-history surface consumes, claims, moves, or deletes broker messages.
Channel, sub-thread, and direct-message retrieval uses peek-family APIs.
History is append-only. A nonzero claimed count in a chat queue means a foreign
tool consumed messages; Taut tolerates that state, but those messages are gone
from history.

Notification queues are the explicit exception. They are inbox pointers and use
claim/read broker APIs as defined in [IAN-7.4].

### [TAUT-7.2] Cursors

`taut_membership.last_seen_ts` is the per-member, per-thread read cursor —
strictly a high-water mark of *seen* message timestamps:

- `read` and `watch` advance it as they display messages.
- `log`, `list`, and `who` never move it (`log` is history inspection, not
  catching up).
- Cursor writes are monotonic: `last_seen_ts` only increases.

### [TAUT-7.3] Unread

A thread is unread for a member iff
`Queue.has_pending(after_timestamp=last_seen_ts)` is true. Unread state
asks the broker, not a cached counter — there is nothing to invalidate.
Renderers may additionally *count* unread messages with bounded peeks for
human display; the count is presentation, not contract (the `--json`
`unread` field stays boolean, [TAUT-8.2]).

### [TAUT-7.4] Senders and their own messages

`say` and `reply` advance the sender's cursor to the written timestamp
iff the sender was caught up at write time (checked immediately before
writing). A sender with existing unread keeps their cursor (they still
have catching up to do).

Joining starts you at **now**: the membership row's `last_seen_ts` is
initialized to the join (or creation) notice's own timestamp, so a new
member begins caught up, and history is a deliberate rewind away via
`log` — joining a busy channel must not scream a thousand unread. One
carve-out: implicit sub-thread join *by reading it* ([TAUT-4.3])
initializes the cursor to 0, because reading the thread is exactly what
was asked; implicit join by replying starts at now like any join.
`leave` notices have no cursor effect.

The advance is applied **after the message insert succeeds**, never
before — cursor movement is not part of the pre-write sidecar state in
the [TAUT-10] ordering, because advancing first and crashing before the
insert would silently skip any message that landed between the
caught-up check and the crash. The check-then-write race (a message
landing in that window gets marked seen) is accepted as cosmetic: the
window is milliseconds and the cost is one message not flagged unread.

### [TAUT-7.5] `--since`

`--since TS` filters with SimpleBroker `after` semantics: strict
`ts > TS`, accepting every timestamp format SimpleBroker's parser accepts
(ISO 8601, unix s/ms/ns, native 19-digit ids). Taut does not reimplement
timestamp parsing ([TAUT-3.5]).

## 8. Surfaces [TAUT-8]

### [TAUT-8.1] CLI verbs

One executable, `taut`. Global options: `--db PATH`, `--as NAME_OR_ALIAS`,
`--token TOKEN` (acts as the member selected by continuity token; the flag wins
over the `TAUT_TOKEN` env var), `--json`, `-t/--timestamps` (show message ids in
human output; `say` prints the new message's id), `-q/--quiet`, `--version`,
`--help`. A literal `--` ends option parsing: every later token is positional,
so message text that looks like an option is sendable
(`taut say general -- -q` posts the text `-q`). Global options may appear
before or after the subcommand, but never after `--`.

| Verb | Behavior | Exit codes |
|---|---|---|
| `init` | Create the resolved SQLite `.taut.db` or initialize the configured backend target plus sidecar schema in the current directory. Idempotent with notice if present. | 0 created/exists, 1 error |
| `join THREAD [--as NAME_OR_ALIAS] [--persona TEXT] [--new]` | Register identity if needed (`--new` forces a fresh member), create a channel if needed, add membership (cursor at now, [TAUT-7.4]), write notice. `--persona` sets/updates the member's persona. | 0; 1 error |
| `leave THREAD` | Remove membership, write notice. | 0; 1 error; 2 not a member |
| `set name NAME` | Change the acting member's current display name and route key. Does not rewrite old messages. | 0; 1 error/name collision; 2 unrecognized |
| `say TARGET [TEXT\|-]` | Post a message (stdin with `-` or when piped and TEXT omitted). `TARGET` may be a channel, sub-thread, or `@name` direct message target ([IAN-5]). Channel and sub-thread targets require membership. Prints message id with `-t`. | 0; 1 error; 2 not a member / no such member |
| `reply THREAD MSG_ID [TEXT\|-]` | Post into the sub-thread of MSG_ID, creating it on first reply. Requires membership in THREAD. A full 19-digit id resolves exactly (peek by id — works for any message ever written). A suffix ≥ 4 digits resolves via a bounded public-API scan of the most recent 1,000 message ids of THREAD; ambiguous → error listing candidates. | 0; 1 error (incl. ambiguous suffix); 2 no such message / not a member |
| `read [THREAD]` | Show unread (all joined threads when bare, grouped), advance cursor through displayed messages. Reads are paged: one invocation displays and marks seen up to 1,000 unread messages per thread; callers drain larger backlogs by rerunning until exit 2. Requires a resolved member; explicit THREAD requires membership (sub-threads implicit-join per [TAUT-4.3]). | 0 showed messages; 1 error; 2 nothing unread / not a member (hint on stderr) |
| `inbox` | Claim and show pending notifications for the acting member. Notifications are consumed; source chat history is not changed. | 0 showed notifications; 1 error; 2 nothing pending |
| `log THREAD [--since TS] [--limit N]` | Show history. No cursor movement. `--limit N` selects the most recent N messages after `--since`, rendered in chronological order. | 0; 1; 2 empty |
| `list [--all]` | Bare: joined threads with unread state. `--all`: every registered thread. | 0; 2 when bare list has no unread |
| `watch [THREAD ...]` | Live-follow (default: all joined chat threads plus the acting member's notification inbox), advancing chat cursors per message and claiming notifications as they display. Adds/drops threads as membership changes while running; a running watch that loses its last chat membership keeps running idle and picks up the next join or notification. | 0 on clean stop; 1 error; 2 unrecognized member / explicit thread miss |
| `rename OLD NEW` | Rename a channel and every registered one-level sub-thread under it. Uses SimpleBroker's public queue rename API and sidecar rename markers. Does not rewrite message bodies. | 0; 1 error/collision/invalid name; 2 no such channel |
| `who [THREAD]` | Members and presence (thread members, or all members when bare). | 0; 1 error; 2 no such thread |
| `whoami [--explain]` | Resolved identity; with `--explain`, the evidence and rule. | 0 resolved; 1 error (incl. invalid token); 2 unrecognized |
| `rejoin [NAME_OR_ALIAS] [--token TOKEN]` | Associate the current identity claim with the selected member ([IAN-3.4]). Target: name or alias if given, else `--token` (subcommand or global), else global `--as`; name/alias combined with any `--token` is an error. | 0; 1 error/collision/ambiguous selectors; 2 no such member/token |
| `summon PROVIDER_OR_NAME [THREAD ...]` | Delegates to the `taut-summon` extension when installed (spec 04); without it, exit 1 with a one-line install hint. | per spec 04 |
| `dismiss NAME` | Delegates likewise (summon `stop`). | per spec 04 |

Delegation verbs carry no core logic and add no core dependency; their
behavior contract lives entirely in the owning extension's spec.

Exit-code rule, matching SimpleBroker: 0 success, 1 error, 2 "empty /
nothing matched / not found" — so `taut read -q && process_inbox` and
polling loops compose in shell. Usage errors — unknown flags, unknown
subcommands, missing or malformed arguments rejected by the parser — are
errors and exit 1, never 2. Exit 2 is reserved for the empty/not-found
class so that polling idioms like `taut read -q && handle_new` cannot
mistake a typo for "nothing new". `--help` and `--version` exit 0.

### [TAUT-8.2] Output contract

- Human output goes to stdout, hints and warnings to stderr. No prompts
  when stdin is not a tty; in non-tty contexts taut decides per the rules
  in this spec and reports what it did (agents must never hang on a
  question).
- `--json` emits one JSON object per line (ndjson), and **every verb has
  a defined JSON shape** — an agent must never have to guess:
  - message objects (`read`, `log`, `watch`): `thread`, `ts`, `from_id`,
    `from`, `kind`, `text`;
  - writing verbs (`say`, `reply`) echo the message object they wrote —
    same fields. The robust id-capture idiom is
    `taut say t "x" --json | jq -r 'select(has("ts")).ts'`, because a
    first-ever use may emit a leading creation line (next bullet) that
    has no `ts`;
  - notification objects (`inbox`, `watch`): `type`, `to_id`, `actor_id`,
    `actor_name`, `thread`, `message_ts`, plus `matched` for mention
    notifications;
  - `join` and `leave` echo their notice's message object;
  - list objects (`list`): `thread`, `kind`, `parent`, `unread` (bool),
    `last_ts`. Direct-message list objects also include `members`, an array of
    participant member ids. `last_ts` is the newest pending broker timestamp for
    the registered thread, obtained through SimpleBroker's public indexed
    lookup; claimed rows from foreign consumers do not count, matching
    [TAUT-7.1].
  - member objects (`who`, `whoami`, `rejoin`, `set name`): `member_id`,
    `name`, `aliases`, `kind`, `presence`, `last_active_ts`, `persona`
    (string or null); `whoami
    --explain` adds `explain` (object with the captured chain and the
    rule that matched; its internal layout is diagnostic, not a stable
    contract);
  - member **creation** (whichever verb caused it) emits one extra
    member-object line *first* — the normal member fields (including
    `persona` when supplied at creation) plus the one-time `token`
    field and no `ts` — followed by the verb's primary object. The token never
    appears in output again. Scripts must therefore select by field, not by line
    position, on paths that can create;
  - `init`: `db` (backend display target; a filesystem path for SQLite),
    `created` (bool). For Postgres, `created` is `false` because Taut has no
    public backend API for a reliable database-created signal.

  These field names are the current contract. Because the project is still in
  development, the specs describe the intended shape directly.
- Human-readable rendering (colors, alignment, time formatting) is
  explicitly not a stable contract.

### [TAUT-8.3] Python API

`taut.client.TautClient` is the embedding surface, and the CLI is a thin
argument-parsing layer over it — every CLI behavior above must be
reachable through one public client method with the same semantics (the
SimpleBroker/Weft layering rule: CLI and library share one operational
model). Public exports from `taut`: `TautClient`, `TautWatcher`,
`Message`, `Thread`, `Member`, the exception hierarchy rooted at
`TautError`, and `__version__`. The package ships typed (`py.typed`).

Core runtime dependencies: exactly `simplebroker>=5.1.0` and `psutil`. The
optional `taut-pg` extension adds `simplebroker-pg` and its driver dependencies
in the same environment as Taut. Python ≥ 3.11. The CLI uses argparse, not a CLI
framework.

### [TAUT-8.4] Watcher

`TautWatcher` subclasses a taut-vendored copy of Weft's
`MultiQueueWatcher` (adapted, attributed; taut must not depend on weft).
The preferred Python construction path is `TautClient.watch(...)`.
`TautWatcher` remains exported for embedding and advanced construction; direct
`TautWatcher(client, ...)` construction is a deprecated compatibility path that
is converted to the same internal watch runtime used by `TautClient.watch()`.
The vendored multi-queue watcher uses SimpleBroker's watcher lifecycle hook to
install its fan-in activity waiter and must not clone SimpleBroker's retry loop.
Contract:

- All queues run in peek mode with a per-queue cursor: fetch is
  peek-after-cursor, never `peek_one()` head-peeking (stock
  `MultiQueueWatcher` PEEK mode re-delivers the head message; the cursor
  override is what makes peek mode usable for chat). Pending checks are
  cursor-aware (`has_pending(after_timestamp=cursor)`), so drained threads
  go quiet instead of spinning.
- Cursors start at the member's stored `last_seen_ts` and persist back
  after each successfully handled message by default. Monotonic batched
  flushes (every N messages, on idle, on stop) are permitted: under
  [TAUT-7.2] monotonicity a crash can only re-show messages, never skip
  them.
- Cursor advancement happens **inside taut's per-queue handler wrapper,
  after the user handler returns** — not after the base watcher's
  dispatch reports. (SimpleBroker's dispatch path routes handler
  exceptions to the error handler and returns normally when that handler
  says "continue", so post-dispatch code cannot tell success from
  handled failure. The wrapper is the only seam that can.)
- A failing handler leaves the cursor in place — the message is re-seen
  (at-least-once display, mirroring SimpleBroker's peek-watcher rule).
  Poison-message liveness: after 3 consecutive failures on the same
  message, the watcher advances past it and emits a warning. At the
  display layer, liveness wins over completeness.
- Membership changes apply while running via `add_queue`/`remove_queue`.
  The watcher re-checks the membership table when the backend reports
  change (on SQLite, by extending SimpleBroker's data-version callback;
  the base callback refreshes `last_ts`, and sidecar writes bump
  `PRAGMA data_version` because they share the file) and at a bounded
  interval. The interval is the portable guarantee: backends whose wake
  signals cover only queue writes ([TAUT-12.1]) still converge on
  membership changes within the interval. Known transient SQLite sidecar
  reads (lock/busy/malformed/disk I/O or the corresponding timestamp
  row-shape misread) must be retried on watcher queue probes, fetches, cursor
  advancement, and membership reads. A transient data-version callback failure
  falls back to a normal pending scan instead of killing the watcher;
  non-transient exceptions still surface.
- `TautWatcher` uses non-persistent SimpleBroker queue handles. The core
  `MultiQueueWatcher` still supports persistent handles when explicitly
  requested, but taut's chat watcher must keep SQLite handles short-lived:
  summon runs watcher, control, provider, and peer CLI processes against one
  fresh database, and long-lived watcher handles have produced malformed-page
  reads under that WAL churn.

The TUI (future) is a consumer of `TautClient` + `TautWatcher`, ships as
the optional extra `taut[tui]`, and adds no new runtime dependency to the
core package.

## 9. Trust Model [TAUT-9]

Taut's trust model is deliberately weak, and the documentation must say so
plainly rather than imply otherwise:

- Everyone who can open the file is root of the chat. `.taut.db` is
  created with SimpleBroker's default 0600 permissions; any process that
  can read/write it can read all history, post as anyone (`--as` requires
  no proof), move cursors, and edit tables with sqlite3.
- Identity claims identify, they do not authenticate. Process evidence,
  continuity tokens, names, existing aliases, and `rejoin` make the common case
  frictionless and make attribution inspectable (`whoami --explain`, claims on
  record), not impossible to spoof.
- The boundary is the file system. Sharing with another uid means loosening
  file permissions yourself; taut will neither manage nor monitor that.
  When a server-backed broker arrives ([TAUT-12.1]), the boundary becomes
  database reachability — wider, but the same shape: storage access is
  membership.
- Threat model in one line: taut assumes every participant could already
  do worse than lie in chat, because they run inside your trust domain.

Anything stronger (signing, tamper evidence) is future work and must not be
implied by docs or output.

## 10. Failure Modes and Edge Cases [TAUT-10]

- No database found: exit 1 with the `taut init` hint ([TAUT-3.2]). `init`
  never runs implicitly.
- Partial failure in compound operations: sidecar writes and message
  writes cannot share a transaction (SimpleBroker forbids queue
  operations inside a sidecar transaction). Ordering rule: sidecar
  *registry and membership* state is written first and is authoritative;
  the notice or message write comes second and is the operation's
  success point for `say`/`reply`, while notices on `join`/`leave` are
  best-effort decoration; the writer's **cursor advance comes last,
  only after the insert succeeded, and is best-effort** ([TAUT-7.4]) —
  it is explicitly not part of the authoritative-first sidecar state.
  Every crash window therefore leaves a valid, merely quieter state
  (membership without a join notice; a registered, still-empty
  sub-thread; a written message with an unadvanced cursor that merely
  re-shows) — never the reverse, never a message in an unregistered
  thread, and never a cursor pointing past messages that were skipped.
  Sidecar writes are idempotent upserts so retrying the command
  converges.
- Locked/busy or transient WAL page-read database: SimpleBroker's busy-timeout
  and Taut's bounded public-wrapper retry discipline apply; surfaced errors
  name the database path when the budget is exhausted.
- Identity claim collision at rejoin: refused with the conflicting member named
  ([IAN-3.4]).
- Member whose process claim went stale: existing membership, history, direct
  messages, and notifications are untouched; the next command from the
  restarted process resolves by token, claim, explicit `--as`, or creates a new
  member with rejoin hints as defined in [IAN-3.3].
- Two members in one ancestor chain: the identity resolver chooses the nearest
  matching claim and `whoami --explain` shows the evidence.
- Same `(pid, start_time)` on two hosts sharing a database: distinct claims;
  `host_id` disambiguates, and it is an opaque machine identity rather than a
  hostname precisely because hostnames collide and drift ([TAUT-3.3],
  [IAN-3.2]).
- Crossing ssh/container boundaries: fresh ancestor chains, identity via
  explicit `--as`/`TAUT_AS` or continuity token propagation ([IAN-3.3]).
- Foreign body in a watched queue: rendered per [TAUT-6.3]; the watcher
  advances past it.
- Notification emission failure after a successful source message write:
  source message remains successful; the warning and retry behavior follow
  [IAN-7.3].
- Notification claimed but renderer fails: notification may be lost; source
  chat history remains the durable record ([IAN-7.4]).
- Partial channel rename: must be recoverable or loudly reportable under
  [IAN-8.3].
- Registry/queue divergence (queue deleted via broker CLI, registry row
  remains): thread lists and joins still work; reads show empty history.
  Taut never repairs silently; a future `doctor` verb may report.
- Newer `schema_version` in `taut_meta`: refuse with upgrade message
  ([TAUT-3.3]).
- Same member active in two processes (human in two terminals): legal;
  cursors are shared, monotonic writes make the union safe ([TAUT-7.2]).
- Unparseable `--since` value: SimpleBroker's parser error is surfaced
  verbatim, exit 1.

## 11. Verification Expectations [TAUT-11]

Proof obligations for the core implementation, and the standing anti-mocking
posture:

- The broker is never mocked. All client, CLI, and watcher tests run
  against real `.taut.db` files in temp dirs.
- Identity tests spawn real child processes where process evidence matters and
  assert claim creation, claim matching, rejoin, token acts-as from an unrelated
  process tree, stable `member_id`, and mutable names. Unit tests may cover
  capture parsing, but selection and matching must be proven through real
  client or CLI paths.
- Addressing and notification tests follow [IAN-10]. They must use real
  broker-backed queues and sidecar state, not mocked schema or queue helpers.
- Watcher tests run a live `TautWatcher` against concurrent writer
  processes and prove: no message lost, no message re-dispatched after
  cursor advance, cursor persisted, `add_queue` on mid-watch join, no
  busy-spin on idle peek queues (bounded poll count or CPU assertion),
  and the failure path: a raising handler leaves the cursor in place,
  the message is re-seen, and the 3-strikes rule advances past it with
  a warning ([TAUT-8.4]).
- CLI tests drive the real console entry point (subprocess or
  `run_cli`-style harness as in SimpleBroker) and assert exit codes 0/1/2
  and `--json` field names per [TAUT-8.2].
- Envelope encode/decode gets a property-based round-trip test including
  `from_id`, sender-name snapshots, and foreign-body inputs.
- Multi-process write/read interleaving over one database is exercised at
  least once (two writers, one reader, ordering by ts holds).

## 12. Roadmap Commitments and Forward Compatibility [TAUT-12]

These sections capture backend obligations beyond the default SQLite path. Taut
deliberately builds on the same components SimpleBroker and Weft already ship:
an alternative use case over proven parts. Where a real gap surfaces, it is
fixed upstream or at the state-boundary layer, never worked around locally.

### [TAUT-12.1] Postgres backend (multi-host for free)

Status: implemented in v0.2.0 as the separate `taut-pg` extension project.
The core package remains SQLite-first and does not depend on
`simplebroker-pg`.

Mechanism: `.taut.toml` ([TAUT-3.2]) carries the same
`backend`/`target`/`backend_options` shape as SimpleBroker's `.broker.toml` and
Weft's `broker.toml`. `resolve_broker_target()` discovers project config
first, sidecar tables live in the broker's configured Postgres schema, and the
multi-queue activity waiter rides LISTEN/NOTIFY while [TAUT-8.4]'s interval
refresh remains the portable correctness path.

Implementation boundaries:

- `extensions/taut_pg` is packaging, docs, and PG-only tests. It does not own
  target resolution, queue construction, sidecar SQL, identity, CLI behavior,
  or watcher behavior.
- The backend plugin is SimpleBroker's `simplebroker-pg` plugin, exposed
  through SimpleBroker's public backend entry point.
- Shared root tests marked `shared` must run against SQLite in the default
  suite and against Postgres through `bin/pytest-pg`.
- Extension tests marked `pg_only` must prove package import, plugin
  availability, `.taut.toml` selection, sidecar compatibility, and cleanup
  against a real Docker Postgres database.
- Release remains GitHub-only and is governed by [TAUT-12.5]. Postgres
  extension releases use `taut_pg/vX.Y.Z`.

Binding obligations:

- no SQLite-specific assumptions outside target resolution and the
  documented data-version wake ([TAUT-8.4] interval backstop is the
  portable path)
- sidecar SQL uses qmark placeholders only (SimpleBroker translates them
  for Postgres)
- SimpleBroker hybrid timestamps and process ids are stored in `BIGINT`
  columns in documented DDL so Postgres does not truncate values that SQLite
  accepts as unbounded integers
- identity claims are host-aware: host identity is captured as claim evidence,
  stored in sidecar state, and used to prevent pid/uid collisions across
  Postgres-backed multi-host databases ([IAN-3.2])

### [TAUT-12.2] Redis/Valkey backend (needs a state mapping, not new plumbing)

Queues come from `simplebroker-redis` as-is. Taut's member/thread/cursor
state does not ride along automatically: sidecar tables exist on SQL
backends so embedded state can share the broker's single-file locking
and retry discipline through one connection, and the Redis backend has
no SQL storage (`Queue.sidecar()` raises `SidecarUnavailableError`
there). On Redis none of that multiplexing is needed — taut state
becomes a **second connection to the same Redis** under a `taut:*` key
namespace, once a data-structure mapping is designed (members, threads,
and membership as hashes; the monotonic cursor advance of [TAUT-7.2] as
an atomic max via a small Lua script or `WATCH`/`MULTI`). Deferred until
that mapping has its own spec section.

Binding obligation: every taut state read and write flows through one state
module, so the SQL implementation and a future Redis mapping are swappable
behind a single interface. The single-target principle generalizes with it:
whatever backend holds the queues holds the state.

### [TAUT-12.3] Captive agents (`summon`)

Host an existing agent harness as a thread member. Summon is the agent's
terminal, not its runtime: the summon driver injects chat messages into
the harness's own live session (its ears), and the agent speaks through
the ordinary taut CLI, selected as its member by its continuity token
— continuity, not authentication ([TAUT-5], [TAUT-9]) — (its mouth).
There is no summon-defined agent protocol — adapters speak each
provider's native streaming envelope. The full contract lives in
`docs/specs/04-summon.md` ([SUM-1]–[SUM-12]); the 2026-06-12 shape
decisions below stand, refined there: the "line-oriented IO bridged to a
thread" sketch is superseded by the ears/mouth split, and the inbox queue
role maps to the member's chat threads themselves.

Shape decided 2026-06-12:

- Ships as a **separate extension package** (`taut-summon`), so the core
  package keeps its runtime dependency set deliberately small. The
  extension may grow optional backends behind its own extras later
  without touching core.
- The captive lane is **taut-native**: built on the vendored multi-queue
  watcher plus direct child-process supervision by the summoning
  process. No manager or daemon appears — the no-daemon property holds
  end to end.
- It is **contract-congruent with Weft's agent task, not code-vendored
  from it**: same control verbs (STOP/STATUS/PING), same queue role
  shapes (inbox/ctrl_in/ctrl_out), same conversation-scope semantics,
  with every divergence listed in the summon spec alongside its reason.
  (Whole-and-faithful vendoring was right for the multi-queue watcher —
  one stable class, diffable against upstream. The agent task is an
  evolving subsystem; there, taut copies the contract, not the code.)
- The summon spec doubles as an **executable conformance suite** for the
  long-running conversational agent contract — control responsiveness
  during idle, restart with conversation scope intact, backpressure when
  the agent is slower than the chat, clean shutdown on leave — written
  portably so Weft can run the same suite against its own agent lane in
  its CI. Contract findings flow upstream as tests, not prose (the plan
  §9 discipline).

Core obligations: envelope readers ignore unknown fields ([TAUT-6.1]) and no
code assumes members only speak via CLI invocations.

### [TAUT-12.4] TUI

Per [TAUT-8.4]: a consumer of `TautClient` + `TautWatcher`, optional
extra, own spec.

### [TAUT-12.5] Release machinery

Status: implemented as local helper plus GitHub Actions release gates.

The repository release boundary is **GitHub-only** until package-name clearance
changes this spec. `bin/release.py` coordinates local version sync, release
prechecks, release-file commits, tag planning, and tag pushes; it never uploads
to PyPI. `--publish` is a compatibility no-op and must say that pushing the tag
is the publication boundary.

Release targets:

- `core` (aliases: `root`, `taut`) releases the root `taut` package with a
  `vX.Y.Z` tag and `.github/workflows/release-gate.yml`.
- `pg` releases `taut-pg` from `extensions/taut_pg` with a
  `taut_pg/vX.Y.Z` tag and `.github/workflows/release-gate-pg.yml`.
- `summon` releases `taut-summon` from `extensions/taut_summon` with a
  `taut_summon/vX.Y.Z` tag and
  `.github/workflows/release-gate-summon.yml`.
- `all` releases every current package version that does not already have a
  GitHub Release. `--version` is invalid with `all`; maintainers must edit
  package version files first when preparing a multi-package version bump.

Helper obligations:

- Accept both positional target form (`bin/release.py pg`) and the older
  `--target pg` form.
- Before release, reject dirty worktrees unless `--dry-run` is set, reject
  already-published GitHub Releases, and plan local/remote tag actions without
  force-pushing tags. Retagging deletes the remote tag first and then pushes the
  recreated tag.
- Keep version files synchronized: root `pyproject.toml` and
  `taut/_constants.py`; extension `pyproject.toml` files; each first-party
  extension's `taut>=...` floor to the current root version; and the root dev
  dependency `taut-summon>=...` to the current local `taut-summon` version.
- Track generated release files when committing, including
  `extensions/taut_summon/uv.lock` for the summon extension.
- Run the relevant local gates before mutation unless `--skip-checks` is set:
  root pytest, `bin/pytest-pg --fast` for core or PG releases, the
  `extensions/taut_summon/tests` suite for core or summon releases split into
  non-process, deterministic `xdist_group` process, strict external-live, and
  local-LLM lanes, ruff over root plus touched extension paths, and split mypy
  lanes so extension `conftest.py` modules do not collide. The process/live/LLM
  lanes are isolated from unrelated summon tests because they drive multiple
  real processes against shared SQLite files; xdist still schedules each lane
  with `-n 1 --dist loadgroup`, but the lanes run as fresh pytest invocations
  rather than one long worker.
- For core or summon releases, require the summon local-LLM lane locally. The
  helper starts local LLM preparation at the beginning of prechecks so Docker
  image/model setup can overlap root and PG checks. It uses an existing
  loopback endpoint when the configured model is already listed; otherwise it
  starts a disposable loopback Ollama container with the same bounded model
  shape as CI, waits for the served model only when the dedicated local-LLM lane
  is reached, and runs that lane with `TAUT_SUMMON_LOCAL_LLM=1`. A separate
  external-live lane runs installed external harnesses in strict prewired mode
  (`TAUT_SUMMON_LIVE_HARNESS_STRICT=1`) so local release checks do not pass by
  skipping already-installed provider CLIs for onboarding.
- In `.github/workflows/test.yml`, keep summon's deterministic process lane
  aligned with the release helper selector:
  `xdist_group and not requires_live_harness and not requires_local_llm`. Run
  that lane as a dedicated fresh matrix job, still under `-n 1 --dist
  loadgroup`, so it is not preceded by the broad root and summon unit suites in
  the same runner environment. The local-LLM lane runs in its own CI job with a
  prepared loopback Ollama model. External-provider live harnesses are a strict
  local release gate unless CI grows explicit credentials/tooling for those
  provider CLIs.
- After version sync, build the selected package artifacts and run
  `uv lock` in `extensions/taut_summon` when the summon package is selected.

Workflow obligations:

- `.github/workflows/release-gate.yml` listens to `v*`, runs the reusable root
  test workflow and the PG extension workflow, verifies the tag still points at
  the tested commit, and calls the reusable release workflow for `taut`.
- `.github/workflows/release-gate-pg.yml` listens to `taut_pg/v*`, runs the
  reusable root test workflow and PG extension workflow, verifies the tag, and
  calls the reusable release workflow for `taut-pg`.
- `.github/workflows/release-gate-summon.yml` listens to `taut_summon/v*`, runs
  the reusable root test workflow (which includes the summon extension and
  local-LLM lane), verifies the tag, and calls the reusable release workflow for
  `taut-summon`.
- `.github/workflows/release.yml` is the only artifact publisher. It builds the
  selected package directory and creates/uploads a GitHub Release. It must not
  contain PyPI upload or Trusted Publishing steps.

## Related Plans

- `docs/plans/2026-06-30-client-module-split-plan.md` — structural
  refactor of `taut.client` from a single module into a package facade and
  concern-specific mixins while preserving the [TAUT-8.3] public import and
  Python API contract.
- `docs/plans/2026-06-18-member-identity-addressing-plan.md` - implemented
  migration from the current development implementation to the stable
  member identity, mutable naming, direct-message, and notification model.
- `docs/plans/2026-06-12-taut-foundation-plan.md` — historical foundation:
  package scaffolding, schema, identity, envelope, client, watcher, CLI.
- `docs/plans/2026-06-12-taut-0.1.1-hardening-plan.md` — post-0.1.0
  hardening slice: name-quality fix, [TAUT-11] burndown, renderer
  conformance to the README, round-5 review, 0.1.1 tag.
- `docs/plans/2026-06-17-github-release-helper-plan.md` — GitHub-only
  release helper while the PyPI `taut` package-name request is pending.
- `docs/plans/2026-06-17-github-actions-release-workflows-plan.md` —
  GitHub Actions test and GitHub-only release publication workflows.
- `docs/plans/2026-07-08-release-helper-simplebroker-port-plan.md` —
  release-helper port to SimpleBroker-style targets, batch planning, summon
  release gating, and GitHub-only release machinery documentation.
- `docs/plans/2026-06-17-taut-pg-extension-plan.md` — implemented
  [TAUT-12.1] plan: separate `taut-pg` extension project,
  Postgres shared/PG-only test split, `bin/pytest-pg`, and GitHub-only
  extension release flow.
- `docs/plans/2026-06-17-implementation-review-followups-plan.md` —
  post-review hardening for missing-plugin errors, bounded `log --limit`,
  project-config proof strength, and expanded shared backend conformance.
- `docs/plans/2026-06-18-simplebroker-latest-timestamp-plan.md` —
  implemented issue #3 fix: use SimpleBroker's indexed latest pending
  timestamp API for `list` metadata instead of a full-history scan.
- `docs/plans/2026-07-01-taut-state-sql-dialect-plan.md` — implemented
  [TAUT-12.2] state-module refactor: introduce an internal `TautState`
  interface and `SqlDialect` seam while preserving current SQLite/Postgres
  behavior.
- `docs/plans/2026-07-01-taut-watch-runtime-plan.md` — implemented
  [TAUT-8.4] follow-up: replace `TautWatcher` access to `TautClient` private
  state and decoder methods with an internal `TautWatchRuntime` seam.
- `docs/plans/2026-07-06-evaluation-findings-remediation-plan.md` —
  implemented evaluation-findings remediation: [TAUT-8.1] usage-error exit
  codes and `--` end-of-options, channel-rename resume, error-path
  hardening, and CLI-surface test-gap closure.
