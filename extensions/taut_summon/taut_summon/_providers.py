"""Registered provider names shared by lazy help and controller surfaces ([SUM-7.2], [SUM-13]).

Kept separate from `_adapter.py` because `taut summon --help`, `taut-summon run --help`,
and `SummonController.provider_names()` enforce a strict no-`_adapter` lazy-import fence.
`_adapter._FACTORIES` derives its harness entries directly from `PROVIDER_NAMES`.
"""

from __future__ import annotations

PROVIDER_NAMES: tuple[str, ...] = (
    "agy",
    "claude",
    "coder",
    "codex",
    "gemini",
    "grok",
    "kimi",
    "opencode",
    "pi",
    "pty",
    "qwen",
    "scripted",
)


def provider_names() -> tuple[str, ...]:
    """Return sorted registered provider names."""

    return PROVIDER_NAMES


__all__ = ["PROVIDER_NAMES", "provider_names"]
