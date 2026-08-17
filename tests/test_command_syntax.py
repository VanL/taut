"""Shared command-syntax contract tests."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.shared


def test_channel_topic_mirror_parses_nested_path_quoted_text_and_clear() -> None:
    from taut.commands.syntax import (
        CommandInput,
        core_command_syntax,
        parse_command_line,
    )

    invocation = parse_command_line(
        CommandInput('channel topic general "focus the team" --json'),
        syntax=core_command_syntax(),
    )

    assert invocation.path == ("channel", "topic")
    assert invocation.values["channel"] == "general"
    assert invocation.values["topic"] == "focus the team"
    assert invocation.values["json"] is True

    cleared = parse_command_line(
        "channel topic general --clear",
        syntax=core_command_syntax(),
    )
    assert cleared.path == ("channel", "topic")
    assert cleared.values["channel"] == "general"
    assert cleared.values["clear"] is True
    assert "topic" not in cleared.values


def test_command_syntax_rejects_mutually_exclusive_topic_values() -> None:
    from taut.commands.syntax import (
        CommandSyntaxError,
        core_command_syntax,
        parse_command_line,
    )

    with pytest.raises(CommandSyntaxError, match="mutually exclusive"):
        parse_command_line(
            "channel topic general focus --clear",
            syntax=core_command_syntax(),
        )


def test_command_syntax_preserves_root_global_precedence_and_literal_separator() -> (
    None
):
    from taut.commands.syntax import core_command_syntax, parse_command_line

    invocation = parse_command_line(
        "--as van say general -- --json",
        syntax=core_command_syntax(),
    )

    assert invocation.path == ("say",)
    assert invocation.values["as_name"] == "van"
    assert invocation.values["target"] == "general"
    assert invocation.values["text"] == "--json"
    assert invocation.values["json"] is False


def test_command_syntax_supports_nested_debug_and_typed_options() -> None:
    from taut.commands.syntax import core_command_syntax, parse_command_line

    invocation = parse_command_line(
        "system debug enable --db workspace.db",
        syntax=core_command_syntax(),
    )

    assert invocation.path == ("system", "debug", "enable")
    assert invocation.values["db_path"] == "workspace.db"

    search = parse_command_line(
        "search --kind message --limit 12 one two",
        syntax=core_command_syntax(),
    )
    assert search.values["query"] == ["one", "two"]
    assert search.values["kind"] == ["message"]
    assert search.values["limit"] == 12

    rejoined = parse_command_line(
        "rejoin --token secret --json",
        syntax=core_command_syntax(),
    )
    assert rejoined.values["rejoin_token"] == "secret"
    assert rejoined.values["json"] is True


def test_command_syntax_exposes_native_root_and_command_help_actions() -> None:
    from taut.commands.syntax import core_command_syntax, parse_command_line

    assert (
        parse_command_line("--version", syntax=core_command_syntax()).action
        == "version"
    )
    assert (
        parse_command_line("channel --help", syntax=core_command_syntax()).action
        == "help"
    )
    assert parse_command_line(
        "channel topic --help", syntax=core_command_syntax()
    ).path == ("channel", "topic")


def test_syntax_provider_adds_summon_paths_without_cli_dispatch() -> None:
    from taut.commands.syntax import (
        CommandSyntax,
        CommandSyntaxProvider,
        PositionalSyntax,
        core_command_syntax,
        merge_command_syntax,
        parse_command_line,
    )

    summon = CommandSyntaxProvider(
        "fixture",
        "1",
        (CommandSyntax(("summon",), "fixture", (PositionalSyntax("name"),)),),
    )
    merged = merge_command_syntax(core_command_syntax(), (summon,))
    invocation = parse_command_line("summon grok", syntax=merged)
    assert invocation.path == ("summon",)
    assert invocation.values["name"] == "grok"


def test_syntax_provider_discovery_is_ordered_and_diagnosable() -> None:
    from taut.commands.syntax import (
        CommandSyntaxDiscovery,
        CommandSyntaxProvider,
        discover_command_syntax,
    )

    class EntryPoint:
        def __init__(self, name: str, value: object) -> None:
            self.name = name
            self.value = name
            self._value = value

        def load(self) -> object:
            if isinstance(self._value, BaseException):
                raise self._value
            return self._value

    first = CommandSyntaxProvider("a", "1", ())
    second = CommandSyntaxProvider("b", "1", ())
    result = discover_command_syntax(
        (
            EntryPoint("broken", RuntimeError("bad provider")),
            EntryPoint("second", lambda: second),
            EntryPoint("first", lambda: first),
        )
    )

    assert isinstance(result, CommandSyntaxDiscovery)
    assert tuple(provider.provider_name for provider in result.providers) == ("a", "b")
    assert result.diagnostics == ("syntax provider 'broken' unavailable: bad provider",)


@pytest.mark.parametrize(
    ("text", "path"),
    [
        ("init", ("init",)),
        ("join general --new", ("join",)),
        ("set name Van", ("set", "name")),
        ("say general hello", ("say",)),
        ("reply general 1234 hello", ("reply",)),
        ("message show 1234", ("message", "show")),
        ("message delete 1234", ("message", "delete")),
        ("message react 1234 thumbs-up", ("message", "react")),
        ("channel show general", ("channel", "show")),
        ("channel rename old new", ("channel", "rename")),
        ("read general", ("read",)),
        ("inbox", ("inbox",)),
        ("log general --limit 10", ("log",)),
        ("search one two", ("search",)),
        ("system dump --output backup.json", ("system", "dump")),
        ("system load --input backup.json --dry-run", ("system", "load")),
        ("system debug disable", ("system", "debug", "disable")),
        ("list --dms", ("list",)),
        ("watch general", ("watch",)),
        ("who general", ("who",)),
        ("whoami --explain", ("whoami",)),
        ("rejoin --token secret", ("rejoin",)),
    ],
)
def test_core_syntax_recognizes_every_released_command_path(
    text: str,
    path: tuple[str, ...],
) -> None:
    from taut.commands.syntax import core_command_syntax, parse_command_line

    assert parse_command_line(text, syntax=core_command_syntax()).path == path
