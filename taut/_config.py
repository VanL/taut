"""Taut's SimpleBroker configuration declarations and resolver."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import replace
from typing import Any, Final

from simplebroker import DEFAULT_CONFIG, Config, ConfigField, resolve_config

from taut._constants import DEFAULT_DB_NAME, PROJECT_CONFIG_NAME

# One declaration object is shared by every resolution because SimpleBroker
# includes declaration identity in persistent process-session identity.
TAUT_CONFIG_DEFAULTS: Final[dict[str, ConfigField]] = dict(DEFAULT_CONFIG)
TAUT_CONFIG_DEFAULTS.update(
    {
        "DEFAULT_DB_NAME": replace(
            DEFAULT_CONFIG["DEFAULT_DB_NAME"], default=DEFAULT_DB_NAME
        ),
        "PROJECT_CONFIG_NAME": replace(
            DEFAULT_CONFIG["PROJECT_CONFIG_NAME"], default=PROJECT_CONFIG_NAME
        ),
        "PROJECT_SCOPE": replace(DEFAULT_CONFIG["PROJECT_SCOPE"], default=True),
        "DB": ConfigField("", "a Taut database path", str),
        "AS": ConfigField("", "a Taut identity name", str),
        "TOKEN": ConfigField("", "a Taut identity token", str, sensitive=True),
    }
)


def load_config(overrides: Mapping[str, Any] | None = None) -> Config:
    """Resolve Taut's namespace into one SimpleBroker Config snapshot."""

    return resolve_config(
        "TAUT",
        defaults=TAUT_CONFIG_DEFAULTS,
        env=os.environ,
        override=overrides,
    )
