"""Command adapter for starting or resuming one summoned harness."""

from __future__ import annotations

import argparse
import logging
import os

from taut import escape_terminal_text
from taut.commands import CommandArgumentParser, CommandContext, CommandError
from taut_summon._providers import PROVIDER_NAMES
from taut_summon.commands import (
    DATABASE_HELP,
    command_error,
    emit_status_inspection,
)
from taut_summon.models import NothingSummoned, SummonOperationError, SummonRequest

_REGISTERED_PROVIDERS = ", ".join(PROVIDER_NAMES)
_DESCRIPTION = (
    "Start or resume a summoned workspace member, or inspect live sessions "
    "(--status). NAME_OR_PROVIDER is the member name; on first summon it may "
    "also select a provider shortcut. THREAD defaults to general. "
    f"Registered providers: {_REGISTERED_PROVIDERS}."
)
_POLICY_ERROR_MESSAGE = "terminal output policy is unavailable"


class _TerminalSafeFormatter(logging.Formatter):
    """Escape the final Summon-owned log body before handler framing."""

    def format(self, record: logging.LogRecord) -> str:
        formatted = super().format(record)
        try:
            return escape_terminal_text(formatted)
        except RuntimeError:
            return _POLICY_ERROR_MESSAGE


def configure_parser(
    parser: argparse.ArgumentParser,
    *,
    include_db: bool,
    require_name: bool = True,
    include_inspection: bool = False,
    include_json: bool = False,
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
            help="Member name (or optional target NAME with --status).",
        )
    parser.add_argument(
        "threads",
        metavar="THREAD",
        nargs="*",
        help="Threads to join in order (default: general).",
    )
    if include_inspection:
        parser.add_argument(
            "--status",
            action="store_true",
            help="Show live summoned sessions or query one named driver.",
        )
    parser.add_argument(
        "--provider",
        metavar="PROVIDER",
        help=(
            "Select the provider adapter explicitly for a chosen member name "
            f"({_REGISTERED_PROVIDERS})."
        ),
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
    parser.add_argument(
        "--provider-arg",
        dest="provider_args",
        action="append",
        default=None,
        metavar="ARG",
        help=(
            "Append one raw argument to the provider CLI (repeatable; use "
            "--provider-arg=--flag for option-shaped values)."
        ),
    )
    if include_json:
        parser.add_argument(
            "--json",
            action="store_true",
            help="Emit successful stdout records as NDJSON (supported with --status).",
        )
    if include_db:
        parser.add_argument("--db", dest="db_path", metavar="PATH", help=DATABASE_HELP)


def request_from_args(args: argparse.Namespace) -> SummonRequest:
    """Build the public controller request from parsed command-local values."""

    return SummonRequest(
        name=args.name,
        threads=tuple(args.threads) if args.threads else ("general",),
        persona=args.persona,
        system_prompt_file=args.system_prompt_file,
        rate_limit=args.rate_limit,
        attach=args.attach,
        detach=args.detach,
        provider_flag=args.provider,
        takeover=args.takeover,
        provider_args=tuple(getattr(args, "provider_args", None) or ()),
    )


def _has_foreground_run_options(args: argparse.Namespace) -> bool:
    return bool(
        getattr(args, "provider", None) is not None
        or getattr(args, "attach", False)
        or getattr(args, "detach", False)
        or getattr(args, "takeover", False)
        or getattr(args, "persona", None) is not None
        or getattr(args, "system_prompt_file", None) is not None
        or getattr(args, "rate_limit", None) is not None
        or getattr(args, "provider_args", None)
    )


def _usage_error_message(
    args: argparse.Namespace,
    *,
    as_json: bool,
) -> str | None:
    if getattr(args, "status", False):
        if args.threads:
            return "--status accepts at most one NAME"
        if _has_foreground_run_options(args):
            return "--status cannot be combined with foreground summon options"
        return None
    if args.name is None:
        return "the following arguments are required: NAME_OR_PROVIDER"
    if as_json:
        return "--json is only supported with --status"
    return None


def _run_status_inspection(
    context: CommandContext,
    name: str | None,
    *,
    as_json: bool,
) -> int:
    from taut_summon.controller import SummonController

    controller = SummonController(db_path=context.db_path)
    try:
        emit_status_inspection(context.stdout, controller, name, as_json=as_json)
    except NothingSummoned as exc:
        raise command_error(exc, context, exit_code=2) from exc
    except SummonOperationError as exc:
        raise command_error(exc, context, exit_code=1) from exc
    return 0


class SummonCommand:
    def __init__(self) -> None:
        self._parser: argparse.ArgumentParser | None = None

    def configure_parser(self, parser: CommandArgumentParser) -> None:
        self._parser = parser
        parser.enable_intermixed_args()
        configure_parser(
            parser,
            include_db=False,
            require_name=False,
            include_inspection=True,
            include_json=True,
        )

    def run(self, context: CommandContext, args: argparse.Namespace) -> int:
        as_json = bool(context.json or getattr(args, "json", False))
        usage_error = _usage_error_message(args, as_json=as_json)
        if usage_error is not None:
            if not context.quiet and self._parser is not None:
                self._parser.print_usage(context.stderr)
            prog = self._parser.prog if self._parser is not None else "taut summon"
            raise CommandError(f"{prog}: error: {usage_error}", exit_code=1)
        if getattr(args, "status", False):
            return _run_status_inspection(context, args.name, as_json=as_json)
        _configure_logging(context)
        from taut_summon.controller import SummonController
        from taut_summon.interaction import ShellSummonInteraction

        try:
            SummonController(db_path=context.db_path).run_foreground(
                request_from_args(args),
                ShellSummonInteraction(
                    input_stream=context.stdin,
                    output_stream=context.stderr,
                ),
                install_signal_handlers=True,
            )
        except NothingSummoned as exc:
            raise command_error(exc, context, exit_code=2) from exc
        except SummonOperationError as exc:
            raise command_error(exc, context, exit_code=1) from exc
        return 0


def _configure_logging(context: CommandContext) -> None:
    """Own Summon logs without disturbing an embedding host's root logger."""

    level_name = os.environ.get("TAUT_SUMMON_LOG", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    handler = logging.StreamHandler(context.stderr)
    handler.setFormatter(
        _TerminalSafeFormatter("%(asctime)s %(name)s %(levelname)s %(message)s")
    )
    package_logger = logging.getLogger("taut_summon")
    package_logger.handlers.clear()
    package_logger.addHandler(handler)
    package_logger.setLevel(level)
    package_logger.propagate = False


def create_command() -> SummonCommand:
    return SummonCommand()


__all__ = [
    "SummonCommand",
    "configure_parser",
    "create_command",
    "request_from_args",
]
