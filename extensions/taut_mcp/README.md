# Taut MCP

`taut-mcp` is the optional stdio MCP adapter for Taut. One client launches one
protocol-clean process. That process can keep up to eight local workspaces
resident, but it is not a daemon and stores no durable MCP session state.
Taut databases remain authoritative.

One application surface supports both MCP wire eras:

- legacy clients using protocol `2025-11-25` and `initialize`;
- modern sessionless clients using `2026-07-28` and `server/discover`.

Both receive the same 21 tools, input schemas, tool results, instructions, and
Taut behavior. The MCP SDK owns the different wire envelopes. The complete
contract is `docs/specs/05-taut-mcp.md` [MCP-1]–[MCP-12].

## Workspaces and Identity

By default, every identity-using call carries:

- `workspace`: an absolute local directory containing an existing Taut
  project; and
- `token`: an existing Taut continuity token for the intended member.

For single-project or named-agent host registrations, `taut mcp` (and
`taut-mcp`) also accepts optional launch defaults:

- `--workspace DIR`: absolute path to a default Taut workspace directory; and
- `--token TOKEN` (requires `--workspace`) or `--as NAME` (mutually exclusive
  with `--token`; pre-verb `taut --as NAME mcp` / `taut --token TOKEN mcp` is
  equivalent when unambiguous).

When a launch default is configured, the corresponding `workspace` and/or
`token` tool properties become optional (`["string", "null"]`) in advertised
schemas and `tools/list` advertises `cacheScope: "private"`, while explicit
non-null per-call values still override the default. Launch `--token` applies
only to the configured `--workspace`; non-default workspaces require an
explicit per-call `token`. Launch `--as NAME` resolves an existing member via
Taut's read-only selector without creating members, installing or migrating
schemas, or touching activity/claims.

The token selects identity continuity. It is not authentication,
authorization, or a bearer capability. Treat it as sensitive input: do not
invent it, place it in chat, or log it.

`attach_workspace(workspace, token)` eagerly resolves the project, validates
the member, starts notification observation, and retains one configured
client. Attach is useful when setup cost should be paid before a domain
operation, but it is not a correctness prerequisite.

Each of the 18 CLI-shaped tools uses the same workspace and identity
resolution. If its workspace is not resident, that first call performs the same
setup lazily and retains the same client/reactor. Reuse the canonical workspace
returned by a successful call or `list_workspaces` for the fast path. Each
resident workspace executes one synchronous command at a time and queues up to
eight additional waiting commands in FIFO order (`MAX_QUEUED_COMMANDS = 8`)
before returning `workspace busy`, so parallel same-turn tool calls from an MCP
host serialize cleanly instead of failing.

`detach_workspace` is different: it accepts only the exact canonical
`workspace` (or omits `workspace` when `--workspace` is configured) and no
token because it removes process-local cached state rather than performing a
Taut identity operation. `list_workspaces` takes no arguments and reports only
state resident in the current process.

After process restart, an ordinary CLI-shaped call can reconstruct its
workspace/member binding from `workspace` plus `token` (or configured launch
defaults); prior attach state is never required.

## Notifications

The fixed read-only resource is:

```text
taut://notifications/current
```

It reports pending notification pointers for resident workspaces. Reading it
does not claim notifications, advance chat cursors, touch member activity, or
return every unread message. Use `inbox(workspace, token, ...)` to consume
notification pointers and act only on the records returned by that consuming
call.

The resource is the level-triggered source of truth. Standard delivery
mechanisms are redundant hints:

- legacy clients use `resources/subscribe` and `resources/unsubscribe`;
- modern clients open a long-lived `subscriptions/listen` request whose
  `notifications.resourceSubscriptions` includes
  `taut://notifications/current`.

Modern listen filters, acknowledgments, subscription ids, fanout,
cancellation, and graceful close are owned by the MCP SDK. A dropped,
duplicated, or delayed hint does not lose Taut data; reread the resource.

## Tool Notes

Channel and chat-thread parameters across `join`, `leave`, `reply`, `read`,
`log`, `who`, `search.channels`, `channel_show`, `channel_topic`, and
`channel_rename` accept an optional single leading `#` (for example `#general`)
and normalize it to the canonical channel or sub-thread name. Known-tool schema
validation failures name the deterministic server-owned invalid, missing, or
conflicting schema field without echoing caller-supplied values or unknown
property keys.

`read` and `log` accept the same direct-message selectors as the CLI
(`@name-or-alias` routes and exact stable `dm.d_*` handles), and `list`
with `dms=true` returns the attached member's durable DM directory.
`say` also accepts a returned exact stable handle for that already valid,
actor-accessible conversation. Only person-addressed `@name-or-alias` may
create a DM or its memberships; stable-handle send never creates or repairs
one. A well-formed inaccessible stable handle returns the ordinary empty
`message` result, while malformed syntax and route failures remain tool errors.

`search(workspace, token, query, ...)` searches the same source-hydrated,
actor-visible history as `TautClient.search`. Bare search covers registered
channels, their sub-threads, and actor-accessible DMs; explicit channel and DM
selectors replace that default with their union. Author, kind, `before`, and
limit filters refine the query. The call does not move chat cursors, claim
notifications, or touch member activity, but it may reconcile disposable
index state; `reindex=true` performs the more expensive complete rebuild.
Returned message ids are exact strings. SQLite and PostgreSQL may return
different Unicode lexical matches, so treat search as retrieval rather than
authoritative cross-backend computation.

`message_show(workspace, token, msg_id)` accepts an exact 19-digit message id
and advances the selected member's seen cursor through that message. Use
`log(workspace, token, ...)` for cursor-neutral inspection.

`message_delete(workspace, token, msg_id)` physically and irreversibly deletes
an ordinary message authored by that member. It does not cascade to
notifications, memberships, cursors, DM state, or sub-threads.

`message_react(workspace, token, msg_id, reaction)` validates the reaction
against the resident workspace configuration, advances the actor's cursor,
and attempts one atomic best-effort broadcast to the current non-actor
audience. A warning means the commit result may be uncertain, so do not
blind-retry.

Use `channel_show(workspace, token, channel)` to read top-level channel
metadata without activity or cursor effects. Use
`channel_topic(workspace, token, channel, topic)` to set one single-line topic
or clear it with JSON `null`; current channel membership is required.

Returned 19-digit timestamps are already exact JSON strings and can be reused
directly by JavaScript. For `log.since`, pass large Unix-nanosecond or native-id
values as strings; bare JSON integers are accepted only in JavaScript's safe
integer range.

MCP cancellation is not transaction evidence. A canceled stdio request gets
no JSON-RPC response in either era, but synchronous Taut work that already
started may still commit. Inspect current Taut state before retrying a
consuming or mutating call.

## Install and Run

The extension distribution remains `taut-mcp`; its core dependency is the
`taut-chat` distribution, which provides `import taut` plus the `taut` and
`taut-chat` commands. Installed MCP registers `taut mcp` as its primary
extension path (without this package, `taut mcp` exits 1 with an install hint
and stays out of `taut --help`). The standalone `taut-mcp` executable is a
supported convenience alias over the same process runner. Install via core's
`default` or `all` extra:

```bash
pipx install 'taut-chat[default]'
# or include PostgreSQL support as well
pipx install 'taut-chat[all]'
taut mcp
```

Register the installed server with a host that launches stdio MCP processes.
For Claude Code, for example:

```bash
claude mcp add taut -- taut mcp
# Or pin a default project directory and existing member identity:
claude mcp add taut -- taut mcp --workspace /abs/path/to/project --as claude
```

The equivalent host configuration is:

```json
{
  "mcpServers": {
    "taut": {
      "command": "taut",
      "args": ["mcp"]
    }
  }
}
```

Without launch defaults, each identity-using call supplies its own `workspace`
and `token` (with launch defaults, those fields become optional while explicit
per-call values still override them).
Taut prints a new member's continuity token when a command such as
`taut join general` first creates that member, and existing members can read
their token back without side effects via `taut whoami --show-token`. Store
that value in the agent's private state when using explicit tokens; the MCP
server itself does not mint or reveal tokens.

To expose the standalone convenience command too:

```bash
pipx inject --include-apps taut-chat taut-mcp
# uv equivalent for a new tool environment:
uv tool install 'taut-chat[all]' --with-executables-from taut-mcp
```

The tag gate reuses the exact wheel and sdist built by canonical Test. It
stages them in a draft GitHub Release, publishes them through the `taut-mcp`
top-level PyPI Trusted Publisher, verifies filenames and SHA-256 digests, and
only then publishes the GitHub Release as immutable.

From this checkout:

```bash
uv sync --directory extensions/taut_mcp --extra dev
uv run --directory extensions/taut_mcp taut mcp
```

Stdout is reserved for MCP messages. Diagnostics are content-free and go to
stderr.
