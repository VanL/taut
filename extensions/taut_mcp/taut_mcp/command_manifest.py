"""Lightweight command-extension manifest for the Taut MCP server."""

from taut.commands import CommandSpec

mcp = CommandSpec(
    command_api_version=1,
    name="mcp",
    summary="Run the MCP stdio server.",
    post_verb_globals=frozenset(),
    implementation="taut_mcp.command:create_command",
    raw_stdio_transport=True,
)

__all__ = ["mcp"]
