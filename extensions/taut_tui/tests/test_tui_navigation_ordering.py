"""Real SQLite schedules; navigation has no generation-rejection contract."""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable
from concurrent.futures import Future
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from _completion import Completion, CompletionKey, CompletionScope
from _screen_completion import ScreenCompletions
from textual.widgets import Input, OptionList

from taut.client import Message, SearchHit, TautClient
from taut_tui.app import TautApp
from taut_tui.screens import SearchScreen
from taut_tui.session import NavigationSnapshot, TuiSession
from taut_tui.widgets import TautOptionList

pytestmark = pytest.mark.sqlite_only


def _seed(db: Path) -> tuple[str, Message, Message]:
    TautClient.init(db_path=db)
    alice = TautClient(db_path=db, as_name="alice")
    bob = TautClient(db_path=db, as_name="bob")
    try:
        alice.join("general")
        bob.join("general")
        old = alice.say("general", "oldneedle channel history")
        new = alice.say("@bob", "newneedle committed direct message")
        return new.thread, old, new
    finally:
        alice.close()
        bob.close()


def test_serialized_navigation_read_cannot_overtake_held_older_worker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = tmp_path / "serialized.db"
    dm, _old, _new = _seed(db)
    session = TuiSession(db_path=str(db), as_name="alice", continuity_token=None)
    release = threading.Event()
    history: list[str] = []
    owners: list[threading.Thread] = []
    original_read = session._refresh_navigation_owned

    async def exercise() -> None:
        with CompletionScope() as scope:

            def old_read() -> NavigationSnapshot:
                owners.append(threading.current_thread())
                snapshot = original_read()
                history.append("old.read")
                old_read_done.succeed(old_read_done.key, snapshot)
                assert release.wait(5), "older navigation worker was not released"
                history.append("old.return")
                return snapshot

            def new_read() -> NavigationSnapshot:
                owners.append(threading.current_thread())
                snapshot = original_read()
                history.append("new.read")
                new_read_done.succeed(new_read_done.key, snapshot)
                history.append("new.return")
                return snapshot

            # Each callable is the exact submitted worker operation, not a
            # invented product navigation generation. Retain its actual Future
            # separately once the real executor returns that identity.
            old_read_done = scope.expect(
                CompletionKey(session, "navigation.read", old_read)
            )
            new_read_done = scope.expect(
                CompletionKey(session, "navigation.read", new_read)
            )
            monkeypatch.setattr(session, "_refresh_navigation_owned", old_read)
            deadline = scope.now() + 5
            old_future = session.refresh_navigation()
            old_returned = scope.observe_future(
                old_future, owner=session, phase="navigation.returned"
            )
            old_source = await old_read_done.wait(
                deadline=deadline, description="older SQLite read"
            )
            assert dm in {thread.name for thread in old_source.direct_messages}
            assert old_future.running()
            assert old_returned.snapshot() is None

            monkeypatch.setattr(session, "_refresh_navigation_owned", new_read)
            new_future = session.refresh_navigation()
            new_returned = scope.observe_future(
                new_future, owner=session, phase="navigation.returned"
            )
            assert new_future is not old_future
            assert not new_future.running()
            assert new_read_done.snapshot() is None
            assert new_returned.snapshot() is None

            release.set()
            assert (
                await old_returned.wait(
                    deadline=deadline, description="older worker return"
                )
                is old_source
            )
            new_source = await new_returned.wait(
                deadline=deadline, description="newer worker return"
            )
            assert (
                await new_read_done.wait(
                    deadline=deadline, description="newer SQLite read"
                )
                is new_source
            )
            assert dm in {thread.name for thread in new_source.direct_messages}
            assert history == ["old.read", "old.return", "new.read", "new.return"]
            assert owners[0] is owners[1]

    try:
        asyncio.run(exercise())
    finally:
        release.set()
        session.close()


@dataclass(frozen=True)
class _NavigationDelivery:
    future: Future[NavigationSnapshot]
    started_at: float
    source: Completion[NavigationSnapshot]
    delivered: Completion[Future[NavigationSnapshot]]
    applied: Completion[tuple[str | object, ...]]
    release: Callable[[], None]


class _OrderedNavigationApp(TautApp):
    def __init__(
        self, db: Path, scope: CompletionScope, patch: pytest.MonkeyPatch
    ) -> None:
        super().__init__(db_path=str(db), as_name="alice", continuity_token=None)
        self.scope = scope
        self.navigation: list[_NavigationDelivery] = []
        self.applied_futures: list[Future[NavigationSnapshot]] = []
        self.submissions: dict[Future[NavigationSnapshot], float] = {}
        original_refresh = TuiSession.refresh_navigation

        def refresh(session: TuiSession) -> Future[NavigationSnapshot]:
            started_at = scope.now()
            future = original_refresh(session)
            if session is self._session:
                self.submissions[future] = started_at
            return future

        patch.setattr(TuiSession, "refresh_navigation", refresh)

    def _watch_future(
        self, future: Future[Any], apply: Callable[[Future[Any]], None]
    ) -> None:
        if apply != self._apply_navigation_result:
            super()._watch_future(future, apply)
            return
        assert self._session is not None
        assert len(self.navigation) < 2, "only the two explicit navigation requests"
        source = self.scope.observe_future(
            future, owner=self._session, phase="navigation.returned"
        )
        delivered: Completion[Future[NavigationSnapshot]] = self.scope.expect(
            CompletionKey(self, "navigation.delivered", future)
        )
        applied: Completion[tuple[str | object, ...]] = self.scope.expect(
            CompletionKey(self, "navigation.applied", future)
        )

        def release() -> None:
            assert delivered.snapshot() is not None
            try:
                apply(future)
                future.result()
            except BaseException as error:
                applied.fail(applied.key, error)
                raise
            self.applied_futures.append(future)
            applied.succeed(applied.key, tuple(self._navigation_targets))

        def hold(done: Future[NavigationSnapshot]) -> None:
            assert done is future
            delivered.succeed(delivered.key, done)

        self.navigation.append(
            _NavigationDelivery(
                future, self.submissions[future], source, delivered, applied, release
            )
        )
        super()._watch_future(future, hold)


def _assert_dm_row(app: TautApp, dm: str) -> None:
    assert dm in app._navigation_targets
    assert app._target_labels[dm] == "DM with bob"
    navigation = app.query_one("#navigation-list", TautOptionList)
    dm_index = app._navigation_targets.index(dm)
    assert navigation.option_count > dm_index
    assert "DM with bob" in str(navigation.get_option_at_index(dm_index).prompt)


def test_reordered_navigation_callbacks_retain_dm_committed_before_both_reads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = tmp_path / "callback-order.db"
    dm, _old, _new = _seed(db)

    async def exercise() -> None:
        with CompletionScope() as scope:
            app = _OrderedNavigationApp(db, scope, monkeypatch)
            async with app.run_test(size=(100, 34)):
                older = app.navigation[0]
                deadline = older.started_at + 5
                old_source = await older.source.wait(
                    deadline=deadline, description="older navigation source"
                )
                assert dm in {thread.name for thread in old_source.direct_messages}
                assert (
                    await older.delivered.wait(
                        deadline=deadline, description="older callback held"
                    )
                    is older.future
                )
                assert older.applied.snapshot() is None

                assert app._session is not None
                deadline = scope.now() + 5
                new_future = app._session.refresh_navigation()
                app._watch_future(new_future, app._apply_navigation_result)
                newer = app.navigation[1]
                assert newer.future is new_future and new_future is not older.future
                new_source = await newer.source.wait(
                    deadline=deadline, description="newer navigation source"
                )
                assert dm in {thread.name for thread in new_source.direct_messages}
                assert (
                    await newer.delivered.wait(
                        deadline=deadline, description="newer callback held"
                    )
                    is new_future
                )

                app.call_later(newer.release)
                assert dm in await newer.applied.wait(
                    deadline=deadline, description="newer navigation applied first"
                )
                _assert_dm_row(app, dm)
                app.call_later(older.release)
                assert dm in await older.applied.wait(
                    deadline=deadline, description="older navigation applied last"
                )
                assert app.applied_futures == [new_future, older.future]
                _assert_dm_row(app, dm)
                # Both callbacks really ran. NavigationSnapshot has no
                # generation, so this is not proof of stale-result rejection.

    asyncio.run(exercise())


@dataclass(frozen=True)
class _SearchDelivery:
    generation: int
    future: Future[list[SearchHit]]
    source: Completion[list[SearchHit]]
    delivered: Completion[Future[list[SearchHit]]]
    finished: Completion[tuple[SearchHit, ...]]
    release: Callable[[], None]


def _hold_search_callbacks(
    screen: SearchScreen, scope: CompletionScope, patch: pytest.MonkeyPatch
) -> list[_SearchDelivery]:
    original_search = screen._search
    original_apply = screen._apply_results
    requests: list[_SearchDelivery] = []
    by_future: dict[Future[list[SearchHit]], _SearchDelivery] = {}

    def search(query: str) -> Future[list[SearchHit]]:
        assert len(requests) < 2, "only the two explicit search requests"
        generation = screen._generation
        future = original_search(query)
        source = scope.observe_future(
            future, owner=screen, phase="search.source", generation=generation
        )
        delivered: Completion[Future[list[SearchHit]]] = scope.expect(
            CompletionKey(screen, "search.delivered", future, generation)
        )
        finished: Completion[tuple[SearchHit, ...]] = scope.expect(
            CompletionKey(screen, "search.callback_finished", future, generation)
        )

        def release() -> None:
            assert delivered.snapshot() is not None
            try:
                original_apply(generation, future)
                future.result()
            except BaseException as error:
                finished.fail(finished.key, error)
                raise
            finished.succeed(finished.key, screen._results)

        request = _SearchDelivery(
            generation, future, source, delivered, finished, release
        )
        requests.append(request)
        by_future[future] = request
        return future

    def hold(generation: int, future: Future[list[SearchHit]]) -> None:
        request = by_future[future]
        assert generation == request.generation
        request.delivered.succeed(request.delivered.key, future)

    patch.setattr(screen, "_search", search)
    patch.setattr(screen, "_apply_results", hold)
    return requests


def test_stale_real_search_callback_cannot_replace_newer_committed_dm_results(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = tmp_path / "search-order.db"
    dm, old_message, new_message = _seed(db)

    async def exercise() -> None:
        with CompletionScope() as scope:
            app = _OrderedNavigationApp(db, scope, monkeypatch)
            screens = ScreenCompletions(app, scope, monkeypatch)
            try:
                async with app.run_test(size=(100, 34)) as pilot:
                    navigation = app.navigation[0]
                    deadline = navigation.started_at + 5
                    await navigation.delivered.wait(
                        deadline=deadline, description="initial navigation callback"
                    )
                    app.call_later(navigation.release)
                    await navigation.applied.wait(
                        deadline=deadline, description="initial DM navigation"
                    )
                    _assert_dm_row(app, dm)

                    deadline = scope.now() + 5
                    app.action_open_search()
                    screen = app.screen
                    assert isinstance(screen, SearchScreen)
                    await screens.ready(screen, deadline=deadline)
                    query = screen.query_one("#search-query", Input)
                    await screens.ready(screen, deadline=deadline, focus=query)
                    requests = _hold_search_callbacks(screen, scope, monkeypatch)

                    deadline = scope.now() + 5
                    query.value = "oldneedle"
                    await pilot.press("enter")
                    older = requests[0]
                    old_source = await older.source.wait(
                        deadline=deadline, description="older real history search"
                    )
                    assert [hit.ts for hit in old_source] == [old_message.ts]
                    assert old_source[0].thread == "general"
                    assert (
                        await older.delivered.wait(
                            deadline=deadline, description="older search callback held"
                        )
                        is older.future
                    )
                    assert older.finished.snapshot() is None

                    deadline = scope.now() + 5
                    query.value = "newneedle"
                    await pilot.press("enter")
                    newer = requests[1]
                    assert newer.future is not older.future
                    assert newer.generation > older.generation
                    new_source = await newer.source.wait(
                        deadline=deadline, description="newer real DM history search"
                    )
                    assert [hit.ts for hit in new_source] == [new_message.ts]
                    assert new_source[0].thread == dm
                    assert (
                        await newer.delivered.wait(
                            deadline=deadline, description="newer search callback held"
                        )
                        is newer.future
                    )

                    app.call_later(newer.release)
                    newest = await newer.finished.wait(
                        deadline=deadline, description="newer search callback applied"
                    )
                    assert [hit.ts for hit in newest] == [new_message.ts]
                    app.call_later(older.release)
                    after_stale = await older.finished.wait(
                        deadline=deadline, description="older search callback rejected"
                    )
                    assert [hit.ts for hit in after_stale] == [new_message.ts]
                    assert screen._generation == newer.generation
                    options = screen.query_one("#search-results", OptionList)
                    assert options.option_count == 1
                    prompt = str(options.get_option_at_index(0).prompt)
                    assert "DM with bob" in prompt
                    assert "newneedle committed direct message" in prompt
                    assert "oldneedle" not in prompt

                    deadline = scope.now() + 5
                    screen.dismiss(None)
                    await screens.result_applied(screen).wait(
                        deadline=deadline, description="search dismissal callback"
                    )
                    await screens.retired(screen).wait(
                        deadline=deadline, description="search screen retired"
                    )
            finally:
                screens.close()

    asyncio.run(exercise())
