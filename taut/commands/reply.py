"""Command adapter for replying to a parent message."""

from __future__ import annotations

import argparse

from taut._exceptions import MessageIdResolutionError
from taut.commands._protocol import CommandArgumentParser, CommandContext
from taut.commands._rendering import emit_sent_message, read_text_argument

_USAGE_HINT = (
    "; usage: taut reply THREAD MSG_ID [TEXT|-] "
    "(MSG_ID is the full 19-digit message id)"
)


class ReplyCommand:
    def configure_parser(self, parser: CommandArgumentParser) -> None:
        parser.description = (
            "Reply to MSG_ID in THREAD. MSG_ID is the full 19-digit message id. "
            "Blank text is ignored with silent exit 2."
        )
        parser.add_argument(
            "thread", metavar="THREAD", help="Parent thread containing MSG_ID."
        )
        parser.add_argument(
            "msg_id",
            metavar="MSG_ID",
            help="Full 19-digit message id.",
        )
        parser.add_argument(
            "text",
            metavar="TEXT|-",
            nargs="?",
            help="Reply text, '-' for stdin, or omit when stdin is piped.",
        )

    def run(self, context: CommandContext, args: argparse.Namespace) -> int:
        client = context.client()
        try:
            message = client.reply(
                args.thread,
                args.msg_id,
                read_text_argument(args.text, context.stdin),
            )
        except MessageIdResolutionError as exc:
            raise type(exc)(str(exc) + _USAGE_HINT) from exc
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


def create_command() -> ReplyCommand:
    return ReplyCommand()
