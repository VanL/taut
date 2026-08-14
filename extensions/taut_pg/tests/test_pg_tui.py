"""Focused real-PostgreSQL smoke for the human-first TUI adapters.

Spec reference: docs/specs/10-taut-tui.md [TUI-13.1].
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from taut.client import Message, TautClient

pytestmark = pytest.mark.pg_only


def _wait_for_message(deliveries: list[object], text: str) -> None:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if any(isinstance(item, Message) and item.text == text for item in deliveries):
            return
        time.sleep(0.02)
    pytest.fail(f"live PostgreSQL delivery did not arrive: {text}")


def test_postgres_tui_navigation_send_live_search_and_doctor(
    taut_pg_project: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from taut_tui.domain import TuiDomainActions
    from taut_tui.session import TuiSession
    from taut_tui.system import TuiSystemOperations

    monkeypatch.chdir(taut_pg_project)
    TautClient.init()
    alice = TautClient(as_name="alice")
    bob = TautClient(as_name="bob")
    for client in (alice, bob):
        client.join("general")
    alice.say("general", "postgres tui search needle")
    deliveries: list[object] = []

    def accept_delivery(_generation: int, item: object) -> bool:
        deliveries.append(item)
        return True

    session = TuiSession(
        db_path=None,
        as_name="alice",
        auth_token=None,
        accept_delivery=accept_delivery,
    )
    system = TuiSystemOperations(db_path=None)
    domain = TuiDomainActions(session=session, system=system, db_path=None)
    try:
        navigation = session.refresh_navigation().result(timeout=10)
        assert [thread.name for thread in navigation.channels] == ["general"]

        snapshot = domain.open_conversation("general").result(timeout=10)
        assert snapshot is not None
        assert any(
            message.text == "postgres tui search needle"
            for message in snapshot.messages
        )

        sent = domain.send_message("general", "sent through tui domain").result(
            timeout=10
        )
        assert sent.text == "sent through tui domain"
        assert any(message.text == sent.text for message in bob.log("general"))

        bob.say("general", "postgres tui live")
        _wait_for_message(deliveries, "postgres tui live")

        hits = domain.search("postgres tui search needle").result(timeout=10)
        assert hits
        context = domain.open_search_result(hits[0]).result(timeout=10)
        assert any(message.ts == hits[0].ts for message in context)

        report = domain.doctor().result(timeout=10)
        assert report.healthy is True
    finally:
        session.close()
        system.close()
        alice.close()
        bob.close()
