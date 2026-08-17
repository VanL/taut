"""Extension-owned widgets that preserve Taut's display and input semantics."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, ClassVar, Self

from rich.console import RenderableType
from rich.text import Text
from textual.binding import Binding, BindingType
from textual.content import Content, ContentText
from textual.message import Message
from textual.visual import VisualType
from textual.widgets import (
    Button,
    Checkbox,
    Input,
    Label,
    OptionList,
    Select,
    Static,
    TextArea,
)
from textual.widgets.option_list import Option

from taut import escape_terminal_text

_DISPLAY_TOKEN = object()
_MESSAGE_TAB_SIZE = 4


class EscapedDisplayText(str):
    """A string escaped exactly once by this module's display policy."""

    def __new__(
        cls,
        value: str,
        *,
        _token: object | None = None,
    ) -> Self:
        if _token is not _DISPLAY_TOKEN:
            raise TypeError("escaped display strings must come from the factory")
        return super().__new__(cls, value)


def escape_display_text(value: str) -> EscapedDisplayText:
    """Escape terminal controls while retaining layout-owned newlines."""

    if isinstance(value, EscapedDisplayText):
        return value
    return EscapedDisplayText(
        "\n".join(
            escape_terminal_text(line, inherit_defaults=True)
            for line in value.split("\n")
        ),
        _token=_DISPLAY_TOKEN,
    )


def escape_message_body(value: str) -> EscapedDisplayText:
    """Expand structural message tabs before applying terminal escape policy."""

    return escape_display_text(value.expandtabs(_MESSAGE_TAB_SIZE))


def escape_inline_text(value: str) -> EscapedDisplayText:
    """Escape controls in metadata that must remain on its owned display line."""

    return EscapedDisplayText(
        escape_terminal_text(value, inherit_defaults=True),
        _token=_DISPLAY_TOKEN,
    )


class DisplayText(Text):
    """Marker for Rich text assembled from already escaped display segments."""

    def __init__(self, *, _token: object | None = None) -> None:
        if _token is not _DISPLAY_TOKEN:
            raise TypeError("styled display text must come from the factory")
        super().__init__()


def display_text(*parts: str | tuple[str, Any]) -> DisplayText:
    """Build styled Rich text without exposing raw strings to Rich first."""

    rendered = DisplayText(_token=_DISPLAY_TOKEN)
    for part in parts:
        if isinstance(part, tuple):
            value, style = part
        else:
            value, style = part, None
        rendered.append(str(escape_display_text(value)), style=style)
    return rendered


def _display_content(value: object) -> Text:
    """Escape plain text and accept only explicitly safe styled text."""

    if isinstance(value, DisplayText):
        return value
    if isinstance(value, str):
        return Text(str(escape_display_text(value)))
    if isinstance(value, Text):
        raise TypeError("raw Rich Text is not a trusted Taut display value")
    raise TypeError(f"unsupported Taut display value: {type(value).__name__}")


class TautStatic(Static):
    """Static content that applies Taut's display policy at the sink."""

    def __init__(self, content: VisualType = "", **kwargs: Any) -> None:
        kwargs["markup"] = False
        super().__init__(_display_content(content), **kwargs)

    def update(self, content: VisualType = "", *, layout: bool = True) -> None:
        super().update(_display_content(content), layout=layout)


class TautLabel(Label):
    """Label content that applies Taut's display policy at the sink."""

    def __init__(self, content: VisualType = "", **kwargs: Any) -> None:
        kwargs["markup"] = False
        super().__init__(_display_content(content), **kwargs)

    def update(self, content: VisualType = "", *, layout: bool = True) -> None:
        super().update(_display_content(content), layout=layout)


class TautButton(Button):
    """Button label that applies Taut's display policy on every assignment."""

    def __init__(
        self,
        label: ContentText | None = None,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        if label is not None:
            if not isinstance(label, str):
                raise TypeError("Taut button labels must be strings")
            label = str(escape_display_text(label))
        super().__init__(label, *args, **kwargs)

    def validate_label(self, label: ContentText) -> Content:
        if not isinstance(label, str):
            raise TypeError("Taut button labels must be strings")
        return super().validate_label(str(escape_display_text(label)))


class TautCheckbox(Checkbox):
    """Checkbox label that applies Taut's display policy on every assignment."""

    def _make_label(self, label: ContentText) -> Content:
        if not isinstance(label, str):
            raise TypeError("Taut checkbox labels must be strings")
        return super()._make_label(str(escape_display_text(label)))


class TautInput(Input):
    """Editable input whose display-only placeholder is terminal-safe."""

    def validate_placeholder(self, placeholder: str) -> str:
        return str(escape_display_text(placeholder))


class TautComposer(TextArea):
    """Multiline composer with explicit structural-input and submit keys."""

    BINDINGS: ClassVar[list[BindingType]] = [
        *TextArea.BINDINGS,
        Binding("enter", "submit", priority=True),
        Binding("ctrl+enter,ctrl+j", "insert_newline", priority=True),
        Binding("ctrl+tab", "insert_tab", priority=True),
    ]

    class Submitted(Message):
        """Posted when the composer requests submission without changing text."""

        def __init__(self, composer: TautComposer) -> None:
            super().__init__()
            self.composer = composer
            self.value = composer.text

    def __init__(self, text: str = "", **kwargs: Any) -> None:
        kwargs["tab_behavior"] = "focus"
        kwargs["show_line_numbers"] = False
        placeholder = kwargs.get("placeholder", "")
        if not isinstance(placeholder, str):
            raise TypeError("Taut composer placeholders must be strings")
        kwargs["placeholder"] = str(escape_display_text(placeholder))
        super().__init__(text, **kwargs)

    def validate_placeholder(self, placeholder: str | Content) -> str:
        if not isinstance(placeholder, str):
            raise TypeError("Taut composer placeholders must be strings")
        return str(escape_display_text(placeholder))

    @property
    def cursor_position(self) -> int:
        """Expose the cursor as a scalar code-point offset for draft state."""

        row, column = self.cursor_location
        lines = self.text.split("\n")
        return sum(len(line) + 1 for line in lines[:row]) + min(
            column,
            len(lines[row]),
        )

    @cursor_position.setter
    def cursor_position(self, position: int) -> None:
        bounded = min(max(position, 0), len(self.text))
        prefix = self.text[:bounded]
        row = prefix.count("\n")
        column = len(prefix.rsplit("\n", 1)[-1])
        self.move_cursor((row, column))

    def action_submit(self) -> None:
        self.post_message(self.Submitted(self))

    def action_insert_newline(self) -> None:
        self.insert("\n")

    def action_insert_tab(self) -> None:
        self.insert("\t")


class TautSelect(Select[Any]):
    """Select whose labels are escaped independently of submitted values."""

    def __init__(
        self,
        options: Iterable[tuple[RenderableType, Any]],
        **kwargs: Any,
    ) -> None:
        super().__init__(self._display_options(options), **kwargs)

    def validate_prompt(self, prompt: str) -> str:
        return str(escape_display_text(prompt))

    def set_options(self, options: Iterable[tuple[RenderableType, Any]]) -> None:
        super().set_options(self._display_options(options))

    @staticmethod
    def _display_options(
        options: Iterable[tuple[RenderableType, Any]],
    ) -> list[tuple[RenderableType, Any]]:
        return [(_display_content(label), value) for label, value in options]


class TautOptionList(OptionList):
    """Escape option prompts and expose activation with its pointer chain."""

    class Activated(Message):
        def __init__(
            self, option_list: TautOptionList, selected: OptionList.OptionSelected
        ):
            super().__init__()
            self.option_list = option_list
            self.option = selected.option
            self.option_index = selected.option_index
            self.chain = (
                option_list._last_pointer_chain
                if option_list._last_pointer_chain
                else (1 if option_list._pointer_pending else 0)
            )

    def __init__(self, *content: Any, **kwargs: Any) -> None:
        kwargs["markup"] = False
        super().__init__(*content, **kwargs)
        self._last_pointer_chain = 0
        self._pointer_pending = False

    def add_options(self, new_options: Iterable[Any]) -> TautOptionList:
        return super().add_options(
            self._display_option(option) for option in new_options
        )

    @staticmethod
    def _display_option(option: Any) -> Any:
        if isinstance(option, Option):
            return Option(
                _display_content(option.prompt),
                id=option.id,
                disabled=option.disabled,
            )
        if option is None:
            return None
        return _display_content(option)

    def replace_option_prompt(
        self,
        option_id: str,
        prompt: VisualType,
    ) -> TautOptionList:
        return super().replace_option_prompt(option_id, _display_content(prompt))

    def replace_option_prompt_at_index(
        self,
        index: int,
        prompt: VisualType,
    ) -> TautOptionList:
        return super().replace_option_prompt_at_index(index, _display_content(prompt))

    def on_mouse_down(self, event: object) -> None:
        del event
        self._pointer_pending = True
        self.capture_mouse()

    def on_mouse_up(self, event: object) -> None:
        style = getattr(event, "style", None)
        released_option = None if style is None else style.meta.get("option")
        self._pointer_pending = isinstance(released_option, int)
        self.release_mouse()

    def on_click(self, event: object) -> None:
        style = getattr(event, "style", None)
        clicked_option = None if style is None else style.meta.get("option")
        if not isinstance(clicked_option, int):
            self._last_pointer_chain = 0
            self._pointer_pending = False
            return
        option = self.get_option_at_index(clicked_option)
        if option.disabled:
            self._last_pointer_chain = 0
            self._pointer_pending = False
            return
        self.highlighted = clicked_option
        self.focus()
        chain = int(getattr(event, "chain", 1))
        if chain >= 2:
            self._last_pointer_chain = chain
            self.action_select()
        else:
            self._last_pointer_chain = 0

    def on_option_list_option_selected(
        self,
        event: OptionList.OptionSelected,
    ) -> None:
        event.stop()
        self.post_message(self.Activated(self, event))
        self._last_pointer_chain = 0
        self._pointer_pending = False


__all__ = [
    "DisplayText",
    "EscapedDisplayText",
    "TautButton",
    "TautCheckbox",
    "TautComposer",
    "TautInput",
    "TautLabel",
    "TautOptionList",
    "TautSelect",
    "TautStatic",
    "display_text",
    "escape_display_text",
    "escape_inline_text",
    "escape_message_body",
]
