"""Command adapter for reading unread messages."""

from __future__ import annotations

import argparse

from taut._exceptions import TautError
from taut.commands._protocol import CommandArgumentParser, CommandContext
from taut.commands._rendering import emit_messages, write_human_line


class ReadCommand:
    def configure_parser(self, parser: CommandArgumentParser) -> None:
        parser.description = (
            "Read up to 1,000 unread messages per selected conversation. "
            "THREAD_OR_DM accepts a channel, subthread, @name-or-alias, or "
            "stable dm.d_ handle. Omit it to read all joined threads; rerun "
            "until exit 2 to drain larger backlogs."
        )
        parser.add_argument(
            "thread",
            metavar="THREAD_OR_DM",
            nargs="?",
            help=(
                "One joined channel/subthread, @name-or-alias DM, or stable "
                "dm.d_ DM; omit to read every joined thread."
            ),
        )

    def run(self, context: CommandContext, args: argparse.Namespace) -> int:
        if context.quiet:
            write_human_line(
                context.stderr,
                "read does not support -q; poll with taut list -q",
            )
            return 1
        client = context.client()
        messages = client.read_unread(args.thread, advance=False)
        try:
            emit_messages(
                messages,
                json_output=context.json,
                timestamps=context.timestamps,
                quiet=False,
                stdout=context.stdout,
                stderr=context.stderr,
                thread_labels=client.last_thread_display_names,
                on_delivered=lambda message: client.mark_seen(
                    message.thread, message.ts
                ),
            )
        except BrokenPipeError:
            try:
                context.stdout.close()
            except BrokenPipeError:
                pass
            raise TautError("output delivery failed: closed pipe") from None
        return 0


def create_command() -> ReadCommand:
    return ReadCommand()
