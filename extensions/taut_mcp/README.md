# Taut MCP

`taut-mcp` is the optional, connection-scoped MCP adapter for Taut. A client
launches one protocol-clean stdio process and explicitly attaches up to eight
existing Taut workspaces with their existing continuity tokens. The process is
not a daemon and retains no attachment state after disconnect.

The version-1 surface is specified in `docs/specs/05-taut-mcp.md`. It exposes
15 explicit tools plus the read-only `taut://notifications/current` resource.
The resource reports notification pointers, not every unread chat message, and
does not claim notifications or advance read cursors.

This package is under implementation and is not yet published. From this
checkout, use its package-local environment:

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
