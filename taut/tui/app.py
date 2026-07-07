"""The Taut TUI application.

Spec: docs/specs/04-taut-tui.md — layout [TUI-6], keyboard [TUI-8],
responsive modes [TUI-9], state/recovery [TUI-10], read semantics
[TUI-10.8]. The app is a pure ``TautClient`` consumer ([TUI-4.2]): every
read goes through client accessors; nothing here touches taut state, SQL,
envelopes, cursors, or notification consumption.

Unread presentation is session state ([TUI-10.8]): per-thread cursors are
snapshotted once at mount, before any watcher exists, and every unread
separator anchors on that snapshot for the whole session.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from textual import events
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.reactive import reactive
from textual.widgets import Input, ListView

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

# Responsive thresholds and pane widths (review F7): named once here, where
# they were previously bare literals duplicated across _compute_mode, the CSS
# block, and the too-small hint text.
MIN_WIDTH = 50
MIN_HEIGHT = 20
NARROW_MAX = 80  # width < NARROW_MAX -> narrow
MEDIUM_MAX = 120  # NARROW_MAX <= width < MEDIUM_MAX -> medium; >= -> wide
NAV_WIDTH = 26  # wide/medium; mirrored by the #navigation CSS default
NAV_WIDTH_NARROW = 8

# Fallback membership-convergence poll for the TUI (review F7 / perf). The
# primary convergence trigger is an unknown-thread watch delivery; this timer
# only catches removals and other-client changes, so it runs far slower than
# the watcher's own 0.5s cadence. Decoupled from WATCH_MEMBERSHIP_REFRESH_SECONDS
# so the UI poll can be slowed without touching watcher timing.
TUI_MEMBERSHIP_POLL_SECONDS = 5.0

# Cap on retained session notifications (session display state only, review F7).
MAX_SESSION_NOTIFICATIONS = 500

KEYBAR_TEXT = (
    "↑↓ move · ⏎ open · c compose · z fold · t thread pane · m members · "
    "/ search · g goto · i inbox · ? help · q quit"
)

HISTORY_LIMIT = 200

HELP_TEXT = """taut TUI commands ([TUI-8.2])
  arrows   move selection        enter  open conversation or thread
  c        focus composer        z      fold/unfold inline thread
  t        toggle thread pane    m      toggle members/presence
  /        search conversation   g      goto conversation
  i        open inbox            ?      this help
  q        quit                  esc    close pane/overlay/search"""


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
    #status-banner { height: 1; color: $warning; display: none; }
    #search-input { display: none; }
    #goto-input { display: none; }
    #inbox-view { height: 1fr; display: none; }
    #help-overlay { display: none; }
    #too-small { display: none; color: $warning; }
    """

    BINDINGS = [
        Binding("q", "quit_app", "quit", show=False),
        Binding("z", "toggle_fold", "fold", show=False),
        Binding("t", "toggle_thread_pane", "thread pane", show=False),
        Binding("escape", "close_transient", "close", show=False, priority=True),
        Binding("c", "focus_composer", "compose", show=False),
        Binding("m", "toggle_members", "members", show=False),
        Binding("slash", "open_search", "search", show=False),
        Binding("g", "open_goto", "goto", show=False),
        Binding("i", "open_inbox", "inbox", show=False),
        Binding("question_mark", "open_help", "help", show=False),
        Binding("enter", "init_here", "init here", show=False, priority=True),
    ]

    active_target: reactive[str | None] = reactive(None, init=False)
    layout_mode: reactive[str] = reactive("wide", init=False)

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
        self._inbox_open = False
        self._inbox_unseen = 0
        # None = the mode's default (wide shows presence, others hide).
        self._presence_override: bool | None = None
        self._uninitialized = False

    def compose(self) -> ComposeResult:
        yield TextStatic("taut", id="titlebar")
        with Horizontal(id="main"):
            yield NavigationPane(id="navigation")
            with Vertical(id="center"):
                yield Input(placeholder="search", id="search-input")
                yield Input(placeholder="goto", id="goto-input")
                yield TranscriptView(id="transcript")
                yield VerticalScroll(id="inbox-view")
                yield TextStatic(HELP_TEXT, id="help-overlay")
                yield TextStatic("", id="status-banner")
                yield Composer(id="composer")
            yield PresencePane(id="presence")
            yield ThreadPane(id="thread-pane")
        yield TextStatic(
            f"terminal too small — resize to at least "
            f"{MIN_WIDTH}×{MIN_HEIGHT} ([TUI-9.4])",
            id="too-small",
        )
        yield TextStatic(KEYBAR_TEXT, id="keybar")

    async def on_mount(self) -> None:
        self.layout_mode = self._compute_mode(self.size.width, self.size.height)
        await self._bootstrap()

    async def _bootstrap(self) -> None:
        try:
            self.client = TautClient(
                db_path=self._db_path,
                as_name=self._as_name,
                token=self._token,
            )
        except NotInitializedError:
            # [TUI-10.1]: the app exists without a client. The empty state
            # offers init-here (Enter) and the quit path (q).
            self._uninitialized = True
            await self._show_fatal(
                "no .taut.db here — this directory isn't a taut project "
                "yet. press enter to init here · q quits"
            )
            return
        except (TautError, RuntimeError) as exc:
            # [TUI-10.6]/[INV-11]: any other construction failure (backend
            # missing, invalid --db, config error) refuses cleanly rather
            # than crashing — and does NOT offer init-here, which would not
            # fix a backend or config problem (completion-review finding).
            await self._show_fatal(f"{exc} · q quits")
            return
        try:
            self.me = self.client.whoami()
            threads = self.client.joined_threads()
        except TautError as exc:
            # [TUI-10.2]: identity errors surface from client rules; setup
            # beyond init stays CLI-first in v1 (Task 8 decision).
            await self._show_fatal(f"{exc} — join with: taut join CHANNEL · q quits")
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
        else:
            # A fresh project (e.g. straight after init-here) has no channel
            # to select, so nothing would clear a prior fatal/empty transcript
            # and success would look like failure (review F2). Show a neutral
            # ready state instead.
            await self.query_one("#transcript", TranscriptView).show_conversation(
                header="── no channels yet — join with: taut join CHANNEL ──",
                messages=[],
                cursor=None,
            )
        self._bridge = WatchBridge(client=self.client, deliver=self._deliver_from_watch)
        self._bridge.start()
        # Convergence fallback timer (review F7/perf): a slow UI poll, since
        # the primary trigger is an unknown-thread delivery (R3-8).
        self.set_interval(TUI_MEMBERSHIP_POLL_SECONDS, self._refresh_membership)

    # -- responsive modes ([TUI-9]; plan Task 7 thresholds) -----------------

    @staticmethod
    def _compute_mode(width: int, height: int) -> str:
        if width < MIN_WIDTH or height < MIN_HEIGHT:
            return "too-small"
        if width < NARROW_MAX:
            return "narrow"
        if width < MEDIUM_MAX:
            return "medium"
        return "wide"

    def on_resize(self, event: events.Resize) -> None:
        self.layout_mode = self._compute_mode(event.size.width, event.size.height)

    def watch_layout_mode(self, mode: str) -> None:
        hint = self.query_one("#too-small", TextStatic)
        main = self.query_one("#main", Horizontal)
        if mode == "too-small":
            main.display = False
            hint.display = True
            return
        hint.display = False
        main.display = True
        # Mode changes reset the members-toggle override to the mode default.
        self._presence_override = None
        nav = self.query_one("#navigation", NavigationPane)
        nav.styles.width = NAV_WIDTH if mode in ("wide", "medium") else NAV_WIDTH_NARROW
        self._apply_presence_visibility()

    def _presence_default(self) -> bool:
        return self.layout_mode == "wide"

    def _apply_presence_visibility(self) -> None:
        presence = self.query_one("#presence", PresencePane)
        if self._pane_thread is not None:
            presence.display = False  # the thread pane borrows the column
            return
        visible = (
            self._presence_override
            if self._presence_override is not None
            else self._presence_default()
        )
        presence.display = visible

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if action == "init_here":
            return self._uninitialized
        return True

    async def action_init_here(self) -> None:
        """[TUI-10.1]: initialize through the same client-owned path as
        `taut init` (the classmethod needs no client), then bootstrap."""

        if not self._uninitialized:
            return
        try:
            TautClient.init(db_path=self._db_path)
        except (TautError, OSError, RuntimeError) as exc:
            # The recovery screen must not crash the app ([TUI-10.1]/[TUI-10.6],
            # review F2): a permission error or a bad --db dir stays a banner.
            await self._show_fatal(f"init failed: {exc} · q quits")
            return
        self._uninitialized = False
        await self._bootstrap()

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
        if not isinstance(item, NavRow):
            return
        if item.target == "inbox":
            await self._open_inbox()
        else:
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
        search = self.query_one("#search-input", Input)
        if search.display:
            search.display = False
            search.value = ""
            self._apply_search_filter("")
            return
        goto = self.query_one("#goto-input", Input)
        if goto.display:
            goto.display = False
            goto.value = ""
            return
        help_overlay = self.query_one("#help-overlay", TextStatic)
        if help_overlay.display:
            help_overlay.display = False
            return
        if self._inbox_open:
            self._close_inbox()
            return
        if self._pane_thread is not None:
            await self._close_thread_pane()

    # -- composer / toggles / overlays ([TUI-6.4], [TUI-6.5], [TUI-8.3]) ----

    def action_focus_composer(self) -> None:
        self.query_one("#composer-input", Input).focus()

    def action_toggle_members(self) -> None:
        if self._pane_thread is not None:
            return  # the thread pane is borrowing the column ([TUI-7.3])
        currently = self.query_one("#presence", PresencePane).display
        self._presence_override = not currently
        self._apply_presence_visibility()

    def action_open_search(self) -> None:
        box = self.query_one("#search-input", Input)
        box.display = True
        box.focus()

    def action_open_goto(self) -> None:
        box = self.query_one("#goto-input", Input)
        box.display = True
        box.value = ""
        box.focus()

    def action_open_help(self) -> None:
        self.query_one("#help-overlay", TextStatic).display = True

    async def action_open_inbox(self) -> None:
        await self._open_inbox()

    def _show_banner(self, text: str) -> None:
        banner = self.query_one("#status-banner", TextStatic)
        banner.update_text(text)
        banner.display = True

    def _clear_banner(self) -> None:
        # Nothing else hides the banner, so a stale "send failed" would linger
        # for the whole session (review F7). Cleared on the next good send.
        banner = self.query_one("#status-banner", TextStatic)
        banner.update_text("")
        banner.display = False

    def _apply_search_filter(self, query: str) -> None:
        """[TUI-8.3]: search the active conversation's loaded content."""

        transcript = self.query_one("#transcript", TranscriptView)
        needle = query.strip().lower()
        for row in transcript.query(TextStatic):
            if row.has_class("transcript-header"):
                continue
            row.display = needle in row.renderable_text.lower() if needle else True

    async def _goto(self, query: str) -> None:
        """[TUI-8.3]: switch among known targets; not a command palette."""

        needle = query.strip().lower()
        if not needle:
            return
        # The inbox is a goto target too ([TUI-8.3]); it is not in _threads,
        # so add it explicitly or `g inbox` is a no-op (review F5).
        candidates: dict[str, str] = {name: name for name in self._threads}
        candidates["inbox"] = "inbox"
        for thread in self._threads.values():
            if thread.kind == "dm":
                other = self._dm_counterpart(thread)
                if other is not None:
                    candidates[other.name.lower()] = thread.name
        exact = candidates.get(needle)
        partial = next(
            (target for alias, target in candidates.items() if needle in alias.lower()),
            None,
        )
        match = exact or partial
        if match == "inbox":
            await self._open_inbox()
        elif match is not None:
            self.select_target(match)

    async def _open_inbox(self) -> None:
        """The inbox renders watch-accumulated notifications — the watch
        runtime is the sole notification consumer; never client.inbox()
        while the watcher runs (finding R3-4)."""

        view = self.query_one("#inbox-view", VerticalScroll)
        await view.remove_children()
        rows: list[TextStatic] = [TextStatic("⧉ inbox", classes="transcript-header")]
        if not self.session_notifications:
            rows.append(TextStatic("no pending notifications", classes="inbox-empty"))
        for notification in self.session_notifications:
            actor = notification.actor_name or "?"
            where = f"in #{notification.thread}" if notification.thread else ""
            rows.append(
                TextStatic(
                    f"{notification.type} from {actor} {where}".strip(),
                    classes="inbox-row",
                )
            )
        await view.mount_all(rows)
        self.query_one("#transcript", TranscriptView).display = False
        view.display = True
        self._inbox_open = True
        self._inbox_unseen = 0
        self._update_nav_label("inbox")

    def _close_inbox(self) -> None:
        self.query_one("#inbox-view", VerticalScroll).display = False
        self.query_one("#transcript", TranscriptView).display = True
        self._inbox_open = False

    async def _send_from_composer(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        if not text or self.client is None or self.active_target is None:
            return
        thread = self._threads.get(self.active_target)
        warnings_before = len(self.client.last_notification_warnings)
        try:
            if thread is not None and thread.kind == "dm":
                other = self._dm_counterpart(thread)
                if other is None:
                    self._show_banner("⚠ unknown DM counterpart")
                    return
                self.client.say(f"@{other.name}", text)
            elif thread is not None and thread.kind == "subthread":
                if thread.parent is None or thread.origin_ts is None:
                    return
                self.client.reply(thread.parent, str(thread.origin_ts), text)
            else:
                self.client.say(self.active_target, text)
        except TautError as exc:
            # [TUI-10.6] composer Error state: recoverable, non-blocking.
            self._show_banner(f"⚠ send failed: {exc}")
            return
        event.input.value = ""
        # A good send clears any stale error banner (review F7) before the
        # partial-warning check below may set a fresh one.
        self._clear_banner()
        # The message itself appears via the watch path (INV-10). A
        # notification-delivery warning is Partial, not failure (INV-12).
        if len(self.client.last_notification_warnings) > warnings_before:
            warning = self.client.last_notification_warnings[-1]
            self._show_banner(f"⚠ {warning} (message sent)")

    async def _open_thread_pane(self, name: str) -> None:
        if self.client is None:
            return
        sub = self._channel_threads.get(name)
        parent_text = ""
        if sub is not None and sub.origin_ts is not None:
            parent = next(
                (m for m in self._active_messages if m.ts == sub.origin_ts),
                None,
            )
            if parent is not None:
                parent_text = f'from "{parent.text}"'
        try:
            replies = self.client.history(name, limit=HISTORY_LIMIT)
        except Exception as exc:
            # A thread-pane read must degrade to a banner, not crash ([TUI-10.4],
            # review F2).
            self._show_banner(f"⚠ could not open thread {name}: {exc}")
            return
        pane = self.query_one("#thread-pane", ThreadPane)
        await pane.show_thread(name=name, parent_text=parent_text, replies=replies)
        # The pane borrows the presence column (frame 1b, [TUI-7.3]).
        self.query_one("#presence", PresencePane).display = False
        pane.display = True
        self._pane_thread = name

    async def _close_thread_pane(self) -> None:
        self.query_one("#thread-pane", ThreadPane).display = False
        self._pane_thread = None
        self._apply_presence_visibility()

    async def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "search-input":
            self._apply_search_filter(event.value)

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "composer-input":
            await self._send_from_composer(event)
            return
        if event.input.id == "goto-input":
            await self._goto(event.value)
            event.input.display = False
            event.input.value = ""
            return
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
            # Already consumed by the watch runtime; accumulate for the
            # inbox view (the sole notification consumer, finding R3-4).
            self.session_notifications.append(item)
            if len(self.session_notifications) > MAX_SESSION_NOTIFICATIONS:
                # Session display state only; bound the oldest away (review F7).
                del self.session_notifications[0]
            if self._inbox_open:
                # The inbox is a live surface: re-render so an arrival is
                # visible without a close/reopen (completion-review finding).
                await self._open_inbox()
            else:
                self._inbox_unseen += 1
                self._update_nav_label("inbox")
            return
        key = (item.thread, item.ts)
        if key in self._seen:
            return  # backfill/watch overlap renders once (finding 3)
        if item.thread not in self._threads:
            refreshed = await self._refresh_membership()
            if not refreshed or item.thread not in self._threads:
                raise RuntimeError(
                    f"watch delivered unknown thread that could not be displayed: "
                    f"{item.thread}"
                )
        if item.thread == self.active_target:
            await self.query_one("#transcript", TranscriptView).append_message(item)
            # Register the dedup key only AFTER the UI accepted the item: a
            # failed mutation must leave redelivery observable, or the retry
            # is swallowed as a duplicate and the cursor advances without
            # display (Task 4 slice-review finding 1).
            self._seen.add(key)
            return
        me_id = self.me.member_id if self.me is not None else None
        is_own = item.from_id is not None and item.from_id == me_id
        if not is_own and item.ts > self._mount_last_ts.get(item.thread, 0):
            # Backlog up to mount is already in the seeded count; only
            # genuinely new arrivals from OTHERS increment the session badge.
            # The watcher echoes the user's own sends back (INV-10); those
            # must not inflate the unread count (review F3).
            self._unread_counts[item.thread] = (
                self._unread_counts.get(item.thread, 0) + 1
            )
        self._update_nav_label(item.thread)
        self._seen.add(key)

    async def _refresh_membership(self) -> bool:
        """Convergence triggers (R3-8): unknown-thread delivery + interval.

        The UI never drives membership; it re-reads what the watcher/client
        already converged on. New threads get their separator anchor at
        discovery time (setdefault — the mount snapshot is never mutated).
        """

        if self.client is None:
            return False
        try:
            threads = self.client.joined_threads()
        except Exception as exc:
            # Reached on the watch handoff (unknown-thread trigger) and the
            # timer. A read failure here (e.g. a concurrent rename guard or a
            # locked DB) must degrade to a banner, never propagate into the
            # watcher and burn its retries toward a poison advance (review F2;
            # Codex adversarial finding).
            self._show_banner(f"⚠ membership refresh failed: {exc}")
            return False
        current = {thread.name: thread for thread in threads}
        if set(current) == set(self._threads):
            self._threads = current
            return True
        removed = sorted(set(self._threads) - set(current))
        if removed:
            # [TUI-10.3]: the watcher already converged; the UI disables
            # the conversation and keeps history. Rejoining is CLI-first.
            names = ", ".join(f"#{name}" for name in removed)
            self._show_banner(
                f"⚠ lost membership in {names} — watcher removed it. "
                f"history kept · rejoin with: taut join {removed[0]}"
            )
            if self.active_target in removed:
                self.query_one("#composer", Composer).set_target_label(
                    f"⚠ membership lost in {self.active_target} — read only"
                )
        try:
            for name in current:
                if name not in self._threads:
                    self.cursor_snapshot.setdefault(name, self.client.read_cursor(name))
                    self._unread_counts.setdefault(name, current[name].unread_count)
                    self._mount_last_ts.setdefault(name, current[name].last_ts or 0)
            # A newly discovered thread may be a DM from a member created after
            # mount; refresh the member cache so the counterpart resolves to a
            # name (and replies are not blocked) instead of "unknown" (review
            # F5; Codex structured finding).
            self._members = {member.member_id: member for member in self.client.who()}
        except Exception as exc:
            self._show_banner(f"⚠ membership refresh failed: {exc}")
            return False
        self._threads = current
        await self._rebuild_nav()
        return True

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
            pending = self._inbox_unseen
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
            # Sub-threads track unread like any joined thread; show the badge
            # so a background reply is visible (review F4).
            return f"↳ {name}{suffix}"
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
                        label=self._row_label(thread.name),
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
        if self.client is None:
            return
        thread = self._threads.get(target)
        # Inline thread affordances come from channel_threads() — never
        # from state reads or name parsing (Addition C; finding R3-3).
        inline: list[Thread] = []
        thread_replies: dict[str, list[Message]] = {}
        try:
            messages = self.client.history(target, limit=HISTORY_LIMIT)
            if thread is None or thread.kind == "channel":
                inline = self.client.channel_threads(target)
                for sub in inline:
                    if sub.name not in self._folded:
                        thread_replies[sub.name] = self.client.history(
                            sub.name, limit=HISTORY_LIMIT
                        )
            if thread is not None and thread.kind == "dm":
                members = [
                    member
                    for member_id in thread.members
                    if (member := self._members.get(member_id)) is not None
                ]
            else:
                members = self.client.who(target)
        except Exception as exc:
            # A conversation read must degrade to a banner, never crash the app
            # ([TUI-10.4], review F2). Backend errors (e.g. a locked DB in the
            # multi-writer case taut exists for) are not all TautError, so catch
            # broadly and surface the message — nothing is swallowed silently.
            self._show_banner(f"⚠ could not open {target}: {exc}")
            return

        cursor = self.cursor_snapshot.get(target)
        # Backfill/watch dedup: everything rendered here counts as seen so
        # a drain of the same rows appends nothing (finding 3).
        self._seen.update((target, message.ts) for message in messages)
        # Viewing clears the session badge ([TUI-10.8]).
        self._unread_counts[target] = 0
        self._update_nav_label(target)
        self._active_messages = messages
        self._channel_threads = {sub.name: sub for sub in inline}

        if thread is not None and thread.kind == "dm":
            other = self._dm_counterpart(thread)
            other_name = other.name if other is not None else "unknown"
            header = f"── @{other_name} ──"
            composer_label = f"message @{other_name}"
        else:
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
