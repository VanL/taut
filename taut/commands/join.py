"""Command adapter for joining a channel."""

from __future__ import annotations

import argparse

from taut.commands._protocol import CommandArgumentParser, CommandContext
from taut.commands._rendering import emit_created_member, emit_messages


class JoinCommand:
    def configure_parser(self, parser: CommandArgumentParser) -> None:
        parser.description = (
            "Join THREAD at its current end. The acting identity and channel are "
            "created when needed."
        )
        parser.add_argument("thread", metavar="THREAD", help="Channel to join.")
        parser.add_argument(
            "--persona",
            metavar="TEXT",
            help="Set or replace the acting member's persona text.",
        )
        parser.add_argument(
            "--new",
            action="store_true",
            help=(
                "Force creation of a fresh member instead of recognizing an "
                "existing one."
            ),
        )

    def run(self, context: CommandContext, args: argparse.Namespace) -> int:
        client = context.client()
        message = client.join(args.thread, persona=args.persona, new=args.new)
        emit_created_member(
            client,
            json_output=context.json,
            quiet=context.quiet,
            stdout=context.stdout,
            stderr=context.stderr,
        )
        emit_messages(
            [message],
            json_output=context.json,
            timestamps=context.timestamps,
            quiet=context.quiet,
            stdout=context.stdout,
            stderr=context.stderr,
        )
        return 0


def create_command() -> JoinCommand:
    return JoinCommand()
