"""Lazy public launch facade for Taut's optional terminal interface."""

from __future__ import annotations


class TuiLaunchError(Exception):
    """A user-facing failure before or during TUI startup."""


class MissingTuiDependencyError(TuiLaunchError):
    """The extension's required Textual dependency is not installed."""


def launch(
    *,
    db_path: str | None,
    as_name: str | None,
    auth_token: str | None,
) -> int:
    """Validate and launch the optional TUI without eager framework imports."""

    from taut_tui._launch import run_tui

    return run_tui(
        db_path=db_path,
        as_name=as_name,
        auth_token=auth_token,
    )


__all__ = ["MissingTuiDependencyError", "TuiLaunchError", "launch"]
