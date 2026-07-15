from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

import anyio
import pytest
from mcp import types
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.server.models import InitializationOptions
from mcp.server.session import ServerSession
from mcp.shared.message import SessionMessage

from taut import TautClient
from taut_mcp._claude_channel import (
    CLAUDE_CHANNEL_CUE,
    send_claude_channel,
)
from taut_mcp._connection_reactor import ConnectionReactor
from taut_mcp.server import create_server

EXTENSION_ROOT = Path(__file__).resolve().parents[1]


async def _wait_until(predicate: Any, *, timeout: float = 5.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        if asyncio.get_running_loop().time() >= deadline:
            raise AssertionError("condition did not become true")
        await asyncio.sleep(0.01)


def _workspace(tmp_path: Path) -> tuple[Path, str, TautClient]:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    db = workspace / ".taut.db"
    TautClient.init(db_path=db)
    selected = TautClient(db_path=db, as_name="selected")
    selected.join("general")
    member = selected.last_created_member
    assert member is not None
    assert member.token is not None
    token = member.token
    selected.close()
    other = TautClient(db_path=db, as_name="other")
    other.join("general")
    return workspace, token, other


def test_claude_channel_capability_is_exact_and_opt_in() -> None:
    """[MCP-9] The research-preview capability is never implicit."""

    _, portable = create_server()
    _, enabled = create_server(claude_channel=True)
    assert portable.capabilities.experimental is None
    assert enabled.capabilities.experimental == {"claude/channel": {}}


def test_claude_channel_wire_notification_contains_only_the_fixed_cue() -> None:
    """[MCP-9] No database-derived data enters the custom wake notification."""

    async def scenario() -> None:
        incoming_send, incoming_receive = anyio.create_memory_object_stream[
            SessionMessage | Exception
        ](1)
        outgoing_send, outgoing_receive = anyio.create_memory_object_stream[
            SessionMessage
        ](1)
        options = InitializationOptions(
            server_name="test",
            server_version="0",
            capabilities=types.ServerCapabilities(),
        )
        session = ServerSession(
            incoming_receive,
            outgoing_send,
            options,
            stateless=True,
        )
        try:
            await send_claude_channel(session)
            sent = await outgoing_receive.receive()
            assert sent.message.model_dump(
                mode="json",
                by_alias=True,
                exclude_none=True,
            ) == {
                "jsonrpc": "2.0",
                "method": "notifications/claude/channel",
                "params": {"content": CLAUDE_CHANNEL_CUE},
            }
        finally:
            await incoming_send.aclose()
            await incoming_receive.aclose()
            await outgoing_send.aclose()
            await outgoing_receive.aclose()

    asyncio.run(scenario())


@pytest.mark.sqlite_only
@pytest.mark.timeout(15)
def test_opt_in_stdio_server_advertises_and_emits_claude_channel(
    tmp_path: Path,
) -> None:
    """[MCP-9] The launch flag wires capability and custom event end to end."""

    workspace, token, other = _workspace(tmp_path)

    async def send_message(
        stream: Any,
        message: types.JSONRPCRequest | types.JSONRPCNotification,
    ) -> None:
        await stream.send(SessionMessage(types.JSONRPCMessage(message)))

    async def scenario() -> None:
        parameters = StdioServerParameters(
            command=sys.executable,
            args=["-m", "taut_mcp", "--claude-channel"],
            cwd=EXTENSION_ROOT,
            env=os.environ.copy(),
        )
        async with stdio_client(parameters) as (read_stream, write_stream):
            await send_message(
                write_stream,
                types.JSONRPCRequest(
                    jsonrpc="2.0",
                    id=1,
                    method="initialize",
                    params={
                        "protocolVersion": types.LATEST_PROTOCOL_VERSION,
                        "capabilities": {},
                        "clientInfo": {"name": "raw-test", "version": "0"},
                    },
                ),
            )
            initialized = await read_stream.receive()
            assert isinstance(initialized, SessionMessage)
            initial_message = initialized.message.root
            assert isinstance(initial_message, types.JSONRPCResponse)
            assert initial_message.id == 1
            assert initial_message.result["capabilities"]["experimental"] == {
                "claude/channel": {}
            }
            await send_message(
                write_stream,
                types.JSONRPCNotification(
                    jsonrpc="2.0",
                    method="notifications/initialized",
                ),
            )
            await send_message(
                write_stream,
                types.JSONRPCRequest(
                    jsonrpc="2.0",
                    id=2,
                    method="tools/call",
                    params={
                        "name": "attach_workspace",
                        "arguments": {
                            "workspace": str(workspace),
                            "token": token,
                        },
                    },
                ),
            )
            attach_response: types.JSONRPCResponse | None = None
            channel_notice: types.JSONRPCNotification | None = None
            with anyio.fail_after(3):
                while attach_response is None or channel_notice is None:
                    received = await read_stream.receive()
                    assert isinstance(received, SessionMessage)
                    message = received.message.root
                    if isinstance(message, types.JSONRPCResponse) and message.id == 2:
                        attach_response = message
                    elif (
                        isinstance(message, types.JSONRPCNotification)
                        and message.method == "notifications/claude/channel"
                    ):
                        channel_notice = message
            assert attach_response.result["isError"] is False
            assert channel_notice.params == {"content": CLAUDE_CHANNEL_CUE}

    try:
        asyncio.run(scenario())
    finally:
        other.close()


@pytest.mark.sqlite_only
@pytest.mark.timeout(15)
def test_claude_attempt_tracker_is_independent_and_fail_open(
    tmp_path: Path,
) -> None:
    """[MCP-9] Each distinct level is attempted once, even after send failure."""

    workspace, token, other = _workspace(tmp_path)

    async def scenario() -> None:
        warnings: list[str] = []
        attempts: list[str] = []
        standard_updates: list[str] = []
        reactor = ConnectionReactor(asyncio.get_running_loop())

        async def failed_send() -> None:
            attempts.append(reactor.current_text)
            raise RuntimeError("host included sensitive failure detail")

        async def standard_send() -> None:
            standard_updates.append(reactor.current_text)

        reactor.configure_claude_channel(failed_send, warnings.append)
        reactor.subscribe(standard_send)
        try:
            attached = await reactor.attach_workspace(str(workspace), token)
            await _wait_until(lambda: len(attempts) == 1 and len(warnings) == 1)
            await _wait_until(lambda: len(standard_updates) == 1)
            first_text = reactor.current_text
            assert attempts == [first_text]
            assert warnings == ["taut-mcp: Claude channel wake failed; continuing"]
            reactor._recompute_resource()
            await asyncio.sleep(0.05)
            assert attempts == [first_text]

            reactor.unsubscribe()
            other.say("general", "changed @selected")
            await _wait_until(lambda: len(attempts) == 2, timeout=1.5)
            await _wait_until(lambda: len(warnings) == 2)
            assert standard_updates == [first_text]
            assert attempts[1] == reactor.current_text
            assert attempts[1] != first_text
            assert json.loads(attempts[1])["workspaces"][0]["notifications"]
            assert reactor.list_workspaces()["records"] == attached["records"]
        finally:
            await reactor.aclose()

    try:
        asyncio.run(scenario())
    finally:
        other.close()
