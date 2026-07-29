from __future__ import annotations

import asyncio
import json
import threading
from pathlib import Path
from typing import Any

import pytest

import taut.identity as identity
import taut_mcp._workspace_reactor as workspace_reactor
from taut import TautClient, addressing
from taut_mcp._process_reactor import ProcessReactor


def _workspace(
    root: Path,
    name: str,
    *,
    selected_name: str,
    other_name: str,
) -> tuple[Path, str, TautClient]:
    workspace = root / name
    workspace.mkdir()
    db = workspace / ".taut.db"
    TautClient.init(db_path=db)
    selected = TautClient(db_path=db, as_name=selected_name)
    selected.join("general")
    member = selected.last_created_member
    assert member is not None
    assert member.token is not None
    token = member.token
    selected.close()
    other = TautClient(db_path=db, as_name=other_name)
    other.join("general")
    return workspace, token, other


async def _wait_until(predicate: Any, *, timeout: float = 5.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        if asyncio.get_running_loop().time() >= deadline:
            raise AssertionError("condition did not become true")
        await asyncio.sleep(0.01)


@pytest.mark.sqlite_only
@pytest.mark.timeout(15)
def test_reaction_appears_in_recipient_resource_and_inbox_consumes_it(
    tmp_path: Path,
) -> None:
    """[MCP-5]/[MCP-7] Outgoing reaction receipts and recipient pointers stay distinct."""

    workspace, recipient_token, actor = _workspace(
        tmp_path,
        "workspace",
        selected_name="recipient",
        other_name="actor",
    )
    actor_member = actor.last_created_member
    assert actor_member is not None
    assert actor_member.token is not None
    source = actor.say("general", "react to this")

    async def scenario() -> None:
        recipient_reactor = ProcessReactor(asyncio.get_running_loop())
        actor_reactor = ProcessReactor(asyncio.get_running_loop())
        try:
            recipient_attached = await recipient_reactor.attach_workspace(
                str(workspace),
                recipient_token,
            )
            actor_attached = await actor_reactor.attach_workspace(
                str(workspace),
                actor_member.token or "",
            )
            result = await actor_reactor._execute_ready_tool(
                str(actor_attached["workspace"]),
                "message_react",
                {"msg_id": str(source.ts), "reaction": "ack"},
            )
            assert result["records"] == [
                {
                    "audience_count": 1,
                    "message_ts": source.ts,
                    "reaction": "ack",
                    "thread": "general",
                }
            ]
            assert (
                json.loads(actor_reactor.current_text)["workspaces"][0]["notifications"]
                == []
            )

            await _wait_until(
                lambda: (
                    json.loads(recipient_reactor.current_text)["workspaces"][0][
                        "notifications"
                    ]
                    == [
                        {
                            "actor_id": actor_member.member_id,
                            "actor_name": "actor",
                            "message_ts": source.ts,
                            "reaction": "ack",
                            "thread": "general",
                            "to_id": None,
                            "type": "reaction",
                        }
                    ]
                ),
                timeout=1.5,
            )
            claimed = await recipient_reactor._execute_ready_tool(
                str(recipient_attached["workspace"]),
                "inbox",
                {"limit": 1},
            )
            assert claimed["record_type"] == "notification"
            assert claimed["records"] == [
                {
                    "actor_id": actor_member.member_id,
                    "actor_name": "actor",
                    "message_ts": source.ts,
                    "reaction": "ack",
                    "thread": "general",
                    "to_id": None,
                    "type": "reaction",
                }
            ]
            assert (
                json.loads(recipient_reactor.current_text)["workspaces"][0][
                    "notifications"
                ]
                == []
            )
        finally:
            await actor_reactor.aclose()
            await recipient_reactor.aclose()

    try:
        asyncio.run(scenario())
    finally:
        actor.close()


@pytest.mark.sqlite_only
@pytest.mark.timeout(15)
def test_legacy_failure_cannot_suppress_modern_resource_delivery(
    tmp_path: Path,
) -> None:
    """[MCP-8] One semantic change independently fans out to both adapters."""

    workspace, token, other = _workspace(
        tmp_path,
        "workspace",
        selected_name="selected",
        other_name="other",
    )

    async def scenario() -> None:
        reactor = ProcessReactor(asyncio.get_running_loop())
        legacy_attempts: list[str] = []
        modern_updates: list[str] = []

        async def failing_legacy() -> None:
            legacy_attempts.append(reactor.current_text)
            raise RuntimeError("synthetic legacy sink failure")

        async def modern_update() -> None:
            modern_updates.append(reactor.current_text)

        reactor.subscribe(failing_legacy)
        reactor.configure_modern_resource_sender(modern_update)
        try:
            await reactor.attach_workspace(str(workspace), token)
            await _wait_until(
                lambda: len(legacy_attempts) == 1 and len(modern_updates) == 1
            )
            assert legacy_attempts == modern_updates

            other.say("general", "changed @selected")
            await _wait_until(
                lambda: len(legacy_attempts) == 2 and len(modern_updates) == 2,
                timeout=1.5,
            )
            assert legacy_attempts == modern_updates
        finally:
            await reactor.aclose()

    try:
        asyncio.run(scenario())
    finally:
        other.close()


@pytest.mark.sqlite_only
@pytest.mark.timeout(60)
def test_resource_sorts_workspaces_and_bounds_each_notification_snapshot(
    tmp_path: Path,
) -> None:
    """[MCP-7] Each ready child contributes at most its oldest 100 pointers."""

    later, later_token, later_other = _workspace(
        tmp_path,
        "z-workspace",
        selected_name="later_selected",
        other_name="later_other",
    )
    earlier, earlier_token, earlier_other = _workspace(
        tmp_path,
        "a-workspace",
        selected_name="earlier_selected",
        other_name="earlier_other",
    )
    for index in range(101):
        later_other.say("general", f"pointer-{index:03d} @later_selected")
    earlier_other.say("general", "one @earlier_selected")

    async def scenario() -> None:
        reactor = ProcessReactor(asyncio.get_running_loop())
        try:
            later_result = await reactor.attach_workspace(str(later), later_token)
            earlier_result = await reactor.attach_workspace(str(earlier), earlier_token)
            parsed = json.loads(reactor.current_text)
            entries = parsed["workspaces"]
            assert [entry["workspace"] for entry in entries] == sorted(
                [later_result["workspace"], earlier_result["workspace"]]
            )
            by_workspace = {entry["workspace"]: entry for entry in entries}
            later_entry = by_workspace[later_result["workspace"]]
            assert len(later_entry["notifications"]) == 100
            assert later_entry["truncated"] is True
            assert [
                item["message_ts"] for item in later_entry["notifications"]
            ] == sorted(item["message_ts"] for item in later_entry["notifications"])
            earlier_entry = by_workspace[earlier_result["workspace"]]
            assert len(earlier_entry["notifications"]) == 1
            assert earlier_entry["truncated"] is False

            claimed = await reactor._execute_ready_tool(
                str(later_result["workspace"]),
                "inbox",
                {"limit": 1},
            )
            assert len(claimed["records"]) == 1
            refreshed = {
                entry["workspace"]: entry
                for entry in json.loads(reactor.current_text)["workspaces"]
            }
            assert len(refreshed[later_result["workspace"]]["notifications"]) == 100
            assert refreshed[later_result["workspace"]]["truncated"] is False
            assert refreshed[earlier_result["workspace"]] == earlier_entry
        finally:
            await reactor.aclose()

    try:
        asyncio.run(scenario())
    finally:
        later_other.close()
        earlier_other.close()


@pytest.mark.sqlite_only
@pytest.mark.timeout(15)
def test_backstop_detects_external_consumption_without_touching_identity(
    tmp_path: Path,
) -> None:
    """[MCP-7]/[MCP-8] Repeated peeks are observational and externally fresh."""

    workspace, token, other = _workspace(
        tmp_path,
        "workspace",
        selected_name="selected",
        other_name="other",
    )
    other.say("general", "pending @selected")
    observer = TautClient(db_path=workspace / ".taut.db")

    def bound_identity() -> tuple[object, ...]:
        row = observer._state.get_member_by_token(token)
        assert row is not None
        return (
            row["last_active_ts"],
            row["host_id"],
            row["host_label"],
            row["anchor_pid"],
            row["anchor_start_time"],
            row["fingerprint"],
            identity.member_presence(row, identity.capture_host_identity().host_id),
        )

    async def scenario() -> None:
        reactor = ProcessReactor(asyncio.get_running_loop())
        try:
            attached = await reactor.attach_workspace(str(workspace), token)
            canonical = str(attached["workspace"])
            assert (
                len(json.loads(reactor.current_text)["workspaces"][0]["notifications"])
                == 1
            )
            before = bound_identity()
            await asyncio.sleep(1.1)
            assert bound_identity() == before
            row = observer._state.get_member_by_token(token)
            assert row is not None
            notification_queue = observer.queue(
                addressing.notification_queue_name(str(row["member_id"]))
            )
            assert notification_queue.read_one(with_timestamps=True) is not None
            await _wait_until(
                lambda: (
                    json.loads(reactor.current_text)["workspaces"][0]["notifications"]
                    == []
                ),
                timeout=1.5,
            )
            assert bound_identity() == before
            assert reactor.list_workspaces()["records"][0]["workspace"] == canonical
        finally:
            await reactor.aclose()

    try:
        asyncio.run(scenario())
    finally:
        observer.close()
        other.close()


class _FakeActivityWaiter:
    def __init__(self) -> None:
        self._event = threading.Event()
        self.closed = False
        self.wait_threads: set[int] = set()
        self.close_thread: int | None = None

    def wait(self, timeout: float) -> bool:
        self.wait_threads.add(threading.get_ident())
        observed = self._event.wait(timeout)
        if observed:
            self._event.clear()
        return observed

    def fire(self) -> None:
        self._event.set()

    def close(self) -> None:
        self.closed = True
        self.close_thread = threading.get_ident()
        self._event.set()


@pytest.mark.sqlite_only
@pytest.mark.timeout(15)
def test_native_activity_wake_is_immediate_but_bursts_are_paced(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """[MCP-8] Native-only snapshots are coalesced to one per 0.5 seconds."""

    workspace, token, other = _workspace(
        tmp_path,
        "workspace",
        selected_name="selected",
        other_name="other",
    )
    waiter = _FakeActivityWaiter()
    factory_called = threading.Event()
    factory_thread: list[int] = []
    queue_names: list[str] = []
    master_thread = threading.get_ident()

    def activity_waiter_factory(
        queues: Any,
        *,
        stop_event: threading.Event,
    ) -> _FakeActivityWaiter:
        del stop_event
        factory_thread.append(threading.get_ident())
        queue_names.extend(queue.name for queue in queues)
        factory_called.set()
        return waiter

    monkeypatch.setattr(
        workspace_reactor,
        "create_activity_waiter_for_queues",
        activity_waiter_factory,
        raising=False,
    )

    async def scenario() -> None:
        reactor = ProcessReactor(asyncio.get_running_loop())
        updates: list[float] = []

        async def updated() -> None:
            updates.append(asyncio.get_running_loop().time())

        try:
            attached = await reactor.attach_workspace(str(workspace), token)
            assert factory_called.wait(timeout=1)
            reactor.subscribe(updated)
            await _wait_until(lambda: len(updates) == 1)
            updates.clear()

            # A completed command starts a fresh observational-backstop interval.
            # Keep that independent poll from racing this native-wake pacing proof.
            await reactor._execute_ready_tool(
                str(attached["workspace"]),
                "whoami",
                {},
            )
            other.say("general", "first @selected")
            started = asyncio.get_running_loop().time()
            waiter.fire()
            await _wait_until(lambda: len(updates) == 1, timeout=0.3)
            assert updates[0] - started < 0.3

            other.say("general", "second @selected")
            waiter.fire()
            await asyncio.sleep(0.2)
            assert len(updates) == 1
            await _wait_until(lambda: len(updates) == 2, timeout=0.6)
            assert updates[1] - updates[0] >= 0.45
            notifications = json.loads(reactor.current_text)["workspaces"][0][
                "notifications"
            ]
            assert [item["matched"] for item in notifications] == [
                "@selected",
                "@selected",
            ]
            assert attached["workspace"] == str(workspace.resolve())
        finally:
            await reactor.aclose()

    try:
        asyncio.run(scenario())
    finally:
        other.close()
    assert waiter.closed is True
    assert len(queue_names) == 1
    assert queue_names[0].startswith("notify.m_")
    assert len(factory_thread) == 1
    assert factory_thread[0] != master_thread
    assert waiter.wait_threads == {factory_thread[0]}
    assert waiter.close_thread == factory_thread[0]


class _FailingActivityWaiter(_FakeActivityWaiter):
    def wait(self, timeout: float) -> bool:
        del timeout
        raise RuntimeError("native waiter unavailable")


@pytest.mark.sqlite_only
@pytest.mark.timeout(15)
def test_native_wait_failure_falls_back_to_observational_backstop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """[MCP-8]/[MCP-11] A failed hint path does not degrade the workspace."""

    workspace, token, other = _workspace(
        tmp_path,
        "workspace",
        selected_name="selected",
        other_name="other",
    )
    waiter = _FailingActivityWaiter()

    def activity_waiter_factory(
        queues: object,
        *,
        stop_event: threading.Event,
    ) -> _FailingActivityWaiter:
        del queues, stop_event
        return waiter

    monkeypatch.setattr(
        workspace_reactor,
        "create_activity_waiter_for_queues",
        activity_waiter_factory,
        raising=False,
    )

    async def scenario() -> None:
        reactor = ProcessReactor(asyncio.get_running_loop())
        try:
            attached = await reactor.attach_workspace(str(workspace), token)
            other.say("general", "fallback @selected")
            await _wait_until(
                lambda: (
                    len(
                        json.loads(reactor.current_text)["workspaces"][0][
                            "notifications"
                        ]
                    )
                    == 1
                ),
                timeout=1.5,
            )
            assert reactor.list_workspaces()["records"] == attached["records"]
        finally:
            await reactor.aclose()

    try:
        asyncio.run(scenario())
    finally:
        other.close()
    assert waiter.closed is True
