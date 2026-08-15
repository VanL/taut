from __future__ import annotations

import asyncio
import gc
import hashlib
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
from typing import Any, cast

import pytest
from simplebroker import Queue
from tests.helpers.eventually import async_eventually

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
        return [json.loads(cast(str, message)) for message in messages]
    finally:
        queue.close()


class _FingerprintAuditedCandidates(dict[int, Any]):
    def __init__(self) -> None:
        super().__init__()
        self.cleared_before_pop: list[bool] = []

    def pop(self, key: int, default: Any = None) -> Any:
        candidate = self.get(key)
        if candidate is not None:
            self.cleared_before_pop.append(candidate.fingerprint is None)
        return super().pop(key, default)


def _assert_frame_excludes_request_values(
    frame: Any,
    *,
    token: str,
) -> None:
    """Reject token/fingerprint values without making local names contractual."""

    assert frame is not None
    fingerprint = hashlib.sha256(token.encode("utf-8")).digest()
    values = tuple(frame.f_locals.values())
    assert not any(type(value) is str and value == token for value in values)
    assert not any(type(value) is bytes and value == fingerprint for value in values)


def _assert_coroutine_excludes_request_values(
    coroutine: Any,
    *,
    token: str,
) -> bool:
    """Inspect each exposed coroutine in the live await chain."""

    current = coroutine
    observed_frame = False
    while current is not None:
        frame = getattr(current, "cr_frame", None)
        if frame is not None:
            observed_frame = True
            _assert_frame_excludes_request_values(frame, token=token)
        awaited = getattr(current, "cr_await", None)
        current = awaited if getattr(awaited, "cr_frame", None) is not None else None
    assert observed_frame or sys.implementation.name != "cpython", (
        "CPython must expose coroutine frames for the MCP live-state cleanup assertion"
    )
    return observed_frame


def _skip_if_coroutine_frames_are_unavailable(*, inspected: bool) -> None:
    if not inspected:
        pytest.skip(
            f"{sys.implementation.name} does not expose coroutine frames; "
            "observable lifecycle assertions passed"
        )


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
                    reactor.detach_workspace(str(attached["workspace"])),
                    timeout=0.25,
                )
        finally:
            release_close.set()
            await asyncio.wait_for(close, timeout=5)

    asyncio.run(scenario())


def test_process_token_bucket_uses_continuous_refill_without_refund() -> None:
    """[MCP-10] Capacity, refill, and rejection math are exact."""

    async def scenario() -> None:
        now = 100.0

        def clock() -> float:
            return now

        reactor = ProcessReactor(asyncio.get_running_loop(), bucket_clock=clock)
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

    workspace, token, _ = _create_workspace(tmp_path, "selected")

    class StartFailThread:
        def start(self) -> None:
            raise RuntimeError("synthetic start failure")

        def is_alive(self) -> bool:
            return False

    async def scenario() -> None:
        reactor = ProcessReactor(asyncio.get_running_loop())
        real_new_owner = reactor._new_owner
        audited = _FingerprintAuditedCandidates()
        reactor._candidates = audited
        inbound: queue.Queue[workspace_reactor.WorkspaceControl] = queue.Queue()
        controls: list[workspace_reactor.WorkspaceControl] = []

        class AuditedOwner:
            wake = threading.Event()
            thread = StartFailThread()

            def __init__(self) -> None:
                self.inbound = inbound

            def send(self, control: workspace_reactor.WorkspaceControl) -> None:
                controls.append(control)
                self.inbound.put_nowait(control)

        def failed_owner(_: int) -> Any:
            return AuditedOwner()

        monkeypatch.setattr(reactor, "_new_owner", failed_owner)
        try:
            with pytest.raises(WorkspaceToolError) as raised:
                await reactor.attach_workspace(str(workspace), token)
            assert str(raised.value) == (
                "workspace attachment failed; use list_workspaces before retrying"
            )
            assert audited.cleared_before_pop == [True]
            assert len(controls) == 1
            bootstrap = controls[0]
            assert isinstance(bootstrap, workspace_reactor.Bootstrap)
            assert bootstrap.token == ""
            assert inbound.empty()
            traceback = raised.value.__traceback__
            while traceback is not None and (
                traceback.tb_frame.f_code.co_name != "ensure_workspace"
            ):
                traceback = traceback.tb_next
            assert traceback is not None
            _assert_frame_excludes_request_values(
                traceback.tb_frame,
                token=token,
            )
            assert reactor.list_workspaces()["records"] == []
            monkeypatch.setattr(reactor, "_new_owner", real_new_owner)
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
            reactor._entries[canonical].fingerprint = None
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
            assert token not in " ".join(reactor.list_workspaces()["warnings"])
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
def test_unexpected_resolution_crash_clears_hidden_candidate_fingerprint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """[MCP-4] Dead-owner fallback clears a hidden digest before removal."""

    workspace, token, _ = _create_workspace(tmp_path, "selected")
    TautClient.set_debug_capture(True, db_path=workspace / ".taut.db")

    def crash_resolution(_: str) -> Any:
        raise OSError("synthetic unexpected resolution crash")

    monkeypatch.setattr(workspace_reactor, "_resolve_workspace", crash_resolution)

    async def scenario() -> None:
        reactor = ProcessReactor(asyncio.get_running_loop())
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
        reactor = ProcessReactor(asyncio.get_running_loop())
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
        canonical = str(attached["workspace"])
        entry = reactor._entries[canonical]
        reactor._maintenance.cancel()
        real_wake = loop.call_soon_threadsafe

        def drop_wake(*_: object) -> None:
            return None

        loop.call_soon_threadsafe = drop_wake  # type: ignore[assignment]
        try:
            detach = asyncio.create_task(reactor.detach_workspace(canonical))
            await async_eventually(
                lambda: not entry.owner.thread.is_alive(),
                timeout=5.0,
                interval=0.01,
                description="detach owner thread stops at the timeout boundary",
                snapshot=lambda: {
                    "owner_thread_alive": entry.owner.thread.is_alive(),
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


@pytest.mark.sqlite_only
@pytest.mark.timeout(10)
def test_maintenance_drains_events_when_threadsafe_wake_fails(tmp_path: Path) -> None:
    """[MCP-8] The 0.5-second pass recovers an already-enqueued event."""

    workspace, token, _ = _create_workspace(tmp_path, "selected")

    async def scenario() -> None:
        loop = asyncio.get_running_loop()
        reactor = ProcessReactor(loop)
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
        reactor = ProcessReactor(asyncio.get_running_loop())
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
        canonical = str(attached["workspace"])
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
        assert reactor._entries[canonical].fingerprint is None
        with _tool_error("workspace reactor failed; detach and reattach"):
            await reactor._execute_ready_tool(canonical, "whoami", {})
        with _tool_error("workspace reactor failed; detach and reattach"):
            await reactor.attach_workspace(canonical, token)

        release_periodic_peek.set()
        await async_eventually(
            lambda: not entry.owner.thread.is_alive(),
            timeout=5.0,
            interval=0.01,
            description="failed detach owner thread stops before retry",
            snapshot=lambda: {
                "owner_thread_alive": entry.owner.thread.is_alive(),
                "entry_status": entry.status,
            },
        )
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
        reactor = ProcessReactor(asyncio.get_running_loop())
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
        frame_inspected = _assert_coroutine_excludes_request_values(
            attach.get_coro(),
            token=token,
        )
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
        _skip_if_coroutine_frames_are_unavailable(inspected=frame_inspected)

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
        frame_inspected = _assert_coroutine_excludes_request_values(
            call.get_coro(),
            token=token,
        )
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
        _skip_if_coroutine_frames_are_unavailable(inspected=frame_inspected)

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
@pytest.mark.timeout(10)
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
            result = await reactor._execute_ready_tool(
                str(healthy["workspace"]), "whoami", {}
            )
            assert result["records"][0]["name"] == "healthy"
            assert diagnostics == [
                "taut-mcp: workspace reactor failed; detach and reattach"
            ]
        finally:
            await reactor.aclose()

    asyncio.run(scenario())

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
                    str(attached["workspace"]),
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
    real_run_cycle = workspace_reactor._WorkspaceReactor._run_cycle

    def crash_after_ready(self: workspace_reactor._WorkspaceReactor) -> bool:
        result = real_run_cycle(self)
        if self.ready:
            outer_local = "outer loop evidence"
            _ = outer_local
            del _
            raise RuntimeError("outer loop failed")
        return result

    monkeypatch.setattr(
        workspace_reactor._WorkspaceReactor,
        "_run_cycle",
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
                    str(attached["workspace"]),
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
