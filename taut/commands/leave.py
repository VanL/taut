"""Command adapter for leaving a joined thread."""

from __future__ import annotations

import argparse

from taut.commands._protocol import CommandArgumentParser, CommandContext
from taut.commands._rendering import emit_messages


class LeaveCommand:
    def configure_parser(self, parser: CommandArgumentParser) -> None:
        parser.description = "Remove the acting member's membership from THREAD."
        parser.add_argument(
            "thread",
            metavar="THREAD",
            help="Joined thread to leave.",
        )

    def run(self, context: CommandContext, args: argparse.Namespace) -> int:
        message = context.client().leave(args.thread)
        emit_messages(
            [message],
            json_output=context.json,
            timestamps=context.timestamps,
            quiet=context.quiet,
            stdout=context.stdout,
            stderr=context.stderr,
        )
        return 0


def create_command() -> LeaveCommand:
    return LeaveCommand()
