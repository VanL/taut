"""Command adapter for stopping one live summoned harness."""

from __future__ import annotations

import argparse

from taut.commands import CommandArgumentParser, CommandContext
from taut_summon.commands import DATABASE_HELP, _write_human_line, command_error
from taut_summon.models import NothingSummoned, SummonOperationError

_DESCRIPTION = (
    "Send STOP to the live driver for NAME and wait for its ownership "
    "evidence to be released."
)


def configure_parser(
    parser: argparse.ArgumentParser,
    *,
    include_db: bool,
) -> None:
    """Configure the shared dismiss syntax on a caller-owned parser."""

    parser.description = _DESCRIPTION
    parser.add_argument(
        "name",
        metavar="NAME",
        help="Current name of the summoned member to stop.",
    )
    if include_db:
        parser.add_argument("--db", dest="db_path", metavar="PATH", help=DATABASE_HELP)


class DismissCommand:
    def configure_parser(self, parser: CommandArgumentParser) -> None:
        configure_parser(parser, include_db=False)

    def run(self, context: CommandContext, args: argparse.Namespace) -> int:
        from taut_summon.controller import SummonController

        try:
            result = SummonController(db_path=context.db_path).stop(args.name)
        except NothingSummoned as exc:
            raise command_error(exc, context, exit_code=2) from exc
        except SummonOperationError as exc:
            raise command_error(exc, context, exit_code=1) from exc
        suffix = f" (db: {context.db_path})" if context.db_path else ""
        _write_human_line(context.stdout, f"stopped '{result.name}'{suffix}")
        return 0


def create_command() -> DismissCommand:
    return DismissCommand()


__all__ = ["DismissCommand", "configure_parser", "create_command"]
