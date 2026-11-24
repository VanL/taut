"""Console entry point for the Taut MCP stdio server."""

from __future__ import annotations

import argparse
import asyncio
import errno
import os
import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Never, cast

import anyio

from ._version import SERVER_VERSION

FATAL_SERVER_ERROR = b"taut-mcp: fatal server error\n"
_MEMBER_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_KNOWN_LAUNCH_ERRORS = frozenset(
    {
        "--workspace must be an absolute UTF-8 directory path",
        "--token requires --workspace",
        "--token must be a non-empty UTF-8 continuity token",
        "--as must match ^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$",
        "taut mcp accepts at most one of --token or --as",
        "argument --as: not allowed with argument --token",
        "argument --token: not allowed with argument --as",
        "argument --workspace: expected one argument",
        "argument --token: expected one argument",
        "argument --as: expected one argument",
    }
)


@dataclass(frozen=True, slots=True)
class McpLaunchDefaults:
    """Explicit server-scoped launch defaults configured via CLI flags."""

    workspace: str | None = None
    token: str | None = None
    as_name: str | None = None

    @property
    def has_identity_default(self) -> bool:
        return self.token is not None or self.as_name is not None

    @property
    def has_any_default(self) -> bool:
        return self.workspace is not None or self.has_identity_default


def _is_strict_utf8(value: str) -> bool:
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeEncodeError:
        return False
    return True


def validate_launch_defaults(defaults: McpLaunchDefaults) -> McpLaunchDefaults:
    """Validate launch defaults with fixed content-free diagnostics."""

    if defaults.workspace is not None and (
        not _is_strict_utf8(defaults.workspace) or not os.path.isabs(defaults.workspace)
    ):
        raise ValueError("--workspace must be an absolute UTF-8 directory path")
    if defaults.token is not None and defaults.as_name is not None:
        raise ValueError("taut mcp accepts at most one of --token or --as")
    if defaults.token is not None:
        if defaults.workspace is None:
            raise ValueError("--token requires --workspace")
        if not defaults.token or not _is_strict_utf8(defaults.token):
            raise ValueError("--token must be a non-empty UTF-8 continuity token")
    if defaults.as_name is not None and (
        not _is_strict_utf8(defaults.as_name)
        or _MEMBER_NAME_RE.fullmatch(defaults.as_name) is None
    ):
        raise ValueError("--as must match ^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
    return defaults


def extract_launch_defaults(args: argparse.Namespace) -> McpLaunchDefaults:
    """Extract and validate launch defaults from parsed CLI namespace."""

    return validate_launch_defaults(
        McpLaunchDefaults(
            workspace=getattr(args, "workspace", None),
            token=getattr(args, "token", None),
            as_name=getattr(args, "as_name", None),
        )
    )


def _emit_launch_error(parser: argparse.ArgumentParser, message: str) -> Never:
    text = (
        message
        if message in _KNOWN_LAUNCH_ERRORS
        else f"invalid launch arguments; run '{parser.prog} --help' for usage"
    )
    stream = getattr(parser, "stderr", sys.stderr)
    stream.write(f"{parser.prog}: error: {text}\n")
    raise SystemExit(1)


async def run_server(defaults: McpLaunchDefaults | None = None) -> None:
    """Load and run the protocol server only after a launch surface executes."""

    from .server import run_server as serve

    await serve(defaults)


def _is_broken_transport(error: BaseException) -> bool:
    if isinstance(
        error,
        (BrokenPipeError, anyio.BrokenResourceError, anyio.ClosedResourceError),
    ):
        return True
    # Windows reports EINVAL rather than EPIPE when the peer closes stdout.
    if os.name == "nt" and isinstance(error, OSError) and error.errno == errno.EINVAL:
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
        _emit_launch_error(self, message)


def _parser() -> argparse.ArgumentParser:
    parser = _Parser(prog="taut-mcp")
    configure_parser(parser)
    return parser


def configure_parser(parser: argparse.ArgumentParser) -> None:
    """Add the shared launch-only MCP arguments to one parser."""

    if not isinstance(parser, _Parser):
        cast(Any, parser).error = lambda message: _emit_launch_error(parser, message)
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {SERVER_VERSION}",
    )
    parser.add_argument(
        "--workspace",
        default=None,
        metavar="DIR",
        help="Default absolute workspace directory for omitted workspace tool inputs.",
    )
    identity_group = parser.add_mutually_exclusive_group()
    identity_group.add_argument(
        "--token",
        default=None,
        metavar="TOKEN",
        help="Default continuity token for the configured --workspace.",
    )
    identity_group.add_argument(
        "--as",
        dest="as_name",
        default=None,
        metavar="NAME",
        help="Default existing workspace member name or alias resolved read-only.",
    )


def run_process(defaults: McpLaunchDefaults | None = None) -> int:
    """Run the process-scoped server and map transport failures to shell status."""

    try:
        asyncio.run(run_server(defaults))
    except Exception as exc:  # noqa: BLE001 approved [DOM-10.2.1] [RUFF-SUP-065] exception
        if _is_broken_transport(exc):
            _silence_broken_stdout()
            return 0
        try:
            os.write(2, FATAL_SERVER_ERROR)
        except OSError:
            pass
        return 1
    return 0


def main(argv: Sequence[str] | None = None) -> None:
    """Parse launch-only flags and run the process-scoped server."""

    parser = _parser()
    args = parser.parse_args(argv)
    try:
        defaults = extract_launch_defaults(args)
    except ValueError as exc:
        _emit_launch_error(parser, str(exc))
    result = run_process(defaults)
    if result:
        raise SystemExit(result)
