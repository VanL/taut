"""Model-based membership and cursor tests through the public client API."""

from __future__ import annotations

from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal

import pytest
from hypothesis import HealthCheck, settings
from hypothesis import strategies as st
from hypothesis.stateful import (
    RuleBasedStateMachine,
    invariant,
    precondition,
    rule,
    run_state_machine_as_test,
)

from taut._exceptions import EmptyResultError, MembershipError, NotFoundError
from taut.client import Message, TautClient

pytestmark = pytest.mark.sqlite_only

Actor = Literal["alice", "bob"]
ACTORS: tuple[Actor, ...] = ("alice", "bob")
ACTOR = st.sampled_from(ACTORS)
TEXT = st.text(alphabet="abcdefghijklmnopqrstuvwxyz ", max_size=12)


@dataclass(frozen=True, slots=True)
class ExpectedRecord:
    ts: int
    from_name: str
    kind: str
    text: str


class ClientMembershipCursorMachine(RuleBasedStateMachine):
    """Compare real client behavior with a small membership/cursor model."""

    def __init__(self) -> None:
        super().__init__()
        self._resources = ExitStack()
        self.clients: dict[Actor, TautClient] = {}
        try:
            root = Path(
                self._resources.enter_context(
                    TemporaryDirectory(prefix="taut-client-stateful-")
                )
            )
            db_path = root / ".taut.db"
            TautClient.init(db_path=db_path)
            for actor in ACTORS:
                client = TautClient(db_path=db_path, as_name=actor, persistent=True)
                self.clients[actor] = client
                self._resources.callback(client.close)

            self.known: dict[Actor, bool] = {"alice": True, "bob": False}
            self.joined: dict[Actor, bool] = {"alice": True, "bob": False}
            self.cursors: dict[Actor, int | None] = {"alice": 0, "bob": None}
            self.history: list[ExpectedRecord] = []

            created = self.clients["alice"].join("general")
            self._append_record(
                created,
                from_name="alice",
                kind="notice",
                text="alice created #general",
            )
            self.cursors["alice"] = len(self.history)
        except BaseException:
            self._resources.close()
            raise

    def teardown(self) -> None:
        self._resources.close()

    def _append_record(
        self,
        message: Message,
        *,
        from_name: str,
        kind: str,
        text: str,
    ) -> None:
        assert (message.thread, message.from_name, message.kind, message.text) == (
            "general",
            from_name,
            kind,
            text,
        )
        if self.history:
            assert message.ts > self.history[-1].ts
        self.history.append(
            ExpectedRecord(
                ts=message.ts,
                from_name=from_name,
                kind=kind,
                text=text,
            )
        )

    @staticmethod
    def _records(messages: list[Message]) -> list[ExpectedRecord]:
        return [
            ExpectedRecord(
                ts=message.ts,
                from_name=message.from_name,
                kind=message.kind,
                text=message.text,
            )
            for message in messages
        ]

    @precondition(lambda self: not self.joined["bob"])
    @rule()
    def bob_join(self) -> None:
        joined = self.clients["bob"].join("general")
        self._append_record(
            joined,
            from_name="bob",
            kind="notice",
            text="bob joined",
        )
        self.known["bob"] = True
        self.joined["bob"] = True
        self.cursors["bob"] = len(self.history)

    @precondition(lambda self: self.joined["bob"])
    @rule()
    def bob_leave(self) -> None:
        left = self.clients["bob"].leave("general")
        self.joined["bob"] = False
        self.cursors["bob"] = None
        self._append_record(
            left,
            from_name="bob",
            kind="notice",
            text="bob left",
        )

    @rule(actor=ACTOR, text=TEXT)
    def post(self, actor: Actor, text: str) -> None:
        if actor == "bob" and not self.joined["bob"]:
            if self.known["bob"]:
                with pytest.raises(
                    MembershipError,
                    match="^bob is not a member of general$",
                ):
                    self.clients["bob"].say("general", text)
            else:
                with pytest.raises(NotFoundError, match="^member not found: bob$"):
                    self.clients["bob"].say("general", text)
            return

        prior_tail = len(self.history)
        prior_cursor = self.cursors[actor]
        assert prior_cursor is not None
        message = self.clients[actor].say("general", text)
        self._append_record(
            message,
            from_name=actor,
            kind="message",
            text=text,
        )
        if prior_cursor == prior_tail:
            self.cursors[actor] = len(self.history)

    @rule(actor=ACTOR)
    def read(self, actor: Actor) -> None:
        if actor == "bob" and not self.joined["bob"]:
            if self.known["bob"]:
                with pytest.raises(
                    MembershipError,
                    match="^bob is not a member of general$",
                ):
                    self.clients["bob"].read("general")
            else:
                with pytest.raises(NotFoundError, match="^member not found: bob$"):
                    self.clients["bob"].read("general")
            return

        cursor = self.cursors[actor]
        assert cursor is not None
        expected = self.history[cursor:]
        if not expected:
            with pytest.raises(EmptyResultError, match="^nothing unread$"):
                self.clients[actor].read("general")
            return

        assert self._records(self.clients[actor].read("general")) == expected
        self.cursors[actor] = len(self.history)

    @rule()
    def inspect_log(self) -> None:
        assert self._records(self.clients["alice"].log("general")) == self.history

    @invariant()
    def public_state_matches_model(self) -> None:
        logged = self._records(self.clients["alice"].log("general"))
        assert logged == self.history
        assert [record.ts for record in logged] == sorted(
            record.ts for record in logged
        )

        for actor in ACTORS:
            client = self.clients[actor]
            if not self.known[actor]:
                with pytest.raises(NotFoundError, match="^member not found: bob$"):
                    client.joined_thread_names()
            else:
                expected_names = ("general",) if self.joined[actor] else ()
                assert client.joined_thread_names() == expected_names

            thread = next(
                item
                for item in client.list_threads(all_threads=True)
                if item.name == "general"
            )
            cursor = self.cursors[actor]
            expected_unread = (
                len(self.history) - cursor
                if self.joined[actor] and cursor is not None
                else 0
            )
            assert thread.unread_count == expected_unread
            assert thread.unread is (expected_unread > 0)
            assert thread.last_ts == self.history[-1].ts


def test_client_membership_and_cursor_semantics_match_reference_model() -> None:
    run_state_machine_as_test(
        ClientMembershipCursorMachine,
        settings=settings(
            max_examples=12,
            stateful_step_count=12,
            deadline=None,
            suppress_health_check=[HealthCheck.too_slow],
        ),
    )


def test_membership_rejoin_starts_after_history_written_while_left(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / ".taut.db"
    TautClient.init(db_path=db_path)
    alice = TautClient(db_path=db_path, as_name="alice")
    bob = TautClient(db_path=db_path, as_name="bob")
    try:
        alice.join("general")
        bob.join("general")
        bob.leave("general")
        while_away = alice.say("general", "written while bob was away")

        rejoined = bob.join("general")

        assert rejoined.text == "bob joined"
        with pytest.raises(EmptyResultError, match="^nothing unread$"):
            bob.read("general")
        assert while_away.ts in [message.ts for message in bob.log("general")]

        after_rejoin = alice.say("general", "written after bob rejoined")
        assert [message.ts for message in bob.read("general")] == [after_rejoin.ts]
    finally:
        bob.close()
        alice.close()
