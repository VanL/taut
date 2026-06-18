# Taut Core Specification

Status: Proposed (governs the v0.1 implementation)

Taut is private, no-config chat for the processes that already share your
machine: you, your agents, and anything else that can run a CLI. It is built
on SimpleBroker and stores everything — messages, threads, members, read
state — in one SQLite file, `.taut.db`, by default. With the `taut-pg`
extension installed, the same state lives in a project-configured Postgres
schema.

This spec defines intended behavior for the v0.1 core: storage model,
identity, message contract, read model, and the CLI, Python API, and watcher
surfaces. It is the source of truth those surfaces are verified against.

## 1. Purpose and Scope [TAUT-1]

In scope:

- the default `.taut.db` storage model and project resolution rules
- thread and room semantics over SimpleBroker queues
- member identity, process fingerprinting, recognition, and rejoin
- the message envelope contract
- the read model: cursors, unread state, and the peek-only discipline
- the CLI surface, the `TautClient` Python API, and the `TautWatcher`
- the trust model and its limits

Out of scope for v0.1 but committed on the roadmap, with compatibility
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
- code-signing identity as fingerprint evidence (recorded as a possible
  future macOS evidence field; not captured in v0.1)

## 2. Mental Model [TAUT-2]

- One file by default. `.taut.db` is a standard SimpleBroker database plus
  taut-owned sidecar tables. There is no other durable state in the SQLite
  path: no config file, no state directory, no lock files. (SQLite WAL
  companions `.taut.db-wal` and `.taut.db-shm` are transient and managed by
  SQLite.) Under `taut-pg`, `.taut.toml` selects a Postgres target and the same
  sidecar tables live in that configured schema.
- A thread is a queue. A **room** is a top-level thread (`general`). A
  **sub-thread** hangs off one message in a room and is itself a queue
  (`general.1837025672140161024`, named by the origin message id).
- Messages are never consumed. Every reader peeks; nothing is ever claimed,
  so the queue is the conversation history. "Read" in taut means "move my
  bookmark", never "remove".
- Who you are is where you ran from. Agents are recognized by a process
  fingerprint anchored at `(pid, process start time)` of an ancestor
  process. Humans are recognized by uid. Explicit `--as` always wins.
- Per-member state is relational. Members, thread registry, membership, and
  read cursors live in `taut_*` sidecar tables in the same file, written
  through SimpleBroker's sidecar API.
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
SimpleBroker project resolution. `TAUT_DB`, `TAUT_AS`, and `TAUT_TOKEN`
([TAUT-5.8]) are the only public environment knobs in v0.1.

### [TAUT-3.3] Sidecar schema v1

Taut-owned tables are created through `Queue.sidecar(transaction=True)`
with idempotent DDL at `taut init` time and verified (created if missing)
on first write access. All tables are prefixed `taut_`.

```sql
CREATE TABLE IF NOT EXISTS taut_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);  -- holds schema_version, currently '1'

CREATE TABLE IF NOT EXISTS taut_members (
    handle            TEXT PRIMARY KEY,
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
);  -- anchor_* and fingerprint are NULL for kind='human'.
    -- token is the continuity token minted at creation ([TAUT-5.8]);
    -- meta is a JSON object; defined keys so far: "persona"
    -- ([TAUT-5.9]). Unknown keys are preserved.
    -- host_id is the opaque stable host identity from [TAUT-5.1];
    -- host_label is the human-readable hostname for display only.
    -- pids and uids only mean anything on their own host, and the
    -- Postgres backend ([TAUT-12.1]) makes multi-host databases real.
    -- Schema v1 carries both columns from day one because the first
    -- release freezes the schema.

CREATE UNIQUE INDEX IF NOT EXISTS taut_members_anchor_unique
    ON taut_members (host_id, anchor_pid, anchor_start_time)
    WHERE anchor_pid IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS taut_members_human_unique
    ON taut_members (host_id, uid)
    WHERE kind = 'human';

CREATE TABLE IF NOT EXISTS taut_threads (
    name       TEXT PRIMARY KEY,
    parent     TEXT,
    origin_ts  BIGINT,
    created_by TEXT NOT NULL,
    created_ts BIGINT NOT NULL
);  -- parent/origin_ts are NULL for rooms

CREATE TABLE IF NOT EXISTS taut_membership (
    thread       TEXT NOT NULL,
    member       TEXT NOT NULL,
    joined_ts    BIGINT NOT NULL,
    last_seen_ts BIGINT NOT NULL DEFAULT 0,
    PRIMARY KEY (thread, member)
);
```

The unique indexes are the schema backstop for the identity invariants:
one anchor → at most one member, one (host, uid) → at most one human.
Member-creation paths must treat a uniqueness violation as a lost race,
not an error — re-resolve and use the member the other process created.
(Partial unique indexes work identically on SQLite and Postgres, so this
stays inside the I9 portability rule.)

Schema evolution is additive within v1 (new tables, new nullable columns).
Any breaking change bumps `schema_version` and requires an explicit
migration path in a future spec revision. Older taut versions encountering
a newer `schema_version` must refuse with a clear error rather than guess.

### [TAUT-3.4] SimpleBroker interop

`.taut.db` is a standard SimpleBroker database. `broker -f .taut.db list`,
`peek`, `dump`, and friends work on it, and that interop is a feature, not
an accident. Two consequences are binding:

- Taut uses only SimpleBroker's public API (`simplebroker` and
  `simplebroker.ext` exports). No underscore-module imports, and no SQL
  against SimpleBroker's own tables — taut's SQL touches `taut_*` tables
  only.
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

## 4. Threads and Rooms [TAUT-4]

### [TAUT-4.1] Naming

- Room names match `^[a-z0-9][a-z0-9_-]{0,63}$`. No dots: the dot is the
  hierarchy separator. Uppercase is rejected, not folded.
- The room name `taut` and the prefix `taut.` are reserved for future
  system use; creating them is an error.
- A sub-thread's queue name is `<room>.<origin_ts>` where `origin_ts` is
  the message id it branched from. Sub-threads of sub-threads are not
  supported in v0.1 (one level, like Slack).
- These names are valid SimpleBroker queue names by construction; taut
  performs its own validation before SimpleBroker sees the name.

### [TAUT-4.2] Creation and registry

- `join` on a nonexistent room creates it: a `taut_threads` row plus a
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
- Joining a room does not auto-join its sub-threads. Replying to a
  sub-thread, or explicitly reading one (`read room.<ts>`), joins it
  implicitly — provided the caller is a member of the parent room
  (Slack's "you're in the thread now"). Rooms are never joined
  implicitly; `read` on a room you have not joined is a miss ([TAUT-8.1]).

## 5. Identity and Fingerprinting [TAUT-5]

### [TAUT-5.1] Fingerprint capture

At identity-relevant commands, taut captures its own ancestor process
chain, from its parent upward, bounded at 12 levels or the first
unreadable ancestor. Per process, best-effort:

- pid and process start time (the load-bearing pair: start time disarms
  pid reuse)
- executable path and argv
- uid, parent pid, process group id, session id, controlling tty
- host identity: an opaque stable id (`/etc/machine-id` on Linux,
  `IOPlatformUUID` on macOS, hostname only as last resort) plus the
  hostname as a display label. Hostnames are not identity — macOS
  renames them spontaneously and containers randomize them; pids and
  uids are meaningless off their host, and multi-host databases
  ([TAUT-12.1]) make collisions real (two devcontainers named
  `devcontainer`, both uid 1000). Matching always uses the opaque id;
  container/namespace evidence is a [TAUT-12.1]-round refinement.
- current working directory (may be unavailable for non-self processes on
  macOS without elevated rights; recorded as null when unknown)

Source is `psutil` for cross-platform process metadata, with `/proc` on
Linux and `ps`/`lsof` fallbacks where a native start-time token or
best-effort field is still needed. Capture must degrade field-by-field:
a missing field is null, never a failed command.

Start time is an opaque token: taut stores the platform-native value
exactly as captured (the `/proc` ticks field on Linux, the `ps lstart`
string on macOS) and matches by byte equality. It is never parsed into
numeric or calendar form — locale, precision, and rounding drift would
silently break the pid+start-time pair. This is why [TAUT-3.3] types
`anchor_start_time` as TEXT.

Executable identity must never come from a truncatable field. macOS
`ps -o comm=` clips to 16 characters (`/opt/homebrew/bi`), which is
enough to defeat shell classification and anchor identities on
per-command wrappers. Rule: when the captured executable path does not
end with `argv[0]`'s basename, `argv[0]` is the authoritative path
source; the [TAUT-5.2] shell/wrapper/infrastructure classification must
consult the best-available untruncated basename. (Capture-fidelity
note for implementers and test authors: `sh -c` with a single simple
command exec-optimizes the shell out of the chain entirely — wrappers
under test must run compound commands to exist at all.)

### [TAUT-5.2] Anchor selection

The **anchor** is the ancestor that *is* the member. Selection walks the
chain from taut's parent upward and picks the first process that is not:

- a shell (`sh`, `bash`, `zsh`, `fish`, `dash`, `ksh`, `csh`, `tcsh`), or
- a trivial wrapper (`env`, `command`, `timeout`, `xargs`, `nohup`,
  `setsid`, `script`, `uv`, `uvx`, `npx`), or
- session infrastructure (`tmux`, `screen`, `sshd`, `login`, terminal
  emulators, `launchd`, `systemd`, `init`).

If such a process exists, the caller is presumed to be an **agent**
anchored there (the direct parent of a CLI invocation is usually a shell;
the agent is one or two levels above it — anchoring must look past
wrappers). If the walk hits session infrastructure or the chain top first,
the caller is presumed to be the **human** owning the uid. The lists above
are constants in one module, not configuration.

Recognition stops at process-namespace boundaries: `ssh box taut …` and
`docker exec app taut …` start fresh ancestor chains in which the
originating agent does not appear, so the caller resolves per the rules
above *inside* that boundary (and typically auto-creates a new identity
there). The supported pattern for crossing the boundary is explicit
identity: propagate `TAUT_AS` (or pass `--as`) through ssh/container
invocations. Namespace-aware evidence is a [TAUT-12.1]-round refinement,
not a v0.1 behavior.

### [TAUT-5.3] Resolution order

Every command resolves the acting member, in order:

1. `--as HANDLE` / `TAUT_AS` — explicit always wins. If the handle
   exists, act as that member for this command (no proof required, see
   [TAUT-9]; acting never re-anchors — `rejoin` is the only verb that
   moves anchors). If the handle does not exist, create it: anchored to
   the current chain when the chain is agent-shaped *and* that anchor is
   unclaimed; otherwise created **unanchored** (kind from the chain
   shape, no anchor). Unanchored members are reachable only via `--as`
   until a later `rejoin` gives them an anchor — anchor uniqueness
   ([TAUT-5.5]) is never violated to satisfy `--as`.
2. Continuity token — if `TAUT_TOKEN` is set (or `--token` given), act
   as the member holding that token ([TAUT-5.8]). A token that matches
   no member is a loud error (exit 1), never a silent fall-through —
   a presented credential failing quietly would mis-attribute
   everything after it.
3. Anchor match — if any stored agent anchor `(pid, start_time)` appears in
   the current ancestor chain *and its stored `host_id` equals the local
   host identity*, the member whose anchor is **nearest to the calling
   process** wins. Nearest-wins is what lets an agent and the human who
   launched it coexist in one process tree; the host clause is what keeps
   anchors meaningful when a Postgres-backed database spans machines.
4. Human fallback — if the chain is human-shaped per [TAUT-5.2], resolve
   to the human member with the caller's uid on the local `host_id`
   (uids, like pids, mean nothing off-host), creating it on first
   state-changing command with handle = login name (suffix-disambiguated
   per [TAUT-5.4] if the name is taken).
5. Otherwise the caller is **unrecognized**: an agent-shaped chain with no
   matching anchor.

### [TAUT-5.4] Unrecognized callers, auto-creation, and suggestions

For the read-only commands `list`, `log`, `who`, and `whoami`, an
unrecognized caller operates as a guest: output works, no cursor exists,
nothing is written. `read` is **not** guest-available — it exists to
advance a member's cursors, so it requires a resolved member and (for an
explicit thread) membership; a non-member gets exit 2 with a hint to
`log` or `join` ([TAUT-8.1]).

For state-changing commands (`join`, `say`, `reply`) from an
unrecognized caller, taut first computes **candidates**: existing agent
members ranked by fingerprint similarity (same executable path: strong;
same cwd: medium; same tty or session: weak; recent `last_active_ts`:
tiebreak; scoring is implementation-owned, not contract). Then:

- Interactively, taut presents the candidates and asks — rejoin one of
  them, or join as new. "Interactively" means **stdin is a tty and
  neither `--json` nor `-q` is in effect**; `--json` output must stay
  pure ndjson, so it always takes the non-interactive path below.
  (Consequence: a human running `echo hi | taut say ci -` is mid-pipe,
  stdin is not a tty, and gets the non-interactive path too — the hint
  on stderr is their prompt.)
- Off-tty (agents — no prompts, ever, [TAUT-8.2]), taut auto-creates a
  new member anchored at the current chain — join stays frictionless —
  and prints the candidate list as a rejoin hint to stderr:

```
created new identity 'claudette'
note: you may be one of these —
        claude     same executable, same cwd, active 4m ago
        claudius   same executable, active 2d ago
      reclaim with 'taut rejoin claude' (or set its TAUT_TOKEN).
```

- `join --new` skips candidates and prompting entirely and creates a
  fresh identity on either kind of terminal.

Taut never rejoins automatically; the choice is the caller's.

Generated handles avoid the `name-2` aesthetic: the first instance of an
executable gets its basename (`claude`); later unrecognized instances
draw from a per-basename knockoff pool (`claudette`, `claudius`,
`claudion`, `claudine`, …), then from a shared pool of names from the
history of computing and ideas (`ada`, `grace`, `blaise`, `hypatia`,
`kurt`, …), and only as a last resort fall back to numeric suffixes.
Pools are constants in one module (like the shell lists), all entries
satisfy the handle rule, and selection is deterministic (first unused,
in order) so tests and transcripts are reproducible. The numeric-suffix
rule still backstops every other collision in taut, including the human
login-name fallback.

### [TAUT-5.5] Rejoin

`taut rejoin [HANDLE]` re-anchors an existing member to the current
chain's anchor and replaces its stored fingerprint. It is the explicit
"that was me" verb after a process restart.

Target selection, exactly: the positional HANDLE if given; otherwise a
`--token` selector (either `rejoin --token TOKEN` or global
`--token TOKEN`); otherwise the member selected by global `--as`.
Giving HANDLE plus any `--token` is an error (ambiguous selectors), and
bare `rejoin` with no selector of any kind is an error with a usage
hint. For this verb the selectors name the **target**, and the target is
also the acting member for attribution (`last_active_ts`) —
re-anchoring *is* the target proving it is alive; there is no separate
acting identity to resolve.
Rules:

- Anchor uniqueness is an invariant enforced at every join and rejoin: one
  anchor, at most one member. `rejoin HANDLE` succeeds iff the current
  chain's anchor is unclaimed or already belongs to `HANDLE`; if it
  belongs to a different member (typically an auto-created `claudette`),
  `rejoin` fails and names that member. There is no merge verb in v0.1;
  the resolution is to rejoin from the right process, or rejoin the stray
  identity itself if that is the one you want going forward.
- Membership rows and cursors are untouched by rejoin; identity continuity
  is the whole point.

### [TAUT-5.6] Presence and activity

- Agent liveness is checked on demand (`who`): the anchor pid exists and
  its start time matches the stored one. Match → `here`; no match →
  `gone`. Liveness is checkable only for anchors on the local host;
  members anchored elsewhere show `remote` (their activity timestamps
  still tell the story). Humans are not liveness-checked (shown by
  activity only).
- Every resolved (non-guest) command updates the member's
  `last_active_ts`.

### [TAUT-5.7] Transparency

`taut whoami --explain` prints the captured chain, which anchor or fallback
rule matched, and why — the heuristic must be observable, because it will
sometimes be wrong and the fix (`--as`, `rejoin`) is only discoverable if
the decision is visible.

### [TAUT-5.8] Continuity tokens

Every member gets a token at creation — short, URL-safe, generated with
`secrets` (`taut-` prefix plus random base32). It is shown exactly once
in the creation output ([TAUT-8.2]) with the suggestion to stash it in
the agent's own state; afterward it lives only in the database.

A token is **continuity, not authentication**. It confers nothing
`--as` doesn't already (the trust model holds, [TAUT-9]); what it adds
is a zero-heuristic way for the *same logical agent* to be itself again
when its process tree has churned — new session, new tty, cron respawn,
fresh container. `TAUT_TOKEN` in the agent's environment means
"remember me", and it survives everything the process anchor doesn't.
It is stored in plaintext: hashing it would imply a security property
taut explicitly does not have.

Token resolution **acts as** the member ([TAUT-5.3] step 2); it does not
move the anchor. Re-anchoring stays the explicit job of `rejoin`, which
accepts `--token` as an alternative selector to the handle
([TAUT-5.5]) — present the token once, rejoin, and the process tree
recognizes you from then on without it.

### [TAUT-5.9] Personas

A member may carry a persona: a saved prompt/description string in
`meta.persona`. Set it at join time (`taut join debate --as claudius
--persona "Stoic. Argues from first principles."`) or update it by
re-running `join --persona`; show it via `who`/`whoami` ([TAUT-8.2]
member objects carry `persona`). To be explicit about power: **any
writer may set or update any member's persona** (and join that member
to rooms) via `--as HANDLE --persona …` — that is the [TAUT-9] trust
model, where storage access is membership; "update it as that member"
is convention, not enforcement. Taut itself only stores and displays
the persona — it is the natural system-prompt seed for captive agents
([TAUT-12.3]) and the thing that makes multi-agent debates read like
debates instead of like one process arguing with itself.

## 6. Message Envelope [TAUT-6]

### [TAUT-6.1] Envelope v1

Every message taut writes is one JSON object, UTF-8, no newlines required:

```json
{"v": 1, "from": "claude", "kind": "message", "text": "parser is green"}
```

- `v` (int, required): envelope version, `1`.
- `from` (string, required): sender handle at write time.
- `kind` (string, required): `"message"` or `"notice"`.
- `text` (string, required): the content.

The broker timestamp is the message id and time; the envelope never
duplicates it. Readers must ignore unknown fields (forward tolerance);
writers must not emit fields outside this spec plus a future-versioned
extension. A `v` greater than known renders as raw text with a one-line
upgrade warning to stderr, never an error.

### [TAUT-6.2] Notices

System events are ordinary messages with `kind: "notice"` and
human-readable `text` (`"van created #general"`, `"claude joined"`,
`"claude left"`). Notices come from the member that caused them — there is
no system member. Renderers display them dimmed/inline; `--json` consumers
filter on `kind`.

### [TAUT-6.3] Foreign bodies

A body that does not parse as a v1 envelope (raw `broker write`, other
tools) renders with sender `?` and the raw body as text. In `--json`
output it is an ordinary [TAUT-8.2] message object — same fields, no
extras — with `"from": "?"` and `"kind": "foreign"`. `foreign` is an
output-only kind: taut never writes it to a queue, and the envelope `v`
field never appears in output. Foreign bodies must never crash or stall
any taut surface.

### [TAUT-6.4] Limits

Body size and content limits are SimpleBroker's (10 MB default). Taut adds
no limit of its own; `text` is arbitrary UTF-8 including newlines and
terminal control characters — escaping at render time is the renderer's
job, and `--json` output is the safe path for machine consumers.

## 7. Read Model [TAUT-7]

### [TAUT-7.1] Peek-only invariant

No taut surface consumes, claims, moves, or deletes broker messages. All
retrieval is peek-family API. v0.1 ships no deletion verb at all; history
is append-only. (Consequence: SimpleBroker vacuum never has work; claimed
counts stay 0. A nonzero claimed count means a foreign tool consumed
messages — tolerated, but those messages are gone from history.)

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
`log` — joining a busy room must not scream a thousand unread. One
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

One executable, `taut`. Global options: `--db PATH`, `--as HANDLE`,
`--token TOKEN` (acts-as via continuity token, [TAUT-5.8]; the flag
wins over the `TAUT_TOKEN` env var), `--json`, `-t/--timestamps` (show
message ids in human output; `say` prints the new message's id),
`-q/--quiet`, `--version`, `--help`.

| Verb | Behavior | Exit codes |
|---|---|---|
| `init` | Create the resolved SQLite `.taut.db` or initialize the configured backend target plus sidecar schema in the current directory. Idempotent with notice if present. | 0 created/exists, 1 error |
| `join THREAD [--as NAME] [--persona TEXT] [--new]` | Register identity if needed (`--new` forces a fresh one, [TAUT-5.4]), create room if needed, add membership (cursor at now, [TAUT-7.4]), write notice. `--persona` sets/updates the member's persona ([TAUT-5.9]). | 0; 1 error |
| `leave THREAD` | Remove membership, write notice. | 0; 1 error; 2 not a member |
| `say THREAD [TEXT\|-]` | Post a message (stdin with `-` or when piped and TEXT omitted). Requires membership: non-members are refused with a `taut join` hint, mirroring `read`. Prints message id with `-t`. | 0; 1 error; 2 not a member (hint on stderr) |
| `reply THREAD MSG_ID [TEXT\|-]` | Post into the sub-thread of MSG_ID, creating it on first reply. Requires membership in THREAD. A full 19-digit id resolves exactly (peek by id — works for any message ever written). A suffix ≥ 4 digits resolves via a bounded public-API scan of the most recent 1,000 message ids of THREAD; ambiguous → error listing candidates. | 0; 1 error (incl. ambiguous suffix); 2 no such message / not a member |
| `read [THREAD]` | Show unread (all joined threads when bare, grouped), advance cursor through displayed messages. Reads are paged: one invocation displays and marks seen up to 1,000 unread messages per thread; callers drain larger backlogs by rerunning until exit 2. Requires a resolved member; explicit THREAD requires membership (sub-threads implicit-join per [TAUT-4.3]). | 0 showed messages; 1 error; 2 nothing unread / not a member (hint on stderr) |
| `log THREAD [--since TS] [--limit N]` | Show history. No cursor movement. `--limit N` selects the most recent N messages after `--since`, rendered in chronological order. | 0; 1; 2 empty |
| `list [--all]` | Bare: joined threads with unread state. `--all`: every registered thread. | 0; 2 when bare list has no unread |
| `watch [THREAD ...]` | Live-follow (default: all joined threads), advancing cursor per message. Adds/drops threads as membership changes while running; a running watch that loses its last membership keeps running idle and picks up the next join. | 0 on clean stop; 1 error; 2 started with no joined threads (hint to join) |
| `who [THREAD]` | Members and presence (thread members, or all members when bare). | 0; 1 error; 2 no such thread |
| `whoami [--explain]` | Resolved identity; with `--explain`, the evidence and rule. | 0 resolved; 1 error (incl. invalid token); 2 unrecognized |
| `rejoin [HANDLE] [--token TOKEN]` | Re-anchor a member to the current process chain ([TAUT-5.5]). Target: HANDLE if given, else `--token` (subcommand or global), else global `--as`; HANDLE combined with any `--token` is an error. | 0; 1 error/collision/ambiguous selectors; 2 no such handle/token |

Exit-code rule, matching SimpleBroker: 0 success, 1 error, 2 "empty /
nothing matched / not found" — so `taut read -q && process_inbox` and
polling loops compose in shell.

### [TAUT-8.2] Output contract

- Human output goes to stdout, hints and warnings to stderr. No prompts
  when stdin is not a tty; in non-tty contexts taut decides per the rules
  in this spec and reports what it did (agents must never hang on a
  question).
- `--json` emits one JSON object per line (ndjson), and **every verb has
  a defined JSON shape** — an agent must never have to guess:
  - message objects (`read`, `log`, `watch`): exactly `thread`, `ts`,
    `from`, `kind`, `text`;
  - writing verbs (`say`, `reply`) echo the message object they wrote —
    same five fields. The robust id-capture idiom is
    `taut say t "x" --json | jq -r 'select(has("ts")).ts'`, because a
    first-ever use may emit a leading creation line (next bullet) that
    has no `ts`;
  - `join` and `leave` echo their notice's message object;
  - list objects (`list`): `thread`, `parent`, `unread` (bool),
    `last_ts`. `last_ts` is the newest pending broker timestamp for the
    registered thread, obtained through SimpleBroker's public indexed lookup;
    claimed rows from foreign consumers do not count, matching [TAUT-7.1].
  - member objects (`who`, `whoami`, `rejoin`): `handle`, `kind`,
    `presence`, `last_active_ts`, `persona` (string or null); `whoami
    --explain` adds `explain` (object with the captured chain and the
    rule that matched; its internal layout is diagnostic, not a
    compatibility surface);
  - member **creation** (whichever verb caused it) emits one extra
    member-object line *first* — the normal member fields (including
    `persona` when supplied at creation) plus the one-time `token`
    field ([TAUT-5.8]) and no `ts` — followed by the verb's primary
    object. The token never appears in output again. Scripts must
    therefore select by field, not by line position, on paths that can
    create;
  - `init`: `db` (backend display target; a filesystem path for SQLite),
    `created` (bool). For Postgres, `created` is `false` because Taut has no
    public backend API for a reliable database-created signal.

  These field names are a compatibility surface from v0.1 on; additions
  are allowed, renames and removals are not.
- Human-readable rendering (colors, alignment, time formatting) is
  explicitly not a compatibility surface.

### [TAUT-8.3] Python API

`taut.client.TautClient` is the embedding surface, and the CLI is a thin
argument-parsing layer over it — every CLI behavior above must be
reachable through one public client method with the same semantics (the
SimpleBroker/Weft layering rule: CLI and library share one operational
model). Public exports from `taut`: `TautClient`, `TautWatcher`,
`Message`, `Thread`, `Member`, the exception hierarchy rooted at
`TautError`, and `__version__`. The package ships typed (`py.typed`).

Core runtime dependencies: exactly `simplebroker` and `psutil`. The optional
`taut-pg` extension adds `simplebroker-pg` and its driver dependencies in the
same environment as Taut. Python ≥ 3.11. The CLI uses argparse, not a CLI
framework.

### [TAUT-8.4] Watcher

`TautWatcher` subclasses a taut-vendored copy of Weft's
`MultiQueueWatcher` (adapted, attributed; taut must not depend on weft).
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
  change (on SQLite, by extending the data-version callback — the
  vendored watcher's own callback only refreshes `last_ts`, and sidecar
  writes bump `PRAGMA data_version` because they share the file) and at
  a bounded interval. The interval is the portable guarantee: backends
  whose wake signals cover only queue writes ([TAUT-12.1]) still
  converge on membership changes within the interval.

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
- Fingerprints identify, they do not authenticate. The anchor match is a
  convenience that makes the common case (same process talking again)
  frictionless and makes impersonation *visible* (`whoami --explain`,
  fingerprints on record), not impossible.
- The boundary is the file system. Sharing with another uid means loosening
  file permissions yourself; taut will neither manage nor monitor that.
  When a server-backed broker arrives ([TAUT-12.1]), the boundary becomes
  database reachability — wider, but the same shape: storage access is
  membership.
- Threat model in one line: taut assumes every participant could already
  do worse than lie in chat, because they run inside your trust domain.

Anything stronger (signing, tamper evidence) is future work and must not
be implied by v0.1 docs or output.

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
- Locked/busy database: SimpleBroker's busy-timeout and retry discipline
  apply; surfaced errors name the database path.
- Anchor collision at (re)join: refused with the conflicting handle named
  ([TAUT-5.5]).
- Member whose anchor process died: existing membership and history are
  untouched; the *next* command from the restarted process follows
  [TAUT-5.4] (guest reads, auto-create + hint on writes). `who` shows
  `gone`.
- Two members in one ancestor chain: nearest anchor wins ([TAUT-5.3]);
  `whoami --explain` shows both candidates.
- Same `(pid, start_time)` on two hosts sharing a database: distinct
  anchors — `host_id` disambiguates, and it is an opaque machine
  identity rather than a hostname precisely because hostnames collide
  and drift ([TAUT-3.3], [TAUT-5.1]).
- Crossing ssh/container boundaries: fresh ancestor chains, identity via
  explicit `--as`/`TAUT_AS` propagation ([TAUT-5.2]).
- Foreign body in a watched queue: rendered per [TAUT-6.3]; the watcher
  advances past it.
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

Proof obligations for the v0.1 implementation, and the standing
anti-mocking posture:

- The broker is never mocked. All client, CLI, and watcher tests run
  against real `.taut.db` files in temp dirs.
- Identity tests spawn real child processes (shell → wrapper → taut) and
  assert anchor selection, nearest-wins, recognition across invocations,
  rejoin, and token acts-as from an unrelated process tree — not unit
  tests against fabricated chain dicts (capture parsing may be
  unit-tested per platform; *selection and matching* must be proven on
  real chains).
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
  foreign-body and future-version inputs.
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
- Release remains GitHub-only. Root releases use `vX.Y.Z`; extension releases
  use `taut_pg/vX.Y.Z`.

Binding obligations:

- no SQLite-specific assumptions outside target resolution and the
  documented data-version wake ([TAUT-8.4] interval backstop is the
  portable path)
- sidecar SQL uses qmark placeholders only (SimpleBroker translates them
  for Postgres)
- SimpleBroker hybrid timestamps and process ids are stored in `BIGINT`
  columns in documented DDL so Postgres does not truncate values that SQLite
  accepts as unbounded integers
- identity is host-aware from day one: hostname captured ([TAUT-5.1]),
  stored ([TAUT-3.3]), matched ([TAUT-5.3]), and presence degrades to
  `remote` off-host ([TAUT-5.6])

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

v0.1 obligation (binding now): every taut state read and write flows
through one state module, so the SQL implementation and a future Redis
mapping are swappable behind a single interface. The single-target
principle generalizes with it: whatever backend holds the queues holds
the state.

### [TAUT-12.3] Captive agents (`summon`)

Host an agent as a thread member: a supervised provider-CLI child
process whose line-oriented IO is bridged to a thread — messages in as
prompts, output back as messages — making "talk to the agent" literally
chat.

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

Needs its own spec before implementation (addressing/mention semantics,
lifecycle, provider lanes). v0.1 obligations: envelope forward tolerance
([TAUT-6.1]) and no assumption anywhere that members only speak via CLI
invocations.

### [TAUT-12.4] TUI

Per [TAUT-8.4]: a consumer of `TautClient` + `TautWatcher`, optional
extra, own spec.

## Related Plans

- `docs/plans/2026-06-12-taut-foundation-plan.md` — v0.1 foundation:
  package scaffolding, schema, identity, envelope, client, watcher, CLI.
- `docs/plans/2026-06-12-taut-0.1.1-hardening-plan.md` — post-0.1.0
  hardening slice: handle-quality fix, [TAUT-11] burndown, renderer
  conformance to the README, round-5 review, 0.1.1 tag.
- `docs/plans/2026-06-17-github-release-helper-plan.md` — GitHub-only
  release helper while the PyPI `taut` package-name request is pending.
- `docs/plans/2026-06-17-github-actions-release-workflows-plan.md` —
  GitHub Actions test and GitHub-only release publication workflows.
- `docs/plans/2026-06-17-taut-pg-extension-plan.md` — implemented
  [TAUT-12.1] plan: separate `taut-pg` extension project,
  Postgres shared/PG-only test split, `bin/pytest-pg`, and GitHub-only
  extension release flow.
- `docs/plans/2026-06-17-implementation-review-followups-plan.md` —
  post-review hardening for missing-plugin errors, bounded `log --limit`,
  project-config proof strength, and expanded shared backend conformance.
- `docs/plans/2026-06-18-simplebroker-latest-timestamp-plan.md` —
  planned issue #3 fix: use SimpleBroker's indexed latest pending timestamp
  API for `list` metadata instead of a full-history scan.
