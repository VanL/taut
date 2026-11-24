from __future__ import annotations

from typing import Any, cast

import pytest
from _result_schemas import result_schema
from jsonschema import ValidationError, validate

from taut import Channel, NotFoundError, TautClient, Thread
from taut_mcp._commands import execute_command, record_object
from taut_mcp._tools import TOOLS


def _tool(name: str) -> Any:
    return next(tool for tool in TOOLS if tool.name == name)


@pytest.mark.parametrize(
    ("tool_name", "read_only", "destructive", "idempotent", "open_world"),
    [
        ("channel_show", True, False, True, True),
        ("channel_topic", False, False, False, True),
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
    assert annotations.read_only_hint is read_only
    assert annotations.destructive_hint is destructive
    assert annotations.idempotent_hint is idempotent
    assert annotations.open_world_hint is open_world


@pytest.mark.parametrize(
    "topic",
    ["x" * 501, "a\nb", "a\rb", "trailing\n", "trailing\r"],
)
def test_channel_topic_schema_routes_only_in_shape_topics(topic: str) -> None:
    schema = _tool("channel_topic").input_schema
    with pytest.raises(ValidationError):
        validate(
            instance={
                "workspace": "/workspace",
                "token": "secret",
                "channel": "general",
                "topic": topic,
            },
            schema=schema,
        )


@pytest.mark.parametrize(
    "instance",
    [
        {"token": "secret", "channel": "general", "topic": "topic"},
        {"workspace": "/workspace", "token": "secret", "topic": "topic"},
        {"workspace": "/workspace", "token": "secret", "channel": "general"},
        {
            "workspace": "/workspace",
            "token": "secret",
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
        validate(instance=instance, schema=_tool("channel_topic").input_schema)


@pytest.mark.parametrize(
    "instance",
    [
        {"token": "secret", "channel": "general"},
        {"workspace": "/workspace", "token": "secret"},
        {
            "workspace": "/workspace",
            "token": "secret",
            "channel": "general",
            "extra": True,
        },
    ],
)
def test_channel_show_schema_rejects_missing_and_additional_fields(
    instance: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        validate(instance=instance, schema=_tool("channel_show").input_schema)


@pytest.mark.parametrize("topic", [None, "", "\u200b", "topic", " spaced ", "x" * 500])
def test_channel_topic_schema_accepts_clear_and_exact_one_line_text(
    topic: str | None,
) -> None:
    validate(
        instance={
            "workspace": "/workspace",
            "token": "secret",
            "channel": "general",
            "topic": topic,
        },
        schema=_tool("channel_topic").input_schema,
    )


@pytest.mark.parametrize("tool_name", ["channel_show", "channel_topic"])
def test_missing_channel_preserves_not_found_for_reactor_mapping(
    tool_name: str,
) -> None:
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
    with pytest.raises(NotFoundError, match="^channel not found: missing$"):
        execute_command(cast(TautClient, MissingClient()), tool_name, arguments)


def test_thread_result_schema_is_closed_and_kind_discriminated() -> None:
    assert _tool("list").output_schema is None
    schema = result_schema("thread")

    valid = [
        {
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

    invalid: dict[str, object] = {
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
        "topic_updated_ts": "0000000000000000123",
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


def test_hash_prefixed_channel_and_subthread_schema_patterns() -> None:
    subthread = "general.1234567890123456789"
    hash_subthread = f"#{subthread}"

    # Channel-only tools accept #general and general, and reject subthreads, ##general, #General.
    channel_only_cases: list[tuple[str, str, dict[str, object]]] = [
        ("join", "thread", {"workspace": "/ws", "token": "tok"}),
        (
            "reply",
            "thread",
            {
                "workspace": "/ws",
                "token": "tok",
                "msg_id": "1234567890123456789",
                "text": "hi",
            },
        ),
        ("channel_show", "channel", {"workspace": "/ws", "token": "tok"}),
        (
            "channel_topic",
            "channel",
            {"workspace": "/ws", "token": "tok", "topic": "ok"},
        ),
        (
            "channel_rename",
            "old_name",
            {"workspace": "/ws", "token": "tok", "new_name": "ops"},
        ),
        (
            "channel_rename",
            "new_name",
            {"workspace": "/ws", "token": "tok", "old_name": "general"},
        ),
    ]
    for tool_name, field_name, base in channel_only_cases:
        schema = _tool(tool_name).input_schema
        for good in ("general", "#general"):
            validate(instance={**base, field_name: good}, schema=schema)
        for bad in (subthread, hash_subthread, "##general", "#General"):
            with pytest.raises(ValidationError):
                validate(instance={**base, field_name: bad}, schema=schema)

    search_schema = _tool("search").input_schema
    validate(
        instance={
            "workspace": "/ws",
            "token": "tok",
            "query": "needle",
            "channels": ["general", "#general"],
        },
        schema=search_schema,
    )
    for bad in (subthread, hash_subthread, "##general", "#General"):
        with pytest.raises(ValidationError):
            validate(
                instance={
                    "workspace": "/ws",
                    "token": "tok",
                    "query": "needle",
                    "channels": [bad],
                },
                schema=search_schema,
            )

    # Sub-thread-capable tools accept general, #general, subthread, and #subthread.
    for tool_name in ("leave", "read", "log", "who"):
        schema = _tool(tool_name).input_schema
        for good in ("general", "#general", subthread, hash_subthread):
            validate(
                instance={"workspace": "/ws", "token": "tok", "thread": good},
                schema=schema,
            )
        for bad in ("##general", "#General", "##" + subthread):
            with pytest.raises(ValidationError):
                validate(
                    instance={"workspace": "/ws", "token": "tok", "thread": bad},
                    schema=schema,
                )
