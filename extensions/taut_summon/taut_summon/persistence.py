"""Logical Summon session persistence contributor.

Spec reference: docs/specs/08-persistence-io.md [PIO-5.3], [PIO-8].
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from simplebroker import Queue, format_message_id
from simplebroker.ext import SidecarSession

from taut.persistence._components import PersistenceComponentCompatibilityError
from taut_summon import _state

_V1_FIELDS = {
    "type",
    "member_id",
    "token",
    "provider",
    "provider_session_id",
    "wired",
    "updated_ts",
}
_V2_FIELDS = _V1_FIELDS - {"provider_session_id"}


class SummonPersistenceComponent:
    def validate_live_schema(self, queue: Queue) -> None:
        """Reject incompatible live state without initializing or migrating it."""

        try:
            _state.validate_summon_schema(queue)
        except _state.SummonStateError as exc:
            raise PersistenceComponentCompatibilityError(
                f"taut-summon live schema is unreadable: {exc}; upgrade taut-summon"
            ) from exc

    def ensure_schema(self, queue: Queue) -> None:
        _state.ensure_summon_schema(queue)

    def dump_records(self, queue: Queue) -> list[dict[str, Any]]:
        return [
            {**record, "updated_ts": format_message_id(record["updated_ts"])}
            for record in _state.persistence_records(queue)
        ]

    def validate_records(
        self,
        version: int,
        records: Iterable[dict[str, Any]],
        *,
        core_member_ids: frozenset[str],
    ) -> None:
        if version not in {1, 2}:
            raise ValueError(f"unsupported taut-summon component version {version}")
        expected_fields = _V1_FIELDS if version == 1 else _V2_FIELDS
        seen: set[str] = set()
        previous: str | None = None
        for record in records:
            if set(record) != expected_fields or record.get("type") != "session":
                raise ValueError("invalid taut-summon session record fields")
            member_id = record["member_id"]
            if (
                not isinstance(member_id, str)
                or not member_id
                or member_id in seen
                or member_id not in core_member_ids
                or (previous is not None and member_id <= previous)
                or not isinstance(record["token"], str)
                or not record["token"]
                or not isinstance(record["provider"], str)
                or not record["provider"]
                or (
                    version == 1
                    and (
                        record["provider_session_id"] is not None
                        and not isinstance(record["provider_session_id"], str)
                    )
                )
                or not isinstance(record["wired"], bool)
                or not _valid_updated_ts(record["updated_ts"])
            ):
                raise ValueError("invalid taut-summon session record")
            seen.add(member_id)
            previous = member_id

    def is_fresh(self, queue: Queue) -> bool:
        return _state.persistence_is_fresh(queue)

    def load_records(
        self,
        session: SidecarSession,
        records: Iterable[dict[str, Any]],
    ) -> None:
        _state.load_persistence_records(
            session,
            (
                {
                    key: value
                    for key, value in record.items()
                    if key != "provider_session_id"
                }
                | {"updated_ts": _updated_ts_as_int(record["updated_ts"])}
                for record in records
            ),
        )


def _valid_updated_ts(value: Any) -> bool:
    try:
        _updated_ts_as_int(value)
    except (TypeError, ValueError):
        return False
    return True


def _updated_ts_as_int(value: Any) -> int:
    formatted = format_message_id(value)
    if isinstance(value, str) and value != formatted:
        raise ValueError("updated_ts string must use the canonical representation")
    return int(formatted)


def create_component() -> SummonPersistenceComponent:
    return SummonPersistenceComponent()


__all__ = ["SummonPersistenceComponent", "create_component"]
