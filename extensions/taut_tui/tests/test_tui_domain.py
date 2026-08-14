"""Native extension action mapping to public Taut operations.

Spec references:
- docs/specs/10-taut-tui.md [TUI-2.3], [TUI-6], [TUI-7]
"""

from __future__ import annotations

from pathlib import Path

import pytest

from taut.client import TautClient
from taut_tui.actions import ActionId

pytestmark = pytest.mark.sqlite_only


def _seed(db_path: Path) -> tuple[TautClient, TautClient]:
    TautClient.init(db_path=db_path)
    alice = TautClient(db_path=db_path, as_name="alice")
    bob = TautClient(db_path=db_path, as_name="bob")
    for client in (alice, bob):
        client.join("general")
    return alice, bob


def test_every_nonvisual_nonsummon_action_has_native_domain_ownership() -> None:
    from taut_tui.domain import CORE_DOMAIN_ACTIONS

    visual = {
        ActionId.COMPOSE_ENTER,
        ActionId.COMMAND_OPEN,
        ActionId.HELP_OPEN,
        ActionId.APPLICATION_QUIT,
    }
    summon = {
        ActionId.SUMMON_START,
        ActionId.SUMMON_LIST,
        ActionId.SUMMON_STATUS,
        ActionId.SUMMON_DISMISS,
    }

    assert CORE_DOMAIN_ACTIONS == set(ActionId) - visual - summon


def test_native_identity_channel_message_search_and_context_flow(
    tmp_path: Path,
) -> None:
    from taut_tui.domain import TuiDomainActions
    from taut_tui.session import TuiSession
    from taut_tui.system import TuiSystemOperations

    db_path = tmp_path / "chat.db"
    alice, bob = _seed(db_path)
    session = TuiSession(db_path=str(db_path), as_name="alice", auth_token=None)
    system = TuiSystemOperations(db_path=str(db_path))
    actions = TuiDomainActions(
        session=session,
        system=system,
        db_path=str(db_path),
    )
    try:
        assert actions.show_identity().result(timeout=5).name == "alice"
        assert actions.set_persona("reviewer").result(timeout=5).persona == "reviewer"
        assert actions.members("general").result(timeout=5)
        topic = actions.set_topic("general", "Release coordination").result(timeout=5)
        assert topic.topic == "Release coordination"
        assert actions.show_topic("general").result(timeout=5) == topic

        sent = actions.send_message("general", "searchable marker").result(timeout=5)
        hits = actions.search("searchable marker").result(timeout=5)
        hit = next(item for item in hits if item.ts == sent.ts)
        context = actions.open_search_result(hit, before=1, after=1).result(timeout=5)
        assert any(message.ts == sent.ts for message in context)

        reaction = actions.react_message(sent.ts, "ack").result(timeout=5)
        assert reaction.message_ts == sent.ts
        deletion = actions.delete_message(sent.ts).result(timeout=5)
        assert deletion.ts == sent.ts
        assert actions.clear_topic("general").result(timeout=5).topic is None
    finally:
        session.close()
        system.close()
        alice.close()
        bob.close()


def test_direct_message_and_reply_flows_keep_core_target_semantics(
    tmp_path: Path,
) -> None:
    from taut_tui.domain import TuiDomainActions
    from taut_tui.session import TuiSession
    from taut_tui.system import TuiSystemOperations

    db_path = tmp_path / "chat.db"
    alice, bob = _seed(db_path)
    origin = bob.say("general", "please review")
    session = TuiSession(db_path=str(db_path), as_name="alice", auth_token=None)
    system = TuiSystemOperations(db_path=str(db_path))
    actions = TuiDomainActions(
        session=session,
        system=system,
        db_path=str(db_path),
    )
    try:
        direct = actions.start_direct_message("bob", "hello privately").result(
            timeout=5
        )
        reply = actions.reply_message("general", origin.ts, "reviewed").result(
            timeout=5
        )
    finally:
        session.close()
        system.close()
        alice.close()
        bob.close()

    assert direct.thread.startswith("dm.")
    assert reply.thread == f"general.{origin.ts}"


def test_empty_real_search_returns_the_domain_empty_collection(tmp_path: Path) -> None:
    from taut_tui.domain import TuiDomainActions
    from taut_tui.session import TuiSession
    from taut_tui.system import TuiSystemOperations

    db_path = tmp_path / "empty-search.db"
    alice, bob = _seed(db_path)
    session = TuiSession(db_path=str(db_path), as_name="alice", auth_token=None)
    system = TuiSystemOperations(db_path=str(db_path))
    actions = TuiDomainActions(
        session=session,
        system=system,
        db_path=str(db_path),
    )
    try:
        assert actions.search("nothing-can-match-this").result(timeout=5) == []
    finally:
        session.close()
        system.close()
        alice.close()
        bob.close()
