"""Constants and SimpleBroker configuration translation for taut.

Spec references:
- docs/specs/02-taut-core.md [TAUT-3.2] (config translation), [TAUT-4.1]
  (naming), [TAUT-5] (identity and recognition, detailed in spec 03)
- docs/specs/03-identity-addressing-notifications.md [IAN-3] (member-id and
  claim-hash formats, anchor evidence), [IAN-4] (name validation and route
  keys), [IAN-6] (reserved queue namespace)
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:
    from simplebroker import ResolvedConfig

__version__: Final[str] = "0.9.6"

DEFAULT_DB_NAME: Final[str] = ".taut.db"
PROJECT_CONFIG_NAME: Final[str] = ".taut.toml"
SCHEMA_VERSION: Final[int] = 2
META_QUEUE_NAME: Final[str] = "taut_meta"
QUEUE_PRIORITY_NORMAL: Final[int] = 100
WATCH_MEMBERSHIP_REFRESH_SECONDS: Final[float] = 0.5

CHANNEL_NAME_RE: Final[re.Pattern[str]] = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
MEMBER_NAME_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
MEMBER_ID_RE: Final[re.Pattern[str]] = re.compile(r"^m_[a-z0-9]{26,52}$")
CLAIM_HASH_RE: Final[re.Pattern[str]] = re.compile(r"^ic_[a-z0-9]{52}$")
MESSAGE_ID_RE: Final[re.Pattern[str]] = re.compile(r"^[0-9]{19}$")
REACTION_SLUG_RE: Final[re.Pattern[str]] = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")
RESERVED_QUEUE_PREFIXES: Final[frozenset[str]] = frozenset(
    {"dm", "notify", "sys", "taut"}
)


SHELL_BASENAMES: Final[tuple[str, ...]] = (
    "sh",
    "bash",
    "zsh",
    "fish",
    "dash",
    "ksh",
    "csh",
    "tcsh",
    "cmd",
    "powershell",
    "pwsh",
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

PER_BASENAME_NAME_POOLS: Final[dict[str, tuple[str, ...]]] = {
    "claude": ("Claudette", "Claudius", "Claudion", "Claudine"),
    "codex": ("Codette", "Codexter", "Codius", "Codine"),
    "gemini": ("Gemina", "Geminus", "Gemma", "Gem"),
    "pi": ("Tau", "Phi"),
    "qwen": ("Qwenda", "Qwenton", "Qwin", "Qwendolyn"),
    "kimi": ("Kimia", "Kimiko", "Kim", "Kimber"),
    "grok": ("Grokkette", "Grokus", "Grokker", "Grokin"),
}

HISTORICAL_NAME_POOL: Final[tuple[str, ...]] = (
    "Ada",
    "Grace",
    "Blaise",
    "Hypatia",
    "Kurt",
    "Alan",
    "Alonzo",
    "Edsger",
    "Barbara",
    "Margaret",
    "Donald",
    "Judea",
)

NO_DATABASE_MESSAGE: Final[str] = (
    "No taut database found. Run 'taut init' to create one."
)


# These defaults encode behavior that is important to Taut. Keep them first.
_TAUT_BROKER_DEFAULTS: Final[dict[str, str]] = {
    "TAUT_DEFAULT_DB_LOCATION": "",
    "TAUT_DEFAULT_DB_NAME": DEFAULT_DB_NAME,
    "TAUT_PROJECT_CONFIG_PATH": "",
    "TAUT_PROJECT_CONFIG_NAME": PROJECT_CONFIG_NAME,
    "TAUT_PROJECT_SCOPE": "1",
    "TAUT_BACKEND": "sqlite",
    "TAUT_LOAD_MAX_FUTURE_SKEW_SECONDS": "300",
    # The remaining named values merely mirror SimpleBroker defaults. Almost
    # all have nothing to do with Taut product policy; they are present so the
    # complete lower-layer config is isolated from ambient BROKER_* settings.
    "TAUT_BUSY_TIMEOUT": "5000",
    "TAUT_CACHE_MB": "10",
    "TAUT_SYNC_MODE": "FULL",
    "TAUT_WAL_AUTOCHECKPOINT": "1000",
    "TAUT_MAX_MESSAGE_SIZE": "10485760",
    "TAUT_READ_COMMIT_INTERVAL": "1",
    "TAUT_GENERATOR_BATCH_SIZE": "100",
    "TAUT_AUTO_VACUUM": "1",
    "TAUT_AUTO_VACUUM_INTERVAL": "100",
    "TAUT_VACUUM_THRESHOLD": "10",
    "TAUT_VACUUM_BATCH_SIZE": "1000",
    "TAUT_SKIP_IDLE_CHECK": "0",
    "TAUT_JITTER_FACTOR": "0.15",
    "TAUT_INITIAL_CHECKS": "100",
    "TAUT_MAX_INTERVAL": "0.1",
    "TAUT_BURST_SLEEP": "0.00001",
    "TAUT_DEBUG": "",
    "TAUT_LOGGING_ENABLED": "0",
    "TAUT_BACKEND_HOST": "localhost",
    "TAUT_BACKEND_PORT": "5432",
    "TAUT_BACKEND_USER": "postgres",
    "TAUT_BACKEND_PASSWORD": "",
    "TAUT_BACKEND_DATABASE": "simplebroker",
    "TAUT_BACKEND_SCHEMA": "simplebroker_pg_v1",
    "TAUT_BACKEND_TARGET": "",
}

_CONFIG_COMPATIBILITY_ERROR: Final[str] = (
    "incompatible SimpleBroker configuration schema: "
    "Taut's complete configuration mapping must be updated"
)


def _broker_config_key(taut_key: str) -> str:
    return f"BROKER_{taut_key.removeprefix('TAUT_')}"


def _required_broker_config_keys() -> frozenset[str]:
    return frozenset(_broker_config_key(key) for key in _TAUT_BROKER_DEFAULTS)


def _require_supported_broker_keys(config: Mapping[str, Any]) -> None:
    if not _required_broker_config_keys().issubset(config):
        raise RuntimeError(_CONFIG_COMPATIBILITY_ERROR)


def freeze_broker_config(config: Mapping[str, Any]) -> ResolvedConfig:
    """Recreate a complete ambient-free broker mapping at an ownership boundary."""

    from simplebroker import resolve_isolated_config

    _require_supported_broker_keys(config)
    _require_supported_broker_keys(resolve_isolated_config({}))
    resolved = resolve_isolated_config(config)
    _require_supported_broker_keys(resolved)
    return resolved


def load_config(
    overrides: Mapping[str, Any] | None = None,
) -> ResolvedConfig:
    """Return SimpleBroker config with taut's public ``TAUT_*`` surface translated.

    The returned nominal mapping is complete and ambient-free. ``TAUT_AS`` and
    ``TAUT_TOKEN`` remain identity inputs consumed by the client layer.
    """

    from simplebroker import resolve_isolated_config
    from simplebroker.ext import InvalidConfigError

    explicit = dict(overrides or {})
    unknown = set(explicit).difference(_TAUT_BROKER_DEFAULTS)
    if unknown:
        key = min(unknown, key=str)
        raise ValueError(f"unknown Taut configuration key: {key}")

    raw: dict[str, Any] = {
        key: os.environ.get(key, default)
        for key, default in _TAUT_BROKER_DEFAULTS.items()
    }
    taut_db = os.environ.get("TAUT_DB")
    if taut_db is not None:
        raw["TAUT_DEFAULT_DB_LOCATION"] = (
            os.path.dirname(taut_db) if os.path.isabs(taut_db) else ""
        )
        raw["TAUT_DEFAULT_DB_NAME"] = (
            os.path.basename(taut_db) if os.path.isabs(taut_db) else taut_db
        )
    raw.update(explicit)
    translated = {_broker_config_key(key): value for key, value in raw.items()}

    _require_supported_broker_keys(resolve_isolated_config({}))
    try:
        resolved = resolve_isolated_config(translated)
    except InvalidConfigError as exc:
        taut_key = f"TAUT_{exc.key.removeprefix('BROKER_')}"
        if taut_key not in _TAUT_BROKER_DEFAULTS:
            raise RuntimeError(_CONFIG_COMPATIBILITY_ERROR) from exc
        raise ValueError(
            f"invalid configuration {taut_key}={exc.value_display}: "
            f"expected {exc.expected}"
        ) from exc

    _require_supported_broker_keys(resolved)
    return resolved


def normalize_name_seed(seed: str | None, *, fallback: str = "agent") -> str:
    """Turn an executable/login seed into a valid deterministic name stem."""

    candidate = (seed or fallback).strip().lower()
    candidate = candidate.rsplit("/", 1)[-1]
    candidate = re.sub(r"[^a-z0-9_-]+", "-", candidate).strip("-_")
    if not candidate or not candidate[0].isalnum():
        candidate = fallback
    return candidate[:64]


def capitalize_automatic_name(name: str) -> str:
    """Uppercase the first lowercase ASCII letter in an automatic name."""

    for index, character in enumerate(name):
        if "a" <= character <= "z":
            return f"{name[:index]}{character.upper()}{name[index + 1 :]}"
    return name


def route_key(name: str) -> str:
    """Return the normalized route key for a member name or alias."""

    return name.lower()


def validate_member_name(name: str) -> None:
    """Raise ``ValueError`` if *name* is not a routable member name."""

    if MEMBER_NAME_RE.fullmatch(name) is None:
        raise ValueError("name must match ^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


def validate_channel_name(name: str) -> None:
    """Raise ``ValueError`` if *name* is not a top-level channel name."""

    if CHANNEL_NAME_RE.fullmatch(name) is None:
        raise ValueError("channel must match ^[a-z0-9][a-z0-9_-]{0,63}$")
    if name in RESERVED_QUEUE_PREFIXES:
        raise ValueError(f"{name} is reserved")
