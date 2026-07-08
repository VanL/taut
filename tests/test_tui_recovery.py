"""Recovery-state tests ([TUI-10]; plan Task 8).

Missing-extra recovery is covered in tests/test_tui_launch.py (Task 1).
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from taut._exceptions import IdentityError, MembershipError, TautError, ThreadNameError
from taut.client import TautClient

textual = pytest.importorskip("textual")

from textual.widgets import Input  # noqa: E402

from taut.identity import HostIdentity, IdentityCapture, ProcessInfo  # noqa: E402
from taut.tui.app import TautApp  # noqa: E402
from taut.tui.widgets import TextStatic  # noqa: E402

if TYPE_CHECKING:
    from textual.pilot import Pilot

pytestmark = [pytest.mark.sqlite_only, pytest.mark.usefixtures("clean_env")]


def _seed_initialized_project(tmp_path: Path) -> Path:
    db = tmp_path / ".taut.db"
    TautClient.init(db_path=db)
    return db


def _identity_capture(name: str) -> IdentityCapture:
    anchor = ProcessInfo(
        pid=100_000 + abs(hash(name)) % 10_000,
        ppid=1,
        start_time=f"seed-{name}",
        argv=(name,),
        uid=90_000 + abs(hash(name)) % 1_000,
        tty=f"/dev/seed-{name}",
        cwd=f"/tmp/seed-{name}",
    )
    return IdentityCapture(
        chain=(anchor,),
        host=HostIdentity(host_id=f"seed-host-{name}", host_label="seed-host"),
        uid=anchor.uid or 0,
        login=name,
        anchor=anchor,
        kind="agent",
        rule="test seed",
    )


def _seed_channels(db: Path, *channels: str) -> None:
    owner = TautClient(
        db_path=db,
        as_name="owner",
        identity_capture=_identity_capture("owner"),
    )
    for channel in channels:
        owner.join(channel)


def _fatal_text(app: TautApp) -> str:
    transcript = app.query_one("#transcript")
    return " ".join(
        row.renderable_text
        for row in transcript.query(TextStatic).filter(".error-banner")
    )


def _first_join_values(app: TautApp) -> tuple[Input, Input, TextStatic]:
    return (
        app.query_one("#firstjoin-name", Input),
        app.query_one("#firstjoin-channel", Input),
        app.query_one("#firstjoin-error", TextStatic),
    )


def _first_join_hint(app: TautApp) -> str:
    return app.query_one("#firstjoin-hint", TextStatic).renderable_text


def _first_join_channel_rows(app: TautApp) -> list[str]:
    chooser = app.query_one("#firstjoin-channels")
    return [row.renderable_text for row in chooser.query(TextStatic)]


async def _submit_first_join(
    app: TautApp,
    pilot: Pilot[int],
    *,
    name: str,
    channel: str,
) -> None:
    name_input, channel_input, _error = _first_join_values(app)
    name_input.value = name
    channel_input.value = channel
    channel_input.focus()
    await pilot.press("enter")
    await pilot.pause()


class TestFirstJoinSetup:
    def test_unrecognized_caller_opens_first_join_form(self, tmp_path: Path) -> None:
        db = _seed_initialized_project(tmp_path)

        async def _run() -> None:
            app = TautApp(db_path=str(db), as_name=None, token=None)
            async with app.run_test(size=(120, 34)) as pilot:
                await pilot.pause()
                name_input, _channel_input, error = _first_join_values(app)
                assert app._first_join_active
                assert app._bridge is None
                assert name_input.display
                assert app.focused is name_input
                assert error.renderable_text == ""
                assert "no identity recognized" in _first_join_hint(app)
                assert "enter a name and channel" in _first_join_hint(app)
                assert "esc then q" in _first_join_hint(app)
                assert "· q quits" not in _first_join_hint(app)
                assert _first_join_channel_rows(app) == []
                assert not app.query_one("#transcript").display
                assert not app.query_one("#composer").display
                assert not _fatal_text(app)

        asyncio.run(_run())

    def test_submit_name_and_channel_bootstraps_working_tui(
        self, tmp_path: Path
    ) -> None:
        db = _seed_initialized_project(tmp_path)

        async def _run() -> None:
            app = TautApp(db_path=str(db), as_name=None, token=None)
            async with app.run_test(size=(120, 34)) as pilot:
                await pilot.pause()
                await _submit_first_join(app, pilot, name="van", channel="general")
                assert not app._first_join_active
                assert app._bridge is not None
                assert app.me is not None
                assert app.me.name == "van"
                assert app.active_target == "general"
                assert (
                    "general"
                    in app.query_one("#composer-label", TextStatic).renderable_text
                )
                assert app.query_one("#presence").display
                assert "taut" in app.query_one("#titlebar", TextStatic).renderable_text

        asyncio.run(_run())

        cli_client = TautClient(db_path=db, as_name="van")
        assert cli_client.whoami().name == "van"
        assert [thread.name for thread in cli_client.joined_threads()] == ["general"]

    def test_existing_channels_are_listed_and_initially_selected(
        self, tmp_path: Path
    ) -> None:
        db = _seed_initialized_project(tmp_path)
        _seed_channels(db, "general", "ops")

        async def _run() -> None:
            app = TautApp(db_path=str(db), as_name=None, token=None)
            async with app.run_test(size=(120, 34)) as pilot:
                await pilot.pause()
                _name_input, channel_input, _error = _first_join_values(app)
                assert app._first_join_active
                assert "no identity recognized" in _first_join_hint(app)
                assert "pick a channel" in _first_join_hint(app)
                assert "type a new one" in _first_join_hint(app)
                assert "esc then q" in _first_join_hint(app)
                assert channel_input.value == "general"
                rows = _first_join_channel_rows(app)
                assert rows == ["existing channels", "> general", "  ops"]

        asyncio.run(_run())

    def test_channel_arrows_pick_existing_channel(self, tmp_path: Path) -> None:
        db = _seed_initialized_project(tmp_path)
        _seed_channels(db, "general", "ops")

        async def _run() -> None:
            app = TautApp(db_path=str(db), as_name=None, token=None)
            async with app.run_test(size=(120, 34)) as pilot:
                await pilot.pause()
                _name_input, channel_input, _error = _first_join_values(app)
                channel_input.focus()
                await pilot.press("down")
                await pilot.pause()
                assert channel_input.value == "ops"
                assert _first_join_channel_rows(app) == [
                    "existing channels",
                    "  general",
                    "> ops",
                ]
                await pilot.press("up")
                await pilot.pause()
                assert channel_input.value == "general"
                await _submit_first_join(app, pilot, name="van", channel="ops")
                assert not app._first_join_active

        asyncio.run(_run())
        assert [t.name for t in TautClient(db_path=db, as_name="van").joined_threads()] == [
            "ops"
        ]

    def test_can_type_new_channel_with_existing_channels(
        self, tmp_path: Path
    ) -> None:
        db = _seed_initialized_project(tmp_path)
        _seed_channels(db, "general")

        async def _run() -> None:
            app = TautApp(db_path=str(db), as_name=None, token=None)
            async with app.run_test(size=(120, 34)) as pilot:
                await pilot.pause()
                _name_input, channel_input, _error = _first_join_values(app)
                channel_input.focus()
                channel_input.value = "research"
                await pilot.pause()
                assert _first_join_channel_rows(app) == [
                    "existing channels",
                    "  general",
                ]
                await _submit_first_join(app, pilot, name="van", channel="research")
                assert not app._first_join_active

        asyncio.run(_run())
        assert [
            t.name for t in TautClient(db_path=db, as_name="van").joined_threads()
        ] == ["research"]

    def test_prefills_explicit_missing_as_name(self, tmp_path: Path) -> None:
        db = _seed_initialized_project(tmp_path)

        async def _run() -> None:
            app = TautApp(db_path=str(db), as_name="newname", token=None)
            async with app.run_test(size=(120, 34)) as pilot:
                await pilot.pause()
                name_input, channel_input, _error = _first_join_values(app)
                assert app._first_join_active
                assert name_input.value == "newname"
                assert app.focused is channel_input

        asyncio.run(_run())

    def test_prefill_with_existing_channels_focuses_channel_picker(
        self, tmp_path: Path
    ) -> None:
        db = _seed_initialized_project(tmp_path)
        _seed_channels(db, "general", "ops")

        async def _run() -> None:
            app = TautApp(db_path=str(db), as_name="newname", token=None)
            async with app.run_test(size=(120, 34)) as pilot:
                await pilot.pause()
                name_input, channel_input, _error = _first_join_values(app)
                assert app._first_join_active
                assert name_input.value == "newname"
                assert channel_input.value == "general"
                assert app.focused is channel_input
                await pilot.press("enter")
                await pilot.pause()
                assert not app._first_join_active

        asyncio.run(_run())
        assert [
            t.name for t in TautClient(db_path=db, as_name="newname").joined_threads()
        ] == ["general"]

    def test_invalid_as_name_shows_cli_first_guidance(self, tmp_path: Path) -> None:
        db = _seed_initialized_project(tmp_path)

        async def _run() -> None:
            app = TautApp(db_path=str(db), as_name="bad name", token=None)
            async with app.run_test(size=(120, 34)) as pilot:
                await pilot.pause()
                assert not app._first_join_active
                assert app._bridge is None
                text = _fatal_text(app)
                assert "name must match" in text
                assert "taut --as NAME join CHANNEL" in text

        asyncio.run(_run())

    def test_validation_error_stays_inline_then_recovers(self, tmp_path: Path) -> None:
        db = _seed_initialized_project(tmp_path)

        async def _run() -> None:
            app = TautApp(db_path=str(db), as_name=None, token=None)
            async with app.run_test(size=(120, 34)) as pilot:
                await pilot.pause()
                await _submit_first_join(app, pilot, name="van", channel="UPPER")
                _name_input, _channel_input, error = _first_join_values(app)
                assert app._first_join_active
                assert app._bridge is None
                assert "channel must match" in error.renderable_text
                await _submit_first_join(app, pilot, name="van", channel="general")
                assert not app._first_join_active
                assert app._bridge is not None

        asyncio.run(_run())

    @pytest.mark.parametrize(
        ("exc", "inline", "snippet"),
        [
            (ThreadNameError("not a channel: x"), True, "not a channel"),
            (MembershipError("membership failed"), True, "membership failed"),
            (
                IdentityError("current identity claim already belongs to van"),
                False,
                "taut rejoin",
            ),
            (TautError("recoverable join failure"), True, "recoverable join failure"),
        ],
    )
    def test_submit_time_error_classes(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        exc: Exception,
        inline: bool,
        snippet: str,
    ) -> None:
        db = _seed_initialized_project(tmp_path)

        def raise_join(self: TautClient, thread: str, **kwargs: object) -> object:
            raise exc

        monkeypatch.setattr("taut.tui.app.TautClient.join", raise_join)

        async def _run() -> None:
            app = TautApp(db_path=str(db), as_name=None, token=None)
            async with app.run_test(size=(120, 34)) as pilot:
                await pilot.pause()
                await _submit_first_join(app, pilot, name="van", channel="general")
                _name_input, _channel_input, error = _first_join_values(app)
                if inline:
                    assert app._first_join_active
                    assert snippet in error.renderable_text
                else:
                    assert not app._first_join_active
                    assert snippet in _fatal_text(app)

        asyncio.run(_run())

    def test_escape_clears_form_and_q_quits(self, tmp_path: Path) -> None:
        db = _seed_initialized_project(tmp_path)

        async def _run() -> None:
            app = TautApp(db_path=str(db), as_name=None, token=None)
            async with app.run_test(size=(120, 34)) as pilot:
                await pilot.pause()
                name_input, channel_input, error = _first_join_values(app)
                name_input.value = "van"
                channel_input.value = "general"
                error.update_text("stale")
                await pilot.press("escape")
                await pilot.pause()
                assert not app._first_join_active
                assert app._bridge is None
                assert not name_input.value
                assert not channel_input.value
                assert error.renderable_text == ""
                assert app.query_one("#navigation").display  # restored
                assert "taut join" in _fatal_text(app)
                await app._show_first_join(prefill=None)
                assert not name_input.value
                assert not channel_input.value
                assert app.check_action("quit_app", ())

        asyncio.run(_run())

    def test_escape_from_prefilled_form_returns_to_member_guidance(
        self, tmp_path: Path
    ) -> None:
        db = _seed_initialized_project(tmp_path)

        async def _run() -> None:
            app = TautApp(db_path=str(db), as_name="newname", token=None)
            async with app.run_test(size=(120, 34)) as pilot:
                await pilot.pause()
                assert app._first_join_active
                await pilot.press("escape")
                await pilot.pause()
                assert not app._first_join_active
                text = _fatal_text(app)
                assert "member not found: newname" in text
                assert "taut --as newname join CHANNEL" in text

        asyncio.run(_run())

    def test_modal_gate_keeps_focus_on_form(self, tmp_path: Path) -> None:
        db = _seed_initialized_project(tmp_path)

        async def _run() -> None:
            app = TautApp(db_path=str(db), as_name=None, token=None)
            async with app.run_test(size=(120, 34)) as pilot:
                await pilot.pause()
                name_input, channel_input, _error = _first_join_values(app)
                assert app.focused is name_input
                for key in ("c", "/", "g", "i", "?", "z", "t", "m"):
                    await pilot.press(key)
                    await pilot.pause()
                    assert app.focused in (name_input, channel_input)
                assert not app.query_one("#search-input").display
                assert not app.query_one("#goto-input").display
                assert not app.query_one("#inbox-view").display
                assert not app.query_one("#help-overlay").display
                assert not app.query_one("#thread-pane").display
                assert not app.query_one("#presence").display
                # Modal means modal: navigation is hidden too, so Tab cannot
                # move focus to the empty list behind the form.
                assert not app.query_one("#navigation").display
                await pilot.press("tab")
                await pilot.pause()
                assert app.focused in (name_input, channel_input)
                app.layout_mode = "medium"
                app.layout_mode = "wide"
                await pilot.pause()
                assert not app.query_one("#presence").display
                assert not app.query_one("#navigation").display
                await _submit_first_join(app, pilot, name="van", channel="general")
                assert not app._first_join_active
                assert app.query_one("#navigation").display

        asyncio.run(_run())

    def test_bootstrap_identity_conflict_is_cli_first(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        db = _seed_initialized_project(tmp_path)

        def raise_conflict(self: TautClient) -> object:
            raise IdentityError("current identity claim already belongs to van")

        monkeypatch.setattr("taut.tui.app.TautClient.whoami", raise_conflict)

        async def _run() -> None:
            app = TautApp(db_path=str(db), as_name=None, token=None)
            async with app.run_test(size=(120, 34)) as pilot:
                await pilot.pause()
                assert not app._first_join_active
                text = _fatal_text(app)
                assert "current identity claim" in text
                assert "taut rejoin" in text

        asyncio.run(_run())


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
                assert app._first_join_active
                await _submit_first_join(app, pilot, name="van", channel="general")
                assert not app._first_join_active
                assert app._bridge is not None
                assert app.active_target == "general"

        asyncio.run(_run())
        # The db is real and client-created: a client can open it.
        assert TautClient(db_path=db, as_name="van").whoami().name == "van"


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


class TestReviewFixes:
    """Pre-PR review fixes for the recovery/membership paths (F2, F5)."""

    def test_init_here_failure_shows_fatal_not_crash(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Review F2: the recovery screen must not crash. If init fails
        # (permission error, bad --db dir), it stays a banner.
        from taut._exceptions import TautError

        db = tmp_path / ".taut.db"  # never created -> uninitialized state

        def raise_init(**kwargs: object) -> object:
            raise TautError("permission denied writing .taut.db")

        monkeypatch.setattr("taut.tui.app.TautClient.init", raise_init)

        async def _run() -> None:
            app = TautApp(db_path=str(db), as_name="van", token=None)
            async with app.run_test(size=(120, 34)) as pilot:
                await pilot.pause()
                assert app._uninitialized  # reached the empty state
                await pilot.press("enter")  # action_init_here
                await pilot.pause()
                transcript = app.query_one("#transcript")
                banners = [
                    row.renderable_text
                    for row in transcript.query(TextStatic).filter(".error-banner")
                ]
                joined = " ".join(banners)
                assert "init failed" in joined
                assert "permission denied" in joined  # the real cause shows
                assert app.is_running  # did not crash
                assert app._uninitialized  # init failed, still uninitialized

        asyncio.run(_run())

    def test_new_dm_member_resolves_after_membership_refresh(
        self, tmp_path: Path
    ) -> None:
        # Review F5: a DM from a member created after mount must not render as
        # "unknown"; the member cache is refreshed on membership change.
        from taut.tui.widgets import NavRow

        db = tmp_path / ".taut.db"
        TautClient.init(db_path=db)
        van = TautClient(db_path=db, as_name="van")
        van.join("general")

        async def _run() -> None:
            app = TautApp(db_path=str(db), as_name="van", token=None)
            async with app.run_test(size=(120, 34)) as pilot:
                await pilot.pause()
                # A brand-new member DMs van after the TUI mounted.
                dana = TautClient(db_path=db, as_name="dana")
                dana.join("general")
                dana.say("@van", "hello van")
                await app._refresh_membership()
                await pilot.pause()
                nav = app.query_one("#navigation")
                dm_labels = [
                    row.renderable_text
                    for row in nav.query(NavRow)
                    if row.target.startswith("dm.")
                ]
                assert dm_labels  # the DM was discovered
                assert any("dana" in label for label in dm_labels)
                assert not any("unknown" in label for label in dm_labels)

        asyncio.run(_run())
