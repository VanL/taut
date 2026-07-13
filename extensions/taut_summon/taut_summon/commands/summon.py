"""Command adapter for starting or resuming one summoned harness."""

from __future__ import annotations

import argparse
import logging
import os

from taut.commands import CommandArgumentParser, CommandContext
from taut_summon.commands import DATABASE_HELP, command_error
from taut_summon.models import NothingSummoned, SummonOperationError, SummonRequest

_DESCRIPTION = (
    "Start or resume a summoned workspace member. NAME_OR_PROVIDER is always "
    "the member name; on first summon it may also select a provider shortcut. "
    "THREAD defaults to general."
)


def configure_parser(
    parser: argparse.ArgumentParser,
    *,
    include_db: bool,
    require_name: bool = True,
) -> None:
    """Configure the shared summon syntax on a caller-owned parser."""

    parser.description = _DESCRIPTION
    if require_name:
        parser.add_argument(
            "name",
            metavar="NAME_OR_PROVIDER",
            help=(
                "Member name; on first summon, a registered provider name is also "
                "the convenience provider selection."
            ),
        )
    else:
        parser.add_argument(
            "name",
            metavar="NAME_OR_PROVIDER",
            nargs="?",
            help=(
                "Member name; after '--', an option-shaped name is accepted literally."
            ),
        )
    parser.add_argument(
        "threads",
        metavar="THREAD",
        nargs="*",
        help="Threads to join in order (default: general).",
    )
    parser.add_argument(
        "--provider",
        metavar="PROVIDER",
        help="Select the provider adapter explicitly for a chosen member name.",
    )
    parser.add_argument(
        "--terminal",
        action="store_true",
        help="Enable one-thread terminal mode when the adapter supports it.",
    )
    terminal_mode = parser.add_mutually_exclusive_group()
    terminal_mode.add_argument(
        "--attach",
        action="store_true",
        help="Force an interactive terminal attach for onboarding or setup.",
    )
    terminal_mode.add_argument(
        "--detach",
        action="store_true",
        help="Force detached startup without the automatic first-use attach.",
    )
    parser.add_argument(
        "--takeover",
        action="store_true",
        help="Replace a dead, abandoned, or indeterminate driver claim.",
    )
    parser.add_argument(
        "--persona",
        metavar="TEXT",
        help="Set or replace the summoned member's short Taut persona.",
    )
    parser.add_argument(
        "--system-prompt-file",
        dest="system_prompt_file",
        metavar="PATH",
        help="Read the complete harness orientation text from PATH.",
    )
    parser.add_argument(
        "--rate-limit",
        dest="rate_limit",
        metavar="N",
        type=int,
        help="Set the per-window posting-rate circuit-breaker threshold.",
    )
    if include_db:
        parser.add_argument("--db", dest="db_path", metavar="PATH", help=DATABASE_HELP)


def request_from_args(args: argparse.Namespace) -> SummonRequest:
    """Build the public controller request from parsed command-local values."""

    return SummonRequest(
        name=args.name,
        threads=tuple(args.threads) if args.threads else ("general",),
        terminal=args.terminal,
        persona=args.persona,
        system_prompt_file=args.system_prompt_file,
        rate_limit=args.rate_limit,
        attach=args.attach,
        detach=args.detach,
        provider_flag=args.provider,
        takeover=args.takeover,
    )


class SummonCommand:
    def configure_parser(self, parser: CommandArgumentParser) -> None:
        parser.enable_intermixed_args()
        configure_parser(parser, include_db=False)

    def run(self, context: CommandContext, args: argparse.Namespace) -> int:
        _configure_logging(context)
        from taut_summon.controller import SummonController
        from taut_summon.interaction import ShellSummonInteraction

        try:
            SummonController(db_path=context.db_path).run_foreground(
                request_from_args(args), ShellSummonInteraction()
            )
        except NothingSummoned as exc:
            raise command_error(exc, context, exit_code=2) from exc
        except SummonOperationError as exc:
            raise command_error(exc, context, exit_code=1) from exc
        return 0


def _configure_logging(context: CommandContext) -> None:
    """Send driver logs to the authoritative command error stream."""

    level_name = os.environ.get("TAUT_SUMMON_LOG", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(
        stream=context.stderr,
        level=level,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )


def create_command() -> SummonCommand:
    return SummonCommand()


__all__ = ["SummonCommand", "configure_parser", "create_command", "request_from_args"]
