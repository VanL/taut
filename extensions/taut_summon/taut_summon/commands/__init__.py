"""Shared command-adapter helpers for both Summon console surfaces."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Literal

from taut.commands import CommandContext, CommandError

if TYPE_CHECKING:
    from taut_summon.models import SummonOperationError

StatusFaultPlane = Literal[
    "resolve_member",
    "resolve_session",
    "control_write",
    "control_read",
    "driver_snapshot",
]
STATUS_FAULT_PLANES: frozenset[StatusFaultPlane] = frozenset(
    {
        "resolve_member",
        "resolve_session",
        "control_write",
        "control_read",
        "driver_snapshot",
    }
)
DATABASE_HELP = (
    "Use an explicit SQLite database path. Omit to discover .taut.toml or "
    ".taut.db from the current directory and its ancestors."
)


def command_error(
    exc: SummonOperationError,
    context: CommandContext,
    *,
    exit_code: int,
) -> CommandError:
    """Translate one domain error without hiding its diagnostic context."""

    if exc.fault_plane in STATUS_FAULT_PLANES and os.environ.get(
        "TAUT_SUMMON_STATUS_FAULT_PLANE"
    ):
        context.stderr.write(
            f"status_fault_plane={exc.fault_plane} error={type(exc).__name__}: {exc}\n"
        )
    suffix = f" (db: {context.db_path})" if context.db_path else ""
    return CommandError(f"{exc}{suffix}", exit_code=exit_code)


__all__ = ["DATABASE_HELP", "STATUS_FAULT_PLANES", "StatusFaultPlane", "command_error"]
