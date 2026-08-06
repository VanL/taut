"""Command adapter for exact-message inspection, deletion, and reactions."""

from __future__ import annotations

import argparse

from taut._exceptions import EmptyResultError, NotFoundError
from taut.commands._protocol import CommandArgumentParser, CommandContext
from taut.commands._rendering import (
    emit_message_deletion,
    emit_message_reaction,
    emit_messages,
    emit_search_warnings,
)


class MessageCommand:
    def configure_parser(self, parser: CommandArgumentParser) -> None:
        parser.description = "Inspect, delete, or react to one exact message."
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
        react_parser = subparsers.add_parser(
            "react",
            help="Send a configured reaction to a message's current audience.",
            description=(
                "React to one visible ordinary message. This advances the acting "
                "member's read cursor through the message, then best-effort "
                "broadcasts a consumable notification to its current audience. "
                "The reaction must be enabled by project configuration; repeating "
                "the command sends a duplicate event."
            ),
        )
        react_parser.add_argument(
            "msg_id",
            metavar="MSG_ID",
            help="Exact full 19-digit message id.",
        )
        react_parser.add_argument(
            "reaction",
            metavar="REACTION",
            help="Reaction slug enabled by the resolved project configuration.",
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
            client = context.client()
            deletion = client.delete_message(args.msg_id)
            emit_message_deletion(
                deletion,
                json_output=context.json,
                quiet=context.quiet,
                stdout=context.stdout,
            )
            emit_search_warnings(client, quiet=context.quiet, stderr=context.stderr)
            return 0
        if args.message_command == "react":
            client = context.client()
            try:
                reaction = client.react_to_message(args.msg_id, args.reaction)
            except NotFoundError:
                raise
            except EmptyResultError:
                return 2
            emit_message_reaction(
                client,
                reaction,
                json_output=context.json,
                quiet=context.quiet,
                stdout=context.stdout,
                stderr=context.stderr,
            )
            return 0
        raise RuntimeError(f"unsupported message operation: {args.message_command}")


def create_command() -> MessageCommand:
    return MessageCommand()
