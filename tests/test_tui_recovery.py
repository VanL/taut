"""Recovery-state tests ([TUI-10]; plan Task 8).

Missing-extra recovery is covered in tests/test_tui_launch.py (Task 1).
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from taut.client import TautClient

textual = pytest.importorskip("textual")

from taut.tui.app import TautApp  # noqa: E402
from taut.tui.widgets import TextStatic  # noqa: E402

pytestmark = [pytest.mark.sqlite_only, pytest.mark.usefixtures("clean_env")]


class TestUninitializedProject:
    def test_empty_state_offers_init_here_and_quit(self, tmp_path: Path) -> None:
        db = tmp_path / ".taut.db"  # does not exist

        async def _run() -> None:
            app = TautApp(db_path=str(db), as_name="van", token=None)
            async with app.run_test(size=(120, 34)) as pilot:
                await pilot.pause()
                transcript = app.query_one("#transcript")
                banners = [
                    row.renderable_text
                    for row in transcript.query(TextStatic).filter(".error-banner")
                ]
                joined = " ".join(banners)
                assert "taut project" in joined  # [TUI-10.1] empty state
                assert "init" in joined
                assert "q" in joined  # quit path

                # init-here uses the same client-owned path as `taut init`
                # (TautClient.init classmethod; findings R3-2/F2).
                await pilot.press("enter")
                await pilot.pause()
                assert db.exists()
                # A fresh project has no members yet: identity guidance
                # surfaces from client rules ([TUI-10.2]); join is
                # CLI-first in v1 (Task 8 decision).
                banners = [
                    row.renderable_text
                    for row in transcript.query(TextStatic).filter(".error-banner")
                ]
                assert any("taut join" in text for text in banners)

        asyncio.run(_run())
        # The db is real and client-created: a client can open it.
        TautClient(db_path=db)


class TestLostMembership:
    def _seed(self, tmp_path: Path) -> Path:
        db = tmp_path / ".taut.db"
        TautClient.init(db_path=db)
        van = TautClient(db_path=db, as_name="van")
        van.join("general")
        van.join("ops")
        van.say("ops", "ops history stays")
        return db

    def test_banner_and_history_kept(self, tmp_path: Path) -> None:
        db = self._seed(tmp_path)

        async def _run() -> None:
            app = TautApp(db_path=str(db), as_name="van", token=None)
            async with app.run_test(size=(120, 34)) as pilot:
                await pilot.pause()
                app.select_target("general")
                await pilot.pause()

                # Membership lost externally while the TUI runs.
                TautClient(db_path=db, as_name="van").leave("ops")
                await app._refresh_membership()
                await pilot.pause()

                banner = app.query_one("#status-banner", TextStatic)
                assert banner.display
                assert "ops" in banner.renderable_text
                assert "history kept" in banner.renderable_text
                assert "taut join" in banner.renderable_text  # frame 1e
                # The conversation is removed from navigation...
                from taut.tui.widgets import NavRow

                nav = app.query_one("#navigation")
                assert not any(row.target == "ops" for row in nav.query(NavRow))
                # ...and the active conversation is untouched.
                assert app.active_target == "general"

        asyncio.run(_run())
        # [TUI-10.3]: message history is not deleted.
        observer = TautClient(db_path=db, as_name="van")
        assert "ops history stays" in [m.text for m in observer.history("ops")]

    def test_active_conversation_disabled_read_only(self, tmp_path: Path) -> None:
        db = self._seed(tmp_path)

        async def _run() -> None:
            app = TautApp(db_path=str(db), as_name="van", token=None)
            async with app.run_test(size=(120, 34)) as pilot:
                await pilot.pause()
                app.select_target("ops")
                await pilot.pause()

                TautClient(db_path=db, as_name="van").leave("ops")
                await app._refresh_membership()
                await pilot.pause()

                label = app.query_one("#composer-label", TextStatic).renderable_text
                assert "lost" in label or "read only" in label
                # History remains on screen ([TUI-10.3]).
                transcript = app.query_one("#transcript")
                texts = [
                    row.renderable_text
                    for row in transcript.query(TextStatic).filter(".message")
                ]
                assert any("ops history stays" in text for text in texts)

        asyncio.run(_run())


class TestCompletionReviewHardening:
    """Completion-review findings (Codex, 2026-07-03)."""

    def test_non_notinitialized_construction_error_shows_clean_fatal(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Finding 1 (INV-11): a backend/config TautError from client
        # construction must refuse cleanly, not crash the app — and must
        # NOT offer init-here (init won't fix a backend problem).
        from taut._exceptions import TautError

        db = tmp_path / ".taut.db"
        TautClient.init(db_path=db)

        real_init = TautApp._bootstrap  # noqa: F841 (documentation)

        def boom(*args: object, **kwargs: object) -> object:
            raise TautError("postgres backend not available. install taut-pg")

        monkeypatch.setattr("taut.tui.app.TautClient", boom)

        async def _run() -> None:
            app = TautApp(db_path=str(db), as_name="van", token=None)
            async with app.run_test(size=(120, 34)) as pilot:
                await pilot.pause()
                transcript = app.query_one("#transcript")
                banners = [
                    row.renderable_text
                    for row in transcript.query(TextStatic).filter(".error-banner")
                ]
                joined = " ".join(banners)
                assert "postgres backend" in joined  # the real cause shows
                assert not app._uninitialized  # no misleading init-here
                # init-here is not offered for a non-init failure.
                assert not app.check_action("init_here", ())

        asyncio.run(_run())

    def test_notification_while_inbox_open_renders_live(self, tmp_path: Path) -> None:
        # Finding 2: the inbox is a live surface; a notification arriving
        # while it is open must appear without a close/reopen.
        db = tmp_path / ".taut.db"
        TautClient.init(db_path=db)
        van = TautClient(db_path=db, as_name="van")
        van.join("general")
        claude = TautClient(db_path=db, as_name="claude")
        claude.join("general")
        van.read()

        async def _run() -> None:
            app = TautApp(db_path=str(db), as_name="van", token=None)
            async with app.run_test(size=(120, 34)) as pilot:
                await pilot.pause()
                await app._open_inbox()
                await pilot.pause()
                inbox_view = app.query_one("#inbox-view")

                def mention_rows() -> int:
                    return sum(
                        "mention" in row.renderable_text
                        for row in inbox_view.query(TextStatic).filter(".inbox-row")
                    )

                assert mention_rows() == 0
                # A mention arrives live while the inbox is open.
                claude.say("general", "live ping @van")
                deadline = 0
                while deadline < 200 and mention_rows() < 1:
                    await asyncio.sleep(0.05)
                    await pilot.pause()
                    deadline += 1
                assert mention_rows() == 1

        asyncio.run(_run())
