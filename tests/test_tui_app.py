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
from taut.client import Message, Notification, TautClient

textual = pytest.importorskip("textual")

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
