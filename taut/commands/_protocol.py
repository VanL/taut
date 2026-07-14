"""Version-1 command manifest, adapter, parser, and execution context.

Spec references:
- docs/specs/02-taut-core.md [TAUT-8.1], [TAUT-8.3], [TAUT-8.6]
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from functools import partial
from typing import TYPE_CHECKING, Any, NoReturn, Protocol, TextIO, TypeAlias

if TYPE_CHECKING:
    from taut.client import TautClient


class GlobalOption(Enum):
    """Closed root-global vocabulary that a command may accept post-verb."""

    DB = "db"
    AS = "as"
    TOKEN = "token"
    JSON = "json"
    TIMESTAMPS = "timestamps"
    QUIET = "quiet"


@dataclass(frozen=True, slots=True)
class CommandSpec:
    """Lightweight metadata loaded without importing command execution code."""

    command_api_version: int
    name: str
    summary: str
    post_verb_globals: frozenset[GlobalOption]
    implementation: str


class CommandArgumentParser(argparse.ArgumentParser):
    """Core-owned command parser with exit-1 usage and injected streams."""

    def __init__(
        self,
        *args: Any,
        stdout: TextIO | None = None,
        stderr: TextIO | None = None,
        **kwargs: Any,
    ) -> None:
        self.stdout = stdout if stdout is not None else sys.stdout
        self.stderr = stderr if stderr is not None else sys.stderr
        self._taut_intermixed_args = False
        super().__init__(*args, **kwargs)

    def enable_intermixed_args(self) -> None:
        """Allow optionals between positionals for this top-level command.

        This is opt-in because argparse does not support intermixed parsing for
        every action shape, including nested subparsers and ``REMAINDER``.
        """

        self._taut_intermixed_args = True

    def parse_command_args(self, args: list[str]) -> argparse.Namespace:
        """Parse a dispatcher-owned tail with the adapter's selected policy."""

        # Python 3.11's intermixed parser drops a leading ``--`` while it
        # temporarily disables positionals, then reports those positionals as
        # missing. Ordinary argparse already handles this literal-only shape.
        if self._taut_intermixed_args and (not args or args[0] != "--"):
            return self.parse_intermixed_args(args)
        return self.parse_args(args)

    def error(self, message: str) -> NoReturn:
        self.print_usage(self.stderr)
        self.exit(1, f"{self.prog}: error: {message}\n")

    def exit(self, status: int = 0, message: str | None = None) -> NoReturn:
        if message:
            from taut.commands._rendering import write_human_line

            write_human_line(
                self.stdout if status == 0 else self.stderr,
                message.removesuffix("\n"),
            )
        raise SystemExit(status)

    def print_help(self, file: Any = None) -> None:
        super().print_help(file if file is not None else self.stdout)

    def print_usage(self, file: Any = None) -> None:
        super().print_usage(file if file is not None else self.stdout)

    def add_subparsers(self, **kwargs: Any) -> Any:
        parser_class = kwargs.pop("parser_class", CommandArgumentParser)
        if parser_class is not CommandArgumentParser:
            raise TypeError("nested command parsers must use CommandArgumentParser")
        kwargs["parser_class"] = partial(
            CommandArgumentParser,
            stdout=self.stdout,
            stderr=self.stderr,
        )
        return super().add_subparsers(**kwargs)

    def _get_option_tuples(self, option_string: str) -> list[tuple[Any, ...]]:
        """Keep core globals exact while preserving adapter abbreviations.

        Argparse has one parser-wide ``allow_abbrev`` switch. Core globals and
        command-local options share this parser so that declared globals remain
        visible in command help. Filtering only core-owned actions preserves
        the released command-local abbreviation behavior without inventing
        abbreviated spellings for post-verb globals.
        """

        option_prefix = option_string.partition("=")[0]
        return [
            option_tuple
            for option_tuple in super()._get_option_tuples(option_string)
            if not str(option_tuple[0].dest).startswith("_root_")
            or option_tuple[1] == option_prefix
        ]


class CommandContext:
    """Resolved root options, authoritative streams, and one lazy client."""

    __slots__ = (
        "_client_factory",
        "_client_instance",
        "as_name",
        "auth_token",
        "db_path",
        "json",
        "quiet",
        "stderr",
        "stdin",
        "stdout",
        "timestamps",
    )

    def __init__(
        self,
        *,
        db_path: str | None,
        as_name: str | None,
        auth_token: str | None,
        json: bool,
        timestamps: bool,
        quiet: bool,
        stdin: TextIO,
        stdout: TextIO,
        stderr: TextIO,
        _client_factory: Callable[..., TautClient] | None = None,
    ) -> None:
        self.db_path = db_path
        self.as_name = as_name
        self.auth_token = auth_token
        self.json = json
        self.timestamps = timestamps
        self.quiet = quiet
        self.stdin = stdin
        self.stdout = stdout
        self.stderr = stderr
        self._client_factory = _client_factory
        self._client_instance: TautClient | None = None

    def client(self) -> TautClient:
        """Create and reuse the selected core client on first execution use."""

        if self._client_instance is None:
            factory = self._client_factory
            if factory is None:
                from taut.client import TautClient

                factory = TautClient
            self._client_instance = factory(
                db_path=self.db_path,
                as_name=self.as_name,
                token=self.auth_token,
            )
        return self._client_instance

    def close(self) -> None:
        """Close the lazily created client, if command execution created one."""

        if self._client_instance is not None:
            self._client_instance.close()


class Command(Protocol):
    """One selected command's parser configuration and execution behavior."""

    def configure_parser(self, parser: CommandArgumentParser) -> None: ...

    def run(self, context: CommandContext, args: argparse.Namespace) -> int: ...


CommandFactory: TypeAlias = Callable[[], Command]


class CommandError(Exception):
    """User-facing extension failure with a restricted shell exit class."""

    def __init__(self, message: str, exit_code: int = 1) -> None:
        if exit_code not in (1, 2):
            raise ValueError("command error exit_code must be 1 or 2")
        super().__init__(message)
        self.exit_code = exit_code
