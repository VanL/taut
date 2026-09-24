"""Explicit public-API dispatch for the eighteen CLI-shaped MCP tools."""

from __future__ import annotations

from typing import TypeAlias, cast

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


def execute_command(  # noqa: C901 approved [DOM-10.2.1] [RUFF-SUP-011] exception
    client: TautClient,
    name: str,
    frozen_arguments: CommandArguments,
) -> tuple[CommandRecord, ...]:
    """Dispatch schema-validated arguments, retaining defaults and domain policy."""

    arguments = dict(frozen_arguments)
    if name == "join":
        record = client.join(
            cast(str, arguments["thread"]),
            persona=cast(str | None, arguments.get("persona")),
            new=False,
        )
        records: tuple[CommandRecord, ...] = () if record is None else (record,)
    elif name == "leave":
        records = (client.leave(cast(str, arguments["thread"])),)
    elif name == "set_name":
        records = (client.set_name(cast(str, arguments["name"])),)
    elif name == "say":
        target = cast(str, arguments["target"])
        try:
            records = (
                client.say(
                    target,
                    cast(str, arguments["text"]),
                ),
            )
        except NotFoundError:
            selector = addressing.parse_dm_selector(target)
            if selector is None or selector.thread is None:
                raise
            records = ()
    elif name == "reply":
        records = (
            client.reply(
                cast(str, arguments["thread"]),
                cast(str, arguments["msg_id"]),
                cast(str, arguments["text"]),
            ),
        )
    elif name == "message_show":
        records = (client.show_message(cast(str, arguments["msg_id"])),)
    elif name == "message_delete":
        records = (client.delete_message(cast(str, arguments["msg_id"])),)
    elif name == "message_react":
        records = (
            client.react_to_message(
                cast(str, arguments["msg_id"]),
                cast(str, arguments["reaction"]),
            ),
        )
    elif name == "read":
        thread = cast(str | None, arguments.get("thread"))
        try:
            records = tuple(
                client.read(
                    thread,
                    limit=cast(int, arguments.get("limit", 100)),
                )
            )
        except NotFoundError:
            if thread is None or addressing.parse_dm_selector(thread) is None:
                raise
            records = ()
    elif name == "inbox":
        records = tuple(client.inbox(limit=cast(int, arguments.get("limit", 1000))))
    elif name == "log":
        since = cast(str | int | None, arguments.get("since"))
        thread = cast(str, arguments["thread"])
        try:
            records = tuple(
                client.log(
                    thread,
                    since=since,
                    limit=cast(int, arguments.get("limit", 100)),
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
                    cast(str, arguments["query"]),
                    channels=cast(tuple[str, ...], arguments.get("channels", ())),
                    direct_messages=cast(
                        tuple[str, ...], arguments.get("direct_messages", ())
                    ),
                    all_direct_messages=cast(
                        bool, arguments.get("all_direct_messages", False)
                    ),
                    from_member=cast(str | None, arguments.get("from_member")),
                    kinds=cast(tuple[str, ...], arguments.get("kinds", ())),
                    before=cast(str | None, arguments.get("before")),
                    limit=cast(int, arguments.get("limit", 50)),
                    reindex=cast(bool, arguments.get("reindex", False)),
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
        all_threads = cast(bool, arguments.get("all", False))
        direct_messages = cast(bool, arguments.get("dms", False))
        if all_threads and direct_messages:
            raise ValueError("all and dms are mutually exclusive")
        if direct_messages:
            records = tuple(client.list_direct_messages())
        else:
            records = tuple(client.list_threads(all_threads=all_threads))
    elif name == "channel_show":
        records = (client.get_channel(cast(str, arguments["channel"])),)
    elif name == "channel_topic":
        records = (
            client.set_channel_topic(
                cast(str, arguments["channel"]),
                cast(str | None, arguments.get("topic")),
            ),
        )
    elif name == "channel_rename":
        records = (
            client.rename_channel(
                cast(str, arguments["old_name"]),
                cast(str, arguments["new_name"]),
            ),
        )
    elif name == "who":
        records = tuple(client.who(cast(str | None, arguments.get("thread"))))
    elif name == "whoami":
        records = (client.whoami(explain=False),)
    else:
        raise AssertionError(f"unregistered child command: {name}")
    return records


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
