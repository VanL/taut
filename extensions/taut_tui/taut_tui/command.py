"""Lightweight adapter for the explicit ``taut tui`` command.

Spec references:
- docs/specs/10-taut-tui.md [TUI-3.1], [TUI-3.2]
"""

from __future__ import annotations

import argparse

from taut.commands import CommandArgumentParser, CommandContext


class _TuiCommand:
    def configure_parser(self, parser: CommandArgumentParser) -> None:
        del parser

    def run(self, context: CommandContext, args: argparse.Namespace) -> int:
        del args
        unsupported = [
            spelling
            for enabled, spelling in (
                (context.json, "--json"),
                (context.timestamps, "--timestamps"),
                (context.quiet, "--quiet"),
            )
            if enabled
        ]
        if unsupported:
            joined = ", ".join(unsupported)
            context.stderr.write(f"taut tui does not accept {joined}\n")
            return 1

        from taut_tui import launch

        return launch(
            db_path=context.db_path,
            as_name=context.as_name,
            continuity_token=context.continuity_token,
        )


def create_command() -> _TuiCommand:
    return _TuiCommand()


__all__ = ["create_command"]
