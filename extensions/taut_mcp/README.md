# Taut MCP

`taut-mcp` is the optional, connection-scoped MCP adapter for Taut. A client
launches one protocol-clean stdio process and explicitly attaches up to eight
existing Taut workspaces with their existing continuity tokens. The process is
not a daemon and retains no attachment state after disconnect.

The version-1 surface is specified in `docs/specs/05-taut-mcp.md`. It exposes
18 explicit tools plus the read-only `taut://notifications/current` resource.
The resource reports notification pointers, not every unread chat message, and
does not claim notifications or advance read cursors.

After attaching a workspace, call `show_message` with its canonical
`workspace` and the exact 19-digit `msg_id` to peek that message. The call
advances the acting member's high-water seen cursor through the message; use
`log` when inspection must be cursor-neutral. Call `delete_message` with the
same inputs to delete an ordinary message authored by the acting member.
Deletion is physical and irreversible, and it does not cascade to
notifications, memberships, cursors, DM state, or sub-threads. Keep message
ids as decimal strings in JavaScript clients because their integer values can
exceed JavaScript's exact-number range.

Call `react_to_message` with the canonical `workspace`, exact `msg_id`, and a
reaction allowed by that workspace's attachment-time configuration. Reacting
advances the actor's high-water cursor and attempts one atomic best-effort
broadcast of a consumable pointer to the current non-actor audience. It does
not create or edit chat history. A warning means the all-or-none broadcast
outcome may be uncertain, so a blind retry can create duplicate reactions.

The repository has a GitHub-only release path for this package, but configuring
that path does not publish a release. After the matching core tag and MCP wheel
exist, install both into one environment:

```bash
pipx install "git+https://github.com/VanL/taut.git@v0.8.0"
pipx inject --include-apps taut ./taut_mcp-0.8.0-py3-none-any.whl
taut-mcp
```

From this checkout, use its package-local environment:

```bash
uv sync --directory extensions/taut_mcp --extra dev
uv run --directory extensions/taut_mcp taut-mcp
```

Workspace attachment tokens are sensitive MCP tool inputs. Supply a token only
to `attach_workspace`; do not repeat it in chat, logs, or ordinary tool calls.
The opt-in `--claude-channel` flag advertises Claude's experimental channel
capability and sends only a fixed cue to reread the notification resource when
its content changes. Channel hints are best-effort and host-specific. Standard
tools, manual resource reads, and resource update subscriptions remain the
portable interface and the source of truth.
