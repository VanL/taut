"""Main ``taut mcp`` command adapter."""

from __future__ import annotations

import argparse

from taut.commands import CommandArgumentParser, CommandContext


class _McpCommand:
    def configure_parser(self, parser: CommandArgumentParser) -> None:
        from .cli import configure_parser

        configure_parser(parser)

    def run(self, context: CommandContext, args: argparse.Namespace) -> int:
        del context
        from .cli import run_process

        return run_process(claude_channel=bool(args.claude_channel))


def create_command() -> _McpCommand:
    return _McpCommand()


__all__ = ["create_command"]
