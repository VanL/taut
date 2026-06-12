"""Argparse CLI for taut.

Spec references:
- docs/specs/02-taut-core.md [TAUT-8.1], [TAUT-8.2]
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from typing import Any

from taut._constants import __version__
from taut._exceptions import (
    AmbiguousMessageError,
    BackendNotSupportedError,
    EmptyResultError,
    IdentityError,
    MembershipError,
    NotFoundError,
    NotInitializedError,
    TautError,
    ThreadNameError,
    TokenError,
)
from taut.client import InitResult, Member, Message, TautClient, Thread


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(_hoist_global_options(list(argv or sys.argv[1:])))
    if not hasattr(args, "func"):
        build_parser().print_help()
        return 1
    try:
        return int(args.func(args))
    except Exception as exc:
        return _handle_error(args, exc)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="taut")
    parser.add_argument("--db", dest="db_path")
    parser.add_argument("--as", dest="as_handle")
    parser.add_argument("--token", dest="auth_token")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("-t", "--timestamps", action="store_true")
    parser.add_argument("-q", "--quiet", action="store_true")
    parser.add_argument("--version", action="version", version=f"taut {__version__}")

    sub = parser.add_subparsers(dest="command")

    p = sub.add_parser("init")
    p.set_defaults(func=_cmd_init)

    p = sub.add_parser("join")
    p.add_argument("thread")
    p.add_argument("--persona")
    p.add_argument("--new", action="store_true")
    p.set_defaults(func=_cmd_join)

    p = sub.add_parser("leave")
    p.add_argument("thread")
    p.set_defaults(func=_cmd_leave)

    p = sub.add_parser("say")
    p.add_argument("thread")
    p.add_argument("text", nargs="?")
    p.set_defaults(func=_cmd_say)

    p = sub.add_parser("reply")
    p.add_argument("thread")
    p.add_argument("msg_id")
    p.add_argument("text", nargs="?")
    p.set_defaults(func=_cmd_reply)

    p = sub.add_parser("read")
    p.add_argument("thread", nargs="?")
    p.set_defaults(func=_cmd_read)

    p = sub.add_parser("log")
    p.add_argument("thread")
    p.add_argument("--since")
    p.add_argument("--limit", type=int)
    p.set_defaults(func=_cmd_log)

    p = sub.add_parser("list")
    p.add_argument("--all", action="store_true", dest="all_threads")
    p.set_defaults(func=_cmd_list)

    p = sub.add_parser("watch")
    p.add_argument("threads", nargs="*")
    p.set_defaults(func=_cmd_watch)

    p = sub.add_parser("who")
    p.add_argument("thread", nargs="?")
    p.set_defaults(func=_cmd_who)

    p = sub.add_parser("whoami")
    p.add_argument("--explain", action="store_true")
    p.set_defaults(func=_cmd_whoami)

    p = sub.add_parser("rejoin")
    p.add_argument("handle", nargs="?")
    p.add_argument("--token", dest="rejoin_token")
    p.set_defaults(func=_cmd_rejoin)

    return parser


def _client(args: argparse.Namespace) -> TautClient:
    return TautClient(
        db_path=args.db_path,
        as_handle=args.as_handle,
        token=args.auth_token,
    )


def _cmd_init(args: argparse.Namespace) -> int:
    result = TautClient.init(db_path=args.db_path)
    _emit_init(args, result)
    return 0


def _cmd_join(args: argparse.Namespace) -> int:
    client = _client(args)
    message = client.join(args.thread, persona=args.persona, new=args.new)
    _emit_created_member(args, client)
    _emit_messages(args, [message])
    return 0


def _cmd_leave(args: argparse.Namespace) -> int:
    client = _client(args)
    message = client.leave(args.thread)
    _emit_messages(args, [message])
    return 0


def _cmd_say(args: argparse.Namespace) -> int:
    client = _client(args)
    message = client.say(args.thread, _read_text_argument(args.text))
    _emit_created_member(args, client)
    if args.json:
        _emit_messages(args, [message])
    elif args.timestamps and not args.quiet:
        print(message.ts)
    return 0


def _cmd_reply(args: argparse.Namespace) -> int:
    client = _client(args)
    message = client.reply(args.thread, args.msg_id, _read_text_argument(args.text))
    _emit_created_member(args, client)
    if args.json:
        _emit_messages(args, [message])
    elif args.timestamps and not args.quiet:
        print(message.ts)
    return 0


def _cmd_read(args: argparse.Namespace) -> int:
    messages = _client(args).read_unread(args.thread)
    _emit_messages(args, messages)
    return 0


def _cmd_log(args: argparse.Namespace) -> int:
    messages = _client(args).log(args.thread, since=args.since, limit=args.limit)
    _emit_messages(args, messages)
    return 0


def _cmd_list(args: argparse.Namespace) -> int:
    threads = _client(args).list_threads(all_threads=args.all_threads)
    _emit_threads(args, threads)
    return 0


def _cmd_watch(args: argparse.Namespace) -> int:
    client = _client(args)

    def handle(message: Message) -> None:
        _emit_messages(args, [message])

    watcher = client.watch(handle, threads=args.threads or None)
    try:
        watcher.run_forever()
    except KeyboardInterrupt:
        return 0
    return 0


def _cmd_who(args: argparse.Namespace) -> int:
    members = _client(args).who(args.thread)
    _emit_members(args, members)
    return 0


def _cmd_whoami(args: argparse.Namespace) -> int:
    member = _client(args).whoami(explain=args.explain)
    _emit_members(args, [member])
    return 0


def _cmd_rejoin(args: argparse.Namespace) -> int:
    client = _client(args)
    member = client.rejoin(args.handle, token=args.rejoin_token)
    _emit_members(args, [member])
    return 0


def _emit_init(args: argparse.Namespace, result: InitResult) -> None:
    if args.quiet:
        return
    if args.json:
        _print_json({"db": result.db, "created": result.created})
    else:
        status = "created" if result.created else "exists"
        print(f"{status}: {result.db}")


def _emit_created_member(args: argparse.Namespace, client: TautClient) -> None:
    member = client.last_created_member
    if member is None:
        return
    if args.json:
        _print_json(_member_object(member, include_token=True))
        return
    if not args.quiet:
        print(f"created new identity '{member.handle}'", file=sys.stderr)
        if member.token:
            print(f"token: {member.token}", file=sys.stderr)
    if client.last_candidates:
        print("note: you may be one of these:", file=sys.stderr)
        for handle, reasons in client.last_candidates:
            print(f"  {handle}  {', '.join(reasons)}", file=sys.stderr)


def _emit_messages(args: argparse.Namespace, messages: list[Message]) -> None:
    if args.quiet:
        return
    for message in messages:
        if message.warning:
            print(f"warning: {message.warning}", file=sys.stderr)
        if args.json:
            _print_json(_message_object(message))
        else:
            prefix = f"{message.ts} " if args.timestamps else ""
            sender = "·" if message.kind == "notice" else message.from_handle
            print(f"{prefix}{message.thread} {sender}: {message.text}")


def _emit_threads(args: argparse.Namespace, threads: list[Thread]) -> None:
    if args.quiet:
        return
    for thread in threads:
        if args.json:
            _print_json(
                {
                    "thread": thread.name,
                    "parent": thread.parent,
                    "unread": thread.unread,
                    "last_ts": thread.last_ts,
                }
            )
        else:
            unread = "unread" if thread.unread else "read"
            print(f"{thread.name}\t{unread}")


def _emit_members(args: argparse.Namespace, members: list[Member]) -> None:
    if args.quiet:
        return
    for member in members:
        if args.json:
            _print_json(_member_object(member, include_token=member.token is not None))
        else:
            persona = f"  {member.persona}" if member.persona else ""
            print(f"{member.handle}\t{member.kind}\t{member.presence}{persona}")
            if member.explain is not None:
                print(json.dumps(member.explain, ensure_ascii=False, sort_keys=True))


def _message_object(message: Message) -> dict[str, Any]:
    return {
        "thread": message.thread,
        "ts": message.ts,
        "from": message.from_handle,
        "kind": message.kind,
        "text": message.text,
    }


def _member_object(member: Member, *, include_token: bool) -> dict[str, Any]:
    obj: dict[str, Any] = {
        "handle": member.handle,
        "kind": member.kind,
        "presence": member.presence,
        "last_active_ts": member.last_active_ts,
        "persona": member.persona,
    }
    if include_token and member.token is not None:
        obj["token"] = member.token
    if member.explain is not None:
        obj["explain"] = member.explain
    return obj


def _print_json(obj: dict[str, Any]) -> None:
    print(json.dumps(obj, ensure_ascii=False, separators=(",", ":")))


def _read_text_argument(text: str | None) -> str:
    if text == "-":
        reader = sys.stdin.read
        return reader()
    if text is not None:
        return text
    if not sys.stdin.isatty():
        reader = sys.stdin.read
        return reader()
    raise ValueError("message text required")


def _handle_error(args: argparse.Namespace, exc: Exception) -> int:
    if isinstance(exc, SystemExit):
        raise exc
    code = _exit_code_for_exception(args, exc)
    if not getattr(args, "quiet", False):
        print(str(exc), file=sys.stderr)
    return code


def _exit_code_for_exception(args: argparse.Namespace, exc: Exception) -> int:
    if isinstance(exc, TokenError):
        return 1
    if isinstance(exc, (EmptyResultError, NotFoundError, MembershipError)):
        return 2
    if isinstance(exc, IdentityError) and getattr(args, "command", None) == "whoami":
        return 2
    if isinstance(
        exc,
        (
            TautError,
            ValueError,
            TokenError,
            ThreadNameError,
            BackendNotSupportedError,
            NotInitializedError,
            AmbiguousMessageError,
        ),
    ):
        return 1
    return 1


def _hoist_global_options(argv: list[str]) -> list[str]:
    """Allow global options before or after subcommands."""

    command = _first_command(argv)
    value_options = {"--db", "--as"}
    if command != "rejoin":
        value_options.add("--token")
    flag_options = {"--json", "-t", "--timestamps", "-q", "--quiet"}
    globals_: list[str] = []
    rest: list[str] = []
    i = 0
    while i < len(argv):
        token = argv[i]
        if token in flag_options:
            globals_.append(token)
            i += 1
            continue
        if token in value_options and i + 1 < len(argv):
            globals_.extend([token, argv[i + 1]])
            i += 2
            continue
        if any(token.startswith(option + "=") for option in value_options):
            globals_.append(token)
            i += 1
            continue
        rest.append(token)
        i += 1
    return [*globals_, *rest]


def _first_command(argv: list[str]) -> str | None:
    commands = {
        "init",
        "join",
        "leave",
        "say",
        "reply",
        "read",
        "log",
        "list",
        "watch",
        "who",
        "whoami",
        "rejoin",
    }
    value_options = {"--db", "--as", "--token"}
    i = 0
    while i < len(argv):
        token = argv[i]
        if token in commands:
            return token
        if token in value_options:
            i += 2
            continue
        i += 1
    return None


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
