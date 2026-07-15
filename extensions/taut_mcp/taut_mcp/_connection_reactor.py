"""Master-thread reactor over child workspace reactors for [MCP-8]."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import queue
import threading
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from taut import Notification

from ._commands import (
    RECORD_TYPE_BY_TOOL,
    CommandScalar,
    record_object,
)
from ._workspace_reactor import (
    ATTACHMENT_FAILED,
    Bootstrap,
    CancelWorkspaceCommand,
    GrantValidation,
    RunWorkspaceCommand,
    StopWorkspace,
    WorkspaceCommandOutcome,
    WorkspaceControl,
    WorkspaceCrashed,
    WorkspaceEvent,
    WorkspaceFailed,
    WorkspaceIdentityLost,
    WorkspaceReady,
    WorkspaceResolved,
    WorkspaceSnapshot,
    WorkspaceStopped,
    run_workspace_reactor,
)

WORKSPACE_BUSY = "workspace busy; retry after backoff"
WORKSPACE_NOT_ATTACHED = (
    "workspace not attached; use list_workspaces and the exact canonical identifier"
)
WORKSPACE_IDENTITY_LOST = "workspace identity lost; detach and reattach"
WORKSPACE_REACTOR_FAILED = "workspace reactor failed; detach and reattach"
WORKSPACE_LIMIT = (
    "workspace attachment limit reached; detach a workspace or wait for cleanup"
)
WORKSPACE_CONFLICT = "workspace already attached; detach to replace token"
WORKSPACE_ABSOLUTE = (
    "workspace path must be absolute; provide an absolute workspace directory"
)
WORKSPACE_PATH_UTF8 = (
    "workspace path is not valid UTF-8; provide an absolute UTF-8 workspace path"
)
WORKSPACE_TOKEN_UTF8 = (
    "workspace token is not valid UTF-8; provide a valid existing UTF-8 "
    "continuity token"
)
WORKSPACE_RESOLUTION_TIMEOUT = (
    "workspace resolution timed out; use list_workspaces then restart if warned"
)
WORKSPACE_ATTACH_TIMEOUT = "workspace attach timed out; use list_workspaces then detach"
WORKSPACE_DETACH_TIMEOUT = "workspace detach timed out; retry detach after backoff"
RATE_LIMIT_EXCEEDED = "rate limit exceeded; retry after backoff"

MAX_WORKSPACES = 8
PHASE_TIMEOUT_SECONDS = 10.0
DETACH_JOIN_SECONDS = 5.0
MAINTENANCE_SECONDS = 0.5
SHUTDOWN_SECONDS = 10.0
BUCKET_CAPACITY = 40.0
BUCKET_REFILL_PER_SECOND = 20.0
CLAUDE_CHANNEL_FAILURE = "taut-mcp: Claude channel wake failed; continuing"
WORKSPACE_REACTOR_FAILURE_DIAGNOSTIC = (
    "taut-mcp: workspace reactor failed; detach and reattach"
)


class WorkspaceToolError(Exception):
    """A fixed, content-free MCP tool failure."""


@dataclass(slots=True)
class _Owner:
    inbound: queue.Queue[WorkspaceControl]
    wake: threading.Event
    thread: threading.Thread

    def send(self, control: WorkspaceControl) -> None:
        self.inbound.put_nowait(control)
        self.wake.set()


@dataclass(slots=True)
class _Candidate:
    generation: int
    locator: str
    fingerprint: bytes | None
    owner: _Owner
    future: asyncio.Future[dict[str, Any]]
    phase: str = "resolution"
    canonical_workspace: str | None = None
    directory_identity: tuple[int, int] | None = None
    backend: str | None = None
    retiring: bool = False
    deadline: asyncio.TimerHandle | None = None
    retired_at: float | None = None
    warning_due: bool = False


@dataclass(slots=True)
class _Entry:
    generation: int
    canonical_workspace: str
    directory_identity: tuple[int, int]
    backend: str
    member_id: str | None
    name: str | None
    fingerprint: bytes | None
    owner: _Owner
    status: str = "ready"
    notifications: tuple[Notification, ...] = ()
    truncated: bool = False
    detach_future: asyncio.Future[dict[str, Any]] | None = None
    detach_record: dict[str, Any] | None = None
    detach_deadline: asyncio.TimerHandle | None = None
    active_command_id: int | None = None
    command_future: asyncio.Future[_CommandCompletion] | None = None


@dataclass(frozen=True, slots=True)
class _CommandCompletion:
    payload: dict[str, Any] | None = None
    error: str | None = None
    canceled: bool = False


def canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _workspace_record(entry: _Entry, *, status: str | None = None) -> dict[str, Any]:
    return {
        "backend": entry.backend,
        "member_id": entry.member_id,
        "name": entry.name,
        "status": entry.status if status is None else status,
        "workspace": entry.canonical_workspace,
    }


def workspace_result(
    records: list[dict[str, Any]],
    *,
    workspace: str | None,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "empty": not records,
        "guidance": [],
        "record_type": "workspace",
        "records": records,
        "warnings": [] if warnings is None else warnings,
        "workspace": workspace,
    }


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


def command_result(
    *,
    name: str,
    record_type: str,
    records: list[dict[str, object]],
    warnings: list[str],
    workspace: str,
) -> dict[str, Any]:
    return {
        "empty": not records,
        "guidance": READ_GUIDANCE if name == "read" and records else [],
        "record_type": record_type,
        "records": records,
        "warnings": warnings,
        "workspace": workspace,
    }


def _notification_record(notification: Notification) -> dict[str, Any]:
    record: dict[str, Any] = {
        "actor_id": notification.actor_id,
        "actor_name": notification.actor_name,
        "message_ts": notification.message_ts,
        "thread": notification.thread,
        "to_id": notification.to_id,
        "type": notification.type,
    }
    if notification.matched is not None:
        record["matched"] = notification.matched
    return record


class ConnectionReactor:
    """Connection-local master reactor; all methods run on its asyncio loop."""

    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        *,
        bucket_clock: Callable[[], float] | None = None,
        diagnostic: Callable[[str], None] | None = None,
    ) -> None:
        if loop is not asyncio.get_running_loop():
            raise RuntimeError("connection reactor requires the running MCP loop")
        self._loop = loop
        self._bucket_clock = loop.time if bucket_clock is None else bucket_clock
        self._diagnostic = (
            self._write_stderr_diagnostic if diagnostic is None else diagnostic
        )
        self._bucket_tokens = BUCKET_CAPACITY
        self._bucket_last = self._bucket_clock()
        self._events: queue.Queue[WorkspaceEvent] = queue.Queue(maxsize=0)
        self._candidates: dict[int, _Candidate] = {}
        self._entries: dict[str, _Entry] = {}
        self._next_generation = 1
        self._next_command_id = 1
        self._closing = False
        self._subscribed = False
        self._resource_sender: Callable[[], Awaitable[None]] | None = None
        self._claude_sender: Callable[[], Awaitable[None]] | None = None
        self._claude_warning: Callable[[str], None] | None = None
        self._claude_tasks: set[asyncio.Future[None]] = set()
        self.current_text = '{"workspaces":[]}'
        self.last_signalled_text = self.current_text
        self.last_claude_attempted_text = self.current_text
        self._maintenance = self._loop.call_later(
            MAINTENANCE_SECONDS,
            self._maintain,
        )

    @staticmethod
    def _write_stderr_diagnostic(message: str) -> None:
        try:
            os.write(2, f"{message}\n".encode())
        except OSError:
            pass

    def charge_request(self) -> None:
        """Charge one schema-valid tool or fixed-resource request."""

        now = self._bucket_clock()
        self._bucket_tokens = min(
            BUCKET_CAPACITY,
            self._bucket_tokens
            + max(0.0, now - self._bucket_last) * BUCKET_REFILL_PER_SECOND,
        )
        self._bucket_last = now
        if self._bucket_tokens < 1.0:
            raise WorkspaceToolError(RATE_LIMIT_EXCEEDED)
        self._bucket_tokens -= 1.0

    def _wake_master(self) -> None:
        try:
            self._loop.call_soon_threadsafe(self._drain_events)
        except RuntimeError:
            # The event is already retained in the unbounded queue. During a
            # live connection the maintenance callback is the backstop.
            pass

    def _new_owner(self, generation: int, locator: str, token: str) -> _Owner:
        inbound: queue.Queue[WorkspaceControl] = queue.Queue(maxsize=0)
        wake = threading.Event()
        thread = threading.Thread(
            target=run_workspace_reactor,
            args=(inbound, wake, self._events, self._wake_master),
            name=f"taut-mcp-workspace-{generation}",
            daemon=False,
        )
        owner = _Owner(inbound, wake, thread)
        owner.send(Bootstrap(generation, locator, token))
        return owner

    @staticmethod
    def _fingerprint(token: str) -> bytes:
        return hashlib.sha256(token.encode("utf-8", errors="strict")).digest()

    @staticmethod
    def _same_workspace(
        canonical: str,
        identity: tuple[int, int],
        other_canonical: str,
        other_identity: tuple[int, int],
    ) -> bool:
        return canonical == other_canonical or identity == other_identity

    def _find_candidate_by_path(self, workspace: str) -> _Candidate | None:
        for candidate in self._candidates.values():
            if (
                candidate.locator == workspace
                or candidate.canonical_workspace == workspace
            ):
                return candidate
        return None

    def _entry_error(self, entry: _Entry) -> str:
        if entry.status == "identity_lost":
            return WORKSPACE_IDENTITY_LOST
        if entry.status == "reactor_failed":
            return WORKSPACE_REACTOR_FAILED
        return WORKSPACE_BUSY

    async def attach_workspace(self, workspace: str, token: str) -> dict[str, Any]:
        if self._closing:
            raise WorkspaceToolError(ATTACHMENT_FAILED)
        try:
            workspace.encode("utf-8", errors="strict")
        except UnicodeEncodeError as exc:
            raise WorkspaceToolError(WORKSPACE_PATH_UTF8) from exc
        try:
            token.encode("utf-8", errors="strict")
        except UnicodeEncodeError as exc:
            raise WorkspaceToolError(WORKSPACE_TOKEN_UTF8) from exc
        if not os.path.isabs(workspace):
            raise WorkspaceToolError(WORKSPACE_ABSOLUTE)
        fingerprint = self._fingerprint(token)

        entry = self._entries.get(workspace)
        if entry is not None:
            if entry.status != "ready":
                raise WorkspaceToolError(self._entry_error(entry))
            if entry.fingerprint is None:
                raise AssertionError("ready workspace requires a token fingerprint")
            if hmac.compare_digest(entry.fingerprint, fingerprint):
                return workspace_result(
                    [_workspace_record(entry)],
                    workspace=entry.canonical_workspace,
                )
            raise WorkspaceToolError(WORKSPACE_CONFLICT)
        if self._find_candidate_by_path(workspace) is not None:
            raise WorkspaceToolError(WORKSPACE_BUSY)
        if len(self._entries) + len(self._candidates) >= MAX_WORKSPACES:
            raise WorkspaceToolError(WORKSPACE_LIMIT)

        generation = self._next_generation
        self._next_generation += 1
        future: asyncio.Future[dict[str, Any]] = self._loop.create_future()
        owner = self._new_owner(generation, workspace, token)
        candidate = _Candidate(
            generation,
            workspace,
            fingerprint,
            owner,
            future,
        )
        self._candidates[generation] = candidate
        try:
            owner.thread.start()
        except Exception as exc:
            candidate.fingerprint = None
            self._candidates.pop(generation, None)
            raise WorkspaceToolError(ATTACHMENT_FAILED) from exc
        token = ""
        candidate.deadline = self._loop.call_later(
            PHASE_TIMEOUT_SECONDS,
            self._candidate_timeout,
            generation,
            "resolution",
        )
        # Once Thread.start succeeds, cancellation drops only this transport
        # waiter. The child lifecycle and master-owned future keep running.
        return await asyncio.shield(future)

    async def detach_workspace(self, workspace: str) -> dict[str, Any]:
        self._reap_dead_owners()
        entry = self._entries.get(workspace)
        if entry is None:
            if self._find_candidate_by_path(workspace) is not None:
                raise WorkspaceToolError(WORKSPACE_BUSY)
            return workspace_result([], workspace=None)
        if entry.status == "detaching":
            raise WorkspaceToolError(WORKSPACE_BUSY)
        if entry.detach_future is not None:
            raise WorkspaceToolError(WORKSPACE_BUSY)
        if entry.active_command_id is not None:
            raise WorkspaceToolError(WORKSPACE_BUSY)

        prior_record = _workspace_record(entry)
        if not entry.owner.thread.is_alive():
            self._entries.pop(workspace, None)
            self._recompute_resource()
            return workspace_result(
                [{**prior_record, "status": "detached"}],
                workspace=workspace,
            )
        entry.status = "detaching"
        entry.notifications = ()
        entry.truncated = False
        entry.detach_record = prior_record
        entry.detach_future = self._loop.create_future()
        entry.owner.send(StopWorkspace(entry.generation))
        entry.detach_deadline = self._loop.call_later(
            DETACH_JOIN_SECONDS,
            self._detach_timeout,
            workspace,
            entry.generation,
        )
        self._recompute_resource()
        return await asyncio.shield(entry.detach_future)

    async def execute_tool(
        self,
        workspace: str,
        name: str,
        arguments: dict[str, object],
    ) -> dict[str, Any]:
        """Route one CLI-shaped operation through its owning child reactor."""

        if name not in RECORD_TYPE_BY_TOOL:
            raise AssertionError(f"unregistered ordinary tool: {name}")
        self._reap_dead_owners()
        entry = self._entries.get(workspace)
        if entry is None:
            raise WorkspaceToolError(WORKSPACE_NOT_ATTACHED)
        if entry.status != "ready":
            raise WorkspaceToolError(self._entry_error(entry))
        if entry.active_command_id is not None:
            raise WorkspaceToolError(WORKSPACE_BUSY)

        frozen: list[tuple[str, CommandScalar]] = []
        for key, value in arguments.items():
            if not isinstance(key, str) or not (
                value is None or isinstance(value, (str, int, bool))
            ):
                raise WorkspaceToolError("invalid tool arguments")
            frozen.append((key, value))

        command_id = self._next_command_id
        self._next_command_id += 1
        future: asyncio.Future[_CommandCompletion] = self._loop.create_future()
        entry.active_command_id = command_id
        entry.command_future = future
        entry.owner.send(
            RunWorkspaceCommand(
                entry.generation,
                command_id,
                name,
                tuple(frozen),
            )
        )
        try:
            completion = await asyncio.shield(future)
        except asyncio.CancelledError:
            current = self._entries.get(workspace)
            if (
                current is entry
                and entry.active_command_id == command_id
                and entry.status == "ready"
            ):
                entry.owner.send(CancelWorkspaceCommand(entry.generation, command_id))
            raise
        if completion.error is not None:
            raise WorkspaceToolError(completion.error)
        if completion.canceled:
            raise asyncio.CancelledError
        if completion.payload is None:
            raise AssertionError("successful command requires a payload")
        return completion.payload

    def list_workspaces(self) -> dict[str, Any]:
        records = [
            _workspace_record(self._entries[workspace])
            for workspace in sorted(self._entries)
        ]
        stalled = any(
            candidate.retiring
            and candidate.retired_at is not None
            and (
                candidate.warning_due or self._loop.time() - candidate.retired_at >= 5.0
            )
            for candidate in self._candidates.values()
        )
        warnings = (
            ["stalled attachment reservation exists; restart taut-mcp to clear"]
            if stalled
            else []
        )
        return workspace_result(records, workspace=None, warnings=warnings)

    def subscribe(self, sender: Callable[[], Awaitable[None]]) -> None:
        self._subscribed = True
        self._resource_sender = sender
        if self.current_text != self.last_signalled_text:
            self._signal_resource_change()

    def unsubscribe(self) -> None:
        self._subscribed = False
        self._resource_sender = None

    def configure_claude_channel(
        self,
        sender: Callable[[], Awaitable[None]],
        warning: Callable[[str], None],
    ) -> None:
        """Install the optional best-effort edge sender once per connection."""

        if self._closing or self._claude_sender is not None:
            return
        self._claude_sender = sender
        self._claude_warning = warning
        if self.current_text != self.last_claude_attempted_text:
            self._signal_claude_change()

    def _signal_resource_change(self) -> None:
        if self._closing or not self._subscribed or self._resource_sender is None:
            return
        self.last_signalled_text = self.current_text
        future = asyncio.ensure_future(self._resource_sender(), loop=self._loop)
        future.add_done_callback(self._ignore_sender_result)

    def _signal_claude_change(self) -> None:
        if (
            self._closing
            or self._claude_sender is None
            or self.current_text == self.last_claude_attempted_text
        ):
            return
        self.last_claude_attempted_text = self.current_text
        try:
            awaitable = self._claude_sender()
        except Exception:
            if self._claude_warning is not None:
                self._claude_warning(CLAUDE_CHANNEL_FAILURE)
            return
        future = asyncio.ensure_future(awaitable, loop=self._loop)
        self._claude_tasks.add(future)
        future.add_done_callback(self._finish_claude_attempt)

    def _finish_claude_attempt(self, future: asyncio.Future[None]) -> None:
        self._claude_tasks.discard(future)
        try:
            future.result()
        except asyncio.CancelledError:
            return
        except Exception:
            if not self._closing and self._claude_warning is not None:
                self._claude_warning(CLAUDE_CHANNEL_FAILURE)

    @staticmethod
    def _ignore_sender_result(future: asyncio.Future[None]) -> None:
        try:
            future.result()
        except (asyncio.CancelledError, Exception):
            pass

    def _recompute_resource(self) -> None:
        workspaces: list[dict[str, Any]] = []
        for workspace in sorted(self._entries):
            entry = self._entries[workspace]
            notifications = (
                [_notification_record(item) for item in entry.notifications]
                if entry.status == "ready"
                else []
            )
            workspaces.append(
                {
                    "member_id": entry.member_id,
                    "notifications": notifications,
                    "status": entry.status,
                    "truncated": entry.truncated if entry.status == "ready" else False,
                    "workspace": workspace,
                }
            )
        updated = canonical_json({"workspaces": workspaces})
        if updated == self.current_text:
            return
        self.current_text = updated
        self._signal_resource_change()
        self._signal_claude_change()

    def _candidate_timeout(self, generation: int, expected_phase: str) -> None:
        if self._closing:
            return
        candidate = self._candidates.get(generation)
        if candidate is None or candidate.retiring or candidate.phase != expected_phase:
            return
        candidate.retiring = True
        candidate.retired_at = self._loop.time()
        candidate.warning_due = expected_phase == "resolution"
        candidate.fingerprint = None
        candidate.owner.send(StopWorkspace(generation))
        if candidate.deadline is not None:
            candidate.deadline.cancel()
            candidate.deadline = None
        if expected_phase == "validation" and candidate.canonical_workspace is not None:
            if candidate.directory_identity is None or candidate.backend is None:
                raise AssertionError("validation phase requires resolution metadata")
            if any(
                self._same_workspace(
                    candidate.canonical_workspace,
                    candidate.directory_identity,
                    existing.canonical_workspace,
                    existing.directory_identity,
                )
                for existing in self._entries.values()
            ):
                raise AssertionError(
                    "validation timeout cannot collide with a published workspace"
                )
            entry = _Entry(
                generation,
                candidate.canonical_workspace,
                candidate.directory_identity,
                candidate.backend,
                None,
                None,
                None,
                candidate.owner,
                status="reactor_failed",
            )
            self._entries[entry.canonical_workspace] = entry
            self._candidates.pop(generation, None)
            self._recompute_resource()
            self._fail_future(candidate.future, WORKSPACE_ATTACH_TIMEOUT)
            return
        self._fail_future(candidate.future, WORKSPACE_RESOLUTION_TIMEOUT)

    def _detach_timeout(self, workspace: str, generation: int) -> None:
        if self._closing:
            return
        entry = self._entries.get(workspace)
        if (
            entry is None
            or entry.generation != generation
            or entry.status != "detaching"
        ):
            return
        if not entry.owner.thread.is_alive():
            self._complete_detach(workspace, entry)
            return
        entry.status = "reactor_failed"
        entry.fingerprint = None
        entry.notifications = ()
        entry.truncated = False
        future = entry.detach_future
        entry.detach_future = None
        entry.detach_record = None
        entry.detach_deadline = None
        self._recompute_resource()
        if future is not None:
            self._fail_future(future, WORKSPACE_DETACH_TIMEOUT)

    def _complete_detach(self, workspace: str, entry: _Entry) -> None:
        record = entry.detach_record or _workspace_record(entry)
        future = entry.detach_future
        if entry.detach_deadline is not None:
            entry.detach_deadline.cancel()
        entry.fingerprint = None
        self._entries.pop(workspace, None)
        self._recompute_resource()
        if future is not None and not future.done():
            future.set_result(
                workspace_result(
                    [{**record, "status": "detached"}],
                    workspace=workspace,
                )
            )

    @staticmethod
    def _fail_future(future: asyncio.Future[dict[str, Any]], message: str) -> None:
        if not future.done():
            future.set_exception(WorkspaceToolError(message))

    def _retire_candidate(
        self,
        candidate: _Candidate,
        *,
        result: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        candidate.retiring = True
        candidate.retired_at = self._loop.time()
        candidate.fingerprint = None
        if candidate.deadline is not None:
            candidate.deadline.cancel()
            candidate.deadline = None
        candidate.owner.send(StopWorkspace(candidate.generation))
        if result is not None and not candidate.future.done():
            candidate.future.set_result(result)
        elif error is not None:
            self._fail_future(candidate.future, error)

    def _on_resolved(self, event: WorkspaceResolved) -> None:
        candidate = self._candidates.get(event.generation)
        if candidate is None or candidate.retiring or candidate.phase != "resolution":
            return
        candidate.canonical_workspace = event.canonical_workspace
        candidate.directory_identity = event.directory_identity
        candidate.backend = event.backend

        for entry in self._entries.values():
            if not self._same_workspace(
                event.canonical_workspace,
                event.directory_identity,
                entry.canonical_workspace,
                entry.directory_identity,
            ):
                continue
            if entry.status != "ready":
                self._retire_candidate(candidate, error=self._entry_error(entry))
            elif entry.fingerprint is None or candidate.fingerprint is None:
                self._retire_candidate(candidate, error=ATTACHMENT_FAILED)
            elif hmac.compare_digest(entry.fingerprint, candidate.fingerprint):
                self._retire_candidate(
                    candidate,
                    result=workspace_result(
                        [_workspace_record(entry)],
                        workspace=entry.canonical_workspace,
                    ),
                )
            else:
                self._retire_candidate(candidate, error=WORKSPACE_CONFLICT)
            return

        for other in self._candidates.values():
            if (
                other.generation == event.generation
                or other.canonical_workspace is None
                or other.directory_identity is None
            ):
                continue
            if self._same_workspace(
                event.canonical_workspace,
                event.directory_identity,
                other.canonical_workspace,
                other.directory_identity,
            ):
                self._retire_candidate(candidate, error=WORKSPACE_BUSY)
                return

        if candidate.deadline is not None:
            candidate.deadline.cancel()
        candidate.phase = "validation"
        candidate.deadline = self._loop.call_later(
            PHASE_TIMEOUT_SECONDS,
            self._candidate_timeout,
            event.generation,
            "validation",
        )
        candidate.owner.send(GrantValidation(event.generation))

    def _on_ready(self, event: WorkspaceReady) -> None:
        candidate = self._candidates.get(event.generation)
        if candidate is None or candidate.retiring or candidate.phase != "validation":
            return
        if (
            candidate.canonical_workspace != event.canonical_workspace
            or candidate.directory_identity != event.directory_identity
            or candidate.backend != event.backend
        ):
            self._retire_candidate(candidate, error=ATTACHMENT_FAILED)
            return
        if candidate.deadline is not None:
            candidate.deadline.cancel()
        if candidate.fingerprint is None:
            self._retire_candidate(candidate, error=ATTACHMENT_FAILED)
            return
        fingerprint = candidate.fingerprint
        entry = _Entry(
            event.generation,
            event.canonical_workspace,
            event.directory_identity,
            event.backend,
            event.member_id,
            event.name,
            fingerprint,
            candidate.owner,
            notifications=event.notifications,
            truncated=event.truncated,
        )
        self._candidates.pop(event.generation, None)
        candidate.fingerprint = None
        self._entries[event.canonical_workspace] = entry
        self._recompute_resource()
        if not candidate.future.done():
            candidate.future.set_result(
                workspace_result(
                    [_workspace_record(entry)],
                    workspace=entry.canonical_workspace,
                )
            )

    def _on_failure(self, event: WorkspaceFailed) -> None:
        candidate = self._candidates.get(event.generation)
        if candidate is None or candidate.retiring or candidate.phase != event.phase:
            return
        self._retire_candidate(candidate, error=event.message)

    def _on_snapshot(self, event: WorkspaceSnapshot) -> None:
        if self._closing:
            return
        entry = next(
            (
                item
                for item in self._entries.values()
                if item.generation == event.generation
            ),
            None,
        )
        if entry is None or entry.status != "ready":
            return
        entry.notifications = event.notifications
        entry.truncated = event.truncated
        self._recompute_resource()

    def _on_command_outcome(self, event: WorkspaceCommandOutcome) -> None:
        if self._closing:
            return
        entry = next(
            (
                item
                for item in self._entries.values()
                if item.generation == event.generation
            ),
            None,
        )
        if (
            entry is None
            or entry.status != "ready"
            or entry.active_command_id != event.command_id
        ):
            return
        entry.notifications = event.notifications
        entry.truncated = event.truncated
        self._recompute_resource()
        future = entry.command_future
        entry.active_command_id = None
        entry.command_future = None
        if future is None or future.done():
            return
        if event.canceled:
            future.set_result(_CommandCompletion(canceled=True))
            return
        payload = command_result(
            name=event.name,
            record_type=event.record_type,
            records=[record_object(record) for record in event.records],
            warnings=list(event.warnings),
            workspace=entry.canonical_workspace,
        )
        future.set_result(_CommandCompletion(payload=payload, error=event.error))

    @staticmethod
    def _settle_active_command(entry: _Entry, error: str) -> None:
        future = entry.command_future
        entry.active_command_id = None
        entry.command_future = None
        if future is not None and not future.done():
            future.set_result(_CommandCompletion(error=error))

    def _on_terminal(self, generation: int, status: str) -> None:
        if self._closing:
            return
        entry = next(
            (item for item in self._entries.values() if item.generation == generation),
            None,
        )
        if entry is None or entry.status != "ready":
            return
        if status == "reactor_failed":
            self._diagnostic(WORKSPACE_REACTOR_FAILURE_DIAGNOSTIC)
        entry.status = status
        entry.fingerprint = None
        entry.notifications = ()
        entry.truncated = False
        self._recompute_resource()
        self._settle_active_command(entry, self._entry_error(entry))

    def _drain_events(self) -> None:
        while True:
            try:
                event = self._events.get_nowait()
            except queue.Empty:
                break
            if isinstance(event, WorkspaceResolved):
                self._on_resolved(event)
            elif isinstance(event, WorkspaceReady):
                self._on_ready(event)
            elif isinstance(event, WorkspaceFailed):
                self._on_failure(event)
            elif isinstance(event, WorkspaceSnapshot):
                self._on_snapshot(event)
            elif isinstance(event, WorkspaceCommandOutcome):
                self._on_command_outcome(event)
            elif isinstance(event, WorkspaceIdentityLost):
                self._on_terminal(event.generation, "identity_lost")
            elif isinstance(event, WorkspaceCrashed):
                self._on_terminal(event.generation, "reactor_failed")
            elif isinstance(event, WorkspaceStopped):
                # The event is a liveness cue, not proof that Thread.run has
                # returned. The nonblocking check below owns that distinction.
                pass
        self._reap_dead_owners()

    def _reap_dead_owners(self) -> None:
        for generation, candidate in list(self._candidates.items()):
            if candidate.owner.thread.is_alive():
                continue
            candidate.fingerprint = None
            if not candidate.future.done():
                self._fail_future(candidate.future, ATTACHMENT_FAILED)
            self._candidates.pop(generation, None)

        for workspace, entry in list(self._entries.items()):
            if entry.owner.thread.is_alive():
                continue
            if entry.status == "detaching":
                self._complete_detach(workspace, entry)
                continue
            if entry.status == "ready":
                self._diagnostic(WORKSPACE_REACTOR_FAILURE_DIAGNOSTIC)
                entry.status = "reactor_failed"
                entry.fingerprint = None
                entry.notifications = ()
                entry.truncated = False
                self._recompute_resource()
                self._settle_active_command(entry, WORKSPACE_REACTOR_FAILED)

    def _maintain(self) -> None:
        self._drain_events()
        if not self._closing:
            self._maintenance = self._loop.call_later(
                MAINTENANCE_SECONDS,
                self._maintain,
            )

    async def aclose(self) -> None:
        if self._closing:
            return
        self._closing = True
        self._maintenance.cancel()
        claude_tasks = list(self._claude_tasks)
        for task in claude_tasks:
            task.cancel()
        owners: dict[int, _Owner] = {}
        for candidate in self._candidates.values():
            candidate.retiring = True
            candidate.retired_at = self._loop.time()
            if candidate.deadline is not None:
                candidate.deadline.cancel()
                candidate.deadline = None
            if not candidate.future.done():
                candidate.future.cancel()
            candidate.fingerprint = None
            owners[candidate.generation] = candidate.owner
        for entry in self._entries.values():
            if entry.detach_deadline is not None:
                entry.detach_deadline.cancel()
                entry.detach_deadline = None
            if entry.detach_future is not None and not entry.detach_future.done():
                entry.detach_future.cancel()
            if entry.command_future is not None and not entry.command_future.done():
                entry.command_future.cancel()
            entry.active_command_id = None
            entry.command_future = None
            entry.fingerprint = None
            owners[entry.generation] = entry.owner
        for generation, owner in owners.items():
            owner.send(StopWorkspace(generation))

        deadline = self._loop.time() + SHUTDOWN_SECONDS
        while any(owner.thread.is_alive() for owner in owners.values()):
            self._drain_events()
            if self._loop.time() >= deadline:
                try:
                    os.write(
                        2,
                        b"taut-mcp: shutdown deadline exceeded; forcing exit\n",
                    )
                finally:
                    os._exit(1)
            await asyncio.sleep(0.01)
        self._drain_events()
        if claude_tasks:
            await asyncio.gather(*claude_tasks, return_exceptions=True)
        self._candidates.clear()
        self._entries.clear()
        self.current_text = '{"workspaces":[]}'
