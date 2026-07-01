from __future__ import annotations

import pytest

from taut import addressing
from taut._exceptions import ThreadNameError

pytestmark = pytest.mark.sqlite_only


def test_parse_channel_targets() -> None:
    bare = addressing.parse_target("general")
    hashed = addressing.parse_target("#general")

    assert bare.kind == "channel"
    assert bare.thread == "general"
    assert hashed.thread == "general"


def test_parse_direct_message_target() -> None:
    target = addressing.parse_target("@Claude")

    assert target.kind == "dm"
    assert target.route_key == "claude"
    assert target.raw_route == "Claude"


def test_parse_subthread_target() -> None:
    target = addressing.parse_target("general.1837025672140161024")

    assert target.kind == "subthread"
    assert target.thread == "general.1837025672140161024"
    assert target.channel == "general"
    assert target.origin_ts == 1837025672140161024


@pytest.mark.parametrize(
    "target",
    [
        "general.foo",
        "general.extra.1837025672140161024",
        "dm",
        "notify",
        "sys",
        "taut",
    ],
)
def test_reject_invalid_or_reserved_channel_targets(target: str) -> None:
    with pytest.raises(ThreadNameError):
        addressing.parse_target(target)


def test_dm_queue_name_is_unordered_pair() -> None:
    a = "m_" + "a" * 26
    b = "m_" + "b" * 26

    assert addressing.dm_queue_name(a, b) == addressing.dm_queue_name(b, a)
    assert addressing.dm_queue_name(a, b).startswith("dm.d_")


def test_notification_queue_name() -> None:
    member_id = "m_" + "a" * 26

    assert addressing.notification_queue_name(member_id) == f"notify.{member_id}"
