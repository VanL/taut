"""Explicit public-API dispatch for the eighteen CLI-shaped MCP tools."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypeAlias

from simplebroker import format_message_id

from taut import (
    Channel,
    Member,
    Message,
    MessageDeletion,
    MessageReaction,
    NotFoundError,
    Notification,
    SearchHit,
    TautClient,
    TautError,
    Thread,
    addressing,
)

_MAX_SAFE_JSON_INTEGER = (1 << 53) - 1

CommandScalar: TypeAlias = str | int | bool | None | tuple[str, ...]
CommandArguments: TypeAlias = tuple[tuple[str, CommandScalar], ...]
CommandRecord: TypeAlias = (
    Channel
    | Message
    | MessageDeletion
    | MessageReaction
    | Notification
    | SearchHit
    | Member
    | Thread
)

RECORD_TYPE_BY_TOOL = {
    "join": "message",
    "leave": "message",
    "set_name": "member",
    "say": "message",
    "reply": "message",
    "message_show": "message",
    "message_delete": "deletion",
    "message_react": "reaction",
    "read": "message",
    "inbox": "notification",
    "log": "message",
    "search": "search_hit",
    "list": "thread",
    "channel_show": "channel",
    "channel_topic": "channel",
    "channel_rename": "thread",
    "who": "member",
    "whoami": "member",
}


@dataclass(frozen=True, slots=True)
class CommandRecords:
    record_type: str
    records: tuple[CommandRecord, ...]


def _required_string(arguments: dict[str, CommandScalar], name: str) -> str:
    value = arguments.get(name)
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    return value


def _optional_string(arguments: dict[str, CommandScalar], name: str) -> str | None:
    value = arguments.get(name)
    if value is not None and not isinstance(value, str):
        raise TypeError(f"{name} must be a string or null")
    return value


def _integer(arguments: dict[str, CommandScalar], name: str, default: int) -> int:
    value = arguments.get(name, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer")
    return value


def _boolean(arguments: dict[str, CommandScalar], name: str, default: bool) -> bool:
    value = arguments.get(name, default)
    if not isinstance(value, bool):
        raise TypeError(f"{name} must be a boolean")
    return value


def _string_tuple(
    arguments: dict[str, CommandScalar],
    name: str,
) -> tuple[str, ...]:
    value = arguments.get(name, ())
    if not isinstance(value, tuple) or not all(isinstance(item, str) for item in value):
        raise TypeError(f"{name} must be a string tuple")
    return value


def execute_command(  # noqa: C901 approved [DOM-10.2.1] [RUFF-SUP-011] exception
    client: TautClient,
    name: str,
    frozen_arguments: CommandArguments,
) -> CommandRecords:
    """Run exactly one allowlisted public client operation."""

    arguments = dict(frozen_arguments)
    if name == "join":
        record = client.join(
            _required_string(arguments, "thread"),
            persona=_optional_string(arguments, "persona"),
            new=False,
        )
        records: tuple[CommandRecord, ...] = (record,)
    elif name == "leave":
        records = (client.leave(_required_string(arguments, "thread")),)
    elif name == "set_name":
        records = (client.set_name(_required_string(arguments, "name")),)
    elif name == "say":
        records = (
            client.say(
                _required_string(arguments, "target"),
                _required_string(arguments, "text"),
            ),
        )
    elif name == "reply":
        records = (
            client.reply(
                _required_string(arguments, "thread"),
                _required_string(arguments, "msg_id"),
                _required_string(arguments, "text"),
            ),
        )
    elif name == "message_show":
        records = (client.show_message(_required_string(arguments, "msg_id")),)
    elif name == "message_delete":
        records = (client.delete_message(_required_string(arguments, "msg_id")),)
    elif name == "message_react":
        records = (
            client.react_to_message(
                _required_string(arguments, "msg_id"),
                _required_string(arguments, "reaction"),
            ),
        )
    elif name == "read":
        thread = _optional_string(arguments, "thread")
        try:
            records = tuple(
                client.read(
                    thread,
                    limit=_integer(arguments, "limit", 100),
                )
            )
        except NotFoundError:
            if thread is None or addressing.parse_dm_selector(thread) is None:
                raise
            records = ()
    elif name == "inbox":
        records = tuple(client.inbox(limit=_integer(arguments, "limit", 1000)))
    elif name == "log":
        since = arguments.get("since")
        if since is not None and (
            isinstance(since, bool) or not isinstance(since, (str, int))
        ):
            raise TypeError("since must be a string, integer, or null")
        if isinstance(since, int) and not (
            -_MAX_SAFE_JSON_INTEGER <= since <= _MAX_SAFE_JSON_INTEGER
        ):
            raise ValueError(
                "since integer must be JSON-safe; pass larger values as text"
            )
        thread = _required_string(arguments, "thread")
        try:
            records = tuple(
                client.log(
                    thread,
                    since=since,
                    limit=_integer(arguments, "limit", 100),
                )
            )
        except NotFoundError:
            if addressing.parse_dm_selector(thread) is None:
                raise
            records = ()
    elif name == "search":
        try:
            records = tuple(
                client.search(
                    _required_string(arguments, "query"),
                    channels=_string_tuple(arguments, "channels"),
                    direct_messages=_string_tuple(arguments, "direct_messages"),
                    all_direct_messages=_boolean(
                        arguments,
                        "all_direct_messages",
                        False,
                    ),
                    from_member=_optional_string(arguments, "from_member"),
                    kinds=_string_tuple(arguments, "kinds"),
                    before=_optional_string(arguments, "before"),
                    limit=_integer(arguments, "limit", 50),
                    reindex=_boolean(arguments, "reindex", False),
                )
            )
        except (TautError, TypeError, ValueError):
            raise
        except Exception:  # noqa: BLE001 approved [DOM-10.2.1] [RUFF-SUP-083] exception
            raise TautError(
                "search provider or index unavailable; fix the workspace "
                "search provider or index and retry"
            ) from None
    elif name == "list":
        all_threads = arguments.get("all", False)
        if not isinstance(all_threads, bool):
            raise TypeError("all must be a boolean")
        direct_messages = arguments.get("dms", False)
        if not isinstance(direct_messages, bool):
            raise TypeError("dms must be a boolean")
        if all_threads and direct_messages:
            raise ValueError("all and dms are mutually exclusive")
        if direct_messages:
            records = tuple(client.list_direct_messages())
        else:
            records = tuple(client.list_threads(all_threads=all_threads))
    elif name == "channel_show":
        try:
            records = (client.get_channel(_required_string(arguments, "channel")),)
        except NotFoundError:
            records = ()
    elif name == "channel_topic":
        try:
            records = (
                client.set_channel_topic(
                    _required_string(arguments, "channel"),
                    _optional_string(arguments, "topic"),
                ),
            )
        except NotFoundError:
            records = ()
    elif name == "channel_rename":
        records = (
            client.rename_channel(
                _required_string(arguments, "old_name"),
                _required_string(arguments, "new_name"),
            ),
        )
    elif name == "who":
        records = tuple(client.who(_optional_string(arguments, "thread")))
    elif name == "whoami":
        records = (client.whoami(explain=False),)
    else:
        raise AssertionError(f"unregistered child command: {name}")
    return CommandRecords(RECORD_TYPE_BY_TOOL[name], records)


def record_object(record: CommandRecord) -> dict[str, object]:  # noqa: C901 approved [DOM-10.2.1] [RUFF-SUP-012] exception
    """Encode one public value object without importing CLI rendering."""

    if isinstance(record, Message):
        return {
            "from": record.from_name,
            "from_id": record.from_id,
            "kind": record.kind,
            "text": record.text,
            "thread": record.thread,
            "ts": format_message_id(record.ts),
        }
    if isinstance(record, MessageDeletion):
        return {
            "deleted": record.deleted,
            "thread": record.thread,
            "ts": format_message_id(record.ts),
        }
    if isinstance(record, MessageReaction):
        return {
            "audience_count": record.audience_count,
            "message_ts": format_message_id(record.message_ts),
            "reaction": record.reaction,
            "thread": record.thread,
        }
    if isinstance(record, Notification):
        notification: dict[str, object] = {
            "actor_id": record.actor_id,
            "actor_name": record.actor_name,
            "message_ts": _optional_message_id(record.message_ts),
            "thread": record.thread,
            "to_id": record.to_id,
            "type": record.type,
        }
        if record.matched is not None:
            notification["matched"] = record.matched
        if record.reaction is not None:
            notification["reaction"] = record.reaction
        return notification
    if isinstance(record, Member):
        return {
            "aliases": list(record.aliases),
            "kind": record.kind,
            "last_active_ts": format_message_id(record.last_active_ts),
            "member_id": record.member_id,
            "name": record.name,
            "persona": record.persona,
            "presence": record.presence,
        }
    if isinstance(record, Channel):
        return {
            "channel": record.name,
            "topic": record.topic,
            "topic_updated_ts": _optional_message_id(record.topic_updated_ts),
            "topic_updated_by_id": record.topic_updated_by_id,
            "topic_updated_by_name": record.topic_updated_by_name,
        }
    if isinstance(record, SearchHit):
        return {
            "channel": record.channel,
            "from": record.from_name,
            "from_id": record.from_id,
            "kind": record.kind,
            "members": list(record.members) if record.members is not None else None,
            "parent": record.parent,
            "text": record.text,
            "thread": record.thread,
            "thread_kind": record.thread_kind,
            "ts": format_message_id(record.ts),
        }
    thread: dict[str, object] = {
        "kind": record.kind,
        "last_ts": _optional_message_id(record.last_ts),
        "parent": record.parent,
        "thread": record.name,
        "unread": record.unread,
    }
    if record.kind == "dm":
        thread["members"] = list(record.members)
    elif record.kind == "channel":
        thread["topic"] = record.topic
    return thread


def _optional_message_id(value: int | None) -> str | None:
    return None if value is None else format_message_id(value)
