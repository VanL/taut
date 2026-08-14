"""Shared target resolution for actor-free read and maintenance operations."""

from __future__ import annotations

import os
import tomllib
from pathlib import Path

from simplebroker import BrokerTarget, ResolvedConfig, resolve_broker_target

from taut._constants import NO_DATABASE_MESSAGE, load_config
from taut._exceptions import NotInitializedError, TautError

_MISSING_POSTGRES_PLUGIN_ERROR = "Unknown backend plugin: postgres"
_MISSING_POSTGRES_PLUGIN_HINT = (
    "Install taut-pg in the same environment as taut to enable Postgres project configs"
)


def backend_install_hint_error(exc: RuntimeError) -> TautError | None:
    """Return Taut's extension hint only for a missing PostgreSQL backend."""

    message = str(exc)
    if (
        _MISSING_POSTGRES_PLUGIN_ERROR in message
        or "Requested backend 'postgres' is not available" in message
    ):
        return TautError(
            f"{_MISSING_POSTGRES_PLUGIN_ERROR}. {_MISSING_POSTGRES_PLUGIN_HINT}."
        )
    return None


def resolve_existing_target(
    db_path: str | Path | None,
) -> tuple[BrokerTarget | str, ResolvedConfig]:
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
        raise (backend_install_hint_error(exc) or TautError(str(exc))) from exc
    if target is None:
        raise NotInitializedError(NO_DATABASE_MESSAGE)
    if target.backend_name == "sqlite" and not Path(target.target).exists():
        raise NotInitializedError(NO_DATABASE_MESSAGE)
    return target, config


def display_target(target: BrokerTarget | str) -> str:
    """Return a credential-safe label for a resolved broker target."""

    return target if isinstance(target, str) else target.display_target
