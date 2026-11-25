"""Shared command-adapter helpers for both Summon console surfaces."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from typing import TYPE_CHECKING, Literal, TextIO

from taut import escape_terminal_text
from taut.commands import CommandContext, CommandError

if TYPE_CHECKING:
    from taut_summon.controller import SummonController
    from taut_summon.models import (
        SummonedMember,
        SummonOperationError,
        SummonStatus,
    )

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


def _write_human_line(stream: TextIO, body: str) -> None:
    """Escape one Summon-owned text record, then append structural LF."""

    stream.write(escape_terminal_text(body))
    stream.write("\n")


def write_ndjson_record(stream: TextIO, payload: Mapping[str, object]) -> None:
    """Write one compact UTF-8 NDJSON record per [TAUT-8.2]."""

    stream.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")


def render_live_member(
    stream: TextIO,
    member: SummonedMember,
    *,
    as_json: bool,
) -> None:
    """Render one live session summary in human or NDJSON format."""

    if as_json:
        write_ndjson_record(
            stream,
            {
                "member_id": member.member_id,
                "name": member.name,
                "provider": member.provider,
                "status": "live",
            },
        )
        return
    fields = (
        escape_terminal_text(member.name),
        escape_terminal_text(member.provider),
        "live",
    )
    stream.write("\t".join(fields) + "\n")


def render_status(
    stream: TextIO,
    status: SummonStatus,
    *,
    as_json: bool,
) -> None:
    """Render one correlated live status reply in human or NDJSON format."""

    if as_json:
        write_ndjson_record(
            stream,
            {
                "member_id": status.member_id,
                "name": status.name,
                "driver": status.driver,
                "provider": status.provider,
                "thread_count": status.thread_count,
                "cursor_lag": dict(status.cursor_lag),
                "details": dict(status.details),
            },
        )
        return
    lag = status.cursor_lag
    lag_text = (
        ", ".join(
            f"#{escape_terminal_text(thread)}:{count}"
            for thread, count in sorted(lag.items())
        )
        if lag
        else "caught up"
    )
    fields = [
        escape_terminal_text(status.name),
        f"provider={escape_terminal_text(status.provider)}",
        f"driver={escape_terminal_text(status.driver)}",
        f"threads={status.thread_count}",
        f"lag={lag_text}",
    ]
    fields.extend(
        f"{escape_terminal_text(key)}={escape_terminal_text(str(value))}"
        for key, value in sorted(status.details.items())
    )
    stream.write("\t".join(fields) + "\n")


def emit_status_inspection(
    stream: TextIO,
    controller: SummonController,
    name: str | None,
    *,
    as_json: bool,
) -> None:
    """Query live sessions or one named driver and render to `stream`."""

    from taut_summon.models import NothingSummoned

    if name is None:
        members = controller.list_live()
        if not members:
            raise NothingSummoned("nothing summoned")
        for member in members:
            render_live_member(stream, member, as_json=as_json)
    else:
        render_status(stream, controller.status(name), as_json=as_json)


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
        _write_human_line(
            context.stderr,
            f"status_fault_plane={exc.fault_plane} error={type(exc).__name__}: {exc}",
        )
    suffix = f" (db: {context.db_path})" if context.db_path else ""
    return CommandError(f"{exc}{suffix}", exit_code=exit_code)


__all__ = [
    "DATABASE_HELP",
    "STATUS_FAULT_PLANES",
    "StatusFaultPlane",
    "command_error",
    "emit_status_inspection",
    "render_live_member",
    "render_status",
    "write_ndjson_record",
]
