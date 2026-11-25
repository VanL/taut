"""Command adapter for replying to a parent message."""

from __future__ import annotations

import argparse

from taut._exceptions import MessageIdResolutionError
from taut.commands._protocol import CommandArgumentParser, CommandContext
from taut.commands._rendering import emit_sent_message, read_text_argument
from taut.commands.syntax import CommandSyntaxError, resolve_reply_positionals

_USAGE_HINT = (
    "; usage: taut reply [THREAD] MSG_ID [TEXT|-] "
    "(MSG_ID is the full 19-digit message id)"
)


class ReplyCommand:
    def configure_parser(self, parser: CommandArgumentParser) -> None:
        parser.description = (
            "Reply to MSG_ID (optionally scoping to THREAD). MSG_ID is the full "
            "19-digit message id. Blank text is ignored with silent exit 2."
        )
        parser.add_argument(
            "thread",
            metavar="THREAD",
            nargs="?",
            help="Optional parent channel containing MSG_ID.",
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
        supplied = [
            item for item in (args.thread, args.msg_id, args.text) if item is not None
        ]
        try:
            try:
                thread, msg_id, raw_text = resolve_reply_positionals(supplied)
            except CommandSyntaxError as exc:
                raise MessageIdResolutionError(str(exc)) from exc
            client = context.client()
            message = client.reply(
                thread,
                msg_id,
                read_text_argument(raw_text, context.stdin),
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
