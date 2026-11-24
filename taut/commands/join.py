"""Command adapter for joining a channel."""

from __future__ import annotations

import argparse

from taut.commands._protocol import CommandArgumentParser, CommandContext
from taut.commands._rendering import (
    emit_created_member,
    emit_messages,
    emit_search_warnings,
    thread_heading,
    write_human_line,
)


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
        parser.add_argument(
            "--recent",
            metavar="N",
            type=int,
            help=(
                "Include up to N (1..1000) most recent prior messages in "
                "chronological order without moving any cursor."
            ),
        )

    def run(self, context: CommandContext, args: argparse.Namespace) -> int:
        if args.recent is not None and not 1 <= args.recent <= 1000:
            raise ValueError("recent must be between 1 and 1000")
        client = context.client()
        result = client.join_channel(
            args.thread,
            persona=args.persona,
            new=args.new,
            recent=args.recent or 0,
        )
        emit_created_member(
            client,
            json_output=context.json,
            quiet=context.quiet,
            stdout=context.stdout,
            stderr=context.stderr,
        )
        to_emit = [
            *result.recent,
            *([result.notice] if result.notice is not None else []),
        ]
        if not to_emit:
            if not context.json and not context.quiet:
                write_human_line(
                    context.stdout,
                    thread_heading(result.thread, stream=context.stdout),
                )
        else:
            emit_messages(
                to_emit,
                json_output=context.json,
                timestamps=context.timestamps,
                quiet=context.quiet,
                stdout=context.stdout,
                stderr=context.stderr,
            )
        emit_search_warnings(client, quiet=context.quiet, stderr=context.stderr)
        return 0


def create_command() -> JoinCommand:
    return JoinCommand()
