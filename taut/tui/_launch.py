"""Launch-decision logic for the Taut TUI.

Pure module: importable without Textual so the CLI never pays for the TUI
(spec 04 [TUI-4.3]; plan INV-6). Owns the missing-extra error type and the
CLI-vs-TUI decision for no-verb invocations ([TUI-5]).
"""

from __future__ import annotations

import sys
from dataclasses import dataclass

# Single source for the missing-extra message (review F7): the exception is
# raised with it and the CLI composes its own line around it, so the two
# never drift.
INSTALL_HINT = 'TUI extra not installed. Install it with: pipx inject taut "taut[tui]"'


class MissingTuiExtraError(Exception):
    """The ``taut[tui]`` extra (Textual) is not installed ([TUI-5.1]).

    Deliberately not an ImportError subclass: the launch site catches only
    this type, so a genuine ImportError from a broken TUI submodule
    propagates as a real error instead of being mis-reported as a missing
    extra (plan review findings 6 + R2-3).
    """


def stdin_isatty() -> bool:
    return sys.stdin.isatty()


def stdout_isatty() -> bool:
    return sys.stdout.isatty()


@dataclass(frozen=True, slots=True)
class LaunchDecision:
    """Outcome of the no-verb dispatch decision ([TUI-5.4])."""

    launch_tui: bool
    db_path: str | None = None
    as_name: str | None = None
    token: str | None = None


def decide(
    *,
    has_verb: bool,
    db_path: str | None,
    as_name: str | None,
    token: str | None,
    json_flag: bool,
    timestamps: bool,
    quiet: bool,
    stdin_isatty: bool,
    stdout_isatty: bool,
) -> LaunchDecision:
    """Decide CLI vs. TUI for an invocation with no subcommand.

    Inputs come from the argparse namespace ``main()`` already holds —
    never from re-parsed argv, so ``--db X`` and ``--db=X`` behave
    identically by construction (finding R4-4). ``--help``/``--version``
    never reach this function; they are argparse actions that exit first
    (INV-2). Either non-tty end forces the CLI path so agents and
    pipelines never hang ([TUI-5.3], INV-3).
    """

    if has_verb:
        return LaunchDecision(launch_tui=False)
    if json_flag or timestamps or quiet:
        # Output-only flags are meaningless for an interactive app (INV-4).
        return LaunchDecision(launch_tui=False)
    if not (stdin_isatty and stdout_isatty):
        return LaunchDecision(launch_tui=False)
    return LaunchDecision(
        launch_tui=True, db_path=db_path, as_name=as_name, token=token
    )
