"""Public package surface for taut.

Spec references:
- docs/specs/02-taut-core.md [TAUT-8.3]
"""

from taut._constants import __version__
from taut._exceptions import (
    AmbiguousMessageError,
    BackendNotSupportedError,
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
from taut.client import Member, Message, Notification, TautClient, Thread
from taut.watcher import TautWatcher

__all__ = [
    "AmbiguousMessageError",
    "BackendNotSupportedError",
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
]
