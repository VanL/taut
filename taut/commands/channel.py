"""Command adapter for channel metadata and rename operations.

Spec references:
- docs/specs/02-taut-core.md [TAUT-4.4], [TAUT-8.1], [TAUT-8.2]
- docs/specs/03-identity-addressing-notifications.md [IAN-8.1]
"""

from __future__ import annotations

import argparse

from taut.commands._protocol import CommandArgumentParser, CommandContext
from taut.commands._rendering import (
    emit_channel,
    emit_renamed_thread,
    emit_search_warnings,
)


class ChannelCommand:
    """Own the required nested grammar for top-level channel operations."""

    def configure_parser(self, parser: CommandArgumentParser) -> None:
        parser.description = (
            "Inspect or change one registered top-level channel. "
            "Exit codes: 0 success; 1 error; 2 missing or inaccessible."
        )
        subparsers = parser.add_subparsers(
            dest="channel_command",
            required=True,
            title="operations",
            metavar="OPERATION",
            help=("Channel operation; use 'taut channel OPERATION --help' for syntax."),
        )

        show_parser = subparsers.add_parser(
            "show",
            help="Show current metadata for one top-level channel.",
            description=(
                "Show current metadata for one registered top-level channel. "
                "Reads only shared registry state: it does not resolve identity, "
                "touch activity, inspect a broker queue, or move a cursor."
            ),
        )
        show_parser.add_argument(
            "channel",
            metavar="CHANNEL",
            help="Registered top-level channel name.",
        )

        topic_parser = subparsers.add_parser(
            "topic",
            help="Set or explicitly clear one channel's topic.",
            description=(
                "Set or clear a top-level channel topic. Setting requires current "
                "membership. Text must be nonblank, contain no line break, and "
                "contain at most 500 Unicode code points. Use --clear to remove it."
            ),
        )
        topic_parser.add_argument(
            "channel",
            metavar="CHANNEL",
            help="Registered top-level channel name.",
        )
        topic_value = topic_parser.add_mutually_exclusive_group(required=True)
        topic_value.add_argument(
            "topic",
            metavar="TEXT",
            nargs="?",
            help="Exact topic text; shell quoting is required for spaces.",
        )
        topic_value.add_argument(
            "--clear",
            action="store_true",
            help="Explicitly remove the current topic.",
        )

        rename_parser = subparsers.add_parser(
            "rename",
            help="Rename a channel and its registered one-level sub-threads.",
            description=(
                "Rename OLD to NEW and move its registered one-level sub-thread "
                "names. Repeating the same command finishes an incomplete rename."
            ),
        )
        rename_parser.add_argument(
            "old_name",
            metavar="OLD",
            help="Current channel name.",
        )
        rename_parser.add_argument(
            "new_name",
            metavar="NEW",
            help="New unused channel name.",
        )

    def run(self, context: CommandContext, args: argparse.Namespace) -> int:
        if args.channel_command == "show":
            channel = context.client().get_channel(args.channel)
            emit_channel(
                channel,
                json_output=context.json,
                quiet=context.quiet,
                stdout=context.stdout,
            )
            return 0
        if args.channel_command == "topic":
            topic = None if args.clear else args.topic
            channel = context.client().set_channel_topic(args.channel, topic)
            emit_channel(
                channel,
                json_output=context.json,
                quiet=context.quiet,
                stdout=context.stdout,
            )
            return 0
        if args.channel_command == "rename":
            client = context.client()
            thread = client.rename_channel(args.old_name, args.new_name)
            emit_renamed_thread(
                thread,
                old_name=args.old_name,
                json_output=context.json,
                quiet=context.quiet,
                stdout=context.stdout,
            )
            emit_search_warnings(client, quiet=context.quiet, stderr=context.stderr)
            return 0
        raise RuntimeError(f"unsupported channel operation: {args.channel_command}")


def create_command() -> ChannelCommand:
    return ChannelCommand()
