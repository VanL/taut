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


def test_direct_message_targets_can_be_disallowed() -> None:
    with pytest.raises(ThreadNameError, match="direct-message targets"):
        addressing.parse_target("@Claude", allow_dm=False)


def test_direct_message_target_must_be_routable_member_name() -> None:
    with pytest.raises(ThreadNameError, match="name must match"):
        addressing.parse_target("@not.valid")


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


def test_validate_chat_thread_name_rejects_subthreads_when_channel_required() -> None:
    with pytest.raises(ThreadNameError, match="sub-thread names"):
        addressing.validate_chat_thread_name(
            "general.1837025672140161024",
            allow_subthread=False,
        )


def test_classify_registered_queue_names() -> None:
    assert addressing.classify_registered_queue("dm.d_abcdef") == "dm"
    assert addressing.classify_registered_queue("notify.m_member") == "notification"
    assert addressing.classify_registered_queue("sys.events") == "system"
    assert addressing.classify_registered_queue("general.1837025672140161024") == (
        "subthread"
    )
    assert addressing.classify_registered_queue("general") == "channel"


def test_dm_queue_name_is_unordered_pair() -> None:
    a = "m_" + "a" * 26
    b = "m_" + "b" * 26

    assert addressing.dm_queue_name(a, b) == addressing.dm_queue_name(b, a)
    assert addressing.dm_queue_name(a, b).startswith("dm.d_")


def test_member_scoped_queue_names_reject_invalid_member_ids() -> None:
    with pytest.raises(ValueError, match="invalid member id"):
        addressing.dm_queue_name("van", "m_" + "b" * 26)

    with pytest.raises(ValueError, match="invalid member id"):
        addressing.notification_queue_name("bob")


def test_parse_dm_selector_accepts_routes_and_exact_stable_handles() -> None:
    routed = addressing.parse_dm_selector("@Claude")
    assert routed is not None
    assert routed.kind == "dm"
    assert routed.route_key == "claude"
    assert routed.thread is None

    stable_name = "dm.d_" + "a" * 26
    stable = addressing.parse_dm_selector(stable_name)
    assert stable is not None
    assert stable.kind == "dm"
    assert stable.thread == stable_name
    assert stable.route_key is None

    assert addressing.parse_dm_selector("general") is None
    assert addressing.parse_dm_selector("general.1234567890123456789") is None


@pytest.mark.parametrize(
    "selector",
    [
        "dm.d_short",
        "dm.d_" + "A" * 26,
        "dm.d_" + "0" * 26,
        "dm.other",
        "@",
        "@bad.name",
    ],
)
def test_parse_dm_selector_rejects_malformed_dm_shapes(selector: str) -> None:
    with pytest.raises(ThreadNameError):
        addressing.parse_dm_selector(selector)


@pytest.mark.parametrize("selector", [None, 1, True, b"@bob"])
def test_parse_dm_selector_rejects_non_string_values(selector: object) -> None:
    with pytest.raises(TypeError, match="direct-message selector must be a string"):
        addressing.parse_dm_selector(selector)  # type: ignore[arg-type]


def test_notification_queue_name() -> None:
    member_id = "m_" + "a" * 26

    assert addressing.notification_queue_name(member_id) == f"notify.{member_id}"


def test_mentioned_route_keys_are_unique_and_boundary_aware() -> None:
    assert addressing.mentioned_route_keys("hi @Bob and @bob, email a@bob") == [
        ("bob", "@Bob")
    ]


def test_special_queue_names_are_reserved_by_prefix() -> None:
    assert addressing.is_special_queue_name("notify.m_abc") is True
    assert addressing.is_special_queue_name("general") is False
