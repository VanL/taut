"""Argparse CLI for taut.

Spec references:
- docs/specs/02-taut-core.md [TAUT-8.1], [TAUT-8.2]
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from collections.abc import Sequence
from datetime import datetime
from typing import Any, NoReturn, TextIO

from taut._constants import __version__
from taut._exceptions import (
    EmptyResultError,
    IdentityError,
    MembershipError,
    NotFoundError,
    TokenError,
)
from taut.client import InitResult, Member, Message, Notification, TautClient, Thread


def main(argv: Sequence[str] | None = None) -> int:
    raw = list(argv or sys.argv[1:])
    command, boundary = _find_first_command(raw)
    if command in _DELEGATED_VERBS:
        # Delegation verbs ([TAUT-8.1] D4) hand their whole tail to the
        # taut-summon extension verbatim ([SUM-3]) — including tokens
        # that spell core globals, so the split happens on the RAW argv
        # before any hoisting; only the pre-verb head is core's. (The
        # tail is also kept away from argparse because REMAINDER
        # mis-parses a leading option-like token.)
        head = _hoist_global_options([*raw[:boundary], command])
        args = build_parser().parse_args(head)
        args.rest = raw[boundary + 1 :]
    else:
        args = build_parser().parse_args(_hoist_global_options(raw))
    if not hasattr(args, "func"):
        build_parser().print_help()
        return 1
    try:
        return int(args.func(args))
    except Exception as exc:
        return _handle_error(args, exc)


class _TautArgumentParser(argparse.ArgumentParser):
    """Parser whose usage errors exit 1, not argparse's default 2.

    [TAUT-8.1]: exit 2 is reserved for the empty/nothing-new/not-found
    class; a usage error (unknown flag, unknown subcommand, malformed
    argument) is an error and must exit 1. `--help`/`--version` keep
    argparse's exit-0 actions.
    """

    def error(self, message: str) -> NoReturn:
        self.print_usage(sys.stderr)
        self.exit(1, f"{self.prog}: error: {message}\n")


def build_parser() -> argparse.ArgumentParser:
    parser = _TautArgumentParser(prog="taut")
    parser.add_argument("--db", dest="db_path")
    parser.add_argument("--as", dest="as_name")
    parser.add_argument("--token", dest="auth_token")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("-t", "--timestamps", action="store_true")
    parser.add_argument("-q", "--quiet", action="store_true")
    parser.add_argument("--version", action="version", version=f"taut {__version__}")

    sub = parser.add_subparsers(dest="command", parser_class=_TautArgumentParser)

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
    p.add_argument("target")
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

    p = sub.add_parser("inbox")
    p.set_defaults(func=_cmd_inbox)

    p = sub.add_parser("set")
    set_sub = p.add_subparsers(
        dest="set_command", required=True, parser_class=_TautArgumentParser
    )
    p_name = set_sub.add_parser("name")
    p_name.add_argument("name")
    p_name.set_defaults(func=_cmd_set_name)

    p = sub.add_parser("rename")
    p.add_argument("old_name")
    p.add_argument("new_name")
    p.set_defaults(func=_cmd_rename)

    p = sub.add_parser("who")
    p.add_argument("thread", nargs="?")
    p.set_defaults(func=_cmd_who)

    p = sub.add_parser("whoami")
    p.add_argument("--explain", action="store_true")
    p.set_defaults(func=_cmd_whoami)

    p = sub.add_parser("rejoin")
    p.add_argument("name_or_alias", nargs="?")
    p.add_argument("--token", dest="rejoin_token")
    p.set_defaults(func=_cmd_rejoin)

    # Delegation verbs ([TAUT-8.1] D4, spec 04 [SUM-3]): the tail is
    # captured whole and handed to the taut-summon extension. `main()`
    # overrides the REMAINDER capture with a verbatim split (see there).
    p = sub.add_parser("summon")
    p.add_argument("rest", nargs=argparse.REMAINDER)
    p.set_defaults(func=_cmd_summon)

    p = sub.add_parser("dismiss")
    p.add_argument("rest", nargs=argparse.REMAINDER)
    p.set_defaults(func=_cmd_dismiss)

    return parser


def _client(args: argparse.Namespace) -> TautClient:
    return TautClient(
        db_path=args.db_path,
        as_name=args.as_name,
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
    message = client.say(args.target, _read_text_argument(args.text))
    _emit_created_member(args, client)
    if args.json:
        _emit_messages(args, [message])
    elif args.timestamps and not args.quiet:
        print(message.ts)
    _emit_notification_warnings(args, client)
    return 0


def _cmd_reply(args: argparse.Namespace) -> int:
    client = _client(args)
    message = client.reply(args.thread, args.msg_id, _read_text_argument(args.text))
    _emit_created_member(args, client)
    if args.json:
        _emit_messages(args, [message])
    elif args.timestamps and not args.quiet:
        print(message.ts)
    _emit_notification_warnings(args, client)
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

    def handle(item: Message | Notification) -> None:
        if isinstance(item, Notification):
            _emit_notifications(args, [item])
        else:
            _emit_messages(args, [item])

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
    member = client.rejoin(args.name_or_alias, token=args.rejoin_token)
    _emit_members(args, [member])
    return 0


def _cmd_inbox(args: argparse.Namespace) -> int:
    notifications = _client(args).inbox()
    _emit_notifications(args, notifications)
    return 0


def _cmd_set_name(args: argparse.Namespace) -> int:
    member = _client(args).set_name(args.name)
    _emit_members(args, [member])
    return 0


# summon/dismiss ([TAUT-8.1] D4): thin hand-off to the taut-summon
# extension — zero summon logic, zero new core dependency. The verbs map
# argv verbatim onto the extension's entry points ([SUM-3]):
# `taut summon X ...` == `taut-summon run X ...`; `taut dismiss X` ==
# `taut-summon stop X`.
_DELEGATED_VERBS = {"summon": "run", "dismiss": "stop"}


def _cmd_summon(args: argparse.Namespace) -> int:
    return _delegate_to_summon("summon", args)


def _cmd_dismiss(args: argparse.Namespace) -> int:
    return _delegate_to_summon("dismiss", args)


def _delegate_to_summon(command: str, args: argparse.Namespace) -> int:
    if importlib.util.find_spec("taut_summon") is None:
        print(
            f"taut {command} requires the taut-summon extension "
            "(pipx inject taut taut-summon)",
            file=sys.stderr,
        )
        return 1
    from taut_summon.cli import main as summon_main

    ext_argv = [_DELEGATED_VERBS[command]]
    if args.db_path:
        # Re-attach the hoisted global --db ahead of the verbatim tail —
        # never after it, where a `--` in the tail would demote it to a
        # positional.
        ext_argv += ["--db", args.db_path]
    ext_argv += list(args.rest)
    return int(summon_main(ext_argv))


def _cmd_rename(args: argparse.Namespace) -> int:
    thread = _client(args).rename_channel(args.old_name, args.new_name)
    if args.quiet:
        return 0
    if args.json:
        _print_json(_thread_object(thread))
    else:
        print(f"renamed {args.old_name} to {thread.name}")
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
        print(f"created new identity '{member.name}'", file=sys.stderr)
        if member.token:
            print(f"token: {member.token}", file=sys.stderr)
    if client.last_candidates:
        print("note: you may be one of these:", file=sys.stderr)
        for name, reasons in client.last_candidates:
            print(f"  {name}  {', '.join(reasons)}", file=sys.stderr)


def _emit_notification_warnings(
    args: argparse.Namespace,
    client: TautClient,
) -> None:
    if args.quiet:
        return
    for warning in client.last_notification_warnings:
        # Entries are self-describing (constructed with their failure or
        # suppression context in the client layer); render them verbatim.
        print(f"warning: {warning}", file=sys.stderr)


def _emit_messages(args: argparse.Namespace, messages: list[Message]) -> None:
    if args.quiet:
        return
    if args.json:
        for message in messages:
            if message.warning:
                print(f"warning: {message.warning}", file=sys.stderr)
            _print_json(_message_object(message))
        return
    for thread, grouped in _group_messages_by_thread(messages).items():
        print(_thread_heading(thread))
        sender_width = max(
            [6]
            + [
                len(message.from_name)
                for message in grouped
                if message.kind != "notice"
            ]
        )
        for message in grouped:
            if message.warning:
                print(f"warning: {message.warning}", file=sys.stderr)
            print(
                _human_message_row(
                    message, timestamps=args.timestamps, sender_width=sender_width
                )
            )


def _emit_threads(args: argparse.Namespace, threads: list[Thread]) -> None:
    if args.quiet:
        return
    for thread in threads:
        if args.json:
            _print_json(_thread_object(thread))
        else:
            print(f"{thread.name}  {_format_unread_count(thread.unread_count)} unread")


def _emit_members(args: argparse.Namespace, members: list[Member]) -> None:
    if args.quiet:
        return
    for member in members:
        if args.json:
            _print_json(_member_object(member, include_token=member.token is not None))
        else:
            persona = f"  {member.persona}" if member.persona else ""
            print(f"{member.name}\t{member.kind}\t{member.presence}{persona}")
            if member.explain is not None:
                print(json.dumps(member.explain, ensure_ascii=False, sort_keys=True))


def _emit_notifications(
    args: argparse.Namespace,
    notifications: list[Notification],
) -> None:
    if args.quiet:
        return
    for notification in notifications:
        if notification.warning:
            print(f"warning: {notification.warning}", file=sys.stderr)
        if args.json:
            _print_json(_notification_object(notification))
        elif notification.type == "mention":
            print(
                f"{notification.actor_name} mentioned you in "
                f"{notification.thread} at {notification.message_ts}"
            )
        elif notification.type == "dm_started":
            print(
                f"{notification.actor_name} started a direct message "
                f"in {notification.thread}"
            )
        else:
            print(notification.raw or "foreign notification")


def _message_object(message: Message) -> dict[str, Any]:
    return {
        "thread": message.thread,
        "ts": message.ts,
        "from_id": message.from_id,
        "from": message.from_name,
        "kind": message.kind,
        "text": message.text,
    }


def _member_object(member: Member, *, include_token: bool) -> dict[str, Any]:
    obj: dict[str, Any] = {
        "member_id": member.member_id,
        "name": member.name,
        "aliases": list(member.aliases),
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


def _thread_object(thread: Thread) -> dict[str, Any]:
    obj: dict[str, Any] = {
        "thread": thread.name,
        "kind": thread.kind,
        "parent": thread.parent,
        "unread": thread.unread,
        "last_ts": thread.last_ts,
    }
    if thread.kind == "dm":
        obj["members"] = list(thread.members)
    return obj


def _notification_object(notification: Notification) -> dict[str, Any]:
    obj: dict[str, Any] = {
        "type": notification.type,
        "to_id": notification.to_id,
        "actor_id": notification.actor_id,
        "actor_name": notification.actor_name,
        "thread": notification.thread,
        "message_ts": notification.message_ts,
    }
    if notification.matched is not None:
        obj["matched"] = notification.matched
    if notification.warning is not None:
        obj["warning"] = notification.warning
    if notification.raw is not None and notification.type == "foreign":
        obj["raw"] = notification.raw
    return obj


def _print_json(obj: dict[str, Any]) -> None:
    print(json.dumps(obj, ensure_ascii=False, separators=(",", ":")))


def _group_messages_by_thread(messages: list[Message]) -> dict[str, list[Message]]:
    grouped: dict[str, list[Message]] = {}
    for message in messages:
        grouped.setdefault(message.thread, []).append(message)
    return grouped


def _thread_heading(thread: str, *, stream: TextIO | None = None) -> str:
    prefix, rule, _notice = _human_glyphs(stream or sys.stdout)
    return f"{prefix} {thread} {rule * 38}"


def _human_message_row(
    message: Message,
    *,
    timestamps: bool,
    sender_width: int,
    stream: TextIO | None = None,
) -> str:
    id_column = f"{message.ts}  " if timestamps else ""
    clock = _format_message_time(message.ts)
    if message.kind == "notice":
        _prefix, _rule, notice = _human_glyphs(stream or sys.stdout)
        return f"  {id_column}{clock} {notice} {message.text}"
    return f"  {id_column}{clock} {message.from_name:<{sender_width}}  {message.text}"


def _human_glyphs(stream: TextIO) -> tuple[str, str, str]:
    if _stream_can_encode("─·", stream):
        return "──", "─", "·"
    return "--", "-", "-"


def _stream_can_encode(text: str, stream: TextIO) -> bool:
    encoding = stream.encoding or sys.getdefaultencoding()
    errors = stream.errors or "strict"
    try:
        text.encode(encoding, errors=errors)
    except UnicodeEncodeError:
        return False
    return True


def _format_message_time(ts: int) -> str:
    return datetime.fromtimestamp(ts / 1_000_000_000).strftime("%H:%M")


def _format_unread_count(count: int) -> str:
    return "999+" if count >= 1000 else str(count)


def _read_text_argument(text: str | None) -> str:
    if text == "-":
        return _read_stdin_text()
    if text is not None:
        return text
    if not sys.stdin.isatty():
        return _read_stdin_text()
    raise ValueError("message text required")


def _read_stdin_text() -> str:
    """Read piped message text, naming stdin in the undecodable-bytes
    diagnostic (the raw codec error does not say which input failed)."""

    reader = sys.stdin.read
    try:
        return reader()
    except UnicodeDecodeError as exc:
        raise ValueError(f"stdin is not valid UTF-8: {exc}") from exc


def _handle_error(args: argparse.Namespace, exc: Exception) -> int:
    if isinstance(exc, SystemExit):
        raise exc
    code = _exit_code_for_exception(exc)
    if not getattr(args, "quiet", False):
        print(str(exc), file=sys.stderr)
    return code


def _exit_code_for_exception(exc: Exception) -> int:
    if isinstance(exc, TokenError):
        return 1
    if isinstance(exc, (EmptyResultError, NotFoundError, MembershipError)):
        return 2
    if isinstance(exc, IdentityError) and str(exc) == "unrecognized caller":
        return 2
    return 1


def _hoist_global_options(argv: list[str]) -> list[str]:
    """Allow global options before or after subcommands.

    A bare ``--`` ends option parsing ([TAUT-8.1]): only the tokens before
    it are hoisted; the separator and everything after it pass through
    untouched so argparse treats them as positionals.
    """

    if "--" in argv:
        boundary = argv.index("--")
        head, tail = argv[:boundary], argv[boundary:]
    else:
        head, tail = argv, []
    command = _first_command(head)
    value_options = {"--db", "--as"}
    if command != "rejoin":
        value_options.add("--token")
    flag_options = {"--json", "-t", "--timestamps", "-q", "--quiet"}
    globals_: list[str] = []
    rest: list[str] = []
    i = 0
    while i < len(head):
        token = head[i]
        if token in flag_options:
            globals_.append(token)
            i += 1
            continue
        if token in value_options and i + 1 < len(head):
            globals_.extend([token, head[i + 1]])
            i += 2
            continue
        if any(token.startswith(option + "=") for option in value_options):
            globals_.append(token)
            i += 1
            continue
        rest.append(token)
        i += 1
    return [*globals_, *rest, *tail]


def _first_command(argv: list[str]) -> str | None:
    return _find_first_command(argv)[0]


def _find_first_command(argv: list[str]) -> tuple[str | None, int]:
    """Return the first subcommand token and its index, or (None, -1).

    Value-option arguments are skipped so an option value that happens to
    spell a command name is never mistaken for one.
    """

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
        "inbox",
        "set",
        "rename",
        "who",
        "whoami",
        "rejoin",
        "summon",
        "dismiss",
    }
    value_options = {"--db", "--as", "--token"}
    i = 0
    while i < len(argv):
        token = argv[i]
        if token == "--":
            return None, -1
        if token in commands:
            return token, i
        if token in value_options:
            i += 2
            continue
        i += 1
    return None, -1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
