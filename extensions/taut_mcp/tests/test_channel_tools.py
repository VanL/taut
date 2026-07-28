from __future__ import annotations

from typing import Any, cast

import pytest
from jsonschema import ValidationError, validate

from taut import Channel, NotFoundError, TautClient, Thread
from taut_mcp._commands import execute_command, record_object
from taut_mcp._tools import TOOLS


def _tool(name: str) -> Any:
    return next(tool for tool in TOOLS if tool.name == name)


def test_manifest_uses_noun_first_channel_and_message_names_only() -> None:
    names = {tool.name for tool in TOOLS}
    assert len(names) == 20
    assert {
        "channel_show",
        "channel_topic",
        "channel_rename",
        "message_show",
        "message_delete",
        "message_react",
    } <= names
    assert {
        "show_channel",
        "set_channel_topic",
        "rename",
        "show_message",
        "delete_message",
        "react_to_message",
    }.isdisjoint(names)


@pytest.mark.parametrize(
    ("tool_name", "read_only", "destructive", "idempotent", "open_world"),
    [
        ("channel_show", True, False, True, True),
        ("channel_topic", False, True, False, True),
    ],
)
def test_channel_tool_annotations(
    tool_name: str,
    read_only: bool,
    destructive: bool,
    idempotent: bool,
    open_world: bool,
) -> None:
    annotations = _tool(tool_name).annotations
    assert annotations is not None
    assert annotations.readOnlyHint is read_only
    assert annotations.destructiveHint is destructive
    assert annotations.idempotentHint is idempotent
    assert annotations.openWorldHint is open_world


@pytest.mark.parametrize(
    "topic",
    ["x" * 501, "a\nb", "a\rb", "trailing\n", "trailing\r"],
)
def test_channel_topic_schema_routes_only_in_shape_topics(topic: str) -> None:
    schema = _tool("channel_topic").inputSchema
    with pytest.raises(ValidationError):
        validate(
            instance={
                "workspace": "/workspace",
                "channel": "general",
                "topic": topic,
            },
            schema=schema,
        )


@pytest.mark.parametrize(
    "instance",
    [
        {"channel": "general", "topic": "topic"},
        {"workspace": "/workspace", "topic": "topic"},
        {"workspace": "/workspace", "channel": "general"},
        {
            "workspace": "/workspace",
            "channel": "general",
            "topic": "topic",
            "extra": True,
        },
    ],
)
def test_channel_topic_schema_rejects_missing_and_additional_fields(
    instance: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        validate(instance=instance, schema=_tool("channel_topic").inputSchema)


@pytest.mark.parametrize(
    "instance",
    [
        {"channel": "general"},
        {"workspace": "/workspace"},
        {"workspace": "/workspace", "channel": "general", "extra": True},
    ],
)
def test_channel_show_schema_rejects_missing_and_additional_fields(
    instance: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        validate(instance=instance, schema=_tool("channel_show").inputSchema)


@pytest.mark.parametrize("topic", [None, "", "\u200b", "topic", " spaced ", "x" * 500])
def test_channel_topic_schema_accepts_clear_and_exact_one_line_text(
    topic: str | None,
) -> None:
    validate(
        instance={
            "workspace": "/workspace",
            "channel": "general",
            "topic": topic,
        },
        schema=_tool("channel_topic").inputSchema,
    )


def test_channel_tools_dispatch_to_public_client_methods() -> None:
    calls: list[tuple[str, tuple[object, ...]]] = []

    class PublicClientSpy:
        def get_channel(self, channel: str) -> object:
            calls.append(("get_channel", (channel,)))
            return object()

        def set_channel_topic(self, channel: str, topic: str | None) -> object:
            calls.append(("set_channel_topic", (channel, topic)))
            return object()

    client = cast(TautClient, PublicClientSpy())
    shown = execute_command(client, "channel_show", (("channel", "general"),))
    changed = execute_command(
        client,
        "channel_topic",
        (("channel", "general"), ("topic", None)),
    )

    assert shown.record_type == "channel"
    assert changed.record_type == "channel"
    assert calls == [
        ("get_channel", ("general",)),
        ("set_channel_topic", ("general", None)),
    ]


@pytest.mark.parametrize("tool_name", ["channel_show", "channel_topic"])
def test_missing_channel_is_an_empty_channel_result(tool_name: str) -> None:
    class MissingClient:
        def get_channel(self, channel: str) -> object:
            raise NotFoundError(f"channel not found: {channel}")

        def set_channel_topic(self, channel: str, topic: str | None) -> object:
            raise NotFoundError(f"channel not found: {channel}")

    arguments: tuple[tuple[str, str | int | bool | None], ...] = (
        ("channel", "missing"),
    )
    if tool_name == "channel_topic":
        arguments += (("topic", "new"),)
    result = execute_command(cast(TautClient, MissingClient()), tool_name, arguments)
    assert result.record_type == "channel"
    assert result.records == ()


def test_thread_output_schema_is_closed_and_kind_discriminated() -> None:
    schema = _tool("list").outputSchema
    assert schema is not None

    base = {
        "empty": False,
        "guidance": [],
        "record_type": "thread",
        "warnings": [],
        "workspace": "/workspace",
    }
    valid = [
        {
            **base,
            "records": [
                {
                    "kind": "channel",
                    "last_ts": None,
                    "parent": None,
                    "thread": "general",
                    "topic": None,
                    "unread": False,
                }
            ],
        },
        {
            **base,
            "records": [
                {
                    "kind": "dm",
                    "last_ts": None,
                    "members": ["other"],
                    "parent": None,
                    "thread": "dm.d_example",
                    "unread": False,
                }
            ],
        },
        {
            **base,
            "records": [
                {
                    "kind": "subthread",
                    "last_ts": None,
                    "parent": "1234567890123456789",
                    "thread": "general.1234567890123456789",
                    "unread": False,
                }
            ],
        },
    ]
    for payload in valid:
        validate(instance=payload, schema=schema)

    invalid = {
        **base,
        "records": [
            {
                "kind": "channel",
                "last_ts": None,
                "members": [],
                "parent": None,
                "thread": "general",
                "topic": None,
                "unread": False,
            }
        ],
    }
    with pytest.raises(ValidationError):
        validate(instance=invalid, schema=schema)


def test_channel_and_thread_records_have_exact_kind_specific_shapes() -> None:
    channel = Channel(
        name="general",
        topic="Current work",
        topic_updated_ts=123,
        topic_updated_by_id="m_author",
        topic_updated_by_name="Author",
    )
    assert record_object(channel) == {
        "channel": "general",
        "topic": "Current work",
        "topic_updated_ts": 123,
        "topic_updated_by_id": "m_author",
        "topic_updated_by_name": "Author",
    }

    top_level = Thread(
        name="general",
        parent=None,
        unread=False,
        last_ts=None,
        kind="channel",
        topic="Current work",
    )
    direct = Thread(
        name="dm.d_example",
        parent=None,
        unread=False,
        last_ts=None,
        kind="dm",
        members=("Author", "Other"),
    )
    subthread = Thread(
        name="general.1234567890123456789",
        parent="general",
        unread=False,
        last_ts=None,
        kind="subthread",
    )

    assert record_object(top_level)["topic"] == "Current work"
    assert "members" not in record_object(top_level)
    assert record_object(direct)["members"] == ["Author", "Other"]
    assert "topic" not in record_object(direct)
    assert "topic" not in record_object(subthread)
    assert "members" not in record_object(subthread)
