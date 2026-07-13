"""Raw command selection, isolated parsing, execution, and cleanup.

Spec references:
- docs/specs/02-taut-core.md [TAUT-8.1], [TAUT-8.2], [TAUT-8.6]
"""

from __future__ import annotations

import argparse
import inspect
import re
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, TextIO

from taut._constants import __version__
from taut.commands._imports import resolve_import_target
from taut.commands._protocol import (
    CommandArgumentParser,
    CommandContext,
    CommandError,
    CommandSpec,
    GlobalOption,
)
from taut.commands._registry import (
    CommandRegistry,
    RegisteredCommand,
    is_core_builtin,
)


@dataclass(slots=True)
class _RootValues:
    db_path: str | None = None
    as_name: str | None = None
    auth_token: str | None = None
    json: bool = False
    timestamps: bool = False
    quiet: bool = False


class _UsageError(Exception):
    pass


_DEFAULT_REGISTRY: CommandRegistry | None = None
_STATIC_REGISTRY: CommandRegistry | None = None
_NEGATIVE_NUMBER_RE = re.compile(r"^-\d+$|^-\d*\.\d+$")
_ROOT_LONG_OPTIONS = (
    "--help",
    "--version",
    "--db",
    "--as",
    "--token",
    "--json",
    "--timestamps",
    "--quiet",
)


def dispatch(
    argv: Sequence[str],
    *,
    registry: CommandRegistry | None = None,
    stdin: TextIO | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
    client_factory: Callable[..., Any] | None = None,
) -> int:
    """Dispatch one argv through the version-1 command interface."""

    input_stream = stdin if stdin is not None else sys.stdin
    output_stream = stdout if stdout is not None else sys.stdout
    error_stream = stderr if stderr is not None else sys.stderr
    try:
        root, verb, tail, action, literal_tail = _split_root(list(argv))
    except _UsageError as exc:
        _write_usage_error(str(exc), error_stream)
        return 1

    if action == "version":
        output_stream.write(f"taut {__version__}\n")
        return 0

    command_registry = (
        registry
        if registry is not None
        else _registry_for_selected_verb(verb, action=action)
    )
    if action == "help":
        _write_root_help(
            command_registry,
            output_stream,
            diagnostics_stream=error_stream,
        )
        return 0
    if verb is None:
        _write_root_help(
            command_registry,
            error_stream,
            diagnostics_stream=error_stream,
        )
        return 1
    try:
        selected = command_registry.get(verb)
    except KeyError:
        _write_usage_error(f"unknown command: {verb}", error_stream)
        return 1
    if selected.error is not None or selected.spec is None:
        error_stream.write(f"{selected.error or f'command {verb!r} is unavailable'}\n")
        return 1

    try:
        if literal_tail:
            command_tail, post = ["--", *tail], _RootValues()
        else:
            command_tail, post = _extract_post_globals(tail, selected.spec)
        merged = _merge_globals(root, post)
    except _UsageError as exc:
        _write_usage_error(str(exc), error_stream, prog=f"taut {verb}")
        return 1
    try:
        command = _load_command(selected)
        parser = _build_command_parser(
            selected.spec,
            command,
            output_stream,
            error_stream,
        )
    except BaseException as exc:
        if isinstance(exc, KeyboardInterrupt):
            raise
        _write_selected_error(selected, exc, error_stream)
        return 1
    try:
        parse_tail = ["--", *command_tail] if selected.verbatim_tail else command_tail
        args = parser.parse_command_args(parse_tail)
    except SystemExit as exc:
        if type(exc.code) is int and exc.code in (0, 1):
            return exc.code
        error_stream.write(f"taut {verb}: unexpected SystemExit({exc.code!r})\n")
        return 1
    context = CommandContext(
        db_path=merged.db_path,
        as_name=merged.as_name,
        auth_token=merged.auth_token,
        json=merged.json,
        timestamps=merged.timestamps,
        quiet=merged.quiet,
        stdin=input_stream,
        stdout=output_stream,
        stderr=error_stream,
        _client_factory=client_factory,
    )
    primary: BaseException | None = None
    result = 1
    try:
        result = command.run(context, args)
        if result not in (0, 1, 2) or isinstance(result, bool):
            raise RuntimeError(
                f"command {verb!r} returned invalid exit value {result!r}; "
                "expected 0, 1, or 2"
            )
    except BaseException as exc:
        if isinstance(exc, KeyboardInterrupt):
            raise
        primary = exc
        result = _render_execution_error(context, exc)
    finally:
        try:
            context.close()
        except BaseException as exc:
            if isinstance(exc, KeyboardInterrupt):
                raise
            if primary is None:
                result = _render_execution_error(context, exc)
    return result


def _default_registry() -> CommandRegistry:
    # CLI dispatch is process-local and single-threaded. A threaded embedder may
    # race to build two equivalent immutable snapshots; the last assignment wins.
    global _DEFAULT_REGISTRY
    if _DEFAULT_REGISTRY is None:
        _DEFAULT_REGISTRY = CommandRegistry()
    return _DEFAULT_REGISTRY


def _static_registry() -> CommandRegistry:
    # This cache has the same benign single-threaded initialization contract.
    global _STATIC_REGISTRY
    if _STATIC_REGISTRY is None:
        _STATIC_REGISTRY = CommandRegistry(entry_points=())
    return _STATIC_REGISTRY


def _registry_for_selected_verb(
    verb: str | None,
    *,
    action: str | None,
) -> CommandRegistry:
    if action is None and verb is not None and is_core_builtin(verb):
        return _static_registry()
    return _default_registry()


def _split_root(
    argv: list[str],
) -> tuple[_RootValues, str | None, list[str], str | None, bool]:
    values = _RootValues()
    i = 0
    while i < len(argv):
        raw_token = argv[i]
        token = _canonicalize_root_long_option(raw_token)
        if token == "--":
            if i + 1 >= len(argv):
                return values, None, [], None, True
            return values, argv[i + 1], argv[i + 2 :], None, True
        if token in ("-h", "--help"):
            return values, None, [], "help", False
        if token == "--version":
            return values, None, [], "version", False
        bundle_action = _consume_root_short_bundle(token, values)
        if bundle_action == "help":
            return values, None, [], "help", False
        if bundle_action == "consumed":
            i += 1
            continue
        consume_argv = [token, *argv[i + 1 :]]
        consumed = _consume_global(consume_argv, 0, values, frozenset(GlobalOption))
        if consumed:
            i += consumed
            continue
        if token.startswith("-"):
            raise _UsageError(f"unrecognized root option: {token}")
        return values, token, argv[i + 1 :], None, False
    return values, None, [], None, False


def _consume_root_short_bundle(token: str, values: _RootValues) -> str | None:
    """Preserve argparse's released bundled ``-t``, ``-q``, and ``-h``."""

    if len(token) <= 2 or not token.startswith("-") or token.startswith("--"):
        return None
    flags = token[1:]
    if any(flag not in {"t", "q", "h"} for flag in flags):
        return None
    values.timestamps = values.timestamps or "t" in flags
    values.quiet = values.quiet or "q" in flags
    return "help" if "h" in flags else "consumed"


def _canonicalize_root_long_option(token: str) -> str:
    """Apply argparse-compatible unique long abbreviations before the verb."""

    if not token.startswith("--") or token == "--":
        return token
    option_prefix, separator, explicit_value = token.partition("=")
    matches = [
        spelling
        for spelling in _ROOT_LONG_OPTIONS
        if spelling.startswith(option_prefix)
    ]
    if len(matches) > 1:
        choices = ", ".join(matches)
        raise _UsageError(f"ambiguous option: {option_prefix} could match {choices}")
    if not matches:
        return token
    canonical = matches[0]
    return f"{canonical}={explicit_value}" if separator else canonical


def _extract_post_globals(
    tail: list[str],
    spec: CommandSpec,
) -> tuple[list[str], _RootValues]:
    values = _RootValues()
    remaining: list[str] = []
    i = 0
    while i < len(tail):
        token = tail[i]
        if token == "--":
            remaining.extend(tail[i:])
            break
        consumed = _consume_global(tail, i, values, spec.post_verb_globals)
        if consumed:
            i += consumed
            continue
        remaining.append(token)
        i += 1
    return remaining, values


def _consume_global(
    argv: list[str],
    index: int,
    values: _RootValues,
    allowed: frozenset[GlobalOption],
) -> int:
    token = argv[index]
    value_options = (
        (GlobalOption.DB, "--db", "db_path"),
        (GlobalOption.AS, "--as", "as_name"),
        (GlobalOption.TOKEN, "--token", "auth_token"),
    )
    for option, spelling, destination in value_options:
        if option not in allowed:
            continue
        if token == spelling:
            if index + 1 >= len(argv) or _looks_like_missing_option_value(
                argv[index + 1]
            ):
                raise _UsageError(f"argument {spelling}: expected one value")
            setattr(values, destination, argv[index + 1])
            return 2
        prefix = f"{spelling}="
        if token.startswith(prefix):
            setattr(values, destination, token[len(prefix) :])
            return 1
    flags = (
        (GlobalOption.JSON, ("--json",), "json"),
        (GlobalOption.TIMESTAMPS, ("-t", "--timestamps"), "timestamps"),
        (GlobalOption.QUIET, ("-q", "--quiet"), "quiet"),
    )
    for option, spellings, destination in flags:
        if option in allowed and token in spellings:
            setattr(values, destination, True)
            return 1
    return 0


def _looks_like_missing_option_value(token: str) -> bool:
    if token == "-":
        return False
    return token.startswith("-") and _NEGATIVE_NUMBER_RE.fullmatch(token) is None


def _merge_globals(before: _RootValues, after: _RootValues) -> _RootValues:
    return _RootValues(
        db_path=after.db_path if after.db_path is not None else before.db_path,
        as_name=after.as_name if after.as_name is not None else before.as_name,
        auth_token=(
            after.auth_token if after.auth_token is not None else before.auth_token
        ),
        json=before.json or after.json,
        timestamps=before.timestamps or after.timestamps,
        quiet=before.quiet or after.quiet,
    )


def _load_command(selected: RegisteredCommand) -> Any:
    assert selected.spec is not None
    factory = resolve_import_target(selected.spec.implementation)
    if not callable(factory):
        raise TypeError("implementation target is not callable")
    try:
        inspect.signature(factory).bind()
    except (TypeError, ValueError) as exc:
        raise TypeError(
            "implementation factory must be callable with no arguments"
        ) from exc
    command = factory()
    if not callable(getattr(command, "configure_parser", None)) or not callable(
        getattr(command, "run", None)
    ):
        raise TypeError("implementation factory did not return a command adapter")
    return command


def _build_command_parser(
    spec: CommandSpec,
    command: Any,
    stdout: TextIO,
    stderr: TextIO,
) -> CommandArgumentParser:
    parser = CommandArgumentParser(
        prog=f"taut {spec.name}",
        description=spec.summary,
        stdout=stdout,
        stderr=stderr,
    )
    _add_declared_globals(parser, spec.post_verb_globals)
    command.configure_parser(parser)
    return parser


def _add_declared_globals(
    parser: CommandArgumentParser,
    options: frozenset[GlobalOption],
) -> None:
    # Dispatch has already extracted every exact declared spelling. These
    # actions make globals visible in command help and make argparse reject
    # near-miss spellings; they are intentionally not a second value path.
    suppressed = argparse.SUPPRESS
    if GlobalOption.DB in options:
        parser.add_argument(
            "--db",
            dest="_root_db",
            metavar="PATH",
            default=suppressed,
            help="Use an explicit SQLite database path instead of project discovery.",
        )
    if GlobalOption.AS in options:
        parser.add_argument(
            "--as",
            dest="_root_as",
            metavar="NAME",
            default=suppressed,
            help="Act as the member with this current name or alias.",
        )
    if GlobalOption.TOKEN in options:
        parser.add_argument(
            "--token",
            dest="_root_token",
            metavar="TOKEN",
            default=suppressed,
            help=(
                "Select identity by continuity token. This provides continuity, "
                "not authentication."
            ),
        )
    if GlobalOption.JSON in options:
        parser.add_argument(
            "--json",
            dest="_root_json",
            action="store_true",
            default=suppressed,
            help=(
                "Emit successful stdout records as NDJSON; errors remain text on "
                "stderr."
            ),
        )
    if GlobalOption.TIMESTAMPS in options:
        parser.add_argument(
            "-t",
            "--timestamps",
            dest="_root_timestamps",
            action="store_true",
            default=suppressed,
            help="Show 19-digit message ids in human message output.",
        )
    if GlobalOption.QUIET in options:
        parser.add_argument(
            "-q",
            "--quiet",
            dest="_root_quiet",
            action="store_true",
            default=suppressed,
            help="Suppress ordinary output while preserving exit status.",
        )


def _write_root_help(
    registry: CommandRegistry,
    stream: TextIO,
    *,
    diagnostics_stream: TextIO,
) -> None:
    stream.write(
        "usage: taut [-h] [--db PATH] [--as NAME_OR_ALIAS] [--token TOKEN] "
        "[--json] [-t] [-q] [--version] COMMAND ...\n\n"
        "Coordinate humans and agents through durable project chat.\n"
        "Exit codes: 0 success; 1 error; 2 empty, nothing matched, or not found.\n"
        "JSON controls successful stdout records; errors remain text on stderr.\n\n"
        "options:\n"
        "  -h, --help       Show this help and exit.\n"
        "  --db PATH        Use an explicit SQLite database path instead of "
        "project discovery.\n"
        "  --as NAME_OR_ALIAS\n"
        "                   Act as the member with this current name or alias.\n"
        "  --token TOKEN    Select identity by continuity token. This provides "
        "continuity, not authentication.\n"
        "  --json           Emit successful stdout records as NDJSON; errors "
        "remain text on stderr.\n"
        "  -t, --timestamps Show 19-digit message ids in human message output.\n"
        "  -q, --quiet      Suppress ordinary output while preserving exit "
        "status.\n"
        "  --version        Show the Taut version and exit.\n\n"
        "commands:\n"
    )
    for command in registry.commands():
        summary = command.spec.summary if command.spec is not None else "unavailable"
        stream.write(f"  {command.name:<12} {summary}\n")
    diagnostics = {
        *registry.diagnostics(),
        *(
            command.error
            for command in registry.commands()
            if command.error is not None
        ),
    }
    for diagnostic in sorted(diagnostics):
        diagnostics_stream.write(f"warning: {diagnostic}\n")


def _write_usage_error(message: str, stream: TextIO, *, prog: str = "taut") -> None:
    stream.write(f"usage: {prog} ...\n{prog}: error: {message}\n")


def _write_selected_error(
    selected: RegisteredCommand,
    exc: BaseException,
    stream: TextIO,
) -> None:
    assert selected.spec is not None
    entry_point = (
        selected.entry_point.value
        if selected.entry_point is not None
        else "static built-in manifest"
    )
    stream.write(
        f"command {selected.name!r} from {selected.distribution_name} "
        f"{selected.distribution_version} failed to load "
        f"(entry point {entry_point}; implementation "
        f"{selected.spec.implementation}): {_exception_message(exc)}\n"
    )


def _render_execution_error(
    context: CommandContext,
    exc: BaseException,
) -> int:
    if isinstance(exc, CommandError):
        code = exc.exit_code
    elif isinstance(exc, SystemExit):
        code = 1
    elif isinstance(exc, Exception):
        code = _exit_code_for_exception(exc)
    else:
        code = 1
    if not context.quiet:
        context.stderr.write(f"{_exception_message(exc)}\n")
    return code


def _exit_code_for_exception(exc: Exception) -> int:
    from taut._exceptions import (
        EmptyResultError,
        IdentityError,
        MembershipError,
        NotFoundError,
        TokenError,
    )

    if isinstance(exc, TokenError):
        return 1
    if isinstance(exc, (EmptyResultError, NotFoundError, MembershipError)):
        return 2
    if isinstance(exc, IdentityError) and str(exc) == "unrecognized caller":
        return 2
    return 1


def _exception_message(exc: BaseException) -> str:
    if isinstance(exc, SystemExit):
        return f"SystemExit({exc.code!r})"
    return str(exc) or type(exc).__name__
