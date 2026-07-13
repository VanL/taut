"""Command adapter for inspecting thread history."""

from __future__ import annotations

import argparse

from taut.commands._protocol import CommandArgumentParser, CommandContext
from taut.commands._rendering import emit_messages


class LogCommand:
    def configure_parser(self, parser: CommandArgumentParser) -> None:
        parser.description = (
            "Show chronological history for THREAD. Filtering never changes unread "
            "state."
        )
        parser.add_argument(
            "thread", metavar="THREAD", help="Thread whose history to show."
        )
        parser.add_argument(
            "--since",
            metavar="TS",
            help=(
                "Show ids strictly after TS: ISO 8601, unix seconds/milliseconds/"
                "nanoseconds, or a native 19-digit id."
            ),
        )
        parser.add_argument(
            "--limit",
            metavar="N",
            type=int,
            help="Show the most recent N matching messages in chronological order.",
        )

    def run(self, context: CommandContext, args: argparse.Namespace) -> int:
        messages = context.client().log(
            args.thread,
            since=args.since,
            limit=args.limit,
        )
        emit_messages(
            messages,
            json_output=context.json,
            timestamps=context.timestamps,
            quiet=context.quiet,
            stdout=context.stdout,
            stderr=context.stderr,
        )
        return 0


def create_command() -> LogCommand:
    return LogCommand()
