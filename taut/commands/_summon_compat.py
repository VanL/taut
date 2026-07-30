"""Install hint for reserved Summon commands when taut-summon is absent."""

from __future__ import annotations

import argparse

from taut.commands._protocol import CommandArgumentParser, CommandContext


class MissingSummonCommand:
    def __init__(self, *, source_verb: str) -> None:
        self._source_verb = source_verb

    def configure_parser(self, parser: CommandArgumentParser) -> None:
        parser.description = f"Install taut-summon to use 'taut {self._source_verb}'."
        parser.add_argument(
            "rest",
            metavar="ARG",
            nargs=argparse.REMAINDER,
            help="Arguments accepted by the separately installed taut-summon command.",
        )

    def run(self, context: CommandContext, args: argparse.Namespace) -> int:
        if not args.rest or args.rest[0] != "--":
            raise RuntimeError("reserved Summon tail separator is missing")
        context.stderr.write(
            f"taut {self._source_verb} requires the taut-summon extension "
            "(pipx inject taut-chat taut-summon)\n"
        )
        return 1


def create_summon_command() -> MissingSummonCommand:
    return MissingSummonCommand(source_verb="summon")


def create_dismiss_command() -> MissingSummonCommand:
    return MissingSummonCommand(source_verb="dismiss")
