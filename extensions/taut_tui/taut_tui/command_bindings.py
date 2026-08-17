"""TUI-owned execution disposition for mirrored command paths.

Syntax is shared with core. These bindings are deliberately separate: a
syntax provider makes a path recognizable, while this registry says whether
the TUI has a typed native owner for it.

Spec references:
- docs/specs/10-taut-tui.md [TUI-2.1], [TUI-7.1]
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from taut.commands.syntax import CommandPath
from taut_tui.actions import ActionId


@dataclass(frozen=True, slots=True)
class TuiCommandBinding:
    """One explicit native TUI owner for a mirrored command path."""

    path: CommandPath
    action_id: ActionId | None = None
    cli_only: bool = False

    def __post_init__(self) -> None:
        if not self.path or (self.cli_only and self.action_id is not None):
            raise ValueError("binding needs a path and one execution disposition")


def _native(path: CommandPath, action_id: ActionId | None = None) -> TuiCommandBinding:
    return TuiCommandBinding(path, action_id)


def _cli_only(path: CommandPath) -> TuiCommandBinding:
    return TuiCommandBinding(path, cli_only=True)


_BINDINGS = (
    _native(("init",), ActionId.WORKSPACE_INITIALIZE),
    _native(("join",), ActionId.CHANNEL_JOIN),
    _native(("leave",), ActionId.CHANNEL_LEAVE),
    _native(("set", "name"), ActionId.IDENTITY_SET_NAME),
    _native(("say",), ActionId.MESSAGE_SEND),
    _native(("reply",), ActionId.MESSAGE_REPLY),
    _native(("message", "show")),
    _native(("message", "delete"), ActionId.MESSAGE_DELETE),
    _native(("message", "react"), ActionId.MESSAGE_REACT),
    _native(("channel", "show"), ActionId.CHANNEL_SHOW_TOPIC),
    _native(("channel", "topic")),
    _native(("channel", "rename"), ActionId.CHANNEL_RENAME),
    _native(("read",)),
    _native(("inbox",), ActionId.NOTIFICATIONS_OPEN),
    _native(("log",)),
    _native(("search",), ActionId.SEARCH_OPEN),
    _native(("system", "doctor"), ActionId.SYSTEM_DOCTOR),
    _native(("system", "dump"), ActionId.SYSTEM_DUMP),
    _native(("system", "debug", "enable")),
    _native(("system", "debug", "disable")),
    _native(("list",)),
    _cli_only(("watch",)),
    _native(("who",)),
    _native(("whoami",), ActionId.IDENTITY_SHOW),
    _native(("rejoin",), ActionId.IDENTITY_REJOIN),
    _native(("summon",), ActionId.SUMMON_START),
    _native(("dismiss",), ActionId.SUMMON_DISMISS),
    _cli_only(("system", "load")),
)

COMMAND_BINDINGS: Mapping[CommandPath, TuiCommandBinding] = MappingProxyType(
    {binding.path: binding for binding in _BINDINGS}
)


def binding_for(path: CommandPath) -> TuiCommandBinding | None:
    """Return the TUI disposition for one exact command path."""

    return COMMAND_BINDINGS.get(path)


__all__ = ["COMMAND_BINDINGS", "TuiCommandBinding", "binding_for"]
