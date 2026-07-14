"""Public package surface for Taut.

Spec references:
- docs/specs/02-taut-core.md [TAUT-8.3], [TAUT-8.6]
"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

from taut._constants import __version__
from taut._exceptions import (
    AmbiguousMessageError,
    BackendNotSupportedError,
    BlankMessageError,
    EmptyResultError,
    IdentityError,
    MembershipError,
    NotFoundError,
    NotInitializedError,
    SchemaVersionError,
    TautError,
    ThreadNameError,
    TokenError,
)

if TYPE_CHECKING:
    from taut.client import Member, Message, Notification, TautClient, Thread
    from taut.terminal import escape_terminal_text
    from taut.watcher import TautWatcher

_LAZY_EXPORTS = {
    "Member": ("taut.client", "Member"),
    "Message": ("taut.client", "Message"),
    "Notification": ("taut.client", "Notification"),
    "TautClient": ("taut.client", "TautClient"),
    "TautWatcher": ("taut.watcher", "TautWatcher"),
    "Thread": ("taut.client", "Thread"),
    "escape_terminal_text": ("taut.terminal", "escape_terminal_text"),
}

__all__ = [
    "AmbiguousMessageError",
    "BackendNotSupportedError",
    "BlankMessageError",
    "EmptyResultError",
    "IdentityError",
    "Member",
    "MembershipError",
    "Message",
    "NotInitializedError",
    "NotFoundError",
    "Notification",
    "SchemaVersionError",
    "TautClient",
    "TautError",
    "TautWatcher",
    "Thread",
    "ThreadNameError",
    "TokenError",
    "__version__",
    "escape_terminal_text",
]


if not TYPE_CHECKING:

    def __getattr__(name: str) -> Any:
        try:
            module_name, attribute_name = _LAZY_EXPORTS[name]
        except KeyError as exc:
            raise AttributeError(
                f"module {__name__!r} has no attribute {name!r}"
            ) from exc
        value = getattr(import_module(module_name), attribute_name)
        globals()[name] = value
        return value

    def __dir__() -> list[str]:
        return sorted({*globals(), *__all__})
