"""Small extension-owned widgets that preserve Taut's input semantics."""

from __future__ import annotations

from typing import Any

from textual.message import Message
from textual.widgets import OptionList


class TautOptionList(OptionList):
    """Expose public option activation with its immediate pointer chain."""

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
        super().__init__(*content, **kwargs)
        self._last_pointer_chain = 0
        self._pointer_pending = False

    def on_mouse_down(self, event: object) -> None:
        del event
        self._pointer_pending = True

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


__all__ = ["TautOptionList"]
