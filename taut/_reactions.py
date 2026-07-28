"""Resolved-project reaction vocabulary for outbound message reactions.

Spec references:
- docs/specs/02-taut-core.md [TAUT-3.2], [TAUT-7.7]
"""

from __future__ import annotations

import tomllib
from importlib import resources
from pathlib import Path
from typing import Any, Final

from taut._constants import REACTION_SLUG_RE
from taut._exceptions import TautError

_PACKAGED_CONFIG_ERROR: Final[str] = "reaction configuration is unavailable"
_PROJECT_CONFIG_ERROR: Final[str] = (
    "invalid .taut.toml: [reactions].values must be a list of unique "
    "lowercase ASCII slugs"
)


def load_reaction_values(config_path: Path | None) -> tuple[str, ...]:
    """Load one immutable outbound vocabulary for a resolved client target."""

    packaged = _load_packaged_values()
    if config_path is None:
        return packaged
    try:
        with config_path.open("rb") as stream:
            document: dict[str, Any] = tomllib.load(stream)
        section = document.get("reactions")
        if section is None:
            return packaged
        if not isinstance(section, dict):
            raise TypeError
        if "values" not in section:
            return packaged
        return _validate_values(section["values"])
    except (
        OSError,
        TypeError,
        UnicodeError,
        ValueError,
        tomllib.TOMLDecodeError,
    ):
        raise TautError(_PROJECT_CONFIG_ERROR) from None


def _load_packaged_values() -> tuple[str, ...]:
    try:
        with resources.files("taut").joinpath("defaults.toml").open("rb") as stream:
            document: dict[str, Any] = tomllib.load(stream)
        section = document["reactions"]
        if not isinstance(section, dict):
            raise TypeError
        return _validate_values(section["values"])
    except (
        KeyError,
        OSError,
        TypeError,
        UnicodeError,
        ValueError,
        tomllib.TOMLDecodeError,
    ):
        raise TautError(_PACKAGED_CONFIG_ERROR) from None


def _validate_values(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise TypeError
    values = tuple(value)
    if any(
        not isinstance(item, str) or REACTION_SLUG_RE.fullmatch(item) is None
        for item in values
    ):
        raise ValueError
    if len(set(values)) != len(values):
        raise ValueError
    return values


__all__: list[str] = []
