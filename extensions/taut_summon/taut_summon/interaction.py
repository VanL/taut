"""Public host-terminal seam for foreground Summon runs ([SUM-7.4], [SUM-13])."""

from __future__ import annotations

import os
import select
import sys
import threading
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from enum import Enum
from typing import Protocol, TextIO


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


@dataclass(frozen=True, slots=True)
class TerminalAttachNotice:
    """Semantic facts a host must present before a raw provider attach."""

    member: str
    provider: str
    detach_hint: str


class SummonInteraction(Protocol):
    """Pre-spawn acknowledgement and terminal handoff from a foreground host."""

    def terminal_availability(self, intent: TerminalIntent) -> TerminalAvailability:
        """Report host availability without changing terminal state."""
        ...

    def confirm_terminal_attach(
        self,
        notice: TerminalAttachNotice,
        *,
        cancel: threading.Event | None = None,
    ) -> bool:
        """Present an actual attach decision and return proceed or cancel."""
        ...

    def terminal_lease(self) -> AbstractContextManager[TerminalLease]:
        """Grant host descriptors and restore host state when the scope exits."""
        ...


class ShellSummonInteraction:
    """Terminal interaction for the standalone shell command surface."""

    def __init__(
        self,
        *,
        input_stream: TextIO | None = None,
        output_stream: TextIO | None = None,
    ) -> None:
        self._availability: TerminalAvailability | None = None
        self._input_stream = sys.stdin if input_stream is None else input_stream
        self._output_stream = sys.stderr if output_stream is None else output_stream

    def terminal_availability(self, intent: TerminalIntent) -> TerminalAvailability:
        del intent
        if not self._input_stream.isatty():
            availability = TerminalAvailability.NO_TTY
        elif os.environ.get("TAUT_HOST_TUI") == "1":
            availability = TerminalAvailability.NESTED_HOST
        else:
            availability = TerminalAvailability.AVAILABLE
        self._availability = availability
        return availability

    def confirm_terminal_attach(
        self,
        notice: TerminalAttachNotice,
        *,
        cancel: threading.Event | None = None,
    ) -> bool:
        from taut import escape_terminal_text

        member = escape_terminal_text(notice.member)
        provider = escape_terminal_text(notice.provider)
        detach_hint = escape_terminal_text(notice.detach_hint)
        self._output_stream.write(
            f"Preparing provider setup for '{member}' with '{provider}'.\n"
            "This is provider setup, not Taut chat.\n"
            "Complete only trust, login, model, or equivalent setup.\n"
            f"When setup is complete, return to Taut with {detach_hint}.\n"
            "This foreground Summon command keeps running after detach; "
            "chat from another terminal.\n"
            "Press Enter to continue, or type anything else to cancel: "
        )
        self._output_stream.flush()
        if cancel is None:
            return self._input_stream.readline() in {"\n", "\r\n"}
        try:
            input_fd = self._input_stream.fileno()
        except (AttributeError, OSError):
            return self._input_stream.readline() in {"\n", "\r\n"}
        while not cancel.is_set():
            ready, _, _ = select.select([input_fd], [], [], 0.1)
            if ready:
                return self._input_stream.readline() in {"\n", "\r\n"}
        return False

    @contextmanager
    def terminal_lease(self) -> Iterator[TerminalLease]:
        if self._availability is not TerminalAvailability.AVAILABLE:
            raise RuntimeError("terminal is not available")
        yield TerminalLease(input_fd=0, output_fd=1)


__all__ = [
    "ShellSummonInteraction",
    "SummonInteraction",
    "TerminalAttachNotice",
    "TerminalAvailability",
    "TerminalIntent",
    "TerminalLease",
]
