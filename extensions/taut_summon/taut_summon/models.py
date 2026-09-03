"""Public typed values for embedding Summon ([SUM-13])."""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TypeAlias

JSONPrimitive: TypeAlias = str | int | float | bool | None


@dataclass(frozen=True, slots=True)
class SummonRequest:
    """One foreground summon request, independent of its database binding."""

    name: str
    threads: tuple[str, ...]
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


class SummonRunHandle:
    """Opaque authority to request stop of one exact foreground run.

    The public value is deliberately narrower than the driver: callers may
    retain its immutable member projection and request cancellation, but they
    do not gain access to mutable driver, process, control, or release state.
    """

    __slots__ = ("__completion", "__request_stop", "member")

    __completion: threading.Event
    __request_stop: Callable[[], None]
    member: SummonedMember

    def __init__(
        self,
        member: SummonedMember,
        *,
        _request_stop: Callable[[], None],
        _completion: threading.Event,
    ) -> None:
        object.__setattr__(self, "member", member)
        object.__setattr__(self, "_SummonRunHandle__request_stop", _request_stop)
        object.__setattr__(self, "_SummonRunHandle__completion", _completion)

    def __setattr__(self, _name: str, _value: object) -> None:
        raise AttributeError("SummonRunHandle is immutable")

    def request_stop(self) -> None:
        """Request this run's existing nonblocking, idempotent stop path."""

        if self.__completion.is_set():
            return
        self.__request_stop()


@dataclass(frozen=True, slots=True)
class SummonStatus:
    """Validated live status returned by a summoned member's driver."""

    member_id: str
    name: str
    driver: str
    provider: str
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
    "SummonOperationError",
    "SummonRequest",
    "SummonRunHandle",
    "SummonStatus",
    "SummonedMember",
]
