"""Explicit public-API dispatch for the twelve CLI-shaped MCP tools."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypeAlias

from taut import Member, Message, Notification, TautClient, Thread

CommandScalar: TypeAlias = str | int | bool | None
CommandArguments: TypeAlias = tuple[tuple[str, CommandScalar], ...]
CommandRecord: TypeAlias = Message | Notification | Member | Thread

RECORD_TYPE_BY_TOOL = {
    "join": "message",
    "leave": "message",
    "set_name": "member",
    "say": "message",
    "reply": "message",
    "read": "message",
    "inbox": "notification",
    "log": "message",
    "list": "thread",
    "rename": "thread",
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


def execute_command(
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
    elif name == "read":
        records = tuple(
            client.read(
                _optional_string(arguments, "thread"),
                limit=_integer(arguments, "limit", 100),
            )
        )
    elif name == "inbox":
        records = tuple(client.inbox(limit=_integer(arguments, "limit", 1000)))
    elif name == "log":
        since = arguments.get("since")
        if since is not None and (
            isinstance(since, bool) or not isinstance(since, (str, int))
        ):
            raise TypeError("since must be a string, integer, or null")
        records = tuple(
            client.log(
                _required_string(arguments, "thread"),
                since=since,
                limit=_integer(arguments, "limit", 100),
            )
        )
    elif name == "list":
        all_threads = arguments.get("all", False)
        if not isinstance(all_threads, bool):
            raise TypeError("all must be a boolean")
        records = tuple(client.list_threads(all_threads=all_threads))
    elif name == "rename":
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


def record_object(record: CommandRecord) -> dict[str, object]:
    """Encode one public value object without importing CLI rendering."""

    if isinstance(record, Message):
        return {
            "from": record.from_name,
            "from_id": record.from_id,
            "kind": record.kind,
            "text": record.text,
            "thread": record.thread,
            "ts": record.ts,
        }
    if isinstance(record, Notification):
        notification: dict[str, object] = {
            "actor_id": record.actor_id,
            "actor_name": record.actor_name,
            "message_ts": record.message_ts,
            "thread": record.thread,
            "to_id": record.to_id,
            "type": record.type,
        }
        if record.matched is not None:
            notification["matched"] = record.matched
        return notification
    if isinstance(record, Member):
        return {
            "aliases": list(record.aliases),
            "kind": record.kind,
            "last_active_ts": record.last_active_ts,
            "member_id": record.member_id,
            "name": record.name,
            "persona": record.persona,
            "presence": record.presence,
        }
    thread: dict[str, object] = {
        "kind": record.kind,
        "last_ts": record.last_ts,
        "parent": record.parent,
        "thread": record.name,
        "unread": record.unread,
    }
    if record.kind == "dm":
        thread["members"] = list(record.members)
    return thread
