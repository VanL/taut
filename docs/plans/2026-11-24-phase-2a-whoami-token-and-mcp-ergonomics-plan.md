# Phase 2A Plan: `taut whoami --show-token` and `taut-mcp` Ergonomics

- Status: `completed`
- Class: `5+P` (per `[DOM-15]`: adds public CLI `--show-token`, `TautClient.whoami(..., include_token=False)`, and pre-setup non-installing `TautClient(..., install_schema=True)`; adds optional launch-time `--workspace` / `--token` / `--as` defaults on `taut mcp` and `taut-mcp` with compact nullable tool-schema properties and private `tools/list` cache scoping; replaces 1-slot ready-workspace immediate rejection with a bounded master-owned per-workspace command FIFO queue; normalizes optional leading `#` across `taut-mcp` channel/sub-thread schemas and `TautClient.search(channels=...)`; and upgrades schema-invalid diagnostics to name deterministic server-owned schema fields without echoing caller values or unknown keys)
- Plan type: implementation with Strategy-A spec promotion (`docs/agent-context/runbooks/writing-plans.md` §4c)
- Owner: repository owner
- Author family: Claude (`Antigravity` harness; cross-family Tier-1 reviewer: OpenAI `codex-cli 0.170.0` / `gpt-6.2-sol`)
- Created: `2026-11-24`
- Spec baseline: `8955636d91d17aeb197e47a206b6e00ef3a2c5de` (`Phase 1 sixty-second onboarding, cold-join context, and auto-join send`)
- Promotion baseline: Slice 0 spec-promotion applied atop `8955636`
- Governing specs:
  - `docs/specs/02-taut-core.md` (`[TAUT-8.1]`, `[TAUT-8.2]`, `[TAUT-8.3]`, `## Related Plans`)
  - `docs/specs/03-identity-addressing-notifications.md` (`[IAN-3.3]`, `[IAN-5.1]`, `## Related Plans`)
  - `docs/specs/05-taut-mcp.md` (`[MCP-2]`, `[MCP-3]`, `[MCP-4]`, `[MCP-5]`, `[MCP-6]`, `[MCP-8]`, `[MCP-9]`, `[MCP-10]`, `[MCP-12]`, `## Related Plans`)
  - `docs/specs/06-search.md` (`[SRCH-4.1]`, `## Related Plans`)
  - `docs/specs/10-taut-tui.md` (`[TUI-7.1]`, `## Related Plans`)
  - `docs/program-theory.md` (`[THEORY-1]`, `[THEORY-2]`, `[THEORY-4]`, `[THEORY-5.A3]`)
- Related plans:
  - `docs/plans/2026-11-23-phase-0-bug-and-performance-remediation-plan.md` (`completed`)
  - `docs/plans/2026-11-24-phase-1-sixty-second-onboarding-plan.md` (`completed`)
  - `docs/plans/2026-11-10-upstream-port-runtime-hardening-and-theory-wave-plan.md` (`promoted` — all 24 `Replacement` spans in `01`, `02`, `03`, `04`, `07`, `08` preserved verbatim)
- Implementation docs to align:
  - `docs/implementation/02-repository-map.md`
  - `docs/implementation/04-taut-architecture.md`
  - `docs/implementation/07-taut-mcp-architecture.md`
  - `README.md`, `extensions/taut_mcp/README.md`, `docs/agent-kernel.md` + `taut/agent-kernel.md`

---

## 1. Context, Motivation, and Scope

The empirical review and owner decisions (`Q1` = **Yes**) identified five adoption and operational friction points across identity continuity and `taut-mcp`:

1. **Continuity tokens are unrecoverable without raw SQL or full workspace dumps:** Taut prints a member's continuity token once to `stderr` at creation, while `taut whoami` and `TautClient.whoami()` hardcode `token=None`. Consistent with `[THEORY-5.A3]` (continuity tokens are identity selectors within the storage trust boundary, not authentication secrets), keeping tokens off default `whoami` avoids casual screen-share noise while `taut whoami --show-token` (`TautClient.whoami(*, explain=False, include_token=False)`) gives operators and scripts a clean, read-only retrieval path that preserves `last_created_member` and `last_candidates`.
2. **`taut-mcp` forces LLM prompts to carry and regenerate `workspace` and `token` on every tool call:** Standard MCP hosts (`.mcp.json`, `claude mcp add`, Claude Desktop, Cursor, Codex, Antigravity) configure per-server launch arguments (`args`). Supporting optional launch-time `--workspace DIR` and mutually exclusive `--token TOKEN` / `--as NAME_OR_ALIAS` defaults on both `taut mcp` and `taut-mcp` makes `workspace` and/or `token` optional nullable (`type: ["string", "null"]`) in advertised tool schemas when configured at launch while preserving explicit per-call `(workspace, token)` overrides, staying strictly under the 21,000-byte manifest ceiling in all four launch modes, scoping `tools/list` cache metadata to `private` when launch defaults customize schemas, and keeping zero ambient `cwd`/`TAUT_DB`/`TAUT_AS`/`TAUT_TOKEN` inference and zero broker/sidecar setup or migration writes on uninitialized or broker-only targets (`TautClient(..., install_schema=False)`).
3. **Parallel tool calls in one LLM turn fail with `workspace busy; retry after backoff`:** `ProcessReactor._execute_ready_tool` currently enforces a single no-wait command slot (`active_command_id`) per ready workspace. Replacing the 1-slot immediate rejection on ready workspaces with a **bounded master-owned per-workspace command FIFO queue** (`MAX_QUEUED_COMMANDS = 8`, allowing 1 active + 8 queued uncancelled commands per ready workspace before returning `workspace busy; retry after backoff`) serializes concurrent same-workspace tool calls cleanly while keeping at most one `RunWorkspaceCommand` in flight to the child reactor turn at a time and synchronously pruning cancelled waiters before both admission capacity checks and FIFO promotion.
4. **`#general` addressing mismatch across `taut-mcp` and `taut search`:** `[IAN-5.1]` accepts an optional single leading `#` on channel and sub-thread targets across CLI verbs and MCP `say.target`, yet `taut-mcp`'s `CHANNEL_PATTERN`, `CHAT_PATTERN`, and `CHAT_OR_DM_PATTERN` reject `#general` / `#general.<19-digit-id>` and `TautClient.search(channels=...)` (`[SRCH-4.1]`) raises `ValueError("search channel selectors must be bare channel names")`. Allowing an optional single leading `#` (`^#?[a-z0-9][a-z0-9_-]{0,63}$`) in MCP channel/chat patterns and normalizing `channels` through `addressing.validate_chat_thread_name(..., allow_subthread=False)` in `TautClient.search` makes `#general` work uniformly across CLI, Python, and MCP (note: TUI `:search --channel` remains intentionally CLI-only per `app.py:1575`).
5. **Opaque schema-validation errors plus Phase 1 `onboard` CLI-parity drift:** `validate_tool_call` currently returns one generic string even when a single field (`msg_id`, `limit`, `channels[0]`, or missing `token`) caused the failure. Returning deterministic, **server-owned field-named** diagnostics (strictly never echoing caller-supplied argument values OR caller-supplied unknown property keys) lets LLMs self-correct in one turn while preserving `[MCP-5]`/`[MCP-10]`'s zero-value-echo safety. In addition, Phase 1 added built-in `onboard` to `BUILTIN_SPECS`; `[MCP-5]` and `test_dual_era_contract.py::INTENTIONALLY_UNEXPOSED_CLI_COMMANDS` explicitly list `onboard` among CLI commands intentionally unexposed as MCP tools.

Out of scope for Phase 2A (scheduled in Phases 2B and 3):
- `taut-summon` provider catalog/readiness, permission presets, `TIOCGWINSZ`/`SIGWINCH`, pre-bootstrap confirmation, and `--tmux` (Phase 2B).
- Separate-distribution packaging polish (`taut-chat` console alias, `taut-chat[default]`, missing-extension install hints for `tui`/`mcp`), 2-arg `taut reply MSG_ID TEXT`, display-only `.taut.toml`, TUI Day-1 UX polish, and `F8` plan hygiene (Phase 3 — the 14 harvest-eligible plans in `docs/plans/README.md` and adding plan-tier counting to `bin/coalesce-check` are explicitly owned by Phase 3's `F8` plan-hygiene slice).

---

## 2. Theory-Versus-Code and Theory-Versus-Spec Audit Table (`[AT-REF-2]`)

| Theory anchor | Principle / commitment | Phase 2A alignment | Verdict |
|---|---|---|---|
| `[THEORY-1]`, `[THEORY-4]` rule 1 | Humans and agents are both first-class; CLI exposes `--json`, protocol surfaces use native machine transport | `taut whoami --show-token [--json]` exposes continuity tokens cleanly on CLI/Python while keeping `:whoami --show-token` CLI-only in TUI chrome; `taut-mcp` launch defaults remove redundant prompt plumbing | Aligned |
| `[THEORY-2]`, `[THEORY-4]` rule 3, `[THEORY-5.A3]` | Storage access is the only boundary; `--as` requires no proof; continuity tokens are selectors, not secrets or auth | `whoami --show-token` retrieves the stored continuity selector read-only without minting or mutating state; `taut mcp --as NAME` resolves an existing member on an already-initialized workspace via `TautClient(..., install_schema=False).whoami(include_token=True)` with zero broker setup, migration, or sidecar DDL writes | Aligned |
| `[THEORY-4]` rule 2 | Zero configuration by default; explicit, project-visible doors otherwise | Bare `taut mcp` / `taut-mcp` retains exact 21-tool required-`(workspace, token)` behavior; launch defaults are explicit CLI arguments (`--workspace`, `--token`, `--as`), never ambient `cwd`/`TAUT_DB`/`TAUT_AS`/`TAUT_TOKEN` inference | Aligned |
| `[THEORY-5.A4]` | No required user-managed daemon | `taut-mcp` remains a connection-scoped stdio child process launched by the MCP host; bounded per-workspace command FIFO lives in-memory on `ProcessReactor` and exits with stdio | Aligned |

---

## 3. Hardening Analysis (`docs/agent-context/runbooks/hardening-plans.md`)

### 3.1 Explicit Invariants

1. **Read-only non-mutation, diagnostic-object preservation, and pre-broker-setup non-installing `TautClient(..., install_schema=False)` (`[IAN-3.3]`, `[TAUT-8.3]`, `[MCP-4]`, `[MCP-5]`):**
   - `TautClient.whoami(*, explain: bool = False, include_token: bool = False) -> Member`:
     - Validates `isinstance(explain, bool)` and `isinstance(include_token, bool)` (`TypeError` before any resolution or I/O).
     - Saves `last_created_member = self.last_created_member` and `last_candidates = self.last_candidates` before `_resolve_member(...)` and restores both references in `finally:`, matching `peek_identity()` and `touch_identity_activity()` so both attributes retain exact object identity (`is`) across `whoami` success, `UnrecognizedCallerError`, and missing-token `TokenError`.
     - Default `include_token=False` leaves `Member.token is None` and omits `"token"` from `--json` and human output.
     - With `include_token=True`, `whoami` uses `_resolve_member(create=False, _touch_activity=False, _heal_claim=False, _require_capture=explain)`: it never creates a member, never records or refreshes a claim, never heals an anchor, and never updates `last_active_ts`. If the resolved member row has a missing or empty stored `token` (`not isinstance(row["token"], str) or not row["token"]`), `whoami(include_token=True)` raises `TokenError("selected member has no continuity token")` (CLI exit `1`) rather than emitting `null` or omitting `"token"`.
     - Human `emit_members` renders `write_human_line(stdout, f"token: {member.token}")` (escaped through `[TAUT-6.4]`) after the member row and before any `--explain` JSON line; `--json` `member_object(member, include_token=True)` includes `"token": member.token`.
     - TUI `:whoami --show-token` is rejected inline with `--show-token is CLI-only in the TUI.` (`[TUI-7.1]`).
     - MCP `whoami` (`_commands.py`) calls `client.whoami(explain=False, include_token=False)` and `record_object(Member)` retains its closed 7-field schema.
   - Pre-broker-setup `TautClient(..., install_schema: bool = True)` (`R2.4` fix):
     - Default `install_schema=True` preserves all existing CLI and library behavior (`self._state.ensure_schema()`).
     - When `install_schema=False` (`isinstance(install_schema, bool)` validated first), `_ClientBase.__init__` runs `require_installed_taut_target(self.target, self.config)` **before** constructing `self._meta_queue = self.queue(META_QUEUE_NAME)`:
       1. Opens a short-lived raw `runner = plugin.create_runner(target_str, backend_options=..., config=self.config)` inside `try ... finally: runner.close()` (where `plugin.create_runner` constructs a raw `SQLiteRunner` / `PostgresRunner` that never invokes `BackendAwareRunner.setup()` or `migrate_schema()`!).
       2. Checks schema-qualified table existence before reading metadata:
          - On PostgreSQL (`backend_name == "postgres"`, `schema_name = runner.schema`), queries `SELECT table_name FROM information_schema.tables WHERE table_schema = ? AND table_name IN ('meta', 'taut_meta')` with `(schema_name,)` and requires `{"meta", "taut_meta"}` in `schema_name` specifically (never falling back through `PostgresRunner`'s `SET search_path TO "<schema>", public` to `public.meta` or `public.taut_meta`!), then reads `SELECT key, value FROM "<quoted_schema>".taut_meta WHERE key IN (?, ?)` with `(SCHEMA_VERSION_KEY, LOAD_GUARD_KEY)`.
          - On SQLite, checks `if not plugin.meta_table_exists(runner): raise NotInitializedError(NO_DATABASE_MESSAGE)` and executes `SELECT key, value FROM taut_meta WHERE key IN (?, ?)` with `(SCHEMA_VERSION_KEY, LOAD_GUARD_KEY)` on `runner.run(..., fetch=True)` (catching `DatabaseError` where `_is_schema_shape_error(exc)` -> `raise NotInitializedError(NO_DATABASE_MESSAGE)`).
       3. Verifies `SCHEMA_VERSION_KEY in meta` (else `raise NotInitializedError(NO_DATABASE_MESSAGE)`), `_require_supported_version(decode_schema_version(meta[SCHEMA_VERSION_KEY]))`, and `LOAD_GUARD_KEY not in meta` (else `raise TautError(LOAD_GUARD_MESSAGE)`).
       4. Only after all checks pass on the raw `SQLRunner` does `_ClientBase.__init__` construct `self._meta_queue = self.queue(META_QUEUE_NAME)` and `self._state = SqlSidecarTautState(...)` (skipping `ensure_schema()`).
     - Thus even an **older-version broker-only target** (e.g. `meta.schema_version = '1'` without `taut_meta`, which `Queue.sidecar()` would otherwise migrate via `BackendAwareRunner.setup()`) fails closed with `NotInitializedError` before `Queue` or `BackendAwareRunner` is ever opened, leaving both SQLite files and PostgreSQL schemas byte-for-byte / row-for-row unchanged!
     - `_validate_candidate` in `taut-mcp` passes `install_schema=False` on **both** the read-only `--as` probe AND the persistent `TautClient`, mapping `NotInitializedError` to `WorkspaceFailed(generation, "validation", PROJECT_NOT_FOUND)`.

2. **Launch-time defaults (`McpLaunchDefaults`), content-free launch parse errors, single-resident default-workspace binding, and the per-call `null`/`""` matrix (`[MCP-3]`, `[MCP-4]`, `[MCP-10]`):**
   - `McpLaunchDefaults(workspace: str | None = None, token: str | None = None, as_name: str | None = None)` is parsed identically on `taut mcp` and `taut-mcp` via `taut_mcp.cli.configure_parser`.
   - Content-free launch parser errors (`cli.py` and `command.py`):
     - `configure_parser` installs a shared content-free `error` handler on the parser (for both `taut-mcp` and `taut mcp`):
       - Known fixed validation/option diagnostics (`--workspace must be an absolute UTF-8 directory path`, `--token requires --workspace`, `--token must be a non-empty UTF-8 continuity token`, `--as must match ^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$`, `argument --as: not allowed with argument --token`, `argument --token: not allowed with argument --as`, `argument --workspace: expected one argument`, `argument --token: expected one argument`, `argument --as: expected one argument`) are emitted verbatim as `<prog>: error: <message>\n` (exit `1`, zero stdout).
       - Any other `argparse` failure on the MCP tail (unrecognized options, `--flag=value`, unexpected positionals, or `surrogateescape` bytes) emits fixed `<prog>: error: invalid launch arguments; run '<prog> --help' for usage\n` (exit `1`, zero stdout).
     - On `taut mcp`, pre-verb root options before `mcp` are split by `[TAUT-8.1]`'s root dispatcher; `command.py` rejects `context.db_path`, `context.json`, `context.timestamps`, and `context.quiet` with fixed `CommandError("taut mcp does not accept --db, --json, --timestamps, or --quiet; use --workspace for a default workspace")` (exit `1`, zero stdout), and merges `context.as_name` / `context.continuity_token` when no second identity flag is present (emitting fixed `CommandError("taut mcp accepts at most one of --token or --as")` on duplicate/conflicting pre-verb + post-verb identity flags).
     - Neither `cli.py` nor `command.py` imports `server`, `_process_reactor`, or `_workspace_reactor` during `--help`, `--version`, or launch-argument validation.
   - Compact nullable schema properties (`build_tools(defaults)`) and `tools/list` cache scoping:
     - With `McpLaunchDefaults()` (no flags), `build_tools` produces the exact 21 `TOOLS` (`20,347` UTF-8 bytes, under `CEILING_BYTES = 21_000`) and `server.py` keeps `CacheHint(ttl_ms=300_000, scope="public")` on `tools/list`.
     - When `defaults.workspace is not None`, `"workspace"` uses compact Draft 2020-12 `{"description": ..., "type": ["string", "null"]}` and is omitted from `"required"` on `attach_workspace`, `detach_workspace`, and all 18 `DOMAIN_TOOL_NAMES` (`20,274` bytes).
     - When `defaults.token is not None` or `defaults.as_name is not None`, `"token"` uses compact `{"description": ..., "type": ["string", "null"]}` and is omitted from `"required"` on `attach_workspace` and all 18 `DOMAIN_TOOL_NAMES` (`20,366` bytes for identity-only; `20,215` bytes when combined with `--workspace`). `detach_workspace` never carries `"token"`.
     - Whenever any launch default is set (`defaults.has_any_default`), `server.py` sets `tools/list` to `CacheHint(ttl_ms=300_000, scope="private")` (`server/discover` and `resources/list` remain `public`).
   - Exact per-call `omitted` / `null` / `""` validation matrix:
     - When a launch default is **absent**, passing JSON `null` (`{"workspace": null, ...}` without `--workspace`, or `{..., "token": null}` without `--token`/`--as`) is rejected by schema validation before registry/filesystem/child work with `invalid tool arguments: invalid field 'workspace'; inspect the tool schema and retry` / `invalid field 'token'`.
     - On `attach_workspace` and all 18 `DOMAIN_TOOL_NAMES` when configured:
       - `"workspace"` omitted or `None` (`used_default_workspace = True`) -> routes to the single published `_Entry` where `entry.is_default_workspace` is `True`; if none is published yet, immediately fails at master preflight with `WORKSPACE_BUSY` if any active `_Candidate` has `candidate.is_default_workspace` or `candidate.locator == defaults.workspace` or `candidate.canonical_workspace == defaults.workspace`; otherwise enters candidate resolution with `locator = defaults.workspace` and `used_default_workspace = True`.
       - `"workspace": ""` -> never selects `defaults.workspace`; rejected on the master thread by `_validate_workspace_request` with `WORKSPACE_ABSOLUTE` before seat allocation or arbitration.
       - `"token"` omitted or `None` -> selects `defaults.token` (subject to default-workspace scoping: `require_default_workspace = True` whenever launch `--token` is used) or `defaults.as_name`.
       - `"token": ""` -> never selects `defaults.token` or `defaults.as_name`; rejected on the master thread by `_validate_workspace_request` (`if token is not None and token == "": raise WorkspaceToolError(IDENTITY_INVALID)`) before seat allocation, cap counting, or arbitration.
     - On `detach_workspace` when `defaults.workspace` is configured:
       - `"workspace"` omitted or `None` -> detaches the single published `_Entry` where `entry.is_default_workspace` is `True` (covering `ready`, `detaching`, `identity_lost`, `reactor_failed`, and validation-timeout tombstones); if none is published, returns `WORKSPACE_BUSY` if any `_Candidate` has `candidate.locator == defaults.workspace or candidate.canonical_workspace == defaults.workspace or candidate.is_default_workspace`, else idempotent `{"records": []}`.
       - `"workspace": ""` -> never selects the default workspace; runs exact string lookup (`""` absent -> idempotent `{"records": []}` without detaching a resident default workspace).
   - Single-resident default workspace latch, symlink-retarget rule, and `--as` selector arbitration (`R2.3` + `R3.1` fix):
     - `Bootstrap` carries `(generation, locator, token, as_name, configured_as_name, default_workspace, used_default_workspace, require_default_workspace)`, where `as_name` is set only when *this* request uses `--as` (`token is None`), while `configured_as_name` is `defaults.as_name` regardless of whether *this* request supplied an explicit `token` — so `_validate_candidate` always computes `matches_default_as` accurately (`True` when `as_name is not None` or when `configured_as_name` matches `member.name`/`member.aliases` by `route_key`)!
     - In `_resolve_candidate` on the child thread: if `bootstrap.used_default_workspace` is `True`, resolving `bootstrap.locator` once directly establishes `is_default_workspace = True` (avoiding double-resolution TOCTOU on `defaults.workspace`); otherwise, whenever `default_workspace is not None`, `_resolve_candidate` resolves `bootstrap.locator` AND checks whether `_resolve_workspace(default_workspace)` shares canonical path or `(st_dev, st_ino)` directory identity with it (`is_default_workspace: bool`, `False` if `default_workspace` fails resolution).
     - If `bootstrap.require_default_workspace` is `True` (request uses launch `--token`) and `not is_default_workspace`, `_resolve_candidate` emits `WorkspaceFailed(generation, "resolution", NON_DEFAULT_WORKSPACE_TOKEN_REQUIRED)` before `WorkspaceResolved` and before `GrantValidation`.
     - **Single-owner default-workspace reservation across validation & symlink retargeting (`[MCP-3]` freeze rule, `R3.1` fix):** At most **one** non-retiring validation-granted `_Candidate` (`phase == "validation"`) or published `_Entry` may hold `is_default_workspace == True` at any time. Helper `_has_other_default_owner(canonical, identity, exclude_generation=...)` returns `True` if any published `_Entry` OR any non-retiring `phase == "validation"` `_Candidate` for a different project (`not _same_workspace(...)`) already holds `is_default_workspace == True`. In `_on_resolved`, when `event.is_default_workspace` is `True` and `_has_other_default_owner(...)` is `True` (because a symlink passed to `--workspace` retargeted on disk while an earlier default validation or resident entry for Project A is active):
       - If `candidate.used_default_workspace` is `True` (caller omitted/nulled `workspace` to target the default project while Project A raced through resolution/validation across a symlink retarget to Project B), `_on_resolved` retires the candidate with `WORKSPACE_BUSY` (`workspace busy; retry after backoff`) and **zero `GrantValidation`** (never validating Project B with Project A's launch `--token` or `--as`).
       - Else if `candidate.require_default_workspace` is `True` (caller supplied explicit `workspace` and omitted/nulled `token` trying to apply launch `--token` to the retargeted project), `_on_resolved` retires the candidate with `NON_DEFAULT_WORKSPACE_TOKEN_REQUIRED` and **zero `GrantValidation`**.
       - Otherwise (caller supplied BOTH an explicit `workspace` AND an explicit `token` or launch `--as` for the second project), `_on_resolved` clamps `candidate.is_default_workspace = False` before `GrantValidation` so the second project validates/publishes as a non-default workspace and `is_default_workspace` remains unique across both overlapping validation and publication! If a `phase == "validation"` candidate later fails validation (`_retire_candidate`), clearing `candidate.is_default_workspace = False` releases the reservation; if it publishes ready (`_on_ready`) or times out into a canonical tombstone (`_candidate_timeout(..., "validation")`), `_Entry.is_default_workspace = True` retains the reservation until `detach_workspace` completes.
     - Both `_preflight_workspace` and `_on_resolved` apply the same strict two-branch selector predicate (`R3.2` fix), retiring any losing or idempotent alias candidate in `_on_resolved` with **zero `GrantValidation`**:
       1. If `require_default_workspace and not entry.is_default_workspace`: fail with `NON_DEFAULT_WORKSPACE_TOKEN_REQUIRED`.
       2. If `entry.status != "ready"`: fail with `self._entry_error(entry)`.
       3. **If `request_token is not None` (explicit per-call `token` or launch `--token`)**: compare **solely** `entry.token == request_token` (`True` -> idempotent `_workspace_record(entry)`; `False` -> `WORKSPACE_CONFLICT`, **never** consulting `entry.matches_default_as`, so passing Bob's explicit token against a resident Claude entry always conflicts!).
       4. **Else (`request_token is None`, request selects launch `--as`)**: check `entry.matches_default_as` (`True` -> idempotent `_workspace_record(entry)`; `False` -> `WORKSPACE_CONFLICT`).

3. **Bounded master-owned per-workspace command FIFO queue with synchronous admission & promotion pruning (`[MCP-5]`, `[MCP-6]`, `[MCP-8]`, `[MCP-11]`, `R2.2` fix):**
   - Each ready `_Entry` owns `active_command_id: int | None`, `command_future: asyncio.Future[_CommandCompletion] | None`, and `queued_commands: deque[_QueuedCommand]` bounded by `MAX_QUEUED_COMMANDS = 8` (1 active + 8 queued uncancelled commands = 9 concurrent commands per ready workspace).
   - Shared `_prune_cancelled_queued_commands(entry)` helper runs synchronously at the master serial point at the start of **all three** operations — `_execute_ready_tool` (before counting `len(entry.queued_commands) < MAX_QUEUED_COMMANDS`), `_promote_next_queued_command`, and `detach_workspace` — removing any item where `queued.canceled or queued.waiter.cancelled()` and cancelling `queued.future`.
   - Because `Task.cancel()` flips `waiter.cancelled() == True` synchronously before any done callback or coroutine unwinds:
     - Cancelling the 8th queued command immediately frees its FIFO slot for a new command admitted on the very same event-loop turn (no false `WORKSPACE_BUSY`!).
     - Cancelling a queued command immediately before `_on_command_outcome` runs never promotes or sends `RunWorkspaceCommand` to the child.
   - Fairness proof uses `channel_show` as Command 1 (which skips post-command `peek_inbox()` in `_refresh_after_command`) while injecting a notification wake during Command 1, proving `_publish_snapshot_if_due()`'s `peek_inbox()` runs on Turn 1 before Command 2 executes on Turn 2.
   - `_settle_commands(entry, error)` settles `entry.command_future` and all uncancelled `queued.future` entries on `identity_lost`, `reactor_failed`, or dead-owner reap; `aclose()` cancels all active and queued futures.

4. **Field-named schema validation diagnostics with zero value/key echo (`[MCP-5]`, `[MCP-10]`):**
   - `ToolValidationError(ValueError)` carries a server-constructed message checked in deterministic order:
     1. Non-`dict` `normalized` (or non-`str` key) -> `"invalid tool arguments (expected JSON object); inspect the tool schema and retry"`.
     2. Missing required property (in `schema.get("required", ())` order) -> `f"invalid tool arguments: missing required field '{req}'; inspect the tool schema and retry"`.
     3. Unknown property (`key not in schema_properties`) -> `"invalid tool arguments (unexpected property); inspect the tool schema and retry"` (**never** echoing the unknown key).
     4. Property-level failure (in `schema_properties` definition order): `f"invalid tool arguments: invalid field '{prop}[{err.path[1]}]'; inspect the tool schema and retry"` for array items, else `f"invalid tool arguments: invalid field '{prop}'; inspect the tool schema and retry"`.
     5. Schema-level cross-field failure (`list` `all=True, dms=True`) -> `"invalid tool arguments: conflicting fields 'all' and 'dms'; inspect the tool schema and retry"` (else `"invalid tool arguments; inspect the tool schema and retry"`).

5. **`#channel` normalization across `taut-mcp` and `taut search` (`[IAN-5.1]`, `[MCP-5]`, `[SRCH-4.1]`):**
   - `_tools.py`: `CHANNEL_PATTERN = r"^#?[a-z0-9][a-z0-9_-]{0,63}$"`, `CHAT_PATTERN = r"^#?[a-z0-9][a-z0-9_-]{0,63}(?:\.[0-9]{19})?$"`, `CHAT_OR_DM_PATTERN = r"^(?:#?[a-z0-9][a-z0-9_-]{0,63}(?:\.[0-9]{19})?|@[A-Za-z0-9][A-Za-z0-9_-]{0,63}|dm\.d_[a-z2-7]{26})$"`.
   - `taut/client/_searching.py`: `_validate_search_request` normalizes `channel_selectors` via `tuple(addressing.validate_chat_thread_name(channel, allow_subthread=False) for channel in channel_selectors)` and removes `#` rejection in `_validate_scope_syntax`.

### 3.2 Hidden Couplings Checked

- **`2026-11-10` Promoted `Replacement` Blocks (`bin/check-doc-paths`):** All 24 `Replacement` spans in `docs/plans/2026-11-10-upstream-port-runtime-hardening-and-theory-wave-plan.md` remain untouched.
- **Complete-Span `Replacement` Integrity (`R2.1`):** Every one of the **34** `Replacement` blocks in §4 (`5` in `02-taut-core.md`, `2` in `03-identity-addressing-notifications.md`, `2` in `06-search.md`, `2` in `10-taut-tui.md`, and `23` in `05-taut-mcp.md`) has its own subheading naming its exact inclusive 1-based line range `(L<start>–L<end>)` in the baseline spec file and replaces complete spans with zero truncated lines or cut backlinks.
- **Phase 1 `BUILTIN_SPECS` vs `test_dual_era_contract.py`:** Adding `"onboard"` to `INTENTIONALLY_UNEXPOSED_CLI_COMMANDS` and `[MCP-5]` restores structural CLI-to-MCP parity.
- **MCP Manifest Ceiling (`test_tools.py:3684`) & `tools/list` Cache Isolation (`server.py:240`):** Compact `type: ["string", "null"]` keeps all 4 launch modes at `20,215`–`20,366` bytes (`<= 21,000`), and `scope="private"` isolates launch-customized schemas.
- **Byte-for-Byte Kernel Sync (`tests/test_docs_references.py`):** Any edit to `docs/agent-kernel.md` is copied byte-for-byte to `taut/agent-kernel.md`.
- **Untouched User Worktree File:** `skills/call-agent/SKILL.md` is never modified, reverted, or staged.

### 3.3 Anti-Mocking Guidance

- All `whoami --show-token`, `TautClient(..., install_schema=False)` (including older-version broker-only fixtures), `taut search --channel '#general'`, and `taut-mcp` tests run against real SQLite and real Docker PostgreSQL 18 plus real stdio subprocesses across both `2025-11-25` and `2026-07-28` MCP SDK clients.

### 3.4 Rollback, Rollout, and Post-Deploy Signals

- **Zero Schema Migration:** No SQLite or PostgreSQL DDL or persisted row format changes; rollback is a pure code revert.

---

## 4. Strategy-A Spec Promotions (Slice 0 — 34 Complete-Span Blocks)

Each numbered block below names the exact inclusive 1-based line span `(L<start>–L<end>)` in the `8955636` baseline file that it replaces in full.

### 4.1 `docs/specs/02-taut-core.md` (5 blocks)

#### 4.1a `[TAUT-8.1]` — `whoami [--explain] [--show-token]` (`L1281–L1283`)

Replacement (`docs/specs/02-taut-core.md`):
```markdown
| `who [THREAD]` | Members and presence (thread members, or all members when bare). | 0; 1 error; 2 no such thread |
| `whoami [--explain] [--show-token]` | Resolved identity; with `--explain`, the evidence and rule; with `--show-token`, also includes the acting member's continuity token on stdout. Read-only selection ([IAN-3.3]). | 0 resolved; 1 error (incl. invalid or missing continuity token); 2 unrecognized |
| `rejoin [NAME_OR_ALIAS] [--token TOKEN]` | Associate the current process claim with the selected member ([IAN-3.4]). Target: name or alias if given, else `--token` (subcommand or global), else global `--as`; name/alias combined with any `--token` is an error. | 0; 1 error/collision/ambiguous selectors; 2 no such member/token |
```

#### 4.1b `[TAUT-8.2]` — `whoami --show-token` JSON field (`L1399–L1410`)

Replacement (`docs/specs/02-taut-core.md`):
```markdown
  - member objects (`who`, `whoami`, `rejoin`, `set name`): `member_id`,
    `name`, `aliases`, `kind`, `presence`, `last_active_ts`, `persona`
    (string or null); `whoami
    --explain` adds `explain` (object with the captured chain and the
    rule that matched; its internal layout is diagnostic, not a stable
    contract); `whoami --show-token` adds `token` (the member's stored
    continuity token string, or exits 1 if the member record has no stored
    continuity token);
  - member **creation** (whichever verb caused it) emits one extra
    member-object line *first* — the normal member fields (including
    `persona` when supplied at creation) plus the one-time `token`
    field and no `ts` — followed by the verb's primary object. Aside from
    that creation prelude, the token appears in CLI output only when
    explicitly requested with `whoami --show-token` (or in a full workspace
    `system dump`). Scripts must therefore select by field, not by line
    position, on paths that can create;
```

#### 4.1c `[TAUT-8.3]` — `TautClient.whoami(..., include_token=False)` (`L1602–L1610`)

Replacement (`docs/specs/02-taut-core.md`):
```markdown
`TautClient.peek_identity() -> Member` returns the client's selected existing
member through [IAN-3.3]'s read-only resolution. It raises the ordinary
identity or token error when no selected member resolves. It does not create,
heal, claim, touch activity, update anchor or fingerprint evidence, inspect
unread state, or mutate membership or cursor state. `TautClient.whoami(*,
explain: bool = False, include_token: bool = False) -> Member` uses this same
read-only selection contract (validating `bool` flags before resolution; when
`include_token=True`, populating `Member.token` from the stored member row or
raising `TokenError` when the row carries no continuity token). Success or failure preserves the
client's existing `last_created_member` and `last_candidates` diagnostic
objects exactly. The name is intentionally identity-oriented: continuity
tokens are selectors, not credentials.
```

#### 4.1d `[TAUT-8.3]` — Pre-broker-setup `TautClient(..., install_schema=True)` (`L1637–L1645`)

Replacement (`docs/specs/02-taut-core.md`):
```markdown
`TautClient(..., inherit_environment_identity: bool = True, install_schema: bool =
True)` controls constructor environment inheritance and schema installation.
`inherit_environment_identity` controls only the constructor's fallback to the
process-wide `TAUT_AS` and `TAUT_TOKEN` identity selectors: the default
preserves CLI and ordinary embedding behavior, while `False` ignores both
environment variables and uses only explicit `as_name=` and `token=` arguments
so long-lived multi-workspace embedders cannot inherit a process-wide identity.
`install_schema=True` preserves ordinary automatic sidecar schema installation
on an existing target; `install_schema=False` validates `bool` and inspects
SimpleBroker's metadata table and Taut's current sidecar schema version on a
short-lived raw backend runner (qualified to the configured PostgreSQL schema on
`postgres` so `search_path`'s `public` fallback cannot satisfy either check)
before opening `Queue` or running broker setup,
raising `NotInitializedError` without writing broker setup, schema migration, or
sidecar DDL on an uninitialized or broker-only SQLite or PostgreSQL target.
```

#### 4.1e `## Related Plans` (`L3235–L3237`)

Replacement (`docs/specs/02-taut-core.md`):
```markdown
- `docs/plans/2026-09-28-simplification-and-hot-path-plan.md` — binds one
  stable actor per CLI read and uses broker timestamp metadata for count-free
  thread listings; also revises watch failure and debug contracts.

- `docs/plans/2026-11-24-phase-2a-whoami-token-and-mcp-ergonomics-plan.md` —
  adds read-only `whoami --show-token` (`TautClient.whoami(...,
  include_token=False)`), pre-setup non-installing `TautClient(...,
  install_schema=False)`, optional launch-time `--workspace`/`--token`/`--as`
  defaults and bounded per-workspace command queuing on `taut-mcp`, `#channel`
  normalization across MCP schemas and `search`, and server-owned field-named
  MCP schema diagnostics.
```

### 4.2 `docs/specs/03-identity-addressing-notifications.md` (2 blocks)

#### 4.2a `[IAN-3.3]` — Read-only `whoami --show-token` (`L282–L297`)

Replacement (`docs/specs/03-identity-addressing-notifications.md`):
```markdown
`whoami` (including `--explain` and `--show-token`), `who`, and `list` use this read-only resolution.
`whoami` reports the selected member; `whoami --show-token` additionally
includes that member's stored continuity token on stdout (raising `TokenError`
and exiting 1 if the stored member row has no continuity token, without minting
or modifying one); `who` and `list` use the selected member
to drive their existing output; and `whoami --explain` also reports the rule
that selected the member (`--explain` and `--show-token` compose cleanly). None records a claim, heals an anchor, updates
activity, or creates a member. `whoami --explain` renders the captured evidence
and the rule in the unrecognized case too. An unrecognized `whoami --explain`
retains `UnrecognizedCallerError` and exit code 2. Its diagnostic keeps
`unrecognized caller` as the first record and the existing `or select...`
recovery record as the last, and inserts exactly one `identity evidence:
<canonical-json>` record immediately after the first. The canonical JSON is
the ordinary explanation object with `rule` equal to `unrecognized` and the
separate `host_rule` described in [IAN-3.2]. This diagnostic contract is the
same with or without global `--json`; `--quiet` suppresses it under the existing
error-rendering rule. The Python API raises `UnrecognizedCallerError` carrying
that explanation as an optional `explain` mapping; it does not fabricate a
`Member` result.
```

#### 4.2b `## Related Plans` (`L1081–L1085`)

Replacement (`docs/specs/03-identity-addressing-notifications.md`):
```markdown
- `docs/plans/2026-09-28-simplification-and-hot-path-plan.md`
- `docs/plans/2026-11-24-phase-2a-whoami-token-and-mcp-ergonomics-plan.md` —
  adds read-only `whoami --show-token` (`TautClient.whoami(...,
  include_token=False)`) so operators and harnesses can retrieve an existing
  member's continuity token without mutating claims or activity.
- `docs/plans/2026-09-24-identity-claim-boundary-plan.md` — narrows the
  step-4 anchor match so a parent agent cannot capture a child agent, specifies
  PATH-independent host-id derivation and its explicit fallback, and routes the
  observational identity verbs through read-only resolution.
```

### 4.3 `docs/specs/06-search.md` (2 blocks)

#### 4.3a `[SRCH-4.1]` — `#channel` normalization on search scope selectors (`L176–L182`)

Replacement (`docs/specs/06-search.md`):
```markdown
The CLI and Python API support these scope selectors:

- repeatable channel selector: one top-level channel name such as `general` or
  `#general` (normalized to the canonical bare channel name under [IAN-5.1];
  sub-threads and multiple leading `#` remain validation errors) and every
  currently registered child sub-thread
- repeatable DM selector: one existing `@name-or-alias` route or stable
  `dm.d_*` handle; a bare name without `@` is malformed
- all-DMs selector: every valid actor-accessible DM
```

#### 4.3b `## Related Plans` (`L697–L699`)

Replacement (`docs/specs/06-search.md`):
```markdown
## Related Plans

- `docs/plans/2026-11-24-phase-2a-whoami-token-and-mcp-ergonomics-plan.md` —
  normalizes optional single leading `#` on repeatable search channel selectors
  across `TautClient.search`, CLI `taut search --channel`, and `taut-mcp`
  `search.channels`.
- `docs/plans/2026-09-28-simplification-and-hot-path-plan.md`
```

### 4.4 `docs/specs/10-taut-tui.md` (2 blocks)

#### 4.4a `[TUI-7.1]` — `whoami --show-token` CLI-only disposition (`L548–L552`)

Replacement (`docs/specs/10-taut-tui.md`):
```markdown
The CLI's omitted-text and `-` stdin forms for `say` and `reply`, project-file
`onboard`, `join --recent`, and `whoami --show-token` are syntax-recognized but
CLI-only in the TUI. The TUI has no process-stdin command source, opens full
channel history natively, and keeps continuity tokens out of shared interactive
chrome; explicit `say ... --join` executes through the native send binding and
refreshes navigation.
```

#### 4.4b `## Related Plans` (`L1110–L1114`)

Replacement (`docs/specs/10-taut-tui.md`):
```markdown
## Related Plans

- `docs/plans/2026-11-24-phase-2a-whoami-token-and-mcp-ergonomics-plan.md` —
  records the [TUI-7.1] explicit CLI-only disposition for `whoami --show-token`.

- `docs/plans/2026-11-24-phase-1-sixty-second-onboarding-plan.md` — records the
  [TUI-7.1] command-mirror dispositions for `onboard` and `join --recent`
  (explicit CLI-only) and `say --join` (native send + navigation refresh).
```

### 4.5 `docs/specs/05-taut-mcp.md` (23 blocks)

#### 4.5a `[MCP-2]` — Workspace + token resolution & default detach (`L35–L43`)

Replacement (`docs/specs/05-taut-mcp.md`):
```markdown
Every identity-using workspace call resolves two values: an absolute
local workspace directory locator and an existing Taut continuity token (either
supplied explicitly in the tool call or inherited from explicit launch-time
`--workspace` and `--token` / `--as` server flags under [MCP-3]–[MCP-4]).
Together they are the application handle from which the server can
reconstruct the configured project and member binding after process loss.
The token is an identity-continuity selector, not authentication,
authorization, or a capability. It is never returned by MCP tools or placed in chat.
`detach_workspace` is the narrow exception: it removes process-local state
by exact published-canonical lookup (or the single resident default workspace bound
from launch `--workspace` when `workspace` is omitted or null), recognizes an exact hidden-candidate
string only to report busy, and reconstructs no Taut identity.
```

#### 4.5b `[MCP-3]` — Launch flags and content-free parser diagnostics (`L99–L103`)

Replacement (`docs/specs/05-taut-mcp.md`):
```markdown
The server starts with no resident workspace and can complete legacy
initialization or modern discovery in that state. It never infers an ambient
current working directory, `TAUT_DB`, `TAUT_AS`, or `TAUT_TOKEN`. Both launch
surfaces (`taut mcp` and `taut-mcp`) accept optional explicit launch-default
flags: `--workspace DIR` (an absolute UTF-8 local directory path) and at most
one of `--token TOKEN` (an existing non-empty UTF-8 continuity token; requires
`--workspace`) or `--as NAME_OR_ALIAS` (matching `[IAN-4.2]`'s member-name
pattern; resolves an existing workspace member read-only on first ensure). On
`taut mcp`, pre-verb `--db`, `--json`, `-t/--timestamps`, and `-q/--quiet` are
usage errors (exit 1 before protocol start); pre-verb `--as` or `--token` is
accepted when not combined with a second identity flag (pre-verb root-option
syntax before `mcp` remains governed by `[TAUT-8.1]`). On both `taut-mcp` and
`taut mcp`'s command-local parser, invalid launch flag combinations, malformed
`--workspace` / `--token` / `--as` values, and unrecognized or positional
arguments exit 1 on stderr with fixed content-free diagnostics and zero stdout,
never echoing a supplied token or untrusted argument value. When launch
defaults are omitted, workspace and identity selection arrive only in
workspace-scoped tool inputs.
```

#### 4.5c `[MCP-3]` — `tools/list` public vs private cache scope (`L176–L181`)

Replacement (`docs/specs/05-taut-mcp.md`):
```markdown
Modern `tools/list` and `resources/list` complete results are deterministic
and return `ttlMs: 300000`; `resources/list` advertises `cacheScope: "public"`,
while `tools/list` advertises `cacheScope: "public"` when no launch defaults are
configured and `cacheScope: "private"` when launch `--workspace`, `--token`, or
`--as` customizes the advertised input schemas. A complete read of
`taut://notifications/current` returns `ttlMs: 0` with
`cacheScope: "private"` because the aggregate changes independently of the
request. Legacy clients receive the equivalent application data through
their era's SDK-owned envelopes without modern cache fields.
```

#### 4.5d `[MCP-4]` — Resolution event payload including default-workspace match bit (`L233–L250`)

Replacement (`docs/specs/05-taut-mcp.md`):
```markdown
The candidate child first performs the same project/config resolution as a
`TautClient` created from that explicit directory, without constructing the
client or opening a database. It computes the OS-native `realpath` of the
directory owning the selected `.taut.db` or `.taut.toml`, removes a trailing
separator except for a filesystem root, verifies strict UTF-8, and records
the directory's `(st_dev, st_ino)` filesystem identity. A resolved canonical
string that fails strict UTF-8 returns the same fixed `workspace path is not
valid UTF-8; provide an absolute UTF-8 workspace path` result as an invalid
input locator and takes the ordinary
candidate rollback path. The pair is an
attachment-session deduplication key, not a persisted identifier. If both
values are zero or the platform cannot supply a usable identity, attachment
fails with `workspace directory identity unavailable; choose a workspace with
stable directory identity` rather than risk two
clients for case aliases of one project. It retains the
resolved config and target on the child thread and sends only immutable
canonical-path, directory-identity, backend-name, and default-workspace-match
boolean data to the master.
The master does not touch the resolved filesystem object.
```

#### 4.5e `[MCP-4]` — Non-installing `--as` and `--token` client construction (`L257–L264`)

Replacement (`docs/specs/05-taut-mcp.md`):
```markdown
After the master grants the candidate, the child constructs its core client
through `TautClient(broker_target=resolved_target,
broker_config=resolved_config, token=token,
inherit_environment_identity=False, install_schema=False)` (when `token` was
resolved through launch `--as NAME_OR_ALIAS`, the child first resolves that
existing member read-only on the same owner thread via a short-lived
`TautClient(broker_target=resolved_target, broker_config=resolved_config,
as_name=as_name, inherit_environment_identity=False,
install_schema=False).whoami(include_token=True)` call to obtain its stored
continuity token without running broker setup/migration, installing sidecar
DDL, creating a member, healing claims, or updating activity; an uninitialized
or broker-only target emits `workspace project not found; initialize Taut there
or choose another directory`, while a missing member or missing token emits
`workspace identity invalid; ensure the configured --as member exists or
provide a valid existing continuity token`). This is the [TAUT-3.2]/[TAUT-8.3]
resolved handoff and identity-isolation seam. The extension does not mutate
or inherit `cwd`, `TAUT_DB`, `TAUT_AS`, `TAUT_TOKEN`, or another
process-global selector and does not translate a PostgreSQL DSN into
`db_path`.
```

#### 4.5f `[MCP-4]` — `detach_workspace` locator and default-workspace semantics (`L385–L394`)

Replacement (`docs/specs/05-taut-mcp.md`):
```markdown
`detach_workspace` deliberately has narrower locator semantics. It accepts
only the exact canonical identifier exposed by ensure or
`list_workspaces` (or an omitted/null `workspace` when launch `--workspace` is
configured, which selects the single published entry matching that default
project — including `ready`, `detaching`, `identity_lost`, `reactor_failed`,
and validation-timeout tombstones — or reports `workspace busy; retry after
backoff` if a hidden candidate for that default project is active, or returns
an idempotent empty result if unattached; an explicit empty string `""` never
selects the default workspace), performs no filesystem/config resolution, and treats an
unrecognized string as an idempotent miss. Before a candidate publishes, an
exact string match against that hidden candidate's immutable original locator
or already-stored canonical string returns `workspace busy; retry after
backoff`; it neither detaches nor resolves. Exact published-canonical lookup
takes precedence over hidden-string lookup. This makes domain calls
reconstructable without turning cache cleanup into another expensive setup
attempt.
```

#### 4.5g `[MCP-4]` — Ready idempotence, single-resident default freeze, and `null`/`""` rules (`L500–L519`)

Replacement (`docs/specs/05-taut-mcp.md`):
```markdown
Ensuring a `ready` canonical workspace with the same token (or a matching
launch `--as` binding, recorded on the resident entry from its validated member
route keys regardless of whether first attachment used `--as` or an explicit
token) is idempotent and returns the existing entry without opening a
client or revalidating the token; a losing or idempotent alias candidate
retires at resolution arbitration without receiving a validation grant. A
different token or non-matching `--as` selector conflicts until the workspace
is detached. A
degraded or detaching entry must finish detachment before any reattachment;
no token can create a second generation while an earlier child might still
be live. Tokens are scoped to their selected Taut database; equality of
token text across databases has no cross-workspace meaning. The process
registry retains the exact resolved continuity token string on a hidden or ready owner and
compares ordinary string equality, without trimming or normalization.
Publication transfers that owner value to the ready entry. Retirement
releases it with the owning entry. Expected diagnostics and protocol results
do not echo tokens. SDK- or host-owned copies and caught internal traceback
frames remain outside Taut's process-state retention contract.

One immutable member id is bound independently to each ready resident
workspace. Member rename does not change it. `attach_workspace` and every
CLI-shaped schema carry `workspace` and `token` properties (required `string`
by default; `workspace` becomes optional `["string", "null"]` when launch
`--workspace` is configured, and `token` becomes optional `["string", "null"]`
when launch `--token` or `--as` is configured) and no per-tool name, member id,
or alternative identity selector. Only omitted or JSON `null` values inherit
launch defaults; explicit empty strings `""` fail master request validation
(`workspace path must be absolute; provide an absolute workspace directory` for
`workspace: ""` and `workspace identity invalid; provide a valid existing
continuity token` for `token: ""`) before seat allocation or arbitration.
Whenever launch `--workspace` is configured (whether paired with `--token`,
`--as`, or explicit per-call tokens), at most one validation-granted candidate
or published entry may hold the default-workspace binding at a time (computed
on the child resolution thread from canonical path or `(st_dev, st_ino)`
directory identity, including symlinks and descendant directories regardless of
which spelling attached first, with zero master-thread filesystem I/O): if a
symlink passed to `--workspace` retargets on disk while an earlier default
validation or resident entry remains active, that binding stays frozen until
validation fails or the entry is detached — at master preflight, an
omitted/null-`workspace` call routes directly to a published default entry when
one exists, or — only when no default entry is published — returns `workspace
busy; retry after backoff` if an active candidate already holds that default
reservation or matches the launch locator, and if an
omitted/null-`workspace` call entered candidate resolution earlier and resolves
to a retargeted project after another validation-granted candidate or published
entry owns the default binding, resolution arbitration retires it with
`workspace busy; retry after backoff` without granting validation. When launch
`--token` is configured for `--workspace`, an omitted or null per-call `token`
applies only to that single default workspace; supplying an explicit `workspace`
for any other project (including a retargeted project while another validation
or published entry owns the default binding) with omitted/null `token` fails
before validation grant with `workspace token required for non-default
workspace; supply token or use the configured default workspace`.
`detach_workspace` carries only `workspace`
(optional `["string", "null"]` when launch `--workspace` is configured) because
it performs no Taut identity operation.
```

#### 4.5h `[MCP-4]` — `join`/`leave` vs identity bootstrap (`L584–L588`)

Replacement (`docs/specs/05-taut-mcp.md`):
```markdown
`join THREAD` and `leave THREAD` change Taut thread membership, not workspace
residency or member identity. MCP offers no ambient selector-free process
inference, per-call `--as`, `join --new`, `rejoin`, or caller-selected member
or token creation. Each identity-using call resolves an existing member by
continuity token (or read-only launch `--as` selection of an existing member).
Identity bootstrap remains an ordinary Taut CLI/Python task.
```

#### 4.5i `[MCP-5]` — Intentionally unexposed CLI commands including `onboard` (`L689–L697`)

Replacement (`docs/specs/05-taut-mcp.md`):
```markdown
`init`, `onboard`, `watch`, `rejoin`, `summon`, `dismiss`, extension-discovered verbs,
and future CLI verbs are not registered automatically. `init`, `onboard`, and identity
bootstrap happen outside MCP; the aggregate notification resource owns the
MCP notification-observation and wake use case, not the CLI `watch` command's
consuming full-chat live-follow behavior; `rejoin` conflicts with immutable
per-workspace identity;
and extension verbs require a later explicit protocol design. Workspace
attachment uses explicit names so it cannot be confused with Taut thread
`join` and `leave`.
```

#### 4.5j `[MCP-5]` — 21-row tool input table, `#channel` patterns, and field-named schema diagnostics (`L789–L825`)

Replacement (`docs/specs/05-taut-mcp.md`):
```markdown
In the table below, `workspace` is `string` and required by default, becoming
`string or null` and optional when launch `--workspace` is configured; `token`
is `string` and required by default on `attach_workspace` and all 18 CLI-shaped
tools, becoming `string or null` and optional when launch `--token` or `--as`
is configured (`detach_workspace` never accepts `token`).

| Tool | Input properties | Default required (`workspace`/`token` optional when configured at launch) | MCP-specific rule |
|------|------------------|----------|-------------------|
| `attach_workspace` | `workspace: string`, `token: string` | both | eagerly enters [MCP-4]'s shared ensure lifecycle; `workspace` is an absolute directory locator; token/launch `--as` must resolve an existing member and token is never echoed |
| `detach_workspace` | `workspace: string` | `workspace` | exact canonical resident identifier for removal (or omitted/null for the resident launch `--workspace`); exact hidden original/stored-canonical string reports busy; performs no filesystem or identity resolution; every other miss is idempotent success |
| `list_workspaces` | no properties | none | returns all published process-local entries in [MCP-7]'s lexicographic Unicode-code-point order of canonical workspace path |
| `join` | `workspace: string`, `token: string`, `thread: string`, `persona: string or null` | `workspace`, `token`, `thread` | lazily ensures the workspace if needed; calls `join(..., new=False)`; no other identity selector |
| `leave` | `workspace: string`, `token: string`, `thread: string` | all | lazily ensures the workspace if needed; ordinary channel/sub-thread membership semantics |
| `channel_show` | `workspace: string`, `token: string`, `channel: string` | all | lazily ensures the workspace if needed; calls `TautClient.get_channel(channel)` without actor resolution, activity, queue, or cursor effects after binding |
| `channel_topic` | `workspace: string`, `token: string`, `channel: string`, `topic: string or null` | all | lazily ensures the workspace if needed; calls `TautClient.set_channel_topic(channel, topic)` directly; null clears and current membership is required |
| `set_name` | `workspace: string`, `token: string`, `name: string` | all | lazily ensures the workspace if needed; no member-id argument |
| `say` | `workspace: string`, `token: string`, `target: string`, `text: string` | all | lazily ensures the workspace if needed; no stdin sentinel; core blank/size rules apply; `@route` may create a DM, while exact `dm.d_*` requires an existing actor-accessible conversation and never creates or heals one |
| `reply` | `workspace: string`, `token: string`, `thread: string`, `msg_id: string`, `text: string` | all | lazily ensures the workspace if needed; exact 19-digit pattern; calls `TautClient.reply(thread, msg_id, text)` |
| `message_show` | `workspace: string`, `token: string`, `msg_id: string` | all | lazily ensures the workspace if needed; exact 19-digit pattern; calls `TautClient.show_message(msg_id)`; searches only current registered chat memberships and may advance the located high-water cursor |
| `message_delete` | `workspace: string`, `token: string`, `msg_id: string` | all | lazily ensures the workspace if needed; exact 19-digit pattern; calls `TautClient.delete_message(msg_id)`; may delete the acting author's own ordinary row after leave and returns no source content |
| `message_react` | `workspace: string`, `token: string`, `msg_id: string`, `reaction: string` | all | lazily ensures the workspace if needed; exact 19-digit id and stable slug patterns; calls `TautClient.react_to_message(msg_id, reaction)` directly; runtime validates the resident client's configured list |
| `read` | `workspace: string`, `token: string`, `thread: string or null`, `limit: integer` | `workspace`, `token` | lazily ensures the workspace if needed; default limit 100; range 1..1,000; explicit DM selectors follow [TAUT-7.8]; null/omitted keeps bare joined-thread behavior; each selected queue has its own limit and cursor advance |
| `inbox` | `workspace: string`, `token: string`, `limit: integer` | `workspace`, `token` | lazily ensures the workspace if needed; default 1,000; range 1..1,000 |
| `log` | `workspace: string`, `token: string`, `thread: string`, `since: string, integer, or null`, `limit: integer` | `workspace`, `token`, `thread` | lazily ensures the workspace if needed; default limit 100; range 1..1,000; DM log is actor-scoped, cursor-neutral, and activity-neutral |
| `search` | `workspace: string`, `token: string`, `query: string`, `channels: array[string]`, `direct_messages: array[string]`, `all_direct_messages: boolean`, `from_member: string or null`, `kinds: array[message\|notice\|foreign]`, `before: string or null`, `limit: integer`, `reindex: boolean` | `workspace`, `token`, `query` | lazily ensures the workspace; freezes every selector array to a tuple; calls `TautClient.search` once with defaults `[]`, `[]`, false, null, `[]`, null, 50, false; adds no retry or post-filter |
| `list` | `workspace: string`, `token: string`, `all: boolean`, `dms: boolean` | `workspace`, `token` | lazily ensures the workspace if needed; both booleans default false; `all && dms` is rejected before child dispatch; selects the public list API with `include_unread_counts=False` |
| `channel_rename` | `workspace: string`, `token: string`, `old_name: string`, `new_name: string` | all | lazily ensures the workspace if needed; channel rename only |
| `who` | `workspace: string`, `token: string`, `thread: string or null` | `workspace`, `token` | lazily ensures the workspace if needed; retains core read-only selection and computed-presence semantics |
| `whoami` | `workspace: string`, `token: string` | both | lazily ensures the workspace if needed; fixed `explain=False, include_token=False`; read-only selection does not touch activity or heal a claim |

The application compiles one Draft 2020-12 validator from each exact
advertised input schema and validates `tools/call` arguments. Top-level channel
and chat-thread string patterns (`join.thread`, `leave.thread`, `reply.thread`,
`read.thread`, `log.thread`, `search.channels[]`, `channel_show.channel`,
`channel_topic.channel`, `channel_rename.old_name`, `channel_rename.new_name`,
and `who.thread`) accept an optional single leading `#` (`^#?[a-z0-9][a-z0-9_-]{0,63}$`,
plus optional `.[0-9]{19}` only on sub-thread-capable `leave.thread`,
`read.thread`, `log.thread`, and `who.thread`), normalized by core
[IAN-5.1] addressing to canonical bare queue names. If the SDK
supplies omitted `arguments` as `None`, the shared adapter
normalizes it to `{}` before validation; no other value is coerced.
`list_workspaces` therefore accepts omitted or explicit-empty arguments,
while a tool with required properties returns the ordinary schema-invalid
result for either form. A schema-invalid known-tool call returns a
`CallToolResult` with
`isError: true`, no `structuredContent`, and exactly one text content block
beginning with `invalid tool arguments` and ending with `; inspect the tool
schema and retry` (naming at most a deterministic server-owned schema field
such as `missing required field 'token'`, `invalid field 'msg_id'`, `invalid
field 'channels[0]'`, `conflicting fields 'all' and 'dms'`, `(unexpected
property)`, or `(expected JSON object)`). It never echoes any caller-supplied
argument value, caller-supplied unknown property key, or raw validator
exception. An unknown tool, malformed
MCP envelope, or invalid protocol metadata remains an SDK-owned protocol
error, not this tool result.
```

#### 4.5k `[MCP-5]` — Bounded per-workspace FIFO admission & pruning (`L859–L878`)

Replacement (`docs/specs/05-taut-mcp.md`):
```markdown
Each ready workspace has one active parent command slot plus a bounded FIFO
queue of up to eight waiting CLI-shaped commands (`MAX_QUEUED_COMMANDS = 8`,
for at most nine concurrent in-flight CLI-shaped calls per ready workspace).
Before counting queued depth, promoting the next command, or checking detach
busy state, the master synchronously prunes any queued item whose request
waiter has already been cancelled (`waiter.cancelled()`). When the active slot
is free, an admitted command dispatches immediately to the child; when occupied
and fewer than eight uncancelled commands are queued, the frozen command waits
in FIFO order on the master reactor and promotes only after the preceding
command's completion installs its post-command snapshot; when eight uncancelled
commands are already queued, a tenth concurrent call for that workspace is
rejected immediately with an `isError` result `workspace busy; retry after
backoff`. Calls for different
workspaces may run concurrently. `attach_workspace` and `detach_workspace`
perform their reservation/status transitions without awaiting at the same
master serial point (`detach_workspace` rejects with `workspace busy; retry
after backoff` whenever a command is active or an uncancelled command is queued
on that workspace). There is no separate process-wide lifecycle lock or
lifecycle-busy state; after the transition, each handler waits only on its
selected child's future. A hidden candidate retains only its own per-path
reservation, so one slow workspace cannot delay lifecycle work for another.
`list_workspaces` and the cached aggregate resource do not enter a parent
admission slot. Every registry transition, generation install/retirement,
ordinary-tool routing lookup, and child-slot/FIFO reservation occurs at one
non-awaiting master-thread serial point. A CLI-shaped tool is routable only
when the entry is `ready`; lookup, status check, cancelled-waiter prune, and
slot or FIFO admission are one atomic admission step. Detach marks an entry
`detaching` at the same serial point before it requests child stop.
`list_workspaces` snapshots only fully published entries at that serial point,
so neither it nor ordinary routing observes a half-published attach. The
applicable admission bound is checked at this serial point after request
validation. There is no process-wide request quota; per-workspace bounded FIFO
queues and the resident cap remain admission bounds.
```

#### 4.5l `[MCP-5]` — Synchronous cancel-while-queued vs active cancel (`L886–L916`)

Replacement (`docs/specs/05-taut-mcp.md`):
```markdown
An admitted command envelope carries its command id. If its MCP request is
canceled or the transport disconnects while the command is still waiting in the
master's per-workspace FIFO queue before dispatch to the child, its request
waiter becomes cancelled synchronously at `Task.cancel()` time: admission
pruning, the waiter's done callback, and FIFO promotion all check
`waiter.cancelled()` at the master serial point, removing the entry without
sending any child control, touching Taut state, consuming a slot against later
admissions, or disturbing remaining FIFO entries even if an admission or
completion drain runs before the request task unwinds. Once dispatched to
the active slot, the master enqueues a cancel-control
envelope with that id and issues only the ordinary payload-free child wake.
On each wake the child drains the inbound queue through `queue.Empty` into
child-owned pending state before selecting work. The instant that drain first
observes `queue.Empty` with an uncanceled selected command is its start
boundary. Before crossing it, a matching cancel envelope prevents every
`TautClient` call and makes the child emit one fixed canceled/no-op completion
for that command id. The master frees the slot through the normal completion
order and discards the Taut outcome. A cancel enqueued after the child has observed that empty queue is
late even if the Python call has not yet begun; the child ignores it as stale
after the command's single completion. This queue order, rather than wall-
clock intent, defines cancel-before-start without cross-thread reactor-state
reads. Once a command crosses the start boundary, the process reactor
shields and awaits the child completion event; cancellation or disconnect is
not a rollback
boundary, so a mutation may commit even when its response cannot be
delivered. Every admitted CLI-shaped command follows this fixed master-thread
completion order: await the child event; if its generation is still current,
install the outcome's status and notification snapshot and recompute the
aggregate; clear the active slot and promote the next uncancelled FIFO-queued
command (if any); then either hand the outcome to a
live transport or discard it after cancellation/disconnect. The workspace remains
busy through snapshot installation even after its requester cancels.
A caller must inspect the selected workspace's current Taut
state before retrying an interrupted consuming or mutating call. SDK
cancellation behavior, including the absence of a canceled stdio response, must be proven
at the stdio protocol boundary. `channel_show` carries the child's already
cached notification snapshot instead of calling `peek_inbox()` after the
metadata read; every other CLI-shaped command carries a new post-command
snapshot. This narrow exception preserves `channel_show`'s actor-free,
sidecar-only contract without changing aggregate ordering.
```

#### 4.5m `[MCP-5]` — Terminal settlement across active and queued commands (`L918–L928`)

Replacement (`docs/specs/05-taut-mcp.md`):
```markdown
A current-generation command outcome normally settles its active parent command
slot and promotes the next uncancelled FIFO-queued command, if any. If the child instead reports terminal `identity_lost` or
`reactor_failed` status, or its owner thread exits, while the active slot or
FIFO queue is non-empty, the process reactor treats the terminal event as the
completion for the active command and every uncancelled queued command on that workspace:
it installs the terminal status and
empty snapshot, synthesizes the corresponding fixed routing error outcome for
each pending future, clears the active slot and FIFO queue, and responds or discards in the same fixed
order. A later outcome for a settled command id is ignored. Thus a known child fault cannot leave
queued callers hung or detach permanently rejected as busy. A still-live child blocked inside a
synchronous call emits no terminal event and remains the explicit
process-restart case in [MCP-11].
```

#### 4.5n `[MCP-6]` — Fixed content-free ensure errors, complete routing matrix, and detach lookup prose (`L1124–L1159`)

Replacement (`docs/specs/05-taut-mcp.md`):
```markdown
Any identity-using caller that starts ensure may receive the fixed
content-free path/config/identity errors: `workspace path is not valid UTF-8;
provide an absolute UTF-8 workspace path`, `workspace token is not valid
UTF-8; provide a valid existing UTF-8 continuity token`, `workspace path must
be absolute; provide an absolute workspace directory`, `workspace project
not found; initialize Taut there or choose another directory`, `workspace
directory identity unavailable; choose a workspace with stable directory
identity`, `workspace configuration or backend unavailable; fix the
workspace configuration or backend and retry`, `workspace identity invalid;
provide a valid existing continuity token`, `workspace identity invalid;
ensure the configured --as member exists or provide a valid existing
continuity token`, `workspace token required for non-default workspace; supply
token or use the configured default workspace`, `workspace attachment failed;
use list_workspaces before retrying`, `workspace resolution timed out; use
list_workspaces then restart if warned`, `workspace attach timed out; use
list_workspaces then detach`, and `workspace already attached; detach to
replace token`. A detach that misses its child deadline returns `workspace
detach timed out; retry detach after backoff`. These errors never echo path
or token.

The registry/status routing matrix is normative:

| Observed state | Identity-using caller with same token | Identity-using caller with different token | `detach_workspace` input |
|----------------|---------------------------------------|--------------------------------------------|--------------------------|
| missing | begin shared ensure if a cap seat is available; a CLI-shaped command dispatches only after publication | same | successful empty no-op without filesystem or identity resolution |
| hidden candidate | `workspace busy; retry after backoff` | `workspace busy; retry after backoff` | exact hidden original/stored-canonical string (or omitted/null matching a hidden default workspace) returns `workspace busy; retry after backoff`; every other string is a missing no-op |
| `ready`, parent admission slot free | CLI-shaped command dispatches immediately; attach returns existing record | `workspace already attached; detach to replace token` | begin one detach |
| `ready`, active slot occupied (`< 8` queued) | CLI-shaped command queues in FIFO order; attach returns the existing record | `workspace already attached; detach to replace token` | `workspace busy; retry after backoff` |
| `ready`, active slot + 8 FIFO slots full | CLI-shaped command returns `workspace busy; retry after backoff`; attach returns the existing record | `workspace already attached; detach to replace token` | `workspace busy; retry after backoff` |
| `detaching` | `workspace busy; retry after backoff` | same | `workspace busy; retry after backoff`; do not send another stop/wake |
| `identity_lost` | `workspace identity lost; detach and reattach` | same | begin detach; no token is required |
| `reactor_failed` | `workspace reactor failed; detach and reattach` | same | run [MCP-4]'s bounded retry-detach; no token is required |
| validation-timeout tombstone | `workspace attach timed out; use list_workspaces then detach` | same | run [MCP-4]'s bounded retry-detach; no token is required |

Attach and CLI-shaped calls accept any absolute locator (or omit/null
`workspace` when launch `--workspace` is configured) and may enter resolution.
`detach_workspace` first performs exact published-canonical lookup (or selects
the single published default-workspace entry when `workspace` is omitted/null
under launch `--workspace`), then checks hidden-candidate strings (or a hidden
default-workspace candidate when omitted/null) only to report busy. Callers
otherwise use the canonical identifier returned by ensure or `list_workspaces`
for removal. It never resolves an alias on the filesystem merely to remove
cached state.
```

#### 4.5o `[MCP-9]` — Advisory instructions rules 2 and 3 (`L1497–L1505`)

Replacement (`docs/specs/05-taut-mcp.md`):
```markdown
2. Treat the continuity token as an opaque identity-continuity selector, not
   authentication, authorization, or an added security boundary. Pass an
   intentionally supplied absolute workspace locator and its existing token
   on `attach_workspace` and every CLI-shaped tool call (unless omitted to use a
   server-configured launch default); never invent the token
   or place it in chat.
3. Preserve and reuse the canonical workspace returned by a successful
   ensure or `list_workspaces`. A CLI-shaped tool can lazily establish the
   same retained client/reactor after process restart. `detach_workspace`
   takes only that exact canonical identifier (or omits `workspace` when a
   launch default workspace is configured) and removes process-local state.
```

#### 4.5p `[MCP-9]` — Advisory instruction rule 9 (`L1523–L1525`)

Replacement (`docs/specs/05-taut-mcp.md`):
```markdown
9. Treat the resource as a repeatable view. For one-time handling, call
   `inbox` with the listed workspace and its token (or omit configured launch
   defaults for that workspace) and handle only records
   returned by that consuming call.
```

#### 4.5q `[MCP-10]` — Launch-flag boundary vs ambient environment (`L1579–L1591`)

Replacement (`docs/specs/05-taut-mcp.md`):
```markdown
Taut's trust model remains [TAUT-9]. Storage access is the security boundary. A
continuity token is an opaque identity-continuity selector inside its selected
workspace. It is not a remote-authentication credential, an access-control
token, or an additional security boundary. Possession can select an existing
identity through Taut's public continuity paths, so a deployment may still
choose to treat it as sensitive application data. Supplying it as an MCP tool
argument can expose it to the client, model context, or host transcript;
`taut-mcp` does not claim to prevent or redact those host-owned copies. The
local stdio boundary does not authorize a remote listener. This contract
defines no ambient `TAUT_TOKEN` inheritance, token-file, or multi-workspace
launch map for the MCP extension; launch defaults are limited to the single
explicit `--workspace` and `--token`/`--as` CLI flags in [MCP-3]. A future non-transcript channel would need its own workspace-
keying, file-authority, redaction, and host-compatibility contract; it is not
inferred from core CLI environment rules.
```

#### 4.5r `[MCP-10]` — Bounded per-workspace command FIFO, rate bounds, and large-frame continuity (`L1624–L1639`)

Replacement (`docs/specs/05-taut-mcp.md`):
```markdown
The master serial point and bounded per-workspace command FIFO in [MCP-5]
execute at most one synchronous command at a time per workspace (queueing up to
eight waiting commands in FIFO order before returning busy) while allowing
different workspaces to progress concurrently.

There is no process-wide request-rate bucket. Repeated reads of the cached
notification resource do not consume an admission quota for later tool calls.
The per-workspace bounded command queue and resident cap remain enforced.
Core message-size, name, limit, and text validation remains authoritative.
MCP framing remains SDK-owned and Taut adds no frame-size limit. A real stdio
continuity probe sends one newline-delimited, schema-invalid JSON-RPC tool-call
frame containing an unknown string argument of at least 1,048,576 UTF-8 bytes.
The server returns the fixed schema-invalid tool result with no traceback or
echoed payload, then answers a following valid `list_workspaces` request on
the same connection. This is a large-frame continuity floor, not a declared
maximum; if the supported SDK later adds a smaller documented limit, revise
this contract before upgrading it.
```

#### 4.5s `[MCP-12]` & `## Related Plans` — Verification expectations and plan backlink (`L1778–L1786`, `L1823–L1825`, `L1848–L1859`, `L2098–L2106`, `L2252–L2258`)

> Note: 4.5s1–4.5s5 below are five individual complete-bullet spans counted in the 34-block total (`5` in `02` + `2` in `03` + `2` in `06` + `2` in `10` + `18` in `4.5a–r` + `5` in `4.5s1–s5` = **34 blocks**).

##### 4.5s1 `[MCP-12]` — Manifest and field-named validation proof (`L1778–L1786`)

Replacement (`docs/specs/05-taut-mcp.md`):
```markdown
- one default manifest/schema snapshot proves the same exact 21 tools for legacy and
  modern discovery; without launch defaults, `attach_workspace` and all 18 CLI-shaped schemas require
  both `workspace` and `token`, `detach_workspace` requires only exact
  canonical `workspace`, and `list_workspaces` remains empty-input; across all
  four launch-default modes (none, workspace-only, identity-only, and both),
  configured properties become optional `["string", "null"]` while preserving
  explicit overrides and staying within the 21,000-byte manifest ceiling;
- malformed, extra, wrong-type, pattern, range, and cross-field-invalid tool
  input is rejected by the one application validator before registry
  inspection, filesystem work, or child dispatch in both eras; each
  known-tool failure is a single-text `isError` result naming at most the
  deterministic server-owned schema field without echoing caller-supplied
  values or unknown keys, while unknown
  tools and malformed protocol input remain protocol errors;
```

##### 4.5s2 `[MCP-12]` — `tools/list` public vs private cache-scope proof (`L1823–L1825`)

Replacement (`docs/specs/05-taut-mcp.md`):
```markdown
- modern tools/list and resources/list are deterministic and advertise
  `ttlMs: 300000` (`resources/list` `cacheScope: "public"`; `tools/list`
  `cacheScope: "public"` without launch defaults and `cacheScope: "private"`
  when launch defaults are configured); current-notifications read
  advertises `ttlMs: 0`, `cacheScope: "private"`;
```

##### 4.5s3 `[MCP-12]` — 21,000-byte ceiling across all launch modes (`L1848–L1859`)

Replacement (`docs/specs/05-taut-mcp.md`):
```markdown
- exact tool-description, annotation, input-schema, and successful-output-
  schema snapshots for every [MCP-5] tool, including every property description, the `records`/optional-`warnings`
  result object, omission of `outputSchema`, rejection of additional
  properties, a serialized tool-manifest size ceiling of 21,000 bytes across
  all launch-default modes, and
  canonical text/structured parity; state probes confirm that `log` and
  `list_workspaces` are observational, `message_show` and `read` advance chat
  cursors, `message_react` advances its cursor and reports the intended
  audience without claiming delivery, `message_delete` removes only its
  eligible exact row, `inbox`
  claims pointers, and `list`/`who`/`whoami` retain their declared read-only
  identity behavior; attach validation reads an existing member without identity,
  claim, activity, or anchor mutation
```

##### 4.5s4 `[MCP-12]` — Bounded FIFO, admission pruning, and `channel_show` fairness proof (`L2098–L2106`)

Replacement (`docs/specs/05-taut-mcp.md`):
```markdown
- master-thread process-reactor ownership plus one owner thread/client per
  child, including child-thread-only attachment resolution and validation;
  atomic registry/status/generation routing admission; bounded per-workspace
  FIFO command queueing (1 active + up to 8 queued) with immediate busy
  rejection at the 10th concurrent call and synchronous cancel-while-queued
  pruning across admission, promotion, and detach in all scheduler orders;
  different-workspace parallel progress; notification service
  before the next queued command executes; fairness between short commands; atomic result-plus-
  snapshot completion before promoting the next queued command; rejection of stale-generation events; synthesized
  admission settlement across active and queued commands on terminal identity loss, child fault, or owner-thread
  exit; late-outcome suppression; and proof that a long child call does not
  block MCP framing, lifecycle work, or another child
```

##### 4.5s5 `## Related Plans` (`L2252–L2258`)

Replacement (`docs/specs/05-taut-mcp.md`):
```markdown
## Related Plans

- `docs/plans/2026-11-24-phase-2a-whoami-token-and-mcp-ergonomics-plan.md` —
  adds optional launch-time `--workspace`/`--token`/`--as` defaults (with
  pre-setup non-installing `TautClient(..., install_schema=False)` validation,
  compact nullable schemas, and private `tools/list` cache scoping), bounded
  per-workspace command FIFO queueing (`MAX_QUEUED_COMMANDS = 8`), `#channel`
  schema normalization, `onboard` CLI-parity accounting, and server-owned
  field-named schema validation diagnostics.
- `docs/plans/2026-09-28-mcp-rate-prose-and-static-proof-plan.md` — removes
  stale rate-state and charge claims after the process bucket's removal.
- `docs/plans/2026-09-28-simplification-and-hot-path-plan.md` — simplifies
  resident token equality and removes process-wide request quotas while
  retaining per-workspace admission and the resident cap.
```

---

## 5. Implementation Slices (Red-Green TDD)

Independent Tier-1 `codex` reviews run before Slice 0 (this plan review) and after Slice 2 completion (post-implementation review covering all slices, specs, tests, and docs).

### Slice 0: Spec Promotion & Gate Verification
- Apply all **34** `Replacement` blocks in §4 (`4.1a–e`, `4.2a–b`, `4.3a–b`, `4.4a–b`, `4.5a–r`, `4.5s1–s5`) by their exact inclusive 1-based line ranges across `docs/specs/02-taut-core.md`, `docs/specs/03-identity-addressing-notifications.md`, `docs/specs/06-search.md`, `docs/specs/10-taut-tui.md`, and `docs/specs/05-taut-mcp.md`.
- Update `Status: promoted` and `Promotion baseline: Slice 0 spec-promotion applied atop 8955636` in `docs/plans/2026-11-24-phase-2a-whoami-token-and-mcp-ergonomics-plan.md` and `docs/plans/README.md`.
- Verify `uv run python bin/check-plan-status-index && uv run python bin/check-doc-paths && uv run python bin/check-cli-claims` exit `0`.

### Slice 1: `TautClient.whoami(..., include_token=False)`, Pre-Setup `TautClient(..., install_schema=False)`, CLI `taut whoami --show-token`, TUI CLI-Only Guard, and `search` `#channel` Normalization
- **RED tests first:**
  - `tests/test_public_api.py`, `tests/test_client.py`, `tests/test_shared_contract.py`, and `extensions/taut_pg/tests/`:
    - `TautClient.whoami(include_token=True)` returns the exact continuity token created at member registration, leaves `last_active_ts`, claims, anchors, and presence byte-for-byte unchanged on SQLite and PostgreSQL, composes with `explain=True`, rejects non-`bool` `explain` or `include_token` with `TypeError` before resolution, raises `TokenError("selected member has no continuity token")` if `taut_members.token` is `NULL` or `""`, and preserves `client.last_created_member is saved_member` and `client.last_candidates is saved_candidates` across both success and `TokenError` / `UnrecognizedCallerError` failure.
    - `TautClient(..., install_schema=False)` rejects non-`bool` `install_schema` with `TypeError`, succeeds on initialized SQLite and PostgreSQL workspaces, and raises `NotInitializedError` with zero bytes/rows/migrations written on:
      1. a `0`-byte SQLite file,
      2. a current-version broker-only SQLite file (`taut_meta` absent),
      3. an **older-version broker-only SQLite file** (`meta.schema_version = '1'`, `taut_meta` absent — proving `BackendAwareRunner.setup()` / `migrate_schema()` never ran because `meta.schema_version` stays `'1'` and file bytes stay byte-for-byte identical!),
      4. an empty PostgreSQL schema,
      5. an **older-version broker-only PostgreSQL schema** (`meta.schema_version = '1'`, `taut_meta` absent — proving `meta.schema_version` stays `'1'` and zero new tables/columns are created!), and
      6. a **PostgreSQL target whose `public` schema has initialized `public.meta` + `public.taut_meta`** while the configured `<schema>` is empty OR older-version broker-only (`meta.schema_version = '1'`, `taut_meta` absent — proving `runner.schema`-qualified checks prevent `PostgresRunner`'s `SET search_path TO "<schema>", public` fallback from matching `public` metadata!).
    - `TautClient.search(..., channels=["#general"])` normalizes `#general` -> `general` on SQLite and PostgreSQL, deduplicates `["general", "#general"]`, and rejects `##general`, `#General`, `#general.1234567890123456789`, and `#dm`.
  - `tests/test_cli.py` & `tests/test_search_cli.py`:
    - `taut whoami --show-token --json` emits `"token": "<tok>"` (and `"explain"` when combined with `--explain`); human `taut whoami --show-token` emits `token: <tok>` on stdout after the member row (escaped via `[TAUT-6.4]`); `-q` suppresses stdout while still validating token presence; corrupted `token = NULL` exits `1`; unrecognized caller exits `2`.
    - `taut search needle --channel '#general'` succeeds with exit `0`, while `--channel '##general'` exits `1`.
  - `extensions/taut_tui/tests/test_tui_app.py`:
    - `:whoami --show-token` is recognized by shared command syntax and rejected inline with `--show-token is CLI-only in the TUI.`.
- **GREEN implementation:**
  - `taut/state/__init__.py` & `taut/state/_sql.py`: add `require_installed_taut_target(target, config)` using `get_backend_plugin(backend_name).create_runner(...)` before any `Queue` is opened — on `postgres`, checking `information_schema.tables WHERE table_schema = ? AND table_name IN ('meta', 'taut_meta')` with `(runner.schema,)` (requiring `{"meta", "taut_meta"}` in `runner.schema`) and reading `SELECT key, value FROM "<quoted_schema>".taut_meta WHERE key IN ('schema_version', 'load_guard')`; on `sqlite`, checking `plugin.meta_table_exists(runner)` and reading `SELECT key, value FROM taut_meta WHERE key IN ('schema_version', 'load_guard')`.
  - `taut/client/_base.py`: add `install_schema: bool = True` to `_ClientBase.__init__`, validating `isinstance(install_schema, bool)` and running `require_installed_taut_target(self.target, self.config)` before `self.queue(META_QUEUE_NAME)` when `False`.
  - `taut/client/_identity.py`: add `include_token: bool = False` to `IdentityMixin.whoami` with `bool` validation, `last_created_member`/`last_candidates` `try`/`finally` restoration, and `TokenError` guard when `include_token=True` and `not row["token"]`.
  - `taut/commands/whoami.py`, `taut/commands/_rendering.py`, `taut/commands/syntax.py`: add `--show-token` option, render `token: {member.token}` in human `emit_members`, and register `_option("show_token", "--show-token")`.
  - `extensions/taut_tui/taut_tui/app.py`: guard `values.get("show_token")` in `_dispatch_identity_command`.
  - `taut/client/_searching.py`: normalize `channel_selectors` with `addressing.validate_chat_thread_name(channel, allow_subthread=False)` in `_validate_search_request`.

### Slice 2: `taut-mcp` Launch Defaults (`--workspace`, `--token`, `--as`), Bounded Per-Workspace Command FIFO, `#channel` Schemas, Field-Named Validation Diagnostics, and Docs Alignment
- **RED tests first (`extensions/taut_mcp/tests/`):**
  - `test_dual_era_contract.py`:
    - Add `"onboard"` to `INTENTIONALLY_UNEXPOSED_CLI_COMMANDS`.
    - Test `build_tools(McpLaunchDefaults(...))` across all 4 launch modes (`default`, `workspace`-only, `as_name`-only, `workspace + token/as_name`), asserting exact schema shapes (`type: ["string", "null"]`), `Draft202012Validator.check_schema`, property-description parity, and serialized byte count `<= 21,000` in every mode.
    - Test `validate_tool_call` deterministic field-named `ToolValidationError` messages (expected JSON object, missing required field in `required` order, unexpected property with secret key non-echo, invalid scalar field, invalid array-element `channels[0]`, conflicting `list` `all`+`dms`), plus explicit JSON `null` rejection (`{"workspace": None, ...}`, `{..., "token": None}`, and `detach_workspace({"workspace": None})`) when the corresponding launch default is absent.
  - `test_tools.py` & `test_channel_tools.py`:
    - Test `#general` acceptance on channel-only tools (`join`, `reply`, `search.channels`, `channel_show`, `channel_topic`, `channel_rename`) while verifying they still **reject** sub-thread `#general.1234567890123456789`, `##general`, and `#General`; and test both `#general` AND `#general.1234567890123456789` acceptance on sub-thread-capable tools (`leave`, `read`, `log`, `who`).
    - Update `test_exact_tool_manifest_snapshot` to the exact SHA-256 of the default 21-tool manifest.
    - Replace single-slot busy test with bounded FIFO + cancellation + admission-prune + `channel_show` fairness proof:
      - 1 active + 8 queued commands execute in exact FIFO order and complete with accurate post-command snapshots; 10th concurrent command immediately fails with `workspace busy; retry after backoff`;
      - **Same-turn admission prune (`R2.2`)**: saturate 1 active + 8 queued commands, call `queued_8.cancel()`, and immediately admit a new 9th command on the **same loop turn** before `queued_8` unwinds — proving the new command queues cleanly instead of falsely returning `workspace busy`;
      - **Both** cancel-before-promotion schedules (`task.cancel() -> _on_command_outcome() -> task unwind` AND `task unwind -> _on_command_outcome()`) on a queued mutating `say` command prevent child dispatch and leave zero committed message rows while subsequent queued commands still execute in order;
      - **`channel_show` fairness proof (`R2.2`)**: hold `channel_show` as Command 1 (which skips post-command `peek_inbox()`), enqueue Command 2 in the FIFO, write a notification + `taut.cache_stale` hint while Command 1 is active, and prove `_publish_snapshot_if_due()`'s due `peek_inbox()` runs on Turn 1 **before** Command 2 executes on Turn 2;
      - `detach_workspace` fails with `workspace busy` while active or uncancelled-queued (and succeeds once the only queued command is cancelled and active settles);
      - `identity_lost` / `reactor_failed` / owner exit settles both active and all queued commands;
      - Independent `fast` workspace completes immediately while `slow` has 1 active + 8 queued commands.
  - `test_process_reactor.py`, `test_stdio_server.py`, and `test_pg_conformance.py`:
    - Launch CLI & content-free parser error tests on both `taut mcp` and `taut-mcp` (updating `test_stdio_server.py:374, 696, 716` to assert the fixed content-free launch error): `--workspace` relative/non-UTF-8 rejection, `--token` without `--workspace` rejection, `--token` + `--as` mutual exclusion, malformed `--as` rejection, secret-bearing `--unknown=secret` / positional / `surrogateescape` argv non-echo with zero stdout and exit `1`, `taut --db ... mcp` / `taut --json mcp` exit-1 rejection, `taut --as claude mcp --workspace ...` pre-verb merging, and `taut mcp --help` lazy-import floor.
    - Update existing `test_stdio_server.py` schema-error assertions (`L661, 860, 1699, 1719, 1752, 1776, 1795, 2502`) to exact deterministic field-named messages while retaining the 1 MiB unknown-property sentinel non-echo assertion (`L866`).
    - Modern `2026-07-28` cache-scope test: `tools/list` returns `cacheScope == "public"` without launch defaults and `cacheScope == "private"` (`ttlMs == 300000`) when launched with `--workspace`, `--as`, or `--workspace` + `--token`.
    - Complete default-workspace, explicit-`null`/`""`, symlink-retarget, and `--as` matrix:
      - Explicit JSON `null` calls (`attach_workspace({"workspace": None, "token": None})`, `whoami({"workspace": None, "token": None})`, and `detach_workspace({"workspace": None})`) succeed identically to `{}` when `--workspace` + `--token`/`--as` are configured, and fail schema validation with `invalid field 'workspace'` / `invalid field 'token'` when absent;
      - Launch `--workspace /alias --token T`, attach canonical `/real` (or descendant `/real/sub`) on Call 1 with explicit `T`, then Call 2 with omitted `workspace`/`token` and Call 3 with `/real` + omitted `token` -> 0-I/O fast path;
      - Launch `--as claude`, attach `/real` on Call 1 with explicit `claude_token` (`Bootstrap.configured_as_name == "claude"`), then Call 2 via `/real` or `/alias` with omitted `token` -> reuses entry (`matches_default_as == True`) with zero `GrantValidation`; Call 1 with explicit `bob_token` followed by Call 2 with omitted `token` returns `WORKSPACE_CONFLICT` with zero `GrantValidation`; and **inverse explicit-token check (`R3.2`)**: Call 1 attaches Claude (`matches_default_as == True`) followed by Call 2 via `/real` or `/alias` with explicit `bob_token` -> returns `WORKSPACE_CONFLICT` with zero `GrantValidation` (never consulting `matches_default_as` when `request_token is not None`);
      - **Symlink retarget across both validation and resident states (`R2.3` + `R3.1`)**:
        1. **Overlapping validation (`R3.1`)**: launch `--workspace /symlink --token T1` pointing to Project A (even when `T1` also exists in Project B), start Project A through its canonical `/real_a` and hold Project A in `phase == "validation"` (`candidate_a.is_default_workspace == True`), then retarget `/symlink` to Project B on disk before Project A publishes: (a) calling with omitted `workspace` + omitted `token` (`{}`) immediately fails with `WORKSPACE_BUSY` at preflight (and likewise fails with `WORKSPACE_BUSY` at `_on_resolved` with **zero `GrantValidation`** if `{}` started while `/real_a` was still in `phase == "resolution"` and `/real_a` won `_on_resolved` first), never applying `T1` to Project B; (b) resolving explicit `/real_b` with omitted `token` fails at `_on_resolved` with `NON_DEFAULT_WORKSPACE_TOKEN_REQUIRED` and zero `GrantValidation`; (c) resolving explicit `/real_b` with explicit `T2` clamps Project B to `is_default_workspace == False` before `GrantValidation` so even if Project A publishes ready or times out into a canonical tombstone, only Project A holds `is_default_workspace == True` (whereas if Project A fails validation, its reservation releases so a fresh default call resolves onto Project B);
        2. **Resident entry (`R2.3`)**: while Project A is resident (`is_default_workspace == True`) and `/symlink` points to Project B, calling with `/real_b` + omitted `token` fails with `NON_DEFAULT_WORKSPACE_TOKEN_REQUIRED` and zero `GrantValidation`; attaching `/real_b` with explicit `T2` attaches Project B with `is_default_workspace == False` while omitted-`workspace` calls and `detach_workspace({})` continue to target Project A unambiguously; after `detach_workspace({})` removes Project A, a subsequent omitted-`workspace` call resolves `/symlink` onto Project B;
      - Validation-timeout tombstone under `--workspace /alias --token T` followed by `detach_workspace({})` -> detaches the canonical tombstone and frees the seat;
      - Explicit `workspace: ""` (`WORKSPACE_ABSOLUTE`), explicit `token: ""` (`IDENTITY_INVALID` on master before seat/arbitration), and `detach_workspace({"workspace": ""})` (idempotent empty result without detaching resident default workspace);
      - `readOnlyHint=true` call (`whoami`, `list`, `channel_show`) under `--as` or `--token` against a `0`-byte SQLite file, an **older-version broker-only** SQLite file (`meta.schema_version = '1'`), an empty PostgreSQL schema, an **older-version broker-only** PostgreSQL schema, and a **PostgreSQL target whose `public` schema has initialized `public.meta` + `public.taut_meta` while `<schema>` is empty or older-version broker-only (`R3.3`)** fails with `PROJECT_NOT_FOUND` and writes zero bytes/migrations/tables.
    - Live PostgreSQL conformance (`test_pg_conformance.py`): `whoami(include_token=True)`, older-broker-version and `public`-schema-populated non-mutation under `--as`/`--token`, `--workspace` + `--as` read-only attachment, `#general` channel/search tools, and parallel same-workspace FIFO execution.
- **GREEN implementation:**
  - `extensions/taut_mcp/taut_mcp/cli.py` & `command.py`: `McpLaunchDefaults`, content-free parser error handler, `validate_launch_defaults`, pre-verb `CommandContext` checks/merge, and plumbing into `run_process` -> `run_server` -> `create_server`.
  - `extensions/taut_mcp/taut_mcp/_tools.py` & `server.py`: `#?` patterns, compact `type: ["string", "null"]` in `build_tools(defaults)`, deterministic field-named `ToolValidationError`, updated `INSTRUCTIONS` rules 2/3/9, and conditional `private` `CacheHint` on `tools/list`.
  - `extensions/taut_mcp/taut_mcp/_process_reactor.py` & `_workspace_reactor.py`: `McpLaunchDefaults` routing, master empty-token check, `Bootstrap.configured_as_name`, child-resolved `is_default_workspace` + master single-owner default-workspace reservation across `phase == "validation"` and `_entries` (`_has_other_default_owner`), `install_schema=False` on both `--as` probe and persistent `TautClient`, strict two-branch selector comparison (`request_token is not None` vs `--as`) across `_preflight_workspace` and `_on_resolved`, default-aware `detach_workspace`, and bounded `queued_commands` (`MAX_QUEUED_COMMANDS = 8`) with `_prune_cancelled_queued_commands` across admission, promotion, and detach.
  - Align `README.md`, `extensions/taut_mcp/README.md`, `docs/agent-kernel.md` + `taut/agent-kernel.md` (byte-identical), and `docs/implementation/{02-repository-map,04-taut-architecture,07-taut-mcp-architecture}.md`.

---

## 6. Verification Gates (`[DOM-10]`)

1. **Documentation, Plan, Ruff Suppression & Static Gates:**
   - `uv run python bin/check-plan-status-index`
   - `uv run python bin/check-doc-paths`
   - `uv run python bin/check-cli-claims`
   - `uv run python bin/check-dom15-fixtures`
   - `uv run python bin/coalesce-check`
   - `uv run python bin/ruff_suppression_index.py --check`
   - `uv run ruff check . && uv run ruff format --check .`
   - `uv run mypy`
   - `uv run --project extensions/taut_mcp --extra dev ruff check extensions/taut_mcp/taut_mcp extensions/taut_mcp/tests && uv run --project extensions/taut_mcp --extra dev ruff format --check extensions/taut_mcp/taut_mcp extensions/taut_mcp/tests && uv run --project extensions/taut_mcp --extra dev mypy extensions/taut_mcp/taut_mcp extensions/taut_mcp/tests --config-file extensions/taut_mcp/pyproject.toml`
   - `uv run --directory extensions/taut_tui ruff check . && uv run --directory extensions/taut_tui ruff format --check . && uv run --directory extensions/taut_tui mypy taut_tui tests`
   - `git diff --check`
2. **Automated Behavioral Suites (SQLite, Live PostgreSQL 18, TUI, MCP):**
   - `uv run pytest -q -m "not pg_only"`
   - `./bin/pytest-pg` (runs root `shared` and `extensions/taut_pg` `pg_only` against Docker PostgreSQL 18)
   - `uv run --project extensions/taut_mcp --extra dev pytest extensions/taut_mcp/tests -q -m "not pg_only"`
   - Live PostgreSQL 18 MCP suite (`SIMPLEBROKER_PG_TEST_DSN` lifecycle):
     ```bash
     uv run python -c '
     import os, subprocess
     from taut._scripts import _cleanup_container, _launch_postgres_container, _postgres_test_dsn, _verify_postgres_test_dsn
     name = _launch_postgres_container()
     try:
         dsn = _postgres_test_dsn(name)
         _verify_postgres_test_dsn(dsn)
         subprocess.run(["uv", "run", "--project", "extensions/taut_mcp", "--extra", "dev", "pytest", "extensions/taut_mcp/tests", "-q"], env={**os.environ, "SIMPLEBROKER_PG_TEST_DSN": dsn}, check=True)
     finally:
         _cleanup_container(name)
     '
     ```
   - `uv run --directory extensions/taut_tui pytest -q -n 2 --dist loadfile`
3. **Adversarial & End-to-End CLI/MCP Probes (`adversarial-acceptance-probes.md`):**
   - End-to-end onboarding + MCP workflow probe:
     1. Run `taut onboard --mcp`, `taut --as claude join general`, and `taut --as claude whoami --show-token --json` in a fresh directory;
     2. Launch real stdio `taut mcp --workspace <dir> --as claude`;
     3. Warm/seed `#dev` sequentially (`await session.call_tool("join", {"thread": "#dev"})`, `await session.call_tool("say", {"target": "#dev", "text": "hello"})`);
     4. Fan out concurrent `asyncio.gather` calls (`read({"thread": "#dev"})`, `search({"query": "hello", "channels": ["#dev"]})`, `who({"thread": "#dev"})`, `whoami({})`) on the warm resident workspace with zero `workspace`/`token` tool arguments, asserting all four succeed in one turn without `workspace busy`;
     5. Run negative probes (`1 MiB` unknown-key non-echo, explicit JSON `null` when defaults absent, non-default workspace without token, missing `--as` member, older-version broker-only target zero-migration, secret launch positional non-echo, and `:whoami --show-token` in TUI).

---

## 7. Pre-Edit Comprehension Gate (`docs/agent-context/runbooks/writing-plans.md`)

**Gate rule:** Before editing any production or test file in Slice 1 or Slice 2, re-verify each question below against the live repository files and record the confirmed answers in a `## 10. Execution Log` section of this plan; if any answer does not hold against the live code, **stop immediately and revise the plan before editing**.

1. **Q1 (Why must `_prune_cancelled_queued_commands` run before both FIFO admission counting and FIFO promotion?)**
   `Task.cancel()` flips `waiter.cancelled() == True` synchronously while scheduling the done callback and the coroutine's `except asyncio.CancelledError:` handler for a later loop turn (`_process_reactor.py:96-119`). Pruning `queued.canceled or queued.waiter.cancelled()` synchronously at admission, promotion, and detach prevents both promoting a cancelled write to the child and falsely returning `workspace busy` when a cancelled slot is replaced on the same loop turn.
2. **Q2 (Why must `TautClient(..., install_schema=False)` validate `meta` and `taut_meta` on a raw `plugin.create_runner(...)` — schema-qualified on PostgreSQL — before opening `Queue(META_QUEUE_NAME)`?)**
   `Queue.sidecar()` lazily runs `BackendAwareRunner.setup()`, which installs tables on an empty target and runs `migrate_schema()` on an older-version broker-only target (`meta.schema_version = '1'`), and `PostgresRunner` sets `search_path` to `"<schema>", public` (`simplebroker_pg/runner.py:1005`). Checking `information_schema.tables WHERE table_schema = ? AND table_name IN ('meta', 'taut_meta')` with `(runner.schema,)` plus `"<quoted_schema>".taut_meta` on PostgreSQL (and `plugin.meta_table_exists(runner)` plus `taut_meta` on SQLite) on the raw `SQLRunner` first fails closed with `NotInitializedError` before `Queue` or `BackendAwareRunner` is constructed, even if `public.taut_meta` exists.
3. **Q3 (How are `matches_default_as`, `is_default_workspace` across validation and symlink retargeting, manifest size, and `tools/list` cache metadata kept coherent?)**
   `Bootstrap` carries `configured_as_name` independently of per-request `as_name` while selector matching checks `entry.token == request_token` solely when `request_token is not None` and `entry.matches_default_as` solely when `request_token is None`; `_on_resolved` reserves at most one default-workspace owner across both `phase == "validation"` candidates and published `_entries` (`_has_other_default_owner`) until validation fails or detach completes; optional `workspace`/`token` use compact `type: ["string", "null"]` (`20,215`–`20,366` bytes `<= 21,000`); and `tools/list` uses `cacheScope: "private"` whenever any launch default is set.

---

## 8. Deviation Log

None.

---

## 9. Review Log

### Round 1 — Tier-1 Pre-Implementation Plan Review (`codex-cli 0.170.0` / `gpt-6.2-sol`, 2026-11-24)

- **Command**: `codex exec -s read-only -c 'model_reasoning_effort="high"' -C /Users/van/Developer/taut -o phase-2a-plan-review-r1.md - < phase-2a-plan-review-prompt.md`
- **Verdict**: `BLOCKED` (4 `P1` + 4 `P2` findings).
- **Dispositions**: All 8 findings (`F1`–`F8`) accepted and incorporated into §§1–7.

### Round 2 — Tier-1 Verification Review (`codex-cli 0.170.0` / `gpt-6.2-sol`, 2026-11-24)

- **Command**: `codex exec -s read-only -c 'model_reasoning_effort="high"' -C /Users/van/Developer/taut -o phase-2a-plan-review-r2.md - < phase-2a-plan-review-r2-prompt.md`
- **Verdict**: `BLOCKED` (`F5` manifest byte counts `20,347` / `20,274` / `20,366` / `20,215` and `F7` diagnostic-object restoration verified; 4 `P1` + 2 `P2` refinements identified).
- **Dispositions**:
  - `R2.1` (`P1` — `Replacement` block count mismatch and partial-paragraph line spans in `03`, `06`, `05`, and backlinks): **Accepted — fixed in plan** (§4, §5 Slice 0). Every one of the **34** `Replacement` blocks now has its own numbered subheading with exact inclusive 1-based `(L<start>–L<end>)` span replacing complete paragraphs/rows/bullets with zero deleted requirements or truncated backlinks.
  - `R2.2` (`P1` — FIFO admission race when counting slots before a cancelled waiter's done callback runs, plus using `channel_show` in fairness proof): **Accepted — fixed in plan** (§3.1(3), §4.5k–l, §4.5s4, §5 Slice 2, §7 Q1). Added `_prune_cancelled_queued_commands(entry)` before FIFO admission counting, promotion, and detach, plus same-turn cancel-then-admit and `channel_show` fairness tests.
  - `R2.3` (`P1` — `Bootstrap` needed `configured_as_name` independent of per-request `as_name`, and symlink retargeting while a default entry is resident needed single-default freeze rules): **Accepted — fixed in plan** (§3.1(2), §4.5g, §5 Slice 2, §7 Q3). Added `configured_as_name` to `Bootstrap` and enforced at-most-one resident `is_default_workspace` entry until detached.
  - `R2.4` (`P1` — `Queue.sidecar()` ran `BackendAwareRunner.setup()` / `migrate_schema()` on older-version broker-only targets before `taut_meta` was checked): **Accepted — fixed in plan** (§3.1(1), §4.1d, §4.5e, §5 Slices 1–2, §7 Q2). Moved both `plugin.meta_table_exists(runner)` and `SELECT key, value FROM taut_meta ...` onto the short-lived raw `SQLRunner` **before** `self.queue(META_QUEUE_NAME)` is constructed, with explicit `meta.schema_version = '1'` older-broker fixtures on SQLite and PostgreSQL.
  - `R2.5` (`P2` — Explicit JSON `null` RED test cases + `[MCP-4]` `L247–250` resolution-event prose + `[MCP-6]` `L1154–1159` detach lookup prose): **Accepted — fixed in plan** (§4.5d, §4.5n, §5 Slice 2).
  - `R2.6` (`P2` — TUI `:search --channel` is intentionally CLI-only at `app.py:1575`, PG MCP verification recipe needed `_postgres_test_dsn` + `_verify_postgres_test_dsn` inside `try/finally`, and §7 needed explicit stop-before-edit gate rule): **Accepted — fixed in plan** (§1.4, §4.3b, §4.4b, §5 Slice 1, §6.2, §7).

### Round 3 — Tier-1 Scoped Verification Review (`codex-cli 0.170.0` / `gpt-6.2-sol`, 2026-11-24)

- **Command**: `codex exec -s read-only -c 'model_reasoning_effort="high"' -C /Users/van/Developer/taut -o phase-2a-plan-review-r3.md - < phase-2a-plan-review-r3-prompt.md`
- **Verdict**: `BLOCKED` (`R2.2` synchronous FIFO pruning + `channel_show` fairness and `R2.5` explicit-`null` + `[MCP-4]`/`[MCP-6]` prose verified; 3 `P1` + 2 `P2` surgical refinements identified).
- **Dispositions**:
  - `R3.1` (`P1` — Reserve `is_default_workspace` at `GrantValidation` across `phase == "validation"` candidates as well as published `_entries` so overlapping validation across a symlink retarget cannot publish two defaults): **Accepted — fixed in plan** (§3.1(2), §4.5g, §5 Slice 2, §7 Q3).
  - `R3.2` (`P1` — Keep explicit-token branch `entry.token == request_token` strictly separate from `--as` branch `entry.matches_default_as`, and add inverse Bob-explicit-token-on-Claude-entry RED case): **Accepted — fixed in plan** (§3.1(2), §5 Slice 2, §7 Q3).
  - `R3.3` (`P1` — Qualify PostgreSQL `meta` and `taut_meta` checks to `runner.schema` so `PostgresRunner`'s `SET search_path TO "<schema>", public` fallback cannot match `public.taut_meta`, plus add `public`-populated PostgreSQL fixture): **Accepted — fixed in plan** (§3.1(1), §4.1d, §5 Slices 1–2, §7 Q2).
  - `R3.4` (`P2` — Expand `4.5d` to full paragraph `L233–L250` and `4.5r` to full paragraph `L1624–L1639` in `docs/specs/05-taut-mcp.md`): **Accepted — fixed in plan** (§4.5d, §4.5r).
  - `R3.5` (`P2` — Include `--extra dev` on `uv run --project extensions/taut_mcp` commands in §6 matching `.github/workflows/test-mcp-extension.yml`): **Accepted — fixed in plan** (§6.1, §6.2).

### Round 4 — Tier-1 Scoped Verification Review (`codex-cli 0.170.0` / `gpt-6.2-sol`, 2026-11-24)

- **Command**: `codex exec -s read-only -c 'model_reasoning_effort="high"' -C /Users/van/Developer/taut -o phase-2a-plan-review-r4.md "$(cat phase-2a-plan-review-r4-prompt.md)" < /dev/null`
- **Verdict**: `FAIL` (`R3.2`, `R3.3`, and `R3.5` verified; 1 `P1` routing edge on `R3.1` + 1 `P2` verbatim word on `R3.4`).
- **Dispositions**:
  - `R3.1` (`P1` — When Project A is validating via `/real_a` and `/symlink` retargets to Project B before Project A publishes, an omitted-`workspace` + omitted-`token` call must honor the validation reservation rather than falling back to `/symlink` and validating Project B with Project A's launch token): **Accepted — fixed in plan** (§3.1(2), §4.5g, §5 Slice 2). Omitted/null `workspace` (`used_default_workspace = True`) now checks `candidate.is_default_workspace` at master preflight (returning `WORKSPACE_BUSY` immediately) AND retires with `WORKSPACE_BUSY` and zero `GrantValidation` at `_on_resolved` if another default owner claimed the reservation first, plus `require_default_workspace` is set whenever launch `--token` is used.
  - `R3.4` (`P2` — Restore `"fixed"` in `"the fixed schema-invalid tool result"` in §4.5r `L1635`): **Accepted — fixed in plan** (§4.5r).

### Round 5 — Tier-1 Scoped Verification Review (`codex-cli 0.170.0` / `gpt-6.2-sol`, 2026-11-24)

- **Command**: `codex exec -s read-only -c 'model_reasoning_effort="high"' -C /Users/van/Developer/taut -o phase-2a-plan-review-r5.md "$(cat phase-2a-plan-review-r5-prompt.md)" < /dev/null`
- **Verdict**: `FAIL` (`R3.4` and the `R3.1` reactor/Slice 2 design verified; 1 `P2` prose-scope clarification in `§4.5g`).
- **Dispositions**:
  - `R3.1` (`P2` — `§4.5g` nested the single-default reservation and omitted-`workspace` busy rule inside the launch `--token` sentence and did not distinguish master-preflight routing to a published default entry from resolution-arbitration `workspace busy` retirement when an earlier omitted-`workspace` candidate resolves after another validation or published entry owns the default binding): **Accepted — fixed in plan** (§4.5g). Separated the `--workspace`-wide single-owner reservation, preflight routing/busy rule, and resolution-arbitration `workspace busy` retirement sentence (applying across `--token`, `--as`, and explicit per-call tokens) from the launch `--token` scoping sentence.

### Round 6 — Tier-1 Scoped Verification Review (`codex-cli 0.170.0` / `gpt-6.2-sol`, 2026-11-24)

- **Command**: `codex exec -s read-only -c 'model_reasoning_effort="high"' -C /Users/van/Developer/taut -o phase-2a-plan-review-r6.md "$(cat phase-2a-plan-review-r6-prompt.md)" < /dev/null`
- **Verdict**: `FAIL` (selector-independent reservation, separate `--token` scope, and resolution-arbitration branch verified; 1 `P2` preflight-precedence wording ambiguity in `§4.5g`).
- **Dispositions**:
  - `R3.1` (`P2` — Make the `§4.5g` master-preflight `workspace busy` branch explicitly conditional on no published default entry existing, so a concurrent explicit `/symlink` candidate for Project B cannot shadow a resident default Project A): **Accepted — fixed in plan** (§4.5g).

### Round 7 — Tier-1 Scoped Verification Review (`codex-cli 0.170.0` / `gpt-6.2-sol`, 2026-11-24)

- **Command**: `codex exec -s read-only -c 'model_reasoning_effort="high"' -C /Users/van/Developer/taut -o phase-2a-plan-review-r7.md "$(cat phase-2a-plan-review-r7-prompt.md)" < /dev/null`
- **Verdict**: `PASS` (zero defects; all 34 `Replacement` blocks and all 24 `2026-11-10` promoted blocks verified).

### Post-Implementation Round 1 — Tier-1 Review (`codex-cli 0.170.0` / `gpt-6.2-sol`, 2026-11-24)

- **Command**: `codex exec -s read-only -c 'model_reasoning_effort="high"' -C /Users/van/Developer/taut -o phase-2a-impl-review-r1.md "$(cat phase-2a-impl-review-prompt.md)" < /dev/null`
- **Verdict**: `BLOCKED` (`F1`–`F5` `P2` + `F6` `P3`; all 34 promoted spec blocks, manifest byte ceiling, Ruff suppressions, doc/CLI claims, kernel parity, and unique coverage marker verified).
- **Dispositions**:
  - `F1` (`P2` — Resident workspace default handoff in `_arbitrate_existing_entry` when `/symlink` retargets to an already-resident workspace with no default owner remaining): **Accepted — fixed in `extensions/taut_mcp/taut_mcp/_process_reactor.py` and tested in `extensions/taut_mcp/tests/test_process_reactor.py`**. `_arbitrate_existing_entry` now passes `require_default_workspace=candidate.require_default_workspace and not effective_is_default` to `_check_entry_selector` and binds `entry.is_default_workspace = True` at the master serial point once selector validation succeeds (covered in both `--token` and `--as` modes).
  - `F2` (`P2` — Fresh `TautClient.init()` DDL left SQLite `meta.schema_proof_cookie` behind `PRAGMA schema_version`, and cold `install_schema=False` / `--as` opens could run broker setup or rewrite `schema_proof_cookie`): **Accepted — fixed in `taut/state/_sql.py`, `taut/state/__init__.py`, `taut/client/__init__.py`, `taut/client/_base.py`, and tested in `tests/test_client.py` + `extensions/taut_mcp/tests/test_process_reactor.py`**. `TautClient.init()` and `ensure_schema()` refresh the SQLite broker receipt after initial DDL, `require_installed_taut_target` verifies `meta.magic` and `meta.schema_version == plugin.schema_version` on the raw runner before opening any `Queue`, and `TautClient(..., install_schema=False)` (`persistent=False`, including `_probe_as_token`) uses `NoSetupSQLRunner` to suppress all SimpleBroker setup/cookie writes even when `meta.schema_proof_cookie` is artificially stale.
  - `F3` (`P2` — PostgreSQL `public.meta` / `public.taut_meta` fallback tests mutated and dropped `public` tables in the shared test database): **Accepted — fixed in `extensions/taut_pg/tests/test_pg_sidecar.py` and `extensions/taut_mcp/tests/test_pg_conformance.py`**. Both tests now create and drop a dedicated test-owned PostgreSQL database (`CREATE DATABASE ...` / `DROP DATABASE ... WITH (FORCE)`) for `public`-schema shadow probes, leaving the shared `SIMPLEBROKER_PG_TEST_DSN` database untouched.
  - `F4` (`P2` — `validate_tool_call` materialized `list(validator.iter_errors(normalized))` across large invalid arrays on the master event loop): **Accepted — fixed in `extensions/taut_mcp/taut_mcp/_tools.py` and tested in `extensions/taut_mcp/tests/test_dual_era_contract.py`**. Pre-compiled per-property and per-item validators visit fields in deterministic schema order and stop at the first failing field or array index via `next(..., None)` (`< 256 KB` traced peak allocation on a 10,000-element invalid array).
  - `F5` (`P2` — Cold explicit workspace attachment resolved `default_workspace` unconditionally on the child thread even when pinned or when the default filesystem was hung): **Accepted — fixed in `extensions/taut_mcp/taut_mcp/_process_reactor.py` and `_workspace_reactor.py`, and tested in `extensions/taut_mcp/tests/test_process_reactor.py`**. `Bootstrap` reuses `pinned_default_workspace` with zero filesystem I/O whenever a validation or resident default owner exists, and uses a coalesced bounded `DefaultWorkspaceProbe` (`0.2s` non-blocking ceiling) when unpinned so a hung default filesystem never blocks unrelated explicit workspace attachments.
  - `F6` (`P3` — `_resolve_request` checked workspace absoluteness before token UTF-8 validity): **Accepted — fixed in `extensions/taut_mcp/taut_mcp/_process_reactor.py` and tested in `extensions/taut_mcp/tests/test_process_reactor.py`**. Restored `[MCP-4]` order: workspace UTF-8 -> token UTF-8 -> workspace absoluteness -> identity check.

### Post-Implementation Rounds 2–7 — Scoped Tier-1 Verification Reviews (`codex-cli 0.170.0` / `gpt-6.2-sol`, 2026-11-24)

- **Round 2 (`FAIL`)**: Verified `F1`, `F4`, and `F6`; identified `F2a` (`P3` — refresh SQLite `schema_proof_cookie` for resolved `BrokerTarget` and `persistent=True` constructors), `F2b` (`P2` — bypass SimpleBroker project target admission on `install_schema=False` after raw validation), `F3` (`P2` — use `psycopg.conninfo.make_conninfo(pg_dsn, dbname=isolated_db)` and assert `SELECT current_database()`), `F5a` (`P2` — preserve timed-out default probe matches and reconcile at the master serial point), and `F5b` (`P2` — settle `_inflight` and `attempt.done` in `finally` on `OSError`/`PermissionError`). All five accepted and fixed.
- **Round 3 (`FAIL`)**: Verified `F2a` and `F5b`; identified `R3-1` & `R3-3` (`P2` — bind late probe matches only to live participants that timed out on that attempt with `O(1)` probe state), `R3-2` (`P2` — enforce read-only PostgreSQL v6 broker table/column/index shape check in `_read_postgres_raw_meta` before bypassing project admission), and `R3-4` (`P3` — `json.dumps(..., ensure_ascii=False)` for supplementary Unicode DSNs in `.taut.toml` fixtures). All four accepted and fixed.
- **Round 4 (`FAIL`)**: Verified `R3-1`, `R3-2`, `R3-3`, and `R3-4`; identified `R4-1` (`P2` — carry `DefaultProbeAttempt` directly on timed-out participants so overlapping probe completions never overwrite an earlier participant's result) and `R4-2` (`P3` — run supplementary Unicode round-trip checks through the actual `make_iso_project` / `make_pg_ws` fixture writers). Both accepted and fixed.
- **Round 5 (`FAIL`)**: Verified `R4-2`; identified `R5-1` (`P2` — invoke `_on_resolved(attempt)` under `_lock` before clearing `_inflight` and retain a `pending_default_probes` list on `_Entry` across multiple alias attaches) and `R5-2` (`P2` — resolve `_UNPINNED_DEFAULT_PROBE_TIMEOUT_SECONDS` at call time in `match()` and wait for both completions to drain in test). Both accepted and fixed.
- **Round 6 (`FAIL`)**: Verified all production fixes (`R5-1` and `R5-2`); identified three `P3` regression-test assertion tightenings (`R6-1` enqueue-boundary `_inflight` + `_lock.locked()` check, `R6-2` recorded `Event.wait` timeout check, `R6-3` bounded `p1_entered`/`p2_entered` waits). All three accepted and fixed in `extensions/taut_mcp/tests/test_process_reactor.py`.
- **Round 7 (`PASS`)**: Verified `R6-1`, `R6-2`, and `R6-3` with zero remaining defects (`Verdict: PASS`).

---

## 10. Execution Log

### Slice 0 & Pre-Edit Comprehension Gate Confirmed (2026-11-24)

- Applied all **34** `Replacement` blocks across `docs/specs/02-taut-core.md`, `03-identity-addressing-notifications.md`, `06-search.md`, `10-taut-tui.md`, and `05-taut-mcp.md`.
- Re-verified all three §7 Pre-Edit Comprehension Gate questions directly against the live repository files before touching code or tests:
  - **Q1 confirmed (`extensions/taut_mcp/taut_mcp/_process_reactor.py:96-119`)**: `_await_owned_future` awaits a per-caller `waiter` future; `Task.cancel()` flips `waiter.cancelled() == True` synchronously while deferring done callbacks and coroutine unwind to a later loop turn, so `_prune_cancelled_queued_commands(entry)` must run synchronously at the master serial point before FIFO admission counting, FIFO promotion, and `detach_workspace`.
  - **Q2 confirmed (`taut/client/_base.py:207-216`, `taut/state/_sql.py:558-610`, `simplebroker_pg/runner.py:1005`)**: `_ClientBase.__init__` currently opens `self.queue(META_QUEUE_NAME)` before `ensure_schema()`, and `Queue.sidecar()` lazily triggers `BackendAwareRunner.setup()` / `migrate_schema()`, while `PostgresRunner` sets `search_path` to `"<schema>", public`. Running `require_installed_taut_target` on a raw `plugin.create_runner(...)` with `runner.schema`-qualified checks on `postgres` before `self.queue(META_QUEUE_NAME)` guarantees zero setup/migration writes and zero `public` schema fallback.
  - **Q3 confirmed (`extensions/taut_mcp/taut_mcp/_process_reactor.py`, `_workspace_reactor.py`, `_tools.py`, `server.py:238-243`)**: `Bootstrap.configured_as_name`, strict two-branch selector matching (`request_token is not None` vs `--as`), single-owner default-workspace reservation across `phase == "validation"` and `_entries` (`_has_other_default_owner`) plus omitted-workspace `WORKSPACE_BUSY` handling, compact `type: ["string", "null"]`, and conditional `scope="private"` on `tools/list` (`server.py:240`) all align cleanly with the live implementation structure.

### Slices 1 & 2 Verification Evidence (2026-11-24)

- **Static, Doc & Type Gates**: `bin/check-plan-status-index`, `bin/check-doc-paths` (`65` sources, `1,634` path claims), `bin/check-cli-claims` (`65` sources, `322` CLI claims), `bin/check-dom15-fixtures`, `bin/coalesce-check`, `bin/ruff_suppression_index.py --check`, `cmp -s docs/agent-kernel.md taut/agent-kernel.md`, `ruff check` + `ruff format --check` (`420` root + `23` MCP files), `mypy` (`149` root + `12` PG + `23` MCP + `56` TUI files), and `git diff --check` all `exit 0`.
- **Behavioral Suites**:
  - Root SQLite/non-PG suite (`uv run pytest -q -m "not pg_only"`): `2,506 passed, 5 skipped` (`exit 0`).
  - Live Docker PostgreSQL 18 root `shared` + `extensions/taut_pg` (`uv run ./bin/pytest-pg`): `290 passed` (`shared`) + `55 passed` (`pg_only`) (`exit 0`).
  - `extensions/taut_mcp` SQLite + live Docker PostgreSQL 18 (`uv run --project extensions/taut_mcp --extra dev pytest extensions/taut_mcp/tests -q -m "not pg_only"` and `uv run ./bin/pytest-pg extensions/taut_mcp/tests`): `345 passed` (non-PG) + `11 passed` (`pg_only`) (`exit 0`).
  - `extensions/taut_tui` (`uv run --directory extensions/taut_tui pytest -q -n 2 --dist loadfile`): `777 passed, 3 skipped` (`exit 0`).
  - End-to-end `taut onboard --mcp` + stdio `taut mcp --workspace <dir> --as claude` 4-way concurrent `asyncio.gather` + negative probes (§6.3): `exit 0`.
