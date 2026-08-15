"""Terminal and optional-dependency preflight for the real TUI app."""

from __future__ import annotations

import importlib
import sys
from typing import Any, TextIO

from taut_tui import MissingTuiDependencyError, TuiLaunchError

_INSTALL_HINT = (
    "The taut-tui installation is missing its Textual dependency; "
    "reinstall it with: pip install 'taut-tui'"
)


def run_tui(
    *,
    db_path: str | None,
    as_name: str | None,
    continuity_token: str | None,
) -> int:
    """Launch the TUI after proving terminal and dependency availability."""

    if not _is_tty(sys.stdin) or not _is_tty(sys.stdout):
        raise TuiLaunchError("taut tui requires interactive input and output terminals")

    _import_textual()
    app_module = importlib.import_module("taut_tui.app")
    app_type: Any = app_module.TautApp
    app = app_type(
        db_path=db_path,
        as_name=as_name,
        continuity_token=continuity_token,
    )
    app.run()
    retained_fatal = _retained_textual_fatal(app)
    if retained_fatal is not None:
        from taut.debug import capture_exception

        capture_exception(
            retained_fatal,
            db_path=db_path,
            surface="tui",
            operation="tui.fatal",
        )
    return 0


def _is_tty(stream: TextIO) -> bool:
    try:
        return stream.isatty()
    except (AttributeError, OSError, ValueError):
        return False


def _import_textual() -> None:
    try:
        importlib.import_module("textual")
    except ModuleNotFoundError as exc:
        if exc.name != "textual":
            raise
        raise MissingTuiDependencyError(_INSTALL_HINT) from None


def _retained_textual_fatal(app: Any) -> Exception | None:
    """Return Textual's retained callback failure without affecting launch."""

    try:
        failure = getattr(app, "_exception", None)
    except BaseException:  # noqa: BLE001 approved [DOM-10.2.1] [RUFF-SUP-090] exception
        return None
    return failure if isinstance(failure, Exception) else None


__all__ = ["run_tui"]
