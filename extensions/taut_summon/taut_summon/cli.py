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
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, NoReturn

from taut import NotInitializedError, TautClient
from taut_summon._adapter import UnknownAdapterError, get_adapter
from taut_summon._control import ControlClient
from taut_summon._state import (
    SummonSessionRow,
    SummonStateError,
    driver_liveness,
    ensure_summon_schema,
    get_session,
    list_sessions,
)

_LEDGER_QUEUE_NAME = "taut_summon_state"
# Client-side patience for a control round-trip. A status client should wait
# as patiently as a stop client: the driver may be loaded or mid-turn, so a
# reply can take a control cadence or two: reporting "did not respond" early
# is a false negative, not a truthful timeout.
_STOP_TIMEOUT_SECONDS = 30.0
_STATUS_TIMEOUT_SECONDS = 30.0


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


@dataclass(frozen=True)
class RunRequest:
    """A parsed ``run`` invocation, resolved as far as [SUM-3] parsing goes."""

    name: str
    threads: tuple[str, ...]
    provider: str
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
    parser = _SummonArgumentParser(prog="taut-summon")
    sub = parser.add_subparsers(dest="command", parser_class=_SummonArgumentParser)

    p = sub.add_parser("run")
    p.add_argument("name", metavar="NAME_OR_PROVIDER")
    p.add_argument("threads", metavar="THREAD", nargs="*")
    p.add_argument("--provider")
    p.add_argument("--terminal", action="store_true")
    p.add_argument("--attach", action="store_true")
    p.add_argument("--detach", action="store_true")
    p.add_argument("--takeover", action="store_true")
    p.add_argument("--persona")
    p.add_argument("--system-prompt-file", dest="system_prompt_file")
    p.add_argument("--rate-limit", dest="rate_limit", type=int)
    p.add_argument("--db", dest="db_path")
    p.set_defaults(func=_cmd_run)

    p = sub.add_parser("stop")
    p.add_argument("name", metavar="NAME")
    p.add_argument("--db", dest="db_path")
    p.set_defaults(func=_cmd_stop)

    p = sub.add_parser("status")
    p.add_argument("name", metavar="NAME", nargs="?")
    p.add_argument("--db", dest="db_path")
    p.set_defaults(func=_cmd_status)

    return parser


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
        provider=args.provider if args.provider is not None else args.name,
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
    # The skeleton echoes the db it parsed so delegation tests can prove
    # --db propagation observably; the real driver replaces the echo
    # with actual target resolution.
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


def _find_member(client: TautClient, name: str) -> Any | None:
    wanted = name.lower()
    for member in client.who():
        if member.name.lower() == wanted:
            return member
        if any(alias.lower() == wanted for alias in member.aliases):
            return member
    return None


def _resolve_session(
    client: TautClient, name: str
) -> tuple[Any, SummonSessionRow] | None:
    """Resolve NAME → current member → durable session row ([SUM-8] lookup)."""

    member = _find_member(client, name)
    if member is None:
        return None
    queue = client.queue(_LEDGER_QUEUE_NAME)
    try:
        ensure_summon_schema(queue)
        row = get_session(queue, member.member_id)
    except SummonStateError:
        return None
    finally:
        queue.close()
    if row is None:
        return None
    return member, row


def _confirm_released(client: TautClient, member_id: str, *, timeout: float) -> bool:
    """Poll the ledger until the driver evidence is cleared ([SUM-9] STOP)."""

    queue = client.queue(_LEDGER_QUEUE_NAME)
    deadline = time.monotonic() + timeout
    try:
        while time.monotonic() < deadline:
            row = get_session(queue, member_id)
            if row is None or row["driver_pid"] is None:
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
    resolved = _resolve_session(client, args.name)
    if resolved is None or driver_liveness(resolved[1]) == "dead":
        print(f"nothing summoned as '{args.name}'{_db_suffix(args)}", file=sys.stderr)
        return 2
    member, _row = resolved
    control = ControlClient(client.queue, member.member_id)
    try:
        control.request("STOP", timeout=_STOP_TIMEOUT_SECONDS)
    finally:
        control.close()
    if _confirm_released(client, member.member_id, timeout=_STOP_TIMEOUT_SECONDS):
        print(f"stopped '{member.name}'{_db_suffix(args)}")
        return 0
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
    resolved = _resolve_session(client, args.name)
    if resolved is None or driver_liveness(resolved[1]) == "dead":
        print(f"nothing summoned as '{args.name}'{_db_suffix(args)}", file=sys.stderr)
        return 2
    member, _row = resolved
    control = ControlClient(client.queue, member.member_id)
    try:
        reply = control.request("STATUS", timeout=_STATUS_TIMEOUT_SECONDS)
    finally:
        control.close()
    if reply is None:
        print(
            f"'{member.name}' is summoned but its driver did not respond"
            f"{_db_suffix(args)}",
            file=sys.stderr,
        )
        return 1
    _print_status(member.name, reply)
    return 0


def _status_all(client: TautClient, args: argparse.Namespace) -> int:
    """Bare ``status``: list every session row with its live/dead evidence."""

    queue = client.queue(_LEDGER_QUEUE_NAME)
    try:
        ensure_summon_schema(queue)
        rows = list_sessions(queue)
    except SummonStateError:
        rows = []
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
    args = build_parser().parse_args(list(argv) if argv is not None else sys.argv[1:])
    if not hasattr(args, "func"):
        build_parser().print_help()
        return 1
    return int(args.func(args))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
