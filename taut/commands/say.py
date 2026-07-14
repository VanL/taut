"""Command adapter for posting one message through the core client."""

from __future__ import annotations

import argparse

from taut.commands._protocol import CommandArgumentParser, CommandContext
from taut.commands._rendering import emit_sent_message, read_text_argument


class SayCommand:
    """Parse and render ``taut say`` without owning messaging behavior."""

    def configure_parser(self, parser: CommandArgumentParser) -> None:
        parser.description = (
            "Post TEXT to TARGET. Use '-' for stdin; when TEXT is omitted, piped "
            "stdin is read automatically. Blank text is ignored with silent exit 2; "
            "other UTF-8 is preserved exactly."
        )
        parser.add_argument(
            "target",
            metavar="TARGET",
            help="Channel, sub-thread, or @NAME direct-message target.",
        )
        parser.add_argument(
            "text",
            metavar="TEXT|-",
            nargs="?",
            help="Message text, '-' for stdin, or omit when stdin is piped.",
        )

    def run(self, context: CommandContext, args: argparse.Namespace) -> int:
        client = context.client()
        message = client.say(
            args.target,
            read_text_argument(args.text, context.stdin),
        )
        emit_sent_message(
            client,
            message,
            json_output=context.json,
            timestamps=context.timestamps,
            quiet=context.quiet,
            stdout=context.stdout,
            stderr=context.stderr,
        )
        return 0


def create_command() -> SayCommand:
    return SayCommand()
