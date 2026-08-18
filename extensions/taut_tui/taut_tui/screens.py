"""Native modal surfaces for typed actions, confirmation, and search.

These screens collect visual input and return typed values. They never call
core, parse argv, or decide domain validity.

Spec references:
- docs/specs/10-taut-tui.md [TUI-7], [TUI-8.2]
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from concurrent.futures import Future
from dataclasses import dataclass
from typing import ClassVar, TypeVar

from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical
from textual.message import Message as TextualMessage
from textual.screen import ModalScreen
from textual.suggester import Suggester
from textual.widgets.option_list import Option

from taut.commands.syntax import (
    CommandInput,
    CommandInvocation,
    CommandSyntax,
    CommandSyntaxError,
    RootCommandSyntax,
    command_nodes,
    format_command_syntax,
    parse_command_line,
)
from taut_tui.actions import ActionId, ActionSpec
from taut_tui.forms import FieldKind, FormSpec, validate_visual_input
from taut_tui.widgets import TautButton as Button
from taut_tui.widgets import TautCheckbox as Checkbox
from taut_tui.widgets import TautInput as Input
from taut_tui.widgets import TautLabel as Label
from taut_tui.widgets import TautOptionList as OptionList
from taut_tui.widgets import TautSelect as Select
from taut_tui.widgets import TautStatic as Static


@dataclass(frozen=True, slots=True)
class FormSubmission:
    action_id: ActionId
    values: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class PaletteEntry:
    action: ActionSpec
    enabled: bool = True
    reason: str | None = None
    scope: str | None = None
    gesture_hint: str | None = None

    def __post_init__(self) -> None:
        if self.enabled and self.reason is not None:
            raise ValueError("enabled palette entries cannot have a disabled reason")
        if not self.enabled and not self.reason:
            raise ValueError("disabled palette entries require a reason")


@dataclass(frozen=True, slots=True)
class CommandLineSubmission:
    invocation: CommandInvocation


@dataclass(frozen=True, slots=True)
class PaletteCommandHandoff:
    """Browser query recognized as a command; open the command line with it."""

    query: str


@dataclass(frozen=True, slots=True)
class SummonStartSubmission:
    name: str
    threads: tuple[str, ...]
    provider: str | None
    persona: str | None
    system_prompt_file: str | None
    rate_limit: int | None
    terminal: bool
    attach: bool
    detach: bool
    takeover: bool


@dataclass(frozen=True, slots=True)
class NamedActionSubmission:
    action_id: ActionId
    name: str


_ResultT = TypeVar("_ResultT")


class _TautModalScreen(ModalScreen[_ResultT]):
    CSS = """
    _TautModalScreen {
        align: center middle;
        background: $background 55%;
    }

    .taut-modal {
        width: 76;
        max-width: 92%;
        height: auto;
        max-height: 90%;
        padding: 1 2;
        background: $surface;
        border-left: tall $accent;
    }

    .modal-title {
        height: 2;
        text-style: bold;
    }

    .field-label { height: 1; color: $text-muted; }
    .form-field { margin-bottom: 1; }
    #form-errors { height: auto; color: $error; margin-bottom: 1; }
    #form-controls { height: 3; align-horizontal: right; }
    #form-controls Button { margin-left: 1; }
    #palette-query { margin-bottom: 1; }
    #palette-results { height: 14; }
    .disabled-reason { color: $text-muted; }
    """


class NativeFormScreen(_TautModalScreen[FormSubmission | None]):
    """Render one closed FormSpec with ordinary focus and mouse behavior."""

    class Submitted(TextualMessage):
        def __init__(
            self, screen: NativeFormScreen, submission: FormSubmission
        ) -> None:
            super().__init__()
            self.screen = screen
            self.submission = submission

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "cancel", "Cancel", show=False),
    ]

    def __init__(self, form: FormSpec) -> None:
        super().__init__()
        self.form = form

    def compose(self) -> ComposeResult:
        with Vertical(classes="taut-modal"):
            yield Static(self.form.title, classes="modal-title")
            for field in self.form.fields:
                yield Label(field.label, classes="field-label")
                yield Input(
                    password=field.kind is FieldKind.SECRET,
                    id=_field_widget_id(field.field_id),
                    classes="form-field",
                )
            yield Static(id="form-errors")
            with Horizontal(id="form-controls"):
                yield Button(
                    self.form.submit.label,
                    variant="primary",
                    id="form-submit",
                )
                yield Button(
                    self.form.cancel.label,
                    id="form-cancel",
                )

    def on_mount(self) -> None:
        if self.form.fields:
            self.query_one(
                f"#{_field_widget_id(self.form.fields[0].field_id)}",
                Input,
            ).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "form-cancel":
            self.action_cancel()
        elif event.button.id == "form-submit":
            self._submit()

    def on_input_changed(self, event: Input.Changed) -> None:
        del event
        self.query_one("#form-errors", Static).update("")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        del event
        self._submit()

    def action_cancel(self) -> None:
        if self.query_one("#form-submit", Button).disabled:
            return
        self._clear_secret_widgets()
        self.dismiss(None)

    def _submit(self) -> None:
        submit = self.query_one("#form-submit", Button)
        if submit.disabled:
            return
        values = self._values()
        errors = validate_visual_input(self.form, values)
        if errors:
            self.query_one("#form-errors", Static).update(
                "\n".join(error.message for error in errors)
            )
            first = errors[0]
            self.query_one(f"#{_field_widget_id(first.field_id)}", Input).focus()
            return
        result = FormSubmission(self.form.action_id, values)
        submit.disabled = True
        self.query_one("#form-cancel", Button).disabled = True
        self.query_one("#form-errors", Static).update("Working…")
        self.post_message(self.Submitted(self, result))

    def show_domain_error(self, message: str) -> None:
        self.query_one("#form-errors", Static).update(message)
        self.query_one("#form-submit", Button).disabled = False
        self.query_one("#form-cancel", Button).disabled = False

    def resume(self) -> None:
        self.query_one("#form-errors", Static).update("")
        self.query_one("#form-submit", Button).disabled = False
        self.query_one("#form-cancel", Button).disabled = False

    def complete(self) -> None:
        self._clear_secret_widgets()
        self.dismiss(None)

    def _values(self) -> dict[str, str]:
        return {
            field.field_id: self.query_one(
                f"#{_field_widget_id(field.field_id)}",
                Input,
            ).value
            for field in self.form.fields
        }

    def _clear_secret_widgets(self) -> None:
        for field in self.form.fields:
            if field.clear_on_close:
                self.query_one(
                    f"#{_field_widget_id(field.field_id)}",
                    Input,
                ).value = ""


class ConfirmationScreen(_TautModalScreen[bool]):
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "reject", "Cancel", show=False),
        Binding("n", "reject", "Cancel", show=False),
        Binding("y", "confirm", "Confirm", show=False),
    ]

    def __init__(self, prompt: str) -> None:
        super().__init__()
        self.prompt = prompt

    def compose(self) -> ComposeResult:
        with Vertical(classes="taut-modal"):
            yield Static("Confirm action", classes="modal-title")
            yield Static(self.prompt)
            with Horizontal(id="form-controls"):
                yield Button("Cancel", id="confirmation-cancel")
                yield Button(
                    "Confirm",
                    variant="error",
                    id="confirmation-confirm",
                )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "confirmation-confirm":
            self.action_confirm()
        else:
            self.action_reject()

    def action_confirm(self) -> None:
        self.dismiss(True)

    def action_reject(self) -> None:
        self.dismiss(False)


class CommandPaletteScreen(
    _TautModalScreen["ActionId | PaletteCommandHandoff | None"]
):
    """Browse the grouped native semantic action registry."""

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "cancel", "Cancel", show=False),
        Binding("down", "highlight_next", "Next action", show=False, priority=True),
        Binding(
            "up",
            "highlight_previous",
            "Previous action",
            show=False,
            priority=True,
        ),
    ]

    def __init__(
        self,
        entries: Iterable[PaletteEntry],
        *,
        command_roots: frozenset[str] = frozenset(),
    ) -> None:
        super().__init__()
        self._entries = tuple(entries)
        self._command_roots = command_roots
        self._visible: tuple[PaletteEntry, ...] = ()
        self._rendered_entries: tuple[
            PaletteEntry | PaletteCommandHandoff | None, ...
        ] = ()
        self._dismissed = False

    def compose(self) -> ComposeResult:
        with Vertical(classes="taut-modal"):
            yield Static("Actions", classes="modal-title")
            yield Static(
                "Type to filter · Up/Down select · Enter run · "
                "Double-click run · Esc close",
                classes="command-instructions",
            )
            yield Input(
                placeholder="Find a native action",
                id="palette-query",
            )
            yield OptionList(id="palette-results")

    def on_mount(self) -> None:
        self._render_results("")
        self.query_one("#palette-query", Input).focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "palette-query":
            self._render_results(event.value)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "palette-query":
            return
        options = self.query_one("#palette-results", OptionList)
        index = options.highlighted
        if index is None or not 0 <= index < len(self._rendered_entries):
            return
        self._activate_index(index)

    def on_taut_option_list_activated(self, event: OptionList.Activated) -> None:
        if event.chain == 1:
            return
        if not (0 <= event.option_index < len(self._rendered_entries)):
            return
        self._activate_index(event.option_index)

    def _activate_index(self, index: int) -> None:
        entry = self._rendered_entries[index]
        if isinstance(entry, PaletteCommandHandoff):
            self._dismiss_once(entry)
        elif entry is not None and entry.enabled:
            self._dismiss_once(entry.action.action_id)

    def action_cancel(self) -> None:
        self._dismiss_once(None)

    def action_highlight_next(self) -> None:
        self._move_highlight(1)

    def action_highlight_previous(self) -> None:
        self._move_highlight(-1)

    def _move_highlight(self, direction: int) -> None:
        activatable = self._activatable_indices()
        if not activatable:
            return
        options = self.query_one("#palette-results", OptionList)
        current = options.highlighted
        if current is None or current not in activatable:
            options.highlighted = (
                activatable[0] if direction > 0 else activatable[-1]
            )
            return
        position = activatable.index(current)
        options.highlighted = activatable[
            (position + direction) % len(activatable)
        ]

    def _activatable_indices(self) -> tuple[int, ...]:
        return tuple(
            index
            for index, entry in enumerate(self._rendered_entries)
            if isinstance(entry, PaletteCommandHandoff)
            or (entry is not None and entry.enabled)
        )

    def _dismiss_once(
        self, result: ActionId | PaletteCommandHandoff | None
    ) -> None:
        if self._dismissed:
            return
        self._dismissed = True
        self.dismiss(result)

    def _render_results(self, query: str) -> None:
        self._visible = tuple(
            entry
            for entry in self._entries
            if _fuzzy_match(
                query,
                f"{entry.action.label} {entry.action.action_id.value}",
            )
        )
        options = self.query_one("#palette-results", OptionList)
        options.clear_options()
        rendered: list[PaletteEntry | PaletteCommandHandoff | None] = []
        entries_by_group: dict[str, list[PaletteEntry]] = {}
        for entry in self._visible:
            entries_by_group.setdefault(entry.action.display_group, []).append(entry)
        grouped = not query.strip() and len(entries_by_group) > 1
        for group, entries in _ordered_groups(entries_by_group):
            if grouped:
                options.add_option(
                    Option(f"{group}", id=f"group:{group}", disabled=True)
                )
                rendered.append(None)
            for entry in entries:
                self._add_palette_option(options, entry)
                rendered.append(entry)
        handoff = self._command_handoff(query)
        if handoff is not None:
            options.add_option(
                Option(
                    f'Run as command: "{handoff.query}"',
                    id="palette-run-command",
                )
            )
            rendered.append(handoff)
        if not rendered:
            options.add_option(
                Option(
                    "No matching actions — use the : command line for "
                    "commands with arguments",
                    id="palette-empty",
                    disabled=True,
                )
            )
            rendered.append(None)
        self._rendered_entries = tuple(rendered)
        activatable = self._activatable_indices()
        options.highlighted = activatable[0] if activatable else None

    def _command_handoff(self, query: str) -> PaletteCommandHandoff | None:
        # Exact root-token membership is evaluated independently of (and
        # before) the fuzzy action matcher, which only governs action rows.
        stripped = query.strip()
        if not stripped:
            return None
        root = stripped.split()[0]
        if root in self._command_roots:
            return PaletteCommandHandoff(stripped)
        return None

    @staticmethod
    def _add_palette_option(options: OptionList, entry: PaletteEntry) -> None:
        suffix = "" if entry.enabled else f"  ({entry.reason})"
        context = "" if entry.scope is None else f"  [{entry.scope}]"
        gesture = "" if entry.gesture_hint is None else f"  {entry.gesture_hint}"
        options.add_option(
            Option(
                f"{entry.action.label}{context}{gesture}{suffix}",
                id=entry.action.action_id.value,
                disabled=not entry.enabled,
            )
        )


def _ordered_groups(
    groups: dict[str, list[PaletteEntry]],
) -> tuple[tuple[str, tuple[PaletteEntry, ...]], ...]:
    order = {
        "Workspace & identity": 0,
        "Conversations": 1,
        "Channels": 2,
        "Messages": 3,
        "Search": 4,
        "System": 5,
        "Summon": 6,
    }
    return tuple(
        (
            group,
            tuple(
                sorted(
                    entries,
                    key=lambda entry: (
                        entry.action.display_order,
                        entry.action.label.casefold(),
                    ),
                )
            ),
        )
        for group, entries in sorted(
            groups.items(),
            key=lambda item: (order.get(item[0], len(order)), item[0]),
        )
    )


class _CommandShadowSuggester(Suggester):
    """Ghost-shadow completion of the current input to a command path."""

    def __init__(self, screen: CommandLineScreen) -> None:
        super().__init__(use_cache=False, case_sensitive=True)
        self._screen = screen

    async def get_suggestion(self, value: str) -> str | None:
        return self._screen.shadow_for(value)


class CommandLineScreen(ModalScreen[CommandLineSubmission | None]):
    """The vi-like bottom command line over the public typed syntax.

    [TUI-7.1]: owns keyboard focus while open, never blocks or dims the
    live view behind it, never presents a browsable completion list, and
    offers inline ghost-shadow completion cycled with Up/Down and accepted
    with Tab.
    """

    CSS = """
    CommandLineScreen {
        align: left bottom;
        background: transparent;
    }

    #command-bar {
        dock: bottom;
        width: 1fr;
        height: auto;
        background: $surface;
        border-top: tall $accent;
        padding: 0 1;
    }

    #command-entry { height: 1; }
    #command-marker { width: 1; color: $accent; text-style: bold; }

    #command-line {
        width: 1fr;
        height: 1;
        border: none;
        padding: 0;
        background: $surface;
    }

    #command-errors { height: 1; color: $text-muted; }
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "cancel", "Cancel", show=False),
        Binding("tab", "accept_shadow", "Complete", show=False),
        Binding(
            "down",
            "shadow_next",
            "Next match",
            show=False,
            priority=True,
        ),
        Binding(
            "up",
            "shadow_previous",
            "Previous match",
            show=False,
            priority=True,
        ),
    ]

    def __init__(
        self,
        syntax: RootCommandSyntax,
        *,
        initial_text: str = "",
        reconcile: Callable[[], str] | None = None,
    ) -> None:
        super().__init__()
        self._syntax = syntax
        self._initial_text = initial_text
        self._reconcile = reconcile
        self._dismissed = False
        self._matches: tuple[str, ...] = ()
        self._match_index = 0

    def compose(self) -> ComposeResult:
        with Vertical(id="command-bar"):
            with Horizontal(id="command-entry"):
                yield Static(":", id="command-marker")
                yield Input(
                    value=self._initial_text,
                    placeholder="command [options]",
                    id="command-line",
                    select_on_focus=False,
                    suggester=_CommandShadowSuggester(self),
                )
            yield Static(id="command-errors")

    def on_mount(self) -> None:
        command_line = self.query_one("#command-line", Input)
        if self._reconcile is not None:
            # [TUI-7.1]: reconcile against the composer's current draft at
            # mount time so keystrokes that raced past the promotion boundary
            # are carried into the command field.
            command_line.value = self._reconcile()
        command_line.focus()
        command_line.cursor_position = len(command_line.value)
        self._render_feedback(command_line.value)

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "command-line":
            self._match_index = 0
            self._render_feedback(event.value)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "command-line":
            return
        self._submit(event.value)

    def shadow_for(self, value: str) -> str | None:
        """Return the cycled match when it extends the exact current input.

        Matches are computed from the value directly because the suggester
        worker can run before the `Input.Changed` message handler updates
        screen state.
        """

        matches = _command_completions(value, self._syntax)
        if not matches:
            return None
        index = self._match_index % len(matches)
        candidate = matches[index]
        if candidate.startswith(value) and len(candidate) > len(value):
            return candidate
        return None

    def action_cancel(self) -> None:
        self._dismiss_once(None)

    def action_accept_shadow(self) -> None:
        command_line = self.query_one("#command-line", Input)
        shadow = self.shadow_for(command_line.value)
        if shadow is None:
            return
        command_line.value = shadow.rstrip() + " "
        command_line.focus()
        command_line.cursor_position = len(command_line.value)

    def action_shadow_next(self) -> None:
        self._cycle_shadow(1)

    def action_shadow_previous(self) -> None:
        self._cycle_shadow(-1)

    def _cycle_shadow(self, direction: int) -> None:
        command_line = self.query_one("#command-line", Input)
        matches = _command_completions(command_line.value, self._syntax)
        if not matches:
            return
        self._match_index = (self._match_index + direction) % len(matches)
        # Input only re-queries its suggester on value changes; refresh the
        # displayed ghost directly. `_suggestion` is a private Textual 8.2.8
        # reactive — pinned by the contract tests; worst-case degradation is
        # a shadow that updates on the next keystroke.
        command_line._suggestion = self.shadow_for(command_line.value) or ""

    def _submit(self, text: str) -> None:
        try:
            invocation = parse_command_line(CommandInput(text), syntax=self._syntax)
        except CommandSyntaxError as exc:
            self._show_feedback(str(exc))
            return
        self._dismiss_once(CommandLineSubmission(invocation))

    def _render_feedback(self, text: str) -> None:
        self._matches = _command_completions(text, self._syntax)
        try:
            invocation = parse_command_line(CommandInput(text), syntax=self._syntax)
        except CommandSyntaxError as exc:
            message = str(exc) if text.strip() else "Type a command"
        else:
            if invocation.action is not None:
                message = f"Ready: {invocation.action} help"
            else:
                message = "Ready: " + format_command_syntax(
                    _syntax_node(invocation, self._syntax)
                )
        if len(self._matches) > 1:
            message = f"{message}  ·  matches: " + ", ".join(self._matches)
        self._show_feedback(message)

    def _show_feedback(self, message: str) -> None:
        self.query_one("#command-errors", Static).update(message)

    def _dismiss_once(self, result: CommandLineSubmission | None) -> None:
        if self._dismissed:
            return
        self._dismissed = True
        self.dismiss(result)


def _command_completions(text: str, syntax: RootCommandSyntax) -> tuple[str, ...]:
    stripped = text.strip()
    if not stripped:
        return tuple(" ".join(node.path) for node in command_nodes(syntax))
    prefix = stripped.split()
    if text.endswith(" "):
        prefix.append("")
    candidates = [
        " ".join(node.path)
        for node in command_nodes(syntax)
        if all(
            part.startswith(expected)
            for part, expected in zip(node.path, prefix, strict=False)
        )
    ]
    return tuple(candidates[:8])


def _syntax_node(
    invocation: CommandInvocation,
    syntax: RootCommandSyntax,
) -> CommandSyntax:
    for node in command_nodes(syntax):
        if node.path == invocation.path:
            return node
    raise ValueError(f"unknown syntax path: {invocation.path}")


class SearchScreen(_TautModalScreen[object | None]):
    """Cursor-neutral history search with stale-completion suppression."""

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "cancel", "Cancel", show=False),
    ]

    def __init__(self, search: Callable[[str], Future[list[object]]]) -> None:
        super().__init__()
        self._search = search
        self._generation = 0
        self._results: tuple[object, ...] = ()

    def compose(self) -> ComposeResult:
        with Vertical(classes="taut-modal"):
            yield Static("Search history", classes="modal-title")
            yield Input(placeholder="Search visible history", id="search-query")
            yield Static(id="search-errors")
            yield OptionList(id="search-results")

    def on_mount(self) -> None:
        self.query_one("#search-query", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        query = event.value.strip()
        if event.input.id != "search-query" or not query:
            return
        self._generation += 1
        generation = self._generation
        self.query_one("#search-errors", Static).update("Searching…")
        future = self._search(query)

        def completed(done: Future[list[object]]) -> None:
            try:
                self.app.call_later(self._apply_results, generation, done)
            except Exception:  # noqa: BLE001 approved [DOM-10.2.1] [RUFF-SUP-086] exception
                return

        future.add_done_callback(completed)

    def on_taut_option_list_activated(self, event: OptionList.Activated) -> None:
        if event.chain == 1:
            return
        self.dismiss(self._results[event.option_index])

    def action_cancel(self) -> None:
        self._generation += 1
        self.dismiss(None)

    def _apply_results(
        self,
        generation: int,
        future: Future[list[object]],
    ) -> None:
        if generation != self._generation:
            return
        try:
            results = tuple(future.result())
        except Exception as exc:  # noqa: BLE001 approved [DOM-10.2.1] [RUFF-SUP-085] exception
            self.query_one("#search-errors", Static).update(type(exc).__name__)
            return
        self._results = results
        self.query_one("#search-errors", Static).update(
            "No matches" if not results else f"{len(results)} result(s)"
        )
        options = self.query_one("#search-results", OptionList)
        options.clear_options()
        for result in results:
            thread = str(getattr(result, "thread", "unknown"))
            author = str(getattr(result, "from_name", "unknown"))
            text = str(getattr(result, "text", ""))
            options.add_option(f"{thread}  {author}  {text}")


class SummonStartScreen(_TautModalScreen[SummonStartSubmission | None]):
    """Native typed controls for every public SummonRequest field."""

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "cancel", "Cancel", show=False),
    ]

    def __init__(self, providers: tuple[str, ...]) -> None:
        super().__init__()
        self._providers = providers

    def compose(self) -> ComposeResult:
        with Vertical(classes="taut-modal"):
            yield Static("Start summoned member", classes="modal-title")
            yield Label("Name", classes="field-label")
            yield Input(id="summon-name", classes="form-field")
            yield Label("Conversations (comma-separated)", classes="field-label")
            yield Input(value="general", id="summon-threads", classes="form-field")
            yield Label("Provider", classes="field-label")
            yield Select(
                ((provider, provider) for provider in self._providers),
                prompt="Infer from name",
                id="summon-provider",
                classes="form-field",
            )
            yield Label("Persona", classes="field-label")
            yield Input(id="summon-persona", classes="form-field")
            yield Label("System prompt file", classes="field-label")
            yield Input(id="summon-system-prompt", classes="form-field")
            yield Label("Rate limit", classes="field-label")
            yield Input(type="integer", id="summon-rate-limit", classes="form-field")
            yield Checkbox("Terminal mode", id="summon-terminal")
            yield Checkbox("Attach", id="summon-attach")
            yield Checkbox("Detach", id="summon-detach")
            yield Checkbox("Take over stale claim", id="summon-takeover")
            yield Static(id="form-errors")
            with Horizontal(id="form-controls"):
                yield Button("Cancel", id="summon-cancel")
                yield Button(
                    "Start",
                    variant="primary",
                    id="summon-submit",
                )

    def on_mount(self) -> None:
        self.query_one("#summon-name", Input).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "summon-cancel":
            self.action_cancel()
        elif event.button.id == "summon-submit":
            self._submit()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        del event
        self._submit()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def _submit(self) -> None:
        name = self.query_one("#summon-name", Input).value.strip()
        if not name:
            self.query_one("#form-errors", Static).update("Name must not be blank.")
            self.query_one("#summon-name", Input).focus()
            return
        rate_input = self.query_one("#summon-rate-limit", Input)
        rate_text = rate_input.value.strip()
        try:
            rate_limit = int(rate_text) if rate_text else None
        except ValueError:
            self.query_one("#form-errors", Static).update(
                "Rate limit must be a whole number."
            )
            rate_input.focus()
            return
        provider_value = self.query_one("#summon-provider", Select).value
        provider = provider_value if isinstance(provider_value, str) else None
        threads = tuple(
            part.strip()
            for part in self.query_one("#summon-threads", Input).value.split(",")
            if part.strip()
        ) or ("general",)
        persona = self.query_one("#summon-persona", Input).value.strip() or None
        system_prompt_file = (
            self.query_one("#summon-system-prompt", Input).value.strip() or None
        )
        self.dismiss(
            SummonStartSubmission(
                name=name,
                threads=threads,
                provider=provider,
                persona=persona,
                system_prompt_file=system_prompt_file,
                rate_limit=rate_limit,
                terminal=self.query_one("#summon-terminal", Checkbox).value,
                attach=self.query_one("#summon-attach", Checkbox).value,
                detach=self.query_one("#summon-detach", Checkbox).value,
                takeover=self.query_one("#summon-takeover", Checkbox).value,
            )
        )


class NamedActionScreen(_TautModalScreen[NamedActionSubmission | None]):
    """Select a public summoned-member name for status or dismiss."""

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "cancel", "Cancel", show=False),
    ]

    def __init__(self, action_id: ActionId, title: str) -> None:
        super().__init__()
        self._action_id = action_id
        self._title = title

    def compose(self) -> ComposeResult:
        with Vertical(classes="taut-modal"):
            yield Static(self._title, classes="modal-title")
            yield Label("Summoned member", classes="field-label")
            yield Input(id="summon-member-name", classes="form-field")
            yield Static(id="form-errors")
            with Horizontal(id="form-controls"):
                yield Button("Cancel", id="named-action-cancel")
                yield Button("Continue", variant="primary", id="named-action-submit")

    def on_mount(self) -> None:
        self.query_one("#summon-member-name", Input).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "named-action-cancel":
            self.action_cancel()
            return
        self._submit()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        del event
        self._submit()

    def _submit(self) -> None:
        name = self.query_one("#summon-member-name", Input).value.strip()
        if not name:
            self.query_one("#form-errors", Static).update(
                "Summoned member must not be blank."
            )
            return
        self.dismiss(NamedActionSubmission(self._action_id, name))

    def action_cancel(self) -> None:
        self.dismiss(None)


def _field_widget_id(field_id: str) -> str:
    return f"field-{field_id.replace('_', '-')}"


def _fuzzy_match(query: str, candidate: str) -> bool:
    needle = "".join(query.casefold().split())
    if not needle:
        return True
    haystack = candidate.casefold()
    cursor = iter(haystack)
    return all(any(char == available for available in cursor) for char in needle)


__all__ = [
    "CommandLineScreen",
    "CommandLineSubmission",
    "CommandPaletteScreen",
    "ConfirmationScreen",
    "FormSubmission",
    "NamedActionScreen",
    "NamedActionSubmission",
    "NativeFormScreen",
    "PaletteCommandHandoff",
    "PaletteEntry",
    "SearchScreen",
    "SummonStartScreen",
    "SummonStartSubmission",
]
