"""Argparse CLI for taut-summon: the ``run``/``stop``/``status`` verbs.

Spec references:
- docs/specs/04-summon.md [SUM-3] (argument shape; name/provider resolution)
- docs/specs/02-taut-core.md [TAUT-8.1] (exit-code classes: usage errors
  exit 1, the nothing-summoned class exits 2)

The installed ``taut summon``/``taut dismiss`` adapters and this standalone
console use the same command factories, parser configuration, and controller
operations. Neither console delegates to the other.

``run`` drives the real summon driver (``taut_summon._driver``);
``stop``/``status`` are thin control-plane clients ([SUM-9]) that resolve
NAME → current member → durable session row, then exchange STOP/STATUS
requests with the live driver over its ``sys.*`` control queues. Exit
classes: 0 on a confirmed stop / a live status; 1 when a live driver does
not answer in time; 2 when nothing is summoned (no session row / no live
driver evidence).
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from typing import NoReturn

from taut.commands import CommandContext, CommandError
from taut_summon.commands import DATABASE_HELP, STATUS_FAULT_PLANES, StatusFaultPlane
from taut_summon.models import (
    NothingSummoned,
    SummonedMember,
    SummonOperationError,
    SummonRequest,
    SummonStatus,
)

_STATUS_FAULT_PLANE_ENV = "TAUT_SUMMON_STATUS_FAULT_PLANE"


def _emit_status_fault_plane(plane: StatusFaultPlane, exc: BaseException) -> None:
    if not os.environ.get(_STATUS_FAULT_PLANE_ENV):
        return
    print(
        f"status_fault_plane={plane} error={type(exc).__name__}: {exc}",
        file=sys.stderr,
    )


class _SummonArgumentParser(argparse.ArgumentParser):
    """Parser whose usage errors exit 1, not argparse's default 2.

    Replicates core's ``taut.cli._TautArgumentParser`` idiom (that class is
    private, so it is copied rather than imported): [TAUT-8.1] reserves
    exit 2 for the empty/nothing/not-found class, and a usage error is an
    error. ``--help`` keeps argparse's exit-0 action.
    """

    def error(self, message: str) -> NoReturn:
        self.print_usage(sys.stderr)
        self.exit(1, f"{self.prog}: error: {message}\n")


class _SummonRootArgumentParser(_SummonArgumentParser):
    """Root parser that lets ``run`` intermix options and thread names.

    Python 3.11/3.12 argparse leaves trailing positionals unparsed for
    ``NAME THREAD... --provider X THREAD`` when ``THREAD`` uses ``nargs='*'``.
    ``parse_intermixed_args`` fixes that shape, but cannot be used on a parser
    with subparsers, so the root parser dispatches the ``run`` subcommand to a
    standalone run parser.
    """

    def parse_args(  # type: ignore[override]
        self,
        args: Sequence[str] | None = None,
        namespace: argparse.Namespace | None = None,
    ) -> argparse.Namespace:
        raw = list(args) if args is not None else sys.argv[1:]
        if raw and raw[0] == "run":
            return _parse_run_args(raw[1:], namespace=namespace)
        return super().parse_args(raw, namespace)


def build_parser() -> argparse.ArgumentParser:
    parser = _SummonRootArgumentParser(
        prog="taut-summon",
        description=(
            "Host existing agent harnesses as Taut workspace members. Exit codes: "
            "0 success; 1 error or unresponsive driver; 2 nothing summoned."
        ),
    )
    sub = parser.add_subparsers(
        dest="command",
        parser_class=_SummonArgumentParser,
        title="commands",
        metavar="COMMAND",
        help="Command to run; use 'taut-summon COMMAND --help' for syntax.",
    )

    p = sub.add_parser(
        "run",
        help="Start or resume a summoned harness member.",
    )
    _add_run_arguments(p)

    p = sub.add_parser(
        "stop",
        help="Ask one live summoned driver to stop.",
        description=(
            "Send STOP to the live driver for NAME and wait for its ownership "
            "evidence to be released."
        ),
    )
    from taut_summon.commands.dismiss import (
        configure_parser as configure_dismiss_parser,
    )
    from taut_summon.commands.dismiss import create_command as create_dismiss_command

    configure_dismiss_parser(p, include_db=True)
    p.set_defaults(command_factory=create_dismiss_command)

    p = sub.add_parser(
        "status",
        help="Show live summoned sessions or query one driver.",
        description=(
            "List all live sessions, or request detailed live status from the "
            "driver for NAME."
        ),
    )
    p.add_argument(
        "name",
        metavar="NAME",
        nargs="?",
        help="Current summoned-member name; omit to list all live sessions.",
    )
    p.add_argument("--db", dest="db_path", metavar="PATH", help=DATABASE_HELP)
    p.set_defaults(func=_cmd_status)

    return parser


def _add_run_arguments(
    parser: argparse.ArgumentParser, *, require_name: bool = True
) -> None:
    from taut_summon.commands.summon import configure_parser, create_command

    configure_parser(parser, include_db=True, require_name=require_name)
    parser.set_defaults(command="run", command_factory=create_command)


def _parse_run_args(
    args: Sequence[str],
    *,
    namespace: argparse.Namespace | None = None,
) -> argparse.Namespace:
    parser = _SummonArgumentParser(prog="taut-summon run")
    _add_run_arguments(parser)
    if "--" in args:
        boundary = list(args).index("--")
        head = list(args[:boundary])
        tail = list(args[boundary + 1 :])
        if not tail:
            return parser.parse_args(list(args), namespace)
        head_parser = _SummonArgumentParser(prog="taut-summon run")
        _add_run_arguments(head_parser, require_name=False)
        parsed = head_parser.parse_intermixed_args(head, namespace)
        if parsed.name is None:
            parsed.name = tail[0]
            parsed.threads = tail[1:]
        else:
            parsed.threads = [*parsed.threads, *tail]
        return parsed
    return parser.parse_intermixed_args(list(args), namespace)


def run_request(args: argparse.Namespace) -> SummonRequest:
    """Resolve a parsed ``run`` namespace per [SUM-3].

    The positional is always the member name; threads default to
    ``general`` when none are given. Provider resolution order: (1) the
    ``--provider`` flag; (2) the existing session row's stored provider —
    lands with the session ledger (S3); (3) the name itself as an adapter
    (the first-summon convenience); (4) otherwise the no-adapter error.
    Only steps (1) and (3) exist at the parsing stage this module owns.
    """

    from taut_summon.commands.summon import request_from_args

    return request_from_args(args)


def _db_suffix(args: argparse.Namespace) -> str:
    """Name an explicitly selected database in user-facing diagnostics."""

    return f" (db: {args.db_path})" if args.db_path else ""


def _cmd_status(args: argparse.Namespace) -> int:
    from taut_summon.controller import SummonController

    controller = SummonController(db_path=args.db_path)
    try:
        if args.name is None:
            members = controller.list_live()
            if not members:
                raise NothingSummoned("nothing summoned")
            for member in members:
                _print_live_member(member)
        else:
            _print_status(controller.status(args.name))
    except NothingSummoned as exc:
        _print_operation_error(exc, args)
        return 2
    except SummonOperationError as exc:
        _print_operation_error(exc, args)
        return 1
    return 0


def _print_operation_error(exc: SummonOperationError, args: argparse.Namespace) -> None:
    plane = exc.fault_plane
    if plane in STATUS_FAULT_PLANES:
        _emit_status_fault_plane(plane, exc)
    print(f"{exc}{_db_suffix(args)}", file=sys.stderr)


def _print_live_member(member: SummonedMember) -> None:
    session = member.provider_session_id or "-"
    print(f"{member.name}\t{member.provider}\tlive\tsession={session}")


def _print_status(status: SummonStatus) -> None:
    session = status.provider_session_id or "-"
    lag = status.cursor_lag
    lag_text = (
        ", ".join(f"#{thread}:{count}" for thread, count in sorted(lag.items()))
        if lag
        else "caught up"
    )
    extra = "\t".join(f"{key}={value}" for key, value in sorted(status.details.items()))
    suffix = f"\t{extra}" if extra else ""
    print(
        f"{status.name}\tprovider={status.provider}\tdriver={status.driver}\t"
        f"session={session}\tthreads={status.thread_count}\tlag={lag_text}{suffix}"
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else sys.argv[1:])
    if not hasattr(args, "func") and not hasattr(args, "command_factory"):
        parser.print_help(sys.stderr)
        return 1
    if hasattr(args, "func"):
        return int(args.func(args))
    context = CommandContext(
        db_path=args.db_path,
        as_name=None,
        auth_token=None,
        json=False,
        timestamps=False,
        quiet=False,
        stdin=sys.stdin,
        stdout=sys.stdout,
        stderr=sys.stderr,
    )
    try:
        return int(args.command_factory().run(context, args))
    except CommandError as exc:
        context.stderr.write(f"{exc}\n")
        return exc.exit_code
    finally:
        context.close()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
