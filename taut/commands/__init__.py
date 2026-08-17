"""Public command-extension interface for Taut.

Spec references:
- docs/specs/02-taut-core.md [TAUT-8.3], [TAUT-8.6]
"""

from __future__ import annotations

from taut.commands._protocol import (
    Command,
    CommandArgumentParser,
    CommandContext,
    CommandError,
    CommandFactory,
    CommandSpec,
    GlobalOption,
)
from taut.commands.syntax import (
    CommandInput,
    CommandInvocation,
    CommandPath,
    CommandSyntax,
    CommandSyntaxDiscovery,
    CommandSyntaxError,
    CommandSyntaxProvider,
    ExclusiveGroupSyntax,
    GlobalOptionSyntax,
    OptionSyntax,
    PositionalSyntax,
    RootCommandSyntax,
    ValueKind,
    command_nodes,
    core_command_syntax,
    discover_command_syntax,
    format_command_syntax,
    merge_command_syntax,
    parse_command_line,
)

__all__ = [
    "Command",
    "CommandArgumentParser",
    "CommandContext",
    "CommandError",
    "CommandFactory",
    "CommandInput",
    "CommandInvocation",
    "CommandPath",
    "CommandSpec",
    "CommandSyntax",
    "CommandSyntaxDiscovery",
    "CommandSyntaxError",
    "CommandSyntaxProvider",
    "ExclusiveGroupSyntax",
    "GlobalOption",
    "GlobalOptionSyntax",
    "OptionSyntax",
    "PositionalSyntax",
    "RootCommandSyntax",
    "ValueKind",
    "command_nodes",
    "core_command_syntax",
    "discover_command_syntax",
    "format_command_syntax",
    "merge_command_syntax",
    "parse_command_line",
]
