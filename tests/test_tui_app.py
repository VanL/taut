"""Textual Pilot tests for the Taut TUI app.

Spec: docs/specs/04-taut-tui.md [TUI-6], [TUI-10.8].
Plan: docs/plans/2026-07-02-taut-tui-implementation-plan.md Task 3.

Anti-mock: every test runs the real App against a real .taut.db seeded
through TautClient. Assertions are structural (roles, classes, text
substrings), never glyphs/colors ([TUI-6.3]; testing-patterns Pattern 5).
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from taut.client import TautClient

textual = pytest.importorskip("textual")

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
