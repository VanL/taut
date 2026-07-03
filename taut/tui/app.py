"""The Taut TUI application.

Spec: docs/specs/04-taut-tui.md — layout [TUI-6], keyboard [TUI-8],
responsive modes [TUI-9], state/recovery [TUI-10], read semantics
[TUI-10.8]. The app is a pure ``TautClient`` consumer ([TUI-4.2]): every
read goes through client accessors; nothing here touches taut state, SQL,
envelopes, cursors, or notification claims.

Unread presentation is session state ([TUI-10.8]): per-thread cursors are
snapshotted once at mount, before any watcher exists, and every unread
separator anchors on that snapshot for the whole session.
"""

from __future__ import annotations

from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.widgets import ListView

from taut._exceptions import NotInitializedError, TautError
from taut.client import Member, TautClient, Thread
from taut.tui.widgets import (
    Composer,
    NavigationPane,
    NavRow,
    NavSection,
    PresencePane,
    TextStatic,
    TranscriptView,
)

KEYBAR_TEXT = (
    "↑↓ move · ⏎ open · c compose · z fold · t thread pane · m members · "
    "/ search · g goto · i inbox · ? help · q quit"
)

HISTORY_LIMIT = 200


class TautApp(App[int]):
    """Frame 2a: navigation | transcript + composer | presence."""

    CSS = """
    #titlebar { height: 1; color: $text-muted; background: $surface; }
    #keybar { height: 1; dock: bottom; color: $text-muted; }
    #main { height: 1fr; }
    #navigation { width: 26; }
    #center { width: 1fr; }
    #presence { width: 28; }
    #transcript { height: 1fr; }
    #composer { height: 2; }
    #composer-label { height: 1; color: $text-muted; }
    .nav-section { color: $text-muted; }
    .notice { color: $text-muted; }
    .separator { color: $warning; }
    .transcript-header { color: $text-muted; }
    .presence-header { color: $text-muted; }
    .error-banner { color: $error; }
    """

    BINDINGS = [Binding("q", "quit_app", "quit", show=False)]

    active_target: reactive[str | None] = reactive(None, init=False)

    def __init__(
        self,
        *,
        db_path: str | None = None,
        as_name: str | None = None,
        token: str | None = None,
    ) -> None:
        super().__init__()
        self._db_path = db_path
        self._as_name = as_name
        self._token = token
        self.client: TautClient | None = None
        self.me: Member | None = None
        # [TUI-10.8]: immutable session snapshot, captured at mount before
        # any watcher exists; separators never re-read stored cursors.
        self.cursor_snapshot: dict[str, int | None] = {}
        self._threads: dict[str, Thread] = {}
        self._members: dict[str, Member] = {}

    def compose(self) -> ComposeResult:
        yield TextStatic("taut", id="titlebar")
        with Horizontal(id="main"):
            yield NavigationPane(id="navigation")
            with Vertical(id="center"):
                yield TranscriptView(id="transcript")
                yield Composer(id="composer")
            yield PresencePane(id="presence")
        yield TextStatic(KEYBAR_TEXT, id="keybar")

    async def on_mount(self) -> None:
        try:
            self.client = TautClient(
                db_path=self._db_path,
                as_name=self._as_name,
                token=self._token,
            )
        except NotInitializedError:
            # [TUI-10.1]: the app exists without a client; recovery task
            # grows this into the init-here empty state.
            await self._show_fatal(
                "no .taut.db here — this directory isn't a taut project yet. "
                "run: taut init  ·  q quits"
            )
            return
        try:
            self.me = self.client.whoami()
            threads = self.client.joined_threads()
        except TautError as exc:
            await self._show_fatal(str(exc))
            return
        self._threads = {thread.name: thread for thread in threads}
        self.cursor_snapshot = {
            name: self.client.read_cursor(name) for name in self._threads
        }
        self._members = {member.member_id: member for member in self.client.who()}
        self.query_one("#titlebar", TextStatic).update_text(
            f"taut · {self._project_label()}"
        )
        await self._rebuild_nav()
        self.query_one("#navigation", NavigationPane).focus()
        default = next(
            (thread.name for thread in threads if thread.kind == "channel"),
            None,
        )
        if default is not None:
            self.active_target = default

    # -- state ------------------------------------------------------------

    def select_target(self, target: str) -> None:
        self.active_target = target

    async def watch_active_target(self, target: str | None) -> None:
        if target is None or self.client is None:
            return
        await self._refresh_conversation(target)

    # -- events -----------------------------------------------------------

    async def on_list_view_selected(self, event: ListView.Selected) -> None:
        item = event.item
        if isinstance(item, NavRow) and item.target != "inbox":
            self.select_target(item.target)

    def action_quit_app(self) -> None:
        self.exit(0)

    # -- rendering --------------------------------------------------------

    def _project_label(self) -> str:
        assert self.client is not None
        target = self.client.target
        if isinstance(target, str):
            return str(Path(target).resolve().parent)
        return str(getattr(target, "display_target", target))

    def _dm_counterpart(self, thread: Thread) -> Member | None:
        me_id = self.me.member_id if self.me is not None else None
        for member_id in thread.members:
            if member_id != me_id:
                return self._members.get(member_id)
        return None

    async def _rebuild_nav(self) -> None:
        channels = [t for t in self._threads.values() if t.kind == "channel"]
        dms = [t for t in self._threads.values() if t.kind == "dm"]
        subthreads = [t for t in self._threads.values() if t.kind == "subthread"]
        rows: list[NavRow | NavSection] = [NavSection("Channels")]
        for thread in channels:
            label = f"# {thread.name}"
            if thread.unread:
                label += f"  {thread.unread_count}"
            rows.append(NavRow(target=thread.name, label=label, classes="nav-channel"))
        if dms:
            rows.append(NavSection("Direct"))
            for thread in dms:
                # DM identity comes from Thread.members + client.who() —
                # never who(dm_name), which raises (finding R4-2).
                other = self._dm_counterpart(thread)
                name = other.name if other is not None else "unknown"
                presence = other.presence if other is not None else "away"
                dot = "●" if presence == "here" else "○"
                label = f"{dot} {name} {presence}"
                if thread.unread:
                    label += f"  {thread.unread_count}"
                rows.append(NavRow(target=thread.name, label=label, classes="nav-dm"))
        if subthreads:
            rows.append(NavSection("Threads"))
            for thread in subthreads:
                rows.append(
                    NavRow(
                        target=thread.name,
                        label=f"↳ {thread.name}",
                        classes="nav-thread",
                    )
                )
        rows.append(NavSection("Inbox"))
        rows.append(NavRow(target="inbox", label="⧉ inbox", classes="nav-inbox"))
        await self.query_one("#navigation", NavigationPane).set_rows(list(rows))

    async def _refresh_conversation(self, target: str) -> None:
        assert self.client is not None
        thread = self._threads.get(target)
        messages = self.client.history(target, limit=HISTORY_LIMIT)
        cursor = self.cursor_snapshot.get(target)

        if thread is not None and thread.kind == "dm":
            other = self._dm_counterpart(thread)
            other_name = other.name if other is not None else "unknown"
            header = f"── @{other_name} ──"
            composer_label = f"message @{other_name}"
            members = [
                member
                for member_id in thread.members
                if (member := self._members.get(member_id)) is not None
            ]
        else:
            members = self.client.who(target)
            header = f"── #{target} ── {len(members)} members"
            if thread is not None and thread.kind == "subthread":
                composer_label = f"reply in {target}"
            else:
                composer_label = f"message #{target}"

        await self.query_one("#transcript", TranscriptView).show_conversation(
            header=header,
            messages=messages,
            cursor=cursor,
        )
        self.query_one("#composer", Composer).set_target_label(composer_label)
        await self.query_one("#presence", PresencePane).show_members(
            members=members, me=self.me
        )

    async def _show_fatal(self, message: str) -> None:
        await self.query_one("#transcript", TranscriptView).show_error(message)


def run_app(
    *,
    db_path: str | None = None,
    as_name: str | None = None,
    token: str | None = None,
) -> int:
    app = TautApp(db_path=db_path, as_name=as_name, token=token)
    result = app.run()
    return result if isinstance(result, int) else 0
