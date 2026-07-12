"""Argparse CLI for taut-summon: the ``run``/``stop``/``status`` verbs.

Spec references:
- docs/specs/04-summon.md [SUM-3] (argument shape; name/provider resolution)
- docs/specs/02-taut-core.md [TAUT-8.1] (exit-code classes: usage errors
  exit 1, the nothing-summoned class exits 2)

Core's ``taut summon``/``taut dismiss`` delegation verbs map argv verbatim
onto ``run``/``stop`` here, so both surfaces share this one contract.

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
import logging
import os
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Literal, NoReturn, TypeVar, cast

from simplebroker.ext import BrokerError

from taut import NotInitializedError, TautClient
from taut_summon._adapter import AdapterError, UnknownAdapterError, get_adapter
from taut_summon._control import ControlClient
from taut_summon._members import find_member as _resolve_member
from taut_summon._state import (
    LEDGER_QUEUE_NAME,
    SummonSessionRow,
    SummonStateError,
    driver_liveness,
    ensure_summon_schema,
    get_session,
    list_sessions,
    release_evidence_confirmed,
)

_LEDGER_QUEUE_NAME = LEDGER_QUEUE_NAME
# Client-side patience for a control round-trip. A status client should wait
# as patiently as a stop client: the driver may be loaded or mid-turn, so a
# reply can take a control cadence or two: reporting "did not respond" early
# is a false negative, not a truthful timeout.
_STOP_TIMEOUT_SECONDS = 30.0
_STATUS_TIMEOUT_SECONDS = 30.0
_STATUS_FAULT_PLANE_ENV = "TAUT_SUMMON_STATUS_FAULT_PLANE"
_CONTROL_FAULT_PLANE_ATTR = "_taut_summon_control_fault_plane"
StatusFaultPlane = Literal[
    "resolve_member",
    "resolve_session",
    "control_write",
    "control_read",
    "driver_snapshot",
]
T = TypeVar("T")

_DATABASE_HELP = (
    "Use an explicit SQLite database path. Omit to discover .taut.toml or "
    ".taut.db from the current directory and its ancestors."
)
_RUN_DESCRIPTION = (
    "Start or resume a summoned workspace member. NAME_OR_PROVIDER is always "
    "the member name; on first summon it may also select a provider shortcut. "
    "THREAD defaults to general."
)


def _emit_status_fault_plane(plane: StatusFaultPlane, exc: BaseException) -> None:
    if not os.environ.get(_STATUS_FAULT_PLANE_ENV):
        return
    print(
        f"status_fault_plane={plane} error={type(exc).__name__}: {exc}",
        file=sys.stderr,
    )


def _with_status_fault_plane(plane: StatusFaultPlane, fn: Callable[[], T]) -> T:
    try:
        return fn()
    except Exception as exc:
        _emit_status_fault_plane(plane, exc)
        raise


def _control_fault_plane(exc: BaseException) -> StatusFaultPlane:
    plane = getattr(exc, _CONTROL_FAULT_PLANE_ATTR, None)
    if plane in ("control_write", "control_read"):
        return cast(StatusFaultPlane, plane)
    return "control_read"


def _is_status_operational_error(exc: BaseException) -> bool:
    if isinstance(exc, BrokerError):
        return True
    if getattr(exc, _CONTROL_FAULT_PLANE_ATTR, None) is not None:
        return True
    return (
        isinstance(exc, RuntimeError)
        and "failed to get database connection:" in str(exc).lower()
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


@dataclass(frozen=True)
class RunRequest:
    """A parsed ``run`` invocation, resolved as far as [SUM-3] parsing goes."""

    name: str
    threads: tuple[str, ...]
    terminal: bool
    persona: str | None
    system_prompt_file: str | None
    rate_limit: int | None
    db_path: str | None
    attach: bool = False
    detach: bool = False
    # The raw --provider flag: None means the name was *implied* by the
    # provider (the convenience form), which selects the [SUM-4]
    # collision rule branch (implied -> pool fallback, chosen -> refuse).
    provider_flag: str | None = None
    takeover: bool = False


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
    p.add_argument(
        "name",
        metavar="NAME",
        help="Current name of the summoned member to stop.",
    )
    p.add_argument("--db", dest="db_path", metavar="PATH", help=_DATABASE_HELP)
    p.set_defaults(func=_cmd_stop)

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
    p.add_argument("--db", dest="db_path", metavar="PATH", help=_DATABASE_HELP)
    p.set_defaults(func=_cmd_status)

    return parser


def _add_run_arguments(
    parser: argparse.ArgumentParser, *, require_name: bool = True
) -> None:
    parser.description = _RUN_DESCRIPTION
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
    parser.add_argument(
        "--attach",
        action="store_true",
        help="Force an interactive terminal attach for onboarding or setup.",
    )
    parser.add_argument(
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
    parser.add_argument("--db", dest="db_path", metavar="PATH", help=_DATABASE_HELP)
    parser.set_defaults(command="run", func=_cmd_run)


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


def run_request(args: argparse.Namespace) -> RunRequest:
    """Resolve a parsed ``run`` namespace per [SUM-3].

    The positional is always the member name; threads default to
    ``general`` when none are given. Provider resolution order: (1) the
    ``--provider`` flag; (2) the existing session row's stored provider —
    lands with the session ledger (S3); (3) the name itself as an adapter
    (the first-summon convenience); (4) otherwise the no-adapter error.
    Only steps (1) and (3) exist at the parsing stage this module owns.
    """

    return RunRequest(
        name=args.name,
        threads=tuple(args.threads) if args.threads else ("general",),
        terminal=args.terminal,
        persona=args.persona,
        system_prompt_file=args.system_prompt_file,
        rate_limit=args.rate_limit,
        db_path=args.db_path,
        attach=args.attach,
        detach=args.detach,
        provider_flag=args.provider,
        takeover=args.takeover,
    )


def _db_suffix(args: argparse.Namespace) -> str:
    """Name an explicitly selected database in user-facing diagnostics."""

    return f" (db: {args.db_path})" if args.db_path else ""


def _cmd_run(args: argparse.Namespace) -> int:
    request = run_request(args)
    _configure_logging()
    # [SUM-3] resolution step 1: an explicit --provider must name a
    # registered adapter before any database work.
    if request.provider_flag is not None:
        try:
            get_adapter(request.provider_flag)
        except UnknownAdapterError as exc:
            print(f"{exc}{_db_suffix(args)}", file=sys.stderr)
            return 1
    from taut_summon._driver import run_driver

    try:
        return run_driver(request)
    except NotInitializedError as exc:
        # No database means no session row can exist, so [SUM-3] step 2 is
        # vacuous: when the implied name is not a registered adapter
        # either, the unknown-adapter error is the truer diagnostic.
        if request.provider_flag is None:
            try:
                get_adapter(request.name)
            except UnknownAdapterError as adapter_exc:
                print(f"{adapter_exc}{_db_suffix(args)}", file=sys.stderr)
                return 1
        print(f"{exc}{_db_suffix(args)}", file=sys.stderr)
        return 1


def _configure_logging() -> None:
    """Send driver logs to stderr; TAUT_SUMMON_LOG selects the level."""

    level_name = os.environ.get("TAUT_SUMMON_LOG", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(
        stream=sys.stderr,
        level=level,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )


def _open_client(args: argparse.Namespace) -> TautClient | None:
    """Open a client, or None when there is no database (nothing summoned)."""

    try:
        return TautClient(db_path=args.db_path)
    except NotInitializedError:
        return None


def _resolve_member_session(client: TautClient, member: Any) -> SummonSessionRow | None:
    queue = client.queue(_LEDGER_QUEUE_NAME)
    try:
        ensure_summon_schema(queue)
        return get_session(queue, member.member_id)
    finally:
        queue.close()


def _resolve_session(
    client: TautClient, name: str
) -> tuple[Any, SummonSessionRow] | None:
    """Resolve NAME → current member → durable session row ([SUM-8] lookup)."""

    member = _resolve_member(client, name)
    if member is None:
        return None
    row = _resolve_member_session(client, member)
    if row is None:
        return None
    return member, row


def _confirm_released(
    client: TautClient,
    member_id: str,
    *,
    driver_pid: int | None,
    driver_start_time: str | None,
    timeout: float,
) -> bool:
    """Poll the ledger until the driver evidence is cleared ([SUM-9] STOP)."""

    queue = client.queue(_LEDGER_QUEUE_NAME)
    deadline = time.monotonic() + timeout
    try:
        while time.monotonic() < deadline:
            row = get_session(queue, member_id)
            stored = (
                (None, None)
                if row is None
                else (row["driver_pid"], row["driver_start_time"])
            )
            if release_evidence_confirmed(stored, (driver_pid, driver_start_time)):
                return True
            time.sleep(0.05)
        return False
    finally:
        queue.close()


def _cmd_stop(args: argparse.Namespace) -> int:
    client = _open_client(args)
    if client is None:
        print(f"nothing summoned as '{args.name}'{_db_suffix(args)}", file=sys.stderr)
        return 2
    try:
        member = _with_status_fault_plane(
            "resolve_member", lambda: _resolve_member(client, args.name)
        )
        row = (
            None
            if member is None
            else _with_status_fault_plane(
                "resolve_session", lambda: _resolve_member_session(client, member)
            )
        )
    except Exception as exc:
        if _is_status_operational_error(exc):
            print(
                f"could not resolve summoned member '{args.name}'{_db_suffix(args)}: "
                f"{exc}",
                file=sys.stderr,
            )
            return 1
        raise
    if member is None or row is None or driver_liveness(row) == "dead":
        print(f"nothing summoned as '{args.name}'{_db_suffix(args)}", file=sys.stderr)
        return 2
    control = ControlClient(
        client.queue,
        member.member_id,
        driver_pid=row["driver_pid"],
        driver_start_time=row["driver_start_time"],
    )
    reply: dict[str, Any] | None
    try:
        try:
            reply = control.request("STOP", timeout=_STOP_TIMEOUT_SECONDS)
        except Exception as exc:
            if _is_status_operational_error(exc):
                print(
                    f"'{member.name}' is summoned but its driver did not stop in time"
                    f"{_db_suffix(args)}: {exc}",
                    file=sys.stderr,
                )
                return 1
            raise
    finally:
        control.close()
    if reply is None:
        print(
            f"'{member.name}' is summoned but its driver did not acknowledge STOP"
            f"{_db_suffix(args)}",
            file=sys.stderr,
        )
        return 1
    if reply.get("status") != "ack":
        error = reply.get("error") or "driver rejected STOP"
        print(
            f"'{member.name}' is summoned but STOP failed{_db_suffix(args)}: {error}",
            file=sys.stderr,
        )
        return 1
    try:
        if _confirm_released(
            client,
            member.member_id,
            driver_pid=row["driver_pid"],
            driver_start_time=row["driver_start_time"],
            timeout=_STOP_TIMEOUT_SECONDS,
        ):
            print(f"stopped '{member.name}'{_db_suffix(args)}")
            return 0
    except Exception as exc:
        if _is_status_operational_error(exc):
            print(
                f"'{member.name}' is summoned but its driver release could not be "
                f"confirmed{_db_suffix(args)}: {exc}",
                file=sys.stderr,
            )
            return 1
        raise
    print(
        f"'{member.name}' is summoned but its driver did not stop in time"
        f"{_db_suffix(args)}",
        file=sys.stderr,
    )
    return 1


def _cmd_status(args: argparse.Namespace) -> int:
    client = _open_client(args)
    if client is None:
        target = f" as '{args.name}'" if args.name else ""
        print(f"nothing summoned{target}{_db_suffix(args)}", file=sys.stderr)
        return 2
    if args.name is None:
        return _status_all(client, args)
    try:
        resolved = _resolve_session(client, args.name)
    except Exception as exc:
        if _is_status_operational_error(exc):
            print(
                f"could not resolve summoned member '{args.name}'{_db_suffix(args)}: "
                f"{exc}",
                file=sys.stderr,
            )
            return 1
        raise
    if resolved is None or driver_liveness(resolved[1]) == "dead":
        print(f"nothing summoned as '{args.name}'{_db_suffix(args)}", file=sys.stderr)
        return 2
    member, row = resolved
    control = ControlClient(
        client.queue,
        member.member_id,
        driver_pid=row["driver_pid"],
        driver_start_time=row["driver_start_time"],
    )
    try:
        try:
            reply = control.request("STATUS", timeout=_STATUS_TIMEOUT_SECONDS)
        except Exception as exc:
            _emit_status_fault_plane(_control_fault_plane(exc), exc)
            if _is_status_operational_error(exc):
                print(
                    f"'{member.name}' is summoned but its driver did not respond"
                    f"{_db_suffix(args)}: {exc}",
                    file=sys.stderr,
                )
                return 1
            raise
    finally:
        control.close()
    if reply is None:
        _emit_status_fault_plane("control_read", TimeoutError("control reply timeout"))
        print(
            f"'{member.name}' is summoned but its driver did not respond"
            f"{_db_suffix(args)}",
            file=sys.stderr,
        )
        return 1
    if reply.get("error") == "status unavailable":
        _emit_status_fault_plane(
            "driver_snapshot", RuntimeError(str(reply.get("error")))
        )
    _print_status(member.name, reply)
    return 0


def _status_all(client: TautClient, args: argparse.Namespace) -> int:
    """Bare ``status``: list every session row with its live/dead evidence."""

    queue = client.queue(_LEDGER_QUEUE_NAME)
    try:
        ensure_summon_schema(queue)
        rows = list_sessions(queue)
    finally:
        queue.close()
    live = [row for row in rows if driver_liveness(row) != "dead"]
    if not live:
        print(f"nothing summoned{_db_suffix(args)}", file=sys.stderr)
        return 2
    names = {member.member_id: member.name for member in client.who()}
    for row in live:
        name = names.get(row["member_id"], row["member_id"])
        session = row["provider_session_id"] or "-"
        print(f"{name}\t{row['provider']}\tlive\tsession={session}")
    return 0


def _print_status(name: str, reply: dict[str, Any]) -> None:
    provider = reply.get("provider", "?")
    session = reply.get("session_id") or "-"
    threads = reply.get("thread_count", "?")
    lag = reply.get("cursor_lag", {})
    lag_text = (
        ", ".join(f"#{thread}:{count}" for thread, count in sorted(lag.items()))
        if isinstance(lag, dict) and lag
        else "caught up"
    )
    reserved = {
        "command",
        "status",
        "request_id",
        "driver",
        "provider",
        "session_id",
        "thread_count",
        "cursor_lag",
    }
    extra = "\t".join(
        f"{key}={value}" for key, value in sorted(reply.items()) if key not in reserved
    )
    suffix = f"\t{extra}" if extra else ""
    print(
        f"{name}\tprovider={provider}\tdriver={reply.get('driver', 'alive')}\t"
        f"session={session}\tthreads={threads}\tlag={lag_text}{suffix}"
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else sys.argv[1:])
    if not hasattr(args, "func"):
        parser.print_help(sys.stderr)
        return 1
    try:
        return int(args.func(args))
    except (AdapterError, BrokerError, SummonStateError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
