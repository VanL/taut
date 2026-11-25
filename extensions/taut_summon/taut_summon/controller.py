"""Typed, CLI-independent Summon operations ([SUM-13])."""

from __future__ import annotations

import math
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from taut_summon._providers import (
    provider_names as _provider_names,
)
from taut_summon.models import (
    DriverUnresponsive,
    JSONPrimitive,
    NothingSummoned,
    StopResult,
    SummonedMember,
    SummonOperationError,
    SummonRequest,
    SummonRunHandle,
    SummonStatus,
)

if TYPE_CHECKING:
    from taut import TautClient
    from taut.client import Member
    from taut_summon._state import SummonSessionRow
    from taut_summon.interaction import SummonInteraction

_STOP_TIMEOUT_SECONDS = 30.0
_STATUS_TIMEOUT_SECONDS = 30.0
_STATUS_MODELED_KEYS = frozenset(
    {
        "command",
        "status",
        "request_id",
        "driver",
        "provider",
        "thread_count",
        "cursor_lag",
    }
)


def _operation_errors() -> tuple[type[BaseException], ...]:
    from simplebroker.ext import BrokerError

    from taut import TautError
    from taut_summon._state import SummonStateError

    return (BrokerError, OSError, SummonStateError, TautError)


class SummonController:
    """Finite Summon operations bound to one optional database path."""

    def __init__(self, *, db_path: str | Path | None = None) -> None:
        self._db_path = db_path

    def provider_names(self) -> tuple[str, ...]:
        """Return supported provider names without constructing adapters."""

        return _provider_names()

    def list_live(self) -> tuple[SummonedMember, ...]:
        """Return every session with non-dead driver evidence."""

        from taut_summon._state import driver_liveness

        op_errors = _operation_errors()
        try:
            client = self._open_client()
        except NothingSummoned:
            return ()
        try:
            rows = self._session_rows(client)
            live = [row for row in rows if driver_liveness(row) != "dead"]
            if not live:
                return ()
            names = {member.member_id: member.name for member in client.who()}
            return tuple(
                SummonedMember(
                    member_id=row["member_id"],
                    name=names.get(row["member_id"], row["member_id"]),
                    provider=row["provider"],
                )
                for row in live
            )
        except (NothingSummoned, SummonOperationError):
            raise
        except op_errors as exc:
            raise SummonOperationError(str(exc)) from exc
        finally:
            client.close()

    def status(self, name: str) -> SummonStatus:
        """Return one validated status from a live, correlated driver reply."""

        op_errors = _operation_errors()
        probe = self._open_client(name=name)
        client: TautClient | None = None
        try:
            member, row = self._resolve_live(probe, name)
            client = self._open_client(name=name, install_schema=True, probe=probe)
            try:
                reply = self._control_request(
                    client, member, row, "STATUS", timeout=_STATUS_TIMEOUT_SECONDS
                )
            except op_errors as exc:
                plane = _control_fault_plane(exc)
                raise DriverUnresponsive(
                    f"'{member.name}' is summoned but its driver did not respond: {exc}",
                    fault_plane=plane,
                ) from exc
            if reply is None:
                raise DriverUnresponsive(
                    f"'{member.name}' is summoned but its driver did not respond",
                    fault_plane="control_read",
                )
            return _status_from_reply(member, reply)
        except (NothingSummoned, SummonOperationError):
            raise
        except op_errors as exc:
            raise SummonOperationError(
                f"could not resolve summoned member '{name}': {exc}"
            ) from exc
        finally:
            if client is not None:
                client.close()
            probe.close()

    def stop(self, name: str) -> StopResult:
        """Stop one live driver after ACK and evidence-relative release."""

        op_errors = _operation_errors()
        probe = self._open_client(name=name)
        client: TautClient | None = None
        try:
            member, row = self._resolve_live(probe, name)
            client = self._open_client(name=name, install_schema=True, probe=probe)
            return self._stop_resolved(client, member, row, op_errors=op_errors)
        except (NothingSummoned, SummonOperationError):
            raise
        except op_errors as exc:
            raise SummonOperationError(
                f"could not resolve summoned member '{name}': {exc}"
            ) from exc
        finally:
            if client is not None:
                client.close()
            probe.close()

    def _stop_resolved(
        self,
        client: TautClient,
        member: Member,
        row: SummonSessionRow,
        *,
        op_errors: tuple[type[BaseException], ...],
    ) -> StopResult:
        try:
            reply = self._control_request(
                client, member, row, "STOP", timeout=_STOP_TIMEOUT_SECONDS
            )
        except op_errors as exc:
            raise DriverUnresponsive(
                f"'{member.name}' is summoned but its driver did not stop in time: "
                f"{exc}",
                fault_plane=_control_fault_plane(exc),
            ) from exc
        if reply is None:
            raise DriverUnresponsive(
                f"'{member.name}' is summoned but its driver did not acknowledge STOP",
                fault_plane="control_read",
            )
        if reply.get("status") != "ack":
            error = reply.get("error") or "driver rejected STOP"
            raise SummonOperationError(
                f"'{member.name}' is summoned but STOP failed: {error}"
            )
        try:
            released = self._confirm_released(
                client,
                member.member_id,
                driver_pid=row["driver_pid"],
                driver_start_time=row["driver_start_time"],
            )
        except op_errors as exc:
            raise DriverUnresponsive(
                f"'{member.name}' is summoned but its driver release could not be "
                f"confirmed: {exc}"
            ) from exc
        if not released:
            raise DriverUnresponsive(
                f"'{member.name}' is summoned but its driver did not stop in time"
            )
        return StopResult(member_id=member.member_id, name=member.name)

    def run_foreground(
        self,
        request: SummonRequest,
        interaction: SummonInteraction,
        *,
        install_signal_handlers: bool = False,
        on_ready: Callable[[SummonRunHandle], None] | None = None,
    ) -> None:
        """Run exactly one driver lifecycle in the foreground."""

        from simplebroker.ext import BrokerError

        from taut import NotInitializedError, TautError
        from taut_summon._adapter import (
            AdapterError,
            get_adapter,
            validate_provider_args,
        )
        from taut_summon._driver import run_driver
        from taut_summon._state import SummonStateError

        try:
            run_driver(
                request,
                interaction,
                db_path=None if self._db_path is None else str(self._db_path),
                install_signal_handlers=install_signal_handlers,
                on_ready=on_ready,
            )
        except NotInitializedError as exc:
            if request.provider_flag is None:
                try:
                    get_adapter(request.name)
                    validate_provider_args(request.name, request.provider_args)
                except AdapterError as adapter_exc:
                    raise SummonOperationError(str(adapter_exc)) from adapter_exc
            raise SummonOperationError(str(exc)) from exc
        except (AdapterError, BrokerError, SummonStateError, TautError) as exc:
            raise SummonOperationError(str(exc)) from exc

    def _open_client(
        self,
        *,
        name: str | None = None,
        install_schema: bool = False,
        probe: TautClient | None = None,
    ) -> TautClient:
        from simplebroker import BrokerTarget

        from taut import NotInitializedError, TautClient

        try:
            if probe is not None:
                if isinstance(probe.target, BrokerTarget):
                    return TautClient(
                        broker_target=probe.target,
                        broker_config=probe.config,
                        install_schema=install_schema,
                    )
                return TautClient(
                    db_path=probe.target,
                    install_schema=install_schema,
                )
            return TautClient(
                db_path=self._db_path,
                install_schema=install_schema,
            )
        except NotInitializedError as exc:
            target = f" as '{name}'" if name is not None else ""
            raise NothingSummoned(f"nothing summoned{target}") from exc

    @staticmethod
    def _session_rows(client: TautClient) -> list[SummonSessionRow]:
        from taut_summon._state import (
            LEDGER_QUEUE_NAME,
            get_summon_schema_version,
            list_sessions,
            validate_summon_schema,
        )

        queue = client.queue(LEDGER_QUEUE_NAME)
        try:
            if get_summon_schema_version(queue) is None:
                return []
            validate_summon_schema(queue)
            return list_sessions(queue)
        finally:
            queue.close()

    @staticmethod
    def _member_session(client: TautClient, member: Member) -> SummonSessionRow | None:
        from taut_summon._state import (
            LEDGER_QUEUE_NAME,
            get_session,
            get_summon_schema_version,
            validate_summon_schema,
        )

        queue = client.queue(LEDGER_QUEUE_NAME)
        try:
            if get_summon_schema_version(queue) is None:
                return None
            validate_summon_schema(queue)
            return get_session(queue, member.member_id)
        finally:
            queue.close()

    def _resolve_live(
        self, client: TautClient, name: str
    ) -> tuple[Member, SummonSessionRow]:
        from taut_summon._members import find_member
        from taut_summon._state import driver_liveness

        op_errors = _operation_errors()
        try:
            member = find_member(client, name)
        except op_errors as exc:
            raise SummonOperationError(
                f"could not resolve summoned member '{name}': {exc}",
                fault_plane="resolve_member",
            ) from exc
        try:
            row = None if member is None else self._member_session(client, member)
        except op_errors as exc:
            raise SummonOperationError(
                f"could not resolve summoned member '{name}': {exc}",
                fault_plane="resolve_session",
            ) from exc
        if member is None or row is None or driver_liveness(row) == "dead":
            raise NothingSummoned(f"nothing summoned as '{name}'")
        return member, row

    @staticmethod
    def _control_request(
        client: TautClient,
        member: Member,
        row: SummonSessionRow,
        command: str,
        *,
        timeout: float,
    ) -> dict[str, Any] | None:
        from taut_summon._control import ControlClient

        control = ControlClient(
            client.queue,
            member.member_id,
            driver_pid=row["driver_pid"],
            driver_start_time=row["driver_start_time"],
        )
        try:
            return control.request(command, timeout=timeout)
        finally:
            control.close()

    @staticmethod
    def _confirm_released(
        client: TautClient,
        member_id: str,
        *,
        driver_pid: int | None,
        driver_start_time: str | None,
    ) -> bool:
        from taut_summon._state import (
            LEDGER_QUEUE_NAME,
            get_session,
            release_evidence_confirmed,
        )

        queue = client.queue(LEDGER_QUEUE_NAME)
        try:
            row = get_session(queue, member_id)
            stored = (
                (None, None)
                if row is None
                else (row["driver_pid"], row["driver_start_time"])
            )
            return release_evidence_confirmed(stored, (driver_pid, driver_start_time))
        finally:
            queue.close()


def _control_fault_plane(exc: BaseException) -> str:
    from taut_summon._control import _CONTROL_FAULT_PLANE_ATTR

    plane = getattr(exc, _CONTROL_FAULT_PLANE_ATTR, None)
    return plane if plane in {"control_write", "control_read"} else "control_read"


def _status_from_reply(member: Member, reply: dict[str, Any]) -> SummonStatus:
    if reply.get("status") != "ok":
        error = reply.get("error") or "driver returned an invalid STATUS reply"
        raise SummonOperationError(str(error), fault_plane="driver_snapshot")
    driver = _required_text(reply, "driver")
    provider = _required_text(reply, "provider")
    thread_count = reply.get("thread_count")
    if (
        not isinstance(thread_count, int)
        or isinstance(thread_count, bool)
        or thread_count < 0
    ):
        raise SummonOperationError("invalid STATUS field 'thread_count'")
    raw_lag = reply.get("cursor_lag")
    if not isinstance(raw_lag, dict):
        raise SummonOperationError("invalid STATUS field 'cursor_lag'")
    cursor_lag: dict[str, int] = {}
    for thread, value in raw_lag.items():
        if (
            not isinstance(thread, str)
            or not isinstance(value, int)
            or isinstance(value, bool)
            or value < 0
        ):
            raise SummonOperationError("invalid STATUS field 'cursor_lag'")
        cursor_lag[thread] = value
    details: dict[str, JSONPrimitive] = {}
    for key, value in reply.items():
        if key in _STATUS_MODELED_KEYS:
            continue
        if not isinstance(key, str) or not _is_json_primitive(value):
            raise SummonOperationError(f"invalid STATUS detail field {key!r}")
        details[key] = cast(JSONPrimitive, value)
    return SummonStatus(
        member_id=member.member_id,
        name=member.name,
        driver=driver,
        provider=provider,
        thread_count=thread_count,
        cursor_lag=dict(cursor_lag),
        details=dict(details),
    )


def _required_text(reply: dict[str, Any], key: str) -> str:
    value = reply.get(key)
    if not isinstance(value, str) or not value:
        raise SummonOperationError(f"invalid STATUS field {key!r}")
    return value


def _is_json_primitive(value: object) -> bool:
    if value is None or isinstance(value, (str, bool, int)):
        return True
    return isinstance(value, float) and math.isfinite(value)


__all__ = ["SummonController"]
