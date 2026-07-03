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

import asyncio
from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.widgets import Input, ListView

from taut._constants import WATCH_MEMBERSHIP_REFRESH_SECONDS
from taut._exceptions import NotInitializedError, TautError
from taut.client import Member, Message, Notification, TautClient, Thread
from taut.tui._bridge import WatchBridge
from taut.tui.widgets import (
    Composer,
    NavigationPane,
    NavRow,
    NavSection,
    PresencePane,
    TextStatic,
    ThreadPane,
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
    .thread-stub { color: $warning; }
    #thread-pane { width: 34; display: none; }
    #thread-pane-label { height: 1; color: $text-muted; }
    #thread-pane-parent { height: 2; color: $text-muted; }
    #thread-pane-replies { height: 1fr; }
    """

    BINDINGS = [
        Binding("q", "quit_app", "quit", show=False),
        Binding("z", "toggle_fold", "fold", show=False),
        Binding("t", "toggle_thread_pane", "thread pane", show=False),
        Binding("escape", "close_transient", "close", show=False, priority=True),
    ]

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
        self._bridge: WatchBridge | None = None
        # Session display state ([TUI-10.8], INV-10 carve-out): unread
        # badges seeded from stored counts at mount, then maintained from
        # watch deliveries; never written back as cursors.
        self._unread_counts: dict[str, int] = {}
        self._mount_last_ts: dict[str, int] = {}
        # Watch/backfill dedup by (thread, ts) — display-layer only.
        self._seen: set[tuple[str, int]] = set()
        self.session_notifications: list[Notification] = []
        # Inline thread display state ([TUI-7.2]: folding is display-only).
        self._folded: set[str] = set()
        self._channel_threads: dict[str, Thread] = {}
        self._active_messages: list[Message] = []
        self._pane_thread: str | None = None

    def compose(self) -> ComposeResult:
        yield TextStatic("taut", id="titlebar")
        with Horizontal(id="main"):
            yield NavigationPane(id="navigation")
            with Vertical(id="center"):
                yield TranscriptView(id="transcript")
                yield Composer(id="composer")
            yield PresencePane(id="presence")
            yield ThreadPane(id="thread-pane")
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
        # [TUI-10.8]: snapshot strictly BEFORE the watcher exists — once it
        # runs, deliveries advance stored cursors for every joined thread.
        self.cursor_snapshot = {
            name: self.client.read_cursor(name) for name in self._threads
        }
        self._unread_counts = {thread.name: thread.unread_count for thread in threads}
        self._mount_last_ts = {thread.name: thread.last_ts or 0 for thread in threads}
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
        self._bridge = WatchBridge(client=self.client, deliver=self._deliver_from_watch)
        self._bridge.start()
        # Convergence fallback timer, aligned to the watcher's own refresh
        # interval; the other trigger is an unknown-thread delivery (R3-8).
        self.set_interval(WATCH_MEMBERSHIP_REFRESH_SECONDS, self._refresh_membership)

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

    async def action_quit_app(self) -> None:
        await self._stop_bridge()
        self.exit(0)

    # -- threads ([TUI-7]) --------------------------------------------------

    def _acted_on_thread(self) -> str | None:
        """The 'active inline thread' for z/t: the sole visible sub-thread,
        else the first (row-level selection arrives with the focus work)."""

        names = list(self._channel_threads)
        return names[0] if names else None

    async def action_toggle_fold(self) -> None:
        name = self._acted_on_thread()
        if name is None or self.active_target is None:
            return
        # Display-only ([TUI-7.2]): no cursor, membership, or history change.
        if name in self._folded:
            self._folded.discard(name)
        else:
            self._folded.add(name)
        await self._refresh_conversation(self.active_target)

    async def action_toggle_thread_pane(self) -> None:
        if self._pane_thread is not None:
            await self._close_thread_pane()
            return
        name = self._acted_on_thread()
        if name is not None:
            await self._open_thread_pane(name)

    async def action_close_transient(self) -> None:
        if self._pane_thread is not None:
            await self._close_thread_pane()

    async def _open_thread_pane(self, name: str) -> None:
        assert self.client is not None
        sub = self._channel_threads.get(name)
        parent_text = ""
        if sub is not None and sub.origin_ts is not None:
            parent = next(
                (m for m in self._active_messages if m.ts == sub.origin_ts),
                None,
            )
            if parent is not None:
                parent_text = f'from "{parent.text}"'
        replies = self.client.history(name, limit=HISTORY_LIMIT)
        pane = self.query_one("#thread-pane", ThreadPane)
        await pane.show_thread(name=name, parent_text=parent_text, replies=replies)
        # The pane borrows the presence column (frame 1b, [TUI-7.3]).
        self.query_one("#presence", PresencePane).display = False
        pane.display = True
        self._pane_thread = name

    async def _close_thread_pane(self) -> None:
        self.query_one("#thread-pane", ThreadPane).display = False
        self.query_one("#presence", PresencePane).display = True
        self._pane_thread = None

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "thread-pane-input" and self._pane_thread is not None:
            sub = self._channel_threads.get(self._pane_thread)
            text = event.value.strip()
            if (
                not text
                or sub is None
                or sub.parent is None
                or sub.origin_ts is None
                or self.client is None
            ):
                return
            # The composer LABEL names the sub-thread; the CALL passes the
            # parent channel + origin message id (finding R3-5).
            try:
                self.client.reply(sub.parent, str(sub.origin_ts), text)
            except TautError as exc:
                self.query_one("#thread-pane-label", TextStatic).update_text(f"⚠ {exc}")
                return
            event.input.value = ""
            await self._open_thread_pane(self._pane_thread)

    async def on_unmount(self) -> None:
        await self._stop_bridge()

    async def _stop_bridge(self) -> None:
        """Stop+join in an executor thread so the UI loop keeps servicing
        any in-flight call_from_thread hand-off (no deadlock; finding 5)."""

        bridge = self._bridge
        self._bridge = None
        if bridge is not None:
            await asyncio.to_thread(bridge.stop)

    # -- live updates -------------------------------------------------------

    def _deliver_from_watch(self, item: Message | Notification) -> None:
        """Runs on the watcher thread. Synchronous hand-off: blocks until
        the UI applied the item; exceptions propagate so the watch runtime
        does not ack an undisplayed chat message (finding 4)."""

        # call_from_thread accepts async callables at runtime (it awaits
        # them and returns the result), but its TypeVar-in-union signature
        # defeats mypy's inference for coroutine arguments.
        self.call_from_thread(self._apply_watch_item, item)  # type: ignore[arg-type]

    async def _apply_watch_item(self, item: Message | Notification) -> None:
        if isinstance(item, Notification):
            # Claimed by the watch runtime already; accumulate for the
            # inbox view (the sole notification consumer, finding R3-4).
            self.session_notifications.append(item)
            self._update_nav_label("inbox")
            return
        key = (item.thread, item.ts)
        if key in self._seen:
            return  # backfill/watch overlap renders once (finding 3)
        if item.thread not in self._threads:
            await self._refresh_membership()
        if item.thread == self.active_target:
            await self.query_one("#transcript", TranscriptView).append_message(item)
            # Register the dedup key only AFTER the UI accepted the item: a
            # failed mutation must leave redelivery observable, or the retry
            # is swallowed as a duplicate and the cursor advances without
            # display (Task 4 slice-review finding 1).
            self._seen.add(key)
            return
        if item.ts > self._mount_last_ts.get(item.thread, 0):
            # Backlog up to mount is already in the seeded count; only
            # genuinely new arrivals increment the session badge.
            self._unread_counts[item.thread] = (
                self._unread_counts.get(item.thread, 0) + 1
            )
        self._update_nav_label(item.thread)
        self._seen.add(key)

    async def _refresh_membership(self) -> None:
        """Convergence triggers (R3-8): unknown-thread delivery + interval.

        The UI never drives membership; it re-reads what the watcher/client
        already converged on. New threads get their separator anchor at
        discovery time (setdefault — the mount snapshot is never mutated).
        """

        if self.client is None:
            return
        threads = self.client.joined_threads()
        current = {thread.name: thread for thread in threads}
        if set(current) == set(self._threads):
            self._threads = current
            return
        for name in current:
            if name not in self._threads:
                self.cursor_snapshot.setdefault(name, self.client.read_cursor(name))
                self._unread_counts.setdefault(name, current[name].unread_count)
                self._mount_last_ts.setdefault(name, current[name].last_ts or 0)
        self._threads = current
        await self._rebuild_nav()

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

    def _row_label(self, name: str) -> str:
        """Navigation label for a target, from session unread state."""

        if name == "inbox":
            pending = len(self.session_notifications)
            return f"⧉ inbox  {pending}" if pending else "⧉ inbox"
        thread = self._threads.get(name)
        count = self._unread_counts.get(name, 0)
        suffix = f"  {count}" if count else ""
        if thread is not None and thread.kind == "dm":
            # DM identity comes from Thread.members + client.who() —
            # never who(dm_name), which raises (finding R4-2).
            other = self._dm_counterpart(thread)
            other_name = other.name if other is not None else "unknown"
            presence = other.presence if other is not None else "away"
            dot = "●" if presence == "here" else "○"
            return f"{dot} {other_name} {presence}{suffix}"
        if thread is not None and thread.kind == "subthread":
            return f"↳ {name}"
        return f"# {name}{suffix}"

    def _update_nav_label(self, name: str) -> None:
        nav = self.query_one("#navigation", NavigationPane)
        for row in nav.query(NavRow):
            if row.target == name:
                row.set_label(self._row_label(name))
                return

    async def _rebuild_nav(self) -> None:
        channels = [t for t in self._threads.values() if t.kind == "channel"]
        dms = [t for t in self._threads.values() if t.kind == "dm"]
        subthreads = [t for t in self._threads.values() if t.kind == "subthread"]
        rows: list[NavRow | NavSection] = [NavSection("Channels")]
        for thread in channels:
            rows.append(
                NavRow(
                    target=thread.name,
                    label=self._row_label(thread.name),
                    classes="nav-channel",
                )
            )
        if dms:
            rows.append(NavSection("Direct"))
            for thread in dms:
                rows.append(
                    NavRow(
                        target=thread.name,
                        label=self._row_label(thread.name),
                        classes="nav-dm",
                    )
                )
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
        rows.append(
            NavRow(
                target="inbox",
                label=self._row_label("inbox"),
                classes="nav-inbox",
            )
        )
        await self.query_one("#navigation", NavigationPane).set_rows(list(rows))

    async def _refresh_conversation(self, target: str) -> None:
        assert self.client is not None
        thread = self._threads.get(target)
        messages = self.client.history(target, limit=HISTORY_LIMIT)
        cursor = self.cursor_snapshot.get(target)
        # Backfill/watch dedup: everything rendered here counts as seen so
        # a drain of the same rows appends nothing (finding 3).
        self._seen.update((target, message.ts) for message in messages)
        # Viewing clears the session badge ([TUI-10.8]).
        self._unread_counts[target] = 0
        self._update_nav_label(target)
        self._active_messages = messages

        # Inline thread affordances come from channel_threads() — never
        # from state reads or name parsing (Addition C; finding R3-3).
        inline: list[Thread] = []
        thread_replies: dict[str, list[Message]] = {}
        if thread is None or thread.kind == "channel":
            inline = self.client.channel_threads(target)
            for sub in inline:
                if sub.name not in self._folded:
                    thread_replies[sub.name] = self.client.history(
                        sub.name, limit=HISTORY_LIMIT
                    )
        self._channel_threads = {sub.name: sub for sub in inline}

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
            inline_threads=inline,
            folded=set(self._folded),
            thread_replies=thread_replies,
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
