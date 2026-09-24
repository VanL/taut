"""Child-thread workspace ownership for [MCP-4] and [MCP-8]."""

from __future__ import annotations

import os
import queue
import time
import tomllib
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path
from threading import Event
from typing import TypeAlias

from simplebroker import (
    BrokerTarget,
    Config,
    resolve_broker_target,
)
from simplebroker.watcher import PollingStrategy

from taut import (
    BlankMessageError,
    EmptyResultError,
    NotFoundError,
    Notification,
    ReactionConfigurationError,
    TautClient,
    TautError,
    TokenError,
)
from taut._cleanup import capture_cleanup_failure
from taut._config import load_config
from taut._constants import CACHE_STALE_QUEUE_NAME
from taut._exceptions import IdentityError, NotInitializedError
from taut.watcher import BaseReactor, QueueMessageContext, QueueMode

from ._commands import (
    CommandArguments,
    CommandRecord,
    execute_command,
)

PROJECT_NOT_FOUND = (
    "workspace project not found; initialize Taut there or choose another directory"
)
DIRECTORY_IDENTITY_UNAVAILABLE = (
    "workspace directory identity unavailable; choose a workspace with stable "
    "directory identity"
)
CONFIGURATION_UNAVAILABLE = (
    "workspace configuration or backend unavailable; fix the workspace "
    "configuration or backend and retry"
)
IDENTITY_INVALID = (
    "workspace identity invalid; provide a valid existing continuity token"
)
ATTACHMENT_FAILED = "workspace attachment failed; use list_workspaces before retrying"
INVALID_UTF8_PATH = (
    "workspace path is not valid UTF-8; provide an absolute UTF-8 workspace path"
)
SNAPSHOT_INTERVAL_SECONDS = 0.5
NOT_FOUND_IS_ERROR_TOOLS = frozenset(
    {
        "channel_rename",
        "channel_show",
        "channel_topic",
        "leave",
        "reply",
        "say",
    }
)
_monotonic = time.monotonic
_directory_stat = os.stat


class _WorkspaceResolutionError(RuntimeError):
    """A fixed, public workspace resolution failure."""


@dataclass(slots=True)
class Bootstrap:
    generation: int
    locator: str
    token: str


@dataclass(frozen=True, slots=True)
class GrantValidation:
    generation: int


@dataclass(frozen=True, slots=True)
class StopWorkspace:
    generation: int


@dataclass(frozen=True, slots=True)
class RunWorkspaceCommand:
    generation: int
    command_id: int
    name: str
    arguments: CommandArguments


@dataclass(frozen=True, slots=True)
class CancelWorkspaceCommand:
    generation: int
    command_id: int


WorkspaceControl: TypeAlias = (
    Bootstrap
    | GrantValidation
    | StopWorkspace
    | RunWorkspaceCommand
    | CancelWorkspaceCommand
)


class _RefreshOutcome(Enum):
    REFRESHED = auto()
    IDENTITY_LOST = auto()
    CRASHED = auto()


@dataclass(frozen=True, slots=True)
class WorkspaceResolved:
    generation: int
    canonical_workspace: str
    directory_identity: tuple[int, int]
    backend: str


@dataclass(frozen=True, slots=True)
class WorkspaceReady:
    generation: int
    member_id: str
    name: str
    notifications: tuple[Notification, ...]
    truncated: bool


@dataclass(frozen=True, slots=True)
class WorkspaceSnapshot:
    generation: int
    notifications: tuple[Notification, ...]
    truncated: bool


@dataclass(frozen=True, slots=True)
class WorkspaceIdentityLost:
    generation: int


@dataclass(frozen=True, slots=True)
class WorkspaceFailed:
    generation: int
    phase: str
    message: str


@dataclass(frozen=True, slots=True)
class WorkspaceCrashed:
    generation: int


@dataclass(frozen=True, slots=True)
class WorkspaceStopped:
    generation: int


@dataclass(frozen=True, slots=True)
class WorkspaceCommandOutcome:
    generation: int
    command_id: int
    name: str
    records: tuple[CommandRecord, ...]
    warnings: tuple[str, ...]
    notifications: tuple[Notification, ...]
    truncated: bool
    error: str | None = None
    canceled: bool = False


WorkspaceEvent: TypeAlias = (
    WorkspaceResolved
    | WorkspaceReady
    | WorkspaceSnapshot
    | WorkspaceIdentityLost
    | WorkspaceFailed
    | WorkspaceCrashed
    | WorkspaceStopped
    | WorkspaceCommandOutcome
)


def _strict_utf8(value: str) -> None:
    value.encode("utf-8", errors="strict")


def _workspace_owner(target: BrokerTarget) -> Path:
    if target.project_root is not None:
        return target.project_root
    if target.backend_name == "sqlite":
        return Path(target.target).parent
    if target.config_path is not None:
        return target.config_path.parent
    raise RuntimeError("resolved target does not identify a project directory")


def _resolve_workspace(
    locator: str,
) -> tuple[BrokerTarget, Config, str, tuple[int, int]]:
    # Explicit workspace resolution outranks the ambient direct-path selector.
    config = load_config({"TAUT_DB": ""})
    try:
        target = resolve_broker_target(locator, config=config)
    except tomllib.TOMLDecodeError as exc:
        raise _WorkspaceResolutionError(CONFIGURATION_UNAVAILABLE) from exc
    except ValueError as exc:
        raise NotInitializedError(PROJECT_NOT_FOUND) from exc
    except RuntimeError as exc:
        raise _WorkspaceResolutionError(CONFIGURATION_UNAVAILABLE) from exc
    if target is None:
        raise NotInitializedError(PROJECT_NOT_FOUND)
    owner = _workspace_owner(target)
    canonical = os.path.realpath(owner)
    try:
        _strict_utf8(canonical)
    except UnicodeEncodeError as exc:
        raise ValueError(INVALID_UTF8_PATH) from exc
    try:
        stat = _directory_stat(canonical)
    except OSError as exc:
        raise _WorkspaceResolutionError(DIRECTORY_IDENTITY_UNAVAILABLE) from exc
    directory_identity = (int(stat.st_dev), int(stat.st_ino))
    if directory_identity == (0, 0):
        raise _WorkspaceResolutionError(DIRECTORY_IDENTITY_UNAVAILABLE)
    return target, config, canonical, directory_identity


class _WorkspaceReactor(BaseReactor):
    """One admitted workspace's policy over the shared watcher lifecycle."""

    def __init__(
        self,
        inbound: queue.Queue[WorkspaceControl],
        strategy: PollingStrategy,
        stop_event: Event,
        outbound: queue.Queue[WorkspaceEvent],
        wake_master: Callable[[], None],
        *,
        generation: int,
        client: TautClient,
        target: BrokerTarget,
        config: Config,
    ) -> None:
        self.inbound = inbound
        self.outbound = outbound
        self.wake_master = wake_master
        self.generation = generation
        self.client = client
        self.target = target
        self.config = config
        self.previous_snapshot: tuple[Notification, ...] = ()
        self.previous_truncated = False
        self.last_finished_command_id = -1
        self.last_snapshot_at = float("-inf")
        self.snapshot_pending = False
        self.crash_capture_attempted = False
        member = client.peek_identity()
        notification_queue = client.notification_activity_queue()
        super().__init__(
            {
                name: {"handler": self._source_changed, "mode": QueueMode.PEEK}
                for name in (notification_queue.name, CACHE_STALE_QUEUE_NAME)
            },
            db=target,
            config=config,
            persistent=True,
            stop_event=stop_event,
            polling_strategy=strategy,
        )
        try:
            for name in self.list_queues():
                source = self.get_queue(name)
                assert source is not None
                self._cursors[name] = source.latest_pending_timestamp() or 0
            pending = tuple(client.peek_inbox(limit=101))
        except BaseException:
            self.stop(join=False)
            raise
        self.previous_snapshot = pending[:100]
        self.previous_truncated = len(pending) > 100
        self._emit(
            WorkspaceReady(
                generation,
                member.member_id,
                member.name,
                self.previous_snapshot,
                self.previous_truncated,
            )
        )

    def _emit(self, event: WorkspaceEvent) -> None:
        self.outbound.put_nowait(event)
        self.wake_master()

    def _drain_controls(self) -> list[WorkspaceControl]:
        controls: list[WorkspaceControl] = []
        while True:
            try:
                controls.append(self.inbound.get_nowait())
            except queue.Empty:
                return controls

    def _source_changed(
        self, body: str, timestamp: int, context: QueueMessageContext
    ) -> None:
        del body
        self.snapshot_pending = True
        self._cursors[context.queue_name] = timestamp

    def next_wait_timeout(self) -> float | None:
        if not self.snapshot_pending:
            return None
        return max(
            0.0, self.last_snapshot_at + SNAPSHOT_INTERVAL_SECONDS - _monotonic()
        )

    def _process_reactor_turn(self) -> None:
        controls = self._drain_controls()
        if any(
            isinstance(item, StopWorkspace) and item.generation == self.generation
            for item in controls
        ):
            self.request_stop()
            return
        if self._handle_command(controls) is False:
            self.request_stop()
            return
        super()._process_reactor_turn()
        if not self._publish_snapshot_if_due():
            self.request_stop()

    def _close_reactor_resources(self) -> None:
        failure = capture_cleanup_failure(None, super()._close_reactor_resources)
        failure = capture_cleanup_failure(failure, self.client.close)
        if failure is not None:
            raise failure

    def _execute_command(self, command: RunWorkspaceCommand) -> bool:
        self.client.last_notification_warnings.clear()
        self.client.last_search_warnings.clear()
        command_records: tuple[CommandRecord, ...] = ()
        command_error: str | None = None
        try:
            command_records = execute_command(
                self.client, command.name, command.arguments
            )
        except TokenError:
            self._emit(WorkspaceIdentityLost(self.generation))
            return False
        except BlankMessageError as exc:
            command_error = str(exc)
        except NotFoundError as exc:
            if command.name in NOT_FOUND_IS_ERROR_TOOLS:
                command_error = str(exc)
            # Every other tool intentionally keeps the general empty result.
        except EmptyResultError:
            pass
        except (TautError, TypeError, ValueError) as exc:
            command_error = str(exc)
        except Exception as exc:  # noqa: BLE001 approved [DOM-10.2.1] [RUFF-SUP-066] exception
            self._capture_crash(exc, operation=f"workspace.command:{command.name}")
            self._emit(WorkspaceCrashed(self.generation))
            return False
        refresh_outcome = self._refresh_after_command(command.name)
        if refresh_outcome is _RefreshOutcome.IDENTITY_LOST:
            return False
        if refresh_outcome is _RefreshOutcome.CRASHED:
            return False
        assert refresh_outcome is _RefreshOutcome.REFRESHED
        self._emit(
            WorkspaceCommandOutcome(
                self.generation,
                command.command_id,
                command.name,
                command_records,
                (
                    *self.client.last_notification_warnings,
                    *self.client.last_search_warnings,
                ),
                self.previous_snapshot,
                self.previous_truncated,
                error=command_error,
            )
        )
        return True

    def _refresh_after_command(self, command_name: str) -> _RefreshOutcome:
        if command_name == "channel_show":
            return _RefreshOutcome.REFRESHED
        try:
            pending = tuple(self.client.peek_inbox(limit=101))
        except IdentityError:
            self._emit(WorkspaceIdentityLost(self.generation))
            return _RefreshOutcome.IDENTITY_LOST
        except Exception as exc:  # noqa: BLE001 approved [DOM-10.2.1] [RUFF-SUP-066] exception
            self._capture_crash(exc, operation="workspace.refresh")
            self._emit(WorkspaceCrashed(self.generation))
            return _RefreshOutcome.CRASHED
        self.previous_snapshot = pending[:100]
        self.previous_truncated = len(pending) > 100
        self.snapshot_pending = False
        return _RefreshOutcome.REFRESHED

    def _handle_command(self, controls: list[WorkspaceControl]) -> bool | None:
        cancels = {
            control.command_id
            for control in controls
            if isinstance(control, CancelWorkspaceCommand)
            and control.generation == self.generation
            and control.command_id > self.last_finished_command_id
        }
        command = next(
            (
                control
                for control in controls
                if isinstance(control, RunWorkspaceCommand)
                and control.generation == self.generation
                and control.command_id > self.last_finished_command_id
            ),
            None,
        )
        if command is None:
            return None
        self.last_finished_command_id = command.command_id
        if command.command_id not in cancels:
            return self._execute_command(command)
        self._emit(
            WorkspaceCommandOutcome(
                self.generation,
                command.command_id,
                command.name,
                (),
                (),
                self.previous_snapshot,
                self.previous_truncated,
                canceled=True,
            )
        )
        return True

    def _publish_snapshot_if_due(self) -> bool:
        now = _monotonic()
        if (
            not self.snapshot_pending
            or now < self.last_snapshot_at + SNAPSHOT_INTERVAL_SECONDS
        ):
            return True
        try:
            pending = tuple(self.client.peek_inbox(limit=101))
        except IdentityError:
            self._emit(WorkspaceIdentityLost(self.generation))
            return False
        except Exception as exc:  # noqa: BLE001 approved [DOM-10.2.1] [RUFF-SUP-066] exception
            self._capture_crash(exc, operation="workspace.snapshot")
            self._emit(WorkspaceCrashed(self.generation))
            return False
        snapshot = pending[:100]
        truncated = len(pending) > 100
        self.snapshot_pending = False
        self.last_snapshot_at = now
        if snapshot != self.previous_snapshot or truncated != self.previous_truncated:
            self.previous_snapshot = snapshot
            self.previous_truncated = truncated
            self._emit(WorkspaceSnapshot(self.generation, snapshot, truncated))
        return True

    def _capture_crash(self, exc: Exception, *, operation: str) -> None:
        """Capture at most one terminal failure for this workspace generation."""

        if self.crash_capture_attempted:
            return
        self.crash_capture_attempted = True
        from taut.debug import capture_exception

        capture_exception(
            exc,
            broker_target=self.target,
            broker_config=self.config,
            surface="mcp",
            operation=operation,
        )


def _resolve_candidate(
    bootstrap: Bootstrap,
    emit: Callable[[WorkspaceEvent], None],
) -> tuple[BrokerTarget, Config, str, tuple[int, int]] | None:
    """Keep the resolution phase's fixed public failure mapping in one place."""
    try:
        return _resolve_workspace(bootstrap.locator)
    except NotInitializedError:
        emit(WorkspaceFailed(bootstrap.generation, "resolution", PROJECT_NOT_FOUND))
        return None
    except ValueError as exc:
        emit(WorkspaceFailed(bootstrap.generation, "resolution", str(exc)))
        return None
    except _WorkspaceResolutionError as exc:
        emit(WorkspaceFailed(bootstrap.generation, "resolution", str(exc)))
        return None


def _validate_candidate(
    token: str,
    inbound: queue.Queue[WorkspaceControl],
    strategy: PollingStrategy,
    stop_event: Event,
    outbound: queue.Queue[WorkspaceEvent],
    wake_master: Callable[[], None],
    *,
    generation: int,
    target: BrokerTarget,
    config: Config,
    emit: Callable[[WorkspaceEvent], None],
) -> _WorkspaceReactor | None:
    """Construct the admitted owner or publish its fixed validation failure."""
    client: TautClient | None = None
    reactor: _WorkspaceReactor | None = None
    try:
        client = TautClient(
            broker_target=target,
            broker_config=config,
            token=token,
            persistent=True,
            inherit_environment_identity=False,
        )
        token = ""
        reactor = _WorkspaceReactor(
            inbound,
            strategy,
            stop_event,
            outbound,
            wake_master,
            generation=generation,
            client=client,
            target=target,
            config=config,
        )
        return reactor
    except IdentityError:
        emit(WorkspaceFailed(generation, "validation", IDENTITY_INVALID))
        return None
    except ReactionConfigurationError:
        emit(WorkspaceFailed(generation, "validation", CONFIGURATION_UNAVAILABLE))
        return None
    except Exception:  # noqa: BLE001 approved [DOM-10.2.1] [RUFF-SUP-066] exception
        emit(WorkspaceFailed(generation, "validation", ATTACHMENT_FAILED))
        return None

    finally:
        token = ""
        if reactor is None and client is not None:
            with suppress(Exception):
                client.close()


def run_workspace_reactor(
    inbound: queue.Queue[WorkspaceControl],
    strategy: PollingStrategy,
    stop_event: Event,
    outbound: queue.Queue[WorkspaceEvent],
    wake_master: Callable[[], None],
) -> None:
    """Resolve/admit once, then drive the shared reactor on this same thread."""
    generation = -1
    reactor: _WorkspaceReactor | None = None
    token = ""

    def emit(event: WorkspaceEvent) -> None:
        outbound.put_nowait(event)
        wake_master()

    try:
        bootstrap = inbound.get()
        if not isinstance(bootstrap, Bootstrap):
            return
        generation = bootstrap.generation
        token = bootstrap.token
        bootstrap.token = ""
        resolved = _resolve_candidate(bootstrap, emit)
        if resolved is None:
            return
        target, config, canonical, directory_identity = resolved
        emit(
            WorkspaceResolved(
                generation, canonical, directory_identity, target.backend_name
            )
        )
        grant = inbound.get()
        if not isinstance(grant, GrantValidation) or grant.generation != generation:
            return
        reactor = _validate_candidate(
            token,
            inbound,
            strategy,
            stop_event,
            outbound,
            wake_master,
            generation=generation,
            target=target,
            config=config,
            emit=emit,
        )
        token = ""
        if reactor is None:
            return
        reactor.run()
    except BaseException as exc:  # noqa: BLE001 approved [DOM-10.2.1] [RUFF-SUP-066] exception
        if generation >= 0:
            if reactor is not None and isinstance(exc, Exception):
                reactor._capture_crash(exc, operation="workspace.run")
            emit(WorkspaceCrashed(generation))
    finally:
        token = ""
        if generation >= 0:
            emit(WorkspaceStopped(generation))
