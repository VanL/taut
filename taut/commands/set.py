"""Command adapter for nested acting-member property changes."""

from __future__ import annotations

import argparse

from taut.commands._protocol import CommandArgumentParser, CommandContext
from taut.commands._rendering import emit_members


class SetCommand:
    def configure_parser(self, parser: CommandArgumentParser) -> None:
        parser.description = (
            "Change one acting-member property through a nested command."
        )
        subparsers = parser.add_subparsers(
            dest="set_command",
            required=True,
            title="properties",
            metavar="PROPERTY",
            help="Property to change; use 'taut set PROPERTY --help' for syntax.",
        )
        name_parser = subparsers.add_parser(
            "name",
            help="Change the current display and routing name.",
            description=(
                "Change the acting member's current display and routing name without "
                "rewriting old messages."
            ),
        )
        name_parser.add_argument(
            "name",
            metavar="NAME",
            help="New unique member name.",
        )

    def run(self, context: CommandContext, args: argparse.Namespace) -> int:
        if args.set_command != "name":
            raise RuntimeError(f"unsupported set property: {args.set_command}")
        member = context.client().set_name(args.name)
        emit_members(
            [member],
            json_output=context.json,
            quiet=context.quiet,
            stdout=context.stdout,
        )
        return 0


def create_command() -> SetCommand:
    return SetCommand()
