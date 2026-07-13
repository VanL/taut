"""Command adapter for showing the resolved acting identity."""

from __future__ import annotations

import argparse

from taut.commands._protocol import CommandArgumentParser, CommandContext
from taut.commands._rendering import emit_members


class WhoAmICommand:
    def configure_parser(self, parser: CommandArgumentParser) -> None:
        parser.description = (
            "Show the acting member and optionally the recognition evidence."
        )
        parser.add_argument(
            "--explain",
            action="store_true",
            help="Include captured identity evidence and the rule that matched.",
        )

    def run(self, context: CommandContext, args: argparse.Namespace) -> int:
        member = context.client().whoami(explain=args.explain)
        emit_members(
            [member],
            json_output=context.json,
            quiet=context.quiet,
            stdout=context.stdout,
        )
        return 0


def create_command() -> WhoAmICommand:
    return WhoAmICommand()
