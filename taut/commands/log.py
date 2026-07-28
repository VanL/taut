"""Command adapter for inspecting thread history."""

from __future__ import annotations

import argparse

from taut.commands._protocol import CommandArgumentParser, CommandContext
from taut.commands._rendering import emit_messages


class LogCommand:
    def configure_parser(self, parser: CommandArgumentParser) -> None:
        parser.description = (
            "Show chronological history for THREAD_OR_DM. Direct messages may "
            "use @name-or-alias or a stable dm.d_ handle. Filtering never "
            "changes unread state."
        )
        parser.add_argument(
            "thread",
            metavar="THREAD_OR_DM",
            help=(
                "Channel, subthread, @name-or-alias DM, or stable dm.d_ DM "
                "whose history to show."
            ),
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
        client = context.client()
        messages = client.log(
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
            thread_labels=getattr(client, "last_thread_display_names", None),
        )
        return 0


def create_command() -> LogCommand:
    return LogCommand()
