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


_PROJECT_CONFIG_SHAPE_HINT = (
    "a project file needs version = 1, backend, and target; a file holding "
    "only [terminal_text] is display policy, not project storage"
)


def invalid_project_config_error(
    exc: tomllib.TOMLDecodeError | ValueError,
    project_config_name: str,
) -> TautError:
    """Translate a project-config failure into Taut's own diagnostic.

    SimpleBroker parses the file Taut selected but reports a syntax error
    without the filename and a shape error under its own default name
    (``.broker.toml``). A CLI diagnostic must name the file the user actually
    wrote, and a file that fails the shape check because it carries only the
    ``[terminal_text]`` table deserves to hear which keys are missing.
    """

    detail = str(exc).replace(".broker.toml", project_config_name)
    detail = detail.removeprefix(f"{project_config_name} ")
    if isinstance(exc, ValueError) and not isinstance(exc, tomllib.TOMLDecodeError):
        lowered = detail.lower()
        if "version" in lowered or "requires" in lowered:
            detail = f"{detail}; {_PROJECT_CONFIG_SHAPE_HINT}"
    return TautError(f"invalid {project_config_name}: {detail}")


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
    except (tomllib.TOMLDecodeError, ValueError) as exc:
        raise invalid_project_config_error(
            exc, str(config["BROKER_PROJECT_CONFIG_NAME"])
        ) from exc
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
