"""Real PostgreSQL conformance for MCP child dispatch."""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from typing import Any

import pytest

import taut.identity as identity
import taut_mcp._workspace_reactor as workspace_reactor
from taut import TautClient
from taut_mcp._process_reactor import ProcessReactor


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
        reactor = ProcessReactor(asyncio.get_running_loop())
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
                await reactor._execute_ready_tool(canonical, tool, arguments)
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
        reactor = ProcessReactor(asyncio.get_running_loop())
        try:
            attached = await reactor.attach_workspace(
                str(taut_pg_project),
                member.token or "",
            )
            canonical = str(attached["workspace"])
            pages = [
                await reactor._execute_ready_tool(
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
def test_postgres_explicit_dm_navigation_and_directory(
    taut_pg_project: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """[MCP-5]/[MCP-12] PostgreSQL matches the public DM navigation contract."""

    monkeypatch.chdir(taut_pg_project)
    TautClient.init()
    selected = TautClient(as_name="selected")
    selected.join("general")
    member = selected.last_created_member
    assert member is not None and member.token is not None
    other = TautClient(as_name="other")
    other.join("general")
    sent = other.say("@selected", "pg private history")
    selected.close()
    other.close()

    async def scenario() -> None:
        reactor = ProcessReactor(asyncio.get_running_loop())
        try:
            attached = await reactor.attach_workspace(
                str(taut_pg_project),
                member.token or "",
            )
            canonical = str(attached["workspace"])
            history = await reactor._execute_ready_tool(
                canonical,
                "log",
                {"thread": "@other", "since": None, "limit": 100},
            )
            assert history["records"][0]["thread"] == sent.thread
            assert history["records"][0]["text"] == "pg private history"
            unread = await reactor._execute_ready_tool(
                canonical,
                "read",
                {"thread": sent.thread, "limit": 100},
            )
            assert unread["records"][0]["thread"] == sent.thread
            directory = await reactor._execute_ready_tool(
                canonical,
                "list",
                {"dms": True},
            )
            assert [record["thread"] for record in directory["records"]] == [
                sent.thread
            ]
            assert directory["records"][0]["unread"] is False
        finally:
            await reactor.aclose()

    asyncio.run(scenario())


@pytest.mark.pg_only
@pytest.mark.timeout(30)
def test_postgres_exact_message_tools_use_public_core_contract(
    taut_pg_project: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(taut_pg_project)
    TautClient.init()
    selected = TautClient(as_name="selected")
    selected.join("general")
    member = selected.last_created_member
    assert member is not None
    assert member.token is not None
    other = TautClient(as_name="other")
    other.join("general")
    shown_target = other.say("general", "pg exact show")
    deletion_target = selected.say("general", "pg exact delete")
    selected_id = member.member_id
    selected.close()
    other.close()
    committed_topic = threading.Event()
    release_topic = threading.Event()
    real_execute = workspace_reactor.execute_command

    def commit_then_delay_topic(
        client: TautClient,
        name: str,
        arguments: Any,
    ) -> Any:
        result = real_execute(client, name, arguments)
        if (
            name == "channel_topic"
            and dict(arguments).get("topic") == "pg canceled topic"
        ):
            committed_topic.set()
            if not release_topic.wait(timeout=5):
                raise AssertionError("test did not release committed PG topic")
        return result

    monkeypatch.setattr(
        workspace_reactor,
        "execute_command",
        commit_then_delay_topic,
    )

    async def scenario() -> None:
        reactor = ProcessReactor(asyncio.get_running_loop())
        observer = TautClient(as_name="other")
        try:
            attached = await reactor.attach_workspace(
                str(taut_pg_project),
                member.token or "",
            )
            canonical = str(attached["workspace"])
            before_history = tuple(observer.log("general", limit=1000))
            before_notifications = tuple(observer.peek_inbox())
            before_membership = observer._state.get_membership(
                thread="general",
                member_id=selected_id,
            )
            before_member = observer._state.get_member(selected_id)
            assert before_member is not None
            shown_channel = await reactor._execute_ready_tool(
                canonical,
                "channel_show",
                {"channel": "general"},
            )
            assert shown_channel["record_type"] == "channel"
            assert shown_channel["records"][0]["topic"] is None
            assert observer._state.get_member(selected_id) == before_member
            topic = await reactor._execute_ready_tool(
                canonical,
                "channel_topic",
                {"channel": "general", "topic": "pg topic"},
            )
            assert topic["record_type"] == "channel"
            assert topic["records"][0]["topic"] == "pg topic"
            changed_member = observer._state.get_member(selected_id)
            assert changed_member is not None
            assert changed_member["last_active_ts"] > before_member["last_active_ts"]
            assert (
                changed_member["last_active_ts"]
                == topic["records"][0]["topic_updated_ts"]
            )
            same_topic = await reactor._execute_ready_tool(
                canonical,
                "channel_topic",
                {"channel": "general", "topic": "pg topic"},
            )
            assert same_topic == topic
            assert observer._state.get_member(selected_id) == changed_member
            assert (
                observer._state.get_membership(
                    thread="general",
                    member_id=selected_id,
                )
                == before_membership
            )
            assert tuple(observer.log("general", limit=1000)) == before_history
            assert tuple(observer.peek_inbox()) == before_notifications
            listed = await reactor._execute_ready_tool(
                canonical,
                "list",
                {"all": True},
            )
            assert (
                next(
                    record
                    for record in listed["records"]
                    if record["thread"] == "general"
                )["topic"]
                == "pg topic"
            )
            shown = await reactor._execute_ready_tool(
                canonical,
                "message_show",
                {"msg_id": str(shown_target.ts)},
            )
            assert shown["record_type"] == "message"
            assert shown["records"][0]["text"] == "pg exact show"
            reacted = await reactor._execute_ready_tool(
                canonical,
                "message_react",
                {"msg_id": str(shown_target.ts), "reaction": "ack"},
            )
            assert reacted["record_type"] == "reaction"
            assert reacted["records"] == [
                {
                    "audience_count": 1,
                    "message_ts": shown_target.ts,
                    "reaction": "ack",
                    "thread": "general",
                }
            ]
            deleted = await reactor._execute_ready_tool(
                canonical,
                "message_delete",
                {"msg_id": str(deletion_target.ts)},
            )
            assert deleted["record_type"] == "deletion"
            assert deleted["records"] == [
                {
                    "deleted": True,
                    "thread": "general",
                    "ts": deletion_target.ts,
                }
            ]
            renamed = await reactor._execute_ready_tool(
                canonical,
                "channel_rename",
                {"old_name": "general", "new_name": "main"},
            )
            assert renamed["records"][0]["thread"] == "main"
            assert renamed["records"][0]["topic"] == "pg topic"
            cleared = await reactor._execute_ready_tool(
                canonical,
                "channel_topic",
                {"channel": "main", "topic": None},
            )
            assert cleared["records"][0]["topic"] is None

            canceled = asyncio.create_task(
                reactor._execute_ready_tool(
                    canonical,
                    "channel_topic",
                    {"channel": "main", "topic": "pg canceled topic"},
                )
            )
            assert await asyncio.to_thread(committed_topic.wait, 5)
            canceled.cancel()
            with pytest.raises(asyncio.CancelledError):
                await canceled
            release_topic.set()
            deadline = asyncio.get_running_loop().time() + 5
            while reactor._entries[canonical].active_command_id is not None:
                if asyncio.get_running_loop().time() >= deadline:
                    raise AssertionError("PG topic completion did not settle")
                await asyncio.sleep(0.01)
            recovered = await reactor._execute_ready_tool(
                canonical,
                "channel_show",
                {"channel": "main"},
            )
            assert recovered["records"][0]["topic"] == "pg canceled topic"
        finally:
            release_topic.set()
            observer.close()
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
        reactor = ProcessReactor(asyncio.get_running_loop())
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
            claimed = await reactor._execute_ready_tool(
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
        reactor = ProcessReactor(asyncio.get_running_loop())
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
                    reactor._execute_ready_tool(str(item["workspace"]), "whoami", {})
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
