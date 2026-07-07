"""Textual Pilot tests for the Taut TUI app.

Spec: docs/specs/04-taut-tui.md [TUI-6], [TUI-10.8].
Plan: docs/plans/2026-07-02-taut-tui-implementation-plan.md Task 3.

Anti-mock: every test runs the real App against a real .taut.db seeded
through TautClient. Assertions are structural (roles, classes, text
substrings), never glyphs/colors ([TUI-6.3]; testing-patterns Pattern 5).
"""

from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from taut._exceptions import EmptyResultError
from taut.client import Message, Notification, TautClient, Thread

textual = pytest.importorskip("textual")

from textual.widgets import Input  # noqa: E402

from taut.tui._bridge import ShutdownNonAck, WatchBridge  # noqa: E402
from taut.tui.app import TautApp  # noqa: E402
from taut.tui.widgets import NavRow, NavSection, TextStatic  # noqa: E402

if TYPE_CHECKING:
    from textual.pilot import Pilot

pytestmark = [pytest.mark.sqlite_only, pytest.mark.usefixtures("clean_env")]


def seed_project(tmp_path: Path) -> Path:
    """A real project: two channels, a DM, read and unread history."""

    db = tmp_path / ".taut.db"
    TautClient.init(db_path=db)
    van = TautClient(db_path=db, as_name="van")
    van.join("general")
    van.join("ops")
    claude = TautClient(db_path=db, as_name="claude")
    claude.join("general")
    claude.say("general", "hello from claude")
    claude.say("@van", "dm ping")
    return db


def run_app(
    db: Path,
    scenario: Callable[[TautApp, Pilot[int]], Awaitable[None]],
    *,
    as_name: str = "van",
) -> None:
    """Drive the real app under Textual's Pilot on a virtual terminal."""

    async def _run() -> None:
        app = TautApp(db_path=str(db), as_name=as_name, token=None)
        async with app.run_test(size=(120, 34)) as pilot:
            await pilot.pause()
            await scenario(app, pilot)

    asyncio.run(_run())


class TestWideLayout:
    def test_nav_sections_list_joined_threads(self, tmp_path: Path) -> None:
        db = seed_project(tmp_path)

        async def scenario(app: TautApp, pilot: Pilot[int]) -> None:
            nav = app.query_one("#navigation")
            labels = [row.target for row in nav.query(NavRow)]
            assert "general" in labels
            assert "ops" in labels
            assert any(str(t).startswith("dm.") for t in labels if t)
            assert "inbox" in labels
            sections = [s.renderable_text for s in nav.query(NavSection)]
            assert sections == ["Channels", "Direct", "Inbox"]

        run_app(db, scenario)

    def test_select_channel_updates_transcript_and_composer(
        self, tmp_path: Path
    ) -> None:
        db = seed_project(tmp_path)

        async def scenario(app: TautApp, pilot: Pilot[int]) -> None:
            app.select_target("general")
            await pilot.pause()
            transcript = app.query_one("#transcript")
            texts = [
                row.renderable_text
                for row in transcript.query(TextStatic).filter(".message")
            ]
            assert any("hello from claude" in text for text in texts)
            assert any("claude" in text for text in texts)
            composer_label = app.query_one(
                "#composer-label", TextStatic
            ).renderable_text
            assert "general" in composer_label

            app.select_target("ops")
            await pilot.pause()
            transcript = app.query_one("#transcript")
            texts = [
                row.renderable_text
                for row in transcript.query(TextStatic).filter(".message")
            ]
            assert not any("hello from claude" in text for text in texts)
            assert "ops" in app.query_one("#composer-label", TextStatic).renderable_text

        run_app(db, scenario)

    def test_notice_and_message_are_distinct_roles(self, tmp_path: Path) -> None:
        db = seed_project(tmp_path)

        async def scenario(app: TautApp, pilot: Pilot[int]) -> None:
            app.select_target("general")
            await pilot.pause()
            transcript = app.query_one("#transcript")
            notices = [
                row.renderable_text
                for row in transcript.query(TextStatic).filter(".notice")
            ]
            messages = [
                row.renderable_text
                for row in transcript.query(TextStatic).filter(".message")
            ]
            # join/create notices render as notices, chat as messages.
            assert any("joined" in text or "created" in text for text in notices)
            assert any("hello from claude" in text for text in messages)

        run_app(db, scenario)

    def test_presence_pane_lists_members_as_text(self, tmp_path: Path) -> None:
        db = seed_project(tmp_path)

        async def scenario(app: TautApp, pilot: Pilot[int]) -> None:
            app.select_target("general")
            await pilot.pause()
            presence = app.query_one("#presence")
            rows = [
                row.renderable_text
                for row in presence.query(TextStatic).filter(".member-row")
            ]
            joined = " ".join(rows)
            assert "van" in joined
            assert "claude" in joined
            # Presence must be text, not color-only ([TUI-8.4]).
            assert "here" in joined or "away" in joined
            you = app.query_one("#presence-you", TextStatic).renderable_text
            assert "van" in you

        run_app(db, scenario)

    def test_dm_row_renders_from_members_not_who_thread(self, tmp_path: Path) -> None:
        # If the implementation wrongly calls client.who(dm_name), mount
        # raises ThreadNameError and this test fails (finding R4-2).
        db = seed_project(tmp_path)

        async def scenario(app: TautApp, pilot: Pilot[int]) -> None:
            nav = app.query_one("#navigation")
            dm_rows = [
                row
                for row in nav.query(NavRow)
                if row.target and str(row.target).startswith("dm.")
            ]
            assert len(dm_rows) == 1
            label = dm_rows[0].renderable_text
            assert "claude" in label
            assert "here" in label or "away" in label

        run_app(db, scenario)

    def test_title_bar_names_project(self, tmp_path: Path) -> None:
        db = seed_project(tmp_path)

        async def scenario(app: TautApp, pilot: Pilot[int]) -> None:
            title = app.query_one("#titlebar", TextStatic).renderable_text
            assert "taut" in title
            assert tmp_path.name in title

        run_app(db, scenario)


class TestUnreadSeparator:
    def test_separator_anchored_at_mount_snapshot(self, tmp_path: Path) -> None:
        db = tmp_path / ".taut.db"
        TautClient.init(db_path=db)
        van = TautClient(db_path=db, as_name="van")
        van.join("general")
        claude = TautClient(db_path=db, as_name="claude")
        claude.join("general")
        claude.say("general", "old-read-message")
        van.read("general")  # advances van's cursor past the first message
        claude.say("general", "new-unread-one")
        claude.say("general", "new-unread-two")

        async def scenario(app: TautApp, pilot: Pilot[int]) -> None:
            app.select_target("general")
            await pilot.pause()
            transcript = app.query_one("#transcript")
            rows = list(transcript.query(TextStatic).filter(".transcript-row"))
            kinds = [
                "separator" if row.has_class("separator") else row.renderable_text
                for row in rows
            ]
            sep_index = kinds.index("separator")
            before = " ".join(str(k) for k in kinds[:sep_index])
            after = " ".join(str(k) for k in kinds[sep_index + 1 :])
            assert "old-read-message" in before
            assert "new-unread-one" in after
            assert "new-unread-two" in after

        run_app(db, scenario)

    def test_no_separator_when_everything_read(self, tmp_path: Path) -> None:
        db = tmp_path / ".taut.db"
        TautClient.init(db_path=db)
        van = TautClient(db_path=db, as_name="van")
        van.join("general")
        van.say("general", "just mine")

        async def scenario(app: TautApp, pilot: Pilot[int]) -> None:
            app.select_target("general")
            await pilot.pause()
            transcript = app.query_one("#transcript")
            assert not list(transcript.query(TextStatic).filter(".separator"))

        run_app(db, scenario)


async def wait_until(
    pilot: Pilot[int],
    predicate: Callable[[], bool],
    *,
    timeout: float = 10.0,
) -> None:
    """Bounded polling (testing-patterns Pattern 4): never a single read."""

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        await pilot.pause()
        if predicate():
            return
        await asyncio.sleep(0.05)
    raise AssertionError("condition not met within the bounded poll")


class TestLiveUpdates:
    """Task 4: real TautWatcher-backed live updates ([TUI-12])."""

    def test_live_message_appears_exactly_once(self, tmp_path: Path) -> None:
        db = seed_project(tmp_path)

        async def scenario(app: TautApp, pilot: Pilot[int]) -> None:
            app.select_target("general")
            await pilot.pause()
            transcript = app.query_one("#transcript")

            def count() -> int:
                return sum(
                    "live-tail-1" in row.renderable_text
                    for row in transcript.query(TextStatic).filter(".message")
                )

            claude = TautClient(db_path=db, as_name="claude")
            claude.say("general", "live-tail-1")
            await wait_until(pilot, lambda: count() >= 1)
            await asyncio.sleep(0.3)
            await pilot.pause()
            assert count() == 1

        run_app(db, scenario)

    def test_backlog_overlap_renders_once(self, tmp_path: Path) -> None:
        # The watcher seeds cursors from stored last_seen_ts, so an unread
        # backlog message arrives via BOTH the history backfill and the
        # initial drain; the transcript renders it once (finding 3).
        db = tmp_path / ".taut.db"
        TautClient.init(db_path=db)
        van = TautClient(db_path=db, as_name="van")
        van.join("general")
        claude = TautClient(db_path=db, as_name="claude")
        claude.join("general")
        claude.say("general", "overlap-msg")  # unread for van at mount

        async def scenario(app: TautApp, pilot: Pilot[int]) -> None:
            app.select_target("general")
            transcript = app.query_one("#transcript")

            def count() -> int:
                return sum(
                    "overlap-msg" in row.renderable_text
                    for row in transcript.query(TextStatic).filter(".message")
                )

            await wait_until(pilot, lambda: count() >= 1)
            await asyncio.sleep(0.3)
            await pilot.pause()
            assert count() == 1

        run_app(db, scenario)

    def test_nav_badge_increments_for_background_channel(self, tmp_path: Path) -> None:
        db = tmp_path / ".taut.db"
        TautClient.init(db_path=db)
        van = TautClient(db_path=db, as_name="van")
        van.join("general")
        van.join("ops")
        claude = TautClient(db_path=db, as_name="claude")
        claude.join("ops")
        van.read()  # start the session with everything read

        async def scenario(app: TautApp, pilot: Pilot[int]) -> None:
            app.select_target("general")
            await pilot.pause()
            nav = app.query_one("#navigation")

            def ops_badge() -> bool:
                return any(
                    row.target == "ops" and row.renderable_text.rstrip().endswith("1")
                    for row in nav.query(NavRow)
                )

            claude.say("ops", "background-live")
            await wait_until(pilot, ops_badge)

        run_app(db, scenario)

    def test_watcher_thread_stopped_after_exit(self, tmp_path: Path) -> None:
        db = seed_project(tmp_path)
        captured: list[threading.Thread] = []

        async def scenario(app: TautApp, pilot: Pilot[int]) -> None:
            assert app._bridge is not None
            thread = app._bridge.thread
            assert thread is not None and thread.is_alive()
            captured.append(thread)

        run_app(db, scenario)
        # run_test teardown runs on_unmount -> bridge.stop(join) (finding 5).
        assert captured and not captured[0].is_alive()

    def test_one_shot_display_failure_redelivers(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # At-least-once for chat messages (findings 4 + R3-9): the primary
        # assertion is RE-DELIVERY — the message ends up displayed exactly
        # once after a one-shot UI failure, never silently dropped.
        db = seed_project(tmp_path)
        original = TautApp._apply_watch_item
        state = {"failed": False}

        async def flaky(self: TautApp, item: object) -> None:
            from taut.client import Message as _Message

            if (
                isinstance(item, _Message)
                and "flaky-once" in item.text
                and not state["failed"]
            ):
                state["failed"] = True
                raise RuntimeError("injected one-shot UI failure")
            await original(self, item)  # type: ignore[arg-type]

        monkeypatch.setattr(TautApp, "_apply_watch_item", flaky)

        async def scenario(app: TautApp, pilot: Pilot[int]) -> None:
            app.select_target("general")
            await pilot.pause()
            transcript = app.query_one("#transcript")

            def count() -> int:
                return sum(
                    "flaky-once" in row.renderable_text
                    for row in transcript.query(TextStatic).filter(".message")
                )

            claude = TautClient(db_path=db, as_name="claude")
            claude.say("general", "flaky-once")
            await wait_until(pilot, lambda: count() >= 1)
            assert state["failed"], "the injected failure never fired"
            await asyncio.sleep(0.3)
            await pilot.pause()
            assert count() == 1

        run_app(db, scenario)

    def test_watch_implies_seen_semantics_and_snapshot_separator(
        self, tmp_path: Path
    ) -> None:
        # The [TUI-10.8] firing test (finding R3-1): running the TUI
        # consumes stored unread for a channel the user never opens — the
        # decided contract, not an accident — while the mount snapshot
        # keeps the separator correct for a late-opened thread.
        db = tmp_path / ".taut.db"
        TautClient.init(db_path=db)
        van = TautClient(db_path=db, as_name="van")
        van.join("general")
        van.join("ops")
        claude = TautClient(db_path=db, as_name="claude")
        claude.join("ops")
        van.read()  # caught up before the backlog arrives
        backlog = claude.say("ops", "ops-backlog-unread")

        async def scenario(app: TautApp, pilot: Pilot[int]) -> None:
            app.select_target("general")
            # Wait until the initial drain acked the ops backlog (stored
            # cursor advanced past it) without the user ever opening ops.
            await wait_until(
                pilot,
                lambda: (van.read_cursor("ops") or 0) >= backlog.ts,
            )
            # Late-opened thread: the separator still anchors on the mount
            # snapshot even though the stored cursor already moved.
            app.select_target("ops")
            await pilot.pause()
            transcript = app.query_one("#transcript")
            rows = list(transcript.query(TextStatic).filter(".transcript-row"))
            labels = [
                "separator" if row.has_class("separator") else row.renderable_text
                for row in rows
            ]
            sep_index = labels.index("separator")
            after = " ".join(str(item) for item in labels[sep_index + 1 :])
            assert "ops-backlog-unread" in after

        run_app(db, scenario)
        # After a clean session: everything delivered is seen ([TUI-10.8]).
        fresh = TautClient(db_path=db, as_name="van")
        with pytest.raises(EmptyResultError, match="no unread threads"):
            fresh.list_threads()


class TestWatchBridge:
    """Bridge-level contract, no App required (plan Task 4)."""

    def _message(self, thread: str = "general") -> Message:
        return Message(
            thread=thread,
            ts=1_000_000_000_000_000_000,
            from_id="m_x",
            from_name="claude",
            kind="message",
            text="in flight",
        )

    def test_message_during_shutdown_raises_nonack(self, tmp_path: Path) -> None:
        db = seed_project(tmp_path)
        client = TautClient(db_path=db, as_name="van")
        delivered: list[object] = []
        bridge = WatchBridge(client=client, deliver=delivered.append)
        bridge.start()
        try:
            bridge.stop(timeout=5.0)
            delivered.clear()
            # A Message fetched in the shutdown window must not be acked:
            # the handler raises instead of returning (finding R2-1).
            with pytest.raises(ShutdownNonAck):
                bridge.handle(self._message())
            assert delivered == []
        finally:
            bridge.stop(timeout=5.0)

    def test_notification_failure_is_best_effort_history_durable(
        self, tmp_path: Path
    ) -> None:
        # Notifications are consumed on read; a display failure is logged,
        # never raised, and the source chat history stays readable — do
        # NOT expect the notification to be re-seen (finding R2-2).
        db = seed_project(tmp_path)
        client = TautClient(db_path=db, as_name="van")

        def deliver(item: object) -> None:
            raise RuntimeError("injected notification render failure")

        bridge = WatchBridge(client=client, deliver=deliver)
        notification = Notification(
            type="mention",
            to_id="m_x",
            actor_id="m_y",
            actor_name="claude",
            thread="general",
            message_ts=123,
        )
        bridge.handle(notification)  # must not raise
        assert [m.text for m in client.history("general")]


class TestSliceReviewHardening:
    """Task 4 per-slice review findings (Codex, 2026-07-03)."""

    def test_widget_failure_below_dedup_still_redelivers(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Slice-review finding 1: if the dedup key is registered BEFORE the
        # UI mutation succeeds, the retry after a widget failure is
        # swallowed as a duplicate and the cursor advances without display.
        # Inject the failure INSIDE the widget, below _apply_watch_item.
        from taut.tui.widgets import TranscriptView

        db = seed_project(tmp_path)
        original = TranscriptView.append_message
        state = {"failed": False}

        async def flaky(self: TranscriptView, message: Message) -> None:
            if "deep-flaky" in message.text and not state["failed"]:
                state["failed"] = True
                raise RuntimeError("injected widget failure")
            await original(self, message)

        monkeypatch.setattr(TranscriptView, "append_message", flaky)

        async def scenario(app: TautApp, pilot: Pilot[int]) -> None:
            app.select_target("general")
            await pilot.pause()
            transcript = app.query_one("#transcript")

            def count() -> int:
                return sum(
                    "deep-flaky" in row.renderable_text
                    for row in transcript.query(TextStatic).filter(".message")
                )

            claude = TautClient(db_path=db, as_name="claude")
            claude.say("general", "deep-flaky")
            await wait_until(pilot, lambda: count() >= 1)
            assert state["failed"]
            await asyncio.sleep(0.3)
            await pilot.pause()
            assert count() == 1

        run_app(db, scenario)

    def test_shutdown_inflight_failure_never_acks_real_watcher(
        self, tmp_path: Path
    ) -> None:
        # Slice-review finding 2: prove the shutdown contract through the
        # REAL watcher — an in-flight message whose hand-off fails during
        # stop is neither acked nor poison-advanced, and is re-seen by the
        # next session (findings R2-1 + R3-9).
        db = tmp_path / ".taut.db"
        TautClient.init(db_path=db)
        van = TautClient(db_path=db, as_name="van")
        van.join("general")
        claude = TautClient(db_path=db, as_name="claude")
        claude.join("general")
        van.read()

        entered = threading.Event()
        release = threading.Event()

        def deliver(item: Message | Notification) -> None:
            if isinstance(item, Message) and "in-flight" in item.text:
                entered.set()
                assert release.wait(timeout=10)
                raise RuntimeError("UI tearing down")

        bridge = WatchBridge(client=van, deliver=deliver)
        bridge.start()
        try:
            message = claude.say("general", "in-flight-shutdown")
            assert entered.wait(timeout=10), "message never reached the handler"
            stopper = threading.Thread(target=bridge.stop)
            stopper.start()
            time.sleep(0.2)  # let the stop event land while deliver blocks
            release.set()
            stopper.join(timeout=10)
            thread = bridge.thread
            assert thread is not None and not thread.is_alive()
            # Not acked, and only one failure — far from the 3-strikes
            # poison advance; the stop event prevented any refetch.
            assert (van.read_cursor("general") or 0) < message.ts
        finally:
            release.set()
            bridge.stop()

        # Next session re-sees the unacked message (at-least-once).
        redelivered: list[str] = []

        def record(item: Message | Notification) -> None:
            if isinstance(item, Message):
                redelivered.append(item.text)

        second = WatchBridge(client=van, deliver=record)
        second.start()
        try:
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                if any("in-flight-shutdown" in text for text in redelivered):
                    break
                time.sleep(0.05)
            assert any("in-flight-shutdown" in text for text in redelivered)
        finally:
            second.stop()

    def test_notification_claim_loss_through_real_watcher(self, tmp_path: Path) -> None:
        # Slice-review finding 3: the best-effort contract through the real
        # READ-mode claim — a failed render loses the notification (never
        # re-seen) while the source chat history stays durable (R2-2).
        db = tmp_path / ".taut.db"
        TautClient.init(db_path=db)
        van = TautClient(db_path=db, as_name="van")
        van.join("general")
        claude = TautClient(db_path=db, as_name="claude")
        claude.join("general")
        van.read()

        attempts: list[Notification] = []

        def deliver(item: Message | Notification) -> None:
            if isinstance(item, Notification):
                attempts.append(item)
                raise RuntimeError("injected notification render failure")

        bridge = WatchBridge(client=van, deliver=deliver)
        bridge.start()
        try:
            message = claude.say("general", "ping @van")
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline and not attempts:
                time.sleep(0.05)
            assert attempts, "mention notification never delivered"
            assert attempts[0].type == "mention"
        finally:
            bridge.stop()

        fresh = TautClient(db_path=db, as_name="van")
        # Source history is the durable record...
        assert message.text in [m.text for m in fresh.history("general")]
        # ...and the claimed notification is legitimately gone — do NOT
        # expect it to be re-seen.
        with pytest.raises(EmptyResultError, match="nothing pending"):
            fresh.inbox()


def seed_thread_project(tmp_path: Path) -> tuple[Path, int]:
    """A channel with one sub-thread: root by van, two replies by claude."""

    db = tmp_path / ".taut.db"
    TautClient.init(db_path=db)
    van = TautClient(db_path=db, as_name="van")
    van.join("general")
    claude = TautClient(db_path=db, as_name="claude")
    claude.join("general")
    root = van.say("general", "root-message")
    claude.reply("general", str(root.ts), "first-reply")
    claude.reply("general", str(root.ts), "second-reply")
    return db, root.ts


class TestInlineThreads:
    """[TUI-7.1]/[TUI-7.2]: inline sub-threads, display-only folding."""

    def test_inline_thread_renders_under_parent(self, tmp_path: Path) -> None:
        db, root_ts = seed_thread_project(tmp_path)

        async def scenario(app: TautApp, pilot: Pilot[int]) -> None:
            app.select_target("general")
            await pilot.pause()
            transcript = app.query_one("#transcript")
            stubs = list(transcript.query(TextStatic).filter(".thread-stub"))
            assert len(stubs) == 1
            assert f"general.{root_ts}" in stubs[0].renderable_text
            assert "2" in stubs[0].renderable_text  # reply count
            replies = [
                row.renderable_text
                for row in transcript.query(TextStatic).filter(".thread-reply")
            ]
            assert any("first-reply" in text for text in replies)
            assert any("second-reply" in text for text in replies)
            # The stub sits directly under its parent message (origin_ts).
            rows = [
                widget
                for widget in transcript.query(TextStatic)
                if widget.has_class("message") or widget.has_class("thread-stub")
            ]
            texts = [row.renderable_text for row in rows]
            root_index = next(
                i for i, text in enumerate(texts) if "root-message" in text
            )
            assert rows[root_index + 1].has_class("thread-stub")

        run_app(db, scenario)

    def test_fold_is_display_only(self, tmp_path: Path) -> None:
        db, root_ts = seed_thread_project(tmp_path)
        sub = f"general.{root_ts}"
        observer = TautClient(db_path=db, as_name="van")

        async def scenario(app: TautApp, pilot: Pilot[int]) -> None:
            app.select_target("general")
            await pilot.pause()
            joined_before = {t.name for t in observer.joined_threads()}

            await pilot.press("z")  # sole visible thread folds ([TUI-8.2])
            await pilot.pause()
            transcript = app.query_one("#transcript")
            assert not list(transcript.query(TextStatic).filter(".thread-reply"))
            stubs = list(transcript.query(TextStatic).filter(".thread-stub"))
            assert stubs and "2" in stubs[0].renderable_text

            await pilot.press("z")  # unfold restores the replies
            await pilot.pause()
            replies = list(transcript.query(TextStatic).filter(".thread-reply"))
            assert len(replies) == 2

            # Display-only ([TUI-7.2]): no membership or cursor movement.
            assert {t.name for t in observer.joined_threads()} == joined_before
            assert observer.read_cursor(sub) is None  # never joined it

        run_app(db, scenario)


class TestThreadPane:
    """[TUI-7.3]: right-side thread pane borrows the presence column."""

    def test_pane_opens_replies_and_closes(self, tmp_path: Path) -> None:
        db, root_ts = seed_thread_project(tmp_path)
        sub = f"general.{root_ts}"

        async def scenario(app: TautApp, pilot: Pilot[int]) -> None:
            app.select_target("general")
            await pilot.pause()

            await pilot.press("t")  # sole visible thread opens ([TUI-8.2])
            await pilot.pause()
            pane = app.query_one("#thread-pane")
            assert pane.display
            assert not app.query_one("#presence").display  # borrowed column
            label = app.query_one("#thread-pane-label", TextStatic).renderable_text
            assert sub in label and "reply" in label
            pane_texts = [
                row.renderable_text
                for row in pane.query(TextStatic).filter(".thread-reply")
            ]
            assert any("first-reply" in text for text in pane_texts)
            # Parent context is visible ([TUI-7.3]).
            parent = app.query_one("#thread-pane-parent", TextStatic).renderable_text
            assert "root-message" in parent
            # INV-9: no nested thread affordance inside the pane.
            assert not list(pane.query(TextStatic).filter(".thread-stub"))

            # The pane composer sends via reply(parent, origin, text): the
            # reply must land in the sub-thread (findings R3-5/R4-4 class).
            pane_input = app.query_one("#thread-pane-input")
            pane_input.focus()
            await pilot.pause()
            await pilot.press(*"from-pane")
            await pilot.press("enter")
            await pilot.pause()
            checker = TautClient(db_path=db, as_name="van")
            await wait_until(
                pilot,
                lambda: "from-pane" in [m.text for m in checker.history(sub)],
            )

            await pilot.press("escape")
            await pilot.pause()
            assert not app.query_one("#thread-pane").display
            assert app.query_one("#presence").display

        run_app(db, scenario)


class TestComposer:
    """[TUI-6.4]: sends go through the client; display via the watch path."""

    def test_composer_send_appears_via_watch_exactly_once(self, tmp_path: Path) -> None:
        db = seed_project(tmp_path)

        async def scenario(app: TautApp, pilot: Pilot[int]) -> None:
            app.select_target("general")
            await pilot.pause()
            await pilot.press("c")  # focus composer ([TUI-8.2])
            await pilot.press(*"sent-from-composer")
            await pilot.press("enter")
            transcript = app.query_one("#transcript")

            def count() -> int:
                return sum(
                    "sent-from-composer" in row.renderable_text
                    for row in transcript.query(TextStatic).filter(".message")
                )

            # INV-10: no optimistic append — the message arrives through
            # the watch path (which also proves the send succeeded).
            await wait_until(pilot, lambda: count() >= 1)
            await asyncio.sleep(0.3)
            await pilot.pause()
            assert count() == 1
            composer_input = app.query_one("#composer-input", Input)
            assert composer_input.value == ""

        run_app(db, scenario)

    def test_notification_warning_banner_send_still_succeeds(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # INV-12: an auxiliary notification-delivery warning surfaces as a
        # banner without downgrading the successful send. The send stays
        # real; only the warning is injected after it.
        db = seed_project(tmp_path)
        original_say = TautClient.say

        def say_with_warning(self: TautClient, target: str, text: str) -> Message:
            message = original_say(self, target, text)
            self.last_notification_warnings.append("injected delivery warning")
            return message

        monkeypatch.setattr(TautClient, "say", say_with_warning)

        async def scenario(app: TautApp, pilot: Pilot[int]) -> None:
            app.select_target("general")
            await pilot.pause()
            await pilot.press("c")
            await pilot.press(*"warned-send")
            await pilot.press("enter")
            transcript = app.query_one("#transcript")
            await wait_until(
                pilot,
                lambda: any(
                    "warned-send" in row.renderable_text
                    for row in transcript.query(TextStatic).filter(".message")
                ),
            )
            banner = app.query_one("#status-banner", TextStatic)
            assert banner.display
            assert "warning" in banner.renderable_text

        run_app(db, scenario)


class TestInbox:
    """[TUI-6.2]/[IAN-7]: the watch runtime is the sole consumer (R3-4)."""

    def test_inbox_shows_watch_claimed_mentions_exactly_once(
        self, tmp_path: Path
    ) -> None:
        db = tmp_path / ".taut.db"
        TautClient.init(db_path=db)
        van = TautClient(db_path=db, as_name="van")
        van.join("general")
        claude = TautClient(db_path=db, as_name="claude")
        claude.join("general")
        van.read()
        message = claude.say("general", "heads up @van")  # pending mention

        async def scenario(app: TautApp, pilot: Pilot[int]) -> None:
            # The initial drain claims and delivers the pending mention.
            await wait_until(pilot, lambda: len(app.session_notifications) >= 1)
            nav = app.query_one("#navigation")

            def inbox_row() -> str:
                for row in nav.query(NavRow):
                    if row.target == "inbox":
                        return row.renderable_text
                return ""

            assert inbox_row().rstrip().endswith("1")  # badge before open
            await pilot.press("i")
            await pilot.pause()
            inbox_view = app.query_one("#inbox-view")
            assert inbox_view.display
            assert not app.query_one("#transcript").display
            rows = [
                row.renderable_text
                for row in inbox_view.query(TextStatic).filter(".inbox-row")
            ]
            assert any("mention" in text and "claude" in text for text in rows)
            assert not inbox_row().rstrip().endswith("1")  # cleared on open
            await pilot.press("escape")
            await pilot.pause()
            assert app.query_one("#transcript").display
            assert not app.query_one("#inbox-view").display

        run_app(db, scenario)
        # Claimed exactly once by the watch runtime: nothing left to claim,
        # while the source chat history stays durable ([TAUT-10]).
        fresh = TautClient(db_path=db, as_name="van")
        with pytest.raises(EmptyResultError, match="nothing pending"):
            fresh.inbox()
        assert message.text in [m.text for m in fresh.history("general")]


class TestToggles:
    def test_members_toggle(self, tmp_path: Path) -> None:
        db = seed_project(tmp_path)

        async def scenario(app: TautApp, pilot: Pilot[int]) -> None:
            app.select_target("general")
            await pilot.pause()
            assert app.query_one("#presence").display
            await pilot.press("m")
            assert not app.query_one("#presence").display
            await pilot.press("m")
            assert app.query_one("#presence").display

        run_app(db, scenario)

    def test_search_filters_and_escape_restores(self, tmp_path: Path) -> None:
        db = seed_project(tmp_path)

        async def scenario(app: TautApp, pilot: Pilot[int]) -> None:
            app.select_target("general")
            await pilot.pause()
            await pilot.press("/")
            await pilot.pause()
            assert app.query_one("#search-input").display
            await pilot.press(*"hello")
            await pilot.pause()
            transcript = app.query_one("#transcript")
            visible = [
                row.renderable_text
                for row in transcript.query(TextStatic).filter(".message")
                if row.display
            ]
            assert any("hello from claude" in text for text in visible)
            # Non-matching rows (the join/create notices) are hidden.
            hidden_notices = [
                row
                for row in transcript.query(TextStatic).filter(".notice")
                if not row.display
            ]
            assert hidden_notices
            await pilot.press("escape")
            await pilot.pause()
            assert not app.query_one("#search-input").display
            all_rows = list(transcript.query(TextStatic).filter(".message"))
            assert all(row.display for row in all_rows)

        run_app(db, scenario)

    def test_goto_switches_target(self, tmp_path: Path) -> None:
        db = seed_project(tmp_path)

        async def scenario(app: TautApp, pilot: Pilot[int]) -> None:
            app.select_target("general")
            await pilot.pause()
            await pilot.press("g")
            await pilot.pause()
            assert app.query_one("#goto-input").display
            await pilot.press(*"ops")
            await pilot.press("enter")
            await pilot.pause()
            assert app.active_target == "ops"
            assert not app.query_one("#goto-input").display
            label = app.query_one("#composer-label", TextStatic).renderable_text
            assert "ops" in label

        run_app(db, scenario)

    def test_help_shows_full_commands_and_escape_keeps_target(
        self, tmp_path: Path
    ) -> None:
        db = seed_project(tmp_path)

        async def scenario(app: TautApp, pilot: Pilot[int]) -> None:
            app.select_target("general")
            await pilot.pause()
            before = app.active_target
            await pilot.press("?")
            await pilot.pause()
            overlay = app.query_one("#help-overlay", TextStatic)
            assert overlay.display
            text = overlay.renderable_text
            # Help exposes the full active command set ([TUI-8.2]), even
            # commands a narrow key bar would omit.
            for fragment in (
                "fold",
                "thread",
                "members",
                "search",
                "goto",
                "inbox",
                "help",
                "quit",
            ):
                assert fragment in text
            await pilot.press("escape")
            await pilot.pause()
            assert not app.query_one("#help-overlay", TextStatic).display
            assert app.active_target == before

        run_app(db, scenario)


class TestAccessibility:
    """[TUI-8.1]/[TUI-8.4]: keyboard-complete, deterministic focus."""

    def test_tab_cycles_focus_through_pane_order(self, tmp_path: Path) -> None:
        db = seed_project(tmp_path)

        async def scenario(app: TautApp, pilot: Pilot[int]) -> None:
            app.select_target("general")
            await pilot.pause()
            seen: list[str] = []
            start = app.focused
            assert start is not None  # exactly one focused pane, always
            for _ in range(8):
                await pilot.press("tab")
                focused = app.focused
                assert focused is not None
                identity = focused.id or type(focused).__name__
                if identity in seen and focused is start:
                    break
                seen.append(identity)
            # The cycle walks the pane model: navigation, transcript,
            # composer (and back) — deterministic order ([TUI-8.1]).
            assert "navigation" in seen
            assert "transcript" in seen
            assert "composer-input" in seen
            # Deterministic pane order: composer follows transcript.
            assert seen.index("composer-input") > seen.index("transcript")

        run_app(db, scenario)

    def test_composer_label_stays_visible_with_content(self, tmp_path: Path) -> None:
        db = seed_project(tmp_path)

        async def scenario(app: TautApp, pilot: Pilot[int]) -> None:
            app.select_target("general")
            await pilot.pause()
            await pilot.press("c")
            await pilot.press(*"draft text")
            await pilot.pause()
            label = app.query_one("#composer-label", TextStatic)
            assert label.display  # [TUI-8.4]: label visible with content
            assert "general" in label.renderable_text
            assert app.query_one("#composer-input", Input).value == "draft text"

        run_app(db, scenario)


class TestMarkupInjection:
    """Review F1: remote content is rendered literally, never as markup."""

    def test_markup_payload_renders_literally_without_crashing(
        self, tmp_path: Path
    ) -> None:
        # `[/]` is an unbalanced Rich close tag: with Static's default
        # markup=True it raises MarkupError at render and, because history
        # re-renders on launch, crash-loops the conversation. markup=False
        # shows it literally.
        db = tmp_path / ".taut.db"
        TautClient.init(db_path=db)
        van = TautClient(db_path=db, as_name="van")
        van.join("general")
        claude = TautClient(db_path=db, as_name="claude")
        claude.join("general")
        claude.say("general", "boom [/] and [bold]spoof[/] end")

        async def scenario(app: TautApp, pilot: Pilot[int]) -> None:
            app.select_target("general")
            await pilot.pause()
            transcript = app.query_one("#transcript")
            texts = [
                row.renderable_text
                for row in transcript.query(TextStatic).filter(".message")
            ]
            # Rendered at all (no crash) and verbatim (markup not interpreted).
            assert any("[/]" in t and "[bold]spoof[/]" in t for t in texts)
            assert app.is_running

        run_app(db, scenario)

    def test_sanitize_text_strips_control_chars_keeps_layout(self) -> None:
        from taut.tui.widgets._shared import sanitize_text

        # ESC (ANSI/OSC) and BEL dropped; newline/tab preserved for labels.
        assert sanitize_text("a\x1b[31mb\x07c") == "a[31mbc"
        assert sanitize_text("line1\nline2\tend") == "line1\nline2\tend"


class TestReviewFixes:
    """Regression coverage for the pre-PR review fixes (F3-F5)."""

    def test_own_message_does_not_badge_background_channel(
        self, tmp_path: Path
    ) -> None:
        # Review F3: the watcher echoes the user's own sends back; a send to a
        # background thread must not inflate its unread badge. Deterministic
        # check: one own + one other message land, the badge shows 1 not 2.
        db = tmp_path / ".taut.db"
        TautClient.init(db_path=db)
        van = TautClient(db_path=db, as_name="van")
        van.join("general")
        van.join("ops")
        claude = TautClient(db_path=db, as_name="claude")
        claude.join("ops")
        van.read()  # start with everything read

        async def scenario(app: TautApp, pilot: Pilot[int]) -> None:
            app.select_target("general")  # ops stays in the background
            await pilot.pause()
            nav = app.query_one("#navigation")

            def ops_label() -> str:
                for row in nav.query(NavRow):
                    if row.target == "ops":
                        return row.renderable_text.rstrip()
                return ""

            van_bg = TautClient(db_path=db, as_name="van")
            van_bg.say("ops", "my own note")  # own echo — must not badge
            claude.say("ops", "their note")  # other — badges once
            await wait_until(pilot, lambda: ops_label().endswith("1"))
            await asyncio.sleep(0.3)
            await pilot.pause()
            # Still 1: the own echo did not add a second unread.
            assert ops_label().endswith("1")

        run_app(db, scenario)

    def test_subthread_nav_row_shows_unread_badge(self) -> None:
        # Review F4: sub-thread rows dropped the unread suffix. Pure label
        # logic — no App runtime needed.
        app = TautApp()
        name = "general.123"
        app._threads = {
            name: Thread(
                name=name,
                parent="general",
                unread=True,
                last_ts=None,
                kind="subthread",
            )
        }
        app._unread_counts = {name: 3}
        assert app._row_label(name).rstrip().endswith("3")
        app._unread_counts[name] = 0
        assert app._row_label(name) == f"↳ {name}"

    def test_subthread_nav_rebuild_shows_unread_badge(self, tmp_path: Path) -> None:
        # The actual failure path was _rebuild_nav(), not _row_label().
        db = tmp_path / ".taut.db"
        TautClient.init(db_path=db)
        van = TautClient(db_path=db, as_name="van")
        van.join("general")
        root = van.say("general", "root")
        van.reply("general", str(root.ts), "reply")

        async def scenario(app: TautApp, pilot: Pilot[int]) -> None:
            await pilot.pause()
            name = f"general.{root.ts}"
            app._threads[name] = Thread(
                name=name,
                parent="general",
                unread=True,
                unread_count=4,
                last_ts=root.ts + 1,
                kind="subthread",
            )
            app._unread_counts[name] = 4
            await app._rebuild_nav()
            nav = app.query_one("#navigation")
            labels = [
                row.renderable_text.rstrip()
                for row in nav.query(NavRow)
                if row.target == name
            ]
            assert labels == [f"↳ {name}  4"]

        run_app(db, scenario)

    def test_unknown_thread_refresh_failure_does_not_ack(self) -> None:
        # A watch-delivered chat item for an unknown thread may be the only
        # convergence trigger. If refresh fails, returning normally would let the
        # watcher advance the cursor for a message that has no visible row.
        app = TautApp()
        message = Message(
            thread="dm.missing",
            ts=123,
            from_id="m_other",
            from_name="other",
            kind="message",
            text="hidden",
        )

        async def failed_refresh() -> bool:
            return False

        app._refresh_membership = failed_refresh  # type: ignore[method-assign]

        with pytest.raises(RuntimeError, match="unknown thread"):
            asyncio.run(app._apply_watch_item(message))

    def test_goto_inbox_opens_the_inbox(self, tmp_path: Path) -> None:
        # Review F5: the inbox is a documented goto target ([TUI-8.3]).
        db = seed_project(tmp_path)

        async def scenario(app: TautApp, pilot: Pilot[int]) -> None:
            app.select_target("general")
            await pilot.pause()
            await pilot.press("g")
            await pilot.pause()
            await pilot.press(*"inbox")
            await pilot.press("enter")
            await pilot.pause()
            assert app.query_one("#inbox-view").display
            assert not app.query_one("#transcript").display
            assert not app.query_one("#goto-input").display

        run_app(db, scenario)
