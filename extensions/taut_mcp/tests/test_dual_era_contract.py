from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

import taut_mcp._process_reactor as process_reactor
from taut import TautClient
from taut_mcp._process_reactor import ProcessReactor
from taut_mcp._tools import TOOLS, ToolValidationError, validate_tool_call
from taut_mcp._workspace_reactor import RunWorkspaceCommand, WorkspaceControl

DOMAIN_TOOL_NAMES = {
    "channel_rename",
    "channel_show",
    "channel_topic",
    "inbox",
    "join",
    "leave",
    "list",
    "log",
    "message_delete",
    "message_react",
    "message_show",
    "read",
    "reply",
    "say",
    "set_name",
    "who",
    "whoami",
}


def _workspace(tmp_path: Path) -> tuple[Path, str]:
    workspace = tmp_path / "selected"
    workspace.mkdir()
    database = workspace / ".taut.db"
    TautClient.init(db_path=database)
    client = TautClient(db_path=database, as_name="selected")
    client.join("general")
    member = client.last_created_member
    assert member is not None
    assert member.token is not None
    client.close()
    return workspace, member.token


DOMAIN_TOOL_ARGUMENTS: dict[str, dict[str, object]] = {
    "channel_rename": {"old_name": "general", "new_name": "main"},
    "channel_show": {"channel": "general"},
    "channel_topic": {"channel": "general", "topic": "lazy topic"},
    "inbox": {"limit": 1},
    "join": {"thread": "work", "persona": None},
    "leave": {"thread": "general"},
    "list": {"all": False, "dms": False},
    "log": {"thread": "general", "since": None, "limit": 1},
    "message_delete": {},
    "message_react": {"reaction": "ack"},
    "message_show": {},
    "read": {"thread": "general", "limit": 1},
    "reply": {"thread": "general", "text": "lazy reply"},
    "say": {"target": "general", "text": "lazy say"},
    "set_name": {"name": "renamed"},
    "who": {"thread": "general"},
    "whoami": {},
}


def _valid_rate_probe_arguments(
    workspace: str,
    token: str,
) -> dict[str, dict[str, object]]:
    message_id = "1234567890123456789"
    arguments = {
        name: {"workspace": workspace, "token": token, **values}
        for name, values in DOMAIN_TOOL_ARGUMENTS.items()
    }
    for name in {"message_delete", "message_react", "message_show", "reply"}:
        arguments[name]["msg_id"] = message_id
    return {
        "attach_workspace": {"workspace": workspace, "token": token},
        "detach_workspace": {"workspace": workspace},
        "list_workspaces": {},
        **arguments,
    }


def test_target_manifest_requires_identity_handle_on_every_domain_tool() -> None:
    """[MCP-5] One target manifest carries workspace plus token per domain call."""

    schemas = {tool.name: tool.input_schema for tool in TOOLS}
    assert set(schemas) == DOMAIN_TOOL_NAMES | {
        "attach_workspace",
        "detach_workspace",
        "list_workspaces",
    }
    for name in DOMAIN_TOOL_NAMES | {"attach_workspace"}:
        assert {"workspace", "token"} <= set(schemas[name]["required"])
        assert {"workspace", "token"} <= set(schemas[name]["properties"])
    assert schemas["detach_workspace"]["required"] == ["workspace"]
    assert "token" not in schemas["detach_workspace"]["properties"]
    assert schemas["list_workspaces"].get("required", []) == []
    assert schemas["list_workspaces"]["properties"] == {}


def test_application_validator_normalizes_only_omitted_arguments() -> None:
    """[MCP-5] Known-tool schema failures have one application-owned shape."""

    assert validate_tool_call("list_workspaces", None) == {}
    assert validate_tool_call("list_workspaces", {}) == {}
    with pytest.raises(ToolValidationError):
        validate_tool_call("whoami", None)
    with pytest.raises(ToolValidationError):
        validate_tool_call("whoami", {"workspace": "/tmp/example"})
    with pytest.raises(ToolValidationError):
        validate_tool_call(
            "whoami",
            {"workspace": "/tmp/example", "token": "secret", "extra": True},
        )


@pytest.mark.sqlite_only
@pytest.mark.timeout(10)
def test_domain_call_lazily_ensures_and_retains_workspace(tmp_path: Path) -> None:
    """[MCP-4] A self-contained domain call needs no prior attachment."""

    workspace, token = _workspace(tmp_path)

    async def scenario() -> None:
        reactor = ProcessReactor(asyncio.get_running_loop())
        try:
            result = await reactor.execute_tool(
                str(workspace),
                token,
                "whoami",
                {},
            )
            assert result["records"][0]["name"] == "selected"
            listed = reactor.list_workspaces()
            assert listed["records"][0]["workspace"] == result["workspace"]
            repeated = await reactor.execute_tool(
                result["workspace"],
                token,
                "whoami",
                {},
            )
            assert repeated["workspace"] == result["workspace"]
            assert len(reactor.list_workspaces()["records"]) == 1
        finally:
            await reactor.aclose()

    asyncio.run(scenario())


@pytest.mark.timeout(20)
def test_rate_boundary_charges_every_valid_tool_and_no_server_owned_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """[MCP-10]/[MCP-12] One boundary charges all tools and no control path."""

    from mcp import types
    from mcp.client import Client
    from mcp.shared.exceptions import MCPError

    from taut_mcp._process_reactor import RATE_LIMIT_EXCEEDED, WorkspaceToolError
    from taut_mcp.server import NOTIFICATIONS_URI, create_server

    charges: list[None] = []

    def exhausted(_: ProcessReactor) -> None:
        charges.append(None)
        raise WorkspaceToolError(RATE_LIMIT_EXCEEDED)

    monkeypatch.setattr(ProcessReactor, "charge_request", exhausted)
    tool_arguments = _valid_rate_probe_arguments(
        str(tmp_path / "unresolved"),
        "valid-rate-probe-token",
    )
    assert set(tool_arguments) == {tool.name for tool in TOOLS}

    async def scenario() -> None:
        modern_server, _ = create_server()
        async with Client(modern_server, mode="2026-07-28") as modern:
            await modern.list_tools()
            await modern.list_resources()
            async with modern.listen(resource_subscriptions=[NOTIFICATIONS_URI]):
                pass
            with pytest.raises(MCPError):
                await modern.call_tool("not_a_tool", {})
            invalid = await modern.call_tool(
                "list_workspaces",
                {"unexpected": True},
            )
            assert invalid.is_error is True
            with pytest.raises(MCPError):
                await modern.read_resource("taut://notifications/missing")
            assert charges == []

            for name in sorted(tool_arguments):
                limited = await modern.call_tool(name, tool_arguments[name])
                assert limited.is_error is True
                assert isinstance(limited.content[0], types.TextContent)
                assert limited.content[0].text == RATE_LIMIT_EXCEEDED
            with pytest.raises(MCPError) as resource:
                await modern.read_resource(NOTIFICATIONS_URI)
            assert resource.value.error.code == -31999
            assert len(charges) == len(TOOLS) + 1

        legacy_server, _ = create_server()
        before_legacy = len(charges)
        async with Client(legacy_server, mode="legacy") as legacy:
            await legacy.send_ping()
            await legacy.list_tools()
            await legacy.list_resources()
            await legacy.subscribe_resource(NOTIFICATIONS_URI)
            await legacy.unsubscribe_resource(NOTIFICATIONS_URI)
        assert len(charges) == before_legacy

    asyncio.run(scenario())


@pytest.mark.sqlite_only
@pytest.mark.timeout(10)
def test_domain_command_envelope_excludes_mcp_identity_fields(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """[MCP-4]/[MCP-10] Workspace and raw token stop at shared ensure."""

    workspace, token = _workspace(tmp_path)

    async def scenario() -> None:
        reactor = ProcessReactor(asyncio.get_running_loop())
        try:
            attached = await reactor.attach_workspace(str(workspace), token)
            canonical = str(attached["workspace"])
            commands: list[RunWorkspaceCommand] = []
            real_send = process_reactor._Owner.send

            def audited_send(
                owner: process_reactor._Owner,
                control: WorkspaceControl,
            ) -> None:
                if isinstance(control, RunWorkspaceCommand):
                    commands.append(control)
                real_send(owner, control)

            monkeypatch.setattr(process_reactor._Owner, "send", audited_send)

            def unexpected_owner(_: int) -> process_reactor._Owner:
                raise AssertionError("matching ready binding must not set up an owner")

            monkeypatch.setattr(reactor, "_new_owner", unexpected_owner)
            result = await reactor.execute_tool(
                canonical,
                token,
                "whoami",
                {},
            )
            assert result["records"][0]["name"] == "selected"
            assert len(commands) == 1
            assert dict(commands[0].arguments) == {}
            assert "workspace" not in dict(commands[0].arguments)
            assert "token" not in dict(commands[0].arguments)
        finally:
            await reactor.aclose()

    asyncio.run(scenario())


@pytest.mark.sqlite_only
@pytest.mark.timeout(20)
@pytest.mark.parametrize("tool_name", sorted(DOMAIN_TOOL_ARGUMENTS))
def test_every_domain_tool_can_be_the_first_lazy_request(
    tmp_path: Path,
    tool_name: str,
) -> None:
    """[MCP-4]/[MCP-5] No CLI-shaped tool depends on prior attachment."""

    workspace = tmp_path / tool_name
    workspace.mkdir()
    database = workspace / ".taut.db"
    TautClient.init(db_path=database)
    selected = TautClient(db_path=database, as_name="selected")
    selected.join("general")
    member = selected.last_created_member
    assert member is not None
    assert member.token is not None
    token = member.token
    parent = selected.say("general", "parent")
    assert parent is not None
    parent_id = str(parent.ts)
    selected.close()
    other = TautClient(db_path=database, as_name="other")
    other.join("general")
    other.say("general", "hello @selected")
    other.close()

    arguments = dict(DOMAIN_TOOL_ARGUMENTS[tool_name])
    if tool_name in {"message_delete", "message_react", "message_show"}:
        arguments["msg_id"] = parent_id
    elif tool_name == "reply":
        arguments["msg_id"] = parent_id

    async def scenario() -> None:
        reactor = ProcessReactor(asyncio.get_running_loop())
        try:
            result = await reactor.execute_tool(
                str(workspace),
                token,
                tool_name,
                arguments,
            )
            assert result["record_type"]
            assert result["workspace"] == str(workspace.resolve())
            listed = reactor.list_workspaces()
            assert len(listed["records"]) == 1
            assert listed["records"][0]["status"] == "ready"
        finally:
            await reactor.aclose()

    asyncio.run(scenario())
