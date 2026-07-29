# Taut MCP

`taut-mcp` is the optional stdio MCP adapter for Taut. One client launches one
protocol-clean process. That process can keep up to eight local workspaces
resident, but it is not a daemon and stores no durable MCP session state.
Taut databases remain authoritative.

One application surface supports both MCP wire eras:

- legacy clients using protocol `2025-11-25` and `initialize`;
- modern sessionless clients using `2026-07-28` and `server/discover`.

Both receive the same 20 tools, input schemas, tool results, instructions, and
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

Each of the 17 CLI-shaped tools also requires `workspace` and `token`. If its
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

Keep returned 19-digit integer timestamps as decimal text before JavaScript
reuse because they can exceed JavaScript's exact-number range.

MCP cancellation is not transaction evidence. A canceled stdio request gets
no JSON-RPC response in either era, but synchronous Taut work that already
started may still commit. Inspect current Taut state before retrying a
consuming or mutating call.

## Install and Run

The repository publishes `taut-mcp` through its GitHub-only release path;
configuring that path does not publish a release. Core Taut and the MCP
extension must be installed into the same environment. For a release wheel:

```bash
pipx install "git+https://github.com/VanL/taut.git@v0.8.0"
pipx inject --include-apps taut ./taut_mcp-0.8.0-py3-none-any.whl
taut-mcp
```

From this checkout:

```bash
uv sync --directory extensions/taut_mcp --extra dev
uv run --directory extensions/taut_mcp taut-mcp
```

Stdout is reserved for MCP messages. Diagnostics are content-free and go to
stderr.
