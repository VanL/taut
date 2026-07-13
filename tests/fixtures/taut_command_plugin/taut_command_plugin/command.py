"""Execution adapter for the installed-wheel command fixture."""

from __future__ import annotations

import argparse

from taut.commands import CommandArgumentParser, CommandContext


class FixtureCommand:
    def configure_parser(self, parser: CommandArgumentParser) -> None:
        parser.add_argument("value", nargs="?", default="ok")

    def run(self, context: CommandContext, args: argparse.Namespace) -> int:
        context.stdout.write(f"fixture:{args.value}\n")
        return 0


def create_command() -> FixtureCommand:
    return FixtureCommand()
