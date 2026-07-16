from __future__ import annotations

import asyncio
import json
import os
import queue
import subprocess
import sys
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

import taut_mcp._connection_reactor as connection_reactor
import taut_mcp._workspace_reactor as workspace_reactor
from taut import TautClient
from taut_mcp._connection_reactor import (
    ConnectionReactor,
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


class _FingerprintAuditedCandidates(dict[int, Any]):
    def __init__(self) -> None:
        super().__init__()
        self.cleared_before_pop: list[bool] = []

    def pop(self, key: int, default: Any = None) -> Any:
        candidate = self.get(key)
        if candidate is not None:
            self.cleared_before_pop.append(candidate.fingerprint is None)
        return super().pop(key, default)


async def _wait_until(
    predicate: Any,
    *,
    timeout: float = 5.0,
) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        if asyncio.get_running_loop().time() >= deadline:
            raise AssertionError("condition did not become true")
        await asyncio.sleep(0.01)


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
        reactor = ConnectionReactor(asyncio.get_running_loop())
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


def test_connection_token_bucket_uses_continuous_refill_without_refund() -> None:
    """[MCP-10] Capacity, refill, and rejection math are exact."""

    async def scenario() -> None:
        now = 100.0

        def clock() -> float:
            return now

        reactor = ConnectionReactor(asyncio.get_running_loop(), bucket_clock=clock)
        try:
            for _ in range(40):
                reactor.charge_request()
            with _tool_error("rate limit exceeded; retry after backoff"):
                reactor.charge_request()

            now += 0.025
            with _tool_error("rate limit exceeded; retry after backoff"):
                reactor.charge_request()
            now += 0.025
            reactor.charge_request()
            with _tool_error("rate limit exceeded; retry after backoff"):
                reactor.charge_request()
        finally:
            await reactor.aclose()

    asyncio.run(scenario())


def test_thread_start_failure_clears_hidden_candidate_fingerprint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """[MCP-4] Removing an unstarted hidden seat clears its digest first."""

    class StartFailThread:
        def start(self) -> None:
            raise RuntimeError("synthetic start failure")

        def is_alive(self) -> bool:
            return False

    async def scenario() -> None:
        reactor = ConnectionReactor(asyncio.get_running_loop())
        audited = _FingerprintAuditedCandidates()
        reactor._candidates = audited

        def failed_owner(_: int, __: str, ___: str) -> Any:
            return connection_reactor._Owner(
                queue.Queue(),
                threading.Event(),
                StartFailThread(),  # type: ignore[arg-type]
            )

        monkeypatch.setattr(reactor, "_new_owner", failed_owner)
        try:
            with _tool_error(
                "workspace attachment failed; use list_workspaces before retrying"
            ):
                await reactor.attach_workspace(
                    str(tmp_path / "workspace"), "secret-token"
                )
            assert audited.cleared_before_pop == [True]
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

    async def scenario() -> None:
        reactor = ConnectionReactor(asyncio.get_running_loop())
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
                "workspace configuration or backend unavailable; fix the workspace configuration or backend and retry"
            ):
                await reactor.attach_workspace(
                    str(invalid_config), "participant-controlled-token"
                )
            with _tool_error(
                "workspace identity invalid; provide a valid existing continuity token"
            ):
                await reactor.attach_workspace(
                    str(workspace), "participant-controlled-invalid-token"
                )
            assert token not in " ".join(reactor.list_workspaces()["warnings"])
        finally:
            await reactor.aclose()

    asyncio.run(scenario())


@pytest.mark.sqlite_only
@pytest.mark.timeout(10)
def test_unexpected_resolution_crash_clears_hidden_candidate_fingerprint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """[MCP-4] Dead-owner fallback clears a hidden digest before removal."""

    workspace, token, _ = _create_workspace(tmp_path, "selected")

    def crash_resolution(_: str) -> Any:
        raise OSError("synthetic unexpected resolution crash")

    monkeypatch.setattr(workspace_reactor, "_resolve_workspace", crash_resolution)

    async def scenario() -> None:
        reactor = ConnectionReactor(asyncio.get_running_loop())
        audited = _FingerprintAuditedCandidates()
        reactor._candidates = audited
        try:
            with _tool_error(
                "workspace attachment failed; use list_workspaces before retrying"
            ):
                await reactor.attach_workspace(str(workspace), token)
            assert audited.cleared_before_pop == [True]
        finally:
            await reactor.aclose()

    asyncio.run(scenario())


@pytest.mark.sqlite_only
@pytest.mark.timeout(15)
def test_workspace_cap_counts_eight_persistent_children(tmp_path: Path) -> None:
    """[MCP-4] One connection admits no more than eight owner threads."""

    workspaces = [_create_workspace(tmp_path, f"member_{index}") for index in range(9)]

    async def scenario() -> None:
        reactor = ConnectionReactor(asyncio.get_running_loop())
        try:
            for workspace, token, _ in workspaces[:8]:
                await reactor.attach_workspace(str(workspace), token)
            with _tool_error(
                "workspace attachment limit reached; detach a workspace or wait for cleanup"
            ):
                workspace, token, _ = workspaces[8]
                await reactor.attach_workspace(str(workspace), token)
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
        reactor = ConnectionReactor(asyncio.get_running_loop())
        try:
            first = await reactor.attach_workspace(str(workspace), token)
            repeated = await reactor.attach_workspace(str(workspace), token)
            aliased = await reactor.attach_workspace(str(alias_same), token)

            assert repeated == first
            assert aliased == first
            assert first["workspace"] == os.path.realpath(workspace)
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
        reactor = ConnectionReactor(asyncio.get_running_loop())
        try:
            attached = await reactor.attach_workspace(
                str(workspace), member.token or ""
            )
            assert attached["workspace"] == os.path.realpath(workspace)
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
        reactor = ConnectionReactor(asyncio.get_running_loop())
        attach = asyncio.create_task(reactor.attach_workspace(str(workspace), token))
        assert await asyncio.to_thread(resolution_started.wait, 5)
        generation = next(iter(reactor._candidates))
        reactor._candidate_timeout(generation, "resolution")
        with _tool_error(
            "workspace resolution timed out; use list_workspaces then restart if warned"
        ):
            await attach
        assert reactor._candidates[generation].fingerprint is None
        assert reactor.list_workspaces()["records"] == []
        assert reactor.list_workspaces()["warnings"] == [
            "stalled attachment reservation exists; restart taut-mcp to clear"
        ]
        release_resolution.set()
        await _wait_until(lambda: not reactor._candidates)
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
        reactor = ConnectionReactor(asyncio.get_running_loop())
        attach = asyncio.create_task(reactor.attach_workspace(str(workspace), token))
        try:
            assert await asyncio.to_thread(resolution_started.wait, 5)
            with _tool_error(
                "workspace not attached; use list_workspaces and the exact canonical identifier"
            ):
                await reactor.execute_tool(str(workspace), "whoami", {})
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

    assert connection_reactor.DETACH_JOIN_SECONDS == 5.0
    workspace, token, _ = _create_workspace(tmp_path, "selected")

    async def scenario() -> None:
        loop = asyncio.get_running_loop()
        reactor = ConnectionReactor(loop)
        attached = await reactor.attach_workspace(str(workspace), token)
        canonical = str(attached["workspace"])
        entry = reactor._entries[canonical]
        reactor._maintenance.cancel()
        real_wake = loop.call_soon_threadsafe

        def drop_wake(*_: object) -> None:
            return None

        loop.call_soon_threadsafe = drop_wake  # type: ignore[assignment]
        try:
            detach = asyncio.create_task(reactor.detach_workspace(canonical))
            await _wait_until(lambda: not entry.owner.thread.is_alive())
            reactor._detach_timeout(canonical, entry.generation)
            result = await detach
            assert result["records"][0]["status"] == "detached"
            assert reactor.list_workspaces()["records"] == []
        finally:
            loop.call_soon_threadsafe = real_wake  # type: ignore[method-assign]
            await reactor.aclose()

    asyncio.run(scenario())


@pytest.mark.sqlite_only
@pytest.mark.timeout(10)
def test_maintenance_drains_events_when_threadsafe_wake_fails(tmp_path: Path) -> None:
    """[MCP-8] The 0.5-second pass recovers an already-enqueued event."""

    workspace, token, _ = _create_workspace(tmp_path, "selected")

    async def scenario() -> None:
        loop = asyncio.get_running_loop()
        reactor = ConnectionReactor(loop)
        real_wake = loop.call_soon_threadsafe

        def failed_wake(*_: object) -> None:
            raise RuntimeError("synthetic closed wake path")

        loop.call_soon_threadsafe = failed_wake  # type: ignore[assignment]
        try:
            attached = await asyncio.wait_for(
                reactor.attach_workspace(str(workspace), token),
                timeout=2,
            )
            assert attached["records"][0]["status"] == "ready"
        finally:
            loop.call_soon_threadsafe = real_wake  # type: ignore[method-assign]
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
        reactor = ConnectionReactor(asyncio.get_running_loop())
        attach = asyncio.create_task(reactor.attach_workspace(str(workspace), token))
        assert await asyncio.to_thread(validation_started.wait, 5)
        generation = next(iter(reactor._candidates))
        reactor._candidate_timeout(generation, "validation")
        with _tool_error("workspace attach timed out; use list_workspaces then detach"):
            await attach
        record = reactor.list_workspaces()["records"][0]
        assert reactor._entries[os.path.realpath(workspace)].fingerprint is None
        assert record == {
            "backend": "sqlite",
            "member_id": None,
            "name": None,
            "status": "reactor_failed",
            "workspace": os.path.realpath(workspace),
        }
        with _tool_error("workspace reactor failed; detach and reattach"):
            await reactor.execute_tool(os.path.realpath(workspace), "whoami", {})
        with _tool_error("workspace reactor failed; detach and reattach"):
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
        reactor = ConnectionReactor(asyncio.get_running_loop())
        attached = await reactor.attach_workspace(str(workspace), token)
        canonical = str(attached["workspace"])
        assert await asyncio.to_thread(periodic_peek_started.wait, 5)

        detach = asyncio.create_task(reactor.detach_workspace(canonical))
        await asyncio.sleep(0)
        entry = reactor._entries[canonical]
        assert entry.status == "detaching"
        with _tool_error("workspace busy; retry after backoff"):
            await reactor.execute_tool(canonical, "whoami", {})
        with _tool_error("workspace busy; retry after backoff"):
            await reactor.attach_workspace(canonical, token)
        with _tool_error("workspace busy; retry after backoff"):
            await reactor.detach_workspace(canonical)
        reactor._detach_timeout(canonical, entry.generation)
        with _tool_error("workspace detach timed out; retry detach after backoff"):
            await detach
        assert reactor.list_workspaces()["records"][0]["status"] == "reactor_failed"
        assert reactor._entries[canonical].fingerprint is None
        with _tool_error("workspace reactor failed; detach and reattach"):
            await reactor.execute_tool(canonical, "whoami", {})
        with _tool_error("workspace reactor failed; detach and reattach"):
            await reactor.attach_workspace(canonical, token)

        release_periodic_peek.set()
        await _wait_until(lambda: not entry.owner.thread.is_alive())
        detached = await reactor.detach_workspace(canonical)
        assert detached["records"][0]["status"] == "detached"
        await reactor.aclose()

    asyncio.run(scenario())


@pytest.mark.sqlite_only
@pytest.mark.timeout(10)
def test_periodic_peek_marks_lost_identity_without_healing_it(tmp_path: Path) -> None:
    """[MCP-8] Losing the immutable token binding degrades the workspace."""

    workspace, token, member_id = _create_workspace(tmp_path, "selected")

    async def scenario() -> None:
        reactor = ConnectionReactor(asyncio.get_running_loop())
        try:
            attached = await reactor.attach_workspace(str(workspace), token)
            canonical = str(attached["workspace"])
            admin = TautClient(db_path=workspace / ".taut.db", as_name="selected")
            with admin._meta_queue.sidecar(transaction=True) as session:
                session.run(
                    "UPDATE taut_members SET token = NULL WHERE member_id = ?",
                    (member_id,),
                )
            admin.close()

            await _wait_until(
                lambda: (
                    reactor.list_workspaces()["records"][0]["status"] == "identity_lost"
                )
            )
            assert reactor._entries[canonical].fingerprint is None
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
                await reactor.execute_tool(canonical, "whoami", {})
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
        reactor = ConnectionReactor(asyncio.get_running_loop())
        attach = asyncio.create_task(reactor.attach_workspace(str(workspace), token))
        assert await asyncio.to_thread(validation_started.wait, 5)
        frame = getattr(attach.get_coro(), "cr_frame", None)
        assert frame is not None
        assert frame.f_locals["token"] == ""
        attach.cancel()
        with pytest.raises(asyncio.CancelledError):
            await attach

        release_validation.set()
        await _wait_until(lambda: bool(reactor.list_workspaces()["records"]))
        assert reactor.list_workspaces()["records"][0]["status"] == "ready"
        await reactor.aclose()

    asyncio.run(scenario())


@pytest.mark.sqlite_only
@pytest.mark.timeout(10)
def test_child_fault_is_isolated_and_reported_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """[MCP-11] One child fault degrades only its workspace and is diagnosed."""

    failed_workspace, failed_token, _ = _create_workspace(tmp_path, "failed")
    healthy_workspace, healthy_token, _ = _create_workspace(tmp_path, "healthy")
    real_execute = workspace_reactor.execute_command

    def selective_crash(client: TautClient, name: str, arguments: Any) -> Any:
        if name == "say" and dict(arguments).get("text") == "trigger-child-fault":
            raise RuntimeError("participant-controlled secret")
        return real_execute(client, name, arguments)

    monkeypatch.setattr(workspace_reactor, "execute_command", selective_crash)

    async def scenario() -> None:
        diagnostics: list[str] = []
        reactor = ConnectionReactor(
            asyncio.get_running_loop(),
            diagnostic=diagnostics.append,
        )
        try:
            failed = await reactor.attach_workspace(str(failed_workspace), failed_token)
            healthy = await reactor.attach_workspace(
                str(healthy_workspace), healthy_token
            )
            with _tool_error("workspace reactor failed; detach and reattach"):
                await reactor.execute_tool(
                    str(failed["workspace"]),
                    "say",
                    {"target": "general", "text": "trigger-child-fault"},
                )

            records = {
                record["workspace"]: record
                for record in reactor.list_workspaces()["records"]
            }
            assert records[str(failed["workspace"])]["status"] == "reactor_failed"
            assert records[str(healthy["workspace"])]["status"] == "ready"
            result = await reactor.execute_tool(str(healthy["workspace"]), "whoami", {})
            assert result["records"][0]["name"] == "healthy"
            assert diagnostics == [
                "taut-mcp: workspace reactor failed; detach and reattach"
            ]
        finally:
            await reactor.aclose()

    asyncio.run(scenario())


@pytest.mark.sqlite_only
@pytest.mark.timeout(10)
def test_shutdown_deadline_forces_isolated_process_exit(tmp_path: Path) -> None:
    """[MCP-3]/[MCP-11] A non-returning child cannot hang process teardown."""

    workspace, token, _ = _create_workspace(tmp_path, "selected")
    probe = """
import asyncio
import sys
import threading

from taut_mcp import _connection_reactor as connection
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
    reactor = connection.ConnectionReactor(asyncio.get_running_loop())
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
