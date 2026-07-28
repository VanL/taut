"""Command adapter for listing threads and unread state."""

from __future__ import annotations

import argparse

from taut.commands._protocol import CommandArgumentParser, CommandContext
from taut.commands._rendering import emit_threads


class ListCommand:
    def configure_parser(self, parser: CommandArgumentParser) -> None:
        parser.description = (
            "List the acting member's threads, or every registered thread."
        )
        mode = parser.add_mutually_exclusive_group()
        mode.add_argument(
            "--all",
            action="store_true",
            dest="all_threads",
            help="List every registered thread, not only joined threads.",
        )
        mode.add_argument(
            "--dms",
            action="store_true",
            help=(
                "List every valid direct-message conversation accessible to "
                "the acting member, including read and empty conversations."
            ),
        )

    def run(self, context: CommandContext, args: argparse.Namespace) -> int:
        client = context.client()
        threads = (
            client.list_direct_messages()
            if args.dms
            else client.list_threads(all_threads=args.all_threads)
        )
        emit_threads(
            threads,
            json_output=context.json,
            quiet=context.quiet,
            stdout=context.stdout,
        )
        return 0


def create_command() -> ListCommand:
    return ListCommand()
