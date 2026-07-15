"""Child-thread workspace ownership for [MCP-4] and [MCP-8]."""

from __future__ import annotations

import os
import queue
import time
import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from threading import Event
from typing import Any, TypeAlias

from simplebroker import (
    ActivityWaiter,
    BrokerTarget,
    create_activity_waiter_for_queues,
    resolve_broker_target,
)

from taut import (
    BlankMessageError,
    EmptyResultError,
    Notification,
    TautClient,
    TautError,
    TokenError,
    addressing,
)
from taut._constants import DEFAULT_DB_NAME, load_config
from taut._exceptions import IdentityError, NotInitializedError

from ._commands import (
    RECORD_TYPE_BY_TOOL,
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
NOTIFICATION_BACKSTOP_SECONDS = 0.5


@dataclass(frozen=True, slots=True)
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


@dataclass(frozen=True, slots=True)
class WorkspaceResolved:
    generation: int
    canonical_workspace: str
    directory_identity: tuple[int, int]
    backend: str


@dataclass(frozen=True, slots=True)
class WorkspaceReady:
    generation: int
    canonical_workspace: str
    directory_identity: tuple[int, int]
    backend: str
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
    record_type: str
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
) -> tuple[BrokerTarget, dict[str, Any], str, tuple[int, int]]:
    # Override the only TAUT_DB-derived broker setting. Attachments resolve only
    # from their explicit directory and .taut.toml/.taut.db project state.
    config = load_config({"BROKER_DEFAULT_DB_NAME": DEFAULT_DB_NAME})
    try:
        target = resolve_broker_target(locator, config=config)
    except (RuntimeError, tomllib.TOMLDecodeError) as exc:
        raise RuntimeError(CONFIGURATION_UNAVAILABLE) from exc
    if target is None:
        raise NotInitializedError(PROJECT_NOT_FOUND)
    owner = _workspace_owner(target)
    canonical = os.path.realpath(owner)
    try:
        _strict_utf8(canonical)
    except UnicodeEncodeError as exc:
        raise ValueError(INVALID_UTF8_PATH) from exc
    try:
        stat = os.stat(canonical)
    except OSError as exc:
        raise RuntimeError(DIRECTORY_IDENTITY_UNAVAILABLE) from exc
    directory_identity = (int(stat.st_dev), int(stat.st_ino))
    if directory_identity == (0, 0):
        raise RuntimeError(DIRECTORY_IDENTITY_UNAVAILABLE)
    return target, config, canonical, directory_identity


def run_workspace_reactor(
    inbound: queue.Queue[WorkspaceControl],
    wake: Event,
    outbound: queue.Queue[WorkspaceEvent],
    wake_master: Callable[[], None],
) -> None:
    """Own one workspace client from resolution through close.

    The wake is deliberately payload-free. Every payload crosses a declared
    Queue, matching the BaseReactor communication contract without inheriting
    its consuming watcher assumptions.
    """

    generation = -1
    client: TautClient | None = None
    token = ""
    target: BrokerTarget | None = None
    config: dict[str, Any] | None = None
    canonical = ""
    directory_identity = (0, 0)
    backend = ""
    ready = False
    degraded = False
    previous_snapshot: tuple[Notification, ...] = ()
    previous_truncated = False
    last_finished_command_id = -1
    activity_stop = Event()
    activity_waiter: ActivityWaiter | None = None
    next_backstop_at = time.monotonic() + NOTIFICATION_BACKSTOP_SECONDS
    last_native_snapshot_at = float("-inf")
    native_snapshot_pending = False

    def emit(event: WorkspaceEvent) -> None:
        outbound.put_nowait(event)
        wake_master()

    def stop_requested(controls: list[WorkspaceControl]) -> bool:
        return any(
            isinstance(control, StopWorkspace) and control.generation == generation
            for control in controls
        )

    try:
        while True:
            if not ready or activity_waiter is None:
                timeout = NOTIFICATION_BACKSTOP_SECONDS
                if ready:
                    timeout = max(0.0, next_backstop_at - time.monotonic())
                wake.wait(timeout=timeout)
            else:
                while not wake.is_set():
                    now = time.monotonic()
                    next_due = (
                        last_native_snapshot_at + NOTIFICATION_BACKSTOP_SECONDS
                        if native_snapshot_pending
                        else next_backstop_at
                    )
                    remaining = next_due - now
                    if remaining <= 0:
                        break
                    try:
                        native_activity = activity_waiter.wait(min(remaining, 0.01))
                    except Exception:
                        try:
                            activity_waiter.close()
                        except Exception:
                            pass
                        activity_waiter = None
                        break
                    if native_activity:
                        native_snapshot_pending = True
                        if (
                            time.monotonic()
                            >= last_native_snapshot_at + NOTIFICATION_BACKSTOP_SECONDS
                        ):
                            break
            wake.clear()
            controls: list[WorkspaceControl] = []
            while True:
                try:
                    controls.append(inbound.get_nowait())
                except queue.Empty:
                    break

            if generation < 0:
                bootstrap = next(
                    (item for item in controls if isinstance(item, Bootstrap)),
                    None,
                )
                if bootstrap is None:
                    continue
                generation = bootstrap.generation
                token = bootstrap.token
                try:
                    target, config, canonical, directory_identity = _resolve_workspace(
                        bootstrap.locator
                    )
                    backend = target.backend_name
                except NotInitializedError:
                    emit(WorkspaceFailed(generation, "resolution", PROJECT_NOT_FOUND))
                    return
                except ValueError as exc:
                    emit(WorkspaceFailed(generation, "resolution", str(exc)))
                    return
                except RuntimeError as exc:
                    message = str(exc)
                    if message not in {
                        CONFIGURATION_UNAVAILABLE,
                        DIRECTORY_IDENTITY_UNAVAILABLE,
                    }:
                        message = ATTACHMENT_FAILED
                    emit(WorkspaceFailed(generation, "resolution", message))
                    return
                emit(
                    WorkspaceResolved(
                        generation,
                        canonical,
                        directory_identity,
                        backend,
                    )
                )
                if stop_requested(controls):
                    return
                continue

            if stop_requested(controls):
                return

            if not ready:
                granted = any(
                    isinstance(control, GrantValidation)
                    and control.generation == generation
                    for control in controls
                )
                if not granted:
                    continue
                if target is None or config is None:
                    raise AssertionError("validation grant requires resolved state")
                try:
                    client = TautClient(
                        broker_target=target,
                        broker_config=config,
                        token=token,
                        persistent=True,
                        inherit_environment_identity=False,
                    )
                    resolved = client._resolve_member(
                        create=False,
                        _touch_activity=False,
                    )
                    member = client._require_member(resolved)
                    notification_queue = client.queue(
                        addressing.notification_queue_name(str(member["member_id"]))
                    )
                    try:
                        activity_waiter = create_activity_waiter_for_queues(
                            [notification_queue],
                            stop_event=activity_stop,
                        )
                    except Exception:
                        # Native delivery is an optional edge hint. The fixed
                        # observational backstop remains authoritative when a
                        # backend cannot create its hint source.
                        activity_waiter = None
                    pending = tuple(client.peek_inbox(limit=101))
                except (IdentityError, TokenError):
                    emit(WorkspaceFailed(generation, "validation", IDENTITY_INVALID))
                    return
                except Exception as exc:
                    del exc
                    emit(WorkspaceFailed(generation, "validation", ATTACHMENT_FAILED))
                    return
                previous_snapshot = pending[:100]
                previous_truncated = len(pending) > 100
                next_backstop_at = time.monotonic() + NOTIFICATION_BACKSTOP_SECONDS
                ready = True
                token = ""
                emit(
                    WorkspaceReady(
                        generation,
                        canonical,
                        directory_identity,
                        backend,
                        str(member["member_id"]),
                        str(member["display_name"]),
                        previous_snapshot,
                        previous_truncated,
                    )
                )
                continue

            if degraded:
                continue
            if client is None:
                raise AssertionError("ready workspace requires a client")

            cancels = {
                control.command_id
                for control in controls
                if isinstance(control, CancelWorkspaceCommand)
                and control.generation == generation
                and control.command_id > last_finished_command_id
            }
            command = next(
                (
                    control
                    for control in controls
                    if isinstance(control, RunWorkspaceCommand)
                    and control.generation == generation
                    and control.command_id > last_finished_command_id
                ),
                None,
            )
            if command is not None:
                last_finished_command_id = command.command_id
                if command.command_id in cancels:
                    emit(
                        WorkspaceCommandOutcome(
                            generation,
                            command.command_id,
                            command.name,
                            "canceled",
                            (),
                            (),
                            previous_snapshot,
                            previous_truncated,
                            canceled=True,
                        )
                    )
                    continue
                client.last_notification_warnings.clear()
                command_records: tuple[CommandRecord, ...] = ()
                command_error: str | None = None
                try:
                    result = execute_command(client, command.name, command.arguments)
                    command_record_type = result.record_type
                    command_records = result.records
                except TokenError:
                    degraded = True
                    emit(WorkspaceIdentityLost(generation))
                    continue
                except BlankMessageError as exc:
                    command_record_type = RECORD_TYPE_BY_TOOL[command.name]
                    command_error = str(exc)
                except EmptyResultError:
                    command_record_type = RECORD_TYPE_BY_TOOL[command.name]
                except (TautError, TypeError, ValueError) as exc:
                    command_record_type = RECORD_TYPE_BY_TOOL[command.name]
                    command_error = str(exc)
                except Exception:
                    emit(WorkspaceCrashed(generation))
                    return
                try:
                    pending = tuple(client.peek_inbox(limit=101))
                except (IdentityError, TokenError):
                    degraded = True
                    emit(WorkspaceIdentityLost(generation))
                    continue
                except Exception:
                    emit(WorkspaceCrashed(generation))
                    return
                previous_snapshot = pending[:100]
                previous_truncated = len(pending) > 100
                native_snapshot_pending = False
                next_backstop_at = time.monotonic() + NOTIFICATION_BACKSTOP_SECONDS
                emit(
                    WorkspaceCommandOutcome(
                        generation,
                        command.command_id,
                        command.name,
                        command_record_type,
                        command_records,
                        tuple(client.last_notification_warnings),
                        previous_snapshot,
                        previous_truncated,
                        error=command_error,
                    )
                )
                continue
            now = time.monotonic()
            backstop_due = now >= next_backstop_at
            native_due = (
                native_snapshot_pending
                and now >= last_native_snapshot_at + NOTIFICATION_BACKSTOP_SECONDS
            )
            if not backstop_due and not native_due:
                continue
            try:
                pending = tuple(client.peek_inbox(limit=101))
            except (IdentityError, TokenError):
                degraded = True
                emit(WorkspaceIdentityLost(generation))
                continue
            except Exception:
                emit(WorkspaceCrashed(generation))
                return
            snapshot = pending[:100]
            truncated = len(pending) > 100
            if backstop_due:
                next_backstop_at = now + NOTIFICATION_BACKSTOP_SECONDS
            if native_due:
                native_snapshot_pending = False
                last_native_snapshot_at = now
            if snapshot != previous_snapshot or truncated != previous_truncated:
                previous_snapshot = snapshot
                previous_truncated = truncated
                emit(WorkspaceSnapshot(generation, snapshot, truncated))
    except BaseException:
        if generation >= 0:
            emit(WorkspaceCrashed(generation))
    finally:
        token = ""
        activity_stop.set()
        if activity_waiter is not None:
            try:
                activity_waiter.close()
            except Exception:
                pass
        if client is not None:
            try:
                client.close()
            except Exception:
                pass
        if generation >= 0:
            emit(WorkspaceStopped(generation))
