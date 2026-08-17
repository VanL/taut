"""Typed command syntax shared by CLI-compatible surface mirrors.

This module owns command shape, tokenization, and typed invocation values. It
does not import command adapters, Textual, or any execution owner.

Spec references:
- docs/specs/02-taut-core.md [TAUT-8.7]
"""

from __future__ import annotations

import shlex
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from importlib import metadata
from types import MappingProxyType


class ValueKind(StrEnum):
    """Surface-neutral value conversions used by the command grammar."""

    STRING = "string"
    INTEGER = "integer"
    PATH = "path"


CommandPath = tuple[str, ...]


@dataclass(frozen=True, slots=True)
class GlobalOptionSyntax:
    """One root option declaration, including its accepted spellings."""

    name: str
    spellings: tuple[str, ...]
    takes_value: bool = False
    value_kind: ValueKind = ValueKind.STRING

    def __post_init__(self) -> None:
        if not self.name or not self.spellings:
            raise ValueError("global option syntax needs a name and spelling")
        if any(not spelling.startswith("-") for spelling in self.spellings):
            raise ValueError("global option spellings must start with '-'")


@dataclass(frozen=True, slots=True)
class PositionalSyntax:
    """One positional value declaration."""

    name: str
    value_kind: ValueKind = ValueKind.STRING
    required: bool = True
    multiple: bool = False


@dataclass(frozen=True, slots=True)
class OptionSyntax:
    """One command-local option declaration."""

    name: str
    spellings: tuple[str, ...]
    takes_value: bool = False
    value_kind: ValueKind = ValueKind.STRING
    required: bool = False
    multiple: bool = False
    default: object | None = None
    choices: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.name or not self.spellings:
            raise ValueError("option syntax needs a name and spelling")
        if any(not spelling.startswith("-") for spelling in self.spellings):
            raise ValueError("option spellings must start with '-'")


@dataclass(frozen=True, slots=True)
class ExclusiveGroupSyntax:
    """Names that may not be present together."""

    names: tuple[str, ...]
    required: bool = False

    def __post_init__(self) -> None:
        if len(self.names) < 2:
            raise ValueError("an exclusive group needs at least two names")


@dataclass(frozen=True, slots=True)
class CommandSyntax:
    """A command node in the canonical syntax tree."""

    path: CommandPath
    summary: str
    positionals: tuple[PositionalSyntax, ...] = ()
    options: tuple[OptionSyntax, ...] = ()
    children: tuple[CommandSyntax, ...] = ()
    exclusive_groups: tuple[ExclusiveGroupSyntax, ...] = ()
    post_verb_globals: tuple[GlobalOptionSyntax, ...] = ()
    intermixed: bool = False
    accepts_remainder: bool = False

    def __post_init__(self) -> None:
        if not self.path or not all(self.path):
            raise ValueError("command syntax needs a nonempty path")
        child_paths = tuple(child.path for child in self.children)
        if len(set(child_paths)) != len(child_paths):
            raise ValueError(f"duplicate child syntax under {' '.join(self.path)}")


@dataclass(frozen=True, slots=True)
class RootCommandSyntax:
    """Root wrapper for globals, root actions, and top-level commands."""

    globals: tuple[GlobalOptionSyntax, ...]
    commands: tuple[CommandSyntax, ...]
    root_actions: tuple[str, ...] = ("help", "version")

    def __post_init__(self) -> None:
        paths = tuple(command.path for command in self.commands)
        if len(set(paths)) != len(paths):
            raise ValueError("duplicate root command syntax")


@dataclass(frozen=True, slots=True)
class CommandSyntaxProvider:
    """Versioned syntax-only contribution from an installed extension."""

    provider_name: str
    provider_version: str
    commands: tuple[CommandSyntax, ...]

    def __post_init__(self) -> None:
        if not self.provider_name or not self.provider_version:
            raise ValueError("syntax providers need stable name and version")


@dataclass(frozen=True, slots=True)
class CommandSyntaxDiscovery:
    """Immutable provider snapshot plus diagnosable load failures."""

    providers: tuple[CommandSyntaxProvider, ...]
    diagnostics: tuple[str, ...] = ()


def discover_command_syntax(
    entry_points: Iterable[object] | None = None,
) -> CommandSyntaxDiscovery:
    """Load installed syntax providers without loading command adapters."""

    discovered = (
        tuple(metadata.entry_points(group="taut.command_syntax"))
        if entry_points is None
        else tuple(entry_points)
    )
    providers: list[CommandSyntaxProvider] = []
    diagnostics: list[str] = []
    for entry_point in sorted(
        discovered,
        key=lambda item: (
            str(getattr(item, "name", "")),
            str(getattr(item, "value", "")),
        ),
    ):
        name = str(getattr(entry_point, "name", "unknown"))
        try:
            loaded = entry_point.load()  # type: ignore[attr-defined]
            provider = loaded() if callable(loaded) else loaded
            if not isinstance(provider, CommandSyntaxProvider):
                raise TypeError("provider did not return CommandSyntaxProvider")
            providers.append(provider)
        except Exception as exc:  # noqa: BLE001 approved [DOM-10.2.1] [RUFF-SUP-085] exception
            diagnostics.append(f"syntax provider {name!r} unavailable: {exc}")
    providers.sort(
        key=lambda provider: (provider.provider_name, provider.provider_version)
    )
    return CommandSyntaxDiscovery(tuple(providers), tuple(diagnostics))


def merge_command_syntax(
    base: RootCommandSyntax,
    providers: Iterable[CommandSyntaxProvider],
) -> RootCommandSyntax:
    """Merge syntax-only provider contributions deterministically."""

    additions: list[CommandSyntax] = []
    for provider in sorted(
        providers,
        key=lambda item: (item.provider_name, item.provider_version),
    ):
        additions.extend(provider.commands)
    commands = (*base.commands, *sorted(additions, key=lambda command: command.path))
    if len({command.path for command in commands}) != len(commands):
        raise CommandSyntaxError("duplicate command path in syntax providers")
    return RootCommandSyntax(base.globals, commands, base.root_actions)


@dataclass(frozen=True, slots=True)
class CommandInput:
    """Text entered after the TUI's leading ``:`` marker."""

    text: str


@dataclass(frozen=True, slots=True)
class CommandInvocation:
    """Typed result of parsing one command-language input."""

    path: CommandPath
    values: Mapping[str, object]
    source: CommandInput
    action: str | None = None


class CommandSyntaxError(ValueError):
    """A user-facing syntax error with a token position when available."""

    def __init__(self, message: str, *, token_index: int | None = None) -> None:
        super().__init__(message)
        self.token_index = token_index


def parse_command_line(
    command: CommandInput | str,
    *,
    syntax: RootCommandSyntax,
) -> CommandInvocation:
    """Parse one textual command into a typed invocation.

    ``syntax`` is explicit so callers can merge core and installed extension
    providers without this parser importing either command implementation.
    """

    source = command if isinstance(command, CommandInput) else CommandInput(command)
    tokens = _tokenize(source.text)
    if not tokens:
        raise CommandSyntaxError("enter a command", token_index=0)

    values: dict[str, object] = {
        option.name: False for option in syntax.globals if not option.takes_value
    }
    tokens, root_action = _extract_root_prefix(tokens, syntax.globals, values)
    if root_action is not None:
        return CommandInvocation(
            (), MappingProxyType(dict(values)), source, root_action
        )
    if not tokens:
        raise CommandSyntaxError("expected a command", token_index=0)

    command_node = _find_root_command(tokens[0], syntax.commands)
    if command_node is None:
        raise CommandSyntaxError(f"unknown command: {tokens[0]}", token_index=0)

    tokens = tokens[1:]
    tokens, post_values = _extract_post_globals(
        tokens,
        command_node.post_verb_globals,
        syntax.globals,
    )
    values.update(post_values)

    current = command_node
    while tokens and current.children:
        child = _find_child(tokens[0], current.children)
        if child is None:
            break
        current = child
        tokens = tokens[1:]

    # Command help is an action, not a requirement to supply the command's
    # normal positionals. It is still attached to the most specific path.
    action = next(
        (value for value in tokens if value in ("-h", "--help", "--version")),
        None,
    )
    if action is not None:
        return CommandInvocation(
            current.path,
            MappingProxyType(dict(values)),
            source,
            "help" if action != "--version" else "version",
        )

    parsed = _parse_node(tokens, current)
    values.update(parsed)
    return CommandInvocation(current.path, MappingProxyType(dict(values)), source)


def format_command_syntax(command: CommandSyntax) -> str:
    """Return a compact, deterministic syntax preview for a command node."""

    parts = [*command.path]
    for positional in command.positionals:
        token = positional.name.upper()
        if positional.multiple:
            token += "..."
        if not positional.required:
            token = f"[{token}]"
        parts.append(token)
    for option in command.options:
        spelling = next(
            (value for value in option.spellings if value.startswith("--")),
            option.spellings[0],
        )
        if option.takes_value:
            spelling += f" {option.name.upper()}"
        if not option.required:
            spelling = f"[{spelling}]"
        parts.append(spelling)
    if command.children:
        parts.append(
            "{" + "|".join(child.path[-1] for child in command.children) + "}"
        )
    return " ".join(parts)


def command_nodes(syntax: RootCommandSyntax) -> tuple[CommandSyntax, ...]:
    """Flatten syntax nodes in stable path order for completion and help."""

    result: list[CommandSyntax] = []

    def visit(node: CommandSyntax) -> None:
        result.append(node)
        for child in node.children:
            visit(child)

    for node in syntax.commands:
        visit(node)
    return tuple(sorted(result, key=lambda node: node.path))


def _tokenize(text: str) -> list[str]:
    lexer = shlex.shlex(text, posix=True)
    lexer.whitespace_split = True
    lexer.commenters = ""
    try:
        return list(lexer)
    except ValueError as exc:
        raise CommandSyntaxError(f"malformed quoting: {exc}") from exc


def _extract_root_prefix(
    tokens: list[str],
    declarations: Sequence[GlobalOptionSyntax],
    values: dict[str, object],
) -> tuple[list[str], str | None]:
    by_spelling = _spelling_map(declarations)
    remaining: list[str] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token == "--":
            remaining.extend(tokens[index:])
            break
        if token in ("-h", "--help"):
            return remaining + tokens[index + 1 :], "help"
        if token == "--version":
            return remaining + tokens[index + 1 :], "version"
        matched = _match_option(token, by_spelling)
        if matched is None:
            if token.startswith("-"):
                # A root-looking option before the command is never a
                # positional. The parser can give the same direct diagnostic
                # as the CLI root splitter without importing it.
                raise CommandSyntaxError(
                    f"unrecognized root option: {token}", token_index=index
                )
            remaining.extend(tokens[index:])
            break
        option, inline_value = matched
        consumed, value = _consume_declared_option(tokens, index, option, inline_value)
        _store_value(values, option.name, value, multiple=False)
        index += consumed
    return remaining, None


def _extract_post_globals(
    tokens: list[str],
    allowed: Sequence[GlobalOptionSyntax],
    all_globals: Sequence[GlobalOptionSyntax],
) -> tuple[list[str], dict[str, object]]:
    allowed_map = _spelling_map(allowed)
    all_map = _spelling_map(all_globals)
    values: dict[str, object] = {
        option.name: False for option in allowed if not option.takes_value
    }
    remaining: list[str] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token == "--":
            remaining.extend(tokens[index:])
            break
        matched = _match_option(token, allowed_map)
        if matched is not None:
            option, inline_value = matched
            consumed, value = _consume_declared_option(
                tokens, index, option, inline_value
            )
            _store_value(values, option.name, value, multiple=False)
            index += consumed
            continue
        all_match = _match_option(token, all_map)
        if token.startswith("--") and all_match is not None:
            # It is a known root option, but this command did not declare it
            # after the verb. Preserve it for the leaf parser, then continue
            # scanning so a later declared global is still extracted.
            known, inline_value = all_match
            remaining.append(token)
            if known.takes_value and inline_value is None:
                if index + 1 >= len(tokens):
                    raise CommandSyntaxError(
                        f"option {known.spellings[0]} expects a value",
                        token_index=index,
                    )
                remaining.append(tokens[index + 1])
                index += 2
            else:
                index += 1
            continue
        remaining.append(token)
        index += 1
    return remaining, values


def _parse_node(tokens: list[str], node: CommandSyntax) -> dict[str, object]:
    if node.children and not tokens:
        raise CommandSyntaxError(
            "choose a subcommand: "
            + ", ".join(child.path[-1] for child in node.children)
        )
    option_map = {
        spelling: option for option in node.options for spelling in option.spellings
    }
    values: dict[str, object] = {
        option.name: (
            list(option.default) if isinstance(option.default, list) else option.default
        )
        for option in node.options
        if option.default is not None
    }
    positional_tokens = _consume_node_options(tokens, option_map, values)
    _assign_positionals(positional_tokens, node, values)
    _validate_node(node, values)
    return values


def _consume_node_options(
    tokens: Sequence[str],
    option_map: Mapping[str, OptionSyntax],
    values: dict[str, object],
) -> list[str]:
    positional_tokens: list[str] = []
    literal = False
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token == "--" and not literal:
            literal = True
            index += 1
            continue
        if not literal and token.startswith("-") and token != "-":
            matched = _match_local_option(token, option_map)
            if matched is None:
                raise CommandSyntaxError(
                    f"unrecognized option: {token}", token_index=index
                )
            option, inline_value = matched
            consumed, value = _consume_declared_option(
                tokens, index, option, inline_value
            )
            _store_value(values, option.name, value, multiple=option.multiple)
            index += consumed
            continue
        positional_tokens.append(token)
        index += 1
    return positional_tokens


def _assign_positionals(
    positional_tokens: Sequence[str],
    node: CommandSyntax,
    values: dict[str, object],
) -> None:
    positional_index = 0
    for positional in node.positionals:
        raw_values, positional_index = _take_positional(
            positional_tokens, positional_index, positional
        )
        if positional.required and not raw_values:
            raise CommandSyntaxError(f"missing required value: {positional.name}")
        if positional.multiple:
            values[positional.name] = [
                _convert_value(value, positional.value_kind, positional.name)
                for value in raw_values
            ]
        elif raw_values:
            values[positional.name] = _convert_value(
                raw_values[0], positional.value_kind, positional.name
            )
    if positional_index < len(positional_tokens) and not node.accepts_remainder:
        raise CommandSyntaxError(
            f"unexpected value: {positional_tokens[positional_index]}"
        )
    if node.accepts_remainder:
        values["remainder"] = list(positional_tokens[positional_index:])


def _take_positional(
    tokens: Sequence[str],
    index: int,
    positional: PositionalSyntax,
) -> tuple[Sequence[str], int]:
    if positional.multiple:
        return tokens[index:], len(tokens)
    if index < len(tokens):
        return tokens[index : index + 1], index + 1
    return (), index


def _validate_node(node: CommandSyntax, values: Mapping[str, object]) -> None:
    for option in node.options:
        if option.required and option.name not in values:
            raise CommandSyntaxError(f"missing required option: {option.name}")
    for group in node.exclusive_groups:
        present = [name for name in group.names if name in values]
        if len(present) > 1:
            raise CommandSyntaxError(
                "arguments are mutually exclusive: " + ", ".join(present)
            )
        if group.required and not present:
            raise CommandSyntaxError(
                "one of these arguments is required: " + ", ".join(group.names)
            )


def _consume_declared_option(
    tokens: Sequence[str],
    index: int,
    option: GlobalOptionSyntax | OptionSyntax,
    inline_value: str | None,
) -> tuple[int, object]:
    if not option.takes_value:
        if inline_value is not None:
            raise CommandSyntaxError(
                f"option {option.spellings[0]} does not take a value",
                token_index=index,
            )
        return 1, True
    if inline_value is not None:
        return 1, _convert_option_value(inline_value, option)
    if index + 1 >= len(tokens):
        raise CommandSyntaxError(
            f"option {option.spellings[0]} expects a value", token_index=index
        )
    return 2, _convert_option_value(tokens[index + 1], option)


def _convert_option_value(
    value: str,
    option: GlobalOptionSyntax | OptionSyntax,
) -> object:
    converted = _convert_value(value, option.value_kind, option.name)
    if (
        isinstance(option, OptionSyntax)
        and option.choices
        and converted not in option.choices
    ):
        choices = ", ".join(option.choices)
        raise CommandSyntaxError(
            f"invalid choice for {option.name}: {value!r} (choose from {choices})"
        )
    return converted


def _convert_value(value: str, kind: ValueKind, name: str) -> object:
    if kind is ValueKind.INTEGER:
        try:
            return int(value)
        except ValueError as exc:
            raise CommandSyntaxError(f"{name} expects an integer") from exc
    return value


def _store_value(
    values: dict[str, object],
    name: str,
    value: object,
    *,
    multiple: bool,
) -> None:
    if multiple:
        stored = values.setdefault(name, [])
        if not isinstance(stored, list):
            raise TypeError(f"multiple option {name!r} has a non-list value")
        stored.append(value)
    else:
        values[name] = value


def _spelling_map(
    declarations: Iterable[GlobalOptionSyntax | OptionSyntax],
) -> dict[str, GlobalOptionSyntax | OptionSyntax]:
    result: dict[str, GlobalOptionSyntax | OptionSyntax] = {}
    for declaration in declarations:
        for spelling in declaration.spellings:
            if spelling in result:
                raise ValueError(f"duplicate option spelling: {spelling}")
            result[spelling] = declaration
    return result


def _match_option(
    token: str,
    declarations: Mapping[str, GlobalOptionSyntax | OptionSyntax],
) -> tuple[GlobalOptionSyntax | OptionSyntax, str | None] | None:
    spelling, separator, inline_value = token.partition("=")
    declaration = declarations.get(spelling)
    if declaration is None:
        return None
    return declaration, inline_value if separator else None


def _match_local_option(
    token: str,
    declarations: Mapping[str, OptionSyntax],
) -> tuple[OptionSyntax, str | None] | None:
    match = _match_option(token, declarations)
    if match is None:
        return None
    option, inline_value = match
    assert isinstance(option, OptionSyntax)
    return option, inline_value


def _find_root_command(
    name: str,
    commands: Sequence[CommandSyntax],
) -> CommandSyntax | None:
    return next((command for command in commands if command.path == (name,)), None)


def _find_child(name: str, children: Sequence[CommandSyntax]) -> CommandSyntax | None:
    return next((child for child in children if child.path[-1] == name), None)


def _global(
    name: str,
    *spellings: str,
    takes_value: bool = False,
    value_kind: ValueKind = ValueKind.STRING,
) -> GlobalOptionSyntax:
    return GlobalOptionSyntax(name, tuple(spellings), takes_value, value_kind)


def _option(
    name: str,
    *spellings: str,
    takes_value: bool = False,
    value_kind: ValueKind = ValueKind.STRING,
    required: bool = False,
    multiple: bool = False,
    default: object | None = None,
    choices: tuple[str, ...] = (),
) -> OptionSyntax:
    return OptionSyntax(
        name,
        tuple(spellings),
        takes_value,
        value_kind,
        required,
        multiple,
        default,
        choices,
    )


def _pos(
    name: str,
    *,
    required: bool = True,
    multiple: bool = False,
    value_kind: ValueKind = ValueKind.STRING,
) -> PositionalSyntax:
    return PositionalSyntax(name, value_kind, required, multiple)


def _node(
    path: CommandPath,
    summary: str,
    *,
    positionals: tuple[PositionalSyntax, ...] = (),
    options: tuple[OptionSyntax, ...] = (),
    children: tuple[CommandSyntax, ...] = (),
    exclusive_groups: tuple[ExclusiveGroupSyntax, ...] = (),
    post_verb_globals: tuple[GlobalOptionSyntax, ...] = (),
    intermixed: bool = False,
    accepts_remainder: bool = False,
) -> CommandSyntax:
    return CommandSyntax(
        path,
        summary,
        positionals,
        options,
        children,
        exclusive_groups,
        post_verb_globals,
        intermixed,
        accepts_remainder,
    )


def core_command_syntax() -> RootCommandSyntax:
    """Return the deterministic syntax tree for core and reserved roots."""

    db = _global("db_path", "--db", takes_value=True, value_kind=ValueKind.PATH)
    acting_as = _global("as_name", "--as", takes_value=True)
    token = _global("continuity_token", "--token", takes_value=True)
    json_output = _global("json", "--json")
    timestamps = _global("timestamps", "-t", "--timestamps")
    quiet = _global("quiet", "-q", "--quiet")
    common = (db, acting_as, token, json_output, timestamps, quiet)
    common_without_token = (db, acting_as, json_output, timestamps, quiet)
    system_globals = (db, json_output, quiet)
    channel_topic = _node(
        ("channel", "topic"),
        "Set or clear one channel topic.",
        positionals=(_pos("channel"), _pos("topic", required=False)),
        options=(_option("clear", "--clear"),),
        exclusive_groups=(ExclusiveGroupSyntax(("topic", "clear"), required=True),),
        post_verb_globals=common,
    )
    channel = _node(
        ("channel",),
        "Inspect or change one registered top-level channel.",
        children=(
            _node(
                ("channel", "show"),
                "Show current metadata for one top-level channel.",
                positionals=(_pos("channel"),),
                post_verb_globals=common,
            ),
            channel_topic,
            _node(
                ("channel", "rename"),
                "Rename a channel.",
                positionals=(_pos("old_name"), _pos("new_name")),
                post_verb_globals=common,
            ),
        ),
        post_verb_globals=common,
    )
    message = _node(
        ("message",),
        "Inspect, delete, or react to one exact message.",
        children=(
            _node(
                ("message", "show"),
                "Show one exact message.",
                positionals=(_pos("msg_id"),),
                post_verb_globals=common,
            ),
            _node(
                ("message", "delete"),
                "Delete one exact message.",
                positionals=(_pos("msg_id"),),
                post_verb_globals=common,
            ),
            _node(
                ("message", "react"),
                "React to one exact message.",
                positionals=(_pos("msg_id"), _pos("reaction")),
                post_verb_globals=common,
            ),
        ),
        post_verb_globals=common,
    )
    system = _node(
        ("system",),
        "Workspace maintenance and diagnosis.",
        children=(
            _node(
                ("system", "dump"),
                "Write a full-workspace backup.",
                options=(
                    _option(
                        "output",
                        "--output",
                        takes_value=True,
                        required=True,
                        value_kind=ValueKind.PATH,
                    ),
                ),
                post_verb_globals=system_globals,
            ),
            _node(
                ("system", "load"),
                "Preflight or restore a workspace backup.",
                options=(
                    _option(
                        "input",
                        "--input",
                        takes_value=True,
                        required=True,
                        value_kind=ValueKind.PATH,
                    ),
                    _option("dry_run", "--dry-run"),
                ),
                post_verb_globals=system_globals,
            ),
            _node(
                ("system", "doctor"),
                "Run passive workspace checks.",
                post_verb_globals=system_globals,
            ),
            _node(
                ("system", "debug"),
                "Enable or disable failure capture.",
                children=(
                    _node(
                        ("system", "debug", "enable"),
                        "Enable failure capture.",
                        post_verb_globals=system_globals,
                    ),
                    _node(
                        ("system", "debug", "disable"),
                        "Disable failure capture.",
                        post_verb_globals=system_globals,
                    ),
                ),
                post_verb_globals=system_globals,
            ),
        ),
        post_verb_globals=system_globals,
    )

    commands = (
        _node(("init",), "Initialize resolved Taut storage.", post_verb_globals=common),
        _node(
            ("join",),
            "Join a channel.",
            positionals=(_pos("thread"),),
            options=(
                _option("persona", "--persona", takes_value=True),
                _option("new", "--new"),
            ),
            post_verb_globals=common,
        ),
        _node(
            ("leave",),
            "Leave a joined thread.",
            positionals=(_pos("thread"),),
            post_verb_globals=common,
        ),
        _node(
            ("set",),
            "Change one acting-member property.",
            children=(
                _node(
                    ("set", "name"),
                    "Change display name.",
                    positionals=(_pos("name"),),
                    post_verb_globals=common,
                ),
            ),
            post_verb_globals=common,
        ),
        _node(
            ("say",),
            "Post text to a target.",
            positionals=(_pos("target"), _pos("text", required=False)),
            post_verb_globals=common,
        ),
        _node(
            ("reply",),
            "Reply to a message in a thread.",
            positionals=(_pos("thread"), _pos("msg_id"), _pos("text", required=False)),
            post_verb_globals=common,
        ),
        message,
        channel,
        _node(
            ("read",),
            "Read unread messages.",
            positionals=(_pos("thread", required=False),),
            post_verb_globals=common,
        ),
        _node(("inbox",), "Claim pending notifications.", post_verb_globals=common),
        _node(
            ("log",),
            "Show cursor-neutral history.",
            positionals=(_pos("thread"),),
            options=(
                _option("since", "--since", takes_value=True),
                _option(
                    "limit", "--limit", takes_value=True, value_kind=ValueKind.INTEGER
                ),
            ),
            post_verb_globals=common,
        ),
        _node(
            ("search",),
            "Search visible message history.",
            positionals=(_pos("query", multiple=True),),
            options=(
                _option(
                    "channel", "--channel", takes_value=True, multiple=True, default=[]
                ),
                _option("dm", "--dm", takes_value=True, multiple=True, default=[]),
                _option("dms", "--dms"),
                _option("from_member", "--from", takes_value=True),
                _option(
                    "kind",
                    "--kind",
                    takes_value=True,
                    multiple=True,
                    default=[],
                    choices=("message", "notice", "foreign"),
                ),
                _option("before", "--before", takes_value=True),
                _option(
                    "limit",
                    "--limit",
                    takes_value=True,
                    value_kind=ValueKind.INTEGER,
                    default=50,
                ),
                _option("reindex", "--reindex"),
            ),
            post_verb_globals=common,
            intermixed=True,
        ),
        system,
        _node(
            ("list",),
            "List joined or registered threads.",
            options=(
                _option("all_threads", "--all"),
                _option("dms", "--dms"),
            ),
            exclusive_groups=(ExclusiveGroupSyntax(("all_threads", "dms")),),
            post_verb_globals=common,
        ),
        _node(
            ("watch",),
            "Follow selected conversations.",
            positionals=(_pos("threads", required=False, multiple=True),),
            post_verb_globals=common,
        ),
        _node(
            ("who",),
            "Show members and presence.",
            positionals=(_pos("thread", required=False),),
            post_verb_globals=common,
        ),
        _node(
            ("whoami",),
            "Show the resolved identity.",
            options=(_option("explain", "--explain"),),
            post_verb_globals=common,
        ),
        _node(
            ("rejoin",),
            "Select an existing member.",
            positionals=(_pos("name_or_alias", required=False),),
            options=(_option("rejoin_token", "--token", takes_value=True),),
            post_verb_globals=common_without_token,
        ),
    )
    return RootCommandSyntax(common, commands)
