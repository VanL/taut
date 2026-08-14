"""Lightweight command-extension manifest for the human-first TUI."""

from taut.commands import CommandSpec, GlobalOption

tui = CommandSpec(
    command_api_version=1,
    name="tui",
    summary="Open Taut's human-first terminal interface.",
    post_verb_globals=frozenset({GlobalOption.DB, GlobalOption.AS, GlobalOption.TOKEN}),
    implementation="taut_tui.command:create_command",
    raw_stdio_transport=True,
)

__all__ = ["tui"]
