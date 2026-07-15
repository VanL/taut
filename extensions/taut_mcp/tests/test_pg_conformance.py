"""Real PostgreSQL conformance for MCP child dispatch."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

import taut.identity as identity
import taut_mcp._workspace_reactor as workspace_reactor
from taut import TautClient
from taut_mcp._connection_reactor import ConnectionReactor


def _sqlite_member(
    workspace: Path,
    name: str,
    *,
    configured: bool,
) -> tuple[str, str]:
    workspace.mkdir()
    if configured:
        data = workspace / "state"
        data.mkdir()
        db = data / "taut.sqlite"
        (workspace / ".taut.toml").write_text(
            'version = 1\nbackend = "sqlite"\ntarget = "state/taut.sqlite"\n',
            encoding="utf-8",
        )
    else:
        db = workspace / ".taut.db"
    TautClient.init(db_path=db)
    client = TautClient(db_path=db, as_name=name)
    client.join("general")
    member = client.last_created_member
    assert member is not None and member.token is not None
    client.close()
    return member.token, member.member_id


@pytest.mark.pg_only
@pytest.mark.timeout(30)
def test_postgres_activity_tools_preserve_identity_and_presence(
    taut_pg_project: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """[MCP-5]/[MCP-12] Activity-only effects match SQLite on PostgreSQL."""

    monkeypatch.chdir(taut_pg_project)
    TautClient.init()
    selected = TautClient(as_name="selected")
    selected.join("general")
    member = selected.last_created_member
    assert member is not None
    assert member.token is not None
    token = member.token
    selected.close()

    async def scenario() -> None:
        reactor = ConnectionReactor(asyncio.get_running_loop())
        observer = TautClient()

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
            attached = await reactor.attach_workspace(str(taut_pg_project), token)
            assert attached["records"][0]["backend"] == "postgres"
            canonical = str(attached["workspace"])
            calls: list[tuple[str, dict[str, object]]] = [
                ("list", {"all": True}),
                ("who", {"thread": None}),
                ("whoami", {}),
            ]
            for tool, arguments in calls:
                before_activity, before_identity = snapshot()
                await reactor.execute_tool(canonical, tool, arguments)
                after_activity, after_identity = snapshot()
                assert after_activity > before_activity
                assert after_identity == before_identity
        finally:
            observer.close()
            await reactor.aclose()

    asyncio.run(scenario())


@pytest.mark.pg_only
@pytest.mark.timeout(60)
def test_postgres_read_limit_pages_without_cursor_gaps(
    taut_pg_project: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """[MCP-5]/[MCP-12] PostgreSQL uses the same pre-cursor page bound."""

    monkeypatch.chdir(taut_pg_project)
    TautClient.init()
    selected = TautClient(as_name="selected")
    selected.join("general")
    member = selected.last_created_member
    assert member is not None
    assert member.token is not None
    other = TautClient(as_name="other")
    other.join("general")
    selected.read("general", limit=1000)
    expected: list[str] = []
    for index in range(250):
        text = f"pg-page-{index:03d}"
        expected.append(text)
        other.say("general", text)
    selected.close()
    other.close()

    async def scenario() -> None:
        reactor = ConnectionReactor(asyncio.get_running_loop())
        try:
            attached = await reactor.attach_workspace(
                str(taut_pg_project),
                member.token or "",
            )
            canonical = str(attached["workspace"])
            pages = [
                await reactor.execute_tool(
                    canonical,
                    "read",
                    {"thread": "general", "limit": limit},
                )
                for limit in (100, 100, 1000)
            ]
            assert [len(page["records"]) for page in pages] == [100, 100, 50]
            assert [
                record["text"] for page in pages for record in page["records"]
            ] == expected
        finally:
            await reactor.aclose()

    asyncio.run(scenario())


@pytest.mark.pg_only
@pytest.mark.timeout(30)
def test_postgres_native_notification_wake_precedes_long_backstop(
    taut_pg_project: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """[MCP-8]/[MCP-12] Real LISTEN/NOTIFY wakes without claiming pointers."""

    monkeypatch.chdir(taut_pg_project)
    monkeypatch.setattr(workspace_reactor, "NOTIFICATION_BACKSTOP_SECONDS", 5.0)
    TautClient.init()
    selected = TautClient(as_name="selected")
    selected.join("general")
    member = selected.last_created_member
    assert member is not None
    assert member.token is not None
    other = TautClient(as_name="other")
    other.join("general")

    async def scenario() -> None:
        reactor = ConnectionReactor(asyncio.get_running_loop())
        updates: asyncio.Queue[float] = asyncio.Queue()

        async def updated() -> None:
            updates.put_nowait(asyncio.get_running_loop().time())

        try:
            attached = await reactor.attach_workspace(
                str(taut_pg_project),
                member.token or "",
            )
            canonical = str(attached["workspace"])
            reactor.subscribe(updated)
            await asyncio.wait_for(updates.get(), timeout=1)
            started = asyncio.get_running_loop().time()
            other.say("general", "native @selected")
            observed = await asyncio.wait_for(updates.get(), timeout=2)
            assert observed - started < 2
            notifications = reactor.current_text
            assert '"matched":"@selected"' in notifications
            claimed = await reactor.execute_tool(
                canonical,
                "inbox",
                {"limit": 1},
            )
            assert claimed["records"][0]["matched"] == "@selected"
        finally:
            await reactor.aclose()

    try:
        asyncio.run(scenario())
    finally:
        selected.close()
        other.close()


@pytest.mark.pg_only
@pytest.mark.timeout(30)
def test_one_reactor_owns_unconfigured_sqlite_configured_sqlite_and_postgres(
    taut_pg_project: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """[MCP-4]/[MCP-12] Mixed backends remain per-child client state."""

    monkeypatch.chdir(taut_pg_project)
    TautClient.init()
    pg_client = TautClient(as_name="postgres_member")
    pg_client.join("general")
    pg_member = pg_client.last_created_member
    assert pg_member is not None and pg_member.token is not None
    pg_client.close()
    plain_workspace = taut_pg_project.parent / f"{taut_pg_project.name}_plain_sqlite"
    plain_token, plain_member_id = _sqlite_member(
        plain_workspace, "plain_member", configured=False
    )
    configured_workspace = (
        taut_pg_project.parent / f"{taut_pg_project.name}_configured_sqlite"
    )
    configured_token, configured_member_id = _sqlite_member(
        configured_workspace, "configured_member", configured=True
    )

    async def scenario() -> None:
        reactor = ConnectionReactor(asyncio.get_running_loop())
        try:
            attached = await asyncio.gather(
                reactor.attach_workspace(str(plain_workspace), plain_token),
                reactor.attach_workspace(str(configured_workspace), configured_token),
                reactor.attach_workspace(str(taut_pg_project), pg_member.token or ""),
            )
            assert [item["records"][0]["backend"] for item in attached] == [
                "sqlite",
                "sqlite",
                "postgres",
            ]
            identities = await asyncio.gather(
                *[
                    reactor.execute_tool(str(item["workspace"]), "whoami", {})
                    for item in attached
                ]
            )
            assert [item["records"][0]["member_id"] for item in identities] == [
                plain_member_id,
                configured_member_id,
                pg_member.member_id,
            ]
        finally:
            await reactor.aclose()

    asyncio.run(scenario())
