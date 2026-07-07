"""Shared base machinery for the Taut client package."""

from __future__ import annotations

import json
import os
import tomllib
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NoReturn

from simplebroker import BrokerTarget, Queue, resolve_broker_target

import taut.identity as identity
from taut._constants import (
    META_QUEUE_NAME,
    NO_DATABASE_MESSAGE,
    PROJECT_CONFIG_NAME,
    load_config,
)
from taut._exceptions import IdentityError, NotInitializedError, TautError
from taut.state import (
    ChannelRenameRow,
    MemberRow,
    SqlSidecarTautState,
    TautState,
    dialect_for_taut_target,
)

from ._models import Member, Message

_MISSING_POSTGRES_PLUGIN_ERROR = "Unknown backend plugin: postgres"
_MISSING_POSTGRES_PLUGIN_HINT = (
    "Install taut-pg in the same environment as taut to enable Postgres project configs"
)


def _raise_invalid_project_config(exc: tomllib.TOMLDecodeError) -> NoReturn:
    """Re-raise a project-config parse failure naming the offending file.

    SimpleBroker's target resolution raises the raw ``TOMLDecodeError``
    ("Invalid value (at line 1, column 12)") without saying which file it
    was parsing; a CLI diagnostic must name the offending input.
    """

    raise TautError(f"invalid {PROJECT_CONFIG_NAME}: {exc}") from exc


def _raise_with_backend_install_hint(exc: RuntimeError) -> NoReturn:
    """Re-raise missing Postgres backend errors with the Taut extension hint."""

    message = str(exc)
    if (
        _MISSING_POSTGRES_PLUGIN_ERROR in message
        or "Requested backend 'postgres' is not available" in message
    ):
        raise TautError(
            f"{_MISSING_POSTGRES_PLUGIN_ERROR}. {_MISSING_POSTGRES_PLUGIN_HINT}."
        ) from exc
    raise exc


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _incomplete_channel_rename_message(rename: ChannelRenameRow) -> str:
    """Actionable diagnostic naming the exact command that finishes a rename."""

    old_name = rename["old_name"]
    new_name = rename["new_name"]
    return (
        f"incomplete channel rename exists: {old_name} -> {new_name}; "
        f"run 'taut rename {old_name} {new_name}' to finish it"
    )


@dataclass(slots=True)
class _ResolvedMember:
    row: MemberRow | None
    capture: identity.IdentityCapture
    claim: identity.IdentityClaim
    created: bool = False
    created_token: str | None = None
    candidates: list[tuple[MemberRow, list[str]]] | None = None
    rule: str = "guest"


class _ClientBase(ABC):
    """Shared state and cross-mixin type contract for TautClient."""

    config: dict[str, Any]
    target: BrokerTarget | str
    as_name: str | None
    token: str | None
    identity_capture: identity.IdentityCapture | None
    last_created_member: Member | None
    last_candidates: list[tuple[str, list[str]]]
    last_notification_warnings: list[str]
    _meta_queue: Queue
    _state: TautState

    def __init__(
        self,
        *,
        db_path: str | Path | None = None,
        as_name: str | None = None,
        token: str | None = None,
        identity_capture: identity.IdentityCapture | None = None,
    ) -> None:
        self.config = load_config()
        self.target = self._resolve_target(db_path)
        self.as_name = as_name or os.environ.get("TAUT_AS")
        self.token = token or os.environ.get("TAUT_TOKEN")
        self.identity_capture = identity_capture
        self.last_created_member = None
        self.last_candidates = []
        self.last_notification_warnings = []
        self._meta_queue = self.queue(META_QUEUE_NAME)
        self._state = SqlSidecarTautState(
            self._meta_queue,
            dialect_for_taut_target(self.target),
        )
        self._state.ensure_schema()

    def queue(self, name: str, *, persistent: bool = False) -> Queue:
        """Return a queue bound to this client's resolved target."""

        return Queue(
            name, db_path=self.target, persistent=persistent, config=self.config
        )

    def _resolve_target(self, db_path: str | Path | None) -> BrokerTarget | str:
        explicit = db_path or os.environ.get("TAUT_DB")
        if explicit is not None:
            path = Path(explicit).expanduser()
            if not path.exists():
                raise NotInitializedError(NO_DATABASE_MESSAGE)
            return str(path)
        try:
            target = resolve_broker_target(Path.cwd(), config=self.config)
        except tomllib.TOMLDecodeError as exc:
            _raise_invalid_project_config(exc)
        except RuntimeError as exc:
            _raise_with_backend_install_hint(exc)
        if target is None:
            raise NotInitializedError(NO_DATABASE_MESSAGE)
        if target.backend_name == "sqlite" and not Path(target.target).exists():
            raise NotInitializedError(NO_DATABASE_MESSAGE)
        return target

    def _capture(self) -> identity.IdentityCapture:
        if self.identity_capture is not None:
            return self.identity_capture
        return identity.capture_identity()

    def _require_member(self, resolved: _ResolvedMember) -> MemberRow:
        if resolved.row is None:
            raise IdentityError("unrecognized caller")
        return resolved.row

    def _ensure_no_incomplete_channel_rename(self) -> None:
        renames = self._state.incomplete_channel_renames()
        if not renames:
            return
        raise TautError(_incomplete_channel_rename_message(renames[0]))

    @abstractmethod
    def _resolve_member(
        self,
        *,
        create: bool,
        force_new: bool = False,
        persona: str | None = None,
        allow_guest: bool = False,
    ) -> _ResolvedMember: ...

    @abstractmethod
    def _insert_message(
        self,
        *,
        queue: Queue,
        thread: str,
        from_id: str,
        from_name: str,
        kind: str,
        text: str,
        ts: int,
        notify_mentions: bool,
    ) -> Message: ...

    @abstractmethod
    def _write_message(
        self,
        *,
        queue: Queue,
        thread: str,
        from_id: str,
        from_name: str,
        kind: str,
        text: str,
        notify_mentions: bool,
    ) -> Message: ...

    @abstractmethod
    def _write_notification(self, *, to_id: str, payload: dict[str, Any]) -> None: ...
