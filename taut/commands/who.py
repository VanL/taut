"""Command adapter for listing member presence."""

from __future__ import annotations

import argparse

from taut.commands._protocol import CommandArgumentParser, CommandContext
from taut.commands._rendering import emit_members


class WhoCommand:
    def configure_parser(self, parser: CommandArgumentParser) -> None:
        parser.description = (
            "Show all members, or only members of THREAD when supplied."
        )
        parser.add_argument(
            "thread",
            metavar="THREAD",
            nargs="?",
            help="Thread whose members to show; omit for every member.",
        )

    def run(self, context: CommandContext, args: argparse.Namespace) -> int:
        members = context.client().who(args.thread)
        emit_members(
            members,
            json_output=context.json,
            quiet=context.quiet,
            stdout=context.stdout,
        )
        return 0


def create_command() -> WhoCommand:
    return WhoCommand()
