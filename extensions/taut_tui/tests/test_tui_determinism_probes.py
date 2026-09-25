"""Forced real-owner schedules. Green probes do not invent S4's historical cause."""

from __future__ import annotations

import asyncio
import threading
from collections.abc import AsyncIterator, Callable
from concurrent.futures import Future
from contextlib import asynccontextmanager
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from _completion import Completion, CompletionKey, CompletionScope, CompletionTimeout

from taut.client import Message, TautClient
from taut_tui.app import TautApp
from taut_tui.session import NavigationSnapshot, TuiSession
from taut_tui.widgets import TautOptionList

pytestmark = pytest.mark.sqlite_only


class _NavigationProbe(TautApp):
    """Retain one initial request at actual source and owner application seams."""

    def __init__(self, db_path: Path, scope: CompletionScope) -> None:
        super().__init__(db_path=str(db_path), as_name="alice", continuity_token=None)
        self.scope = scope
        self.source_read: Completion[NavigationSnapshot] = scope.expect(
            CompletionKey(self, "navigation.sqlite_read", request=object())
        )
        self.source_returned: Completion[NavigationSnapshot] | None = None
        self.apply_delivered: Completion[Future[NavigationSnapshot]] | None = None
        self.applied: Completion[tuple[str | object, ...]] | None = None
        self.held_apply: Callable[[], None] | None = None
        self.deadline = 0.0

    def _watch_future(
        self, future: Future[Any], apply: Callable[[Future[Any]], None]
    ) -> None:
        if apply != self._apply_navigation_result or self.source_returned is not None:
            super()._watch_future(future, apply)
            return
        self.deadline = self.scope.now() + 5
        self.source_returned = self.scope.observe_future(
            future, owner=self, phase="navigation.source_returned"
        )
        self.apply_delivered = self.scope.expect(
            CompletionKey(self, "navigation.apply_delivered", future)
        )
        self.applied = self.scope.expect(
            CompletionKey(self, "navigation.applied", future)
        )

        def hold_apply(done: Future[NavigationSnapshot]) -> None:
            assert self.apply_delivered is not None

            def release() -> None:
                assert self.applied is not None
                apply(done)
                if done.cancelled():
                    self.applied.cancel(self.applied.key)
                elif (error := done.exception()) is not None:
                    self.applied.fail(self.applied.key, error)
                else:
                    self.applied.succeed(
                        self.applied.key, tuple(self._navigation_targets)
                    )

            self.held_apply = release
            self.apply_delivered.succeed(self.apply_delivered.key, done)

        super()._watch_future(future, hold_apply)


@asynccontextmanager
async def _running_probe(
    app: _NavigationProbe, release: threading.Event
) -> AsyncIterator[Any]:
    async with app.run_test(size=(100, 34)) as pilot:
        try:
            yield pilot
        finally:
            # Release before run_test joins the real serialized session owner.
            release.set()


def _seed_dm(db_path: Path) -> str:
    TautClient.init(db_path=db_path)
    alice = TautClient(db_path=db_path, as_name="alice")
    bob = TautClient(db_path=db_path, as_name="bob")
    try:
        alice.join("general")
        bob.join("general")
        return alice.say("@bob", "committed before navigation").thread
    finally:
        alice.close()
        bob.close()


async def _retired_attempt_observer(
    pilot: Any, predicate: Callable[[], bool], attempts: int
) -> None:
    """The retired Pilot observer, retained only for its causal red fixture."""
    for _ in range(attempts):
        await pilot.pause(0.01)
        if predicate():
            return
    pytest.fail("condition did not become true")


@pytest.mark.parametrize("old_attempts", [0, 200])
def test_real_dm_source_return_and_application_are_separate_owned_phases(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, old_attempts: int
) -> None:
    db_path = tmp_path / "phases.db"
    dm = _seed_dm(db_path)
    release_source = threading.Event()
    original_read = TuiSession._refresh_navigation_owned

    async def exercise() -> None:
        with CompletionScope() as scope:
            app = _NavigationProbe(db_path, scope)

            def held_read(session: TuiSession) -> NavigationSnapshot:
                snapshot = original_read(session)
                app.source_read.succeed(app.source_read.key, snapshot)
                if not release_source.wait(5):
                    raise TimeoutError(
                        "test did not release the real navigation worker"
                    )
                return snapshot

            monkeypatch.setattr(TuiSession, "_refresh_navigation_owned", held_read)
            try:
                async with _running_probe(app, release_source) as pilot:
                    source = await app.source_read.wait(
                        deadline=app.deadline, description="committed SQLite DM read"
                    )
                    assert dm in {thread.name for thread in source.direct_messages}, (
                        "source missing committed DM"
                    )
                    assert app.source_returned is not None
                    assert app.source_returned.snapshot() is None
                    assert app.applied is not None
                    assert app.applied.snapshot() is None
                    assert dm not in app._navigation_targets
                    release_source.set()
                    returned = await app.source_returned.wait(
                        deadline=app.deadline, description="navigation worker return"
                    )
                    assert returned is source
                    assert app.apply_delivered is not None
                    future = await app.apply_delivered.wait(
                        deadline=app.deadline,
                        description="navigation callback delivery",
                    )
                    assert future is app.source_returned.key.request
                    assert future.result() is source
                    assert app.applied.snapshot() is None
                    assert dm not in app._navigation_targets
                    assert app.held_apply is not None
                    # Elicitation (c), deliberately the retired observer's
                    # finite-attempt behavior. Each controlled yield runs on
                    # the existing loop; no wall clock or product is mocked.
                    if old_attempts:

                        async def controlled_pause(delay: float) -> None:
                            assert delay == 0.01
                            yielded = asyncio.get_running_loop().create_future()
                            asyncio.get_running_loop().call_soon(
                                yielded.set_result, None
                            )
                            await yielded

                        with monkeypatch.context() as pause_patch:
                            # Replace only this test Pilot's yield seam. The
                            # retired observer itself is unchanged and really
                            # exhausts its 200 attempts while apply is held.
                            pause_patch.setattr(pilot, "pause", controlled_pause)
                            with pytest.raises(
                                pytest.fail.Exception,
                                match="condition did not become true",
                            ):
                                await _retired_attempt_observer(
                                    pilot,
                                    lambda: dm in app._navigation_targets,
                                    old_attempts,
                                )
                    assert app.applied.snapshot() is None
                    assert scope.now() < app.deadline
                    app.call_later(app.held_apply)
                    rendered = await app.applied.wait(
                        deadline=app.deadline, description="navigation rendered DM"
                    )
                    assert dm in rendered, "applied navigation omitted committed DM"
                    assert dm in app._navigation_targets
                    assert app._target_labels[dm] == "DM with bob"
                    navigation = app.query_one("#navigation-list", TautOptionList)
                    dm_index = app._navigation_targets.index(dm)
                    assert navigation.option_count > dm_index, "rendered DM row missing"
                    assert "DM with bob" in str(
                        navigation.get_option_at_index(dm_index).prompt
                    )
            finally:
                release_source.set()

    asyncio.run(exercise())


@pytest.mark.parametrize("behavior_late", [False, True])
def test_real_setup_and_navigation_use_distinct_nonresetting_deadlines(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, behavior_late: bool
) -> None:
    """Advance only the observer clock at real serialized-worker barriers."""

    db_path = tmp_path / "split-budgets.db"
    dm = _seed_dm(db_path)
    clock = [0.0]
    setup_release, behavior_release = threading.Event(), threading.Event()
    session = TuiSession(db_path=str(db_path), as_name="alice", continuity_token=None)

    async def exercise() -> None:
        with CompletionScope(clock=lambda: clock[0]) as scope:
            setup_entered = scope.expect(
                CompletionKey(session, "bootstrap.client_owned", request=object())
            )
            behavior_entered = scope.expect(
                CompletionKey(session, "navigation.read", request=object())
            )
            original_read = session._refresh_navigation_owned

            def setup(client: TautClient) -> None:
                assert "general" in client.joined_thread_names()
                setup_entered.succeed(setup_entered.key, None)
                assert setup_release.wait(5), "bootstrap barrier not released"

            def read() -> NavigationSnapshot:
                result = original_read()
                assert dm in {thread.name for thread in result.direct_messages}
                behavior_entered.succeed(behavior_entered.key, None)
                assert behavior_release.wait(5), "behavior barrier not released"
                return result

            monkeypatch.setattr(session, "_refresh_navigation_owned", read)
            setup_deadline = scope.now() + 30
            setup_future = session.submit_client_operation(setup)
            setup_returned = scope.observe_future(
                setup_future, owner=session, phase="bootstrap.returned"
            )
            await setup_entered.wait(
                deadline=setup_deadline, description="bootstrap entered"
            )
            clock[0] = 12.0
            setup_release.set()
            await setup_returned.wait(
                deadline=setup_deadline, description="bootstrap complete"
            )

            # Behavior starts at its actual request, not at bootstrap start.
            behavior_deadline = scope.now() + 5
            future = session.refresh_navigation()
            returned = scope.observe_future(
                future, owner=session, phase="navigation.returned"
            )
            await behavior_entered.wait(
                deadline=behavior_deadline, description="navigation read"
            )
            assert returned.snapshot() is None
            clock[0] = 17.001 if behavior_late else 16.999
            behavior_release.set()
            if behavior_late:
                with pytest.raises(CompletionTimeout, match="navigation.returned"):
                    await returned.wait(
                        deadline=behavior_deadline, description="behavior budget"
                    )
                assert future.cancelled() is False
            else:
                result = await returned.wait(
                    deadline=behavior_deadline, description="behavior budget"
                )
                assert dm in {thread.name for thread in result.direct_messages}

    try:
        asyncio.run(exercise())
    finally:
        setup_release.set()
        behavior_release.set()
        session.close()


def test_queued_old_highlight_cannot_replace_new_search_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def exercise() -> None:
        with CompletionScope() as scope:
            app = TautApp(db_path=None, as_name=None, continuity_token=None)
            async with app.run_test(size=(100, 34)):
                transcript = app.query_one("#transcript", TautOptionList)
                messages = tuple(
                    Message(
                        "general", index, "m_alice", "alice", "message", f"row {index}"
                    )
                    for index in range(1, 4)
                )
                app._render_messages(messages)
                stale = transcript.OptionHighlighted(
                    transcript, transcript.get_option_at_index(2), 2
                )
                delivered = scope.expect(
                    CompletionKey(app, "old-highlight.applied", stale)
                )
                dispatch = app._on_message

                async def observe(message: Any) -> None:
                    await dispatch(message)
                    if message is stale:
                        delivered.succeed(delivered.key, None)

                # This is a real queued Textual message, not a direct handler
                # call. No yield separates queuing it from arming newer search.
                monkeypatch.setattr(app, "_on_message", observe)
                transcript.post_message(stale)
                app._conversation_intent = 7
                hit = messages[1]
                app.visual_state = replace(app.visual_state, selected_message_id=hit.ts)
                app._arm_search_anchor(7, hit.ts)
                await delivered.wait(
                    deadline=scope.now() + 5, description="old highlight delivered"
                )
                assert app.visual_state.selected_message_id == hit.ts
                assert app.visual_state.viewport.message_id == hit.ts
                assert app.visual_state.viewport.search_owned is True

    asyncio.run(exercise())
