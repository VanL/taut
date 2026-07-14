"""Temporary command bridge to the previous taut-summon CLI.

This module preserves the released ``taut summon`` and ``taut dismiss``
behavior until taut-summon publishes native command adapters. Its stream
redirection changes process-global ``sys`` streams while the legacy CLI runs,
so this bridge is not safe for concurrent in-process dispatch.

Removal condition: retain this bridge in the paired 0.6.0 release because it
supports taut-summon 0.5.4. It may be removed only in a later paired release
where 0.6.0 is the immediately previous supported Summon, 0.6.0 contains both
``taut.commands`` entry points, and the artifact policy no longer promises
0.5.4 compatibility.
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
from collections.abc import Iterator
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from typing import Any, TextIO

from taut.commands._protocol import CommandArgumentParser, CommandContext
from taut.commands._rendering import write_human_line


@contextmanager
def _redirect_stdin(stream: TextIO) -> Iterator[None]:
    previous = sys.stdin
    sys.stdin = stream
    try:
        yield
    finally:
        sys.stdin = previous


class _LineBufferedTerminalStream:
    """Escape legacy text records while preserving their LF framing."""

    def __init__(self, stream: TextIO) -> None:
        self._stream = stream
        self._buffer = ""

    def write(self, text: str) -> int:
        if not isinstance(text, str):
            raise TypeError("write() argument must be str")
        segments = text.split("\n")
        self._buffer += segments[0]
        for segment in segments[1:]:
            write_human_line(self._stream, self._buffer)
            self._buffer = segment
        return len(text)

    def flush(self) -> None:
        if self._buffer:
            write_human_line(self._stream, self._buffer)
            self._buffer = ""
        self._stream.flush()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._stream, name)


class SummonCompatibilityCommand:
    def __init__(self, *, source_verb: str, extension_verb: str) -> None:
        self._source_verb = source_verb
        self._extension_verb = extension_verb

    def configure_parser(self, parser: CommandArgumentParser) -> None:
        parser.description = (
            f"Delegate verbatim to 'taut-summon {self._extension_verb}'. "
            "The extension owns all remaining arguments."
        )
        parser.add_argument(
            "rest",
            metavar="ARG",
            nargs=argparse.REMAINDER,
            help=(
                f"Arguments passed verbatim to 'taut-summon {self._extension_verb}'."
            ),
        )

    def run(self, context: CommandContext, args: argparse.Namespace) -> int:
        if not args.rest or args.rest[0] != "--":
            raise RuntimeError("summon compatibility tail separator is missing")
        forwarded_tail = args.rest[1:]
        if importlib.util.find_spec("taut_summon") is None:
            context.stderr.write(
                f"taut {self._source_verb} requires the taut-summon extension "
                "(pipx inject taut taut-summon)\n"
            )
            return 1

        from taut_summon.cli import main as summon_main

        extension_argv = [self._extension_verb]
        if context.db_path:
            extension_argv.extend(("--db", context.db_path))
        extension_argv.extend(forwarded_tail)
        safe_stdout = _LineBufferedTerminalStream(context.stdout)
        safe_stderr = _LineBufferedTerminalStream(context.stderr)
        try:
            with (
                _redirect_stdin(context.stdin),
                redirect_stdout(safe_stdout),
                redirect_stderr(safe_stderr),
            ):
                return int(summon_main(extension_argv))
        except SystemExit as exc:
            if type(exc.code) is int and exc.code in (0, 1, 2):
                return exc.code
            raise
        finally:
            safe_stdout.flush()
            safe_stderr.flush()


def create_summon_command() -> SummonCompatibilityCommand:
    return SummonCompatibilityCommand(source_verb="summon", extension_verb="run")


def create_dismiss_command() -> SummonCompatibilityCommand:
    return SummonCompatibilityCommand(source_verb="dismiss", extension_verb="stop")
