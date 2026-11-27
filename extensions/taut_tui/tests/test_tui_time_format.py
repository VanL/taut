"""Boundary tests for TUI compact relative-age and sub-thread formatting.

Spec references:
- docs/specs/10-taut-tui.md [TUI-5.3], [TUI-13.2]
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from taut_tui.time_format import format_relative_time, format_subthread_label

_NS = 1_000_000_000
_DAY_NS = 86_400 * _NS
_EPOCH_UTC = datetime(1970, 1, 1, tzinfo=UTC)
_CHICAGO = ZoneInfo("America/Chicago")


def _local_ns(
    year: int,
    month: int,
    day: int,
    hour: int = 0,
    minute: int = 0,
    second: int = 0,
) -> int:
    dt = datetime(year, month, day, hour, minute, second, tzinfo=_CHICAGO)
    whole_seconds = (dt.astimezone(UTC) - _EPOCH_UTC) // timedelta(seconds=1)
    return whole_seconds * _NS


@pytest.mark.parametrize(
    ("ts_ns", "now_ns", "expected"),
    [
        # Future skew and sub-minute -> "now"
        (
            _local_ns(2026, 11, 27, 12, 0, 1),
            _local_ns(2026, 11, 27, 12, 0, 0),
            "now",
        ),
        (
            _local_ns(2026, 11, 27, 13, 0, 0),
            _local_ns(2026, 11, 27, 12, 0, 0),
            "now",
        ),
        (
            _local_ns(2026, 11, 27, 12, 0, 0),
            _local_ns(2026, 11, 27, 12, 0, 0),
            "now",
        ),
        (
            _local_ns(2026, 11, 27, 12, 0, 0),
            _local_ns(2026, 11, 27, 12, 0, 59) + (_NS - 1),
            "now",
        ),
        # 1m..50m ago (60s..3059s)
        (
            _local_ns(2026, 11, 27, 12, 0, 0),
            _local_ns(2026, 11, 27, 12, 1, 0),
            "1m ago",
        ),
        (
            _local_ns(2026, 11, 27, 12, 0, 0),
            _local_ns(2026, 11, 27, 12, 1, 59),
            "1m ago",
        ),
        (
            _local_ns(2026, 11, 27, 12, 0, 0),
            _local_ns(2026, 11, 27, 12, 2, 0),
            "2m ago",
        ),
        (
            _local_ns(2026, 11, 27, 12, 0, 0),
            _local_ns(2026, 11, 27, 12, 50, 59),
            "50m ago",
        ),
        # 51m..119m -> "1h ago" (3060s..7199s)
        (
            _local_ns(2026, 11, 27, 12, 0, 0),
            _local_ns(2026, 11, 27, 12, 51, 0),
            "1h ago",
        ),
        (
            _local_ns(2026, 11, 27, 12, 0, 0),
            _local_ns(2026, 11, 27, 13, 59, 59),
            "1h ago",
        ),
        # Same local calendar day >= 7200s -> 2h..23h ago, plus 24h ago on 25h DST fall-back
        (
            _local_ns(2026, 11, 27, 21, 30, 0),
            _local_ns(2026, 11, 27, 23, 30, 0),
            "2h ago",
        ),
        (
            _local_ns(2026, 11, 27, 0, 30, 0),
            _local_ns(2026, 11, 27, 23, 30, 0),
            "23h ago",
        ),
        (
            _local_ns(2026, 11, 1, 0, 15, 0),
            _local_ns(2026, 11, 1, 23, 30, 0),
            "24h ago",
        ),
        # Across local midnight: < 2h keeps minutes/1h; >= 2h becomes "yesterday"
        (
            _local_ns(2026, 11, 26, 23, 50, 0),
            _local_ns(2026, 11, 27, 0, 10, 0),
            "20m ago",
        ),
        (
            _local_ns(2026, 11, 26, 23, 10, 0),
            _local_ns(2026, 11, 27, 0, 30, 0),
            "1h ago",
        ),
        (
            _local_ns(2026, 11, 26, 22, 30, 0),
            _local_ns(2026, 11, 27, 0, 30, 0),
            "yesterday",
        ),
        (
            _local_ns(2026, 11, 26, 1, 0, 0),
            _local_ns(2026, 11, 27, 23, 0, 0),
            "yesterday",
        ),
        # 2..6 local calendar days -> fixed English Mon..Sun (all 7 weekdays covered)
        (
            _local_ns(2026, 11, 25, 12, 0, 0),
            _local_ns(2026, 11, 27, 12, 0, 0),
            "Wed",
        ),
        (
            _local_ns(2026, 11, 24, 12, 0, 0),
            _local_ns(2026, 11, 27, 12, 0, 0),
            "Tue",
        ),
        (
            _local_ns(2026, 11, 23, 12, 0, 0),
            _local_ns(2026, 11, 27, 12, 0, 0),
            "Mon",
        ),
        (
            _local_ns(2026, 11, 22, 12, 0, 0),
            _local_ns(2026, 11, 27, 12, 0, 0),
            "Sun",
        ),
        (
            _local_ns(2026, 11, 21, 12, 0, 0),
            _local_ns(2026, 11, 27, 12, 0, 0),
            "Sat",
        ),
        (
            _local_ns(2026, 11, 27, 12, 0, 0),
            _local_ns(2026, 11, 29, 12, 0, 0),
            "Fri",
        ),
        (
            _local_ns(2026, 11, 26, 12, 0, 0),
            _local_ns(2026, 11, 29, 12, 0, 0),
            "Thu",
        ),
        # 6 -> 7 calendar-day seam with < 7 * 86400s elapsed -> "1w ago" (not same weekday)
        (
            _local_ns(2026, 11, 20, 23, 59, 0),
            _local_ns(2026, 11, 27, 0, 1, 0),
            "1w ago",
        ),
        # 7..27 days -> 1w..3w ago
        (
            _local_ns(2026, 11, 27, 12, 0, 0) - 7 * _DAY_NS,
            _local_ns(2026, 11, 27, 12, 0, 0),
            "1w ago",
        ),
        (
            _local_ns(2026, 11, 27, 12, 0, 0) - 13 * _DAY_NS,
            _local_ns(2026, 11, 27, 12, 0, 0),
            "1w ago",
        ),
        (
            _local_ns(2026, 11, 27, 12, 0, 0) - 14 * _DAY_NS,
            _local_ns(2026, 11, 27, 12, 0, 0),
            "2w ago",
        ),
        (
            _local_ns(2026, 11, 27, 12, 0, 0) - 20 * _DAY_NS,
            _local_ns(2026, 11, 27, 12, 0, 0),
            "2w ago",
        ),
        (
            _local_ns(2026, 11, 27, 12, 0, 0) - 21 * _DAY_NS,
            _local_ns(2026, 11, 27, 12, 0, 0),
            "3w ago",
        ),
        (
            _local_ns(2026, 11, 27, 12, 0, 0) - 27 * _DAY_NS,
            _local_ns(2026, 11, 27, 12, 0, 0),
            "3w ago",
        ),
        # 28..364 days -> 1mo..11mo ago (clamped so 28..29 != 0mo and 360..364 != 12mo)
        (
            _local_ns(2026, 11, 27, 12, 0, 0) - 28 * _DAY_NS,
            _local_ns(2026, 11, 27, 12, 0, 0),
            "1mo ago",
        ),
        (
            _local_ns(2026, 11, 27, 12, 0, 0) - 29 * _DAY_NS,
            _local_ns(2026, 11, 27, 12, 0, 0),
            "1mo ago",
        ),
        (
            _local_ns(2026, 11, 27, 12, 0, 0) - 59 * _DAY_NS,
            _local_ns(2026, 11, 27, 12, 0, 0),
            "1mo ago",
        ),
        (
            _local_ns(2026, 11, 27, 12, 0, 0) - 60 * _DAY_NS,
            _local_ns(2026, 11, 27, 12, 0, 0),
            "2mo ago",
        ),
        (
            _local_ns(2026, 11, 27, 12, 0, 0) - 330 * _DAY_NS,
            _local_ns(2026, 11, 27, 12, 0, 0),
            "11mo ago",
        ),
        (
            _local_ns(2026, 11, 27, 12, 0, 0) - 364 * _DAY_NS,
            _local_ns(2026, 11, 27, 12, 0, 0),
            "11mo ago",
        ),
        # >= 365 days -> Ny ago
        (
            _local_ns(2026, 11, 27, 12, 0, 0) - 365 * _DAY_NS,
            _local_ns(2026, 11, 27, 12, 0, 0),
            "1y ago",
        ),
        (
            _local_ns(2026, 11, 27, 12, 0, 0) - 730 * _DAY_NS,
            _local_ns(2026, 11, 27, 12, 0, 0),
            "2y ago",
        ),
    ],
)
def test_format_relative_time_bucket_boundaries(
    ts_ns: int,
    now_ns: int,
    expected: str,
) -> None:
    assert format_relative_time(ts_ns, now_ns=now_ns, local_tz=_CHICAGO) == expected


def test_format_relative_time_defaults_to_live_clock_and_handles_synthetic_ids() -> (
    None
):
    current = time.time_ns()
    assert format_relative_time(current) == "now"
    synthetic_old = format_relative_time(1)
    assert synthetic_old.endswith("y ago")
    assert int(synthetic_old.removesuffix("y ago")) >= 50


def test_format_subthread_label_cases() -> None:
    origin_ts = 1_723_400_000_000_000_000
    now_ns = origin_ts + 300 * _NS
    subthread = f"general.{origin_ts}"

    assert (
        format_subthread_label(
            subthread,
            {"general": "#general"},
            now_ns=now_ns,
            local_tz=_CHICAGO,
        )
        == "#general (thread 5m ago)"
    )
    assert (
        format_subthread_label(
            subthread,
            {"general": "#main"},
            now_ns=now_ns,
            local_tz=_CHICAGO,
        )
        == "#main (thread 5m ago)"
    )
    assert (
        format_subthread_label(
            subthread,
            {},
            now_ns=now_ns,
            local_tz=_CHICAGO,
        )
        == "#general (thread 5m ago)"
    )
    assert format_subthread_label("general", {}, now_ns=now_ns) is None
    assert (
        format_subthread_label(
            "dm.d_abcdefghijklmnopqrstuvwxyz",
            {},
            now_ns=now_ns,
        )
        is None
    )
    assert format_subthread_label("general.notanid", {}, now_ns=now_ns) is None
    assert format_subthread_label("root\nthread\tlabel", {}, now_ns=now_ns) is None
