"""Command adapter for renaming a channel and its sub-threads."""

from __future__ import annotations

import argparse

from taut.commands._protocol import CommandArgumentParser, CommandContext
from taut.commands._rendering import emit_renamed_thread


class RenameCommand:
    def configure_parser(self, parser: CommandArgumentParser) -> None:
        parser.description = (
            "Rename OLD to NEW and move its registered one-level sub-thread names."
        )
        parser.add_argument("old_name", metavar="OLD", help="Current channel name.")
        parser.add_argument("new_name", metavar="NEW", help="New unused channel name.")

    def run(self, context: CommandContext, args: argparse.Namespace) -> int:
        thread = context.client().rename_channel(args.old_name, args.new_name)
        emit_renamed_thread(
            thread,
            old_name=args.old_name,
            json_output=context.json,
            quiet=context.quiet,
            stdout=context.stdout,
        )
        return 0


def create_command() -> RenameCommand:
    return RenameCommand()
