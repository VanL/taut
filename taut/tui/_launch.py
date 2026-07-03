"""Launch-decision logic for the Taut TUI.

Pure module: importable without Textual so the CLI never pays for the TUI
(spec 04 [TUI-4.3]; plan INV-6). Owns the missing-extra error type; the
CLI-vs-TUI launch decision itself lands here in the dispatch slice.
"""

from __future__ import annotations


class MissingTuiExtraError(Exception):
    """The ``taut[tui]`` extra (Textual) is not installed ([TUI-5.1]).

    Deliberately not an ImportError subclass: the launch site catches only
    this type, so a genuine ImportError from a broken TUI submodule
    propagates as a real error instead of being mis-reported as a missing
    extra (plan review findings 6 + R2-3).
    """
