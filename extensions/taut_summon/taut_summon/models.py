"""Public typed values for embedding Summon ([SUM-13])."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TypeAlias

JSONPrimitive: TypeAlias = str | int | float | bool | None


@dataclass(frozen=True, slots=True)
class SummonRequest:
    """One foreground summon request, independent of its database binding."""

    name: str
    threads: tuple[str, ...]
    terminal: bool
    persona: str | None
    system_prompt_file: str | None
    rate_limit: int | None
    attach: bool = False
    detach: bool = False
    provider_flag: str | None = None
    takeover: bool = False


@dataclass(frozen=True, slots=True)
class SummonedMember:
    """Public summary of one live summoned member."""

    member_id: str
    name: str
    provider: str
    provider_session_id: str | None


@dataclass(frozen=True, slots=True)
class SummonStatus:
    """Validated live status returned by a summoned member's driver."""

    member_id: str
    name: str
    driver: str
    provider: str
    provider_session_id: str | None
    thread_count: int
    cursor_lag: dict[str, int] = field(default_factory=dict)
    details: dict[str, JSONPrimitive] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class StopResult:
    """Identity of a member whose driver acknowledged and completed stop."""

    member_id: str
    name: str


class SummonOperationError(Exception):
    """A public Summon operation failed without a successful domain result."""

    def __init__(self, message: str, *, fault_plane: str | None = None) -> None:
        super().__init__(message)
        self.fault_plane = fault_plane


class NothingSummoned(SummonOperationError):
    """No live summoned driver matches the requested operation."""


class DriverUnresponsive(SummonOperationError):
    """A live driver did not complete its control-plane operation in time."""


__all__ = [
    "DriverUnresponsive",
    "NothingSummoned",
    "StopResult",
    "SummonedMember",
    "SummonOperationError",
    "SummonRequest",
    "SummonStatus",
]
