"""Logical Summon session persistence contributor.

Spec reference: docs/specs/08-persistence-io.md [PIO-5.3], [PIO-8].
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from simplebroker import Queue
from simplebroker.ext import SidecarSession

from taut_summon import _state

_FIELDS = {
    "type",
    "member_id",
    "token",
    "provider",
    "provider_session_id",
    "wired",
    "updated_ts",
}


class SummonPersistenceComponent:
    def ensure_schema(self, queue: Queue) -> None:
        _state.ensure_summon_schema(queue)

    def dump_records(self, queue: Queue) -> list[dict[str, Any]]:
        return _state.persistence_records(queue)

    def validate_records(
        self,
        version: int,
        records: Iterable[dict[str, Any]],
        *,
        core_member_ids: frozenset[str],
    ) -> None:
        if version != 1:
            raise ValueError(f"unsupported taut-summon component version {version}")
        seen: set[str] = set()
        previous: str | None = None
        for record in records:
            if set(record) != _FIELDS or record.get("type") != "session":
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
                    record["provider_session_id"] is not None
                    and not isinstance(record["provider_session_id"], str)
                )
                or not isinstance(record["wired"], bool)
                or not isinstance(record["updated_ts"], int)
                or isinstance(record["updated_ts"], bool)
                or record["updated_ts"] < 0
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
        _state.load_persistence_records(session, records)


def create_component() -> SummonPersistenceComponent:
    return SummonPersistenceComponent()


__all__ = ["SummonPersistenceComponent", "create_component"]
