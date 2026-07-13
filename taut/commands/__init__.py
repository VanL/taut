"""Public command-extension interface for Taut.

Spec references:
- docs/specs/02-taut-core.md [TAUT-8.3], [TAUT-8.6]
"""

from __future__ import annotations

from taut.commands._protocol import (
    Command,
    CommandArgumentParser,
    CommandContext,
    CommandError,
    CommandFactory,
    CommandSpec,
    GlobalOption,
)

__all__ = [
    "Command",
    "CommandArgumentParser",
    "CommandContext",
    "CommandError",
    "CommandFactory",
    "CommandSpec",
    "GlobalOption",
]
