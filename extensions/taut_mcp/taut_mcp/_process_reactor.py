"""Process reactor over child workspace reactors for [MCP-8]."""

from __future__ import annotations

import asyncio
import json
import os
import queue
import threading
from collections import deque
from collections.abc import Awaitable, Callable, Coroutine
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import suppress
from dataclasses import dataclass, field
from typing import Any, cast

from simplebroker import format_message_id
from simplebroker.ext import PollingStrategy

from taut import Notification

from ._commands import (
    CommandArguments,
    CommandScalar,
    record_object,
)
from ._results import DOMAIN_TOOL_NAMES, tool_result
from ._workspace_reactor import (
    ATTACHMENT_FAILED,
    IDENTITY_INVALID,
    NON_DEFAULT_WORKSPACE_TOKEN_REQUIRED,
    Bootstrap,
    CancelWorkspaceCommand,
    DefaultProbeAttempt,
    DefaultWorkspaceProbe,
    DefaultWorkspaceResolved,
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
from .cli import McpLaunchDefaults

WORKSPACE_BUSY = "workspace busy; retry after backoff"
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

MAX_WORKSPACES = 8
MAX_QUEUED_COMMANDS = 8
PHASE_TIMEOUT_SECONDS = 10.0
DETACH_JOIN_SECONDS = 5.0
SHUTDOWN_SECONDS = 10.0
WORKSPACE_REACTOR_FAILURE_DIAGNOSTIC = (
    "taut-mcp: workspace reactor failed; detach and reattach"
)


def _freeze_command_arguments(arguments: dict[str, object]) -> CommandArguments:
    frozen: list[tuple[str, CommandScalar]] = []
    for key, value in arguments.items():
        if isinstance(value, list):
            if not all(isinstance(item, str) for item in value):
                raise AssertionError("validated command arrays require strings")
            command_value: CommandScalar = tuple(value)
        else:
            command_value = cast(CommandScalar, value)
        frozen.append((key, command_value))
    return tuple(frozen)


class WorkspaceToolError(Exception):
    """A fixed, content-free MCP tool failure."""


def _bind_waiter[FutureResult](
    loop: asyncio.AbstractEventLoop,
    future: asyncio.Future[FutureResult],
) -> asyncio.Future[FutureResult]:
    waiter: asyncio.Future[FutureResult] = loop.create_future()

    def settle(completed: asyncio.Future[FutureResult]) -> None:
        if waiter.cancelled():
            if not completed.cancelled():
                completed.exception()
            return
        if completed.cancelled():
            waiter.cancel()
            return
        error = completed.exception()
        if error is not None:
            waiter.set_exception(error)
        else:
            waiter.set_result(completed.result())

    future.add_done_callback(settle)
    return waiter


async def _await_owned_future[FutureResult](
    future: asyncio.Future[FutureResult],
) -> FutureResult:
    """Wait without transferring task cancellation to a reactor-owned future."""

    return await _bind_waiter(asyncio.get_running_loop(), future)


@dataclass(slots=True)
class _QueuedCommand:
    command_id: int
    name: str
    arguments: CommandArguments
    future: asyncio.Future[_CommandCompletion]
    waiter: asyncio.Future[_CommandCompletion]
    canceled: bool = False


@dataclass(slots=True)
class _Owner:
    inbound: queue.Queue[WorkspaceControl]
    notify_activity: Callable[[], None]
    run: Callable[[], None]
    completion: Future[None] | None = None

    def alive(self) -> bool:
        return self.completion is not None and not self.completion.done()

    def send(self, control: WorkspaceControl) -> None:
        self.inbound.put_nowait(control)
        self.notify_activity()


@dataclass(slots=True)
class _Candidate:
    generation: int
    locator: str
    token: str | None
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
    used_default_workspace: bool = False
    require_default_workspace: bool = False
    is_default_workspace: bool = False
    pending_default_probe: DefaultProbeAttempt | None = None


@dataclass(slots=True)
class _Entry:
    generation: int
    canonical_workspace: str
    directory_identity: tuple[int, int]
    backend: str
    member_id: str | None
    name: str | None
    token: str | None
    owner: _Owner
    status: str = "ready"
    notifications: tuple[Notification, ...] = ()
    truncated: bool = False
    detach_future: asyncio.Future[dict[str, Any]] | None = None
    detach_record: dict[str, Any] | None = None
    detach_deadline: asyncio.TimerHandle | None = None
    active_command_id: int | None = None
    command_future: asyncio.Future[_CommandCompletion] | None = None
    queued_commands: deque[_QueuedCommand] = field(default_factory=deque)
    attach_timed_out: bool = False
    is_default_workspace: bool = False
    matches_default_as: bool = False
    pending_default_probes: list[DefaultProbeAttempt] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class _CommandCompletion:
    payload: dict[str, Any] | None = None
    error: str | None = None


def canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _is_strict_utf8(value: str) -> bool:
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeEncodeError:
        return False
    return True


@dataclass(frozen=True, slots=True)
class _ResolvedRequest:
    locator: str
    request_token: str | None
    as_name: str | None
    used_default_workspace: bool
    require_default_workspace: bool


def _workspace_record(entry: _Entry, *, status: str | None = None) -> dict[str, Any]:
    return {
        "backend": entry.backend,
        "member_id": entry.member_id,
        "name": entry.name,
        "status": entry.status if status is None else status,
        "workspace": entry.canonical_workspace,
    }


def _notification_record(notification: Notification) -> dict[str, Any]:
    record: dict[str, Any] = {
        "actor_id": notification.actor_id,
        "actor_name": notification.actor_name,
        "message_ts": (
            None
            if notification.message_ts is None
            else format_message_id(notification.message_ts)
        ),
        "thread": notification.thread,
        "to_id": notification.to_id,
        "type": notification.type,
    }
    if notification.matched is not None:
        record["matched"] = notification.matched
    if notification.reaction is not None:
        record["reaction"] = notification.reaction
    return record


class ProcessReactor:
    """Process-local master reactor; all methods run on its asyncio loop."""

    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        *,
        diagnostic: Callable[[str], None] | None = None,
        defaults: McpLaunchDefaults | None = None,
    ) -> None:
        if loop is not asyncio.get_running_loop():
            raise RuntimeError("process reactor requires the running MCP loop")
        self._loop = loop
        self._defaults = McpLaunchDefaults() if defaults is None else defaults
        self._default_probe = (
            DefaultWorkspaceProbe(
                self._defaults.workspace,
                on_resolved=self._emit_default_probe_resolved,
            )
            if self._defaults.workspace is not None
            else None
        )
        self._diagnostic = (
            self._write_stderr_diagnostic if diagnostic is None else diagnostic
        )
        self._events: queue.Queue[WorkspaceEvent] = queue.Queue(maxsize=0)
        self._candidates: dict[int, _Candidate] = {}
        self._entries: dict[str, _Entry] = {}
        self._next_generation = 1
        self._next_command_id = 1
        self._closing = False
        self._subscribed = False
        self._resource_sender: Callable[[], Awaitable[None]] | None = None
        self._modern_resource_sender: Callable[[], Awaitable[None]] | None = None
        self._resource_tasks: set[asyncio.Future[None]] = set()
        self.current_text = '{"workspaces":[]}'
        self.last_signalled_text = self.current_text
        self._executor = ThreadPoolExecutor(
            max_workers=MAX_WORKSPACES, thread_name_prefix="taut-mcp-workspace"
        )

    @staticmethod
    def _write_stderr_diagnostic(message: str) -> None:
        try:
            os.write(2, f"{message}\n".encode())
        except OSError:
            pass

    def _wake_master(self) -> None:
        try:
            self._loop.call_soon_threadsafe(self._drain_events)
        except RuntimeError:
            # The loop is closed during teardown. Maintenance on that loop
            # cannot recover this callback; queued payload ownership is unchanged.
            pass

    def _emit_default_probe_resolved(self, attempt: DefaultProbeAttempt) -> None:
        self._events.put_nowait(DefaultWorkspaceResolved(attempt))
        self._wake_master()

    def _new_owner(self, generation: int) -> _Owner:
        inbound: queue.Queue[WorkspaceControl] = queue.Queue(maxsize=0)
        stop_event = threading.Event()
        strategy = PollingStrategy(stop_event)

        def run() -> None:
            run_workspace_reactor(
                inbound, strategy, stop_event, self._events, self._wake_master
            )

        return _Owner(inbound, strategy.notify_activity, run)

    @staticmethod
    def _discard_unstarted_controls(owner: _Owner) -> None:
        """Keep a rolled-back bootstrap from granting a later-started worker work."""

        while True:
            try:
                owner.inbound.get_nowait()
            except queue.Empty:
                return

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

    def _find_default_entry(self) -> _Entry | None:
        for entry in self._entries.values():
            if entry.is_default_workspace:
                return entry
        return None

    def _pinned_default_identity(self) -> tuple[str, tuple[int, int]] | None:
        default_entry = self._find_default_entry()
        if default_entry is not None:
            return (
                default_entry.canonical_workspace,
                default_entry.directory_identity,
            )
        for candidate in self._candidates.values():
            if (
                not candidate.retiring
                and candidate.phase == "validation"
                and candidate.is_default_workspace
                and candidate.canonical_workspace is not None
                and candidate.directory_identity is not None
            ):
                return (
                    candidate.canonical_workspace,
                    candidate.directory_identity,
                )
        return None

    def _find_default_or_path_candidate(self, locator: str) -> _Candidate | None:
        for candidate in self._candidates.values():
            if (
                (not candidate.retiring and candidate.is_default_workspace)
                or candidate.locator == locator
                or candidate.canonical_workspace == locator
            ):
                return candidate
        return None

    def _has_other_default_owner(
        self,
        canonical: str,
        identity: tuple[int, int],
        *,
        exclude_generation: int,
    ) -> bool:
        for entry in self._entries.values():
            if entry.is_default_workspace and not self._same_workspace(
                canonical,
                identity,
                entry.canonical_workspace,
                entry.directory_identity,
            ):
                return True
        for other in self._candidates.values():
            if (
                other.generation == exclude_generation
                or other.retiring
                or other.phase != "validation"
                or not other.is_default_workspace
                or other.canonical_workspace is None
                or other.directory_identity is None
            ):
                continue
            if not self._same_workspace(
                canonical,
                identity,
                other.canonical_workspace,
                other.directory_identity,
            ):
                return True
        return False

    def _select_request_locator(self, workspace: str | None) -> tuple[str, bool]:
        if workspace is not None:
            if not os.path.isabs(workspace):
                raise WorkspaceToolError(WORKSPACE_ABSOLUTE)
            return workspace, False
        if self._defaults.workspace is not None:
            return self._defaults.workspace, True
        raise WorkspaceToolError(WORKSPACE_ABSOLUTE)

    def _resolve_request(
        self,
        workspace: str | None,
        token: str | None,
    ) -> _ResolvedRequest:
        if workspace is not None and not _is_strict_utf8(workspace):
            raise WorkspaceToolError(WORKSPACE_PATH_UTF8)
        if token is not None and not _is_strict_utf8(token):
            raise WorkspaceToolError(WORKSPACE_TOKEN_UTF8)
        locator, used_default_workspace = self._select_request_locator(workspace)

        if token is not None:
            if token == "":
                raise WorkspaceToolError(IDENTITY_INVALID)
            return _ResolvedRequest(
                locator=locator,
                request_token=token,
                as_name=None,
                used_default_workspace=used_default_workspace,
                require_default_workspace=False,
            )
        if self._defaults.token is not None:
            return _ResolvedRequest(
                locator=locator,
                request_token=self._defaults.token,
                as_name=None,
                used_default_workspace=used_default_workspace,
                require_default_workspace=True,
            )
        if self._defaults.as_name is not None:
            return _ResolvedRequest(
                locator=locator,
                request_token=None,
                as_name=self._defaults.as_name,
                used_default_workspace=used_default_workspace,
                require_default_workspace=False,
            )
        raise WorkspaceToolError(IDENTITY_INVALID)

    def _check_entry_selector(
        self,
        entry: _Entry,
        *,
        token: str | None,
        require_default_workspace: bool,
    ) -> dict[str, Any]:
        if require_default_workspace and not entry.is_default_workspace:
            raise WorkspaceToolError(NON_DEFAULT_WORKSPACE_TOKEN_REQUIRED)
        if entry.status != "ready":
            raise WorkspaceToolError(self._entry_error(entry))
        if token is not None:
            if entry.token == token:
                return tool_result([_workspace_record(entry)])
            raise WorkspaceToolError(WORKSPACE_CONFLICT)
        if entry.matches_default_as:
            return tool_result([_workspace_record(entry)])
        raise WorkspaceToolError(WORKSPACE_CONFLICT)

    def _preflight_workspace(
        self,
        request: _ResolvedRequest,
    ) -> dict[str, Any] | None:
        """Return an existing result or admit a new workspace candidate."""

        if request.used_default_workspace:
            default_entry = self._find_default_entry()
            if default_entry is not None:
                return self._check_entry_selector(
                    default_entry,
                    token=request.request_token,
                    require_default_workspace=request.require_default_workspace,
                )
            if self._find_default_or_path_candidate(request.locator) is not None:
                raise WorkspaceToolError(WORKSPACE_BUSY)
        else:
            entry = self._entries.get(request.locator)
            if entry is not None:
                return self._check_entry_selector(
                    entry,
                    token=request.request_token,
                    require_default_workspace=request.require_default_workspace,
                )
            if self._find_candidate_by_path(request.locator) is not None:
                raise WorkspaceToolError(WORKSPACE_BUSY)
        if len(self._entries) + len(self._candidates) >= MAX_WORKSPACES:
            raise WorkspaceToolError(WORKSPACE_LIMIT)
        return None

    def _entry_error(self, entry: _Entry) -> str:
        if entry.attach_timed_out:
            return WORKSPACE_ATTACH_TIMEOUT
        if entry.status == "identity_lost":
            return WORKSPACE_IDENTITY_LOST
        if entry.status == "reactor_failed":
            return WORKSPACE_REACTOR_FAILED
        return WORKSPACE_BUSY

    def attach_workspace(
        self,
        workspace: str | None,
        token: str | None,
    ) -> Coroutine[Any, Any, dict[str, Any]]:
        """Eagerly ensure one workspace and return its published record."""

        return self.ensure_workspace(workspace, token)

    async def ensure_workspace(
        self,
        workspace: str | None,
        token: str | None,
    ) -> dict[str, Any]:
        """Resolve, validate, and retain one workspace owner if it is missing."""

        if self._closing:
            raise WorkspaceToolError(ATTACHMENT_FAILED)
        self._drain_events()
        request = self._resolve_request(workspace, token)

        existing = self._preflight_workspace(request)
        if existing is not None:
            return existing

        generation = self._next_generation
        self._next_generation += 1
        future: asyncio.Future[dict[str, Any]] = self._loop.create_future()
        owner: _Owner | None = None
        candidate: _Candidate | None = None
        try:
            owner = self._new_owner(generation)
            candidate = _Candidate(
                generation,
                request.locator,
                request.request_token,
                owner,
                future,
                used_default_workspace=request.used_default_workspace,
                require_default_workspace=request.require_default_workspace,
            )
            self._candidates[generation] = candidate
            owner.completion = self._executor.submit(owner.run)
            owner.completion.add_done_callback(lambda _: self._wake_master())
            owner.send(
                Bootstrap(
                    generation,
                    request.locator,
                    request.request_token,
                    as_name=request.as_name,
                    configured_as_name=self._defaults.as_name,
                    default_workspace=self._defaults.workspace,
                    pinned_default_workspace=self._pinned_default_identity(),
                    default_probe=self._default_probe,
                    used_default_workspace=request.used_default_workspace,
                    require_default_workspace=request.require_default_workspace,
                )
            )
        except Exception:  # noqa: BLE001 approved [DOM-10.2.1] [RUFF-SUP-066] exception
            if owner is not None:
                self._discard_unstarted_controls(owner)
                # A submitted worker may begin after this rollback. Stop releases it.
                owner.send(StopWorkspace(generation))
            self._candidates.pop(generation, None)
            future.cancel()
            raise WorkspaceToolError(ATTACHMENT_FAILED) from None
        if candidate is None:
            raise AssertionError("started owner requires a hidden candidate")
        candidate.deadline = self._loop.call_later(
            PHASE_TIMEOUT_SECONDS, self._candidate_timeout, generation, "resolution"
        )
        # Cancellation drops only this waiter. The child lifecycle keeps running.
        return await _await_owned_future(future)

    def _select_detach_entry(
        self,
        workspace: str | None,
    ) -> tuple[str, _Entry] | None:
        if workspace is None:
            if self._defaults.workspace is None:
                raise WorkspaceToolError(WORKSPACE_ABSOLUTE)
            entry = self._find_default_entry()
            if entry is None:
                if (
                    self._find_default_or_path_candidate(self._defaults.workspace)
                    is not None
                ):
                    raise WorkspaceToolError(WORKSPACE_BUSY)
                return None
            return entry.canonical_workspace, entry
        entry = self._entries.get(workspace)
        if entry is None:
            if self._find_candidate_by_path(workspace) is not None:
                raise WorkspaceToolError(WORKSPACE_BUSY)
            return None
        return workspace, entry

    async def detach_workspace(self, workspace: str | None) -> dict[str, Any]:
        if self._closing:
            raise WorkspaceToolError(ATTACHMENT_FAILED)
        self._drain_events()
        selected = self._select_detach_entry(workspace)
        if selected is None:
            return tool_result([])
        workspace_key, entry = selected
        self._prune_cancelled_queued_commands(entry)
        if (
            entry.status == "detaching"
            or entry.detach_future is not None
            or entry.active_command_id is not None
            or entry.queued_commands
        ):
            raise WorkspaceToolError(WORKSPACE_BUSY)

        prior_record = _workspace_record(entry)
        if not entry.owner.alive():
            self._entries.pop(workspace_key, None)
            self._recompute_resource()
            return tool_result([{**prior_record, "status": "detached"}])
        entry.status = "detaching"
        entry.notifications = ()
        entry.truncated = False
        entry.detach_record = prior_record
        entry.detach_future = self._loop.create_future()
        entry.owner.send(StopWorkspace(entry.generation))
        entry.detach_deadline = self._loop.call_later(
            DETACH_JOIN_SECONDS,
            self._detach_timeout,
            workspace_key,
            entry.generation,
        )
        self._recompute_resource()
        return await _await_owned_future(entry.detach_future)

    async def execute_tool(
        self,
        workspace: str | None,
        token: str | None,
        name: str,
        arguments: dict[str, object],
    ) -> dict[str, Any]:
        """Route one CLI-shaped operation through its owning child reactor."""

        if name not in DOMAIN_TOOL_NAMES:
            raise AssertionError(f"unregistered ordinary tool: {name}")
        ensure = self.ensure_workspace(workspace, token)
        ensured = await ensure
        records = ensured["records"]
        if not records or not isinstance(records[0].get("workspace"), str):
            raise AssertionError("successful ensure requires an attach record")
        canonical_workspace: str = records[0]["workspace"]
        return await self._execute_ready_tool(
            canonical_workspace,
            name,
            arguments,
        )

    @staticmethod
    def _prune_cancelled_queued_commands(entry: _Entry) -> None:
        if not entry.queued_commands:
            return
        kept: deque[_QueuedCommand] = deque()
        for item in entry.queued_commands:
            if item.canceled or item.waiter.cancelled():
                item.canceled = True
                if not item.future.done():
                    item.future.cancel()
            else:
                kept.append(item)
        entry.queued_commands = kept

    def _promote_next_queued_command(self, entry: _Entry) -> None:
        self._prune_cancelled_queued_commands(entry)
        if not entry.queued_commands or entry.status != "ready":
            return
        nxt = entry.queued_commands.popleft()
        entry.active_command_id = nxt.command_id
        entry.command_future = nxt.future
        entry.owner.send(
            RunWorkspaceCommand(
                entry.generation,
                nxt.command_id,
                nxt.name,
                nxt.arguments,
            )
        )

    def _admit_ready_command(
        self,
        entry: _Entry,
        name: str,
        frozen: CommandArguments,
    ) -> tuple[int, _QueuedCommand | None, asyncio.Future[_CommandCompletion]]:
        command_id = self._next_command_id
        self._next_command_id += 1
        future: asyncio.Future[_CommandCompletion] = self._loop.create_future()
        waiter = _bind_waiter(self._loop, future)
        if entry.active_command_id is None:
            entry.active_command_id = command_id
            entry.command_future = future
            entry.owner.send(
                RunWorkspaceCommand(entry.generation, command_id, name, frozen)
            )
            return command_id, None, waiter
        if len(entry.queued_commands) >= MAX_QUEUED_COMMANDS:
            future.cancel()
            waiter.cancel()
            raise WorkspaceToolError(WORKSPACE_BUSY)
        queued = _QueuedCommand(command_id, name, frozen, future, waiter)
        entry.queued_commands.append(queued)
        return command_id, queued, waiter

    def _cancel_ready_command(
        self,
        canonical_workspace: str,
        entry: _Entry,
        command_id: int,
        queued: _QueuedCommand | None,
    ) -> None:
        if queued is not None and queued in entry.queued_commands:
            queued.canceled = True
            entry.queued_commands.remove(queued)
            if not queued.future.done():
                queued.future.cancel()
            return
        current = self._entries.get(canonical_workspace)
        if (
            current is entry
            and entry.active_command_id == command_id
            and entry.status == "ready"
        ):
            entry.owner.send(CancelWorkspaceCommand(entry.generation, command_id))

    async def _execute_ready_tool(
        self,
        canonical_workspace: str,
        name: str,
        arguments: dict[str, object],
    ) -> dict[str, Any]:
        """Admit one command against an already ensured canonical workspace."""

        # No suspension occurs before this admission/send sequence. It is the
        # master-loop linearization point for cancellation versus command
        # creation after ensure.
        entry = self._entries.get(canonical_workspace)
        if entry is None:
            raise AssertionError("successful ensure requires a published entry")
        if entry.status != "ready":
            raise WorkspaceToolError(self._entry_error(entry))
        self._prune_cancelled_queued_commands(entry)

        frozen = _freeze_command_arguments(arguments)
        command_id, queued, waiter = self._admit_ready_command(entry, name, frozen)
        try:
            completion = await waiter
        except asyncio.CancelledError:
            self._cancel_ready_command(canonical_workspace, entry, command_id, queued)
            raise
        if completion.error is not None:
            raise WorkspaceToolError(completion.error)
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
        return tool_result(records, warnings=warnings)

    def subscribe(self, sender: Callable[[], Awaitable[None]]) -> None:
        self._subscribed = True
        self._resource_sender = sender
        if self.current_text != self.last_signalled_text:
            self._signal_resource_change()

    def unsubscribe(self) -> None:
        self._subscribed = False
        self._resource_sender = None

    def configure_modern_resource_sender(
        self,
        sender: Callable[[], Awaitable[None]],
    ) -> None:
        """Install the process-wide modern subscription-bus publisher."""

        if self._closing or self._modern_resource_sender is not None:
            return
        self._modern_resource_sender = sender

    def _signal_resource_change(self) -> None:
        if self._closing or not self._subscribed or self._resource_sender is None:
            return
        self.last_signalled_text = self.current_text
        future = asyncio.ensure_future(self._resource_sender(), loop=self._loop)
        self._resource_tasks.add(future)
        future.add_done_callback(self._finish_resource_attempt)

    def _signal_modern_change(self) -> None:
        if self._closing or self._modern_resource_sender is None:
            return
        try:
            awaitable = self._modern_resource_sender()
        except Exception:  # noqa: BLE001 approved [DOM-10.2.1] [RUFF-SUP-066] exception
            return
        future = asyncio.ensure_future(awaitable, loop=self._loop)
        self._resource_tasks.add(future)
        future.add_done_callback(self._finish_resource_attempt)

    def _finish_resource_attempt(self, future: asyncio.Future[None]) -> None:
        self._resource_tasks.discard(future)
        with suppress(asyncio.CancelledError, Exception):
            future.result()

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
        self._signal_modern_change()

    def _candidate_timeout(self, generation: int, expected_phase: str) -> None:
        if self._closing:
            return
        candidate = self._candidates.get(generation)
        if candidate is None or candidate.retiring or candidate.phase != expected_phase:
            return
        candidate.retiring = True
        candidate.retired_at = self._loop.time()
        candidate.warning_due = expected_phase == "resolution"
        candidate.token = None
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
                attach_timed_out=True,
                is_default_workspace=candidate.is_default_workspace,
                pending_default_probes=(
                    [candidate.pending_default_probe]
                    if not candidate.is_default_workspace
                    and candidate.pending_default_probe is not None
                    else []
                ),
            )
            candidate.is_default_workspace = False
            candidate.pending_default_probe = None
            self._entries[entry.canonical_workspace] = entry
            self._candidates.pop(generation, None)
            self._recompute_resource()
            self._fail_future(candidate.future, WORKSPACE_ATTACH_TIMEOUT)
            return
        candidate.is_default_workspace = False
        candidate.pending_default_probe = None
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
        if not entry.owner.alive():
            self._complete_detach(workspace, entry)
            return
        entry.status = "reactor_failed"
        entry.token = None
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
        entry.token = None
        self._entries.pop(workspace, None)
        self._recompute_resource()
        if future is not None and not future.done():
            future.set_result(tool_result([{**record, "status": "detached"}]))

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
        candidate.token = None
        candidate.is_default_workspace = False
        candidate.pending_default_probe = None
        if candidate.deadline is not None:
            candidate.deadline.cancel()
            candidate.deadline = None
        candidate.owner.send(StopWorkspace(candidate.generation))
        if result is not None and not candidate.future.done():
            candidate.future.set_result(result)
        elif error is not None:
            self._fail_future(candidate.future, error)

    def _consume_completed_probe_match(
        self,
        event: WorkspaceResolved,
    ) -> tuple[bool, DefaultProbeAttempt | None]:
        pending_probe = event.pending_default_probe
        if event.is_default_workspace or pending_probe is None:
            return False, None
        if not pending_probe.done.is_set():
            return False, pending_probe
        result = pending_probe.result
        if result is None:
            return False, None
        matched = self._same_workspace(
            event.canonical_workspace,
            event.directory_identity,
            result[0],
            result[1],
        )
        return matched, None

    def _arbitrate_default_workspace(
        self,
        candidate: _Candidate,
        event: WorkspaceResolved,
        *,
        is_default_candidate: bool,
    ) -> bool | None:
        if not is_default_candidate:
            return False
        if not self._has_other_default_owner(
            event.canonical_workspace,
            event.directory_identity,
            exclude_generation=event.generation,
        ):
            return True
        if candidate.used_default_workspace:
            self._retire_candidate(candidate, error=WORKSPACE_BUSY)
            return None
        if candidate.require_default_workspace:
            self._retire_candidate(
                candidate,
                error=NON_DEFAULT_WORKSPACE_TOKEN_REQUIRED,
            )
            return None
        return False

    def _arbitrate_existing_entry(
        self,
        candidate: _Candidate,
        event: WorkspaceResolved,
        *,
        effective_is_default: bool,
        pending_probe: DefaultProbeAttempt | None,
    ) -> bool:
        for entry in self._entries.values():
            if not self._same_workspace(
                event.canonical_workspace,
                event.directory_identity,
                entry.canonical_workspace,
                entry.directory_identity,
            ):
                continue
            try:
                result = self._check_entry_selector(
                    entry,
                    token=candidate.token,
                    require_default_workspace=(
                        candidate.require_default_workspace and not effective_is_default
                    ),
                )
            except WorkspaceToolError as exc:
                self._retire_candidate(candidate, error=str(exc))
            else:
                if effective_is_default:
                    entry.is_default_workspace = True
                    entry.pending_default_probes.clear()
                    self._clear_pending_default_probes()
                elif (
                    pending_probe is not None
                    and entry.status != "detaching"
                    and self._pinned_default_identity() is None
                    and all(
                        item is not pending_probe
                        for item in entry.pending_default_probes
                    )
                ):
                    entry.pending_default_probes.append(pending_probe)
                self._retire_candidate(candidate, result=result)
            return True
        return False

    def _has_same_workspace_candidate(self, event: WorkspaceResolved) -> bool:
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
                return True
        return False

    def _on_resolved(self, event: WorkspaceResolved) -> None:
        candidate = self._candidates.get(event.generation)
        if candidate is None or candidate.retiring or candidate.phase != "resolution":
            return
        candidate.canonical_workspace = event.canonical_workspace
        candidate.directory_identity = event.directory_identity
        candidate.backend = event.backend

        probe_matched, pending_probe = self._consume_completed_probe_match(event)
        effective_is_default = self._arbitrate_default_workspace(
            candidate,
            event,
            is_default_candidate=event.is_default_workspace or probe_matched,
        )
        if effective_is_default is None:
            return
        if self._arbitrate_existing_entry(
            candidate,
            event,
            effective_is_default=effective_is_default,
            pending_probe=pending_probe,
        ):
            return
        if self._has_same_workspace_candidate(event):
            self._retire_candidate(candidate, error=WORKSPACE_BUSY)
            return

        if candidate.deadline is not None:
            candidate.deadline.cancel()
        candidate.is_default_workspace = effective_is_default
        candidate.pending_default_probe = (
            None if effective_is_default else pending_probe
        )
        if effective_is_default:
            self._clear_pending_default_probes()
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
        assert candidate.canonical_workspace is not None
        assert candidate.directory_identity is not None
        assert candidate.backend is not None
        if candidate.deadline is not None:
            candidate.deadline.cancel()
        effective_token = event.token or candidate.token
        assert effective_token is not None
        entry = _Entry(
            event.generation,
            candidate.canonical_workspace,
            candidate.directory_identity,
            candidate.backend,
            event.member_id,
            event.name,
            effective_token,
            candidate.owner,
            notifications=event.notifications,
            truncated=event.truncated,
            is_default_workspace=candidate.is_default_workspace,
            matches_default_as=event.matches_default_as,
            pending_default_probes=(
                [candidate.pending_default_probe]
                if not candidate.is_default_workspace
                and candidate.pending_default_probe is not None
                else []
            ),
        )
        self._candidates.pop(event.generation, None)
        candidate.token = None
        candidate.is_default_workspace = False
        candidate.pending_default_probe = None
        self._entries[entry.canonical_workspace] = entry
        self._recompute_resource()
        if not candidate.future.done():
            candidate.future.set_result(tool_result([_workspace_record(entry)]))

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
        self._promote_next_queued_command(entry)
        if future is None or future.done():
            return
        if event.canceled:
            future.cancel()
            return
        payload = tool_result(
            [record_object(record) for record in event.records],
            warnings=list(event.warnings),
        )
        future.set_result(_CommandCompletion(payload=payload, error=event.error))

    def _settle_commands(self, entry: _Entry, error: str) -> None:
        self._prune_cancelled_queued_commands(entry)
        future = entry.command_future
        queued = list(entry.queued_commands)
        entry.active_command_id = None
        entry.command_future = None
        entry.queued_commands.clear()
        if future is not None and not future.done():
            future.set_result(_CommandCompletion(error=error))
        for item in queued:
            if not item.future.done():
                item.future.set_result(_CommandCompletion(error=error))

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
        entry.token = None
        entry.notifications = ()
        entry.truncated = False
        self._recompute_resource()
        self._settle_commands(entry, self._entry_error(entry))

    def _clear_pending_default_probes(self) -> None:
        for entry in self._entries.values():
            entry.pending_default_probes.clear()
        for candidate in self._candidates.values():
            candidate.pending_default_probe = None

    def _reconcile_entry_default_probe(
        self,
        attempt: DefaultProbeAttempt,
        result: tuple[str, tuple[int, int]] | None,
    ) -> bool:
        for entry in self._entries.values():
            if all(item is not attempt for item in entry.pending_default_probes):
                continue
            entry.pending_default_probes = [
                item for item in entry.pending_default_probes if item is not attempt
            ]
            if (
                result is not None
                and entry.status != "detaching"
                and self._same_workspace(
                    result[0],
                    result[1],
                    entry.canonical_workspace,
                    entry.directory_identity,
                )
            ):
                entry.is_default_workspace = True
                self._clear_pending_default_probes()
                return True
        return False

    def _reconcile_candidate_default_probe(
        self,
        attempt: DefaultProbeAttempt,
        result: tuple[str, tuple[int, int]] | None,
    ) -> bool:
        for candidate in self._candidates.values():
            if candidate.pending_default_probe is not attempt:
                continue
            candidate.pending_default_probe = None
            if (
                result is not None
                and not candidate.retiring
                and candidate.phase == "validation"
                and candidate.canonical_workspace is not None
                and candidate.directory_identity is not None
                and self._same_workspace(
                    result[0],
                    result[1],
                    candidate.canonical_workspace,
                    candidate.directory_identity,
                )
            ):
                candidate.is_default_workspace = True
                self._clear_pending_default_probes()
                return True
        return False

    def _on_default_workspace_resolved(
        self,
        event: DefaultWorkspaceResolved,
    ) -> None:
        if self._closing or self._pinned_default_identity() is not None:
            self._clear_pending_default_probes()
            return
        result = event.attempt.result
        if self._reconcile_entry_default_probe(event.attempt, result):
            return
        self._reconcile_candidate_default_probe(event.attempt, result)

    def _drain_events(self) -> None:  # noqa: C901 approved [DOM-10.2.1] [RUFF-SUP-015] exception
        while True:
            try:
                event = self._events.get_nowait()
            except queue.Empty:
                break
            if isinstance(event, WorkspaceResolved):
                self._on_resolved(event)
            elif isinstance(event, DefaultWorkspaceResolved):
                self._on_default_workspace_resolved(event)
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
                # The event is a liveness cue, not proof that the workspace callable has
                # returned. Executor completion owns that distinction.
                pass
        self._reap_dead_owners()

    def _reap_dead_owners(self) -> None:
        if self._closing:
            return
        for generation, candidate in list(self._candidates.items()):
            if candidate.owner.alive():
                continue
            candidate.token = None
            if not candidate.future.done():
                self._fail_future(candidate.future, ATTACHMENT_FAILED)
            self._candidates.pop(generation, None)

        for workspace, entry in list(self._entries.items()):
            if entry.owner.alive():
                continue
            if entry.status == "detaching":
                self._complete_detach(workspace, entry)
                continue
            if entry.status == "ready":
                self._diagnostic(WORKSPACE_REACTOR_FAILURE_DIAGNOSTIC)
                entry.status = "reactor_failed"
                entry.token = None
                entry.notifications = ()
                entry.truncated = False
                self._recompute_resource()
                self._settle_commands(entry, WORKSPACE_REACTOR_FAILED)

    async def aclose(self) -> None:  # noqa: C901 approved [DOM-10.2.1] [RUFF-SUP-016] exception
        if self._closing:
            return
        self._closing = True
        resource_tasks = list(self._resource_tasks)
        for task in resource_tasks:
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
            candidate.token = None
            candidate.is_default_workspace = False
            candidate.pending_default_probe = None
            owners[candidate.generation] = candidate.owner
        for entry in self._entries.values():
            if entry.detach_deadline is not None:
                entry.detach_deadline.cancel()
                entry.detach_deadline = None
            if entry.detach_future is not None and not entry.detach_future.done():
                entry.detach_future.cancel()
            if entry.command_future is not None and not entry.command_future.done():
                entry.command_future.cancel()
            for queued in entry.queued_commands:
                if not queued.future.done():
                    queued.future.cancel()
            entry.queued_commands.clear()
            entry.pending_default_probes.clear()
            entry.active_command_id = None
            entry.command_future = None
            entry.token = None
            owners[entry.generation] = entry.owner
        for generation, owner in owners.items():
            owner.send(StopWorkspace(generation))

        completions = [
            asyncio.wrap_future(owner.completion)
            for owner in owners.values()
            if owner.completion is not None
        ]
        if completions:
            _, pending = await asyncio.wait(completions, timeout=SHUTDOWN_SECONDS)
            if pending:
                try:
                    os.write(
                        2,
                        b"taut-mcp: shutdown deadline exceeded; forcing exit\n",
                    )
                finally:
                    os._exit(1)
            # Retrieve worker failures after every owner has returned. Published
            # events own public diagnostics; completion owns resource retirement.
            await asyncio.gather(*completions, return_exceptions=True)
        self._executor.shutdown(wait=False)
        self._drain_events()
        if resource_tasks:
            await asyncio.gather(*resource_tasks, return_exceptions=True)
        self._candidates.clear()
        self._entries.clear()
        self.current_text = '{"workspaces":[]}'
