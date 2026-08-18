"""TUI-local command syntax layered over the CLI-compatible mirror."""

from __future__ import annotations

from taut.commands.syntax import CommandSyntax, CommandSyntaxProvider


def provide_syntax() -> CommandSyntaxProvider:
    """Publish shell-only textual aliases without changing core CLI syntax."""

    return CommandSyntaxProvider(
        "taut-tui",
        "0.9",
        (
            CommandSyntax(("q",), "Quit the TUI."),
            CommandSyntax(("quit",), "Quit the TUI."),
        ),
    )


__all__ = ["provide_syntax"]
