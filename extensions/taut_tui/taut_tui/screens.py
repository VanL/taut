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

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical
from textual.message import Message as TextualMessage
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    Checkbox,
    Input,
    Label,
    OptionList,
    Select,
    Static,
)
from textual.widgets.option_list import Option

from taut import escape_terminal_text
from taut_tui.actions import ActionId, ActionSpec
from taut_tui.forms import FieldKind, FormSpec, validate_visual_input
from taut_tui.widgets import TautOptionList


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
        self.query_one("#form-errors", Static).update(Text(_display_text(message)))
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
            yield Static(Text(_display_text(self.prompt)))
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


class CommandPaletteScreen(_TautModalScreen[ActionId | None]):
    """Search only the native semantic action registry."""

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "cancel", "Cancel", show=False),
    ]

    def __init__(self, entries: Iterable[PaletteEntry]) -> None:
        super().__init__()
        self._entries = tuple(entries)
        self._visible: tuple[PaletteEntry, ...] = ()

    def compose(self) -> ComposeResult:
        with Vertical(classes="taut-modal"):
            yield Static("Commands", classes="modal-title")
            yield Input(placeholder="Find a native action", id="palette-query")
            yield TautOptionList(id="palette-results")

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
        for index, entry in enumerate(self._visible):
            if entry.enabled:
                options.highlighted = index
                self.dismiss(entry.action.action_id)
                return

    def on_taut_option_list_activated(self, event: TautOptionList.Activated) -> None:
        if event.chain == 1:
            return
        entry = self._visible[event.option_index]
        if entry.enabled:
            self.dismiss(entry.action.action_id)

    def action_cancel(self) -> None:
        self.dismiss(None)

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
        for entry in self._visible:
            suffix = "" if entry.enabled else f"  ({entry.reason})"
            context = "" if entry.scope is None else f"  [{entry.scope}]"
            gesture = "" if entry.gesture_hint is None else f"  {entry.gesture_hint}"
            options.add_option(
                Option(
                    Text(
                        _display_text(f"{entry.action.label}{context}{gesture}{suffix}")
                    ),
                    id=entry.action.action_id.value,
                    disabled=not entry.enabled,
                )
            )


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
            yield TautOptionList(id="search-results")

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

    def on_taut_option_list_activated(self, event: TautOptionList.Activated) -> None:
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
            options.add_option(
                Text(
                    f"{_display_text(thread)}  {_display_text(author)}  "
                    f"{_display_text(text)}"
                )
            )


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
                ((_display_text(provider), provider) for provider in self._providers),
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


def _display_text(value: str) -> str:
    return "\n".join(
        escape_terminal_text(line, inherit_defaults=True) for line in value.split("\n")
    )


def _fuzzy_match(query: str, candidate: str) -> bool:
    needle = "".join(query.casefold().split())
    if not needle:
        return True
    haystack = candidate.casefold()
    cursor = iter(haystack)
    return all(any(char == available for available in cursor) for char in needle)


__all__ = [
    "CommandPaletteScreen",
    "ConfirmationScreen",
    "FormSubmission",
    "NamedActionScreen",
    "NamedActionSubmission",
    "NativeFormScreen",
    "PaletteEntry",
    "SearchScreen",
    "SummonStartScreen",
    "SummonStartSubmission",
]
