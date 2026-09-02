"""Taut exception hierarchy.

Spec references:
- docs/specs/02-taut-core.md [TAUT-3.2], [TAUT-3.3], [TAUT-5], [TAUT-8.1]
"""

from __future__ import annotations


class TautError(Exception):
    """Base class for all taut user-visible failures."""


class NotInitializedError(TautError):
    """Raised when no taut database can be resolved."""


class BackendNotSupportedError(TautError):
    """Raised when the resolved broker backend is not supported by taut."""


class SchemaVersionError(TautError):
    """Raised when the database schema is newer than this taut version."""


class ThreadNameError(TautError):
    """Raised for invalid or reserved thread names."""


class IdentityError(TautError):
    """Raised when member identity cannot be resolved safely."""


class UnrecognizedCallerError(IdentityError):
    """Raised when no selector or process evidence maps to an existing member.

    The dispatcher maps this exact subtype to exit 2 ("nothing found") so
    scripts can distinguish "taut does not know who you are" from an invalid
    selector, which stays exit 1. ``hints`` are recovery lines; ``str()``
    joins them under the message, and the CLI renders each as its own record.
    """

    def __init__(
        self, message: str = "unrecognized caller", *, hints: tuple[str, ...] = ()
    ) -> None:
        super().__init__("\n".join((message, *hints)))
        self.message = message
        self.hints = hints


class MembershipError(TautError):
    """Raised when a command requires thread membership."""


class EmptyResultError(TautError):
    """Raised when a command succeeded but matched no messages or rows."""


class BlankMessageError(EmptyResultError):
    """Raised when a proposed user message contains only blank characters."""


class NotFoundError(EmptyResultError):
    """Raised when a requested thread, member, or message does not exist."""


class AmbiguousMessageError(TautError):
    """Raised when a message-id suffix matches more than one message."""


class WatcherRejected(Exception):
    """Stop a live watcher after rejecting an item without acknowledging it.

    Watch handlers raise this control-flow exception when they cannot accept an
    item into their destination. Taut stops the watcher after the first
    rejection and does not advance the rejected chat message's cursor.
    """


class TokenError(IdentityError):
    """Raised when a presented continuity token does not match a member."""
