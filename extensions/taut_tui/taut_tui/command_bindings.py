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


@dataclass(frozen=True, slots=True)
class TuiCommandBinding:
    """One explicit native TUI owner for a mirrored command path."""

    path: CommandPath
    cli_only: bool = False

    def __post_init__(self) -> None:
        if not self.path:
            raise ValueError("binding needs a path")


def _native(path: CommandPath) -> TuiCommandBinding:
    return TuiCommandBinding(path)


def _cli_only(path: CommandPath) -> TuiCommandBinding:
    return TuiCommandBinding(path, cli_only=True)


_BINDINGS = (
    _native(("init",)),
    _native(("join",)),
    _native(("leave",)),
    _native(("set", "name")),
    _native(("say",)),
    _native(("reply",)),
    _native(("message", "show")),
    _native(("message", "delete")),
    _native(("message", "react")),
    _native(("channel", "show")),
    _native(("channel", "topic")),
    _native(("channel", "rename")),
    _native(("read",)),
    _native(("inbox",)),
    _native(("log",)),
    _native(("search",)),
    _native(("system", "doctor")),
    _native(("system", "dump")),
    _native(("system", "debug", "enable")),
    _native(("system", "debug", "disable")),
    _native(("list",)),
    _cli_only(("watch",)),
    _native(("who",)),
    _native(("whoami",)),
    _native(("rejoin",)),
    _native(("summon",)),
    _native(("dismiss",)),
    _native(("q",)),
    _native(("quit",)),
    _cli_only(("system", "load")),
)

COMMAND_BINDINGS: Mapping[CommandPath, TuiCommandBinding] = MappingProxyType(
    {binding.path: binding for binding in _BINDINGS}
)


def binding_for(path: CommandPath) -> TuiCommandBinding | None:
    """Return the TUI disposition for one exact command path."""

    return COMMAND_BINDINGS.get(path)


__all__ = ["COMMAND_BINDINGS", "TuiCommandBinding", "binding_for"]
