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
    ActivityWaiter,
    BrokerTarget,
    ResolvedConfig,
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
_REACTION_CONFIGURATION_ERRORS = frozenset(
    {
        "reaction configuration is unavailable",
        (
            "invalid .taut.toml: [reactions].values must be a list of unique "
            "lowercase ASCII slugs"
        ),
    }
)


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
) -> tuple[BrokerTarget, ResolvedConfig, str, tuple[int, int]]:
    # Explicit workspace resolution outranks ambient TAUT_DB for both halves of
    # the lower-layer default path.
    config = load_config(
        {
            "TAUT_DEFAULT_DB_LOCATION": "",
            "TAUT_DEFAULT_DB_NAME": DEFAULT_DB_NAME,
        }
    )
    try:
        target = resolve_broker_target(locator, config=config)
    except tomllib.TOMLDecodeError as exc:
        raise RuntimeError(CONFIGURATION_UNAVAILABLE) from exc
    except ValueError as exc:
        raise NotInitializedError(PROJECT_NOT_FOUND) from exc
    except RuntimeError as exc:
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


class _WorkspaceReactor:
    """Single child-thread owner for one workspace lifecycle."""

    def __init__(
        self,
        inbound: queue.Queue[WorkspaceControl],
        wake: Event,
        outbound: queue.Queue[WorkspaceEvent],
        wake_master: Callable[[], None],
    ) -> None:
        self.inbound = inbound
        self.wake = wake
        self.outbound = outbound
        self.wake_master = wake_master
        self.generation = -1
        self.client: TautClient | None = None
        self.token = ""
        self.target: BrokerTarget | None = None
        self.config: ResolvedConfig | None = None
        self.canonical = ""
        self.directory_identity = (0, 0)
        self.backend = ""
        self.ready = False
        self.degraded = False
        self.previous_snapshot: tuple[Notification, ...] = ()
        self.previous_truncated = False
        self.last_finished_command_id = -1
        self.activity_stop = Event()
        self.activity_waiter: ActivityWaiter | None = None
        self.next_backstop_at = time.monotonic() + NOTIFICATION_BACKSTOP_SECONDS
        self.last_native_snapshot_at = float("-inf")
        self.native_snapshot_pending = False

    def _emit(self, event: WorkspaceEvent) -> None:
        self.outbound.put_nowait(event)
        self.wake_master()

    def _stop_requested(self, controls: list[WorkspaceControl]) -> bool:
        return any(
            isinstance(control, StopWorkspace) and control.generation == self.generation
            for control in controls
        )

    def _wait_for_work(self) -> None:
        if not self.ready or self.activity_waiter is None:
            timeout = NOTIFICATION_BACKSTOP_SECONDS
            if self.ready:
                timeout = max(0.0, self.next_backstop_at - time.monotonic())
            self.wake.wait(timeout=timeout)
            return
        while not self.wake.is_set():
            now = time.monotonic()
            next_due = (
                self.last_native_snapshot_at + NOTIFICATION_BACKSTOP_SECONDS
                if self.native_snapshot_pending
                else self.next_backstop_at
            )
            remaining = next_due - now
            if remaining <= 0:
                return
            try:
                native_activity = self.activity_waiter.wait(min(remaining, 0.01))
            except Exception:  # noqa: BLE001 approved [DOM-10.2.1] [RUFF-SUP-066] exception
                with suppress(Exception):
                    self.activity_waiter.close()
                self.activity_waiter = None
                return
            if native_activity:
                self.native_snapshot_pending = True
                if (
                    time.monotonic()
                    >= self.last_native_snapshot_at + NOTIFICATION_BACKSTOP_SECONDS
                ):
                    return

    def _drain_controls(self) -> list[WorkspaceControl]:
        self.wake.clear()
        controls: list[WorkspaceControl] = []
        while True:
            try:
                controls.append(self.inbound.get_nowait())
            except queue.Empty:
                return controls

    def _bootstrap(self, controls: list[WorkspaceControl]) -> bool:
        bootstrap = next(
            (item for item in controls if isinstance(item, Bootstrap)),
            None,
        )
        if bootstrap is None:
            return True
        self.generation = bootstrap.generation
        self.token = bootstrap.token
        bootstrap.token = ""
        try:
            (
                self.target,
                self.config,
                self.canonical,
                self.directory_identity,
            ) = _resolve_workspace(bootstrap.locator)
            self.backend = self.target.backend_name
        except NotInitializedError:
            self._emit(
                WorkspaceFailed(self.generation, "resolution", PROJECT_NOT_FOUND)
            )
            return False
        except ValueError as exc:
            self._emit(WorkspaceFailed(self.generation, "resolution", str(exc)))
            return False
        except RuntimeError as exc:
            message = str(exc)
            if message not in {
                CONFIGURATION_UNAVAILABLE,
                DIRECTORY_IDENTITY_UNAVAILABLE,
            }:
                message = ATTACHMENT_FAILED
            self._emit(WorkspaceFailed(self.generation, "resolution", message))
            return False
        self._emit(
            WorkspaceResolved(
                self.generation,
                self.canonical,
                self.directory_identity,
                self.backend,
            )
        )
        return not self._stop_requested(controls)

    def _validation_granted(self, controls: list[WorkspaceControl]) -> bool:
        return any(
            isinstance(control, GrantValidation)
            and control.generation == self.generation
            for control in controls
        )

    def _validate(self, controls: list[WorkspaceControl]) -> bool:
        if not self._validation_granted(controls):
            return True
        if self.target is None or self.config is None:
            raise AssertionError("validation grant requires resolved state")
        try:
            self.client = TautClient(
                broker_target=self.target,
                broker_config=self.config,
                token=self.token,
                persistent=True,
                inherit_environment_identity=False,
            )
            resolved = self.client._resolve_member(
                create=False,
                _touch_activity=False,
            )
            member = self.client._require_member(resolved)
            notification_queue = self.client.queue(
                addressing.notification_queue_name(str(member["member_id"]))
            )
            try:
                self.activity_waiter = create_activity_waiter_for_queues(
                    [notification_queue],
                    stop_event=self.activity_stop,
                )
            except Exception:  # noqa: BLE001 approved [DOM-10.2.1] [RUFF-SUP-066] exception
                self.activity_waiter = None
            pending = tuple(self.client.peek_inbox(limit=101))
            self.token = ""
        except (IdentityError, TokenError):
            self._emit(WorkspaceFailed(self.generation, "validation", IDENTITY_INVALID))
            return False
        except TautError as exc:
            message = (
                CONFIGURATION_UNAVAILABLE
                if str(exc) in _REACTION_CONFIGURATION_ERRORS
                else ATTACHMENT_FAILED
            )
            self._emit(WorkspaceFailed(self.generation, "validation", message))
            return False
        except Exception:  # noqa: BLE001 approved [DOM-10.2.1] [RUFF-SUP-066] exception
            self._emit(
                WorkspaceFailed(self.generation, "validation", ATTACHMENT_FAILED)
            )
            return False
        self.previous_snapshot = pending[:100]
        self.previous_truncated = len(pending) > 100
        self.next_backstop_at = time.monotonic() + NOTIFICATION_BACKSTOP_SECONDS
        self.ready = True
        self._emit(
            WorkspaceReady(
                self.generation,
                self.canonical,
                self.directory_identity,
                self.backend,
                str(member["member_id"]),
                str(member["display_name"]),
                self.previous_snapshot,
                self.previous_truncated,
            )
        )
        return True

    def _execute_command(self, command: RunWorkspaceCommand) -> bool:
        if self.client is None:
            raise AssertionError("ready workspace requires a client")
        self.client.last_notification_warnings.clear()
        self.client.last_search_warnings.clear()
        command_records: tuple[CommandRecord, ...] = ()
        command_error: str | None = None
        try:
            result = execute_command(self.client, command.name, command.arguments)
            command_record_type = result.record_type
            command_records = result.records
        except TokenError:
            self.degraded = True
            self._emit(WorkspaceIdentityLost(self.generation))
            return True
        except BlankMessageError as exc:
            command_record_type = RECORD_TYPE_BY_TOOL[command.name]
            command_error = str(exc)
        except EmptyResultError:
            command_record_type = RECORD_TYPE_BY_TOOL[command.name]
        except (TautError, TypeError, ValueError) as exc:
            command_record_type = RECORD_TYPE_BY_TOOL[command.name]
            command_error = str(exc)
        except Exception:  # noqa: BLE001 approved [DOM-10.2.1] [RUFF-SUP-066] exception
            self._emit(WorkspaceCrashed(self.generation))
            return False
        refresh_outcome = self._refresh_after_command(command.name)
        if refresh_outcome is _RefreshOutcome.IDENTITY_LOST:
            return True
        if refresh_outcome is _RefreshOutcome.CRASHED:
            return False
        assert refresh_outcome is _RefreshOutcome.REFRESHED
        self._emit(
            WorkspaceCommandOutcome(
                self.generation,
                command.command_id,
                command.name,
                command_record_type,
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
        if self.client is None:
            raise AssertionError("ready workspace requires a client")
        try:
            pending = tuple(self.client.peek_inbox(limit=101))
        except (IdentityError, TokenError):
            self.degraded = True
            self._emit(WorkspaceIdentityLost(self.generation))
            return _RefreshOutcome.IDENTITY_LOST
        except Exception:  # noqa: BLE001 approved [DOM-10.2.1] [RUFF-SUP-066] exception
            self._emit(WorkspaceCrashed(self.generation))
            return _RefreshOutcome.CRASHED
        self.previous_snapshot = pending[:100]
        self.previous_truncated = len(pending) > 100
        self.native_snapshot_pending = False
        self.next_backstop_at = time.monotonic() + NOTIFICATION_BACKSTOP_SECONDS
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
                "canceled",
                (),
                (),
                self.previous_snapshot,
                self.previous_truncated,
                canceled=True,
            )
        )
        return True

    def _publish_snapshot_if_due(self) -> bool:
        if self.client is None:
            raise AssertionError("ready workspace requires a client")
        now = time.monotonic()
        backstop_due = now >= self.next_backstop_at
        native_due = (
            self.native_snapshot_pending
            and now >= self.last_native_snapshot_at + NOTIFICATION_BACKSTOP_SECONDS
        )
        if not backstop_due and not native_due:
            return True
        try:
            pending = tuple(self.client.peek_inbox(limit=101))
        except (IdentityError, TokenError):
            self.degraded = True
            self._emit(WorkspaceIdentityLost(self.generation))
            return True
        except Exception:  # noqa: BLE001 approved [DOM-10.2.1] [RUFF-SUP-066] exception
            self._emit(WorkspaceCrashed(self.generation))
            return False
        snapshot = pending[:100]
        truncated = len(pending) > 100
        if backstop_due:
            self.next_backstop_at = now + NOTIFICATION_BACKSTOP_SECONDS
        if native_due:
            self.native_snapshot_pending = False
            self.last_native_snapshot_at = now
        if snapshot != self.previous_snapshot or truncated != self.previous_truncated:
            self.previous_snapshot = snapshot
            self.previous_truncated = truncated
            self._emit(WorkspaceSnapshot(self.generation, snapshot, truncated))
        return True

    def _run_cycle(self) -> bool:
        self._wait_for_work()
        controls = self._drain_controls()
        if self.generation < 0:
            return self._bootstrap(controls)
        if self._stop_requested(controls):
            return False
        if not self.ready:
            return self._validate(controls)
        if self.degraded:
            return True
        command_state = self._handle_command(controls)
        if command_state is None:
            return self._publish_snapshot_if_due()
        return command_state

    def _run_loop(self) -> None:
        while self._run_cycle():
            pass

    def _cleanup(self) -> None:
        self.token = ""
        self.activity_stop.set()
        if self.activity_waiter is not None:
            with suppress(Exception):
                self.activity_waiter.close()
        if self.client is not None:
            with suppress(Exception):
                self.client.close()
        if self.generation >= 0:
            self._emit(WorkspaceStopped(self.generation))

    def run(self) -> None:
        try:
            self._run_loop()
        except BaseException:  # noqa: BLE001 approved [DOM-10.2.1] [RUFF-SUP-066] exception
            if self.generation >= 0:
                self._emit(WorkspaceCrashed(self.generation))
        finally:
            self._cleanup()


def run_workspace_reactor(
    inbound: queue.Queue[WorkspaceControl],
    wake: Event,
    outbound: queue.Queue[WorkspaceEvent],
    wake_master: Callable[[], None],
) -> None:
    """Own one workspace client from resolution through close."""

    _WorkspaceReactor(inbound, wake, outbound, wake_master).run()
