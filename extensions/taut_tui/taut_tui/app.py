"""Textual composition root for the human-first Taut interface.

Spec references:
- docs/specs/10-taut-tui.md [TUI-2.2], [TUI-4.3], [TUI-5], [TUI-6],
  [TUI-7.1], [TUI-8], [TUI-9]
"""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Future
from dataclasses import replace
from pathlib import Path
from typing import Any, ClassVar, TypeVar, cast

from textual import events
from textual.app import App, ComposeResult, SeverityLevel
from textual.binding import Binding, BindingType
from textual.containers import Grid, Horizontal, Vertical
from textual.css.query import NoMatches
from textual.screen import ModalScreen

from taut import (
    IdentityError,
    NotInitializedError,
    TautError,
)
from taut.addressing import parse_target
from taut.client import (
    Channel,
    DoctorReport,
    DumpReport,
    InitResult,
    Member,
    Message,
    MessageDeletion,
    MessageReaction,
    Notification,
    SearchHit,
    Thread,
)
from taut.commands.syntax import (
    CommandInvocation,
    RootCommandSyntax,
    command_nodes,
    core_command_syntax,
    discover_command_syntax,
    format_command_syntax,
    merge_command_syntax,
)
from taut_tui.actions import (
    ActionContext,
    ActionId,
    ActionInvocation,
    ActionRoute,
    InteractionIntent,
    MouseGesture,
    action_spec,
    available_action_specs,
    gesture_hint,
    invoke_action,
    resolve_gesture,
    resolve_mouse,
)
from taut_tui.command_bindings import binding_for
from taut_tui.command_syntax import provide_syntax as provide_tui_syntax
from taut_tui.domain import TuiDomainActions
from taut_tui.forms import (
    FORM_SPECS,
    ActionApplicabilityFacts,
    ActionInputKind,
    evaluate_action_applicability,
    input_spec,
)
from taut_tui.layout import layout_placement, transition_layout
from taut_tui.models import (
    DraftState,
    FocusTarget,
    InspectorKind,
    InspectorState,
    InteractionMode,
    LayoutMode,
    LogicalSurface,
    ScrollAnchor,
    TerminalSize,
    VisualState,
)
from taut_tui.screens import (
    CommandLineScreen,
    CommandLineSubmission,
    CommandPaletteScreen,
    ConfirmationScreen,
    FormSubmission,
    NamedActionScreen,
    NamedActionSubmission,
    NativeFormScreen,
    PaletteEntry,
    SearchScreen,
    SummonStartScreen,
    SummonStartSubmission,
)
from taut_tui.session import (
    ConversationSnapshot,
    Delivery,
    NavigationSnapshot,
    TuiSession,
)
from taut_tui.summon import (
    OwnedSummonRun,
    OwnedSummonShutdown,
    SummonLogBridge,
    SummonUnavailable,
    TerminalAttachConfirmationRequest,
    TerminalLeaseRequest,
    TuiSummonInteraction,
    TuiSummonOperations,
)
from taut_tui.system import TuiSystemOperations
from taut_tui.widgets import (
    DisplayText,
    TautButton,
    TautComposer,
    TautOptionList,
    TautStatic,
    display_text,
    escape_display_text,
    escape_inline_text,
    escape_message_body,
)

_ResultT = TypeVar("_ResultT")


class ResizeHint(TautStatic):
    """Focusable recovery target while all content surfaces are hidden."""

    can_focus = True


class InspectorBody(TautStatic):
    """Focusable contextual surface for keyboard and mouse parity."""

    can_focus = True


class TerminalTooSmallScreen(ModalScreen[None]):
    """Opaque focus shield while the terminal cannot render usable content."""

    CSS = """
    TerminalTooSmallScreen {
        background: $background;
        align: center middle;
    }

    TerminalTooSmallScreen #resize-hint {
        width: 1fr;
        height: 1fr;
        content-align: center middle;
        color: $warning;
    }
    """

    def compose(self) -> ComposeResult:
        yield ResizeHint(
            "Terminal too small\nResize to at least 50 columns × 20 rows",
            id="resize-hint",
        )

    def on_mount(self) -> None:
        self.query_one("#resize-hint", ResizeHint).focus()


class TautApp(App[None]):
    """Low-chrome shell over public session work and stable visual state."""

    TITLE = "Taut"
    ENABLE_COMMAND_PALETTE = False
    CSS = """
    Screen {
        background: $background;
        color: $text;
        layout: vertical;
    }

    #workspace {
        height: 1fr;
        width: 1fr;
        layout: horizontal;
    }

    .surface {
        height: 1fr;
        padding: 0 1;
        border-left: tall $surface;
    }

    .surface:focus-within {
        border-left: tall $accent;
    }

    #navigation { width: 24; }
    #conversation { width: 1fr; }
    #inspector { width: 30; }

    .surface-title {
        height: 1;
        color: $text-muted;
        text-style: bold;
    }

    #navigation-list, #transcript { height: 1fr; }

    OptionList {
        border: none;
        padding: 0 1;
        background: $background;
    }

    OptionList:focus {
        border: none;
        background: $background;
        background-tint: transparent;
    }

    #composer {
        height: 5;
        width: 1fr;
        border: none;
        background: $background;
    }

    #composer-controls { height: 5; }
    #composer-send { width: 9; min-width: 9; }

    #context-actions {
        height: 6;
        grid-size: 2 2;
        grid-columns: 1fr 1fr;
        grid-rows: 3 3;
    }
    #context-actions Button {
        width: 1fr;
        min-width: 6;
        height: 3;
        border: none;
        padding: 0;
    }

    #resize-hint {
        width: 1fr;
        height: 1fr;
        content-align: center middle;
        color: $warning;
    }

    #status-bar { height: 3; }

    #status-line {
        width: 1fr;
        height: 3;
        content-align: left middle;
        color: $text-muted;
        padding: 0 1;
    }

    #status-bar Button {
        width: auto;
        min-width: 8;
        height: 3;
        border: none;
        background: $background;
        color: $text-muted;
    }

    #status-bar Button:focus {
        background: $surface;
        color: $text;
    }
    """
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("i", "enter_compose", "Compose", show=False),
        Binding("colon", "open_command_line", "Command line", show=False),
        Binding("slash", "open_search", "Search", show=False),
        Binding("question_mark", "open_help", "Help", show=False),
        Binding("q", "quit_tui", "Quit", show=False),
        Binding("escape", "leave_mode", "Normal mode", show=False),
        Binding("ctrl+p", "open_command", "Commands", show=False),
        Binding("ctrl+f", "open_search", "Search", show=False),
        Binding("f1", "open_help", "Help", show=False),
        Binding("ctrl+q", "quit_tui", "Quit", show=False),
        Binding(
            "ctrl+c",
            "quit_tui_anywhere",
            "Quit",
            show=False,
            priority=True,
        ),
        Binding(
            "ctrl+d",
            "quit_tui_anywhere",
            "Quit",
            show=False,
            priority=True,
        ),
    ]

    def notify(
        self,
        message: str,
        *,
        title: str = "",
        severity: SeverityLevel = "information",
        timeout: float | None = None,
        markup: bool = False,
    ) -> None:
        """Route every toast through the same terminal-display boundary."""

        del markup
        super().notify(
            str(escape_display_text(message)),
            title=str(escape_display_text(title)),
            severity=severity,
            timeout=timeout,
            markup=False,
        )

    def _query_base(
        self,
        selector: str | type[Any],
        expect_type: type[Any] | None = None,
    ) -> Any:
        """Query the mounted application screen, even while a modal is active."""

        screen = self._base_screen
        if expect_type is not None:
            assert isinstance(selector, str)
            if screen is None:
                return super().query_one(selector, expect_type)
            return screen.query_one(selector, expect_type)
        if screen is None:
            return super().query_one(selector)
        return screen.query_one(selector)

    def __init__(
        self,
        *,
        db_path: str | None,
        as_name: str | None,
        continuity_token: str | None,
    ) -> None:
        super().__init__()
        self.db_path = db_path
        self.as_name = as_name
        self.continuity_token = continuity_token
        self.visual_state = VisualState()
        self.layout_mode = LayoutMode.MEDIUM
        self._accepted_size = TerminalSize(80, 24)
        self._navigation_targets: list[str | ActionId] = []
        self._target_labels: dict[str, str] = {}
        self._target_kinds: dict[str, str] = {}
        self._reply_threads: dict[tuple[str, int], str] = {}
        self._session: TuiSession | None = None
        self._system: TuiSystemOperations | None = None
        self._domain: TuiDomainActions | None = None
        self._summon: TuiSummonOperations | None = None
        self._summon_bridge: SummonLogBridge | None = None
        self._summon_interaction: TuiSummonInteraction | None = None
        self._message_rows: tuple[Message, ...] = ()
        self._selected_search_hit: SearchHit | None = None
        self._pending_g = False
        self._operation_state = "idle"
        self._conversation_intent = 0
        self._next_send_token = 0
        self._pending_sends: dict[int, tuple[str, int]] = {}
        self._search_hits_by_intent: dict[int, SearchHit] = {}
        self._owned_summon_tokens: set[str] = set()
        self._summon_names: dict[str, str] = {}
        self._owned_exit_confirmation_open = False
        self._base_screen: Any | None = None
        self._resize_generation = 0
        self._shutting_down = False

    def compose(self) -> ComposeResult:
        with Horizontal(id="workspace"):
            with Vertical(id="navigation", classes="surface"):
                yield TautStatic("Conversations", classes="surface-title")
                yield TautOptionList("Loading workspace…", id="navigation-list")
            with Vertical(id="conversation", classes="surface"):
                yield TautStatic(
                    "Conversation", id="target-header", classes="surface-title"
                )
                yield TautOptionList(id="transcript")
                with Horizontal(id="composer-controls"):
                    yield TautComposer(
                        placeholder="Message selected target", id="composer"
                    )
                    yield TautButton("Send", id="composer-send")
            with Vertical(id="inspector", classes="surface"):
                yield TautStatic("Inspector", classes="surface-title")
                yield InspectorBody(
                    "Select a message, member, or action",
                    id="inspector-body",
                )
                with Grid(id="context-actions"):
                    yield TautButton("Members", id="members-action")
                    yield TautButton("Reply", id="reply-action")
                    yield TautButton("React", id="react-action")
                    yield TautButton("Delete", id="delete-action")
            yield ResizeHint(
                "Terminal too small\nResize to at least 50 columns × 20 rows",
                id="resize-hint",
            )
        with Horizontal(id="status-bar"):
            yield TautStatic(id="status-line")
            yield TautButton("Pane", id="pane-affordance")
            yield TautButton("Replies", id="reply-affordance")
            yield TautButton("Commands", id="commands-affordance")
            yield TautButton("Search", id="search-affordance")
            yield TautButton("Help", id="help-affordance")

    def on_mount(self) -> None:
        if self._base_screen is None:
            self._base_screen = self.screen
        size = TerminalSize(self.size.width, self.size.height)
        self._accepted_size = size
        self._apply_placement(size)
        self._set_mode(InteractionMode.NORMAL)
        self._query_base("#navigation-list", TautOptionList).focus()
        self._update_status()
        self._session = TuiSession(
            db_path=self.db_path,
            as_name=self.as_name,
            continuity_token=self.continuity_token,
            commit_conversation=self._commit_conversation_from_worker,
            accept_delivery=self._accept_delivery_from_worker,
            report_watcher_degraded=self._report_watcher_degraded_from_worker,
        )
        self._system = TuiSystemOperations(db_path=self.db_path)
        self._domain = TuiDomainActions(
            session=self._session,
            system=self._system,
            db_path=self.db_path,
        )
        bridge = SummonLogBridge(self._accept_summon_log_from_worker)
        try:
            summon = TuiSummonOperations(
                db_path=self.db_path,
                ready_callback=self._accept_summon_ready_from_worker,
            )
        except SummonUnavailable:
            summon = None
        except Exception as exc:  # noqa: BLE001 approved [DOM-10.2.1] [RUFF-SUP-085] exception
            summon = None
            self._show_error(str(exc) or type(exc).__name__)
        else:
            bridge.install()
            self._summon_bridge = bridge
            self._summon_interaction = TuiSummonInteraction(
                self,
                log_bridge=bridge,
            )
        self._summon = summon
        self._watch_future(
            self._session.refresh_navigation(),
            self._apply_navigation_result,
        )

    def on_unmount(self) -> None:
        self._shutting_down = True
        try:
            if self._summon_interaction is not None:
                close_interaction = getattr(self._summon_interaction, "close", None)
                if close_interaction is not None:
                    close_interaction()
            if self._summon is not None:
                self._summon.close()
            self._summon = None
            self._owned_summon_tokens.clear()
            self._summon_names.clear()
        finally:
            try:
                if self._summon_bridge is not None:
                    self._summon_bridge.restore()
                    self._summon_bridge = None
            finally:
                self._summon_interaction = None
                try:
                    if self._session is not None:
                        try:
                            self._session.close()
                        except Exception as exc:  # noqa: BLE001 approved [DOM-10.2.1] [RUFF-SUP-089] exception
                            detail = str(exc) or type(exc).__name__
                            self._operation_state = f"cleanup failed: {detail}"
                            self.notify(
                                f"TUI cleanup failed: {detail}",
                                severity="error",
                            )
                        finally:
                            self._session = None
                finally:
                    if self._system is not None:
                        self._system.close()
                        self._system = None
                    self._domain = None

    def on_resize(self, event: events.Resize) -> None:
        if self._base_screen is None and not isinstance(
            self.screen, TerminalTooSmallScreen
        ):
            self._base_screen = self.screen
        self._capture_draft_cursor()
        self._capture_scroll_anchor()
        prior_mode = self.layout_mode
        self._resize_generation += 1
        resize_generation = self._resize_generation
        size = TerminalSize(event.size.width, event.size.height)
        transition = transition_layout(
            self.visual_state,
            current_size=self._accepted_size,
            new_size=size,
        )
        self.visual_state = transition.state
        self._accepted_size = size
        self._apply_placement(size)
        entered_too_small = (
            prior_mode is not LayoutMode.TOO_SMALL
            and self.layout_mode is LayoutMode.TOO_SMALL
        )
        left_too_small = (
            prior_mode is LayoutMode.TOO_SMALL
            and self.layout_mode is not LayoutMode.TOO_SMALL
        )
        if entered_too_small:
            self.push_screen(TerminalTooSmallScreen())
        elif left_too_small and isinstance(self.screen, TerminalTooSmallScreen):
            self.pop_screen()
        self.call_after_refresh(self._render_latest_resize, resize_generation)
        if self.layout_mode is not LayoutMode.TOO_SMALL and len(self.screen_stack) == 1:
            self._focus_visual_target()
        self._update_status()

    def _render_latest_resize(self, generation: int) -> None:
        if generation != self._resize_generation:
            return
        conversation = self._query_base("#conversation")
        if not conversation.display:
            return
        snapshot = (
            self._session.conversation_snapshot() if self._session is not None else None
        )
        if snapshot is not None:
            self._render_messages(snapshot.messages)

    def on_text_area_changed(self, event: TautComposer.Changed) -> None:
        if not isinstance(event.text_area, TautComposer):
            return
        if event.text_area.id != "composer":
            return
        composer = event.text_area
        target = self.visual_state.active_conversation or "__unselected__"
        self.visual_state = self.visual_state.with_draft(
            DraftState(
                target=target,
                text=composer.text,
                cursor_position=min(composer.cursor_position, len(composer.text)),
                revision=(
                    0
                    if (prior := self.visual_state.draft_for(target)) is None
                    else prior.revision + (prior.text != composer.text)
                ),
            )
        )
        command_text = self._composer_command_text(composer.text, submitted=False)
        if command_text is not None:
            self.action_open_command_line(
                initial_text=command_text,
                originating_draft=self._current_draft_identity(),
            )

    def on_taut_composer_submitted(self, event: TautComposer.Submitted) -> None:
        if event.composer.id != "composer" or not event.value.strip():
            return
        command_text = self._composer_command_text(event.value, submitted=True)
        if command_text is not None:
            self.action_open_command_line(
                initial_text=command_text,
                originating_draft=self._current_draft_identity(),
            )
            return
        self._dispatch_tui_action(
            ActionId.MESSAGE_SEND,
            source=ActionRoute.KEYBOARD,
        )

    def _submit_composer(self, text: str) -> None:
        target = self.visual_state.active_conversation
        domain = self._domain
        if target is None or domain is None:
            self._show_error("Select a conversation before sending.")
            return
        self._operation_state = "sending"
        draft = self.visual_state.draft_for(target)
        self._next_send_token += 1
        send_token = self._next_send_token
        self._pending_sends[send_token] = (
            target,
            0 if draft is None else draft.revision,
        )
        self._update_status()
        self._watch_future(
            domain.send_message(target, text),
            lambda done: self._apply_send_result(send_token, done),
        )

    def _capture_draft_cursor(self) -> None:
        target = self.visual_state.active_conversation
        if target is None:
            return
        try:
            composer = self._query_base("#composer", TautComposer)
        except NoMatches:
            return
        draft = self.visual_state.draft_for(target)
        self.visual_state = self.visual_state.with_draft(
            DraftState(
                target=target,
                text=composer.text,
                cursor_position=min(composer.cursor_position, len(composer.text)),
                revision=0 if draft is None else draft.revision,
            )
        )

    def on_button_pressed(self, event: TautButton.Pressed) -> None:
        if event.button.id == "pane-affordance":
            self._cycle_surface()
            return
        if event.button.id == "reply-affordance":
            self._toggle_reply_surface()
            return
        actions = {
            "commands-affordance": ActionId.COMMAND_OPEN,
            "search-affordance": ActionId.SEARCH_OPEN,
            "help-affordance": ActionId.HELP_OPEN,
            "composer-send": ActionId.MESSAGE_SEND,
            "members-action": ActionId.MEMBERS_OPEN,
            "reply-action": ActionId.MESSAGE_REPLY,
            "react-action": ActionId.MESSAGE_REACT,
            "delete-action": ActionId.MESSAGE_DELETE,
        }
        action_id = actions.get(event.button.id or "")
        if action_id is not None:
            self._dispatch_tui_action(action_id, source=ActionRoute.MOUSE)

    def on_click(self, event: events.Click) -> None:
        if getattr(event.widget, "id", None) != "composer":
            return
        interaction = resolve_mouse(MouseGesture.COMPOSER)
        if interaction.action_id is not None:
            self._dispatch_tui_action(
                interaction.action_id,
                source=ActionRoute.MOUSE,
            )

    def on_descendant_focus(self, event: events.DescendantFocus) -> None:
        if self._shutting_down:
            return
        if event.widget.id != "composer":
            self._capture_draft_cursor()
        surface = _surface_for_widget(event.widget.id)
        if surface is not None:
            self.visual_state = replace(
                self.visual_state,
                focus=FocusTarget(surface, event.widget.id or surface.value),
                pane_choice=surface,
            )
        if event.widget.id == "composer":
            self._set_mode(InteractionMode.COMPOSE)

    def on_taut_option_list_activated(self, event: TautOptionList.Activated) -> None:
        if event.chain == 1:
            return
        if event.option_list.id == "transcript":
            if 0 <= event.option_index < len(self._message_rows):
                self._select_message(event.option_index)
                self._toggle_reply_surface()
            return
        if event.option_list.id != "navigation-list":
            return
        if not 0 <= event.option_index < len(self._navigation_targets):
            return
        selected = self._navigation_targets[event.option_index]
        if isinstance(selected, ActionId):
            self._show_empty_action(selected)
            return
        self._dispatch_tui_action(
            ActionId.CONVERSATION_OPEN,
            source=ActionRoute.NAVIGATION,
            context=ActionContext(
                target=selected,
                target_label=self._target_labels.get(selected, selected),
                surface=LogicalSurface.NAVIGATION,
            ),
        )

    def on_option_list_option_highlighted(
        self,
        event: TautOptionList.OptionHighlighted,
    ) -> None:
        if self._shutting_down:
            return
        if event.option_list.id == "navigation-list" and 0 <= event.option_index < len(
            self._navigation_targets
        ):
            selected = self._navigation_targets[event.option_index]
            self.visual_state = replace(
                self.visual_state,
                selected_navigation=selected if isinstance(selected, str) else None,
            )
        elif event.option_list.id == "transcript" and 0 <= event.option_index < len(
            self._message_rows
        ):
            message = self._message_rows[event.option_index]
            self.visual_state = replace(
                self.visual_state,
                selected_message_id=message.ts,
            )
            self._update_reply_affordance()

    def on_terminal_lease_request(self, event: TerminalLeaseRequest) -> None:
        event.hold(self)

    def on_terminal_attach_confirmation_request(
        self,
        event: TerminalAttachConfirmationRequest,
    ) -> None:
        if self._shutting_down or event.resolved.is_set():
            event.resolve(False)
            return
        notice = event.notice
        try:
            member = escape_display_text(str(notice.member))
            provider = escape_display_text(str(notice.provider))
            detach_hint = escape_display_text(str(notice.detach_hint))
            prompt = (
                f"Open provider setup for {member} with {provider}?\n\n"
                "This is provider setup, not Taut chat. Complete only trust, "
                "login, model, or equivalent setup.\n"
                f"Return to Taut with {detach_hint}. The TUI will resume and "
                "keep this Summon run active."
            )
            self.push_screen(
                ConfirmationScreen(prompt),
                lambda decision: event.resolve(bool(decision)),
            )
        except BaseException as exc:  # noqa: BLE001 approved [DOM-10.2.1] [RUFF-SUP-085] exception
            event.fail(exc)

    def on_key(self, event: events.Key) -> None:
        gesture = self._normalized_gesture(event)
        if gesture is None:
            return
        interaction = resolve_gesture(gesture, mode=self.visual_state.mode)
        if interaction is None:
            return
        if interaction.intent is InteractionIntent.LEAVE_TRANSIENT:
            self._leave_transient_from_key(event)
            return
        if interaction.intent is InteractionIntent.OPEN_COMMAND_LINE:
            event.prevent_default()
            event.stop()
            self.action_open_command_line()
            return
        if self.visual_state.mode is not InteractionMode.NORMAL:
            return
        if interaction.intent is InteractionIntent.DISPATCH_ACTION:
            event.prevent_default()
            event.stop()
            if interaction.action_id is not None:
                self._dispatch_tui_action(
                    interaction.action_id,
                    source=ActionRoute.KEYBOARD,
                )
            return
        if self._dispatch_navigation_intent(interaction.intent):
            event.prevent_default()
            event.stop()

    def _normalized_gesture(self, event: events.Key) -> str | None:
        gesture = event.character or event.key
        if self.visual_state.mode is InteractionMode.NORMAL:
            if gesture == "g":
                self._pending_g = True
                event.prevent_default()
                event.stop()
                return None
            if self._pending_g:
                self._pending_g = False
                gesture = f"g {gesture}"
        return gesture

    def _leave_transient_from_key(self, event: events.Key) -> None:
        if self.visual_state.mode is not InteractionMode.NORMAL:
            event.prevent_default()
            event.stop()
            self.action_leave_mode()

    def action_open_command(self) -> None:
        if self.visual_state.mode is InteractionMode.NORMAL:
            self._set_mode(InteractionMode.COMMAND)
            self.push_screen(
                CommandPaletteScreen(self._palette_entries()),
                self._complete_palette,
            )

    def action_open_command_line(
        self,
        *,
        initial_text: str = "",
        originating_draft: tuple[str, int] | None = None,
    ) -> None:
        if self.visual_state.mode is InteractionMode.NORMAL or (
            self.visual_state.mode is InteractionMode.COMPOSE and initial_text
        ):
            self._set_mode(InteractionMode.COMMAND)
            self.push_screen(
                CommandLineScreen(
                    self._command_syntax(),
                    initial_text=initial_text,
                ),
                lambda submission: self._complete_command_line(
                    submission,
                    originating_draft=originating_draft,
                ),
            )

    def _current_draft_identity(self) -> tuple[str, int] | None:
        target = self.visual_state.active_conversation or "__unselected__"
        draft = self.visual_state.draft_for(target)
        return None if draft is None else (target, draft.revision)

    def _composer_command_text(self, text: str, *, submitted: bool) -> str | None:
        if not text.startswith(":"):
            return None
        body = text[1:]
        boundary = next(
            (index for index, character in enumerate(body) if character.isspace()),
            None,
        )
        if boundary is None:
            if not submitted:
                return None
            root = body
            command_text = body
        else:
            root = body[:boundary]
            remainder = body[boundary:].lstrip()
            command_text = root + " " + remainder
        roots = {node.path[0] for node in command_nodes(self._command_syntax())}
        return command_text if root in roots else None

    def action_open_search(self) -> None:
        if self.visual_state.mode is InteractionMode.NORMAL:
            self._set_mode(InteractionMode.SEARCH)
            domain = self._domain
            if domain is None:
                self._set_mode(InteractionMode.NORMAL)
                return

            def search(query: str) -> Future[list[object]]:
                return cast(Future[list[object]], domain.search(query))

            self.push_screen(SearchScreen(search), self._complete_search)

    def action_open_help(self) -> None:
        self._render_inspector(
            "Keys: j/k or Down/Up move; h/l or Left/Right change panes; "
            "gg / Home and G / End jump; Ctrl-U / PageUp pages up; "
            "PageDown pages down; Tab / Shift-Tab move focus; Enter opens; "
            "i composes; "
            "in compose, Enter sends, Ctrl-Enter, Shift-Enter, or Ctrl-J "
            "inserts a newline, and Ctrl-Tab inserts a tab; "
            ": / Ctrl-P commands; / / Ctrl-F search; ? / F1 help; "
            "g i opens notifications; q / Ctrl-Q quits in normal mode; "
            "Ctrl-C / Ctrl-D quits whenever the TUI owns the terminal. "
            "Notification pointers are consumable and shared by sessions; "
            "chat history remains durable. "
            "Use Pane to cycle compact surfaces and Replies to open or close a "
            "selected reply thread. "
            "Use your terminal's modified drag (commonly Shift-drag) for text selection.",
            kind=InspectorKind.SYSTEM,
        )

    def action_quit_tui(self) -> None:
        reason = self._system.quit_block_reason() if self._system is not None else None
        if reason is not None:
            self._show_error(reason)
            return
        summon_reason = (
            self._summon.quit_block_reason() if self._summon is not None else None
        )
        if summon_reason is not None:
            if self._summon is not None and self._summon.has_pending_owned():
                self._show_error(summon_reason)
                return
            if self._owned_exit_confirmation_open:
                return
            self._owned_exit_confirmation_open = True
            try:
                self.push_screen(
                    ConfirmationScreen(f"{summon_reason} Stop owned runs and quit?"),
                    self._complete_owned_exit,
                )
            except BaseException:
                self._owned_exit_confirmation_open = False
                raise
            return
        self.exit()

    def action_quit_tui_anywhere(self) -> None:
        self._dispatch_tui_action(
            ActionId.APPLICATION_QUIT,
            source=ActionRoute.KEYBOARD,
        )

    def action_enter_compose(self) -> None:
        if self.visual_state.mode is InteractionMode.NORMAL:
            self._dispatch_tui_action(
                ActionId.COMPOSE_ENTER,
                source=ActionRoute.KEYBOARD,
            )

    def action_leave_mode(self) -> None:
        if self.visual_state.mode is InteractionMode.NORMAL:
            return
        self._set_mode(InteractionMode.NORMAL)
        if self.layout_mode is LayoutMode.COMPACT:
            self.visual_state = replace(
                self.visual_state,
                pane_choice=LogicalSurface.CONVERSATION,
                focus=FocusTarget(LogicalSurface.CONVERSATION, "transcript"),
            )
            self._apply_placement(self._accepted_size)
            self._focus_visual_target()
        else:
            self._query_base("#navigation-list", TautOptionList).focus()

    def check_action(
        self,
        action: str,
        parameters: tuple[object, ...],
    ) -> bool | None:
        del parameters
        normal_only = {
            "enter_compose",
            "open_command",
            "open_command_line",
            "open_search",
            "quit_tui",
        }
        if action in normal_only:
            return self.visual_state.mode is InteractionMode.NORMAL
        if action == "leave_mode":
            return self.visual_state.mode is not InteractionMode.NORMAL
        return True

    def _dispatch_tui_action(
        self,
        action_id: ActionId,
        *,
        source: ActionRoute,
        context: ActionContext | None = None,
    ) -> None:
        self._dispatch_action_invocation(
            invoke_action(
                action_id,
                context or self._current_action_context(),
                source=source,
            )
        )

    def _dispatch_action_invocation(self, invocation: ActionInvocation) -> None:
        action_id = invocation.action_id
        context = invocation.context
        if action_id is ActionId.CONVERSATION_OPEN and context.target is not None:
            self.visual_state = replace(
                self.visual_state,
                selected_navigation=context.target,
            )
        applicability = evaluate_action_applicability(
            action_id,
            self._current_action_applicability_facts(),
        )
        if not applicability.enabled:
            assert applicability.reason is not None
            self._show_error(applicability.reason)
            return
        if self._open_native_form(action_id) or self._dispatch_shell_action(action_id):
            return
        domain = self._domain
        if domain is None:
            self._show_error("The Taut session is still starting.")
            return
        if self._dispatch_simple_domain_action(action_id, domain):
            return
        if self._dispatch_context_action(action_id, domain):
            return
        if self._dispatch_system_or_summon_action(action_id, domain):
            return
        self._show_error(f"{action_spec(action_id).label} needs a current selection.")

    def _current_action_context(self) -> ActionContext:
        target = self.visual_state.active_conversation
        return ActionContext(
            target=target,
            target_label=(
                None if target is None else self._target_labels.get(target, target)
            ),
            message_id=self.visual_state.selected_message_id,
            surface=self.visual_state.focus.surface,
        )

    def _current_action_applicability_facts(self) -> ActionApplicabilityFacts:
        """Project mutable Textual state into the closed pure fact vocabulary."""

        target = self.visual_state.active_conversation
        selected_message_id = self.visual_state.selected_message_id
        draft = None if target is None else self.visual_state.draft_for(target)
        return ActionApplicabilityFacts(
            selected_target=self.visual_state.selected_navigation is not None,
            active_target=target is not None,
            active_channel=(
                target is not None and self._target_kinds.get(target) == "channel"
            ),
            selected_message=(
                selected_message_id is not None
                and any(
                    message.ts == selected_message_id for message in self._message_rows
                )
            ),
            selected_search_result=self._selected_search_hit is not None,
            has_nonblank_draft=draft is not None and bool(draft.text.strip()),
        )

    def _open_native_form(self, action_id: ActionId) -> bool:
        if action_id not in FORM_SPECS:
            return False
        contract = input_spec(action_id)
        if contract.kind is not ActionInputKind.FORM or contract.form is None:
            return False
        self.push_screen(NativeFormScreen(contract.form))
        return True

    def on_native_form_screen_submitted(
        self,
        event: NativeFormScreen.Submitted,
    ) -> None:
        event.stop()
        self._complete_form(event.submission, screen=event.screen)

    def _dispatch_shell_action(self, action_id: ActionId) -> bool:
        if action_id is ActionId.COMPOSE_ENTER:
            self._set_mode(InteractionMode.COMPOSE)
            self._query_base("#composer", TautComposer).focus()
        elif action_id is ActionId.COMMAND_OPEN:
            self.action_open_command()
        elif action_id is ActionId.SEARCH_OPEN:
            self.action_open_search()
        elif action_id is ActionId.HELP_OPEN:
            self.action_open_help()
        elif action_id is ActionId.APPLICATION_QUIT:
            self.action_quit_tui()
        else:
            return False
        return True

    def _command_syntax(self) -> RootCommandSyntax:
        syntax = core_command_syntax()
        discovery = discover_command_syntax()
        providers = [provide_tui_syntax(), *discovery.providers]
        if self._summon is not None and not any(
            provider.provider_name == "taut-summon" for provider in providers
        ):
            try:
                from taut_summon.command_syntax import provide_syntax

                providers.append(provide_syntax())
            except Exception as exc:  # noqa: BLE001 approved [DOM-10.2.1] [RUFF-SUP-085] exception
                self._operation_state = f"syntax unavailable: {exc}"
        if discovery.diagnostics:
            self._operation_state = discovery.diagnostics[0]
        return merge_command_syntax(syntax, tuple(providers))

    def _complete_command_line(
        self,
        submission: CommandLineSubmission | None,
        *,
        originating_draft: tuple[str, int] | None = None,
    ) -> None:
        return_mode = (
            InteractionMode.COMPOSE
            if originating_draft is not None
            else InteractionMode.NORMAL
        )
        self._set_mode(return_mode)
        if submission is not None:
            if originating_draft is not None:
                self._clear_originating_command_draft(originating_draft)
            self._dispatch_command_invocation(submission.invocation)

    def _clear_originating_command_draft(self, origin: tuple[str, int]) -> None:
        target, revision = origin
        draft = self.visual_state.draft_for(target)
        if draft is None or draft.revision != revision:
            return
        self.visual_state = self.visual_state.with_draft(
            DraftState(target=target, revision=revision + 1)
        )
        active_target = self.visual_state.active_conversation or "__unselected__"
        if active_target == target:
            self._query_base("#composer", TautComposer).text = ""

    def _dispatch_command_invocation(self, invocation: CommandInvocation) -> None:
        if invocation.action is not None:
            self._render_command_action(invocation)
            return
        policy_error = self._command_policy_error(invocation)
        if policy_error is not None:
            self._show_error(policy_error)
            return
        binding = binding_for(invocation.path)
        if binding is None or binding.cli_only:
            self._show_error("CLI-only in TUI: " + " ".join(invocation.path))
            return
        if invocation.path in {("q",), ("quit",)}:
            self._dispatch_tui_action(
                ActionId.APPLICATION_QUIT,
                source=ActionRoute.KEYBOARD,
            )
            return
        if invocation.path in {("summon",), ("dismiss",)}:
            self._dispatch_summon_command(invocation)
            return
        domain = self._domain
        if domain is None:
            self._show_error("The Taut session is still starting.")
            return
        handlers = (
            self._dispatch_identity_command,
            self._dispatch_conversation_command,
            self._dispatch_message_command,
            self._dispatch_channel_command,
            self._dispatch_system_command,
        )
        for handler in handlers:
            if handler(invocation, domain):
                return
        self._show_error("CLI-only in TUI: " + " ".join(invocation.path))

    def _render_command_action(self, invocation: CommandInvocation) -> None:
        if invocation.action == "version":
            from taut import __version__

            self._render_inspector(f"taut {__version__}\nTUI command mirror")
            return
        syntax = self._command_syntax()
        if not invocation.path:
            text = "Commands\n" + "\n".join(
                format_command_syntax(node) for node in command_nodes(syntax)
            )
        else:
            node = next(
                (
                    candidate
                    for candidate in command_nodes(syntax)
                    if candidate.path == invocation.path
                ),
                None,
            )
            text = (
                format_command_syntax(node)
                if node is not None
                else "Unknown command syntax"
            )
        self._render_inspector(text)

    def _command_policy_error(self, invocation: CommandInvocation) -> str | None:
        values = invocation.values
        requested_db = values.get("db_path")
        if requested_db is not None:
            if self.db_path is None:
                return "--db is unavailable in TUI command mode; use the active session target."
            if str(requested_db) != str(self.db_path):
                return "--db must match the active TUI session target."
        if (
            values.get("as_name") is not None
            or values.get("continuity_token") is not None
        ):
            return "TUI identity is fixed for this session; omit --as and --token."
        for option in ("json", "timestamps", "quiet"):
            if values.get(option):
                spelling = {
                    "json": "--json",
                    "timestamps": "--timestamps",
                    "quiet": "--quiet",
                }[option]
                return f"{spelling} is CLI-only in the TUI result surface."
        return None

    def _dispatch_identity_command(
        self,
        invocation: CommandInvocation,
        domain: TuiDomainActions,
    ) -> bool:
        values = invocation.values
        if invocation.path == ("init",):
            self._run_action(domain.initialize_workspace(), refresh_navigation=True)
        elif invocation.path == ("set", "name"):
            self._run_action(domain.set_name(str(values["name"])))
        elif invocation.path == ("rejoin",):
            self._run_action(
                domain.rejoin_identity(
                    cast(str | None, values.get("name_or_alias") or None),
                    token=cast(str | None, values.get("rejoin_token") or None),
                ),
                refresh_navigation=True,
            )
        elif invocation.path == ("whoami",):
            self._run_action(domain.show_identity(explain=bool(values.get("explain"))))
        else:
            return False
        return True

    def _dispatch_conversation_command(
        self,
        invocation: CommandInvocation,
        domain: TuiDomainActions,
    ) -> bool:
        values = invocation.values
        if invocation.path == ("join",):
            self._run_action(
                domain.join_channel(
                    str(values["thread"]),
                    persona=cast(str | None, values.get("persona")),
                    new=bool(values.get("new")),
                ),
                refresh_navigation=True,
            )
        elif invocation.path == ("leave",):
            target = str(values["thread"])
            self._confirm_command(
                f"Leave {target}?",
                lambda: self._run_action(
                    domain.leave_channel(target), refresh_navigation=True
                ),
            )
        else:
            return False
        return True

    def _dispatch_message_command(
        self,
        invocation: CommandInvocation,
        domain: TuiDomainActions,
    ) -> bool:
        path = invocation.path
        if path in {("say",), ("reply",)}:
            self._dispatch_send_command(invocation, domain)
            return True
        if path[:1] == ("message",):
            self._dispatch_message_operation(invocation, domain)
            return True
        if path in {("read",), ("inbox",), ("log",), ("search",)}:
            self._dispatch_history_command(invocation, domain)
            return True
        return False

    def _dispatch_send_command(
        self,
        invocation: CommandInvocation,
        domain: TuiDomainActions,
    ) -> None:
        values = invocation.values
        text = values.get("text")
        if not isinstance(text, str) or text == "-":
            self._show_error(
                "CLI-only in TUI: " + " ".join(invocation.path) + " with stdin"
            )
        elif invocation.path == ("say",):
            self._run_action(domain.send_message(str(values["target"]), text))
        else:
            self._run_action(
                domain.reply_message(str(values["thread"]), str(values["msg_id"]), text)
            )

    def _dispatch_message_operation(
        self,
        invocation: CommandInvocation,
        domain: TuiDomainActions,
    ) -> None:
        values = invocation.values
        if invocation.path == ("message", "show"):
            self._run_action(domain.show_message(str(values["msg_id"])))
        elif invocation.path == ("message", "delete"):
            message_id = str(values["msg_id"])
            self._confirm_command(
                f"Delete message {message_id}?",
                lambda: self._run_action(domain.delete_message(message_id)),
            )
        else:
            self._run_action(
                domain.react_message(str(values["msg_id"]), str(values["reaction"]))
            )

    def _dispatch_history_command(
        self,
        invocation: CommandInvocation,
        domain: TuiDomainActions,
    ) -> None:
        values = invocation.values
        if invocation.path == ("read",):
            self._run_action(
                domain.read_messages(cast(str | None, values.get("thread")))
            )
        elif invocation.path == ("inbox",):
            self._run_action(domain.inbox())
        elif invocation.path == ("log",):
            self._run_action(
                domain.log_messages(
                    str(values["thread"]),
                    since=cast(str | int | None, values.get("since")),
                    limit=cast(int | None, values.get("limit")),
                )
            )
        else:
            unsupported = next(
                (
                    option
                    for option in (
                        "channel",
                        "dm",
                        "dms",
                        "from_member",
                        "kind",
                        "before",
                        "reindex",
                    )
                    if values.get(option)
                ),
                None,
            )
            if unsupported is not None:
                self._show_error(
                    f"--{unsupported.replace('_', '-')} is CLI-only in the TUI."
                )
                return
            query = " ".join(cast(list[str], values["query"]))
            self._run_action(domain.search(query, limit=cast(int, values["limit"])))

    def _dispatch_channel_command(
        self,
        invocation: CommandInvocation,
        domain: TuiDomainActions,
    ) -> bool:
        values = invocation.values
        path = invocation.path
        if path == ("channel", "show"):
            self._run_action(domain.show_topic(str(values["channel"])))
        elif path == ("channel", "topic"):
            channel = str(values["channel"])
            if values.get("clear"):
                self._run_action(domain.clear_topic(channel))
            else:
                self._run_action(domain.set_topic(channel, str(values["topic"])))
        elif path == ("channel", "rename"):
            old_name = str(values["old_name"])
            self._confirm_command(
                f"Rename {old_name}?",
                lambda: self._run_action(
                    domain.rename_channel(old_name, str(values["new_name"])),
                    refresh_navigation=True,
                ),
            )
        elif path == ("who",):
            self._run_action(
                domain.members_for_thread(cast(str | None, values.get("thread")))
            )
        elif path == ("list",):
            self._run_action(
                domain.list_threads(
                    all_threads=bool(values.get("all_threads")),
                    direct_messages=bool(values.get("dms")),
                )
            )
        else:
            return False
        return True

    def _dispatch_system_command(
        self,
        invocation: CommandInvocation,
        domain: TuiDomainActions,
    ) -> bool:
        path = invocation.path
        values = invocation.values
        if path == ("system", "doctor"):
            self._run_action(domain.doctor())
        elif path == ("system", "debug", "enable"):
            assert self._system is not None
            self._run_action(self._system.submit_debug(True))
        elif path == ("system", "debug", "disable"):
            assert self._system is not None
            self._run_action(self._system.submit_debug(False))
        elif path == ("system", "dump"):
            output = Path(str(values["output"]))
            self._run_command_dump(domain, output)
        else:
            return False
        return True

    def _run_command_dump(self, domain: TuiDomainActions, output: Path) -> None:
        if output.exists():
            self._confirm_command(
                f"Replace existing dump {output}?",
                lambda: self._run_action(domain.dump(output, replace_confirmed=True)),
            )
        else:
            self._run_action(domain.dump(output))

    def _dispatch_summon_command(self, invocation: CommandInvocation) -> None:
        summon = self._summon
        interaction = self._summon_interaction
        values = invocation.values
        if summon is None or interaction is None:
            self._show_error(
                "Summon command syntax is known, but Summon is not installed."
            )
            return
        if invocation.path == ("dismiss",):
            name = str(values["name"])
            self._confirm_command(
                f"Dismiss {name}?",
                lambda: self._run_action(summon.submit_stop(name)),
            )
            return
        try:
            request = summon.build_request(
                name=str(values["name"]),
                threads=tuple(cast(list[str], values.get("threads") or ["general"])),
                terminal=bool(values.get("terminal")),
                persona=cast(str | None, values.get("persona")),
                system_prompt_file=cast(str | None, values.get("system_prompt_file")),
                rate_limit=cast(int | None, values.get("rate_limit")),
                attach=bool(values.get("attach")),
                detach=bool(values.get("detach")),
                provider_flag=cast(str | None, values.get("provider")),
                takeover=bool(values.get("takeover")),
            )
            token, future = summon.start(request, interaction)
        except Exception as exc:  # noqa: BLE001 approved [DOM-10.2.1] [RUFF-SUP-085] exception
            self._show_error(str(exc) or type(exc).__name__)
            return
        self._owned_summon_tokens.add(token)
        self._summon_names[token] = str(values["name"])
        self._operation_state = f"summon {values['name']} starting"
        self._update_status()
        self._watch_future(future, lambda done: self._apply_summon_return(token, done))

    def _confirm_command(self, prompt: str, action: Callable[[], None]) -> None:
        self.push_screen(
            ConfirmationScreen(prompt),
            lambda confirmed: action() if confirmed else None,
        )

    def _dispatch_simple_domain_action(
        self,
        action_id: ActionId,
        domain: TuiDomainActions,
    ) -> bool:
        if action_id is ActionId.WORKSPACE_INITIALIZE:
            self._run_action(domain.initialize_workspace(), refresh_navigation=True)
        elif action_id is ActionId.IDENTITY_SHOW:
            self._run_action(domain.show_identity())
        elif action_id is ActionId.CONVERSATION_OPEN:
            target = self.visual_state.selected_navigation
            assert target is not None
            intent = self._advance_conversation_intent()
            self.visual_state = replace(
                self.visual_state,
                scroll_anchor=ScrollAnchor.tail(),
            )
            self._watch_future(
                domain.open_conversation(target, intent_token=intent),
                lambda done: self._apply_optional_conversation(intent, done),
            )
        elif action_id is ActionId.NOTIFICATIONS_OPEN:
            self._render_notifications(domain.notifications())
        elif action_id is ActionId.MEMBERS_OPEN:
            self._run_action(domain.members(self.visual_state.active_conversation))
        elif action_id is ActionId.MESSAGE_SEND:
            composer = self._query_base("#composer", TautComposer)
            if composer.text.strip():
                self._submit_composer(composer.text)
        elif action_id is ActionId.SEARCH_OPEN_RESULT:
            self._open_selected_search_result()
        else:
            return False
        return True

    def _dispatch_context_action(
        self,
        action_id: ActionId,
        domain: TuiDomainActions,
    ) -> bool:
        if action_id is ActionId.CHANNEL_LEAVE:
            self._confirm_context_action(
                action_id,
                self.visual_state.active_conversation,
                lambda target: self._run_action(
                    domain.leave_channel(target), refresh_navigation=True
                ),
            )
        elif action_id is ActionId.CHANNEL_SHOW_TOPIC:
            self._with_active_target(
                lambda target: self._run_action(domain.show_topic(target))
            )
        elif action_id is ActionId.CHANNEL_CLEAR_TOPIC:
            self._with_active_target(
                lambda target: self._run_action(domain.clear_topic(target))
            )
        elif action_id is ActionId.MESSAGE_DELETE:
            self._confirm_message_delete(domain)
        else:
            return False
        return True

    def _dispatch_system_or_summon_action(
        self,
        action_id: ActionId,
        domain: TuiDomainActions,
    ) -> bool:
        if action_id is ActionId.SYSTEM_DOCTOR:
            self._run_action(domain.doctor())
        elif action_id is ActionId.SUMMON_LIST:
            if self._summon is None:
                self._show_error("Summon support is not installed.")
            else:
                self._run_action(self._summon.submit_list())
        elif action_id is ActionId.SUMMON_START:
            if self._summon is None:
                self._show_error("Summon support is not installed.")
            else:
                try:
                    providers = self._summon.provider_names()
                except Exception as exc:  # noqa: BLE001 approved [DOM-10.2.1] [RUFF-SUP-085] exception
                    self._show_error(str(exc) or type(exc).__name__)
                else:
                    self.push_screen(
                        SummonStartScreen(providers),
                        self._complete_summon_start,
                    )
        elif action_id in {ActionId.SUMMON_STATUS, ActionId.SUMMON_DISMISS}:
            if self._summon is None:
                self._show_error("Summon support is not installed.")
            else:
                self.push_screen(
                    NamedActionScreen(action_id, action_spec(action_id).label),
                    self._complete_named_summon_action,
                )
        else:
            return False
        return True

    def _complete_summon_start(
        self,
        submission: SummonStartSubmission | None,
    ) -> None:
        summon = self._summon
        interaction = self._summon_interaction
        if submission is None or summon is None or interaction is None:
            return
        try:
            request = summon.build_request(
                name=submission.name,
                threads=submission.threads,
                terminal=submission.terminal,
                persona=submission.persona,
                system_prompt_file=submission.system_prompt_file,
                rate_limit=submission.rate_limit,
                attach=submission.attach,
                detach=submission.detach,
                provider_flag=submission.provider,
                takeover=submission.takeover,
            )
            token, future = summon.start(request, interaction)
        except Exception as exc:  # noqa: BLE001 approved [DOM-10.2.1] [RUFF-SUP-085] exception
            self._show_error(str(exc) or type(exc).__name__)
            return
        self._owned_summon_tokens.add(token)
        self._summon_names[token] = submission.name
        self._operation_state = f"summon {submission.name} starting"
        self._update_status()
        self._watch_future(
            future,
            lambda done: self._apply_summon_return(token, done),
        )

    def _complete_named_summon_action(
        self,
        submission: NamedActionSubmission | None,
    ) -> None:
        summon = self._summon
        if submission is None or summon is None:
            return
        if submission.action_id is ActionId.SUMMON_STATUS:
            self._run_action(summon.submit_status(submission.name))
            return
        prompt = action_spec(ActionId.SUMMON_DISMISS).confirmation_prompt
        assert prompt is not None
        self.push_screen(
            ConfirmationScreen(prompt.format(target=submission.name)),
            lambda confirmed: (
                self._run_action(summon.submit_stop(submission.name))
                if confirmed
                else None
            ),
        )

    def _apply_summon_return(
        self,
        token: str,
        future: Future[None],
    ) -> None:
        self._owned_summon_tokens.discard(token)
        member_name = self._summon_names.pop(token, "summoned member")
        try:
            future.result()
        except BaseException as exc:  # noqa: BLE001 approved [DOM-10.2.1] [RUFF-SUP-087] exception
            try:
                self._show_error(str(exc) or type(exc).__name__)
            except BaseException:  # noqa: BLE001,S110 approved [DOM-10.2.1] [RUFF-SUP-086] exception
                pass
        else:
            try:
                self._render_inspector(
                    f"Summon run for {member_name} ended.",
                    kind=InspectorKind.SUMMON,
                )
            except BaseException:  # noqa: BLE001,S110 approved [DOM-10.2.1] [RUFF-SUP-086] exception
                pass
        self._operation_state = "idle"
        try:
            self._update_status()
        except BaseException:  # noqa: BLE001,S110 approved [DOM-10.2.1] [RUFF-SUP-086] exception
            pass

    def _confirm_message_delete(self, domain: TuiDomainActions) -> None:
        message_id = self.visual_state.selected_message_id
        if message_id is None:
            self._show_error("Select a message first.")
            return
        target = self.visual_state.active_conversation
        intent = self._conversation_intent
        prompt = action_spec(ActionId.MESSAGE_DELETE).confirmation_prompt
        assert prompt is not None
        self.push_screen(
            ConfirmationScreen(prompt.format(target=message_id)),
            lambda confirmed: (
                self._run_deletion(
                    domain.delete_message(message_id),
                    target=target,
                    intent=intent,
                )
                if confirmed
                else None
            ),
        )

    def _dispatch_navigation_intent(self, intent: InteractionIntent) -> bool:
        focused = self.focused
        if not isinstance(focused, TautOptionList):
            if intent is InteractionIntent.SURFACE_PREVIOUS:
                self._move_surface(-1)
                return True
            if intent is InteractionIntent.SURFACE_NEXT:
                self._move_surface(1)
                return True
            return False
        actions = {
            InteractionIntent.ITEM_PREVIOUS: focused.action_cursor_up,
            InteractionIntent.ITEM_NEXT: focused.action_cursor_down,
            InteractionIntent.ITEM_FIRST: focused.action_first,
            InteractionIntent.ITEM_LAST: focused.action_last,
            InteractionIntent.PAGE_UP: focused.action_page_up,
            InteractionIntent.PAGE_DOWN: focused.action_page_down,
            InteractionIntent.ACTIVATE_SELECTION: focused.action_select,
        }
        action = actions.get(intent)
        if action is not None:
            action()
            return True
        if intent is InteractionIntent.SURFACE_PREVIOUS:
            self._move_surface(-1)
            return True
        if intent is InteractionIntent.SURFACE_NEXT:
            self._move_surface(1)
            return True
        return False

    def _move_surface(self, direction: int) -> None:
        surfaces = [LogicalSurface.NAVIGATION, LogicalSurface.CONVERSATION]
        if self.visual_state.inspector is not None:
            surfaces.append(LogicalSurface.INSPECTOR)
        current = self.visual_state.focus.surface
        try:
            index = surfaces.index(current)
        except ValueError:
            index = 1
        selected = surfaces[max(0, min(len(surfaces) - 1, index + direction))]
        widget_ids = {
            LogicalSurface.NAVIGATION: "navigation-list",
            LogicalSurface.CONVERSATION: "transcript",
            LogicalSurface.INSPECTOR: "inspector-body",
        }
        self.visual_state = replace(
            self.visual_state,
            pane_choice=selected,
            focus=FocusTarget(selected, widget_ids[selected]),
        )
        self._apply_placement(self._accepted_size)
        self._focus_visual_target()
        if selected is LogicalSurface.CONVERSATION and self._message_rows:
            self.call_after_refresh(self._render_messages, self._message_rows)

    def _cycle_surface(self) -> None:
        surfaces = [LogicalSurface.NAVIGATION, LogicalSurface.CONVERSATION]
        if self.visual_state.inspector is not None:
            surfaces.append(LogicalSurface.INSPECTOR)
        placement = layout_placement(self._accepted_size, self.visual_state)
        current = (
            placement.visible_surfaces[0]
            if self.layout_mode is LayoutMode.COMPACT
            else self.visual_state.pane_choice
        )
        try:
            index = surfaces.index(current)
        except ValueError:
            index = 0
        selected = surfaces[(index + 1) % len(surfaces)]
        widget_ids = {
            LogicalSurface.NAVIGATION: "navigation-list",
            LogicalSurface.CONVERSATION: "transcript",
            LogicalSurface.INSPECTOR: "inspector-body",
        }
        self.visual_state = replace(
            self.visual_state,
            pane_choice=selected,
        )
        self._apply_placement(self._accepted_size)
        self.visual_state = replace(
            self.visual_state,
            focus=FocusTarget(selected, widget_ids[selected]),
        )
        self._focus_visual_target()
        if selected is LogicalSurface.CONVERSATION and self._message_rows:
            self.call_after_refresh(self._render_messages, self._message_rows)

    def _select_message(self, index: int) -> None:
        if not 0 <= index < len(self._message_rows):
            return
        message = self._message_rows[index]
        self.visual_state = replace(
            self.visual_state,
            selected_message_id=message.ts,
            inspector=InspectorState(
                InspectorKind.MESSAGE,
                selected_item=str(message.ts),
            ),
            pane_choice=LogicalSurface.INSPECTOR,
            focus=FocusTarget(LogicalSurface.INSPECTOR, "inspector-body"),
        )
        self._query_base("#inspector-body", TautStatic).update(
            display_text(
                (escape_inline_text(message.from_name), "bold"),
                f"  {message.ts}\n",
                escape_message_body(message.text),
                "\n\nReply · React · Delete",
            )
        )
        self._apply_placement(self._accepted_size)
        self._focus_visual_target()

    def _selected_reply_thread(self) -> str | None:
        target = self.visual_state.active_conversation
        message_id = self.visual_state.selected_message_id
        if target is None or message_id is None:
            return None
        return self._reply_threads.get((target, message_id))

    def _toggle_reply_surface(self) -> None:
        session = self._session
        target = self.visual_state.active_conversation
        if session is None or target is None:
            return
        current = self.visual_state.open_reply_thread
        reply_thread = self._selected_reply_thread()
        if current is None and reply_thread is None:
            return
        intent = self._advance_conversation_intent()
        self._watch_future(
            session.open_conversation(
                target,
                reply_thread=None if current is not None else reply_thread,
                intent_token=intent,
            ),
            lambda done: self._apply_optional_conversation(intent, done),
        )

    def _update_reply_affordance(self) -> None:
        try:
            button = self._query_base("#reply-affordance", TautButton)
        except NoMatches:
            return
        current = self.visual_state.open_reply_thread
        available = current is not None or self._selected_reply_thread() is not None
        button.display = available and self.layout_mode is not LayoutMode.TOO_SMALL
        button.label = "Close replies" if current is not None else "Replies"

    def _update_context_affordances(self) -> None:
        if self._base_screen is None:
            return
        usable = self.layout_mode is not LayoutMode.TOO_SMALL
        has_target = self.visual_state.active_conversation is not None
        has_message = self.visual_state.selected_message_id is not None and any(
            message.ts == self.visual_state.selected_message_id
            for message in self._message_rows
        )
        self._query_base("#composer-send", TautButton).display = usable and has_target
        self._query_base("#members-action", TautButton).display = usable and has_target
        for selector in ("#reply-action", "#react-action", "#delete-action"):
            self._query_base(selector, TautButton).display = usable and has_message
        self._query_base("#context-actions").display = usable and (
            has_target or has_message
        )

    def _render_reply_inspector(self, snapshot: ConversationSnapshot) -> None:
        parts: list[str] = [
            "Replies to ",
            escape_inline_text(snapshot.reply_thread or ""),
            "\n",
        ]
        if not snapshot.reply_messages:
            parts.append("No replies yet.")
        else:
            for index, message in enumerate(snapshot.reply_messages):
                if index:
                    parts.append("\n")
                parts.extend(
                    (
                        f"{message.ts}  ",
                        escape_inline_text(message.from_name),
                        "  ",
                        escape_message_body(message.text),
                    )
                )
        self._render_inspector(display_text(*parts), kind=InspectorKind.REPLIES)

    def _palette_entries(self) -> tuple[PaletteEntry, ...]:
        summon_available = self._summon is not None
        facts = self._current_action_applicability_facts()
        entries: list[PaletteEntry] = []
        for spec in available_action_specs(
            summon_available=summon_available,
            route=ActionRoute.PALETTE,
        ):
            applicability = evaluate_action_applicability(spec.action_id, facts)
            entries.append(
                PaletteEntry(
                    spec,
                    enabled=applicability.enabled,
                    reason=applicability.reason,
                    scope=self._palette_scope(spec.action_id),
                    gesture_hint=gesture_hint(spec.action_id),
                )
            )
        return tuple(entries)

    def _palette_scope(self, action_id: ActionId) -> str:
        if action_id in {
            ActionId.CHANNEL_LEAVE,
            ActionId.MEMBERS_OPEN,
            ActionId.CHANNEL_SHOW_TOPIC,
            ActionId.CHANNEL_SET_TOPIC,
            ActionId.CHANNEL_CLEAR_TOPIC,
            ActionId.CHANNEL_RENAME,
            ActionId.COMPOSE_ENTER,
            ActionId.MESSAGE_SEND,
            ActionId.MESSAGE_REPLY,
            ActionId.MESSAGE_REACT,
            ActionId.MESSAGE_DELETE,
        }:
            target = self.visual_state.active_conversation
            if target is not None:
                return self._target_labels.get(target, target)
        return action_spec(action_id).family.value

    def _complete_palette(self, action_id: ActionId | None) -> None:
        self._set_mode(InteractionMode.NORMAL)
        if action_id is not None:
            self._dispatch_tui_action(action_id, source=ActionRoute.PALETTE)

    def _complete_search(self, result: object | None) -> None:
        self._set_mode(InteractionMode.NORMAL)
        if result is None:
            return
        if not isinstance(result, SearchHit):
            self._show_error("Search returned an unsupported result.")
            return
        self._selected_search_hit = result
        self._dispatch_tui_action(
            ActionId.SEARCH_OPEN_RESULT,
            source=ActionRoute.CONTEXT,
        )

    def _complete_form(
        self,
        submission: FormSubmission,
        *,
        screen: NativeFormScreen,
    ) -> None:
        domain = self._domain
        if domain is None:
            screen.show_domain_error("The Taut session is still starting.")
            return
        if self._complete_identity_form(submission, domain, screen=screen):
            return
        if self._complete_conversation_form(submission, domain, screen=screen):
            return
        if self._complete_message_form(submission, domain, screen=screen):
            return
        self._complete_system_form(submission, domain, screen=screen)

    def _complete_identity_form(
        self,
        submission: FormSubmission,
        domain: TuiDomainActions,
        *,
        screen: NativeFormScreen,
    ) -> bool:
        values = submission.values
        action_id = submission.action_id
        if action_id is ActionId.IDENTITY_REJOIN:
            self._run_form_action(
                screen,
                domain.rejoin_identity(
                    values["name_or_alias"] or None,
                    token=values["continuity_token"] or None,
                ),
                refresh_navigation=True,
            )
        elif action_id is ActionId.IDENTITY_SET_NAME:
            self._run_form_action(screen, domain.set_name(values["name"]))
        elif action_id is ActionId.IDENTITY_SET_PERSONA:
            self._run_form_action(
                screen,
                domain.set_persona(values["persona"] or None),
            )
        else:
            return False
        return True

    def _complete_conversation_form(
        self,
        submission: FormSubmission,
        domain: TuiDomainActions,
        *,
        screen: NativeFormScreen,
    ) -> bool:
        values = submission.values
        action_id = submission.action_id
        if action_id is ActionId.CHANNEL_JOIN:
            self._run_form_action(
                screen,
                domain.join_channel(values["channel"]),
                refresh_navigation=True,
            )
        elif action_id is ActionId.DIRECT_MESSAGE_START:
            self._run_form_action(
                screen,
                domain.start_direct_message(values["member"], values["message"]),
                refresh_navigation=True,
            )
        elif action_id is ActionId.CHANNEL_SET_TOPIC:
            self._with_active_target(
                lambda target: self._run_form_action(
                    screen,
                    domain.set_topic(target, values["topic"]),
                )
            )
        elif action_id is ActionId.CHANNEL_RENAME:
            self._confirm_context_action(
                action_id,
                self.visual_state.active_conversation,
                lambda target: self._run_form_action(
                    screen,
                    domain.rename_channel(target, values["new_name"]),
                    refresh_navigation=True,
                ),
                cancelled_action=screen.resume,
            )
        else:
            return False
        return True

    def _complete_message_form(
        self,
        submission: FormSubmission,
        domain: TuiDomainActions,
        *,
        screen: NativeFormScreen,
    ) -> bool:
        values = submission.values
        action_id = submission.action_id
        if action_id is ActionId.MESSAGE_REPLY:
            self._with_selected_message(
                lambda target, message_id: self._run_form_action(
                    screen,
                    domain.reply_message(target, message_id, values["message"]),
                    refresh_navigation=True,
                )
            )
        elif action_id is ActionId.MESSAGE_REACT:
            message_id = self.visual_state.selected_message_id
            if message_id is None:
                self._show_error("Select a message first.")
            else:
                self._run_form_action(
                    screen,
                    domain.react_message(message_id, values["reaction"]),
                )
        else:
            return False
        return True

    def _complete_system_form(
        self,
        submission: FormSubmission,
        domain: TuiDomainActions,
        *,
        screen: NativeFormScreen,
    ) -> bool:
        values = submission.values
        action_id = submission.action_id
        if action_id is ActionId.SYSTEM_DUMP:
            output = Path(values["output_path"])
            if output.exists():
                prompt = action_spec(action_id).confirmation_prompt
                assert prompt is not None
                self.push_screen(
                    ConfirmationScreen(prompt.format(target=output)),
                    lambda confirmed: (
                        self._run_form_action(
                            screen, domain.dump(output, replace_confirmed=True)
                        )
                        if confirmed
                        else screen.resume()
                    ),
                )
            else:
                self._run_form_action(screen, domain.dump(output))
        elif action_id is ActionId.SYSTEM_LOAD_HELP:
            screen.complete()
            self._render_inspector(domain.load_help(values["input_path"]))
        else:
            return False
        return True

    def _confirm_context_action(
        self,
        action_id: ActionId,
        target: str | None,
        confirmed_action: Callable[[str], None],
        cancelled_action: Callable[[], None] | None = None,
    ) -> None:
        if target is None:
            self._show_error("Select a conversation first.")
            return
        prompt = action_spec(action_id).confirmation_prompt
        assert prompt is not None
        self.push_screen(
            ConfirmationScreen(prompt.format(target=target)),
            lambda confirmed: (
                confirmed_action(target)
                if confirmed
                else (cancelled_action() if cancelled_action is not None else None)
            ),
        )

    def _with_active_target(self, action: Callable[[str], None]) -> None:
        target = self.visual_state.active_conversation
        if target is None:
            self._show_error("Select a conversation first.")
        else:
            action(target)

    def _with_selected_message(
        self,
        action: Callable[[str, int], None],
    ) -> None:
        target = self.visual_state.active_conversation
        message_id = self.visual_state.selected_message_id
        if target is None or message_id is None:
            self._show_error("Select a message first.")
        else:
            action(target, message_id)

    def _set_mode(self, mode: InteractionMode) -> None:
        self.visual_state = replace(self.visual_state, mode=mode)
        self._update_status()

    def _apply_placement(self, size: TerminalSize) -> None:
        placement = layout_placement(size, self.visual_state)
        self.layout_mode = placement.mode
        visible = set(placement.visible_surfaces)
        widgets = {
            LogicalSurface.NAVIGATION: self._query_base("#navigation"),
            LogicalSurface.CONVERSATION: self._query_base("#conversation"),
            LogicalSurface.INSPECTOR: self._query_base("#inspector"),
            LogicalSurface.RESIZE_HINT: self._query_base("#resize-hint"),
        }
        for surface, widget in widgets.items():
            widget.display = surface in visible
        self._query_base("#status-bar").display = (
            placement.mode is not LayoutMode.TOO_SMALL
        )
        self._query_base("#pane-affordance").display = (
            placement.mode is LayoutMode.COMPACT
        )
        self._update_reply_affordance()
        self._update_context_affordances()
        for region in placement.regions:
            if region.surface is not LogicalSurface.RESIZE_HINT:
                widgets[region.surface].styles.width = region.columns

    def _focus_visual_target(self) -> None:
        widget_id = self.visual_state.focus.widget_id
        aliases = {
            "navigation": "navigation-list",
            "inspector": "inspector-body",
        }
        widget_id = aliases.get(widget_id, widget_id)
        try:
            widget = self._query_base(f"#{widget_id}")
        except NoMatches:
            widget = self._query_base("#transcript")
        if widget.display:
            widget.focus()

    def _update_status(self) -> None:
        raw_target = self.visual_state.active_conversation
        target = (
            "no target"
            if raw_target is None
            else self._target_labels.get(raw_target, raw_target)
        )
        self._query_base("#status-line", TautStatic).update(
            f"{self.visual_state.mode.value}  {target}  {self._operation_state}"
        )

    def _watch_future(
        self,
        future: Future[_ResultT],
        apply: Callable[[Future[_ResultT]], None],
    ) -> None:
        def completed(done: Future[_ResultT]) -> None:
            if self._shutting_down:
                return

            def apply_if_running() -> None:
                base_screen = self._base_screen
                if self._shutting_down:
                    return
                if base_screen is not None:
                    if not base_screen.is_attached:
                        return
                    try:
                        base_screen.query_one("#workspace")
                    except NoMatches:
                        return
                try:
                    apply(done)
                except NoMatches:
                    # The screen may detach between the readiness probe above
                    # and a queued presentation callback. Domain work already
                    # completed; teardown owns this missing-widget boundary.
                    return

            try:
                self.call_later(apply_if_running)
            except Exception:  # noqa: BLE001 approved [DOM-10.2.1] [RUFF-SUP-086] exception
                return

        future.add_done_callback(completed)

    def _run_action(
        self,
        future: Future[_ResultT],
        *,
        refresh_navigation: bool = False,
    ) -> None:
        self._operation_state = "working"
        self._update_status()
        self._watch_future(
            future,
            lambda done: self._apply_action_result(
                done,
                refresh_navigation=refresh_navigation,
            ),
        )

    def _run_form_action(
        self,
        screen: NativeFormScreen,
        future: Future[_ResultT],
        *,
        refresh_navigation: bool = False,
    ) -> None:
        self._operation_state = "working"
        self._update_status()
        self._watch_future(
            future,
            lambda done: self._apply_form_action_result(
                screen,
                done,
                refresh_navigation=refresh_navigation,
            ),
        )

    def _apply_form_action_result(
        self,
        screen: NativeFormScreen,
        future: Future[_ResultT],
        *,
        refresh_navigation: bool,
    ) -> None:
        self._operation_state = "idle"
        try:
            result = future.result()
        except Exception as exc:  # noqa: BLE001 approved [DOM-10.2.1] [RUFF-SUP-085] exception
            screen.show_domain_error(str(exc) or type(exc).__name__)
            self._update_status()
            return
        screen.complete()
        if isinstance(result, Message):
            snapshot = (
                self._session.commit_returned_message(result)
                if self._session is not None
                else None
            )
            if snapshot is not None:
                self._apply_conversation(snapshot)
        self._render_domain_result(result)
        if refresh_navigation and self._session is not None:
            self._watch_future(
                self._session.refresh_navigation(),
                self._apply_navigation_result,
            )
        self._update_status()

    def _apply_action_result(
        self,
        future: Future[_ResultT],
        *,
        refresh_navigation: bool,
    ) -> None:
        self._operation_state = "idle"
        try:
            result = future.result()
        except Exception as exc:  # noqa: BLE001 approved [DOM-10.2.1] [RUFF-SUP-085] exception
            self._show_error(str(exc) or type(exc).__name__)
            self._update_status()
            return
        if isinstance(result, Message):
            snapshot = (
                self._session.commit_returned_message(result)
                if self._session is not None
                else None
            )
            if snapshot is not None:
                self._apply_conversation(snapshot)
        self._render_domain_result(result)
        if refresh_navigation and self._session is not None:
            self._watch_future(
                self._session.refresh_navigation(),
                self._apply_navigation_result,
            )
        self._update_status()

    def _render_domain_result(self, result: object) -> None:
        formatter = _RESULT_FORMATTERS.get(type(result))
        if formatter is not None:
            self._render_inspector(formatter(result))
        elif isinstance(result, (list, tuple)):
            text = (
                "No results" if not result else "\n".join(map(_safe_projection, result))
            )
            self._render_inspector(text)
        else:
            self._render_inspector(_safe_projection(result))

    def _run_deletion(
        self,
        future: Future[MessageDeletion],
        *,
        target: str | None,
        intent: int,
    ) -> None:
        self._operation_state = "working"
        self._update_status()
        self._watch_future(
            future,
            lambda done: self._apply_deletion_result(
                done,
                target=target,
                intent=intent,
            ),
        )

    def _apply_deletion_result(
        self,
        future: Future[MessageDeletion],
        *,
        target: str | None,
        intent: int,
    ) -> None:
        self._operation_state = "idle"
        try:
            result = future.result()
        except Exception as exc:  # noqa: BLE001 approved [DOM-10.2.1] [RUFF-SUP-085] exception
            self._show_error(str(exc) or type(exc).__name__)
            self._update_status()
            return
        self._render_domain_result(result)
        self._refresh_after_deletion(target=target, intent=intent)
        self._update_status()

    def _refresh_after_deletion(self, *, target: str | None, intent: int) -> None:
        session = self._session
        if (
            target is None
            or session is None
            or intent != self._conversation_intent
            or self.visual_state.active_conversation != target
        ):
            return
        self._watch_future(
            session.open_conversation(
                target,
                reply_thread=self.visual_state.open_reply_thread,
                intent_token=intent,
            ),
            lambda done: self._apply_optional_conversation(intent, done),
        )

    def _render_inspector(
        self,
        text: str | DisplayText,
        *,
        kind: InspectorKind = InspectorKind.SYSTEM,
        style: str | None = None,
        reveal: bool | None = None,
    ) -> None:
        should_reveal = (
            self.visual_state.mode is InteractionMode.NORMAL
            if reveal is None
            else reveal
        )
        self.visual_state = replace(
            self.visual_state,
            inspector=InspectorState(kind),
            pane_choice=(
                LogicalSurface.INSPECTOR
                if should_reveal
                else self.visual_state.pane_choice
            ),
            focus=(
                FocusTarget(LogicalSurface.INSPECTOR, "inspector-body")
                if should_reveal
                else self.visual_state.focus
            ),
        )
        self._apply_placement(self._accepted_size)
        rendered = text
        if style is not None:
            if not isinstance(text, str):
                raise TypeError("styled inspector input must be a plain string")
            rendered = display_text((text, style))
        self._query_base("#inspector-body", TautStatic).update(rendered)
        if should_reveal:
            self._focus_visual_target()

    def _render_notifications(self, notifications: tuple[Notification, ...]) -> None:
        if not notifications:
            self._render_inspector(
                "No notifications claimed this session.",
                kind=InspectorKind.NOTIFICATIONS,
            )
            return
        lines = ["Claimed notification pointers"]
        for notification in notifications:
            lines.append(
                f"{notification.type}  {notification.actor_name or 'unknown'}  "
                f"{notification.thread or ''}"
            )
        self._render_inspector("\n".join(lines), kind=InspectorKind.NOTIFICATIONS)

    def _open_selected_search_result(self) -> None:
        domain = self._domain
        hit = self._selected_search_hit
        if domain is None or hit is None:
            self._show_error("Select a search result first.")
            return
        self._operation_state = "searching"
        intent = self._advance_conversation_intent(reset_search=False)
        self._search_hits_by_intent[intent] = hit
        self._update_status()
        self._watch_future(
            domain.open_search_result(hit),
            lambda done: self._apply_search_context(intent, done),
        )

    def _apply_search_context(
        self,
        intent: int,
        future: Future[list[Message]],
    ) -> None:
        if intent != self._conversation_intent:
            self._search_hits_by_intent.pop(intent, None)
            return
        self._operation_state = "idle"
        try:
            messages = tuple(future.result())
        except Exception as exc:  # noqa: BLE001 approved [DOM-10.2.1] [RUFF-SUP-085] exception
            self._show_error(str(exc) or type(exc).__name__)
            self._update_status()
            return
        hit = self._search_hits_by_intent.pop(intent, None)
        session = self._session
        if hit is None or session is None or intent != self._conversation_intent:
            return
        self.visual_state = replace(
            self.visual_state,
            scroll_anchor=ScrollAnchor.history(hit.ts),
        )
        self._watch_future(
            session.open_history_context(
                hit.thread,
                messages,
                intent_token=intent,
            ),
            lambda done: self._apply_optional_conversation(intent, done),
        )

    def _advance_conversation_intent(self, *, reset_search: bool = True) -> int:
        self._conversation_intent += 1
        if reset_search and self._operation_state == "searching":
            self._operation_state = "idle"
            self._update_status()
        return self._conversation_intent

    def _accept_summon_log_from_worker(self, message: str) -> None:
        try:
            self.call_later(
                self._apply_summon_log,
                message,
            )
        except Exception:  # noqa: BLE001 approved [DOM-10.2.1] [RUFF-SUP-086] exception
            return

    def _apply_summon_log(self, message: str) -> None:
        try:
            self._render_inspector(
                display_text("Summon\n", message),
                kind=InspectorKind.SUMMON,
            )
        except BaseException:  # noqa: BLE001 approved [DOM-10.2.1] [RUFF-SUP-087] exception
            return

    def _accept_summon_ready_from_worker(self, run: OwnedSummonRun) -> None:
        try:
            self.call_later(
                self._apply_summon_ready,
                run,
            )
        except Exception:  # noqa: BLE001 approved [DOM-10.2.1] [RUFF-SUP-086] exception
            return

    def _apply_summon_ready(self, run: OwnedSummonRun) -> None:
        if run.token not in self._owned_summon_tokens:
            return
        if run.member_name is not None:
            self._summon_names[run.token] = run.member_name
        try:
            self._operation_state = "summon live"
            self._render_inspector(
                f"Summon ready\n{_safe_projection(run)}",
                kind=InspectorKind.SUMMON,
            )
            self._update_status()
        except BaseException:  # noqa: BLE001 approved [DOM-10.2.1] [RUFF-SUP-087] exception
            return

    def _complete_owned_exit(self, confirmed: bool | None) -> None:
        self._owned_exit_confirmation_open = False
        if not confirmed:
            return
        summon = self._summon
        if summon is None:
            self.exit()
            return
        self._operation_state = "stopping summoned members"
        self._update_status()
        self._watch_future(
            summon.stop_owned_and_wait(),
            self._apply_owned_exit_result,
        )

    def _apply_owned_exit_result(
        self,
        future: Future[OwnedSummonShutdown],
    ) -> None:
        self._operation_state = "idle"
        try:
            result = future.result()
        except Exception as exc:  # noqa: BLE001 approved [DOM-10.2.1] [RUFF-SUP-085] exception
            self._show_error(str(exc) or type(exc).__name__)
            self._update_status()
            return
        if result.complete:
            self.exit()
            return
        details = [
            f"{failure.member_name or failure.token}: {failure.error}"
            for failure in result.errors
        ]
        details.extend(
            f"{run.member_name or run.token} did not stop" for run in result.unresolved
        )
        self._show_error("; ".join(details) or "Summon shutdown did not complete.")
        self._update_status()

    def _apply_navigation_result(
        self,
        future: Future[NavigationSnapshot],
    ) -> None:
        try:
            result = future.result()
        except NotInitializedError:
            self._set_navigation_actions(
                (ActionId.WORKSPACE_INITIALIZE,),
                ("Initialize this workspace",),
            )
            return
        except IdentityError:
            self._set_navigation_actions(
                (ActionId.CHANNEL_JOIN, ActionId.IDENTITY_REJOIN),
                ("Join a channel", "Rejoin an existing identity"),
            )
            return
        except TautError as exc:
            self._show_error(str(exc))
            return
        except Exception as exc:  # noqa: BLE001 approved [DOM-10.2.1] [RUFF-SUP-085] exception
            self._show_error(str(exc) or type(exc).__name__)
            return
        labels: list[str] = []
        targets: list[str | ActionId] = []
        target_labels: dict[str, str] = {}
        target_kinds: dict[str, str] = {}
        reply_threads: dict[tuple[str, int], str] = {}
        for thread in result.channels:
            marker = "*" if thread.unread else " "
            count = f" {thread.unread_count}" if thread.unread_count else ""
            labels.append(f"{marker} #{thread.name}{count}")
            targets.append(thread.name)
            target_labels[thread.name] = f"#{thread.name}"
            target_kinds[thread.name] = thread.kind
        for thread in result.direct_messages:
            marker = "*" if thread.unread else " "
            labels.append(f"{marker} {thread.display_name or 'Direct message'}")
            targets.append(thread.name)
            target_labels[thread.name] = thread.display_name or "Direct message"
            target_kinds[thread.name] = thread.kind
        for thread in result.subthreads:
            parsed = parse_target(thread.name, allow_dm=False)
            if parsed.channel is not None and parsed.origin_ts is not None:
                reply_threads[(parsed.channel, parsed.origin_ts)] = thread.name
        labels.extend(("  Notifications", "  Join channel", "  Start direct message"))
        targets.extend(
            (
                ActionId.NOTIFICATIONS_OPEN,
                ActionId.CHANNEL_JOIN,
                ActionId.DIRECT_MESSAGE_START,
            )
        )
        self._target_labels = target_labels
        self._target_kinds = target_kinds
        self._reply_threads = reply_threads
        self._set_navigation_actions(tuple(targets), tuple(labels))
        if self._message_rows:
            self._render_messages(self._message_rows)

    def _set_navigation_actions(
        self,
        targets: tuple[str | ActionId, ...],
        labels: tuple[str, ...],
    ) -> None:
        navigation = self._query_base("#navigation-list", TautOptionList)
        navigation.clear_options()
        navigation.add_options(labels)
        self._navigation_targets = list(targets)

    def _commit_conversation_from_worker(
        self,
        snapshot: ConversationSnapshot,
    ) -> bool:
        if self._shutting_down:
            return False
        if (
            snapshot.intent_token is not None
            and snapshot.intent_token != self._conversation_intent
        ):
            return False
        try:
            return bool(self.call_from_thread(self._apply_conversation, snapshot))
        except RuntimeError:
            return False

    def _accept_delivery_from_worker(
        self,
        generation: int,
        item: Delivery,
    ) -> bool:
        if self._shutting_down:
            return False
        try:
            return bool(self.call_from_thread(self._apply_delivery, generation, item))
        except RuntimeError:
            return False

    def _report_watcher_degraded_from_worker(
        self, generation: int, detail: str
    ) -> None:
        if self._shutting_down:
            return
        try:
            self.call_from_thread(self._apply_watcher_degraded, generation, detail)
        except RuntimeError:
            return

    def _apply_watcher_degraded(self, generation: int, detail: str) -> None:
        if generation != self.visual_state.model_generation:
            return
        self._operation_state = f"live updates stopped: {detail}"
        self._update_status()

    def _apply_optional_conversation(
        self,
        intent: int,
        future: Future[ConversationSnapshot | None],
    ) -> None:
        if intent != self._conversation_intent:
            return
        try:
            result = future.result()
        except Exception as exc:  # noqa: BLE001 approved [DOM-10.2.1] [RUFF-SUP-085] exception
            self._show_error(str(exc) or type(exc).__name__)
            return
        if result is not None and intent == self._conversation_intent:
            self._apply_conversation(result)

    def _apply_send_result(
        self,
        send_token: int,
        future: Future[Message],
    ) -> None:
        pending = self._pending_sends.pop(send_token, None)
        try:
            message = future.result()
        except Exception as exc:  # noqa: BLE001 approved [DOM-10.2.1] [RUFF-SUP-085] exception
            detail = str(exc) or type(exc).__name__
            pending_suffix = (
                f"; {len(self._pending_sends)} send(s) pending"
                if self._pending_sends
                else ""
            )
            self._operation_state = f"send failed: {detail}{pending_suffix}"
            self._show_error(detail)
            self._update_status()
            return
        session = self._session
        snapshot = session.commit_returned_message(message) if session else None
        if snapshot is not None:
            self._apply_conversation(snapshot)
        composer = self._query_base("#composer", TautComposer)
        if pending is not None:
            target, revision = pending
            draft = self.visual_state.draft_for(target)
            if (
                message.thread == target
                and draft is not None
                and draft.revision == revision
            ):
                self.visual_state = self.visual_state.with_draft(
                    DraftState(target=target, revision=revision + 1)
                )
                if self.visual_state.active_conversation == target:
                    composer.text = ""
        self._operation_state = "sending" if self._pending_sends else "idle"
        self._update_status()

    def _apply_conversation(self, snapshot: ConversationSnapshot) -> bool:
        selected = self.visual_state.selected_message_id
        if selected is not None and not any(
            message.ts == selected for message in snapshot.messages
        ):
            selected = None
        self.visual_state = replace(
            self.visual_state,
            active_conversation=snapshot.target,
            open_reply_thread=snapshot.reply_thread,
            selected_message_id=selected,
            model_generation=snapshot.generation,
        )
        target_label = self._target_labels.get(snapshot.target, snapshot.target)
        self._query_base("#target-header", TautStatic).update(target_label)
        self._render_messages(snapshot.messages)
        if snapshot.reply_thread is not None:
            self._render_reply_inspector(snapshot)
        elif (
            self.visual_state.inspector is not None
            and self.visual_state.inspector.kind is InspectorKind.REPLIES
        ):
            self.visual_state = replace(
                self.visual_state,
                inspector=None,
                pane_choice=LogicalSurface.CONVERSATION,
                focus=FocusTarget(LogicalSurface.CONVERSATION, "transcript"),
            )
            self._apply_placement(self._accepted_size)
            self._focus_visual_target()
        draft = self.visual_state.draft_for(snapshot.target)
        composer = self._query_base("#composer", TautComposer)
        composer.placeholder = f"Message {target_label}"
        composer.text = "" if draft is None else draft.text
        if draft is not None:
            composer.cursor_position = draft.cursor_position
        self._update_status()
        return True

    def _apply_delivery(self, generation: int, item: Delivery) -> bool:
        if isinstance(item, Notification):
            if (
                self.visual_state.inspector is not None
                and self.visual_state.inspector.kind is InspectorKind.NOTIFICATIONS
            ):
                notifications = (
                    self._session.notification_feed() if self._session else ()
                )
                self._render_notifications(notifications)
            if self._session is not None:
                self._watch_future(
                    self._session.refresh_navigation(),
                    self._apply_navigation_result,
                )
            return True
        if generation != self.visual_state.model_generation:
            return False
        session = self._session
        snapshot = session.conversation_snapshot() if session is not None else None
        if snapshot is None:
            return False
        self._capture_scroll_anchor()
        self._render_messages(snapshot.messages)
        if snapshot.reply_thread is not None:
            self._render_reply_inspector(snapshot)
        return True

    def _render_messages(self, messages: tuple[Message, ...]) -> None:
        transcript = self._query_base("#transcript", TautOptionList)
        transcript.clear_options()
        self._message_rows = messages
        for message in messages:
            transcript.add_option(self._message_prompt(message))
        if messages:
            anchor = self.visual_state.scroll_anchor
            highlighted = next(
                (
                    index
                    for index, message in enumerate(messages)
                    if message.ts == self.visual_state.selected_message_id
                ),
                len(messages) - 1,
            )
            transcript.highlighted = highlighted
            if anchor.tail_pinned:
                transcript.scroll_end(animate=False)
            elif anchor.message_id is not None:
                anchor_index = next(
                    (
                        index
                        for index, message in enumerate(messages)
                        if message.ts == anchor.message_id
                    ),
                    highlighted,
                )
                transcript.highlighted = anchor_index
                self.call_after_refresh(
                    self._restore_transcript_anchor,
                    messages,
                    anchor_index,
                    anchor.intra_row_offset,
                )
        self._update_context_affordances()

    def _capture_scroll_anchor(self) -> None:
        if not self._message_rows:
            return
        transcript = self._query_base("#transcript", TautOptionList)
        if transcript.is_vertical_scroll_end:
            anchor = ScrollAnchor.tail()
        else:
            width = max(1, transcript.scrollable_content_region.width)
            line = int(transcript.scroll_offset.y)
            option_index = 0
            intra_row = line
            for index, message in enumerate(self._message_rows):
                height = self._message_row_height(message, width)
                if intra_row < height:
                    option_index = index
                    break
                intra_row -= height
            else:
                option_index = len(self._message_rows) - 1
                intra_row = 0
            anchor = ScrollAnchor.history(
                self._message_rows[option_index].ts,
                intra_row_offset=intra_row,
            )
        self.visual_state = replace(self.visual_state, scroll_anchor=anchor)

    def _message_prompt(self, message: Message) -> DisplayText:
        target = self.visual_state.active_conversation
        reply_marker = (
            "  ↳ replies"
            if target is not None and (target, message.ts) in self._reply_threads
            else ""
        )
        if self.layout_mode is LayoutMode.COMPACT:
            return display_text(
                (escape_inline_text(message.from_name), "bold"),
                f"  {message.ts}",
                (reply_marker, "italic"),
                "\n",
                escape_message_body(message.text),
                "\n",
            )
        return display_text(
            (str(message.ts), "dim"),
            "  ",
            (escape_inline_text(message.from_name), "bold"),
            "  ",
            escape_message_body(message.text),
            (reply_marker, "italic"),
            "\n",
        )

    def _message_row_height(self, message: Message, width: int) -> int:
        return max(1, len(self._message_prompt(message).wrap(self.console, width)))

    def _restore_transcript_anchor(
        self,
        messages: tuple[Message, ...],
        anchor_index: int,
        intra_row_offset: int,
    ) -> None:
        transcript = self._query_base("#transcript", TautOptionList)
        width = max(1, transcript.scrollable_content_region.width)
        row_height = self._message_row_height(messages[anchor_index], width)
        bounded_offset = min(intra_row_offset, row_height - 1)
        anchor = self.visual_state.scroll_anchor
        if (
            not anchor.tail_pinned
            and anchor.message_id == messages[anchor_index].ts
            and anchor.intra_row_offset != bounded_offset
        ):
            self.visual_state = replace(
                self.visual_state,
                scroll_anchor=ScrollAnchor.history(
                    anchor.message_id,
                    intra_row_offset=bounded_offset,
                ),
            )
        y = (
            sum(
                self._message_row_height(message, width)
                for message in messages[:anchor_index]
            )
            + bounded_offset
        )
        transcript.scroll_to(y=y, animate=False, force=True)

    def _show_empty_action(self, action_id: ActionId) -> None:
        self._dispatch_tui_action(action_id, source=ActionRoute.NAVIGATION)

    def _show_error(self, message: str) -> None:
        self._render_inspector(
            message,
            kind=InspectorKind.SYSTEM,
            style="bold red",
        )


def _safe_projection(value: object) -> str:
    """Project extension/core values without exposing token-like fields."""

    name = getattr(value, "name", None)
    provider = getattr(value, "provider", None)
    session = getattr(value, "provider_session_id", None)
    driver = getattr(value, "driver", None)
    thread_count = getattr(value, "thread_count", None)
    cursor_lag = getattr(value, "cursor_lag", None)
    details = getattr(value, "details", None)
    if (
        name is not None
        and provider is not None
        and driver is not None
        and isinstance(thread_count, int)
        and isinstance(cursor_lag, dict)
        and isinstance(details, dict)
    ):
        lag = (
            ", ".join(
                f"#{thread}:{count}" for thread, count in sorted(cursor_lag.items())
            )
            if cursor_lag
            else "caught up"
        )
        detail = " ".join(f"{key}={item}" for key, item in sorted(details.items()))
        suffix = f"\n{detail}" if detail else ""
        return (
            f"Summon status\n{name}\nprovider={provider}  driver={driver}\n"
            f"session={session or '-'}  threads={thread_count}\nlag={lag}{suffix}"
        )
    member_id = getattr(value, "member_id", None)
    if name is not None and provider is not None and member_id is not None:
        return f"{name}  {provider}  live  session={session or '-'}"
    member_name = getattr(value, "member_name", None)
    if member_name is not None:
        return str(member_name)
    if name is not None:
        return str(name)
    path = getattr(value, "path", None)
    if path is not None:
        return str(path)
    if isinstance(value, (str, int, float, bool)):
        return str(value)
    return type(value).__name__


def _surface_for_widget(widget_id: str | None) -> LogicalSurface | None:
    if widget_id == "navigation-list":
        return LogicalSurface.NAVIGATION
    if widget_id in {"transcript", "composer", "composer-send"}:
        return LogicalSurface.CONVERSATION
    if widget_id in {
        "inspector-body",
        "members-action",
        "reply-action",
        "react-action",
        "delete-action",
    }:
        return LogicalSurface.INSPECTOR
    return None


def _format_member(value: object) -> str:
    assert isinstance(value, Member)
    return f"Identity\n{value.name}\n{value.presence}\n{value.persona or 'no persona'}"


def _format_channel(value: object) -> str:
    assert isinstance(value, Channel)
    return f"#{value.name}\nTopic: {value.topic or '(not set)'}"


def _format_thread(value: object) -> str:
    assert isinstance(value, Thread)
    return f"Conversation\n{value.display_name or value.name}"


def _format_doctor(value: object) -> str:
    assert isinstance(value, DoctorReport)
    lines = ["System doctor", "healthy" if value.healthy else "findings"]
    lines.extend(
        f"{check.status.upper()}  {check.name}: {check.detail}"
        for check in value.checks
    )
    return "\n".join(lines)


def _format_dump(value: object) -> str:
    assert isinstance(value, DumpReport)
    return (
        f"Dump complete\n{value.path}\n"
        f"{value.queues} queues · {value.messages} messages"
    )


def _format_init(value: object) -> str:
    assert isinstance(value, InitResult)
    state = "created" if value.created else "already exists"
    return f"Workspace {state}\n{value.db}"


def _format_reaction(value: object) -> str:
    assert isinstance(value, MessageReaction)
    return f"Reaction {value.reaction} added to {value.message_ts}"


def _format_deletion(value: object) -> str:
    assert isinstance(value, MessageDeletion)
    return f"Deleted message {value.ts}"


_RESULT_FORMATTERS: dict[type[object], Callable[[object], str]] = {
    Member: _format_member,
    Channel: _format_channel,
    Thread: _format_thread,
    DoctorReport: _format_doctor,
    DumpReport: _format_dump,
    InitResult: _format_init,
    MessageReaction: _format_reaction,
    MessageDeletion: _format_deletion,
}


__all__ = ["TautApp"]
