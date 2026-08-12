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

Every identity-using call carries:

- `workspace`: an absolute local directory containing an existing Taut
  project; and
- `token`: an existing Taut continuity token for the intended member.

The token selects identity continuity. It is not authentication,
authorization, or a bearer capability. Treat it as sensitive input: do not
invent it, place it in chat, or log it.

`attach_workspace(workspace, token)` eagerly resolves the project, validates
the member, starts notification observation, and retains one configured
client. Attach is useful when setup cost should be paid before a domain
operation, but it is not a correctness prerequisite.

Each of the 18 CLI-shaped tools also requires `workspace` and `token`. If its
workspace is not resident, that first call performs the same setup lazily and
retains the same client/reactor. Reuse the canonical workspace returned by a
successful call or `list_workspaces` for the fast path.

`detach_workspace` is different: it accepts only the exact canonical
`workspace` and no token because it removes process-local cached state rather
than performing a Taut identity operation. `list_workspaces` takes no
arguments and reports only state resident in the current process.

After process restart, an ordinary CLI-shaped call can reconstruct its
workspace/member binding from `workspace` plus `token`; prior attach state is
never required.

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

The resource is the level-triggered source of truth. Delivery mechanisms are
redundant hints:

- legacy clients use `resources/subscribe` and `resources/unsubscribe`;
- modern clients open a long-lived `subscriptions/listen` request whose
  `notifications.resourceSubscriptions` includes
  `taut://notifications/current`.

Modern listen filters, acknowledgments, subscription ids, fanout,
cancellation, and graceful close are owned by the MCP SDK. A dropped,
duplicated, or delayed hint does not lose Taut data; reread the resource.

`--claude-channel` adds Claude's experimental channel wake only for legacy
clients. It sends a fixed cue to reread the resource and includes no Taut
content. Modern discovery does not advertise a corresponding Claude
capability. The Claude path is host-specific and best-effort; it never
replaces standard tools, resource reads, or subscriptions.

## Tool Notes

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
`taut-chat` distribution, which still provides `import taut` and the `taut`
command. Installed MCP registers `taut mcp` as its primary extension path. The
standalone `taut-mcp` executable is a supported convenience alias over the same
process runner. The repository's coordinated PyPI and immutable GitHub Release
path is configured, but configuring it does not publish a release. Once the
first coordinated PyPI version is published:

```bash
pipx install 'taut-chat[all]'
taut mcp
```

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
