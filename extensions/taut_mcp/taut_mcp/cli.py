"""Console entry point for the Taut MCP stdio server."""

from __future__ import annotations

import argparse
import asyncio
import os
from collections.abc import Sequence
from typing import Never

import anyio

from .server import SERVER_VERSION, run_server

FATAL_SERVER_ERROR = b"taut-mcp: fatal server error\n"


def _is_broken_transport(error: BaseException) -> bool:
    if isinstance(
        error,
        (BrokenPipeError, anyio.BrokenResourceError, anyio.ClosedResourceError),
    ):
        return True
    if isinstance(error, BaseExceptionGroup):
        return bool(error.exceptions) and all(
            _is_broken_transport(item) for item in error.exceptions
        )
    return False


def _silence_broken_stdout() -> None:
    """Prevent Python's final stdout flush from turning a clean exit into 120."""

    try:
        replacement = os.open(os.devnull, os.O_WRONLY)
        try:
            os.dup2(replacement, 1)
        finally:
            os.close(replacement)
    except OSError:
        pass


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> Never:
        self.exit(1, f"{self.prog}: error: {message}\n")


def _parser() -> argparse.ArgumentParser:
    parser = _Parser(prog="taut-mcp")
    parser.add_argument(
        "--claude-channel",
        action="store_true",
        help="enable the experimental Claude channel wake hint",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {SERVER_VERSION}",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    """Parse launch-only flags and run the connection-scoped server."""

    parser = _parser()
    args = parser.parse_args(argv)
    try:
        asyncio.run(run_server(claude_channel=bool(args.claude_channel)))
    except Exception as exc:
        if _is_broken_transport(exc):
            _silence_broken_stdout()
            return
        try:
            os.write(2, FATAL_SERVER_ERROR)
        except OSError:
            pass
        raise SystemExit(1) from None
