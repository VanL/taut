"""Responsive-mode selection tests ([TUI-9]; plan Task 7).

Structural inspection gates: each representative size chooses the expected
mode without incoherent overlap. Thresholds (plan Task 7 decision): wide
>=120 cols, medium 80-119, narrow 50-79, too-small <50 cols OR <20 rows.
The structural modes are the contract; exact numbers are tunable.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from taut.client import TautClient

textual = pytest.importorskip("textual")

from taut.tui.app import TautApp  # noqa: E402

pytestmark = [pytest.mark.sqlite_only, pytest.mark.usefixtures("clean_env")]


def seed(tmp_path: Path) -> Path:
    db = tmp_path / ".taut.db"
    TautClient.init(db_path=db)
    van = TautClient(db_path=db, as_name="van")
    van.join("general")
    van.say("general", "sizing probe")
    return db


def mode_at(db: Path, width: int, height: int) -> dict[str, object]:
    """Run the real app at a size and capture the structural outcome."""

    result: dict[str, object] = {}

    async def _run() -> None:
        app = TautApp(db_path=str(db), as_name="van", token=None)
        async with app.run_test(size=(width, height)) as pilot:
            await pilot.pause()
            result["mode"] = app.layout_mode
            result["main"] = app.query_one("#main").display
            result["hint"] = app.query_one("#too-small").display
            result["nav"] = app.query_one("#navigation").display
            result["presence"] = app.query_one("#presence").display
            result["transcript"] = app.query_one("#transcript").display
            result["composer"] = app.query_one("#composer").display

    asyncio.run(_run())
    return result


class TestResponsiveModes:
    def test_wide_shows_three_panes(self, tmp_path: Path) -> None:
        state = mode_at(seed(tmp_path), 130, 34)
        assert state["mode"] == "wide"
        assert state["nav"] and state["presence"] and state["transcript"]
        assert state["composer"] and not state["hint"]

    def test_medium_collapses_presence_behind_toggle(self, tmp_path: Path) -> None:
        state = mode_at(seed(tmp_path), 100, 34)
        assert state["mode"] == "medium"
        assert state["nav"] and state["transcript"] and state["composer"]
        assert not state["presence"]  # available via m ([TUI-9.2])
        assert not state["hint"]

    def test_narrow_keeps_transcript_and_composer_reachable(
        self, tmp_path: Path
    ) -> None:
        state = mode_at(seed(tmp_path), 64, 34)
        assert state["mode"] == "narrow"
        assert state["transcript"] and state["composer"]  # [TUI-9.3]
        assert not state["presence"]
        assert not state["hint"]

    def test_too_small_width_shows_hint_without_crashing(self, tmp_path: Path) -> None:
        state = mode_at(seed(tmp_path), 40, 34)
        assert state["mode"] == "too-small"
        assert state["hint"] and not state["main"]  # [TUI-9.4]

    def test_too_small_height_shows_hint(self, tmp_path: Path) -> None:
        # Height is part of the enumerable threshold contract
        # (engineering-principles §12; finding R3-11).
        state = mode_at(seed(tmp_path), 130, 15)
        assert state["mode"] == "too-small"
        assert state["hint"] and not state["main"]

    def test_members_toggle_reveals_presence_in_medium(self, tmp_path: Path) -> None:
        db = seed(tmp_path)

        async def _run() -> None:
            app = TautApp(db_path=str(db), as_name="van", token=None)
            async with app.run_test(size=(100, 34)) as pilot:
                await pilot.pause()
                assert not app.query_one("#presence").display
                await pilot.press("m")
                assert app.query_one("#presence").display
                await pilot.press("m")
                assert not app.query_one("#presence").display

        asyncio.run(_run())
