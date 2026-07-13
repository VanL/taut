"""Command adapter for initializing the resolved Taut storage."""

from __future__ import annotations

import argparse

from taut.commands._protocol import CommandArgumentParser, CommandContext
from taut.commands._rendering import emit_init


class InitCommand:
    def configure_parser(self, parser: CommandArgumentParser) -> None:
        parser.description = (
            "Initialize Taut storage and report whether it was created or already "
            "existed. Running this command more than once is safe."
        )

    def run(self, context: CommandContext, args: argparse.Namespace) -> int:
        from taut.client import TautClient

        result = TautClient.init(db_path=context.db_path)
        emit_init(
            result,
            json_output=context.json,
            quiet=context.quiet,
            stdout=context.stdout,
        )
        return 0


def create_command() -> InitCommand:
    return InitCommand()
