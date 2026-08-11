"""Shared target resolution for actor-free read and maintenance operations."""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any

from simplebroker import BrokerTarget, resolve_broker_target

from taut._constants import NO_DATABASE_MESSAGE, load_config
from taut._exceptions import NotInitializedError, TautError


def resolve_existing_target(
    db_path: str | Path | None,
) -> tuple[BrokerTarget | str, dict[str, Any]]:
    """Resolve an existing workspace without creating a SQLite target."""

    config = load_config()
    explicit = db_path or os.environ.get("TAUT_DB")
    if explicit is not None:
        path = Path(explicit).expanduser()
        if not path.exists():
            raise NotInitializedError(NO_DATABASE_MESSAGE)
        return str(path), config
    try:
        target = resolve_broker_target(Path.cwd(), config=config)
    except tomllib.TOMLDecodeError as exc:
        raise TautError(f"invalid project configuration: {exc}") from exc
    except RuntimeError as exc:
        raise TautError(str(exc)) from exc
    if target is None:
        raise NotInitializedError(NO_DATABASE_MESSAGE)
    if target.backend_name == "sqlite" and not Path(target.target).exists():
        raise NotInitializedError(NO_DATABASE_MESSAGE)
    return target, config


def display_target(target: BrokerTarget | str) -> str:
    """Return a credential-safe label for a resolved broker target."""

    return target if isinstance(target, str) else target.display_target
