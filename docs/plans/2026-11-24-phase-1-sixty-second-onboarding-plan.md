# Phase 1: 60-Second Onboarding, Cold-Join Context, Auto-Join Send, and Postgres `init().created` Plan

- **Date:** 2026-11-24
- **Status:** completed (see `docs/plans/README.md` status index)
- **Class:** 5 (normative specification additions across `docs/specs/02-taut-core.md` and `docs/specs/10-taut-tui.md`, new public CLI verb `onboard` and options `join --recent N` / `say --join`, new public `TautClient` methods and value objects, wheel-packaged `taut/agent-kernel.md` resource, and cross-backend `ensure_schema() -> bool` sidecar-installation detection). The hardening checklist (`docs/agent-context/runbooks/hardening-plans.md`) is applied because `onboard` mutates user repository files (`AGENTS.md`, `CLAUDE.md`, `.gitignore`, `.dockerignore`, `.mcp.json`) under operator-owned permission, containment, and non-creation invariants, and `ensure_schema()` governs concurrent initialization inside SQLite's sidecar writer transaction and under PostgreSQL's `taut:schema` advisory lock.
- **Plan type:** implementation with Strategy-A spec promotion (`docs/agent-context/runbooks/writing-plans.md` §4c)
- **Owner:** Taut engineering

## 1. Goal

Reduce first-run human and agent adoption friction without relaxing `[THEORY-2]`/`[PIO-6.2]` permission boundaries, `[TAUT-6.4]` terminal-policy safety, `[TAUT-6.5]` blank filtering, or `[TAUT-7.4]` unread bookmark semantics:

1. **Race-exact cross-backend `TautClient.init().created` (`[TAUT-8.2]`)**: Return `created=True` solely when `ensure_schema()` commits the `taut_meta.schema_version` insert inside SQLite's sidecar writer transaction (`sidecar(transaction=True)`) or under PostgreSQL's `taut:schema` transaction advisory lock (covering fresh SQLite files, pre-existing raw SimpleBroker SQLite files without Taut sidecar state, and fresh PostgreSQL schemas), and `created=False` when Taut's sidecar schema is already present (including for the loser of a concurrent initialization race on either backend), while retaining the fast-fail SQLite parent-directory writability preflight.
2. **Indexed `O(N)` cold-join context via `taut join THREAD --recent N` (`TautClient.join_channel`) & `docs/agent-kernel.md` update (`[TAUT-7.4]`, `[TAUT-8.1]`–`[TAUT-8.3]`)**: Keep `join`'s high-water unread bookmark at **now** (`[TAUT-7.4]`), while letting callers request `1..1000` chronological prior messages in `O(N)` via `Queue.peek_many(recent, with_timestamps=True, before_timestamp=notice.ts if notice is not None else None, order="newest")` reversed to ascending `ts` order — cursor-neutrally on both first join and repeat join (preserving any unread delta for a subsequent `taut read`). Package `taut/agent-kernel.md` inside `taut-chat` sdist/wheels in byte-for-byte sync with `docs/agent-kernel.md`.
3. **Single-resolution channel auto-join send via `taut say TARGET [TEXT|-] --join` (`TautClient.say(..., join=False)`) (`[TAUT-6.5]`, `[TAUT-8.1]`–`[TAUT-8.3]`, `[TUI-7.1]`)**: Validate `type(join) is bool` and filter blank text before any domain work (`BlankMessageError`), reject non-top-level-channel targets (`@route`, `dm.d_*`, `chan.<origin_ts>`) with `ThreadNameError` (CLI exit `1`), resolve/create the acting member **once** (preserving `last_created_member` and its one-time continuity token), ensure channel + membership via shared `_ensure_channel_membership()` (writing the creation/join notice to the queue when newly joined), and post `text` returning the sent `Message` (keeping `[TAUT-8.2]`'s single-`ts` JSON stdout output).
4. **One-command project bootstrap via `taut onboard` (`TautClient.onboard`, `TautClient.agent_kernel`) (`[TAUT-8.1]`–`[TAUT-8.3]`, `[TUI-7.1]`)**:
   - Actor-free project bootstrap accepting only `--db`, `--json`, and `--quiet` from root globals (rejecting `--as`, `--token`, and `--timestamps` in both pre-verb and post-verb positions).
   - Full preflight before any storage init or file write: resolves target storage path without opening it; rejects path or hard-link aliases (`_same_path_or_file`, including `os.path.samefile`) between SQLite target/sidecar files and any enabled onboarding file (even when `--no-init` is passed) AND between any enabled onboarding file and **every** managed onboarding filename (including disabled roles, so `.gitignore -> .mcp.json` is rejected even when `--mcp` is omitted; `CLAUDE.md` ↔ `AGENTS.md` deduplicates only when `Path.resolve()` is identical, while distinct hard-linked `CLAUDE.md` and `AGENTS.md` paths fail closed so `os.replace` cannot sever a hard link); and rejects symlinks escaping `root`, broken symlinks, directories, invalid UTF-8, unbalanced/duplicate `<!-- taut:onboard:start -->`/`<!-- taut:onboard:end -->` markers, malformed `.mcp.json`, and any existing differing `mcpServers.taut` entry.
   - Appends missing exact lines (`set(existing_text.splitlines())`, preserving significant leading/trailing spaces) from the five default SQLite/lock filenames (`.taut.db`, `.taut.db.lock`, `.taut.lock`, `.taut.db-wal`, `.taut.db-shm`) to `.gitignore` and `.dockerignore` in place via `os.open(..., os.O_WRONLY | os.O_APPEND)` (**without `O_CREAT`**, preserving inode, owner, group, mode, and ACLs, and making ignore-file creation mechanically impossible even if unlinked after preflight).
   - Creates absent `AGENTS.md` / `.mcp.json` via same-directory `0o666` (`umask`-honoring) exclusive staging (`[PIO-6.2]`), and updates existing `AGENTS.md`/`CLAUDE.md`/`.mcp.json` via same-directory crash-atomic staging + `copymode` + `os.replace` on the `root`-contained resolved target (preserving `CLAUDE.md -> AGENTS.md` symlinks).
   - `taut onboard --print-kernel` splits `TautClient.agent_kernel().removesuffix("\n").split("\n")` strictly on structural LF `"\n"` (never `str.splitlines()`, so C1 characters such as `U+0085` still reach `[TAUT-6.4]` escaping) and emits each line through `write_human_line` without requiring an initialized workspace.

## 2. Source Documents

- `docs/program-theory.md` — `[THEORY-1]`, `[THEORY-2]`, `[THEORY-4]`, `[THEORY-5.A1]`–`[THEORY-5.A6]`
- `docs/specs/product-section-registry.md` — two-way promise alignment between `README.md` and canonical specs
- `docs/specs/01-development-documentation-operating-model.md` — `[DOM-5]`, `[DOM-10.1]`, `[DOM-10.2.1]`, `[DOM-11]`, `[DOM-15]`
- `docs/specs/02-taut-core.md` — `[TAUT-3.3]`, `[TAUT-4.2]`, `[TAUT-4.3]`, `[TAUT-6.4]`, `[TAUT-6.5]`, `[TAUT-7.4]`, `[TAUT-8.1]`, `[TAUT-8.2]`, `[TAUT-8.3]`, `[TAUT-9]`
- `docs/specs/03-identity-addressing-notifications.md` — `[IAN-3.3]`, `[IAN-5.1]`, `[IAN-5.3]`
- `docs/specs/08-persistence-io.md` — `[PIO-6.2]` (`0o666 & ~umask` operator-owned file creation)
- `docs/specs/10-taut-tui.md` — `[TUI-2.1]`, `[TUI-7.1]`
- `docs/agent-kernel.md`, `README.md`, `extensions/taut_mcp/README.md`, `docs/implementation/02-repository-map.md`, `docs/implementation/04-taut-architecture.md`, `docs/implementation/12-taut-tui.md`
- `docs/agent-context/runbooks/writing-plans.md`, `hardening-plans.md`, `review-loops-and-agent-bootstrap.md`, `testing-patterns.md`, `adversarial-acceptance-probes.md`

## 3. Spec Baseline

- **Baseline commit:** `d42a549f998a3f88389392e8146ca62b07daf29b` (`Phase 0 bug fixes and hot-path performance remediation`)
- **Promotion strategy:** **Strategy A — In-file edit before code** (`docs/agent-context/runbooks/writing-plans.md` §4c). Slice 0 stages the initial `taut/agent-kernel.md` resource copy from `docs/agent-kernel.md`, applies every `Replacement` block below to `docs/specs/02-taut-core.md` and `docs/specs/10-taut-tui.md` (preserving `2026-11-10`'s promoted `Replacement` blocks verbatim), sets `Status: promoted` in `docs/plans/README.md`, and verifies both `bin/check-doc-paths` and `bin/check-cli-claims` exit `0` before Slice 1 begins.
- **Promotion baseline:** Slice 0 spec-promotion applied atop d42a549
- **Touched spec sections:**
  - `docs/specs/02-taut-core.md`: `[TAUT-6.5]`, `[TAUT-7.4]`, `[TAUT-8.1]`, `[TAUT-8.2]`, `[TAUT-8.3]`, `## Related Plans`
  - `docs/specs/10-taut-tui.md`: `[TUI-7.1]`, `## Related Plans`

## 4. Proposed Spec Delta

Every `Replacement` block below is exact post-promotion text for its backticked target file, verified mechanically by `bin/check-doc-paths` once Slice 0 promotes the spec delta.

### 4.1 `docs/specs/02-taut-core.md`

#### 4.1a `[TAUT-6.5]` — `say(..., join=...)` boolean type validation before blank filtering (`L910–920`)

Replacement (`docs/specs/02-taut-core.md`):
```markdown
`TautClient.say()` validates `type(join) is bool` (`TypeError("join must be a bool")`)
and then `TautClient.say()` and `TautClient.reply()` filter blank text before any
domain work, raising public `BlankMessageError`, a subclass of
`EmptyResultError`. The blank check precedes target parsing, `--join`
top-level-channel validation, incomplete-rename checks, identity/activity work,
queue/timestamp work, and all thread, membership, message, notification, and
cursor mutation. Blank filtering thus wins over later target, parent-message,
membership, and rename failures, and `say(..., join=True)` on blank text creates
no member, channel, membership, or join notice. Parsing, text acquisition,
storage/schema bootstrap, and client construction that occur before the method
call keep their existing priority. For human CLI output, terminal-policy
preflight occurs before command execution; an unavailable policy therefore
retains its existing diagnostic exit 1 and wins over blank filtering.
```

#### 4.1b `[TAUT-7.4]` — `join --recent N` / `join_channel(..., recent=N)` indexed cursor-neutral prior context (`L1026–1036`)

Replacement (`docs/specs/02-taut-core.md`):
```markdown
Joining starts you at **now**: sidecar membership is initialized with the
provisional timestamp taken immediately before the join (or creation) notice.
After that notice commits, the bounded interval probe catches the cursor up to
the notice only when no intervening chat row exists. Thus a new member normally
begins caught up, while a concurrent row remains unread; older history is a
deliberate rewind away via `log` or inline at join time via `join --recent N`
(`TautClient.join_channel(..., recent=N)`). `recent` (`0` default; `1..1000`
when requested) uses SimpleBroker's indexed `Queue.peek_many(recent,
with_timestamps=True, before_timestamp=..., order="newest")` query to return up
to `N` most recent surviving messages strictly prior to any notice written by
the current join (or up to `N` most recent surviving messages in the channel
when no notice is written) in ascending message-id order without moving any
cursor. A row committed between membership creation and the join notice may
appear in `recent` and still remain unread under the interval probe above, while
already-joined callers preserve their unread delta for `read`. One carve-out:
implicit sub-thread join *by reading it* ([TAUT-4.3]) initializes the cursor to
0, because reading the thread is exactly what was asked; implicit join by
replying starts at now like any join. `leave` notices have no cursor effect.
```

#### 4.1c `[TAUT-8.1]` — `onboard` verb, `join --recent N`, `say --join`, and actor-free `onboard` globals (`L1250–1257`, `L1311–1316`)

Replacement (`docs/specs/02-taut-core.md`):
```markdown
| `init` | Create the resolved SQLite `.taut.db` or initialize the configured backend target plus sidecar schema in the current directory. Idempotent with notice if present. | 0 created/exists, 1 error |
| `onboard [--channel CHANNEL] [--mcp] [--no-init] [--no-agents] [--no-ignore]` / `onboard --print-kernel` | Actor-free current-directory onboarding (`--db`, `--json`, `--quiet` root globals; `--as`, `--token`, and `-t/--timestamps` are usage errors in any position). Preflights channel syntax, root-directory containment, path and hard-link alias collisions (`os.path.samefile`) between enabled write targets and SQLite target/sidecar files (even under `--no-init`) or **any** managed onboarding filename including disabled roles (`CLAUDE.md` ↔ `AGENTS.md` deduplicates only when `Path.resolve()` is identical; distinct hard-linked `CLAUDE.md` and `AGENTS.md` paths fail closed), UTF-8 validity, balanced `<!-- taut:onboard:start -->` … `<!-- taut:onboard:end -->` markers, and `.mcp.json` shape before mutating storage or files. Initializes resolved storage unless `--no-init`; writes or updates the fenced section in existing `AGENTS.md`/`CLAUDE.md` files (creates `AGENTS.md` when neither exists; skipped with `--no-agents`); appends any missing exact lines (`splitlines()`, without whitespace stripping) among `.taut.db`, `.taut.db.lock`, `.taut.lock`, `.taut.db-wal`, and `.taut.db-shm` in place (`O_WRONLY \| O_APPEND`, never `O_CREAT`) to `.gitignore` and `.dockerignore` **strictly only when each ignore file already exists** (never creating an absent ignore file, never rewriting negation rules, and leaving custom `--db` paths operator-managed; skipped with `--no-ignore`); and with `--mcp` adds `"taut": {"command": "taut", "args": ["mcp"]}` to `.mcp.json`'s `mcpServers` object while failing closed if a differing `mcpServers.taut` entry already exists. `--print-kernel` rejects `--db`, `--json`, `-q`, and all other command-local flags, touches no storage or files, and splits `taut/agent-kernel.md` strictly on structural LF `"\n"` through [TAUT-6.4]'s human-output escape policy. | 0 completed or printed; 1 usage, collision/alias, containment, invalid channel/JSON/UTF-8/marker, existing differing `mcpServers.taut`, terminal-policy, or storage/I/O error |
| `join THREAD [--as NAME_OR_ALIAS] [--persona TEXT] [--new] [--recent N]` | Register identity if needed (`--new` forces a fresh member), create a channel if needed, add membership (cursor at now, [TAUT-7.4]), write notice. When the acting member already belongs to THREAD, `join` succeeds, applies `--persona` if given, and writes no notice, no membership row, and no cursor change; it prints the thread header (or the requested `--recent` messages, or the thread header when `--recent` finds an empty channel) so callers see a consistent shape. `--persona` sets/updates the member's persona. `--recent N` (`1..1000`) includes up to `N` most recent prior messages chronologically without moving any cursor. | 0; 1 error (including `N < 1` or `N > 1000`) |
| `leave THREAD` | Remove membership, write notice. | 0; 1 error; 2 not a member |
| `channel show CHANNEL` | Return current metadata for one registered top-level channel. Resolves no actor and changes no activity, membership, queue, message, notification, or cursor state. | 0 showed; 1 invalid name, corrupt metadata, or error; 2 no such top-level channel |
| `channel topic CHANNEL TEXT` / `channel topic CHANNEL --clear` | Set one exact one-line topic or explicitly clear it. Requires an existing acting member and current channel membership. A same-value set and absent clear are successful no-ops. No stdin form. | 0 changed or no-op; 1 usage, invalid topic, corruption, or error; 2 no such channel / unrecognized member / not a member |
| `set name NAME` | Change the acting member's current display name and route key. Does not rewrite old messages. | 0; 1 error/name collision; 2 unrecognized |
| `say TARGET [TEXT\|-] [--join]` | Post a message (stdin with `-` or when piped and TEXT omitted). Blank text is filtered before routing under [TAUT-6.5]. `TARGET` retains every [IAN-5.1] channel/sub-thread form, including quoted `#channel`, and also accepts `@name-or-alias` or an exact `dm.d_<26-lowercase-base32-chars>` stable handle. Without `--join`, channel and sub-thread targets require existing membership. With `--join`, `TARGET` must be a top-level channel (sub-threads and DM targets exit 1); Taut resolves or creates the acting member once and joins/creates the channel (writing the standard creation/join notice to the queue when not already a member) before posting; if the later message write fails, any committed member/channel/join state remains durable. `@route` may create the deterministic conversation; `dm.d_*` requires an existing fully valid actor-accessible conversation and never creates or heals one. Prints message id with `-t` only when a message is written. | 0 wrote; 1 malformed syntax on a nonblank attempt, `--join` on non-channel target, or error; 2 blank filtered / not a member / no such member / inaccessible or invalid stable DM |
```

Replacement (`docs/specs/02-taut-core.md`):
```markdown
The `system` noun requires `dump`, `load`, or `doctor`, is core-owned, and
accepts only `--db`, `--json`, and `--quiet` from the root-global vocabulary;
`onboard` is likewise actor-free and accepts only `--db`, `--json`, and
`--quiet` from the root-global vocabulary (`--print-kernel` accepts no root
globals other than `--help`).
Doctor has no command-local flags and follows spec 09. It does not add a
`status` operation. An uninitialized dump or doctor source retains
[TAUT-3.2]'s exit 1 and `taut init` hint.
```

#### 4.1d `[TAUT-8.2]` — `join --recent`, `say --join`, race-exact `init.created`, and `onboard` JSON shape (`L1344–1349`, `L1368`, `L1392–1395`)

Replacement (`docs/specs/02-taut-core.md`):
```markdown
  - writing verbs (`say`, `reply`) echo the message object they wrote, with the
    same fields as read messages (including `say --join`, which records any
    channel creation/join notice in the queue without echoing a second `ts`
    object to stdout). A blank attempt filtered under [TAUT-6.5]
    writes no message, emits no human or JSON record, and exits 2. For a
    successful write, the robust id-capture idiom remains
    `taut say t "x" --json | jq -r 'select(has("ts")).ts'`, because a first-ever
    use may emit a leading creation line with no `ts`;
```

Replacement (`docs/specs/02-taut-core.md`):
```markdown
  - `join` and `leave` echo their notice's message object (`join` when already a
    member emits no notice object; `join --recent N` emits up to `N`
    chronological prior message objects followed by the join notice object when
    a notice was written);
```

Replacement (`docs/specs/02-taut-core.md`):
```markdown
  - `init`: `db` (backend display target; a filesystem path for SQLite),
    `created` (bool: `true` iff this call committed the `taut_meta`
    `schema_version` insert inside SQLite's sidecar writer transaction or under
    PostgreSQL's `taut:schema` advisory lock, and `false` when Taut's sidecar
    schema was already present on SQLite or PostgreSQL, including for the loser
    of a concurrent initialization race).
  - `onboard`: `root` (resolved directory path string), `channel` (canonical
    channel name), `init` (`{"db": ..., "created": ...}` or `null` when
    `--no-init`), and `files` (ordered array of `{"path": str, "action":
    "created" | "updated" | "unchanged" | "skipped_absent" |
    "skipped_disabled"}` covering the target agent instruction file(s),
    `.gitignore`, `.dockerignore`, and `.mcp.json`). `onboard --print-kernel`
    splits packaged `taut/agent-kernel.md` strictly on structural LF `"\n"` and
    writes each line through [TAUT-6.4]'s human-output escape policy, rejecting
    `--db`, `--json`, and `-q`.
```

#### 4.1e `[TAUT-8.3]` — Public exports and signatures for `JoinResult`, `OnboardFileStep`, `OnboardReport`, `join_channel`, `say(..., join=...)`, `onboard`, and `agent_kernel` (`L1425–1434`, `L1481–1492`)

Replacement (`docs/specs/02-taut-core.md`):
```markdown
model). Public exports from `taut`: `TautClient`, `TautWatcher`, `Message`,
`MessageDeletion`, `MessageReaction`, `JoinResult`, `OnboardFileStep`,
`OnboardReport`, `SearchHit`, `Channel`, `Thread`, `Member`,
`PersistenceComponentReport`, `DumpReport`, `LoadReport`, `DoctorCheck`,
`DoctorReport`, `WatcherRejected`, the
exception hierarchy rooted at `TautError` including `BlankMessageError`,
`MessageIdResolutionError`, and its not-found subtype
`MessageIdNotFoundError`,
`escape_terminal_text`, and `__version__`. The package ships typed
(`py.typed`) and includes `taut/defaults.toml` and `taut/agent-kernel.md` in
both source and wheel distributions.
```

Replacement (`docs/specs/02-taut-core.md`):
```markdown
`JoinResult` is a frozen, slotted public value object with exact fields
`thread: str`, `notice: Message | None`, and `recent: tuple[Message, ...]`.
`TautClient.join_channel(thread: str, *, persona: str | None = None, new: bool =
False, recent: int = 0) -> JoinResult` validates `recent` (`bool`/non-`int`
raises `TypeError("recent must be an integer")`; `< 0` or `> 1000` raises
`ValueError("recent must be between 0 and 1000")` on the Python method, while
CLI `--recent N` requires `1..1000`) before identity, thread, membership, or
queue mutation. If the post-join `peek_many` read raises after membership/notice
commit, the committed join state remains durable. `TautClient.join(thread: str,
*, persona: str | None = None, new: bool = False) -> Message | None` delegates
to `join_channel(..., recent=0).notice`.

`OnboardFileStep` (`path: str`, `action: Literal["created", "updated",
"unchanged", "skipped_absent", "skipped_disabled"]`) and `OnboardReport`
(`root: str`, `channel: str`, `init: InitResult | None`,
`files: tuple[OnboardFileStep, ...]`) are frozen, slotted public values. The
actor-free class methods are `TautClient.onboard(*, root: str | Path | None =
None, db_path: str | Path | None = None, channel: str = "general", mcp: bool =
False, init_storage: bool = True, update_agents: bool = True, update_ignore:
bool = True) -> OnboardReport` and `TautClient.agent_kernel() -> str` (plus
optional `directory: str | Path | None = None` on `TautClient.init`). `onboard`
enforces strict `root` containment on every managed path and symlink target,
rejects path and hard-link alias collisions (`os.path.samefile`) between any
enabled write target and resolved SQLite target/sidecar files (including when
`init_storage=False`) or **any** managed onboarding filename including disabled
roles (`CLAUDE.md` ↔ `AGENTS.md` deduplicates only when `Path.resolve()` is
identical; distinct hard-linked `CLAUDE.md` and `AGENTS.md` paths fail closed),
appends missing exact default ignore lines (`splitlines()`) in place via
`O_WRONLY | O_APPEND` without `O_CREAT` (never creating `.gitignore` or
`.dockerignore` and preserving existing inode, owner, mode, and ACLs), creates
absent `AGENTS.md`/`.mcp.json` via same-directory `0o666` exclusive staging
([PIO-6.2]), and updates existing `AGENTS.md`/`CLAUDE.md`/`.mcp.json` via
same-directory atomic replacement on the resolved target (`copymode` preserves
mode bits; the replacement inode is owned by the invoking OS user without
copying extended ACLs, matching [PIO-6.2]). Storage initialization, atomic
replacements, and complete ignore-line appends are idempotent on retry; an
interrupted short `O_APPEND` write can leave a partial trailing line requiring
manual trim before retry.

`TautClient.say(target: str, text: str, *, join: bool = False) -> Message`
retains every [IAN-5.1] channel/sub-thread form and also accepts
`@name-or-alias` or an exact `dm.d_<26-lowercase-base32-chars>` stable handle.
When `join=True`, a nonblank call requires a top-level channel target (raising
`ThreadNameError("--join is only supported for top-level channels")` on
sub-threads and DM selectors), resolves or creates the acting member once
(preserving `last_created_member`), ensures the channel and membership exist
(writing the creation/join notice to the queue when newly joined), and then
writes and returns the sent `Message`; if the message write fails, any committed
member/channel/join state remains durable. `@route` may create the deterministic
conversation when `join=False`. A stable handle requires an existing fully valid
actor-accessible conversation under [IAN-5.3] and never creates or heals one.
Malformed syntax on a nonblank attempt is a validation error. A well-formed
inaccessible or invalid stable handle raises the ordinary content-free
not-found class. A successful stable send returns the stable DM thread and
preserves the ordinary integer Python message id; JSON adapters emit that id as
[TAUT-3.5]'s canonical string. Blank filtering and human output remain
unchanged.
```

#### 4.1f `docs/specs/02-taut-core.md` `## Related Plans` (`L3156–3161`, placed below `2026-09-28` so `2026-11-10`'s promoted `Replacement` block stays intact)

Replacement (`docs/specs/02-taut-core.md`):
```markdown
- `docs/plans/2026-09-28-simplification-and-hot-path-plan.md` — binds one
  stable actor per CLI read and uses broker timestamp metadata for count-free
  thread listings; also revises watch failure and debug contracts.

- `docs/plans/2026-11-24-phase-1-sixty-second-onboarding-plan.md` — adds
  actor-free `onboard` (with `root`-contained preflight, `O_APPEND`
  existing-only `.gitignore`/`.dockerignore` updates, non-overwriting
  `.mcp.json` registration, and wheel-packaged `taut/agent-kernel.md`),
  indexed cursor-neutral `join --recent N` (`TautClient.join_channel`),
  single-resolution top-level channel `say --join`, and sidecar-backed
  `TautClient.init().created` across SQLite and PostgreSQL.

- `docs/plans/2026-09-24-tui-participation-loop-plan.md` — publishes the
```

### 4.2 `docs/specs/10-taut-tui.md`

#### 4.2a `[TUI-7.1]` — TUI disposition for `onboard`, `join --recent`, and `say --join` (`L548–551`)

Replacement (`docs/specs/10-taut-tui.md`):
```markdown
The CLI's omitted-text and `-` stdin forms for `say` and `reply`, project-file
`onboard`, and `join --recent` are syntax-recognized but CLI-only in the TUI.
The TUI has no process-stdin command source and already opens full channel
history natively; explicit `say ... --join` executes through the native send
binding and refreshes navigation.
```

#### 4.2b `docs/specs/10-taut-tui.md` `## Related Plans` (`L1108–1113`)

Replacement (`docs/specs/10-taut-tui.md`):
```markdown
## Related Plans

- `docs/plans/2026-11-24-phase-1-sixty-second-onboarding-plan.md` — records the
  [TUI-7.1] command-mirror dispositions for `onboard` and `join --recent`
  (explicit CLI-only) and `say --join` (native send + navigation refresh).

- `docs/plans/2026-09-24-tui-text-selection-and-clipboard-plan.md` — enables
  framework text selection in the transcript, adds `y` and timed auto-copy
  through OSC 52, and pins copied text to the policy-filtered display form.
```

## 5. Context and Key Files

| File | Role in Phase 1 |
|---|---|
| `taut/state/_sql.py`, `taut/state/__init__.py` | `ensure_schema() -> bool` returns `True` iff this call inserted `taut_meta.schema_version` inside SQLite's sidecar writer transaction or under PostgreSQL's `taut:schema` advisory lock |
| `taut/client/__init__.py`, `taut/client/_models.py`, `taut/__init__.py` | `TautClient.init(*, db_path=None, directory=None)` with `created = schema_created`; `JoinResult(thread, notice, recent)`, `OnboardFileStep`, `OnboardReport`; `TautClient.onboard()`, `TautClient.agent_kernel()`; lazy package exports |
| `taut/_onboard.py` *(new)* | Storage-target & cross-role path/hard-link alias preflight (`_same_path_or_file`), `root`-containment validation, `O_WRONLY \| O_APPEND` existing-only ignore updater (`splitlines()` without `.strip()`), `0o666` staging + atomic `AGENTS.md`/`CLAUDE.md`/`.mcp.json` publisher, packaged `agent-kernel.md` reader |
| `taut/client/_threads.py`, `taut/client/_messaging.py` | Shared `_ensure_channel_membership(thread, member, persona=...)`; `TautClient.join_channel()` using `Queue.peek_many(..., order="newest")`; `TautClient.say(..., join=False)` with single `_resolve_member(create=True)` |
| `taut/commands/_builtins.py`, `taut/commands/syntax.py`, `taut/commands/_rendering.py` | `onboard` built-in spec (`_SYSTEM_GLOBALS`), syntax nodes/options (`onboard`, `join --recent`, `say --join`), `emit_onboard()` |
| `taut/commands/onboard.py` *(new)*, `taut/commands/join.py`, `taut/commands/say.py` | CLI adapters (`OnboardCommand` rejects `context.as_name`, `context.continuity_token`, `context.timestamps`, and on `--print-kernel` rejects `context.db_path`, `context.json`, `context.quiet`) |
| `docs/agent-kernel.md`, `taut/agent-kernel.md` *(new)*, `pyproject.toml` | Cold-join `--recent 20` & `say --join` recipes; wheel/sdist inclusion |
| `extensions/taut_tui/taut_tui/command_bindings.py`, `domain.py`, `app.py` | `_cli_only(("onboard",))`, pre-action `join --recent` CLI-only diagnostic, native `say --join` + navigation refresh |
| `README.md`, `docs/implementation/02-repository-map.md`, `04-taut-architecture.md`, `12-taut-tui.md` | Two-way promise alignment (`product-section-registry.md`, including `taut-mcp` optional installation and per-call `workspace`/`token` note) and architecture docs |

## 6. Invariants, Hidden Couplings, and Constraints

1. **Filesystem containment, path/hard-link alias preflight, and existing-only `O_APPEND` ignore updates (`F1`, `F2`)**:
   - Every candidate path (`AGENTS.md`, `CLAUDE.md`, `.gitignore`, `.dockerignore`, `.mcp.json`) is checked before any mutation: directories, broken symlinks, and symlinks whose `Path.resolve()` falls outside `resolved_root` (`not resolved.is_relative_to(resolved_root)`) fail closed with `TautError` (CLI exit `1`).
   - Alias checking uses `_same_path_or_file(left, right)` (`left.resolve(strict=False) == right.resolve(strict=False)` or `left.exists() and right.exists() and os.path.samefile(left, right)`, matching `taut/persistence/_operations.py:84`):
     - Whenever any file step is enabled (`update_agents or update_ignore or mcp`), even when `init_storage=False` (`--no-init`), preflight resolves the target storage without opening a database and rejects any alias between the SQLite database/sidecars (`<db>`, `<db>.lock`, `<db>-wal`, `<db>-shm`, `resolved_root / ".taut.lock"`) and any enabled onboarding file.
     - Every enabled onboarding write target is also compared against **every** managed onboarding filename (`AGENTS.md`, `CLAUDE.md`, `.gitignore`, `.dockerignore`, `.mcp.json`), **including disabled roles** (so `.gitignore -> .mcp.json` is rejected even when `--mcp` is omitted). `CLAUDE.md` and `AGENTS.md` deduplicate to one write **only** when `CLAUDE.md.resolve() == AGENTS.md.resolve()` (symlink alias); if both exist at distinct resolved paths with `os.path.samefile(claude_md, agents_md)` (hard-linked regular files), preflight fails closed with `TautError` rather than letting `os.replace` sever the hard link.
   - `.gitignore` and `.dockerignore` use an exact literal-line policy: check `set(existing_text.splitlines())` (**without `.strip()`**, preserving significant leading/trailing spaces in Git/Docker ignore syntax) against the 5 default filenames (`.taut.db`, `.taut.db.lock`, `.taut.lock`, `.taut.db-wal`, `.taut.db-shm`) and append missing lines via `os.open(resolved_path, os.O_WRONLY | os.O_APPEND)` (**without `O_CREAT`**). Absent files (`not os.path.lexists(path)` or `FileNotFoundError` on `os.open`) return `action="skipped_absent"` and are never created; operator negation lines and `.taut.toml` are never touched; custom `--db` paths remain operator-managed.
   - `.mcp.json` with `--mcp`: if `mcpServers.taut` is absent, insert `{"command": "taut", "args": ["mcp"]}`; if already equal to `{"command": "taut", "args": ["mcp"]}`, report `"unchanged"`; if `mcpServers.taut` already exists with any different value, fail closed in preflight with `TautError("cannot update .mcp.json: mcpServers.taut already exists with different configuration")` rather than overwriting operator config.
   - Absent `AGENTS.md` / `.mcp.json` creation uses `os.open(staged, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o666)` (`[PIO-6.2]`) + atomic publication without overwriting a racing destination; updates to existing `AGENTS.md`/`CLAUDE.md`/`.mcp.json` stage in `resolved_target.parent` + `shutil.copymode(resolved_target, staged)` + `os.replace(staged, resolved_target)`.
2. **Single-actor `say --join`, blank-first, and single-`ts` JSON stdout (`F4`, `[TAUT-6.5]`, `[TAUT-8.2]`)**:
   - `say(..., join=True)` validates `type(join) is bool`, runs `is_blank_message_text(text)` before any target/member/channel work, validates top-level channel target (`allow_subthread=False`, rejecting `@route`, `dm.d_*`, and sub-threads with `ThreadNameError`), calls `_resolve_member(create=True)` **once**, passes `member` into `_ensure_channel_membership()` and `_say_chat_thread()`, and preserves `self.last_created_member` so first-contact CLI `--json` emits `[created_member_without_ts, sent_message_with_ts]`.
3. **Actor-free `onboard` & `[TAUT-6.4]` terminal-policy continuity (`F5`)**:
   - `OnboardCommand.run()` explicitly rejects `context.as_name`, `context.continuity_token`, and `context.timestamps` (`CommandError`, exit `1`), matching `SystemCommand.run()`, and on `--print-kernel` additionally rejects `context.db_path`, `context.json`, and `context.quiet`.
   - `onboard` keeps `raw_stdio_transport=False`, preserving `[TAUT-6.4]` human-output terminal-policy preflight with zero new exemptions.
4. **Gate & suppression couplings (`F6`, `[DOM-10.2.1]`)**:
   - `2026-11-10`'s promoted `Replacement` blocks in `docs/specs/02-taut-core.md` remain verbatim; `taut/agent-kernel.md` is staged in Slice 0 so `bin/check-doc-paths` and `bin/check-cli-claims` exit `0` at Slice 0 completion.
   - Zero new `# noqa` directives (`bin/ruff_suppression_index.py --check`).
   - `skills/call-agent/SKILL.md` remains untouched.

## 7. Rollout / Partial-Failure / Rollback Notes

- Schema version (`SCHEMA_VERSION`) is unchanged; no database migration occurs.
- **Retry semantics**: `onboard` preflights all inputs and existing files before mutating storage or disk. Storage initialization, atomic `AGENTS.md`/`CLAUDE.md`/`.mcp.json` replacements, and complete ignore-line appends are idempotent (`unchanged` on retry). Because `.gitignore`/`.dockerignore` updates use in-place `O_APPEND` rather than inode replacement, an interrupted OS short-write can leave a partial trailing line that an operator trims before retrying.
- **Operator rollback**: rollback requires a pre-run existence and content snapshot of candidate files plus `.taut.db` taken before `taut onboard` runs, compared against post-failure inspection: restore modified pre-existing files from that pre-run content snapshot (never blind `git checkout -- <file>`); remove `AGENTS.md`, `.mcp.json`, or `.taut.db` only when the pre-run snapshot proves that file did not exist beforehand (`init.created` indicates fresh Taut sidecar installation, which can also occur on a pre-existing raw SimpleBroker SQLite file); and if no pre-run snapshot was captured, leave affected files in place and inspect manually rather than guessing whether a file or edit pre-existed.

## 8. Dependency-Ordered Slices and Tasks

### Slice 0: Spec Promotion (`Strategy A`) & Initial Packaged Kernel Resource

1. Copy `docs/agent-kernel.md` identically to `taut/agent-kernel.md` so path claims in `docs/specs/02-taut-core.md` resolve immediately.
2. Apply all `Replacement` blocks in §4.1 (`docs/specs/02-taut-core.md`) and §4.2 (`docs/specs/10-taut-tui.md`).
3. Update `Status:` to `promoted` and `Promotion baseline:` to `Slice 0 spec-promotion applied atop d42a549` in this plan and `docs/plans/README.md`.
4. Verify `uv run bin/check-plan-status-index && uv run bin/check-doc-paths && uv run bin/check-cli-claims` all exit `0`.

### Slice 1: Cross-Backend `TautClient.init().created` (`ensure_schema() -> bool`)

1. **Write RED tests**:
   - In `tests/test_client.py`:
     - Fresh SQLite `TautClient.init(db_path=db)` returns `created=True`, second call returns `created=False`.
     - Pre-existing raw SimpleBroker SQLite database (`Queue("raw", db_path=str(db)).write("hello")` before `TautClient.init(db_path=db)`) returns `created=True` on first `TautClient.init` and `created=False` on second `TautClient.init`.
     - `TautClient.init(directory=sub_tmp)` without `chdir` initializes `sub_tmp / ".taut.db"` with `created=True` and second call `created=False`.
   - In `extensions/taut_pg/tests/test_pg_sidecar.py` and `extensions/taut_pg/tests/test_pg_integration.py`:
     - Update first-call `TautClient.init()` / `taut init --json` assertions from `False` to `True`, add a second `init` call asserting `created is False`, and add a concurrent `TautClient.init()` race test against an empty Postgres schema asserting `[r.created for r in results].count(True) == 1` and `[r.created for r in results].count(False) == N - 1`.
2. **Implement Slice 1**:
   - Update `ensure_schema()` and `SqlSidecarTautState.ensure_schema()` (`taut/state/_sql.py`, `taut/state/__init__.py`) to return `bool` (`True` iff `(SCHEMA_VERSION_KEY, str(SCHEMA_VERSION))` was inserted inside SQLite's writer transaction or under PostgreSQL's `taut:schema` advisory lock).
   - Update `_ensure_initialized_schema()` and `TautClient.init(*, db_path: str | Path | None = None, directory: str | Path | None = None)` in `taut/client/__init__.py` so `created = schema_created` on both SQLite and PostgreSQL (retaining `not db_file.exists()` solely for the SQLite parent-directory writability preflight).
3. **Verify Slice 1**:
   - `uv run --no-sync --extra dev pytest tests/test_client.py tests/test_project_config.py tests/test_command_registry.py -k "init"`
   - `uv run ./bin/pytest-pg extensions/taut_pg/tests/test_pg_sidecar.py extensions/taut_pg/tests/test_pg_integration.py -k "init"`

### Slice 2: `join --recent N` (`TautClient.join_channel`), `say --join`, TUI Bindings & `agent-kernel.md`

1. **Write RED tests**:
   - In `tests/test_public_api.py`: add `JoinResult` (`thread`, `notice`, `recent`) to `EXPECTED_PUBLIC_EXPORTS` and test frozen/slotted shape, `__module__ == "taut.client"`, and `join_channel` / `say(..., join=False)` keyword-only parameter defaults.
   - In `tests/test_client.py` and `tests/test_cli.py`:
     - `join_channel` / `taut join THREAD --recent N`:
       - Validation-first: `recent=True`, `recent="5"`, `recent=-1`, `recent=1001` fail before creating member/channel (`TypeError`/`ValueError`); CLI `--recent 0`, `--recent -1`, `--recent 1001`, `--recent nope` exit `1` without creating member or channel.
       - Indexed top-`N` & post-commit durability proof: spy `Queue.peek_many` on a 50-message channel with `join_channel("general", recent=2)` and assert `[call for call in peek_calls if call.get("order") == "newest"]` has length `1` with `limit=2, order="newest", with_timestamps=True, before_timestamp=result.notice.ts` (using `.get("order")` because `_advance_sender_if_no_intervening`'s `peek_many(1, ...)` interval probe omits `order`, and never calling `peek_generator`), returning `(M49, M50)` in ascending order plus `notice`, with cursor caught up so `read()` raises `EmptyResultError`; also fault `peek_many` specifically when `kwargs.get("order") == "newest"` and verify that the committed membership and join notice remain durable in storage.
       - Membership-to-notice interleaving proof (extending `test_join_notice_does_not_skip_message_published_after_membership`): an intervening message written between `add_membership` and the join notice appears in `result.recent` AND remains unread in a subsequent `bob.read("general")`!
       - Repeat join when already a member with 3 unread messages and `--recent 2`: returns `notice=None`, `recent=(last_2_messages)` **without moving the stored cursor**, so a subsequent `client.read("general")` still returns all 3 unread messages; repeat join on an empty channel with `--recent 5` prints the thread heading in human mode and exits `0` (`--json` prints nothing and exits `0`).
     - `say(..., join=True)` / `taut say TARGET [TEXT|-] --join`:
       - `say("ops", "hello", join="yes")` raises `TypeError("join must be a bool")`.
       - Blank `taut say newchan "   " --join` exits `2` silently without creating a member, `newchan`, or any notice.
       - Non-channel targets (`say("@bob", "hi", join=True)`, `say("dm.d_...", "hi", join=True)`, `say("general.1837025672140161024", "hi", join=True)`) raise `ThreadNameError` (CLI exit `1`) before creating a member or writing any message.
       - Fresh actor `taut --db ... --as freshbot say '#ops' "deploy green" --join --json`: creates `freshbot` + `#ops`, writes `"freshbot created #ops"` notice to queue, writes `"deploy green"` message, and emits **2 NDJSON lines**: line 0 is the created member with `"name": "freshbot"` and one-time `"token"` (no `"ts"`), and line 1 is `"deploy green"` with `"ts"` (`select(has("ts")).ts` yields 1 line!). Repeat `taut --db ... --as freshbot say ops "second" --join --json` writes no duplicate join notice and emits 1 NDJSON line.
   - In `extensions/taut_tui/tests/test_tui_action_handlers.py`:
     - Verify `:join newchan --recent 5` reports `--recent is CLI-only in the TUI.` **before** joining `newchan` (`newchan` is not created/joined!), and `:say newchan "from tui" --join` joins `newchan`, posts `"from tui"`, and refreshes navigation.
2. **Implement Slice 2**:
   - Add `JoinResult` to `taut/client/_models.py`, `taut/client/__init__.py`, and `taut/__init__.py`.
   - Extract `_ensure_channel_membership()` in `taut/client/_threads.py`; implement `TautClient.join_channel()` using `Queue.peek_many(recent, with_timestamps=True, before_timestamp=..., order="newest")` reversed to ascending order, and delegate `TautClient.join()` to `join_channel(..., recent=0).notice`.
   - Implement `join: bool = False` in `TautClient.say()` (`taut/client/_messaging.py`) resolving `member` once via `_resolve_member(create=True)`.
   - Update `taut/commands/syntax.py`, `taut/commands/join.py`, `taut/commands/say.py`, `extensions/taut_tui/taut_tui/domain.py`, and `extensions/taut_tui/taut_tui/app.py`.
   - Update `docs/agent-kernel.md` and sync `taut/agent-kernel.md` identically, add `/taut/agent-kernel.md` to `pyproject.toml` `[tool.hatch.build]`, and add the byte-for-byte sync check in `tests/test_docs_references.py`.
3. **Verify Slice 2**:
   - `uv run --no-sync --extra dev pytest tests/test_client.py tests/test_cli.py tests/test_command_syntax.py tests/test_public_api.py tests/test_docs_references.py`
   - `uv run --project extensions/taut_tui --extra dev --locked pytest extensions/taut_tui/tests/test_tui_command_bindings.py extensions/taut_tui/tests/test_tui_action_handlers.py -n 2 --dist loadfile`

### Slice 3: `taut onboard` (`TautClient.onboard` & `TautClient.agent_kernel`), Packaging & Docs

1. **Write RED tests** in `tests/test_onboard.py` *(new)*, `tests/test_public_api.py`, `tests/test_lazy_imports.py`, and `extensions/taut_tui/tests/`:
   - In `tests/test_public_api.py`: add `OnboardFileStep` and `OnboardReport` to `EXPECTED_PUBLIC_EXPORTS` and assert frozen/slotted shapes, `__module__ == "taut.client"`, and `TautClient.onboard` / `TautClient.agent_kernel` signatures.
   - **Ignore-file non-creation & `O_APPEND` inode-preservation tests**:
     - Empty directory (no `.gitignore`, no `.dockerignore`): `taut onboard` creates `.taut.db` and `AGENTS.md`, MUST NOT create `.gitignore` or `.dockerignore`, and `--json` reports `skipped_absent` for both.
     - Existing `.gitignore` (`node_modules/\n .taut.db\n!.taut.db\n` without trailing newline, custom mode `0o640` — note leading-space `' .taut.db'` does NOT satisfy bare `'.taut.db'`) and `.dockerignore` (`dist/\n.taut.db\n.taut.lock\n`): first `taut onboard` appends missing exact lines (`splitlines()` without `.strip()`, so bare `.taut.db` is still appended despite `' .taut.db'`) via `O_APPEND` **preserving exact `st_ino` and mode `0o640`**, leaves negation line `!.taut.db` untouched, never adds `.taut.toml`, and second `taut onboard` reports `unchanged` with byte-identical files.
     - Unlink-after-preflight race test: monkeypatch preflight/apply boundary to unlink `.gitignore` right before `_apply_planned_ignore` runs and verify `FileNotFoundError` maps cleanly to `skipped_absent` without recreating `.gitignore`!
   - **Containment, path/hard-link alias & fail-closed preflight tests**:
     - `taut onboard --db AGENTS.md`, `taut onboard --db .gitignore`, `taut onboard --db .mcp.json --mcp`, hard-linked `.gitignore` ↔ pre-existing `chat.db` with `taut onboard --db chat.db --no-init`, in-`root` symlink `.gitignore -> .mcp.json` **both with and without `--mcp`** (disabled-role alias protection!), hard-linked `AGENTS.md` ↔ `CLAUDE.md` (distinct paths sharing an inode), hard-linked `.gitignore` ↔ `AGENTS.md`, symlink `AGENTS.md -> ../outside.md` escaping `root`, broken symlink `.gitignore`, directory `.dockerignore`, invalid UTF-8 `AGENTS.md`, unbalanced `<!-- taut:onboard:start -->`, malformed `.mcp.json`, non-object `mcpServers`, and existing differing `mcpServers.taut` (`{"command": "custom"}`) ALL exit `1` **before** creating `.taut.db` or modifying any file!
   - **`AGENTS.md` / `CLAUDE.md` selection, symlink preservation & `--channel`**:
     - Neither exists -> creates `AGENTS.md` (`0o666 & ~umask`, not `0o600`).
     - Only `CLAUDE.md` exists -> updates `CLAUDE.md` (`updated`), does NOT create `AGENTS.md`.
     - `AGENTS.md` exists (`0o640`) and `CLAUDE.md` is an in-`root` symlink to `AGENTS.md` -> updates `AGENTS.md` once, keeps `CLAUDE.md.is_symlink()` `True`, and preserves mode `0o640`.
     - Re-running with `--channel dev` updates the `<!-- taut:onboard:start -->` … `<!-- taut:onboard:end -->` block in place; re-running with `--channel dev` again reports `unchanged`.
   - **Actor-free root-global rejection & `--print-kernel` terminal-policy tests**:
     - `taut --as van onboard`, `taut onboard --as van`, `taut --token tok onboard`, `taut -t onboard` all exit `1`!
     - `taut onboard --print-kernel` splits strictly on structural LF `"\n"` (`removesuffix("\n").split("\n")`): prints exact `docs/agent-kernel.md` content under default policy in an uninitialized directory without creating `.taut.db` or `AGENTS.md`; applies a valid configured `.taut.toml` `[terminal_text]` `escape_patterns = ["Session-start"]` matcher via `write_human_line` while preserving structural `\n` line breaks (and escapes a C1 `U+0085` byte in a monkeypatched kernel payload to `\x85` rather than splitting it into a raw newline!); fails closed with exit `1` on a malformed `.taut.toml` (`[TAUT-6.4]`); and rejects `--db`, `--json`, `-q`, and `--mcp` with exit `1`.
   - **Installed wheel end-to-end onboarding smoke test (`test_lazy_imports.py`)**:
     - Extend `test_sdist_rebuild_installs_terminal_policy_outside_checkout` (`--no-deps` venv) ONLY with archive membership (`taut/agent-kernel.md` in sdist and wheel) plus `importlib.resources.files("taut").joinpath("agent-kernel.md").read_text("utf-8")` (no `TautClient` import in the `--no-deps` probe).
     - Add an `@pytest.mark.installed_wheel` test using `installed_command_fixture` (`tests/conftest.py:258`, which installs `simplebroker` and `psutil` alongside the built `taut-chat` wheel) in a fresh directory outside the repo checkout: assert `TautClient.agent_kernel()` returns the packaged text, run `taut onboard --channel dev` and `taut onboard --print-kernel`, have `--as van` post `"kickoff"` with `say dev "kickoff" --join`, then execute the rendered session-start recipe as `--as claude`: `join dev --recent 20 --json` exits `0` and includes `"kickoff"`, immediate `read --json` exits `2` (caught up at join), a subsequent `"followup"` from `van` makes `claude`'s `read --json` exit `0` returning `"followup"`, and `claude`'s `say dev "ack"` exits `0`.
   - **TUI command mirror**:
     - Verify `test_every_core_leaf_has_one_explicit_tui_disposition` passes and `:onboard` reports `CLI-only in TUI: onboard`.
2. **Implement Slice 3**:
   - Create `taut/_onboard.py` and wire `OnboardFileStep`, `OnboardReport`, `TautClient.onboard()`, and `TautClient.agent_kernel()`.
   - Create `taut/commands/onboard.py`, register `onboard` in `taut/commands/_builtins.py` (`globals_=_SYSTEM_GLOBALS`), `taut/commands/syntax.py`, `taut/commands/_rendering.py`, and `_cli_only(("onboard",))` in `extensions/taut_tui/taut_tui/command_bindings.py`.
   - Update `README.md` (`Command Reference`, `Quick Start`, `Working With Agents` — including optional `taut-mcp` installation and per-call `workspace`/`token` note for `onboard --mcp`), `docs/implementation/02-repository-map.md`, `docs/implementation/04-taut-architecture.md`, and `docs/implementation/12-taut-tui.md`.
3. **Verify Slice 3**:
   - `uv run --no-sync --extra dev pytest tests/test_onboard.py tests/test_public_api.py tests/test_lazy_imports.py tests/test_cli_claims.py tests/test_docs_references.py`
   - `uv run --no-sync --extra dev pytest -m installed_wheel tests/test_lazy_imports.py -k "onboard"`
   - `uv run bin/check-doc-paths && uv run bin/check-cli-claims && uv run bin/check-plan-status-index`

## 9. Testing Plan and Anti-Mocking Rules

- Real temporary filesystem trees (`tmp_path`), real POSIX symlinks, inodes (`st_ino`), and file modes, real SQLite databases, real sdist -> wheel -> fresh-venv builds (`test_lazy_imports.py`), real Docker PostgreSQL 18 (`./bin/pytest-pg`), and real Textual `TautApp` under `run_test()`.
- Apply adversarial CLI probes (`docs/agent-context/runbooks/adversarial-acceptance-probes.md`): `--db` collisions against managed files, external symlinks, broken symlinks, directory collisions, invalid UTF-8 files, unbalanced markers, malformed/conflicting `.mcp.json`, malformed `.taut.toml` on `--print-kernel`, pre-verb and post-verb `--as`/`--token`/`-t` rejection, blank `say --join`, out-of-range `--recent`, and `--` option terminators.

## 10. Final Verification and Gates

```bash
uv run --extra dev ruff check taut tests bin extensions/taut_pg/taut_pg extensions/taut_pg/tests bin/pytest-pg extensions/taut_summon/taut_summon extensions/taut_summon/tests
uv run --extra dev ruff format --check taut tests extensions bin
uv run --project extensions/taut_tui --extra dev ruff check extensions/taut_tui/taut_tui extensions/taut_tui/tests
uv run --project extensions/taut_mcp --extra dev ruff check extensions/taut_mcp/taut_mcp extensions/taut_mcp/tests
uv run --no-sync --extra dev python bin/ruff_suppression_index.py --check
uv run --extra dev mypy taut tests bin/release.py bin/release-artifact.py bin/require-green-workflows.py --config-file pyproject.toml
uv run --extra dev mypy taut/_scripts.py extensions/taut_pg/taut_pg extensions/taut_pg/tests extensions/taut_pg/tests/conftest.py --config-file pyproject.toml
uv run --extra dev mypy extensions/taut_summon/taut_summon extensions/taut_summon/tests extensions/taut_summon/tests/conftest.py --config-file pyproject.toml
uv run --project extensions/taut_tui --extra dev mypy extensions/taut_tui/taut_tui extensions/taut_tui/tests --config-file extensions/taut_tui/pyproject.toml
uv run --project extensions/taut_mcp --extra dev mypy extensions/taut_mcp/taut_mcp extensions/taut_mcp/tests --config-file extensions/taut_mcp/pyproject.toml
uv run bin/check-plan-status-index && uv run bin/check-plan-status-index --self-test
uv run bin/check-doc-paths && uv run bin/check-doc-paths --self-test
uv run bin/check-cli-claims && uv run bin/check-dom15-fixtures
uv run bin/coalesce-check
uv run --extra dev pytest -m "not installed_wheel"
uv run --extra dev pytest -m installed_wheel tests/test_lazy_imports.py -k "onboard"
uv run --project extensions/taut_tui --extra dev --locked pytest extensions/taut_tui/tests -n 2 --dist loadfile
uv run ./bin/pytest-pg
git diff --check
```

## 11. Out of Scope

- `taut whoami --show-token` and `taut mcp` launch-time `--workspace` / `--token` / `--as` defaults, bounded command FIFO, and `#channel` MCP normalization — owned by Phase 2A (Plan 3).
- `taut summon` provider readiness/catalog, pass-through args, permission presets, `TIOCGWINSZ`/`SIGWINCH` attach resize, and `--tmux` — owned by Phase 2B (Plan 4).
- `#channel` normalization in `join` and `search --channel`, 2-arg `taut reply MSG_ID TEXT`, `taut-chat` script alias / `taut-chat[default]` extras / install hints, `TautClient` context manager, TUI Day-1 UX polish, and `F8` plan-hygiene sweep — owned by Phase 3 (Plan 5).
- Modifying or staging `skills/call-agent/SKILL.md`.

## 12. Independent Review Loop

- **Author family:** Gemini (`Antigravity`).
- **Reviewer family:** OpenAI (`codex`, `codex-cli 0.170.0`, read-only OS-sandboxed Tier-1 review).
- **Rejected alternatives in force:** `[THEORY-5.A1]` through `[THEORY-5.A6]` in `docs/program-theory.md`.

## 13. Fresh-Eyes Review

Re-read in full on 2026-11-24 after incorporating all Round-1 `codex` findings (`F1`–`F6`):

1. Verified `onboard` enforces `root` symlink containment, preflights SQLite `--db`/sidecar cross-role collisions before opening storage, uses `O_WRONLY | O_APPEND` without `O_CREAT` on `.gitignore`/`.dockerignore` (preserving inode/owner/mode/ACLs and preventing file recreation on concurrent unlink), and fails closed on an existing differing `mcpServers.taut` entry.
2. Verified `join_channel(..., recent=N)` uses `Queue.peek_many(recent, with_timestamps=True, before_timestamp=..., order="newest")`, `JoinResult` drops the racy `joined` boolean in favor of `(thread, notice, recent)`, and `say(..., join=True)` resolves the acting member once so `last_created_member` and its continuity token survive to output.
3. Verified Slice 0 preserves `2026-11-10`'s promoted `Replacement` blocks verbatim, stages `taut/agent-kernel.md` before path claims land, and keeps `[TAUT-6.4]` terminal-policy preflight unchanged on `onboard --print-kernel`.

## 14. Review Log

### Round 1 — Pre-Implementation Plan Review (`codex-cli 0.170.0`, 2026-11-24)

- **Command**: `codex exec -s read-only -c 'model_reasoning_effort="high"' -C /Users/van/Developer/taut -o phase1_plan_review_msg.txt --json - < phase1_plan_review_prompt.txt`
- **Verdict**: `BLOCKED` (6 blocking findings `F1`–`F6` + proof refinements).
- **Dispositions**:
  - `F1` (`onboard` `--db` cross-role collision, external symlinks, `os.replace` recreating unlinked ignore files and losing owner/ACLs, untracked rollback prose): **Accepted — fixed in plan** (§1, §4.1c, §4.1e, §6, §7, §8 Slice 3). Added storage-target resolution and cross-role collision preflight, strict `root` symlink containment, `O_WRONLY | O_APPEND` (without `O_CREAT`) in-place appends for `.gitignore`/`.dockerignore` preserving inode/owner/mode/ACLs, `[PIO-6.2]` permission/inode documentation for atomic `AGENTS.md`/`CLAUDE.md`/`.mcp.json` updates, and truthful retry/rollback notes.
  - `F2` (narrow literal-line ignore policy, custom `--db` boundary, existing differing `mcpServers.taut`, `README.md` MCP note): **Accepted — fixed in plan** (§1, §4.1c, §6, §8 Slice 3). Adopted literal-line append policy (never rewriting operator negations; custom `--db` paths documented as operator-managed), fail-closed `TautError` when `mcpServers.taut` already exists with a different configuration, and `README.md` note on `taut-mcp` installation and per-call `workspace`/`token` inputs.
  - `F3` (`O(history)` scan in `join_channel`, `JoinResult.joined` race, post-commit read failure, membership-to-notice interleaving): **Accepted — fixed in plan** (§1, §4.1b, §4.1d, §4.1e, §8 Slice 2). Switched to `Queue.peek_many(recent, with_timestamps=True, before_timestamp=..., order="newest")`, simplified `JoinResult` to `(thread, notice, recent)`, specified post-commit read durability, and added the membership-to-notice interleaving test.
  - `F4` (`say --join` double `_resolve_member()` clearing `last_created_member`, TUI pre-action `--recent` check): **Accepted — fixed in plan** (§1, §4.1c, §4.1e, §6, §8 Slice 2). Shared `_ensure_channel_membership()` with a single `_resolve_member(create=True)` call, added explicit `--as freshbot` 2-line NDJSON CLI test, and required TUI `:join --recent` rejection before joining.
  - `F5` (pre-verb `--as`/`--token`/`-t` leak in `_SYSTEM_GLOBALS` and `[TAUT-6.4]` terminal-policy preflight on `--print-kernel`): **Accepted — fixed in plan** (§1, §4.1c, §4.1d, §6, §8 Slice 3). `OnboardCommand.run()` rejects `context.as_name`, `context.continuity_token`, and `context.timestamps` (and `db_path`/`json`/`quiet` on `--print-kernel`), and `--print-kernel` keeps `[TAUT-6.4]`'s standard human-output terminal-policy preflight with a malformed-`.taut.toml` test.
  - `F6` + proof notes (Slice 0 `bin/check-doc-paths` failure on `taut/agent-kernel.md` and `2026-11-10` `Replacement` block, race-exact `init.created` wording, concurrent `TautClient.init()` PG test, wheel smoke execution, Slice 2/3 `test_public_api.py` split, normal `-n 2` TUI lane): **Accepted — fixed in plan** (§1, §3, §4.1d, §4.1f, §8 Slices 0–3).

### Round 2 — Scoped Verification (`codex-cli 0.170.0`, 2026-11-24)

- **Command**: `codex exec -s read-only -c 'model_reasoning_effort="high"' -C /Users/van/Developer/taut -o phase1_plan_review_r2_msg.txt --json - < phase1_plan_review_r2_prompt.txt`
- **Verdict**: `FAIL` (Slice 0 promotion dry-run and `F4` passed; 5 precision tightenings across `F1`, `F2`, `F3`, `F5`, `F6`).
- **Dispositions**:
  - `F1` (hard-link aliases via `os.path.samefile`, collision check under `--no-init`, and §7 partial-append / unstaged-edit / pre-existing raw-DB rollback accuracy): **Accepted — fixed in plan** (§1, §4.1c, §4.1e, §6, §7, §8 Slice 3). Adopted `_same_path_or_file` (`resolve(strict=False)` + `os.path.samefile`), ran storage-alias collision preflight whenever any file step is enabled (including `--no-init`), qualified short-write `O_APPEND` retry, and grounded §7 rollback in pre-run working-tree and file-existence state.
  - `F2` (cross-role managed-file aliases such as `.gitignore -> .mcp.json` and `.strip()` altering leading-space ignore patterns): **Accepted — fixed in plan** (§1, §4.1c, §4.1e, §6, §8 Slice 3). Rejected all cross-role aliases across managed files (retaining only `CLAUDE.md` ↔ `AGENTS.md` same-role deduplication) and switched literal-line detection to `set(existing_text.splitlines())` without `.strip()`, with firing tests for both.
  - `F3` (scope `peek_many` count assertion to `order="newest"` separate from `_advance_sender_if_no_intervening`, plus fault-injection durability proof): **Accepted — fixed in plan** (§8 Slice 2).
  - `F5` (`--print-kernel` line-by-line `write_human_line` policy application + valid configured-matcher test): **Accepted — fixed in plan** (§1, §4.1c, §4.1d, §8 Slice 3).
  - `F6` (use `installed_command_fixture` with runtime deps `simplebroker`/`psutil` for end-to-end wheel onboarding smoke test, explicit `read` exit `2` -> `0` two-actor oracle, and explicit SQLite writer-transaction vs PostgreSQL `taut:schema` advisory-lock wording): **Accepted — fixed in plan** (§1, §4.1d, §5, §8 Slices 1 & 3, §10).

### Round 3 — Scoped Verification (`codex-cli 0.170.0`, 2026-11-24)

- **Command**: `codex exec -s read-only -c 'model_reasoning_effort="high"' -C /Users/van/Developer/taut -o phase1_plan_review_r3_msg.txt --json - < phase1_plan_review_r3_prompt.txt`
- **Verdict**: `FAIL` (5 narrow edge-case tightenings across `F1`, `F2`, `F3`, `F5`, `F6`).
- **Dispositions**:
  - `F1` (§7 rollback referenced `OnboardReport` even when a mid-apply failure raised before returning a report): **Accepted — fixed in plan** (§7). Grounded rollback in a pre-run existence/content snapshot and post-failure filesystem/git inspection.
  - `F2` (disabled-role alias `.gitignore -> .mcp.json` when `--mcp` omitted, and `os.replace` severing hard-linked `AGENTS.md` ↔ `CLAUDE.md`): **Accepted — fixed in plan** (§1, §4.1c, §4.1e, §6, §8 Slice 3). Enabled write targets are compared against every managed onboarding filename including disabled roles; `CLAUDE.md` ↔ `AGENTS.md` deduplicates only on identical `Path.resolve()`, while distinct hard-linked `AGENTS.md`/`CLAUDE.md` paths fail closed.
  - `F3` (`call.get("order") == "newest"` in `peek_many` spy): **Accepted — fixed in plan** (§8 Slice 2).
  - `F5` (`str.splitlines()` splits C1 `U+0085` before `_escape_human_text`): **Accepted — fixed in plan** (§1, §4.1c, §4.1d, §8 Slice 3). Split strictly on structural LF `"\n"` (`removesuffix("\n").split("\n")`) with a C1 `U+0085` test.
  - `F6` (`--no-deps` sdist test cannot import `TautClient`; header line 5 `taut:schema` wording): **Accepted — fixed in plan** (header, §8 Slice 3). Kept `--no-deps` sdist probe on archive + `importlib.resources` only, moved `TautClient.agent_kernel()` assertion into `installed_command_fixture`, and updated header line 5.

### Round 4 — Scoped Verification (`codex-cli 0.170.0`, 2026-11-24)

- **Command**: `codex exec -s read-only -c 'model_reasoning_effort="high"' -C /Users/van/Developer/taut -o phase1_plan_review_r4_msg.txt --json - < phase1_plan_review_r4_prompt.txt`
- **Verdict**: `FAIL` (`F2`, `F3`, `F5`, `F6` passed; 1 wording tightening on `F1` in §7).
- **Disposition**:
  - `F1` (§7 `"or inspect"` made pre-run snapshot optional; without a pre-run snapshot, post-failure `git status`/`git diff` cannot distinguish pre-existing untracked files or recover unstaged edits): **Accepted — fixed in plan** (§7). Required a pre-run existence and content snapshot for rollback, compared with post-failure inspection, leaving affected files in place when no pre-run snapshot exists.

### Round 5 — Scoped Verification (`codex-cli 0.170.0`, 2026-11-24)

- **Command**: `codex exec -s read-only -c 'model_reasoning_effort="high"' -C /Users/van/Developer/taut -o phase1_plan_review_r5_msg.txt --json - < phase1_plan_review_r5_prompt.txt`
- **Verdict**: **`PASS`** (`F1` verified resolved; no new defects). Plan promoted via Slice 0 (`Status: promoted`).

### Post-Implementation Review Round 1 (`codex-cli 0.170.0`, 2026-11-24)

- **Command**: `codex exec -s read-only -c 'model_reasoning_effort="high"' -C /Users/van/Developer/taut -o phase1_post_impl_review_r1_msg.txt --json - < phase1_post_impl_review_prompt.txt`
- **Verdict**: `BLOCKED` (5 blocking findings `F1`–`F5` + 6 proof/reference tightenings).
- **Dispositions**:
  - `F1` (concurrent join loser writing duplicate notice and advancing cursor past unread messages): **Accepted — fixed** (`taut/state/__init__.py`, `taut/state/_sql.py::add_membership_with_status`, `taut/client/_threads.py::_ensure_channel_membership`, `tests/test_client.py::test_concurrent_join_loser_does_not_write_duplicate_notice_or_skip_unread`). `add_membership_with_status` returns `(row, inserted)` via `INSERT ... ON CONFLICT DO NOTHING RETURNING ...`; when `inserted` is `False`, `_ensure_channel_membership` skips notice emission and cursor advancement, and `won_thread_create` checks `created_by` + `created_ts`.
  - `F2` (symlinked `--db` canonical companion paths and `.taut.toml` alias protection): **Accepted — fixed** (`taut/_onboard.py::_resolve_sqlite_companions_and_config_name`, `_preflight_aliases`, `tests/test_onboard.py`). Companion checks now cover both `sqlite_file` and `sqlite_file.resolve(strict=False)`, and `PROJECT_CONFIG_NAME` (`.taut.toml`) is included in protected project files.
  - `F3` (disabled-role standalone containment check and post-preflight path/parent TOCTOU): **Accepted — fixed** (`taut/_onboard.py`, `tests/test_onboard.py`). Preflight inspects all five `MANAGED_ONBOARD_FILENAMES` unconditionally; POSIX mutations pin `root_fd`, walk parent directories with `O_DIRECTORY | O_NOFOLLOW`, open files with `O_NOFOLLOW`, and verify `(st_dev, st_ino)` matches preflight.
  - `F4` (`O_EXCL` staging cleanup ownership, `O_BINARY` on Windows, and atomic `os.link` creation): **Accepted — fixed** (`taut/_onboard.py::_stage_and_publish`, `tests/test_onboard.py`). `created_staged` is latched only after `os.open(..., O_CREAT | O_EXCL)` succeeds, `O_BINARY` is applied on Windows, and create-only publication uses `os.link` without `os.replace`.
  - `F5` (duplicate JSON keys and `NaN` in `.mcp.json`): **Accepted — fixed** (`taut/_onboard.py::_reject_duplicate_json_keys`, `_reject_json_constant`, `tests/test_onboard.py`).
  - Verification & doc-name tightenings: **Accepted — fixed** (valid-UTF-8 SQLite hard-link alias test, post-preread `Barrier` in SQLite and PostgreSQL `TautClient.init()` race tests forcing the locked loser branch, invalid/DM target blank-first `say(..., join=True)` assertions, `TuiSession` worker flush in `:join --recent` negative test, and `_apply_planned_ignore` / `TuiDomainActions.send_message` doc references).

### Post-Implementation Review Round 2 (`codex-cli 0.170.0`, 2026-11-24)

- **Command**: `codex exec -s read-only -c 'model_reasoning_effort="high"' -C /Users/van/Developer/taut -o phase1_post_impl_review_r2_msg.txt --json - < phase1_post_impl_review_r2_prompt.txt`
- **Verdict**: `FAIL` (`F2` and all 6 verification/reference items passed; 4 targeted items across `F1`, `F3`, `F4`, `F5`).
- **Dispositions**:
  - `F1` (two concurrent first joins by the same member splitting `upsert_thread` and `add_membership_with_status` across two transactions and emitting `"joined"` instead of `"created"`): **Accepted — fixed** (`taut/state/_sql.py::ensure_channel_membership`, `taut/client/_threads.py::_ensure_channel_membership`, `tests/test_client.py::test_concurrent_same_member_first_channel_creation_emits_created_notice`). Combined channel check/insert and membership check/insert into a single atomic sidecar transaction under `_CHAT_TOPOLOGY_LOCK_KEY`.
  - `F3` (`_open_root_fd` opening `resolved_root` without `O_NOFOLLOW`/`samestat`, and clarifying `os.replace` containment vs in-root CAS): **Accepted — fixed** (`taut/_onboard.py::_open_root_fd`, `_publish_staged_file`). `_open_root_fd` now opens `resolved_root` with `O_DIRECTORY | O_NOFOLLOW` and verifies `os.path.samestat(raw_stat, os.fstat(fd))`; root containment for replacements is unconditionally guaranteed by pinned `parent_fd` + POSIX `renameat` never following destination symlinks, while pre-replace `stat` is documented as best-effort before `[TAUT-8.3]`'s same-directory atomic replacement.
  - `F4` (`os.link` failing on filesystems that lack hard links): **Accepted — fixed** (`taut/_onboard.py::_create_direct_exclusive`, `_publish_staged_file`, `tests/test_onboard.py`). Falls back to exclusive `O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW` (`O_BINARY` on Windows) mode `0o666` creation when `os.link` raises `_LINK_UNSUPPORTED_ERRNOS` (while still re-raising `EEXIST`).
  - `F5` (valid large-exponent JSON numbers such as `1e400` in `.mcp.json` overflowing float to `inf` and raising bare `ValueError` under `allow_nan=False`): **Accepted — fixed** (`taut/_onboard.py::_dump_json`, `_plan_mcp_step`, `tests/test_onboard.py`). Uses `parse_float=Decimal` + `_dump_json` and catches `InvalidOperation`, preserving `1e400` cleanly while rejecting `NaN`/`Infinity` tokens and duplicate keys.

### Post-Implementation Review Round 3 (`codex-cli 0.170.0`, 2026-11-24)

- **Command**: `codex exec -s read-only -c 'model_reasoning_effort="high"' -C /Users/van/Developer/taut -o phase1_post_impl_review_r3_msg.txt --json - < phase1_post_impl_review_r3_prompt.txt`
- **Verdict**: `FAIL` (`F1` production fix verified; 4 narrow items across `F1` test barrier, `F3`, `F4`, `F5`).
- **Dispositions**:
  - `F1` verification gap (`Barrier` placed before `join()` rather than after `get_membership -> None`): **Accepted — fixed** (`tests/test_client.py::test_concurrent_same_member_first_channel_creation_emits_created_notice`). Synchronizes both callers inside `SqlSidecarTautState.get_membership` when `thread == "brandnew"` and `existing is None`.
  - `F3` (`parent_fd` for a subdirectory moved outside `root_fd` after `_open_pinned_parent_fd`): **Accepted — fixed** (`taut/_onboard.py::_assert_parent_inside_root`, `tests/test_onboard.py`). Re-verifies both downward `O_DIRECTORY | O_NOFOLLOW` walk from `root_fd` (`samestat`) and upward `..` walk from `parent_fd` to `root_fd` immediately before `_write_all_fd` and `_publish_staged_file`.
  - `F4` (`_create_direct_exclusive` exposing destination before write completion): **Accepted — fixed** (`taut/_onboard.py::_atomic_rename_noreplace`, `_publish_staged_file`, `tests/test_onboard.py`). Replaced direct destination writes with kernel-atomic no-overwrite rename of the already-written `0o666` staging file (`renameatx_np(..., RENAME_EXCL)` on macOS, `renameat2(..., RENAME_NOREPLACE)` on Linux, `MoveFileExW(..., 0)` on Windows).
  - `F5` (recursive `_dump_json` hitting `RecursionError` at 600 nesting levels and `Decimal` rejecting `0e1000000000000000000`): **Accepted — fixed** (`taut/_onboard.py::_RawJsonNumber`, `_push_json_container`, `_dump_json`, `tests/test_onboard.py`). Preserves validated JSON number tokens verbatim via `parse_float=_RawJsonNumber, parse_int=_RawJsonNumber` and serializes containers with an explicit iterative stack (0 recursion frames).

### Post-Implementation Review Round 4 (`codex-cli 0.170.0`, 2026-11-24)

- **Command**: `codex exec -s read-only -c 'model_reasoning_effort="high"' -C /Users/van/Developer/taut -o phase1_post_impl_review_r4_msg.txt --json - < phase1_post_impl_review_r4_prompt.txt`
- **Verdict**: `FAIL` (`F1`, `F4`, `F5` passed; 1 narrow ordering refinement on `F3`).
- **Disposition**:
  - `F3` (`_assert_parent_inside_root` ran before `stat`/`chmod` in `_publish_staged_file` and before `fstat` in `_read_utf8_with_identity`): **Accepted — fixed** (`taut/_onboard.py::_read_utf8_with_identity`, `_write_all_fd`, `_publish_staged_file`, `_stage_and_publish`, `_apply_planned_ignore`, `tests/test_onboard.py`). Placed `_assert_parent_inside_root` immediately before every `os.read`, `os.write`, `os.replace`, `os.link`, and `_atomic_rename_noreplace` call, with fault-injection tests moving `subdir` during `os.chmod` and `os.fstat`.

### Post-Implementation Review Round 5 (`codex-cli 0.170.0`, 2026-11-24)

- **Command**: `codex exec -s read-only -c 'model_reasoning_effort="high"' -C /Users/van/Developer/taut -o phase1_post_impl_review_r5_msg.txt --json - < phase1_post_impl_review_r5_prompt.txt`
- **Verdict**: `FAIL` (2 micro-items: retain `_assert_parent_inside_root` before `os.stat` and `os.chmod` in addition to before `os.replace`, and assert `reads_after_move == []` in the `fstat` fault-injection test).
- **Disposition**:
  - **Accepted — fixed** (`taut/_onboard.py::_publish_staged_file`, `tests/test_onboard.py`). `_assert_parent_inside_root` now runs before `os.stat`, before `os.chmod`, and before `os.replace`, and the `fstat` fault-injection test spies `os.read` to prove zero `os.read` calls occur after the parent move.

### Post-Implementation Review Round 6 (`codex-cli 0.170.0`, 2026-11-24)

- **Command**: `codex exec -s read-only -c 'model_reasoning_effort="high"' -C /Users/van/Developer/taut -o phase1_post_impl_review_r6_msg.txt --json - < phase1_post_impl_review_r6_prompt.txt`
- **Verdict**: `FAIL` (Round-5 `_publish_staged_file` and `fstat` spy items passed; 1 regression in `_cleanup_staged_file` where guarding `unlink` on the old relative path leaked the owned staging file when renamed within the workspace without closing the `unlinkat` race).
- **Disposition**:
  - **Accepted — fixed** (`taut/_onboard.py::_cleanup_staged_file`). Restored unconditional `unlink` of the exclusively created temporary staging file on `parent_fd`, avoiding leaked temp files on in-workspace renames without claiming atomic parent-location CAS across `unlinkat`.

### Post-Implementation Review Round 7 (`codex-cli 0.170.0`, 2026-11-24)

- **Command**: `codex exec -s read-only -c 'model_reasoning_effort="high"' -C /Users/van/Developer/taut -o phase1_post_impl_review_r7_msg.txt --json - < phase1_post_impl_review_r7_prompt.txt`
- **Verdict**: **`PASS`** (verified cleanup after in-workspace rename, preservation of pre-existing staging file on `O_EXCL` collision, and intact Round-5 containment checks).

## 15. Execution Log

### Pre-Edit Comprehension Check (2026-11-24)

1. **Q1 (`onboard` containment, alias preflight, and `O_APPEND` non-creation)**:
   Every enabled write target must stay inside `resolved_root` (`Path.resolve().is_relative_to(resolved_root)`) and be checked via `_same_path_or_file` (`resolve(strict=False)` + `os.path.samefile`) against both resolved SQLite target/sidecar files (even under `--no-init`) and all five managed onboarding filenames including disabled roles (`CLAUDE.md` ↔ `AGENTS.md` deduplicating only on identical `Path.resolve()`, failing closed on distinct hard-linked paths). `.gitignore` and `.dockerignore` use `os.open(..., os.O_WRONLY | os.O_APPEND)` without `O_CREAT` over exact `splitlines()` membership so absent/unlinked ignore files can never be created and existing inode/owner/mode/ACLs stay intact.
2. **Q2 (`say --join` single actor resolution & blank-first ordering)**:
   `_resolve_member()` resets `self.last_created_member = None` at entry, so `say(..., join=True)` must validate `type(join) is bool`, check `is_blank_message_text(text)` before any domain work, reject non-top-level-channel targets with `ThreadNameError`, call `_resolve_member(create=True)` once, and pass that `MemberRow` into shared `_ensure_channel_membership()` and `_say_chat_thread()` so first-contact `--json` preserves the one-time continuity-token line alongside a single `ts`-bearing message line.
3. **Q3 (`join_channel` indexed `peek_many` & `init().created` sidecar atomicity)**:
   `Queue.peek_many(recent, with_timestamps=True, before_timestamp=notice.ts if notice is not None else None, order="newest")` reversed to ascending order bounds catch-up reads to `O(recent)` without moving any cursor; `ensure_schema() -> bool` returns `True` solely when committing the `taut_meta.schema_version` insert inside SQLite's writer transaction or under PostgreSQL's `taut:schema` advisory lock.

### Implementation & Verification Evidence (2026-11-24)

- **Slice 0 (Spec Promotion & Initial Packaged Kernel Resource)**:
  - Staged `taut/agent-kernel.md` from `docs/agent-kernel.md`, applied all §4.1 (`docs/specs/02-taut-core.md`) and §4.2 (`docs/specs/10-taut-tui.md`) `Replacement` blocks, updated status to `promoted`, and verified `bin/check-plan-status-index`, `bin/check-doc-paths` (`1611 path claim(s): OK`), and `bin/check-cli-claims` (`300 command claim(s): OK`).
- **Slice 1 (Cross-Backend `TautClient.init().created`)**:
  - RED -> GREEN in `taut/state/_sql.py`, `taut/state/__init__.py`, `taut/client/__init__.py`, `tests/test_client.py`, and `extensions/taut_pg/tests/{test_pg_sidecar,test_pg_integration}.py`. Verified on SQLite (`14 passed`) and Docker PostgreSQL 18 (`5 passed`, including 4-worker concurrent `TautClient.init()` race).
- **Slice 2 (`join --recent N`, `say --join`, TUI Bindings & `agent-kernel.md`)**:
  - RED -> GREEN in `taut/client/{_models,_base,_threads,_messaging,__init__}.py`, `taut/__init__.py`, `taut/commands/{syntax,join,say}.py`, `extensions/taut_tui/taut_tui/{domain,app}.py`, `docs/agent-kernel.md`, `taut/agent-kernel.md`, and `pyproject.toml`. Verified `test_public_api.py`, `test_command_syntax.py`, `test_docs_references.py`, `test_cli_claims.py`, `test_client.py`, `test_cli.py`, and TUI binding/action handler suites (`0` failures).
- **Slice 3 (`taut onboard`, `TautClient.onboard`, `TautClient.agent_kernel`, Wheel Packaging & Docs)**:
  - RED -> GREEN in `taut/_onboard.py`, `taut/commands/onboard.py`, `taut/commands/{_builtins,syntax,_rendering}.py`, `taut/client/{_models,__init__}.py`, `taut/__init__.py`, `extensions/taut_tui/taut_tui/command_bindings.py`, `tests/{test_onboard,test_public_api,test_command_registry,test_lazy_imports}.py`, `README.md`, and `docs/implementation/{02-repository-map,04-taut-architecture,12-taut-tui}.md`.
- **Full §10 Gate Matrix**:
  - All Ruff checks/format across core, `taut_pg`, `taut_summon`, `taut_tui`, `taut_mcp` + `bin/ruff_suppression_index.py --check`: `0` issues.
  - All 5 `mypy` invocations (`149 + 13 + 55 + 56 + 23` files): `0` issues.
  - `check-plan-status-index` (+ `--self-test`), `check-doc-paths` (`1624 path claim(s)` + `--self-test`), `check-cli-claims` (`310 command claim(s)`), `check-dom15-fixtures`, `coalesce-check`, `git diff --check`: all `0`.
  - Root `pytest -m "not installed_wheel"`, `pytest -m installed_wheel tests/test_lazy_imports.py -k "onboard"`, full `taut_tui` (`-n 2 --dist loadfile`), and Docker PostgreSQL 18 `./bin/pytest-pg` (`shared` + `pg_only`): all passed (`0` failures).
