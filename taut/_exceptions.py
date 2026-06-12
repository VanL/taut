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
    """Raised when the resolved broker backend is not supported by v0.1."""


class SchemaVersionError(TautError):
    """Raised when the database schema is newer than this taut version."""


class ThreadNameError(TautError):
    """Raised for invalid or reserved thread names."""


class IdentityError(TautError):
    """Raised when member identity cannot be resolved safely."""


class MembershipError(TautError):
    """Raised when a command requires thread membership."""


class EmptyResultError(TautError):
    """Raised when a command succeeded but matched no messages or rows."""


class NotFoundError(EmptyResultError):
    """Raised when a requested thread, member, or message does not exist."""


class AmbiguousMessageError(TautError):
    """Raised when a message-id suffix matches more than one message."""


class TokenError(IdentityError):
    """Raised when a presented continuity token does not match a member."""
