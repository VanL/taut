"""Backend-real proofs for the single-source workspace reactor [MCP-8]."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
from conftest import canonical_of
from tests.helpers.eventually import async_eventually

from taut import EmptyResultError, Notification, TautClient
from taut_mcp._process_reactor import ProcessReactor
from taut_mcp._workspace_reactor import _resolve_workspace


@pytest.mark.parametrize(
    "backend", ["sqlite", pytest.param("postgres", marks=pytest.mark.pg_only)]
)
@pytest.mark.timeout(30)
def test_peer_claim_publication_and_unpublished_claim_gap(
    backend: str,
    tmp_path: Path,
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Normal claims refresh; raw claims leave a stale advisory view until a hint."""
    project = (
        tmp_path if backend == "sqlite" else request.getfixturevalue("taut_pg_project")
    )
    monkeypatch.chdir(project)
    TautClient.init()
    target, config, _, _ = _resolve_workspace(str(project))
    snapshot_calls: list[None] = []
    original_peek = TautClient.peek_inbox

    def observed_peek(self: TautClient, *, limit: int = 1000) -> list[Notification]:
        snapshot_calls.append(None)
        return original_peek(self, limit=limit)

    monkeypatch.setattr(TautClient, "peek_inbox", observed_peek)
    selected = TautClient(
        broker_target=target, broker_config=config, as_name="selected", persistent=True
    )
    other = TautClient(
        broker_target=target, broker_config=config, as_name="other", persistent=True
    )
    try:
        selected.join("general")
        member = selected.last_created_member
        assert member is not None and member.token is not None
        token = member.token
        other.join("general")
        other.say("general", "first @selected")

        async def scenario() -> None:
            reactor = ProcessReactor(asyncio.get_running_loop())

            def count() -> int:
                return len(
                    json.loads(reactor.current_text)["workspaces"][0]["notifications"]
                )

            try:
                attached = await reactor.attach_workspace(str(project), token)
                canonical = canonical_of(attached)
                assert count() == 1
                baseline_calls = len(snapshot_calls)
                await asyncio.sleep(1.2)
                assert len(snapshot_calls) == baseline_calls
                assert len(selected.inbox()) == 1
                with pytest.raises(EmptyResultError):
                    selected.inbox()
                await async_eventually(
                    lambda: count() == 0,
                    timeout=3,
                    description="peer claim hint refreshes snapshot",
                )
                other.say("general", "second @selected")
                await async_eventually(
                    lambda: count() == 1, timeout=3, description="new pointer appears"
                )
                # Drain the pointer through raw broker mechanics, without Taut's hint.
                assert selected.notification_activity_queue().read_one() is not None
                await asyncio.sleep(0.8)
                assert count() == 1
                selected.queue("taut.cache_stale").write("{}")
                await async_eventually(
                    lambda: count() == 0,
                    timeout=3,
                    description="explicit source row clears stale cache",
                )
                # The cached pointer never authorizes a second atomic claim.
                result = await reactor._execute_ready_tool(canonical, "inbox", {})
                assert result["records"] == []
            finally:
                await reactor.aclose()

        asyncio.run(scenario())
    finally:
        other.close()
        selected.close()


@pytest.mark.sqlite_only
@pytest.mark.timeout(15)
def test_admission_retains_prestart_command_and_notification(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bootstrap has no broker client; a pre-start command survives its latch."""
    import queue
    import threading

    from simplebroker.watcher import PollingStrategy

    from taut_mcp import _workspace_reactor as module

    monkeypatch.chdir(tmp_path)
    TautClient.init()
    seed = TautClient(as_name="selected", persistent=True)
    seed.join("general")
    member = seed.last_created_member
    assert member is not None and member.token is not None
    seed.close()
    constructed = threading.Event()

    class TrackedClient(TautClient):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            constructed.set()
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(module, "TautClient", TrackedClient)
    inbound: queue.Queue[module.WorkspaceControl] = queue.Queue()
    outbound: queue.Queue[module.WorkspaceEvent] = queue.Queue()
    stop = threading.Event()
    strategy = PollingStrategy(stop)
    thread = threading.Thread(
        target=module.run_workspace_reactor,
        args=(inbound, strategy, stop, outbound, lambda: None),
    )
    inbound.put(module.Bootstrap(7, str(tmp_path), member.token))
    strategy.notify_activity()
    thread.start()
    try:
        assert isinstance(outbound.get(timeout=3), module.WorkspaceResolved)
        assert not constructed.is_set()
        inbound.put(module.GrantValidation(7))
        inbound.put(module.RunWorkspaceCommand(7, 1, "whoami", ()))
        strategy.notify_activity()
        assert isinstance(outbound.get(timeout=3), module.WorkspaceReady)
        result = outbound.get(timeout=3)
        assert isinstance(result, module.WorkspaceCommandOutcome)
        assert result.command_id == 1 and result.error is None
    finally:
        inbound.put(module.StopWorkspace(7))
        strategy.notify_activity()
        thread.join(timeout=5)
        assert not thread.is_alive()


@pytest.mark.sqlite_only
@pytest.mark.timeout(15)
def test_command_identity_loss_settles_slot_before_owner_retirement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A terminal event settles the active call and keeps its exact classification."""
    from taut_mcp._process_reactor import WorkspaceToolError

    monkeypatch.chdir(tmp_path)
    TautClient.init()
    seed = TautClient(as_name="selected", persistent=True)
    seed.join("general")
    member = seed.last_created_member
    assert member is not None and member.token is not None

    token = member.token

    async def scenario() -> None:
        reactor = ProcessReactor(asyncio.get_running_loop())
        try:
            canonical = canonical_of(
                await reactor.attach_workspace(str(tmp_path), token)
            )
            with seed._meta_queue.sidecar(transaction=True) as state:
                state.run(
                    "UPDATE taut_members SET token = NULL WHERE member_id = ?",
                    (member.member_id,),
                )
            with pytest.raises(WorkspaceToolError, match="workspace identity lost"):
                await reactor._execute_ready_tool(canonical, "whoami", {})
            entry = reactor._entries[canonical]
            assert entry.active_command_id is None
            await async_eventually(
                lambda: not entry.owner.alive(),
                timeout=3,
                description="identity-lost command owner retires",
            )
            reactor._drain_events()
            assert entry.status == "identity_lost"
        finally:
            await reactor.aclose()

    try:
        asyncio.run(scenario())
    finally:
        seed.close()


@pytest.mark.sqlite_only
@pytest.mark.timeout(15)
def test_workspace_cleanup_attempts_client_and_preserves_first_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Both owners get cleanup even when watcher cleanup reports a failure."""
    import queue
    import threading

    from simplebroker.watcher import PollingStrategy

    from taut.watcher import BaseReactor
    from taut_mcp import _workspace_reactor as module

    monkeypatch.chdir(tmp_path)
    TautClient.init()
    seed = TautClient(as_name="selected", persistent=True)
    seed.join("general")
    member = seed.last_created_member
    assert member is not None and member.token is not None
    seed.close()
    target, config, _, _ = _resolve_workspace(str(tmp_path))
    client = TautClient(
        broker_target=target, broker_config=config, token=member.token, persistent=True
    )
    stop = threading.Event()
    reactor = module._WorkspaceReactor(
        queue.Queue(),
        PollingStrategy(stop),
        stop,
        queue.Queue(),
        lambda: None,
        generation=1,
        client=client,
        target=target,
        config=config,
    )
    first = RuntimeError("watcher cleanup failed")
    calls: list[str] = []

    def fail_watcher(self: BaseReactor) -> None:
        calls.append("watcher")
        raise first

    def fail_client() -> None:
        calls.append("client")
        raise RuntimeError("client cleanup failed")

    try:
        with monkeypatch.context() as patch:
            patch.setattr(BaseReactor, "_close_reactor_resources", fail_watcher)
            patch.setattr(client, "close", fail_client)
            with pytest.raises(RuntimeError) as raised:
                reactor.stop(join=False)
            assert raised.value is first
            assert calls == ["watcher", "client"]
    finally:
        reactor.stop(join=False)


@pytest.mark.parametrize(
    "backend", ["sqlite", pytest.param("postgres", marks=pytest.mark.pg_only)]
)
@pytest.mark.timeout(20)
def test_source_cursor_precedes_baseline_snapshot_publication(
    backend: str,
    tmp_path: Path,
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A pointer inserted after baseline read remains visible after owner startup."""
    import threading

    project = (
        tmp_path if backend == "sqlite" else request.getfixturevalue("taut_pg_project")
    )
    monkeypatch.chdir(project)
    TautClient.init()
    target, config, _, _ = _resolve_workspace(str(project))
    selected = TautClient(
        broker_target=target, broker_config=config, as_name="selected", persistent=True
    )
    other = TautClient(
        broker_target=target, broker_config=config, as_name="other", persistent=True
    )
    baseline_read = threading.Event()
    release = threading.Event()
    original = TautClient.peek_inbox
    captured: list[list[Notification]] = []

    def held_baseline(self: TautClient, *, limit: int = 1000) -> list[Notification]:
        result = original(self, limit=limit)
        if not baseline_read.is_set():
            captured.append(result)
            baseline_read.set()
            if not release.wait(5):
                raise AssertionError("baseline publication was not released")
        return result

    try:
        selected.join("general")
        member = selected.last_created_member
        assert member is not None and member.token is not None
        token = member.token
        other.join("general")
        monkeypatch.setattr(TautClient, "peek_inbox", held_baseline)

        async def scenario() -> None:
            reactor = ProcessReactor(asyncio.get_running_loop())
            attaching = asyncio.create_task(
                reactor.attach_workspace(str(project), token)
            )
            try:
                assert await asyncio.to_thread(baseline_read.wait, 5)
                assert captured == [[]]
                other.say("general", "between baseline and ready @selected")
                release.set()
                await attaching
                await async_eventually(
                    lambda: (
                        len(
                            json.loads(reactor.current_text)["workspaces"][0][
                                "notifications"
                            ]
                        )
                        == 1
                    ),
                    timeout=3,
                    description="post-baseline insertion remains cursor-qualified",
                )
            finally:
                release.set()
                await reactor.aclose()
                await asyncio.gather(attaching, return_exceptions=True)

        asyncio.run(scenario())
    finally:
        release.set()
        other.close()
        selected.close()


@pytest.mark.sqlite_only
@pytest.mark.parametrize("operation", ["ensure", "detach"])
@pytest.mark.timeout(15)
def test_lifecycle_admission_drains_identity_loss_before_reaping(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    """A retired real child keeps its queued terminal cause at admission."""
    from taut_mcp._process_reactor import WorkspaceToolError
    from taut_mcp._workspace_reactor import RunWorkspaceCommand

    monkeypatch.chdir(tmp_path)
    TautClient.init()
    seed = TautClient(as_name="selected", persistent=True)
    seed.join("general")
    member = seed.last_created_member
    assert member is not None and member.token is not None
    token = member.token

    async def scenario() -> None:
        diagnostics: list[str] = []
        reactor = ProcessReactor(
            asyncio.get_running_loop(), diagnostic=diagnostics.append
        )
        try:
            canonical = canonical_of(
                await reactor.attach_workspace(str(tmp_path), token)
            )
            entry = reactor._entries[canonical]
            drain = reactor._drain_events
            monkeypatch.setattr(reactor, "_drain_events", lambda: None)
            with seed._meta_queue.sidecar(transaction=True) as state:
                state.run(
                    "UPDATE taut_members SET token = NULL WHERE member_id = ?",
                    (member.member_id,),
                )
            entry.owner.send(RunWorkspaceCommand(entry.generation, 1, "whoami", ()))
            await async_eventually(
                lambda: not entry.owner.alive(),
                timeout=3,
                description="identity-lost child exits before parent applies events",
            )
            assert entry.status == "ready"
            monkeypatch.setattr(reactor, "_drain_events", drain)
            if operation == "ensure":
                with pytest.raises(WorkspaceToolError, match="workspace identity lost"):
                    await reactor.ensure_workspace(canonical, token)
            else:
                result = await reactor.detach_workspace(canonical)
                assert result["records"][0]["status"] == "detached"
            assert entry.status == "identity_lost"
            assert diagnostics == []
        finally:
            await reactor.aclose()

    try:
        asyncio.run(scenario())
    finally:
        seed.close()
