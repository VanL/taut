"""Command adapter for live-following chat and notification activity."""

from __future__ import annotations

import argparse
from typing import TYPE_CHECKING

from taut.commands._protocol import CommandArgumentParser, CommandContext
from taut.commands._rendering import (
    _TerminalOutputPolicyError,
    emit_watch_item,
    preflight_human_output_policy,
)

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

        if not context.json and not context.quiet:
            preflight_human_output_policy()
        client = context.client()
        sink_closed = False
        policy_failure: _TerminalOutputPolicyError | None = None

        def handle(item: Message | Notification) -> None:
            nonlocal policy_failure, sink_closed
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
            except _TerminalOutputPolicyError as exc:
                # Like EPIPE, a renderer policy failure is a terminal delivery
                # failure, not poison queue content. Stop before cursor advance
                # and carry the bootstrap-safe signal out of the reactor.
                policy_failure = exc
                raise StopWatching from None
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
        if policy_failure is not None:
            raise policy_failure
        if sink_closed:
            try:
                context.stdout.close()
            except BrokenPipeError:
                pass
        return 0


def create_command() -> WatchCommand:
    return WatchCommand()
