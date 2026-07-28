"""Command adapter for exact-message inspection and deletion."""

from __future__ import annotations

import argparse

from taut.commands._protocol import CommandArgumentParser, CommandContext
from taut.commands._rendering import emit_message_deletion, emit_messages


class MessageCommand:
    def configure_parser(self, parser: CommandArgumentParser) -> None:
        parser.description = (
            "Inspect or delete one message using its exact 19-digit id."
        )
        subparsers = parser.add_subparsers(
            dest="message_command",
            required=True,
            title="operations",
            metavar="OPERATION",
            help=("Message operation; use 'taut message OPERATION --help' for syntax."),
        )
        show_parser = subparsers.add_parser(
            "show",
            help="Show one message and advance its thread's read cursor.",
            description=(
                "Show one exact message from current memberships and advance that "
                "thread's high-water read cursor through it. Use log for "
                "cursor-neutral known-thread inspection."
            ),
        )
        show_parser.add_argument(
            "msg_id",
            metavar="MSG_ID",
            help="Exact full 19-digit message id.",
        )
        delete_parser = subparsers.add_parser(
            "delete",
            help="Physically delete one exact author-owned message.",
            description=(
                "Physically and irreversibly delete one exact ordinary message "
                "authored by the acting member. This may work after leaving and "
                "does not cascade or recall already-fetched output."
            ),
        )
        delete_parser.add_argument(
            "msg_id",
            metavar="MSG_ID",
            help="Exact full 19-digit message id.",
        )

    def run(self, context: CommandContext, args: argparse.Namespace) -> int:
        if args.message_command == "show":
            message = context.client().show_message(args.msg_id)
            emit_messages(
                [message],
                json_output=context.json,
                timestamps=context.timestamps,
                quiet=context.quiet,
                stdout=context.stdout,
                stderr=context.stderr,
            )
            return 0
        if args.message_command == "delete":
            deletion = context.client().delete_message(args.msg_id)
            emit_message_deletion(
                deletion,
                json_output=context.json,
                quiet=context.quiet,
                stdout=context.stdout,
            )
            return 0
        raise RuntimeError(f"unsupported message operation: {args.message_command}")


def create_command() -> MessageCommand:
    return MessageCommand()
