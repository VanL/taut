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
from jsonschema import validate
from simplebroker import BrokerTarget

import taut.identity as identity
import taut_mcp._workspace_reactor as workspace_reactor
from taut import TautClient
from taut_mcp._commands import RECORD_TYPE_BY_TOOL, execute_command
from taut_mcp._connection_reactor import ConnectionReactor, WorkspaceToolError
from taut_mcp._tools import TOOLS

READ_GUIDANCE = [
    {
        "action": (
            "Use log for non-consuming channel or sub-thread rereads. Direct "
            "messages have no public log operation."
        ),
        "code": "read_cursor_advanced",
        "message": (
            "Read cursors advanced through the returned records; no message "
            "history was deleted."
        ),
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
        tool.outputSchema
        for tool in TOOLS
        if tool.outputSchema is not None
        and tool.outputSchema["properties"]["record_type"].get("const") == record_type
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
            "list",
            {"all": True},
            "list_threads",
            (),
            {"all_threads": True},
        ),
        (
            "rename",
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
    iterable_methods = {"read", "inbox", "log", "list_threads", "who"}

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


@pytest.mark.sqlite_only
@pytest.mark.timeout(15)
def test_all_cli_shaped_tools_dispatch_on_the_workspace_owner_thread(
    tmp_path: Path,
) -> None:
    """[MCP-5]/[MCP-6] Every explicit ordinary tool has a real firing case."""

    workspace, token = _workspace_with_two_members(tmp_path)

    async def scenario() -> None:
        reactor = ConnectionReactor(asyncio.get_running_loop())
        try:
            attached = await reactor.attach_workspace(str(workspace), token)
            canonical = str(attached["workspace"])

            joined = await reactor.execute_tool(
                canonical,
                "join",
                {"thread": "work", "persona": "reviewer"},
            )
            _assert_result(joined, record_type="message", workspace=canonical)
            assert joined["records"][0]["thread"] == "work"
            assert joined["records"][0]["kind"] == "notice"

            left = await reactor.execute_tool(
                canonical,
                "leave",
                {"thread": "work"},
            )
            _assert_result(left, record_type="message", workspace=canonical)
            assert left["records"][0]["text"] == "selected left"

            named = await reactor.execute_tool(
                canonical,
                "set_name",
                {"name": "renamed"},
            )
            _assert_result(named, record_type="member", workspace=canonical)
            assert named["records"][0]["name"] == "renamed"
            assert "token" not in named["records"][0]

            said = await reactor.execute_tool(
                canonical,
                "say",
                {"target": "general", "text": "top level"},
            )
            _assert_result(said, record_type="message", workspace=canonical)
            parent_ts = said["records"][0]["ts"]

            replied = await reactor.execute_tool(
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

            unread = await reactor.execute_tool(
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
            assert unread["records"][0]["text"] == "other joined"

            inbox = await reactor.execute_tool(
                canonical,
                "inbox",
                {"limit": 1000},
            )
            _assert_result(inbox, record_type="notification", workspace=canonical)
            assert inbox["records"][0]["type"] == "mention"
            assert inbox["records"][0]["matched"] == "@selected"

            history = await reactor.execute_tool(
                canonical,
                "log",
                {"thread": "general", "since": None, "limit": 1},
            )
            _assert_result(history, record_type="message", workspace=canonical)
            assert len(history["records"]) == 1

            listed = await reactor.execute_tool(
                canonical,
                "list",
                {"all": True},
            )
            _assert_result(listed, record_type="thread", workspace=canonical)
            assert {record["thread"] for record in listed["records"]} >= {
                "general",
                f"general.{parent_ts}",
            }

            renamed = await reactor.execute_tool(
                canonical,
                "rename",
                {"old_name": "general", "new_name": "main"},
            )
            _assert_result(renamed, record_type="thread", workspace=canonical)
            assert renamed["records"][0]["thread"] == "main"

            members = await reactor.execute_tool(
                canonical,
                "who",
                {"thread": "main"},
            )
            _assert_result(members, record_type="member", workspace=canonical)
            assert {record["name"] for record in members["records"]} == {
                "other",
                "renamed",
            }

            identity = await reactor.execute_tool(
                canonical,
                "whoami",
                {},
            )
            _assert_result(identity, record_type="member", workspace=canonical)
            assert identity["records"][0]["name"] == "renamed"
            assert "token" not in identity["records"][0]

            empty = await reactor.execute_tool(
                canonical,
                "log",
                {"thread": "missing", "since": None, "limit": 100},
            )
            _assert_result(empty, record_type="message", workspace=canonical)
            assert empty["records"] == []

            with _tool_error("dm is reserved"):
                await reactor.execute_tool(
                    canonical,
                    "join",
                    {"thread": "dm", "persona": None},
                )
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
        reactor = ConnectionReactor(asyncio.get_running_loop())
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
            blocked = asyncio.create_task(reactor.execute_tool(slow, "whoami", {}))
            assert await asyncio.to_thread(started.wait, 5)

            with _tool_error("workspace busy; retry after backoff"):
                await reactor.execute_tool(slow, "who", {"thread": None})
            with _tool_error("workspace busy; retry after backoff"):
                await reactor.detach_workspace(slow)

            independent = await asyncio.wait_for(
                reactor.execute_tool(fast, "whoami", {}),
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
        reactor = ConnectionReactor(asyncio.get_running_loop())
        try:
            canonical = str(
                (await reactor.attach_workspace(str(workspace), token))["workspace"]
            )
            assert await asyncio.to_thread(blocked_peek.wait, 5)
            canceled = asyncio.create_task(
                reactor.execute_tool(
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
            identity = await reactor.execute_tool(canonical, "whoami", {})
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
        reactor = ConnectionReactor(asyncio.get_running_loop())
        try:
            canonical = str(
                (await reactor.attach_workspace(str(workspace), token))["workspace"]
            )
            canceled = asyncio.create_task(
                reactor.execute_tool(
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
            identity = await reactor.execute_tool(canonical, "whoami", {})
            assert identity["records"][0]["name"] == "selected"
        finally:
            release.set()
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
        reactor = ConnectionReactor(asyncio.get_running_loop())
        try:
            canonical = str(
                (await reactor.attach_workspace(str(workspace), token))["workspace"]
            )
            command = asyncio.create_task(reactor.execute_tool(canonical, "whoami", {}))
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
        reactor = ConnectionReactor(asyncio.get_running_loop())
        try:
            canonical = str(
                (
                    await reactor.attach_workspace(
                        str(workspace),
                        member.token or "",
                    )
                )["workspace"]
            )
            first = await reactor.execute_tool(
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

            second = await reactor.execute_tool(
                canonical,
                "read",
                {"thread": None, "limit": 1},
            )
            assert len(second["records"]) <= 2
            assert len({record["thread"] for record in second["records"]}) == len(
                second["records"]
            )

            history = await reactor.execute_tool(
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
        reactor = ConnectionReactor(asyncio.get_running_loop())
        try:
            canonical = str(
                (
                    await reactor.attach_workspace(
                        str(workspace),
                        member.token or "",
                    )
                )["workspace"]
            )
            first = await reactor.execute_tool(
                canonical,
                "read",
                {"thread": "general"},
            )
            second = await reactor.execute_tool(
                canonical,
                "read",
                {"thread": "general", "limit": 100},
            )
            third = await reactor.execute_tool(
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
            empty = await reactor.execute_tool(
                canonical,
                "read",
                {"thread": "general", "limit": 100},
            )
            assert empty["empty"] is True
            assert empty["guidance"] == []
            history = await reactor.execute_tool(
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
        reactor = ConnectionReactor(asyncio.get_running_loop())
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
            result = await reactor.execute_tool(canonical, tool, arguments)
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
        "read": "message",
        "inbox": "notification",
        "log": "message",
        "list": "thread",
        "rename": "thread",
        "who": "member",
        "whoami": "member",
    }
    assert {tool.name for tool in TOOLS} == set(expected_record_types)
    for tool in TOOLS:
        schema = tool.outputSchema
        assert schema is not None
        assert schema["additionalProperties"] is False
        assert (
            schema["properties"]["record_type"]["const"]
            == expected_record_types[tool.name]
        )
        assert schema["properties"]["record_type"]["type"] == "string"
        assert schema["properties"]["records"]["items"]["additionalProperties"] is False


def test_exact_tool_manifest_snapshot() -> None:
    """[MCP-5]/[MCP-12] Pin every agent-facing manifest contract field."""

    snapshot = [
        {
            "annotations": (
                tool.annotations.model_dump(mode="json", exclude_none=True)
                if tool.annotations is not None
                else None
            ),
            "description": tool.description,
            "inputSchema": tool.inputSchema,
            "name": tool.name,
            "outputSchema": tool.outputSchema,
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
        "98763d26f8a42d7ae65b8b96c1f8b554f90a9e5f6a84f3336061cdee438faa12"
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
        assert_property_descriptions(tool.inputSchema)
        assert tool.outputSchema is not None
        assert_property_descriptions(tool.outputSchema)


def test_unknown_tool_is_not_an_ordinary_tool_result() -> None:
    """[MCP-6] Unknown names stay JSON-RPC errors, never `isError` content."""

    async def scenario() -> None:
        from mcp import types
        from mcp.shared.exceptions import McpError

        from taut_mcp.server import create_server

        server, _ = create_server()
        handler = server.request_handlers[types.CallToolRequest]
        request = types.CallToolRequest(
            params=types.CallToolRequestParams(name="not_a_tool", arguments={})
        )
        with pytest.raises(McpError):
            await handler(request)

    asyncio.run(scenario())
