"""Public host-terminal seam for foreground Summon runs ([SUM-7.4], [SUM-13])."""

from __future__ import annotations

import os
import sys
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from enum import Enum
from typing import Protocol


class TerminalIntent(Enum):
    """Whether the caller explicitly requires or merely prefers a terminal."""

    REQUIRED = "required"
    PREFERRED = "preferred"


class TerminalAvailability(Enum):
    """Why the host can or cannot grant its human terminal."""

    AVAILABLE = "available"
    NO_TTY = "no-tty"
    NESTED_HOST = "nested-host"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class TerminalLease:
    """Host-owned input and output descriptors valid for one attach scope."""

    input_fd: int
    output_fd: int


class SummonInteraction(Protocol):
    """Two-phase terminal handoff supplied by a foreground host."""

    def terminal_availability(self, intent: TerminalIntent) -> TerminalAvailability:
        """Report host availability without changing terminal state."""
        ...

    def terminal_lease(self) -> AbstractContextManager[TerminalLease]:
        """Grant host descriptors and restore host state when the scope exits."""
        ...


class ShellSummonInteraction:
    """Terminal interaction for the standalone shell command surface."""

    def __init__(self) -> None:
        self._availability: TerminalAvailability | None = None

    def terminal_availability(self, intent: TerminalIntent) -> TerminalAvailability:
        del intent
        if not sys.stdin.isatty():
            availability = TerminalAvailability.NO_TTY
        elif os.environ.get("TAUT_HOST_TUI") == "1":
            availability = TerminalAvailability.NESTED_HOST
        else:
            availability = TerminalAvailability.AVAILABLE
        self._availability = availability
        return availability

    @contextmanager
    def terminal_lease(self) -> Iterator[TerminalLease]:
        if self._availability is not TerminalAvailability.AVAILABLE:
            raise RuntimeError("terminal is not available")
        yield TerminalLease(input_fd=0, output_fd=1)


__all__ = [
    "ShellSummonInteraction",
    "SummonInteraction",
    "TerminalAvailability",
    "TerminalIntent",
    "TerminalLease",
]
