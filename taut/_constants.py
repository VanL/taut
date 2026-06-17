"""Constants and SimpleBroker configuration translation for taut.

Spec references:
- docs/specs/02-taut-core.md [TAUT-3.2], [TAUT-4.1], [TAUT-5.2], [TAUT-5.4]
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from typing import Any, Final

from simplebroker import resolve_config

__version__: Final[str] = "0.1.1"

DEFAULT_DB_NAME: Final[str] = ".taut.db"
PROJECT_CONFIG_NAME: Final[str] = ".taut.toml"
SCHEMA_VERSION: Final[int] = 1
META_QUEUE_NAME: Final[str] = "taut_meta"
QUEUE_PRIORITY_NORMAL: Final[int] = 100
WATCH_MEMBERSHIP_REFRESH_SECONDS: Final[float] = 0.5

ROOM_NAME_RE: Final[re.Pattern[str]] = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
HANDLE_RE: Final[re.Pattern[str]] = ROOM_NAME_RE
MESSAGE_ID_RE: Final[re.Pattern[str]] = re.compile(r"^[0-9]{19}$")

SHELL_BASENAMES: Final[tuple[str, ...]] = (
    "sh",
    "bash",
    "zsh",
    "fish",
    "dash",
    "ksh",
    "csh",
    "tcsh",
)

WRAPPER_BASENAMES: Final[tuple[str, ...]] = (
    "env",
    "command",
    "timeout",
    "xargs",
    "nohup",
    "setsid",
    "script",
    "uv",
    "uvx",
    "npx",
)

INFRASTRUCTURE_BASENAMES: Final[tuple[str, ...]] = (
    "tmux",
    "screen",
    "sshd",
    "login",
    "loginwindow",
    "terminal",
    "terminal.app",
    "iterm",
    "iterm2",
    "wezterm",
    "alacritty",
    "kitty",
    "ghostty",
    "launchd",
    "systemd",
    "init",
)

PER_BASENAME_HANDLE_POOLS: Final[dict[str, tuple[str, ...]]] = {
    "claude": ("claudette", "claudius", "claudion", "claudine"),
    "codex": ("codette", "codexter", "codius", "codine"),
    "gemini": ("gemina", "geminus", "gemma", "gem"),
    "qwen": ("qwenda", "qwenton", "qwin", "qwendolyn"),
    "kimi": ("kimia", "kimiko", "kim", "kimber"),
    "grok": ("grokkette", "grokus", "grokker", "grokin"),
}

HISTORICAL_HANDLE_POOL: Final[tuple[str, ...]] = (
    "ada",
    "grace",
    "blaise",
    "hypatia",
    "kurt",
    "alan",
    "alonzo",
    "edsger",
    "barbara",
    "margaret",
    "donald",
    "judea",
)

NO_DATABASE_MESSAGE: Final[str] = (
    "No taut database found. Run 'taut init' to create one."
)


def load_config(overrides: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Return SimpleBroker config with taut's public ``TAUT_*`` surface translated.

    Taut exposes only ``TAUT_DB``, ``TAUT_AS``, and ``TAUT_TOKEN``. Only
    ``TAUT_DB`` affects broker config; identity environment is consumed by the
    client layer. The three broker keys below are the full project-resolution
    contract for [TAUT-3.2].
    """

    raw: dict[str, Any] = {
        "BROKER_DEFAULT_DB_NAME": os.environ.get("TAUT_DB", DEFAULT_DB_NAME),
        "BROKER_PROJECT_SCOPE": True,
        "BROKER_PROJECT_CONFIG_NAME": PROJECT_CONFIG_NAME,
    }
    if overrides:
        raw.update(overrides)
    return resolve_config(raw)


def normalize_handle_seed(seed: str | None, *, fallback: str = "agent") -> str:
    """Turn an executable/login seed into a valid deterministic handle stem."""

    candidate = (seed or fallback).strip().lower()
    candidate = candidate.rsplit("/", 1)[-1]
    candidate = re.sub(r"[^a-z0-9_-]+", "-", candidate).strip("-_")
    if not candidate or not candidate[0].isalnum():
        candidate = fallback
    return candidate[:64]


def validate_handle(handle: str) -> None:
    """Raise ``ValueError`` if *handle* is not a taut handle."""

    if HANDLE_RE.fullmatch(handle) is None:
        raise ValueError("handle must match ^[a-z0-9][a-z0-9_-]{0,63}$")
