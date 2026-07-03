"""Taut TUI package.

Spec: docs/specs/04-taut-tui.md. This package imports WITHOUT Textual
(INV-6, [TUI-4.3]); Textual is imported lazily inside :func:`run_tui`,
the single lazy import point. The TUI is a pure consumer of
``TautClient``/``TautClient.watch()`` ([TUI-4.2]) behind the ``taut[tui]``
extra ([TUI-4.1]).
"""

from __future__ import annotations

from taut.tui._launch import MissingTuiExtraError

__all__ = ["MissingTuiExtraError", "run_tui"]


def run_tui(
    *,
    db_path: str | None = None,
    as_name: str | None = None,
    token: str | None = None,
) -> int:
    """Start the TUI, returning a process exit code.

    Raises :class:`MissingTuiExtraError` when Textual is not installed —
    the only condition the CLI translates into the [TUI-5.1] install hint.
    Any other import failure is a real bug and propagates (finding R2-3).
    """

    try:
        import textual  # noqa: F401  # probe only ([TUI-5.1])
    except ImportError as exc:
        if exc.name != "textual":
            # textual is installed but broken (e.g. a missing transitive
            # dependency): a real bug, not a missing extra. The install
            # hint would mislead (Task 1 slice-review finding).
            raise
        raise MissingTuiExtraError(
            'TUI extra not installed. Install it with: pipx inject taut "taut[tui]"'
        ) from exc
    from taut.tui.app import run_app  # Textual present: the real import.

    return run_app(db_path=db_path, as_name=as_name, token=token)
