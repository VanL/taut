"""Command adapter for associating the current process claim with a member."""

from __future__ import annotations

import argparse

from taut.commands._protocol import CommandArgumentParser, CommandContext
from taut.commands._rendering import emit_members


class RejoinCommand:
    def configure_parser(self, parser: CommandArgumentParser) -> None:
        parser.description = (
            "Select an existing member by NAME_OR_ALIAS, continuity token, or the "
            "global --as selector, then associate the current process claim with "
            "that member. Rejoin does not rename the member. Continuity tokens are "
            "not authentication."
        )
        parser.add_argument(
            "name_or_alias",
            metavar="NAME_OR_ALIAS",
            nargs="?",
            help="Existing current name or alias; omit when selecting another way.",
        )
        parser.add_argument(
            "--token",
            dest="rejoin_token",
            metavar="TOKEN",
            help="Select the existing member by continuity token.",
        )

    def run(self, context: CommandContext, args: argparse.Namespace) -> int:
        member = context.client().rejoin(
            args.name_or_alias,
            token=args.rejoin_token,
        )
        emit_members(
            [member],
            json_output=context.json,
            quiet=context.quiet,
            stdout=context.stdout,
        )
        return 0


def create_command() -> RejoinCommand:
    return RejoinCommand()
