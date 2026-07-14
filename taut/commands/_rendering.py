"""Stream-based input and output helpers shared by command adapters.

Spec references:
- docs/specs/02-taut-core.md [TAUT-6.4], [TAUT-8.1], [TAUT-8.2], [TAUT-8.6]
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from typing import TYPE_CHECKING, Any, TextIO

from taut import escape_terminal_text
from taut._exceptions import EmptyResultError, NotFoundError

_POLICY_ERROR_MESSAGE = "terminal output policy is unavailable"

if TYPE_CHECKING:
    from taut.client import (
        InitResult,
        Member,
        Message,
        Notification,
        TautClient,
        Thread,
    )


class _TerminalOutputPolicyError(RuntimeError):
    """Internal signal that the fixed policy diagnostic must bypass escaping."""

    def __init__(self, *, project_config_syntax: bool = False) -> None:
        super().__init__(_POLICY_ERROR_MESSAGE)
        self.project_config_syntax = project_config_syntax


def emit_init(
    result: InitResult,
    *,
    json_output: bool,
    quiet: bool,
    stdout: TextIO,
) -> None:
    """Render the idempotent storage initialization result."""

    if quiet:
        return
    if json_output:
        write_json(stdout, {"db": result.db, "created": result.created})
    else:
        status = "created" if result.created else "exists"
        write_human_line(stdout, f"{status}: {result.db}")


def read_text_argument(text: str | None, stdin: TextIO) -> str:
    """Resolve explicit or piped message text from the authoritative stream."""

    if text == "-":
        return _read_stdin_text(stdin)
    if text is not None:
        return text
    if not stdin.isatty():
        return _read_stdin_text(stdin)
    raise ValueError("message text required")


def emit_sent_message(
    client: TautClient,
    message: Message,
    *,
    json_output: bool,
    timestamps: bool,
    quiet: bool,
    stdout: TextIO,
    stderr: TextIO,
) -> None:
    """Render the shared successful output contract for say and reply."""

    emit_created_member(
        client,
        json_output=json_output,
        quiet=quiet,
        stdout=stdout,
        stderr=stderr,
    )
    if json_output:
        if not quiet:
            write_json(stdout, message_object(message))
    elif timestamps and not quiet:
        write_human_line(stdout, str(message.ts))
    emit_notification_warnings(client, quiet=quiet, stderr=stderr)


def emit_created_member(
    client: TautClient,
    *,
    json_output: bool,
    quiet: bool,
    stdout: TextIO,
    stderr: TextIO,
) -> None:
    """Render the identity-creation prelude exposed by client operations."""

    member = client.last_created_member
    if member is None:
        return
    if json_output:
        write_json(stdout, member_object(member, include_token=True))
        return
    if not quiet:
        write_human_line(stderr, f"created new identity '{member.name}'")
        if member.token:
            write_human_line(stderr, f"token: {member.token}")
    if client.last_candidates:
        write_human_line(stderr, "note: you may be one of these:")
        for name, reasons in client.last_candidates:
            write_human_line(stderr, f"  {name}  {', '.join(reasons)}")


def emit_notification_warnings(
    client: TautClient,
    *,
    quiet: bool,
    stderr: TextIO,
) -> None:
    """Render self-describing notification warnings verbatim."""

    if quiet:
        return
    for warning in client.last_notification_warnings:
        write_human_line(stderr, f"warning: {warning}")


def emit_messages(
    messages: list[Message],
    *,
    json_output: bool,
    timestamps: bool,
    quiet: bool,
    stdout: TextIO,
    stderr: TextIO,
) -> None:
    """Render message records in the established human or NDJSON shape."""

    if quiet:
        return
    if json_output:
        for message in messages:
            if message.warning:
                write_human_line(stderr, f"warning: {message.warning}")
            write_json(stdout, message_object(message))
        return
    for thread, grouped in _group_messages_by_thread(messages).items():
        write_human_line(stdout, thread_heading(thread, stream=stdout))
        sender_width = max(
            [6]
            + [
                len(_escape_human_text(message.from_name))
                for message in grouped
                if message.kind != "notice"
            ]
        )
        for message in grouped:
            if message.warning:
                write_human_line(stderr, f"warning: {message.warning}")
            write_human_line(
                stdout,
                human_message_row(
                    message,
                    timestamps=timestamps,
                    sender_width=sender_width,
                    stream=stdout,
                ),
            )


def emit_members(
    members: list[Member],
    *,
    json_output: bool,
    quiet: bool,
    stdout: TextIO,
) -> None:
    """Render public member values without reaching back into the client."""

    if quiet:
        return
    for member in members:
        if json_output:
            write_json(
                stdout, member_object(member, include_token=member.token is not None)
            )
        else:
            persona = f"  {member.persona}" if member.persona else ""
            write_human_line(
                stdout,
                f"{member.name}\t{member.kind}\t{member.presence}{persona}",
            )
            if member.explain is not None:
                write_human_line(
                    stdout,
                    json.dumps(member.explain, ensure_ascii=False, sort_keys=True),
                )


def emit_threads(
    threads: list[Thread],
    *,
    json_output: bool,
    quiet: bool,
    stdout: TextIO,
) -> None:
    """Render thread metadata and human unread counts."""

    if quiet:
        return
    for thread in threads:
        if json_output:
            write_json(stdout, thread_object(thread))
        else:
            label = thread.display_name or thread.name
            write_human_line(
                stdout,
                f"{label}  {format_unread_count(thread.unread_count)} unread",
            )


def emit_notifications(
    notifications: list[Notification],
    *,
    client: TautClient | None,
    json_output: bool,
    quiet: bool,
    stdout: TextIO,
    stderr: TextIO,
) -> None:
    """Render consumed notification pointers and actionable human hints."""

    if quiet:
        return
    for notification in notifications:
        if notification.warning:
            write_human_line(stderr, f"warning: {notification.warning}")
        if json_output:
            write_json(stdout, notification_object(notification))
        elif notification.type == "mention":
            assert notification.message_ts is not None
            inspect_action = _mention_inspect_action(client, notification)
            reply_id = _mention_reply_id(client, notification)
            reply_action = (
                f"; reply: taut reply {notification.thread} {reply_id}"
                if reply_id is not None
                else ""
            )
            write_human_line(
                stdout,
                f"{format_message_time(notification.message_ts)} "
                f"{notification.actor_name} mentioned you in {notification.thread}; "
                f"inspect: {inspect_action}{reply_action}",
            )
        elif notification.type == "reply":
            assert notification.message_ts is not None
            write_human_line(
                stdout,
                f"{format_message_time(notification.message_ts)} "
                f"{notification.actor_name} replied in {notification.thread}; "
                f"inspect: taut log {notification.thread}",
            )
        elif notification.type == "dm_started":
            assert notification.message_ts is not None
            write_human_line(
                stdout,
                f"{format_message_time(notification.message_ts)} "
                f"{notification.actor_name} started a direct message in "
                f"{notification.thread}; read: taut read",
            )
        else:
            write_human_line(
                stdout,
                notification.raw or "foreign notification",
            )


def emit_watch_item(
    item: Message | Notification,
    *,
    client: TautClient,
    json_output: bool,
    timestamps: bool,
    quiet: bool,
    stdout: TextIO,
    stderr: TextIO,
) -> None:
    """Route one live item through the shared message/notification renderers."""

    from taut.client import Notification

    if isinstance(item, Notification):
        emit_notifications(
            [item],
            client=client,
            json_output=json_output,
            quiet=quiet,
            stdout=stdout,
            stderr=stderr,
        )
    else:
        emit_messages(
            [item],
            json_output=json_output,
            timestamps=timestamps,
            quiet=quiet,
            stdout=stdout,
            stderr=stderr,
        )


def emit_renamed_thread(
    thread: Thread,
    *,
    old_name: str,
    json_output: bool,
    quiet: bool,
    stdout: TextIO,
) -> None:
    """Render one successful channel rename."""

    if quiet:
        return
    if json_output:
        write_json(stdout, thread_object(thread))
    else:
        write_human_line(stdout, f"renamed {old_name} to {thread.name}")


def message_object(message: Message) -> dict[str, Any]:
    return {
        "thread": message.thread,
        "ts": message.ts,
        "from_id": message.from_id,
        "from": message.from_name,
        "kind": message.kind,
        "text": message.text,
    }


def member_object(member: Member, *, include_token: bool) -> dict[str, Any]:
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


def thread_object(thread: Thread) -> dict[str, Any]:
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


def notification_object(notification: Notification) -> dict[str, Any]:
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


def write_json(stream: TextIO, obj: dict[str, Any]) -> None:
    stream.write(json.dumps(obj, ensure_ascii=False, separators=(",", ":")) + "\n")


def write_human_line(stream: TextIO, body: str) -> None:
    """Escape one complete human record, then append its structural newline."""

    escaped = _escape_human_text(body)
    stream.write(escaped)
    stream.write("\n")


def preflight_human_output_policy() -> None:
    """Validate the effective human-output policy before command side effects."""

    _escape_human_text("")


def _escape_human_text(body: str) -> str:
    try:
        return escape_terminal_text(body)
    except RuntimeError as exc:
        raise _TerminalOutputPolicyError(
            project_config_syntax=(
                getattr(exc, "_taut_project_config_syntax", False) is True
            )
        ) from exc


def thread_heading(thread: str, *, stream: TextIO) -> str:
    prefix, rule, _notice = _human_glyphs(stream)
    return f"{prefix} {thread} {rule * 38}"


def human_message_row(
    message: Message,
    *,
    timestamps: bool,
    sender_width: int,
    stream: TextIO,
) -> str:
    id_column = f"{message.ts}  " if timestamps else ""
    clock = format_message_time(message.ts)
    if message.kind == "notice":
        _prefix, _rule, notice = _human_glyphs(stream)
        return f"  {id_column}{clock} {notice} {message.text}"
    escaped_sender = _escape_human_text(message.from_name)
    padding = " " * max(0, sender_width - len(escaped_sender))
    # Keep the original sender in this intermediate row. ``write_human_line``
    # scans the complete row once, so generated escapes are never input to a
    # later policy pass. The preview above exists only to preserve alignment.
    return f"  {id_column}{clock} {message.from_name}{padding}  {message.text}"


def format_message_time(ts: int) -> str:
    return datetime.fromtimestamp(ts / 1_000_000_000).strftime("%H:%M")


def format_unread_count(count: int) -> str:
    return "999+" if count >= 1000 else str(count)


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


def _group_messages_by_thread(messages: list[Message]) -> dict[str, list[Message]]:
    grouped: dict[str, list[Message]] = {}
    for message in messages:
        grouped.setdefault(message.thread, []).append(message)
    return grouped


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


def _read_stdin_text(stdin: TextIO) -> str:
    """Read stdin while naming that input in Unicode diagnostics."""

    try:
        return stdin.read()
    except UnicodeDecodeError as exc:
        raise ValueError(f"stdin is not valid UTF-8: {exc}") from exc
