"""Compact relative-age and sub-thread label formatting for the TUI.

Spec references:
- docs/specs/10-taut-tui.md [TUI-5.3]
"""

from __future__ import annotations

import time
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta, tzinfo
from typing import Final

from taut import ThreadNameError
from taut.addressing import parse_target

_NS_PER_SECOND: Final[int] = 1_000_000_000
_MINUTE_SECONDS: Final[int] = 60
_HOUR_SECONDS: Final[int] = 3_600
_ONE_HOUR_BUCKET_START: Final[int] = 51 * _MINUTE_SECONDS
_TWO_HOURS_SECONDS: Final[int] = 2 * _HOUR_SECONDS
_DAY_SECONDS: Final[int] = 86_400
_CALENDAR_WINDOW_SECONDS: Final[int] = 8 * _DAY_SECONDS
_EPOCH_UTC: Final[datetime] = datetime(1970, 1, 1, tzinfo=UTC)
_WEEKDAY_NAMES: Final[tuple[str, ...]] = (
    "Mon",
    "Tue",
    "Wed",
    "Thu",
    "Fri",
    "Sat",
    "Sun",
)


def format_relative_time(
    ts_ns: int,
    *,
    now_ns: int | None = None,
    local_tz: tzinfo | None = None,
) -> str:
    """Format a nanosecond message ID as a compact human relative age."""

    ref_ns = time.time_ns() if now_ns is None else now_ns
    elapsed_ns = ref_ns - ts_ns
    if elapsed_ns < _MINUTE_SECONDS * _NS_PER_SECOND:
        return "now"
    elapsed_seconds = elapsed_ns // _NS_PER_SECOND
    if elapsed_seconds < _ONE_HOUR_BUCKET_START:
        return f"{elapsed_seconds // _MINUTE_SECONDS}m ago"
    if elapsed_seconds < _TWO_HOURS_SECONDS:
        return "1h ago"
    if elapsed_seconds < _CALENDAR_WINDOW_SECONDS:
        return _format_calendar_window(
            ts_ns // _NS_PER_SECOND,
            ref_ns // _NS_PER_SECOND,
            elapsed_seconds,
            local_tz,
        )
    return _format_elapsed_days(elapsed_seconds // _DAY_SECONDS)


def _format_calendar_window(
    msg_sec: int,
    ref_sec: int,
    elapsed_seconds: int,
    local_tz: tzinfo | None,
) -> str:
    msg_date = (_EPOCH_UTC + timedelta(seconds=msg_sec)).astimezone(local_tz).date()
    ref_date = (_EPOCH_UTC + timedelta(seconds=ref_sec)).astimezone(local_tz).date()
    day_delta = (ref_date - msg_date).days
    if day_delta <= 0:
        return f"{elapsed_seconds // _HOUR_SECONDS}h ago"
    if day_delta == 1:
        return "yesterday"
    if day_delta <= 6:
        return _WEEKDAY_NAMES[msg_date.weekday()]
    return _format_elapsed_days(day_delta)


def _format_elapsed_days(days: int) -> str:
    if days < 28:
        return f"{days // 7}w ago"
    if days < 365:
        months = min(11, max(1, days // 30))
        return f"{months}mo ago"
    return f"{days // 365}y ago"


def format_subthread_label(
    name: str,
    target_labels: Mapping[str, str],
    *,
    now_ns: int | None = None,
    local_tz: tzinfo | None = None,
) -> str | None:
    """Format ``channel.<origin_ts>`` as ``#channel (thread <age>)``."""

    try:
        parsed = parse_target(name, allow_dm=False)
    except ThreadNameError:
        return None
    if parsed.kind != "subthread" or parsed.channel is None or parsed.origin_ts is None:
        return None
    channel_label = target_labels.get(parsed.channel, f"#{parsed.channel}")
    age = format_relative_time(
        parsed.origin_ts,
        now_ns=now_ns,
        local_tz=local_tz,
    )
    return f"{channel_label} (thread {age})"


__all__ = ["format_relative_time", "format_subthread_label"]
