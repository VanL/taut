from __future__ import annotations

import asyncio
import hashlib
import json
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, cast

import pytest
from jsonschema import ValidationError, validate
from simplebroker import BrokerTarget, Queue

import taut_mcp._workspace_reactor as workspace_reactor
from taut import (
    MessageDeletion,
    Notification,
    SearchHit,
    TautClient,
    TautError,
    identity,
)
from taut.search._jobs import PENDING_QUEUE_NAME
from taut_mcp._commands import RECORD_TYPE_BY_TOOL, execute_command, record_object
from taut_mcp._process_reactor import (
    ProcessReactor,
    WorkspaceToolError,
    _notification_record,
    command_result,
)
from taut_mcp._tools import TOOLS

READ_GUIDANCE = [
    {
        "action": (
            "Use log for non-consuming channel, sub-thread, or accessible "
            "direct-message rereads. After an uncertain read, inspect list "
            "before retrying."
        ),
        "code": "read_cursor_advanced",
        "message": (
            "Read cursors advanced through the returned records; no message "
            "history was deleted."
        ),
    }
]

MESSAGE_NOT_DELETED_GUIDANCE = [
    {
        "action": (
            "Verify the full 19-digit message id and current author identity "
            "before retrying."
        ),
        "code": "message_not_deleted",
        "message": "No matching deletable own message was found.",
    }
]

MESSAGE_REACTION_NOT_SENT_GUIDANCE = [
    {
        "action": (
            "Verify the full 19-digit message id, current membership, and that "
            "another current thread member exists before retrying."
        ),
        "code": "message_reaction_not_sent",
        "message": "No reactable message with a current recipient was found.",
    }
]


@contextmanager
def _tool_error(message: str) -> Iterator[None]:
    with pytest.raises(WorkspaceToolError) as raised:
        yield
    assert str(raised.value) == message


def _workspace_with_two_members(
    tmp_path: Path,
    name: str = "workspace",
    selected_name: str = "selected",
    other_name: str = "other",
) -> tuple[Path, str]:
    workspace = tmp_path / name
    workspace.mkdir()
    db = workspace / ".taut.db"
    TautClient.init(db_path=db)

    selected = TautClient(db_path=db, as_name=selected_name)
    selected.join("general")
    member = selected.last_created_member
    assert member is not None
    assert member.token is not None
    selected.close()

    other = TautClient(db_path=db, as_name=other_name)
    other.join("general")
    other.say("general", f"hello @{selected_name}")
    other.close()
    return workspace, member.token


async def _wait_until(predicate: Any, *, timeout: float = 5.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        if asyncio.get_running_loop().time() >= deadline:
            raise AssertionError("condition did not become true")
        await asyncio.sleep(0.01)


def _assert_result(
    payload: dict[str, Any],
    *,
    record_type: str,
    workspace: str,
    guidance: list[dict[str, str]] | None = None,
) -> None:
    assert payload["record_type"] == record_type
    assert payload["workspace"] == workspace
    assert payload["empty"] is (not payload["records"])
    assert payload["guidance"] == ([] if guidance is None else guidance)
    assert payload["warnings"] == []
    schema = next(
        tool.output_schema
        for tool in TOOLS
        if tool.output_schema is not None
        and tool.output_schema["properties"]["record_type"].get("const") == record_type
    )
    validate(instance=payload, schema=schema)


@pytest.mark.parametrize(
    ("tool", "arguments", "method", "positional", "keywords"),
    [
        (
            "join",
            {"thread": "work", "persona": "reviewer"},
            "join",
            ("work",),
            {"persona": "reviewer", "new": False},
        ),
        ("leave", {"thread": "work"}, "leave", ("work",), {}),
        ("set_name", {"name": "renamed"}, "set_name", ("renamed",), {}),
        (
            "say",
            {"target": "general", "text": "hello"},
            "say",
            ("general", "hello"),
            {},
        ),
        (
            "reply",
            {"thread": "general", "msg_id": "123", "text": "child"},
            "reply",
            ("general", "123", "child"),
            {},
        ),
        (
            "message_show",
            {"msg_id": "1234567890123456789"},
            "show_message",
            ("1234567890123456789",),
            {},
        ),
        (
            "message_delete",
            {"msg_id": "1234567890123456789"},
            "delete_message",
            ("1234567890123456789",),
            {},
        ),
        (
            "message_react",
            {"msg_id": "1234567890123456789", "reaction": "ack"},
            "react_to_message",
            ("1234567890123456789", "ack"),
            {},
        ),
        (
            "read",
            {"thread": None, "limit": 17},
            "read",
            (None,),
            {"limit": 17},
        ),
        ("inbox", {"limit": 19}, "inbox", (), {"limit": 19}),
        (
            "log",
            {"thread": "general", "since": 11, "limit": 23},
            "log",
            ("general",),
            {"since": 11, "limit": 23},
        ),
        (
            "search",
            {
                "query": "parser",
                "channels": ("general",),
                "direct_messages": ("@Ada",),
                "all_direct_messages": True,
                "from_member": "Ada",
                "kinds": ("message", "notice"),
                "before": "1234567890123456789",
                "limit": 23,
                "reindex": True,
            },
            "search",
            ("parser",),
            {
                "channels": ("general",),
                "direct_messages": ("@Ada",),
                "all_direct_messages": True,
                "from_member": "Ada",
                "kinds": ("message", "notice"),
                "before": "1234567890123456789",
                "limit": 23,
                "reindex": True,
            },
        ),
        (
            "list",
            {"all": True},
            "list_threads",
            (),
            {"all_threads": True},
        ),
        (
            "channel_rename",
            {"old_name": "general", "new_name": "main"},
            "rename_channel",
            ("general", "main"),
            {},
        ),
        ("who", {"thread": None}, "who", (None,), {}),
        ("whoami", {}, "whoami", (), {"explain": False}),
    ],
)
def test_each_ordinary_tool_is_a_thin_public_client_proxy(
    tool: str,
    arguments: dict[str, object],
    method: str,
    positional: tuple[object, ...],
    keywords: dict[str, object],
) -> None:
    """[MCP-5]/[MCP-12] Dispatch names and arguments stay core-canonical."""

    record = object()
    calls: list[tuple[str, tuple[object, ...], dict[str, object]]] = []
    iterable_methods = {"read", "inbox", "log", "search", "list_threads", "who"}

    class PublicClientSpy:
        def __getattr__(self, name: str) -> Any:
            def invoke(*args: object, **kwargs: object) -> object:
                calls.append((name, args, kwargs))
                return [record] if name in iterable_methods else record

            return invoke

    result = execute_command(
        cast(TautClient, PublicClientSpy()),
        tool,
        tuple(cast(dict[str, Any], arguments).items()),
    )
    assert result.record_type == RECORD_TYPE_BY_TOOL[tool]
    assert result.records == (record,)
    assert calls == [(method, positional, keywords)]


def test_search_command_layer_supplies_every_omitted_default_once() -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    class PublicClientSpy:
        def search(self, query: str, **kwargs: object) -> list[SearchHit]:
            calls.append((query, kwargs))
            return []

    result = execute_command(
        cast(TautClient, PublicClientSpy()),
        "search",
        (("query", "parser"),),
    )

    assert result.record_type == "search_hit"
    assert result.records == ()
    assert calls == [
        (
            "parser",
            {
                "channels": (),
                "direct_messages": (),
                "all_direct_messages": False,
                "from_member": None,
                "kinds": (),
                "before": None,
                "limit": 50,
                "reindex": False,
            },
        )
    ]


@pytest.mark.parametrize(
    "failure",
    [TautError("domain failure"), TypeError("bad type"), ValueError("bad value")],
)
def test_search_preserves_domain_and_argument_failures(failure: Exception) -> None:
    class PublicClientSpy:
        def search(self, query: str, **kwargs: object) -> list[SearchHit]:
            raise failure

    with pytest.raises(type(failure)) as raised:
        execute_command(
            cast(TautClient, PublicClientSpy()),
            "search",
            (("query", "parser"),),
        )
    assert raised.value is failure


def test_search_sanitizes_unexpected_provider_failures() -> None:
    class PublicClientSpy:
        def search(self, query: str, **kwargs: object) -> list[SearchHit]:
            raise RuntimeError("postgres secret detail")

    with pytest.raises(
        TautError,
        match=(
            "^search provider or index unavailable; fix the workspace search "
            "provider or index and retry$"
        ),
    ) as raised:
        execute_command(
            cast(TautClient, PublicClientSpy()),
            "search",
            (("query", "parser"),),
        )
    assert "postgres" not in str(raised.value)


def test_search_hit_record_projection_is_exact_and_json_safe() -> None:
    hit = SearchHit(
        thread="dm.d_abcdefghijklmnopqrstuvwxyz",
        ts=1_800_000_000_000_000_123,
        from_id="m_author",
        from_name="Ada",
        kind="message",
        text="parser is green",
        thread_kind="dm",
        channel=None,
        parent=None,
        members=("m_actor", "m_author"),
    )

    assert record_object(hit) == {
        "thread": "dm.d_abcdefghijklmnopqrstuvwxyz",
        "ts": "1800000000000000123",
        "from_id": "m_author",
        "from": "Ada",
        "kind": "message",
        "text": "parser is green",
        "thread_kind": "dm",
        "channel": None,
        "parent": None,
        "members": ["m_actor", "m_author"],
    }


def test_list_dms_is_a_thin_public_client_proxy() -> None:
    record = object()
    calls: list[str] = []

    class PublicClientSpy:
        def list_direct_messages(self) -> list[object]:
            calls.append("list_direct_messages")
            return [record]

    result = execute_command(
        cast(TautClient, PublicClientSpy()),
        "list",
        (("all", False), ("dms", True)),
    )

    assert result.record_type == "thread"
    assert result.records == (record,)
    assert calls == ["list_direct_messages"]


def test_list_rejects_all_and_dms_before_public_client_dispatch() -> None:
    class PublicClientSpy:
        def __getattr__(self, name: str) -> object:
            raise AssertionError(f"unexpected client dispatch: {name}")

    with pytest.raises(ValueError, match="all and dms are mutually exclusive"):
        execute_command(
            cast(TautClient, PublicClientSpy()),
            "list",
            (("all", True), ("dms", True)),
        )


@pytest.mark.parametrize("tool_name", ["read", "log"])
@pytest.mark.parametrize(
    "selector",
    [
        "@Claude",
        "dm.d_" + "a" * 26,
        "general",
        "general.1234567890123456789",
    ],
)
def test_read_and_log_schemas_accept_chat_or_dm_selectors(
    tool_name: str,
    selector: str,
) -> None:
    tool = next(tool for tool in TOOLS if tool.name == tool_name)

    validate(
        instance={"workspace": "/workspace", "token": "secret", "thread": selector},
        schema=tool.input_schema,
    )


@pytest.mark.parametrize(
    "since",
    [
        None,
        9_007_199_254_740_991,
        "2026-08-10T12:34:56Z",
        "1800000000000000001",
        "1800000000",
    ],
)
def test_log_since_schema_preserves_strings_and_safe_json_integers(
    since: object,
) -> None:
    tool = next(tool for tool in TOOLS if tool.name == "log")

    validate(
        instance={
            "workspace": "/workspace",
            "token": "secret",
            "thread": "general",
            "since": since,
        },
        schema=tool.input_schema,
    )


@pytest.mark.parametrize(
    "since",
    [9_007_199_254_740_992, -9_007_199_254_740_992],
)
def test_log_since_rejects_unsafe_bare_json_integer_before_dispatch(
    since: int,
) -> None:
    tool = next(tool for tool in TOOLS if tool.name == "log")
    arguments = {
        "workspace": "/workspace",
        "token": "secret",
        "thread": "general",
        "since": since,
    }

    with pytest.raises(ValidationError):
        validate(instance=arguments, schema=tool.input_schema)

    class PublicClientSpy:
        def __getattr__(self, name: str) -> object:
            raise AssertionError(f"unexpected client dispatch: {name}")

    with pytest.raises(ValueError, match="since integer must be JSON-safe"):
        execute_command(
            cast(TautClient, PublicClientSpy()),
            "log",
            (("thread", "general"), ("since", since)),
        )


@pytest.mark.parametrize("tool_name", ["read", "log"])
@pytest.mark.parametrize(
    "selector",
    [
        "@",
        "@bad.name",
        "dm.d_short",
        "dm.d_" + "A" * 26,
        "dm.d_" + "0" * 26,
    ],
)
def test_read_and_log_schemas_reject_malformed_dm_selectors(
    tool_name: str,
    selector: str,
) -> None:
    tool = next(tool for tool in TOOLS if tool.name == tool_name)

    with pytest.raises(ValidationError):
        validate(
            instance={
                "workspace": "/workspace",
                "token": "secret",
                "thread": selector,
            },
            schema=tool.input_schema,
        )


def test_list_schema_rejects_all_and_dms_together() -> None:
    tool = next(tool for tool in TOOLS if tool.name == "list")

    with pytest.raises(ValidationError):
        validate(
            instance={
                "workspace": "/workspace",
                "token": "secret",
                "all": True,
                "dms": True,
            },
            schema=tool.input_schema,
        )

    for arguments in (
        {"workspace": "/workspace", "token": "secret"},
        {"workspace": "/workspace", "token": "secret", "all": True},
        {"workspace": "/workspace", "token": "secret", "dms": True},
        {
            "workspace": "/workspace",
            "token": "secret",
            "all": False,
            "dms": False,
        },
    ):
        validate(instance=arguments, schema=tool.input_schema)


def test_message_deletion_record_encoding_is_closed_and_content_free() -> None:
    deletion = MessageDeletion(
        thread="general",
        ts=1_234_567_890_123_456_789,
    )

    assert record_object(deletion) == {
        "deleted": True,
        "thread": "general",
        "ts": "1234567890123456789",
    }


def test_record_encoding_formats_all_external_timestamp_fields_only() -> None:
    from taut import Channel, Member, Message, Thread

    first = 1_800_000_000_000_000_001
    second = 1_800_000_000_000_000_002
    message = Message("general", first, "m_sender", "alice", "message", "one")
    adjacent = Message("general", second, "m_sender", "alice", "message", "two")
    member = Member("m_sender", "alice", (), "human", "online", second)
    channel = Channel("general", "topic", second, "m_sender", "alice")
    thread = Thread("general", None, True, second)

    assert record_object(message)["ts"] == "1800000000000000001"
    assert record_object(adjacent)["ts"] == "1800000000000000002"
    assert record_object(member)["last_active_ts"] == "1800000000000000002"
    assert record_object(channel)["topic_updated_ts"] == "1800000000000000002"
    assert record_object(thread)["last_ts"] == "1800000000000000002"
    assert (
        record_object(Channel("empty", None, None, None, None))["topic_updated_ts"]
        is None
    )
    assert record_object(Thread("empty", None, False, None))["last_ts"] is None

    assert message.ts == first
    assert adjacent.ts == second
    assert member.last_active_ts == second
    assert channel.topic_updated_ts == second
    assert thread.last_ts == second


def test_message_reaction_and_notification_encodings_are_closed() -> None:
    from taut import MessageReaction

    reaction = MessageReaction(
        thread="general",
        message_ts=1_234_567_890_123_456_789,
        reaction="ack",
        audience_count=2,
    )
    notification = Notification(
        type="reaction",
        to_id=None,
        actor_id="m_actor",
        actor_name="actor",
        thread="general",
        message_ts=reaction.message_ts,
        reaction="ack",
    )

    assert record_object(reaction) == {
        "audience_count": 2,
        "message_ts": "1234567890123456789",
        "reaction": "ack",
        "thread": "general",
    }
    assert record_object(notification) == {
        "actor_id": "m_actor",
        "actor_name": "actor",
        "message_ts": "1234567890123456789",
        "reaction": "ack",
        "thread": "general",
        "to_id": None,
        "type": "reaction",
    }
    assert _notification_record(notification) == record_object(notification)


def test_empty_reaction_result_has_content_free_guidance() -> None:
    payload = command_result(
        name="message_react",
        record_type="reaction",
        records=[],
        warnings=[],
        workspace="/workspace",
    )

    assert payload == {
        "empty": True,
        "guidance": MESSAGE_REACTION_NOT_SENT_GUIDANCE,
        "record_type": "reaction",
        "records": [],
        "warnings": [],
        "workspace": "/workspace",
    }


@pytest.mark.sqlite_only
@pytest.mark.timeout(15)
def test_all_cli_shaped_tools_dispatch_on_the_workspace_owner_thread(
    tmp_path: Path,
) -> None:
    """[MCP-5]/[MCP-6] Every explicit ordinary tool has a real firing case."""

    workspace, token = _workspace_with_two_members(tmp_path)
    other = TautClient(db_path=workspace / ".taut.db", as_name="other")
    other_owned = other.say("general", "not deletable by selected")

    async def scenario() -> None:
        reactor = ProcessReactor(asyncio.get_running_loop())
        try:
            attached = await reactor.attach_workspace(str(workspace), token)
            canonical = str(attached["workspace"])

            joined = await reactor._execute_ready_tool(
                canonical,
                "join",
                {"thread": "work", "persona": "reviewer"},
            )
            _assert_result(joined, record_type="message", workspace=canonical)
            assert joined["records"][0]["thread"] == "work"
            assert joined["records"][0]["kind"] == "notice"

            left = await reactor._execute_ready_tool(
                canonical,
                "leave",
                {"thread": "work"},
            )
            _assert_result(left, record_type="message", workspace=canonical)
            assert left["records"][0]["text"] == "selected left"

            named = await reactor._execute_ready_tool(
                canonical,
                "set_name",
                {"name": "renamed"},
            )
            _assert_result(named, record_type="member", workspace=canonical)
            assert named["records"][0]["name"] == "renamed"
            assert "token" not in named["records"][0]

            said = await reactor._execute_ready_tool(
                canonical,
                "say",
                {"target": "general", "text": "top level"},
            )
            _assert_result(said, record_type="message", workspace=canonical)
            parent_ts = said["records"][0]["ts"]

            reacted = await reactor._execute_ready_tool(
                canonical,
                "message_react",
                {"msg_id": str(parent_ts), "reaction": "ack"},
            )
            _assert_result(reacted, record_type="reaction", workspace=canonical)
            assert reacted["records"] == [
                {
                    "audience_count": 1,
                    "message_ts": parent_ts,
                    "reaction": "ack",
                    "thread": "general",
                }
            ]
            reaction_notification = other.inbox()
            assert len(reaction_notification) == 1
            reacted_actor_id = reaction_notification[0].actor_id
            assert reacted_actor_id is not None
            assert record_object(reaction_notification[0]) == {
                "actor_id": reacted_actor_id,
                "actor_name": "renamed",
                "message_ts": parent_ts,
                "reaction": "ack",
                "thread": "general",
                "to_id": None,
                "type": "reaction",
            }

            missing_reaction = await reactor._execute_ready_tool(
                canonical,
                "message_react",
                {
                    "msg_id": "1234567890123456789",
                    "reaction": "ack",
                },
            )
            _assert_result(
                missing_reaction,
                record_type="reaction",
                workspace=canonical,
                guidance=MESSAGE_REACTION_NOT_SENT_GUIDANCE,
            )
            assert missing_reaction["records"] == []

            replied = await reactor._execute_ready_tool(
                canonical,
                "reply",
                {
                    "thread": "general",
                    "msg_id": str(parent_ts),
                    "text": "child reply",
                },
            )
            _assert_result(replied, record_type="message", workspace=canonical)
            assert replied["records"][0]["thread"] == f"general.{parent_ts}"

            deletion_target = await reactor._execute_ready_tool(
                canonical,
                "say",
                {"target": "general", "text": "delete through MCP"},
            )
            deletion_ts = deletion_target["records"][0]["ts"]
            deleted = await reactor._execute_ready_tool(
                canonical,
                "message_delete",
                {"msg_id": str(deletion_ts)},
            )
            _assert_result(deleted, record_type="deletion", workspace=canonical)
            assert deleted["records"] == [
                {
                    "deleted": True,
                    "thread": "general",
                    "ts": deletion_ts,
                }
            ]

            missing_show = await reactor._execute_ready_tool(
                canonical,
                "message_show",
                {"msg_id": "1234567890123456789"},
            )
            _assert_result(
                missing_show,
                record_type="message",
                workspace=canonical,
            )
            assert missing_show["records"] == []

            repeated_delete = await reactor._execute_ready_tool(
                canonical,
                "message_delete",
                {"msg_id": str(deletion_ts)},
            )
            _assert_result(
                repeated_delete,
                record_type="deletion",
                workspace=canonical,
                guidance=MESSAGE_NOT_DELETED_GUIDANCE,
            )
            assert repeated_delete["records"] == []
            not_author = await reactor._execute_ready_tool(
                canonical,
                "message_delete",
                {"msg_id": str(other_owned.ts)},
            )
            assert not_author == repeated_delete

            unread_after_reaction = other.say("general", "after reaction unread")
            unread = await reactor._execute_ready_tool(
                canonical,
                "read",
                {"thread": "general", "limit": 1},
            )
            _assert_result(
                unread,
                record_type="message",
                workspace=canonical,
                guidance=READ_GUIDANCE,
            )
            assert len(unread["records"]) == 1
            assert unread["records"][0]["ts"] == str(unread_after_reaction.ts)
            assert unread["records"][0]["text"] == "after reaction unread"

            shown = await reactor._execute_ready_tool(
                canonical,
                "message_show",
                {"msg_id": str(parent_ts)},
            )
            _assert_result(shown, record_type="message", workspace=canonical)
            assert shown["records"] == [said["records"][0]]

            inbox = await reactor._execute_ready_tool(
                canonical,
                "inbox",
                {"limit": 1000},
            )
            _assert_result(inbox, record_type="notification", workspace=canonical)
            assert inbox["records"][0]["type"] == "mention"
            assert inbox["records"][0]["matched"] == "@selected"

            history = await reactor._execute_ready_tool(
                canonical,
                "log",
                {"thread": "general", "since": None, "limit": 1},
            )
            _assert_result(history, record_type="message", workspace=canonical)
            assert len(history["records"]) == 1

            with _tool_error("topic must not be blank"):
                await reactor._execute_ready_tool(
                    canonical,
                    "channel_topic",
                    {"channel": "general", "topic": ""},
                )

            initial_channel = await reactor._execute_ready_tool(
                canonical,
                "channel_show",
                {"channel": "general"},
            )
            _assert_result(
                initial_channel,
                record_type="channel",
                workspace=canonical,
            )
            assert initial_channel["records"] == [
                {
                    "channel": "general",
                    "topic": None,
                    "topic_updated_by_id": None,
                    "topic_updated_by_name": None,
                    "topic_updated_ts": None,
                }
            ]

            history_before_topic = tuple(other.log("general", limit=1000))
            notifications_before_topic = tuple(other.peek_inbox())
            topic = await reactor._execute_ready_tool(
                canonical,
                "channel_topic",
                {"channel": "general", "topic": "Current work"},
            )
            _assert_result(topic, record_type="channel", workspace=canonical)
            assert topic["records"][0]["channel"] == "general"
            assert topic["records"][0]["topic"] == "Current work"
            assert topic["records"][0]["topic_updated_by_name"] == "renamed"
            assert isinstance(topic["records"][0]["topic_updated_ts"], str)
            assert tuple(other.log("general", limit=1000)) == history_before_topic
            assert tuple(other.peek_inbox()) == notifications_before_topic

            same_topic = await reactor._execute_ready_tool(
                canonical,
                "channel_topic",
                {"channel": "general", "topic": "Current work"},
            )
            assert same_topic == topic

            shown_channel = await reactor._execute_ready_tool(
                canonical,
                "channel_show",
                {"channel": "general"},
            )
            assert shown_channel == topic

            missing_channel = await reactor._execute_ready_tool(
                canonical,
                "channel_show",
                {"channel": "missing"},
            )
            _assert_result(
                missing_channel,
                record_type="channel",
                workspace=canonical,
            )
            assert missing_channel["records"] == []

            listed = await reactor._execute_ready_tool(
                canonical,
                "list",
                {"all": True},
            )
            _assert_result(listed, record_type="thread", workspace=canonical)
            assert {record["thread"] for record in listed["records"]} >= {
                "general",
                f"general.{parent_ts}",
            }
            general = next(
                record for record in listed["records"] if record["thread"] == "general"
            )
            assert general["topic"] == "Current work"
            child = next(
                record
                for record in listed["records"]
                if record["thread"] == f"general.{parent_ts}"
            )
            assert "topic" not in child

            renamed = await reactor._execute_ready_tool(
                canonical,
                "channel_rename",
                {"old_name": "general", "new_name": "main"},
            )
            _assert_result(renamed, record_type="thread", workspace=canonical)
            assert renamed["records"][0]["thread"] == "main"
            assert renamed["records"][0]["topic"] == "Current work"

            cleared = await reactor._execute_ready_tool(
                canonical,
                "channel_topic",
                {"channel": "main", "topic": None},
            )
            _assert_result(cleared, record_type="channel", workspace=canonical)
            assert cleared["records"] == [
                {
                    "channel": "main",
                    "topic": None,
                    "topic_updated_by_id": None,
                    "topic_updated_by_name": None,
                    "topic_updated_ts": None,
                }
            ]

            members = await reactor._execute_ready_tool(
                canonical,
                "who",
                {"thread": "main"},
            )
            _assert_result(members, record_type="member", workspace=canonical)
            assert {record["name"] for record in members["records"]} == {
                "other",
                "renamed",
            }

            identity = await reactor._execute_ready_tool(
                canonical,
                "whoami",
                {},
            )
            _assert_result(identity, record_type="member", workspace=canonical)
            assert identity["records"][0]["name"] == "renamed"
            assert "token" not in identity["records"][0]

            empty = await reactor._execute_ready_tool(
                canonical,
                "log",
                {"thread": "missing", "since": None, "limit": 100},
            )
            _assert_result(empty, record_type="message", workspace=canonical)
            assert empty["records"] == []

            with _tool_error("dm is reserved"):
                await reactor._execute_ready_tool(
                    canonical,
                    "join",
                    {"thread": "dm", "persona": None},
                )
        finally:
            await reactor.aclose()

    try:
        asyncio.run(scenario())
    finally:
        other.close()


@pytest.mark.sqlite_only
@pytest.mark.timeout(15)
def test_wrong_kind_channel_is_an_empty_channel_result(tmp_path: Path) -> None:
    """[MCP-6] A registered non-channel row returns the ordinary empty shape."""

    workspace, token = _workspace_with_two_members(tmp_path)
    client = TautClient(db_path=workspace / ".taut.db", as_name="selected")
    with client._meta_queue.sidecar(transaction=True) as session:
        session.run(
            "UPDATE taut_threads SET kind = ? WHERE name = ?",
            ("subthread", "general"),
        )
    client.close()

    async def scenario() -> None:
        reactor = ProcessReactor(asyncio.get_running_loop())
        try:
            attached = await reactor.attach_workspace(str(workspace), token)
            canonical = str(attached["workspace"])
            cases: tuple[tuple[str, dict[str, object]], ...] = (
                ("channel_show", {"channel": "general"}),
                (
                    "channel_topic",
                    {"channel": "general", "topic": "replacement"},
                ),
            )
            for name, arguments in cases:
                result = await reactor._execute_ready_tool(canonical, name, arguments)
                _assert_result(
                    result,
                    record_type="channel",
                    workspace=canonical,
                )
                assert result["records"] == []
        finally:
            await reactor.aclose()

    asyncio.run(scenario())


@pytest.mark.sqlite_only
@pytest.mark.timeout(15)
def test_channel_show_does_not_refresh_notification_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """[MCP-5] Metadata-only show performs no post-command inbox peek."""

    workspace, token = _workspace_with_two_members(tmp_path)

    def unexpected_peek(self: TautClient, *, limit: int = 1000) -> Any:
        del self, limit
        raise AssertionError("channel_show inspected the notification queue")

    async def scenario() -> None:
        reactor = ProcessReactor(asyncio.get_running_loop())
        try:
            attached = await reactor.attach_workspace(str(workspace), token)
            canonical = str(attached["workspace"])
            monkeypatch.setattr(
                workspace_reactor.TautClient,
                "peek_inbox",
                unexpected_peek,
            )
            result = await reactor._execute_ready_tool(
                canonical,
                "channel_show",
                {"channel": "general"},
            )
            _assert_result(result, record_type="channel", workspace=canonical)
            assert result["records"][0]["channel"] == "general"
            assert reactor.list_workspaces()["records"][0]["status"] == "ready"
        finally:
            await reactor.aclose()

    asyncio.run(scenario())


@pytest.mark.sqlite_only
@pytest.mark.timeout(15)
def test_post_command_snapshot_identity_loss_marks_workspace_lost(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """[MCP-11] Identity loss during post-command refresh is terminal."""

    workspace, token = _workspace_with_two_members(tmp_path)

    def lost_identity(self: TautClient, *, limit: int = 1000) -> Any:
        del self, limit
        raise workspace_reactor.TokenError("identity disappeared")

    async def scenario() -> None:
        reactor = ProcessReactor(asyncio.get_running_loop())
        try:
            attached = await reactor.attach_workspace(str(workspace), token)
            canonical = str(attached["workspace"])
            monkeypatch.setattr(
                workspace_reactor.TautClient,
                "peek_inbox",
                lost_identity,
            )
            with _tool_error("workspace identity lost; detach and reattach"):
                await reactor._execute_ready_tool(
                    canonical,
                    "say",
                    {"target": "general", "text": "committed before identity loss"},
                )
            assert reactor.list_workspaces()["records"][0]["status"] == "identity_lost"
        finally:
            await reactor.aclose()

    asyncio.run(scenario())


@pytest.mark.sqlite_only
@pytest.mark.timeout(15)
def test_post_command_snapshot_crash_marks_workspace_failed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """[MCP-11] Unexpected post-command refresh failure crashes the owner."""

    workspace, token = _workspace_with_two_members(tmp_path)

    def unexpected_failure(self: TautClient, *, limit: int = 1000) -> Any:
        del self, limit
        raise RuntimeError("private refresh failure")

    async def scenario() -> None:
        reactor = ProcessReactor(asyncio.get_running_loop())
        try:
            attached = await reactor.attach_workspace(str(workspace), token)
            canonical = str(attached["workspace"])
            monkeypatch.setattr(
                workspace_reactor.TautClient,
                "peek_inbox",
                unexpected_failure,
            )
            with _tool_error("workspace reactor failed; detach and reattach"):
                await reactor._execute_ready_tool(
                    canonical,
                    "say",
                    {"target": "general", "text": "committed before refresh crash"},
                )
            assert reactor.list_workspaces()["records"][0]["status"] == "reactor_failed"
        finally:
            await reactor.aclose()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("tool_name", "method_name", "arguments"),
    [
        ("channel_show", "get_channel", {"channel": "general"}),
        (
            "channel_topic",
            "set_channel_topic",
            {"channel": "general", "topic": "fault"},
        ),
    ],
)
@pytest.mark.sqlite_only
@pytest.mark.timeout(15)
def test_unexpected_channel_tool_fault_is_terminal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    tool_name: str,
    method_name: str,
    arguments: dict[str, object],
) -> None:
    """[MCP-11] Non-Taut channel failures use the terminal reactor path."""

    workspace, token = _workspace_with_two_members(tmp_path)

    def unexpected_fault(*args: object, **kwargs: object) -> object:
        del args, kwargs
        raise RuntimeError("private backend detail")

    async def scenario() -> None:
        reactor = ProcessReactor(asyncio.get_running_loop())
        try:
            attached = await reactor.attach_workspace(str(workspace), token)
            canonical = str(attached["workspace"])
            monkeypatch.setattr(
                workspace_reactor.TautClient,
                method_name,
                unexpected_fault,
            )
            with _tool_error("workspace reactor failed; detach and reattach"):
                await reactor._execute_ready_tool(canonical, tool_name, arguments)
            assert reactor.list_workspaces()["records"][0]["status"] == "reactor_failed"
        finally:
            await reactor.aclose()

    asyncio.run(scenario())


@pytest.mark.sqlite_only
@pytest.mark.timeout(15)
def test_channel_topic_identity_loss_uses_fixed_terminal_status(
    tmp_path: Path,
) -> None:
    """[MCP-11] Lost attachment identity is not a topic-domain error."""

    workspace, token = _workspace_with_two_members(tmp_path)

    async def scenario() -> None:
        reactor = ProcessReactor(asyncio.get_running_loop())
        try:
            attached = await reactor.attach_workspace(str(workspace), token)
            canonical = str(attached["workspace"])
            admin = TautClient(
                db_path=workspace / ".taut.db",
                as_name="selected",
            )
            with admin._meta_queue.sidecar(transaction=True) as session:
                session.run(
                    "UPDATE taut_members SET token = NULL WHERE display_name = ?",
                    ("selected",),
                )
            admin.close()
            with _tool_error("workspace identity lost; detach and reattach"):
                await reactor._execute_ready_tool(
                    canonical,
                    "channel_topic",
                    {"channel": "general", "topic": "lost"},
                )
            assert reactor.list_workspaces()["records"][0]["status"] == "identity_lost"
        finally:
            await reactor.aclose()

    asyncio.run(scenario())


@pytest.mark.sqlite_only
@pytest.mark.timeout(15)
def test_channel_topic_recoverable_storage_error_keeps_workspace_ready(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """[MCP-11] Ordinary backend TautError is not a terminal reactor fault."""

    workspace, token = _workspace_with_two_members(tmp_path)

    def recoverable_failure(
        self: TautClient,
        channel: str,
        topic: str | None,
    ) -> object:
        del self, channel, topic
        raise TautError("recoverable channel storage failure")

    async def scenario() -> None:
        reactor = ProcessReactor(asyncio.get_running_loop())
        try:
            attached = await reactor.attach_workspace(str(workspace), token)
            canonical = str(attached["workspace"])
            monkeypatch.setattr(
                workspace_reactor.TautClient,
                "set_channel_topic",
                recoverable_failure,
            )
            with _tool_error("recoverable channel storage failure"):
                await reactor._execute_ready_tool(
                    canonical,
                    "channel_topic",
                    {"channel": "general", "topic": "new"},
                )
            assert reactor.list_workspaces()["records"][0]["status"] == "ready"
        finally:
            await reactor.aclose()

    asyncio.run(scenario())


@pytest.mark.sqlite_only
@pytest.mark.timeout(15)
def test_corrupt_topic_is_recoverable_tool_error_not_reactor_failure(
    tmp_path: Path,
) -> None:
    """[MCP-6] Stored contract corruption is an ordinary Taut tool error."""

    workspace, token = _workspace_with_two_members(tmp_path)
    client = TautClient(db_path=workspace / ".taut.db", as_name="selected")
    with client._meta_queue.sidecar(transaction=True) as session:
        session.run(
            "UPDATE taut_threads SET meta = ? WHERE name = ?",
            (
                json.dumps(
                    {
                        "topic": {
                            "text": "broken",
                            "updated_ts": 10,
                            "updated_by_id": "m_author",
                            "extra": True,
                        }
                    }
                ),
                "general",
            ),
        )
    client.close()

    async def scenario() -> None:
        reactor = ProcessReactor(asyncio.get_running_loop())
        try:
            attached = await reactor.attach_workspace(str(workspace), token)
            canonical = str(attached["workspace"])
            cases: tuple[tuple[str, dict[str, object]], ...] = (
                ("channel_show", {"channel": "general"}),
                (
                    "channel_topic",
                    {"channel": "general", "topic": "replacement"},
                ),
            )
            for name, arguments in cases:
                with _tool_error(
                    "taut_threads.meta.topic: expected exactly text, "
                    "updated_ts, and updated_by_id"
                ):
                    await reactor._execute_ready_tool(canonical, name, arguments)
            listed = reactor.list_workspaces()
            assert listed["records"][0]["status"] == "ready"
        finally:
            await reactor.aclose()

    asyncio.run(scenario())


@pytest.mark.sqlite_only
@pytest.mark.timeout(15)
def test_show_message_advances_exact_thread_high_water_without_show_guidance(
    tmp_path: Path,
) -> None:
    workspace, token = _workspace_with_two_members(tmp_path)
    db = workspace / ".taut.db"
    selected = TautClient(db_path=db, token=token)
    other = TautClient(db_path=db, as_name="other")
    try:
        selected.read("general", limit=1000)
        older = other.say("general", "older unread")
        target = other.say("general", "exact target")
        later = other.say("general", "later unread")
        selected_row = selected._state.get_member_by_token(token)
        assert selected_row is not None
        member_id = selected_row["member_id"]
    finally:
        selected.close()
        other.close()

    async def scenario() -> None:
        reactor = ProcessReactor(asyncio.get_running_loop())
        observer = TautClient(db_path=db, token=token)
        try:
            canonical = str(
                (await reactor.attach_workspace(str(workspace), token))["workspace"]
            )
            shown = await reactor._execute_ready_tool(
                canonical,
                "message_show",
                {"msg_id": str(target.ts)},
            )
            _assert_result(shown, record_type="message", workspace=canonical)
            assert shown["records"][0]["text"] == "exact target"

            membership = observer._state.get_membership(
                thread="general",
                member_id=member_id,
            )
            assert membership is not None
            assert membership["last_seen_ts"] == target.ts
            unread = await reactor._execute_ready_tool(
                canonical,
                "read",
                {"thread": "general", "limit": 100},
            )
            assert [record["ts"] for record in unread["records"]] == [str(later.ts)]
            assert older.ts < target.ts < later.ts
        finally:
            observer.close()
            await reactor.aclose()

    asyncio.run(scenario())


@pytest.mark.sqlite_only
@pytest.mark.timeout(15)
def test_delete_message_unrelated_dm_is_content_free_and_indistinguishable(
    tmp_path: Path,
) -> None:
    workspace, token = _workspace_with_two_members(tmp_path)
    db = workspace / ".taut.db"
    other = TautClient(db_path=db, as_name="other")
    third = TautClient(db_path=db, as_name="third")
    try:
        third.join("general")
        secret = "private body must not cross MCP"
        direct = other.say("@third", secret)
    finally:
        third.close()
        other.close()

    async def scenario() -> None:
        reactor = ProcessReactor(asyncio.get_running_loop())
        try:
            canonical = str(
                (await reactor.attach_workspace(str(workspace), token))["workspace"]
            )
            ineligible = await reactor._execute_ready_tool(
                canonical,
                "message_delete",
                {"msg_id": str(direct.ts)},
            )
            author = TautClient(db_path=db, as_name="other")
            try:
                author.delete_message(str(direct.ts))
            finally:
                author.close()
            missing = await reactor._execute_ready_tool(
                canonical,
                "message_delete",
                {"msg_id": str(direct.ts)},
            )

            assert ineligible == missing
            _assert_result(
                ineligible,
                record_type="deletion",
                workspace=canonical,
                guidance=MESSAGE_NOT_DELETED_GUIDANCE,
            )
            encoded = json.dumps(ineligible, sort_keys=True)
            for sensitive in (secret, direct.thread, "other", "third"):
                assert sensitive not in encoded
        finally:
            await reactor.aclose()

    asyncio.run(scenario())


@pytest.mark.sqlite_only
@pytest.mark.timeout(15)
def test_message_tools_reject_in_pattern_signed_int64_overflow(
    tmp_path: Path,
) -> None:
    workspace, token = _workspace_with_two_members(tmp_path)

    async def scenario() -> None:
        reactor = ProcessReactor(asyncio.get_running_loop())
        try:
            canonical = str(
                (await reactor.attach_workspace(str(workspace), token))["workspace"]
            )
            for tool_name in (
                "message_show",
                "message_delete",
                "message_react",
            ):
                with _tool_error("msg_id must be a full 19-digit message id"):
                    await reactor._execute_ready_tool(
                        canonical,
                        tool_name,
                        {
                            "msg_id": "9223372036854775808",
                            **(
                                {"reaction": "ack"}
                                if tool_name == "message_react"
                                else {}
                            ),
                        },
                    )
        finally:
            await reactor.aclose()

    asyncio.run(scenario())


@pytest.mark.sqlite_only
@pytest.mark.timeout(15)
def test_attached_workspaces_freeze_independent_reaction_vocabularies(
    tmp_path: Path,
) -> None:
    """[MCP-3]/[MCP-5] Reaction allowlists are per attachment, not process-global."""

    ack_workspace, ack_token = _workspace_with_two_members(tmp_path, "ack")
    done_workspace, done_token = _workspace_with_two_members(
        tmp_path,
        "done",
        "done_selected",
        "done_other",
    )

    def configure(workspace: Path, value: str) -> None:
        (workspace / ".taut.toml").write_text(
            "\n".join(
                [
                    "version = 1",
                    'backend = "sqlite"',
                    'target = ".taut.db"',
                    "",
                    "[reactions]",
                    f'values = ["{value}"]',
                    "",
                ]
            ),
            encoding="utf-8",
        )

    configure(ack_workspace, "ack")
    configure(done_workspace, "done")
    ack_source_client = TautClient(
        db_path=ack_workspace / ".taut.db",
        as_name="other",
    )
    done_source_client = TautClient(
        db_path=done_workspace / ".taut.db",
        as_name="done_other",
    )
    ack_source = ack_source_client.say("general", "ack target")
    done_source = done_source_client.say("general", "done target")
    ack_source_client.close()
    done_source_client.close()

    async def scenario() -> None:
        reactor = ProcessReactor(asyncio.get_running_loop())
        try:
            ack_canonical = str(
                (await reactor.attach_workspace(str(ack_workspace), ack_token))[
                    "workspace"
                ]
            )
            done_canonical = str(
                (await reactor.attach_workspace(str(done_workspace), done_token))[
                    "workspace"
                ]
            )
            ack_result = await reactor._execute_ready_tool(
                ack_canonical,
                "message_react",
                {"msg_id": str(ack_source.ts), "reaction": "ack"},
            )
            done_result = await reactor._execute_ready_tool(
                done_canonical,
                "message_react",
                {"msg_id": str(done_source.ts), "reaction": "done"},
            )
            assert ack_result["records"][0]["reaction"] == "ack"
            assert done_result["records"][0]["reaction"] == "done"

            with _tool_error("reaction must be one of: ack"):
                await reactor._execute_ready_tool(
                    ack_canonical,
                    "message_react",
                    {"msg_id": str(ack_source.ts), "reaction": "done"},
                )
            with _tool_error("reaction must be one of: done"):
                await reactor._execute_ready_tool(
                    done_canonical,
                    "message_react",
                    {"msg_id": str(done_source.ts), "reaction": "ack"},
                )

            configure(ack_workspace, "done")
            frozen = await reactor._execute_ready_tool(
                ack_canonical,
                "message_react",
                {"msg_id": str(ack_source.ts), "reaction": "ack"},
            )
            assert frozen["records"][0]["reaction"] == "ack"

            await reactor.detach_workspace(ack_canonical)
            reattached = await reactor.attach_workspace(
                str(ack_workspace),
                ack_token,
            )
            refreshed = await reactor._execute_ready_tool(
                str(reattached["workspace"]),
                "message_react",
                {"msg_id": str(ack_source.ts), "reaction": "done"},
            )
            assert refreshed["records"][0]["reaction"] == "done"
        finally:
            await reactor.aclose()

    asyncio.run(scenario())


@pytest.mark.sqlite_only
@pytest.mark.timeout(15)
def test_command_warnings_are_ordered_and_operation_local(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """[MCP-6] Notification warnings precede search warnings and never leak."""

    workspace, token = _workspace_with_two_members(tmp_path)
    real_execute = workspace_reactor.execute_command

    def execute_with_warnings(client: TautClient, name: str, arguments: Any) -> Any:
        result = real_execute(client, name, arguments)
        if name == "say":
            client.last_notification_warnings.append("notification warning")
            client.last_search_warnings.append("search warning")
        return result

    monkeypatch.setattr(
        workspace_reactor,
        "execute_command",
        execute_with_warnings,
    )

    async def scenario() -> None:
        reactor = ProcessReactor(asyncio.get_running_loop())
        try:
            canonical = str(
                (await reactor.attach_workspace(str(workspace), token))["workspace"]
            )
            warned = await reactor._execute_ready_tool(
                canonical,
                "say",
                {"target": "general", "text": "warning source commit"},
            )
            assert warned["records"][0]["text"] == "warning source commit"
            assert warned["warnings"] == ["notification warning", "search warning"]

            later = await reactor._execute_ready_tool(canonical, "whoami", {})
            assert later["warnings"] == []
        finally:
            await reactor.aclose()

    asyncio.run(scenario())


@pytest.mark.sqlite_only
@pytest.mark.timeout(15)
def test_search_enqueue_warning_preserves_real_source_and_does_not_leak(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """[MCP-6]/[SRCH-8.3] Source success wins over derived-index warning."""

    workspace, token = _workspace_with_two_members(tmp_path)
    real_write = Queue.write

    def failing_search_enqueue(queue: Queue, body: str) -> int:
        if queue.name == PENDING_QUEUE_NAME:
            raise RuntimeError("index queue offline")
        return real_write(queue, body)

    monkeypatch.setattr(Queue, "write", failing_search_enqueue)

    async def scenario() -> None:
        reactor = ProcessReactor(asyncio.get_running_loop())
        try:
            canonical = str(
                (await reactor.attach_workspace(str(workspace), token))["workspace"]
            )
            sent = await reactor._execute_ready_tool(
                canonical,
                "say",
                {"target": "general", "text": "source survives warning"},
            )
            assert sent["records"][0]["text"] == "source survives warning"
            assert sent["warnings"] == [
                (
                    "search invalidation enqueue failed for general/"
                    f"{sent['records'][0]['ts']}: index queue offline"
                )
            ]
            assert "source survives" not in sent["warnings"][0]

            observer = TautClient(db_path=workspace / ".taut.db", token=token)
            try:
                assert any(
                    message.text == "source survives warning"
                    for message in observer.log("general")
                )
            finally:
                observer.close()

            later = await reactor._execute_ready_tool(canonical, "whoami", {})
            assert later["warnings"] == []
        finally:
            await reactor.aclose()

    asyncio.run(scenario())


@pytest.mark.sqlite_only
@pytest.mark.timeout(15)
def test_same_workspace_rejects_overlap_while_another_workspace_progresses(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """[MCP-5] The no-wait slot is per workspace, not connection-wide."""

    slow_workspace, slow_token = _workspace_with_two_members(tmp_path, "slow")
    fast_workspace, fast_token = _workspace_with_two_members(
        tmp_path,
        "fast",
        "fast_member",
        "fast_other",
    )
    slow_db = (slow_workspace / ".taut.db").resolve()
    started = threading.Event()
    release = threading.Event()
    real_execute = workspace_reactor.execute_command

    def delayed_execute(client: TautClient, name: str, arguments: Any) -> Any:
        assert isinstance(client.target, BrokerTarget)
        target = Path(str(client.target.target)).resolve()
        if target == slow_db and name == "whoami":
            started.set()
            if not release.wait(timeout=5):
                raise AssertionError("test did not release slow command")
        return real_execute(client, name, arguments)

    monkeypatch.setattr(workspace_reactor, "execute_command", delayed_execute)

    async def scenario() -> None:
        reactor = ProcessReactor(asyncio.get_running_loop())
        try:
            slow = str(
                (await reactor.attach_workspace(str(slow_workspace), slow_token))[
                    "workspace"
                ]
            )
            fast = str(
                (await reactor.attach_workspace(str(fast_workspace), fast_token))[
                    "workspace"
                ]
            )
            blocked = asyncio.create_task(
                reactor._execute_ready_tool(slow, "whoami", {})
            )
            assert await asyncio.to_thread(started.wait, 5)

            with _tool_error("workspace busy; retry after backoff"):
                await reactor._execute_ready_tool(slow, "who", {"thread": None})
            for tool_name in (
                "message_show",
                "message_delete",
                "message_react",
            ):
                with _tool_error("workspace busy; retry after backoff"):
                    await reactor._execute_ready_tool(
                        slow,
                        tool_name,
                        {
                            "msg_id": "1234567890123456789",
                            **(
                                {"reaction": "ack"}
                                if tool_name == "message_react"
                                else {}
                            ),
                        },
                    )
            with _tool_error("workspace busy; retry after backoff"):
                await reactor.detach_workspace(slow)

            independent = await asyncio.wait_for(
                reactor._execute_ready_tool(fast, "whoami", {}),
                timeout=2,
            )
            assert independent["records"][0]["name"] == "fast_member"
            release.set()
            completed = await blocked
            assert completed["records"][0]["name"] == "selected"
        finally:
            release.set()
            await reactor.aclose()

    asyncio.run(scenario())


@pytest.mark.sqlite_only
@pytest.mark.timeout(15)
def test_cancel_before_child_start_is_a_no_op_and_releases_the_slot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """[MCP-5] Execute plus cancel in one drain makes no Taut call."""

    workspace, token = _workspace_with_two_members(tmp_path)
    blocked_peek = threading.Event()
    release_peek = threading.Event()
    calls = 0
    calls_lock = threading.Lock()
    real_peek = workspace_reactor.TautClient.peek_inbox

    def delayed_peek(self: TautClient, *, limit: int = 1000) -> Any:
        nonlocal calls
        with calls_lock:
            calls += 1
            call_number = calls
        if call_number == 2:
            blocked_peek.set()
            if not release_peek.wait(timeout=5):
                raise AssertionError("test did not release periodic peek")
        return real_peek(self, limit=limit)

    monkeypatch.setattr(workspace_reactor.TautClient, "peek_inbox", delayed_peek)

    async def scenario() -> None:
        reactor = ProcessReactor(asyncio.get_running_loop())
        try:
            canonical = str(
                (await reactor.attach_workspace(str(workspace), token))["workspace"]
            )
            assert await asyncio.to_thread(blocked_peek.wait, 5)
            canceled = asyncio.create_task(
                reactor._execute_ready_tool(
                    canonical,
                    "say",
                    {"target": "general", "text": "must not commit"},
                )
            )
            await _wait_until(
                lambda: reactor._entries[canonical].active_command_id is not None
            )
            canceled.cancel()
            with pytest.raises(asyncio.CancelledError):
                await canceled
            with _tool_error("workspace busy; retry after backoff"):
                await reactor.detach_workspace(canonical)

            release_peek.set()
            await _wait_until(
                lambda: reactor._entries[canonical].active_command_id is None
            )
            observer = TautClient(db_path=workspace / ".taut.db", token=token)
            try:
                assert all(
                    message.text != "must not commit"
                    for message in observer.log("general")
                )
            finally:
                observer.close()
            identity = await reactor._execute_ready_tool(canonical, "whoami", {})
            assert identity["records"][0]["name"] == "selected"
        finally:
            release_peek.set()
            await reactor.aclose()

    asyncio.run(scenario())


@pytest.mark.sqlite_only
@pytest.mark.timeout(15)
def test_cancel_after_child_start_discards_result_but_keeps_committed_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """[MCP-5] A late cancel is not a rollback boundary."""

    workspace, token = _workspace_with_two_members(tmp_path)
    started = threading.Event()
    release = threading.Event()
    real_execute = workspace_reactor.execute_command

    def delayed_execute(client: TautClient, name: str, arguments: Any) -> Any:
        if name == "say":
            started.set()
            if not release.wait(timeout=5):
                raise AssertionError("test did not release started command")
        return real_execute(client, name, arguments)

    monkeypatch.setattr(workspace_reactor, "execute_command", delayed_execute)

    async def scenario() -> None:
        reactor = ProcessReactor(asyncio.get_running_loop())
        try:
            canonical = str(
                (await reactor.attach_workspace(str(workspace), token))["workspace"]
            )
            canceled = asyncio.create_task(
                reactor._execute_ready_tool(
                    canonical,
                    "say",
                    {"target": "general", "text": "commits after start"},
                )
            )
            assert await asyncio.to_thread(started.wait, 5)
            canceled.cancel()
            with pytest.raises(asyncio.CancelledError):
                await canceled
            with _tool_error("workspace busy; retry after backoff"):
                await reactor.detach_workspace(canonical)

            release.set()
            await _wait_until(
                lambda: reactor._entries[canonical].active_command_id is None
            )
            observer = TautClient(db_path=workspace / ".taut.db", token=token)
            try:
                assert any(
                    message.text == "commits after start"
                    for message in observer.log("general")
                )
            finally:
                observer.close()
            identity = await reactor._execute_ready_tool(canonical, "whoami", {})
            assert identity["records"][0]["name"] == "selected"
        finally:
            release.set()
            await reactor.aclose()

    asyncio.run(scenario())


@pytest.mark.sqlite_only
@pytest.mark.timeout(15)
@pytest.mark.parametrize("selector_mode", ["explicit", "bare"])
def test_canceled_started_dm_read_recovers_directory_and_history(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    selector_mode: str,
) -> None:
    """[MCP-5]/[MCP-11] Recovery exposes state/history, not delivery proof."""

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    db = workspace / ".taut.db"
    TautClient.init(db_path=db)
    selected = TautClient(db_path=db, as_name="selected")
    selected.join("general")
    member = selected.last_created_member
    assert member is not None and member.token is not None
    selected_id = member.member_id
    other = TautClient(db_path=db, as_name="other")
    other.join("general")
    sent = other.say("@selected", "uncertain DM page")
    selected.close()
    other.close()

    committed = threading.Event()
    release = threading.Event()
    real_execute = workspace_reactor.execute_command

    def commit_then_delay_result(
        client: TautClient,
        name: str,
        arguments: Any,
    ) -> Any:
        result = real_execute(client, name, arguments)
        if name == "read":
            committed.set()
            if not release.wait(timeout=5):
                raise AssertionError("test did not release committed DM read")
        return result

    monkeypatch.setattr(
        workspace_reactor,
        "execute_command",
        commit_then_delay_result,
    )

    async def scenario() -> None:
        reactor = ProcessReactor(asyncio.get_running_loop())
        observer = TautClient(db_path=db)
        try:
            canonical = str(
                (
                    await reactor.attach_workspace(
                        str(workspace),
                        member.token or "",
                    )
                )["workspace"]
            )
            canceled = asyncio.create_task(
                reactor._execute_ready_tool(
                    canonical,
                    "read",
                    {
                        "thread": sent.thread if selector_mode == "explicit" else None,
                        "limit": 100,
                    },
                )
            )
            assert await asyncio.to_thread(committed.wait, 5)
            canceled.cancel()
            with pytest.raises(asyncio.CancelledError):
                await canceled

            release.set()
            await _wait_until(
                lambda: reactor._entries[canonical].active_command_id is None
            )
            directory = await reactor._execute_ready_tool(
                canonical,
                "list",
                {"dms": True},
            )
            assert directory["records"][0]["thread"] == sent.thread
            assert directory["records"][0]["unread"] is False

            membership_before = observer._state.get_membership(
                thread=sent.thread,
                member_id=selected_id,
            )
            actor_before = observer._state.get_member(selected_id)
            history = await reactor._execute_ready_tool(
                canonical,
                "log",
                {"thread": sent.thread, "since": None, "limit": 100},
            )
            assert history["records"][0]["text"] == "uncertain DM page"
            assert history["guidance"] == []
            assert (
                observer._state.get_membership(
                    thread=sent.thread,
                    member_id=selected_id,
                )
                == membership_before
            )
            assert observer._state.get_member(selected_id) == actor_before
        finally:
            release.set()
            observer.close()
            await reactor.aclose()

    asyncio.run(scenario())


@pytest.mark.sqlite_only
@pytest.mark.timeout(15)
@pytest.mark.parametrize(
    ("terminal", "expected_status", "expected_error"),
    [
        (
            "identity",
            "identity_lost",
            "workspace identity lost; detach and reattach",
        ),
        (
            "fault",
            "reactor_failed",
            "workspace reactor failed; detach and reattach",
        ),
    ],
)
def test_terminal_event_settles_an_occupied_command_slot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    terminal: str,
    expected_status: str,
    expected_error: str,
) -> None:
    """[MCP-5] Terminal child events synthesize one command completion."""

    workspace, token = _workspace_with_two_members(tmp_path)
    started = threading.Event()
    release = threading.Event()
    real_execute = workspace_reactor.execute_command

    def terminal_execute(client: TautClient, name: str, arguments: Any) -> Any:
        started.set()
        if not release.wait(timeout=5):
            raise AssertionError("test did not release terminal command")
        if terminal == "fault":
            raise RuntimeError("must not cross the child boundary")
        return real_execute(client, name, arguments)

    monkeypatch.setattr(workspace_reactor, "execute_command", terminal_execute)

    async def scenario() -> None:
        reactor = ProcessReactor(asyncio.get_running_loop())
        try:
            canonical = str(
                (await reactor.attach_workspace(str(workspace), token))["workspace"]
            )
            command = asyncio.create_task(
                reactor._execute_ready_tool(canonical, "whoami", {})
            )
            assert await asyncio.to_thread(started.wait, 5)
            if terminal == "identity":
                admin = TautClient(
                    db_path=workspace / ".taut.db",
                    as_name="selected",
                )
                with admin._meta_queue.sidecar(transaction=True) as session:
                    session.run(
                        "UPDATE taut_members SET token = NULL WHERE display_name = ?",
                        ("selected",),
                    )
                admin.close()
            release.set()
            with _tool_error(expected_error):
                await command
            entry = reactor._entries[canonical]
            assert entry.status == expected_status
            assert entry.active_command_id is None
            assert entry.command_future is None
            detached = await reactor.detach_workspace(canonical)
            assert detached["records"][0]["status"] == "detached"
        finally:
            release.set()
            await reactor.aclose()

    asyncio.run(scenario())


@pytest.mark.sqlite_only
@pytest.mark.timeout(15)
def test_bare_read_forwards_per_thread_limit_and_includes_direct_messages(
    tmp_path: Path,
) -> None:
    """[MCP-5]/[MCP-6] Bare read is bounded per selected chat queue."""

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    db = workspace / ".taut.db"
    TautClient.init(db_path=db)
    selected = TautClient(db_path=db, as_name="selected")
    selected.join("general")
    member = selected.last_created_member
    assert member is not None
    assert member.token is not None
    selected.join("alpha")
    selected.close()
    other = TautClient(db_path=db, as_name="other")
    other.join("general")
    other.join("alpha")
    other.say("general", "general one")
    other.say("general", "general two")
    other.say("alpha", "alpha one")
    other.say("alpha", "alpha two")
    private = other.say("@selected", "private one")
    other.close()

    async def scenario() -> None:
        reactor = ProcessReactor(asyncio.get_running_loop())
        try:
            canonical = str(
                (
                    await reactor.attach_workspace(
                        str(workspace),
                        member.token or "",
                    )
                )["workspace"]
            )
            first = await reactor._execute_ready_tool(
                canonical,
                "read",
                {"limit": 1},
            )
            _assert_result(
                first,
                record_type="message",
                workspace=canonical,
                guidance=READ_GUIDANCE,
            )
            assert len(first["records"]) == 3
            assert len({record["thread"] for record in first["records"]}) == 3
            assert any(
                record["thread"] == private.thread for record in first["records"]
            )

            second = await reactor._execute_ready_tool(
                canonical,
                "read",
                {"thread": None, "limit": 1},
            )
            assert len(second["records"]) <= 2
            assert len({record["thread"] for record in second["records"]}) == len(
                second["records"]
            )

            history = await reactor._execute_ready_tool(
                canonical,
                "log",
                {"thread": "general", "since": None, "limit": 100},
            )
            assert {record["text"] for record in history["records"]} >= {
                "general one",
                "general two",
            }
        finally:
            await reactor.aclose()

    asyncio.run(scenario())


@pytest.mark.sqlite_only
@pytest.mark.timeout(15)
def test_explicit_dm_read_log_and_directory_use_public_core_contract(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    db = workspace / ".taut.db"
    TautClient.init(db_path=db)
    selected = TautClient(db_path=db, as_name="selected")
    selected.join("general")
    member = selected.last_created_member
    assert member is not None and member.token is not None
    selected_id = member.member_id
    other = TautClient(db_path=db, as_name="other")
    other.join("general")
    sent = other.say("@selected", "private history")
    selected.close()
    other.close()

    async def scenario() -> None:
        reactor = ProcessReactor(asyncio.get_running_loop())
        observer = TautClient(db_path=db)
        try:
            canonical = str(
                (
                    await reactor.attach_workspace(
                        str(workspace),
                        member.token or "",
                    )
                )["workspace"]
            )
            before_log = observer._state.get_member(selected_id)
            assert before_log is not None

            history = await reactor._execute_ready_tool(
                canonical,
                "log",
                {"thread": "@other", "since": None, "limit": 100},
            )
            _assert_result(history, record_type="message", workspace=canonical)
            assert history["records"][0]["thread"] == sent.thread
            assert history["records"][0]["text"] == "private history"
            assert observer._state.get_member(selected_id) == before_log

            unread = await reactor._execute_ready_tool(
                canonical,
                "read",
                {"thread": sent.thread, "limit": 100},
            )
            _assert_result(
                unread,
                record_type="message",
                workspace=canonical,
                guidance=READ_GUIDANCE,
            )
            assert unread["records"][0]["thread"] == sent.thread

            directory = await reactor._execute_ready_tool(
                canonical,
                "list",
                {"dms": True},
            )
            _assert_result(directory, record_type="thread", workspace=canonical)
            assert directory["records"] == [
                {
                    "kind": "dm",
                    "last_ts": str(sent.ts),
                    "members": list(
                        next(
                            item
                            for item in observer.list_threads(all_threads=True)
                            if item.name == sent.thread
                        ).members
                    ),
                    "parent": None,
                    "thread": sent.thread,
                    "unread": False,
                }
            ]
        finally:
            observer.close()
            await reactor.aclose()

    asyncio.run(scenario())


@pytest.mark.sqlite_only
@pytest.mark.timeout(15)
def test_well_formed_absent_and_inaccessible_dms_are_content_free_empty_results(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    db = workspace / ".taut.db"
    TautClient.init(db_path=db)
    selected = TautClient(db_path=db, as_name="selected")
    selected.join("general")
    member = selected.last_created_member
    assert member is not None and member.token is not None
    other = TautClient(db_path=db, as_name="other")
    other.join("general")
    outsider = TautClient(db_path=db, as_name="outsider")
    outsider.join("general")
    selected.close()
    outsider.close()
    inaccessible = other.say("@outsider", "not selected").thread
    other.close()

    async def scenario() -> None:
        reactor = ProcessReactor(asyncio.get_running_loop())
        try:
            canonical = str(
                (
                    await reactor.attach_workspace(
                        str(workspace),
                        member.token or "",
                    )
                )["workspace"]
            )
            for tool in ("read", "log"):
                encoded_results: list[str] = []
                for selector in ("@missing", inaccessible):
                    result = await reactor._execute_ready_tool(
                        canonical,
                        tool,
                        {
                            "thread": selector,
                            "limit": 100,
                            **({"since": None} if tool == "log" else {}),
                        },
                    )
                    _assert_result(
                        result,
                        record_type="message",
                        workspace=canonical,
                    )
                    assert result["records"] == []
                    encoded_results.append(
                        json.dumps(
                            result,
                            ensure_ascii=False,
                            sort_keys=True,
                            separators=(",", ":"),
                        )
                    )
                assert encoded_results[0] == encoded_results[1]
        finally:
            await reactor.aclose()

    asyncio.run(scenario())


@pytest.mark.sqlite_only
@pytest.mark.timeout(30)
def test_search_returns_all_facets_and_preserves_authoritative_state(
    tmp_path: Path,
) -> None:
    """[MCP-5]/[SRCH-5.4] Real SQLite search is exact and state-neutral."""

    workspace, token = _workspace_with_two_members(tmp_path)
    db = workspace / ".taut.db"
    selected = TautClient(db_path=db, token=token)
    identity_record = selected.whoami(explain=False)
    channel = selected.say("general", "verticalneedle channel")
    parent = selected.say("general", "parent without marker")
    subthread = selected.reply(
        "general",
        str(parent.ts),
        "verticalneedle subthread",
    )
    direct = selected.say("@other", "verticalneedle direct")
    selected.close()

    observer = TautClient(db_path=db, token=token)

    def snapshot() -> tuple[object, object, object]:
        return (
            observer._state.get_member(identity_record.member_id),
            observer._state.list_memberships(identity_record.member_id),
            observer.peek_inbox(limit=1000),
        )

    async def scenario() -> None:
        reactor = ProcessReactor(asyncio.get_running_loop())
        try:
            canonical = str(
                (await reactor.attach_workspace(str(workspace), token))["workspace"]
            )
            before = snapshot()
            arguments = {
                "query": "verticalneedle",
                "channels": ["general"],
                "direct_messages": [direct.thread],
                "all_direct_messages": False,
                "from_member": "selected",
                "kinds": ["message"],
                "before": None,
                "limit": 50,
                "reindex": False,
            }
            result = await reactor._execute_ready_tool(
                canonical,
                "search",
                arguments,
            )
            _assert_result(result, record_type="search_hit", workspace=canonical)
            assert {record["text"] for record in result["records"]} == {
                "verticalneedle channel",
                "verticalneedle subthread",
                "verticalneedle direct",
            }
            by_text = {record["text"]: record for record in result["records"]}
            assert by_text["verticalneedle channel"]["thread_kind"] == "channel"
            assert by_text["verticalneedle channel"]["channel"] == "general"
            assert by_text["verticalneedle channel"]["parent"] is None
            assert by_text["verticalneedle channel"]["members"] is None
            assert by_text["verticalneedle subthread"]["thread_kind"] == "subthread"
            assert by_text["verticalneedle subthread"]["channel"] == "general"
            assert by_text["verticalneedle subthread"]["parent"] == "general"
            assert by_text["verticalneedle subthread"]["members"] is None
            assert by_text["verticalneedle direct"]["thread_kind"] == "dm"
            assert by_text["verticalneedle direct"]["channel"] is None
            assert by_text["verticalneedle direct"]["parent"] is None
            assert len(by_text["verticalneedle direct"]["members"]) == 2
            assert all(
                isinstance(record["ts"], str) and len(record["ts"]) == 19
                for record in result["records"]
            )
            assert {record["ts"] for record in result["records"]} == {
                str(channel.ts),
                str(subthread.ts),
                str(direct.ts),
            }

            rebuilt = await reactor._execute_ready_tool(
                canonical,
                "search",
                {**arguments, "reindex": True},
            )
            assert rebuilt["records"] == result["records"]

            empty = await reactor._execute_ready_tool(
                canonical,
                "search",
                {**arguments, "query": "absentverticalneedle"},
            )
            _assert_result(empty, record_type="search_hit", workspace=canonical)
            assert empty["records"] == []
            assert snapshot() == before
        finally:
            observer.close()
            await reactor.aclose()

    asyncio.run(scenario())


@pytest.mark.sqlite_only
@pytest.mark.timeout(15)
def test_search_provider_failure_is_sanitized_without_retiring_workspace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """[MCP-6] Backend detail is hidden and the child remains usable."""

    workspace, token = _workspace_with_two_members(tmp_path)

    def unavailable(self: TautClient, query: str, **kwargs: object) -> list[SearchHit]:
        raise RuntimeError("sqlite index path and secret provider detail")

    monkeypatch.setattr(workspace_reactor.TautClient, "search", unavailable)

    async def scenario() -> None:
        reactor = ProcessReactor(asyncio.get_running_loop())
        try:
            canonical = str(
                (await reactor.attach_workspace(str(workspace), token))["workspace"]
            )
            with _tool_error(
                "search provider or index unavailable; fix the workspace "
                "search provider or index and retry"
            ):
                await reactor._execute_ready_tool(
                    canonical,
                    "search",
                    {"query": "needle"},
                )
            identity_result = await reactor._execute_ready_tool(
                canonical,
                "whoami",
                {},
            )
            assert identity_result["records"][0]["name"] == "selected"
            assert reactor.list_workspaces()["records"][0]["status"] == "ready"
        finally:
            await reactor.aclose()

    asyncio.run(scenario())


@pytest.mark.sqlite_only
@pytest.mark.timeout(15)
def test_late_search_cancellation_does_not_retry_or_retire_workspace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """[MCP-5] Cancellation discards delivery, not the single core operation."""

    workspace, token = _workspace_with_two_members(tmp_path)
    source = TautClient(db_path=workspace / ".taut.db", token=token)
    source.say("general", "cancel search needle")
    source.close()
    started = threading.Event()
    release = threading.Event()
    calls = 0
    real_execute = workspace_reactor.execute_command

    def delayed_execute(client: TautClient, name: str, arguments: Any) -> Any:
        nonlocal calls
        if name == "search":
            calls += 1
            started.set()
            if not release.wait(timeout=5):
                raise AssertionError("test did not release search")
        return real_execute(client, name, arguments)

    monkeypatch.setattr(workspace_reactor, "execute_command", delayed_execute)

    async def scenario() -> None:
        reactor = ProcessReactor(asyncio.get_running_loop())
        try:
            canonical = str(
                (await reactor.attach_workspace(str(workspace), token))["workspace"]
            )
            pending = asyncio.create_task(
                reactor._execute_ready_tool(
                    canonical,
                    "search",
                    {"query": "needle", "channels": ["general"]},
                )
            )
            assert await asyncio.to_thread(started.wait, 5)
            pending.cancel()
            with pytest.raises(asyncio.CancelledError):
                await pending
            release.set()
            await _wait_until(
                lambda: reactor._entries[canonical].active_command_id is None
            )
            assert calls == 1
            identity_result = await reactor._execute_ready_tool(
                canonical,
                "whoami",
                {},
            )
            assert identity_result["records"][0]["name"] == "selected"
        finally:
            release.set()
            await reactor.aclose()

    asyncio.run(scenario())


@pytest.mark.sqlite_only
@pytest.mark.timeout(120)
def test_explicit_read_limit_pages_without_post_read_slicing(tmp_path: Path) -> None:
    """[MCP-5]/[MCP-12] The bound reaches core before cursor movement."""

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    db = workspace / ".taut.db"
    TautClient.init(db_path=db)
    selected = TautClient(db_path=db, as_name="selected")
    selected.join("general")
    member = selected.last_created_member
    assert member is not None
    assert member.token is not None
    other = TautClient(db_path=db, as_name="other")
    other.join("general")
    selected.read("general", limit=1000)
    expected: list[str] = []
    for index in range(250):
        text = f"page-{index:03d}"
        expected.append(text)
        other.say("general", text)
    selected.close()
    other.close()

    async def scenario() -> None:
        reactor = ProcessReactor(asyncio.get_running_loop())
        try:
            canonical = str(
                (
                    await reactor.attach_workspace(
                        str(workspace),
                        member.token or "",
                    )
                )["workspace"]
            )
            first = await reactor._execute_ready_tool(
                canonical,
                "read",
                {"thread": "general"},
            )
            second = await reactor._execute_ready_tool(
                canonical,
                "read",
                {"thread": "general", "limit": 100},
            )
            third = await reactor._execute_ready_tool(
                canonical,
                "read",
                {"thread": "general", "limit": 1000},
            )
            combined = [
                record["text"]
                for payload in (first, second, third)
                for record in payload["records"]
            ]
            assert [
                len(first["records"]),
                len(second["records"]),
                len(third["records"]),
            ] == [100, 100, 50]
            assert combined == expected
            empty = await reactor._execute_ready_tool(
                canonical,
                "read",
                {"thread": "general", "limit": 100},
            )
            assert empty["empty"] is True
            assert empty["guidance"] == []
            history = await reactor._execute_ready_tool(
                canonical,
                "log",
                {"thread": "general", "since": None, "limit": 1000},
            )
            assert {record["text"] for record in history["records"]} >= set(expected)
        finally:
            await reactor.aclose()

    asyncio.run(scenario())


@pytest.mark.sqlite_only
@pytest.mark.timeout(15)
@pytest.mark.parametrize(
    ("tool", "arguments"),
    [
        ("list", {"all": True}),
        ("who", {"thread": None}),
        ("whoami", {}),
    ],
)
def test_activity_writing_tools_do_not_change_bound_identity_or_presence(
    tmp_path: Path,
    tool: str,
    arguments: dict[str, object],
) -> None:
    """[MCP-5]/[MCP-12] Activity writes do not heal MCP identity."""

    workspace, token = _workspace_with_two_members(tmp_path)

    async def scenario() -> None:
        reactor = ProcessReactor(asyncio.get_running_loop())
        observer = TautClient(db_path=workspace / ".taut.db")

        def snapshot() -> tuple[int, tuple[object, ...]]:
            row = observer._state.get_member_by_token(token)
            assert row is not None
            stable = (
                row["host_id"],
                row["host_label"],
                row["anchor_pid"],
                row["anchor_start_time"],
                row["fingerprint"],
                identity.member_presence(
                    row,
                    identity.capture_host_identity().host_id,
                ),
            )
            return row["last_active_ts"], stable

        try:
            canonical = str(
                (await reactor.attach_workspace(str(workspace), token))["workspace"]
            )
            before_activity, before_identity = snapshot()
            result = await reactor._execute_ready_tool(canonical, tool, arguments)
            assert result["record_type"] in {"thread", "member"}
            after_activity, after_identity = snapshot()
            assert after_activity > before_activity
            assert after_identity == before_identity
        finally:
            observer.close()
            await reactor.aclose()

    asyncio.run(scenario())


def test_every_tool_declares_a_closed_common_output_schema() -> None:
    """[MCP-6] Structured results are declared before any tool is callable."""

    expected_record_types = {
        "attach_workspace": "workspace",
        "detach_workspace": "workspace",
        "list_workspaces": "workspace",
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
    assert {tool.name for tool in TOOLS} == set(expected_record_types)
    for tool in TOOLS:
        schema = tool.output_schema
        assert schema is not None
        assert schema["additionalProperties"] is False
        assert (
            schema["properties"]["record_type"]["const"]
            == expected_record_types[tool.name]
        )
        assert schema["properties"]["record_type"]["type"] == "string"
        record_schema = schema["properties"]["records"]["items"]
        if "oneOf" in record_schema:
            assert all(
                branch["additionalProperties"] is False
                for branch in record_schema["oneOf"]
            )
        else:
            assert record_schema["additionalProperties"] is False

    deletion_schema = next(
        tool.output_schema for tool in TOOLS if tool.name == "message_delete"
    )
    assert deletion_schema is not None
    assert deletion_schema["properties"]["records"]["items"] == {
        "additionalProperties": False,
        "properties": {
            "deleted": {
                "const": True,
                "description": "True for a successful physical deletion.",
            },
            "thread": {
                "description": "Taut thread from which the message was deleted.",
                "type": "string",
            },
            "ts": {
                "description": "Deleted Taut message timestamp/id.",
                "pattern": r"^[0-9]{19}$",
                "type": "string",
            },
        },
        "required": ["thread", "ts", "deleted"],
        "type": "object",
    }
    reaction_schema = next(
        tool.output_schema for tool in TOOLS if tool.name == "message_react"
    )
    assert reaction_schema is not None
    assert reaction_schema["properties"]["records"]["items"] == {
        "additionalProperties": False,
        "properties": {
            "audience_count": {
                "description": (
                    "Current authorized non-actor recipient count; not a "
                    "delivery or consumption receipt."
                ),
                "minimum": 1,
                "type": "integer",
            },
            "message_ts": {
                "description": "Reacted-to Taut message timestamp/id.",
                "pattern": r"^[0-9]{19}$",
                "type": "string",
            },
            "reaction": {
                "description": "Configured reaction slug sent by the actor.",
                "type": "string",
            },
            "thread": {
                "description": "Exact Taut thread containing the source message.",
                "type": "string",
            },
        },
        "required": ["thread", "message_ts", "reaction", "audience_count"],
        "type": "object",
    }
    notification_schema = next(
        tool.output_schema for tool in TOOLS if tool.name == "inbox"
    )
    assert notification_schema is not None
    assert notification_schema["properties"]["records"]["items"]["properties"][
        "reaction"
    ] == {
        "description": "Reaction slug for a reaction notification.",
        "type": "string",
    }


def test_output_schemas_require_canonical_string_timestamps() -> None:
    schemas = {
        tool.name: tool.output_schema["properties"]["records"]["items"]
        for tool in TOOLS
        if tool.output_schema is not None
    }
    canonical = {"pattern": r"^[0-9]{19}$", "type": "string"}

    for tool_name, field in (
        ("say", "ts"),
        ("message_delete", "ts"),
        ("message_react", "message_ts"),
        ("who", "last_active_ts"),
    ):
        field_schema = schemas[tool_name]["properties"][field]
        assert field_schema["pattern"] == canonical["pattern"]
        assert field_schema["type"] == canonical["type"]

    search_schema = schemas["search"]
    assert all(
        branch["properties"]["ts"]["pattern"] == canonical["pattern"]
        and branch["properties"]["ts"]["type"] == canonical["type"]
        for branch in search_schema["oneOf"]
    )

    for tool_name, field in (
        ("inbox", "message_ts"),
        ("channel_show", "topic_updated_ts"),
    ):
        assert schemas[tool_name]["properties"][field]["anyOf"] == [
            canonical,
            {"type": "null"},
        ]

    thread_schema = schemas["list"]
    assert all(
        branch["properties"]["last_ts"]["anyOf"] == [canonical, {"type": "null"}]
        for branch in thread_schema["oneOf"]
    )


@pytest.mark.parametrize(
    "invalid",
    [
        "123456789012345678",
        "12345678901234567890",
        " 1234567890123456789",
        "+1234567890123456789",
        1_234_567_890_123_456_789,
        True,
        None,
    ],
)
@pytest.mark.parametrize(
    "tool_name", ["message_show", "message_delete", "message_react"]
)
def test_exact_message_tool_schemas_reject_non_exact_string_ids(
    tool_name: str,
    invalid: object,
) -> None:
    tool = next(tool for tool in TOOLS if tool.name == tool_name)

    with pytest.raises(ValidationError):
        validate(
            instance={
                "workspace": "/workspace",
                "token": "secret",
                "msg_id": invalid,
                **({"reaction": "ack"} if tool_name == "message_react" else {}),
            },
            schema=tool.input_schema,
        )


@pytest.mark.parametrize("tool_name", ["message_show", "message_delete"])
def test_exact_message_tool_manifest_contract(tool_name: str) -> None:
    tool = next(tool for tool in TOOLS if tool.name == tool_name)

    assert tool.input_schema["required"] == ["workspace", "token", "msg_id"]
    assert tool.input_schema["properties"]["msg_id"] == {
        "description": (
            "Exact native Taut message id as a 19-digit decimal string. "
            "Preserve it as text; suffixes, whitespace, signs, and numeric JSON "
            "values are invalid."
        ),
        "pattern": r"^[0-9]{19}$",
        "type": "string",
    }
    assert tool.annotations is not None
    assert tool.annotations.model_dump(
        mode="json",
        exclude_none=True,
        by_alias=True,
    ) == {
        "destructiveHint": True,
        "idempotentHint": False,
        "openWorldHint": True,
        "readOnlyHint": False,
    }


@pytest.mark.parametrize(
    "invalid",
    [
        "",
        "-ack",
        "Ack",
        "ack!",
        "a" * 33,
        1,
        True,
        None,
    ],
)
def test_react_to_message_schema_rejects_malformed_reaction_slugs(
    invalid: object,
) -> None:
    tool = next(tool for tool in TOOLS if tool.name == "message_react")

    with pytest.raises(ValidationError):
        validate(
            instance={
                "workspace": "/workspace",
                "token": "secret",
                "msg_id": "1234567890123456789",
                "reaction": invalid,
            },
            schema=tool.input_schema,
        )


def test_react_to_message_manifest_contract_has_no_static_enum() -> None:
    tool = next(tool for tool in TOOLS if tool.name == "message_react")

    assert tool.description == (
        "Send one configured reaction to the current audience of an exact "
        "ordinary message, excluding this member. Validates against the "
        "workspace's attachment-time reaction vocabulary, advances this "
        "member's high-water cursor through the target, then attempts one "
        "atomic best-effort notification broadcast to every requested inbox. "
        "Repeating may deliver duplicates."
    )
    assert tool.input_schema["required"] == [
        "workspace",
        "token",
        "msg_id",
        "reaction",
    ]
    assert tool.input_schema["properties"]["reaction"] == {
        "description": (
            "Configured lowercase ASCII reaction slug matching "
            "^[a-z0-9][a-z0-9_-]{0,31}$. Used only by message_react; the "
            "schema is not an enum because the attached workspace config "
            "remains authoritative."
        ),
        "pattern": r"^[a-z0-9][a-z0-9_-]{0,31}$",
        "type": "string",
    }
    assert "enum" not in tool.input_schema["properties"]["reaction"]
    assert tool.annotations is not None
    assert tool.annotations.model_dump(
        mode="json",
        exclude_none=True,
        by_alias=True,
    ) == {
        "destructiveHint": True,
        "idempotentHint": False,
        "openWorldHint": True,
        "readOnlyHint": False,
    }


def test_search_manifest_and_result_family_are_exact() -> None:
    """[MCP-5]/[MCP-6] Search is explicit, closed, and truthful."""

    tool = next(tool for tool in TOOLS if tool.name == "search")

    assert tool.description == (
        "Search actor-visible Taut history without moving chat cursors, "
        "claiming notifications, or touching member activity. The call may "
        "reconcile disposable derived index state; reindex=true rebuilds it. "
        "Backend tokenization and ranking may differ."
    )
    assert tool.input_schema["required"] == ["workspace", "token", "query"]
    assert set(tool.input_schema["properties"]) == {
        "workspace",
        "token",
        "query",
        "channels",
        "direct_messages",
        "all_direct_messages",
        "from_member",
        "kinds",
        "before",
        "limit",
        "reindex",
    }
    assert tool.input_schema["properties"]["channels"]["items"]["pattern"] == (
        r"^[a-z0-9][a-z0-9_-]{0,63}$"
    )
    assert (
        tool.input_schema["properties"]["direct_messages"]["items"]["pattern"]
        == r"^(?:@[A-Za-z0-9][A-Za-z0-9_-]{0,63}|dm\.d_[a-z2-7]{26})$"
    )
    assert tool.input_schema["properties"]["kinds"]["items"]["enum"] == [
        "message",
        "notice",
        "foreign",
    ]
    for name in ("channels", "direct_messages", "kinds"):
        assert tool.input_schema["properties"][name]["default"] == []
        assert "uniqueItems" not in tool.input_schema["properties"][name]
    assert tool.input_schema["properties"]["before"]["anyOf"] == [
        {"pattern": r"^[0-9]{19}$", "type": "string"},
        {"type": "null"},
    ]
    assert tool.input_schema["properties"]["limit"] == {
        "default": 50,
        "description": (
            "Maximum records requested from one queue, from 1 through 1,000 "
            "inclusive. Defaults to 50."
        ),
        "maximum": 1000,
        "minimum": 1,
        "type": "integer",
    }
    assert tool.annotations is not None
    assert tool.annotations.model_dump(
        mode="json",
        exclude_none=True,
        by_alias=True,
    ) == {
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
        "readOnlyHint": False,
    }

    assert tool.output_schema is not None
    assert tool.output_schema["properties"]["record_type"]["const"] == "search_hit"
    branches = tool.output_schema["properties"]["records"]["items"]["oneOf"]
    assert [branch["properties"]["thread_kind"]["const"] for branch in branches] == [
        "channel",
        "subthread",
        "dm",
    ]
    expected_fields = {
        "thread",
        "ts",
        "from_id",
        "from",
        "kind",
        "text",
        "thread_kind",
        "channel",
        "parent",
        "members",
    }
    for branch in branches:
        assert branch["additionalProperties"] is False
        assert set(branch["properties"]) == expected_fields
        assert set(branch["required"]) == expected_fields
        assert branch["properties"]["ts"]["pattern"] == r"^[0-9]{19}$"
        assert branch["properties"]["kind"]["enum"] == [
            "message",
            "notice",
            "foreign",
        ]

    channel, subthread, dm = branches
    assert channel["properties"]["channel"]["type"] == "string"
    assert channel["properties"]["parent"]["type"] == "null"
    assert channel["properties"]["members"]["type"] == "null"
    assert subthread["properties"]["channel"]["type"] == "string"
    assert subthread["properties"]["parent"]["type"] == "string"
    assert subthread["properties"]["members"]["type"] == "null"
    assert dm["properties"]["channel"]["type"] == "null"
    assert dm["properties"]["parent"]["type"] == "null"
    assert dm["properties"]["members"]["minItems"] == 2
    assert dm["properties"]["members"]["maxItems"] == 2


def test_search_schema_accepts_defaults_nulls_and_duplicate_filters() -> None:
    tool = next(tool for tool in TOOLS if tool.name == "search")

    validate(
        instance={"workspace": "/workspace", "token": "secret", "query": "x"},
        schema=tool.input_schema,
    )
    validate(
        instance={
            "workspace": "/workspace",
            "token": "secret",
            "query": "parser",
            "channels": ["general", "general"],
            "direct_messages": ["@Ada", "@Ada"],
            "all_direct_messages": True,
            "from_member": None,
            "kinds": ["message", "message"],
            "before": None,
            "limit": 1000,
            "reindex": True,
        },
        schema=tool.input_schema,
    )


@pytest.mark.parametrize(
    "arguments",
    [
        {"workspace": "/workspace", "token": "secret"},
        {"workspace": "/workspace", "token": "secret", "query": ""},
        {"workspace": "/workspace", "token": "secret", "query": "x", "extra": 1},
        {
            "workspace": "/workspace",
            "token": "secret",
            "query": "x",
            "channels": "general",
        },
        {
            "workspace": "/workspace",
            "token": "secret",
            "query": "x",
            "channels": ["General"],
        },
        {
            "workspace": "/workspace",
            "token": "secret",
            "query": "x",
            "direct_messages": ["general"],
        },
        {
            "workspace": "/workspace",
            "token": "secret",
            "query": "x",
            "kinds": ["event"],
        },
        {
            "workspace": "/workspace",
            "token": "secret",
            "query": "x",
            "before": 1_234_567_890_123_456_789,
        },
        {"workspace": "/workspace", "token": "secret", "query": "x", "before": "1234"},
        {"workspace": "/workspace", "token": "secret", "query": "x", "limit": 0},
        {"workspace": "/workspace", "token": "secret", "query": "x", "limit": 1001},
        {"workspace": "/workspace", "token": "secret", "query": "x", "reindex": 1},
    ],
)
def test_search_schema_rejects_malformed_calls(arguments: dict[str, object]) -> None:
    tool = next(tool for tool in TOOLS if tool.name == "search")

    with pytest.raises(ValidationError):
        validate(instance=arguments, schema=tool.input_schema)


def test_exact_tool_manifest_snapshot() -> None:
    """[MCP-5]/[MCP-12] Pin every agent-facing manifest contract field."""

    snapshot = [
        {
            "annotations": (
                tool.annotations.model_dump(
                    mode="json",
                    exclude_none=True,
                    by_alias=True,
                )
                if tool.annotations is not None
                else None
            ),
            "description": tool.description,
            "inputSchema": tool.input_schema,
            "name": tool.name,
            "outputSchema": tool.output_schema,
        }
        for tool in TOOLS
    ]
    encoded = json.dumps(
        snapshot,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    assert hashlib.sha256(encoded).hexdigest() == (
        "60e4d48d629cc5628c1624603fb839a45ed64d65236aa0a170308cb4e4533500"
    )

    def assert_property_descriptions(schema: dict[str, object]) -> None:
        properties = schema.get("properties", {})
        assert isinstance(properties, dict)
        for property_schema in properties.values():
            assert isinstance(property_schema, dict)
            assert property_schema.get("description")
            assert_property_descriptions(property_schema)
            items = property_schema.get("items")
            if isinstance(items, dict):
                assert_property_descriptions(items)

    for tool in TOOLS:
        assert tool.description
        assert_property_descriptions(tool.input_schema)
        assert tool.output_schema is not None
        assert_property_descriptions(tool.output_schema)


def test_unknown_tool_is_not_an_ordinary_tool_result() -> None:
    """[MCP-6] Unknown names stay JSON-RPC errors, never `isError` content."""

    async def scenario() -> None:
        from mcp.client import Client
        from mcp.shared.exceptions import MCPError

        from taut_mcp.server import create_server

        server, _ = create_server()
        async with Client(server, mode="2026-07-28") as client:
            with pytest.raises(MCPError):
                await client.call_tool("not_a_tool", {})

    asyncio.run(scenario())
