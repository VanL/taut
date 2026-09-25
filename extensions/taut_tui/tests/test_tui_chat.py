"""Serialized extension session ownership and active-only live delivery tests.

Spec references:
- docs/specs/10-taut-tui.md [TUI-4.1], [TUI-6]
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from concurrent.futures import Future
from pathlib import Path
from threading import Event, Lock
from typing import Any

import pytest
from _app_completion import AppCompletions, observed
from _chat_completion import InitialDrainEvent, SessionDeliveries
from _completion import (
    Completion,
    CompletionKey,
    CompletionScope,
    CompletionSuperseded,
    CompletionTimeout,
)
from simplebroker import Queue

from taut.client import Message, Notification, TautClient
from taut_tui.app import TautApp
from taut_tui.session import ConversationSnapshot, NavigationSnapshot
from taut_tui.viewport import ViewportEffect, ViewportEffectKind

pytestmark = pytest.mark.sqlite_only


@pytest.fixture(autouse=True)
def _observe_chat_apps(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    original = TautApp.__init__
    probes: list[AppCompletions] = []

    def initialize(app: Any, *args: Any, **kwargs: Any) -> None:
        original(app, *args, **kwargs)
        probe = AppCompletions(app, monkeypatch)
        app._test_completions = probe
        probes.append(probe)

    monkeypatch.setattr(TautApp, "__init__", initialize)
    try:
        yield
    finally:
        for probe in probes:
            probe.close()


def test_session_delivery_completion_retains_exact_generation_and_message() -> None:
    from _completion import CompletionTimeout

    calls: list[tuple[int, Message | Notification]] = []

    def accept(generation: int, item: Message | Notification) -> bool:
        calls.append((generation, item))
        return True

    probe = SessionDeliveries(accept)
    probe.bind(object())
    message = Message("general", 7, "alice-id", "alice", "message", "same text")
    try:
        assert probe.accept(3, message) is True
        with pytest.raises(CompletionTimeout):
            probe.wait(4, message, deadline=probe.scope.now())
        assert probe.wait(3, message, deadline=probe.scope.now() + 5) is message
        assert calls == [(3, message)]
    finally:
        probe.close()


class _NotificationRefreshProbe:
    def __init__(self, app: TautApp, *, last_history_ts: int) -> None:
        self._app = app
        self._last_history_ts = last_history_ts
        self.scope = observed(app).scope
        self.history_caught_up: Completion[Any] | None = None
        self.notification_refresh_applied: Completion[Any] | None = None
        self.notification_requested = self.scope.expect(
            CompletionKey(app, "notification.refresh_requested", request=self)
        )
        self.notification_armed = False
        self.observed_notification_ts: int | None = None
        self.notification_refresh_succeeded: bool | None = None
        self._handling_notification = False
        self._applying_target_navigation = False
        self._target_effect: ViewportEffect | None = None
        self._target_refresh: Future[NavigationSnapshot] | None = None
        self._original_apply_delivery = app._apply_delivery
        self._original_apply_navigation = app._apply_navigation_result
        self._original_apply_optional = app._apply_optional_conversation
        self._original_apply_effect = app._apply_viewport_effect
        self._original_after_refresh = app.call_after_refresh
        self.original_refresh_navigation: (
            Callable[[], Future[NavigationSnapshot]] | None
        ) = None

    def observe_open_conversation(
        self,
        intent: int,
        future: Future[ConversationSnapshot | None],
        *,
        error_prefix: str = "",
    ) -> None:
        self._original_apply_optional(intent, future, error_prefix=error_prefix)
        if future.cancelled() or future.exception() is not None:
            return
        snapshot = future.result()
        if snapshot is None or snapshot.target != "general":
            return
        if not any(
            message.ts == self._last_history_ts for message in snapshot.messages
        ):
            return
        transcript = self._app.query_one("#transcript")
        completed = self.scope.expect(
            CompletionKey(self._app, "history.scroll_applied", future)
        )
        self.history_caught_up = completed

        def scrolled() -> None:
            completed.succeed(completed.key, snapshot)

        # Queue behind the final future-driven render's initial tail scroll.
        transcript.scroll_end(
            animate=False,
            on_complete=scrolled,
        )

    def observe_delivery(
        self,
        generation: int,
        item: Message | Notification,
    ) -> bool:
        is_target_notification = (
            self.notification_armed
            and isinstance(item, Notification)
            and item.thread == "quiet"
            and item.actor_name == "bob"
            and item.matched == "@alice"
        )
        if is_target_notification:
            assert isinstance(item, Notification)
            assert item.message_ts is not None
            self.observed_notification_ts = item.message_ts
        self._handling_notification = is_target_notification
        try:
            accepted = self._original_apply_delivery(generation, item)
        finally:
            self._handling_notification = False
        return accepted

    def observe_navigation(self, future: Future[NavigationSnapshot]) -> None:
        is_target = future is self._target_refresh
        self._applying_target_navigation = is_target
        try:
            self._original_apply_navigation(future)
        finally:
            self._applying_target_navigation = False
        if is_target:
            self.notification_refresh_succeeded = (
                not future.cancelled() and future.exception() is None
            )
            completed = self.notification_refresh_applied
            assert completed is not None
            if future.cancelled():
                completed.cancel(completed.key)
            elif (error := future.exception()) is not None:
                completed.fail(completed.key, error)

    def observe_after_refresh(
        self, callback: Callable[..., Any], *args: Any, **kwargs: Any
    ) -> bool:
        if (
            self._applying_target_navigation
            and callback == self._app._apply_viewport_effect
        ):
            assert self._target_effect is None, "extra notification viewport effect"
            effect = args[0]
            assert isinstance(effect, ViewportEffect)
            assert effect.kind is ViewportEffectKind.RESTORE
            self._target_effect = effect
        return self._original_after_refresh(callback, *args, **kwargs)

    def observe_effect(
        self, effect: ViewportEffect, messages: tuple[Message, ...]
    ) -> None:
        is_target = effect is self._target_effect
        accepted = (
            not self._app._shutting_down
            and self._app.visual_state.viewport.accepts(effect)
        )
        self._original_apply_effect(effect, messages)
        if is_target:
            completed = self.notification_refresh_applied
            assert completed is not None
            if not accepted:
                completed.supersede(completed.key)
            else:
                assert any(message.ts == effect.message_id for message in messages)
                # Accepted RESTORE delegates to immediate=True scroll_to. Its
                # actual return is this exact effect's applied boundary.
                completed.succeed(completed.key, effect)

    def observe_refresh_navigation(self) -> Future[NavigationSnapshot]:
        refresh = self.original_refresh_navigation
        assert refresh is not None
        future = refresh()
        if self._handling_notification:
            self._target_refresh = future
            self.notification_refresh_applied = self.scope.expect(
                CompletionKey(self._app, "notification.restore_applied", future)
            )
            self.notification_requested.succeed(
                self.notification_requested.key, self.notification_refresh_applied
            )
        return future


def _seed(db_path: Path) -> tuple[TautClient, TautClient]:
    TautClient.init(db_path=db_path)
    alice = TautClient(db_path=db_path, as_name="alice")
    bob = TautClient(db_path=db_path, as_name="bob")
    for client in (alice, bob):
        client.join("general")
        client.join("quiet")
    return alice, bob


def test_navigation_uses_public_joined_channels_and_actor_scoped_dms(
    tmp_path: Path,
) -> None:
    from taut_tui.session import TuiSession

    db_path = tmp_path / "chat.db"
    alice, bob = _seed(db_path)
    alice.say("@bob", "hello")
    session = TuiSession(db_path=str(db_path), as_name="alice", continuity_token=None)
    try:
        navigation = session.refresh_navigation().result(timeout=5)
    finally:
        session.close()
        alice.close()
        bob.close()

    assert [thread.name for thread in navigation.channels] == ["general", "quiet"]
    assert len(navigation.direct_messages) == 1
    assert navigation.direct_messages[0].display_name == "DM with bob"
    assert navigation.direct_messages[0].name != "DM with bob"


def test_only_active_conversation_advances_while_inactive_stays_unread(
    tmp_path: Path,
) -> None:
    from taut_tui.session import TuiSession

    db_path = tmp_path / "chat.db"
    alice, bob = _seed(db_path)
    deliveries: list[Message | Notification] = []
    committed: list[ConversationSnapshot] = []
    lock = Lock()

    def commit(snapshot: ConversationSnapshot) -> bool:
        with lock:
            committed.append(snapshot)
        return True

    def accept(_generation: int, item: Message | Notification) -> bool:
        with lock:
            deliveries.append(item)
        return True

    observed = SessionDeliveries(accept)
    session = TuiSession(
        db_path=str(db_path),
        as_name="alice",
        continuity_token=None,
        commit_conversation=commit,
        accept_delivery=observed.accept,
    )
    observed.bind(session)
    try:
        opened = session.open_conversation("general").result(timeout=5)
        assert opened is not None
        deadline = observed.scope.now() + 5
        active_message = bob.say("general", "active")
        quiet_message = bob.say("quiet", "inactive")
        delivered = observed.wait(opened.generation, active_message, deadline=deadline)
        assert delivered.ts == active_message.ts and delivered.text == "active"
        navigation = session.refresh_navigation().result(timeout=5)
    finally:
        session.close()
        observed.close()
        alice.close()
        bob.close()

    assert committed[-1].target == "general"
    assert not any(
        isinstance(item, Message) and item.ts == quiet_message.ts for item in deliveries
    )
    quiet = next(item for item in navigation.channels if item.name == "quiet")
    assert quiet.unread is True
    assert quiet.unread_count >= 1


def test_latest_switch_wins_and_stops_old_watcher_before_replacement(
    tmp_path: Path,
) -> None:
    from taut_tui.session import TuiSession

    db_path = tmp_path / "chat.db"
    alice, bob = _seed(db_path)
    commits: list[ConversationSnapshot] = []
    deliveries: list[Message | Notification] = []

    def commit(snapshot: ConversationSnapshot) -> bool:
        commits.append(snapshot)
        return True

    def accept(_generation: int, item: Message | Notification) -> bool:
        deliveries.append(item)
        return True

    observed = SessionDeliveries(accept)
    session = TuiSession(
        db_path=str(db_path),
        as_name="alice",
        continuity_token=None,
        commit_conversation=commit,
        accept_delivery=observed.accept,
    )
    observed.bind(session)
    try:
        first = session.open_conversation("general")
        second = session.open_conversation("quiet")
        first.result(timeout=5)
        opened = second.result(timeout=5)
        assert opened is not None
        general_message = bob.say("general", "old inactive")
        deadline = observed.scope.now() + 5
        active_message = bob.say("quiet", "new active")
        delivered = observed.wait(opened.generation, active_message, deadline=deadline)
        assert delivered.ts == active_message.ts and delivered.text == "new active"
    finally:
        session.close()
        observed.close()
        alice.close()
        bob.close()

    assert commits[-1].target == "quiet"
    assert not any(
        isinstance(item, Message) and item.ts == general_message.ts
        for item in deliveries
    )


def test_repeated_target_switches_retire_broker_worker_cores(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from taut_tui.session import TuiSession

    db_path = tmp_path / "chat.db"
    alice, bob = _seed(db_path)
    alice.join("quiet")
    bob.join("quiet")
    anchor = TautClient(db_path=db_path, as_name="alice", persistent=True)
    anchor._meta_queue.has_pending()
    assert anchor._meta_queue.conn is not None
    process_session = anchor._meta_queue.conn._shared_session
    assert process_session is not None
    baseline_cores = len(process_session._cores)
    session = TuiSession(
        db_path=str(db_path),
        as_name="alice",
        continuity_token=None,
    )
    original_watch = TautClient.watch
    scope = CompletionScope()
    readiness: dict[object, tuple[InitialDrainEvent, list[float]]] = {}

    def watch(client: TautClient, *args: object, **kwargs: object) -> object:
        watcher = original_watch(client, *args, **kwargs)  # type: ignore[arg-type]
        if client is session._client:
            assert len(readiness) < 3, "unexpected extra watcher"
            ready = InitialDrainEvent(scope, watcher)
            watcher.notify_ready_after_initial_drain(ready)
            started: list[float] = []
            original_start = watcher.start

            def start() -> object:
                assert not started, "watcher started more than once"
                started.append(time.monotonic())
                return original_start()

            monkeypatch.setattr(watcher, "start", start)
            readiness[watcher] = (ready, started)
        return watcher

    monkeypatch.setattr(TautClient, "watch", watch)
    try:
        for target in ("general", "quiet", "general"):
            session.open_conversation(target).result(timeout=5)
            assert session._watcher is not None
            watcher, _thread = session._watcher
            ready, started = readiness[watcher]
            assert len(started) == 1
            ready.completion.wait_sync(
                deadline=started[0] + 5, description="watcher initial drain"
            )
            assert baseline_cores < len(process_session._cores) <= baseline_cores + 2
    finally:
        session.close()
        scope.close()
        scope.raise_if_invalid()

    assert len(process_session._cores) == baseline_cores
    anchor_queue = anchor.queue("tui.anchor.probe")
    anchor_queue.write("anchor survives switches")
    assert anchor_queue.read() == "anchor survives switches"
    anchor.close()
    alice.close()
    bob.close()


@pytest.mark.parametrize("published_at", (4.0, 6.0))
def test_initial_drain_deadline_uses_publication_not_waiter_wakeup(
    published_at: float,
) -> None:
    clock = [0.0]
    with CompletionScope(clock=lambda: clock[0]) as scope:
        watcher = object()
        ready = InitialDrainEvent(scope, watcher)
        assert ready.completion.key.owner is watcher
        clock[0] = published_at
        ready.set()
        assert ready.is_set()
        clock[0] = 8.0
        if published_at > 5.0:
            with pytest.raises(CompletionTimeout, match="initial_drain"):
                ready.completion.wait_sync(deadline=5, description="initial drain")
        else:
            ready.completion.wait_sync(deadline=5, description="initial drain")


def test_shutdown_rejection_does_not_acknowledge_chat_message(tmp_path: Path) -> None:
    from taut_tui.session import TuiSession

    db_path = tmp_path / "chat.db"
    alice, bob = _seed(db_path)
    rejected = Event()

    def reject(_generation: int, _item: Message | Notification) -> bool:
        rejected.set()
        return False

    session = TuiSession(
        db_path=str(db_path),
        as_name="alice",
        continuity_token=None,
        accept_delivery=reject,
    )
    try:
        session.open_conversation("general").result(timeout=5)
        sent = bob.say("general", "must replay")
        assert rejected.wait(5)
    finally:
        session.close()

    replay = alice.read_unread("general")
    alice.close()
    bob.close()

    assert any(message.ts == sent.ts for message in replay)


def test_current_delivery_rejection_reports_visible_degradation_owner_event(
    tmp_path: Path,
) -> None:
    from taut_tui.session import TuiSession

    db_path = tmp_path / "degraded.db"
    alice, bob = _seed(db_path)
    degraded: list[tuple[int, str]] = []
    reported = Event()

    def reject(_generation: int, _item: Message | Notification) -> bool:
        return False

    def report(generation: int, detail: str) -> None:
        degraded.append((generation, detail))
        reported.set()

    session = TuiSession(
        db_path=str(db_path),
        as_name="alice",
        continuity_token=None,
        accept_delivery=reject,
        report_watcher_degraded=report,
    )
    try:
        session.open_conversation("general").result(timeout=5)
        bob.say("general", "reject and degrade")
        assert reported.wait(5)
        assert degraded == [(1, "watcher exited unexpectedly")]
    finally:
        session.close()
        alice.close()
        bob.close()


def test_close_attempts_client_cleanup_when_watcher_stop_times_out() -> None:
    from taut_tui.session import TuiSession, WatcherStopTimeout

    class StuckThread:
        def is_alive(self) -> bool:
            return True

    class StuckWatcher:
        def request_stop(self) -> None:
            return None

        def stop(self, *, join: bool, timeout: float | None = None) -> None:
            del join, timeout

    class ClosingClient:
        def __init__(self) -> None:
            self.closed = False

        def close(self) -> None:
            self.closed = True

    session = TuiSession(db_path=None, as_name=None, continuity_token=None)
    client = ClosingClient()
    session._watcher = (StuckWatcher(), StuckThread())  # type: ignore[assignment]
    session._client = client  # type: ignore[assignment]

    with pytest.raises(WatcherStopTimeout):
        session.close()

    assert client.closed is True


def test_broker_session_timeout_closes_client_but_watcher_queue_survives(
    tmp_path: Path,
) -> None:
    from taut_tui.session import TuiSession, WatcherStopTimeout

    db_path = tmp_path / "chat.db"
    TautClient.init(db_path=db_path)
    client = TautClient(db_path=db_path, as_name="alice", persistent=True)
    client.join("general")
    watcher = client.watch(lambda _item: None, threads=["general"])
    watcher_queue = watcher.get_queue("general")
    assert isinstance(watcher_queue, Queue)

    class StuckThread:
        def is_alive(self) -> bool:
            return True

    class SurvivingWatcher:
        def request_stop(self) -> None:
            return None

        def stop(self, *, join: bool, timeout: float | None = None) -> None:
            del join, timeout

    session = TuiSession(db_path=None, as_name=None, continuity_token=None)
    session._client = client
    session._watcher = (SurvivingWatcher(), StuckThread())  # type: ignore[assignment]

    with pytest.raises(WatcherStopTimeout):
        session.close()

    assert client._session is None
    watcher_queue.write("survives client cleanup")
    pending = list(watcher_queue.peek(all_messages=True) or ())
    assert "survives client cleanup" in pending
    watcher.stop(join=False)


def test_explicit_reply_open_commits_claimed_history_and_watches_both_surfaces(
    tmp_path: Path,
) -> None:
    from taut_tui.session import TuiSession

    db_path = tmp_path / "chat.db"
    alice, bob = _seed(db_path)
    origin = alice.say("general", "root")
    first_reply = bob.reply("general", str(origin.ts), "first reply")
    commits: list[ConversationSnapshot] = []
    deliveries: list[Message | Notification] = []

    def commit(snapshot: ConversationSnapshot) -> bool:
        commits.append(snapshot)
        return True

    def accept(_generation: int, item: Message | Notification) -> bool:
        deliveries.append(item)
        return True

    observed = SessionDeliveries(accept)
    session = TuiSession(
        db_path=str(db_path),
        as_name="alice",
        continuity_token=None,
        commit_conversation=commit,
        accept_delivery=observed.accept,
    )
    observed.bind(session)
    try:
        snapshot = session.open_conversation(
            "general",
            reply_thread=first_reply.thread,
        ).result(timeout=5)
        assert snapshot is not None
        assert any(message.ts == first_reply.ts for message in snapshot.reply_messages)

        deadline = observed.scope.now() + 5
        parent_live = bob.say("general", "parent live")
        reply_live = bob.reply("general", str(origin.ts), "reply live")
        for message in (parent_live, reply_live):
            delivered = observed.wait(snapshot.generation, message, deadline=deadline)
            assert (delivered.thread, delivered.ts) == (message.thread, message.ts)

        closed = session.open_conversation("general").result(timeout=5)
        assert closed is not None
        assert closed.reply_thread is None
        assert session._watcher is not None
        assert session._watcher[0]._thread_filter == {"general"}
        later_reply = bob.reply("general", str(origin.ts), "inactive reply")
    finally:
        session.close()
        observed.close()

    replay = alice.read_unread(first_reply.thread)
    alice.close()
    bob.close()

    assert commits[0].reply_thread == first_reply.thread
    assert any(message.ts == later_reply.ts for message in replay)


def test_transcript_decodes_literal_escapes_toward_sender_intent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """[TUI-5.3] a stored literal backslash-n body renders as a line break."""

    import asyncio

    from taut_tui.app import TautApp
    from taut_tui.widgets import TautOptionList

    db_path = tmp_path / "workspace.db"
    alice, bob = _seed(db_path)
    try:
        bob.say("general", "first paragraph.\\n\\nsecond paragraph.")
        bob.say("general", "real newline:\nkept as-is")

        async def exercise() -> None:
            app = TautApp(db_path=str(db_path), as_name="alice", continuity_token=None)
            async with app.run_test(size=(130, 34)) as pilot:

                async def forbidden_pause(*_args: object, **_kwargs: object) -> None:
                    raise AssertionError("chat wait must not drive the pilot")

                monkeypatch.setattr(pilot, "pause", forbidden_pause)
                await observed(app).navigation()
                navigation = app.query_one("#navigation-list", TautOptionList)
                index = next(
                    i
                    for i, target in enumerate(app._navigation_targets)
                    if target == "general"
                )
                navigation.highlighted = index
                opening = observed(app).opening()
                navigation.action_select()
                await observed(app).conversation(opening)
                transcript = app.query_one("#transcript", TautOptionList)
                prompts = [
                    str(transcript.get_option_at_index(i).prompt)
                    for i in range(transcript.option_count)
                ]
                decoded = next(p for p in prompts if "first paragraph." in p)
                assert "first paragraph.\n\nsecond paragraph." in decoded
                assert "\\n" not in decoded
                real = next(p for p in prompts if "real newline:" in p)
                assert "real newline:\nkept as-is" in real

        asyncio.run(exercise())
    finally:
        alice.close()
        bob.close()


def test_notification_refresh_keeps_scrolled_transcript_position(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """[TUI-6.2]: a nav refresh must not yank a scrolled-up transcript."""

    import asyncio

    from taut_tui.widgets import TautOptionList

    db_path = tmp_path / "scroll.db"
    alice, bob = _seed(db_path)
    last_history = None
    for ts in range(40):
        last_history = bob.say("general", f"history row {ts}")
    assert last_history is not None
    seeded_history = alice.read("general", limit=1000)
    assert seeded_history[-1].ts == last_history.ts

    async def exercise() -> None:
        app = TautApp(db_path=str(db_path), as_name="alice", continuity_token=None)
        probe = _NotificationRefreshProbe(
            app,
            last_history_ts=last_history.ts,
        )
        monkeypatch.setattr(app, "_apply_delivery", probe.observe_delivery)
        monkeypatch.setattr(
            app,
            "_apply_optional_conversation",
            probe.observe_open_conversation,
        )
        monkeypatch.setattr(
            app,
            "_apply_viewport_effect",
            probe.observe_effect,
        )
        monkeypatch.setattr(
            app,
            "call_after_refresh",
            probe.observe_after_refresh,
        )
        monkeypatch.setattr(
            app,
            "_apply_navigation_result",
            probe.observe_navigation,
        )
        async with app.run_test(size=(130, 34)):
            await observed(app).navigation()
            navigation = app.query_one("#navigation-list", TautOptionList)
            index = next(
                i for i, t in enumerate(app._navigation_targets) if t == "general"
            )
            navigation.highlighted = index
            opening = observed(app).opening()
            history_deadline = probe.scope.now() + 5
            navigation.action_select()
            await observed(app).conversation(opening)
            transcript = app.query_one("#transcript", TautOptionList)
            assert probe.history_caught_up is not None
            await probe.history_caught_up.wait(
                deadline=history_deadline, description="history scroll applied"
            )
            # Put the widget at the settled position, then cross the same
            # explicit user-ownership seam used by wheel, keys, and scrollbar.
            scroll_applied = probe.scope.expect(
                CompletionKey(transcript, "test.user_scroll_applied", request=object())
            )

            def scrolled() -> None:
                scroll_applied.succeed(scroll_applied.key, None)

            deadline = probe.scope.now() + 5
            transcript.scroll_to(
                y=0,
                animate=False,
                force=True,
                on_complete=scrolled,
                immediate=True,
            )
            await scroll_applied.wait(
                deadline=deadline, description="user scroll applied"
            )
            app._capture_settled_transcript_viewport()
            top_offset = int(transcript.scroll_offset.y)
            assert not transcript.is_vertical_scroll_end, {
                "max_scroll_y": transcript.max_scroll_y,
                "offset": transcript.scroll_offset,
                "options": transcript.option_count,
                "region": transcript.scrollable_content_region,
                "virtual_size": transcript.virtual_size,
            }
            # A mention in another thread claims a notification pointer and
            # triggers a navigation refresh without a #general delivery.
            session = app._session
            assert session is not None
            probe.original_refresh_navigation = session.refresh_navigation
            monkeypatch.setattr(
                session,
                "refresh_navigation",
                probe.observe_refresh_navigation,
            )
            probe.notification_armed = True
            deadline = probe.scope.now() + 5
            ping = bob.say("quiet", "@alice ping")
            # The exact refresh Future is captured by the delivery callback.
            # Await its retained request handoff before reading the bound phase.
            restored = await probe.notification_requested.wait(
                deadline=deadline, description="notification refresh requested"
            )
            await restored.wait(
                deadline=deadline, description="notification viewport restored"
            )
            assert probe.observed_notification_ts == ping.ts
            assert probe.notification_refresh_succeeded is True
            assert int(transcript.scroll_offset.y) == top_offset
            assert not transcript.is_vertical_scroll_end

    try:
        asyncio.run(exercise())
    finally:
        alice.close()
        bob.close()


def test_notification_refresh_observer_rejects_a_newer_unrelated_restore(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_navigation = _NotificationRefreshProbe.observe_navigation
    superseded_generations: list[tuple[int, int]] = []

    def apply_then_supersede(
        probe: _NotificationRefreshProbe, future: Future[NavigationSnapshot]
    ) -> None:
        original_navigation(probe, future)
        if future is probe._target_refresh:
            app = probe._app
            target_generation = app.visual_state.viewport.generation
            # Real rendering queues another real restore before either callback
            # runs. The target Future's effect now lacks viewport authority.
            app._render_messages(app._message_rows)
            superseded_generations.append(
                (target_generation, app.visual_state.viewport.generation)
            )

    monkeypatch.setattr(
        _NotificationRefreshProbe, "observe_navigation", apply_then_supersede
    )
    with pytest.raises(CompletionSuperseded, match="notification.restore_applied"):
        test_notification_refresh_keeps_scrolled_transcript_position(
            tmp_path, monkeypatch
        )
    assert len(superseded_generations) == 1
    old, newer = superseded_generations[0]
    assert newer > old
