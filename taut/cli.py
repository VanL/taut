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

from simplebroker.ext import StopWatching

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
    raw = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()
    command, boundary = _find_first_command(raw)
    if command in _DELEGATED_VERBS:
        # Delegation verbs ([TAUT-8.1] D4) hand their whole tail to the
        # taut-summon extension verbatim ([SUM-3]) — including tokens
        # that spell core globals, so the split happens on the RAW argv
        # before any hoisting; only the pre-verb head is core's. (The
        # tail is also kept away from argparse because REMAINDER
        # mis-parses a leading option-like token.)
        head = _hoist_global_options([*raw[:boundary], command])
        args = parser.parse_args(head)
        args.rest = raw[boundary + 1 :]
    else:
        args = parser.parse_args(_hoist_global_options(raw))
    if not hasattr(args, "func"):
        parser.print_help(sys.stderr)
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
    parser = _TautArgumentParser(
        prog="taut",
        description=(
            "Coordinate humans and agents through durable project chat. "
            "Exit codes: 0 success; 1 error; 2 empty, nothing matched, or not "
            "found. JSON controls successful stdout records; errors remain text "
            "on stderr."
        ),
    )
    parser.add_argument(
        "--db",
        dest="db_path",
        metavar="PATH",
        help="Use an explicit SQLite database path instead of project discovery.",
    )
    parser.add_argument(
        "--as",
        dest="as_name",
        metavar="NAME_OR_ALIAS",
        help="Act as the member with this current name or alias.",
    )
    parser.add_argument(
        "--token",
        dest="auth_token",
        metavar="TOKEN",
        help=(
            "Select identity by continuity token. This provides continuity, not "
            "authentication."
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit successful stdout records as NDJSON; errors remain text on stderr.",
    )
    parser.add_argument(
        "-t",
        "--timestamps",
        action="store_true",
        help="Show 19-digit message ids in human message output.",
    )
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Suppress ordinary output while preserving exit status.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"taut {__version__}",
        help="Show the Taut version and exit.",
    )

    sub = parser.add_subparsers(
        dest="command",
        parser_class=_TautArgumentParser,
        title="commands",
        metavar="COMMAND",
        help="Command to run; use 'taut COMMAND --help' for command syntax.",
    )

    p = sub.add_parser(
        "init",
        help="Initialize the resolved Taut storage.",
        description=(
            "Create the default SQLite database or initialize the sidecar schema "
            "for the project-configured backend."
        ),
    )
    p.set_defaults(func=_cmd_init)

    p = sub.add_parser(
        "join",
        help="Join a channel, creating it when needed.",
        description=(
            "Join THREAD at its current end. The acting identity and channel are "
            "created when needed."
        ),
    )
    p.add_argument("thread", metavar="THREAD", help="Channel to join.")
    p.add_argument(
        "--persona",
        metavar="TEXT",
        help="Set or replace the acting member's persona text.",
    )
    p.add_argument(
        "--new",
        action="store_true",
        help="Force creation of a fresh member instead of recognizing an existing one.",
    )
    p.set_defaults(func=_cmd_join)

    p = sub.add_parser(
        "leave",
        help="Leave a joined thread without deleting history.",
        description="Remove the acting member's membership from THREAD.",
    )
    p.add_argument("thread", metavar="THREAD", help="Joined thread to leave.")
    p.set_defaults(func=_cmd_leave)

    p = sub.add_parser(
        "say",
        help="Post to a channel, sub-thread, or direct-message target.",
        description=(
            "Post TEXT to TARGET. Use '-' for stdin; when TEXT is omitted, piped "
            "stdin is read automatically. Empty text and arbitrary UTF-8 are allowed."
        ),
    )
    p.add_argument(
        "target",
        metavar="TARGET",
        help="Channel, sub-thread, or @NAME direct-message target.",
    )
    p.add_argument(
        "text",
        metavar="TEXT|-",
        nargs="?",
        help="Message text, '-' for stdin, or omit when stdin is piped.",
    )
    p.set_defaults(func=_cmd_say)

    p = sub.add_parser(
        "reply",
        help="Reply in the sub-thread rooted at a message.",
        description=(
            "Reply to MSG_ID in THREAD. MSG_ID is a full 19-digit id or a unique "
            "suffix of at least 4 digits from the most recent 1,000 messages."
        ),
    )
    p.add_argument("thread", metavar="THREAD", help="Parent thread containing MSG_ID.")
    p.add_argument(
        "msg_id",
        metavar="MSG_ID",
        help="Full 19-digit message id or unique suffix of at least 4 digits.",
    )
    p.add_argument(
        "text",
        metavar="TEXT|-",
        nargs="?",
        help="Reply text, '-' for stdin, or omit when stdin is piped.",
    )
    p.set_defaults(func=_cmd_reply)

    p = sub.add_parser(
        "read",
        help="Show unread messages and advance chat cursors.",
        description=(
            "Read up to 1,000 unread messages per selected thread. Omit THREAD to "
            "read all joined threads; rerun until exit 2 to drain larger backlogs."
        ),
    )
    p.add_argument(
        "thread",
        metavar="THREAD",
        nargs="?",
        help="One joined thread; omit to read every joined thread.",
    )
    p.set_defaults(func=_cmd_read)

    p = sub.add_parser(
        "log",
        help="Show thread history without moving a cursor.",
        description=(
            "Show chronological history for THREAD. Filtering never changes unread "
            "state."
        ),
    )
    p.add_argument("thread", metavar="THREAD", help="Thread whose history to show.")
    p.add_argument(
        "--since",
        metavar="TS",
        help=(
            "Show ids strictly after TS: ISO 8601, unix seconds/milliseconds/"
            "nanoseconds, or a native 19-digit id."
        ),
    )
    p.add_argument(
        "--limit",
        metavar="N",
        type=int,
        help="Show the most recent N matching messages in chronological order.",
    )
    p.set_defaults(func=_cmd_log)

    p = sub.add_parser(
        "list",
        help="List joined threads and unread state.",
        description="List the acting member's threads, or every registered thread.",
    )
    p.add_argument(
        "--all",
        action="store_true",
        dest="all_threads",
        help="List every registered thread, not only joined threads.",
    )
    p.set_defaults(func=_cmd_list)

    p = sub.add_parser(
        "watch",
        help="Live-follow chat and notification activity.",
        description=(
            "Follow selected joined chat threads plus the acting member's notification "
            "inbox. Omit THREAD to follow all current and later memberships."
        ),
    )
    p.add_argument(
        "threads",
        metavar="THREAD",
        nargs="*",
        help="Joined thread filters; omit to follow every membership.",
    )
    p.set_defaults(func=_cmd_watch)

    p = sub.add_parser(
        "inbox",
        help="Claim and show pending notification pointers.",
        description=(
            "Claim pending notification pointers. Source chat remains durable even "
            "though claimed pointers are consumable."
        ),
    )
    p.set_defaults(func=_cmd_inbox)

    p = sub.add_parser(
        "set",
        help="Change a property of the acting member.",
        description="Change one acting-member property through a nested command.",
    )
    set_sub = p.add_subparsers(
        dest="set_command",
        required=True,
        parser_class=_TautArgumentParser,
        title="properties",
        metavar="PROPERTY",
        help="Property to change; use 'taut set PROPERTY --help' for syntax.",
    )
    p_name = set_sub.add_parser(
        "name",
        help="Change the current display and routing name.",
        description=(
            "Change the acting member's current display and routing name without "
            "rewriting old messages."
        ),
    )
    p_name.add_argument("name", metavar="NAME", help="New unique member name.")
    p_name.set_defaults(func=_cmd_set_name)

    p = sub.add_parser(
        "rename",
        help="Rename a channel and its registered sub-threads.",
        description=(
            "Rename OLD to NEW and move its registered one-level sub-thread names."
        ),
    )
    p.add_argument("old_name", metavar="OLD", help="Current channel name.")
    p.add_argument("new_name", metavar="NEW", help="New unused channel name.")
    p.set_defaults(func=_cmd_rename)

    p = sub.add_parser(
        "who",
        help="Show members and presence evidence.",
        description="Show all members, or only members of THREAD when supplied.",
    )
    p.add_argument(
        "thread",
        metavar="THREAD",
        nargs="?",
        help="Thread whose members to show; omit for every member.",
    )
    p.set_defaults(func=_cmd_who)

    p = sub.add_parser(
        "whoami",
        help="Show the identity Taut resolved for this caller.",
        description="Show the acting member and optionally the recognition evidence.",
    )
    p.add_argument(
        "--explain",
        action="store_true",
        help="Include captured identity evidence and the rule that matched.",
    )
    p.set_defaults(func=_cmd_whoami)

    p = sub.add_parser(
        "rejoin",
        help="Associate current identity evidence with an existing member.",
        description=(
            "Rejoin by NAME_OR_ALIAS, continuity token, or the global --as selector. "
            "Continuity tokens are not authentication."
        ),
    )
    p.add_argument(
        "name_or_alias",
        metavar="NAME_OR_ALIAS",
        nargs="?",
        help="Existing current name or alias; omit when selecting another way.",
    )
    p.add_argument(
        "--token",
        dest="rejoin_token",
        metavar="TOKEN",
        help="Select the existing member by continuity token.",
    )
    p.set_defaults(func=_cmd_rejoin)

    # Delegation verbs ([TAUT-8.1] D4, spec 04 [SUM-3]): the tail is
    # captured whole and handed to the taut-summon extension. `main()`
    # overrides the REMAINDER capture with a verbatim split (see there).
    p = sub.add_parser(
        "summon",
        help="Delegate agent-harness startup to the taut-summon extension.",
        description=(
            "Delegate verbatim to 'taut-summon run'. The extension owns provider, "
            "name, thread, and adapter options."
        ),
    )
    p.add_argument(
        "rest",
        metavar="ARG",
        nargs=argparse.REMAINDER,
        help="Arguments passed verbatim to 'taut-summon run'.",
    )
    p.set_defaults(func=_cmd_summon)

    p = sub.add_parser(
        "dismiss",
        help="Delegate agent-harness shutdown to the taut-summon extension.",
        description="Delegate verbatim to 'taut-summon stop'.",
    )
    p.add_argument(
        "rest",
        metavar="ARG",
        nargs=argparse.REMAINDER,
        help="Arguments passed verbatim to 'taut-summon stop'.",
    )
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
    sink_closed = False

    def handle(item: Message | Notification) -> None:
        nonlocal sink_closed
        if sink_closed:
            raise StopWatching
        try:
            if isinstance(item, Notification):
                _emit_notifications(args, [item], client=client)
            else:
                _emit_messages(args, [item])
            sys.stdout.flush()
        except BrokenPipeError:
            sink_closed = True
            raise StopWatching from None

    watcher = client.watch(handle, threads=args.threads or None)
    try:
        watcher.run_forever()
    except KeyboardInterrupt:
        return 0
    finally:
        watcher.stop(join=True, timeout=5.0)
    if sink_closed:
        try:
            sys.stdout.close()
        except BrokenPipeError:
            # The record flush already classified this pipe as closed. Suppress
            # only the matching final close so interpreter shutdown stays quiet.
            pass
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
    client = _client(args)
    notifications = client.inbox()
    _emit_notifications(args, notifications, client=client)
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
            label = thread.display_name or thread.name
            print(f"{label}  {_format_unread_count(thread.unread_count)} unread")


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
    *,
    client: TautClient | None = None,
) -> None:
    if args.quiet:
        return
    for notification in notifications:
        if notification.warning:
            print(f"warning: {notification.warning}", file=sys.stderr)
        if args.json:
            _print_json(_notification_object(notification))
        elif notification.type == "mention":
            assert notification.message_ts is not None
            inspect_action = _mention_inspect_action(client, notification)
            reply_id = _mention_reply_id(client, notification)
            reply_action = (
                f"; reply: taut reply {notification.thread} {reply_id}"
                if reply_id is not None
                else ""
            )
            print(
                f"{_format_message_time(notification.message_ts)} "
                f"{notification.actor_name} mentioned you in {notification.thread}; "
                f"inspect: {inspect_action}{reply_action}"
            )
        elif notification.type == "reply":
            assert notification.message_ts is not None
            print(
                f"{_format_message_time(notification.message_ts)} "
                f"{notification.actor_name} replied in {notification.thread}; "
                f"inspect: taut log {notification.thread}"
            )
        elif notification.type == "dm_started":
            assert notification.message_ts is not None
            print(
                f"{_format_message_time(notification.message_ts)} "
                f"{notification.actor_name} started a direct message in "
                f"{notification.thread}; read: taut read"
            )
        else:
            print(notification.raw or "foreign notification")


def _mention_inspect_action(
    client: TautClient | None,
    notification: Notification,
) -> str:
    thread = notification.thread
    if thread is None:
        return "taut read"
    if client is not None:
        thread_row = next(
            (
                candidate
                for candidate in client.list_threads(all_threads=True)
                if candidate.name == thread
            ),
            None,
        )
        if thread_row is not None and thread_row.kind == "dm":
            return "taut read"
    return f"taut log {thread}"


def _mention_reply_id(
    client: TautClient | None,
    notification: Notification,
) -> str | None:
    """Return the shortest currently usable reply id for a mention pointer."""

    thread = notification.thread
    message_ts = notification.message_ts
    if client is None or thread is None or message_ts is None:
        return None
    if thread not in client.joined_thread_names():
        return None
    thread_row = next(
        (
            candidate
            for candidate in client.list_threads(all_threads=True)
            if candidate.name == thread
        ),
        None,
    )
    if (
        thread_row is None
        or thread_row.kind != "channel"
        or thread_row.parent is not None
    ):
        return None

    full_id = str(message_ts)
    try:
        recent_ids = [str(message.ts) for message in client.log(thread, limit=1000)]
    except (EmptyResultError, NotFoundError):
        return full_id
    if full_id not in recent_ids:
        return full_id
    for length in range(4, len(full_id) + 1):
        suffix = full_id[-length:]
        if sum(candidate.endswith(suffix) for candidate in recent_ids) == 1:
            return suffix
    return full_id


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
    code = _exit_code_for_exception(exc)
    if not getattr(args, "quiet", False):
        message = str(exc)
        if getattr(args, "command", None) == "reply" and (
            "message id" in message or message.startswith("message not found")
        ):
            message += (
                "; usage: taut reply THREAD MSG_ID [TEXT|-] "
                "(MSG_ID is a full 19-digit id or unique suffix of at least 4 digits)"
            )
        print(message, file=sys.stderr)
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
