"""Command adapter for claiming pending notification pointers."""

from __future__ import annotations

import argparse

from taut.commands._protocol import CommandArgumentParser, CommandContext
from taut.commands._rendering import emit_notifications


class InboxCommand:
    def configure_parser(self, parser: CommandArgumentParser) -> None:
        parser.description = (
            "Claim pending notification pointers. Source chat remains durable even "
            "though claimed pointers are consumable."
        )

    def run(self, context: CommandContext, args: argparse.Namespace) -> int:
        client = context.client()
        notifications = client.inbox()
        emit_notifications(
            notifications,
            client=client,
            json_output=context.json,
            quiet=context.quiet,
            stdout=context.stdout,
            stderr=context.stderr,
        )
        return 0


def create_command() -> InboxCommand:
    return InboxCommand()
