"""Command adapter for live-following chat and notification activity."""

from __future__ import annotations

import argparse
from typing import TYPE_CHECKING

from taut.commands._protocol import CommandArgumentParser, CommandContext
from taut.commands._rendering import emit_watch_item

if TYPE_CHECKING:
    from taut.client import Message, Notification


class WatchCommand:
    def configure_parser(self, parser: CommandArgumentParser) -> None:
        parser.description = (
            "Follow selected joined chat threads plus the acting member's "
            "notification inbox. Omit THREAD to follow all current and later "
            "memberships."
        )
        parser.add_argument(
            "threads",
            metavar="THREAD",
            nargs="*",
            help="Joined thread filters; omit to follow every membership.",
        )

    def run(self, context: CommandContext, args: argparse.Namespace) -> int:
        from simplebroker.ext import StopWatching

        client = context.client()
        sink_closed = False

        def handle(item: Message | Notification) -> None:
            nonlocal sink_closed
            if sink_closed:
                raise StopWatching
            try:
                emit_watch_item(
                    item,
                    client=client,
                    json_output=context.json,
                    timestamps=context.timestamps,
                    quiet=context.quiet,
                    stdout=context.stdout,
                    stderr=context.stderr,
                )
                context.stdout.flush()
            except BrokenPipeError:
                sink_closed = True
                raise StopWatching from None

        watcher = client.watch(handle, threads=args.threads or None)
        try:
            watcher.run_forever()
        except KeyboardInterrupt:
            return 0
        finally:
            watcher.stop(join=True, timeout=5.0)
        if sink_closed:
            try:
                context.stdout.close()
            except BrokenPipeError:
                pass
        return 0


def create_command() -> WatchCommand:
    return WatchCommand()
