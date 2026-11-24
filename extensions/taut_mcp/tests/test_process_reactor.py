from __future__ import annotations

import asyncio
import gc
import json
import os
import queue
import shutil
import subprocess
import sys
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from conftest import canonical_of
from simplebroker import Queue
from tests.helpers.eventually import async_eventually

import taut.watcher as core_watcher
import taut_mcp._process_reactor as process_reactor
import taut_mcp._workspace_reactor as workspace_reactor
from taut import TautClient, TautError
from taut_mcp._process_reactor import (
    ProcessReactor,
    WorkspaceToolError,
)


@contextmanager
def _tool_error(message: str) -> Iterator[None]:
    with pytest.raises(WorkspaceToolError) as raised:
        yield
    assert str(raised.value) == message


def _create_workspace(tmp_path: Path, name: str) -> tuple[Path, str, str]:
    workspace = tmp_path / name
    workspace.mkdir()
    db = workspace / ".taut.db"
    TautClient.init(db_path=db)
    client = TautClient(db_path=db, as_name=name)
    client.join("general")
    member = client.last_created_member
    assert member is not None
    assert member.token is not None
    client.close()
    return workspace, member.token, member.member_id


def _debug_events(workspace: Path) -> list[dict[str, Any]]:
    queue = Queue("taut.debug", db_path=str(workspace / ".taut.db"))
    try:
        messages = queue.peek(all_messages=True, include_claimed=True)
        assert messages is not None
        return [json.loads(message) for message in messages]
    finally:
        queue.close()


@pytest.mark.sqlite_only
@pytest.mark.timeout(10)
def test_teardown_denies_ready_publication_after_validation_started(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """[MCP-11] A late validation success cannot publish during close."""

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    db = workspace / ".taut.db"
    TautClient.init(db_path=db)
    selected = TautClient(db_path=db, as_name="selected")
    selected.join("general")
    member = selected.last_created_member
    assert member is not None
    assert member.token is not None
    selected.close()

    validation_started = threading.Event()
    release_validation = threading.Event()
    real_client = workspace_reactor.TautClient

    def delayed_client(*args: object, **kwargs: Any) -> TautClient:
        client = real_client(*args, **kwargs)
        validation_started.set()
        if not release_validation.wait(timeout=5):
            raise AssertionError("test did not release validation")
        return client

    monkeypatch.setattr(workspace_reactor, "TautClient", delayed_client)

    async def scenario() -> None:
        reactor = ProcessReactor(asyncio.get_running_loop())
        attach = asyncio.create_task(
            reactor.attach_workspace(str(workspace), member.token or "")
        )
        assert await asyncio.to_thread(validation_started.wait, 5)

        close = asyncio.create_task(reactor.aclose())
        await asyncio.sleep(0)
        release_validation.set()
        await asyncio.wait_for(close, timeout=5)

        with pytest.raises(asyncio.CancelledError):
            await attach
        assert reactor.list_workspaces()["records"] == []

    asyncio.run(scenario())


@pytest.mark.sqlite_only
@pytest.mark.timeout(10)
def test_teardown_rejects_detach_admission(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """[MCP-11] Close publishes its gate before yielding during teardown."""

    workspace, token, _ = _create_workspace(tmp_path, "selected")
    close_started = threading.Event()
    release_close = threading.Event()
    real_close = workspace_reactor.TautClient.close

    def delayed_close(client: TautClient) -> None:
        close_started.set()
        if not release_close.wait(timeout=5):
            raise AssertionError("test did not release workspace close")
        real_close(client)

    monkeypatch.setattr(workspace_reactor.TautClient, "close", delayed_close)

    async def scenario() -> None:
        reactor = ProcessReactor(asyncio.get_running_loop())
        attached = await reactor.attach_workspace(str(workspace), token)
        close = asyncio.create_task(reactor.aclose())
        try:
            assert await asyncio.to_thread(close_started.wait, 5)
            with _tool_error(process_reactor.ATTACHMENT_FAILED):
                await asyncio.wait_for(
                    reactor.detach_workspace(canonical_of(attached)),
                    timeout=0.25,
                )
        finally:
            release_close.set()
            await asyncio.wait_for(close, timeout=5)

    asyncio.run(scenario())


@pytest.mark.sqlite_only
@pytest.mark.timeout(15)
def test_broker_session_owner_retirement_orders_waiter_before_scope_close(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace, token, _ = _create_workspace(tmp_path, "selected")
    db = workspace / ".taut.db"
    second = TautClient(db_path=db, as_name="second")
    second.join("general")
    second_token = second.last_created_member
    assert second_token is not None and second_token.token is not None
    second.close()
    peer = TautClient(db_path=db, token=token, persistent=True)
    peer._meta_queue.has_pending()
    real_waiter_factory = core_watcher.create_activity_waiter_for_queues
    real_client_close = workspace_reactor.TautClient.close
    waiters: dict[int, Any] = {}
    close_order: list[bool] = []

    class RecordingWaiter:
        def __init__(self, delegate: Any) -> None:
            self.delegate = delegate
            self.closed = False

        def wait(self, timeout: float | None) -> bool:
            if self.delegate is None:
                return False
            return bool(self.delegate.wait(timeout))

        def close(self) -> None:
            self.closed = True
            if self.delegate is not None:
                self.delegate.close()

    def recording_waiter(*args: Any, **kwargs: Any) -> Any:
        delegate = real_waiter_factory(*args, **kwargs)
        waiter = RecordingWaiter(delegate)
        waiters[threading.get_ident()] = waiter
        return waiter

    def ordered_client_close(client: TautClient) -> None:
        waiter = waiters.get(threading.get_ident())
        if waiter is not None:
            close_order.append(waiter.closed)
        real_client_close(client)

    monkeypatch.setattr(
        core_watcher,
        "create_activity_waiter_for_queues",
        recording_waiter,
    )
    monkeypatch.setattr(workspace_reactor.TautClient, "close", ordered_client_close)

    async def scenario() -> None:
        reactor = ProcessReactor(asyncio.get_running_loop())
        with _tool_error(
            "workspace identity invalid; provide a valid existing continuity token"
        ):
            await reactor.attach_workspace(str(workspace), "taut-invalid-token")
        await async_eventually(
            lambda: not reactor._candidates,
            timeout=5,
            interval=0.01,
            description="failed MCP candidate is reaped",
        )

        attached = await reactor.attach_workspace(str(workspace), token)
        canonical = canonical_of(attached)
        with _tool_error("workspace already attached; detach to replace token"):
            await reactor.attach_workspace(canonical, second_token.token or "")
        await reactor.detach_workspace(canonical)

        await reactor.attach_workspace(str(workspace), token)
        await reactor.aclose()

    asyncio.run(scenario())

    assert close_order and all(close_order)
    peer_queue = peer.queue("mcp.peer.probe")
    peer_queue.write("peer survives MCP owner retirement")
    assert peer_queue.read() == "peer survives MCP owner retirement"
    peer.close()


def test_thread_start_failure_releases_hidden_candidate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """[MCP-4] Failed worker submission releases its hidden seat for retry."""

    workspace, token, _ = _create_workspace(tmp_path, "selected")

    async def scenario() -> None:
        reactor = ProcessReactor(asyncio.get_running_loop())
        real_new_owner = reactor._new_owner
        real_submit = reactor._executor.submit
        inbound: queue.Queue[workspace_reactor.WorkspaceControl] = queue.Queue()
        controls: list[workspace_reactor.WorkspaceControl] = []

        class AuditedOwner:
            wake = threading.Event()
            run = staticmethod(lambda: None)
            completion = None

            def __init__(self) -> None:
                self.inbound = inbound

            def send(self, control: workspace_reactor.WorkspaceControl) -> None:
                controls.append(control)
                self.inbound.put_nowait(control)

        def failed_owner(_: int) -> Any:
            return AuditedOwner()

        monkeypatch.setattr(reactor, "_new_owner", failed_owner)

        def fail_submit(*args: object, **kwargs: object) -> None:
            raise RuntimeError("synthetic submission failure")

        monkeypatch.setattr(reactor._executor, "submit", fail_submit)
        try:
            with pytest.raises(WorkspaceToolError) as raised:
                await reactor.attach_workspace(str(workspace), token)
            assert str(raised.value) == (
                "workspace attachment failed; use list_workspaces before retrying"
            )
            assert len(controls) == 1
            assert isinstance(controls[0], workspace_reactor.StopWorkspace)
            assert isinstance(inbound.get_nowait(), workspace_reactor.StopWorkspace)
            assert inbound.empty()
            assert reactor.list_workspaces()["records"] == []
            monkeypatch.setattr(reactor, "_new_owner", real_new_owner)
            monkeypatch.setattr(reactor._executor, "submit", real_submit)
            retried = await reactor.attach_workspace(str(workspace), token)
            assert retried["records"][0]["status"] == "ready"
        finally:
            await reactor.aclose()

    asyncio.run(scenario())


def test_owner_setup_failure_maps_to_fixed_attachment_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """[MCP-4]/[MCP-10] Pre-dispatch setup drops token and diagnostic detail."""

    async def scenario() -> None:
        reactor = ProcessReactor(asyncio.get_running_loop())

        def failed_owner(_: int) -> Any:
            raise RuntimeError("participant-controlled setup detail")

        monkeypatch.setattr(reactor, "_new_owner", failed_owner)

        def fail_submit(*args: object, **kwargs: object) -> None:
            raise RuntimeError("synthetic submission failure")

        monkeypatch.setattr(reactor._executor, "submit", fail_submit)
        try:
            with _tool_error(
                "workspace attachment failed; use list_workspaces before retrying"
            ):
                await reactor.attach_workspace(
                    str(tmp_path / "workspace"),
                    "participant-controlled-token",
                )
            assert reactor.list_workspaces()["records"] == []
            assert reactor._candidates == {}
        finally:
            await reactor.aclose()

    asyncio.run(scenario())


@pytest.mark.sqlite_only
@pytest.mark.timeout(10)
def test_direct_rejections_keep_fixed_errors(
    tmp_path: Path,
) -> None:
    """[MCP-4]/[MCP-10] Direct errors remain fixed and content-free."""

    workspace, token, _ = _create_workspace(tmp_path, "selected")

    async def scenario() -> None:
        reactor = ProcessReactor(asyncio.get_running_loop())
        try:
            relative_token = "relative-path-token"
            with pytest.raises(WorkspaceToolError) as relative:
                await reactor.attach_workspace("relative/path", relative_token)
            assert str(relative.value) == process_reactor.WORKSPACE_ABSOLUTE

            await reactor.attach_workspace(str(workspace), token)
            conflict_token = "different-token"
            with pytest.raises(WorkspaceToolError) as conflict:
                await reactor.attach_workspace(str(workspace), conflict_token)
            assert str(conflict.value) == process_reactor.WORKSPACE_CONFLICT

            canonical = str(workspace.resolve())
            reactor._entries[canonical].status = "identity_lost"
            reactor._entries[canonical].token = None
            degraded_token = "degraded-token"
            with pytest.raises(WorkspaceToolError) as degraded:
                await reactor.attach_workspace(canonical, degraded_token)
            assert str(degraded.value) == process_reactor.WORKSPACE_IDENTITY_LOST

            invalid_utf8_token = "invalid-\ud800-token"
            with pytest.raises(WorkspaceToolError) as invalid_utf8:
                await reactor.attach_workspace(canonical, invalid_utf8_token)
            assert str(invalid_utf8.value) == process_reactor.WORKSPACE_TOKEN_UTF8
            assert invalid_utf8.value.__context__ is None
        finally:
            await reactor.aclose()

    asyncio.run(scenario())


@pytest.mark.sqlite_only
@pytest.mark.timeout(10)
def test_fixed_attachment_rejections_pin_literal_recovery_text(
    tmp_path: Path,
) -> None:
    """[MCP-6]/[MCP-10] Attachment errors are fixed and content-free."""

    empty_workspace = tmp_path / "participant-controlled-empty-path"
    empty_workspace.mkdir()
    invalid_config = tmp_path / "participant-controlled-config-path"
    invalid_config.mkdir()
    (invalid_config / ".taut.toml").write_text("version = [", encoding="utf-8")
    workspace, token, _ = _create_workspace(tmp_path, "selected")
    invalid_reaction_workspace, invalid_reaction_token, _ = _create_workspace(
        tmp_path,
        "invalid-reaction",
    )
    (invalid_reaction_workspace / ".taut.toml").write_text(
        "\n".join(  # noqa: FLY002 approved [DOM-10.2.1] [RUFF-SUP-072] exception
            [
                "version = 1",
                'backend = "sqlite"',
                'target = ".taut.db"',
                "",
                "[reactions]",
                'values = ["Ack"]',
                "",
            ]
        ),
        encoding="utf-8",
    )

    async def scenario() -> None:
        reactor = ProcessReactor(asyncio.get_running_loop())
        try:
            with _tool_error(
                "workspace path must be absolute; provide an absolute workspace directory"
            ):
                await reactor.attach_workspace("relative/path", "secret-token")
            with _tool_error(
                "workspace path is not valid UTF-8; provide an absolute UTF-8 workspace path"
            ):
                await reactor.attach_workspace("/absolute/\ud800", "secret-token")
            with _tool_error(
                "workspace token is not valid UTF-8; provide a valid existing UTF-8 continuity token"
            ):
                await reactor.attach_workspace(str(workspace), "secret-\ud800")
            with _tool_error(
                "workspace project not found; initialize Taut there or choose another directory"
            ):
                await reactor.attach_workspace(
                    str(empty_workspace), "participant-controlled-token"
                )
            with _tool_error(
                "workspace project not found; initialize Taut there or choose another directory"
            ):
                await reactor.attach_workspace(
                    str(tmp_path / "participant-controlled-missing-path"),
                    "participant-controlled-token",
                )
            with _tool_error(
                "workspace configuration or backend unavailable; fix the workspace configuration or backend and retry"
            ):
                await reactor.attach_workspace(
                    str(invalid_config), "participant-controlled-token"
                )
            with _tool_error(
                "workspace configuration or backend unavailable; fix the workspace configuration or backend and retry"
            ):
                await reactor.attach_workspace(
                    str(invalid_reaction_workspace),
                    invalid_reaction_token,
                )
            with _tool_error(
                "workspace identity invalid; provide a valid existing continuity token"
            ):
                await reactor.attach_workspace(
                    str(workspace), "participant-controlled-invalid-token"
                )
            assert token not in " ".join(reactor.list_workspaces().get("warnings", []))
        finally:
            await reactor.aclose()

    asyncio.run(scenario())


@pytest.mark.sqlite_only
@pytest.mark.timeout(10)
def test_unrelated_client_validation_error_keeps_generic_attachment_mapping(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """[MCP-3] Only the two reaction-config diagnostics use config mapping."""

    workspace, token, _ = _create_workspace(tmp_path, "selected")

    def fail_client(*args: object, **kwargs: object) -> TautClient:
        del args, kwargs
        raise TautError("participant-controlled unrelated failure")

    monkeypatch.setattr(workspace_reactor, "TautClient", fail_client)

    async def scenario() -> None:
        reactor = ProcessReactor(asyncio.get_running_loop())
        try:
            with _tool_error(
                "workspace attachment failed; use list_workspaces before retrying"
            ):
                await reactor.attach_workspace(str(workspace), token)
        finally:
            await reactor.aclose()

    asyncio.run(scenario())


@pytest.mark.sqlite_only
@pytest.mark.timeout(10)
def test_directory_identity_failure_uses_fixed_attachment_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """[MCP-4]/[MCP-12] A real resolver stat failure fires its fixed class."""

    workspace, token, _ = _create_workspace(tmp_path, "selected")

    def fail_directory_stat(_: str) -> os.stat_result:
        raise OSError("participant-controlled stat detail")

    monkeypatch.setattr(workspace_reactor, "_directory_stat", fail_directory_stat)

    async def scenario() -> None:
        reactor = ProcessReactor(asyncio.get_running_loop())
        try:
            with _tool_error(
                "workspace directory identity unavailable; choose a workspace "
                "with stable directory identity"
            ):
                await reactor.attach_workspace(str(workspace), token)
            assert reactor.list_workspaces()["records"] == []
        finally:
            await reactor.aclose()

    asyncio.run(scenario())


@pytest.mark.sqlite_only
@pytest.mark.timeout(10)
def test_unexpected_resolution_crash_releases_hidden_candidate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """[MCP-4] Dead-owner fallback releases its hidden reservation."""

    workspace, token, _ = _create_workspace(tmp_path, "selected")
    TautClient.set_debug_capture(True, db_path=workspace / ".taut.db")

    def crash_resolution(_: str) -> Any:
        raise OSError("synthetic unexpected resolution crash")

    monkeypatch.setattr(workspace_reactor, "_resolve_workspace", crash_resolution)

    async def scenario() -> None:
        reactor = ProcessReactor(asyncio.get_running_loop())
        try:
            with _tool_error(
                "workspace attachment failed; use list_workspaces before retrying"
            ):
                await reactor.attach_workspace(str(workspace), token)
            assert reactor._candidates == {}
        finally:
            await reactor.aclose()

    asyncio.run(scenario())

    assert _debug_events(workspace) == []


@pytest.mark.sqlite_only
@pytest.mark.timeout(15)
def test_workspace_cap_counts_eight_persistent_children(tmp_path: Path) -> None:
    """[MCP-4] One connection admits no more than eight owner threads."""

    first_workspace, token, member_id = _create_workspace(tmp_path, "member_0")
    workspaces = [(first_workspace, token, member_id)]
    for index in range(1, 9):
        workspace = tmp_path / f"member_{index}"
        workspace.mkdir()
        shutil.copy2(first_workspace / ".taut.db", workspace / ".taut.db")
        workspaces.append((workspace, token, member_id))

    async def scenario() -> None:
        reactor = ProcessReactor(asyncio.get_running_loop())
        try:
            for workspace, token, _ in workspaces[:8]:
                await reactor.attach_workspace(str(workspace), token)
            workspace, token, _ = workspaces[8]
            with pytest.raises(WorkspaceToolError) as limited:
                await reactor.attach_workspace(str(workspace), token)
            assert str(limited.value) == (
                "workspace attachment limit reached; detach a workspace or wait "
                "for cleanup"
            )
            assert len(reactor.list_workspaces()["records"]) == 8
        finally:
            await reactor.aclose()

    asyncio.run(scenario())


@pytest.mark.sqlite_only
@pytest.mark.timeout(10)
def test_attach_is_idempotent_by_token_and_collapses_path_aliases(
    tmp_path: Path,
) -> None:
    """[MCP-4] Canonical path and directory identity prevent duplicate clients."""

    workspace, token, member_id = _create_workspace(tmp_path, "selected")
    second = TautClient(db_path=workspace / ".taut.db", as_name="other")
    second.join("general")
    second_member = second.last_created_member
    assert second_member is not None
    assert second_member.token is not None
    second.close()
    alias_same = tmp_path / "alias_same"
    alias_other = tmp_path / "alias_other"
    try:
        alias_same.symlink_to(workspace, target_is_directory=True)
        alias_other.symlink_to(workspace, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"directory symlinks unavailable: {exc}")

    async def scenario() -> None:
        reactor = ProcessReactor(asyncio.get_running_loop())
        try:
            first = await reactor.attach_workspace(str(workspace), token)
            repeated = await reactor.attach_workspace(str(workspace), token)
            aliased = await reactor.attach_workspace(str(alias_same), token)

            assert repeated == first
            assert aliased == first
            assert canonical_of(first) == os.path.realpath(workspace)
            assert first["records"][0]["member_id"] == member_id
            assert len(reactor.list_workspaces()["records"]) == 1
            with _tool_error("workspace already attached; detach to replace token"):
                await reactor.attach_workspace(
                    str(alias_other), second_member.token or ""
                )
        finally:
            await reactor.aclose()

    asyncio.run(scenario())


@pytest.mark.sqlite_only
@pytest.mark.timeout(15)
def test_concurrent_lazy_aliases_publish_only_one_client(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """[MCP-4] Two pre-publication aliases share one validation/client owner."""

    workspace, token, _ = _create_workspace(tmp_path, "selected")
    aliases = [tmp_path / "alias_one", tmp_path / "alias_two"]
    try:
        for alias in aliases:
            alias.symlink_to(workspace, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"directory symlinks unavailable: {exc}")

    resolution_barrier = threading.Barrier(2)
    validation_started = threading.Event()
    release_validation = threading.Event()
    validation_calls: list[int] = []
    real_resolve = workspace_reactor._resolve_workspace
    real_client = workspace_reactor.TautClient

    def synchronized_resolve(locator: str) -> Any:
        resolved = real_resolve(locator)
        resolution_barrier.wait(timeout=5)
        return resolved

    def counted_client(*args: object, **kwargs: Any) -> TautClient:
        validation_calls.append(threading.get_ident())
        validation_started.set()
        if not release_validation.wait(timeout=5):
            raise AssertionError("test did not release validation")
        return real_client(*args, **kwargs)

    monkeypatch.setattr(workspace_reactor, "_resolve_workspace", synchronized_resolve)
    monkeypatch.setattr(workspace_reactor, "TautClient", counted_client)

    async def scenario() -> None:
        reactor = ProcessReactor(asyncio.get_running_loop())
        calls = [
            asyncio.create_task(reactor.execute_tool(str(alias), token, "whoami", {}))
            for alias in aliases
        ]
        try:
            assert await asyncio.to_thread(validation_started.wait, 5)
            await async_eventually(
                lambda: any(call.done() for call in calls),
                timeout=5.0,
                interval=0.01,
                description="one concurrent alias attachment finishes",
                snapshot=lambda: {
                    "done_count": sum(call.done() for call in calls),
                    "total_count": len(calls),
                    "validation_call_count": len(validation_calls),
                },
            )
            completed = next(call for call in calls if call.done())
            with _tool_error("workspace busy; retry after backoff"):
                completed.result()
            assert len(validation_calls) == 1
            release_validation.set()
            results = await asyncio.gather(*calls, return_exceptions=True)
            successes = [item for item in results if isinstance(item, dict)]
            failures = [
                item for item in results if isinstance(item, WorkspaceToolError)
            ]
            assert len(successes) == 1
            assert len(failures) == 1
            assert str(failures[0]) == "workspace busy; retry after backoff"
            assert len(validation_calls) == 1
            listed = reactor.list_workspaces()["records"]
            assert len(listed) == 1
            assert listed[0]["workspace"] == os.path.realpath(workspace)
        finally:
            release_validation.set()
            await asyncio.gather(*calls, return_exceptions=True)
            await reactor.aclose()

    asyncio.run(scenario())


@pytest.mark.sqlite_only
@pytest.mark.timeout(10)
def test_attach_respects_workspace_local_sqlite_config(tmp_path: Path) -> None:
    """[MCP-2]/[MCP-4] SQLite attachment honors an explicit .taut.toml."""

    workspace = tmp_path / "configured"
    data = workspace / "state"
    data.mkdir(parents=True)
    db = data / "configured.sqlite"
    TautClient.init(db_path=db)
    selected = TautClient(db_path=db, as_name="configured_member")
    selected.join("general")
    member = selected.last_created_member
    assert member is not None
    assert member.token is not None
    selected.close()
    (workspace / ".taut.toml").write_text(
        'version = 1\nbackend = "sqlite"\ntarget = "state/configured.sqlite"\n',
        encoding="utf-8",
    )
    assert not (workspace / ".taut.db").exists()

    async def scenario() -> None:
        reactor = ProcessReactor(asyncio.get_running_loop())
        try:
            attached = await reactor.attach_workspace(
                str(workspace), member.token or ""
            )
            assert canonical_of(attached) == os.path.realpath(workspace)
            assert attached["records"][0] == {
                "backend": "sqlite",
                "member_id": member.member_id,
                "name": "configured_member",
                "status": "ready",
                "workspace": os.path.realpath(workspace),
            }
        finally:
            await reactor.aclose()

    asyncio.run(scenario())


@pytest.mark.sqlite_only
@pytest.mark.timeout(10)
def test_resolution_timeout_retires_candidate_without_publishing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """[MCP-4] Resolution timeout stops and later reaps only its candidate."""

    workspace, token, _ = _create_workspace(tmp_path, "selected")
    resolution_started = threading.Event()
    release_resolution = threading.Event()
    real_resolve = workspace_reactor._resolve_workspace

    def delayed_resolve(locator: str) -> tuple[Any, ...]:
        resolution_started.set()
        if not release_resolution.wait(timeout=5):
            raise AssertionError("test did not release resolution")
        return real_resolve(locator)

    monkeypatch.setattr(workspace_reactor, "_resolve_workspace", delayed_resolve)

    async def scenario() -> None:
        reactor = ProcessReactor(asyncio.get_running_loop())
        attach = asyncio.create_task(reactor.attach_workspace(str(workspace), token))
        assert await asyncio.to_thread(resolution_started.wait, 5)
        generation = next(iter(reactor._candidates))
        reactor._candidate_timeout(generation, "resolution")
        with _tool_error(
            "workspace resolution timed out; use list_workspaces then restart if warned"
        ):
            await attach
        assert reactor._candidates[generation].token is None
        assert reactor.list_workspaces()["records"] == []
        assert reactor.list_workspaces()["warnings"] == [
            "stalled attachment reservation exists; restart taut-mcp to clear"
        ]
        release_resolution.set()
        await async_eventually(
            lambda: not reactor._candidates,
            timeout=5.0,
            interval=0.01,
            description="timed-out resolution candidate is reaped",
            snapshot=lambda: {
                "candidate_count": len(reactor._candidates),
                "candidate_generations": sorted(reactor._candidates),
            },
        )
        await reactor.aclose()

    asyncio.run(scenario())


@pytest.mark.sqlite_only
@pytest.mark.timeout(10)
def test_hidden_candidate_uses_the_normative_routing_matrix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """[MCP-6] Hidden candidates are non-routable and lifecycle-busy."""

    workspace, token, _ = _create_workspace(tmp_path, "selected")
    resolution_started = threading.Event()
    release_resolution = threading.Event()
    real_resolve = workspace_reactor._resolve_workspace

    def delayed_resolve(locator: str) -> tuple[Any, ...]:
        resolution_started.set()
        if not release_resolution.wait(timeout=5):
            raise AssertionError("test did not release resolution")
        return real_resolve(locator)

    monkeypatch.setattr(workspace_reactor, "_resolve_workspace", delayed_resolve)

    async def scenario() -> None:
        reactor = ProcessReactor(asyncio.get_running_loop())
        attach = asyncio.create_task(reactor.attach_workspace(str(workspace), token))
        try:
            assert await asyncio.to_thread(resolution_started.wait, 5)
            with _tool_error("workspace busy; retry after backoff"):
                await reactor.execute_tool(str(workspace), token, "whoami", {})
            for tool_name in (
                "message_show",
                "message_delete",
                "message_react",
            ):
                with _tool_error("workspace busy; retry after backoff"):
                    await reactor.execute_tool(
                        str(workspace),
                        token,
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
                await reactor.attach_workspace(str(workspace), token)
            with _tool_error("workspace busy; retry after backoff"):
                await reactor.detach_workspace(str(workspace))
            release_resolution.set()
            attached = await attach
            assert attached["records"][0]["status"] == "ready"
        finally:
            release_resolution.set()
            await reactor.aclose()

    asyncio.run(scenario())


@pytest.mark.sqlite_only
@pytest.mark.timeout(10)
def test_detach_uses_distinct_five_second_deadline_and_final_liveness_check(
    tmp_path: Path,
) -> None:
    """[MCP-4] A dead owner at the deadline completes detach successfully."""

    assert process_reactor.DETACH_JOIN_SECONDS == 5.0
    workspace, token, _ = _create_workspace(tmp_path, "selected")

    async def scenario() -> None:
        loop = asyncio.get_running_loop()
        reactor = ProcessReactor(loop)
        attached = await reactor.attach_workspace(str(workspace), token)
        canonical = canonical_of(attached)
        entry = reactor._entries[canonical]
        real_wake = loop.call_soon_threadsafe

        def drop_wake(*_: object) -> None:
            return None

        loop.call_soon_threadsafe = drop_wake  # type: ignore[assignment]
        try:
            detach = asyncio.create_task(reactor.detach_workspace(canonical))
            await async_eventually(
                lambda: not entry.owner.alive(),
                timeout=5.0,
                interval=0.01,
                description="detach owner thread stops at the timeout boundary",
                snapshot=lambda: {
                    "owner_thread_alive": entry.owner.alive(),
                    "entry_status": entry.status,
                },
            )
            reactor._detach_timeout(canonical, entry.generation)
            result = await detach
            assert result["records"][0]["status"] == "detached"
            assert reactor.list_workspaces()["records"] == []
        finally:
            loop.call_soon_threadsafe = real_wake  # type: ignore[method-assign]
            await reactor.aclose()

    asyncio.run(scenario())


def test_closed_loop_wake_is_harmless_after_teardown() -> None:
    """[MCP-8] A closed loop is not recoverable by a timer on that loop."""
    loop = asyncio.new_event_loop()

    async def create_and_close() -> ProcessReactor:
        reactor = ProcessReactor(asyncio.get_running_loop())
        await reactor.aclose()
        return reactor

    reactor = loop.run_until_complete(create_and_close())
    loop.close()
    reactor._wake_master()


def test_completion_drains_events_before_quiet_owner_reap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """[MCP-8] Completion drains publication before inspecting retirement."""

    async def scenario() -> None:
        reactor = ProcessReactor(asyncio.get_running_loop())
        observed: list[str] = []
        original = reactor._drain_events

        def drain() -> None:
            observed.append("drain")
            original()

        monkeypatch.setattr(reactor, "_drain_events", drain)
        monkeypatch.setattr(
            reactor, "_reap_dead_owners", lambda: observed.append("reap")
        )
        reactor._drain_events()
        assert observed == ["drain", "reap"]
        await reactor.aclose()

    asyncio.run(scenario())


@pytest.mark.sqlite_only
@pytest.mark.timeout(10)
def test_validation_timeout_publishes_detachable_tombstone(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """[MCP-4] A granted client cannot overlap its timeout replacement."""

    workspace, token, _ = _create_workspace(tmp_path, "selected")
    validation_started = threading.Event()
    release_validation = threading.Event()
    real_client = workspace_reactor.TautClient

    def delayed_client(*args: object, **kwargs: Any) -> TautClient:
        client = real_client(*args, **kwargs)
        validation_started.set()
        if not release_validation.wait(timeout=5):
            raise AssertionError("test did not release validation")
        return client

    monkeypatch.setattr(workspace_reactor, "TautClient", delayed_client)

    async def scenario() -> None:
        reactor = ProcessReactor(asyncio.get_running_loop())
        attach = asyncio.create_task(reactor.attach_workspace(str(workspace), token))
        assert await asyncio.to_thread(validation_started.wait, 5)
        generation = next(iter(reactor._candidates))
        reactor._candidate_timeout(generation, "validation")
        with _tool_error("workspace attach timed out; use list_workspaces then detach"):
            await attach
        record = reactor.list_workspaces()["records"][0]
        assert reactor._entries[os.path.realpath(workspace)].token is None
        assert record == {
            "backend": "sqlite",
            "member_id": None,
            "name": None,
            "status": "reactor_failed",
            "workspace": os.path.realpath(workspace),
        }
        with _tool_error("workspace attach timed out; use list_workspaces then detach"):
            await reactor._execute_ready_tool(os.path.realpath(workspace), "whoami", {})
        with _tool_error("workspace attach timed out; use list_workspaces then detach"):
            await reactor.attach_workspace(os.path.realpath(workspace), token)
        release_validation.set()
        detached = await reactor.detach_workspace(os.path.realpath(workspace))
        assert detached["records"][0]["status"] == "detached"
        await reactor.aclose()

    asyncio.run(scenario())


@pytest.mark.sqlite_only
@pytest.mark.timeout(10)
def test_detach_timeout_becomes_retryable_reactor_failed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """[MCP-4] A stuck child keeps its seat until retry observes exit."""

    workspace, token, _ = _create_workspace(tmp_path, "selected")
    periodic_peek_started = threading.Event()
    release_periodic_peek = threading.Event()
    real_peek = workspace_reactor.TautClient.peek_inbox
    peek_calls = 0
    calls_lock = threading.Lock()

    def delayed_peek(self: TautClient, *, limit: int = 1000) -> Any:
        nonlocal peek_calls
        with calls_lock:
            peek_calls += 1
            call_number = peek_calls
        if call_number == 2:
            periodic_peek_started.set()
            if not release_periodic_peek.wait(timeout=5):
                raise AssertionError("test did not release periodic peek")
        return real_peek(self, limit=limit)

    monkeypatch.setattr(workspace_reactor.TautClient, "peek_inbox", delayed_peek)

    async def scenario() -> None:
        reactor = ProcessReactor(asyncio.get_running_loop())
        attached = await reactor.attach_workspace(str(workspace), token)
        canonical = canonical_of(attached)
        source = TautClient(db_path=workspace / ".taut.db")
        try:
            source.queue("taut.cache_stale").write("{}")
        finally:
            source.close()
        assert await asyncio.to_thread(periodic_peek_started.wait, 5)

        detach = asyncio.create_task(reactor.detach_workspace(canonical))
        await asyncio.sleep(0)
        entry = reactor._entries[canonical]
        assert entry.status == "detaching"
        with _tool_error("workspace busy; retry after backoff"):
            await reactor._execute_ready_tool(canonical, "whoami", {})
        with _tool_error("workspace busy; retry after backoff"):
            await reactor.attach_workspace(canonical, token)
        with _tool_error("workspace busy; retry after backoff"):
            await reactor.detach_workspace(canonical)
        reactor._detach_timeout(canonical, entry.generation)
        with _tool_error("workspace detach timed out; retry detach after backoff"):
            await detach
        assert reactor.list_workspaces()["records"][0]["status"] == "reactor_failed"
        assert reactor._entries[canonical].token is None
        with _tool_error("workspace reactor failed; detach and reattach"):
            await reactor._execute_ready_tool(canonical, "whoami", {})
        with _tool_error("workspace reactor failed; detach and reattach"):
            await reactor.attach_workspace(canonical, token)

        release_periodic_peek.set()
        await async_eventually(
            lambda: not entry.owner.alive(),
            timeout=5.0,
            interval=0.01,
            description="failed detach owner thread stops before retry",
            snapshot=lambda: {
                "owner_thread_alive": entry.owner.alive(),
                "entry_status": entry.status,
            },
        )
        detached = await reactor.detach_workspace(canonical)
        assert detached["records"][0]["status"] == "detached"
        await reactor.aclose()

    asyncio.run(scenario())


@pytest.mark.sqlite_only
@pytest.mark.timeout(10)
def test_source_hint_marks_lost_identity_then_retires_without_healing(
    tmp_path: Path,
) -> None:
    """[MCP-8] Losing the immutable token binding degrades the workspace."""

    workspace, token, member_id = _create_workspace(tmp_path, "selected")

    async def scenario() -> None:
        reactor = ProcessReactor(asyncio.get_running_loop())
        try:
            attached = await reactor.attach_workspace(str(workspace), token)
            canonical = canonical_of(attached)
            admin = TautClient(db_path=workspace / ".taut.db", as_name="selected")
            with admin._meta_queue.sidecar(transaction=True) as session:
                session.run(
                    "UPDATE taut_members SET token = NULL WHERE member_id = ?",
                    (member_id,),
                )
            admin.queue("taut.cache_stale").write("{}")
            admin.close()

            await async_eventually(
                lambda: (
                    reactor.list_workspaces()["records"][0]["status"] == "identity_lost"
                ),
                timeout=5.0,
                interval=0.01,
                description="periodic peek publishes identity-lost status",
                snapshot=lambda: {
                    "record_count": len(reactor.list_workspaces()["records"]),
                    "statuses": [
                        record["status"]
                        for record in reactor.list_workspaces()["records"]
                    ],
                },
            )
            await async_eventually(
                lambda: not reactor._entries[canonical].owner.alive(),
                timeout=5,
                description="identity-lost child retires",
            )
            reactor._drain_events()
            assert reactor._entries[canonical].status == "identity_lost"
            assert reactor._entries[canonical].token is None
            assert json.loads(reactor.current_text) == {
                "workspaces": [
                    {
                        "member_id": member_id,
                        "notifications": [],
                        "status": "identity_lost",
                        "truncated": False,
                        "workspace": canonical,
                    }
                ]
            }
            with _tool_error("workspace identity lost; detach and reattach"):
                await reactor._execute_ready_tool(canonical, "whoami", {})
            with _tool_error("workspace identity lost; detach and reattach"):
                await reactor.attach_workspace(canonical, token)
            detached = await reactor.detach_workspace(canonical)
            assert detached["records"][0]["status"] == "detached"
        finally:
            await reactor.aclose()

    asyncio.run(scenario())


@pytest.mark.sqlite_only
@pytest.mark.timeout(10)
def test_canceled_attach_waiter_does_not_cancel_started_child_lifecycle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """[MCP-4]/[MCP-5]/[MCP-10] Dispatch transfers token and child ownership."""

    workspace, token, _ = _create_workspace(tmp_path, "selected")
    validation_started = threading.Event()
    release_validation = threading.Event()
    real_client = workspace_reactor.TautClient

    def delayed_client(*args: object, **kwargs: Any) -> TautClient:
        client = real_client(*args, **kwargs)
        validation_started.set()
        if not release_validation.wait(timeout=5):
            raise AssertionError("test did not release validation")
        return client

    monkeypatch.setattr(workspace_reactor, "TautClient", delayed_client)

    async def scenario() -> None:
        reactor = ProcessReactor(asyncio.get_running_loop())
        attach = asyncio.create_task(reactor.attach_workspace(str(workspace), token))
        assert await asyncio.to_thread(validation_started.wait, 5)
        busy_token = "busy-token"
        with pytest.raises(WorkspaceToolError) as busy:
            await reactor.attach_workspace(str(workspace), busy_token)
        assert str(busy.value) == "workspace busy; retry after backoff"
        attach.cancel()
        with pytest.raises(asyncio.CancelledError):
            await attach

        release_validation.set()
        await async_eventually(
            lambda: bool(reactor.list_workspaces()["records"]),
            timeout=5.0,
            interval=0.01,
            description="canceled attach publishes the started workspace",
            snapshot=lambda: {
                "record_count": len(reactor.list_workspaces()["records"]),
                "statuses": [
                    record["status"] for record in reactor.list_workspaces()["records"]
                ],
            },
        )
        [record] = reactor.list_workspaces()["records"]
        assert record["status"] == "ready"
        identity_result = await reactor.execute_tool(
            str(record["workspace"]),
            token,
            "whoami",
            {},
        )
        assert identity_result["records"][0]["name"] == "selected"
        await reactor.aclose()

    asyncio.run(scenario())


@pytest.mark.sqlite_only
@pytest.mark.timeout(10)
def test_canceled_attach_retrieves_later_validation_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """[MCP-4]/[MCP-11] An abandoned ensure owns its fixed failure."""

    workspace, token, _ = _create_workspace(tmp_path, "selected")
    validation_started = threading.Event()
    release_validation = threading.Event()

    def failing_client(*_args: object, **_kwargs: Any) -> TautClient:
        validation_started.set()
        if not release_validation.wait(timeout=5):
            raise AssertionError("test did not release validation")
        raise RuntimeError("participant-controlled validation detail")

    monkeypatch.setattr(workspace_reactor, "TautClient", failing_client)

    async def scenario() -> None:
        loop = asyncio.get_running_loop()
        contexts: list[dict[str, Any]] = []
        loop.set_exception_handler(lambda _loop, context: contexts.append(context))
        reactor = ProcessReactor(loop)
        attach = asyncio.create_task(reactor.attach_workspace(str(workspace), token))
        assert await asyncio.to_thread(validation_started.wait, 5)
        attach.cancel()
        with pytest.raises(asyncio.CancelledError):
            await attach

        release_validation.set()
        await async_eventually(
            lambda: not reactor._candidates,
            timeout=5.0,
            interval=0.01,
            description="failed canceled attachment owner is reaped",
        )
        gc.collect()
        await asyncio.sleep(0)
        await reactor.aclose()

        assert contexts == []

    asyncio.run(scenario())


@pytest.mark.sqlite_only
@pytest.mark.timeout(10)
def test_canceled_lazy_ensure_publishes_without_admitting_domain_command(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """[MCP-4]/[MCP-5] Cancellation-first setup retains no domain command."""

    workspace, token, _ = _create_workspace(tmp_path, "selected")
    validation_started = threading.Event()
    release_validation = threading.Event()
    real_client = workspace_reactor.TautClient

    def delayed_client(*args: object, **kwargs: Any) -> TautClient:
        client = real_client(*args, **kwargs)
        validation_started.set()
        if not release_validation.wait(timeout=5):
            raise AssertionError("test did not release validation")
        return client

    monkeypatch.setattr(workspace_reactor, "TautClient", delayed_client)

    async def scenario() -> None:
        reactor = ProcessReactor(asyncio.get_running_loop())
        call = asyncio.create_task(
            reactor.execute_tool(
                str(workspace),
                token,
                "say",
                {"target": "general", "text": "must not be sent"},
            )
        )
        assert await asyncio.to_thread(validation_started.wait, 5)
        call.cancel()
        with pytest.raises(asyncio.CancelledError):
            await call

        release_validation.set()
        await async_eventually(
            lambda: bool(reactor.list_workspaces()["records"]),
            timeout=5.0,
            interval=0.01,
            description="canceled lazy tool publishes the started workspace",
            snapshot=lambda: {
                "record_count": len(reactor.list_workspaces()["records"]),
                "statuses": [
                    record["status"] for record in reactor.list_workspaces()["records"]
                ],
            },
        )
        canonical = str(reactor.list_workspaces()["records"][0]["workspace"])
        history = await reactor.execute_tool(
            canonical,
            token,
            "log",
            {"thread": "general", "since": None, "limit": 100},
        )
        assert all(
            record["text"] != "must not be sent" for record in history["records"]
        )
        await reactor.aclose()

    asyncio.run(scenario())


@pytest.mark.sqlite_only
@pytest.mark.timeout(10)
def test_normal_shutdown_does_not_report_child_fault(tmp_path: Path) -> None:
    """[MCP-11] Intentionally stopped owners are not child failures."""

    workspace, token, _ = _create_workspace(tmp_path, "selected")

    async def scenario() -> None:
        diagnostics: list[str] = []
        reactor = ProcessReactor(
            asyncio.get_running_loop(),
            diagnostic=diagnostics.append,
        )
        await reactor.attach_workspace(str(workspace), token)
        await reactor.aclose()
        assert diagnostics == []

    asyncio.run(scenario())


@pytest.mark.sqlite_only
def test_child_fault_is_isolated_and_reported_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """[MCP-11] One child fault degrades only its workspace and is diagnosed."""

    failed_workspace, failed_token, _ = _create_workspace(tmp_path, "failed")
    healthy_workspace, healthy_token, _ = _create_workspace(tmp_path, "healthy")
    TautClient.set_debug_capture(True, db_path=failed_workspace / ".taut.db")
    real_execute = workspace_reactor.execute_command

    def selective_crash(client: TautClient, name: str, arguments: Any) -> Any:
        if name == "say" and dict(arguments).get("text") == "trigger-child-fault":
            raise RuntimeError("participant-controlled secret")
        return real_execute(client, name, arguments)

    monkeypatch.setattr(workspace_reactor, "execute_command", selective_crash)

    async def scenario() -> None:
        diagnostics: list[str] = []
        reactor = ProcessReactor(
            asyncio.get_running_loop(),
            diagnostic=diagnostics.append,
        )
        try:
            failed = await reactor.attach_workspace(str(failed_workspace), failed_token)
            healthy = await reactor.attach_workspace(
                str(healthy_workspace), healthy_token
            )
            with _tool_error("workspace reactor failed; detach and reattach"):
                await reactor._execute_ready_tool(
                    canonical_of(failed),
                    "say",
                    {"target": "general", "text": "trigger-child-fault"},
                )

            records = {
                record["workspace"]: record
                for record in reactor.list_workspaces()["records"]
            }
            assert records[canonical_of(failed)]["status"] == "reactor_failed"
            assert records[canonical_of(healthy)]["status"] == "ready"
            result = await reactor._execute_ready_tool(
                canonical_of(healthy), "whoami", {}
            )
            assert result["records"][0]["name"] == "healthy"
            assert diagnostics == [
                "taut-mcp: workspace reactor failed; detach and reattach"
            ]
        finally:
            await reactor.aclose()

    asyncio.run(asyncio.wait_for(scenario(), timeout=10))

    events = _debug_events(failed_workspace)
    assert len(events) == 1
    assert events[0]["surface"] == "mcp"
    assert events[0]["operation"] == "workspace.command:say"
    assert events[0]["exception"]["message"] == "participant-controlled secret"


@pytest.mark.sqlite_only
@pytest.mark.timeout(10)
def test_refresh_crash_captures_after_runtime_enable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """[MCP-8] Resident workspaces read capture state at failure time."""

    workspace, token, _ = _create_workspace(tmp_path, "selected")
    fail_refresh = threading.Event()
    real_peek = workspace_reactor.TautClient.peek_inbox

    def failing_peek(self: TautClient, *, limit: int = 1000) -> Any:
        if fail_refresh.is_set():
            raise RuntimeError("refresh failed")
        return real_peek(self, limit=limit)

    monkeypatch.setattr(workspace_reactor.TautClient, "peek_inbox", failing_peek)

    async def scenario() -> None:
        reactor = ProcessReactor(asyncio.get_running_loop())
        try:
            attached = await reactor.attach_workspace(str(workspace), token)
            TautClient.set_debug_capture(True, db_path=workspace / ".taut.db")
            fail_refresh.set()
            with _tool_error("workspace reactor failed; detach and reattach"):
                await reactor._execute_ready_tool(
                    canonical_of(attached),
                    "whoami",
                    {},
                )
        finally:
            await reactor.aclose()

    asyncio.run(scenario())

    events = _debug_events(workspace)
    assert len(events) == 1
    assert events[0]["operation"] == "workspace.refresh"


@pytest.mark.sqlite_only
@pytest.mark.timeout(10)
def test_snapshot_crash_is_captured_before_content_free_workspace_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """[MCP-8] Periodic snapshot failure has its own stable operation label."""

    workspace, token, _ = _create_workspace(tmp_path, "selected")
    TautClient.set_debug_capture(True, db_path=workspace / ".taut.db")
    fail_snapshot = threading.Event()
    real_peek = workspace_reactor.TautClient.peek_inbox

    def failing_peek(self: TautClient, *, limit: int = 1000) -> Any:
        if fail_snapshot.is_set():
            raise RuntimeError("snapshot failed")
        return real_peek(self, limit=limit)

    monkeypatch.setattr(workspace_reactor.TautClient, "peek_inbox", failing_peek)

    async def scenario() -> None:
        reactor = ProcessReactor(asyncio.get_running_loop())
        try:
            await reactor.attach_workspace(str(workspace), token)
            fail_snapshot.set()
            source = TautClient(db_path=workspace / ".taut.db")
            try:
                source.queue("taut.cache_stale").write("{}")
            finally:
                source.close()
            await async_eventually(
                lambda: (
                    reactor.list_workspaces()["records"][0]["status"]
                    == "reactor_failed"
                ),
                timeout=3.0,
                description="snapshot crash publication",
            )
        finally:
            await reactor.aclose()

    asyncio.run(scenario())

    events = _debug_events(workspace)
    assert len(events) == 1
    assert events[0]["operation"] == "workspace.snapshot"


@pytest.mark.sqlite_only
@pytest.mark.timeout(10)
def test_outer_workspace_loop_crash_is_captured_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """[MCP-8] Unexpected reactor-loop failures retain workspace evidence."""

    workspace, token, _ = _create_workspace(tmp_path, "selected")
    TautClient.set_debug_capture(True, db_path=workspace / ".taut.db")
    real_run_cycle = workspace_reactor._WorkspaceReactor._process_reactor_turn

    def crash_after_ready(self: workspace_reactor._WorkspaceReactor) -> None:
        result = real_run_cycle(self)
        if self.client is not None:
            outer_local = "outer loop evidence"
            _ = outer_local
            del _
            raise RuntimeError("outer loop failed")
        return result

    monkeypatch.setattr(
        workspace_reactor._WorkspaceReactor,
        "_process_reactor_turn",
        crash_after_ready,
    )

    async def scenario() -> None:
        reactor = ProcessReactor(asyncio.get_running_loop())
        try:
            await reactor.attach_workspace(str(workspace), token)
            await async_eventually(
                lambda: (
                    reactor.list_workspaces()["records"][0]["status"]
                    == "reactor_failed"
                ),
                timeout=3.0,
                description="outer workspace crash publication",
            )
        finally:
            await reactor.aclose()

    asyncio.run(scenario())

    events = _debug_events(workspace)
    assert len(events) == 1
    assert events[0]["operation"] == "workspace.run"
    assert any(
        "outer loop evidence" in value
        for frame in events[0]["frames"]
        for value in frame["locals"].values()
    )


@pytest.mark.sqlite_only
@pytest.mark.timeout(10)
def test_workspace_crash_observes_runtime_disable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """[MCP-8] Disabling capture takes effect without a reactor restart."""

    workspace, token, _ = _create_workspace(tmp_path, "selected")
    TautClient.set_debug_capture(True, db_path=workspace / ".taut.db")

    def crash_command(client: TautClient, name: str, arguments: Any) -> Any:
        raise RuntimeError("disabled crash")

    monkeypatch.setattr(workspace_reactor, "execute_command", crash_command)

    async def scenario() -> None:
        reactor = ProcessReactor(asyncio.get_running_loop())
        try:
            attached = await reactor.attach_workspace(str(workspace), token)
            TautClient.set_debug_capture(False, db_path=workspace / ".taut.db")
            with _tool_error("workspace reactor failed; detach and reattach"):
                await reactor._execute_ready_tool(
                    canonical_of(attached),
                    "whoami",
                    {},
                )
        finally:
            await reactor.aclose()

    asyncio.run(scenario())

    assert _debug_events(workspace) == []


@pytest.mark.sqlite_only
@pytest.mark.timeout(10)
def test_shutdown_deadline_forces_isolated_process_exit(tmp_path: Path) -> None:
    """[MCP-3]/[MCP-11] A non-returning child cannot hang process teardown."""

    workspace, token, _ = _create_workspace(tmp_path, "selected")
    probe = """
import asyncio
import sys
import threading

from taut_mcp import _process_reactor as connection
from taut_mcp import _workspace_reactor as workspace

connection.SHUTDOWN_SECONDS = 0.1
started = threading.Event()
real_client = workspace.TautClient

def stuck_client(*args, **kwargs):
    client = real_client(*args, **kwargs)
    started.set()
    threading.Event().wait()
    return client

workspace.TautClient = stuck_client

async def main():
    reactor = connection.ProcessReactor(asyncio.get_running_loop())
    asyncio.create_task(reactor.attach_workspace(sys.argv[1], sys.argv[2]))
    if not await asyncio.to_thread(started.wait, 5):
        raise RuntimeError("validation did not start")
    await reactor.aclose()

asyncio.run(main())
"""

    completed = subprocess.run(
        [sys.executable, "-c", probe, str(workspace), token],
        cwd=Path(__file__).resolve().parents[1],
        text=True,
        capture_output=True,
        timeout=5,
        check=False,
    )

    assert completed.returncode == 1
    assert completed.stdout == ""
    assert "taut-mcp: shutdown deadline exceeded; forcing exit" in completed.stderr
    assert str(workspace) not in completed.stderr
    assert token not in completed.stderr


@pytest.mark.parametrize(
    "name", ["attach_workspace", "detach_workspace", "list_workspaces"]
)
def test_domain_dispatch_rejects_lifecycle_tools(tmp_path: Path, name: str) -> None:
    async def scenario() -> None:
        reactor = ProcessReactor(asyncio.get_running_loop())
        try:
            with pytest.raises(AssertionError, match="unregistered ordinary tool"):
                await reactor.execute_tool(str(tmp_path), "unused", name, {})
        finally:
            await reactor.aclose()

    asyncio.run(scenario())


@pytest.mark.sqlite_only
@pytest.mark.timeout(10)
def test_detach_waits_for_callable_return_without_retirement_polling(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """[MCP-8] Terminal publication precedes executor-owned completion."""
    workspace, token, _ = _create_workspace(tmp_path, "completion")
    returned = threading.Event()
    release = threading.Event()
    original = process_reactor.run_workspace_reactor

    def held_return(*args: Any) -> None:
        original(*args)
        returned.set()
        assert release.wait(5)

    monkeypatch.setattr(process_reactor, "run_workspace_reactor", held_return)

    async def scenario() -> None:
        loop = asyncio.get_running_loop()
        reactor = ProcessReactor(loop)
        try:
            canonical = canonical_of(
                await reactor.attach_workspace(str(workspace), token)
            )
            detach = asyncio.create_task(reactor.detach_workspace(canonical))
            assert await asyncio.to_thread(returned.wait, 3)
            reactor._drain_events()
            assert not detach.done()
            assert reactor._entries[canonical].owner.alive()
            release.set()
            result = await asyncio.wait_for(detach, 1)
            assert result["records"][0]["status"] == "detached"
        finally:
            release.set()
            await reactor.aclose()

    asyncio.run(scenario())


@pytest.mark.timeout(5)
def test_quiet_owner_return_settles_admission_without_clock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """[MCP-8] A callable that publishes nothing still has a completion event."""
    monkeypatch.setattr(process_reactor, "run_workspace_reactor", lambda *args: None)

    async def scenario() -> None:
        loop = asyncio.get_running_loop()
        reactor = ProcessReactor(loop)
        try:
            with _tool_error(workspace_reactor.ATTACHMENT_FAILED):
                await asyncio.wait_for(
                    reactor.attach_workspace(str(tmp_path / "missing"), "token"), 1
                )
            assert not reactor._candidates
        finally:
            await reactor.aclose()

    asyncio.run(scenario())


@pytest.mark.timeout(10)
def test_real_executor_start_failure_never_grants_failed_owner_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """[MCP-4] submit may enqueue work before native thread startup fails."""
    workspace, token, _ = _create_workspace(tmp_path, "retry")
    resolved: list[str] = []
    real_resolve = workspace_reactor._resolve_workspace

    def resolve(locator: str) -> Any:
        resolved.append(locator)
        return real_resolve(locator)

    monkeypatch.setattr(workspace_reactor, "_resolve_workspace", resolve)
    real_start = threading.Thread.start
    fail_once = True

    def start(thread: threading.Thread) -> None:
        nonlocal fail_once
        if thread.name.startswith("taut-mcp-workspace") and fail_once:
            fail_once = False
            raise RuntimeError("native thread startup failed")
        real_start(thread)

    monkeypatch.setattr(threading.Thread, "start", start)

    async def scenario() -> None:
        reactor = ProcessReactor(asyncio.get_running_loop())
        owners: list[Any] = []
        real_new_owner = reactor._new_owner

        def new_owner(generation: int) -> Any:
            owner = real_new_owner(generation)
            owners.append(owner)
            return owner

        monkeypatch.setattr(reactor, "_new_owner", new_owner)
        try:
            with _tool_error(workspace_reactor.ATTACHMENT_FAILED):
                await reactor.attach_workspace(str(tmp_path / "missing"), "secret")
            attached = await asyncio.wait_for(
                reactor.attach_workspace(str(workspace), token), 2
            )
            assert attached["records"][0]["status"] == "ready"
            assert resolved == [str(workspace)]
            assert len(owners) == 2
            assert not reactor._candidates
        finally:
            # Rescue the pre-fix library work item if the assertion above fails.
            for owner in owners:
                owner.send(workspace_reactor.StopWorkspace(1))
            await reactor.aclose()
            reactor._executor.shutdown(wait=False, cancel_futures=True)

    asyncio.run(scenario())


@pytest.mark.timeout(10)
def test_failed_submit_can_already_be_running_without_workspace_authority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """[MCP-4] An existing worker may claim a task before new-worker failure."""
    workspace, token, _ = _create_workspace(tmp_path, "existing")
    entered = threading.Event()
    resolved: list[str] = []
    real_resolve = workspace_reactor._resolve_workspace

    def resolve(locator: str) -> Any:
        resolved.append(locator)
        return real_resolve(locator)

    monkeypatch.setattr(workspace_reactor, "_resolve_workspace", resolve)

    async def scenario() -> None:
        reactor = ProcessReactor(asyncio.get_running_loop())
        try:
            attached = await reactor.attach_workspace(str(workspace), token)
            first = reactor._entries[canonical_of(attached)]
            real_new_owner = reactor._new_owner

            def new_owner(generation: int) -> Any:
                owner = real_new_owner(generation)
                run = owner.run

                def entered_run() -> None:
                    entered.set()
                    run()

                owner.run = entered_run
                return owner

            monkeypatch.setattr(reactor, "_new_owner", new_owner)
            real_start = threading.Thread.start

            def fail_second_worker(thread: threading.Thread) -> None:
                if thread.name.startswith("taut-mcp-workspace"):
                    first.owner.send(workspace_reactor.StopWorkspace(first.generation))
                    assert entered.wait(3)
                    raise RuntimeError("native thread startup failed")
                real_start(thread)

            monkeypatch.setattr(threading.Thread, "start", fail_second_worker)
            with _tool_error(workspace_reactor.ATTACHMENT_FAILED):
                await reactor.attach_workspace(
                    str(tmp_path / "never-resolve"), "secret"
                )
            assert entered.is_set()
            assert resolved == [str(workspace)]
            monkeypatch.setattr(threading.Thread, "start", real_start)
        finally:
            await reactor.aclose()

    asyncio.run(scenario())


@pytest.mark.sqlite_only
@pytest.mark.timeout(20)
def test_fifo_terminal_settlement_and_detach_after_queued_cancel(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """[MCP-5] Terminal child failure settles active + all queued commands; detach checks uncancelled queued slots."""

    workspace, token, _ = _create_workspace(tmp_path, "selected")
    hold_cmd = threading.Event()
    started_cmd = threading.Event()
    crash_cmd = threading.Event()
    real_execute = workspace_reactor.execute_command

    def controlled_execute(client: TautClient, name: str, arguments: Any) -> Any:
        started_cmd.set()
        assert hold_cmd.wait(timeout=10)
        if crash_cmd.is_set():
            raise RuntimeError("boom inside child command")
        return real_execute(client, name, arguments)

    monkeypatch.setattr(workspace_reactor, "execute_command", controlled_execute)

    async def scenario() -> None:
        diagnostics: list[str] = []
        reactor = ProcessReactor(
            asyncio.get_running_loop(), diagnostic=diagnostics.append
        )
        try:
            canonical = str(
                canonical_of(await reactor.attach_workspace(str(workspace), token))
            )

            # Active + 1 queued -> detach fails; cancel queued + finish active -> detach succeeds!
            active1 = asyncio.create_task(
                reactor._execute_ready_tool(canonical, "whoami", {})
            )
            assert await asyncio.to_thread(started_cmd.wait, 5)
            queued1 = asyncio.create_task(
                reactor._execute_ready_tool(canonical, "inbox", {"limit": 1})
            )
            await asyncio.sleep(0)
            with _tool_error("workspace busy; retry after backoff"):
                await reactor.detach_workspace(canonical)
            queued1.cancel()
            hold_cmd.set()
            await active1
            with pytest.raises(asyncio.CancelledError):
                await queued1
            detached = await reactor.detach_workspace(canonical)
            assert detached["records"][0]["status"] == "detached"

            # Reattach, saturate active + 3 queued, trigger child crash -> all 4 settle with reactor_failed!
            hold_cmd.clear()
            started_cmd.clear()
            crash_cmd.set()
            canonical = str(
                canonical_of(await reactor.attach_workspace(str(workspace), token))
            )
            active2 = asyncio.create_task(
                reactor._execute_ready_tool(canonical, "whoami", {})
            )
            assert await asyncio.to_thread(started_cmd.wait, 5)
            queued_crash = [
                asyncio.create_task(
                    reactor._execute_ready_tool(canonical, "inbox", {"limit": idx})
                )
                for idx in range(1, 4)
            ]
            await asyncio.sleep(0)
            hold_cmd.set()

            for task in (active2, *queued_crash):
                with _tool_error("workspace reactor failed; detach and reattach"):
                    await task
            assert diagnostics
        finally:
            hold_cmd.set()
            await reactor.aclose()

    asyncio.run(scenario())


def _instrument_grant_reactor(
    monkeypatch: pytest.MonkeyPatch,
    defaults: Any,
    grants: list[int],
) -> ProcessReactor:
    r = ProcessReactor(asyncio.get_running_loop(), defaults=defaults)
    orig_r_new_owner = r._new_owner

    def wrapped_new_owner(generation: int) -> Any:
        owner = orig_r_new_owner(generation)
        orig_put = owner.inbound.put_nowait

        def tracked_put(control: Any) -> None:
            if isinstance(control, workspace_reactor.GrantValidation):
                grants.append(control.generation)
            orig_put(control)

        monkeypatch.setattr(owner.inbound, "put_nowait", tracked_put)
        return owner

    monkeypatch.setattr(r, "_new_owner", wrapped_new_owner)
    return r


@pytest.mark.sqlite_only
@pytest.mark.timeout(25)
def test_launch_defaults_as_selector_and_symlink_retarget_matrix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """[MCP-3]/[MCP-4]/[MCP-6] --as selector (R3.2), resident symlink retarget (R2.3), and empty-string guards."""

    from taut_mcp.cli import McpLaunchDefaults

    (tmp_path / "proj_a").mkdir()
    (tmp_path / "proj_b").mkdir()
    ws_a, claude_tok_a, _ = _create_workspace(tmp_path / "proj_a", "claude")
    bob_client_a = TautClient(db_path=ws_a / ".taut.db", as_name="bob")
    try:
        bob_client_a.join("general")
        assert bob_client_a.last_created_member is not None
        assert bob_client_a.last_created_member.token is not None
        bob_tok_a = bob_client_a.last_created_member.token
    finally:
        bob_client_a.close()

    ws_b, _claude_tok_b, _ = _create_workspace(tmp_path / "proj_b", "claude")
    b_admin = TautClient(db_path=ws_b / ".taut.db", as_name="claude")
    try:
        with b_admin._meta_queue.sidecar(transaction=True) as session:
            session.run(
                "UPDATE taut_members SET token = ? WHERE name_key = 'claude'",
                (claude_tok_a,),
            )
    finally:
        b_admin.close()
    bob_client_b = TautClient(db_path=ws_b / ".taut.db", as_name="bob_b")
    try:
        bob_client_b.join("general")
        assert bob_client_b.last_created_member is not None
        assert bob_client_b.last_created_member.token is not None
        bob_tok_b = bob_client_b.last_created_member.token
    finally:
        bob_client_b.close()

    symlink = tmp_path / "default_link"
    symlink.symlink_to(ws_a)
    grants: list[int] = []

    async def scenario() -> None:
        r_as = _instrument_grant_reactor(
            monkeypatch, McpLaunchDefaults(as_name="claude"), grants
        )
        try:
            att1 = await r_as.attach_workspace(str(ws_a), claude_tok_a)
            assert len(grants) == 1
            assert (await r_as.attach_workspace(canonical_of(att1), None)) == att1
            assert (await r_as.attach_workspace(str(symlink), None)) == att1
            assert len(grants) == 1
            await async_eventually(
                lambda: not r_as._candidates,
                timeout=5.0,
                interval=0.01,
                description="alias candidate reaped after symlink attach",
            )

            with _tool_error("workspace already attached; detach to replace token"):
                await r_as.attach_workspace(canonical_of(att1), bob_tok_a)
            with _tool_error("workspace already attached; detach to replace token"):
                await r_as.attach_workspace(str(symlink), bob_tok_a)
            assert len(grants) == 1
            await async_eventually(
                lambda: not r_as._candidates,
                timeout=5.0,
                interval=0.01,
                description="alias candidate reaped after rejected symlink attach",
            )

            await r_as.detach_workspace(canonical_of(att1))
            await r_as.attach_workspace(str(ws_a), bob_tok_a)
            assert len(grants) == 2
            with _tool_error("workspace already attached; detach to replace token"):
                await r_as.attach_workspace(canonical_of(att1), None)
            with _tool_error("workspace already attached; detach to replace token"):
                await r_as.attach_workspace(str(symlink), None)
            assert len(grants) == 2
            await async_eventually(
                lambda: not r_as._candidates,
                timeout=5.0,
                interval=0.01,
                description="alias candidate reaped before close",
            )
        finally:
            await r_as.aclose()

        grants.clear()
        r_res = _instrument_grant_reactor(
            monkeypatch,
            McpLaunchDefaults(workspace=str(symlink), token=claude_tok_a),
            grants,
        )
        try:
            att_a = await r_res.attach_workspace(str(ws_a), claude_tok_a)
            canon_a = canonical_of(att_a)
            assert len(grants) == 1
            assert (await r_res.attach_workspace(None, None)) == att_a
            assert (await r_res.attach_workspace(canon_a, None)) == att_a
            assert len(grants) == 1

            with _tool_error(
                "workspace path must be absolute; provide an absolute workspace directory"
            ):
                await r_res.attach_workspace("", None)
            with _tool_error(
                "workspace identity invalid; provide a valid existing continuity token"
            ):
                await r_res.attach_workspace(None, "")
            assert await r_res.detach_workspace("") == {"records": []}
            assert canon_a in r_res._entries
            assert len(grants) == 1

            symlink.unlink()
            symlink.symlink_to(ws_b)
            with _tool_error(
                "workspace token required for non-default workspace; supply token or use the configured default workspace"
            ):
                await r_res.attach_workspace(str(ws_b), None)
            assert len(grants) == 1
            await async_eventually(
                lambda: not r_res._candidates,
                timeout=5.0,
                interval=0.01,
                description="rejected ws_b candidate reaped",
            )

            att_b2 = await r_res.attach_workspace(str(ws_b), bob_tok_b)
            assert r_res._entries[canonical_of(att_b2)].is_default_workspace is False
            assert (await r_res.execute_tool(None, None, "whoami", {}))["records"][0][
                "name"
            ] == "claude"

            det_a = await r_res.detach_workspace(None)
            assert det_a["records"][0]["workspace"] == canon_a
            await r_res.detach_workspace(canonical_of(att_b2))
            att_b_default = await r_res.attach_workspace(None, None)
            assert canonical_of(att_b_default) == str(ws_b.resolve())
        finally:
            await r_res.aclose()

    asyncio.run(scenario())


@pytest.mark.sqlite_only
@pytest.mark.timeout(25)
def test_launch_defaults_overlapping_validation_and_resolution_race(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """[MCP-3]/[MCP-4] Overlapping validation and resolution races across symlink retarget (R3.1) plus timeout tombstone detach."""

    from taut_mcp.cli import McpLaunchDefaults

    (tmp_path / "proj_a").mkdir()
    (tmp_path / "proj_b").mkdir()
    ws_a, claude_tok_a, _ = _create_workspace(tmp_path / "proj_a", "claude")
    sub_a = ws_a / "subdir"
    sub_a.mkdir()
    ws_b, _claude_tok_b, _ = _create_workspace(tmp_path / "proj_b", "claude")
    b_admin = TautClient(db_path=ws_b / ".taut.db", as_name="claude")
    try:
        with b_admin._meta_queue.sidecar(transaction=True) as session:
            session.run(
                "UPDATE taut_members SET token = ? WHERE name_key = 'claude'",
                (claude_tok_a,),
            )
    finally:
        b_admin.close()
    bob_client_b = TautClient(db_path=ws_b / ".taut.db", as_name="bob_b")
    try:
        bob_client_b.join("general")
        assert bob_client_b.last_created_member is not None
        assert bob_client_b.last_created_member.token is not None
        bob_tok_b = bob_client_b.last_created_member.token
    finally:
        bob_client_b.close()

    symlink = tmp_path / "default_link"
    symlink.symlink_to(ws_a)
    grants: list[int] = []

    async def exercise_overlapping_validation() -> None:
        hold_val_a = threading.Event()
        entered_val_a = threading.Event()
        real_validate = workspace_reactor._validate_candidate

        def gated_validate(token: str | None, *args: Any, **kwargs: Any) -> Any:
            target = kwargs["target"]
            if Path(str(target.target)).resolve() == (ws_a / ".taut.db").resolve():
                entered_val_a.set()
                assert hold_val_a.wait(timeout=10)
            return real_validate(token, *args, **kwargs)

        with monkeypatch.context() as vpatch:
            vpatch.setattr(workspace_reactor, "_validate_candidate", gated_validate)
            r_ov = _instrument_grant_reactor(
                vpatch,
                McpLaunchDefaults(workspace=str(symlink), token=claude_tok_a),
                grants,
            )
            try:
                task_a = asyncio.create_task(
                    r_ov.attach_workspace(str(sub_a), claude_tok_a)
                )
                assert await asyncio.to_thread(entered_val_a.wait, 5)
                assert len(grants) == 1

                symlink.unlink()
                symlink.symlink_to(ws_b)

                with _tool_error("workspace busy; retry after backoff"):
                    await r_ov.attach_workspace(None, None)
                with _tool_error("workspace busy; retry after backoff"):
                    await r_ov.execute_tool(None, None, "whoami", {})
                with _tool_error("workspace busy; retry after backoff"):
                    await r_ov.detach_workspace(None)
                assert len(grants) == 1

                with _tool_error(
                    "workspace token required for non-default workspace; supply token or use the configured default workspace"
                ):
                    await r_ov.attach_workspace(str(ws_b), None)
                assert len(grants) == 1
                await async_eventually(
                    lambda: set(r_ov._candidates) == {1},
                    timeout=5.0,
                    interval=0.01,
                    description="rejected ws_b candidate reaped",
                )

                att_b = await r_ov.attach_workspace(str(ws_b), bob_tok_b)
                assert r_ov._entries[canonical_of(att_b)].is_default_workspace is False
                assert len(grants) == 2

                r_ov._candidate_timeout(1, "validation")
                with _tool_error(
                    "workspace attach timed out; use list_workspaces then detach"
                ):
                    await task_a
                hold_val_a.set()
                await async_eventually(
                    lambda: not r_ov._entries[str(ws_a.resolve())].owner.alive(),
                    timeout=5.0,
                    interval=0.01,
                    description="timed out A owner exited",
                )
                detached_tombstone = await r_ov.detach_workspace(None)
                assert detached_tombstone["records"][0]["workspace"] == str(
                    ws_a.resolve()
                )
            finally:
                hold_val_a.set()
                await r_ov.aclose()

    async def exercise_resolution_race() -> None:
        grants.clear()
        symlink.unlink()
        symlink.symlink_to(ws_a)
        hold_res_link = threading.Event()
        entered_res_link = threading.Event()
        real_res_ws = workspace_reactor._resolve_workspace
        link_calls = 0
        link_lock = threading.Lock()

        def gated_res(locator: str) -> Any:
            nonlocal link_calls
            if locator == str(symlink):
                with link_lock:
                    link_calls += 1
                    call_num = link_calls
                if call_num == 1:
                    entered_res_link.set()
                    assert hold_res_link.wait(timeout=10)
            return real_res_ws(locator)

        with monkeypatch.context() as rpatch:
            rpatch.setattr(workspace_reactor, "_resolve_workspace", gated_res)
            r_race = _instrument_grant_reactor(
                rpatch,
                McpLaunchDefaults(workspace=str(symlink), token=claude_tok_a),
                grants,
            )
            try:
                omitted_call = asyncio.create_task(r_race.attach_workspace(None, None))
                assert await asyncio.to_thread(entered_res_link.wait, 5)
                att_a_race = await r_race.attach_workspace(str(ws_a), claude_tok_a)
                assert len(grants) == 1
                symlink.unlink()
                symlink.symlink_to(ws_b)
                hold_res_link.set()
                with _tool_error("workspace busy; retry after backoff"):
                    await omitted_call
                assert len(grants) == 1
                assert (await r_race.attach_workspace(None, None)) == att_a_race
            finally:
                hold_res_link.set()
                await r_race.aclose()

    async def scenario() -> None:
        await exercise_overlapping_validation()
        await exercise_resolution_race()

    asyncio.run(scenario())


@pytest.mark.sqlite_only
@pytest.mark.timeout(20)
def test_launch_defaults_uninitialized_and_older_broker_non_mutation(
    tmp_path: Path,
) -> None:
    """[MCP-4] 0-byte and older-version broker-only SQLite targets are never mutated under --as or --token (R2.4)."""

    import sqlite3

    from simplebroker import Queue

    from taut_mcp.cli import McpLaunchDefaults

    zero_dir = tmp_path / "zero_ws"
    zero_dir.mkdir()
    zero_db = zero_dir / ".taut.db"
    zero_db.write_bytes(b"")

    old_dir = tmp_path / "old_broker_ws"
    old_dir.mkdir()
    old_db = old_dir / ".taut.db"
    with sqlite3.connect(old_db) as conn:
        conn.execute("PRAGMA journal_mode=DELETE")
        conn.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value BLOB NOT NULL)")
        conn.execute("INSERT INTO meta (key, value) VALUES ('schema_version', '1')")
        conn.commit()
    old_bytes_before = old_db.read_bytes()

    cur_broker_dir = tmp_path / "cur_broker_ws"
    cur_broker_dir.mkdir()
    cur_broker_db = cur_broker_dir / ".taut.db"
    q = Queue("plain", db_path=str(cur_broker_db))
    try:
        q.write("item")
    finally:
        q.close()
    cur_bytes_before = cur_broker_db.read_bytes()

    async def scenario() -> None:
        for defaults in (
            McpLaunchDefaults(as_name="claude"),
            McpLaunchDefaults(workspace=str(old_dir), token="tok_any"),
        ):
            r_ro = ProcessReactor(asyncio.get_running_loop(), defaults=defaults)

            def candidates_reaped(reactor: ProcessReactor = r_ro) -> bool:
                return not reactor._candidates

            try:
                tok_arg = None if defaults.as_name else "tok_any"
                for ws_dir in (zero_dir, old_dir, cur_broker_dir):
                    with _tool_error(
                        "workspace project not found; initialize Taut there or choose another directory"
                    ):
                        await r_ro.execute_tool(str(ws_dir), tok_arg, "whoami", {})
                    await async_eventually(
                        candidates_reaped,
                        timeout=5.0,
                        interval=0.01,
                        description="failed candidate reaped",
                    )
                    with _tool_error(
                        "workspace project not found; initialize Taut there or choose another directory"
                    ):
                        await r_ro.execute_tool(
                            str(ws_dir),
                            tok_arg,
                            "channel_show",
                            {"channel": "general"},
                        )
                    await async_eventually(
                        candidates_reaped,
                        timeout=5.0,
                        interval=0.01,
                        description="failed candidate reaped",
                    )
            finally:
                await r_ro.aclose()

        assert zero_db.read_bytes() == b""
        assert old_db.read_bytes() == old_bytes_before
        assert cur_broker_db.read_bytes() == cur_bytes_before

    asyncio.run(scenario())


@pytest.mark.sqlite_only
@pytest.mark.timeout(25)
def test_launch_defaults_resident_handoff_slow_default_isolation_cold_as_and_utf8_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """[MCP-4] Regression coverage for F1 (resident default handoff), F2 (cold --as broker metadata), F5 (slow default isolation), and F6 (UTF-8 check order)."""

    import sqlite3

    from taut_mcp.cli import McpLaunchDefaults

    (tmp_path / "proj_a").mkdir()
    (tmp_path / "proj_b").mkdir()
    (tmp_path / "proj_c").mkdir()
    ws_a, claude_tok_a, _ = _create_workspace(tmp_path / "proj_a", "claude")
    ws_b, _claude_tok_b, _ = _create_workspace(tmp_path / "proj_b", "claude")
    ws_c, claude_tok_c, _ = _create_workspace(tmp_path / "proj_c", "claude")
    b_admin = TautClient(db_path=ws_b / ".taut.db", as_name="claude")
    try:
        with b_admin._meta_queue.sidecar(transaction=True) as session:
            session.run(
                "UPDATE taut_members SET token = ? WHERE name_key = 'claude'",
                (claude_tok_a,),
            )
    finally:
        b_admin.close()

    # Cold initialized workspace with zero members joined and forced stale proof cookie (F2).
    cold_ws = tmp_path / "cold_init_ws"
    cold_ws.mkdir()
    cold_db = cold_ws / ".taut.db"
    TautClient.init(db_path=cold_db)
    with sqlite3.connect(cold_db) as conn:
        init_meta = dict(conn.execute("SELECT key, value FROM meta").fetchall())
        init_cookie = conn.execute("PRAGMA schema_version").fetchone()[0]
        assert int(init_meta["schema_proof_cookie"]) == init_cookie
        conn.execute("UPDATE meta SET value = 6 WHERE key = 'schema_proof_cookie'")
        conn.commit()
        cold_meta_before = dict(conn.execute("SELECT key, value FROM meta").fetchall())

    symlink = tmp_path / "default_link"
    symlink.symlink_to(ws_a)
    grants: list[int] = []

    async def exercise_resident_default_handoff(defaults: McpLaunchDefaults) -> None:
        grants.clear()
        symlink.unlink(missing_ok=True)
        symlink.symlink_to(ws_a)
        reactor = _instrument_grant_reactor(monkeypatch, defaults, grants)
        try:
            # Attach B explicitly while symlink points to A (no default owner resident).
            att_b = await reactor.attach_workspace(str(ws_b), claude_tok_a)
            canon_b = canonical_of(att_b)
            assert reactor._entries[canon_b].is_default_workspace is False
            assert len(grants) == 1

            # Retarget symlink to already-resident B with no default owner remaining (F1).
            symlink.unlink()
            symlink.symlink_to(ws_b)
            bound = await reactor.attach_workspace(None, None)
            assert bound == att_b
            assert len(grants) == 1
            assert reactor._entries[canon_b].is_default_workspace is True
            await async_eventually(
                lambda: not reactor._candidates,
                timeout=5.0,
                interval=0.01,
                description="handoff candidate reaped",
            )

            # Subsequent retarget to C stays pinned to B, and omitted detach removes B.
            symlink.unlink()
            symlink.symlink_to(ws_c)
            assert (await reactor.attach_workspace(None, None)) == att_b
            detached = await reactor.detach_workspace(None)
            assert detached["records"][0]["workspace"] == canon_b
        finally:
            await reactor.aclose()

    async def exercise_slow_default_isolation() -> None:
        symlink.unlink(missing_ok=True)
        symlink.symlink_to(ws_a)
        hold_default = threading.Event()
        default_calls = 0
        call_lock = threading.Lock()
        real_res_ws = workspace_reactor._resolve_workspace

        def slow_default_res(locator: str) -> Any:
            nonlocal default_calls
            if locator == str(symlink):
                with call_lock:
                    default_calls += 1
                hold_default.wait(timeout=10)
            return real_res_ws(locator)

        # 1) Unpinned default: hung default filesystem does not block explicit ws_c attach (F5).
        with monkeypatch.context() as spatch:
            spatch.setattr(workspace_reactor, "_resolve_workspace", slow_default_res)
            r_unpinned = ProcessReactor(
                asyncio.get_running_loop(),
                defaults=McpLaunchDefaults(workspace=str(symlink), token=claude_tok_a),
            )
            try:
                att_c = await asyncio.wait_for(
                    r_unpinned.attach_workspace(str(ws_c), claude_tok_c),
                    timeout=3.0,
                )
                assert canonical_of(att_c) == str(ws_c.resolve())
            finally:
                hold_default.set()
                await r_unpinned.aclose()

        # 2) Pinned default: explicit ws_c attach performs zero _resolve_workspace(symlink) calls (F5).
        hold_default.clear()
        r_pinned = ProcessReactor(
            asyncio.get_running_loop(),
            defaults=McpLaunchDefaults(workspace=str(symlink), token=claude_tok_a),
        )
        try:
            await r_pinned.attach_workspace(None, None)
            with call_lock:
                default_calls = 0
            with monkeypatch.context() as ppatch:
                ppatch.setattr(
                    workspace_reactor, "_resolve_workspace", slow_default_res
                )
                att_c2 = await asyncio.wait_for(
                    r_pinned.attach_workspace(str(ws_c), claude_tok_c),
                    timeout=3.0,
                )
                assert canonical_of(att_c2) == str(ws_c.resolve())
                assert default_calls == 0
        finally:
            hold_default.set()
            await r_pinned.aclose()

    async def exercise_cold_as_and_utf8_order() -> None:
        # F2: unsuccessful --as probe on cold initialized workspace never rewrites meta.
        r_cold = ProcessReactor(
            asyncio.get_running_loop(),
            defaults=McpLaunchDefaults(
                workspace=str(cold_ws), as_name="missing_claude"
            ),
        )
        try:
            with _tool_error(
                "workspace identity invalid; ensure the configured --as member exists or provide a valid existing continuity token"
            ):
                await r_cold.execute_tool(None, None, "whoami", {})
        finally:
            await r_cold.aclose()
        with sqlite3.connect(cold_db) as conn:
            cold_meta_after = dict(
                conn.execute("SELECT key, value FROM meta").fetchall()
            )
        assert cold_meta_after == cold_meta_before

        # F6: strict UTF-8 checks for workspace then token precede path absoluteness.
        r_utf8 = ProcessReactor(asyncio.get_running_loop())
        try:
            with _tool_error(
                "workspace path is not valid UTF-8; provide an absolute UTF-8 workspace path"
            ):
                await r_utf8.attach_workspace("bad\ud800path", "bad\ud800token")
            with _tool_error(
                "workspace token is not valid UTF-8; provide a valid existing UTF-8 continuity token"
            ):
                await r_utf8.attach_workspace("relative/path", "bad\ud800token")
        finally:
            await r_utf8.aclose()

    async def full_scenario() -> None:
        await exercise_resident_default_handoff(
            McpLaunchDefaults(workspace=str(symlink), token=claude_tok_a)
        )
        await exercise_resident_default_handoff(
            McpLaunchDefaults(workspace=str(symlink), as_name="claude")
        )
        await exercise_slow_default_isolation()
        await exercise_cold_as_and_utf8_order()

    asyncio.run(full_scenario())


@pytest.mark.sqlite_only
@pytest.mark.timeout(25)
def test_launch_defaults_slow_alias_reconcile_and_probe_error_recovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """[MCP-4] Regression coverage for F5a (slow matching alias reconciliation) and F5b (probe PermissionError recovery)."""

    from taut_mcp.cli import McpLaunchDefaults

    (tmp_path / "proj_a").mkdir()
    (tmp_path / "proj_b").mkdir()
    (tmp_path / "proj_c").mkdir()
    ws_a, claude_tok_a, _ = _create_workspace(tmp_path / "proj_a", "claude")
    ws_b, _claude_tok_b, _ = _create_workspace(tmp_path / "proj_b", "claude")
    ws_c, claude_tok_c, _ = _create_workspace(tmp_path / "proj_c", "claude")
    symlink = tmp_path / "default_link"
    symlink.symlink_to(ws_a)
    real_res_ws = workspace_reactor._resolve_workspace

    async def exercise_slow_alias_reconcile() -> None:
        symlink.unlink(missing_ok=True)
        symlink.symlink_to(ws_a)
        probe_entered = threading.Event()
        probe_release = threading.Event()
        probe_finished = threading.Event()

        def delayed_matching_alias(locator: str) -> Any:
            if locator == str(symlink):
                probe_entered.set()
                probe_release.wait(timeout=10)
                try:
                    return real_res_ws(locator)
                finally:
                    probe_finished.set()
            return real_res_ws(locator)

        with monkeypatch.context() as f5a_patch:
            f5a_patch.setattr(
                workspace_reactor,
                "_UNPINNED_DEFAULT_PROBE_TIMEOUT_SECONDS",
                0.03,
            )
            f5a_patch.setattr(
                workspace_reactor, "_resolve_workspace", delayed_matching_alias
            )
            r_f5a = ProcessReactor(
                asyncio.get_running_loop(),
                defaults=McpLaunchDefaults(workspace=str(symlink), token=claude_tok_a),
            )
            try:
                att_a_slow = await r_f5a.attach_workspace(str(ws_a), claude_tok_a)
                assert probe_entered.is_set()
                probe_release.set()
                assert await asyncio.to_thread(probe_finished.wait, 5)
                await async_eventually(
                    lambda: (
                        r_f5a._entries[canonical_of(att_a_slow)].is_default_workspace
                        is True
                    ),
                    timeout=5.0,
                    interval=0.01,
                    description="late default probe pinned resident ws_a",
                )
                symlink.unlink()
                symlink.symlink_to(ws_b)
                assert (await r_f5a.attach_workspace(None, None)) == att_a_slow
                assert set(r_f5a._entries) == {canonical_of(att_a_slow)}
            finally:
                probe_release.set()
                await r_f5a.aclose()

    async def exercise_probe_error_recovery() -> None:
        symlink.unlink(missing_ok=True)
        symlink.symlink_to(ws_a)
        perm_calls = 0
        perm_lock = threading.Lock()

        def oneshot_perm_error(locator: str) -> Any:
            nonlocal perm_calls
            if locator == str(symlink):
                with perm_lock:
                    perm_calls += 1
                    current = perm_calls
                if current == 1:
                    raise PermissionError("EACCES simulated on default locator")
            return real_res_ws(locator)

        with monkeypatch.context() as f5b_patch:
            f5b_patch.setattr(
                workspace_reactor, "_resolve_workspace", oneshot_perm_error
            )
            r_f5b = ProcessReactor(
                asyncio.get_running_loop(),
                defaults=McpLaunchDefaults(workspace=str(symlink), token=claude_tok_a),
            )
            try:
                assert r_f5b._default_probe is not None
                att_c_perm = await r_f5b.attach_workspace(str(ws_c), claude_tok_c)
                assert canonical_of(att_c_perm) == str(ws_c.resolve())
                assert r_f5b._default_probe._inflight is None
                att_a_rec = await r_f5b.attach_workspace(str(ws_a), claude_tok_a)
                assert perm_calls == 2
                assert (
                    r_f5b._entries[canonical_of(att_a_rec)].is_default_workspace is True
                )
            finally:
                await r_f5b.aclose()

    async def scenario() -> None:
        await exercise_slow_alias_reconcile()
        await exercise_probe_error_recovery()

    asyncio.run(scenario())


@pytest.mark.sqlite_only
@pytest.mark.timeout(25)
def test_launch_defaults_unrelated_resident_retarget_and_hung_probe_bound(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """[MCP-4] Regression coverage for R3-1 (unrelated resident is not pinned by another caller's slow probe) and R3-3 (hung probe retains O(1) state)."""

    from taut_mcp.cli import McpLaunchDefaults

    (tmp_path / "proj_a").mkdir()
    (tmp_path / "proj_b").mkdir()
    (tmp_path / "proj_c").mkdir()
    ws_a, claude_tok_a, _ = _create_workspace(tmp_path / "proj_a", "claude")
    ws_b, _claude_tok_b, _ = _create_workspace(tmp_path / "proj_b", "claude")
    ws_c, claude_tok_c, _ = _create_workspace(tmp_path / "proj_c", "claude")
    b_admin = TautClient(db_path=ws_b / ".taut.db", as_name="claude")
    try:
        with b_admin._meta_queue.sidecar(transaction=True) as session:
            session.run(
                "UPDATE taut_members SET token = ? WHERE name_key = 'claude'",
                (claude_tok_a,),
            )
    finally:
        b_admin.close()

    symlink = tmp_path / "default_link"
    real_res_ws = workspace_reactor._resolve_workspace

    async def exercise_unrelated_resident_not_pinned() -> None:
        # 1) Start with broken symlink so explicit ws_a attaches unpinned.
        symlink.unlink(missing_ok=True)
        symlink.symlink_to(tmp_path / "missing_initial_target")
        reactor = ProcessReactor(
            asyncio.get_running_loop(),
            defaults=McpLaunchDefaults(workspace=str(symlink), token=claude_tok_a),
        )
        probe_entered = threading.Event()
        probe_release = threading.Event()
        probe_finished = threading.Event()

        def slow_link_res(locator: str) -> Any:
            if locator == str(symlink):
                probe_entered.set()
                probe_release.wait(timeout=10)
                try:
                    return real_res_ws(locator)
                finally:
                    probe_finished.set()
            return real_res_ws(locator)

        try:
            att_a = await reactor.attach_workspace(str(ws_a), claude_tok_a)
            canon_a = canonical_of(att_a)
            assert reactor._entries[canon_a].is_default_workspace is False

            # 2) Point symlink at ws_a, then attach ws_c while probe is slow:
            # ws_c's probe samples ws_a (> timeout), then symlink retargets to ws_b!
            symlink.unlink()
            symlink.symlink_to(ws_a)
            with monkeypatch.context() as r3_patch:
                r3_patch.setattr(
                    workspace_reactor,
                    "_UNPINNED_DEFAULT_PROBE_TIMEOUT_SECONDS",
                    0.03,
                )
                r3_patch.setattr(workspace_reactor, "_resolve_workspace", slow_link_res)
                att_c = await reactor.attach_workspace(str(ws_c), claude_tok_c)
                assert canonical_of(att_c) == str(ws_c.resolve())
                assert probe_entered.is_set()
                probe_release.set()
                assert await asyncio.to_thread(probe_finished.wait, 5)

            await asyncio.sleep(0.05)
            reactor._drain_events()
            assert reactor._entries[canon_a].is_default_workspace is False

            # 3) Retarget symlink to ws_b; omitted-workspace call must attach ws_b, NOT ws_a!
            symlink.unlink()
            symlink.symlink_to(ws_b)
            att_b = await reactor.attach_workspace(None, None)
            assert canonical_of(att_b) == str(ws_b.resolve())
            assert reactor._entries[canonical_of(att_b)].is_default_workspace is True
        finally:
            probe_release.set()
            await reactor.aclose()

    async def exercise_hung_probe_constant_state() -> None:
        symlink.unlink(missing_ok=True)
        symlink.symlink_to(ws_a)
        hold_forever = threading.Event()

        def hung_link_res(locator: str) -> Any:
            if locator == str(symlink):
                hold_forever.wait(timeout=10)
            return real_res_ws(locator)

        with monkeypatch.context() as hpatch:
            hpatch.setattr(
                workspace_reactor,
                "_UNPINNED_DEFAULT_PROBE_TIMEOUT_SECONDS",
                0.01,
            )
            hpatch.setattr(workspace_reactor, "_resolve_workspace", hung_link_res)
            r_hung = ProcessReactor(
                asyncio.get_running_loop(),
                defaults=McpLaunchDefaults(workspace=str(symlink), token=claude_tok_a),
            )

            def no_live_candidates(reactor: ProcessReactor = r_hung) -> bool:
                return not reactor._candidates

            try:
                for _ in range(10):
                    with _tool_error(
                        "workspace identity invalid; provide a valid existing continuity token"
                    ):
                        await r_hung.attach_workspace(str(ws_c), "bad-token")
                    await async_eventually(
                        no_live_candidates,
                        timeout=5.0,
                        interval=0.01,
                        description="failed candidate reaped",
                    )
                assert r_hung._default_probe is not None
                assert r_hung._default_probe._inflight is not None
                assert not hasattr(r_hung._default_probe._inflight, "timed_out_checks")
                assert not r_hung._candidates
            finally:
                hold_forever.set()
                await r_hung.aclose()

    async def full() -> None:
        await exercise_unrelated_resident_not_pinned()
        await exercise_hung_probe_constant_state()

    asyncio.run(full())


class _TimeoutRecordingEvent:
    def __init__(self, sink: list[float | None]) -> None:
        self._inner = threading.Event()
        self._sink = sink

    def is_set(self) -> bool:
        return self._inner.is_set()

    def set(self) -> None:
        self._inner.set()

    def wait(self, timeout: float | None = None) -> bool:
        self._sink.append(timeout)
        return self._inner.wait(timeout=timeout)


@pytest.mark.sqlite_only
@pytest.mark.timeout(25)
def test_launch_defaults_overlapping_probes_preserve_first_participant_match(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """[MCP-4] R4-1 / R5-2 / R6-1 / R6-2: overlapping probes preserve timed-out match, use call-time timeout, and enqueue while owning _inflight."""

    from taut_mcp.cli import McpLaunchDefaults

    (tmp_path / "proj_a").mkdir()
    (tmp_path / "proj_b").mkdir()
    (tmp_path / "proj_c").mkdir()
    ws_a, claude_tok_a, _ = _create_workspace(tmp_path / "proj_a", "claude")
    ws_b, _claude_tok_b, _ = _create_workspace(tmp_path / "proj_b", "claude")
    ws_c, claude_tok_c, _ = _create_workspace(tmp_path / "proj_c", "claude")
    symlink = tmp_path / "default_link"
    real_res_ws = workspace_reactor._resolve_workspace

    async def exercise_delayed_resolved_after_two_drained_probes() -> None:
        symlink.unlink(missing_ok=True)
        symlink.symlink_to(ws_a)
        probe_num = 0
        probe_lock = threading.Lock()
        probe1_entered = threading.Event()
        probe1_release = threading.Event()
        probe1_done = threading.Event()
        probe2_done = threading.Event()
        ws_a_timed_out = threading.Event()
        hold_ws_a_emit = threading.Event()
        seen_pending: list[tuple[bool, object]] = []
        observed_timeouts: list[float | None] = []
        enqueue_slot_states: list[tuple[bool, bool]] = []

        def staged_res(locator: str) -> Any:
            nonlocal probe_num
            if locator == str(symlink):
                with probe_lock:
                    probe_num += 1
                    cur = probe_num
                if cur == 1:
                    probe1_entered.set()
                    probe1_release.wait(timeout=10)
                    try:
                        return real_res_ws(locator)
                    finally:
                        probe1_done.set()
                try:
                    return real_res_ws(locator)
                finally:
                    probe2_done.set()
            return real_res_ws(locator)

        real_is_default = workspace_reactor._is_default_candidate

        def delayed_ws_a_after_probe(
            bootstrap: Any,
            canonical: str,
            directory_identity: tuple[int, int],
        ) -> Any:
            matched, pending = real_is_default(bootstrap, canonical, directory_identity)
            if bootstrap.locator == str(ws_a):
                seen_pending.append((matched, pending))
                ws_a_timed_out.set()
                hold_ws_a_emit.wait(timeout=10)
            return matched, pending

        with monkeypatch.context() as opatch:
            opatch.setattr(
                workspace_reactor,
                "_UNPINNED_DEFAULT_PROBE_TIMEOUT_SECONDS",
                0.02,
            )
            opatch.setattr(
                workspace_reactor,
                "Event",
                lambda: _TimeoutRecordingEvent(observed_timeouts),
            )
            opatch.setattr(workspace_reactor, "_resolve_workspace", staged_res)
            opatch.setattr(
                workspace_reactor,
                "_is_default_candidate",
                delayed_ws_a_after_probe,
            )
            r_ov = ProcessReactor(
                asyncio.get_running_loop(),
                defaults=McpLaunchDefaults(workspace=str(symlink), token=claude_tok_a),
            )
            assert r_ov._default_probe is not None
            real_enqueue = r_ov._default_probe._on_resolved
            assert real_enqueue is not None

            def checking_enqueue(attempt: Any) -> None:
                probe = r_ov._default_probe
                assert probe is not None
                enqueue_slot_states.append(
                    (probe._inflight is attempt, probe._lock.locked())
                )
                real_enqueue(attempt)

            opatch.setattr(r_ov._default_probe, "_on_resolved", checking_enqueue)
            drained_probes = 0
            real_on_probe = r_ov._on_default_workspace_resolved

            def counting_on_probe(event: Any) -> None:
                nonlocal drained_probes
                drained_probes += 1
                real_on_probe(event)

            opatch.setattr(r_ov, "_on_default_workspace_resolved", counting_on_probe)
            try:
                task_a = asyncio.create_task(
                    r_ov.attach_workspace(str(ws_a), claude_tok_a)
                )
                assert await asyncio.to_thread(probe1_entered.wait, 5)
                assert await asyncio.to_thread(ws_a_timed_out.wait, 5)
                assert observed_timeouts == [0.02]
                assert len(seen_pending) == 1
                first_matched, first_pending = seen_pending[0]
                assert first_matched is False and first_pending is not None

                probe1_release.set()
                assert await asyncio.to_thread(probe1_done.wait, 5)
                await async_eventually(
                    lambda: drained_probes >= 1,
                    timeout=5.0,
                    interval=0.01,
                    description="probe 1 completion drained",
                )

                symlink.unlink()
                symlink.symlink_to(ws_b)
                att_c = await r_ov.attach_workspace(str(ws_c), claude_tok_c)
                assert canonical_of(att_c) == str(ws_c.resolve())
                assert await asyncio.to_thread(probe2_done.wait, 5)
                await async_eventually(
                    lambda: drained_probes >= 2,
                    timeout=5.0,
                    interval=0.01,
                    description="probe 2 completion drained before ws_a resolved",
                )
                assert enqueue_slot_states == [(True, True), (True, True)]
                assert observed_timeouts == [0.02, 0.02]

                hold_ws_a_emit.set()
                att_a = await task_a
                canon_a = canonical_of(att_a)
                assert r_ov._entries[canon_a].is_default_workspace is True
                assert r_ov._entries[canon_a].pending_default_probes == []
                assert (await r_ov.attach_workspace(None, None)) == att_a
            finally:
                probe1_release.set()
                hold_ws_a_emit.set()
                await r_ov.aclose()

    asyncio.run(exercise_delayed_resolved_after_two_drained_probes())


@pytest.mark.sqlite_only
@pytest.mark.timeout(25)
def test_launch_defaults_two_aliases_on_resident_entry_preserve_pending_probes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """[MCP-4] R5-1: two alias attaches on one resident entry preserve all pending probes."""

    from taut_mcp.cli import McpLaunchDefaults

    (tmp_path / "proj_a").mkdir()
    (tmp_path / "proj_b").mkdir()
    ws_a, claude_tok_a, _ = _create_workspace(tmp_path / "proj_a", "claude")
    ws_b, _claude_tok_b, _ = _create_workspace(tmp_path / "proj_b", "claude")
    symlink = tmp_path / "default_link"
    alias1 = tmp_path / "alias_a_1"
    alias2 = tmp_path / "alias_a_2"
    alias1.symlink_to(ws_a)
    alias2.symlink_to(ws_a)
    real_res_ws = workspace_reactor._resolve_workspace

    async def exercise_two_aliases_on_resident_entry() -> None:
        symlink.unlink(missing_ok=True)
        symlink.symlink_to(tmp_path / "missing_init")
        r_alias = ProcessReactor(
            asyncio.get_running_loop(),
            defaults=McpLaunchDefaults(workspace=str(symlink), token=claude_tok_a),
        )
        p_num = 0
        p_lock = threading.Lock()
        p1_entered = threading.Event()
        p1_release = threading.Event()
        p2_entered = threading.Event()
        p2_release = threading.Event()
        hold_cb1 = threading.Event()

        def two_alias_res(locator: str) -> Any:
            nonlocal p_num
            if locator == str(symlink):
                with p_lock:
                    p_num += 1
                    cur = p_num
                if cur == 1:
                    p1_entered.set()
                    p1_release.wait(timeout=10)
                    return real_res_ws(locator)
                p2_entered.set()
                p2_release.wait(timeout=10)
                return real_res_ws(locator)
            return real_res_ws(locator)

        assert r_alias._default_probe is not None
        real_cb = r_alias._default_probe._on_resolved
        assert real_cb is not None
        cb_calls = 0

        def delayed_first_cb(attempt: Any) -> None:
            nonlocal cb_calls
            cb_calls += 1
            if cb_calls == 1:

                def emit_later() -> None:
                    hold_cb1.wait(timeout=10)
                    real_cb(attempt)

                threading.Thread(target=emit_later, daemon=True).start()
                return
            real_cb(attempt)

        try:
            att_a = await r_alias.attach_workspace(str(ws_a), claude_tok_a)
            canon_a = canonical_of(att_a)
            assert r_alias._entries[canon_a].is_default_workspace is False

            symlink.unlink()
            symlink.symlink_to(ws_a)
            with monkeypatch.context() as apatch:
                apatch.setattr(
                    workspace_reactor,
                    "_UNPINNED_DEFAULT_PROBE_TIMEOUT_SECONDS",
                    0.02,
                )
                apatch.setattr(workspace_reactor, "_resolve_workspace", two_alias_res)
                apatch.setattr(r_alias._default_probe, "_on_resolved", delayed_first_cb)
                assert (
                    await r_alias.attach_workspace(str(alias1), claude_tok_a)
                ) == att_a
                assert await asyncio.to_thread(p1_entered.wait, 5)
                assert len(r_alias._entries[canon_a].pending_default_probes) == 1
                p1_release.set()
                await async_eventually(
                    lambda: r_alias._default_probe._inflight is None,  # type: ignore[union-attr]
                    timeout=5.0,
                    interval=0.01,
                    description="probe 1 finished with callback 1 held",
                )

                symlink.unlink()
                symlink.symlink_to(ws_b)
                assert (
                    await r_alias.attach_workspace(str(alias2), claude_tok_a)
                ) == att_a
                assert await asyncio.to_thread(p2_entered.wait, 5)
                assert len(r_alias._entries[canon_a].pending_default_probes) == 2

                p2_release.set()
                hold_cb1.set()
                await async_eventually(
                    lambda: r_alias._entries[canon_a].is_default_workspace is True,
                    timeout=5.0,
                    interval=0.01,
                    description="entry_a pinned once held callback 1 drained",
                )
                assert r_alias._entries[canon_a].pending_default_probes == []
                assert (await r_alias.attach_workspace(None, None)) == att_a
        finally:
            p1_release.set()
            p2_release.set()
            hold_cb1.set()
            await r_alias.aclose()

    asyncio.run(exercise_two_aliases_on_resident_entry())
