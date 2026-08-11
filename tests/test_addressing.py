from __future__ import annotations

import pytest

from taut import addressing
from taut._exceptions import ThreadNameError

pytestmark = pytest.mark.sqlite_only


def test_parse_channel_targets() -> None:
    expected = addressing.TargetAddress(
        kind="channel",
        thread="general",
        channel="general",
    )

    assert addressing.parse_target("general") == expected
    assert addressing.parse_target("#general") == expected


def test_parse_direct_message_target() -> None:
    target = addressing.parse_target("@Claude")

    assert target.kind == "dm"
    assert target.route_key == "claude"
    assert target.raw_route == "Claude"


def test_parse_stable_direct_message_write_target() -> None:
    stable_name = "dm.d_" + "a" * 26

    target = addressing.parse_target(stable_name)

    assert target == addressing.TargetAddress(kind="dm", thread=stable_name)


@pytest.mark.parametrize(
    "target",
    [
        "dm.d_short",
        "dm.d_" + "A" * 26,
        "dm.d_" + "0" * 26,
        "dm.other",
    ],
)
def test_parse_target_rejects_malformed_stable_dm_shapes(target: str) -> None:
    with pytest.raises(ThreadNameError) as caught:
        addressing.parse_target(target)
    assert str(caught.value) == f"invalid direct-message selector: {target}"


def test_direct_message_targets_can_be_disallowed() -> None:
    with pytest.raises(ThreadNameError, match="direct-message targets"):
        addressing.parse_target("@Claude", allow_dm=False)

    with pytest.raises(ThreadNameError, match="direct-message targets"):
        addressing.parse_target("dm.d_" + "a" * 26, allow_dm=False)


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


@pytest.mark.parametrize(
    ("queue_name", "expected"),
    [
        ("dm.d_" + "a" * 26, "dm"),
        ("notify.m_" + "b" * 26, "notification"),
        ("sys.events", "system"),
        ("taut.search_index", "system"),
        ("general.1837025672140161024", "subthread"),
        ("general", "channel"),
    ],
)
def test_classify_registered_queue_names(queue_name: str, expected: str) -> None:
    assert addressing.classify_registered_queue(queue_name) == expected


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


@pytest.mark.parametrize(
    "queue_name",
    [
        "dm",
        "dm.d_" + "a" * 26,
        "notify",
        "notify.m_" + "b" * 26,
        "sys",
        "sys.events",
        "taut",
        "taut.search_index",
    ],
)
def test_special_queue_names_are_reserved_by_prefix(queue_name: str) -> None:
    assert addressing.is_special_queue_name(queue_name) is True


@pytest.mark.parametrize(
    "queue_name",
    ["general", "general.1837025672140161024", "database.events"],
)
def test_ordinary_queue_names_do_not_use_reserved_prefixes(queue_name: str) -> None:
    assert addressing.is_special_queue_name(queue_name) is False
